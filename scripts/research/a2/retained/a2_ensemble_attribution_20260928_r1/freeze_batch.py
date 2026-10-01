"""Immutable-by-hash recoverable snapshot; never modifies the source batch."""
from pathlib import Path
from datetime import datetime, timezone
import argparse,hashlib,json,zipfile

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT.parent/'a2_buy_sell_cash_multimodel_20260928'
MANIFEST=ROOT/'FROZEN_BATCH_MANIFEST.json'
ARCHIVE=ROOT/'frozen_a2_buy_sell_cash_multimodel_20260928.zip'
SKIP={'__pycache__','.pytest_cache'}

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def write(path,obj):Path(path).write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding='utf-8')
def files():
    return sorted(p for p in SOURCE.rglob('*') if p.is_file() and not any(x in SKIP for x in p.relative_to(SOURCE).parts))

def freeze():
    if MANIFEST.exists() or ARCHIVE.exists():raise RuntimeError('EXISTING_FROZEN_SNAPSHOT_PRESERVED')
    verification=read(SOURCE/'VERIFICATION.json')
    assert verification['status']=='PASS_WITH_EXPLICIT_DATA_LIMITATIONS'
    assert verification['audited_scenarios']==70 and verification['replay_fit_attempts']==0
    paths=files();entries=[]
    for path in paths:
        entries.append(dict(relative_path=path.relative_to(SOURCE).as_posix(),bytes=path.stat().st_size,sha256=sha(path)))
    expected=verification['frozen_source_and_ledger_sha256']
    for path,digest in expected.items():assert sha(path)==digest,f'ORIGINAL_VERIFICATION_DRIFT:{path}'
    with zipfile.ZipFile(ARCHIVE,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as z:
        for path in paths:z.write(path,arcname=path.relative_to(SOURCE).as_posix())
    with zipfile.ZipFile(ARCHIVE) as z:
        assert len(z.infolist())==len(entries)
        for item in entries:
            with z.open(item['relative_path']) as f:
                assert hashlib.file_digest(f,'sha256').hexdigest()==item['sha256']
    for item in entries:assert sha(SOURCE/item['relative_path'])==item['sha256']
    assert [p.relative_to(SOURCE).as_posix() for p in files()]==[x['relative_path'] for x in entries]
    manifest=dict(status='FROZEN_BY_HASH_WITH_RECOVERABLE_SNAPSHOT',created_utc=datetime.now(timezone.utc).isoformat(),
        source=str(SOURCE),source_files=len(entries),source_bytes=sum(x['bytes'] for x in entries),
        files=entries,archive=str(ARCHIVE),archive_sha256=sha(ARCHIVE),archive_entries_content_verified=True,
        original_verification_sha256=sha(SOURCE/'VERIFICATION.json'),bound_dependency_sha256=expected,
        scenarios=70,independent_samples=0,independent_samples_note='70 is the scenario count, not independent statistical samples; this analysis adds none.',
        source_modified=False,fit_calls=0,new_replay_calls=0,
        prohibited=['refit','additional epochs or seeds','test-driven weight search','reopen sealed capacity paired experiment'])
    write(MANIFEST,manifest)
    print(json.dumps({k:manifest[k] for k in ['status','source_files','source_bytes','fit_calls','new_replay_calls']}),flush=True)

def verify():
    manifest=read(MANIFEST)
    assert sha(ARCHIVE)==manifest['archive_sha256']
    for item in manifest['files']:assert sha(SOURCE/item['relative_path'])==item['sha256'],item['relative_path']
    assert {p.relative_to(SOURCE).as_posix() for p in files()}=={x['relative_path'] for x in manifest['files']}
    for path,digest in manifest['bound_dependency_sha256'].items():assert sha(path)==digest,path
    receipt=dict(status='PASS',checked_utc=datetime.now(timezone.utc).isoformat(),source_files=len(manifest['files']),
                 bound_dependency_count=len(manifest['bound_dependency_sha256']),snapshot_sha256=manifest['archive_sha256'],
                 manifest_sha256=sha(MANIFEST),source_and_dependencies_unchanged=True,archive_unchanged=True,
                 fit_calls=0,new_replay_calls=0)
    write(ROOT/'FREEZE_VERIFICATION.json',receipt);print(json.dumps(receipt),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--verify',action='store_true');a=p.parse_args()
    verify() if a.verify else freeze()
