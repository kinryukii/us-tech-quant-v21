"""Account-only routing over immutable consensus owners; no action on import.

Templates and private functions are engineering artifacts. They create no run,
fit, source admission or data authority. The original source loader must still
accept a composed source scope before an authorized account entry can proceed.
"""
from __future__ import annotations
import ast
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from scripts.common.storage_paths import assert_safe_output_path, resolve
from scripts.research.a2.evaluation import consensus_evaluation_run as engine

SCHEMA = 'CONSENSUS_ACCOUNT_SOURCE_CONTINUATION_ROUTING_R1'
ENGINEERING = 'ENGINEERING_ONLY_NO_ACCOUNT_EXECUTION'
AUTHORIZED = 'AUTHORIZED_PRE2026_ACCOUNT_REPLAY'
PRIOR_FITS = 1291
FIT_LIMIT = 10000
FEATURE_ORIGIN = engine.fusion.PARENT_RUN
FROZEN_ORIGIN = engine.fusion.CONTINUATION_RUN
FREEZE = 'CONSENSUS_ACCOUNT_SOURCE_CONTINUATION_FREEZE.json'
REF_PATHS = {
    'account_freeze': (FROZEN_ORIGIN, engine.FREEZE),
    'fusion_freeze': (FROZEN_ORIGIN, 'CONSENSUS_FUSION_FREEZE.json'),
    'predictor_freeze': (FEATURE_ORIGIN, 'CONSENSUS_PREDICTOR_FREEZE.json'),
    'features': (FEATURE_ORIGIN, 'derived/consensus100_daily.parquet'),
    'final_calibration_manifest': (FROZEN_ORIGIN, 'models/consensus_final_calibration_completion/receipt.json'),
    'final_calibration_freeze': (FROZEN_ORIGIN, 'CONSENSUS_FINAL_CALIBRATION_COMPLETION_FREEZE.json'),
}
RISK_IDENTITY = ('owner', 'source_return_matrix', 'asset_order', 'window', 'cutoff', 'params', 'custody')
ENGINE_SHA = {
    'runner': 'acbe5224a155969ee28fbc13bdba858744a6e7439bc60a777a0f274d8f9c3b6f',
    'account_inputs': 'dbd16fe143886d9ecb2d2507b2583e05caf0933e1962ab8c43db9b4ed713e31a',
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def file_ref(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return dict(path=str(path), sha256=digest.hexdigest())


def _pin(ref):
    require(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}, 'ROUTING_EXACT_REF_REQUIRED')
    require(file_ref(ref['path'])['sha256'] == ref['sha256'], 'ROUTING_REFERENCE_CHANGED')
    return Path(ref['path'])


def _fields(ref, names):
    """Lexically skip unselected JSON values, including calibration payloads."""
    path = _pin(ref)
    require(path.suffix == '.json' and path.stat().st_size <= 1024 * 1024, 'ROUTING_SMALL_METADATA_REQUIRED')
    with path.open('rb') as stream:
        return engine.account_inputs._JsonProjection(stream).metadata_fields(set(names))


def source_pins():
    original = engine.source_pins()
    require(all(original[k]['sha256'] == sha for k, sha in ENGINE_SHA.items()), 'ROUTING_PROTECTED_ENGINE_CHANGED')
    return dict(original_engine=original, routing_adapter=file_ref(__file__))


def _output(run):
    run = Path(run).resolve()
    assert_safe_output_path(run, kind='backtest', paths=resolve(engine.predictors.REPO))
    require(engine.TASK in run.parts, 'ROUTING_MANAGED_TASK_PATH_REQUIRED')
    for origin in (FEATURE_ORIGIN.resolve(), FROZEN_ORIGIN.resolve()):
        require(not run.is_relative_to(origin) and not origin.is_relative_to(run), 'ROUTING_OLD_OUTPUT_FORBIDDEN')
    return run


def template(output_run, *, frozen_refs, source_scope_ref, composition_ref=None, expected_source_set=None):
    """Return metadata only. The caller saves it through the managed-run owner."""
    return dict(schema=SCHEMA, status=ENGINEERING, task_id=engine.TASK,
        output_run=str(_output(output_run)), feature_origin=str(FEATURE_ORIGIN),
        frozen_origin=str(FROZEN_ORIGIN), frozen_refs=copy.deepcopy(frozen_refs),
        account_source_scope_ref=copy.deepcopy(source_scope_ref),
        composition_ref=copy.deepcopy(composition_ref), expected_source_set=copy.deepcopy(expected_source_set),
        required_supplement_count=None if expected_source_set is None else sum(len(x['event_keys']) for x in expected_source_set['supplements']),
        source_pins=source_pins(),
        recipe=engine.recipe_for_run(engine.fusion.CONTINUATION_RUN),
        budget=dict(prior_fit_units=PRIOR_FITS, max_fit_units=FIT_LIMIT),
        old_account_state_reused=False, risk_cache_identity_fields=list(RISK_IDENTITY),
        source_policy='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY',
        test_2026_read_authorized=False, real_account_execution_authorized=False)


def _calibration_count(ref):
    path = _pin(ref)
    require(path.suffix == '.json' and path.stat().st_size <= 1024 * 1024, 'ROUTING_SMALL_METADATA_REQUIRED')
    count = 0
    for name in ('predictor_completions', 'fusion_completions'):
        with path.open('rb') as stream:
            q = engine.account_inputs._JsonProjection(stream)
            q.descend((name,)); q.expect(b'[')
            while True:
                q.white()
                if q.peek() == b']':
                    q.take(); break
                q.skip(); count += 1; q.white()
                if q.peek() == b',': q.take()
                else: q.expect(b']'); break
    return count


def validate_composition(ref, *, expected_source_set, execute=False):
    """The original owner, not this metadata connector, admits every source."""
    require(ref is not None, 'ROUTING_SOURCE_COMPOSITION_REQUIRED')
    require(isinstance(expected_source_set, dict) and set(expected_source_set) == {'base_ref', 'supplements'}, 'ROUTING_FROZEN_SOURCE_SET_REQUIRED')
    required_supplements = sum(len(x['event_keys']) for x in expected_source_set['supplements'])
    value = _fields(ref, ('schema', 'status', 'base_native_count', 'supplement_count',
        'base_ref', 'supplements', 'joint_source_scope_ref', 'joint_owner_preflight_ref',
        'original_namespaces_preserved', 'source_conflicts_resolved_by_choice'))
    require(value.get('schema') == 'CONSENSUS_ACCOUNT_SOURCE_COMPOSITION_ROUTING_R1', 'ROUTING_COMPOSITION_SCHEMA_REQUIRED')
    require(value.get('base_native_count') == 105 and value.get('supplement_count') == required_supplements,
        'ROUTING_ALL105_AND_ACCEPTED_SUPPLEMENTS_REQUIRED')
    require(value.get('original_namespaces_preserved') is True
        and value.get('source_conflicts_resolved_by_choice') is False, 'ROUTING_ORIGINAL_NAMESPACE_NO_CHOICE_REQUIRED')
    require(value.get('base_ref') == expected_source_set['base_ref'] and value.get('supplements') == expected_source_set['supplements'], 'ROUTING_FROZEN_SOURCE_SET_CHANGED')
    _pin(value['base_ref'])
    keys = []; fingerprints = []
    for item in value['supplements']:
        require(set(item) == {'bundle_ref', 'native_owner_ref', 'review_ref', 'original_namespace',
            'event_keys', 'event_fingerprints'}, 'ROUTING_EXACT_SUPPLEMENT_PROVENANCE_REQUIRED')
        require(item['original_namespace'] and len(item['event_keys']) == len(item['event_fingerprints']),
            'ROUTING_SUPPLEMENT_NAMESPACE_FINGERPRINT_REQUIRED')
        for role in ('bundle_ref', 'native_owner_ref', 'review_ref'): _pin(item[role])
        keys.extend(json.dumps(k, sort_keys=True) for k in item['event_keys'])
        fingerprints.extend(item['event_fingerprints'])
    require(len(keys) == value['supplement_count'] and len(set(keys)) == len(keys)
        and len(set(fingerprints)) == len(fingerprints), 'ROUTING_SUPPLEMENT_DUPLICATE_OR_MISSING_EVENT')
    if execute:
        require(value.get('status') == 'QUALIFIED_BY_ORIGINAL_OWNER_NO_ACCOUNT_REPLAY', 'ROUTING_ALL_SOURCE_QUALIFICATION_REQUIRED')
        proof = _fields(value['joint_owner_preflight_ref'], ('status', 'source_scope_ref', 'all_source_qualified',
            'base_native_count', 'supplement_count', 'original_namespaces_preserved', 'source_conflicts_resolved_by_choice'))
        require(proof.get('status') == 'PASS_ORIGINAL_ACCOUNT_SOURCE_OWNER_PREFLIGHT'
            and proof.get('all_source_qualified') is True and proof.get('base_native_count') == 105
            and proof.get('supplement_count') == value['supplement_count']
            and proof.get('source_scope_ref') == value['joint_source_scope_ref']
            and proof.get('original_namespaces_preserved') is True
            and proof.get('source_conflicts_resolved_by_choice') is False, 'ROUTING_JOINT_ORIGINAL_OWNER_PROOF_REQUIRED')
    return value


def validate(route, *, execute=False):
    run = _output(route['output_run'])
    require(route.get('schema') == SCHEMA and route.get('task_id') == engine.TASK, 'ROUTING_MANIFEST_REQUIRED')
    require(route.get('feature_origin') == str(FEATURE_ORIGIN) and route.get('frozen_origin') == str(FROZEN_ORIGIN),
        'ROUTING_FROZEN_ORIGIN_CHANGED')
    require(route.get('source_pins') == source_pins(), 'ROUTING_SOURCE_PINS_CHANGED')
    require(route.get('budget') == dict(prior_fit_units=PRIOR_FITS, max_fit_units=FIT_LIMIT), 'ROUTING_BUDGET_RESET_FORBIDDEN')
    require(route.get('recipe') == engine.recipe_for_run(engine.fusion.CONTINUATION_RUN)
        and len(route['recipe']['fusion_methods']) == 14, 'ROUTING_ALL14_WITH_ZERO_ABSTAIN_REQUIRED')
    require(route.get('old_account_state_reused') is False
        and route.get('risk_cache_identity_fields') == list(RISK_IDENTITY), 'ROUTING_OLD_STATE_OR_PARTIAL_RISK_IDENTITY_FORBIDDEN')
    require(route.get('source_policy') == 'FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY'
        and route.get('test_2026_read_authorized') is False, 'ROUTING_PRE2026_ONLY_REQUIRED')
    expected = route.get('expected_source_set')
    count = None if expected is None else sum(len(x['event_keys']) for x in expected['supplements'])
    require(route.get('required_supplement_count') == count, 'ROUTING_ACCEPTED_SUPPLEMENT_COUNT_REQUIRED')
    refs = route['frozen_refs']; require(set(refs) == set(REF_PATHS), 'ROUTING_EXACT_FROZEN_REFS_REQUIRED')
    for role, (root, relative) in REF_PATHS.items():
        require(Path(refs[role]['path']).resolve() == (root / relative).resolve(), 'ROUTING_FROZEN_REF_PATH_CHANGED:' + role)
    # Only these bounded JSON metadata fields are decoded. No features, predictions or joblib.
    account = _fields(refs['account_freeze'], ('recipe', 'source_pins', 'final_calibration_completion_ref', 'predictor_freeze_ref', 'fusion_freeze_ref'))
    require(account.get('recipe') == route['recipe'] and account.get('source_pins') == route['source_pins']['original_engine']
        and account.get('final_calibration_completion_ref') == refs['final_calibration_manifest']
        and account.get('predictor_freeze_ref') == refs['predictor_freeze']
        and account.get('fusion_freeze_ref') == refs['fusion_freeze'], 'ROUTING_ORIGINAL_EVALUATION_CLOSURE_CHANGED')
    predictor = _fields(refs['predictor_freeze'], ('membership_sha256',))
    require(predictor.get('membership_sha256') == refs['features']['sha256'], 'ROUTING_FROZEN_FEATURE_READER_REF_CHANGED')
    calibration = _fields(refs['final_calibration_manifest'], ('completion_spec_ref', 'status', 'native_training_refitted', 'test_2026_content_read'))
    require(calibration.get('completion_spec_ref') == refs['final_calibration_freeze']
        and calibration.get('status') == 'COMPLETE_PRE2026_CALIBRATION_NO_TEST_READ_AUTHORITY'
        and calibration.get('native_training_refitted') is False and calibration.get('test_2026_content_read') is False
        and _calibration_count(refs['final_calibration_manifest']) == 51, 'ROUTING_FROZEN51_CALIBRATION_REQUIRED')
    for role in ('fusion_freeze', 'predictor_freeze', 'final_calibration_freeze'): _pin(refs[role])
    cal_sources = _fields(refs['final_calibration_freeze'], ('source_pins',))
    for ref in cal_sources['source_pins'].values(): _pin(ref)
    if execute:
        require(route.get('status') == AUTHORIZED and route.get('real_account_execution_authorized') is True,
            'ROUTING_REAL_ACCOUNT_EXECUTION_NOT_AUTHORIZED')
        composed = validate_composition(route['composition_ref'], expected_source_set=expected, execute=True)
        require(route['account_source_scope_ref'] == composed['joint_source_scope_ref'], 'ROUTING_COMPOSED_SOURCE_SCOPE_CHANGED')
    return run


def compose_sources(combined, descendants, *, composition_ref, expected_source_set):
    """Connect already-native facts to the original conflict-checking merger."""
    manifest = validate_composition(composition_ref, expected_source_set=expected_source_set)
    require(len(descendants) == len(manifest['supplements']), 'ROUTING_ALL_NATIVE_DESCENDANTS_REQUIRED')
    result = combined
    for item, descendant in zip(manifest['supplements'], descendants):
        require(descendant['original_namespace'] == item['original_namespace']
            and descendant['bundle_ref'] == item['bundle_ref']
            and descendant['event_fingerprints'] == item['event_fingerprints'], 'ROUTING_NATIVE_NAMESPACE_OR_FINGERPRINT_CHANGED')
        actual = {event.event_fingerprint for event in descendant['native']['events']['entitlement_events']}
        require(set(item['event_fingerprints']) <= actual, 'ROUTING_NATIVE_EVENT_FINGERPRINT_MISSING')
        result = engine.account_inputs.merge_completion_descendant(result, descendant['native'], composition_ref)
    return result



def _bind_native_bundle(item, original_owner, original, calendar):
    """Original immutable native entry, with its own exact bundle/SCOPE.

    Only a future authorized caller reaches this function. No native bundle is
    decoded while building or validating an engineering routing template.
    """
    _pin(item['native_owner_ref']); bundle_path = _pin(item['bundle_ref'])
    token = item['native_owner_ref']['sha256'] + item['bundle_ref']['sha256']
    owner = engine.account_inputs.existing._load_python(item['native_owner_ref'],
        '_consensus_source_continuation_native_' + hashlib.sha256(token.encode()).hexdigest()[:20])
    bundle = json.loads(bundle_path.read_text(encoding='utf-8'))
    return owner.bind_source_account_descendant(original_owner, original, bundle,
        account_dates=calendar, bundle_ref=item['bundle_ref'])


def connect_qualified_supplements(route, combined, composition, bound, original_owner, original):
    """Keep the R6 branch intact; connect each heterogeneous immutable native owner."""
    require(route.get('status') == AUTHORIZED and route.get('real_account_execution_authorized') is True,
        'ROUTING_REAL_ACCOUNT_EXECUTION_NOT_AUTHORIZED')
    manifest = validate_composition(route['composition_ref'],
        expected_source_set=route['expected_source_set'], execute=True)
    require(bound['source_scope_ref'] == route['account_source_scope_ref'] == manifest['joint_source_scope_ref'],
        'ROUTING_COMPOSED_SOURCE_SCOPE_CHANGED')
    descendants = []
    for item in manifest['supplements']:
        native = _bind_native_bundle(item, original_owner, original, bound['calendar'])
        descendants.append(dict(original_namespace=item['original_namespace'], bundle_ref=item['bundle_ref'],
            event_fingerprints=item['event_fingerprints'], native=native))
    result = compose_sources(combined, descendants, composition_ref=route['composition_ref'],
        expected_source_set=route['expected_source_set'])
    return result, dict(original_R6=composition, supplementary_composition_ref=route['composition_ref'],
        original_bundle_namespaces=[item['original_namespace'] for item in manifest['supplements']],
        ordinary_R6_owner_or_SCOPE_replaced=False)


def _source_inputs_namespace(route):
    """One routing hook before original typed-fact checks and quote construction."""
    original = engine.account_inputs
    namespace = dict(vars(original))
    namespace['_routing_connect_supplements'] = lambda combined, composition, bound, owner, kwargs: connect_qualified_supplements(
        route, combined, composition, bound, owner, kwargs)
    tree = ast.parse(Path(original.__file__).read_bytes())
    node = copy.deepcopy(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'load_account_inputs'))
    anchors = [i for i, stmt in enumerate(node.body) if isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call) and any(isinstance(arg, ast.Constant)
        and arg.value == 'TYPED_ACCOUNT_FACT_SCOPE_CHANGED' for arg in stmt.value.args)]
    require(len(anchors) == 1, 'ROUTING_SOURCE_INPUT_AST_ANCHOR_CHANGED')
    original_business = ast.dump(node, include_attributes=False)
    node.body[anchors[0]:anchors[0]] = ast.parse(
        'combined, composition = _routing_connect_supplements(combined, composition, bound, original_owner, original)').body
    restored = copy.deepcopy(node); del restored.body[anchors[0]]
    require(ast.dump(restored, include_attributes=False) == original_business, 'ROUTING_SOURCE_BUSINESS_AST_CHANGED')
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(module, original.__file__, 'exec'), namespace)
    return SimpleNamespace(**namespace)


