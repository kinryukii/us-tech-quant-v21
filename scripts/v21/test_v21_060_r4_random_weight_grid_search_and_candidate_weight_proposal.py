#!/usr/bin/env python
import csv,hashlib,importlib.util,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; SCRIPT=ROOT/"scripts/v21/v21_060_r4_random_weight_grid_search_and_candidate_weight_proposal.py"; WRAPPER=ROOT/"scripts/v21/run_v21_060_r4_random_weight_grid_search_and_candidate_weight_proposal.ps1"
s=importlib.util.spec_from_file_location("r4",SCRIPT); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
REQ=(m.ROW_NAME,m.PORT_NAME,m.SEED_NAME,m.OVERALL_NAME,m.PAIR_NAME,m.REPORT_NAME,m.PROPOSAL_NAME,m.EXAMPLE_NAME,m.FORCED_NAME,m.LINEAGE_NAME,m.SUMMARY_NAME)
ALLOWED={m.PASS_STATUS,m.PARTIAL_STATUS,m.FAIL_A0,m.FAIL_VARIANT,m.FAIL_HARDCODED,m.FAIL_PRICE,m.FAIL_TQQQ,m.FAIL_MUTATION}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def test_repository_wrapper():
 r2=m.load(ROOT,"r2t","v21_060_r2_multi_seed_random_asof_abcd_robustness_backtest.py"); protected=r2.protected_files(ROOT)+list((ROOT/"outputs/v21/experiments/momentum_dynamic/random_backtests").glob("V21_060_R[23]_*"))+list((ROOT/"outputs/v21/experiments/momentum_dynamic").glob("V21_059_R1_[BC]*")); protected=sorted({p.resolve() for p in protected if p.is_file()}); before={p.relative_to(ROOT).as_posix():sha(p) for p in protected}
 run=subprocess.run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-File",str(WRAPPER)],cwd=ROOT,text=True,capture_output=True)
 out=ROOT/m.OUT_REL; summary=json.loads((out/m.SUMMARY_NAME).read_text()); assert summary["FINAL_STATUS"] in ALLOWED; assert run.returncode==(1 if summary["FINAL_STATUS"].startswith("FAIL_") else 0),run.stdout+run.stderr
 assert all((out/x).is_file() for x in REQ)
 weights=set()
 with (out/m.ROW_NAME).open("r",encoding="utf-8") as h:
  for row in csv.DictReader(h): weights.add(round(float(row["momentum_weight"]),2)); assert row["research_only"]=="TRUE"
 assert weights==set(m.WEIGHTS)
 with (out/m.PORT_NAME).open("r",encoding="utf-8") as h:
  splits=set()
  for row in csv.DictReader(h): splits.add(row["seed_split"]); assert float(row["initial_capital_usd"])==10000
 assert splits=={"TRAIN","VALIDATION"}
 proposal=list(csv.DictReader((out/m.PROPOSAL_NAME).open("r",encoding="utf-8"))); assert len(proposal)==1; assert proposal[0]["production_adoption_allowed"]==proposal[0]["official_use_allowed"]=="FALSE"
 forced=list(csv.DictReader((out/m.FORCED_NAME).open("r",encoding="utf-8"))); assert set(m.FORCED)=={x["ticker"] for x in forced}
 for t in ("DRAM","SPCX"):
  x=next(y for y in forced if y["ticker"]==t)
  if x["local_price_missing_flag"]=="TRUE":assert x["included_in_any_seed"]=="FALSE"
 assert summary["a0_replayed"] is False and summary["a0_modified"] is False and summary["production_adoption_allowed"] is False and summary["official_use_allowed"] is False
 assert summary["hardcoded_inclusion_violation_count"]==summary["local_price_missing_included_violation_count"]==summary["tqqq_ipo_watch_violation_count"]==0
 assert before=={p:sha(ROOT/p) for p in before}
 assert {p.parent.resolve() for p in out.glob("V21_060_R4*") if p.is_file()}=={out.resolve()}
 ledger=ROOT/"outputs/v21/experiments/momentum_dynamic/V21_060_R1_ABCD_FORWARD_OBSERVATION_LEDGER.csv"
 with ledger.open("r",encoding="utf-8") as h: assert all(row["variant_id"]!="D_WEIGHT_OPTIMIZED_R1" for row in csv.DictReader(h))
if __name__=="__main__":test_repository_wrapper();print("PASS test_v21_060_r4_random_weight_grid_search_and_candidate_weight_proposal")
