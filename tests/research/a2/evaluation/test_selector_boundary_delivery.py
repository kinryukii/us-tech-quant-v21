"""Synthetic C12 delivery gates and production routing; no real outcomes or fits."""
from __future__ import annotations
import copy
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
from scripts.research.a2.evaluation import selector_boundary_delivery as sut


def setup_gate(monkeypatch, complete=None):
    root=Path('D:/SYNTHETIC_C12_NO_FILES')
    dag=sut.controller.physical_dag()
    ledger=dict(design_sha256='design',hard_cap=380,active_ceiling=122,scientific_retry=0,
        slots={s['id']:{**s,'status':'BLOCKED','charged':False,'backend_entered':False} for s in dag['active_slots']})
    statuses={cid:dict(status='FAILED_REQUIRED_OUTER_COMPONENT',year=2025) for cid in sut.ev.ROLES}
    caps={p:dict(candidate_id=cid,outer_year=2025,selected_capacity=None,outer_y_values_read=0)
          for p,cid in zip(sut.controller.est.PARADIGMS,sut.ev.ROLES)}
    ids=[]
    if complete is not None:
        p=sut.controller.est.PARADIGMS[complete];cid=sut.ev.ROLES[complete];ids=[cid]
        caps[p]['selected_capacity']='LOW'
        statuses[cid]=dict(status='COMPLETE_2025_ONLY',year=2025,selected_capacity='LOW',
            complete_components=[q if p=='QUANTILE_HGB' else seed for seed,q in sut.controller.components(p)])
        slotids=['SCALER_2025-01-01']+[f'OUTER_{p}_{seed}_{q}' for seed,q in sut.controller.components(p)]
        for sid in slotids:
            ledger['slots'][sid].update(status='COMPLETE',charged=True,backend_entered=True,
                selected_capacity='LOW',model=dict(path=str(root/'models'/f'{sid}.joblib'),sha256='model'))
    final=dict(status='FINAL_PIPELINES_FROZEN',research_id=sut.ev.RESEARCH_ID,design_sha256='design',
        all_training_terminal=True,capacity_selection_complete=True,roles=list(sut.ev.ROLES),
        role_statuses={cid:'PARTIAL_INPUT_BLOCKED' if cid in ids else 'FAILED' for cid in sut.ev.ROLES},
        outer_pipeline_status=statuses,fit_ledger_sha256='ledger',outer_labels_read=0,
        capacity_receipts={p:dict(path=str(root/f'{p}.json'),sha256='cap') for p in caps})
    assembly=dict(status='C12_PARTIAL_2025_ASSEMBLY',design_freeze_sha256='design',
        final_pipelines_freeze=dict(path=str(root/'FINAL_PIPELINES_FREEZE.json'),sha256='final'),
        outer_pipeline_status=statuses,complete_common_732_candidates=[],forecast2026_rows=0,
        failed_or_untestable={cid:sut.controller.GAP for cid in sut.ev.ROLES},complete_2025_candidates=ids,
        score_paths={cid:dict(path=str(root/'panel.parquet'),sha256='score') for cid in ids},
        diagnostic_paths={cid:{k:dict(path=str(root/f'{k}.parquet'),sha256='diag') for k in ('pairs','matched')} for cid in ids})
    d=dict(sources={str(Path(sut.__file__)):'source'},physical_dag=dict(path=str(root/'DAG.json'),sha256='dag'))
    objects={root/'SCORE_ASSEMBLY.json':assembly,root/'FINAL_PIPELINES_FREEZE.json':final,
        root/'FIT_LEDGER.json':ledger,root/'DAG.json':dag,**{root/f'{p}.json':cp for p,cp in caps.items()}}
    def digest(path):
        return 'source' if Path(path)==Path(sut.__file__) else {'DESIGN_FREEZE.json':'design','FIT_LEDGER.json':'ledger'}.get(Path(path).name,'unused')
    monkeypatch.setattr(sut,'sha',digest);monkeypatch.setattr(sut,'readj',lambda p:objects[Path(p)])
    monkeypatch.setattr(sut,'pin',lambda item:Path(item['path']))
    return root,d,assembly,final,ledger,caps


