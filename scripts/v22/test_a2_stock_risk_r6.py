from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).with_name("a2_stock_risk_r6.py")
SPEC = importlib.util.spec_from_file_location("a2_stock_risk_r6", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_information_set_and_candidate_caps_are_frozen() -> None:
    assert len(MODULE.R3.FEATURES) == 22
    assert len(MODULE.CANDIDATES) == 6
    assert len({candidate.family for candidate in MODULE.CANDIDATES}) == 3
    assert max(sum(candidate.family == family for candidate in MODULE.CANDIDATES) for family in {c.family for c in MODULE.CANDIDATES}) <= 3
    assert MODULE.R3.R1.sha256_file(MODULE.R3R_OOF_PATH) == MODULE.R3R_SIGNAL_HASH


def test_bad_asymmetry_target_uses_preregistered_joint_condition() -> None:
    frame = pd.DataFrame({"forward_5d_stock_mae": [0.11, 0.11, 0.09, 0.10], "forward_5d_stock_mfe": [0.04, 0.06, 0.04, 0.05], "forward_5d_stock_return": [-0.02, -0.02, -0.02, 0.01]})
    primary, secondary = MODULE.event_labels(frame, 0.10, 0.05)
    assert np.array_equal(primary, [1, 0, 0, 1])
    assert np.array_equal(secondary, [1, 1, 0, 0])


def test_sparse_position_rule_is_exact_and_cash_preserving() -> None:
    percentiles = np.array([0.0, 0.899999, 0.90, 1.0])
    multipliers = np.where(percentiles >= MODULE.R6_INTERVENTION_PERCENTILE, MODULE.R6_INTERVENTION_MULTIPLIER, 1.0)
    assert np.array_equal(multipliers, [1.0, 1.0, 0.5, 0.5])
    assert np.all((multipliers > 0) & (multipliers <= 1))


def test_predictive_gate_requires_every_preregistered_condition() -> None:
    passing = {"positive_direction_folds": 4, "auroc": 0.61, "average_precision_lift": 1.6, "top_decile_bad_asymmetry_lift": 2.1}
    assert MODULE.predictive_gate(passing)
    for key in passing:
        failed = dict(passing)
        failed[key] = 0
        assert not MODULE.predictive_gate(failed)


def test_2026_is_absent_from_authoritative_inputs() -> None:
    oof = pd.read_parquet(MODULE.R3R_OOF_PATH, columns=["signal_date"])
    assert pd.to_datetime(oof.signal_date).lt(pd.Timestamp("2026-01-01")).all()
