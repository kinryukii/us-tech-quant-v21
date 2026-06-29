from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


STAGE = "V21.156_CONDITIONAL_STRATEGY_SWITCHING_SHADOW_SIMULATION"
OUT = Path("outputs/v21/V21.156_CONDITIONAL_STRATEGY_SWITCHING_SHADOW_SIMULATION")
V155 = Path("outputs/v21/V21.155_CONDITIONAL_STRATEGY_SWITCHING_STATE_MACHINE_AND_D_REENTRY_GATE")
RULES = V155 / "state_machine_rules.json"
ROLES = V155 / "strategy_role_registry.json"
THRESHOLDS = V155 / "switching_gate_thresholds.json"
D_SPEC = V155 / "d_reentry_gate_spec.json"
V153_DAILY = Path("outputs/v21/V21.153_REALIZED_WINDOW_COMPARISON_20260616_TO_LATEST/realized_window_daily_returns.csv")
V154_CLEAN = Path("outputs/v21/V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT/clean_replay_summary.csv")
PRICE = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")

FLAGS = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "current_primary_control_unchanged": True,
    "D_permanent_ban": False,
    "D_reentry_path_open": True,
    "current_D_switching_allowed": False,
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def discover(path: Path, source_name: str) -> dict:
    row = {"source_name": source_name, "path": str(path).replace("\\", "/"), "exists": path.exists(), "rows": 0, "date_min": "", "date_max": "", "usable": False, "warning": ""}
    if not path.exists():
        row["warning"] = "INPUT_MISSING"
        return row
    try:
        if path.suffix.lower() == ".csv":
            df = pd.read_csv(path)
            row["rows"] = len(df)
            date_cols = [c for c in df.columns if "date" in c.lower() or c.lower() in {"as_of_date"}]
            if date_cols and len(df):
                vals = pd.to_datetime(df[date_cols[0]], errors="coerce").dropna()
                if len(vals):
                    row["date_min"] = str(vals.min().date())
                    row["date_max"] = str(vals.max().date())
            row["usable"] = True
        else:
            row["rows"] = 1
            row["usable"] = True
    except Exception as exc:
        row["warning"] = f"READ_ERROR:{exc}"
    return row


def score_dates() -> pd.DataFrame:
    if V153_DAILY.exists():
        daily = pd.read_csv(V153_DAILY)
        b = daily[(daily["strategy_id"].eq("B_STATIC_MOMENTUM_BLEND")) & (daily["variant"].eq("EXEC_BASELINE")) & (daily["bucket"].eq("Top20"))].copy()
        if not b.empty:
            b["date"] = pd.to_datetime(b["date"])
            rows = []
            for _, r in b.sort_values("date").iterrows():
                q = float(r["QQQ_daily_return"])
                rows.append(
                    {
                        "as_of_date": str(r["date"].date()),
                        "risk_off_score": 3 if q <= -0.01 else (2 if q < 0 else 0),
                        "market_trend_score": 3 if q > 0.01 else (1 if q > 0 else 0),
                        "overheat_score": 2,
                        "recipient_risk_score": 2,
                        "left_tail_risk_score": 2 if q <= -0.015 else 0,
                        "repeated_loser_score": None,
                        "concentration_score": None,
                        "data_quality_score": 0,
                        "forward_health_score_E_R1": None,
                        "forward_health_score_softcap": None,
                        "forward_health_score_C": None,
                        "forward_health_score_D": None,
                        "score_status": "PARTIAL_INPUTS_AVAILABLE",
                    }
                )
            return pd.DataFrame(rows)
    return pd.DataFrame(
        [
            {
                "as_of_date": "CURRENT",
                "risk_off_score": None,
                "market_trend_score": None,
                "overheat_score": None,
                "recipient_risk_score": None,
                "left_tail_risk_score": None,
                "repeated_loser_score": None,
                "concentration_score": None,
                "data_quality_score": None,
                "forward_health_score_E_R1": None,
                "forward_health_score_softcap": None,
                "forward_health_score_C": None,
                "forward_health_score_D": None,
                "score_status": "INPUT_MISSING",
            }
        ]
    )


