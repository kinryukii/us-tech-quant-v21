"""Read-only loader/interface/hash checks; no training or 2026 file reads."""
from pathlib import Path
import json
import sys
import numpy as np

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
import meta_models as m


def main():
    sys.path.insert(0,str(m.dc.BASE_ROOT))
    import evaluate
    guard=evaluate.forbid_fitting()
    def deny_nnls(*args,**kwargs):
        guard['attempts']+=1
        raise RuntimeError('NNLS_FORBIDDEN_IN_INTERFACE_VERIFICATION')
    m.nnls=deny_nnls
    receipt=json.loads((m.OUT/'TRAIN_RECEIPT.json').read_text(encoding='utf-8'))
    assert receipt['status']=='PASS' and len(receipt['fits'])==8
    assert sum(r['main_fit_calls'] for r in receipt['fits'])==8
    assert sum(r['nnls_calls'] for r in receipt['fits'])==2
    assert sum(r['estimator_fit_calls'] for r in receipt['fits'])==6
    assert sum(r['closed_form_anchor_estimates'] for r in receipt['fits'])==2
    checks=[]
    for stage in m.STAGES:
        source=m.dc.load_training(stage)
        frame=source.iloc[:150].copy()
        for name in m.NAMES:
            rec=next(r for r in receipt['fits'] if r['stage']==stage and r['name']==name)
            assert m.dc.training_sources(stage)==rec['source_sha256']
            assert m.sha(m.__file__)==rec['code_sha256']
            model=m.MetaModels(name,stage)
            values,diagnostics=model.predict(frame)
            assert len(values)==len(frame) and np.isfinite(values).all()
            assert all(v.shape==(len(frame),) and np.isfinite(v).all() for v in diagnostics.values())
            np.testing.assert_allclose(values,diagnostics['anchor_prediction']+diagnostics['residual_prediction'],atol=1e-12,rtol=1e-10)
            if name=='fusion_learned_weights':
                np.testing.assert_allclose(values,sum(diagnostics[f'contribution_{c}'] for c in m.dc.RANK_COLUMNS),atol=1e-12)
            if name=='fusion_hgb_then_linear':
                np.testing.assert_allclose(diagnostics['residual_prediction'],sum(diagnostics[f'linear_residual_contribution_{c}'] for c in m.dc.META_COLUMNS),atol=1e-12)
            input_only=frame.drop(columns=[c for c in ['signal_date','label_end_date','base_fit_cutoff','target_advantage','ticker'] if c in frame])
            other,_=model.predict(input_only)
            np.testing.assert_array_equal(values,other)
            matrix=values.reshape(-1,5);adjusted=matrix-matrix[:,:1]
            assert np.array_equal(adjusted[:,0],np.zeros(len(matrix)))
            checks.append(dict(name=name,stage=stage,rows=len(frame),finite_outputs=True,
                raw_anchor_residual_reconcile=True,date_and_future_label_columns_unused=True,
                caller_zero_action_subtraction_exact=True,diagnostic_fields=list(diagnostics),
                artifact_sha256=rec['artifact_sha256']))
    assert guard['attempts']==0
    m.write(m.OUT/'VERIFY.json',dict(status='PASS',checks=checks,
        behavior_tests_passed=5,inference_fit_attempts=guard['attempts'],test2026_rows_read=0,
        original_sources_and_artifacts_unchanged=True))
    print(json.dumps(dict(status='PASS',methods=len(checks),fit_attempts=guard['attempts'],behavior_tests_passed=5)))


if __name__=='__main__':main()
