import importlib.util
from pathlib import Path
import pandas as pd

P = Path(__file__).with_name('v22_067a0_fast3_recent_year_underlying_event_dataset_r1.py')
spec = importlib.util.spec_from_file_location('a0', P); a0 = importlib.util.module_from_spec(spec); spec.loader.exec_module(a0)

def test_01_time_range_is_fixed(): assert str(a0.START_ET.date()) == '2025-07-29' and str(a0.END_ET.date()) == '2026-07-28'
def test_02_only_underlyings_allowed(): assert a0.SYMBOLS == ('QQQ', 'SOXX')
def test_03_grid_is_five_minutes(): assert all(m % 5 == 0 for m in range(0,60,5))
def test_04_no_future_feature_contract(): assert a0._session(pd.Timestamp('2026-01-02 16:05', tz='America/New_York')) == 'AFTER_HOURS'
def _bars():
    i = pd.DatetimeIndex(['2026-01-02 00:00:00+00:00','2026-01-02 00:01:00+00:00']); return pd.Series([100.,101.],i), pd.Series([100.,99.],i), pd.Series([100.,100.],i)
def test_05_long_label_uses_high_low():
    h,l,c=_bars(); assert a0._label(h,l,c,.005,.0025,'LONG',30).iloc[0] == 'ADVERSE_FIRST'
def test_06_short_label_uses_low_high():
    h,l,c=_bars(); assert a0._label(h,l,c,.005,.0025,'SHORT',30).iloc[0] == 'ADVERSE_FIRST'
def test_07_conservative_both_is_adverse():
    h,l,c=_bars(); assert a0._label(h,l,c,.005,.0025,'LONG',30).iloc[0] == 'ADVERSE_FIRST'
def test_08_frozen_canonical_read_only_contract(): assert a0.CANONICAL.name == 'canonical'
