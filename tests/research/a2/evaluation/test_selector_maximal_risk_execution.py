"""C14 execution orchestration with fake owners only; no risk/label/science read."""
import copy
import hashlib
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import pytest
from scripts.research.a2.evaluation import selector_maximal_risk_execution as m


def empty_result(**extra):
    return dict(complete_candidates=[], failed_or_untestable={}, panels={}, native_pair_predictions={}, **extra)


@pytest.fixture
def start_data(monkeypatch):
    refs = {k: {'path': str(m.RUN / (k + '.json')), 'sha256': ('a' if k == 'current_audit' else 'b') * 64}
            for k in m.SOURCE_FIELDS}
    refs['requirement_matrix'] = dict(path=str(m.RUN / 'RISK_ROLE_REQUIREMENT_MATRIX.json'), sha256=m.MATRIX_SHA)
    config = dict(refs, research_id=m.ctl.ID, status='REVIEWED_C14_RISK_EXECUTION_INPUTS')
    values = {f'2024-{i:04d}': {'numeric_read_authority': False} for i in range(752)}
    bindings = dict(research_id=m.ctl.ID, numeric_read_authority=False, bindings=values)
    audit = dict(status='PASS_FULL752_CURRENT_U_UID_EPOCH_SEGMENT_SOURCE_METADATA', research_id=m.ctl.ID,
                 days_checked=752, exact_days=752, bindings_ref=refs['current_bindings'],
                 bindings_content_sha256=m.binding.content_hash(values),
                 helper_ref=dict(path=str(Path(m.current_owner.__file__).resolve()), sha256=m.binding.sha(m.current_owner.__file__)),
                 **{k: 0 for k in ('risk_numeric_reads', 'label_numeric_reads', 'economic_reads', 'fit', 'solve', 'bootstrap', 'test2026_rows_read')})
    matrix = {'roles': [], 'research_id': m.ctl.ID}
    bodies = {refs[k]['path']: v for k, v in [('requirement_matrix', matrix), ('current_audit', audit), ('current_bindings', bindings)]}
    monkeypatch.setattr(m, 'read_exact', lambda reference, **_: bodies[reference['path']])
    review = dict(metadata_inputs={k: refs[k] for k in ('requirement_matrix', 'current_audit', 'current_bindings')})
    return config, review, matrix, audit, bindings


def test_start_exact_full752_metadata_only(start_data):
    config, review, matrix, _, bindings = start_data
    observed_matrix, values = m.validate_start(config, review)
    assert observed_matrix is matrix and values is bindings['bindings'] and len(values) == 752


@pytest.mark.parametrize('mutation', ['config_key', 'identity', 'matrix_pin', 'review_input', 'audit_status', 'audit_identity',
                                     'days', 'exact_days', 'risk_numeric', 'label_numeric', 'economic', 'fit', 'solve',
                                     'bootstrap', '2026', 'bindings_ref', 'helper_ref', 'content', 'top_authority',
                                     'row_authority', 'short752'])
def test_start_rejects_bad_metadata_before_numeric_boundary(start_data, mutation):
    config, review, _, audit, bindings = start_data
    if mutation == 'config_key': config['unknown'] = True
    elif mutation == 'identity': config['research_id'] = 'C15'
    elif mutation == 'matrix_pin': config['requirement_matrix']['sha256'] = '0' * 64
    elif mutation == 'review_input': review['metadata_inputs']['current_audit'] = {'path': 'foreign', 'sha256': '0' * 64}
    elif mutation == 'audit_status': audit['status'] = 'PASS'
    elif mutation == 'audit_identity': audit['research_id'] = 'C13'
    elif mutation == 'days': audit['days_checked'] = 751
    elif mutation == 'exact_days': audit['exact_days'] = 751
    elif mutation in ('risk_numeric', 'label_numeric', 'economic', 'fit', 'solve', 'bootstrap', '2026'):
        audit[{'risk_numeric': 'risk_numeric_reads', 'label_numeric': 'label_numeric_reads', 'economic': 'economic_reads',
               '2026': 'test2026_rows_read'}.get(mutation, mutation)] = 1
    elif mutation == 'bindings_ref': audit['bindings_ref'] = {'path': 'foreign', 'sha256': '0' * 64}
    elif mutation == 'helper_ref': audit['helper_ref']['sha256'] = '0' * 64
    elif mutation == 'content': audit['bindings_content_sha256'] = '0' * 64
    elif mutation == 'top_authority': bindings['numeric_read_authority'] = True
    elif mutation == 'row_authority': next(iter(bindings['bindings'].values()))['numeric_read_authority'] = True
    elif mutation == 'short752': bindings['bindings'].pop(next(iter(bindings['bindings'])))
    with pytest.raises((ValueError, KeyError)):
        m.validate_start(config, review)


@pytest.fixture
def source_review(monkeypatch):
    modules = (m.ctl, *m.REQUIRED_NEW)
    pins = {str(Path(module.__file__).resolve()): m.binding.sha(module.__file__) for module in modules}
    pins[str(Path(m.__file__).resolve())] = m.binding.sha(m.__file__)
    review = dict(status='PASS', research_id=m.ctl.ID, adapter_sha256=m.binding.sha(m.binding.__file__),
                  source_pins=pins, scientific_contract_changed=False, scientific_retry=0, test2026_rows_read=0)
    monkeypatch.setattr(m, 'read_exact', lambda *_args, **_kwargs: review)
    return review


def test_execution_reviews_every_physical_source_before_dispatch(source_review):
    assert m.reviewed_sources({'path': 'synthetic', 'sha256': '0' * 64}) is source_review


@pytest.mark.parametrize('mutation', ['status', 'identity', 'adapter', 'missing_inputs', 'missing_driver', 'changed_owner', 'science', 'retry', '2026'])
def test_execution_review_rejects_unreviewed_sources(source_review, mutation):
    if mutation == 'status': source_review['status'] = 'WAITING'
    elif mutation == 'identity': source_review['research_id'] = 'C15'
    elif mutation == 'adapter': source_review['adapter_sha256'] = '0' * 64
    elif mutation == 'missing_inputs': source_review['source_pins'].pop(str(Path(m.input_owner.__file__).resolve()))
    elif mutation == 'missing_driver': source_review['source_pins'].pop(str(Path(m.__file__).resolve()))
    elif mutation == 'changed_owner': source_review['source_pins'][str(Path(m.ctl.__file__).resolve())] = '0' * 64
    elif mutation == 'science': source_review['scientific_contract_changed'] = True
    elif mutation == 'retry': source_review['scientific_retry'] = 1
    elif mutation == '2026': source_review['test2026_rows_read'] = 1
    with pytest.raises(ValueError): m.reviewed_sources({'path': 'synthetic', 'sha256': '0' * 64})


