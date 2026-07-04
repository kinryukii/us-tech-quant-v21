from __future__ import annotations
import csv, importlib.util
from pathlib import Path
P=Path(__file__).with_name("v21_247_reweighted_strategy_replay_and_forward_backtest.py")
S=importlib.util.spec_from_file_location("m247",P); m=importlib.util.module_from_spec(S); S.loader.exec_module(m)
def wc(p,rows,fields):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open("w",encoding="utf-8",newline="") as f:
  w=csv.DictWriter(f,fields,lineterminator="\n"); w.writeheader(); w.writerows(rows)
def test_reweighted_outputs_pit_research_only(tmp_path):
 repo=tmp_path/"repo"; root=repo/"outputs/v21/V21.243_R1_RECENT_0618_STRATEGY_SUCCESS_AUDIT_WITH_REPLAY"
 rows=[{"ranking_date":"2026-06-18","strategy":s,"ticker":"AAA","rank":1,"source_mode":"RETROSPECTIVE_PIT_LITE_REPLAY","pit_status":"PIT_LITE_REPLAY","forward_window":"1D","target_price_date":"2026-06-22","forward_return":r,"maturity_status":"MATURED"} for s,r in [("E_R1","0.02"),("A1","-0.04"),("DRAM","-0.03"),("QQQ","0.01"),("SOXX","0.0"),("SMH","0.0"),("ABCDE_AGGREGATE","-0.02")]]
 wc(root/"recent_0618_r1_strategy_success_by_ticker.csv",rows,["ranking_date","strategy","ticker","rank","source_mode","pit_status","forward_window","target_price_date","forward_return","maturity_status"])
 before=(root/"recent_0618_r1_strategy_success_by_ticker.csv").read_bytes(); s=m.run(repo); out=repo/m.OUT_REL
 assert (root/"recent_0618_r1_strategy_success_by_ticker.csv").read_bytes()==before
 assert s["broker_action_allowed"] is False and s["official_adoption_allowed"] is False
 assert "PIT_LITE_REPLAY" in (out/"reweighted_strategy_forward_success_by_ticker.csv").read_text(encoding="utf-8")
 assert all((out/n).exists() for n in ["reweighted_strategy_forward_success_summary.csv","reweighted_strategy_candidate_decision_matrix.csv","v21_247_summary.json"])
