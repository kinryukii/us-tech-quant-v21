"""Seal old batches and bind the new experiment contract before any meta fitting."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json

ROOT = Path(__file__).resolve().parent
WS = ROOT.parent
OLD = [WS / 'a2_multimodel_joint_20260928', WS / 'a2_multimodel_joint_review_20260928']

def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def write(name, obj):
    (ROOT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')

def substantive():
    return sorted(p for folder in OLD for p in folder.rglob('*') if p.is_file()
                  and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts
                  and p.suffix not in ('.pyc', '.pyo'))

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('phase', choices=['before', 'after'])
    phase = parser.parse_args().phase
    current = {str(p): sha(p) for p in substantive()}
    if phase == 'before':
        if (ROOT / 'PRE_FIT_LOCK.json').exists():
            raise RuntimeError('Preserve initial lock')
        request = Path('C:/Users/Lenovo/.codex/attachments/51c3eac3-4258-4fa5-8cde-02f357dd9b2f/已粘贴的文本.txt')
        inputs = [WS/'a2_latest_effective_joint_20260927/data/pre2026_joint_context.parquet',
                  WS/'a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet',
                  WS/'a2_latest_effective_joint_20260927/data/calendar.parquet',
                  OLD[0]/'data/test_features_context.parquet', OLD[0]/'data/test_prices.parquet',
                  WS/'a2_qualification_holdings_v1_20260927/data/operational_exit_evidence.csv']
        write('OLD_SOURCE_BEFORE.json', dict(files=current, roots=list(map(str, OLD))))
        write('PRE_FIT_LOCK.json', dict(status='PRE_FIT_LOCKED', created_utc=datetime.now(timezone.utc).isoformat(),
              experiment='A2_CONTEXTUAL_STACKING_R1', contract_sha256=sha(ROOT/'EXPERIMENT_CONTRACT.md'),
              user_request_sha256=sha(request), frozen_old_files=len(current),
              input_sha256={str(p): sha(p) for p in inputs},
              old_source_seal_sha256=sha(ROOT/'OLD_SOURCE_BEFORE.json'),
              state_fields=['cash_weight','current_weight','available_slots','realized_vol_20d'],
              interaction_multipliers=[4,16,64], alpha_main=100,
              main_cost_bps=10, sensitivity_cost_bps=[5,25],
              select_period='2024 only; signal split 2024-10-01 with mature-label purge',
              fit_2026_rows=0, base_expert_fits=0, planned_meta_fit_calls=8))
        print(json.dumps(dict(status='PRE_FIT_LOCKED', old_files=len(current)), ensure_ascii=False))
    else:
        original=json.loads((ROOT/'OLD_SOURCE_BEFORE.json').read_text(encoding='utf-8'))['files']
        lock=json.loads((ROOT/'PRE_FIT_LOCK.json').read_text(encoding='utf-8'))
        changed=[p for p in original if current.get(p)!=original[p]]
        added=sorted(set(current)-set(original))
        input_changed=[p for p,h in lock['input_sha256'].items() if sha(p)!=h]
        assert sha(ROOT/'EXPERIMENT_CONTRACT.md')==lock['contract_sha256']
        result=dict(status='PASS' if not changed and not added and not input_changed else 'FAIL',
                    old_files_checked=len(original), changed_or_removed=changed, added=added,
                    experiment_inputs_changed=input_changed,
                    contract_sha256=lock['contract_sha256'])
        write('OLD_SOURCE_AFTER.json', result)
        print(json.dumps(result, ensure_ascii=False))
        assert result['status']=='PASS'

if __name__=='__main__': main()
