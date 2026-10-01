"""Write-once seal for a known calibration intervention, using absolute sources."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OLD = ROOT.parent / 'a2_pto_full_compat_20260928_r2'

def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str,
                               allow_nan=False), encoding='utf-8')

def verify_freeze():
    marker = ROOT / 'FROZEN_BEFORE_2026.json'
    if not marker.exists():
        raise RuntimeError('NEW_BATCH_FREEZE_REQUIRED')
    receipt = read(marker)
    mismatches = [name for name, digest in receipt['bindings'].items()
                  if not Path(name).is_file() or sha(name) != digest]
    if mismatches:
        raise RuntimeError('FROZEN_SOURCE_CHANGED:' + ','.join(mismatches))
    return receipt

def freeze():
    marker = ROOT / 'FROZEN_BEFORE_2026.json'
    if marker.exists():
        return verify_freeze()
    if (ROOT / 'predictions/evaluation_2026').exists():
        raise RuntimeError('NEW_2026_INFERENCE_ALREADY_STARTED')
    required = ['EXPERIMENT_CONTRACT.md', 'PREDECLARED_PATHS.csv',
                'BASELINE_CORRECTION.json', 'BASELINE_TEST_RECEIPT.json',
                'A2_REUSE_AUDIT.json', 'A2_ADAPTER_STATUS.json', 'A2_TEST_RECEIPT.json',
                'baseline_correction.py', 'a2_adapter.py',
                'run_retest.py', 'analyze_retest.py', 'integrity.py']
    missing = [name for name in required if not (ROOT / name).is_file()]
    if missing:
        raise RuntimeError('PREREQUISITES_MISSING:' + ','.join(missing))
    baseline = read(ROOT / 'BASELINE_CORRECTION.json')
    if (baseline.get('read_2026_rows') != 0 or baseline.get('fit_calls') != 0 or
            baseline.get('fit_2026_rows', 0) or baseline.get('read_2026_numeric_rows', 0)):
        raise RuntimeError('BASELINE_USED_TEST_DATA')
    if read(ROOT / 'BASELINE_TEST_RECEIPT.json').get('status') != 'PASS':
        raise RuntimeError('BASELINE_TESTS_REQUIRED')
    if read(ROOT / 'A2_TEST_RECEIPT.json').get('status') != 'PASS':
        raise RuntimeError('A2_ADAPTER_TESTS_REQUIRED')
    a2_state = read(ROOT / 'A2_ADAPTER_STATUS.json')
    if (a2_state.get('fit_2026_rows', 0) or a2_state.get('base_model_fit_calls', 0) or
            {item['stage'] for item in a2_state['records']} != {'validation', 'final'}):
        raise RuntimeError('A2_PREPARATION_LEARNING_CONTRACT_INVALID')
    for item in a2_state['records']:
        if item['status'] not in {'TRAINED', 'FAILED_ADAPTER'}:
            raise RuntimeError('UNRESOLVED_A2_ADAPTER')
        if item['status'] == 'TRAINED' and str(item['max_label_end'])[:10] >= item['fit_cutoff_exclusive']:
            raise RuntimeError('A2_ADAPTER_LABEL_NOT_MATURE')
    original = read(OLD / 'FROZEN_BEFORE_2026.json')
    bindings = {str(OLD / name): digest for name, digest in original['bindings'].items()}
    bindings[str(OLD / 'FROZEN_BEFORE_2026.json')] = sha(OLD / 'FROZEN_BEFORE_2026.json')
    # Includes current adapters and their pre-test-only fit records, never outputs.
    for folder in [ROOT, ROOT / 'models', ROOT / 'audits']:
        for path in folder.iterdir() if folder == ROOT else folder.rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.name not in {
                'RUN_STATE.json', 'FROZEN_BEFORE_2026.json', 'REPLAY_STARTED.json'}:
                bindings[str(path)] = sha(path)
    for year in [2025, 2026]:
        prediction = OLD / 'predictions' / f'evaluation_{year}'
        complete = prediction / 'COMPLETE.json'
        bindings[str(complete)] = sha(complete)
        for name, digest in read(complete)['artifacts'].items():
            bindings[str(prediction / name)] = digest
        for relative in ['ALL_PATHS.csv', 'pto/SUMMARY.csv', 'rl_control/DONE.json']:
            path = OLD / 'results' / f'evaluation_{year}' / relative
            bindings[str(path)] = sha(path)
        rl = OLD / 'results' / f'evaluation_{year}' / 'rl_control'
        for name, digest in read(rl / 'DONE.json')['artifacts'].items():
            bindings[str(rl / name)] = digest
    # A2 originals are explicitly bound by the adapter/audit, including FAILED cases.
    a2 = read(ROOT / 'A2_REUSE_AUDIT.json')
    for key in ['source_bindings', 'bindings', 'sources_sha256']:
        for name, digest in a2.get(key, {}).items():
            if isinstance(digest, str) and len(digest) == 64:
                bindings[str(name)] = digest
    reference = OLD.parent / 'original_A2_scores_common_account_reference_r1'
    for name in ['REFERENCE_CONTRACT.md', 'reference_policy.py']:
        bindings[str(reference / name)] = sha(reference / name)
    changed = [name for name, digest in bindings.items()
               if not Path(name).is_file() or sha(name) != digest]
    if changed:
        raise RuntimeError('PRE_FREEZE_SOURCE_DRIFT:' + ','.join(changed))
    receipt = {'status': 'KNOWN_INTERVENTION_BATCH_FROZEN',
               'created_utc': datetime.now(timezone.utc).isoformat(),
               'bindings': bindings, 'blind_test': False,
               'prior_2026_exposure_preserved': True,
               'new_2026_inference_started': False,
               'formal_full_pool_status': 'BLOCKED_DATA',
               'no_post_test_selection_or_tuning': True}
    with marker.open('x', encoding='utf-8') as handle:
        json.dump(receipt, handle, ensure_ascii=False, indent=2, allow_nan=False)
    return verify_freeze()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    receipt = verify_freeze() if args.verify else freeze()
    print(receipt['status'], len(receipt['bindings']), 'bound files', flush=True)
