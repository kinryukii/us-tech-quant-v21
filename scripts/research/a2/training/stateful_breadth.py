"""Post-R5 breadth stage; composes the frozen controller and shared replay APIs.

This module owns only identity, typed metadata admission and a bounded stage.
It has no Controller class, fitting, policy, fill, cash or corporate-action logic.
No run is created by importing it or by preparing its inactive template.
"""
from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path

from scripts.research.a2.training import stateful_execution as execution
from scripts.research.a2.training import stateful_completion as meta
from scripts.research.a2.training import stateful_values as values
from scripts.storage.storage_r2a import assert_write_path, write_json_atomic

DESIGN_SHA = 'd9ca279bcbe22c1f2ea5a9d17d2c76ecf8f98d1b5b4dac1c4c212dad64669488'
NAMESPACE = 'V24_A_BREADTH_PRE2026_R1'
GATES = ('accounting', 'quote_source', 'certified_nav', 'cash', 'entitlement',
         'terminal', 'required_audits')
PROTECTED = {
    'scripts/research/a2/training/stateful_execution.py':
        'b59030b6ec8da7e600297c46f3f078adf743a74b793ea20a65e844abafab446d',
    'scripts/research/a2/training/stateful_completion.py':
        '59df0e8d389c5c905c737df60cab2d183ac5b7a8b7c87f23f8a8b87573073bf0',
    'scripts/research/a2/training/stateful_replay.py':
        '2ea7cca05f4ab1029a1effc4849fccfbd95773892543ad3f4bf8dece9223aa11',
    'scripts/research/a2/evaluation/continuous_research_account.py':
        'b9bd90d88b0c678698092341483c3129931e007dfe892b25a61fd26eaf0c4d35',
    'scripts/v22/corporate_action_transition_r1.py':
        '79cb09efb1d4a25c8a746cd015cbc873b926b77e9c2a30e2ca82f5f583750e32',
}
Blocked = execution.ExecutionBlocked


def require(condition, code):
    if not condition:
        raise Blocked(code)


def protected_custody():
    for name, expected in PROTECTED.items():
        require(values.sha(values.REPO/name) == expected, 'BREADTH_PROTECTED_SOURCE_CHANGED')
    return dict(PROTECTED)


def read_design(path):
    path = Path(path).resolve()
    require(values.sha(path) == DESIGN_SHA, 'BREADTH_FROZEN_DESIGN_CHANGED')
    design = execution.read_json(path)
    validate_design(design)
    return design


def validate_design(design):
    s = design.get('specification', {})
    c = s.get('candidates_in_exact_order', [])
    require(design.get('schema_id') == 'A_BREADTH_FROZEN_DESIGN_R1'
            and s.get('research_id') == NAMESPACE
            and values.digest(s) == design.get('specification_sha256'),
            'BREADTH_SPECIFICATION_CHANGED')
    require(len(c) == 19 and len({r.get('candidate_id') for r in c}) == 19
            and len({r.get('scientific_tuple_sha256') for r in c}) == 19
            and [r.get('ordinal') for r in c] == list(range(1, 20)),
            'BREADTH_EXACT19_ORDER_IDENTITY')
    require(Counter(r.get('breadth_layer') for r in c) ==
            {'VALUE_MAIN': 9, 'FUSION_MAIN': 4, 'PRESELECTED_INTERACTION': 6},
            'BREADTH_STRUCTURED_DESIGN')
    require(s.get('fit_policy', {}).get('new_fit_hard_limit') == 0
            and s.get('budget', {}).get('new_account_attempt_hard_limit') == 19
            and s.get('breadth_is_not_a_R5_prerequisite') is True,
            'BREADTH_FROZEN_SCOPE')
    return c


def identity_template(design):
    """Separate execution namespace; every source binding remains explicitly empty."""
    candidates = validate_design(design)
    return {
        'schema_id': 'A_BREADTH_EXECUTION_IDENTITY_R1',
        'namespace': NAMESPACE, 'status': 'INACTIVE_TEMPLATE',
        'design_sha256': DESIGN_SHA,
        'specification_sha256': design['specification_sha256'],
        'candidate_order': [c['candidate_id'] for c in candidates],
        'candidate_tuples': [c['scientific_tuple_sha256'] for c in candidates],
        'new_fit_hard_limit': 0, 'max_new_account_paths': 19,
        'prior_fit_units': 455, 'prior_account_paths_after_R5': 127,
        'max_cumulative_account_paths': 146,
        'parent_R5_run': None, 'parent_R5_source_account_fingerprint': None,
        'bank_input_manifest_sha256': design['parent_custody']['input_manifest']['sha256'],
        'registry_admission': None,
        'source_slots': {k: {'state': 'UNBOUND', 'approved': False,
                            'source_qualified': False, 'ref': None}
                         for k in execution.R5_SOURCE_SLOTS},
        'execution_authority': None, 'source_activated': False,
        'Branch_N_adopted': False, 'strict_PIT_promotion_eligible': False,
        'real_run_created': False, '2026_locked': True,
        'account_contract': copy.deepcopy(design['specification']['account']),
        'controller_sha256': PROTECTED['scripts/research/a2/training/stateful_execution.py'],
        'adapter_sha256': values.sha(Path(__file__)),
    }


