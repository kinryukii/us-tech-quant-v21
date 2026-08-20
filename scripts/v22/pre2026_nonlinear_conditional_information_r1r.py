"""R1R event-level quintile evaluation; reuses R1 source and fit contracts unchanged."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
R1_PATH = HERE / "pre2026_nonlinear_conditional_information_r1.py"
R1_RESULTS = Path(r"D:\us-tech-quant-results\PRE2026_NONLINEAR_CONDITIONAL_INFORMATION_R1")
RESULTS = Path(r"D:\us-tech-quant-results\PRE2026_NONLINEAR_CONDITIONAL_INFORMATION_R1R")
R1_PREREG = R1_RESULTS / "pre2026_nonlinear_r1_preregistration.json"
ABCDE_FREEZE = Path(r"D:\us-tech-quant\config\v21\abcde_compact_v1_freeze_r1.json")
R1_PREREG_SHA = "51833cf8a5fec2957df116bd668aa458c3887a6c08d85d9e8c1071581539eebe"

spec = importlib.util.spec_from_file_location("pre2026_r1_reuse", R1_PATH)
r1 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(r1)


class Stop(RuntimeError): pass


def sha(path: Path) -> str: return r1.sha(path)


def event_buckets(part: pd.DataFrame, prediction: str) -> pd.DataFrame:
    """Deterministic fold-local ranking; intentionally has no signal-date grouping."""
    out = part.sort_values([prediction, "sample_id"], kind="stable").copy()
    n = len(out); position = np.arange(n)
    out["event_rank_strength"] = position / max(n - 1, 1)
    out["quintile"] = np.minimum((position * 5 // n) + 1, 5).astype(int)
    return out.sort_index()


def tail(values: pd.Series) -> dict[str, float]:
    def cvar(q: float) -> float:
        threshold = values.quantile(q)
        return float(values[values <= threshold].mean())
    return {"p05": float(values.quantile(.05)), "cvar05": cvar(.05), "p10": float(values.quantile(.10)), "cvar10": cvar(.10), "worst": float(values.min())}


def quintile_metrics(part: pd.DataFrame, model: str) -> tuple[dict[str, float], pd.DataFrame]:
    rank, bucket = f"{model}_event_rank_strength", f"{model}_quintile"
    rows = []
    for q, group in part.groupby(bucket, sort=True):
        pos, neg = group.loc[group.target > 0, "target"].sum(), -group.loc[group.target < 0, "target"].sum()
        rows.append({"model_id": model, "quintile": int(q), "row_count": len(group), "mean_target": float(group.target.mean()), "median_target": float(group.target.median()), "positive_rate": float((group.target > 0).mean()), "profit_factor": float(pos / neg) if neg > 0 else None})
    table = pd.DataFrame(rows).set_index("quintile")
    q1, q5 = part[part[bucket] == 1], part[part[bucket] == 5]
    means = table["mean_target"]
    metrics = {"oof_rank_spearman": float(part[rank].corr(part.target, method="spearman")), "q5_mean": float(q5.target.mean()), "q5_median": float(q5.target.median()), "q1_mean": float(q1.target.mean()), "q1_median": float(q1.target.median()), "q5_q1_mean": float(q5.target.mean()-q1.target.mean()), "q5_q1_median": float(q5.target.median()-q1.target.median()), "quintile_monotonic_spearman": float(pd.Series(means.index, index=means.index).corr(means, method="spearman")), **{f"q5_{k}": v for k,v in tail(q5.target).items()}}
    return metrics, table.reset_index()


def classify(ridge: dict[str, float], hgb: dict[str, float], fold: pd.DataFrame) -> str:
    better_s = int((fold.hgb_spearman > fold.ridge_spearman).sum())
    positive = int((fold.hgb_q5_q1_mean > 0).sum())
    better_q = int((fold.hgb_q5_q1_mean > fold.ridge_q5_q1_mean).sum())
    a = hgb["oof_rank_spearman"] > 0 and hgb["oof_rank_spearman"]-ridge["oof_rank_spearman"] >= .01 and better_s >= 4 and positive >= 4 and better_q >= 4 and hgb["q5_q1_mean"] > 0 and hgb["q5_q1_mean"] > ridge["q5_q1_mean"] and hgb["q5_mean"] > ridge["q5_mean"] and hgb["q5_median"] >= ridge["q5_median"] and hgb["q5_cvar10"] >= ridge["q5_cvar10"]
    if a: return "A_CONFIRMED_PRE2026_EVENT_LEVEL_NONLINEAR_CONDITIONAL_INFORMATION"
    if hgb["oof_rank_spearman"] > ridge["oof_rank_spearman"] and positive >= 3 and hgb["q5_q1_mean"] > ridge["q5_q1_mean"]: return "B_PARTIAL_OR_UNSTABLE_PRE2026_EVENT_LEVEL_NONLINEAR_INCREMENT"
    return "C_CURRENT_INFORMATION_SET_EVENT_LEVEL_NONLINEAR_EDGE_NOT_CONFIRMED"


def source_manifest(hashes: dict[str, str]) -> dict[str, object]:
    return {name: {"path": str(path), "sha256_before": hashes[name], "sha256_after": sha(path), "purpose": purpose} for name, (path, purpose) in r1.source_paths().items()} | {"r1_preregistration": {"path": str(R1_PREREG), "sha256_before": hashes["r1_preregistration"], "sha256_after": sha(R1_PREREG), "purpose": "frozen parent model configuration only"}, "abcde_freeze_manifest": {"path": str(ABCDE_FREEZE), "sha256_before": hashes["abcde_freeze_manifest"], "sha256_after": sha(ABCDE_FREEZE), "purpose": "frozen benchmark provenance only"}}


def preflight() -> tuple[dict[str, str], list[str], list[dict[str, object]], dict[str, object]]:
    if RESULTS.exists(): raise Stop("STOP_R1R_RESULTS_ROOT_ALREADY_EXISTS")
    target, base_hashes, features, folds = r1.preflight()
    if not R1_PREREG.is_file() or not ABCDE_FREEZE.is_file(): raise Stop("STOP_R1R_REQUIRED_PARENT_OR_FREEZE_MANIFEST_MISSING")
    parent = json.loads(R1_PREREG.read_text(encoding="utf-8"))
    if sha(R1_PREREG) != R1_PREREG_SHA or parent.get("models") != {"RIDGE_FIXED_R1": r1.RIDGE_CONFIG, "HGB_SHALLOW_FIXED_R1": r1.HGB_CONFIG}: raise Stop("STOP_R1R_PARENT_PREREGISTRATION_OR_MODEL_CONFIG_MISMATCH")
    hashes = base_hashes | {"r1_preregistration": sha(R1_PREREG), "abcde_freeze_manifest": sha(ABCDE_FREEZE)}
    prereg = {"experiment_id": "PRE2026_NONLINEAR_CONDITIONAL_INFORMATION_R1R", "status": "FROZEN_BEFORE_TARGET_READ_AND_MODEL_FIT", "parent_r1_preregistration_sha256": hashes["r1_preregistration"], "parent_r1_status": "STOP", "parent_r1_stop_reason": "AUTHORITATIVE_PRE2026_MATRIX_LACKS_CROSS_SECTIONAL_SIGNAL_DATE", "repair_scope": "EVENT_LEVEL_EVALUATION_GEOMETRY_ONLY", "target_contract_id": r1.TARGET_ID, "target_contract_sha256": hashes["target_contract"], "target_name": r1.TARGET_NAME, "target_max_forward_horizon_minutes": 60, "feature_set_id": r1.FEATURE_ID, "feature_schema_sha256": parent["feature_schema_sha256"], "feature_count": len(features), "training_cutoff": "2025-12-31", "target_end_cutoff": "2026-01-01T00:00:00Z", "fold_source": "REUSED_AUTHORITATIVE", "fold_contract": folds, "purge_rule": "target_end_timestamp < validation_start", "models": parent["models"], "event_evaluation": {"same_day_cross_sectional_evaluation_used": False, "quantile_count": 5, "rank": "validation-fold prediction ascending, stable sample_id secondary tie-break", "q1": "lowest predicted 20%", "q5": "highest predicted 20%"}, "classification": {"A": "all A1-A10 from R1R prompt", "B": "strict rank-Spearman gain + >=3 positive HGB Q5-Q1 folds + pooled spread gain", "C": "otherwise"}, "source_sha256": hashes, "holdout_2026_read_count": 0, "r1_partial_outcome_artifact_read_count": 0}
    return hashes, features, folds, prereg


def run() -> dict[str, object]:
    hashes, features, folds, prereg = preflight()
    r1.write_json(RESULTS / "pre2026_nonlinear_r1r_preregistration.json", prereg)
    frame, excluded = r1.load_frame(features)
    if frame.sample_id.duplicated().any() or frame.signal_date.nunique() != len(frame): raise Stop("STOP_R1R_EVENT_SAMPLE_IDENTITY_FAILURE")
    fit_rows, predictions = [], []
    for f in folds:
        start = pd.Timestamp(f["validation_start"]); valid = frame[frame.validation_slice == f["validation_block"]].copy(); train0 = frame[frame.validation_slice.isin(f["train_blocks"])].copy(); train = r1.purge_train(train0, start)
        if train.empty or valid.empty or not (train.signal_date < valid.signal_date.min()).all() or not (train.target_end_timestamp < start).all(): raise Stop("STOP_R1R_TEMPORAL_PURGE_FAILURE")
        ridge = r1.Pipeline([("imputer", r1.SimpleImputer(strategy="median")), ("scaler", r1.StandardScaler()), ("model", r1.Ridge(**r1.RIDGE_CONFIG))]); hgb = r1.Pipeline([("imputer", r1.SimpleImputer(strategy="median")), ("model", r1.HistGradientBoostingRegressor(**r1.HGB_CONFIG))])
        valid["ridge_prediction"] = ridge.fit(train[features], train.target).predict(valid[features]); valid["hgb_prediction"] = hgb.fit(train[features], train.target).predict(valid[features]); valid["fold_id"] = f["fold_id"]
        for model in ("ridge", "hgb"):
            ranked = event_buckets(valid, f"{model}_prediction"); valid[f"{model}_event_rank_strength"] = ranked.event_rank_strength; valid[f"{model}_quintile"] = ranked.quintile
        rm, _ = quintile_metrics(valid, "ridge"); hm, _ = quintile_metrics(valid, "hgb")
        fit_rows.append({"fold_id": f["fold_id"], "train_row_count_before_purge": len(train0), "purged_row_count": len(train0)-len(train), "train_row_count_after_purge": len(train), "train_signal_min": train.signal_date.min(), "train_signal_max": train.signal_date.max(), "train_target_end_max": train.target_end_timestamp.max(), "validation_signal_min": valid.signal_date.min(), "validation_signal_max": valid.signal_date.max(), "ridge_spearman": r1.spearman(valid, "ridge_prediction"), "hgb_spearman": r1.spearman(valid, "hgb_prediction"), **{f"ridge_{k}": v for k,v in rm.items() if k != "oof_rank_spearman"}, **{f"hgb_{k}": v for k,v in hm.items() if k != "oof_rank_spearman"}})
        predictions.append(valid[["sample_id", "signal_date", "ticker", "direction", "fold_id", "target", "target_end_timestamp", "ridge_prediction", "hgb_prediction", "ridge_event_rank_strength", "hgb_event_rank_strength", "ridge_quintile", "hgb_quintile"]])
    oof = pd.concat(predictions, ignore_index=True); fold = pd.DataFrame(fit_rows)
    if oof.sample_id.duplicated().any(): raise Stop("STOP_R1R_OOF_SELF_TRAIN_LEAKAGE")
    ridge, ridge_q = quintile_metrics(oof, "ridge"); hgb, hgb_q = quintile_metrics(oof, "hgb"); classification = classify(ridge, hgb, fold)
    manifest = source_manifest(hashes)
    if any(v["sha256_before"] != v["sha256_after"] for v in manifest.values()): raise Stop("STOP_R1R_SOURCE_MUTATION")
    counts = {"hgb_spearman_beats_ridge_fold_count": int((fold.hgb_spearman > fold.ridge_spearman).sum()), "hgb_positive_q5_q1_fold_count": int((fold.hgb_q5_q1_mean > 0).sum()), "hgb_q5_q1_beats_ridge_fold_count": int((fold.hgb_q5_q1_mean > fold.ridge_q5_q1_mean).sum())}
    audit = {"event_level_data_geometry_status": "PASS", "pre2026_eligible_row_count": len(frame), "unique_signal_timestamp_count": int(frame.signal_date.nunique()), "max_samples_per_signal_date": 1, "train_signal_timestamp_min": fold.train_signal_min.min(), "train_signal_timestamp_max": fold.train_signal_max.max(), "train_target_end_max": fold.train_target_end_max.max(), **excluded, "model_fit_with_2026_signal_count": 0, "model_fit_with_2026_target_observation_count": 0, "preprocessing_leakage_count": 0, "oof_self_train_leakage_count": 0}
    decision = {"A_CONFIRMED_PRE2026_EVENT_LEVEL_NONLINEAR_CONDITIONAL_INFORMATION": "PRE2026_EVENT_LEVEL_NONLINEAR_CONDITIONAL_INFORMATION_CONFIRMED_FREEZE_BEFORE_2026_HOLDOUT", "B_PARTIAL_OR_UNSTABLE_PRE2026_EVENT_LEVEL_NONLINEAR_INCREMENT": "PARTIAL_PRE2026_EVENT_LEVEL_NONLINEAR_INCREMENT_REQUIRE_FROZEN_CONFIRMATION_NO_TUNING", "C_CURRENT_INFORMATION_SET_EVENT_LEVEL_NONLINEAR_EDGE_NOT_CONFIRMED": "CURRENT_INFORMATION_SET_EVENT_LEVEL_NONLINEAR_EDGE_NOT_CONFIRMED_STOP_MODEL_TUNING"}[classification]
    summary = {"status": "PASS", "classification": classification, "decision": decision, "target_contract_id": r1.TARGET_ID, "target_contract_sha256": hashes["target_contract"], "target_name": r1.TARGET_NAME, "target_max_forward_horizon": 60, "feature_set_id": r1.FEATURE_ID, "feature_schema_sha256": prereg["feature_schema_sha256"], "feature_count": len(features), "pit_audit_status": "PASS_R28_DECISION_TIME_FEATURE_RECONSTRUCTION", "oof_fold_count": 5, "fold_contract_change_status": "UNCHANGED_FROM_R1", "purge_status": "PASS", "ridge": ridge, "hgb": hgb, "delta_oof_rank_spearman": hgb["oof_rank_spearman"]-ridge["oof_rank_spearman"], "delta_q5_mean": hgb["q5_mean"]-ridge["q5_mean"], "delta_q5_q1_mean": hgb["q5_q1_mean"]-ridge["q5_q1_mean"], **counts, **audit, "model_fit_count": 10, "model_predict_call_count": 10, "source_mutation_status": "PASS", "r1_partial_outcome_artifact_read_count": 0, "holdout_2026_read_count": 0, "persisted_model_binary_count": 0}
    r1.write_json(RESULTS / "source_manifest.json", manifest); r1.write_json(RESULTS / "eligibility_audit.json", audit); r1.write_json(RESULTS / "fold_contract.json", {"fold_source": "REUSED_AUTHORITATIVE", "folds": folds}); r1.write_json(RESULTS / "model_configs.json", prereg["models"]); oof.to_parquet(RESULTS / "oof_predictions.parquet", index=False); r1.write_csv(fold, RESULTS / "fold_metrics.csv"); r1.write_csv(pd.concat([ridge_q, hgb_q]), RESULTS / "quintile_metrics.csv"); r1.write_json(RESULTS / "aggregate_metrics.json", {"ridge": ridge, "hgb": hgb, "counts": counts}); r1.write_json(RESULTS / "pre2026_nonlinear_r1r_summary.json", summary)
    return summary


def main() -> None:
    try:
        result = run(); print(f"PRE2026_NONLINEAR_R1R_STATUS={result['status']}\nPRE2026_NONLINEAR_R1R_CLASSIFICATION={result['classification']}\nPRE2026_NONLINEAR_R1R_DECISION={result['decision']}\nRESULTS_ROOT={RESULTS}\nSUMMARY_PATH={RESULTS / 'pre2026_nonlinear_r1r_summary.json'}")
    except Stop as exc:
        print(f"PRE2026_NONLINEAR_R1R_STATUS=STOP\nPRE2026_NONLINEAR_R1R_DECISION={exc}"); raise SystemExit(2)


if __name__ == "__main__": main()
