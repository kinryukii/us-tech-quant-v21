"""Focused identity and mechanics tests for constant-gross R5."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).with_name("a2_risk_control_r5.py")
SPEC = importlib.util.spec_from_file_location("a2_risk_control_r5", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_frozen_sources_and_exact_inherited_policy() -> None:
    sources, identity = MODULE.verify_sources()
    assert all(item["sha256"] == item["expected_sha256"] for item in sources.values())
    assert identity["live_frozen_identity"]["verified_a2_artifact_count"] == 46
    policy = MODULE.inherited_policy_manifest()
    assert policy["stock_multiplier"] == {"risk_percentile>=0.90": .5, "risk_percentile<0.90": 1.0}


def test_waterfill_preserves_gross_and_existing_cap() -> None:
    pre = np.array([.025] * 11 + [.05] * 9)
    weights, binds = MODULE.waterfill(pre)
    assert abs(weights.sum() - 1) <= 2e-15
    assert weights.max() <= .06 + 1e-14
    assert binds > 0


def test_full_panel_is_past_only_top20_and_same_gross() -> None:
    panel = MODULE.load_panel()
    assert len(panel.dates) == 984
    assert panel.rows.groupby("signal_date").size().eq(20).all()
    assert (panel.rows.information_date < panel.rows.signal_date).all()
    assert (panel.rows.train_max_target_end < panel.rows.embargo_cutoff).all()
    np.testing.assert_allclose(panel.r5_weights.sum(axis=1), panel.raw_weights.sum(axis=1), atol=2e-15, rtol=0)
    assert panel.r5_weights.max() <= .06 + 1e-14


def test_original_r6_reproduces_preserved_history() -> None:
    panel = MODULE.load_panel(); actual = MODULE.simulate(panel, panel.r6_weights, MODULE.BASE_COST)
    expected = MODULE.pd.read_parquet(MODULE.BASE_R6_PORTFOLIO)
    merged = actual.merge(expected, left_on="date", right_on="execution_date", validate="one_to_one")
    assert np.max(np.abs(merged.daily_return - merged.base_r6_daily_return)) <= 1e-12
    assert np.max(np.abs(merged.turnover_x - merged.turnover_y)) <= 1e-12


def test_placebo_and_reverse_mechanics_preserve_distribution_and_gross() -> None:
    panel = MODULE.load_panel(); rng = np.random.default_rng(MODULE.RNG_SEED)
    placebo = MODULE.placebo_weights(panel, rng, False); rank_placebo = MODULE.placebo_weights(panel, rng, True)
    np.testing.assert_allclose(placebo.sum(axis=1), 1, atol=2e-15, rtol=0)
    np.testing.assert_allclose(rank_placebo.sum(axis=1), 1, atol=2e-15, rtol=0)
    np.testing.assert_allclose(panel.reverse_weights.sum(axis=1), 1, atol=2e-15, rtol=0)
