import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.169_DECISION_BOUNDARY_AND_ACTION_GUARDRAIL"
REQ = [
    "decision_boundary_state.csv",
    "action_guardrail_matrix.csv",
    "research_vs_execution_classification.csv",
    "portfolio_mode_guardrail.csv",
    "cash_constrained_fallback_guardrail.csv",
    "adoption_blocker_register.csv",
    "broker_action_blocker_register.csv",
    "maturity_gate_status.csv",
    "data_quality_gate_status.csv",
    "fallback_interpretation_guardrail.csv",
    "decision_boundary_warnings.csv",
    "protected_output_mutation_audit.csv",
    "V21.169_DECISION_BOUNDARY_AND_ACTION_GUARDRAIL_report.txt",
    "V21.169_DECISION_BOUNDARY_AND_ACTION_GUARDRAIL_summary.json",
]


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / name)


def summary() -> dict:
    return json.loads((OUT / "V21.169_DECISION_BOUNDARY_AND_ACTION_GUARDRAIL_summary.json").read_text(encoding="utf-8"))


def test_required_outputs_and_summary_exist():
    assert OUT.exists()
    for name in REQ:
        assert (OUT / name).exists(), name
    assert "final_status" in summary()


def test_policy_flags_and_guardrail_enabled():
    s = summary()
    assert s["research_only"] is True
    assert s["action_guardrail_enabled"] is True
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["live_trading_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert s["role_review_required"] is False


def test_no_action_allowed_any_module():
    s = summary()
    assert s["adoption_allowed_any_module"] is False
    assert s["broker_action_allowed_any_module"] is False
    assert s["live_trading_allowed_any_module"] is False


def test_portfolio_mode_blocked_matches_v168():
    v168 = json.loads((ROOT / "outputs" / "v21" / "V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER" / "V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER_summary.json").read_text())
    if v168["portfolio_mode_blocked"] is True:
        assert summary()["portfolio_mode_blocked"] is True


def test_fallback_interpretation_flags():
    s = summary()
    assert s["not_user_preference_only_strategy"] is True
    assert s["not_diversified_portfolio"] is True
    fg = read("fallback_interpretation_guardrail.csv")
    assert fg["adoption_allowed"].astype(str).str.lower().eq("false").all()
    assert fg["broker_action_allowed"].astype(str).str.lower().eq("false").all()


def test_maturity_gate_fails_when_no_matured_results():
    switch = json.loads((ROOT / "outputs" / "v21" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR_summary.json").read_text())
    if switch["matured_result_count_after"] == 0:
        assert summary()["maturity_gate_status"] != "PASS"


def test_data_quality_gate_fails_on_blocking_impact():
    v165 = json.loads((ROOT / "outputs" / "v21" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD_summary.json").read_text())
    if v165["max_data_quality_impact"] == "BLOCKING_IMPACT":
        assert summary()["data_quality_gate_status"] != "PASS"


def test_execution_gate_fails_when_no_600usd_executable_state():
    v167 = json.loads((ROOT / "outputs" / "v21" / "V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK" / "V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK_summary.json").read_text())
    if v167["active_600usd_executable_state_count"] == 0:
        assert summary()["execution_gate_status"] != "PASS"


def test_fallback_mode_research_only_non_promoted():
    df = read("cash_constrained_fallback_guardrail.csv")
    assert len(df) == 1
    assert df["cash_constrained_fallback_mode_research_only"].astype(str).str.lower().iloc[0] == "true"
    assert df["adoption_allowed"].astype(str).str.lower().iloc[0] == "false"
    assert df["broker_action_allowed"].astype(str).str.lower().iloc[0] == "false"


def test_output_directory_is_isolated():
    assert OUT.as_posix().endswith("outputs/v21/V21.169_DECISION_BOUNDARY_AND_ACTION_GUARDRAIL")
    for path in OUT.iterdir():
        assert path.is_file()
        assert path.parent == OUT


def test_no_official_or_protected_outputs_modified():
    s = summary()
    audit = read("protected_output_mutation_audit.csv")
    assert s["protected_outputs_modified"] is False
    assert int(audit["changed_protected_file_count"].iloc[0]) == 0
