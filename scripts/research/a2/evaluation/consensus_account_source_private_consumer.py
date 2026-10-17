"""Private consensus SOURCE wiring; import performs no market reads or execution.

Legacy exact61 remains engineering-only. Dynamic continuation requires the
existing human scope, complete SOURCE closure, a new managed output and saved
freeze. All cash/FX arithmetic stays with the protected canonical owners.
"""
from __future__ import annotations
import ast
import copy
import json
import inspect
import hashlib
import sys
from dataclasses import asdict, replace
from pathlib import Path
from types import FunctionType, SimpleNamespace
from scripts.research.a2.evaluation import consensus_account_source_continuation as routing
from scripts.research.a2.data import consensus_account_inputs as inputs
from scripts.research.a2.data import consensus_cad_source_completion as cad

SCHEMA = 'CONSENSUS61_PRIVATE_ACCOUNT_CONSUMER_ENGINEERING_R1'
READER_SCHEMA = 'CONSENSUS61_PRIVATE_SOURCE_DATA_READER_BINDING_R1'
FX_SCHEMA = 'CONSENSUS61_CAD272_KNOWN_RELEASE_SOURCE_QUALIFICATION_R1'
FREEZE = 'CONSENSUS61_PRIVATE_CONSUMER_FREEZE.json'
ENGINEERING = 'ENGINEERING_ONLY_NO_ACCOUNT_EXECUTION'
CAD_INDEX_COUNTS = {17: 3, 18: 1}
CONTINUATION_SCHEMA = 'CONSENSUS_DYNAMIC_PRIVATE_ACCOUNT_CONTINUATION_R1'
CONTINUATION_READER_SCHEMA = 'CONSENSUS_DYNAMIC_PRIVATE_SOURCE_DATA_READER_BINDING_R1'
CONTINUATION_FX_SCHEMA = 'CONSENSUS_DYNAMIC_CAD272_KNOWN_RELEASE_SOURCE_QUALIFICATION_R1'
EXECUTION_SCHEMA = 'CONSENSUS_PRE2026_NEW_ACCOUNT_EXECUTION_CONTRACT_R1'
AUTHORIZATION_SCHEMA = 'CONSENSUS_PRE2026_VENDOR_ACCOUNT_HUMAN_SCOPE_R1'
TASK_RESULTS = routing.resolve(routing.engine.predictors.REPO).results_root/'_maintenance'/routing.engine.TASK
HUMAN_AUTHORIZATION_REF = dict(path=str(TASK_RESULTS/'ACCOUNT_VENDOR_CONTINUATION_HUMAN_SCOPE.json'),sha256='7beac10e71a29ab2cf75f221fb88e6938395c7e95da51b0fd64172133103f24a')
AUTHORIZED_SPEC_REF = dict(path=str(TASK_RESULTS/'AUTHORIZED_RESEARCH_SPEC.json'),sha256='9e7ac9f73d61a613eae5988e477d8825bb52ac112a422f7948bf885f1abc853b')
ORIGINAL_GAPS_REF = dict(path=str(TASK_RESULTS/'source_repair/ALL14_ACTUAL_ACCOUNT_LIFECYCLE_SOURCE_GAPS_R1.json'),sha256='5657520f8cf44ae729361d6438a7854275fa750f9b9e5eacb43ab0bf1398650c')
CONTINUATION_FREEZE = 'CONSENSUS_DYNAMIC_PRIVATE_CONSUMER_FREEZE.json'
PARTITION_SCHEMA = 'CONSENSUS_PRE2026_SOURCE_REVIEWED_NATIVE_UNSUPPORTED_PARTITION_R1'
PARTITION_STATUS = 'FROZEN_REVIEWED_PARTITION_NOT_ECONOMIC_PASS'
PARTITION_FREEZE = 'CONSENSUS_REVIEWED_PARTITION_PRIVATE_CONSUMER_FREEZE.json'
RISK_CODE_SOURCE_SHA = '3c603f20ebd362b3f495be5e48fad97771279f483184cc7e88f4e95a876efe56'
RISK_CODE_LOGICAL_REF = dict(path=str(routing.engine.predictors.REPO/'scripts/research/a2/inference/reused_r5_risk_inputs.py'),sha256=RISK_CODE_SOURCE_SHA)
RISK_CODE_FIXED_REF = dict(path=str(routing.resolve(routing.engine.predictors.REPO).cache_root/'V24/V24_B_FAST_TRACK_PAIR_COMPLETION_R1/source_audit/original_frozen'/('reused_r5_risk_inputs_'+RISK_CODE_SOURCE_SHA+'.py')),sha256=RISK_CODE_SOURCE_SHA)
RISK_CODE_TRANSPORT_REF = dict(path=str(TASK_RESULTS/'source_repair/vendor_api_gap_completion/R6_EXACT_RISK_CODE_CUSTODY_MINIMAL_DIFF_RECEIPT_R1.json'),sha256='7b0465e2a51f7059f306041de4971c063d03337c5122ba40717fa93e405a4774')
PARTITION_SCOPE_REF = dict(path=str(TASK_RESULTS/'source_repair/vendor_api_gap_completion/SOURCE_PARTITION_RESEARCH_EXECUTION_SCOPE_R8.json'),sha256='99a4f8ea58b268f212e11c0fdf6b9937db1d7654b0e4ac44ff20b54e484d2a44')
CVX_IDENTITY_PROJECTION_REF = dict(path=str(TASK_RESULTS/'source_repair/vendor_api_gap_completion/SOURCE192_CVX_EXACT_THREE_ORIGINAL_CLASS_DATED_RAW_IDENTITY_PROJECTION_FREEZE_R1.json'),sha256='403930a15afeea94568b712f7266ca19e896544ff1eb3c5cdb989a97df48e7c1')
DD_IDENTITY_PROJECTION_REF = dict(path=str(TASK_RESULTS/'source_repair/vendor_api_gap_completion/SOURCE192_DD_EXACT_ELEVEN_ORIGINAL_CLASS_DATED_RAW_IDENTITY_PROJECTION_FREEZE_R1.json'),sha256='26090e92bc26de128c96176ebfd4201bb3226e676fa1a5d43076dec3b51271fa')
IDENTITY_PROJECTION_MANIFEST_REF = dict(path=str(TASK_RESULTS/'source_repair/vendor_api_gap_completion/SOURCE192_CVX_DD_EXACT_IDENTITY_PROJECTION_MANIFEST_FREEZE_R1.json'),sha256='3c9968e6a0ec3da3486f64e618c989990484288546102597a606a5d2abb0ac1a')
AUTHORIZED = 'FROZEN_AUTHORIZED_PRE2026_ACCOUNT_CONTINUATION'
BINDER_KINDS = {'ORIGINAL_USD_NATIVE_BINDER','ORIGINAL_CAD_FOREIGN_NATIVE','MASSIVE_VENDOR_USD_NATIVE_BINDER'}
PROTECTED = {
 'routing': '87ee6432888e9ba423d7c07cd847fb6959e32700dfa2db9eaa826833a5f1f18b',
 'inputs': 'dbd16fe143886d9ecb2d2507b2583e05caf0933e1962ab8c43db9b4ed713e31a',
 'CAD': '52026df74a5887da76e322591a5be0c3245060b9c7a59586584805c5e4de5f56',
 'shareholder': '6e12fe1991aa71c8ab958dc48fc33442853ec00d3418e2127869457caa3dc578',
 'CA': '142c36633e47633fff5c9c63be030536fa7b1dba8a67f8432643c084f4dcdce4',
 'engine': 'acbe5224a155969ee28fbc13bdba858744a6e7439bc60a777a0f274d8f9c3b6f',
}
require = routing.require
canonical = lambda ref: {k: ref[k] for k in ('path', 'sha256')}


def protected_pins():
    modules = dict(routing=routing, inputs=inputs, CAD=cad,
        shareholder=inputs.account, CA=inputs.existing.ca, engine=routing.engine)
    for role, module in modules.items():
        require(routing.file_ref(module.__file__)['sha256'] == PROTECTED[role], 'PRIVATE_CONSUMER_PROTECTED_OWNER_CHANGED:' + role)
    require(cad.ca is inputs.existing.ca, 'PRIVATE_CONSUMER_CANONICAL_CA_REQUIRED')
    return {role: routing.file_ref(module.__file__) for role, module in modules.items()}


def _metadata(ref, names):
    return routing._fields(canonical(ref), names)


def _array_projection(ref, path):
    with routing._pin(canonical(ref)).open('rb') as stream:
        q=inputs._JsonProjection(stream);q.descend(path);q.expect(b'[');rows=[]
        while True:
            q.white()
            if q.peek()==b']':q.take();break
            rows.append(q.scalar());q.white()
            if q.peek()==b',':q.take()
            else:q.expect(b']');break
    return rows


def _source_entry_projection(q):
    """Large native groups retain bounded per-key/fingerprint metadata decoding."""
    q.expect(b'{');value={}
    while True:
        q.white()
        if q.peek()==b'}':q.take();break
        key=q.scalar();q.expect(b':')
        if key in ('event_keys','event_fingerprints','key_to_component_fingerprints'):
            q.expect(b'[');rows=[]
            while True:
                q.white()
                if q.peek()==b']':q.take();break
                rows.append(q.scalar());q.white()
                if q.peek()==b',':q.take()
                else:q.expect(b']');break
            value[key]=rows
        else:value[key]=q.scalar()
        q.white()
        if q.peek()==b',':q.take()
        else:q.expect(b'}');break
    return value


def expected_projection(ref, *, source_roles=None):
    """Each original scalar stays <=65KiB; never decode the whole large set."""
    p = routing._pin(canonical(ref))
    with p.open('rb') as stream:
        q = inputs._JsonProjection(stream); q.descend(('expected_source_set', 'base_ref')); base = q.scalar()
    with p.open('rb') as stream:
        q = inputs._JsonProjection(stream); q.descend(('expected_source_set', 'supplements')); q.expect(b'['); entries = []
        while True:
            q.white()
            if q.peek() == b']': q.take(); break
            entries.append(_source_entry_projection(q) if source_roles is not None else q.scalar()); q.white()
            if q.peek() == b',': q.take()
            else: q.expect(b']'); break
    value = dict(base_ref=base, supplements=entries)
    validate_entries(value, source_roles=source_roles)
    return value


def _composition_projection(ref, *, dynamic=False):
    value = _metadata(ref, ('schema','status','base_native_count','supplement_count',
        'base_ref','original_actual_preflight_ref','actual_source_preflight_ref','original_namespaces_preserved',
        'source_conflicts_resolved_by_choice'))
    path = routing._pin(canonical(ref))
    with path.open('rb') as stream:
        q = inputs._JsonProjection(stream); q.descend(('supplements',)); q.expect(b'['); entries = []
        while True:
            q.white()
            if q.peek() == b']': q.take(); break
            entries.append(_source_entry_projection(q) if dynamic else q.scalar()); q.white()
            if q.peek() == b',': q.take()
            else: q.expect(b']'); break
    value['supplements'] = entries
    return value


def _qualified_origin(route, expected, joint):
    scope = _metadata(route['qualified_source_scope_ref'], ('schema','task_id',
        'source_completion_count','qualified_source_expected_set_ref',
        'qualified_source_composition_ref','joint_owner_source_preflight_ref'))
    dynamic = route.get('schema') == CONTINUATION_SCHEMA
    count = route['current_source_count'] if dynamic else 61
    require(scope.get('schema') == 'CONSENSUS100_ACCOUNT_SOURCE_SCOPE_R1'
        and scope.get('task_id') == routing.engine.TASK and scope.get('source_completion_count') == count
        and scope.get('qualified_source_expected_set_ref') == route['expected_freeze_ref']
        and scope.get('joint_owner_source_preflight_ref') == route['source_joint_ref'],
        'PRIVATE61_QUALIFIED_ORIGIN_CURRENT_SOURCE_REFS_REQUIRED')
    composition = _composition_projection(scope['qualified_source_composition_ref'],dynamic=dynamic)
    if composition.get('schema') == 'CONSENSUS192_QUALIFIED_SOURCE_JOINT_COMPOSITION_VENDOR100':
        current_composition = (dynamic and count == 192 and len(composition['supplements']) == 35
            and composition.get('status') == 'QUALIFIED_EXACT192_ORIGINAL35_OWNER_NO_ACCOUNT'
            and composition.get('actual_source_preflight_ref') == route['source_joint_ref'])
    else:
        current_composition = (composition.get('schema') == 'CONSENSUS_ACCOUNT_SOURCE_COMPOSITION_ROUTING_R1'
            and composition.get('status') == f'QUALIFIED_EXACT{count}_BY_ORIGINAL_OWNER_NO_ACCOUNT_REPLAY'
            and composition.get('original_actual_preflight_ref') == route['source_joint_ref'])
    require(current_composition
        and composition.get('base_native_count') == 105 and composition.get('supplement_count') == count
        and composition.get('original_namespaces_preserved') is True
        and composition.get('source_conflicts_resolved_by_choice') is False,
        'PRIVATE61_CURRENT_COMPOSITION_AND_ACTUAL_JOINT_REQUIRED')
    require(composition['base_ref'] == expected['base_ref']
        and composition['supplements'] == expected['supplements'], 'PRIVATE61_EXPECTED_BASE_AND_OWNER_CUSTODY_CHANGED')
    routing._pin(canonical(expected['base_ref']))
    expected_metadata = _metadata(route['expected_freeze_ref'], ('original_actual_preflight_ref',))
    require(expected_metadata.get('original_actual_preflight_ref') == route['source_joint_ref'],
        'PRIVATE61_EXPECTED_ACTUAL_JOINT_REF_REQUIRED')
    # This is the original bootstrap scope used by actual joint source admission.
    # It remains distinct from the qualified61 scope and grants no new authority.
    routing._pin(canonical(joint['source_scope_ref']))
    return scope


def validate_entries(expected, *, source_roles=None):
    require(set(expected) == {'base_ref', 'supplements'}, 'PRIVATE61_EXPECTED_SOURCE_FIELDS_REQUIRED')
    entries = expected['supplements']
    roles = _entry_roles(expected, source_roles)
    if source_roles is None: require(len(entries) == 20, 'PRIVATE61_ALL20_OWNER_ENTRIES_REQUIRED')
    keys = []; fps = []; usd = 0; foreign = 0
    for index, item in enumerate(entries, 1):
        require(all(k in item for k in ('bundle_ref', 'native_owner_ref', 'original_namespace', 'event_keys', 'event_fingerprints')), 'PRIVATE61_ORIGINAL_OWNER_PROVENANCE_REQUIRED')
        require(item['original_namespace'], 'PRIVATE61_ORIGINAL_NAMESPACE_AND_FINGERPRINTS_REQUIRED')
        _event_component_map(item,roles[index-1]['binder_kind'])
        require(all(set(key) == {'ticker','effective_date','reason','source_reference','source_fingerprint'} for key in item['event_keys']), 'PRIVATE61_FULL_ORIGINAL5_FIELDS_REQUIRED')
        if roles[index-1]['binder_kind'] == 'ORIGINAL_CAD_FOREIGN_NATIVE':
            require(len(item['event_keys']) == roles[index-1]['event_count'], 'PRIVATE61_CAD_TWO_OWNER_FOUR_EVENTS_REQUIRED'); foreign += len(item['event_keys'])
        else: usd += len(item['event_keys'])
        keys.extend(inputs.existing.source._key(key) for key in item['event_keys']); fps.extend(item['event_fingerprints'])
    count = sum(len(item['event_keys']) for item in entries)
    require(foreign == 4 and len(set(keys)) == count and len(set(fps)) == len(fps), 'PRIVATE61_EXACT_SOURCE_KEYS_AND_FINGERPRINTS_REQUIRED')
    if source_roles is None: require(usd == 57 and count == 61, 'PRIVATE61_EXACT57_USD_AND4_CAD_REQUIRED')
    return dict(current_count=count,owner_count=len(entries),USD_owner_count=len(entries)-2,USD_count=usd,CAD_owner_count=2,CAD_count=4)


def _event_component_map(item, binder_kind):
    if binder_kind!='MASSIVE_VENDOR_USD_NATIVE_BINDER':
        require(len(item['event_keys'])==len(item['event_fingerprints']), 'PRIVATE61_ORIGINAL_NAMESPACE_AND_FINGERPRINTS_REQUIRED')
        return None
    rows=item.get('key_to_component_fingerprints')
    require(isinstance(rows,list) and len(rows)==len(item['event_keys']), 'DYNAMIC_VENDOR_QUALIFIED_COMPONENT_MAP_REQUIRED')
    keys=[];fps=[]
    for row in rows:
        require(set(row)=={'original_record','component_fingerprints'} and isinstance(row['component_fingerprints'],list)
            and row['component_fingerprints'], 'DYNAMIC_VENDOR_EXPLICIT_ORIGINAL_KEY_COMPONENTS_REQUIRED')
        keys.append(inputs.existing.source._key(row['original_record']));fps.extend(row['component_fingerprints'])
    require(len(set(keys))==len(keys) and set(keys)=={inputs.existing.source._key(k) for k in item['event_keys']}
        and len(set(fps))==len(fps) and set(fps)==set(item['event_fingerprints']), 'DYNAMIC_VENDOR_COMPONENT_MAP_OR_FINGERPRINT_CHANGED')
    return rows


