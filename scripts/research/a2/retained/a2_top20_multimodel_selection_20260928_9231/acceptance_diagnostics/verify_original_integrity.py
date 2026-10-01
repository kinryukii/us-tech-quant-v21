"""Verify the original batch and input files stayed unchanged during acceptance.

This proves preservation, not correctness of any original data or model.
"""
from pathlib import Path
import datetime
import hashlib
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    checked = []
    failures = []
    for name, base in [('ORIGINAL_SNAPSHOT.json', ROOT),
                       ('ORIGINAL_DATA_SNAPSHOT.json', None)]:
        snapshot = json.loads((HERE / name).read_text(encoding='utf-8'))
        for key, expected in snapshot['hashes'].items():
            path = base / key if base is not None else Path(key)
            observed = sha(path) if path.is_file() else None
            checked.append(str(path))
            if observed != expected:
                failures.append({'path': str(path), 'expected': expected,
                                 'observed': observed})
    result = {
        'verified_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'status': 'PASS_ORIGINAL_FILES_UNCHANGED' if not failures else 'FAIL',
        'checked_files': len(checked),
        'unique_files': len(set(checked)),
        'failures': failures,
        'scope': 'Original model/code/receipts/reports and all original parquet ledgers, '
                 'plus the six explicitly pinned upstream data files.',
        'does_not_prove': 'Correct source data, complete universe, historical vendor arrival, '
                          'certified shareholder returns, or untouched blind test.',
    }
    (HERE / 'ORIGINAL_INTEGRITY_VERIFICATION.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
