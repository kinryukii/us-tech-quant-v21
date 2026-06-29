from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


STAGE = "V21.155_CONDITIONAL_STRATEGY_SWITCHING_STATE_MACHINE_AND_D_REENTRY_GATE"
OUT = Path("outputs/v21/V21.155_CONDITIONAL_STRATEGY_SWITCHING_STATE_MACHINE_AND_D_REENTRY_GATE")

INPUTS = {
    "V21.128": Path("outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/V21.128_summary.json"),
    "V21.153_R2": Path("outputs/v21/V21.153_R2_SOFTCAP_RETURN_VS_RISK_ATTRIBUTION/compact_readable_report.txt"),
    "V21.154": Path("outputs/v21/V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT/V21.154_machine_summary.json"),
}

FLAGS = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "current_primary_control_unchanged": True,
    "D_permanent_ban": False,
    "D_current_switching_allowed": False,
    "D_reentry_path_open": True,
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def current_roles() -> list[dict]:
    return [
        {
            "strategy": "A1_BASELINE_CONTROL",
            "role": "PRIMARY_CONTROL",
            "switching_allowed": True,
            "reason": "DEFAULT_BASELINE",
            "clean_replay_evidence": None,
            "reentry_allowed": False,
            "adoption_allowed": False,
            "broker_action_allowed": False,
        },
        {
            "strategy": "E_R1",
            "role": "DEFENSIVE_OVERLAY_CANDIDATE",
            "switching_allowed": False,
            "reason": "WAIT_FORWARD_MATURITY",
            "clean_replay_evidence": True,
            "reentry_allowed": False,
            "adoption_allowed": False,
            "broker_action_allowed": False,
        },
        {
            "strategy": "soft-cap",
            "role": "RETURN_ENHANCER_OVERLAY_CANDIDATE",
            "switching_allowed": False,
            "reason": "RECIPIENT_RISK_NOT_YET_CONTROLLED",
            "clean_replay_evidence": None,
            "reentry_allowed": False,
            "adoption_allowed": False,
            "broker_action_allowed": False,
        },
        {
            "strategy": "C",
            "role": "REGIME_SPECIFIC_OVERLAY_CANDIDATE",
            "switching_allowed": False,
            "reason": "ROLE_NOT_CONFIRMED",
            "clean_replay_evidence": None,
            "reentry_allowed": False,
            "adoption_allowed": False,
            "broker_action_allowed": False,
        },
        {
            "strategy": "D_original",
            "role": "FROZEN_WITH_REENTRY_PATH",
            "switching_allowed": False,
            "reason": "CURRENT_VERSION_CONCENTRATION_AND_LEFT_TAIL_RISK_BLOCKED",
            "clean_replay_evidence": None,
            "reentry_allowed": True,
            "adoption_allowed": False,
            "broker_action_allowed": False,
        },
        {
            "strategy": "D_R2C",
            "role": "REJECTED_CURRENT_VERSION",
            "switching_allowed": False,
            "reason": "CURRENT_VERSION_NOT_ADOPTABLE_BUT_D_DIRECTION_NOT_PERMANENTLY_BANNED",
            "clean_replay_evidence": None,
            "reentry_allowed": True,
            "adoption_allowed": False,
            "broker_action_allowed": False,
        },
    ]


