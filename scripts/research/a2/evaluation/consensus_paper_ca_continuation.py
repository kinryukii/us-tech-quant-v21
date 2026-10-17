"""One authorized MAIN cash continuation; the frozen driver remains immutable.

This adapter changes only the expressly named source/account admission. The
original predictors, selectors, account math, lifecycle, locks and resource
checks retain their owners. Default frozen execution does not import this file.
"""
from __future__ import annotations
import ast
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import importlib
import inspect
import json
from pathlib import Path
from functools import lru_cache
import textwrap
from types import FunctionType, SimpleNamespace

DRIVER_SHA = '2838947f5e08773ba6b38a748a8aa1983d92a1ddb81651e13350c6a9f2517193'
CASH_SHA = '3aafa77d7637e08032041d884bbd8ad03f6c7fe5e5d08996c51c3a87fa7b7398'
CASH_DEPENDENCY_SHA = '142c36633e47633fff5c9c63be030536fa7b1dba8a67f8432643c084f4dcdce4'
ADMISSION_SHA = 'b075d8d1baec3b0784fe0f7f5494ec19651d171a549993d50a6eef89d5cc717d'
FACTS_SHA = '9cb19e43f4d2f8eba52c16572a9d76ea7ca29826f082dea0c2798c8b98f91cb3'
DECISION_SHA = '22389127115e919c525653a493ffc37f4d5156426ef400e867a31d1d8bc13392'
USER_MESSAGE = '01a1441d-83f1-7e10-b818-795b3daba6d4'
CARD = 'call_d7276351a4904662b912b8467c1e12c4'
SCHEMA = 'CONSENSUS_MAIN_FINITE_CA_ADMISSION_R1'
FACT_SCHEMA = 'CONSENSUS_MAIN_FINITE_NASDAQ_CASH_FACTS_R1'
PREFIX_SCHEMA = 'CONSENSUS_MAIN_FINITE_CA_ACCEPTED_PREFIX_R1'
SOURCE_SCOPE = 'FINITE_NASDAQ_MU_CASH_20261014'
SCOPE = dict(ticker='MU', code='US.MU', ex_date='2026-10-14', target_session='2026-10-15', accepted_prefix_end='2026-10-13')
TARGET16_ADMISSION_SHA = '46625e4a726089a1661680bd5a342dd6ef649cf4ef63457159e14439086bdc31'
TARGET16_DECISION_SHA = '6b0d1b68d8ad5b7dae9104d917dd58594fb23e9fbb1a0e932d7dce9675bf3965'
TARGET16_QUESTION_ITEM = ['request_user_input_async', 'call_94b0a9f1cd8d4a1bb9800720b8857f2e', 0]
TARGET16_SCOPE = dict(SCOPE, target_session='2026-10-16', accepted_prefix_end='2026-10-15')
LEGACY_ADAPTER_EVIDENCE = dict(path='D:/us-tech-quant-results/_maintenance/DEMO_STRATEGY_CATALOG_SHOWCASE_20261017_R1/finite_main_target16/accepted_target15_adapter.py.before',
    sha256='d8121308382122278c5553676e52444c91d386eacba5901b5cc3113ec8a574a0')
_SEAL = object()


@lru_cache(maxsize=1)
def _owner():
    owner = importlib.import_module('scripts.research.a2.evaluation.consensus_paper_performance')
    owner.need(owner.reference(owner.__file__)['sha256'] == DRIVER_SHA, 'FINITE_CA_FROZEN_DRIVER_CHANGED')
    return owner


def _cash_runtime():
    # Reuse the original release's exact CA first-import phase. Its original
    # installer rejects any preloaded other instance and checks code identity.
    # Metadata qualification need not initialize CBC/account/model modules.
    owner = _owner()
    release = owner.projected_metadata(owner.R7_RELEASE, ('runtime_bootstrap_ref',))
    bootstrap = owner.load_original_owner(release['runtime_bootstrap_ref'], '_finite_ca_original_cash_runtime')
    source = bootstrap.load(bootstrap.CA_HELPER_REF, '_finite_ca_original_cash_source')
    return source.install_before_financial_imports(bootstrap.CA_PROOF_REF, context_task_id=bootstrap.TASK)


def _cash():
    # Source adjudication keeps its exact pure implementation without importing
    # current CA classes into the original account's canonical namespace.
    _cash_runtime()
    import copy
    import math
    import re
    import pandas as pd
    owner = _owner(); root = Path(owner.__file__).resolve().parents[4]
    cash_path = root / 'scripts/research/a2/data/joint_cash_bindings.py'
    dependency_path = root / 'scripts/v22/corporate_action_transition_r1.py'
    cash_ref = owner.reference(cash_path); dependency_ref = owner.reference(dependency_path)
    owner.need(cash_ref['sha256'] == CASH_SHA, 'FINITE_CA_CASH_OWNER_CHANGED')
    owner.need(dependency_ref['sha256'] == CASH_DEPENDENCY_SHA, 'FINITE_CA_CASH_DEPENDENCY_CHANGED')
    function_names = {'_hash', '_sha', '_guard', 'normal_cash_ex_date', 'adjudicate_post_verified_cash_ex'}
    constant_names = {'SPEC', 'NSCC_CNS_BANK_HOLIDAY_RECORD_RESEARCH',
        'NYSE_RULE235_POST_T1_NONBUSINESS_RESEARCH', 'NYSE_RULE235_PRE_T1_NONBUSINESS_RESEARCH'}
    dependency_names = {'canonical_bytes', 'RAW_OLD_SHARE_COORDINATE', 'USD_PER_RAW_OLD_SHARE',
        'CLOSED_RECORD_RESEARCH_POLICY', 'CLOSED_RECORD_RESEARCH_ROLE'}
    def select(path, names):
        tree = ast.parse(path.read_bytes(), filename=str(path)); selected = []; found = []
        for node in tree.body:
            name = (node.name if isinstance(node, ast.FunctionDef) else node.targets[0].id
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) else None)
            if name in names: selected.append(node); found.append(name)
        owner.need(len(found) == len(names) and set(found) == names, 'FINITE_CA_CASH_PURE_SOURCE_ABI_CHANGED')
        return selected
    namespace = dict(__name__=__name__ + '._cash_source', __file__=str(cash_path),
        copy=copy, hashlib=hashlib, math=math, re=re, pd=pd, json=json)
    for path, names in ((dependency_path, dependency_names), (cash_path, function_names | constant_names)):
        nodes = select(path, names)
        future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
        projection = ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[]))
        exec(compile(projection, str(path), 'exec'), namespace)
    owner.verified(cash_ref); owner.verified(dependency_ref)
    return SimpleNamespace(__file__=str(cash_path), _hash=namespace['_hash'],
        adjudicate_post_verified_cash_ex=namespace['adjudicate_post_verified_cash_ex'],
        dependency_ref=dependency_ref, projection=dict(functions=sorted(function_names),
            constants=sorted(constant_names), dependency_nodes=sorted(dependency_names),
            original_function_ast_unchanged=True, account_class_nodes_loaded=0))


