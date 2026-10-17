"""Synthetic only: new snapshot valuation over the existing continuous engine."""
from dataclasses import replace
import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.evaluation import joint_frozen_history_r3 as adapter
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays
from scripts.v22.corporate_action_transition_r1 import (
    CorporateActionTransition, SourceBackedEntitlementEvent, SourceBackedTerminalEvent,
    RAW_OLD_SHARE_COORDINATE, USD_PER_RAW_OLD_SHARE,
)


def fixture():
    dates = pd.bdate_range("2024-01-02", periods=7)
    tickers = np.asarray([f"S{i:02}" for i in range(20)])
    prices = np.full((7, 20), 100.)
    market = MarketArrays(dates, tickers, prices.copy(), prices.copy(), adv=np.full(prices.shape, 1e8),
        signal_asof=[(d+pd.Timedelta(hours=16)).tz_localize("America/New_York") for d in dates])
    scores = np.broadcast_to(np.linspace(.01, .02, 20), prices.shape).copy()
    return market, scores, {}, np.zeros(prices.shape, bool)


def freeze_for(market, scores, events, quality, **changes):
    freeze = adapter.FrozenHistoryAccountFreeze(
        "SYNTHETIC_B_FROZEN_HISTORY_R3", "LEGACY_PARENT_RESEARCH_ID", "SYNTHETIC_RUN",
        "d"*64, adapter.input_digests(market, scores, events, quality), adapter.source_pins(),
        "Synthetic named raw common-share snapshot; historical availability/revision unknown",
        synthetic=True)
    return replace(freeze, **changes)


def run(inputs=None, freeze=None, expected_sha=None):
    market, scores, events, quality = inputs or fixture()
    freeze = freeze or freeze_for(market, scores, events, quality)
    return adapter.run_frozen_history_controls(market, scores, event_inputs=events,
        uncertified_quality_only=quality, freeze=freeze,
        expected_freeze_sha256=expected_sha or freeze.digest())


def test_two_controls_share_same_source_continuous_engine_3000_10bps_zero_fee_interest():
    inputs = fixture(); before = adapter.input_digests(*inputs)
    result = run(inputs)
    replay = result.replay
    assert len(replay.metadata["path_ids"]) == 2
    assert all("SYNTHETIC_B_FROZEN_HISTORY_R3::" in path for path in replay.metadata["path_ids"])
    assert replay.daily.groupby("path_id").first().cash.eq(3000).all()
    assert result.physical_account_replays == 2 and result.physical_fit_count == 0
    assert all(row["mechanism_accounting_consistent"] for row in result.qualification_by_path.values())
    np.testing.assert_allclose(replay.fills.transaction_cost, replay.fills.benchmark_notional*.001)
    assert replay.fills.transaction_fee.eq(0).all()
    assert replay.metadata["account_config"]["cash_interest"] == 0
    assert replay.metadata["account_config"]["transaction_cost_bps"] == 0
    assert replay.daily.certified_nav.isna().all()
    assert not replay.daily.certified_NAV.any() and not replay.daily.strict_PIT_promotion_eligible.any()
    assert replay.metadata["source_authority"] == replay.metadata["historical_revision"] == "UNKNOWN"
    np.testing.assert_allclose(replay.daily.research_raw_snapshot_value, replay.daily.nav)
    assert before == adapter.input_digests(*inputs)
    assert replay.metadata["annual_reset"] is False


def test_uncertified_quality_keeps_engine_prior_marks_but_snapshot_uses_current_raw_close():
    market, scores, events, quality = fixture()
    market.quality[2, 0] = True; quality[2, 0] = True
    market.open[2, 0] = 123.; market.close[2, 0] = 125.
    original_quality = market.quality.copy()
    result = run((market, scores, events, quality))
    day = result.replay.daily[result.replay.daily.date.eq(market.dates[2])]
    position = result.replay.positions[result.replay.positions.date.eq(market.dates[2]) & result.replay.positions.ticker.eq("S00")]
    assert position.stale.all()
    assert position.mark.eq(100).all()  # The unchanged engine retained its prior mark.
    assert day.stale_count.gt(0).all()
    assert day.research_raw_snapshot_value.gt(day.engine_original_nav).all()
    assert day.mechanism_accounting_consistent.all() and day.certified_nav.isna().all()
    for row in day.itertuples():
        held = result.replay.positions[result.replay.positions.date.eq(row.date) & result.replay.positions.path_id.eq(row.path_id)]
        expected = row.cash+sum(p.fractional_shares*market.close[2, np.flatnonzero(market.tickers == p.ticker)[0]] for p in held.itertuples())
        assert row.research_raw_snapshot_value == pytest.approx(expected)
    np.testing.assert_array_equal(market.quality, original_quality)
    assert all(q["mechanism_accounting_consistent"] for q in result.qualification_by_path.values())
    assert not any(q["certified_NAV"] for q in result.qualification_by_path.values())


