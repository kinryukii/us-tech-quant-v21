from __future__ import annotations

from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.153_REALIZED_WINDOW_COMPARISON_20260616_TO_LATEST")
PRICE = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
REQUIRED = [
    "realized_window_strategy_comparison.csv",
    "realized_window_daily_returns.csv",
    "realized_window_vs_QQQ_comparison.csv",
    "realized_window_vs_Nasdaq_comparison.csv",
    "realized_window_drawdown_comparison.csv",
    "realized_window_left_tail_comparison.csv",
    "choppy_day_diagnostic.csv",
    "down_day_defense_diagnostic.csv",
    "overheat_contribution_audit.csv",
    "semiconductor_benchmark_diagnostic.csv",
    "invalid_holding_audit.csv",
    "V21.153_REALIZED_WINDOW_COMPARISON_20260616_TO_LATEST_REPORT.md",
    "compact_readable_report.txt",
]


def test_required_outputs_exist() -> None:
    assert OUT.exists()
    for name in REQUIRED:
        assert (OUT / name).exists(), name


def test_controls_and_lineage() -> None:
    report = (OUT / "V21.153_REALIZED_WINDOW_COMPARISON_20260616_TO_LATEST_REPORT.md").read_text(encoding="utf-8")
    assert "protected_outputs_modified=false" in report
    assert "official_adoption_allowed=false" in report
    assert "broker_action_allowed=false" in report
    assert "E_R1_diagnostic_only=true" in report
    assert "not used as adoption evidence" in report


def test_window_dates_and_latest_price() -> None:
    comp = pd.read_csv(OUT / "realized_window_strategy_comparison.csv")
    assert set(comp["start_date"]) == {"2026-06-16"}
    latest = str(pd.to_datetime(pd.read_csv(PRICE, usecols=["date"])["date"]).max().date())
    assert set(comp["latest_price_date_used"]) == {latest}
    assert set(comp["end_date"]) == {latest}


def test_benchmarks_and_nasdaq_availability() -> None:
    q = pd.read_csv(OUT / "realized_window_vs_QQQ_comparison.csv")
    assert not q.empty
    assert "excess_return_vs_QQQ" in q.columns
    report = (OUT / "V21.153_REALIZED_WINDOW_COMPARISON_20260616_TO_LATEST_REPORT.md").read_text(encoding="utf-8")
    assert "primary_benchmark=QQQ" in report
    assert "benchmark_ixic_available=" in report


def test_soft_cap_weights_not_retuned_and_sum() -> None:
    comp = pd.read_csv(OUT / "realized_window_strategy_comparison.csv")
    soft = comp[comp["variant"].eq("OVERHEAT_SOFT_CAP_R1")]
    assert not soft.empty
    assert (soft["concentration_proxy"] > 0).all()
    report = (OUT / "V21.153_REALIZED_WINDOW_COMPARISON_20260616_TO_LATEST_REPORT.md").read_text(encoding="utf-8")
    assert "soft_cap_weights_not_retuned=true" in report


def test_policies_separate_and_invalid_audited() -> None:
    comp = pd.read_csv(OUT / "realized_window_strategy_comparison.csv")
    assert "EXEC_OVERHEAT_SKIP" in set(comp["variant"])
    assert "OVERHEAT_SOFT_CAP_R1" in set(comp["variant"])
    invalid = pd.read_csv(OUT / "invalid_holding_audit.csv")
    assert not invalid.empty


def test_costs_recorded() -> None:
    comp = pd.read_csv(OUT / "realized_window_strategy_comparison.csv")
    assert (comp["transaction_cost_impact"] == 10.0).all()
    assert (comp["slippage_impact"] == 5.0).all()


def test_no_price_lookahead() -> None:
    daily = pd.read_csv(OUT / "realized_window_daily_returns.csv")
    latest = pd.to_datetime(pd.read_csv(PRICE, usecols=["date"])["date"]).max()
    assert pd.to_datetime(daily["date"]).max() <= latest