@pytest.fixture
def flow(tmp_path, monkeypatch):
    run = tmp_path / 'run'; run.mkdir()
    monkeypatch.setattr(m, 'RUN', run)
    # This fixture tests orchestration only; the real context is exercised below.
    monkeypatch.setattr(m, 'frozen_test_configuration', lambda _review: nullcontext())
    events, written = [], {}
    roles = list(m.hybrids.ROLES)
    states = {role: dict(phase='FULL752_NUMERIC_INPUT_QUALIFIED', role=role) for role in (*roles, 'C14_D01', 'C14_G1')}
    states['C14_D12'] = dict(phase='BLOCKED_BUDGET', reasons=['FROZEN'], role='C14_D12')
    qual = dict(roles=states)
    matrix = dict(roles=[{'role': r} for r in states], marker='EXACT_FROZEN_MATRIX')
    review_ref = dict(path=str(run / 'RISK_INPUT_SOURCE_REVIEW_R1.json'), sha256='a' * 64)
    cfg_ref = dict(path=str(run / 'EXECUTION_INPUTS.json'), sha256='b' * 64)
    old_ref = dict(path=str(run / 'ML_ASSEMBLY.json'), sha256='c' * 64)
    config = dict(source_review=review_ref)
    review = dict(immutable_inputs={'ML_ASSEMBLY.json': old_ref})
    old_ml = empty_result()
    cfg = {'synthetic': True}; design = {'research_id': m.ctl.ID}
    q = dict(artifacts={k: {'path': k, 'sha256': 'd' * 64} for k in ('raw_current', 'pair_geometry', 'current_pair_features')})
    geometry = pd.DataFrame({k: [pd.Timestamp('2024-01-02') if k == 'signal_date' else 'synthetic'] for k in m.ctl.PAIR_KEYS})
    if 'signal_date' not in geometry: geometry['signal_date'] = pd.Timestamp('2024-01-02')
    raw = pd.DataFrame({'signal_date': [pd.Timestamp('2024-01-02')]})
    features = geometry.copy(); features['synthetic_x'] = 1.0
    frames = {'raw_current': raw, 'pair_geometry': geometry, 'current_pair_features': features}
    def read(reference, **_):
        events.append(('read', reference['path']))
        if reference == cfg_ref: return config
        if reference == old_ref: return old_ml
        if Path(reference['path']).name == 'RISK_DECISIONS_TERMINAL_R1.json': return ns.done
        raise AssertionError('Unplanned fake read: ' + str(reference))
    monkeypatch.setattr(m, 'read_exact', read)
    def review_sources(reference):
        events.append(('review_sources', reference)); return review
    monkeypatch.setattr(m, 'reviewed_sources', review_sources)
    def validate(*_):
        events.append(('current_audit_full752',)); return matrix, {'synthetic': True}
    monkeypatch.setattr(m, 'validate_start', validate)
    monkeypatch.setattr(m.ctl, 'checked', lambda r: (events.append(('checked_frozen', r)) or (cfg, design, q)))
    monkeypatch.setattr(m.evidence, 'validate_design', lambda _: events.append(('design_validation',)))
    monkeypatch.setattr(m, 'assert_safe_output_path', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(m, 'resolve', lambda *_: None)
    def put(path, value):
        written[str(path)] = copy.deepcopy(value); events.append(('put', Path(path).name))
    monkeypatch.setattr(m, 'put', put)
    monkeypatch.setattr(m, 'ref', lambda p: {'path': str(p), 'sha256': 'e' * 64})
    monkeypatch.setattr(m, 'stage', lambda path, name, **_: events.append(('stage', name)))
    monkeypatch.setattr(m.binding, 'read_publication_metadata', lambda: (events.append(('publication_metadata',)) or {'publication': 'FAKE_PUB'}))
    monkeypatch.setattr(m.ctl, 'project', lambda *_args, **kwargs: (events.append(('label_free_raw_projection', kwargs['start'], kwargs['stop'])) or raw.copy()))
    class Inputs:
        def __init__(self, pub, received_matrix, current, received_raw, **kwargs):
            events.append(('inputs_constructor',))
            assert pub == 'FAKE_PUB' and received_matrix is matrix
            assert kwargs['source_review'] is review and kwargs['source_review_ref'] == review_ref
        def qualify(self): events.append(('qualify_full752',)); return qual
        def status(self): return qual
        def get_risk(self, role, day): raise AssertionError('No real numeric kernel in orchestration tests')
    monkeypatch.setattr(m.input_owner, 'RiskInputs', Inputs)
    class Journal:
        def __init__(self, received_run):
            assert str(run / 'risk_execution' / 'INPUT_QUALIFICATION_R1.json') in written
            events.append(('journal_constructed_after_qualification_saved',))
            self.run, self.path = run, run / 'delta.json'
            self.roles, self.slots, self.requests = [], {}, {}
            self.families = {*roles, 'C14_D01'}
            ns.journal = self
        def activate_role(self, role, gate_ref):
            assert written[gate_ref['path']]['phase'] == 'FULL752_NUMERIC_INPUT_QUALIFIED'
            events.append(('activate', role)); self.roles.append(role)
        def block_remaining(self, role, reason): events.append(('block_remaining', role, reason))
    monkeypatch.setattr(m.journal_owner, 'RiskJournal', Journal)
    def pin(reference): events.append(('pin', reference['path'])); return reference['path']
    monkeypatch.setattr(m.ctl, 'pin', pin)
    monkeypatch.setattr(m.ctl, 'footer', lambda reference: events.append(('footer', reference['path'])))
    monkeypatch.setattr(m.pq, 'read_table', lambda path: SimpleNamespace(to_pandas=lambda: frames[path].copy()))
    monkeypatch.setattr(m.ctl, 'feature_order', lambda: ['synthetic_x'])
    rt = [None] * 10; rt[5] = object(); rt[8] = SimpleNamespace(Fusion=object)
    def runtime_for(received_run, received_cfg):
        assert received_run == run and received_cfg is cfg
        events.append(('runtime_for',)); return tuple(rt)
    monkeypatch.setattr(m.ctl, 'runtime_for', runtime_for)
    def hybrid(received_run, received_design, received_q, received_raw, received_geometry, base_x, role,
               get_risk, received_journal, kernel, runtime):
        assert runtime is rt[5] and received_journal is ns.journal and role in ns.journal.roles
        assert base_x.shape == (1, 1)
        events.append(('hybrid', role))
        return empty_result()
    monkeypatch.setattr(m.hybrids, 'execute_hybrid', hybrid)
    def membership(received_run, received_design, received_q, received_raw, received_geometry, received_matrix,
                   get_risk, received_journal, received_review_ref, *, role_gates, qualification_ref):
        assert received_matrix is matrix and received_review_ref == review_ref
        assert role_gates is states and role_gates['C14_G1']['phase'] == 'FULL752_NUMERIC_INPUT_QUALIFIED'
        assert qualification_ref['path'] == str(run / 'risk_execution' / 'INPUT_QUALIFICATION_R1.json')
        events.append(('membership_fixed_roles',)); return empty_result()
    monkeypatch.setattr(m.membership, 'execute_membership', membership)
    def terminal(*args):
        events.append(('terminal',)); assert args[3] is old_ml
        return dict(status='RISK_DECISIONS_TERMINAL_JOINT_DELIVERY_PENDING', joint_delivery_completed=False,
                    coverage_sufficient_claim_allowed=False)
    monkeypatch.setattr(m, 'terminal', terminal)
    ns = SimpleNamespace(run=run, events=events, written=written, qual=qual, states=states, matrix=matrix,
                         config_ref=cfg_ref, review_ref=review_ref, rt=rt, frames=frames, roles=roles, done=None)
    return ns


def test_execution_qualifies_all_inputs_saves_gates_then_activates_fake_science(flow):
    result = m.execute(flow.run, flow.config_ref)
    names = [e[0] for e in flow.events]
    assert names.index('review_sources') < names.index('current_audit_full752') < names.index('qualify_full752')
    assert names.index('qualify_full752') < names.index('journal_constructed_after_qualification_saved') < names.index('activate')
    assert names.index('activate') < names.index('runtime_for') < names.index('hybrid') < names.index('membership_fixed_roles') < names.index('terminal')
    assert [e[1] for e in flow.events if e[0] == 'activate'] == [*flow.roles, 'C14_D01']
    assert 'C14_G1' not in flow.journal.roles and 'C14_D12' not in flow.journal.roles
    assert result['joint_delivery_completed'] is False and result['coverage_sufficient_claim_allowed'] is False
    assert all('/risk_execution/' in p.replace('\\', '/') for p in flow.written)
    assert not any(Path(p).name in ('ML_ASSEMBLY.json', 'FINAL_PIPELINES_FREEZE.json', 'FIT_LEDGER.json') for p in flow.written)
    assert ('label_free_raw_projection', '2023-01-01', '2026-01-01') in flow.events


def test_no_qualified_hybrid_never_constructs_runtime_or_reads_features(flow):
    for role in flow.roles: flow.states[role]['phase'] = 'PARTIAL_INPUT_BLOCKED'
    m.execute(flow.run, flow.config_ref)
    assert not any(e[0] in ('runtime_for', 'hybrid') for e in flow.events)
    assert not any(e == ('pin', 'current_pair_features') for e in flow.events)
    assert flow.journal.roles == ['C14_D01']


@pytest.mark.parametrize('before', ['review', 'current_audit', 'qualify'])
def test_early_guard_failure_has_no_reservation_dispatch(flow, monkeypatch, before):
    def failure(*_args, **_kwargs): raise ValueError('SYNTHETIC_' + before)
    if before == 'review': monkeypatch.setattr(m, 'reviewed_sources', failure)
    elif before == 'current_audit': monkeypatch.setattr(m, 'validate_start', failure)
    else: monkeypatch.setattr(m.input_owner.RiskInputs, 'qualify', failure)
    with pytest.raises(ValueError): m.execute(flow.run, flow.config_ref)
    assert not any(e[0] in ('activate', 'hybrid', 'membership_fixed_roles') for e in flow.events)
    assert not hasattr(flow, 'journal')


def test_started_engineering_marker_prevents_duplicate_worker(flow):
    root = flow.run / 'risk_execution'; root.mkdir(); (root / 'EXECUTION_STARTED_R1.json').write_text('{}')
    with pytest.raises(ValueError, match='NO_DUPLICATE_WORKER'): m.execute(flow.run, flow.config_ref)
    assert not any(e[0] in ('publication_metadata', 'qualify_full752', 'activate') for e in flow.events)


@pytest.mark.parametrize('mutation', ['identity', 'status', 'review', 'joint', 'coverage'])
def test_done_marker_requires_exact_identity_and_pending_claims(flow, mutation):
    root = flow.run / 'risk_execution'; root.mkdir(); (root / 'RISK_DECISIONS_TERMINAL_R1.json').write_text('{}')
    flow.done = dict(research_id=m.ctl.ID, status='RISK_DECISIONS_TERMINAL_JOINT_DELIVERY_PENDING', review_ref=flow.review_ref,
                     joint_delivery_completed=False, coverage_sufficient_claim_allowed=False,
                     **{k: dict(path=k, sha256='f' * 64) for k in ('assembly', 'final_pipeline', 'delta', 'input_qualification')})
    flow.done[{'identity': 'research_id', 'status': 'status', 'review': 'review_ref', 'joint': 'joint_delivery_completed',
               'coverage': 'coverage_sufficient_claim_allowed'}[mutation]] = True
    with pytest.raises(ValueError, match='EXACT_TERMINAL_CONTINUATION_RECEIPT_REQUIRED'): m.execute(flow.run, flow.config_ref)
    assert not any(e[0] in ('publication_metadata', 'qualify_full752', 'activate') for e in flow.events)


def test_exact_done_marker_is_physical_ref_reuse_only(flow):
    root = flow.run / 'risk_execution'; root.mkdir(); (root / 'RISK_DECISIONS_TERMINAL_R1.json').write_text('{}')
    flow.done = dict(research_id=m.ctl.ID, status='RISK_DECISIONS_TERMINAL_JOINT_DELIVERY_PENDING', review_ref=flow.review_ref,
                     joint_delivery_completed=False, coverage_sufficient_claim_allowed=False,
                     **{k: dict(path=k, sha256='f' * 64) for k in ('assembly', 'final_pipeline', 'delta', 'input_qualification')})
    assert m.execute(flow.run, flow.config_ref) is flow.done
    assert [e[1] for e in flow.events if e[0] == 'pin'] == ['assembly', 'final_pipeline', 'delta', 'input_qualification']
    assert not any(e[0] in ('publication_metadata', 'qualify_full752', 'activate') for e in flow.events)


@pytest.mark.parametrize('started', [False, True])
def test_unexpected_rx_exception_continues_independent_role_without_fake_finish(flow, monkeypatch, started):
    calls = []
    def fail_first(*args):
        role, journal = args[6], args[8]
        calls.append(role)
        if role == flow.roles[0]:
            if started: journal.slots['scientific-node'] = dict(candidate_id=role, status='STARTED')
            raise RuntimeError('SYNTHETIC_RX_FAILURE')
        return empty_result()
    monkeypatch.setattr(m.hybrids, 'execute_hybrid', fail_first)
    m.execute(flow.run, flow.config_ref)
    assert calls == flow.roles and ('membership_fixed_roles',) in flow.events
    assert any(Path(p).name == 'ENGINEERING_FAILURE_R1.json' for p in flow.written)
    blocked = [e for e in flow.events if e[0] == 'block_remaining']
    assert bool(blocked) is (not started)
    if started: assert flow.journal.slots['scientific-node']['status'] == 'STARTED'


def test_feature_order_or_future_rows_fail_before_hybrid(flow, monkeypatch):
    flow.frames['current_pair_features'].loc[0, m.ctl.PAIR_KEYS[-1]] = 'foreign'
    with pytest.raises(ValueError, match='EXACT_PAIR_FEATURE_ORDER_REQUIRED'): m.execute(flow.run, flow.config_ref)
    assert not any(e[0] in ('runtime_for', 'hybrid') for e in flow.events)


def test_runtime_parts_requires_native_ten_item_calibration_owner():
    with pytest.raises(ValueError, match='SHARED_RUNTIME_TUPLE'): m.ctl.runtime_parts((None,) * 9)
    with pytest.raises(ValueError, match='SHARED_RUNTIME_TUPLE'): m.ctl.runtime_parts((None,) * 10)
    rt = [None] * 10; rt[5] = object(); rt[8] = SimpleNamespace(Fusion=object)
    assert m.ctl.runtime_parts(tuple(rt)) == (rt[5], rt[8])


@pytest.fixture
def finish(tmp_path, monkeypatch):
    run = tmp_path / 'run'; run.mkdir()
    written = {}
    monkeypatch.setattr(m, 'put', lambda p, v: written.__setitem__(Path(p).name, copy.deepcopy(v)))
    monkeypatch.setattr(m, 'ref', lambda p: dict(path=str(p), sha256='a' * 64))
    monkeypatch.setattr(m.binding, 'sha', lambda _: 'a' * 64)
    monkeypatch.setattr(m.evidence, 'validate_final_pipeline_gate', lambda *_: True)
    old = dict(status='SCORE_ASSEMBLY_COMPLETE', complete_candidates=['C14_P01'], failed_or_untestable={},
               panels={'C14_P01': {'path': 'OLD_IMMUTABLE_PANEL'}}, native_pair_predictions={'C14_P01': {'path': 'OLD_IMMUTABLE_NATIVE'}})
    roles = ['C14_P01', *dict.fromkeys([*m.hybrids.ROLES, *m.membership.ROLES]), 'C14_D12', 'C14_TEST_CONTRAST']
    design = dict(roles=roles, blocked_roles={'C14_D12': 'BLOCKED_BUDGET:ORIGINAL'},
                  contrasts=[dict(candidate_id='C14_TEST_CONTRAST', left='C14_P01', right='C14_D01')])
    qualification = dict(roles={r: dict(phase='FULL752_NUMERIC_INPUT_QUALIFIED', reasons=[]) for r in ('C14_D01', 'C14_RX_HGB_LW', 'C14_G1')})
    qualification['roles']['C14_D12'] = dict(phase='BLOCKED_BUDGET', reasons=['ORIGINAL'])
    journal = SimpleNamespace(path=run / 'delta.json', slots={}, requests={})
    return SimpleNamespace(run=run, written=written, old=old, design=design, qualification=qualification, journal=journal,
                           q={'pair_key_sha256': 'b' * 64}, review_ref={'path': 'synthetic', 'sha256': 'c' * 64})


def test_terminal_exact_enum_contrast_budget_no_old_ml_write_or_complete_claim(finish):
    before = copy.deepcopy(finish.old)
    result = empty_result(); result['complete_candidates'] = ['C14_D01', 'C14_D02']; result['panels'] = {'C14_D01': {'path': 'NEW'}, 'C14_D02': {'path': 'RAW'}}
    summary = m.terminal(finish.run, finish.design, finish.q, finish.old, finish.qualification, [result], finish.journal, finish.review_ref)
    assert finish.old == before
    assembly = finish.written['SCORE_ASSEMBLY_R1.json']
    assert assembly['panels']['C14_P01'] == before['panels']['C14_P01']
    assert assembly['native_pair_predictions']['C14_P01'] == before['native_pair_predictions']['C14_P01']
    assert assembly['role_statuses']['C14_D12'] == 'BLOCKED_BUDGET'
    assert assembly['role_statuses']['C14_TEST_CONTRAST'] == 'COMPLETE'
    assert set(assembly['role_statuses'].values()) <= m.TERMINAL
    assert set(finish.written) == {'FIT_STATUS_SNAPSHOT_R1.json', 'SCORE_ASSEMBLY_R1.json', 'FINAL_PIPELINES_FREEZE_R1.json', 'RISK_DECISIONS_TERMINAL_R1.json'}
    assert summary['joint_delivery_completed'] is False and summary['coverage_sufficient_claim_allowed'] is False
    assert summary['combined_charged_solves'] == 18006


@pytest.mark.parametrize('status', ['STARTED', 'RESERVED'])
def test_terminal_rejects_unresolved_scientific_node_without_writing(finish, status):
    finish.journal.slots['node'] = {'status': status}
    with pytest.raises(ValueError, match='NO_UNRESOLVED_CONDITIONAL_TRAINING'):
        m.terminal(finish.run, finish.design, finish.q, finish.old, finish.qualification, [], finish.journal, finish.review_ref)
    assert finish.written == {} and finish.journal.slots['node']['status'] == status


@pytest.mark.parametrize('mutation', ['foreign_role', 'old_panel', 'old_native', 'unqualified_complete', 'foreign_failed', 'foreign_roles', 'foreign_predicted', 'foreign_variance', 'artifact_without_complete', 'duplicate_complete', 'missing_panel', 'complete_and_failed'])
def test_terminal_rejects_outside_conditional_role_outputs_or_old_ml_overwrite(finish, mutation):
    result = empty_result()
    if mutation == 'foreign_role': result['complete_candidates'] = ['C15_FAKE_NEW_ROLE']
    elif mutation == 'old_panel': result['panels']['C14_P01'] = {'path': 'FORGED_REPLACEMENT'}
    elif mutation == 'old_native': result['native_pair_predictions']['C14_P01'] = {'path': 'FORGED_REPLACEMENT'}
    elif mutation == 'unqualified_complete': result['complete_candidates'] = ['C14_G1']; result['panels']['C14_G1'] = {'path': 'NEW'}; finish.qualification['roles']['C14_G1']['phase'] = 'PARTIAL_INPUT_BLOCKED'
    elif mutation == 'foreign_failed': result['failed_or_untestable']['C15_FAKE_NEW_ROLE'] = 'FORGED'
    elif mutation in ('foreign_roles', 'foreign_predicted', 'foreign_variance'):
        result[{'foreign_roles': 'roles', 'foreign_predicted': 'predicted_risk', 'foreign_variance': 'variance_diagnostics'}[mutation]] = {'C15_FAKE_NEW_ROLE': {}}
    elif mutation == 'artifact_without_complete': result['panels']['C14_D01'] = {'path': 'NEW'}
    elif mutation == 'duplicate_complete': result['complete_candidates'] = ['C14_D01', 'C14_D01']
    elif mutation == 'missing_panel': result['complete_candidates'] = ['C14_D01']
    elif mutation == 'complete_and_failed': result['complete_candidates'] = ['C14_D01']; result['panels']['C14_D01'] = {'path': 'NEW'}; result['failed_or_untestable']['C14_D01'] = 'FAILED'
    with pytest.raises(ValueError):
        m.terminal(finish.run, finish.design, finish.q, finish.old, finish.qualification, [result], finish.journal, finish.review_ref)
    assert finish.written == {}

@pytest.mark.parametrize('matched', [True, False])
def test_fixed_contrast_is_endpoint_only_no_fake_panel_fit_or_solve(finish, matched):
    result = empty_result()
    if matched:
        result['complete_candidates'] = ['C14_D01']
        result['panels'] = {'C14_D01': {'path': 'NEW_OWNER_PANEL'}}
    else:
        result['failed_or_untestable'] = {'C14_D01': 'FAILED_UNTESTABLE:SYNTHETIC_INPUT'}
    summary = m.terminal(finish.run, finish.design, finish.q, finish.old, finish.qualification,
                         [result], finish.journal, finish.review_ref)
    assembly = finish.written['SCORE_ASSEMBLY_R1.json']
    contrast = 'C14_TEST_CONTRAST'
    assert (contrast in assembly['complete_candidates']) is matched
    assert (assembly['role_statuses'][contrast] == 'COMPLETE') is matched
    assert summary['complete_conditional_roles'] == (['C14_D01'] if matched else [])
    assert summary['complete_fixed_contrasts'] == ([contrast] if matched else [])
    assert contrast not in assembly['panels'] and contrast not in assembly['native_pair_predictions']
    assert summary['reserved_fit_slots'] == summary['backend_entered'] == summary['charged_solves'] == 0
    assert summary['combined_charged_solves'] == 18006
    assert finish.journal.slots == {} and finish.journal.requests == {}
    assert summary['joint_delivery_completed'] is False and summary['coverage_sufficient_claim_allowed'] is False

@pytest.mark.parametrize('artifact', ['raw_current', 'pair_geometry', 'current_pair_features'])
def test_pre_read_footer_rejects_before_disallowed_numeric_materialization(flow, monkeypatch, artifact):
    materialized = []
    def footer(reference):
        flow.events.append(('footer', reference['path']))
        if reference['path'] == artifact: raise ValueError('SYNTHETIC_PRE2026_FOOTER_BLOCK')
    def materialize(path):
        materialized.append(path)
        return SimpleNamespace(to_pandas=lambda: flow.frames[path].copy())
    monkeypatch.setattr(m.ctl, 'footer', footer)
    monkeypatch.setattr(m.pq, 'read_table', materialize)
    with pytest.raises(ValueError, match='SYNTHETIC_PRE2026_FOOTER_BLOCK'):
        m.execute(flow.run, flow.config_ref)
    assert artifact not in materialized
    assert not any(e[0] in ('runtime_for', 'hybrid', 'membership_fixed_roles') for e in flow.events)
    for name in materialized:
        assert ('footer', name) in flow.events

@pytest.fixture
def frozen_configuration(tmp_path, monkeypatch):
    """Physical files are tiny synthetic configs/code, never research inputs."""
    repo = (tmp_path / 'synthetic_repo').resolve(); repo.mkdir()
    run = (tmp_path / 'synthetic_run').resolve(); run.mkdir()
    (run / 'source_snapshot').mkdir()
    live = repo / 'pytest.ini'
    snapshot = run / 'source_snapshot' / 'pytest.ini'
    live.write_text('[pytest]\naddopts = synthetic-current\n', encoding='utf-8')
    snapshot.write_text('[pytest]\naddopts = synthetic-original\n', encoding='utf-8')
    code = [repo / 'controller.py', repo / 'estimator.py', repo / 'evidence.py']
    for index, path in enumerate(code):
        path.write_text('SYNTHETIC_VALUE = ' + str(index) + '\n', encoding='utf-8')
    monkeypatch.setattr(m, 'RUN', run)
    monkeypatch.setattr(m.ctl, 'REPO', repo)
    monkeypatch.setattr(m.ctl, 'CACHE', {})
    review = dict(nonexecuting_test_configuration=dict(
        classification='EXACT_ORIGINAL_NONEXECUTING_PYTEST_CONFIGURATION',
        live=dict(path=str(live), sha256=m.binding.sha(live)),
        original_snapshot=dict(path=str(snapshot), sha256=m.binding.sha(snapshot)),
        executed=False))
    sources = {str(live): m.binding.sha(snapshot), **{str(path): m.binding.sha(path) for path in code}}
    design = dict(research_id=m.ctl.ID, sources=sources,
                  frozen_science=dict(seed=20260928, cutoff='2026-01-01', strict_PIT_promotion_eligible=False))
    owner_guard, owner_pin = m.ctl.checked_sources, m.ctl.pin
    calls, pins = [], []
    def guard(received_run, received_design):
        calls.append((received_run, copy.deepcopy(received_design)))
        return owner_guard(received_run, received_design)
    def pin(reference):
        pins.append(copy.deepcopy(reference))
        return owner_pin(reference)
    monkeypatch.setattr(m.ctl, 'checked_sources', guard)
    monkeypatch.setattr(m.ctl, 'pin', pin)
    return SimpleNamespace(repo=repo, run=run, live=live, snapshot=snapshot, code=code,
                           review=review, design=design, guard=guard, calls=calls, pins=pins)


def test_frozen_configuration_maps_only_original_pytest_and_calls_every_owner_pin(frozen_configuration):
    f = frozen_configuration
    before_review, before_design = copy.deepcopy(f.review), copy.deepcopy(f.design)
    with m.frozen_test_configuration(f.review):
        assert m.ctl.checked_sources is not f.guard
        first = m.ctl.checked_sources(f.run, f.design)
        second = m.ctl.checked_sources(f.run, f.design)
        assert first == second
    assert m.ctl.checked_sources is f.guard
    assert f.review == before_review and f.design == before_design
    mapped = {str(f.snapshot): f.design['sources'][str(f.live)],
              **{str(path): f.design['sources'][str(path)] for path in f.code}}
    assert first == mapped and len(first) == len(f.design['sources'])
    assert len(f.calls) == 2
    for received_run, received_design in f.calls:
        assert received_run == f.run
        assert received_design == dict(before_design, sources=mapped)
    assert f.pins == [dict(path=path, sha256=digest) for path, digest in f.calls[0][1]['sources'].items()] * 2
    assert not any(pin['path'] == str(f.live) for pin in f.pins)


@pytest.mark.parametrize('mutation', [
    'missing_review', 'classification', 'executed', 'live_path', 'snapshot_path',
    'live_hash', 'snapshot_hash', 'extra_field', 'executable_substitution'])
def test_frozen_configuration_rejects_nonexact_custody_before_guard(frozen_configuration, mutation):
    f = frozen_configuration
    review = copy.deepcopy(f.review); custody = review['nonexecuting_test_configuration']
    if mutation == 'missing_review': review.clear()
    elif mutation == 'classification': custody['classification'] = 'GENERAL_SOURCE_EXCEPTION'
    elif mutation == 'executed': custody['executed'] = True
    elif mutation == 'live_path': custody['live']['path'] = str(f.repo / 'alternate.ini')
    elif mutation == 'snapshot_path': custody['original_snapshot']['path'] = str(f.run / 'other' / 'pytest.ini')
    elif mutation == 'live_hash': custody['live']['sha256'] = '0' * 64
    elif mutation == 'snapshot_hash': custody['original_snapshot']['sha256'] = '0' * 64
    elif mutation == 'extra_field': custody['allow_other_sources'] = True
    elif mutation == 'executable_substitution':
        custody['live'] = dict(path=str(f.code[0]), sha256=m.binding.sha(f.code[0]))
    with pytest.raises(ValueError):
        with m.frozen_test_configuration(review):
            raise AssertionError('Invalid admission must not enter the body')
    assert m.ctl.checked_sources is f.guard and not f.calls and not f.pins


@pytest.mark.parametrize('mutation', ['missing_live', 'wrong_original', 'already_snapshot', 'wrong_run'])
def test_frozen_configuration_rejects_design_or_run_changes_without_owner_bypass(frozen_configuration, mutation):
    f = frozen_configuration; design = copy.deepcopy(f.design); run = f.run
    if mutation == 'missing_live': design['sources'].pop(str(f.live))
    elif mutation == 'wrong_original': design['sources'][str(f.live)] = f.review['nonexecuting_test_configuration']['live']['sha256']
    elif mutation == 'already_snapshot': design['sources'][str(f.snapshot)] = m.binding.sha(f.snapshot)
    elif mutation == 'wrong_run': run = f.run / 'different_run'
    before = copy.deepcopy(design)
    with pytest.raises(ValueError):
        with m.frozen_test_configuration(f.review):
            m.ctl.checked_sources(run, design)
    assert design == before and m.ctl.checked_sources is f.guard
    assert not f.calls and not f.pins


@pytest.mark.parametrize('which', ['live', 'snapshot'])
def test_frozen_configuration_rechecks_both_physical_files_after_admission(frozen_configuration, which):
    f = frozen_configuration
    before = copy.deepcopy(f.design)
    with pytest.raises(ValueError, match='TEST_CONFIGURATION_CHANGED_AFTER_ADMISSION'):
        with m.frozen_test_configuration(f.review):
            getattr(f, which).write_text('SYNTHETIC_MUTATION_AFTER_ADMISSION', encoding='utf-8')
            m.ctl.checked_sources(f.run, f.design)
    assert f.design == before and m.ctl.checked_sources is f.guard
    assert not f.calls and not f.pins


def test_frozen_configuration_keeps_executable_change_rejection_in_original_guard(frozen_configuration):
    f = frozen_configuration; before = copy.deepcopy(f.design)
    f.code[1].write_text('SYNTHETIC_CHANGED_CODE = 123456\n', encoding='utf-8')
    with pytest.raises(ValueError, match='PIN_CHANGED:'):
        with m.frozen_test_configuration(f.review):
            m.ctl.checked_sources(f.run, f.design)
    assert len(f.calls) == 1 and f.design == before
    assert m.ctl.checked_sources is f.guard
    assert any(pin['path'] == str(f.code[1]) for pin in f.pins)


def test_frozen_configuration_restores_original_function_after_body_exception(frozen_configuration):
    f = frozen_configuration
    with pytest.raises(RuntimeError, match='SYNTHETIC_BODY_FAILURE'):
        with m.frozen_test_configuration(f.review):
            m.ctl.checked_sources(f.run, f.design)
            raise RuntimeError('SYNTHETIC_BODY_FAILURE')
    assert m.ctl.checked_sources is f.guard and len(f.calls) == 1


@pytest.mark.parametrize('fail_body', [False, True])
def test_execute_scopes_actual_configuration_context_around_reviewed_body(frozen_configuration, monkeypatch, fail_body):
    f = frozen_configuration; events = []
    config_ref = dict(path=str(f.run / 'synthetic_inputs.json'), sha256='a' * 64)
    review_ref = dict(path=str(f.run / 'synthetic_review.json'), sha256='b' * 64)
    config = dict(source_review=review_ref)
    def read(reference):
        assert reference == config_ref; events.append('config'); return config
    def review_sources(reference):
        assert reference == review_ref; events.append('review'); return f.review
    def body(run, received_ref, received_config, review):
        assert run == f.run and received_ref == config_ref and received_config is config and review is f.review
        assert m.ctl.checked_sources is not f.guard
        events.append('reviewed_body')
        m.ctl.checked_sources(run, f.design)
        if fail_body: raise RuntimeError('SYNTHETIC_REVIEWED_BODY_FAILURE')
        return {'synthetic': 'complete'}
    monkeypatch.setattr(m, 'read_exact', read)
    monkeypatch.setattr(m, 'reviewed_sources', review_sources)
    monkeypatch.setattr(m, '_execute_reviewed', body)
    if fail_body:
        with pytest.raises(RuntimeError, match='SYNTHETIC_REVIEWED_BODY_FAILURE'):
            m.execute(f.run, config_ref)
    else:
        assert m.execute(f.run, config_ref) == {'synthetic': 'complete'}
    assert events == ['config', 'review', 'reviewed_body']
    assert m.ctl.checked_sources is f.guard and len(f.calls) == 1


@pytest.fixture
def recovery_case(tmp_path, monkeypatch):
    """Tiny physical metadata/opaque artifacts; no production body or state."""
    run=(tmp_path/'recovery_run').resolve();old=run/'risk_execution'
    run.mkdir();monkeypatch.setattr(m,'RUN',run)
    def write(path,value):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value),encoding='utf-8')
        return dict(path=str(path),sha256=m.binding.sha(path))
    def pin(reference):
        path=Path(reference['path'])
        m.ctl.require(m.binding.sha(path)==reference['sha256'],'SYNTHETIC_PIN_CHANGED')
        return path
    def read(reference,**_):return json.loads(pin(reference).read_text(encoding='utf-8'))
    monkeypatch.setattr(m.ctl,'pin',pin);monkeypatch.setattr(m,'read_exact',read)
    matrix=dict(roles=[dict(role='WAIT_'+str(i),current_status='WAITING_R5_PUBLICATION') for i in range(10)]
        +[dict(role='C14_D02',current_status='READY_FOR_METADATA_BINDING')])
    def build(mutation=None):
        refs={};delta=run/'RISK_EXECUTION_DELTA.jsonl';delta.write_text('{"event":"HEADER"}\n',encoding='utf-8')
        refs['delta_header']=dict(path=str(delta),sha256=m.binding.sha(delta))
        snap=run/'source_corrections/C14_SOURCE_METADATA_RECOVERY_ROUTING_R1/RISK_EXECUTION_DELTA_HEADER.jsonl'
        snap.parent.mkdir(parents=True,exist_ok=True);snap.write_bytes(delta.read_bytes())
        refs['header_snapshot']=dict(path=str(snap),sha256=m.binding.sha(snap))
        refs['source_review']=write(run/'RISK_INPUT_SOURCE_REVIEW_R2.json',dict(status='PASS'))
        cfg=dict(source_review=refs['source_review'])
        if mutation=='prior_config':cfg['source_review']={}
        refs['config']=write(old/'EXECUTION_INPUTS_R2.json',cfg)
        refs['started']=write(old/'EXECUTION_STARTED_R1.json',dict(config=refs['config'],review=refs['source_review']))
        refs['assembly']=write(old/'SCORE_ASSEMBLY_R1.json',dict(status='SCORE_ASSEMBLY_COMPLETE'))
        refs['final_pipeline']=write(old/'FINAL_PIPELINES_FREEZE_R1.json',dict(status='FINAL_PIPELINES_FROZEN'))
        slots={str(i):dict(status='UNRESERVED',entered=0) for i in range(144)}
        if mutation=='slot_started':slots['0']['status']='STARTED'
        if mutation=='slot_failed':slots['0']['status']='FAILED'
        if mutation=='slot_entered':slots['0']['entered']=1
        if mutation=='slot_bool':slots['0']['entered']=False
        if mutation=='slot_count':slots.pop('0')
        refs['fit_snapshot']=write(old/'FIT_STATUS_SNAPSHOT_R1.json',dict(authoritative_delta_ref=refs['delta_header'],not_an_independent_ledger=True,slots=slots))
        counts={k:0 for k in ('native_state_load_attempts','native_states_loaded','daily_role_bindings','selector_fit',
            'risk_estimator_fit','solver','bootstrap','risk_numeric_read','test2026_rows_read','EF_access','provider_fetch')}
        if mutation in counts:counts[mutation]=1
        if mutation=='counts_bool':counts['selector_fit']=False
        if mutation=='counts_missing':counts.pop('selector_fit')
        gates={r['role']:dict(states=[],full_required_dates_qualified=False,phase='BLOCKED_INPUT',
            reasons=['RiskBindingBlocked:ORIGINAL_MECHANISM_SOURCE_TIME_ONLY']) for r in matrix['roles']}
        if mutation=='qualified':gates['WAIT_0']['full_required_dates_qualified']=True
        if mutation=='states':gates['WAIT_0']['states']=[{}]
        if mutation=='other_blocker':gates['WAIT_0']['reasons']=['NATIVE_SCIENTIFIC_FAILURE']
        if mutation=='roles_missing':gates.pop('WAIT_0')
        qual=dict(research_id=m.ctl.ID,counts=counts,realized_endpoint_qualified=False,roles=gates)
        if mutation=='endpoint':qual['realized_endpoint_qualified']=True
        refs['qualification']=write(old/'INPUT_QUALIFICATION_R1.json',qual)
        artifacts={}
        for key,name in (('panel','scores_pre2026.parquet'),('predicted_risk','predicted_risk_pre2026.parquet')):
            path=old/'C14_D02'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'SYNTHETIC_OPAQUE_NOT_PARQUET')
            artifacts[key]=dict(path=str(path),sha256=m.binding.sha(path))
        d02=dict(status='MEMBERSHIP_COMPLETE',role='C14_D02',failure=None)
        member=dict(research_id=m.ctl.ID,status='MEMBERSHIP_ASSEMBLY_COMPLETE',complete_candidates=['C14_D02'],
            native_pair_predictions={},roles={'C14_D02':d02},panels={'C14_D02':artifacts['panel']},
            predicted_risk={'C14_D02':artifacts['predicted_risk']})
        if mutation=='extra_complete':member['complete_candidates'].append('C14_RX_HGB_LW')
        if mutation=='native_predictions':member['native_pair_predictions']['C14_D02']={}
        refs['membership']=write(old/'MEMBERSHIP_ASSEMBLY.json',member)
        refs['d02_receipts']=write(old/'C14_D02/MEMBERSHIP_RECEIPTS.json',[{}] if mutation=='d02_receipts' else [])
        refs['d02_assembly']=write(old/'C14_D02/MEMBERSHIP_ASSEMBLY.json',{} if mutation=='d02_assembly' else d02)
        terminal=dict(research_id=m.ctl.ID,status='RISK_DECISIONS_TERMINAL_JOINT_DELIVERY_PENDING',review_ref=refs['source_review'],
            input_qualification=refs['qualification'],assembly=refs['assembly'],final_pipeline=refs['final_pipeline'],delta=refs['delta_header'],
            complete_conditional_roles=['C14_D02'],complete_fixed_contrasts=[],joint_delivery_completed=False,coverage_sufficient_claim_allowed=False,
            combined_charged_solves=m.journal_owner.BASELINE_SOLVES,
            **{k:0 for k in ('reserved_fit_slots','backend_entered','complete_fit_slots','failed_fit_slots','blocked_fit_slots',
                              'charged_solves','new_risk_estimations','scientific_retry','test2026_rows_read')})
        if mutation in ('reserved_fit_slots','backend_entered','complete_fit_slots','failed_fit_slots','blocked_fit_slots',
                        'charged_solves','new_risk_estimations','scientific_retry'):terminal[mutation]=1
        if mutation=='prior_terminal_chain':terminal['assembly']={}
        if mutation=='joint':terminal['joint_delivery_completed']=True
        if mutation=='coverage':terminal['coverage_sufficient_claim_allowed']=True
        if mutation=='contrast':terminal['complete_fixed_contrasts']=['C14_CONTRAST']
        refs['terminal']=write(old/'RISK_DECISIONS_TERMINAL_R1.json',terminal)
        monkeypatch.setattr(m,'RECOVERY_PINS',{k:refs[k]['sha256'] for k in m.RECOVERY_PINS})
        receipt=dict(schema=m.RECOVERY_SCHEMA,research_id=m.ctl.ID,status='PASS',classification='SOURCE_METADATA_ENGINEERING_ONLY',
            artifact_root=str(old/m.RECOVERY_NAME),prior_refs=refs,d02_artifacts=artifacts,scientific_contract_changed=False,
            scientific_retry=0,historical_delta_reference_policy=m.RECOVERY_DELTA_POLICY)
        if mutation=='artifact_root':receipt['artifact_root']=str(old/'other')
        if mutation=='classification':receipt['classification']='SCIENTIFIC_RETRY'
        if mutation=='receipt_extra':receipt['allow_other']=True
        if mutation=='receipt_retry_bool':receipt['scientific_retry']=False
        if mutation=='missing_pin':receipt['prior_refs'].pop('assembly')
        if mutation=='foreign_pin':receipt['prior_refs']['assembly']['path']=str(run/'foreign.json')
        if mutation=='wrong_literal_pin':receipt['prior_refs']['terminal']['sha256']='0'*64
        if mutation=='artifact_pin':receipt['d02_artifacts']['panel']=dict(path='foreign',sha256='0'*64)
        reference=write(run/'C14_SOURCE_METADATA_RECOVERY_RECEIPT_R1.json',receipt)
        return SimpleNamespace(run=run,old=old,matrix=matrix,receipt=receipt,refs=refs,reference=reference,
            review=dict(source_metadata_recovery_ref=reference),write=write)
    return build


