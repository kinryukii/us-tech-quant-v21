import importlib.util
from pathlib import Path
import pandas as pd
P=Path(__file__).with_name('v22_080a_fast3_24h_one_percent_move_atlas_r1.py'); spec=importlib.util.spec_from_file_location('m',P); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
def f(v):
 t=pd.date_range('2024-01-02 04:00',periods=len(v),freq='min',tz='America/New_York'); return pd.DataFrame({'timestamp_et':t,'timestamp_utc':t.tz_convert('UTC'),'broker_trade_date':'2024-01-02','session':'PREMARKET','open':[x[0] for x in v],'high':[x[1] for x in v],'low':[x[2] for x in v],'close':[x[3] for x in v],'volume':1,'valid_bar':True})
def test_up_first_touch(): assert m.detect_events(f([(100,100,100,100),(100,100.9,100,100),(100,101,100,100)]),'QQQ').query("direction=='UP'").shape[0]==1
def test_down_first_touch(): assert m.detect_events(f([(101.5,101.5,101.5,101.5),(101.5,102,101.5,101.8),(101,101,100.98,101)]),'QQQ').query("direction=='DOWN'").iloc[0].start_price==102
def test_reset_nonoverlap(): assert len(m.detect_events(f([(100,100,100,100),(100,101,100,100),(100,100,100,100),(100,101,100,100)]),'QQQ'))==2
def test_same_bar_ambiguous(): assert 'AMBIGUOUS' in set(m.detect_events(f([(100,100,100,100),(100,102,98,100)]),'QQQ').direction)
def test_session_normalize(): assert m.normalize_session('junk')=='UNKNOWN_SESSION'
def test_mapping_complete(): assert len(m.MAPPING)==4 and m.MAPPING[('SOXX','DOWN')]=='SOXS'
def test_first_after_exact(): assert m.first_at_or_after(f([(1,1,1,1)]),pd.Timestamp('2024-01-02 09:00',tz='UTC')) is not None
def test_first_after_gap_rejected(): assert m.first_at_or_after(f([(1,1,1,1)]),pd.Timestamp('2024-01-02 08:00',tz='UTC'),1) is None
def test_primary_mapping_excludes_pre_entry_target_from_mapping_denominator():
    x=pd.DataFrame({'latency_minutes':[3,3,3,1],'latency_mapping_status':['SUCCESS','TARGET_ALREADY_REACHED_BEFORE_DELAY','ENTRY_TIMESTAMP_MISMATCH','SUCCESS']})
    all_, eligible, success, metrics=m.primary_mapping_metrics(x)
    assert len(all_)==3 and len(eligible)==2 and len(success)==1
    assert metrics['primary_delay_ineligible_count']==1 and metrics['primary_leveraged_mapping_success_rate']==.5
def test_safety_source(): assert 'order_generation_allowed":False' in P.read_text()
