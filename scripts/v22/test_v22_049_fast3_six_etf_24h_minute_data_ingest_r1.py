import importlib.util
from pathlib import Path
import pandas as pd
P=Path(__file__).with_name('v22_049_fast3_six_etf_24h_minute_data_ingest_r1.py'); S=importlib.util.spec_from_file_location('v22049',P); m=importlib.util.module_from_spec(S); S.loader.exec_module(m)
def test_fixed_contract():
 assert m.CFG['symbols']==['US.QQQ','US.SOXX','US.TQQQ','US.SQQQ','US.SOXL','US.SOXS']; assert m.CFG['page_size']==1000
def test_session_timezone_and_trade_boundary():
 x=pd.Timestamp('2026-07-24 21:00',tz=m.ET); assert m.classify(x)=='NIGHT'; assert m.broker_date(x)=='2026-07-25'; assert pd.Timestamp('2026-07-24 20:00').tz_localize(m.ET).tz_convert('UTC').hour==0
def test_normalize_no_fill_and_dedupe_key():
 f=pd.DataFrame([{'time_key':'2026-07-24 09:30:00','open':1,'high':2,'low':.5,'close':1.5,'volume':1}]); o=m.normalize(f,'US.QQQ','2026-01-01T00:00:00Z'); assert list(o.columns)==m.CANONICAL_COLUMNS; assert o.iloc[0].session=='RTH'; assert str(o.iloc[0].timestamp_jst).startswith('2026-07-24 22:30'); assert str(o.timestamp_utc.dtype)=='datetime64[ns, UTC]'
def test_mixed_offsets_normalize_to_utc():
 f=pd.DataFrame([{'time_key':'2026-03-08T01:59:00-05:00','open':1,'high':1,'low':1,'close':1,'volume':1},{'time_key':'2026-03-08T03:01:00-04:00','open':1,'high':1,'low':1,'close':1,'volume':1}]); o=m.normalize(f,'US.QQQ','x'); assert str(o.timestamp_utc.dtype)=='datetime64[ns, UTC]' and o.timestamp_utc.is_monotonic_increasing
def test_atomic_parquet(tmp_path):
 f=pd.DataFrame({'code':['US.QQQ'],'timestamp_et':['2026-01-01 00:00:00-05:00']}); target=tmp_path/'x.parquet'; m.atomic_parquet(f,target); assert target.exists()
def test_utc_concat_remains_datetime():
 a=pd.DataFrame({'t':pd.date_range('2026-01-01',periods=2,tz='UTC')}); b=a.copy(); x=pd.concat([a,b]); assert str(m.normalize_timestamp_utc(x.t).dtype)=='datetime64[ns, UTC]'
def test_aware_et_and_utc_unify():
 x=pd.Series([pd.Timestamp('2026-01-01',tz='UTC'),pd.Timestamp('2025-12-31 19:00',tz=m.ET)],dtype=object); assert m.normalize_timestamp_utc(x).nunique()==1
def test_nat_stays_datetime():
 x=m.normalize_timestamp_utc(pd.Series(['2026-01-01T00:00:00Z',pd.NA])); assert str(x.dtype)=='datetime64[ns, UTC]' and pd.isna(x.iloc[1])
def test_naive_futu_is_et_then_utc():
 x=m.normalize_timestamp_utc(pd.Series(['2026-07-24 09:30:00'])); assert x.iloc[0].hour==13
def test_et_derived_only_from_utc():
 x=m.normalize_timestamp_utc(pd.Series(['2026-07-24T13:30:00Z'])); et=x.dt.tz_convert(m.ET); assert isinstance(et.dtype,pd.DatetimeTZDtype) and et.iloc[0].hour==9
def test_summary_utc_format_contract():
 x=m.normalize_timestamp_utc(pd.Series(['2026-07-24T13:30:00Z'])); assert x.min().isoformat().replace('+00:00','Z').endswith('Z')
