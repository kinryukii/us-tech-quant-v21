"""Synthetic conformance against immutable holding-aware execution v2.

No training, production prediction, 2026 input, or economic ranking is read.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from batch_engine import BatchMarket, run_batch, HoldingAwareDecision, OperationalExit, _reference


def fixture(names=("A", "B", "C"), days=7, signal_days=None):
    cal = pd.bdate_range("2025-06-02", periods=days)
    prices = pd.DataFrame([dict(ticker=t, trade_date=d, open=100., close=100., price_quality_warning=False)
                           for d in cal for t in names])
    chosen = cal[:days - 2] if signal_days is None else cal[list(signal_days)]
    features = pd.DataFrame([dict(ticker=t, signal_date=d, new_buy_eligible=True,
                                  avg_dollar_volume_20d=1e9, known_feature=1.) for d in chosen for t in names])
    return prices, cal, features


DAILY_FLOATS = ["cash", "nav", "certified_nav", "pretrade_nav", "open_posttrade_nav", "cash_weight",
                "known_position_value", "transaction_cost_amount", "buy_notional", "sell_notional",
                "buy_cash_scale", "net_return", "indicative_return", "turnover"]
DAILY_DISCRETE = ["valuation_status", "actual_name_count", "stale_count", "unknown_count",
                  "open_stale_count", "open_unknown_count", "blocked_order_count"]


def assert_conforms(batch, refs):
    for strategy, reference in refs.items():
        got = batch.daily.loc[batch.daily.strategy_id.eq(strategy)].sort_values("date").reset_index(drop=True)
        expected = reference.daily.sort_values("date").reset_index(drop=True)
        for column in DAILY_FLOATS:
            np.testing.assert_allclose(got[column], expected[column], rtol=1e-12, atol=1e-7, equal_nan=True, err_msg=column)
        for column in DAILY_DISCRETE:
            assert got[column].tolist() == expected[column].tolist(), column
        for column in ["cash_flow_identity_error", "nav_identity_error", "cost_identity_error", "open_self_finance_error"]:
            valid = got[column].dropna()
            assert valid.empty or valid.abs().max() < 1e-7
        pos = batch.positions.loc[batch.positions.strategy_id.eq(strategy)].sort_values(["date", "ticker"]).reset_index(drop=True) if len(batch.positions) else pd.DataFrame()
        old = reference.positions.sort_values(["date", "ticker"]).reset_index(drop=True)
        assert len(pos) == len(old)
        if len(old):
            assert list(zip(pos.date, pos.ticker)) == list(zip(old.date, old.ticker))
            for column in ["index_units", "mark", "market_value", "weight"]:
                np.testing.assert_allclose(pos[column], old[column], rtol=1e-12, atol=1e-7, equal_nan=True, err_msg=column)
            for column in ["stale", "unknown", "mark_source", "mark_date"]:
                assert pos[column].tolist() == old[column].tolist(), column
        trades = batch.trades.loc[batch.trades.strategy_id.eq(strategy)].sort_values(["execution_date", "side", "ticker"]).reset_index(drop=True) if len(batch.trades) else pd.DataFrame()
        oldtrades = reference.trades.sort_values(["execution_date", "side", "ticker"]).reset_index(drop=True)
        assert len(trades) == len(oldtrades)
        if len(oldtrades):
            for column in ["order_id", "signal_date", "execution_date", "ticker", "side", "action", "decision_semantic"]:
                assert trades[column].tolist() == oldtrades[column].tolist(), column
            for column in ["price", "notional", "index_units", "index_units_before", "index_units_after", "transaction_cost", "capacity_adv"]:
                np.testing.assert_allclose(trades[column], oldtrades[column], rtol=1e-12, atol=1e-7, equal_nan=True, err_msg=column)
        targets = batch.target_decisions.loc[batch.target_decisions.strategy_id.eq(strategy)].sort_values("order_id").reset_index(drop=True)
        oldtargets = reference.target_decisions.set_index("order_id").loc[targets.order_id].reset_index()
        for column in ["target_weight", "raw_model_weight", "current_weight", "current_units", "reserved_weight"]:
            np.testing.assert_allclose(targets[column], oldtargets[column], rtol=1e-12, atol=1e-8, equal_nan=True, err_msg=column)
        for column in ["decision_semantic", "order_type", "explicit_model_decision", "signal_reserved", "adaptation_reasons"]:
            assert targets[column].tolist() == oldtargets[column].tolist(), column
        executions = batch.execution_results.loc[batch.execution_results.strategy_id.eq(strategy)].sort_values(["order_id", "status"]).reset_index(drop=True) if len(batch.execution_results) else pd.DataFrame()
        oldexecutions = reference.execution_results.loc[reference.execution_results.order_id.isin(targets.order_id)].sort_values(["order_id", "status"]).reset_index(drop=True)
        assert len(executions) == len(oldexecutions)
        for column in ["order_id", "status", "reason", "actual_names_at_event"]:
            assert executions[column].tolist() == oldexecutions[column].tolist(), column
        raw = batch.raw_model_outputs.loc[batch.raw_model_outputs.strategy_id.eq(strategy)].sort_values("signal_date")
        expected_raw = reference.raw_model_outputs.sort_values("signal_date")
        assert [json.loads(x) for x in raw.model_decisions_json] == [json.loads(x) for x in expected_raw.model_decisions_json]


def fixed_callback(targets):
    def callback(day, context):
        weights = np.zeros_like(context["current_units"])
        for ticker, value in targets.items():
            weights[:, context["ticker_index"][ticker]] = value
        decided = np.zeros_like(weights, dtype=bool)
        for ticker in targets:
            decided[:, context["ticker_index"][ticker]] = context["decision_mask"][:, context["ticker_index"][ticker]]
        return dict(targets=weights, decided=decided)
    return callback


def compare_fixed(prices, cal, features, targets, *, market_kwargs=None, **kwargs):
    market_kwargs = market_kwargs or {}
    batch = run_batch(BatchMarket(prices, cal, features, **market_kwargs), fixed_callback(targets), ["s"], **kwargs)
    reference = _reference.run_replay(prices, cal, features,
        lambda day, ctx: HoldingAwareDecision({t: w for t, w in targets.items() if t in ctx.decision_tickers}),
        candidate="s", **market_kwargs, **kwargs)
    assert_conforms(batch, {"s": reference})
    return batch, reference


def test_simple_explicit_zero_exit_and_full_account_link():
    px, cal, fs = fixture(signal_days=[0])
    got, _ = compare_fixed(px, cal, fs, {"A": 0., "B": .1}, initial_cash=9000., initial_positions={"A": 10.}, max_positions=2)
    assert got.trades.loc[got.trades.side.eq("SELL"), "action"].iloc[0] == "EXIT"
    assert got.daily.cash.iloc[-1] > 0
    assert set(got.trades.order_id).issubset(set(got.target_decisions.order_id))
    assert not got.metadata["terminal_liquidation"]


def test_missing_input_preserves_units_and_signal_budget():
    px, cal, fs = fixture(signal_days=[0])
    fs = fs.loc[fs.ticker.ne("A")]
    px.loc[px.ticker.eq("A") & px.trade_date.ge(cal[1]), ["open", "close"]] = 200.
    got, _ = compare_fixed(px, cal, fs, {"B": .4}, initial_cash=1000., initial_positions={"A": 10.}, max_positions=2, max_weight=.5)
    assert got.positions.loc[got.positions.ticker.eq("A"), "index_units"].eq(10.).all()
    assert got.signal_contexts.reserved_weight.iloc[0] == pytest.approx(.5)


def test_omitted_output_reserves_live_slot_and_keeps_units():
    px, cal, fs = fixture(signal_days=[0])
    got, _ = compare_fixed(px, cal, fs, {"B": .1}, initial_cash=9000., initial_positions={"A": 10.}, max_positions=1)
    assert got.trades.empty
    assert got.signal_contexts.final_reserved_slots.iloc[0] == 1


def test_unexpected_sale_open_failure_preserves_actual_slot():
    px, cal, fs = fixture(signal_days=[0])
    px.loc[px.ticker.eq("A") & px.trade_date.eq(cal[1]), "open"] = np.nan
    got, _ = compare_fixed(px, cal, fs, {"A": 0., "B": .1}, initial_cash=9000., initial_positions={"A": 10.}, max_positions=1)
    assert got.trades.empty
    assert set(got.execution_results.loc[got.execution_results.status.eq("REJECTED"), "reason"]) == {"MISSING_OR_INVALID_OPEN", "LIVE_POSITION_LIMIT"}


def test_uncertified_and_missing_marks_do_not_create_fills():
    px, cal, fs = fixture()
    px.loc[px.ticker.eq("A") & px.trade_date.isin(cal[1:3]), "price_quality_warning"] = True
    px = px.loc[~(px.ticker.eq("B") & px.trade_date.eq(cal[2]))]
    px.loc[px.ticker.eq("C") & px.trade_date.eq(cal[3]), "close"] = np.nan
    got, _ = compare_fixed(px, cal, fs, {"A": .1, "B": .1, "C": .1}, initial_cash=9000., initial_positions={"A": 10.}, max_positions=3)
    assert got.daily.valuation_status.eq("stale").any()


def test_capacity_missing_adv_fee_and_cash_scale_conform():
    px, cal, fs = fixture()
    fs.loc[fs.ticker.eq("A"), "avg_dollar_volume_20d"] = 1000.
    fs.loc[fs.ticker.eq("B") & fs.signal_date.eq(cal[0]), "avg_dollar_volume_20d"] = np.nan
    got, _ = compare_fixed(px, cal, fs, {"A": .5, "B": .5, "C": .5}, initial_cash=1000., max_positions=3, max_weight=.5, max_invested=1., cost_bps=100., capacity_fraction=.01)
    buys = got.trades.loc[got.trades.side.eq("BUY") & got.trades.ticker.eq("A")]
    assert buys.notional.le(10. + 1e-8).all()
    assert np.allclose(got.trades.transaction_cost, got.trades.notional * .01)
    scaled, _ = compare_fixed(px, cal, fs, {"A": .5, "B": .5, "C": .5}, initial_cash=1000.,
                               max_positions=3, max_weight=.5, max_invested=1., cost_bps=100., capacity_fraction=None)
    assert (scaled.daily.buy_cash_scale < 1.).any()


def test_known_restriction_and_dated_operational_exit_conform():
    px, cal, fs = fixture(signal_days=[0])
    kr = pd.DataFrame([dict(signal_date=cal[0], ticker="A", known_at=cal[0], source_id="pause", reason="known pause", sell_restricted=True)])
    ops = {cal[0]: {"A": OperationalExit("mandate", cal[0], "mandate:1")}}
    got, _ = compare_fixed(px, cal, fs, {"B": .1}, market_kwargs=dict(known_restrictions=kr, operational_exits_by_signal=ops),
                           initial_cash=9000., initial_positions={"A": 10.}, max_positions=1)
    assert got.trades.empty
    assert "SIGNAL_KNOWN_SELL_RESTRICTION" in set(got.execution_results.reason)


def test_unknown_initial_nav_recovers_only_from_current_observed_mark():
    px, cal, fs = fixture()
    px.loc[px.ticker.eq("A") & px.trade_date.eq(cal[0]), ["open", "close"]] = np.nan
    got, _ = compare_fixed(px, cal, fs, {"B": .1}, initial_cash=9000., initial_positions={"A": 10.}, max_positions=2)
    assert got.daily.valuation_status.iloc[0] == "unknown"
    assert np.isnan(got.daily.nav.iloc[0])
    assert got.daily.valuation_status.iloc[1] == "certified"


def test_random_heterogeneous_accounts_conform_independently():
    rng = np.random.default_rng(20260928)
    names = tuple(f"T{i:02}" for i in range(8))
    px, cal, fs = fixture(names=names, days=24)
    values = 100. * np.exp(rng.normal(0., .02, size=(len(cal), len(names))).cumsum(axis=0))
    opens = values * np.exp(rng.normal(0., .01, size=values.shape))
    px["open"], px["close"] = opens.ravel(), values.ravel()
    px.loc[px.ticker.eq("T00") & px.trade_date.isin(cal[2:5]), "open"] = np.nan
    px.loc[px.ticker.eq("T03") & px.trade_date.isin(cal[7:9]), "price_quality_warning"] = True
    fs.loc[fs.ticker.eq("T04") & fs.signal_date.isin(cal[4:7]), "new_buy_eligible"] = False
    fs = fs.loc[~(fs.ticker.eq("T01") & fs.signal_date.isin(cal[10:13]))]
    fs["avg_dollar_volume_20d"] = rng.uniform(5e4, 3e7, len(fs))
    K = 5
    raw = rng.uniform(0., .1, (len(cal), K, len(names)))
    declared = rng.random(raw.shape) > .15
    raw[rng.random(raw.shape) < .2] = 0.
    day_i = {d: i for i, d in enumerate(cal)}
    ids = [f"s{k}" for k in range(K)]
    def callback(day, ctx):
        i = day_i[ctx["signal_date"]]
        return dict(targets=raw[i], decided=declared[i] & ctx["decision_mask"])
    market = BatchMarket(px, cal, fs)
    got = run_batch(market, callback, ids, max_positions=4)
    refs = {}
    for k, sid in enumerate(ids):
        def policy(day, ctx, k=k):
            i = day_i[ctx.signal_date]
            return HoldingAwareDecision({t: raw[i, k, names.index(t)] for t in ctx.decision_tickers if declared[i, k, names.index(t)]})
        refs[sid] = _reference.run_replay(px, cal, fs, policy, candidate=sid, max_positions=4, capacity_fraction=.01)
    assert_conforms(got, refs)
    assert got.daily.groupby("strategy_id").nav.last().nunique() == K


def test_next_open_change_cannot_change_signal_targets():
    px, cal, fs = fixture(signal_days=[0])
    a = run_batch(BatchMarket(px, cal, fs), fixed_callback({"A": .1, "B": .1}), ["s"])
    altered = px.copy()
    altered.loc[altered.trade_date.eq(cal[1]), "open"] *= 4.
    b = run_batch(BatchMarket(altered, cal, fs), fixed_callback({"A": .1, "B": .1}), ["s"])
    pd.testing.assert_frame_equal(a.raw_model_outputs, b.raw_model_outputs)
    pd.testing.assert_frame_equal(a.target_decisions, b.target_decisions)
    pd.testing.assert_frame_equal(a.signal_contexts, b.signal_contexts)


def test_saved_complete_decided_mask_covers_explicit_unheld_zeros(tmp_path):
    px, cal, fs = fixture(signal_days=[0])
    market = BatchMarket(px, cal, fs)
    def callback(day, ctx):
        target = np.zeros_like(ctx["current_units"])
        target[:, 0] = .1
        return dict(targets=target, decided=ctx["decision_mask"], raw=[{"source": "synthetic"}])
    got = run_batch(market, callback, ["s"], output_dir=tmp_path / "batch")
    coverage = np.load(tmp_path / "batch/decision_coverage/20250602.npz")
    decided = np.unpackbits(coverage["decided"], axis=1, bitorder="little")[:, :market.N].astype(bool)
    assert decided.all() and np.array_equal(coverage["targets"], [[.1, 0., 0.]])
    raw = pd.read_parquet(tmp_path / "batch/raw_model_outputs")
    assert raw.explicit_unheld_zero_count.iloc[0] == 2
    targets = pd.read_parquet(tmp_path / "batch/target_decisions")
    assert len(targets) == 1  # Complete zero evidence lives in the packed matrix.
    for table in ["daily", "positions", "target_decisions", "trades", "execution_results"]:
        saved = pd.read_parquet(tmp_path / "batch" / table)
        assert {"strategy_id", "decision_id", "order_id"}.issubset(saved)
    assert got.daily.date.nunique() == len(cal)


def test_future_or_unsourced_operational_evidence_rejected():
    px, cal, fs = fixture(signal_days=[0])
    for op in [OperationalExit("reason", cal[1], "source"), OperationalExit("reason", cal[0], "")]:
        with pytest.raises(ValueError):
            run_batch(BatchMarket(px, cal, fs, operational_exits_by_signal={cal[0]: {"A": op}}), fixed_callback({"B": .1}), ["s"])


def test_forward_label_columns_are_removed_from_callback():
    px, cal, fs = fixture(signal_days=[0])
    fs["y_next_open"] = 999.
    fs["target"] = 999.
    def callback(day, ctx):
        assert "y_next_open" not in day and "target" not in day
        return dict(targets=np.zeros_like(ctx["current_units"]), decided=ctx["decision_mask"])
    run_batch(BatchMarket(px, cal, fs), callback, ["s"])


def test_384_accounts_receive_independent_actual_state_arrays():
    px, cal, fs = fixture(days=5)
    K = 384
    ids = [f"s{k:03d}" for k in range(K)]
    seen = []
    def callback(day, ctx):
        assert ctx["current_units"].shape == (K, len(day))
        target = np.zeros_like(ctx["current_units"])
        target[:, 0] = np.arange(1, K + 1) / K * .1
        seen.append(ctx["current_units"].copy())
        return dict(targets=target, decided=ctx["decision_mask"])
    got = run_batch(BatchMarket(px, cal, fs), callback, ids)
    assert len(got.daily) == K * len(cal)
    assert got.daily.groupby("strategy_id").nav.last().nunique() == K
    assert seen[0].sum() == 0. and np.unique(seen[1][:, 0]).size == K
    assert got.daily.cash.ge(0).all() and got.daily.actual_name_count.le(20).all()


def test_saved_target_experts_have_same_account_row_mapping(tmp_path):
    px, cal, fs = fixture(signal_days=[0])
    def callback(day, ctx):
        targets = np.zeros_like(ctx["current_units"])
        experts = np.zeros((1, 13, len(day)))
        experts[0, :, 0] = .01 * np.arange(1, 14)
        targets[1, 0] = experts[0, :, 0].mean()
        return dict(targets=targets, decided=ctx["decision_mask"], expert_targets=experts,
                    expert_strategy_indices=[1], expert_names=[f"p{i}" for i in range(13)])
    got = run_batch(BatchMarket(px, cal, fs), callback, ["ordinary", "fusion"], output_dir=tmp_path / "experts")
    saved = np.load(tmp_path / "experts/decision_coverage/20250602_experts.npz")
    assert saved["targets"].shape == (1, 13, 3)
    assert saved["rowindices"].tolist() == [1]
    assert saved["expert_names"].tolist() == [f"p{i}" for i in range(13)]
    targets = pd.read_parquet(tmp_path / "experts/target_decisions")
    assert targets.loc[targets.strategy_id.eq("fusion"), "raw_model_weight"].iloc[0] == pytest.approx(saved["targets"][0, :, 0].mean())
