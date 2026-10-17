"""C14 thin prebinding adapter over frozen R5 metadata and membership owners.

This adapter adds no estimator, scheduler, bank, account or optimizer. Original
C14 source snapshots and ML delivery remain byte-identical. Numeric functions
accept caller-qualified in-memory payloads; the prebind command never calls them.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict, is_dataclass
from pathlib import Path
import copy
import hashlib
import json
from collections import Counter
import numpy as np
import pandas as pd
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.data import selector_maximal_risk_consumer as contract
from scripts.research.a2.inference import joint_event_risk_chain_r5 as chain_owner
from scripts.research.a2.risk.joint_risk_estimators import validate_covariance
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
from scripts.research.a2.factors import selector_constrained_membership as membership
from scripts.research.a2.evaluation.selector_constrained_evidence import _empirical_cvar_owner

RUN = Path('D:/us-tech-quant-backtests/V24/20261004T070941+0000_13adcb4c')
DESIGN_SHA = '8bdcabcc09817691741d8aaaf7baab8ba663e0360e13cc62b9d918208ff901b6'
DAG_SHA = 'b26dbcb71e63ea56263567cfd1ed8b086e8d8a221a5544ff9ab37e014e1dce85'
B_ID = 'V24_B_DYNAMIC_FULLPOOL_RISK_AND_IDENTITY_R5'
LIMIT = pd.Timestamp('2026-01-01', tz='UTC')
ANCHOR_FAMILIES = set(contract.FAMILIES) - set(chain_owner.CONTINUOUS) - set(contract.NO_NATIVE)
COUNTERS = ('selector_fit','risk_estimator_fit','solver','bootstrap','risk_numeric_read',
            '2026_read','EF_access','provider_fetch')
NUMERIC_FIELDS = {'covariance','marginal_sigma','scenarios','scenario_returns','replicas',
                  'returns','risk_values','mu','sigma','nav','sharpe','performance','winner','target'}

BANK_KEYS={'schema','research_id','plan_ref','qualification_ref','event_support_ref','source_authority_ref',
    'execution_producer_ref','model_producer_ref','method_bindings','states','blocked_or_failed','ledger_ref','new_fit_units',
    'cumulative_fit_units','daily_metadata_support_ref','future_next_event_lookup_allowed','strict_PIT_promotion_eligible',
    'quote_qualified','certified_nav_qualified','account_attempts','test2026_rows_read'}
BANK_STATE_KEYS={'node_id','event_id','dependency','dependency_local_event_id','recipe_id','family','as_of','cutoff','assets',
    'asset_uids','asset_epochs','learned_states','status','block_reason','family_source_qualification','method','risk_state_id',
    'artifact_ref','fit_dependency_ids','finite_check','covariance_sha256','source_receipt','event_policy_binding','source_support_identity'}
LEDGER_KEYS={'status','fit_attempts','inherited_fit_units','new_fit_units','risk_fit_units','records','failures','physical_events',
    'account_paths','test2026_rows_read','baseline_source','shared_cache_artifacts'}

class RiskBindingBlocked(ValueError):
    """A dependent role fails closed without changing any other role's mask."""


def need(ok, reason):
    if not ok: raise RiskBindingBlocked(reason)


def clock(value):
    at = pd.Timestamp(value)
    need(not pd.isna(at) and at.tzinfo is not None and at < LIMIT,
         'EXPLICIT_PRE2026_INFORMATION_CLOCK_REQUIRED')
    return at.tz_convert('UTC')


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''): digest.update(chunk)
    return digest.hexdigest()


def frozen_contract(run=RUN):
    run = Path(run)
    need(run.resolve() == RUN.resolve(), 'EXACT_EXISTING_C14_RUN_REQUIRED')
    result = []
    for name, digest in (('DESIGN_FREEZE.json', DESIGN_SHA), ('PHYSICAL_DAG.json', DAG_SHA)):
        path = run/name
        need(sha(path) == digest, 'FROZEN_CONTRACT_BYTES_CHANGED:'+name)
        result.append(json.loads(path.read_text(encoding='utf-8')))
    design, dag = result
    need(design['research_id'] == dag['research_id'] == contract.ID and
         design['strict_PIT_promotion_eligible'] is False and design['test2026_locked'] is True,
         'EXACT_MECHANISM_IDENTITY_AND_TIME_LOCK_REQUIRED')
    return design, dag


