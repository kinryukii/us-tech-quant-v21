from __future__ import annotations
import hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def snap(): return {str(p.relative_to(ROOT)):(p.stat().st_size,p.stat().st_mtime_ns) for p in ROOT.rglob('*') if p.is_file()}
def main():
 before=snap(); cmd=['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/v22/run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1'),'-DailyPathReplayOnly'];r=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True);after=snap();changed=sorted(set(before)^set(after)|{p for p in before if p in after and before[p]!=after[p]}); forbidden=[p for p in changed if p.split('/')[0] in {'outputs','data','cache','.venv'} or p.endswith(('.parquet','.duckdb','.db','.zip','.pdf','.stdout.log','.stderr.log'))];out=Path(r'D:\us-tech-quant-results\storage_migration_r2a');out.mkdir(parents=True,exist_ok=True);payload={'status':'PASS' if r.returncode==0 and not forbidden else 'FAIL','returncode':r.returncode,'changed':changed,'forbidden':forbidden,'stdout':r.stdout,'stderr':r.stderr};(out/'repo_write_guard_report.json').write_text(json.dumps(payload,indent=2));print(json.dumps(payload));raise SystemExit(0 if payload['status']=='PASS' else 1)
if __name__=='__main__':main()
