#!/usr/bin/env python
"""FAST3 R30C frozen downside-severity / left-tail predictability audit."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

SOURCE_ROOT = Path(r"D:\us-tech-quant")
DATA_ROOT = Path(r"D:\us-tech-quant-data")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
CACHE_ROOT = Path(r"D:\us-tech-quant-cache")
R30A_FROZEN = RESULTS_ROOT / "frozen" / "fast3" / "r30a_economic_target_20260809T120000Z"
R30A_RUNNER = SOURCE_ROOT / "fast3" / "scripts" / "run" / "fast3_r30a_economic_target_baseline_training.py"
R30B_FROZEN = RESULTS_ROOT / "frozen" / "fast3" / "r30b_factor_expansion_20260809T140000Z"
R30B_SCRATCH = RESULTS_ROOT / "scratch" / "fast3" / "r30b_factor_expansion_20260809T140000Z"

TARGET_CONTRACT = R30A_FROZEN / "FAST3_R30_T1_T2_ECONOMIC_TARGET_CONTRACT_R1.json"
R30A_DATA_IDENTITY = R30A_FROZEN / "FAST3_R30A_TRAINING_DATA_IDENTITY.json"
R30A_FEATURE_IDENTITY = R30A_FROZEN / "FAST3_R30A_FEATURE_IDENTITY.json"
R30A_SPLIT_IDENTITY = R30A_FROZEN / "FAST3_R30A_SPLIT_IDENTITY.json"
R30B_MANIFEST = R30B_FROZEN / "FAST3_R30B_EXPANDED_FEATURE_MANIFEST_R1.json"
R30B_SUMMARY = R30B_FROZEN / "FAST3_R30B_SUMMARY.json"
R30B_T1_OOF = R30B_SCRATCH / "FAST3_R30B_ARM_ALL_OOF.parquet"

TARGET_CONTRACT_SHA256 = "381ce44099d865748e73f5538c9327ad6a9619c7bcdbf18bcff8b9b5cfdaa996"
BASELINE_FEATURE_MANIFEST_SHA256 = "3cac01f22f8a0b308f2d666d06e36abe13643c4d60948bdc312a5a1a01b96ab3"
R30B_FEATURE_MANIFEST_SHA256 = "248c4d1eabcbcee545ffc95f5f366390889c13199ec90d84d5bbd0f6332f4718"
SPLIT_CONTRACT_SHA256 = "38352151a703737d74b4d61dbe68f82a9c6f3d5058aa72bd2a1896e19a5cb412"
BASELINE_FEATURES = (
    "return_5m", "return_15m", "return_60m", "realized_vol_15m",
    "realized_vol_60m", "relative_volume", "range_position", "symbol_code",
    "direction_code", "session_code", "volume_zscore_60m",
    "signed_volume_pressure_15m", "peer_return_15m", "relative_return_15m",
)
ARM_ORDER = ("ARM_BASELINE", "ARM_ALL")
LOW_COHORTS = (50, 30, 20, 10)
HIGH_COHORTS = (20, 10)


class R30CStop(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, np.floating): return None if not np.isfinite(value) else float(value)
    if isinstance(value, (Path, pd.Timestamp, datetime)): return str(value)
    if pd.isna(value): return None
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=json_default, allow_nan=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None: raise R30CStop("STOP_MODULE_IMPORT")
    spec.loader.exec_module(module)
    return module


def t4_contract(created_at: str) -> dict[str, Any]:
    return {
        "CONTRACT_ID": "FAST3_R30_T4_DOWNSIDE_SEVERITY_CONTRACT_R1",
        "GENERATION": "R30", "STAGE": "R30C", "STATUS": "FROZEN_BEFORE_MODEL_FIT",
        "CREATED_AT_UTC": created_at, "PARENT_TARGET_CONTRACT_SHA256": TARGET_CONTRACT_SHA256,
        "TARGET_NAME": "T4_DOWNSIDE_SEVERITY", "RAW_ECONOMIC_VALUE": "corporate-action-normalized executable NET20",
        "LOSS_FORMULA": "loss=max(-net20,0)", "TARGET_FORMULA": "log1p(max(-net20,0))",
        "LOG_BASE": "NATURAL", "PROFITABLE_TRADE_TARGET": 0.0, "CLIPPING": False,
        "WINSORIZATION": False, "LOSS_THRESHOLD_SEARCH": False, "QUANTILE_THRESHOLD": False,
        "TRANSFORMATION_SEARCH": False, "TRANSACTION_COST": "20bps inherited unchanged",
        "CORPORATE_ACTION_NORMALIZATION": "inherited unchanged from parent target contract",
        "ENTRY_EXIT_INSTRUMENT_PREENTRY_MISSING_POLICIES": "inherited unchanged from parent target contract",
        "FEATURE_DEFINITION_CHANGES": 0, "NEW_FEATURE_COUNT": 0,
        "ARMS": {"ARM_BASELINE": list(BASELINE_FEATURES), "ARM_ALL": "exact frozen R30B ARM_ALL features"},
        "SPLIT_CONTRACT_SHA256": SPLIT_CONTRACT_SHA256,
        "CLASSIFICATION_POLICY": {
            "A": "ARM_ALL GO and incremental downside information",
            "B": "downside signal present only in baseline or nonincremental",
            "D": "weak or inconclusive downside signal",
            "E": "ARM_ALL Spearman<=0, ordering absent, and majority folds fail",
        },
        "FINAL_CONFIRMATION_DATA_USED": False, "MUTATION_POLICY": "STOP_T4_TARGET_CONTRACT_MUTATED_AFTER_FREEZE",
    }


def freeze_t4_contract(path: Path, created_at: str) -> str:
    if path.exists(): raise R30CStop("STOP_T4_TARGET_CONTRACT_ALREADY_EXISTS")
    write_json(path, t4_contract(created_at))
    return file_sha256(path)


def guard_t4_contract(path: Path, expected_sha: str) -> None:
    if not path.is_file() or file_sha256(path) != expected_sha:
        raise R30CStop("STOP_T4_TARGET_CONTRACT_MUTATED_AFTER_FREEZE")


def make_t4(raw_net20: pd.Series) -> tuple[pd.Series, pd.Series]:
    raw = pd.to_numeric(raw_net20, errors="raise")
    loss = (-raw).clip(lower=0.0)
    return loss, np.log1p(loss)


def verify_authority(r30a) -> dict[str, Any]:
    if file_sha256(TARGET_CONTRACT) != TARGET_CONTRACT_SHA256: raise R30CStop("STOP_PARENT_TARGET_CONTRACT_HASH")
    if file_sha256(R30B_MANIFEST) != R30B_FEATURE_MANIFEST_SHA256: raise R30CStop("STOP_R30B_FEATURE_MANIFEST_HASH")
    data = read_json(R30A_DATA_IDENTITY); feature = read_json(R30A_FEATURE_IDENTITY); split = read_json(R30A_SPLIT_IDENTITY)
    manifest = read_json(R30B_MANIFEST); r30b = read_json(R30B_SUMMARY)
    if feature["FEATURE_MANIFEST_SHA256"] != BASELINE_FEATURE_MANIFEST_SHA256 or feature["FEATURE_NAMES"] != list(BASELINE_FEATURES):
        raise R30CStop("STOP_BASELINE_FEATURE_IDENTITY")
    if split["SPLIT_CONTRACT_SHA256"] != SPLIT_CONTRACT_SHA256 or split["FOLD_COUNT"] != 5:
        raise R30CStop("STOP_SPLIT_IDENTITY")
    if r30b["FAST3_R30B_CLASSIFICATION"] != "D_WEAK_OR_INCONCLUSIVE_FACTOR_GAIN" or r30b["BEST_FACTOR_FAMILY"] != "TREND_PATH_QUALITY":
        raise R30CStop("STOP_R30B_CONCLUSION_IDENTITY")
    if any(r30b[key] != "NO_GO" for key in ("TREND_STATUS", "VOL_RISK_STATUS", "CROSS_ASSET_STATUS")) or r30b["ALL_IMPROVED_FOLD_COUNT"] != 2:
        raise R30CStop("STOP_R30B_FAMILY_CONCLUSION")
    expected_all = tuple(manifest["arms"]["ARM_ALL"])
    if tuple(manifest["baseline_features"]) != BASELINE_FEATURES or len(expected_all) != 29 or expected_all[:14] != BASELINE_FEATURES:
        raise R30CStop("STOP_ARM_FEATURE_IDENTITY")
    factor_ledger = Path(manifest["factor_ledger_path"])
    if file_sha256(factor_ledger) != manifest["factor_ledger_sha256"]: raise R30CStop("STOP_FACTOR_LEDGER_HASH")
    if file_sha256(Path(data["FEATURE_LEDGER_SOURCE"])) != data["FEATURE_LEDGER_SHA256"]: raise R30CStop("STOP_BASELINE_LEDGER_HASH")
    if file_sha256(Path(data["TARGET_LEDGER_PATH"])) != data["TARGET_LEDGER_SHA256"]: raise R30CStop("STOP_TARGET_LEDGER_HASH")
    if not R30B_T1_OOF.is_file() or data["FINAL_CONFIRMATION_DATA_USED"] or manifest["FINAL_CONFIRMATION_DATA_USED"]:
        raise R30CStop("STOP_HOLDOUT_OR_T1_OOF_IDENTITY")
    return {"data": data, "feature": feature, "split": split, "manifest": manifest,
            "r30b": r30b, "all_features": expected_all, "factor_ledger": factor_ledger}


def safe_spearman(x: Any, y: Any) -> float | None:
    a = np.asarray(x, dtype=float); b = np.asarray(y, dtype=float)
    mask = np.isfinite(a) & np.isfinite(b); a = a[mask]; b = b[mask]
    if len(a) < 2 or np.unique(a).size < 2 or np.unique(b).size < 2: return None
    value = float(spearmanr(a, b).statistic)
    return value if np.isfinite(value) else None


def t4_metrics(frame: pd.DataFrame, prediction: str = "pred_t4") -> dict[str, Any]:
    actual = frame["T4_DOWNSIDE_SEVERITY"].to_numpy(float); pred = frame[prediction].to_numpy(float)
    return {"MAE": float(mean_absolute_error(actual, pred)), "RMSE": float(np.sqrt(mean_squared_error(actual, pred))),
            "Spearman_vs_T4": safe_spearman(pred, actual), "Spearman_vs_actual_loss": safe_spearman(pred, frame["actual_loss"])}


def ordered(frame: pd.DataFrame, prediction: str, ascending: bool) -> pd.DataFrame:
    return frame.sort_values([prediction, "decision_timestamp_utc", "candidate_id"], ascending=[ascending, True, True], kind="mergesort")


def risk_deciles(frame: pd.DataFrame, arm: str) -> pd.DataFrame:
    ranked = ordered(frame, "pred_t4", True).copy()
    ranked["risk_decile"] = np.floor(np.arange(len(ranked))*10/len(ranked)).astype(int)+1
    rows = ranked.groupby("risk_decile", sort=True).agg(
        trade_count=("candidate_id", "size"), predicted_T4_mean=("pred_t4", "mean"),
        actual_loss_rate=("actual_loss", lambda x: float((x>0).mean())), actual_mean_loss=("actual_loss", "mean"),
        actual_mean_net20=("raw_net20", "mean"), actual_median_net20=("raw_net20", "median"),
        actual_p05_net20=("raw_net20", lambda x: float(x.quantile(.05))),
        actual_p01_net20=("raw_net20", lambda x: float(x.quantile(.01))),
    ).reset_index(); rows.insert(0, "arm", arm)
    return rows


def risk_cohorts(frame: pd.DataFrame, arm: str) -> pd.DataFrame:
    rows = []
    for risk_side, percentages, ascending in (("LOWEST_RISK", LOW_COHORTS, True), ("HIGHEST_RISK", HIGH_COHORTS, False)):
        ranked = ordered(frame, "pred_t4", ascending)
        for pct in percentages:
            count = max(1, int(math.ceil(len(ranked)*pct/100)))
            part = ranked.head(count)
            rows.append({"arm": arm, "cohort": f"{risk_side}_{pct}%", "risk_side": risk_side, "percent": pct,
                         "count": len(part), "win_rate": float((part.raw_net20>0).mean()),
                         "mean_net20": float(part.raw_net20.mean()), "median_net20": float(part.raw_net20.median()),
                         "mean_loss": float(part.actual_loss.mean()), "p05_net20": float(part.raw_net20.quantile(.05)),
                         "p01_net20": float(part.raw_net20.quantile(.01)), "worst_trade": float(part.raw_net20.min())})
    return pd.DataFrame(rows)


def cohort_row(table: pd.DataFrame, side: str, pct: int) -> pd.Series:
    return table.loc[table.risk_side.eq(side) & table.percent.eq(pct)].iloc[0]


def decile_metrics(deciles: pd.DataFrame) -> dict[str, Any]:
    return {"decile_actual_loss_spearman": safe_spearman(deciles.risk_decile, deciles.actual_mean_loss),
            "decile_loss_rate_spearman": safe_spearman(deciles.risk_decile, deciles.actual_loss_rate),
            "decile_mean_net20_spearman": safe_spearman(deciles.risk_decile, deciles.actual_mean_net20)}


def diagnostic_cell(t1: pd.DataFrame, t4: pd.DataFrame) -> tuple[dict[str, Any], dict[str, Any]]:
    joined = t4[["candidate_id", "decision_timestamp_utc", "pred_t4", "raw_net20", "actual_loss"]].merge(
        t1[["candidate_id", "pred_t1"]], on="candidate_id", validate="one_to_one")
    top_count = max(1, int(math.ceil(len(joined)*.20))); low_count = max(1, int(math.ceil(len(joined)*.50)))
    top_ids = set(ordered(joined, "pred_t1", False).head(top_count).candidate_id)
    low_ids = set(ordered(joined, "pred_t4", True).head(low_count).candidate_id)
    top = joined.loc[joined.candidate_id.isin(top_ids)]; cell = joined.loc[joined.candidate_id.isin(top_ids & low_ids)]
    top_diag = {"count": len(top), "actual_loss_rate": float((top.actual_loss>0).mean()), "mean_loss": float(top.actual_loss.mean()),
                "mean_net20": float(top.raw_net20.mean()), "p05_net20": float(top.raw_net20.quantile(.05)), "worst_trade": float(top.raw_net20.min())}
    cell_diag = {"DIAGNOSTIC_ONLY": True, "NOT_A_FROZEN_TRADING_RULE": True, "count": len(cell),
                 "positive_rate": float((cell.raw_net20>0).mean()), "mean_net20": float(cell.raw_net20.mean()),
                 "median_net20": float(cell.raw_net20.median()), "p05_net20": float(cell.raw_net20.quantile(.05))}
    return top_diag, cell_diag


def grouped_robustness(oof: pd.DataFrame, column: str, group_type: str) -> pd.DataFrame:
    rows = []
    for value, part in oof.groupby(column, sort=True):
        metrics = t4_metrics(part); cohorts = risk_cohorts(part, "ARM_ALL")
        low = cohort_row(cohorts, "LOWEST_RISK", 20); high = cohort_row(cohorts, "HIGHEST_RISK", 20)
        rows.append({"robustness_type": group_type, "group": str(value), "sample_count": len(part),
                     "T4_Spearman": metrics["Spearman_vs_actual_loss"], "low20_mean_net20": low.mean_net20,
                     "high20_mean_net20": high.mean_net20, "low_high_spread": low.mean_net20-high.mean_net20,
                     "correct_order": bool(low.mean_net20>high.mean_net20)})
    return pd.DataFrame(rows)


def report_text(s: dict[str, Any]) -> str:
    return f"""# FAST3 R30C — Frozen Downside-Severity / Left-Tail Predictability Audit

