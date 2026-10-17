"""R9 pre-outcome branch manifests and finite DAG; no account or fit implementation.

The state/action consumer and unique continuous engine own all economics.
This module enumerates signal-legal identities and delegates real qualification
back to the frozen R5 owner. A metadata readiness result never activates a run.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import math
import re
import pandas as pd

DESIGN_SHA = '45addfc866d4de39dc76eef0996ec5c0d3a65b84c0228d5619c797237b4f7456'
SOURCE_SLOTS = ('market_quote_authority', 'security_identity_binding', 'cash_source_bundle',
                'MKFG_terminal_binding', 'MKFG_settlement_authority')
GATES = ('accounting', 'quote_source', 'certified_nav', 'cash', 'entitlement', 'terminal', 'required_audits')
GROSS_GRID = (0., .25, .5, .75, 1.)
MAX_BRANCHES = 60000
FORBIDDEN_OUTCOMES = {'y', 'label', 'outcome', 'ending_nav', 'terminal_nav', 'return', 'profit', 'winner'}
SHA = re.compile(r'^[0-9a-f]{64}$')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _require(ok, reason):
    if not ok:
        raise ValueError(reason)


def _no_outcome(value):
    if isinstance(value, dict):
        _require(not (set(value) & FORBIDDEN_OUTCOMES), 'OUTCOME_NOT_ALLOWED_IN_BRANCH_FORMATION')
        for item in value.values():
            _no_outcome(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _no_outcome(item)


def _time(value):
    stamp = pd.Timestamp(value)
    _require(not pd.isna(stamp) and stamp.date() < pd.Timestamp('2026-01-01').date(), 'PRE2026_CLOCK_REQUIRED')
    return stamp


def readiness_gate(source_slots, seven_groups):
    """Cheap literal checks only; successful metadata still needs owner validation."""
    missing = []
    for slot in SOURCE_SLOTS:
        item = source_slots.get(slot, {}) if isinstance(source_slots, dict) else {}
        if not isinstance(item, dict) or any(item.get(k) is not True for k in ('approved', 'source_qualified')):
            missing.append(slot)
        elif not isinstance(item.get('ref'), dict) or not item['ref'].get('path') or not SHA.fullmatch(str(item['ref'].get('sha256', ''))):
            missing.append(slot)
    groups = {k: isinstance(seven_groups, dict) and seven_groups.get(k) is True for k in GATES}
    return {'status': 'READY_FOR_FROZEN_R5_OWNER_VALIDATION' if not missing and all(groups.values())
            else 'NOT_TESTABLE_SOURCE_ACCOUNT_AUTHORITY', 'unbound_slots': missing,
            'groups': groups, 'real_execution_admitted': False}


def require_real_reference(r5_run, r5_auth):
    """Real source objects and baseline receipts are validated by the existing owner."""
    _require(r5_run is not None and isinstance(r5_auth, dict), 'QUALIFIED_REAL_RAW_REFERENCE_UNBOUND')
    from scripts.research.a2.training import stateful_execution as owner
    owner.r5_source_decision(r5_auth, verify_refs=True)
    result = owner.r5_baseline_gate(r5_run, r5_auth)
    _require(result.get('all_passed') is True and all(result.get('groups', {}).get(k) is True for k in GATES),
             'REQUIRED_RAW_BASELINE_UNQUALIFIED')
    return result


def mechanical_actions(stocks, reference_gross):
    """All eligible pairs before labels; membership uses signal-state flags only."""
    _no_outcome(stocks)
    _require(isinstance(reference_gross, (int, float)) and not isinstance(reference_gross, bool)
             and math.isfinite(reference_gross) and 0 <= reference_gross <= 1, 'REFERENCE_GROSS_UNKNOWN')
    from scripts.research.a2.training.stateful_decision import _valid_sid
    seen = set()
    for row in stocks:
        sid = row.get('sid')
        _require(isinstance(sid, str) and _valid_sid(sid) and sid != row.get('ticker') and not sid.strip().upper().startswith('A2_TICKER_') and sid not in seen,
                 'EXACT_SECURITY_IDENTITY_REQUIRED')
        seen.add(sid)
        for flag in ('is_held', 'decision_eligible', 'buy_eligible', 'sell_eligible', 'raw_buy_pool', 'terminal_closed'):
            _require(type(row.get(flag)) is bool, 'UNKNOWN_SIGNAL_ACTION_SUPPORT:' + flag)
        _require(not (row['is_held'] and row['terminal_closed']), 'TERMINAL_SHARES_NOT_EXTINGUISHED')
        if row['decision_eligible'] and not row['terminal_closed'] and (row['is_held'] or (row['raw_buy_pool'] and row['buy_eligible'])):
            _require(isinstance(row.get('raw_rank'), (float, int)) and not isinstance(row.get('raw_rank'), bool) and math.isfinite(row['raw_rank']), 'RAW_RANK_UNKNOWN')
    order = lambda row: (row['raw_rank'], row['sid'])
    entrants = sorted((r for r in stocks if not r['is_held'] and r['raw_buy_pool']
                       and r['buy_eligible'] and r['decision_eligible'] and not r['terminal_closed']), key=order)
    incumbents = sorted((r for r in stocks if r['is_held'] and r['decision_eligible']), key=order)
    actions = []
    for entrant in entrants:
        actions.extend({'objective': 'ENTRY_ADVANTAGE', 'action': a, 'entrant_sid': entrant['sid']}
                       for a in ('SKIP', 'BUY'))
    for incumbent in incumbents:
        actions.append({'objective': 'INCUMBENT_ADVANTAGE', 'action': 'HOLD', 'incumbent_sid': incumbent['sid']})
        if incumbent['sell_eligible']:
            actions.append({'objective': 'INCUMBENT_ADVANTAGE', 'action': 'SELL', 'incumbent_sid': incumbent['sid']})
            actions.extend({'objective': 'INCUMBENT_ADVANTAGE', 'action': 'REPLACE',
                            'incumbent_sid': incumbent['sid'], 'entrant_sid': entrant['sid']} for entrant in entrants)
    actions.append({'objective': 'SCALAR_GROSS_ADVANTAGE', 'action': 'REFERENCE_GROSS', 'gross': float(reference_gross)})
    actions.extend({'objective': 'SCALAR_GROSS_ADVANTAGE', 'action': 'GROSS', 'gross': g} for g in GROSS_GRID)
    return actions



def _verified_snapshot(snapshot):
    from scripts.research.a2.training import stateful_account_decision as consumer
    from scripts.research.a2.training.stateful_decision import _valid_sid
    payload = snapshot.get('prefix_payload')
    _require(isinstance(payload, dict), 'SUPPLEMENTAL_EXACT_PREFIX_PAYLOAD_REQUIRED')
    consumer.verify_reference_prefix(snapshot, snapshot['prefix_identity'])
    for key in ('signal_index', 'signal_date', 'signal_asof', 'source_account_identity', 'quantity_coordinate', 'account'):
        _require(consumer._digest(snapshot[key]) == consumer._digest(payload.get(key)), 'SNAPSHOT_PREFIX_FIELD_MISMATCH:' + key)
    _require(consumer._digest(snapshot['stocks']) == consumer._digest(payload.get('decision_state_stocks')), 'SNAPSHOT_ACTION_SUPPORT_NOT_PREFIX_BOUND')
    coordinates = payload.get('securities')
    _require(isinstance(coordinates, list) and coordinates, 'FULL_ENGINE_SECURITY_COORDINATE_REQUIRED')
    seen = set()
    for row in coordinates:
        sid = row.get('sid')
        _require(isinstance(sid, str) and _valid_sid(sid) and not sid.strip().upper().startswith('A2_TICKER_') and sid != row.get('ticker') and sid not in seen, 'EXACT_SECURITY_IDENTITY_REQUIRED')
        _require(isinstance(row.get('raw_fractional_shares'), (int, float)) and math.isfinite(row['raw_fractional_shares']) and row['raw_fractional_shares'] >= 0, 'RAW_QUANTITY_REQUIRED')
        seen.add(sid)
    lookup = {r['sid']: r for r in coordinates}
    _require(all(r['sid'] in lookup and r['ticker'] == lookup[r['sid']]['ticker'] for r in snapshot['stocks']), 'ACTION_COORDINATE_NOT_IN_ENGINE_UNIVERSE')
    return coordinates


def build_branch_manifest(snapshots, planner, calendar, binding, *, max_branches=MAX_BRANCHES):
    """Compile the complete mechanical set, retain exact-intent aliases, no outcome reads.

    planner(snapshot, action) must consume the existing frozen planner and return
    full weights/explicit_mask plus its source-bound planner_intent. This module
    never sizes shares, estimates cash, or simulates an action.
    """
    _require(type(max_branches) is int and 0 < max_branches <= MAX_BRANCHES, 'BRANCH_CAP_EXPANSION_FORBIDDEN')
    _no_outcome(binding)
    source_identity = binding.get('source_account_identity', {})
    _require(isinstance(source_identity, dict) and all(source_identity.get(k) for k in ('reference_run_id', 'source_account_id', 'reference_policy_sha256', 'q_contract_sha256', 'friction_contract_sha256', 'security_binding_sha256')), 'EXACT_REFERENCE_SOURCE_IDENTITY_REQUIRED')
    _require(source_identity['reference_policy_sha256'] == binding['continuation_policy_sha'] and source_identity['q_contract_sha256'] == binding['fixed_q_contract_sha256'] and source_identity['friction_contract_sha256'] == digest(binding['friction']), 'REFERENCE_POLICY_Q_FRICTION_IDENTITY_MISMATCH')
    reference_gross = binding.get('reference_gross_intent')
    _require(isinstance(reference_gross, (int, float)) and not isinstance(reference_gross, bool) and math.isfinite(reference_gross) and 0 <= reference_gross <= 1, 'REFERENCE_GROSS_INTENT_UNBOUND')
    for key in ('reference_run_source_account_id', 'continuation_policy_sha', 'fixed_q_contract_sha256'):
        _require(isinstance(binding.get(key), str) and bool(binding[key].strip()), 'BRANCH_BINDING_UNBOUND:' + key)
    _require(SHA.fullmatch(binding['continuation_policy_sha']) and SHA.fullmatch(binding['fixed_q_contract_sha256']), 'BRANCH_SOURCE_SHA_REQUIRED')
    _require(isinstance(binding.get('source_event_quote_bindings'), dict) and binding['source_event_quote_bindings'], 'SOURCE_EVENT_QUOTE_BINDINGS_REQUIRED')
    friction = binding.get('friction', {})
    _require(friction.get('one_way_bps') == 10 and type(friction.get('one_way_bps')) is int
             and friction.get('fee_bps') == 0 and friction.get('benchmark') == 'NEXT_RAW_OPEN', 'FROZEN_R9_10BPS_CONTRACT_REQUIRED')
    dates = pd.DatetimeIndex(pd.to_datetime(calendar))
    _require(not dates.empty and dates.is_monotonic_increasing and not dates.has_duplicates
             and not dates.hasnans and dates.tz is None and dates.equals(dates.normalize()), 'LEGAL_SESSION_CALENDAR_REQUIRED')
    _require(dates[-1] < pd.Timestamp('2026-01-01'), 'LOCKED_2026_CALENDAR_FORBIDDEN')
    branches = {}; aliases = []; blocked = []
    for snapshot in snapshots:
        _no_outcome(snapshot)
        coordinates = _verified_snapshot(snapshot)
        stamp = _time(snapshot['signal_asof']); day = _time(snapshot['signal_date']).normalize()
        _require(stamp.date() == day.date() and day in dates, 'SIGNAL_CLOCK_CALENDAR_MISMATCH')
        prefix = snapshot['prefix_identity']
        _require(SHA.fullmatch(str(prefix.get('sha256', ''))) and prefix.get('precision') == 'EXACT_FLOAT64_HEX_NO_ROUND', 'EXACT_PREFIX_IDENTITY_REQUIRED')
        _require(snapshot['source_account_identity'] == source_identity, 'REFERENCE_SOURCE_ACCOUNT_IDENTITY_MISMATCH')
        _require(snapshot.get('quantity_coordinate') == 'RAW_OLD_SECURITY_SHARES', 'RAW_QUANTITY_COORDINATE_REQUIRED')
        idx = dates.get_loc(day)
        if idx + 5 >= len(dates):
            blocked.append({'path_id': snapshot['path_id'], 'signal_asof': stamp.isoformat(), 'reason': 'FIVE_SESSION_HORIZON_UNAVAILABLE'})
            continue
        horizon = dates[idx + 5]
        actions = mechanical_actions(snapshot['stocks'], reference_gross)
        for action in actions:
            compiled = planner(deepcopy(snapshot), deepcopy(action)); _no_outcome(compiled)
            weights, explicit = compiled.get('weights'), compiled.get('explicit_mask')
            _require(isinstance(weights, list) and isinstance(explicit, list) and len(weights) == len(explicit) == len(coordinates), 'FULL_FROZEN_PLANNER_INTENT_REQUIRED')
            _require(all(isinstance(w, (int, float)) and not isinstance(w, bool) and math.isfinite(w) and w >= 0 for w in weights)
                     and sum(weights) <= 1 + 1e-10 and all(type(v) is bool for v in explicit), 'INVALID_FROZEN_PLANNER_INTENT')
            intent = compiled.get('planner_intent', {})
            _require(intent.get('prefix_sha256') == prefix['sha256'] and intent.get('q_contract_sha256') == binding['fixed_q_contract_sha256']
                     and intent.get('friction_contract_sha256') == source_identity['friction_contract_sha256'], 'PLANNER_SOURCE_PREFIX_FRICTION_NOT_BOUND')
            available = _time(intent.get('available_at'))
            _require(available.tzinfo == stamp.tzinfo and available <= stamp, 'FUTURE_PLANNER_INTENT')
            core = {'reference_run_source_account_id': binding['reference_run_source_account_id'],
                    'source_account_identity': source_identity,
                    'reference_path_id': snapshot.get('reference_path_id', 'RAW_s10'),
                    'prefix_identity': prefix, 'signal_asof': stamp.isoformat(), 'signal_index': snapshot['signal_index'],
                    'SID_quantity_coordinate': {'coordinate': snapshot['quantity_coordinate'],
                        'stocks': deepcopy(coordinates)},
                    'continuation_policy_sha': binding['continuation_policy_sha'], 'horizon_end': str(horizon.date()),
                    'execution_session': str(dates[idx + 1].date()), 'fixed_q_contract_sha256': binding['fixed_q_contract_sha256'],
                    'friction': friction, 'source_event_quote_bindings': binding['source_event_quote_bindings'],
                    'target_decision': {'weights': weights, 'explicit_mask': explicit}}
            branch_sha = digest(core)
            alias = {'action_semantic_intent': action, 'branch_sha256': branch_sha, 'planner_intent': intent}
            aliases.append(alias)
            if branch_sha not in branches:
                branches[branch_sha] = {'branch_sha256': branch_sha, **core,
                    'terminal_nav_qualification': 'UNASSESSED_REQUIRED', 'status': 'NOT_EXECUTED'}
    count = len(branches)
    return {'schema': 'R9_COMPLETE_PRE_OUTCOME_BRANCH_MANIFEST_R1',
            'status': 'BLOCKED_BUDGET' if count > max_branches else 'PRE_OUTCOME_MANIFEST_COMPLETE_NOT_EXECUTED',
            'branch_cap': max_branches, 'required_distinct_branches': count, 'mechanical_action_aliases': len(aliases),
            'branches': list(branches.values()), 'aliases': aliases, 'unsupported_horizons': blocked,
            'complete_set_before_outcome': True, 'outcome_read': False, 'real_branches_executed': 0,
            'manifest_sha256': digest({'branches': list(branches.values()), 'aliases': aliases, 'unsupported_horizons': blocked})}



def compile_existing_action(reference, ctx, snapshot, action, planner_intent):
    """Compile through the one action consumer; no parallel decision implementation."""
    from scripts.research.a2.training.stateful_account_decision import single_action_override
    intervention = {**action, 'path_id': snapshot['path_id'], 'signal_index': snapshot['signal_index'],
                    'planner_intent': deepcopy(planner_intent)}
    target = single_action_override(reference, ctx, snapshot, intervention)
    p = tuple(ctx.path_ids).index(snapshot['path_id'])
    return {'weights': target.weights[p].tolist(), 'explicit_mask': target.explicit_mask[p].tolist(),
            'planner_intent': deepcopy(planner_intent)}


def reserve_branch_attempt(manifest, journal, branch_sha, *, elapsed_seconds=0.):
    """One attempt per scientific identity, including failures; no retry or refunds."""
    _require(manifest.get('status') == 'PRE_OUTCOME_MANIFEST_COMPLETE_NOT_EXECUTED'
             and manifest.get('complete_set_before_outcome') is True, 'COMPLETE_WITHIN_BUDGET_MANIFEST_REQUIRED')
    _require(math.isfinite(elapsed_seconds) and 0 <= elapsed_seconds < 7200, 'BLOCKED_BUDGET_WALL')
    identities = {r['branch_sha256'] for r in manifest['branches']}
    _require(branch_sha in identities and len(identities) <= MAX_BRANCHES, 'UNKNOWN_BRANCH_IDENTITY')
    _require(not any(row['branch_sha256'] == branch_sha for row in journal), 'SCIENTIFIC_BRANCH_RETRY_FORBIDDEN')
    _require(len(journal) < manifest['branch_cap'], 'BLOCKED_BUDGET_BRANCH_CAP')
    _require(sum(row.get('status') == 'STARTED' for row in journal) < 32, 'MAX32_BRANCH_ROWS')
    journal.append({'branch_sha256': branch_sha, 'status': 'STARTED', 'full_prefix_replay_attempt': 1})
    return journal[-1]



def qualified_terminal_value(branch, replay, path_id, *, quote_source_verified=False):
    """Reuse the account owner's audits; final NAV is never input to branch selection."""
    _require(quote_source_verified is True, 'COUNTERFACTUAL_QUOTE_SOURCE_AUTHORITY_UNBOUND')
    from scripts.research.a2.training.stateful_replay import qualification_checks
    checks = qualification_checks(replay, path_id)
    keys = ('accounting_qualified', 'quote_qualified', 'certified_NAV_all_window_finite',
            'cash_identity_correct', 'entitlement_identity_correct')
    _require(all(checks.get(k) is True for k in keys), 'COUNTERFACTUAL_ACCOUNT_NOT_TESTABLE')
    if replay.metadata.get('terminal_lifecycle_enabled') is True:
        _require(checks.get('terminal_identity_correct') is True and checks.get('terminal_settlement_qualified') is True,
                 'COUNTERFACTUAL_TERMINAL_NOT_TESTABLE')
    daily = replay.daily.loc[replay.daily.path_id.eq(path_id)].sort_values('date')
    dates = pd.DatetimeIndex(pd.to_datetime(daily.date))
    _require(not dates.empty and not dates.has_duplicates and dates.is_monotonic_increasing
             and dates[-1] == pd.Timestamp(branch['horizon_end'])
             and dates[-1] < pd.Timestamp('2026-01-01'), 'EXACT_BRANCH_HORIZON_AND_CONTINUITY_REQUIRED')
    _require(replay.metadata.get('execution_friction') == branch['friction'], 'BRANCH_FRICTION_CUSTODY_MISMATCH')
    nav = float(daily.iloc[-1].certified_nav)
    _require(math.isfinite(nav) and nav > 0, 'CERTIFIED_TERMINAL_NAV_REQUIRED')
    return {'branch_sha256': branch['branch_sha256'], 'terminal_nav_qualification': True,
            'certified_terminal_nav': nav, 'qualification_checks': checks}


