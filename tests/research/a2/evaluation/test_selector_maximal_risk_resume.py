"""Synthetic-only admission, transport and exact checkpoint reuse checks."""
from __future__ import annotations

from copy import deepcopy
from contextlib import nullcontext
import hashlib
import json
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

from scripts.research.a2.evaluation import selector_maximal_risk_resume as m


@pytest.fixture(autouse=True)
def clean_admission_custody():
    prior = dict(m._CUSTODY)
    authority, seal = m._TERMINAL_AUTHORITY, m._TERMINAL_TRANSPORT_SEAL
    checkpoint = m._POST_REBOOT_AUTHORITY
    m._CUSTODY.clear()
    m._TERMINAL_AUTHORITY = m._TERMINAL_TRANSPORT_SEAL = None
    m._POST_REBOOT_AUTHORITY = None
    yield
    m._CUSTODY.clear()
    m._CUSTODY.update(prior)
    m._TERMINAL_AUTHORITY, m._TERMINAL_TRANSPORT_SEAL = authority, seal
    m._POST_REBOOT_AUTHORITY = checkpoint


def rows_bytes(rows, monkeypatch):
    previous = '0' * 64
    result = []
    for sequence, (action, data) in enumerate(rows):
        payload = dict(sequence=sequence, previous=previous, action=action, data=data)
        row = dict(payload, sha256=m.digest(payload)); previous = row['sha256']; result.append(row)
    raw = ''.join(json.dumps(row, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n' for row in result).encode()
    monkeypatch.setattr(m, 'DELTA_BYTES', len(raw)); monkeypatch.setattr(m, 'DELTA_LINES', len(result))
    monkeypatch.setattr(m, 'DELTA_SHA', hashlib.sha256(raw).hexdigest())
    return raw


@pytest.fixture
def delta_rows():
    rows = [('HEADER', dict(research_id=m.ID, scientific_retry=0))]
    for role in m.ACTIVATED:
        rows.append(('ACTIVATE_ROLE', dict(role=role, qualification=dict(marker=role))))
    for role in m.RX:
        rows.append(('BLOCK_REMAINING', dict(role=role, nodes=[f'{role}|{i}' for i in range(14)],
            reason='UNEXPECTED_ENGINEERING_FAILURE_BEFORE_UNUSED_FITS')))
    for role, count in m.EXPECTED_SOLVES.items():
        for i in range(count):
            token = f'CLASSICAL|{role}|2024-DAY-{i:03}'
            result = dict(chosen_uids=['synthetic'], optimizer_solve_calls=1)
            receipt = dict(identity=dict(role=role, day=i), result=result, result_sha256=m.digest(result))
            rows.extend([('SOLVE_ENTER', dict(token=token)), ('SOLVE_COMPLETE', dict(token=token, receipt=receipt))])
    return rows


def test_full_checkpoint_pairs_and_typed_prefit_blocks(delta_rows, monkeypatch):
    value = m.audit_delta(rows_bytes(delta_rows, monkeypatch))
    assert value['counts'] == {'C14_D01': 752, 'C14_D05': 226}
    assert len(value['requests']) == 978 and set(value['activations']) == set(m.ACTIVATED)
    assert all(len(v['nodes']) == 14 for v in value['blocks'].values())


@pytest.mark.parametrize('mutation', ['missing_complete', 'duplicate_enter', 'fit_begin', 'fit_enter',
    'fit_finish', 'solve_failed', 'hybrid_charge', 'corrupt_result', 'wrong_cache_kind', 'block_node_count',
    'block_reason', 'foreign_activation', 'duplicate_activation', 'foreign_role', 'orphan_complete'])
def test_checkpoint_rejects_scientific_retry_and_ambiguous_charge(delta_rows, monkeypatch, mutation):
    rows = deepcopy(delta_rows)
    if mutation == 'missing_complete': rows.pop()
    elif mutation == 'duplicate_enter': rows[-1] = rows[-2]
    elif mutation in ('fit_begin', 'fit_enter', 'fit_finish', 'solve_failed'):
        rows.append((mutation.upper(), {'token': 'CLASSICAL|C14_D05|day'}))
    elif mutation == 'hybrid_charge':
        rows[-2][1]['token'] = rows[-1][1]['token'] = 'HYBRID|C14_RX_HGB_LW|day'
    elif mutation == 'corrupt_result': rows[-1][1]['receipt']['result']['chosen_uids'] = ['changed']
    elif mutation == 'wrong_cache_kind': rows[-1][1]['receipt']['matching_records'] = []
    elif mutation == 'block_node_count': rows[9][1]['nodes'].pop()
    elif mutation == 'block_reason': rows[9][1]['reason'] = 'FAILED_SCIENCE'
    elif mutation == 'foreign_activation': rows[1][1]['role'] = 'C15'
    elif mutation == 'duplicate_activation': rows[2][1]['role'] = rows[1][1]['role']
    elif mutation == 'foreign_role':
        rows[-2][1]['token'] = rows[-1][1]['token'] = 'CLASSICAL|C14_D06|other'
    elif mutation == 'orphan_complete': rows[-1][1]['token'] = 'CLASSICAL|C14_D05|orphan'
    with pytest.raises((ValueError, KeyError)):
        m.audit_delta(rows_bytes(rows, monkeypatch))


def test_delta_requires_exact_historical_full_pin_and_hash_chain(delta_rows, monkeypatch):
    raw = rows_bytes(delta_rows, monkeypatch)
    with pytest.raises(ValueError, match='BYTES'):
        m.audit_delta(raw[:-1])
    values = [json.loads(line) for line in raw.splitlines()]
    values[30]['previous'] = 'f' * 64
    bad = ''.join(json.dumps(v) + '\n' for v in values).encode()
    monkeypatch.setattr(m, 'DELTA_BYTES', len(bad)); monkeypatch.setattr(m, 'DELTA_SHA', hashlib.sha256(bad).hexdigest())
    with pytest.raises(ValueError, match='HASH_CHAIN'):
        m.audit_delta(bad)


@pytest.fixture
def qualification(monkeypatch, tmp_path):
    monkeypatch.setattr(m, 'ROOT', tmp_path/'risk_execution'); monkeypatch.setattr(m, 'B_RUN', tmp_path/'B_R5')
    monkeypatch.setattr(m, 'safe_path', lambda p: Path(p).resolve())
    review = dict(path='original_review', sha256='a' * 64)
    dates = [f'2023-{i:04d}' for i in range(752)]
    current = {d: dict(c14_current_key_sha256=f'{i:064x}') for i,d in enumerate(dates)}
    matrix = dict(design_sha256='d' * 64, dag_sha256='e' * 64, roles=[])
    gates, activations, bodies = {}, {}, {}
    for index, role in enumerate(m.QUALIFIED):
        family = ('LW', 'QQQ', 'LW', 'OAS', 'EWMA', 'SHR_HP', 'PCA', 'QQQ', 'LW', 'PCA')[index]
        req = dict(role=role, required_family_method=family, required_dates=dates)
        matrix['roles'].append(req)
        states = []
        for i,d in enumerate(dates):
            # Ten roles share six families of 55 exact native files.
            family_index = {'LW': 0, 'QQQ': 1, 'OAS': 2, 'EWMA': 3, 'SHR_HP': 4, 'PCA': 5}[family]
            state_number = family_index * 55 + i % 55
            ref = dict(path=str(m.B_RUN/'models/risk'/f'{state_number}.joblib'), sha256=f'{state_number:064x}')
            states.append(dict(decision_date=d, state_ref=ref, header_qualified=True, current_UID_qualified=True,
                numeric_qualified=True, full_U_keys_sha256=current[d]['c14_current_key_sha256'],
                native_as_of='2024-01-02', native_cutoff='2023-12-31'))
        gate = dict(phase='FULL752_NUMERIC_INPUT_QUALIFIED', research_id=m.ID, role=role, family=family,
            design_sha256=matrix['design_sha256'], dag_sha256=matrix['dag_sha256'], source_review=review,
            full_required_dates_qualified=True, calendar_positions=752, full_risk_mature_positions=732, learned_positions=482,
            states=states, reasons=[], realized_endpoint_qualified=False, selector_fit=0, solver=0, test2026_rows_read=0,
            strict_PIT_promotion_eligible=False)
        gates[role] = gate; path = str(m.ROOT/'input_gates'/f'{role}.json'); bodies[path] = gate
        if role in m.ACTIVATED:
            activations[role] = dict(qualification_ref=dict(path=path, sha256='f' * 64), family=family,
                states_sha256=m.digest(states), dates=deepcopy(states))
    counts = dict(native_state_load_attempts=330, native_states_loaded=330, daily_role_bindings=7520,
        selector_fit=0, risk_estimator_fit=0, solver=0, bootstrap=0, risk_numeric_read=330,
        test2026_rows_read=0, EF_access=0, provider_fetch=0)
    q = dict(research_id=m.ID, roles=gates, counts=counts, strict_PIT_promotion_eligible=False, realized_endpoint_qualified=False)
    pins = []
    monkeypatch.setattr(m, 'reference', lambda p: dict(path=str(p), sha256='f' * 64))
    monkeypatch.setattr(m, 'read', lambda ref, **_: deepcopy(bodies[ref['path']]))
    monkeypatch.setattr(m, 'pin', lambda ref, **_: pins.append(ref) or Path(ref['path']))
    return SimpleNamespace(q=q, matrix=matrix, current=current, review=review, activations=activations, bodies=bodies, pins=pins)


def test_metadata_restore_verifies_ten752_gates_eight_activations_and330_physical_files(qualification):
    f = qualification
    gates = m.validate_qualification(f.q, f.matrix, f.current, f.review, f.activations)
    assert set(gates) == set(m.QUALIFIED) and len(f.pins) == 330
    assert gates is not f.q['roles'] and gates['C14_D01']['states'] is not f.q['roles']['C14_D01']['states']


@pytest.mark.parametrize('mutation', ['q_counts', 'q_science', 'phase', 'date', 'short', 'native', 'uid', 'psd',
    'full_u', 'source_review', 'family', 'design', 'gate_body', 'activation_state_digest', 'activation_dates', 'foreign_native'])
def test_metadata_qualification_rejects_stale_or_partial_authority(qualification, mutation):
    f = qualification; gate = f.q['roles']['C14_D01']; state = gate['states'][0]
    if mutation == 'q_counts': f.q['counts']['native_states_loaded'] = 329
    elif mutation == 'q_science': f.q['counts']['selector_fit'] = 1
    elif mutation == 'phase': gate['phase'] = 'WAITING_R5_PUBLICATION'
    elif mutation == 'date': state['decision_date'] = '2026-01-01'
    elif mutation == 'short': gate['states'].pop()
    elif mutation == 'native': state['header_qualified'] = False
    elif mutation == 'uid': state['current_UID_qualified'] = False
    elif mutation == 'psd': state['numeric_qualified'] = False
    elif mutation == 'full_u': state['full_U_keys_sha256'] = 'f' * 64
    elif mutation == 'source_review': gate['source_review'] = dict(path='new_review', sha256='b' * 64)
    elif mutation == 'family': gate['family'] = 'R6'
    elif mutation == 'design': gate['design_sha256'] = 'a' * 64
    elif mutation == 'gate_body': f.bodies[str(m.ROOT/'input_gates/C14_D01.json')] = dict(gate, solver=1)
    elif mutation == 'activation_state_digest': f.activations['C14_D01']['states_sha256'] = '0' * 64
    elif mutation == 'activation_dates': f.activations['C14_D01']['dates'][0]['numeric_qualified'] = False
    elif mutation == 'foreign_native': state['state_ref']['path'] = str(m.B_RUN.parent/'R6/foreign.joblib')
    with pytest.raises((ValueError, KeyError)):
        m.validate_qualification(f.q, f.matrix, f.current, f.review, f.activations)


def test_restore_requires_pristine_exact_owner_and_never_calls_qualify():
    class Inputs:
        def __init__(self):
            self._qualified=False; self._gates={}; self._cache={}; self._failed={}; self.counts={'risk_numeric_read':0}
            self.requirements={'C14_D01':{}}; self.review_ref={'original':'R3'}; self.verified=[]
        def _verify(self, **kw): self.verified.append(kw)
        def qualify(self): raise AssertionError('Numeric qualification replay forbidden')
    owner=SimpleNamespace(input_owner=SimpleNamespace(RiskInputs=Inputs)); inputs=Inputs()
    gates={'C14_D01':dict(role='C14_D01',source_review=inputs.review_ref,full_required_dates_qualified=True)}
    m.restore_input_gates(inputs,gates,owner)
    assert inputs._qualified is True and inputs.counts == {'risk_numeric_read':0}
    assert len(inputs.verified)==2 and inputs._gates is not gates
    with pytest.raises(ValueError,match='PRISTINE'):
        m.restore_input_gates(inputs,gates,owner)
    inputs=Inputs(); inputs._cache['entered']='state'
    with pytest.raises(ValueError,match='PRISTINE'):
        m.restore_input_gates(inputs,gates,owner)


def test_snapshot_guard_maps_only_actual_three_canonical_modules(monkeypatch, tmp_path):
    custody={}; modules={}; design={'sources':{'untouched.py':'c'*64}}; transport={}
    for i,name in enumerate(('synthetic_ca','synthetic_account','synthetic_joint')):
        relative=f'{name}.py'; live=tmp_path/relative; snapshot=tmp_path/'source_snapshot'/relative
        transport[name]=(relative,'a'*64,'b'*64)
        custody[name]=dict(live=dict(path=str(live),sha256='b'*64),original_snapshot=dict(path=str(snapshot),sha256='a'*64))
        modules[name]=object(); design['sources'][str(live)]='a'*64
    monkeypatch.setattr(m,'TRANSPORT',transport);monkeypatch.setattr(m,'REPO',tmp_path)
    monkeypatch.setattr(m,'RUN',tmp_path/'run');monkeypatch.setattr(m,'validate_transport',lambda _:None)
    seen=[]
    monkeypatch.setattr(m,'assert_module',lambda module,name,path:seen.append((module,name,path)))
    checked=[]
    original=lambda run,d:checked.append(deepcopy(d)) or 'CHECKED'
    ctl=SimpleNamespace(checked_sources=original);execution=SimpleNamespace(ctl=ctl)
    with m.executable_snapshot_guard(execution,custody,modules):
        assert ctl.checked_sources(m.RUN,design)=='CHECKED'
        assert design['sources']['untouched.py']=='c'*64
        assert set(checked[0]['sources'])=={'untouched.py',*(v['original_snapshot']['path'] for v in custody.values())}
        assert len(seen)==3
    assert ctl.checked_sources is original
    with pytest.raises(ValueError,match='PIN'):
        with m.executable_snapshot_guard(execution,custody,modules):
            ctl.checked_sources(m.RUN,{'sources':{'untouched.py':'c'*64}})
    assert ctl.checked_sources is original


def test_existing_live_module_pollution_refuses_before_snapshot_execution(monkeypatch):
    name=next(iter(m.TRANSPORT));monkeypatch.setattr(m,'validate_transport',lambda _:None)
    monkeypatch.setitem(sys.modules,name,SimpleNamespace(__file__='live.py'))
    with pytest.raises(ValueError,match='COLD_PROCESS'):
        m.load_snapshots({})


def test_preloaded_fast_account_refuses_before_snapshot_execution(monkeypatch):
    monkeypatch.setattr(m,'validate_transport',lambda _:None)
    monkeypatch.setitem(sys.modules,m.FAST_NAME,SimpleNamespace(__file__='fake_fast.py'))
    with pytest.raises(ValueError,match='COLD_PROCESS'):
        m.load_snapshots({})


@pytest.mark.parametrize('name',[m.JOINT_NAME,m.POLICY_NAME,m.OPT_NAME])
def test_preloaded_joint_or_dependency_refuses_before_snapshot_execution(monkeypatch,name):
    monkeypatch.setattr(m,'validate_transport',lambda _:None)
    monkeypatch.setitem(sys.modules,name,SimpleNamespace(__file__='fake_joint_dependency.py'))
    monkeypatch.setattr(m,'pin',lambda *_a,**_k:pytest.fail('Pin or execution after cold-process pollution'))
    with pytest.raises(ValueError,match='COLD_PROCESS'):
        m.load_snapshots({})


@pytest.mark.parametrize('mutation',['missing_joint','extra_executable'])
def test_only_fixed_three_transport_modules_are_admitted(monkeypatch,mutation):
    custody={name:{} for name in m.TRANSPORT}
    if mutation=='missing_joint':custody.pop(m.JOINT_NAME)
    else:custody['unapproved.fourth_source']={}
    monkeypatch.setattr(m,'pin',lambda *_a,**_k:pytest.fail('Pin after invalid transport set'))
    with pytest.raises(ValueError,match='ONLY_THREE_FIXED'):
        m.validate_transport(custody)


@pytest.mark.parametrize('mutation',['none','joint_code_origin','policy_code_origin','opt_code_origin','joint_dependency_identity'])
def test_real_synthetic_three_snapshot_bytes_execute_with_canonical_origins(monkeypatch,tmp_path,mutation):
    import importlib
    package=tmp_path/'synthetic_resume';package.mkdir();(package/'__init__.py').write_text('',encoding='utf-8')
    frozen=tmp_path/'source_snapshot';frozen.mkdir()
    ca_name='synthetic_resume.ca';account_name='synthetic_resume.account';fast_name='synthetic_resume.fast'
    joint_name='synthetic_resume.joint';policy_name='synthetic_resume.policy';opt_name='synthetic_resume.optimization'
    membership_name='synthetic_resume.membership'
    ca_code='''class CorporateActionTransition: pass
class CorporateActionTransitionAdapter: pass
class SourceBackedEntitlementEvent: pass
class SourceBackedTerminalEvent: pass
class EntitlementLifecycleState: pass
RAW_OLD_SHARE_COORDINATE = "original"
def apply_transition_to_positions(): pass
def apply_entitlement_lifecycle(): pass
def _entitlement_effective_day(): pass
def _entitlement_pay_date(): pass
'''
    fast_code='''class MarketArrays: pass
class TargetDecision: pass
def run_many(): return "original_fast"
'''
    account_code='''from synthetic_resume.ca import (CorporateActionTransitionAdapter, apply_transition_to_positions,
    SourceBackedEntitlementEvent, SourceBackedTerminalEvent, EntitlementLifecycleState,
    apply_entitlement_lifecycle, RAW_OLD_SHARE_COORDINATE, _entitlement_effective_day, _entitlement_pay_date)
from synthetic_resume.fast import MarketArrays, TargetDecision, run_many
from synthetic_resume import fast as _common_engine
class PersistentPolicyContext: pass
def _engine_with_entitlement_hook(): return "frozen_account"
'''
    policy_code='''from synthetic_resume.fast import TargetDecision
from synthetic_resume.optimization import project_budget
class JointResearchPolicy: pass
class InfeasiblePolicy(ValueError): pass
EPS=0.00001
def _support_projection(): pass
def _capped_mass(): pass
def _covariance_action(): pass
'''
    opt_code='''def _smooth_cvar(): pass
def project_budget(): pass
'''
    joint_code='''from synthetic_resume.policy import (JointResearchPolicy, InfeasiblePolicy, EPS,
    _support_projection, _capped_mass, _covariance_action)
from synthetic_resume.optimization import _smooth_cvar
from synthetic_resume.fast import TargetDecision
class AllocationUnavailable(InfeasiblePolicy): pass
class AllocationResult: pass
class JointAllocationPolicy(JointResearchPolicy): pass
class TradingControlPolicy: pass
def _hrp(): return "frozen_joint_hrp"
def allocate_q(): pass
def exposure(): pass
def _v24_call(): pass
'''
    if mutation=='joint_code_origin':joint_code+='exec(compile("def _hrp(): pass", "wrong_live_joint.py", "exec"))\n'
    elif mutation=='policy_code_origin':policy_code+='exec(compile("def _covariance_action(): pass", "wrong_policy.py", "exec"))\n'
    elif mutation=='opt_code_origin':opt_code+='exec(compile("def _smooth_cvar(): pass", "wrong_opt.py", "exec"))\n'
    elif mutation=='joint_dependency_identity':joint_code+='class JointResearchPolicy: pass\n'
    transport={};custody={}
    for name,code in ((ca_name,ca_code),(account_name,account_code),(joint_name,joint_code)):
        relative='synthetic_resume/'+name.rsplit('.',1)[1]+'.py';live=tmp_path/relative
        live.write_text('raise AssertionError("LIVE SOURCE MUST NOT EXECUTE")\n',encoding='utf-8')
        snapshot=frozen/relative;snapshot.parent.mkdir(exist_ok=True);snapshot.write_text(code,encoding='utf-8')
        frozen_sha=hashlib.sha256(snapshot.read_bytes()).hexdigest();live_sha=hashlib.sha256(live.read_bytes()).hexdigest()
        transport[name]=(relative,frozen_sha,live_sha)
        custody[name]=dict(live=dict(path=str(live),sha256=live_sha),original_snapshot=dict(path=str(snapshot),sha256=frozen_sha))
    fast_path=package/'fast.py';fast_path.write_text(fast_code,encoding='utf-8')
    policy_path=package/'policy.py';policy_path.write_text(policy_code,encoding='utf-8')
    opt_path=package/'optimization.py';opt_path.write_text(opt_code,encoding='utf-8')
    membership_path=package/'membership.py';membership_path.write_text('''def _hierarchical():
    from synthetic_resume.joint import _hrp
    return _hrp()
''',encoding='utf-8')
    monkeypatch.setattr(m,'REPO',tmp_path);monkeypatch.setattr(m,'RUN',tmp_path)
    monkeypatch.setattr(m,'TRANSPORT',transport);monkeypatch.setattr(m,'FAST_NAME',fast_name)
    monkeypatch.setattr(m,'CA_NAME',ca_name);monkeypatch.setattr(m,'ACCOUNT_NAME',account_name)
    monkeypatch.setattr(m,'JOINT_NAME',joint_name);monkeypatch.setattr(m,'POLICY_NAME',policy_name)
    monkeypatch.setattr(m,'POLICY_PATH',policy_path);monkeypatch.setattr(m,'POLICY_SHA',hashlib.sha256(policy_path.read_bytes()).hexdigest())
    monkeypatch.setattr(m,'OPT_NAME',opt_name);monkeypatch.setattr(m,'OPT_PATH',opt_path)
    monkeypatch.setattr(m,'OPT_SHA',hashlib.sha256(opt_path.read_bytes()).hexdigest())
    monkeypatch.setattr(m,'MEMBERSHIP_NAME',membership_name);monkeypatch.setattr(m,'MEMBERSHIP_PATH',membership_path)
    monkeypatch.setattr(m,'FAST_PATH',fast_path);monkeypatch.setattr(m,'FAST_SHA',hashlib.sha256(fast_path.read_bytes()).hexdigest())
    monkeypatch.syspath_prepend(str(tmp_path));importlib.invalidate_caches()
    try:
        if mutation!='none':
            with pytest.raises(ValueError,match='DEPENDENCY_IDENTITIES' if mutation=='joint_dependency_identity' else 'CODE_ORIGIN'):
                m.load_snapshots(custody)
            return
        modules=m.load_snapshots(custody)
        ca,account,joint=modules[ca_name],modules[account_name],modules[joint_name]
        assert account._engine_with_entitlement_hook()=='frozen_account'
        assert joint._hrp()=='frozen_joint_hrp'
        assert account.CorporateActionTransitionAdapter is ca.CorporateActionTransitionAdapter
        assert str(frozen) in account._engine_with_entitlement_hook.__code__.co_filename
        assert str(frozen) in joint._hrp.__code__.co_filename
        owner=importlib.import_module(membership_name)
        execution=SimpleNamespace(binding=SimpleNamespace(membership=owner))
        compare=SimpleNamespace(engine=account,CorporateActionTransition=ca.CorporateActionTransition)
        m.verify_downstream_bindings(modules,compare,execution)
        assert owner._hierarchical()=='frozen_joint_hrp'  # Synthetic scalar, no numerical or native owner.
        exec(compile('def _hierarchical(): return "unapproved_route"',str(membership_path),'exec'),owner.__dict__)
        with pytest.raises(ValueError,match='D11_CANONICAL_HRP_IMPORT'):
            m.verify_downstream_bindings(modules,compare,execution)
        m.function_origin(account,('_engine_with_entitlement_hook',),account.__file__)
        exec(compile('def _engine_with_entitlement_hook(): pass','wrong_live.py','exec'),account.__dict__)
        with pytest.raises(ValueError,match='CODE_ORIGIN'):
            m.function_origin(account,('_engine_with_entitlement_hook',),account.__file__)
    finally:
        for name in list(sys.modules):
            if name=='synthetic_resume' or name.startswith('synthetic_resume.'):
                sys.modules.pop(name)


def test_review_revision_uses_fixed_r3_path_and_preserves_failed_r1_marker():
    assert m.REVIEW_PATH==m.RUN/'C14_CHECKPOINT_CLASSICAL_RESUME_REVIEW_R3.json'
    assert m.SCHEMA=='C14_CHECKPOINT_CLASSICAL_ONLY_REVIEW_V2'
    assert m.MARKER=='CHECKPOINT_CLASSICAL_RESUME_STARTED_R2.json'
    assert m.AUDIT=='CHECKPOINT_CLASSICAL_RESUME_COMPLETE_R2.json'
    assert m.PINS['prior_checkpoint_marker'][0].name=='CHECKPOINT_CLASSICAL_RESUME_STARTED_R1.json'


@pytest.fixture
def failed_publication(monkeypatch,tmp_path):
    prior_review=dict(path='original_formal_R2',sha256='a'*64)
    delta=dict(path='original_delta',sha256='b'*64,bytes=6526570,lines=1967)
    marker=dict(status='STARTED_CLASSICAL_ONLY_CHECKPOINT_CONTINUATION',research_id=m.ID,
        review=prior_review,prior_delta=delta,scientific_retry=0,RX_reopened=False)
    pipeline=dict(status='CLASSICAL_CHECKPOINT_CONTINUATION_RUNNING',phase='ADMITTED_PRE_INPUT',
        review_ref=prior_review,execution_native_reads_started=False,exact_complete_cache_counts=m.EXPECTED_SOLVES,
        preserved_engineering_blocked_fit_slots=28)
    failure=dict(schema='C14_CHECKPOINT_PRE_DATA_PUBLICATION_CLOSURE_FAILURE_V1',
        status='ENGINEERING_FAILURE_BEFORE_ANY_NEW_BUSINESS_INPUT_OR_SCIENTIFIC_ENTRY',research_id=m.ID,
        exact_error_type='RiskBindingBlocked',exact_error='EXACT_FORMAL_R5_CODE_CLOSURE_REQUIRED',
        new_attempt_only_counts=dict(raw_metadata_projection=0,native_numeric_read=0,labels_read=0,new_fit=0,new_solve_charge=0,new_bootstrap=0),
        original_qualification_reads_historical=330,original_complete_caches_preserved=m.EXPECTED_SOLVES,
        original_RX28_blocks_preserved=True,no_terminal=True,one_shot_marker_preserved=True,
        all_three_B_frozen_hashes_equal_C_actual_executed_snapshot_hashes=True,scientific_retry=0,
        sole_delta=dict(delta,actions=dict(HEADER=1,ACTIVATE_ROLE=8,BLOCK_REMAINING=2,SOLVE_ENTER=978,SOLVE_COMPLETE=978)),
        B_code_pin_count=29,B_changed_live_sources=[Path(v[0]).name for v in m.TRANSPORT.values()])
    refs={}
    trace=('line 617, in resume\n publication = execution.binding.read_publication_metadata()\n'
        'line 900, in read_publication_metadata\nRiskBindingBlocked: EXACT_FORMAL_R5_CODE_CLOSURE_REQUIRED\n')
    for key in m.FAILURE_REFS:
        p=tmp_path/(key+'.txt');p.write_text(trace if key=='stderr' else 'synthetic '+key,encoding='utf-8')
        failure[key]=m.reference(p);refs[key]=(p,failure[key]['sha256'])
    monkeypatch.setattr(m,'FAILURE_REFS',refs)
    return SimpleNamespace(values=dict(publication_failure=failure,prior_checkpoint_marker=marker,pipeline=pipeline),
        review=dict(pause_delta=delta,prior_checkpoint_review=prior_review),refs=refs)


def test_only_fixed_failed_publication_before_data_can_be_recovered(failed_publication):
    f=failed_publication;m.validate_publication_failure(f.values,f.review)


@pytest.mark.parametrize('mutation',['science','wrong_failure','old_marker','pipeline_entered','delta_prefix','trace','prior_source','missing_proof'])
def test_failed_publication_receipt_trace_prefix_or_entry_changes_refuse(failed_publication,mutation):
    f=failed_publication;failure=f.values['publication_failure']
    if mutation=='science':failure['new_attempt_only_counts']['new_fit']=1
    elif mutation=='wrong_failure':failure['exact_error']='OTHER_FAILURE'
    elif mutation=='old_marker':f.values['prior_checkpoint_marker']['RX_reopened']=True
    elif mutation=='pipeline_entered':f.values['pipeline']['phase']='NUMERIC_ENTERED'
    elif mutation=='delta_prefix':failure['sole_delta']['sha256']='changed'
    elif mutation=='trace':
        p=f.refs['stderr'][0];p.write_text('wrong trace',encoding='utf-8')
        failure['stderr']=m.reference(p);f.refs['stderr']=(p,failure['stderr']['sha256'])
    elif mutation=='prior_source':f.refs['entry'][0].write_text('changed prior executable',encoding='utf-8')
    else:failure['no_terminal']=False
    with pytest.raises(ValueError):m.validate_publication_failure(f.values,f.review)


def test_publication_preflight_precedes_marker_and_execution_reuses_object():
    import ast
    tree=ast.parse(Path(m.__file__).read_text(encoding='utf-8'))
    resume=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='resume')
    calls=[n for n in ast.walk(resume) if isinstance(n,ast.Call)]
    preflight=[n for n in calls if isinstance(n.func,ast.Name) and n.func.id=='publication_metadata_preflight']
    marker=[n for n in calls if isinstance(n.func,ast.Attribute) and n.func.attr=='open']
    assert len(preflight)==len(marker)==1 and preflight[0].lineno<marker[0].lineno
    assert not any(isinstance(n.func,ast.Attribute) and n.func.attr=='read_publication_metadata' for n in calls)


@pytest.fixture
def publication_kernel(monkeypatch,tmp_path):
    # Execute the actual byte-identical metadata reader through the existing
    # binder. Only its external metadata/qualification fixtures are synthetic.
    from scripts.research.a2.data import selector_maximal_risk_binding as b
    from scripts.research.a2.risk import event_risk_contract_r5 as event
    from scripts.research.a2.evaluation import joint_event_risk_execution_r5 as qualification
    repo=tmp_path/'repo';run=tmp_path/'C_run';bankrun=tmp_path/'B_run'
    monkeypatch.setattr(m,'REPO',repo);monkeypatch.setattr(m,'RUN',run);monkeypatch.setattr(m,'B_RUN',bankrun)
    transport={};custody={};modules={};closure=[]
    for name,(relative,_,_) in m.TRANSPORT.items():
        live=repo/relative;live.parent.mkdir(parents=True,exist_ok=True);live.write_text('live '+name,encoding='utf-8')
        frozen=run/'source_snapshot'/relative;frozen.parent.mkdir(parents=True,exist_ok=True)
        frozen.write_text('frozen '+name,encoding='utf-8')
        live_ref=m.reference(live);frozen_ref=m.reference(frozen)
        transport[name]=(relative,frozen_ref['sha256'],live_ref['sha256'])
        custody[name]=dict(live=live_ref,original_snapshot=frozen_ref)
        modules[name]=SimpleNamespace(__file__=str(frozen),__name__=name)
        closure.append(dict(path=str(live),sha256=frozen_ref['sha256']))
    for i in range(26):
        p=repo/f'source_{i:02d}.py';p.write_text('original source '+str(i),encoding='utf-8');closure.append(m.reference(p))
    monkeypatch.setattr(m,'TRANSPORT',transport)
    original_origin=m.function_origin
    monkeypatch.setattr(m,'function_origin',lambda module,names,path:
        original_origin(module,names,path) if module is b else None)
    monkeypatch.setattr(m,'assert_module',lambda module,name,path:
        m.need(module is modules[name] and module.__file__==str(path),'SYNTHETIC_CANONICAL_ORIGIN'))
    refs={}
    for key,name in dict(plan='R5_FINITE_EVENT_RISK_PLAN.json',support='support/EVENT_RISK_SUPPORT_R5.json',
        source_authority='SOURCE_AUTHORITY.json',bank='models/risk/EVENT_RISK_BANK_R5.json',
        freeze='R5_SCIENCE_AND_EXECUTION_FREEZE.json',qualification='support/RISK_EVENT_QUALIFICATION_READER_RECOVERY_R5_R1.json',
        ledger='work/FIT_STATUS.json').items():
        p=bankrun/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}',encoding='utf-8');refs[key]=m.reference(p)
    refs.update(model_producer=closure[3],execution_producer=closure[4])
    freeze=dict(source_code_pins=closure,qualification_ref=refs['qualification'])
    bank={field:deepcopy(refs[name]) for name,field in b.chain_owner.REF_FIELDS.items()}
    bank.update(qualification_ref=refs['qualification'],ledger_ref=refs['ledger'])
    prior=dict(schema='C14_R5_PUBLICATION_ADMISSION_R3',research_id=m.ID,status='SOURCE_ONLY_PUBLICATION_QUALIFIED',
        numeric_execution_performed=False,strict_PIT_promotion_eligible=False,counts={k:0 for k in b.COUNTERS},publication_refs=refs)
    binding_path=Path(b.__file__).resolve()
    admission=dict(original={'source_pins':{str(binding_path):m.sha(binding_path)}},
        values=dict(B_freeze=freeze,original_publication_admission=prior),
        review=dict(snapshot_transport=custody,B_freeze=refs['freeze'],
            original_publication_admission=dict(path='historical authority',sha256='a'*64)))
    calls=[];reader=b.read_publication_metadata;original_sha=b.sha;original_code=reader.__code__
    class Publication:
        def __init__(self):self.refs=deepcopy(refs)
        def verify(self):calls.append('verify_metadata')
    monkeypatch.setattr(b,'PublicationBinding',Publication)
    monkeypatch.setattr(b,'contract',SimpleNamespace(B_RUN=bankrun,FILES={'freeze':'R5_SCIENCE_AND_EXECUTION_FREEZE.json','bank':'models/risk/EVENT_RISK_BANK_R5.json'},
        readiness=lambda:dict(status='PUBLISHED_METADATA_REVIEW_REQUIRED')))
    # Keep the real function's code origin pinned; adapt its repo-location-only
    # Path(__file__) lookup to this wholly synthetic closure fixture.
    monkeypatch.setattr(b,'Path',lambda value:repo/'scripts/research/a2/data/binding.py' if str(value)==str(binding_path) else Path(value))
    bodies={'R5_SCIENCE_AND_EXECUTION_FREEZE.json':freeze,'EVENT_RISK_BANK_R5.json':bank,
        'R5_FINITE_EVENT_RISK_PLAN.json':{},'EVENT_RISK_SUPPORT_R5.json':{},'FIT_STATUS.json':{}}
    monkeypatch.setattr(b,'read_r5_metadata',lambda ref:calls.append(('metadata',Path(ref['path']).name)) or bodies[Path(ref['path']).name])
    monkeypatch.setattr(qualification,'read_event_qualification',lambda owner,**kw:calls.append(('qualification',kw['qualification_ref'])) or {})
    def qualify(*args,**kwargs):
        assert kwargs['expected_code_pins']==kwargs['observed_code_pins']=={r['path']:r['sha256'] for r in closure}
        assert kwargs['refs']==refs
        calls.append('original_qualify_route');return Publication()
    monkeypatch.setattr(b,'qualify_publication',qualify)
    clones=[]
    def bind(function,**kwargs):
        clone=event.bind_pinned_kernel(function,**kwargs);clones.append(clone);return clone
    execution=SimpleNamespace(binding=b,membership=SimpleNamespace(event=SimpleNamespace(bind_pinned_kernel=bind)))
    return SimpleNamespace(execution=execution,admission=admission,modules=modules,custody=custody,
        closure=closure,refs=refs,binding=b,reader=reader,code=original_code,sha=original_sha,calls=calls,clones=clones)