def _contains(actual, frozen):
    if isinstance(frozen, dict):
        return isinstance(actual, dict) and all(k in actual and _contains(actual[k], v) for k, v in frozen.items())
    return actual == frozen


def _small_ref(parent, ref):
    path = execution.own_path(Path(parent).resolve(), ref['path'])
    require(execution._sha_identity(ref.get('sha256')) and path.is_file()
            and values.sha(path) == ref['sha256'], 'BREADTH_METADATA_REFERENCE_CHANGED')
    return path


def _metadata(parent, ref, schema):
    return meta.read_metadata(Path(parent).resolve(), _small_ref(parent, ref), schema)


def packet_specs(design):
    result = {}
    for name, dep in design['exact_fit_prediction_publication_dependency_refs'].items():
        result[name] = {'source_kind': dep['source_kind'],
                        'annual': {y: copy.deepcopy(e['refs'])
                                   for y, e in dep['annual'].items()}}
    risk = {}
    for name, dep in design['exact_risk_dependency_refs'].items():
        risk[name] = {'annual': {y: copy.deepcopy(e['refs'])
                                for y, e in dep['annual'].items()}}
    return result, risk


def validate_dependencies(design):
    """Read only small producer metadata. No model/parquet is opened or hashed."""
    parent = Path(design['parent_custody']['run_config']['path']).resolve().parent
    manifest_sha = design['parent_custody']['input_manifest']['sha256']
    _small_ref(parent, design['parent_custody']['input_manifest'])
    for ref in design['implementation_source_pins'].values():
        require(values.sha(Path(ref['path'])) == ref['sha256'], 'BREADTH_PRODUCER_SOURCE_CHANGED')
    packets, risks = packet_specs(design)
    a = meta.ALL
    fields = ('status', 'model_id', 'year', 'model_sha256', 'reuse_tuple_sha256',
              'scientific_target_qualified', 'scientific_feature_pit_qualified',
              'train_label_maturity_max', 'calibration_label_maturity_max', 'model_path')
    fit_schema = {k: a for k in fields}
    # The reuse tuple is identity metadata, not fitted numeric calibration state.
    fit_schema['reuse_tuple'] = a
    pub_schema = {k: a for k in (
        'status', 'prediction_role', 'year', 'model_id', 'sha256', 'model_sha256',
        'reuse_tuple_sha256', 'producer_source_sha256', 'input_manifest_sha256',
        'fit_receipt_sha256', 'fit_receipt_path', 'path', 'test_2026_rows_read')}
    counts = Counter()
    for key, packet in packets.items():
        fusion = key.startswith('fusion::')
        model = key.split('::')[-1]
        producer_path = 'scripts/research/a2/training/stateful_fusion.py' if fusion else 'scripts/research/a2/training/stateful_values.py'
        producer = design['implementation_source_pins'][producer_path]['sha256']
        require(packet['source_kind'] == ('V24_FUSION_OUTPUTS' if fusion else 'V24_VALUE_OUTPUTS')
                and set(packet['annual']) == {'2023', '2024', '2025'},
                'BREADTH_PACKET_TYPE_OR_ANNUAL_GRID')
        for year, entry in packet['annual'].items():
            fit = _metadata(parent, entry['receipt'], fit_schema)
            pub = _metadata(parent, entry['prediction_receipt'], pub_schema)
            frozen = design['exact_fit_prediction_publication_dependency_refs'][key]['annual'][year]['fit_identity']
            tup = fit.get('reuse_tuple', {})
            require(fit.get('status') in ('TRAINED', 'EXACT_REUSED')
                    and fit.get('model_id') == model and fit.get('year') == int(year)
                    and fit.get('scientific_target_qualified') is True
                    and fit.get('scientific_feature_pit_qualified') is True,
                    'BREADTH_VALUE_TARGET_OR_PIT')
            require(_contains(tup, frozen.get('reuse_tuple'))
                    and fit.get('model_sha256') == frozen.get('model_sha256')
                    and fit.get('reuse_tuple_sha256') == frozen.get('reuse_tuple_sha256')
                    and values.digest(tup) == fit.get('reuse_tuple_sha256'),
                    'BREADTH_EXACT_FIT_IDENTITY_CHANGED')
            cutoff = year+'-01-01'
            require(tup.get('label_definition') == values.LABEL
                    and tup.get('fold') == 'ANNUAL_'+year
                    and tup.get('source_pins', {}).get('module_sha256') == producer
                    and tup.get('source_pins', {}).get('input_manifest_sha256') == manifest_sha
                    and tup.get('feature_binding', {}).get('features') == values.feature_binding()['features']
                    and str(tup.get('cutoff_exclusive', ''))[:10] == cutoff
                    and str(tup.get('calibration_label_maturity_exclusive', ''))[:10] == cutoff
                    and len(tup.get('calibration_sessions', [])) == 60
                    and bool(fit.get('train_label_maturity_max'))
                    and str(fit['train_label_maturity_max']) < str(tup.get('training_signal_and_label_maturity_exclusive', ''))
                    and bool(fit.get('calibration_label_maturity_max'))
                    and str(fit['calibration_label_maturity_max'])[:10] < cutoff,
                    'BREADTH_TARGET_FEATURE_OR_CLOCK_CHANGED')
            expected = dict(status='PUBLISHED',
                            model_id=model, year=int(year),
                            producer_source_sha256=producer,
                            input_manifest_sha256=manifest_sha,
                            fit_receipt_sha256=entry['receipt']['sha256'],
                            model_sha256=fit['model_sha256'],
                            reuse_tuple_sha256=fit['reuse_tuple_sha256'],
                            sha256=entry['prediction']['sha256'], test_2026_rows_read=0)
            if fusion:
                expected['prediction_role'] = 'MODEL_OOF'
            require(all(pub.get(k) == v for k, v in expected.items())
                    and Path(pub.get('path', '')).resolve() == Path(entry['prediction']['path']).resolve()
                    and Path(pub.get('fit_receipt_path', '')).resolve() == Path(entry['receipt']['path']).resolve(),
                    'BREADTH_PUBLICATION_CLOSURE')
            if fusion:
                experts = tup.get('packet', [])
                state = ['state_mean_ret20d', 'state_mean_realized_vol20d',
                         'state_breadth_price_vs_ma20_positive', 'state_expert_disagreement'] if model.startswith('gate_') else []
                grid = {(int(e.get('year', 0)), e.get('model_id')) for e in tup.get('expert_oof_pins', [])}
                require(tup.get('feature_binding_role') == 'UNDERLYING_SOURCE32_NOT_FUSION_ESTIMATOR_INPUTS'
                        and len(experts) == 3 and set(experts) == {'ridge', 'hgb', 'lgb'}
                        and tup.get('model_input_columns') == ['expert_'+m for m in experts]+state
                        and grid == {(y, m) for y in range(2021, int(year)) for m in ('ridge', 'hgb', 'lgb')}
                        and len(tup.get('expert_oof_pins', [])) == len(grid),
                        'BREADTH_FUSION_INPUT_OR_PAST_EXPERT_GRID')
            counts['fusion_years' if fusion else 'value_years'] += 1
    risk_schema = {k: a for k in ('status', 'year', 'method_id', 'model_sha256',
                                  'scientific_feature_pit_qualified',
                                  'scientific_return_proxy_qualified', 'reuse_tuple_sha256')}
    for method, packet in risks.items():
        require(set(packet['annual']) == {'2023', '2024', '2025'}, 'BREADTH_RISK_ANNUAL_GRID')
        for year, entry in packet['annual'].items():
            r = _metadata(parent, entry['receipt'], risk_schema)
            frozen = design['exact_risk_dependency_refs'][method]['annual'][year]['receipt_metadata']
            require(r.get('status') == 'FITTED' and r.get('year') == int(year)
                    and r.get('method_id') == method
                    and r.get('scientific_feature_pit_qualified') is True
                    and r.get('scientific_return_proxy_qualified') is True
                    and r.get('model_sha256') == entry['bundle']['sha256']
                    and all(r.get(k) == frozen.get(k) for k in risk_schema),
                    'BREADTH_EXACT_RISK_IDENTITY_CHANGED')
            counts['risk_years'] += 1
    return dict(status='PASS_PRODUCER_METADATA_ONLY', **counts,
                model_parquet_read_or_hash=False, new_fit=0)


