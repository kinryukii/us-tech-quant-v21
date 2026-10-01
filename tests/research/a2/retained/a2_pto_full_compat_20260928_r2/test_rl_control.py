from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import torch

import rl_control as rl
from fast_account import MarketArrays, TargetDecision, run_many


def synthetic_market(names=25, days=12):
    dates = pd.bdate_range("2023-01-03", periods=days)
    tickers = np.asarray([f"T{i:02d}" for i in range(names)])
    opening = np.column_stack([100*(1+0.004*np.sin(np.arange(days)+i))*(1+0.001*(i%4)*np.arange(days)) for i in range(names)])
    closing = opening*(1+0.003*np.cos(np.arange(days))[:, None])
    features = np.zeros((days, names, 32), dtype=np.float32)
    features[:, :, 0] = np.sin(np.arange(days)[:, None]+np.arange(names)[None, :])
    features[:, :, 31] = 100_000.0
    market = MarketArrays(dates, tickers, opening, closing, adv=np.full((days, names), 100_000.),
                          signal_mask=np.r_[np.ones(days-2, bool), False, False])
    return market, features


def test_real_account_feedback_and_capacity_are_used_by_policy():
    torch.manual_seed(rl.SEED)
    actor = rl.Actor()
    market, features = synthetic_market()
    experiences, records, audit = rl.collect_episode(actor, None, market, features, np.zeros(32), np.ones(32), rl.SEED)
    assert audit["max_actual_names"] <= 20
    assert audit["capacity_violations"] == 0
    assert audit["next_open_violations"] == 0
    assert audit["cash_identity_error_max"] < 1e-6
    assert records[0]["fees"] > 0
    assert records[0]["actual_cash"] < 1_000_000
    assert np.count_nonzero(experiences[1]["current_units"] > 0) > 0
    assert experiences[1]["decision_cash"] < experiences[0]["decision_cash"]
    assert all(r["reward_end_date"] > r["execution_date"] > r["signal_date"] for r in records)


@pytest.mark.parametrize("method", ["reinforce", "ppo"])
def test_actual_rl_updates_and_matching_zero_initialization(method):
    market, features = synthetic_market(names=6, days=38)
    torch.set_num_threads(2)
    actor, critic, initial, metrics, records = rl.train_one(method, market, features, np.zeros(32), np.ones(32), epochs=2)
    assert metrics["actor_parameter_delta_l2"] > 0
    assert metrics["actual_parameter_updates"] >= 2
    assert metrics["initial_actor_digest"] != metrics["final_actor_digest"]
    zero = rl.Actor(); zero.load_state_dict(initial)
    assert rl.state_digest(zero) == metrics["initial_actor_digest"]
    assert records[-1]["reward_end_date"] < pd.Timestamp("2024-01-01")
    assert critic is not None if method == "ppo" else critic is None


def test_ppo_clipped_ratio_limits_favorable_policy_changes():
    old = torch.tensor([0., 0.])
    new = torch.log(torch.tensor([2., .5])).requires_grad_()
    advantage = torch.tensor([1., -1.])
    loss, ratio = rl.clipped_policy_loss(new, old, advantage)
    np.testing.assert_allclose(ratio.detach(), [2., .5])
    assert float(loss.detach()) == pytest.approx(-.2)
    loss.backward()
    np.testing.assert_allclose(new.grad, [0., 0.])


def test_signal_targets_do_not_read_future_open_and_missing_input_keeps_units():
    torch.manual_seed(rl.SEED)
    actor = rl.Actor()
    market, features = synthetic_market(names=2, days=7)
    first_targets = []

    def replay(opening):
        altered = MarketArrays(market.dates, market.tickers, opening, market.close,
                               adv=market.adv, input_present=market.input_present.copy(),
                               new_buy_eligible=market.new_buy_eligible, signal_mask=market.signal_mask)
        altered.input_present[1] = False
        policy = rl.EpisodePolicy(actor, None, features, np.zeros(32), np.ones(32), rl.SEED)

        def wrapped(i, context):
            result = policy(i, context)
            if i == 0:
                first_targets.append(result.weights.copy())
            return result

        return run_many(altered, ["training"], wrapped)

    original = replay(market.open.copy())
    altered = market.open.copy(); altered[1] *= 2
    replay(altered)
    np.testing.assert_array_equal(first_targets[0], first_targets[1])
    held1 = original.positions.loc[original.positions.date.eq(market.dates[1])].set_index("ticker").index_units
    held2 = original.positions.loc[original.positions.date.eq(market.dates[2])].set_index("ticker").index_units
    pd.testing.assert_series_equal(held1, held2)
    preserved = original.orders.loc[original.orders.signal_date.eq(market.dates[1])]
    assert preserved.order_type.eq("HOLD_UNITS").all()


