from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from fast3.economics import executable_payoff_ledger_hard_r26a as m

def candidates():
    return pd.DataFrame({"candidate_id":["a","b"],"candidate_instrument":["QQQ","SOXS"],"decision_timestamp_et":pd.to_datetime(["2020-01-01 14:00Z","2020-01-01 14:05Z"]),"authoritative_anchor_timestamp_et":pd.to_datetime(["2020-01-01 14:00Z","2020-01-01 14:05Z"])})
def bars(symbol):
    t=pd.date_range("2020-01-01 13:59Z", periods=24*60+30, freq="min")
    return pd.DataFrame({"symbol":symbol,"timestamp_et":t,"open":np.arange(len(t),dtype=float)+10,"high":np.arange(len(t),dtype=float)+11,"low":np.arange(len(t),dtype=float)+9,"close":np.arange(len(t),dtype=float)+10.5,"volume":1.0,"bar_hash":[str(i) for i in range(len(t))]})
def test_six_symbol_mapping_and_unknown_rejection():
    out=m.assert_candidate_map(candidates()); assert out.up_action_instrument.tolist()==["TQQQ","SOXS"] and out.down_action_instrument.tolist()==["SQQQ","SOXL"]
    with pytest.raises(m.R26AContractError,match="MAPPING_UNRESOLVED"): m.assert_candidate_map(candidates().assign(candidate_instrument="SPY"))
def test_strict_entry_fixed_exit_open_costs_and_invalid_retention():
    x=m.assert_candidate_map(candidates().iloc[:1]); out=m._join_action(x,bars("TQQQ"),"up")
    r=out.iloc[0]; assert r.up_entry_timestamp_et == pd.Timestamp("2020-01-01 14:01Z") and r.up_exit_timestamp_et == pd.Timestamp("2020-01-02 14:00Z")
    assert r.up_entry_delay_minutes==1 and r.up_exit_delay_minutes==0 and r.up_exit_reason=="FIXED_FROZEN_HORIZON"
    assert np.isclose(r.up_action_net_return_10bps,r.up_exit_price/r.up_entry_price-1-.001) and r.up_action_mfe not in (None,np.nan)
    bad=m._join_action(x,bars("TQQQ").iloc[:5],"up"); assert len(bad)==1 and not bad.iloc[0].up_payoff_valid and bad.iloc[0].up_invalid_reason=="EXIT_BAR_UNAVAILABLE"
def test_hashes_and_cardinality_are_deterministic():
    assert m.stable_hash({"b":1,"a":2})==m.stable_hash({"a":2,"b":1})
    f=pd.DataFrame({"candidate_id":["a","a"],"up_payoff_valid":[True,True],"down_payoff_valid":[True,True],"up_entry_price":[1.,1.],"up_exit_price":[2.,2.],"down_entry_price":[1.,1.],"down_exit_price":[2.,2.],"up_action_net_return_5bps":[.9995,.9995],"up_action_net_return_10bps":[.999,.999],"up_action_net_return_20bps":[.998,.998],"down_action_net_return_5bps":[.9995,.9995],"down_action_net_return_10bps":[.999,.999],"down_action_net_return_20bps":[.998,.998]})
    a=m.payoff_audit(f,pd.Series(["a","b"])); assert a["duplicate_candidate_count"]==1 and a["missing_candidate_count"]==1 and a["unexpected_candidate_count"]==0

def test_path_extrema_normal_multi_bar_interval_is_inclusive():
    values=np.array([11., 14., 13.])
    assert m._range_extreme(values,np.array([0]),np.array([2]),True).tolist()==[14.]
    assert m._range_extreme(values,np.array([0]),np.array([2]),False).tolist()==[11.]

def test_path_extrema_single_bar_and_empty_interval_are_deterministic():
    values=np.array([11.])
    assert m._range_extreme(values,np.array([0]),np.array([0]),True).tolist()==[11.]
    assert m._range_extreme(values,np.array([0]),np.array([0]),False).tolist()==[11.]
    assert np.isnan(m._range_extreme(values,np.array([1]),np.array([0]),True)[0])
    assert np.isnan(m._range_extreme(values,np.array([1]),np.array([0]),False)[0])

def test_noncontinuous_index_and_same_timestamp_candidates_do_not_expand_extrema_arrays():
    x=candidates().iloc[[1,0]].copy()
    x.index=[9,41]
    x["candidate_instrument"]="QQQ"
    x["authoritative_anchor_timestamp_et"]=pd.Timestamp("2020-01-01 14:00Z")
    out=m._join_action(m.assert_candidate_map(x),bars("TQQQ"),"up")
    assert out.candidate_id.tolist()==["a","b"] and len(out)==2
    assert out.index.equals(pd.RangeIndex(2))
    assert out[["up_action_mfe","up_action_mae"]].notna().all().all()

def test_entry_and_exit_missing_keep_candidate_and_null_extrema():
    x=m.assert_candidate_map(candidates().iloc[:1])
    no_exit=m._join_action(x,bars("TQQQ").iloc[:5],"up")
    no_entry=m._join_action(x.assign(authoritative_anchor_timestamp_et=pd.Timestamp("2020-01-03 14:00Z")),bars("TQQQ").iloc[:5],"up")
    for frame,reason in ((no_exit,"EXIT_BAR_UNAVAILABLE"),(no_entry,"ENTRY_BAR_UNAVAILABLE")):
        assert len(frame)==1 and not frame.iloc[0].up_payoff_valid and frame.iloc[0].up_invalid_reason==reason
        assert frame[["up_action_mfe","up_action_mae"]].isna().all().all()

