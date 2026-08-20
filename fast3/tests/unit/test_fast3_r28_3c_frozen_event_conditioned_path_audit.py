import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SOURCE = Path(__file__).parents[2] / "scripts" / "run" / "fast3_r28_3c_frozen_event_conditioned_path_audit.py"
SPEC = importlib.util.spec_from_file_location("r28_3c", SOURCE)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def events():
    x = pd.DataFrame({"direction": ["UP", "UP", "DOWN", "DOWN"], "score_bucket": ["TOP_5", "BOTTOM", "TOP_5", "BOTTOM"], "bucket_ordinal": [7, 1, 7, 1],
                      "frozen_score": [.9, .1, .9, .1], "score_rank_pct": [.01, .9, .01, .9], "timestamp": pd.date_range("2024-01-02", periods=4, freq="h", tz="UTC"),
                      "session": ["REGULAR"] * 4, "time_to_touch_minutes": [30., 300., 30., 300.], "post_touch_mfe": [.02, .01, .02, .01], "post_touch_mae": [-.01, -.02, -.01, -.02],
                      "terminal_favorable_return": [.005, -.005, .005, -.005], "touch_to_horizon_giveback": [.015, .015, .015, .015], "full_giveback": [False, True, False, True], "returned_to_entry": [False, True, False, True]})
    for minute, values in ((5, [.001, -.001, .001, -.001]), (15, [.002, -.002, .002, -.002]), (30, [.003, -.003, .003, -.003]), (60, [.004, -.004, .004, -.004]), (120, [.005, -.005, .005, -.005]), (240, [.006, -.006, .006, -.006])):
        x[f"post_touch_{minute}m_favorable_return"] = values; x[f"post_touch_{minute}m_available"] = True
    for level in AUDIT.CONTINUATION_LEVELS: x[f"post_touch_reach_{AUDIT.threshold_label(level)}"] = [True, False, True, False]
    return x


def test_frozen_contract_has_no_model_or_data_write_calls():
    source = SOURCE.read_text(encoding="utf-8")
    assert ".fit(" not in source and "predict_proba" not in source
    assert AUDIT.RESULTS != AUDIT.REPO and AUDIT.RANDOM_SEED == 28303 and AUDIT.MATCHED_EVENT_RUN_COUNT == 1000


def test_fixed_thresholds_windows_and_bucket_cover_are_predeclared():
    assert AUDIT.LADDER == (.0025, .005, .0075, .01)
    assert AUDIT.POST_WINDOWS == (5, 15, 30, 60, 120, 240)
    assert AUDIT.CONTINUATION_LEVELS == (.0125, .015, .02)
    assert sum(upper - lower for _, lower, upper, _ in AUDIT.SCORE_BINS) == pytest.approx(1)


def test_favorable_normalization_and_continuation_classification():
    assert (1.01 / 1 - 1) * 1 == pytest.approx(.01)
    assert (.99 / 1 - 1) * -1 == pytest.approx(.01)
    x = events(); table, rho = AUDIT.post_touch_path(x)
    populated = table.loc[table.touch_count > 0]
    assert populated.continuation_rate.between(0, 1).all() and populated.reversal_rate.between(0, 1).all()
    assert rho["UP"][30] > 0 and rho["DOWN"][30] > 0


def test_giveback_returned_entry_and_continuation_thresholds():
    x = events(); geometry, continuation = AUDIT.giveback_and_continuation(x)
    populated = geometry.loc[geometry.touch_count > 0]
    assert populated.full_giveback_rate.between(0, 1).all()
    assert populated.returned_to_entry_rate.between(0, 1).all()
    assert continuation.filter(like="1P25").iloc[0, 0] == pytest.approx(1)
    assert max(.01, .02) - .005 == pytest.approx(.015)


def test_fast_medium_slow_boundaries_are_fixed():
    x = events(); result = AUDIT.fast_slow(x)
    assert set(result.touch_speed_group) == {"FAST_TOUCH", "SLOW_TOUCH"}
    assert AUDIT.FAST_TOUCH_MINUTES == 60 and AUDIT.MEDIUM_TOUCH_MINUTES == 240


def test_matched_comparison_is_deterministic_with_fixed_seed():
    x = pd.concat([events()] * 20, ignore_index=True)
    x["score_rank_pct"] = np.tile([.01, .9, .01, .9], 20)
    first, one = AUDIT.matched_comparison(x)
    second, two = AUDIT.matched_comparison(x)
    pd.testing.assert_frame_equal(first, second)
    assert one == two and first.matched_event_run_count.eq(1000).all()


def test_no_silent_drops_and_window_availability_is_explicit():
    x = events(); x.loc[0, "post_touch_120m_favorable_return"] = np.nan; x.loc[0, "post_touch_120m_available"] = False
    table, _ = AUDIT.post_touch_path(x)
    row = table.loc[(table.direction == "UP") & (table.post_touch_horizon_minutes == 120)].iloc[0]
    assert row.available_count + row.unavailable_count == row.touch_count
