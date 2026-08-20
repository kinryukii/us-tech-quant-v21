from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest


SOURCE = Path(__file__).with_name("a2_pit_moomoo_current_week_completion_r1.py")
SPEC = importlib.util.spec_from_file_location("a2_current_week_r1_tested", SOURCE)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_cutoff_is_frozen_before_august_19_close() -> None:
    assert str(MODULE.FIXED_CUTOFF.date()) == "2026-08-18"


def test_planned_ranges_request_only_prefix_and_suffix() -> None:
    member = {"required_history_start": "2020-01-01"}
    frame = pd.DataFrame({"date": pd.to_datetime(["2020-02-03", "2026-08-01"])})
    assert MODULE.planned_ranges(member, frame) == [
        ("2020-01-01", "2020-02-02"),
        ("2026-08-02", "2026-08-18"),
    ]


def test_normalizer_rejects_invalid_prices() -> None:
    bad = pd.DataFrame({
        "date": ["2026-08-18"], "open": [1.0], "high": [1.0], "low": [0.0],
        "close": [1.0], "volume": [1], "turnover": [1.0],
    })
    with pytest.raises(RuntimeError, match="INVALID_OHLCV"):
        MODULE.normalize_frame(bad, "TEST", "US.TEST", "TEST")


def test_all_declared_final_statuses_are_terminal() -> None:
    required = {
        "COMPLETE_TO_FIXED_CUTOFF", "PARTIAL_MISSING_HISTORY", "EMPTY_RESPONSE_CONFIRMED",
        "UNKNOWN_SECURITY", "UNSUPPORTED_SECURITY", "UNSUPPORTED_OTC",
        "INVALID_HISTORICAL_MAPPING", "OTHER_HARD_FAILURE",
    }
    assert MODULE.TERMINAL == required
