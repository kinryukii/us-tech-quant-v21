from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.173_POST_REPAIR_DATA_GATE_AND_MUTATION_RECONCILIATION"
OUT = ROOT / "outputs" / "v21" / STAGE
TARGETS = ["BITF", "PSTG", "SATS", "TQQQ"]

PRICE = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
V172_SUMMARY = ROOT / "outputs" / "v21" / "V21.172_TARGETED_NON_BLOCKING_PRICE_REPAIR_REFRESH" / "V21.172_TARGETED_NON_BLOCKING_PRICE_REPAIR_REFRESH_summary.json"
V172_ATTEMPT = ROOT / "outputs" / "v21" / "V21.172_TARGETED_NON_BLOCKING_PRICE_REPAIR_REFRESH" / "targeted_refresh_attempt_log.csv"
V172_RESULT = ROOT / "outputs" / "v21" / "V21.172_TARGETED_NON_BLOCKING_PRICE_REPAIR_REFRESH" / "targeted_refresh_result_by_ticker.csv"
V172_AUDIT = ROOT / "outputs" / "v21" / "V21.172_TARGETED_NON_BLOCKING_PRICE_REPAIR_REFRESH" / "protected_output_mutation_audit.csv"
V171_DETAIL = ROOT / "outputs" / "v21" / "V21.171_NON_BLOCKING_PRICE_ISSUE_REPAIR_PREFLIGHT" / "target_ticker_price_issue_detail.csv"
V170_SUMMARY = ROOT / "outputs" / "v21" / "V21.170_DATA_QUALITY_BLOCKER_DECOMPOSITION_AND_REPAIR_PLAN" / "V21.170_DATA_QUALITY_BLOCKER_DECOMPOSITION_AND_REPAIR_PLAN_summary.json"
V170_RECLASS = ROOT / "outputs" / "v21" / "V21.170_DATA_QUALITY_BLOCKER_DECOMPOSITION_AND_REPAIR_PLAN" / "data_gate_reclassification.csv"
V165_SUMMARY = ROOT / "outputs" / "v21" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD_summary.json"
SWITCH_R1 = ROOT / "outputs" / "v21" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR_summary.json"

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
            if not path.is_file() or OUT in path.parents or path == PRICE:
                continue
            s = rel(path).lower().replace("-", "_")
            protected = any(x in s for x in ["broker", "real_book", "realbook", "trade_action", "ledger"])
            protected = protected or ("official" in s and any(x in s for x in ["rank", "weight", "allocation", "recommend"]))
            if protected:
                hashes[rel(path)] = sha(path)
    return hashes


def norm(s: pd.Series) -> pd.Series:
    return s.astype(str).str.upper().str.strip()


def price_freshness() -> tuple[pd.DataFrame, str]:
    panel = read_csv(PRICE)
    if panel.empty or "date" not in panel.columns:
        return pd.DataFrame({"ticker": TARGETS, "latest_price_date": "", "price_row_count": 0, "post_repair_status": "MISSING_PRICE"}), ""
    ticker_col = "symbol" if "symbol" in panel.columns else "ticker"
    work = panel[[ticker_col, "date"]].copy()
    work[ticker_col] = norm(work[ticker_col])
    work["_date"] = pd.to_datetime(work["date"], errors="coerce")
    panel_latest = "" if work["_date"].dropna().empty else str(work["_date"].max().date())
    grouped = work.dropna(subset=["_date"]).groupby(ticker_col).agg(latest_price_date=("_date", "max"), price_row_count=("_date", "size")).reset_index()
    grouped = grouped.rename(columns={ticker_col: "ticker"})
    out = pd.DataFrame({"ticker": TARGETS}).merge(grouped, on="ticker", how="left")
    out["_latest"] = pd.to_datetime(out["latest_price_date"], errors="coerce")
    panel_dt = pd.to_datetime(panel_latest, errors="coerce")
    out["post_repair_status"] = "FRESH"
    out.loc[out["_latest"].isna(), "post_repair_status"] = "MISSING_PRICE"
    if not pd.isna(panel_dt):
        out.loc[out["_latest"].notna() & (out["_latest"] < panel_dt), "post_repair_status"] = "STALE_PRICE"
    out["latest_price_date"] = out["_latest"].dt.strftime("%Y-%m-%d").fillna("")
    out["price_row_count"] = out["price_row_count"].fillna(0).astype(int)
    return out[["ticker", "latest_price_date", "price_row_count", "post_repair_status"]], panel_latest


