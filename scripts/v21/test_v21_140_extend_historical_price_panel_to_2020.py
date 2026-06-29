import json
from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020")
CANONICAL = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")

REQUIRED = [
    "V21.140_extended_ohlcv_panel_2020_plus.csv",
    "V21.140_extended_adjusted_close_panel_2020_plus.csv",
    "V21.140_price_coverage_by_ticker.csv",
    "V21.140_missing_data_report.csv",
    "V21.140_delisting_and_symbol_warning_report.csv",
    "V21.140_benchmark_coverage_report.csv",
    "V21.140_data_source_audit.csv",
    "V21.140_summary.json",
    "V21.140_readable_report.txt",
]


def summary():
    with (OUT / "V21.140_summary.json").open("r", encoding="utf-8") as f:
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


def test_extended_panel_date_bounds_and_latest_date():
    panel = pd.read_csv(OUT / "V21.140_extended_ohlcv_panel_2020_plus.csv", usecols=["symbol", "date", "close", "adjusted_close"])
    assert not panel.empty
    dates = pd.to_datetime(panel["date"])
    assert dates.min() < pd.Timestamp("2021-01-01")
    assert dates.max() >= pd.to_datetime(pd.read_csv(CANONICAL, usecols=["date"])["date"]).max()
    assert panel["symbol"].notna().all()
    assert panel["close"].notna().any()
    assert panel["adjusted_close"].notna().any()


def test_benchmark_coverage_present_if_available():
    bench = pd.read_csv(OUT / "V21.140_benchmark_coverage_report.csv")
    assert not bench.empty
    for ticker in ["QQQ", "SPY", "SOXX"]:
        row = bench[bench["symbol"].eq(ticker)]
        assert not row.empty, ticker
        assert bool(row.iloc[0]["has_2020_data"]) is True
        assert bool(row.iloc[0]["usable_for_20D"]) is True


def test_coverage_report_one_row_per_ticker():
    coverage = pd.read_csv(OUT / "V21.140_price_coverage_by_ticker.csv")
    assert not coverage.empty
    assert coverage["symbol"].is_unique
    assert coverage["coverage_ratio"].between(0, 1.1).all()
    assert {"first_available_date", "last_available_date", "usable_for_random_backtest_2020_plus"}.issubset(coverage.columns)


def test_missing_and_source_reports_generated():
    missing = pd.read_csv(OUT / "V21.140_missing_data_report.csv")
    source = pd.read_csv(OUT / "V21.140_data_source_audit.csv")
    assert "warning_flags" in missing.columns
    assert not source.empty
    assert "source_provider" in source.columns or "source_type" in source.columns


def test_no_protected_mutation_and_pit_warning():
    s = summary()
    assert s["pit_strict_possible_from_price_only"] is False
    assert "SURVIVORSHIP" in s["survivorship_bias_warning"]
    audit = pd.read_csv(OUT / "V21.140_data_source_audit.csv")
    assert not audit.astype(str).apply(lambda col: col.str.contains("WEB_FETCH_USED", case=False, na=False)).any().any()
