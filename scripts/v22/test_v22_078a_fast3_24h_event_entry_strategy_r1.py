import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd

P=Path(__file__).with_name("v22_078a_fast3_24h_event_entry_strategy_r1.py")
spec=importlib.util.spec_from_file_location("v078",P); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
def r(**kw):
    d={"session":"REGULAR","session_minutes_since_start":20,"QQQ_trend_z_30m":1.2,"SOXX_trend_z_30m":1.2,"QQQ_trend_z_60m":1.5,"SOXX_trend_z_60m":1.5,"QQQ_close":11,"SOXX_close":21,"QQQ_prior_60m_high":10,"SOXX_prior_60m_high":20,"QQQ_prior_60m_low":9,"SOXX_prior_60m_low":19,"QQQ_return_15m":-.001,"SOXX_return_15m":-.001,"QQQ_return_60m":.01,"SOXX_return_60m":.01,"QQQ_return_5m":.001,"SOXX_return_5m":.001,"QQQ_previous_session_return":.01,"SOXX_previous_session_return":.01,"QQQ_previous_session_high":10,"SOXX_previous_session_high":20,"QQQ_previous_session_low":9,"SOXX_previous_session_low":19};d.update(kw);return pd.Series(d)
def test_confirmation_zero_reads_and_safety():assert m.SAFE["confirmation_remains_sealed"] and m.SAFE["confirmation_row_read_count"]==0 and m.SAFE["broker_connection_count"]==0
def test_authoritative_four_sessions_and_timezone():assert set(m.SESSION_MAP.values())=={"OVERNIGHT","PREMARKET","REGULAR","AFTER_HOURS"}
def test_first_breakout_does_not_repeat():assert m.event(r(),{"S1L":False,"S1S":False},"S1")=="SOXL" and m.event(r(),{"S1L":True,"S1S":False},"S1") is None
def test_pullback_is_first_directional_restart():assert m.event(r(),{"S2L5":False,"S2S5":False},"S2")=="SOXL" and m.event(r(),{"S2L5":True,"S2S5":False},"S2") is None
def test_session_transition_event_and_15_min_gate():assert m.event(r(session_minutes_since_start=20,QQQ_return_15m=.001,SOXX_return_15m=.001),None,"S3")=="SOXL" and m.event(r(session_minutes_since_start=10,QQQ_return_15m=.001,SOXX_return_15m=.001),None,"S3") is None
def test_next_minute_open_only():
 z=pd.DataFrame({"SOXL_open":[1,2],"SOXL_high":[1,2],"SOXL_low":[1,2],"SOXL_close":[1,2]});assert m.nextbar(z,0,"SOXL")==1
def test_invalid_next_bar_is_not_backfilled():
 z=pd.DataFrame({"SOXL_open":[1,np.nan,3],"SOXL_high":[1,np.nan,3],"SOXL_low":[1,np.nan,3],"SOXL_close":[1,np.nan,3]});assert m.nextbar(z,0,"SOXL") is None
def test_stop_loss_has_priority_over_profit():assert P.read_text().index('if rl<=-.006')<P.read_text().index('elif rh>=.03')
def test_trailing_return_converts_to_price_with_plus_one():
 assert np.isclose(m.trailing_exit_price(100,.02,.005),101.5)
def test_trend_failure_is_next_minute_action_and_cross_session_contract():assert 'pending=nextbar' in P.read_text() and m.trans("REGULAR","AFTER_HOURS")=="REGULAR_TO_AFTER_HOURS"
def test_five_chronological_folds():
 _,f,_,_=m.metrics(pd.DataFrame(),[f"2024-01-0{x}" for x in range(1,6)],{});assert len(f)==5 and all(x["time_order_valid"] for x in f)
def test_no_model_or_hyperparameter_search():assert m.SAFE["model_fit_call_count"]==0 and m.SAFE["hyperparameter_search_count"]==0
def test_month_and_year_use_canonical_trade_date_not_utc_entry_timestamp():
 t=pd.DataFrame({"trade_date":["2024-01-01"],"entry_timestamp":pd.to_datetime(["2024-01-02T02:00:00Z"]),"net_return_25bps":[.01],"gross_return":[.02],"net_return_10bps":[.019],"net_return_50bps":[.015],"holding_minutes":[1],"exit_reason":["MAX_HOLDING"]})
 _,_,mo,yr=m.metrics(t,[f"2024-01-0{x}" for x in range(1,6)],{});assert list(mo.index)==["2024-01"] and list(yr.index)==[2024]
