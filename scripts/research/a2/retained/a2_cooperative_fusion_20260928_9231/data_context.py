"""Read-only pre-2026 OOF context for the frozen cooperative-fusion experiment.

No model is fitted here. Only this new batch's DATA_READY.json is written by main.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
BASE_ROOT = ROOT.parent / 'a2_top20_multimodel_selection_20260928_9231'
CONTEXT_PATH = ROOT.parent / 'a2_latest_effective_joint_20260927/data/pre2026_joint_context.parquet'
RANK_COLUMNS = ['rank_ridge','rank_elastic_net','rank_logistic','rank_hgb','rank_q50','rank_mlp']
META_COLUMNS = [*RANK_COLUMNS,'q10_downside_rank','current_weight','cash_weight','age_scaled','action']
GATE_COLUMNS = ['current_weight','cash_weight','age_scaled','realized_vol_20d','ret_20d']
STAGES = {'validation': ([2024], '2025-01-01'), 'final': ([2024,2025], '2026-01-01')}
ACTIONS = [0.,.025,.05,.075,.10]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def _read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _stage(stage):
    if stage not in STAGES:
        raise ValueError('STAGE_MUST_BE_VALIDATION_OR_FINAL')
    return STAGES[stage]


def training_sources(stage):
    """Validate and return immutable source bindings before a downstream fit."""
    years, cutoff = _stage(stage)
    paths = [Path(__file__), ROOT/'EXPERIMENT_CONTRACT.md',CONTEXT_PATH,
             BASE_ROOT/'ENSEMBLE_CONTRACT.md']
    expected = {}
    context_hash = sha(CONTEXT_PATH)
    for year in years:
        receipt_path = BASE_ROOT/f'ensemble_artifacts/oof_{year}_RECEIPT.json'
        receipt = _read_json(receipt_path)
        oof_path = BASE_ROOT/f'ensemble_artifacts/oof_{year}.parquet'
        if receipt['year'] != year or receipt['reads_2026_rows'] != 0:
            raise ValueError('OOF_RECEIPT_YEAR_OR_2026_READ_VIOLATION')
        if receipt['base_fit_cutoff_exclusive'] != f'{year}-01-01':
            raise ValueError('OOF_BASE_CUTOFF_VIOLATION')
        if receipt['meta_label_cutoff_exclusive'] != f'{year+1}-01-01':
            raise ValueError('OOF_LABEL_CUTOFF_VIOLATION')
        if receipt['input_sha256'] != context_hash:
            raise ValueError('ORIGINAL_FEATURE_CONTEXT_HASH_CHANGED')
        expected[str(oof_path)] = receipt['oof_sha256']
        expected[str(BASE_ROOT/'ENSEMBLE_CONTRACT.md')] = receipt['ensemble_contract_sha256']
        expected.update(receipt['base_artifact_sha256'])
        paths.extend([receipt_path,oof_path])
    meta_receipt_path = BASE_ROOT/f'ensemble_artifacts/{stage}_TRAIN_RECEIPT.json'
    meta_receipt = _read_json(meta_receipt_path)
    if meta_receipt['cutoff_exclusive'] != cutoff or meta_receipt['oof_years'] != years:
        raise ValueError('OLD_LINEAR_META_STAGE_BOUNDARY_MISMATCH')
    if pd.Timestamp(meta_receipt['label_end_max']) >= pd.Timestamp(cutoff):
        raise ValueError('OLD_LINEAR_META_LABEL_LEAKAGE')
    model_path=BASE_ROOT/f'ensemble_artifacts/{stage}_stacking.joblib'
    expected[str(model_path)]=meta_receipt['artifact_sha256']
    paths.extend([meta_receipt_path,model_path])
    actual = {str(Path(path)):sha(path) for path in dict.fromkeys([*paths,*map(Path,expected)])}
    for path, wanted in expected.items():
        if actual[str(Path(path))] != wanted:
            raise ValueError(f'FROZEN_UPSTREAM_ARTIFACT_CHANGED: {path}')
    return actual


def _finite_array(frame, columns):
    x=frame.loc[:,columns].to_numpy(dtype=np.float64,copy=True)
    if not np.isfinite(x).all():
        raise ValueError('NONFINITE_META_INPUT')
    return x


def meta_features(frame):
    """Return exactly N x 11 in contract order; no learned transform."""
    output=frame.copy(deep=False).assign(age_scaled=np.minimum(frame.age.to_numpy(float),252.)/252.)
    return _finite_array(output,META_COLUMNS)


def gate_features(frame):
    """Return exactly N x 5; same security-state gives the same gate for all actions."""
    output=frame.copy(deep=False).assign(age_scaled=np.minimum(frame.age.to_numpy(float),252.)/252.)
    return _finite_array(output,GATE_COLUMNS)


def load_training(stage):
    """Load only the contract's 2024/2025 OOF, left-join pre-2026 signal features.

    Row order, labels, states/actions and sample counts remain unchanged. The
    full frozen pre-context file is hashed, but parquet rows are date-filtered
    before reading: no test-2026 input or result file is opened by this module.
    """
    years, cutoff = _stage(stage)
    sources = training_sources(stage)
    parts=[]
    for year in years:
        frame=pd.read_parquet(BASE_ROOT/f'ensemble_artifacts/oof_{year}.parquet')
        receipt=_read_json(BASE_ROOT/f'ensemble_artifacts/oof_{year}_RECEIPT.json')
        for column in ['signal_date','label_end_date','base_fit_cutoff']:
            frame[column]=pd.to_datetime(frame[column])
        if len(frame)!=90000 or len(frame)!=receipt['oof_rows']:
            raise ValueError('OOF_ROW_COUNT_CHANGED')
        if not frame.signal_date.dt.year.eq(year).all():
            raise ValueError('OOF_SIGNAL_YEAR_MISMATCH')
        if not (frame.label_end_date.gt(frame.signal_date)&frame.label_end_date.lt(f'{year+1}-01-01')).all():
            raise ValueError('OOF_LABEL_MATURITY_VIOLATION')
        if not (frame.base_fit_cutoff.eq(f'{year}-01-01')&frame.signal_date.ge(frame.base_fit_cutoff)).all():
            raise ValueError('BASE_FIT_NOT_STRICTLY_BEFORE_OOF_OBSERVATION')
        expected_stage='development' if year==2024 else 'validation'
        if not frame.base_stage.eq(expected_stage).all():
            raise ValueError('WRONG_BASE_STAGE')
        if frame.duplicated(['signal_date','ticker','state_id','action']).any():
            raise ValueError('DUPLICATE_OOF_ACTION')
        if len(frame[['signal_date','ticker']].drop_duplicates())!=6000:
            raise ValueError('OOF_BASE_SAMPLE_COUNT_CHANGED')
        if not frame.groupby(['signal_date','ticker','state_id']).action.apply(lambda s:np.array_equal(np.sort(s.to_numpy(float)),ACTIONS)).all():
            raise ValueError('OOF_ACTION_GRID_CHANGED')
        if not frame.groupby(['signal_date','ticker']).state_id.nunique().eq(3).all():
            raise ValueError('OOF_STATE_GRID_CHANGED')
        if frame.signal_date.nunique()!=receipt['sampled_days']:
            raise ValueError('OOF_SAMPLE_DAYS_CHANGED')
        if not frame.loc[frame.action.eq(0),[*RANK_COLUMNS,'q10_downside_rank','target_advantage']].eq(0).all().all():
            raise ValueError('ZERO_ACTION_REFERENCE_CHANGED')
        if not np.isfinite(frame[[*RANK_COLUMNS,'q10_downside_rank','current_weight','cash_weight','age','action','target_advantage']].to_numpy(float)).all():
            raise ValueError('NONFINITE_OOF')
        parts.append(frame)
    frame=pd.concat(parts,ignore_index=True)
    source=pd.read_parquet(CONTEXT_PATH,
        columns=['signal_date','ticker','realized_vol_20d','ret_20d','label_end_date','label_available','new_buy_eligible'],
        filters=[('signal_date','>=',pd.Timestamp('2024-01-01')),('signal_date','<',pd.Timestamp(cutoff))])
    source['signal_date']=pd.to_datetime(source.signal_date)
    source['label_end_date']=pd.to_datetime(source.label_end_date)
    if not source.signal_date.lt(cutoff).all() or source.duplicated(['signal_date','ticker']).any():
        raise ValueError('SOURCE_BOUNDARY_OR_DUPLICATE_VIOLATION')
    source=source.rename(columns={'label_end_date':'source_label_end_date','label_available':'source_label_available','new_buy_eligible':'source_new_buy_eligible'})
    before=len(frame)
    frame=frame.merge(source,on=['signal_date','ticker'],how='left',validate='many_to_one',sort=False,indicator=True)
    if len(frame)!=before or not frame['_merge'].eq('both').all():
        raise ValueError('CONTEXT_JOIN_MISSING_OR_CHANGED_ROWS')
    if not (frame.label_end_date.eq(frame.source_label_end_date)&frame.source_label_available&frame.source_new_buy_eligible).all():
        raise ValueError('SOURCE_LABEL_OR_ELIGIBILITY_MISMATCH')
    frame=frame.drop(columns=['source_label_end_date','source_label_available','source_new_buy_eligible','_merge'])
    if not frame.label_end_date.lt(cutoff).all():
        raise ValueError('META_TRAINING_LABEL_BOUNDARY_VIOLATION')
    meta_features(frame);gate_features(frame)
    frame.attrs['training_sources']=sources
    frame.attrs['stage']=stage
    frame.attrs['cutoff_exclusive']=cutoff
    return frame


def load_linear_baseline(stage):
    """Load the original same-stage six-rank linear stack, never fit it."""
    training_sources(stage)
    model=joblib.load(BASE_ROOT/f'ensemble_artifacts/{stage}_stacking.joblib')
    if model.n_features_in_ != len(RANK_COLUMNS):
        raise ValueError('OLD_LINEAR_META_FEATURE_COUNT_CHANGED')
    return model


def linear_baseline_predict(frame, stage):
    return np.asarray(load_linear_baseline(stage).predict(_finite_array(frame,RANK_COLUMNS)),dtype=np.float64)


def main():
    stages={}
    for stage in STAGES:
        frame=load_training(stage)
        stages[stage]={'rows':len(frame),'signal_years':sorted(map(int,frame.signal_date.dt.year.unique())),
            'signal_first':str(frame.signal_date.min().date()),'signal_last':str(frame.signal_date.max().date()),
            'label_end_max':str(frame.label_end_date.max().date()),'cutoff_exclusive':STAGES[stage][1],
            'base_keys':len(frame[['signal_date','ticker']].drop_duplicates()),
            'meta_feature_shape':list(meta_features(frame).shape),'gate_feature_shape':list(gate_features(frame).shape),
            'upstream_source_sha256':frame.attrs['training_sources']}
    probe=pd.DataFrame({**{name:[0.] for name in RANK_COLUMNS},'q10_downside_rank':[.2],
        'current_weight':[.1],'cash_weight':[.7],'age':[504.],'action':[.05],
        'realized_vol_20d':[.3],'ret_20d':[-.1]})
    assert np.array_equal(meta_features(probe)[0,-4:],[.1,.7,1.,.05])
    assert np.array_equal(gate_features(probe)[0],[.1,.7,1.,.3,-.1])
    try:_stage('test2026')
    except ValueError:pass
    else:raise AssertionError('Invalid stage accepted')
    receipt={'status':'PASS_DATA_BOUNDARIES_AND_SOURCE_BINDINGS_ONLY','created_utc':datetime.now(timezone.utc).isoformat(),
        'stages':stages,'rank_columns':RANK_COLUMNS,'meta_columns':META_COLUMNS,'gate_columns':GATE_COLUMNS,
        'join':'left many_to_one signal_date,ticker; OOF row order and counts unchanged',
        'age_transform':'min(age,252)/252 for both meta and gate',
        'new_fit_calls':0,'model_predict_calls':0,'test2026_rows_read':0,'base_training_calls':0,
        'research_status':'Observed-history cooperative-layer experiment, not a new blind test or repaired-base certification.',
        'inherited_limitations':['Pre2026 static identity and missing-price/121-day selection','Corporate-action and extreme-move feature dependence, without proof of numeric error','Historical supplier arrival and revisions unproven','2026 incomplete candidate subpool','GLW 2026-02-26/27 conflict','Initial 2026Q2 member pool persists for nine signals after restatement activation']}
    (ROOT/'DATA_READY.json').write_text(json.dumps(receipt,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    print(json.dumps({k:{p:v for p,v in s.items() if p!='upstream_source_sha256'} for k,s in stages.items()},indent=2))


if __name__=='__main__':main()