def test_training_rejects_2026_market_input():
    panel = pd.DataFrame({"signal_date": pd.to_datetime(["2026-01-02"])})
    prices = pd.DataFrame({"trade_date": pd.to_datetime(["2025-12-31"])})
    with pytest.raises(ValueError, match="RL_TRAINING_BOUNDARY"):
        rl.prepare_market(panel, prices, "2026-01-01")


def test_frozen_runtime_maps_four_controls_to_independent_accounts(tmp_path):
    torch.manual_seed(rl.SEED)
    initial = rl.Actor()
    for method in ["reinforce", "reinforce_zero", "ppo", "ppo_zero"]:
        actor = rl.Actor(); actor.load_state_dict(initial.state_dict())
        if method in ["reinforce", "ppo"]:
            with torch.no_grad():
                actor.net[-1].bias.add_(0.5 if method == "reinforce" else -0.5)
        torch.save(dict(actor_state=actor.state_dict(), mean=torch.zeros(32, dtype=torch.float64),
                        scale=torch.ones(32, dtype=torch.float64)),
                   tmp_path/f"rl_validation_{method}.pt")
    market, features = synthetic_market(names=8, days=7)
    runtime = rl.RLRuntime("validation", feature_cube=features, model_dir=tmp_path)
    controls = ["reinforce", "reinforce_zero", "ppo", "ppo_zero"]
    replay = run_many(market, controls, runtime)
    zero_a = replay.daily.loc[replay.daily.path_id.eq("reinforce_zero"), ["cash", "nav"]].to_numpy()
    zero_b = replay.daily.loc[replay.daily.path_id.eq("ppo_zero"), ["cash", "nav"]].to_numpy()
    np.testing.assert_array_equal(zero_a, zero_b)
    assert len(set(replay.daily.path_id)) == 4
    assert replay.final_units.shape == (4, 8)
    assert replay.audit["cash_identity_error_max"] < 1e-6
    with pytest.raises(ValueError, match="UNDECLARED_RL_PATH"):
        run_many(market, ["other_policy"], runtime)


def test_unknown_nav_rl_account_does_not_break_healthy_account(tmp_path):
    torch.manual_seed(rl.SEED)
    initial = rl.Actor()
    for method in ["reinforce", "reinforce_zero", "ppo", "ppo_zero"]:
        torch.save(dict(actor_state=initial.state_dict(), mean=torch.zeros(32, dtype=torch.float64),
                        scale=torch.ones(32, dtype=torch.float64)),
                   tmp_path/f"rl_validation_{method}.pt")
    market = MarketArrays(pd.bdate_range("2025-01-02", periods=3), np.array(["UNKNOWN_HELD", "AVAILABLE"]),
                          open=np.array([[np.nan, 100.], [np.nan, 101.], [np.nan, 102.]]),
                          close=np.array([[np.nan, 100.], [np.nan, 101.], [np.nan, 102.]]),
                          adv=np.full((3, 2), 1_000_000.), signal_mask=np.array([True, True, False]))
    runtime = rl.RLRuntime("validation", feature_cube=np.zeros((3, 2, 32)), model_dir=tmp_path)
    replay = run_many(market, ["reinforce", "ppo"], runtime, initial_cash=np.array([0., 1_000_000.]),
                      initial_units=np.array([[1., 0.], [0., 0.]]))
    assert replay.final_units[0, 0] == 1.0 and replay.final_cash[0] == 0.0
    assert replay.final_units[1, 1] > 0
    assert replay.daily.loc[replay.daily.path_id.eq("reinforce"), "nav"].isna().all()
