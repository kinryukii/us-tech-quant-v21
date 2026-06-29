#!/usr/bin/env python
"""Focused tests for V21.105-R1 decomposition helpers."""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_105_r1_rebalance_failure_and_turnover_decomposition.py"
spec = importlib.util.spec_from_file_location("v21_105_r1", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_weighted_statistics() -> None:
    values = pd.Series([1.0, 3.0])
    weights = pd.Series([1, 3])
    assert math.isclose(module.weighted_mean(values, weights), 2.5)
    assert module.weighted_quantile(values, weights, .5) == 3.0


def test_gate_contract() -> None:
    gates = module.gate_design()
    assert len(gates) == 5
    assert all(row["diagnostic_only"] == "TRUE" for row in gates)
    assert all(row["official_adoption_allowed"] == "FALSE" for row in gates)


def test_blocker_classification() -> None:
    status, _ = module.classify(
        pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), 1, 0, False, False
    )
    assert status == module.FAIL_BLOCKER


if __name__ == "__main__":
    test_weighted_statistics()
    test_gate_contract()
    test_blocker_classification()
    print("PASS test_v21_105_r1_rebalance_failure_and_turnover_decomposition")
