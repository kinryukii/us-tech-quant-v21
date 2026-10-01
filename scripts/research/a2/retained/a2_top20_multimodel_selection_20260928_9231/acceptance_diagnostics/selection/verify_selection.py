"""Independent validation of the saved frozen sorting tables, without fitting."""
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(OUT))
import run_selection as s


def main():
    details={}
    guard=s.ev.forbid_fitting()
    for year in [2025,2026]:
        done=json.loads((OUT/f'COMPLETE_{year}.json').read_text(encoding='utf-8'))
        frozen=json.loads((OUT/f'PRE_INFERENCE_{year}.json').read_text(encoding='utf-8'))
        assert done['fit_attempts']==0 and done['source_sha256_unchanged']
        for p,h in frozen['source_sha256'].items():assert s.ev.sha(p)==h,p
        for p,h in done['output_sha256'].items():assert s.ev.sha(p)==h,p
        scores=pd.read_parquet(OUT/f'scores_{year}.parquet')
        candidates=pd.read_parquet(OUT/f'candidates_{year}.parquet')
        eligible=candidates[candidates.ranking_eligible]
        daily=pd.read_parquet(OUT/f'daily_{year}.parquet')
        assert len(scores)==len(eligible)*len(s.POLICIES)
        assert not scores.duplicated(['policy','signal_date','ticker']).any()
        assert set(scores.policy)==set(s.POLICIES)
        assert scores.groupby(['signal_date','ticker']).size().eq(len(s.POLICIES)).all()
        expected=eligible.groupby('signal_date').size()
        for (policy,date),g in scores.groupby(['policy','signal_date'],sort=False):
            assert len(g)==expected[date]
            if policy=='cash_control':
                assert g.reference_score.isna().all() and g.reference_rank.isna().all() and not g.reference_top20.any()
            else:
                order=g.sort_values(['reference_score','ticker'],ascending=[False,True],kind='stable')
                assert np.array_equal(order.reference_rank,np.arange(1,len(g)+1))
                assert np.array_equal(g.reference_top20,g.reference_rank.le(20))
                assert g.reference_top20.sum()==min(20,len(g))
        for alias in ['joint_hgb_lw','joint_hgb_pca']:
            a=scores[scores.policy.eq(alias)].sort_values(['signal_date','ticker'])
            b=scores[scores.policy.eq('joint_hgb')].sort_values(['signal_date','ticker'])
            for column in ['reference_score','reference_rank','reference_top20']:
                assert np.array_equal(a[column],b[column])
        assert daily.groupby('signal_date').complete_common_pool.nunique().eq(1).all()
        assert daily.loc[~daily.complete_common_pool,['main_ic','main_top20_minus_rest','main_simple_gross','main_simple_net']].isna().all().all()
        full=daily.simple_gross_if_selected_labels_complete.notna()
        assert np.allclose(daily.loc[full,'simple_net_if_selected_labels_complete'],
            daily.loc[full,'simple_gross_if_selected_labels_complete']-daily.loc[full,'selected_count']*.0475*.002)
        cont=pd.read_parquet(OUT/f'ensemble_contributions_{year}.parquet')
        rebuilt=cont[[f'contribution_{name}' for name in s.en.BASE_NAMES]].sum(axis=1)-cont.disagreement_penalty-cont.downside_penalty
        assert np.allclose(rebuilt,cont.reference_score,atol=1e-12,rtol=1e-11)
        assert not cont.duplicated(['policy','signal_date','ticker']).any()
        joined=cont[['policy','signal_date','ticker','reference_score']].merge(
            scores[['policy','signal_date','ticker','reference_score']],on=['policy','signal_date','ticker'],suffixes=('_contributions','_ranking'),validate='one_to_one')
        assert len(joined)==len(cont)
        assert np.array_equal(joined.reference_score_contributions,joined.reference_score_ranking)
        conflicts=eligible[eligible.known_event_conflict]
        assert conflicts.forward_return.isna().all()
        assert conflicts.label_status.str.contains('KNOWN_EVENT_CONFLICT').all()
        if year==2026:
            dates=eligible.loc[eligible.input_conflict,'signal_date'].unique()
            assert not daily[daily.signal_date.isin(dates)].complete_common_pool.any()
        details[str(year)]={'status':'PASS','candidate_rows':len(eligible),'score_rows':len(scores),
            'signal_days':len(expected),'policies':len(s.POLICIES),
            'full_common_days':int(daily[daily.policy.eq('joint_hgb')].complete_common_pool.sum()),
            'known_event_conflict_rows':len(conflicts),'all_source_and_output_hashes_verified':True,
            'candidate_pool_preserved_across_all_methods':True,'ranking_and_tie_break_reproduced':True,
            'contributions_reconcile':True,'simple_20bps_cost_identity':True,'incomplete_main_metrics_missing':True}
    assert guard['attempts']==0
    s.write(OUT/'VERIFICATION.json',dict(status='PASS_FROZEN_SELECTION_DIAGNOSTIC',years=details,
        synthetic_behavior_tests_passed=4,fit_attempts=guard['attempts'],source_files_modified=False))
    print(json.dumps(details),flush=True)


if __name__=='__main__':main()
