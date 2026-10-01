"""Seal every substantive source file before/after a read-only review."""
from pathlib import Path
import argparse,hashlib,json
ROOT=Path(__file__).resolve().parent
SOURCE=ROOT.parent/'a2_multimodel_joint_20260928'
EXCLUDE={'.pyc','.pyo'}

def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def files():
    return sorted(p for p in SOURCE.rglob('*') if p.is_file() and p.suffix not in EXCLUDE
                  and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts)

def main():
    a=argparse.ArgumentParser();a.add_argument('phase',choices=['before','after']);arg=a.parse_args()
    path=ROOT/'FROZEN_SOURCE_BEFORE.json'
    current={str(p.relative_to(SOURCE)):{'sha256':sha(p),'bytes':p.stat().st_size} for p in files()}
    if arg.phase=='before':
        if path.exists():raise RuntimeError('Preserve original pre-review seal')
        receipt={'source':str(SOURCE),'files':current,'file_count':len(current),'total_bytes':sum(x['bytes'] for x in current.values())}
        path.write_text(json.dumps(receipt,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps({'phase':'before','file_count':len(current),'bytes':receipt['total_bytes']}))
    else:
        original=json.loads(path.read_text(encoding='utf-8'))['files']
        changed=[p for p in original if p not in current or original[p]!=current[p]]
        added=sorted(set(current)-set(original))
        receipt={'status':'PASS' if not changed and not added else 'FAIL','files_checked':len(original),
                 'changed_or_removed':changed,'added':added,'before_seal_sha256':sha(path)}
        (ROOT/'FROZEN_SOURCE_AFTER.json').write_text(json.dumps(receipt,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps(receipt,ensure_ascii=False))
        if changed or added:raise RuntimeError('Frozen source changed')

if __name__=='__main__':main()
