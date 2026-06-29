import json
from pathlib import Path

import pandas as pd

from scripts.v21.v21_173_daily_chain_orchestrator_for_switch_governance import main


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.173_DAILY_CHAIN_ORCHESTRATOR_FOR_SWITCH_GOVERNANCE"
REQUIRED = [
    "orchestrator_stage_run_summary.csv",
    "orchestrator_final_switch_snapshot.csv",
    "orchestrator_error_warning_log.csv",
    "orchestrator_artifact_index.csv",
    "V21.173_daily_switch_governance_orchestrator_report.txt",
    "validation_summary.json",
]
ALLOWED = {
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


def test_required_outputs_and_summary_parseable():
    assert OUT.exists()
    for name in REQUIRED:
        assert (OUT / name).exists(), name
    assert summary()["stage"] == "V21.173_DAILY_CHAIN_ORCHESTRATOR_FOR_SWITCH_GOVERNANCE"


def test_stage_summary_includes_required_chain_stages():
    stages = read_csv("orchestrator_stage_run_summary.csv")
    assert {"V21.169", "V21.171", "V21.172"}.issubset(set(stages["stage_id"]))
    assert not stages["run_mode"].eq("MISSING").any()
    assert set(stages["run_mode"]) == {"CONSUMED_EXISTING_OUTPUTS"}


def test_final_decision_enum_and_wait_maturity():
    s = summary()
    snap = read_csv("orchestrator_final_switch_snapshot.csv").iloc[0]
    assert s["final_decision"] in ALLOWED
    assert snap["final_decision"] in ALLOWED
    assert s["final_decision"] == "WAIT_MORE_MATURITY"
    assert snap["final_decision"] == "WAIT_MORE_MATURITY"


def test_action_flags_all_blocked():
    s = summary()
    snap = read_csv("orchestrator_final_switch_snapshot.csv").iloc[0]
    assert s["role_review_required"] is False
    assert s["switch_allowed_research_only"] is False
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert s["one_day_outperformance_switch_allowed"] is False
    for col in [
        "role_review_required",
        "switch_allowed_research_only",
        "official_adoption_allowed",
        "broker_action_allowed",
        "protected_outputs_modified",
        "one_day_outperformance_switch_allowed",
    ]:
        assert str(snap[col]).lower() in {"false", "0"}


def test_no_new_ledger_data_warning_nonfatal():
    s = summary()
    log = read_csv("orchestrator_error_warning_log.csv")
    warning = log[log["warning_type"].eq("WARN_NO_NEW_SWITCH_LEDGER_DATA")]
    assert not warning.empty
    assert set(warning["severity"]) == {"WARNING"}
    assert s["no_new_ledger_data_warning_nonfatal"] is True
    assert s["fatal_error_count"] == 0


def test_expected_final_snapshot_fields():
    snap = read_csv("orchestrator_final_switch_snapshot.csv").iloc[0]
    assert snap["current_primary_control"] == "A1_CONTROL"
    assert snap["best_forward_tracking_state"] == "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING"
    assert snap["threshold_source"] == "V21.170_SWITCH_TRIGGER_THRESHOLD_CALIBRATION_R1"
    assert snap["calibration_mode"] == "conservative_default"
    assert "matured 5D/10D/20D observations" in snap["next_required_condition"]


def test_artifact_index_key_files_exist_and_non_empty():
    s = summary()
    artifacts = read_csv("orchestrator_artifact_index.csv")
    assert s["artifact_index_key_files_ok"] is True
    required_stages = {"V21.169", "V21.171", "V21.172", "V21.173"}
    assert required_stages.issubset(set(artifacts["stage_id"]))
    assert artifacts["exists"].astype(str).str.lower().isin(["true"]).all()
    assert artifacts["non_empty"].astype(str).str.lower().isin(["true"]).all()


def test_policy_breach_errors_absent():
    log = read_csv("orchestrator_error_warning_log.csv")
    forbidden = {
        "UNEXPECTED_OFFICIAL_ADOPTION_ALLOWED",
        "UNEXPECTED_BROKER_ACTION_ALLOWED",
        "UNEXPECTED_PROTECTED_OUTPUTS_MODIFIED",
    }
    assert forbidden.isdisjoint(set(log["warning_type"]))
    assert summary()["error_count"] == 0