def require_same_risk_cache_identity(old, new):
    require(set(old) == set(new) == set(RISK_IDENTITY) and old == new, 'ROUTING_RISK_CACHE_TUPLE_CHANGED')


def _replace_expression(node, before, after):
    original = ast.dump(ast.parse(before, mode='eval').body, include_attributes=False)
    replacement = ast.parse(after, mode='eval').body
    class Replace(ast.NodeTransformer):
        count = 0
        def visit(self, value):
            if isinstance(value, ast.expr) and ast.dump(value, include_attributes=False) == original:
                self.count += 1
                return ast.copy_location(copy.deepcopy(replacement), value)
            return super().visit(value)
    tx = Replace(); node = tx.visit(node)
    require(tx.count == 1, 'ROUTING_EXACT_AST_ANCHOR_CHANGED:' + before)
    return node


def bind_runner(route, freeze_ref):
    """Compile only isolated routing changes; never patch the imported engines.

    Calling the returned run_all still requires a separately authorized manifest
    and the original source loader. This function itself reads metadata/code only.
    """
    route = copy.deepcopy(route); run = validate(route)
    require(Path(freeze_ref['path']).resolve() == run / FREEZE, 'ROUTING_NEW_FREEZE_PATH_REQUIRED')
    namespace = dict(vars(engine)); namespace['_routing_origin'] = lambda value: FROZEN_ORIGIN if Path(value).resolve() == run else Path(value).resolve()
    namespace['_routing_feature_origin'] = lambda value: FEATURE_ORIGIN if Path(value).resolve() == run else engine.fusion.reader_run(value)
    namespace['_routing_prior'] = lambda value: route['budget']['prior_fit_units'] if Path(value).resolve() == run else (_ for _ in ()).throw(ValueError('ROUTING_WRONG_OUTPUT_RUN'))
    changes = {
        'recipe_for_run': [('Path(run).resolve()==fusion.CONTINUATION_RUN', '_routing_origin(run)==fusion.CONTINUATION_RUN')],
        'published_forecasts': [('Path(run).resolve()==fusion.CONTINUATION_RUN', '_routing_origin(run)==fusion.CONTINUATION_RUN'),
            ('fusion.published_fusion_forecasts(run,method,year,reader)', 'fusion.published_fusion_forecasts(_routing_origin(run),method,year,reader)')],
        'make_policy': [("fusion.metadata(run/'CONTINUATION_SCOPE.json')['budget']['prior_fit_units'] if run==fusion.CONTINUATION_RUN else 0", '_routing_prior(run)')],
        'run_all': [('fusion.reader_run(run)', '_routing_feature_origin(run)')],
    }
    tree = ast.parse(Path(engine.__file__).read_bytes()); nodes = []
    for old in tree.body:
        if not isinstance(old, ast.FunctionDef): continue
        node = copy.deepcopy(old)
        for before, after in changes.get(node.name, ()): node = _replace_expression(node, before, after)
        nodes.append(node)
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(module, engine.__file__, 'exec'), namespace)
    namespace['source_pins'] = source_pins
    # Windows spawn must resolve the actual original module-level worker object.
    namespace['_risk_worker'] = engine._risk_worker
    namespace['account_inputs'] = _source_inputs_namespace(route)
    def contract(value):
        require(Path(value).resolve() == run, 'ROUTING_WRONG_OUTPUT_RUN')
        validate(route, execute=True)
        require(_fields(freeze_ref, set(route)) == route, 'ROUTING_SAVED_FREEZE_CHANGED')
        frozen = dict(route, account_source_scope_ref=route['account_source_scope_ref'])
        return run, frozen, freeze_ref
    namespace['contract'] = contract
    return SimpleNamespace(**namespace), dict(changed_routing_functions=list(changes), anchor_count=5, source_input_routing_anchor_count=1, original_spawn_worker_identity_preserved=True,
        remaining_function_AST_unchanged=True, original_engine_globals_modified=False,
        input_data_or_run_created=False, real_account_run_executed=False)
