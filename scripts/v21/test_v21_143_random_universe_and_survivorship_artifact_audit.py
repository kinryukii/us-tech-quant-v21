import json
from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.143_RANDOM_UNIVERSE_AND_SURVIVORSHIP_ARTIFACT_AUDIT")
V140 = Path("outputs/v21/V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020")
V141 = Path("outputs/v21/V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST")
V142 = Path("outputs/v21/V21.142_EXTENDED_REGIME_FAILURE_AND_E_R1_TAIL_ADVANTAGE_DECOMPOSITION")

REQUIRED = [
    "V21.143_summary.json",
    "V21.143_random_baseline_construction_audit.csv",
    "V21.143_survivorship_bias_audit.csv",
    "V21.143_universe_composition_by_strategy.csv",
    "V21.143_alternative_random_baseline_metrics.csv",
    "V21.143_regime_comparison_with_fair_random_baselines.csv",
    "V21.143_e_r1_recheck_against_fair_baselines.csv",
    "V21.143_d_and_d_r2a_recheck_against_fair_baselines.csv",
    "V21.143_artifact_classification.csv",
    "V21.143_missing_delisted_ticker_warning.csv",
    "V21.143_readable_report.txt",
]


def summary():
    with (OUT / "V21.143_summary.json").open("r", encoding="utf-8") as f:
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


def test_inputs_exist():
    assert (V140 / "V21.140_extended_adjusted_close_panel_2020_plus.csv").exists()
    assert (V141 / "V21.141_trial_level_returns.csv").exists()
    assert (V142 / "V21.142_summary.json").exists()


def test_alternative_random_baselines_generated():
    m = pd.read_csv(OUT / "V21.143_alternative_random_baseline_metrics.csv")
    assert not m.empty
    names = set(m["baseline_name"])
    for required in [
        "RANDOM_CURRENT_UNIVERSE_EQUAL_WEIGHT",
        "RANDOM_2020_COVERAGE_ONLY_EQUAL_WEIGHT",
        "RANDOM_IPO_AGE_MATCHED_TO_STRATEGY",
        "RANDOM_SECTOR_MATCHED_TO_STRATEGY",
        "RANDOM_SECTOR_AND_AGE_MATCHED_TO_STRATEGY",
    ]:
        assert required in names


def test_artifact_classification_and_rechecks_exist():
    cls = pd.read_csv(OUT / "V21.143_artifact_classification.csv")
    e = pd.read_csv(OUT / "V21.143_e_r1_recheck_against_fair_baselines.csv")
    d = pd.read_csv(OUT / "V21.143_d_and_d_r2a_recheck_against_fair_baselines.csv")
    assert not cls.empty
    assert cls["artifact_classification"].notna().all()
    assert not e.empty
    assert not d.empty
    assert {"D_WEIGHT_OPTIMIZED_R1", "D_R2A_REPEATED_LOSER_SOFT_PENALTY"}.issubset(set(d["strategy_id"]))


def test_report_contains_status_and_decision():
    text = (OUT / "V21.143_readable_report.txt").read_text(encoding="utf-8")
    assert "FINAL_STATUS=" in text
    assert "DECISION=" in text
    s = summary()
    assert "FINAL_STATUS" in s
    assert "DECISION" in s