def test_cross_action_partitions_have_one_up_and_down_extrema_per_candidate(monkeypatch,tmp_path):
    raw=candidates().copy(); raw.index=[17,3]
    def fake_legal_bars(_,symbol): return bars(symbol),{"symbol":symbol,"file_count":1,"files":[],"legal_bar_count":1470,"rejected_bar_count":0}
    monkeypatch.setattr(m,"legal_bars",fake_legal_bars)
    out,_=m.construct_payoffs(raw,tmp_path)
    assert out.candidate_id.tolist()==["a","b"] and len(out)==2
    assert out.up_action_instrument.tolist()!=out.down_action_instrument.tolist()
    assert out[["up_action_mfe","up_action_mae","down_action_mfe","down_action_mae"]].notna().all().all()

def test_construct_payoffs_resume_is_order_and_hash_stable(monkeypatch,tmp_path):
    raw=candidates().iloc[[1,0]].copy(); raw.index=[101,5]
    def fake_legal_bars(_,symbol): return bars(symbol),{"symbol":symbol,"file_count":1,"files":[],"legal_bar_count":1470,"rejected_bar_count":0}
    monkeypatch.setattr(m,"legal_bars",fake_legal_bars)
    first,_=m.construct_payoffs(raw,tmp_path)
    resumed,_=m.construct_payoffs(raw,tmp_path)
    pd.testing.assert_frame_equal(first,resumed,check_exact=True,check_dtype=True)
    assert first.candidate_id.tolist()==["a","b"] and first.payoff_row_hash.tolist()==resumed.payoff_row_hash.tolist()

def test_canonical_json_normalizes_missing_numpy_scalars_timestamp_path_and_nested_values():
    value={"nan":np.nan,"na":pd.NA,"nat":pd.NaT,"integer":np.int64(7),"float":np.float32(1.5),"bool":np.bool_(True),"timestamp":pd.Timestamp("2020-01-01 14:00:00+00:00"),"path":Path("a") / "b","nested":({"missing":np.nan},)}
    encoded=m.canonical_json(value); decoded=json.loads(encoded)
    assert decoded["nan"] is None and decoded["na"] is None and decoded["nat"] is None
    assert decoded["integer"]==7 and decoded["float"]==1.5 and decoded["bool"] is True
    assert decoded["timestamp"]=="2020-01-01T14:00:00.000000000+00:00" and decoded["path"]=="a/b"
    assert decoded["nested"]==[{"missing":None}] and "NaN" not in encoded

def _construct_with_bars(monkeypatch,tmp_path,bar_frame):
    monkeypatch.setattr(m,"legal_bars",lambda _,symbol:(bar_frame(symbol),{"symbol":symbol,"file_count":1,"files":[],"legal_bar_count":len(bar_frame(symbol)),"rejected_bar_count":0}))
    return m.construct_payoffs(candidates(),tmp_path)[0]

def test_invalid_payoff_row_hash_serializes_unavailable_fields_as_null(monkeypatch,tmp_path):
    frame=_construct_with_bars(monkeypatch,tmp_path,lambda symbol:bars(symbol).iloc[:5])
    assert (~frame.up_payoff_valid).all() and frame.up_invalid_reason.notna().all()
    payload=m.payoff_row_payload(frame.drop(columns="payoff_row_hash").iloc[0].to_dict())
    encoded=m.canonical_json(payload)
    assert json.loads(encoded)["up_entry_price"] is None and json.loads(encoded)["up_action_mfe"] is None
    assert "NaN" not in encoded and frame.payoff_row_hash.notna().all()

@pytest.mark.parametrize("field,bad",[("up_entry_price",np.nan),("up_action_gross_return",np.inf),("up_action_net_return_20bps",-np.inf)])
def test_valid_payoff_row_nonfinite_values_fail_closed(monkeypatch,tmp_path,field,bad):
    frame=_construct_with_bars(monkeypatch,tmp_path,bars).drop(columns="payoff_row_hash")
    frame.loc[0,field]=bad
    with pytest.raises(m.R26AContractError,match="VALID_PAYOFF_NONFINITE"):
        m.payoff_row_hashes(frame)

def test_equivalent_scalar_and_missing_representations_have_identical_payoff_hash(monkeypatch,tmp_path):
    valid=_construct_with_bars(monkeypatch,tmp_path,bars).drop(columns="payoff_row_hash").iloc[0].to_dict()
    numpy_scalars=valid.copy(); numpy_scalars["polarity"]=np.int64(valid["polarity"]); numpy_scalars["frozen_horizon_hours"]=np.int64(24); numpy_scalars["up_entry_price"]=np.float64(valid["up_entry_price"]); numpy_scalars["up_payoff_valid"]=np.bool_(True)
    assert m.stable_hash(m.payoff_row_payload(valid))==m.stable_hash(m.payoff_row_payload(numpy_scalars))
    invalid=_construct_with_bars(monkeypatch,tmp_path,lambda symbol:bars(symbol).iloc[:5]).drop(columns="payoff_row_hash").iloc[0].to_dict()
    alternate=invalid.copy(); alternate["up_entry_price"]=pd.NA; alternate["up_entry_timestamp_et"]=np.datetime64("NaT","ns")
    assert m.stable_hash(m.payoff_row_payload(invalid))==m.stable_hash(m.payoff_row_payload(alternate))
