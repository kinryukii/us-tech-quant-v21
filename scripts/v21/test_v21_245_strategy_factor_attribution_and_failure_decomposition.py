from __future__ import annotations
import csv, importlib.util
from pathlib import Path
P=Path(__file__).with_name("v21_245_strategy_factor_attribution_and_failure_decomposition.py")
S=importlib.util.spec_from_file_location("m245",P); m=importlib.util.module_from_spec(S); S.loader.exec_module(m)
def wc(p,rows,fields):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open("w",encoding="utf-8",newline="") as f:
  w=csv.DictWriter(f,fields,lineterminator="\n"); w.writeheader(); w.writerows(rows)
def seed(tmp_path):
 repo=tmp_path/"repo"; root=repo/"outputs/v21/V21.243_R1_RECENT_0618_STRATEGY_SUCCESS_AUDIT_WITH_REPLAY"
 rows=[{"ranking_date":"2026-06-18","strategy":s,"ticker":"AAA","rank":1,"source_mode":"RETROSPECTIVE_PIT_LITE_REPLAY","pit_status":"PIT_LITE_REPLAY","forward_window":"1D","forward_return":r,"maturity_status":"MATURED"} for s,r in [("E_R1","0.03"),("A1","-0.04"),("B","-0.02"),("C","-0.01"),("D","-0.03"),("ABCDE_AGGREGATE","-0.02"),("DRAM","-0.05")]]
 wc(root/"recent_0618_r1_strategy_success_by_ticker.csv",rows,["ranking_date","strategy","ticker","rank","source_mode","pit_status","forward_window","forward_return","maturity_status"])
 return repo, root/"recent_0618_r1_strategy_success_by_ticker.csv"
def test_outputs_research_flags_and_pit(tmp_path):
 repo,input_file=seed(tmp_path); before=input_file.read_bytes(); s=m.run(repo)
 assert input_file.read_bytes()==before and s["broker_action_allowed"] is False and s["official_adoption_allowed"] is False
 out=repo/m.OUT_REL
 assert "PIT_LITE_REPLAY" in (out/"strategy_factor_contribution_by_ticker.csv").read_text(encoding="utf-8")
 for name in ["strategy_factor_contribution_by_strategy.csv","strategy_factor_contribution_by_ticker.csv","strategy_winner_loser_attribution.csv","e_r1_success_attribution.csv","a1_left_tail_attribution.csv","b_c_d_failure_attribution.csv","abcde_aggregate_drag_attribution.csv","dram_underperformance_attribution.csv","strategy_sector_theme_exposure_audit.csv","strategy_repeated_loser_audit.csv","v21_245_summary.json","V21.245_strategy_factor_attribution_report.txt"]:
  assert (out/name).exists()
