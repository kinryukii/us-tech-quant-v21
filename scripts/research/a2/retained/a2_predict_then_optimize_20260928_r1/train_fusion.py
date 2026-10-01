from __future__ import annotations
from common import *
import argparse, time, warnings
import pandas as pd
import joblib
from threadpoolctl import threadpool_limits
from fusion_models import Fusion, state_features

def native_path(stage,provider):
    return ROOT/'predictions/native'/stage/(provider+'.parquet')

def load_native(stage,panel,providers=None):
    tables=[]
    for p in (PROVIDERS if providers is None else providers):
        t=pd.read_parquet(native_path(stage,p))
        assert not t.duplicated(['signal_date','ticker']).any()
        t=t.set_index(['signal_date','ticker']).reindex(pd.MultiIndex.from_frame(panel[['signal_date','ticker']]))
        assert np.isfinite(t[['mu','sigma']].to_numpy(float)).all(),p
        tables.append(t)
    return np.column_stack([t.mu.to_numpy() for t in tables]),np.column_stack([t.sigma.to_numpy() for t in tables])

def training_rows(panel,maximum=20000):
    return _sample(panel,maximum)

def _sample(panel,maximum=20000):
    # All OOF dates represented, keys independent of predictions and outcomes.
    f=panel.copy();f['_hash']=[hashlib.sha256(f'20260928|{d.date()}|{t}'.encode()).hexdigest() for d,t in zip(f.signal_date,f.ticker)]
    f=f.sort_values(['signal_date','_hash','ticker'],kind='stable')
    f['_rank']=f.groupby('signal_date').cumcount()
    f=f.sort_values(['_rank','signal_date','_hash'],kind='stable').head(maximum).sort_values(['signal_date','ticker'],kind='stable')
    assert f.signal_date.nunique()==panel.signal_date.nunique()
    return f.drop(columns=['_hash','_rank'])

def main():
    if not (ROOT/'DESIGN_LOCK.json').exists(): raise RuntimeError('UNLOCKED_DESIGN')
    p=argparse.ArgumentParser();p.add_argument('--predict-year',type=int);p.add_argument('--resume',action='store_true')
    p.add_argument('--groups');p.add_argument('--providers');a=p.parse_args()
    groups=COALITIONS if not a.groups else {g:COALITIONS[g] for g in a.groups.split(',')}
    providers=PROVIDERS if not a.groups else [p for p in PROVIDERS if any(p in m for m in groups.values())]
    if a.predict_year is not None:return predict_year(a.predict_year,provider_subset=a.providers.split(',') if a.providers else None)
    if (ROOT/'GLOBAL_FREEZE.json').exists():raise RuntimeError('LEARNING_FORBIDDEN_AFTER_GLOBAL_FREEZE')
    contract=read(ROOT/'contract.json');assert sha(ROOT/'contract.json')==read(ROOT/'DESIGN_LOCK.json')['contract_sha256']
    panel=pd.read_parquet(ROOT/'input/pre2026.parquet')
    keys=['signal_date','ticker']
    blocks=[]
    for stage,year in [('early',2024),('validation',2025)]:
        f=panel.loc[panel.signal_date.dt.year.eq(year)].sort_values(keys).reset_index(drop=True)
        xx,ss=load_native(stage,f,providers)
        for i,name in enumerate(providers):f['mu__'+name]=xx[:,i];f['sigma__'+name]=ss[:,i]
        f['base_fit_cutoff']=contract['stages'][stage];blocks.append(f)
    oof=pd.concat(blocks,ignore_index=True)
    assert (pd.to_datetime(oof.base_fit_cutoff)<=oof.signal_date).all()
    oof_path=ROOT/'predictions'/('FUSION_OOF.parquet' if not a.groups else 'FUSION_OOF_PART_'+hashlib.sha256(a.groups.encode()).hexdigest()[:12]+'.parquet')
    if not oof_path.exists():oof.to_parquet(oof_path,index=False)
    logs=[]
    for stage,cutoff in [('validation','2025-01-01'),('final','2026-01-01')]:
        f=oof.loc[oof.signal_date.lt(cutoff)&oof.label_end_date.lt(cutoff)&oof.label_available].copy()
        f=_sample(f);y=np.clip(f.y_next_open.to_numpy(float),-.2,.2)
        weights=f.signal_date.map(1/f.groupby('signal_date').size()).to_numpy(float,copy=True);weights/=weights.mean()
        for group,members in groups.items():
            x=f[['mu__'+m for m in members]].to_numpy(float)
            full_x=oof[['mu__'+m for m in members]].to_numpy(float)
            state=state_features(oof,full_x)[f.index.to_numpy()]
            for method in FUSIONS:
                path=ROOT/'fusion_artifacts'/stage/(group+'__'+method+'.joblib');path.parent.mkdir(parents=True,exist_ok=True)
                receipt=path.with_suffix('.json')
                if path.exists():
                    if not a.resume: raise RuntimeError('FUSION_ALREADY_EXISTS')
                    record=read(receipt)
                    assert record['artifact_sha256']==sha(path),'FUSION_ARTIFACT_CHANGED'
                    prior_input=ROOT/record['input_path']
                    assert prior_input.is_file() and record['input_sha256']==sha(prior_input),'FUSION_INPUT_CHANGED'
                    assert record['stage']==stage and record['group']==group and record['method']==method and record['members']==members
                    assert record['cutoff']==cutoff and record['label_end_max']<cutoff and record['rows']==len(f)
                    logs.append(record);continue
                start=time.monotonic()
                with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=2):
                    model=Fusion(method).fit(x,y,state,weights)
                joblib.dump(model,path)
                record=dict(stage=stage,group=group,method=method,members=members,rows=len(f),dates=int(f.signal_date.nunique()),
                  signal_max=str(f.signal_date.max()),label_end_max=str(f.label_end_date.max()),cutoff=cutoff,
                  base_prediction_cutoffs=sorted(f.base_fit_cutoff.unique()),input_sha256=sha(oof_path),input_path=str(oof_path.relative_to(ROOT)),
                  artifact_sha256=sha(path),training_mse=model.training_mse,residual_scale=model.residual_scale,
                  fitted=method not in ['equal','median'],seconds=time.monotonic()-start,warnings=[str(w.message) for w in caught])
                write(receipt,record);logs.append(record)
                pd.DataFrame(logs).to_csv(ROOT/'FUSION_FIT_LOG.csv',index=False)
                print(json.dumps(dict(stage=stage,group=group,method=method,seconds=round(record['seconds'],2))),flush=True)
    if not a.groups:
        write(ROOT/'fusion_artifacts/COMPLETE.json',dict(status='COMPLETE',objects=len(logs),learned_objects=sum(r['fitted'] for r in logs),fit_2026_rows=0))
        predict_year(2025)