def _clone(fn, **bindings):
    namespace = dict(fn.__globals__); namespace.update(bindings)
    result = FunctionType(fn.__code__, namespace, fn.__name__, fn.__defaults__, fn.__closure__)
    result.__kwdefaults__ = fn.__kwdefaults__
    return result


def _read(ref, limit=65536):
    owner = _owner(); owner._ca_locator_ref(ref)
    path = owner.verified(ref)
    owner.need(path.stat().st_size <= limit, 'FINITE_CA_DOCUMENT_BOUND')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            owner.need(key not in result, 'FINITE_CA_DUPLICATE_KEY'); result[key] = value
        return result
    with path.open('rb') as stream: raw = stream.read(limit + 1)
    owner.need(len(raw) <= limit, 'FINITE_CA_DOCUMENT_BOUND')
    def reject(value): raise ValueError('FINITE_CA_NONFINITE_JSON')
    result = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    owner.verified(ref)
    owner.need(isinstance(result, dict), 'FINITE_CA_OBJECT_REQUIRED')
    return result


def _static(ref, as_of):
    owner = _owner()
    owner.need(isinstance(ref, dict) and ref.get('sha256') in (ADMISSION_SHA, TARGET16_ADMISSION_SHA), 'FINITE_CA_EXACT_ADMISSION_COMMITMENT_REQUIRED')
    scope = TARGET16_SCOPE if ref['sha256'] == TARGET16_ADMISSION_SHA else SCOPE
    body = _read(ref)
    owner.need(body.get('facts_ref', {}).get('sha256') == FACTS_SHA, 'FINITE_CA_EXACT_FACT_COMMITMENT_REQUIRED')
    owner.need(body.get('schema') == SCHEMA and body.get('scope') == scope, 'FINITE_CA_EXACT_SCOPE_REQUIRED')
    auth = body.get('authorization', {})
    if scope == TARGET16_SCOPE:
        owner.need(auth.get('user_message_id') is None and auth.get('question_item_id') == TARGET16_QUESTION_ITEM
            and auth.get('decision_ref', {}).get('sha256') == TARGET16_DECISION_SHA, 'FINITE_CA_EXACT_HUMAN_DECISION_REQUIRED')
        authorization = _read(auth['receipt_ref'])
        owner.need(authorization.get('schema') == 'FINITE_MAIN_TARGET16_HUMAN_DECISION_R1'
            and authorization.get('proposal_ref') == auth['decision_ref']
            and authorization.get('question_item_id') == TARGET16_QUESTION_ITEM
            and authorization.get('answer') == '批准，仅续接到10/16（推荐）'
            and authorization.get('user_message_id') is None, 'FINITE_CA_EXACT_HUMAN_DECISION_REQUIRED')
        recorded = datetime.fromisoformat(authorization['recorded_at_utc'])
        owner.need(recorded.tzinfo is not None and recorded <= datetime.fromisoformat(str(as_of).replace('Z','+00:00')),
            'FINITE_CA_AUTHORIZATION_RECORD_AFTER_ASOF')
        owner.need(body.get('previous_admission_ref', {}).get('sha256') == ADMISSION_SHA,
            'FINITE_CA_ORIGINAL_ADMISSION_REQUIRED')
        previous, _ = _static(body['previous_admission_ref'], as_of)
        owner.need(body['facts_ref'] == previous['facts_ref']
            and body.get('original_prefix_manifest_ref') == previous['accepted_prefix_manifest_ref']
            and body.get('legacy_adapter_evidence_ref', {}).get('sha256') == LEGACY_ADAPTER_EVIDENCE['sha256'],
            'FINITE_CA_ORIGINAL_FACTS_AND_PREFIX_REQUIRED')
        owner.verified(body['legacy_adapter_evidence_ref'])
        _extended_calendar(body, _read(body['facts_ref'], 131072), as_of=as_of)
    else:
        owner.need(auth.get('user_message_id') == USER_MESSAGE and auth.get('card_id') == CARD
            and auth.get('decision_ref', {}).get('sha256') == DECISION_SHA, 'FINITE_CA_EXACT_HUMAN_DECISION_REQUIRED')
    owner.verified(auth['decision_ref'])
    owner.need(body.get('frozen_driver_ref') == owner.reference(owner.__file__), 'FINITE_CA_FROZEN_DRIVER_CHANGED')
    for key in ('publication_ref', 'capture_ref', 'daily_report_ref', 'accepted_prefix_manifest_ref', 'facts_ref'):
        owner._ca_locator_ref(body[key])
    stamp = datetime.fromisoformat(str(as_of).replace('Z', '+00:00'))
    owner.need(stamp.tzinfo is not None, 'FINITE_CA_AWARE_ASOF_REQUIRED')
    prefix = owner.projected_metadata(body['accepted_prefix_manifest_ref'],
        ('schema', 'status', 'end', 'candidate_ids', 'extensions', 'model_fit_calls', 'broker_action_allowed'))
    owner.need(prefix.get('schema') == 'CONSENSUS_FIXED_MAIN_PAPER_EXTENSION_MANIFEST_R1'
        and prefix.get('status') == 'PREFIX_VERIFIED_DESCRIPTIVE_EXTENSION'
        and prefix.get('end') == scope['accepted_prefix_end'] and prefix.get('candidate_ids') == list(owner.IDS)
        and set(prefix.get('extensions', {})) == set(owner.IDS)
        and prefix.get('model_fit_calls') == 0 and prefix.get('broker_action_allowed') is False,
        'FINITE_CA_ACCEPTED_13_PREFIX_REQUIRED')
    if scope == TARGET16_SCOPE:
        accepted = owner.projected_metadata(body['accepted_prefix_manifest_ref'], ('end','as_of','extensions'))
        receipts = {sid: owner.projected_metadata(item, ('source_refs',)) for sid,item in accepted['extensions'].items()}
        proof = validate_published_continuation(None, manifest_ref=body['accepted_prefix_manifest_ref'],
            manifest=accepted, completion_receipts=receipts)
        owner.need(proof['admission_ref'] == body['previous_admission_ref'], 'FINITE_CA_ACCEPTED_15_ORIGINAL_IDENTITY_REQUIRED')
    return body, prefix