def candidate_state(scores: dict, d_r3_gates_passed: bool = False, d_r3_exists: bool = False) -> tuple[str, list[dict]]:
    triggers: list[dict] = []
    def num(name: str, default: int = 0):
        val = scores.get(name, default)
        return default if val is None or pd.isna(val) else val
    if scores.get("data_quality_score") is None or scores.get("risk_off_score") is None:
        triggers.append({"trigger_type": "FALLBACK", "trigger_score_name": "data_quality_score", "trigger_score_value": scores.get("data_quality_score"), "trigger_threshold": "available", "trigger_detail": "INPUT_MISSING_FALLBACK_A1"})
        return "STATE_FALLBACK_A1_ONLY", triggers
    if num("data_quality_score") >= 3:
        triggers.append({"trigger_type": "DATA_QUALITY", "trigger_score_name": "data_quality_score", "trigger_score_value": scores.get("data_quality_score"), "trigger_threshold": "<3", "trigger_detail": "DATA_QUALITY_GATE_FAILED"})
        return "STATE_FALLBACK_A1_ONLY", triggers
    if num("risk_off_score") >= 3 or num("left_tail_risk_score") >= 2 or num("repeated_loser_score") >= 2:
        triggers.append({"trigger_type": "DEFENSIVE", "trigger_score_name": "risk_off_score", "trigger_score_value": scores.get("risk_off_score"), "trigger_threshold": ">=3", "trigger_detail": "RISK_OFF_OR_LEFT_TAIL"})
        return "STATE_DEFENSIVE_A1_E_R1", triggers
    if num("risk_off_score") <= 1 and num("overheat_score") >= 2 and num("recipient_risk_score", 99) <= 1:
        triggers.append({"trigger_type": "RETURN_ENHANCER", "trigger_score_name": "overheat_score", "trigger_score_value": scores.get("overheat_score"), "trigger_threshold": ">=2", "trigger_detail": "LOW_RISK_OFF_OVERHEAT"})
        return "STATE_RETURN_ENHANCED_A1_SOFTCAP", triggers
    if scores.get("forward_health_score_C") == "ROLE_CONFIRMED":
        triggers.append({"trigger_type": "REGIME_SPECIFIC", "trigger_score_name": "forward_health_score_C", "trigger_score_value": "ROLE_CONFIRMED", "trigger_threshold": "ROLE_CONFIRMED", "trigger_detail": "C_REGIME_ROLE"})
        return "STATE_REGIME_SPECIFIC_A1_C", triggers
    if d_r3_exists and d_r3_gates_passed:
        triggers.append({"trigger_type": "D_R3_PROBATION", "trigger_score_name": "D_R3_gates", "trigger_score_value": "PASS", "trigger_threshold": "ALL_PASS", "trigger_detail": "D_R3_REENTRY_GATES_PASS"})
        return "STATE_REGIME_MOMENTUM_A1_D_R3_PROBATION", triggers
    return "STATE_BASE_A1", [{"trigger_type": "BASELINE", "trigger_score_name": "none", "trigger_score_value": "", "trigger_threshold": "", "trigger_detail": "NO_OVERLAY_TRIGGER"}]


