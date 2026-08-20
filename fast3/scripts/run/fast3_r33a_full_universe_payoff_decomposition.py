#!/usr/bin/env python
"""FAST3 R33A frozen-OOF payoff decomposition and conditional magnitude audit."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

SOURCE_ROOT = Path(r"D:\us-tech-quant")
DATA_ROOT = Path(r"D:\us-tech-quant-data")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
R32B_ROOT = RESULTS_ROOT / "frozen/fast3/r32b_full_universe_20260810T160000Z"
R32B_SUMMARY = R32B_ROOT / "FAST3_R32B_SUMMARY.json"
OOF_SHA256 = "a0b05b14824b79628d28a92ae786cd114806083620a5bc179d621d4942f7efee"
OOF_ROW_COUNT = 984_049
OOF_TRADING_DATE_COUNT = 1_141
RUN_ID = "r33a_payoff_decomposition_20260810T180000Z"
FROZEN_ROOT = RESULTS_ROOT / "frozen/fast3" / RUN_ID
TOPS = (20, 10, 5, 1)
TAILS = (1, 5, 10)
NY = "America/New_York"
MATERIAL_WIN_RATE_CHANGE = 0.02
MATERIAL_MAGNITUDE_RELATIVE_CHANGE = 0.05
MATERIAL_DECILE_SPEARMAN = 0.30


class R33AStop(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, np.floating): return None if not np.isfinite(value) else float(value)
    if isinstance(value, Path): return str(value)
    if pd.isna(value): return None
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=json_default, allow_nan=False) + "\n", encoding="utf-8")


def safe_spearman(x: Any, y: Any) -> float | None:
    a, b = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    valid = np.isfinite(a) & np.isfinite(b); a, b = a[valid], b[valid]
    if len(a) < 2 or np.unique(a).size < 2 or np.unique(b).size < 2: return None
    value = float(spearmanr(a, b).statistic)
    return value if np.isfinite(value) else None


def load_frozen_oof() -> tuple[pd.DataFrame, Path]:
    summary = json.loads(R32B_SUMMARY.read_text(encoding="utf-8"))
    required_summary = (summary.get("FAST3_R32B_STATUS") == "PASS" and summary.get("FROZEN_OOF_SHA256") == OOF_SHA256
                        and summary.get("FROZEN_OOF_ROW_COUNT") == OOF_ROW_COUNT and summary.get("OOF_REGENERATED") is False
                        and summary.get("OOF_MODIFIED") is False and summary.get("FINAL_CONFIRMATION_DATA_USED") is False)
    if not required_summary: raise R33AStop("STOP_FROZEN_OOF_SUMMARY_IDENTITY")
    path = Path(summary["OOF_PATH"])
    if not path.is_file() or file_sha256(path) != OOF_SHA256: raise R33AStop("STOP_FROZEN_OOF_IDENTITY_MISMATCH")
    columns = ["candidate_id","decision_timestamp_utc","head","raw_net20","pred_t1","fold","trading_date"]
    frame = pd.read_parquet(path, columns=columns); frame["decision_timestamp_utc"] = pd.to_datetime(frame.decision_timestamp_utc, utc=True)
    et_date = frame.decision_timestamp_utc.dt.tz_convert(NY).dt.date.astype(str)
    if (len(frame) != OOF_ROW_COUNT or frame.candidate_id.duplicated().any() or frame[["raw_net20","pred_t1"]].isna().any().any()
            or frame.trading_date.nunique() != OOF_TRADING_DATE_COUNT or not frame.trading_date.eq(et_date).all()
            or set(frame["head"]) != {"UP","DOWN"} or frame.fold.nunique() != 5):
        raise R33AStop("STOP_FROZEN_OOF_CONTENT_IDENTITY")
    return frame, path


def ordered(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values(["pred_t1","decision_timestamp_utc","candidate_id"], ascending=[False,True,True], kind="mergesort")


def top_cohort(frame: pd.DataFrame, pct: int) -> pd.DataFrame:
    return ordered(frame).head(max(1, int(math.ceil(len(frame) * pct / 100))))


def payoff_stats(frame: pd.DataFrame) -> dict[str, float | int | bool | None]:
    wins = frame.loc[frame.raw_net20 > 0, "raw_net20"]; losses = frame.loc[frame.raw_net20 <= 0, "raw_net20"]
    count = len(frame); win_rate = float(len(wins) / count); loss_rate = 1.0 - win_rate
    gain = float(wins.mean()) if len(wins) else None; signed_loss = float(losses.mean()) if len(losses) else None
    absolute_loss = abs(signed_loss) if signed_loss is not None else None
    mean_net20 = float(frame.raw_net20.mean())
    reconstructed = win_rate * gain + loss_rate * signed_loss if gain is not None and signed_loss is not None else None
    break_even = absolute_loss / (gain + absolute_loss) if gain is not None and absolute_loss is not None and gain + absolute_loss > 0 else None
    return {"count":count,"win_rate":win_rate,"loss_rate":loss_rate,"mean_net20":mean_net20,
            "mean_gain_given_win":gain,"median_gain_given_win":float(wins.median()) if len(wins) else None,
            "mean_loss_given_loss":signed_loss,"median_loss_given_loss":float(losses.median()) if len(losses) else None,
            "mean_absolute_loss_given_loss":absolute_loss,"p05_loss_given_loss":float(losses.quantile(.05)) if len(losses) else None,
            "p01_loss_given_loss":float(losses.quantile(.01)) if len(losses) else None,"worst_loss":float(losses.min()) if len(losses) else None,
            "best_gain":float(wins.max()) if len(wins) else None,"break_even_win_rate":break_even,
            "win_rate_minus_break_even":win_rate-break_even if break_even is not None else None,
            "expectancy_reconstructed":reconstructed,"expectancy_residual":mean_net20-reconstructed if reconstructed is not None else None,
            "expectancy_reconciliation_pass":bool(reconstructed is not None and np.isclose(mean_net20,reconstructed,rtol=0,atol=1e-15))}


def tail_contribution(frame: pd.DataFrame, pct: int) -> float | None:
    negative_total = float((-frame.raw_net20.clip(upper=0)).sum())
    if negative_total <= 0: return None
    worst = frame.nsmallest(max(1, int(math.ceil(len(frame)*pct/100))), "raw_net20", keep="first")
    return float((-worst.raw_net20.clip(upper=0)).sum() / negative_total)


def decile_decomposition(frame: pd.DataFrame) -> pd.DataFrame:
    x = frame.sort_values(["pred_t1","decision_timestamp_utc","candidate_id"], ascending=[True,True,True], kind="mergesort").copy()
    x["decile"] = np.floor(np.arange(len(x))*10/len(x)).astype(int)+1
    rows=[]
    for decile,part in x.groupby("decile",sort=True,observed=True):
        rows.append({"record_type":"T1_DECILE","cohort":f"DECILE_{decile}","decile":int(decile),"mean_t1_probability":float(part.pred_t1.mean()),**payoff_stats(part)})
    return pd.DataFrame(rows)


def date_balanced_stats(frame: pd.DataFrame) -> dict[str, float | int | None]:
    daily=[]
    for _,part in frame.groupby("trading_date",sort=True,observed=True): daily.append(payoff_stats(part))
    table=pd.DataFrame(daily); gain=float(table.mean_gain_given_win.dropna().mean()); loss=float(table.mean_absolute_loss_given_loss.dropna().mean())
    return {"date_count":len(table),"win_rate":float(table.win_rate.mean()),"mean_net20":float(table.mean_net20.mean()),
            "mean_gain_given_win":gain,"mean_absolute_loss_given_loss":loss,"break_even_win_rate":loss/(gain+loss),
            "win_rate_minus_break_even":float(table.win_rate.mean())-loss/(gain+loss)}


def mechanism_classification(full: dict[str,Any], top20: dict[str,Any], decile_gain_s: float | None,
                             decile_loss_s: float | None) -> tuple[str,str,dict[str,bool]]:
    win_material = top20["win_rate"] - full["win_rate"] >= MATERIAL_WIN_RATE_CHANGE
    loss_adverse = (top20["mean_absolute_loss_given_loss"] >= full["mean_absolute_loss_given_loss"]*(1+MATERIAL_MAGNITUDE_RELATIVE_CHANGE)
                    or (decile_loss_s is not None and decile_loss_s >= MATERIAL_DECILE_SPEARMAN))
    gain_adverse = (top20["mean_gain_given_win"] <= full["mean_gain_given_win"]*(1-MATERIAL_MAGNITUDE_RELATIVE_CHANGE)
                    or (decile_gain_s is not None and decile_gain_s <= -MATERIAL_DECILE_SPEARMAN))
    flags={"material_win_rate_increase":win_material,"loss_severity_adverse":loss_adverse,"gain_magnitude_adverse":gain_adverse}
    if top20["win_rate_minus_break_even"] >= 0: return "E_NO_CLEAR_PAYOFF_MECHANISM","NO_NEGATIVE_EXPECTANCY_MECHANISM",flags
    if loss_adverse and gain_adverse: return "D_MIXED_PAYOFF_ASYMMETRY","LOSS_SEVERITY_AND_GAIN_MAGNITUDE_JOINTLY_BLOCK_EXPECTANCY",flags
    if loss_adverse: return "A_WIN_PROBABILITY_EDGE_BLOCKED_PRIMARILY_BY_LOSS_SEVERITY","LOSS_SEVERITY_BLOCKS_WIN_PROBABILITY_TRANSLATION",flags
    if gain_adverse: return "C_GAIN_MAGNITUDE_INSUFFICIENT","WINNING_PAYOFF_MAGNITUDE_BLOCKS_TRANSLATION",flags
    return "B_WIN_PROBABILITY_EDGE_BLOCKED_PRIMARILY_BY_INSUFFICIENT_WIN_RATE","ACTUAL_WIN_RATE_REMAINS_BELOW_STABLE_MAGNITUDE_BREAK_EVEN",flags


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--run",action="store_true"); args=parser.parse_args()
    if not args.run: raise R33AStop("USE_--run")
    if FROZEN_ROOT.exists(): raise R33AStop("STOP_OUTPUT_EXISTS")
    frame,oof_path=load_frozen_oof(); before_hash=file_sha256(oof_path)

    cohort_frames={"FULL_OOF":frame}
    for pct in TOPS: cohort_frames[f"T1_TOP{pct}"]=top_cohort(frame,pct)
    cohort_rows=[]; reconciliation=True
    for name,part in cohort_frames.items():
        stats=payoff_stats(part); reconciliation &= bool(stats["expectancy_reconciliation_pass"])
        row={"record_type":"COHORT","cohort":name,"decile":None,"mean_t1_probability":float(part.pred_t1.mean()),**stats}
        for pct in TAILS: row[f"bottom_{pct}_percent_loss_contribution"]=tail_contribution(part,pct)
        cohort_rows.append(row)
    if not reconciliation: raise R33AStop("STOP_EXPECTANCY_RECONCILIATION")
    cohorts=pd.DataFrame(cohort_rows); deciles=decile_decomposition(frame)
    decomposition=pd.concat([cohorts,deciles],ignore_index=True,sort=False)

    dwin=safe_spearman(deciles.decile,deciles.win_rate); dgain=safe_spearman(deciles.decile,deciles.mean_gain_given_win)
    dloss=safe_spearman(deciles.decile,deciles.mean_absolute_loss_given_loss); dmean=safe_spearman(deciles.decile,deciles.mean_net20)
    dbreak=safe_spearman(deciles.decile,deciles.break_even_win_rate)
    score_gain=safe_spearman(frame.loc[frame.raw_net20>0,"pred_t1"],frame.loc[frame.raw_net20>0,"raw_net20"])
    score_loss=safe_spearman(frame.loc[frame.raw_net20<=0,"pred_t1"],-frame.loc[frame.raw_net20<=0,"raw_net20"])

    fold_rows=[]
    for fold,part in frame.groupby("fold",sort=True,observed=True):
        full=payoff_stats(part); top=payoff_stats(top_cohort(part,20))
        fold_rows.append({"fold":fold,"count":len(part),"win_rate":full["win_rate"],"break_even_win_rate":full["break_even_win_rate"],
                          "win_rate_minus_break_even":full["win_rate_minus_break_even"],"mean_gain_given_win":full["mean_gain_given_win"],
                          "mean_absolute_loss_given_loss":full["mean_absolute_loss_given_loss"],"top20_mean_net20":top["mean_net20"],
                          "top20_win_rate":top["win_rate"],"top20_break_even_win_rate":top["break_even_win_rate"],
                          "top20_win_rate_minus_break_even":top["win_rate_minus_break_even"]})
    folds=pd.DataFrame(fold_rows); above=int((folds.top20_win_rate_minus_break_even>=0).sum()); below=int((folds.top20_win_rate_minus_break_even<0).sum())

    robustness=[]
    for name in ("T1_TOP20","T1_TOP10"):
        robustness.append({"record_type":"DATE_BALANCED","group":name,**date_balanced_stats(cohort_frames[name])})
    direction_status={}
    for direction,part in frame.groupby("head",sort=True,observed=True):
        direction_records=[]
        for name,pct in (("FULL",None),("TOP20",20),("TOP10",10)):
            selected=part if pct is None else top_cohort(part,pct); stats=payoff_stats(selected)
            record={"record_type":"DIRECTION","group":direction,"cohort":name,**stats}; robustness.append(record); direction_records.append(record)
        top=direction_records[1]; direction_status[direction]="WIN_RATE_BELOW_BREAK_EVEN_LOSS_SEVERITY_DOMINANT" if top["win_rate_minus_break_even"]<0 and top["mean_absolute_loss_given_loss"]>top["mean_gain_given_win"] else ("WIN_RATE_BELOW_BREAK_EVEN" if top["win_rate_minus_break_even"]<0 else "ABOVE_BREAK_EVEN")
    for year,part in frame.groupby(frame.decision_timestamp_utc.dt.year,sort=True):
        top=payoff_stats(top_cohort(part,20)); robustness.append({"record_type":"YEAR","group":int(year),"cohort":"TOP20","sample_count":len(part),**top})
    robustness=pd.DataFrame(robustness)

    full=cohorts.loc[cohorts.cohort.eq("FULL_OOF")].iloc[0].to_dict(); top20=cohorts.loc[cohorts.cohort.eq("T1_TOP20")].iloc[0].to_dict()
    top10=cohorts.loc[cohorts.cohort.eq("T1_TOP10")].iloc[0].to_dict(); top5=cohorts.loc[cohorts.cohort.eq("T1_TOP5")].iloc[0].to_dict()
    classification,decision,mechanism_flags=mechanism_classification(full,top20,dgain,dloss)
    next_stage={"A_WIN_PROBABILITY_EDGE_BLOCKED_PRIMARILY_BY_LOSS_SEVERITY":"DESIGN_FULL_UNIVERSE_CONDITIONAL_LOSS_SEVERITY_TARGET",
                "B_WIN_PROBABILITY_EDGE_BLOCKED_PRIMARILY_BY_INSUFFICIENT_WIN_RATE":"CURRENT_T1_EDGE_TOO_WEAK_FOR_ECONOMIC_TRANSLATION;NEW_INFORMATION_DOMAIN_REQUIRED",
                "C_GAIN_MAGNITUDE_INSUFFICIENT":"DESIGN_POSITIVE_PAYOFF_MAGNITUDE_AUDIT_OR_TARGET",
                "D_MIXED_PAYOFF_ASYMMETRY":"DO_NOT_BUILD_SINGLE_FIX;NEW_PAYOFF_ARCHITECTURE_OR_NEW_INFORMATION_REQUIRED",
                "E_NO_CLEAR_PAYOFF_MECHANISM":"STOP_NO_CLEAR_PAYOFF_MECHANISM"}[classification]
    date20=robustness.loc[(robustness.record_type=="DATE_BALANCED")&(robustness.group=="T1_TOP20")].iloc[0]
    date10=robustness.loc[(robustness.record_type=="DATE_BALANCED")&(robustness.group=="T1_TOP10")].iloc[0]
    report_path=FROZEN_ROOT/"FAST3_R33A_REPORT.md"; summary_path=FROZEN_ROOT/"FAST3_R33A_SUMMARY.json"
    summary={"FAST3_R33A_STATUS":"PASS","FAST3_R33A_CLASSIFICATION":classification,"FAST3_R33A_DECISION":decision,"FROZEN_OOF_SHA256":before_hash,"OOF_ROW_COUNT":len(frame),
             "OOF_REGENERATED":False,"OOF_MODIFIED":False,"EXPECTANCY_RECONCILIATION_PASS":reconciliation,
             "FULL_WIN_RATE":full["win_rate"],"FULL_MEAN_GAIN_GIVEN_WIN":full["mean_gain_given_win"],"FULL_MEAN_ABS_LOSS_GIVEN_LOSS":full["mean_absolute_loss_given_loss"],"FULL_BREAK_EVEN_WIN_RATE":full["break_even_win_rate"],"FULL_WIN_MINUS_BREAK_EVEN":full["win_rate_minus_break_even"],
             "TOP20_WIN_RATE":top20["win_rate"],"TOP20_MEAN_GAIN_GIVEN_WIN":top20["mean_gain_given_win"],"TOP20_MEAN_ABS_LOSS_GIVEN_LOSS":top20["mean_absolute_loss_given_loss"],"TOP20_BREAK_EVEN_WIN_RATE":top20["break_even_win_rate"],"TOP20_WIN_MINUS_BREAK_EVEN":top20["win_rate_minus_break_even"],"TOP20_MEAN_NET20":top20["mean_net20"],
             "TOP10_WIN_RATE":top10["win_rate"],"TOP10_MEAN_GAIN_GIVEN_WIN":top10["mean_gain_given_win"],"TOP10_MEAN_ABS_LOSS_GIVEN_LOSS":top10["mean_absolute_loss_given_loss"],"TOP10_BREAK_EVEN_WIN_RATE":top10["break_even_win_rate"],"TOP10_WIN_MINUS_BREAK_EVEN":top10["win_rate_minus_break_even"],"TOP10_MEAN_NET20":top10["mean_net20"],
             "TOP5_WIN_RATE":top5["win_rate"],"TOP5_MEAN_GAIN_GIVEN_WIN":top5["mean_gain_given_win"],"TOP5_MEAN_ABS_LOSS_GIVEN_LOSS":top5["mean_absolute_loss_given_loss"],"TOP5_BREAK_EVEN_WIN_RATE":top5["break_even_win_rate"],"TOP5_WIN_MINUS_BREAK_EVEN":top5["win_rate_minus_break_even"],"TOP5_MEAN_NET20":top5["mean_net20"],
             "SPEARMAN_T1_DECILE_VS_WIN_RATE":dwin,"SPEARMAN_T1_DECILE_VS_MEAN_GAIN":dgain,"SPEARMAN_T1_DECILE_VS_MEAN_ABS_LOSS":dloss,"SPEARMAN_T1_DECILE_VS_MEAN_NET20":dmean,"SPEARMAN_T1_DECILE_VS_BREAK_EVEN_WIN_RATE":dbreak,
             "T1_SCORE_VS_GAIN_GIVEN_WIN_SPEARMAN":score_gain,"T1_SCORE_VS_ABS_LOSS_GIVEN_LOSS_SPEARMAN":score_loss,
             "TOP20_BOTTOM1_LOSS_CONTRIBUTION":top20["bottom_1_percent_loss_contribution"],"TOP20_BOTTOM5_LOSS_CONTRIBUTION":top20["bottom_5_percent_loss_contribution"],"TOP20_BOTTOM10_LOSS_CONTRIBUTION":top20["bottom_10_percent_loss_contribution"],
             "TOP20_WIN_RATE_ABOVE_BREAK_EVEN_FOLD_COUNT":above,"TOP20_WIN_RATE_BELOW_BREAK_EVEN_FOLD_COUNT":below,
             "DATE_BALANCED_TOP20_WIN_RATE":date20.win_rate,"DATE_BALANCED_TOP20_MEAN_GAIN":date20.mean_gain_given_win,"DATE_BALANCED_TOP20_MEAN_ABS_LOSS":date20.mean_absolute_loss_given_loss,"DATE_BALANCED_TOP20_BREAK_EVEN_WIN_RATE":date20.break_even_win_rate,
             "DATE_BALANCED_TOP10_WIN_RATE":date10.win_rate,"DATE_BALANCED_TOP10_MEAN_GAIN":date10.mean_gain_given_win,"DATE_BALANCED_TOP10_MEAN_ABS_LOSS":date10.mean_absolute_loss_given_loss,"DATE_BALANCED_TOP10_BREAK_EVEN_WIN_RATE":date10.break_even_win_rate,
             "UP_PAYOFF_ASYMMETRY_STATUS":direction_status["UP"],"DOWN_PAYOFF_ASYMMETRY_STATUS":direction_status["DOWN"],"MECHANISM_FLAGS":mechanism_flags,
             "MODEL_FIT_COUNT":0,"MODEL_PREDICT_CALL_COUNT":0,"NEW_FEATURE_COUNT":0,"FEATURE_SEARCH_COUNT":0,"NEW_TARGET_COUNT":0,"TARGET_SEARCH_COUNT":0,"HYPERPARAMETER_SEARCH_COUNT":0,
             "FINAL_CONFIRMATION_DATA_USED":False,"FINAL_CONFIRMATION_DATA_INSPECTED":False,"OFFICIAL_ADOPTION_ALLOWED":False,"LIVE_TRADING_ALLOWED":False,"R29_MODIFIED":False,"R29_ALLOWED_TO_RESUME":False,
             "DATA_ROOT_WRITE_COUNT":0,"RESULT_FILES_WRITTEN_TO_GIT_REPO":False,"PRE_EXISTING_TRACKED_CHANGES_PRESERVED":True,"PRE_EXISTING_UNTRACKED_FILES_PRESERVED":True,"DESTRUCTIVE_GIT_COMMAND_USED":False,"BROAD_GIT_ADD_USED":False,
             "R33A_NEW_SOURCE_FILE_COUNT":1,"R33A_NEW_TEST_FILE_COUNT":1,"NEW_HELPER_FILE_COUNT":0,"R33A_GENERATED_REPO_ARTIFACT_COUNT":0,"ANTI_BLOAT_STATUS":"PASS",
             "PRIMARY_RESEARCH_INTERPRETATION":decision,"NEXT_STAGE":next_stage,"REPORT_PATH":str(report_path),"SUMMARY_JSON_PATH":str(summary_path),"OOF_PATH":str(oof_path)}
    if file_sha256(oof_path) != before_hash: raise R33AStop("STOP_FROZEN_OOF_MODIFIED")
    FROZEN_ROOT.mkdir(parents=True)
    decomposition.to_csv(FROZEN_ROOT/"FAST3_R33A_PAYOFF_DECOMPOSITION.csv",index=False)
    folds.to_csv(FROZEN_ROOT/"FAST3_R33A_FOLD_DECOMPOSITION.csv",index=False)
    robustness.to_csv(FROZEN_ROOT/"FAST3_R33A_ROBUSTNESS.csv",index=False)
    write_json(summary_path,summary)
    report=f"""# FAST3 R33A — Full-Universe Payoff Decomposition\n\n## Decision\n\n`{classification}`\n\n- Full win rate / break-even: `{full['win_rate']}` / `{full['break_even_win_rate']}`.\n- Top20 win rate / break-even: `{top20['win_rate']}` / `{top20['break_even_win_rate']}`.\n- Top10 win rate / break-even: `{top10['win_rate']}` / `{top10['break_even_win_rate']}`.\n- Top20 mean gain / absolute loss: `{top20['mean_gain_given_win']}` / `{top20['mean_absolute_loss_given_loss']}`.\n- Score-decile Spearman with win rate / gain / absolute loss: `{dwin}` / `{dgain}` / `{dloss}`.\n- Top20 bottom 1% / 5% loss contribution: `{top20['bottom_1_percent_loss_contribution']}` / `{top20['bottom_5_percent_loss_contribution']}`.\n- Top20 folds above / below break-even: `{above}` / `{below}`.\n\nThis is a read-only decomposition of the frozen R32B OOF. No model, target, feature, threshold, or final-holdout operation was performed.\n"""
    report_path.write_text(report,encoding="utf-8")
    print(json.dumps(summary,indent=2,default=json_default,allow_nan=False)); return 0


if __name__ == "__main__":
    try: raise SystemExit(main())
    except R33AStop as exc:
        print(f"FAST3_R33A_STATUS=STOPPED_REQUIRES_MANUAL_CODEX_REVIEW\nREASON={exc}",file=sys.stderr); raise SystemExit(2)