def source_fingerprint(control):
    return values.digest({
        'source_decision': control.auth['source_decision'],
        'source_account_binding': control.auth['source_account_binding'],
        'parent_input_manifest_sha256': control.auth['parent_input_manifest_sha256'],
        'shared_replay_sha256': control.auth['source_pins']['replay_module_sha256'],
        'controller_sha256': control.auth['module_sha256']})


def validate_handoff_state(state, gate, candidates, history):
    """No economic outcomes, and no extra prerequisite on Raw -> original37."""
    require(state.get('status') == 'COMPLETED', 'BREADTH_PARENT_R5_NOT_COMPLETE')
    require(set(gate.get('groups', {})) == set(GATES)
            and all(gate['groups'].get(k) is True for k in GATES)
            and gate.get('all_passed') is True, 'BREADTH_REQUIRED_RAW_SEVEN_LITERAL_TRUE')
    declared = [(c['candidate_id'], c['scientific_tuple_sha256']) for c in candidates]
    starts = [(e.get('candidate_id'), e.get('scientific_tuple_sha256')) for e in history
              if e.get('event') == 'ACCOUNT_PATH_ATTEMPT_STARTED']
    ends = [(e.get('candidate_id'), e.get('scientific_tuple_sha256')) for e in history
            if e.get('event') in ('ACCOUNT_PATH_COMPLETE', 'ACCOUNT_PATH_FAILED')]
    require(len(declared) == 38 and declared[0][0] == 'RAW_s10'
            and starts == declared and len(ends) == 38
            and len(set(ends)) == 38 and set(ends) == set(declared),
            'BREADTH_PARENT_EXACT38_TERMINALS_REQUIRED')
    require(not execution.outstanding(history, account=True), 'BREADTH_PARENT_OUTSTANDING')
    return True