def _entry_roles(expected, source_roles):
    entries = expected['supplements']
    if source_roles is None:
        return [dict(binder_kind='ORIGINAL_CAD_FOREIGN_NATIVE' if i in CAD_INDEX_COUNTS else 'ORIGINAL_USD_NATIVE_BINDER',
            event_count=CAD_INDEX_COUNTS.get(i,len(item['event_keys']))) for i,item in enumerate(entries,1)]
    require(isinstance(source_roles,list) and len(source_roles)==len(entries), 'DYNAMIC_SOURCE_ALL_OWNER_ROLES_REQUIRED')
    role_fields={'original_namespace','native_owner_ref','bundle_ref','binder_kind','event_count'}
    require(all(isinstance(r,dict) and set(r)==role_fields for r in source_roles), 'DYNAMIC_SOURCE_ROLE_OWNER_OR_BUNDLE_CHANGED')
    def identity(item):
        return (inputs.existing.digest(item['original_namespace']),
            inputs.existing.digest(canonical(item['native_owner_ref'])), inputs.existing.digest(canonical(item['bundle_ref'])))
    by_identity={identity(r):r for r in source_roles}
    require(len(by_identity)==len(entries), 'DYNAMIC_SOURCE_ROLE_OWNER_BUNDLE_DUPLICATE')
    owner_bundles=set()
    for namespace,owner,bundle in by_identity:
        require((owner,bundle) not in owner_bundles, 'DYNAMIC_SOURCE_ROLE_OWNER_BUNDLE_DUPLICATE')
        owner_bundles.add((owner,bundle))
    ordered=[]
    for item in entries:
        role=by_identity.get(identity(item))
        require(isinstance(role,dict) and set(role)=={'original_namespace','native_owner_ref','bundle_ref','binder_kind','event_count'}
            and role['binder_kind'] in BINDER_KINDS and role['event_count']==len(item['event_keys'])
            and canonical(role['native_owner_ref'])==canonical(item['native_owner_ref'])
            and canonical(role['bundle_ref'])==canonical(item['bundle_ref']), 'DYNAMIC_SOURCE_ROLE_OWNER_OR_BUNDLE_CHANGED')
        ordered.append(role)
    foreign=[r for r in ordered if r['binder_kind']=='ORIGINAL_CAD_FOREIGN_NATIVE']
    require(len(foreign)==2 and sorted(r['event_count'] for r in foreign)==[1,3], 'DYNAMIC_SOURCE_ORIGINAL_FOUR_CAD_REQUIRED')
    require(all('2023-01-01'<=str(k['effective_date'])<'2026-01-01' for item in entries for k in item['event_keys']),
        'DYNAMIC_SOURCE_PRE2026_EFFECTIVE_BOUNDARY_REQUIRED')
    return ordered


def template(original_route, *, expected_freeze_ref, source_joint_ref, qualified_source_scope_ref,
             reader_scope_ref, fx_qualification_ref, source_roles=None, execution_contract_ref=None, source_partition_ref=None, source_identity_projection_ref=None):
    require(original_route['status'] == routing.ENGINEERING, 'PRIVATE_CONSUMER_ORIGINAL_ENGINEERING_METADATA_REQUIRED')
    route = dict(schema=SCHEMA, status=ENGINEERING, task_id=routing.engine.TASK,
        original_routing_metadata=copy.deepcopy(original_route),
        expected_freeze_ref=canonical(expected_freeze_ref), source_joint_ref=canonical(source_joint_ref),
        qualified_source_scope_ref=canonical(qualified_source_scope_ref), reader_scope_ref=canonical(reader_scope_ref),
        fx_qualification_ref=canonical(fx_qualification_ref), current_source_count=61, current_owner_count=20,
        source_gaps_remaining=133, global_latest_FX='UNKNOWN', real_account_execution_authorized=False,
        test2026_read_authorized=False, account_or_PTO_qualified=False,
        reader_owner_ref=routing.file_ref(inputs.__file__), consumer_owner_ref=routing.file_ref(__file__))
    if source_roles is not None:
        expected=expected_projection(expected_freeze_ref,source_roles=source_roles); counts=validate_entries(expected,source_roles=source_roles)
        route.update(schema=CONTINUATION_SCHEMA,source_roles=copy.deepcopy(source_roles),current_source_count=counts['current_count'],
            current_owner_count=counts['owner_count'],source_gaps_remaining=194-counts['current_count'],
            execution_contract_ref=None if execution_contract_ref is None else canonical(execution_contract_ref))
    if source_partition_ref is not None:
        require(source_roles is not None,'PARTITION_DYNAMIC_SOURCE_ROLES_REQUIRED')
        route.update(source_partition_ref=canonical(source_partition_ref),source_review_gaps=0)
    if source_identity_projection_ref is not None:
        require(source_partition_ref is not None,'IDENTITY_PROJECTION_REVIEWED_PARTITION_REQUIRED')
        route.update(source_identity_projection_ref=canonical(source_identity_projection_ref),source_only_identity_projection_authorized=True)
    route['joint_execution_binding']=copy.deepcopy(JOINT_EXECUTION_BINDING)
    return route


def reader_scope_template(data_scope, *, data_origin_ref, output_run, dynamic=False, execute=False):
    """Preserve the original reader fields, while naming this distinct producer."""
    value = copy.deepcopy(data_scope)
    value.update(schema=READER_SCHEMA, original_data_scope_schema=data_scope['schema'],
        data_origin_scope_ref=canonical(data_origin_ref), consumer_output_run=str(Path(output_run).resolve()),
        consumer_producer_ref=routing.file_ref(__file__), data_reader_owner_ref=routing.file_ref(inputs.__file__),
        consumer_execution_authorized=False)
    if dynamic:
        value.update(schema=CONTINUATION_READER_SCHEMA,consumer_execution_authorized=bool(execute))
    return value


def _fx_metadata(route):
    value = _metadata(route['fx_qualification_ref'], ('schema','task_id','status','original_fx_convention_ref',
        'original_availability_ref','old258_book_ref','early14_book_ref','early14_qualification_ref',
        'old_count','early_count','combined_count','payload_qualification_ref',
        'available_at_convention','actual_timestamp_authority','same_release_date_market_close_mark_allowed',
        'global_latest','source_only_not_account_coverage','merged272_payload_ref','canonical_payload_proof_sha256','revision_vintage','FX_account_coverage_qualified'))
    dynamic=route.get('schema')==CONTINUATION_SCHEMA
    require(value.get('schema') == (CONTINUATION_FX_SCHEMA if dynamic else FX_SCHEMA) and value.get('task_id') == routing.engine.TASK
        and value.get('status') == 'QUALIFIED_KNOWN_PUBLISHED_BOOKS_ONLY', 'PRIVATE61_EXPLICIT272_FX_METADATA_REQUIRED')
    require(value.get('original_fx_convention_ref') == inputs.account.FX_CONVENTION_REF
        and value.get('original_availability_ref') == inputs.account.FX_AVAILABILITY_REF
        and value.get('old258_book_ref') == cad.OLD_FX_REF and value.get('early14_book_ref') == cad.EARLY_FX_REF
        and value.get('early14_qualification_ref') == cad.EARLY_FX_QUAL_REF, 'PRIVATE61_ORIGINAL258_EARLY14_FX_REFS_REQUIRED')
    require((value.get('old_count'),value.get('early_count'),value.get('combined_count')) == (258,14,272)
        and value.get('available_at_convention') == 'END_OF_CERTIFIED_RELEASE_DATE_AMERICA_NEW_YORK_23_59_59_CONVERTED_TO_UTC'
        and value.get('actual_timestamp_authority') == 'UNKNOWN_RETAINED'
        and value.get('same_release_date_market_close_mark_allowed') is False
        and value.get('global_latest') == 'UNKNOWN' and value.get('source_only_not_account_coverage') is True,
        'PRIVATE61_FX_COUNT_OR_CONSERVATIVE_AVAILABILITY_CHANGED')
    require(value.get('revision_vintage') == 'UNKNOWN' and value.get('FX_account_coverage_qualified') is False, 'PRIVATE61_FX_SOURCE_NOT_ACCOUNT_COVERAGE_REQUIRED')
    payload = _metadata(value['merged272_payload_ref'], ('proof_sha256','actual_joint61_receipt_ref','FX_mark_count','old_count','early_count'))
    require(payload.get('proof_sha256') == value.get('canonical_payload_proof_sha256') and isinstance(payload.get('proof_sha256'),str) and len(payload['proof_sha256']) == 64 and payload.get('actual_joint61_receipt_ref') == (value.get('payload_qualification_ref') if dynamic else route['source_joint_ref']) and (payload.get('old_count'),payload.get('early_count'),payload.get('FX_mark_count')) == (258,14,272), 'PRIVATE61_ACTUAL272_PAYLOAD_REF_AND_DIGEST_REQUIRED')
    qualification = _metadata(value['payload_qualification_ref'], ('status','FX_mark_count','source_conflicts_resolved_by_choice'))
    require(qualification.get('status') == 'PASS_ORIGINAL_ACCOUNT_SOURCE_OWNER_PREFLIGHT'
        and qualification.get('FX_mark_count') == 272 and qualification.get('source_conflicts_resolved_by_choice') is False,
        'PRIVATE61_NEW272_PAYLOAD_QUALIFICATION_REQUIRED')
    return value


def validate(route, *, execute=False):
    protected_pins()
    require(route.get('joint_execution_binding')==JOINT_EXECUTION_BINDING,'EXACT_JOINT_EXECUTION_BINDING_REQUIRED')
    dynamic=route.get('schema')==CONTINUATION_SCHEMA
    require(route.get('schema') in (SCHEMA,CONTINUATION_SCHEMA) and route.get('status') in ((ENGINEERING,AUTHORIZED) if dynamic else (ENGINEERING,))
        and route.get('task_id') == routing.engine.TASK, 'PRIVATE_CONSUMER_DISTINCT_ENGINEERING_SCHEMA_REQUIRED')
    run = routing.validate(route['original_routing_metadata'])
    if not dynamic:
        require(route.get('current_source_count') == 61 and route.get('current_owner_count') == 20, 'PRIVATE61_CURRENT_COUNT_NOT_INHERITED49_REQUIRED')
    require(route.get('reader_owner_ref') == routing.file_ref(inputs.__file__)
        and route.get('consumer_owner_ref') == routing.file_ref(__file__), 'PRIVATE_CONSUMER_READER_AND_PRODUCER_IDENTITY_REQUIRED')
    roles=route.get('source_roles') if dynamic else None
    expected = expected_projection(route['expected_freeze_ref'],source_roles=roles)
    counts=validate_entries(expected,source_roles=roles)
    if dynamic:
        require(0<counts['current_count']<=194 and route.get('source_gaps_remaining')==194-counts['current_count'], 'DYNAMIC_ORIGINAL194_GAP_COUNT_REQUIRED')
    require(route['current_source_count']==counts['current_count'] and route['current_owner_count']==counts['owner_count'], 'DYNAMIC_SOURCE_ACTUAL_COUNTS_REQUIRED')
    joint = _metadata(route['source_joint_ref'], ('status','all_source_qualified','base_native_count','supplement_count',
        'FX_mark_count','original_namespaces_preserved','source_conflicts_resolved_by_choice','source_scope_ref'))
    joint['event_fingerprints']=_array_projection(route['source_joint_ref'],('event_fingerprints',))
    joint['removed_exact_original_keys']=_array_projection(route['source_joint_ref'],('removed_exact_original_keys',))
    require(joint.get('status') == 'PASS_ORIGINAL_ACCOUNT_SOURCE_OWNER_PREFLIGHT' and joint.get('all_source_qualified') is True
        and joint.get('base_native_count') == 105 and joint.get('supplement_count') == counts['current_count']
        and joint.get('FX_mark_count') == 272 and joint.get('original_namespaces_preserved') is True
        and joint.get('source_conflicts_resolved_by_choice') is False, 'PRIVATE61_ACTUAL_JOINT_SOURCE_QUALIFICATION_REQUIRED')
    require(set(joint['event_fingerprints']) == {fp for e in expected['supplements'] for fp in e['event_fingerprints']}
        and {inputs.existing.source._key(k) for k in joint['removed_exact_original_keys']} ==
            {inputs.existing.source._key(k) for e in expected['supplements'] for k in e['event_keys']}, 'PRIVATE61_ACTUAL5FIELD_SET_CHANGED')
    _qualified_origin(route, expected, joint)
    if route.get('source_partition_ref') is not None: _partition_metadata(route,expected)
    if route.get('source_code_transport_ref') is not None: _risk_code_transport(route['source_code_transport_ref'])
    reader = _metadata(route['reader_scope_ref'], ('schema','task_id','data_origin_scope_ref','consumer_output_run',
        'consumer_producer_ref','data_reader_owner_ref','consumer_execution_authorized'))
    require(reader.get('schema') == (CONTINUATION_READER_SCHEMA if dynamic else READER_SCHEMA) and reader.get('task_id') == routing.engine.TASK
        and reader.get('data_origin_scope_ref') == route['qualified_source_scope_ref']
        and reader.get('consumer_output_run') == str(run) and reader.get('consumer_producer_ref') == route['consumer_owner_ref']
        and reader.get('data_reader_owner_ref') == route['reader_owner_ref'] and reader.get('consumer_execution_authorized') is (route.get('status')==AUTHORIZED if dynamic else False),
        'PRIVATE_CONSUMER_DATA_ORIGIN_AND_OUTPUT_MUST_BE_DISTINCT')
    _fx_metadata(route)
    require(route.get('test2026_read_authorized') is False and route.get('account_or_PTO_qualified') is False,
        'PRIVATE_CONSUMER_ENGINEERING_IS_NOT_ACCOUNT_AUTHORITY')
    if execute:
        require(route.get('real_account_execution_authorized') is True, 'PRIVATE_CONSUMER_ACCOUNT_EXECUTION_NOT_AUTHORIZED')
        require(route.get('source_gaps_remaining') == 0 or dynamic and route.get('source_partition_ref') is not None, 'PRIVATE_CONSUMER_SOURCE_GAPS_BLOCK_ACCOUNT')
        if not dynamic: raise ValueError('PRIVATE_CONSUMER_NEW_ACCOUNT_AUTHORIZATION_CONTRACT_REQUIRED')
        _execution_contract(route,run)
    return run, expected



def _fit_log_prefix(proof):
    """Read only a pinned raw JSONL prefix; never decode market/result payloads."""
    path=Path(proof['path']);size=proof['bytes']
    require(isinstance(size,int) and 0<size<=4*1024*1024 and path.stat().st_size>=size,
        'CARRYOVER_BOUNDED_RAW_FIT_PREFIX_REQUIRED')
    with path.open('rb') as stream:raw=stream.read(size)
    require(len(raw)==size and raw.endswith(b'\n') and hashlib.sha256(raw).hexdigest()==proof['sha256'],
        'CARRYOVER_RAW_FIT_PREFIX_CHANGED')
    rows=[json.loads(line) for line in raw.splitlines() if line]
    started=[row for row in rows if row.get('event')=='FIT_STARTED']
    require(len(started)==proof['fit_started_count'] and all(row.get('fit_units')==1 for row in started)
        and sum(row['fit_units'] for row in started)==proof['fit_units'], 'CARRYOVER_RAW_FIT_COUNT_CHANGED')
    return started


def _method_matrix_metadata(route, run, *, require_review=False):
    """New comparison scope; old fixed-recipe authorities remain unchanged."""
    reference=route.get('method_matrix_scope_ref')
    if reference is None:
        require(route.get('method_matrix_admission_ref') is None,'MATRIX_REVIEW_WITHOUT_SCOPE');return None
    value=_metadata(reference,('schema','status','task_id','research_id','output_run','selection_boundary_exclusive','initial_cash','prior_fit_units','max_fit_units','test2026_read_authorized','real_trades_authorized','old_account_state_reused','source_policy','matrix_coordinates_ref','extension_source_ref'))
    require(value.get('schema')=='CONSENSUS_METHOD_MATRIX_EXTENSION_R1' and value.get('status')=='AUTHORIZED_PRE2026_COMPARISON' and value.get('task_id')==routing.engine.TASK and value.get('research_id')=='CONSENSUS100_PTO_3000_PRE2026_FULL_METHOD_COMPLETION_R12' and value.get('output_run')==str(run),'EXPLICIT_NEW_MATRIX_AUTHORITY_REQUIRED')
    require((value.get('selection_boundary_exclusive'),value.get('initial_cash'),value.get('prior_fit_units'),value.get('max_fit_units'))==('2026-01-01',3000,2063,10000) and value.get('source_policy')=='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY' and all(value.get(k) is False for k in ('test2026_read_authorized','real_trades_authorized','old_account_state_reused')),'MATRIX_CLOCK_ACCOUNT_AND_LIFETIME_BUDGET_CHANGED')
    for key in ('matrix_coordinates_ref','extension_source_ref'):routing._pin(canonical(value[key]))
    if require_review:
        review_ref=route.get('method_matrix_admission_ref');require(review_ref is not None,'MATRIX_INDEPENDENT_ADMISSION_REQUIRED')
        review=_metadata(review_ref,('status','scope_ref','consumer_ref','metadata_code_only','economic_PASS'))
        require(str(review.get('status','')).startswith('PASS') and review.get('scope_ref')==reference and review.get('consumer_ref')==route['consumer_owner_ref'] and review.get('metadata_code_only') is True and review.get('economic_PASS') is False,'MATRIX_EXACT_CODE_SCOPE_ADMISSION_REQUIRED')
    return value