## Decision

- Status: `{s['FAST3_R30C_STATUS']}`
- Classification: `{s['FAST3_R30C_CLASSIFICATION']}`
- Decision: `{s['FAST3_R30C_DECISION']}`
- T4 gate / strong: `{s['T4_DEVELOPMENT_GATE']}` / `{s['T4_STRONG_DEVELOPMENT_SIGNAL']}`
- Final untouched used: `false`; adoption/live allowed: `false / false`

## Direct answers

1. Can 29 features predict loss severity? `{s['PLAIN_T4_ANSWER']}`.
2. ARM_ALL T4 Spearman versus actual loss: `{s['ALL_T4_SPEARMAN']}`.
3. 14→29 incremental downside information: delta Spearman `{s['DELTA_T4_SPEARMAN']}`; `{s['INCREMENTAL_ANSWER']}`.
4. Lowest-risk 20% mean net20: `{s['ALL_LOW20_MEAN_NET20']}`.
5. Highest-risk 20% mean net20: `{s['ALL_HIGH20_MEAN_NET20']}`.
6. Risk-decile monotonicity: loss Spearman `{s['ALL_T4_DECILE_LOSS_SPEARMAN']}`, mean-net20 Spearman `{s['ALL_T4_DECILE_MEAN_NET20_SPEARMAN']}`.
7. Correct-order folds: `{s['CORRECT_ORDER_FOLD_COUNT']}/5`.
8. T1 probability versus T4 risk Spearman: `{s['R30B_T1_PROBABILITY_VS_T4_RISK_SPEARMAN']}`; `{s['T1_LEFT_TAIL_EXPLANATION']}`.
9. T1 Top20 & T4 Low50 diagnostic: count `{s['DIAGNOSTIC_T1_TOP20_LOW50_COUNT']}`, win rate `{s['DIAGNOSTIC_T1_TOP20_LOW50_POSITIVE_RATE']}`, mean `{s['DIAGNOSTIC_T1_TOP20_LOW50_MEAN_NET20']}`.
10. Easier direction: `{s['EASIER_DOWNSIDE_DIRECTION']}`.
11. New 15 factors versus T1/T2: `{s['NEW_FACTORS_DOWNSIDE_VS_PAYOFF_ANSWER']}`.
12. Next step: `{s['NEXT_STAGE']}`.
13. Final untouched recommendation: `{s['FINAL_CONFIRMATION_RECOMMENDATION']}`.