def _owned_handoff(control):
    require(isinstance(control, execution.Controller), 'BREADTH_REQUIRES_EXISTING_CONTROLLER')
    control.guard()
    persisted = execution._continuation_metadata(control.run, control.run/'EXECUTION_STATUS.json', {'status': meta.ALL})
    require(persisted.get('status') == 'COMPLETED', 'BREADTH_PARENT_PERSISTED_STATUS_NOT_COMPLETE')
    require(control.auth.get('namespace') == execution.R5_NAMESPACE,
            'BREADTH_PARENT_NAMESPACE')
    execution.r5_source_decision(control.auth)
    gate = execution.r5_baseline_gate(control.run, control.auth)
    history = execution._continuation_events(control.run, 'ACCOUNT_PATH_LOG.jsonl')
    validate_handoff_state(control.state, gate, control.candidates, history)
    return source_fingerprint(control)


def attempt_budget(candidates, history):
    require(all(e.get('event') in ('ACCOUNT_PATH_ATTEMPT_STARTED', 'ACCOUNT_PATH_COMPLETE',
                                   'ACCOUNT_PATH_FAILED', 'ACCOUNT_EXACT_REUSED') for e in history),
            'BREADTH_UNAUTHORIZED_FIT_OR_EVENT')
    ids = {c['candidate_id']: c['scientific_tuple_sha256'] for c in candidates}
    starts = [e for e in history if e.get('event') == 'ACCOUNT_PATH_ATTEMPT_STARTED']
    ends = [e for e in history if e.get('event') in ('ACCOUNT_PATH_COMPLETE', 'ACCOUNT_PATH_FAILED')]
    reused = [e for e in history if e.get('event') == 'ACCOUNT_EXACT_REUSED']
    require(len(starts) <= 19 and len({e.get('candidate_id') for e in starts}) == len(starts)
            and len({e.get('scientific_tuple_sha256') for e in starts}) == len(starts),
            'BREADTH_ATTEMPT_LIMIT_OR_DUPLICATE')
    require(len({e.get('candidate_id') for e in ends}) == len(ends)
            and len({e.get('candidate_id') for e in reused}) == len(reused)
            and not {e.get('candidate_id') for e in starts}.intersection(e.get('candidate_id') for e in reused),
            'BREADTH_TERMINAL_OR_REUSE_DUPLICATE')
    require(all(e.get('candidate_id') in ids and e.get('scientific_tuple_sha256') == ids[e['candidate_id']]
                for e in starts+ends+reused)
            and {e.get('candidate_id') for e in ends}.issubset(e.get('candidate_id') for e in starts),
            'BREADTH_LOG_IDENTITY_OR_UNSTARTED_TERMINAL')
    ordered = [e['candidate_id'] for e in history
               if e.get('event') in ('ACCOUNT_PATH_ATTEMPT_STARTED', 'ACCOUNT_EXACT_REUSED')]
    require(ordered == [c['candidate_id'] for c in candidates][:len(ordered)],
            'BREADTH_FROZEN_ORDER_CHANGED')
    return dict(new_account_attempts=len(starts), failed_attempts=sum(e.get('event') == 'ACCOUNT_PATH_FAILED' for e in ends),
                exact_reused=len(reused), outstanding=len(starts)-len(ends),
                finished_slots=len(ends)+len(reused), new_fit=0)


