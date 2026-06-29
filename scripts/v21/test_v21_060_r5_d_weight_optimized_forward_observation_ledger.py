#!/usr/bin/env python
import csv,hashlib,importlib.util,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];SCRIPT=ROOT/"scripts/v21/v21_060_r5_d_weight_optimized_forward_observation_ledger.py";WRAP=ROOT/"scripts/v21/run_v21_060_r5_d_weight_optimized_forward_observation_ledger.ps1"
s=importlib.util.spec_from_file_location("r5",SCRIPT);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
REQ=(m.RANK_NAME,m.COMP_NAME,m.RISK_NAME,m.LEDGER_NAME,m.APPEND_NAME,m.FORCED_NAME,m.LINEAGE_NAME,m.SUMMARY_NAME)
ALLOWED={m.PASS,m.PARTIAL,m.FAIL_A0,m.FAIL_VARIANT,m.FAIL_HARD,m.FAIL_PRICE,m.FAIL_TQQQ,m.FAIL_MUT}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def test_repository_wrapper():
 r2=m.load(ROOT,"r2t","v21_060_r2_multi_seed_random_asof_abcd_robustness_backtest.py");ps=m.protected(ROOT,r2);before={p.relative_to(ROOT).as_posix():sha(p) for p in ps}
 run=subprocess.run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-File",str(WRAP)],cwd=ROOT,text=True,capture_output=True);out=ROOT/m.OUT_REL;summary=json.loads((out/m.SUMMARY_NAME).read_text());assert summary["FINAL_STATUS"] in ALLOWED;assert run.returncode==(1 if summary["FINAL_STATUS"].startswith("FAIL_") else 0),run.stdout+run.stderr;assert all((out/x).is_file() for x in REQ)
 ranking=list(csv.DictReader((out/m.RANK_NAME).open("r",encoding="utf-8")));eligible=[x for x in ranking if x["eligible_for_variant_ranking"]=="TRUE"];assert eligible
 for x in eligible:
  assert abs(float(x["applied_momentum_weight"])-.4)<1e-9;assert abs(float(x["final_shadow_score"])-(.6*float(x["base_score"])+.4*float(x["momentum_score"])))<1e-7;assert x["research_only"]=="TRUE"
 ledger=list(csv.DictReader((out/m.LEDGER_NAME).open("r",encoding="utf-8")));ids=[x["observation_id"] for x in ledger];assert len(ids)==len(set(ids));assert all(x["variant_id"]==m.D and x["research_only"]=="TRUE" for x in ledger)
 forced=list(csv.DictReader((out/m.FORCED_NAME).open("r",encoding="utf-8")));assert set(m.FORCED)=={x["ticker"] for x in forced}
 for t in ("DRAM","SPCX"):
  x=next(y for y in forced if y["ticker"]==t)
  if x["local_price_missing_flag"]=="TRUE":assert x["present_in_D_ranking"]==x["present_in_D_observation"]=="FALSE"
 assert summary["a0_replayed"] is False and summary["a0_modified"] is False and summary["source_abcd_ledger_modified"] is False and summary["existing_b_c_outputs_modified"] is False
 for k in ("hardcoded_inclusion_violation_count","local_price_missing_ranked_violation_count","local_price_missing_observation_violation_count","tqqq_ipo_watch_violation_count","leveraged_full_size_violation_count","inverse_non_hedge_violation_count"):assert summary[k]==0
 assert summary["production_adoption_allowed"] is False and summary["official_use_allowed"] is False;assert before=={p:sha(ROOT/p) for p in before};assert {p.parent.resolve() for p in out.glob("V21_060_R5*") if p.is_file()}=={out.resolve()}
if __name__=="__main__":test_repository_wrapper();print("PASS test_v21_060_r5_d_weight_optimized_forward_observation_ledger")
