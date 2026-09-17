"""Targeted causal and endpoint tests, never a substitute for historical fits."""
import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

spec = importlib.util.spec_from_file_location('stock_open_3h_tested', Path(__file__).with_name('stock_open_3h.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def bars(date='2024-01-03'):
    clocks = ['04:01','09:24','09:25','09:30','09:31','12:29','12:30','12:31','16:00']
    opens = [98,99,101,105,100,101,102,500,105]
    closes = [98,99,101,105,100.2,101.5,103,500,106]
    return pd.DataFrame({'symbol':'NVDA', 'timestamp_utc':pd.to_datetime([date+' '+c for c in clocks]).tz_localize('America/New_York').tz_convert('UTC'),
                         'open':opens,'close':closes,'high':np.maximum(opens,closes),'low':np.minimum(opens,closes),
                         'volume':10.,'turnover':np.array(closes)*10})


def test_exact_end_stamped_three_hour_target():
    r = m.minute_summary(bars()).iloc[0]
    assert r.open_price == 100
    assert r.price_12_30 == 103
    assert r.label_reason == 'OK'
    assert r.last_feature_bar_end_utc == pd.Timestamp('2024-01-03 14:24Z')


def test_post_prediction_values_cannot_change_same_day_features():
    a = bars()
    b = a.copy()
    later = b.timestamp_utc >= pd.Timestamp('2024-01-03 14:25Z')
    b.loc[later,['open','high','low','close','volume','turnover']] *= 10
    x,y = m.minute_summary(a),m.minute_summary(b)
    columns = [c for c in x if c.startswith('pm_')]
    pd.testing.assert_frame_equal(x[columns],y[columns])


def test_endpoint_missing_or_no_trade_is_not_zero_return():
    x = bars()
    x = x[x.timestamp_utc != pd.Timestamp('2024-01-03 17:30Z')]
    r = m.minute_summary(x).iloc[0]
    assert pd.isna(r.price_12_30)
    assert r.label_reason == 'MISSING_OR_NO_TRADE_ENDPOINT'
    x = bars()
    x.loc[x.timestamp_utc.eq(pd.Timestamp('2024-01-03 17:30Z')),'volume'] = 0
    assert m.minute_summary(x).iloc[0].label_reason == 'MISSING_OR_NO_TRADE_ENDPOINT'


def test_future_rth_values_only_reach_later_dates():
    a = pd.concat([bars('2024-01-03'),bars('2024-01-04')],ignore_index=True)
    b = a.copy()
    b.loc[b.timestamp_utc.eq(pd.Timestamp('2024-01-04 21:00Z')),'close'] = 999
    x,y = m.add_lags(m.minute_summary(a)),m.add_lags(m.minute_summary(b))
    cols = [c for c in x if c.startswith(('pm_','lag_'))]
    pd.testing.assert_frame_equal(x[cols],y[cols])


def test_duplicates_and_2026_are_rejected():
    with pytest.raises(ValueError,match='Duplicate'):
        m.minute_summary(pd.concat([bars(),bars().iloc[:1]]))
    with pytest.raises(ValueError,match='2026'):
        m.minute_summary(bars('2026-01-02'))


def test_dst_and_half_day_have_exact_1230_endpoints():
    winter,summer = m.minute_summary(bars('2024-01-03')),m.minute_summary(bars('2024-07-03'))
    assert winter.last_feature_bar_end_utc.iloc[0].hour == 14
    assert summer.last_feature_bar_end_utc.iloc[0].hour == 13
    x = bars('2024-07-03')
    x = x[x.timestamp_utc < pd.Timestamp('2024-07-03 17:00Z')]
    r = m.minute_summary(x).iloc[0]
    assert r.label_reason == 'OK'
    assert 'rth_return' not in r or pd.isna(r.rth_return)


def test_early_close_after_hours_is_excluded_from_rth_lags():
    x = bars('2024-07-03')
    # A real half-day can still have an after-hours bar stamped 16:00.
    r = m.minute_summary(x, {'2024-07-03'}).iloc[0]
    assert r.label_reason == 'OK' and r.price_12_30 == 103
    assert 'rth_return' not in r or pd.isna(r.rth_return)


def test_missing_session_does_not_shift_previous_observation_into_yesterday():
    x = pd.concat([bars('2024-01-03'), bars('2024-01-05')], ignore_index=True)
    out = m.add_lags(m.minute_summary(x), ['2024-01-03','2024-01-04','2024-01-05'])
    assert len(out) == 3
    assert pd.isna(out.loc[out.date.eq('2024-01-05'), 'lag_rth_return'].iloc[0])
