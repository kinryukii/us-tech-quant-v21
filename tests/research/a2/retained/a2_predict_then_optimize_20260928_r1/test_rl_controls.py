"""RL projection, actual-fill reward/account semantics and paired zero controls."""
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_contract import FEATURES
from engine_v2 import run_replay
from rl_controls import (PolicyNetwork, project_logits, state_digest, observations,
                         filled_step_reward, actor_decision, TrainingActor, FrozenRL, ARTIFACTS)


def test_projection_respects_reserved_slots_budget_and_buy_eligibility():
    weight = project_logits([5., 4., 3.], [.1, .02, .1], slots=2, budget=.12)
    assert (weight >= 0).all() and (weight <= [.1, .02, .1]).all()
    assert np.count_nonzero(weight) <= 2 and weight.sum() <= .12 + 1e-12


def test_actual_filled_reward_uses_cash_capacity_and_cost_instead_of_requested_weight():
    s, e, end = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    record = dict(signal_date=s, before_units={}, before_cash=1000.)
    # Actual capacity allows only $10, although the target requested $100.
    reward = filled_step_reward(record, {"A": 1.}, 989.99, e,
        {("A", e): 10., ("A", end): 11.}, {s: e, e: end}, "2025-01-01", 10.)
    assert reward["valid"]
    assert np.isclose(reward["reward"], .00099)
    assert np.isclose(reward["transaction_cost"], .01)
    assert reward["actual_name_count"] == 1


def test_reward_clips_training_label_and_rejects_future_endpoint():
    s, e, end = pd.to_datetime(["2024-12-27", "2024-12-30", "2024-12-31"])
    record = dict(signal_date=s, before_units={"A": 1.}, before_cash=0.)
    kwargs = dict(actual_units={"A": 1.}, actual_cash=0., execution_date=e,
        price_map={("A", e): 10., ("A", end): 30.}, next_date={s: e, e: end}, cost_bps=10.)
    assert np.isclose(filled_step_reward(record, cutoff="2025-01-01", **kwargs)["reward"], .20)
    assert not filled_step_reward(record, cutoff="2024-12-31", **kwargs)["valid"]


def test_observation_uses_own_actual_weight_and_cash():
    day = pd.DataFrame([dict(ticker="A", new_buy_eligible=True, **{f: 0. for f in FEATURES})])
    context = SimpleNamespace(current_weights={"A": .03}, cash_weight=.97,
        buy_restricted_tickers=(), max_weight=.1)
    obs, upper = observations(day, context, np.zeros(32), np.ones(32))
    assert obs.shape == (1, 34)
    assert np.allclose(obs.numpy()[0, -2:], [.03, .97])
    assert upper[0] == .1


@pytest.mark.parametrize("method", ["reinforce", "ppo"])
def test_matched_zero_stays_immutable_after_actual_account_updates(method):
    torch.manual_seed(20260928)
    learned, zero = PolicyNetwork(), PolicyNetwork()
    zero.load_state_dict(learned.state_dict())
    before = state_digest(zero)
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
    panel = pd.DataFrame([dict(signal_date=d, ticker="A", new_buy_eligible=True,
                              **{f: (1000. if f == "avg_dollar_volume_20d" else .01) for f in FEATURES})
                          for d in dates[:2]])
    prices = pd.DataFrame([dict(ticker="A", trade_date=d, open=p, close=p)
                           for d, p in zip(dates, [10., 10., 12., 13.])])
    actor = TrainingActor(learned, np.zeros(32), np.ones(32), method,
        torch.optim.Adam(learned.parameters(), lr=.001),
        prices.set_index(["ticker", "trade_date"]).open.to_dict(), dict(zip(dates[:-1], dates[1:])),
        "2025-01-01", dict(cost_bps=10., ppo_clip=.2))
    result = run_replay(prices, dates, panel, actor, initial_cash=1000., cost_bps=10.,
                        capacity_fraction=.01, signal_start=dates[0], signal_end=dates[1])
    actor.flush(result)
    assert len(actor.update_rows) == 2
    assert result.daily.actual_name_count.max() == 1
    assert result.trades.notional.max() <= 10. + 1e-8
    assert state_digest(zero) == before
    assert state_digest(learned) != before
    assert all(row["valid"] for row in actor.reward_rows)


@pytest.mark.parametrize("stage", ["validation", "final"])
@pytest.mark.parametrize("method", ["reinforce", "ppo"])
def test_completed_artifacts_load_as_matched_frozen_controls(stage, method):
    if not (ARTIFACTS / f"{stage}_{method}" / "TRAIN_RECEIPT.json").exists():
        pytest.skip("fixed actual training has not completed yet")
    learned = FrozenRL(stage, method)
    zero = FrozenRL(stage, method, zero=True)
    assert state_digest(learned.model) != state_digest(zero.model)
    assert np.array_equal(learned.mean, zero.mean)
    assert np.array_equal(learned.scale, zero.scale)
    panel = pd.DataFrame([dict(ticker=f"T{i:02}", new_buy_eligible=True,
                               **{f: 0. for f in FEATURES}) for i in range(35)])
    context = SimpleNamespace(nav=1000., cash_weight=.90, current_weights={"T00": .10},
        current_units={"T00": 10.}, buy_restricted_tickers=(), max_weight=.1,
        available_slots=20, available_weight=.95)
    for actor in [learned, zero]:
        decision = actor(panel, context)
        assert len(decision.raw_model_outputs) == 35
        assert sum(w > 0 for w in decision.model_decisions.values()) <= 20
        assert sum(decision.model_decisions.values()) <= .95 + 1e-10
        assert "T00" in decision.model_decisions
