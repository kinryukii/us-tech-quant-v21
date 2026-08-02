import json

import numpy as np
import pandas as pd

from v22_081_bounded_self_improvement import FEATURES, SAFETY, digest, et, make_action, metrics, mutation, nonoverlap


def test_deterministic_bounded_mutation_and_feature_cap():
    config = {"random_seeds": [1, 2], "model_families": ["logistic", "tree"], "feature_count_range": [10, 17]}
    one, two = mutation(3, [], config), mutation(3, [], config)
    assert one == two
    assert len(one["feature_names"]) <= 40
    assert one["model_type"] in config["model_families"]
    assert digest(one) == digest(two)
    parent = {"experiment_id": "E001", "decision": "RETAIN", "score": 1.0, "model_type": "logistic", "feature_names": FEATURES[:10], "params": {"c": .1, "l1_ratio": .5, "depth": 3, "min_leaf": 500, "trees": 32, "iterations": 30, "leaves": 5, "l2": 1.0}}
    child = mutation(6, [parent], config)
    assert child["parent_experiment_id"] == "E001"
    assert child["mutation_changes"]["hyperparameter_changes"] <= 3
    assert child["mutation_changes"]["threshold_changes"] <= 2


def test_no_trade_and_real_delay_cost_surface_are_explicit():
    n = 4; timestamps = pd.date_range("2025-01-02 10:00", periods=n, freq="65min", tz="America/New_York")
    data = {"decision_timestamp": timestamps, "calendar_date": timestamps.normalize(), "soxx_vol_60m": [.01] * n}
    for symbol in ("soxl", "soxs"):
        for delay in (0, 1, 3, 5): data[f"{symbol}_gross_60m_delay{delay}"] = [.02, .01, -.01, .03]
    frame = make_action(pd.DataFrame(data), np.array([.7, .7, .2, .7]), np.array([.8, .2, .8, .5]), {"opportunity_threshold": .4, "direction_margin": .05})
    assert frame.action.tolist() == ["LONG", "SHORT", "FLAT", "FLAT"]
    measured = metrics(frame.assign(actual_opportunity=[1, 1, 0, 0]), {"complexity": 1}, {"a": 1.0})
    assert measured["trade_count"] == 2 and measured["no_trade_rate"] == .5
    assert measured["mean_net_5bps_delay0"] > measured["mean_net_30bps_delay0"]
    assert SAFETY["broker_action_allowed"] is False


def test_nonoverlap_and_pit_feature_contract_scope():
    t = pd.date_range("2025-01-02 10:00", periods=3, freq="5min", tz="America/New_York")
    f = pd.DataFrame({"decision_timestamp": t, "action": ["LONG"] * 3, "gross_delay1": [.01] * 3})
    assert len(nonoverlap(f)) == 1
    assert len(FEATURES) < 40
    assert str(et("2026-02-28 23:59:59").tz) == "America/New_York"