def test_original_publication_reader_uses_exact29_three_logical_transports_and_nine_prior_refs(publication_kernel):
    f=publication_kernel
    result,proof=m.publication_metadata_preflight(f.execution,f.admission,f.modules)
    assert result['publication'].refs==f.refs
    assert proof['code_ref_count']==29 and proof['original_physical_code_refs']==26
    assert proof['transport_observation_counts']=={name:1 for name in m.TRANSPORT}
    assert f.binding.sha is f.sha and f.binding.read_publication_metadata is f.reader
    assert f.reader.__code__ is f.code and f.clones[0].__code__ is f.code
    assert 'original_qualify_route' in f.calls and any(isinstance(v,tuple) and v[0]=='qualification' for v in f.calls)
    assert all(ref['path'] in m._CUSTODY for ref in f.refs.values())
    for value in proof['transported_code_refs'].values():
        assert value['logical_canonical_code_ref']['sha256']==value['actual_executed_snapshot_ref']['sha256']
        assert value['actual_live_source_ref']['sha256']!=value['logical_canonical_code_ref']['sha256']


@pytest.mark.parametrize('mutation',['missing','extra','wrong_frozen_hash','changed_live','changed_other_source','changed_bank_pin','wrong_module'])
def test_publication_transport_rejects_closure_custody_or_original_bank_changes(publication_kernel,mutation):
    f=publication_kernel
    if mutation=='missing':f.closure.pop(0)
    elif mutation=='extra':f.closure.append(dict(path=str(m.REPO/'extra.py'),sha256='c'*64))
    elif mutation=='wrong_frozen_hash':f.closure[0]['sha256']='c'*64
    elif mutation=='changed_live':Path(next(iter(f.custody.values()))['live']['path']).write_text('changed live',encoding='utf-8')
    elif mutation=='changed_other_source':Path(f.closure[-1]['path']).write_text('changed other source',encoding='utf-8')
    elif mutation=='changed_bank_pin':f.refs['bank']['sha256']='c'*64
    else:f.modules[next(iter(f.modules))]=SimpleNamespace(__file__='wrong-origin')
    with pytest.raises(ValueError):m.publication_metadata_preflight(f.execution,f.admission,f.modules)
    assert f.binding.sha is f.sha and f.reader.__code__ is f.code


