"""Check saved diagnostics only; no model inference, fitting, or account replay."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

OUT=Path(__file__).resolve().parent
ROOT=OUT.parent
OLD=ROOT.parent/'a2_top20_multimodel_selection_20260928_9231/acceptance_diagnostics/selection'
EXPERTS=['ridge','elastic_net','logistic','hgb','q50','mlp']
CONTROLS=['joint_hgb','ensemble_equal','ensemble_stacking']

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def run():
    results=[]
    for year,complete in [(2025,245),(2026,88)]:
        pre=json.loads((OUT/f'PRE_INFERENCE_{year}.json').read_text(encoding='utf-8'))
        receipt=json.loads((OUT/f'COMPLETE_{year}.json').read_text(encoding='utf-8'))
        assert receipt['fit_attempts']==0 and receipt['source_sha256_unchanged']
        for path,digest in pre['source_sha256'].items():assert sha(path)==digest,('SOURCE_HASH',path)
        for path,digest in receipt['output_sha256'].items():assert sha(path)==digest,('OUTPUT_HASH',path)
        candidates=pd.read_parquet(OLD/f'candidates_{year}.parquet')
        candidates=candidates[candidates.ranking_eligible].set_index(['signal_date','ticker']).sort_index()
        scores=pd.read_parquet(OUT/f'scores_{year}.parquet')
        assert not scores.duplicated(['policy','signal_date','ticker']).any()
        assert len(scores)==7*len(candidates)==receipt['score_rows']
        assert np.isfinite(scores.reference_score).all()
        daily=pd.read_parquet(OUT/f'daily_{year}.parquet').set_index(['policy','signal_date']).sort_index()
        assert daily.index.is_unique
        max_error=0.;selected_unknown=0;gate_ranges={}
        for name,part in scores.groupby('policy'):
            part=part.set_index(['signal_date','ticker']).sort_index()
            assert part.index.equals(candidates.index)
            for column in ['label_available','label_status','input_conflict_day','forward_return']:
                pd.testing.assert_series_equal(part[column],candidates[column],check_names=False)
            assert int(daily.loc[name].complete_common_pool.sum())==complete
            for date,day in part.reset_index().groupby('signal_date'):
                ordered=day.sort_values(['reference_score','ticker'],ascending=[False,True])
                np.testing.assert_array_equal(ordered.reference_rank,np.arange(1,len(day)+1))
                np.testing.assert_array_equal(day.reference_top20,day.reference_rank.le(20))
                selected=day[day.reference_top20]
                assert len(selected)==20
                selected_unknown+=int((~selected.label_available).sum())
                metric=daily.loc[(name,date)]
                full=bool(day.label_available.all() and not day.input_conflict_day.any())
                assert bool(metric.complete_common_pool)==full
                expected=.0475*selected.forward_return.sum()-.0475*20*.002 if selected.label_available.all() else np.nan
                np.testing.assert_allclose(metric.simple_net_if_selected_labels_complete,expected,equal_nan=True,rtol=1e-12,atol=1e-12)
                if not full:assert pd.isna(metric.main_simple_net)
            diagnostic=pd.read_parquet(OUT/f'diagnostics_{year}_{name}.parquet').set_index(['signal_date','ticker']).sort_index()
            assert diagnostic.index.is_unique and diagnostic.index.equals(part.index)
            np.testing.assert_array_equal(diagnostic.reference_score,part.reference_score)
            actions=np.stack(diagnostic.reference_action_values)
            np.testing.assert_allclose(actions[:,0],0.,atol=1e-14)
            np.testing.assert_array_equal(actions[:,2],part.reference_score)
            if name in ['fusion_fixed_non_equal','fusion_conditional_gate']:
                reconstructed=diagnostic[[f'contributions_{x}' for x in EXPERTS]].sum(axis=1)
                weights=diagnostic[[f'weights_{x}' for x in EXPERTS]].to_numpy(float)
                assert (weights>=0).all()
                np.testing.assert_allclose(weights.sum(axis=1),1.,atol=2e-7)
                if name=='fusion_conditional_gate':gate_ranges={x:float(np.ptp(weights[:,j])) for j,x in enumerate(EXPERTS)}
            elif name=='fusion_learned_weights':reconstructed=diagnostic[[f'contribution_rank_{x}' for x in EXPERTS]].sum(axis=1)
            elif name=='fusion_target_decisions':
                mixed=diagnostic[[f'target_contributions_{x}' for x in EXPERTS]].sum(axis=1)
                np.testing.assert_allclose(mixed,diagnostic.mixed_target,atol=1e-12)
                reconstructed=10.*mixed-.25
            else:reconstructed=diagnostic.anchor_prediction+diagnostic.residual_prediction
            error=float(np.abs(reconstructed-part.reference_score).max());max_error=max(max_error,error)
            assert error<1e-8
        controls=pd.read_parquet(OUT/f'controls_daily_{year}.parquet').drop(columns='diagnostic_origin').sort_values(['policy','signal_date']).reset_index(drop=True)
        original=pd.read_parquet(OLD/f'daily_{year}.parquet')
        original=original[original.policy.isin(CONTROLS)].sort_values(['policy','signal_date']).reset_index(drop=True)
        pd.testing.assert_frame_equal(controls,original)
        results.append(dict(year=year,score_rows=len(scores),unique_score_keys=True,
            candidate_rows=len(candidates),complete_common_days=complete,all_seven_same_pool=True,
            all_rankings_reconstructed=True,selected_rows_with_missing_labels=selected_unknown,
            labels_and_conflict_flags_exactly_original=True,original_controls_exactly_unchanged=True,
            maximum_score_reconstruction_error=max_error,gate_weight_range_at_fixed_state=gate_ranges,
            source_and_output_hashes_unchanged=True))
    result=dict(status='PASS',years=results,fit_calls=0,predict_calls=0,replay_calls=0,
        verifier_sha256=sha(__file__),scope='Saved table reconciliation; gate variation is state-feature variation, not validation of predictive benefit')
    (OUT/'VERIFICATION.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':run()
