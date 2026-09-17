"""Synthetic economic-unit, missingness and causality checks; no data readers."""
import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.factors.economic_return_features import ACTION_FIELDS, classify_vendor_events, build_accrual_returns


def setup(closes=(100., 101., 102., 103., 104.)):
    calendar = pd.bdate_range("2020-01-02", periods=len(closes))
    prices = pd.DataFrame({"ticker": "ABC", "trade_date": calendar, "close": closes})
    coverage = pd.DataFrame([dict(ticker="ABC", coverage_start=calendar[0], coverage_end=calendar[-1],
                                 source_reference="synthetic successful query", source_fingerprint="synthetic-query",
                                 complete=True)])
    return prices, calendar, coverage


def event(date, **overrides):
    row = dict.fromkeys(ACTION_FIELDS, np.nan)
    row.update(ticker="ABC", ex_div_date=date, source_type="SYNTHETIC",
               source_reference="synthetic event", source_fingerprint="synthetic-event",
               sdk_schema_fingerprint="synthetic-full-sdk-schema", action_fields_complete=True,
               identity_unchanged=True, cash_unit_basis="PER_OLD_SHARE_SAME_CURRENCY",
               cash_unit_source_reference="synthetic issuer same-currency per-old-share declaration",
               cash_unit_source_fingerprint="synthetic-unit-evidence")
    row.update(overrides)
    return row


def classified(rows=()):
    return classify_vendor_events(pd.DataFrame(rows, columns=None if rows else ["ticker", "ex_div_date"]))


def calculate(prices, calendar, coverage, rows=()):
    return build_accrual_returns(prices, classified(rows), calendar, event_coverage=coverage)


def test_no_action_requires_query_coverage_and_adjacent_prices():
    prices, calendar, coverage = setup()
    out = calculate(prices, calendar, coverage)
    assert out.return_valid.tolist() == [False, True, True, True, True]
    np.testing.assert_allclose(out.daily_gross_return.iloc[1:], np.diff(prices.close) / prices.close.iloc[:-1])
    unknown = build_accrual_returns(prices, classified(), calendar)
    assert not unknown.return_valid.any()
    assert unknown.return_status.eq("EVENT_COVERAGE_UNCONFIRMED").all()
    assert unknown.quantity_multiplier.isna().all()
    assert unknown.event_status.eq("EVENT_ABSENCE_UNCONFIRMED").all()


def test_ordinary_special_cash_are_independent_old_share_amounts():
    prices, calendar, coverage = setup((100, 95.4, 96, 97, 98))
    e = event(calendar[1], per_cash_div=.1, special_dividend=4.5, company_act_flag=192,
              forward_adj_factorA=.954, forward_adj_factorB=0.)
    out = calculate(prices, calendar, coverage, [e])
    assert out.loc[1, "cash_per_old_share"] == pytest.approx(4.6)
    assert out.loc[1, "daily_gross_return"] == pytest.approx(0.)
    assert out.loc[1, "quantity_multiplier"] == 1
    # A different purely representational A/B cannot change q, D or the return.
    changed = dict(e, forward_adj_factorA=1., forward_adj_factorB=-4.6)
    alternative = calculate(prices, calendar, coverage, [changed])
    np.testing.assert_allclose(out.daily_gross_return, alternative.daily_gross_return, equal_nan=True)


@pytest.mark.parametrize("closes,ratio,components", [
    ((100, 50, 51, 52, 53), .5, {"split_base": 1, "split_ert": 2}),
    ((10, 100, 101, 102, 103), 10., {"join_base": 10, "join_ert": 1}),
])
def test_split_and_reverse_split_reciprocal_quantity(closes, ratio, components):
    prices, calendar, coverage = setup(closes)
    out = calculate(prices, calendar, coverage, [event(calendar[1], split_ratio=ratio, **components)])
    assert out.loc[1, "quantity_multiplier"] == pytest.approx(1 / ratio)
    assert out.loc[1, "cash_per_old_share"] == 0
    assert out.loc[1, "daily_gross_return"] == pytest.approx(0.)


