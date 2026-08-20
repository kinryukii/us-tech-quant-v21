from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


SOURCE = Path(__file__).parents[2] / "scripts" / "run" / "fast3_r28_3f_leveraged_etf_integrity_audit.py"
SPEC = importlib.util.spec_from_file_location("r28_3f", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_return_recomputation_and_inverse_etf_direction_semantics():
    assert np.isclose(MODULE.instrument_return(10.0, 12.0), .2)
    # An inverse ETF is still a long position in the instrument: no second sign flip.
    assert np.isclose(MODULE.instrument_return(40.0, 36.0), -.1)


def test_split_and_reverse_split_fixtures():
    reverse = [{"pre_to_post_price_multiplier": 10.0}]
    forward = [{"pre_to_post_price_multiplier": 1.0 / 15.0}]
    assert MODULE.corrected_price(3.56, reverse) == 35.6
    assert np.isclose(MODULE.corrected_price(600.0, forward), 40.0)


def test_adjusted_vs_unadjusted_basis_fixture():
    assert MODULE.price_basis({"NONE"}) == ("RAW", False)
    assert MODULE.price_basis({"NONE", "SPLIT_ADJUSTED"}) == ("UNKNOWN", True)


def test_extreme_return_attribution_is_fixed_and_deterministic():
    values = pd.Series([10.0] + [0.0] * 99)
    result = MODULE.extreme_attribution(values)
    assert result["TOP_1PCT_TRADE_COUNT"] == 1
    assert result["EX_SINGLE_BEST_TRADE_MEAN_NET20"] == 0.0
    assert result["TOP_1PCT_CONTRIBUTION_SHARE"] == 1.0


def _bars():
    return pd.DataFrame({
        "symbol": ["SOXS"] * 3,
        "timestamp_utc": pd.to_datetime(["2024-04-14T23:59Z", "2024-04-15T08:00Z", "2024-04-15T08:01Z"]),
        "open": [3.56, 3.56, 35.5], "high": [3.57, 3.57, 35.6], "low": [3.55, 3.55, 35.4],
        "close": [3.56, 3.56, 35.5], "volume": [1, 1, 1], "source": ["moomoo_opend"] * 3,
        "adjustment_type": ["NONE"] * 3, "partition_key": ["p1", "p1", "p2"],
    })


def test_entry_exit_source_and_cross_partition_path_fixture():
    bars = _bars()
    index = bars.set_index("timestamp_utc")
    assert index.loc[pd.Timestamp("2024-04-14T23:59Z"), "open"] == 3.56
    assert index.loc[pd.Timestamp("2024-04-15T08:01Z"), "open"] == 35.5
    assert index.loc[pd.Timestamp("2024-04-14T23:59Z"), "partition_key"] != index.loc[pd.Timestamp("2024-04-15T08:01Z"), "partition_key"]


def test_discontinuity_fixture_detects_reverse_split_and_partition_boundary():
    result = MODULE.detect_discontinuities(_bars(), "SOXS")
    assert len(result) == 1
    assert result.iloc[0].absolute_price_ratio > 9.9
    assert bool(result.iloc[0].partition_boundary)


def test_official_action_overlap_fixture():
    actions = MODULE.apply_action_metadata(MODULE.detect_discontinuities(_bars(), "SOXS"))
    row = pd.Series({"action_instrument": "SOXS", "entry_timestamp": pd.Timestamp("2024-04-14T23:59Z"),
                     "first_touch_exit_timestamp": pd.Timestamp("2024-04-15T09:00Z")})
    matches = MODULE.overlap_actions(row, actions)
    assert len(matches) == 1
    assert matches[0]["action_type"] == "REVERSE_SPLIT"
    assert matches[0]["split_ratio"] == "1:10"


def test_source_declares_external_storage_and_no_model_or_placebo_calls():
    text = SOURCE.read_text(encoding="utf-8")
    assert 'DATA_ROOT = Path(r"D:\\us-tech-quant-data")' in text
    assert 'RESULTS_ROOT = Path(r"D:\\us-tech-quant-results")' in text
    assert 'CACHE_ROOT = Path(r"D:\\us-tech-quant-cache")' in text
    lowered = text.lower()
    assert ".fit(" not in lowered
    assert ".predict(" not in lowered
    assert "matched_placebo(" not in lowered


def test_timestamp_first_executable_rule_fixture():
    bars = _bars()
    target = pd.Timestamp("2024-04-15T08:00:30Z")
    location = int(pd.DatetimeIndex(bars.timestamp_utc).searchsorted(target, side="left"))
    assert bars.timestamp_utc.iloc[location] == pd.Timestamp("2024-04-15T08:01Z")


def test_head_column_mapping_uses_column_not_dataframe_method():
    frame = pd.DataFrame({"head": ["UP", "DOWN"], "underlying_symbol": ["SOXX", "SOXX"]})
    mapped = np.where(frame["head"].eq("UP"), np.where(frame.underlying_symbol.eq("SOXX"), "SOXL", "TQQQ"),
                      np.where(frame.underlying_symbol.eq("SOXX"), "SOXS", "SQQQ"))
    assert mapped.tolist() == ["SOXL", "SOXS"]
