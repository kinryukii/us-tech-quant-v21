from __future__ import annotations
import argparse,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; SOFT=900*1024**2; HARD=1288490188
def main():
 p=argparse.ArgumentParser();p.add_argument('--json',required=True);a=p.parse_args(); rows=[];total=0
 for x in ROOT.rglob('*'):
  if x.is_file() and not x.is_symlink():
   n=x.stat().st_size;total+=n
   if n>50*1024**2: rows.append({'path':str(x),'size_bytes':n})
 out={'repo_root':str(ROOT),'repo_size_bytes':total,'soft_warning':total>SOFT,'hard_limit_bytes':HARD,'hard_limit_passed':total<=HARD,'large_files':sorted(rows,key=lambda r:r['size_bytes'],reverse=True)}
 Path(a.json).parent.mkdir(parents=True,exist_ok=True);Path(a.json).write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out))
if __name__=='__main__':main()