class _MetadataJSON:
    """Bounded JSON metadata reader: reject a payload key before its value read.

    This narrow reader is for original R5 publication JSON, never model/joblib
    artifacts. It has no skip-and-consume branch for numerical payload fields.
    """
    def __init__(self, stream, root_keys=None, record_collections=(), metadata_kind=None):
        self.root_keys=root_keys
        self.metadata_kind=metadata_kind
        self.record_collections=set(record_collections)
        self.stream, self.char = stream, stream.read(1)
    def take(self):
        value = self.char; self.char = self.stream.read(1); return value
    def space(self):
        while self.char and self.char.isspace(): self.take()
    def string(self):
        need(self.char == '"', 'METADATA_JSON_STRING_REQUIRED')
        data = self.take(); escaped = False
        while self.char:
            c = self.take(); data += c
            if c == '"' and not escaped: return json.loads(data)
            escaped = not escaped if c == '\\' else False
        raise RiskBindingBlocked('TRUNCATED_METADATA_JSON_STRING')
    def mu_metadata_type(self, path):
        """The ticker MU in exact producer-owned metadata maps, never a mu payload."""
        if (self.metadata_kind in ('bank', 'ledger') and len(path) == 3 and
                path[0] in self.record_collections and path[1] == '*' and
                path[2] in ('asset_uids', 'asset_epochs') and
                ((path[0] in ('states', 'blocked_or_failed') and self.metadata_kind == 'bank') or
                 (path[0] == 'records' and self.metadata_kind == 'ledger'))):
            return 'nullable_string'
        if (self.metadata_kind == 'ledger' and
                path == ('physical_events', '*', 'context', 'identity_epoch', 'uids')):
            return 'string'
        if self.metadata_kind != 'support' or path[:2] != ('events', '*'):
            return None
        paths = {
            ('asset_uids',): 'nullable_string', ('asset_epochs',): 'nullable_string',
            ('segment_starts',): 'nullable_date', ('security_coordinates',): 'coordinate',
            ('qualified_ff48_support',): 'nullable_ff48',
            ('history_support', 'nominal_n'): 'count',
            ('history_support', 'source_metadata_blockers'): 'source_reason',
            ('history_support', 'current_identity_blockers'): 'identity_reason',
            ('complete_structural_signature', 'asset_uids'): 'nullable_string',
            ('complete_structural_signature', 'asset_epochs'): 'nullable_string',
            ('complete_structural_signature', 'blocked_assets'): 'identity_reason',
            ('complete_structural_signature', 'security_coordinates'): 'coordinate',
            ('complete_structural_signature', 'ff48_qualified_source_support'): 'nullable_ff48',
            ('complete_structural_signature', 'feature_source_support'): 'strings',
        }
        return paths.get(path[2:])
    def literal(self, token, result):
        for expected in token:
            need(self.char == expected, 'EXACT_NATIVE_METADATA_LITERAL_REQUIRED')
            self.take()
        return result
    def metadata_leaf(self, kind):
        """Typed metadata only; reject a wrong first type before consuming its body."""
        self.space()
        if kind.startswith('nullable_'):
            if self.char == 'n': return self.literal('null', None)
            kind = kind.removeprefix('nullable_')
        if kind in ('string', 'date', 'sha', 'clock', 'source_reason', 'identity_reason', 'class_status'):
            need(self.char == '"', 'NATIVE_ASSET_IDENTITY_STRING_REQUIRED')
            result = self.string()
            if kind == 'date':
                need(len(result) == 10 and result[4] == result[7] == '-' and
                     all('0' <= c <= '9' for c in result.replace('-', '')) and result < '2026-01-01',
                     'EXACT_PRE2026_NATIVE_METADATA_DATE_REQUIRED')
                need(pd.Timestamp(result).strftime('%Y-%m-%d') == result, 'EXACT_NATIVE_METADATA_DATE_REQUIRED')
            elif kind == 'sha':
                need(len(result) == 64 and all(c in '0123456789abcdef' for c in result), 'NATIVE_METADATA_SHA_REQUIRED')
            elif kind == 'clock': clock(result)
            elif kind == 'source_reason':
                need(result in ('DECLARED_AVAILABLE_LABEL_ENDPOINT_METADATA_INVALID',
                                'AMBIGUOUS_REQUIRED_SOURCE_LABEL_UID_KEYS',
                                'WRONG_REQUIRED_STORED_LABEL_COORDINATE'), 'EXACT_NATIVE_SOURCE_BLOCK_REASON_REQUIRED')
            elif kind == 'identity_reason':
                need(result in ('AMBIGUOUS_OR_MISSING_CURRENT_UID', 'NONUNIQUE_CURRENT_UID',
                                'UNKNOWN_CURRENT_UID'), 'EXACT_NATIVE_IDENTITY_BLOCK_REASON_REQUIRED')
            elif kind == 'class_status':
                need(result in ('EXACT_FROZEN_INTERVAL_METADATA_DECLARATION',
                                'CLASS_COORDINATE_UNRESOLVED'), 'EXACT_NATIVE_CLASS_STATUS_REQUIRED')
            return result
        if kind == 'false':
            need(self.char == 'f', 'NATIVE_METADATA_FALSE_REQUIRED')
            return self.literal('false', False)
        if kind in ('count', 'group'):
            need('0' <= self.char <= '9', 'NATIVE_METADATA_INTEGER_REQUIRED')
            digits = ''
            while self.char and '0' <= self.char <= '9': digits += self.take()
            need(self.char in ',]} \r\n\t', 'NATIVE_METADATA_INTEGER_REQUIRED')
            need(len(digits) == 1 or digits[0] != '0', 'NATIVE_METADATA_INTEGER_REQUIRED')
            result = int(digits)
            need(0 <= result <= 252 if kind == 'count' else 1 <= result <= 48, 'NATIVE_METADATA_INTEGER_RANGE_REQUIRED')
            return result
        if kind == 'strings':
            need(self.char == '[', 'NATIVE_METADATA_STRING_LIST_REQUIRED')
            self.take(); self.space(); result = []
            if self.char == ']': self.take(); return result
            while True:
                need(self.char == '"', 'NATIVE_METADATA_STRING_LIST_REQUIRED')
                result.append(self.string()); self.space(); c = self.take()
                if c == ']': return result
                need(c == ',', 'NATIVE_METADATA_STRING_LIST_REQUIRED'); self.space()
        if kind in ('coordinate', 'ff48'):
            need(self.char == '{', 'NATIVE_METADATA_OBJECT_REQUIRED')
            fields = ({'raw_transport_codes': 'strings', 'security_class_declaration': 'nullable_string',
                       'security_id_type': 'nullable_string', 'cusip': 'nullable_string',
                       'mapping_status': 'nullable_string', 'class_coordinate_status': 'class_status',
                       'strict_historical_authority': 'false'} if kind == 'coordinate' else
                      {'group': 'group', 'sic_source_sha256': 'sha', 'available_at': 'clock'})
            self.take(); self.space(); result = {}
            while self.char != '}':
                key = self.string(); self.space()
                need(key in fields and key not in result and self.char == ':', 'EXACT_NATIVE_METADATA_OBJECT_FIELDS_REQUIRED')
                self.take(); result[key] = self.metadata_leaf(fields[key]); self.space(); c = self.take()
                if c == '}':
                    need(set(result) == set(fields), 'EXACT_NATIVE_METADATA_OBJECT_FIELDS_REQUIRED')
                    return result
                need(c == ',', 'INVALID_NATIVE_METADATA_OBJECT'); self.space()
            raise RiskBindingBlocked('EXACT_NATIVE_METADATA_OBJECT_FIELDS_REQUIRED')
        raise RiskBindingBlocked('UNAPPROVED_NATIVE_METADATA_LEAF')
    def value(self, depth=0, path=()):
        need(depth < 100, 'METADATA_DEPTH_LIMIT'); self.space()
        if self.char == '{':
            self.take(); self.space(); value = {}
            if self.char == '}': self.take(); return value
            while True:
                self.space(); key = self.string(); self.space()
                mu_type = self.mu_metadata_type(path) if key == 'MU' else None
                need(key.lower() not in NUMERIC_FIELDS or mu_type is not None,
                     'NUMERIC_OR_OUTCOME_PAYLOAD_FORBIDDEN:'+key)
                if depth==0 and self.root_keys is not None:
                    need(key in self.root_keys,'UNAPPROVED_R5_METADATA_FIELD:'+key)
                if len(path)==2 and path[0] in self.record_collections and path[1]=='*':
                    need(key in BANK_STATE_KEYS,'UNAPPROVED_R5_RECORD_FIELD:'+key)
                need(key not in value and self.char == ':', 'DUPLICATE_KEY_OR_INVALID_METADATA_JSON')
                self.take()
                value[key] = (self.metadata_leaf(mu_type) if mu_type is not None else
                              self.value(depth+1,path+(key,)))
                self.space()
                c = self.take()
                if c == '}': return value
                need(c == ',', 'INVALID_METADATA_JSON_OBJECT')
        if self.char == '[':
            self.take(); self.space(); value = []
            if self.char == ']': self.take(); return value
            while True:
                value.append(self.value(depth+1,path+('*',))); self.space(); c = self.take()
                if c == ']': return value
                need(c == ',', 'INVALID_METADATA_JSON_ARRAY')
        if self.char == '"': return self.string()
        data = ''
        while self.char and self.char not in ',]} \r\n\t': data += self.take()
        need(bool(data), 'INVALID_METADATA_JSON_PRIMITIVE')
        value = json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(RiskBindingBlocked('NONFINITE_METADATA')))
        need(type(value) in (int,float,bool,type(None)), 'INVALID_METADATA_PRIMITIVE')
        return value


def read_r5_metadata(reference, *, owner_root=contract.B_RUN):
    """Read pinned original R5 JSON metadata; no covariance/scenario deserializer."""
    path = Path(reference['path']); root = Path(owner_root)
    need(root.resolve() == contract.B_RUN.resolve(), 'ORIGINAL_R5_OWNER_ONLY')
    approved={'EVENT_RISK_BANK_R5.json','R5_SCIENCE_AND_EXECUTION_FREEZE.json','R5_FINITE_EVENT_RISK_PLAN.json',
              'RISK_EVENT_QUALIFICATION_R5.json','RISK_EVENT_QUALIFICATION_READER_RECOVERY_R5_R1.json',
              'EVENT_RISK_SUPPORT_R5.json','FIT_STATUS.json','SOURCE_AUTHORITY.json'}
    need(path.name in approved,'EXACT_APPROVED_R5_METADATA_FILE_REQUIRED')
    need(path.is_absolute() and path.suffix == '.json' and path.resolve().is_relative_to(root.resolve()),
         'R5_RUN_OWNED_METADATA_REFERENCE_REQUIRED')
    assert_safe_output_path(path, kind='backtest')
    need(path.stat().st_size <= 300*1024*1024, 'BOUNDED_R5_METADATA_SIZE_REQUIRED')
    need(sha(path) == reference['sha256'], 'R5_METADATA_PHYSICAL_SHA_MISMATCH')
    root_keys=BANK_KEYS if path.name=='EVENT_RISK_BANK_R5.json' else LEDGER_KEYS if path.name=='FIT_STATUS.json' else None
    records=('states','blocked_or_failed') if path.name=='EVENT_RISK_BANK_R5.json' else ('records',) if path.name=='FIT_STATUS.json' else ()
    with path.open('r', encoding='utf-8-sig') as stream:
        kind = {'EVENT_RISK_BANK_R5.json': 'bank', 'FIT_STATUS.json': 'ledger', 'EVENT_RISK_SUPPORT_R5.json': 'support'}.get(path.name, 'other')
        reader = _MetadataJSON(stream,root_keys=root_keys,record_collections=records,metadata_kind=kind); value = reader.value(); reader.space()
        need(reader.char == '', 'TRAILING_METADATA_JSON_FORBIDDEN')
    need(isinstance(value,dict),'R5_METADATA_OBJECT_REQUIRED')
    if path.name=='FIT_STATUS.json':
        need(value.get('inherited_fit_units')==3027 and value.get('test2026_rows_read')==0
             and value.get('account_paths')==0,'EXACT_ORIGINAL_R5_LEDGER_SCOPE_REQUIRED')
    else:
        need(value.get('research_id') == B_ID, 'ORIGINAL_R5_RESEARCH_ID_REQUIRED')
    need(value.get('strict_PIT_promotion_eligible',False) is False, 'NO_PIT_PROMOTION')
    if path.name=='EVENT_RISK_BANK_R5.json':
        need(value.get('schema')=='B_R5_EVENT_RISK_BANK_V1' and set(value)==BANK_KEYS,'EXACT_NATIVE_BANK_METADATA_SCHEMA_REQUIRED')
        need(all(set(r)<=BANK_STATE_KEYS for r in [*value['states'],*value['blocked_or_failed']]),'EXACT_NATIVE_BANK_RECORD_FIELDS_REQUIRED')
    return value


