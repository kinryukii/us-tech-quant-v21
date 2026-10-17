import pandas as pd
import pytest
from scripts.research.a2.data.consensus_training_inputs import annual_fold, mature_keys

def test_final_fit_key_cannot_consume_2026_sessions():
    c=pd.bdate_range("2020-01-01", "2025-12-31")
    f=annual_fold(c,2026)
    assert f["cutoff_exclusive"]==pd.Timestamp("2026-01-01")
    assert f["calibration_sessions"].max()<f["cutoff_exclusive"]
    with pytest.raises(ValueError):annual_fold(c,2027)

def test_metadata_maturity_excludes_future_target_and_keeps_calibration_separate():
    fold={"calibration_start":pd.Timestamp("2024-10-01"),"cutoff_exclusive":pd.Timestamp("2025-01-01"),"calibration_sessions":pd.DatetimeIndex(["2024-12-10"])}
    x=pd.DataFrame({"signal_date":["2024-09-20","2024-09-20","2024-12-10","2026-01-05"],"ticker":["A","B","A","A"],"feature_available":True,"label_available":True,"account_event_unhandled":False,"feature_source":"FROZEN_RAW_A2_TRAINING_MATRIX_32","label_mature_date":["2024-09-27","2024-10-01","2024-12-18","2026-01-10"],"target_end_date_20d":["2024-10-18","2024-10-18","2025-01-09","2026-02-03"]})
    assert mature_keys(x,fold,"train",5).ticker.tolist()==["A"]
    assert len(mature_keys(x,fold,"calibration",5))==1
    assert mature_keys(x,fold,"train",20).empty
    assert mature_keys(x,fold,"calibration",20).empty

def test_labels_do_not_qualify_missing_or_unhandled_features():
    fold={"calibration_start":pd.Timestamp("2024-10-01"),"cutoff_exclusive":pd.Timestamp("2025-01-01"),"calibration_sessions":pd.DatetimeIndex([])}
    x=pd.DataFrame({"signal_date":["2024-09-20"]*3,"ticker":["A","B","C"],"feature_available":[False,True,True],"label_available":True,"account_event_unhandled":[False,True,False],"feature_source":["FROZEN_RAW_A2_TRAINING_MATRIX_32","FROZEN_RAW_A2_TRAINING_MATRIX_32","unqualified"],"label_mature_date":"2024-09-27"})
    assert mature_keys(x,fold,"train",5).empty


def test_clock_predicates_are_applied_before_any_primary_projection(tmp_path, monkeypatch):
    from scripts.research.a2.data import consensus_training_inputs as module
    p=tmp_path/"metadata_fixture.parquet";p.write_bytes(b"synthetic")
    st=p.stat();reader=module.ConsensusInputs.__new__(module.ConsensusInputs)
    reader.records={"value_training_panel":{"path":str(p),"file_fingerprint":{"size":st.st_size,"mtime_ns":st.st_mtime_ns}}}
    observed={}
    class Table:
        def to_pandas(self):return pd.DataFrame()
    def scan(path, *, columns, filters):
        observed.update(columns=columns,filters=filters);return Table()
    monkeypatch.setattr(module.pq,"read_table",scan)
    reader._vectors("value_training_panel",["signal_date","label_mature_date"],[])
    assert ("signal_date","<",pd.Timestamp("2026-01-01")) in observed["filters"]
    assert ("label_mature_date","<",pd.Timestamp("2026-01-01")) in observed["filters"]


def test_authoritative_past_feature_producer_is_prefix_invariant():
    import numpy as np
    from pathlib import Path
    from scripts.research.a2.data.joint_input_binding import existing_feature_functions, FEATURES
    owner=Path(__file__).resolve().parents[4]/"scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py"
    f=existing_feature_functions(owner)
    c=pd.bdate_range("2024-01-01",periods=160)
    x=pd.DataFrame({"ticker":"A","trade_date":c,"close":100*np.exp(np.arange(160)*.001),"volume":np.arange(160)+1000.})
    past=f(x.iloc[:140]);future=x.copy();future.loc[140:,"close"]=1e9;future.loc[140:,"volume"]=1e12
    extended=f(future)
    pd.testing.assert_frame_equal(past[["trade_date",*FEATURES]].reset_index(drop=True),extended.loc[extended.trade_date<=c[139],["trade_date",*FEATURES]].reset_index(drop=True))


