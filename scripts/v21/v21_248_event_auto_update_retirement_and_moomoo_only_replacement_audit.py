#!/usr/bin/env python
from __future__ import annotations
import argparse,csv,json,re
from pathlib import Path
from typing import Any

STAGE="V21.248_EVENT_AUTO_UPDATE_RETIREMENT_AND_MOOMOO_ONLY_REPLACEMENT_AUDIT"; OUT_REL=Path("outputs/v21")/STAGE
PAT=re.compile(r"(event|news|earnings|calendar|yfinance|yahoo|external)",re.I)
def wcsv(p:Path,d:list[dict[str,Any]],fields:list[str]):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open("w",encoding="utf-8",newline="") as f:
  wr=csv.DictWriter(f,fields,extrasaction="ignore",lineterminator="\n"); wr.writeheader(); wr.writerows(d)
def wjson(p:Path,d): p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(d,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
def scan(repo:Path):
 files=[]
 for root in [repo/"scripts/v21", repo/"config", repo]:
  if not root.exists(): continue
  pats=["*.py","*.ps1","*.json","*.yaml","*.yml"] if root!=repo else ["run_*.ps1"]
  for pat in pats:
   for p in root.glob(pat) if root==repo else root.rglob(pat):
    if p.is_file(): files.append(p)
 rows=[]; imports=[]; wrappers=[]; non=[]; outputs=[]
 for p in sorted(set(files)):
  try: text=p.read_text(encoding="utf-8",errors="ignore")
  except OSError: continue
  rel=p.relative_to(repo).as_posix() if p.is_relative_to(repo) else str(p)
  hit=bool(PAT.search(p.name) or PAT.search(text))
  if not hit: continue
  active=rel.startswith("scripts/v21/run_v21_234") or "DAILY_CHAIN_RETENTION" in text
  cls="KEEP_REQUIRED" if active else "DISABLE_READY"
  rows.append({"path":str(p),"relative_path":rel,"module_type":p.suffix.lower(),"event_auto_update_related":True,"active_chain_dependency":active,"retirement_decision":cls,"notes":"inventory only; no deletion"})
  if p.suffix.lower()==".py": imports.append({"path":str(p),"relative_path":rel,"contains_import_reference":"import" in text,"matched_terms":";".join(sorted(set(m.group(0).lower() for m in PAT.finditer(text))))[:200]})
  if p.suffix.lower()==".ps1": wrappers.append({"path":str(p),"relative_path":rel,"wrapper_reference":True,"active_chain_dependency":active})
  if re.search(r"(yfinance|yahoo|external|news|event)",text,re.I): non.append({"path":str(p),"relative_path":rel,"dependency_type":"NON_MOOMOO_OR_EVENT_REFERENCE","active_chain_dependency":active,"replacement_available":"MOOMOO_PRICE_ONLY_OR_PLACEHOLDER"})
 for p in (repo/"outputs/v21").glob("V21.*EVENT*") if (repo/"outputs/v21").exists() else []:
  outputs.append({"output_path":str(p),"relative_path":p.relative_to(repo).as_posix(),"dependency_status":"HISTORICAL_OUTPUT_ONLY","active_dependency":False})
 return rows,imports,wrappers,outputs,non
def run(repo:Path,out:Path|None=None):
 out=out or repo/OUT_REL; out.mkdir(parents=True,exist_ok=True)
 inv,imp,wrap,dep,non=scan(repo)
 coverage=[
  {"coverage_item":"daily_price_data","moomoo_only_replacement":"AVAILABLE","notes":"V21.231 canonical Moomoo snapshot"},
  {"coverage_item":"risk_event_metadata","moomoo_only_replacement":"PLACEHOLDER_ONLY","notes":"No reliable local Moomoo event source confirmed"},
  {"coverage_item":"event_auto_update","moomoo_only_replacement":"RETIRE_OR_DISABLE_CANDIDATE","notes":"Current research chain uses price-only Moomoo data"},
 ]
 plan=[]
 for r in inv:
  plan.append({"relative_path":r["relative_path"],"recommended_action":"KEEP_REQUIRED" if r["active_chain_dependency"] else "DISABLE_READY","next_verification":"disable first, rerun daily chain, then quarantine/delete only after verification","delete_now":False})
 decision="KEEP_REQUIRED" if any(r["active_chain_dependency"] for r in inv) else "DISABLE_READY"
 wcsv(out/"event_auto_update_module_inventory.csv",inv,["path","relative_path","module_type","event_auto_update_related","active_chain_dependency","retirement_decision","notes"])
 wcsv(out/"event_auto_update_import_reference_audit.csv",imp,["path","relative_path","contains_import_reference","matched_terms"])
 wcsv(out/"event_auto_update_wrapper_reference_audit.csv",wrap,["path","relative_path","wrapper_reference","active_chain_dependency"])
 wcsv(out/"event_auto_update_output_dependency_audit.csv",dep,["output_path","relative_path","dependency_status","active_dependency"])
 wcsv(out/"non_moomoo_fetch_dependency_audit.csv",non,["path","relative_path","dependency_type","active_chain_dependency","replacement_available"])
 wcsv(out/"moomoo_only_replacement_coverage_audit.csv",coverage,["coverage_item","moomoo_only_replacement","notes"])
 wcsv(out/"event_auto_update_retirement_plan.csv",plan,["relative_path","recommended_action","next_verification","delete_now"])
 s={"final_status":decision,"final_decision":"EVENT_AUTO_UPDATE_RETIREMENT_PLAN_READY_RESEARCH_ONLY","inventory_count":len(inv),"active_dependency_count":sum(1 for r in inv if r["active_chain_dependency"]),"non_moomoo_dependency_count":len(non),"warning_count":sum(1 for c in coverage if "PLACEHOLDER" in c["moomoo_only_replacement"]),"error_count":0,"broker_action_allowed":False,"official_adoption_allowed":False}
 wjson(out/"v21_248_summary.json",s); (out/"V21.248_event_auto_update_retirement_report.txt").write_text(f"{STAGE}\nfinal_status={decision}\nno_delete=True\n",encoding="utf-8"); return s
def main(argv=None):
 p=argparse.ArgumentParser(); p.add_argument("--repo-root",type=Path,default=Path(r"D:\us-tech-quant")); p.add_argument("--output-dir",type=Path)
 a=p.parse_args(argv); s=run(a.repo_root.resolve(),a.output_dir); print(str((a.output_dir or a.repo_root/OUT_REL)/"v21_248_summary.json")); return int(s["error_count"])
if __name__=="__main__": raise SystemExit(main())
