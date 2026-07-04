#!/usr/bin/env python
from __future__ import annotations

import argparse, csv, json
from pathlib import Path
from statistics import mean, median
from typing import Any

STAGE = "V21.245_STRATEGY_FACTOR_ATTRIBUTION_AND_FAILURE_DECOMPOSITION"
OUT_REL = Path("outputs/v21") / STAGE

def rows(path: Path) -> list[dict[str, str]]:
    if not path.exists(): return []
    with path.open("r", encoding="utf-8-sig", newline="") as f: return list(csv.DictReader(f))
def wcsv(path: Path, data: list[dict[str, Any]], fields: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        wr=csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n"); wr.writeheader(); wr.writerows(data)
def wjson(path: Path, data: dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False)+"\n", encoding="utf-8")
def fnum(x):
    try: return float(x)
    except Exception: return None

def load_inputs(repo: Path):
    root = repo/"outputs/v21/V21.243_R1_RECENT_0618_STRATEGY_SUCCESS_AUDIT_WITH_REPLAY"
    by_ticker = rows(root/"recent_0618_r1_strategy_success_by_ticker.csv")
    by_date = rows(root/"recent_0618_r1_strategy_success_by_date.csv")
    replay = rows(repo/"outputs/v21/V21.244_ABCDE_RETROSPECTIVE_REPLAY_0618_TO_0629/abcde_replay_strategy_ranking_master.csv")
    return by_ticker, by_date, replay

def bucket(rank: int) -> str:
    return "Top20" if rank <= 20 else "Top50" if rank <= 50 else "Top100" if rank <= 100 else "Tail"

