from analyze_predictions import *

def main():
    source=pd.read_parquet(DATA,columns=['signal_date','ticker','label_end_date','y_next_open','realized_vol_20d','avg_dollar_volume_20d'])
    rows=[]; contrasts=[]; corr=[]; relief=[]
    for year in (2024,2025):
        keys=pd.read_parquet(META/f'oof_sample_keys_{year}.parquet');keys['_order']=np.arange(len(keys))
        f=keys.merge(source,on=['signal_date','ticker','label_end_date'],validate='one_to_one').sort_values('_order')
        z=np.load(META/f'oof_matrix_{year}.npz');x=z['features']; cols=z['feature_order'].tolist();n=len(keys)
        y=reward(f,False); dates=np.tile(f.signal_date.values,15); actions=np.repeat(list(ACTIONS)*3,n)
        state=np.repeat(np.arange(3),5*n); probs=x[:,cols.index('base_logistic')]; yy=(y>0).astype(float)
        qmat=np.column_stack([x[:,cols.index('base_'+m)] for m in ('q10','q50','q90')])
        slices=[('action_positive',actions>0)]+[(f'state{si}_action{a:.3f}',(state==si)&np.isclose(actions,a)) for si in range(3) for a in ACTIONS]
        for label,mask in slices:
            p=np.clip(probs[mask],1e-15,1-1e-15); ys=yy[mask]; dat=dates[mask]
            for metric,loss in [('brier',(p-ys)**2),('logloss',-(xlogy(ys,p)+xlogy(1-ys,1-p)))]:
                rows.append(dict(year=year,slice=label,model='logistic',metric=metric,expanded_rows=int(mask.sum()),probability_mean=float(p.mean()),event_rate=float(ys.mean()),**summarize(loss,dat)))
            for j,q in enumerate((.1,.5,.9)):
                pred=qmat[mask,j]; u=y[mask]-pred
                for metric,loss in [('pinball',np.maximum(q*u,(q-1)*u)),('coverage_y_le_q',(y[mask]<=pred).astype(float))]:
                    rows.append(dict(year=year,slice=label,model=f'q{int(q*100)}',metric=metric,expanded_rows=int(mask.sum()),**summarize(loss,dat)))
        pp={m:x[:,cols.index('base_'+m)].reshape(3,5,n) for m in ('ridge','elastic_net','hgb')}
        if year==2025:pp['stack_validation']=joblib.load(META/'validation_meta.joblib').predict(x).reshape(3,5,n)
        yt=y.reshape(3,5,n); yt=yt[:,1:]-yt[:,:1];dt=np.tile(f.signal_date.values,12)
        errors={}
        for m,p in pp.items():
            err=(p[:,1:]-p[:,:1]-yt).reshape(-1); errors[m]=err
            for metric,loss in [('mse',err**2),('mae',np.abs(err))]:
                contrasts.append(dict(year=year,model=m,metric=metric,target='incremental_utility_vs_action0_unclipped',**summarize(loss,dt)))
        for a,b in itertools.combinations(errors,2):
            corr.append(dict(year=year,a=a,b=b,residual_pearson=float(np.corrcoef(errors[a],errors[b])[0,1])))
        clipped_target=z['target'].reshape(3,5,n)
        clipped_delta=clipped_target[:,1:]-clipped_target[:,:1]
        for m,p in pp.items():
            ec=(p[:,1:]-p[:,:1]-clipped_delta).reshape(-1)
            for metric,loss in [('mse',ec**2),('mae',np.abs(ec))]:
                contrasts.append(dict(year=year,model=m,metric=metric,target='incremental_utility_vs_action0_clipped_sensitivity',**summarize(loss,dt)))
        for a,b in itertools.permutations(errors,2):
            la=(errors[a]**2).reshape(12,n).mean(axis=0);lb=(errors[b]**2).reshape(12,n).mean(axis=0)
            bad=la>=np.quantile(la,.75)
            row=dict(year=year,reference=a,member=b,member_beats_reference_fraction=float(np.mean(lb<la)),opposite_signed_error_fraction=float(np.mean(errors[a]*errors[b]<0)))
            for label,mask in [('all',np.ones(n,bool)),('reference_bad_quartile',bad),('reference_other_75pct',~bad)]:
                row.update({label+'_'+k:v for k,v in summarize(la[mask]-lb[mask],f.signal_date.values[mask]).items()})
            relief.append(row)
    pd.DataFrame(relief).to_csv(OUT/'incremental_pairwise_error_relief.csv',index=False)
    pd.DataFrame(rows).to_csv(OUT/'state_action_stratified_metrics.csv',index=False)
    pd.DataFrame(contrasts).to_csv(OUT/'incremental_utility_metrics.csv',index=False)
    pd.DataFrame(corr).to_csv(OUT/'incremental_utility_correlations.csv',index=False)
    print(pd.DataFrame(rows).query("year==2025 and slice=='action_positive'").to_string(index=False))
    print(pd.DataFrame(corr).query('year==2025').to_string(index=False))

if __name__=='__main__':main()
