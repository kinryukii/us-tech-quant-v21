"""Synthetic cash/fee integration over the immutable shared order engine."""
from dataclasses import replace
from pathlib import Path
import ast
import hashlib

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.evaluation import consensus_cash_account as account
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2 import fast_account as owner


def market(dates=None, tickers=("A", "B"), days=6):
    dates = pd.DatetimeIndex(dates) if dates is not None else pd.bdate_range("2025-06-02", periods=days)
    shape = (len(dates), len(tickers))
    return owner.MarketArrays(dates, np.asarray(tickers), np.full(shape, 100.), np.full(shape, 100.),
        adv=np.full(shape, 1e8), signal_mask=np.arange(len(dates)) < len(dates)-1)


def fixed(weights):
    array = np.asarray(weights, float)
    def policy(di, context):
        values = array[di] if array.ndim == 3 else array
        return owner.TargetDecision(values, context.decision_mask.copy(), "synthetic")
    return policy


def test_fee_is_once_per_real_fill_and_quote_shares_formula():
    config = account.FeeConfig(25, .5)
    notionals = np.array([0., 100., 5.])
    np.testing.assert_allclose(account.fee_for_notional(notionals, config), [0., .75, .5125])
    quote = account.quote_transition_cost([.1, 0.], [0., .1], 3000., config)
    np.testing.assert_allclose(quote["fees"], account.fee_for_notional([300., 300.], config))
    assert quote["total_fee"] == 2.5
    assert quote["spread_slippage_added_separately"] is False
    with pytest.raises(ValueError):
        account.FeeConfig(20)
    with pytest.raises(ValueError):
        account.fee_for_notional([-1.], config)


def test_t2_t1_use_supplied_sessions_skip_holiday_never_invent_trailing_date():
    calendar = pd.DatetimeIndex(["2024-05-23", "2024-05-24", "2024-05-28", "2024-05-29", "2024-05-30"])
    assert account.settlement_date("2024-05-24", calendar) == pd.Timestamp("2024-05-29")
    assert account.settlement_date("2024-05-28", calendar) == pd.Timestamp("2024-05-29")
    assert account.settlement_date("2024-05-30", calendar) is None
    with pytest.raises(ValueError):
        account.settlement_date("2024-05-27", calendar)
    with pytest.raises(ValueError):
        account.validate_calendar(["2024-05-25"])


def test_opt_out_is_equivalent_to_original_engine_and_preserves_bytes():
    data = market()
    weights = np.zeros((5, 2, 2))
    weights[:, :, 0] = .40
    weights[2:, :, 0] = .20
    weights[2:, :, 1] = .30
    before = hashlib.sha256(Path(owner.__file__).read_bytes()).hexdigest()
    expected = owner.run_many(data, ["x", "y"], fixed(weights), initial_cash=3000., cost_bps=10., max_weight=.5)
    actual = account.run_cash_account(data, ["x", "y"], fixed(weights),
        fee_config=account.FeeConfig(10, 0, 0, False), max_weight=.5)
    for field in ("daily", "positions", "orders", "fills", "execution_results", "contexts"):
        a, b = getattr(actual, field), getattr(expected, field)
        for column in b.columns:
            if pd.api.types.is_numeric_dtype(b[column]):
                np.testing.assert_allclose(a[column], b[column], rtol=1e-12, atol=1e-8, equal_nan=True)
            else:
                pd.testing.assert_series_equal(a[column], b[column], check_names=False)
    assert hashlib.sha256(Path(owner.__file__).read_bytes()).hexdigest() == before == account.ENGINE_SHA
    assert actual.metadata["source_lineage"]["cash_fee_ast_anchor_count"] == 10
    assert actual.metadata["source_lineage"]["original_engine_unchanged"] is True


