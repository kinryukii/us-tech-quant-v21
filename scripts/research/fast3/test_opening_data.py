"""Targeted no-fit checks for the fixed 09:45 feature/target adapter."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import opening_data as m


def clocks(dates, clock):
    return pd.to_datetime(pd.Series(dates).astype(str)+' '+clock).dt.tz_localize('America/New_York').dt.tz_convert('UTC')


def cal(dates, half=()):
    x = pd.DataFrame({'date': dates})
    x['market_open_utc'] = clocks(x.date, '09:30')
    x['market_close_utc'] = [clocks([d], '13:00' if d in half else '16:00').iloc[0] for d in dates]
    return x


def bars(date='2025-11-28', ticker='NVDA', half=True):
    rows = []
    for minute in list(range(571, 588))+[750, 780 if half else 960]:
        price = 100+(minute-570)/100
        rows.append({'symbol': ticker, 'timestamp_utc': clocks([date], f'{minute//60:02}:{minute%60:02}').iloc[0],
                     'open': price-.01, 'close': price, 'high': price+.01, 'low': price-.02, 'volume': 10.})
    return pd.DataFrame(rows)


def result(x, dates=None):
    if dates is None:
        dates = sorted(x.timestamp_utc.dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d').unique())
    return m.summarize_minutes(x, cal(dates, half=dates)).iloc[-1]


def mask_clock(x, clock):
    return x.timestamp_utc.dt.tz_convert('America/New_York').dt.strftime('%H:%M').eq(clock)


def test_exact_ending_bars_and_half_day():
    x = bars()
    x.loc[mask_clock(x, '09:46'), ['open', 'close', 'high', 'low']] = [50, 50, 50, 50]
    r = result(x)
    assert r.price_at_09_46 == pytest.approx(100.16)
    assert r.price_at_12_30 == pytest.approx(101.8)
    assert r.opening_return == pytest.approx(100.14/100-1)
    assert r.label_reason == 'OK'
    assert r.opening_valid_bar_fraction == 1
    assert r.opening_staleness_minutes == 0


def test_after_cutoff_changes_cannot_affect_opening_inputs():
    x = bars()
    y = x.copy()
    later = y.timestamp_utc.dt.tz_convert('America/New_York').dt.strftime('%H:%M').ge('09:45')
    y.loc[later, ['open', 'high', 'low', 'close', 'volume']] *= 10
    pd.testing.assert_series_equal(result(x)[m.OPENING_COLUMNS], result(y)[m.OPENING_COLUMNS])
    assert result(x).price_at_09_46 != result(y).price_at_09_46


def test_missing_label_does_not_invalidate_features():
    x = bars()
    absent = x[~mask_clock(x, '09:47')]
    assert result(absent).label_reason == 'MISSING_OR_INVALID_START_0947'
    assert np.isnan(result(absent).price_at_09_46)
    pd.testing.assert_series_equal(result(x)[m.OPENING_COLUMNS], result(absent)[m.OPENING_COLUMNS])


def test_missing_and_stale_window_are_field_local():
    x = bars()
    x = x[~mask_clock(x, '09:44')]
    r = result(x)
    assert r.opening_staleness_minutes == 1
    assert r.opening_valid_bar_fraction == pytest.approx(13/14)
    assert np.isnan(r.opening_return)
    assert np.isnan(r.opening_rv)
    assert r.opening_range > 0
    assert r.label_reason == 'OK'


def test_missing_open_bar_keeps_known_range_position_and_drawdown():
    x = bars()
    r = result(x[~mask_clock(x, '09:31')])
    assert np.isnan(r.opening_range)
    assert np.isnan(r.opening_return)
    assert np.isnan(r.opening_rv)
    assert np.isfinite(r.opening_range_position)
    assert np.isfinite(r.opening_drawdown)
    assert r.opening_valid_bar_fraction == pytest.approx(13/14)


def test_zero_range_and_zero_trade_volume():
    x = bars()
    x[['open', 'close', 'high', 'low']] = 100.
    r = result(x)
    assert r.opening_efficiency == 0
    assert r.opening_rv == 0
    assert np.isnan(r.opening_range_position)
    x.volume = 0.
    r = result(x)
    assert r.opening_valid_bar_fraction == 0
    assert np.isnan(r.opening_relative_volume)
    assert r.label_reason == 'MISSING_OR_INVALID_BOTH_ENDPOINTS'


def test_exact_previous_half_day_close_not_last_observation():
    dates = ['2025-11-28', '2025-12-01', '2025-12-02']
    x = pd.concat([bars(d, half=True) for d in dates if d != dates[1]], ignore_index=True)
    z = m.summarize_minutes(x, cal(dates, half=dates))
    assert np.isnan(z.loc[z.date.eq(dates[2]), 'opening_gap'].iloc[0])
    complete = pd.concat([x, bars(dates[1])], ignore_index=True)
    z = m.summarize_minutes(complete, cal(dates, half=dates))
    assert z.loc[z.date.eq(dates[1]), 'opening_gap'].iloc[0] == pytest.approx(100/102.1-1)


def test_volume_history_uses_20_calendar_sessions_with_minimum_10():
    dates = pd.bdate_range('2025-09-01', periods=42).strftime('%Y-%m-%d').tolist()
    # First 21 have volume 140, last has volume 140; intervening 20 sessions missing.
    x = pd.concat([bars(d) for d in dates[:21]+dates[-1:]], ignore_index=True)
    z = m.summarize_minutes(x, cal(dates, half=dates))
    assert np.isnan(z.iloc[9].opening_relative_volume)
    assert z.iloc[10].opening_relative_volume == 1
    assert np.isnan(z.iloc[-1].opening_relative_volume)


def test_dst_and_pre2026_boundary():
    dates = ['2025-03-07', '2025-03-10']
    x = pd.concat([bars(d) for d in dates], ignore_index=True)
    z = m.summarize_minutes(x, cal(dates, half=dates))
    assert [v.hour for v in z.opening_last_feature_bar_end_utc] == [14, 13]
    with pytest.raises(ValueError, match='2026'):
        m.summarize_minutes(bars('2026-01-02'), cal(['2026-01-02']))


def test_duplicate_bar_fails_without_keep_last():
    x = bars()
    with pytest.raises(ValueError, match='Duplicate'):
        result(pd.concat([x, x.iloc[:1]], ignore_index=True))


def test_actual_store_reader_filters_mixed_2026_before_pandas(tmp_path):
    sys.path.insert(0, 'D:/us-tech-quant')
    from scripts.storage.storage_r2a import DataStore
    from scripts.common.storage_paths import resolve
    # Synthetic file is inside this test reader's explicitly configured cache.
    store = DataStore(resolve(Path('D:/us-tech-quant'), cache_root=tmp_path))
    path = tmp_path/'mixed.parquet'
    x = pd.concat([bars('2025-12-31'), bars('2026-01-02')], ignore_index=True)
    x.to_parquet(path, index=False)
    result = m.safe_minute_read(store, [path])
    assert len(result) == len(bars('2025-12-31'))
    assert result.timestamp_utc.max() < m.CUTOFF


def test_a_b_values_missing_population_and_unlabelled_predictions_align():
    dates = ['2025-11-28']
    tickers = m.TICKERS+['UNACQUIRED']
    old = pd.DataFrame({'ticker': tickers, 'date': dates*len(tickers), 'eligible': True,
                        'pm_a': [1., np.nan, 3., 4., np.nan], 'market_a': 1.})
    old['sample_id'] = old.ticker+'|'+old.date
    old['prediction_at_utc'] = clocks(old.date, '09:25')
    old['last_feature_bar_end_utc'] = clocks(old.date, '09:24')
    summaries = {}
    for ticker in m.TICKERS+['QQQ', 'SOXX']:
        x = bars(ticker=ticker)
        if ticker == 'NVDA':
            x = x[~mask_clock(x, '09:47')]
        summaries[ticker] = m.summarize_minutes(x, cal(dates, half=dates))
    panel, config = m.assemble_panel(old, summaries, ['pm_a', 'market_a'], ['market_a'], clocks)
    assert len(panel) == 5
    assert int(panel.prediction_eligible.sum()) == 4
    assert int(panel.evaluable.sum()) == 3
    assert np.isnan(panel.loc[panel.ticker.eq('NVDA'), 'y'].iloc[0])
    assert config['inherited_A_B_comparison']['status'] == 'PASS'
    assert config['feature_columns_B'][:2] == config['feature_columns_A']
    assert config['baseline_columns_B'] == ['market_a']+m.MARKET_OPENING_COLUMNS


def test_inherited_a_cannot_update_to_0945_pit():
    old = pd.DataFrame({'ticker': ['NVDA'], 'date': ['2025-11-28'], 'eligible': [True],
        'sample_id': ['NVDA|2025-11-28'], 'pm_a': [1.]})
    old['prediction_at_utc'] = clocks(old.date, '09:25')
    old['last_feature_bar_end_utc'] = clocks(old.date, '09:24')
    old['pit_sec_available_at'] = clocks(old.date, '09:30')
    with pytest.raises(ValueError, match='Inherited A PIT'):
        m.assemble_panel(old, {}, ['pm_a'], [], clocks)
