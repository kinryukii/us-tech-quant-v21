"""Synthetic C14 post-fit recovery; no real labels, models or solver calls."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.evaluation import selector_maximal_breadth_delivery as sut
from test_selector_maximal_breadth_delivery import delivery, pin, write_json


@pytest.mark.parametrize('rule,kind,decision',[
    ('U0_POINT_GT0','edge','U0'),('U1_PROB_GT_0_5','probability','U1'),
    ('U2_Q10_GT0_MATCH_Q50','quantile','U2'),
    ('U3_MU_MINUS_SIGMA_GT0_MATCH_MU','gaussian','U3')])
def test_terminal_delivery_passes_native_frozen_diagnostic_coordinate(delivery,monkeypatch,rule,kind,decision):
    root,cfg,d,q,a=delivery; cid='C14_FULL_RIDGE'; dates=pd.to_datetime(['2024-01-02','2025-01-02'])
    panel=root/'panel.parquet'
    pd.DataFrame(dict(signal_date=dates,security_uid=['S','S'],ticker=['S','S'],
        U_t_fingerprint=['U','U'],rank=[1,1],score=[1.,1.],candidate_id=[cid,cid])).to_parquet(panel,index=False)
    reader=sut.pre2026
    monkeypatch.setattr(sut,'pre2026',lambda path,*a: pd.read_parquet(path,columns=a[0]) if Path(path)==panel else reader(path,*a))
    geometry=pd.DataFrame(dict(signal_date=dates,challenger_uid=['C','C'],incumbent_uid=['I','I'],
        challenger_raw_rank=[21,21],incumbent_raw_rank=[11,11]))
    monkeypatch.setattr(sut.ctl,'label_pairs',lambda *a,**k: (geometry,np.array([0.,0.]),np.zeros((2,4)),dates,{'synthetic':True}))
    native=root/'native.parquet'
    pd.DataFrame(dict(**geometry.to_dict('list'),point=[.1,.2],prob=[.7,.8],q10=[.01,.02],
        q50=[.1,.2],q90=[.3,.4],mu=[.1,.2],sigma=[.01,.02])).to_parquet(native,index=False)
    a.update(complete_candidates=[cid],panels={cid:pin(panel)},
        native_pair_predictions={cid:{**pin(native),'matching_path':'synthetic','matching_sha256':'synthetic'}})
    write_json(root/'ML_ASSEMBLY.json',a); d['roles']=[cid]; d['role_bindings']=[dict(candidate_id=cid,output_rule=rule)]
    monkeypatch.setattr(sut.ev,'membership_diagnostics',lambda *a,**k: pd.DataFrame(dict(signal_date=dates,
        candidate_id=[cid,cid],year=[2024,2025],replacement_edge=[0.,0.],raw_overlap=[1.,1.],
        replacement_count=[0,0],membership_turnover=[0.,0.])))
    monkeypatch.setattr(sut.old_delivery,'matched_reader',lambda _: pd.DataFrame({'signal_date':dates}))
    calls=[]
    def diagnostic(*args,**kw):
        assert kw['kind']==kind and kw['decision']==decision
        assert (kw['native_probability'] is not None)==(kind=='gaussian')
        calls.append(kw); return pd.DataFrame({'synthetic':[True]}),pd.DataFrame(),pd.DataFrame()
    monkeypatch.setattr(sut.ev,'pair_diagnostics',diagnostic)
    monkeypatch.setattr(sut.ctl,'decode',lambda *a,**k: (_ for _ in ()).throw(AssertionError('ORACLE_RE_SOLVED')))
    before=(root/'ORACLE_RECEIPT.json').read_bytes(); ledger=(root/'FIT_LEDGER.json').read_bytes()
    sut.finish(root)
    assert len(calls)==1 and (root/'ORACLE_RECEIPT.json').read_bytes()==before
    assert (root/'FIT_LEDGER.json').read_bytes()==ledger


@pytest.fixture
def correction(tmp_path,monkeypatch):
    ctl=sut.ctl; run=tmp_path/'run'; repo=tmp_path/'repo'; run.mkdir()
    monkeypatch.setattr(ctl,'REPO',repo); monkeypatch.setattr(ctl,'assert_safe_output_path',lambda *a,**k: None)
    monkeypatch.setattr(ctl,'resolve',lambda _: None)
    sources={}; changes={}
    for rel in ['scripts/research/a2/training/selector_maximal_breadth.py',
                'scripts/research/a2/evaluation/selector_maximal_breadth_delivery.py','untouched.py']:
        source=repo/rel; source.parent.mkdir(parents=True,exist_ok=True); source.write_text('original')
        original=sut.sha(source); sources[str(source)]=original
        if rel=='untouched.py': continue
        snap=run/'source_snapshot'/rel; snap.parent.mkdir(parents=True,exist_ok=True); snap.write_bytes(source.read_bytes())
        source.write_text('corrected')
        changes[str(source)]={'original_sha256':original,'corrected_sha256':sut.sha(source),'original_snapshot':pin(snap)}
    write_json(run/'FIT_LEDGER.json',{'slots':{'N':{'status':'COMPLETE'}}})
    write_json(run/'ML_ASSEMBLY.json',{'all_training_terminal':True,'capacity_selection_complete':True})
    for name in ['DESIGN_FREEZE.json','PHYSICAL_DAG.json','SOURCE_CLOSURE_RECEIPT.json','FORMAL_FREEZE_RECEIPT.json',
                 'ML_DELIVERY_COMPLETE.json','SCORE_ASSEMBLY.json']: write_json(run/name,{'synthetic':True})
    write_json(run/'FINAL_PIPELINES_FREEZE.json',{'status':'FINAL_PIPELINES_FROZEN','forecast2026_rows':0,
        'design_sha256':sut.sha(run/'DESIGN_FREEZE.json'),'fit_ledger_sha256':sut.sha(run/'FIT_LEDGER.json'),
        'score_assembly_sha256':sut.sha(run/'SCORE_ASSEMBLY.json')})
    pins={p.name:sut.sha(p) for p in run.glob('*.json')}
    review={'status':'PASS','classification':'POSTFIT_ENGINEERING_ONLY','research_id':ctl.ID,
            'source_changes':changes,'terminal_pins':pins}
    write_json(run/'INDEPENDENT_REVIEW.json',review)
    c={**review,'scientific_parameters_changed':False,'scientific_retry':0,
       'repair_preparation_outcome_reads':0,'independent_review':pin(run/'INDEPENDENT_REVIEW.json')}
    write_json(run/'SOURCE_CORRECTION.json',c)
    return run,{'sources':sources},c,repo


def test_postfit_correction_preserves_original_snapshots_and_exact_other_pins(correction):
    run,d,c,repo=correction; proof=sut.ctl.checked_sources(run,d)
    for source,change in c['source_changes'].items():
        assert proof[source]['original_sha256']==d['sources'][source]
        assert proof[source]['executed_sha256']==change['corrected_sha256']
    assert proof[str(repo/'untouched.py')]==d['sources'][str(repo/'untouched.py')]


@pytest.mark.parametrize('fault',['other_source','corrected_source','snapshot','pending','missing_marker',
    'wrong_pin','review_changed','unreviewed','science','retry','outcome_reads','future','extra_source'])
def test_postfit_correction_rejects_drift_before_any_numeric_projection(correction,fault):
    run,d,c,repo=correction
    if fault=='other_source': (repo/'untouched.py').write_text('tampered')
    elif fault=='corrected_source': Path(next(iter(c['source_changes']))).write_text('tampered')
    elif fault=='snapshot': Path(next(iter(c['source_changes'].values()))['original_snapshot']['path']).write_text('tampered')
    elif fault=='pending':
        write_json(run/'FIT_LEDGER.json',{'slots':{'N':{'status':'STARTED'}}})
        c['terminal_pins']['FIT_LEDGER.json']=sut.sha(run/'FIT_LEDGER.json')
    elif fault=='missing_marker': (run/'ML_DELIVERY_COMPLETE.json').unlink()
    elif fault=='wrong_pin': c['terminal_pins']['DESIGN_FREEZE.json']='0'*64
    elif fault=='review_changed': write_json(run/'INDEPENDENT_REVIEW.json',{'status':'FAIL'})
    elif fault=='unreviewed':
        write_json(run/'INDEPENDENT_REVIEW.json',{'status':'FAIL'})
        c['independent_review']=pin(run/'INDEPENDENT_REVIEW.json')
    elif fault=='science': c['scientific_parameters_changed']=True
    elif fault=='retry': c['scientific_retry']=1
    elif fault=='outcome_reads': c['repair_preparation_outcome_reads']=1
    elif fault=='future':
        gate=json.loads((run/'FINAL_PIPELINES_FREEZE.json').read_text());gate['forecast2026_rows']=1
        write_json(run/'FINAL_PIPELINES_FREEZE.json',gate)
        c['terminal_pins']['FINAL_PIPELINES_FREEZE.json']=sut.sha(run/'FINAL_PIPELINES_FREEZE.json')
    else: c['source_changes'][str(repo/'untouched.py')]=next(iter(c['source_changes'].values()))
    write_json(run/'SOURCE_CORRECTION.json',c)
    with pytest.raises((ValueError,FileNotFoundError)): sut.ctl.checked_sources(run,d)


def test_postfit_source_correction_forbids_training_before_checked_or_runtime(correction,monkeypatch):
    run,*_=correction
    monkeypatch.setattr(sut.ctl,'checked',lambda _: (_ for _ in ()).throw(AssertionError('TRAINING_OPENED')))
    with pytest.raises(ValueError,match='FORBIDS_TRAINING'): sut.ctl.run(run)