def test_zero_entry_recovery_reads_metadata_opaque_pins_and_default_is_unchanged(recovery_case):
    c=recovery_case();before={p:p.read_bytes() for p in c.run.rglob('*') if p.is_file()}
    assert m.recovery_metadata(c.run,{},c.matrix) is None
    result=m.recovery_metadata(c.run,c.review,c.matrix)
    assert result['root']==c.old/m.RECOVERY_NAME and result['raw_identity_ref']==c.refs['membership']
    assert {p:p.read_bytes() for p in before}==before
    assert not result['root'].exists()


@pytest.mark.parametrize('mutation', ['native_state_load_attempts','native_states_loaded','daily_role_bindings','selector_fit',
    'risk_estimator_fit','solver','bootstrap','risk_numeric_read','test2026_rows_read','EF_access','provider_fetch',
    'reserved_fit_slots','backend_entered','complete_fit_slots','failed_fit_slots','blocked_fit_slots','charged_solves',
    'new_risk_estimations','scientific_retry','counts_bool','counts_missing','slot_started','slot_failed','slot_entered',
    'slot_bool','slot_count','qualified','states','other_blocker','roles_missing','endpoint','extra_complete',
    'native_predictions','d02_receipts','d02_assembly','prior_config','prior_terminal_chain','joint','coverage','contrast',
    'artifact_root','classification','receipt_extra','receipt_retry_bool','missing_pin','foreign_pin','wrong_literal_pin','artifact_pin'])
