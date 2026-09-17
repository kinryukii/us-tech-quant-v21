"""Synthetic-only fixed month/timing/coverage and inherited R4 fee checks."""
import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.factors import intraday_continuation as module
from scripts.research.a2.factors.intraday_continuation import build_intraday_continuation, one_session_group_return, VALUE_COLUMNS


def fixture():
    calendar = pd.bdate_range("2019-12-30", "2020-03-04").difference(
        pd.to_datetime(["2020-01-01", "2020-01-20", "2020-02-17"]))
    rows = []
    r = .003 * np.sin(np.arange(len(calendar)) * .7)
    r[calendar.get_loc("2020-01-17")] = .08
    for ticker, multiplier in (("AAA", 1), ("BBB", -.4)):
        for n, date in enumerate(calendar):
            opening = 100 + n  # raw price level need not be cross-day continuous
            rows.append(dict(ticker=ticker, trade_date=date, open=opening,
                             close=opening * (1 + multiplier * r[n])))
    prices = pd.DataFrame(rows)
    panel = pd.DataFrame([(date, ticker) for date in calendar for ticker in ("BBB", "AAA")],
                         columns=["signal_date", "ticker"])
    return prices, calendar, panel, r


def test_month_end_signal_next_session_and_exact_compound_formula():
    prices, calendar, panel, r = fixture()
    out = build_intraday_continuation(prices, calendar, panel, compute_values=True)
    pd.testing.assert_frame_equal(out[["signal_date", "ticker"]], panel)
    a = out.loc[out.ticker.eq("AAA")].set_index("signal_date")
    row = a.loc["2020-01-31"]
    assert row.measurement_month == "2020-01"
    assert row.measurement_start == pd.Timestamp("2020-01-02")
    assert row.measurement_end == row.factor_information_end_date == pd.Timestamp("2020-01-31")
    assert row.next_market_session == pd.Timestamp("2020-02-03")
    assert row.full_support and row.feature_available
    assert row.expected_session_count == row.observed_session_count == 21
    expected = np.prod(1 + r[calendar.to_period("M") == pd.Period("2020-01")]) - 1
    assert row.intraday_continuation_score == pytest.approx(expected)
    assert a.loc["2020-02-03", "intraday_continuation_score"] == pytest.approx(expected)
    assert a.loc["2020-01-30", "measurement_month"] == "2019-12"
    assert not a.loc["2020-01-30", "calendar_month_boundary_complete"]
    assert a.loc["2020-02-14", "next_market_session"] == pd.Timestamp("2020-02-18")
    assert row.next_session_gross_return == pytest.approx(r[calendar.get_loc("2020-02-03")])


def test_coverage_only_never_calls_value_math_or_exposes_result(monkeypatch):
    prices, calendar, panel, _ = fixture()
    before = prices.copy(deep=True)
    def forbidden(*args, **kwargs):
        raise AssertionError("value math called in coverage-only mode")
    # Replace only this module's numerical namespace. Pandas legitimately uses
    # scalar log(row_count) in its sorting algorithm, which is not price math.
    class GuardedNumpy:
        log = staticmethod(forbidden)
        expm1 = staticmethod(forbidden)
        def __getattr__(self, name):
            return getattr(np, name)
    monkeypatch.setattr(module, "np", GuardedNumpy())
    out = build_intraday_continuation(prices, calendar, panel, compute_values=False)
    assert out[list(VALUE_COLUMNS)].isna().all().all()
    assert not out.values_computed.any()
    assert "open" not in out and "close" not in out
    assert out.feature_available.any() and out.target_available.any()
    pd.testing.assert_frame_equal(before, prices)


def test_missing_month_bar_preserves_keys_and_does_not_skip_into_next_sample():
    prices, calendar, panel, _ = fixture()
    absent = prices.loc[~(prices.ticker.eq("AAA") & prices.trade_date.eq("2020-01-16"))]
    out = build_intraday_continuation(absent, calendar, panel, compute_values=True)
    assert len(out) == len(panel)
    a = out.loc[out.ticker.eq("AAA")].set_index("signal_date")
    row = a.loc["2020-01-31"]
    assert row.observed_session_count == 20 and row.expected_session_count == 21
    assert not row.full_support and np.isnan(row.intraday_continuation_score)
    # Each intraday bar is independent; missing Jan16 does not destroy Jan17 C/O.
    assert a.loc["2020-01-16", "target_available"]
    assert a.loc["2020-02-28", "full_support"]


def test_missing_next_close_changes_target_only_never_prior_signal_selection():
    prices, calendar, panel, _ = fixture()
    base = build_intraday_continuation(prices, calendar, panel, compute_values=True)
    prices.loc[prices.ticker.eq("AAA") & prices.trade_date.eq("2020-02-03"), "close"] = np.nan
    out = build_intraday_continuation(prices, calendar, panel, compute_values=True)
    index = out.index[out.ticker.eq("AAA") & out.signal_date.eq("2020-01-31")][0]
    assert out.loc[index, "feature_available"]
    assert out.loc[index, "intraday_continuation_score"] == base.loc[index, "intraday_continuation_score"]
    assert not out.loc[index, "target_available"]
    assert np.isnan(out.loc[index, "next_session_gross_return"])
    # Feb3's historical January support is intact, but current close is absent.
    row = out.loc[out.ticker.eq("AAA") & out.signal_date.eq("2020-02-03")].iloc[0]
    assert row.full_support and not row.current_close_available and not row.feature_available


