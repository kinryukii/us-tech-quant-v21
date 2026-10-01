from pathlib import Path
import json, hashlib, itertools
import numpy as np
import pandas as pd
import joblib
from scipy.special import xlogy

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT/'a2_multimodel_joint_20260928'
OUT = Path(__file__).resolve().parent
META = SRC/'ensemble_artifacts/meta'
DATA = ROOT/'a2_latest_effective_joint_20260927/data/pre2026_joint_context.parquet'
STATES = ((0.,.95,0.),(.05,.5,10.),(.1,.05,40.))
ACTIONS = (0.,.025,.05,.075,.1)
HASHES={}

def digest(p):
    p=Path(p)
    with p.open('rb') as f: value=hashlib.file_digest(f,'sha256').hexdigest()
    HASHES[str(p)]=value
    return value

def write(name,x):
    (OUT/name).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False,default=str),encoding='utf8')

def interval(values):
    x=np.asarray(values,float); x=x[np.isfinite(x)]; n=len(x)
    mean=float(x.mean()); z=x-mean
    omega=float(z@z/n)
    for lag in range(1,min(5,n-1)+1):
        omega+=2*(1-lag/6)*float(z[lag:]@z[:-lag]/n)
    se=float(np.sqrt(max(omega,0)/n))
    return dict(daily_mean=mean,days=n,hac_lag=5,hac_se=se,ci95_low=mean-1.96*se,ci95_high=mean+1.96*se)

def summarize(values,dates):
    return interval(pd.Series(values).groupby(np.asarray(dates)).mean().values)

def reward(f,clip):
    y=f.y_next_open.to_numpy(float)
    if clip: y=np.clip(y,-.2,.2)
    adv=f.avg_dollar_volume_20d.to_numpy(float); vol=f.realized_vol_20d.to_numpy(float)
    rewards=[]
    for cur,_,_ in STATES:
        for action in ACTIONS:
            actual=cur+np.minimum(action-cur,.01*adv/1e6) if action>cur else np.full(len(f),action)
            rewards.append(actual*y-.001*np.abs(actual-cur)-2*vol**2*actual**2)
    return np.concatenate(rewards)

