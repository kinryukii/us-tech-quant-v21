#!/usr/bin/env python
"""Focused tests for V21.106-R1 feasibility audit."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_106_r1_full_pit_factor_replay_feasibility_audit.py"
spec = importlib.util.spec_from_file_location("v21_106_r1", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_required_families() -> None:
    families = {row["factor_family"] for row in module.required_inventory()}
    assert families == {
        "FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME",
        "DATA_TRUST", "MOMENTUM", "BENCHMARK", "UNIVERSE_MEMBERSHIP",
    }


def test_feasibility_contract() -> None:
    rows = module.family_feasibility()
    by_family = {row["factor_family"]: row["feasibility_classification"] for row in rows}
    assert by_family["BENCHMARK"] == "FULL_PIT_REPLAY_READY"
    assert by_family["FUNDAMENTAL"].startswith("PIT_REPLAY_BLOCKED")
    assert by_family["UNIVERSE_MEMBERSHIP"] == "PIT_REPLAY_BLOCKED_MISSING_HISTORY"


def test_expected_status() -> None:
    assert module.BLOCKED == "PARTIAL_PASS_V21_106_R1_FULL_REPLAY_BLOCKED_USE_LIVE_FORWARD"


if __name__ == "__main__":
    test_required_families()
    test_feasibility_contract()
    test_expected_status()
    print("PASS test_v21_106_r1_full_pit_factor_replay_feasibility_audit")