def governed_for(candidate: str) -> tuple[str, str, str, str]:
    mapping = {
        "STATE_DEFENSIVE_A1_E_R1": ("STATE_BASE_A1", "E_R1", "E_R1_WAIT_FORWARD_MATURITY", "FORWARD_MATURITY_MONITOR"),
        "STATE_RETURN_ENHANCED_A1_SOFTCAP": ("STATE_BASE_A1", "soft-cap", "SOFTCAP_RECIPIENT_RISK_NOT_VALIDATED", "RECIPIENT_RISK_AUDIT"),
        "STATE_REGIME_SPECIFIC_A1_C": ("STATE_BASE_A1", "C", "C_ROLE_NOT_CONFIRMED", "C_ROLE_EVIDENCE_STAGE"),
        "STATE_REGIME_MOMENTUM_A1_D_R3_PROBATION": ("STATE_BASE_A1", "future_D_R3", "D_R3_REENTRY_GATES_NOT_PASSED", "D_R3_REENTRY_GATE_APPLICATION"),
        "STATE_FALLBACK_A1_ONLY": ("STATE_BASE_A1", "inputs", "INPUT_MISSING_FALLBACK_A1", "INPUT_COMPLETION"),
    }
    return mapping.get(candidate, ("STATE_BASE_A1", "A1", "NONE", "NONE"))


def anti_churn(states: list[str], dates: list[str], cooldown: int = 5) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    transitions = []
    current = states[0] if states else "STATE_BASE_A1"
    last_transition_idx = 0
    for i, (d, cand) in enumerate(zip(dates, states)):
        desired = cand
        allowed = desired != current and (i - last_transition_idx) >= cooldown
        reason = "NO_CHANGE" if desired == current else ("COOLDOWN_BLOCK" if not allowed else "TRANSITION_ALLOWED")
        if allowed:
            transitions.append({"as_of_date": d, "from_state": current, "to_state": desired, "transition_type": "SHADOW_DIAGNOSTIC"})
            current = desired
            last_transition_idx = i
        rows.append({"as_of_date": d, "candidate_state": cand, "anti_churn_state": current, "transition_allowed": allowed, "anti_churn_reason": reason, "minimum_holding_period_days": 5, "cooldown_days": cooldown})
    return pd.DataFrame(rows), pd.DataFrame(transitions, columns=["as_of_date", "from_state", "to_state", "transition_type"])


def permission_audit() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ["A1", "PRIMARY_CONTROL", True, True, False, False, "", "WAIT_MORE_MATURITY", True, True],
            ["E_R1", "DEFENSIVE_OVERLAY_CANDIDATE", True, False, False, False, "WAIT_FORWARD_MATURITY", "FORWARD_MATURITY_MONITOR", True, False],
            ["soft-cap", "RETURN_ENHANCER_OVERLAY_CANDIDATE", True, False, False, False, "RECIPIENT_RISK_NOT_YET_CONTROLLED", "RECIPIENT_RISK_AUDIT", True, False],
            ["C", "REGIME_SPECIFIC_OVERLAY_CANDIDATE", True, False, False, False, "ROLE_NOT_CONFIRMED", "C_ROLE_EVIDENCE_STAGE", True, False],
            ["D_original", "FROZEN_WITH_REENTRY_PATH", False, False, False, False, "CURRENT_VERSION_BLOCKED_REENTRY_PATH_OPEN", "BUILD_D_R3_RISK_CONSTRAINED", False, False],
            ["D_R2C", "REJECTED_CURRENT_VERSION", False, False, False, False, "CURRENT_VERSION_REJECTED_REENTRY_PATH_OPEN", "BUILD_D_R3_RISK_CONSTRAINED", False, False],
            ["future_D_R3", "PROBATIONARY_OVERLAY", False, False, False, False, "D_R3_NOT_BUILT", "D_R3_REENTRY_GATE_APPLICATION", False, False],
        ],
        columns=["strategy", "role", "diagnostic_trigger_allowed", "current_switching_allowed", "adoption_allowed", "broker_action_allowed", "current_blocker", "next_required_stage", "can_appear_in_shadow_candidate_state", "can_appear_in_governed_state"],
    )