def physical_fit_dag(design):
    """Exact inner slots and conditional outer upper reservations; no model fitting."""
    _require(design['training_budget']['physical_fit_hard_cap'] == 174, 'FROZEN174_REQUIRED')
    heads = [row['objective_id'] for row in design['objectives']]
    nodes = []
    for fold in design['folds']:
        year = fold['outer_year']
        for head in heads:
            scaler = f'R9_{year}_{head}_INNER_SHARED_SCALER'
            nodes.append({'node_id': scaler, 'kind': 'SCALER', 'stage': 'INNER', 'outer_year': year,
                          'dependencies': ['QUALIFIED_ACCOUNT_STATE_LABELS', 'CHRONOLOGICAL_CORE_MASK'], 'status': 'NOT_ADMITTED'})
            for model in design['models']:
                for capacity in ('LOW', 'MID', 'HIGH'):
                    for seed in model['seeds']:
                        ident = f'R9_{year}_{head}_INNER_{model["family"]}_{capacity}_{seed}'
                        deps = ['QUALIFIED_ACCOUNT_STATE_LABELS', 'CHRONOLOGICAL_CORE_MASK']
                        if model['family'] in ('RIDGE', 'MLP'):
                            deps.append(scaler)
                        nodes.append({'node_id': ident, 'kind': 'ESTIMATOR', 'stage': 'INNER', 'outer_year': year,
                                      'family': model['family'], 'capacity': capacity, 'seed': seed,
                                      'dependencies': deps, 'status': 'NOT_ADMITTED'})
            nodes.append({'node_id': f'R9_{year}_{head}_OUTER_SHARED_SCALER', 'kind': 'CONDITIONAL_SCALER',
                          'stage': 'OUTER', 'outer_year': year, 'dependencies': ['COMMON_THREE_HEAD_INNER_SELECTION'], 'status': 'CONDITIONAL_RESERVATION_NOT_A_FIT'})
            for seed_slot in range(3):
                nodes.append({'node_id': f'R9_{year}_{head}_OUTER_SELECTED_SEED_SLOT_{seed_slot}', 'kind': 'CONDITIONAL_ESTIMATOR',
                              'stage': 'OUTER', 'outer_year': year, 'dependencies': ['COMMON_THREE_HEAD_INNER_SELECTION', 'FULL_LEGAL_OUTER_TRAINING_MASK'],
                              'status': 'CONDITIONAL_RESERVATION_NOT_A_FIT'})
    _require(len(nodes) == 174 and len({n['node_id'] for n in nodes}) == 174, 'PHYSICAL174_DAG_IDENTITY')
    return {'schema': 'R9_PHYSICAL_DAG_R1', 'nodes': nodes, 'inner_estimator_slots': 144, 'inner_scaler_slots': 6,
            'conditional_outer_estimator_upper': 18, 'conditional_outer_scaler_upper': 6, 'physical_fit_hard_cap': 174,
            'actual_estimator_fits': 0, 'actual_scaler_fits': 0, 'failed_fits': 0, 'scientific_retry': 0,
            'ensemble_fit': 0, 'calibrator_fit': 0, 'real_training_admitted': False}
