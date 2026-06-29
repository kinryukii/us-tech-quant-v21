import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.164_SWITCH_STATE_FORWARD_TRACKING_LEDGER"
REQ = [
    "switch_state_forward_ledger.csv",
    "switch_state_pending_maturity.csv",
    "switch_state_matured_results.csv",
    "switch_state_vs_a1_comparison.csv",
    "switch_state_regime_snapshot.csv",
    "switch_state_component_return_attribution.csv",
    "switch_state_risk_diagnostics.csv",
    "switch_state_excluded_name_impact.csv",
    "switch_state_data_quality_warnings.csv",
    "V21.164_SWITCH_STATE_FORWARD_TRACKING_LEDGER_report.txt",
    "V21.164_SWITCH_STATE_FORWARD_TRACKING_LEDGER_summary.json",
]
STATES_163 = {
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
    return json.loads((OUT / "V21.164_SWITCH_STATE_FORWARD_TRACKING_LEDGER_summary.json").read_text(encoding="utf-8"))


def test_required_outputs_and_summary_exist():
    assert OUT.exists()
    for name in REQ:
        assert (OUT / name).exists(), name
    assert "final_status" in summary()


def test_policy_flags_enforced():
    s = summary()
    assert s["research_only"] is True
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["live_trading_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert s["role_review_required"] is False
    assert s["switch_adoption_allowed"] is False


def test_ledger_rows_pending_and_a1_control():
    ledger = read("switch_state_forward_ledger.csv")
    assert len(ledger) > 0
    assert "A1_CONTROL" in set(ledger["tracked_state"])
    pending = read("switch_state_pending_maturity.csv")
    matured = read("switch_state_matured_results.csv")
    assert len(pending) > 0 or len(matured) == len(ledger)
    assert ledger["broker_action_allowed"].astype(str).str.lower().eq("false").all()
    assert ledger["live_trading_allowed"].astype(str).str.lower().eq("false").all()


def test_selected_switch_state_valid():
    s = summary()
    assert s["selected_switch_state"] in STATES_163
    snap = read("switch_state_regime_snapshot.csv")
    assert snap["selected_switch_state"].iloc[0] in STATES_163


def test_if_matured_results_exist_vs_a1_comparison_exists():
    matured = read("switch_state_matured_results.csv")
    comp = read("switch_state_vs_a1_comparison.csv")
    if len(matured) > 0:
        assert len(comp) > 0
        assert "excess_return_vs_a1" in comp.columns


def test_excluded_name_impact_and_diagnostics_exist():
    impact = read("switch_state_excluded_name_impact.csv")
    assert len(impact) > 0
    assert {"HOOD", "WING", "JHX", "AMC"}.issubset(set(impact["ticker"]))
    risk = read("switch_state_risk_diagnostics.csv")
    attrib = read("switch_state_component_return_attribution.csv")
    assert len(risk) > 0
    assert len(attrib) > 0


def test_output_directory_is_isolated_no_protected_modified():
    s = summary()
    assert OUT.as_posix().endswith("outputs/v21/V21.164_SWITCH_STATE_FORWARD_TRACKING_LEDGER")
    for path in OUT.iterdir():
        assert path.is_file()
        assert path.parent == OUT
    assert s["protected_outputs_modified"] is False
