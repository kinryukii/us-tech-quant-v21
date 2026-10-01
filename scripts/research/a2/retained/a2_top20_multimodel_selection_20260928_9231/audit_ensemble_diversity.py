"""Read-only diversity, pre-2026 meta validation and KKT evidence.

The outputs concern sampled counterfactual state/action advantages, not
independent stock picks, a trading account, annual returns or causal effects.
"""
from pathlib import Path
import json
import sys

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
import ensemble as e


def ratio(a,b):
    return float(a/b) if b else None


def matrix_record(frame,method):
    corr=frame[e.RANK_COLUMNS].corr(method=method)
    if not np.isfinite(corr.to_numpy()).all():
        raise ValueError('NONFINITE_FEATURE_CORRELATION')
    result={base:{other:float(corr.iloc[i,j]) for j,other in enumerate(e.BASE_NAMES)}
            for i,base in enumerate(e.BASE_NAMES)}
    raw=corr.to_numpy();off=raw[np.triu_indices(len(raw),1)]
    eig=np.maximum(np.linalg.eigvalsh(raw),0)
    return dict(matrix=result,maximum_absolute_off_diagonal=float(np.abs(off).max()),
        mean_absolute_off_diagonal=float(np.abs(off).mean()),
        correlation_effective_dimension=float(eig.sum()**2/(eig@eig)),
        effective_dimension_definition='(sum of eigenvalues)^2 / sum of squared eigenvalues; descriptive, between 1 and 6')


def diagnostics(y,pred):
    y=np.asarray(y,float);pred=np.asarray(pred,float)
    assert len(y)==len(pred) and np.isfinite(y).all() and np.isfinite(pred).all()
    truth=y>0;positive=pred>0
    tp=int((truth&positive).sum());tn=int((~truth&~positive).sum())
    fp=int((~truth&positive).sum());fn=int((truth&~positive).sum())
    tpr=ratio(tp,tp+fn);tnr=ratio(tn,tn+fp)
    return dict(rows=len(y),mse=float(np.mean((y-pred)**2)),
        zero_advantage_prediction_mse=float(np.mean(y**2)),
        mae=float(np.mean(np.abs(y-pred))),
        true_positive_advantage_fraction=float(truth.mean()),predicted_positive_advantage_fraction=float(positive.mean()),
        positive_advantage_accuracy=float((positive==truth).mean()),
        balanced_positive_advantage_accuracy=None if tpr is None or tnr is None else float((tpr+tnr)/2),
        positive_advantage_recall=tpr,nonpositive_advantage_recall=tnr,
        sign_three_class_accuracy=float((np.sign(y)==np.sign(pred)).mean()),
        true_zero_advantage_rows=int((y==0).sum()),predicted_zero_advantage_rows=int((pred==0).sum()),
        confusion=dict(tp=tp,fp=fp,fn=fn,tn=tn))


def kkt(model,frame):
    x=frame[e.RANK_COLUMNS].to_numpy(float);y=frame.target_advantage.to_numpy(float)
    w=model.coef_
    gradient=x.T@(x@w-y)+model.alpha*w
    residual=np.where(w>1e-14,np.abs(gradient),np.maximum(-gradient,0))
    denom=max(1.,float(np.max(np.abs(x.T@y))))
    objective=float(.5*np.sum((x@w-y)**2)+.5*model.alpha*(w@w))
    gap_bound=float((residual@residual)/(2*model.alpha))
    return dict(nonnegative_coefficients=bool((w>=-1e-12).all()),
        maximum_raw_kkt_violation=float(residual.max()),normalizing_scale=denom,
        normalized_kkt_violation=float(residual.max()/denom),
        regularized_objective_half_sse=objective,
        strong_convexity_objective_gap_upper_bound=gap_bound,
        relative_objective_gap_upper_bound=ratio(gap_bound,objective),
        coefficient_zero_threshold=1e-14,
        definition='g=X.T@(X@w-y)+alpha*w; positive w requires g=0, zero w requires g>=0',
        coefficients={name:float(c) for name,c in zip(e.BASE_NAMES,w)})