def test_exact_qualified_keys_exclude_other_dates_before_value_projection(tmp_path):
    import numpy as np
    from scripts.research.a2.data import consensus_training_inputs as module
    p=tmp_path/"synthetic.parquet"
    dates=pd.to_datetime(["2024-09-01", "2024-09-02", "2024-09-01", "2024-09-02"])
    values=pd.DataFrame({"signal_date":dates,"ticker":["A","A","B","B"],
        "label_mature_date":pd.Timestamp("2024-09-10"),"y":[1.,np.inf,np.inf,2.]})
    values.to_parquet(p,index=False);st=p.stat()
    reader=module.ConsensusInputs.__new__(module.ConsensusInputs)
    reader.records={"value_training_panel":{"path":str(p),"file_fingerprint":{"size":st.st_size,"mtime_ns":st.st_mtime_ns}}}
    keys=values.iloc[[0,3]][["signal_date","ticker"]]
    got=reader._vectors("value_training_panel",["signal_date","ticker","y"],module.exact_key_filters(keys,"ticker"))
    assert got.y.tolist()==[1.,2.]
    with pytest.raises(ValueError,match="EMPTY_EXACT_KEYS"):module.exact_key_filters(keys.iloc[:0],"ticker")


def test_train_secondary_and_prediction_each_scan_only_prior_qualified_keys(monkeypatch):
    from scripts.research.a2.data import consensus_training_inputs as module
    reader=module.ConsensusInputs.__new__(module.ConsensusInputs)
    fold={"calibration_start":pd.Timestamp("2024-10-01"),"cutoff_exclusive":pd.Timestamp("2025-01-01"),"calibration_sessions":pd.DatetimeIndex(["2024-12-10"])}
    reader.annual_fold=lambda year:fold
    dates=pd.to_datetime(["2024-09-20", "2024-09-21", "2024-12-10", "2024-12-10"])
    flags=pd.DataFrame({"signal_date":dates,"ticker":["A","B","A","B"],"cusip":["AAA","BBB","AAA","BBB"],
        "feature_available":True,"label_available":True,"account_event_unhandled":False,
        "feature_source":"FROZEN_RAW_A2_TRAINING_MATRIX_32","label_mature_date":pd.to_datetime(["2024-09-27","2024-09-28","2024-12-18","2024-12-18"]),
        "target_end_date_3d":pd.to_datetime(["2024-09-25","2024-09-26","2024-12-15","2024-12-15"])})
    reader.train_flags=flags;calls=[]
    def scan(name,cols,filters):
        assert filters and all(isinstance(branch,list) for branch in filters)
        calls.append((name,filters));rows=[]
        for branch in filters:
            entity=branch[0][2]
            for date in branch[1][2]:
                row={"signal_date":date,"ticker":entity,"y_open5":.01,**{f:1. for f in module.FEATURES}}
                if name=="multi_horizon_labels":row.update(security_uid=entity,ER_3D=.02)
                rows.append(row)
        return pd.DataFrame(rows)[cols]
    reader._vectors=scan
    train,cal=reader.read_training_fold(2025,3)
    assert len(train)==len(cal)==2
    for name,filters in calls:
        for branch in filters:
            entity,dates_allowed=branch[0][2],branch[1][2]
            if entity in ("A","CUSIP:AAA"):assert pd.Timestamp("2024-09-21") not in dates_allowed
            if entity in ("B","CUSIP:BBB"):assert pd.Timestamp("2024-09-20") not in dates_allowed
    reader.prediction_keys=lambda year:flags.iloc[[1,2]][["signal_date","ticker","feature_available","feature_source"]]
    pred=reader.read_prediction_year(2024)
    assert len(pred)==2
    assert calls[-1][1][0][1][2]==[pd.Timestamp("2024-12-10")]