def _extended_calendar(body, capsule, *, as_of, current=None):
    """Keep the old facts calendar; prove only its one-session extension."""
    owner = _owner(); proof = _read(body['calendar_extension_ref'])
    calendar = proof.get('calendar_qualification', {})
    recorded = calendar.get('as_of_utc')
    owner.validate_calendar_proof(calendar, recorded, TARGET16_SCOPE['target_session'])
    owner.need(datetime.fromisoformat(recorded.replace('Z','+00:00')) <= datetime.fromisoformat(str(as_of).replace('Z','+00:00')),
        'FINITE_CA_CALENDAR_PROOF_AFTER_ASOF')
    owner.need(proof.get('schema') == 'FINITE_MAIN_TARGET16_CALENDAR_EXTENSION_R1'
        and proof.get('facts_ref') == body['facts_ref'] and proof.get('previous_admission_ref') == body['previous_admission_ref']
        and proof.get('legacy_calendar_session_count') == len(capsule['calendar'])
        and proof.get('legacy_calendar_end') == capsule['calendar'][-1] == SCOPE['target_session']
        and proof.get('legacy_calendar_binding') == capsule['calendar_binding']
        and proof.get('legacy_session_dates_sha256') == hashlib.sha256(owner.canonical(capsule['calendar']).encode()).hexdigest()
        and calendar['main_sessions'] == capsule['calendar'] + [TARGET16_SCOPE['target_session']],
        'FINITE_CA_EXACT_CALENDAR_EXTENSION_REQUIRED')
    if current is not None:
        owner.validate_calendar_proof(current, as_of, TARGET16_SCOPE['target_session'])
        owner.need({k:v for k,v in current.items() if k != 'as_of_utc'} ==
            {k:v for k,v in calendar.items() if k != 'as_of_utc'}, 'FINITE_CA_CURRENT_CALENDAR_CHANGED')
    return calendar


