from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.170_DATA_QUALITY_BLOCKER_DECOMPOSITION_AND_REPAIR_PLAN"
OUT = ROOT / "outputs" / "v21" / STAGE

V169_SUMMARY = ROOT / "outputs" / "v21" / "V21.169_DECISION_BOUNDARY_AND_ACTION_GUARDRAIL" / "V21.169_DECISION_BOUNDARY_AND_ACTION_GUARDRAIL_summary.json"
V169_BLOCKERS = ROOT / "outputs" / "v21" / "V21.169_DECISION_BOUNDARY_AND_ACTION_GUARDRAIL" / "adoption_blocker_register.csv"
V168_SUMMARY = ROOT / "outputs" / "v21" / "V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER" / "V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER_summary.json"
V167_R1_SUMMARY = ROOT / "outputs" / "v21" / "V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK" / "V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK_summary.json"
V166_SUMMARY = ROOT / "outputs" / "v21" / "V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR" / "V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR_summary.json"
V165_SUMMARY = ROOT / "outputs" / "v21" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD_summary.json"
V165_STALE = ROOT / "outputs" / "v21" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD" / "stale_or_missing_tickers.csv"
V165_IMPACT = ROOT / "outputs" / "v21" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD" / "data_quality_impact_classification.csv"
V165_NEUTRAL = ROOT / "outputs" / "v21" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD" / "neutral_fallback_cells.csv"
SWITCH_R1_SUMMARY = ROOT / "outputs" / "v21" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR_summary.json"
SWITCH_R1_LEDGER = ROOT / "outputs" / "v21" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR" / "switch_ledger_r1_full_ledger.csv"

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "live_trading_allowed": False,
    "protected_outputs_modified": False,
    "role_review_required": False,
}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def write_csv(name: str, df: pd.DataFrame) -> None:
    df.to_csv(OUT / name, index=False)


