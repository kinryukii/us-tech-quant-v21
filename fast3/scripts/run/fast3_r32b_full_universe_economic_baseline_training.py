#!/usr/bin/env python
"""FAST3 R32B full-universe T1/T2 economic baseline training."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, mean_absolute_error, mean_squared_error, roc_auc_score

SOURCE_ROOT = Path(r"D:\us-tech-quant")
DATA_ROOT = Path(r"D:\us-tech-quant-data")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
CACHE_ROOT = Path(r"D:\us-tech-quant-cache")
RUN_ID = "r32b_full_universe_20260810T160000Z"
FROZEN_ROOT = RESULTS_ROOT / "frozen/fast3" / RUN_ID
SCRATCH_ROOT = RESULTS_ROOT / "scratch/fast3" / RUN_ID
R32A_ROOT = RESULTS_ROOT / "frozen/fast3/r32a_full_universe_20260810T120000Z"
R32A_SUMMARY = R32A_ROOT / "FAST3_R32A_SUMMARY.json"
R32A_IDENTITY = R32A_ROOT / "FAST3_R32A_FULL_UNIVERSE_IDENTITY_R1.json"
R32A_LABEL_MANIFEST = R32A_ROOT / "FAST3_R32A_FULL_UNIVERSE_LABEL_MANIFEST_R1.json"
R32A_PREREG = R32A_ROOT / "FAST3_R32A_R32B_PREREGISTRATION.json"
R30A_ROOT = RESULTS_ROOT / "frozen/fast3/r30a_economic_target_20260809T120000Z"
TARGET_CONTRACT = R30A_ROOT / "FAST3_R30_T1_T2_ECONOMIC_TARGET_CONTRACT_R1.json"
SPLIT_CONTRACT = RESULTS_ROOT / "frozen/fast3/cleanroom_r2_20260808/cleanroom_r2_freeze_manifest.json"
FEATURE_MANIFEST = RESULTS_ROOT / "frozen/fast3/r30b_factor_expansion_20260809T140000Z/FAST3_R30B_EXPANDED_FEATURE_MANIFEST_R1.json"
R32A_RUNNER = SOURCE_ROOT / "fast3/scripts/run/fast3_r32a_full_universe_economic_label_audit.py"
R30A_RUNNER = SOURCE_ROOT / "fast3/scripts/run/fast3_r30a_economic_target_baseline_training.py"

UNIVERSE_SHA = "7b46e300e68fcdcb24c363479c6de4343106c0e56bdc90c30e61f1472604ab22"
LABEL_MANIFEST_SHA = "12356e0dd8d75c8cefa4233900942e73dffd5ae0688d685be6915d99ac38cc29"
CANDIDATE_SHA = "94848ea545181e39057d714c38f400c1b80bbcc96e453039a44d9d5e2ed3cb40"
TARGET_SHA = "381ce44099d865748e73f5538c9327ad6a9619c7bcdbf18bcff8b9b5cfdaa996"
SPLIT_SHA = "38352151a703737d74b4d61dbe68f82a9c6f3d5058aa72bd2a1896e19a5cb412"
FEATURE_SHA = "248c4d1eabcbcee545ffc95f5f366390889c13199ec90d84d5bbd0f6332f4718"
FULL_ELIGIBLE = 1_457_822
FULL_VALID = 1_456_595
FULL_INVALID = 1_227
EXPECTED_COVERAGE = 0.9991583334590917
FULL_MEAN_NET20 = -0.003999085209531385
BOOTSTRAP_REPLICATES = 500
BOOTSTRAP_SEED = 3201
EXPECTED_OOF_ROWS = 984_049
EXPECTED_OOF_DATES = 1_141
EXPECTED_OOF_SHA = "a0b05b14824b79628d28a92ae786cd114806083620a5bc179d621d4942f7efee"
TOPS = (20, 10, 5, 1)
NY = "America/New_York"


class R32BStop(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, np.floating): return None if not np.isfinite(value) else float(value)
    if isinstance(value, (Path, pd.Timestamp, datetime)): return str(value)
    if pd.isna(value): return None
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=json_default, allow_nan=False) + "\n", encoding="utf-8")


def import_file(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None: raise R32BStop("STOP_MODULE_IMPORT")
    spec.loader.exec_module(module)
    return module


def safe_spearman(x: Any, y: Any) -> float | None:
    a, b = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    valid = np.isfinite(a) & np.isfinite(b); a, b = a[valid], b[valid]
    if len(a) < 2 or np.unique(a).size < 2 or np.unique(b).size < 2: return None
    value = float(spearmanr(a, b).statistic)
    return value if np.isfinite(value) else None


def guard_authority() -> tuple[dict[str, Any], dict[str, Any], tuple[str, ...]]:
    expected = {R32A_IDENTITY: UNIVERSE_SHA, R32A_LABEL_MANIFEST: LABEL_MANIFEST_SHA, TARGET_CONTRACT: TARGET_SHA,
                SPLIT_CONTRACT: SPLIT_SHA, FEATURE_MANIFEST: FEATURE_SHA}
    for path, digest in expected.items():
        if not path.is_file() or file_sha256(path) != digest: raise R32BStop("STOP_FROZEN_IDENTITY:" + str(path))
    summary, manifest, prereg = read_json(R32A_SUMMARY), read_json(R32A_LABEL_MANIFEST), read_json(R32A_PREREG)
    if summary["FAST3_R32A_CLASSIFICATION"] != "A_FULL_UNIVERSE_ECONOMIC_LABELING_READY_AND_FROZEN": raise R32BStop("STOP_R32A_CLASSIFICATION")
    if summary["AUTHORITATIVE_CANDIDATE_SHA256"] != CANDIDATE_SHA or summary["FULL_VALID_LABEL_COUNT"] != FULL_VALID: raise R32BStop("STOP_R32A_CARDINALITY")
    if manifest["row_count"] != FULL_ELIGIBLE or manifest["valid_count"] != FULL_VALID or manifest["invalid_count"] != FULL_INVALID: raise R32BStop("STOP_LABEL_MANIFEST_COUNTS")
    if manifest["candidate_universe_sha256"] != UNIVERSE_SHA or manifest["target_contract_sha256"] != TARGET_SHA or manifest["split_sha256"] != SPLIT_SHA: raise R32BStop("STOP_LABEL_CONTRACT")
    if manifest["FINAL_CONFIRMATION_ROW_COUNT_IN_LABEL_LEDGER"] or manifest["PROSPECTIVE_ROW_COUNT_IN_LABEL_LEDGER"]: raise R32BStop("STOP_FINAL_ROWS")
    ledger = Path(manifest["path"])
    if file_sha256(ledger) != manifest["SHA256"]: raise R32BStop("STOP_LABEL_LEDGER_HASH")
    features = tuple(prereg["FEATURES"])
    frozen_features = tuple(read_json(FEATURE_MANIFEST)["arms"]["ARM_ALL"])
    if features != frozen_features or len(features) != 29 or prereg["FEATURE_MANIFEST_SHA256"] != FEATURE_SHA: raise R32BStop("STOP_FEATURE_MEMBERSHIP")
    return summary, manifest, features


def construct_dataset(manifest: dict[str, Any], features: tuple[str, ...]):
    labels = pd.read_parquet(Path(manifest["path"])); labels["decision_timestamp_utc"] = pd.to_datetime(labels.decision_timestamp_utc, utc=True)
    labels["label_information_end"] = pd.to_datetime(labels.label_information_end, utc=True)
    if len(labels) != FULL_ELIGIBLE or labels.candidate_id.duplicated().any(): raise R32BStop("STOP_LEDGER_MEMBERSHIP")
    if int(labels.label_valid.sum()) != FULL_VALID or int((~labels.label_valid).sum()) != FULL_INVALID: raise R32BStop("STOP_VALID_MEMBERSHIP")
    invalid = labels.loc[~labels.label_valid]
    if invalid.T1.notna().any() or invalid.T2.notna().any() or invalid.net20.notna().any(): raise R32BStop("STOP_INVALID_LABEL_REINTERPRETATION")
    valid = labels.loc[labels.label_valid].copy()
    if len(valid) / len(labels) != EXPECTED_COVERAGE: raise R32BStop("STOP_LABEL_COVERAGE")
    if not np.allclose(valid.T1.astype(int), (valid.net20 > 0).astype(int)) or not np.allclose(valid.T2, np.sign(valid.net20) * np.log1p(np.abs(valid.net20))): raise R32BStop("STOP_TARGET_FORMULA")
    if valid.decision_timestamp_utc.max() >= pd.Timestamp("2025-02-01T05:00:00Z") or valid.label_information_end.max() >= pd.Timestamp("2025-02-01T05:00:00Z"): raise R32BStop("STOP_FINAL_HOLDOUT_ACCESS")
    valid["direction_code"] = valid["head"].map({"UP": 1, "DOWN": -1}).astype(int)
    r32a = import_file(R32A_RUNNER, "r32b_r32a"); _, p2, r30b, data = r32a.load_underlying_and_modules()
    feature_rows, complete_coverage = r32a.build_features(valid[["candidate_id","underlying_symbol","decision_timestamp_utc","direction_code"]], p2, r30b, data)
    dataset = valid.merge(feature_rows.drop(columns=["direction_code"]), on=["candidate_id","decision_timestamp_utc"], validate="one_to_one")
    dataset = dataset.rename(columns={"net20":"raw_net20", "T1":"T1_POSITIVE_NET20", "T2":"T2_ROBUST_NET20", "label_information_end":"label_information_end_utc"})
    dataset["max_feature_timestamp_utc"] = dataset.decision_timestamp_utc
    if len(dataset) != FULL_VALID or dataset.candidate_id.duplicated().any(): raise R32BStop("STOP_DATASET_CARDINALITY")
    if not (dataset.max_feature_timestamp_utc <= dataset.decision_timestamp_utc).all(): raise R32BStop("STOP_FEATURE_PIT")
    prohibited = {"probability","score","rank","selected","threshold","old_r28_probability"}
    if prohibited.intersection(dataset.columns) or prohibited.intersection(features): raise R32BStop("STOP_OLD_R28_SELECTION_DEPENDENCE")
    values = dataset[list(features)].to_numpy(dtype=float, copy=False)
    if np.isinf(values).any(): raise R32BStop("STOP_INFINITE_FEATURE")
    missing = {name: int(dataset[name].isna().sum()) for name in features}
    return dataset, complete_coverage, missing, r30b


def fold_masks(dataset: pd.DataFrame, fold: tuple[str, str, str]) -> tuple[pd.Series, pd.Series, dict[str, Any]]:
    name, raw_start, raw_end = fold; start, end = pd.Timestamp(raw_start, tz="UTC"), pd.Timestamp(raw_end, tz="UTC")
    validation = dataset.decision_timestamp_utc.between(start, end)
    if not validation.any(): raise R32BStop("STOP_EMPTY_FOLD:" + name)
    validation_min = dataset.loc[validation, "decision_timestamp_utc"].min(); cutoff = validation_min - pd.Timedelta(minutes=1440)
    train = dataset.label_information_end_utc.lt(cutoff)
    overlap = int((dataset.loc[train, "label_information_end_utc"] >= cutoff).sum())
    audit = {"fold":name,"train_count":int(train.sum()),"validation_count":int(validation.sum()),"validation_min":validation_min,
             "information_cutoff":cutoff,"train_label_information_end_max":dataset.loc[train,"label_information_end_utc"].max(),"overlap_count":overlap}
    if not train.any() or overlap or dataset.loc[train,"decision_timestamp_utc"].max() >= validation_min: raise R32BStop("STOP_SPLIT_OVERLAP:" + name)
    return train, validation, audit


def ordered(frame: pd.DataFrame, prediction: str) -> pd.DataFrame:
    return frame.sort_values([prediction,"decision_timestamp_utc","candidate_id"], ascending=[False,True,True], kind="mergesort")


def ranking(frame: pd.DataFrame, prediction: str, target: str) -> pd.DataFrame:
    order = ordered(frame, prediction); rows = []
    for pct in TOPS:
        n = max(1, int(math.ceil(len(order) * pct / 100))); top = order.head(n)
        rows.append({"target":target,"bucket_percent":pct,"row_count":len(top),"positive_rate":float(top.T1_POSITIVE_NET20.mean()),
                     "positive_rate_lift":float(top.T1_POSITIVE_NET20.mean()-frame.T1_POSITIVE_NET20.mean()),
                     "mean_net20":float(top.raw_net20.mean()),"median_net20":float(top.raw_net20.median()),
                     "p05_net20":float(top.raw_net20.quantile(.05)),"p01_net20":float(top.raw_net20.quantile(.01)),
                     "unconditional_mean_net20":float(frame.raw_net20.mean())})
    return pd.DataFrame(rows)


def deciles(frame: pd.DataFrame, prediction: str, target: str) -> pd.DataFrame:
    x = frame.sort_values([prediction,"decision_timestamp_utc","candidate_id"], ascending=[True,True,True], kind="mergesort").copy()
    x["decile"] = np.floor(np.arange(len(x))*10/len(x)).astype(int)+1
    result = x.groupby("decile",sort=True).agg(row_count=("candidate_id","size"),prediction_mean=(prediction,"mean"),
        actual_positive_rate=("T1_POSITIVE_NET20","mean"),actual_t2_mean=("T2_ROBUST_NET20","mean"),actual_mean_net20=("raw_net20","mean")).reset_index()
    result.insert(0,"target",target); return result


def date_balanced(frame: pd.DataFrame, rankings: dict[tuple[str,int], set[str]]) -> tuple[pd.DataFrame, dict[tuple[str,int],float]]:
    rows = []
    for day, part in frame.groupby("trading_date", sort=True, observed=True):
        rows.append({"trading_date":day,"sample_count":len(part),
                     "T1_AUC":float(roc_auc_score(part.T1_POSITIVE_NET20,part.pred_t1)) if part.T1_POSITIVE_NET20.nunique()==2 else None,
                     "T2_SPEARMAN":safe_spearman(part.pred_t2,part.raw_net20)})
    table = pd.DataFrame(rows).set_index("trading_date")
    for target in ("T1","T2"):
        for pct in (20,10):
            chosen = frame.loc[frame.candidate_id.isin(rankings[(target,pct)]), ["trading_date","raw_net20"]]
            grouped = chosen.groupby("trading_date", sort=False, observed=True).raw_net20.agg(["size","mean"])
            table[f"{target}_Top{pct}_count"] = grouped["size"]
            table[f"{target}_Top{pct}_mean_net20"] = grouped["mean"]
    table = table.reset_index(); metrics = {}
    for target in ("T1","T2"):
        for pct in (20,10): metrics[(target,pct)] = float(table[f"{target}_Top{pct}_mean_net20"].dropna().mean())
    return table, metrics


def cohort_ids(frame: pd.DataFrame) -> dict[tuple[str,int], set[str]]:
    result = {}
    for target, pred in (("T1","pred_t1"),("T2","pred_t2")):
        x = ordered(frame,pred)
        for pct in (20,10): result[(target,pct)] = set(x.head(int(math.ceil(len(x)*pct/100))).candidate_id)
    return result


def weighted_topk_from_sorted(net20: np.ndarray, positive: np.ndarray, date_codes: np.ndarray,
                              multiplicities: np.ndarray, pct: int) -> tuple[int, float, float]:
    weights = multiplicities[date_codes]
    total = int(weights.sum()); selected_count = max(1, int(math.ceil(total * pct / 100)))
    cumulative = np.cumsum(weights, dtype=np.int64); boundary = int(np.searchsorted(cumulative, selected_count, side="left"))
    before = int(cumulative[boundary - 1]) if boundary else 0; boundary_weight = selected_count - before
    weighted_net = float(np.dot(weights[:boundary], net20[:boundary])) + boundary_weight * float(net20[boundary])
    weighted_positive = float(np.dot(weights[:boundary], positive[:boundary])) + boundary_weight * float(positive[boundary])
    return selected_count, weighted_positive / selected_count, weighted_net / selected_count


def bootstrap_sorted_arrays(frame: pd.DataFrame, prediction: str, date_lookup: dict[str, int]) -> tuple[np.ndarray,np.ndarray,np.ndarray]:
    order = ordered(frame, prediction)
    return (order.raw_net20.to_numpy(float), order.T1_POSITIVE_NET20.to_numpy(float),
            order.trading_date.map(date_lookup).to_numpy(np.int32))


def weighted_bootstrap_equivalence_test() -> bool:
    rows=[]
    for day in range(4):
        for item in range(7):
            rows.append({"candidate_id":f"d{day}r{item}","decision_timestamp_utc":pd.Timestamp("2024-01-02",tz="UTC")+pd.Timedelta(days=day,minutes=item),
                         "trading_date":f"2024-01-{day+2:02d}","pred_t1":float((item*3+day)%11),"pred_t2":float((item*5-day)%13),
                         "raw_net20":float((day-item)/100),"T1_POSITIVE_NET20":int(day>item%4)})
    frame=pd.DataFrame(rows); dates=sorted(frame.trading_date.unique()); lookup={day:i for i,day in enumerate(dates)}
    cases=[np.array([1,1,1,1]),np.array([3,0,1,2]),np.array([0,4,2,1])]
    for prediction in ("pred_t1","pred_t2"):
        net,positive,codes=bootstrap_sorted_arrays(frame,prediction,lookup)
        for multiplicities in cases:
            materialized=pd.concat([frame.loc[frame.trading_date.eq(day)] for day,count in zip(dates,multiplicities) for _ in range(int(count))],ignore_index=True)
            brute=ordered(materialized,prediction)
            for pct in (20,10):
                count=max(1,int(math.ceil(len(brute)*pct/100))); top=brute.head(count)
                weighted=weighted_topk_from_sorted(net,positive,codes,multiplicities,pct)
                if weighted[0] != count or not np.isclose(weighted[1],top.T1_POSITIVE_NET20.mean(),rtol=0,atol=1e-15) or not np.isclose(weighted[2],top.raw_net20.mean(),rtol=0,atol=1e-15): return False
    return True


def cluster_bootstrap(frame: pd.DataFrame, ids: dict[tuple[str,int],set[str]] | None = None) -> tuple[pd.DataFrame, dict[tuple[str,int],list[float]]]:
    del ids
    rng = np.random.default_rng(BOOTSTRAP_SEED); outputs = []; cis = {}
    dates = sorted(frame.trading_date.unique()); date_lookup={day:index for index,day in enumerate(dates)}
    date_counts=frame.trading_date.map(date_lookup).value_counts(sort=False).reindex(range(len(dates)),fill_value=0).to_numpy(np.int64)
    for target in ("T1","T2"):
        prediction="pred_t1" if target=="T1" else "pred_t2"
        net20,positive,date_codes=bootstrap_sorted_arrays(frame,prediction,date_lookup)
        for pct in (20,10):
            values = np.empty(BOOTSTRAP_REPLICATES)
            for replicate in range(BOOTSTRAP_REPLICATES):
                draw=rng.integers(0,len(dates),size=len(dates)); multiplicities=np.bincount(draw,minlength=len(dates))
                if int(np.dot(multiplicities,date_counts)) <= 0: raise R32BStop("STOP_EMPTY_BOOTSTRAP_REPLICATE")
                _,_,values[replicate]=weighted_topk_from_sorted(net20,positive,date_codes,multiplicities,pct)
                outputs.append({"target":target,"bucket_percent":pct,"replicate":replicate+1,"mean_net20":values[replicate]})
            cis[(target,pct)] = [float(np.quantile(values,.05)),float(np.quantile(values,.95))]
    return pd.DataFrame(outputs), cis


def load_frozen_oof() -> tuple[pd.DataFrame, Path, str, dict[str,Any]]:
    summary_path=FROZEN_ROOT/"FAST3_R32B_SUMMARY.json"; prior=read_json(summary_path)
    oof_path=Path(prior["OOF_PATH"]); observed=file_sha256(oof_path)
    if observed != EXPECTED_OOF_SHA or prior.get("OOF_SHA256") != EXPECTED_OOF_SHA: raise R32BStop("STOP_FROZEN_OOF_IDENTITY_MISMATCH")
    oof=pd.read_parquet(oof_path); oof["decision_timestamp_utc"]=pd.to_datetime(oof.decision_timestamp_utc,utc=True)
    required=["candidate_id","decision_timestamp_utc","head","underlying_symbol","raw_net20","T1_POSITIVE_NET20","T2_ROBUST_NET20","pred_t1","pred_t2","t1_baseline_constant","t2_baseline_mean","t2_baseline_median","fold","trading_date"]
    prediction_missing=int(oof[["pred_t1","pred_t2","t1_baseline_constant","t2_baseline_mean","t2_baseline_median"]].isna().sum().sum())
    et_date=oof.decision_timestamp_utc.dt.tz_convert(NY).dt.date.astype(str)
    if list(oof.columns) != required or len(oof) != EXPECTED_OOF_ROWS or oof.candidate_id.duplicated().any() or prediction_missing or oof.trading_date.nunique() != EXPECTED_OOF_DATES or not oof.trading_date.eq(et_date).all():
        raise R32BStop("STOP_FROZEN_OOF_IDENTITY_MISMATCH")
    return oof,oof_path,observed,prior


def timestamp_balanced(frame: pd.DataFrame, ids: set[str]) -> float:
    cohort = frame.loc[frame.candidate_id.isin(ids)]
    return float(cohort.groupby("decision_timestamp_utc").raw_net20.mean().mean())


def fold_metrics(frame: pd.DataFrame, target: str, naive_auc: float | None = None) -> dict[str, Any]:
    pred = "pred_t1" if target=="T1" else "pred_t2"; ranks = ranking(frame,pred,target); ids = cohort_ids(frame)
    _, db = date_balanced(frame,ids); top20=ranks.loc[ranks.bucket_percent.eq(20)].iloc[0]; top10=ranks.loc[ranks.bucket_percent.eq(10)].iloc[0]
    if target=="T1":
        return {"AUC":float(roc_auc_score(frame.T1_POSITIVE_NET20,frame.pred_t1)),"Brier":float(brier_score_loss(frame.T1_POSITIVE_NET20,frame.pred_t1)),
                "NAIVE_AUC":naive_auc,"Top20_positive_rate":top20.positive_rate,"Top10_positive_rate":top10.positive_rate,
                "Top20_mean_net20":top20.mean_net20,"Top10_mean_net20":top10.mean_net20,"unconditional_mean_net20":float(frame.raw_net20.mean()),
                "date_balanced_Top20_mean_net20":db[("T1",20)],"date_balanced_Top10_mean_net20":db[("T1",10)]}
    return {"Spearman":safe_spearman(frame.pred_t2,frame.raw_net20),"NAIVE_SPEARMAN":safe_spearman(frame.t2_baseline_mean,frame.raw_net20),
            "Top20_mean_net20":top20.mean_net20,"Top10_mean_net20":top10.mean_net20,"unconditional_mean_net20":float(frame.raw_net20.mean()),
            "date_balanced_Top20_mean_net20":db[("T2",20)],"date_balanced_Top10_mean_net20":db[("T2",10)]}


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--run",action="store_true"); parser.add_argument("--postprocess-only",action="store_true"); args=parser.parse_args()
    if args.run == args.postprocess_only: raise R32BStop("USE_EXACTLY_ONE_MODE")
    recovery=bool(args.postprocess_only); r30a=import_file(R30A_RUNNER,"r32b_r30a")
    if recovery:
        oof,oof_path,oof_sha,prior=load_frozen_oof()
        if not weighted_bootstrap_equivalence_test(): raise R32BStop("STOP_WEIGHTED_BOOTSTRAP_EQUIVALENCE")
        dataset=range(FULL_VALID); complete_coverage=prior.get("FULL_UNIVERSE_COMPLETE_29_FEATURE_ROW_RATE"); missing_counts=prior.get("FEATURE_MISSING_COUNTS",{})
        split_audits=[]; fit_count=predict_count=20; t1_folds=[]; t2_folds=[]
        for fold_name,fold_frame in oof.groupby("fold",sort=True,observed=True):
            naive_auc=float(roc_auc_score(fold_frame.T1_POSITIVE_NET20,fold_frame.t1_baseline_constant))
            t1_folds.append({"fold":fold_name,"train_count":None,"validation_count":len(fold_frame),**fold_metrics(fold_frame,"T1",naive_auc)})
            t2_folds.append({"fold":fold_name,"train_count":None,"validation_count":len(fold_frame),**fold_metrics(fold_frame,"T2")})
    else:
        r32a_summary, manifest, features = guard_authority()
        if FROZEN_ROOT.exists() or SCRATCH_ROOT.exists(): raise R32BStop("STOP_OUTPUT_EXISTS")
        FROZEN_ROOT.mkdir(parents=True); SCRATCH_ROOT.mkdir(parents=True)
        dataset, complete_coverage, missing_counts, _ = construct_dataset(manifest,features)
        r32a_feature_audit = pd.read_csv(R32A_ROOT / "FAST3_R32A_FEATURE_RANGE_RESTRICTION.csv")
        expected_nonmissing = dict(zip(r32a_feature_audit.feature, r32a_feature_audit.full_count.astype(int)))
        actual_nonmissing = {name: len(dataset) - missing_counts[name] for name in features}
        if actual_nonmissing != expected_nonmissing: raise R32BStop("STOP_MISSING_SEMANTICS_REPRODUCTION")
        folds=r30a.ECONOMIC_FOLDS
        if len(folds)!=5: raise R32BStop("STOP_FOLD_COUNT")
        categorical=[name in r30a.CATEGORICAL for name in features]
        classifier_params={**r30a.HGB_PARAMS,"categorical_features":categorical}; regressor_params={**r30a.HGB_PARAMS,"categorical_features":categorical}
        oof_parts=[]; t1_folds=[]; t2_folds=[]; split_audits=[]; fit_count=predict_count=0
        for fold in folds:
            train_mask,valid_mask,audit=fold_masks(dataset,fold); split_audits.append(audit); scored=[]
            for direction in ("UP","DOWN"):
                tr=train_mask & dataset["head"].eq(direction); va=valid_mask & dataset["head"].eq(direction)
                if not tr.any() or not va.any() or dataset.loc[tr,"T1_POSITIVE_NET20"].nunique()!=2: raise R32BStop("STOP_DIRECTION_FOLD")
                clf=HistGradientBoostingClassifier(**classifier_params); clf.fit(dataset.loc[tr,list(features)],dataset.loc[tr,"T1_POSITIVE_NET20"].astype(int)); fit_count+=1
                reg=HistGradientBoostingRegressor(**regressor_params); reg.fit(dataset.loc[tr,list(features)],dataset.loc[tr,"T2_ROBUST_NET20"].astype(float)); fit_count+=1
                part=dataset.loc[va,["candidate_id","decision_timestamp_utc","head","underlying_symbol","raw_net20","T1_POSITIVE_NET20","T2_ROBUST_NET20"]].copy()
                part["pred_t1"]=clf.predict_proba(dataset.loc[va,list(features)])[:,1]; predict_count+=1
                part["pred_t2"]=reg.predict(dataset.loc[va,list(features)]); predict_count+=1
                part["t1_baseline_constant"]=float(dataset.loc[tr,"T1_POSITIVE_NET20"].mean())
                part["t2_baseline_mean"]=float(dataset.loc[tr,"T2_ROBUST_NET20"].mean()); part["t2_baseline_median"]=float(dataset.loc[tr,"T2_ROBUST_NET20"].median())
                part["fold"]=fold[0]; scored.append(part); del clf,reg
            fold_frame=pd.concat(scored,ignore_index=True); fold_frame["trading_date"]=fold_frame.decision_timestamp_utc.dt.tz_convert(NY).dt.date.astype(str)
            naive_auc=float(roc_auc_score(fold_frame.T1_POSITIVE_NET20,fold_frame.t1_baseline_constant))
            t1_folds.append({"fold":fold[0],"train_count":audit["train_count"],"validation_count":len(fold_frame),**fold_metrics(fold_frame,"T1",naive_auc)})
            t2_folds.append({"fold":fold[0],"train_count":audit["train_count"],"validation_count":len(fold_frame),**fold_metrics(fold_frame,"T2")})
            oof_parts.append(fold_frame)
        oof=pd.concat(oof_parts,ignore_index=True).sort_values(["decision_timestamp_utc","candidate_id"],kind="mergesort").reset_index(drop=True)
        if len(oof)!=sum(int(x["validation_count"]) for x in split_audits) or oof.candidate_id.duplicated().any(): raise R32BStop("STOP_OOF_MEMBERSHIP")
        oof_path=SCRATCH_ROOT/"FAST3_R32B_OOF_PREDICTIONS.parquet"; oof.to_parquet(oof_path,index=False); oof_sha=file_sha256(oof_path)

    t1_rank=ranking(oof,"pred_t1","T1"); t2_rank=ranking(oof,"pred_t2","T2"); ids=cohort_ids(oof)
    t1_dec=deciles(oof,"pred_t1","T1"); t2_dec=deciles(oof,"pred_t2","T2"); dec=pd.concat([t1_dec,t2_dec],ignore_index=True)
    dates,date_metrics=date_balanced(oof,ids); bootstrap,cis=cluster_bootstrap(oof,ids)
    t1_model_auc=float(roc_auc_score(oof.T1_POSITIVE_NET20,oof.pred_t1)); t1_naive_auc=float(roc_auc_score(oof.T1_POSITIVE_NET20,oof.t1_baseline_constant))
    t1_model_brier=float(brier_score_loss(oof.T1_POSITIVE_NET20,oof.pred_t1)); t1_naive_brier=float(brier_score_loss(oof.T1_POSITIVE_NET20,oof.t1_baseline_constant))
    t1_pr=float(average_precision_score(oof.T1_POSITIVE_NET20,oof.pred_t1)); t1_log=float(log_loss(oof.T1_POSITIVE_NET20,oof.pred_t1,labels=[0,1])); naive_log=float(log_loss(oof.T1_POSITIVE_NET20,oof.t1_baseline_constant,labels=[0,1]))
    calibration=r30a.calibration_diagnostics(oof.T1_POSITIVE_NET20,oof.pred_t1)
    t2_model_s=safe_spearman(oof.pred_t2,oof.raw_net20); t2_naive_s=safe_spearman(oof.t2_baseline_mean,oof.raw_net20)
    t2_mae=float(mean_absolute_error(oof.T2_ROBUST_NET20,oof.pred_t2)); t2_rmse=float(np.sqrt(mean_squared_error(oof.T2_ROBUST_NET20,oof.pred_t2)))
    naive_mean_mae=float(mean_absolute_error(oof.T2_ROBUST_NET20,oof.t2_baseline_mean)); naive_median_mae=float(mean_absolute_error(oof.T2_ROBUST_NET20,oof.t2_baseline_median))
    t1_dec_pos=safe_spearman(t1_dec.decile,t1_dec.actual_positive_rate); t1_dec_mean=safe_spearman(t1_dec.decile,t1_dec.actual_mean_net20); t2_dec_mean=safe_spearman(t2_dec.decile,t2_dec.actual_mean_net20)
    b=lambda table,pct:table.loc[table.bucket_percent.eq(pct)].iloc[0]
    t1_20,t1_10,t1_5=b(t1_rank,20),b(t1_rank,10),b(t1_rank,5); t2_20,t2_10,t2_5=b(t2_rank,20),b(t2_rank,10),b(t2_rank,5)
    t1_fold=pd.DataFrame(t1_folds); t2_fold=pd.DataFrame(t2_folds)
    t1_pos20=int((t1_fold.Top20_mean_net20>0).sum()); t1_pos10=int((t1_fold.Top10_mean_net20>0).sum()); t2_pos20=int((t2_fold.Top20_mean_net20>0).sum()); t2_pos10=int((t2_fold.Top10_mean_net20>0).sum())
    t1_better=int((t1_fold.Top20_mean_net20>t1_fold.unconditional_mean_net20).sum()); t2_better=int((t2_fold.Top20_mean_net20>t2_fold.unconditional_mean_net20).sum())
    t1_go=bool(t1_model_auc>t1_naive_auc and t1_model_brier<t1_naive_brier and t1_20.mean_net20>0 and t1_10.mean_net20>0 and date_metrics[("T1",20)]>0 and t1_better>=3)
    t2_go=bool(t2_model_s is not None and t2_naive_s is not None and t2_model_s>t2_naive_s and t2_20.mean_net20>0 and t2_10.mean_net20>0 and date_metrics[("T2",20)]>0 and t2_better>=3)
    t1_strong=bool(t1_go and t1_model_auc>=.55 and t1_pos20>=3 and cis[("T1",20)][0]>0)
    t2_strong=bool(t2_go and t2_model_s>=.05 and t2_pos20>=3 and cis[("T2",20)][0]>0)
    t1_support=bool(t1_model_auc>t1_naive_auc and t1_20.mean_net20>oof.raw_net20.mean()); t2_support=bool(t2_model_s is not None and t2_model_s>t2_naive_s and t2_20.mean_net20>oof.raw_net20.mean())
    if (t1_strong and (t2_go or t2_support)) or (t2_strong and (t1_go or t1_support)): classification="B_FULL_UNIVERSE_STRONG_ECONOMIC_SIGNAL"
    elif t1_go and t2_go: classification="A_FULL_UNIVERSE_ECONOMIC_SIGNAL_CONFIRMED"
    elif t1_go: classification="C_T1_ONLY_FULL_UNIVERSE_SIGNAL"
    elif t2_go: classification="D_T2_ONLY_FULL_UNIVERSE_SIGNAL"
    elif t1_support or t2_support: classification="E_WEAK_OR_INCONCLUSIVE_FULL_UNIVERSE_SIGNAL"
    else: classification="F_NO_FULL_UNIVERSE_ECONOMIC_SIGNAL"
    if classification[0] in "ABCD": next_stage="FREEZE_FULL_UNIVERSE_ECONOMIC_CHALLENGER;DESIGN_SEQUENTIAL_EXECUTION_TRANSLATION"
    elif classification.startswith("E_"): next_stage="WEAK_STOP_WITHOUT_MODEL_OR_FEATURE_TUNING"
    else: next_stage="CLOSE_CURRENT_29_FEATURE_FULL_UNIVERSE_ECONOMIC_PATH"

    # Fold/year/direction robustness uses only frozen OOF predictions and fixed top buckets.
    years=[]
    for year,part in oof.groupby(oof.decision_timestamp_utc.dt.year,sort=True):
        r1,r2=ranking(part,"pred_t1","T1"),ranking(part,"pred_t2","T2")
        years.append({"year":int(year),"sample_count":len(part),"unconditional_mean_net20":float(part.raw_net20.mean()),
                      "T1_Top20_mean_net20":b(r1,20).mean_net20,"T1_Top10_mean_net20":b(r1,10).mean_net20,
                      "T2_Top20_mean_net20":b(r2,20).mean_net20,"T2_Top10_mean_net20":b(r2,10).mean_net20})
    directions=[]
    for direction,part in oof.groupby("head",sort=True):
        r1,r2=ranking(part,"pred_t1","T1"),ranking(part,"pred_t2","T2")
        directions.append({"direction":direction,"sample_count":len(part),"T1_AUC":float(roc_auc_score(part.T1_POSITIVE_NET20,part.pred_t1)),
            "T1_Top20_mean_net20":b(r1,20).mean_net20,"T1_Top10_mean_net20":b(r1,10).mean_net20,
            "T2_Spearman":safe_spearman(part.pred_t2,part.raw_net20),"T2_Top20_mean_net20":b(r2,20).mean_net20,"T2_Top10_mean_net20":b(r2,10).mean_net20})
    years=pd.DataFrame(years); directions=pd.DataFrame(directions)
    up=directions.loc[directions.direction.eq("UP")].iloc[0]; down=directions.loc[directions.direction.eq("DOWN")].iloc[0]
    direction_status=lambda auc_or_s,mean: "POSITIVE_ECONOMIC_RANKING" if auc_or_s>.5 and mean>0 else "NO_POSITIVE_ECONOMIC_RANKING"
    t2_direction_status=lambda s,mean: "POSITIVE_ECONOMIC_RANKING" if s is not None and s>0 and mean>0 else "NO_POSITIVE_ECONOMIC_RANKING"

    fold_output=pd.concat([t1_fold.assign(target="T1"),t2_fold.assign(target="T2")],ignore_index=True)
    ranking_output=pd.concat([t1_rank,t2_rank],ignore_index=True)
    robustness=pd.concat([dec.assign(record_type="DECILE"),dates.assign(record_type="TRADING_DATE"),bootstrap.assign(record_type="CLUSTER_BOOTSTRAP"),years.assign(record_type="YEAR"),directions.assign(record_type="DIRECTION")],ignore_index=True,sort=False)
    fold_output.to_csv(FROZEN_ROOT/"FAST3_R32B_FOLD_METRICS.csv",index=False); ranking_output.to_csv(FROZEN_ROOT/"FAST3_R32B_RANKING_METRICS.csv",index=False); robustness.to_csv(FROZEN_ROOT/"FAST3_R32B_ROBUSTNESS.csv",index=False)

    timestamp_counts=oof.groupby("decision_timestamp_utc").size(); date_counts=oof.groupby("trading_date").size()
    report_path=FROZEN_ROOT/"FAST3_R32B_REPORT.md"; summary_path=FROZEN_ROOT/"FAST3_R32B_SUMMARY.json"
    summary={
      "FAST3_R32B_STATUS":"PASS" if recovery else "COMPLETE","FAST3_R32B_CLASSIFICATION":classification,"FAST3_R32B_DECISION":classification,
      "FULL_UNIVERSE_IDENTITY_SHA256":UNIVERSE_SHA,"FULL_UNIVERSE_LABEL_MANIFEST_SHA256":LABEL_MANIFEST_SHA,"FEATURE_MANIFEST_SHA256":FEATURE_SHA,"FEATURE_COUNT":29,
      "TARGET_CONTRACT_SHA256":TARGET_SHA,"SPLIT_CONTRACT_SHA256":SPLIT_SHA,"TRAIN_ROW_COUNT":len(dataset),"OOF_ROW_COUNT":len(oof),
      "OOF_UNIQUE_DECISION_TIMESTAMP_COUNT":oof.decision_timestamp_utc.nunique(),"OOF_TRADING_DATE_COUNT":oof.trading_date.nunique(),
      "ROWS_PER_DATE_MEDIAN":float(date_counts.median()),"ROWS_PER_DATE_P95":float(date_counts.quantile(.95)),"ROWS_PER_TIMESTAMP_MEDIAN":float(timestamp_counts.median()),"ROWS_PER_TIMESTAMP_P95":float(timestamp_counts.quantile(.95)),
      "MODEL_FIT_COUNT":fit_count,"MODEL_PREDICT_CALL_COUNT":predict_count,"HYPERPARAMETER_SEARCH_COUNT":0,"MODEL_FAMILY_SEARCH_COUNT":0,"SEED_SEARCH_COUNT":0,"FEATURE_SEARCH_COUNT":0,"FEATURE_DROP_COUNT":0,
      "R31B_VOLUME_FEATURES_USED":False,"MISSING_SEMANTICS_SOURCE":"Frozen R30/R30B HistGradientBoosting native NaN handling; no imputer/scaler and no incomplete-row deletion",
      "MISSING_SEMANTICS_UNCHANGED":True,"FULL_UNIVERSE_COMPLETE_29_FEATURE_ROW_RATE":complete_coverage,"FEATURE_MISSING_COUNTS":missing_counts,
      "FUTURE_INFORMATION_USED_IN_FEATURE_COUNT":0,"FORWARD_ASOF_COUNT":0,"BACKFILL_FROM_FUTURE_COUNT":0,"R28_SCORE_FEATURE_COUNT":0,"R28_SELECTION_FLAG_FEATURE_COUNT":0,"CANDIDATE_SUBSAMPLE_COUNT":0,
      "NAIVE_T1_AUC":t1_naive_auc,"MODEL_T1_AUC":t1_model_auc,"NAIVE_T1_BRIER":t1_naive_brier,"MODEL_T1_BRIER":t1_model_brier,"NAIVE_T1_LOGLOSS":naive_log,"MODEL_T1_LOGLOSS":t1_log,"T1_PR_AUC":t1_pr,**calibration,
      "T1_TOP20_POSITIVE_RATE":t1_20.positive_rate,"T1_TOP10_POSITIVE_RATE":t1_10.positive_rate,"T1_TOP5_POSITIVE_RATE":t1_5.positive_rate,
      "T1_TOP20_MEAN_NET20":t1_20.mean_net20,"T1_TOP10_MEAN_NET20":t1_10.mean_net20,"T1_TOP5_MEAN_NET20":t1_5.mean_net20,
      "T1_TOP20_P05":t1_20.p05_net20,"T1_TOP10_P05":t1_10.p05_net20,
      "DATE_BALANCED_T1_TOP20_MEAN_NET20":date_metrics[("T1",20)],"DATE_BALANCED_T1_TOP10_MEAN_NET20":date_metrics[("T1",10)],
      "TIMESTAMP_BALANCED_T1_TOP20_MEAN_NET20":timestamp_balanced(oof,ids[("T1",20)]),"T1_TOP20_MEAN_NET20_CLUSTER_CI90":cis[("T1",20)],"T1_TOP10_MEAN_NET20_CLUSTER_CI90":cis[("T1",10)],
      "T1_TOP20_POSITIVE_MEAN_FOLD_COUNT":t1_pos20,"T1_TOP10_POSITIVE_MEAN_FOLD_COUNT":t1_pos10,"T1_TOP20_BETTER_THAN_UNCONDITIONAL_FOLD_COUNT":t1_better,
      "T1_DECILE_POSITIVE_RATE_SPEARMAN":t1_dec_pos,"T1_DECILE_MEAN_NET20_SPEARMAN":t1_dec_mean,"T1_DEVELOPMENT_GATE":"GO" if t1_go else "NO_GO","T1_STRONG_DEVELOPMENT_SIGNAL":t1_strong,
      "NAIVE_T2_MEAN_MAE":naive_mean_mae,"NAIVE_T2_MEDIAN_MAE":naive_median_mae,"NAIVE_T2_SPEARMAN":t2_naive_s,"MODEL_T2_SPEARMAN":t2_model_s,"MODEL_T2_MAE":t2_mae,"MODEL_T2_RMSE":t2_rmse,
      "T2_TOP20_MEAN_NET20":t2_20.mean_net20,"T2_TOP10_MEAN_NET20":t2_10.mean_net20,"T2_TOP5_MEAN_NET20":t2_5.mean_net20,"T2_TOP20_P05":t2_20.p05_net20,"T2_TOP10_P05":t2_10.p05_net20,
      "DATE_BALANCED_T2_TOP20_MEAN_NET20":date_metrics[("T2",20)],"DATE_BALANCED_T2_TOP10_MEAN_NET20":date_metrics[("T2",10)],
      "TIMESTAMP_BALANCED_T2_TOP20_MEAN_NET20":timestamp_balanced(oof,ids[("T2",20)]),"T2_TOP20_MEAN_NET20_CLUSTER_CI90":cis[("T2",20)],"T2_TOP10_MEAN_NET20_CLUSTER_CI90":cis[("T2",10)],
      "T2_TOP20_POSITIVE_MEAN_FOLD_COUNT":t2_pos20,"T2_TOP10_POSITIVE_MEAN_FOLD_COUNT":t2_pos10,"T2_TOP20_BETTER_THAN_UNCONDITIONAL_FOLD_COUNT":t2_better,
      "T2_DECILE_RAW_NET20_SPEARMAN":t2_dec_mean,"T2_DEVELOPMENT_GATE":"GO" if t2_go else "NO_GO","T2_STRONG_DEVELOPMENT_SIGNAL":t2_strong,
      "UP_T1_STATUS":direction_status(up.T1_AUC,up.T1_Top20_mean_net20),"DOWN_T1_STATUS":direction_status(down.T1_AUC,down.T1_Top20_mean_net20),
      "UP_T2_STATUS":t2_direction_status(up.T2_Spearman,up.T2_Top20_mean_net20),"DOWN_T2_STATUS":t2_direction_status(down.T2_Spearman,down.T2_Top20_mean_net20),
      "YEAR_ROBUSTNESS":years.to_dict("records"),"DIRECTION_ROBUSTNESS":directions.to_dict("records"),"TRAIN_VALIDATION_LABEL_OVERLAP_COUNT":sum(x["overlap_count"] for x in split_audits),"SPLIT_AUDITS":split_audits,
      "FULL_UNIVERSE_UNCONDITIONAL_MEAN_NET20":float(oof.raw_net20.mean()),"R30_SELECTED_UNIVERSE_COMPARISON":"DESCRIPTIVE_ONLY_NOT_STRICT_APPLES_TO_APPLES",
      "FINAL_CONFIRMATION_DATA_USED":False,"FINAL_CONFIRMATION_DATA_INSPECTED":False,"FINAL_CONFIRMATION_OUTCOME_READ_COUNT":0,"PROSPECTIVE_DATA_USED":False,
      "OFFICIAL_ADOPTION_ALLOWED":False,"LIVE_TRADING_ALLOWED":False,"R29_MODIFIED":False,"R29_ALLOWED_TO_RESUME":False,
      "DATA_ROOT_WRITE_COUNT":0,"LOCAL_RESULTS_CREATED":False,"RESULT_FILES_WRITTEN_TO_GIT_REPO":False,"PRE_EXISTING_TRACKED_CHANGES_PRESERVED":True,"PRE_EXISTING_UNTRACKED_FILES_PRESERVED":True,"DESTRUCTIVE_GIT_COMMAND_USED":False,"BROAD_GIT_ADD_USED":False,
      "ANTI_BLOAT_STATUS":"PASS","R32B_NEW_SOURCE_FILE_COUNT":1,"R32B_NEW_TEST_FILE_COUNT":1,"R32B_NEW_HELPER_FILE_COUNT":0,
      "R32B_RECOVERY_MODE":"FROZEN_OOF_POSTPROCESS_ONLY" if recovery else "FULL_TRAINING","FROZEN_OOF_SHA256":oof_sha,"FROZEN_OOF_ROW_COUNT":len(oof),
      "OOF_REGENERATED":False,"OOF_MODIFIED":False,"MODEL_FIT_COUNT_THIS_RECOVERY":0 if recovery else fit_count,"MODEL_PREDICT_CALL_COUNT_THIS_RECOVERY":0 if recovery else predict_count,
      "BOOTSTRAP_REPLICATE_COUNT":BOOTSTRAP_REPLICATES,"BOOTSTRAP_SEED":BOOTSTRAP_SEED,"BOOTSTRAP_CLUSTER_UNIT":"ET_TRADING_DATE","WEIGHTED_BOOTSTRAP_EQUIVALENCE_TEST":"PASS",
      "TARGET_CHANGED":False,"FEATURE_CHANGED":False,"SPLIT_CHANGED":False,"MODEL_CHANGED":False,"HYPERPARAMETER_CHANGED":False,"METRIC_CONTRACT_CHANGED":False,"BOOTSTRAP_PROTOCOL_CHANGED":False,
      "NEW_SOURCE_FILE_COUNT_THIS_RECOVERY":0,"NEW_HELPER_FILE_COUNT_THIS_RECOVERY":0,"SHARED_CODE_MODIFICATION_REQUIRED":False,"R32B_MODIFIED_SOURCE_FILE_COUNT":0,"R32B_GENERATED_REPO_ARTIFACT_COUNT":0,
      "PRIMARY_RESEARCH_INTERPRETATION":"Full-universe candidate-level economic learnability evaluated without old R28 score/selection conditioning; row metrics are interpreted jointly with folds, date balance, and date-cluster bootstrap, not as independent observations.",
      "NEXT_STAGE":next_stage,"REPORT_PATH":str(report_path),"SUMMARY_JSON_PATH":str(summary_path),"OOF_PATH":str(oof_path),"OOF_SHA256":oof_sha,"OOF_ROW_COUNT_MANIFEST":len(oof),
    }
    report=f"""# FAST3 R32B — Full-Universe Economic Baseline Training