def adjudicate_finite_nasdaq_cash(capsule, facts_ref, *, source_scope=SOURCE_SCOPE):
    """Pinned original source adjudicator with one explicit finite venue seam.

    The source payload stays NASDAQ. The original date arithmetic and all its
    cash, exception, source, unit, raw-close and publication checks are retained.
    Nasdaq applicability is separately source bound; no NYSE listing is invented.
    """
    owner = _owner(); cash = _cash(); facts = capsule['facts']; refs = capsule['source_refs']
    owner.need(source_scope == SOURCE_SCOPE and capsule.get('schema') == FACT_SCHEMA, 'FINITE_CA_NASDAQ_SCOPE_REQUIRED')
    owner.need(facts.get('ticker') == 'MU' and facts.get('listing_identity') == 'NASDAQ:MU'
        and facts.get('vendor_named_ex_date') == SCOPE['ex_date']
        and facts.get('record_date') == SCOPE['ex_date'] and facts.get('available_at') is None
        and facts.get('clock_role') == 'POST_VERIFIED_ACCOUNTING_ONLY', 'FINITE_CA_EXACT_EVENT_REQUIRED')
    names = ('issuer_cash', 'security_identity', 'nasdaq_applicability', 'finra_rule', 'vendor_event', 'prior_raw_close')
    owner.need(set(refs) == set(names), 'FINITE_CA_SIX_SOURCE_BINDINGS_REQUIRED')
    for ref in refs.values(): owner._ca_locator_ref(ref)
    owner.need(facts['issuer_source_fingerprint'] == refs['issuer_cash']['sha256']
        and facts['identity_source_fingerprint'] == refs['security_identity']['sha256']
        and facts['vendor_source_fingerprint'] == refs['vendor_event']['sha256']
        and facts['prior_raw_close']['source_fingerprint'] == refs['prior_raw_close']['sha256'],
        'FINITE_CA_FACT_SOURCE_BINDING_CHANGED')
    rule = capsule['rule_sources']['TPLUS1']
    owner.need(rule['source_fingerprint'] == refs['finra_rule']['sha256'], 'FINITE_CA_RULE_SOURCE_CHANGED')
    applicability = capsule['nasdaq_applicability']
    owner.need(applicability == dict(listing_identity='NASDAQ:MU', source_ref=refs['nasdaq_applicability'],
        effective_from='2024-05-28', normal_cash_ex_equals_record=True), 'FINITE_CA_NASDAQ_APPLICABILITY_REQUIRED')
    source = textwrap.dedent(inspect.getsource(cash.adjudicate_post_verified_cash_ex)); tree = ast.parse(source)
    matches = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.NotIn)
                and ast.unparse(node.left) == "facts.get('listing_identity')"):
            matches.append(node)
    owner.need(len(matches) == 1, 'FINITE_CA_VENUE_SEAM_CHANGED')
    original = deepcopy(tree)
    matches[0].comparators = [ast.parse("('NASDAQ:' + facts['ticker'],)", mode='eval').body]
    namespace = dict(cash.adjudicate_post_verified_cash_ex.__globals__)
    exec(compile(ast.fix_missing_locations(tree), cash.__file__, 'exec'), namespace)
    envelope = dict(path=facts_ref['path'], sha256=facts_ref['sha256'], payload=deepcopy(facts),
        guard=dict(status='HASH_VERIFIED_PAYLOAD', path=facts_ref['path'], sha256=facts_ref['sha256'], payload_sha256=cash._hash(facts)))
    result = namespace['adjudicate_post_verified_cash_ex'](envelope, calendar=capsule['calendar'],
        calendar_binding=capsule['calendar_binding'], rule_sources=capsule['rule_sources'],
        scope_end_exclusive='2027-01-01', source_scope='US_2026_SOURCE_ONLY')
    owner.need(result.get('status') == 'ADJUDICATED_RESEARCH_EX_DATE' and result.get('ex_date') == SCOPE['ex_date'],
        'FINITE_CA_SOURCE_ADJUDICATION_BLOCKED:' + str(result.get('reason')))
    result.update(finite_source_scope=source_scope, source_admission_changed=True, cash_owner_ref=owner.reference(cash.__file__),
        cash_dependency_ref=cash.dependency_ref, cash_source_projection=deepcopy(cash.projection),
        source_projection_seam='EXACT_MU_20261014_NASDAQ_LISTING_MEMBERSHIP_ONLY',
        original_function_ast_sha256=hashlib.sha256(ast.dump(original, include_attributes=False).encode()).hexdigest(),
        projected_function_ast_sha256=hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest(),
        nasdaq_applicability_ref=refs['nasdaq_applicability'], generic_source_owner_unchanged=True)
    return result


def _event(body, capsule):
    _cash_runtime()
    from scripts.v22.corporate_action_transition_r1 import ResearchReconstructedCashEvent
    f = capsule['facts']; ref = body['facts_ref']; src = capsule['source_refs']['issuer_cash']
    return ResearchReconstructedCashEvent(event_id='FINITE_MAIN_CASH:MU:2026-10-14', action_type='CASH_DIVIDEND',
        old_security_id=f['security_id'], ticker='MU', ex_date=SCOPE['ex_date'], record_date=f['record_date'],
        pay_date=f['pay_date'], available_at=None, cash_per_old_share=f['cash_per_raw_share'], currency='USD',
        amount_unit='USD_PER_RAW_OLD_SHARE', quantity_coordinate='RAW_OLD_SECURITY_SHARES',
        source_type='TIER1_ISSUER_REGULATOR_EXCHANGE', source_reference=src['path'], source_fingerprint=src['sha256'],
        reconstruction_ref=ref['path'], reconstruction_sha256=ref['sha256'], clock_role='POST_VERIFIED_ACCOUNTING_ONLY')


def qualify_admission(paths, finite_ca_admission_ref, *, as_of, preflight=None):
    owner = _owner(); body, prefix = _static(finite_ca_admission_ref, as_of); scope = body['scope']
    if preflight is None:
        calendar = owner.completed_calendar(paths, as_of)
        capture = owner.resolve_current_capture(paths, calendar)
        preflight = owner.metadata_preflight(paths, capture_ref=capture, as_of=as_of)
    owner.need(preflight['end'] == scope['target_session'] and preflight['publication_ref'] == body['publication_ref']
        and preflight['capture_ref'] == body['capture_ref'], 'FINITE_CA_CURRENT_INPUT_BINDING_CHANGED')
    source = owner._current_quote_source(paths, preflight['document'], preflight['end'], as_of)
    owner.need(source['report_ref'] == body['daily_report_ref'], 'FINITE_CA_CURRENT_REPORT_CHANGED')
    capsule = _read(body['facts_ref'], 131072)
    adjudication = adjudicate_finite_nasdaq_cash(capsule, body['facts_ref'])
    if scope == TARGET16_SCOPE:
        calendar = _extended_calendar(body, capsule, as_of=as_of, current=preflight['calendar_qualification'])
        extended = deepcopy(capsule); extended['calendar'] = calendar['main_sessions']
        extended['calendar_binding'] = dict(status='SOURCE_BOUND_LEGAL_SESSION_CALENDAR',
            session_dates_sha256=_cash()._hash(extended['calendar']),
            source_reference=calendar['calendar_ref']['path'], source_fingerprint=calendar['calendar_ref']['sha256'])
        checked = adjudicate_finite_nasdaq_cash(extended, body['facts_ref'])
        owner.need({k:v for k,v in checked.items() if k != 'calendar_binding'} ==
            {k:v for k,v in adjudication.items() if k != 'calendar_binding'}, 'FINITE_CA_EVENT_CHANGED_WITH_CALENDAR_EXTENSION')
    else:
        owner.need(capsule['calendar'] == preflight['calendar_qualification']['main_sessions'], 'FINITE_CA_CALENDAR_CHANGED')
    event = _event(body, capsule)
    return dict(status='FINITE_CA_ADMISSION_QUALIFIED_NOT_REPLAY', admission_ref=deepcopy(finite_ca_admission_ref),
        admitted_event_terms={'US.MU': [SCOPE['ex_date']]}, end=scope['target_session'],
        accepted_prefix_end=scope['accepted_prefix_end'], accepted_prefix_manifest_ref=body['accepted_prefix_manifest_ref'],
        event_fingerprint=event.event_fingerprint, source_adjudication=adjudication,
        broker_action_allowed=False, models_loaded=0, model_fit_calls=0, account_replays=0)


