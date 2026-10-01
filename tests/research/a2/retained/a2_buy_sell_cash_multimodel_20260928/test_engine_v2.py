"""Synthetic causal/accounting proofs; no production model fit or replay."""
import json
import numpy as np
import pandas as pd
import pytest

try:
    from .engine_v2 import run_replay, HoldingAwareDecision, OperationalExit
except ImportError:
    from engine_v2 import run_replay, HoldingAwareDecision, OperationalExit


def fixture(names=("A", "B"), signals=(0,), days=4):
    calendar = pd.bdate_range("2025-06-02", periods=days)
    prices = pd.DataFrame([{"ticker": t, "trade_date": d, "open": 100., "close": 100., "price_quality_warning": False}
                           for d in calendar for t in names])
    features = pd.DataFrame([{"ticker": t, "signal_date": calendar[i], "new_buy_eligible": True,
                              "avg_dollar_volume_20d": 1e9, "known_feature": 1.}
                             for i in signals for t in names],
                            columns=["ticker", "signal_date", "new_buy_eligible", "avg_dollar_volume_20d", "known_feature"])
    return prices, calendar, features


def invariant(result):
    assert result.daily.cash.ge(0).all()
    assert result.daily.actual_name_count.le(result.metadata["max_positions"]).all()
    for key in ["nav_identity_error", "cash_flow_identity_error", "cost_identity_error", "open_self_finance_error"]:
        values = result.daily[key].dropna()
        assert values.empty or values.abs().max() < 1e-7


def test_missing_input_holds_exact_units_and_reserves_signal_capital_slots():
    prices, cal, features = fixture()
    features = features.loc[features.ticker == "B"]
    seen = []

    def policy(day, ctx):
        seen.append(ctx)
        assert set(day.ticker) == {"B"}
        assert ctx.reserved_tickers == ("A",)
        assert ctx.reserved_slots == 1 and ctx.available_slots == 1
        assert ctx.reserved_weight == pytest.approx(.5)
        assert ctx.available_weight == pytest.approx(.45)
        return HoldingAwareDecision({"B": .4})

    prices.loc[(prices.ticker == "A") & prices.trade_date.ge(cal[1]), ["open", "close"]] = 200.
    result = run_replay(prices, cal, features, policy, initial_cash=1000, initial_positions={"A": 10},
                        max_positions=2, max_weight=.5)
    a = result.positions.loc[result.positions.ticker == "A"]
    assert a.index_units.eq(10).all()
    assert not result.trades.ticker.eq("A").any()
    decision = result.target_decisions.loc[result.target_decisions.ticker == "A"].iloc[0]
    assert decision.decision_semantic == "MODEL_NO_DECISION"
    assert decision.order_type == "HOLD_UNITS"
    assert not decision.explicit_model_decision
    assert len(seen) == 1
    invariant(result)


def test_present_input_but_omitted_output_preserves_holding_and_reprojects_budget():
    prices, cal, features = fixture()
    result = run_replay(prices, cal, features, lambda day, ctx: HoldingAwareDecision({"B": .1}),
                        initial_cash=9000, initial_positions={"A": 10}, max_positions=1)
    assert result.trades.empty
    assert result.positions.ticker.eq("A").all()
    context = result.signal_contexts.iloc[0]
    assert context.reserved_slots == 0 and context.final_reserved_slots == 1
    b = result.target_decisions.loc[result.target_decisions.ticker == "B"].iloc[0]
    assert b.raw_model_weight == .1 and b.adapted_target_weight == 0
    assert b.adaptation_reasons == "SIGNAL_RESERVED_SLOT_BUDGET"
    invariant(result)


