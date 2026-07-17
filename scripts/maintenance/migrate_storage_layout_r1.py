#!/usr/bin/env python
"""Auditable, collision-safe external storage migration (default: DryRun)."""
from __future__ import annotations
import argparse, csv, hashlib, json, os, shutil, sys, tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT / "scripts"))
from common.storage_paths import resolve, validate
RUN = "storage_migration_r1"
FIELDS = "source_path destination_path category size_bytes source_sha256 destination_sha256 source_mtime migration_action verification_status deletion_status collision_resolution error".split()

def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
def files(root: Path):
    if root.exists():
        for p in root.rglob("*"):
            if p.is_file() and not p.is_symlink(): yield p
def write_json(path,payload): path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(payload,indent=2,ensure_ascii=False,default=str)+"\n",encoding="utf-8")
def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",newline="",encoding="utf-8") as f: w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)
def category(rel: Path) -> str:
    s=rel.as_posix().lower(); n=rel.name.lower()
    if rel.parts and rel.parts[0]==".venv": return "envs"
    if rel.parts and rel.parts[0]=="cache": return "cache"
    if any(x in s for x in ("backtest","r9","bootstrap","permutation","random_")): return "backtest"
    if n.endswith((".pdf",".zip",".html")) or "/reports/" in s or "/bundle" in s: return "results"
    if "/v22.040_" in s or "/v22.044_" in s or "/v21.233_" in s or "/v21.231_" in s: return "daily"
    return "results"
def destination(paths, rel):
    cat=category(rel); root=getattr(paths,cat+"_root")
    if cat == "envs" and rel.parts[0] == ".venv":
        return cat, root / ".venv" / Path(*rel.parts[1:])
    # preserve provenance while preventing unrelated names from colliding
    return cat, root / "migrated_from_repo" / rel
def audit(paths, out: Path):
    roots={"repo":paths.repo_root,"backtests":paths.backtest_root,"cache":paths.cache_root,"daily":paths.daily_root,"data":paths.data_root,"envs":paths.envs_root,"results":paths.results_root}
    root_rows=[]; largest=[]; groups=defaultdict(list); ext=Counter()
    for name,root in roots.items():
        total=count=dirs=0; children=Counter()
        for p in files(root):
            size=p.stat().st_size; total+=size;count+=1; ext[p.suffix.lower() or "[none]"]+=size
            rel=p.relative_to(root); children[rel.parts[0] if rel.parts else "[root]"]+=size
            record={"root":name,"path":str(p),"size_bytes":size,"mtime_utc":datetime.fromtimestamp(p.stat().st_mtime,timezone.utc).isoformat(),"extension":p.suffix.lower()}
            if size>=20*1024*1024: largest.append(record)
            groups[sha(p)].append(record)
        if root.exists(): dirs=sum(1 for p in root.rglob("*") if p.is_dir())
        root_rows.append({"root":name,"path":str(root),"bytes":total,"file_count":count,"dir_count":dirs,"top_level_bytes":dict(children)})
    largest=sorted(largest,key=lambda x:x["size_bytes"],reverse=True)[:300]
    dup=[{"sha256":h,"file_count":len(v),"total_bytes":sum(x["size_bytes"] for x in v),"paths":" | ".join(x["path"] for x in v)} for h,v in groups.items() if len(v)>1]
    write_json(out/"storage_audit_before.json",{"created_at_utc":datetime.now(timezone.utc).isoformat(),"roots":root_rows,"extension_bytes":dict(ext),"large_file_count":len(largest),"duplicate_group_count":len(dup)})
    write_csv(out/"storage_audit_before.csv",root_rows,["root","path","bytes","file_count","dir_count","top_level_bytes"])
    write_csv(out/"largest_files_before.csv",largest,["root","path","size_bytes","mtime_utc","extension"])
    write_csv(out/"duplicate_hash_groups_before.csv",dup,["sha256","file_count","total_bytes","paths"])
def hardcoded_audit(out: Path):
    pats=("D:\\us-tech-quant\\outputs","D:\\us-tech-quant\\data","D:\\us-tech-quant\\cache","D:\\us-tech-quant\\.venv","outputs\\","data\\","cache\\",".venv\\","Path(__file__)","repo_root / \"outputs\"","repo_root / \"data\"")
    exts={".py",".ps1",".bat",".cmd",".json",".yaml",".yml",".toml",".ini",".md"}; lines=[]
    for p in files(ROOT):
        if p.suffix.lower() in exts:
            try: text=p.read_text(encoding="utf-8",errors="ignore")
            except OSError: continue
            for no,line in enumerate(text.splitlines(),1):
                if any(x in line for x in pats): lines.append(f"{p.relative_to(ROOT)}:{no}:{line}")
    (out/"hardcoded_path_audit.txt").write_text("\n".join(lines)+"\n",encoding="utf-8"); return len(lines)
