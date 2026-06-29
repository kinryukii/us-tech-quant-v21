import json
from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST")
PRICE = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")


REQUIRED = [
    "V21.139_summary.json",
    "V21.139_strategy_metric_summary.csv",
    "V21.139_pairwise_winrate_matrix.csv",
    "V21.139_pairwise_excess_return_matrix.csv",
    "V21.139_seed_level_metrics.csv",
    "V21.139_trial_level_returns.csv",
    "V21.139_invalid_trials.csv",
    "V21.139_worst_trials_decomposition.csv",
    "V21.139_strategy_registry_used.csv",
    "V21.139_pit_status_audit.csv",
    "V21.139_readable_report.txt",
]


def load_summary():
    with (OUT / "V21.139_summary.json").open("r", encoding="utf-8") as f:
        return json.load(f)


def test_outputs_exist_and_controls():
    assert OUT.exists()
    for name in REQUIRED:
        assert (OUT / name).exists(), name
    summary = load_summary()
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["protected_outputs_modified"] is False
    assert summary["research_only"] is True
    assert summary["strategy_adoption_allowed"] is False


def test_no_future_dates_or_exit_beyond_panel():
    prices = pd.read_csv(PRICE, usecols=["date"])
    max_price_date = pd.to_datetime(prices["date"]).max()
    trials = pd.read_csv(OUT / "V21.139_trial_level_returns.csv")
    assert not trials.empty
    asof = pd.to_datetime(trials["sampled_asof_date"])
    exit_dates = pd.to_datetime(trials["exit_date"])
    assert (asof <= max_price_date).all()
    assert (exit_dates <= max_price_date).all()
    assert (exit_dates > asof).all()


def test_every_strategy_has_pit_status_and_non_pit_excluded():
    registry = pd.read_csv(OUT / "V21.139_strategy_registry_used.csv")
    pit = pd.read_csv(OUT / "V21.139_pit_status_audit.csv")
    assert not registry.empty
    assert set(registry["strategy_id"]) == set(pit["strategy_id"])
    assert pit["pit_status"].isin(["PIT_STRICT", "PIT_LITE", "SNAPSHOT_ONLY_INVALID_FOR_HISTORICAL_BACKTEST"]).all()
    non_pit = pit[pit["pit_status"].ne("PIT_STRICT")]
    if not non_pit.empty:
        assert (non_pit["adoption_grade_included"] == False).all()


def test_metric_rows_have_required_coverage_fields():
    metrics = pd.read_csv(OUT / "V21.139_strategy_metric_summary.csv")
    assert not metrics.empty
    required_cols = {"strategy_id", "horizon", "portfolio_size", "seed_coverage", "draw_coverage", "trial_count"}
    assert required_cols.issubset(metrics.columns)
    assert metrics["strategy_id"].notna().all()
    assert metrics["horizon"].isin(["5D", "10D", "20D"]).all()
    assert (metrics["seed_coverage"] > 0).all()
    assert (metrics["draw_coverage"] > 0).all()


def test_pairwise_matrices_square_and_include_a1():
    for name in ["V21.139_pairwise_winrate_matrix.csv", "V21.139_pairwise_excess_return_matrix.csv"]:
        df = pd.read_csv(OUT / name)
        assert "strategy_id" in df.columns
        row_names = set(df["strategy_id"])
        col_names = set(df.columns) - {"strategy_id"}
        assert row_names == col_names
        assert "A1_BASELINE_CONTROL" in row_names


def test_invalid_trials_recorded_not_silently_dropped():
    invalid = pd.read_csv(OUT / "V21.139_invalid_trials.csv")
    assert not invalid.empty
    assert "invalid_reason" in invalid.columns


def test_trial_columns_and_leakage_flags():
    trials = pd.read_csv(OUT / "V21.139_trial_level_returns.csv")
    assert "future_price_used_for_scoring" in trials.columns
    assert (trials["future_price_used_for_scoring"] == False).all()
    assert (trials["no_leakage_sample_date_ok"] == True).all()
    forbidden_score_cols = [c for c in trials.columns if "used_for_score" in c.lower() and trials[c].astype(str).str.lower().eq("true").any()]
    assert forbidden_score_cols == []


def test_non_pit_diagnostic_status_blocks_adoption_grade_conclusion():
    summary = load_summary()
    registry = pd.read_csv(OUT / "V21.139_strategy_registry_used.csv")
    if registry["pit_status"].ne("PIT_STRICT").any():
        assert "NO_ADOPTION" in summary["DECISION"] or "WAIT" in summary["DECISION"]
        assert summary["official_adoption_allowed"] is False