@pytest.mark.parametrize('suffix',['models/risk/native.joblib','foreign.py','outside_metadata.json'])
def test_publication_clone_sha_cannot_transport_native_or_foreign_paths(publication_kernel,suffix):
    f=publication_kernel;m.publication_metadata_preflight(f.execution,f.admission,f.modules)
    resolver=f.clones[0].__globals__['sha']
    with pytest.raises(ValueError,match='TRANSPORT_DOMAIN_FORBIDDEN'):
        resolver(m.B_RUN/suffix)


@pytest.mark.parametrize('suffix',['.joblib','.joblib.tmp'])
def test_original_hashed_rx_model_destination_rejected_without_fit_event(monkeypatch,tmp_path,suffix):
    run=tmp_path/'run';root=run/'risk_execution/source_metadata_recovery_r1'
    monkeypatch.setattr(m,'RUN',run);monkeypatch.setattr(m,'ROOT',root)
    role=m.RX[0];node='RX_MODEL|'+role+'|2024-01-01|LOW|20260928|None'
    p=run/'risk_execution/models'/(m.digest(node)+suffix);p.parent.mkdir(parents=True);p.write_bytes(b'not a real model')
    with pytest.raises(ValueError,match='RX_NODE_ARTIFACT'):
        m.validate_rx_artifacts(role,[node],root/role/'ENGINEERING_FAILURE_R1.json')


def test_runtime_source_custody_blocks_charge_after_transport_change(monkeypatch,tmp_path):
    p=tmp_path/'new_resume.py';p.write_text('original',encoding='utf-8')
    ref=dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest());m.pin(ref)
    class Journal:
        def __init__(self):self.pins={};self.charges=[]
        def pin(self,path,expected):
            assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==expected
            self.pins[str(path)]=m.stamp(path)
        def verify(self):
            if not all(m.stamp(p)==s for p,s in self.pins.items()):raise ValueError('RUNTIME_PIN_CHANGED')
        def charge(self):self.verify();self.charges.append('charged')
    j=Journal();m.bind_runtime_custody(j)
    p.write_text('changed source after admission',encoding='utf-8')
    with pytest.raises(ValueError,match='RUNTIME_PIN'):
        j.charge()
    assert j.charges==[]


@pytest.mark.parametrize('field',['status','independent_review','classification','scientific_retry','test2026_rows_read','schema','source_pins'])
def test_unapproved_review_stops_before_any_numeric_or_event(monkeypatch,tmp_path,field):
    monkeypatch.setattr(m,'ROOT',tmp_path);monkeypatch.setattr(m,'no_other_worker',lambda:None)
    value=dict(schema=m.SCHEMA,status='PASS',research_id=m.ID,classification='CHECKPOINT_CLASSICAL_ONLY',
        independent_review=True,scientific_contract_changed=False,scientific_retry=0,test2026_rows_read=0,
        source_pins={str(Path(m.__file__).resolve()):'a'*64,
            str(m.REPO/'tests/research/a2/evaluation/test_selector_maximal_risk_resume.py'):'b'*64},
        **{key:{} for key in m.PINS},pause_delta={},D01_artifacts={},snapshot_transport={})
    value[field]={'status':'WAITING','independent_review':False,'classification':'RX_RETRY','scientific_retry':1,
        'test2026_rows_read':1,'schema':'GENERIC_RESUME','source_pins':{}}[field]
    def read(ref,**kw):
        assert kw.get('path')==m.REVIEW_PATH
        return value
    monkeypatch.setattr(m,'read',read)
    monkeypatch.setattr(m,'pin',lambda *_a,**_k:pytest.fail('Pin after rejected review'))
    with pytest.raises(ValueError):m.admit({'path':str(m.REVIEW_PATH),'sha256':'c'*64})


def test_other_worker_rejected_including_suspended_original(monkeypatch):
    monkeypatch.setattr(m,'process_inventory',lambda:[dict(ProcessId=19164,CommandLine='python -m selector_maximal_risk_execution')])
    with pytest.raises(ValueError,match='OTHER_C14'):
        m.no_other_worker()
    monkeypatch.setattr(m,'process_inventory',lambda:[dict(ProcessId=__import__('os').getpid(),CommandLine='python -m selector_maximal_risk_resume')])
    m.no_other_worker()


def test_one_shot_marker_rejects_before_review_and_numerics(monkeypatch,tmp_path):
    monkeypatch.setattr(m,'ROOT',tmp_path);monkeypatch.setattr(m,'no_other_worker',lambda:None)
    (tmp_path/m.MARKER).write_text('STARTED',encoding='utf-8')
    monkeypatch.setattr(m,'read',lambda *_a,**_k:pytest.fail('Read after existing one-shot marker'))
    with pytest.raises(ValueError,match='ONE_SHOT'):
        m.admit({'path':'unused','sha256':'0'*64})


def test_rx_original_errors_are_preserved_without_reopening():
    failures={r:dict(error_type='ValueError',error='PIN_CHANGED:original.py') for r in m.RX}
    results=m.preserved_hybrid_results(failures)
    assert all(v['complete_candidates']==[] and v['panels']=={} for v in results)
    assert set().union(*(set(v['failed_or_untestable']) for v in results))==set(m.RX)


@pytest.fixture
def completed_d01(monkeypatch,tmp_path):
    monkeypatch.setattr(m,'ROOT',tmp_path)
    names={'assembly':'MEMBERSHIP_ASSEMBLY.json','receipts':'MEMBERSHIP_RECEIPTS.json',
        'panel':'scores_pre2026.parquet','predicted_risk':'predicted_risk_pre2026.parquet'}
    refs={k:dict(path=str(tmp_path/'C14_D01'/name),sha256='a'*64) for k,name in names.items()}
    dates=[f'2024-synthetic-{i:03d}' for i in range(752)]
    oldreview=dict(path='R3',sha256='b'*64)
    assembly=dict(status='MEMBERSHIP_COMPLETE',role='C14_D01',calendar_dates=752,failure=None,
        source_review=oldreview,scientific_retry=0,forecast2026_rows=0)
    receipts=[];requests={}
    for i,day in enumerate(dates):
        result=dict(chosen_uids=[f'opaque-{i}'],optimizer_solve_calls=1)
        receipts.append(dict(signal_date=day,result=result))
        requests['CLASSICAL|C14_D01|'+day]=dict(result_sha256=m.digest(result))
    bodies={refs['assembly']['path']:assembly,refs['receipts']['path']:receipts}
    pins=[]
    monkeypatch.setattr(m,'pin',lambda ref,**kw:pins.append((ref,kw)) or Path(ref['path']))
    monkeypatch.setattr(m,'read',lambda ref,**kw:deepcopy(bodies[ref['path']]))
    return SimpleNamespace(refs=refs,dates=dates,review=oldreview,assembly=assembly,
        receipts=receipts,journal={'requests':requests},pins=pins)


def test_d01_all752_opaque_artifact_receipts_match_original_cache_without_owner_call(completed_d01):
    f=completed_d01
    assert m.validate_d01(f.refs,f.journal,f.dates,f.review)==f.assembly
    assert len(f.pins)==4
    admission=dict(review={'D01_artifacts':f.refs},d01=f.assembly)
    result=m.completed_d01_result(admission,dict(artifacts={'raw_current':{'rows':313668}}))
    assert result['complete_candidates']==['C14_D01'] and result['native_pair_predictions']=={}
    assert result['panels']['C14_D01']['sha256']==f.refs['panel']['sha256']
    assert result['panels']['C14_D01']['calendar_dates']==752
    assert result['variance_diagnostics']['C14_D01']==result['predicted_risk']['C14_D01']


@pytest.mark.parametrize('mutation',['receipt_digest','short_receipt','date_order','assembly_failure','foreign_source','missing_artifact'])
def test_d01_partial_or_changed_artifact_is_never_assumed_complete(completed_d01,mutation):
    f=completed_d01
    if mutation=='receipt_digest':f.receipts[0]['result']['chosen_uids']=['changed-opaque-value']
    elif mutation=='short_receipt':f.receipts.pop()
    elif mutation=='date_order':f.receipts[0]['signal_date']='foreign-day'
    elif mutation=='assembly_failure':f.assembly['status']='MEMBERSHIP_FAILED'
    elif mutation=='foreign_source':f.assembly['source_review']={'path':'R6','sha256':'c'*64}
    elif mutation=='missing_artifact':f.refs.pop('predicted_risk')
    with pytest.raises((ValueError,KeyError)):
        m.validate_d01(f.refs,f.journal,f.dates,f.review)


def test_original_classical_request_reuses_complete_exact_cache_and_charges_new_only_once():
    # Only the approved existing source is imported; no constructor/data readers.
    from scripts.research.a2.training import selector_maximal_risk_journal as original
    token='CLASSICAL|C14_D05|2024-01-02T00:00:00';identity={'role':'C14_D05','full_U':'synthetic'}
    result={'chosen_uids':['opaque'],'optimizer_solve_calls':1}
    class Journal:
        def __init__(self):
            self.run='synthetic';self.events=[]
            self.requests={token:dict(status='COMPLETE',charged=1,identity=deepcopy(identity),result=deepcopy(result),
                result_sha256=original.digest(result))}
        def verify(self):pass
        def role_token(self,t):return t.split('|')
        def solve_callback(self,run,t):self.events.append(('ENTER',t));self.requests[t]={'status':'ENTERED','charged':1}
        def complete_solve(self,run,t,**receipt):self.events.append(('COMPLETE',t));self.requests[t].update(status='COMPLETE',**receipt)
        def fail_solve(self,t,error):self.events.append(('FAILED',t));self.requests[t]['status']='FAILED'
    j=Journal()
    cached=original.RiskJournal.classical_request(j,token,identity,lambda:pytest.fail('Completed token re-solved'))
    assert cached==result and cached is not j.requests[token]['result'] and j.events==[]
    with pytest.raises(ValueError):
        original.RiskJournal.classical_request(j,token,{'role':'changed'},lambda:pytest.fail('Changed identity solved'))
    next_token='CLASSICAL|C14_D05|2024-01-03T00:00:00';calls=[]
    original.RiskJournal.classical_request(j,next_token,identity,lambda:calls.append('new') or result)
    original.RiskJournal.classical_request(j,next_token,identity,lambda:pytest.fail('New COMPLETE re-solved'))
    assert calls==['new'] and j.events==[('ENTER',next_token),('COMPLETE',next_token)]
    for status in ('ENTERED','STARTED','FAILED'):
        j.requests[next_token]['status']=status
        with pytest.raises(ValueError):
            original.RiskJournal.classical_request(j,next_token,identity,lambda:pytest.fail('Charged nonCOMPLETE solved'))


def test_new_module_import_has_no_business_owner_imports():
    # Module source itself contains only deferred importlib imports, never a
    # top-level import of execution, native payload, pandas or an estimator.
    import ast
    tree=ast.parse(Path(m.__file__).read_text(encoding='utf-8'))
    roots=[]
    for node in tree.body:
        if isinstance(node,ast.Import): roots.extend(a.name.split('.')[0] for a in node.names)
        elif isinstance(node,ast.ImportFrom): roots.append((node.module or '').split('.')[0])
    assert not set(roots)&{'scripts','numpy','pandas','pyarrow','joblib'}


def terminal_contract():
    value = {key: {} for key in ('source_pins','source_backups','prior_resume_source',
        'original_source_review','runtime_source_review','original_config','qualification',
        'prior_terminal','prior_audit','prior_delta','snapshot_transport','recover_rx_nodes',
        'completed_artifacts','classical_failures','rx_failures','B_freeze','original_publication_admission')}
    value.update(schema=m.TERMINAL_SCHEMA,status='PASS',research_id=m.ID,
        classification='TERMINAL_BOUND_SOURCE_GUARD_ENGINEERING_ONLY',independent_review=True,
        scientific_contract_changed=False,scientific_retry=0,test2026_rows_read=0)
    return value


def test_terminal_review_requires_exact_closed_engineering_authority():
    m.terminal_review_contract(terminal_contract())


@pytest.mark.parametrize('field,value', [('schema','FOREIGN'),('status','PENDING'),
    ('research_id','C15'),('classification','SCIENTIFIC_RETRY'),('independent_review',1),
    ('scientific_contract_changed',0),('scientific_retry',False),('scientific_retry',1),
    ('test2026_rows_read',False),('test2026_rows_read',1),('unexpected',None)])
def test_terminal_review_rejects_arbitrary_partial_or_type_alias_authority(field,value):
    review=terminal_contract();review[field]=value
    with pytest.raises(ValueError,match='INDEPENDENT_TERMINAL'):
        m.terminal_review_contract(review)
    review=terminal_contract();review.pop('prior_terminal')
    with pytest.raises(ValueError,match='INDEPENDENT_TERMINAL'):
        m.terminal_review_contract(review)


@pytest.fixture(scope='module')
def terminal_delta_rows():
    dates=[f'2024-SYNTHETIC-{i:03d}' for i in range(752)]
    rows=[('HEADER',dict(research_id=m.ID,scientific_retry=0))]
    rows.extend(('ACTIVATE_ROLE',dict(role=role,qualification={'marker':role})) for role in m.ACTIVATED)
    rows.extend(('BLOCK_REMAINING',dict(role=role,nodes=[f'{role}|{i}' for i in range(14)],
        reason='UNEXPECTED_ENGINEERING_FAILURE_BEFORE_UNUSED_FITS')) for role in m.RX)
    for role,count in m.TERMINAL_SOLVES.items():
        for day in dates[:count]:
            token=f'CLASSICAL|{role}|{day}'
            identity=dict(research_id=m.ID,design_sha256='a'*64,role=role,family='SYNTHETIC',method='FIXED',
                recipe_sha256='b'*64,risk_metadata_sha256='c'*64,state_ref={'path':'synthetic-native-ref','sha256':'d'*64},
                risk_state_id='synthetic-state',cutoff='2023-12-31',as_of='2024-01-01',decision_asof=day,
                full_U_keys_sha256='e'*64,pair_key_sha256='f'*64,requirement_sha256='1'*64,
                role_qualification_sha256='2'*64)
            result={'opaque_synthetic_result':['quoted \\" } ] {',{'nested':[None,True,1.25]}]}
            receipt=dict(identity=identity,result=result,result_sha256=m.digest(result))
            rows.extend([('SOLVE_ENTER',dict(token=token)),('SOLVE_COMPLETE',dict(receipt=receipt,token=token))])
    return dates,rows