def test_future_perturbation_and_price_prefix_leave_all_mature_evidence_unchanged():
    prices, calendar, panel, _ = fixture()
    cutoff = pd.Timestamp("2020-02-14")
    keys = panel.loc[panel.signal_date.le(cutoff)].reset_index(drop=True)
    base = build_intraday_continuation(prices, calendar, keys, compute_values=True)
    changed = prices.copy()
    changed.loc[changed.trade_date.gt(cutoff), "close"] *= 3
    future = build_intraday_continuation(changed, calendar, keys, compute_values=True)
    np.testing.assert_allclose(base.intraday_continuation_score, future.intraday_continuation_score, equal_nan=True)
    mature = base.next_market_session.le(cutoff)
    pd.testing.assert_frame_equal(base.loc[mature].reset_index(drop=True), future.loc[mature].reset_index(drop=True))
    short = build_intraday_continuation(prices.loc[prices.trade_date.le(cutoff)], calendar, keys, compute_values=True)
    np.testing.assert_allclose(base.intraday_continuation_score, short.intraday_continuation_score, equal_nan=True)
    pd.testing.assert_frame_equal(base.loc[mature].reset_index(drop=True), short.loc[mature].reset_index(drop=True))
    assert not short.loc[short.signal_date.eq(cutoff), "target_available"].any()


def test_same_bar_scale_cancels_but_additive_affine_transform_does_not():
    prices, calendar, panel, _ = fixture()
    base = build_intraday_continuation(prices, calendar, panel, compute_values=True)
    scaled = prices.copy()
    scaled[["open", "close"]] *= 7
    other = build_intraday_continuation(scaled, calendar, panel, compute_values=True)
    np.testing.assert_allclose(base[list(VALUE_COLUMNS)], other[list(VALUE_COLUMNS)], atol=1e-12, equal_nan=True)
    affine = prices.copy()
    affine[["open", "close"]] += 20
    wrong = build_intraday_continuation(affine, calendar, panel, compute_values=True)
    assert not np.allclose(base.intraday_continuation_score.dropna(), wrong.intraday_continuation_score.dropna())


def test_boundaries_missing_ticker_and_metadata_are_never_auto_certified():
    prices, calendar, panel, _ = fixture()
    panel = pd.concat([panel, pd.DataFrame([dict(signal_date=calendar[-2], ticker="MISSING")])], ignore_index=True)
    panel["identity_qualification"] = "CONDITIONAL_TRANSPORT_ONLY"
    out = build_intraday_continuation(prices, calendar, panel, compute_values=False)
    assert out.identity_qualification.eq("CONDITIONAL_TRANSPORT_ONLY").all()
    assert out.source_qualification.eq("UNREVIEWED_NOT_CERTIFIED").all()
    row = out.iloc[-1]
    assert row.ticker == "MISSING" and not row.feature_available and not row.target_available
    assert not out.loc[out.signal_date.eq(calendar[-1]), "next_session_known"].any()
    with pytest.raises(ValueError, match="duplicate signal_date"):
        build_intraday_continuation(prices, calendar, pd.concat([panel, panel.iloc[[0]]]))


@pytest.mark.parametrize("cost_bps", [10, 20])
def test_inherited_r4_both_legs_match_closed_form_and_no_leverage(cost_bps):
    values = pd.Series(np.linspace(-.12, .19, 20), index=[f"A{i:02}" for i in range(20)])
    out = one_session_group_return(values, cost_bps=cost_bps)
    c = cost_bps / 20000
    expected = (1-c)/(1+c) * (1+values.mean()) - 1
    assert out["status"] == "CONDITIONAL_BAR_FEE_SCENARIO"
    assert out["bar_return_cost_scenario"] == pytest.approx(expected)
    assert out["entry_cost_initial_capital"] > 0 and out["exit_cost_initial_capital"] > 0
    assert out["entry_cash_after"] >= 0 and out["ending_cash"] >= 0
    assert 0 < out["buy_scale"] <= 1
    assert out["ending_stock_exposure"] == 0
    assert out["main_r4_source_sha256"] == module.R4_SOURCE_SHA256


def test_unchanged_names_still_pay_two_legs_every_day():
    values = pd.Series(0., index=[f"A{i:02}" for i in range(20)])
    today = one_session_group_return(values)
    tomorrow = one_session_group_return(values)
    assert today == tomorrow
    assert today["gross_bar_return"] == 0
    assert today["bar_return_cost_scenario"] < 0
    assert today["total_cost_initial_capital"] == pytest.approx(-today["bar_return_cost_scenario"])


def test_missing_group_outcome_is_unavailable_without_dropping_a_name():
    values = pd.Series(.01, index=[f"A{i:02}" for i in range(20)])
    values.iloc[0] = np.nan
    out = one_session_group_return(values)
    assert out["status"] == "UNAVAILABLE_GROUP_BAR" and out["name_count"] == 20
    assert np.isnan(out["bar_return_cost_scenario"])
    with pytest.raises(ValueError, match="exactly 20"):
        one_session_group_return(values.dropna())
    with pytest.raises(ValueError, match="10 primary / 20 stress"):
        one_session_group_return(values, cost_bps=5)


def test_main_r4_definition_only_and_hash_guard(tmp_path, monkeypatch):
    helper = module.load_pinned_weight_rebalance()
    assert helper.__name__ == "calculate_weight_rebalance"
    assert set(helper.__globals__).issubset({"np", "Any", "__builtins__", "calculate_weight_rebalance"})
    bad_source = tmp_path / "changed_r4.py"
    bad_source.write_text("raise RuntimeError('full module must never execute')\n", encoding="utf-8")
    module.load_pinned_weight_rebalance.cache_clear()
    monkeypatch.setattr(module, "R4_SOURCE", bad_source)
    with pytest.raises(RuntimeError, match="MAIN_R4_SOURCE_HASH_MISMATCH"):
        module.load_pinned_weight_rebalance()
    module.load_pinned_weight_rebalance.cache_clear()
