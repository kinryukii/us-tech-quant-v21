"""Completion gate and immutable artifact inventory; never trains a model."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def main():
    assert not (ROOT / 'COMPLETION.json').exists(), 'Final completion is write-once'
    checks = [
        ('panel_artifacts/PANEL_RECEIPT.json', 'PASS'),
        ('panel_artifacts/PANEL_VALIDATION.json', 'PASS'),
        ('panel_artifacts/LABEL_WARNING_RECEIPT.json', 'PASS'),
        ('meta_artifacts/FIT_RECEIPT.json', 'PASS'),
        ('meta_artifacts/META_VERIFICATION.json', 'PASS'),
        ('independent_audit/META_CONTRACT_AUDIT.json', 'PASS'),
        ('INDEPENDENT_LEDGER_CHECKS.json', 'PASS'),
        ('cash_diagnostic/CASH_DIAGNOSTIC_RECEIPT.json', 'PASS'),
        ('cash_diagnostic/INDEPENDENT_REVIEW.json', 'PASS'),
        ('OLD_SOURCE_AFTER.json', 'PASS'),
        ('evaluation_2025/cost_10/RECOVERY_PREFIX_PROOF.json', 'PASS'),
        ('paired_analysis/ANALYSIS_RECEIPT.json', 'FROZEN_PAIRED_ANALYSIS_COMPLETE'),
        ('RESEARCH_DISPOSITION.json', 'FROZEN_R1_NOT_ADOPTED'),
    ]
    gate = {}
    for name, status in checks:
        path = ROOT / name
        value = read(path)
        assert value['status'] == status, (name, value.get('status'))
        gate[name] = dict(status=status, sha256=sha(path))
    lock = read(ROOT / 'PRE_FIT_LOCK.json')
    assert sha(ROOT / 'EXPERIMENT_CONTRACT.md') == lock['contract_sha256']
    fit = read(ROOT / 'meta_artifacts/FIT_RECEIPT.json')
    assert fit['meta_fit_calls'] == 8 and fit['new_base_expert_fit_calls'] == 0 and fit['fit_2026_rows'] == 0
    for record in fit['fits']:
        for path_key, hash_key in [('artifact', 'artifact_sha256'),
                                   ('main_scaler_artifact', 'main_scaler_sha256'),
                                   ('interaction_scaler_artifact', 'interaction_scaler_sha256')]:
            assert sha(Path(record[path_key])) == record[hash_key]
    disposition = read(ROOT / 'RESEARCH_DISPOSITION.json')
    assert not disposition['uses_2026_results'] and not disposition['promoted_to_main_strategy']
    for path, expected in disposition['evidence_sha256'].items():
        assert sha(Path(path)) == expected
    completed = []
    required = ['DONE.json', 'RUNTIME_LOAD_RECEIPT.json', 'LEDGER_ACCEPTANCE.json',
                'action_diagnostics.parquet', 'target_decisions.parquet', 'positions.parquet',
                'trades.parquet', 'daily.parquet', 'signal_contexts.parquet', 'daily_meta_audit.parquet']
    for year in (2025, 2026):
        for cost in (5, 10, 25):
            parent = ROOT / f'evaluation_{year}/cost_{cost}'
            assert read(parent / 'COMPLETE.json')['status'] == 'FROZEN_PAIRED_REPLAY_COMPLETE'
            for method in ('M0', 'M1'):
                folder = parent / method
                for name in required:
                    assert (folder / name).is_file(), str(folder / name)
                done = read(folder / 'DONE.json')
                assert done['policy'] == method and done['year'] == year and done['cost_bps'] == cost
                assert done['stage'] == ('validation' if year == 2025 else 'final')
                assert done['fit_attempts'] == 0
                assert read(folder / 'LEDGER_ACCEPTANCE.json')['status'] == 'PASS'
                completed.append(dict(year=year, cost_bps=cost, model=method,
                    stage=done['stage'], done_sha256=sha(folder/'DONE.json'),
                    runtime_load_receipt_sha256=sha(folder/'RUNTIME_LOAD_RECEIPT.json')))
    assert len(completed) == 12
    assert (ROOT/'paired_analysis/2025_SELECTED_STATE_SUPPORT.json').is_file()
    assert read(ROOT/'delivery_tables/EXPORT_RECEIPT.json')['status'] == 'PASS'
    report = ROOT / 'REPORT.md'
    assert report.is_file() and (ROOT/'paired_analysis/paired_paths.png').is_file()
    assert 'TODO' not in report.read_text(encoding='utf-8')
    exclusions = {'COMPLETION.json', 'ARTIFACT_MANIFEST.json'}
    files = sorted(path for path in ROOT.rglob('*') if path.is_file()
                   and path.name not in exclusions and '__pycache__' not in path.parts
                   and '.pytest_cache' not in path.parts and path.suffix not in ('.pyc', '.pyo'))
    manifest = dict(status='FROZEN_DELIVERY_INVENTORY', files={str(p.relative_to(ROOT)):
        dict(size=p.stat().st_size, sha256=sha(p)) for p in files})
    manifest_path = ROOT / 'ARTIFACT_MANIFEST.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    result = dict(status='COMPLETE_AND_FROZEN', experiment='A2_CONTEXTUAL_STACKING_R1',
        completed_utc=datetime.now(timezone.utc).isoformat(), meta_fit_calls=8,
        base_expert_fit_calls=0, fit_2026_rows=0, completed_fixed_replays=12,
        old_files_unchanged=read(ROOT/'OLD_SOURCE_AFTER.json')['old_files_checked'],
        remaining_required_work=0, adopted=False, disposition=disposition['status'],
        uses_2026_for_selection=False, blind_test=False,
        result_limitations=['Retrospective nonblind research', 'Original price-index coordinate',
            'Inherited label-price warnings retained', 'Original 2026 pool and valuation certification limits retained'],
        stage_runtime_bindings=completed, verification=gate,
        report_path=str(report), report_sha256=sha(report),
        artifact_count=len(files), manifest_path=str(manifest_path), manifest_sha256=sha(manifest_path))
    (ROOT/'COMPLETION.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('status', 'completed_fixed_replays',
        'meta_fit_calls', 'old_files_unchanged', 'remaining_required_work', 'disposition', 'artifact_count')}, ensure_ascii=False))


if __name__ == '__main__': main()