def test_explicit_zero_with_input_is_active_exit_and_has_linked_raw_evidence():
    prices, cal, features = fixture(names=("A",))
    result = run_replay(prices, cal, features,
                        lambda day, ctx: HoldingAwareDecision({"A": 0.}, raw_model_outputs={"A": {"action_values": [3., 2., 1., 0., -1.]}}),
                        initial_cash=9000, initial_positions={"A": 10})
    assert result.trades.iloc[0].action == "EXIT"
    assert result.trades.iloc[0].decision_semantic == "MODEL_ACTIVE_EXIT"
    raw = result.raw_model_outputs.iloc[0]
    assert json.loads(raw.model_decisions_json) == {"A": 0.}
    assert json.loads(raw.raw_model_outputs_json)["A"]["action_values"] == [3., 2., 1., 0., -1.]
    assert raw.decision_id == result.target_decisions.iloc[0].decision_id == result.execution_results.iloc[0].decision_id
    assert result.daily.iloc[-1].cash == pytest.approx(9999)
    invariant(result)


def test_zero_allocation_to_unheld_name_is_not_called_active_exit():
    prices, cal, features = fixture(names=("A",))
    result = run_replay(prices, cal, features, lambda *_: HoldingAwareDecision({"A": 0.}))
    assert result.target_decisions.iloc[0].decision_semantic == "MODEL_ZERO_ALLOCATION"
    assert result.trades.empty


def test_operational_exit_is_dated_sourced_and_separate_from_model_exit():
    prices, cal, features = fixture()
    features = features.loc[features.ticker == "B"]
    action = OperationalExit("documented mandate withdrawal", cal[0], "memo:123")

    def policy(day, ctx):
        assert ctx.reserved_slots == 0  # Predeclared, known, executable operation releases a planned slot.
        return HoldingAwareDecision({"B": .1})

    result = run_replay(prices, cal, features, policy, initial_cash=9000, initial_positions={"A": 10}, max_positions=1,
                        operational_exits_by_signal={cal[0]: {"A": action}})
    sold = result.trades.loc[result.trades.side == "SELL"].iloc[0]
    assert sold.decision_semantic == "OPERATIONAL_EXIT_REQUIRED"
    assert result.operational_actions.iloc[0].source_id == "memo:123"
    assert set(result.trades.ticker) == {"A", "B"}
    invariant(result)


@pytest.mark.parametrize("known_offset,source", [(1, "memo:future"), (0, "")])
def test_operational_exit_rejects_future_or_unsourced_evidence(known_offset, source):
    prices, cal, features = fixture()
    action = OperationalExit("reason", cal[known_offset], source)
    with pytest.raises(ValueError):
        run_replay(prices, cal, features, lambda *_: HoldingAwareDecision(operational_exits={"A": action}),
                   initial_positions={"A": 10})


def test_signal_known_restriction_is_reserved_and_not_released_by_next_open():
    prices, cal, features = fixture()
    restrictions = pd.DataFrame([dict(signal_date=cal[0], ticker="A", known_at=cal[0],
                                     source_id="known:trade-pause", reason="known restriction", sell_restricted=True)])
    seen = []

    def policy(day, ctx):
        seen.append(ctx)
        assert "A" not in set(day.ticker)
        assert ctx.available_slots == 0
        return HoldingAwareDecision({"B": .1})

    result = run_replay(prices, cal, features, policy, initial_cash=9000, initial_positions={"A": 10},
                        max_positions=1, known_restrictions=restrictions)
    assert result.trades.empty
    assert seen[0].reserved_tickers == ("A",)
    assert result.signal_contexts.iloc[0].final_reserved_slots == 1
    invariant(result)


def test_known_restricted_operational_exit_keeps_slot_and_is_execution_rejected():
    prices, cal, features = fixture()
    restrictions = pd.DataFrame([dict(signal_date=cal[0], ticker="A", known_at=cal[0],
                                     source_id="pause", reason="known", sell_restricted=True)])
    result = run_replay(prices, cal, features, lambda *_: HoldingAwareDecision({"B": .1}),
                        initial_cash=9000, initial_positions={"A": 10}, max_positions=1, known_restrictions=restrictions,
                        operational_exits_by_signal={cal[0]: {"A": OperationalExit("exit mandate", cal[0], "mandate")}})
    assert result.trades.empty
    a = result.execution_results.loc[result.execution_results.ticker == "A"].iloc[0]
    assert a.decision_semantic == "OPERATIONAL_EXIT_REQUIRED" and a.execution_semantic == "EXECUTION_REJECTED"
    assert a.reason == "SIGNAL_KNOWN_SELL_RESTRICTION"
    assert result.signal_contexts.iloc[0].reserved_slots == 1