def requirement_matrix(design, dag):
    """Derive role/slot routing only from original frozen role bindings and DAG."""
    risk = design['risk']; rows = []
    calendar = [s.rsplit('|',1)[-1] for s in dag['solve_request_ids'] if s.startswith('CLASSICAL|C14_D01|')]
    need(len(calendar)==752 and calendar==sorted(set(calendar)),'EXACT_FROZEN752_CALENDAR_REQUIRED')
    need(all(pd.Timestamp(d)<pd.Timestamp('2026-01-01') for d in calendar),'PRE2026_DATE_MASK_REQUIRED')
    slots = dag['conditional_risk_fit_nodes']
    def add(role, learner, family, route, owner, solves, inferential=False):
        nodes = [copy.deepcopy(n) for n in slots if n['candidate_id'] == role]
        if route == 'RAW_IDENTITY':
            category, status, missing = 'NO_RISK_INPUT_REQUIRED','READY_FOR_METADATA_BINDING',[]
        elif route == 'BLOCKED_BUDGET':
            category, status, missing = 'STRUCTURALLY_UNSUPPORTED_BY_CURRENT_R5','BLOCKED_BUDGET',['original reservation absent; no authorization']
        elif family in risk['permanent_blocked_methods']:
            category, status, missing = 'STRUCTURALLY_UNSUPPORTED_BY_CURRENT_R5','BLOCKED_BY_CURRENT_B_SCOPE',['native '+family+' producer absent; substitution forbidden']
        elif family in chain_owner.CONTINUOUS:
            category, status, missing = 'WAITING_R5_PUBLICATION','WAITING_R5_PUBLICATION',['formal bank/freeze/qualification/ledger and exact per-role coverage']
        else:
            category, status = 'REQUIRES_ADDITIONAL_SPECIFIC_INPUT','BLOCKED_BY_CURRENT_B_SCOPE'
            missing = ['continuous full-required-date '+family+' state; current R5 is two anchors only']
        if family == 'TAIL_CVAR': missing += ['independently qualified native H5 scenario matrix and scenario-source receipt']
        if family in ('UNCERTAINTY_JACKKNIFE','DISAGREEMENT_ENSEMBLE'):
            missing += ['native full-U PSD covariance replicas; >=2 for ddof=1; scalar sigma insufficient']
        if family == 'QQQ_RESIDUAL': missing += ['exact QQQ past-only source/recipe/available_at binding']
        if family == 'REGIME_COVARIANCE': missing += ['past20-session QQQ volatility and past252-session median regime state with exact past-only source clock']
        if route == 'CLASSICAL' and owner not in membership.METHODS:
            missing += ['FROZEN_MEMBERSHIP_OWNER_UNBOUND:'+owner]
        rows.append(dict(role=role,learner=learner,risk_representation=family,required_family_method=family,
            required_horizon=5,required_dates=list(calendar),
            required_732_mature_day_support=True,learned_support_mask=482,calendar_positions=752,
            outer_prediction_dates=502 if route in ('HYBRID','VETO') else 752,
            full_risk_inferential_eligible=inferential,ordered_U_requirement='exact current full U, preserve original order',
            UID_epoch_requirement='exact current UID and epoch; no cross-identity/epoch stitching',
            source_requirement='original R5 source identity/version/hash/security coordinate/recipe/parameters',
            cutoff_available_at_requirement='history cutoff < state as_of <= historical available_at <= decision < 2026; every own fold cutoff',
            PSD_requirement='existing validate_covariance regularize=False; no repair',
            scenario_replica_requirement='nativeH5 scenarios' if family=='TAIL_CVAR' else
                'fullPSD native covariance replicas' if family in ('UNCERTAINTY_JACKKNIFE','DISAGREEMENT_ENSEMBLE') else 'none',
            solver_requirement=dict(route=route,existing_owner=owner,maximum_named_requests=solves,
                named_request_ids=[s for s in dag['solve_request_ids'] if role in s]),
            classification=category,current_status=status,missing_inputs=missing,
            possible_final_statuses=['WAITING_R5_PUBLICATION','STATIC_COMPATIBLE_WAITING_COVERAGE','READY_FOR_METADATA_BINDING','BLOCKED_BY_CURRENT_B_SCOPE','BLOCKED_SOURCE','BLOCKED_INPUT','BLOCKED_BUDGET'],
            conditional_fit_slots=len(nodes),conditional_fit_nodes=nodes))
    for b in risk['hybrid_bindings']:
        add(b['candidate_id'],b['head'],b['family'],'HYBRID','selector_maximal_breadth_estimators',502)
    for b in risk['classical_bindings']:
        route = 'RAW_IDENTITY' if b['existing_rule']=='RAW_IDENTITY' else 'BLOCKED_BUDGET' if b['candidate_id']=='C14_D12' else 'CLASSICAL'
        add(b['candidate_id'],'NONE',b['family'],route,b['existing_rule'],0 if route!='CLASSICAL' else 752,b['candidate_id'] in risk['risk_efficiency_eligible_roles'])
    for gate,family in risk['gate_families'].items(): add('C14_'+gate,'FIXED_RIDGE_C14_P01',family,'VETO',gate,0)
    add('C14_RX7','NONE','DISAGREEMENT_ENSEMBLE','BLOCKED_BUDGET','RX7',0)
    need(sum(r['conditional_fit_slots'] for r in rows)==144 and len(slots)==144,'ALL144_CONDITIONAL_SLOTS_MUST_REMAIN')
    return dict(schema='C14_FROZEN_RISK_REQUIREMENT_MATRIX_V1',research_id=contract.ID,
        design_sha256=DESIGN_SHA,dag_sha256=DAG_SHA,roles=rows,
        slot_counts_by_classification=dict(Counter({cat:sum(r['conditional_fit_slots'] for r in rows if r['classification']==cat)
            for cat in {r['classification'] for r in rows}})),
        risk_efficiency_hypotheses=copy.deepcopy(design['evaluation']['risk_specs']),
        endpoint_requirements=dict(full_risk_mature_positions=732,calendar_positions=752,learned_positions=482,
            input_scenario_source_is_distinct_from_realized_endpoint_source=True,
            native_H5_realized_equal_weight_return_source='independently qualified full732 endpoint receipt; never fabricate/drop'),
        blocked_native_methods=copy.deepcopy(risk['permanent_blocked_methods']),
        counts={k:0 for k in COUNTERS},strict_PIT_promotion_eligible=False)


@dataclass(frozen=True)
class RiskMetadata:
    """Exact caller-projected metadata; no numerical arrays or model objects."""
    role: str
    family: str
    header: dict
    current: dict
    decision_asof: str
    recipe_sha256: str
    parameters: dict
    coverage_dates: tuple
    publication_refs: dict
    _seal: str = field(init=False,repr=False)

    def __post_init__(self):
        object.__setattr__(self,'_seal',content_hash({k:v for k,v in self.__dict__.items() if k!='_seal'}))

    def verify(self):
        need(self._seal==content_hash({k:v for k,v in self.__dict__.items() if k!='_seal'}),'MUTATED_ROLE_METADATA')