def test_quality_cannot_be_reclassified_without_an_explicit_frozen_source_only_mask():
    market, scores, events, quality = fixture()
    market.quality[2, 0] = True
    result = run((market, scores, events, quality))
    assert not all(q["mechanism_accounting_consistent"] for q in result.qualification_by_path.values())
    day = result.replay.daily[result.replay.daily.date.eq(market.dates[2])]
    assert day.research_raw_snapshot_value.notna().all()
    assert day.mechanism_account_value.isna().all()
    assert day.stale_count.gt(0).all()


@pytest.mark.parametrize("mutation", ["negative", "2026"])
def test_material_numeric_or_clock_gaps_block_before_account_call(mutation, monkeypatch):
    market, scores, events, quality = fixture()
    if mutation == "close_missing": market.close[2, 0] = np.nan
    if mutation == "open_missing": market.open[2, 0] = np.nan
    if mutation == "negative": market.close[2, 0] = -1.
    if mutation == "missing_score": scores[2, 0] = np.nan
    if mutation == "missing_adv": market.adv[2, 0] = np.nan
    if mutation == "2026": market.dates = market.dates+pd.DateOffset(years=2)
    freeze = freeze_for(market, scores, events, quality)
    def forbidden(*args, **kwargs): raise AssertionError("numeric/clock gap reached the account")
    monkeypatch.setattr(adapter.common, "run_continuous_account", forbidden)
    with pytest.raises(adapter.FrozenHistoryAccountBlocked): run((market, scores, events, quality), freeze)


def test_absent_held_current_quote_cannot_use_prior_marks_for_snapshot_value():
    market, scores, events, quality = fixture()
    for mask in (market.row_present, market.input_present, market.new_buy_eligible): mask[2, 0] = False
    market.open[2, 0] = np.nan; market.close[2, 0] = np.nan
    result = run((market, scores, events, quality))
    day = result.replay.daily[result.replay.daily.date.eq(market.dates[2])]
    assert day.nav.notna().all() and day.stale_count.gt(0).all()
    assert day.research_raw_snapshot_value.isna().all() and day.mechanism_account_value.isna().all()
    assert not all(q["mechanism_accounting_consistent"] for q in result.qualification_by_path.values())


@pytest.mark.parametrize("mutation", ["old_id", "strict", "certified", "coordinate", "contradiction", "fee", "freeze_sha", "source", "payload"])
def test_scientific_identity_and_binding_mutations_are_rejected(mutation):
    inputs = fixture(); freeze = freeze_for(*inputs); original = freeze.digest()
    if mutation == "old_id": freeze = replace(freeze, research_id=freeze.parent_research_id)
    if mutation == "strict": freeze = replace(freeze, strict_PIT_promotion_eligible=True)
    if mutation == "certified": freeze = replace(freeze, certified_NAV=True)
    if mutation == "coordinate": freeze = replace(freeze, raw_price_coordinate="ADJUSTED_CLOSE")
    if mutation == "contradiction": freeze = replace(freeze, identity_coordinate_consistent=False)
    if mutation == "fee": freeze = replace(freeze, fee_bps=10.)
    if mutation == "freeze_sha":
        with pytest.raises(adapter.FrozenHistoryAccountBlocked): run(inputs, freeze, "e"*64)
        return
    if mutation == "source": freeze = replace(freeze, source_sha256={"other": "a"*64})
    if mutation == "payload": inputs[1][2, 0] = .9
    with pytest.raises(adapter.FrozenHistoryAccountBlocked): run(inputs, freeze)


def test_unresolved_economic_event_remains_blocked_despite_finite_prices_and_source_quality_mask():
    market, scores, events, quality = fixture()
    market.quality[2, 0] = True; quality[2, 0] = True
    events["unsupported_events"] = [dict(ticker="S00", effective_date=str(market.dates[2].date()),
        reason="UNRESOLVED_ECONOMIC_RIGHT", source_reference="synthetic://unresolved", source_fingerprint="a"*64)]
    result = run((market, scores, events, quality))
    assert not result.replay.accounting_exceptions.empty
    assert not any(q["mechanism_accounting_consistent"] for q in result.qualification_by_path.values())
    assert result.replay.daily.research_raw_snapshot_value.notna().all()
    assert result.replay.daily.loc[result.replay.daily.date.ge(market.dates[2]), "mechanism_account_value"].isna().all()


def entitlement_args(events):
    mapping = {"secS00": "S00"}
    return dict(entitlement_enabled=True, entitlement_events=tuple(events), entitlement_security_tickers=mapping,
        entitlement_source_binding=dict(status="SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND", source_fingerprint="d"*64,
            event_fingerprints=[event.event_fingerprint for event in events], security_tickers=mapping,
            quantity_coordinate=RAW_OLD_SHARE_COORDINATE))


