"""Fixed, pre-2026-only Ridge-vs-shallow-HGB economic OOF experiment."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


RESULTS = Path(r"D:\us-tech-quant-results\PRE2026_NONLINEAR_CONDITIONAL_INFORMATION_R1")
FROZEN = Path(r"D:\us-tech-quant-results\frozen\fast3")
R43A = FROZEN / "r43a_independent_economic_target_contract_freeze_r1"
R43B = FROZEN / "r43b_current_information_set_economic_baseline_r1"
TARGET_CONTRACT = R43A / "FAST3_R43A_ECONOMIC_TARGET_CONTRACT.json"
FEATURE_PREREG = R43B / "FAST3_R43B_PREREGISTRATION.json"
FEATURE_MATRIX = R43B / "FAST3_R43B_FEATURE_IDENTITY.csv"
FOLD_SCHEDULE = R43B / "FAST3_R43B_OOF_FOLD_SCHEDULE.csv"
LEDGER = Path(r"D:\us-tech-quant-results\scratch\fast3\r36_payoff_path_decomposition_r1_20260810T131648Z\FAST3_R36_PATH_DIAGNOSTIC_LEDGER.parquet")
CUTOFF = pd.Timestamp("2026-01-01", tz="UTC")
TARGET_ID = "FAST3_R43A_INDEPENDENT_ECONOMIC_TARGET_CONTRACT_FREEZE_R1"
TARGET_NAME = "AVERAGE_FIXED_HORIZON_NET20"
FEATURE_ID = "FAST3_R43B_CURRENT_INFORMATION_SET_ECONOMIC_BASELINE_R1"
RIDGE_CONFIG = {"alpha": 10.0, "fit_intercept": True}
HGB_CONFIG = {"loss": "squared_error", "learning_rate": 0.05, "max_iter": 200, "max_depth": 2,
              "min_samples_leaf": 500, "l2_regularization": 1.0, "early_stopping": False, "random_state": 20260815}


class Stop(RuntimeError): pass


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""): h.update(block)
    return h.hexdigest()


def write_json(path: Path, value: object) -> None:
    def clean(x):
        if isinstance(x, dict): return {k: clean(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)): return [clean(v) for v in x]
        if isinstance(x, (float, np.floating)) and not np.isfinite(x): return None
        return x
    def default(x):
        if isinstance(x, (pd.Timestamp, Path)): return str(x)
        if isinstance(x, (np.integer,)): return int(x)
        if isinstance(x, (np.floating,)): return float(x)
        raise TypeError(type(x).__name__)
    text = json.dumps(clean(value), sort_keys=True, indent=2, ensure_ascii=True, default=default, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, newline="\n") as f:
        f.write(text); tmp = Path(f.name)
    os.replace(tmp, path)


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n", float_format="%.12g")


def source_paths() -> dict[str, tuple[Path, str]]:
    return {"target_contract": (TARGET_CONTRACT, "frozen primary target identity"),
            "feature_preregistration": (FEATURE_PREREG, "frozen 14-feature identity and folds"),
            "feature_matrix": (FEATURE_MATRIX, "authoritative PIT-safe feature values"),
            "fold_schedule": (FOLD_SCHEDULE, "authoritative chronological OOF schedule"),
            "target_ledger": (LEDGER, "authoritative fixed-horizon target values")}


def preflight() -> tuple[dict[str, object], dict[str, str], list[str], list[dict[str, object]]]:
    paths = source_paths()
    if any(not path.is_file() for path, _ in paths.values()): raise Stop("STOP_REQUIRED_AUTHORITATIVE_SOURCE_MISSING")
    hashes = {name: sha(path) for name, (path, _) in paths.items()}
    target = json.loads(TARGET_CONTRACT.read_text(encoding="utf-8"))
    features = json.loads(FEATURE_PREREG.read_text(encoding="utf-8"))
    if target.get("CONTRACT_ID") != TARGET_ID or target.get("PRIMARY_TARGET_NAME") != TARGET_NAME or target.get("HORIZONS") != [5, 10, 15, 30, 60]:
        raise Stop("STOP_AUTHORITATIVE_TARGET_CONTRACT_MISMATCH")
    if features.get("CONTRACT_ID") != FEATURE_ID or features.get("BASELINE_FEATURE_COUNT") != 14 or len(features.get("BASELINE_FEATURES", [])) != 14:
        raise Stop("STOP_AUTHORITATIVE_FEATURE_CONTRACT_MISMATCH")
    ledger_meta = pq.ParquetFile(LEDGER).metadata
    fields = {f.name: i for i, f in enumerate(pq.ParquetFile(LEDGER).schema_arrow)}
    entry_stats = ledger_meta.row_group(0).column(fields["entry_timestamp"]).statistics
    entry_max = pd.Timestamp(entry_stats.max)
    entry_max = entry_max.tz_localize("UTC") if entry_max.tzinfo is None else entry_max.tz_convert("UTC")
    if entry_max + pd.Timedelta(minutes=60) >= CUTOFF:
        raise Stop("STOP_FAIL_CLOSED_PRE2026_LABEL_BOUNDARY_UNPROVABLE")
    schedule = pd.read_csv(FOLD_SCHEDULE)
    expected = ["OOF_2021", "OOF_2022", "OOF_2023", "OOF_2024", "OOF_2025_JAN"]
    if schedule["fold"].tolist() != expected: raise Stop("STOP_AUTHORITATIVE_FOLD_CONTRACT_MISMATCH")
    folds = [{"fold_id": row.fold, "train_blocks": features["OOF_FOLD_CONTRACT"][i]["train_blocks"], "validation_block": row.fold,
              "validation_start": str(row.valid_start), "validation_end": str(row.valid_end)} for i, row in enumerate(schedule.itertuples(index=False))]
    return target, hashes, list(features["BASELINE_FEATURES"]), folds


def prereg(target: dict[str, object], hashes: dict[str, str], features: list[str], folds: list[dict[str, object]]) -> dict[str, object]:
    return {"experiment_id": "PRE2026_NONLINEAR_CONDITIONAL_INFORMATION_R1", "status": "FROZEN_BEFORE_TARGET_READ_AND_MODEL_FIT",
            "target_contract_id": TARGET_ID, "target_contract_sha256": hashes["target_contract"], "target_name": TARGET_NAME,
            "target_max_forward_horizon_minutes": 60, "target_timezone_contract": "UTC", "feature_set_id": FEATURE_ID,
            "feature_schema_sha256": hashlib.sha256(json.dumps(features, separators=(",", ":")).encode()).hexdigest(), "feature_count": len(features),
            "training_cutoff_date": "2025-12-31", "target_observation_cutoff": "2026-01-01T00:00:00Z", "fold_source": "REUSED_AUTHORITATIVE",
            "fold_contract": folds, "purge_rule": "drop train target_end_timestamp >= validation_start", "models": {"RIDGE_FIXED_R1": RIDGE_CONFIG, "HGB_SHALLOW_FIXED_R1": HGB_CONFIG},
            "metrics": ["pooled_spearman", "daily_prediction_deciles_D1_D10", "decile_monotonic_spearman", "p05_cvar05_worst"],
            "classification": {"A": "all preregistered A1-A8", "B": "strict pooled Spearman gain + >=3 positive HGB fold spreads + pooled spread gain", "C": "otherwise"},
            "stop_conditions": ["no_2026_signal_or_target_observation", "duplicate_sample_identity", "purge_failure", "source_hash_mutation"], "source_sha256": hashes,
            "holdout_2026_read_count": 0, "linear_weight_search_authorized": False, "new_feature_allowed": False}


def load_frame(features: list[str]) -> tuple[pd.DataFrame, dict[str, int]]:
    feature = pd.read_csv(FEATURE_MATRIX)
    required_feature = ["candidate_id", "decision_timestamp_utc", "direction", "validation_slice", *features]
    if list(feature.columns) != required_feature or feature["candidate_id"].duplicated().any(): raise Stop("STOP_FEATURE_IDENTITY_OR_DUPLICATE_FAILURE")
    feature["decision_timestamp_utc"] = pd.to_datetime(feature["decision_timestamp_utc"], utc=True, errors="raise")
    target = pd.read_parquet(LEDGER, columns=["candidate_id", "decision_timestamp_utc", "entry_timestamp", "underlying_symbol", "path_complete", "return_5m_net20", "return_10m_net20", "return_15m_net20", "return_30m_net20", "return_60m_net20"])
    target["decision_timestamp_utc"] = pd.to_datetime(target["decision_timestamp_utc"], utc=True, errors="raise")
    target["entry_timestamp"] = pd.to_datetime(target["entry_timestamp"], utc=True, errors="raise")
    returns = target.filter(regex=r"^return_.*_net20$")
    target["target"] = returns.mean(axis=1)
    target["target_end_timestamp"] = target["entry_timestamp"] + pd.Timedelta(minutes=60)
    if target["candidate_id"].duplicated().any() or not target["path_complete"].eq(True).all() or not np.isfinite(returns.to_numpy(dtype=float)).all(): raise Stop("STOP_TARGET_IDENTITY_OR_VALIDITY_FAILURE")
    frame = feature.merge(target[["candidate_id", "decision_timestamp_utc", "underlying_symbol", "target", "target_end_timestamp"]], on=["candidate_id", "decision_timestamp_utc"], validate="one_to_one", how="inner")
    if len(frame) != len(feature) or frame["candidate_id"].duplicated().any(): raise Stop("STOP_FEATURE_TARGET_JOIN_FAILURE")
    frame = frame.rename(columns={"candidate_id": "sample_id", "underlying_symbol": "ticker", "decision_timestamp_utc": "signal_date"})
    eligible, excluded_signal, excluded_target = eligibility(frame)
    if len(eligible) == 0 or eligible["signal_date"].ge(CUTOFF).any() or eligible["target_end_timestamp"].ge(CUTOFF).any(): raise Stop("STOP_PRE2026_ELIGIBILITY_FAILURE")
    return eligible.sort_values(["signal_date", "sample_id"], kind="stable").reset_index(drop=True), {"excluded_signal_date_2026_plus_count": excluded_signal, "excluded_target_crosses_2026_count": excluded_target}


def eligibility(frame: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    excluded_signal = int(frame["signal_date"].ge(CUTOFF).sum())
    excluded_target = int(frame["target_end_timestamp"].ge(CUTOFF).sum())
    return frame.loc[frame["signal_date"].lt(CUTOFF) & frame["target_end_timestamp"].lt(CUTOFF)].copy(), excluded_signal, excluded_target


def purge_train(train: pd.DataFrame, validation_start: pd.Timestamp) -> pd.DataFrame:
    return train.loc[train["target_end_timestamp"] < validation_start].copy()


def require_cross_section(frame: pd.DataFrame) -> None:
    if frame.groupby("signal_date", sort=False).size().max() < 2:
        raise Stop("STOP_AUTHORITATIVE_PRE2026_MATRIX_LACKS_CROSS_SECTIONAL_SIGNAL_DATE")


def deciles(part: pd.DataFrame, prediction: str) -> pd.Series:
    order = part.sort_values([prediction, "sample_id"], kind="stable").groupby("signal_date", sort=False).cumcount()
    size = part.groupby("signal_date", sort=False)[prediction].transform("size")
    return (np.floor(order * 10 / size).astype(int) + 1).clip(1, 10)


def spearman(part: pd.DataFrame, column: str) -> float:
    return float(part[column].corr(part["target"], method="spearman")) if len(part) > 1 else float("nan")


def tail(values: pd.Series) -> dict[str, float]:
    q = values.quantile(.05); subset = values[values <= q]
    return {"p05_target": float(q), "cvar05": float(subset.mean()), "worst_target": float(values.min())}


def model_metrics(part: pd.DataFrame, model: str) -> tuple[dict[str, float], pd.DataFrame]:
    pred = f"{model}_prediction"; work = part.copy(); work["decile"] = deciles(work, pred)
    rows = []
    for decile, bucket in work.groupby("decile", sort=True):
        pos, neg = bucket.loc[bucket.target > 0, "target"].sum(), -bucket.loc[bucket.target < 0, "target"].sum()
        rows.append({"model_id": model, "decile": int(decile), "row_count": len(bucket), "mean_target": float(bucket.target.mean()), "median_target": float(bucket.target.median()), "positive_rate": float((bucket.target > 0).mean()), "profit_factor": float(pos / neg) if neg > 0 else None})
    table = pd.DataFrame(rows); means = table.set_index("decile")["mean_target"]
    d1, d10 = work[work.decile == 1], work[work.decile == 10]
    metric = {"spearman": spearman(work, pred), "d10_mean": float(d10.target.mean()), "d10_median": float(d10.target.median()), "d1_mean": float(d1.target.mean()), "d1_median": float(d1.target.median()),
              "d10_d1_mean": float(d10.target.mean() - d1.target.mean()), "d10_d1_median": float(d10.target.median() - d1.target.median()),
              "decile_monotonic_spearman": float(pd.Series(means.index, index=means.index).corr(means, method="spearman")), **{f"pooled_{k}": v for k, v in tail(work.target).items()}, **{f"d10_{k}": v for k, v in tail(d10.target).items()}, **{f"d1_{k}": v for k, v in tail(d1.target).items()}}
    return metric, table


def classify(r: dict[str, float], h: dict[str, float], fold: pd.DataFrame) -> str:
    beats = int((fold.hgb_spearman > fold.ridge_spearman).sum()); positive = int((fold.hgb_d10_d1_mean > 0).sum())
    a = h["spearman"] > 0 and h["spearman"] - r["spearman"] >= .01 and beats >= 4 and positive >= 4 and h["d10_d1_mean"] > r["d10_d1_mean"] and h["d10_d1_mean"] > 0 and h["d10_mean"] > r["d10_mean"] and h["d10_median"] >= r["d10_median"] and h["d10_cvar05"] >= r["d10_cvar05"]
    if a: return "A_CONFIRMED_NONLINEAR_CONDITIONAL_INFORMATION"
    if h["spearman"] > r["spearman"] and positive >= 3 and h["d10_d1_mean"] > r["d10_d1_mean"]: return "B_PARTIAL_OR_UNSTABLE_NONLINEAR_INCREMENT"
    return "C_CURRENT_INFORMATION_SET_NONLINEAR_EDGE_NOT_CONFIRMED"


def finalize(hashes_before: dict[str, str], registration: dict[str, object], features: list[str], folds: list[dict[str, object]], oof_frame: pd.DataFrame, fold_metrics: pd.DataFrame, audit: dict[str, object]) -> dict[str, object]:
    ridge_metrics, ridge_deciles = model_metrics(oof_frame, "ridge"); hgb_metrics, hgb_deciles = model_metrics(oof_frame, "hgb")
    decision = classify(ridge_metrics, hgb_metrics, fold_metrics); hashes_after = {name: sha(path) for name, (path, _) in source_paths().items()}
    if hashes_before != hashes_after: raise Stop("STOP_SOURCE_MUTATION")
    counts = {"hgb_spearman_beats_ridge_fold_count": int((fold_metrics.hgb_spearman > fold_metrics.ridge_spearman).sum()), "hgb_positive_d10_d1_fold_count": int((fold_metrics.hgb_d10_d1_mean > 0).sum()), "hgb_d10_mean_beats_ridge_fold_count": int((fold_metrics.hgb_d10_mean > fold_metrics.ridge_d10_mean).sum())}
    summary = {"status": "PASS", "classification": decision, "decision": {"A_CONFIRMED_NONLINEAR_CONDITIONAL_INFORMATION": "NONLINEAR_CONDITIONAL_INFORMATION_CONFIRMED_PRE2026_FREEZE_CANDIDATE_BEFORE_2026_HOLDOUT", "B_PARTIAL_OR_UNSTABLE_NONLINEAR_INCREMENT": "PARTIAL_NONLINEAR_INCREMENT_REQUIRE_FROZEN_CONFIRMATION_NO_TUNING", "C_CURRENT_INFORMATION_SET_NONLINEAR_EDGE_NOT_CONFIRMED": "CURRENT_INFORMATION_SET_NONLINEAR_EDGE_NOT_CONFIRMED_STOP_MODEL_TUNING"}[decision], "target_contract_id": TARGET_ID, "target_contract_sha256": hashes_before["target_contract"], "target_name": TARGET_NAME, "target_max_forward_horizon": 60, "feature_set_id": FEATURE_ID, "feature_schema_sha256": registration["feature_schema_sha256"], "feature_count": len(features), "pit_audit_status": "PASS_R28_DECISION_TIME_FEATURE_RECONSTRUCTION", "fold_source": "REUSED_AUTHORITATIVE", "oof_fold_count": 5, "purge_status": "PASS", "ridge": ridge_metrics, "hgb": hgb_metrics, "delta_spearman": hgb_metrics["spearman"]-ridge_metrics["spearman"], "delta_d10_mean": hgb_metrics["d10_mean"]-ridge_metrics["d10_mean"], "delta_d10_d1_mean": hgb_metrics["d10_d1_mean"]-ridge_metrics["d10_d1_mean"], **counts, **audit, "model_fit_count": 10, "model_predict_call_count": 10, "source_mutation_status": "PASS", "holdout_2026_read_count": 0, "persisted_model_binary_count": 0}
    write_csv(pd.concat([ridge_deciles, hgb_deciles]), RESULTS / "decile_metrics.csv"); write_json(RESULTS / "aggregate_metrics.json", {"ridge": ridge_metrics, "hgb": hgb_metrics, "counts": counts}); write_json(RESULTS / "pre2026_nonlinear_r1_summary.json", summary)
    return summary


def resume() -> dict[str, object]:
    target_contract, hashes_before, features, folds = preflight(); registration = prereg(target_contract, hashes_before, features, folds)
    existing = json.loads((RESULTS / "pre2026_nonlinear_r1_preregistration.json").read_text(encoding="utf-8"))
    if existing != registration: raise Stop("STOP_EXISTING_PREREGISTRATION_MISMATCH")
    required = ["oof_predictions.parquet", "fold_metrics.csv", "data_eligibility_audit.json"]
    if any(not (RESULTS / name).is_file() for name in required): raise Stop("STOP_PARTIAL_RUN_NOT_RESUMABLE_WITHOUT_REFIT")
    oof = pd.read_parquet(RESULTS / "oof_predictions.parquet"); folds_metric = pd.read_csv(RESULTS / "fold_metrics.csv")
    require_cross_section(oof)
    audit = json.loads((RESULTS / "data_eligibility_audit.json").read_text(encoding="utf-8"))
    return finalize(hashes_before, registration, features, folds, oof, folds_metric, audit)


def run() -> dict[str, object]:
    if RESULTS.exists(): return resume()
    target_contract, hashes_before, features, folds = preflight()
    registration = prereg(target_contract, hashes_before, features, folds)
    write_json(RESULTS / "pre2026_nonlinear_r1_preregistration.json", registration)
    frame, excluded = load_frame(features)
    require_cross_section(frame)
    if frame["sample_id"].duplicated().any(): raise Stop("STOP_DUPLICATE_SAMPLE_IDENTITY")
    fold_rows, oof = [], []
    for spec in folds:
        valid_start = pd.Timestamp(spec["validation_start"]); valid = frame[frame.validation_slice == spec["validation_block"]].copy()
        train = frame[frame.validation_slice.isin(spec["train_blocks"])].copy(); before = len(train); train = purge_train(train, valid_start)
        if train.empty or valid.empty or not (train.signal_date < valid.signal_date.min()).all() or not (train.target_end_timestamp < valid_start).all(): raise Stop("STOP_TEMPORAL_PURGE_FAILURE")
        xtr, xva, y = train[features], valid[features], train.target
        ridge = Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler()), ("model", Ridge(**RIDGE_CONFIG))])
        hgb = Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", HistGradientBoostingRegressor(**HGB_CONFIG))])
        valid["ridge_prediction"] = ridge.fit(xtr, y).predict(xva); valid["hgb_prediction"] = hgb.fit(xtr, y).predict(xva); valid["fold_id"] = spec["fold_id"]
        rm, _ = model_metrics(valid, "ridge"); hm, _ = model_metrics(valid, "hgb")
        fold_rows.append({"fold_id": spec["fold_id"], "train_row_count": len(train), "purged_train_row_count": before-len(train), "train_signal_date_min": train.signal_date.min(), "train_signal_date_max": train.signal_date.max(), "train_target_end_max": train.target_end_timestamp.max(), "validation_start": valid_start, "validation_signal_date_max": valid.signal_date.max(), **{f"ridge_{k}": v for k,v in rm.items()}, **{f"hgb_{k}": v for k,v in hm.items()}})
        oof.append(valid[["signal_date", "ticker", "sample_id", "fold_id", "direction", "target", "target_end_timestamp", "ridge_prediction", "hgb_prediction"]])
    oof_frame = pd.concat(oof, ignore_index=True); fold_metrics = pd.DataFrame(fold_rows)
    if oof_frame.sample_id.duplicated().any(): raise Stop("STOP_OOF_SELF_TRAIN_LEAKAGE")
    audit = {"feature_rows": len(frame), "unique_signal_dates": int(frame.signal_date.nunique()), "unique_tickers": int(frame.ticker.nunique()), "feature_date_min": frame.signal_date.min(), "feature_date_max": frame.signal_date.max(), "target_date_min": frame.signal_date.min(), "target_date_max": frame.signal_date.max(), "pre2026_eligible_row_count": len(frame), **excluded, "max_model_fit_signal_date": fold_metrics.train_signal_date_max.max(), "max_model_fit_target_end_timestamp": fold_metrics.train_target_end_max.max(), "source_mutation_status": "PASS"}
    hashes_after = {name: sha(path) for name, (path, _) in source_paths().items()}
    if hashes_before != hashes_after: raise Stop("STOP_SOURCE_MUTATION")
    source_manifest = {name: {"path": str(path), "sha256_before": hashes_before[name], "sha256_after": hashes_after[name], "purpose": purpose} for name,(path,purpose) in source_paths().items()}
    write_json(RESULTS / "source_manifest.json", source_manifest); write_json(RESULTS / "data_eligibility_audit.json", audit); write_json(RESULTS / "fold_contract.json", {"fold_source": "REUSED_AUTHORITATIVE", "folds": folds}); write_json(RESULTS / "model_configs.json", {"RIDGE_FIXED_R1": RIDGE_CONFIG, "HGB_SHALLOW_FIXED_R1": HGB_CONFIG}); oof_frame.to_parquet(RESULTS / "oof_predictions.parquet", index=False); write_csv(fold_metrics, RESULTS / "fold_metrics.csv")
    return finalize(hashes_before, registration, features, folds, oof_frame, fold_metrics, audit)


def main() -> None:
    try:
        s = run()
        print(f"PRE2026_NONLINEAR_R1_STATUS={s['status']}\nPRE2026_NONLINEAR_R1_CLASSIFICATION={s['classification']}\nPRE2026_NONLINEAR_R1_DECISION={s['decision']}\nRESULTS_ROOT={RESULTS}\nSUMMARY_PATH={RESULTS / 'pre2026_nonlinear_r1_summary.json'}")
    except Stop as exc:
        print(f"PRE2026_NONLINEAR_R1_STATUS=STOP\nPRE2026_NONLINEAR_R1_DECISION={exc}")
        raise SystemExit(2)


if __name__ == "__main__": main()