def test_split_cash_mixed_is_rejected_even_when_each_field_is_clear():
    prices, calendar, coverage = setup((100, 49.5, 50, 51, 52))
    out = calculate(prices, calendar, coverage, [event(calendar[1], split_ratio=.5, per_cash_div=1.)])
    assert out.loc[1, "event_status"] == "UNSUPPORTED_MIXED_SPLIT_CASH"
    assert not out.loc[1, "return_valid"]
    assert out.loc[2, "return_valid"]  # a later independent return, not a bridge


def test_cash_unit_evidence_cannot_be_inferred_or_silently_scaled():
    prices, calendar, coverage = setup((100, 99, 100, 101, 102))
    for patch in ({"cash_unit_basis": "PER_NEW_SHARE"}, {"cash_unit_source_reference": ""},
                  {"cash_unit_source_fingerprint": ""}):
        out = calculate(prices, calendar, coverage, [event(calendar[1], per_cash_div=1., **patch)])
        assert out.loc[1, "event_status"] == "UNCONFIRMED_CASH_UNIT"
        assert np.isnan(out.loc[1, "daily_gross_return"])


@pytest.mark.parametrize("patch,status", [
    ({"spin_off_ratio": 10}, "UNSUPPORTED_COMPLEX_ACTION"),
    ({"per_share_div_ratio": 10}, "UNSUPPORTED_COMPLEX_ACTION"),
    ({"per_share_trans_ratio": 10}, "UNSUPPORTED_COMPLEX_ACTION"),
    ({"allotment_ratio": 10}, "UNSUPPORTED_COMPLEX_ACTION"),
    ({"stk_spo_ratio": 10}, "UNSUPPORTED_COMPLEX_ACTION"),
    ({"forward_adj_factorA": .9, "forward_adj_factorB": 0}, "UNEXPLAINED_ADJUSTMENT"),
    ({"forward_adj_factorA": 1., "forward_adj_factorB": 0}, "UNKNOWN_EVENT"),
    ({"per_cash_div": -1}, "MALFORMED_ACTION_VALUE"),
    ({"per_cash_div": np.inf}, "MALFORMED_ACTION_VALUE"),
    ({"company_act_flag": 64}, "MISSING_FLAGGED_ACTION_VALUE"),
    ({"company_act_flag": 1024}, "UNKNOWN_ACTION_FLAG"),
    ({"per_cash_div": 1, "identity_unchanged": False}, "UNKNOWN_SECURITY_IDENTITY"),
    ({"split_ratio": .5, "split_base": 1}, "PARTIAL_SPLIT_COMPONENTS"),
    ({"split_ratio": .5, "split_base": 2, "split_ert": 1}, "CONFLICTING_SPLIT_RATIO"),
    ({"split_ratio": 2, "split_base": 2, "split_ert": 1}, "CONFLICTING_SPLIT_DIRECTION"),
])
def test_unsupported_events_fail_closed_with_specific_evidence_status(patch, status):
    row = classified([event("2020-01-03", **patch)]).iloc[0]
    assert not row.event_supported
    assert row.event_status == status
    assert np.isnan(row.quantity_multiplier) and np.isnan(row.cash_per_old_share)


def test_partial_schema_or_missing_source_evidence_is_not_absent_action():
    row = pd.DataFrame([event("2020-01-03", per_cash_div=1.)])
    assert classify_vendor_events(row.drop(columns="special_dividend")).iloc[0].event_status == "INCOMPLETE_ACTION_EVIDENCE"
    row.loc[0, "source_fingerprint"] = ""
    assert classify_vendor_events(row).iloc[0].event_status == "INCOMPLETE_ACTION_EVIDENCE"


