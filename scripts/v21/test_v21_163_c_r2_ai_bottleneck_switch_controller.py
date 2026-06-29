import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER"
REQ = [
    "switch_controller_state.csv",
    "switch_controller_component_status.csv",
    "switch_controller_decision_rules.csv",
    "switch_controller_research_allocation_state.csv",
    "switch_controller_excluded_names.csv",
    "switch_controller_warnings.csv",
    "switch_controller_policy_flags.csv",
    "V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER_report.txt",
    "V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER_summary.json",
]
STATES = {
    "A1_ONLY_CONTROL",
    "A1_PLUS_C_R2_FORWARD_TRACKING",
    "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING",
    "A1_PLUS_E_R1_DEFENSIVE_FORWARD_TRACKING",
    "A1_PLUS_SOFTCAP_WATCH_ONLY",
    "NO_SWITCH_INSUFFICIENT_EVIDENCE",
}


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / name)


def summary() -> dict:
    return json.loads((OUT / "V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER_summary.json").read_text(encoding="utf-8"))


def test_required_outputs_and_summary_exist():
    assert OUT.exists()
    for name in REQ:
        assert (OUT / name).exists(), name
    assert "final_status" in summary()


def test_policy_flags_remain_enforced():
    s = summary()
    assert s["research_only"] is True
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert s["role_review_required"] is False
    assert s["switch_adoption_allowed"] is False
    assert s["live_trading_allowed"] is False
    policy = read("switch_controller_policy_flags.csv")
    assert policy["live_trading_allowed"].astype(str).str.lower().eq("false").all()


def test_selected_state_and_a1_primary():
    s = summary()
    assert s["selected_switch_state"] in STATES
    assert s["a1_primary_control"] is True
    state = read("switch_controller_state.csv")
    assert state["selected_switch_state"].iloc[0] in STATES
    assert state["a1_primary_control"].astype(str).str.lower().eq("true").all()


def test_c_r2_and_ai_cannot_be_adopted_and_broker_false():
    comp = read("switch_controller_component_status.csv")
    assert comp["adoption_allowed"].astype(str).str.lower().eq("false").all()
    alloc = read("switch_controller_research_allocation_state.csv")
    assert alloc["broker_action_allowed"].astype(str).str.lower().eq("false").all()
    assert alloc["official_weight"].astype(float).eq(0.0).all()


def test_excluded_names_decision_rules_and_component_status_exist():
    excluded = read("switch_controller_excluded_names.csv")
    assert excluded is not None
    rules = read("switch_controller_decision_rules.csv")
    comp = read("switch_controller_component_status.csv")
    assert len(rules) > 0
    assert len(comp) > 0
    assert {"A1_PRIMARY_CONTROL", "C_R2_FACTOR_ROTATION", "AI_BOTTLENECK_THEME"}.issubset(set(comp["component"]))


def test_output_directory_is_isolated_no_protected_modified():
    s = summary()
    assert OUT.as_posix().endswith("outputs/v21/V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER")
    for path in OUT.iterdir():
        assert path.is_file()
        assert path.parent == OUT
    assert s["protected_outputs_modified"] is False
