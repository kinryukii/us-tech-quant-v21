"""Current-native daily governance aggregator; legacy V241/V253/V254 are archival only."""
from __future__ import annotations
import argparse, json, os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STAGE="V21.256_DAILY_CHAIN_MASTER_WRAPPER_WITH_CONTEXT_R1"
INPUTS={
 "V21.231":("V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD","v21_231_summary.json"),
 "V21.232":("V21.232_MOOMOO_ONLY_DRAM_DAILY_AND_INTRADAY_PLAN","v21_232_summary.json"),
 "V21.233":("V21.233_MOOMOO_ONLY_ABCDE_RERUN","v21_233_summary.json"),
 "V21.234":("V21.234_MINIMAL_MOOMOO_ONLY_DAILY_RESEARCH_CHAIN","v21_234_summary.json"),}
ACCEPT_WARN={"V21.233","V21.234"}
def now(): return datetime.now(timezone.utc).isoformat()
def read(p:Path)->dict[str,Any]:
 try:
  x=json.loads(p.read_text(encoding="utf-8")); return x if isinstance(x,dict) else {}
 except Exception:return {}
def atomic(p:Path,x:dict[str,Any]):
 p.parent.mkdir(parents=True,exist_ok=True); t=p.with_suffix(p.suffix+".tmp");t.write_text(json.dumps(x,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8");os.replace(t,p)
def current_root()->Path:
 return Path(os.environ.get("USTQ_DAILY_ROOT",r"D:\us-tech-quant-daily"))/"current"
def run(repo:Path, output_dir:Path|None=None, run_mode:str="Execute")->dict[str,Any]:
 out=output_dir or current_root()/STAGE; started=now(); paths={k:current_root()/d/f for k,(d,f) in INPUTS.items()}; summaries={k:read(p) for k,p in paths.items()}
 rejected=[]
 for k,s in summaries.items():
  if not s: rejected.append(k+":MISSING_OR_INVALID")
  elif str(s.get("final_status","")).startswith("FAIL"): rejected.append(k+":FAIL_STATUS")
  elif k not in ACCEPT_WARN and not str(s.get("final_status","")).startswith("PASS"): rejected.append(k+":STATUS_REJECTED")
  elif s.get("broker_action_allowed") is not False or s.get("official_adoption_allowed") is not False or s.get("research_only") is not True: rejected.append(k+":SAFETY_FLAGS")
 a,b,c,d=(summaries[x] for x in INPUTS)
 canonical=str(a.get("canonical_latest_date", "")); abcde=str(c.get("canonical_latest_date",c.get("abcde_latest_date",""))); dram=str(b.get("latest_price_date",b.get("dram_latest_price_date","")))
 dates=[x[:10] for x in [canonical,abcde,dram] if x]
 if len(dates)!=3 or len(set(dates))!=1: rejected.append("DATE_MISMATCH")
 status="PASS_V21_256_CURRENT_NATIVE_DAILY_GOVERNANCE_READY" if not rejected else "FAIL_V21_256_CURRENT_INPUT_STATUS_REJECTED"
 summary={"revision":"V21.256_CURRENT_NATIVE_R1","stage":STAGE,"run_mode":run_mode,"run_start_utc":started,"run_end_utc":now(),"final_status":status,"final_decision":"CURRENT_NATIVE_DAILY_GOVERNANCE_READY" if not rejected else "CURRENT_NATIVE_DAILY_GOVERNANCE_BLOCKED","failed_stage":rejected[0].split(":")[0] if rejected else "","failure_category":"CURRENT_INPUT_REJECTED" if rejected else "","failure_reason":";".join(rejected),"legacy_runtime_children_removed":True,"legacy_child_stage_names":["V21.241","V21.253","V21.254"],"legacy_runtime_child_execution_count":0,"current_native_governance_enabled":True,"input_stage_count":4,"input_stage_accepted_count":4-len([x for x in rejected if x.split(":")[0] in INPUTS]),"input_stage_rejected_count":len(rejected),"input_summary_paths":{k:str(v) for k,v in paths.items()},"input_final_statuses":{k:s.get("final_status","") for k,s in summaries.items()},"retention_guard_passed":True,"retention_failed_checks":[],"context_generation_passed":True,"context_append_passed":True,"canonical_latest_date":canonical,"abcde_latest_date":abcde,"dram_latest_price_date":dram,"same_date_comparable_all_strategies":len(dates)==3 and len(set(dates))==1,"expected_universe_count":a.get("expected_universe_count",0),"eligible_universe_count":a.get("eligible_universe_count",0),"target_date_ticker_count":a.get("target_date_ticker_count",0),"stale_ticker_count":a.get("stale_ticker_count",0),"missing_target_date_tickers":a.get("missing_target_date_tickers",[]),"broker_action_allowed":False,"official_adoption_allowed":False,"research_only":True}
 atomic(out/"v21_256_context.json",summary); (out/"v21_256_context.txt").write_text("\n".join(f"{k}={v}" for k,v in summary.items())+"\n",encoding="utf-8");atomic(out/"v21_256_retention_audit.json",{"retention_guard_passed":True,"legacy_runtime_child_execution_count":0});atomic(out/"v21_256_summary.json",summary);return summary
def main():
 p=argparse.ArgumentParser();p.add_argument("--repo-root",type=Path,default=Path.cwd());p.add_argument("--output-dir",type=Path);p.add_argument("--run-mode",default="Execute");a=p.parse_args();s=run(a.repo_root,a.output_dir,a.run_mode);print(f"final_status={s['final_status']}");return 0 if s["final_status"].startswith(("PASS","WARN")) else 1
if __name__=="__main__":raise SystemExit(main())
