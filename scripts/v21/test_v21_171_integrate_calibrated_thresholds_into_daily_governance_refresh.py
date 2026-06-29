import json
from pathlib import Path

import pandas as pd

from scripts.v21.v21_171_integrate_calibrated_thresholds_into_daily_governance_refresh import main


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.171_INTEGRATE_CALIBRATED_THRESHOLDS_INTO_DAILY_GOVERNANCE_REFRESH"
REQUIRED = [
    "integrated_threshold_source_audit.csv",
    "integrated_daily_governance_snapshot.csv",
    "threshold_gate_evaluation_matrix.csv",
    "switch_state_threshold_pass_fail_matrix.csv",
    "integrated_decision_history.csv",
    "integrated_switch_decision_change_log.csv",
    "V21.171_integrated_threshold_governance_report.txt",
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
    assert summary()["stage"] == "V21.171_INTEGRATE_CALIBRATED_THRESHOLDS_INTO_DAILY_GOVERNANCE_REFRESH"


def test_v21_170_threshold_source_detected_or_warning_emitted():
    audit = read_csv("integrated_threshold_source_audit.csv")
    s = summary()
    assert set(audit["threshold_source"]) == {"V21.170_SWITCH_TRIGGER_THRESHOLD_CALIBRATION_R1"}
    if s["threshold_source_detected"]:
        assert audit["exists"].astype(str).str.lower().isin(["true"]).all()
        assert audit["parseable"].astype(str).str.lower().isin(["true"]).all()
    else:
        warning_types = [w["warning_type"] for w in s.get("warnings", [])]
        assert any("SOURCE_MISSING_WARNING" in w for w in warning_types)


def test_final_decision_enum_and_wait_maturity_when_insufficient():
    s = summary()
    assert s["final_decision"] in ALLOWED
    if s["calibration_matured_observations"] == 0:
        assert s["final_decision"] == "WAIT_MORE_MATURITY"
        assert s["role_review_required"] is False


def test_one_day_outperformance_cannot_trigger_role_review():
    s = summary()
    gates = read_csv("threshold_gate_evaluation_matrix.csv")
    assert s["one_day_outperformance_switch_allowed"] is False
    hyst = gates[gates["gate_category"].astype(str).eq("hysteresis_thresholds")]
    assert not hyst.empty
    assert not hyst["gate_pass"].astype(str).str.lower().isin(["true", "1"]).any()
    assert s["role_review_required"] is False


def test_research_only_policy_flags():
    s = summary()
    snap = read_csv("integrated_daily_governance_snapshot.csv").iloc[0]
    assert s["research_only"] is True
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert str(snap["official_adoption_allowed"]).lower() in {"false", "0"}
    assert str(snap["broker_action_allowed"]).lower() in {"false", "0"}


def test_dram_only_not_official_portfolio_strategy():
    matrix = read_csv("switch_state_threshold_pass_fail_matrix.csv")
    dram = matrix[matrix["state"].astype(str).eq("DRAM_ONLY")]
    assert not dram.empty
    assert set(dram["eligibility_class"]) == {"execution_fallback_only"}
    assert not dram["official_portfolio_strategy"].astype(str).str.lower().isin(["true", "1"]).any()
    assert summary()["dram_only_official_portfolio_strategy"] is False


def test_missing_threshold_files_warn_not_empirical_fabrication():
    audit = read_csv("integrated_threshold_source_audit.csv")
    s = summary()
    if not audit["exists"].astype(str).str.lower().isin(["true"]).all():
        warning_types = [w["warning_type"] for w in s.get("warnings", [])]
        assert any("SOURCE_MISSING_WARNING" in w for w in warning_types)
    assert s["calibration_defaults_used"] is True
    assert s["insufficient_historical_calibration_data"] is True


def test_decision_history_and_change_log_fields():
    history = read_csv("integrated_decision_history.csv")
    change = read_csv("integrated_switch_decision_change_log.csv").iloc[0]
    s = summary()
    assert not history.empty
    latest = history.sort_values("refresh_date").tail(1).iloc[0]
    assert latest["current_decision"] == s["final_decision"]
    assert latest["threshold_source"] == "V21.170_SWITCH_TRIGGER_THRESHOLD_CALIBRATION_R1"
    assert str(change["current_role_review_required"]).lower() in {"false", "0"}
    assert str(change["current_official_adoption_allowed"]).lower() in {"false", "0"}
    assert str(change["current_broker_action_allowed"]).lower() in {"false", "0"}


def test_expected_current_snapshot():
    snap = read_csv("integrated_daily_governance_snapshot.csv").iloc[0]
    assert snap["final_decision"] == "WAIT_MORE_MATURITY"
    assert snap["threshold_source"] == "V21.170_SWITCH_TRIGGER_THRESHOLD_CALIBRATION_R1"
    assert str(snap["calibration_defaults_used"]).lower() in {"true", "1"}
    assert str(snap["insufficient_historical_calibration_data"]).lower() in {"true", "1"}
    assert snap["current_primary_control"] == "A1_CONTROL"
    assert snap["best_forward_tracking_state"] == "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING"
