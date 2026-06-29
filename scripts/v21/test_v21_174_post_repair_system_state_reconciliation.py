import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.174_POST_REPAIR_SYSTEM_STATE_RECONCILIATION"
REQ = [
    "system_state_reconciliation_summary.csv",
    "guardrail_status_after_post_repair.csv",
    "active_blocker_register_after_post_repair.csv",
    "data_gate_final_status.csv",
    "maturity_gate_final_status.csv",
    "capital_execution_gate_final_status.csv",
    "policy_gate_final_status.csv",
    "fallback_interpretation_gate_final_status.csv",
    "unresolved_non_blocking_price_issues.csv",
    "research_continuation_status.csv",
    "post_repair_system_policy_flags.csv",
    "protected_output_mutation_audit.csv",
    "V21.174_POST_REPAIR_SYSTEM_STATE_RECONCILIATION_report.txt",
    "V21.174_POST_REPAIR_SYSTEM_STATE_RECONCILIATION_summary.json",
]


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / name)


def summary() -> dict:
    return json.loads((OUT / "V21.174_POST_REPAIR_SYSTEM_STATE_RECONCILIATION_summary.json").read_text(encoding="utf-8"))


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
    assert s["live_trading_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert s["role_review_required"] is False


def test_no_new_price_refresh():
    assert summary()["canonical_price_panel_mutated_by_this_stage"] is False


def test_data_gate_passes_if_v173_passed():
    v173 = json.loads((ROOT / "outputs" / "v21" / "V21.173_POST_REPAIR_DATA_GATE_AND_MUTATION_RECONCILIATION" / "V21.173_POST_REPAIR_DATA_GATE_AND_MUTATION_RECONCILIATION_summary.json").read_text())
    if v173["post_repair_data_gate_status"] == "POST_REPAIR_DATA_GATE_PASS_NO_TRUE_BLOCKERS":
        assert summary()["data_gate_status"] == "PASS_NO_TRUE_DATA_BLOCKERS"


def test_maturity_gate_fails_if_no_matured_results():
    switch = json.loads((ROOT / "outputs" / "v21" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR_summary.json").read_text())
    if switch["matured_result_count_after"] == 0:
        assert summary()["maturity_gate_status"] != "PASS_MATURITY_AVAILABLE"


def test_execution_gate_fails_if_600usd_blocked():
    v168 = json.loads((ROOT / "outputs" / "v21" / "V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER" / "V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER_summary.json").read_text())
    if v168["portfolio_mode_blocked"] is True:
        assert summary()["execution_gate_status"] != "PASS_EXECUTION_FEASIBLE"


def test_research_allowed_and_adoption_blocked_logic():
    s = summary()
    if s["data_gate_status"] == "PASS_NO_TRUE_DATA_BLOCKERS" and s["policy_gate_status"] == "PASS_POLICY_BLOCKS_ENFORCED":
        assert s["research_continuation_allowed"] is True
    if s["maturity_gate_status"] != "PASS_MATURITY_AVAILABLE" or s["execution_gate_status"] != "PASS_EXECUTION_FEASIBLE":
        assert s["adoption_blocked"] is True


def test_broker_live_official_flags_false_and_audit_clean():
    s = summary()
    assert s["broker_action_allowed"] is False
    assert s["live_trading_allowed"] is False
    assert s["official_adoption_allowed"] is False
    audit = read("protected_output_mutation_audit.csv")
    assert str(audit["audit_clean"].iloc[0]).lower() == "true"


def test_output_directory_is_isolated():
    assert OUT.as_posix().endswith("outputs/v21/V21.174_POST_REPAIR_SYSTEM_STATE_RECONCILIATION")
    for path in OUT.iterdir():
        assert path.is_file()
        assert path.parent == OUT


def test_no_official_or_protected_outputs_modified():
    s = summary()
    audit = read("protected_output_mutation_audit.csv")
    assert s["protected_outputs_modified"] is False
    assert int(audit["changed_protected_file_count"].iloc[0]) == 0
