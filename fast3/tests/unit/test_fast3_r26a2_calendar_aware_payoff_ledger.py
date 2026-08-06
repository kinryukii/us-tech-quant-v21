from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from fast3.economics import executable_payoff_ledger_calendar_hard_r26a2 as m

def candidate(anchor="2020-01-03 20:59Z"):
    return pd.DataFrame({"candidate_id":["c"],"candidate_instrument":["QQQ"],"decision_timestamp_et":[pd.Timestamp(anchor)],"authoritative_anchor_timestamp_et":[pd.Timestamp(anchor)]})
def bars(symbol="TQQQ"):
    # Friday close entry; the immutable +24h target is Saturday and is rescued
    # by Monday's first legal open, well inside the fixed 96-hour allowance.
    ts=pd.DatetimeIndex(["2020-01-03 20:58Z","2020-01-03 21:00Z","2020-01-06 14:30Z","2020-01-06 14:31Z"])
    return pd.DataFrame({"symbol":symbol,"timestamp_et":ts,"open":[10.,11.,12.,13.],"high":[11.,12.,13.,14.],"low":[9.,10.,11.,12.],"close":[10.5,11.5,12.5,13.5],"volume":[1.]*4,"bar_hash":[str(x) for x in range(4)]})
def test_mapping_real_etfs_and_unknown_fail_closed():
    x=m.assert_candidate_map(candidate()); assert x.up_action_instrument.iloc[0]=="TQQQ" and x.down_action_instrument.iloc[0]=="SQQQ"
    with pytest.raises(m.R26A2ContractError,match="MAPPING_UNRESOLVED"): m.assert_candidate_map(candidate().assign(candidate_instrument="SPY"))
def test_strict_entry_frozen_24h_weekend_rescue_open_costs_and_no_pretarget_exit():
    out=m._join_action(m.assert_candidate_map(candidate()),bars(),"up"); row=out.iloc[0]
    assert row.up_entry_timestamp_et==pd.Timestamp("2020-01-03 21:00Z")
    assert row.up_theoretical_exit_timestamp_et==pd.Timestamp("2020-01-04 21:00Z")
    assert row.up_actual_exit_timestamp_et==pd.Timestamp("2020-01-06 14:30Z") and row.up_actual_exit_timestamp_et>=row.up_theoretical_exit_timestamp_et
    assert 0<=row.up_calendar_exit_delay_minutes<=96*60 and row.up_exchange_weekend_at_theoretical_exit and row.up_exit_reason=="NEXT_LEGAL_BAR_AFTER_FROZEN_24H_HORIZON"
    assert str(out.up_exchange_weekend_at_theoretical_exit.dtype)=="boolean"
    assert row.up_entry_price==11 and row.up_exit_price==12 and row.up_action_net_return_10bps==pytest.approx(12/11-1-.001)
def test_entry_ceiling_exit_ceiling_and_invalid_row_retention():
    x=m.assert_candidate_map(candidate())
    late=bars().iloc[[0,2,3]].copy(); out=m._join_action(x,late,"up"); assert not out.up_payoff_valid.iloc[0] and out.up_invalid_reason.iloc[0]=="ENTRY_BAR_UNAVAILABLE"
    assert out.loc[0,[f"up_{field}" for field in m._CALENDAR_FIELDS]].isna().all()
    too_late=bars().iloc[:2].copy(); too_late.loc[len(too_late)]=["TQQQ",pd.Timestamp("2020-01-09 22:00Z"),14,15,13,14.5,1,"x"]; out=m._join_action(x,too_late,"up"); assert not out.up_payoff_valid.iloc[0] and out.up_actual_exit_timestamp_et.isna().all()
    assert out.loc[0,[f"up_{field}" for field in m._CALENDAR_FIELDS]].isna().all()

def test_calendar_exchange_holidays_dst_timezone_nat_nullable_and_hash_stability():
    # UTC and New York inputs describe the same valid local timestamp.
    target=m._utc_datetime_series(["2020-01-07 15:00Z", "2020-01-04 15:00Z", "2020-01-05 15:00Z", "2020-07-03 15:00Z", "2020-11-27 18:00Z", "2020-03-08 14:30Z", "2020-11-01 14:30Z", pd.Timestamp("2020-01-07 10:00", tz="America/New_York"), pd.NaT, None, np.datetime64("NaT", "ns")], pd.RangeIndex(11))
    diagnostics=m._calendar_diagnostics(target, pd.Series([True]*8+[False]*3, dtype=bool))
    assert diagnostics.dtypes.astype(str).eq("boolean").all()
    # Normal Tuesday, Saturday, Sunday, observed NYSE Independence Day closure,
    # and the 13:00 ET early close (not a full closure).
    assert diagnostics.loc[0].tolist()==[False,False,False,True]
    assert diagnostics.loc[1].tolist()==[True,False,True,False]
    assert diagnostics.loc[2].tolist()==[True,False,True,False]
    assert diagnostics.loc[3].tolist()==[False,True,True,False]
    assert diagnostics.loc[4].tolist()==[False,False,False,True]
    # DST conversion is deterministic and the equivalent UTC/New-York inputs
    # receive the same complete classification.
    assert diagnostics.loc[5].tolist()==[True,False,True,False]
    assert diagnostics.loc[6].tolist()==[True,False,True,False]
    assert diagnostics.loc[7].tolist()==diagnostics.loc[0].tolist()
    assert diagnostics.loc[8:].isna().all(axis=None)
    assert json.loads(m.canonical_json(diagnostics.loc[8].to_dict()))[m._CALENDAR_FIELDS[0]] is None
    first=m.stable_hash({field:diagnostics.loc[0,field] for field in m._CALENDAR_FIELDS})
    resumed=m._calendar_diagnostics(target.copy(), pd.Series([True]*8+[False]*3, dtype=bool))
    second=m.stable_hash({field:resumed.loc[0,field] for field in m._CALENDAR_FIELDS})
    assert diagnostics.equals(resumed) and first==second
def test_canonical_hash_index_dtype_order_and_missing_stability(monkeypatch,tmp_path):
    raw=candidate(); raw.index=[42]
    monkeypatch.setattr(m,"legal_bars",lambda _,symbol:(bars(symbol),{"symbol":symbol,"file_count":1,"files":[],"legal_bar_count":4,"rejected_bar_count":0}))
    first,_=m.construct_payoffs(raw,tmp_path); second,_=m.construct_payoffs(raw.copy(),tmp_path)
    assert first.index.equals(pd.RangeIndex(1)) and first.payoff_row_hash.tolist()==second.payoff_row_hash.tolist()
    payload=first.drop(columns="payoff_row_hash").iloc[0].to_dict(); assert json.loads(m.canonical_json(payload))["up_entry_price"]==11
def test_invalid_hash_rejects_nonfinite_and_preserves_nulls(monkeypatch,tmp_path):
    monkeypatch.setattr(m,"legal_bars",lambda _,symbol:(bars(symbol),{"symbol":symbol,"file_count":1,"files":[],"legal_bar_count":4,"rejected_bar_count":0}))
    frame,_=m.construct_payoffs(candidate(),tmp_path); bad=frame.drop(columns="payoff_row_hash").copy(); bad.loc[0,"up_entry_price"]=np.inf
    with pytest.raises(m.R26A2ContractError,match="NONFINITE"): m.payoff_row_hashes(bad)
