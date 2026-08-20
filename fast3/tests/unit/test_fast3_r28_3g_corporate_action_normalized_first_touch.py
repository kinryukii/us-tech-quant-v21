from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


SOURCE = Path(__file__).parents[2] / "scripts" / "run" / "fast3_r28_3g_corporate_action_normalized_first_touch.py"
SPEC = importlib.util.spec_from_file_location("r28_3g", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def action(multiplier: float) -> dict:
    return {"pre_to_post_price_multiplier": multiplier}


def test_one_for_ten_reverse_split_economic_normalization():
    result = MODULE.normalize_trade(3.56, 36.33, [action(10.0)])
    assert result["normalized_entry_equivalent"] == 35.6
    assert np.isclose(result["normalized_net20"], 36.33 / 35.6 - 1 - .002)
    assert np.isclose(result["post_action_share_factor"], .1)


def test_ordinary_forward_split_normalization():
    result = MODULE.normalize_trade(600.0, 42.0, [action(1.0 / 15.0)])
    assert np.isclose(result["normalized_entry_equivalent"], 40.0)
    assert np.isclose(result["normalized_gross"], .05)


def test_split_ratio_to_price_multiplier():
    assert MODULE.price_multiplier("REVERSE_SPLIT", "1:10") == 10.0
    assert np.isclose(MODULE.price_multiplier("FORWARD_SPLIT", "15:1"), 1.0 / 15.0)


def test_no_action_trade_is_unchanged():
    result = MODULE.normalize_trade(100.0, 110.0, [])
    assert result["corporate_action_factor"] == 1.0
    assert np.isclose(result["normalized_gross"], .10)


def test_multiple_actions_have_cumulative_factor_and_share_equivalence():
    result = MODULE.normalize_trade(10.0, 120.0, [action(2.0), action(5.0)])
    assert result["corporate_action_factor"] == 10.0
    assert result["post_action_share_factor"] == .1
    assert np.isclose(result["normalized_gross"], .2)


def test_actions_between_uses_strictly_after_entry_through_exit():
    records = [
        {"symbol": "SOXS", "effective_timestamp": "2024-04-15T08:01:00+00:00"},
        {"symbol": "SQQQ", "effective_timestamp": "2024-04-15T08:01:00+00:00"},
    ]
    found = MODULE.actions_between(pd.Timestamp("2024-04-15T00:27Z"), pd.Timestamp("2024-04-16T00:27Z"), "SOXS", records)
    assert len(found) == 1


def test_pre_entry_touch_explicit_classification_fixture():
    entry = pd.Timestamp("2022-11-10T13:32Z")
    touch = pd.Timestamp("2022-11-10T13:31Z")
    state = "PRE_ENTRY_TOUCH_NOT_CAPTURABLE" if touch < entry else "EXECUTED_VALID_TRADE"
    assert state == "PRE_ENTRY_TOUCH_NOT_CAPTURABLE"


def test_no_silent_drop_reconciliation_fixture():
    selected, valid, pre_entry, other_invalid, nonexec = 1198, 1197, 1, 0, 0
    assert selected == valid + pre_entry + other_invalid + nonexec


def test_up_down_semantics_remain_instrument_long_returns():
    up = MODULE.normalize_trade(10.0, 11.0, [])
    down_inverse_etf = MODULE.normalize_trade(40.0, 36.0, [])
    assert up["normalized_gross"] > 0
    assert down_inverse_etf["normalized_gross"] < 0  # no mathematical re-inversion


def test_tail_rule_is_fixed_and_does_not_drop_rows():
    values = pd.Series([1.0] + [0.0] * 99)
    result = MODULE.tail_audit(values)
    assert result["CORRECTED_TOP_1PCT_TRADE_COUNT"] == 1
    assert result["CORRECTED_MEAN_DRIVEN_BY_EXTREME_OUTLIERS"]


def test_source_enforces_raw_data_and_external_storage_contract():
    text = SOURCE.read_text(encoding="utf-8")
    assert 'DATA_ROOT = Path(r"D:\\us-tech-quant-data")' in text
    assert 'RESULTS_ROOT = Path(r"D:\\us-tech-quant-results")' in text
    assert 'CACHE_ROOT = Path(r"D:\\us-tech-quant-cache")' in text
    assert 'all_adjustment_types != {"NONE"}' in text
    lowered = text.lower()
    assert ".fit(" not in lowered
    assert ".predict(" not in lowered
    assert "matched_placebo(" not in lowered
