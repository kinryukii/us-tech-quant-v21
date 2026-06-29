#!/usr/bin/env python
"""Focused tests for V21.105-R2 gate contracts."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_105_r2_rebalance_gate_backtest.py"
spec = importlib.util.spec_from_file_location("v21_105_r2", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def ranking(count: int = 100) -> pd.DataFrame:
    return pd.DataFrame({"ticker": [f"T{i:03d}" for i in range(1, count + 1)]})


def test_gate_count_and_costs() -> None:
    assert len(module.gate_specs()) == 25
    assert module.COSTS == (0, 10, 20, 50, 100)


def test_retention_buffer_keeps_top50_members() -> None:
    spec = module.GateSpec("X", "RETENTION_BUFFER", 20, 21, 50)
    current = [f"T{i:03d}" for i in range(31, 51)]
    selected, execute, _ = module.select_gate(spec, ranking(), current, [])
    assert set(selected) == set(current)
    assert not execute


def test_overlap_gate_can_skip() -> None:
    spec = module.GateSpec("X", "OVERLAP_THRESHOLD", 20, 21, .70)
    current = [f"T{i:03d}" for i in range(1, 21)]
    selected, execute, overlap = module.select_gate(spec, ranking(), current, [])
    assert selected == current
    assert not execute
    assert overlap == 1.0


def test_rank_improvement_threshold() -> None:
    spec = module.GateSpec("X", "RANK_IMPROVEMENT", 20, 21, 30)
    current = [f"T{i:03d}" for i in range(1, 20)] + ["T080"]
    selected, execute, _ = module.select_gate(spec, ranking(), current, [])
    assert "T020" in selected and "T080" not in selected
    assert execute


if __name__ == "__main__":
    test_gate_count_and_costs()
    test_retention_buffer_keeps_top50_members()
    test_overlap_gate_can_skip()
    test_rank_improvement_threshold()
    print("PASS test_v21_105_r2_rebalance_gate_backtest")