def exact_reuse_qualified(evidence, candidate, fingerprint):
    return (isinstance(evidence, dict)
            and evidence.get('candidate_id') == candidate['candidate_id']
            and evidence.get('scientific_tuple_sha256') == candidate['scientific_tuple_sha256']
            and evidence.get('source_account_fingerprint') == fingerprint
            and evidence.get('execution_friction') == candidate['execution_friction']
            and evidence.get('candidate') == candidate
            and set(evidence.get('groups', {})) == set(GATES)
            and all(evidence['groups'].get(k) is True for k in GATES))


def completion(candidates, history, baseline_passed=True):
    budget = attempt_budget(candidates, history)
    states = {c['candidate_id']: 'NOT_EXECUTED' for c in candidates}
    for e in history:
        if e.get('event') == 'ACCOUNT_PATH_COMPLETE':
            states[e['candidate_id']] = 'COMPLETE_NOT_AUTOMATIC_QUALIFICATION'
        elif e.get('event') == 'ACCOUNT_PATH_FAILED':
            states[e['candidate_id']] = 'FAILED_ATTEMPT_RETAINED'
        elif e.get('event') == 'ACCOUNT_EXACT_REUSED':
            states[e['candidate_id']] = 'EXACT_REUSED_QUALIFIED_ACCOUNT'
    if baseline_passed is not True:
        require(not history, 'BREADTH_EXECUTED_WITHOUT_REQUIRED_BASELINE')
        states = dict.fromkeys(states, 'NOT_EXECUTED_REQUIRED_BASELINE_UNQUALIFIED')
    finished = budget['outstanding'] == 0 and budget['finished_slots'] == 19
    return dict(status='PENDING_UNIFIED_ECONOMIC_EVALUATION' if finished else 'NOT_TESTABLE' if baseline_passed is not True else 'IN_PROGRESS',
                finite_execution_complete=finished, budget=budget, candidate_states=states,
                economic_values_read=0, winner_selected=False, new_fit=0, test_2026_rows_read=0)


def _canonical_admission(design, declaration):
    from scripts.maintenance import research_registry
    root, _ = research_registry._load_config(None, None)
    live = research_registry.verify_a_breadth_admission(
        root, design_sha256=DESIGN_SHA,
        execution_source_pins={'breadth_adapter': values.sha(Path(__file__)),
                               'stateful_execution': PROTECTED['scripts/research/a2/training/stateful_execution.py'],
                               'stateful_completion': PROTECTED['scripts/research/a2/training/stateful_completion.py']})
    require(isinstance(declaration, dict) and declaration == live,
            'BREADTH_CANONICAL_METADATA_ADMISSION_CHANGED')
    return live


def validated_history(run, candidates, fingerprint, *, control=None, design=None):
    fit = execution._continuation_events(run, 'FIT_LOG.jsonl')
    require(not fit,
            'BREADTH_ZERO_FIT_VIOLATION')
    history = execution._continuation_events(run, 'ACCOUNT_PATH_LOG.jsonl')
    for e in history:
        require(e.get('namespace') == NAMESPACE
                and e.get('module_sha256') == values.sha(Path(__file__))
                and e.get('controller_module_sha256') == PROTECTED['scripts/research/a2/training/stateful_execution.py'],
                'BREADTH_EVENT_PRODUCER_OR_NAMESPACE_CHANGED')
        if e.get('event') == 'ACCOUNT_PATH_ATTEMPT_STARTED':
            require(type(e.get('path_units')) is int and e['path_units'] == 1,
                    'BREADTH_EVENT_ATTEMPT_UNIT')
        elif e.get('event') in ('ACCOUNT_PATH_COMPLETE', 'ACCOUNT_PATH_FAILED'):
            audit = _metadata(run, {'path': e.get('audit_path'), 'sha256': e.get('audit_sha256')},
                              {k: meta.ALL for k in ('status', 'candidate_id', 'scientific_tuple_sha256',
                                'source_account_fingerprint', 'fit_units', 'test_2026_rows_read',
                                'execution_friction', 'annual_reset')})
            require(audit.get('candidate_id') == e.get('candidate_id')
                    and audit.get('scientific_tuple_sha256') == e.get('scientific_tuple_sha256')
                    and audit.get('fit_units') == 0 and audit.get('test_2026_rows_read') == 0,
                    'BREADTH_TERMINAL_AUDIT_IDENTITY')
            if e['event'] == 'ACCOUNT_PATH_COMPLETE':
                candidate = next((c for c in candidates if c['candidate_id'] == e['candidate_id']), {})
                require(audit.get('status') == 'ACTUAL_CONTINUOUS_PRE2026_REPLAY_COMPLETE'
                        and audit.get('source_account_fingerprint') == fingerprint
                        and audit.get('execution_friction') == candidate.get('execution_friction')
                        and audit.get('annual_reset') is False, 'BREADTH_COMPLETE_AUDIT_NOT_BOUND')
        elif e.get('event') == 'ACCOUNT_EXACT_REUSED':
            _verify_reuse_event(run, e, candidates, fingerprint, control=control, design=design)
        else:
            raise Blocked('BREADTH_UNREGISTERED_EVENT')
    attempt_budget(candidates, history)
    return history