def metadata_preflight(paths, *, capture_ref, as_of, finite_ca_admission_ref):
    owner = _owner(); result = owner.metadata_preflight(paths, capture_ref=capture_ref, as_of=as_of)
    result['finite_ca_admission'] = qualify_admission(paths, finite_ca_admission_ref, as_of=as_of, preflight=result)
    return result


@dataclass(frozen=True)
class FiniteCAAuthority:
    base: object
    admission_ref: dict
    event: object
    seal: object
    def __getattr__(self, name): return getattr(self.base, name)


def _authority(value):
    owner = _owner()
    owner.need(type(value) is FiniteCAAuthority and value.seal is _SEAL, 'FINITE_CA_AUTHORITY_REQUIRED')
    owner._authority(value.base)
    return value


def validate_descriptive_input_dates(authority, dates, *, feature_context=False):
    return _clone(_owner().validate_descriptive_input_dates, _authority=_authority)(authority, dates, feature_context=feature_context)


def require_descriptive_decision(authority, date, path_id=None, **kwargs):
    return _clone(_owner().require_descriptive_decision, validate_descriptive_input_dates=validate_descriptive_input_dates)(authority, date, path_id, **kwargs)


def validate_descriptive_account(authority, dates, path_ids, account_config, execution_friction):
    return _clone(_owner().validate_descriptive_account, validate_descriptive_input_dates=validate_descriptive_input_dates)(authority, dates, path_ids, account_config, execution_friction)


def validate_account_friction(value, ids, friction):
    if type(value) is not FiniteCAAuthority: return _owner().validate_account_friction(value, ids, friction)
    value = _authority(value)
    _owner().need(tuple(ids) == value.allowed_path_ids and _owner().canonical(friction) == value.friction_json, 'FINITE_CA_ECONOMICS_CHANGED')
    return value


def validate_reconstructed_accounting_events(authority, events, *, require_exact=False):
    value = _authority(authority); events = tuple(events); expected = value.event
    new = [e for e in events if getattr(e, 'event_fingerprint', None) == expected.event_fingerprint]
    _owner().need(len(new) <= 1 and (not require_exact or len(new) == 1), 'FINITE_CA_EXACT_NEW_EVENT_REQUIRED')
    for e in new:
        e.__post_init__(); _owner().need(type(e) is type(expected) and e == expected, 'FINITE_CA_TYPED_EVENT_CHANGED')
    old = tuple(e for e in events if e not in new)
    _owner().validate_reconstructed_accounting_events(value.base, old, require_exact=require_exact)
    return value


def _raw_projection(admission_ref, capsule):
    owner = _owner(); source = textwrap.dedent(inspect.getsource(owner.prepare_raw_quote_extension)); tree = ast.parse(source)
    seen = dict(terms=0, capture=0, count=0, schema=0)
    class Project(ast.NodeTransformer):
        def visit_Expr(self, node):
            if (isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == 'need' and len(node.value.args) == 2):
                condition = ast.unparse(node.value.args[0])
                if condition == "not ca['typed_event_terms_required']":
                    seen['terms'] += 1
                    return ast.copy_location(ast.parse('_finite_terms_gate(ca)').body[0], node)
                if condition == 'events.empty':
                    seen['capture'] += 1
                    return ast.copy_location(ast.parse('_finite_capture_gate(events)').body[0], node)
            return self.generic_visit(node)
        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id == 'dict':
                for kw in node.keywords:
                    if kw.arg == 'current_in_scope_ca_event_count' and isinstance(kw.value, ast.Constant) and kw.value.value == 0:
                        kw.value = ast.Constant(1); seen['count'] += 1
                    if kw.arg == 'schema' and isinstance(kw.value, ast.Constant) and kw.value.value == 'CONSENSUS_FIXED_MAIN_RAW_QUOTE_EXTENSION_R1':
                        kw.value = ast.Constant('CONSENSUS_FIXED_MAIN_FINITE_CA_RAW_QUOTE_EXTENSION_R1'); seen['schema'] += 1
            return self.generic_visit(node)
    tree = Project().visit(tree)
    owner.need(seen == dict(terms=1, capture=1, count=1, schema=1), 'FINITE_CA_RAW_SOURCE_SEAMS_CHANGED')
    def terms(ca):
        owner.need(ca['typed_event_terms_required'] == {'US.MU': [SCOPE['ex_date']]}
            and ca.get('finite_ca_admission_ref') == admission_ref and not ca['missing_codes'], 'FINITE_CA_UNADMITTED_EVENT')
    def capture(events):
        import pandas as pd
        expected = capsule['capture_event_binding']
        owner.need(expected.get('ticker') == 'MU' and expected.get('event_date') == SCOPE['ex_date']
            and expected.get('share_event') is False and expected.get('row_count') == 1, 'FINITE_CA_CAPTURE_BINDING_REQUIRED')
        owner.need(len(events) == 1 and set(events.columns) == {'ticker','event_date','audit_kind','share_event'}, 'FINITE_CA_CAPTURE_EVENT_SET_CHANGED')
        row = events.iloc[0]
        owner.need(str(row.ticker) == 'MU' and str(pd.Timestamp(row.event_date).date()) == SCOPE['ex_date']
            and row.audit_kind == expected['audit_kind'] and not pd.isna(row.share_event) and bool(row.share_event) is False,
            'FINITE_CA_CAPTURE_EVENT_CHANGED')
    def qualify(*args, **kwargs):
        tail, proof = owner.qualify_current_tail(*args, **kwargs)
        ca = proof['ca_qualification']; terms(deepcopy(ca) | {'finite_ca_admission_ref': admission_ref})
        owner.need(not proof['missing_raw_dates'], 'FINITE_CA_RAW_SOURCE_GAP')
        proof = deepcopy(proof); proof['status'] = 'READY'
        proof['ca_qualification'].update(status='READY', finite_ca_admission_ref=deepcopy(admission_ref), finite_source_admission=True)
        proof['finite_ca_admission_ref'] = deepcopy(admission_ref)
        proof['source_admission_changed'] = True
        return tail, proof
    namespace = dict(owner.prepare_raw_quote_extension.__globals__, qualify_current_tail=qualify,
        _finite_terms_gate=terms, _finite_capture_gate=capture)
    exec(compile(ast.fix_missing_locations(tree), owner.__file__, 'exec'), namespace)
    return namespace['prepare_raw_quote_extension']


