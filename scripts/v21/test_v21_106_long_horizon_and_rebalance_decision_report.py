#!/usr/bin/env python
"""Focused tests for V21.106 decision report contracts."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_106_long_horizon_and_rebalance_decision_report.py"
spec = importlib.util.spec_from_file_location("v21_106", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_source_chain_complete() -> None:
    assert list(module.SOURCES) == [
        "V21.104", "V21.104-R1", "V21.104-R2",
        "V21.105", "V21.105-R1", "V21.105-R2",
    ]


def test_next_steps_order() -> None:
    rows = module.next_steps()
    assert [row["priority"] for row in rows] == [1, 2, 3, 4]
    assert rows[0]["stage"] == "V21.106-R1_FULL_PIT_FACTOR_REPLAY_FEASIBILITY_AUDIT"
    assert rows[2]["stage"] == "V21.107_LIVE_FORWARD_TRACKING_FOR_D_TOP20_HOLD_AND_D_TOP50_QUARTERLY"


def test_expected_classification_constant() -> None:
    assert module.PARTIAL_WARN == "PARTIAL_PASS_V21_106_D_EDGE_CONFIRMED_BUT_ADOPTION_BLOCKED_BY_PIT_WARNINGS"


if __name__ == "__main__":
    test_source_chain_complete()
    test_next_steps_order()
    test_expected_classification_constant()
    print("PASS test_v21_106_long_horizon_and_rebalance_decision_report")
