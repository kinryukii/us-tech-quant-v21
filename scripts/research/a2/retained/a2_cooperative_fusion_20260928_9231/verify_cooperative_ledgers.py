"""Read completed new ledgers with the original independent reconstruction checks.

No replay or prediction. Never call the old verifier's main() or write its root.
"""
from pathlib import Path
import importlib.util
import json
import sys
import pandas as pd

ROOT=Path(__file__).resolve().parent
BASE_ROOT=ROOT.parent/'a2_top20_multimodel_selection_20260928_9231'
sys.dont_write_bytecode=True
EXPECTED=['fusion_fixed_non_equal','fusion_learned_weights','fusion_nonlinear_stacking',
          'fusion_conditional_gate','fusion_hgb_then_linear','fusion_linear_then_hgb','fusion_target_decisions']


def main():
    source=BASE_ROOT/'verify_and_report.py'
    spec=importlib.util.spec_from_file_location('read_only_old_account_verifier',source)
    verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier)
    source_hash=verifier.sha(source)
    verifier.ROOT=ROOT # In-memory relative-path reporting only; inspect() is read-only.
    scenarios=[];paths=[]
    for year,cost in [(2025,10),(2026,10),(2026,5),(2026,25)]:
        folder=ROOT/f'evaluation_{year}/cost_{cost}'
        complete=verifier.read(folder/'COMPLETE.json')
        frozen=verifier.read(folder/'FROZEN_BEFORE_REPLAY.json')
        assert complete['fit_attempts']==0 and complete['policies']==7
        assert frozen['roster']==EXPECTED and not frozen['blind_test'] and not frozen['full_pool_complete']
        assert all(verifier.sha(p)==h for p,h in frozen['source_sha256'].items())
        qualification=verifier.read(folder/'ACTIVE_13F_AUDIT.json')
        assert qualification['latest_restatement_membership_certified'] is False
        assert qualification['qualification_scope']=='QUARTER_CLOCK_ONLY_INHERITED_DATA_LIMITATIONS'
        for name in EXPECTED:
            result=verifier.inspect(folder/name)
            assert result['formal_performance'] is False and result['certified_retrospective_return'] is None
            # Recompute the renamed price-gate-only return from original ledger semantics.
            daily=pd.read_parquet(folder/name/'daily.parquet')
            known=daily.certified_nav.dropna()
            if year==2025 and daily.certified_nav.notna().all():
                assert abs(result['price_gate_only_return']-(known.iloc[-1]/1e6-1))<1e-12
            else:assert result['price_gate_only_return'] is None
            paths.append(result)
        scenarios.append({'year':year,'cost_bps':cost,'paths':7,'frozen_hashes_verified':True})
    assert len(paths)==28 and verifier.sha(source)==source_hash
    output={'status':'PASS','paths':paths,'scenarios':scenarios,'path_count':28,
        'reused_verifier':str(source),'reused_verifier_sha256':source_hash,
        'full_replay_calls':0,'model_predict_calls':0,'fit_calls':0,
        'full_pool_certified':False,'blind_test':False,'shareholder_total_return_certified':False,
        'checks':'Original independent trades->units/cash/cost/NAV reconstruction; action clocks, buy capacity, active/reserved constraints; new frozen 7-path roster and inherited qualification.'}
    (ROOT/'INDEPENDENT_LEDGER_VERIFICATION.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'status':'PASS','paths':28,'fit_calls':0,'full_pool_certified':False}))


if __name__=='__main__':main()