def test_recovery_rejects_any_prior_entry_changed_chain_or_alternative_route(recovery_case,mutation):
    c=recovery_case(mutation)
    with pytest.raises((ValueError,KeyError)):m.recovery_metadata(c.run,c.review,c.matrix)
    assert not (c.old/m.RECOVERY_NAME).exists()


@pytest.mark.parametrize('target', ['terminal','qualification','source_review','config','header_snapshot','membership','assembly','final_pipeline','fit_snapshot','d02_assembly','d02_receipts'])
def test_recovery_rejects_changed_physical_prior_pin(recovery_case,target):
    c=recovery_case();path=Path(c.refs[target]['path']);path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError):m.recovery_metadata(c.run,c.review,c.matrix)


@pytest.mark.parametrize('mutation', [None,'sequence','roles','requests','slot_started','entered','foreign_ledger','live_delta'])
def test_recovery_replays_only_original_header_authority_and_never_creates_new_ledger(recovery_case,monkeypatch,mutation):
    c=recovery_case();recovery=m.recovery_metadata(c.run,c.review,c.matrix);calls=[]
    slots={str(i):dict(status='UNRESERVED',entered=0) for i in range(144)}
    j=SimpleNamespace(path=c.run/'RISK_EXECUTION_DELTA.jsonl',sequence=1,roles={},requests={},slots=slots,verify=lambda:calls.append('verify'))
    if mutation=='sequence':j.sequence=2
    if mutation=='roles':j.roles['C14_RX_HGB_LW']={}
    if mutation=='requests':j.requests['CLASSICAL|C14_D01|SYNTHETIC']={}
    if mutation=='slot_started':j.slots['0']['status']='STARTED'
    if mutation=='entered':j.slots['0']['entered']=1
    if mutation=='foreign_ledger':j.path=c.old/m.RECOVERY_NAME/'RISK_EXECUTION_DELTA.jsonl'
    if mutation=='live_delta':j.path.write_bytes(j.path.read_bytes()+b'{"event":"ACTIVATE"}\n')
    def constructor(run):calls.append(run);return j
    monkeypatch.setattr(m.journal_owner,'RiskJournal',constructor)
    if mutation is None:
        assert m.recovery_journal(c.run,recovery) is j and calls==[c.run,'verify']
    else:
        with pytest.raises(ValueError):m.recovery_journal(c.run,recovery)
        assert calls==([] if mutation=='live_delta' else [c.run])
    assert not (c.old/m.RECOVERY_NAME).exists()


