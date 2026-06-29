import json
from pathlib import Path

import pandas as pd

from scripts.v21.v21_169_daily_switch_ledger_append_and_governance_refresh import main


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.169_DAILY_SWITCH_LEDGER_APPEND_AND_GOVERNANCE_REFRESH"
REQUIRED = [
    "daily_switch_ledger_append_summary.csv",
    "refreshed_switch_state_maturity_scoreboard.csv",
    "refreshed_switch_state_decision_history.csv",
    "switch_decision_change_log.csv",
    "current_switch_governance_snapshot.csv",
    "V21.169_daily_switch_refresh_report.txt",
    "validation_summary.json",
]
ALLOWED_FINAL_DECISIONS = {
    "KEEP_A1_CONTROL",
    "WAIT_MORE_MATURITY",
    "ALLOW_FORWARD_TRACKING_ONLY",
    "BLOCKED_BY_RISK",
    "BLOCKED_BY_EXECUTION",
    "BLOCKED_BY_DATA_QUALITY",
    "ROLE_REVIEW_REQUIRED",
    "SWITCH_ALLOWED_RESEARCH_ONLY",
    "OFFICIAL_ADOPTION_BLOCKED",
}


def setup_module():
    main()


def read_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / name)


def summary() -> dict:
    return json.loads((OUT / "validation_summary.json").read_text(encoding="utf-8"))


def test_required_outputs_exist_and_summary_parseable():
    assert OUT.exists()
    for name in REQUIRED:
        assert (OUT / name).exists(), name
    parsed = summary()
    assert parsed["stage"] == "V21.169_DAILY_SWITCH_LEDGER_APPEND_AND_GOVERNANCE_REFRESH"


def test_final_decision_enum_and_research_policy_flags():
    s = summary()
    assert s["final_decision"] in ALLOWED_FINAL_DECISIONS
    assert s["research_only"] is True
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["protected_outputs_modified"] is False


def test_official_adoption_false_unless_all_gates_pass_not_expected():
    s = summary()
    maturity = read_csv("refreshed_switch_state_maturity_scoreboard.csv")
    all_matured = maturity["maturity_gate_status"].astype(str).eq("PASS_MATURITY_AVAILABLE").all()
    if not all_matured:
        assert s["official_adoption_allowed"] is False
    assert s["official_adoption_allowed"] is False


def test_no_new_data_condition_is_warning_not_failure():
    append = read_csv("daily_switch_ledger_append_summary.csv")
    s = summary()
    if int(append["new_rows_appended"].iloc[0]) == 0:
        assert append["append_status"].iloc[0] == "WARN_NO_NEW_SWITCH_LEDGER_DATA"
        assert s["final_status"] == "WARN_NO_NEW_SWITCH_LEDGER_DATA"
        assert s["no_new_data"] is True


def test_maturity_missing_or_pending_does_not_fabricate_pass():
    maturity = read_csv("refreshed_switch_state_maturity_scoreboard.csv")
    unsupported = maturity[maturity["missing_observations"].astype(int).gt(0)]
    assert not maturity.empty
    assert not unsupported["maturity_gate_status"].astype(str).str.contains("PASS", case=False, na=False).any()
    zero_matured = maturity[maturity["matured_observations"].astype(int).eq(0)]
    assert not zero_matured["maturity_gate_status"].astype(str).str.contains("PASS", case=False, na=False).any()


def test_missing_source_warnings_are_recorded_not_silent_pass():
    s = summary()
    warning_types = [str(w.get("warning_type", "")) for w in s.get("warnings", [])]
    assert any("SOURCE_MISSING_WARNING" in w for w in warning_types)
    maturity = read_csv("refreshed_switch_state_maturity_scoreboard.csv")
    if maturity["stale_source_warning"].astype(str).str.contains("SOURCE_MISSING_WARNING|MISSING_OBSERVATION_WARNING", regex=True).any():
        flagged = maturity[maturity["stale_source_warning"].astype(str).ne("NONE")]
        assert not flagged["maturity_gate_status"].astype(str).str.contains("PASS", case=False, na=False).any()


def test_decision_history_initializes_or_appends_correctly():
    history = read_csv("refreshed_switch_state_decision_history.csv")
    change = read_csv("switch_decision_change_log.csv")
    s = summary()
    assert not history.empty
    assert len(history["refresh_date"].astype(str)) == len(set(history["refresh_date"].astype(str)))
    latest = history.sort_values("refresh_date").tail(1).iloc[0]
    assert latest["current_decision"] == s["final_decision"]
    assert change["current_decision"].iloc[0] == s["final_decision"]
    assert "previous_decision" in history.columns
    assert "decision_changed" in history.columns


def test_expected_current_snapshot_values():
    snap = read_csv("current_switch_governance_snapshot.csv").iloc[0]
    assert snap["current_primary_control"] == "A1_CONTROL"
    assert snap["best_forward_tracking_state"] == "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING"
    assert str(snap["role_review_required"]).lower() in {"false", "0"}
    assert str(snap["official_adoption_allowed"]).lower() in {"false", "0"}
    assert str(snap["broker_action_allowed"]).lower() in {"false", "0"}


def test_change_log_keeps_action_flags_false():
    change = read_csv("switch_decision_change_log.csv").iloc[0]
    assert str(change["current_role_review_required"]).lower() in {"false", "0"}
    assert str(change["current_official_adoption_allowed"]).lower() in {"false", "0"}
    assert str(change["current_broker_action_allowed"]).lower() in {"false", "0"}


def test_repo_dirty_state_warning_recorded_without_failure():
    s = summary()
    assert "repo_dirty_state_warning" in s
    assert "pre_existing_dirty_state_detected" in s
    assert isinstance(s["pre_existing_dirty_state_detected"], bool)
    assert s["stage_modified_unrelated_files"] is False
    assert s["protected_output_mutation_audit_clean"] is True