def test_unsettled_sale_is_nav_asset_but_cannot_fund_same_session_buy():
    dates = ["2024-05-28", "2024-05-29", "2024-05-30", "2024-05-31", "2024-06-03"]
    data = market(dates)
    weights = np.array([[[.95, 0.]], [[0., .95]], [[0., .95]], [[0., .95]]])
    seen = {}
    def policy(di, context):
        seen[di] = (context.settled_cash.copy(), context.unsettled_cash.copy())
        return fixed(weights)(di, context)
    replay = account.run_cash_account(data, ["x"], policy, max_weight=1.)
    sale_day = replay.daily.loc[replay.daily.date.eq(pd.Timestamp("2024-05-30"))].iloc[0]
    after = replay.daily.loc[replay.daily.date.eq(pd.Timestamp("2024-05-31"))].iloc[0]
    assert sale_day.unsettled_cash > 2800.
    assert sale_day.buy_notional < 160.
    assert sale_day.total_cash_assets > sale_day.settled_cash + 2800.
    assert after.unsettled_cash == 0.
    assert after.settlement_release > 2800.
    assert replay.settlement_ledger.status.tolist() == ["SETTLED"]
    assert after.buy_notional > 2500.
    assert seen[2][1][0] > 2800.
    for key in ("cash_identity_error_max", "cost_identity_error_max", "self_finance_error_max", "nav_identity_error_max"):
        assert replay.audit[key] < 1e-8
    np.testing.assert_allclose(replay.daily.nav,
        replay.daily.known_position_value + replay.daily.total_cash_assets, atol=1e-8)
    fills = replay.fills
    np.testing.assert_allclose(fills.transaction_cost, account.fee_for_notional(fills.notional, account.FeeConfig()))


def test_fixed_stress_fee_scales_buys_within_cash_and_no_fee_on_rejection():
    data = market(tickers=("A", "B"), days=3)
    weights = np.array([[[.5, .5]], [[.5, .5]]])
    config = account.FeeConfig(25, .5)
    replay = account.run_cash_account(data, ["x"], fixed(weights), fee_config=config, max_weight=.5, max_invested=1.)
    assert replay.daily.cash.min() >= 0.
    assert (replay.fills.notional >= 5.-1e-8).all()
    np.testing.assert_allclose(replay.fills.transaction_cost, account.fee_for_notional(replay.fills.notional, config))
    assert replay.audit["cash_identity_error_max"] < 1e-8
    assert replay.audit["cost_identity_error_max"] < 1e-8
    small = market(tickers=("A",), days=3)
    rejected = account.run_cash_account(small, ["x"], fixed([[[.001]], [[.001]]]), fee_config=config)
    assert rejected.fills.empty
    assert "BELOW_MINIMUM_TRADE" in rejected.execution_results.reason.tolist()
    assert "MISSING_SIGNAL_ADV" not in rejected.execution_results.reason.tolist()
    assert rejected.daily.transaction_cost_amount.sum() == 0.
    assert rejected.final_cash[0] == 3000.


def test_missing_open_and_reserved_hold_keep_units_names_cash_and_charge_no_fee():
    data = market(days=3)
    data.open[1, 0] = np.nan
    data.close[1, 0] = np.nan
    data.input_present[0, 0] = False
    data.initial_marks[0] = 100.
    weights = np.array([[[0., .1]], [[0., .1]]])
    replay = account.run_cash_account(data, ["x"], fixed(weights), initial_units=[1., 0.], max_positions=1)
    assert replay.final_units[0, 0] == 1.
    assert replay.final_units[0, 1] == 0.
    assert replay.fills.empty
    assert replay.daily.transaction_cost_amount.sum() == 0.
    assert replay.daily.actual_name_count.max() == 1


def test_corporate_action_hook_reuses_owner_projection_and_receivables_not_spent():
    data = market(tickers=("A",), days=3)
    data.signal_mask[:] = False
    data.open[1:, 0] = 50.
    data.close[1:, 0] = 50.
    data.initial_marks[0] = 100.
    def hook(di, date, units, cash):
        if di == 1:
            units = units * 2
        return units, cash, np.array([25.])
    replay = account.run_cash_account(data, ["x"], fixed([[0.]]), initial_units=[10.],
        corporate_action_hook=hook)
    np.testing.assert_allclose(replay.daily.nav, 4025.)
    np.testing.assert_allclose(replay.daily.corporate_receivable, 25.)
    assert replay.final_cash[0] == 3000.
    assert replay.final_units[0, 0] == 20.


