"""Bounded real-loader inference checks, no fitting and no full replay."""
from pathlib import Path
from types import SimpleNamespace
import json
import sys
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

ROOT=Path(__file__).resolve().parent
BASE=ROOT.parent/'a2_top20_multimodel_selection_20260928_9231'
sys.dont_write_bytecode=True
sys.path.insert(0,str(BASE))
import evaluate as old
sys.path.insert(0,str(ROOT))
import policy as p
import data_context as dc


def main():
    guard=old.forbid_fitting()
    import scipy.optimize
    def denied(*args,**kwargs):
        guard['attempts']+=1
        raise RuntimeError('NNLS_FORBIDDEN_DURING_INTEGRATION_REVIEW')
    scipy.optimize.nnls=denied
    hashes={str(ROOT/n):old.sha(ROOT/n) for n in ['policy.py','replay.py','data_context.py','meta_models.py','gate.py','EXPERIMENT_CONTRACT.md']}
    hashes.update({str(path):old.sha(path) for directory in ['meta_artifacts','gate_artifacts']
                   for path in (ROOT/directory).iterdir() if path.suffix in ['.pt','.npz','.joblib']})
    source=pd.read_parquet(old.DATA/'pre2026_joint_context.parquet',
        filters=[('signal_date','==',pd.Timestamp('2025-01-02'))],
        columns=['signal_date','ticker','new_buy_eligible',*old.FEATURES])
    # Small inference-only smoke panel; ranks are not used as performance evidence.
    day=source.sort_values('ticker').head(12).copy().reset_index(drop=True)
    day.loc[0,'new_buy_eligible']=False # Held security can hold/reduce, never increase.
    day.loc[1,'new_buy_eligible']=False # Unheld and ineligible row must be removed.
    held,excluded,restricted=day.ticker.iloc[:3]
    ctx=SimpleNamespace(current_weights={'RESERVED':.2,held:.04},current_units={'RESERVED':1.,held:2.},
        cash_weight=.76,available_slots=2,available_weight=.075,
        buy_restricted_tickers=(restricted,),reserved_tickers=('RESERVED',),reserved_weights={'RESERVED':.2})
    checks={};rows=[]
    checks['rank_order_matches_original_and_data_context']=list(p.original.RANK_COLUMNS)==dc.RANK_COLUMNS
    checks['fixed_weights_nonnegative_and_sum_one']=bool(np.all(p.FIXED>=0) and np.isclose(p.FIXED.sum(),1.))
    with threadpool_limits(limits=2):
        for stage in ['validation','final']:
            for name in p.NAMES:
                actor=p.CooperativePolicy(name,stage)
                observed=[];predict=actor.base.predict
                def capture(frame,current,cash,age,**kwargs):
                    observed.append((frame.ticker.tolist(),np.asarray(current).copy(),cash,np.asarray(age).copy(),kwargs.copy()))
                    return predict(frame,current,cash,age,**kwargs)
                actor.base.predict=capture
                result=actor(day,ctx)
                assert len(observed)==1
                names,current,cash,age,options=observed[0]
                assert excluded not in names and 'RESERVED' not in result.model_decisions
                assert result.model_decisions[restricted]==0.
                assert result.model_decisions[held]<=.04+1e-10
                assert current[names.index(held)]==.04 and cash==.76 and age[names.index(held)]==1.
                assert options['max_names']==2 and options['max_exposure']==.075
                weights=np.array(list(result.model_decisions.values()))
                assert np.isfinite(weights).all() and weights.min()>=0 and weights.max()<=.1+1e-10
                assert (weights>1e-9).sum()<=2 and weights.sum()<=.075+1e-10
                for ticker,info in result.raw_model_outputs.items():
                    scores=np.asarray(info['fused_action_values'])
                    assert scores[0]==0 and np.isfinite(scores).all()
                    if 'contributions' in info:
                        np.testing.assert_allclose(np.asarray(info['contributions']).sum(axis=-1),scores,atol=1e-10,rtol=1e-8)
                    if name=='fusion_learned_weights':
                        np.testing.assert_allclose(sum(np.asarray(info['contribution_'+c]) for c in dc.RANK_COLUMNS),scores,atol=1e-15)
                    if name in ['fusion_hgb_then_linear','fusion_linear_then_hgb','fusion_nonlinear_stacking']:
                        np.testing.assert_allclose(np.asarray(info['anchor_prediction'])+np.asarray(info['residual_prediction']),scores,atol=1e-14)
                    if name=='fusion_hgb_then_linear':
                        np.testing.assert_allclose(sum(np.asarray(info['linear_residual_contribution_'+c]) for c in dc.META_COLUMNS),info['residual_prediction'],atol=1e-14)
                    if name=='fusion_target_decisions':
                        targets=np.asarray(info['expert_target_weights']);terms=np.asarray(info['target_contributions'])
                        np.testing.assert_allclose(terms,targets*p.FIXED,atol=1e-14)
                        np.testing.assert_allclose(terms.sum(),info['mixed_target'],atol=1e-14)
                        expected=-((p.vm.ACTIONS-info['mixed_target'])/.1)**2
                        np.testing.assert_allclose(expected-expected[0],scores,atol=1e-14)
                usable=day.loc[day.ticker.isin(names)].sort_values('ticker').reset_index(drop=True)
                poisoned=usable.assign(y_next_open=np.nan,label_end_date=pd.Timestamp('2099-01-01'),
                    next_open=-1e99,following_open=1e99,target_advantage=np.inf)
                left=actor.score(usable,current,cash,age,slots=2,exposure=.075,restricted=(restricted,))[0]
                right=actor.score(poisoned,current,cash,age,slots=2,exposure=.075,restricted=(restricted,))[0]
                np.testing.assert_array_equal(left,right)
                zeroctx=SimpleNamespace(**{**ctx.__dict__,'available_slots':0,'available_weight':0.})
                zero=actor(day,zeroctx)
                assert sum(zero.model_decisions.values())==0.
                rows.append({'stage':stage,'policy':name,'status':'PASS','account_input_rows':len(names),
                    'base_predict_calls_per_account_decision':1,'future_field_poison_invariance':True,
                    'zero_action_and_contribution_reconstruction':True,'slots_budget_buy_restriction':True})
    checks['all14_real_loader_cases']=len(rows)==14
    checks['fit_guard_attempts_zero']=guard['attempts']==0
    checks['new_sources_and_models_unchanged']=all(old.sha(path)==digest for path,digest in hashes.items())
    output={'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'cases':rows,
        'reviewed_source_sha256':hashes,'full_replays':0,'test2026_rows_read':0,
        'sample_scope':'First 12 names of 2025-01-02, inference/constraint smoke only; no performance claim.',
        'fit_attempts':guard['attempts']}
    (ROOT/'POLICY_INTEGRATION_VERIFY.json').write_text(json.dumps(output,indent=2,ensure_ascii=False),encoding='utf-8')
    assert all(checks.values()),checks
    print(json.dumps({'status':output['status'],'cases':len(rows),'checks':checks},indent=2))


if __name__=='__main__':main()
