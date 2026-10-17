"""First matched new-policy account pair over immutable learned B assets.

Orchestration only. The original account, execution projection, CA convention,
forecast reader and risk-state guards own their respective business rules.
"""
from __future__ import annotations
import argparse
import copy
from dataclasses import fields, replace
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
import traceback
import time
from datetime import datetime, timezone
from types import SimpleNamespace
import numpy as np
import pandas as pd
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.inference.reused_policy_inputs import FrozenAnnualOpportunityReader, OpportunityInputUnavailable
from scripts.research.a2.inference.reused_r5_risk_inputs import ExistingRiskInputUnavailable, HeldLineageUnavailable, causal_held_domain
from scripts.research.a2.inference.reused_feasible_policy import (feasible_target, FeasiblePolicyBlocked,
    MECHANISM_PANEL_POLICIES, MECHANISM_PANEL_PROFILE, PTO_REUSE_KIND, PTO_FORECAST_RECIPE, RAW_SOURCE_REUSE_KIND)
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision

TASK = 'V24_B_REUSED_ASSET_FEASIBLE_POLICY_PAIR_R1'
CA_TASK = 'V24_B_CA_SOURCE_COMPLETION_AND_REUSED_PAIR_CONTINUATION_R1'
CAUSAL_HELD_TASK = 'V24_B_CAUSAL_HELD_SUPPORT_AND_REUSED_PAIR_R1'
FAST_TRACK_TASK = 'V24_B_FAST_TRACK_PAIR_COMPLETION_R1'
CAUSAL_INPUT_REFS = ('held_support_admission_ref', 'single_lw_approval_ref',
    'single_lw_preflight_ref', 'supplemental_lw_state_ref',
    'held_identity_source_binding_ref', 'runtime_independent_acceptance_ref')
CASH_CLOCK = 'ORDINARY_CASH_PAY_DATE_END_NEXT_ACCOUNT_SESSION'
REPO = Path('D:/us-tech-quant')
PATHS = resolve(REPO)
OLD_CACHE = Path('D:/us-tech-quant-cache/V24/V24_B_FINAL_JOINT_POLICY_ACCOUNT_AND_COVERAGE_R1/source_audit')
CUSTODY = OLD_CACHE / 'r5_existing_p2_safe_consumer_r5.py'
RUNTIME = OLD_CACHE / 'run_final_B_R5_policy_space.py'
CUSTODY_SHA = 'cf93b9b0bf82123a6268e82f224e41eb4742b23599fbdb1efdbe2bff98d2268c'
RUNTIME_SHA = '8789dbfd1245d2f44148d837f792fbf9db4914b14bac3125246d25acb99c35a3'
FLAGS = dict(strict_PIT=False, production_qualified=False, quote_qualified=False, certified_NAV=False)
PTO_ACCOUNT_PROFILE = dict(schema='B_PTO_MATCHED_SOURCE_ACCOUNT_PROFILE_V1',
    policies=[PTO_REUSE_KIND, RAW_SOURCE_REUSE_KIND],
    recipes={PTO_REUSE_KIND: PTO_FORECAST_RECIPE, RAW_SOURCE_REUSE_KIND: 'ORIGINAL_RAW_A2'},
    predictive_refits=0, cost_bps=10, sessions=752,
    raw_policy_rule_preserved=True, complete_account_only_economics=True)
TABLES = ('daily', 'positions', 'orders', 'fills', 'execution_results', 'contexts',
          'operational_actions', 'accounting_exceptions', 'entitlements')


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def pin(reference):
    path = Path(reference['path'])
    if path.drive.upper() != 'D:':
        raise ValueError('PAIR_SOURCE_OUTSIDE_APPROVED_D_ROOT')
    if sha(path) != reference['sha256']:
        raise ValueError('PAIR_FROZEN_SOURCE_CHANGED:' + str(path))
    return path


def module(path, name, *, register=False):
    # Dataclass annotation resolution needs its own private module namespace.
    # Legacy loaders keep their original unregistered behavior.
    if register and name in sys.modules:
        existing = sys.modules[name]
        if Path(getattr(existing, '__file__', '')).resolve() != Path(path).resolve():
            raise ValueError('PAIR_PRIVATE_MODULE_NAMESPACE_COLLISION')
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    if register:
        if not name.startswith('_pair_frozen_history_cash_owner_'):
            raise ValueError('PAIR_PRIVATE_CASH_MODULE_NAME_REQUIRED')
        sys.modules[name] = result
    try:
        spec.loader.exec_module(result)
    except BaseException:
        if register and sys.modules.get(name) is result:
            del sys.modules[name]
        raise
    return result



def account_custody(runtime):
    """Reuse only the exact frozen account interface and owner relocation.

    The pair does not consume the legacy P2 slot/model adapters. Their import
    chain must not require unused current selector or fusion source identities.
    The selected relocation functions retain their frozen source bodies.
    """
    import ast
    import builtins
    import types
    pin({'path': str(CUSTODY), 'sha256': CUSTODY_SHA})
    pin({'path': str(RUNTIME), 'sha256': RUNTIME_SHA})
    if Path(getattr(runtime, '__file__', '')).resolve() != RUNTIME.resolve():
        raise ValueError('PAIR_EXACT_ORIGINAL_ACCOUNT_RUNTIME_REQUIRED')
    constants = {'_R5_ROOT', '_CANONICAL_OWNER', '_RECOVERED_OWNER',
                 '_OWNER_SHA', '_METADATA_OWNER_SHA', '_METADATA_ROLE', '_RECOVERY'}
    functions = {'_r5_sha', '_clone', '_private_module_functions',
                 'relocation_descriptor', 'load_interface'}
    selected = []
    found_constants = []; found_functions = []
    for node in ast.parse(CUSTODY.read_text(encoding='utf-8-sig')).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in constants):
            found_constants.append(node.targets[0].id); selected.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in functions:
            found_functions.append(node.name); selected.append(node)
    if (set(found_constants) != constants or len(found_constants) != len(constants)
            or set(found_functions) != functions or len(found_functions) != len(functions)):
        raise ValueError('PAIR_FROZEN_ACCOUNT_CUSTODY_FUNCTION_SET_CHANGED')
    namespace = dict(__file__=str(CUSTODY), __name__='_pair_original_account_custody',
                     builtins=builtins, hashlib=hashlib, importlib=importlib,
                     types=types, Path=Path, previous=SimpleNamespace(old=runtime))
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(CUSTODY), 'exec'), namespace)
    # Both references remain required by the original relocation. Unconsumed
    # r2-r4 P2 kernel checks are not imported by this account pair.
    pin({'path': str(namespace['_RECOVERED_OWNER']), 'sha256': namespace['_OWNER_SHA']})
    pin(namespace['_RECOVERY'])
    return SimpleNamespace(load_interface=namespace['load_interface'],
                           relocation_descriptor=namespace['relocation_descriptor'],
                           account_custody_source_ref=dict(path=str(CUSTODY), sha256=CUSTODY_SHA))


def json_safe(value):
    if isinstance(value, dict): return {str(k): json_safe(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)): return [json_safe(v) for v in value]
    if isinstance(value, np.ndarray): return json_safe(value.tolist())
    if isinstance(value, np.generic): return json_safe(value.item())
    if isinstance(value, (pd.Timestamp, Path)): return str(value)
    if isinstance(value, float) and not np.isfinite(value): return None
    return value