def predict_year(year,provider_subset=None):
    if year==2026:
        from freeze_batch import validate_global_freeze
        validate_global_freeze()
    stage='validation' if year==2025 else 'final'
    panel=pd.read_parquet(ROOT/f'input/eval_{year}/features.parquet').sort_values(['signal_date','ticker']).reset_index(drop=True)
    providers=PROVIDERS if provider_subset is None else provider_subset
    x,sigma=load_native(stage,panel,providers);out=ROOT/f'predictions/forecasts/{year}';out.mkdir(parents=True,exist_ok=True)
    roster=forecasts() if provider_subset is None else [s for s in forecasts() if s['fusion']=='identity' and s['members'][0] in providers]
    for spec in roster:
        path=out/(spec['forecast_id']+'.parquet')
        if path.exists(): continue
        indices=[providers.index(m) for m in spec['members']];xx=x[:,indices];ss=sigma[:,indices]
        if spec['fusion']=='identity':mu=xx[:,0];s=ss[:,0]
        else:
            model=joblib.load(ROOT/'fusion_artifacts'/stage/(spec['forecast_id']+'.joblib'))
            state=state_features(panel,xx);mu=model.predict(xx,state);s=model.uncertainty(xx,ss,state)
        f=panel[['signal_date','ticker']].copy();f['forecast_id']=spec['forecast_id'];f['mu']=mu;f['sigma']=s
        f['q10']=mu-1.2815515655446*s;f['q50']=mu;f['q90']=mu+1.2815515655446*s
        f['marginal_semantics']='training_residual_normal_proxy' if spec['fusion']=='identity' else 'fused_normal_moment_proxy'
        if spec['fusion']=='identity':
            native=pd.read_parquet(native_path(stage,spec['members'][0])).set_index(['signal_date','ticker']).reindex(pd.MultiIndex.from_frame(panel[['signal_date','ticker']]))
            for col in ['q10','q50','q90']:
                if col in native:
                    values=native[col].to_numpy(float)
                    f[col]=np.where(np.isfinite(values),values,f[col].to_numpy(float))
            has_native=np.isfinite(native[['q10','q50','q90']].to_numpy(float)).all(axis=1)
            if spec['members'][0] in QUANTILES:f.loc[has_native,'marginal_semantics']='native_quantile_piecewise'
            elif spec['members'][0] in DISTRIBUTIONS:f.loc[has_native,'marginal_semantics']='native_normal_distribution'
            elif spec['members'][0] in PROBS:f['marginal_semantics']='class_probability_amplitude_normal_moment_proxy'
        f['prediction_id']=[spec['forecast_id']+'|'+str(d.date())+'|'+t for d,t in zip(f.signal_date,f.ticker)]
        assert np.isfinite(f[['mu','sigma','q10','q50','q90']].to_numpy(float)).all()
        f.to_parquet(path,index=False)
    print(json.dumps({'forecast_year':year,'count':len(roster),'partial_generation_only':provider_subset is not None}),flush=True)

if __name__=='__main__':main()