def _parent_reuse(control, design, candidate):
    """Only a same-bank, same-source, explicitly qualified parent account."""
    fingerprint = source_fingerprint(control)
    old = next((c for c in control.candidates if c.get('candidate_id') == candidate['candidate_id']
                and c.get('scientific_tuple_sha256') == candidate['scientific_tuple_sha256']), None)
    if old is None:
        return None
    fields = ('candidate_id', 'scientific_tuple_sha256', 'value_model', 'risk', 'action',
              'action_cost_mode', 'control', 'gross', 'forecast', 'target_role', 'execution_friction')
    if any(old.get(k, 'none' if k == 'forecast' else None) != candidate.get(k) for k in fields):
        return None
    packets, risks = packet_specs(design)
    key = candidate['value_model']; risk = candidate['risk']
    if control.auth['value_packets'].get(key) != packets[key]:
        return None
    if risk not in ('diag', 'diag20_reference') and control.auth['risk_packets'].get(risk) != risks[risk]:
        return None
    parent_events = execution._continuation_events(control.run, 'ACCOUNT_PATH_LOG.jsonl')
    complete = [e for e in parent_events if e.get('candidate_id') == candidate['candidate_id']
                and e.get('event') == 'ACCOUNT_PATH_COMPLETE']
    if len(complete) != 1:
        return None
    event = complete[0]
    ref = {'path': event.get('audit_path'), 'sha256': event.get('audit_sha256')}
    audit = _metadata(control.run, ref, {k: meta.ALL for k in (
        'candidate_ids', 'source_run', 'input_manifest_sha256', 'execution_friction')})
    # R5's legacy batch audit computes qualification_checks only for its first path.
    # Never project those first-path checks onto another member of the batch.
    if not audit.get('candidate_ids') or audit['candidate_ids'][0] != candidate['candidate_id']:
        return None
    if (audit.get('source_run') != control.config['parent_run_dir']
            or audit.get('input_manifest_sha256') != control.auth['input_manifest_sha256']
            or audit.get('execution_friction') != candidate['execution_friction']):
        return None
    gate = execution.r5_baseline_gate(control.run, control.auth, candidate['candidate_id'])
    if gate.get('all_passed') is not True or any(gate.get('groups', {}).get(k) is not True for k in GATES):
        return None
    return dict(candidate_id=candidate['candidate_id'],
                scientific_tuple_sha256=candidate['scientific_tuple_sha256'],
                source_account_fingerprint=fingerprint,
                execution_friction=candidate['execution_friction'],
                candidate=copy.deepcopy(candidate), groups=gate['groups'],
                parent_run=str(control.run), parent_audit_ref=ref,
                packet_identity_sha256=values.digest({'value': packets[key],
                    'risk': risks.get(risk, {'kind': risk})}),
                metadata_receipt_physically_verified=True)


def _verify_reuse_event(run, event, candidates, fingerprint, *, control=None, design=None):
    require(control is not None and design is not None, 'BREADTH_REUSE_REQUIRES_OWNED_PARENT')
    candidate = next((c for c in candidates if c['candidate_id'] == event.get('candidate_id')), None)
    require(candidate is not None, 'BREADTH_REUSE_UNKNOWN_CANDIDATE')
    proof_schema = {k: meta.ALL for k in ('candidate_id', 'scientific_tuple_sha256',
        'source_account_fingerprint', 'execution_friction', 'groups', 'parent_run',
        'parent_audit_ref', 'packet_identity_sha256', 'metadata_receipt_physically_verified')}
    proof_schema['candidate'] = {k: meta.ALL for k in candidate}
    proof = _metadata(run, {'path': event.get('audit_path'), 'sha256': event.get('audit_sha256')}, proof_schema)
    expected = _parent_reuse(control, design, candidate)
    require(expected is not None and proof == expected
            and exact_reuse_qualified(proof, candidate, fingerprint),
            'BREADTH_EXACT_REUSE_NOT_CERTIFIED')
    return proof