def terminal_rows_bytes(rows,monkeypatch):
    previous='0'*64;lines=[]
    for sequence,(action,data) in enumerate(rows):
        payload=dict(action=action,data=data,previous=previous,sequence=sequence)
        previous=m.digest(payload)
        lines.append(json.dumps(dict(payload,sha256=previous),sort_keys=True,separators=(',',':'),ensure_ascii=False))
    raw=('\n'.join(lines)+'\n').encode()
    monkeypatch.setattr(m,'TERMINAL_DELTA_BYTES',len(raw))
    monkeypatch.setattr(m,'TERMINAL_DELTA_LINES',len(lines))
    monkeypatch.setattr(m,'TERMINAL_DELTA_SHA',hashlib.sha256(raw).hexdigest())
    return raw


def test_terminal_delta_hashes_result_raw_bytes_without_decoding_business_values(terminal_delta_rows,monkeypatch):
    dates,rows=terminal_delta_rows;raw=terminal_rows_bytes(rows,monkeypatch)
    original_loads=json.loads;seen=[]
    def metadata_only(value,*args,**kwargs):
        if isinstance(value,(bytes,bytearray)):
            assert not value.startswith(b'{"opaque_synthetic_result":')
            seen.append(value[:20])
        return original_loads(value,*args,**kwargs)
    monkeypatch.setattr(m.json,'loads',metadata_only)
    audit=m.audit_terminal_delta(raw,dates)
    assert audit['counts']=={'C14_D01':752,'C14_D05':752,'C14_D06':752,'C14_D09':537}
    assert len(audit['requests'])==2793 and audit['sequence']==5597 and seen
    assert all(set(v)=={'identity','result_sha256'} for v in audit['requests'].values())
    assert set(audit['activations'])==set(m.ACTIVATED) and len(audit['blocks'])==2


@pytest.mark.parametrize('mutation',['missing_complete','duplicate_enter','orphan_complete','wrong_result_digest',
    'identity_extra','identity_missing','receipt_extra','enter_extra','foreign_token','hybrid_token',
    'fit_started','solve_failed','duplicate_activation','partial_block','scientific_block','d09_date_gap'])
def test_terminal_delta_refuses_partial_scientific_or_changed_opaque_prefix(terminal_delta_rows,monkeypatch,mutation):
    dates,original=terminal_delta_rows;rows=deepcopy(original)
    if mutation=='missing_complete':rows.pop()
    elif mutation=='duplicate_enter':rows[-1]=deepcopy(rows[-2])
    elif mutation=='orphan_complete':rows[-1][1]['token']='CLASSICAL|C14_D09|'+dates[700]
    elif mutation=='wrong_result_digest':rows[-1][1]['receipt']['result_sha256']='0'*64
    elif mutation=='identity_extra':rows[-1][1]['receipt']['identity']['forecast']=1
    elif mutation=='identity_missing':rows[-1][1]['receipt']['identity'].pop('cutoff')
    elif mutation=='receipt_extra':rows[-1][1]['receipt']['matching_records']=[]
    elif mutation=='enter_extra':rows[-2][1]['entered']=1
    elif mutation=='foreign_token':rows[-2][1]['token']=rows[-1][1]['token']='CLASSICAL|C15|'+dates[0]
    elif mutation=='hybrid_token':rows[-2][1]['token']=rows[-1][1]['token']='HYBRID|C14_RX_HGB_LW|'+dates[0]
    elif mutation in ('fit_started','solve_failed'):rows.append((mutation.upper(),{'token':'forbidden'}))
    elif mutation=='duplicate_activation':rows[2][1]['role']=rows[1][1]['role']
    elif mutation=='partial_block':rows[9][1]['nodes'].pop()
    elif mutation=='scientific_block':rows[9][1]['reason']='SCIENTIFIC_FAILED'
    elif mutation=='d09_date_gap':rows[-2][1]['token']=rows[-1][1]['token']='CLASSICAL|C14_D09|'+dates[537]
    with pytest.raises((ValueError,KeyError)):
        m.audit_terminal_delta(terminal_rows_bytes(rows,monkeypatch),dates)


@pytest.mark.parametrize('mutation',['truncated','crlf','wrong_bytes','wrong_sha','wrong_lines','chain','bool_sequence'])
def test_terminal_delta_requires_exact_physical_prefix_and_canonical_chain(terminal_delta_rows,monkeypatch,mutation):
    dates,rows=terminal_delta_rows;raw=terminal_rows_bytes(rows,monkeypatch)
    if mutation=='truncated':raw=raw[:-1]
    elif mutation=='crlf':raw=raw.replace(b'\n',b'\r\n')
    elif mutation=='wrong_bytes':monkeypatch.setattr(m,'TERMINAL_DELTA_BYTES',len(raw)+1)
    elif mutation=='wrong_sha':monkeypatch.setattr(m,'TERMINAL_DELTA_SHA','0'*64)
    elif mutation=='wrong_lines':monkeypatch.setattr(m,'TERMINAL_DELTA_LINES',5596)
    else:
        lines=raw.splitlines();row=json.loads(lines[1])
        if mutation=='chain':row['previous']='f'*64
        else:row['sequence']=True
        row['sha256']=m.digest({k:v for k,v in row.items() if k!='sha256'})
        lines[1]=json.dumps(row,sort_keys=True,separators=(',',':')).encode()
        raw=b'\n'.join(lines)+b'\n'
        monkeypatch.setattr(m,'TERMINAL_DELTA_BYTES',len(raw))
        monkeypatch.setattr(m,'TERMINAL_DELTA_SHA',hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError):m.audit_terminal_delta(raw,dates)


@pytest.fixture
def terminal_artifacts(monkeypatch,tmp_path):
    run=tmp_path/'run';newroot=run/'risk_execution/source_guard_recovery_r1'
    monkeypatch.setattr(m,'RUN',run);monkeypatch.setattr(m,'TERMINAL_ROOT',newroot)
    monkeypatch.setattr(m,'safe_path',lambda p:Path(p).resolve())
    assembly={field:{} for field in ('panels','predicted_risk','variance_diagnostics')};declared={};pins=[]
    for role in m.TERMINAL_COMPLETE:
        parent=run/'risk_execution/source_metadata_recovery_r1'/role;parent.mkdir(parents=True)
        refs={}
        for name in ('scores_pre2026.parquet','predicted_risk_pre2026.parquet'):
            path=parent/name;path.write_bytes(b'OPAQUE_SYNTHETIC_PARQUET_NOT_DECODED')
            refs[name]=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        assembly['panels'][role]=dict(refs['scores_pre2026.parquet'],calendar_dates=752,rows=1234)
        risk=dict(refs['predicted_risk_pre2026.parquet'],rows=752)
        assembly['predicted_risk'][role]=risk;assembly['variance_diagnostics'][role]=deepcopy(risk)
        declared[role]={field:deepcopy(assembly[field][role]) for field in assembly}
    def physical_pin(ref,**kwargs):
        path=Path(ref['path']);assert hashlib.sha256(path.read_bytes()).hexdigest()==ref['sha256']
        pins.append(deepcopy(ref));return path
    monkeypatch.setattr(m,'pin',physical_pin)
    return SimpleNamespace(run=run,newroot=newroot,assembly=assembly,declared=declared,pins=pins)


def test_six_completed_roles_reuse_only_exact_opaque_original_physical_artifacts(terminal_artifacts):
    f=terminal_artifacts;result=m.terminal_completed_artifacts(f.assembly,f.declared)
    assert result['complete_candidates']==list(m.TERMINAL_COMPLETE) and len(f.pins)==18
    assert result['native_pair_predictions']=={} and result['failed_or_untestable']=={}
    assert result['panels']==f.assembly['panels'] and result['panels'] is not f.assembly['panels']


@pytest.mark.parametrize('mutation',['missing_role','extra_role','short_calendar','short_risk','variance_mismatch',
    'changed_declared','new_root','foreign_root','nonparquet'])
def test_completed_artifacts_refuse_partial_or_arbitrary_reuse(terminal_artifacts,mutation):
    f=terminal_artifacts;role=m.TERMINAL_COMPLETE[0]
    if mutation=='missing_role':f.declared.pop(role)
    elif mutation=='extra_role':f.declared['C15']={}
    elif mutation=='short_calendar':f.assembly['panels'][role]['calendar_dates']=751
    elif mutation=='short_risk':f.assembly['predicted_risk'][role]['rows']=751
    elif mutation=='variance_mismatch':f.assembly['variance_diagnostics'][role]['sha256']='0'*64
    elif mutation=='changed_declared':f.declared[role]['panels']['sha256']='0'*64
    else:
        if mutation=='new_root':path=f.newroot/'forbidden.parquet'
        elif mutation=='foreign_root':path=f.run/'native/forbidden.parquet'
        else:path=f.run/'risk_execution/forbidden.joblib'
        f.assembly['panels'][role]['path']=str(path)
        f.declared[role]['panels']['path']=str(path)
    with pytest.raises((ValueError,KeyError)):m.terminal_completed_artifacts(f.assembly,f.declared)


@pytest.fixture
def terminal_admission(monkeypatch,tmp_path):
    """All physical refs are mock metadata; only synthetic role-directory checks touch disk."""
    run=tmp_path/'run';repo=tmp_path/'repo';root=run/'risk_execution/source_metadata_recovery_r1'
    newroot=run/'risk_execution/source_guard_recovery_r1'
    monkeypatch.setattr(m,'RUN',run);monkeypatch.setattr(m,'REPO',repo);monkeypatch.setattr(m,'ROOT',root)
    monkeypatch.setattr(m,'TERMINAL_ROOT',newroot)
    monkeypatch.setattr(m,'TERMINAL_REVIEW_PATH',run/'C14_TERMINAL_SOURCE_GUARD_RECOVERY_REVIEW_R1.json')
    monkeypatch.setattr(m,'REVIEW_PATH',run/'C14_CHECKPOINT_CLASSICAL_RESUME_REVIEW_R3.json')
    monkeypatch.setattr(m,'__file__',str(repo/'scripts/research/a2/evaluation/selector_maximal_risk_resume.py'))
    monkeypatch.setattr(m,'safe_path',lambda p:Path(p).resolve())
    monkeypatch.setattr(m.sys,'dont_write_bytecode',True)
    registered={};bodies={};reads=[];pins=[];calls=[]
    def register(path,body=None,sha=None):
        ref=dict(path=str(path),sha256=sha or m.digest(body));registered[str(path)]=ref
        if body is not None:bodies[str(path)]=body
        return deepcopy(ref)
    def physical_pin(ref,*,path=None,expected=None):
        assert set(ref)=={'path','sha256'}
        if path is not None:m.need(ref['path']==str(path),'SYNTHETIC_EXACT_PATH_REQUIRED')
        if expected is not None:m.need(ref['sha256']==expected,'SYNTHETIC_EXACT_SHA_REQUIRED')
        m.need(ref==registered.get(ref['path']),'SYNTHETIC_PHYSICAL_PIN_CHANGED')
        pins.append(deepcopy(ref));return Path(ref['path'])
    def metadata_read(ref,**kwargs):
        physical_pin(ref,**kwargs);reads.append(deepcopy(ref));return deepcopy(bodies[ref['path']])
    monkeypatch.setattr(m,'pin',physical_pin);monkeypatch.setattr(m,'read',metadata_read)
    monkeypatch.setattr(m,'no_other_worker',lambda:calls.append('no_other_worker'))
    monkeypatch.setattr(m,'verify_custody',lambda:calls.append('verify_custody'))
    monkeypatch.setattr(m,'validate_transport',lambda value:calls.append(('transport',deepcopy(value))))
    monkeypatch.setattr(m,'original_source_custody',lambda *args:calls.append('original_source_custody'))
    review=terminal_contract();source_paths={}
    for relative,oldsha in m.TERMINAL_SOURCE_BACKUPS.items():
        path=str(repo/'scripts/research/a2'/relative);source_paths[path]=oldsha
        review['source_pins'][path]=register(path,sha='3'*64)['sha256']
        paired=repo/'tests/research/a2'/Path(relative).parent/f'test_{Path(relative).name}'
        review['source_pins'][str(paired)]=register(paired,sha='4'*64)['sha256']
        review['source_backups'][path]=register(run/'source_corrections/C14_TERMINAL_SOURCE_GUARD_RECOVERY_R1'/relative,sha=oldsha)
    for path in (Path(m.__file__),repo/'tests/research/a2/evaluation/test_selector_maximal_risk_resume.py'):
        review['source_pins'][str(path)]=register(path,sha='5'*64)['sha256']
    review['prior_resume_source']=register(run/'source_corrections/C14_TERMINAL_SOURCE_GUARD_RECOVERY_R1/evaluation/selector_maximal_risk_resume.py',
        sha='90f46ae8d3470fbf59e52f1a5c938b422d8e4fe24de1306f7106dfed3bd406e6')
    source_paths[str(repo/'scripts/research/a2/data/untouched.py')]='6'*64
    register(repo/'scripts/research/a2/data/untouched.py',sha='6'*64)
    original=dict(source_pins=source_paths,immutable_inputs={'ML_ASSEMBLY.json':register(run/'ML_ASSEMBLY.json',{'frozen':'opaque'})},
        immutable_config={'fixed':True})
    names={'original_review':'original_source_review','original_config':'original_config','qualification':'qualification',
        'B_freeze':'B_freeze','original_publication_admission':'original_publication_admission'}
    original_ref=dict(path=str(run/'RISK_INPUT_SOURCE_REVIEW_R3.json'),sha256='7'*64)
    gates={r:dict(role=r,source_review=deepcopy(original_ref),full_required_dates_qualified=True) for r in m.QUALIFIED}
    matrix=dict(roles=[{'required_dates':[f'synthetic-{i:03d}' for i in range(752)]}])
    matrix_ref=register(run/'REQUIREMENT_MATRIX.json',matrix)
    current_ref=register(run/'CURRENT_U_BINDINGS.json',{'bindings':{'synthetic':'fixed'}})
    config=dict(source_review=original_ref,requirement_matrix=matrix_ref,current_bindings=current_ref)
    qbody=dict(roles=gates,counts={'native_states_loaded':330})
    fixed_bodies=dict(original_review=original,original_config=config,qualification=qbody,B_freeze={'fixed':29},
        original_publication_admission={'historical_identity':'only'})
    fixed={}
    for key,field in names.items():
        path=Path(original_ref['path']) if key=='original_review' else run/f'{key}.json'
        sha=original_ref['sha256'] if key=='original_review' else m.PINS[key][1]
        review[field]=register(path,fixed_bodies[key],sha=sha);fixed[key]=(path,sha)
    monkeypatch.setattr(m,'PINS',dict(m.PINS,**fixed))
    runtime=deepcopy(original)
    for path in review['source_backups']:runtime['source_pins'][path]=review['source_pins'][path]
    runtime.update(prior_source_review=deepcopy(original_ref),prior_input_qualification=deepcopy(review['qualification']))
    review['runtime_source_review']=register(run/'RISK_INPUT_SOURCE_REVIEW_R4.json',runtime)
    review['snapshot_transport']={'exact_transport':'synthetic-fixed-object'}
    old_ref=register(m.REVIEW_PATH,{'original_review':original_ref},
        sha='cd364aa71a026706d2c7c20b89d7101d9d6eba8815e5d18405c7c89f9e8e59b8')
    register(root/m.MARKER,sha='076c382851deb2cc32f253cca5e90d027338976b77602e2d25c20062e2b48521')
    original_inputs={f'input_{i}':register(run/f'original_input_{i}.json',{'synthetic':i}) for i in range(5)}
    register(run/'DESIGN_FREEZE.json',{'original_design':'fixed','inputs':original_inputs},
        sha='8bdcabcc09817691741d8aaaf7baab8ba663e0360e13cc62b9d918208ff901b6')
    prepared={f'artifact_{i}':register(run/f'prepared_{i}.parquet',sha=f'{i+30:064x}') for i in range(3)}
    prepared_ref=register(run/'INPUT_QUALIFICATION.json',{'artifacts':prepared})
    register(run/'FORMAL_FREEZE_RECEIPT.json',{'input_qualification_sha256':prepared_ref['sha256']},
        sha='00fa18f066358e6cf19f21b27b7bc048575830611e35786d87da55a67caa28f4')
    delta_path=run/'RISK_EXECUTION_DELTA.jsonl';delta_path.parent.mkdir(parents=True,exist_ok=True)
    raw=b'OPAQUE_SYNTHETIC_DELTA_NOT_A_BUSINESS_LEDGER\n';delta_path.write_bytes(raw)
    sha=hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(m,'TERMINAL_DELTA_BYTES',len(raw));monkeypatch.setattr(m,'TERMINAL_DELTA_SHA',sha)
    delta_ref=register(delta_path,sha=sha)
    review['prior_delta']=dict(delta_ref,bytes=len(raw),lines=m.TERMINAL_DELTA_LINES)
    journal=dict(activations={r:{'marker':r} for r in m.ACTIVATED},
        blocks={r:dict(nodes=[f'{r}|{i}' for i in range(14)]) for r in m.RX},requests={},
        counts=dict(m.TERMINAL_SOLVES),sequence=5597,previous='8'*64)
    monkeypatch.setattr(m,'audit_terminal_delta',lambda observed,dates:(m.need(observed==raw,'PREFIX_CHANGED') or deepcopy(journal)))
    def qualification_only(value,*args):
        calls.append(('validate_qualification',deepcopy(args[-1])));return deepcopy(value['roles'])
    monkeypatch.setattr(m,'validate_qualification',qualification_only)
    failure_text='RiskJournalBlocked:PHYSICAL_AUTHORITY_CHANGED:continuous_research_account.py'
    assembly=dict(conditional_delta_ref=delta_ref,role_failure_details={r:failure_text for r in m.TERMINAL_CLASSICAL})
    assembly_ref=register(root/'RISK_DECISIONS_ASSEMBLY.json',assembly)
    gate=dict(conditional_delta_ref=delta_ref,score_assembly_sha256=assembly_ref['sha256'],forecast2026_rows=0,
        outer_labels_read=0,role_failure_details=deepcopy(assembly['role_failure_details']))
    gate_ref=register(root/'RISK_FINAL_PIPELINE.json',gate)
    terminal=dict(status='RISK_DECISIONS_TERMINAL_JOINT_DELIVERY_PENDING',research_id=m.ID,review_ref=original_ref,
        input_qualification=review['qualification'],delta=delta_ref,complete_conditional_roles=list(m.TERMINAL_COMPLETE),
        charged_solves=2793,combined_charged_solves=20799,reserved_fit_slots=28,blocked_fit_slots=28,
        backend_entered=0,complete_fit_slots=0,failed_fit_slots=0,scientific_retry=0,new_risk_estimations=0,
        test2026_rows_read=0,joint_delivery_completed=False,coverage_sufficient_claim_allowed=False,
        strict_PIT_promotion_eligible=False,assembly=assembly_ref,final_pipeline=gate_ref)
    review['prior_terminal']=register(root/'RISK_DECISIONS_TERMINAL_R1.json',terminal,sha=m.TERMINAL_SHA)
    audit=dict(review=old_ref,status='CLASSICAL_ONLY_CHECKPOINT_CONTINUATION_TERMINAL',terminal=review['prior_terminal'],
        original_input_qualification=review['qualification'],RX_reopened=False,preserved_engineering_blocked_fit_slots=28,
        execution_input_counts={'native_states_loaded':243})
    review['prior_audit']=register(root/m.AUDIT,audit,sha=m.TERMINAL_AUDIT_SHA)
    completed=dict(complete_candidates=list(m.TERMINAL_COMPLETE),panels={},predicted_risk={},variance_diagnostics={},
        failed_or_untestable={},native_pair_predictions={})
    review['completed_artifacts']={r:{'opaque':'fixed'} for r in m.TERMINAL_COMPLETE}
    monkeypatch.setattr(m,'terminal_completed_artifacts',lambda observed,declared:deepcopy(completed))
    for role in m.TERMINAL_CLASSICAL:
        path=root/role/'MEMBERSHIP_ASSEMBLY.json';path.parent.mkdir(parents=True);path.write_text('SYNTHETIC_ONLY')
        review['classical_failures'][role]=register(path,dict(status='MEMBERSHIP_FAILED',role=role,failure=failure_text,
            source_review=original_ref,scientific_retry=0,forecast2026_rows=0))
    for role in m.RX:
        review['rx_failures'][role]=register(root/role/'ENGINEERING_FAILURE_R1.json',
            {'error_type':'ValueError','error':'PIN_CHANGED:continuous_research_account.py'},sha=m.FAILURE_SHA)
    review['recover_rx_nodes']=sorted(n for block in journal['blocks'].values() for n in block['nodes'])
    monkeypatch.setattr(m,'validate_rx_artifacts',lambda role,nodes,path:calls.append(('validate_rx',role,deepcopy(nodes))))
    review_ref=register(m.TERMINAL_REVIEW_PATH,review,sha='9'*64)
    return SimpleNamespace(run=run,root=root,newroot=newroot,repo=repo,review=review,review_ref=review_ref,
        original=original,runtime=runtime,gates=gates,terminal=terminal,audit=audit,assembly=assembly,gate=gate,
        registered=registered,bodies=bodies,reads=reads,pins=pins,calls=calls,journal=journal,completed=completed,
        register=register,raw=raw)


