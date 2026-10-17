"""Synthetic-only cash63 identity/routes; no real models, quotes or outcomes."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import pytest
from scripts.research.a2.evaluation import consensus_original_cash63_profile as r
from scripts.research.a2.evaluation import frozen_test_authority as f, frozen_a94_profile as p


def pin(name):
    return dict(path=str(Path("D:/synthetic_cash63") / name), sha256=hashlib.sha256(name.encode()).hexdigest())


def fixture_metadata():
    heads = {h: dict(model_ref=pin(h.replace(':', '_') + '.model'), receipt_ref=pin(h.replace(':', '_') + '.receipt'), new_pool_sigma=.07)
             for h in r.HEADS}
    inventory, rows = [], []
    names = sorted(r.HEADS)
    for i in range(63):
        head = names[i % 12]
        oid = f"OLD_{i:02d}"
        oldsha, newsha = hashlib.sha256(oid.encode()).hexdigest(), hashlib.sha256((r.PREFIX + oid).encode()).hexdigest()
        spec = dict(candidate_id=oid, scientific_tuple_sha256=oldsha, action='stateful', action_cost_mode='blind',
                    value_model=head, risk='diag20_reference', gross='fixed', control='none', forecast='none',
                    execution_friction=dict(kind='FIXED_ADVERSE_OPEN_SLIPPAGE', one_way_bps=10, fee_bps=0,
                                            scenario_id='SYNTHETIC_10BPS', benchmark='NEXT_RAW_OPEN'))
        inventory.append(dict(candidate_id=oid, scientific_tuple_sha256=oldsha, specification=spec,
                              runtime_owner='STATEFUL_OVERLAY', source_group='A_ORIGINAL_ACCOUNT',
                              required_action_roles=[], dependency_closure=dict(status='COMPLETE', state_ids=[]),lookback=None))
        rows.append(dict(candidate_id=r.PREFIX + oid, original_candidate_id=oid, learned_head=head,
                         original_rule_specification=deepcopy(spec), original_scientific_tuple_sha256=oldsha,
                         scientific_tuple_sha256=newsha, original_rules_modified=False,
                         new_model_ref=heads[head]['model_ref'], new_head_receipt_ref=heads[head]['receipt_ref']))
    return dict(schema='CASH12_HEADS_AND_63_RECONSTRUCTION_R1', research_id=r.TASK, heads=heads,
                configurations=rows, original_inventory_ref=pin('inventory.json'),
                policy_authority_ref=dict(path=pin('policy.py')['path'], sha256='e15d9e14a9b8e8078072c048366808c38e899bcc7c422674bf16eb7688a1bcee')), dict(candidates=inventory)


@pytest.fixture
def installed(monkeypatch):
    monkeypatch.setattr(r, '_STATE', None)
    for module, names in [(f, ('_verified', 'load_descriptive_authority', 'validate_reconstructed_accounting_events')),
                           (p, ('profile_tasks', 'profile_contract', 'load_authority', 'contract_for_authority',
                                'required_action_roles'))]:
        for name in names:
            monkeypatch.setattr(module, name, getattr(module, name))
    binding, inventory = fixture_metadata()
    refs = {name: pin(name+'.json') for name in ('config','binding','accepted','oldconfig','sealed','inventory','schedule','admission','qualification','outputs','plan')}
    refs['schedule']['sha256'] = r.SCHEDULE_SHA
    binding['original_inventory_ref'] = refs['inventory']
    manifest = r.candidate_rows(binding, inventory)
    sources = {k: pin(k+'.json') for k in f.SOURCE_GROUPS}
    windows = [dict(window_id='MAIN', start='2026-01-02', end='2026-10-08')]
    windows += [dict(window_id=f'RANDOM_{i:03d}', start='2026-01-05', end='2026-10-08') for i in range(1,101)]
    old = dict(task_id=r.OLD_TASK, inventory_ref=refs['inventory'], schedule_ref=refs['schedule'],
               admission_ref=refs['admission'], plan_ref=refs['plan'], runtime_source_refs=[])
    oldbound = dict(task_id=r.OLD_TASK, status='SOURCE_AND_POLICY_BOUND_FOR_DESCRIPTIVE_EVALUATION',
                    candidate_manifest_ref=refs['inventory'], schedule_ref=refs['schedule'], windows=windows,
                    candidate_bindings=inventory['candidates'], fresh_account=True, initial_cash_usd=3000,
                    initial_holdings=[], initial_receivables=[], strict_PIT_promotion_eligible=False,
                    production_qualified=False, finalist_selected=False, source_refs=sources,
                    source_qualification_ref=refs['qualification'], allowed_path_ids=[x['candidate_id'] for x in inventory['candidates']],
                    state_refs={}, as_of='2026-10-09T01:00:00+00:00', feature_history_start='2023-01-03', raw_selector_binding={})
    q = dict(task_id=r.OLD_TASK, source_refs=sources, groups={k:True for k in f.SOURCE_GROUPS},
             candidate_source_qualification={cid:dict(status='QUALIFIED',required_action_roles=[],source_ref=sources['action_inputs'])
                                             for cid in oldbound['allowed_path_ids']})
    own = dict(path=str(Path(r.__file__).resolve()), sha256=hashlib.sha256(Path(r.__file__).read_bytes()).hexdigest())
    config = dict(task_id=r.TASK, execution_release='ROOT_RELEASED_FROZEN_CASH63_2026',new_fit=0,tuning=False,
                  user_scope='SYNTHETIC_FIXED63_NO_RESEARCH_EXECUTION',source_pins={'profile':own},
                  head_binding_ref=refs['binding'],training_acceptance_ref=refs['accepted'],
                  old_account_config_ref=refs['oldconfig'],sealed_recovery_config_ref=refs['sealed'],
                  schedule_ref=refs['schedule'], candidates=manifest,source_refs=sources,new_value_outputs_ref=refs['outputs'])
    docs = {refs['config']['path']:config, refs['binding']['path']:binding, refs['inventory']['path']:inventory,
            refs['oldconfig']['path']:old, refs['schedule']['path']:dict(windows=windows), refs['admission']['path']:oldbound,
            refs['qualification']['path']:q, refs['sealed']['path']:dict(original_config_ref=refs['oldconfig'],sources=[],training_allowed=False,prediction_allowed=False),
            refs['accepted']['path']:dict(schema='CASH12_FINAL_TRAINING_AND_BINDING_ACCEPTANCE_R1',status='COMPLETE',binding_ref=refs['binding'],training_contract_earlier_cutoffs_preserved=True),
            refs['outputs']['path']:dict(new_fit=0,task_id=r.TASK,start='2026-01-02',end='2026-10-08',
                head_binding_ref=refs['binding'],training_acceptance_ref=refs['accepted'],requested_heads=12,support_heads=['lgb'],
                outputs={**{h:dict(role='REQUESTED_HEAD',model_ref=binding['heads'][h]['model_ref'],
                    receipt_ref=binding['heads'][h]['receipt_ref'],sigma=.07,lineage='SYNTHETIC_LINEAGE',frame_ref=pin(h+'.parquet'),
                    read_columns=['signal_date','ticker','prediction','prediction_qualified']) for h in r.HEADS},'lgb':dict(role='SUPPORT_ONLY')}),
            refs['plan']['path']:dict(as_of_utc=oldbound['as_of'])}
    old_state = str(Path(p._ALL_PINS['old_states'][0]))
    docs[old_state] = dict(value_models=[],risk_models=[])
    parent_contract = dict(metadata_refs=dict(old_states=dict(path=old_state,sha256=p._ALL_PINS['old_states'][1])),raw_selector_binding={})
    monkeypatch.setattr(p, 'profile_contract', lambda *a, **kw: deepcopy(parent_contract))
    from scripts.research.a2.training.stateful_values import diagnostic_columns
    for head, item in binding['heads'].items():
        docs[item['receipt_ref']['path']] = dict(native_model_id=head)
        if not head.startswith('fusion::'):
            docs[refs['outputs']['path']]['outputs'][head]['read_columns'].extend(diagnostic_columns(head))
    monkeypatch.setattr(r, '_document', lambda reference, **kw: deepcopy(docs[reference['path']]))
    monkeypatch.setattr(r, '_physical', lambda reference: Path(reference['path']))
    monkeypatch.setattr(p, '_document', lambda reference: deepcopy(docs[reference['path']]))
    calls = []
    def old_events(bound, source, task, key):
        assert task == r.OLD_TASK and bound == oldbound and source == sources
        calls.append(key)
        return json.dumps(dict(task_id=r.OLD_TASK,clock_role='POST_VERIFIED_ACCOUNTING_ONLY',
                               strict_PIT_promotion_eligible=False,production_qualified=False,
                               events=[dict(event_fingerprint='a'*64,reconstruction_ref=pin(key))]))
    monkeypatch.setattr(f, '_load_post_verified_binding', old_events)
    r.install_routes(refs['config'])
    return refs, docs, calls


def test_exact_recipe_and_model_identity():
    binding, inventory = fixture_metadata()
    result = r.candidate_rows(binding,inventory)
    assert len(result) == 63 and all(row['runtime_owner']=='STATEFUL_OVERLAY' for row in result)
    changed = deepcopy(binding); changed['configurations'][0]['original_rule_specification']['risk']='CHANGED'
    with pytest.raises(ValueError,match='RULES_CHANGED'):r.candidate_rows(changed,inventory)
    changed = deepcopy(binding); changed['configurations'][0]['new_model_ref']=pin('OTHER_MODEL')
    with pytest.raises(ValueError,match='HEAD_BYTES'):r.candidate_rows(changed,inventory)


def test_route_subset_original_controller_and_policy(installed):
    from scripts.research.a2.evaluation import stateful_frozen_a94 as controller
    specs = r.candidates()[:7]; ids=[c['candidate_id'] for c in specs]
    auth=r.load_authority('MAIN',ids)
    assert len(auth.allowed_path_ids)==63 and auth.source_ready_policy_ids==tuple(ids)
    batches=controller.prepare_batches(auth,specs)
    assert len(batches)==1 and batches[0].candidate_ids==tuple(ids)
    checked=batches[0].scoped_authority
    f.validate_descriptive_account(checked,['2026-01-02','2026-10-08'],ids,
        dict(initial_nav=3000,initial_cash=3000,initial_holdings=[],initial_receivables=[]),specs[0]['execution_friction'])
    f.require_descriptive_decision(checked,'2026-01-02',ids[0])
    changed=deepcopy(specs);changed[0]['gross']='CHANGED'
    with pytest.raises(ValueError,match='FULL_SPEC_CHANGED'):controller.prepare_batches(auth,changed)


def test_no_forgery_order_or_none(installed):
    ids=[c['candidate_id'] for c in r.candidates()[:2]]
    for bad in ([],ids[::-1],[ids[0],ids[0]],['UNREGISTERED']):
        with pytest.raises(ValueError,match='SUBSET'):r.load_authority('MAIN',bad)
    with pytest.raises(ValueError):f.load_descriptive_authority(None)
    value=r.load_authority('MAIN')
    with pytest.raises(ValueError):f._verified(replace(value,start=f.pd.Timestamp('2026-01-05')))
    with pytest.raises(ValueError):f._verified(replace(value,provenance_json='{}'))
    with pytest.raises(ValueError,match='REGISTERED_WINDOW'):r.load_authority('NOT_A_WINDOW')


def test_old_cash_header_then_new_honest_scope_and_original_exact_event_gate(installed):
    refs,docs,calls=installed
    assert calls==['research_cash_reconstruction','research_terminal_reconstruction']
    value=r.load_authority('MAIN')
    binding=json.loads(value.research_cash_reconstruction_json)
    assert binding['task_id']==r.TASK and binding['original_task_id']==r.OLD_TASK
    assert binding['new_scope_config_ref']==refs['config']
    assert binding['original_catalogue_ref']==docs[refs['admission']['path']]['source_refs']['corporate_actions']
    with pytest.raises(ValueError,match='CATALOGUE_CHANGED'):
        f.validate_reconstructed_accounting_events(value,[],require_exact=True)


def test_risk_loader_metadata_route_without_model_loading(installed):
    from scripts.research.a2.inference.frozen_a94_values import FrozenStateLoader
    specs=r.candidates()[:1];auth=r.load_authority('MAIN',[specs[0]['candidate_id']])
    checked=f.validate_descriptive_policy(auth,specs)
    loader=FrozenStateLoader(checked)
    assert loader.authority is checked
    with pytest.raises(ValueError,match='UNKNOWN_OR_UNBOUND'):loader.load('old_value:ridge')


def test_wrong_release_and_altered_frozen_manifest_fail_closed(installed,monkeypatch):
    refs,docs,_=installed
    monkeypatch.setattr(r,'_STATE',None)
    docs[refs['config']['path']]['tuning']=True
    with pytest.raises(ValueError,match='ACCOUNT_ONLY_RELEASE'):r._prepare(refs['config'],f,p)


def test_physical_sha_verification_is_real(tmp_path):
    path=tmp_path/'synthetic_metadata.json';path.write_text('{}',encoding='utf-8')
    reference=dict(path=str(path),sha256=hashlib.sha256(b'{}').hexdigest())
    assert r._document(reference)=={}
    path.write_text('{"changed":true}',encoding='utf-8')
    with pytest.raises(ValueError,match='SOURCE_SHA_CHANGED'):r._document(reference)

def test_metadata_size_caps_are_role_bound(tmp_path):
    def document(size):
        payload=b'{"pad":"'+b'x'*(size-10)+b'"}'
        assert len(payload)==size
        path=tmp_path/(str(size)+'.json');path.write_bytes(payload)
        return dict(path=str(path),sha256=hashlib.sha256(payload).hexdigest())
    ordinary=document(2_000_000)
    assert isinstance(r._document(ordinary),dict)
    expanded=document(4*1024*1024)
    with pytest.raises(ValueError,match='BOUNDED_METADATA'):r._document(expanded)
    assert isinstance(r._document(expanded,kind='source_qualification'),dict)
    too_large=document(4*1024*1024+1)
    with pytest.raises(ValueError,match='BOUNDED_METADATA'):r._document(too_large,kind='source_qualification')
    with pytest.raises(ValueError,match='KNOWN_METADATA_KIND'):r._document(ordinary,kind='unlimited')
