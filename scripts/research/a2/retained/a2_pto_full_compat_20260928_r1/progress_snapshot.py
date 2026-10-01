"""Read-only replay progress, with a durable resume snapshot. No learning."""
from common import ROOT, json, write_json
from datetime import datetime, timezone


def main():
    rows = []
    for year in (2025, 2026):
        complete, failed, active = [], [], []
        for i in range(36):
            folder = ROOT / f'results/{year}/batch_{i:03d}'
            if (folder / 'COMPLETE.json').exists():
                r = json.loads((folder / 'COMPLETE.json').read_text(encoding='utf-8'))
                complete.append(r)
            elif (folder / 'FAILED.json').exists():
                failed.append(json.loads((folder / 'FAILED.json').read_text(encoding='utf-8')))
            elif folder.exists():
                saved = sorted((folder / 'decision_coverage').glob('*.npz'))
                last = saved[-1].stem.removesuffix('_experts') if saved else None
                active.append({'batch': folder.name, 'last_saved_signal': last})
        rows.append({'year': year, 'complete_batches': len(complete),
                     'complete_accounts': sum(r['accounts'] for r in complete),
                     'failed_batches': len(failed), 'active': active})
    result = {'created_utc': datetime.now(timezone.utc).isoformat(),
              'learning_frozen': (ROOT / 'FREEZE.json').exists(),
              'results': rows, 'full_pool_status': 'BLOCKED_DATA'}
    watch = ROOT / 'audits/VERIFICATION_WATCH_STATUS.json'
    if watch.exists():
        w = json.loads(watch.read_text(encoding='utf-8'))
        result['independent_watch_status'] = w['status']
    write_json(ROOT / 'CURRENT_PROGRESS.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