def test_terminal_admission_seals_exact_review_source_bridge_history_and_old_qualification(terminal_admission):
    f=terminal_admission;value=m.admit_terminal_recovery(f.review_ref)
    assert value['runtime']==f.runtime and value['gates']==f.gates and value['journal']==f.journal
    assert m._TERMINAL_AUTHORITY==f.review_ref and m._TERMINAL_AUTHORITY is not f.review_ref
    assert m._TERMINAL_TRANSPORT_SEAL==m.digest(f.review['snapshot_transport'])
    assert f.calls.count('no_other_worker')==2 and len([v for v in f.calls if isinstance(v,tuple) and v[0]=='validate_rx'])==2
    assert not f.newroot.exists() and f.root.exists()
    assert {'path':str(f.run/'RISK_EXECUTION_DELTA.jsonl'),'sha256':m.TERMINAL_DELTA_SHA} in f.pins
    with pytest.raises(ValueError,match='SINGLE_USE'):m.admit_terminal_recovery(f.review_ref)


@pytest.mark.parametrize('mutation',['foreign_review_ref','wrong_terminal_pin','wrong_audit_pin','wrong_qualification_ref',
    'missing_source','extra_source','missing_source_backup','changed_backup_pin','source_bridge_extra',
    'source_bridge_immutable','source_bridge_bool','runtime_prior_ref','config_prior_ref','delta_count','delta_hash',
    'terminal_status','terminal_partial','terminal_entered','terminal_retry','terminal_joint','terminal_review_ref',
    'audit_reopened','audit_partial','assembly_delta','gate_outer_label','gate_assembly','missing_classical',
    'classical_science','classical_source','classical_extra_artifact','missing_rx','rx_science','rx_node_short'])
def test_terminal_admission_rejects_foreign_partial_or_entered_recovery(terminal_admission,mutation):
    f=terminal_admission;review=f.review;ref=deepcopy(f.review_ref)
    if mutation=='foreign_review_ref':ref['path']=str(f.run/'ARBITRARY_PASS.json')
    elif mutation=='wrong_terminal_pin':review['prior_terminal']['sha256']='0'*64
    elif mutation=='wrong_audit_pin':review['prior_audit']['sha256']='0'*64
    elif mutation=='wrong_qualification_ref':review['qualification']['path']=str(f.run/'fake_qualification.json')
    elif mutation=='missing_source':review['source_pins'].pop(next(iter(review['source_pins'])))
    elif mutation=='extra_source':review['source_pins'][str(f.repo/'scripts/foreign.py')]='0'*64
    elif mutation=='missing_source_backup':review['source_backups'].pop(next(iter(review['source_backups'])))
    elif mutation=='changed_backup_pin':next(iter(review['source_backups'].values()))['sha256']='0'*64
    elif mutation=='source_bridge_extra':f.runtime['source_pins'][str(f.repo/'scripts/research/a2/data/untouched.py')]='0'*64
    elif mutation=='source_bridge_immutable':f.runtime['immutable_inputs']['extra']={'path':'fake','sha256':'0'*64}
    elif mutation=='source_bridge_bool':f.runtime['immutable_config']['fixed']=1
    elif mutation=='runtime_prior_ref':f.runtime['prior_source_review']={'path':'other','sha256':'0'*64}
    elif mutation=='config_prior_ref':f.bodies[review['original_config']['path']]['source_review']={'path':'R4'}
    elif mutation=='delta_count':review['prior_delta']['lines']-=1
    elif mutation=='delta_hash':review['prior_delta']['sha256']='0'*64
    elif mutation=='terminal_status':f.terminal['status']='RUNNING'
    elif mutation=='terminal_partial':f.terminal['complete_conditional_roles'].pop()
    elif mutation=='terminal_entered':f.terminal['backend_entered']=1
    elif mutation=='terminal_retry':f.terminal['scientific_retry']=1
    elif mutation=='terminal_joint':f.terminal['joint_delivery_completed']=True
    elif mutation=='terminal_review_ref':f.terminal['review_ref']={'path':'R4'}
    elif mutation=='audit_reopened':f.audit['RX_reopened']=True
    elif mutation=='audit_partial':f.audit['preserved_engineering_blocked_fit_slots']=27
    elif mutation=='assembly_delta':f.assembly['conditional_delta_ref']={'path':'other'}
    elif mutation=='gate_outer_label':f.gate['outer_labels_read']=1
    elif mutation=='gate_assembly':f.gate['score_assembly_sha256']='0'*64
    elif mutation=='missing_classical':review['classical_failures'].pop('C14_D11')
    elif mutation=='classical_science':f.bodies[review['classical_failures']['C14_D09']['path']]['failure']='SCIENTIFIC_FAILURE'
    elif mutation=='classical_source':f.bodies[review['classical_failures']['C14_D09']['path']]['source_review']={'path':'R4'}
    elif mutation=='classical_extra_artifact':(f.root/'C14_D09/partial.parquet').write_bytes(b'FORBIDDEN_SYNTHETIC')
    elif mutation=='missing_rx':review['rx_failures'].pop(m.RX[0])
    elif mutation=='rx_science':f.bodies[review['rx_failures'][m.RX[0]]['path']]['error']='FAILED_FIT'
    elif mutation=='rx_node_short':review['recover_rx_nodes'].pop()
    with pytest.raises((ValueError,KeyError)):m.admit_terminal_recovery(ref)
    assert not f.newroot.exists()


def test_terminal_admission_rejects_parallel_worker_or_existing_output_before_any_metadata(terminal_admission,monkeypatch):
    f=terminal_admission
    def worker_present():raise ValueError('PARALLEL_WORKER')
    monkeypatch.setattr(m,'no_other_worker',worker_present)
    with pytest.raises(ValueError,match='PARALLEL_WORKER'):m.admit_terminal_recovery(f.review_ref)
    assert not f.reads
    monkeypatch.setattr(m,'no_other_worker',lambda:None);f.newroot.mkdir(parents=True)
    with pytest.raises(ValueError,match='ONE_SHOT'):m.admit_terminal_recovery(f.review_ref)
    assert not f.reads


def terminal_inputs(f):
    class Inputs:
        def __init__(self,*args,source_review=None,source_review_ref=None):
            self._qualified=False;self._gates={};self._cache={};self._failed={}
            self.counts={'risk_numeric_read':0,'selector_fit':0,'solver':0}
            self.requirements={r:{} for r in m.QUALIFIED};self.review=source_review or deepcopy(f.runtime)
            self.review_ref=source_review_ref or deepcopy(f.review['runtime_source_review']);self.verified=[]
        def _verify(self,**kwargs):self.verified.append(kwargs)
        def qualify(self):pytest.fail('Native numeric qualification replay forbidden')
        def get_risk(self,*args):pytest.fail('Synthetic owner metadata restore must not read native')
        def status(self):return {'counts':deepcopy(self.counts),'roles':deepcopy(self._gates)}
    return Inputs


def test_terminal_prior_gates_restore_requires_real_formal_r4_and_original_body(terminal_admission):
    f=terminal_admission;m.admit_terminal_recovery(f.review_ref)
    Inputs=terminal_inputs(f);inputs=Inputs();owner=SimpleNamespace(input_owner=SimpleNamespace(RiskInputs=Inputs))
    m.restore_input_gates(inputs,f.gates,owner,prior_review_ref=f.review['original_source_review'])
    assert inputs._qualified and inputs._gates==f.gates and inputs._gates is not f.gates
    assert inputs.verified==[{'full':True},{'full':True}] and not any(inputs.counts.values())
    assert f.review['runtime_source_review'] in f.reads and f.review['qualification'] in f.reads


@pytest.mark.parametrize('mutation',['no_authority','formal_pin','formal_contract','foreign_prior_ref','runtime_ref',
    'runtime_body','runtime_prior','runtime_qualification','qualification_body','gate_type_alias','entered','cache','fake_owner'])
def test_terminal_gate_transport_refuses_unsealed_or_changed_authority(terminal_admission,mutation):
    f=terminal_admission;m.admit_terminal_recovery(f.review_ref)
    Inputs=terminal_inputs(f);inputs=Inputs();owner=SimpleNamespace(input_owner=SimpleNamespace(RiskInputs=Inputs))
    gates=deepcopy(f.gates);prior=deepcopy(f.review['original_source_review'])
    if mutation=='no_authority':m._TERMINAL_AUTHORITY=None
    elif mutation=='formal_pin':f.registered[f.review_ref['path']]['sha256']='0'*64
    elif mutation=='formal_contract':f.review['independent_review']=False
    elif mutation=='foreign_prior_ref':prior={'path':'foreign_R3','sha256':'0'*64}
    elif mutation=='runtime_ref':inputs.review_ref={'path':'R6','sha256':'0'*64}
    elif mutation=='runtime_body':inputs.review['immutable_config']['fixed']=1
    elif mutation=='runtime_prior':inputs.review['prior_source_review']={'path':'foreign'}
    elif mutation=='runtime_qualification':inputs.review['prior_input_qualification']={'path':'foreign'}
    elif mutation=='qualification_body':f.bodies[f.review['qualification']['path']]['roles'][m.QUALIFIED[0]]['role']='C15'
    elif mutation=='gate_type_alias':gates[m.QUALIFIED[0]]['full_required_dates_qualified']=1
    elif mutation=='entered':inputs.counts['selector_fit']=1
    elif mutation=='cache':inputs._cache['native']='present'
    elif mutation=='fake_owner':owner.input_owner.RiskInputs=type('WrongOwner',(),{})
    with pytest.raises((ValueError,KeyError)):
        m.restore_input_gates(inputs,gates,owner,prior_review_ref=prior)
    assert inputs._qualified is False and inputs._gates=={}


@pytest.fixture
def terminal_boundary():
    requests={}
    for role,count in m.TERMINAL_SOLVES.items():
        for i in range(count):
            token=f'CLASSICAL|{role}|synthetic-{i:03d}'
            requests[token]=dict(status='COMPLETE',charged=1,identity={'role':role,'day':i},result_sha256=f'{i:064x}')
    slots={f'node-{i}':dict(status='BLOCKED_DEPENDENCY' if i<28 else 'UNRESERVED',entered=0) for i in range(144)}
    calls=[]
    journal=SimpleNamespace(sequence=5597,previous='e'*64,requests=requests,slots=slots,
        _source_guard_zero_entry_state=lambda data:calls.append(('state',deepcopy(data))),
        _source_guard_artifact_absent=lambda nodes:calls.append(('artifacts',deepcopy(nodes))),
        verify=lambda:calls.append(('verify',)))
    prior={t:{k:v[k] for k in ('identity','result_sha256')} for t,v in requests.items()}
    admission=dict(journal=dict(sequence=5597,previous='e'*64,requests=deepcopy(prior)),
        review_ref={'path':'review','sha256':'f'*64},review={'recover_rx_nodes':[f'node-{i}' for i in range(28)]})
    return SimpleNamespace(journal=journal,admission=admission,calls=calls)


def test_terminal_journal_boundary_checks2793_complete_identity_digest_and_original28_without_append(terminal_boundary):
    f=terminal_boundary;m.terminal_journal_boundary(f.journal,f.admission)
    assert [v[0] for v in f.calls]==['state','artifacts','verify']
    assert f.calls[0][1]['nodes']==f.admission['review']['recover_rx_nodes']
    assert len(f.journal.requests)==2793 and len(f.journal.slots)==144


@pytest.mark.parametrize('mutation',['sequence','previous','partial','entered','entered_bool','block_status',
    'charged_started','charged_failed','charge_count','identity','identity_type','digest','missing_prior'])
def test_terminal_journal_refuses_started_failed_entered_or_nonexact_cache(terminal_boundary,mutation):
    f=terminal_boundary;j=f.journal;token=next(iter(j.requests));request=j.requests[token]
    if mutation=='sequence':j.sequence-=1
    elif mutation=='previous':j.previous='0'*64
    elif mutation=='partial':j.requests.pop(token)
    elif mutation=='entered':j.slots['node-0']['entered']=1
    elif mutation=='entered_bool':j.slots['node-0']['entered']=False
    elif mutation=='block_status':j.slots['node-0']['status']='FAILED'
    elif mutation=='charged_started':request['status']='STARTED'
    elif mutation=='charged_failed':request['status']='FAILED'
    elif mutation=='charge_count':request['charged']=2
    elif mutation=='identity':request['identity']['role']='C15'
    elif mutation=='identity_type':request['identity']['day']=False
    elif mutation=='digest':request['result_sha256']='f'*64
    elif mutation=='missing_prior':f.admission['journal']['requests'].pop(token)
    with pytest.raises(ValueError):m.terminal_journal_boundary(j,f.admission)
    assert not f.calls


