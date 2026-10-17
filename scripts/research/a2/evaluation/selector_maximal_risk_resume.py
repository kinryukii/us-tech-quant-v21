"""Fixed C14 checkpoint and terminal-bound engineering continuations.

The first admission remains classical-only. The separate terminal admission
reuses all complete artifacts and authorizes only the original zero-entry RX28
plus unentered named classical solves. Frozen science and prior bytes remain
unchanged; qualification metadata reuse never replaces real native load gates.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import dis
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

REPO = Path('D:/us-tech-quant').resolve()
RUN = Path('D:/us-tech-quant-backtests/V24/20261004T070941+0000_13adcb4c').resolve()
ROOT = RUN / 'risk_execution/source_metadata_recovery_r1'
B_RUN = Path('D:/us-tech-quant-backtests/V24/20261004T044305+0000_d21499cc').resolve()
ID = 'V24_C_SELECTOR_MAXIMAL_BREADTH_PRE2026_C14'
SCHEMA = 'C14_CHECKPOINT_CLASSICAL_ONLY_REVIEW_V2'
CLASSICAL = ('C14_D01', 'C14_D05', 'C14_D06', 'C14_D09', 'C14_D10', 'C14_D11')
RX = ('C14_RX_HGB_LW', 'C14_RX_XGB_QQQ_RESIDUAL')
QUALIFIED = (*RX, *CLASSICAL, 'C14_G1', 'C14_G4')
ACTIVATED = (*RX, *CLASSICAL)
EXPECTED_SOLVES = {'C14_D01': 752, 'C14_D05': 226}
MARKER = 'CHECKPOINT_CLASSICAL_RESUME_STARTED_R2.json'
AUDIT = 'CHECKPOINT_CLASSICAL_RESUME_COMPLETE_R2.json'
REVIEW_PATH = RUN/'C14_CHECKPOINT_CLASSICAL_RESUME_REVIEW_R3.json'
MAINTENANCE = Path('D:/us-tech-quant-results/V24/C_SELECTOR/C14_MAXIMAL_BREADTH/_maintenance/C14_RISK_EXECUTION_ENGINEERING_R1')
CA_NAME = 'scripts.v22.corporate_action_transition_r1'
ACCOUNT_NAME = 'scripts.research.a2.evaluation.continuous_research_account'
JOINT_NAME = 'scripts.research.a2.portfolio.joint_allocation_methods'
FAST_NAME = 'scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account'
FAST_PATH = REPO/'scripts/research/a2/retained/a2_pto_full_compat_20260928_r2/fast_account.py'
FAST_SHA = '200462d48816918a5b9fe72f2239a81d01f69a32d57922e8e47cf1ee4c06ee1b'
POLICY_NAME = 'scripts.research.a2.inference.joint_portfolio_policy'
POLICY_PATH = REPO/'scripts/research/a2/inference/joint_portfolio_policy.py'
POLICY_SHA = 'c116bd9dcf28e9a6f53a3b183d2335febd02ae1ef4bbfe90a827b70dcd27352f'
OPT_NAME = 'scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.optimization'
OPT_PATH = REPO/'scripts/research/a2/retained/a2_pto_full_compat_20260928_r2/optimization.py'
OPT_SHA = '0a96355fa6aa99ac63766c4a1765a7e099513828bd7ddfdd9e36a03b31b6be73'
MEMBERSHIP_NAME = 'scripts.research.a2.factors.selector_constrained_membership'
MEMBERSHIP_PATH = REPO/'scripts/research/a2/factors/selector_constrained_membership.py'
FAILURE_SHA = '6a370e5b212ae5e6455b2f33896f0197ee0550a86b74a9da1bc801e4ce22b633'
PINS = {
    'original_config': (RUN/'risk_execution/EXECUTION_INPUTS_R3.json', '797d897ca2645ee5d78a4d634caf454f408a61b99087219649d40d51382cf33c'),
    'original_review': (RUN/'RISK_INPUT_SOURCE_REVIEW_R3.json', '94494524c91fac4cac34eff9283c4b2e546d668c2478edebf693c3089d249b6e'),
    'qualification': (ROOT/'INPUT_QUALIFICATION_R1.json', 'a4976c8990b9af5e5107bcaeeed70ff7d15680f8659d4680fdeb6e4d646f99d3'),
    'prior_started': (ROOT/'EXECUTION_STARTED_R1.json', '29c7ba39eea8d1765e9effcdc3f63c687b91632560da0a7ff4507cb1c9fcb814'),
    'pipeline': (ROOT/'PIPELINE_STATE.json', '5ee8bc58e733c0831d30b9bc197d1470250b6362786115deb0491ebfdc498ab7'),
    'pause_receipt': (Path('D:/us-tech-quant-results/V24/C_SELECTOR/C14_MAXIMAL_BREADTH/_maintenance/C14_RISK_EXECUTION_ENGINEERING_R1/USER_REQUESTED_PAUSE_R1.json'), '52b3dea64b393e6c5a85a3d91c79df7fcf42ee82957fb8f07bab0412fdb6f803'),
    'publication_failure': (MAINTENANCE/'CHECKPOINT_PUBLICATION_CLOSURE_FAILURE_R1.json', 'f871939bc07b7903a7c9eeed900505c5f92913ecc698772152304c2351a32ce9'),
    'prior_checkpoint_marker': (ROOT/'CHECKPOINT_CLASSICAL_RESUME_STARTED_R1.json', '97e5f89417f32ce3aeda8a7e26101f80632f97e2f6a495978a5a79b11bed67a4'),
    'prior_checkpoint_review': (RUN/'C14_CHECKPOINT_CLASSICAL_RESUME_REVIEW_R2.json', '62002405782898ee9d139f26fb0b2a96b73757c97e83d9aa72da94a4ecfbc2a9'),
    'B_freeze': (B_RUN/'R5_SCIENCE_AND_EXECUTION_FREEZE.json', 'c87698161826a34af0a8c22d1d3392bf43e177092f5428a18be1633d635ac76c'),
    'original_publication_admission': (RUN/'R5_PUBLICATION_ADMISSION_R3.json', '59ff275b551986ea412cd1efc4b5f599ecbcbe1faf2e3eaa83cd7ec364737270'),
}
FAILURE_REFS = {
    'entry': (MAINTENANCE/'CHECKPOINT_RESUME_ENTRY_BEFORE_PUBLICATION_CLOSURE_RECOVERY_R1.txt', 'd9fa4e37bd97324600653930d9bb3cdacec69d2d2d42be64b527d8c89bcde0b2'),
    'formal_review': PINS['prior_checkpoint_review'],
    'prelaunch': (RUN/'risk_execution/CLASSICAL_CHECKPOINT_RESUME_PRELAUNCH_R1.json', '81a485822cc5ca30868c7f017315c94ceb61cb268f376cd50c86626bbdac0f00'),
    'launch': (RUN/'risk_execution/CLASSICAL_CHECKPOINT_RESUME_LAUNCH_RECEIPT_R1.json', '0ada085f7dfb0ea7faf8bfe411dd5c0bc0b7d54b793bc965529079426aa3d6bb'),
    'marker': PINS['prior_checkpoint_marker'],
    'pipeline': PINS['pipeline'],
    'stdout': (RUN/'logs/c14_classical_checkpoint_resume_r1.stdout.log', '26c0126d84edd606c33260d23eed084f9b313e498d4edae4ba8279e2dbdaaa59'),
    'stderr': (RUN/'logs/c14_classical_checkpoint_resume_r1.stderr.log', '70eafe1445360e4abdafcf80ea76ddf8b6a8a30e3093c3a5d17d773ea8a80232'),
    'B_freeze': PINS['B_freeze'],
}
DELTA_SHA = '22196965a414968bdb7b36b53773c2743521435bf38d4233fbe6f2f0ad6dd0b1'
DELTA_BYTES, DELTA_LINES = 6526570, 1967
TRANSPORT = {
    CA_NAME: (
        'scripts/v22/corporate_action_transition_r1.py',
        '79cb09efb1d4a25c8a746cd015cbc873b926b77e9c2a30e2ca82f5f583750e32',
        '2f65861d376b0596782033e19a0c6625bf539da845d48cba8e04efd26d38a9e4'),
    ACCOUNT_NAME: (
        'scripts/research/a2/evaluation/continuous_research_account.py',
        'b9bd90d88b0c678698092341483c3129931e007dfe892b25a61fd26eaf0c4d35',
        'd4c54be4d10340edbc37ee87b48b544ad02ae81ae8ff338481fb79361393a8de'),
    JOINT_NAME: (
        'scripts/research/a2/portfolio/joint_allocation_methods.py',
        '0feae460e1de42fb712ae2a035bf6fcbd48f22f96e7e4c97db2cf1309e721250',
        'd2869e7f837b4e4a58fa5a08d773a35ef6a3edd64530224e2435a75fbdb54917'),
}
_CUSTODY = {}


def stamp(path):
    s = Path(path).stat()
    return s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_dev, s.st_ino


def verify_custody():
    need(all(stamp(p) == value[0] for p, value in _CUSTODY.items()), 'ADMITTED_PHYSICAL_CUSTODY_CHANGED')


def need(ok, message):
    if not ok:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def safe_path(value):
    p = Path(value).absolute()
    need(p.drive.upper() == 'D:', 'D_CUSTODY_ONLY')
    for ancestor in (p, *p.parents):
        if ancestor.exists():
            need(not (getattr(ancestor.stat(), 'st_file_attributes', 0) & 0x400),
                 'REPARSE_CUSTODY_FORBIDDEN')
    need(p == p.resolve(), 'PHYSICAL_PATH_ALIAS_FORBIDDEN')
    return p


def sha(path):
    p = safe_path(path)
    before = p.stat()
    h = hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    after = p.stat()
    need((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
         (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'PIN_CHANGED_DURING_HASH')
    return h.hexdigest()


def pin(reference, *, path=None, expected=None):
    need(isinstance(reference, dict) and set(reference) == {'path', 'sha256'}, 'EXACT_PHYSICAL_REF_REQUIRED')
    p = safe_path(reference['path'])
    if path is not None:
        need(p == Path(path).resolve(), 'FIXED_PHYSICAL_PATH_REQUIRED')
    h = reference['sha256']
    need(isinstance(h, str) and len(h) == 64 and all(c in '0123456789abcdef' for c in h), 'SHA256_REQUIRED')
    need(expected is None or h == expected, 'FIXED_HISTORICAL_SHA_REQUIRED')
    before = stamp(p)
    need(sha(p) == h, 'PHYSICAL_PIN_CHANGED:' + str(p))
    observed = stamp(p)
    need(before == observed and (str(p) not in _CUSTODY or _CUSTODY[str(p)] == (observed, h)),
         'CUSTODY_CHANGED_AFTER_ADMISSION')
    _CUSTODY[str(p)] = observed, h
    return p


def read(reference, **kwargs):
    p = pin(reference, **kwargs)
    value = json.loads(p.read_text(encoding='utf-8'))
    pin(reference, **kwargs)
    return value


def reference(path):
    return {'path': str(Path(path)), 'sha256': sha(path)}


def process_inventory():
    # Process metadata only. Never suspend/resume/kill or start a business worker.
    code = "Get-CimInstance Win32_Process | Where-Object {$_.Name -match '^python(w)?\\.exe$'} | Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress"
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', code],
        capture_output=True, text=True, check=True, timeout=45)
    value = json.loads(result.stdout.strip() or '[]')
    return value if isinstance(value, list) else [value]


def no_other_worker():
    for process in process_inventory():
        command = str(process.get('CommandLine') or '').replace('\\', '/').lower()
        module = ('selector_maximal_risk_execution' in command or 'selector_maximal_risk_resume' in command)
        if not module:
            continue
        pid = int(process['ProcessId'])
        self_process = pid == os.getpid()
        launcher = pid == os.getppid() and 'selector_maximal_risk_resume' in command
        need(self_process or launcher, 'OTHER_C14_EXECUTION_OR_RESUME_WORKER_EXISTS')


def audit_delta(raw):
    """Read only event structure and opaque cache digests; never select outcomes."""
    need(raw.endswith(b'\n') and len(raw) == DELTA_BYTES
        and hashlib.sha256(raw).hexdigest() == DELTA_SHA, 'EXACT_PAUSE_DELTA_BYTES_REQUIRED')
    lines = raw.splitlines()
    need(len(lines) == DELTA_LINES, 'EXACT_PAUSE_DELTA_LINES_REQUIRED')
    previous = '0' * 64
    actions, activations, blocks, requests = Counter(), {}, {}, {}
    for sequence, line in enumerate(lines):
        row = json.loads(line)
        need(set(row) == {'sequence', 'previous', 'action', 'data', 'sha256'}, 'EXACT_DELTA_ROW_SCHEMA')
        payload = {k: row[k] for k in ('sequence', 'previous', 'action', 'data')}
        need(type(row['sequence']) is int and row['sequence'] == sequence and row['previous'] == previous
            and digest(payload) == row['sha256'], 'DELTA_HASH_CHAIN_CHANGED')
        previous = row['sha256']; action, data = row['action'], row['data']; actions[action] += 1
        if action == 'HEADER':
            need(sequence == 0 and data.get('research_id') == ID and data.get('scientific_retry') == 0,
                 'ORIGINAL_DELTA_HEADER_REQUIRED')
        elif action == 'ACTIVATE_ROLE':
            role = data['role']
            need(role in ACTIVATED and role not in activations, 'EXACT_EIGHT_ACTIVATIONS_REQUIRED')
            activations[role] = data['qualification']
        elif action == 'BLOCK_REMAINING':
            role = data['role']
            need(role in RX and role not in blocks and len(data['nodes']) == len(set(data['nodes'])) == 14
                and data['reason'] == 'UNEXPECTED_ENGINEERING_FAILURE_BEFORE_UNUSED_FITS', 'ONLY_TWO_PREFIT_ENGINEERING_BLOCKS')
            blocks[role] = data
        elif action == 'SOLVE_ENTER':
            token = data['token']
            need(token not in requests and token.startswith('CLASSICAL|'), 'CHARGED_RX_OR_DUPLICATE_SOLVE_FORBIDDEN')
            requests[token] = None
        elif action == 'SOLVE_COMPLETE':
            token, receipt = data['token'], data['receipt']
            need(token in requests and requests[token] is None and set(receipt) == {'identity', 'result', 'result_sha256'}
                and digest(receipt['result']) == receipt['result_sha256'], 'MATCHED_EXACT_COMPLETE_CACHE_REQUIRED')
            requests[token] = receipt
        else:
            raise ValueError('FIT_STARTED_FAILED_OR_UNKNOWN_EVENT_FORBIDDEN:' + action)
    need(actions == Counter(HEADER=1, ACTIVATE_ROLE=8, BLOCK_REMAINING=2, SOLVE_ENTER=978, SOLVE_COMPLETE=978)
        and set(activations) == set(ACTIVATED) and set(blocks) == set(RX), 'EXACT_PAUSE_EVENT_COUNTS_REQUIRED')
    need(all(v is not None for v in requests.values()), 'CHARGED_WITHOUT_COMPLETE_CACHE_FORBIDDEN')
    counts = Counter(token.split('|')[1] for token in requests)
    need(dict(counts) == EXPECTED_SOLVES, 'ONLY_752_D01_226_D05_PAUSE_CACHE_REQUIRED')
    return {'activations': activations, 'blocks': blocks, 'requests': requests,
            'counts': dict(counts), 'previous': previous, 'sequence': len(lines)}


def validate_qualification(qualification, matrix, current, original_review_ref, activations):
    gates = qualification.get('roles', {})
    rows = {row['role']: row for row in matrix['roles']}
    need(qualification.get('research_id') == ID and qualification.get('strict_PIT_promotion_eligible') is False
        and qualification.get('realized_endpoint_qualified') is False and set(gates) == set(rows), 'EXACT_PRIOR_INPUT_QUALIFICATION')
    expected = dict(native_state_load_attempts=330, native_states_loaded=330, daily_role_bindings=7520,
        selector_fit=0, risk_estimator_fit=0, solver=0, bootstrap=0, risk_numeric_read=330,
        test2026_rows_read=0, EF_access=0, provider_fetch=0)
    need(qualification.get('counts') == expected and all(type(v) is int for v in qualification['counts'].values()),
         'HISTORICAL_330_LOADS_AND_ZERO_QUALIFICATION_SCIENCE_REQUIRED')
    need({r for r, g in gates.items() if g.get('phase') == 'FULL752_NUMERIC_INPUT_QUALIFIED'} == set(QUALIFIED),
         'EXACT_TEN_FULL752_ROLES_REQUIRED')
    native_refs = {}
    for role, gate in gates.items():
        req = rows[role]; dates = req['required_dates']
        need(len(dates) == len(set(dates)) == 752 and dates == sorted(dates)
            and all(d < '2026-01-01' for d in dates) and set(dates) == set(current), 'EXACT752_PRE2026_DATES')
        need(gate.get('research_id') == ID and gate.get('role') == role and gate.get('family') == req['required_family_method']
            and gate.get('source_review') == original_review_ref and gate.get('design_sha256') == matrix['design_sha256']
            and gate.get('dag_sha256') == matrix['dag_sha256'] and gate.get('calendar_positions') == 752
            and gate.get('full_risk_mature_positions') == 732 and gate.get('learned_positions') == 482
            and gate.get('realized_endpoint_qualified') is False and gate.get('strict_PIT_promotion_eligible') is False
            and all(type(gate.get(k)) is int and gate[k] == 0 for k in ('selector_fit', 'solver', 'test2026_rows_read')),
            'FROZEN_ROLE_GATE_METADATA_CHANGED')
        if role not in QUALIFIED:
            need(gate.get('full_required_dates_qualified') is False and gate.get('states') == [], 'UNQUALIFIED_ROLE_CANNOT_GAIN_STATES')
            continue
        need(gate.get('full_required_dates_qualified') is True and gate.get('reasons') == []
            and [s.get('decision_date') for s in gate.get('states', [])] == dates, 'FULL752_NO_SHORTENING')
        for state in gate['states']:
            need(set(state) == {'decision_date', 'state_ref', 'header_qualified', 'current_UID_qualified',
                'numeric_qualified', 'full_U_keys_sha256', 'native_as_of', 'native_cutoff'}
                and all(state[k] is True for k in ('header_qualified', 'current_UID_qualified', 'numeric_qualified'))
                and state['full_U_keys_sha256'] == current[state['decision_date']]['c14_current_key_sha256'],
                'NATIVE_PSD_UID_FULL_U_SOURCE_GATE_CHANGED')
            ref = state['state_ref']; p = safe_path(ref['path'])
            need(p.is_relative_to(B_RUN/'models/risk') and p.suffix == '.joblib', 'ONLY_ORIGINAL_B_R5_NATIVE_FILES')
            need(str(p) not in native_refs or native_refs[str(p)] == ref, 'CONFLICTING_NATIVE_STATE_SHA')
            native_refs[str(p)] = ref
        gate_ref = reference(ROOT/'input_gates'/f'{role}.json')
        need(read(gate_ref) == gate, 'PHYSICAL_ROLE_GATE_DIFFERS_FROM_PRIOR_QUALIFICATION')
        if role in activations:
            stored = activations[role]
            need(stored == dict(qualification_ref=gate_ref, family=gate['family'],
                states_sha256=digest(gate['states']), dates=gate['states']), 'ACTIVATION_GATE_EVERY_FIELD_CHANGED')
    need(len(native_refs) == 330, 'EXACT_330_UNIQUE_NATIVE_PHYSICAL_PINS_REQUIRED')
    for ref in native_refs.values():
        pin(ref)  # Bytes only: no joblib/unpickle/covariance/PSD replay.
    return deepcopy(gates)


def validate_transport(custody):
    need(set(custody) == set(TRANSPORT), 'ONLY_THREE_FIXED_EXECUTABLE_SNAPSHOT_MODULES')
    transport = TRANSPORT
    if _TERMINAL_AUTHORITY is not None:
        pin(_TERMINAL_AUTHORITY, path=TERMINAL_REVIEW_PATH)
        need(_TERMINAL_TRANSPORT_SEAL == digest(custody), 'SEALED_TERMINAL_TRANSPORT_CHANGED')
        transport = TERMINAL_TRANSPORT
    for name, (relative, frozen, live) in transport.items():
        value = custody[name]
        need(set(value) == {'live', 'original_snapshot'}, 'EXACT_EXECUTABLE_DUAL_CUSTODY_SCHEMA')
        pin(value['live'], path=REPO/relative, expected=live)
        pin(value['original_snapshot'], path=RUN/'source_snapshot'/relative, expected=frozen)


def original_source_custody(design, review, custody):
    need(len(design['sources']) == 66 and len(review['source_pins']) == 30, 'ORIGINAL66_AND_REVIEWED30_SOURCES_REQUIRED')
    correction = read({'path': str(RUN/'SOURCE_CORRECTION.json'),
        'sha256': '1546b89dec22d71b2842de9d3b55b20f8508d6edccbaafac45f79e21be5159fd'})
    executable = {str(REPO/relative): (frozen, live, custody[name]['original_snapshot'])
                  for name, (relative, frozen, live) in TRANSPORT.items()}
    test = review['nonexecuting_test_configuration']
    for path, frozen in design['sources'].items():
        if path in executable:
            need(executable[path][0] == frozen, 'ORIGINAL_EXECUTABLE_SNAPSHOT_FREEZE_CHANGED')
        elif Path(path).name == 'pytest.ini':
            need(test['original_snapshot']['sha256'] == frozen and test['executed'] is False,
                 'ORIGINAL_NONEXECUTING_TEST_CUSTODY_REQUIRED')
            pin(test['live'], path=path); pin(test['original_snapshot'], path=RUN/'source_snapshot/pytest.ini', expected=frozen)
        elif path in correction['source_changes']:
            change = correction['source_changes'][path]
            need(change['original_sha256'] == frozen and review['source_pins'].get(path) == change['corrected_sha256'],
                 'ONLY_EXISTING_POSTFIT_OWNER_CORRECTION_ALLOWED')
            pin(change['original_snapshot'], expected=frozen)
            pin({'path': path, 'sha256': change['corrected_sha256']})
        else:
            pin({'path': path, 'sha256': frozen})
    for path, h in review['source_pins'].items():
        pin({'path': path, 'sha256': h})


def validate_d01(artifacts, journal, dates, source_review_ref):
    names = {'assembly': 'MEMBERSHIP_ASSEMBLY.json', 'receipts': 'MEMBERSHIP_RECEIPTS.json',
             'panel': 'scores_pre2026.parquet', 'predicted_risk': 'predicted_risk_pre2026.parquet'}
    need(set(artifacts) == set(names), 'ALL_FOUR_D01_ARTIFACT_PINS_REQUIRED')
    for key, name in names.items():
        pin(artifacts[key], path=ROOT/'C14_D01'/name)
    assembly = read(artifacts['assembly'])
    need(assembly.get('status') == 'MEMBERSHIP_COMPLETE' and assembly.get('role') == 'C14_D01'
        and assembly.get('calendar_dates') == 752 and assembly.get('failure') is None
        and assembly.get('source_review') == source_review_ref and assembly.get('scientific_retry') == 0
        and assembly.get('forecast2026_rows') == 0, 'EXACT_COMPLETED_D01_ASSEMBLY_REQUIRED')
    receipts = read(artifacts['receipts'])
    need(len(receipts) == 752 and [r['signal_date'] for r in receipts] == list(dates), 'ALL752_D01_OPAQUE_RECEIPTS')
    for row in receipts:
        token = 'CLASSICAL|C14_D01|' + row['signal_date']
        need(token in journal['requests'] and digest(row['result']) == journal['requests'][token]['result_sha256'],
             'D01_ARTIFACT_RECEIPT_DIFFERS_FROM_CHARGED_COMPLETE_CACHE')
    return assembly


def validate_rx_artifacts(role, nodes, failure_path):
    for base in (ROOT/role, RUN/'models'/role, RUN/'models/risk_hybrids'/role):
        if base.exists():
            allowed = {failure_path.resolve()} if base == ROOT/role else set()
            need(all(f.resolve() in allowed for f in base.rglob('*') if f.is_file()),
                 'RX_MODEL_OR_PREDICTION_ARTIFACT_FORBIDDEN')
    for node in nodes:
        # Original hybrid.node_mapper names this exact model/scaler destination.
        model = RUN/'risk_execution/models'/(digest(node) + '.joblib')
        need(not model.exists() and not list(model.parent.glob(model.name + '.*')),
             'ORIGINAL_RX_NODE_ARTIFACT_FORBIDDEN')
    need(not list((RUN/'predictions').glob('*' + role + '*')), 'RX_PREDICTION_ARTIFACT_FORBIDDEN')


def validate_publication_failure(values, review):
    failure, marker, pipeline = (values[k] for k in
        ('publication_failure', 'prior_checkpoint_marker', 'pipeline'))
    need(failure.get('schema') == 'C14_CHECKPOINT_PRE_DATA_PUBLICATION_CLOSURE_FAILURE_V1'
        and failure.get('status') == 'ENGINEERING_FAILURE_BEFORE_ANY_NEW_BUSINESS_INPUT_OR_SCIENTIFIC_ENTRY'
        and failure.get('research_id') == ID and failure.get('exact_error_type') == 'RiskBindingBlocked'
        and failure.get('exact_error') == 'EXACT_FORMAL_R5_CODE_CLOSURE_REQUIRED', 'ONLY_EXACT_PRE_DATA_PUBLICATION_FAILURE_RECOVERABLE')
    expected_counts = dict(raw_metadata_projection=0, native_numeric_read=0, labels_read=0,
        new_fit=0, new_solve_charge=0, new_bootstrap=0)
    need(failure.get('new_attempt_only_counts') == expected_counts
        and all(type(v) is int for v in failure['new_attempt_only_counts'].values())
        and failure.get('original_qualification_reads_historical') == 330
        and failure.get('original_complete_caches_preserved') == EXPECTED_SOLVES
        and all(failure.get(k) is True for k in ('original_RX28_blocks_preserved', 'no_terminal',
            'one_shot_marker_preserved', 'all_three_B_frozen_hashes_equal_C_actual_executed_snapshot_hashes'))
        and type(failure.get('scientific_retry')) is int and failure['scientific_retry'] == 0,
        'EXACT_ZERO_NEW_ENTRY_FAILURE_PROOF_REQUIRED')
    expected_delta = dict(review['pause_delta'], actions=dict(HEADER=1, ACTIVATE_ROLE=8,
        BLOCK_REMAINING=2, SOLVE_ENTER=978, SOLVE_COMPLETE=978))
    need(failure.get('sole_delta') == expected_delta and failure.get('B_code_pin_count') == 29
        and set(failure.get('B_changed_live_sources', [])) == {Path(v[0]).name for v in TRANSPORT.values()},
        'UNCHANGED_FAILED_PUBLICATION_DELTA_AND_CLOSURE_REQUIRED')
    for key, (path, h) in FAILURE_REFS.items():
        pin(failure[key], path=path, expected=h)
    need(marker.get('status') == 'STARTED_CLASSICAL_ONLY_CHECKPOINT_CONTINUATION'
        and marker.get('research_id') == ID and marker.get('review') == review['prior_checkpoint_review']
        and marker.get('prior_delta') == review['pause_delta'] and marker.get('scientific_retry') == 0
        and marker.get('RX_reopened') is False and pipeline.get('status') == 'CLASSICAL_CHECKPOINT_CONTINUATION_RUNNING'
        and pipeline.get('phase') == 'ADMITTED_PRE_INPUT' and pipeline.get('review_ref') == marker['review']
        and pipeline.get('execution_native_reads_started') is False
        and pipeline.get('exact_complete_cache_counts') == EXPECTED_SOLVES
        and pipeline.get('preserved_engineering_blocked_fit_slots') == 28,
        'EXACT_FAILED_R1_MARKER_AND_PRE_INPUT_PIPELINE_REQUIRED')
    stderr = Path(failure['stderr']['path']).read_text(encoding='utf-8')
    need('line 617, in resume' in stderr and 'publication = execution.binding.read_publication_metadata()' in stderr
        and 'line 900, in read_publication_metadata' in stderr
        and stderr.rstrip().endswith('RiskBindingBlocked: EXACT_FORMAL_R5_CODE_CLOSURE_REQUIRED'),
        'EXACT_PRE_DATA_FAILED_TRACE_REQUIRED')
    pin(failure['stderr'])


def admit(review_ref):
    """All hard gates before imports of business owners or numerical reads."""
    need(not _CUSTODY, 'ADMISSION_IS_SINGLE_USE_IN_THIS_PROCESS')
    need(sys.dont_write_bytecode, 'CANONICAL_PYTHON_MINUS_B_REQUIRED')
    no_other_worker()
    need(not (ROOT/MARKER).exists() and not (ROOT/AUDIT).exists()
        and not (ROOT/'CHECKPOINT_CLASSICAL_RESUME_COMPLETE_R1.json').exists()
        and not (ROOT/'RISK_DECISIONS_TERMINAL_R1.json').exists(), 'ONE_SHOT_UNFINISHED_CHECKPOINT_ONLY')
    review = read(review_ref, path=REVIEW_PATH)
    fields = {'schema', 'status', 'research_id', 'classification', 'independent_review',
        'scientific_contract_changed', 'scientific_retry', 'test2026_rows_read', 'source_pins',
        *PINS, 'pause_delta', 'D01_artifacts', 'snapshot_transport'}
    need(set(review) == fields and review['schema'] == SCHEMA and review['status'] == 'PASS'
        and review['research_id'] == ID and review['classification'] == 'CHECKPOINT_CLASSICAL_ONLY'
        and review['independent_review'] is True and review['scientific_contract_changed'] is False
        and type(review['scientific_retry']) is int and review['scientific_retry'] == 0
        and type(review['test2026_rows_read']) is int and review['test2026_rows_read'] == 0,
        'INDEPENDENT_CLASSICAL_ONLY_RECOVERY_REVIEW_REQUIRED')
    own = Path(__file__).resolve()
    tests = REPO/'tests/research/a2/evaluation/test_selector_maximal_risk_resume.py'
    need(set(review['source_pins']) == {str(own), str(tests)}, 'EXACT_NEW_ENTRY_AND_SYNTHETIC_TEST_SOURCE_PINS')
    for p, h in review['source_pins'].items():
        pin({'path': p, 'sha256': h})
    values = {key: read(review[key], path=path, expected=h) for key, (path, h) in PINS.items()}
    config, original = values['original_config'], values['original_review']
    need(config['source_review'] == review['original_review'] and values['prior_started']['config'] == review['original_config']
        and values['prior_started']['review'] == review['original_review']
        and values['pause_receipt'].get('status') == 'PAUSED_BY_EXPLICIT_HUMAN_REQUEST', 'PAUSE_STARTED_CONFIG_CHAIN_REQUIRED')
    delta = review['pause_delta']
    need(delta == dict(path=str(RUN/'RISK_EXECUTION_DELTA.jsonl'), sha256=DELTA_SHA,
                      bytes=DELTA_BYTES, lines=DELTA_LINES), 'EXACT_FULL_PAUSE_DELTA_PIN_REQUIRED')
    validate_publication_failure(values, review)
    delta_ref = {k: delta[k] for k in ('path', 'sha256')}; delta_path = pin(delta_ref)
    journal = audit_delta(delta_path.read_bytes()); pin(delta_ref)
    validate_transport(review['snapshot_transport'])
    design = read(dict(path=str(RUN/'DESIGN_FREEZE.json'), sha256='8bdcabcc09817691741d8aaaf7baab8ba663e0360e13cc62b9d918208ff901b6'))
    original_source_custody(design, original, review['snapshot_transport'])
    matrix, current = read(config['requirement_matrix']), read(config['current_bindings'])['bindings']
    gates = validate_qualification(values['qualification'], matrix, current, review['original_review'], journal['activations'])
    d01 = validate_d01(review['D01_artifacts'], journal, matrix['roles'][0]['required_dates'], review['original_review'])
    failures = {}
    for role in RX:
        p = ROOT/role/'ENGINEERING_FAILURE_R1.json'
        value = read(dict(path=str(p), sha256=FAILURE_SHA))
        need(value.get('error_type') == 'ValueError' and value.get('error', '').startswith('PIN_CHANGED:')
            and 'continuous_research_account.py' in value['error'], 'ONLY_ORIGINAL_PREFIT_SOURCE_DRIFT_FAILURE')
        failures[role] = value
        # No fitted state or predictions may have appeared after this zero-entry failure.
        validate_rx_artifacts(role, journal['blocks'][role]['nodes'], p)
    for role in (*CLASSICAL[1:], 'C14_G1', 'C14_G4'):
        need(not (ROOT/role).exists(), 'UNEXPECTED_PARTIAL_OR_EXISTING_ROLE_ARTIFACT')
    need(not (ROOT/'MEMBERSHIP_ASSEMBLY.json').exists(), 'UNEXPECTED_EXISTING_MEMBERSHIP_ASSEMBLY')
    no_other_worker()
    verify_custody()
    return dict(review_ref=deepcopy(review_ref), review=review, values=values, config=config,
        original=original, matrix=matrix, current=current, gates=gates, journal=journal, d01=d01, failures=failures)


def assert_module(module, name, snapshot):
    p = Path(snapshot).resolve()
    need(sys.modules.get(name) is module and Path(module.__file__).resolve() == p
        and module.__spec__.name == name and Path(module.__spec__.origin).resolve() == p
        and module.__package__ == name.rpartition('.')[0]
        and Path(module.__loader__.path).resolve() == p, 'CANONICAL_SNAPSHOT_MODULE_ORIGIN_REQUIRED')
    parent = sys.modules[name.rpartition('.')[0]]
    need(getattr(parent, name.rpartition('.')[2], None) is module, 'CANONICAL_PARENT_MODULE_IDENTITY_REQUIRED')


def function_origin(module, names, path):
    for name in names:
        function = getattr(module, name)
        need(function.__module__ == module.__name__
            and Path(function.__code__.co_filename).resolve() == Path(path).resolve()
            and function.__globals__ is module.__dict__, 'CANONICAL_FUNCTION_CODE_ORIGIN_REQUIRED')


def load_snapshots(custody):
    """Execute the actual immutable bytes under original canonical module names."""
    validate_transport(custody)
    pollution = ('scripts.research.a2.training.selector_maximal_breadth',
        'scripts.research.a2.evaluation.selector_maximal_risk_execution',
        'scripts.research.a2.evaluation.selector_account_compare', FAST_NAME, POLICY_NAME, OPT_NAME, *TRANSPORT)
    need(not any(name in sys.modules for name in pollution), 'COLD_PROCESS_SNAPSHOT_ADMISSION_REQUIRED')
    for path, h in ((FAST_PATH, FAST_SHA), (POLICY_PATH, POLICY_SHA), (OPT_PATH, OPT_SHA)):
        pin(dict(path=str(path), sha256=h))
    modules = {}
    for name in TRANSPORT:  # CA, account, then joint; all import their canonical dependencies.
        parent_name, _, leaf = name.rpartition('.')
        parent = importlib.import_module(parent_name)
        need(not hasattr(parent, leaf), 'PARENT_CONFLICTING_MODULE_ALIAS_FORBIDDEN')
        path = pin(custody[name]['original_snapshot'])
        code = path.read_bytes(); pin(custody[name]['original_snapshot'])
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        setattr(parent, leaf, module)
        exec(compile(code, str(path), 'exec'), module.__dict__)
        assert_module(module, name, path)
        modules[name] = module
    ca, account, joint = modules[CA_NAME], modules[ACCOUNT_NAME], modules[JOINT_NAME]
    function_origin(ca, ('apply_transition_to_positions', 'apply_entitlement_lifecycle',
        '_entitlement_effective_day', '_entitlement_pay_date'), ca.__file__)
    function_origin(account, ('_engine_with_entitlement_hook',), account.__file__)
    need(ca.CorporateActionTransition.__module__ == ca.__name__
        and account.PersistentPolicyContext.__module__ == account.__name__, 'CANONICAL_SNAPSHOT_CLASS_ORIGIN_REQUIRED')
    for symbol in ('CorporateActionTransitionAdapter', 'apply_transition_to_positions',
        'SourceBackedEntitlementEvent', 'SourceBackedTerminalEvent', 'EntitlementLifecycleState',
        'apply_entitlement_lifecycle', 'RAW_OLD_SHARE_COORDINATE', '_entitlement_effective_day', '_entitlement_pay_date'):
        need(getattr(account, symbol) is getattr(ca, symbol), 'ACCOUNT_CANONICAL_CA_SYMBOL_REQUIRED')
    fast = importlib.import_module(FAST_NAME)
    pin(dict(path=str(FAST_PATH), sha256=FAST_SHA))
    assert_module(fast, FAST_NAME, FAST_PATH)
    function_origin(fast, ('run_many',), FAST_PATH)
    need(all(getattr(fast, k).__module__ == FAST_NAME for k in ('MarketArrays', 'TargetDecision')),
         'ORIGINAL_FAST_ACCOUNT_TYPE_ORIGIN_REQUIRED')
    need(account._common_engine is fast and all(getattr(account, k) is getattr(fast, k)
        for k in ('MarketArrays', 'TargetDecision', 'run_many')), 'ORIGINAL_FAST_ACCOUNT_DEPENDENCY_IDENTITY_REQUIRED')
    policy, optimization = importlib.import_module(POLICY_NAME), importlib.import_module(OPT_NAME)
    for module, name, path, h in ((policy, POLICY_NAME, POLICY_PATH, POLICY_SHA),
            (optimization, OPT_NAME, OPT_PATH, OPT_SHA)):
        pin(dict(path=str(path), sha256=h))
        assert_module(module, name, path)
    function_origin(policy, ('_support_projection', '_capped_mass', '_covariance_action'), POLICY_PATH)
    function_origin(optimization, ('_smooth_cvar', 'project_budget'), OPT_PATH)
    need(policy.JointResearchPolicy.__module__ == POLICY_NAME
        and policy.InfeasiblePolicy.__module__ == POLICY_NAME, 'ORIGINAL_JOINT_POLICY_TYPE_ORIGIN_REQUIRED')
    function_origin(joint, ('_hrp', 'allocate_q', 'exposure', '_v24_call'), joint.__file__)
    need(all(getattr(joint, k).__module__ == JOINT_NAME for k in
        ('AllocationUnavailable', 'AllocationResult', 'JointAllocationPolicy', 'TradingControlPolicy')),
        'CANONICAL_JOINT_SNAPSHOT_TYPE_ORIGIN_REQUIRED')
    need(all(getattr(joint, k) is getattr(policy, k) for k in
        ('JointResearchPolicy', 'InfeasiblePolicy', 'EPS', '_support_projection', '_capped_mass', '_covariance_action'))
        and joint._smooth_cvar is optimization._smooth_cvar and joint.TargetDecision is fast.TargetDecision
        and policy.TargetDecision is fast.TargetDecision and policy.project_budget is optimization.project_budget,
        'ORIGINAL_JOINT_SNAPSHOT_DEPENDENCY_IDENTITIES_REQUIRED')
    verify_custody()
    return modules


def verify_downstream_bindings(modules, compare, execution):
    ca, account, joint = modules[CA_NAME], modules[ACCOUNT_NAME], modules[JOINT_NAME]
    need(compare.engine is account and compare.CorporateActionTransition is ca.CorporateActionTransition,
         'DOWNSTREAM_ACCOUNT_AND_CA_CANONICAL_IDENTITIES_REQUIRED')
    need(importlib.import_module(JOINT_NAME) is joint, 'DOWNSTREAM_JOINT_CANONICAL_IDENTITY_REQUIRED')
    assert_module(joint, JOINT_NAME, joint.__file__)
    function_origin(joint, ('_hrp',), joint.__file__)
    owner = importlib.import_module(MEMBERSHIP_NAME)
    need(execution.binding.membership is owner, 'DOWNSTREAM_ORIGINAL_MEMBERSHIP_OWNER_REQUIRED')
    assert_module(owner, MEMBERSHIP_NAME, MEMBERSHIP_PATH)
    function_origin(owner, ('_hierarchical',), MEMBERSHIP_PATH)
    # D11 imports _hrp locally. Verify that actual compiled owner route without
    # calling a decision, allocating a portfolio or reading a business payload.
    code = list(dis.get_instructions(owner._hierarchical))
    need(any(a.opname == 'IMPORT_NAME' and a.argval == JOINT_NAME
        and b.opname == 'IMPORT_FROM' and b.argval == '_hrp'
        and c.opname == 'STORE_FAST' and c.argval == '_hrp'
        for a, b, c in zip(code, code[1:], code[2:])), 'DOWNSTREAM_D11_CANONICAL_HRP_IMPORT_REQUIRED')


def publication_metadata_preflight(execution, admission, modules):
    """Original source-only reader; three logical code refs name executed bytes.

    This isolated namespace does not change binding.sha or any metadata/native
    reader. Live hashes remain separately truthful dual-custody evidence.
    """
    binding = execution.binding
    path = Path(binding.__file__).resolve()
    expected = admission['original']['source_pins'][str(path)]
    pin(dict(path=str(path), sha256=expected))
    function_origin(binding, ('read_publication_metadata',), path)
    freeze = admission['values']['B_freeze']
    prior = admission['values']['original_publication_admission']
    original_refs = prior.get('publication_refs', {})
    need(prior.get('schema') == 'C14_R5_PUBLICATION_ADMISSION_R3'
        and prior.get('research_id') == ID and prior.get('status') == 'SOURCE_ONLY_PUBLICATION_QUALIFIED'
        and prior.get('numeric_execution_performed') is False
        and prior.get('strict_PIT_promotion_eligible') is False
        and set(prior.get('counts', {})) == set(binding.COUNTERS)
        and all(type(v) is int and v == 0 for v in prior['counts'].values())
        and set(original_refs) == {'plan', 'support', 'source_authority', 'model_producer', 'execution_producer',
            'bank', 'freeze', 'qualification', 'ledger'}
        and original_refs['freeze'] == admission['review']['B_freeze']
        and Path(original_refs['bank']['path']) == B_RUN/'models/risk/EVENT_RISK_BANK_R5.json',
        'EXACT_PRIOR_SOURCE_ONLY_PUBLICATION_IDENTITY_REQUIRED')
    for ref in original_refs.values():
        pin(ref)
    rows = freeze.get('source_code_pins', [])
    closure = {str(safe_path(r['path'])): r['sha256'] for r in rows}
    need(len(rows) == len(closure) == 29 and all(Path(p).is_relative_to(REPO)
        and Path(p).suffix == '.py' for p in closure), 'EXACT_ORIGINAL_B29_CODE_REF_CLOSURE_REQUIRED')
    custody = admission['review']['snapshot_transport']
    validate_transport(custody)
    mapped, evidence = {}, {}
    for name, (relative, frozen, _) in TRANSPORT.items():
        canonical = str(REPO/relative)
        need(closure.get(canonical) == frozen, 'B_FROZEN_CODE_REF_MUST_EQUAL_EXECUTED_SNAPSHOT')
        assert_module(modules[name], name, custody[name]['original_snapshot']['path'])
        mapped[canonical] = name
        evidence[name] = dict(logical_canonical_code_ref=dict(path=canonical, sha256=frozen),
            actual_live_source_ref=deepcopy(custody[name]['live']),
            actual_executed_snapshot_ref=deepcopy(custody[name]['original_snapshot']))
    for p, h in closure.items():
        if p not in mapped:
            pin(dict(path=p, sha256=h))
    metadata = {str(Path(original_refs[k]['path'])): original_refs[k]['sha256'] for k in ('freeze', 'bank')}
    need(not set(metadata).intersection(closure) and len(set(metadata) | set(closure)) == 31,
         'EXACT_31_SOURCE_ONLY_READER_SHA_DOMAIN_REQUIRED')
    observed = Counter()
    original_sha = binding.sha
    def code_ref_sha(value):
        p = str(safe_path(value))
        need(p in closure or p in metadata, 'PUBLICATION_CODE_REF_TRANSPORT_DOMAIN_FORBIDDEN')
        if p not in mapped:
            actual = original_sha(value)
            if p in closure:
                need(actual == closure[p], 'ORIGINAL_B26_PHYSICAL_SOURCE_PIN_CHANGED')
            else:
                need(actual == metadata[p], 'ORIGINAL_PUBLICATION_METADATA_PIN_CHANGED')
            return actual
        name = mapped[p]
        validate_transport(custody)
        module = modules[name]
        assert_module(module, name, custody[name]['original_snapshot']['path'])
        function_origin(module, {CA_NAME: ('apply_transition_to_positions',),
            ACCOUNT_NAME: ('_engine_with_entitlement_hook',), JOINT_NAME: ('_hrp',)}[name], module.__file__)
        observed[name] += 1
        return sha(custody[name]['original_snapshot']['path'])
    reader = execution.membership.event.bind_pinned_kernel(binding.read_publication_metadata,
        physical_path=path, expected_sha256=expected, dependencies={'sha': code_ref_sha})
    need(binding.sha is original_sha and reader.__code__ is binding.read_publication_metadata.__code__,
         'ORIGINAL_PUBLICATION_READER_CODE_AND_GLOBAL_SHA_UNCHANGED')
    publication = reader()
    need(observed == Counter({name: 1 for name in TRANSPORT}), 'ALL_THREE_CODE_REF_TRANSPORTS_OBSERVED_EXACTLY_ONCE')
    need(publication.get('status') == 'SOURCE_ONLY_PUBLICATION_QUALIFIED'
        and publication.get('numeric_execution_performed') is False
        and publication.get('publication') is not None
        and all(type(v) is int and v == 0 for v in publication.get('counts', {}).values())
        and set(publication.get('counts', {})) == set(binding.COUNTERS), 'COMPLETE_ORIGINAL_SOURCE_ONLY_PUBLICATION_PREFLIGHT_REQUIRED')
    need(type(publication['publication']) is binding.PublicationBinding, 'ORIGINAL_SEALED_PUBLICATION_OBJECT_REQUIRED')
    need(publication['publication'].refs == original_refs, 'ORIGINAL_PUBLICATION_ALL_NINE_REFS_MUST_MATCH')
    publication['publication'].verify()
    for ref in publication['publication'].refs.values():
        pin(ref)
    need(binding.sha is original_sha, 'ORIGINAL_BINDING_SHA_GLOBAL_MUST_REMAIN_UNCHANGED')
    verify_custody()
    proof = dict(status='ORIGINAL_B29_LOGICAL_CODE_REFS_BOUND_TO_ACTUAL_EXECUTED_SOURCES',
        B_freeze=admission['review']['B_freeze'], original_publication_admission=admission['review']['original_publication_admission'],
        code_ref_count=29, original_physical_code_refs=26,
        transported_code_refs=evidence, transport_observation_counts=dict(observed),
        original_reader_code_reused=True, original_binding_sha_global_unchanged=True,
        original_metadata_qualification_chain_reused=True, native_numeric_reads=0,
        label_reads=0, fit=0, solve=0, bootstrap=0)
    return publication, proof


@contextmanager
def executable_snapshot_guard(execution, custody, modules):
    """Transport exactly three executable pins only when their true modules match."""
    original = execution.ctl.checked_sources
    def checked(run, design):
        need(Path(run).resolve() == RUN, 'ORIGINAL_RUN_ONLY')
        validate_transport(custody)
        mapped = deepcopy(design)
        old_keys, new_keys = set(), set()
        for name, (relative, frozen, _) in TRANSPORT.items():
            old, new = str(REPO/relative), custody[name]['original_snapshot']['path']
            assert_module(modules[name], name, new)
            need(mapped['sources'].get(old) == frozen and new not in mapped['sources'], 'EXACT_FROZEN_EXECUTABLE_PIN_REQUIRED')
            mapped['sources'][new] = mapped['sources'].pop(old)
            old_keys.add(old); new_keys.add(new)
        need(len(mapped['sources']) == len(design['sources'])
            and {p:h for p,h in mapped['sources'].items() if p not in new_keys} ==
                {p:h for p,h in design['sources'].items() if p not in old_keys}, 'EVERY_OTHER_EXECUTABLE_GUARD_PRESERVED')
        return original(run, mapped)
    execution.ctl.checked_sources = checked
    try:
        yield
    finally:
        execution.ctl.checked_sources = original


def restore_input_gates(inputs, gates, execution, *, prior_review_ref=None):
    """Closed metadata restore; the original owner still verifies every real load."""
    need(type(inputs) is execution.input_owner.RiskInputs and inputs._qualified is False
        and inputs._gates == {} and inputs._cache == {} and inputs._failed == {}
        and all(type(v) is int and v == 0 for v in inputs.counts.values()), 'PRISTINE_ORIGINAL_INPUT_OWNER_REQUIRED')
    inputs._verify(full=True)
    gate_review = inputs.review_ref
    if prior_review_ref is not None:
        need(_TERMINAL_AUTHORITY is not None, 'TERMINAL_AUTHORITY_REQUIRED_FOR_PRIOR_GATES')
        authority = read(_TERMINAL_AUTHORITY, path=TERMINAL_REVIEW_PATH)
        terminal_review_contract(authority)
        runtime_ref = authority['runtime_source_review']
        runtime_path = RUN/'RISK_INPUT_SOURCE_REVIEW_R4.json'
        if _POST_REBOOT_AUTHORITY is not None:
            checkpoint = read(_POST_REBOOT_AUTHORITY, path=POST_REBOOT_REVIEW_PATH)
            post_reboot_review_contract(checkpoint)
            need(checkpoint['original_source_guard_review'] == _TERMINAL_AUTHORITY
                and checkpoint['prior_runtime_source_review'] == runtime_ref,
                'EXACT_POST_REBOOT_GATE_AUTHORITY_REQUIRED')
            runtime_ref = checkpoint['runtime_source_review']
            runtime_path = RUN/'RISK_INPUT_SOURCE_REVIEW_R5.json'
        need(prior_review_ref == authority['original_source_review']
            and prior_review_ref == dict(path=str(PINS['original_review'][0]),sha256=PINS['original_review'][1])
            and inputs.review_ref == runtime_ref
            and digest(inputs.review) == digest(read(runtime_ref,path=runtime_path))
            and inputs.review.get('prior_source_review') == prior_review_ref
            and inputs.review.get('prior_input_qualification') == authority['qualification']
            and digest(gates) == digest(read(authority['qualification'],path=PINS['qualification'][0],
                expected=PINS['qualification'][1])['roles']), 'EXACT_REVIEWED_PRIOR_GATE_TRANSPORT_REQUIRED')
        gate_review = prior_review_ref
    need(set(gates) == set(inputs.requirements)
        and all(g['source_review'] == gate_review and g['role'] == r for r,g in gates.items()),
        'EXACT_ADMITTED_PRIOR_GATES_ONLY')
    inputs._gates = deepcopy(gates)
    inputs._qualified = True
    inputs._verify(full=True)
    need(all(v == 0 for v in inputs.counts.values()), 'METADATA_RESTORE_CANNOT_CHARGE_NATIVE_REPLAY')


def preserved_hybrid_results(failures):
    return [dict(status='HYBRID_FAILED_UNTESTABLE', complete_candidates=[],
        failed_or_untestable={role: value['error_type'] + ':' + value['error']}, panels={}, native_pair_predictions={})
        for role, value in failures.items()]


def completed_d01_result(admission, q):
    artifacts = admission['review']['D01_artifacts']
    panel = dict(artifacts['panel'], rows=q['artifacts']['raw_current']['rows'], calendar_dates=752,
                 common_rows=q['artifacts']['raw_current']['rows'], raw_fallback_2023_exact=False)
    risk = dict(artifacts['predicted_risk'], rows=752)
    return dict(complete_candidates=['C14_D01'], failed_or_untestable={}, panels={'C14_D01': panel},
        native_pair_predictions={}, predicted_risk={'C14_D01': risk}, variance_diagnostics={'C14_D01': risk},
        roles={'C14_D01': admission['d01']})


def bind_runtime_custody(journal):
    """Original journal owns ongoing checks; native loads retain their own SHA gate."""
    mutable = {str(RUN/'RISK_EXECUTION_DELTA.jsonl'), str(ROOT/'PIPELINE_STATE.json'),
               str(TERMINAL_ROOT/'PIPELINE_STATE.json')}
    verify_custody()
    for path, (_, expected) in _CUSTODY.items():
        p = Path(path)
        if path in mutable or p.is_relative_to(B_RUN/'models/risk'):
            continue
        journal.pin(p, expected)
    journal.verify()


def resume(review_ref, *, validate_only=False):
    admission = admit(review_ref)
    modules = load_snapshots(admission['review']['snapshot_transport'])
    execution = importlib.import_module('scripts.research.a2.evaluation.selector_maximal_risk_execution')
    compare = importlib.import_module('scripts.research.a2.evaluation.selector_account_compare')
    verify_downstream_bindings(modules, compare, execution)
    review = execution.reviewed_sources(admission['review']['original_review'])
    with execution.frozen_test_configuration(review), executable_snapshot_guard(execution,
            admission['review']['snapshot_transport'], modules):
        matrix, current = execution.validate_start(admission['config'], review)
        cfg, design, q = execution.ctl.checked(RUN)
        execution.evidence.validate_design(design)
        journal = execution.journal_owner.RiskJournal(RUN)
        need(journal.sequence == admission['journal']['sequence'] and journal.previous == admission['journal']['previous']
            and len(journal.requests) == 978 and all(s['entered'] == 0 for s in journal.slots.values())
            and sum(s['status'] == 'BLOCKED_DEPENDENCY' for s in journal.slots.values()) == 28
            and all(s['status'] in ('BLOCKED_DEPENDENCY', 'UNRESERVED') for s in journal.slots.values()),
            'REPLAYED_ORIGINAL_JOURNAL_ZERO_FIT_BOUNDARY_REQUIRED')
        for token, request in journal.requests.items():
            need(request['status'] == 'COMPLETE' and request['charged'] == 1
                and request['identity'] == admission['journal']['requests'][token]['identity']
                and request['result_sha256'] == admission['journal']['requests'][token]['result_sha256'],
                'ORIGINAL_JOURNAL_EXACT_COMPLETE_REPLAY_REQUIRED')
        for field in ('panel', 'predicted_risk'):
            execution.ctl.footer(admission['review']['D01_artifacts'][field])
        need(execution.pq.ParquetFile(admission['review']['D01_artifacts']['panel']['path']).metadata.num_rows == q['artifacts']['raw_current']['rows']
            and execution.pq.ParquetFile(admission['review']['D01_artifacts']['predicted_risk']['path']).metadata.num_rows == 752,
            'D01_COMPLETE_ARTIFACT_FOOTER_COUNTS_REQUIRED')
        no_other_worker()
        verify_custody()
        # Complete the actual original metadata chain before the new once marker.
        # The returned sealed object is reused below; no post-marker re-read.
        publication, publication_transport = publication_metadata_preflight(execution, admission, modules)
        bind_runtime_custody(journal)
        journal.verify()
        status = dict(status='PASS_CHECKPOINT_CLASSICAL_ONLY_ADMISSION', research_id=ID,
            historical_native_qualification_reads=330, restored_numeric_reads=0,
            exact_complete_cache_counts=EXPECTED_SOLVES, preserved_engineering_blocked_fit_slots=28,
            new_fit=0, new_risk_estimation=0, scientific_retry=0, test2026_rows_read=0,
            publication_metadata_preflight='SOURCE_ONLY_PUBLICATION_QUALIFIED',
            publication_source_transport=publication_transport,
            joint_delivery_completed=False, coverage_sufficient_claim_allowed=False)
        if validate_only:
            return status
        paths = execution.resolve(execution.ctl.REPO)
        execution.assert_safe_output_path(ROOT, kind='backtest', paths=paths)
        # Exclusive one-shot marker precedes every business table/native read and event.
        with (ROOT/MARKER).open('x', encoding='utf-8') as stream:
            json.dump(dict(status='STARTED_CLASSICAL_ONLY_CHECKPOINT_CONTINUATION', research_id=ID,
                review=review_ref, prior_delta=admission['review']['pause_delta'], current_time=execution.ctl.now(),
                prior_failed_marker=admission['review']['prior_checkpoint_marker'],
                publication_failure=admission['review']['publication_failure'],
                publication_source_transport=publication_transport,
                scientific_retry=0, RX_reopened=False), stream, indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        execution.stage(ROOT/'PIPELINE_STATE.json', 'CLASSICAL_CHECKPOINT_CONTINUATION_RUNNING',
            phase='ADMITTED_PRE_INPUT', review_ref=review_ref, exact_complete_cache_counts=EXPECTED_SOLVES,
            historical_qualification_native_reads=330, execution_native_reads_started=False,
            preserved_engineering_blocked_fit_slots=28, RX_reopened=False)
        raw_meta = execution.ctl.project(q['artifacts']['raw_current'], list(execution.current_owner.RAW_META),
            start='2023-01-01', stop='2026-01-01', run=RUN)
        inputs = execution.input_owner.RiskInputs(publication['publication'], matrix, current, raw_meta,
            source_review=review, source_review_ref=admission['review']['original_review'])
        restore_input_gates(inputs, admission['gates'], execution)
        execution.stage(ROOT/'PIPELINE_STATE.json', 'CLASSICAL_CHECKPOINT_CONTINUATION_RUNNING',
            phase='PRIOR_QUALIFICATION_METADATA_RESTORED', review_ref=review_ref, exact_complete_cache_counts=EXPECTED_SOLVES,
            historical_qualification_native_reads=330, execution_input_counts=inputs.status()['counts'],
            preserved_engineering_blocked_fit_slots=28, RX_reopened=False)
        for key in ('raw_current', 'pair_geometry'):
            execution.ctl.footer(q['artifacts'][key])
        raw = execution.pq.read_table(execution.ctl.pin(q['artifacts']['raw_current'])).to_pandas()
        geometry = execution.pq.read_table(execution.ctl.pin(q['artifacts']['pair_geometry'])).to_pandas()
        execution.ctl.require(raw.signal_date.lt('2026-01-01').all() and geometry.signal_date.lt('2026-01-01').all(),
                              'PREPARED_INPUT_PRE2026_LOCK')
        member = execution.membership
        need(tuple(member.ROLES) == (*CLASSICAL, 'C14_D02', 'C14_G1', 'C14_G4'), 'EXACT_FROZEN_MEMBERSHIP_ROSTER_REQUIRED')
        kernel = member.event.bind_pinned_kernel(member.execute_membership, physical_path=member.__file__,
            expected_sha256=review['source_pins'][str(Path(member.__file__).resolve())],
            dependencies={'ROLES': tuple(r for r in member.ROLES if r != 'C14_D01')})
        recovery = execution.read_exact(review['source_metadata_recovery_ref'])
        result = kernel(RUN, design, q, raw, geometry, matrix, inputs.get_risk, journal,
            admission['review']['original_review'], role_gates=inputs.status()['roles'],
            qualification_ref=admission['review']['qualification'], artifact_root=ROOT,
            raw_identity_ref=recovery['prior_refs']['membership'])
        results = [*preserved_hybrid_results(admission['failures']), completed_d01_result(admission, q), result]
        summary = execution.terminal(RUN, design, q, execution.read_exact(review['immutable_inputs']['ML_ASSEMBLY.json']),
            admission['values']['qualification'], results, journal, admission['review']['original_review'], artifact_root=ROOT)
        execution.stage(ROOT/'PIPELINE_STATE.json', summary['status'], terminal=execution.ref(ROOT/'RISK_DECISIONS_TERMINAL_R1.json'),
            joint_delivery_completed=False, coverage_sufficient_claim_allowed=False)
        audit = dict(status='CLASSICAL_ONLY_CHECKPOINT_CONTINUATION_TERMINAL', research_id=ID,
            review=review_ref, original_input_qualification=admission['review']['qualification'],
            historical_qualification_counts=admission['values']['qualification']['counts'],
            execution_input_counts=inputs.status()['counts'], terminal=execution.ref(ROOT/'RISK_DECISIONS_TERMINAL_R1.json'),
            reused_D01_artifacts=admission['review']['D01_artifacts'], original_complete_cache_counts=EXPECTED_SOLVES,
            prior_failed_marker=admission['review']['prior_checkpoint_marker'],
            publication_failure=admission['review']['publication_failure'], publication_source_transport=publication_transport,
            RX_reopened=False, preserved_engineering_blocked_fit_slots=28, scientific_retry=0,
            test2026_rows_read=0, joint_delivery_completed=False, coverage_sufficient_claim_allowed=False)
        execution.put(ROOT/AUDIT, audit)
        return summary



# A separate one-shot admission for the completed R2 worker. Original markers,
# terminals, gates and completed artifacts remain at their original paths.
TERMINAL_SCHEMA = 'C14_TERMINAL_SOURCE_GUARD_RECOVERY_V1'
TERMINAL_REVIEW_PATH = RUN/'C14_TERMINAL_SOURCE_GUARD_RECOVERY_REVIEW_R1.json'
TERMINAL_ROOT = RUN/'risk_execution/source_guard_recovery_r1'
TERMINAL_MARKER = 'SOURCE_GUARD_RECOVERY_STARTED_R1.json'
TERMINAL_AUDIT = 'SOURCE_GUARD_RECOVERY_COMPLETE_R1.json'
TERMINAL_SHA = 'f4ac7ecb650787b9695470080b4284f54333c2062278cc3b55a4794d6a208bf2'
TERMINAL_AUDIT_SHA = '52fe1ba01fc7273b7e6e482b3d689287da6939802e905dca822fef3de1c05f11'
TERMINAL_DELTA_SHA = '12c5f2a1866b6693d92985d73982db2e55bec1e0b166ee17cdf0261b6486d948'
TERMINAL_DELTA_BYTES, TERMINAL_DELTA_LINES = 13094104, 5597
TERMINAL_SOLVES = {'C14_D01':752, 'C14_D05':752, 'C14_D06':752, 'C14_D09':537}
TERMINAL_COMPLETE = ('C14_D01','C14_D05','C14_D06','C14_D02','C14_G1','C14_G4')
TERMINAL_CLASSICAL = ('C14_D09','C14_D10','C14_D11')
TERMINAL_SOURCE_BACKUPS = {
    'training/selector_maximal_risk_journal.py':'ab2ac39a22440892b1f99d8b9f2fbb70b28d260ec449e98349f9046ae48bd674',
    'evaluation/selector_maximal_risk_execution.py':'95d57d78291058e32f6620f861da46a3f3a902021399bfa5ea99d53dcc07866e',
    'training/selector_maximal_risk_hybrids.py':'aed6e06f59077a3dd8c665f17f44d382810bd125c766e2810e641d6c2b65e38d',
    'training/selector_maximal_risk_membership.py':'a2fec18c01cd7de3fb1c4eaad0cac0159942762b918877a038882f60fb680fe7',
}
TERMINAL_TRANSPORT = dict(TRANSPORT)
TERMINAL_TRANSPORT[ACCOUNT_NAME] = (
    TRANSPORT[ACCOUNT_NAME][0], TRANSPORT[ACCOUNT_NAME][1],
    'b7704332f208e9a1a7b9aa9cba75008f77da4d501193d8f6124a04b674562d4a')
_TERMINAL_AUTHORITY = None
_TERMINAL_TRANSPORT_SEAL = None


def terminal_review_contract(review):
    fields = {'schema','status','research_id','classification','independent_review',
        'scientific_contract_changed','scientific_retry','test2026_rows_read',
        'source_pins','source_backups','prior_resume_source','original_source_review',
        'runtime_source_review','original_config','qualification','prior_terminal',
        'prior_audit','prior_delta','snapshot_transport','recover_rx_nodes',
        'completed_artifacts','classical_failures','rx_failures','B_freeze',
        'original_publication_admission'}
    need(set(review) == fields and review['schema'] == TERMINAL_SCHEMA
        and review['status'] == 'PASS' and review['research_id'] == ID
        and review['classification'] == 'TERMINAL_BOUND_SOURCE_GUARD_ENGINEERING_ONLY'
        and review['independent_review'] is True
        and review['scientific_contract_changed'] is False
        and type(review['scientific_retry']) is int and review['scientific_retry'] == 0
        and type(review['test2026_rows_read']) is int and review['test2026_rows_read'] == 0,
        'INDEPENDENT_TERMINAL_SOURCE_GUARD_REVIEW_REQUIRED')


def terminal_completed_artifacts(assembly, declared):
    """Only physical artifact custody and metadata; no numerical table replay."""
    need(set(declared) == set(TERMINAL_COMPLETE), 'EXACT_SIX_COMPLETED_ROLES_REUSE_REQUIRED')
    result = dict(complete_candidates=list(TERMINAL_COMPLETE),failed_or_untestable={},
        panels={},native_pair_predictions={},predicted_risk={},variance_diagnostics={})
    for role in TERMINAL_COMPLETE:
        expected = {field:assembly[field][role] for field in
            ('panels','predicted_risk','variance_diagnostics')}
        need(declared[role] == expected and expected['panels'].get('calendar_dates') == 752
            and expected['predicted_risk'].get('rows') == 752
            and expected['predicted_risk'] == expected['variance_diagnostics'],
            'EXACT_COMPLETE_FULL752_ARTIFACT_METADATA_REQUIRED')
        for field, value in expected.items():
            path = safe_path(value['path'])
            need(path.is_relative_to(RUN/'risk_execution')
                and not path.is_relative_to(TERMINAL_ROOT) and path.suffix == '.parquet',
                'ONLY_PRIOR_COMPLETE_CONDITIONAL_ARTIFACTS_REUSED')
            pin({k:value[k] for k in ('path','sha256')})
            result[field][role] = deepcopy(value)
    return result


def admit_terminal_recovery(review_ref):
    """Metadata/opaque custody admission; no native, label, fit or solve call."""
    global _TERMINAL_AUTHORITY, _TERMINAL_TRANSPORT_SEAL
    need(not _CUSTODY and _TERMINAL_AUTHORITY is None, 'ADMISSION_IS_SINGLE_USE_IN_THIS_PROCESS')
    need(sys.dont_write_bytecode, 'CANONICAL_PYTHON_MINUS_B_REQUIRED')
    no_other_worker()
    need(not TERMINAL_ROOT.exists(), 'ONE_SHOT_NEW_SOURCE_GUARD_ROOT_REQUIRED')
    review = read(review_ref, path=TERMINAL_REVIEW_PATH)
    terminal_review_contract(review)
    source_paths = {str(REPO/'scripts/research/a2'/p) for p in TERMINAL_SOURCE_BACKUPS}
    own = str(Path(__file__).resolve())
    tests = str(REPO/'tests/research/a2/evaluation/test_selector_maximal_risk_resume.py')
    paired = {str(REPO/'tests/research/a2'/Path(p).parent/f'test_{Path(p).name}')
              for p in TERMINAL_SOURCE_BACKUPS}
    need(set(review['source_pins']) == source_paths | {own,tests} | paired
        and all(safe_path(p).is_relative_to(REPO) and Path(p).suffix == '.py'
                for p in review['source_pins']), 'EXACT_RECOVERY_SOURCE_AND_TEST_CLOSURE_REQUIRED')
    for p,h in review['source_pins'].items(): pin(dict(path=p,sha256=h))
    need(set(review['source_backups']) == source_paths, 'ONLY_FOUR_ORIGINAL_OWNER_SOURCE_BRIDGES')
    for relative, old_sha in TERMINAL_SOURCE_BACKUPS.items():
        live = str(REPO/'scripts/research/a2'/relative)
        pin(review['source_backups'][live],
            path=RUN/'source_corrections/C14_TERMINAL_SOURCE_GUARD_RECOVERY_R1'/relative,
            expected=old_sha)
    pin(review['prior_resume_source'],
        path=RUN/'source_corrections/C14_TERMINAL_SOURCE_GUARD_RECOVERY_R1/evaluation/selector_maximal_risk_resume.py',
        expected='90f46ae8d3470fbf59e52f1a5c938b422d8e4fe24de1306f7106dfed3bd406e6')
    fixed = dict(original_source_review=PINS['original_review'], original_config=PINS['original_config'],
        qualification=PINS['qualification'], B_freeze=PINS['B_freeze'],
        original_publication_admission=PINS['original_publication_admission'],
        prior_terminal=(ROOT/'RISK_DECISIONS_TERMINAL_R1.json',TERMINAL_SHA),
        prior_audit=(ROOT/AUDIT,TERMINAL_AUDIT_SHA))
    values = {k:read(review[k],path=p,expected=h) for k,(p,h) in fixed.items()}
    original = values['original_source_review']
    runtime = read(review['runtime_source_review'], path=RUN/'RISK_INPUT_SOURCE_REVIEW_R4.json')
    expected_runtime = deepcopy(original)
    for p in source_paths:
        need(original['source_pins'][p] == TERMINAL_SOURCE_BACKUPS[
            str(Path(p).relative_to(REPO/'scripts/research/a2')).replace('\\','/')],
            'ORIGINAL_R3_OWNER_SOURCE_HASH_CHANGED')
        expected_runtime['source_pins'][p] = review['source_pins'][p]
    expected_runtime['prior_source_review'] = review['original_source_review']
    expected_runtime['prior_input_qualification'] = review['qualification']
    need(digest(runtime) == digest(expected_runtime), 'ONLY_REVIEWED_FOUR_OWNER_RUNTIME_SOURCE_BRIDGE_ALLOWED')
    for ref in runtime['immutable_inputs'].values(): pin(ref)
    prior_review = read(dict(path=str(REVIEW_PATH),sha256='cd364aa71a026706d2c7c20b89d7101d9d6eba8815e5d18405c7c89f9e8e59b8'))
    pin(dict(path=str(ROOT/MARKER),sha256='076c382851deb2cc32f253cca5e90d027338976b77602e2d25c20062e2b48521'))
    for p,h in original['source_pins'].items():
        if p not in source_paths: pin(dict(path=p,sha256=h))
    _TERMINAL_AUTHORITY = deepcopy(review_ref)
    _TERMINAL_TRANSPORT_SEAL = digest(review['snapshot_transport'])
    validate_transport(review['snapshot_transport'])
    design = read(dict(path=str(RUN/'DESIGN_FREEZE.json'),
        sha256='8bdcabcc09817691741d8aaaf7baab8ba663e0360e13cc62b9d918208ff901b6'))
    original_source_custody(design,runtime,review['snapshot_transport'])
    for ref in design['inputs'].values(): pin({k:ref[k] for k in ('path','sha256')})
    freeze = read(dict(path=str(RUN/'FORMAL_FREEZE_RECEIPT.json'),
        sha256='00fa18f066358e6cf19f21b27b7bc048575830611e35786d87da55a67caa28f4'))
    prepared = read(dict(path=str(RUN/'INPUT_QUALIFICATION.json'),sha256=freeze['input_qualification_sha256']))
    for ref in prepared['artifacts'].values(): pin({k:ref[k] for k in ('path','sha256')})
    config = values['original_config']
    need(config['source_review'] == review['original_source_review'], 'ORIGINAL_CONFIG_SOURCE_REVIEW_CHANGED')
    matrix = read(config['requirement_matrix'])
    current = read(config['current_bindings'])['bindings']
    delta = review['prior_delta']
    need(delta == dict(path=str(RUN/'RISK_EXECUTION_DELTA.jsonl'),sha256=TERMINAL_DELTA_SHA,
        bytes=TERMINAL_DELTA_BYTES,lines=TERMINAL_DELTA_LINES), 'EXACT_COMPLETED_WORKER_DELTA_REQUIRED')
    raw = pin({k:delta[k] for k in ('path','sha256')}).read_bytes()
    journal = audit_terminal_delta(raw, matrix['roles'][0]['required_dates'])
    pin({k:delta[k] for k in ('path','sha256')})
    gates = validate_qualification(values['qualification'],matrix,current,
        review['original_source_review'],journal['activations'])
    terminal, audit = values['prior_terminal'], values['prior_audit']
    need(terminal['status'] == 'RISK_DECISIONS_TERMINAL_JOINT_DELIVERY_PENDING'
        and terminal['research_id'] == ID and terminal['review_ref'] == review['original_source_review']
        and terminal['input_qualification'] == review['qualification']
        and terminal['delta'] == {k:delta[k] for k in ('path','sha256')}
        and terminal['complete_conditional_roles'] == list(TERMINAL_COMPLETE)
        and terminal['charged_solves'] == 2793 and terminal['combined_charged_solves'] == 20799
        and terminal['reserved_fit_slots'] == terminal['blocked_fit_slots'] == 28
        and all(terminal[k] == 0 for k in ('backend_entered','complete_fit_slots','failed_fit_slots',
            'scientific_retry','new_risk_estimations','test2026_rows_read'))
        and terminal['joint_delivery_completed'] is False
        and terminal['coverage_sufficient_claim_allowed'] is False
        and terminal['strict_PIT_promotion_eligible'] is False, 'EXACT_ENGINEERING_TERMINAL_BOUNDARY_REQUIRED')
    need(audit['review'] == dict(path=str(REVIEW_PATH),sha256='cd364aa71a026706d2c7c20b89d7101d9d6eba8815e5d18405c7c89f9e8e59b8')
        and prior_review['original_review'] == review['original_source_review']
        and audit['status'] == 'CLASSICAL_ONLY_CHECKPOINT_CONTINUATION_TERMINAL'
        and audit['terminal'] == review['prior_terminal']
        and audit['original_input_qualification'] == review['qualification']
        and audit['RX_reopened'] is False and audit['preserved_engineering_blocked_fit_slots'] == 28,
        'ORIGINAL_RESUME_AUDIT_BOUNDARY_REQUIRED')
    assembly = read(terminal['assembly']); gate = read(terminal['final_pipeline'])
    need(assembly['conditional_delta_ref'] == terminal['delta']
        and gate['conditional_delta_ref'] == terminal['delta']
        and gate['score_assembly_sha256'] == terminal['assembly']['sha256']
        and all(gate[k] == 0 for k in ('forecast2026_rows','outer_labels_read')),
        'PRIOR_TERMINAL_CLOSURE_CHANGED')
    completed = terminal_completed_artifacts(assembly,review['completed_artifacts'])
    need(set(review['classical_failures']) == set(TERMINAL_CLASSICAL)
        and set(review['rx_failures']) == set(RX), 'ALL_FIVE_ORIGINAL_ENGINEERING_FAILURES_REQUIRED')
    for role in TERMINAL_CLASSICAL:
        failure = read(review['classical_failures'][role],path=ROOT/role/'MEMBERSHIP_ASSEMBLY.json')
        need(failure['status'] == 'MEMBERSHIP_FAILED' and failure['role'] == role
            and failure['failure'] == 'RiskJournalBlocked:PHYSICAL_AUTHORITY_CHANGED:continuous_research_account.py'
            and failure['source_review'] == review['original_source_review']
            and failure['scientific_retry'] == failure['forecast2026_rows'] == 0
            and list((ROOT/role).iterdir()) == [ROOT/role/'MEMBERSHIP_ASSEMBLY.json'],
            'ONLY_UNCOMMITTED_CLASSICAL_SOURCE_CUSTODY_FAILURE_RECOVERABLE')
        need(assembly['role_failure_details'][role] == failure['failure']
            and gate['role_failure_details'][role] == failure['failure'],
            'CLASSICAL_FAILURE_HISTORY_MUST_BE_PRESERVED')
    nodes = sorted(n for role in RX for n in journal['blocks'][role]['nodes'])
    need(review['recover_rx_nodes'] == nodes and len(nodes) == len(set(nodes)) == 28,
        'ALL_AND_ONLY_ORIGINAL_RX28_REQUIRED')
    for role in RX:
        p = ROOT/role/'ENGINEERING_FAILURE_R1.json'
        failure = read(review['rx_failures'][role],path=p,expected=FAILURE_SHA)
        need(failure['error_type'] == 'ValueError' and failure['error'].startswith('PIN_CHANGED:')
            and 'continuous_research_account.py' in failure['error'], 'EXACT_ORIGINAL_RX_PREFIT_SOURCE_ERROR')
        validate_rx_artifacts(role,journal['blocks'][role]['nodes'],p)
    no_other_worker(); verify_custody()
    return dict(review_ref=deepcopy(review_ref),review=review,values=values,original=original,
        runtime=runtime,config=config,matrix=matrix,current=current,gates=gates,
        journal=journal,completed=completed)

def _opaque_json_end(raw, start):
    """Find a value boundary without decoding economic string/number values."""
    need(start < len(raw), 'TRUNCATED_OPAQUE_JSON')
    char = raw[start]
    if char == 34:
        cursor = start + 1
        while cursor < len(raw):
            if raw[cursor] == 92: cursor += 2
            elif raw[cursor] == 34: return cursor + 1
            else:
                need(raw[cursor] >= 32, 'UNESCAPED_JSON_CONTROL_CHARACTER')
                cursor += 1
        raise ValueError('UNTERMINATED_OPAQUE_JSON_STRING')
    if char in (123,91):
        close = 125 if char == 123 else 93
        cursor = start + 1
        while cursor < len(raw):
            if raw[cursor] == close: return cursor + 1
            if raw[cursor] in (34,123,91): cursor = _opaque_json_end(raw,cursor)
            else: cursor += 1
        raise ValueError('UNTERMINATED_OPAQUE_JSON_CONTAINER')
    cursor = start
    while cursor < len(raw) and raw[cursor] not in (44,125,93): cursor += 1
    need(cursor > start, 'EMPTY_OPAQUE_JSON_VALUE')
    return cursor


def _opaque_object_fields(raw):
    """Raw canonical field spans; caller alone chooses metadata to decode."""
    need(raw[:1] == b'{' and raw[-1:] == b'}', 'EXACT_OPAQUE_JSON_OBJECT_REQUIRED')
    fields = {}; cursor = 1
    while cursor < len(raw)-1:
        need(raw[cursor] == 34, 'CANONICAL_JSON_FIELD_REQUIRED')
        key_end = _opaque_json_end(raw,cursor)
        key = json.loads(raw[cursor:key_end])
        need(isinstance(key,str) and key not in fields, 'DUPLICATE_JSON_FIELD')
        need(raw[key_end:key_end+1] == b':', 'CANONICAL_JSON_COLON_REQUIRED')
        start = key_end+1; end = _opaque_json_end(raw,start)
        fields[key] = raw[start:end]; cursor = end
        if cursor < len(raw)-1:
            need(raw[cursor:cursor+1] == b',', 'CANONICAL_JSON_COMMA_REQUIRED')
            cursor += 1
    need(cursor == len(raw)-1, 'EXACT_OPAQUE_JSON_OBJECT_END_REQUIRED')
    return fields


def audit_terminal_delta(raw, dates):
    """One reviewed canonical prefix; result values are hashed without decode."""
    need(raw.endswith(b'\n') and b'\r' not in raw and len(raw) == TERMINAL_DELTA_BYTES
        and hashlib.sha256(raw).hexdigest() == TERMINAL_DELTA_SHA, 'EXACT_TERMINAL_DELTA_PREFIX_REQUIRED')
    lines = raw.splitlines()
    need(len(lines) == TERMINAL_DELTA_LINES, 'EXACT_TERMINAL_DELTA_LINE_COUNT_REQUIRED')
    actions,activations,blocks,requests = Counter(),{},{},{}
    previous = '0'*64
    identity_fields = {'research_id','design_sha256','role','family','method','recipe_sha256',
        'risk_metadata_sha256','state_ref','risk_state_id','cutoff','as_of','decision_asof',
        'full_U_keys_sha256','pair_key_sha256','requirement_sha256','role_qualification_sha256'}
    for sequence,line in enumerate(lines):
        row = _opaque_object_fields(line)
        need(tuple(row) == ('action','data','previous','sequence','sha256'), 'EXACT_CANONICAL_DELTA_ROW_SCHEMA_REQUIRED')
        seq = json.loads(row['sequence'])
        prev,h = json.loads(row['previous']),json.loads(row['sha256'])
        stop = line.rfind(b',"sha256":')
        need(stop > 0 and type(seq) is int and seq == sequence and prev == previous
            and hashlib.sha256(line[:stop]+b'}').hexdigest() == h, 'TERMINAL_DELTA_HASH_CHAIN_CHANGED')
        previous = h; action = json.loads(row['action']); actions[action] += 1
        need(action in {'HEADER','ACTIVATE_ROLE','BLOCK_REMAINING','SOLVE_ENTER','SOLVE_COMPLETE'},
            'FIT_STARTED_FAILED_RX_CHARGE_OR_UNKNOWN_EVENT_FORBIDDEN')
        if action == 'HEADER':
            data = json.loads(row['data'])
            need(sequence == 0 and data.get('research_id') == ID and data.get('scientific_retry') == 0,
                'ORIGINAL_TERMINAL_DELTA_HEADER_REQUIRED')
        elif action == 'ACTIVATE_ROLE':
            data = json.loads(row['data']); role = data['role']
            need(role in ACTIVATED and role not in activations, 'EXACT_EIGHT_ACTIVATIONS_REQUIRED')
            activations[role] = data['qualification']
        elif action == 'BLOCK_REMAINING':
            data = json.loads(row['data']); role = data['role']
            need(role in RX and role not in blocks and len(data['nodes']) == len(set(data['nodes'])) == 14
                and data['reason'] == 'UNEXPECTED_ENGINEERING_FAILURE_BEFORE_UNUSED_FITS',
                'ONLY_TWO_ORIGINAL_PREFIT_ENGINEERING_BLOCKS')
            blocks[role] = data
        else:
            data = _opaque_object_fields(row['data']); token = json.loads(data['token'])
            parts = token.split('|')
            need(len(parts) == 3 and parts[0] == 'CLASSICAL' and parts[1] in CLASSICAL and parts[2] in dates,
                'EXACT_ORIGINAL_CLASSICAL_TOKEN_REQUIRED')
            if action == 'SOLVE_ENTER':
                need(tuple(data) == ('token',) and token not in requests, 'DUPLICATE_OR_CHANGED_SOLVE_ENTER')
                requests[token] = None
            else:
                need(tuple(data) == ('receipt','token') and token in requests and requests[token] is None,
                    'MATCHED_UNIQUE_ENTER_BEFORE_COMPLETE_REQUIRED')
                receipt = _opaque_object_fields(data['receipt'])
                need(tuple(receipt) == ('identity','result','result_sha256'), 'EXACT_CLASSICAL_COMPLETE_RECEIPT_SCHEMA_REQUIRED')
                result_sha = json.loads(receipt['result_sha256'])
                need(hashlib.sha256(receipt['result']).hexdigest() == result_sha,
                    'EXACT_OPAQUE_COMPLETE_CACHE_DIGEST_REQUIRED')
                need(set(_opaque_object_fields(receipt['identity'])) == identity_fields,
                    'ONLY_CLASSICAL_SOURCE_METADATA_IDENTITY_FIELDS_REQUIRED')
                requests[token] = dict(identity=json.loads(receipt['identity']),result_sha256=result_sha)
    need(actions == Counter(HEADER=1,ACTIVATE_ROLE=8,BLOCK_REMAINING=2,SOLVE_ENTER=2793,SOLVE_COMPLETE=2793)
        and set(activations) == set(ACTIVATED) and set(blocks) == set(RX)
        and all(v is not None for v in requests.values()), 'EXACT_TERMINAL_COMPLETE_ONLY_PREFIX_REQUIRED')
    counts = Counter(t.split('|')[1] for t in requests)
    need(dict(counts) == TERMINAL_SOLVES, 'EXACT_TERMINAL_CLASSICAL_COMPLETE_COUNTS_REQUIRED')
    need(sorted(t.rsplit('|',1)[1] for t in requests if t.startswith('CLASSICAL|C14_D09|')) == list(dates[:537]),
        'EXACT_INITIAL_D09_DATE_PREFIX_REQUIRED')
    return dict(activations=activations,blocks=blocks,requests=requests,counts=dict(counts),
        sequence=len(lines),previous=previous,actions=dict(actions))



def terminal_journal_boundary(journal, admission):
    need(journal.sequence == admission['journal']['sequence']
        and journal.previous == admission['journal']['previous']
        and len(journal.requests) == 2793
        and all(type(s['entered']) is int and s['entered'] == 0 for s in journal.slots.values())
        and sum(s['status'] == 'BLOCKED_DEPENDENCY' for s in journal.slots.values()) == 28
        and sum(s['status'] == 'UNRESERVED' for s in journal.slots.values()) == 116,
        'EXACT_TERMINAL_JOURNAL_ZERO_ENTRY_BOUNDARY_REQUIRED')
    for token, request in journal.requests.items():
        prior = admission['journal']['requests'].get(token)
        need(prior is not None and request['status'] == 'COMPLETE' and request['charged'] == 1
            and digest(request['identity']) == digest(prior['identity'])
            and request['result_sha256'] == prior['result_sha256'],
            'ALL2793_COMPLETE_CACHE_IDENTITIES_AND_DIGESTS_REQUIRED')
    data = dict(review_ref=admission['review_ref'],nodes=admission['review']['recover_rx_nodes'])
    journal._source_guard_zero_entry_state(data)
    journal._source_guard_artifact_absent(data['nodes'])
    journal.verify()


def resume_terminal_recovery(review_ref, *, validate_only=False):
    admission = admit_terminal_recovery(review_ref)
    authority = admission['review']
    modules = load_snapshots(authority['snapshot_transport'])
    execution = importlib.import_module('scripts.research.a2.evaluation.selector_maximal_risk_execution')
    compare = importlib.import_module('scripts.research.a2.evaluation.selector_account_compare')
    verify_downstream_bindings(modules,compare,execution)
    review = execution.reviewed_sources(authority['runtime_source_review'])
    need(digest(review) == digest(admission['runtime']), 'PHYSICAL_RUNTIME_REVIEW_CHANGED')
    with execution.frozen_test_configuration(review), executable_snapshot_guard(execution,
            authority['snapshot_transport'],modules):
        matrix,current = execution.validate_start(admission['config'],review)
        cfg,design,q = execution.ctl.checked(RUN)
        execution.evidence.validate_design(design)
        journal = execution.journal_owner.RiskJournal(RUN,source_guard_recovery_ref=review_ref)
        terminal_journal_boundary(journal,admission)
        # Pin complete artifacts and verify only physical clocks/footer counts.
        for role in TERMINAL_COMPLETE:
            panel = admission['completed']['panels'][role]
            risk = admission['completed']['predicted_risk'][role]
            for value in (panel,risk):
                execution.ctl.footer({k:value[k] for k in ('path','sha256')})
            need(execution.pq.ParquetFile(panel['path']).metadata.num_rows == q['artifacts']['raw_current']['rows']
                and execution.pq.ParquetFile(risk['path']).metadata.num_rows == 752,
                'PRIOR_COMPLETE_ARTIFACT_FOOTER_COUNTS_REQUIRED')
        no_other_worker(); verify_custody()
        publication,transport_proof = publication_metadata_preflight(execution,admission,modules)
        bind_runtime_custody(journal)
        journal.verify()
        status = dict(status='PASS_TERMINAL_SOURCE_GUARD_ENGINEERING_ADMISSION',research_id=ID,
            prior_terminal=authority['prior_terminal'],prior_audit=authority['prior_audit'],
            prior_delta=authority['prior_delta'],exact_complete_cache_counts=TERMINAL_SOLVES,
            unentered_named_classical_solves=1719,recoverable_original_RX_nodes=28,
            historical_qualification_native_reads=330,prior_worker_execution_native_reads=243,
            preflight_new_native_numeric_reads=0,new_fit=0,new_solve=0,new_risk_estimation=0,
            scientific_retry=0,test2026_rows_read=0,
            publication_metadata_preflight='SOURCE_ONLY_PUBLICATION_QUALIFIED',
            publication_source_transport=transport_proof,
            joint_delivery_completed=False,coverage_sufficient_claim_allowed=False)
        if validate_only:
            return status
        paths = execution.resolve(execution.ctl.REPO)
        execution.assert_safe_output_path(TERMINAL_ROOT,kind='backtest',paths=paths)
        no_other_worker(); journal.verify(); verify_custody()
        need(not TERMINAL_ROOT.exists(), 'ONE_SHOT_NEW_SOURCE_GUARD_ROOT_REQUIRED')
        TERMINAL_ROOT.mkdir(parents=True,exist_ok=False)
        with (TERMINAL_ROOT/TERMINAL_MARKER).open('x',encoding='utf-8') as stream:
            json.dump(dict(status='STARTED_TERMINAL_SOURCE_GUARD_ENGINEERING_RECOVERY',
                research_id=ID,review=review_ref,runtime_source_review=authority['runtime_source_review'],
                prior_terminal=authority['prior_terminal'],prior_audit=authority['prior_audit'],
                prior_delta=authority['prior_delta'],current_time=execution.ctl.now(),
                publication_source_transport=transport_proof,
                original_RX_nodes=authority['recover_rx_nodes'],scientific_retry=0,
                test2026_rows_read=0,joint_delivery_completed=False),stream,indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        # This is the sole additive state transition. No new activation/slot/ID.
        recovered = journal.recover_source_guard_zero_entry(review_ref)
        need(recovered == authority['recover_rx_nodes'], 'EXACT_ORIGINAL_RX28_RECOVERY_REQUIRED')
        execution.stage(TERMINAL_ROOT/'PIPELINE_STATE.json','TERMINAL_SOURCE_GUARD_RECOVERY_RUNNING',
            phase='ORIGINAL_RX28_ADDITIVELY_RECOVERED',review_ref=review_ref,
            historical_qualification_native_reads=330,prior_worker_execution_native_reads=243,
            exact_complete_cache_counts=TERMINAL_SOLVES,unentered_named_classical_solves=1719,
            recovered_original_RX_nodes=28)
        raw_meta = execution.ctl.project(q['artifacts']['raw_current'],list(execution.current_owner.RAW_META),
            start='2023-01-01',stop='2026-01-01',run=RUN)
        inputs = execution.input_owner.RiskInputs(publication['publication'],matrix,current,raw_meta,
            source_review=review,source_review_ref=authority['runtime_source_review'])
        restore_input_gates(inputs,admission['gates'],execution,
            prior_review_ref=authority['original_source_review'])
        execution.stage(TERMINAL_ROOT/'PIPELINE_STATE.json','TERMINAL_SOURCE_GUARD_RECOVERY_RUNNING',
            phase='PRIOR_QUALIFICATION_METADATA_RESTORED',review_ref=review_ref,
            historical_qualification_native_reads=330,prior_worker_execution_native_reads=243,
            execution_input_counts=inputs.status()['counts'])
        for key in ('raw_current','pair_geometry','current_pair_features'):
            execution.ctl.footer(q['artifacts'][key])
        raw = execution.pq.read_table(execution.ctl.pin(q['artifacts']['raw_current'])).to_pandas()
        geometry = execution.pq.read_table(execution.ctl.pin(q['artifacts']['pair_geometry'])).to_pandas()
        raw.signal_date = execution.pd.to_datetime(raw.signal_date)
        geometry.signal_date = execution.pd.to_datetime(geometry.signal_date)
        need(raw.signal_date.lt('2026-01-01').all() and geometry.signal_date.lt('2026-01-01').all(),
            'PREPARED_INPUT_PRE2026_LOCK')
        features = execution.pq.read_table(execution.ctl.pin(q['artifacts']['current_pair_features'])).to_pandas()
        need(features[list(execution.ctl.PAIR_KEYS)].equals(geometry[list(execution.ctl.PAIR_KEYS)])
            and len(execution.ctl.feature_order()) == 216, 'EXACT_ORIGINAL_PAIR_AND216_FEATURE_ORDER_REQUIRED')
        base_x = features[execution.ctl.feature_order()].to_numpy(float)
        runtime = execution.ctl.runtime_parts(execution.ctl.runtime_for(RUN,cfg))[0]
        need(tuple(execution.hybrids.ROLES) == RX, 'EXACT_TWO_ORIGINAL_RX_ROLES_REQUIRED')
        results = [admission['completed']]
        for role in RX:
            execution.stage(TERMINAL_ROOT/'PIPELINE_STATE.json','QUALIFIED_HYBRID_RUNNING',role=role,
                review_ref=review_ref,source_guard_recovery=True)
            try:
                result = execution.hybrids.execute_hybrid(RUN,design,q,raw,geometry,base_x,role,
                    inputs.get_risk,journal,execution.kernel,runtime,artifact_root=TERMINAL_ROOT)
            except Exception as error:
                details = dict(error_type=type(error).__name__,error=str(error),traceback=traceback.format_exc())
                execution.put(TERMINAL_ROOT/role/'ENGINEERING_FAILURE_R1.json',details)
                if not any(s['candidate_id'] == role and s['status'] == 'STARTED' for s in journal.slots.values()):
                    journal.block_remaining(role,'UNEXPECTED_ENGINEERING_FAILURE_BEFORE_UNUSED_FITS')
                result = dict(status='HYBRID_FAILED_UNTESTABLE',complete_candidates=[],
                    failed_or_untestable={role:details['error_type']+':'+details['error']},
                    panels={},native_pair_predictions={})
            results.append(result)
        execution.stage(TERMINAL_ROOT/'PIPELINE_STATE.json','QUALIFIED_UNFINISHED_CLASSICAL_RUNNING',
            review_ref=review_ref,exact_reuse_classical_cache_counts=TERMINAL_SOLVES)
        member = execution.membership
        need(tuple(member.ROLES) == (*CLASSICAL,'C14_D02','C14_G1','C14_G4'),
            'EXACT_FROZEN_MEMBERSHIP_ROSTER_REQUIRED')
        kernel = member.event.bind_pinned_kernel(member.execute_membership,physical_path=member.__file__,
            expected_sha256=review['source_pins'][str(Path(member.__file__).resolve())],
            dependencies={'ROLES':TERMINAL_CLASSICAL})
        results.append(kernel(RUN,design,q,raw,geometry,matrix,inputs.get_risk,journal,
            authority['runtime_source_review'],role_gates=inputs.status()['roles'],
            qualification_ref=authority['qualification'],artifact_root=TERMINAL_ROOT))
        summary = execution.terminal(RUN,design,q,
            execution.read_exact(review['immutable_inputs']['ML_ASSEMBLY.json']),
            admission['values']['qualification'],results,journal,authority['runtime_source_review'],
            artifact_root=TERMINAL_ROOT,input_qualification_ref=authority['qualification'])
        terminal_ref = execution.ref(TERMINAL_ROOT/'RISK_DECISIONS_TERMINAL_R1.json')
        execution.stage(TERMINAL_ROOT/'PIPELINE_STATE.json',summary['status'],terminal=terminal_ref,
            joint_delivery_completed=False,coverage_sufficient_claim_allowed=False)
        audit = dict(status='TERMINAL_SOURCE_GUARD_ENGINEERING_RECOVERY_TERMINAL',research_id=ID,
            review=review_ref,runtime_source_review=authority['runtime_source_review'],
            original_input_qualification=authority['qualification'],
            historical_qualification_counts=admission['values']['qualification']['counts'],
            prior_worker_execution_input_counts=admission['values']['prior_audit']['execution_input_counts'],
            execution_input_counts=inputs.status()['counts'],
            prior_terminal=authority['prior_terminal'],prior_audit=authority['prior_audit'],
            preserved_prior_engineering_failures=dict(authority['classical_failures'],**authority['rx_failures']),
            terminal=terminal_ref,reused_completed_artifacts=authority['completed_artifacts'],
            original_complete_cache_counts=TERMINAL_SOLVES,recovered_original_RX_nodes=recovered,
            publication_source_transport=transport_proof,scientific_retry=0,test2026_rows_read=0,
            joint_delivery_completed=False,coverage_sufficient_claim_allowed=False)
        execution.put(TERMINAL_ROOT/TERMINAL_AUDIT,audit)
        return dict(status=summary['status'],terminal=terminal_ref,
            complete_conditional_roles=len(summary['complete_conditional_roles']),
            charged_solves=summary['charged_solves'],backend_entered=summary['backend_entered'],
            scientific_retry=0,test2026_rows_read=0,joint_delivery_completed=False)

# This mode continues only the durable ROOT2 checkpoint after a reboot.
POST_REBOOT_SCHEMA = 'C14_POST_REBOOT_CLASSICAL_CHECKPOINT_V1'
POST_REBOOT_REVIEW_PATH = RUN/'C14_POST_REBOOT_CLASSICAL_CHECKPOINT_REVIEW_R1.json'
POST_REBOOT_MARKER = 'POST_REBOOT_CLASSICAL_CHECKPOINT_STARTED_R1.json'
POST_REBOOT_AUDIT = 'POST_REBOOT_CLASSICAL_CHECKPOINT_COMPLETE_R1.json'
POST_REBOOT_DELTA_SHA = '94829aa339c9128665fef95a0650d45cd029c38387e8f1a95e57260ce443734e'
POST_REBOOT_DELTA_BYTES, POST_REBOOT_DELTA_LINES = 15563481, 7832
POST_REBOOT_SOLVES = dict(TERMINAL_SOLVES, C14_D09=608,
    C14_RX_HGB_LW=502, C14_RX_XGB_QQQ_RESIDUAL=502)
POST_REBOOT_OLD_REVIEW_SHA = '0f3d8ed74282ec026a7238e8d7afdfe0cde8f53c034c99694a8c18f5449b697b'
POST_REBOOT_R4_SHA = 'b5372ea2703639b1c3e44d90d6f0cc9f9780175d8164506b081f85b8fae1891f'
POST_REBOOT_OLD_MARKER_SHA = '57b7a0860bb53c61f459eb05d298957fc57e78e5938d11eb4f76fc0396156b91'
POST_REBOOT_RECEIPT_SHA = '31df277876e354db95203bc35fffdf71c292a89376b34ffe0769059ec97516a3'
POST_REBOOT_RX_RECEIPT_SHA = '69df4659a7c5506e29001a44ab3728616186e2011f274c011bc3419e20788e91'
POST_REBOOT_SOURCE_BACKUPS = {
    'evaluation/selector_maximal_risk_resume.py':
        '1a6cf59a48851058d85e0c35bca777db784ac3d71293ac19bc83716cf5d0798e',
    'training/selector_maximal_risk_journal.py':
        '1525702202d93bd2b35bc4b98fb9d71fd3ec44d4d80439823aa42e7b6c0bea6c',
    'tests/evaluation/test_selector_maximal_risk_resume.py':
        'bd8ebfc4847809bee29dadddffa23005b317cad934792dd02c66638bb321b06c',
    'tests/training/test_selector_maximal_risk_journal.py':
        '8f6002693e885e837e5934ab099d4fd92d692351ed5c38297a4209def13cfa30',
}
_POST_REBOOT_AUTHORITY = None


def post_reboot_source_paths():
    return {str(REPO/('tests/research/a2' if rel.startswith('tests/') else 'scripts/research/a2')/
        (rel[6:] if rel.startswith('tests/') else rel)): (rel, old)
        for rel,old in POST_REBOOT_SOURCE_BACKUPS.items()}


def post_reboot_review_contract(review):
    fields = {'schema','status','research_id','classification','independent_review',
        'scientific_contract_changed','scientific_retry','test2026_rows_read',
        'source_pins','source_backups','original_source_guard_review',
        'prior_runtime_source_review','runtime_source_review','checkpoint_delta',
        'old_recovery_event','old_marker','reboot_receipt','input_qualification',
        'completed_fit_artifacts','completed_role_artifacts','remaining_classical_roles',
        'snapshot_transport','execution_configuration','B_freeze',
        'original_publication_admission','independent_RX_completion'}
    need(isinstance(review,dict) and set(review) == fields
        and review['schema'] == POST_REBOOT_SCHEMA and review['status'] == 'PASS'
        and review['research_id'] == ID
        and review['classification'] == 'POST_REBOOT_CLASSICAL_ONLY_CHECKPOINT_ENGINEERING'
        and review['independent_review'] is True and review['scientific_contract_changed'] is False
        and type(review['scientific_retry']) is int and review['scientific_retry'] == 0
        and type(review['test2026_rows_read']) is int and review['test2026_rows_read'] == 0
        and review['remaining_classical_roles'] == list(TERMINAL_CLASSICAL),
        'INDEPENDENT_FIXED_ROOT2_CLASSICAL_CHECKPOINT_REVIEW_REQUIRED')


def audit_post_reboot_delta(raw, dates, old_review_ref, nodes):
    """Inspect source/control metadata and hash caches without decoding values."""
    need(raw.endswith(b'\n') and b'\r' not in raw and len(raw) == POST_REBOOT_DELTA_BYTES
        and hashlib.sha256(raw).hexdigest() == POST_REBOOT_DELTA_SHA,
        'EXACT_POST_REBOOT_DELTA_PREFIX_REQUIRED')
    lines = raw.splitlines()
    need(len(lines) == POST_REBOOT_DELTA_LINES, 'EXACT_POST_REBOOT_DELTA_LINES_REQUIRED')
    prior = audit_terminal_delta(b'\n'.join(lines[:TERMINAL_DELTA_LINES])+b'\n', dates)
    requests = deepcopy(prior['requests']); fits = {}; recovered = None
    actions = Counter(prior['actions']); previous = prior['previous']
    classical_identity = set(next(iter(requests.values()))['identity'])
    hybrid_identity = {'design_sha256','pair_key_sha256','candidate_id',
        'full_U_keys_sha256','score_sha256','eligibility_sha256'}
    for sequence,line in enumerate(lines[TERMINAL_DELTA_LINES:], TERMINAL_DELTA_LINES):
        row = _opaque_object_fields(line)
        need(tuple(row) == ('action','data','previous','sequence','sha256'),
            'EXACT_CANONICAL_CHECKPOINT_ROW_SCHEMA_REQUIRED')
        seq,prev,h = (json.loads(row[k]) for k in ('sequence','previous','sha256'))
        stop = line.rfind(b',"sha256":')
        need(stop > 0 and type(seq) is int and seq == sequence and prev == previous
            and hashlib.sha256(line[:stop]+b'}').hexdigest() == h,
            'POST_REBOOT_DELTA_HASH_CHAIN_CHANGED')
        previous = h; action = json.loads(row['action']); actions[action] += 1
        need(action in {'SOURCE_GUARD_ZERO_ENTRY','FIT_BEGIN','FIT_ENTER','FIT_FINISH',
            'SOLVE_ENTER','SOLVE_COMPLETE'}, 'NO_NEW_ACTIVATION_BLOCK_FAILURE_OR_UNKNOWN_CHECKPOINT_EVENT')
        data = _opaque_object_fields(row['data'])
        if action == 'SOURCE_GUARD_ZERO_ENTRY':
            need(recovered is None and sequence == TERMINAL_DELTA_LINES
                and tuple(data) == ('nodes','review_ref'), 'EXACT_ONE_ORIGINAL_RECOVERY_EVENT_REQUIRED')
            recovered = json.loads(row['data'])
            need(recovered == dict(review_ref=old_review_ref,nodes=nodes),
                'ORIGINAL_RECOVERY_EVENT_AND_RX28_CHANGED')
        elif action.startswith('FIT_'):
            node = json.loads(data['node'])
            need(recovered is not None and node in nodes, 'ONLY_ORIGINAL_RECOVERED_FIT_NODES')
            if action == 'FIT_BEGIN':
                need(tuple(data) == ('identity','node') and node not in fits,
                    'FIT_BEGIN_DUPLICATE_OR_RETRY_FORBIDDEN')
                identity = _opaque_object_fields(data['identity'])
                need('cutoff' in identity and json.loads(identity['cutoff']) == node.split('|')[2],
                    'EXACT_CHECKPOINT_FIT_CUTOFF_REQUIRED')
                fits[node] = dict(status='STARTED',entered=0,
                    identity_sha256=hashlib.sha256(data['identity']).hexdigest())
            elif action == 'FIT_ENTER':
                need(tuple(data) == ('event','node') and node in fits
                    and fits[node]['status'] == 'STARTED' and fits[node]['entered'] == 0,
                    'EXACT_SINGLE_FIT_BACKEND_ENTRY_REQUIRED')
                fits[node]['entered'] = 1
            else:
                need(tuple(data) == ('details','node','status') and node in fits
                    and fits[node]['status'] == 'STARTED' and fits[node]['entered'] == 1
                    and json.loads(data['status']) == 'COMPLETE',
                    'ALL_ENTERED_FITS_MUST_BE_COMPLETE_NO_RETRY')
                details = _opaque_object_fields(data['details'])
                need(tuple(details) == ('artifact',), 'EXACT_COMPLETED_FIT_ARTIFACT_REQUIRED')
                artifact = json.loads(details['artifact'])
                need(isinstance(artifact,dict) and set(artifact) == {'path','sha256'},
                    'EXACT_COMPLETED_FIT_PHYSICAL_REF_REQUIRED')
                fits[node].update(status='COMPLETE',artifact=artifact)
        else:
            token = json.loads(data['token']); parts = token.split('|')
            need(len(parts) == 3 and parts[2] in dates
                and ((parts[0] == 'CLASSICAL' and parts[1] == 'C14_D09')
                     or (parts[0] == 'HYBRID' and parts[1] in RX)),
                'ONLY_ORIGINAL_RX_AND_D09_CHECKPOINT_SOLVES')
            if action == 'SOLVE_ENTER':
                need(tuple(data) == ('token',) and token not in requests,
                    'NO_DUPLICATE_OR_RETRIED_CHECKPOINT_SOLVE')
                requests[token] = None
            else:
                need(tuple(data) == ('receipt','token') and token in requests and requests[token] is None,
                    'UNIQUE_ENTER_BEFORE_CHECKPOINT_COMPLETE_REQUIRED')
                receipt = _opaque_object_fields(data['receipt']); is_hybrid = parts[0] == 'HYBRID'
                fields = ('identity','matching_records','matching_sha256') if is_hybrid else ('identity','result','result_sha256')
                need(tuple(receipt) == fields, 'EXACT_CHECKPOINT_CACHE_KIND_REQUIRED')
                identity = _opaque_object_fields(receipt['identity'])
                need(set(identity) == (hybrid_identity if is_hybrid else classical_identity),
                    'EXACT_CHECKPOINT_SOURCE_IDENTITY_FIELDS_REQUIRED')
                value_sha = json.loads(receipt[fields[2]])
                need(hashlib.sha256(receipt[fields[1]]).hexdigest() == value_sha,
                    'EXACT_OPAQUE_CHECKPOINT_CACHE_HASH_REQUIRED')
                decoded_identity = json.loads(receipt['identity'])
                need(not is_hybrid or decoded_identity['candidate_id'] == parts[1],
                    'EXACT_HYBRID_CHECKPOINT_ROLE_IDENTITY_REQUIRED')
                requests[token] = dict(identity=decoded_identity,**{fields[2]:value_sha})
    need(recovered == dict(review_ref=old_review_ref,nodes=nodes)
        and len(nodes) == len(set(nodes)) == 28 and set(fits) == set(nodes)
        and all(f['status'] == 'COMPLETE' and f['entered'] == 1 for f in fits.values())
        and all(v is not None for v in requests.values()), 'CLOSED_RX28_FIT_AND_SOLVE_CHECKPOINT_REQUIRED')
    need(actions == Counter(HEADER=1,ACTIVATE_ROLE=8,BLOCK_REMAINING=2,
        SOURCE_GUARD_ZERO_ENTRY=1,FIT_BEGIN=28,FIT_ENTER=28,FIT_FINISH=28,
        SOLVE_ENTER=3868,SOLVE_COMPLETE=3868), 'EXACT_POST_REBOOT_ACTION_COUNTS_REQUIRED')
    counts = dict(Counter(t.split('|')[1] for t in requests))
    need(counts == POST_REBOOT_SOLVES
        and sorted(t.rsplit('|',1)[1] for t in requests if t.startswith('CLASSICAL|C14_D09|')) == list(dates[:608]),
        'EXACT_COMPLETED3868_AND_D09_608_DATE_PREFIX_REQUIRED')
    for role in RX:
        need(sorted(t.rsplit('|',1)[1] for t in requests if t.startswith('HYBRID|'+role+'|')) == list(dates[250:]),
            'EXACT_RX502_LEARNED_DATE_MASK_REQUIRED')
    return dict(prior,requests=requests,fits=fits,recovery_event=recovered,
        counts=counts,sequence=len(lines),previous=previous,actions=dict(actions))


def opaque_selected_metadata(ref, fields, *, path=None):
    """Select metadata spans before JSON decoding, including indented assemblies."""
    p = pin(ref,path=path); raw = p.read_bytes().strip()
    need(raw[:1] == b'{' and raw[-1:] == b'}', 'OPAQUE_METADATA_OBJECT_REQUIRED')
    spans = {}; cursor = 1
    while cursor < len(raw)-1:
        while raw[cursor] in b' \t\n\r': cursor += 1
        key_end = _opaque_json_end(raw,cursor); key = json.loads(raw[cursor:key_end])
        need(isinstance(key,str) and key not in spans, 'DUPLICATE_OPAQUE_METADATA_FIELD')
        cursor = key_end
        while raw[cursor] in b' \t\n\r': cursor += 1
        need(raw[cursor:cursor+1] == b':','OPAQUE_METADATA_COLON_REQUIRED'); cursor += 1
        while raw[cursor] in b' \t\n\r': cursor += 1
        end = _opaque_json_end(raw,cursor); spans[key] = raw[cursor:end]; cursor = end
        while cursor < len(raw)-1 and raw[cursor] in b' \t\n\r': cursor += 1
        if cursor < len(raw)-1:
            need(raw[cursor:cursor+1] == b',','OPAQUE_METADATA_COMMA_REQUIRED'); cursor += 1
    need(cursor == len(raw)-1 and set(fields) <= set(spans), 'REQUIRED_OPAQUE_METADATA_FIELDS_MISSING')
    selected = {k:json.loads(spans[k]) for k in fields}; pin(ref,path=path)
    return selected


def post_reboot_completed_rx(declared):
    need(set(declared) == set(RX), 'BOTH_COMPLETED_RX_ARTIFACT_CLOSURES_REQUIRED')
    results = []
    fields = {'status','research_id','role','head','family','feature_count','complete_candidates',
        'failed_or_untestable','panels','native_pair_predictions','fit_failures',
        'forecast2026_rows','scientific_retry','strict_PIT_promotion_eligible'}
    for role in RX:
        refs = declared[role]
        need(isinstance(refs,dict) and set(refs) == {'assembly','panel','native_pairs','matching'},
            'EXACT_FOUR_COMPLETED_RX_REFS_REQUIRED')
        parent = TERMINAL_ROOT/role
        names = dict(assembly='HYBRID_ASSEMBLY.json',panel='scores_pre2026.parquet',
            native_pairs='native_pairs_pre2026.parquet',matching='matching_pre2026.parquet')
        for key,name in names.items(): pin(refs[key],path=parent/name)
        metadata = opaque_selected_metadata(refs['assembly'],fields,path=parent/names['assembly'])
        need(metadata['status'] == 'HYBRID_COMPLETE' and metadata['research_id'] == ID
            and metadata['role'] == role and metadata['feature_count'] == 228
            and (metadata['head'],metadata['family']) ==
                (('HGB','LW') if role == RX[0] else ('XGB','QQQ_RESIDUAL'))
            and metadata['complete_candidates'] == [role]
            and metadata['failed_or_untestable'] == metadata['fit_failures'] == {}
            and metadata['forecast2026_rows'] == metadata['scientific_retry'] == 0
            and metadata['strict_PIT_promotion_eligible'] is False
            and set(metadata['panels']) == set(metadata['native_pair_predictions']) == {role},
            'COMPLETE_UNFAILED_FROZEN_RX_METADATA_REQUIRED')
        panel,native = metadata['panels'][role],metadata['native_pair_predictions'][role]
        need({k:panel[k] for k in ('path','sha256')} == refs['panel']
            and panel['calendar_dates'] == 752 and panel['raw_fallback_2023_exact'] is True
            and {k:native[k] for k in ('path','sha256')} == refs['native_pairs']
            and native['kind'] == 'U0_POINT_GT0' and native['rows'] == 502*200
            and dict(path=native['matching_path'],sha256=native['matching_sha256']) == refs['matching'],
            'EXACT_RX_PANEL_NATIVE_MATCHING_REFERENCE_CHAIN_REQUIRED')
        results.append(dict(complete_candidates=[role],failed_or_untestable={},
            panels={role:panel},native_pair_predictions={role:native}))
    return results



def assert_checkpoint_entry_origin():
    canonical = REPO/'scripts/research/a2/evaluation/selector_maximal_risk_resume.py'
    module = sys.modules[__name__]
    spec = getattr(module,'__spec__',None)
    loader = getattr(module,'__loader__',None)
    need(Path(module.__file__).resolve() == canonical.resolve()
        and spec is not None
        and spec.name == 'scripts.research.a2.evaluation.selector_maximal_risk_resume'
        and Path(spec.origin).resolve() == canonical.resolve()
        and loader is not None and Path(loader.path).resolve() == canonical.resolve(),
        'CURRENT_CANONICAL_CHECKPOINT_MODULE_ORIGIN_REQUIRED')
    function_origin(module,('admit_source_guard_checkpoint','resume_source_guard_checkpoint',
        'audit_post_reboot_delta','post_reboot_completed_rx'),canonical)


def admit_source_guard_checkpoint(review_ref):
    """A fixed durable, all-complete prefix admits only uncharged classical work."""
    global _TERMINAL_AUTHORITY, _TERMINAL_TRANSPORT_SEAL, _POST_REBOOT_AUTHORITY
    need(not _CUSTODY and _TERMINAL_AUTHORITY is None and _POST_REBOOT_AUTHORITY is None,
        'ADMISSION_IS_SINGLE_USE_IN_THIS_PROCESS')
    need(sys.dont_write_bytecode, 'CANONICAL_PYTHON_MINUS_B_REQUIRED'); no_other_worker()
    assert_checkpoint_entry_origin()
    need(TERMINAL_ROOT.is_dir() and not any((TERMINAL_ROOT/name).exists() for name in
        (POST_REBOOT_MARKER,POST_REBOOT_AUDIT,TERMINAL_AUDIT,'RISK_DECISIONS_TERMINAL_R1.json')),
        'ONE_SHOT_UNTERMINATED_EXISTING_ROOT2_CHECKPOINT_REQUIRED')
    review = read(review_ref,path=POST_REBOOT_REVIEW_PATH); post_reboot_review_contract(review)
    source_paths = post_reboot_source_paths()
    need(set(review['source_pins']) == set(review['source_backups']) == set(source_paths),
        'ONLY_FOUR_FIXED_POST_REBOOT_SOURCE_TEST_PATHS')
    old = read(review['original_source_guard_review'],path=TERMINAL_REVIEW_PATH,
        expected=POST_REBOOT_OLD_REVIEW_SHA); terminal_review_contract(old)
    for path,(relative,old_sha) in source_paths.items():
        need(old['source_pins'][path] == old_sha,'ORIGINAL_SOURCE_GUARD_FOUR_PINS_CHANGED')
        pin(review['source_backups'][path],path=RUN/'source_corrections/C14_POST_REBOOT_CLASSICAL_CHECKPOINT_R1'/relative,
            expected=old_sha)
        pin(dict(path=path,sha256=review['source_pins'][path]))
    for path,h in old['source_pins'].items():
        if path not in source_paths: pin(dict(path=path,sha256=h))
    for field,old_field in (('snapshot_transport','snapshot_transport'),
        ('execution_configuration','original_config'),('input_qualification','qualification'),
        ('B_freeze','B_freeze'),('original_publication_admission','original_publication_admission'),
        ('prior_runtime_source_review','runtime_source_review')):
        need(review[field] == old[old_field], 'ORIGINAL_CHECKPOINT_AUTHORITY_CHANGED:'+field)
    r4 = read(review['prior_runtime_source_review'],path=RUN/'RISK_INPUT_SOURCE_REVIEW_R4.json',
        expected=POST_REBOOT_R4_SHA)
    runtime = read(review['runtime_source_review'],path=RUN/'RISK_INPUT_SOURCE_REVIEW_R5.json')
    expected = deepcopy(r4)
    journal_path = str(REPO/'scripts/research/a2/training/selector_maximal_risk_journal.py')
    expected['source_pins'][journal_path] = review['source_pins'][journal_path]
    expected['prior_runtime_source_review'] = review['prior_runtime_source_review']
    need(digest(runtime) == digest(expected), 'ONLY_JOURNAL_R5_PIN_AND_PRIOR_R4_REF_MAY_CHANGE')
    for path,h in runtime['source_pins'].items(): pin(dict(path=path,sha256=h))
    for ref in runtime['immutable_inputs'].values(): pin(ref)
    values = {key:read(old[field],path=p,expected=h) for key,field,(p,h) in (
        ('original_source_review','original_source_review',PINS['original_review']),
        ('original_config','original_config',PINS['original_config']),
        ('qualification','qualification',PINS['qualification']),
        ('B_freeze','B_freeze',PINS['B_freeze']),
        ('original_publication_admission','original_publication_admission',PINS['original_publication_admission']),
        ('prior_terminal','prior_terminal',(ROOT/'RISK_DECISIONS_TERMINAL_R1.json',TERMINAL_SHA)),
        ('prior_audit','prior_audit',(ROOT/AUDIT,TERMINAL_AUDIT_SHA)))}
    _TERMINAL_AUTHORITY = deepcopy(review['original_source_guard_review'])
    _TERMINAL_TRANSPORT_SEAL = digest(review['snapshot_transport'])
    _POST_REBOOT_AUTHORITY = deepcopy(review_ref)
    validate_transport(review['snapshot_transport'])
    design = read(dict(path=str(RUN/'DESIGN_FREEZE.json'),
        sha256='8bdcabcc09817691741d8aaaf7baab8ba663e0360e13cc62b9d918208ff901b6'))
    original_source_custody(design,runtime,review['snapshot_transport'])
    for ref in design['inputs'].values(): pin({k:ref[k] for k in ('path','sha256')})
    freeze = read(dict(path=str(RUN/'FORMAL_FREEZE_RECEIPT.json'),
        sha256='00fa18f066358e6cf19f21b27b7bc048575830611e35786d87da55a67caa28f4'))
    prepared = read(dict(path=str(RUN/'INPUT_QUALIFICATION.json'),sha256=freeze['input_qualification_sha256']))
    for ref in prepared['artifacts'].values(): pin({k:ref[k] for k in ('path','sha256')})
    config = values['original_config']
    need(config['source_review'] == old['original_source_review'],'ORIGINAL_CONFIG_REVIEW_CHANGED')
    matrix = read(config['requirement_matrix']); current = read(config['current_bindings'])['bindings']
    delta = review['checkpoint_delta']
    need(delta == dict(path=str(RUN/'RISK_EXECUTION_DELTA.jsonl'),sha256=POST_REBOOT_DELTA_SHA,
        bytes=POST_REBOOT_DELTA_BYTES,lines=POST_REBOOT_DELTA_LINES),
        'EXACT_CLOSED_POST_REBOOT_CHECKPOINT_DELTA_REQUIRED')
    dref = {k:delta[k] for k in ('path','sha256')}
    journal = audit_post_reboot_delta(pin(dref).read_bytes(),matrix['roles'][0]['required_dates'],
        review['original_source_guard_review'],old['recover_rx_nodes']); pin(dref)
    need(review['old_recovery_event'] == dict(sequence=TERMINAL_DELTA_LINES,**journal['recovery_event']),
        'EXACT_OLD_ADDITIVE_EVENT_MUST_BE_PRESERVED')
    marker = read(review['old_marker'],path=TERMINAL_ROOT/TERMINAL_MARKER,
        expected=POST_REBOOT_OLD_MARKER_SHA)
    need(marker['review'] == review['original_source_guard_review']
        and marker['original_RX_nodes'] == old['recover_rx_nodes']
        and marker['prior_delta'] == old['prior_delta'], 'EXACT_OLD_RECOVERY_MARKER_REQUIRED')
    read(review['reboot_receipt'],path=MAINTENANCE/'POST_REBOOT_CHECKPOINT_OBSERVATION_R1.json',
        expected=POST_REBOOT_RECEIPT_SHA)
    read(review['independent_RX_completion'],path=MAINTENANCE/'TERMINAL_SOURCE_GUARD_RX_COMPLETE_OBSERVATION_R1.json',
        expected=POST_REBOOT_RX_RECEIPT_SHA)
    gates = validate_qualification(values['qualification'],matrix,current,
        old['original_source_review'],journal['activations'])
    need(set(review['completed_fit_artifacts']) == set(old['recover_rx_nodes']),
        'ALL28_COMPLETED_FIT_ARTIFACTS_REQUIRED')
    for node,ref in review['completed_fit_artifacts'].items():
        need(ref == journal['fits'][node]['artifact'],'EXACT_FIT_FINISH_ARTIFACT_REFERENCE_REQUIRED')
        pin(ref,path=RUN/'risk_execution/models'/(digest(node)+'.joblib'))
    declared = review['completed_role_artifacts']
    need(set(declared) == set(TERMINAL_COMPLETE) | set(RX), 'ALL_EIGHT_COMPLETED_ROLE_CLOSURES_REQUIRED')
    need({r:declared[r] for r in TERMINAL_COMPLETE} == old['completed_artifacts'],
        'EXACT_ORIGINAL_SIX_COMPLETED_ARTIFACTS_REQUIRED')
    terminal = values['prior_terminal']
    need(terminal['assembly'] and terminal['input_qualification'] == old['qualification']
        and terminal['delta'] == {k:old['prior_delta'][k] for k in ('path','sha256')}
        and terminal['complete_conditional_roles'] == list(TERMINAL_COMPLETE)
        and terminal['joint_delivery_completed'] is False, 'ORIGINAL_TERMINAL_CLOSURE_REQUIRED')
    completed = terminal_completed_artifacts(read(terminal['assembly']),old['completed_artifacts'])
    rx_completed = post_reboot_completed_rx({r:declared[r] for r in RX})
    for role in TERMINAL_CLASSICAL:
        parent = TERMINAL_ROOT/role
        need(not parent.exists() or not any(parent.iterdir()),'NO_NONCOMPLETE_CLASSICAL_ARTIFACT_OVERWRITE')
    no_other_worker(); verify_custody()
    return dict(review_ref=deepcopy(review_ref),review=review,original=values['original_source_review'],
        original_authority=old,values=values,runtime=runtime,config=config,matrix=matrix,current=current,
        gates=gates,journal=journal,completed=completed,rx_completed=rx_completed)


def post_reboot_journal_boundary(journal, admission):
    observed = admission['journal']
    need(journal.sequence == observed['sequence'] and journal.previous == observed['previous']
        and len(journal.requests) == 3868
        and sum(s['status'] == 'COMPLETE' for s in journal.slots.values()) == 28
        and sum(s['status'] == 'UNRESERVED' for s in journal.slots.values()) == 116,
        'EXACT_CLOSED_POST_REBOOT_JOURNAL_BOUNDARY_REQUIRED')
    for node,slot in journal.slots.items():
        if node in observed['fits']:
            fit = observed['fits'][node]
            need(slot['status'] == 'COMPLETE' and type(slot['entered']) is int and slot['entered'] == 1
                and digest(slot['identity']) == fit['identity_sha256'] and slot['artifact'] == fit['artifact'],
                'ALL28_COMPLETED_FIT_IDENTITIES_ARTIFACTS_REQUIRED')
        else:
            need(slot['status'] == 'UNRESERVED' and type(slot['entered']) is int and slot['entered'] == 0,
                'ALL116_UNRESERVED_NODES_MUST_REMAIN_UNTOUCHED')
    for token,request in journal.requests.items():
        prior = observed['requests'].get(token)
        need(prior is not None and request['status'] == 'COMPLETE' and type(request['charged']) is int
            and request['charged'] == 1 and digest(request['identity']) == digest(prior['identity']),
            'ALL3868_CHARGED_COMPLETE_CACHE_IDENTITIES_REQUIRED')
        kind = 'matching_sha256' if token.startswith('HYBRID|') else 'result_sha256'
        need(request[kind] == prior[kind], 'EXACT_COMPLETE_CACHE_DIGEST_REQUIRED')
    need(getattr(journal,'_source_guard_recovered',False) is True, 'ORIGINAL_RECOVERY_EVENT_REQUIRED')
    journal.verify()


def resume_source_guard_checkpoint(review_ref, *, validate_only=False):
    admission = admit_source_guard_checkpoint(review_ref); authority = admission['review']
    old = admission['original_authority']
    modules = load_snapshots(authority['snapshot_transport'])
    execution = importlib.import_module('scripts.research.a2.evaluation.selector_maximal_risk_execution')
    compare = importlib.import_module('scripts.research.a2.evaluation.selector_account_compare')
    verify_downstream_bindings(modules,compare,execution)
    review = execution.reviewed_sources(authority['runtime_source_review'])
    need(digest(review) == digest(admission['runtime']), 'PHYSICAL_CHECKPOINT_RUNTIME_REVIEW_CHANGED')
    with execution.frozen_test_configuration(review), executable_snapshot_guard(execution,
            authority['snapshot_transport'],modules):
        matrix,current = execution.validate_start(admission['config'],review)
        cfg,design,q = execution.ctl.checked(RUN); execution.evidence.validate_design(design)
        journal = execution.journal_owner.RiskJournal(RUN,post_reboot_checkpoint_ref=review_ref)
        post_reboot_journal_boundary(journal,admission)
        for result in [admission['completed'],*admission['rx_completed']]:
            for role,panel in result['panels'].items():
                execution.ctl.footer({k:panel[k] for k in ('path','sha256')})
                need(execution.pq.ParquetFile(panel['path']).metadata.num_rows == q['artifacts']['raw_current']['rows'],
                    'EXACT_REUSED_FULL752_PANEL_FOOTER_REQUIRED')
                if role in RX:
                    native = result['native_pair_predictions'][role]
                    execution.ctl.footer({k:native[k] for k in ('path','sha256')})
                    need(execution.pq.ParquetFile(native['path']).metadata.num_rows == 502*200,
                        'EXACT_REUSED_RX502_NATIVE_PAIR_FOOTER_REQUIRED')
                    execution.ctl.footer(dict(path=native['matching_path'],sha256=native['matching_sha256']))
                else:
                    risk = result['predicted_risk'][role]
                    execution.ctl.footer({k:risk[k] for k in ('path','sha256')})
                    need(execution.pq.ParquetFile(risk['path']).metadata.num_rows == 752,
                        'EXACT_REUSED_CLASSICAL_RISK_FOOTER_REQUIRED')
        no_other_worker(); verify_custody()
        publication,transport_proof = publication_metadata_preflight(execution,admission,modules)
        bind_runtime_custody(journal); journal.verify()
        status = dict(status='PASS_POST_REBOOT_CLASSICAL_CHECKPOINT_ADMISSION',research_id=ID,
            checkpoint_delta=authority['checkpoint_delta'],complete_cache_counts=POST_REBOOT_SOLVES,
            unentered_named_classical_solves=1648,completed_RX_fit_slots=28,
            historical_qualification_native_reads=330,prior_checkpoint_execution_native_reads=243,
            interrupted_worker_execution_input_counts='UNKNOWN_DUE_REBOOT',
            preflight_new_native_numeric_reads=0,new_fit=0,new_solve=0,new_risk_estimation=0,
            current_resume_module=dict(path=str(Path(__file__).resolve()),
                sha256=authority['source_pins'][str(Path(__file__).resolve())]),
            scientific_retry=0,test2026_rows_read=0,publication_source_transport=transport_proof,
            joint_delivery_completed=False,coverage_sufficient_claim_allowed=False)
        if validate_only: return status
        paths = execution.resolve(execution.ctl.REPO)
        execution.assert_safe_output_path(TERMINAL_ROOT,kind='backtest',paths=paths)
        no_other_worker(); journal.verify(); verify_custody()
        need(not any((TERMINAL_ROOT/n).exists() for n in
            (POST_REBOOT_MARKER,POST_REBOOT_AUDIT,TERMINAL_AUDIT,'RISK_DECISIONS_TERMINAL_R1.json')),
            'ONE_SHOT_POST_REBOOT_MARKER_REQUIRED')
        with (TERMINAL_ROOT/POST_REBOOT_MARKER).open('x',encoding='utf-8') as stream:
            json.dump(dict(status='STARTED_POST_REBOOT_CLASSICAL_ONLY_CHECKPOINT',
                research_id=ID,review=review_ref,runtime_source_review=authority['runtime_source_review'],
                checkpoint_delta=authority['checkpoint_delta'],old_marker=authority['old_marker'],
                current_time=execution.ctl.now(),remaining_classical_roles=list(TERMINAL_CLASSICAL),
                completed_fit_slots_reused=28,interrupted_worker_execution_input_counts='UNKNOWN_DUE_REBOOT',
                scientific_retry=0,test2026_rows_read=0,joint_delivery_completed=False),stream,indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        execution.stage(TERMINAL_ROOT/'PIPELINE_STATE.json','POST_REBOOT_CLASSICAL_CHECKPOINT_RUNNING',
            phase='ORIGINAL_RX_COMPLETE_AND_CLASSICAL_CACHE_REUSED',review_ref=review_ref,
            exact_complete_cache_counts=POST_REBOOT_SOLVES,unentered_named_classical_solves=1648,
            interrupted_worker_execution_input_counts='UNKNOWN_DUE_REBOOT')
        raw_meta = execution.ctl.project(q['artifacts']['raw_current'],list(execution.current_owner.RAW_META),
            start='2023-01-01',stop='2026-01-01',run=RUN)
        inputs = execution.input_owner.RiskInputs(publication['publication'],matrix,current,raw_meta,
            source_review=review,source_review_ref=authority['runtime_source_review'])
        restore_input_gates(inputs,admission['gates'],execution,prior_review_ref=old['original_source_review'])
        for key in ('raw_current','pair_geometry'): execution.ctl.footer(q['artifacts'][key])
        raw = execution.pq.read_table(execution.ctl.pin(q['artifacts']['raw_current'])).to_pandas()
        geometry = execution.pq.read_table(execution.ctl.pin(q['artifacts']['pair_geometry'])).to_pandas()
        raw.signal_date = execution.pd.to_datetime(raw.signal_date)
        geometry.signal_date = execution.pd.to_datetime(geometry.signal_date)
        need(raw.signal_date.lt('2026-01-01').all() and geometry.signal_date.lt('2026-01-01').all(),
            'PREPARED_CLASSICAL_INPUT_PRE2026_LOCK')
        member = execution.membership
        need(tuple(member.ROLES) == (*CLASSICAL,'C14_D02','C14_G1','C14_G4'),
            'EXACT_FROZEN_MEMBERSHIP_ROSTER_REQUIRED')
        kernel = member.event.bind_pinned_kernel(member.execute_membership,physical_path=member.__file__,
            expected_sha256=review['source_pins'][str(Path(member.__file__).resolve())],
            dependencies={'ROLES':TERMINAL_CLASSICAL})
        results = [admission['completed'],*admission['rx_completed']]
        results.append(kernel(RUN,design,q,raw,geometry,matrix,inputs.get_risk,journal,
            authority['runtime_source_review'],role_gates=inputs.status()['roles'],
            qualification_ref=authority['input_qualification'],artifact_root=TERMINAL_ROOT))
        summary = execution.terminal(RUN,design,q,
            execution.read_exact(review['immutable_inputs']['ML_ASSEMBLY.json']),
            admission['values']['qualification'],results,journal,authority['runtime_source_review'],
            artifact_root=TERMINAL_ROOT,input_qualification_ref=authority['input_qualification'])
        terminal_ref = execution.ref(TERMINAL_ROOT/'RISK_DECISIONS_TERMINAL_R1.json')
        execution.stage(TERMINAL_ROOT/'PIPELINE_STATE.json',summary['status'],terminal=terminal_ref,
            joint_delivery_completed=False,coverage_sufficient_claim_allowed=False)
        execution.put(TERMINAL_ROOT/POST_REBOOT_AUDIT,dict(
            status='POST_REBOOT_CLASSICAL_ONLY_CHECKPOINT_TERMINAL',research_id=ID,
            review=review_ref,runtime_source_review=authority['runtime_source_review'],
            original_source_guard_review=authority['original_source_guard_review'],
            original_input_qualification=authority['input_qualification'],
            historical_qualification_counts=admission['values']['qualification']['counts'],
            prior_checkpoint_execution_input_counts=admission['values']['prior_audit']['execution_input_counts'],
            interrupted_worker_execution_input_counts='UNKNOWN_DUE_REBOOT',
            resumed_worker_execution_input_counts=inputs.status()['counts'],
            checkpoint_delta=authority['checkpoint_delta'],old_marker=authority['old_marker'],
            preserved_old_recovery_event=authority['old_recovery_event'],
            reused_completed_artifacts=authority['completed_role_artifacts'],
            reused_completed_fit_artifacts=authority['completed_fit_artifacts'],
            original_complete_cache_counts=POST_REBOOT_SOLVES,terminal=terminal_ref,
            RX_reopened=False,new_fit=0,scientific_retry=0,test2026_rows_read=0,
            publication_source_transport=transport_proof,joint_delivery_completed=False,
            coverage_sufficient_claim_allowed=False))
        return dict(status=summary['status'],terminal=terminal_ref,
            complete_conditional_roles=len(summary['complete_conditional_roles']),
            charged_solves=summary['charged_solves'],backend_entered=summary['backend_entered'],
            interrupted_worker_execution_input_counts='UNKNOWN_DUE_REBOOT',
            scientific_retry=0,test2026_rows_read=0,joint_delivery_completed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', required=True)
    parser.add_argument('--review-sha256', required=True)
    parser.add_argument('--validate-only', action='store_true')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--terminal-source-guard-recovery', action='store_true')
    modes.add_argument('--source-guard-classical-checkpoint', action='store_true')
    args = parser.parse_args()
    entry = (resume_source_guard_checkpoint if args.source_guard_classical_checkpoint else
        resume_terminal_recovery if args.terminal_source_guard_recovery else resume)
    result = entry(dict(path=args.review, sha256=args.review_sha256), validate_only=args.validate_only)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