def bind_role_metadata(requirement, record, current, decision_asof, binding, publication_refs, *, required_dates):
    need(requirement['solver_requirement']['route'] not in ('BLOCKED_BUDGET','RAW_IDENTITY'),'ROLE_HAS_NO_NUMERIC_ROUTE')
    need(requirement['current_status'] != 'BLOCKED_BY_CURRENT_B_SCOPE','BLOCKED_BY_CURRENT_B_SCOPE')
    family=requirement['required_family_method']
    need(record.get('family') == binding.get('family') == family,'EXACT_FROZEN_ROLE_FAMILY_NO_FALLBACK')
    need(record.get('method') == binding['method'] and record.get('parameters') == binding['parameters']
         and record.get('history_recipe') == binding['history_recipe'],'EXACT_METHOD_PARAMETERS_HISTORY_RECIPE_REQUIRED')
    need(record.get('representation') == binding['representation'] == 'CONTINUOUS','ANCHOR_CANNOT_IMPERSONATE_CONTINUOUS')
    need(set(publication_refs)=={'bank','freeze','qualification','ledger'} and
         all(isinstance(r,dict) and len(r.get('sha256',''))==64 and Path(r.get('path','')).is_absolute()
             and Path(r['path']).resolve().is_relative_to(contract.B_RUN.resolve()) for r in publication_refs.values()),
         'FORMAL_ORIGINAL_R5_PUBLICATION_REFS_REQUIRED')
    at,available=clock(decision_asof),clock(record['available_at'])
    need(clock(record['as_of'])<=available<=at,'LATE_STATE_AVAILABLE_AT')
    need(record.get('security_coordinate')==current['security_coordinate'] and
         record.get('source_support_identity')==current['source_support_identity'],'EXACT_CURRENT_SOURCE_COORDINATE_REQUIRED')
    need(len(required_dates)==752 and tuple(required_dates)==tuple(requirement['required_dates'])
         and tuple(record.get('coverage_dates',()))==tuple(required_dates),'EXACT_FROZEN_DATE_MASK_NO_SHORTENING')
    need(record.get('psd_qualified') in (True,'DEFERRED_NUMERIC_EXACT_OWNER_CHECK') and record.get('finite_check') is True,'PSD_AND_FINITE_METADATA_REQUIRED')
    if family=='TAIL_CVAR':
        need(record.get('scenario_qualified') is True and record.get('scenario_horizon')==5
             and record.get('scenario_source_ref') is not None,'NATIVE_H5_SCENARIO_SOURCE_REQUIRED')
    if family in ('UNCERTAINTY_JACKKNIFE','DISAGREEMENT_ENSEMBLE'):
        need(record.get('replica_count',0)>=2 and record.get('replicas_full_psd_qualified') is True
             and record.get('replica_refs'),'FULL_PSD_REPLICAS_REQUIRED_NOT_SCALAR_SIGMA')
    header=contract.qualify_header(record,current,decision_asof,binding['recipe_sha256'])
    need(header['numeric_read_authority'] is False,'HEADER_CANNOT_GRANT_NUMERIC_AUTHORITY')
    return RiskMetadata(requirement['role'],family,copy.deepcopy(record),copy.deepcopy(current),
        str(at),binding['recipe_sha256'],copy.deepcopy(binding['parameters']),tuple(required_dates),copy.deepcopy(publication_refs))


def bind_partial_roles(matrix, inputs):
    """Keep every frozen role, all masks and independent blockers in serialized output."""
    output=[]
    for requirement in matrix['roles']:
        role=requirement['role']; status=requirement['current_status']; reason=list(requirement['missing_inputs']); bound=None
        if status not in ('BLOCKED_BY_CURRENT_B_SCOPE','BLOCKED_BUDGET') and requirement['solver_requirement']['route']!='RAW_IDENTITY':
            if role in inputs:
                try:
                    bound=bind_role_metadata(requirement,**inputs[role]); status='READY_FOR_METADATA_BINDING'; reason=[]
                except (ValueError,KeyError,TypeError) as error:
                    status='BLOCKED_SOURCE' if any(s in str(error) for s in ('SOURCE','AVAILABLE','CUTOFF','EPOCH','UID')) else 'BLOCKED_INPUT'
                    reason=[str(error)]
        output.append(dict(role=role,status=status,reasons=reason,metadata_bound=bound is not None,
            binding_sha256=None if bound is None else bound._seal,calendar_positions=752,
            full_risk_mature_positions=732,learned_positions=482,numeric_execution_performed=False))
    return dict(research_id=contract.ID,roles=output,counts={k:0 for k in COUNTERS},strict_PIT_promotion_eligible=False)


@dataclass(frozen=True)
class NativeRiskPayload:
    """Numeric payload attested after one exact pinned native RiskState load.

    A missing exporter covariance digest is kept missing in metadata. This sealed
    attestation records the existing content_hash computed from the pinned state,
    without estimating, repairing or replacing its covariance.
    """
    values: dict
    metadata_seal: str
    artifact_ref: dict
    covariance_sha256: str
    _seal: str = field(init=False,repr=False)
    def __post_init__(self):
        object.__setattr__(self,'_seal',content_hash({k:v for k,v in self.__dict__.items() if k!='_seal'}))
    def verify(self):
        need(self._seal==content_hash({k:v for k,v in self.__dict__.items() if k!='_seal'}),'MUTATED_NATIVE_RISK_PAYLOAD')
    def get(self,key,default=None): return self.values.get(key,default)
    def __getitem__(self,key): return self.values[key]


@dataclass(frozen=True)
class P01Proposal:
    """Sealed exact cached P01 proposal; contains no new decoder execution."""
    receipt: dict
    cache_ref: dict
    _seal: str = field(init=False,repr=False)
    def __post_init__(self):
        object.__setattr__(self,'_seal',content_hash({k:v for k,v in self.__dict__.items() if k!='_seal'}))
    def verify(self):
        need(self._seal==content_hash({k:v for k,v in self.__dict__.items() if k!='_seal'}),'MUTATED_P01_PROPOSAL')
    def get(self,key,default=None): return self.receipt.get(key,default)
    def __getitem__(self,key): return self.receipt[key]


def read_p01_proposal(cache_ref,*,decision_asof,raw_metadata,expected_identity):
    """Read the existing complete decoder cache, never decode or charge again.

    Called only during qualified consumption. This prebind phase tests it through
    an in-memory file double and never opens the real ledger or predictions.
    """
    from scripts.research.a2.training.selector_maximal_breadth import content_hash as decoder_hash
    at=clock(decision_asof); path=Path(cache_ref['path'])
    need(path.resolve()==(RUN/'SOLVE_LEDGER.json').resolve(),'EXACT_ORIGINAL_C14_DECODER_CACHE_OWNER_REQUIRED')
    need(sha(path)==cache_ref['sha256'],'P01_CACHE_PHYSICAL_PIN_CHANGED')
    need(path.stat().st_size<=64*1024*1024,'BOUNDED_P01_DECODER_CACHE_REQUIRED')
    with path.open(encoding='utf-8') as stream: ledger=json.load(stream)
    need(ledger.get('research_id')==contract.ID and ledger.get('hard_cap')==30000,'EXACT_P01_LEDGER_IDENTITY_REQUIRED')
    token='MAIN|C14_P01|'+at.tz_localize(None).normalize().isoformat()
    native=ledger['requests'].get(token)
    need(isinstance(native,dict) and native.get('status')=='COMPLETE' and native.get('charged')==1
         and isinstance(native.get('matching_records'),list),'BLOCKED_CHARGED_DECODER_NO_COMPLETE_CACHE')
    need(native['identity']==expected_identity and expected_identity.get('candidate_id')=='C14_P01'
         and expected_identity.get('design_sha256')==DESIGN_SHA,'EXACT_P01_INPUT_IDENTITY_REQUIRED')
    for key in ('pair_key_sha256','full_U_keys_sha256','score_sha256','eligibility_sha256'):
        need(len(expected_identity.get(key,''))==64,'EXACT_P01_INPUT_IDENTITY_REQUIRED')
    from scripts.research.a2.training.selector_maximal_breadth import pairs, KEYS
    raw=pairs._raw(raw_metadata,with_score=True)
    need(raw.signal_date.nunique()==1 and raw.signal_date.iloc[0]==at.tz_localize(None).normalize(),
         'EXACT_P01_CURRENT_RAW_DATE_REQUIRED')
    raw_uids=raw.security_uid.tolist()[:40]
    need(decoder_hash(raw_metadata[[*KEYS,'raw_rank','U_t_fingerprint']].astype(str).values.tolist())
         ==expected_identity['full_U_keys_sha256'] and pairs.pair_key_sha256(pairs.geometry(raw_metadata))
         ==expected_identity['pair_key_sha256'],'EXACT_P01_FULL_U_AND200_PAIR_KEYS_REQUIRED')
    records=native['matching_records']
    need(decoder_hash(records)==native.get('matching_sha256'),'EXACT_P01_MATCH_CACHE_SHA_REQUIRED')
    need(len(raw_uids)==40 and len(set(raw_uids))==40 and len(records)<=10,'EXACT_P01_RAW40_MATCH_GEOMETRY')
    seen_c=set(); seen_i=set()
    for row in records:
        c=row['challenger_uid']; i=row['incumbent_uid']
        need(pd.Timestamp(row['signal_date'])==at.tz_localize(None).normalize()
             and c in raw_uids[20:40] and i in raw_uids[10:20] and c not in seen_c and i not in seen_i
             and row['challenger_raw_rank']==raw_uids.index(c)+1 and row['incumbent_raw_rank']==raw_uids.index(i)+1
             and np.isfinite(row['predicted_edge']) and row['predicted_edge']>0,'EXACT_P01_POSITIVE_ONE_TO_ONE_MATCH_REQUIRED')
        seen_c.add(c);seen_i.add(i)
    # Reuse the original zero-solver membership owner for the already cached pairs.
    from scripts.research.a2.training.selector_maximal_breadth import membership_panel, PAIR_KEYS
    panel=membership_panel(raw_metadata,pd.DataFrame(records,columns=[*PAIR_KEYS,'predicted_edge']),'C14_P01')
    chosen=panel.sort_values('rank').security_uid.tolist()[:20]
    receipt=dict(candidate_id='C14_P01',decision_asof=str(at),chosen_uids=chosen,exact_decoder_cache_complete=True,
        decoder_request_id=token,artifact_ref=copy.deepcopy(cache_ref),matching_sha256=native['matching_sha256'])
    return P01Proposal(receipt,copy.deepcopy(cache_ref))