def _prepare(paths, sid, preflight, qualified, admission_ref, capsule, event, runtime_custody_ref=None):
    import pandas as pd
    owner = _owner()
    prepared, flags = owner._prepare_candidate(paths, sid, preflight, qualified, runtime_custody_ref)
    for day in (SCOPE['accepted_prefix_end'], SCOPE['ex_date']):
        owner.need(prepared['sid_by_key'].get((pd.Timestamp(day), 'MU')) == event.old_security_id,
            'FINITE_CA_ORIGINAL_ACCOUNT_SECURITY_CHANGED')
    source = deepcopy(prepared['account_source_kwargs']); old_events = tuple(source['entitlement_events'])
    owner.need(not any(getattr(e, 'ticker', None) == 'MU' and str(getattr(e, 'ex_date', '')) == SCOPE['ex_date'] for e in old_events),
        'FINITE_CA_NEW_EVENT_ALREADY_IN_ORIGINAL_CATALOGUE')
    source['entitlement_events'] = (*old_events, event)
    identities = dict(source['entitlement_security_tickers'])
    owner.need(identities.get(event.old_security_id, 'MU') == 'MU'
        and not any(ticker == 'MU' and sid != event.old_security_id for sid,ticker in identities.items()),
        'FINITE_CA_ORIGINAL_SECURITY_ALIAS_CHANGED')
    identities[event.old_security_id] = 'MU'; source['entitlement_security_tickers'] = identities
    binding = deepcopy(source['entitlement_source_binding']); manifest = deepcopy(binding.get('manifest', {}))
    manifest['finite_ca_continuation'] = dict(admission_ref=admission_ref, event_fingerprint=event.event_fingerprint,
        original_source_binding=deepcopy(binding), original_catalogue_order_preserved=True)
    binding.update(manifest=manifest, source_fingerprint=_cash()._hash(manifest), security_tickers=identities,
        event_fingerprints=[e.event_fingerprint for e in source['entitlement_events']])
    source['entitlement_source_binding'] = binding
    refs = dict(prepared['source_refs'], finite_ca_admission_ref=deepcopy(admission_ref), finite_ca_adapter_ref=owner.reference(__file__))
    provenance = json.loads(prepared['authority'].provenance_json)
    provenance.update(source_refs=refs, finite_ca_admission_ref=deepcopy(admission_ref), finite_accounting_admission_changed=True)
    base = replace(prepared['authority'], provenance_json=owner.canonical(provenance))
    prepared.update(source_refs=refs, account_source_kwargs=source,
        authority=FiniteCAAuthority(base, deepcopy(admission_ref), event, _SEAL))
    return prepared, flags


def _guard_projection(function, **bindings):
    return _clone(_owner().guard_projection, __name__=__name__)(function, **bindings)


def _prefix_receipt(paths, sid, frames, admission_ref, body):
    owner = _owner(); scope = body.get('scope', SCOPE); end = scope['accepted_prefix_end']
    next_session = scope['target_session'] if scope == TARGET16_SCOPE else SCOPE['ex_date']
    manifest = owner.projected_metadata(body['accepted_prefix_manifest_ref'], ('end','extensions'))
    completion_ref = manifest['extensions'][sid]
    meta = owner.projected_metadata(completion_ref, ('candidate_ids','end','artifacts'))
    owner.need(meta['end'] == end and meta['candidate_ids'] == [sid] and set(meta['artifacts']) == set(owner.LEDGER_TABLES),
        'FINITE_CA_ACCEPTED_PREFIX_COMPLETION_CHANGED')
    refs = meta['artifacts']
    core = _clone(owner.compare_prefix, PREFIX_END=end)(frames, refs, sid)
    # Exact original exception: final pending next-open metadata can mature;
    # targets, quantities and every other cell/schema remain byte-level exact.
    stocks = _clone(owner.compare_stock_prefix, PREFIX_END=end)(frames, refs, sid, next_execution_date=next_session)
    proof = dict(schema=PREFIX_SCHEMA, status='EXACT_ACCEPTED_PREFIX_WITH_ORIGINAL_PENDING_MATURITY',
        candidate_id=sid, end=end, finite_ca_admission_ref=deepcopy(admission_ref),
        accepted_prefix_manifest_ref=body['accepted_prefix_manifest_ref'], accepted_completion_ref=completion_ref,
        core_tables=core, stock_tables=stocks, adapter_ref=owner.reference(__file__))
    from scripts.common.storage_paths import assert_safe_output_path
    identity = hashlib.sha256(owner.canonical(proof).encode()).hexdigest()[:20]
    destination = paths.backtest_root/owner.TASK/'descriptive_main_extension'/'finite_ca_prefix'/identity/'PREFIX_COMPARISON.json'
    assert_safe_output_path(destination, kind='backtest', paths=paths); destination.parent.mkdir(parents=True, exist_ok=True)
    text = owner.canonical(proof) + '\n'
    if destination.exists(): owner.need(destination.read_text(encoding='utf8') == text, 'FINITE_CA_PRESERVE_PREFIX_RECEIPT')
    else: destination.write_text(text, encoding='utf8')
    return owner.reference(destination)