def test_share_transform_and_cash_receivables_reuse_same_ca_coordinates_without_double_count():
    market, scores, events, quality = fixture()
    split = CorporateActionTransition("2024-01-04", "FORWARD_SPLIT", "secS00", "secS00", "S00", "S00", 2., 0.,
        "TIER2_LOCAL_CANONICAL", "synthetic://split", "a"*64)
    dividend = SourceBackedEntitlementEvent("div", "CASH_DIVIDEND", "secS00", "S00",
        "2024-01-04", "2024-01-04", "2024-01-06", "2024-01-03 12:00:00+00:00", 10., "USD",
        USD_PER_RAW_OLD_SHARE, RAW_OLD_SHARE_COORDINATE, "TIER2_LOCAL_CANONICAL", "synthetic://div", "c"*64)
    market.open[2:, 0] = market.close[2:, 0] = 45.
    events.update(corporate_actions=(split,), corporate_action_known_at={split.event_fingerprint: "2024-01-03 12:00:00+00:00"})
    events.update(entitlement_args([dividend]))
    result = run((market, scores, events, quality))
    assert result.replay.metadata["entitlement_lifecycle_enabled"]
    assert not result.replay.entitlements.empty
    assert result.replay.daily.receivable_value_usd.gt(0).any()
    np.testing.assert_allclose(result.replay.daily.research_raw_snapshot_value, result.replay.daily.nav)
    assert all(q["mechanism_accounting_consistent"] for q in result.qualification_by_path.values())
    assert result.replay.metadata["snapshot_previous_mark_substitution"] is False


def test_terminal_missing_settlement_retains_exceptions_and_blocks_mechanism_value():
    market, scores, events, quality = fixture()
    terminal = SourceBackedTerminalEvent("terminal", "secS00", "S00", "2024-01-04 14:30:00+00:00",
        "2024-01-03 12:00:00+00:00", 105., "USD", USD_PER_RAW_OLD_SHARE, RAW_OLD_SHARE_COORDINATE,
        "synthetic://quantity", "a"*64, "TIER1_ISSUER_REGULATOR_EXCHANGE", "synthetic://terminal", "b"*64)
    events.update(entitlement_args([terminal]))
    result = run((market, scores, events, quality))
    assert result.replay.metadata["terminal_lifecycle_enabled"]
    assert not result.replay.accounting_exceptions.empty
    assert not any(q["mechanism_accounting_consistent"] for q in result.qualification_by_path.values())
    assert result.replay.entitlements.remaining_raw_shares.dropna().eq(0).any()
    assert result.replay.daily.loc[result.replay.daily.date.ge(market.dates[2]), "mechanism_account_value"].isna().all()


@pytest.mark.parametrize("mutation", ["close_missing", "open_missing", "missing_score", "missing_adv"])
def test_actual_dependency_gaps_preserve_shared_trace_and_block_mechanism_qualification(mutation):
    market, scores, events, quality = fixture()
    if mutation == "close_missing": market.close[2, 0] = np.nan
    if mutation == "open_missing": market.open[2, 0] = np.nan
    if mutation == "missing_score": scores[2, 0] = np.nan
    if mutation == "missing_adv": market.adv[0, 0] = np.nan
    result = run((market, scores, events, quality))
    assert not all(q["mechanism_accounting_consistent"] for q in result.qualification_by_path.values())
    if mutation == "missing_score":
        assert all(q["selection_input_gaps"] for q in result.qualification_by_path.values())
        assert np.isnan(scores[2, 0])
    if mutation == "missing_adv":
        assert result.replay.execution_results.reason.eq("MISSING_SIGNAL_ADV").any()
    if mutation in {"close_missing", "open_missing"}:
        day = result.replay.daily[result.replay.daily.date.eq(market.dates[2])]
        assert day.nav.notna().all() and day.research_raw_snapshot_value.isna().all()


def test_unrelated_unrequested_raw_nan_rows_do_not_expand_control_dependencies():
    market, scores, events, quality = fixture()
    market.open[0, 0] = np.nan  # No opening holdings or execution on first date.
    market.open[3, 0] = market.close[3, 0] = np.nan
    market.input_present[:, 0] = market.new_buy_eligible[:, 0] = False
    market.adv[:, 0] = np.nan; scores[:, 0] = np.nan
    original_open, original_close = market.open.copy(), market.close.copy()
    result = run((market, scores, events, quality))
    assert all(q["mechanism_accounting_consistent"] for q in result.qualification_by_path.values())
    assert "S00" not in result.replay.positions.ticker.values
    assert len(result.replay.metadata["ticker_order"]) == 20
    np.testing.assert_array_equal(market.open, original_open)
    np.testing.assert_array_equal(market.close, original_close)


def test_actual_missing_next_open_rejects_original_order_without_a_fabricated_fill():
    market, scores, events, quality = fixture()
    market.open[1, 0] = np.nan
    result = run((market, scores, events, quality))
    rejected = result.replay.execution_results[result.replay.execution_results.ticker.eq("S00") &
        result.replay.execution_results.execution_date.eq(market.dates[1])]
    assert rejected.reason.eq("MISSING_OR_INVALID_OPEN").all()
    assert rejected.status.eq("REJECTED").all()
    assert result.replay.fills[result.replay.fills.ticker.eq("S00") &
        result.replay.fills.execution_date.eq(market.dates[1])].empty
    assert not all(q["actual_execution_inputs_complete"] for q in result.qualification_by_path.values())
    assert not all(q["mechanism_accounting_consistent"] for q in result.qualification_by_path.values())
