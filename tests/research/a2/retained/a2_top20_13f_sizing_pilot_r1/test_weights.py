from weights import allocate, portfolio_share
import pandas as pd
import pytest
from run import build_weights


def test_hand_calculated_dollar_and_complete_share():
    base = {"A": 0.5, "B": 0.5}
    values = {("f1", "A"): 100.0, ("f1", "B"): 100.0,
              ("f2", "A"): 80.0, ("f2", "B"): 20.0}
    assert allocate(base, {"A": 180.0, "B": 120.0}) == ({"A": 0.6, "B": 0.4}, "WEIGHTED")
    weights, status = portfolio_share(base, ("f1", "f2"), values, {"f1": 1000.0, "f2": 100.0})
    assert status == "WEIGHTED"
    assert abs(weights["A"] - 0.75) < 1e-15
    assert abs(weights["B"] - 0.25) < 1e-15


def test_missing_and_zero_behaviors():
    base = {"A": 0.4, "B": 0.6}
    assert allocate(base, {"A": None}) == (base, "UNKNOWN_INPUT")
    assert allocate(base, {}) == (base, "ZERO_OBSERVED_AMOUNT")
    assert allocate(base, {"A": 2}) == ({"A": 1.0, "B": 0.0}, "WEIGHTED")
    assert allocate({"A": 0.0, "B": 0.0}, {"A": None}) == ({"A": 0.0, "B": 0.0}, "ZERO_EXPOSURE")
    assert portfolio_share(base, ("f1", "f2"), {}, {"f1": 1000.0}) == (base, "UNKNOWN_FULL_DENOMINATOR")


def test_pit_quarter_switch_and_old_supplement_cannot_roll_back():
    names = [f"S{i:02d}" for i in range(20)]
    signals = pd.DataFrame([{"signal_date": pd.Timestamp(date), "ticker": name, "a2_rank": i + 1}
                            for date in ("2024-05-01", "2024-06-01") for i, name in enumerate(names)])
    intervals = pd.DataFrame([{"report_quarter": quarter, "ticker": "S00", "effective_end": pd.Timestamp("2025-12-31"),
                               "mapping_status": "RESOLVED", "aggregate_value_usd": amount,
                               "source_filing": quarter, "cusip": "000000001", "institution_support_count": 1}
                              for quarter, amount in (("2023Q4", 100.0), ("2024Q1", 200.0))])
    timing = pd.DataFrame([
        {"report_quarter": "2023Q4", "report_date": pd.Timestamp("2023-12-31"),
         "latest_included_filing_timestamp": pd.Timestamp("2024-04-15"), "effective_date": pd.Timestamp("2024-04-22"),
         "effective_end": pd.Timestamp("2024-05-20")},
        {"report_quarter": "2024Q1", "report_date": pd.Timestamp("2024-03-31"),
         "latest_included_filing_timestamp": pd.Timestamp("2024-05-25"), "effective_date": pd.Timestamp("2024-05-30"),
         "effective_end": pd.Timestamp("2025-12-31")},
    ])
    _, targets, status = build_weights(signals, intervals, timing)
    assert status.report_quarter.tolist() == ["2023Q4", "2024Q1"]
    assert targets[pd.Timestamp("2024-05-01")]["S00"] == 1.0
    assert targets[pd.Timestamp("2024-06-01")]["S00"] == 1.0
    future = timing.copy()
    future.loc[0, "effective_date"] = pd.Timestamp("2024-05-02")
    with pytest.raises(RuntimeError, match="UNKNOWN_13F_CLOCK"):
        build_weights(signals, intervals, future)
    old_supplement = pd.concat([timing, timing.iloc[[0]].assign(effective_date=pd.Timestamp("2024-06-15"))])
    with pytest.raises(AssertionError):
        build_weights(signals, intervals, old_supplement)