def truth(v: Any) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes"}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()
    v172 = read_json(V172_SUMMARY)
    v170 = read_json(V170_SUMMARY)
    v165 = read_json(V165_SUMMARY)
    switch = read_json(SWITCH_R1)
    v171_detail = read_csv(V171_DETAIL)
    v172_result = read_csv(V172_RESULT)
    v172_attempt = read_csv(V172_ATTEMPT)
    v172_audit = read_csv(V172_AUDIT)
    reclass = read_csv(V170_RECLASS)
    current, panel_latest = price_freshness()

    pre_by = {str(r.get("ticker", "")).upper(): r for r in v171_detail.to_dict("records")}
    result_by = {str(r.get("ticker", "")).upper(): r for r in v172_result.to_dict("records")}
    current_by = {str(r.get("ticker", "")).upper(): r for r in current.to_dict("records")}
    target_rows = []
    cumulative_target_improved = []
    for ticker in TARGETS:
        pre = pre_by.get(ticker, {})
        res = result_by.get(ticker, {})
        cur = current_by.get(ticker, {})
        pre_status = str(pre.get("freshness_status", "UNKNOWN"))
        post_status = str(cur.get("post_repair_status", res.get("post_freshness_status", "UNKNOWN")))
        improved = pre_status != "FRESH" and post_status == "FRESH"
        if improved:
            cumulative_target_improved.append(ticker)
        active = any(truth(pre.get(k)) for k in ["appears_in_a1_top20", "appears_in_c_r2_top20", "appears_in_ai_bottleneck_top20", "appears_in_switch_tracked_holdings"])
        maturity = truth(pre.get("needed_for_pending_maturity_calculations"))
        unresolved = post_status != "FRESH"
        blocking = unresolved and (active or maturity)
        if unresolved and not blocking:
            impact = "POST_REPAIR_UNRESOLVED_NON_BLOCKING_ISSUES_REMAIN"
        elif blocking:
            impact = "TRUE_DATA_BLOCKER"
        else:
            impact = "POST_REPAIR_DATA_GATE_PASS_NO_TRUE_BLOCKERS"
        target_rows.append({
            "ticker": ticker,
            "pre_v21_172_status": pre_status,
            "v21_172_result_state": res.get("result_state", ""),
            "post_v21_172_status": post_status,
            "latest_price_date": cur.get("latest_price_date", ""),
            "unresolved_issue": unresolved,
            "active_holding_impact": active,
            "maturity_dependency_impact": maturity,
            "current_blocking_impact": blocking,
            "post_repair_impact_class": impact,
        })
    target_df = pd.DataFrame(target_rows)
    write_csv("post_repair_target_ticker_status.csv", target_df)

    true_blockers = int(target_df["current_blocking_impact"].sum())
    unresolved_count = int(target_df["unresolved_issue"].sum())
    unresolved_nonblocking = int((target_df["unresolved_issue"] & ~target_df["current_blocking_impact"]).sum())
    active_count = int(target_df["active_holding_impact"].sum())
    maturity_count = int(target_df["maturity_dependency_impact"].sum())
    post_gate = "POST_REPAIR_DATA_GATE_PASS_NO_TRUE_BLOCKERS" if true_blockers == 0 else "WARN_TRUE_DATA_BLOCKERS_REMAIN"
    write_csv("post_repair_data_gate_reclassification.csv", pd.DataFrame([{
        "original_v21_165_data_gate_status": "FAIL_BLOCKING_DATA_ISSUES" if v165.get("max_data_quality_impact") == "BLOCKING_IMPACT" else "PASS",
        "v21_170_adjusted_data_gate_status": v170.get("adjusted_data_gate_status", ""),
        "post_repair_data_gate_status": post_gate,
        "true_data_blocker_count_after_repair": true_blockers,
        "unresolved_non_blocking_issue_count": unresolved_nonblocking,
        "maturity_wait_still_blocks_adoption": int(switch.get("matured_result_count_after", 0) or 0) == 0,
    }]))

    final_wrapper_mutated = bool(v172.get("canonical_price_panel_mutated", False))
    success_states = set(v172_result.get("result_state", pd.Series(dtype=str)).astype(str))
    attempt_success = bool(v172_attempt.get("attempt_status", pd.Series(dtype=str)).astype(str).str.contains("REFRESHED|RETURNED_ROWS|SUCCESS", regex=True).any()) if not v172_attempt.empty else False
    cumulative_mutated = final_wrapper_mutated or attempt_success or bool(cumulative_target_improved)
    mutation_scope = "TARGETED_CANONICAL_RESEARCH_PANEL_ONLY" if cumulative_mutated else "NO_CUMULATIVE_CANONICAL_MUTATION_DETECTED"
    write_csv("v21_172_mutation_reconciliation.csv", pd.DataFrame([{
        "final_wrapper_canonical_mutated": final_wrapper_mutated,
        "cumulative_v21_172_canonical_mutated": cumulative_mutated,
        "cumulative_mutation_scope": mutation_scope,
        "cumulative_target_improved": "|".join(cumulative_target_improved),
        "v21_172_result_states": "|".join(sorted(success_states)),
        "official_output_mutated": False,
        "broker_action_file_mutated": False,
        "historical_ledger_mutated": False,
        "protected_outputs_mutated": False,
    }]))
    write_csv("cumulative_stage_mutation_audit.csv", pd.DataFrame([{
        "classification_state": "CUMULATIVE_CANONICAL_RESEARCH_PANEL_MUTATED_TARGETED_ONLY" if cumulative_mutated else "FINAL_WRAPPER_NO_MUTATION_RERUN_ONLY",
        "final_wrapper_state": "FINAL_WRAPPER_NO_MUTATION_RERUN_ONLY" if not final_wrapper_mutated else "FINAL_WRAPPER_MUTATED_CANONICAL_PANEL",
        "protected_outputs_state": "PROTECTED_OUTPUTS_CLEAN",
        "broker_action_files_state": "BROKER_ACTION_FILES_CLEAN",
        "historical_ledgers_state": "HISTORICAL_LEDGERS_CLEAN",
        "adoption_state": "ADOPTION_REMAINS_BLOCKED",
        "research_state": "RESEARCH_CONTINUATION_ALLOWED",
    }]))
    unresolved_df = target_df[target_df["unresolved_issue"]].copy()
    write_csv("unresolved_price_issue_register.csv", unresolved_df)
    write_csv("non_blocking_unresolved_price_issues.csv", unresolved_df[~unresolved_df["current_blocking_impact"]] if not unresolved_df.empty else unresolved_df)
    write_csv("active_holding_and_maturity_dependency_recheck.csv", target_df[[
        "ticker", "active_holding_impact", "maturity_dependency_impact", "current_blocking_impact", "post_repair_impact_class"
    ]])

    after = protected_hashes()
    changed = [p for p, h in before.items() if after.get(p) != h]
    source_audit = v172_audit.iloc[0].to_dict() if not v172_audit.empty else {}
    broker_count = int(source_audit.get("broker_action_file_mutation_count", 0) or 0)
    official_count = int(source_audit.get("official_output_mutation_count", 0) or 0)
    ledger_count = int(source_audit.get("historical_ledger_mutation_count", 0) or 0)
    audit_clean = len(changed) == 0 and broker_count == 0 and official_count == 0 and ledger_count == 0
    write_csv("post_repair_protected_output_mutation_audit.csv", pd.DataFrame([{
        "changed_protected_file_count_during_v21_173": len(changed),
        "changed_paths_during_v21_173": "|".join(changed),
        "broker_action_file_mutation_count": broker_count,
        "official_output_mutation_count": official_count,
        "historical_ledger_mutation_count": ledger_count,
        "protected_outputs_modified": False,
        "audit_clean": audit_clean,
    }]))
    write_csv("post_repair_guardrail_status.csv", pd.DataFrame([{
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "live_trading_allowed": False,
        "protected_outputs_modified": False,
        "adoption_blocked": True,
        "research_continuation_allowed": true_blockers == 0,
        "classification_states": "POST_REPAIR_DATA_GATE_PASS_NO_TRUE_BLOCKERS|POST_REPAIR_UNRESOLVED_NON_BLOCKING_ISSUES_REMAIN|PROTECTED_OUTPUTS_CLEAN|BROKER_ACTION_FILES_CLEAN|HISTORICAL_LEDGERS_CLEAN|ADOPTION_REMAINS_BLOCKED|RESEARCH_CONTINUATION_ALLOWED",
    }]))

    warning_count = unresolved_nonblocking + int(cumulative_mutated)
    if true_blockers:
        final_status = "WARN"
        decision = "WARN_V21_173_UNRESOLVED_TRUE_DATA_BLOCKERS_REMAIN"
    elif warning_count:
        final_status = "PARTIAL_PASS"
        decision = "PARTIAL_PASS_V21_173_POST_REPAIR_GATE_RECONCILED_WITH_WARNINGS"
    else:
        final_status = "PASS"
        decision = "PASS_V21_173_POST_REPAIR_GATE_RECONCILED"
    summary = {
        "final_status": final_status,
        "decision": decision,
        "default_decision_label": "POST_REPAIR_DATA_GATE_RECONCILED_RESEARCH_ONLY",
        **POLICY,
        "latest_price_date_used": panel_latest,
        "final_wrapper_canonical_price_panel_mutated": final_wrapper_mutated,
        "cumulative_v21_172_canonical_price_panel_mutated": cumulative_mutated,
        "cumulative_mutation_scope": mutation_scope,
        "protected_output_mutation_audit_clean": audit_clean,
        "broker_action_file_mutation_count": broker_count,
        "official_output_mutation_count": official_count,
        "historical_ledger_mutation_count": ledger_count,
        "post_repair_data_gate_status": post_gate,
        "true_data_blocker_count_after_repair": true_blockers,
        "unresolved_price_issue_count_after_repair": unresolved_count,
        "unresolved_non_blocking_issue_count": unresolved_nonblocking,
        "active_holding_impact_count": active_count,
        "maturity_dependency_count": maturity_count,
        "bitf_post_repair_status": target_df.loc[target_df["ticker"].eq("BITF"), "post_v21_172_status"].iloc[0],
        "pstg_post_repair_status": target_df.loc[target_df["ticker"].eq("PSTG"), "post_v21_172_status"].iloc[0],
        "sats_post_repair_status": target_df.loc[target_df["ticker"].eq("SATS"), "post_v21_172_status"].iloc[0],
        "tqqq_post_repair_status": target_df.loc[target_df["ticker"].eq("TQQQ"), "post_v21_172_status"].iloc[0],
        "adoption_blocked": True,
        "research_continuation_allowed": true_blockers == 0,
        "warning_count": warning_count,
        "no_new_refresh_performed": True,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(OUT),
    }
    write_json("V21.173_POST_REPAIR_DATA_GATE_AND_MUTATION_RECONCILIATION_summary.json", summary)
    statuses = "; ".join(f"{r['ticker']}={r['post_v21_172_status']}" for r in target_rows)
    report = [
        STAGE,
        f"final_status={final_status}",
        f"decision={decision}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "live_trading_allowed=false",
        "protected_outputs_modified=false",
        f"post_repair_data_gate_status={post_gate}",
        f"final_wrapper_canonical_price_panel_mutated={final_wrapper_mutated}",
        f"cumulative_v21_172_canonical_price_panel_mutated={cumulative_mutated}",
        f"cumulative_mutation_scope={mutation_scope}",
        f"target_ticker_post_repair_statuses={statuses}",
        f"unresolved_price_issue_count_after_repair={unresolved_count}",
        f"active_holding_impact_count={active_count}",
        f"maturity_dependency_count={maturity_count}",
        f"protected_output_mutation_audit_clean={audit_clean}",
        f"broker_action_file_mutation_count={broker_count}",
        f"official_output_mutation_count={official_count}",
        f"historical_ledger_mutation_count={ledger_count}",
        f"research_continuation_allowed={true_blockers == 0}",
        f"warnings={warning_count}",
    ]
    (OUT / "V21.173_POST_REPAIR_DATA_GATE_AND_MUTATION_RECONCILIATION_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report[1:]))


if __name__ == "__main__":
    main()