def _risk_fit_carryover(route,run,*,_predecessor=False):
    ref=route.get('risk_fit_carryover_ref')
    if ref is None:return None
    names=('schema','status','task_id','output_run','original_run','original_freeze_ref',
        'risk_state_receipt_ref','risk_state_ref','risk_fit_log_ref','original_fit_log_ref',
        'baseline_fit_log_proofs','prior_fit_units','carried_fit_units','effective_prior_fit_units',
        'max_fit_units','risk_cache_entry_count','log_started_tuple_count','risk_state_source_modules',
        'predecessor_carryover_ref','current_run_fit_units','method_matrix_scope_ref')
    value=_metadata(ref,names)
    matrix_chain=value.get('schema')=='CONSENSUS_PRE2026_RISK_FIT_CARRYOVER_R3'
    chained=value.get('schema') in ('CONSENSUS_PRE2026_RISK_FIT_CARRYOVER_R2','CONSENSUS_PRE2026_RISK_FIT_CARRYOVER_R3')
    require(value.get('schema') in ('CONSENSUS_PRE2026_RISK_FIT_CARRYOVER_R1','CONSENSUS_PRE2026_RISK_FIT_CARRYOVER_R2','CONSENSUS_PRE2026_RISK_FIT_CARRYOVER_R3')
        and not (chained and _predecessor)
        and value.get('status')=='PINNED_CHECKPOINT_CARRYOVER' and value.get('task_id')==routing.engine.TASK
        and value.get('output_run')==str(run), 'CARRYOVER_TASK_AND_OUTPUT_IDENTITY_REQUIRED')
    original=routing._output(value['original_run'])
    require(original!=run and not original.is_relative_to(run) and not run.is_relative_to(original),
        'CARRYOVER_DISTINCT_PRESERVED_ORIGINAL_RUN_REQUIRED')
    old_ref=canonical(value['original_freeze_ref'])
    require(Path(old_ref['path']).resolve()==original/_freeze_name(route), 'CARRYOVER_ORIGINAL_FREEZE_PATH_CHANGED')
    old=_metadata(old_ref,('schema','status','task_id','test2026_read_authorized','original_routing_metadata',
        'execution_contract_ref','source_roles','source_partition_ref','source_identity_projection_ref','source_code_transport_ref',
        'risk_fit_carryover_ref','effective_prior_fit_units','partition_scope_ref'))
    require(old.get('schema')==CONTINUATION_SCHEMA and old.get('status')==AUTHORIZED
        and old.get('task_id')==routing.engine.TASK and old.get('test2026_read_authorized') is False,
        'CARRYOVER_ORIGINAL_PRE2026_AUTHORITY_REQUIRED')
    predecessor=None
    if chained:
        if matrix_chain:
            matrix=_method_matrix_metadata(route,run)
            require(matrix is not None and value.get('method_matrix_scope_ref')==route['method_matrix_scope_ref'] and route.get('no_new_risk_fit') is False and route.get('account_repair_ref') is None,'CARRYOVER_MATRIX_SCOPE_NOT_EQUAL_REPAIR_REQUIRED')
        else:
            require(value.get('method_matrix_scope_ref') is None and route.get('no_new_risk_fit') is True and route.get('account_repair_ref') is not None,'CARRYOVER_EXACT_R8_R9_PREDECESSOR_AND_NO_NEW_FIT_REQUIRED')
        require(value.get('predecessor_carryover_ref')==old.get('risk_fit_carryover_ref'),'CARRYOVER_EXACT_R8_R9_PREDECESSOR_REQUIRED')
        predecessor=_risk_fit_carryover(old,original,_predecessor=True)
        require(predecessor is not None and predecessor['schema']=='CONSENSUS_PRE2026_RISK_FIT_CARRYOVER_R1'
            and value['baseline_fit_log_proofs']==predecessor['baseline_fit_log_proofs'],
            'CARRYOVER_ONLY_ONE_ORIGINAL_PREDECESSOR_REQUIRED')
    else:
        require(value.get('predecessor_carryover_ref') is None and value.get('current_run_fit_units') is None,
            'CARRYOVER_R1_CANNOT_HIDE_ADDITIONAL_PREFIX')
    before=old['original_routing_metadata'];after=route['original_routing_metadata']
    require(before.get('output_run')==str(original) and all(before.get(k)==after[k]
        for k in ('feature_origin','frozen_origin','frozen_refs','source_pins','budget','recipe','source_policy','test_2026_read_authorized'))
        and all(old.get(k)==route.get(k) for k in ('source_roles','source_identity_projection_ref','source_code_transport_ref')),
        'CARRYOVER_FROZEN_MODELS_SOURCE_RECIPE_OR_CLOCK_CHANGED')
    if old.get('source_partition_ref') is not None:
        fields=('retained_unsupported_keys','sourcefact_refs','native_count','original_key_count','native_gap_count','source_review_gaps','economic_PASS','test2026_read_authorized')
        require(route.get('source_partition_ref') is not None and _metadata(old['source_partition_ref'],fields)==_metadata(route['source_partition_ref'],fields),
            'CARRYOVER_RETAINED_SOURCE_PARTITION_CHANGED')
    authority=_metadata(old['execution_contract_ref'],('human_authorization_ref','authorized_spec_ref','protected_owner_refs','budget','scope_start','scope_end_exclusive','test2026_read_authorized','real_trades_authorized','old_account_state_reused'))
    require(authority.get('human_authorization_ref')==HUMAN_AUTHORIZATION_REF
        and authority.get('authorized_spec_ref')==AUTHORIZED_SPEC_REF and authority.get('protected_owner_refs')==protected_pins()
        and authority.get('budget')==dict(prior_fit_units=1291,max_fit_units=10000)
        and authority.get('scope_start')=='2023-01-01' and authority.get('scope_end_exclusive')=='2026-01-01'
        and all(authority.get(k) is False for k in ('test2026_read_authorized','real_trades_authorized','old_account_state_reused')),
        'CARRYOVER_ORIGINAL_HUMAN_SCOPE_CHANGED')
    require(len(value['baseline_fit_log_proofs'])==2
        and {Path(proof['path']).resolve() for proof in value['baseline_fit_log_proofs']}=={(routing.FEATURE_ORIGIN/'FIT_LOG.jsonl').resolve(),(routing.FROZEN_ORIGIN/'FIT_LOG.jsonl').resolve()}
        and sum(len(_fit_log_prefix(proof)) for proof in value['baseline_fit_log_proofs'])==1291,
        'CARRYOVER_ORIGINAL_NATIVE1291_RAW_PROOF_REQUIRED')
    log_path=routing._pin(canonical(value['original_fit_log_ref']))
    require(log_path.resolve()==original/'FIT_LOG.jsonl','CARRYOVER_ORIGINAL_FIT_LOG_PATH_CHANGED')
    prefix_path=routing._pin(canonical(value['risk_fit_log_ref']))
    proof=dict(value['risk_fit_log_ref'],bytes=prefix_path.stat().st_size,
        fit_started_count=value['current_run_fit_units'] if chained else value['carried_fit_units'],
        fit_units=value['current_run_fit_units'] if chained else value['carried_fit_units'])
    started=_fit_log_prefix(proof)
    require(routing.file_ref(prefix_path)['sha256']==routing.file_ref(log_path)['sha256']
        and all(row.get('budget_bucket')=='consensus_account_primary_risk'
            and row.get('component') in ('RISK_INPUT_PREPROCESSING_ATTEMPT','RISK_ESTIMATOR_STATE_ATTEMPT')
            and row.get('model_id') in routing.engine.joint.PRIMARY_RISKS for row in started),
        'CARRYOVER_EXACT_STOPPED_RISK_LOG_REQUIRED')
    tokens={row['reuse_tuple_sha256'] for row in started}
    require(all(isinstance(token,str) and len(token)==64
        and sorted(row['component'] for row in started if row['reuse_tuple_sha256']==token)==['RISK_ESTIMATOR_STATE_ATTEMPT','RISK_INPUT_PREPROCESSING_ATTEMPT'] for token in tokens),
        'CARRYOVER_ORIGINAL_RISK_COMPONENT_PAIRS_REQUIRED')
    if predecessor is not None:
        require(not tokens & predecessor['started_tokens'],'CARRYOVER_PREFIXES_CANNOT_REPEAT_FIT_TUPLE')
        started=predecessor['started']+started;tokens=predecessor['started_tokens']|tokens
    require(value.get('carried_fit_units')==len(started),'CARRYOVER_CHAIN_TOTAL_UNITS_CHANGED')
    require(value.get('prior_fit_units')==1291 and value.get('max_fit_units')==10000
        and value.get('effective_prior_fit_units')==1291+len(started)<10000
        and value.get('log_started_tuple_count')==len(tokens)
        and route.get('effective_prior_fit_units')==value['effective_prior_fit_units'],
        'CARRYOVER_CUMULATIVE_FIT_BUDGET_CHANGED')
    if matrix_chain:
        require(matrix['prior_fit_units']==value['effective_prior_fit_units'],
            'MATRIX_PRIOR_MUST_EQUAL_PROVEN_CUMULATIVE_FIT_UNITS')
    receipt_ref=canonical(value['risk_state_receipt_ref']);receipt_path=routing._pin(receipt_ref)
    require(receipt_path.resolve().is_relative_to(original/'evaluation'/'consensus_account')
        and receipt_path.name=='receipt.json','CARRYOVER_ORIGINAL_ACCOUNT_RECEIPT_PATH_REQUIRED')
    receipt=_metadata(receipt_ref,('status','task_id','freeze_ref','artifacts'))
    state_ref=canonical(value['risk_state_ref'])
    require(receipt.get('status') in ('COMPLETE','NOT_TESTABLE') and receipt.get('task_id')==routing.engine.TASK
        and receipt.get('freeze_ref')==old_ref and receipt.get('artifacts',{}).get('state')==state_ref
        and Path(state_ref['path']).resolve()==receipt_path.parent/'state.joblib',
        'CARRYOVER_HASHED_TERMINAL_PRE2026_RISK_STATE_REQUIRED')
    routing._pin(state_ref)
    require(isinstance(value.get('risk_state_source_modules'),list),'CARRYOVER_EXPLICIT_STATE_SOURCE_MODULES_REQUIRED')
    roles={(tuple(canonical(role['native_owner_ref']).values()),tuple(canonical(role['bundle_ref']).values())) for role in route['source_roles']}
    for module in value['risk_state_source_modules']:
        owner=canonical(module['owner_ref']);bundle=canonical(module['bundle_ref'])
        expected='_consensus_dynamic_source_'+inputs.existing.digest(dict(owner=owner,bundle=bundle))[:24]
        require(module['name']==expected and (tuple(owner.values()),tuple(bundle.values())) in roles,'CARRYOVER_STATE_MODULE_SOURCE_MEMBERSHIP_CHANGED')
        routing._pin(owner);routing._pin(bundle)
    return dict(value,started=started,started_tokens=tokens)


def _carryover_risk_cache(value):
    """Same joblib owner as E: full pinned pre2026 state is loaded, only risk is used."""
    for expected in value['risk_state_source_modules']:
        module=sys.modules.get(expected['name']);spec=getattr(module,'__spec__',None)
        require(module is not None and spec is not None and spec.name==expected['name']
            and Path(spec.origin).resolve()==Path(expected['owner_ref']['path']).resolve()
            and Path(module.__file__).resolve()==Path(expected['owner_ref']['path']).resolve()
            and routing.file_ref(module.__file__)==canonical(expected['owner_ref']),
            'CARRYOVER_EXACT_REGISTERED_SOURCE_MODULE_REQUIRED')
    state=routing.engine.joblib.load(routing._pin(canonical(value['risk_state_ref'])))
    cache=state['risk_cache'];require(isinstance(cache,dict) and len(cache)==value['risk_cache_entry_count'],
        'CARRYOVER_RISK_CACHE_COUNT_CHANGED')
    represented=set();pd=routing.engine.pd;joint=routing.engine.joint
    for key,bundle in cache.items():
        require(isinstance(key,tuple) and len(key)==4 and isinstance(bundle,joint.risk.RiskBundle)
            and key[1]==bundle.method_id and key[1] in joint.PRIMARY_RISKS and key[2] in (60,120),
            'CARRYOVER_EXACT_ORIGINAL_RISK_CACHE_TYPE_REQUIRED')
        cutoff=pd.Timestamp(bundle.specification['fit_cutoff'])
        require(pd.Timestamp('2023-01-01')<=cutoff<=routing.engine.BOUNDARY
            and pd.Timestamp(key[0])==cutoff.to_period('M').start_time
            and tuple(sorted(set(bundle.assets)))==tuple(bundle.assets)
            and all(pd.Timestamp(day)<cutoff for day in bundle.fitted_dates)
            and bundle.status in ('FITTED','BLOCKED_INPUT','FIT_FAILED','BLOCKED_DEPENDENCY')
            and 0<=bundle.budget['total_state_estimations']<=2,
            'CARRYOVER_RISK_CLOCK_STATUS_OR_BUDGET_CHANGED')
        event=dict(method=bundle.method_id,cutoff=cutoff.isoformat(),month=pd.Timestamp(key[0]).isoformat(),
            assets=list(bundle.assets),input_sha256=key[3])
        token=routing.engine.values.digest(dict(source_pins=routing.engine.source_pins(),event=event))
        require(token in value['started_tokens'] and token not in represented,
            'CARRYOVER_RISK_CACHE_TUPLE_NOT_IN_ORIGINAL_FIT_LOG')
        represented.add(token)
    # Missing checkpoint tuples remain banned by make_policy's original start guard.
    return cache



def _equal_repair_metadata(route,run,carryover):
    """One named failed equal slot; only its pinned pre2026 receipt metadata."""
    ref=route.get('account_repair_ref');no_fit=route.get('no_new_risk_fit')
    if route.get('method_matrix_scope_ref') is not None:
        _method_matrix_metadata(route,run)
        require(ref is None and no_fit is False and route.get('original_final_risk_receipt_ref') is None
            and carryover is not None and carryover['schema']=='CONSENSUS_PRE2026_RISK_FIT_CARRYOVER_R3',
            'MATRIX_IS_NEW_FIT_COMPARISON_NOT_EQUAL_NO_FIT_REPAIR')
        return None
    if ref is None and no_fit is None:
        require(route.get('original_final_risk_receipt_ref') is None,'ORIGINAL_FINAL_REUSE_NEEDS_NAMED_REPAIR')
        return None
    require(no_fit is True and ref is not None and carryover is not None
        and carryover['schema']=='CONSENSUS_PRE2026_RISK_FIT_CARRYOVER_R2',
        'NO_NEW_FIT_REPAIR_NEEDS_TWO_PREFIX_CARRYOVER')
    scope=_metadata(ref,('schema','status','task_id','output_run','original_run','original_freeze_ref',
        'original_failed_receipt_ref','stage2_receipt_refs','fusion_method','risk_method','allocation_method',
        'diagnostic','initial_cash_usd','initial_holdings','no_new_risk_fit','test2026_read_authorized',
        'real_trades_authorized','old_account_state_reused','prior_fit_units','effective_prior_fit_units',
        'max_fit_units','scope_start','scope_end_exclusive','protected_owner_refs','actual_compiler_ref',
        'old_failed_fit_tuples_no_retry','old_receipts_preserved','original_execution_invariant_diagnostic_only',
        'execution_invariant_original_error','allowed_failure_scalar_fields',
        'invariant_diagnostic_replay_only_semantics_unchanged','original_retained_assertion_predicate_unchanged',
        'source_backed_stock_delivery_and_mechanical_exit_timing_unchanged'))
    require(scope.get('schema')=='CONSENSUS_EQUAL_EMPTY_SUPPORT_NO_NEW_FIT_REPAIR_R1'
        and scope.get('status')=='FROZEN_NO_NEW_FIT_EQUAL_REPAIR' and scope.get('task_id')==routing.engine.TASK
        and scope.get('output_run')==str(run) and scope.get('original_run')==carryover['original_run']
        and scope.get('original_freeze_ref')==carryover['original_freeze_ref']
        and tuple(scope.get(k) for k in ('fusion_method','risk_method','allocation_method'))==('nnls_zero_abstain','LW','equal_weight')
        and scope.get('diagnostic') is None and scope.get('initial_cash_usd')==3000 and scope.get('initial_holdings')==[]
        and scope.get('no_new_risk_fit') is True and scope.get('old_failed_fit_tuples_no_retry') is True
        and scope.get('old_receipts_preserved') is True
        and all(scope.get(k) is False for k in ('test2026_read_authorized','real_trades_authorized','old_account_state_reused'))
        and scope.get('scope_start')=='2023-01-01' and scope.get('scope_end_exclusive')=='2026-01-01'
        and scope.get('prior_fit_units')==1291 and scope.get('max_fit_units')==10000
        and scope.get('effective_prior_fit_units')==carryover['effective_prior_fit_units']
        and scope.get('protected_owner_refs')==protected_pins()
        and scope.get('actual_compiler_ref')==JOINT_EXECUTION_BINDING['actual_allocator_compiler_ref'],
        'EXACT_NO_NEW_FIT_EQUAL_REPAIR_SCOPE_REQUIRED')
    diagnostic=route.get('execution_invariant_scalar_diagnostic_authorized')
    require(diagnostic==scope.get('original_execution_invariant_diagnostic_only'),'ACCOUNT_INVARIANT_DIAGNOSTIC_SCOPE_CHANGED')
    if diagnostic is not None:
        require(diagnostic is True and scope.get('execution_invariant_original_error')=='common cash/actual name invariant'
            and scope.get('allowed_failure_scalar_fields')==list(INVARIANT_SCALAR_FIELDS)
            and all(scope.get(k) is True for k in ('invariant_diagnostic_replay_only_semantics_unchanged',
                'original_retained_assertion_predicate_unchanged','source_backed_stock_delivery_and_mechanical_exit_timing_unchanged')),
            'EXACT_SIX_SCALAR_ORIGINAL_GATE_DIAGNOSTIC_ONLY_REQUIRED')
    refs=scope['stage2_receipt_refs'];recipe=route['original_routing_metadata']['recipe']
    require(len(refs)==len(recipe['stage2'])==17,'REPAIR_ORIGINAL_SEVENTEEN_STAGE2_SLOTS_REQUIRED')
    original=Path(scope['original_run']).resolve();receipts=[];equal=None
    for pin,path in zip(refs,recipe['stage2']):
        fid=routing.engine.flow_id(scope['fusion_method'],path['risk_method'],path['allocation_method'],run=routing.FROZEN_ORIGIN)
        require(Path(pin['path']).resolve()==original/'evaluation/consensus_account'/fid/'receipt.json',
            'REPAIR_ORIGINAL_STAGE2_ORDER_OR_PATH_CHANGED')
        value=_metadata(pin,('status','task_id','flow_id','fusion_method','risk_method','allocation_method',
            'diagnostic_only','freeze_ref','fee_config','lookback_sessions','statistics','failure','fit_units'))
        require(value.get('task_id')==routing.engine.TASK and value.get('flow_id')==fid
            and value.get('freeze_ref')==scope['original_freeze_ref']
            and tuple(value.get(k) for k in ('fusion_method','risk_method','allocation_method'))==
                (scope['fusion_method'],path['risk_method'],path['allocation_method'])
            and value.get('diagnostic_only') is False and value.get('lookback_sessions')==120
            and value.get('fee_config')==recipe['fee_config']
            and value.get('status') in ('COMPLETE','NOT_TESTABLE','FAILED_NO_RETRY'),
            'REPAIR_ORIGINAL_FROZEN_STAGE2_METADATA_CHANGED')
        value['receipt_path']=str(Path(pin['path']));receipts.append(value)
        if (path['risk_method'],path['allocation_method'])==('LW','equal_weight'):
            equal=pin
            require(value['status']=='FAILED_NO_RETRY'
                and value.get('failure')==dict(type='ZeroDivisionError',reason='float division by zero'),
                'REPAIR_ONLY_ORIGINAL_EMPTY_SUPPORT_ENGINEERING_FAILURE')
    require(equal==scope['original_failed_receipt_ref'],'REPAIR_FAILED_RECEIPT_PIN_CHANGED')
    return dict(scope,original_stage2_receipts=receipts)