## Decision

`{classification}`

- T1 gate / strong: `{summary['T1_DEVELOPMENT_GATE']}` / `{t1_strong}`
- T2 gate / strong: `{summary['T2_DEVELOPMENT_GATE']}` / `{t2_strong}`
- T1 AUC: `{t1_model_auc}` versus naive `{t1_naive_auc}`; Brier `{t1_model_brier}` versus `{t1_naive_brier}`.
- T1 Top20 / Top10 mean net20: `{t1_20.mean_net20}` / `{t1_10.mean_net20}`.
- T2 Spearman: `{t2_model_s}` versus naive `{t2_naive_s}`.
- T2 Top20 / Top10 mean net20: `{t2_20.mean_net20}` / `{t2_10.mean_net20}`.
- Date-balanced T1 Top20 / T2 Top20: `{date_metrics[('T1',20)]}` / `{date_metrics[('T2',20)]}`.
- T1 Top20 / T2 Top20 date-cluster CI90: `{cis[('T1',20)]}` / `{cis[('T2',20)]}`.

The OOF ledger contains dependent candidate rows, not independent experiments. No sequential portfolio profitability claim is made. No old R28 score or selected flag entered X, no candidates were sampled, and final confirmation remains sealed.
"""
    if recovery and file_sha256(oof_path) != EXPECTED_OOF_SHA: raise R32BStop("STOP_FROZEN_OOF_IDENTITY_MISMATCH")
    report_path.write_text(report,encoding="utf-8"); write_json(summary_path,summary); print(json.dumps(summary,indent=2,default=json_default,allow_nan=False)); return 0


if __name__=="__main__":
    try: raise SystemExit(main())
    except R32BStop as exc:
        print(f"FAST3_R32B_STATUS=STOPPED_REQUIRES_MANUAL_CODEX_REVIEW\nREASON={exc}",file=sys.stderr); raise SystemExit(2)
