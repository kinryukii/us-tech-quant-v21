"""Focused contracts for A2 Stock Risk R4."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).with_name("a2_stock_risk_r4.py")
SPEC = importlib.util.spec_from_file_location("a2_stock_risk_r4", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_frozen_r3r_information_and_no_new_features() -> None:
    assert MODULE.REFERENCE_CANDIDATE == "LGBM_STOCK_Q90_1"
    assert len(MODULE.R3.FEATURES) == 22
    assert MODULE.RIDGE_ALPHA == 1.0
    assert MODULE.R3R_OOF_PATH.exists()


def test_position_mapping_is_unchanged_and_cash_preserving() -> None:
    percentiles = np.array([0.10, 0.70, 0.71, 0.85, 0.86, 0.95, 0.96])
    multipliers = MODULE.R3.R1.direct_multiplier(percentiles)
    assert np.array_equal(multipliers, [1.0, 1.0, 0.75, 0.75, 0.50, 0.50, 0.25])
    assert np.all(multipliers > 0) and np.all(multipliers <= 1)


def _metrics(r4_return: float, r4_sharpe: float, r4_mdd: float, r4_es: float) -> pd.DataFrame:
    rows = []
    for name, ret, sharpe, mdd, es in [
        ("RAW_A2", 1.0, 1.0, -0.40, -0.06), ("CONSTANT_EXPOSURE_MATCHED_A2", 0.90, 1.0, -0.35, -0.05),
        ("R3_RAW_RISK_SCALING_A2", 0.70, 0.9, -0.30, -0.045), ("R4_ALPHA_CONDITIONED_RESIDUAL_RISK_A2", r4_return, r4_sharpe, r4_mdd, r4_es),
    ]:
        rows.append({"strategy": name, "total_return": ret, "sharpe": sharpe, "maximum_drawdown": mdd, "expected_shortfall_5": es})
    return pd.DataFrame(rows)


def _attribution(r4_winner: float, r4_loss: float) -> pd.DataFrame:
    return pd.DataFrame([
        {"strategy": "R3_RAW_RISK_SCALING_A2", "gross_winner_upside_sacrificed": 1.0, "gross_loss_avoided": 1.0, "net_scaling_value": 0.0},
        {"strategy": "R4_ALPHA_CONDITIONED_RESIDUAL_RISK_A2", "gross_winner_upside_sacrificed": r4_winner, "gross_loss_avoided": r4_loss, "net_scaling_value": r4_loss - r4_winner},
    ])


def test_preregistered_a_gate_requires_all_conditions() -> None:
    classification, values = MODULE.classify(_metrics(0.95, 1.10, -0.30, -0.045), _attribution(0.60, 0.70), 4)
    assert classification == "A" and values["A_GATE_PASS"]
    classification, _ = MODULE.classify(_metrics(0.89, 1.10, -0.30, -0.045), _attribution(0.60, 0.70), 4)
    assert classification != "A"


def test_r3r_artifacts_are_pre2026_only() -> None:
    oof = pd.read_parquet(MODULE.R3R_OOF_PATH, columns=["signal_date", "candidate_id"])
    assert pd.to_datetime(oof.signal_date).lt(pd.Timestamp("2026-01-01")).all()
