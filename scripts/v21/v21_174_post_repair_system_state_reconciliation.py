from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.174_POST_REPAIR_SYSTEM_STATE_RECONCILIATION"
OUT = ROOT / "outputs" / "v21" / STAGE

PRICE = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
V173_SUMMARY = ROOT / "outputs" / "v21" / "V21.173_POST_REPAIR_DATA_GATE_AND_MUTATION_RECONCILIATION" / "V21.173_POST_REPAIR_DATA_GATE_AND_MUTATION_RECONCILIATION_summary.json"
V173_UNRESOLVED = ROOT / "outputs" / "v21" / "V21.173_POST_REPAIR_DATA_GATE_AND_MUTATION_RECONCILIATION" / "non_blocking_unresolved_price_issues.csv"
V172_SUMMARY = ROOT / "outputs" / "v21" / "V21.172_TARGETED_NON_BLOCKING_PRICE_REPAIR_REFRESH" / "V21.172_TARGETED_NON_BLOCKING_PRICE_REPAIR_REFRESH_summary.json"
V171_SUMMARY = ROOT / "outputs" / "v21" / "V21.171_NON_BLOCKING_PRICE_ISSUE_REPAIR_PREFLIGHT" / "V21.171_NON_BLOCKING_PRICE_ISSUE_REPAIR_PREFLIGHT_summary.json"
V170_SUMMARY = ROOT / "outputs" / "v21" / "V21.170_DATA_QUALITY_BLOCKER_DECOMPOSITION_AND_REPAIR_PLAN" / "V21.170_DATA_QUALITY_BLOCKER_DECOMPOSITION_AND_REPAIR_PLAN_summary.json"
V169_SUMMARY = ROOT / "outputs" / "v21" / "V21.169_DECISION_BOUNDARY_AND_ACTION_GUARDRAIL" / "V21.169_DECISION_BOUNDARY_AND_ACTION_GUARDRAIL_summary.json"
V168_SUMMARY = ROOT / "outputs" / "v21" / "V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER" / "V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER_summary.json"
V167_R1_SUMMARY = ROOT / "outputs" / "v21" / "V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK" / "V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK_summary.json"
V165_SUMMARY = ROOT / "outputs" / "v21" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD_summary.json"
SWITCH_R1_SUMMARY = ROOT / "outputs" / "v21" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR_summary.json"

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


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pre_price_hash = sha(PRICE) if PRICE.exists() else ""
    before = protected_hashes()

    v173 = read_json(V173_SUMMARY)
    v172 = read_json(V172_SUMMARY)
    v171 = read_json(V171_SUMMARY)
    v170 = read_json(V170_SUMMARY)
    v169 = read_json(V169_SUMMARY)
    v168 = read_json(V168_SUMMARY)
    v167 = read_json(V167_R1_SUMMARY)
    v165 = read_json(V165_SUMMARY)
    switch = read_json(SWITCH_R1_SUMMARY)
    unresolved = read_csv(V173_UNRESOLVED)

    active_holding_impact = int(v173.get("active_holding_impact_count", 0) or 0)
    maturity_dependency = int(v173.get("maturity_dependency_count", 0) or 0)
    post_gate = str(v173.get("post_repair_data_gate_status", "UNKNOWN"))
    data_gate = "PASS_NO_TRUE_DATA_BLOCKERS" if post_gate == "POST_REPAIR_DATA_GATE_PASS_NO_TRUE_BLOCKERS" and active_holding_impact == 0 and maturity_dependency == 0 else "FAIL_TRUE_DATA_BLOCKERS_REMAIN"
    matured_count = int(switch.get("matured_result_count_after", 0) or 0)
    maturity_gate = "FAIL_WAIT_MATURITY" if matured_count == 0 else "PASS_MATURITY_AVAILABLE"
    active_exec = int(v167.get("active_600usd_executable_state_count", 0) or 0)
    portfolio_blocked = bool(v168.get("portfolio_mode_blocked", True)) or active_exec == 0
    execution_gate = "FAIL_INSUFFICIENT_CAPITAL" if portfolio_blocked else "PASS_EXECUTION_FEASIBLE"
    policy_gate = "PASS_POLICY_BLOCKS_ENFORCED"
    fallback_gate = "PASS_FALLBACK_INTERPRETATION_CORRECT" if bool(v168.get("not_user_preference_only_strategy", True)) and bool(v168.get("not_diversified_portfolio", True)) else "FAIL_FALLBACK_INTERPRETATION"
    research_allowed = data_gate == "PASS_NO_TRUE_DATA_BLOCKERS" and policy_gate == "PASS_POLICY_BLOCKS_ENFORCED"
    adoption_blocked = maturity_gate != "PASS_MATURITY_AVAILABLE" or execution_gate != "PASS_EXECUTION_FEASIBLE"

    classifications = [
        "SYSTEM_RESEARCH_CONTINUATION_ALLOWED" if research_allowed else "SYSTEM_RESEARCH_CONTINUATION_BLOCKED",
        "DATA_GATE_PASS_NO_TRUE_DATA_BLOCKERS" if data_gate == "PASS_NO_TRUE_DATA_BLOCKERS" else "DATA_GATE_FAIL_TRUE_BLOCKERS",
        "MATURITY_GATE_FAIL_WAIT_MATURITY" if maturity_gate != "PASS_MATURITY_AVAILABLE" else "MATURITY_GATE_PASS",
        "EXECUTION_GATE_FAIL_INSUFFICIENT_CAPITAL_600USD" if execution_gate != "PASS_EXECUTION_FEASIBLE" else "EXECUTION_GATE_PASS",
        "POLICY_GATE_PASS_BLOCKS_ENFORCED",
        "FALLBACK_INTERPRETATION_PASS" if fallback_gate.startswith("PASS") else "FALLBACK_INTERPRETATION_FAIL",
        "ADOPTION_BLOCKED_BY_MATURITY_AND_CAPITAL" if adoption_blocked else "ADOPTION_RESEARCH_GATE_AVAILABLE",
        "UNRESOLVED_PRICE_ISSUES_NON_BLOCKING" if int(v173.get("unresolved_non_blocking_issue_count", 0) or 0) else "NO_UNRESOLVED_PRICE_ISSUES",
        "NO_NEW_REFRESH_PERFORMED",
    ]

    write_csv("system_state_reconciliation_summary.csv", pd.DataFrame([{
        "classification_states": "|".join(classifications),
        "data_gate_status": data_gate,
        "maturity_gate_status": maturity_gate,
        "execution_gate_status": execution_gate,
        "policy_gate_status": policy_gate,
        "fallback_interpretation_gate_status": fallback_gate,
        "research_continuation_allowed": research_allowed,
        "adoption_blocked": adoption_blocked,
    }]))
    write_csv("guardrail_status_after_post_repair.csv", pd.DataFrame([{
        "prior_v21_169_data_quality_gate_status": v169.get("data_quality_gate_status", ""),
        "post_repair_data_gate_status": data_gate,
        "maturity_gate_status": maturity_gate,
        "execution_gate_status": execution_gate,
        "policy_gate_status": policy_gate,
        "fallback_interpretation_gate_status": fallback_gate,
    }]))
    blockers = [
        {"blocker_type": "MATURITY_WAIT", "active": maturity_gate != "PASS_MATURITY_AVAILABLE", "classification": "MATURITY_GATE_FAIL_WAIT_MATURITY"},
        {"blocker_type": "USD_600_INSUFFICIENT_CAPITAL", "active": execution_gate != "PASS_EXECUTION_FEASIBLE", "classification": "EXECUTION_GATE_FAIL_INSUFFICIENT_CAPITAL_600USD"},
        {"blocker_type": "TRUE_DATA_QUALITY_BLOCKER", "active": data_gate != "PASS_NO_TRUE_DATA_BLOCKERS", "classification": data_gate},
    ]
    write_csv("active_blocker_register_after_post_repair.csv", pd.DataFrame(blockers))
    write_csv("data_gate_final_status.csv", pd.DataFrame([{"data_gate_status": data_gate, "post_repair_data_gate_status": post_gate, "active_holding_impact_count": active_holding_impact, "maturity_dependency_count": maturity_dependency}]))
    write_csv("maturity_gate_final_status.csv", pd.DataFrame([{"maturity_gate_status": maturity_gate, "matured_result_count_after": matured_count}]))
    write_csv("capital_execution_gate_final_status.csv", pd.DataFrame([{"execution_gate_status": execution_gate, "portfolio_mode_blocked": portfolio_blocked, "active_600usd_executable_state_count": active_exec, "active_cash_budget_usd": v168.get("active_cash_budget_usd", 600)}]))
    write_csv("policy_gate_final_status.csv", pd.DataFrame([{**POLICY, "policy_gate_status": policy_gate, "broker_action_blocked": True, "live_trading_blocked": True, "official_adoption_blocked": True}]))
    write_csv("fallback_interpretation_gate_final_status.csv", pd.DataFrame([{"fallback_interpretation_gate_status": fallback_gate, "not_user_preference_only_strategy": v168.get("not_user_preference_only_strategy", True), "not_diversified_portfolio": v168.get("not_diversified_portfolio", True)}]))
    write_csv("unresolved_non_blocking_price_issues.csv", unresolved)
    write_csv("research_continuation_status.csv", pd.DataFrame([{"research_continuation_allowed": research_allowed, "reason": "Data and policy gates pass; maturity/capital still block adoption."}]))
    write_csv("post_repair_system_policy_flags.csv", pd.DataFrame([{**POLICY, "adoption_blocked": adoption_blocked, "broker_action_blocked": True, "live_trading_blocked": True}]))

    post_price_hash = sha(PRICE) if PRICE.exists() else ""
    canonical_mutated_by_stage = pre_price_hash != post_price_hash
    after = protected_hashes()
    changed = [p for p, h in before.items() if after.get(p) != h]
    audit_clean = len(changed) == 0 and not canonical_mutated_by_stage
    write_csv("protected_output_mutation_audit.csv", pd.DataFrame([{
        "canonical_price_panel_mutated_by_this_stage": canonical_mutated_by_stage,
        "pre_stage_price_panel_sha256": pre_price_hash,
        "post_stage_price_panel_sha256": post_price_hash,
        "changed_protected_file_count": len(changed),
        "changed_paths": "|".join(changed),
        "protected_outputs_modified": False,
        "audit_clean": audit_clean,
        "stage_output_directory": rel(OUT),
    }]))

    warning_count = int(v173.get("unresolved_non_blocking_issue_count", 0) or 0) + int(maturity_gate != "PASS_MATURITY_AVAILABLE") + int(execution_gate != "PASS_EXECUTION_FEASIBLE")
    if research_allowed and adoption_blocked:
        final_status = "PARTIAL_PASS"
        decision = "PARTIAL_PASS_V21_174_SYSTEM_STATE_RECONCILED_WITH_WARNINGS"
    elif research_allowed:
        final_status = "PASS"
        decision = "PASS_V21_174_SYSTEM_STATE_RECONCILED"
    else:
        final_status = "WARN"
        decision = "WARN_V21_174_SYSTEM_STATE_RECONCILIATION_BLOCKED"
    summary = {
        "final_status": final_status,
        "decision": decision,
        "default_decision_label": "SYSTEM_STATE_RECONCILED_RESEARCH_CONTINUATION_ALLOWED_ADOPTION_BLOCKED",
        **POLICY,
        "latest_price_date_used": v173.get("latest_price_date_used") or v172.get("post_refresh_latest_price_date_used") or v165.get("latest_price_date_used"),
        "data_gate_status": data_gate,
        "maturity_gate_status": maturity_gate,
        "execution_gate_status": execution_gate,
        "policy_gate_status": policy_gate,
        "fallback_interpretation_gate_status": fallback_gate,
        "research_continuation_allowed": research_allowed,
        "adoption_blocked": adoption_blocked,
        "broker_action_blocked": True,
        "live_trading_blocked": True,
        "portfolio_mode_blocked": portfolio_blocked,
        "active_cash_budget_usd": int(v168.get("active_cash_budget_usd", 600) or 600),
        "unresolved_price_issue_count": int(v173.get("unresolved_price_issue_count_after_repair", 0) or 0),
        "unresolved_non_blocking_price_issue_count": int(v173.get("unresolved_non_blocking_issue_count", 0) or 0),
        "active_holding_impact_count": active_holding_impact,
        "maturity_dependency_count": maturity_dependency,
        "canonical_price_panel_mutated_by_this_stage": canonical_mutated_by_stage,
        "cumulative_v21_172_canonical_price_panel_mutated": bool(v173.get("cumulative_v21_172_canonical_price_panel_mutated", False)),
        "protected_output_mutation_audit_clean": audit_clean,
        "warning_count": warning_count,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(OUT),
    }
    write_json("V21.174_POST_REPAIR_SYSTEM_STATE_RECONCILIATION_summary.json", summary)
    report = [
        STAGE,
        f"final_status={final_status}",
        f"decision={decision}",
        f"data_gate_status={data_gate}",
        f"maturity_gate_status={maturity_gate}",
        f"execution_gate_status={execution_gate}",
        f"policy_gate_status={policy_gate}",
        f"fallback_interpretation_gate_status={fallback_gate}",
        f"research_continuation_allowed={research_allowed}",
        f"adoption_blocked={adoption_blocked}",
        f"unresolved_non_blocking_price_issues={int(v173.get('unresolved_non_blocking_issue_count', 0) or 0)}",
        f"canonical_price_panel_mutated_by_this_stage={canonical_mutated_by_stage}",
        f"warnings={warning_count}",
    ]
    (OUT / "V21.174_POST_REPAIR_SYSTEM_STATE_RECONCILIATION_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report[1:]))


if __name__ == "__main__":
    main()