def test_reviewed_recovery_routes_all_new_outputs_and_reuses_one_journal(flow,monkeypatch):
    f=flow;root=f.run/'risk_execution'/m.RECOVERY_NAME;old=f.run/'risk_execution';old.mkdir()
    (old/'EXECUTION_STARTED_R1.json').write_text('SYNTHETIC_OLD_START')
    (old/'RISK_DECISIONS_TERMINAL_R1.json').write_text('SYNTHETIC_OLD_TERMINAL')
    identity=dict(path=str(old/'MEMBERSHIP_ASSEMBLY.json'),sha256='a'*64)
    j=SimpleNamespace(run=f.run,path=f.run/'RISK_EXECUTION_DELTA.jsonl',roles=[],slots={},requests={},families={*f.roles,'C14_D01'})
    def activate(role,reference):
        assert reference['path'].startswith(str(root));f.events.append(('activate',role));j.roles.append(role)
    j.activate_role=activate
    def recovery_journal(run,recovery):
        assert run==f.run and recovery['root']==root;f.events.append(('original_journal_zero_entry',));return j
    monkeypatch.setattr(m,'recovery_metadata',lambda *_:dict(root=root,raw_identity_ref=identity))
    monkeypatch.setattr(m,'recovery_journal',recovery_journal)
    monkeypatch.setattr(m.journal_owner,'RiskJournal',lambda *_:pytest.fail('A second ledger/constructor is forbidden'))
    def hybrid(*args,artifact_root):
        assert artifact_root==root and args[8] is j;f.events.append(('recovery_hybrid',args[6]));return empty_result()
    def membership(*args,role_gates,qualification_ref,artifact_root,raw_identity_ref):
        assert args[7] is j and artifact_root==root and raw_identity_ref==identity
        assert qualification_ref['path']==str(root/'INPUT_QUALIFICATION_R1.json')
        f.events.append(('recovery_membership',));return empty_result()
    def terminal(*args,artifact_root):
        assert artifact_root==root and args[6] is j;return dict(status='RISK_DECISIONS_TERMINAL_JOINT_DELIVERY_PENDING')
    monkeypatch.setattr(m.hybrids,'execute_hybrid',hybrid);monkeypatch.setattr(m.membership,'execute_membership',membership)
    monkeypatch.setattr(m,'terminal',terminal)
    m.execute(f.run,f.config_ref)
    names=[e[0] for e in f.events]
    assert names.index('original_journal_zero_entry')<names.index('qualify_full752')<names.index('activate')<names.index('recovery_hybrid')
    assert all(Path(p).is_relative_to(root) for p in f.written)
    assert (old/'EXECUTION_STARTED_R1.json').read_text()=='SYNTHETIC_OLD_START'
    assert (old/'RISK_DECISIONS_TERMINAL_R1.json').read_text()=='SYNTHETIC_OLD_TERMINAL'


