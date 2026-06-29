import json
from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.144_FAIR_BASELINE_EXTENDED_STRATEGY_RETEST")
V143 = Path("outputs/v21/V21.143_RANDOM_UNIVERSE_AND_SURVIVORSHIP_ARTIFACT_AUDIT")

REQUIRED = [
    "V21.144_summary.json",
    "V21.144_fair_baseline_metric_summary_all_period.csv",
    "V21.144_fair_baseline_metric_summary_by_regime.csv",
    "V21.144_strategy_vs_fair_baseline_matrix.csv",
    "V21.144_strategy_vs_A1_matrix.csv",
    "V21.144_left_tail_summary.csv",
    "V21.144_e_r1_fair_baseline_recheck.csv",
    "V21.144_d_and_d_r2a_fair_baseline_recheck.csv",
    "V21.144_a1_control_review.csv",
    "V21.144_comparison_to_v21_141_142_143.csv",
    "V21.144_invalid_trials.csv",
    "V21.144_pit_status_audit.csv",
    "V21.144_readable_report.txt",
]


def summary():
    with (OUT / "V21.144_summary.json").open("r", encoding="utf-8") as f:
        return json.load(f)


def test_required_outputs_and_controls():
    assert OUT.exists()
    for name in REQUIRED:
        assert (OUT / name).exists(), name
    s = summary()
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert s["strategy_adoption_allowed"] is False
    assert s["research_only"] is True


def test_v21_143_recommended_fair_baselines_used():
    assert (V143 / "V21.143_summary.json").exists()
    s = summary()
    used = set(s["fair_baselines_used"].split("|"))
    assert "RANDOM_SECTOR_AND_AGE_MATCHED_TO_STRATEGY" in used
    assert "RANDOM_2020_COVERAGE_ONLY_EQUAL_WEIGHT" in used
    metrics = pd.read_csv(OUT / "V21.144_fair_baseline_metric_summary_all_period.csv")
    assert used.issubset(set(metrics["baseline_name"]))


def test_recheck_outputs_exist_and_nonempty():
    assert not pd.read_csv(OUT / "V21.144_e_r1_fair_baseline_recheck.csv").empty
    d = pd.read_csv(OUT / "V21.144_d_and_d_r2a_fair_baseline_recheck.csv")
    assert {"D_WEIGHT_OPTIMIZED_R1", "D_R2A_REPEATED_LOSER_SOFT_PENALTY"}.issubset(set(d["strategy_id"]))
    assert not pd.read_csv(OUT / "V21.144_a1_control_review.csv").empty


def test_pit_status_for_every_strategy_and_non_pit_diagnostic():
    pit = pd.read_csv(OUT / "V21.144_pit_status_audit.csv")
    assert not pit.empty
    assert pit["strategy_id"].notna().all()
    non_pit = pit[~pit["pit_status"].eq("PIT_STRICT")]
    assert not non_pit.empty
    assert (non_pit["diagnostic_only"] == True).all()


def test_report_contains_status_and_decision():
    text = (OUT / "V21.144_readable_report.txt").read_text(encoding="utf-8")
    assert "FINAL_STATUS=" in text
    assert "DECISION=" in text
    s = summary()
    assert "FINAL_STATUS" in s
    assert "DECISION" in s
