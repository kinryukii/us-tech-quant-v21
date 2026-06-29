import json
from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST")
PANEL = Path("outputs/v21/V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020/V21.140_extended_adjusted_close_panel_2020_plus.csv")
V139 = Path("outputs/v21/V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST/V21.139_summary.json")

REQUIRED = [
    "V21.141_summary.json",
    "V21.141_strategy_metric_summary_all_period.csv",
    "V21.141_strategy_metric_summary_by_regime.csv",
    "V21.141_pairwise_winrate_matrix_all_period.csv",
    "V21.141_pairwise_winrate_matrix_by_regime.csv",
    "V21.141_pairwise_excess_return_matrix_all_period.csv",
    "V21.141_seed_level_metrics.csv",
    "V21.141_trial_level_returns.csv",
    "V21.141_invalid_trials.csv",
    "V21.141_missing_price_exclusions.csv",
    "V21.141_regime_robustness_score.csv",
    "V21.141_v21_139_comparison.csv",
    "V21.141_pit_status_audit.csv",
    "V21.141_worst_trials_decomposition.csv",
    "V21.141_readable_report.txt",
]

EXPECTED_REGIMES = {
    "COVID_CRASH_AND_REBOUND",
    "LIQUIDITY_GROWTH_BULL",
    "RATE_HIKE_TECH_BEAR",
    "AI_SEMICONDUCTOR_REACCELERATION",
    "LATE_SUPERCYCLE_CURRENT",
}


def summary():
    with (OUT / "V21.141_summary.json").open("r", encoding="utf-8") as f:
        return json.load(f)


def test_outputs_exist_and_controls():
    assert OUT.exists()
    for name in REQUIRED:
        assert (OUT / name).exists(), name
    s = summary()
    assert "FINAL_STATUS" in s
    assert "DECISION" in s
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert s["research_only"] is True


def test_trial_dates_cover_extended_period_and_do_not_exceed_panel():
    trials = pd.read_csv(OUT / "V21.141_trial_level_returns.csv")
    panel_dates = pd.to_datetime(pd.read_csv(PANEL, usecols=["date"])["date"])
    asof = pd.to_datetime(trials["sampled_asof_date"])
    exits = pd.to_datetime(trials["exit_date"])
    assert (asof < pd.Timestamp("2021-01-01")).any()
    assert (asof.dt.year == 2022).any()
    assert (exits <= panel_dates.max()).all()
    assert (exits > asof).all()


def test_pit_status_exists_and_non_pit_diagnostic_only():
    pit = pd.read_csv(OUT / "V21.141_pit_status_audit.csv")
    assert not pit.empty
    assert pit["pit_status"].notna().all()
    non_pit = pit[~pit["pit_status"].eq("PIT_STRICT")]
    assert not non_pit.empty
    assert (non_pit["diagnostic_only"] == True).all()
    assert (non_pit["adoption_grade_included"] == False).all()


def test_regime_metric_file_has_expected_labels():
    regimes = pd.read_csv(OUT / "V21.141_strategy_metric_summary_by_regime.csv")
    assert not regimes.empty
    assert EXPECTED_REGIMES.issubset(set(regimes["regime"]))


def test_invalid_trials_and_missing_exclusions_recorded():
    invalid = pd.read_csv(OUT / "V21.141_invalid_trials.csv")
    exclusions = pd.read_csv(OUT / "V21.141_missing_price_exclusions.csv")
    assert not invalid.empty
    assert "invalid_reason" in invalid.columns
    assert not exclusions.empty
    assert "exclusion_reason" in exclusions.columns


def test_v21_139_comparison_generated_if_source_exists():
    comp = pd.read_csv(OUT / "V21.141_v21_139_comparison.csv")
    if V139.exists():
        assert not comp.empty
        assert "comparison_item" in comp.columns


def test_pairwise_and_summary_fields():
    win = pd.read_csv(OUT / "V21.141_pairwise_winrate_matrix_all_period.csv")
    assert "strategy_id" in win.columns
    assert "A1_BASELINE_CONTROL" in set(win["strategy_id"])
    assert set(win["strategy_id"]) == (set(win.columns) - {"strategy_id"})
    s = summary()
    for key in [
        "best_strategy_vs_A1_by_10D_Top20_winrate_all_period",
        "best_strategy_vs_QQQ_by_10D_Top20_winrate_all_period",
        "best_left_tail_strategy_all_period",
        "remaining_blockers",
    ]:
        assert key in s
