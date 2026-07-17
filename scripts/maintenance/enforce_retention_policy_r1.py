"""Retention guard: defaults to reporting; only deletes explicit transient cache files in --execute."""
from __future__ import annotations
import argparse,json,sys
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from common.storage_paths import resolve
def main():
 a=argparse.ArgumentParser();a.add_argument('--execute',action='store_true');a.add_argument('--json',required=True);x=a.parse_args();p=resolve(ROOT);cut=datetime.now(timezone.utc)-timedelta(days=7);rows=[]
 for f in p.cache_root.rglob('*'):
  if f.is_file() and f.suffix.lower() in {'.tmp','.partial','.pyc'} and datetime.fromtimestamp(f.stat().st_mtime,timezone.utc)<cut:
   rows.append({'path':str(f),'deleted':False,'reason':'stale_transient_cache'})
   if x.execute:f.unlink();rows[-1]['deleted']=True
 Path(x.json).parent.mkdir(parents=True,exist_ok=True);Path(x.json).write_text(json.dumps({'mode':'EXECUTE' if x.execute else 'DRY_RUN','rows':rows},indent=2)+'\n')
if __name__=='__main__':main()
