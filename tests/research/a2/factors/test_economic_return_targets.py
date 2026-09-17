import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.factors.economic_return_targets import attach_economic_targets, HORIZONS


def fixture():
    calendar = pd.bdate_range('2022-01-03', periods=90)
    panel = pd.DataFrame([(d, t) for d in calendar[25:45] for t in ('A', 'B', 'C')], columns=['signal_date', 'ticker'])
    frame = pd.DataFrame([(d, t, r) for d in calendar for t, r in [('A', .001), ('B', .002), ('C', .003)]], columns=['trade_date', 'ticker', 'gross_accrual_return'])
    return panel, frame, calendar


def test_four_horizon_compounding_and_common_offset_rank_equivalence():
    panel, frame, calendar = fixture()
    out = attach_economic_targets(panel, frame, calendar, expected_names_per_date=3)
    for h in HORIZONS:
        np.testing.assert_allclose(out.loc[out.ticker.eq('B'), f'economic_stock_return_{h}d'], (1.002 ** h) - 1)
    np.testing.assert_allclose(out.target, np.tile([1/3, 2/3, 1], len(panel)//3))
    assert out.target_end_date.iloc[0] == calendar[45]
    mean = out[[f'economic_stock_return_{h}d' for h in HORIZONS]].mean(axis=1)
    common_offset = out.signal_date.map({d: x for x, d in enumerate(out.signal_date.unique())})
    np.testing.assert_allclose((mean-common_offset).groupby(out.signal_date).rank(method='average', pct=True), out.target)


def test_unsupported_future_day_preserves_every_key_and_prevents_partial_rank():
    panel, frame, calendar = fixture()
    bad = frame.ticker.eq('B') & frame.trade_date.eq(calendar[35])
    frame.loc[bad, 'gross_accrual_return'] = np.nan
    out = attach_economic_targets(panel, frame, calendar, expected_names_per_date=3)
    pd.testing.assert_frame_equal(out[['signal_date', 'ticker']], panel)
    affected = out.signal_date.lt(calendar[35])
    assert out.loc[affected, 'target'].isna().all()
    assert out.loc[~affected, 'target'].notna().all()
    assert out.loc[affected & out.ticker.eq('A'), 'target_valid'].all()
    assert not out.loc[affected, 'target_universe_complete'].any()


def test_future_return_change_cannot_change_matured_labels():
    panel, frame, calendar = fixture()
    old = attach_economic_targets(panel, frame, calendar, expected_names_per_date=3)
    changed = frame.copy()
    changed.loc[changed.trade_date.gt(calendar[55]), 'gross_accrual_return'] = .09
    new = attach_economic_targets(panel, changed, calendar, expected_names_per_date=3)
    mature = old.target_end_date.le(calendar[55])
    pd.testing.assert_frame_equal(old.loc[mature], new.loc[mature])


def test_rejects_changed_maturity_and_does_not_silently_drop_members():
    panel, frame, calendar = fixture()
    with pytest.raises(ValueError, match='cardinality'):
        attach_economic_targets(panel.iloc[1:], frame, calendar, expected_names_per_date=3)
    panel['target_end_date'] = calendar[-1]
    with pytest.raises(ValueError, match='maturity'):
        attach_economic_targets(panel, frame, calendar, expected_names_per_date=3)


def test_zero_terminal_gross_value_is_a_valid_arithmetic_return():
    panel, frame, calendar = fixture()
    frame.loc[frame.ticker.eq('B') & frame.trade_date.eq(calendar[35]), 'gross_accrual_return'] = -1.0
    out = attach_economic_targets(panel, frame, calendar, expected_names_per_date=3)
    assert out.target.notna().all()
    assert out.loc[(out.ticker.eq('B')) & out.signal_date.lt(calendar[35]), 'economic_stock_return_20d'].eq(-1).all()


def test_coverage_only_mode_does_not_compute_values_or_rankings():
    panel, frame, calendar = fixture()
    out = attach_economic_targets(panel, frame, calendar, expected_names_per_date=3, compute_values=False)
    assert out.target.isna().all()
    assert out.target_valid.all() and out.target_universe_complete.all()
    for horizon in HORIZONS:
        assert f'economic_stock_return_{horizon}d' not in out
        assert out[f'economic_stock_return_{horizon}d_valid'].all()
