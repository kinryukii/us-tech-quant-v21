import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SOURCE = Path(__file__).parents[2] / "scripts" / "run" / "fast3_r28_3b_soxx_natural_baseline.py"
SPEC = importlib.util.spec_from_file_location("r28_3b", SOURCE)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def cohort():
    return pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=10, freq="h", tz="UTC"),
                         "label": ["UP_FIRST", "DOWN_FIRST", "NO_EVENT", "UP_FIRST", "NO_EVENT"] * 2,
                         "probability_up": np.linspace(.1, .9, 10), "probability_down": np.linspace(.9, .1, 10),
                         "mfe_24h": np.linspace(.01, .10, 10), "mae_24h": -np.linspace(.01, .10, 10),
                         "terminal_return_24h": np.linspace(-.03, .03, 10), "time_to_event_minutes": [10, 20, np.nan, 30, np.nan] * 2,
                         "any_up_24h": [True] * 10, "any_down_24h": [True] * 10, "plus_threshold_24h": [True] * 10, "minus_threshold_24h": [True] * 10})


def test_no_fit_or_predict_or_data_root_writes():
    source = SOURCE.read_text(encoding="utf-8")
    assert ".fit(" not in source and "predict_proba" not in source
    assert AUDIT.DATA not in AUDIT.OUT.parents


def test_fixed_contract_constants_and_score_bins():
    assert AUDIT.HORIZON == pd.Timedelta(hours=24) and AUDIT.THRESHOLD == .01
    assert sum(upper - lower for _, lower, upper, _ in AUDIT.SCORE_BINS) == pytest.approx(1)
    assert [name for name, _, _, _ in AUDIT.SCORE_BINS][:3] == ["TOP_1PCT", "PCT_1_TO_2", "PCT_2_TO_5"]


def test_first_touch_and_reconciliation_labels():
    labels = AUDIT.first_touch_labels(np.array([2, -1, 4, 3]), np.array([-1, 2, 4, 1]))
    assert labels.tolist() == ["UP_FIRST", "DOWN_FIRST", "AMBIGUOUS", "DOWN_FIRST"]
    x = cohort(); summary = AUDIT.natural_summary(x)
    assert int(summary.loc[summary.metric.isin(["UP_FIRST", "DOWN_FIRST", "NO_EVENT", "TIE_OR_AMBIGUOUS"]), "count"].sum()) == len(x)


def test_natural_gain_lift_and_no_score_bucket_drop():
    x = pd.concat([cohort()] * 20, ignore_index=True); table, summary = AUDIT.score_event_table(x)
    assert table.groupby("head").candidate_count.sum().eq(len(x)).all()
    up = table.loc[(table["head"] == "UP") & (table.bucket == "TOP_1PCT")].iloc[0]
    assert up.absolute_probability_gain == pytest.approx(up.event_rate - up.natural_base_rate)
    assert up.relative_lift == pytest.approx(up.event_rate / up.natural_base_rate)
    assert summary["UP"]["top5_event_rate"] in (0.0, 1.0)


def test_sparse_mfe_mae_and_terminal_geometry_primitives():
    values = np.array([2., 5., 1., 4., 3.]); left, right = np.array([0, 1]), np.array([4, 3])
    assert AUDIT.query_extrema(AUDIT.sparse_extrema(values, True), left, right, True).tolist() == [5., 5.]
    assert AUDIT.query_extrema(AUDIT.sparse_extrema(values, False), left, right, False).tolist() == [1., 1.]
    reference, high, low, terminal = 2., 5., 1., 3.
    assert high / reference - 1 == 1.5 and low / reference - 1 == -.5 and terminal / reference - 1 == .5


def test_conditional_matching_is_deterministic_and_relaxes_in_order():
    x = pd.concat([cohort()] * 3, ignore_index=True); x["weekday"] = "Monday"; x["session"] = "PREMARKET"; x["calendar_month"] = "2024-01"
    first, second = AUDIT.conditional_baseline(x), AUDIT.conditional_baseline(x)
    pd.testing.assert_frame_equal(first, second)
    assert first.conditional_match_L0_count.sum() == first.selected_top5_count.sum()
    assert first.conditional_unmatched_count.sum() == 0