@pytest.mark.parametrize('index',[None,0,5,7,8])
def test_real_component_key_contract_all_required(monkeypatch,index):
    root,d,a,f,l,c=setup_gate(monkeypatch,index)
    actual=sut.terminal_receipts(root,d)
    assert actual==(a,f,l,c)


@pytest.mark.parametrize('field,value', [('status','TRAINING'),('all_training_terminal',False),
    ('capacity_selection_complete',False),('outer_labels_read',1),('design_sha256','changed'),
    ('roles',[]),('role_statuses',{})])
def test_final_gate_rejects_before_outcome_read(monkeypatch,field,value):
    root,d,a,f,l,c=setup_gate(monkeypatch);f[field]=value
    monkeypatch.setattr(sut,'pre2026',lambda *args,**kwargs:pytest.fail('OUTCOME_READER_NOT_ALLOWED'))
    with pytest.raises(ValueError,match='FINAL_PIPELINES_FREEZE'):
        sut.terminal_receipts(root,d)


def test_receipt_pin_wrong_path_and_delivery_source_drift(monkeypatch):
    root,d,a,f,l,c=setup_gate(monkeypatch)
    d['sources'][str(Path(sut.__file__))]='drift'
    with pytest.raises(ValueError,match='SOURCE_NOT_FROZEN'):sut.terminal_receipts(root,d)
    d['sources'][str(Path(sut.__file__))]='source'
    a['final_pipelines_freeze']['path']=str(root/'OTHER.json')
    with pytest.raises(ValueError,match='EXACT_FINAL_PIPELINE_PATH'):sut.terminal_receipts(root,d)


def test_unresolved_reservation_refuses_final_delivery(monkeypatch):
    root,d,a,f,l,c=setup_gate(monkeypatch)
    s=next(iter(l['slots'].values()));s.update(status='RESERVED',charged=True)
    with pytest.raises(ValueError,match='ALL_FIT_SLOTS_TERMINAL'):sut.terminal_receipts(root,d)


def test_complete_panel_cannot_hide_missing_seed_or_fit(monkeypatch):
    root,d,a,f,l,c=setup_gate(monkeypatch,5)
    a['outer_pipeline_status'][sut.ev.ROLES[5]]['complete_components'].pop()
    with pytest.raises(ValueError,match='ALL_REQUIRED_SEEDS_QUANTILES'):sut.terminal_receipts(root,d)
    root,d,a,f,l,c=setup_gate(monkeypatch,1)
    s=l['slots']['OUTER_RIDGE_20260928_None'];s.update(status='BLOCKED',charged=False,backend_entered=False)
    with pytest.raises(ValueError,match='EVERY_OUTER_FIT'):sut.terminal_receipts(root,d)


def test_complete_model_byte_pins_required(monkeypatch):
    root,d,a,f,l,c=setup_gate(monkeypatch,1)
    def verify(item):
        if str(item['path']).endswith('.joblib'):raise ValueError('PIN_CHANGED')
        return Path(item['path'])
    monkeypatch.setattr(sut,'pin',verify)
    with pytest.raises(ValueError,match='PIN_CHANGED'):sut.terminal_receipts(root,d)


def test_backend_reservation_failure_counts_are_distinct(monkeypatch):
    root,d,a,f,l,c=setup_gate(monkeypatch)
    rows=list(l['slots'].values())
    rows[0].update(status='COMPLETE',charged=True,backend_entered=True)
    rows[3].update(status='FAILED',charged=True,backend_entered=True)
    rows[4].update(status='FAILED',charged=True,backend_entered=False)
    counts=sut.ledger_counts(l)
    assert counts['actual_backend_calls']==2 and counts['charged_reservations']==3
    assert counts['failed_fit_calls']==1 and counts['failed_slots']==2
    assert counts['scaler_calls']==1 and counts['estimator_calls']==1
    assert counts['blocked_nominal_slots_are_not_reservations'] is True