def main():
    digest(OUT/'DIAGNOSTIC_SPEC.md'); digest(Path(__file__)); digest(DATA)
    receipt=json.loads((META/'FIT_RECEIPT.json').read_text(encoding='utf8'));digest(META/'FIT_RECEIPT.json')
    source=pd.read_parquet(DATA,columns=['signal_date','ticker','label_end_date','y_next_open','realized_vol_20d','avg_dollar_volume_20d'])
    assert source.signal_date.lt('2026-01-01').all()
    assert source.label_end_date.dropna().lt('2026-01-01').all()
    assert not source.duplicated(['signal_date','ticker']).any()
    metrics=[]; pairs=[]; correlations=[]; quantiles=[]; classifications=[]; calibration=[]; audits=[]; daily=[]; errors=[]
    for year in (2024,2025):
        kp=META/f'oof_sample_keys_{year}.parquet'; mp=META/f'oof_matrix_{year}.npz'
        assert digest(kp)==receipt['oof_sampling'][str(year)]['sample_keys_sha256']
        assert digest(mp)==receipt['oof_sampling'][str(year)]['matrix_sha256']
        keys=pd.read_parquet(kp); keys['_order']=np.arange(len(keys))
        f=keys.merge(source,on=['signal_date','ticker','label_end_date'],how='left',validate='one_to_one',indicator=True).sort_values('_order')
        assert f._merge.eq('both').all() and np.isfinite(f[['y_next_open','realized_vol_20d','avg_dollar_volume_20d']]).all().all()
        assert f.signal_date.dt.year.eq(year).all() and f.label_end_date.lt(f'{year+1}-01-01').all()
        z=np.load(mp,allow_pickle=False); x=z['features']; saved=z['target']; columns=z['feature_order'].tolist()
        yc=reward(f,True); yu=reward(f,False)
        assert np.allclose(yc,saved,rtol=0,atol=1e-14),np.max(np.abs(yc-saved))
        n=len(f); dates=np.tile(f.signal_date.values,15)
        pp={name:x[:,columns.index('base_'+name)] for name in ('ridge','elastic_net','hgb')}
        if year==2025:
            rec=next(r for r in receipt['fits'] if r['stage']=='validation')
            assert rec['oof_years']==[2024] and pd.Timestamp(rec['train_label_end_max'])<pd.Timestamp('2025-01-01')
            artifact=Path(rec['artifact']); assert digest(artifact)==rec['artifact_sha256']
            pp['stack_validation']=joblib.load(artifact).predict(x)
        for clock in receipt['oof_predictor_clocks'][str(year)]:
            assert pd.Timestamp(clock['signal_max'])<pd.Timestamp(f'{year}-01-01') and pd.Timestamp(clock['label_end_max'])<pd.Timestamp(f'{year}-01-01')
        clipped=np.abs(f.y_next_open.to_numpy(float))>.2
        audits.append(dict(year=year,stock_date_rows=n,expanded_rows=n*15,days=f.signal_date.nunique(),signal_max=str(f.signal_date.max()),label_max=str(f.label_end_date.max()),clip_changed_stock_dates=int(clipped.sum()),max_raw_return=float(f.y_next_open.max()),min_raw_return=float(f.y_next_open.min()),saved_target_reconstruction_max_abs_error=float(np.max(np.abs(yc-saved))),prediction_names=list(pp)))
        f.loc[clipped,['signal_date','ticker','label_end_date','y_next_open']].assign(year=year).to_csv(OUT/f'untrimmed_large_returns_{year}.csv',index=False)
        for target,y in [('unclipped_primary',yu),('clipped_training_sensitivity',yc)]:
            residual={m:p-y for m,p in pp.items()}
            for m,r in residual.items():
                for metric,loss in [('mse',r*r),('mae',np.abs(r)),('bias',r)]:
                    s=summarize(loss,dates)
                    metrics.append(dict(year=year,target=target,model=m,metric=metric,row_mean=float(loss.mean()),**s))
                    d=pd.DataFrame({'signal_date':dates,'value':loss}).groupby('signal_date',as_index=False).value.mean()
                    d['year']=year;d['target']=target;d['model']=m;d['metric']=metric;daily.append(d)
            # Correlations stay within common utility units, including stock-date-mean residuals.
            avg=pd.DataFrame({m:r.reshape(15,n).mean(axis=0) for m,r in residual.items()})
            for a,b in itertools.combinations(pp,2):
                ra,rb=residual[a],residual[b]
                ac=ra.reshape(15,n);bc=rb.reshape(15,n)
                correlations.append(dict(year=year,target=target,a=a,b=b,expanded_residual_pearson=float(np.corrcoef(ra,rb)[0,1]),stock_date_mean_residual_pearson=float(avg[a].corr(avg[b])),daily_mean_residual_pearson=float(pd.DataFrame({'date':dates,'a':ra,'b':rb}).groupby('date')[['a','b']].mean().corr().iloc[0,1])))
            for a,b in itertools.permutations(pp,2):
                ra,rb=residual[a],residual[b];la=(ra*ra).reshape(15,n).mean(axis=0);lb=(rb*rb).reshape(15,n).mean(axis=0)
                # Worst quartile selected on stock-date mean squared error, then date-clustered summaries.
                bad=la>=np.quantile(la,.75)
                row=dict(year=year,target=target,reference=a,member=b,member_beats_reference_fraction=float(np.mean(lb<la)),opposite_signed_error_fraction=float(np.mean(ra*rb<0)),reference_bad_quartile_stock_dates=int(bad.sum()))
                for label,mask in [('all',np.ones(n,bool)),('reference_bad_quartile',bad),('reference_other_75pct',~bad)]:
                    diff=la[mask]-lb[mask]; ss=summarize(diff,f.signal_date.values[mask])
                    row.update({label+'_'+key:val for key,val in ss.items()})
                pairs.append(row)
            p=x[:,columns.index('base_logistic')]; yy=(y>0).astype(float); p=np.clip(p,1e-15,1-1e-15)
            for metric,loss in [('brier',(p-yy)**2),('logloss',-(xlogy(yy,p)+xlogy(1-yy,1-p)))]:
                classifications.append(dict(year=year,target=target,metric=metric,row_mean=float(loss.mean()),event_rate=float(yy.mean()),mean_probability=float(p.mean()),**summarize(loss,dates)))
            bins=np.minimum((p*10).astype(int),9)
            for binid in range(10):
                idx=bins==binid
                if not idx.any(): continue
                ss=summarize(yy[idx]-p[idx],dates[idx])
                calibration.append(dict(year=year,target=target,probability_lower=binid/10,probability_upper=(binid+1)/10,expanded_rows=int(idx.sum()),mean_probability=float(p[idx].mean()),observed_positive_fraction=float(yy[idx].mean()),**ss))
            qmat=np.column_stack([x[:,columns.index('base_'+m)] for m in ('q10','q50','q90')])
            for j,q in enumerate((.1,.5,.9)):
                pred=qmat[:,j]; u=y-pred; pin=np.maximum(q*u,(q-1)*u)
                for metric,loss in [('pinball',pin),('coverage_y_le_q',(y<=pred).astype(float))]:
                    quantiles.append(dict(year=year,target=target,quantile=q,metric=metric,row_mean=float(loss.mean()),**summarize(loss,dates)))
            for metric,loss in [('q10_q90_interval_coverage',((y>=qmat[:,0])&(y<=qmat[:,2])).astype(float)),('quantile_crossing_fraction',np.any(np.diff(qmat,axis=1)<0,axis=1).astype(float))]:
                quantiles.append(dict(year=year,target=target,quantile='joint',metric=metric,row_mean=float(loss.mean()),**summarize(loss,dates)))
        # Persist individual stock-date aggregate errors for inspection, never independent-expanded inference.
        er=f[['signal_date','ticker','label_end_date','y_next_open']].copy();er['year']=year
        for m,p in pp.items():
            er[m+'_mse_unclipped']=((p-yu)**2).reshape(15,n).mean(axis=0)
            er[m+'_mse_clipped']=((p-yc)**2).reshape(15,n).mean(axis=0)
        errors.append(er)
    pd.DataFrame(metrics).to_csv(OUT/'mean_target_metrics.csv',index=False)
    pd.DataFrame(pairs).to_csv(OUT/'pairwise_error_relief.csv',index=False)
    pd.DataFrame(correlations).to_csv(OUT/'comparable_residual_correlations.csv',index=False)
    pd.DataFrame(quantiles).to_csv(OUT/'quantile_diagnostics.csv',index=False)
    pd.DataFrame(classifications).to_csv(OUT/'classification_metrics.csv',index=False)
    pd.DataFrame(calibration).to_csv(OUT/'classification_calibration.csv',index=False)
    pd.concat(daily,ignore_index=True).to_csv(OUT/'daily_prediction_loss.csv',index=False)
    pd.concat(errors,ignore_index=True).to_parquet(OUT/'stock_date_errors.parquet',index=False)
    write('PREDICTION_AUDIT.json',dict(status='PASS',scope='post_hoc_frozen_predictions_no_refit_no_2026',audits=audits,input_sha256=HASHES,uncertainty='signal-date mean, Newey-West lag5, normal95; no 15x independence'))
    print(json.dumps(audits,indent=2,default=str))
    print(pd.DataFrame(metrics).query("year==2025 and metric=='mse'")[['target','model','daily_mean','ci95_low','ci95_high']].to_string(index=False))
    print(pd.DataFrame(correlations).query("year==2025 and target=='unclipped_primary'").to_string(index=False))

if __name__=='__main__':main()