def test_recovery_terminal_writes_only_versioned_artifacts_and_retains_ml_refs(finish,monkeypatch):
    f=finish;root=f.run/'risk_execution'/m.RECOVERY_NAME;paths=[]
    def put(path,value):paths.append(Path(path));f.written[Path(path).name]=copy.deepcopy(value)
    monkeypatch.setattr(m,'put',put)
    m.terminal(f.run,f.design,f.q,f.old,f.qualification,[],f.journal,f.review_ref,artifact_root=root)
    assert all(p.parent==root for p in paths) and len(paths)==4
    assert f.written['SCORE_ASSEMBLY_R1.json']['original_ml_assembly_ref']['path']==str(f.run/'ML_ASSEMBLY.json')
    assert f.written['SCORE_ASSEMBLY_R1.json']['conditional_delta_ref']['path']==str(f.journal.path)


@pytest.fixture
def retained_terminal_qualification(finish,monkeypatch):
    f=finish;root=f.run/'risk_execution'/m.SOURCE_GUARD_RECOVERY_NAME
    path=f.run/'risk_execution'/m.RECOVERY_NAME/'INPUT_QUALIFICATION_R1.json'
    path.parent.mkdir(parents=True)
    f.qualification=copy.deepcopy(f.qualification)
    f.qualification['synthetic_zero_entry']=False
    path.write_text(json.dumps(f.qualification),encoding='utf-8')
    before=path.read_bytes();digest=hashlib.sha256(before).hexdigest()
    reference=dict(path=str(path.resolve()),sha256=digest)
    monkeypatch.setattr(m,'SOURCE_METADATA_QUALIFICATION_SHA',digest)
    monkeypatch.setattr(m.binding,'sha',lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
        if Path(p).resolve()==path.resolve() else 'a'*64)
    monkeypatch.setattr(m,'ref',lambda p:dict(path=str(p),sha256=m.binding.sha(p)))
    return SimpleNamespace(f=f,root=root,path=path,reference=reference,before=before)