@pytest.fixture
def terminal_runtime(terminal_admission,monkeypatch):
    f=terminal_admission;events=[];constructed=[];publication=object()
    for role in m.TERMINAL_COMPLETE:
        panel=dict(path=str(f.root/role/'scores_pre2026.parquet'),sha256='a'*64,calendar_dates=752)
        risk=dict(path=str(f.root/role/'predicted_risk_pre2026.parquet'),sha256='b'*64,rows=752)
        f.completed['panels'][role]=panel;f.completed['predicted_risk'][role]=risk
        f.completed['variance_diagnostics'][role]=deepcopy(risk)
    admission=m.admit_terminal_recovery(f.review_ref)
    monkeypatch.setattr(m,'admit_terminal_recovery',lambda ref:admission)
    modules={'synthetic_transport':object()}
    monkeypatch.setattr(m,'load_snapshots',lambda transport:events.append(('load_snapshots',transport)) or modules)
    monkeypatch.setattr(m,'verify_downstream_bindings',lambda *args:events.append(('verify_downstream',)))
    monkeypatch.setattr(m,'executable_snapshot_guard',lambda *args:nullcontext())
    monkeypatch.setattr(m,'terminal_journal_boundary',lambda *args:events.append(('journal_boundary',)))
    monkeypatch.setattr(m,'bind_runtime_custody',lambda journal:events.append(('bind_runtime_custody',)))
    def publication_preflight(*args):
        assert not f.newroot.exists()
        events.append(('publication_preflight',));return {'publication':publication},{'source_only':'fixed'}
    monkeypatch.setattr(m,'publication_metadata_preflight',publication_preflight)
    class Journal:
        def __init__(self,run,**kwargs):
            assert run==f.run and kwargs=={'source_guard_recovery_ref':f.review_ref}
            self.slots={};self.recoveries=[];events.append(('journal_construct',kwargs))
        def verify(self):events.append(('journal_verify',))
        def recover_source_guard_zero_entry(self,ref):
            marker=f.newroot/m.TERMINAL_MARKER
            assert marker.exists() and json.loads(marker.read_text())['review']==f.review_ref
            assert not self.recoveries and ref==f.review_ref
            self.recoveries.append(deepcopy(ref));events.append(('recover_original28',))
            return deepcopy(f.review['recover_rx_nodes'])
    BaseInputs=terminal_inputs(f)
    class Inputs(BaseInputs):
        def __init__(self,pub,matrix,current,raw_meta,**kwargs):
            assert pub is publication and kwargs['source_review_ref']==f.review['runtime_source_review']
            assert kwargs['source_review']==f.runtime and raw_meta=={'synthetic_raw_meta':True}
            super().__init__(source_review=kwargs['source_review'],source_review_ref=kwargs['source_review_ref'])
            constructed.append(self);events.append(('input_owner_construct_R4',))
    q={'artifacts':{key:dict(path=str(f.run/(key+'.parquet')),sha256='c'*64,rows=1234)
        for key in ('raw_current','pair_geometry','current_pair_features')}}
    def project(*args,**kwargs):
        assert (f.newroot/m.TERMINAL_MARKER).exists()
        assert ('recover_original28',) in events
        assert kwargs==dict(start='2023-01-01',stop='2026-01-01',run=f.run)
        events.append(('raw_metadata_projection',));return {'synthetic_raw_meta':True}
    ctl=SimpleNamespace(REPO=f.repo,checked=lambda run:({}, {'frozen_design':True},q),
        footer=lambda ref:events.append(('footer',deepcopy(ref))),project=project,now=lambda:'SYNTHETIC_TIME',
        pin=lambda ref:ref['path'],PAIR_KEYS=('pair',),feature_order=lambda:[f'f{i}' for i in range(216)],
        runtime_for=lambda *args:'frozen-runtime',runtime_parts=lambda runtime:('fixed-runtime',))
    class Dates:
        def lt(self,limit):
            assert limit=='2026-01-01';return SimpleNamespace(all=lambda:True)
    class Frame:
        signal_date=Dates()
        def __getitem__(self,keys):return self
        def equals(self,other):return True
        def to_numpy(self,kind):assert kind is float;return ['SYNTHETIC_FEATURES']
    def read_table(path):
        assert constructed and constructed[0]._qualified and not any(constructed[0].counts.values())
        events.append(('synthetic_prepared_read',path));return SimpleNamespace(to_pandas=lambda:Frame())
    def parquet_file(path):
        return SimpleNamespace(metadata=SimpleNamespace(num_rows=1234 if Path(path).name=='scores_pre2026.parquet' else 752))
    def stage(path,status,**details):events.append(('stage',status,deepcopy(details)))
    def hybrid(*args,**kwargs):
        assert kwargs=={'artifact_root':f.newroot}
        assert args[6] in m.RX and constructed[0]._qualified
        events.append(('original_hybrid_owner',args[6]))
        return dict(complete_candidates=[args[6]],failed_or_untestable={},panels={},native_pair_predictions={})
    member_path=f.repo/'scripts/research/a2/training/selector_maximal_risk_membership.py'
    def membership_kernel(*args,**kwargs):
        assert args[0]==f.run and args[-1]==f.review['runtime_source_review']
        assert kwargs['artifact_root']==f.newroot and kwargs['qualification_ref']==f.review['qualification']
        assert kwargs['role_gates']==constructed[0]._gates
        events.append(('original_membership_owner',))
        return dict(complete_candidates=list(m.TERMINAL_CLASSICAL),failed_or_untestable={},panels={},native_pair_predictions={})
    member_function=object()
    def bind_kernel(function,**kwargs):
        assert function is member_function and kwargs['physical_path']==str(member_path)
        assert kwargs['expected_sha256']==f.runtime['source_pins'][str(member_path)]
        assert kwargs['dependencies']=={'ROLES':m.TERMINAL_CLASSICAL}
        events.append(('bind_original_membership_only_unfinished',));return membership_kernel
    membership=SimpleNamespace(ROLES=(*m.CLASSICAL,'C14_D02','C14_G1','C14_G4'),__file__=str(member_path),
        execute_membership=member_function,event=SimpleNamespace(bind_pinned_kernel=bind_kernel))
    def terminal(*args,**kwargs):
        assert args[4]==admission['values']['qualification'] and args[-1]==f.review['runtime_source_review']
        assert kwargs==dict(artifact_root=f.newroot,input_qualification_ref=f.review['qualification'])
        assert args[5][0]==admission['completed'] and len(args[5])==4
        events.append(('original_terminal_owner',))
        return dict(status='RISK_DECISIONS_TERMINAL_JOINT_DELIVERY_PENDING',complete_conditional_roles=['SYNTHETIC'],
            charged_solves=4512,backend_entered=28)
    execution=SimpleNamespace(reviewed_sources=lambda ref:deepcopy(f.runtime),
        frozen_test_configuration=lambda review:nullcontext(),validate_start=lambda *args:({'synthetic':'matrix'},{'synthetic':'current'}),
        ctl=ctl,evidence=SimpleNamespace(validate_design=lambda value:events.append(('validate_design',))),
        journal_owner=SimpleNamespace(RiskJournal=Journal),pq=SimpleNamespace(ParquetFile=parquet_file,read_table=read_table),
        resolve=lambda repo:'SYNTHETIC_PATHS',assert_safe_output_path=lambda *args,**kwargs:events.append(('safe_new_root',)),
        stage=stage,current_owner=SimpleNamespace(RAW_META=('signal_date',)),input_owner=SimpleNamespace(RiskInputs=Inputs),
        pd=SimpleNamespace(to_datetime=lambda value:value),hybrids=SimpleNamespace(ROLES=m.RX,execute_hybrid=hybrid),
        kernel=object(),membership=membership,terminal=terminal,read_exact=lambda ref:{'opaque_frozen_ML':True},
        ref=lambda path:dict(path=str(path),sha256='d'*64),put=lambda path,body:events.append(('put',str(path),deepcopy(body))))
    original_import=m.importlib.import_module
    def owner_import(name,*args,**kwargs):
        if name=='scripts.research.a2.evaluation.selector_maximal_risk_execution':return execution
        if name=='scripts.research.a2.evaluation.selector_account_compare':return SimpleNamespace()
        return original_import(name,*args,**kwargs)
    monkeypatch.setattr(m.importlib,'import_module',owner_import)
    return SimpleNamespace(f=f,admission=admission,execution=execution,events=events,constructed=constructed,q=q)


def test_terminal_validate_only_stops_before_marker_recovery_data_fit_or_solve(terminal_runtime,monkeypatch):
    f=terminal_runtime
    monkeypatch.setattr(f.execution.ctl,'project',lambda *args,**kwargs:pytest.fail('Numeric/prepared input after validate-only'))
    monkeypatch.setattr(f.execution,'resolve',lambda *args:pytest.fail('Output allocation after validate-only'))
    monkeypatch.setattr(f.execution.input_owner,'RiskInputs',lambda *args,**kwargs:pytest.fail('Input owner after validate-only'))
    monkeypatch.setattr(f.execution.pq,'read_table',lambda *args:pytest.fail('Prepared values after validate-only'))
    value=m.resume_terminal_recovery(f.f.review_ref,validate_only=True)
    assert value['status']=='PASS_TERMINAL_SOURCE_GUARD_ENGINEERING_ADMISSION'
    assert value['historical_qualification_native_reads']==330 and value['prior_worker_execution_native_reads']==243
    assert all(value[k]==0 for k in ('preflight_new_native_numeric_reads','new_fit','new_solve','new_risk_estimation','scientific_retry','test2026_rows_read'))
    assert value['joint_delivery_completed'] is False and value['coverage_sufficient_claim_allowed'] is False
    assert not f.f.newroot.exists() and not f.constructed
    assert ('publication_preflight',) in f.events and ('bind_runtime_custody',) in f.events
    assert not any(event[0] in {'recover_original28','raw_metadata_projection','original_hybrid_owner','original_membership_owner','original_terminal_owner','put'} for event in f.events)
    assert f.f.calls.count('no_other_worker')>=3


def test_terminal_runtime_marker_precedes_only_original28_restore_and_original_owners(terminal_runtime):
    f=terminal_runtime;old_files={p:p.read_bytes() for p in f.f.root.glob('*/MEMBERSHIP_ASSEMBLY.json')}
    value=m.resume_terminal_recovery(f.f.review_ref)
    labels=[event[0] for event in f.events]
    assert labels.index('publication_preflight')<labels.index('recover_original28')<labels.index('raw_metadata_projection')
    assert labels.index('input_owner_construct_R4')<labels.index('synthetic_prepared_read')<labels.index('original_hybrid_owner')
    assert labels.count('recover_original28')==1 and labels.count('original_hybrid_owner')==2
    assert labels.count('original_membership_owner')==labels.count('original_terminal_owner')==1
    inputs=f.constructed[0]
    assert inputs._qualified and inputs._gates==f.f.gates and not any(inputs.counts.values())
    assert inputs.review_ref==f.f.review['runtime_source_review'] and inputs.verified==[{'full':True},{'full':True}]
    marker=json.loads((f.f.newroot/m.TERMINAL_MARKER).read_text())
    assert marker['original_RX_nodes']==f.f.review['recover_rx_nodes'] and marker['scientific_retry']==0
    assert marker['runtime_source_review']==f.f.review['runtime_source_review']
    assert all(p.read_bytes()==raw for p,raw in old_files.items())
    assert value['joint_delivery_completed'] is False and value['terminal']['path'].startswith(str(f.f.newroot))
    audits=[event for event in f.events if event[0]=='put' and event[1].endswith(m.TERMINAL_AUDIT)]
    assert len(audits)==1 and audits[0][2]['original_input_qualification']==f.f.review['qualification']
    assert audits[0][2]['preserved_prior_engineering_failures']==dict(f.f.review['classical_failures'],**f.f.review['rx_failures'])


@pytest.mark.parametrize('failure',['runtime_review','parallel_worker','footer','publication','runtime_custody'])
def test_terminal_runtime_preflight_failure_cannot_create_marker_or_recover_slots(terminal_runtime,monkeypatch,failure):
    f=terminal_runtime
    def blocked(*args,**kwargs):raise ValueError('SYNTHETIC_PREFLIGHT_BLOCK')
    if failure=='runtime_review':monkeypatch.setattr(f.execution,'reviewed_sources',lambda ref:dict(f.f.runtime,foreign=True))
    elif failure=='parallel_worker':monkeypatch.setattr(m,'no_other_worker',blocked)
    elif failure=='footer':monkeypatch.setattr(f.execution.ctl,'footer',blocked)
    elif failure=='publication':monkeypatch.setattr(m,'publication_metadata_preflight',blocked)
    elif failure=='runtime_custody':monkeypatch.setattr(m,'bind_runtime_custody',blocked)
    with pytest.raises(ValueError):m.resume_terminal_recovery(f.f.review_ref)
    assert not f.f.newroot.exists() and not f.constructed
    assert not any(event[0]=='recover_original28' for event in f.events)


def post_reboot_contract():
    value = {key:{} for key in ('source_pins','source_backups','original_source_guard_review',
        'prior_runtime_source_review','runtime_source_review','checkpoint_delta','old_recovery_event',
        'old_marker','reboot_receipt','input_qualification','completed_fit_artifacts','completed_role_artifacts',
        'snapshot_transport','execution_configuration','B_freeze','original_publication_admission',
        'independent_RX_completion')}
    value.update(schema=m.POST_REBOOT_SCHEMA,status='PASS',research_id=m.ID,
        classification='POST_REBOOT_CLASSICAL_ONLY_CHECKPOINT_ENGINEERING',independent_review=True,
        scientific_contract_changed=False,scientific_retry=0,test2026_rows_read=0,
        remaining_classical_roles=list(m.TERMINAL_CLASSICAL))
    return value


def test_post_reboot_closed_contract_and_exact_four_source_backup_paths():
    m.post_reboot_review_contract(post_reboot_contract())
    paths=m.post_reboot_source_paths()
    assert len(paths)==4
    assert {Path(p).name for p in paths}=={'selector_maximal_risk_resume.py','selector_maximal_risk_journal.py',
        'test_selector_maximal_risk_resume.py','test_selector_maximal_risk_journal.py'}
    assert all('D:'==Path(p).drive for p in paths)


@pytest.mark.parametrize('field,value',[('schema','FOREIGN'),('status','PENDING'),('research_id','C15'),
    ('classification','RX_RETRY'),('independent_review',1),('scientific_contract_changed',0),
    ('scientific_retry',False),('scientific_retry',1),('test2026_rows_read',False),('test2026_rows_read',1),
    ('remaining_classical_roles',['C14_D01','C14_D09','C14_D10','C14_D11'])])
def test_post_reboot_contract_refuses_aliases_science_or_extra_roles(field,value):
    review=post_reboot_contract();review[field]=value
    with pytest.raises(ValueError):m.post_reboot_review_contract(review)


@pytest.fixture(scope='module')
def post_reboot_rows(terminal_delta_rows):
    dates,oldrows=terminal_delta_rows;rows=deepcopy(oldrows)
    nodes=sorted(f'RX_MODEL|{role}|2023-12-31|SYNTHETIC_{i}|20260928|None' for role in m.RX for i in range(14))
    for index,role in enumerate(m.RX):
        rows[9+index][1]['nodes']=[n for n in nodes if '|'+role+'|' in n]
    oldref={'path':'SYNTHETIC_OLD_FORMAL','sha256':'7'*64}
    rows.append(('SOURCE_GUARD_ZERO_ENTRY',dict(nodes=nodes,review_ref=oldref)))
    for node in nodes:
        identity=dict(cutoff='2023-12-31',opaque_capacity_selection='NEVER_DECODE_FIT_SELECTION')
        artifact=dict(path='SYNTHETIC_MODELS/'+m.digest(node)+'.joblib',sha256='8'*64)
        rows.extend([('FIT_BEGIN',dict(node=node,identity=identity)),
            ('FIT_ENTER',dict(node=node,event={'opaque':'NEVER_DECODE_BACKEND_VALUE'})),
            ('FIT_FINISH',dict(node=node,status='COMPLETE',details={'artifact':artifact}))])
    for role in m.RX:
        for day in dates[250:]:
            token='HYBRID|'+role+'|'+day
            identity=dict(design_sha256='a'*64,pair_key_sha256='b'*64,candidate_id=role,
                full_U_keys_sha256='c'*64,score_sha256='d'*64,eligibility_sha256='e'*64)
            matching=[{'OPAQUE_MATCHING_VALUES':'NEVER_DECODE_MATCHING'}]
            receipt=dict(identity=identity,matching_records=matching,matching_sha256=m.digest(matching))
            rows.extend([('SOLVE_ENTER',dict(token=token)),('SOLVE_COMPLETE',dict(token=token,receipt=receipt))])
    template=deepcopy(oldrows[-1][1]['receipt'])
    for day in dates[537:608]:
        token='CLASSICAL|C14_D09|'+day;receipt=deepcopy(template)
        receipt['identity']['decision_asof']=day
        rows.extend([('SOLVE_ENTER',dict(token=token)),('SOLVE_COMPLETE',dict(token=token,receipt=receipt))])
    return dates,rows,oldref,nodes


def post_reboot_rows_bytes(rows,monkeypatch):
    old=terminal_rows_bytes(rows[:5597],monkeypatch)
    previous='0'*64;lines=[]
    for sequence,(action,data) in enumerate(rows):
        payload=dict(action=action,data=data,previous=previous,sequence=sequence);previous=m.digest(payload)
        lines.append(json.dumps(dict(payload,sha256=previous),sort_keys=True,separators=(',',':'),ensure_ascii=False))
    raw=('\n'.join(lines)+'\n').encode()
    assert raw.startswith(old)
    monkeypatch.setattr(m,'POST_REBOOT_DELTA_BYTES',len(raw))
    monkeypatch.setattr(m,'POST_REBOOT_DELTA_LINES',len(lines))
    monkeypatch.setattr(m,'POST_REBOOT_DELTA_SHA',hashlib.sha256(raw).hexdigest())
    return raw


def test_post_reboot_opaque_audit_closed3868_fit28_and_never_decodes_values(post_reboot_rows,monkeypatch):
    dates,rows,oldref,nodes=post_reboot_rows;raw=post_reboot_rows_bytes(rows,monkeypatch)
    original=json.loads
    def metadata_only(value,*args,**kwargs):
        if isinstance(value,(bytes,bytearray)):
            assert b'NEVER_DECODE_FIT_SELECTION' not in value
            assert b'NEVER_DECODE_BACKEND_VALUE' not in value
            assert b'NEVER_DECODE_MATCHING' not in value
            assert not value.startswith(b'{"opaque_synthetic_result":')
        return original(value,*args,**kwargs)
    monkeypatch.setattr(m.json,'loads',metadata_only)
    audit=m.audit_post_reboot_delta(raw,dates,oldref,nodes)
    assert audit['sequence']==7832 and audit['counts']==m.POST_REBOOT_SOLVES
    assert len(audit['fits'])==28 and len(audit['requests'])==3868
    assert audit['actions']['SOURCE_GUARD_ZERO_ENTRY']==1
    assert all(set(f)=={'status','entered','identity_sha256','artifact'} for f in audit['fits'].values())