def test_missing_market_session_cannot_bridge_and_event_does_not_move():
    prices, calendar, coverage = setup()
    absent = prices.loc[prices.trade_date.ne(calendar[1])]
    out = calculate(absent, calendar, coverage, [event(calendar[1], per_cash_div=1.)])
    assert out.return_valid.tolist() == [False, False, False, True, True]
    assert out.loc[1, "event_present"] and not out.loc[2, "event_present"]
    assert out.loc[2, "cash_per_old_share"] == 0
    assert out.loc[3, "daily_gross_return"] == pytest.approx(103 / 102 - 1)


def test_future_price_and_event_perturbation_prefix_invariance_and_input_unchanged():
    prices, calendar, coverage = setup()
    before = prices.copy(deep=True)
    cutoff = calendar[2]
    prefix = calculate(prices.loc[prices.trade_date.le(cutoff)], calendar, coverage)
    changed = prices.copy()
    changed.loc[changed.trade_date.gt(cutoff), "close"] *= 20
    out = calculate(changed, calendar, coverage, [event(calendar[3], split_ratio=.05),
                                               event(calendar[4], spin_off_ratio=10)])
    pd.testing.assert_frame_equal(prefix, out.loc[out.trade_date.le(cutoff)].reset_index(drop=True))
    pd.testing.assert_frame_equal(prices, before)


def test_affine_accumulated_cash_counterexample_and_currency_scale_invariance():
    prices, calendar, coverage = setup((100, 99, 100, 101, 102))
    rows = [event(calendar[1], per_cash_div=1)]
    out = calculate(prices, calendar, coverage, rows)
    # After the dividend, one vintage's price+held cash gives 101/100-1,
    # whereas a new one-share position gives 100/99-1. They are different.
    affine_levels = np.array([100., 100., 101., 102., 103.])
    assert out.loc[2, "daily_gross_return"] == pytest.approx(100 / 99 - 1)
    assert out.loc[2, "daily_gross_return"] != pytest.approx(affine_levels[2] / affine_levels[1] - 1)
    scaled = prices.copy()
    scaled["close"] *= 7
    scaled_out = calculate(scaled, calendar, coverage, [event(calendar[1], per_cash_div=7)])
    np.testing.assert_allclose(out.daily_gross_return, scaled_out.daily_gross_return, equal_nan=True)


def test_active_noncalendar_event_and_duplicate_days_are_rejected():
    prices, calendar, coverage = setup()
    with pytest.raises(ValueError, match="outside authoritative"):
        calculate(prices, calendar, coverage, [event("2020-01-04", per_cash_div=1)])
    e = event(calendar[1], per_cash_div=1.)
    with pytest.raises(ValueError, match="duplicate event day"):
        classified([e, e])


def test_optional_dated_identity_requires_adjacency_without_permanent_deletion():
    prices, calendar, coverage = setup()
    transport = calculate(prices, calendar, coverage)
    assert not transport.identity_continuity_certified.any()
    assert transport.identity_status.eq("INHERITED_VENDOR_TRANSPORT_ONLY").all()
    prices["economic_security_id"] = ["old", "old", "", "new", "new"]
    out = calculate(prices, calendar, coverage)
    assert out.return_valid.tolist() == [False, True, False, False, True]
    assert out.identity_continuity_certified.tolist() == [False, True, False, False, True]
    assert out.loc[4, "prior_economic_security_id"] == "new"
    # Future identity changes cannot remove earlier valid observations.
    prefix = calculate(prices.iloc[:2], calendar, coverage)
    pd.testing.assert_frame_equal(prefix, out.iloc[:2].reset_index(drop=True))


def test_nonfinite_economic_component_is_classified_unsupported():
    row = classified([event("2020-01-03", per_cash_div=1e308, special_dividend=1e308)]).iloc[0]
    assert row.event_status == "NONFINITE_ECONOMIC_COMPONENT"
    assert not row.event_supported