def _original_final_risk_metadata(route,selected,scope):
    """Raw pins and pre2026 final receipt metadata only; no old joblib decoding."""
    ref=route.get('original_final_risk_receipt_ref')
    require(ref is not None,'REPAIR_ORIGINAL_WINNER_FINAL_RECEIPT_REQUIRED')
    root=Path(scope['original_run']).resolve()/'models/consensus_final_policy'/selected['flow_id']
    require(Path(ref['path']).resolve()==root/'receipt.json','REPAIR_FINAL_RECEIPT_SELECTED_ORIGIN_CHANGED')
    value=_metadata(ref,('status','task_id','selected_flow','freeze_ref','final_risk_fit_cutoff',
        'test_rows_read','artifacts','actual_final_risk_budget'))
    require(value.get('status')=='COMPLETE' and value.get('task_id')==routing.engine.TASK
        and value.get('selected_flow')==selected['flow_id'] and value.get('freeze_ref')==scope['original_freeze_ref']
        and value.get('final_risk_fit_cutoff')=='2026-01-01 exclusive' and value.get('test_rows_read')==0
        and isinstance(value.get('artifacts'),dict) and value['artifacts'].get('state') is not None,
        'REPAIR_ORIGINAL_FINAL_PRE2026_COMPLETE_REQUIRED')
    for pin in value['artifacts'].values():
        require(Path(pin['path']).resolve().is_relative_to(root),'REPAIR_ORIGINAL_FINAL_ARTIFACT_PATH_CHANGED')
        routing._pin(canonical(pin))
    return dict(value,receipt_path=str(Path(ref['path'])),reuse_scope='PINNED_ORIGINAL_FINAL_METADATA_AND_RAW_HASHES_ONLY_NO_OLD_ACCOUNT_LOAD')


def run_equal_weight_repair(runner,route,run):
    """Reuse E's input, account, selector and final freeze owners for one slot."""
    run,f,freeze_ref=runner.contract(run)
    carryover=_risk_fit_carryover(route,run);scope=_equal_repair_metadata(route,run,carryover)
    require(scope is not None and not (run/'FIT_LOG.jsonl').exists(),'NO_NEW_FIT_REPAIR_FRESH_NO_FIT_LOG_REQUIRED')
    with runner.predictors.fit_lock(run):
        bound=runner.account_inputs.metadata_preflight(frozen_contract_ref=freeze_ref,source_scope_ref=f['account_source_scope_ref'])
        reader_root=runner._routing_feature_origin(run)
        reader=runner.ConsensusInputs(reader_root,reader_root/'derived/consensus100_daily.parquet')
        _,pf,_=runner.predictors.contract(reader_root,'ridge',2023,5);runner.predictors.reader_integrity(reader,pf)
        adv,returns,_=runner.qualified_vectors(reader,bound['scope'])
        loaded=runner.account_inputs.load_account_inputs(bound,signal_adv_by_key=adv)
        require(runner.pd.DatetimeIndex(loaded['market'].dates).min()>=runner.pd.Timestamp('2023-01-01')
            and runner.pd.DatetimeIndex(loaded['market'].dates).max()<runner.BOUNDARY,'ACCOUNT_PIPELINE_PRE2026_REQUIRED')
        method=scope['fusion_method'];forecasts,pins=runner.published_forecasts(run,method,reader);cache={}
        result=runner.evaluate_flow(run,method,'LW','equal_weight',forecasts,returns,loaded,freeze_ref,pins,cache)
        require(result.get('fit_units')==0 and not (run/'FIT_LOG.jsonl').exists(),'NO_NEW_FIT_REPAIR_FIT_OCCURRED')
        stage2=[result if (r['risk_method'],r['allocation_method'])==('LW','equal_weight') else r
            for r in scope['original_stage2_receipts']]
        selected=runner.select_best(stage2);final=None
        if result['status']=='COMPLETE':
            if selected['flow_id']==result['flow_id']:
                final=runner.freeze_selected_risk(run,result,forecasts,returns,loaded,freeze_ref,cache)
                require(final.get('fit_units')==0 and not (run/'FIT_LOG.jsonl').exists(),'NO_NEW_FIT_REPAIR_FINAL_FIT_OCCURRED')
            else:final=_original_final_risk_metadata(route,selected,scope)
        new_winner=result['status']=='COMPLETE' and selected['flow_id']==result['flow_id']
        final_complete=final is not None and final['status']=='COMPLETE'
        complete=result['status']=='COMPLETE' and final_complete and not new_winner
        status=('COMPLETE' if complete else 'CANDIDATE_UNTIL_REQUIRED_DIAGNOSTICS_NO_TEST_USE'
            if new_winner and final_complete else 'REPAIR_NOT_COMPLETE_NO_TEST_USE')
        invariant=None
        if route.get('execution_invariant_scalar_diagnostic_authorized') is True:
            failure=result.get('failure',{})
            if result['status']=='NOT_TESTABLE' and failure.get('type')=='NotTestable' and failure.get('reason','').startswith(INVARIANT_SCALAR_PREFIX):
                invariant=json.loads(failure['reason'][len(INVARIANT_SCALAR_PREFIX):])
                require(set(invariant)==set(INVARIANT_SCALAR_FIELDS),'ACCOUNT_INVARIANT_FAILURE_METADATA_CHANGED')
                status='DIAGNOSTIC_NOT_TESTABLE_ORIGINAL_GUARD_PRESERVED'
        summary=dict(status=status,task_id=runner.TASK,
            freeze_ref=freeze_ref,account_repair_ref=canonical(route['account_repair_ref']),
            original_failed_receipt_ref=scope['original_failed_receipt_ref'],repair_receipt=result,stage2=stage2,
            selected_fusion=method,selected_flow=selected['flow_id'],final_risk_receipt=final,
            original_final_risk_receipt_ref=route.get('original_final_risk_receipt_ref'),
            no_new_risk_fit=True,new_fit_units=0,effective_prior_fit_units=carryover['effective_prior_fit_units'],
            selection_rule='UNCHANGED_E_SELECT_BEST_ALL_ORIGINAL_SEVENTEEN_SLOTS_FAILED_EQUAL_REPLACED_ONLY',
            original_failed_receipt_preserved=True,old_account_state_reused=False,
            execution_invariant_scalar_metadata=invariant,original_execution_invariant_diagnostic_only=route.get('execution_invariant_scalar_diagnostic_authorized',False),
            new_winner_requires_original_four_diagnostic_sensitivities=new_winner,
            required_diagnostic_recipe=copy.deepcopy(f['recipe']['diagnostic_sensitivities']) if new_winner else [],
            sensitivity_selection_feedback=False,original_winner_diagnostic_evidence_reuse_requires_Root_original_completion_proof=not new_winner,
            strict_PIT_certified=False,conditional_research_only=True,test_2026_rows_read=0)
        runner.write_json_atomic(run/'evaluation/consensus_equal_empty_support_repair_summary.json',summary)
        return summary


def execution_contract_template(route, *, research_id, managed_run_config_ref, managed_input_manifest_ref):
    require(route.get('schema')==CONTINUATION_SCHEMA,'DYNAMIC_CONTINUATION_SCHEMA_REQUIRED')
    run=routing._output(route['original_routing_metadata']['output_run'])
    carryover=_risk_fit_carryover(route,run)
    _equal_repair_metadata(route,run,carryover)
    _method_matrix_metadata(route,run)
    return dict(joint_execution_binding=copy.deepcopy(JOINT_EXECUTION_BINDING),schema=EXECUTION_SCHEMA,status=AUTHORIZED,task_id=routing.engine.TASK,research_id=str(research_id),output_run=str(run),
        managed_run_config_ref=canonical(managed_run_config_ref),managed_input_manifest_ref=canonical(managed_input_manifest_ref),
        human_authorization_ref=copy.deepcopy(HUMAN_AUTHORIZATION_REF),authorized_spec_ref=copy.deepcopy(AUTHORIZED_SPEC_REF),
        original_gaps_ref=copy.deepcopy(ORIGINAL_GAPS_REF),frozen_refs=copy.deepcopy(route['original_routing_metadata']['frozen_refs']),
        budget=dict(prior_fit_units=1291,max_fit_units=10000),recipe=copy.deepcopy(route['original_routing_metadata']['recipe']),
        scope_start='2023-01-01',scope_end_exclusive='2026-01-01',test2026_read_authorized=False,real_trades_authorized=False,
        old_account_state_reused=False,old_risk_cache_reused=carryover is not None,account_state_root=str(run/'evaluation'/'consensus_account'),risk_cache_root=str(run/'models'/'consensus_final_policy'),
        consumer_owner_ref=copy.deepcopy(route['consumer_owner_ref']),protected_owner_refs=protected_pins(),
        **({k:copy.deepcopy(route[k]) for k in ('risk_fit_carryover_ref','effective_prior_fit_units','partition_scope_ref','no_new_risk_fit','account_repair_ref','original_final_risk_receipt_ref','execution_invariant_scalar_diagnostic_authorized') if k in route} if carryover is not None else {}),
        **{k:copy.deepcopy(route[k]) for k in ('expected_freeze_ref','source_joint_ref','qualified_source_scope_ref','reader_scope_ref','fx_qualification_ref','source_roles')},
        **({k:copy.deepcopy(route[k]) for k in ('source_partition_ref','source_review_gaps','source_gaps_remaining')} if route.get('source_partition_ref') is not None else {}),
        **({k:copy.deepcopy(route[k]) for k in ('method_matrix_scope_ref','method_matrix_admission_ref') if k in route}),
        **({'source_code_transport_ref':canonical(route['source_code_transport_ref'])} if route.get('source_code_transport_ref') is not None else {}),
        **({k:copy.deepcopy(route[k]) for k in ('source_identity_projection_ref','source_only_identity_projection_authorized')} if route.get('source_identity_projection_ref') is not None else {}))


def _execution_contract(route, run):
    ref=route.get('execution_contract_ref');require(ref is not None,'DYNAMIC_FORMAL_EXECUTION_CONTRACT_REQUIRED')
    value=_metadata(ref,('schema','status','task_id','research_id','output_run','managed_run_config_ref','managed_input_manifest_ref',
        'human_authorization_ref','authorized_spec_ref','frozen_refs','budget','recipe','scope_start','scope_end_exclusive',
        'test2026_read_authorized','real_trades_authorized','old_account_state_reused','old_risk_cache_reused',
        'account_state_root','risk_cache_root','consumer_owner_ref','protected_owner_refs','expected_freeze_ref',
        'source_joint_ref','qualified_source_scope_ref','reader_scope_ref','fx_qualification_ref','source_roles','original_gaps_ref','source_partition_ref','source_review_gaps','source_gaps_remaining','source_code_transport_ref','source_identity_projection_ref','source_only_identity_projection_authorized','risk_fit_carryover_ref','effective_prior_fit_units','partition_scope_ref','joint_execution_binding','no_new_risk_fit','account_repair_ref','original_final_risk_receipt_ref','execution_invariant_scalar_diagnostic_authorized','method_matrix_scope_ref','method_matrix_admission_ref'))
    carryover=_risk_fit_carryover(route,run)
    require(value.get('joint_execution_binding')==route.get('joint_execution_binding')==JOINT_EXECUTION_BINDING,'EXECUTION_JOINT_BINDING_CHANGED')
    require(value.get('risk_fit_carryover_ref')==route.get('risk_fit_carryover_ref')
        and value.get('effective_prior_fit_units')==route.get('effective_prior_fit_units')
        and value.get('partition_scope_ref')==route.get('partition_scope_ref')
        and all(value.get(k)==route.get(k) for k in ('no_new_risk_fit','account_repair_ref','original_final_risk_receipt_ref','execution_invariant_scalar_diagnostic_authorized')),
        'CARRYOVER_EXECUTION_PROOF_CHANGED')
    _equal_repair_metadata(route,run,carryover)
    require(all(value.get(k)==route.get(k) for k in ('method_matrix_scope_ref','method_matrix_admission_ref')),'MATRIX_EXECUTION_SCOPE_OR_REVIEW_CHANGED')
    _method_matrix_metadata(route,run,require_review=route.get('method_matrix_scope_ref') is not None)
    require(value.get('schema')==EXECUTION_SCHEMA and value.get('status')==AUTHORIZED and value.get('task_id')==routing.engine.TASK
        and value.get('research_id') and value['research_id']!=routing.engine.TASK
        and value.get('output_run')==str(run) and route.get('status')==AUTHORIZED,
        'DYNAMIC_NEW_RUN_IDENTITY_AND_FROZEN_EXECUTION_REQUIRED')
    require(value.get('budget')==dict(prior_fit_units=1291,max_fit_units=10000)
        and value.get('scope_start')=='2023-01-01' and value.get('scope_end_exclusive')=='2026-01-01'
        and value.get('test2026_read_authorized') is False and value.get('real_trades_authorized') is False
        and value.get('old_account_state_reused') is False and value.get('old_risk_cache_reused') is (carryover is not None),
        'DYNAMIC_PRE2026_BUDGET_AND_NEW_STATE_REQUIRED')
    require(value.get('recipe')==route['original_routing_metadata']['recipe']
        and value.get('frozen_refs')==route['original_routing_metadata']['frozen_refs']
        and value.get('consumer_owner_ref')==route['consumer_owner_ref']
        and value.get('protected_owner_refs')==protected_pins() and value.get('source_roles')==route['source_roles']
        and all(value.get(key)==route[key] for key in ('expected_freeze_ref','source_joint_ref','qualified_source_scope_ref','reader_scope_ref','fx_qualification_ref')),
        'DYNAMIC_EXECUTION_SOURCE_MODEL_AND_OWNER_PINS_CHANGED')
    require(value.get('source_code_transport_ref')==route.get('source_code_transport_ref'), 'EXECUTION_CODE_SOURCE_TRANSPORT_CHANGED')
    require(value.get('source_identity_projection_ref')==route.get('source_identity_projection_ref') and value.get('source_only_identity_projection_authorized',False)==route.get('source_only_identity_projection_authorized',False),'EXECUTION_SOURCE_IDENTITY_PROJECTION_CHANGED')
    require(value.get('account_state_root')==str(run/'evaluation'/'consensus_account') and value.get('risk_cache_root')==str(run/'models'/'consensus_final_policy'),
        'DYNAMIC_NEW_ACCOUNT_AND_RISK_OUTPUT_ROOTS_REQUIRED')
    for key,name in (('managed_run_config_ref','run_config.json'),('managed_input_manifest_ref','input_manifest.json')):
        r=value[key];require(Path(r['path']).resolve()==run/name,'DYNAMIC_MANAGED_OUTPUT_METADATA_PATH_REQUIRED')
        m=_metadata(r,('strategy_id','run_id','research_start_date','research_end_date','input_data_copied','duplicate_market_data_count',
            'broker_action_allowed','official_adoption_allowed','research_only','execution_assumption'))
        require(m.get('strategy_id')==routing.engine.TASK and m.get('run_id')==run.name
            and m.get('research_start_date')=='2023-01-01' and m.get('research_end_date')=='2025-12-31'
            and m.get('input_data_copied') is False and m.get('duplicate_market_data_count')==0
            and m.get('broker_action_allowed') is False and m.get('official_adoption_allowed') is False
            and m.get('research_only') is True and m.get('execution_assumption')=='RESEARCH_ONLY',
            'DYNAMIC_CANONICAL_MANAGED_RUN_PROVENANCE_REQUIRED')
    require(value['authorized_spec_ref']==AUTHORIZED_SPEC_REF and value['human_authorization_ref']==HUMAN_AUTHORIZATION_REF,
        'DYNAMIC_EXISTING_HUMAN_AND_AUTHORIZED_SPEC_REFS_REQUIRED')
    routing._pin(AUTHORIZED_SPEC_REF)
    authorization=_metadata(HUMAN_AUTHORIZATION_REF,('schema','task_id','authorization_source','recorded_by','human_user_authorized',
        'account_replay_authorized','pre2026_risk_fitting_authorized','authorized_spec_ref','scope','restrictions'))
    a_scope=authorization.get('scope',{});restrictions=authorization.get('restrictions',{})
    require(authorization.get('schema')==AUTHORIZATION_SCHEMA and authorization.get('task_id')==routing.engine.TASK
        and authorization.get('authorization_source')=='DIRECT_HUMAN_MESSAGES_IN_THIS_CHAT' and authorization.get('recorded_by')=='root'
        and all(authorization.get(k) is True for k in ('human_user_authorized','account_replay_authorized','pre2026_risk_fitting_authorized'))
        and authorization.get('authorized_spec_ref')==AUTHORIZED_SPEC_REF
        and a_scope.get('source_policy')=='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY' and a_scope.get('history_vintage')=='UNKNOWN'
        and a_scope.get('development_end_exclusive')=='2026-01-01' and a_scope.get('source_gaps_must_be_qualified_before_account_execution') is True
        and a_scope.get('reuse_R1_features_and_R2_fusion') is True and (a_scope.get('prior_fit_units'),a_scope.get('max_fit_units'))==(1291,10000)
        and (a_scope.get('account_initial_cash_usd'),a_scope.get('account_type'),a_scope.get('fractional'))==(3000,'CASH',True)
        and a_scope.get('new_managed_account_output_required') is True and a_scope.get('old_frozen_outputs_preserved') is True
        and all(restrictions.get(k) is False for k in ('test2026_read_authorized','FAST3_Confirmation_access','broker_action_allowed',
            'production_promotion_allowed','provider_upgrade_or_purchase_allowed','future_adjusted_cash_or_price_as_actual_share_allowed',
            'source_qualification_or_economic_acceptance_granted')), 'DYNAMIC_EXISTING_HUMAN_CONTINUATION_AUTHORIZATION_REQUIRED')
    require(value.get('original_gaps_ref')==ORIGINAL_GAPS_REF,'DYNAMIC_ORIGINAL194_SOURCE_GAPS_REF_REQUIRED')
    gaps=_array_projection(ORIGINAL_GAPS_REF,('gaps',))
    current=expected_projection(route['expected_freeze_ref'],source_roles=route['source_roles'])
    keys={inputs.existing.source._key(k) for item in current['supplements'] for k in item['event_keys']}
    original={inputs.existing.source._key({k:g[k] for k in ('ticker','effective_date','reason','source_reference','source_fingerprint')}) for g in gaps}
    if route.get('source_partition_ref') is None:
        require(len(gaps)==len(original)==len(keys)==194 and keys==original,'DYNAMIC_ALL_ORIGINAL194_SOURCE_GAPS_QUALIFIED_REQUIRED')
    else:
        require(all(value.get(k)==route.get(k) for k in ('source_partition_ref','source_review_gaps','source_gaps_remaining')), 'PARTITION_EXECUTION_REF_AND_COUNTS_CHANGED')
        partition=_partition_metadata(route,current)
        require(value['research_id']==partition['research_id'], 'PARTITION_NEW_RESEARCH_ID_REQUIRED')
    scope=_metadata(route['reader_scope_ref'],('numeric_read_authorization','scope_start','scope_end_exclusive','consumer_execution_authorized'))
    require(scope==dict(numeric_read_authorization=inputs.GATE,scope_start='2023-01-01',scope_end_exclusive='2026-01-01',consumer_execution_authorized=True),
        'DYNAMIC_FROZEN_NUMERIC_PRE2026_SOURCE_GATE_REQUIRED')
    fields=('scope_start','scope_end_exclusive','raw_price_coordinate','historical_quote_vintage_status','strict_PIT',
        'sources','source_fact_owner_ref','source_dependency_refs','pool_ref','calendar_ref','settlement_calendar_ref',
        'signal_adv_source_ref','continuation_scope_ref','account_convention_scope_ref','source_completion_manifest_ref',
        'legacy_source_transport','source_fact_construction_transport','research_id','continuation_source_dependency_custody',
        'current_corporate_owner_ref','quote_classification_scope_proof','signal_quote_domain_ref',
        'signal_quote_population_scope_proof','signal_quote_legacy_source_transport','historical_source_code_transport_ref')
    origin=_metadata(route['qualified_source_scope_ref'],fields);reader=_metadata(route['reader_scope_ref'],fields)
    if route.get('source_code_transport_ref') is not None:
        require(origin.get('historical_source_code_transport_ref')==reader.get('historical_source_code_transport_ref')==route['source_code_transport_ref'], 'READER_CODE_SOURCE_TRANSPORT_CHANGED')
    require(origin==reader and origin.get('scope_start')=='2023-01-01' and origin.get('scope_end_exclusive')=='2026-01-01'
        and origin.get('raw_price_coordinate')=='RAW_ACTUAL_SHARE' and origin.get('historical_quote_vintage_status')=='UNKNOWN'
        and origin.get('strict_PIT') is False, 'DYNAMIC_APPROVED_SOURCE_READER_ORIGIN_FIELDS_CHANGED')
    freeze_ref=routing.file_ref(run/_freeze_name(route))
    require(_metadata(freeze_ref,set(route))==route,'PRIVATE_CONSUMER_SAVED_FREEZE_CHANGED')
    return value