def main():
    paths=[ROOT/'ensemble.py',ROOT/'ENSEMBLE_CONTRACT.md']
    paths.extend(e.OUT/f'oof_{year}.parquet' for year in [2024,2025])
    paths.extend(e.OUT/f'{stage}_{suffix}' for stage in ['validation','final']
                 for suffix in ['stacking.joblib','TRAIN_RECEIPT.json'])
    frozen={str(p):e.sha(p) for p in paths}
    oofs={}
    audits={}
    for year in [2024,2025]:
        f=pd.read_parquet(e.OUT/f'oof_{year}.parquet')
        e.verify_oof_clock(f,f'{year+1}-01-01')
        assert set(f.signal_date.dt.year)=={year}
        assert len(f)==90000 and not f.duplicated(['signal_date','ticker','state_id','action']).any()
        rec=json.loads((e.OUT/f'OOF_{year}_RECEIPT.json').read_text(encoding='utf-8'))
        assert e.sha(e.OUT/f'oof_{year}.parquet')==rec['oof_sha256']
        for path,digest in rec['base_artifact_sha256'].items():assert e.sha(path)==digest
        oofs[year]=f
        audits[str(year)]={'rows':len(f),'security_days':len(f[['signal_date','ticker']].drop_duplicates()),
            'signal_days':f.signal_date.nunique(),'signal_max':str(f.signal_date.max().date()),
            'label_end_max':str(f.label_end_date.max().date()),'base_stage':f.base_stage.unique().tolist(),
            'base_fit_cutoff':f.base_fit_cutoff.unique().tolist(),'artifact_and_base_hashes_verified':True,
            'all_rows_pearson':matrix_record(f,'pearson'),
            'nonzero_action_pearson':matrix_record(f[f.action.ne(0)],'pearson'),
            'nonzero_action_spearman':matrix_record(f[f.action.ne(0)],'spearman')}
    models={}
    for stage in ['validation','final']:
        rec=json.loads((e.OUT/f'{stage}_TRAIN_RECEIPT.json').read_text(encoding='utf-8'))
        assert rec['status']=='PASS' and rec['artifact_sha256']==e.sha(e.OUT/f'{stage}_stacking.joblib')
        models[stage]=joblib.load(e.OUT/f'{stage}_stacking.joblib')
        assert not models[stage].fit_intercept and models[stage].positive and models[stage].alpha==100
    performance={}
    for year in [2024,2025]:
        f=oofs[year]
        with threadpool_limits(limits=2):pred=models['validation'].predict(f[e.RANK_COLUMNS].to_numpy(float))
        mask=f.action.ne(0).to_numpy()
        performance[str(year)]={'scope':'in_sample_meta_fit_2024' if year==2024 else 'out_of_time_meta_validation_2025',
            'base_prediction_scope':'out_of_time in both years',
            'meta_model':'frozen validation_stacking trained only on 2024 OOF labels',
            'all_actions':diagnostics(f.target_advantage,pred),
            'nonzero_actions':diagnostics(f.target_advantage.to_numpy()[mask],pred[mask]),
            'by_state_nonzero_actions':{str(state):diagnostics(f.loc[mask&f.state_id.eq(state),'target_advantage'],
                pred[mask&f.state_id.eq(state).to_numpy()]) for state in sorted(f.state_id.unique())}}
    actual_coef={name:float(c) for name,c in zip(e.BASE_NAMES,models['final'].coef_)}
    total=float(models['final'].coef_.sum())
    final_weights={name:c/total for name,c in actual_coef.items()} if total>0 else {name:None for name in actual_coef}
    result={'status':'PASS','purpose':'Descriptive pre-2026 ensemble diversity and temporal validation',
        'status_scope':'Input integrity, chronological boundaries and finite metric computation; KKT residuals are reported separately, not asserted equal to the solver tolerance.',
        'unit':'sampled counterfactual one-session state-action utility advantage versus action zero; NOT portfolio returns',
        'target_underlying_return_clip':[-.2,.2],'target_cost_per_side':.001,
        'target_capacity_fraction':.01,'target_nominal_cash':1000000,
        'inputs':audits,'validation_meta_comparison':performance,
        'final_coefficients':actual_coef,'final_positive_coefficients':{k:v for k,v in actual_coef.items() if v>0},
        'final_coefficient_sum':total,'final_coefficient_shares_descriptive_only':final_weights,
        'coefficient_share_note':'Coefficient shares describe this calibration; they are not portfolio allocations or causal feature importance.',
        'mse_out_of_time_to_in_sample_ratio_nonzero_actions':ratio(performance['2025']['nonzero_actions']['mse'],performance['2024']['nonzero_actions']['mse']),
        'kkt':{'validation':kkt(models['validation'],oofs[2024]),
               'final':kkt(models['final'],pd.concat([oofs[2024],oofs[2025]],ignore_index=True))},
        'fit_calls':0,'reads_2026':False,'input_hashes':frozen,
        'limitations':['Multiple states/actions share stock/date labels and are not independent observations; no statistical significance is claimed.',
            'The zero action has mechanically zero target and six zero inputs; nonzero-action metrics prevent this from obscuring difficulty.',
            'The direction task is positive net utility advantage, not next-day stock-price direction.',
            'Yearly MSE changes also reflect market/regime and target variance changes, not only overfitting.',
            'Correlations describe predictions; heterogeneous model families alone do not establish useful diversification.',
            'No metric here selects, retrains, retunes, or promotes a model.']}
    for path,digest in frozen.items():assert e.sha(path)==digest
    result['inputs_unchanged']=True
    e.write(ROOT/'ENSEMBLE_DIVERSITY_AND_VALIDATION.json',result)
    print(json.dumps(dict(status='PASS',effective_dimensions={y:audits[y]['nonzero_action_pearson']['correlation_effective_dimension'] for y in audits},
        mse_nonzero={y:performance[y]['nonzero_actions']['mse'] for y in performance},
        balanced_accuracy_nonzero={y:performance[y]['nonzero_actions']['balanced_positive_advantage_accuracy'] for y in performance},
        final_coefficients=actual_coef,kkt={stage:info['normalized_kkt_violation'] for stage,info in result['kkt'].items()})),flush=True)


if __name__=='__main__':main()
