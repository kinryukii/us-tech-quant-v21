import json
from pathlib import Path

import pandas as pd

from scripts.v21.v21_170_switch_trigger_threshold_calibration_r1 import main


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.170_SWITCH_TRIGGER_THRESHOLD_CALIBRATION_R1"
REQUIRED = [
    "switch_trigger_threshold_table.csv",
    "maturity_requirement_table.csv",
    "excess_return_threshold_table.csv",
    "risk_blocker_threshold_table.csv",
    "hysteresis_threshold_table.csv",
    "execution_proxy_threshold_table.csv",
    "calibrated_switch_decision_policy.csv",
    "V21.170_switch_trigger_threshold_report.txt",
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


def test_required_outputs_and_summary_exist():
    assert OUT.exists()
    for name in REQUIRED:
        assert (OUT / name).exists(), name
    assert summary()["stage"] == "V21.170_SWITCH_TRIGGER_THRESHOLD_CALIBRATION_R1"


def test_all_threshold_values_present_and_non_null():
    for name in [
        "switch_trigger_threshold_table.csv",
        "maturity_requirement_table.csv",
        "excess_return_threshold_table.csv",
        "risk_blocker_threshold_table.csv",
        "hysteresis_threshold_table.csv",
        "execution_proxy_threshold_table.csv",
    ]:
        df = read_csv(name)
        assert not df.empty, name
        threshold_cols = [c for c in df.columns if "threshold" in c or "minimum" in c or "maximum" in c or c.endswith("_allowed")]
        assert threshold_cols, name
        assert not df[threshold_cols].isna().any().any(), name


def test_expected_default_threshold_values():
    maturity = read_csv("maturity_requirement_table.csv").set_index("horizon")
    assert int(maturity.loc["5D", "minimum_matured_observations"]) == 5
    assert int(maturity.loc["10D", "minimum_matured_observations"]) == 5
    assert int(maturity.loc["20D", "minimum_matured_observations"]) == 3
    excess = read_csv("excess_return_threshold_table.csv").set_index("horizon")
    assert float(excess.loc["10D", "minimum_win_rate_vs_A1"]) == 0.60
    assert float(excess.loc["20D", "minimum_win_rate_vs_A1"]) == 0.60
    assert float(excess.loc["10D", "minimum_avg_excess_return_vs_A1"]) == 0.005
    assert float(excess.loc["20D", "minimum_avg_excess_return_vs_A1"]) == 0.008


def test_final_decision_enums_are_valid():
    policy = read_csv("calibrated_switch_decision_policy.csv")
    assert set(policy["allowed_final_decision"]).issubset(ALLOWED_FINAL_DECISIONS)
    assert set(policy["allowed_final_decision"]) == ALLOWED_FINAL_DECISIONS
    assert summary()["final_decision"] in ALLOWED_FINAL_DECISIONS


def test_policy_flags_are_research_only_and_block_actions():
    s = summary()
    assert s["research_only"] is True
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert s["v21_168_outputs_modified"] is False
    assert s["v21_169_outputs_modified"] is False


def test_dram_only_not_official_portfolio_strategy():
    execution = read_csv("execution_proxy_threshold_table.csv")
    dram = execution[execution["execution_classification"].astype(str).eq("DRAM-only")]
    assert not dram.empty
    assert str(dram["official_portfolio_strategy"].iloc[0]).lower() in {"false", "0"}
    assert str(dram["adoption_allowed_by_this_stage"].iloc[0]).lower() in {"false", "0"}
    assert "execution_fallback_only" in str(dram["notes"].iloc[0])
    assert summary()["dram_only_official_portfolio_strategy"] is False


def test_one_day_outperformance_cannot_trigger_switch():
    hyst = read_csv("hysteresis_threshold_table.csv").iloc[0]
    assert str(hyst["one_day_outperformance_switch_allowed"]).lower() in {"false", "0"}
    assert int(hyst["minimum_hysteresis_consecutive_pass_days"]) == 3
    assert int(hyst["minimum_decision_stability_days_before_switch"]) == 3
    assert summary()["one_day_outperformance_switch_allowed"] is False


def test_insufficient_history_warning_not_failure():
    s = summary()
    warning_types = [w["warning_type"] for w in s.get("warnings", [])]
    assert "CALIBRATION_DEFAULTS_USED_WITH_INSUFFICIENT_HISTORY" in warning_types
    assert s["calibration_defaults_used"] is True
    assert s["insufficient_historical_calibration_data"] is True
    assert s["final_status"] == "PASS_DEFAULT_THRESHOLDS_CALIBRATED_WITH_WARNINGS"


def test_missing_optional_sources_warn_not_fabricated_pass():
    s = summary()
    warning_types = [w["warning_type"] for w in s.get("warnings", [])]
    assert any("SOURCE_MISSING_WARNING" in w for w in warning_types)
    threshold_table = read_csv("switch_trigger_threshold_table.csv")
    assert set(threshold_table["threshold_basis"]) == {"conservative_default"}