def _risk_code_transport(ref):
    require(canonical(ref)==RISK_CODE_TRANSPORT_REF,'EXACT_RISK_CODE_TRANSPORT_REF_REQUIRED')
    value=_metadata(ref,('status','original_code_ref','fixed_custody_ref','old_ref_not_current_risk_execution',
        'old_facts_reconstruction_ids_math_bytes_unchanged','old_freeze_modified','current_risk_modified'))
    require(value.get('status')=='PASS_ORIGINAL_SOURCE_API_EXACT_RISK_PYTHON_BYTES_CUSTODY_ONLY'
        and Path(value['original_code_ref']['path']).resolve()==Path(RISK_CODE_LOGICAL_REF['path']).resolve()
        and value['original_code_ref']['sha256']==RISK_CODE_SOURCE_SHA and canonical(value['fixed_custody_ref'])==RISK_CODE_FIXED_REF
        and value.get('old_ref_not_current_risk_execution') is True and value.get('old_facts_reconstruction_ids_math_bytes_unchanged') is True
        and value.get('old_freeze_modified') is False and value.get('current_risk_modified') is False,
        'EXACT_SOURCE_ONLY_RISK_CODE_CUSTODY_REQUIRED')
    path=routing._pin(RISK_CODE_FIXED_REF);require(path.suffix=='.py','PYTHON_CODE_CUSTODY_ONLY_REQUIRED')
    return path


def exact_risk_code_source_pin(original_pin, *, transport_ref):
    """Only the proved SOURCE Python-byte pair; all other refs retain original pin."""
    _risk_code_transport(transport_ref)
    def pin(ref):
        if Path(ref['path']).resolve()==Path(RISK_CODE_LOGICAL_REF['path']).resolve():
            require(ref['sha256']==RISK_CODE_SOURCE_SHA,'OLD_RISK_CODE_SOURCE_HASH_CHANGED')
            return routing._pin(RISK_CODE_FIXED_REF)
        return original_pin(ref)
    return pin


def exact_risk_code_source_bound(bound, *, transport_ref):
    if transport_ref is None: return bound
    return dict(bound,pin=exact_risk_code_source_pin(bound['pin'],transport_ref=transport_ref))


def bind_exact_risk_code_source_owner(owner, *, transport_ref):
    """One SOURCE-only old Python-byte pair; original binder/math/read stay intact."""
    _risk_code_transport(transport_ref)
    original=owner.bind_source_account_descendant;factory=original.__globals__.get('_owner')
    require(callable(factory),'PRIVATE_SOURCE_FACTORY_OWNER_REQUIRED')
    def projected_factory():
        private,anchors=factory();binder=private.bind_source_account_descendant;oldns=binder.__globals__;ns=dict(oldns)
        pin=exact_risk_code_source_pin(oldns['_pin'],transport_ref=transport_ref)
        ns['_pin']=pin
        for name,function in tuple(ns.items()):
            if isinstance(function,FunctionType) and function.__globals__ is oldns:ns[name]=_rebind(function,ns)
        require(ns['bind_source_account_descendant'].__code__ is binder.__code__ and ns['bind_source_account_descendant'].__globals__['_pin'] is pin,
            'EXACT_PRIVATE_SOURCE_BINDER_PIN_NOT_BOUND')
        return SimpleNamespace(**ns),anchors
    ns=dict(original.__globals__);ns['_owner']=projected_factory
    result=SimpleNamespace(**vars(owner));result.bind_source_account_descendant=_rebind(original,ns)
    require(result.bind_source_account_descendant.__code__ is original.__code__,'SOURCE_BINDER_CODE_CHANGED')
    return result


def _freeze_name(route):
    return PARTITION_FREEZE if route.get('source_partition_ref') is not None else CONTINUATION_FREEZE if route.get('schema')==CONTINUATION_SCHEMA else FREEZE


def _partition_metadata(route,expected):
    value=_metadata(route['source_partition_ref'],('schema','status','task_id','research_id','root_scope_ref','original_gaps_ref',
        'native_expected_ref','source_joint_ref','native_count','original_key_count','native_gap_count','source_review_gaps',
        'retained_unsupported_keys','sourcefact_refs','economic_PASS','test2026_read_authorized'))
    require(value.get('schema')==PARTITION_SCHEMA and value.get('status')==PARTITION_STATUS and value.get('task_id')==routing.engine.TASK
        and value.get('economic_PASS') is False and value.get('test2026_read_authorized') is False
        and value.get('original_gaps_ref')==ORIGINAL_GAPS_REF and value.get('native_expected_ref')==route['expected_freeze_ref']
        and value.get('source_joint_ref')==route['source_joint_ref']
        and (value.get('native_count'),value.get('original_key_count'),value.get('native_gap_count'),value.get('source_review_gaps'))==(192,194,2,0)
        and route.get('current_source_count')==192 and route.get('source_gaps_remaining')==2 and route.get('source_review_gaps')==0,
        'PARTITION_FROZEN_ACTUAL192_REVIEWED194_REQUIRED')
    fields=('schema','status','task_id','research_id','output_run','recorded_by','authorization_basis','human_authorization_ref',
        'authorized_spec_ref','no_new_explicit_item_by_item_user_approval_claimed','decision_disclosed_to_user_before_outcome_read',
        'old_all194_native_path_preserved','old_freezes_unchanged','original_gaps_ref','retained_unsupported_keys','sourcefact_refs',
        'native_count_required','source_review_count_required','native_gap_count_required','source_review_gap_count_required',
        'economic_PASS','scope_start','scope_end_exclusive','source_policy','history_vintage','strict_PIT_certified',
        'test2026_read_authorized','real_trades_authorized','future_payment_outcomes_as_training_input','cash_date_or_amount_synthesis_allowed',
        'retained_event_exclusion_from_pool_allowed','retained_events_remain_original_unsupported','unknown_values_are_not_zero',
        'actual_affected_account_candidate_must_be_NOT_TESTABLE','unheld_is_not_preassumed','existing_account_unsupported_failclosed_unchanged',
        'candidate_families_risk_cost_selection_units_unchanged','original_pool_and_quote_masks_unchanged','prior_fit_units','max_fit_units','protected_owner_refs','source_identity_projection_ref','source_only_identity_projection_authorized')
    scope_ref=route.get('partition_scope_ref',PARTITION_SCOPE_REF)
    require(scope_ref==PARTITION_SCOPE_REF or route.get('risk_fit_carryover_ref') is not None,'PARTITION_RECOVERY_SCOPE_NEEDS_CARRYOVER_PROOF')
    fields+=('risk_fit_carryover_ref','effective_prior_fit_units','no_new_risk_fit','account_repair_ref','original_final_risk_receipt_ref','execution_invariant_scalar_diagnostic_authorized')
    intention=_metadata(scope_ref,fields)
    final=_metadata(value['root_scope_ref'],fields+('intention_scope_ref','native_expected_ref','source_joint_ref'))
    require(final.get('risk_fit_carryover_ref')==route.get('risk_fit_carryover_ref') and final.get('effective_prior_fit_units')==route.get('effective_prior_fit_units')
        and all(final.get(k)==route.get(k) for k in ('no_new_risk_fit','account_repair_ref','original_final_risk_receipt_ref','execution_invariant_scalar_diagnostic_authorized')),
        'PARTITION_RECOVERY_FIT_PROOF_CHANGED')
    require(final.get('status')==PARTITION_STATUS and final.get('intention_scope_ref')==scope_ref
        and final.get('native_expected_ref')==route['expected_freeze_ref'] and final.get('source_joint_ref')==route['source_joint_ref']
        and all(final.get(k)==intention.get(k) for k in fields if k!='status')
        and final.get('schema')=='CONSENSUS_PRE2026_RETAINED_UNSUPPORTED_ACCOUNT_SCOPE_R1'
        and final.get('research_id')==value.get('research_id') and final.get('task_id')==routing.engine.TASK
        and final.get('output_run')==route['original_routing_metadata']['output_run']
        and final.get('authorization_basis')=='EXISTING_HUMAN_TASK_SCOPE_INTERPRETED_BY_ROOT'
        and final.get('no_new_explicit_item_by_item_user_approval_claimed') is True
        and final.get('human_authorization_ref')==HUMAN_AUTHORIZATION_REF and final.get('authorized_spec_ref')==AUTHORIZED_SPEC_REF
        and final.get('protected_owner_refs')==protected_pins() and final.get('economic_PASS') is False
        and final.get('existing_account_unsupported_failclosed_unchanged') is True
        and final.get('candidate_families_risk_cost_selection_units_unchanged') is True,
        'PARTITION_ROOT_INTERPRETATION_FREEZE_REQUIRED')
    identity_ref=route.get('source_identity_projection_ref')
    require(final.get('source_identity_projection_ref')==identity_ref and final.get('source_only_identity_projection_authorized',False)==(identity_ref is not None) and route.get('source_only_identity_projection_authorized',False)==(identity_ref is not None),'PARTITION_ROOT_EXACT_IDENTITY_PROJECTION_REQUIRED')
    if identity_ref is not None: _source_identity_projection_metadata(identity_ref)
    retained=value['retained_unsupported_keys']
    require(retained==final['retained_unsupported_keys'] and value.get('sourcefact_refs')==final['sourcefact_refs']
        and len(retained)==2 and all(set(k)=={'ticker','effective_date','reason','source_reference','source_fingerprint'} for k in retained),
        'PARTITION_EXACT_TWO_RETAINED_ORIGINAL5_KEYS_REQUIRED')
    for ref in value['sourcefact_refs'].values():routing._pin(canonical(ref))
    original=_array_projection(ORIGINAL_GAPS_REF,('gaps',));key=inputs.existing.source._key
    original_set={key({k:g[k] for k in ('ticker','effective_date','reason','source_reference','source_fingerprint')}) for g in original}
    native_set={key(k) for item in expected['supplements'] for k in item['event_keys']};retained_set={key(k) for k in retained}
    require(len(original)==len(original_set)==194 and len(native_set)==192 and len(retained_set)==2 and not native_set&retained_set
        and native_set|retained_set==original_set, 'PARTITION_DISJOINT_COMPLETE_ORIGINAL194_REQUIRED')
    return value


def _retain_partition_unsupported(before,after,retained):
    key=inputs.existing.source._key
    for original in retained:
        wanted=key(original)
        left=[row for row in before.get('unsupported_events',()) if key(row)==wanted]
        right=[row for row in after.get('unsupported_events',()) if key(row)==wanted]
        require(len(left)==len(right)==1 and left==right,'PARTITION_ORIGINAL_UNSUPPORTED_CHANGED_OR_REMOVED')
        require(not any(getattr(e,'ticker',None)==original['ticker'] and str(inputs.existing.ca._entitlement_effective_day(e).date())==original['effective_date']
            for e in after.get('entitlement_events',())), 'PARTITION_RETAINED_UNSUPPORTED_HAS_NATIVE_EVENT')
    return after


def retain_qualified_fx(result, original_marks, qualified_fx):
    cad._validate_fx_qualification(qualified_fx)
    expected = tuple(qualified_fx.marks); supplied = tuple(original_marks)
    require(len(supplied) == len(expected) == 272 and all(type(a) is type(b) and asdict(a)==asdict(b)
        for a,b in zip(supplied,expected)), 'PRIVATE61_QUALIFIED272_BOOK_PAYLOAD_CHANGED')
    copied = tuple(result.get('foreign_fx_marks', ()))
    require(len(copied) == 272 and all(asdict(a)==asdict(b) for a,b in zip(supplied,copied)), 'PRIVATE61_FX_PAYLOAD_CHANGED_BY_ORIGINAL_MERGE')
    cad.ca.select_foreign_fx_mark(copied, as_of='2025-12-31T23:59:59+00:00')
    result['foreign_fx_marks'] = supplied
    return result


def compose_components(combined, expected, descendants, *, qualified_fx, source_roles=None):
    """Source-only pure composition; all CAD/USD facts are already qualified."""
    counts=validate_entries(expected,source_roles=source_roles);roles=_entry_roles(expected,source_roles)
    require(len(descendants) == counts['owner_count'], 'PRIVATE61_ALL_BOUND_DESCENDANTS_REQUIRED')
    cad._validate_fx_qualification(qualified_fx)
    marks = tuple(combined.get('foreign_fx_marks', ()))
    if len(marks) == 258:
        require(all(asdict(a)==asdict(b) for a,b in zip(marks,qualified_fx.old_marks)), 'PRIVATE61_OLD258_BOOK_CHANGED')
        combined = dict(combined, foreign_fx_marks=cad.merge_fx_marks(marks,qualified_fx.early_marks))
    marks = tuple(combined.get('foreign_fx_marks', ()))
    result = combined
    for index,(item,desc) in enumerate(zip(expected['supplements'],descendants),1):
        require(desc['original_namespace'] == item['original_namespace'] and canonical(desc['bundle_ref']) == canonical(item['bundle_ref']), 'PRIVATE61_BINDER_NAMESPACE_OR_BUNDLE_CHANGED')
        native = desc['native']
        if roles[index-1]['binder_kind']=='ORIGINAL_CAD_FOREIGN_NATIVE':
            require(type(desc.get('CAD_original_resolution')) is dict and desc.get('binder_kind') == 'ORIGINAL_CAD_FOREIGN_NATIVE', 'PRIVATE61_CAD_NOT_USD_BINDER_REQUIRED')
            closed=desc.get('CAD_native_qualifications',())
            require(len(closed)==roles[index-1]['event_count'] and all(type(n) is cad.NativeQualification and n.proof_sha256==cad.digest(n.proof) and n.source.receipt_sha256==cad.digest(n.source.receipt) and n.source.key in cad.CASES and n.proof['event_fingerprint']==n.source.event.event_fingerprint and n.source.event.currency=='CAD' and n.source.event.amount_unit==cad.ca.CAD_PER_RAW_OLD_SHARE for n in closed), 'PRIVATE61_CLOSED_CAD_NATIVE_QUALIFICATIONS_REQUIRED')
            require(desc['CAD_original_resolution']['proof']['removed_exact_original_keys'] == native['events']['entitlement_source_binding']['manifest']['removed_exact_original_keys'], 'PRIVATE61_CAD_ORIGINAL5FIELD_BINDING_REQUIRED')
        else: require(desc.get('binder_kind') == roles[index-1]['binder_kind'], 'PRIVATE61_USD_ORIGINAL_BINDER_REQUIRED')
        records = native['events']['entitlement_source_binding']['manifest']['removed_exact_original_keys']
        actual = {e.event_fingerprint for e in native['events']['entitlement_events']}
        if roles[index-1]['binder_kind']=='MASSIVE_VENDOR_USD_NATIVE_BINDER':
            require(native['events']['entitlement_source_binding']['manifest'].get('key_to_component_fingerprints')==item['key_to_component_fingerprints'], 'DYNAMIC_VENDOR_ORIGINAL_API_COMPONENT_MAP_CHANGED')
        require({inputs.existing.source._key(k) for k in records} == {inputs.existing.source._key(k) for k in item['event_keys']}
            and set(item['event_fingerprints']) <= actual, 'PRIVATE61_EXACT5FIELD_OR_NATIVE_FINGERPRINT_CHANGED')
        result = inputs.merge_completion_descendant(result,native,canonical(item['bundle_ref']))
        result = retain_qualified_fx(result,marks,qualified_fx)
    return result


