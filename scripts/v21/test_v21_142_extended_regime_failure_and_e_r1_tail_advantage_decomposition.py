import json
from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.142_EXTENDED_REGIME_FAILURE_AND_E_R1_TAIL_ADVANTAGE_DECOMPOSITION")
V141 = Path("outputs/v21/V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST")

REQUIRED = [
    "V21.142_summary.json",
    "V21.142_e_r1_left_tail_decomposition.csv",
    "V21.142_d_original_risk_decomposition.csv",
    "V21.142_d_r2a_supercycle_dependency_decomposition.csv",
    "V21.142_b_regime_robustness_decomposition.csv",
    "V21.142_cross_strategy_regime_leadership.csv",
    "V21.142_worst_5pct_trial_overlap.csv",
    "V21.142_ticker_loss_contribution.csv",
    "V21.142_sector_industry_loss_contribution.csv",
    "V21.142_missing_data_artifact_audit.csv",
    "V21.142_readable_report.txt",
]


def summary():
    with (OUT / "V21.142_summary.json").open("r", encoding="utf-8") as f:
        return json.load(f)


def test_required_outputs_and_controls():
    assert OUT.exists()
    for name in REQUIRED:
        assert (OUT / name).exists(), name
    s = summary()
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert s["research_only"] is True
    assert s["strategy_adoption_allowed"] is False


def test_v21_141_inputs_exist():
    assert (V141 / "V21.141_trial_level_returns.csv").exists()
    assert (V141 / "V21.141_regime_robustness_score.csv").exists()
    assert (V141 / "V21.141_strategy_metric_summary_by_regime.csv").exists()


def test_key_strategies_appear_in_decomposition():
    d = pd.read_csv(OUT / "V21.142_d_original_risk_decomposition.csv")
    d2 = pd.read_csv(OUT / "V21.142_d_r2a_supercycle_dependency_decomposition.csv")
    b = pd.read_csv(OUT / "V21.142_b_regime_robustness_decomposition.csv")
    tick = pd.read_csv(OUT / "V21.142_ticker_loss_contribution.csv")
    e = pd.read_csv(OUT / "V21.142_e_r1_left_tail_decomposition.csv")
    assert "D_WEIGHT_OPTIMIZED_R1" in set(d["strategy_id"])
    assert "D_R2A_REPEATED_LOSER_SOFT_PENALTY" in set(d2["strategy_id"])
    assert "B_STATIC_MOMENTUM_BLEND" in set(b["strategy_id"])
    for strategy in ["A1_BASELINE_CONTROL", "B_STATIC_MOMENTUM_BLEND", "D_WEIGHT_OPTIMIZED_R1", "D_R2A_REPEATED_LOSER_SOFT_PENALTY", "E_R1_REPAIRED"]:
        assert strategy in set(tick["strategy_id"])
    assert e["comparison"].astype(str).str.contains("E_R1_vs_A1_BASELINE_CONTROL").any()


def test_worst_5pct_and_missing_artifact_non_empty():
    overlap = pd.read_csv(OUT / "V21.142_worst_5pct_trial_overlap.csv")
    miss = pd.read_csv(OUT / "V21.142_missing_data_artifact_audit.csv")
    assert not overlap.empty
    assert "worst_5pct_overlap_count" in overlap.columns
    assert not miss.empty
    assert "missing_data_artifact_major" in miss.columns


def test_report_contains_status_and_decision():
    text = (OUT / "V21.142_readable_report.txt").read_text(encoding="utf-8")
    assert "FINAL_STATUS=" in text
    assert "DECISION=" in text
    s = summary()
    assert "FINAL_STATUS" in s
    assert "DECISION" in s
