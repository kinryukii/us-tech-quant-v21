#!/usr/bin/env python
"""Focused tests for V21.107 append-safe live tracking."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_107_live_forward_tracking.py"
spec = importlib.util.spec_from_file_location("v21_107", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_deterministic_ids() -> None:
    assert module.observation_id("2026-06-22", "TOP20_HOLD_ONLY") == (
        "V21_107::2026-06-22::TOP20_HOLD_ONLY"
    )


def test_quarterly_due() -> None:
    calendar = [f"2026-01-{day:02d}" for day in range(1, 32)] + [
        f"2026-02-{day:02d}" for day in range(1, 29)
    ] + [f"2026-03-{day:02d}" for day in range(1, 32)]
    master = [{"view_type": "TOP50_QUARTERLY_REBALANCE", "ranking_date": "2026-01-01"}]
    assert module.quarterly_due(master, "2026-03-10", calendar)
    assert not module.quarterly_due(master, "2026-02-01", calendar)


def test_turnover_initial_formation() -> None:
    observation = {
        "observation_id": "X", "ranking_date": "2026-06-22",
        "view_type": "TOP50_QUARTERLY_REBALANCE",
        "tickers_json": json.dumps(["A", "B"]),
    }
    row = module.make_turnover(observation, [], "RUN")
    assert row["realized_turnover"] == 1.0
    assert row["entry_count"] == 2


def test_benchmark_summary_empty() -> None:
    assert module.benchmark_summary([]) == []


def test_pending_start_price_hydration() -> None:
    observations = [{
        "ranking_date": "2026-06-22",
        "start_prices_json": json.dumps({"A": None}),
        "benchmark_start_prices_json": json.dumps({"QQQ": None, "SPY": None, "SOXX": None}),
    }]
    candidate = pd.DataFrame({"A": [10.0]}, index=["2026-06-22"])
    benchmark = pd.DataFrame(
        {"QQQ": [20.0], "SPY": [30.0], "SOXX": [40.0]}, index=["2026-06-22"]
    )
    assert module.hydrate_pending_start_prices(observations, candidate, benchmark) == 4
    assert json.loads(observations[0]["start_prices_json"])["A"] == 10.0


if __name__ == "__main__":
    test_deterministic_ids()
    test_quarterly_due()
    test_turnover_initial_formation()
    test_benchmark_summary_empty()
    test_pending_start_price_hydration()
    print("PASS test_v21_107_live_forward_tracking")
