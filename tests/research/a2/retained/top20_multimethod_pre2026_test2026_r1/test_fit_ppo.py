"""Small synthetic timing, identity, projection, and reward checks for PPO."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fit_ppo import FEATURES, Top20ReplayEnv, actor_sha, load_days
from policy_engine import PriceStore, project_capped_simplex


def fixture():
    dates = pd.to_datetime(["2023-06-01", "2023-06-02", "2023-06-05", "2023-06-06"])
    names = [f"S{i:02}" for i in range(20)]
    price = []
    for i, ticker in enumerate(names):
        for k, day in enumerate(dates):
            value = 10.0 + .1 * i + (.5 * k if i == 0 else 0.0)
            price.append({"trade_date": day, "ticker": ticker,
                          "open": value, "close": value})
    days = []
    for j in range(2):
        tickers = names if j == 0 else names[1:] + names[:1]
        days.append({"date": dates[j], "execution": dates[j + 1],
                     "terminal": dates[j + 2], "tickers": tickers,
                     "keys": tickers, "features": np.zeros((20, len(FEATURES))),
                     "usable": True})
    scaler = {"columns": FEATURES, "mean": np.zeros(len(FEATURES)),
              "std": np.ones(len(FEATURES)),
              "constant": np.zeros(len(FEATURES), bool)}
    return days, PriceStore(pd.DataFrame(price)), scaler


def test_projection_exact_zero_and_full_cash():
    z = np.r_[np.full(20, -1.), 1.]
    weights = project_capped_simplex(z)
    assert np.array_equal(weights[:20], np.zeros(20))
    assert weights[-1] == pytest.approx(1.)
    assert weights.sum() == pytest.approx(1.)


def test_ledger_reward_and_rank_reordering():
    days, prices, scaler = fixture()
    env = Top20ReplayEnv(days, prices, scaler, record=True)
    obs, _ = env.reset(seed=11)
    assert obs.shape == env.observation_space.shape
    first = np.r_[np.array([1.]), np.full(19, -1.), -1.]
    obs, reward, done, _, info = env.step(first)
    assert not done and info["fee"] > 0
    assert env.account.shares.get("S00", 0) > 0
    # S00 moved from first rank slot to the final one, yet its holding weight
    # follows the permanent ticker identity into that new slot.
    slots = obs.reshape(-1) if isinstance(obs, np.ndarray) else obs
    additional_stride = len(FEATURES) + 4
    assert slots[19 * additional_stride + len(FEATURES)] > 0
    _, _, done, _, info = env.step(np.r_[np.full(20, -1.), 1.])
    assert done and info["terminal_nav"] == pytest.approx(env.account.cash)
    assert env.reward_sum / 100 == pytest.approx(np.log(env.account.cash), abs=1e-10)
    assert not env.account.shares
    assert env.transactions[1]["trades"][0]["side"] == "SELL"


def test_feature_fallback_does_not_erase_market_path():
    days, prices, scaler = fixture()
    days[1]["usable"] = False
    env = Top20ReplayEnv(days, prices, scaler)
    env.reset()
    env.step(np.r_[np.array([1.]), np.full(19, -1.), -1.])
    _, reward, done, _, info = env.step(np.r_[np.full(20, -1.), 1.])
    assert done and info["fallback"]
    assert info["target_stock_weight"] == pytest.approx(1.)
    assert np.isfinite(reward)


def test_future_open_cannot_change_signal_observation():
    days, prices, scaler = fixture()
    first = Top20ReplayEnv(days, prices, scaler)
    observed, _ = first.reset()
    changed = PriceStore(pd.DataFrame([
        {"trade_date": date, "ticker": ticker, "open": value, "close": prices.close[(date, ticker)]}
        for (date, ticker), value in prices.open.items()]))
    changed.open[(days[0]["execution"], "S00")] *= 7
    second = Top20ReplayEnv(days, changed, scaler)
    observed_after_future_change, _ = second.reset()
    np.testing.assert_array_equal(observed, observed_after_future_change)


def test_future_label_crossing_rejected():
    days, _, _ = fixture()
    rows = []
    for day in days:
        for rank, (ticker, key) in enumerate(zip(day["tickers"], day["keys"]), 1):
            rows.append({"signal_date": day["date"], "execution_date": day["execution"],
                         "label_end_date": day["terminal"], "ticker": ticker,
                         "experiment_security_key": key, "raw_a2_rank": rank,
                         "base_usable_day": True,
                         "label_available_at_utc": pd.Timestamp("2026-01-02", tz="UTC"),
                         **dict.fromkeys(FEATURES, 0.)})
    with pytest.raises(RuntimeError, match="PPO_TRAIN_CLOCK_INVALID"):
        load_days(pd.DataFrame(rows), "2026-01-01")


def test_actor_hash_excludes_critic_and_detects_action_update():
    import torch
    from stable_baselines3 import PPO

    days, prices, scaler = fixture()
    model = PPO("MlpPolicy", Top20ReplayEnv(days, prices, scaler),
                policy_kwargs={"net_arch": {"pi": [32, 16], "vf": [32, 16]}},
                n_steps=128, batch_size=64, n_epochs=5, seed=11, verbose=0)
    before = actor_sha(model)
    with torch.no_grad():
        next(model.policy.mlp_extractor.value_net.parameters()).add_(1.)
    assert actor_sha(model) == before
    with torch.no_grad():
        next(model.policy.mlp_extractor.policy_net.parameters()).add_(1.)
    assert actor_sha(model) != before
