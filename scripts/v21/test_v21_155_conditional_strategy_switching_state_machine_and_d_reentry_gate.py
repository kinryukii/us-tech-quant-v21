from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import importlib.util


SCRIPT = Path("scripts/v21/v21_155_conditional_strategy_switching_state_machine_and_d_reentry_gate.py")
OUT = Path("outputs/v21/V21.155_CONDITIONAL_STRATEGY_SWITCHING_STATE_MACHINE_AND_D_REENTRY_GATE")


def mod():
    spec = importlib.util.spec_from_file_location("v155", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


def test_outputs_exist_and_summary_controls() -> None:
    required = [
        "strategy_role_registry.json",
        "state_machine_rules.json",
        "switching_gate_thresholds.json",
        "d_reentry_gate_spec.json",
        "current_strategy_role_audit.csv",
        "current_strategy_blocker_audit.csv",
        "strategy_state_by_date_diagnostic.csv",
        "switch_trigger_ledger.csv",
        "switch_blocker_ledger.csv",
        "d_reentry_status_report.csv",
        "overlay_permission_matrix.csv",
        "V21.155_readable_report.txt",
        "V21.155_machine_summary.json",
    ]
    for name in required:
        assert (OUT / name).exists(), name
    s = json.loads((OUT / "V21.155_machine_summary.json").read_text(encoding="utf-8"))
    for key in ["FINAL_STATUS", "DECISION", "research_only", "official_adoption_allowed", "broker_action_allowed", "protected_outputs_modified", "current_primary_control_unchanged", "D_permanent_ban", "D_reentry_path_open"]:
        assert key in s
    assert s["research_only"] is True
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["protected_outputs_modified"] is False


def test_a1_defaults_to_base_state() -> None:
    s = json.loads((OUT / "V21.155_machine_summary.json").read_text(encoding="utf-8"))
    assert s["current_active_state"] == "STATE_BASE_A1"
    roles = pd.read_csv(OUT / "current_strategy_role_audit.csv")
    a1 = roles[roles["strategy"].eq("A1_BASELINE_CONTROL")].iloc[0]
    assert a1["role"] == "PRIMARY_CONTROL"
    assert bool(a1["switching_allowed"]) is True


def test_risk_off_prioritizes_e_r1_over_softcap() -> None:
    m = mod()
    state, triggers, blockers = m.evaluate_state({"risk_off_score": 3, "overheat_score": 3, "recipient_risk_score": 0, "left_tail_risk_score": 0})
    assert state == "STATE_BASE_A1"
    assert triggers[0]["candidate_state"] == "STATE_DEFENSIVE_A1_E_R1"
    assert blockers[0]["blocked_reason"] == "E_R1_WAIT_FORWARD_MATURITY"


def test_softcap_blocked_when_recipient_risk_elevated() -> None:
    m = mod()
    _, triggers, blockers = m.evaluate_state({"risk_off_score": 0, "overheat_score": 3, "recipient_risk_score": 2})
    assert triggers[0]["candidate_state"] == "STATE_RETURN_ENHANCED_A1_SOFTCAP"
    assert blockers[0]["blocked_reason"] == "SOFTCAP_RECIPIENT_RISK_NOT_VALIDATED"


def test_current_d_cannot_switch_and_reentry_open() -> None:
    d = pd.read_csv(OUT / "d_reentry_status_report.csv")
    cur = d[d["version"].isin(["D_original", "D_R2C"])]
    assert (~cur["current_switching_allowed"].astype(bool)).all()
    assert cur["reentry_allowed"].astype(bool).all()
    s = json.loads((OUT / "V21.155_machine_summary.json").read_text(encoding="utf-8"))
    assert s["D_permanent_ban"] is False
    assert s["D_reentry_path_open"] is True


def test_future_d_r3_only_probation_after_gates() -> None:
    spec = json.loads((OUT / "d_reentry_gate_spec.json").read_text(encoding="utf-8"))
    assert spec["D_reentry_path_open"] is True
    assert "regime_specific_gate" in spec["D_R3_required_gates"]
    assert "execution_cap_gate" in spec["D_R3_required_gates"]
    matrix = pd.read_csv(OUT / "overlay_permission_matrix.csv")
    r3 = matrix[matrix["strategy"].eq("future_D_R3")].iloc[0]
    assert r3["role"] == "PROBATIONARY_OVERLAY"
    assert "10%" in r3["max_diagnostic_overlay_weight"]


def test_hysteresis_and_missing_input_fallback() -> None:
    rules = json.loads((OUT / "state_machine_rules.json").read_text(encoding="utf-8"))
    assert rules["hysteresis"]["minimum_holding_period_trading_days"] == 5
    assert rules["hysteresis"]["cooldown_trading_days"] == 5
    m = mod()
    state, _, blockers = m.evaluate_state({}, inputs_missing=True)
    assert state == "STATE_BASE_A1"
    assert blockers[0]["blocked_reason"] == "INPUT_MISSING"


def test_no_mutation_claims() -> None:
    report = (OUT / "V21.155_readable_report.txt").read_text(encoding="utf-8")
    assert "official_adoption_allowed=false" in report
    assert "broker_action_allowed=false" in report
    assert "protected_outputs_modified=false" in report