def _consumer_uids(meta):
    """Reuse C14's already frozen CUSIP namespace; native state stays unchanged."""
    assets=meta.current['assets']; native=meta.current['asset_uids']
    if 'consumer_uids' not in meta.current:
        return [native[a] for a in assets]
    from scripts.research.a2.data import selector_shared_risk_consumer as namespace_owner
    path=Path(namespace_owner.__file__).resolve()
    expected='71a57696ba1596ee03c17939d561b75cfcd9870969aadc32991fc4e0dbf79fd3'
    need(meta.current.get('consumer_namespace_owner_ref')==dict(path=str(path),sha256=expected)
         and sha(path)==expected,'EXACT_FROZEN_C14_NAMESPACE_OWNER_REQUIRED')
    mapped={a:namespace_owner.namespace(native[a]) for a in assets}
    need(meta.current['consumer_uids']==mapped and len(set(mapped.values()))==len(assets),
         'EXACT_FROZEN_CUSIP_NAMESPACE_ONE_TO_ONE_REQUIRED')
    return [mapped[a] for a in assets]


def _numeric_input(meta, payload, raw_uids):
    need(type(meta) is RiskMetadata,'TYPED_ROLE_METADATA_REQUIRED')
    meta.verify()
    expected = {b['candidate_id']:b['family'] for b in contract.specification()['hybrid_bindings']}
    expected.update({b['candidate_id']:b['family'] for b in contract.specification()['classical_bindings']})
    expected.update({'C14_G1':'LW','C14_G2':'TAIL_CVAR','C14_G3':'UNCERTAINTY_JACKKNIFE','C14_G4':'PCA_FACTOR'})
    need(expected.get(meta.role)==meta.family,'EXACT_FROZEN_ROLE_FAMILY_NO_FALLBACK')
    clock(meta.decision_asof)
    assets=meta.current['assets']; n=len(assets)
    need(payload.get('family')==meta.family and payload.get('ordered_U')==assets
         and payload.get('uids')==meta.current['asset_uids'] and payload.get('epochs')==meta.current['asset_epochs'],
         'NUMERIC_FULL_U_UID_EPOCH_BINDING_REQUIRED')
    for key,expected in (('state_id',meta.header['risk_state_id']),('method',meta.header['method']),
                         ('recipe_sha256',meta.recipe_sha256),('horizon_sessions',5),
                         ('cutoff',meta.header['cutoff']),('as_of',meta.header['as_of']),
                         ('source_support_identity',meta.current['source_support_identity']),('parameters',meta.parameters)):
        need(payload.get(key)==expected,'EXACT_NUMERIC_STATE_SOURCE_METHOD_TIME_PARAMS:'+key)
    cov=np.asarray(payload['covariance'],dtype=float)
    need(cov.shape==(n,n),'NO_NUMERIC_FULL_U_PADDING')
    validate_covariance(cov,regularize=False)
    digest=sha_array(cov)
    if meta.header['covariance_sha256'] is None:
        need(type(payload) is NativeRiskPayload,'PINNED_NATIVE_COVARIANCE_ATTESTATION_REQUIRED')
        payload.verify()
        need(payload.metadata_seal==meta._seal and payload.artifact_ref==meta.header['artifact_ref']
             and payload.covariance_sha256==digest,'EXACT_PINNED_NATIVE_COVARIANCE_ATTESTATION_REQUIRED')
    else:
        need(digest==meta.header['covariance_sha256'],'EXACT_COVARIANCE_PAYLOAD_SHA_REQUIRED')
    uids=_consumer_uids(meta)
    need(len(raw_uids)==40 and len(set(raw_uids))==40 and set(raw_uids)<=set(uids),'EXACT_RAW40_CURRENT_UID_GEOMETRY')
    pos={u:i for i,u in enumerate(uids)}; indices=[pos[u] for u in raw_uids]
    return cov,indices


def sha_array(value): return content_hash(np.asarray(value,dtype=float))


def hybrid_coordinates(meta,payload,raw_uids):
    """Frozen two coordinates per asset; pair encoding remains exactly 12 columns."""
    cov,indices=_numeric_input(meta,payload,raw_uids)
    need(meta.role in {b['candidate_id'] for b in contract.specification()['hybrid_bindings']},'FROZEN_HYBRID_ROLE_REQUIRED')
    if meta.family=='UNCERTAINTY_JACKKNIFE':
        replicas=_replicas(meta,payload,cov.shape)
        coord=np.stack([np.column_stack((np.diag(r),r[:,indices[:20]].sum(axis=1)/20)) for r in replicas])
        return np.std(coord,axis=0,ddof=1)
    return np.column_stack((np.diag(cov),cov[:,indices[:20]].sum(axis=1)/20))


def pair_risk_columns(coords, challenger_positions, incumbent_positions):
    coords=np.asarray(coords,float); c=np.asarray(challenger_positions,int); i=np.asarray(incumbent_positions,int)
    need(coords.ndim==2 and coords.shape[1]==2 and np.isfinite(coords).all() and c.shape==i.shape
         and (c>=0).all() and (i>=0).all() and (c<len(coords)).all() and (i<len(coords)).all(), 'EXACT_FINITE_PAIR_RISK_COORDINATES')
    values=np.column_stack((coords[c],coords[i],coords[c]-coords[i]))
    return np.column_stack((values,np.zeros_like(values)))  # No missing state may reach this function.


def _replicas(meta,payload,shape):
    values=np.asarray(payload.get('replicas'),float)
    need(values.ndim==3 and values.shape[1:]==shape and len(values)>=2
         and len(values)==meta.header.get('replica_count'),'FULL_PSD_NATIVE_REPLICA_DIMENSION')
    need([sha_array(x) for x in values]==meta.header.get('replica_sha256s'),'EXACT_REPLICA_PAYLOAD_SHA_REQUIRED')
    for value in values: validate_covariance(value,regularize=False)
    return values


def whole_set_veto(meta,payload,raw_uids,proposal_uids,*,proposal_receipt):
    """Consume the already decoded C14_P01 set. Never invoke matching or refill."""
    need(meta.role in ('C14_G1','C14_G2','C14_G3','C14_G4'),'FROZEN_G_GATE_REQUIRED')
    need(type(proposal_receipt) is P01Proposal,'VERIFIED_TYPED_P01_PROPOSAL_REQUIRED')
    proposal_receipt.verify()
    need(proposal_receipt.cache_ref==proposal_receipt['artifact_ref'],'EXACT_P01_CACHE_REFERENCE_REQUIRED')
    need(proposal_receipt.get('candidate_id')=='C14_P01' and
         proposal_receipt.get('chosen_uids')==list(proposal_uids) and
         clock(proposal_receipt['decision_asof'])==clock(meta.decision_asof) and
         proposal_receipt.get('exact_decoder_cache_complete') is True and
         proposal_receipt.get('decoder_request_id')=='MAIN|C14_P01|'+clock(meta.decision_asof).tz_localize(None).normalize().isoformat() and
         Path(proposal_receipt.get('artifact_ref',{}).get('path','')).is_absolute() and
         len(proposal_receipt.get('artifact_ref',{}).get('sha256',''))==64,'EXACT_P01_COMPLETE_DECODE_RECEIPT_REQUIRED')
    need(len(proposal_uids)==20 and len(set(proposal_uids))==20 and set(raw_uids[:10])<=set(proposal_uids)
         and set(proposal_uids)<=set(raw_uids),'EXACT20_RAW_CORE10_BOUNDARY_GEOMETRY')
    expected={'C14_G1':'LW','C14_G2':'TAIL_CVAR','C14_G3':'UNCERTAINTY_JACKKNIFE','C14_G4':'PCA_FACTOR'}
    need(meta.family==expected[meta.role],'EXACT_G_GATE_REPRESENTATION')
    cov,indices=_numeric_input(meta,payload,raw_uids)
    alluids=_consumer_uids(meta)
    lookup={u:i for i,u in enumerate(alluids)}; proposed=[lookup[u] for u in proposal_uids]; baseline=indices[:20]
    def variance(value,positions): return float(value[np.ix_(positions,positions)].sum()/400)
    if meta.role=='C14_G1': before,after=variance(cov,baseline),variance(cov,proposed); passed=after<=before
    elif meta.role=='C14_G2':
        scenes=np.asarray(payload.get('scenarios'),float)
        need(scenes.ndim==2 and scenes.shape[1]==len(cov) and len(scenes)>0 and np.isfinite(scenes).all()
             and sha_array(scenes)==meta.header.get('scenario_sha256'),'EXACT_FULL_U_NATIVE_H5_SCENARIOS')
        before=float(_empirical_cvar_owner()(-scenes[:,baseline].mean(axis=1),alpha=.95))
        after=float(_empirical_cvar_owner()(-scenes[:,proposed].mean(axis=1),alpha=.95)); passed=after<=before
    elif meta.role=='C14_G3':
        replicas=_replicas(meta,payload,cov.shape)
        before=float(np.std([variance(x,baseline) for x in replicas],ddof=1))
        after=float(np.std([variance(x,proposed) for x in replicas],ddof=1)); passed=after<=before
    else:
        matrix=cov[np.ix_(indices,indices)]; _,groups=membership._clusters(matrix,tuple(raw_uids))
        ranks={u:i for i,u in enumerate(raw_uids)}
        def occupied(chosen):
            positions={ranks[u] for u in chosen}-set(range(10))
            counts=np.array([len(positions&set(g)) for g in groups]); return float(np.sum((counts/10)**2)),int(np.sum(counts>0))
        before,nb=occupied(raw_uids[:20]); after,na=occupied(proposal_uids); passed=after<=before and na>=nb
    return dict(role=meta.role,status='PASS_WHOLE_SET' if passed else 'VETO_WHOLE_SET',
        chosen_uids=list(proposal_uids if passed else raw_uids[:20]),proposal_uids=list(proposal_uids),
        baseline=before,proposal=after,rematching=False,refill=False,extra_solves=0,anchor='C14_P01')


