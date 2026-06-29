import json
from pathlib import Path

import pandas as pd

from scripts.v21.v21_172_switch_governance_compact_daily_report_r1 import main


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.172_SWITCH_GOVERNANCE_COMPACT_DAILY_REPORT_R1"
REQUIRED = [
    "compact_switch_governance_snapshot.csv",
    "compact_switch_blocker_summary.csv",
    "compact_switch_action_flags.csv",
    "compact_switch_watchlist.csv",
    "V21.172_compact_switch_governance_daily_report.txt",
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


def test_required_outputs_exist_and_report_non_empty():
    assert OUT.exists()
    for name in REQUIRED:
        assert (OUT / name).exists(), name
    report = (OUT / "V21.172_compact_switch_governance_daily_report.txt").read_text(encoding="utf-8")
    assert len(report.strip()) > 100
    assert "Conclusion:" in report


def test_validation_summary_parseable_and_decision_valid():
    s = summary()
    assert s["stage"] == "V21.172_SWITCH_GOVERNANCE_COMPACT_DAILY_REPORT_R1"
    assert s["final_decision"] in ALLOWED


def test_wait_maturity_under_current_insufficient_maturity():
    s = summary()
    if s["insufficient_historical_calibration_data"] is True:
        assert s["final_decision"] == "WAIT_MORE_MATURITY"
    blockers = read_csv("compact_switch_blocker_summary.csv")
    maturity = blockers[blockers["blocker"].eq("insufficient_forward_maturity")]
    assert not maturity.empty
    assert str(maturity["active"].iloc[0]).lower() in {"true", "1"}


def test_action_flags_block_role_review_adoption_and_broker():
    s = summary()
    flags = read_csv("compact_switch_action_flags.csv").iloc[0]
    assert s["role_review_required"] is False
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert s["one_day_outperformance_switch_allowed"] is False
    assert str(flags["role_review_required"]).lower() in {"false", "0"}
    assert str(flags["official_adoption_allowed"]).lower() in {"false", "0"}
    assert str(flags["broker_action_allowed"]).lower() in {"false", "0"}
    assert str(flags["one_day_outperformance_switch_allowed"]).lower() in {"false", "0"}


def test_snapshot_current_control_and_forward_state():
    snap = read_csv("compact_switch_governance_snapshot.csv").iloc[0]
    assert snap["current_primary_control"] == "A1_CONTROL"
    assert snap["best_forward_tracking_state"] == "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING"
    assert snap["final_decision"] == "WAIT_MORE_MATURITY"
    assert snap["threshold_source"] == "V21.170_SWITCH_TRIGGER_THRESHOLD_CALIBRATION_R1"
    assert str(snap["calibration_defaults_used"]).lower() in {"true", "1"}


def test_watchlist_contains_required_states():
    watch = read_csv("compact_switch_watchlist.csv")
    states = set(watch["watch_state"].astype(str))
    for required in [
        "A1_CONTROL",
        "C_R2_CHALLENGER",
        "AI_BOTTLENECK_THEME",
        "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING",
        "E_R1_DEFENSIVE_CANDIDATE",
        "SOFT_CAP",
        "D_ORIGINAL",
        "DRAM_ONLY",
    ]:
        assert required in states


def test_dram_only_not_official_portfolio_strategy():
    watch = read_csv("compact_switch_watchlist.csv")
    dram = watch[watch["watch_state"].eq("DRAM_ONLY")]
    assert not dram.empty
    assert set(dram["eligibility_class"]) == {"execution_fallback_only"}
    assert not dram["official_portfolio_strategy"].astype(str).str.lower().isin(["true", "1"]).any()
    assert summary()["dram_only_official_portfolio_strategy"] is False


def test_missing_input_files_warn_not_fabricated_pass_results():
    s = summary()
    if s["source_warning_count"] > 0:
        assert any(w["warning_type"] == "SOURCE_MISSING_WARNING" for w in s["warnings"])
    blockers = read_csv("compact_switch_blocker_summary.csv")
    source_blocker = blockers[blockers["blocker"].eq("source_missing_warnings")]
    assert not source_blocker.empty
    if str(source_blocker["active"].iloc[0]).lower() in {"true", "1"}:
        assert s["source_warning_count"] > 0


def test_no_protected_or_action_outputs_enabled():
    s = summary()
    assert s["changed_protected_file_count"] == 0
    assert s["research_only"] is True
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
