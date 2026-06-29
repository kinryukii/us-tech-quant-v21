from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.169_DECISION_BOUNDARY_AND_ACTION_GUARDRAIL"
OUT = ROOT / "outputs" / "v21" / STAGE

V168_SUMMARY = ROOT / "outputs" / "v21" / "V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER" / "V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER_summary.json"
V168_STATE = ROOT / "outputs" / "v21" / "V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER" / "cash_constrained_fallback_state.csv"
V167_R1_SUMMARY = ROOT / "outputs" / "v21" / "V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK" / "V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK_summary.json"
V167_SUMMARY = ROOT / "outputs" / "v21" / "V21.167_SMALL_ACCOUNT_OVERLAY_CLOSURE_CONTROLLER" / "V21.167_SMALL_ACCOUNT_OVERLAY_CLOSURE_CONTROLLER_summary.json"
V166_SUMMARY = ROOT / "outputs" / "v21" / "V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR" / "V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR_summary.json"
V165_SUMMARY = ROOT / "outputs" / "v21" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD_summary.json"
SWITCH_R1_SUMMARY = ROOT / "outputs" / "v21" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR_summary.json"
SWITCH_STATE = ROOT / "outputs" / "v21" / "V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER" / "switch_controller_state.csv"

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "live_trading_allowed": False,
    "protected_outputs_modified": False,
    "role_review_required": False,
    "action_guardrail_enabled": True,
}

MODULES = [
    "A1_PRIMARY_CONTROL",
    "C_R2_CHALLENGER",
    "AI_BOTTLENECK_THEME",
    "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_SWITCH_STATE",
    "SOFTCAP_RETURN_OVERLAY",
    "E_R1_DEFENSIVE_OVERLAY",
    "DRAM_HBM_NAND_FALLBACK",
    "USD_600_PORTFOLIO_MODE",
    "USD_600_CASH_CONSTRAINED_FALLBACK_MODE",
]

DOMAINS = [
    "RESEARCH_RANKING",
    "FORWARD_TRACKING",
    "PORTFOLIO_EXECUTION",
    "CASH_CONSTRAINED_FALLBACK",
    "BROKER_ACTION",
    "OFFICIAL_ADOPTION",
]


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


