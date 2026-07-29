from pathlib import Path
import numpy as np, pandas as pd, pytest
import v22_050_fast3_six_etf_minute_tradability_audit_r1 as m

def good():return {"data_baseline_frozen":True,"v22_050_allowed":True,"canonical_parquet_count":582,"duplicate_count":0,"invalid_ohlc_count":0}
def test_bad_baseline():
    x=good();x["data_baseline_frozen"]=False
    with pytest.raises(m.AuditError):m.validate_snapshot(x)
def test_good_baseline():m.validate_snapshot(good())
def test_naive_rejected():
    with pytest.raises(m.AuditError):m.normalize_utc(pd.Series(pd.to_datetime(["2026-01-01"])))
def test_sessions():
    u=pd.Series(pd.to_datetime(["2026-01-02T01:00:00Z","2026-01-02T10:00:00Z","2026-01-02T15:00:00Z","2026-01-02T22:00:00Z"],utc=True));assert m.classify_session(u.dt.tz_convert("America/New_York")).tolist()==list(m.SESSIONS)
def test_sunday_night():
    u=pd.Series(pd.to_datetime(["2026-01-05T01:00:00Z"],utc=True));assert m.broker_date(u.dt.tz_convert("America/New_York")).iloc[0]=="2026-01-05"
def test_alignment():
    r=m.alignment(np.array([1,2,3,4]),np.array([2,3,4,5]));assert r["alignment_ratio"]==.75 and r["missing_execution_timestamp_count"]==1
def test_rth_eligible():assert m.tradability("RTH",100,.995,.97,.01,1000,True)=="BACKTEST_ELIGIBLE"
def test_night_not_eligible_on_low_volume():assert m.tradability("NIGHT",100,1,1,0,1,True)=="BACKTEST_WITH_CAUTION"
def test_gate_pass():
    r={s:"BACKTEST_ELIGIBLE" for s in m.SYMBOLS};a={p:.999 for p in m.RTH_REQUIRED};assert m.fast3_gate(r,a,0,0,True,True)==(True,[])
def test_gate_symbol_fail():
    r={s:"BACKTEST_ELIGIBLE" for s in m.SYMBOLS};r["SOXS"]="BACKTEST_WITH_CAUTION";a={p:.999 for p in m.RTH_REQUIRED};ok,f=m.fast3_gate(r,a,0,0,True,True);assert not ok and "rth_not_eligible_SOXS" in f
def test_gate_alignment_fail():
    r={s:"BACKTEST_ELIGIBLE" for s in m.SYMBOLS};a={p:.999 for p in m.RTH_REQUIRED};a["QQQ_TQQQ"]=.9;ok,f=m.fast3_gate(r,a,0,0,True,True);assert not ok and any("QQQ_TQQQ" in x for x in f)
def test_policy_fixed_false():
    src=Path(m.__file__).read_text(encoding="utf-8-sig");assert '"broker_action_allowed":False' in src and '"official_adoption_allowed":False' in src and '"paper_trading_allowed":False' in src
