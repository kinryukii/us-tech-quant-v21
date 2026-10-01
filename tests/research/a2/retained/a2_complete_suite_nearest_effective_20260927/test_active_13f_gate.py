import pandas as pd
import pytest

from active_13f_gate import validate_active_13f_pool
from engine import run_replay


def example():
    timing = pd.DataFrame({
        "quarter": ["2025Q3", "2025Q4", "2026Q1"],
        "latest_filing_date": pd.to_datetime(["2025-11-14", "2026-02-18", "2026-05-15"]),
        "quarter_effective_date": pd.to_datetime(["2025-11-21", "2026-02-25", "2026-05-22"]),
    })
    panel = pd.DataFrame({
        "signal_date": pd.to_datetime(["2026-02-24", "2026-02-25", "2026-05-21", "2026-05-22"]),
        "ticker": ["AAA"] * 4,
        "quarter": ["2025Q3", "2025Q4", "2025Q4", "2026Q1"],
        "new_buy_eligible": [True] * 4,
    })
    panel = panel.merge(timing, on="quarter", validate="many_to_one")
    return panel, timing


def test_old_effective_quarter_remains_buyable_until_successor_takes_effect():
    panel, timing = example()
    audit = validate_active_13f_pool(panel, timing, quarter_column="quarter")
    assert audit["status"] == "PASS"
    assert audit["carry_forward_rows"] == 2
    assert audit["carry_forward_days"] == 2
    assert audit["new_buy_eligible_rows"] == 4


@pytest.mark.parametrize("row,quarter", [(0, "2025Q4"), (1, "2025Q3")])
def test_uneffective_new_quarter_and_expired_old_quarter_both_rejected(row, quarter):
    panel, timing = example()
    panel.loc[row, "quarter"] = quarter
    with pytest.raises(ValueError, match="latest effective quarter"):
        validate_active_13f_pool(panel, timing, quarter_column="quarter")


def test_obsolete_strict_previous_quarter_buy_flag_rejected():
    panel, timing = example()
    panel.loc[0, "new_buy_eligible"] = False
    with pytest.raises(ValueError, match="obsolete or missing new-buy flag"):
        validate_active_13f_pool(panel, timing, quarter_column="quarter")


def test_carried_active_quarter_can_submit_and_fill_a_new_buy():
    panel, timing = example()
    day = panel.iloc[:1].copy()
    validate_active_13f_pool(day, timing, quarter_column="quarter")
    calendar = pd.DatetimeIndex(pd.to_datetime(["2026-02-24", "2026-02-25"]))
    prices = pd.DataFrame({
        "ticker": ["AAA", "AAA"], "trade_date": calendar,
        "open": [100.0, 100.0], "close": [100.0, 100.0],
    })
    result = run_replay(prices, calendar, day, lambda *_: {"AAA": .10})
    assert list(result.trades.side) == ["BUY"]
    assert result.trades.iloc[0].signal_date == calendar[0]
    assert result.trades.iloc[0].execution_date == calendar[1]
