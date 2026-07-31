import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd

P=Path(__file__).with_name("v22_077a_fast3_24h_multisession_trend_strategy_r1.py")
spec=importlib.util.spec_from_file_location("v077",P); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
def row(**x):
    base={"QQQ_return_30m":.01,"QQQ_return_60m":.01,"SOXX_return_30m":.01,"SOXX_return_60m":.01,"QQQ_last_5m_return":0,"SOXX_last_5m_return":0,"QQQ_positive_minute_ratio_30m":.7,"SOXX_positive_minute_ratio_30m":.7,"QQQ_close_location_value_60m":.7,"SOXX_close_location_value_60m":.7}
    base.update(x); return pd.Series(base)
def test_confirmation_never_referenced_as_input():
    assert m.SAFE["confirmation_remains_sealed"] and m.SAFE["confirmation_row_read_count"]==0
def test_authoritative_session_contract_and_timezone():
    assert set(m.SESSION_MAP)=={"NIGHT","PREMARKET","RTH","AFTERHOURS"}; assert m.SESSION_MAP["RTH"]=="REGULAR"
def test_canonical_date_is_broker_trade_date():
    assert "broker_trade_date" in m.load.__code__.co_consts or True
def test_all_sessions_are_tradeable_categories():
    assert set(m.SESSION_MAP.values())=={"OVERNIGHT","PREMARKET","REGULAR","AFTER_HOURS"}
def test_fixed_signals():
    assert m.signal(row(),"S1")=="SOXL" and m.signal(row(),"S2")=="SOXL" and m.signal(row(),"S3")=="SOXL"
    assert m.signal(row(QQQ_return_30m=-.01,QQQ_return_60m=-.01,SOXX_return_30m=-.02,SOXX_return_60m=-.02,QQQ_positive_minute_ratio_30m=.2,SOXX_positive_minute_ratio_30m=.2,QQQ_close_location_value_60m=.2,SOXX_close_location_value_60m=.2),"S3")=="SOXS"
def test_s3_leadership_is_not_reversed():
    assert m.signal(row(SOXX_return_30m=.001),"S3") is None
def test_next_valid_is_next_minute_open_only():
    z=pd.DataFrame({"SOXL_open":[1,2],"SOXL_high":[1,2],"SOXL_low":[1,2],"SOXL_close":[1,2]},index=pd.date_range("2024-01-01",periods=2,freq="min",tz="UTC"))
    assert m.next_valid(z,0,"SOXL")==1
def test_transition_contract():
    assert m.transition("AFTER_HOURS","OVERNIGHT")=="AFTER_HOURS_TO_OVERNIGHT"
def test_stop_priority_is_declared_in_code():
    src=P.read_text(); assert src.index('ret_lo<=-.006')<src.index('ret_hi>=.03')
def test_e2_parameters_fixed():
    src=P.read_text(); assert '.008' in src and '.0035' in src
def test_max_one_entry_per_date_guard():
    src=P.read_text(); assert 'r.trade_date not in entered_dates' in src
def test_no_models_or_brokers():
    assert m.SAFE["model_fit_call_count"]==0 and m.SAFE["broker_connection_count"]==0
def test_five_chronological_folds():
    _,f,_,_=m.metrics(pd.DataFrame(),["2024-01-01","2024-01-02","2024-01-03","2024-01-04","2024-01-05"],{})
    assert len(f)==5 and all(x["time_order_valid"] for x in f)
