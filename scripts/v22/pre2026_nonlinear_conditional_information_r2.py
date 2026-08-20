"""Single-parameter HGB architecture nondegeneracy repair for pre-2026 R2."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
def load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py"); module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader; spec.loader.exec_module(module); return module
r1 = load("pre2026_nonlinear_conditional_information_r1")
r1r = load("pre2026_nonlinear_conditional_information_r1r")
RESULTS = Path(r"D:\us-tech-quant-results\PRE2026_NONLINEAR_CONDITIONAL_INFORMATION_R2")
R1R_PREREG = Path(r"D:\us-tech-quant-results\PRE2026_NONLINEAR_CONDITIONAL_INFORMATION_R1R\pre2026_nonlinear_r1r_preregistration.json")
R1_PREREG = Path(r"D:\us-tech-quant-results\PRE2026_NONLINEAR_CONDITIONAL_INFORMATION_R1\pre2026_nonlinear_r1_preregistration.json")
ABCDE_FREEZE = Path(r"D:\us-tech-quant\config\v21\abcde_compact_v1_freeze_r1.json")

class Stop(RuntimeError): pass
def sha(path: Path) -> str: return r1.sha(path)
def nonconstant(pred: np.ndarray) -> dict[str, object]:
    return {"prediction_unique_count": int(np.unique(pred).size), "prediction_std": float(np.std(pred)), "prediction_min": float(np.min(pred)), "prediction_max": float(np.max(pred)), "hgb_nonconstant": bool(np.unique(pred).size >= 2 and np.std(pred) > 0)}
def config_diff(old: dict[str, object], new: dict[str, object]) -> dict[str, list[object]]: return {k: [old.get(k), new.get(k)] for k in sorted(set(old)|set(new)) if old.get(k) != new.get(k)}
def architecture_gate(fold: pd.DataFrame) -> bool: return int(fold.hgb_nonconstant.sum()) == 5

def preflight():
    if RESULTS.exists(): raise Stop("STOP_R2_RESULTS_ROOT_ALREADY_EXISTS")
    target, base_hashes, features, folds = r1.preflight()
    if any(not p.is_file() for p in (R1R_PREREG, R1_PREREG, ABCDE_FREEZE)): raise Stop("STOP_R2_PARENT_IDENTITY_SOURCE_MISSING")
    parent = json.loads(R1R_PREREG.read_text(encoding="utf-8"))
    old = parent.get("models", {}).get("HGB_SHALLOW_FIXED_R1")
    if old != r1.HGB_CONFIG: raise Stop("STOP_R2_PARENT_HGB_CONFIG_DRIFT")
    new = dict(old); new["min_samples_leaf"] = 50
    diff = config_diff(old, new)
    if diff != {"min_samples_leaf": [500, 50]}: raise Stop("STOP_FAIL_CLOSED_MULTI_PARAMETER_DRIFT")
    hashes = base_hashes | {"r1r_preregistration": sha(R1R_PREREG), "r1_preregistration": sha(R1_PREREG), "abcde_freeze_manifest": sha(ABCDE_FREEZE)}
    prereg = {"experiment_id": "PRE2026_NONLINEAR_CONDITIONAL_INFORMATION_R2", "status": "FROZEN_BEFORE_TARGET_READ_AND_MODEL_FIT", "parent": "PRE2026_NONLINEAR_CONDITIONAL_INFORMATION_R1R", "parent_r1r_classification": "C_CURRENT_INFORMATION_SET_EVENT_LEVEL_NONLINEAR_EDGE_NOT_CONFIRMED", "repair_scope": "HGB_MIN_SAMPLES_LEAF_ARCHITECTURE_NONDEGENERACY_ONLY", "old_min_samples_leaf": 500, "new_min_samples_leaf": 50, "architecture_feasibility": {"minimum_train_rows": 199, "minimum_binary_split_rows": 100, "rationale": "2*50 < 199; CONFIG_CANDIDATE_COUNT=1"}, "target_contract_id": r1.TARGET_ID, "target_contract_sha256": hashes["target_contract"], "feature_set_id": r1.FEATURE_ID, "feature_schema_sha256": parent["feature_schema_sha256"], "feature_count": len(features), "fold_contract": folds, "purge_rule": "target_end_timestamp < validation_start", "ridge_config": r1.RIDGE_CONFIG, "hgb_config": new, "quantile_count": 5, "same_day_cross_sectional_evaluation_used": False, "classification": "A/B/C unchanged from R1R and gated by 5/5 nonconstant HGB folds", "source_sha256": hashes}
    return base_hashes, hashes, features, folds, new, prereg, diff

def manifest(hashes: dict[str, str]) -> dict[str, object]:
    items = {name: (path, purpose) for name,(path,purpose) in r1.source_paths().items()} | {"r1r_preregistration": (R1R_PREREG, "parent structural identity/config only"), "r1_preregistration": (R1_PREREG, "parent frozen config only"), "abcde_freeze_manifest": (ABCDE_FREEZE, "benchmark provenance only")}
    out = {name: {"path": str(path), "sha256_before": hashes[name], "sha256_after": sha(path), "purpose": purpose} for name,(path,purpose) in items.items()}
    if any(x["sha256_before"] != x["sha256_after"] for x in out.values()): raise Stop("STOP_R2_SOURCE_MUTATION")
    return out

def run():
    _, hashes, features, folds, hgb_config, prereg, diff = preflight()
    r1.write_json(RESULTS / "pre2026_nonlinear_r2_preregistration.json", prereg)
    frame, excluded = r1.load_frame(features); records=[]; predictions=[]
    for f in folds:
        start = pd.Timestamp(f["validation_start"]); valid = frame[frame.validation_slice == f["validation_block"]].copy(); train0 = frame[frame.validation_slice.isin(f["train_blocks"])].copy(); train = r1.purge_train(train0, start)
        if train.empty or valid.empty or not (train.target_end_timestamp < start).all(): raise Stop("STOP_R2_TEMPORAL_PURGE_FAILURE")
        ridge = r1.Pipeline([("imputer", r1.SimpleImputer(strategy="median")), ("scaler", r1.StandardScaler()), ("model", r1.Ridge(**r1.RIDGE_CONFIG))]); hgb = r1.Pipeline([("imputer", r1.SimpleImputer(strategy="median")), ("model", r1.HistGradientBoostingRegressor(**hgb_config))])
        valid["ridge_prediction"] = ridge.fit(train[features], train.target).predict(valid[features]); hpred = hgb.fit(train[features], train.target).predict(valid[features]); valid["hgb_prediction"] = hpred; valid["fold_id"] = f["fold_id"]
        for model in ("ridge", "hgb"):
            ranked = r1r.event_buckets(valid, f"{model}_prediction"); valid[f"{model}_event_rank_strength"] = ranked.event_rank_strength; valid[f"{model}_quintile"] = ranked.quintile
        rm, _ = r1r.quintile_metrics(valid, "ridge"); hm, _ = r1r.quintile_metrics(valid, "hgb"); arch = nonconstant(hpred)
        records.append({"fold_id": f["fold_id"], "train_row_count": len(train), "purged_row_count": len(train0)-len(train), "validation_row_count": len(valid), "train_signal_min": train.signal_date.min(), "train_signal_max": train.signal_date.max(), "train_target_end_max": train.target_end_timestamp.max(), "validation_signal_min": valid.signal_date.min(), "validation_signal_max": valid.signal_date.max(), **arch, "ridge_spearman": r1.spearman(valid,"ridge_prediction"), "hgb_spearman": r1.spearman(valid,"hgb_prediction"), **{f"ridge_{k}":v for k,v in rm.items() if k!="oof_rank_spearman"}, **{f"hgb_{k}":v for k,v in hm.items() if k!="oof_rank_spearman"}})
        predictions.append(valid[["sample_id","signal_date","ticker","direction","fold_id","target","target_end_timestamp","ridge_prediction","hgb_prediction","ridge_event_rank_strength","hgb_event_rank_strength","ridge_quintile","hgb_quintile"]])
    fold = pd.DataFrame(records); oof = pd.concat(predictions,ignore_index=True); arch_audit = fold[["fold_id","train_row_count","validation_row_count","prediction_unique_count","prediction_std","prediction_min","prediction_max","hgb_nonconstant"]]
    r1.write_csv(arch_audit, RESULTS / "architecture_nondegeneracy_audit.csv")
    if not architecture_gate(fold): raise Stop("STOP_HGB_ARCHITECTURE_REPAIR_STILL_DEGENERATE")
    ridge, rq = r1r.quintile_metrics(oof,"ridge"); hgb,hq = r1r.quintile_metrics(oof,"hgb"); classification = r1r.classify(ridge,hgb,fold); sources = manifest(hashes)
    counts={"hgb_nonconstant_prediction_fold_count":5,"hgb_spearman_beats_ridge_fold_count":int((fold.hgb_spearman>fold.ridge_spearman).sum()),"hgb_positive_q5_q1_fold_count":int((fold.hgb_q5_q1_mean>0).sum()),"hgb_q5_q1_beats_ridge_fold_count":int((fold.hgb_q5_q1_mean>fold.ridge_q5_q1_mean).sum())}
    decision={"A_CONFIRMED_PRE2026_EVENT_LEVEL_NONLINEAR_CONDITIONAL_INFORMATION":"PRE2026_EVENT_LEVEL_NONLINEAR_INFORMATION_CONFIRMED_AFTER_ARCHITECTURE_REPAIR_FREEZE_BEFORE_2026_HOLDOUT","B_PARTIAL_OR_UNSTABLE_PRE2026_EVENT_LEVEL_NONLINEAR_INCREMENT":"PARTIAL_PRE2026_NONLINEAR_INCREMENT_AFTER_ARCHITECTURE_REPAIR_NO_TUNING","C_CURRENT_INFORMATION_SET_EVENT_LEVEL_NONLINEAR_EDGE_NOT_CONFIRMED":"CURRENT_14_FEATURE_INFORMATION_SET_NONLINEAR_EDGE_NOT_CONFIRMED_CLOSE_MODEL_COMPLEXITY_SEARCH"}[classification]
    audit={"pre2026_eligible_row_count":len(frame),"oof_fold_count":5,"fold_contract_change_status":"UNCHANGED_FROM_R1R","purge_status":"PASS",**excluded,"model_fit_with_2026_signal_count":0,"model_fit_with_2026_target_observation_count":0,"preprocessing_leakage_count":0,"oof_self_train_leakage_count":0}
    summary={"status":"PASS","classification":classification,"decision":decision,"repair_scope":"HGB_MIN_SAMPLES_LEAF_ARCHITECTURE_NONDEGENERACY_ONLY","old_min_samples_leaf":500,"new_min_samples_leaf":50,"config_candidate_count":1,"hgb_config_diff_from_r1r":diff,"target_contract_id":r1.TARGET_ID,"target_contract_sha256":hashes["target_contract"],"feature_set_id":r1.FEATURE_ID,"feature_schema_sha256":prereg["feature_schema_sha256"],"feature_count":len(features),"ridge":ridge,"hgb":hgb,"delta_oof_rank_spearman":hgb["oof_rank_spearman"]-ridge["oof_rank_spearman"],"delta_q5_mean":hgb["q5_mean"]-ridge["q5_mean"],"delta_q5_q1_mean":hgb["q5_q1_mean"]-ridge["q5_q1_mean"],**counts,**audit,"model_fit_count":10,"model_predict_call_count":10,"source_mutation_status":"PASS","persisted_model_binary_count":0}
    r1.write_json(RESULTS/"source_manifest.json",sources); r1.write_json(RESULTS/"eligibility_audit.json",audit); r1.write_json(RESULTS/"fold_contract.json",{"fold_source":"REUSED_AUTHORITATIVE","folds":folds}); r1.write_json(RESULTS/"model_configs.json",{"RIDGE_FIXED_R1":r1.RIDGE_CONFIG,"HGB_SHALLOW_ARCH_REPAIR_R2":hgb_config}); oof.to_parquet(RESULTS/"oof_predictions.parquet",index=False); r1.write_csv(fold,RESULTS/"fold_metrics.csv"); r1.write_csv(pd.concat([rq,hq]),RESULTS/"quintile_metrics.csv"); r1.write_json(RESULTS/"aggregate_metrics.json",{"ridge":ridge,"hgb":hgb,"counts":counts}); r1.write_json(RESULTS/"pre2026_nonlinear_r2_summary.json",summary)
    return summary

def main():
    try:
        s=run(); print(f"PRE2026_NONLINEAR_R2_STATUS={s['status']}\nPRE2026_NONLINEAR_R2_CLASSIFICATION={s['classification']}\nPRE2026_NONLINEAR_R2_DECISION={s['decision']}\nRESULTS_ROOT={RESULTS}\nSUMMARY_PATH={RESULTS/'pre2026_nonlinear_r2_summary.json'}")
    except Stop as exc: print(f"PRE2026_NONLINEAR_R2_STATUS=STOP\nPRE2026_NONLINEAR_R2_DECISION={exc}"); raise SystemExit(2)
if __name__=="__main__": main()