def state_machine_rules() -> dict:
    return {
        "current_active_state": "STATE_BASE_A1",
        "states": [
            "STATE_BASE_A1",
            "STATE_DEFENSIVE_A1_E_R1",
            "STATE_RETURN_ENHANCED_A1_SOFTCAP",
            "STATE_HYBRID_CAUTION_A1_E_R1_SOFTCAP",
            "STATE_REGIME_SPECIFIC_A1_C",
            "STATE_REGIME_MOMENTUM_A1_D_R3_PROBATION",
            "STATE_FALLBACK_A1_ONLY",
        ],
        "priority_order": [
            "DATA_QUALITY_VALIDITY_GATE",
            "DEFENSIVE_PROTECTION_E_R1",
            "A1_BASELINE",
            "SOFTCAP_RETURN_ENHANCER",
            "C_REGIME_SPECIFIC_OVERLAY",
            "D_R3_PROBATIONARY_REGIME_MOMENTUM_OVERLAY",
        ],
        "entry_rules": {
            "STATE_DEFENSIVE_A1_E_R1": {
                "candidate_condition": "risk_off_score >= 3 OR left_tail_risk_score elevated OR repeated_loser_score elevated OR concentration_score elevated with volatility/risk-off",
                "switching_allowed_now": False,
                "blocked_reason": "E_R1_WAIT_FORWARD_MATURITY",
            },
            "STATE_RETURN_ENHANCED_A1_SOFTCAP": {
                "candidate_condition": "risk_off_score <= 1 AND overheat_score >= 2 AND recipient_risk_score <= 1",
                "switching_allowed_now": False,
                "blocked_reason": "SOFTCAP_RECIPIENT_RISK_NOT_VALIDATED",
            },
            "STATE_REGIME_SPECIFIC_A1_C": {
                "candidate_condition": "C regime-specific forward evidence and matching market regime",
                "switching_allowed_now": False,
                "blocked_reason": "C_ROLE_NOT_CONFIRMED",
            },
            "STATE_REGIME_MOMENTUM_A1_D_R3_PROBATION": {
                "candidate_condition": "future D_R3 exists and every D re-entry gate passes",
                "switching_allowed_now": False,
                "blocked_reason": "D_R3_NOT_BUILT",
            },
        },
        "hysteresis": {
            "entry_threshold_exit_threshold_differ": True,
            "defensive_exit": "risk_off_score <= 1 for 2 consecutive trading days",
            "softcap_exit": "risk_off_score >= 2 OR recipient_risk_score >= 2",
            "D_R3_exit": "immediate if any D_R3 risk warning appears",
            "minimum_holding_period_trading_days": 5,
            "cooldown_trading_days": 5,
            "max_transitions_per_cooldown": 1,
        },
        "diagnostic_only": True,
        "no_trading_instructions": True,
    }


def thresholds() -> dict:
    return {
        "risk_off_score": {"defensive_entry": 3, "defensive_exit": 1, "exit_consecutive_days": 2},
        "overheat_score": {"softcap_entry": 2},
        "recipient_risk_score": {"softcap_entry_max": 1, "softcap_exit": 2},
        "market_trend_score": {"D_R3_entry_min": 3},
        "minimum_holding_period_trading_days": 5,
        "cooldown_trading_days": 5,
        "D_R3_initial_max_overlay_weight": 0.10,
        "D_R3_matured_max_overlay_weight": 0.15,
    }


def d_reentry_spec() -> dict:
    gates = {
        "concentration_gate": [
            "Top20 sector max weight <= A1 sector max weight + tolerance",
            "Top20 industry max weight <= A1 industry max weight + tolerance",
            "Top50 sector and industry concentration not worse than A1 beyond tolerance",
        ],
        "left_tail_gate": [
            "D_R3 left-tail proxy no worse than A1",
            "D_R3 worst bucket loss no worse than A1",
            "D_R3 drawdown proxy no worse than A1",
        ],
        "repeated_loser_gate": [
            "D_R3 repeated loser count <= A1",
            "D_R3 severe repeated loser exposure <= A1",
        ],
        "neutralization_retention_gate": [
            "sector-neutral / industry-neutral score retention >= 70%",
            "neutralized performance collapse fails gate",
        ],
        "forward_maturity_gate": [
            "sufficient Top20/Top50 matured observations across 5D/10D/20D",
            "multiple as-of dates required",
            "single short window not sufficient",
        ],
        "A1_QQQ_comparison_gate": [
            "acceptable winrate vs A1",
            "positive excess return vs QQQ if benchmark available",
            "return/drawdown ratio not worse than A1",
        ],
        "regime_specific_gate": [
            "D_R3 may apply only for REGIME_SPECIFIC_OVERLAY or PROBATIONARY_OVERLAY",
            "D_R3 may not apply for PRIMARY_CONTROL",
            "D_R3 may not replace A1",
        ],
        "execution_cap_gate": [
            "maximum diagnostic overlay weight <= 10% initially",
            "may rise to 15% only after additional forward maturity",
            "no broker action",
            "no adoption",
            "no official ranking mutation",
        ],
    }
    return {"D_permanent_ban": False, "D_reentry_path_open": True, "current_D_versions_blocked": True, "D_R3_required_gates": gates}


