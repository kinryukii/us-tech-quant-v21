from __future__ import annotations
import csv, importlib.util
from pathlib import Path
P=Path(__file__).with_name("v21_246_factor_weight_recalibration_candidates.py")
S=importlib.util.spec_from_file_location("m246",P); m=importlib.util.module_from_spec(S); S.loader.exec_module(m)
def test_weights_bounded_research_only_outputs(tmp_path):
 repo=tmp_path/"repo"; s=m.run(repo); out=repo/m.OUT_REL
 rows=list(csv.DictReader((out/"factor_weight_candidate_master.csv").open(encoding="utf-8")))
 for cand in {r["candidate"] for r in rows}:
  assert abs(sum(float(r["weight"]) for r in rows if r["candidate"]==cand)-1.0)<1e-9
 assert s["bounded_candidate_deltas"] is True and s["official_adoption_allowed"] is False
 assert all((out/n).exists() for n in ["factor_weight_candidate_master.csv","factor_weight_candidate_delta_audit.csv","new_factor_feasibility_audit.csv","candidate_strategy_definition.csv","candidate_risk_constraint_audit.csv","v21_246_summary.json"])