def bind_components(expected, original_owner, original, calendar, *, pin, read, qualified_fx, original_source_kwargs_ref, source_roles=None, source_code_transport_ref=None):
    """Only a separately authorized source loader supplies actual payloads here."""
    validate_entries(expected,source_roles=source_roles);roles=_entry_roles(expected,source_roles)
    cad._validate_fx_qualification(qualified_fx); descendants=[]; canonical_native=[]
    for index,item in enumerate(expected['supplements'],1):
        owner_ref=canonical(item['native_owner_ref']); bundle_ref=canonical(item['bundle_ref'])
        pin(owner_ref)
        loader_name=('_consensus_dynamic_source_'+inputs.existing.digest(dict(owner=owner_ref,bundle=bundle_ref))[:24]) if source_roles is not None else item['original_namespace']
        owner=inputs.existing._load_python(owner_ref,loader_name);bundle=read(bundle_ref)
        if roles[index-1]['binder_kind']!='ORIGINAL_CAD_FOREIGN_NATIVE':
            require(callable(getattr(owner,'bind_source_account_descendant',None)), 'PRIVATE61_ORIGINAL_USD_BINDER_API_REQUIRED')
            if roles[index-1]['binder_kind']=='MASSIVE_VENDOR_USD_NATIVE_BINDER':
                require(getattr(owner,'SOURCE_BINDER_ROLE',None)=='MASSIVE_VENDOR_USD_NATIVE_BINDER' and canonical(bundle.get('completion_binder_owner_ref',{}))==owner_ref, 'DYNAMIC_VENDOR_ACTUAL_OWNER_API_REQUIRED')
            owner._read=inputs.completion_predecessor_reader(bundle,pin,read)
            if source_code_transport_ref is not None and callable(owner.bind_source_account_descendant.__globals__.get('_owner')):
                owner=bind_exact_risk_code_source_owner(owner,transport_ref=source_code_transport_ref)
            result=owner.bind_source_account_descendant(original_owner,original,bundle,account_dates=calendar,bundle_ref=bundle_ref)
            if roles[index-1]['binder_kind']=='MASSIVE_VENDOR_USD_NATIVE_BINDER':
                require(result['events']['entitlement_source_binding']['manifest'].get('key_to_component_fingerprints')==item['key_to_component_fingerprints'], 'DYNAMIC_VENDOR_ORIGINAL_API_COMPONENT_MAP_CHANGED')
            descendants.append(dict(original_namespace=item['original_namespace'],bundle_ref=bundle_ref,native=result,binder_kind=roles[index-1]['binder_kind']))
            continue
        require(canonical(bundle['completion_binder_owner_ref'])==owner_ref and bundle['status']=='QUALIFIED_SOURCE_NATIVE_COMPONENT_ONLY_NOT_ACCOUNT', 'PRIVATE61_ORIGINAL_CAD_COMPONENT_OWNER_REQUIRED')
        require(owner.ca is inputs.existing.ca,'PRIVATE61_CANONICAL_FOREIGN_EVENT_TYPE_REQUIRED')
        native=[];sources=[]
        for row in bundle['native_proofs']:
            sq=read(canonical(row['source_qualification_ref'])); np=read(canonical(row['native_proof_ref']))
            event=owner.ca.SourceBackedForeignCashEvent(**sq['event'])
            q=owner.SourceQualification(tuple(row['key']),event,sq['receipt'],sq['receipt_sha256'])
            require(owner.digest(q.receipt)==q.receipt_sha256 and owner.digest(np['proof'])==np['proof_sha256']==row['native_proof_fingerprint'] and np['proof']['event_fingerprint']==event.event_fingerprint, 'PRIVATE61_CLOSED_ORIGINAL_CAD_NATIVE_PROOFS_REQUIRED')
            n=owner.NativeQualification(q,np['proof'],np['proof_sha256']); native.append(n); sources.append(q)
            cq=cad.SourceQualification(q.key,event,q.receipt,q.receipt_sha256)
            canonical_native.append(cad.NativeQualification(cq,n.proof,n.proof_sha256))
        require(len(native)==roles[index-1]['event_count'],'PRIVATE61_CAD_COMPONENT_COUNT_REQUIRED')
        resolution=owner.qualify_original_records(original,native,original_ref=canonical(original_source_kwargs_ref))
        require(resolution==bundle['original_resolution'],'PRIVATE61_CAD_ORIGINAL5FIELD_RESOLUTION_CHANGED')
        component_fx=owner.qualify_fx_marks(qualified_fx.old_marks,qualified_fx.early_marks,sources=sources)
        require(all(asdict(a)==asdict(b) for a,b in zip(component_fx.marks,qualified_fx.marks)) and len(component_fx.marks)==272 and all(n.proof['qualified_FX_payload_proof_sha256']==component_fx.proof_sha256 for n in native), 'PRIVATE61_CAD_ORIGINAL_COMPONENT_FX_PAYLOAD_PROOF_REQUIRED')
        events=tuple(n.source.event for n in native);mapping={e.old_security_id:e.ticker for e in events}
        payload=dict(events=dict(entitlement_events=events,entitlement_security_tickers=mapping,
            entitlement_source_binding=dict(source_fingerprint=owner.digest([n.proof_sha256 for n in native]),
                manifest=dict(removed_exact_original_keys=copy.deepcopy(resolution['proof']['removed_exact_original_keys']),CAD_native_proof_fingerprints=[n.proof_sha256 for n in native],CAD_original_resolution=copy.deepcopy(resolution)),security_tickers=mapping),research_account_authority={}))
        descendants.append(dict(original_namespace=item['original_namespace'],bundle_ref=bundle_ref,native=payload,binder_kind='ORIGINAL_CAD_FOREIGN_NATIVE',CAD_original_resolution=resolution,CAD_native_qualifications=tuple(canonical_native[-len(native):])))
    require(len(canonical_native)==4,'PRIVATE61_ALL4_CANONICAL_CAD_QUALIFICATIONS_REQUIRED')
    return descendants,tuple(canonical_native)


def _named_source_identity_projection_metadata(ref):
    ref=canonical(ref)
    if ref==CVX_IDENTITY_PROJECTION_REF:
        ticker='CVX';count=3;status='FROZEN_EXACT_THREE_ORIGINAL_CVX_IDENTITY_REPRESENTATIONS'
        source_sid='SOURCE_ISSUER_COMMON_CLASS:0d7bd0e3ba929e637481cef5f8a1a6f00ebf17fd51be8570396f236913fed7ec';cusip='166764100';clock='2023-01-31T18:58:04Z'
        issuer='Chevron Corporation';payload_sha='63f07fafd2470b7ea88add9acdb7277a7177305976a77e2307ab9768fdfc8417'
        dates={'2023-02-15','2023-05-18','2023-11-16'}
        official=dict(subject_company_cik=93410,subject_company_name='CHEVRON CORP',issuer_literal='CHEVRON CORPORATION',title_of_class='Common Stock',cusip=cusip,acceptance_datetime_local='20230131135804',acceptance_timezone='America/New_York',available_at_utc=clock)
    elif ref==DD_IDENTITY_PROJECTION_REF:
        ticker='DD';count=11;status='FROZEN_EXACT_ELEVEN_ORIGINAL_DD_IDENTITY_REPRESENTATIONS'
        source_sid='SOURCE_ISSUER_COMMON_CLASS:e2ed4b7d2c8319ffe0205f635a4dca9430d063db41cd5ed3183b0be34d21dde5';cusip='26614N102';clock='2023-02-03T16:43:53Z'
        issuer='DuPont de Nemours, Inc.';payload_sha='5b9b16995ae1aa7a0c8d373cf768cbcddeea1dab2ac576d81561a84bb12c429c'
        dates={'2023-02-27','2023-05-30','2023-07-28','2023-11-29','2024-02-28','2024-05-31','2024-08-30','2024-11-29','2025-03-03','2025-05-30','2025-08-29'}
        official=dict(subject_company_cik=1666700,subject_company_name='DuPont de Nemours, Inc.',issuer_literal='DUPONT DE NEMOURS INC',title_of_class='COMMON STOCK',cusip=cusip,acceptance_datetime_local='20230203114353',acceptance_timezone='America/New_York',available_at_utc=clock)
    else:raise ValueError('EXACT_NAMED_CVX_OR_DD_IDENTITY_PROJECTION_REQUIRED')
    names=('schema','status','task_id','ticker','source_sid','accounting_sid','cusip','security_uid','source_coordinate','identity_available_at',
        'same_common_share_class','share_quantity_effect','source_cash_terms_changed','original_source_available_at_changed',
        'original_source_fingerprints_changed','original_source192_qualification_precedes_projection','original_mapping_rewritten','strict_PIT',
        'historical_archive_vintage','only_authorized_original_event_count','new_legal_CUSIP_created','derived_fingerprint_rule','non_sid_digest_rule',
        'official_subject_common_security','event_projections','evidence_refs','dated_identity_links','actual2026_values_read','market_forecast_or_account_read','new_fits',
        'share_quantity_effect_scope','parent_quantity_evidence','retained_unsupported_event','retained_unsupported_instructions')
    proof=_metadata(ref,names)
    require(proof.get('schema')==f'CONSENSUS_{ticker}_ORIGINAL_CLASS_DATED_RAW_IDENTITY_PROJECTION_R1'
        and proof.get('status')==status and proof.get('task_id')==routing.engine.TASK
        and proof.get('ticker')==ticker and proof.get('source_sid')==source_sid
        and proof.get('accounting_sid')==f'FROZEN_RAW_TRANSPORT_CODE:US.{ticker}' and proof.get('cusip')==cusip
        and proof.get('security_uid')==f'CUSIP:{cusip}' and proof.get('source_coordinate')=='RAW_ACTUAL_SHARE'
        and proof.get('only_authorized_original_event_count')==count and proof.get('identity_available_at')==clock
        and proof.get('same_common_share_class') is True and proof.get('original_source192_qualification_precedes_projection') is True
        and proof.get('historical_archive_vintage')=='UNKNOWN' and proof.get('new_fits')==0
        and all(proof.get(k) is False for k in ('share_quantity_effect','source_cash_terms_changed','original_source_available_at_changed',
            'original_source_fingerprints_changed','original_mapping_rewritten','strict_PIT','new_legal_CUSIP_created','actual2026_values_read','market_forecast_or_account_read'))
        and proof.get('derived_fingerprint_rule')=='SHA256_CANONICAL_DATACLASS_ASDICT_WITH_ONLY_OLD_SECURITY_ID_REPLACED'
        and proof.get('non_sid_digest_rule')=='SHA256_CANONICAL_EVENT_TYPE_AND_ASDICT_EXCLUDING_OLD_SECURITY_ID',
        f'{ticker}_EXACT_COMMON_SHARE_REPRESENTATION_PROOF_REQUIRED')
    require(proof['official_subject_common_security']==official,f'{ticker}_PREEX_SUBJECT_COMMON_CLASS_AND_CUSIP_REQUIRED')
    rows=proof['event_projections'];require(len(rows)==count and {r['ex_date'] for r in rows}==dates
        and len({r['original_event_fingerprint'] for r in rows})==count and len({r['derived_event_fingerprint'] for r in rows})==count,f'{ticker}_EXACT_ORIGINAL_EVENTS_REQUIRED')
    links=[]
    for row in rows:
        identity=row['original_identity_binding'];dated=row['dated_identity_rows']
        require(row.get('event_type')=='SourceBackedEntitlementEvent' and row.get('identity_available_at')==clock
            and row.get('source_coordinate')==proof['source_coordinate'] and row.get('cusip')==cusip and row.get('security_uid')==proof['security_uid']
            and row.get('accounting_sid')==proof['accounting_sid'] and row['original_source_fact_ref']['sha256']==row['source_fingerprint']
            and identity.get('security_id')==source_sid and identity.get('issuer')==issuer
            and identity.get('listing_identity')==f'NYSE:{ticker}' and identity.get('security_type')=='COMMON_STOCK'
            and identity.get('identity_payload_sha256')==payload_sha
            and len(dated)==2 and {r['signal_date'] for r in dated}=={row['prior_date'],row['ex_date']}
            and all(r==dict(signal_date=r['signal_date'],ticker=ticker,security_id=cusip,moomoo_transport_code=f'US.{ticker}') for r in dated),
            f'{ticker}_ORIGINAL_CLASS_AND_EXACT_DATED_UID_REQUIRED')
        links.extend(dict(signal_date=r['signal_date'],security_uid=proof['security_uid'],ticker=ticker,accounting_sid=proof['accounting_sid']) for r in dated)
        routing._pin(canonical(row['original_source_fact_ref']))
    require(proof['dated_identity_links']==links,f'{ticker}_ORIGINAL_DATED_MAPPER_LINKS_CHANGED')
    for evidence in proof['evidence_refs'].values():routing._pin(canonical(evidence))
    if ticker=='DD':
        parent=proof['parent_quantity_evidence'];retained=proof['retained_unsupported_instructions']
        require(proof.get('share_quantity_effect_scope')=='THIS_IDENTITY_REPRESENTATION_PROJECTION_ONLY'
            and parent.get('document_date')=='2025-10-15' and parent.get('absolute_publication_available_at')=='UNKNOWN_IN_THIS_BODY_CUSTODY'
            and parent.get('historical_availability')=='UNKNOWN' and parent.get('only_Qnity_distribution_no_parent_surrender_exchange_and_parent_outstanding_rights_unchanged') is True
            and parent.get('other_corporate_actions_exhaustively_checked') is False and parent.get('unproved_other_actions')=='UNKNOWN'
            and parent.get('child_asset_or_cash_in_lieu_valuation_qualified') is False
            and proof['retained_unsupported_event']==dict(ticker='DD',effective_date='2025-11-03',reason='VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY',
                source_reference=r'D:\us-tech-quant-results\A2_STATEFUL_ACTION_AND_CASH_PRE2026_TEST2026_R1\ACCOUNT_EVENT_BINDING_R1.json',source_fingerprint='153701085c92c6508d55782fedb41f86458a0c67e888a3e5300fbc6ae136bb9d')
            and all(retained.get(k) is True for k in ('all_original_Nov03_fields_must_remain_unchanged','all6500_remaining_unsupported_preserved',
                'owner26_removes_only_DD_2025_11_28_cash_key','preexisting_held_Nov03_permanently_invalid_NAV','actual_holdings_not_assumed','namespace_projection_does_not_qualify_distribution')),
            'DD_PARENT_QUANTITY_EVIDENCE_AND_RETAINED_UNSUPPORTED_REQUIRED')
        require({r['role'] for r in parent['fragments']}=={'DOCUMENT_DATE','LEGAL_ISSUERS_AND_DISTRIBUTED_COMMON_CLASS','OLD_DD_NO_SURRENDER_OR_EXCHANGE','OLD_DD_OUTSTANDING_SHARES_AND_RIGHTS_UNCHANGED'} and len(parent['fragments'])==4,'DD_EXACT_FOUR_PARENT_EVIDENCE_FRAGMENTS_REQUIRED')
        for row in parent['fragments']:routing._pin(canonical(row['fragment_ref']))
    return proof


def _source_identity_projection_metadata(ref):
    # Retain the frozen CVX-only interface; the current two-domain route has one manifest.
    if canonical(ref)==CVX_IDENTITY_PROJECTION_REF:return _named_source_identity_projection_metadata(ref)
    require(canonical(ref)==IDENTITY_PROJECTION_MANIFEST_REF,'EXACT_TWO_NAMED_IDENTITY_PROJECTION_MANIFEST_REQUIRED')
    manifest=_metadata(ref,('schema','status','task_id','projections','authorized_original_event_count','original_source192_qualification_precedes_projection',
        'original_source_payload_unchanged','original_Source_available_at_unchanged','original_Source_fingerprints_unchanged','all_non_SID_economic_fields_unchanged',
        'share_quantity_effect','other_ticker_alias_authorized','unsupported_events_all_original_fields_unchanged','retained_DD_Nov03_unsupported_event',
        'retained_DD_held_permanent_NAV_invalid','child_asset_or_cash_in_lieu_qualification','unproved_other_actions','strict_PIT','historical_archive_vintage','actual2026_values_read','market_forecast_or_account_read','new_fits'))
    require(manifest.get('schema')=='CONSENSUS_CVX_DD_EXACT_IDENTITY_PROJECTION_MANIFEST_R1'
        and manifest.get('status')=='FROZEN_TWO_NAMED_SOURCE_IDENTITY_REPRESENTATIONS' and manifest.get('task_id')==routing.engine.TASK
        and manifest.get('projections')==[dict(ticker='CVX',projection_ref=CVX_IDENTITY_PROJECTION_REF,original_event_count=3),dict(ticker='DD',projection_ref=DD_IDENTITY_PROJECTION_REF,original_event_count=11)]
        and manifest.get('authorized_original_event_count')==14 and manifest.get('historical_archive_vintage')=='UNKNOWN' and manifest.get('unproved_other_actions')=='UNKNOWN' and manifest.get('new_fits')==0
        and all(manifest.get(k) is True for k in ('original_source192_qualification_precedes_projection','original_source_payload_unchanged','original_Source_available_at_unchanged',
            'original_Source_fingerprints_unchanged','all_non_SID_economic_fields_unchanged','unsupported_events_all_original_fields_unchanged','retained_DD_held_permanent_NAV_invalid'))
        and all(manifest.get(k) is False for k in ('share_quantity_effect','other_ticker_alias_authorized','child_asset_or_cash_in_lieu_qualification','strict_PIT','actual2026_values_read','market_forecast_or_account_read')),
        'EXACT_CVX_DD_SOURCE_ONLY_MANIFEST_REQUIRED')
    proofs=[_named_source_identity_projection_metadata(row['projection_ref']) for row in manifest['projections']]
    require(manifest['retained_DD_Nov03_unsupported_event']==proofs[1]['retained_unsupported_event'],'DD_MANIFEST_RETAINED_EVENT_CHANGED')
    return dict(manifest,qualified_projections=proofs)