def write(path, value):
    path = Path(path)
    kind = 'backtest' if path.is_relative_to(PATHS.backtest_root) else 'results'
    assert_safe_output_path(path, kind=kind, paths=PATHS)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(json_safe(value), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()
    if path.exists():
        if path.read_bytes() != raw: raise ValueError('IMMUTABLE_PAIR_OUTPUT_ALREADY_EXISTS:' + str(path))
    else:
        with path.open('xb') as handle: handle.write(raw)
    return dict(path=str(path), sha256=sha(path))


def claim_account_output_scope(run, freeze, task_id, *, paths=PATHS):
    """Claim only an output namespace inside the unchanged managed run.

    Omission preserves every original output path. The declared engineering
    namespace is covered by the independently reviewed freeze; atomic directory
    creation prevents a second invocation from reusing or overwriting it.
    """
    run = Path(run)
    if 'account_output_namespace' not in freeze:
        return run
    namespace = freeze['account_output_namespace']
    if (task_id not in (CAUSAL_HELD_TASK, FAST_TRACK_TASK) or not isinstance(namespace, str)
            or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', namespace) is None
            or namespace.upper() in {'CON','PRN','AUX','NUL'}
            or re.fullmatch(r'(?:COM|LPT)[1-9]', namespace.upper()) is not None):
        raise ValueError('SAFE_DECLARED_CAUSAL_ACCOUNT_OUTPUT_NAMESPACE_REQUIRED')
    if run.drive.upper() != 'D:':
        raise ValueError('LITERAL_D_ACCOUNT_OUTPUT_RUN_REQUIRED_BEFORE_IO')
    if Path(freeze['run']).resolve() != run.resolve():
        raise ValueError('UNCHANGED_MANAGED_RUN_IDENTITY_REQUIRED')
    output = run / 'account_invocations' / namespace
    assert_safe_output_path(output, kind='backtest', paths=paths)
    if not output.resolve().is_relative_to(run.resolve()):
        raise ValueError('ACCOUNT_OUTPUT_NAMESPACE_ESCAPES_MANAGED_RUN')
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        output.mkdir()
    except FileExistsError as error:
        raise ValueError('ACCOUNT_OUTPUT_NAMESPACE_ALREADY_CLAIMED') from error
    return output


def bind_account_sources(owner, market, original_events, decisions, *, shared,
                         bundle=None, adapter=None, bundle_ref=None):
    """Bind original decision quality before applying source-only CA facts."""
    market = shared.bind_original_wrapper_quality(market, original_events)
    usable, coverage = shared.quote.build_usable_a_mask(
        market.dates, market.tickers, market.quality, decisions,
        raw_open=market.open, raw_close=market.close)
    if bundle is None:
        return market, original_events, usable, coverage, None
    if adapter is None:
        raise ValueError('PAIR_SOURCE_DESCENDANT_ADAPTER_REQUIRED')
    quality_before = np.asarray(market.quality).copy()
    kwargs = dict(account_dates=tuple(market.dates))
    if bundle.get('post_verified_cash_scope') is not None:
        kwargs['bundle_ref'] = bundle_ref
    bound = adapter(owner, copy.deepcopy(original_events), bundle, **kwargs)
    if not np.array_equal(market.quality, quality_before):
        raise ValueError('PAIR_SOURCE_DESCENDANT_CHANGED_DECISION_QUALITY')
    if not isinstance(bound, dict) or set(bound) != {
            'events', 'receipt', 'ordinary_cash_event_fingerprints'}:
        raise ValueError('PAIR_SOURCE_DESCENDANT_RESULT_SCHEMA')
    return market, bound['events'], usable, coverage, bound


def bind_frozen_history_cash_namespace(owner, events, *, reference, shared):
    """Use the original private account with a lossless, pinned cash dependency view."""
    from scripts.research.a2.data.reused_pair_ca_sources import rebind_entitlement_catalogue
    original_ca = owner._frozen_ca_module
    target = module(pin(reference), '_pair_frozen_history_cash_owner_'+reference['sha256'], register=True)
    bound = rebind_entitlement_catalogue(events, source_owner=original_ca, target_owner=target)
    private = SimpleNamespace(**vars(owner))
    names = ('SourceBackedEntitlementEvent', 'SourceBackedTerminalEvent',
        'EntitlementLifecycleState', 'apply_entitlement_lifecycle',
        '_entitlement_effective_day', '_entitlement_pay_date', '_validate_research_account_authority')
    for name in names:
        setattr(private, name, getattr(target, name))
    private._entitlement_binding = shared.clone(owner._entitlement_binding,
        SourceBackedEntitlementEvent=target.SourceBackedEntitlementEvent,
        SourceBackedTerminalEvent=target.SourceBackedTerminalEvent)
    private._frozen_ca_module = target
    return private, bound


COST_SENSITIVITY_PROFILES = {
    'ORIGINAL_PAIR_S5': dict(schema='B_ORIGINAL_PAIR_FIXED_COST_SENSITIVITY_V1',
        name='ORIGINAL_PAIR_S5', primary_cost_bps=10, one_way_bps=5,
        subjects=['SIMPLE_FEASIBLE','JOINT_REUSE'], sessions=752),
    'ORIGINAL_PAIR_S20': dict(schema='B_ORIGINAL_PAIR_FIXED_COST_SENSITIVITY_V1',
        name='ORIGINAL_PAIR_S20', primary_cost_bps=10, one_way_bps=20,
        subjects=['SIMPLE_FEASIBLE','JOINT_REUSE'], sessions=752),
}


def cost_sensitivity_profile(freeze):
    profile=freeze.get('cost_sensitivity_profile')
    if profile is None: return None
    if (freeze.get('mechanism_panel_profile') is not None
            or not isinstance(profile,dict)
            or profile != COST_SENSITIVITY_PROFILES.get(profile.get('name'))):
        raise ValueError('EXACT_ORIGINAL_FIVE_OR_TWENTY_BPS_PAIR_PROFILE_REQUIRED')
    return profile


def policy_execution_bps(freeze):
    profile=cost_sensitivity_profile(freeze)
    return 10 if profile is None else profile['one_way_bps']


def policy_account_label(kind,freeze):
    return kind+'_S'+str(policy_execution_bps(freeze))


def guard_completed_main_pair(freeze, *, parent=None):
    """Validate pinned original-pair metadata only; never evaluate economic values."""
    if parent is None:
        parent=read(pin(freeze['parent_freeze_ref']))
    if (not isinstance(parent,dict) or parent.get('task_id')!=FAST_TRACK_TASK
            or parent.get('status')!='FROZEN'
            or parent.get('cost',{}).get('one_way_bps')!=10
            or parent.get('mechanism_panel_profile') is not None
            or parent.get('cost_sensitivity_profile') is not None):
        raise ValueError('QUALIFIED_ORIGINAL_TEN_BPS_MAIN_PAIR_PARENT_REQUIRED')
    reference=freeze['completed_pair_comparison_ref']
    actual=pin(reference)
    own=Path(parent['run'])
    if 'account_output_namespace' in parent:
        own=own/'account_invocations'/parent['account_output_namespace']
    if actual.resolve()!=(own/'PAIR_COST_AFTER_DESCRIPTIVE_COMPARISON.json').resolve():
        raise ValueError('ACTUAL_MAIN_PAIR_OWN_OUTPUT_REF_REQUIRED')
    primary=read(actual)
    source=freeze['source_account_contract_ref']
    pin(source)
    if (source!=parent.get('source_account_contract_ref')
            or not isinstance(primary,dict)
            or primary.get('source_account_contract_ref')!=source):
        raise ValueError('FOLLOWUP_COMMON_EXACT_MAIN_PAIR_SOURCE_REQUIRED')
    if (primary.get('schema')!='B_FAST_TRACK_MATCHED_PAIR_DESCRIPTIVE_COMPARISON_V1'
            or primary.get('actual_cost_already_in_cash_and_NAV') is not True
            or primary.get('costs_deducted_twice') is not False
            or not isinstance(primary.get('accounts'),dict)
            or set(primary['accounts'])!={'SIMPLE_FEASIBLE','JOINT_REUSE'}):
        raise ValueError('REAL_MATCHED_MAIN_PAIR_REQUIRED')
    calendar_shas=set()
    for kind,value in primary['accounts'].items():
        expected_id=FAST_TRACK_TASK+'::'+kind+'_S10'
        if (not isinstance(value,dict)
                or value.get('status')!='COMPLETE_752_DESCRIPTIVE_RESEARCH'
                or value.get('research_account_gates',{}).get('status')!='PASS'
                or value.get('first_failure') is not None
                or value.get('account_truth_passed') is not True
                or value.get('initial_capital')!=3000.
                or value.get('annual_reset') is not False
                or value.get('path_id')!=expected_id
                or value.get('source_account_contract_ref')!=source):
            raise ValueError('REAL_COMPLETE_QUALIFIED_PRIMARY_BOOK_REQUIRED:'+kind)
        coverage=value.get('coverage')
        if (not isinstance(coverage,dict)
                or any(type(coverage.get(k)) is not int or coverage[k]!=n for k,n in
                    (('expected_sessions',752),('observed_sessions',752),('missing_sessions',0)))
                or coverage.get('first_session')!='2023-01-03'
                or coverage.get('last_session')!='2025-12-31'
                or not isinstance(coverage.get('expected_session_sha256'),str)
                or re.fullmatch(r'[0-9a-f]{64}',coverage['expected_session_sha256']) is None):
            raise ValueError('PRIMARY_BOOK_EXACT_ORIGINAL_752_COVERAGE_REQUIRED:'+kind)
        calendar_shas.add(coverage['expected_session_sha256'])
    comparison=primary.get('comparison',{})
    if (len(calendar_shas)!=1 or not isinstance(comparison,dict)
            or comparison.get('status')!='MATCHED_COMPLETE_DESCRIPTIVE_DIFFERENCES'
            or comparison.get('simple_path_id')!=FAST_TRACK_TASK+'::SIMPLE_FEASIBLE_S10'
            or comparison.get('joint_path_id')!=FAST_TRACK_TASK+'::JOINT_REUSE_S10'):
        raise ValueError('PRIMARY_PAIR_MATCHED_ORIGINAL_CALENDAR_AND_PATHS_REQUIRED')
    return primary


def fast_track_account_order(freeze):
    """Default pair remains exact; a distinct fixed profile admits only four descendants."""
    pto = freeze.get('pto_account_profile')
    if pto is not None:
        if (pto != PTO_ACCOUNT_PROFILE or freeze.get('mechanism_panel_profile') is not None
                or freeze.get('cost_sensitivity_profile') is not None):
            raise ValueError('EXACT_PTO_ACCOUNT_PROFILE_REQUIRED')
        reused = freeze.get('qualified_account_reuse', {})
        if not isinstance(reused, dict) or not set(reused) <= set(pto['policies']):
            raise ValueError('PTO_EXACT_REUSE_POLICY_KEYS_REQUIRED')
        deferred = freeze.get('deferred_account_blocks', {})
        if (not isinstance(deferred, dict) or not set(deferred) <= {PTO_REUSE_KIND}
                or set(deferred) & set(reused)):
            raise ValueError('PTO_EXACT_SOURCE_DEFERRAL_KEYS_REQUIRED')
        order = freeze.get('account_execution_order')
        wanted = [kind for kind in pto['policies'] if kind not in reused and kind not in deferred]
        if not isinstance(order, (list, tuple)) or tuple(order) != tuple(wanted):
            raise ValueError('PTO_ONLY_MISSING_ACCOUNTS_IN_FROZEN_ORDER')
        return tuple(order)
    profile=freeze.get('mechanism_panel_profile')
    if profile is None:
        wanted={'SIMPLE_FEASIBLE','JOINT_REUSE'}
        default=('SIMPLE_FEASIBLE','JOINT_REUSE')
        reason='FAST_TRACK_EXACT_TWO_INDEPENDENT_BOOKS_REQUIRED'
    else:
        if profile != MECHANISM_PANEL_PROFILE:
            raise ValueError('EXACT_FROZEN_MECHANISM_PANEL_PROFILE_REQUIRED')
        wanted=set(MECHANISM_PANEL_POLICIES)
        default=tuple(MECHANISM_PANEL_POLICIES)
        reason='EXACT_FOUR_MECHANISM_PANEL_BOOKS_REQUIRED'
    order=freeze.get('account_execution_order',default)
    if (not isinstance(order,(list,tuple)) or len(order)!=len(wanted) or set(order)!=wanted):
        raise ValueError(reason)
    return tuple(order)


def ordinary_cash_lifecycle(owner, events, approved_fingerprints, *, clone):
    """Original lifecycle with an explicit private ordinary-cash pay threshold.

    Typed issuer pay_date and event fingerprints remain original source terms.
    The claim's pay_date is the declared research not-before date; real account
    sessions select the first open after the issuer pay-date day has ended.
    """
    original = owner.apply_entitlement_lifecycle
    helper = original.__globals__['_entitlement_pay_date']
    approved = tuple(approved_fingerprints)
    if (len(set(approved)) != len(approved)
            or any(not isinstance(x, str) or len(x) != 64
                   or any(c not in '0123456789abcdef' for c in x) for x in approved)):
        raise ValueError('PAIR_ORDINARY_CASH_FINGERPRINTS_INVALID')
    catalogue = tuple(events.get('entitlement_events', ()))
    by_fingerprint = {e.event_fingerprint: e for e in catalogue}
    if len(by_fingerprint) != len(catalogue) or not set(approved).issubset(by_fingerprint):
        raise ValueError('PAIR_ORDINARY_CASH_CATALOGUE_BINDING_REQUIRED')
    thresholds, rows = {}, []
    group_proofs=[p for p in events.get('entitlement_source_binding',{}).get('manifest',{}).get('proofs',[])
                  if p.get('cash_component_group_binding') is not None]
    for fingerprint in sorted(approved):
        event = by_fingerprint[fingerprint]
        if (not isinstance(event, owner.SourceBackedEntitlementEvent)
                or isinstance(event, owner.SourceBackedTerminalEvent)
                or event.ticker == 'MKFG' or event.action_type != 'CASH_DIVIDEND'
                or not pd.Timestamp('2023-01-01') <= pd.Timestamp(event.ex_date) < pd.Timestamp('2026-01-01')):
            raise ValueError('PAIR_ORDINARY_CASH_CLOCK_SCOPE_REQUIRED')
        pay = pd.Timestamp(event.pay_date)
        if pd.isna(pay) or pay.tzinfo is not None or pay != pay.normalize():
            raise ValueError('PAIR_ISSUER_PAY_DATE_REQUIRED')
        threshold = str((pay + pd.Timedelta(days=1)).date())
        thresholds[fingerprint] = threshold
        rows.append(dict(event_id=event.event_id, event_fingerprint=fingerprint,
            ticker=event.ticker, issuer_pay_date=str(pay.date()),
            research_cash_not_before_date=threshold, clock_role=CASH_CLOCK,
            broker_cash_available_at='UNKNOWN'))
        group=[p['cash_component_group_binding'] for p in group_proofs if p['event_fingerprint']==fingerprint]
        if group:
            from scripts.research.a2.data.reused_pair_ca_sources import (
                BASE_VARIABLE_COMPONENT_ROLE, BASE_VARIABLE_COMPONENT_KINDS)
            base_variable = group[0].get('cash_evidence_role') == BASE_VARIABLE_COMPONENT_ROLE
            component_kinds = list(BASE_VARIABLE_COMPONENT_KINDS) if base_variable else [
                'ANNUAL_COMMON_SHARE_CASH_DIVIDEND','QUARTERLY_COMMON_SHARE_CASH_DIVIDEND']
            if (len(group)!=1 or group[0].get('status')!='PINNED_SAME_CLOCK_COMMON_CASH_COMPONENT_GROUP'
                    or group[0].get('cash_per_raw_share')!=event.cash_per_old_share
                    or group[0].get('security_id')!=event.old_security_id or group[0].get('ticker')!=event.ticker
                    or group[0].get('pay_date')!=event.pay_date or group[0].get('record_date')!=event.record_date
                    or group[0].get('ex_date')!=event.ex_date
                    or group[0].get('annual_ordinary_or_quarterly_reclassification') is not False
                    or group[0].get('clock_applicability_role')!='EXPLICIT_SAME_CLOCK_COMMON_CASH_COMPONENT_GROUP_NOT_ORDINARY_RECLASSIFICATION'
                    or group[0].get('consumption_set_role')!='ORDINARY_PAY_END_CLOCK_SET_PLUS_EXPLICIT_SAME_CLOCK_COMPONENT_GROUPS'
                    or [p['component_kind'] for p in group[0]['cash_components']]!=component_kinds):
                raise ValueError('PAIR_COMPONENT_GROUP_EXACT_CLOCK_BINDING_REQUIRED')
            rows[-1].update(cash_component_group_binding=copy.deepcopy(group[0]),
                cash_clock_consumption_set_role=group[0]['consumption_set_role'],
                source_cash_classification=('EXPLICIT_TOTAL_BASE_AND_VARIABLE_COMMON_CASH_COMPONENT_GROUP_NOT_ORDINARY_RECLASSIFICATION'
                    if base_variable else 'ANNUAL_AND_QUARTERLY_COMMON_CASH_COMPONENT_GROUP_NOT_ORDINARY_RECLASSIFICATION'))
    def research_pay_date(event):
        if event.event_fingerprint in thresholds:
            return thresholds[event.event_fingerprint]
        return helper(event)
    lifecycle = clone(original, _entitlement_pay_date=research_pay_date)
    receipt = dict(schema='B_ORDINARY_CASH_RESEARCH_CLOCK_V1', convention=CASH_CLOCK,
        issuer_pay_date_preserved=True, original_lifecycle_code_preserved=True,
        claim_pay_date_role='RESEARCH_CASH_NOT_BEFORE_LOCAL_DATE',
        actual_cash_available_session_role='ACTUAL_CASH_PAID_RECORD_SESSION',
        terminal_and_MKFG_rule='ORIGINAL_UNCHANGED', events=rows, **FLAGS)
    if any('cash_component_group_binding' in row for row in rows):
        receipt['consumption_set_role']='ORDINARY_PAY_END_CLOCK_SET_PLUS_EXPLICIT_SAME_CLOCK_COMPONENT_GROUPS'
    return lifecycle, receipt


def restrict_context(ctx, columns, pool_mask):
    """Only common source-defined eligibility and ordered axis transport change."""
    common = ctx.common if hasattr(ctx, 'common') else ctx
    updates = {}
    n = len(ctx.tickers)
    for field in fields(common):
        value = getattr(common, field.name)
        if isinstance(value, np.ndarray) and value.shape == (1, n):
            updates[field.name] = value[:, columns]
    updates['current_units'] = np.asarray(ctx.current_units)[:, columns]
    updates['tickers'] = np.asarray(ctx.tickers)[columns]
    updates['decision_mask'] = np.asarray(ctx.decision_mask)[:, columns] & pool_mask[columns][None,:]
    updates['buy_allowed'] = np.asarray(ctx.buy_allowed)[:, columns] & pool_mask[columns][None,:]
    return replace(common, **updates)


def restrict_causal_context(ctx, domain):
    """Transport a qualified E-union-H axis without creating held locks."""
    common = ctx.common if hasattr(ctx, 'common') else ctx
    n = len(ctx.tickers)
    columns = np.asarray(domain['columns'])
    if (columns.ndim != 1 or columns.dtype.kind not in 'iu'
            or np.any(columns < 0) or np.any(columns >= n)
            or (len(columns) > 1 and np.any(np.diff(columns) <= 0))):
        raise ValueError('CAUSAL_EXACT_MASTER_ORDERED_COLUMNS_REQUIRED')
    assets = tuple(map(str, np.asarray(ctx.tickers)[columns]))
    if tuple(domain['assets']) != assets:
        raise ValueError('CAUSAL_REQUIRED_ASSET_AXIS_CHANGED')
    masks = {}
    for name in ('pool_mask', 'decision_mask', 'buy_allowed'):
        value = np.asarray(domain[name])
        if value.shape != (n,) or value.dtype != bool:
            raise ValueError('CAUSAL_FULL_MASTER_BOOLEAN_MASK_REQUIRED:' + name)
        masks[name] = value
    exclusions = domain.get('investment_exclusion_tickers', ())
    if domain.get('receipt', {}).get('investment_exclusion_tickers', []) != list(exclusions):
        raise ValueError('CAUSAL_FROZEN_INVESTMENT_EXCLUSION_RECEIPT_CHANGED')
    expected = causal_held_domain(ctx, masks['pool_mask'], excluded_tickers=exclusions)
    if (not np.array_equal(columns, expected['columns'])
            or not np.array_equal(masks['decision_mask'], expected['decision_mask'])
            or not np.array_equal(masks['buy_allowed'], expected['buy_allowed'])):
        raise ValueError('CAUSAL_DOMAIN_DROPPED_REQUIRED_HELD_OR_CHANGED_ACTION_MASK')
    if (np.any(masks['decision_mask'] & ~np.asarray(ctx.decision_mask)[0])
            or np.any(masks['buy_allowed'] & ~np.asarray(ctx.buy_allowed)[0])
            or np.any(masks['buy_allowed'] & ~masks['pool_mask'])):
        raise ValueError('CAUSAL_DOMAIN_CREATED_ORIGINAL_ACTION_PERMISSION')
    updates = {}
    for field in fields(common):
        value = getattr(common, field.name)
        if isinstance(value, np.ndarray) and value.shape == (1, n):
            updates[field.name] = value[:, columns]
    updates['current_units'] = np.asarray(ctx.current_units)[:, columns]
    updates['tickers'] = np.asarray(ctx.tickers)[columns]
    updates['decision_mask'] = masks['decision_mask'][columns][None, :].copy()
    updates['buy_allowed'] = masks['buy_allowed'][columns][None, :].copy()
    return replace(common, **updates)


def causal_policy_decision(kind, ctx, risk, forecasts):
    """Consume common qualified identity/forecast; only Joint consumes covariance."""
    domain = risk.qualified_causal_domain(ctx)
    if not isinstance(domain, dict) or not isinstance(domain.get('receipt'), dict):
        raise ValueError('CAUSAL_QUALIFIED_DOMAIN_RECEIPT_REQUIRED')
    narrow = restrict_causal_context(ctx, domain)
    columns = np.asarray(domain['columns'], dtype=int)
    eligible = narrow.decision_mask[0] & narrow.buy_allowed[0]
    forecast = forecasts.for_decision(ctx.signal_date, narrow.tickers, eligible,
        narrow.current_units[0], decision_as_of=ctx.signal_asof,
        held_weights=narrow.current_weights[0])
    if tuple(forecast.assets) != tuple(domain['assets']):
        raise ValueError('CAUSAL_FORECAST_AXIS_CHANGED')
    if kind in ('SIMPLE_FEASIBLE', RAW_SOURCE_REUSE_KIND):
        covariance, psd = None, False
        risk_receipt = dict(schema='B_SIMPLE_NUMERIC_RISK_DEPENDENCY_R1',
            status='NOT_CONSUMED_BY_FIXED_SIMPLE_POLICY', numeric_state_loaded=False,
            qualified_common_domain_receipt=domain['receipt'], **FLAGS)
    elif kind == 'JOINT_REUSE' or kind in MECHANISM_PANEL_POLICIES or kind == PTO_REUSE_KIND:
        required = risk.for_required_domain(ctx, domain)
        if (tuple(required.assets) != tuple(domain['assets'])
                or not np.array_equal(np.asarray(required.columns), columns)):
            raise ValueError('CAUSAL_JOINT_RISK_REQUIRED_AXIS_CHANGED')
        covariance, psd = required.covariance, required.covariance_psd_qualified
        risk_receipt = required.source_receipt
    else:
        raise ValueError('UNKNOWN_CAUSAL_PAIR_POLICY_KIND')
    if kind == PTO_REUSE_KIND and forecast.source_receipt.get('forecast_recipe') != PTO_FORECAST_RECIPE:
        raise ValueError('PTO_EXPLICIT_TWO_MEMBER_FORECAST_RECIPE_REQUIRED')
    if kind == RAW_SOURCE_REUSE_KIND and forecast.source_receipt.get('forecast_recipe') != 'ORIGINAL_RAW_A2':
        raise ValueError('RAW_ORIGINAL_FORECAST_RECIPE_REQUIRED')
    result = feasible_target(kind, forecast.mean, forecast.uncertainty, covariance,
        narrow, covariance_psd_qualified=psd)
    # Candidate identity admission is committed only after the complete decision
    # succeeds. An actual new position is registered by a later owner fill.
    risk.note_qualified_decision(ctx, domain)
    return dict(columns=columns, forecast=forecast, result=result,
                domain_receipt=domain['receipt'], risk_receipt=risk_receipt)


def guard_causal_input_freeze(freeze):
    """Require real pinned acceptance before loading a new descendant runtime."""
    for name in CAUSAL_INPUT_REFS:
        reference = freeze.get(name)
        if (not isinstance(reference, dict) or set(reference) != {'path', 'sha256'}
                or not reference['path'] or not reference['sha256']):
            raise ValueError('CAUSAL_ACTUAL_INPUT_REFERENCE_REQUIRED:' + name)
        pin(reference)
    if not freeze.get('causal_lw_reuse_rule'):
        raise ValueError('CAUSAL_FROZEN_LW_REUSE_RULE_REQUIRED')
    accepted = read(freeze['runtime_independent_acceptance_ref']['path'])
    if (accepted.get('schema') != 'B_CAUSAL_HELD_RUNTIME_INDEPENDENT_ACCEPTANCE_V1'
            or accepted.get('status') != 'PASS_SOURCE_RUNTIME_READY_FOR_PAIRED_REPLAY'
            or accepted.get('independent') is not True):
        raise ValueError('CAUSAL_INDEPENDENT_RUNTIME_ACCEPTANCE_REQUIRED')
    # Detailed state, UID/lineage, producer-pin and reuse-rule semantics have one
    # authority: CausalHeldLWInputs.from_freeze. They are not duplicated here.


def guard_fast_track_freeze(freeze):
    """Validate the new human-authorized contract without another milestone approval.

    Source/input pins still bind the actual implementation. Historical immutable
    acceptance applies only to inherited artifacts, not this new input rule.
    """
    fast_track_account_order(freeze)
    sensitivity=cost_sensitivity_profile(freeze)
    parent = read(pin(freeze['parent_freeze_ref']))
    if freeze.get('pto_account_profile') is not None:
        guard_pto_account_freeze(freeze, parent)
    for key in ('account_config', 'cost', 'research_window', 'joint_allocator_parameters',
                'common_feasibility', 'opportunity_annual_refs', 'decision_and_outcome',
                'execution', 'accounting_freeze_ref', 'shared_quote_config_ref', 'policies'):
        expected=parent.get(key)
        if freeze.get('pto_account_profile') is not None and key in ('joint_allocator_parameters', 'opportunity_annual_refs', 'policies'):
            continue  # Explicit scientific descendant checked by its own exact profile.
        if sensitivity is not None and key=='cost':
            if expected.get('one_way_bps') != 10:
                raise ValueError('COST_SENSITIVITY_REQUIRES_ORIGINAL_TEN_BPS_PARENT')
            expected=dict(expected,one_way_bps=sensitivity['one_way_bps'])
        if freeze.get('mechanism_panel_profile') is not None and key=='joint_allocator_parameters':
            expected=dict(expected,no_action_hysteresis=False)
        if freeze.get(key) != expected:
            raise ValueError('FAST_TRACK_ORIGINAL_ACCOUNT_POLICY_CHANGED:' + key)
    if freeze.get('mechanism_panel_profile') is not None:
        if freeze.get('scientific_identity') == parent.get('scientific_identity'):
            raise ValueError('PANEL_DISTINCT_SCIENTIFIC_POLICY_IDENTITY_REQUIRED')
        if freeze.get('cost',{}).get('one_way_bps') != 10:
            raise ValueError('PANEL_ORIGINAL_TEN_BPS_PRIMARY_COST_REQUIRED')
        pin(freeze['mechanism_panel_design_ref'])
        # The original complete comparator is mandatory at the actual consumer gate.
    if sensitivity is not None:
        if freeze.get('scientific_identity') == parent.get('scientific_identity'):
            raise ValueError('SENSITIVITY_DISTINCT_COST_IDENTITY_REQUIRED')
        pin(freeze['mechanism_panel_design_ref'])
    if freeze.get('mechanism_panel_profile') is not None or sensitivity is not None:
        guard_completed_main_pair(freeze,parent=parent)
    if any(freeze.get(key) is not False for key in FLAGS):
        raise ValueError('FAST_TRACK_RESEARCH_FLAGS_REQUIRED')
    rule = freeze.get('continuous_lw_rule', {})
    expected = dict(required_domain='E_UNION_OWN_ACTUAL_H',
        estimation_domain='FULL_ORIGINAL_P_UNION_OWN_ACTUAL_H',
        max_new_outputs_per_decision_date=1, max_learned_units_per_output=9,
        max_physical_operations_per_output=14, window_learned_cap=6768,
        window_physical_cap=10528, matrix_mixing=False, future_state_allowed=False,
        unchanged_failed_estimate_retry_allowed=False)
    if any(rule.get(k) != v for k,v in expected.items()):
        raise ValueError('FAST_TRACK_CONTINUOUS_LW_CONTRACT_REQUIRED')
    if freeze.get('historical_CA_source_acquisition_authorized') is not True:
        raise ValueError('FAST_TRACK_HISTORICAL_SOURCE_AUTHORIZATION_REQUIRED')
    for key in ('held_identity_source_binding_ref', 'supplemental_lw_state_ref'):
        pin(freeze[key])



def guard_pto_account_freeze(freeze, parent):
    from dataclasses import asdict
    from scripts.research.a2.inference.reused_policy_inputs import P0_ANNUAL_REFERENCES, RIDGE_ANNUAL_REFERENCES
    design = read(pin(freeze['pto_design_ref']))
    preflight = read(pin(freeze['registry_preflight_ref']))
    if (freeze['scientific_identity'] == parent['scientific_identity']
            or design.get('status') != 'FROZEN_BEFORE_NEW_ACCOUNT_OUTCOME'
            or design.get('scientific_identity') != freeze['scientific_identity']
            or design.get('source_parent_ref') != freeze['parent_freeze_ref']
            or preflight.get('status') != 'PASS'
            or design.get('source_account_contract_ref') != freeze['source_account_contract_ref']
            or freeze.get('source_account_contract_ref') != parent.get('source_account_contract_ref')):
        raise ValueError('PTO_EXPLICIT_DESIGN_SOURCE_IDENTITY_AND_PREFLIGHT_REQUIRED')
    if (freeze.get('cost', {}).get('one_way_bps') != 10
            or freeze.get('policies') != PTO_ACCOUNT_PROFILE['recipes']
            or freeze.get('joint_allocator_parameters') != dict(method='robust_cost_aware',
                risk_penalty=4., uncertainty_penalty=.5, iterations=128, tolerance=2e-6,
                execution_friction_bps=10, full_target=True, fixed_feasible_gross=True)
            or freeze.get('opportunity_annual_refs') != {
                'HGB': {str(y):asdict(r) for y,r in P0_ANNUAL_REFERENCES.items()},
                'RIDGE': {str(y):asdict(r) for y,r in RIDGE_ANNUAL_REFERENCES.items()}}):
        raise ValueError('PTO_FROZEN_RECIPES_PARAMETERS_AND_INPUT_REFS_REQUIRED')
    for ref in freeze.get('qualified_account_reuse', {}).values():
        result = read(pin(ref))
        if (result.get('kind') not in PTO_ACCOUNT_PROFILE['policies']
                or result.get('source_account_contract_ref') != freeze['source_account_contract_ref']
                or result.get('scientific_identity') != freeze['scientific_identity']
                or result.get('account_config') != freeze['account_config'] or result.get('cost') != freeze['cost']
                or result.get('pto_account_profile') != PTO_ACCOUNT_PROFILE
                or result.get('research_account_qualified') is not True
                or result.get('research_account_gates', {}).get('status') != 'PASS'
                or result.get('full_window_completed') is not True):
            raise ValueError('PTO_REUSE_REQUIRES_EXACT_COMPLETE_QUALIFIED_ACCOUNT')
    load_pto_deferred_source_blocks(freeze)



def load_pto_deferred_source_blocks(freeze):
    """Retain an exact unresolved source failure; never treat it as a completed book."""
    deferred = {}
    for kind, refs in freeze.get('deferred_account_blocks', {}).items():
        if (kind != PTO_REUSE_KIND or set(refs) != {'prior_freeze_ref','prior_result_ref','missing_source_ref'}
                or kind in freeze.get('qualified_account_reuse', {})):
            raise ValueError('PTO_EXACT_SOURCE_DEFERRAL_KEYS_REQUIRED')
        prior = read(pin(refs['prior_freeze_ref']))
        result = read(pin(refs['prior_result_ref']))
        missing = read(pin(refs['missing_source_ref']))
        expected = Path(prior['run'])/'account_invocations'/prior['account_output_namespace']/'work'/policy_account_label(kind,prior)/'POLICY_RESULT.json'
        shared_keys = ('run','pto_account_profile','policies','opportunity_annual_refs',
            'joint_allocator_parameters','account_config','cost','research_window','common_feasibility',
            'decision_and_outcome','execution','accounting_freeze_ref','shared_quote_config_ref',
            'continuous_lw_rule','continuous_lw_resource_config','legacy_lw_owner_binding_ref',
            'frozen_history_cash_owner_ref','source_account_contract_ref')
        if (Path(refs['prior_result_ref']['path']).resolve() != expected.resolve()
                or any(prior.get(key) != freeze.get(key) for key in shared_keys)
                or any(prior.get('continuous_lw_source_science', {}).get(key) !=
                       freeze.get('continuous_lw_source_science', {}).get(key)
                       for key in ('scientific_contract_identity','actual_snapshot_timestamp'))
                or result.get('scientific_identity') != prior.get('scientific_identity')
                or result.get('pto_account_profile') != PTO_ACCOUNT_PROFILE
                or result.get('account_config') != prior.get('account_config')
                or result.get('cost') != prior.get('cost')
                or result.get('source_account_contract_ref') != freeze.get('source_account_contract_ref')
                or result.get('kind') != kind or result.get('status') != 'PAIRED_POLICY_BLOCKED_REAL_INPUT'
                or result.get('full_window_completed') is not False
                or result.get('research_account_qualified') is not False):
            raise ValueError('PTO_DEFER_ONLY_EXACT_UNQUALIFIED_SOURCE_FAILURE')
        failure = result.get('first_failure') or {}
        keys = failure.get('candidate_event_keys') or []
        contract = read(pin(freeze['source_account_contract_ref']))
        limits = contract.get('source_completion_limits', {})
        unresolved = limits.get('new_batch_unresolved_original_ex_dates', {})
        admitted = [key for event in contract.get('events', []) for key in event.get('original_unsupported_keys', [])]
        if (failure.get('reason') != 'ACTUAL_ACCOUNT_FACT_UNEXECUTABLE' or not keys
                or any(set(key) != {'effective_date','ticker','reason','source_reference','source_fingerprint'}
                       or key.get('effective_date') != failure.get('failure_session_date')
                       or key.get('reason') != 'VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY'
                       or key.get('effective_date') not in unresolved.get(key.get('ticker'), [])
                       or key in admitted for key in keys)
                or missing.get('status') != 'BLOCKED_MISSING_ISSUER_DECLARED_DIRECT_EX_DATE'
                or missing.get('source_account_contract_ref') != freeze['source_account_contract_ref']
                or missing.get('prior_result_ref') != refs['prior_result_ref']
                or missing.get('candidate_event_keys') != keys):
            raise ValueError('PTO_DEFER_REQUIRES_CURRENT_UNRESOLVED_EXACT_SOURCE_KEY')
        deferred[kind] = dict(prior_freeze_ref=refs['prior_freeze_ref'],prior_result_ref=refs['prior_result_ref'],
            missing_source_ref=refs['missing_source_ref'],status='DEFERRED_UNRESOLVED_SOURCE_NOT_QUALIFIED',
            original_failure_reason=failure['reason'],candidate_event_keys=keys,
            prior_scientific_identity=prior['scientific_identity'],qualified=False,complete=False)
    return deferred


def load_pto_reused_accounts(freeze):
    results = []
    for kind, ref in freeze.get('qualified_account_reuse', {}).items():
        result = read(pin(ref))
        if result.get('kind') != kind:
            raise ValueError('PTO_REUSED_ACCOUNT_KIND_MISMATCH')
        results.append(result)
    return results


def publish_pto_account_comparison(output, freeze, results, expected_sessions):
    if ({r['kind'] for r in results} != set(PTO_ACCOUNT_PROFILE['policies']) or len(results) != 2
            or any(r.get('research_account_qualified') is not True
                   or r.get('full_window_completed') is not True for r in results)):
        return None
    if any(r.get('source_account_contract_ref') != freeze['source_account_contract_ref']
           or r.get('scientific_identity') != freeze['scientific_identity'] for r in results):
        raise ValueError('PTO_MATCHED_SOURCE_AND_SCIENTIFIC_IDENTITY_REQUIRED')
    from scripts.research.a2.evaluation.reused_policy_pair_economics import evaluate_reused_account, compare_reused_pair
    evaluated = {}
    for result in results:
        frames = {name:pd.read_parquet(pin(ref)) for name,ref in result['artifacts'].items() if name in TABLES}
        candidate = dict(candidate_id=result['path_id'], scientific_tuple_sha256=freeze['scientific_identity'],
            execution_friction=dict(one_way_bps=10))
        evaluated[result['kind']] = evaluate_reused_account(candidate, frames,
            expected_sessions=expected_sessions, account_truth_passed=True, complete=True, first_failure=None)
    comparison = compare_reused_pair(evaluated[RAW_SOURCE_REUSE_KIND], evaluated[PTO_REUSE_KIND])
    comparison['difference_coordinate'] = 'PTO_MINUS_MATCHED_SOURCE_ORIGINAL_RAW_RULE'
    return write(Path(output)/'PTO_MATCHED_COST_AFTER_COMPARISON.json',dict(
        schema='B_PTO_MATCHED_SOURCE_COST_AFTER_COMPARISON_V1', accounts=evaluated, comparison=comparison,
        source_account_contract_ref=freeze['source_account_contract_ref'], pto_design_ref=freeze['pto_design_ref'],
        actual_cost_already_in_cash_and_NAV=True, costs_deducted_twice=False,
        exposed_development_only=True, scientific_winner=None, **FLAGS))

def update_account_progress(root, **value):
    """A bounded live observation; never a resumable account checkpoint."""
    path = Path(root) / 'PAIR_PROGRESS.json'
    assert_safe_output_path(path, kind='backtest', paths=PATHS)
    payload = dict(value, observed_at=datetime.now(timezone.utc).isoformat(),
                   resume_authority=False)
    raw = json.dumps(json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(raw, encoding='utf-8')
    for attempt in range(5):
        try:
            temporary.replace(path)
            break
        except PermissionError as exc:
            if getattr(exc, 'winerror', None) not in (5, 32) or attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def make_causal_input_adapter(freeze, base_shared, account_id, market, *, source_context=None, factory=None):
    extra = {}
    if factory is None:
        if freeze.get('task_id') == FAST_TRACK_TASK:
            from scripts.research.a2.inference.reused_r5_risk_inputs import ContinuousCausalLWInputs
            factory = ContinuousCausalLWInputs.from_freeze
            if (freeze.get('pto_account_profile') == PTO_ACCOUNT_PROFILE
                    and account_id == FAST_TRACK_TASK+'::'+policy_account_label(RAW_SOURCE_REUSE_KIND, freeze)):
                # Raw retains this exact source/holding book without estimator authority.
                # The original owner still supplies the shared durable budget metadata.
                from scripts.research.a2.risk.continuous_lw_support import ContinuousLWEstimator
                metadata_owner = SimpleNamespace(run=Path(freeze['run']), ledger=None)
                def source_only_estimate(request):
                    raise ExistingRiskInputUnavailable('RAW_SOURCE_ONLY_NUMERIC_RISK_DISABLED')
                source_only_estimate.budget_summary = lambda: ContinuousLWEstimator.budget_summary(metadata_owner)
                extra['estimate_callback'] = source_only_estimate
        else:
            from scripts.research.a2.inference.reused_r5_risk_inputs import CausalHeldLWInputs
            factory = CausalHeldLWInputs.from_freeze
    return factory(freeze=freeze, base_shared=base_shared, account_id=account_id,
        market_dates=market.dates, master_assets=market.tickers, source_context=source_context, **extra)


def causal_owner_source_context(freeze, market, events, input_refs, owner_ref,
                                source_descendant_binding_ref=None, *, typed_ca_owner=None):
    """Transport the already-bound owner catalogue and raw row-presence axis.

    Prices, accounting outputs and strategy arrays are deliberately absent. The
    accepted identity/source owner qualifies these facts; this runner creates no
    second identity master or CA catalogue and executes no quantity conversion.
    """
    if typed_ca_owner is None:
        raise ValueError('ACTUAL_PRIVATE_TYPED_CA_OWNER_REQUIRED')
    typed_path = Path(typed_ca_owner.__file__)
    if typed_path.drive.upper() != 'D:':
        raise ValueError('LITERAL_D_TYPED_CA_OWNER_REQUIRED_BEFORE_IO')
    typed_ref = dict(path=str(typed_path), sha256=sha(typed_path))
    legacy = input_refs.get('code:scripts/v22/corporate_action_transition_r1.py')
    classes = dict(cash=typed_ca_owner.SourceBackedEntitlementEvent,
                   terminal=typed_ca_owner.SourceBackedTerminalEvent)
    current = freeze.get('frozen_history_cash_owner_ref')
    inherited = freeze.get('inherited_typed_ca_owner_ref')
    actual_matches = (legacy.get('sha256') == typed_ref['sha256'] if isinstance(legacy, dict) else False)
    if current is not None:
        pin(current)
        actual_matches = (current == typed_ref and isinstance(inherited, dict)
            and isinstance(legacy, dict) and legacy.get('sha256') == inherited['sha256'])
    if not actual_matches or any(not isinstance(value, type) for value in classes.values()):
        raise ValueError('EXACT_INHERITED_TYPED_CA_SOURCE_AND_ACTUAL_CLASSES_REQUIRED')
    present = np.asarray(market.row_present)
    if present.dtype != np.bool_ or present.shape != (len(market.dates), len(market.tickers)):
        raise ValueError('CAUSAL_RAW_SOURCE_PRESENCE_AXIS_REQUIRED')
    return dict(owner_ref=copy.deepcopy(owner_ref), input_refs=copy.deepcopy(input_refs),
        events=copy.deepcopy(events), typed_ca_owner_ref=typed_ref,
        typed_entitlement_classes=classes, market_dates=tuple(market.dates),
        master_assets=tuple(map(str, market.tickers)), raw_row_present=present.copy(),
        source_account_contract_ref=copy.deepcopy(freeze.get('source_account_contract_ref')),
        source_descendant_binding_ref=copy.deepcopy(source_descendant_binding_ref))


def causal_unit_transition_observer(original, events, owner_ref, observer):
    """Observe the original owner's successful unit-factor call, not actual shares.

    The original function executes once and its result is returned unchanged.
    A unit-one setup commitment must later be reconciled against direct actual
    raw quantities by the held source adapter; it is never an admission or a
    fabricated PRE_OPEN actual position effect.
    """
    known_at = events.get('corporate_action_known_at') or {}
    def observed(transition, positions, cash, execution_date):
        result = original(transition, positions, cash, execution_date)
        record = result[2]
        if record is not None:
            payload = dict(role='UNIT_COORDINATE_APPLIED',
                event_fingerprint=record['event_fingerprint'],
                effective_session=pd.Timestamp(record['effective_date']),
                typed_kind=record['action_type'], old_ticker=record['old_ticker'],
                new_ticker=record['new_ticker'], old_security_id=record['old_security_id'],
                new_security_id=record['new_security_id'],
                source_reference=record['source_reference'],
                source_fingerprint=record['source_fingerprint'],
                known_at=known_at.get(record['event_fingerprint']),
                owner_ref=owner_ref, unit_before_quantity=record['old_quantity'],
                unit_after_quantity=record['new_quantity'],
                quantity_multiplier=record['quantity_multiplier'],
                quantity_coordinate='ORIGINAL_OWNER_UNIT_FACTOR_COMMITMENT',
                timing_rule=record['timing_rule'])
            observer(copy.deepcopy(payload))
        return result
    return observed


def project_causal_preopen_quantities(interface, owner, convention_ref, commitments, boundary, *, clone):
    """Add a direct quantity observation to the existing owner AST projection.

    The owner's actual pre-open units and prior factors remain the sole inputs.
    The private keyword is removed before the original cash lifecycle call.
    No cash/identity catalogue, share arithmetic or execution clock is changed.
    """
    import ast
    project = interface.project_current_owner
    original = project.__globals__.get('_project')
    if not callable(original):
        raise ValueError('PAIR_ORIGINAL_OWNER_PROJECTION_ENTRY_REQUIRED')
    proofs = []
    def observed_compile(tree, filename, mode, *args, **kwargs):
        if not isinstance(tree, ast.Module) or len(tree.body) != 1:
            raise ValueError('PAIR_PREOPEN_OWNER_COMPILE_SHAPE')
        projected = copy.deepcopy(tree)
        calls = [n for n in ast.walk(projected) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == 'apply_entitlement_lifecycle']
        if len(calls) != 1:
            raise ValueError('PAIR_PREOPEN_OWNER_LIFECYCLE_ANCHOR_REQUIRED')
        call = calls[0]
        if (len(call.args) != 3 or ast.unparse(call.args[1]) != 'positions'
                or {k.arg:ast.unparse(k.value) for k in call.keywords}.get('execution_date') != 'date'
                or any(k.arg == '_pair_original_preopen_raw_positions' for k in call.keywords)):
            raise ValueError('PAIR_PREOPEN_OWNER_DIRECT_QUANTITY_ANCHOR_REQUIRED')
        values = ast.parse('{str(ticker): float(units[r, ti[ticker]] * before_factors[ti[ticker]]) for ticker in market.tickers}', mode='eval').body
        call.keywords.append(ast.keyword(arg='_pair_original_preopen_raw_positions', value=values))
        proof = dict(original_projected_ast_sha256=hashlib.sha256(ast.dump(tree,include_attributes=False).encode()).hexdigest(),
            observed_projected_ast_sha256=hashlib.sha256(ast.dump(projected,include_attributes=False).encode()).hexdigest(),
            quantity_role='DIRECT_ORIGINAL_OWNER_PREOPEN_UNITS_TIMES_PRIOR_FACTOR',
            accounting_arithmetic_changed=False, cash_catalogue_changed=False, share_conversion_added=False)
        call.keywords.pop()
        if ast.dump(projected,include_attributes=False) != ast.dump(tree,include_attributes=False):
            raise ValueError('PAIR_PREOPEN_OBSERVATION_REVERSE_AST_CHANGED')
        call.keywords.append(ast.keyword(arg='_pair_original_preopen_raw_positions', value=values))
        proofs.append(proof)
        return compile(ast.fix_missing_locations(projected), filename, mode, *args, **kwargs)
    inner = clone(original, compile=observed_compile)
    fn, lineage = clone(project, _project=inner)(owner, convention_ref, commitments, boundary)
    if len(proofs) != 1:
        raise ValueError('PAIR_PREOPEN_OWNER_OBSERVATION_COMPILE_COUNT')
    lineage = dict(lineage, inherited_projected_function_ast_sha256=lineage.get('projected_function_ast_sha256'),
        projected_function_ast_sha256=proofs[0]['observed_projected_ast_sha256'],
        direct_preopen_quantity_observation=dict(proofs[0],reverse_quantity_observation_ast_exact=True))
    return fn, lineage


def causal_lifecycle_quantity_payload(args, kwargs, result, account_id, owner_ref,
                                     original_preopen_raw_positions=None):
    """Project direct original lifecycle positions without cash/economic fields.

    Before/after here are the lifecycle owner's raw-share inputs and outputs.
    An ordinary SPLIT factor is outside that lifecycle output: its actual post
    quantity is supplied by the first actual raw fill-before, or direct close
    context only when that asset has no fills, in the accepted source adapter.
    """
    terminal_fields = ('event_id', 'event_fingerprint', 'old_security_id', 'ticker',
                       'phase', 'session', 'entitled_raw_shares', 'source_fingerprint')
    terminal = [{k: row[k] for k in terminal_fields if k in row}
                for row in result.records if row.get('phase') == 'SECURITY_EXTINGUISHED']
    payload = dict(role='PRE_OPEN_LIFECYCLE_APPLIED', account_id=account_id,
        session=pd.Timestamp(kwargs['execution_date']), session_open_at=kwargs['session_open_at'],
        quantity_coordinate='RAW_ACTUAL_SHARE',
        security_tickers=kwargs['security_tickers'], positions_before=args[1],
        positions_after=result.positions, terminal_effect_records=terminal, owner_ref=owner_ref)
    if original_preopen_raw_positions is not None:
        payload['original_preopen_raw_positions_by_ticker'] = original_preopen_raw_positions
        payload['original_preopen_quantity_role'] = 'DIRECT_ORIGINAL_OWNER_PREOPEN_UNITS_TIMES_PRIOR_FACTOR'
    return copy.deepcopy(payload)


def causal_adapter_load_totals(base_shared, adapters):
    """Count shared original deserializations once and per-account supplement loads."""
    existing = int(base_shared.loads_count)
    supplemental = sum(int(adapter.supplemental_loads_count) for adapter in adapters)
    return dict(physical_existing_state_loads=existing,
        physical_supplemental_state_loads=supplemental,
        physical_risk_state_loads_total=existing + supplemental)


class PairInputBlocked(RuntimeError):
    def __init__(self, receipt):
        self.receipt = json_safe(receipt)
        super().__init__(self.receipt.get('reason', 'PAIR_INPUT_BLOCKED'))



def _failure_receipt(task_id, path_id, reason, day, state, ticker=None, *,
                     execution_session=False, **details):
    session = str(pd.Timestamp(day).date()) if day is not None else None
    receipt = dict(path_id=path_id, signal_date=session, ticker=ticker, reason=reason, **details)
    if task_id in (CA_TASK, CAUSAL_HELD_TASK, FAST_TRACK_TASK):
        causal_signal = (state or {}).get('signal_date')
        receipt['signal_date'] = (str(pd.Timestamp(causal_signal).date())
                                  if causal_signal is not None else None)
        receipt['failure_session_date'] = session
        if execution_session:
            receipt['execution_date'] = session
    return receipt


def execute(run, freeze, kind, owner, market, events, usable, shared, parent, risk, forecasts,
            cash_clock=None, source_binding_ref=None, source_context=None, original_qualifier=None):
    label = policy_account_label(kind,freeze)
    task_id = freeze.get('task_id', TASK)
    if task_id == FAST_TRACK_TASK and original_qualifier is None:
        raise ValueError('FAST_TRACK_ORIGINAL_TEN_ACCOUNT_GATES_REQUIRED')
    pid = task_id + '::' + label
    root = run / 'work' / label
    root.mkdir(parents=True, exist_ok=True)
    claim = root / 'ATTEMPT_CLAIM.json'
    with claim.open('x', encoding='utf-8') as handle:
        claim_identity = dict(path_id=pid, pid=os.getpid(),
            new_policy_identity=task_id == TASK, scientific_retry=False)
        if 'account_output_namespace' in freeze:
            claim_identity.update(account_output_namespace=freeze['account_output_namespace'],
                original_managed_run=freeze['run'], engineering_continuation=True)
        if task_id in (CA_TASK, CAUSAL_HELD_TASK, FAST_TRACK_TASK):
            claim_identity['new_source_account_identity'] = True
        if task_id in (CAUSAL_HELD_TASK, FAST_TRACK_TASK):
            claim_identity['new_causal_held_input_identity'] = True
        json.dump(claim_identity, handle)
    chunks, uses, diagnostics, entitlements = {}, [], [], []
    state, current_day, last_held = None, None, {}
    started = time.perf_counter()
    observed_daily_rows = 0
    last_domain_snapshot, last_risk_selection = None, None
    execution_session_active = False
    def fail(reason, day, ticker=None, *, execution_session=False, **details):
        raise PairInputBlocked(_failure_receipt(task_id, pid, reason, day, state, ticker,
            execution_session=execution_session, **details))
    def checked(day, ctx):
        nonlocal current_day, state, execution_session_active, last_domain_snapshot, last_risk_selection
        current_day = pd.Timestamp(ctx.signal_date)
        execution_session_active = False
        state = dict(signal_date=str(current_day), state_asof=str(ctx.signal_asof),
                     units=ctx.current_units, cash=ctx.cash, nav=ctx.nav,
                     weights=ctx.current_weights, tickers=list(map(str, ctx.tickers)),
                     holding_age=ctx.holding_age, entry_date=np.asarray(ctx.entry_date).astype(str),
                     receivable_value_usd=getattr(ctx, 'receivable_value_usd', None),
                     reserved_mask=ctx.reserved_mask, sell_restricted=ctx.sell_restricted)
        try:
            if task_id == FAST_TRACK_TASK:
                last_domain_snapshot = risk.describe_required_domains(ctx)
                last_risk_selection = None
            if task_id in (CAUSAL_HELD_TASK, FAST_TRACK_TASK):
                prepared = causal_policy_decision(kind, ctx, risk, forecasts)
                columns, forecast, result = (prepared['columns'], prepared['forecast'], prepared['result'])
            else:
                rs = risk.for_decision(ctx)
                columns = np.asarray(rs.columns, dtype=int)
                narrow = restrict_context(ctx, columns, np.asarray(rs.pool_mask, bool))
                eligible = narrow.decision_mask[0] & narrow.buy_allowed[0]
                forecast = forecasts.for_decision(ctx.signal_date, narrow.tickers, eligible,
                    narrow.current_units[0], decision_as_of=ctx.signal_asof, held_weights=narrow.current_weights[0])
                result = feasible_target(kind, forecast.mean, forecast.uncertainty, rs.covariance,
                    narrow, covariance_psd_qualified=rs.covariance_psd_qualified)
        except FeasiblePolicyBlocked:
            raise  # Policy implementation/feasibility failures need diagnosis, not source excuses.
        except PairInputBlocked:
            raise
        except (OpportunityInputUnavailable, ExistingRiskInputUnavailable, HeldLineageUnavailable) as error:
            receipt = getattr(error, 'receipt', {})
            reason = ('REQUIRED_HELD_IDENTITY_UNAVAILABLE' if isinstance(error, HeldLineageUnavailable)
                      else 'REQUIRED_FROZEN_INPUT_UNAVAILABLE')
            fail(reason, current_day,
                 source_failure_type=type(error).__name__, source_reason=str(error), source_receipt=receipt)
        if task_id == FAST_TRACK_TASK:
            last_risk_selection = prepared['risk_receipt']
        weights = np.zeros_like(ctx.current_weights)
        explicit = np.zeros_like(ctx.decision_mask)
        weights[:,columns], explicit[:,columns] = result.target.weights, result.target.explicit_mask
        source_use = dict(date=str(current_day.date()), opportunity=forecast.source_receipt,
            risk=prepared['risk_receipt'] if task_id in (CAUSAL_HELD_TASK, FAST_TRACK_TASK) else rs.source_receipt)
        if task_id in (CAUSAL_HELD_TASK, FAST_TRACK_TASK):
            source_use['causal_held_domain'] = prepared['domain_receipt']
        uses.append(source_use)
        diagnostics.append(dict(date=str(current_day.date()), **result.receipt))
        if len(uses) == 1 or len(uses) % 50 == 0:
            print(json.dumps(dict(event='PAIR_POLICY_PROGRESS',kind=kind,sessions=len(uses),date=str(current_day.date()))), flush=True)
        return TargetDecision(weights, explicit, 'REUSED_ASSET_PAIR_V1')
    def ledger(name, frame):
        nonlocal current_day, last_held, execution_session_active, observed_daily_rows
        chunks.setdefault(name, []).append(frame.copy())
        if frame.empty: return
        if name == 'fills' and task_id in (CAUSAL_HELD_TASK, FAST_TRACK_TASK):
            current_day = pd.Timestamp(frame.execution_date.iloc[0])
            execution_session_active = True
            try:
                risk.observe_fills(frame)
            except (ExistingRiskInputUnavailable, HeldLineageUnavailable) as error:
                reason = ('REQUIRED_HELD_IDENTITY_UNAVAILABLE' if isinstance(error, HeldLineageUnavailable)
                          else 'REQUIRED_FROZEN_INPUT_UNAVAILABLE')
                fail(reason, current_day,
                    execution_session=True, source_failure_type=type(error).__name__,
                    source_reason=str(error), source_receipt=getattr(error, 'receipt', {}))
        if name == 'daily':
            current_day = pd.Timestamp(frame.date.iloc[0])
            execution_session_active = True
            if not frame.accounting_qualified.all():
                candidates = [dict(e) for e in events.get('unsupported_events', ())
                    if pd.Timestamp(e['effective_date']) == current_day and last_held.get(str(e['ticker']),0)>1e-10]
                fail('ACTUAL_ACCOUNT_FACT_UNEXECUTABLE', current_day, execution_session=True,
                     candidate_event_keys=candidates, actual_prior_holdings=last_held,
                     observed_entitlements=entitlements, accounting_rows=frame.to_dict('records'))
            if not np.isfinite(frame.cash).all() or not np.isfinite(frame.nav).all() or frame.cash.lt(-1e-8).any():
                fail('ACTUAL_CASH_OR_NAV_INVALID', current_day, execution_session=True)
            if frame.actual_name_count.eq(0).all(): last_held = {}
            observed_daily_rows += len(frame)
            if task_id == FAST_TRACK_TASK:
                update_account_progress(root, status='ACCOUNT_RUNNING', kind=kind, path_id=pid,
                    observed_daily_rows=observed_daily_rows, policy_calls=len(uses),
                    last_daily_date=str(current_day.date()), elapsed_seconds=time.perf_counter()-started)
        if name == 'positions':
            last_held = {str(r.ticker): float(r.fractional_shares) for r in frame.itertuples()}
            for row in frame.itertuples():
                d, c = market.dates.get_loc(pd.Timestamp(row.date)), pd.Index(market.tickers).get_loc(row.ticker)
                if not (market.row_present[d,c] and np.isfinite([market.open[d,c],market.close[d,c]]).all()
                        and min(market.open[d,c],market.close[d,c]) > 0):
                    fail('HELD_RAW_ENDPOINT_UNAVAILABLE', row.date, str(row.ticker), execution_session=True)
                if market.quality[d,c] and not usable[d,c]:
                    fail('HELD_QUOTE_NOT_A_UNDER_SHARED_FROZEN_DOMAIN',row.date,str(row.ticker), execution_session=True)
        if name == 'execution_results':
            for row in frame.itertuples():
                if row.status != 'REJECTED': continue
                material = row.reason in {'MISSING_PRICE_ROW','MISSING_OR_INVALID_OPEN','MISSING_SIGNAL_ADV','UNKNOWN_NAV'}
                if row.reason == 'PRICE_QUALITY_UNCERTIFIED':
                    d,c = market.dates.get_loc(pd.Timestamp(row.execution_date)),pd.Index(market.tickers).get_loc(row.ticker)
                    material = not (usable[d,c] and market.row_present[d,c] and np.isfinite(market.open[d,c]) and market.open[d,c]>0)
                if material: fail('ACTUAL_EXECUTION_FACT_UNAVAILABLE',row.execution_date,str(row.ticker), execution_session=True,
                                  original_rejection_reason=str(row.reason),order_id=str(row.order_id))
    original_lifecycle = owner.apply_entitlement_lifecycle
    def observe_quantity(payload):
        try:
            risk.observe_owner_transitions(copy.deepcopy(payload))
        except (ExistingRiskInputUnavailable, HeldLineageUnavailable) as error:
            reason = ('REQUIRED_HELD_IDENTITY_UNAVAILABLE' if isinstance(error, HeldLineageUnavailable)
                      else 'REQUIRED_FROZEN_INPUT_UNAVAILABLE')
            day = payload.get('session', payload.get('effective_session'))
            fail(reason, day, execution_session=payload['role'] == 'PRE_OPEN_LIFECYCLE_APPLIED',
                 source_failure_type=type(error).__name__, source_reason=str(error),
                 source_receipt=getattr(error, 'receipt', {}),
                 source_observation_role=payload['role'])
    clock_events = {row['event_fingerprint']: row for row in (cash_clock or {}).get('events', ())}
    def observed(*args, **kwargs):
        nonlocal current_day, execution_session_active
        if task_id in (CA_TASK, CAUSAL_HELD_TASK, FAST_TRACK_TASK):
            current_day = pd.Timestamp(kwargs['execution_date'])
            execution_session_active = True
        quantity_args = (args[0], copy.deepcopy(args[1])) if task_id in (CAUSAL_HELD_TASK, FAST_TRACK_TASK) else None
        original_preopen = kwargs.pop('_pair_original_preopen_raw_positions', None)
        if original_preopen is not None and task_id not in (CAUSAL_HELD_TASK, FAST_TRACK_TASK):
            raise ValueError('PAIR_PREOPEN_QUANTITY_OBSERVATION_SCOPE_REQUIRED')
        authority = events.get('research_account_authority')
        if task_id == FAST_TRACK_TASK and freeze.get('frozen_history_cash_owner_ref') is not None:
            # The inherited projected B owner omits this keyword. Transport only
            # the source binder's exact standalone cash admission to its lifecycle.
            if 'research_account_authority' in kwargs and kwargs['research_account_authority'] != authority:
                raise ValueError('PAIR_FROZEN_HISTORY_CASH_AUTHORITY_CHANGED')
            kwargs['research_account_authority'] = authority
        try: result = original_lifecycle(*args, **kwargs)
        except ValueError as error:
            if str(error) not in {'MISSING_EX_PRETRADE_POSITION_SNAPSHOT','TERMINAL_SOURCE_NOT_AVAILABLE_BY_EFFECTIVE_OPEN',
                                  'MISSING_EX_RECEIVABLE_STATE','TERMINAL_OLD_SECURITY_REAPPEARED'}: raise
            event = None
            tb = error.__traceback__
            while tb:
                if tb.tb_frame.f_code is original_lifecycle.__code__: event=tb.tb_frame.f_locals.get('event')
                tb=tb.tb_next
            fail('ACTUAL_ORIGINAL_LIFECYCLE_FACT_UNAVAILABLE',kwargs['execution_date'],
                 getattr(event,'ticker',None),execution_session=True,original_exception=str(error),
                 event_id=getattr(event,'event_id',None),event_fingerprint=getattr(event,'event_fingerprint',None),
                 culprit_uniquely_identified=event is not None)
        if task_id in (CAUSAL_HELD_TASK, FAST_TRACK_TASK):
            observe_quantity(causal_lifecycle_quantity_payload(quantity_args, kwargs, result,
                pid, source_context['owner_ref'], original_preopen_raw_positions=original_preopen))
        for record in result.records:
            clock = dict(clock_events.get(record['event_fingerprint'], {}))
            if clock:
                clock['research_cash_available_session'] = (record['session']
                    if record['phase'] == 'CASH_PAID' else None)
            entitlements.append(dict(record, **clock, accounting_qualified=bool(result.accounting_qualified),
                                     original_state_blocked_events=list(result.state.blocked_events)))
        return result
    quantity_dependencies = {}
    if task_id in (CAUSAL_HELD_TASK, FAST_TRACK_TASK):
        if not isinstance(source_context, dict) or 'owner_ref' not in source_context:
            raise ValueError('CAUSAL_ACTUAL_OWNER_SOURCE_CONTEXT_REQUIRED')
        quantity_dependencies['apply_transition_to_positions'] = causal_unit_transition_observer(
            owner.apply_transition_to_positions, events, source_context['owner_ref'], observe_quantity)
    account = shared.clone(owner.run_continuous_account,
        apply_entitlement_lifecycle=observed, **quantity_dependencies)
    friction = dict(kind='FIXED_ADVERSE_OPEN_SLIPPAGE',one_way_bps=policy_execution_bps(freeze),fee_bps=0,
                    benchmark='NEXT_RAW_OPEN',authority='HYPOTHETICAL_RESEARCH_SCENARIO',scenario_id=pid)
    print(json.dumps(dict(event='PAIR_ACCOUNT_STARTED',kind=kind,path_id=pid)),flush=True)
    if task_id == FAST_TRACK_TASK:
        update_account_progress(root, status='ACCOUNT_STARTED', kind=kind, path_id=pid,
            observed_daily_rows=0, policy_calls=0, elapsed_seconds=0)
    status, failure, qualification, audit = None, None, None, None
    artifacts, partial_clock_roles = {}, {}
    metadata = None
    try:
        replay = account(market,(pid,),checked,dict(parent.ACCOUNT),ledger_callback=ledger,execution_friction=friction,**events)
        view=SimpleNamespace(path_ids=(pid,),research_id=task_id,parent_research_id=freeze['parent_task_id'],
            run_id=Path(freeze.get('run', run)).name,research_kind='REUSED_TRAINED_ASSET_FEASIBLE_PAIR',
            identity_assumption=freeze['identity_rule'],synthetic=False,digest=lambda:freeze['scientific_identity'])
        qualification = shared.clone(parent._qualify,_audit_pass=shared.audit_pass)(replay,market,usable,view,{pid:[]})
        if len(replay.daily)!=752 or not qualification[pid]['mechanism_accounting_consistent']:
            raise AssertionError('PAIR_FULL_WINDOW_ACCOUNT_TRUTH_FAILED')
        replay.daily['TOTAL_ECONOMIC_NAV']=replay.daily.mechanism_account_value
        rights=replay.daily.get('receivable_value_usd',0.)
        replay.daily['LIQUID_NAV']=replay.daily.TOTAL_ECONOMIC_NAV-rights
        replay.daily['research_gross']=(replay.daily.TOTAL_ECONOMIC_NAV-replay.daily.cash-rights)/replay.daily.TOTAL_ECONOMIC_NAV
        replay.daily['research_cash_weight']=replay.daily.cash/replay.daily.TOTAL_ECONOMIC_NAV
        positions=replay.positions
        if len(positions):
            d=pd.Index(market.dates).get_indexer(pd.to_datetime(positions.date))
            c=pd.Index(market.tickers).get_indexer(positions.ticker)
            if np.any(d<0) or np.any(c<0): raise AssertionError('OUTCOME_POSITION_COORDINATE_CHANGED')
            positions['research_raw_market_value']=shared.quote.outcome_raw_close_values(
                positions.fractional_shares.to_numpy(float)[None,:],market.close[d,c],
                ~market.quality[d,c],usable[d,c],market.row_present[d,c])[0]
        else:
            positions['research_raw_market_value']=pd.Series(dtype=float)
        artifacts={name:parent.save_frame(run,label,name,getattr(replay,name)) for name in TABLES if hasattr(replay,name)}
        status,audit='PAIRED_POLICY_ACCOUNT_COMPLETE',replay.audit
        metadata=copy.deepcopy(getattr(replay, 'metadata', None))
    except PairInputBlocked as error:
        status,failure='PAIRED_POLICY_BLOCKED_REAL_INPUT',error.receipt
    except Exception as error:
        status='ENGINEERING_FAILURE_REQUIRES_DIAGNOSIS'
        if task_id in (CA_TASK, CAUSAL_HELD_TASK, FAST_TRACK_TASK):
            failure=_failure_receipt(task_id, pid, str(error), current_day, state,
                execution_session=execution_session_active, type=type(error).__name__,
                traceback=traceback.format_exc())
        else:
            failure=dict(type=type(error).__name__,reason=str(error),traceback=traceback.format_exc(),
                         signal_date=str(current_day.date()) if current_day is not None else None)
    if status != 'PAIRED_POLICY_ACCOUNT_COMPLETE':
        failure_clock = 'failure_session_date' if task_id in (CA_TASK, CAUSAL_HELD_TASK, FAST_TRACK_TASK) else 'signal_date'
        failure_day=pd.Timestamp(failure.get(failure_clock)) if failure.get(failure_clock) else current_day
        for name,parts in chunks.items():
            frame=pd.concat(parts,ignore_index=True)
            if frame.empty: continue
            if task_id in (CA_TASK, CAUSAL_HELD_TASK, FAST_TRACK_TASK):
                clock = ('date' if 'date' in frame else
                         'execution_date' if 'execution_date' in frame else 'signal_date')
                partial_clock_roles[name] = dict(column=clock, role=(
                    'ACCOUNT_SESSION' if clock == 'date' else
                    'EXECUTION_SESSION' if clock == 'execution_date' else
                    'COMPLETED_DECISION_RECORD_NOT_COMPLETED_EXECUTION'))
            else:
                clock='date' if 'date' in frame else ('execution_date' if name in ('fills','execution_results') else 'signal_date')
            if clock not in frame:
                artifacts[name+'_unclassified_partial']=parent.save_frame(run,label,name+'_unclassified_partial',frame)
                continue
            before=pd.to_datetime(frame[clock]).lt(failure_day) if failure_day is not None else np.zeros(len(frame),bool)
            for suffix,mask in (('_prefix',before),('_failure_session_partial',~before)):
                if np.asarray(mask).any(): artifacts[name+suffix]=parent.save_frame(run,label,name+suffix,frame.loc[mask].copy())
        causal = dict(last_policy_context=state, failure_session=failure_day,
            P_E_H_D_U_at_failure=last_domain_snapshot, selected_risk_state_at_failure=last_risk_selection,
            latest_adapter_request=getattr(risk, 'last_request', None),
            latest_estimator_request=getattr(getattr(risk, 'estimate_callback', None), 'last_request', None),
            clock_and_checks=dict(policy_signal_date=(state or {}).get('signal_date'),
                observation_session_date=current_day, execution_session_active=execution_session_active,
                observed_daily_rows=observed_daily_rows, complete_account=False),
            no_partial_session_claimed_complete=True, artifacts=artifacts)
        if task_id in (CA_TASK, CAUSAL_HELD_TASK, FAST_TRACK_TASK):
            causal['partial_table_clock_roles'] = partial_clock_roles
        write(root/'CAUSAL_ACCOUNT_AT_FIRST_FAILURE.json', causal)
    result=dict(status=status,path_id=pid,kind=kind,first_failure=failure,
        full_window_completed=status=='PAIRED_POLICY_ACCOUNT_COMPLETE',policy_calls=len(uses),
        artifacts=artifacts,qualification=qualification,audit=audit,metadata=metadata,new_fits=0,new_predictions=0,
        opportunity_rows_reused=sum(len(x['opportunity']['required_assets']) for x in uses),**FLAGS)
    if task_id == FAST_TRACK_TASK:
        result['new_fits_scope'] = 'PREDICTIVE_MODEL_ONLY'
        result['new_predictive_fits'] = 0
        result['new_risk_estimates_this_account'] = getattr(risk, 'new_outputs_count', 0)
        if original_qualifier is None:
            raise ValueError('FAST_TRACK_ORIGINAL_TEN_ACCOUNT_GATES_REQUIRED')
        result['research_account_gates'] = original_qualifier(result, expected_days=752)
        result['research_account_qualified'] = result['research_account_gates'].get('status') == 'PASS'
        if result['full_window_completed'] and not result['research_account_qualified']:
            status = result['status'] = 'PAIRED_POLICY_ACCOUNT_UNQUALIFIED'
    if task_id in (CA_TASK, CAUSAL_HELD_TASK, FAST_TRACK_TASK):
        result['partial_table_clock_roles'] = partial_clock_roles
    if source_binding_ref is not None:
        result['source_account_contract_ref'] = freeze['source_account_contract_ref']
        result['source_descendant_binding_ref'] = source_binding_ref
    if freeze.get('pto_account_profile') is not None:
        result.update(scientific_identity=freeze['scientific_identity'], pto_account_profile=freeze['pto_account_profile'],
            account_config=freeze['account_config'], cost=freeze['cost'])
    result['source_provenance_ref']=write(root/'PER_USE_SOURCE_PROVENANCE.json',uses)
    result['diagnostics_ref']=write(root/'FEASIBLE_POLICY_DIAGNOSTICS.json',diagnostics)
    result['entitlement_observer_ref']=write(root/'ENTITLEMENT_OBSERVER.json',entitlements)
    result['result_ref']=write(root/'POLICY_RESULT.json',result)
    if task_id == FAST_TRACK_TASK:
        update_account_progress(root, status=status, kind=kind, path_id=pid,
            observed_daily_rows=observed_daily_rows, policy_calls=len(uses),
            last_daily_date=str(current_day.date()) if current_day is not None else None,
            elapsed_seconds=time.perf_counter()-started, full_window_completed=result['full_window_completed'])
    print(json.dumps(dict(event='PAIR_ACCOUNT_TERMINAL',kind=kind,status=status,policy_calls=len(uses),
                         reason=None if failure is None else failure.get('reason'))),flush=True)
    return result


def run_pair(freeze_path, review_path=None, *, task_id=TASK):
    freeze=read(freeze_path)
    review=read(review_path) if review_path is not None else None
    if (task_id not in (TASK, CA_TASK, CAUSAL_HELD_TASK, FAST_TRACK_TASK) or freeze['task_id'] != task_id
            or freeze['status'] != 'FROZEN'):
        raise ValueError('PAIR_IMMUTABLE_FREEZE_REQUIRED')
    source_contract = freeze.get('source_account_contract_ref')
    if (task_id in (CA_TASK, CAUSAL_HELD_TASK, FAST_TRACK_TASK)) != (source_contract is not None):
        raise ValueError('PAIR_SOURCE_ACCOUNT_CONTRACT_SCOPE_REQUIRED')
    bundle = read(pin(source_contract)) if source_contract is not None else None
    if task_id == FAST_TRACK_TASK:
        guard_fast_track_freeze(freeze)
    elif review is None or review.get('status')!='PASS' or review.get('freeze_ref')!={'path':str(Path(freeze_path)), 'sha256':sha(freeze_path)}:
        raise ValueError('PAIR_INDEPENDENT_REVIEW_OF_EXACT_FREEZE_REQUIRED')
    for reference in freeze['source_pins']+freeze['input_pins']: pin(reference)
    if task_id in (CAUSAL_HELD_TASK, FAST_TRACK_TASK):
        if task_id == CAUSAL_HELD_TASK:
            guard_causal_input_freeze(freeze)
    run=Path(freeze['run']);assert_safe_output_path(run,kind='backtest',paths=PATHS)
    if task_id in (CAUSAL_HELD_TASK, FAST_TRACK_TASK) and run.parent.resolve() != (PATHS.backtest_root / task_id).resolve():
        raise ValueError('CAUSAL_DESCENDANT_TASK_RUN_ROOT_REQUIRED')
    output = claim_account_output_scope(run, freeze, task_id)
    if freeze.get('pto_account_profile') is not None and not fast_track_account_order(freeze):
        reused = load_pto_reused_accounts(freeze)
        deferred = load_pto_deferred_source_blocks(freeze)
        if deferred:
            return write(output/'PAIR_ACCOUNT_TRUTH_STAGE.json', dict(
                status='PTO_NO_RUNNABLE_ACCOUNT_SOURCE_BLOCKS_RETAINED',results=reused,
                deferred_account_blocks=deferred,expected_account_count=2,pair_complete=False,
                complete_count=len(reused),qualified_count=len(reused),comparison_ref=None,
                new_predictive_fits=0,new_risk_estimates=0,new_risk_learned_units=0,
                new_risk_physical_operations=0,new_real_account_runs=0,real2026_reads=0,**FLAGS))
        expected = pd.read_parquet(pin(reused[0]['artifacts']['daily']), columns=['date'])['date']
        comparison = publish_pto_account_comparison(output, freeze, reused, expected)
        if comparison is None:
            raise ValueError('PTO_REUSED_ACCOUNTS_REQUIRE_COMPLETE_COMPARISON')
        return write(output/'PAIR_ACCOUNT_TRUTH_STAGE.json', dict(status='PTO_ALL_QUALIFIED_ACCOUNTS_REUSED',
            results=reused, complete_count=len(reused), qualified_count=len(reused), comparison_ref=comparison,
            new_predictive_fits=0, new_risk_estimates=0, new_risk_learned_units=0,
            new_risk_physical_operations=0, new_real_account_runs=0, real2026_reads=0, **FLAGS))
    runtime=module(pin({'path':str(RUNTIME),'sha256':RUNTIME_SHA}),'_new_pair_original_runtime')
    custody=account_custody(runtime)
    interface=custody.load_interface();shared=interface.load_shared();parent=shared.load_parent()
    owner,market,events,input_refs=runtime.runtime_inputs(parent)
    if freeze.get('frozen_history_cash_owner_ref') is not None:
        if task_id != FAST_TRACK_TASK or bundle.get('post_verified_cash_scope') is None:
            raise ValueError('EXPLICIT_FROZEN_HISTORY_CASH_NAMESPACE_REQUIRED')
        owner,events = bind_frozen_history_cash_namespace(owner,events,
            reference=freeze['frozen_history_cash_owner_ref'],shared=shared)
    if len(market.dates)!=752: raise ValueError('PAIR_EXACT_752_SESSIONS_REQUIRED')
    cfg=read(freeze['shared_quote_config_ref']['path'])['shared_quote_B']
    for name in ('source_binding_B_ref','rule_ref','classification_ref','population_ref','clarification_ref'): pin(cfg[name])
    adapter = None
    if bundle is not None:
        bound_parent = bundle.get('parent_cash_kwargs_ref', {})
        actual_parent = input_refs['cash_kwargs']
        if (Path(bound_parent.get('path', '')).resolve() != Path(actual_parent['path']).resolve()
                or bound_parent.get('sha256') != actual_parent['sha256']):
            raise ValueError('PAIR_SOURCE_DESCENDANT_WRONG_ORIGINAL_CASH_INPUT')
        from scripts.research.a2.data.reused_pair_ca_sources import bind_source_account_descendant
        adapter = bind_source_account_descendant
    market,events,usable,coverage,source_bound=bind_account_sources(owner,market,events,
        read(cfg['classification_ref']['path'])['branches']['B']['decisions'],
        shared=shared,bundle=bundle,adapter=adapter,bundle_ref=source_contract)
    cash_clock = None
    lifecycle = owner.apply_entitlement_lifecycle
    source_receipt = None
    if source_bound is not None:
        lifecycle,cash_clock=ordinary_cash_lifecycle(owner,events,
            source_bound['ordinary_cash_event_fingerprints'],clone=shared.clone)
        source_receipt=write(output/'SOURCE_ACCOUNT_DESCENDANT_BINDING.json',dict(
            source_account_contract_ref=source_contract,source_binding=source_bound['receipt'],
            ordinary_cash_clock=cash_clock,original_decision_quality_preserved=True,**FLAGS))
    prior=read(freeze['accounting_freeze_ref']['path'])
    commitments={k:prior[k]['sha256'] for k in ('contract_ref','rule_ref','population_ref')}
    convention=interface.convention_functions(owner,commitments)['load_research_ca_accounting_convention'](freeze['accounting_freeze_ref'])
    event_binding=interface.runtime_event_binding(owner,events,convention)
    runtime_binding=dict(input_refs=input_refs,quote_coverage=coverage,
        event_binding=event_binding,owner_source_custody=custody.relocation_descriptor(),**FLAGS)
    if source_receipt is not None:
        runtime_binding.update(source_account_contract_ref=source_contract,
                               source_descendant_binding_ref=source_receipt)
    write(output/'RUNTIME_INPUT_AND_ACCOUNT_BINDING.json',runtime_binding)
    from scripts.research.a2.inference.reused_r5_risk_inputs import ExistingR5LWInputs
    risk=ExistingR5LWInputs(interface=interface,market_dates=market.dates,master_assets=market.tickers)
    pto = freeze.get('pto_account_profile') is not None
    forecasts=FrozenAnnualOpportunityReader(recipe=PTO_FORECAST_RECIPE) if pto else FrozenAnnualOpportunityReader()
    from scripts.research.a2.inference.reused_policy_inputs import make_raw_control_reader
    raw_forecasts = make_raw_control_reader() if pto and RAW_SOURCE_REUSE_KIND in fast_track_account_order(freeze) else None
    results=load_pto_reused_accounts(freeze) if pto else []
    risk_budget_before = None
    risk_budget_owner = None
    causal_adapters=[]
    source_context = (causal_owner_source_context(freeze, market, events, input_refs,
        runtime_binding['owner_source_custody']['actual_execution_source_ref'], source_receipt,
        typed_ca_owner=owner._frozen_ca_module)
        if task_id in (CAUSAL_HELD_TASK, FAST_TRACK_TASK) else None)
    from threadpoolctl import threadpool_limits
    order = fast_track_account_order(freeze) if task_id == FAST_TRACK_TASK else ('SIMPLE_FEASIBLE','JOINT_REUSE')
    for kind in order:
        boundary,proofs=[],[]
        path_source_context = source_context
        if task_id in (CAUSAL_HELD_TASK, FAST_TRACK_TASK):
            # The original owner below is the sole writer of this path's list.
            # Keep its live reference so accepted PRE_OPEN applicability facts
            # reach the source guard before each later decision, without a copy.
            path_source_context = dict(source_context, account_boundary_context=dict(
                account_id=task_id+'::'+policy_account_label(kind,freeze),
                owner_ref=copy.deepcopy(source_context['owner_ref']),
                convention_ref=copy.deepcopy(freeze['accounting_freeze_ref']), rows=boundary))
        path_risk = (make_causal_input_adapter(freeze, risk, task_id+'::'+policy_account_label(kind,freeze), market, source_context=path_source_context)
                     if task_id in (CAUSAL_HELD_TASK, FAST_TRACK_TASK) else risk)
        if task_id in (CAUSAL_HELD_TASK, FAST_TRACK_TASK):
            causal_adapters.append(path_risk)
            if not pto or kind != RAW_SOURCE_REUSE_KIND or risk_budget_owner is None:
                risk_budget_owner = path_risk
            if pto and risk_budget_before is None:
                risk_budget_before = copy.deepcopy(path_risk.budget_summary())
        if task_id in (CAUSAL_HELD_TASK, FAST_TRACK_TASK):
            fn,lineage=project_causal_preopen_quantities(interface,owner,freeze['accounting_freeze_ref'],
                commitments,boundary,clone=shared.clone)
        else:
            fn,lineage=interface.project_current_owner(owner,freeze['accounting_freeze_ref'],commitments,boundary)
        if freeze.get('frozen_history_cash_owner_ref') is not None:
            ca_owner = owner._frozen_ca_module
            def cash_authority(event_values, authority, quote_domain):
                if quote_domain is not None or not isinstance(authority, dict) or authority.get('schema') != 'B_FROZEN_HISTORY_CASH_ACCOUNT_AUTHORITY_V1':
                    raise ValueError('PAIR_EXACT_STANDALONE_CASH_AUTHORITY_REQUIRED')
                return ca_owner._validate_research_account_authority(event_values,authority)
            fn = shared.clone(fn, _b_reject_a_authority=cash_authority)
            lineage.update(frozen_history_cash_owner_ref=freeze['frozen_history_cash_owner_ref'],
                standalone_B_cash_authority=True, A_or_terminal_authority_added=False,
                original_quantity_and_account_arithmetic_preserved=True)
        private=SimpleNamespace(**vars(owner));private.run_continuous_account=fn
        private.apply_entitlement_lifecycle=lifecycle
        adapted=shared.adapt_owner(private,usable,proofs)
        with threadpool_limits(limits=2):
            result=execute(output,freeze,kind,adapted,market,events,usable,shared,parent,path_risk,
                           raw_forecasts if kind == RAW_SOURCE_REUSE_KIND else forecasts,
                           cash_clock=cash_clock, source_binding_ref=source_receipt, source_context=path_source_context,
                           original_qualifier=interface.original_qualification_gates if task_id == FAST_TRACK_TASK else None)
        label=policy_account_label(kind,freeze)
        result['execution_coordinate_proof_ref']=parent.save_frame(output,label,'execution_coordinate_proof',pd.concat(proofs,ignore_index=True)) if proofs else None
        result['boundary_ref']=parent.save_frame(output,label,'research_ca_session_boundary',pd.DataFrame(boundary)) if boundary else None
        result['account_interface_lineage']=lineage
        results.append(result)
        if (result['status']=='ENGINEERING_FAILURE_REQUIRES_DIAGNOSIS'
                and freeze.get('mechanism_panel_profile') is None): break
    stage_value=dict(status='PAIR_ACCOUNT_STAGE_TERMINAL',results=results,
        complete_count=sum(r['full_window_completed'] for r in results),expected_sessions=752,
        shared_external_information=True,independent_causal_accounts=True,new_predictive_fits=0,
        new_risk_estimates=0,new_inference_calls=0,physical_existing_state_loads=risk.loads_count,**FLAGS)
    if task_id in (CAUSAL_HELD_TASK, FAST_TRACK_TASK):
        stage_value.update(causal_adapter_load_totals(risk, causal_adapters))
    if 'account_output_namespace' in freeze:
        stage_value.update(account_output_namespace=freeze['account_output_namespace'],
            original_managed_run=str(run), account_output_root=str(output), engineering_continuation=True)
    if pto:
        deferred = load_pto_deferred_source_blocks(freeze)
        stage_value.update(deferred_account_blocks=deferred,expected_account_count=2,
            pair_complete=not deferred and len(results)==2 and all(
                r.get('research_account_qualified') is True and r.get('full_window_completed') is True
                for r in results))
    if task_id == FAST_TRACK_TASK:
        stage_value['qualified_count'] = sum(r.get('research_account_qualified') is True for r in results)
        if pto:
            stage_value['comparison_ref'] = publish_pto_account_comparison(output, freeze, results, market.dates)
        elif freeze.get('mechanism_panel_profile') is None:
            stage_value['comparison_ref'] = publish_fast_track_comparison(output, freeze, results, market.dates)
        else:
            stage_value['comparison_ref'] = publish_mechanism_panel_comparison(output,freeze,results,market.dates)
        # Both adapters share this task's durable scope. Read the final owner
        # once; deserializations and inherited paid states are not new fits.
        budget = risk_budget_owner.budget_summary() if risk_budget_owner is not None else risk_budget_before
        stage_value['risk_budget_summary'] = budget
        stage_value['new_risk_estimates'] = budget['new_complete_outputs']
        stage_value['new_risk_learned_units'] = budget['charged_new_learned_units']
        stage_value['new_risk_physical_operations'] = budget['charged_new_physical_operations']
        if pto:
            stage_value['risk_budget_cumulative'] = copy.deepcopy(budget)
            for out_key, key in (('new_risk_estimates','new_complete_outputs'),
                    ('new_risk_learned_units','charged_new_learned_units'),
                    ('new_risk_physical_operations','charged_new_physical_operations')):
                stage_value[out_key] = budget[key] - risk_budget_before[key]
                if stage_value[out_key] < 0: raise ValueError('PTO_RISK_BUDGET_COUNTER_REGRESSED')
    stage=write(output/'PAIR_ACCOUNT_TRUTH_STAGE.json',stage_value)
    return stage


def publish_fast_track_comparison(output, freeze, results, expected_sessions):
    """Consume the existing descriptive metric owner only after both ten gates."""
    if (len(results) != 2 or any(r.get('research_account_qualified') is not True
            or not r.get('full_window_completed') for r in results)):
        return None
    if ({r['kind'] for r in results} != {'SIMPLE_FEASIBLE','JOINT_REUSE'}
            or len({r['path_id'] for r in results}) != 2
            or any(r.get('source_account_contract_ref') != freeze['source_account_contract_ref']
                   for r in results)
            or results[0]['source_descendant_binding_ref'] != results[1]['source_descendant_binding_ref']):
        raise ValueError('FAST_TRACK_MATCHED_SOURCE_AND_INDEPENDENT_ACCOUNTS_REQUIRED')
    from scripts.research.a2.evaluation.reused_policy_pair_economics import (
        evaluate_reused_account, compare_reused_pair)
    evaluated = {}
    for result in results:
        frames={name:pd.read_parquet(pin(reference)) for name,reference in result['artifacts'].items()
                if name in TABLES}
        candidate=dict(candidate_id=result['path_id'],scientific_tuple_sha256=freeze['scientific_identity'],
            execution_friction=dict(one_way_bps=policy_execution_bps(freeze)))
        value=evaluate_reused_account(candidate,frames,expected_sessions=expected_sessions,
            account_truth_passed=True,complete=True,first_failure=result['first_failure'])
        value['source_account_contract_ref']=freeze['source_account_contract_ref']
        value['research_account_gates']=result['research_account_gates']
        evaluated[result['kind']]=value
    comparison=compare_reused_pair(evaluated['SIMPLE_FEASIBLE'],evaluated['JOINT_REUSE'])
    value=dict(schema='B_FAST_TRACK_MATCHED_PAIR_DESCRIPTIVE_COMPARISON_V1', accounts=evaluated,
        comparison=comparison, source_account_contract_ref=freeze['source_account_contract_ref'],
        actual_cost_already_in_cash_and_NAV=True, costs_deducted_twice=False,
        scientific_winner=None, **FLAGS)
    sensitivity=cost_sensitivity_profile(freeze)
    if sensitivity is not None:
        value.update(schema='B_FAST_TRACK_MATCHED_PAIR_COST_SENSITIVITY_DESCRIPTIVE_V1',
            cost_sensitivity_profile=copy.deepcopy(sensitivity),
            original_primary_pair_ref=freeze['completed_pair_comparison_ref'])
    return write(Path(output)/'PAIR_COST_AFTER_DESCRIPTIVE_COMPARISON.json',value)


def publish_mechanism_panel_comparison(output,freeze,results,expected_sessions):
    """Reuse the descriptive owner for frozen contrasts; incomplete paths stay explicit."""
    if freeze.get("mechanism_panel_profile") != MECHANISM_PANEL_PROFILE:
        raise ValueError("EXACT_FROZEN_MECHANISM_PANEL_PROFILE_REQUIRED")
    main=guard_completed_main_pair(freeze)
    from scripts.research.a2.evaluation.reused_policy_pair_economics import (
        evaluate_reused_account,compare_reused_pair)
    accounts=dict(main["accounts"])
    excluded={}
    for result in results:
        kind=result["kind"]
        if kind not in MECHANISM_PANEL_POLICIES or kind in accounts or kind in excluded:
            raise ValueError("PANEL_UNIQUE_FIXED_KIND_REQUIRED")
        if result.get("source_account_contract_ref")!=freeze["source_account_contract_ref"]:
            raise ValueError("PANEL_COMMON_SOURCE_ACCOUNT_CONTRACT_REQUIRED")
        if (not result.get("full_window_completed") or result.get("research_account_qualified") is not True):
            excluded[kind]=dict(status="NOT_ECONOMICALLY_COMPARABLE",
                account_status=result.get("status"),first_failure=result.get("first_failure"),
                gates=result.get("research_account_gates"))
            continue
        frames={name:pd.read_parquet(pin(ref)) for name,ref in result["artifacts"].items() if name in TABLES}
        candidate=dict(candidate_id=result["path_id"],scientific_tuple_sha256=freeze["scientific_identity"],
            execution_friction=dict(one_way_bps=10))
        value=evaluate_reused_account(candidate,frames,expected_sessions=expected_sessions,
            account_truth_passed=True,complete=True,first_failure=result["first_failure"])
        value["source_account_contract_ref"]=freeze["source_account_contract_ref"]
        value["research_account_gates"]=result["research_account_gates"]
        accounts[kind]=value
    if set(accounts).union(excluded)!={"SIMPLE_FEASIBLE","JOINT_REUSE",*MECHANISM_PANEL_POLICIES}:
        raise ValueError("PANEL_ALL_FOUR_DESCENDANTS_REQUIRE_TERMINAL_EVIDENCE")
    definitions={
        "P0_CONDITIONAL_USE":("JOINT_REUSE_NO_ALPHA","JOINT_REUSE"),
        "Q0_RISK_CONFIGURATION_BUNDLE":("SIMPLE_FEASIBLE","JOINT_REUSE"),
        "GROSS_CASH":("JOINT_REUSE","JOINT_REUSE_G1"),
        "STATEFUL_ACTION":("JOINT_REUSE","JOINT_REUSE_A2"),
        "COMBINED_VS_SIMPLE":("SIMPLE_FEASIBLE","JOINT_REUSE_G1_A2"),
        "COMBINED_VS_BASE_JOINT":("JOINT_REUSE","JOINT_REUSE_G1_A2"),
    }
    contrasts={}
    for name,(reference,challenger) in definitions.items():
        if reference not in accounts or challenger not in accounts:
            contrasts[name]=dict(status="NOT_ECONOMICALLY_COMPARABLE",reference=reference,challenger=challenger)
        else:
            value=compare_reused_pair(accounts[reference],accounts[challenger])
            value.update(reference_kind=reference,challenger_kind=challenger,
                         difference_coordinate="CHALLENGER_MINUS_REFERENCE")
            contrasts[name]=value
    interaction_kinds=("JOINT_REUSE_G1_A2","JOINT_REUSE_G1","JOINT_REUSE_A2","JOINT_REUSE")
    interaction=dict(status="NOT_ECONOMICALLY_COMPARABLE")
    if all(k in accounts for k in interaction_kinds):
        signs=(1.,-1.,-1.,1.)
        interaction=dict(status="DESCRIPTIVE_POLICY_INTERACTION",
            formula="combined-G1-A2+base",exogenous_causal_effect=False,
            cumulative_return=sum(s*accounts[k]["economic_metrics"]["cumulative_return"]
                                  for k,s in zip(interaction_kinds,signs)),
            yearly_return={y:sum(s*accounts[k]["yearly"][y]["total_return"]
                                  for k,s in zip(interaction_kinds,signs)) for y in ("2023","2024","2025")})
    return write(Path(output)/"MECHANISM_PANEL_COST_AFTER_DESCRIPTIVE_COMPARISON.json",dict(
        schema="B_FOUR_FIXED_MECHANISM_DESCENDANTS_DESCRIPTIVE_V1",
        accounts=accounts,excluded=excluded,contrasts=contrasts,interaction=interaction,
        original_pair_ref=freeze["completed_pair_comparison_ref"],
        source_account_contract_ref=freeze["source_account_contract_ref"],
        opportunity_scope=MECHANISM_PANEL_PROFILE["opportunity_scope"],
        actual_cost_already_in_cash_and_NAV=True,costs_deducted_twice=False,
        scientific_winner=None,**FLAGS))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--freeze',required=True);parser.add_argument('--review')
    parser.add_argument('--task-id',choices=(TASK,CA_TASK,CAUSAL_HELD_TASK,FAST_TRACK_TASK),default=TASK)
    args=parser.parse_args();print(json.dumps(run_pair(args.freeze,args.review,task_id=args.task_id)),flush=True)

if __name__=='__main__': main()