def classical_route(requirement,meta,payload,raw_uids,decision_at):
    route=requirement['solver_requirement']; role=requirement['role']
    clock(decision_at)
    need(len(raw_uids)==40 and len(set(raw_uids))==40,'EXACT_RAW40_CURRENT_UID_GEOMETRY')
    if route['route']=='RAW_IDENTITY': return dict(role=role,chosen_uids=list(raw_uids[:20]),optimizer_solve_calls=0)
    need(route['route']=='CLASSICAL' and route['existing_owner'] in membership.METHODS,
         'FROZEN_MEMBERSHIP_OWNER_UNBOUND_OR_BLOCKED_BUDGET')
    need(clock(decision_at)==clock(meta.decision_asof),'EXACT_CLASSICAL_DECISION_CLOCK_REQUIRED')
    need(meta.role==role and meta.family==requirement['required_family_method'],'EXACT_CLASSICAL_ROLE_BINDING')
    cov,indices=_numeric_input(meta,payload,raw_uids)
    return membership.select(route['existing_owner'],cov[np.ix_(indices,indices)],raw_uids,raw_uids,list(range(1,41)),
        decision_at=decision_at,state_cutoff=meta.header['cutoff'])


def serialize_status(path,result):
    """One existing-run status owner; no numeric payload may be serialized."""
    assert_safe_output_path(path,kind='backtest',paths=resolve(Path(__file__).resolve().parents[4]))
    need(Path(path).resolve().is_relative_to(RUN.resolve()),'EXACT_C14_STATUS_OWNER_REQUIRED')
    def inspect(value):
        if isinstance(value,dict):
            need(not (set(k.lower() for k in value)&NUMERIC_FIELDS),'NO_NUMERIC_RESULT_IN_METADATA_STATUS')
            for v in value.values(): inspect(v)
        elif isinstance(value,(list,tuple)):
            for v in value: inspect(v)
    inspect(result)
    text=json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n'
    target=Path(path); temporary=target.with_suffix(target.suffix+'.tmp')
    temporary.write_text(text,encoding='utf-8'); temporary.replace(target)

@dataclass(frozen=True)
class PublicationBinding:
    """Sealed source-only original R5 publication; numerical PSD is still unknown."""
    plan: dict
    support: dict
    bank: dict
    refs: dict
    continuity: dict
    _seal: str = field(init=False,repr=False)
    def __post_init__(self):
        object.__setattr__(self,'_seal',content_hash({k:v for k,v in self.__dict__.items() if k!='_seal'}))
    def verify(self):
        need(self._seal==content_hash({k:v for k,v in self.__dict__.items() if k!='_seal'}),'MUTATED_PUBLICATION_METADATA')
        for reference in self.refs.values():
            p=Path(reference['path'])
            need(p.is_absolute() and p.drive.upper()=='D:' and
                 (p.resolve().is_relative_to(contract.B_RUN.resolve()) or p.resolve().is_relative_to(Path(__file__).resolve().parents[4])),
                 'ORIGINAL_R5_CUSTODY_REFERENCE_ONLY')
            need(sha(p)==reference['sha256'],'PUBLICATION_PHYSICAL_PIN_CHANGED')


R5_PLAN_SHA = '97dd4d91560bc80885eea511adb89a7bced2b52882bed26ddfefb0694aca54f0'
CHAIN_OWNER_SHA = '58f6f272039f990abb050393cdfacbb952772970bd7968156fcd0c2c426050a7'
EVENT_CONTRACT_SHA = 'ef17df6d655cc25796613282a87c8f04fe9ade62cf815c3ce06d22dd245a0b90'
RM_UNBOUND_BINDING = dict(parent_risk='RM', family='MULTI_HORIZON',
    method='R5::MULTI_HORIZON::UNBOUND_3_10_20',
    representation='EVENT_CLASSICAL_WITH_PRIOR_COMPLETION',
    recipe_sha256='513bd58da78a2183731927c72d74023d345b2adf0a968d719f922d0a60a83eb7',
    producer_sha256='cf4ad7274a1c9f5aa1e598f01edebab19db0b1b801bb6476eb36885fc61c9eeb',
    availability='BLOCKED_UNBOUND_HORIZONS')


