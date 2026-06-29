import json
from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.148_E_R1_A1_PIT_LITE_REPLAY_DIAGNOSTIC_ONLY")
MANIFEST = Path("outputs/v21/V21.147_E_R1_A1_PIT_LITE_REPLAY_MANIFEST/V21.147_summary.json")
REQUIRED = [
    "V21.148_summary.json",
    "V21.148_e_r1_vs_a1_replay_metrics_all_period.csv",
    "V21.148_e_r1_vs_a1_replay_metrics_by_regime.csv",
    "V21.148_e_r1_vs_benchmark_metrics.csv",
    "V21.148_a1_vs_benchmark_metrics.csv",
    "V21.148_left_tail_replay_analysis.csv",
    "V21.148_seed_level_replay_metrics.csv",
    "V21.148_trial_level_replay_returns.csv",
    "V21.148_invalid_trials.csv",
    "V21.148_regime_robustness_summary.csv",
    "V21.148_prior_stage_consistency_check.csv",
    "V21.148_leakage_and_limitation_audit.csv",
    "V21.148_remaining_blockers.csv",
    "V21.148_readable_report.txt",
]


def summary():
    with (OUT / "V21.148_summary.json").open("r", encoding="utf-8") as f:
        return json.load(f)


def test_required_outputs_and_controls():
    assert OUT.exists()
    for name in REQUIRED:
        assert (OUT / name).exists(), name
    s = summary()
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["strategy_adoption_allowed"] is False
    assert s["pit_strict_claim_allowed"] is False
    assert s["adoption_grade_backtest"] is False


def test_manifest_read_and_no_violations():
    assert MANIFEST.exists()
    audit = pd.read_csv(OUT / "V21.148_leakage_and_limitation_audit.csv")
    assert not audit.empty
    assert (audit["forbidden_input_violation"] == False).all()
    assert (audit["future_leakage_violation"] == False).all()
    assert (audit["pit_strict_claim_violation"] == False).all()


def test_replay_metrics_have_strategies_buckets_horizons():
    trials = pd.read_csv(OUT / "V21.148_trial_level_replay_returns.csv")
    assert {"E_R1_REPAIRED", "A1_BASELINE_CONTROL"}.issubset(set(trials["strategy_id"]))
    assert {"Top20", "Top50"}.issubset(set(trials["portfolio_size"]))
    assert {"5D", "10D", "20D"}.issubset(set(trials["horizon"]))
    metrics = pd.read_csv(OUT / "V21.148_e_r1_vs_a1_replay_metrics_all_period.csv")
    assert {"Top20", "Top50"}.issubset(set(metrics["portfolio_size"]))
    assert {"5D", "10D", "20D"}.issubset(set(metrics["horizon"]))


def test_invalid_trials_and_report():
    invalid = pd.read_csv(OUT / "V21.148_invalid_trials.csv")
    assert not invalid.empty
    text = (OUT / "V21.148_readable_report.txt").read_text(encoding="utf-8")
    assert "FINAL_STATUS=" in text
    assert "DECISION=" in text
