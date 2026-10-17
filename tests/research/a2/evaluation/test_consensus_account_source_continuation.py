"""Generated custody and isolated routing only; no actual data, run or fit."""
import copy
import hashlib
import json
import pickle
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import pytest
from scripts.research.a2.evaluation import consensus_account_source_continuation as routing


def saved(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')
    return routing.file_ref(path)


@pytest.fixture
def route_fixture(tmp_path, monkeypatch):
    r1 = tmp_path / routing.engine.TASK / 'R1'
    r2 = tmp_path / routing.engine.TASK / 'R2'
    monkeypatch.setattr(routing, 'FEATURE_ORIGIN', r1)
    monkeypatch.setattr(routing, 'FROZEN_ORIGIN', r2)
    mapping = {name: ((r1 if name in ('predictor_freeze', 'features') else r2), rel)
        for name, (_, rel) in routing.REF_PATHS.items()}
    monkeypatch.setattr(routing, 'REF_PATHS', mapping)
    refs = {}
    for name, (root, rel) in mapping.items():
        if name in ('account_freeze', 'final_calibration_manifest'): continue
        value = {'source_pins': {'runner': routing.file_ref(routing.engine.__file__)}} if name == 'final_calibration_freeze' else {}
        refs[name] = saved(root / rel, value)
    refs['predictor_freeze'] = saved(r1 / mapping['predictor_freeze'][1], {'membership_sha256': refs['features']['sha256']})
    refs['final_calibration_manifest'] = saved(r2 / mapping['final_calibration_manifest'][1], dict(
        completion_spec_ref=refs['final_calibration_freeze'], status='COMPLETE_PRE2026_CALIBRATION_NO_TEST_READ_AUTHORITY',
        native_training_refitted=False, test_2026_content_read=False,
        predictor_completions=[{'synthetic_calibration_payload_must_skip': 123456789}] * 37,
        fusion_completions=[{'synthetic_calibration_payload_must_skip': 123456789}] * 14))
    refs['account_freeze'] = saved(r2 / mapping['account_freeze'][1], dict(
        recipe=routing.engine.recipe_for_run(routing.engine.fusion.CONTINUATION_RUN),
        source_pins=routing.source_pins()['original_engine'], final_calibration_completion_ref=refs['final_calibration_manifest'],
        predictor_freeze_ref=refs['predictor_freeze'], fusion_freeze_ref=refs['fusion_freeze']))
    scope = saved(tmp_path / 'source_scope.json', {'task_id': routing.engine.TASK})
    output = routing.resolve(routing.engine.predictors.REPO).backtest_root / routing.engine.TASK / 'synthetic_route_never_created'
    assert not output.exists()
    route = routing.template(output, frozen_refs=refs, source_scope_ref=scope)
    return route, refs, tmp_path


def test_frozen_origin14_recipe_and_no_metadata_feature_or_calibration_payload_read(route_fixture, monkeypatch):
    route, refs, _ = route_fixture
    pinned = []; actual = routing._pin
    monkeypatch.setattr(routing, '_pin', lambda ref: (pinned.append(ref['path']), actual(ref))[1])
    decoded = []; q = routing.engine.account_inputs._JsonProjection; scalar = q.scalar
    def tracked(self, *args, **kwargs):
        value = scalar(self, *args, **kwargs); decoded.append(value); return value
    monkeypatch.setattr(q, 'scalar', tracked)
    assert routing.validate(route) == Path(route['output_run'])
    assert len(route['recipe']['fusion_methods']) == 14
    assert route['recipe']['fusion_methods'][-1] == routing.engine.fusion.owner.NNLS_ZERO_ABSTAIN
    assert refs['features']['path'] not in pinned
    assert 'synthetic_calibration_payload_must_skip' not in json.dumps(decoded)
    assert not Path(route['output_run']).exists()


@pytest.mark.parametrize('mutation,code', [
    (lambda r: r.update(frozen_origin='wrong'), 'FROZEN_ORIGIN'),
    (lambda r: r.update(feature_origin='wrong'), 'FROZEN_ORIGIN'),
    (lambda r: r['budget'].update(prior_fit_units=0), 'BUDGET_RESET'),
    (lambda r: r['recipe']['fusion_methods'].pop(), 'ALL14'),
    (lambda r: r.update(old_account_state_reused=True), 'OLD_STATE'),
    (lambda r: r['risk_cache_identity_fields'].pop(), 'PARTIAL_RISK'),
    (lambda r: r.update(test_2026_read_authorized=True), 'PRE2026'),
    (lambda r: r.update(required_supplement_count=35), 'SUPPLEMENT_COUNT'),
    (lambda r: r['source_pins']['original_engine']['runner'].update(sha256='0'*64), 'SOURCE_PINS'),
    (lambda r: r['frozen_refs']['features'].update(path='wrong'), 'FROZEN_REF_PATH'),
])
def test_bad_routes_fail_before_source_loader(route_fixture, mutation, code, monkeypatch):
    route, _, _ = route_fixture
    mutation(route)
    with pytest.raises(ValueError, match=code): routing.validate(route)


def test_old_output_and_parent_output_rejected(route_fixture, monkeypatch):
    route, _, _ = route_fixture
    monkeypatch.setattr(routing, 'assert_safe_output_path', lambda *a, **k: None)
    for origin in (routing.FEATURE_ORIGIN, routing.FROZEN_ORIGIN, routing.FROZEN_ORIGIN / 'child'):
        route['output_run'] = str(origin)
        with pytest.raises(ValueError, match='OLD_OUTPUT'): routing.validate(route)


def test_wrong_frozen_closure_and_wrong51count_rejected(route_fixture):
    route, refs, _ = route_fixture
    p = Path(refs['final_calibration_manifest']['path']); payload = json.loads(p.read_text())
    payload['fusion_completions'].pop(); route['frozen_refs']['final_calibration_manifest'] = saved(p, payload)
    # Preserve the referring account freeze so the count gate is actually reached.
    ap = Path(refs['account_freeze']['path']); account = json.loads(ap.read_text())
    account['final_calibration_completion_ref'] = route['frozen_refs']['final_calibration_manifest']
    route['frozen_refs']['account_freeze'] = saved(ap, account)
    with pytest.raises(ValueError, match='FROZEN51'): routing.validate(route)
    route['frozen_refs']['account_freeze']['sha256'] = '0'*64
    with pytest.raises(ValueError, match='REFERENCE_CHANGED'): routing.validate(route)


def private_runner(route):
    freeze_ref = dict(path=str(Path(route['output_run']) / routing.FREEZE), sha256='a'*64)
    runner, anchors = routing.bind_runner(route, freeze_ref)
    ns = runner.run_all.__globals__
    fusion = SimpleNamespace(**vars(routing.engine.fusion)); fusion.CONTINUATION_RUN = routing.FROZEN_ORIGIN
    ns['fusion'] = fusion  # Only the private function namespace changes.
    return runner, ns, anchors


def test_private_routing_keeps_original_windows_worker_and_blocks_run(route_fixture, monkeypatch):
    route, _, _ = route_fixture
    original_recipe = copy.deepcopy(routing.engine.RECIPE)
    runner, ns, anchors = private_runner(route)
    assert anchors['anchor_count'] == 5 and anchors['remaining_function_AST_unchanged']
    assert runner._risk_worker is routing.engine._risk_worker
    assert pickle.loads(pickle.dumps(runner._risk_worker)) is routing.engine._risk_worker
    assert len(runner.recipe_for_run(Path(route['output_run']))['fusion_methods']) == 14
    ns['account_inputs'] = SimpleNamespace(metadata_preflight=lambda **k: pytest.fail('unauthorized actual metadata'))
    with pytest.raises(ValueError, match='NOT_AUTHORIZED'): runner.run_all(Path(route['output_run']))
    assert routing.engine.RECIPE == original_recipe
    assert routing.engine.fusion.CONTINUATION_RUN != routing.FROZEN_ORIGIN
    assert not Path(route['output_run']).exists()


def test_private_oof_publication_calls_only_frozen_origin_and_three_pre26_years(route_fixture):
    route, _, _ = route_fixture; runner, ns, _ = private_runner(route); calls = []
    def published(origin, method, year, reader):
        calls.append((origin, year))
        return pd.DataFrame(dict(signal_date=[pd.Timestamp(f'{year}-01-03')], ticker='S', prediction=.01,
            value_sigma=.02, prediction_qualified=True)), {'year': year}
    ns['fusion'].published_fusion_forecasts = published
    frame, pins = runner.published_forecasts(Path(route['output_run']), 'equal', object())
    assert calls == [(routing.FROZEN_ORIGIN, y) for y in (2023, 2024, 2025)]
    assert len(frame) == len(pins) == 3
    assert ns['_routing_feature_origin'](Path(route['output_run'])) == routing.FEATURE_ORIGIN


def test_risk_controller_uses_new_log_inherited1291_and_original_worker_without_fit(route_fixture):
    route, _, _ = route_fixture; runner, ns, _ = private_runner(route); jobs = []
    values = SimpleNamespace(**vars(routing.engine.values)); values._events = lambda log: []
    values._fit_job = lambda *a, **kw: (jobs.append(kw), 'synthetic-not-fitted')[1]; ns['values'] = values
    class Policy:
        def __init__(self, *a, **kw): self.started = kw['on_risk_fit_started']
        def _risk(self): return None
    ns['joint'] = SimpleNamespace(ConsensusJointPolicy=Policy, risk=SimpleNamespace())
    policy = runner.make_policy(None, None, None, None, Path(route['output_run']), {}, {}, 'synthetic')
    policy.started({'method': 'LW'})
    bound_fit = policy._risk.__func__.__globals__['risk'].fit_risk_estimator
    assert bound_fit('LW', None, params={'fit_cutoff': '2025-12-31'}) == 'synthetic-not-fitted'
    assert jobs[0]['prior'] == 1291 and jobs[0]['auth']['max_fit_units'] == 10000
    assert jobs[0]['log'] == Path(route['output_run']) / 'FIT_LOG.jsonl'
    assert jobs[0]['worker_target'] is routing.engine._risk_worker
    assert not jobs[0]['log'].exists()


def test_exact_ast_anchor_drift_is_rejected():
    import ast
    node = ast.parse('def x():\n return 0').body[0]
    with pytest.raises(ValueError, match='AST_ANCHOR'): routing._replace_expression(node, 'missing()', 'new()')


@pytest.mark.parametrize('key', routing.RISK_IDENTITY)
def test_risk_cache_reuse_requires_every_exact_coordinate(key):
    identity = {k: ['same'] for k in routing.RISK_IDENTITY}
    routing.require_same_risk_cache_identity(identity, copy.deepcopy(identity))
    changed = copy.deepcopy(identity); changed[key] = ['different']
    with pytest.raises(ValueError, match='RISK_CACHE_TUPLE'): routing.require_same_risk_cache_identity(identity, changed)


def test_missing_or_unqualified_source_composition_cannot_run(route_fixture):
    route, _, _ = route_fixture
    route.update(status=routing.AUTHORIZED, real_account_execution_authorized=True)
    with pytest.raises(ValueError, match='SOURCE_COMPOSITION'): routing.validate(route, execute=True)


def test_original_owner_source_conflict_is_not_deduplicated(route_fixture):
    _, _, tmp = route_fixture; ca = routing.engine.account_inputs.existing.ca
    def event(amount):
        return ca.SourceBackedEntitlementEvent('cash','CASH_DIVIDEND','RAW:S','S','2025-06-03','2025-06-03','2025-06-04',
            '2025-06-01T00:00:00Z',amount,'USD',ca.USD_PER_RAW_OLD_SHARE,ca.RAW_OLD_SHARE_COORDINATE,
            'TIER2_LOCAL_CANONICAL','generated','a'*64)
    old, new = event(.2), event(.3)
    from dataclasses import replace
    native_events = (new,) + tuple(replace(new,event_id='cash'+str(i),ticker='S'+str(i),old_security_id='RAW:S'+str(i)) for i in range(1,36))
    bundle = saved(tmp/'bundle.json', {})
    item = dict(bundle_ref=bundle, native_owner_ref=routing.file_ref(routing.engine.account_inputs.__file__),
        review_ref=saved(tmp/'review.json', {'status':'generated source-only'}), original_namespace='ORIGINAL_RAW_S',
        event_keys=[{'ticker':str(i),'ex_date':'2025-06-03'} for i in range(36)],
        event_fingerprints=[e.event_fingerprint for e in native_events])
    comp = saved(tmp/'composition.json', dict(schema='CONSENSUS_ACCOUNT_SOURCE_COMPOSITION_ROUTING_R1',
        status=routing.ENGINEERING, base_native_count=105, supplement_count=36, base_ref=bundle,
        supplements=[item], original_namespaces_preserved=True, source_conflicts_resolved_by_choice=False))
    expected = dict(base_ref=bundle,supplements=[copy.deepcopy(item)])
    binding = dict(manifest={},source_fingerprint='a'*64,security_tickers={'RAW:S':'S'})
    combined = dict(entitlement_events=(old,), unsupported_events=(), entitlement_security_tickers={'RAW:S':'S'},
        entitlement_source_binding=binding,research_account_authority={})
    native = dict(events=dict(entitlement_events=native_events,entitlement_source_binding=dict(binding,
        manifest=dict(removed_exact_original_keys=[]))))
    descendant = dict(original_namespace=item['original_namespace'],bundle_ref=bundle,
        event_fingerprints=item['event_fingerprints'],native=native)
    with pytest.raises(ValueError, match='COMPLETION_CASH_SOURCE_CONFLICT_NO_CHOICE'):
        routing.compose_sources(combined, [descendant], composition_ref=comp,expected_source_set=expected)
    assert combined['entitlement_events'] == (old,)
    descendant['original_namespace'] = 'rewritten'
    with pytest.raises(ValueError, match='NATIVE_NAMESPACE'): routing.compose_sources(combined,[descendant],composition_ref=comp,expected_source_set=expected)
    with pytest.raises(ValueError, match='ALL_SOURCE_QUALIFICATION'): routing.validate_composition(comp, expected_source_set=expected, execute=True)



def test_frozen36_source_set_rejects_missing_whole_QCOM_bundle_even_if_count_is_changed(route_fixture):
    _, _, tmp = route_fixture
    base = saved(tmp/'base105.json', {})
    def batch(name, count, offset):
        return dict(bundle_ref=saved(tmp/(name+'.json'),{}),
            native_owner_ref=routing.file_ref(routing.engine.account_inputs.__file__),
            review_ref=saved(tmp/(name+'_review.json'),{'status':'generated independent acceptance'}),
            original_namespace=name,event_keys=[{'ticker':str(i),'ex_date':'2025-01-03'} for i in range(offset,offset+count)],
            event_fingerprints=[hashlib.sha256(str(i).encode()).hexdigest() for i in range(offset,offset+count)])
    prior35, qcom1 = batch('original_prior35',35,0),batch('original_QCOM1',1,35)
    expected = dict(base_ref=base,supplements=[prior35,qcom1])
    value = dict(schema='CONSENSUS_ACCOUNT_SOURCE_COMPOSITION_ROUTING_R1',status=routing.ENGINEERING,
        base_native_count=105,supplement_count=36,base_ref=base,supplements=[prior35,qcom1],
        original_namespaces_preserved=True,source_conflicts_resolved_by_choice=False)
    ref = saved(tmp/'composition_exact36.json',value)
    routing.validate_composition(ref,expected_source_set=expected)
    value['supplements'].pop();value['supplement_count']=35
    missing = saved(tmp/'composition_missing_QCOM.json',value)
    with pytest.raises(ValueError,match='ALL105_AND_ACCEPTED_SUPPLEMENTS'):
        routing.validate_composition(missing,expected_source_set=expected)
    value['supplement_count']=36
    missing = saved(tmp/'composition_missing_QCOM_false_count.json',value)
    with pytest.raises(ValueError,match='FROZEN_SOURCE_SET_CHANGED'):
        routing.validate_composition(missing,expected_source_set=expected)



def test_source_connector_preserves_original_metadata_R6_branch_and_private_hook(route_fixture):
    route, _, _ = route_fixture
    private = routing._source_inputs_namespace(route)
    assert private.metadata_preflight is routing.engine.account_inputs.metadata_preflight
    assert private.completion_metadata is routing.engine.account_inputs.completion_metadata
    assert private.load_account_inputs is not routing.engine.account_inputs.load_account_inputs
    assert '_routing_connect_supplements' in private.load_account_inputs.__code__.co_names
    assert '_routing_connect_supplements' not in routing.engine.account_inputs.load_account_inputs.__code__.co_names


def test_engineering_source_connector_rejects_before_any_native_bundle_decode(route_fixture, monkeypatch):
    route, _, _ = route_fixture
    monkeypatch.setattr(routing, '_bind_native_bundle', lambda *a: pytest.fail('native source decoded'))
    with pytest.raises(ValueError, match='NOT_AUTHORIZED'):
        routing.connect_qualified_supplements(route, {}, {}, {}, object(), {})


def test_generated_immutable_source_owners_each_receive_own_bundle_SCOPE_not_flattened(tmp_path):
    results = []
    for scope in ('original_scope_one', 'original_scope_two'):
        owner_path = tmp_path / (scope+'.py')
        owner_path.write_text(
            "def bind_source_account_descendant(env, original, bundle, *, account_dates, bundle_ref):\n"
            "    assert bundle['source_profile_completion_scope'] == "+repr(scope)+"\n"
            "    return dict(scope=bundle['source_profile_completion_scope'], bundle_ref=bundle_ref, original=original, calendar=account_dates)\n",
            encoding='utf-8')
        bundle_ref = saved(tmp_path/(scope+'.json'), {'source_profile_completion_scope':scope})
        item = dict(native_owner_ref=routing.file_ref(owner_path),bundle_ref=bundle_ref)
        results.append(routing._bind_native_bundle(item, object(), {'generated_original_source':True}, ('2025-01-03',)))
    assert [x['scope'] for x in results] == ['original_scope_one','original_scope_two']
    assert results[0]['bundle_ref'] != results[1]['bundle_ref']
    assert all(x['original']=={'generated_original_source':True} for x in results)
