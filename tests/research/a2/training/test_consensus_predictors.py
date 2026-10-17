"""Synthetic lifecycle and cutoff tests; no real market/label/pool payload reads."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import consensus_predictors as owner
from scripts.research.a2.data.consensus_training_inputs import annual_fold


class SyntheticReader:
    def __init__(self,run):
        self.calendar=pd.bdate_range('2020-01-01','2025-12-31')
        self.records={};self.membership_sha256=owner.values.sha(run/'derived/consensus100_daily.parquet')
        self.reads=0

    def annual_fold(self,year):return annual_fold(self.calendar,year)

    def frame(self,dates,horizon=5):
        n=len(dates);z=np.arange(n,dtype=float)-n/2+3*int(pd.Timestamp(dates[0]).month>=10)
        f=pd.DataFrame(dict(signal_date=dates,ticker='SYN',cusip='000000001',
            label_mature_date=pd.to_datetime(dates)+pd.Timedelta(days=1),
            feature_available=True,label_available=True,account_event_unhandled=False,
            feature_source='FROZEN_RAW_A2_TRAINING_MATRIX_32',label_coordinate=owner.values.LABEL))
        for k,name in enumerate(owner.FEATURES):f[name]=z+(k+1)*.01
        f['y_open5']=.02*z+np.where(np.arange(n)%2,.01,-.01)
        f['target']=f.y_open5 if horizon==5 else .05*z+.3
        if horizon!=5:f['target_end_date_'+str(horizon)+'d']=f.signal_date+pd.Timedelta(days=1)
        return f

    def read_training_fold(self,year,horizon=5):
        self.reads+=1;fold=self.annual_fold(year)
        start=max(pd.Timestamp('2020-01-02'),pd.Timestamp(f'{year-1}-01-02'))
        train_dates=self.calendar[self.calendar>=start][:12]
        return self.frame(train_dates,horizon),self.frame(fold['calibration_sessions'][:12],horizon)

    def prediction_keys(self,year):
        dates=self.calendar[self.calendar>=pd.Timestamp(f'{year}-01-01')][:6]
        return pd.DataFrame(dict(signal_date=[*dates,dates[0]],ticker=['SYN']*6+['MISSING'],feature_available=[True]*6+[False]))

    def read_prediction_year(self,year):
        keys=self.prediction_keys(year).iloc[:6]
        return self.frame(keys.signal_date.tolist()).drop(columns=['target','y_open5'])


@pytest.fixture
def setup(tmp_path,monkeypatch):
    # Only authority/config source text is reused; every vector and target is synthetic.
    spec=json.loads(owner.spec_path().read_text(encoding='utf-8'))
    sp=tmp_path/'synthetic_spec.json';sp.write_text(json.dumps(spec),encoding='utf-8')
    run=tmp_path/'run';(run/'derived').mkdir(parents=True)
    (run/'derived/PHYSICAL_SOURCE_BINDING.json').write_text('{}',encoding='utf-8')
    (run/'derived/consensus100_daily.parquet').write_bytes(b'SYNTHETIC_IDENTITY_ONLY')
    monkeypatch.setattr(owner,'spec_path',lambda:sp)
    monkeypatch.setattr(owner,'assert_safe_output_path',lambda *a,**k:None)
    monkeypatch.setattr(owner.values,'assert_write_path',lambda *a,**k:None)
    def write(path,obj):Path(path).parent.mkdir(parents=True,exist_ok=True);Path(path).write_text(json.dumps(obj,allow_nan=False),encoding='utf-8')
    monkeypatch.setattr(owner,'write_json_atomic',write);monkeypatch.setattr(owner.values,'write_json_atomic',write)
    frozen=owner.freeze_template(run);frozen['status']='AUTHORIZED_PRE2026_TRAINING_ONLY'
    write(run/'CONSENSUS_PREDICTOR_FREEZE.json',frozen)
    return run,SyntheticReader(run),frozen


def events(run):
    p=run/'FIT_LOG.jsonl'
    return [json.loads(line) for line in p.read_text(encoding='utf-8').splitlines()] if p.exists() else []


def test_exact_schedule_and_explicit_svm_alias(setup):
    _,_,f=setup;s=f['ordered_slots']
    assert len(s)==228 and len({(x['model_id'],x['year'],x['horizon']) for x in s})==228
    assert sum(x['horizon']==5 for x in s)==174
    assert {x['model_id'] for x in s if x['horizon']!=5}=={'ridge','hgb','xgb'}
    assert owner.ALIAS=={'rbf_svm':'svc'}


def test_frame_hash_binds_secondary_target_and_clock(setup):
    _,r,_=setup;f=r.read_training_fold(2021,3)[0]
    assert owner.frame_hash(f)!=owner.frame_hash(f.assign(target=f.target+.01))
    assert owner.frame_hash(f)!=owner.frame_hash(f.assign(target_end_date_3d=f.target_end_date_3d+pd.Timedelta(days=1)))


def test_final_cutoff_has_independent_gate_and_no_test_prediction(setup):
    run,r,_=setup
    with pytest.raises(ValueError,match='FINAL_CUTOFF_NEEDS_ROOT_GATE'):owner.fit_one(run,'ridge',2026,5,r)
    with pytest.raises(ValueError,match='2026_PREDICTION_REQUIRES'):owner.predict_one(run,'ridge',2026,5,r)
    assert r.reads==0


def test_train_only_scaler_calibration_and_exact_checkpoint_reuse(setup):
    run,r,_=setup;f=owner.fit_one(run,'ridge',2021,5,r)
    assert isinstance(f,owner.ConsensusPredictor)
    fold,train,cal=owner.guarded_frames(r,2021,5)
    np.testing.assert_allclose(f.native.scaler.mean_,train[list(owner.FEATURES)].mean().to_numpy())
    assert not np.allclose(f.native.scaler.mean_,pd.concat([train,cal])[list(owner.FEATURES)].mean().to_numpy())
    raw=owner.raw_predict(f.native,'ridge',cal,r)
    assert f.calibration['sigma']==pytest.approx(np.std(cal.target.to_numpy()-raw,ddof=1))
    starts=[e for e in events(run) if e['event']=='FIT_STARTED'];assert len(starts)==3
    again=owner.fit_one(run,'ridge',2021,5,r)
    assert again.receipt['model_sha256']==f.receipt['model_sha256']
    assert len([e for e in events(run) if e['event']=='FIT_STARTED'])==3


def test_secondary_ols_bridge_uses_past_y_open5_and_counts_statistics(setup):
    run,r,_=setup;f=owner.fit_one(run,'ridge',2021,3,r)
    assert isinstance(f,owner.ConsensusPredictor) and f.bridge['input_horizon']==3 and f.bridge['output_horizon']==5
    _,_,cal=owner.guarded_frames(r,2021,3);raw=owner.raw_predict(f.native,'ridge',cal,r)
    coef=np.linalg.lstsq(np.column_stack([np.ones(len(cal)),raw]),cal.y_open5.to_numpy(),rcond=None)[0]
    assert f.bridge['intercept']==pytest.approx(coef[0]);assert f.bridge['slope']==pytest.approx(coef[1])
    components=[e['component'] for e in events(run) if e['event']=='FIT_STARTED']
    assert components==['SCALER','PREDICTOR','HELDOUT_OLS_BRIDGE_TO_PRIMARY5D','HELDOUT_BRIDGE_RESIDUAL_SIGMA']
    assert f.receipt['fit_units']==4


def test_failed_slot_is_never_overwritten_or_scientifically_retried(setup,monkeypatch):
    run,r,_=setup
    monkeypatch.setattr(owner.values,'_fit_job',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('SYNTHETIC_FAILURE')))
    failed=owner.fit_one(run,'ridge',2021,5,r);assert failed['status']=='FAILED'
    receipt=Path(failed['receipt_path']);before=receipt.read_bytes()
    monkeypatch.setattr(r,'read_training_fold',lambda *a,**k:pytest.fail('failed slot re-read for retry'))
    assert owner.fit_one(run,'ridge',2021,5,r)['status']=='FAILED' and receipt.read_bytes()==before


def test_budget_exhaustion_blocks_before_physical_fit(setup):
    run,r,_=setup
    (run/'FIT_LOG.jsonl').write_text(json.dumps(dict(event='FIT_STARTED',fit_units=10000))+'\n',encoding='utf-8')
    f=owner.fit_one(run,'ridge',2021,5,r)
    assert f['status']=='FAILED' and 'BUDGET_EXHAUSTED' in f['failure']['message'] and f['fit_units']==0


def test_predict_preserves_unavailable_keys_and_checkpoint_hashes(setup):
    run,r,_=setup;result=owner.predict_one(run,'ridge',2021,5,r)
    assert result['status']=='PUBLISHED' and result['rows']==7 and result['unavailable_rows']==1
    out=pd.read_parquet(result['path']);missing=out.loc[out.ticker.eq('MISSING')].iloc[0]
    assert not missing.prediction_qualified and pd.isna(missing.prediction)
    before=len(events(run));assert owner.predict_one(run,'ridge',2021,5,r)==result;assert len(events(run))==before
    Path(result['path']).write_bytes(Path(result['path']).read_bytes()+b'changed')
    with pytest.raises(ValueError,match='PREDICTION_CHECKPOINT_CHANGED'):owner.predict_one(run,'ridge',2021,5,r)


def test_completed_model_bytes_must_match_before_reuse(setup):
    run,r,_=setup;f=owner.fit_one(run,'ridge',2021,5,r)
    path=Path(f.receipt['model_path']);path.write_bytes(path.read_bytes()+b'changed')
    with pytest.raises(ValueError,match='COMPLETED_CHECKPOINT_BYTES_CHANGED'):owner.fit_one(run,'ridge',2021,5,r)


def test_secondary_cartesian_expansion_and_source_change_are_rejected(setup,monkeypatch):
    run,r,f=setup
    with pytest.raises(ValueError,match='UNPLANNED_METHOD'):owner.fit_one(run,'rf',2021,3,r)
    monkeypatch.setattr(owner,'source_pins',lambda:{})
    with pytest.raises(ValueError,match='FROZEN_PREDICTOR_SOURCE_CHANGED'):owner.fit_one(run,'ridge',2021,5,r)


def test_illegal_training_maturity_is_not_silently_filtered(setup,monkeypatch):
    _,r,_=setup;original=r.read_training_fold
    def bad(year,horizon):
        train,cal=original(year,horizon);train.loc[0,'label_mature_date']=pd.Timestamp('2026-01-02');return train,cal
    monkeypatch.setattr(r,'read_training_fold',bad)
    with pytest.raises(ValueError,match='UNQUALIFIED_OR_UNORDERED'):owner.guarded_frames(r,2021,5)


def test_final_source_guard_proves_every_physical_clock_before_payload(setup,tmp_path,monkeypatch):
    import pyarrow.parquet as pq
    run,r,f=setup;p=tmp_path/'synthetic_mixed_clock.parquet'
    pd.DataFrame(dict(signal_date=pd.to_datetime(['2025-12-01']),
        label_mature_date=pd.to_datetime(['2026-01-02']),x=[99])).to_parquet(p,index=False)
    st=p.stat();r.records={'synthetic':dict(path=str(p),sha256=owner.values.sha(p),rows=1,
        schema=pq.ParquetFile(p).schema_arrow.names,date_bounds={'signal_date':[], 'label_mature_date':[]},
        file_fingerprint=dict(size=st.st_size,mtime_ns=st.st_mtime_ns))}
    monkeypatch.setattr(pq,'read_table',lambda *a,**k:pytest.fail('mixed clock payload opened'))
    with pytest.raises(ValueError,match='Forbidden mixed/test input'):owner.reader_integrity(r,f)