def test_label_end_footer_proved_before_target_projection(monkeypatch):
    calls=[];monkeypatch.setattr(sut,'pin',lambda b:Path('D:/fake.parquet'))
    def prove(*args,**kwargs):calls.append('footer');raise ValueError('FUTURE_LABEL_FOOTER')
    monkeypatch.setattr(sut.shared,'prove_label_boundary',prove)
    monkeypatch.setattr(sut,'pre2026',lambda *args,**kwargs:pytest.fail('TARGET_BODY_READ_BEFORE_FOOTER'))
    with pytest.raises(ValueError,match='FUTURE_LABEL_FOOTER'):sut.reference_labels({'raw_score':{}})
    assert calls==['footer']


def test_real_reader_refuses_future_clock_before_projection(tmp_path,monkeypatch):
    path=tmp_path/'synthetic_future_clock.parquet'
    pd.DataFrame({'signal_date':pd.to_datetime(['2026-01-02']),'target':[999.]}).to_parquet(path,index=False)
    monkeypatch.setattr(pq,'read_table',lambda *args,**kwargs:pytest.fail('LOCKED_BODY_READ'))
    with pytest.raises(ValueError,match='PHYSICAL_PRE2026_BOUNDARY'):
        sut.pre2026(path,['target'],'signal_date')


def test_exact_full_u_and_unknown_pair_tail_preservation(monkeypatch):
    ref=pd.DataFrame({'signal_date':pd.to_datetime(['2025-01-03','2025-01-03']),
        'security_uid':['C','I'],'ticker':['C','I'],'U_t_fingerprint':['U','U'],'target':[np.nan,.01]})
    geometry=pd.DataFrame({'signal_date':pd.to_datetime(['2025-01-03']),'challenger_uid':['C'],'incumbent_uid':['I']})
    assert np.isnan(sut.pair_truth(ref,geometry)[0])
    geometry.loc[0,'challenger_uid']='UNKNOWN'
    with pytest.raises(ValueError,match='PAIR_UID'):sut.pair_truth(ref,geometry)
    panel=ref.drop(columns='target').assign(rank=[1,2],candidate_id='R',score=[2.,1.])
    monkeypatch.setattr(sut,'pin',lambda b:Path('D:/fake.parquet'));monkeypatch.setattr(sut,'pre2026',lambda *a:panel)
    assert len(sut.bound_2025_panel(ref,{},'R'))==2
    panel=panel.iloc[:1]
    with pytest.raises(ValueError,match='FULL_U_IDENTITY'):sut.bound_2025_panel(ref,{},'R')


def test_empty_matched_parquet_is_legal_pre2026(tmp_path):
    path=tmp_path/'synthetic_empty_matched.parquet'
    pd.DataFrame(columns=[*sut.controller.pairs.PAIR_KEYS,'predicted_edge']).to_parquet(path,index=False)
    assert sut.matched_reader(dict(path=str(path),sha256=sut.sha(path))).empty


def test_duplicate_and_unfrozen_pipeline_stop_before_any_y(monkeypatch):
    root=Path('D:/fake_run');monkeypatch.setattr(sut,'safe_d',lambda x:Path(x))
    monkeypatch.setattr(sut,'assert_safe_output_path',lambda *a,**k:None)
    monkeypatch.setattr(sut.controller,'checked',lambda r:({'results_directory':'D:/fake_results'},{},{}))
    monkeypatch.setattr(sut,'pre2026',lambda *a,**k:pytest.fail('BODY_READ_BEFORE_GATE'))
    monkeypatch.setattr(sut,'new_outputs',lambda *a:(_ for _ in ()).throw(FileExistsError('PRESERVE_PARTIAL')))
    with pytest.raises(FileExistsError,match='PRESERVE_PARTIAL'):sut.run(root)
    monkeypatch.setattr(sut,'new_outputs',lambda *a:None)
    monkeypatch.setattr(sut,'terminal_receipts',lambda *a:(_ for _ in ()).throw(ValueError('NOT_FROZEN')))
    with pytest.raises(ValueError,match='NOT_FROZEN'):sut.run(root)