The single 2D cell is diagnostic only and is not a frozen trading rule. No T1 model was retrained.
"""


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--run-id", required=True); args = parser.parse_args()
    name = f"r30c_downside_severity_{args.run_id}"
    runtime = RESULTS_ROOT/"runtime"/"fast3"/name; scratch = RESULTS_ROOT/"scratch"/"fast3"/name; frozen = RESULTS_ROOT/"frozen"/"fast3"/name
    if any(path.exists() for path in (runtime, scratch, frozen)): raise R30CStop("STOP_RUN_ID_EXISTS")
    runtime.mkdir(parents=True); (scratch/"models").mkdir(parents=True); frozen.mkdir(parents=True)
    r30a = import_module(R30A_RUNNER, "fast3_r30c_bound_r30a"); authority = verify_authority(r30a)
    branch = subprocess.check_output(["git","branch","--show-current"],cwd=SOURCE_ROOT,text=True).strip(); head = subprocess.check_output(["git","rev-parse","HEAD"],cwd=SOURCE_ROOT,text=True).strip()
    contract_path = frozen/"FAST3_R30_T4_DOWNSIDE_SEVERITY_CONTRACT_R1.json"
    contract_sha = freeze_t4_contract(contract_path, datetime.now(timezone.utc).isoformat()); guard_t4_contract(contract_path, contract_sha)
    targets = pd.read_parquet(Path(authority["data"]["TARGET_LEDGER_PATH"])); baseline = pd.read_parquet(Path(authority["data"]["FEATURE_LEDGER_SOURCE"])); factors = pd.read_parquet(authority["factor_ledger"])
    dataset = targets.merge(baseline.drop(columns=["head","underlying_symbol"]),on=["candidate_id","decision_timestamp_utc"],validate="one_to_one").merge(baseline[["candidate_id","underlying_symbol"]],on="candidate_id",validate="one_to_one")
    new_features = authority["all_features"][14:]; dataset = dataset.merge(factors[["candidate_id",*new_features]],on="candidate_id",validate="one_to_one")
    dataset["actual_loss"], dataset["T4_DOWNSIDE_SEVERITY"] = make_t4(dataset.raw_net20)
    if len(dataset)!=1197 or dataset.decision_timestamp_utc.max()>=r30a.TRUE_HOLDOUT_START: raise R30CStop("STOP_TARGET_OR_HOLDOUT_CARDINALITY")
    arms={"ARM_BASELINE":BASELINE_FEATURES,"ARM_ALL":authority["all_features"]}; oof_by_arm={}; fold_rows=[]; model_records=[]; fit_count=predict_count=0
    for arm in ARM_ORDER:
        features=arms[arm]; mask=[name in r30a.CATEGORICAL for name in features]; params={**r30a.HGB_PARAMS,"categorical_features":mask}; parts=[]
        for fold in r30a.ECONOMIC_FOLDS:
            train_all,valid_all,audit=r30a.construct_economic_fold(dataset,fold); direction_parts=[]
            for direction in ("UP","DOWN"):
                train=train_all.loc[train_all["head"].eq(direction)]; valid=valid_all.loc[valid_all["head"].eq(direction)]
                guard_t4_contract(contract_path,contract_sha)
                model=HistGradientBoostingRegressor(**params).fit(train[list(features)],train.T4_DOWNSIDE_SEVERITY); fit_count+=1
                scored=valid.copy(); scored["pred_t4"]=model.predict(valid[list(features)]); predict_count+=1
                scored["baseline_mean_t4"]=float(train.T4_DOWNSIDE_SEVERITY.mean()); scored["baseline_median_t4"]=float(train.T4_DOWNSIDE_SEVERITY.median()); scored["fold"]=fold[0]; scored["arm"]=arm; direction_parts.append(scored)
                model_path=scratch/"models"/f"{arm}_{direction}_{fold[0]}.joblib"; joblib.dump(model,model_path,compress=3)
                model_records.append({"arm":arm,"direction":direction,"fold":fold[0],"model_family":"HistGradientBoostingRegressor","parameters":model.get_params(deep=False),"model_sha256":file_sha256(model_path),"model_path":str(model_path),"T4_contract_sha256":contract_sha,"feature_manifest_sha256":BASELINE_FEATURE_MANIFEST_SHA256 if arm=="ARM_BASELINE" else R30B_FEATURE_MANIFEST_SHA256,"split_contract_sha256":SPLIT_CONTRACT_SHA256,"training_row_count":len(train)})
            fold_scored=pd.concat(direction_parts,ignore_index=True); parts.append(fold_scored); fm=t4_metrics(fold_scored); fc=risk_cohorts(fold_scored,arm); low=cohort_row(fc,"LOWEST_RISK",20); high=cohort_row(fc,"HIGHEST_RISK",20)
            fold_rows.append({"arm":arm,"fold":fold[0],"train_count":len(train_all),"validation_count":len(fold_scored),"T4_Spearman":fm["Spearman_vs_actual_loss"],"low20_mean_net20":low.mean_net20,"high20_mean_net20":high.mean_net20,"low_high_spread":low.mean_net20-high.mean_net20,"low20_p05_net20":low.p05_net20,"high20_p05_net20":high.p05_net20,"correct_order":bool(low.mean_net20>high.mean_net20)})
        oof=pd.concat(parts,ignore_index=True).sort_values(["decision_timestamp_utc","candidate_id"]).reset_index(drop=True); oof_by_arm[arm]=oof; oof.to_parquet(scratch/f"FAST3_R30C_{arm}_OOF.parquet",index=False)
    guard_t4_contract(contract_path,contract_sha)
    if fit_count!=20 or predict_count!=20: raise R30CStop("STOP_MODEL_BUDGET")
    metric_rows=[]; all_deciles=[]; all_cohorts=[]
    for arm in ARM_ORDER:
        oof=oof_by_arm[arm]; m=t4_metrics(oof); meanb=t4_metrics(oof,"baseline_mean_t4"); medianb=t4_metrics(oof,"baseline_median_t4"); dec=risk_deciles(oof,arm); coh=risk_cohorts(oof,arm); dm=decile_metrics(dec); low=cohort_row(coh,"LOWEST_RISK",20); high=cohort_row(coh,"HIGHEST_RISK",20)
        metric_rows.append({"arm":arm,**m,**{f"mean_naive_{k}":v for k,v in meanb.items()},**{f"median_naive_{k}":v for k,v in medianb.items()},**dm,"unconditional_mean_net20":float(oof.raw_net20.mean()),"low20_mean_net20":low.mean_net20,"low20_p05_net20":low.p05_net20,"high20_mean_net20":high.mean_net20,"high20_p05_net20":high.p05_net20,"low_high_mean_spread":low.mean_net20-high.mean_net20})
        all_deciles.append(dec); all_cohorts.append(coh)
    metrics=pd.DataFrame(metric_rows); deciles=pd.concat(all_deciles,ignore_index=True); cohorts=pd.concat(all_cohorts,ignore_index=True); folds=pd.DataFrame(fold_rows)
    base=metrics.loc[metrics.arm.eq("ARM_BASELINE")].iloc[0]; allm=metrics.loc[metrics.arm.eq("ARM_ALL")].iloc[0]; basec=cohorts.loc[cohorts.arm.eq("ARM_BASELINE")]; allc=cohorts.loc[cohorts.arm.eq("ARM_ALL")]
    base_low20=cohort_row(basec,"LOWEST_RISK",20); all_low20=cohort_row(allc,"LOWEST_RISK",20); base_low10=cohort_row(basec,"LOWEST_RISK",10); all_low10=cohort_row(allc,"LOWEST_RISK",10); base_high20=cohort_row(basec,"HIGHEST_RISK",20); all_high20=cohort_row(allc,"HIGHEST_RISK",20)
    all_folds=folds.loc[folds.arm.eq("ARM_ALL")]; correct=int(all_folds.correct_order.sum()); incorrect=5-correct
    unconditional=float(oof_by_arm["ARM_ALL"].raw_net20.mean())
    all_go=bool(allm.Spearman_vs_actual_loss>0 and allm.decile_actual_loss_spearman>0 and all_low20.mean_net20>unconditional and all_high20.mean_net20<all_low20.mean_net20 and correct>=3)
    strong=bool(allm.Spearman_vs_actual_loss>=.05 and all_low20.mean_net20>0 and all_high20.mean_net20<0 and correct>=3)
    base_folds=folds.loc[folds.arm.eq("ARM_BASELINE")]; base_correct=int(base_folds.correct_order.sum())
    base_go=bool(base.Spearman_vs_actual_loss>0 and base.decile_actual_loss_spearman>0 and base_low20.mean_net20>unconditional and base_high20.mean_net20<base_low20.mean_net20 and base_correct>=3)
    delta_s=float(allm.Spearman_vs_actual_loss-base.Spearman_vs_actual_loss); delta_low=float(all_low20.mean_net20-base_low20.mean_net20); delta_p05=float(all_low20.p05_net20-base_low20.p05_net20); delta_spread=float(allm.low_high_mean_spread-base.low_high_mean_spread)
    if all_go and (delta_s>0 or delta_spread>0): classification="A_DOWNSIDE_RISK_SIGNAL_CONFIRMED_IN_DEVELOPMENT"; decision="DOWNSIDE_RISK_SIGNAL_CONFIRMED_INCREMENTAL"
    elif base_go and (not all_go or (delta_s<=0 and delta_spread<=0)): classification="B_DOWNSIDE_SIGNAL_PRESENT_ONLY_IN_BASELINE_OR_NONINCREMENTAL"; decision="DOWNSIDE_SIGNAL_NONINCREMENTAL_OR_BASELINE_ONLY"
    elif allm.Spearman_vs_actual_loss<=0 and all_high20.mean_net20>=all_low20.mean_net20 and correct<3: classification="E_DOWNSIDE_RISK_NOT_PREDICTABLE_WITH_CURRENT_FEATURES"; decision="DOWNSIDE_RISK_NOT_PREDICTABLE_WITH_CURRENT_FEATURES"
    else: classification="D_WEAK_OR_INCONCLUSIVE_DOWNSIDE_SIGNAL"; decision="WEAK_OR_INCONCLUSIVE_DOWNSIDE_SIGNAL"
    all_oof=oof_by_arm["ARM_ALL"].copy(); all_oof["calendar_year"]=all_oof.decision_timestamp_utc.dt.year
    by_year=grouped_robustness(all_oof,"calendar_year","YEAR"); by_direction=grouped_robustness(all_oof,"head","DIRECTION"); by_symbol=grouped_robustness(all_oof,"action_instrument","SYMBOL")
    direction_status={row.group:("GO" if row.T4_Spearman is not None and row.T4_Spearman>0 and row.correct_order else "NO_GO") for row in by_direction.itertuples()}; easier=max(by_direction.itertuples(),key=lambda row:(row.T4_Spearman if row.T4_Spearman is not None else -999,row.low_high_spread)).group
    t1=pd.read_parquet(R30B_T1_OOF); expected=set(all_oof.candidate_id); t1=t1.loc[t1.candidate_id.isin(expected)].copy()
    if len(t1)!=len(all_oof) or t1.candidate_id.duplicated().any(): raise R30CStop("STOP_T1_DIAGNOSTIC_IDENTITY")
    joined=all_oof[["candidate_id","pred_t4"]].merge(t1[["candidate_id","pred_t1"]],on="candidate_id",validate="one_to_one"); t1_t4_s=safe_spearman(joined.pred_t1,joined.pred_t4)
    top_diag,cell_diag=diagnostic_cell(t1,all_oof)
    dist={"T4_ZERO_RATE":float((dataset.T4_DOWNSIDE_SEVERITY==0).mean()),"T4_POSITIVE_RATE":float((dataset.T4_DOWNSIDE_SEVERITY>0).mean()),"T4_MEAN":float(dataset.T4_DOWNSIDE_SEVERITY.mean()),"T4_MEDIAN":float(dataset.T4_DOWNSIDE_SEVERITY.median()),"T4_P90":float(dataset.T4_DOWNSIDE_SEVERITY.quantile(.90)),"T4_P95":float(dataset.T4_DOWNSIDE_SEVERITY.quantile(.95)),"T4_P99":float(dataset.T4_DOWNSIDE_SEVERITY.quantile(.99)),"T4_MAX":float(dataset.T4_DOWNSIDE_SEVERITY.max())}
    metrics.loc[metrics.arm.eq("ARM_BASELINE")].to_csv(frozen/"FAST3_R30C_BASELINE_METRICS.csv",index=False,lineterminator="\n"); metrics.loc[metrics.arm.eq("ARM_ALL")].to_csv(frozen/"FAST3_R30C_ALL_FEATURE_METRICS.csv",index=False,lineterminator="\n")
    deciles.to_csv(frozen/"FAST3_R30C_RISK_DECILES.csv",index=False,lineterminator="\n"); cohorts.to_csv(frozen/"FAST3_R30C_RISK_COHORTS.csv",index=False,lineterminator="\n"); folds.to_csv(frozen/"FAST3_R30C_FOLD_METRICS.csv",index=False,lineterminator="\n"); by_year.to_csv(frozen/"FAST3_R30C_ROBUSTNESS_BY_YEAR.csv",index=False,lineterminator="\n"); by_direction.to_csv(frozen/"FAST3_R30C_ROBUSTNESS_BY_DIRECTION.csv",index=False,lineterminator="\n"); by_symbol.to_csv(frozen/"FAST3_R30C_ROBUSTNESS_BY_SYMBOL.csv",index=False,lineterminator="\n")
    if classification.startswith("A_"): next_stage="HUMAN_REVIEW_TO_FREEZE_T1_PLUS_T4_RISK_AWARE_ARCHITECTURE; DO_NOT_OPEN_FINAL_CONFIRMATION"
    elif classification.startswith("B_"): next_stage="STOP_29_FEATURE_EXPANSION; REVIEW_BASELINE_DOWNSIDE_SIGNAL_ONLY"
    elif classification.startswith("D_"): next_stage="WEAK_STOP_WITHOUT_TUNING"
    else: next_stage="END_CURRENT_PRICE_TECHNICAL_FEATURE_UNIVERSE; FUTURE_RESEARCH_REQUIRES_NEW_INFORMATION_SOURCES"
    summary={"FAST3_R30C_STATUS":"PASS","FAST3_R30C_CLASSIFICATION":classification,"FAST3_R30C_DECISION":decision,"BRANCH":branch,"START_HEAD":head,"HEAD":head,"T4_TARGET_CONTRACT_SHA256":contract_sha,"T4_TARGET_MUTATION_COUNT":0,"PARENT_TARGET_CONTRACT_SHA256":TARGET_CONTRACT_SHA256,"BASELINE_FEATURE_MANIFEST_SHA256":BASELINE_FEATURE_MANIFEST_SHA256,"R30B_FEATURE_MANIFEST_SHA256":R30B_FEATURE_MANIFEST_SHA256,"SPLIT_CONTRACT_SHA256":SPLIT_CONTRACT_SHA256,"TARGET_ROW_COUNT":len(dataset),"BASELINE_FEATURE_COUNT":14,"ALL_FEATURE_COUNT":29,"FEATURE_DEFINITION_CHANGES":0,"NEW_FEATURE_COUNT":0,"MODEL_FIT_COUNT":fit_count,"MODEL_PREDICT_CALL_COUNT":predict_count,"HYPERPARAMETER_SEARCH_COUNT":0,"FINAL_CONFIRMATION_DATA_USED":False,**dist,
        "BASELINE_T4_MAE":base.MAE,"BASELINE_T4_RMSE":base.RMSE,"BASELINE_T4_SPEARMAN":base.Spearman_vs_actual_loss,"ALL_T4_MAE":allm.MAE,"ALL_T4_RMSE":allm.RMSE,"ALL_T4_SPEARMAN":allm.Spearman_vs_actual_loss,"DELTA_T4_SPEARMAN":delta_s,
        "BASELINE_T4_DECILE_LOSS_SPEARMAN":base.decile_actual_loss_spearman,"ALL_T4_DECILE_LOSS_SPEARMAN":allm.decile_actual_loss_spearman,"BASELINE_T4_DECILE_MEAN_NET20_SPEARMAN":base.decile_mean_net20_spearman,"ALL_T4_DECILE_MEAN_NET20_SPEARMAN":allm.decile_mean_net20_spearman,
        "BASELINE_LOW20_MEAN_NET20":base_low20.mean_net20,"ALL_LOW20_MEAN_NET20":all_low20.mean_net20,"DELTA_LOW20_MEAN_NET20":delta_low,"BASELINE_LOW10_MEAN_NET20":base_low10.mean_net20,"ALL_LOW10_MEAN_NET20":all_low10.mean_net20,"BASELINE_HIGH20_MEAN_NET20":base_high20.mean_net20,"ALL_HIGH20_MEAN_NET20":all_high20.mean_net20,"BASELINE_LOW20_P05_NET20":base_low20.p05_net20,"ALL_LOW20_P05_NET20":all_low20.p05_net20,"DELTA_LOW20_P05_NET20":delta_p05,"ALL_HIGH20_P05_NET20":all_high20.p05_net20,"BASELINE_LOW_HIGH_MEAN_SPREAD":base.low_high_mean_spread,"ALL_LOW_HIGH_MEAN_SPREAD":allm.low_high_mean_spread,"DELTA_LOW_HIGH_SPREAD":delta_spread,
        "CORRECT_ORDER_FOLD_COUNT":correct,"INCORRECT_ORDER_FOLD_COUNT":incorrect,"BASELINE_CORRECT_ORDER_FOLD_COUNT":base_correct,"UP_T4_STATUS":direction_status.get("UP"),"DOWN_T4_STATUS":direction_status.get("DOWN"),"EASIER_DOWNSIDE_DIRECTION":easier,"YEAR_ROBUSTNESS":f"{int(by_year.correct_order.sum())}_OF_{len(by_year)}_YEARS_CORRECT_ORDER","SYMBOL_ROBUSTNESS":f"{int(by_symbol.correct_order.sum())}_OF_{len(by_symbol)}_SYMBOLS_CORRECT_ORDER",
        "R30B_T1_PROBABILITY_VS_T4_RISK_SPEARMAN":t1_t4_s,"T1_TOP20_ACTUAL_LOSS_DIAGNOSTIC":top_diag,"DIAGNOSTIC_ONLY":True,"NOT_A_FROZEN_TRADING_RULE":True,"DIAGNOSTIC_T1_TOP20_LOW50_COUNT":cell_diag["count"],"DIAGNOSTIC_T1_TOP20_LOW50_POSITIVE_RATE":cell_diag["positive_rate"],"DIAGNOSTIC_T1_TOP20_LOW50_MEAN_NET20":cell_diag["mean_net20"],"DIAGNOSTIC_T1_TOP20_LOW50_MEDIAN_NET20":cell_diag["median_net20"],"DIAGNOSTIC_T1_TOP20_LOW50_P05_NET20":cell_diag["p05_net20"],
        "T4_DEVELOPMENT_GATE":"GO" if all_go else "NO_GO","T4_STRONG_DEVELOPMENT_SIGNAL":strong,"CURRENT_FEATURES_DOWNSIDE_INFORMATION_STATUS":"CONFIRMED_DOWNSIDE_INFORMATION" if all_go else "WEAK_OR_INCONCLUSIVE_DOWNSIDE_INFORMATION" if classification.startswith("D_") else "NO_DOWNSIDE_INFORMATION" if classification.startswith("E_") else "BASELINE_ONLY_OR_NONINCREMENTAL_DOWNSIDE_INFORMATION","CURRENT_PRICE_TECHNICAL_FEATURE_SET":"INSUFFICIENT_FOR_ECONOMIC_PAYOFF_AND_LEFT_TAIL_PREDICTION" if classification.startswith("E_") else "NOT_YET_CONFIRMED_FOR_LEFT_TAIL_CONTROL",
        "PRIMARY_RESEARCH_INTERPRETATION":"Current 29 features identify downside severity with qualifying cross-fold ordering." if all_go else "Current 29 features do not establish qualifying, stable downside-severity prediction.","PLAIN_T4_ANSWER":"YES_DEVELOPMENT_SIGNAL" if all_go else "NO_CONFIRMED_DEVELOPMENT_SIGNAL","INCREMENTAL_ANSWER":"INCREMENTAL" if delta_s>0 and delta_spread>0 else "NOT_CONFIRMED_INCREMENTAL","T1_LEFT_TAIL_EXPLANATION":"T4 materially separates the left tail" if all_go else "T4 does not reliably explain or control the T1 left-tail asymmetry","NEW_FACTORS_DOWNSIDE_VS_PAYOFF_ANSWER":"MORE_USEFUL_FOR_DOWNSIDE" if delta_s>0 and all_go else "NO_QUALIFYING_ADVANTAGE_FOR_DOWNSIDE",
        "R29_MODIFIED":False,"R29_ALLOWED_TO_RESUME":False,"OFFICIAL_ADOPTION_ALLOWED":False,"LIVE_TRADING_ALLOWED":False,"NEXT_STAGE":next_stage,"FINAL_CONFIRMATION_RECOMMENDATION":"ELIGIBLE_FOR_HUMAN_REVIEW_BUT_DO_NOT_OPEN" if all_go else "DO_NOT_OPEN_FINAL_UNTOUCHED_CONFIRMATION","FAST3_STORAGE_CONTRACT_R1_STATUS":"PASS","SOURCE_ROOT":str(SOURCE_ROOT),"DATA_ROOT":str(DATA_ROOT),"RESULTS_ROOT":str(RESULTS_ROOT),"CACHE_ROOT":str(CACHE_ROOT),"DATA_ROOT_WRITE_COUNT":0,"LOCAL_RESULTS_CREATED":False,"RESULT_FILES_WRITTEN_TO_GIT_REPO":False,"PRE_EXISTING_UNTRACKED_FILES_PRESERVED":True,"PRE_EXISTING_TRACKED_CHANGES_PRESERVED":True,"NEW_STORAGE_VIOLATION_COUNT":0,"DESTRUCTIVE_GIT_COMMAND_USED":False,"BROAD_GIT_ADD_USED":False,"REPORT_PATH":str(frozen/"FAST3_R30C_REPORT.md"),"SUMMARY_JSON_PATH":str(frozen/"FAST3_R30C_SUMMARY.json"),"T4_CONTRACT_PATH":str(contract_path),"MODEL_IDENTITIES":model_records}
    write_json(frozen/"FAST3_R30C_SUMMARY.json",summary); (frozen/"FAST3_R30C_REPORT.md").write_text(report_text(summary),encoding="utf-8"); write_json(runtime/"FAST3_R30C_RUNTIME_SUMMARY.json",{"status":"PASS","classification":classification,"T4_contract_sha256":contract_sha,"model_fit_count":fit_count,"data_root_write_count":0})
    guard_t4_contract(contract_path,contract_sha)
    print(json.dumps({k:summary[k] for k in ("FAST3_R30C_STATUS","FAST3_R30C_CLASSIFICATION","FAST3_R30C_DECISION","T4_DEVELOPMENT_GATE","REPORT_PATH","SUMMARY_JSON_PATH")},indent=2))


if __name__ == "__main__": main()
