"""Fabricated metadata and stub engines only: zero real replay, readers or fits."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.evaluation import joint_event_account_dispatch_r5 as dispatch
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays

_spec = importlib.util.spec_from_file_location('_dispatch_event_fixture',
    Path(__file__).resolve().parents[1] / 'inference' / 'test_joint_event_policy_r5.py')
_fixture = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_fixture)


def make(cost=10, risk='RD'):
    obj, data, ctx, _ = _fixture.make(cost=cost, risk=risk)
    # A deliberately fabricated 752-session calendar, never an exchange claim.
    days = pd.bdate_range('2023-01-03', '2025-12-31')
    days = days[:751].append(days[-1:])
    closes = tuple(str(d.tz_localize('America/New_York') + pd.Timedelta(hours=16)) for d in days)
    legal = ('2022-12-30T16:00:00-05:00',) + closes
    activation = replace(obj.activation, legal_calendar_sha256=dispatch.policy.ad.legal_calendar_sha256(legal))
    n = len(ctx.tickers); prices = np.full((752, n), 100.)
    market = MarketArrays(days, np.asarray(ctx.tickers), prices.copy(), prices.copy(),
        adv=np.full(prices.shape, 1e8), signal_asof=list(map(pd.Timestamp, closes)))
    scores = np.full(prices.shape, .01); events = {}; quality = np.zeros(prices.shape, bool)
    parent = dispatch.owner.FrozenHistoryAccountFreeze('SYNTHETIC_PARENT_ACCOUNT', 'SYNTHETIC_OLDER_PARENT',
        'SYNTHETIC_PARENT_RUN', '8'*64, dispatch.owner.input_digests(market, scores, events, quality),
        dispatch.owner.source_pins(), 'Synthetic raw-share custody with unknown historical availability', synthetic=True)
    contract = obj.contract
    hashes = {'whole_freeze':'0'*64, 'plan':contract.source_contract_sha256,
        'bank':activation.bank_manifest_sha256, 'registration':'1'*64, 'source_authority':'2'*64,
        'parent_account_freeze':'3'*64, 'parent_policy_binding':contract.parent_policy_binding_sha256,
        'qualification':'4'*64, 'family_freeze':contract.family_freeze_sha256,
        'prediction_clarification':contract.prediction_clarification_sha256,
        'alpha_reuse':contract.alpha_reuse_receipt_sha256, 'registration_patch':'a'*64}
    refs = {name:dispatch.PhysicalRef('D:/synthetic-metadata/' + name + '.json', value) for name,value in hashes.items()}
    row, prior = contract.rows[0], contract.parent_rows[0]
    b = activation.method_bindings[0]
    p = dispatch.EventPathQualification(row.id, dispatch.content_hash(row), dispatch.content_hash(prior),
        row.risk, b.family, dict.fromkeys(dispatch.PROOF_GATES, True), '5'*64, '6'*64, '7'*64)
    proof = dispatch.EventAccountQualification(contract.research_id, contract.run_id, contract.digest(),
        activation.digest(), parent.digest(), hashes['whole_freeze'], hashes['plan'], hashes['bank'],
        hashes['source_authority'], parent.input_sha256, dispatch.content_hash(tuple(str(d.date()) for d in days)),
        legal, dispatch.content_hash(contract.forecast_lineage), (p,))
    freeze = dispatch.EventAccountDispatchFreeze(contract.research_id, contract.run_id, contract.digest(),
        activation.digest(), proof.digest(), parent.digest(), (row.id,), cost, refs, dispatch.source_pins())
    return dict(market=market, raw_scores=scores, event_inputs=events, uncertified_quality_only=quality,
        parent_freeze=parent, contract=contract, activation=activation, input_provider=obj.provider,
        qualification=proof, freeze=freeze, expected_dispatch_sha256=freeze.digest(), synthetic=True)


def invoke(values):
    return dispatch.run_event_family_account(**values)


def refresh(values, **changes):
    values = dict(values, **changes)
    freeze = replace(values['freeze'], contract_sha256=values['contract'].digest(),
        activation_sha256=values['activation'].digest(), qualification_sha256=values['qualification'].digest(),
        parent_account_freeze_sha256=values['parent_freeze'].digest())
    return dict(values, freeze=freeze, expected_dispatch_sha256=freeze.digest())


@pytest.fixture
def engine(monkeypatch):
    calls = []
    def stub(market, paths, obj, account, **kwargs):
        assert obj.token.mode == 'ACCOUNT_REPLAY'
        calls.append(dict(market=market, paths=paths, policy=obj, account=account, kwargs=kwargs))
        return SimpleNamespace(metadata={'annual_reset':False})
    def qualify(replay, market, quality, freeze, gaps):
        calls[-1]['qualification_owner'] = freeze
        assert not gaps
        return {p:dict(mechanism_accounting_consistent=False, quote_qualified=False,
            certified_NAV=False, strict_PIT_promotion_eligible=False) for p in freeze.path_ids}
    monkeypatch.setattr(dispatch.owner.common, 'run_continuous_account', stub)
    monkeypatch.setattr(dispatch.owner, '_qualify', qualify)
    return calls


@pytest.mark.parametrize('cost', [5,10,20])
def test_exact_cost_and_path_transport_reuses_owner_without_reset_or_new_qualification(cost, engine):
    values = make(cost); before = dispatch.owner.input_digests(values['market'], values['raw_scores'],
        values['event_inputs'], values['uncertified_quality_only'])
    result = invoke(values)
    assert len(engine) == 1 and result.physical_fit_count == 0
    assert engine[0]['paths'] == values['freeze'].path_ids
    assert engine[0]['account'] == dispatch.owner.ACCOUNT
    assert engine[0]['kwargs']['execution_friction']['one_way_bps'] == cost
    assert engine[0]['kwargs']['execution_friction']['benchmark'] == 'NEXT_RAW_OPEN'
    af = engine[0]['qualification_owner']
    assert isinstance(af, dispatch.SensitivityFreeze) and af.input_sha256 == values['parent_freeze'].input_sha256
    assert af.initial_cash_usd == 3000 and af.fee_bps == af.cash_interest == 0
    assert not af.quote_qualified and not af.certified_NAV and not af.strict_PIT_promotion_eligible
    assert not result.replay.metadata['annual_reset']
    assert not next(iter(result.qualification_by_path.values()))['mechanism_accounting_consistent']
    assert before == dispatch.owner.input_digests(values['market'], values['raw_scores'],
        values['event_inputs'], values['uncertified_quality_only'])


@pytest.mark.parametrize('gate', dispatch.PROOF_GATES)
@pytest.mark.parametrize('value', [False, None, 1])
def test_every_gate_requires_exact_true_before_any_engine_call(gate, value, engine):
    values = make(); proof = values['qualification']; p = proof.paths[0]
    proof = replace(proof, paths=(replace(p, gates={**p.gates,gate:value}),))
    with pytest.raises(dispatch.EventAccountDispatchBlocked): invoke(refresh(values, qualification=proof))
    assert engine == []


@pytest.mark.parametrize('ref', sorted(dispatch.REF_NAMES))
def test_missing_physical_dependency_cannot_issue_replay_token(ref, engine):
    values = make(); refs = dict(values['freeze'].refs); refs.pop(ref)
    freeze = replace(values['freeze'], refs=refs)
    with pytest.raises(dispatch.EventAccountDispatchBlocked):
        invoke(dict(values, freeze=freeze, expected_dispatch_sha256=freeze.digest()))
    assert engine == []


@pytest.mark.parametrize('change', ['path','cost','parent_tuple','row_proof','calendar','legal_calendar',
    'source_code','held_domain','session_count','source_flags','payload','parent_freeze'])
def test_frozen_parent_path_cost_context_and_support_changes_stop_dispatch(change, engine):
    values = make(); freeze = values['freeze']; proof = values['qualification']
    if change == 'path': freeze = replace(freeze,path_ids=('UNREGISTERED_PATH',))
    if change == 'cost': freeze = replace(freeze,cost_bps=20)
    if change == 'parent_tuple':
        contract = values['contract']; prior = replace(contract.parent_rows[0],gross='G2')
        contract = replace(contract,parent_rows=(prior,),parent_rows_sha256=dispatch.content_hash((prior,)))
        values = refresh(values,contract=contract,qualification=replace(proof,contract_sha256=contract.digest(),
            paths=(replace(proof.paths[0],parent_row_sha256=dispatch.content_hash(prior)),)))
        freeze = values['freeze']; proof = values['qualification']
    if change == 'row_proof': proof = replace(proof,paths=(replace(proof.paths[0],row_sha256='a'*64),))
    if change == 'calendar': proof = replace(proof,decision_calendar_sha256='a'*64)
    if change == 'legal_calendar': proof = replace(proof,legal_sessions=proof.legal_sessions[1:])
    if change == 'source_code': freeze = replace(freeze,source_sha256={})
    if change == 'held_domain': proof = replace(proof,paths=(replace(proof.paths[0],gates={}),))
    if change == 'session_count': proof = replace(proof,session_count=751)
    if change == 'source_flags': proof = replace(proof,quote_qualified=True)
    if change == 'payload': values['raw_scores'][0,0] = .9
    if change == 'parent_freeze': values['parent_freeze'] = replace(values['parent_freeze'], initial_cash_usd=4000)
    if proof is not values['qualification']:
        values = refresh(values,qualification=proof); freeze = values['freeze']
    with pytest.raises((ValueError,KeyError)): invoke(dict(values,freeze=freeze,expected_dispatch_sha256=freeze.digest()))
    assert engine == []


@pytest.mark.parametrize('risk', ['RH','RT','RR','RU','RE','RM','SHR_EB','SHR_FACTOR'])
def test_anchor_only_or_unbound_families_never_become_full_chain_candidates(risk, engine):
    with pytest.raises(dispatch.EventAccountDispatchBlocked): invoke(make(risk=risk))
    assert engine == []


def test_original_control_cannot_be_replayed_through_family_dispatch(engine):
    values = make(); contract = values['contract']; prior = replace(contract.parent_rows[0],
        risk='NONE',prediction='RAW_RANK',optimizer='SIMPLE_EQUAL')
    row = replace(prior)
    contract = replace(contract,rows=(row,),parent_rows=(prior,),parent_rows_sha256=dispatch.content_hash((prior,)))
    p = replace(values['qualification'].paths[0],row_sha256=dispatch.content_hash(row),
        parent_row_sha256=dispatch.content_hash(prior),risk_method='NONE')
    proof = replace(values['qualification'],contract_sha256=contract.digest(),paths=(p,))
    with pytest.raises(dispatch.EventAccountDispatchBlocked,match='CONTROL_EXACT_REUSE_ONLY'):
        invoke(refresh(values,contract=contract,qualification=proof))
    assert engine == []


def test_explicit_cvar_missing_producer_is_not_hp(engine):
    values = make(); b = replace(values['activation'].method_bindings[0], parent_risk='TAIL_CVAR',family='TAIL_CVAR',
        method='R5::TAIL_CVAR::EXPLICIT_SCENARIO_SOURCE_REQUIRED',availability='BLOCKED_MISSING_PRODUCER')
    activation = replace(values['activation'],method_bindings=(b,),allowed_risk_methods=(b.method,))
    contract = values['contract']; prior = replace(contract.parent_rows[0],risk='TAIL_CVAR'); row = replace(prior,risk=b.method)
    contract = replace(contract,rows=(row,),parent_rows=(prior,),parent_rows_sha256=dispatch.content_hash((prior,)))
    p = replace(values['qualification'].paths[0],row_sha256=dispatch.content_hash(row),
        parent_row_sha256=dispatch.content_hash(prior),risk_method=b.method,family=b.family)
    proof = replace(values['qualification'],activation_sha256=activation.digest(),contract_sha256=contract.digest(),paths=(p,))
    with pytest.raises(dispatch.EventAccountDispatchBlocked):
        invoke(refresh(values,contract=contract,activation=activation,qualification=proof))
    assert engine == []


def test_real_runtime_guard_failure_precedes_all_input_body_and_provider_access(engine, monkeypatch):
    values = make(); score_copy = values['raw_scores'].copy(); calls = []
    def denied(run, **kwargs):
        calls.append((run,kwargs)); raise ValueError('REGISTERED_R5_EXACT_FREEZE_SOURCE_AND_METADATA_SCOPE_REQUIRED')
    def forbidden(*args, **kwargs): raise AssertionError('input body read before accepted activation')
    monkeypatch.setattr(dispatch.runtime,'guard',denied)
    monkeypatch.setattr(dispatch.owner,'input_digests',forbidden)
    values.update(synthetic=False,run='D:/synthetic-run',input_provider=forbidden)
    with pytest.raises(ValueError,match='REGISTERED_R5'): invoke(values)
    assert calls == [('D:/synthetic-run',dict(numeric=True,expected_freeze_sha256=values['freeze'].refs['whole_freeze'].sha256))]
    np.testing.assert_array_equal(values['raw_scores'],score_copy)
    assert engine == []


def test_real_parent_cannot_be_mislabeled_synthetic(engine):
    values = make(); parent = replace(values['parent_freeze'],synthetic=False)
    values = refresh(values,parent_freeze=parent)
    with pytest.raises(dispatch.EventAccountDispatchBlocked,match='CANNOT_BE_DECLARED_SYNTHETIC'): invoke(values)
    assert engine == []


def test_source_closure_is_physical_and_excludes_registry_mutable_admission_code():
    pins = dispatch.code_pins()
    assert {p['path']:p['sha256'] for p in pins} == dispatch.source_pins()
    assert str(Path(dispatch.runtime.__file__).resolve()) in dispatch.source_pins()
    assert str(Path(dispatch.runtime.parent.__file__).resolve()) in dispatch.source_pins()
    assert all('research_registry.py' not in p['path'] for p in pins)


@pytest.mark.parametrize('change', ['wrong_run','wrong_owner','wrong_parent','wrong_freeze','wrong_source',
    'patch_sha','not_applied','head','multiple_entities','authority',None])
def test_wrong_owner_or_science_registration_receipt_cannot_authorize_account(change, engine):
    values = make(); freeze = values['freeze']; run = Path('D:/synthetic-r5-run')
    refs = dict(freeze.refs)
    refs['registration'] = dispatch.PhysicalRef(str(run / 'REGISTRATION_RECEIPT.json'), '1'*64)
    refs['registration_patch'] = dispatch.PhysicalRef(str(run / 'work/REGISTRY_ADMISSION_PATCH.json'), 'a'*64)
    freeze = replace(freeze, refs=refs)
    head = 'b'*64
    receipt = dict(status='PASS', head_sha256=head,
        manifest=dict(snapshot_sha256=head, patch_sha256='a'*64),
        event=dict(event_type='APPLY_PATCH',new_head_sha256=head,patch_sha256='a'*64))
    metadata = dict(event_science_freeze_sha256=refs['whole_freeze'].sha256,
        event_source_authority_sha256=refs['source_authority'].sha256,fit_authority=False,
        formal_freeze_authority=False,strict_PIT_promotion_eligible=False)
    entity = dict(entity_id=dispatch.runtime.ID,canonical_name=dispatch.runtime.ID,status='OPEN',
        parent_entity_id='V24_B_JOINT_MAXIMAL_BREADTH_PRE2026_R4',metadata=metadata)
    patch = dict(operations=[dict(op='add_entity',entity=entity,parent_entity_id=entity['parent_entity_id'])])
    if change=='wrong_run': refs['registration']=replace(refs['registration'],path='D:/another-run/REGISTRATION_RECEIPT.json')
    if change=='wrong_owner': entity['entity_id']='ANOTHER_RESEARCH'
    if change=='wrong_parent': entity['parent_entity_id']='ANOTHER_PARENT'
    if change=='wrong_freeze': metadata['event_science_freeze_sha256']='c'*64
    if change=='wrong_source': metadata['event_source_authority_sha256']='c'*64
    if change=='patch_sha': receipt['event']['patch_sha256']='c'*64
    if change=='not_applied': receipt['status']='BLOCKED'
    if change=='head': receipt['manifest']['snapshot_sha256']='c'*64
    if change=='multiple_entities': patch['operations'].append(patch['operations'][0])
    if change=='authority': metadata['fit_authority']=True
    if change is None:
        dispatch._registration_guard(run,freeze,receipt,patch)
    else:
        with pytest.raises(dispatch.EventAccountDispatchBlocked): dispatch._registration_guard(run,freeze,receipt,patch)
    assert engine==[]


def test_account_replay_token_is_issued_only_after_parent_input_guard(engine, monkeypatch):
    values=make(); modes=[]; original=dispatch.policy.EventFamilyPolicy
    def spy(*args,**kwargs):
        modes.append(kwargs['token'].mode); return original(*args,**kwargs)
    monkeypatch.setattr(dispatch.policy,'EventFamilyPolicy',spy)
    values['raw_scores'][0,0]=.9
    with pytest.raises(dispatch.owner.FrozenHistoryAccountBlocked): invoke(values)
    assert modes==['SUPPORT_DISCOVERY'] and engine==[]
