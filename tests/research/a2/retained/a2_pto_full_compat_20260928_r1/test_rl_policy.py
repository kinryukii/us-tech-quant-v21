"""Timing, account feedback and fixed-budget RL checks on synthetic data."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import torch
from sklearn.preprocessing import StandardScaler

import rl_policy as rl


def test_hash_selection_keeps_actual_holdings_and_ignores_outcomes():
    day = pd.DataFrame({"ticker": [f"T{i}" for i in range(85)], "new_buy_eligible": True})
    for name in rl.FEATURES:
        day[name] = .1
    day["target"] = np.arange(len(day))
    context = SimpleNamespace(current_units={"T84": 2.}, signal_date=pd.Timestamp("2024-01-02"))
    selected = rl.select_observations(day, context)
    assert len(selected) == 81 and "T84" in selected.ticker.tolist()
    changed = day.sample(frac=1, random_state=11).copy()
    changed.target = -10000.
    assert selected.ticker.tolist() == rl.select_observations(changed, context).ticker.tolist()


def test_preopen_reward_excludes_following_action_fee_and_purges_endpoint():
    cal = pd.date_range("2024-01-02", periods=4)
    daily = pd.DataFrame({"date": cal, "open_pretrade_nav": [1e6, 1e6, 1009000., 1008000.],
                          "open_stale_count": 0, "open_unknown_count": 0,
                          "transaction_cost_amount": [0., 10., 2000., 0.],
                          "actual_name_count": 1, "cash": 500000.})
    record = {"signal_date": cal[0], "tickers": ["A"], "decision_id": "signal1",
              "old_logprob": -1., "old_value": 0.}
    result = SimpleNamespace(daily=daily)
    reward = rl.reward_ledger(result, [record], cal, "2025-01-01")
    assert reward.log_net_reward.iloc[0] == np.log(1.009)
    assert reward.action_execution_fees.iloc[0] == 10.
    with pytest.raises(ValueError, match="BOUNDARY"):
        rl.reward_ledger(result, [record], cal, cal[2])
    daily.loc[2, "open_stale_count"] = 1
    with pytest.raises(ValueError, match="NO_VALID_REWARDS"):
        rl.reward_ledger(result, [record], cal, "2025-01-01")


def test_missing_reward_breaks_future_credit_assignment():
    result = rl.returns_to_go([.1, .2, .3], [True, False, True], gamma=.9)
    np.testing.assert_allclose(result, [.1, 0., .3])


def test_ppo_reuses_one_rollout_exactly_four_updates():
    torch.manual_seed(rl.SEED)
    model = rl.ActorCritic()
    initial = model.actor.weight.detach().clone()
    generator = torch.Generator().manual_seed(5)
    records = []
    for i in range(12):
        x = torch.randn(4, 35, generator=generator)
        with torch.no_grad():
            logits, value = model(x)
            actions = torch.multinomial(torch.softmax(logits, dim=1), 1, generator=generator).flatten()
            old_logprob = float(torch.distributions.Categorical(logits=logits).log_prob(actions).sum())
        records.append({"observations": x.numpy(), "actions": actions.numpy(),
                        "tickers": ["A", "B", "C", "D"], "old_logprob": old_logprob,
                        "old_value": float(value.mean())})
    rewards = pd.DataFrame({"valid_learning_reward": True, "log_net_reward": np.linspace(-.01, .02, 12)})
    optimizer = torch.optim.Adam(model.parameters(), lr=.001)
    logs = rl.optimize_rollout(model, optimizer, records, rewards, "ppo", epochs=4)
    assert len(logs) == 4 and [r["rollout_reuse_count"] for r in logs] == [1, 2, 3, 4]
    assert sum(r["optimizer_steps_this_epoch"] for r in logs) == 4
    assert logs[0]["clip_fraction"] == 0.
    assert not torch.equal(model.actor.weight, initial)
    assert all(np.isfinite(r["loss"]) for r in logs)


def test_real_engine_capacity_cost_and_missing_input_hold_units():
    cal = pd.date_range("2024-01-02", periods=5)
    prices = pd.DataFrame({"trade_date": cal, "ticker": "A", "open": 10., "close": 10.})
    frame = pd.DataFrame({"signal_date": [cal[0]], "ticker": "A", "new_buy_eligible": True})
    for name in rl.FEATURES:
        frame[name] = 0.
    frame["avg_dollar_volume_20d"] = 100000.
    scaler = StandardScaler().fit(np.zeros((2, 32)))
    model = rl.ActorCritic()
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.zero_()
        model.actor.bias[4] = 1.
    policy = rl._Policy(model, scaler)
    result = rl.engine.run_replay(prices, cal, frame, policy, capacity_fraction=.01,
                                  initial_cash=1e6, cost_bps=10., signal_start=cal[0], signal_end=cal[3])
    assert result.trades.notional.sum() == 1000.
    assert result.trades.transaction_cost.sum() == 1.
    positions = result.positions.loc[result.positions.ticker.eq("A")]
    assert positions.index_units.nunique() == 1
    assert positions.index_units.iloc[-1] == 100.
    assert result.daily.actual_name_count.max() == 1
    assert result.daily.cash.iloc[-1] == 998999.
