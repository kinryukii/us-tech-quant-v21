"""Focused contract tests for the A2 RISK-ML-R1 runner."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).with_name("a2_risk_ml_r1.py")
SPEC = importlib.util.spec_from_file_location("a2_risk_ml_r1", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_preregistered_caps_and_contracts() -> None:
    assert len(MODULE.FEATURES) == 14
    assert len(MODULE.FEATURES) <= 20
    assert len({c.family for c in MODULE.CANDIDATES}) == 3
    assert len(MODULE.CANDIDATES) == 6
    assert len(MODULE.CANDIDATES) <= 9
    assert len(MODULE.FOLDS) == 5
    assert MODULE.TRAINING_CUTOFF.isoformat() == "2026-01-01T00:00:00"


def test_fixed_mapping_and_slow_reentry() -> None:
    percentiles = np.array([0.10, 0.70, 0.71, 0.85, 0.86, 0.95, 0.96])
    direct = MODULE.direct_multiplier(percentiles)
    assert np.array_equal(direct, np.array([1.0, 1.0, 0.75, 0.75, 0.50, 0.50, 0.25]))
    slow = MODULE.slow_reentry_multiplier(np.array([0.25, 1.00, 1.00, 1.00]))
    assert np.array_equal(slow, np.array([0.25, 0.50, 0.75, 1.00]))


def test_overlay_cost_contract() -> None:
    raw = np.array([0.01, -0.02])
    controlled, turnover = MODULE.controlled_returns(raw, np.array([0.5, 1.0]))
    assert np.allclose(turnover, np.array([0.25, 0.25]))
    assert np.allclose(controlled, np.array([0.00475, -0.02025]))


def test_empirical_percentile_uses_reference_only() -> None:
    reference = np.array([0.1, 0.2, 0.3, 0.4])
    assert np.allclose(MODULE.empirical_percentile(reference, np.array([0.05, 0.25, 0.5])), [0.0, 0.5, 1.0])