def project_source_identity(combined, *, projection_ref):
    """Derive only the named CVX/DD representations after original native gates."""
    metadata=_source_identity_projection_metadata(projection_ref);proofs=metadata.get('qualified_projections',(metadata,));events=tuple(combined['entitlement_events'])
    mapping=dict(combined['entitlement_security_tickers']);rows={};retained_snapshots=[]
    for proof in proofs:
        source_sid=proof['source_sid'];ticker=proof['ticker'];catalogue={r['original_event_fingerprint']:r for r in proof['event_projections']}
        require({e.event_fingerprint for e in events if e.old_security_id==source_sid}==set(catalogue) and sum(e.event_fingerprint in catalogue for e in events)==len(catalogue),f'{ticker}_EXACT_ORIGINAL_TYPED_CATALOGUE_REQUIRED')
        require(mapping.get(source_sid)==ticker and mapping.get(proof['accounting_sid']) in (None,ticker)
            and not any(getattr(e,'old_security_id',None)==source_sid or getattr(e,'new_security_id',None)==source_sid for e in combined.get('corporate_actions',())),f'{ticker}_IDENTITY_ONLY_NO_SHARE_TRANSITION_REQUIRED')
        for fp,row in catalogue.items():require(fp not in rows,'NAMED_PROJECTION_ORIGINAL_FINGERPRINT_COLLISION');rows[fp]=(row,proof)
        if ticker=='DD':
            retained=proof['retained_unsupported_event'];selected=[r for r in combined.get('unsupported_events',()) if all(r.get(k)==v for k,v in retained.items())]
            require(len(selected)==1 and all(selected[0].get(k)==v for k,v in retained.items()),'DD_ORIGINAL_NOV03_UNSUPPORTED_REQUIRED')
            retained_snapshots.append((selected[0],copy.deepcopy(selected[0])))
    projected=[];lineage=[];pd=inputs.pd
    for event in events:
        found=rows.get(event.event_fingerprint)
        if found is None:projected.append(event);continue
        row,proof=found;ticker=proof['ticker'];original=asdict(event);non_sid={k:v for k,v in original.items() if k!='old_security_id'}
        require(type(event) is inputs.existing.ca.SourceBackedEntitlementEvent and event.ticker==ticker and event.old_security_id==proof['source_sid']
            and event.ex_date==row['ex_date'] and event.source_fingerprint==row['source_fingerprint'] and event.source_reference==row['source_reference']
            and event.available_at==row['original_source_available_at'] and event.action_type=='CASH_DIVIDEND' and event.currency=='USD'
            and event.amount_unit==inputs.existing.ca.USD_PER_RAW_OLD_SHARE and event.quantity_coordinate==inputs.existing.ca.RAW_OLD_SHARE_COORDINATE
            and inputs.existing.digest(dict(event_type=type(event).__name__,fields=non_sid))==row['non_sid_fields_sha256'],f'{ticker}_ORIGINAL_TYPE_FIELDS_AND_SOURCE_FINGERPRINT_REQUIRED')
        cash_clock=pd.Timestamp(event.available_at);identity_clock=pd.Timestamp(row['identity_available_at']);open_clock=(pd.Timestamp(event.ex_date)+pd.Timedelta(hours=9,minutes=30)).tz_localize('America/New_York').tz_convert('UTC')
        require(cash_clock.tzinfo is not None and identity_clock.tzinfo is not None and max(cash_clock,identity_clock)==pd.Timestamp(row['effective_identity_available_at'])
            and max(cash_clock,identity_clock)<=open_clock,f'{ticker}_IDENTITY_PROOF_AVAILABLE_BEFORE_EVENT_REQUIRED')
        converted=replace(event,old_security_id=proof['accounting_sid'])
        require(type(converted) is type(event) and converted.event_fingerprint==row['derived_event_fingerprint']
            and {k:v for k,v in asdict(converted).items() if k!='old_security_id'}==non_sid,f'{ticker}_DERIVED_FINGERPRINT_ONLY_SID_CHANGE_REQUIRED')
        projected.append(converted);lineage.append(dict(original_event_fingerprint=event.event_fingerprint,derived_event_fingerprint=converted.event_fingerprint,
            non_sid_fields_sha256=row['non_sid_fields_sha256'],original_source_fingerprint=event.source_fingerprint,original_source_available_at=event.available_at,
            identity_available_at=row['identity_available_at'],effective_identity_available_at=row['effective_identity_available_at']))
    for proof in proofs:del mapping[proof['source_sid']];mapping[proof['accounting_sid']]=proof['ticker']
    binding=combined['entitlement_source_binding'];fps=[e.event_fingerprint for e in projected];require(len(fps)==len(set(fps)),'NAMED_PROJECTED_EVENT_FINGERPRINT_COLLISION')
    result=dict(combined,entitlement_events=tuple(projected),entitlement_security_tickers=mapping,
        entitlement_source_binding=dict(binding,event_fingerprints=fps,security_tickers=mapping,
            source_fingerprint=inputs.existing.digest(dict(original_source_binding_fingerprint=binding['source_fingerprint'],identity_projection_ref=canonical(projection_ref),event_fingerprints=fps)),
            manifest=dict(binding['manifest'],source_identity_projection=dict(projection_ref=canonical(projection_ref),original_source_binding_fingerprint=binding['source_fingerprint'],
                event_lineage=lineage,source_only_not_account_qualification=True,share_quantity_effect=False))))
    require(result.get('unsupported_events') is combined.get('unsupported_events') and all(original==snapshot for original,snapshot in retained_snapshots),'DD_ALL_ORIGINAL_UNSUPPORTED_FIELDS_CHANGED')
    return result


def source_connector(expected, *, qualified_fx, pin, read, original_source_kwargs_ref, source_roles=None, source_partition_ref=None, source_code_transport_ref=None, source_identity_projection_ref=None):
    """Inject a single heterogeneous hook, without the old uniform USD hook."""
    expected=copy.deepcopy(expected);source_roles=copy.deepcopy(source_roles)
    retained=None if source_partition_ref is None else _metadata(source_partition_ref,('retained_unsupported_keys',))['retained_unsupported_keys']
    validate_entries(expected,source_roles=source_roles)
    def connect(combined,composition,bound,original_owner,original):
        if source_code_transport_ref is not None: _risk_code_transport(source_code_transport_ref)
        if retained is not None:
            require(_metadata(source_partition_ref,('retained_unsupported_keys',))['retained_unsupported_keys']==retained,'PARTITION_CONNECTOR_RETAINED_PROOF_CHANGED')
            _retain_partition_unsupported(original,combined,retained)
        descendants,_=bind_components(expected,original_owner,original,bound['calendar'],pin=pin,read=read,qualified_fx=qualified_fx,original_source_kwargs_ref=original_source_kwargs_ref,source_roles=source_roles,source_code_transport_ref=source_code_transport_ref)
        result=compose_components(combined,expected,descendants,qualified_fx=qualified_fx,source_roles=source_roles)
        if source_identity_projection_ref is not None: result=project_source_identity(result,projection_ref=source_identity_projection_ref)
        if retained is not None: _retain_partition_unsupported(original,result,retained)
        counts=validate_entries(expected,source_roles=source_roles)
        return result,dict(original_R6=composition,private_source_counts=counts,source_only_not_account_qualification=True)
    return connect


def _validate_connector(route, connector, expected):
    require(callable(connector) and getattr(connector,'__code__',None) is next(c for c in source_connector.__code__.co_consts
        if inspect.iscode(c) and c.co_name=='connect'), 'DYNAMIC_CANONICAL_SOURCE_CONNECTOR_FACTORY_REQUIRED')
    cells=dict(zip(connector.__code__.co_freevars,(c.cell_contents for c in connector.__closure__)))
    require(cells.get('expected')==expected and cells.get('source_roles')==route['source_roles'] and cells.get('source_partition_ref')==route.get('source_partition_ref') and cells.get('source_code_transport_ref')==route.get('source_code_transport_ref') and cells.get('source_identity_projection_ref')==route.get('source_identity_projection_ref'),
        'DYNAMIC_SOURCE_CONNECTOR_FROZEN_EXPECTED_AND_ROLES_CHANGED')
    fx=_fx_metadata(route)
    require(getattr(cells.get('qualified_fx'),'proof_sha256',None)==fx['canonical_payload_proof_sha256'],
        'DYNAMIC_SOURCE_CONNECTOR_QUALIFIED_FX_PAYLOAD_CHANGED')
    sources=_metadata(route['reader_scope_ref'],('sources',)).get('sources',{})
    require(canonical(cells['original_source_kwargs_ref'])==canonical(sources['original_cash_kwargs']),
        'DYNAMIC_SOURCE_CONNECTOR_ORIGINAL_KWARGS_ORIGIN_CHANGED')


def _rebind(function, namespace):
    value = FunctionType(function.__code__,namespace,name=function.__name__,argdefs=function.__defaults__,closure=function.__closure__)
    value.__kwdefaults__ = function.__kwdefaults__
    return value


def _guarded_execution(route, function, *, cache_context=None):
    cache_context={} if cache_context is None else cache_context
    def guarded(*args, **kwargs):
        run,_=validate(route, execute=True)
        arguments=inspect.signature(function).bind(*args,**kwargs).arguments
        if route.get('no_new_risk_fit') is True:
            require(function.__name__ not in ('run_all','main'),'NO_NEW_FIT_REPAIR_CANNOT_RUN_FULL_RECIPE')
            if function.__name__=='make_policy':
                config=arguments['config']
                require((config.risk_method,config.allocation_method,config.lookback_sessions)==('LW','equal_weight',120)
                    and arguments['fee_config']==routing.engine.cash.FeeConfig(**route['original_routing_metadata']['recipe']['fee_config']),
                    'NO_NEW_FIT_REPAIR_EXACT_EQUAL_POLICY_AND_FEES_REQUIRED')
            if function.__name__=='evaluate_flow':
                require(tuple(arguments[k] for k in ('method','risk_method','allocation_method'))==('nnls_zero_abstain','LW','equal_weight')
                    and arguments.get('diagnostic') is None,'NO_NEW_FIT_REPAIR_ONLY_ORIGINAL_EQUAL_SLOT')
        if 'run' in arguments: require(Path(arguments['run']).resolve()==run, 'PRIVATE_CONSUMER_WRONG_OUTPUT_RUN')
        if route.get('schema')==CONTINUATION_SCHEMA:
            for key in ('cache','shared_cache'):
                if key not in arguments: continue
                cache=arguments[key]
                if 'cache' not in cache_context:
                    require(isinstance(cache,dict) and not cache, 'DYNAMIC_INITIAL_OLD_RISK_CACHE_FORBIDDEN')
                    carryover=_risk_fit_carryover(route,run)
                    if carryover is not None:cache.update(_carryover_risk_cache(carryover))
                    cache_context['cache']=cache
                else: require(cache is cache_context['cache'], 'DYNAMIC_SHARED_RISK_CACHE_INSTANCE_CHANGED')
            if 'freeze_ref' in arguments:
                require(arguments['freeze_ref']==routing.file_ref(run/_freeze_name(route)), 'DYNAMIC_NEW_AUTHORITY_FREEZE_AND_READER_REQUIRED')
            if 'selected' in arguments:
                selected=arguments['selected'];state_ref=selected['artifacts']['state']
                require(Path(selected['receipt_path']).resolve().is_relative_to(run/'evaluation'/'consensus_account')
                    and Path(state_ref['path']).resolve().is_relative_to(run/'evaluation'/'consensus_account'), 'DYNAMIC_OLD_SELECTED_ACCOUNT_STATE_FORBIDDEN')
                routing._pin(canonical(state_ref))
            if 'frozen_contract_ref' in arguments:
                require(canonical(arguments['frozen_contract_ref'])==routing.file_ref(run/_freeze_name(route)) and arguments.get('source_scope_ref')==route['reader_scope_ref'], 'DYNAMIC_NEW_AUTHORITY_FREEZE_AND_READER_REQUIRED')
            if 'task_authority' in arguments:
                authority=arguments['task_authority']
                require(canonical(authority.get('frozen_contract_ref',{}))==routing.file_ref(run/_freeze_name(route)) and authority.get('source_scope_ref')==route['reader_scope_ref'], 'DYNAMIC_NEW_AUTHORITY_FREEZE_AND_READER_REQUIRED')
        return function(*args, **kwargs)
    guarded.__name__ = function.__name__
    return guarded



INVARIANT_SCALAR_FIELDS=('cash_failure','name_failure','cash_min','actual_name_max','max_positions','pre2026_execution_date')
INVARIANT_SCALAR_PREFIX='ORIGINAL_ACCOUNT_INVARIANT_SCALAR_METADATA:'


def _account_invariant_scalar_exception(cash,units,max_positions,date,cash_failure,name_failure):
    pd=routing.engine.pd;np=routing.engine.np;day=pd.Timestamp(date)
    require(pd.Timestamp('2023-01-01')<=day<pd.Timestamp('2026-01-01'),'ACCOUNT_INVARIANT_DIAGNOSTIC_PRE2026_ONLY')
    minimum=float(np.min(cash))
    payload=dict(cash_failure=bool(cash_failure),name_failure=bool(name_failure),cash_min=minimum if np.isfinite(minimum) else None,
        actual_name_max=int(np.count_nonzero(units>routing.engine.cash.engine.TOL,axis=1).max()),max_positions=int(max_positions),
        pre2026_execution_date=day.date().isoformat())
    require(tuple(payload)==INVARIANT_SCALAR_FIELDS and (payload['cash_failure'] or payload['name_failure']),
        'ACCOUNT_INVARIANT_ORIGINAL_REJECTED_CONJUNCT_REQUIRED')
    return routing.engine.NotTestable(INVARIANT_SCALAR_PREFIX+json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False))


def _cash_invariant_diagnostic_entry(entry):
    """One private final-AST Raise edit; original predicate and arithmetic exact."""
    cash=routing.engine.cash
    require(entry is cash.run_cash_account and routing.file_ref(cash.__file__)==routing.engine.source_pins()['cash'],
        'EXACT_ORIGINAL_CASH_ENTRY_AND_LOGICAL_PIN_REQUIRED')
    original_projector=cash._project_engine
    def projector(rules,usable_a=None):
        captured=[]
        def diagnostic_compile(tree,*args,**kwargs):
            if isinstance(tree,ast.Module) and any(isinstance(n,ast.Name) and n.id=='_cash_rules' for n in ast.walk(tree)):
                before=copy.deepcopy(tree);node=copy.deepcopy(tree)
                matches=[n for n in ast.walk(node) if isinstance(n,ast.If) and len(n.body)==1 and isinstance(n.body[0],ast.Raise)
                    and isinstance(n.body[0].exc,ast.Call) and isinstance(n.body[0].exc.func,ast.Name)
                    and n.body[0].exc.func.id=='AssertionError' and len(n.body[0].exc.args)==1
                    and isinstance(n.body[0].exc.args[0],ast.Constant) and n.body[0].exc.args[0].value=='common cash/actual name invariant']
                require(len(matches)==1 and isinstance(matches[0].test,ast.BoolOp) and isinstance(matches[0].test.op,ast.Or)
                    and len(matches[0].test.values)==2,'EXACT_ORIGINAL_CASH_OR_NAME_ASSERTION_REQUIRED')
                gate=matches[0];old_raise=copy.deepcopy(gate.body[0]);predicate=ast.dump(gate.test)
                gate.body[0].exc=ast.Call(func=ast.Name(id='_account_invariant_scalar_exception',ctx=ast.Load()),
                    args=[ast.Name(id=name,ctx=ast.Load()) for name in ('cash','units','max_positions','date')]
                         +[copy.deepcopy(n) for n in gate.test.values],keywords=[])
                node=ast.fix_missing_locations(node);reverse=copy.deepcopy(node)
                reverse_gate=next(n for n in ast.walk(reverse) if isinstance(n,ast.If) and ast.dump(n.test)==predicate
                    and len(n.body)==1 and isinstance(n.body[0],ast.Raise));reverse_gate.body[0]=old_raise
                require(ast.dump(reverse)==ast.dump(before),'ACCOUNT_INVARIANT_DIAGNOSTIC_REVERSE_AST_NOT_EXACT')
                captured.append(dict(original_cash_projected_ast_sha256=hashlib.sha256(ast.dump(before).encode()).hexdigest(),
                    diagnostic_cash_projected_ast_sha256=hashlib.sha256(ast.dump(node).encode()).hexdigest(),
                    original_assertion_predicate_ast_sha256=hashlib.sha256(predicate.encode()).hexdigest(),
                    original_predicate_unchanged=True,reverse_restoration_exact=True,raise_replacement_count=1,
                    original_arithmetic_order_and_gate_unchanged=True,allowed_scalar_fields=list(INVARIANT_SCALAR_FIELDS)))
                return compile(node,*args,**kwargs)
            return compile(tree,*args,**kwargs)
        bound=_rebind(original_projector,{**original_projector.__globals__,'compile':diagnostic_compile})
        function,lineage=bound(rules,usable_a);require(len(captured)==1,'EXACTLY_ONE_FINAL_CASH_DIAGNOSTIC_PROJECTION_REQUIRED')
        function=_rebind(function,{**function.__globals__,'_account_invariant_scalar_exception':_account_invariant_scalar_exception})
        lineage=dict(lineage,original_cash_adapter_ast_sha256=lineage['adapter_ast_sha256'],
            adapter_ast_sha256=captured[0]['diagnostic_cash_projected_ast_sha256'],account_invariant_diagnostic=captured[0])
        return function,lineage
    return _rebind(entry,{**entry.__globals__,'_project_engine':projector})