def test_future_calendar_append_changes_no_prior_economic_decision_or_fill():
    data = market(days=3)
    weights = np.array([[[.1, 0.]], [[0., .1]]])
    first = account.run_cash_account(data, ["x"], fixed(weights))
    extended = data.dates.append(pd.DatetimeIndex(["2025-06-05", "2025-06-06"]))
    second = account.run_cash_account(data, ["x"], fixed(weights), settlement_calendar=extended)
    np.testing.assert_allclose(first.daily[["nav", "cash", "unsettled_cash"]], second.daily[["nav", "cash", "unsettled_cash"]])
    np.testing.assert_allclose(first.fills[["notional", "index_units", "transaction_cost"]], second.fills[["notional", "index_units", "transaction_cost"]])


def test_ast_anchor_failure_is_closed_without_source_mutation(monkeypatch):
    monkeypatch.setattr(account, "HOOK_AST_SHA", "0" * 64)
    with pytest.raises(ValueError, match="projection owner changed"):
        account.run_cash_account(market(), ["x"], fixed([[.1, 0.]]))

def test_subminimum_capacity_order_does_not_occupy_a_free_name_slot():
    data = market(tickers=("A", "B", "C"), days=3)
    data.adv[:, 0] = 300.  # one-percent capacity = USD3, below minimum
    data.open[1, 2] = np.nan  # failed C sale still occupies the live second slot
    data.initial_marks[2] = 100.
    replay = account.run_cash_account(data, ["x"], fixed([[.1, .09, 0.]]),
        initial_units=[0., 0., 1.], max_positions=2)
    assert replay.final_units[0, 0] == 0.
    assert replay.final_units[0, 1] > 0.
    assert set(replay.fills.loc[replay.fills.side.eq("BUY"), "ticker"]) == {"B"}


@pytest.mark.parametrize("operational", [False, True])
def test_small_full_exit_reclaims_slot_with_real_fee_and_settlement(operational):
    data = market(tickers=("A", "B"), days=3)
    data.initial_marks[0] = 100.
    if operational:
        data.operational_exits[data.dates[0]] = {
            "A": owner.OperationalEvidence("synthetic confirmed exit", data.signal_asof[0], "fixture")}
    config = account.FeeConfig(10, .5, 5, True)
    replay = account.run_cash_account(data, ["x"], fixed([[0., .1]]), fee_config=config,
        initial_units=[.04, 0.], max_positions=1)
    sell = replay.fills.loc[replay.fills.side.eq("SELL")].iloc[0]
    assert sell.ticker == "A" and sell.notional == pytest.approx(4.)
    assert sell.transaction_cost == pytest.approx(.504)
    assert replay.final_units[0, 0] == 0. and replay.final_units[0, 1] > 0.
    assert not replay.execution_results.reason.eq("LIVE_POSITION_LIMIT").any()
    assert replay.daily.loc[replay.daily.date.eq(data.dates[1]), "unsettled_cash"].iloc[0] == pytest.approx(3.496)
    assert replay.daily.loc[replay.daily.date.eq(data.dates[2]), "settlement_release"].iloc[0] == pytest.approx(3.496)
    quote = account.quote_transition_cost([4/3004, 0.], [0., .1], 3004., config)
    assert quote["fees"][0] == pytest.approx(.504)


def test_small_ordinary_reduction_keeps_minimum_and_nonprofitable_exit_rejected():
    data = market(tickers=("A",), days=2)
    data.initial_marks[0] = 100.
    config = account.FeeConfig(10, .5, 5, True)
    ordinary = account.run_cash_account(data, ["x"], fixed([[6/3010]]), fee_config=config,
        initial_units=[.1])
    assert ordinary.final_units[0, 0] == pytest.approx(.1)
    assert ordinary.fills.empty
    assert ordinary.execution_results.reason.eq("MINIMUM_TRADE_OR_FEE_EXCEEDS_PROCEEDS").any()
    tiny = account.run_cash_account(data, ["x"], fixed([[0.]]), fee_config=config,
        initial_units=[.004])
    assert tiny.final_units[0, 0] == pytest.approx(.004) and tiny.fills.empty
    quote = account.quote_transition_cost([.4/3000.4], [0.], 3000.4, config)
    assert quote["total_fee"] == 0.


