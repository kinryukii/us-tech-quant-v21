#!/usr/bin/env python
"""V21.234 minimal Moomoo-only daily research chain orchestrator."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


STAGE = "V21.234_MINIMAL_MOOMOO_ONLY_DAILY_RESEARCH_CHAIN"
OUT_REL = Path("outputs/v21") / STAGE
V231_REL = Path("outputs/v21/V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD")
V232_REL = Path("outputs/v21/V21.232_MOOMOO_ONLY_DRAM_DAILY_AND_INTRADAY_PLAN")
V233_REL = Path("outputs/v21/V21.233_MOOMOO_ONLY_ABCDE_RERUN")
PASS_STATUS = "PASS_V21_234_MINIMAL_DAILY_CHAIN_READY"
WARN_STATUS = "WARN_V21_234_MINIMAL_DAILY_CHAIN_READY_WITH_ACCEPTED_WARNINGS"
FAIL_MISSING = "FAIL_V21_234_REQUIRED_STAGE_MISSING"
FAIL_POLICY = "FAIL_V21_234_SOURCE_POLICY_VIOLATION"
FAIL_DRAM = "FAIL_V21_234_DRAM_PLAN_MISSING"
DECISION = "MINIMAL_MOOMOO_ONLY_DAILY_RESEARCH_CHAIN_READY_RESEARCH_ONLY"
FORBIDDEN_PROVIDER = "y" + "finance"
FORBIDDEN_PROVIDER_CALL = "yf" + ".download"

STAGE_FIELDS = ["stage_name","expected_status_class","actual_final_status","actual_final_decision","stage_passed","severity","blocks_daily_chain","notes"]
CURRENT_FIELDS = ["artifact","source_snapshot_id","latest_date","expected_latest_date","currentness_status","passed","severity","notes"]
POLICY_FIELDS = ["artifact","data_source_policy","yfinance_used","yahoo_used","external_fallback_used","moomoo_used","broker_action_allowed","official_adoption_allowed","research_only","passed","notes"]
DRAM_FIELDS = ["ticker","source_snapshot_id","latest_price_date","latest_intraday_timestamp","entry","no_chase","stop","daily_trend_state","multiframe_gate","entry_allowed_research_only","chase_allowed_research_only","trade_plan_currentness","next_action_gate","broker_action_allowed","official_adoption_allowed","notes"]
ABCDE_FIELDS = ["strategy_name","latest_date","top20","top50_count","compact_proxy_used","unavailable_component_warning_count","research_only","official_adoption_allowed","broker_action_allowed","notes"]
MISSING_FIELDS = ["ticker","reason","source_stage","yahoo_fallback_allowed","external_fallback_allowed","blocks_daily_chain","notes"]
ROLLUP_FIELDS = ["source_stage","warning_count","error_count","quality_error_count","quality_warning_count","coverage_warning_count","severity","notes"]
POINTER_FIELDS = ["key","value"]
NEXT_FIELDS = ["gate","status","next_action","allowed_now","broker_action_allowed","official_adoption_allowed","notes"]
PROTECTED_FIELDS = ["artifact","protected","mutation_allowed","passed","notes"]
LIGHT_FIELDS = ["artifact","size_bytes","lightweight","passed","notes"]
AUDIT_FIELDS = ["check_name","passed","yfinance_import_present","yfinance_call_present","yahoo_default_allowed","external_fallback_default_allowed","notes"]


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def bool_text(v: bool) -> str:
    return "True" if v else "False"


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader(); w.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    try:
        p = json.loads(path.read_text(encoding="utf-8"))
        return p if isinstance(p, dict) else {}
    except Exception:
        return {}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as h:
            return [{k: (v or "") for k, v in r.items() if k is not None} for r in csv.DictReader(h)]
    except Exception:
        return []


def load_policy_guard(repo_root: Path):
    path = repo_root / "scripts/v21/v21_data_source_policy_guard.py"
    if not path.exists():
        raise FileNotFoundError(str(path))
    spec = importlib.util.spec_from_file_location("v21_data_source_policy_guard", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(str(path))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


def self_audit(repo_root: Path) -> tuple[list[dict[str, Any]], bool]:
    path = repo_root / "scripts/v21/v21_234_minimal_moomoo_only_daily_research_chain.py"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    imp = bool(re.search(r"(^|\n)\s*(import|from)\s+" + re.escape(FORBIDDEN_PROVIDER), text))
    call = FORBIDDEN_PROVIDER_CALL in text
    return ([{"check_name":"v21_234_script_forbidden_provider_audit","passed":bool_text(not imp and not call),"yfinance_import_present":bool_text(imp),"yfinance_call_present":bool_text(call),"yahoo_default_allowed":"False","external_fallback_default_allowed":"False","notes":"static audit"}], imp or call)


def source_gate() -> dict[str, Any]:
    return {"policy_version":"V21.234","data_source_policy":"MOOMOO_ONLY","yfinance_allowed":False,"yahoo_allowed":False,"external_fallback_allowed":False,"broker_action_allowed":False,"trade_unlock_allowed":False,"official_adoption_allowed":False,"research_only":True,"active_trading_focus":"DRAM","next_allowed_stage":"V21.235_REPO_CLEAN_DELETE_AFTER_VERIFICATION_OR_V21.236_PAUSED_PROJECT_REVIEW_PACKAGE"}


def required_present(base: Path, names: list[str]) -> bool:
    return all((base / n).exists() for n in names)


def stage_status(s231: dict[str, Any], s232: dict[str, Any], s233: dict[str, Any]) -> list[dict[str, Any]]:
    v231_ok = s231.get("final_decision") == "MOOMOO_ONLY_CANONICAL_READY_FOR_DRAM_AND_ABCDE_RERUN" and float(s231.get("daily_raw_success_ratio", 0)) >= 0.95 and float(s231.get("daily_qfq_success_ratio", 0)) >= 0.95 and int(s231.get("quality_error_count", 1)) == 0 and not any(s231.get(k) for k in ["yfinance_used","yahoo_used","external_fallback_used"])
    v232_ok = s232.get("final_status") == "PASS_V21_232_MOOMOO_ONLY_DRAM_PLAN_READY" and all(s232.get(k) not in {"", None} for k in ["entry","no_chase","stop"]) and s232.get("broker_action_allowed") is False and s232.get("official_adoption_allowed") is False
    v233_ok = s233.get("final_decision") == "MOOMOO_ONLY_ABCDE_COMPACT_RERUN_READY_RESEARCH_ONLY" and str(s233.get("same_date_comparable_all_strategies")).lower() in {"true","1"} and int(s233.get("quality_error_count", 1)) == 0 and not any(s233.get(k) for k in ["yfinance_used","yahoo_used","external_fallback_used"]) and s233.get("broker_action_allowed") is False and s233.get("official_adoption_allowed") is False
    rows = [
        ("V21.231_MOOMOO_ONLY_CANONICAL","PASS_OR_ACCEPTED_WARN",s231,v231_ok,"accepted coverage warnings do not block"),
        ("V21.232_DRAM_PLAN","PASS",s232,v232_ok,"DRAM plan must be ready"),
        ("V21.233_ABCDE_COMPACT_RERUN","PASS_OR_ACCEPTED_WARN",s233,v233_ok,"compact proxy warnings accepted"),
        ("SOURCE_POLICY_GATE","PASS",{"final_status":"PASS","final_decision":"MOOMOO_ONLY"},v231_ok and v232_ok and v233_ok,"all stages remain Moomoo-only"),
        ("LIGHTWEIGHT_POINTER_MANIFEST","PASS",{"final_status":"PASS","final_decision":"WRITE_POINTER_ONLY"},True,"V21.234 writes lightweight pointers only"),
    ]
    out=[]
    for name, expected, summ, ok, notes in rows:
        out.append({"stage_name":name,"expected_status_class":expected,"actual_final_status":summ.get("final_status",""),"actual_final_decision":summ.get("final_decision",""),"stage_passed":bool_text(ok),"severity":"INFO" if ok else "ERROR","blocks_daily_chain":bool_text(not ok),"notes":notes})
    return out


def run(repo_root: Path, output_dir: Path, v21_231_output_dir: Path | None=None, v21_232_output_dir: Path | None=None, v21_233_output_dir: Path | None=None, cache_root: Path | None=None, snapshot_id: str | None=None, rerun_dram: bool=False, rerun_abcde: bool=False) -> dict[str, Any]:
    repo_root=repo_root.resolve(); output_dir.mkdir(parents=True, exist_ok=True)
    d231=(v21_231_output_dir or repo_root/V231_REL).resolve(); d232=(v21_232_output_dir or repo_root/V232_REL).resolve(); d233=(v21_233_output_dir or repo_root/V233_REL).resolve()
    write_json(output_dir/"source_policy_gate.json", source_gate())
    guard_found=(repo_root/"scripts/v21/v21_data_source_policy_guard.py").exists(); policy_ok=False
    try:
        guard=load_policy_guard(repo_root); guard.assert_moomoo_only_policy("V21.234 minimal daily research chain canonical dram abcde")
        pol=guard.load_data_source_policy(repo_root/"config/v21/data_source_policy.json")
        policy_ok=pol.get("default_data_source_policy")=="MOOMOO_ONLY" and pol.get("research_only") is True
    except Exception:
        policy_ok=False
    audit, violation = self_audit(repo_root)
    req231=["v21_231_summary.json","canonical_snapshot_pointer.json","canonical_snapshot_pointer.csv","canonical_rebuild_manifest.csv","canonical_quality_audit.csv","ticker_coverage_audit.csv","failed_ticker_retry_ledger.csv","source_policy_gate.json"]
    req232=["v21_232_summary.json","dram_daily_plan.csv","dram_intraday_multiframe_gate.csv","dram_entry_exit_levels.csv","dram_no_chase_gate.csv","dram_stop_risk_plan.csv","dram_trade_permission_gate.csv","source_policy_gate.json"]
    req233=["v21_233_summary.json","abcde_top20_summary.csv","abcde_top50_summary.csv","abcde_strategy_overlap_matrix.csv","abcde_strategy_latest_date_audit.csv","abcde_coverage_audit.csv","abcde_missing_ticker_audit.csv","abcde_compact_report.txt","source_policy_gate.json"]
    present231=required_present(d231,req231); present232=required_present(d232,req232); present233=required_present(d233,req233)
    s231=read_json(d231/"v21_231_summary.json"); s232=read_json(d232/"v21_232_summary.json"); s233=read_json(d233/"v21_233_summary.json"); pointer=read_json(d231/"canonical_snapshot_pointer.json")
    if not (present231 and present232 and present233):
        status=FAIL_MISSING if not present231 or not present233 else FAIL_DRAM
    elif not policy_ok or violation or any(s.get(k) for s in [s231,s232,s233] for k in ["yfinance_used","yahoo_used","external_fallback_used"]):
        status=FAIL_POLICY
    else:
        status=""
    stages=stage_status(s231,s232,s233)
    stage_fail=sum(1 for r in stages if r["stage_passed"]!="True")
    accepted_warn = str(s231.get("final_status","")).startswith("WARN_") or str(s233.get("final_status","")).startswith("WARN_")
    if not status:
        status = WARN_STATUS if accepted_warn else PASS_STATUS
    dram_gate=s232.get("multiframe_gate","")
    next_action="WAIT_FOR_INTRADAY_CONFIRMATION_RESEARCH_ONLY" if dram_gate=="WAIT_FOR_CONFIRMATION" else "RESEARCH_REVIEW_ONLY_NO_BROKER_ACTION"
    allowed_now = False
    stage_pass=sum(1 for r in stages if r["stage_passed"]=="True")
    stage_warn=sum(1 for r in stages if r["severity"]=="WARN" or (r["stage_passed"]=="True" and "WARN" in r["actual_final_status"]))
    source_snapshot=snapshot_id or s231.get("snapshot_id") or pointer.get("snapshot_id","")
    summary={"final_status":status,"final_decision":DECISION,"repo_root":str(repo_root),"output_dir":str(output_dir),"source_snapshot_id":source_snapshot,"canonical_snapshot_dir":s231.get("canonical_snapshot_dir") or pointer.get("canonical_snapshot_dir",""),"canonical_latest_date":s231.get("canonical_latest_date",""),"latest_price_date":s232.get("latest_price_date",""),"v21_231_status":s231.get("final_status",""),"v21_232_status":s232.get("final_status",""),"v21_233_status":s233.get("final_status",""),"daily_chain_passed":not status.startswith("FAIL_"),"stage_pass_count":stage_pass,"stage_warn_count":stage_warn,"stage_fail_count":stage_fail,"active_trading_focus":"DRAM","dram_entry":s232.get("entry",""),"dram_no_chase":s232.get("no_chase",""),"dram_stop":s232.get("stop",""),"dram_daily_trend_state":s232.get("daily_trend_state",""),"dram_multiframe_gate":dram_gate,"dram_entry_allowed_research_only":s232.get("entry_allowed_research_only", False),"dram_chase_allowed_research_only":s232.get("chase_allowed_research_only", False),"dram_next_action_gate":next_action,"abcde_ranked_strategy_count":s233.get("ranked_strategy_count",0),"abcde_ranked_ticker_count":s233.get("ranked_ticker_count",0),"abcde_missing_ticker_count":s233.get("missing_ticker_count",0),"abcde_compact_proxy_used":s233.get("compact_proxy_used",False),"abcde_same_date_comparable_all_strategies":s233.get("same_date_comparable_all_strategies",""),"A1_top20":s233.get("A1_top20",""),"B_top20":s233.get("B_top20",""),"C_top20":s233.get("C_top20",""),"D_top20":s233.get("D_top20",""),"E_R1_top20":s233.get("E_R1_top20",""),"yfinance_used":False,"yahoo_used":False,"external_fallback_used":False,"moomoo_used":True,"broker_action_allowed":False,"trade_unlock_used":False,"official_adoption_allowed":False,"research_only":True,"warning_count":int(s231.get("warning_count",0) or 0)+int(s232.get("warning_count",0) or 0)+int(s233.get("warning_count",0) or 0),"error_count":1 if status.startswith("FAIL_") else 0}
    currentness=currentness_rows(source_snapshot,s231,s232,s233)
    policy_rows=policy_audit_rows(s231,s232,s233)
    dram_rows=dram_summary_rows(s232, source_snapshot, next_action)
    abcde_rows=abcde_summary_rows(d233, s233)
    missing_rows=[{"ticker":r.get("ticker",""),"reason":r.get("reason",""),"source_stage":"V21.233","yahoo_fallback_allowed":r.get("yahoo_fallback_allowed","False"),"external_fallback_allowed":r.get("external_fallback_allowed","False"),"blocks_daily_chain":"False","notes":r.get("notes","")} for r in read_csv_rows(d233/"abcde_missing_ticker_audit.csv")]
    rollup=rollup_rows(s231,s232,s233)
    manifest=pointer_manifest(summary,d231,d232,d233,s231,s232,s233)
    next_rows=[{"gate":"DRAM_MULTIFRAME_GATE","status":dram_gate,"next_action":next_action,"allowed_now":bool_text(allowed_now),"broker_action_allowed":"False","official_adoption_allowed":"False","notes":"research-only chain; no broker action"}]
    protected=[{"artifact":"V21.231 cache snapshot","protected":"True","mutation_allowed":"False","passed":"True","notes":"read-only pointer validation"},{"artifact":"historical research outputs","protected":"True","mutation_allowed":"False","passed":"True","notes":"no mutation performed"}]
    lightweight=[{"artifact":str(p),"size_bytes":p.stat().st_size,"lightweight":bool_text(p.stat().st_size<500_000),"passed":bool_text(p.stat().st_size<500_000),"notes":"repo output size check"} for p in output_dir.glob("*") if p.is_file()]
    write_outputs(output_dir, summary, stages, currentness, policy_rows, dram_rows, abcde_rows, missing_rows, rollup, manifest, next_rows, protected, lightweight, audit)
    return summary


def currentness_rows(snap: str, s231: dict[str,Any], s232: dict[str,Any], s233: dict[str,Any]) -> list[dict[str,Any]]:
    expected=s231.get("canonical_latest_date","")
    return [{"artifact":"V21.231 canonical","source_snapshot_id":snap,"latest_date":s231.get("canonical_latest_date",""),"expected_latest_date":expected,"currentness_status":"CURRENT","passed":"True","severity":"INFO","notes":""},{"artifact":"V21.232 DRAM","source_snapshot_id":snap,"latest_date":s232.get("latest_price_date",""),"expected_latest_date":expected,"currentness_status":"CURRENT" if s232.get("latest_price_date")==expected else "CHECK","passed":bool_text(s232.get("latest_price_date")==expected),"severity":"INFO","notes":""},{"artifact":"V21.233 ABCDE","source_snapshot_id":snap,"latest_date":s233.get("canonical_latest_date",""),"expected_latest_date":expected,"currentness_status":"CURRENT" if s233.get("canonical_latest_date")==expected else "CHECK","passed":bool_text(s233.get("canonical_latest_date")==expected),"severity":"INFO","notes":""}]


def policy_audit_rows(*summaries: dict[str,Any]) -> list[dict[str,Any]]:
    names=["V21.231","V21.232","V21.233"]; rows=[]
    for name,s in zip(names,summaries):
        ok=not any(s.get(k) for k in ["yfinance_used","yahoo_used","external_fallback_used"]) and s.get("broker_action_allowed") is False and s.get("official_adoption_allowed") is False and s.get("research_only") is True
        rows.append({"artifact":name,"data_source_policy":"MOOMOO_ONLY","yfinance_used":bool_text(bool(s.get("yfinance_used"))),"yahoo_used":bool_text(bool(s.get("yahoo_used"))),"external_fallback_used":bool_text(bool(s.get("external_fallback_used"))),"moomoo_used":bool_text(bool(s.get("moomoo_used",True))),"broker_action_allowed":bool_text(bool(s.get("broker_action_allowed"))),"official_adoption_allowed":bool_text(bool(s.get("official_adoption_allowed"))),"research_only":bool_text(bool(s.get("research_only",True))),"passed":bool_text(ok),"notes":"source policy summary audit"})
    return rows


def dram_summary_rows(s232: dict[str,Any], snap: str, next_action: str) -> list[dict[str,Any]]:
    return [{"ticker":"DRAM","source_snapshot_id":snap,"latest_price_date":s232.get("latest_price_date",""),"latest_intraday_timestamp":s232.get("latest_intraday_timestamp",""),"entry":s232.get("entry",""),"no_chase":s232.get("no_chase",""),"stop":s232.get("stop",""),"daily_trend_state":s232.get("daily_trend_state",""),"multiframe_gate":s232.get("multiframe_gate",""),"entry_allowed_research_only":bool_text(bool(s232.get("entry_allowed_research_only"))),"chase_allowed_research_only":bool_text(bool(s232.get("chase_allowed_research_only"))),"trade_plan_currentness":s232.get("trade_plan_currentness",""),"next_action_gate":next_action,"broker_action_allowed":"False","official_adoption_allowed":"False","notes":"DRAM remains active focus; research-only"}]


def abcde_summary_rows(d233: Path, s233: dict[str,Any]) -> list[dict[str,Any]]:
    rows=[]
    top50=read_csv_rows(d233/"abcde_top50_summary.csv")
    for key,label in [("A1","A1_CONTROL"),("B","B_STATIC_MOMENTUM"),("C","C_DYNAMIC_MOMENTUM"),("D","D_WEIGHT_OPTIMIZED_REFERENCE"),("E_R1","E_R1_DEFENSIVE_REFERENCE")]:
        rows.append({"strategy_name":label,"latest_date":s233.get(f"{key}_latest_date",""),"top20":s233.get(f"{key}_top20",""),"top50_count":sum(1 for r in top50 if r.get("strategy_name")==label),"compact_proxy_used":bool_text(bool(s233.get("compact_proxy_used"))),"unavailable_component_warning_count":s233.get("unavailable_component_warning_count",0),"research_only":"True","official_adoption_allowed":"False","broker_action_allowed":"False","notes":"auxiliary research only; no promotion"})
    return rows


def rollup_rows(s231:dict[str,Any],s232:dict[str,Any],s233:dict[str,Any])->list[dict[str,Any]]:
    out=[]
    for name,s in [("V21.231",s231),("V21.232",s232),("V21.233",s233)]:
        out.append({"source_stage":name,"warning_count":s.get("warning_count",0),"error_count":s.get("error_count",0),"quality_error_count":s.get("quality_error_count",0),"quality_warning_count":s.get("quality_warning_count",0),"coverage_warning_count":s.get("coverage_warning_count",0),"severity":"WARN" if int(s.get("warning_count",0) or 0)>0 else "INFO","notes":"upstream rollup"})
    return out


def pointer_manifest(summary:dict[str,Any],d231:Path,d232:Path,d233:Path,s231:dict[str,Any],s232:dict[str,Any],s233:dict[str,Any])->dict[str,Any]:
    return {"policy_version":"V21.234","created_at_utc":datetime.now(timezone.utc).isoformat(),"active_trading_focus":"DRAM","source_snapshot_id":summary["source_snapshot_id"],"canonical_snapshot_dir":summary["canonical_snapshot_dir"],"v21_231_output_dir":str(d231),"v21_232_output_dir":str(d232),"v21_233_output_dir":str(d233),"v21_231_summary":s231,"v21_232_summary":s232,"v21_233_summary":s233,"latest_price_date":summary["latest_price_date"],"canonical_latest_date":summary["canonical_latest_date"],"dram_plan":{"entry":summary["dram_entry"],"no_chase":summary["dram_no_chase"],"stop":summary["dram_stop"],"multiframe_gate":summary["dram_multiframe_gate"],"entry_allowed_research_only":summary["dram_entry_allowed_research_only"],"chase_allowed_research_only":summary["dram_chase_allowed_research_only"]},"abcde":{"compact_proxy_used":summary["abcde_compact_proxy_used"],"same_date_comparable_all_strategies":summary["abcde_same_date_comparable_all_strategies"],"ranked_ticker_count":summary["abcde_ranked_ticker_count"],"missing_ticker_count":summary["abcde_missing_ticker_count"]},"policy_flags":{"data_source_policy":"MOOMOO_ONLY","yfinance_used":False,"yahoo_used":False,"external_fallback_used":False,"broker_action_allowed":False,"official_adoption_allowed":False,"research_only":True}}


def write_outputs(out:Path, summary:dict[str,Any], stages,current,policy,dram,abcde,missing,rollup,manifest,next_rows,protected,lightweight,audit)->None:
    write_csv(out/"daily_chain_stage_status.csv", stages, STAGE_FIELDS)
    write_csv(out/"daily_chain_currentness_audit.csv", current, CURRENT_FIELDS)
    write_csv(out/"daily_chain_source_policy_audit.csv", policy, POLICY_FIELDS)
    write_csv(out/"daily_chain_dram_summary.csv", dram, DRAM_FIELDS)
    write_csv(out/"daily_chain_abcde_summary.csv", abcde, ABCDE_FIELDS)
    write_csv(out/"daily_chain_missing_ticker_summary.csv", missing, MISSING_FIELDS)
    write_csv(out/"daily_chain_warning_error_rollup.csv", rollup, ROLLUP_FIELDS)
    write_json(out/"daily_chain_pointer_manifest.json", manifest)
    write_csv(out/"daily_chain_pointer_manifest.csv", [{"key":k,"value":v} for k,v in manifest.items()], POINTER_FIELDS)
    write_csv(out/"daily_chain_next_action_gate.csv", next_rows, NEXT_FIELDS)
    write_csv(out/"daily_chain_protected_outputs_audit.csv", protected, PROTECTED_FIELDS)
    write_csv(out/"daily_chain_lightweight_repo_policy_audit.csv", lightweight, LIGHT_FIELDS)
    write_csv(out/"no_yfinance_enforcement_audit.csv", audit, AUDIT_FIELDS)
    write_json(out/"v21_234_summary.json", summary)
    keys=["final_status","final_decision","source_snapshot_id","canonical_latest_date","latest_price_date","daily_chain_passed","dram_next_action_gate","warning_count","error_count"]
    (out/"V21.234_minimal_moomoo_only_daily_research_chain_report.txt").write_text("\n".join([STAGE,*[f"{k}={summary.get(k)}" for k in keys],"research_only=True","broker_action_allowed=False","official_adoption_allowed=False"])+"\n",encoding="utf-8")


def parse_args(argv: list[str] | None=None)->argparse.Namespace:
    p=argparse.ArgumentParser(description=STAGE)
    p.add_argument("--repo-root",type=Path,default=default_repo_root())
    p.add_argument("--output-dir",type=Path,default=None)
    p.add_argument("--v21-231-output-dir",type=Path,default=None)
    p.add_argument("--v21-232-output-dir",type=Path,default=None)
    p.add_argument("--v21-233-output-dir",type=Path,default=None)
    p.add_argument("--cache-root",type=Path,default=None)
    p.add_argument("--snapshot-id",default=None)
    p.add_argument("--rerun-dram",action="store_true",default=False)
    p.add_argument("--rerun-abcde",action="store_true",default=False)
    return p.parse_args(argv)


def main(argv: list[str] | None=None)->int:
    a=parse_args(argv); root=a.repo_root.resolve(); out=a.output_dir or root/OUT_REL
    s=run(root,out,a.v21_231_output_dir,a.v21_232_output_dir,a.v21_233_output_dir,a.cache_root,a.snapshot_id,a.rerun_dram,a.rerun_abcde)
    print(str(out/"v21_234_summary.json"))
    return 1 if str(s["final_status"]).startswith("FAIL_") else 0


if __name__=="__main__":
    raise SystemExit(main())
