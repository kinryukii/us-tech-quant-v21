"""Synthetic original-membership composition; no actual labels/bank/solver/cache."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import selector_maximal_risk_membership as m


def writej(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,default=str),encoding='utf-8')
    return dict(path=str(path),sha256=m.binding.sha(path))


class FakeJournal:
    def __init__(self,run,dates):
        self.run=run.resolve();self.dates=tuple(d.isoformat() for d in dates);self.calls=[];self.results={};self.identities={};self.failed=set()
        self.roles={r:dict(qualification_ref=dict(sha256='f'*64)) for r in m.CLASSICAL}
    def verify(self):pass
    def pin(self,path,digest):
        assert m.binding.sha(path)==digest
    def read_ref(self,ref,root):
        assert Path(ref['path']).resolve().is_relative_to(root.resolve())
        self.pin(ref['path'],ref['sha256']);return json.loads(Path(ref['path']).read_text(encoding='utf-8'))
    def classical_request(self,token,identity,operation):
        self.calls.append(token)
        if token in self.failed:raise ValueError('CHARGED_WITHOUT_COMPLETE_NO_RETRY')
        if token in self.results:
            assert self.identities[token]==identity;return self.results[token]
        self.identities[token]=copy.deepcopy(identity)
        try:result=operation()
        except Exception:self.failed.add(token);raise
        self.results[token]=copy.deepcopy(result);return result


class FakeInputs:
    def __init__(self,raw,requirements,source_review_ref):
        self.raw=raw;self.requirements=requirements;self.source_review_ref=source_review_ref;self.calls=[];self.bad_gate=None
    def role_gate(self,role):
        dates=sorted(self.raw.signal_date.unique())
        gate=dict(phase='FULL752_NUMERIC_INPUT_QUALIFIED',role=role,family=self.requirements[role]['required_family_method'],
            source_review=self.source_review_ref,full_required_dates_qualified=True,states=[dict(decision_date=d.isoformat()) for d in dates])
        if self.bad_gate==role:gate['states']=gate['states'][:-1]
        return gate
    def get_risk(self,role,day):
        self.calls.append((role,day))
        meta=SimpleNamespace(role=role,family=self.requirements[role]['required_family_method'],decision_asof=m.decision_close(day),
            uids=self.raw.loc[self.raw.signal_date.eq(day),'security_uid'].tolist(),_seal='d'*64,recipe_sha256='e'*64,
            header=dict(method='SYNTHETIC_NATIVE',artifact_ref=dict(path='SYNTHETIC_NEVER_READ',sha256='c'*64),
                        risk_state_id='SYNTHETIC_RISK_ID',cutoff=str(m.decision_close(day)-pd.Timedelta(days=1)),as_of=str(m.decision_close(day))))
        return meta,'SYNTHETIC_PAYLOAD'


@pytest.fixture
def synthetic(tmp_path,monkeypatch):
    run=tmp_path/'C14';run.mkdir();writes={};route_calls=[]
    dates=pd.to_datetime(['2023-01-03','2023-04-03','2023-08-01','2023-10-02','2024-01-03','2024-04-01',
        '2024-08-01','2024-10-01','2025-01-02','2025-04-01','2025-08-01','2025-10-01'])
    monkeypatch.setattr(m,'CALENDAR_DATES',12);monkeypatch.setattr(m,'OUTER_DATES',8)
    raw=pd.DataFrame([dict(signal_date=d,security_uid=f'CUSIP:{i:09}',ticker=f'A{i:02}',U_t_fingerprint='FULL_U',
        raw_rank=i+1,raw_score=float(50-i)) for d in dates for i in range(45)])
    geometry=m.owner.pairs.geometry(raw);future=geometry.loc[geometry.signal_date.dt.year.ge(2024)].reset_index(drop=True)
    q=dict(research_id=m.owner.ID,pair_key_sha256=m.owner.pairs.pair_key_sha256(geometry),
        full_U_keys_sha256=m.owner.content_hash(raw[[*m.owner.KEYS,'U_t_fingerprint','raw_rank']].astype(str).values.tolist()))
    design=dict(research_id=m.owner.ID)
    family=dict(zip(m.CLASSICAL,('LW','OAS','EWMA','SHR_HP','PCA_FACTOR','QQQ_RESIDUAL')));family.update(C14_D02='LW',C14_G1='LW',C14_G4='PCA_FACTOR')
    owners=dict(zip(m.CLASSICAL,('D02','D05','D06','D09','D10','D11')))
    reqs={r:dict(role=r,required_family_method=family[r],required_dates=[d.isoformat() for d in dates],
        solver_requirement=dict(route='CLASSICAL' if r in m.CLASSICAL else 'RAW_IDENTITY' if r=='C14_D02' else 'VETO',existing_owner=owners.get(r,'RAW_IDENTITY' if r=='C14_D02' else r.removeprefix('C14_')))) for r in m.ROLES}
    design['risk']=dict(classical_bindings=[dict(candidate_id=r,family=family[r],existing_rule=owners.get(r,'RAW_IDENTITY')) for r in (*m.CLASSICAL,'C14_D02')],gate_families=dict(G1='LW',G4='PCA_FACTOR'))
    matrix=dict(research_id=m.owner.ID,design_sha256=m.binding.DESIGN_SHA,dag_sha256=m.binding.DAG_SHA,roles=list(reqs.values()))
    native=future.copy();native['point']=.1;native['source_cutoff']=native.signal_date.dt.year.astype(str)+'-01-01'
    native['source_capacity']='LOW';native['source_kind']='MODEL_OOF';native['paradigm']='RIDGE'
    npath=run/'predictions/native_pairs_C14_P01_pre2026.parquet';npath.parent.mkdir();npath.write_bytes(b'SYNTHETIC_NO_REAL_PARQUET')
    nref=dict(path=str(npath),sha256=m.binding.sha(npath),kind='U0_POINT_GT0')
    assembly=dict(status='ML_ASSEMBLY_COMPLETE',research_id=m.owner.ID,design_freeze_sha256=m.binding.DESIGN_SHA,
        pair_key_sha256=q['pair_key_sha256'],full_U_keys_sha256=q['full_U_keys_sha256'],all_training_terminal=True,
        forecast2026_rows=0,complete_candidates=['C14_P01'],native_pair_predictions=dict(C14_P01=nref))
    aref=writej(run/'ML_ASSEMBLY.json',assembly); requests={}
    for day,ix in future.groupby('signal_date',sort=True).indices.items():
        rd=raw.loc[raw.signal_date.eq(day)];g=future.iloc[ix]
        identity=dict(design_sha256=m.binding.DESIGN_SHA,pair_key_sha256=m.owner.pairs.pair_key_sha256(g),candidate_id='C14_P01',
            full_U_keys_sha256=m.owner.content_hash(rd[[*m.owner.KEYS,'raw_rank','U_t_fingerprint']].astype(str).values.tolist()),
            score_sha256=hashlib.sha256(np.full(200,.1,dtype='<f8').tobytes()).hexdigest(),
            eligibility_sha256=hashlib.sha256(np.ones(200,bool).tobytes()).hexdigest())
        row=g.iloc[0].to_dict();row['signal_date']=day.isoformat();row['predicted_edge']=.1
        requests['MAIN|C14_P01|'+day.isoformat()]=dict(status='COMPLETE',charged=1,identity=identity,matching_records=[row],matching_sha256=m.owner.content_hash([row]))
    lref=writej(run/'SOLVE_LEDGER.json',dict(research_id=m.owner.ID,hard_cap=30000,requests=requests))
    monkeypatch.setattr(m.binding,'RUN',run);monkeypatch.setitem(m.transport.BASELINE_HASHES,'SOLVE_LEDGER.json',lref['sha256'])
    paths=(Path(m.__file__),Path(m.owner.__file__),Path(m.transport.__file__),Path(m.binding.__file__),Path(m.rank_owner.__file__),
           Path(m.evidence.__file__),Path(m.event.__file__),Path(m.decision_close.__code__.co_filename))
    review=dict(status='PASS',research_id=m.owner.ID,source_pins={str(p.resolve()):m.binding.sha(p) for p in paths},
        immutable_inputs={'ML_ASSEMBLY.json':aref,'SOLVE_LEDGER.json':lref,'C14_P01_native':nref})
    review_ref=writej(run/'SOURCE_REVIEW.json',review);journal=FakeJournal(run,dates);inputs=FakeInputs(raw,reqs,review_ref)
    original_route=m.binding.classical_route
    def route(req,meta,payload,uids,at):
        role=req['role'];route_calls.append(role)
        if role=='C14_D02':return original_route(req,meta,payload,uids,at)
        assert payload=='SYNTHETIC_PAYLOAD' and req['solver_requirement']['existing_owner'] in m.binding.membership.METHODS
        return dict(chosen_uids=uids[:19]+[uids[20]],receipt=dict(optimizer_solve_calls=1))
    monkeypatch.setattr(m.binding,'classical_route',route)
    monkeypatch.setattr(m.binding,'_consumer_uids',lambda meta:meta.uids)
    monkeypatch.setattr(m.binding,'_numeric_input',lambda meta,payload,uids:(np.eye(45),[meta.uids.index(u) for u in uids]))
    monkeypatch.setattr(m.owner,'project',lambda ref,columns,**kw:native[list(columns)].copy())
    monkeypatch.setattr(m,'assert_safe_output_path',lambda path,**kw:None if Path(path).resolve().is_relative_to(run.resolve()) else pytest.fail('synthetic output only'))
    def table(path,frame):writes[str(path)]=frame.copy();return dict(path=str(path),sha256='a'*64,rows=len(frame))
    monkeypatch.setattr(m.owner,'write_table',table);monkeypatch.setattr(m.owner,'write_json',lambda path,value:writes.update({str(path):copy.deepcopy(value)}))
    def execute():return m.execute_membership(run,design,q,raw,geometry,matrix,inputs.get_risk,journal,review_ref)
    return SimpleNamespace(**locals())


def test_all_fixed_roles_full_u_classical_named_requests_and_veto_no_rematch(synthetic,monkeypatch):
    s=synthetic;loads=[];original=m.json.load
    def count(stream):loads.append(stream.name);return original(stream)
    monkeypatch.setattr(m.json,'load',count)
    result=s.execute()
    assert result['complete_candidates']==list(m.ROLES) and not result['failed_or_untestable']
    assert len(s.journal.calls)==len(m.CLASSICAL)*12 and len(set(s.journal.calls))==72
    assert all(t.startswith('CLASSICAL|') and '|C14_D02|' not in t for t in s.journal.calls)
    assert len(loads)==1 and loads[0].endswith('SOLVE_LEDGER.json')
    for role in m.ROLES:
        panel=s.writes[result['panels'][role]['path']]
        assert len(panel)==len(s.raw) and panel.groupby('signal_date').size().eq(45).all()
        assert panel.groupby('signal_date')['rank'].apply(lambda x:set(x)==set(range(1,46))).all()
    for role in m.VETO:
        panel=s.writes[result['panels'][role]['path']];fallback=panel.loc[panel.signal_date.dt.year.eq(2023)]
        expected=s.raw.loc[s.raw.signal_date.dt.year.eq(2023)]
        assert np.array_equal(fallback.score,expected.raw_score) and np.array_equal(fallback['rank'],expected.raw_rank)
        rows=s.writes[result['predicted_risk'][role]['path']]
        assert rows.learned_prediction.sum()==8 and rows.optimizer_solve_calls.eq(0).all()
    assert not any(r=='C14_D02' for r,d in s.inputs.calls)
    assert result['forecast2026_rows']==result['scientific_retry']==0 and not result['strict_PIT_promotion_eligible']


def test_wrong_cached_score_identity_blocks_only_vetos_and_no_retry(synthetic):
    s=synthetic;path=s.run/'SOLVE_LEDGER.json';ledger=json.loads(path.read_text(encoding='utf-8'))
    next(iter(ledger['requests'].values()))['identity']['score_sha256']='0'*64
    ref=writej(path,ledger);s.review['immutable_inputs']['SOLVE_LEDGER.json']=ref
    m.transport.BASELINE_HASHES['SOLVE_LEDGER.json']=ref['sha256'];s.review_ref.update(writej(s.run/'SOURCE_REVIEW.json',s.review))
    result=s.execute()
    assert result['complete_candidates']==[*m.CLASSICAL,'C14_D02']
    assert set(result['failed_or_untestable'])==set(m.VETO)
    assert all('EXACT_P01_INPUT_IDENTITY_REQUIRED' in r for r in result['failed_or_untestable'].values())
    assert len(s.journal.calls)==72 and not any('scores_pre2026' in p and any(g in p for g in m.VETO) for p in s.writes)


def test_classical_failure_is_typed_independent_roles_continue(synthetic):
    s=synthetic;token='CLASSICAL|C14_D01|'+s.dates[0].isoformat();s.journal.failed.add(token)
    result=s.execute()
    assert set(result['failed_or_untestable'])=={'C14_D01'} and len(result['complete_candidates'])==8
    assert s.journal.calls.count(token)==1 and not any('C14_D01/scores' in p.replace('\\','/') for p in s.writes)


def test_missing_full752_gate_precedes_old_prediction_cache_read(synthetic,monkeypatch):
    s=synthetic;s.inputs.bad_gate='C14_G1';s.inputs.requirements['C14_G4']['required_dates']=[]
    monkeypatch.setattr(m.owner,'project',lambda *a,**kw:pytest.fail('no prediction read without qualified veto'))
    result=s.execute()
    assert set(result['failed_or_untestable'])==set(m.VETO)
    assert 'FULL752_VETO_INPUT_GATE' in result['failed_or_untestable']['C14_G1']


def test_source_review_failure_precedes_any_risk_prediction_or_solver(synthetic,monkeypatch):
    s=synthetic;s.review['source_pins'].pop(str(Path(m.__file__).resolve()))
    s.review_ref.update(writej(s.run/'SOURCE_REVIEW.json',s.review))
    monkeypatch.setattr(m.owner,'project',lambda *a,**kw:pytest.fail('prediction read before source closure'))
    with pytest.raises(ValueError,match='CLOSURE_INCOMPLETE'):s.execute()
    assert not s.journal.calls and not s.inputs.calls and not s.writes


def test_p01_cache_physical_change_after_first_read_fails_closed(synthetic):
    s=synthetic;reader=m._p01_reader(s.run,s.q,s.geometry,s.review);day=s.dates[4];rd=s.raw.loc[s.raw.signal_date.eq(day)]
    first=reader(day,rd);assert first['candidate_id']=='C14_P01'
    with (s.run/'SOLVE_LEDGER.json').open('a',encoding='utf-8') as stream:stream.write(' ')
    with pytest.raises(ValueError,match='CACHE_CHANGED'):reader(day,rd)


def test_changed_frozen_membership_owner_cannot_charge(synthetic):
    s=synthetic;s.reqs['C14_D01']['solver_requirement']['existing_owner']='D09'
    result=s.execute()
    assert set(result['failed_or_untestable'])=={'C14_D01'}
    assert 'FROZEN_FAMILY_MEMBERSHIP_OWNER_CHANGED' in result['failed_or_untestable']['C14_D01']
    assert not any('|C14_D01|' in t for t in s.journal.calls)


def recovery_refs(s):
    """Only fabricated old D02 metadata and opaque bytes are created."""
    root=s.run/'risk_execution';refs={}
    for key,name in (('panel','scores_pre2026.parquet'),('predicted_risk','predicted_risk_pre2026.parquet')):
        path=root/'C14_D02'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'SYNTHETIC_D02_OPAQUE')
        refs[key]=dict(path=str(path),sha256=m.binding.sha(path),rows=len(s.raw) if key=='panel' else 12)
    refs['panel'].update(calendar_dates=12,common_rows=len(s.raw),raw_fallback_2023_exact=False)
    role=dict(status='MEMBERSHIP_COMPLETE',role='C14_D02',failure=None,calendar_dates=12,
        raw_fallback_2023_exact=False,year2023_counted_as_learning_success=False,source_review={'path':'ORIGINAL_REVIEW','sha256':'b'*64},
        scientific_retry=0,forecast2026_rows=0)
    value=dict(research_id=m.owner.ID,status='MEMBERSHIP_ASSEMBLY_COMPLETE',complete_candidates=['C14_D02'],
        native_pair_predictions={},panels={'C14_D02':refs['panel']},predicted_risk={'C14_D02':refs['predicted_risk']},
        variance_diagnostics={'C14_D02':refs['predicted_risk']},roles={'C14_D02':role})
    reference=writej(root/'MEMBERSHIP_ASSEMBLY.json',value)
    custody=dict(prior_refs=dict(membership=reference),d02_artifacts={k:{a:v[a] for a in ('path','sha256')} for k,v in refs.items()})
    recovery=writej(s.run/'C14_SOURCE_METADATA_RECOVERY_RECEIPT_R1.json',custody)
    s.review['source_metadata_recovery_ref']=recovery;s.review_ref.update(writej(s.run/'SOURCE_REVIEW.json',s.review))
    return reference,value,custody,recovery


@pytest.mark.parametrize('recovery_name',['source_metadata_recovery_r1','source_guard_recovery_r1'])
def test_recovery_membership_exact_reuses_old_d02_refs_without_reading_or_rewriting_payload(synthetic,monkeypatch,recovery_name):
    s=synthetic;reference,value,custody,recovery=recovery_refs(s);root=s.run/'risk_execution'/recovery_name
    before={p:p.read_bytes() for p in (s.run/'risk_execution/C14_D02').iterdir()}
    result=m.execute_membership(s.run,s.design,s.q,s.raw,s.geometry,s.matrix,s.inputs.get_risk,s.journal,s.review_ref,
        artifact_root=root,raw_identity_ref=reference)
    assert result['complete_candidates']==list(m.ROLES) and len(s.journal.calls)==72
    assert 'C14_D02' not in s.route_calls and not any(r=='C14_D02' for r,d in s.inputs.calls)
    for field in ('panels','predicted_risk','variance_diagnostics','roles'):
        assert result[field]['C14_D02']==value[field]['C14_D02']
    assert all(Path(p).is_relative_to(root) for p in s.writes)
    assert not any(Path(p).parent.name=='C14_D02' for p in s.writes)
    assert {p:p.read_bytes() for p in before}==before
    assert result['roles']['C14_D02']['source_review']['path']=='ORIGINAL_REVIEW'
    assert result['roles']['C14_D02']['year2023_counted_as_learning_success'] is False


@pytest.mark.parametrize('root_kind',['alternate','descendant','foreign','models'])
def test_membership_rejects_nonfixed_artifact_root_before_risk_or_solver(synthetic,root_kind):
    s=synthetic;root={'alternate':s.run/'risk_execution/source_guard_recovery_r2',
        'descendant':s.run/'risk_execution/source_guard_recovery_r1/nested',
        'foreign':s.run.parent/'other/risk_execution/source_guard_recovery_r1',
        'models':s.run/'risk_execution/models'}[root_kind]
    with pytest.raises(ValueError,match='ARTIFACT_ROOT'):
        m.execute_membership(s.run,s.design,s.q,s.raw,s.geometry,s.matrix,s.inputs.get_risk,s.journal,s.review_ref,
            artifact_root=root)
    assert not s.inputs.calls and not s.journal.calls and not s.route_calls and not s.writes


@pytest.mark.parametrize('mutation',['foreign_root','missing_review','foreign_member','changed_panel','extra_complete','short_calendar','wrong_rows','wrong_risk_rows'])
def test_recovery_d02_rejects_unreviewed_changed_or_partial_reuse(synthetic,mutation):
    s=synthetic;reference,value,custody,recovery=recovery_refs(s);root=s.run/'risk_execution/source_metadata_recovery_r1'
    if mutation=='foreign_root':root=s.run/'risk_execution/other'
    elif mutation=='missing_review':s.review.pop('source_metadata_recovery_ref')
    elif mutation=='foreign_member':custody['prior_refs']['membership']={}
    elif mutation=='changed_panel':Path(value['panels']['C14_D02']['path']).write_bytes(b'CHANGED_SYNTHETIC')
    elif mutation=='extra_complete':value['complete_candidates'].append('C14_D01')
    elif mutation=='short_calendar':value['panels']['C14_D02']['calendar_dates']=11
    elif mutation=='wrong_rows':value['panels']['C14_D02']['common_rows']-=1
    elif mutation=='wrong_risk_rows':value['predicted_risk']['C14_D02']['rows']=11
    if mutation in ('extra_complete','short_calendar','wrong_rows','wrong_risk_rows'):
        reference=writej(s.run/'risk_execution/MEMBERSHIP_ASSEMBLY.json',value)
        custody['prior_refs']['membership']=reference
    recovery.update(writej(s.run/'C14_SOURCE_METADATA_RECOVERY_RECEIPT_R1.json',custody))
    s.review_ref.update(writej(s.run/'SOURCE_REVIEW.json',s.review))
    with pytest.raises((ValueError,AssertionError)):
        m.execute_membership(s.run,s.design,s.q,s.raw,s.geometry,s.matrix,s.inputs.get_risk,s.journal,s.review_ref,
            artifact_root=root,raw_identity_ref=reference)
    # Cardinality rejection currently occurs at the D02 branch, after independent
    # classical work. None can rewrite or re-solve the preserved D02 identity.
    assert 'C14_D02' not in s.route_calls and not any(Path(p).parent.name=='C14_D02' for p in s.writes)