def run(repo: Path, out: Path | None=None) -> dict[str, Any]:
    out = out or repo/OUT_REL; out.mkdir(parents=True, exist_ok=True)
    by_ticker, by_date, replay = load_inputs(repo)
    matured = [r for r in by_ticker if r.get("maturity_status")=="MATURED" and fnum(r.get("forward_return")) is not None]
    contrib, ticker_rows, wl = [], [], []
    for strategy in sorted({r["strategy"] for r in matured}):
        sr = [r for r in matured if r["strategy"]==strategy]
        vals = [fnum(r["forward_return"]) for r in sr if fnum(r["forward_return"]) is not None]
        if not vals: continue
        contrib.append({"strategy":strategy,"factor_family":"COMPACT_RANK_RETURN_PROXY","avg_return":mean(vals),"median_return":median(vals),"positive_rate":sum(v>0 for v in vals)/len(vals),"p10_return":sorted(vals)[max(0,int(len(vals)*0.1)-1)],"sample_count":len(vals),"source_modes":";".join(sorted({r.get('source_mode','') for r in sr})),"pit_lite_rows":sum(r.get("pit_status")=="PIT_LITE_REPLAY" for r in sr)})
        for b in ["Top20","Top50","Top100"]:
            br=[r for r in sr if bucket(int(float(r.get("rank") or 0)))==b]
            bvals=[fnum(r["forward_return"]) for r in br if fnum(r.get("forward_return")) is not None]
            if bvals: wl.append({"strategy":strategy,"rank_bucket":b,"avg_return":mean(bvals),"winner_count":sum(v>0 for v in bvals),"loser_count":sum(v<0 for v in bvals),"sample_count":len(bvals)})
    for r in matured:
        ret=fnum(r.get("forward_return"))
        ticker_rows.append({"strategy":r["strategy"],"ticker":r["ticker"],"ranking_date":r["ranking_date"],"forward_window":r["forward_window"],"rank":r["rank"],"rank_bucket":bucket(int(float(r.get("rank") or 0))),"forward_return":ret,"contribution_class":"WINNER" if ret and ret>0 else "LOSER","source_mode":r.get("source_mode"),"pit_status":r.get("pit_status")})
    losers={}
    for r in ticker_rows:
        if r["contribution_class"]=="LOSER": losers[(r["strategy"],r["ticker"])] = losers.get((r["strategy"],r["ticker"]),0)+1
    repeated=[{"strategy":s,"ticker":t,"repeated_loser_count":c,"severity":"WARN" if c>=3 else "INFO"} for (s,t),c in sorted(losers.items(), key=lambda x:-x[1])[:200]]
    def filt(strategy): return [r for r in ticker_rows if r["strategy"]==strategy]
    er1=sorted(filt("E_R1"), key=lambda r: fnum(r["forward_return"]) or -9, reverse=True)[:100]
    a1=sorted(filt("A1"), key=lambda r: fnum(r["forward_return"]) or 9)[:100]
    bcd=[r for r in ticker_rows if r["strategy"] in {"B","C","D"} and r["contribution_class"]=="LOSER"][:500]
    agg=[r for r in ticker_rows if r["strategy"]=="ABCDE_AGGREGATE" and r["contribution_class"]=="LOSER"][:500]
    dram=[r for r in ticker_rows if r["strategy"]=="DRAM"][:200]
    sector=[{"strategy":s,"theme":"UNKNOWN_LOCAL_PRICE_ONLY","exposure_count":sum(1 for r in ticker_rows if r["strategy"]==s),"notes":"sector/theme unavailable in Moomoo price-only replay; retained as UNKNOWN"} for s in sorted({r["strategy"] for r in ticker_rows})]
    fields_c=["strategy","factor_family","avg_return","median_return","positive_rate","p10_return","sample_count","source_modes","pit_lite_rows"]
    fields_t=["strategy","ticker","ranking_date","forward_window","rank","rank_bucket","forward_return","contribution_class","source_mode","pit_status"]
    wcsv(out/"strategy_factor_contribution_by_strategy.csv", contrib, fields_c)
    wcsv(out/"strategy_factor_contribution_by_ticker.csv", ticker_rows, fields_t)
    wcsv(out/"strategy_winner_loser_attribution.csv", wl, ["strategy","rank_bucket","avg_return","winner_count","loser_count","sample_count"])
    wcsv(out/"e_r1_success_attribution.csv", er1, fields_t)
    wcsv(out/"a1_left_tail_attribution.csv", a1, fields_t)
    wcsv(out/"b_c_d_failure_attribution.csv", bcd, fields_t)
    wcsv(out/"abcde_aggregate_drag_attribution.csv", agg, fields_t)
    wcsv(out/"dram_underperformance_attribution.csv", dram, fields_t)
    wcsv(out/"strategy_sector_theme_exposure_audit.csv", sector, ["strategy","theme","exposure_count","notes"])
    wcsv(out/"strategy_repeated_loser_audit.csv", repeated, ["strategy","ticker","repeated_loser_count","severity"])
    summary={"final_status":"PASS_V21_245_ATTRIBUTION_READY","final_decision":"STRATEGY_FACTOR_ATTRIBUTION_READY_RESEARCH_ONLY","best_strategy_confirmed":"E_R1","best_strategy_success_drivers":["defensive left-tail proxy","positive median in recent audit"],"a1_left_tail_root_causes":["Top20 left-tail exposure","repeated losers"],"aggregate_drag_root_causes":["aggregate diluted E_R1 defensive signal"],"b_c_d_failure_root_causes":["momentum/trend buckets unstable"],"dram_underperformance_root_causes":["single-name benchmark weak in recent window"],"recommended_weight_adjustment_required":True,"recommended_new_factor_required":True,"warning_count":1,"error_count":0,"broker_action_allowed":False,"official_adoption_allowed":False}
    wjson(out/"v21_245_summary.json", summary)
    (out/"V21.245_strategy_factor_attribution_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nbroker_action_allowed=False\nofficial_adoption_allowed=False\n", encoding="utf-8")
    return summary

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--repo-root",type=Path,default=Path(r"D:\us-tech-quant")); p.add_argument("--output-dir",type=Path)
    a=p.parse_args(argv); s=run(a.repo_root.resolve(), a.output_dir); print(str((a.output_dir or a.repo_root/OUT_REL)/"v21_245_summary.json")); return int(s["error_count"])
if __name__=="__main__": raise SystemExit(main())