def _worker(candidate, control, design, folder):
    """Numerical worker: existing readers, transition interfaces and one engine."""
    from scripts.research.a2.training import stateful_replay as replay
    import numpy as np
    import pandas as pd

    source_run = Path(control.config['parent_run_dir']).resolve()
    reader = replay._read_parent_inputs_readonly(source_run)
    market, top, qualified, vol, stock, raw = replay.read_market(reader)
    packets, risks = packet_specs(design)
    auth = {**control.auth, **control.auth['source_pins'],
            'value_packets': packets, 'risk_packets': risks}
    auth['module_sha256'] = auth['replay_module_sha256']
    key = candidate['value_model']
    packet = replay.read_packet(packets[key], reader, market.dates, market.tickers, auth=auth)
    packet['mu'] = np.where(stock, packet['mu'], np.nan)
    if candidate['risk'] in ('diag', 'diag20_reference'):
        def risk_provider(di, selected, tickers, method):
            return np.diag(vol[di, selected]**2)
    else:
        risk_provider, _ = replay.read_risk_packets(auth, reader, [candidate], market.dates, vol, source_run)
    old = replay._old()
    account = old.config_adapter(replay._json(replay.PARENT/'R1_ACCOUNT_CONFIG.json'))
    events, known, unsupported, _ = old.frozen_events(replay._json(replay.PARENT/'INPUT_BINDING_R1.json'))
    market, unsupported, kwargs, binding = replay._bound_entitlement_inputs(auth, market, events, unsupported)
    result, frames = replay.execute_market(
        market, [candidate], {key: packet}, top, qualified, vol, account,
        stock_present=stock, raw_selector_present=raw, events=events,
        known_at=known, unsupported=unsupported, risk_provider=risk_provider,
        execution_friction=candidate['execution_friction'], **kwargs)
    expected = pd.MultiIndex.from_product([market.dates, [candidate['candidate_id']]], names=['date', 'path_id'])
    actual = pd.MultiIndex.from_frame(result.daily[['date', 'path_id']])
    require(len(market.dates) == 752 and all(d.year in (2023, 2024, 2025) for d in market.dates)
            and actual.equals(expected), 'BREADTH_FULL_WINDOW_PATH_GRID')
    records = {}
    for name, frame in frames.items():
        path = folder/(name+'.parquet'); assert_write_path(path, 'backtest')
        frame.to_parquet(path, index=False)
        records[name] = dict(path=str(path), sha256=values.sha(path), rows=len(frame))
    q = replay.qualification_checks(result, candidate['candidate_id'])
    return dict(status='ACTUAL_CONTINUOUS_PRE2026_REPLAY_COMPLETE',
                candidate_id=candidate['candidate_id'],
                scientific_tuple_sha256=candidate['scientific_tuple_sha256'],
                source_account_fingerprint=source_fingerprint(control),
                qualification_checks=q, source_binding=binding, artifacts=records,
                fit_units=0, test_2026_rows_read=0, annual_reset=False,
                execution_friction=candidate['execution_friction'],
                account_engine='EXISTING_STATEFUL_REPLAY_EXECUTE_MARKET')