def qualify_original_r5_chain(plan, support, bank, **kwargs):
    """Reuse the pinned source-only owner with one declared RM roster correction.

    The native plan includes 16 executable families plus a seventeenth binding
    explicitly blocked as unbound RM. Original metadata, helpers and kernel code
    stay unchanged; the existing isolated kernel binder corrects only the legacy
    equal-roster assertion. RM remains unbound and cannot produce a numeric role.
    """
    bindings=plan['method_bindings']
    if not any(v.get('family')=='MULTI_HORIZON' for v in bindings):
        return chain_owner.qualify_chain(plan,support,bank,**kwargs)
    declared=plan['risk_families']
    extras={v['family'] for v in bindings}-set(declared)
    if not extras:
        return chain_owner.qualify_chain(plan,support,bank,**kwargs)
    from scripts.research.a2.risk import event_risk_contract_r5 as event
    required=set(event.FAMILIES); refs=kwargs['pinned_refs']
    owner_path=Path(chain_owner.__file__).resolve(); event_path=Path(event.__file__).resolve()
    def pinned(path, expected):
        matches=[h for p,h in kwargs['expected_code_pins'].items() if Path(p).resolve()==path]
        observed=[h for p,h in kwargs['observed_code_pins'].items() if Path(p).resolve()==path]
        need(matches==observed==[expected] and sha(path)==expected,'EXACT_R5_ROSTER_KERNEL_CLOSURE_REQUIRED')
    pinned(owner_path,CHAIN_OWNER_SHA); pinned(event_path,EVENT_CONTRACT_SHA)
    need(Path(refs['plan']['path']).resolve()==(contract.B_RUN/'R5_FINITE_EVENT_RISK_PLAN.json').resolve()
         and refs['plan']['sha256']==R5_PLAN_SHA,'EXACT_FROZEN_R5_ROSTER_PLAN_PIN_REQUIRED')
    def prove():
        need(tuple(declared)==tuple(event.FAMILIES) and len(set(declared))==16,
             'ALL16_NATIVE_EXECUTABLE_FAMILIES_REQUIRED')
        names=[v['family'] for v in bindings]
        need(len(names)==17 and len(set(names))==17 and set(names)==required|{'MULTI_HORIZON'},
             'ONLY_EXPLICIT_UNBOUND_RM_ROSTER_SENTINEL_ALLOWED')
        sentinel=[v for v in bindings if v['family']=='MULTI_HORIZON']
        need(sentinel==[RM_UNBOUND_BINDING] and refs['model_producer']['sha256']==sentinel[0]['producer_sha256'],
             'EXACT_LITERAL_BLOCKED_RM_BINDING_REQUIRED')
        need(plan.get('unbound_parent_RM_role_is_not_additional_research_family') is True
             and type(plan.get('RM_new_fit_units')) is int and plan['RM_new_fit_units']==0,
             'RM_NOT_A_RESEARCH_FAMILY_AND_ZERO_FIT_UNITS_REQUIRED')
        need({f for n in plan['nodes'] for f in n['families']}==required
             and plan['estimator_recipes'] and all(set(r.get('method_ids',{}))==required
                 for r in plan['estimator_recipes'].values()),'EXACT16_NODE_AND_RECIPE_FAMILIES_NO_RM_REQUIRED')
        need(all(r.get('family') in required for r in bank['states']+bank['blocked_or_failed']),
             'NO_RM_OR_UNKNOWN_BANK_STATE_ALLOWED')
    prove(); corrections=[]
    def corrected_need(condition,reason):
        if condition is False and reason=='ALL_FROZEN_FAMILIES_MUST_REMAIN_IN_REPORT':
            prove(); need(not corrections,'ONLY_ONE_RM_ROSTER_ASSERTION_CORRECTION_ALLOWED')
            corrections.append(reason); return
        return chain_owner._need(condition,reason)
    kernel=event.bind_pinned_kernel(chain_owner.qualify_chain,physical_path=owner_path,
        expected_sha256=CHAIN_OWNER_SHA,dependencies={'_need':corrected_need})
    result=kernel(plan,support,bank,**kwargs)
    need(corrections==['ALL_FROZEN_FAMILIES_MUST_REMAIN_IN_REPORT'],
         'EXACT_SINGLE_LEGACY_ROSTER_ASSERTION_REQUIRED')
    for name,value in (('plan',plan),('support',support),('bank',bank)):
        need(content_hash(value)==kwargs['expected_content_sha256'][name],'NATIVE_ROSTER_INPUT_METADATA_MUTATED:'+name)
    family=result['family_continuity']
    need(set(family)==required|{'MULTI_HORIZON'} and family['MULTI_HORIZON']==dict(
        scope='UNBOUND_SOURCE',continuous_chain=False,qualified_days=0,
        first_input_blocker={'reason':'RM_3_10_20_HORIZON_SOURCE_UNBOUND'}),
        'ALL16_FAMILIES_AND_NATIVE_RM_UNBOUND_REPORT_REQUIRED')
    need(result['source_only_qualification'] is True and result['real_numeric_reads']==0
         and result['strict_PIT_promotion_eligible'] is False and result['daily_domain_count']==752,
         'SOURCE_ONLY752_ORIGINAL_SCIENTIFIC_LOCKS_REQUIRED')
    result['metadata_compatibility_correction']=dict(status='DECLARED_RM_SENTINEL_ROSTER_CORRECTION',
        owner_ref={'path':str(owner_path),'sha256':CHAIN_OWNER_SHA},
        dependency='_need',corrected_reason=corrections[0],original_kernel_code_reused=True,
        original_module_and_helper_globals_unchanged=True,original_input_metadata_unchanged=True,
        RM_scope='UNBOUND_SOURCE',RM_new_fit_units=0,RM_numeric_admission=False)
    return result


def qualify_publication(plan,support,bank,freeze,qualification,ledger,*,refs,expected_content_sha256,expected_code_pins,observed_code_pins):
    """Global source custody first, then independent per-family continuous coverage."""
    need(freeze.get('schema')=='B_R5_SCIENCE_AND_EXECUTION_FREEZE_V1' and
         freeze.get('research_id')==B_ID and freeze.get('status')=='FROZEN_BEFORE_NUMERIC' and
         freeze.get('test2026_reads')==0,'FORMAL_R5_SCIENCE_FREEZE_REQUIRED')
    need(Path(refs['bank']['path']).resolve()==(contract.B_RUN/contract.FILES['bank']).resolve()
         and Path(refs['freeze']['path']).resolve()==(contract.B_RUN/contract.FILES['freeze']).resolve(),
         'EXACT_FORMAL_R5_PUBLICATION_FILES_REQUIRED')
    need(bank.get('account_attempts')==0 and bank.get('test2026_rows_read')==0,
         'R5_NO_ACCOUNT_OR2026_CONSUMPTION_REQUIRED')
    need(freeze['source_authority_ref']==refs['source_authority'] and
         freeze['plan_ref']==refs['plan'] and freeze['support_ref']==refs['support']
         and bank['qualification_ref']==freeze['qualification_ref']==refs['qualification']
         and bank['ledger_ref']==refs['ledger'],'BANK_FREEZE_QUALIFICATION_LEDGER_CUSTODY_REQUIRED')
    need(qualification.get('schema')=='B_R5_FINITE_EVENT_RISK_QUALIFICATION_V1' and
         qualification.get('research_id')==B_ID and qualification['plan_ref']==refs['plan']
         and qualification['support_ref']==refs['support'] and qualification['model_producer_ref']==refs['model_producer'],
         'EXACT_R5_SOURCE_QUALIFICATION_SCHEMA_AND_REFS')
    need(ledger.get('status')=='B_R5_FINITE_EVENT_RISK_QUEUE_COMPLETE' and
         ledger.get('new_fit_units')==bank['new_fit_units'] and
         ledger.get('risk_fit_units')==bank['new_fit_units'] and
         ledger.get('fit_attempts')==bank['cumulative_fit_units'] and
         ledger.get('inherited_fit_units')==3027 and ledger.get('test2026_rows_read')==0 and
         ledger.get('account_paths')==0,'TERMINAL_OWNER_LEDGER_REQUIRED')
    records=ledger.get('records',[])
    need(bank['states']==[r for r in records if r.get('status')=='PASS_FROZEN_HISTORY_MECHANISM' and r.get('finite_check')]
         and bank['blocked_or_failed']==[r for r in records if r not in bank['states']],
         'ALL_FAILED_AND_BLOCKED_OWNER_RECORDS_MUST_REMAIN')
    closure={p['path']:p['sha256'] for p in freeze['source_code_pins']}
    need(closure==expected_code_pins==observed_code_pins,'EXACT_FORMAL_R5_CODE_CLOSURE_REQUIRED')
    result=qualify_original_r5_chain(plan,support,bank,pinned_refs=refs,
        expected_content_sha256=expected_content_sha256,expected_code_pins=expected_code_pins,
        observed_code_pins=observed_code_pins)
    need(result['real_numeric_reads']==0 and result['source_only_qualification'] is True,'METADATA_ONLY_CHAIN_REQUIRED')
    publication=PublicationBinding(copy.deepcopy(plan),copy.deepcopy(support),copy.deepcopy(bank),copy.deepcopy(refs),result)
    publication.verify()
    return publication


def project_r5_role(publication,requirement,*,current,decision_asof):
    """Map the real bank's native fields after its original qualified event chain.

    State use time is the original frozen-history event Close replay assumption,
    not physical publication time or strict historical availability. Source time
    remains the native SourceReceipt clock and must be <= the history cutoff.
    """
    publication.verify(); family=requirement['required_family_method']; at=clock(decision_asof)
    need(requirement['current_status']=='WAITING_R5_PUBLICATION','BLOCKED_BY_CURRENT_B_SCOPE')
    continuity=publication.continuity['family_continuity'][family]
    need(continuity['continuous_chain'] is True and continuity['qualified_days']==752,
         'COMPLETE752_CURRENT_FAMILY_CHAIN_REQUIRED')
    day=next((d for d in publication.support['daily_support_chain'] if clock(d['decision_asof'])==at),None)
    need(day is not None,'EXACT_CURRENT_DECISION_EVENT_REQUIRED')
    dep='FF48' if family=='FF48_HIERARCHICAL' else 'PRIMARY'; local=day['dependency_local_event_ids'][dep]
    found=[r for r in publication.bank['states'] if r['family']==family and r['dependency_local_event_id']==local]
    need(len(found)==1,'ONE_EXACT_NATIVE_STATE_PER_CURRENT_EVENT_REQUIRED'); record=found[0]
    bindings=[b for b in publication.plan['method_bindings'] if b['family']==family and b['method']==record['method']]
    need(len(bindings)==1,'ONE_EXACT_NATIVE_METHOD_BINDING_REQUIRED'); binding=bindings[0]
    recipe=publication.plan['estimator_recipes'][record['recipe_id']]
    need(content_hash(recipe)==binding['recipe_sha256'],'EXACT_NATIVE_RECIPE_PIN_REQUIRED')
    receipt=record['source_receipt']
    need(clock(receipt['available_at'])<=clock(record['cutoff'])<clock(record['as_of'])<=at,
         'NATIVE_SOURCE_CLOCK_AND_EVENT_REPLAY_BOUNDARY')
    need(receipt.get('observation_time_assumed') is True and receipt.get('strict_PIT_promotion_eligible') is False
         and receipt.get('return_coordinate')==current['security_coordinate'],'ORIGINAL_MECHANISM_SOURCE_TIME_ONLY')
    header={k:copy.deepcopy(record[k]) for k in ('family','status','assets','asset_uids','asset_epochs','as_of','cutoff','method',
        'artifact_ref','risk_state_id','event_policy_binding','source_support_identity','covariance_sha256','finite_check')}
    dates=[pd.Timestamp(d['decision_asof']).tz_convert('UTC').tz_localize(None).normalize().isoformat()
           for d in publication.support['daily_support_chain']]
    need(dates==requirement['required_dates'],'R5_AND_C14_EXACT752_DATE_MASK_MISMATCH')
    header.update(strict_PIT_promotion_eligible=False,recipe_sha256=binding['recipe_sha256'],horizon_sessions=5,
        structural_identity=record['event_policy_binding']['structural_identity'],source_still_valid=True,maturity_still_valid=True,
        security_coordinate=receipt['return_coordinate'],available_at=record['as_of'],
        source_available_at=receipt['available_at'],available_at_basis='FROZEN_EVENT_CLOSE_REPLAY_ASSUMPTION',
        parameters=copy.deepcopy(recipe),history_recipe=copy.deepcopy(recipe),representation='CONTINUOUS',
        coverage_dates=dates,psd_qualified='DEFERRED_NUMERIC_EXACT_OWNER_CHECK',
        covariance_digest_status='DEFERRED_FROM_EXACT_PINNED_STATE' if record['covariance_sha256'] is None else 'NATIVE_EXPORTER_DIGEST_PRESENT')
    native_binding=dict(family=family,method=record['method'],recipe_sha256=binding['recipe_sha256'],
        parameters=copy.deepcopy(recipe),history_recipe=copy.deepcopy(recipe),representation='CONTINUOUS')
    refs={k:copy.deepcopy(publication.refs[k]) for k in ('bank','freeze','qualification','ledger')}
    return bind_role_metadata(requirement,header,current,decision_asof,native_binding,refs,required_dates=requirement['required_dates'])