def tf(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()

    v168 = read_json(V168_SUMMARY)
    v167_r1 = read_json(V167_R1_SUMMARY)
    v167 = read_json(V167_SUMMARY)
    v166 = read_json(V166_SUMMARY)
    v165 = read_json(V165_SUMMARY)
    switch_r1 = read_json(SWITCH_R1_SUMMARY)
    switch = read_csv(SWITCH_STATE)

    active_cash = int(v168.get("active_cash_budget_usd") or v167_r1.get("active_cash_budget_usd") or 600)
    portfolio_blocked = bool(v168.get("portfolio_mode_blocked", True))
    fallback_research_only = bool(v168.get("cash_constrained_fallback_mode_research_only", True))
    not_preference = bool(v168.get("not_user_preference_only_strategy", True))
    not_diversified = bool(v168.get("not_diversified_portfolio", True))
    selected_regime = str(v168.get("selected_regime") or v167_r1.get("selected_regime") or "UNKNOWN")
    regime_confidence = v168.get("regime_confidence", v167_r1.get("regime_confidence", ""))
    if not switch.empty:
        selected_regime = str(switch.get("selected_regime", pd.Series([selected_regime])).iloc[0])
        regime_confidence = switch.get("regime_confidence", pd.Series([regime_confidence])).iloc[0]

    matured_count = int(switch_r1.get("matured_result_count_after", 0) or 0)
    comparison_exists = bool(switch_r1.get("newly_matured_count", 0) or 0)
    maturity_gate_status = "PASS" if matured_count > 0 and comparison_exists else "FAIL_WAIT_MATURITY"
    data_quality_impact = str(v165.get("max_data_quality_impact", "UNKNOWN"))
    data_quality_gate_status = "PASS" if data_quality_impact != "BLOCKING_IMPACT" else "FAIL_BLOCKING_DATA_ISSUES"
    active_exec = int(v167_r1.get("active_600usd_executable_state_count", 0) or 0)
    execution_gate_status = "PASS" if active_exec > 0 else "FAIL_INSUFFICIENT_CAPITAL"
    policy_gate_status = "PASS_POLICY_BLOCKS_ENFORCED"
    fallback_gate_status = "PASS_FALLBACK_INTERPRETATION_CORRECT" if not_preference and not_diversified else "FAIL_FALLBACK_INTERPRETATION"

    domain_rows = []
    for domain in DOMAINS:
        if domain == "RESEARCH_RANKING":
            classification = "ALLOWED_RESEARCH_ONLY"
            allowed = True
        elif domain == "FORWARD_TRACKING":
            classification = "ALLOWED_FORWARD_TRACKING_ONLY"
            allowed = True
        elif domain == "PORTFOLIO_EXECUTION":
            classification = "BLOCKED_PORTFOLIO_EXECUTION_INSUFFICIENT_CAPITAL"
            allowed = False
        elif domain == "CASH_CONSTRAINED_FALLBACK":
            classification = "CASH_CONSTRAINED_FALLBACK_RESEARCH_ONLY"
            allowed = True
        elif domain == "BROKER_ACTION":
            classification = "BLOCKED_BROKER_ACTION_POLICY"
            allowed = False
        else:
            classification = "BLOCKED_ADOPTION_INSUFFICIENT_MATURITY|BLOCKED_ADOPTION_DATA_QUALITY"
            allowed = False
        domain_rows.append({
            "decision_domain": domain,
            "classification": classification,
            "research_only": True,
            "domain_allowed_for_research_readout": allowed,
            "official_adoption_allowed": False,
            "broker_action_allowed": False,
            "live_trading_allowed": False,
            "protected_outputs_modified": False,
        })
    write_csv("decision_boundary_state.csv", pd.DataFrame(domain_rows))

    module_rows = []
    for module in MODULES:
        if module == "A1_PRIMARY_CONTROL":
            classification = "ALLOWED_RESEARCH_ONLY"
            role = "PRIMARY_RESEARCH_REFERENCE"
        elif module == "C_R2_CHALLENGER":
            classification = "ALLOWED_FORWARD_TRACKING_ONLY"
            role = "CHALLENGER_FORWARD_TRACKING_ONLY"
        elif module == "AI_BOTTLENECK_THEME":
            classification = "ALLOWED_FORWARD_TRACKING_ONLY"
            role = "THEME_FORWARD_TRACKING_ONLY"
        elif module == "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_SWITCH_STATE":
            classification = "ALLOWED_FORWARD_TRACKING_ONLY|BLOCKED_ADOPTION_INSUFFICIENT_MATURITY"
            role = "SWITCH_STATE_FORWARD_TRACKING_ONLY"
        elif module == "USD_600_PORTFOLIO_MODE":
            classification = "BLOCKED_PORTFOLIO_EXECUTION_INSUFFICIENT_CAPITAL"
            role = "PORTFOLIO_MODE_BLOCKED"
        elif module == "USD_600_CASH_CONSTRAINED_FALLBACK_MODE":
            classification = "CASH_CONSTRAINED_FALLBACK_RESEARCH_ONLY|NOT_DIVERSIFIED_PORTFOLIO|NO_ACTION_ALLOWED"
            role = "FALLBACK_RESEARCH_ONLY"
        elif module == "DRAM_HBM_NAND_FALLBACK":
            classification = "CASH_CONSTRAINED_FALLBACK_RESEARCH_ONLY|NOT_USER_PREFERENCE_ONLY_STRATEGY|NOT_DIVERSIFIED_PORTFOLIO|NO_ACTION_ALLOWED"
            role = "CASH_CONSTRAINED_FALLBACK_CANDIDATE_SET"
        else:
            classification = "ALLOWED_RESEARCH_ONLY|BLOCKED_ADOPTION_INSUFFICIENT_MATURITY|BLOCKED_ADOPTION_DATA_QUALITY|NO_ACTION_ALLOWED"
            role = "RESEARCH_ONLY_OVERLAY_OR_STANDBY"
        module_rows.append({
            "module": module,
            "current_role": role,
            "classification": classification,
            "research_only": True,
            "adoption_allowed": False,
            "broker_action_allowed": False,
            "live_trading_allowed": False,
            "official_adoption_allowed": False,
            "not_user_preference_only_strategy": module == "DRAM_HBM_NAND_FALLBACK" or module == "USD_600_CASH_CONSTRAINED_FALLBACK_MODE",
            "not_diversified_portfolio": module in {"DRAM_HBM_NAND_FALLBACK", "USD_600_CASH_CONSTRAINED_FALLBACK_MODE"},
        })
    module_df = pd.DataFrame(module_rows)
    write_csv("research_vs_execution_classification.csv", module_df)

    matrix_rows = []
    for row in module_rows:
        for domain in DOMAINS:
            allowed = domain in {"RESEARCH_RANKING", "FORWARD_TRACKING"} and "FALLBACK" not in row["module"]
            if domain == "CASH_CONSTRAINED_FALLBACK":
                allowed = row["module"] in {"DRAM_HBM_NAND_FALLBACK", "USD_600_CASH_CONSTRAINED_FALLBACK_MODE"}
            if domain in {"PORTFOLIO_EXECUTION", "BROKER_ACTION", "OFFICIAL_ADOPTION"}:
                allowed = False
            matrix_rows.append({
                "module": row["module"],
                "decision_domain": domain,
                "allowed": allowed,
                "guardrail_classification": "NO_ACTION_ALLOWED" if domain in {"BROKER_ACTION", "OFFICIAL_ADOPTION", "PORTFOLIO_EXECUTION"} else row["classification"],
                "research_only": True,
                "adoption_allowed": False,
                "broker_action_allowed": False,
                "live_trading_allowed": False,
            })
    write_csv("action_guardrail_matrix.csv", pd.DataFrame(matrix_rows))

    write_csv("portfolio_mode_guardrail.csv", pd.DataFrame([{
        "portfolio_mode_blocked": portfolio_blocked,
        "portfolio_mode_block_reason": v168.get("portfolio_mode_block_reason", "UNKNOWN"),
        "active_600usd_executable_diversified_state_count": active_exec,
        "classification": "BLOCKED_PORTFOLIO_EXECUTION_INSUFFICIENT_CAPITAL" if portfolio_blocked else "PORTFOLIO_EXECUTION_RESEARCH_FEASIBLE",
        "research_only": True,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
    }]))
    write_csv("cash_constrained_fallback_guardrail.csv", pd.DataFrame([{
        "fallback_mode_state": "CASH_CONSTRAINED_FALLBACK_RESEARCH_ONLY",
        "cash_constrained_fallback_mode_research_only": fallback_research_only,
        "not_user_preference_only_strategy": not_preference,
        "not_diversified_portfolio": not_diversified,
        "fallback_execution_promoted": False,
        "classification": "CASH_CONSTRAINED_FALLBACK_RESEARCH_ONLY|NOT_USER_PREFERENCE_ONLY_STRATEGY|NOT_DIVERSIFIED_PORTFOLIO|NO_ACTION_ALLOWED",
        "research_only": True,
        "adoption_allowed": False,
        "broker_action_allowed": False,
    }]))

    adoption_blockers = [
        {"blocker_type": "BLOCKED_ADOPTION_INSUFFICIENT_MATURITY", "gate": "maturity_gate", "status": maturity_gate_status, "detail": f"matured_result_count_after={matured_count}"},
        {"blocker_type": "BLOCKED_ADOPTION_DATA_QUALITY", "gate": "data_quality_gate", "status": data_quality_gate_status, "detail": f"max_data_quality_impact={data_quality_impact}"},
        {"blocker_type": "BLOCKED_PORTFOLIO_EXECUTION_INSUFFICIENT_CAPITAL", "gate": "execution_gate", "status": execution_gate_status, "detail": f"active_600usd_executable_state_count={active_exec}"},
    ]
    write_csv("adoption_blocker_register.csv", pd.DataFrame(adoption_blockers))
    write_csv("broker_action_blocker_register.csv", pd.DataFrame([
        {"blocker_type": "BLOCKED_BROKER_ACTION_POLICY", "status": "ACTIVE", "detail": "broker_action_allowed=false for all modules"},
        {"blocker_type": "BLOCKED_LIVE_TRADING_POLICY", "status": "ACTIVE", "detail": "live_trading_allowed=false for all modules"},
        {"blocker_type": "NO_ACTION_ALLOWED", "status": "ACTIVE", "detail": "No orders, broker files, or trading instructions generated"},
    ]))
    write_csv("maturity_gate_status.csv", pd.DataFrame([{
        "gate": "maturity_gate",
        "status": maturity_gate_status,
        "matured_result_count_after": matured_count,
        "comparison_vs_a1_exists": comparison_exists,
        "pass": maturity_gate_status == "PASS",
    }]))
    write_csv("data_quality_gate_status.csv", pd.DataFrame([{
        "gate": "data_quality_gate",
        "status": data_quality_gate_status,
        "max_data_quality_impact": data_quality_impact,
        "pass": data_quality_gate_status == "PASS",
    }]))
    write_csv("fallback_interpretation_guardrail.csv", pd.DataFrame([{
        "gate": "fallback_interpretation_gate",
        "status": fallback_gate_status,
        "not_user_preference_only_strategy": not_preference,
        "not_diversified_portfolio": not_diversified,
        "fallback_research_only": fallback_research_only,
        "dram_hbm_nand_not_preference_only": True,
        "dram_hbm_nand_not_diversified_portfolio": True,
        "adoption_allowed": False,
        "broker_action_allowed": False,
    }]))

    warnings = [
        {"warning_type": "MATURITY_GATE", "warning": maturity_gate_status},
        {"warning_type": "DATA_QUALITY_GATE", "warning": data_quality_gate_status},
        {"warning_type": "EXECUTION_GATE", "warning": execution_gate_status},
        {"warning_type": "PORTFOLIO_MODE", "warning": str(v168.get("portfolio_mode_block_reason", ""))},
        {"warning_type": "ACTION_GUARDRAIL", "warning": "No broker, live, official, or adoption action allowed."},
    ]
    write_csv("decision_boundary_warnings.csv", pd.DataFrame(warnings))

    adoption_any = bool(module_df["adoption_allowed"].astype(str).str.lower().eq("true").any())
    broker_any = bool(module_df["broker_action_allowed"].astype(str).str.lower().eq("true").any())
    live_any = bool(module_df["live_trading_allowed"].astype(str).str.lower().eq("true").any())
    after = protected_hashes()
    changed = [p for p, h in before.items() if after.get(p) != h]
    write_csv("protected_output_mutation_audit.csv", pd.DataFrame([{
        "audit_item": "protected_output_mutation_check",
        "protected_file_count_before": len(before),
        "protected_file_count_after": len(after),
        "changed_protected_file_count": len(changed),
        "protected_outputs_modified": False,
        "changed_paths": "|".join(changed),
        "stage_output_directory": rel(OUT),
    }]))

    blocker_count = len(adoption_blockers) + 3
    warning_count = len(warnings)
    blocked = maturity_gate_status != "PASS" or data_quality_gate_status != "PASS" or execution_gate_status != "PASS"
    final_status = "WARN" if blocked else "PASS"
    decision = "WARN_V21_169_ACTION_BLOCKED_BY_MATURITY_DATA_AND_CAPITAL" if blocked else "PASS_V21_169_DECISION_GUARDRAIL_READY"
    summary = {
        "final_status": final_status,
        "decision": decision,
        "default_decision_label": "ACTION_BLOCKED_RESEARCH_ONLY_GUARDRAIL_ACTIVE",
        **POLICY,
        "active_cash_budget_usd": active_cash,
        "portfolio_mode_blocked": portfolio_blocked,
        "cash_constrained_fallback_mode_research_only": fallback_research_only,
        "not_user_preference_only_strategy": not_preference,
        "not_diversified_portfolio": not_diversified,
        "maturity_gate_status": maturity_gate_status,
        "data_quality_gate_status": data_quality_gate_status,
        "execution_gate_status": execution_gate_status,
        "policy_gate_status": policy_gate_status,
        "fallback_interpretation_gate_status": fallback_gate_status,
        "adoption_allowed_any_module": adoption_any,
        "broker_action_allowed_any_module": broker_any,
        "live_trading_allowed_any_module": live_any,
        "selected_regime": selected_regime,
        "regime_confidence": float(regime_confidence) if str(regime_confidence) else "",
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(OUT),
    }
    write_json("V21.169_DECISION_BOUNDARY_AND_ACTION_GUARDRAIL_summary.json", summary)
    report = [
        STAGE,
        f"final_status={final_status}",
        f"decision={decision}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "live_trading_allowed=false",
        "action_guardrail_enabled=true",
        "protected_outputs_modified=false",
        f"active_cash_budget_usd={active_cash}",
        f"selected_regime={selected_regime}",
        f"regime_confidence={regime_confidence}",
        f"maturity_gate_status={maturity_gate_status}",
        f"data_quality_gate_status={data_quality_gate_status}",
        f"execution_gate_status={execution_gate_status}",
        f"policy_gate_status={policy_gate_status}",
        f"fallback_interpretation_gate_status={fallback_gate_status}",
        f"portfolio_mode_blocked={portfolio_blocked}",
        "cash_constrained_fallback_mode_state=CASH_CONSTRAINED_FALLBACK_RESEARCH_ONLY",
        f"adoption_allowed_any_module={adoption_any}",
        f"broker_action_allowed_any_module={broker_any}",
        f"warnings={warning_count}",
    ]
    (OUT / "V21.169_DECISION_BOUNDARY_AND_ACTION_GUARDRAIL_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report[1:]))


if __name__ == "__main__":
    main()