def d_reentry_audit() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ["D_original", True, "FROZEN_WITH_REENTRY_PATH", False, False, True, "BLOCK", "BLOCK", "BLOCK", "UNKNOWN", "BLOCK", "BLOCK", "BLOCK", "PASS", "CURRENT_VERSION_BLOCKED", "CURRENT_VERSION_BLOCKED_REENTRY_PATH_OPEN"],
            ["D_R2C", True, "REJECTED_CURRENT_VERSION", False, False, True, "BLOCK", "BLOCK", "BLOCK", "UNKNOWN", "BLOCK", "BLOCK", "BLOCK", "PASS", "CURRENT_VERSION_REJECTED", "CURRENT_VERSION_REJECTED_REENTRY_PATH_OPEN"],
            ["future_D_R3", False, "PROBATIONARY_OVERLAY", False, False, True, "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "PASS", "NOT_BUILT", "D_R3_NOT_BUILT"],
        ],
        columns=["d_variant", "exists", "current_role", "current_switching_allowed", "d_permanent_ban", "d_reentry_path_open", "concentration_gate_status", "left_tail_gate_status", "repeated_loser_gate_status", "neutralization_retention_gate_status", "forward_maturity_gate_status", "a1_qqq_comparison_gate_status", "regime_specific_gate_status", "execution_cap_gate_status", "final_d_reentry_status", "blocker"],
    )