def load_qualified_state(meta,publication,*,source_review):
    """Future explicit numeric consumer entry; never called by prebind acceptance."""
    need(source_review.get('status')=='PASS' and source_review.get('research_id')==contract.ID
         and source_review.get('adapter_sha256')==sha(__file__),'INDEPENDENT_EXACT_ADAPTER_REVIEW_REQUIRED')
    meta.verify(); publication.verify()
    need(meta.header.get('available_at_basis')=='FROZEN_EVENT_CLOSE_REPLAY_ASSUMPTION','ORIGINAL_EVENT_METADATA_BINDING_REQUIRED')
    need(meta.publication_refs=={k:publication.refs[k] for k in ('bank','freeze','qualification','ledger')},
         'EXACT_REVIEWED_PUBLICATION_BINDING_REQUIRED')
    original=[r for r in publication.bank['states'] if r['risk_state_id']==meta.header['risk_state_id']]
    need(len(original)==1 and original[0]['artifact_ref']==meta.header['artifact_ref'],'EXACT_ORIGINAL_BANK_STATE_REQUIRED')
    ref=meta.header['artifact_ref']; path=Path(ref['path'])
    need(path.is_absolute() and path.resolve().is_relative_to(contract.B_RUN.resolve()) and sha(path)==ref['sha256'],
         'ORIGINAL_R5_STATE_PHYSICAL_SHA_REQUIRED')
    import joblib
    from scripts.research.a2.risk.shared_risk_engine_r2 import RiskState
    state=joblib.load(path)
    need(type(state) is RiskState and state.status=='PASS_FROZEN_HISTORY_MECHANISM' and state.method==meta.header['method']
         and state.risk_state_id==meta.header['risk_state_id'] and state.horizon==5
         and list(state.assets)==meta.current['assets'] and clock(state.cutoff)==clock(meta.header['cutoff'])
         and clock(state.as_of)==clock(meta.header['as_of'])
         and state.notes['event_policy_binding']==meta.header['event_policy_binding'], 'TYPED_NATIVE_R5_STATE_BINDING_MISMATCH')
    need(set(state.coverage)==set(state.assets) and all(state.coverage[a]['uid']==meta.current['asset_uids'][a]
         and state.coverage[a]['identity_epoch']==meta.current['asset_epochs'][a] for a in state.assets),
         'EXACT_NATIVE_FULL_U_COVERAGE_UID_EPOCH_REQUIRED')
    from scripts.research.a2.evaluation.joint_frozen_history_risk_r3 import _json as native_json
    receipt=native_json(state.source_receipt)
    need(receipt==original[0]['source_receipt'] and state.return_coordinate==meta.current['security_coordinate'],
         'EXACT_NATIVE_SOURCE_RECEIPT_AND_COORDINATE_REQUIRED')
    lineage=state.notes.get('estimator_lineage',{})
    need(lineage.get('recipe_sha256')==meta.recipe_sha256 and
         lineage.get('source_support_identity_sha256')==content_hash(meta.current['source_support_identity']),
         'EXACT_NATIVE_ESTIMATOR_SOURCE_RECIPE_REQUIRED')
    payload=dict(family=meta.family,ordered_U=list(state.assets),uids=meta.current['asset_uids'],epochs=meta.current['asset_epochs'],
        covariance=state.covariance,state_id=state.risk_state_id,method=state.method,recipe_sha256=meta.recipe_sha256,
        horizon_sessions=state.horizon,cutoff=meta.header['cutoff'],as_of=meta.header['as_of'],
        source_support_identity=meta.current['source_support_identity'],parameters=meta.parameters)
    validate_covariance(np.asarray(state.covariance,float),regularize=False)
    digest=content_hash(state.covariance)
    if meta.header['covariance_sha256'] is not None:
        need(digest==meta.header['covariance_sha256'],'NATIVE_COVARIANCE_CONTENT_SHA_MISMATCH')
    return NativeRiskPayload(payload,meta._seal,copy.deepcopy(ref),digest)


def read_publication_metadata():
    """Single source-only entry: absent bank returns without further dependency reads.

    Recovery qualification is handled by its existing original R5 bounded owner,
    preserving the original qualification and its retained-node recovery proof.
    No state or cache artifact is opened here.
    """
    ready=contract.readiness()
    if ready['status']!='PUBLISHED_METADATA_REVIEW_REQUIRED':
        return dict(status='WAITING_R5_PUBLICATION',readiness=ready,publication=None,
                    counts={k:0 for k in COUNTERS})
    def ref(path): return dict(path=str(path),sha256=sha(path))
    freeze_ref=ref(contract.B_RUN/contract.FILES['freeze'])
    freeze=read_r5_metadata(freeze_ref)
    bank_ref=ref(contract.B_RUN/contract.FILES['bank'])
    bank=read_r5_metadata(bank_ref)
    refs={name:copy.deepcopy(bank[field]) for name,field in chain_owner.REF_FIELDS.items()}
    refs.update(bank=bank_ref,freeze=freeze_ref,qualification=copy.deepcopy(bank['qualification_ref']),
                ledger=copy.deepcopy(bank['ledger_ref']))
    need(freeze['qualification_ref']==refs['qualification'],'EXACT_FREEZE_QUALIFICATION_REF_REQUIRED')
    closure={p['path']:p['sha256'] for p in freeze['source_code_pins']}
    repo=Path(__file__).resolve().parents[4]
    need(all(Path(p).is_absolute() and Path(p).drive.upper()=='D:' and Path(p).resolve().is_relative_to(repo)
             for p in closure),'PINNED_ORIGINAL_R5_REPOSITORY_CODE_ONLY')
    observed={p:sha(p) for p in closure}
    need(observed==closure,'EXACT_FORMAL_R5_CODE_CLOSURE_REQUIRED')
    for name in ('model_producer','execution_producer'):
        need(closure.get(refs[name]['path'])==refs[name]['sha256'],'EXACT_FROZEN_PRODUCER_REQUIRED')
    plan=read_r5_metadata(refs['plan']); support=read_r5_metadata(refs['support'])
    ledger=read_r5_metadata(refs['ledger'])
    from scripts.research.a2.evaluation.joint_event_risk_execution_r5 import read_event_qualification
    qualification=read_event_qualification(contract.B_RUN,qualification_ref=refs['qualification'])
    publication=qualify_publication(plan,support,bank,freeze,qualification,ledger,refs=refs,
        expected_content_sha256={name:content_hash(value) for name,value in (('plan',plan),('support',support),('bank',bank))},
        expected_code_pins=closure,observed_code_pins=observed)
    return dict(status='SOURCE_ONLY_PUBLICATION_QUALIFIED',publication=publication,
                counts={k:0 for k in COUNTERS},numeric_execution_performed=False)