def test_source_guard_terminal_binds_exact_retained_qualification_without_copy_or_ledger(retained_terminal_qualification,monkeypatch):
    s=retained_terminal_qualification;f=s.f;paths=[]
    def put(path,value):paths.append(Path(path));f.written[Path(path).name]=copy.deepcopy(value)
    monkeypatch.setattr(m,'put',put)
    summary=m.terminal(f.run,f.design,f.q,f.old,f.qualification,[],f.journal,f.review_ref,
        artifact_root=s.root,input_qualification_ref=s.reference)
    assert len(paths)==4 and all(p.parent==s.root for p in paths)
    assert not any(p.name in ('INPUT_QUALIFICATION_R1.json','RISK_EXECUTION_DELTA.jsonl') for p in paths)
    assert f.written['SCORE_ASSEMBLY_R1.json']['input_qualification']==s.reference==summary['input_qualification']
    assert f.written['SCORE_ASSEMBLY_R1.json']['conditional_delta_ref']['path']==str(f.journal.path)
    assert f.written['SCORE_ASSEMBLY_R1.json']['original_ml_assembly_ref']['path']==str(f.run/'ML_ASSEMBLY.json')
    assert s.path.read_bytes()==s.before and f.journal.slots=={} and f.journal.requests=={}
    assert summary['joint_delivery_completed'] is False and summary['coverage_sufficient_claim_allowed'] is False


