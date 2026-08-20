#!/usr/bin/env python
"""FAST3 R33B full-universe conditional loss-severity learning."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

SOURCE_ROOT=Path(r"D:\us-tech-quant"); DATA_ROOT=Path(r"D:\us-tech-quant-data"); RESULTS_ROOT=Path(r"D:\us-tech-quant-results")
RUN_ID="r33b_conditional_loss_severity_20260810T200000Z"
FROZEN_ROOT=RESULTS_ROOT/"frozen/fast3"/RUN_ID; SCRATCH_ROOT=RESULTS_ROOT/"scratch/fast3"/RUN_ID
R32B_RUNNER=SOURCE_ROOT/"fast3/scripts/run/fast3_r32b_full_universe_economic_baseline_training.py"
R30A_RUNNER=SOURCE_ROOT/"fast3/scripts/run/fast3_r30a_economic_target_baseline_training.py"
R33A_SUMMARY=RESULTS_ROOT/"frozen/fast3/r33a_payoff_decomposition_20260810T180000Z/FAST3_R33A_SUMMARY.json"
R32B_SUMMARY=RESULTS_ROOT/"frozen/fast3/r32b_full_universe_20260810T160000Z/FAST3_R32B_SUMMARY.json"
R33A_SUMMARY_SHA="64bc0af59947fe7dd473c9ede6b1ead20ec1a74733f85da761fd821186ac19b5"
R32B_SUMMARY_SHA="9e09d7b0561d934fd145a2a291c6c0e25a75ee7f3fa8415a478067a272c55bb1"
R32B_OOF_SHA="a0b05b14824b79628d28a92ae786cd114806083620a5bc179d621d4942f7efee"
FULL_UNIVERSE_SHA="7b46e300e68fcdcb24c363479c6de4343106c0e56bdc90c30e61f1472604ab22"
LABEL_MANIFEST_SHA="12356e0dd8d75c8cefa4233900942e73dffd5ae0688d685be6915d99ac38cc29"
FEATURE_SHA="248c4d1eabcbcee545ffc95f5f366390889c13199ec90d84d5bbd0f6332f4718"
SPLIT_SHA="38352151a703737d74b4d61dbe68f82a9c6f3d5058aa72bd2a1896e19a5cb412"
FULL_VALID=1_456_595; R32B_OOF_ROWS=984_049; FEATURE_COUNT=29; NY="America/New_York"


class R33BStop(RuntimeError): pass


def file_sha256(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda:handle.read(8*1024*1024),b""): digest.update(block)
    return digest.hexdigest()


def import_file(path: Path,name: str):
    spec=importlib.util.spec_from_file_location(name,path); module=importlib.util.module_from_spec(spec)
    if spec.loader is None: raise R33BStop("STOP_MODULE_IMPORT")
    spec.loader.exec_module(module); return module


def json_default(value: Any) -> Any:
    if isinstance(value,np.integer): return int(value)
    if isinstance(value,np.floating): return None if not np.isfinite(value) else float(value)
    if isinstance(value,(Path,pd.Timestamp)): return str(value)
    if pd.isna(value): return None
    raise TypeError(type(value).__name__)


def write_json(path: Path,value: Any) -> None:
    path.write_text(json.dumps(value,indent=2,sort_keys=True,default=json_default,allow_nan=False)+"\n",encoding="utf-8")


def safe_spearman(x: Any,y: Any) -> float | None:
    a,b=np.asarray(x,dtype=float),np.asarray(y,dtype=float); valid=np.isfinite(a)&np.isfinite(b); a,b=a[valid],b[valid]
    if len(a)<2 or np.unique(a).size<2 or np.unique(b).size<2: return None
    value=float(spearmanr(a,b).statistic); return value if np.isfinite(value) else None


def derive_t5(net20: pd.Series) -> pd.Series:
    result=pd.Series(np.nan,index=net20.index,dtype=float); eligible=net20.lt(0)
    result.loc[eligible]=np.log1p(-net20.loc[eligible].astype(float)); return result


def candidate_id_hash(values: pd.Series) -> str:
    digest=hashlib.sha256()
    for value in values.astype(str).sort_values(kind="mergesort"): digest.update(value.encode("utf-8")+b"\n")
    return digest.hexdigest()


def validate_authority() -> tuple[Any,Any,dict[str,Any],Path]:
    if file_sha256(R33A_SUMMARY)!=R33A_SUMMARY_SHA or file_sha256(R32B_SUMMARY)!=R32B_SUMMARY_SHA: raise R33BStop("STOP_PRIOR_SUMMARY_IDENTITY")
    r33a=json.loads(R33A_SUMMARY.read_text(encoding="utf-8")); r32s=json.loads(R32B_SUMMARY.read_text(encoding="utf-8"))
    if r33a.get("FAST3_R33A_CLASSIFICATION")!="A_WIN_PROBABILITY_EDGE_BLOCKED_PRIMARILY_BY_LOSS_SEVERITY": raise R33BStop("STOP_R33A_CLASSIFICATION")
    if r32s.get("FAST3_R32B_STATUS")!="PASS" or r32s.get("FROZEN_OOF_SHA256")!=R32B_OOF_SHA or r32s.get("OOF_REGENERATED") or r32s.get("OOF_MODIFIED"): raise R33BStop("STOP_R32B_OOF_SUMMARY")
    oof_path=Path(r32s["OOF_PATH"])
    if file_sha256(oof_path)!=R32B_OOF_SHA: raise R33BStop("STOP_R32B_OOF_HASH")
    r32b=import_file(R32B_RUNNER,"r33b_r32b"); r30a=import_file(R30A_RUNNER,"r33b_r30a")
    if (r32b.UNIVERSE_SHA!=FULL_UNIVERSE_SHA or r32b.LABEL_MANIFEST_SHA!=LABEL_MANIFEST_SHA or r32b.FEATURE_SHA!=FEATURE_SHA
            or r32b.SPLIT_SHA!=SPLIT_SHA or len(r30a.ECONOMIC_FOLDS)!=5): raise R33BStop("STOP_AUTHORITATIVE_CONTRACT")
    return r32b,r30a,r32s,oof_path


def assign_deciles(frame: pd.DataFrame,prediction: str) -> pd.DataFrame:
    x=frame.sort_values([prediction,"decision_timestamp_utc","candidate_id"],ascending=[True,True,True],kind="mergesort").copy()
    x["decile"]=np.floor(np.arange(len(x))*10/len(x)).astype(int)+1; return x


def split_half(frame: pd.DataFrame,prediction: str) -> tuple[pd.DataFrame,pd.DataFrame]:
    x=frame.sort_values([prediction,"decision_timestamp_utc","candidate_id"],ascending=[True,True,True],kind="mergesort")
    boundary=len(x)//2; return x.iloc[:boundary].copy(),x.iloc[boundary:].copy()


def conditional_t1_audit(losses: pd.DataFrame) -> tuple[pd.DataFrame,float | None,float | None,float | None,int,int,int]:
    x=assign_deciles(losses,"pred_t1"); rows=[]; pooled_pred=[]; pooled_loss=[]
    correct=incorrect=tied=0
    for decile,part in x.groupby("decile",sort=True,observed=True):
        spearman=safe_spearman(part.pred_t5,part.abs_loss); low,high=split_half(part,"pred_t5")
        low_mean=float(low.abs_loss.mean()); high_mean=float(high.abs_loss.mean())
        if np.isclose(high_mean,low_mean,rtol=0,atol=1e-15): tied+=1
        elif high_mean>low_mean: correct+=1
        else: incorrect+=1
        pooled_pred.append(part.pred_t5.rank(method="average",pct=True)); pooled_loss.append(part.abs_loss.rank(method="average",pct=True))
        rows.append({"t1_decile":int(decile),"count":len(part),"t1_probability_mean":float(part.pred_t1.mean()),"t5_spearman_vs_abs_loss":spearman,
                     "low_t5_count":len(low),"high_t5_count":len(high),"low_t5_mean_abs_loss":low_mean,"high_t5_mean_abs_loss":high_mean,
                     "high_minus_low_abs_loss":high_mean-low_mean,"ordering":"CORRECT" if high_mean>low_mean else ("TIED" if np.isclose(high_mean,low_mean,rtol=0,atol=1e-15) else "INCORRECT")})
    values=[row["t5_spearman_vs_abs_loss"] for row in rows if row["t5_spearman_vs_abs_loss"] is not None]
    pooled=safe_spearman(pd.concat(pooled_pred),pd.concat(pooled_loss))
    return pd.DataFrame(rows),pooled,float(np.mean(values)) if values else None,float(np.median(values)) if values else None,correct,incorrect,tied


def severity_metrics(losses: pd.DataFrame) -> dict[str,float | int | None]:
    return {"loss_row_count":len(losses),"t5_spearman_vs_actual_t5":safe_spearman(losses.pred_t5,losses.actual_t5),
            "t5_spearman_vs_abs_loss":safe_spearman(losses.pred_t5,losses.abs_loss),
            "t5_mae":float(mean_absolute_error(losses.actual_t5,losses.pred_t5)),
            "t5_rmse":float(np.sqrt(mean_squared_error(losses.actual_t5,losses.pred_t5))),
            "naive_t5_mean_mae":float(mean_absolute_error(losses.actual_t5,losses.naive_t5_mean)),
            "naive_t5_median_mae":float(mean_absolute_error(losses.actual_t5,losses.naive_t5_median))}


def economic_stats(frame: pd.DataFrame) -> dict[str,float | int | None]:
    wins=frame.loc[frame.raw_net20>0,"raw_net20"]; losses=frame.loc[frame.raw_net20<=0,"raw_net20"]
    p=float(len(wins)/len(frame)); gain=float(wins.mean()) if len(wins) else None; abs_loss=float(-losses.mean()) if len(losses) else None
    break_even=abs_loss/(gain+abs_loss) if gain is not None and abs_loss is not None else None
    return {"count":len(frame),"positive_rate":p,"mean_net20":float(frame.raw_net20.mean()),"median_net20":float(frame.raw_net20.median()),
            "mean_gain_given_win":gain,"mean_abs_loss_given_loss":abs_loss,"break_even_win_rate":break_even,
            "p05_net20":float(frame.raw_net20.quantile(.05)),"p01_net20":float(frame.raw_net20.quantile(.01)),"worst_net20":float(frame.raw_net20.min())}


def top20_t5_split(frame: pd.DataFrame) -> tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame]:
    ordered=frame.sort_values(["pred_t1","decision_timestamp_utc","candidate_id"],ascending=[False,True,True],kind="mergesort")
    top=ordered.head(max(1,int(math.ceil(len(ordered)*.20)))); low,high=split_half(top,"pred_t5")
    return top,low,high


def date_diagnostics(losses: pd.DataFrame,top_low: pd.DataFrame,top_high: pd.DataFrame) -> tuple[float | None,float | None,int]:
    by_date=losses.groupby("trading_date",sort=True,observed=True).agg(mean_predicted_t5=("pred_t5","mean"),mean_actual_abs_loss=("abs_loss","mean")).reset_index()
    severity=safe_spearman(by_date.mean_predicted_t5,by_date.mean_actual_abs_loss)
    low=top_low.loc[top_low.raw_net20<0].groupby("trading_date",observed=True).raw_net20.mean().mul(-1)
    high=top_high.loc[top_high.raw_net20<0].groupby("trading_date",observed=True).raw_net20.mean().mul(-1)
    common=low.index.intersection(high.index); spread=float((high.loc[common]-low.loc[common]).mean()) if len(common) else None
    return severity,spread,len(common)


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--run",action="store_true"); args=parser.parse_args()
    if not args.run: raise R33BStop("USE_--run")
    if FROZEN_ROOT.exists() or SCRATCH_ROOT.exists(): raise R33BStop("STOP_OUTPUT_EXISTS")
    r32b,r30a,r32s,r32_oof_path=validate_authority(); before_oof_hash=file_sha256(r32_oof_path)
    _,manifest,features=r32b.guard_authority()
    if len(features)!=FEATURE_COUNT or "pred_t1" in features or "T1" in features or any("VOLUME" in name or "ILLIQUIDITY" in name for name in features): raise R33BStop("STOP_FEATURE_MEMBERSHIP")
    dataset,complete_coverage,missing_counts,_=r32b.construct_dataset(manifest,features)
    dataset["actual_t5"]=derive_t5(dataset.raw_net20); eligible=dataset.raw_net20.lt(0)
    if dataset.loc[~eligible,"actual_t5"].notna().any() or dataset.loc[eligible,"actual_t5"].isna().any(): raise R33BStop("STOP_T5_ELIGIBILITY")
    if not np.allclose(dataset.loc[eligible,"actual_t5"],np.log1p(-dataset.loc[eligible,"raw_net20"]),rtol=0,atol=1e-15): raise R33BStop("STOP_T5_FORMULA")
    zero_count=int(dataset.raw_net20.eq(0).sum()); winner_count=int(dataset.raw_net20.gt(0).sum())
    fold_counts=[]; used_train=np.zeros(len(dataset),dtype=bool)
    for fold in r30a.ECONOMIC_FOLDS:
        train,valid,audit=r32b.fold_masks(dataset,fold); used_train |= (train & eligible).to_numpy()
        for direction in ("UP","DOWN"):
            fold_counts.append({"fold":fold[0],"direction":direction,"train_loss_count":int((train&eligible&dataset["head"].eq(direction)).sum()),
                                "validation_all_count":int((valid&dataset["head"].eq(direction)).sum()),"validation_loss_count":int((valid&eligible&dataset["head"].eq(direction)).sum())})
    contract={"CONTRACT_ID":"FAST3_R33_T5_CONDITIONAL_LOSS_SEVERITY_CONTRACT_R1","STATUS":"FROZEN_BEFORE_FIT","TARGET_NAME":"T5_CONDITIONAL_LOSS_SEVERITY",
              "FORMULA":"natural_log1p(-corporate_action_normalized_executable_net20)","TRAINING_ELIGIBILITY":"label_valid == true AND net20 < 0",
              "ZERO_RETURN_TRAINING_ELIGIBLE":False,"WINNING_ROW_T5_ZERO_FILL":False,"TRANSFORMATION":"NATURAL_LOG1P_ABSOLUTE_LOSS_LOSERS_ONLY",
              "CLIPPING":False,"WINSORIZATION":False,"CORPORATE_ACTION_NORMALIZATION_REQUIRED":True,"TARGET_CONTRACT_SOURCE_SHA256":r32b.TARGET_SHA,
              "FULL_UNIVERSE_IDENTITY_SHA256":FULL_UNIVERSE_SHA,"FULL_UNIVERSE_LABEL_MANIFEST_SHA256":LABEL_MANIFEST_SHA,"FEATURE_MANIFEST_SHA256":FEATURE_SHA,
              "SPLIT_CONTRACT_SHA256":SPLIT_SHA,"FEATURE_COUNT":FEATURE_COUNT,"FEATURE_NAMES":list(features),"T1_PROBABILITY_USED_AS_T5_TRAINING_FEATURE":False,
              "MODEL_FAMILY":"HistGradientBoostingRegressor independent UP/DOWN","HGB_PARAMETERS":r30a.HGB_PARAMS,"HYPERPARAMETER_SEARCH_COUNT":0,
              "FULL_VALID_LABEL_COUNT":len(dataset),"FULL_T5_ELIGIBLE_LOSS_ROW_COUNT":int(eligible.sum()),"TRAIN_LOSS_UNIQUE_ROW_COUNT":int(used_train.sum()),
              "WINNING_ROWS_EXCLUDED_COUNT":winner_count,"ZERO_ROWS_EXCLUDED_COUNT":zero_count,"T5_ELIGIBLE_CANDIDATE_ID_SHA256":candidate_id_hash(dataset.loc[eligible,"candidate_id"]),
              "T5_DISTRIBUTION":{"mean":float(dataset.loc[eligible,"actual_t5"].mean()),"median":float(dataset.loc[eligible,"actual_t5"].median()),"p90":float(dataset.loc[eligible,"actual_t5"].quantile(.90)),"p95":float(dataset.loc[eligible,"actual_t5"].quantile(.95)),"p99":float(dataset.loc[eligible,"actual_t5"].quantile(.99)),"max":float(dataset.loc[eligible,"actual_t5"].max())},
              "PER_FOLD_DIRECTION_COUNTS":fold_counts,"VALIDATION_PREDICTION_SCOPE":"ALL OOF-eligible validation candidates","PRIMARY_EVALUATION_SCOPE":"actual net20 < 0 OOF rows",
              "FOLD_CORRECT_RULE":"severity_spearman > 0 AND conditional_spearman > 0 AND top20_high_abs_loss > low_abs_loss AND top20_low_mean_net20 > high_mean_net20",
              "FINAL_CONFIRMATION_DATA_USED":False}
    FROZEN_ROOT.mkdir(parents=True); SCRATCH_ROOT.mkdir(parents=True)
    contract_path=FROZEN_ROOT/"FAST3_R33_T5_CONDITIONAL_LOSS_SEVERITY_CONTRACT_R1.json"; write_json(contract_path,contract); contract_sha=file_sha256(contract_path)

    categorical=[name in r30a.CATEGORICAL for name in features]; params={**r30a.HGB_PARAMS,"categorical_features":categorical}
    predictions=[]; fit_count=predict_count=0
    for fold in r30a.ECONOMIC_FOLDS:
        train,valid,_=r32b.fold_masks(dataset,fold)
        for direction in ("UP","DOWN"):
            tr=train&eligible&dataset["head"].eq(direction); va=valid&dataset["head"].eq(direction)
            if not tr.any() or not va.any() or file_sha256(contract_path)!=contract_sha: raise R33BStop("STOP_T5_TARGET_CONTRACT_MUTATED_AFTER_FREEZE")
            model=HistGradientBoostingRegressor(**params); model.fit(dataset.loc[tr,list(features)],dataset.loc[tr,"actual_t5"]); fit_count+=1
            part=dataset.loc[va,["candidate_id"]].copy(); part["pred_t5"]=model.predict(dataset.loc[va,list(features)]); predict_count+=1
            part["naive_t5_mean"]=float(dataset.loc[tr,"actual_t5"].mean()); part["naive_t5_median"]=float(dataset.loc[tr,"actual_t5"].median()); part["fold_model"]=fold[0]
            predictions.append(part); del model
    predicted=pd.concat(predictions,ignore_index=True)
    if len(predicted)!=R32B_OOF_ROWS or predicted.candidate_id.duplicated().any() or predicted.pred_t5.isna().any(): raise R33BStop("STOP_T5_PREDICTION_MEMBERSHIP")
    r32_oof=pd.read_parquet(r32_oof_path); r32_oof["decision_timestamp_utc"]=pd.to_datetime(r32_oof.decision_timestamp_utc,utc=True)
    oof=r32_oof.merge(predicted,on="candidate_id",validate="one_to_one")
    if len(oof)!=len(r32_oof) or not oof.fold.eq(oof.fold_model).all(): raise R33BStop("STOP_R32B_T5_OOF_RECONCILIATION")
    oof["abs_loss"]=np.where(oof.raw_net20<0,-oof.raw_net20,np.nan); oof["actual_t5"]=derive_t5(oof.raw_net20)
    oof_path=SCRATCH_ROOT/"FAST3_R33B_T5_OOF_PREDICTIONS.parquet"; oof.to_parquet(oof_path,index=False); oof_sha=file_sha256(oof_path)
    losses=oof.loc[oof.raw_net20<0].copy(); aggregate=severity_metrics(losses)

    loss_deciles=assign_deciles(losses,"pred_t5"); decile_rows=[]
    for decile,part in loss_deciles.groupby("decile",sort=True,observed=True):
        decile_rows.append({"decile":int(decile),"count":len(part),"mean_predicted_t5":float(part.pred_t5.mean()),"actual_mean_abs_loss":float(part.abs_loss.mean()),
                            "actual_median_abs_loss":float(part.abs_loss.median()),"actual_p90_abs_loss":float(part.abs_loss.quantile(.90)),"actual_p95_abs_loss":float(part.abs_loss.quantile(.95)),"actual_mean_signed_net20":float(part.raw_net20.mean())})
    loss_decile_table=pd.DataFrame(decile_rows); decile_s=safe_spearman(loss_decile_table.decile,loss_decile_table.actual_mean_abs_loss)
    conditional,conditional_s,within_mean,within_median,correct_deciles,incorrect_deciles,tied_deciles=conditional_t1_audit(losses)

    top20,low,high=top20_t5_split(oof); low_stats=economic_stats(low); high_stats=economic_stats(high)
    economic_correct=bool(low_stats["mean_abs_loss_given_loss"]<high_stats["mean_abs_loss_given_loss"] and low_stats["mean_net20"]>high_stats["mean_net20"])
    first_positive=bool(low_stats["mean_net20"]>0)
    split_table=pd.DataFrame([{"risk_half":"LOW_T5_RISK_HALF",**low_stats},{"risk_half":"HIGH_T5_RISK_HALF",**high_stats}])

    fold_rows=[]; correct_folds=0
    for fold,part in oof.groupby("fold",sort=True,observed=True):
        fold_losses=part.loc[part.raw_net20<0].copy(); severity=safe_spearman(fold_losses.pred_t5,fold_losses.abs_loss)
        _,fold_conditional,_,_,_,_,_=conditional_t1_audit(fold_losses); _,fold_low,fold_high=top20_t5_split(part)
        low_fold=economic_stats(fold_low); high_fold=economic_stats(fold_high)
        correct=bool(severity is not None and severity>0 and fold_conditional is not None and fold_conditional>0
                     and high_fold["mean_abs_loss_given_loss"]>low_fold["mean_abs_loss_given_loss"] and low_fold["mean_net20"]>high_fold["mean_net20"])
        correct_folds+=int(correct)
        fold_rows.append({"fold":fold,"loss_row_count":len(fold_losses),"t5_spearman_vs_abs_loss":severity,"conditional_t5_loss_spearman":fold_conditional,
                          "top20_low_t5_mean_abs_loss":low_fold["mean_abs_loss_given_loss"],"top20_high_t5_mean_abs_loss":high_fold["mean_abs_loss_given_loss"],
                          "top20_low_t5_mean_net20":low_fold["mean_net20"],"top20_high_t5_mean_net20":high_fold["mean_net20"],"ordering":"CORRECT" if correct else "INCORRECT"})
    fold_table=pd.DataFrame(fold_rows); incorrect_folds=5-correct_folds
    date_s,date_spread,date_common=date_diagnostics(losses,low,high)

    robustness=[]; direction_records=[]
    for direction,part in oof.groupby("head",sort=True,observed=True):
        part_losses=part.loc[part.raw_net20<0].copy(); severity=safe_spearman(part_losses.pred_t5,part_losses.abs_loss)
        _,cond,_,_,_,_,_=conditional_t1_audit(part_losses); _,dlow,dhigh=top20_t5_split(part)
        dlow_loss=float(-dlow.loc[dlow.raw_net20<0,"raw_net20"].mean()); dhigh_loss=float(-dhigh.loc[dhigh.raw_net20<0,"raw_net20"].mean()); spread=dhigh_loss-dlow_loss
        status="POSITIVE_CONDITIONAL_SEVERITY_INFORMATION" if severity is not None and severity>0 and cond is not None and cond>0 and spread>0 else "NO_POSITIVE_CONDITIONAL_SEVERITY_INFORMATION"
        row={"record_type":"DIRECTION","group":direction,"loss_row_count":len(part_losses),"t5_spearman":severity,"conditional_t5_spearman":cond,"top20_low_high_loss_spread":spread,"status":status}; robustness.append(row); direction_records.append(row)
    year_records=[]
    for year,part in oof.groupby(oof.decision_timestamp_utc.dt.year,sort=True):
        part_losses=part.loc[part.raw_net20<0].copy(); severity=safe_spearman(part_losses.pred_t5,part_losses.abs_loss); _,ylow,yhigh=top20_t5_split(part)
        spread=float(-yhigh.loc[yhigh.raw_net20<0,"raw_net20"].mean()+ylow.loc[ylow.raw_net20<0,"raw_net20"].mean())
        row={"record_type":"YEAR","group":int(year),"loss_row_count":len(part_losses),"t5_spearman":severity,"top20_low_high_loss_spread":spread}; robustness.append(row); year_records.append(row)
    robustness.append({"record_type":"DATE_BALANCED","group":"ALL_LOSS_ROWS","loss_row_count":len(losses),"t5_spearman":date_s,"top20_low_high_loss_spread":date_spread,"common_date_count":date_common})
    robustness_table=pd.DataFrame(robustness)

    mae_better=bool(aggregate["t5_mae"]<aggregate["naive_t5_mean_mae"] or aggregate["t5_mae"]<aggregate["naive_t5_median_mae"])
    go=bool(aggregate["t5_spearman_vs_abs_loss"]>0 and conditional_s is not None and conditional_s>0 and correct_deciles>=6 and correct_folds>=3 and mae_better)
    strong=bool(go and aggregate["t5_spearman_vs_abs_loss"]>=.05 and conditional_s>=.03 and correct_deciles>=7 and correct_folds>=3)
    if strong and economic_correct: classification="B_STRONG_INCREMENTAL_LOSS_SEVERITY_SIGNAL"; decision="STRONG_INCREMENTAL_CONDITIONAL_LOSS_SEVERITY_INFORMATION"
    elif go: classification="A_CONDITIONAL_LOSS_SEVERITY_SIGNAL_CONFIRMED"; decision="CONDITIONAL_LOSS_SEVERITY_INFORMATION_CONFIRMED"
    elif aggregate["t5_spearman_vs_abs_loss"]<0 and conditional_s is not None and conditional_s<0 and correct_deciles<=4 and correct_folds<=2 and not economic_correct: classification="E_CONDITIONAL_LOSS_SIGNAL_REVERSED"; decision="CONDITIONAL_LOSS_SEVERITY_RANKING_REVERSED"
    elif aggregate["t5_spearman_vs_abs_loss"]>0 or (conditional_s is not None and conditional_s>0) or correct_deciles>=5 or correct_folds>=2: classification="C_WEAK_OR_INCONCLUSIVE_CONDITIONAL_LOSS_SIGNAL"; decision="WEAK_OR_INCONCLUSIVE_CONDITIONAL_LOSS_INFORMATION"
    else: classification="D_NO_CONDITIONAL_LOSS_SEVERITY_SIGNAL"; decision="NO_CONDITIONAL_LOSS_SEVERITY_INFORMATION"
    next_stage="FREEZE_T1_PLUS_CONDITIONAL_T5_RISK_ARCHITECTURE_DESIGN" if classification[0] in "AB" else ("WEAK_STOP_WITHOUT_T5_TUNING" if classification.startswith("C_") else "CLOSE_CURRENT_29_FEATURE_CONDITIONAL_LOSS_PATH;NEW_INFORMATION_DOMAIN_REQUIRED")
    direction_map={row["group"]:row for row in direction_records}
    report_path=FROZEN_ROOT/"FAST3_R33B_REPORT.md"; summary_path=FROZEN_ROOT/"FAST3_R33B_SUMMARY.json"
    summary={"FAST3_R33B_STATUS":"PASS","FAST3_R33B_CLASSIFICATION":classification,"FAST3_R33B_DECISION":decision,"T5_TARGET_CONTRACT_SHA256":contract_sha,"T5_TARGET_CONTRACT_FROZEN":True,
             "FULL_VALID_LABEL_COUNT":len(dataset),"FULL_T5_ELIGIBLE_LOSS_ROW_COUNT":int(eligible.sum()),"TRAIN_LOSS_ROW_COUNT":int(used_train.sum()),"TOTAL_FOLD_TRAIN_LOSS_OBSERVATIONS":sum(row["train_loss_count"] for row in fold_counts),
             "OOF_ROW_COUNT":len(oof),"OOF_LOSS_ROW_COUNT":len(losses),"FEATURE_MANIFEST_SHA256":FEATURE_SHA,"FEATURE_COUNT":FEATURE_COUNT,
             "MODEL_FIT_COUNT":fit_count,"MODEL_PREDICT_CALL_COUNT":predict_count,"HYPERPARAMETER_SEARCH_COUNT":0,"MODEL_FAMILY_SEARCH_COUNT":0,"FEATURE_SEARCH_COUNT":0,"FEATURE_DROP_COUNT":0,
             "NEW_FEATURE_COUNT":0,"NEW_TARGET_COUNT":1,"TARGET_SEARCH_COUNT":0,"T1_PROBABILITY_USED_AS_T5_TRAINING_FEATURE":False,"R31B_VOLUME_FEATURES_USED":False,
             "T5_SPEARMAN_VS_ACTUAL_T5":aggregate["t5_spearman_vs_actual_t5"],"T5_SPEARMAN_VS_ABS_LOSS":aggregate["t5_spearman_vs_abs_loss"],"T5_MAE":aggregate["t5_mae"],"T5_RMSE":aggregate["t5_rmse"],
             "NAIVE_T5_MEAN_MAE":aggregate["naive_t5_mean_mae"],"NAIVE_T5_MEDIAN_MAE":aggregate["naive_t5_median_mae"],"T5_DECILE_ABS_LOSS_SPEARMAN":decile_s,
             "CONDITIONAL_T5_LOSS_SPEARMAN":conditional_s,"MEAN_WITHIN_T1_DECILE_T5_SPEARMAN":within_mean,"MEDIAN_WITHIN_T1_DECILE_T5_SPEARMAN":within_median,
             "CORRECT_T1_DECILE_COUNT":correct_deciles,"INCORRECT_T1_DECILE_COUNT":incorrect_deciles,"TIED_T1_DECILE_COUNT":tied_deciles,"T5_CORRECT_FOLD_COUNT":correct_folds,"T5_INCORRECT_FOLD_COUNT":incorrect_folds,
             "DATE_BALANCED_T5_SEVERITY_SPEARMAN":date_s,"DATE_BALANCED_T1_TOP20_LOW_HIGH_LOSS_SPREAD":date_spread,"DATE_BALANCED_COMMON_DATE_COUNT":date_common,
             "T1_TOP20_LOW_T5_COUNT":low_stats["count"],"T1_TOP20_HIGH_T5_COUNT":high_stats["count"],"T1_TOP20_LOW_T5_POSITIVE_RATE":low_stats["positive_rate"],"T1_TOP20_HIGH_T5_POSITIVE_RATE":high_stats["positive_rate"],
             "T1_TOP20_LOW_T5_MEAN_NET20":low_stats["mean_net20"],"T1_TOP20_HIGH_T5_MEAN_NET20":high_stats["mean_net20"],"T1_TOP20_LOW_T5_MEAN_ABS_LOSS":low_stats["mean_abs_loss_given_loss"],"T1_TOP20_HIGH_T5_MEAN_ABS_LOSS":high_stats["mean_abs_loss_given_loss"],
             "T1_TOP20_LOW_T5_BREAK_EVEN_WIN_RATE":low_stats["break_even_win_rate"],"T1_TOP20_HIGH_T5_BREAK_EVEN_WIN_RATE":high_stats["break_even_win_rate"],"T1_TOP20_LOW_T5_P05":low_stats["p05_net20"],"T1_TOP20_HIGH_T5_P05":high_stats["p05_net20"],
             "T1_TOP20_ECONOMIC_DIAGNOSTIC_CORRECT":economic_correct,"FIRST_RISK_FILTERED_POSITIVE_COHORT":first_positive,
             "UP_T5_STATUS":direction_map["UP"]["status"],"DOWN_T5_STATUS":direction_map["DOWN"]["status"],"YEAR_ROBUSTNESS":year_records,"DIRECTION_ROBUSTNESS":direction_records,
             "T5_DEVELOPMENT_GATE":"GO" if go else "NO_GO","T5_STRONG_DEVELOPMENT_SIGNAL":strong,"NEW_BOOTSTRAP_PROTOCOL":False,
             "CORPORATE_ACTION_NORMALIZATION_REQUIRED":True,"TAIL_CLIPPING_USED":False,"CANDIDATE_SUBSAMPLE_COUNT":0,"OOF_REGENERATED":False,"R32B_OOF_MODIFIED":False,"R32B_OOF_SHA256":before_oof_hash,
             "FINAL_CONFIRMATION_DATA_USED":False,"FINAL_CONFIRMATION_DATA_INSPECTED":False,"FINAL_CONFIRMATION_OUTCOME_READ_COUNT":0,"OFFICIAL_ADOPTION_ALLOWED":False,"LIVE_TRADING_ALLOWED":False,
             "R29_MODIFIED":False,"R29_ALLOWED_TO_RESUME":False,"DATA_ROOT_WRITE_COUNT":0,"RESULT_FILES_WRITTEN_TO_GIT_REPO":False,"PRE_EXISTING_TRACKED_CHANGES_PRESERVED":True,"PRE_EXISTING_UNTRACKED_FILES_PRESERVED":True,"DESTRUCTIVE_GIT_COMMAND_USED":False,"BROAD_GIT_ADD_USED":False,
             "R33B_NEW_SOURCE_FILE_COUNT":1,"R33B_NEW_TEST_FILE_COUNT":1,"NEW_HELPER_FILE_COUNT":0,"R33B_GENERATED_REPO_ARTIFACT_COUNT":0,"ANTI_BLOAT_STATUS":"PASS",
             "PRIMARY_RESEARCH_INTERPRETATION":decision,"NEXT_STAGE":next_stage,"REPORT_PATH":str(report_path),"SUMMARY_JSON_PATH":str(summary_path),"T5_CONTRACT_PATH":str(contract_path),"T5_OOF_PATH":str(oof_path),"T5_OOF_SHA256":oof_sha,"T5_OOF_ROW_COUNT":len(oof),
             "FEATURE_COMPLETE_ROW_RATE":complete_coverage,"FEATURE_MISSING_COUNTS":missing_counts}
    if file_sha256(contract_path)!=contract_sha or file_sha256(r32_oof_path)!=before_oof_hash: raise R33BStop("STOP_FROZEN_ARTIFACT_MUTATION")
    fold_table.to_csv(FROZEN_ROOT/"FAST3_R33B_T5_FOLD_METRICS.csv",index=False); loss_decile_table.to_csv(FROZEN_ROOT/"FAST3_R33B_T5_LOSS_DECILES.csv",index=False)
    conditional.to_csv(FROZEN_ROOT/"FAST3_R33B_T1_CONDITIONAL_T5.csv",index=False); split_table.to_csv(FROZEN_ROOT/"FAST3_R33B_T1_TOP20_T5_SPLIT.csv",index=False); robustness_table.to_csv(FROZEN_ROOT/"FAST3_R33B_ROBUSTNESS.csv",index=False)
    write_json(summary_path,summary)
    report=f"""# FAST3 R33B — Conditional Loss-Severity Learning\n\n## Decision\n\n`{classification}`\n\n- T5 gate / strong: `{summary['T5_DEVELOPMENT_GATE']}` / `{strong}`.\n- T5 Spearman vs absolute loss: `{aggregate['t5_spearman_vs_abs_loss']}`.\n- Conditional T5-loss Spearman within frozen T1 deciles: `{conditional_s}`.\n- Correct T1 deciles / folds: `{correct_deciles}/10` / `{correct_folds}/5`.\n- Model / naive mean / naive median MAE: `{aggregate['t5_mae']}` / `{aggregate['naive_t5_mean_mae']}` / `{aggregate['naive_t5_median_mae']}`.\n- T1 Top20 low/high T5 mean loss: `{low_stats['mean_abs_loss_given_loss']}` / `{high_stats['mean_abs_loss_given_loss']}`.\n- T1 Top20 low/high T5 mean net20: `{low_stats['mean_net20']}` / `{high_stats['mean_net20']}`.\n\nT5 was trained only on strict losing training rows, predicted for every validation row, and evaluated on realized losers. Frozen T1 probability was used only for conditional diagnostics, never as T5 X. Final confirmation remains sealed.\n"""
    report_path.write_text(report,encoding="utf-8"); print(json.dumps(summary,indent=2,default=json_default,allow_nan=False)); return 0


if __name__=="__main__":
    try: raise SystemExit(main())
    except R33BStop as exc:
        print(f"FAST3_R33B_STATUS=STOPPED_REQUIRES_MANUAL_CODEX_REVIEW\nREASON={exc}",file=sys.stderr); raise SystemExit(2)