def test_unexpected_next_open_sale_failure_does_not_change_signal_targets_and_caps_buys():
    prices, cal, features = fixture()
    policy = lambda *_: HoldingAwareDecision({"A": 0., "B": .1}, raw_model_outputs={"A": {"logits": [-1.]}, "B": {"logits": [1.]}})
    original = run_replay(prices, cal, features, policy, initial_cash=9000, initial_positions={"A": 10}, max_positions=1)
    altered = prices.copy()
    altered.loc[(altered.ticker == "A") & (altered.trade_date == cal[1]), "open"] = np.nan
    failed = run_replay(altered, cal, features, policy, initial_cash=9000, initial_positions={"A": 10}, max_positions=1)
    pd.testing.assert_frame_equal(original.raw_model_outputs, failed.raw_model_outputs)
    pd.testing.assert_frame_equal(original.target_decisions, failed.target_decisions)
    pd.testing.assert_frame_equal(original.signal_contexts, failed.signal_contexts)
    assert failed.trades.empty
    rejects = failed.execution_results.loc[failed.execution_results.status == "REJECTED"]
    assert set(rejects.reason) == {"MISSING_OR_INVALID_OPEN", "LIVE_POSITION_LIMIT"}
    assert failed.daily.actual_name_count.eq(1).all()
    assert failed.signal_contexts.iloc[0].reserved_slots == 0
    invariant(failed)


def test_next_open_price_level_does_not_leak_into_raw_or_adapted_targets():
    prices, cal, features = fixture()
    policy = lambda *_: HoldingAwareDecision({"A": .05, "B": .05})
    a = run_replay(prices, cal, features, policy)
    changed = prices.copy()
    changed.loc[changed.trade_date == cal[1], "open"] *= 4
    b = run_replay(changed, cal, features, policy)
    pd.testing.assert_frame_equal(a.target_decisions, b.target_decisions)
    assert a.trades.index_units.sum() == pytest.approx(4*b.trades.index_units.sum())


def test_quality_warning_is_never_consumed_and_known_at_signal_reserves_old_units():
    prices, cal, features = fixture()
    prices.loc[(prices.ticker == "A") & (prices.trade_date == cal[0]), "price_quality_warning"] = True
    # Seed a trusted earlier mark; today's huge flagged quote cannot inflate capital.
    earlier = pd.DataFrame([dict(ticker="A", trade_date=cal[0]-pd.Timedelta(days=1), open=100., close=100., price_quality_warning=False)])
    prices.loc[(prices.ticker == "A") & (prices.trade_date == cal[0]), ["open", "close"]] = 1e9
    prices = pd.concat([prices, earlier], ignore_index=True)

    def policy(day, ctx):
        assert ctx.nav == pytest.approx(10000)
        assert ctx.reserved_weight == pytest.approx(.1)
        assert "A" not in day.ticker.tolist()
        return HoldingAwareDecision({"B": .1})

    result = run_replay(prices, cal, features, policy, initial_cash=9000, initial_positions={"A": 10})
    assert result.daily.iloc[0].stale_count == 1
    assert pd.isna(result.daily.iloc[0].certified_nav)
    assert result.positions.loc[result.positions.ticker == "A", "index_units"].eq(10).all()
    assert not result.trades.ticker.eq("A").any()
    invariant(result)


def test_future_quality_rejection_is_execution_fact_not_previous_signal_filter():
    prices, cal, features = fixture(names=("A",))
    policy = lambda *_: HoldingAwareDecision({"A": .1})
    good = run_replay(prices, cal, features, policy)
    prices.loc[prices.trade_date == cal[1], "price_quality_warning"] = True
    bad = run_replay(prices, cal, features, policy)
    pd.testing.assert_frame_equal(good.target_decisions, bad.target_decisions)
    assert bad.trades.empty
    assert bad.execution_results.iloc[0].reason == "PRICE_QUALITY_UNCERTIFIED"


