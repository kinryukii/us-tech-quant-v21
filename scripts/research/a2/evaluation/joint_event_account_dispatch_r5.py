"""Qualification-before-replay dispatch to the unchanged continuous account.

Caller-owned inputs only. Real use requires accepted R5 numeric activation and
physical, frozen source-only qualification evidence. This module neither reads
forecasts/quotes nor implements allocation, valuation, completion or accounting.
"""
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Mapping
import hashlib
import pandas as pd
from scripts.common import storage_paths
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.evaluation import joint_frozen_history_r3 as owner
from scripts.research.a2.evaluation.joint_control_sensitivity_r4 import SensitivityFreeze
from scripts.research.a2.evaluation import joint_r5_runtime as runtime
from scripts.research.a2.inference import joint_event_policy_r5 as policy
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash

CONTINUOUS_FAMILIES = frozenset(('SHR_HP', 'SHR_CC', 'LW', 'OAS', 'EWMA', 'PCA_FACTOR', 'QQQ_RESIDUAL'))
PROOF_GATES = (
    'forecast_complete_eligible_union_actual_held', 'full_752_session_risk_chain',
    'current_full_pool_uid_epoch', 'execution_quote_dependency_support',
    'event_rights_coordinate_support', 'account_coordinate_source_support',
    'unsupported_events_and_quality_constraints_preserved', 'unchanged_full_held_domain')
REF_NAMES = frozenset(('whole_freeze', 'plan', 'bank', 'registration', 'source_authority',
    'parent_account_freeze', 'parent_policy_binding', 'qualification',
    'family_freeze', 'prediction_clarification', 'alpha_reuse', 'registration_patch'))


class EventAccountDispatchBlocked(owner.FrozenHistoryAccountBlocked):
    pass


def _check(value, reason):
    if not value:
        raise EventAccountDispatchBlocked(reason)


