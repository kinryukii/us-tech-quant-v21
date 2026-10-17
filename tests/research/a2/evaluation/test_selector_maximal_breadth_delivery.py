"""C14 delivery contract, immutable checkpoint and cached-oracle synthetic tests.

All fixtures live in approved external pytest scratch. No research outcomes,
real labels, learners, covariance matrices or matching solver are opened.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
from scripts.research.a2.evaluation import selector_maximal_breadth_delivery as sut


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def pin(path):
    return {'path': str(path), 'sha256': sut.sha(path)}


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    root = tmp_path/'run'; root.mkdir(); results=tmp_path/'results'; results.mkdir()
    write_json(root/'DESIGN_FREEZE.json', {'synthetic': True})
    write_json(root/'FIT_LEDGER.json', {'slots': {'N': {'status':'COMPLETE','entered':1,'kind':'ESTIMATOR'}}})
    write_json(root/'SOLVE_LEDGER.json', {'requests':['ORACLE|2024-01-02','ORACLE|2025-01-02']})
    a = dict(all_training_terminal=True, capacity_selection_complete=True,
        design_freeze_sha256=sut.sha(root/'DESIGN_FREEZE.json'),
        fit_ledger_sha256=sut.sha(root/'FIT_LEDGER.json'),complete_candidates=[],
        failed_or_untestable={},panels={},native_pair_predictions={})
    write_json(root/'ML_ASSEMBLY.json',a)
    raw_path=root/'raw.parquet'; pd.DataFrame({'signal_date':pd.to_datetime(['2024-01-02','2025-01-02'])}).to_parquet(raw_path,index=False)
    oracle_path=root/'cached_oracle.parquet'; dates=pd.to_datetime(['2024-01-02','2025-01-02'])
    pd.DataFrame({'signal_date':dates,'oracle_utility':[.02,.01]}).to_parquet(oracle_path,index=False)
    write_json(root/'ORACLE_RECEIPT.json',dict(design_sha256=sut.sha(root/'DESIGN_FREEZE.json'),pair_key_sha256='pair',artifact=pin(oracle_path)))
    cfg=dict(results_directory=str(results),cache_directory=str(tmp_path/'cache'))
    d=dict(roles=[],blocked_roles={},contrasts=[],role_bindings=[],sources={},coverage_plan={},
        evaluation=dict(legacy=dict(clock={'path':'CLOCK'},edge={'path':'EDGE'},numeric_ids=['OLD']),bootstrap={},new_specs=[]))
    q=dict(pair_key_sha256='pair',artifacts={'raw_current':pin(raw_path)})
    monkeypatch.setattr(sut.ctl,'checked',lambda _: (cfg,d,q))
    monkeypatch.setattr(sut,'assert_safe_output_path',lambda *a,**k: None)
    monkeypatch.setattr(sut.ctl,'pin',lambda ref: Path(ref['path']))
    monkeypatch.setattr(sut.ev,'validate_design',lambda _: True)
    monkeypatch.setattr(sut.ev,'validate_final_pipeline_gate',lambda *a: True)
    monkeypatch.setattr(sut.risk,'readiness',lambda: {'status':'WAITING_B_R5_NUMERIC_BANK','numeric_reads':0,'new_fits':0})
    monkeypatch.setattr(sut.old_delivery,'reference_labels',lambda _: pd.DataFrame())
    monkeypatch.setattr(sut,'pre2026',lambda path,*a: pd.DataFrame({'signal_date':dates, **({'included':[True,True]} if str(path)=='CLOCK' else {'OLD':[0.,0.]})}))
    monkeypatch.setattr(sut.ctl,'label_pairs',lambda *a,**k: (pd.DataFrame({'signal_date':dates}),np.array([0.,0.]),np.zeros((2,4)),dates,{'synthetic':True}))
    monkeypatch.setattr(sut.ctl.pairs,'pair_key_sha256',lambda _: 'pair')
    monkeypatch.setattr(sut.ctl,'decode_days',lambda *a,**k: (_ for _ in ()).throw(AssertionError('ORACLE_RE_SOLVED')))
    monkeypatch.setattr(sut.ctl,'flush_solve_ledger',lambda _: None)
    monkeypatch.setattr(sut.ev,'statistics',lambda *a,**k: ([],{'numeric_complete_series':147,'exposure_namespace':321},np.array([1.])))
    monkeypatch.setattr(sut.ev,'training_coverage_audit',lambda *a: {})
    monkeypatch.setattr(sut.ev,'render_report',lambda _: 'Synthetic report; no real outcomes')
    def table(path,frame):
        path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); frame.to_parquet(path,index=False); return pin(path)
    monkeypatch.setattr(sut,'table',table)
    return root,cfg,d,q,a


def test_completed_delivery_reuses_pinned_outputs_without_reopening_labels(delivery,monkeypatch):
    root,cfg,d,q,a=delivery
    artifact=root/'existing.json';write_json(artifact,{'synthetic':True})
    done={'status':'DONE','outputs':{'existing':pin(artifact)}};write_json(root/'DELIVERY_COMPLETE.json',done)
    seen=[];monkeypatch.setattr(sut.ctl,'pin',lambda r: seen.append(r) or Path(r['path']))
    monkeypatch.setattr(sut.old_delivery,'reference_labels',lambda _: (_ for _ in ()).throw(AssertionError('LABEL_REOPEN')))
    assert sut.finish(root)==done and seen==[pin(artifact)]


@pytest.mark.parametrize('case',['nonterminal','capacity','freeze_hash','ledger_hash','unresolved'])
def test_outcome_read_rejected_until_all_terminal_receipts_bind(delivery,monkeypatch,case):
    root,cfg,d,q,a=delivery
    if case=='nonterminal':a['all_training_terminal']=False
    elif case=='capacity':a['capacity_selection_complete']=False
    elif case=='freeze_hash':a['design_freeze_sha256']='x'*64
    elif case=='ledger_hash':a['fit_ledger_sha256']='x'*64
    else:
        write_json(root/'FIT_LEDGER.json',{'slots':{'N':{'status':'STARTED','entered':1}}})
        a['fit_ledger_sha256']=sut.sha(root/'FIT_LEDGER.json')
    write_json(root/'ML_ASSEMBLY.json',a)
    monkeypatch.setattr(sut.old_delivery,'reference_labels',lambda _: (_ for _ in ()).throw(AssertionError('LABEL_TOO_EARLY')))
    with pytest.raises(ValueError,match='TERMINAL|UNRESOLVED'):sut.finish(root)


def test_independent_final_pipeline_gate_precedes_label_projection(delivery,monkeypatch):
    root,*_=delivery
    def refuse(*a):raise ValueError('GATE_REJECTED')
    monkeypatch.setattr(sut.ev,'validate_final_pipeline_gate',refuse)
    monkeypatch.setattr(sut.old_delivery,'reference_labels',lambda _: (_ for _ in ()).throw(AssertionError('LABEL_TOO_EARLY')))
    with pytest.raises(ValueError,match='GATE_REJECTED'):sut.finish(root)


def test_cached_oracle_no_new_solver_call_and_waiting_risk_not_claimed_executed(delivery):
    root,cfg,d,q,a=delivery
    done=sut.finish(root)
    assert done['risk_queue_completed'] is False and done['strict_PIT_promotion_eligible'] is False
    assert done['status']=='C14_WAITING_B_R5_NUMERIC_BANK'
    assert done['fit_counts']['solver_requests']==2
    assert done['fit_counts']['shared_risk_new_estimation_by_C']==0
    assert sut.finish(root)==done


@pytest.mark.parametrize('field,value',[('design_sha256','x'*64),('pair_key_sha256','bad')])
def test_oracle_reuse_requires_exact_design_and_pair_identity(delivery,field,value):
    root,*_=delivery
    r=json.loads((root/'ORACLE_RECEIPT.json').read_text());r[field]=value;write_json(root/'ORACLE_RECEIPT.json',r)
    with pytest.raises(ValueError,match='EXACT_ORACLE_REUSE'):sut.finish(root)


def test_existing_metadata_output_never_replaced_with_different_content(tmp_path,monkeypatch):
    monkeypatch.setattr(sut,'assert_safe_output_path',lambda *a,**k: None)
    path=tmp_path/'receipt.json';sut.put(path,{'x':1});original=path.read_bytes()
    sut.put(path,{'x':1});assert path.read_bytes()==original
    with pytest.raises(ValueError,match='PRESERVE_DIFFERENT'):sut.put(path,{'x':2})
    assert path.read_bytes()==original


def test_resume_reuses_frozen_branch_snapshot_when_bank_publication_changes(delivery,monkeypatch):
    root,*_=delivery
    old=sut.old_delivery.reference_labels
    monkeypatch.setattr(sut.old_delivery,'reference_labels',lambda _: (_ for _ in ()).throw(RuntimeError('SYNTHETIC_ENGINEERING_STOP')))
    with pytest.raises(RuntimeError,match='SYNTHETIC_ENGINEERING_STOP'):sut.finish(root)
    before=(root/'SCORE_ASSEMBLY.json').read_bytes()
    monkeypatch.setattr(sut.old_delivery,'reference_labels',old)
    monkeypatch.setattr(sut.risk,'readiness',lambda: (_ for _ in ()).throw(AssertionError('REFRESH_AFTER_FINAL_GATE')))
    done=sut.finish(root)
    assert (root/'SCORE_ASSEMBLY.json').read_bytes()==before
    assert done['status']=='C14_WAITING_B_R5_NUMERIC_BANK'


def test_main_does_not_restart_terminal_ml_when_only_delivery_needs_resume(delivery,monkeypatch):
    root,*_=delivery
    write_json(root/'ML_DELIVERY_COMPLETE.json',{'synthetic':True})
    monkeypatch.setattr(sut.ctl,'run',lambda _: (_ for _ in ()).throw(AssertionError('ML_RESTART')))
    monkeypatch.setattr(sut,'finish',lambda _: {'status':'SYNTHETIC','outputs':{'report':{'path':'synthetic_report'}}})
    monkeypatch.setattr('sys.argv',['delivery','--run',str(root)])
    sut.main()