def test_unknown_nav_preserves_units_and_does_not_create_budget_or_call_model():
    prices, cal, features = fixture(names=("B",))
    result = run_replay(prices, cal, features, lambda *_: pytest.fail("unknown NAV cannot fund a model allocation"),
                        initial_cash=1000, initial_positions={"UNKNOWN": 10})
    assert result.daily.nav.isna().all()
    assert result.daily.certified_nav.isna().all()
    assert result.trades.empty
    assert result.positions.index_units.eq(10).all()
    assert result.signal_contexts.available_weight.eq(0).all()
    assert not result.raw_model_outputs.policy_called.any()


def test_latest_pool_ineligible_existing_stock_cannot_receive_overnight_increase():
    prices, cal, features = fixture(names=("A",))
    features["new_buy_eligible"] = False
    prices.loc[prices.trade_date == cal[1], ["open", "close"]] = 50.
    result = run_replay(prices, cal, features, lambda *_: HoldingAwareDecision({"A": .1}),
                        initial_cash=9000, initial_positions={"A": 10})
    assert result.trades.empty
    assert result.positions.index_units.eq(10).all()
    assert result.execution_results.iloc[0].reason == "SIGNAL_BUY_INELIGIBLE"


def test_two_sided_costs_terminal_no_trade_and_raw_input_defensive_copy():
    prices, cal, features = fixture(names=("A",), signals=(0, 1))

    def policy(day, ctx):
        day.loc[:, "avg_dollar_volume_20d"] = 0.
        ctx.current_weights["fake"] = 99.
        return HoldingAwareDecision({"A": .1 if ctx.signal_date == cal[0] else 0.})

    result = run_replay(prices, cal, features, policy, capacity_fraction=.01)
    assert result.trades.action.tolist() == ["BUY", "EXIT"]
    assert result.trades.transaction_cost.tolist() == pytest.approx([100., 100.])
    assert result.daily.iloc[-1].cash == pytest.approx(999800.)
    assert len(result.raw_model_outputs) == 2
    assert not result.trades.execution_date.eq(cal[-1]).any()
    invariant(result)


def test_actual_twenty_position_limit_includes_all_missing_input_holdings():
    names = tuple(f"A{i:02d}" for i in range(21))
    prices, cal, features = fixture(names=names)
    features = features.loc[features.ticker == names[-1]]
    initial = {name: 1. for name in names[:20]}

    def policy(day, ctx):
        assert ctx.reserved_slots == 20 and ctx.available_slots == 0
        return HoldingAwareDecision({names[-1]: .1})

    result = run_replay(prices, cal, features, policy, initial_cash=8000, initial_positions=initial)
    assert result.trades.empty
    assert result.daily.actual_name_count.eq(20).all()
    assert result.positions.index_units.eq(1.).all()
    invariant(result)


def test_bare_mapping_and_implicit_cash_liquidation_are_rejected():
    prices, cal, features = fixture()
    with pytest.raises(ValueError, match="HoldingAwareDecision"):
        run_replay(prices, cal, features, lambda *_: {})
    with pytest.raises(ValueError, match="implicit cash"):
        run_replay(prices, cal, features, lambda *_: HoldingAwareDecision(), missing_signal_policy="cash")


def test_utc_session_close_accepts_prior_operational_proof_and_rejects_future_proof():
    prices, cal, features = fixture(names=("A",))
    asofs = {d: (d + pd.Timedelta(hours=16)).tz_localize("America/New_York").tz_convert("UTC") for d in cal}
    prior = OperationalExit("known mandate", asofs[cal[0]] - pd.Timedelta(minutes=1), "utc:proof")
    result = run_replay(prices, cal, features, lambda *_: HoldingAwareDecision(), initial_positions={"A": 10},
                        signal_asof=asofs, operational_exits_by_signal={cal[0]: {"A": prior}})
    assert result.trades.iloc[0].decision_semantic == "OPERATIONAL_EXIT_REQUIRED"
    assert result.signal_contexts.iloc[0].signal_asof == asofs[cal[0]]
    future = OperationalExit("late mandate", asofs[cal[0]] + pd.Timedelta(seconds=1), "utc:future")
    with pytest.raises(ValueError, match="not known at signal"):
        run_replay(prices, cal, features, lambda *_: HoldingAwareDecision(), initial_positions={"A": 10},
                   signal_asof=asofs, operational_exits_by_signal={cal[0]: {"A": future}})