@pytest.mark.parametrize('mutation',['missing_complete','duplicate_enter','cache_hash','foreign_classical',
    'wrong_RX_role','RX_date_gap','d09_gap','fit_failed','fit_unfinished','duplicate_fit_entry',
    'fit_artifact_missing','fit_wrong_cutoff','second_recovery','changed_recovery','new_activation',
    'charged_failure','extra_receipt','bool_sequence'])
def test_post_reboot_audit_refuses_every_retry_open_or_changed_checkpoint(post_reboot_rows,monkeypatch,mutation):
    dates,original,oldref,nodes=post_reboot_rows;rows=deepcopy(original)
    firsthybrid=5597+1+28*3
    if mutation=='missing_complete':rows.pop()
    elif mutation=='duplicate_enter':rows[-1]=deepcopy(rows[-2])
    elif mutation=='cache_hash':rows[firsthybrid+1][1]['receipt']['matching_sha256']='0'*64
    elif mutation=='foreign_classical':
        rows[-2][1]['token']=rows[-1][1]['token']='CLASSICAL|C14_D10|'+dates[0]
    elif mutation=='wrong_RX_role':rows[firsthybrid+1][1]['receipt']['identity']['candidate_id']=m.RX[1]
    elif mutation=='RX_date_gap':
        rows[firsthybrid][1]['token']=rows[firsthybrid+1][1]['token']='HYBRID|'+m.RX[0]+'|'+dates[0]
    elif mutation=='d09_gap':rows[-2][1]['token']=rows[-1][1]['token']='CLASSICAL|C14_D09|'+dates[608]
    elif mutation=='fit_failed':rows[5600][1]['status']='FAILED'
    elif mutation=='fit_unfinished':rows.pop(5600)
    elif mutation=='duplicate_fit_entry':rows[5600]=deepcopy(rows[5599])
    elif mutation=='fit_artifact_missing':rows[5600][1]['details']={}
    elif mutation=='fit_wrong_cutoff':rows[5598][1]['identity']['cutoff']='2025-12-31'
    elif mutation=='second_recovery':rows.append(deepcopy(rows[5597]))
    elif mutation=='changed_recovery':rows[5597][1]['nodes']=nodes[:-1]
    elif mutation=='new_activation':rows.append(('ACTIVATE_ROLE',dict(role='C14_D10',qualification={})))
    elif mutation=='charged_failure':rows[-1]=('SOLVE_FAILED',dict(token=rows[-1][1]['token'],error='failure'))
    elif mutation=='extra_receipt':rows[-1][1]['receipt']['charged']=0
    raw=post_reboot_rows_bytes(rows,monkeypatch)
    if mutation=='bool_sequence':
        lines=raw.splitlines();row=json.loads(lines[5597]);row['sequence']=True
        row['sha256']=m.digest({k:v for k,v in row.items() if k!='sha256'})
        lines[5597]=json.dumps(row,sort_keys=True,separators=(',',':')).encode();raw=b'\n'.join(lines)+b'\n'
        monkeypatch.setattr(m,'POST_REBOOT_DELTA_BYTES',len(raw))
        monkeypatch.setattr(m,'POST_REBOOT_DELTA_SHA',hashlib.sha256(raw).hexdigest())
    with pytest.raises((ValueError,KeyError)):
        m.audit_post_reboot_delta(raw,dates,oldref,nodes)


@pytest.fixture
def post_reboot_boundary():
    requests={};prior={}
    for role,count in m.POST_REBOOT_SOLVES.items():
        prefix='HYBRID' if role in m.RX else 'CLASSICAL'
        for i in range(count):
            token=f'{prefix}|{role}|synthetic-{i:03d}';kind='matching_sha256' if role in m.RX else 'result_sha256'
            requests[token]=dict(status='COMPLETE',charged=1,identity={'role':role,'day':i},**{kind:f'{i:064x}'})
            prior[token]={k:deepcopy(v) for k,v in requests[token].items() if k not in ('status','charged')}
    slots={};fits={}
    for i in range(144):
        node=f'node-{i}';slots[node]=dict(status='COMPLETE' if i<28 else 'UNRESERVED',entered=1 if i<28 else 0)
        if i<28:
            slots[node].update(identity={'cutoff':'2023-12-31'},artifact={'path':f'model{i}','sha256':'8'*64})
            fits[node]=dict(status='COMPLETE',entered=1,identity_sha256=m.digest(slots[node]['identity']),artifact=slots[node]['artifact'])
    calls=[];j=SimpleNamespace(sequence=7832,previous='e'*64,requests=requests,slots=slots,
        _source_guard_recovered=True,verify=lambda:calls.append('verify'))
    a={'journal':dict(sequence=7832,previous='e'*64,requests=prior,fits=fits)}
    return SimpleNamespace(journal=j,admission=a,calls=calls)


def test_post_reboot_boundary_preserves_complete_all28_and3868_without_transition(post_reboot_boundary):
    f=post_reboot_boundary;m.post_reboot_journal_boundary(f.journal,f.admission)
    assert f.calls==['verify']


@pytest.mark.parametrize('mutation',['sequence','previous','request_missing','started_solve','failed_solve',
    'charged_bool','cache_digest','cache_identity','fit_started','fit_entered_bool','fit_identity','fit_artifact',
    'extra_reserved','unreserved_entered','recovery_missing'])
def test_post_reboot_boundary_blocks_scientific_retry_or_changed_identity(post_reboot_boundary,mutation):
    f=post_reboot_boundary;j=f.journal;request=j.requests[next(iter(j.requests))]
    if mutation=='sequence':j.sequence-=1
    elif mutation=='previous':j.previous='0'*64
    elif mutation=='request_missing':j.requests.pop(next(iter(j.requests)))
    elif mutation=='started_solve':request['status']='ENTERED'
    elif mutation=='failed_solve':request['status']='FAILED'
    elif mutation=='charged_bool':request['charged']=True
    elif mutation=='cache_digest':request['result_sha256']='f'*64
    elif mutation=='cache_identity':request['identity']['role']='C15'
    elif mutation=='fit_started':j.slots['node-0']['status']='STARTED'
    elif mutation=='fit_entered_bool':j.slots['node-0']['entered']=True
    elif mutation=='fit_identity':j.slots['node-0']['identity']['cutoff']='2025-12-31'
    elif mutation=='fit_artifact':j.slots['node-0']['artifact']={'path':'other','sha256':'0'*64}
    elif mutation=='extra_reserved':j.slots['node-28']['status']='RESERVED'
    elif mutation=='unreserved_entered':j.slots['node-28']['entered']=1
    elif mutation=='recovery_missing':j._source_guard_recovered=False
    with pytest.raises(ValueError):m.post_reboot_journal_boundary(j,f.admission)
    assert not f.calls


@pytest.fixture
def post_reboot_gate_fixture(terminal_admission,monkeypatch):
    f=terminal_admission;m.admit_terminal_recovery(f.review_ref)
    monkeypatch.setattr(m,'POST_REBOOT_REVIEW_PATH',f.run/'C14_POST_REBOOT_CLASSICAL_CHECKPOINT_REVIEW_R1.json')
    checkpoint=post_reboot_contract()
    checkpoint['original_source_guard_review']=f.review_ref
    checkpoint['prior_runtime_source_review']=f.review['runtime_source_review']
    runtime=deepcopy(f.runtime);runtime['prior_runtime_source_review']=checkpoint['prior_runtime_source_review']
    runtime_ref=f.register(f.run/'RISK_INPUT_SOURCE_REVIEW_R5.json',runtime)
    checkpoint['runtime_source_review']=runtime_ref
    checkpoint_ref=f.register(m.POST_REBOOT_REVIEW_PATH,checkpoint)
    m._POST_REBOOT_AUTHORITY=checkpoint_ref
    Inputs=terminal_inputs(f);inputs=Inputs(source_review=deepcopy(runtime),source_review_ref=runtime_ref)
    return SimpleNamespace(f=f,checkpoint=checkpoint,checkpoint_ref=checkpoint_ref,runtime=runtime,
        runtime_ref=runtime_ref,inputs=inputs,owner=SimpleNamespace(input_owner=SimpleNamespace(RiskInputs=Inputs)))


def test_post_reboot_gate_restore_real_R5_reference_and_exact_prior_a497_without_numeric_replay(post_reboot_gate_fixture):
    p=post_reboot_gate_fixture
    m.restore_input_gates(p.inputs,p.f.gates,p.owner,prior_review_ref=p.f.review['original_source_review'])
    assert p.inputs._qualified and p.inputs._gates==p.f.gates
    assert p.inputs.verified==[{'full':True},{'full':True}] and not any(p.inputs.counts.values())
    assert p.runtime_ref in p.f.reads


@pytest.mark.parametrize('mutation',['formal_authority','R4_ref','runtime_body','runtime_prior','gate_body',
    'qualification_body','cache','counts','failed_cache','qualified'])
def test_post_reboot_gate_restore_rejects_alias_nonpristine_or_changed_qualification(post_reboot_gate_fixture,mutation):
    p=post_reboot_gate_fixture;gates=deepcopy(p.f.gates);inputs=p.inputs
    if mutation=='formal_authority':p.checkpoint['original_source_guard_review']={'path':'foreign','sha256':'0'*64}
    elif mutation=='R4_ref':inputs.review_ref=p.f.review['runtime_source_review']
    elif mutation=='runtime_body':inputs.review['extra']='changed'
    elif mutation=='runtime_prior':inputs.review['prior_source_review']={'path':'foreign'}
    elif mutation=='gate_body':gates[m.QUALIFIED[0]]['role']='C15'
    elif mutation=='qualification_body':p.f.bodies[p.f.review['qualification']['path']]['roles'][m.QUALIFIED[0]]['role']='C15'
    elif mutation=='cache':inputs._cache['risk']='present'
    elif mutation=='counts':inputs.counts['risk_numeric_read']=1
    elif mutation=='failed_cache':inputs._failed['risk']='failure'
    elif mutation=='qualified':inputs._qualified=True
    with pytest.raises((ValueError,KeyError)):
        m.restore_input_gates(inputs,gates,p.owner,prior_review_ref=p.f.review['original_source_review'])
    assert inputs._gates=={}


@pytest.fixture
def post_reboot_admission(terminal_admission,monkeypatch):
    f=terminal_admission;review=post_reboot_contract();old=f.review
    monkeypatch.setattr(m,'POST_REBOOT_REVIEW_PATH',f.run/'C14_POST_REBOOT_CLASSICAL_CHECKPOINT_REVIEW_R1.json')
    monkeypatch.setattr(m,'assert_checkpoint_entry_origin',lambda:f.calls.append('current_origin'))
    f.newroot.mkdir(parents=True)
    for path,(rel,oldsha) in m.post_reboot_source_paths().items():
        old['source_pins'][path]=oldsha
        review['source_pins'][path]=f.register(Path(path),sha='a'*64)['sha256']
        review['source_backups'][path]=f.register(f.run/'source_corrections/C14_POST_REBOOT_CLASSICAL_CHECKPOINT_R1'/rel,sha=oldsha)
    oldref=f.register(m.TERMINAL_REVIEW_PATH,old,sha=m.POST_REBOOT_OLD_REVIEW_SHA)
    review['original_source_guard_review']=oldref
    old['runtime_source_review']=f.register(f.run/'RISK_INPUT_SOURCE_REVIEW_R4.json',f.runtime,sha=m.POST_REBOOT_R4_SHA)
    for field,oldfield in (('prior_runtime_source_review','runtime_source_review'),
        ('execution_configuration','original_config'),('input_qualification','qualification'),
        ('snapshot_transport','snapshot_transport'),('B_freeze','B_freeze'),
        ('original_publication_admission','original_publication_admission')):
        review[field]=deepcopy(old[oldfield])
    runtime=deepcopy(f.runtime)
    journalpath=str(f.repo/'scripts/research/a2/training/selector_maximal_risk_journal.py')
    runtime['source_pins'][journalpath]=review['source_pins'][journalpath]
    runtime['prior_runtime_source_review']=review['prior_runtime_source_review']
    review['runtime_source_review']=f.register(f.run/'RISK_INPUT_SOURCE_REVIEW_R5.json',runtime)
    nodes=old['recover_rx_nodes'];fits={}
    for node in nodes:
        artifact=f.register(f.run/'risk_execution/models'/(m.digest(node)+'.joblib'),sha='b'*64)
        fits[node]=dict(status='COMPLETE',entered=1,identity_sha256='c'*64,artifact=artifact)
    observed=dict(f.journal,sequence=7832,previous='f'*64,counts=deepcopy(m.POST_REBOOT_SOLVES),
        fits=fits,recovery_event=dict(nodes=nodes,review_ref=oldref))
    monkeypatch.setattr(m,'audit_post_reboot_delta',
        lambda raw,dates,ref,ns:(m.need(raw==f.raw and ref==oldref and ns==nodes,'SYNTHETIC_EXACT_PREFIX_REQUIRED') or deepcopy(observed)))
    delta=f.register(f.run/'RISK_EXECUTION_DELTA.jsonl',sha=m.POST_REBOOT_DELTA_SHA)
    review['checkpoint_delta']=dict(delta,bytes=m.POST_REBOOT_DELTA_BYTES,lines=m.POST_REBOOT_DELTA_LINES)
    review['completed_fit_artifacts']={node:deepcopy(fit['artifact']) for node,fit in fits.items()}
    review['old_recovery_event']=dict(sequence=5597,**observed['recovery_event'])
    review['old_marker']=f.register(f.newroot/m.TERMINAL_MARKER,
        dict(review=oldref,original_RX_nodes=nodes,prior_delta=old['prior_delta']),sha=m.POST_REBOOT_OLD_MARKER_SHA)
    review['reboot_receipt']=f.register(m.MAINTENANCE/'POST_REBOOT_CHECKPOINT_OBSERVATION_R1.json',
        {'opaque':'fixed metadata receipt'},sha=m.POST_REBOOT_RECEIPT_SHA)
    review['independent_RX_completion']=f.register(m.MAINTENANCE/'TERMINAL_SOURCE_GUARD_RX_COMPLETE_OBSERVATION_R1.json',
        {'opaque':'fixed metadata independent receipt'},sha=m.POST_REBOOT_RX_RECEIPT_SHA)
    review['completed_role_artifacts']=dict(deepcopy(old['completed_artifacts']),
        **{role:{key:{'path':role+'/'+key,'sha256':'d'*64} for key in ('assembly','panel','native_pairs','matching')} for role in m.RX})
    monkeypatch.setattr(m,'post_reboot_completed_rx',lambda declared:[dict(complete_candidates=[r],
        failed_or_untestable={},panels={},native_pair_predictions={}) for r in m.RX])
    review_ref=f.register(m.POST_REBOOT_REVIEW_PATH,review)
    return SimpleNamespace(f=f,review=review,review_ref=review_ref,runtime=runtime,observed=observed)


def test_post_reboot_admission_seals_fixed_refs_all_artifacts_closed_prefix_and_no_business(post_reboot_admission):
    p=post_reboot_admission;value=m.admit_source_guard_checkpoint(p.review_ref)
    assert value['journal']==p.observed and value['runtime']==p.runtime
    assert value['original_authority']==p.f.review and value['gates']==p.f.gates
    assert m._POST_REBOOT_AUTHORITY==p.review_ref
    assert m._TERMINAL_AUTHORITY==p.review['original_source_guard_review']
    assert 'current_origin' in p.f.calls
    assert not (p.f.newroot/m.POST_REBOOT_MARKER).exists()
    assert p.review['old_marker'] in p.f.reads and p.review['independent_RX_completion'] in p.f.reads
    assert all(ref in p.f.pins for ref in p.review['completed_fit_artifacts'].values())


@pytest.mark.parametrize('mutation',['newmarker','terminal','old_audit','partial_classical_artifact','extra_source',
    'missing_source','backup_sha','old_formal_sha','R4_sha','R5_extra','R5_other_pin','snapshot',
    'configuration','qualification_ref','Bfreeze','publication','delta_lines','old_event',
    'old_marker_body','old_marker_sha','missing_fit','fit_reference','partial_roles','six_role_changed',
    'parallel_worker','executed_origin'])