def validate_published_continuation(paths, *, manifest_ref, manifest, completion_receipts):
    """Historical verification only; never require today's latest source or fetch."""
    owner = _owner(); refs = []
    owner.need(set(completion_receipts) == set(owner.IDS), 'FINITE_CA_THREE_COMPLETIONS_REQUIRED')
    for sid, receipt in completion_receipts.items():
        refs.append(receipt.get('source_refs', {}).get('finite_ca_admission_ref'))
    owner.need(all(isinstance(ref, dict) and ref == refs[0] for ref in refs), 'FINITE_CA_PUBLICATION_ADMISSION_MISMATCH')
    body, prefix = _static(refs[0], manifest['as_of']); scope = body['scope']
    next_session = scope['target_session'] if scope == TARGET16_SCOPE else SCOPE['ex_date']
    owner.need(manifest.get('end') == scope['target_session'], 'FINITE_CA_PUBLICATION_CUTOFF_CHANGED')
    for sid, receipt in completion_receipts.items():
        source = receipt['source_refs']
        owner.need(source.get('current_publication') == body['publication_ref'], 'FINITE_CA_PUBLISHED_SOURCE_CHANGED')
        adapter_ref = source.get('finite_ca_adapter_ref')
        current_adapter = owner.reference(__file__)
        if scope == SCOPE and adapter_ref == dict(current_adapter, sha256=LEGACY_ADAPTER_EVIDENCE['sha256']):
            # Historical source custody: old refs stay unchanged; never use this snapshot for execution.
            owner.verified(LEGACY_ADAPTER_EVIDENCE)
        else:
            owner.need(adapter_ref == current_adapter, 'FINITE_CA_ADAPTER_IDENTITY_CHANGED')
        proof = _read(source['accepted_extension_prefix_comparison_ref'])
        owner.need(proof.get('schema') == PREFIX_SCHEMA
            and proof.get('status') == 'EXACT_ACCEPTED_PREFIX_WITH_ORIGINAL_PENDING_MATURITY'
            and proof.get('candidate_id') == sid and proof.get('end') == scope['accepted_prefix_end']
            and proof.get('finite_ca_admission_ref') == refs[0]
            and proof.get('accepted_prefix_manifest_ref') == body['accepted_prefix_manifest_ref']
            and proof.get('accepted_completion_ref') == prefix['extensions'][sid]
            and proof.get('adapter_ref') == adapter_ref, 'FINITE_CA_ACCEPTED_PREFIX_PROOF_CHANGED')
        expected = owner.projected_metadata(prefix['extensions'][sid], ('artifacts',))['artifacts']
        core = proof['core_tables']; stock = proof['stock_tables']
        owner.need(core.get('status') == 'EXACT_MATCH' and stock.get('status') == 'EXACT_CLOSED_PREFIX_WITH_PENDING_MATURITY'
            and set(core.get('table_comparisons', {})) == set(owner.TABLES)
            and set(stock.get('table_comparisons', {})) == set(owner.STOCK_TABLES), 'FINITE_CA_SIX_PREFIX_TABLES_REQUIRED')
        for name, check in {**core['table_comparisons'], **stock['table_comparisons']}.items():
            owner.need(check.get('original_ref') == expected[name], 'FINITE_CA_ACCEPTED_PREFIX_BASELINE_CHANGED')
            owner.verified(expected[name])
        for name, check in core['table_comparisons'].items():
            owner.need(check.get('status') == 'EXACT_MATCH', 'FINITE_CA_CORE_PREFIX_CHANGED')
        for name, check in stock['table_comparisons'].items():
            maturity = check.get('pending_maturity', {})
            allowed = ['planned_execution_date'] if name == 'actions' else ['execution_date','status']
            owner.need(check.get('status') == 'EXACT_CLOSED_PREFIX_WITH_PENDING_MATURITY'
                and check.get('unchanged_columns_status') == 'EXACT_MATCH'
                and maturity.get('signal_date') == scope['accepted_prefix_end']
                and maturity.get('next_execution_date') == next_session
                and maturity.get('allowed_columns') == allowed
                and type(maturity.get('changed_rows')) is int and maturity['changed_rows'] >= 0,
                'FINITE_CA_PENDING_EXCEPTION_CHANGED')
    if manifest_ref is not None: owner.verified(manifest_ref)
    return dict(status='FINITE_CA_PUBLISHED_CONTINUATION_VERIFIED', admission_ref=refs[0], end=manifest['end'],
        accepted_prefix_end=scope['accepted_prefix_end'], model_fit_calls=0, broker_action_allowed=False)