def test_all_signal_prices_unavailable_produces_stable_empty_target_schema():
    prices, cal, features = fixture(names=("A",))
    prices.loc[prices.trade_date == cal[0], "price_quality_warning"] = True
    result = run_replay(prices, cal, features, lambda day, ctx: HoldingAwareDecision())
    assert result.target_decisions.empty and "decision_semantic" in result.target_decisions
    assert result.trades.empty and "price" in result.trades
    assert result.daily.cash.eq(1_000_000).all()


def test_training_executor_and_ledger_agree_on_locked_units_cash_and_costs():
    import torch
    from neural_train import execute_targets
    prices, cal, features = fixture(names=("A", "B", "C"))
    features = features.loc[features.ticker != "A"]
    for ticker, opening in [("A", 120.), ("B", 90.), ("C", 110.)]:
        prices.loc[(prices.ticker == ticker) & (prices.trade_date == cal[1]), "open"] = opening
    result = run_replay(prices, cal, features, lambda *_: HoldingAwareDecision({"B": .05, "C": .1}),
                        initial_cash=.4, initial_positions={"A": .004, "B": .002})
    td = torch.float64
    units, cash, fees, nav, blocked, cap_info = execute_targets(
        torch.tensor([.004, .002, 0.], dtype=td), torch.tensor(.4, dtype=td),
        torch.tensor([120., 90., 110.], dtype=td), torch.tensor([True, True, True]),
        torch.tensor([.4, .05, .1], dtype=td), torch.tensor([True, False, False]), torch.tensor([False, True, True]),
        torch.full((3,), 1e12, dtype=td))
    actual = result.positions.loc[result.positions.date == cal[1]].set_index("ticker").index_units.reindex(["A", "B", "C"])
    np.testing.assert_allclose(actual.to_numpy(), units.numpy(), atol=1e-12, rtol=1e-12)
    assert result.daily.iloc[1].cash == pytest.approx(float(cash), abs=1e-12)
    assert result.daily.iloc[1].transaction_cost_amount == pytest.approx(float(fees), abs=1e-12)
    assert blocked == 0


def test_training_and_ledger_both_block_twenty_first_name_after_unexpected_failed_sale():
    import torch
    from neural_train import execute_targets
    names = tuple(f"A{i:02d}" for i in range(21))
    prices, cal, features = fixture(names=names)
    prices.loc[(prices.ticker == names[0]) & (prices.trade_date == cal[1]), "open"] = np.nan
    decisions = {t: .01 for t in names}
    decisions[names[0]] = 0.
    initial = {t: .0001 for t in names[:20]}
    result = run_replay(prices, cal, features, lambda *_: HoldingAwareDecision(decisions), initial_cash=.8, initial_positions=initial)
    weights = torch.tensor([decisions[t] for t in names], dtype=torch.float64)
    fill = torch.ones(21, dtype=torch.bool); fill[0] = False
    units, cash, fees, nav, blocked, cap_info = execute_targets(
        torch.tensor([.0001]*20+[0.], dtype=torch.float64), torch.tensor(.8, dtype=torch.float64),
        torch.full((21,), 100., dtype=torch.float64), fill, weights,
        torch.zeros(21, dtype=torch.bool), torch.ones(21, dtype=torch.bool),
        torch.full((21,), 1e12, dtype=torch.float64))
    assert blocked == 1
    assert result.execution_results.reason.eq("LIVE_POSITION_LIMIT").sum() == 1
    assert int((units > 0).sum()) == result.daily.iloc[1].actual_name_count == 20
    assert result.daily.iloc[1].cash == pytest.approx(float(cash), abs=1e-12)