def private_shareholder(route, native, *, old_trp_fingerprints, freeze_ref):
    proxy = cad.private_shareholder_namespace(native, old_trp_fingerprints=old_trp_fingerprints)
    ns = proxy.make_task_authority.__globals__
    original_metadata = inputs.account._metadata_ref
    def metadata_ref(ref, *, scope=False, child=False):
        require(isinstance(ref,dict) and set(ref)=={'path','sha256'}, 'PRIVATE_CONSUMER_EXACT_METADATA_REF_REQUIRED')
        if canonical(ref) == canonical(freeze_ref):
            require(not scope and _metadata(ref,('schema','task_id')) == dict(schema=route['schema'],task_id=routing.engine.TASK), 'PRIVATE_CONSUMER_FREEZE_METADATA_REQUIRED'); return canonical(ref)
        if canonical(ref) == route['reader_scope_ref']:
            require(scope and _metadata(ref,('schema','task_id')) == dict(schema=CONTINUATION_READER_SCHEMA if route['schema']==CONTINUATION_SCHEMA else READER_SCHEMA,task_id=routing.engine.TASK), 'PRIVATE_CONSUMER_READER_SCOPE_METADATA_REQUIRED'); return canonical(ref)
        return original_metadata(ref,scope=scope,child=child)
    def foreign_scope(authority):
        require(authority.get('account_fx_convention_scope_ref') == inputs.account.FX_CONVENTION_REF
            and authority.get('fx_source_availability_qualification_ref') == route['fx_qualification_ref'], 'PRIVATE61_AUTHORITY_EXPLICIT272_FX_REF_REQUIRED')
        old = dict(authority, fx_source_availability_qualification_ref=inputs.account.FX_AVAILABILITY_REF)
        inputs.account._validate_foreign_cash_scopes(old)
        _fx_metadata(route)
    ns.update(_metadata_ref=metadata_ref, _validate_foreign_cash_scopes=foreign_scope)
    if route.get('execution_invariant_scalar_diagnostic_authorized') is True:
        ns['run_cash_account']=_cash_invariant_diagnostic_entry(ns['run_cash_account'])
    proxy._metadata_ref=metadata_ref; proxy._validate_foreign_cash_scopes=foreign_scope
    require(proxy.make_task_authority.__globals__ is ns and proxy.run_shareholder_cash_account.__globals__ is ns
        and proxy.run_shareholder_cash_account.__globals__['validate_task_authority'] is proxy.validate_task_authority,
        'PRIVATE_CONSUMER_TWO_AUTHORITY_ENTRY_VALIDATORS_REQUIRED')
    for name in ('make_task_authority', 'run_shareholder_cash_account'):
        ns[name] = _guarded_execution(route, ns[name]); setattr(proxy, name, ns[name])
    return proxy


def private_inputs(route, proxy, connector):
    if route['schema']==CONTINUATION_SCHEMA:
        _validate_connector(route,connector,expected_projection(route['expected_freeze_ref'],source_roles=route['source_roles']))
    routed = routing._source_inputs_namespace({})
    ns = dict(vars(routed)); ns.update(account=proxy,_routing_connect_supplements=connector,
        _consumer_fx_qualification_ref=lambda:route['fx_qualification_ref'],
        _consumer_source_bound=lambda bound:exact_risk_code_source_bound(bound,transport_ref=route.get('source_code_transport_ref')))
    tree = ast.parse(Path(inputs.__file__).read_text(encoding='utf-8'))
    original = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='load_account_inputs')
    node = copy.deepcopy(original)
    anchor = [i for i,n in enumerate(node.body) if isinstance(n,ast.Expr) and any(isinstance(x,ast.Constant) and x.value=='TYPED_ACCOUNT_FACT_SCOPE_CHANGED' for x in ast.walk(n))]
    require(len(anchor)==1,'PRIVATE_CONSUMER_INPUT_AST_ANCHOR_CHANGED')
    node.body[anchor[0]:anchor[0]] = ast.parse('combined, composition = _routing_connect_supplements(combined, composition, bound, original_owner, original)').body
    refs = [n for n in ast.walk(node) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='completion_refs' for t in n.targets) and isinstance(n.value,ast.Call)]
    require(len(refs)==1,'PRIVATE_CONSUMER_FX_AUTHORITY_METADATA_AST_ANCHOR_CHANGED')
    kw=next(k for k in refs[0].value.keywords if k.arg=='fx_source_availability_qualification_ref');before=copy.deepcopy(kw.value)
    kw.value=ast.parse('_consumer_fx_qualification_ref()',mode='eval').body
    restored=copy.deepcopy(node); restored.body.pop(anchor[0]);rrefs=[n for n in ast.walk(restored) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='completion_refs' for t in n.targets) and isinstance(n.value,ast.Call)]
    next(k for k in rrefs[0].value.keywords if k.arg=='fx_source_availability_qualification_ref').value=before
    require(ast.dump(restored,include_attributes=False)==ast.dump(original,include_attributes=False),'PRIVATE_CONSUMER_INPUT_BUSINESS_AST_CHANGED')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),inputs.__file__,'exec'),ns)
    ns['_private_original_metadata_preflight'] = _rebind(inputs.metadata_preflight,ns)
    ns['_private_original_load_account_inputs'] = ns['load_account_inputs']
    def input_entry_guard(freeze_ref,source_ref):
        run,_=validate(route,execute=True)
        if route['schema']==CONTINUATION_SCHEMA:
            _validate_connector(route,connector,expected_projection(route['expected_freeze_ref'],source_roles=route['source_roles']))
            require(freeze_ref==routing.file_ref(run/_freeze_name(route)) and source_ref==route['reader_scope_ref'], 'DYNAMIC_INPUT_EXACT_NEW_FREEZE_AND_READER_REQUIRED')
    ns['_consumer_input_entry_guard'] = input_entry_guard
    wrapper = ('def metadata_preflight(*,frozen_contract_ref,source_scope_ref):\n'
        ' _consumer_input_entry_guard(frozen_contract_ref,source_scope_ref)\n'
        ' return _private_original_metadata_preflight(frozen_contract_ref=frozen_contract_ref,source_scope_ref=source_scope_ref)\n'
        'def load_account_inputs(bound,*,signal_adv_by_key):\n'
        " _consumer_input_entry_guard(bound.get('frozen_contract_ref'),bound.get('source_scope_ref'))\n"
        ' return _private_original_load_account_inputs(_consumer_source_bound(bound),signal_adv_by_key=signal_adv_by_key)\n')
    exec(compile(wrapper,__file__,'exec'),ns)
    return SimpleNamespace(**ns)


def bind_runner(route, freeze_ref, *, native, old_trp_fingerprints, connector):
    """Compile routing only; no actual source, quote, forecast or run is loaded."""
    run,expected=validate(route)
    if route['schema']==CONTINUATION_SCHEMA: _validate_connector(route,connector,expected)
    require(Path(freeze_ref['path']).resolve()==run/_freeze_name(route),'PRIVATE_CONSUMER_EXACT_NEW_FREEZE_PATH_REQUIRED')
    proxy=private_shareholder(route,native,old_trp_fingerprints=old_trp_fingerprints,freeze_ref=freeze_ref)
    source_inputs=private_inputs(route,proxy,connector)
    ns=dict(vars(routing.engine)); ns.update(shareholder=proxy,account_inputs=source_inputs)
    ns['_routing_origin']=lambda value:routing.FROZEN_ORIGIN if Path(value).resolve()==run else Path(value).resolve()
    ns['_routing_feature_origin']=lambda value:routing.FEATURE_ORIGIN if Path(value).resolve()==run else routing.engine.fusion.reader_run(value)
    carryover=_risk_fit_carryover(route,run)
    _equal_repair_metadata(route,run,carryover)
    ns['_no_new_risk_fit']=route.get('no_new_risk_fit') is True
    ns['_carryover_fit_started']=lambda token:carryover is not None and token in carryover['started_tokens']
    ns['_routing_prior']=lambda value:(carryover['effective_prior_fit_units'] if carryover is not None else route['original_routing_metadata']['budget']['prior_fit_units']) if Path(value).resolve()==run else (_ for _ in ()).throw(ValueError('PRIVATE_CONSUMER_WRONG_OUTPUT_RUN'))
    changes={'recipe_for_run':[('Path(run).resolve()==fusion.CONTINUATION_RUN','_routing_origin(run)==fusion.CONTINUATION_RUN')],
        'published_forecasts':[('Path(run).resolve()==fusion.CONTINUATION_RUN','_routing_origin(run)==fusion.CONTINUATION_RUN'),('fusion.published_fusion_forecasts(run,method,year,reader)','fusion.published_fusion_forecasts(_routing_origin(run),method,year,reader)')],
        'make_policy':[("fusion.metadata(run/'CONTINUATION_SCOPE.json')['budget']['prior_fit_units'] if run==fusion.CONTINUATION_RUN else 0",'_routing_prior(run)')],
        'run_all':[('fusion.reader_run(run)','_routing_feature_origin(run)')]}
    if carryover is not None:
        changes['make_policy'].insert(0,("not any(e.get('event')=='FIT_STARTED' and e.get('reuse_tuple_sha256')==token for e in values._events(log))","not _carryover_fit_started(token) and not any(e.get('event')=='FIT_STARTED' and e.get('reuse_tuple_sha256')==token for e in values._events(log))"))
    if ns['_no_new_risk_fit']:
        changes['make_policy'].extend([
            ('values.digest(dict(source_pins=source_pins(),event=event))',
             "_reject_new_risk_fit() if _no_new_risk_fit else values.digest(dict(source_pins=source_pins(),event=event))"),
            ("pending.get('event',{}).get('method')==method",
             "not _no_new_risk_fit and pending.get('event',{}).get('method')==method")])
        def reject_fit():raise routing.engine.NotTestable('NO_NEW_RISK_FIT_CACHE_MISS')
        ns['_reject_new_risk_fit']=reject_fit
    nodes=[]
    for original in ast.parse(Path(routing.engine.__file__).read_text(encoding='utf-8')).body:
        if not isinstance(original,ast.FunctionDef): continue
        node=copy.deepcopy(original)
        for before,after in changes.get(node.name,()): node=routing._replace_expression(node,before,after)
        nodes.append(node)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),routing.engine.__file__,'exec'),ns)
    ns['source_pins']=routing.engine.source_pins
    ns['_risk_worker']=routing.engine._risk_worker
    def contract(value):
        require(Path(value).resolve()==run,'PRIVATE_CONSUMER_WRONG_OUTPUT_RUN');validate(route,execute=True)
        require(_metadata(freeze_ref,set(route))==route,'PRIVATE_CONSUMER_SAVED_FREEZE_CHANGED')
        return run,dict(route['original_routing_metadata'],account_source_scope_ref=route['reader_scope_ref']),canonical(freeze_ref)
    ns['contract']=contract
    require(ns['evaluate_flow'].__globals__['shareholder'] is proxy
        and ns['run_all'].__globals__['account_inputs'] is source_inputs
        and source_inputs.metadata_preflight.__globals__['account'] is proxy
        and source_inputs.load_account_inputs.__globals__['account'] is proxy
        and ns['_risk_worker'] is routing.engine._risk_worker,'PRIVATE_CONSUMER_SHARED_PROXY_AND_SPAWN_WORKER_REQUIRED')
    cache_context={}
    if route.get('method_matrix_scope_ref') is not None:
        # Expose the bound original E only to an evaluator adapter which must
        # reapply this exact route/cache guard to its resulting callable.
        ns['_matrix_evaluation_source']=ns['evaluate_flow']
        ns['_matrix_execution_guard']=lambda function:_guarded_execution(route,function,cache_context=cache_context)
    for name in ('evaluate_flow', 'freeze_selected_risk', 'make_policy', 'run_all', 'main',
                 'freeze_template', 'published_forecasts', 'qualified_vectors', 'unavailable_publication'):
        ns[name] = _guarded_execution(route, ns[name],cache_context=cache_context)
    return SimpleNamespace(**ns),dict(engine_routing_anchor_count=5+int(carryover is not None)+2*int(ns['_no_new_risk_fit']),input_source_hook_count=1,input_FX_metadata_hook_count=1,
        no_new_risk_fit_guard_count=2 if ns['_no_new_risk_fit'] else 0,
        input_business_AST_restored_exact=True,shared_private_shareholder_validator=True,
        original_spawn_worker_identity_preserved=True,actual_account_or_fit_run=False)


"""One exact frozen Joint owner, private engine/routing binding only; no data reads."""
from pathlib import Path
from types import SimpleNamespace
import sys
JOINT_57_SHA='57ae2b73bd187ea68c126e18ff52b8c06ab14bde98dceddb770bdc4414bf15d0'
JOINT_OPTIMIZED_SHA='bc00205c61dcb5a534062066f2b6a8442bef34bfedf00735f81026d8a973abaf'
COMPILER_SHA='960c4db21c1e179bb28cda17f055995ccaef41c72b1242458b8084b12edd6f8f'

def _historical_joint_routing(public_routing):
    canonical_engine=public_routing.engine
    paths=public_routing.resolve(canonical_engine.predictors.REPO)
    vendor=paths.cache_root/'_maintenance'/canonical_engine.TASK/'source_repair'/'vendor_api_gap_completion'
    logical=dict(path=str(paths.repo_root/'scripts/research/a2/inference/consensus_joint_policy.py'),sha256=JOINT_57_SHA)
    custody=dict(path=str(vendor/'source_custody'/('consensus_joint_policy_'+JOINT_57_SHA+'.py')),sha256=JOINT_57_SHA)
    compiler=dict(path=str(vendor/'allocator_template_performance/allocator_template_function_proposal_r3_empty_support.py'),sha256=COMPILER_SHA)
    actual=public_routing.file_ref(logical['path'])
    require(actual['sha256'] in (JOINT_57_SHA,JOINT_OPTIMIZED_SHA),'ONLY_EXACT_REVIEWED_JOINT_BYTES_ALLOWED')
    public_routing._pin(custody);compiler_path=public_routing._pin(compiler)
    old=inputs.existing._load_python(custody,'_consensus_private_frozen_joint_'+JOINT_57_SHA)
    old_class_call=old.ConsensusJointPolicy.__call__.__code__
    old_transition=old.allocate_transition.__code__
    # This registered module is private and task-owned; public Joint is untouched.
    exec(compile(compiler_path.read_text(encoding='utf-8'),str(compiler_path),'exec'),vars(old))
    require(old.ConsensusJointPolicy.__call__.__code__ is old_class_call
        and old.allocate_transition.__code__ is old_transition,'FROZEN_JOINT_NUMERICAL_BYTECODE_CHANGED')
    engine_ns=dict(vars(canonical_engine));engine_ns['joint']=old
    for name,function in tuple(engine_ns.items()):
        if isinstance(function,FunctionType) and function.__globals__ is vars(canonical_engine):
            engine_ns[name]=_rebind(function,engine_ns)
    original_pins=engine_ns['source_pins']
    def source_pins():
        pins=original_pins()
        require(pins['joint_policy']==custody,'EXACT_FROZEN_JOINT_CUSTODY_REQUIRED')
        pins['joint_policy']=copy.deepcopy(logical)
        current=canonical_engine.source_pins()
        require(current['joint_policy']['path']==logical['path'] and current['joint_policy']['sha256'] in (JOINT_57_SHA,JOINT_OPTIMIZED_SHA),'UNREVIEWED_CANONICAL_JOINT_CHANGE')
        require(set(current)==set(pins) and all(pins[k]==current[k] for k in pins if k!='joint_policy'),
            'OTHER_EVALUATION_OWNERS_CHANGED')
        return pins
    engine_ns['source_pins']=source_pins
    # Children retain the real canonical protected entry and numerical risk owner.
    engine_ns['_risk_worker']=canonical_engine._risk_worker
    frozen_engine=SimpleNamespace(**engine_ns)
    route_ns=dict(vars(public_routing));route_ns['engine']=frozen_engine
    for name,function in tuple(route_ns.items()):
        if isinstance(function,FunctionType) and function.__globals__ is vars(public_routing):
            route_ns[name]=_rebind(function,route_ns)
    binding=dict(logical_joint_owner_ref=copy.deepcopy(logical),physical_joint_custody_ref=copy.deepcopy(custody),
        actual_allocator_compiler_ref=copy.deepcopy(compiler),canonical_risk_worker_unchanged=True,
        frozen_joint_transition_and_policy_bytecode_unchanged=True,
        allocator_empty_support_normalization_guard_count=2,nonempty_support_normalization_expressions_unchanged=True)
    return SimpleNamespace(**route_ns),canonical_engine,binding

def _historical_joint_final_owner(public_final,frozen_engine,binding):
    # Optional existing final-closure entry; no result/model/state is read here.
    ns=dict(vars(public_final));ns['evaluation']=frozen_engine
    for name,function in tuple(ns.items()):
        if isinstance(function,FunctionType) and function.__globals__ is vars(public_final):
            ns[name]=_rebind(function,ns)
    original_pin=ns['_pin'];logical=copy.deepcopy(binding['logical_joint_owner_ref']);custody=copy.deepcopy(binding['physical_joint_custody_ref'])
    def pin(record,expected=None):
        if Path(record['path']).resolve()==Path(logical['path']).resolve():
            require(record==logical and (expected is None or Path(expected).resolve()==Path(logical['path']).resolve()),
                'ONLY_EXACT_FROZEN_JOINT_LOGICAL_PIN_ALLOWED')
            return original_pin(custody,Path(custody['path']))
        return original_pin(record,expected)
    ns['_pin']=pin
    return SimpleNamespace(**ns)

CANONICAL_ENGINE=routing.engine
routing,CANONICAL_ENGINE,JOINT_EXECUTION_BINDING=_historical_joint_routing(routing)