@pytest.mark.parametrize('mutation',['missing','path','sha','extra','body','bool_alias','physical','during_read'])
def test_source_guard_terminal_rejects_nonexact_retained_qualification_before_any_output(retained_terminal_qualification,monkeypatch,mutation):
    s=retained_terminal_qualification;f=s.f;reference=copy.deepcopy(s.reference);body=copy.deepcopy(f.qualification)
    if mutation=='missing':reference=None
    elif mutation=='path':reference['path']=str(s.root/'INPUT_QUALIFICATION_R1.json')
    elif mutation=='sha':reference['sha256']='f'*64
    elif mutation=='extra':reference['forged']=True
    elif mutation=='body':body['forged']=True
    elif mutation=='bool_alias':body['synthetic_zero_entry']=0
    elif mutation=='physical':s.path.write_bytes(b'CHANGED_SYNTHETIC_QUALIFICATION')
    elif mutation=='during_read':
        original=m.read_exact
        def read(reference,**kwargs):
            value=original(reference,**kwargs)
            s.path.write_bytes(b'CHANGED_AFTER_SYNTHETIC_READ')
            return value
        monkeypatch.setattr(m,'read_exact',read)
    with pytest.raises(ValueError):
        m.terminal(f.run,f.design,f.q,f.old,body,[],f.journal,f.review_ref,
            artifact_root=s.root,input_qualification_ref=reference)
    assert not f.written and f.journal.slots=={} and f.journal.requests=={}


@pytest.mark.parametrize('root_kind',['alternate','descendant','foreign','models'])
def test_terminal_rejects_nonfixed_artifact_root_before_qualification_read_or_output(finish,monkeypatch,root_kind):
    f=finish;root={'alternate':f.run/'risk_execution/source_guard_recovery_r2',
        'descendant':f.run/'risk_execution/source_guard_recovery_r1/nested',
        'foreign':f.run.parent/'other/risk_execution/source_guard_recovery_r1',
        'models':f.run/'risk_execution/models'}[root_kind]
    monkeypatch.setattr(m,'read_exact',lambda *_a,**_k:pytest.fail('No qualification read under an arbitrary root'))
    with pytest.raises(ValueError,match='ARTIFACT_ROOT'):
        m.terminal(f.run,f.design,f.q,f.old,f.qualification,[],f.journal,f.review_ref,artifact_root=root)
    assert not f.written


@pytest.mark.parametrize('recovery',[False,True])
def test_original_terminal_roots_keep_local_qualification_and_reject_external_override(finish,monkeypatch,recovery):
    f=finish;root=f.run/'risk_execution'
    if recovery:root=root/m.RECOVERY_NAME
    monkeypatch.setattr(m,'read_exact',lambda *_a,**_k:pytest.fail('Default roots must not acquire a new qualification reader'))
    summary=m.terminal(f.run,f.design,f.q,f.old,f.qualification,[],f.journal,f.review_ref,artifact_root=root)
    expected=dict(path=str(root/'INPUT_QUALIFICATION_R1.json'),sha256='a'*64)
    assert summary['input_qualification']==expected==f.written['SCORE_ASSEMBLY_R1.json']['input_qualification']
    f.written.clear()
    with pytest.raises(ValueError,match='EXPLICIT_QUALIFICATION_REF_ONLY'):
        m.terminal(f.run,f.design,f.q,f.old,f.qualification,[],f.journal,f.review_ref,
            artifact_root=root,input_qualification_ref=expected)
    assert not f.written



def test_recovery_missing_original_delta_is_rejected_before_any_journal_constructor(recovery_case,monkeypatch):
    c=recovery_case();recovery=m.recovery_metadata(c.run,c.review,c.matrix)
    (c.run/'RISK_EXECUTION_DELTA.jsonl').unlink()
    monkeypatch.setattr(m.journal_owner,'RiskJournal',lambda *_:pytest.fail('Missing original authority must never create a new ledger'))
    with pytest.raises(FileNotFoundError):m.recovery_journal(c.run,recovery)
    assert not (c.run/'RISK_EXECUTION_DELTA.jsonl').exists()
    assert not (c.old/m.RECOVERY_NAME).exists()
