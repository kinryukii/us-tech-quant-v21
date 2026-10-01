"""Synthetic-only input isolation and idempotent budget accounting checks."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.evaluation import joint_sequential_training as runner
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays


def inputs():
    dates = pd.DatetimeIndex(["2021-01-04", "2022-12-28", "2022-12-29",
                              "2022-12-30", "2023-01-03", "2023-01-04"])
    shape = (len(dates), 2)
    evidence = pd.DataFrame([
        dict(signal_date=dates[1], ticker="A", known_at=dates[1],
             source_id="synthetic_prior", reason="restricted", buy_restricted=True),
        dict(signal_date=dates[-1], ticker="A", known_at=dates[-1],
             source_id="synthetic_later", reason="restricted", buy_restricted=True),
    ])
    restricted = np.zeros(shape, bool)
    restricted[1, 0] = restricted[-1, 0] = True
    market = MarketArrays(
        dates, ["A", "B"], np.arange(12).reshape(shape) + 100.,
        np.arange(12).reshape(shape) + 100.5,
        adv=np.full(shape, 1e6), buy_restricted=restricted,
        known_restrictions_evidence=evidence,
        operational_exits={dates[1]: {"A": "prior"}, dates[-1]: {"A": "later"}},
    )
    prior = SimpleNamespace(effective_date="2022-12-29", event_fingerprint="prior")
    later = SimpleNamespace(effective_date="2023-01-03", event_fingerprint="later")
    return {
        "market": market, "feature_cube": np.arange(6*2*32).reshape(6, 2, 32).astype(float),
        "mu": {"EQUAL": np.arange(12).reshape(shape).astype(float)},
        "sigma": {"EQUAL": np.full(shape, .01)},
        "replay_kwargs": {
            "corporate_actions": [prior, later],
            "corporate_action_known_at": {"prior": dates[1], "later": dates[-1]},
            "unsupported_events": [
                dict(ticker="A", effective_date="2022-12-30", reason="prior"),
                dict(ticker="A", effective_date="2023-01-04", reason="later"),
            ],
        },
    }


def test_complete_prefix_slices_all_dated_inputs_and_corporate_action_identity():
    full = inputs()
    market, features, mu, sigma, kwargs, identity = runner.prefix_inputs(full, "2023-01-01")
    assert market.dates.equals(full["market"].dates[:4])
    np.testing.assert_array_equal(market.open, full["market"].open[:4])
    np.testing.assert_array_equal(features, full["feature_cube"][:4])
    np.testing.assert_array_equal(mu, full["mu"]["EQUAL"][:4])
    assert sigma.shape == (4, 2)
    assert market.buy_restricted.sum() == 1
    assert len(market.known_restrictions_evidence) == 1
    assert all(d < pd.Timestamp("2023-01-01") for d in market.operational_exits)
    assert [x.event_fingerprint for x in kwargs["corporate_actions"]] == ["prior"]
    assert set(kwargs["corporate_action_known_at"]) == {"prior"}
    assert [x["reason"] for x in kwargs["unsupported_events"]] == ["prior"]
    assert identity["corporate_action_fingerprints"] == ["prior"]
    assert identity["calendar_sessions"] == 4
    assert identity["candidate_sampling"] is False


def test_later_features_prices_and_forecasts_do_not_change_prefix_identity():
    first = inputs()
    prefix = runner.prefix_inputs(first, "2023-01-01")
    first["feature_cube"][4:] = -1e9
    first["mu"]["EQUAL"][4:] = -1e9
    first["sigma"]["EQUAL"][4:] = 1e9
    first["market"].open[4:] = 1e12
    second = runner.prefix_inputs(first, "2023-01-01")
    assert prefix[-1] == second[-1]
    np.testing.assert_array_equal(prefix[0].open, second[0].open)


def test_updates_checkpoint_once_and_shared_cap_rejects_extra_updates():
    calls = []
    record = {
        "identity": {"kind": "sequential_ppo", "cutoff_exclusive": "2023-01-01"},
        "status": "FIT_COMPLETE",
    }
    task = SimpleNamespace(
        status={"records": [record], "rl_optimizer_updates": 8},
        checkpoint=lambda: calls.append("checkpoint"),
    )
    runner.count_completed_updates(task, "sequential_ppo", 2023, 10)
    runner.count_completed_updates(task, "sequential_ppo", 2023, 10)
    assert task.status["rl_optimizer_updates"] == 18
    assert calls == ["checkpoint"]
    with pytest.raises(RuntimeError, match="count changed"):
        runner.count_completed_updates(task, "sequential_ppo", 2023, 11)
    record.pop("rl_updates_counted")
    task.status["rl_optimizer_updates"] = runner.MAX_UPDATES
    with pytest.raises(RuntimeError, match="budget exceeded"):
        runner.count_completed_updates(task, "sequential_ppo", 2023, 1)


def test_reward_audit_discloses_masked_steps_and_only_qualified_endpoints():
    frame = pd.DataFrame([
        dict(valid_learning_reward=True, reward_end_date=pd.Timestamp("2022-12-29"),
             mask_reason="AVAILABLE"),
        dict(valid_learning_reward=False, reward_end_date=pd.Timestamp("2025-12-31"),
             mask_reason="UNKNOWN_STALE_OR_UNQUALIFIED_ACCOUNT_REWARD"),
    ])
    result = runner.reward_audit_summary([frame])[0]
    assert result["qualified_reward_steps"] == result["masked_reward_steps"] == 1
    assert result["qualified_reward_endpoint_max"] == "2022-12-29 00:00:00"


def test_physical_2026_inputs_are_rejected_before_projection():
    full = inputs()
    full["market"].dates = pd.DatetimeIndex([
        "2021-01-04", "2022-12-28", "2022-12-29", "2022-12-30", "2023-01-03", "2026-01-01"])
    with pytest.raises(ValueError, match="training boundary"):
        runner.prefix_inputs(full, "2023-01-01")

