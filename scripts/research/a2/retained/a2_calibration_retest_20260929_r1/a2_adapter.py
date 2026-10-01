"""Original frozen Raw A2 -> time-legal common one-day return calibration.

Only --prepare fits new statistical adapters, on preserved pre2026 OOF rows.
The original A2 estimator and all previous batches are read-only. 2026 inference
requires the new whole-batch seal before any model or test panel is loaded.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parent
OLD = ROOT.parent / "a2_pto_full_compat_20260928_r2"
ORIGINAL = Path("D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1")
FEATURE_SOURCE = Path("D:/us-tech-quant/scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py")
MODEL = ORIGINAL / "A2/final_full_pre2026_hgb.joblib"
OOF = ORIGINAL / "A2/oof_predictions.parquet"
MODEL_SHA256 = "4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b"
OOF_SHA256 = "e336be6c267167356ce3d39fa629f80fe7b2968711112a9c976fdb002c693468"
FEATURE_SOURCE_SHA256 = "fd4fe78d27bfbf57c89343d60550366ccf7fcbf3d6a65e7ef66f28405d050c19"
TRAINING_MATRIX_SHA256 = "31cc2b3dd2aa7a7c3372d56d5f3f351746b4ad06ef984563de576071913615fb"
KEYS = ["signal_date", "ticker"]
SEED = 20260928
MAX_ROWS = 40000
PERIODS = {
    "validation": (["2023H2", "2024"], "2025-01-01", "2025"),
    "final": (["2023H2", "2024", "2025"], "2026-01-01", "final"),
}
SPEC = {
    "input": "saved original Raw A2 MEAN_ER_3D_5D_10D_20D score",
    "output": "one-day uncosted raw index return decimal plus common period delta",
    "calibration": "StandardScaler weighted on sampled earlier OOF; Ridge alpha100",
    "sample": "unchanged old sample: sorted signal_date/ticker, seed20260928, per-date quota, max40000",
    "date_weighting": "equal total weight per sampled signal date, normalized mean weight1",
    "base_model_fit_calls": 0,
    "original_A2_2025": "saved FINAL OOF; never full-pre2026 model backprediction",
    "cash": "endogenous optimization; max .95 is a ceiling, not mandatory exposure",
}


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str,
                               allow_nan=False), encoding="utf-8")


def _keys_checked(frame, name):
    if not set(KEYS).issubset(frame.columns) or frame.empty:
        raise ValueError(name + "_EMPTY_OR_MISSING_KEYS")
    if frame[KEYS].isna().any().any() or frame.duplicated(KEYS).any():
        raise ValueError(name + "_MISSING_OR_DUPLICATE_KEYS")
    if not pd.api.types.is_datetime64_any_dtype(frame.signal_date):
        raise ValueError(name + "_SIGNAL_DATE_DTYPE")
    if frame.signal_date.dt.tz is not None:
        raise ValueError(name + "_SIGNAL_DATE_TZ")
    if not frame.signal_date.eq(frame.signal_date.dt.normalize()).all():
        raise ValueError(name + "_SIGNAL_DATE_NOT_SESSION_LABEL")


def align_history(raw_scores, common_history, cutoff, *, require_same_keys=True):
    """Align exactly to the common keys; reject missing rows before sampling.

    The preserved original OOF contains full years; production allows unused
    original keys. Every requested common key must occur exactly once. No label
    or forecast NaNs may silently remove a training row.
    """
    _keys_checked(raw_scores, "A2_OOF")
    _keys_checked(common_history, "COMMON_HISTORY")
    cutoff = pd.Timestamp(cutoff)
    if cutoff > pd.Timestamp("2026-01-01") or pd.isna(cutoff):
        raise ValueError("ADAPTER_PRE2026_CUTOFF_REQUIRED")
    if not {"y_next_open", "label_end_date"}.issubset(common_history.columns):
        raise ValueError("COMMON_ONE_DAY_TARGET_REQUIRED")
    h = common_history[KEYS + ["y_next_open", "label_end_date"]].copy()
    if (not h.signal_date.lt(cutoff).all()
            or not h.label_end_date.lt(cutoff).all()
            or not h.label_end_date.gt(h.signal_date).all()):
        raise ValueError("ADAPTER_CLOCK_LEAK_OR_INVALID_LABEL_CLOCK")
    score_name = "raw_a2_score" if "raw_a2_score" in raw_scores else "a2_prediction"
    if score_name not in raw_scores:
        raise ValueError("ORIGINAL_A2_SCORE_REQUIRED")
    scores = raw_scores[KEYS + [score_name]].rename(columns={score_name: "raw_a2_score"})
    if require_same_keys:
        a = h[KEYS].sort_values(KEYS).reset_index(drop=True)
        b = scores[KEYS].sort_values(KEYS).reset_index(drop=True)
        if not a.equals(b):
            raise ValueError("A2_COMMON_HISTORY_KEY_SETS_DIFFER")
    result = h.merge(scores, on=KEYS, how="left", sort=False,
                     validate="one_to_one", indicator=True)
    if not result["_merge"].eq("both").all():
        raise ValueError("A2_COMMON_HISTORY_MISSING_SCORE_KEYS")
    if not np.isfinite(result[["raw_a2_score", "y_next_open"]].to_numpy(float)).all():
        raise ValueError("ADAPTER_NONFINITE_INPUT_OR_TARGET")
    result = result.drop(columns="_merge")
    result.attrs["unused_original_oof_keys"] = int(len(scores) - len(result))
    return result


def sample(frame):
    """Exact old calibration_fusion.sample, with unchanged numerical budget."""
    frame = frame.sort_values(KEYS).reset_index(drop=True)
    rng = np.random.default_rng(SEED)
    quota = max(1, MAX_ROWS // frame.signal_date.nunique())
    picks = []
    for _, group in frame.groupby("signal_date", sort=True):
        picks.extend(sorted(rng.choice(group.index, min(quota, len(group)), replace=False)))
    if len(picks) > MAX_ROWS:
        picks = sorted(rng.choice(picks, MAX_ROWS, replace=False))
    return frame.loc[picks].reset_index(drop=True)


def date_weights(dates):
    dates = pd.Series(dates)
    counts = dates.map(dates.value_counts()).to_numpy(float)
    weights = 1. / counts
    return weights / weights.mean()


def fit_adapter(history, cutoff):
    """Fit the authorized new score adapter, never an A2 base estimator."""
    h = align_history(history[KEYS + ["raw_a2_score"]], history, cutoff)
    sampled = sample(h)
    x = sampled[["raw_a2_score"]].to_numpy(float)
    y = sampled.y_next_open.to_numpy(float)
    weights = date_weights(sampled.signal_date)
    with threadpool_limits(limits=1):
        scaler = StandardScaler().fit(x, sample_weight=weights)
        xx = scaler.transform(x)
        model = Ridge(alpha=100.).fit(xx, y, sample_weight=weights)
        mu = model.predict(xx)
    rms = float(np.sqrt(np.average((y - mu) ** 2, weights=weights)))
    calibrator = {"scaler": scaler, "model": model,
                  "residual_rms": max(rms, 1e-6), "spec": SPEC}
    receipt = {
        "status": "TRAINED", "full_history_rows": len(h), "sampled_rows": len(sampled),
        "fit_cutoff_exclusive": str(pd.Timestamp(cutoff).date()),
        "max_signal": str(h.signal_date.max()), "max_label_end": str(h.label_end_date.max()),
        "fit_2026_rows": 0, "base_model_fit_calls": 0,
        "new_calibrator_fit_calls": 1, "new_standardizer_fit_calls": 1,
        "calibration_unit": "one-day raw return decimal before period delta",
        "residual_rms_in_fit": rms, "spec": SPEC,
    }
    return calibrator, receipt


def predict_adapter(calibrator, raw_scores):
    values = np.asarray(raw_scores, dtype=np.float64).reshape(-1, 1)
    if not np.isfinite(values).all():
        raise ValueError("A2_INFERENCE_NONFINITE_SCORE")
    return calibrator["model"].predict(calibrator["scaler"].transform(values))


def _feature_order():
    if sha(FEATURE_SOURCE) != FEATURE_SOURCE_SHA256:
        raise RuntimeError("ORIGINAL_FEATURE_SOURCE_CHANGED")
    for node in ast.parse(FEATURE_SOURCE.read_text(encoding="utf-8-sig")).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "FEATURE_COLUMNS"
                for target in node.targets):
            return list(ast.literal_eval(node.value))
    raise RuntimeError("ORIGINAL_ORDERED_FEATURES_MISSING")


def _assert_hash(path, expected):
    if sha(path) != expected:
        raise RuntimeError("SOURCE_OR_ARTIFACT_CHANGED:" + str(path))


def _preparation_sources(stage):
    histories, _, _ = PERIODS[stage]
    paths = [MODEL, OOF, FEATURE_SOURCE, ORIGINAL / "A2/training_matrix.parquet",
             OLD / "data/pre_panel.parquet", OLD / "calibration_fusion.py",
             OLD / "train_cooperation.py", OLD / "shared.py", Path(__file__)]
    paths += [OLD / "predictions" / f"raw_oof_{period}.parquet" for period in histories]
    paths += [OLD / "predictions" / f"raw_oof_{period}_receipt.json" for period in histories]
    return {str(path.resolve()): sha(path) for path in paths}


def prepare_a2_adapter(stage):
    if stage not in PERIODS:
        raise ValueError("FIXED_A2_STAGES_ONLY")
    if (ROOT / "FROZEN_BEFORE_2026.json").exists():
        raise RuntimeError("PREPARE_FORBIDDEN_AFTER_NEW_FREEZE")
    _assert_hash(MODEL, MODEL_SHA256)
    _assert_hash(OOF, OOF_SHA256)
    _assert_hash(ORIGINAL / "A2/training_matrix.parquet", TRAINING_MATRIX_SHA256)
    features = _feature_order()
    audit = read(ROOT / "A2_REUSE_AUDIT.json")
    if features != audit["original_raw_a2"]["feature_order"]:
        raise RuntimeError("ORIGINAL_FEATURE_ORDER_CHANGED")
    bindings = _preparation_sources(stage)
    folder = ROOT / "models"
    folder.mkdir(parents=True, exist_ok=True)
    receipt_path = folder / f"a2_{stage}_calibrator.json"
    if receipt_path.exists():
        prior = read(receipt_path)
        if prior["source_bindings"] != bindings:
            raise RuntimeError("A2_PREPARE_BINDING_CHANGED")
        for name, digest in prior.get("artifacts", {}).items():
            _assert_hash(name, digest)
        return prior
    histories, cutoff, period = PERIODS[stage]
    parts = []
    for history in histories:
        prior = read(OLD / "predictions" / f"raw_oof_{history}_receipt.json")
        if pd.Timestamp(prior["base_fit_cutoff_exclusive"]) >= pd.Timestamp(cutoff):
            raise RuntimeError("COMMON_HISTORY_BASE_FIT_AFTER_ADAPTER_CUTOFF")
        part = pd.read_parquet(OLD / "predictions" / f"raw_oof_{history}.parquet",
                               columns=KEYS + ["y_next_open", "label_end_date"])
        if not part.signal_date.ge(pd.Timestamp(prior["base_fit_cutoff_exclusive"])).all():
            raise RuntimeError("COMMON_HISTORY_PREDICTION_BEFORE_BASE_FIT_CUTOFF")
        parts.append(part)
    common = pd.concat(parts, ignore_index=True)
    original = pd.read_parquet(OOF, columns=KEYS + ["a2_prediction", "split"])
    allowed = {2023: "DEVELOPMENT", 2024: "CONFIRMATION", 2025: "FINAL"}
    expected_stage = original.signal_date.dt.year.map(allowed)
    if not original["split"].eq(expected_stage).all():
        raise RuntimeError("ORIGINAL_OOF_STAGE_YEAR_MISMATCH")
    for vintage in audit["original_raw_a2"]["original_oof_stages"]:
        rows = original.loc[original["split"].eq(vintage["stage"])]
        if (len(rows) != vintage["prediction_rows"]
                or not rows.signal_date.gt(pd.Timestamp(vintage["training_target_end_last"])).all()
                or not rows.signal_date.gt(pd.Timestamp(vintage["training_signal_last"])).all()):
            raise RuntimeError("ORIGINAL_OOF_VINTAGE_TRAINING_CLOCK_LEAK")
    h = align_history(original, common, cutoff, require_same_keys=False)
    sampled = sample(h)
    calibrator, receipt = fit_adapter(h, cutoff)
    destination = folder / f"a2_{stage}_calibrator.joblib"
    sample_path = folder / f"a2_{stage}_sample_keys.parquet"
    if destination.exists() or sample_path.exists():
        raise RuntimeError("UNRECEIPTED_A2_PREPARE_ARTIFACT_EXISTS")
    joblib.dump(calibrator, destination)
    sampled[KEYS + ["label_end_date"]].to_parquet(sample_path, index=False)
    receipt.update(stage=stage, period=period, unused_original_oof_keys=h.attrs["unused_original_oof_keys"],
                   source_bindings=bindings, artifacts={str(p): sha(p) for p in [destination, sample_path]})
    for path, digest in bindings.items():
        _assert_hash(path, digest)
    write(receipt_path, receipt)
    return receipt


def prepare():
    """Resolve both declared calibration fits, retaining explicit failures."""
    if (ROOT / "FROZEN_BEFORE_2026.json").exists():
        raise RuntimeError("PREPARE_FORBIDDEN_AFTER_NEW_FREEZE")
    status_path = ROOT / "A2_ADAPTER_STATUS.json"
    if status_path.exists():
        status = read(status_path)
        for name, digest in status.get("source_bindings", {}).items():
            _assert_hash(name, digest)
        for name, digest in status.get("artifacts", {}).items():
            _assert_hash(name, digest)
        return status
    records = []
    for stage in PERIODS:
        started = time.monotonic()
        try:
            record = prepare_a2_adapter(stage)
        except Exception as exc:
            record = {"stage": stage, "status": "FAILED_ADAPTER",
                      "exception": type(exc).__name__, "reason": str(exc),
                      "base_model_fit_calls": 0, "fit_2026_rows": 0}
        record["elapsed_seconds"] = time.monotonic() - started
        records.append(record)
    bindings = {}; artifacts = {}
    for record in records:
        bindings.update(record.get("source_bindings", {}))
        artifacts.update(record.get("artifacts", {}))
    status = {
        "status": "COMPLETE" if all(x["status"] == "TRAINED" for x in records) else "FAILED_ADAPTER",
        "created_utc": datetime.now(timezone.utc).isoformat(), "records": records,
        "source_bindings": bindings, "artifacts": artifacts,
        "base_model_fit_calls": 0, "fit_2026_rows": 0,
        "new_calibrator_fit_calls": sum(x.get("new_calibrator_fit_calls", 0) for x in records),
        "new_standardizer_fit_calls": sum(x.get("new_standardizer_fit_calls", 0) for x in records),
        "year_records": {
            "2025": {"stage": "validation", "period": "2025", "score_source": str(OOF),
                     "score_source_sha256": OOF_SHA256, "status": "NOT_INFERRED"},
            "2026": {"stage": "final", "period": "final", "score_source": str(MODEL),
                     "score_source_sha256": MODEL_SHA256, "status": "NOT_INFERRED_REQUIRES_NEW_FREEZE"},
        },
        "spec": SPEC,
        "inference_receipts": "predictions/evaluation_YEAR/A2_COMPLETE.json; frozen prepare status is never mutated",
    }
    write(status_path, status)
    audit_path = ROOT / "A2_REUSE_AUDIT.json"
    audit = read(audit_path)
    # Required originals remain bound even when an adapter failed before fitting.
    audit.setdefault("source_bindings", {}).update({str(p): sha(p) for p in [MODEL, OOF, FEATURE_SOURCE]})
    audit["source_bindings"].update(bindings)
    audit["source_bindings"].update(artifacts)
    audit["adapter_preparation_receipt"] = str(status_path)
    write(audit_path, audit)
    return status


def _verify_new_freeze():
    marker = ROOT / "FROZEN_BEFORE_2026.json"
    if not marker.is_file():
        raise RuntimeError("NEW_BATCH_FREEZE_REQUIRED")
    module = importlib.import_module("integrity")
    if Path(module.__file__).resolve() != (ROOT / "integrity.py").resolve():
        raise RuntimeError("WRONG_NEW_INTEGRITY_MODULE")
    return module.verify_freeze()


def _assert_bound(receipt, path, digest):
    if receipt["bindings"].get(str(Path(path).resolve())) != digest:
        raise RuntimeError("REQUIRED_A2_SOURCE_NOT_IN_NEW_FREEZE:" + str(path))


def _old_runtime():
    if str(OLD) not in sys.path:
        sys.path.insert(0, str(OLD))
    module = importlib.import_module("market_runtime")
    if Path(module.__file__).resolve() != (OLD / "market_runtime.py").resolve() or Path(module.ROOT) != OLD:
        raise RuntimeError("WRONG_FROZEN_MARKET_RUNTIME")
    return module


@contextmanager
def _forbid_a2_fit():
    def denied(*args, **kwargs):
        raise RuntimeError("ORIGINAL_A2_BASE_FIT_FORBIDDEN")
    with patch.object(HistGradientBoostingRegressor, "fit", denied):
        yield


def predict_original(feature_frame, model_path=MODEL, expected_hash=MODEL_SHA256,
                     *, feature_order=None):
    """Only read-only inference on the exact original model and ordered inputs."""
    _assert_hash(model_path, expected_hash)
    features = _feature_order() if feature_order is None else list(feature_order)
    if len(features) != 32 or not set(features).issubset(feature_frame.columns):
        raise ValueError("ORIGINAL_32_ORDERED_FEATURES_REQUIRED")
    x = feature_frame[features].to_numpy(dtype=np.float64)
    if not np.isfinite(x).all():
        raise ValueError("ORIGINAL_A2_NONFINITE_FEATURES")
    with _forbid_a2_fit(), threadpool_limits(limits=1):
        model = joblib.load(model_path)
        if model.n_features_in_ != 32:
            raise RuntimeError("ORIGINAL_A2_FEATURE_COUNT_MISMATCH")
        score = np.asarray(model.predict(x), dtype=np.float64)
    _assert_hash(model_path, expected_hash)
    if score.shape != (len(feature_frame),) or not np.isfinite(score).all():
        raise RuntimeError("ORIGINAL_A2_INVALID_PREDICTION")
    return score


def _period_delta(year):
    # The correction module owns the baseline intervention and period schema.
    module = importlib.import_module("baseline_correction")
    if Path(module.__file__).resolve() != (ROOT / "baseline_correction.py").resolve():
        raise RuntimeError("WRONG_BASELINE_CORRECTION_MODULE")
    return float(module.delta_for_year(year))


def make_a2_predictions(year):
    if year not in [2025, 2026]:
        raise ValueError("FIXED_EVALUATION_YEARS")
    seal = _verify_new_freeze() if year == 2026 else None
    # The gate above precedes even status, model, old output or panel reads.
    status = read(ROOT / "A2_ADAPTER_STATUS.json")
    stage = "validation" if year == 2025 else "final"
    record = next(x for x in status["records"] if x["stage"] == stage)
    output = ROOT / "predictions" / f"evaluation_{year}"
    complete = output / "A2_COMPLETE.json"
    if complete.exists():
        prior = read(complete)
        for name, digest in prior.get("artifacts", {}).items():
            _assert_hash(output / name, digest)
        return prior
    if record["status"] != "TRAINED":
        common_path = OLD / "predictions" / f"evaluation_{year}" / "raw.parquet"
        unavailable = pd.read_parquet(common_path, columns=KEYS)
        _keys_checked(unavailable, "COMMON_FAILED_ADAPTER_CONTEXT")
        unavailable["raw_a2_score"] = np.nan
        unavailable["a2__mu"] = np.nan
        output.mkdir(parents=True, exist_ok=True)
        destination = output / "a2_scores.parquet"
        if destination.exists():
            raise RuntimeError("UNRECEIPTED_A2_PREDICTION_EXISTS")
        unavailable.to_parquet(destination, index=False)
        failure = {"status": "FAILED_ADAPTER", "year": year, "stage": stage,
                   "reason": record.get("reason", "PREPARE_FAILED"),
                   "failure": record.get("reason", "PREPARE_FAILED"),
                   "rows": len(unavailable), "fit_calls": 0,
                   "fit_2026_rows": 0, "base_model_inference_calls": 0,
                   "source_bindings": {str(common_path): sha(common_path)},
                   "artifacts": {destination.name: sha(destination)}, "base_model_unchanged": True}
        if year == 2026:
            _verify_new_freeze()
        write(complete, failure)
        return failure
    calibrator_path = ROOT / "models" / f"a2_{stage}_calibrator.joblib"
    expected = record["artifacts"][str(calibrator_path)]
    _assert_hash(calibrator_path, expected)
    if seal is not None:
        _assert_bound(seal, MODEL, MODEL_SHA256)
        _assert_bound(seal, OOF, OOF_SHA256)
        _assert_bound(seal, calibrator_path, expected)
    delta = _period_delta(year)
    if not np.isfinite(delta):
        raise RuntimeError("NONFINITE_COMMON_BASELINE_DELTA")
    if year == 2025:
        _assert_hash(OOF, OOF_SHA256)
        common = pd.read_parquet(OLD / "predictions/evaluation_2025/raw.parquet", columns=KEYS)
        _keys_checked(common, "COMMON_EVALUATION")
        original = pd.read_parquet(OOF, columns=KEYS + ["a2_prediction", "split"])
        original = original.loc[original["split"].eq("FINAL")].copy()
        frame = common.merge(original[KEYS + ["a2_prediction"]], on=KEYS, how="left",
                             validate="one_to_one", indicator=True)
        if not frame["_merge"].eq("both").all():
            raise RuntimeError("ORIGINAL_2025_OOF_CANDIDATE_MISMATCH")
        raw = frame.a2_prediction.to_numpy(float)
        source_identity = "ORIGINAL_SAVED_2025_FINAL_OOF"
        source_binding = {str(OOF): OOF_SHA256}
    else:
        prepared = _old_runtime().prepare_market(year)
        frame = prepared.panel.loc[prepared.panel.runtime_input_usable].reset_index(drop=True)
        _keys_checked(frame, "COMMON_EVALUATION")
        expected_keys = pd.read_parquet(OLD / "predictions/evaluation_2026/raw.parquet", columns=KEYS)
        if not frame[KEYS].equals(expected_keys[KEYS]):
            raise RuntimeError("ORIGINAL_2026_COMMON_RUNTIME_CONTEXT_KEY_MISMATCH")
        features = _feature_order()
        raw = predict_original(frame, feature_order=features)
        source_identity = "ORIGINAL_FINAL_PRE2026_MODEL_RETROSPECTIVE_INFERENCE"
        source_binding = {str(MODEL): MODEL_SHA256, str(FEATURE_SOURCE): FEATURE_SOURCE_SHA256}
    calibrator = joblib.load(calibrator_path)
    mu_before = predict_adapter(calibrator, raw)
    result = frame[KEYS].copy()
    result["raw_a2_score"] = raw
    result["a2__mu"] = mu_before + delta
    if not np.isfinite(result[["raw_a2_score", "a2__mu"]].to_numpy(float)).all():
        raise RuntimeError("A2_NONFINITE_COMMON_FORECAST")
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "a2_scores.parquet"
    if destination.exists():
        raise RuntimeError("UNRECEIPTED_A2_PREDICTION_EXISTS")
    result.to_parquet(destination, index=False)
    receipt = {"status": "COMPLETE", "year": year, "stage": stage,
               "period": "2025" if year == 2025 else "final", "rows": len(result),
               "columns": list(result.columns), "score_identity": source_identity,
               "calibration_sha256": expected, "common_baseline_delta": delta,
               "baseline_correction_sha256": sha(ROOT / "BASELINE_CORRECTION.json"),
               "common_delta_applied_once_in_a2_adapter": True,
               "source_bindings": source_binding, "artifacts": {destination.name: sha(destination)},
               "fit_calls": 0, "fit_2026_rows": 0, "base_model_unchanged": True,
               "old_A2_top20_filter": False, "blind_test": False,
               "original_pool_formal_status": "BLOCKED_DATA" if year == 2026 else "HISTORICAL_INPUT_LIMITATIONS"}
    for path, digest in source_binding.items():
        _assert_hash(path, digest)
    if year == 2026:
        _verify_new_freeze()
    write(complete, receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--year", type=int, choices=[2025, 2026])
    args = parser.parse_args()
    if args.prepare == (args.year is not None):
        parser.error("choose exactly --prepare or --year")
    receipt = prepare() if args.prepare else make_a2_predictions(args.year)
    print(receipt["status"], flush=True)
