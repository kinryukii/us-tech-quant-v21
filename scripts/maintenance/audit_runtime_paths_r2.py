from __future__ import annotations
import csv,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from common.storage_paths import resolve
EXT={'.py','.ps1','.bat','.cmd','.json','.yaml','.yml','.toml','.ini','.md'}
TOKENS=('outputs','data','cache','.venv','repo_root / "outputs"','repo_root / "data"','Path(__file__)')
def cls(p,line):
 s=str(p).replace('\\','/').lower();l=line.lower()
 if 'storage_migration_r1' in s or '/docs/' in s:return 'MIGRATION_MANIFEST_REFERENCE' if 'migration' in s else 'DOCUMENTATION_EXAMPLE'
 if '/test_' in s:return 'ACTIVE_RUNTIME_TEST'
 if '.bak' in p.name or 'archive' in s:return 'LEGACY_ARCHIVED_SCRIPT'
 if p.suffix=='.md':return 'DOCUMENTATION_EXAMPLE'
 if p.suffix in {'.py','.ps1','.bat','.cmd'}:
  if any(x in l for x in ('write','mkdir','copy','move','output-dir','out_rel','cache_root','output_dir')):return 'ACTIVE_RUNTIME_WRITE'
  if '.venv' in l or 'python.exe' in l:return 'ACTIVE_RUNTIME_INTERPRETER'
  if 'subprocess' in l or 'powershell' in l:return 'ACTIVE_RUNTIME_SUBPROCESS'
  return 'ACTIVE_RUNTIME_READ'
 return 'FALSE_POSITIVE'
def main():
 p=resolve(ROOT);out=p.results_root/'storage_migration_r2';out.mkdir(parents=True,exist_ok=True);rows=[]
 for f in ROOT.rglob('*'):
  if f.is_file() and f.suffix.lower() in EXT:
   for n,l in enumerate(f.read_text(encoding='utf-8',errors='ignore').splitlines(),1):
    if any(t in l for t in TOKENS):
     c=cls(f,l);rows.append({'file':str(f.relative_to(ROOT)),'line':n,'matched_text':l.strip(),'classification':c,'entrypoint_reachable':c.startswith('ACTIVE_RUNTIME'),'read_or_write':'WRITE' if 'WRITE' in c else 'READ','replacement_root':'storage_paths','planned_action':'refactor' if c.startswith('ACTIVE_RUNTIME') else 'allowlist','actual_action':'','validation_status':'PENDING'})
 with (out/'runtime_path_inventory.csv').open('w',newline='',encoding='utf-8') as h:w=csv.DictWriter(h,fieldnames=list(rows[0]) if rows else []);w.writeheader();w.writerows(rows)
 (out/'runtime_path_inventory.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
 entry='scripts/v22/run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1';edges=[]
 for r in rows:
  if r['file'].startswith(('scripts/v22/','scripts/v21/','scripts/common/')):edges.append({'from':entry if r['file'].endswith('.ps1') and '044' in r['file'] else r['file'],'to':r['file'],'classification':r['classification']})
 (out/'active_runtime_dependency_graph.json').write_text(json.dumps({'entrypoint':entry,'edges':edges},indent=2),encoding='utf-8')
 allow=[r for r in rows if not r['classification'].startswith('ACTIVE_RUNTIME')]
 (out/'legacy_path_allowlist.json').write_text(json.dumps(allow,indent=2),encoding='utf-8')
 print(json.dumps({'raw_path_match_count':len(rows),'active':sum(r['classification'].startswith('ACTIVE_RUNTIME') for r in rows)}))
if __name__=='__main__':main()