def performance_outputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    warnings = []
    if not V154_CLEAN.exists():
        warnings.append("INPUT_MISSING_PERFORMANCE_LEDGER")
        empty = pd.DataFrame(columns=["path_name", "portfolio_bucket", "holding_horizon", "valid_observations", "average_return"])
        return empty, pd.DataFrame(columns=["metric", "value"]), pd.DataFrame(columns=["metric", "value"]), warnings
    clean = pd.read_csv(V154_CLEAN)
    perf = clean.rename(columns={"E_R1_average_return": "shadow_E_R1_average_return", "A1_average_return": "governed_A1_average_return"})
    perf["governed_state_path"] = "STATE_BASE_A1"
    perf["shadow_candidate_state_path"] = "NOT_ACTIONABLE_CLEAN_ONLY"
    vs_a1 = perf[["portfolio_bucket", "holding_horizon", "valid_paired_trial_count", "E_R1_minus_A1_average_return", "E_R1_winrate_vs_A1"]].copy()
    vs_qqq = perf[["portfolio_bucket", "holding_horizon", "valid_paired_trial_count", "QQQ_average_return"]].copy()
    return perf, vs_a1, vs_qqq, warnings


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    core_missing = [p for p in [RULES, ROLES, THRESHOLDS, D_SPEC] if not p.exists()]
    sources = [
        discover(RULES, "V21.155_state_machine_rules"),
        discover(ROLES, "V21.155_strategy_role_registry"),
        discover(THRESHOLDS, "V21.155_switching_gate_thresholds"),
        discover(D_SPEC, "V21.155_d_reentry_gate_spec"),
        discover(V153_DAILY, "V21.153_realized_window_daily_returns"),
        discover(V154_CLEAN, "V21.154_clean_replay_summary"),
        discover(PRICE, "canonical_ohlcv_price_panel"),
    ]
    signals = score_dates()
    trigger_rows = []
    blocker_rows = []
    gov_rows = []
    shadow_rows = []
    for _, row in signals.iterrows():
        scores = row.to_dict()
        cand, triggers = candidate_state(scores)
        governed, blocked_strategy, blocker, next_stage = governed_for(cand)
        for t in triggers:
            t.update({"as_of_date": row["as_of_date"], "shadow_candidate_state": cand})
            trigger_rows.append(t)
        blocker_rows.append({"as_of_date": row["as_of_date"], "shadow_candidate_state": cand, "governed_state": governed, "blocked_strategy": blocked_strategy, "blocker_code": blocker, "blocker_detail": blocker, "required_next_stage": next_stage})
        gov_rows.append({"as_of_date": row["as_of_date"], "governed_state": governed, "governed_policy_valid": True})
        shadow_rows.append({"as_of_date": row["as_of_date"], "shadow_candidate_state": cand, "not_actionable": cand != governed})
    anti, transitions = anti_churn([r["shadow_candidate_state"] for r in shadow_rows], [r["as_of_date"] for r in shadow_rows])
    perf, vs_a1, vs_qqq, perf_warnings = performance_outputs()
    input_warnings = [s for s in sources if s["warning"]] + [{"source_name": "performance", "warning": w} for w in perf_warnings]
    if core_missing:
        final_status = "BLOCKED_V21_156_SWITCHING_RULE_INPUTS_MISSING"
        decision = "DO_NOT_USE_SHADOW_SWITCHING_UNTIL_V21_155_INPUTS_REPAIRED"
    elif input_warnings:
        final_status = "PARTIAL_PASS_V21_156_SHADOW_SWITCHING_READY_WITH_INPUT_WARNINGS"
        decision = "USE_SWITCHING_ENGINE_DIAGNOSTIC_ONLY_INPUTS_INCOMPLETE"
    else:
        final_status = "PASS_V21_156_SHADOW_SWITCHING_SIMULATION_READY"
        decision = "SHADOW_SWITCHING_ENGINE_READY_GOVERNED_STATE_A1_ONLY_RESEARCH_ONLY"
    latest_price = ""
    if PRICE.exists():
        try:
            latest_price = str(pd.to_datetime(pd.read_csv(PRICE, usecols=["date"])["date"]).max().date())
        except Exception:
            latest_price = ""
    summary = {
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_used": latest_price,
        "current_active_governed_state": "STATE_BASE_A1",
        "governed_state_is_a1_only": True,
        "shadow_candidate_states_observed": "|".join(sorted(set(r["shadow_candidate_state"] for r in shadow_rows))),
        "transition_count_governed": 0,
        "transition_count_shadow": int(len(transitions)),
        "input_warning_count": len(input_warnings),
        "performance_computed": not perf.empty,
        **FLAGS,
    }
    pd.DataFrame(sources).to_csv(OUT / "input_discovery_report.csv", index=False)
    signals.to_csv(OUT / "signal_score_by_date.csv", index=False)
    pd.DataFrame(gov_rows).to_csv(OUT / "governed_state_by_date.csv", index=False)
    pd.DataFrame(shadow_rows).to_csv(OUT / "shadow_candidate_state_by_date.csv", index=False)
    pd.DataFrame(trigger_rows).to_csv(OUT / "switch_trigger_ledger.csv", index=False)
    pd.DataFrame(blocker_rows).to_csv(OUT / "switch_blocker_ledger.csv", index=False)
    anti.to_csv(OUT / "anti_churn_decision_ledger.csv", index=False)
    transitions.to_csv(OUT / "state_transition_ledger.csv", index=False)
    permission_audit().to_csv(OUT / "overlay_candidate_permission_audit.csv", index=False)
    d_reentry_audit().to_csv(OUT / "d_reentry_shadow_audit.csv", index=False)
    perf.to_csv(OUT / "switching_shadow_performance_clean_only.csv", index=False)
    vs_a1.to_csv(OUT / "switching_shadow_vs_a1_summary.csv", index=False)
    vs_qqq.to_csv(OUT / "switching_shadow_vs_qqq_summary.csv", index=False)
    pd.DataFrame(input_warnings if input_warnings else [{"source_name": "", "warning": ""}]).to_csv(OUT / "missing_input_warnings.csv", index=False)
    (OUT / "V21.156_machine_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"latest_price_date_used={latest_price}",
        "current_active_governed_state=STATE_BASE_A1",
        "governed_state_is_a1_only=true",
        f"shadow_candidate_states_observed={summary['shadow_candidate_states_observed']}",
        f"transition_count_governed=0",
        f"transition_count_shadow={summary['transition_count_shadow']}",
        f"input_warning_count={len(input_warnings)}",
        f"performance_computed={str(summary['performance_computed']).lower()}",
        "D_permanent_ban=false",
        "D_reentry_path_open=true",
        "current_D_switching_allowed=false",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "protected_outputs_modified=false",
        "current_primary_control_unchanged=true",
    ]
    (OUT / "V21.156_readable_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