def migration_rows(paths):
    for base in (ROOT/"cache",ROOT/"outputs"):
        for source in files(base):
            rel=source.relative_to(ROOT); cat,dest=destination(paths,rel); st=source.stat()
            yield {"source_path":str(source),"destination_path":str(dest),"category":cat,"size_bytes":st.st_size,"source_sha256":"","destination_sha256":"","source_mtime":datetime.fromtimestamp(st.st_mtime,timezone.utc).isoformat(),"migration_action":"move_verified","verification_status":"PENDING","deletion_status":"NOT_STARTED","collision_resolution":"","error":""}
    venv = ROOT / ".venv"
    if venv.is_symlink():
        target = venv.resolve()
        yield {"source_path":str(venv),"destination_path":str(target),"category":"envs","size_bytes":0,"source_sha256":"","destination_sha256":"","source_mtime":"","migration_action":"remove_repo_junction_after_validation","verification_status":"TARGET_EXTERNAL_EXISTS" if target.exists() else "FAILED","deletion_status":"NOT_STARTED","collision_resolution":"not_a_data_move","error":"" if target.exists() else "external venv target missing"}
def transfer(row, execute):
    src=Path(row["source_path"]); dst=Path(row["destination_path"])
    if row["migration_action"] == "remove_repo_junction_after_validation":
        if not dst.exists(): raise RuntimeError("external environment target missing")
        if execute: src.unlink(); row["deletion_status"]="REPO_JUNCTION_REMOVED"
        row["verification_status"]="TARGET_EXTERNAL_EXISTS"; return row
    row["source_sha256"]=sha(src)
    if dst.exists():
        got=sha(dst); row["destination_sha256"]=got
        if got==row["source_sha256"]: row.update(migration_action="duplicate_identical",verification_status="HASH_MATCH",collision_resolution="retain_destination")
        else:
            dst=dst.with_name(dst.stem+"__"+row["source_sha256"][:12]+dst.suffix); row["destination_path"]=str(dst); row["collision_resolution"]="renamed_hash_prefix"
    if not execute: row["verification_status"]="DRY_RUN";return row
    if not dst.exists():
        dst.parent.mkdir(parents=True,exist_ok=True); temp=dst.with_name(dst.name+".partial")
        if temp.exists(): temp.unlink()
        shutil.copy2(src,temp)
        if temp.stat().st_size!=src.stat().st_size or sha(temp)!=row["source_sha256"]: temp.unlink(missing_ok=True);raise RuntimeError("copy hash mismatch")
        os.replace(temp,dst); row["destination_sha256"]=sha(dst)
    if row["destination_sha256"]!=row["source_sha256"]: raise RuntimeError("destination hash mismatch")
    row["verification_status"]="HASH_MATCH"; src.unlink();row["deletion_status"]="SOURCE_REMOVED";return row
def main():
    ap=argparse.ArgumentParser();g=ap.add_mutually_exclusive_group();g.add_argument("--dry-run",action="store_true");g.add_argument("--execute",action="store_true");g.add_argument("--verify-only",action="store_true");ap.add_argument("--resume",action="store_true");ap.add_argument("--skip-cache-cleanup",action="store_true");a=ap.parse_args();paths=resolve(ROOT);out=paths.results_root/RUN
    if a.verify_only:
        rows=[]
        for p in files(out):
            if p.name=="migration_manifest.csv": continue
        print(json.dumps({"status":"VERIFY_ONLY_READY","manifest":str(out/"migration_manifest.csv")}));return
    validate(paths,require_writable=a.execute); audit(paths,out);hard=hardcoded_audit(out); rows=[];errors=[]
    for row in migration_rows(paths):
        try: rows.append(transfer(row,a.execute))
        except Exception as e: row["error"]=repr(e);row["verification_status"]="FAILED";errors.append(row);rows.append(row)
    write_csv(out/"migration_manifest.csv",rows,FIELDS); (out/"migration_manifest.jsonl").write_text("".join(json.dumps(r)+"\n" for r in rows),encoding="utf-8"); (out/"migration_errors.jsonl").write_text("".join(json.dumps(r)+"\n" for r in errors),encoding="utf-8")
    summary={"status":"PASS" if not errors else "FAIL","mode":"EXECUTE" if a.execute else "DRY_RUN","files_considered":len(rows),"files_moved":sum(r["deletion_status"]=="SOURCE_REMOVED" for r in rows),"bytes_moved":sum(int(r["size_bytes"]) for r in rows if r["deletion_status"]=="SOURCE_REMOVED"),"review_required_count":0,"migration_error_count":len(errors),"hardcoded_paths_found":hard};write_json(out/"migration_summary.json",summary);print(json.dumps(summary))
if __name__=="__main__": main()
