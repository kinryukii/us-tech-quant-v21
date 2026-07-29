import ast, importlib.util
from pathlib import Path
import numpy as np, pandas as pd
p=Path(__file__).with_name('v22_067_fast3_multifactor_feature_atlas_r1.py');s=importlib.util.spec_from_file_location('atlas',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def test_1_cutoff_guard(): assert 'x=x[x.index<=cut]' in p.read_text()
def test_2_trailing_volume_excludes_current(): assert "Timedelta(days=1)" in p.read_text()
def test_3_no_split_refit(): assert 'src.quantile(.8)' in p.read_text()
def test_4_alignment_guard(): assert 'timestamp_alignment_error' in p.read_text()
def test_5_leverage_formula(): assert np.isclose(m.leverage_deviation(.10,.02),.04)
def test_6_gap_up_down(): assert m.gap_fill(100,110,105)==.5 and m.gap_fill(100,90,95)==.5
def test_7_gap_zero_safe(): assert np.isnan(m.gap_fill(100,100,101))
def test_8_mfe_mae_direction():
 x=pd.DataFrame({'close':[100,102,99]},index=pd.date_range('2026-01-01',periods=3,freq='min',tz='UTC'));z=m.path_labels(x,100,'LONG');assert np.isclose(z['MFE'],.02) and np.isclose(z['MAE'],-.01)
def test_9_unhit_target_null():
 x=pd.DataFrame({'close':[100,101]},index=pd.date_range('2026-01-01',periods=2,freq='min',tz='UTC'));assert pd.isna(m.path_labels(x,100,'LONG')['TIME_TO_PLUS_3PCT_MINUTES'])
def test_10_missing_trend(): assert np.isnan(m.trend_slope([1]*24,31))
def test_11_join_preservation_guard(): assert 'silent_join_drop_count' in p.read_text()
def test_12_hash_guard(): assert 'before={str(p):sha(p) for p in FROZEN}' in p.read_text()
def test_13_no_broker(): assert 'BROKER_ACTION_ALLOWED\':False' in p.read_text()
def test_14_no_paper(): assert 'PAPER_TRADING_ALLOWED\':False' in p.read_text()
def test_15_no_fit_or_random_split():
 calls=[n.func.attr for n in ast.walk(ast.parse(p.read_text())) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)];assert not {'fit','fit_transform','partial_fit','train_test_split'}.intersection(calls)