def permission_matrix() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ["A1", "PRIMARY_CONTROL", True, True, False, False, "100% diagnostic baseline", "", False, "WAIT_MORE_MATURITY"],
            ["E_R1", "DEFENSIVE_OVERLAY_CANDIDATE", False, True, False, False, "0% current; TBD diagnostic", "WAIT_FORWARD_MATURITY", False, "FORWARD_MATURITY_MONITOR"],
            ["soft-cap", "RETURN_ENHANCER_OVERLAY_CANDIDATE", False, True, False, False, "0% current; TBD diagnostic", "RECIPIENT_RISK_FILTER_REQUIRED", False, "RECIPIENT_RISK_AUDIT"],
            ["C", "REGIME_SPECIFIC_OVERLAY_CANDIDATE", False, True, False, False, "0% current", "ROLE_NOT_CONFIRMED", False, "C_ROLE_EVIDENCE_STAGE"],
            ["D_original", "FROZEN_WITH_REENTRY_PATH", False, False, False, False, "0%", "CURRENT_VERSION_BLOCKED_REENTRY_PATH_OPEN", True, "BUILD_D_R3_RISK_CONSTRAINED"],
            ["D_R2C", "REJECTED_CURRENT_VERSION", False, False, False, False, "0%", "CURRENT_VERSION_REJECTED_REENTRY_PATH_OPEN", True, "BUILD_D_R3_RISK_CONSTRAINED"],
            ["future_D_R3", "PROBATIONARY_OVERLAY", False, True, False, False, "10% max after gates pass", "D_R3_NOT_BUILT", True, "D_R3_REENTRY_GATE_APPLICATION"],
        ],
        columns=[
            "strategy",
            "role",
            "current_switching_allowed",
            "diagnostic_trigger_allowed",
            "adoption_allowed",
            "broker_action_allowed",
            "max_diagnostic_overlay_weight",
            "current_blocker",
            "reentry_allowed",
            "next_required_stage",
        ],
    )