def test_open_market_bank_holiday_is_not_cash_settlement_day():
    trades=pd.DatetimeIndex(["2025-10-10","2025-10-13","2025-10-14","2025-10-15"])
    settles=trades[trades!=pd.Timestamp("2025-10-13")]
    assert account.settlement_date("2025-10-10",settles,trading_calendar=trades)==pd.Timestamp("2025-10-14")
    assert account.settlement_date("2025-10-13",settles,trading_calendar=trades)==pd.Timestamp("2025-10-14")
    old_trades=pd.DatetimeIndex(["2023-10-05","2023-10-06","2023-10-09","2023-10-10","2023-10-11"])
    old_settles=old_trades[old_trades!=pd.Timestamp("2023-10-09")]
    assert account.settlement_date("2023-10-05",old_settles,trading_calendar=old_trades)==pd.Timestamp("2023-10-10")


def test_bank_holiday_replay_keeps_sale_proceeds_unspendable_until_settlement():
    data=market(dates=pd.DatetimeIndex(["2025-10-09","2025-10-10","2025-10-13","2025-10-14","2025-10-15"]))
    settles=data.dates[data.dates!=pd.Timestamp("2025-10-13")]
    replay=account.run_cash_account(data,["x"],fixed(np.asarray([[.1,0.],[0.,.1],[0.,.1],[0.,.1],[0.,.1]])[:,None,:]),settlement_calendar=settles)
    holiday=replay.daily.loc[replay.daily.date.eq(pd.Timestamp("2025-10-13"))].iloc[0]
    assert holiday.settlement_release==0 and holiday.unsettled_cash>0
    assert replay.daily.loc[replay.daily.date.eq(pd.Timestamp("2025-10-14")),"settlement_release"].iloc[0]>0
    assert replay.fills.loc[replay.fills.side.eq("SELL"),"settlement_date"].iloc[0]==pd.Timestamp("2025-10-14")


def test_quote_projection_composes_actual_fees_and_settlement():
    data=market(days=5)
    quality=data.quality.copy();quality[1,:]=True
    data=replace(data,quality=quality)
    weights=np.asarray([[.1,0.],[0.,.1],[0.,.1],[0.,.1],[0.,.1]])[:,None,:]
    proofs=[]
    replay=account.run_cash_account(data,["x"],fixed(weights),fee_config=account.FeeConfig(25,.5),
        usable_a=np.ones_like(data.quality),ledger_callback=lambda name,frame: proofs.append(frame.copy()) if name=="execution_coordinate_proof" else None)
    assert len(replay.fills)>0 and proofs
    assert replay.fills.iloc[0].execution_date==data.dates[1]
    assert np.isfinite(replay.daily.nav).all()
    assert replay.daily.cash_flow_identity_error.abs().max()<1e-8
    assert replay.daily.cost_identity_error.abs().max()<1e-8
    proof=pd.concat(proofs)
    assert proof.identity_error.max()<1e-8
    assert proof.actual_fee_verified_by_cash_owner.sum()>0
    assert proof.net_sale_cash_withheld_by_cash_owner.sum()>0
    lineage=replay.metadata["source_lineage"]
    assert lineage["quote_execution_projection"]["normalized_reverse_projection_exact"] is True
    assert lineage["cash_fee_ast_anchor_count"]==10
    assert "QUANTITY_NOTIONAL" in lineage["quote_proof_scope"]


def test_quote_execution_mask_requires_exact_bool_shape():
    data=market()
    for bad in (np.ones_like(data.open),np.ones((1,1),bool)):
        with pytest.raises(ValueError,match="bool mask"):
            account.run_cash_account(data,["x"],fixed([[0.,0.]]),usable_a=bad)