def source_pins():
    """Hash code only; reuse the existing account and policy dependency closures."""
    pins = {**owner.source_pins(), **policy.source_pins()}
    for path in (Path(runtime.__file__), Path(runtime.parent.__file__),
                 Path(storage_paths.__file__), Path(__file__),
                 Path(__file__).with_name('joint_control_sensitivity_r4.py')):
        path = path.resolve()
        pins[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return pins


def code_pins():
    """Consumer closure for the whole freeze; registry remains a live admission gate."""
    return [dict(path=path, sha256=value) for path, value in sorted(source_pins().items())]


@dataclass(frozen=True)
class PhysicalRef:
    path: str
    sha256: str


@dataclass(frozen=True)
class EventPathQualification:
    path_id: str
    row_sha256: str
    parent_row_sha256: str
    risk_method: str
    family: str
    gates: Mapping[str, bool]
    forecast_support_sha256: str
    risk_chain_support_sha256: str
    coordinate_support_sha256: str


@dataclass(frozen=True)
class EventAccountQualification:
    """Already frozen dependency qualification; never inferred from risk names.

    The proof must cover actual held requirements without deleting keys. Each
    policy invocation rechecks those actual requirements in the original owner.
    Input support here confers no certified-quote, NAV or PIT qualification.
    """
    research_id: str
    run_id: str
    contract_sha256: str
    activation_sha256: str
    parent_account_freeze_sha256: str
    whole_freeze_sha256: str
    plan_sha256: str
    bank_sha256: str
    source_authority_sha256: str
    input_sha256: Mapping[str, str]
    decision_calendar_sha256: str
    legal_sessions: tuple[str, ...]
    forecast_lineage_sha256: str
    paths: tuple[EventPathQualification, ...]
    session_count: int = 752
    status: str = 'QUALIFIED_FROZEN_MECHANISM_INPUTS_UNCERTIFIED'
    strict_PIT_promotion_eligible: bool = False
    quote_qualified: bool = False
    certified_NAV: bool = False

    def digest(self):
        return content_hash(self)


@dataclass(frozen=True)
class EventAccountDispatchFreeze:
    research_id: str
    run_id: str
    contract_sha256: str
    activation_sha256: str
    qualification_sha256: str
    parent_account_freeze_sha256: str
    path_ids: tuple[str, ...]
    cost_bps: int
    refs: Mapping[str, PhysicalRef]
    source_sha256: Mapping[str, str]
    status: str = 'FROZEN_BEFORE_ACCOUNT_REPLAY'
    scientific_retry: int = 0
    strict_PIT_promotion_eligible: bool = False
    quote_qualified: bool = False
    certified_NAV: bool = False

    def digest(self):
        return content_hash(self)


@dataclass(frozen=True)
class EventAccountDispatchResult:
    replay: object
    qualification_by_path: Mapping[str, object]
    dispatch_freeze_sha256: str
    account_freeze_sha256: str
    physical_account_replays: int
    physical_fit_count: int = 0



def _registration_guard(run, freeze, receipt, patch):
    """Bind the canonical apply receipt to its R5 single-entity patch, not a new schema."""
    ref = freeze.refs['registration']
    _check(Path(ref.path).resolve() == (Path(run) / 'REGISTRATION_RECEIPT.json').resolve() and
           Path(freeze.refs['registration_patch'].path).resolve().is_relative_to(Path(run).resolve()),
           'CURRENT_R5_REGISTRATION_CUSTODY_REQUIRED')
    event, manifest = receipt.get('event', {}), receipt.get('manifest', {})
    head, patch_sha = receipt.get('head_sha256'), freeze.refs['registration_patch'].sha256
    _check(receipt.get('status') == 'PASS' and policy.ad._sha(head) and
           event.get('event_type') == 'APPLY_PATCH' and event.get('new_head_sha256') == head and
           manifest.get('snapshot_sha256') == head and
           event.get('patch_sha256') == manifest.get('patch_sha256') == patch_sha,
           'CANONICAL_APPLY_RECEIPT_PATCH_HEAD_BINDING_REQUIRED')
    operations = patch.get('operations', ())
    _check(len(operations) == 1 and operations[0].get('op') == 'add_entity',
           'CANONICAL_SINGLE_R5_REGISTRATION_PATCH_REQUIRED')
    entity = operations[0].get('entity', {}); metadata = entity.get('metadata', {})
    _check(entity.get('entity_id') == entity.get('canonical_name') == runtime.ID and
           entity.get('parent_entity_id') == operations[0].get('parent_entity_id') ==
               'V24_B_JOINT_MAXIMAL_BREADTH_PRE2026_R4' and
           entity.get('status') == 'OPEN' and metadata.get('event_science_freeze_sha256') ==
               freeze.refs['whole_freeze'].sha256 and metadata.get('event_source_authority_sha256') ==
               freeze.refs['source_authority'].sha256 and
           all(metadata.get(k) is False for k in ('fit_authority', 'formal_freeze_authority',
                                                'strict_PIT_promotion_eligible')),
           'EXACT_R5_REGISTRATION_OWNER_SCIENCE_SOURCE_REQUIRED')


def _physical_bindings(run, freeze, qualification, parent_freeze, dispatch_ref, activation, contract):
    """Existing bounded metadata reader and physical pinning; no bank decoding."""
    _check(isinstance(dispatch_ref, PhysicalRef), 'PUBLISHED_DISPATCH_FREEZE_REQUIRED')
    paths = resolve(runtime.parent.REPO)
    for ref in (*freeze.refs.values(), dispatch_ref):
        _check(isinstance(ref, PhysicalRef) and policy.ad._sha(ref.sha256) and
               Path(ref.path).is_absolute(), 'EXACT_PHYSICAL_METADATA_REF_REQUIRED')
        assert_safe_output_path(ref.path, kind='backtest', paths=paths)
        runtime.parent._pin(ref.path, ref.sha256, 'R5_ACCOUNT_DEPENDENCY')
    for ref, value in ((dispatch_ref, freeze), (freeze.refs['qualification'], qualification),
                       (freeze.refs['parent_account_freeze'], parent_freeze)):
        _check(Path(ref.path).stat().st_size <= 64 * 1024, 'COMPACT_FROZEN_ACCOUNT_PROOF_REQUIRED')
        _check(content_hash(runtime.parent.read_json(ref.path)) == content_hash(asdict(value)),
               'PUBLISHED_ACCOUNT_PROOF_BODY_MISMATCH')
    _check(Path(freeze.refs['whole_freeze'].path).resolve() ==
           (Path(run) / 'R5_SCIENCE_AND_EXECUTION_FREEZE.json').resolve() and
           Path(freeze.refs['source_authority'].path).resolve() ==
           (Path(run) / 'SOURCE_AUTHORITY.json').resolve() and
           Path(freeze.refs['plan'].path).resolve() ==
           (Path(run) / 'R5_FINITE_EVENT_RISK_PLAN.json').resolve(), 'CURRENT_R5_SOURCE_SCIENCE_PLAN_REQUIRED')
    _registration_guard(run, freeze, runtime.parent.read_json(freeze.refs['registration'].path),
                        runtime.parent.read_json(freeze.refs['registration_patch'].path))
    plan = runtime.parent.read_json(freeze.refs['plan'].path)
    _check(plan.get('research_id') == runtime.ID and
           frozenset(plan.get('continuous_families', ())) == CONTINUOUS_FAMILIES and
           plan.get('method_bindings') == [asdict(b) for b in activation.method_bindings],
           'EXACT_FROZEN_CONTINUOUS_FAMILY_PLAN_REQUIRED')
    parent_binding = runtime.parent.read_json(freeze.refs['parent_policy_binding'].path)
    rows, contrasts = parent_binding.get('policy_paths', ()), parent_binding.get('contrasts', ())
    _check(parent_binding.get('research_id') == runtime.ID and len(rows) == 52 and len(contrasts) == 12 and
           len(contract.parent_rows) == len(rows), 'FULL_PARENT_52_PATH_12_CONTRAST_BINDING_REQUIRED')
    for record, prior in zip(rows, contract.parent_rows):
        _check({k:record.get(k) for k in prior.__dataclass_fields__ if k != 'scope'} ==
               {k:getattr(prior,k) for k in prior.__dataclass_fields__ if k != 'scope'} and
               prior.scope == ('MAIN' if prior.cost_bps == 10 else 'SENSITIVITY_NO_SELECTION'),
               'PUBLISHED_PARENT_TUPLE_PATH_COST_OR_ORDER_CHANGED')
    _check(contract.contrast_binding_sha256 == content_hash(contrasts), 'ORIGINAL_12_CONTRASTS_CHANGED')


def _qualification_guard(freeze, proof, contract, activation, parent_freeze):
    _check(isinstance(proof, EventAccountQualification) and proof.digest() == freeze.qualification_sha256,
           'FROZEN_SOURCE_ONLY_ACCOUNT_QUALIFICATION_REQUIRED')
    _check(proof.status == 'QUALIFIED_FROZEN_MECHANISM_INPUTS_UNCERTIFIED' and
           type(proof.session_count) is int and proof.session_count == 752 and
           all(getattr(proof, k) is False for k in ('strict_PIT_promotion_eligible', 'quote_qualified', 'certified_NAV')),
           'FULL_752_UNCERTIFIED_MECHANISM_QUALIFICATION_REQUIRED')
    _check((proof.research_id, proof.run_id, proof.contract_sha256, proof.activation_sha256,
            proof.parent_account_freeze_sha256, proof.input_sha256, proof.bank_sha256,
            proof.forecast_lineage_sha256) ==
           (freeze.research_id, freeze.run_id, freeze.contract_sha256, freeze.activation_sha256,
            parent_freeze.digest(), parent_freeze.input_sha256, activation.bank_manifest_sha256,
            content_hash(contract.forecast_lineage)), 'SOURCE_ACCOUNT_FORECAST_BANK_BINDING_MISMATCH')
    for name in ('whole_freeze', 'plan', 'bank', 'source_authority'):
        _check(getattr(proof, name + '_sha256') == freeze.refs[name].sha256,
               'QUALIFICATION_PHYSICAL_DEPENDENCY_MISMATCH:' + name)
    _check(policy.ad._sha(proof.decision_calendar_sha256) and
           policy.ad.legal_calendar_sha256(proof.legal_sessions) == activation.legal_calendar_sha256,
           'SEPARATE_EXACT_DECISION_AND_SOURCE_LEGAL_CALENDARS_REQUIRED')
    policy._sessions(proof.legal_sessions)
    _check(tuple(p.path_id for p in proof.paths) == freeze.path_ids, 'EXACT_QUALIFIED_PATH_SET_REQUIRED')
    byid = {r.id: (r, prior) for r, prior in zip(contract.rows, contract.parent_rows)}
    for p in proof.paths:
        _check(isinstance(p, EventPathQualification) and p.path_id in byid,
               'EXACT_FROZEN_FAMILY_PATH_REQUIRED')
        row, prior = byid[p.path_id]
        _check(row.risk != 'NONE', 'CONTROL_EXACT_REUSE_ONLY_NO_REPEAT_REPLAY')
        b = policy._binding(activation.method_bindings, row.risk)
        _check(b.availability == 'READY' and b.family in CONTINUOUS_FAMILIES,
               'RM_CVAR_AND_ANCHOR_ONLY_FAMILIES_CANNOT_DISPATCH_FULL_CHAIN')
        _check((p.row_sha256, p.parent_row_sha256, p.risk_method, p.family) ==
               (content_hash(row), content_hash(prior), b.method, b.family) and
               row.cost_bps == freeze.cost_bps, 'EXACT_PARENT_TUPLE_PATH_COST_REQUIRED')
        _check(set(p.gates) == set(PROOF_GATES) and all(p.gates[k] is True for k in PROOF_GATES),
               'INCOMPLETE_REQUIRED_FORECAST_RISK_UID_QUOTE_EVENT_ACCOUNT_SUPPORT')
        _check(all(policy.ad._sha(s) for s in (p.forecast_support_sha256,
               p.risk_chain_support_sha256, p.coordinate_support_sha256)), 'EXACT_PATH_SUPPORT_PROOFS_REQUIRED')


def run_event_family_account(market, raw_scores, *, event_inputs, uncertified_quality_only,
        parent_freeze, contract, activation, input_provider, qualification, freeze,
        expected_dispatch_sha256, run=None, dispatch_ref=None, synthetic=False):
    """One cost-bound batch, one unchanged persistent engine, zero fits.

    In real mode numeric activation precedes *all* input-body access. No files
    are written here. Support discovery cannot mint a replay token. A caller
    publishes the already qualified freeze only after independent source proof.
    """
    _check(type(synthetic) is bool and isinstance(freeze, EventAccountDispatchFreeze),
           'TYPED_FROZEN_EVENT_ACCOUNT_DISPATCH_REQUIRED')
    _check(freeze.digest() == expected_dispatch_sha256 and policy.ad._sha(expected_dispatch_sha256) and
           freeze.status == 'FROZEN_BEFORE_ACCOUNT_REPLAY' and type(freeze.scientific_retry) is int and
           freeze.scientific_retry == 0 and all(getattr(freeze, k) is False for k in
           ('strict_PIT_promotion_eligible', 'quote_qualified', 'certified_NAV')),
           'IMMUTABLE_UNCERTIFIED_NO_RETRY_ACCOUNT_DISPATCH_REQUIRED')
    _check(set(freeze.refs) == REF_NAMES and all(isinstance(r, PhysicalRef) and
           policy.ad._sha(r.sha256) for r in freeze.refs.values()), 'COMPLETE_FROZEN_ACCOUNT_DEPENDENCIES_REQUIRED')
    if not synthetic:
        _check(run is not None, 'CURRENT_R5_RUN_REQUIRED')
        runtime.guard(run, numeric=True, expected_freeze_sha256=freeze.refs['whole_freeze'].sha256)
    _check(isinstance(parent_freeze, owner.FrozenHistoryAccountFreeze) and
           parent_freeze.synthetic is synthetic, 'REAL_INPUTS_CANNOT_BE_DECLARED_SYNTHETIC')
    _check(isinstance(contract, policy.FrozenEventFamilyPolicyContract) and
           isinstance(activation, policy.FrozenEventMechanismActivation) and
           (freeze.research_id, freeze.run_id, freeze.contract_sha256, freeze.activation_sha256,
            freeze.parent_account_freeze_sha256) ==
           (contract.research_id, contract.run_id, contract.digest(), activation.digest(), parent_freeze.digest()) and
           (synthetic or (contract.research_id == runtime.ID and len(contract.rows) == 52)),
           'EXACT_R5_DESCENDANT_PARENT_52_PATH_CONTRACT_REQUIRED')
    _check(freeze.source_sha256 == source_pins() and
           freeze.refs['parent_policy_binding'].sha256 == contract.parent_policy_binding_sha256 and
           freeze.refs['plan'].sha256 == contract.source_contract_sha256 and
           freeze.refs['family_freeze'].sha256 == contract.family_freeze_sha256 and
           freeze.refs['prediction_clarification'].sha256 == contract.prediction_clarification_sha256 and
           freeze.refs['alpha_reuse'].sha256 == contract.alpha_reuse_receipt_sha256,
           'CURRENT_CODE_PARENT_POLICY_AND_SCIENTIFIC_PLAN_REQUIRED')
    _check(type(freeze.cost_bps) is int and freeze.cost_bps in (5, 10, 20) and
           bool(freeze.path_ids) and len(set(freeze.path_ids)) == len(freeze.path_ids),
           'EXACT_UNIQUE_COST_BOUND_ACCOUNT_PATHS_REQUIRED')
    _qualification_guard(freeze, qualification, contract, activation, parent_freeze)
    token = policy.parent.FrozenFamilyPolicyToken(contract.research_id, contract.run_id,
        contract.family_freeze_sha256, freeze.path_ids)  # SUPPORT_DISCOVERY only.
    kwargs = dict(expected_contract_sha256=freeze.contract_sha256, activation=activation,
        expected_activation_sha256=freeze.activation_sha256, input_provider=input_provider)
    obj = policy.EventFamilyPolicy(contract, token=token, expected_token_sha256=token.digest(), **kwargs)
    if not synthetic:
        # The actual producer bindings must be identical to the fixed plan.
        _physical_bindings(run, freeze, qualification, parent_freeze, dispatch_ref, activation, contract)
    owner._freeze_guard(parent_freeze, freeze.parent_account_freeze_sha256, market, raw_scores,
                        event_inputs, uncertified_quality_only)
    dates = pd.DatetimeIndex(market.dates)
    _check(len(dates) == qualification.session_count and
           content_hash(tuple(str(d.date()) for d in dates)) == qualification.decision_calendar_sha256 and
           (synthetic or (dates[0] == pd.Timestamp('2023-01-03') and dates[-1] == pd.Timestamp('2025-12-31'))),
           'EXACT_UNCHANGED_FULL_752_SESSION_ACCOUNT_DOMAIN_REQUIRED')
    legal = policy._sessions(qualification.legal_sessions)
    decisions = policy._sessions(market.signal_asof)
    _check(len(decisions) == len(dates) and (legal.get_indexer(decisions) > 0).all() and
           tuple(decisions.tz_convert('America/New_York').tz_localize(None).normalize()) == tuple(dates),
           'CURRENT_ACCOUNT_CLOSES_MUST_MATCH_PINNED_LEGAL_SOURCE_CALENDAR')
    activation.validate(freeze.activation_sha256, decisions[0])
    before = owner.input_digests(market, raw_scores, event_inputs, uncertified_quality_only)
    values = asdict(parent_freeze)
    values.update(research_id=contract.research_id, parent_research_id=parent_freeze.research_id,
        run_id=contract.run_id, registration_receipt_sha256=freeze.refs['registration'].sha256,
        one_way_friction_bps=float(freeze.cost_bps), scenario_path_ids=freeze.path_ids)
    account_freeze = SensitivityFreeze(**values)
    token = replace(token, mode='ACCOUNT_REPLAY')
    obj = policy.EventFamilyPolicy(contract, token=token, expected_token_sha256=token.digest(), **kwargs)
    replay = owner.common.run_continuous_account(market, freeze.path_ids, obj, dict(owner.ACCOUNT),
        execution_friction=obj.friction_contract(freeze.path_ids[0]), **event_inputs)
    _check(before == owner.input_digests(market, raw_scores, event_inputs, uncertified_quality_only),
           'CALLER_INPUT_MUTATION_DURING_ACCOUNT_REPLAY')
    gaps = [d for d in obj.diagnostics if d.get('block_reason')]
    result = owner._qualify(replay, market, uncertified_quality_only, account_freeze, gaps)
    return EventAccountDispatchResult(replay, result, freeze.digest(), account_freeze.digest(), len(freeze.path_ids))