def test_post_reboot_admission_refuses_changed_refs_parallel_partial_or_reentry(post_reboot_admission,monkeypatch,mutation):
    p=post_reboot_admission;r=p.review;f=p.f
    if mutation in ('newmarker','terminal','old_audit'):
        name={'newmarker':m.POST_REBOOT_MARKER,'terminal':'RISK_DECISIONS_TERMINAL_R1.json','old_audit':m.TERMINAL_AUDIT}[mutation]
        (f.newroot/name).write_text('EXISTING_IMMUTABLE_SYNTHETIC')
    elif mutation=='partial_classical_artifact':
        dest=f.newroot/'C14_D09';dest.mkdir();(dest/'partial.parquet').write_bytes(b'KEEP_PARTIAL')
    elif mutation=='extra_source':r['source_pins']['foreign.py']='e'*64
    elif mutation=='missing_source':r['source_pins'].pop(next(iter(r['source_pins'])))
    elif mutation=='backup_sha':r['source_backups'][next(iter(r['source_backups']))]['sha256']='0'*64
    elif mutation=='old_formal_sha':r['original_source_guard_review']['sha256']='0'*64
    elif mutation=='R4_sha':r['prior_runtime_source_review']['sha256']='0'*64
    elif mutation=='R5_extra':p.runtime['extra']='FORBIDDEN'
    elif mutation=='R5_other_pin':p.runtime['source_pins'][str(f.repo/'scripts/research/a2/data/untouched.py')]='0'*64
    elif mutation=='snapshot':r['snapshot_transport']={'changed':True}
    elif mutation=='configuration':r['execution_configuration']={'path':'foreign','sha256':'0'*64}
    elif mutation=='qualification_ref':r['input_qualification']={'path':'foreign','sha256':'0'*64}
    elif mutation=='Bfreeze':r['B_freeze']={'path':'foreign','sha256':'0'*64}
    elif mutation=='publication':r['original_publication_admission']={'path':'foreign','sha256':'0'*64}
    elif mutation=='delta_lines':r['checkpoint_delta']['lines']=7831
    elif mutation=='old_event':r['old_recovery_event']['nodes']=r['old_recovery_event']['nodes'][:-1]
    elif mutation=='old_marker_body':f.bodies[r['old_marker']['path']]['review']={'path':'other'}
    elif mutation=='old_marker_sha':r['old_marker']['sha256']='0'*64
    elif mutation=='missing_fit':r['completed_fit_artifacts'].pop(next(iter(r['completed_fit_artifacts'])))
    elif mutation=='fit_reference':r['completed_fit_artifacts'][next(iter(r['completed_fit_artifacts']))]['path']='foreignmodel'
    elif mutation=='partial_roles':r['completed_role_artifacts'].pop(m.RX[0])
    elif mutation=='six_role_changed':r['completed_role_artifacts']['C14_D01']={'changed':True}
    elif mutation=='parallel_worker':monkeypatch.setattr(m,'no_other_worker',lambda:(_ for _ in ()).throw(ValueError('PARALLEL')))
    elif mutation=='executed_origin':monkeypatch.setattr(m,'assert_checkpoint_entry_origin',lambda:(_ for _ in ()).throw(ValueError('ORIGIN')))
    with pytest.raises((ValueError,KeyError)):m.admit_source_guard_checkpoint(p.review_ref)
    assert not (f.newroot/m.POST_REBOOT_MARKER).exists() or mutation=='newmarker'


@pytest.fixture
def post_reboot_runtime(terminal_runtime,monkeypatch):
    p=terminal_runtime;f=p.f;f.newroot.mkdir(parents=True)
    oldmarker=f.newroot/m.TERMINAL_MARKER;oldmarker.write_bytes(b'ORIGINAL_RECOVERY_MARKER_IMMUTABLE')
    authority=post_reboot_contract();ref={'path':'SYNTHETIC_POST_REVIEW','sha256':'e'*64}
    authority.update(runtime_source_review={'path':'SYNTHETIC_R5','sha256':'f'*64},
        input_qualification=f.review['qualification'],snapshot_transport=f.review['snapshot_transport'],
        checkpoint_delta={'path':'SYNTHETIC_DELTA','sha256':'8'*64,'bytes':15563481,'lines':7832},
        old_marker={'path':str(oldmarker),'sha256':hashlib.sha256(oldmarker.read_bytes()).hexdigest()},
        old_recovery_event={'sequence':5597},completed_fit_artifacts={'opaque':'28 complete'},
        completed_role_artifacts={'opaque':'eight complete'},original_source_guard_review=f.review_ref,
        source_pins={str(Path(m.__file__).resolve()):'9'*64})
    rx=[]
    for role in m.RX:
        rx.append(dict(complete_candidates=[role],failed_or_untestable={},
            panels={role:dict(path=str(f.newroot/role/'scores_pre2026.parquet'),sha256='1'*64,calendar_dates=752)},
            native_pair_predictions={role:dict(path=str(f.newroot/role/'native_pairs_pre2026.parquet'),sha256='2'*64,
                matching_path=str(f.newroot/role/'matching_pre2026.parquet'),matching_sha256='3'*64)}))
    admission=dict(p.admission,review=authority,review_ref=ref,rx_completed=rx,original_authority=deepcopy(f.review))
    monkeypatch.setattr(m,'admit_source_guard_checkpoint',lambda r:admission)
    monkeypatch.setattr(m,'post_reboot_journal_boundary',lambda *args:p.events.append(('post_boundary',)))
    monkeypatch.setattr(m,'publication_metadata_preflight',lambda *args:({'publication':object()},{'source_only':'fixed'}))
    class Journal:
        def __init__(self,run,**kwargs):
            assert kwargs=={'post_reboot_checkpoint_ref':ref};p.events.append(('post_journal_construct',))
        def verify(self):p.events.append(('post_journal_verify',))
        def recover_source_guard_zero_entry(self,*args):pytest.fail('Recovery repeated')
        def reserve(self,*args):pytest.fail('Reservation repeated')
        def stored_fit(self,*args):pytest.fail('Scientific fit repeated')
    p.execution.journal_owner.RiskJournal=Journal
    Base=terminal_inputs(f)
    class Inputs(Base):
        def __init__(self,*args,**kwargs):
            assert kwargs['source_review_ref']==authority['runtime_source_review']
            super().__init__(source_review=f.runtime,source_review_ref=authority['runtime_source_review'])
            p.constructed.append(self);p.events.append(('post_inputs',))
    p.execution.input_owner.RiskInputs=Inputs
    def restore(inputs,gates,*args,**kwargs):
        assert kwargs=={'prior_review_ref':f.review['original_source_review']}
        inputs._qualified=True;inputs._gates=deepcopy(gates);p.events.append(('post_metadata_restore',))
    monkeypatch.setattr(m,'restore_input_gates',restore)
    def project(*args,**kwargs):
        assert (f.newroot/m.POST_REBOOT_MARKER).exists()
        assert kwargs==dict(start='2023-01-01',stop='2026-01-01',run=f.run)
        p.events.append(('post_raw_meta',));return {'synthetic_raw_meta':True}
    p.execution.ctl.project=project
    p.execution.ctl.runtime_for=lambda *args:pytest.fail('RX runtime prepared')
    p.execution.ctl.runtime_parts=lambda *args:pytest.fail('RX runtime parts prepared')
    p.execution.ctl.feature_order=lambda *args:pytest.fail('RX feature order entered')
    p.execution.hybrids.execute_hybrid=lambda *args,**kwargs:pytest.fail('RX owner entered')
    original_table=p.execution.pq.read_table
    def table(path):
        assert Path(path).name in ('raw_current.parquet','pair_geometry.parquet')
        return original_table(path)
    p.execution.pq.read_table=table
    p.execution.pq.ParquetFile=lambda path:SimpleNamespace(metadata=SimpleNamespace(
        num_rows=100400 if Path(path).name=='native_pairs_pre2026.parquet' else
            1234 if Path(path).name=='scores_pre2026.parquet' else 752))
    def membership(*args,**kwargs):
        assert args[-1]==authority['runtime_source_review']
        assert kwargs==dict(role_gates=p.constructed[0]._gates,qualification_ref=authority['input_qualification'],artifact_root=f.newroot)
        p.events.append(('post_original_membership_only',));p.constructed[0].counts['risk_numeric_read']=7
        return dict(complete_candidates=list(m.TERMINAL_CLASSICAL),failed_or_untestable={},panels={},native_pair_predictions={})
    def bind(function,**kwargs):
        assert kwargs['dependencies']=={'ROLES':m.TERMINAL_CLASSICAL}
        p.events.append(('post_bind_fixed_classical',));return membership
    p.execution.membership.event.bind_pinned_kernel=bind
    def terminal(*args,**kwargs):
        assert args[5]==[admission['completed'],*rx,args[5][-1]]
        assert args[-1]==authority['runtime_source_review']
        assert kwargs==dict(artifact_root=f.newroot,input_qualification_ref=authority['input_qualification'])
        p.events.append(('post_original_terminal',))
        return dict(status='RISK_DECISIONS_TERMINAL_JOINT_DELIVERY_PENDING',
            complete_conditional_roles=[*m.TERMINAL_COMPLETE,*m.RX,*m.TERMINAL_CLASSICAL],charged_solves=5516,backend_entered=28)
    p.execution.terminal=terminal
    return SimpleNamespace(p=p,authority=authority,ref=ref,admission=admission,oldmarker=oldmarker)


def test_post_reboot_cold_validation_returns_before_newmarker_raw_native_labels_fit_solve(post_reboot_runtime,monkeypatch):
    f=post_reboot_runtime;p=f.p;original=f.oldmarker.read_bytes()
    p.execution.ctl.project=lambda *args,**kwargs:pytest.fail('Raw projection before cold admission')
    p.execution.pq.read_table=lambda *args,**kwargs:pytest.fail('Numeric input before cold admission')
    p.execution.input_owner.RiskInputs=lambda *args,**kwargs:pytest.fail('Native owner before cold admission')
    p.execution.resolve=lambda *args,**kwargs:pytest.fail('Output allocation before cold admission')
    result=m.resume_source_guard_checkpoint(f.ref,validate_only=True)
    assert result['status']=='PASS_POST_REBOOT_CLASSICAL_CHECKPOINT_ADMISSION'
    assert result['interrupted_worker_execution_input_counts']=='UNKNOWN_DUE_REBOOT'
    assert result['unentered_named_classical_solves']==1648
    assert result['historical_qualification_native_reads']==330 and result['prior_checkpoint_execution_native_reads']==243
    assert all(result[k]==0 for k in ('preflight_new_native_numeric_reads','new_fit','new_solve','new_risk_estimation'))
    assert not (p.f.newroot/m.POST_REBOOT_MARKER).exists() and not p.constructed
    assert f.oldmarker.read_bytes()==original


def test_post_reboot_runtime_reuses_RX_refs_only_calls_original_three_classical_and_separates_reads(post_reboot_runtime):
    f=post_reboot_runtime;p=f.p;original=f.oldmarker.read_bytes()
    result=m.resume_source_guard_checkpoint(f.ref)
    names=[e[0] for e in p.events]
    assert names.count('post_original_membership_only')==names.count('post_original_terminal')==1
    assert 'original_hybrid_owner' not in names and 'recover_original28' not in names
    assert names.index('post_metadata_restore')<names.index('post_bind_fixed_classical')
    assert [Path(e[1]).name for e in p.events if e[0]=='synthetic_prepared_read']==['raw_current.parquet','pair_geometry.parquet']
    audit=[e[2] for e in p.events if e[0]=='put' and Path(e[1]).name==m.POST_REBOOT_AUDIT][0]
    assert audit['interrupted_worker_execution_input_counts']=='UNKNOWN_DUE_REBOOT'
    assert audit['resumed_worker_execution_input_counts']['risk_numeric_read']==7
    assert audit['historical_qualification_counts']['native_states_loaded']==330
    assert audit['prior_checkpoint_execution_input_counts']['native_states_loaded']==243
    assert audit['RX_reopened'] is False and audit['new_fit']==0
    assert f.oldmarker.read_bytes()==original and result['joint_delivery_completed'] is False
    with pytest.raises(ValueError,match='ONE_SHOT'):m.resume_source_guard_checkpoint(f.ref)


@pytest.mark.parametrize('mutation',['file','spec_origin','spec_name','loader','function_code'])
def test_post_reboot_requires_executed_current_canonical_source_and_function_origin(monkeypatch,mutation):
    module=sys.modules[m.__name__];canonical=Path(m.__file__).resolve()
    fake=SimpleNamespace(__file__=str(canonical),__spec__=SimpleNamespace(name=m.__name__,origin=str(canonical)),
        __loader__=SimpleNamespace(path=str(canonical)))
    monkeypatch.setattr(m.sys,'modules',dict(m.sys.modules,**{m.__name__:fake}))
    monkeypatch.setattr(m,'function_origin',lambda *args:m.need(mutation!='function_code','CODE_ORIGIN'))
    if mutation=='file':fake.__file__='backup/resume.py'
    elif mutation=='spec_origin':fake.__spec__.origin='backup/resume.py'
    elif mutation=='spec_name':fake.__spec__.name='clone'
    elif mutation=='loader':fake.__loader__.path='backup/resume.py'
    with pytest.raises(ValueError):m.assert_checkpoint_entry_origin()


@pytest.fixture
def post_reboot_rx_artifacts(monkeypatch,tmp_path):
    newroot=tmp_path/'run/risk_execution/source_guard_recovery_r1'
    monkeypatch.setattr(m,'TERMINAL_ROOT',newroot)
    monkeypatch.setattr(m,'safe_path',lambda p:Path(p).resolve())
    bodies={};declared={}
    for role,(head,family) in zip(m.RX,(('HGB','LW'),('XGB','QQQ_RESIDUAL'))):
        parent=newroot/role;parent.mkdir(parents=True)
        refs={}
        for key,name in dict(assembly='HYBRID_ASSEMBLY.json',panel='scores_pre2026.parquet',
            native_pairs='native_pairs_pre2026.parquet',matching='matching_pre2026.parquet').items():
            path=parent/name
            if key!='assembly':path.write_bytes(b'OPAQUE_SYNTHETIC_FILE_NO_VALUES')
            refs[key]=dict(path=str(path),sha256='a'*64)
        bodies[role]=dict(status='HYBRID_COMPLETE',research_id=m.ID,role=role,head=head,family=family,
            feature_count=228,complete_candidates=[role],failed_or_untestable={},fit_failures={},
            forecast2026_rows=0,scientific_retry=0,strict_PIT_promotion_eligible=False,
            panels={role:dict(refs['panel'],rows=1234,common_rows=1234,calendar_dates=752,raw_fallback_2023_exact=True)},
            native_pair_predictions={role:dict(refs['native_pairs'],rows=100400,kind='U0_POINT_GT0',
                matching_path=refs['matching']['path'],matching_sha256=refs['matching']['sha256'])},
            capacity_selection={'FORBIDDEN_VALUE':'NEVER_DECODE_CAPACITY_SELECTION'},
            oof_lineage={'FORBIDDEN_VALUE':'NEVER_DECODE_OOF_LINEAGE'})
        declared[role]=refs
    def rewrite():
        for role in m.RX:
            Path(declared[role]['assembly']['path']).write_text(json.dumps(bodies[role],indent=2),encoding='utf-8')
    rewrite()
    def pin(ref,*,path=None,**kwargs):
        m.need(isinstance(ref,dict) and set(ref)=={'path','sha256'},'EXACT_REF_REQUIRED')
        if path is not None:m.need(ref['path']==str(path),'EXACT_FIXED_RX_PATH_REQUIRED')
        m.need(Path(ref['path']).is_file(),'EXACT_PHYSICAL_RX_FILE_REQUIRED')
        return Path(ref['path'])
    monkeypatch.setattr(m,'pin',pin)
    return SimpleNamespace(bodies=bodies,declared=declared,rewrite=rewrite)


def test_post_reboot_reuses_both_rx_four_physical_refs_without_decoding_selection_or_lineage(post_reboot_rx_artifacts,monkeypatch):
    p=post_reboot_rx_artifacts;original=json.loads
    def metadata_only(value,*args,**kwargs):
        if isinstance(value,(bytes,bytearray)):
            assert b'NEVER_DECODE_CAPACITY_SELECTION' not in value
            assert b'NEVER_DECODE_OOF_LINEAGE' not in value
        return original(value,*args,**kwargs)
    monkeypatch.setattr(m.json,'loads',metadata_only)
    results=m.post_reboot_completed_rx(p.declared)
    assert [r['complete_candidates'] for r in results]==[[role] for role in m.RX]
    assert all(set(r)=={'complete_candidates','failed_or_untestable','panels','native_pair_predictions'} for r in results)


@pytest.mark.parametrize('mutation',['missing_role','missing_ref','extra_ref','foreign_path','missing_file',
    'partial_status','wrong_head','wrong_family','feature_count','partial_panel','nonzero_forecast','science_retry',
    'PIT_promotion','fit_failure','panel_ref','native_ref','matching_ref','native_rows'])
def test_post_reboot_rx_reuse_refuses_incomplete_or_changed_original_artifacts(post_reboot_rx_artifacts,mutation):
    p=post_reboot_rx_artifacts;role=m.RX[0];body=p.bodies[role];declared=p.declared
    if mutation=='missing_role':declared.pop(role)
    elif mutation=='missing_ref':declared[role].pop('matching')
    elif mutation=='extra_ref':declared[role]['models']={'path':'extra','sha256':'a'*64}
    elif mutation=='foreign_path':declared[role]['assembly']['path']='other/HYBRID_ASSEMBLY.json'
    elif mutation=='missing_file':Path(declared[role]['matching']['path']).unlink()
    elif mutation=='partial_status':body['status']='HYBRID_FAILED'
    elif mutation=='wrong_head':body['head']='XGB'
    elif mutation=='wrong_family':body['family']='SCALAR_ONLY'
    elif mutation=='feature_count':body['feature_count']=216
    elif mutation=='partial_panel':body['panels'][role]['calendar_dates']=502
    elif mutation=='nonzero_forecast':body['forecast2026_rows']=1
    elif mutation=='science_retry':body['scientific_retry']=1
    elif mutation=='PIT_promotion':body['strict_PIT_promotion_eligible']=True
    elif mutation=='fit_failure':body['fit_failures']={'failed_node':{'status':'FAILED'}}
    elif mutation=='panel_ref':body['panels'][role]['sha256']='0'*64
    elif mutation=='native_ref':body['native_pair_predictions'][role]['sha256']='0'*64
    elif mutation=='matching_ref':body['native_pair_predictions'][role]['matching_sha256']='0'*64
    elif mutation=='native_rows':body['native_pair_predictions'][role]['rows']=100399
    if mutation not in ('missing_role','missing_ref','extra_ref','foreign_path','missing_file'):p.rewrite()
    with pytest.raises((ValueError,KeyError)):m.post_reboot_completed_rx(declared)