def already_current(paths, calendar_proof, as_of, *, finite_ca_admission_ref):
    owner = _owner(); result = owner.already_current(paths, calendar_proof, as_of)
    if result is None: return None
    ref = result['manifest_ref']; manifest = owner.projected_metadata(ref, ('end','as_of','extensions'))
    receipts = {sid:owner.projected_metadata(item, ('source_refs',)) for sid,item in manifest['extensions'].items()}
    proof = validate_published_continuation(paths, manifest_ref=ref, manifest=manifest, completion_receipts=receipts)
    owner.need(proof['admission_ref'] == finite_ca_admission_ref, 'FINITE_CA_CURRENT_ADMISSION_CHANGED')
    return {**result, 'finite_ca_admission_ref': finite_ca_admission_ref}


def _execution_projection():
    owner = _owner()
    replay = _clone(owner.replay_projection, guard_projection=_guard_projection)
    return _clone(owner.execute_prepared, _authority=_authority, guard_projection=_guard_projection,
        validate_descriptive_account=validate_descriptive_account, replay_projection=replay)


def run_qualified_main(paths, *, finite_ca_admission_ref, capture_ref=None, as_of, execute=False, auto=False, ca_receipt_refs=()):
    owner = _owner()
    if auto:
        proof = owner.completed_calendar(paths, as_of)
        current = already_current(paths, proof, as_of, finite_ca_admission_ref=finite_ca_admission_ref)
        if current is not None: return current
    if capture_ref is None:
        capture_ref = owner.resolve_current_capture(paths, owner.completed_calendar(paths, as_of))
    if not execute:
        preflight = metadata_preflight(paths, capture_ref=capture_ref, as_of=as_of, finite_ca_admission_ref=finite_ca_admission_ref)
        return {k:v for k,v in preflight.items() if k not in ('document','originals','baselines')}
    body, _ = _static(finite_ca_admission_ref, as_of); capsule = _read(body['facts_ref'], 131072); event = _event(body, capsule)
    raw = _raw_projection(finite_ca_admission_ref, capsule)
    original_inputs = _clone(owner.qualified_inputs, prepare_raw_quote_extension=raw)
    def inputs(paths, preflight, *, ca_receipt_refs=()):
        # The original loop calls this under its daily OS lock. Rebind the
        # finite decision after any wait, before source decoding or models.
        qualify_admission(paths, finite_ca_admission_ref, as_of=as_of, preflight=preflight)
        return original_inputs(paths, preflight, ca_receipt_refs=ca_receipt_refs)
    execute_fn = _execution_projection()
    def prepare(paths, sid, preflight, qualified, runtime_custody_ref=None):
        return _prepare(paths, sid, preflight, qualified, admission_ref=finite_ca_admission_ref,
            capsule=capsule, event=event, runtime_custody_ref=runtime_custody_ref)
    def publish(paths, *, candidate_id, frames, baseline_refs, authority, source_refs, projection_receipts):
        value = _authority(authority)
        prefix_ref = _prefix_receipt(paths, candidate_id, frames, finite_ca_admission_ref, body)
        refs = dict(source_refs, accepted_extension_prefix_comparison_ref=prefix_ref)
        provenance = json.loads(value.provenance_json); provenance['source_refs'] = refs
        value = replace(value, base=replace(value.base, provenance_json=owner.canonical(provenance)))
        return _clone(owner.publish_verified, _authority=_authority)(paths, candidate_id=candidate_id, frames=frames,
            baseline_refs=baseline_refs, authority=value, source_refs=refs, projection_receipts=projection_receipts)
    def manifest(paths, completions):
        receipts = {sid:owner.projected_metadata(ref, ('source_refs',)) for sid,ref in completions.items()}
        validate_published_continuation(paths, manifest_ref=None,
            manifest=dict(end=body['scope']['target_session'], as_of=as_of), completion_receipts=receipts)
        return owner.publish_manifest(paths, completions)
    def admitted_preflight(paths, *, capture_ref, as_of):
        # The original run owns its sole preflight. Its finite source admission
        # follows that result; inputs() separately rechecks it under the OS lock.
        return metadata_preflight(paths, capture_ref=capture_ref, as_of=as_of,
            finite_ca_admission_ref=finite_ca_admission_ref)
    run = _clone(owner.run_qualified_main, metadata_preflight=admitted_preflight,
        qualified_inputs=inputs, _prepare_candidate=prepare,
        execute_prepared=execute_fn, publish_verified=publish, publish_manifest=manifest,
        forward_r10=lambda paths,sid,roles,value:owner.forward_r10(paths,sid,roles,_authority(value).base),
        forward_r7=lambda paths,flags,dates,value,**kw:owner.forward_r7(paths,flags,dates,_authority(value).base,**kw),
        already_current=lambda paths,proof,clock:already_current(paths,proof,clock,finite_ca_admission_ref=finite_ca_admission_ref))
    return run(paths, capture_ref=capture_ref, as_of=as_of, execute=True, auto=auto, ca_receipt_refs=ca_receipt_refs)


def main(argv=None):
    import argparse
    from scripts.common.storage_paths import resolve
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--finite-ca-admission-ref', required=True)
    parser.add_argument('--capture-ref'); parser.add_argument('--ca-receipt-ref', action='append', default=[])
    parser.add_argument('--auto', action='store_true'); parser.add_argument('--execute', action='store_true')
    parser.add_argument('--as-of', default=datetime.now(timezone.utc).isoformat())
    args = parser.parse_args(argv)
    try:
        result = run_qualified_main(resolve(), finite_ca_admission_ref=json.loads(args.finite_ca_admission_ref),
            capture_ref=json.loads(args.capture_ref) if args.capture_ref else None,
            as_of=args.as_of, execute=args.execute, auto=args.auto, ca_receipt_refs=[json.loads(x) for x in args.ca_receipt_ref])
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print(json.dumps(dict(status='BLOCKED', reason=str(exc), error_type=type(exc).__name__, model_fit_calls=0, broker_action_allowed=False)))
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False)); return 0


if __name__ == '__main__': raise SystemExit(main())
