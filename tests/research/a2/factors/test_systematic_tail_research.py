import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.factors.systematic_tail_research import chronological_masks, holm


def test_label_maturity_and_embargo_are_strict():
    dates = pd.bdate_range("2022-11-01", "2023-02-01")
    start = dates[dates.year == 2023][0]
    boundary = dates[dates.get_loc(start) - 5]
    panel = pd.DataFrame({"signal_date": [dates[0], dates[1], dates[2], start],
        "target_end_date": [boundary-pd.Timedelta(days=1), boundary, start, start+pd.Timedelta(days=20)],
        "target": [1., 2., 3., 4.]})
    train, valid, audit = chronological_masks(panel, 2023, dates)
    assert train.tolist() == [True, False, False, False]
    assert valid.tolist() == [False, False, False, True]
    assert audit["max_train_label_maturity"] < boundary


def test_future_label_changes_do_not_change_earlier_training_membership():
    dates = pd.bdate_range("2022-01-03", "2023-04-01")
    panel = pd.DataFrame({"signal_date": dates, "target_end_date": dates+pd.Timedelta(days=30), "target": 0.1})
    original = chronological_masks(panel, 2023, dates)[0]
    panel.loc[panel.signal_date.dt.year.eq(2023), "target"] = 99.0
    assert original.equals(chronological_masks(panel, 2023, dates)[0])


def test_holm_stepdown_known_values_and_order():
    np.testing.assert_allclose(holm([0.04, 0.001, 0.02]), [0.04, 0.003, 0.04])
    np.testing.assert_allclose(holm([1., 1., 1.]), [1., 1., 1.])
    with pytest.raises(ValueError):
        holm([np.nan])


def test_date_common_benchmark_cannot_change_ordinal_multihorizon_target():
    stock = np.array([[0.02, 0.05, -0.01, 0.12], [0.03, 0.01, 0.03, 0.04], [-0.1, 0.2, 0.3, 0.1]])
    benchmark = np.array([0.03, -0.02, 0.06, 0.08])
    changed_benchmark = benchmark + np.array([2.0, -4.0, 3.0, 6.0])
    rank = lambda market: pd.Series((stock - market).mean(axis=1)).rank(method="average", pct=True)
    pd.testing.assert_series_equal(rank(benchmark), rank(changed_benchmark))
