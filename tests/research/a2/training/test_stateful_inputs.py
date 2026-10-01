"""Synthetic only: no real sources, model fits, or account runs."""
import json,hashlib
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import stateful_inputs as inputs

def test_strict_training_and_calibration_maturity():
 c=pd.Timestamp("2022-10-06");cut=pd.Timestamp("2023-01-01")
 flags=pd.DataFrame({"signal_date":pd.to_datetime(["2022-10-03","2022-10-03","2022-10-06","2022-12-23","2022-10-03"]),"feature_available":[True,True,True,True,False],"label_available":[True]*5,"account_event_unhandled":[False]*5,"label_mature_date":pd.to_datetime(["2022-10-05","2022-10-06","2022-10-14","2023-01-01","2022-10-05"])})
 train,cal=inputs._training_masks(flags,{"calibration_start":c,"cutoff_exclusive":cut,"calibration_sessions":pd.to_datetime(["2022-10-06","2022-12-23"])})
 assert train.tolist()==[True,False,False,False,False]
 assert cal.tolist()==[False,False,True,False,False]

def test_inference_preserves_unlabelled_and_unavailable_keys():
 flags=pd.DataFrame({"signal_date":pd.to_datetime(["2023-01-03"]*2),"ticker":["LEGAL","MISSING"],"feature_available":[True,False]})
 vector=pd.DataFrame({"signal_date":pd.to_datetime(["2023-01-03"]),"ticker":["LEGAL"],"ret_1d":[.01]})
 a=inputs._join_vectors(flags,vector,features=("ret_1d",))
 assert a.ticker.tolist()==["LEGAL","MISSING"] and pd.isna(a.ret_1d.iloc[1])
 # No labels are required or used; changing attached future maturity does not select keys.
 labels=flags.assign(label_available=[False,True],label_mature_date=pd.to_datetime(["2027-01-01","2023-01-05"]))
 b=inputs._join_vectors(labels,vector,features=("ret_1d",))
 assert a[["signal_date","ticker","ret_1d"]].equals(b[["signal_date","ticker","ret_1d"]])

def test_past_window_is_future_append_invariant():
 cal=pd.bdate_range("2022-01-01","2025-12-31");future=pd.bdate_range("2026-01-01","2026-01-30")
 assert inputs._window(cal,"2023-03-03",20).equals(inputs._window(cal.append(future),"2023-03-03",20))
 with pytest.raises(ValueError,match="HISTORY_DECISION"):inputs._window(cal.append(future),"2026-01-05",20)
 assert inputs._fold(cal,2023)["calendar_sha256"]==inputs._fold(cal.append(future),2023)["calendar_sha256"]

def test_source_hash_failure_precedes_any_table_read(tmp_path,monkeypatch):
 run=tmp_path/"run";run.mkdir();(run/"input_manifest.json").write_text(json.dumps({"run_id":"SYNTHETIC"}))
 source=tmp_path/"bad-source";source.write_bytes(b"SYNTHETIC")
 monkeypatch.setattr(inputs,"resolve",lambda repo:SimpleNamespace(backtest_root=tmp_path))
 monkeypatch.setattr(inputs,"SOURCES",{"calendar":{"path":str(source),"sha256":"0"*64,"date":"trade_date","rows":1}})
 reads=[]
 monkeypatch.setattr(inputs.pq,"read_table",lambda *a,**k:reads.append(True))
 with pytest.raises(ValueError,match="SOURCE_HASH_MISMATCH"):inputs.prepare_inputs(run)
 assert not reads

def test_early_packet_and_missing_vector_fail_closed():
 cal=pd.bdate_range("2020-01-02","2025-12-31")
 assert inputs._fold(cal,2021)["packet_role"]=="INTERNAL_PACKET_OOF"
 assert inputs._fold(cal,2022)["packet_role"]=="INTERNAL_PACKET_OOF"
 assert inputs._fold(cal,2023)["packet_role"]=="OUTER_EVALUATION_OOF"
 flags=pd.DataFrame({"signal_date":pd.to_datetime(["2023-01-03"]),"ticker":["LEGAL"],"feature_available":[True]})
 empty=pd.DataFrame({"signal_date":pd.to_datetime([]),"ticker":[],"ret_1d":[]})
 with pytest.raises(ValueError,match="LEGAL_VECTOR_KEYS_NOT_COMPLETE"):inputs._join_vectors(flags,empty,features=("ret_1d",))

def test_short_clock_sequence_is_fixed20_and_unobserved_left_pad():
 reader=object.__new__(inputs.InputReader);reader.calendar=pd.bdate_range("2020-01-02",periods=3)
 reader.pred_flags=pd.DataFrame({"signal_date":reader.calendar,"ticker":["A"]*3,"feature_available":[True]*3})
 vectors=reader.pred_flags[["signal_date","ticker"]].copy()
 for name in inputs.FEATURES:vectors[name]=1.
 reader._vectors=lambda *args,**kwargs:vectors
 result=reader.sequence_window(["A"],reader.calendar[-1])
 assert result["features"].shape==(1,20,32) and result["left_pad_sessions"]==17 and not result["window_complete"]
 assert not result["step_available"][0,:17].any() and not result["cell_observed"][0,:17].any()
 assert np.isnan(result["features"][0,:17]).all()