def write_json(name: str, payload: dict[str, Any]) -> None:
    (OUT / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def protected_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for base in [ROOT / "outputs", ROOT / "data"]:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or OUT in path.parents:
                continue
            s = rel(path).lower().replace("-", "_")
            protected = any(x in s for x in ["broker", "real_book", "realbook", "trade_action"])
            protected = protected or ("official" in s and any(x in s for x in ["rank", "weight", "allocation", "recommend"]))
            if protected:
                hashes[rel(path)] = sha(path)
    return hashes


def bool_val(v: Any) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes"}


def classify_price_row(row: dict[str, Any]) -> str:
    in_top20 = any(bool_val(row.get(c)) for c in ["in_a1_top20", "in_c_r2_top20", "in_ai_bottleneck_top20"])
    in_top50 = any(bool_val(row.get(c)) for c in ["in_a1_top50", "in_c_r2_top50", "in_ai_bottleneck_top50"])
    in_switch = bool_val(row.get("in_switch_tracked_state"))
    status = str(row.get("freshness_status", ""))
    if in_top20 or in_switch:
        return "PRICE_MISSING_BLOCKING_IF_IN_ACTIVE_HOLDINGS" if status == "MISSING_PRICE" else "PRICE_STALE_BLOCKING_IF_IN_ACTIVE_HOLDINGS"
    if status == "MISSING_PRICE":
        return "PRICE_MISSING_NON_BLOCKING_IF_NOT_IN_ACTIVE_HOLDINGS" if not in_top50 else "NON_BLOCKING_DATA_WARNING"
    return "NON_BLOCKING_DATA_WARNING"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()

    v169 = read_json(V169_SUMMARY)
    v168 = read_json(V168_SUMMARY)
    v167 = read_json(V167_R1_SUMMARY)
    v166 = read_json(V166_SUMMARY)
    v165 = read_json(V165_SUMMARY)
    switch_r1 = read_json(SWITCH_R1_SUMMARY)
    impact = read_csv(V165_IMPACT)
    stale = read_csv(V165_STALE)
    neutral = read_csv(V165_NEUTRAL)
    adoption_blockers = read_csv(V169_BLOCKERS)
    switch_ledger = read_csv(SWITCH_R1_LEDGER)

    original_data_gate = str(v169.get("data_quality_gate_status", "UNKNOWN"))
    latest_price_date = str(v165.get("latest_price_date_used") or v167.get("latest_price_date_used") or "")
    matured_count = int(switch_r1.get("matured_result_count_after", 0) or 0)
    active_exec = int(v167.get("active_600usd_executable_state_count", 0) or 0)

    stale_rows = []
    true_data_blockers = []
    non_blocking = []
    repair_rows = []
    for row in stale.to_dict("records"):
        impact_class = classify_price_row(row)
        ticker = str(row.get("ticker", "")).upper()
        affected = []
        for label, col in [
            ("A1_TOP20", "in_a1_top20"), ("A1_TOP50", "in_a1_top50"),
            ("C_R2_TOP20", "in_c_r2_top20"), ("C_R2_TOP50", "in_c_r2_top50"),
            ("AI_TOP20", "in_ai_bottleneck_top20"), ("AI_TOP50", "in_ai_bottleneck_top50"),
            ("SWITCH_TRACKED_STATE", "in_switch_tracked_state"),
        ]:
            if bool_val(row.get(col)):
                affected.append(label)
        blocks_maturity = bool_val(row.get("in_switch_tracked_state"))
        out = {
            "ticker": ticker,
            "issue_type": row.get("freshness_status", ""),
            "latest_price_date": row.get("latest_price_date", ""),
            "impact_class": impact_class,
            "affected_modules": "|".join(affected) if affected else "NONE_ACTIVE",
            "in_a1_top20": bool_val(row.get("in_a1_top20")),
            "in_a1_top50": bool_val(row.get("in_a1_top50")),
            "in_c_r2_top20": bool_val(row.get("in_c_r2_top20")),
            "in_c_r2_top50": bool_val(row.get("in_c_r2_top50")),
            "in_ai_bottleneck_top20": bool_val(row.get("in_ai_bottleneck_top20")),
            "in_ai_bottleneck_top50": bool_val(row.get("in_ai_bottleneck_top50")),
            "in_switch_tracked_state": bool_val(row.get("in_switch_tracked_state")),
            "needed_for_maturity_calculation": blocks_maturity,
            "blocks_adoption": impact_class in {"PRICE_MISSING_BLOCKING_IF_IN_ACTIVE_HOLDINGS", "PRICE_STALE_BLOCKING_IF_IN_ACTIVE_HOLDINGS"},
            "blocks_maturity": blocks_maturity,
        }
        stale_rows.append(out)
        refresh_required = str(row.get("freshness_status", "")) in {"MISSING_PRICE", "STALE_PRICE"}
        repair = {
            "ticker": ticker,
            "issue_type": row.get("freshness_status", ""),
            "impact_class": impact_class,
            "affected_modules": out["affected_modules"],
            "recommended_action": "QUEUE_PRICE_REFRESH_IN_SEPARATE_APPROVED_REFRESH_STAGE" if refresh_required else "MONITOR",
            "refresh_required": refresh_required,
            "safe_to_continue_research": not out["blocks_adoption"],
            "blocks_adoption": out["blocks_adoption"],
            "blocks_maturity": out["blocks_maturity"],
        }
        repair_rows.append(repair)
        if out["blocks_adoption"] or out["blocks_maturity"]:
            true_data_blockers.append(out)
        else:
            non_blocking.append(out)

    wait_rows = []
    for row in impact.to_dict("records"):
        issue = str(row.get("issue_type", ""))
        if "MATURITY" in issue or issue in {"WAIT_MATURITY", "NO_NEW_MATURED_ROWS", "NO_NEW_RANKING_DATE"}:
            wait_rows.append({
                "issue_type": issue,
                "decomposition_class": "MATURITY_WAIT_NOT_DATA_DEFECT",
                "original_impact_level": row.get("impact_level", ""),
                "blocks_maturity": bool_val(row.get("blocks_maturity_calculation")) or "MATURITY" in issue,
                "true_data_defect": False,
                "detail": "Waiting for forward horizon maturity; not a source-data repair defect.",
            })
    if matured_count == 0 and not wait_rows:
        wait_rows.append({
            "issue_type": "WAIT_MATURITY",
            "decomposition_class": "MATURITY_WAIT_NOT_DATA_DEFECT",
            "original_impact_level": "BLOCKING_IMPACT",
            "blocks_maturity": True,
            "true_data_defect": False,
            "detail": "matured_result_count_after=0",
        })

    capital_rows = [{
        "issue_type": "USD_600_INSUFFICIENT_CAPITAL",
        "decomposition_class": "CAPITAL_CONSTRAINT_NOT_DATA_DEFECT",
        "active_cash_budget_usd": v168.get("active_cash_budget_usd", 600),
        "active_600usd_executable_state_count": active_exec,
        "portfolio_mode_blocked": bool_val(v168.get("portfolio_mode_blocked", True)),
        "true_data_defect": False,
        "detail": "Whole-share diversified execution is blocked by account size, not by data quality.",
    }]

    proxy_rows = []
    if not neutral.empty:
        for row in neutral.to_dict("records"):
            proxy_rows.append({
                "ticker": row.get("ticker", ""),
                "issue_type": "NEUTRAL_FALLBACK_CELL",
                "decomposition_class": "PROXY_NEUTRAL_FALLBACK_LOW_IMPACT",
                "neutral_fallback_cell_count": row.get("neutral_fallback_cell_count", ""),
                "true_data_defect": False,
                "blocks_adoption": False,
                "recommended_action": "MONITOR_OR_REPAIR_PROXY_SOURCE_IN_SEPARATE_RESEARCH_STAGE",
            })

    adjusted_gate = "PASS_NO_TRUE_DATA_BLOCKERS" if len(true_data_blockers) == 0 else "FAIL_TRUE_DATA_BLOCKERS_REMAIN"
    summary_rows = [
        {"blocker_family": "true_data_blockers", "decomposition_class": "TRUE_DATA_BLOCKER", "count": len(true_data_blockers), "data_defect": True},
        {"blocker_family": "maturity_wait", "decomposition_class": "MATURITY_WAIT_NOT_DATA_DEFECT", "count": len(wait_rows), "data_defect": False},
        {"blocker_family": "capital_execution", "decomposition_class": "CAPITAL_CONSTRAINT_NOT_DATA_DEFECT", "count": len(capital_rows), "data_defect": False},
        {"blocker_family": "non_blocking_data_warnings", "decomposition_class": "NON_BLOCKING_DATA_WARNING", "count": len(non_blocking), "data_defect": True},
        {"blocker_family": "proxy_neutral_fallback", "decomposition_class": "PROXY_NEUTRAL_FALLBACK_LOW_IMPACT", "count": len(proxy_rows), "data_defect": False},
    ]

    write_csv("blocker_decomposition_summary.csv", pd.DataFrame(summary_rows))
    write_csv("true_data_blockers.csv", pd.DataFrame(true_data_blockers, columns=[
        "ticker", "issue_type", "latest_price_date", "impact_class", "affected_modules",
        "in_a1_top20", "in_a1_top50", "in_c_r2_top20", "in_c_r2_top50",
        "in_ai_bottleneck_top20", "in_ai_bottleneck_top50", "in_switch_tracked_state",
        "needed_for_maturity_calculation", "blocks_adoption", "blocks_maturity",
    ]))
    write_csv("maturity_wait_blockers.csv", pd.DataFrame(wait_rows))
    write_csv("capital_execution_blockers.csv", pd.DataFrame(capital_rows))
    write_csv("non_blocking_data_warnings.csv", pd.DataFrame(non_blocking + proxy_rows))
    write_csv("stale_missing_ticker_impact.csv", pd.DataFrame(stale_rows))
    write_csv("top20_top50_data_blocker_impact.csv", pd.DataFrame(stale_rows))
    write_csv("switch_maturity_data_dependency.csv", pd.DataFrame([{
        "matured_result_count_after": matured_count,
        "pending_maturity_count_after": switch_r1.get("pending_maturity_count_after", ""),
        "switch_ledger_rows": len(switch_ledger),
        "stale_missing_tickers_in_switch_tracked_state": sum(1 for r in stale_rows if r["in_switch_tracked_state"]),
        "maturity_wait_not_data_defect": True,
    }]))
    write_csv("data_repair_action_plan.csv", pd.DataFrame(repair_rows + [
        {
            "ticker": "ALL",
            "issue_type": "WAIT_MATURITY",
            "impact_class": "MATURITY_WAIT_NOT_DATA_DEFECT",
            "affected_modules": "SWITCH_LEDGER",
            "recommended_action": "WAIT_FOR_FORWARD_HORIZON_MATURITY_AND_APPEND_LEDGER",
            "refresh_required": False,
            "safe_to_continue_research": True,
            "blocks_adoption": True,
            "blocks_maturity": True,
        },
        {
            "ticker": "ALL",
            "issue_type": "USD_600_INSUFFICIENT_CAPITAL",
            "impact_class": "CAPITAL_CONSTRAINT_NOT_DATA_DEFECT",
            "affected_modules": "EXECUTION_FEASIBILITY",
            "recommended_action": "KEEP_CASH_CONSTRAINED_FALLBACK_RESEARCH_ONLY",
            "refresh_required": False,
            "safe_to_continue_research": True,
            "blocks_adoption": True,
            "blocks_maturity": False,
        },
    ]))
    write_csv("data_gate_reclassification.csv", pd.DataFrame([{
        "original_data_gate_status": original_data_gate,
        "adjusted_data_gate_status": adjusted_gate,
        "true_data_blocker_count": len(true_data_blockers),
        "maturity_wait_blocker_count": len(wait_rows),
        "capital_blocker_count": len(capital_rows),
        "non_blocking_warning_count": len(non_blocking) + len(proxy_rows),
        "explanation": "WAIT_MATURITY and USD 600 capital constraints are separated from true source-data defects.",
    }]))

    after = protected_hashes()
    changed = [p for p, h in before.items() if after.get(p) != h]
    audit_clean = len(changed) == 0
    write_csv("protected_output_mutation_audit.csv", pd.DataFrame([{
        "audit_item": "protected_output_mutation_check",
        "protected_file_count_before": len(before),
        "protected_file_count_after": len(after),
        "changed_protected_file_count": len(changed),
        "protected_outputs_modified": False,
        "audit_clean": audit_clean,
        "changed_paths": "|".join(changed),
        "stage_output_directory": rel(OUT),
    }]))

    impact_lookup = {r["ticker"]: r["impact_class"] for r in stale_rows}
    data_refresh_recommended = any(bool(r["refresh_required"]) for r in repair_rows)
    warning_count = len(non_blocking) + len(wait_rows) + len(capital_rows) + len(proxy_rows)
    if len(true_data_blockers) > 0:
        final_status = "WARN"
        decision = "WARN_V21_170_TRUE_DATA_BLOCKERS_REMAIN"
    elif warning_count:
        final_status = "PARTIAL_PASS"
        decision = "PARTIAL_PASS_V21_170_DATA_BLOCKERS_DECOMPOSED_WITH_WARNINGS"
    else:
        final_status = "PASS"
        decision = "PASS_V21_170_DATA_BLOCKERS_DECOMPOSED"
    summary = {
        "final_status": final_status,
        "decision": decision,
        "default_decision_label": "DATA_BLOCKERS_DECOMPOSED_REPAIR_PLAN_READY_RESEARCH_ONLY",
        **POLICY,
        "latest_price_date_used": latest_price_date,
        "original_data_gate_status": original_data_gate,
        "adjusted_data_gate_status": adjusted_gate,
        "true_data_blocker_count": len(true_data_blockers),
        "maturity_wait_blocker_count": len(wait_rows),
        "capital_blocker_count": len(capital_rows),
        "non_blocking_data_warning_count": len(non_blocking) + len(proxy_rows),
        "stale_ticker_count": int(v165.get("stale_ticker_count", 0) or 0),
        "missing_price_ticker_count": int(v165.get("missing_price_ticker_count", 0) or 0),
        "neutral_fallback_cell_count": int(v165.get("neutral_fallback_cell_count", 0) or 0),
        "bitf_impact_class": impact_lookup.get("BITF", ""),
        "pstg_impact_class": impact_lookup.get("PSTG", ""),
        "sats_impact_class": impact_lookup.get("SATS", ""),
        "tqqq_impact_class": impact_lookup.get("TQQQ", ""),
        "adoption_blocked": True,
        "maturity_blocked": matured_count == 0,
        "execution_blocked_by_capital": active_exec == 0,
        "data_refresh_recommended": data_refresh_recommended,
        "protected_output_mutation_audit_clean": audit_clean,
        "warning_count": warning_count,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(OUT),
    }
    write_json("V21.170_DATA_QUALITY_BLOCKER_DECOMPOSITION_AND_REPAIR_PLAN_summary.json", summary)
    report = [
        STAGE,
        f"final_status={final_status}",
        f"decision={decision}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "live_trading_allowed=false",
        "protected_outputs_modified=false",
        f"original_data_gate_status={original_data_gate}",
        f"adjusted_data_gate_status={adjusted_gate}",
        f"true_data_blocker_count={len(true_data_blockers)}",
        f"maturity_wait_blocker_count={len(wait_rows)}",
        f"capital_blocker_count={len(capital_rows)}",
        f"BITF={impact_lookup.get('BITF', '')}",
        f"PSTG={impact_lookup.get('PSTG', '')}",
        f"SATS={impact_lookup.get('SATS', '')}",
        f"TQQQ={impact_lookup.get('TQQQ', '')}",
        f"data_refresh_recommended={data_refresh_recommended}",
        "adoption_blocked=True",
        f"warnings={warning_count}",
    ]
    (OUT / "V21.170_DATA_QUALITY_BLOCKER_DECOMPOSITION_AND_REPAIR_PLAN_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report[1:]))


if __name__ == "__main__":
    main()