def test_synthetic_production_delivery_smoke(tmp_path,monkeypatch):
    root=tmp_path/'run';result=tmp_path/'results';root.mkdir();result.mkdir()
    dates=pd.DatetimeIndex(np.concatenate([pd.bdate_range(f'{y}-01-02',periods=n).to_numpy()
                                          for y,n in ((2023,250),(2024,252),(2025,250))]))
    clock=pd.DataFrame({'signal_date':dates,'included':np.arange(752)<732})
    ref=pd.DataFrame([dict(signal_date=day,security_uid=f'UID{rank:02d}',ticker=f'S{rank:02d}',
        U_t_fingerprint='SYNTHETIC_U40',raw_rank=rank,raw_score=-rank,target=.0001*rank,
        label_end_date=day+pd.Timedelta(days=1)) for day in dates for rank in range(1,41)])
    tail=ref.signal_date.isin(dates[732:]);ref.loc[tail,'target']=np.nan;ref.loc[tail,'label_end_date']=pd.NaT
    ref=ref.sort_values(sut.KEY).reset_index(drop=True);r2025=ref.loc[ref.signal_date.dt.year.eq(2025)].reset_index(drop=True)
    geom=sut.controller.pairs.geometry(ref);g2025=geom.loc[geom.signal_date.dt.year.eq(2025)].reset_index(drop=True)
    cid=sut.ev.ROLES[1]
    panel=r2025[sut.KEY+['ticker','U_t_fingerprint']].copy()
    panel['rank']=r2025.raw_rank.to_numpy();panel['score']=-r2025.raw_rank.to_numpy(float)
    panel['candidate_id']=cid
    pp=g2025.assign(prediction_0=0.)
    matched=pd.DataFrame(columns=[*sut.controller.pairs.PAIR_KEYS,'predicted_edge'])
    oldids=[f'OLD_{i}' for i in range(147)]
    old=pd.DataFrame(np.zeros((732,147)),columns=oldids);old.insert(0,'signal_date',dates[:732])
    legacy=dict(numeric_ids=oldids,exposure_ids=[f'EXPO_{i}' for i in range(169)],
        failed_or_untestable={f'FAILED_{i}':'OLD' for i in range(22)},
        **{k:dict(path=str(root/f'{k}.mock'),sha256='fake') for k in ('design','assembly','evidence','clock','edge')})
    design=dict(sources={},evaluation=dict(legacy=legacy,bootstrap={}),pair_key_sha256=sut.controller.pairs.pair_key_sha256(geom))
    _,_,a,f,ledger,caps=setup_gate(monkeypatch)
    a['complete_2025_candidates']=[cid];a['score_paths']={cid:dict(path=str(root/'panel.mock'),sha256='fake')}
    a['diagnostic_paths']={cid:{k:dict(path=str(root/f'{k}.mock'),sha256='fake') for k in ('pairs','matched')}}
    a['outer_pipeline_status'][cid]=dict(status='COMPLETE_2025_ONLY',year=2025)
    f.update(design_sha256='b'*64,role_statuses={r:'PARTIAL_INPUT_BLOCKED' for r in sut.ev.ROLES})
    pairreceipt=dict(pairs=dict(path=str(root/'geometry.mock'),sha256='fake'),pairs_count=150400,
        pair_key_sha256=design['pair_key_sha256'])
    monkeypatch.setattr(sut,'sha',lambda p:'constant');monkeypatch.setattr(sut,'pin',lambda b:Path(b['path']))
    monkeypatch.setattr(sut,'safe_d',lambda p:Path(p));monkeypatch.setattr(sut,'assert_safe_output_path',lambda *a,**k:None)
    def fresh(paths,stage):
        for p in paths:
            if p.exists():raise FileExistsError('DUPLICATE')
            p.parent.mkdir(parents=True,exist_ok=True)
    monkeypatch.setattr(sut,'new_outputs',fresh)
    monkeypatch.setattr(sut.controller,'checked',lambda r:({'results_directory':str(result)},design,pairreceipt))
    monkeypatch.setattr(sut,'terminal_receipts',lambda *a:(a_value,f,ledger,caps));a_value=a
    monkeypatch.setattr(sut.ev,'validate_legacy_metadata',lambda *a:None)
    monkeypatch.setattr(sut,'readj',lambda p:{})
    monkeypatch.setattr(sut,'reference_labels',lambda d:ref)
    frames={'clock.mock':clock,'edge.mock':old,'geometry.mock':geom,'panel.mock':panel,'pairs.mock':pp,'matched.mock':matched}
    monkeypatch.setattr(sut,'pre2026',lambda path,cols,c:frames[path.name][cols].copy())
    monkeypatch.setattr(sut,'matched_reader',lambda item:matched.copy())
    seen=[]
    def statistics(legacy_edges,new,positions,calendar,rule,ids,failed):
        seen.append((len(legacy_edges),len(new.columns),len(positions),len(calendar)))
        assert list(legacy_edges)==oldids and new.empty
        tests=[dict(candidate_id=r,supported=False,pooled_edge=None) for r in sut.ev.ROLES]
        return legacy_edges,tests,dict(critical_max_t=3.1,legacy_critical_max_t=3.1),np.array([3.1,3.1])
    monkeypatch.setattr(sut.ev,'statistics',statistics)
    def write(path,value):path.write_text(__import__('json').dumps(value,default=str),encoding='utf-8')
    monkeypatch.setattr(sut,'put',write);monkeypatch.setattr(sut,'putj',write)
    from scripts.maintenance import audit_repo_size_r1
    monkeypatch.setattr(audit_repo_size_r1,'audit',lambda *a:dict(violations=[],accounting_complete=True,hard_limit_passed=True))
    evidence=sut.run(root)
    assert seen==[(732,0,732,752)] and evidence['numeric_complete_series']==147
    assert evidence['exposure_namespace']==178 and evidence['supported']==[]
    assert evidence['strict_PIT_promotion_eligible'] is False and evidence['outcome2026_reads']==0
    assert evidence['C6A']=='BLOCKED_INPUT' and evidence['C8']=='BLOCKED_DEPENDENCY'
    dd=pd.read_parquet(root/'diagnostics/selector_evidence/PARTIAL_DAILY_DIAGNOSTICS.parquet')
    assert len(dd)==250 and dd.common_mature_date.sum()==230
    assert dd.loc[~dd.common_mature_date,'replacement_edge'].isna().all()
    primary=pd.read_parquet(root/'diagnostics/selector_evidence/PRIMARY_DAILY_EDGE.parquet')
    assert len(primary)==732 and len(primary.columns)==148
    assert (root/'DELIVERY_COMPLETE.json').exists()
    report=(result/'FINAL_REPORT.md').read_text(encoding='utf-8')
    assert all(f'{n}. **' in report for n in range(1,24))
    assert 'C12_PARTIAL_INPUT_BLOCKED' in report and '不是统计上的负结果' not in report
    with pytest.raises(FileExistsError,match='DUPLICATE'):sut.run(root)

def test_empty_matched_missing_schema_and_nonempty_future_fail(tmp_path,monkeypatch):
    empty=tmp_path/'synthetic_bad_empty.parquet'
    pd.DataFrame(columns=['not_a_pair']).to_parquet(empty,index=False)
    with pytest.raises(ValueError,match='EMPTY_MATCHED_SCHEMA'):
        sut.matched_reader(dict(path=str(empty),sha256=sut.sha(empty)))
    future=tmp_path/'synthetic_future_matched.parquet'
    pd.DataFrame([dict(signal_date=pd.Timestamp('2026-01-02'),challenger_uid='C',incumbent_uid='I',
        challenger_raw_rank=21,incumbent_raw_rank=11,predicted_edge=.1)]).to_parquet(future,index=False)
    binding=dict(path=str(future),sha256=sut.sha(future))
    monkeypatch.setattr(pq,'read_table',lambda *a,**k:pytest.fail('FUTURE_MATCH_BODY_READ'))
    with pytest.raises(ValueError,match='PHYSICAL_PRE2026_BOUNDARY'):sut.matched_reader(binding)