def evaluate_state(scores: dict, inputs_missing: bool = False) -> tuple[str, list[dict], list[dict]]:
    triggers, blockers = [], []
    if inputs_missing:
        blockers.append({"candidate_state": "STATE_FALLBACK_A1_ONLY", "blocked_reason": "INPUT_MISSING", "action": "fallback_to_STATE_BASE_A1"})
        return "STATE_BASE_A1", triggers, blockers
    if scores.get("risk_off_score", 0) >= 3 or scores.get("left_tail_risk_score", 0) >= 2:
        triggers.append({"candidate_state": "STATE_DEFENSIVE_A1_E_R1", "trigger": "RISK_OFF_OR_LEFT_TAIL_ELEVATED"})
        blockers.append({"candidate_state": "STATE_DEFENSIVE_A1_E_R1", "blocked_reason": "E_R1_WAIT_FORWARD_MATURITY"})
        return "STATE_BASE_A1", triggers, blockers
    if scores.get("risk_off_score", 0) <= 1 and scores.get("overheat_score", 0) >= 2:
        triggers.append({"candidate_state": "STATE_RETURN_ENHANCED_A1_SOFTCAP", "trigger": "LOW_RISK_OFF_OVERHEAT_PRESENT"})
        if scores.get("recipient_risk_score", 0) >= 2:
            blockers.append({"candidate_state": "STATE_RETURN_ENHANCED_A1_SOFTCAP", "blocked_reason": "SOFTCAP_RECIPIENT_RISK_NOT_VALIDATED"})
        else:
            blockers.append({"candidate_state": "STATE_RETURN_ENHANCED_A1_SOFTCAP", "blocked_reason": "SOFTCAP_RECIPIENT_RISK_FILTER_REQUIRED"})
        return "STATE_BASE_A1", triggers, blockers
    return "STATE_BASE_A1", triggers, blockers


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    missing = [k for k, p in INPUTS.items() if not p.exists()]
    v154 = load_json(INPUTS["V21.154"])
    roles = current_roles()
    rules = state_machine_rules()
    d_spec = d_reentry_spec()
    matrix = permission_matrix()
    score_rows = [
        {
            "date": "CURRENT",
            "risk_off_score": 0,
            "market_trend_score": 0,
            "overheat_score": 0,
            "recipient_risk_score": 2,
            "left_tail_risk_score": 0,
            "repeated_loser_score": 0,
            "concentration_score": 0,
            "data_quality_score": 1 if missing else 0,
            "forward_health_score_E_R1": "WAIT_FORWARD_MATURITY",
            "forward_health_score_softcap": "WAIT_FORWARD_MATURITY_RISK_MIXED",
            "forward_health_score_C": "ROLE_NOT_CONFIRMED",
            "forward_health_score_D": "CURRENT_D_BLOCKED_D_R3_NOT_BUILT",
            "current_state": "STATE_BASE_A1",
            "input_warning": "INPUT_MISSING:" + "|".join(missing) if missing else "",
        }
    ]
    state, triggers, blockers = evaluate_state(score_rows[0], bool(missing))
    triggers.append({"candidate_state": "STATE_REGIME_MOMENTUM_A1_D_R3_PROBATION", "trigger": "D_R3_REQUEST_NOT_PRESENT"})
    blockers.append({"candidate_state": "STATE_REGIME_MOMENTUM_A1_D_R3_PROBATION", "blocked_reason": "D_R3_NOT_BUILT"})
    blockers.append({"candidate_state": "CURRENT_D_ORIGINAL_OR_D_R2C", "blocked_reason": "CURRENT_D_VERSION_BLOCKED_REENTRY_PATH_OPEN"})
    blocker_audit = pd.DataFrame(
        [
            {"strategy": r["strategy"], "current_blocker": r["reason"], "switching_allowed": r["switching_allowed"], "reentry_allowed": r["reentry_allowed"]}
            for r in roles
            if not r["switching_allowed"]
        ]
    )
    d_status = pd.DataFrame(
        [
            {"version": "D_original", "current_switching_allowed": False, "reentry_allowed": True, "status": "FROZEN_WITH_REENTRY_PATH", "next_step": "BUILD_D_R3_RISK_CONSTRAINED"},
            {"version": "D_R2C", "current_switching_allowed": False, "reentry_allowed": True, "status": "REJECTED_CURRENT_VERSION", "next_step": "BUILD_D_R3_RISK_CONSTRAINED"},
            {"version": "future_D_R3", "current_switching_allowed": False, "reentry_allowed": True, "status": "NOT_BUILT", "next_step": "PASS_ALL_D_REENTRY_GATES"},
        ]
    )
    if missing:
        final_status = "PARTIAL_PASS_V21_155_FRAMEWORK_READY_WITH_INPUT_WARNINGS"
        decision = "USE_RULES_DIAGNOSTIC_ONLY_WAIT_INPUT_COMPLETION"
    else:
        final_status = "PASS_V21_155_SWITCHING_STATE_MACHINE_AND_D_REENTRY_GATE_READY"
        decision = "CONDITIONAL_SWITCHING_FRAMEWORK_READY_RESEARCH_ONLY_D_REENTRY_PATH_OPEN"
    summary = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "current_active_state": state,
        "input_warnings": missing,
        "E_R1_clean_replay_evidence": bool(v154.get("E_R1_left_tail_advantage_persisted_clean", False)),
        **FLAGS,
    }
    (OUT / "strategy_role_registry.json").write_text(json.dumps({"roles": roles}, indent=2), encoding="utf-8")
    (OUT / "state_machine_rules.json").write_text(json.dumps(rules, indent=2), encoding="utf-8")
    (OUT / "switching_gate_thresholds.json").write_text(json.dumps(thresholds(), indent=2), encoding="utf-8")
    (OUT / "d_reentry_gate_spec.json").write_text(json.dumps(d_spec, indent=2), encoding="utf-8")
    pd.DataFrame(roles).to_csv(OUT / "current_strategy_role_audit.csv", index=False)
    blocker_audit.to_csv(OUT / "current_strategy_blocker_audit.csv", index=False)
    pd.DataFrame(score_rows).to_csv(OUT / "strategy_state_by_date_diagnostic.csv", index=False)
    pd.DataFrame(triggers).to_csv(OUT / "switch_trigger_ledger.csv", index=False)
    pd.DataFrame(blockers).to_csv(OUT / "switch_blocker_ledger.csv", index=False)
    d_status.to_csv(OUT / "d_reentry_status_report.csv", index=False)
    matrix.to_csv(OUT / "overlay_permission_matrix.csv", index=False)
    (OUT / "V21.155_machine_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"current_active_state={state}",
        "A1_role=PRIMARY_CONTROL",
        "E_R1_role=DEFENSIVE_OVERLAY_CANDIDATE switching_allowed=false blocker=WAIT_FORWARD_MATURITY",
        "softcap_role=RETURN_ENHANCER_OVERLAY_CANDIDATE switching_allowed=false blocker=RECIPIENT_RISK_NOT_YET_CONTROLLED",
        "C_role=REGIME_SPECIFIC_OVERLAY_CANDIDATE switching_allowed=false blocker=ROLE_NOT_CONFIRMED",
        "D_original_role=FROZEN_WITH_REENTRY_PATH switching_allowed=false",
        "D_R2C_role=REJECTED_CURRENT_VERSION switching_allowed=false",
        "D_permanent_ban=false",
        "D_reentry_path_open=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "protected_outputs_modified=false",
    ]
    (OUT / "V21.155_readable_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
