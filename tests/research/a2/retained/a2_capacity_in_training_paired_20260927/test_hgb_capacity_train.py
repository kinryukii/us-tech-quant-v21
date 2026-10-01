import numpy as np
import pandas as pd
import pytest

import hgb_capacity_train as hgb


def row(adv, forward=0.10, vol=0.10):
    values = {feature: 0.0 for feature in hgb.original.FEATURES}
    values.update(avg_dollar_volume_20d=adv, realized_vol_20d=vol,
                  y_next_open=forward)
    return pd.DataFrame([values])


def test_nonbinding_capacity_matches_frozen_one_step_reward_and_inputs():
    selected = row(20_000_000.0)
    candidate_x, candidate_y, audit = hgb.expand_capacity(selected)
    baseline = selected.rename(columns={"y_next_open": "joint_return"})
    frozen_x, frozen_y, _ = hgb.original.counterfactual(baseline, robust_training=True)
    np.testing.assert_array_equal(candidate_x, frozen_x)
    np.testing.assert_allclose(candidate_y, frozen_y, rtol=0, atol=1e-15)
    assert audit["capacity_limited_buy_labels"] == 0


def test_partial_buy_changes_reward_but_keeps_requested_action_feature():
    x, y, audit = hgb.expand_capacity(row(1_000_000.0))
    # First state is current=0, action=10%; 1% of $1m ADV permits 1% weight.
    assert x[4, 35] == pytest.approx(0.10)
    actual = 0.01
    expected = actual * 0.10 - 0.001 * actual - 0.5 * 4.0 * 0.10**2 * actual**2
    assert y[4] == pytest.approx(expected)
    # Final state is current=10%, action=0; sells retain the original rule.
    assert y[10] == pytest.approx(-0.001 * 0.10)
    assert audit["capacity_limited_buy_labels"] == 6


def test_missing_or_invalid_adv_does_not_become_unlimited_fill():
    for adv in [0.0, np.nan, np.inf, -1.0]:
        with pytest.raises(ValueError, match="ADV_MUST_BE_FINITE_POSITIVE"):
            hgb.expand_capacity(row(adv))
