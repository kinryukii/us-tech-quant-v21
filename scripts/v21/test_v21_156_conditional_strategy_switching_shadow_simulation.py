from __future__ import annotations

import json
from pathlib import Path
import importlib.util

import pandas as pd


SCRIPT = Path("scripts/v21/v21_156_conditional_strategy_switching_shadow_simulation.py")
OUT = Path("outputs/v21/V21.156_CONDITIONAL_STRATEGY_SWITCHING_SHADOW_SIMULATION")


def mod():
    spec = importlib.util.spec_from_file_location("v156", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


def test_required_outputs_and_summary_fields() -> None:
    required = [
        "input_discovery_report.csv", "signal_score_by_date.csv", "governed_state_by_date.csv",
        "shadow_candidate_state_by_date.csv", "switch_trigger_ledger.csv", "switch_blocker_ledger.csv",
        "anti_churn_decision_ledger.csv", "state_transition_ledger.csv", "overlay_candidate_permission_audit.csv",
        "d_reentry_shadow_audit.csv", "switching_shadow_performance_clean_only.csv",
        "switching_shadow_vs_a1_summary.csv", "switching_shadow_vs_qqq_summary.csv",
        "missing_input_warnings.csv", "V21.156_readable_report.txt", "V21.156_machine_summary.json",
    ]
    for name in required:
        assert (OUT / name).exists(), name
    s = json.loads((OUT / "V21.156_machine_summary.json").read_text(encoding="utf-8"))
    for k in ["FINAL_STATUS", "DECISION", "latest_price_date_used", "current_active_governed_state", "governed_state_is_a1_only", "shadow_candidate_states_observed", "transition_count_governed", "transition_count_shadow", "input_warning_count", "performance_computed", "D_permanent_ban", "D_reentry_path_open", "current_D_switching_allowed", "research_only", "official_adoption_allowed", "broker_action_allowed", "protected_outputs_modified", "current_primary_control_unchanged"]:
        assert k in s


def test_rules_loaded_and_governed_a1() -> None:
    disc = pd.read_csv(OUT / "input_discovery_report.csv")
    assert disc[disc["source_name"].eq("V21.155_state_machine_rules")]["usable"].astype(bool).iloc[0]
    assert disc[disc["source_name"].eq("V21.155_strategy_role_registry")]["usable"].astype(bool).iloc[0]
    gov = pd.read_csv(OUT / "governed_state_by_date.csv")
    assert set(gov["governed_state"]) == {"STATE_BASE_A1"}


def test_e_r1_shadow_and_blocker() -> None:
    m = mod()
    cand, _ = m.candidate_state({"data_quality_score": 0, "risk_off_score": 3, "left_tail_risk_score": 0})
    assert cand == "STATE_DEFENSIVE_A1_E_R1"
    governed, _, blocker, _ = m.governed_for(cand)
    assert governed == "STATE_BASE_A1"
    assert blocker == "E_R1_WAIT_FORWARD_MATURITY"


def test_softcap_candidate_and_recipient_block() -> None:
    m = mod()
    cand, _ = m.candidate_state({"data_quality_score": 0, "risk_off_score": 0, "overheat_score": 2, "recipient_risk_score": 1})
    assert cand == "STATE_RETURN_ENHANCED_A1_SOFTCAP"
    assert m.governed_for(cand)[2] == "SOFTCAP_RECIPIENT_RISK_NOT_VALIDATED"
    cand2, _ = m.candidate_state({"data_quality_score": 0, "risk_off_score": 0, "overheat_score": 2, "recipient_risk_score": 2})
    assert cand2 == "STATE_BASE_A1"


def test_d_blocked_and_reentry_open() -> None:
    d = pd.read_csv(OUT / "d_reentry_shadow_audit.csv")
    assert set(d[d["d_variant"].isin(["D_original", "D_R2C"])]["final_d_reentry_status"]) == {"CURRENT_VERSION_BLOCKED", "CURRENT_VERSION_REJECTED"}
    s = json.loads((OUT / "V21.156_machine_summary.json").read_text(encoding="utf-8"))
    assert s["D_permanent_ban"] is False
    assert s["D_reentry_path_open"] is True
    assert s["current_D_switching_allowed"] is False


def test_future_d_r3_requires_gates() -> None:
    m = mod()
    cand, _ = m.candidate_state({"data_quality_score": 0, "risk_off_score": 0}, d_r3_exists=True, d_r3_gates_passed=True)
    assert cand == "STATE_REGIME_MOMENTUM_A1_D_R3_PROBATION"
    cand2, _ = m.candidate_state({"data_quality_score": 0, "risk_off_score": 0}, d_r3_exists=True, d_r3_gates_passed=False)
    assert cand2 == "STATE_BASE_A1"


def test_anti_churn_prevents_rapid_switching_and_missing_fallback() -> None:
    m = mod()
    anti, trans = m.anti_churn(["STATE_BASE_A1", "STATE_DEFENSIVE_A1_E_R1", "STATE_RETURN_ENHANCED_A1_SOFTCAP"], ["d1", "d2", "d3"])
    assert len(trans) == 0
    cand, _ = m.candidate_state({"data_quality_score": None, "risk_off_score": None})
    assert cand == "STATE_FALLBACK_A1_ONLY"


def test_performance_and_no_mutation_claims() -> None:
    perf = pd.read_csv(OUT / "switching_shadow_performance_clean_only.csv")
    if not perf.empty:
        assert "valid_paired_trial_count" in perf.columns
    report = (OUT / "V21.156_readable_report.txt").read_text(encoding="utf-8")
    assert "official_adoption_allowed=false" in report
    assert "broker_action_allowed=false" in report
    assert "protected_outputs_modified=false" in report