def run_stage(control, run, identity, design_path, admission, *, execution_authority=None):
    """Future authorized handoff only. Preparing a template cannot call this."""
    require(isinstance(execution_authority, dict)
            and execution_authority.get('approved') is True
            and execution_authority.get('namespace') == NAMESPACE,
            'BREADTH_REAL_EXECUTION_NOT_AUTHORIZED')
    require(identity.get('status') == 'FROZEN_BOUND_EXECUTION_IDENTITY'
            and identity.get('source_activated') is True
            and identity.get('execution_authority') == execution_authority,
            'BREADTH_INACTIVE_TEMPLATE')
    design = read_design(design_path)
    protected_custody()
    require(identity.get('design_sha256') == DESIGN_SHA
            and identity.get('adapter_sha256') == values.sha(Path(__file__))
            and identity.get('max_new_account_paths') == 19
            and identity.get('new_fit_hard_limit') == 0
            and identity.get('2026_locked') is True,
            'BREADTH_EXECUTION_IDENTITY_CHANGED')
    expected_identity = identity_template(design)
    immutable = ('schema_id', 'namespace', 'design_sha256', 'specification_sha256',
                 'candidate_order', 'candidate_tuples', 'new_fit_hard_limit',
                 'max_new_account_paths', 'prior_fit_units', 'prior_account_paths_after_R5',
                 'max_cumulative_account_paths', 'bank_input_manifest_sha256',
                 '2026_locked', 'account_contract', 'controller_sha256', 'adapter_sha256')
    require(all(identity.get(k) == expected_identity[k] for k in immutable),
            'BREADTH_DECLARED_IDENTITY_DIFFERS_FROM_FROZEN_DESIGN')
    _canonical_admission(design, admission)
    fingerprint = _owned_handoff(control)
    require(identity.get('parent_R5_run') == str(control.run)
            and identity.get('parent_R5_source_account_fingerprint') == fingerprint
            and identity.get('source_slots') == control.auth['source_decision']['slots'],
            'BREADTH_PARENT_SOURCE_ACCOUNT_CHANGED')
    run = Path(run).resolve()
    require(run != control.run and not run.is_relative_to(control.run)
            and not control.run.is_relative_to(run), 'BREADTH_PATH_NOT_ISOLATED')
    assert_write_path(run/'ACCOUNT_PATH_LOG.jsonl', 'backtest')
    require(run.is_dir() and execution.read_json(run/'run_config.json').get('breadth_identity') == identity,
            'BREADTH_MANAGED_FROZEN_RUN_REQUIRED')
    config_sha = values.sha(run/'run_config.json')
    validate_dependencies(design)
    candidates = validate_design(design)
    from scripts.research.a2.training import stateful_replay as replay
    with execution.continuation_lock(control.run, control.auth['module_sha256'], execution.R5_NAMESPACE):
        require(_owned_handoff(control) == fingerprint, 'BREADTH_HANDOFF_CHANGED')
        history = validated_history(run, candidates, fingerprint, control=control, design=design)
        budget = attempt_budget(candidates, history)
        require(not budget['outstanding'], 'BREADTH_OUTSTANDING_NO_AUTORETRY')
        completed = {e['candidate_id'] for e in history if e.get('event') in (
            'ACCOUNT_PATH_COMPLETE', 'ACCOUNT_PATH_FAILED', 'ACCOUNT_EXACT_REUSED')}
        for candidate in candidates:
            if candidate['candidate_id'] in completed:
                continue
            require(values.sha(run/'run_config.json') == config_sha, 'BREADTH_RUN_CONFIG_CHANGED')
            require(_owned_handoff(control) == fingerprint, 'BREADTH_PARENT_IDENTITY_CHANGED')
            protected_custody()
            proof = _parent_reuse(control, design, candidate)
            if proof is not None:
                proof_path = run/'reused'/('%02d.json' % candidate['ordinal'])
                assert_write_path(proof_path, 'backtest')
                require(not proof_path.exists(), 'BREADTH_EXISTING_REUSE_PROOF_PRESERVED')
                write_json_atomic(proof_path, proof)
                replay._append(run/'ACCOUNT_PATH_LOG.jsonl', dict(
                    event='ACCOUNT_EXACT_REUSED', namespace=NAMESPACE,
                    candidate_id=candidate['candidate_id'],
                    scientific_tuple_sha256=candidate['scientific_tuple_sha256'],
                    controller_module_sha256=control.auth['module_sha256'],
                    module_sha256=values.sha(Path(__file__)),
                    audit_path=str(proof_path), audit_sha256=values.sha(proof_path)))
                history = validated_history(run, candidates, fingerprint, control=control, design=design)
                budget = attempt_budget(candidates, history)
                continue
            folder = run/'ledgers/stateful'/('attempt_%04d' % (budget['new_account_attempts']+1))
            assert_write_path(folder, 'backtest')
            require(not folder.exists(), 'BREADTH_EXISTING_ATTEMPT_PRESERVED')
            folder.mkdir(parents=True)
            event = dict(namespace=NAMESPACE, candidate_id=candidate['candidate_id'],
                         scientific_tuple_sha256=candidate['scientific_tuple_sha256'],
                         controller_module_sha256=control.auth['module_sha256'],
                         module_sha256=values.sha(Path(__file__)))
            replay._append(run/'ACCOUNT_PATH_LOG.jsonl',
                           dict(event, event='ACCOUNT_PATH_ATTEMPT_STARTED', path_units=1))
            try:
                audit = _worker(candidate, control, design, folder)
                write_json_atomic(folder/'audit.json', audit)
                terminal = dict(event, event='ACCOUNT_PATH_COMPLETE',
                                audit_path=str(folder/'audit.json'),
                                audit_sha256=values.sha(folder/'audit.json'))
            except Exception as exc:
                audit = dict(status='FAILED_ACCOUNT_ATTEMPT_RETAINED',
                             candidate_id=candidate['candidate_id'],
                             scientific_tuple_sha256=candidate['scientific_tuple_sha256'],
                             failure=dict(type=type(exc).__name__, message=str(exc).split(':', 1)[0]),
                             fit_units=0, test_2026_rows_read=0)
                write_json_atomic(folder/'audit.json', audit)
                terminal = dict(event, event='ACCOUNT_PATH_FAILED',
                                audit_path=str(folder/'audit.json'),
                                audit_sha256=values.sha(folder/'audit.json'))
            replay._append(run/'ACCOUNT_PATH_LOG.jsonl', terminal)
            require(values.sha(run/'run_config.json') == config_sha, 'BREADTH_RUN_CONFIG_CHANGED')
            require(_owned_handoff(control) == fingerprint, 'BREADTH_PARENT_IDENTITY_CHANGED')
            protected_custody()
            history = validated_history(run, candidates, fingerprint, control=control, design=design)
            budget = attempt_budget(candidates, history)
        report = completion(candidates, history)
        write_json_atomic(run/'BREADTH_COMPLETION.json', report)
        return report
