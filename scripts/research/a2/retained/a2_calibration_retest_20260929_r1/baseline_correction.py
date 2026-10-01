"""One declared common-intercept correction; all old learned artifacts stay read-only."""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OLD = ROOT.parent / "a2_pto_full_compat_20260928_r2"
SEED = 20260928
MAX_ROWS = 40000
KEYS = ["signal_date", "ticker"]
OOF_COLUMNS = KEYS + ["y_next_open", "label_end_date"]
PERIODS = {
    "2025": (["2023H2", "2024"], "2025-01-01", 2025),
    "final": (["2023H2", "2024", "2025"], "2026-01-01", 2026),
}
EXPECTED_DELTA_BPS = {2025: 3.172794, 2026: -1.741201}


def sha(path: Path | str) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path | str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _immutable_json(path: Path, value: dict) -> dict:
    if path.exists():
        old = read_json(path)
        comparable = lambda x: {k: v for k, v in x.items() if k != "created_utc"}
        if comparable(old) != comparable(value):
            raise RuntimeError(f"PRESERVE_EXISTING_RECEIPT:{path}")
        return old
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return value


def equal_date_mean(frame: pd.DataFrame, value: str = "y_next_open") -> float:
    if frame.empty or frame.signal_date.isna().any():
        raise ValueError("EMPTY_OR_MISSING_SIGNAL_DATE")
    y = frame[value].to_numpy(dtype=float)
    if not np.isfinite(y).all():
        raise ValueError("NONFINITE_BASELINE_TARGET")
    counts = frame.signal_date.map(frame.signal_date.value_counts()).to_numpy(dtype=float)
    return float(np.average(y, weights=1.0 / counts))


def historical_sample(frame: pd.DataFrame) -> pd.DataFrame:
    """Reconstruct the OLD fixed sample only to measure its historical baseline."""
    frame = frame.sort_values(KEYS).reset_index(drop=True)
    rng = np.random.default_rng(SEED)
    quota = max(1, MAX_ROWS // frame.signal_date.nunique())
    picks = []
    for _, group in frame.groupby("signal_date", sort=True):
        picks.extend(sorted(rng.choice(group.index, min(quota, len(group)), replace=False)))
    if len(picks) > MAX_ROWS:
        picks = sorted(rng.choice(picks, MAX_ROWS, replace=False))
    return frame.loc[picks].reset_index(drop=True)


def validate_oof(frame: pd.DataFrame, receipt: dict) -> dict:
    if frame.empty or frame[KEYS + ["label_end_date"]].isna().any().any():
        raise ValueError("EMPTY_OR_MISSING_OOF_KEY_CLOCK")
    if frame.duplicated(KEYS).any():
        raise ValueError("DUPLICATE_OOF_KEYS")
    if not np.isfinite(frame.y_next_open.to_numpy(float)).all():
        raise ValueError("NONFINITE_OOF_TARGET")
    first = pd.Timestamp(receipt["oof_first"])
    last = pd.Timestamp(receipt["oof_last_exclusive"])
    base = pd.Timestamp(receipt["base_fit_cutoff_exclusive"])
    if (frame.signal_date.lt(first) | frame.signal_date.ge(last) | frame.signal_date.lt(base)).any():
        raise ValueError("OOF_SIGNAL_CLOCK_VIOLATION")
    if (frame.label_end_date.ge(last) | frame.label_end_date.le(frame.signal_date)).any():
        raise ValueError("OOF_LABEL_CLOCK_VIOLATION")
    if (frame.signal_date.ge("2026-01-01") | frame.label_end_date.ge("2026-01-01")).any():
        raise ValueError("OOF_CONTAINS_2026")
    if len(frame) != receipt["rows"]:
        raise ValueError("OOF_ROW_COUNT_CHANGED")
    return {"rows": len(frame), "signal_days": int(frame.signal_date.nunique()),
            "duplicate_keys": 0, "clock_violations": 0,
            "first_signal": str(frame.signal_date.min()), "last_signal": str(frame.signal_date.max()),
            "last_label_end": str(frame.label_end_date.max())}


def prepare_baseline() -> dict:
    if (ROOT / "FROZEN_BEFORE_2026.json").exists():
        raise RuntimeError("CANNOT_PREPARE_FROZEN_BATCH")
    frames, bindings, checks = {}, {}, {}
    for period in ["2023H2", "2024", "2025"]:
        path = OLD / "predictions" / f"raw_oof_{period}.parquet"
        receipt_path = path.with_name(f"raw_oof_{period}_receipt.json")
        receipt = read_json(receipt_path)
        digest = sha(path)
        if digest != receipt["sha256"]:
            raise RuntimeError(f"OOF_RECEIPT_HASH_MISMATCH:{period}")
        frames[period] = pd.read_parquet(path, columns=OOF_COLUMNS)
        checks[period] = validate_oof(frames[period], receipt)
        bindings[str(path)] = digest
        bindings[str(receipt_path)] = sha(receipt_path)
    for name in ["calibration_fusion.py", "train_cooperation.py", "shared.py"]:
        bindings[str(OLD / name)] = sha(OLD / name)
    records, previous_keys = {}, set()
    for period, (history, cutoff, year) in PERIODS.items():
        whole = pd.concat([frames[p] for p in history], ignore_index=True)
        if whole.duplicated(KEYS).any():
            raise ValueError("DUPLICATE_POOLED_OOF_KEYS")
        if not (whole.signal_date.lt(cutoff).all() and whole.label_end_date.lt(cutoff).all()):
            raise ValueError("POOLED_BASELINE_CLOCK_VIOLATION")
        current_keys = set(map(tuple, whole[KEYS].to_numpy()))
        if not previous_keys.issubset(current_keys):
            raise ValueError("BASELINE_HISTORY_IS_NOT_NESTED")
        status_path = OLD / "models" / f"calibration_{period}" / "STATUS.json"
        status = read_json(status_path)
        bindings[str(status_path)] = sha(status_path)
        old_inputs = {str(Path(p).resolve()): h for p, h in status["binding"]["inputs"].items()}
        for p in history:
            path = OLD / "predictions" / f"raw_oof_{p}.parquet"
            if old_inputs.get(str(path.resolve())) != bindings[str(path)]:
                raise RuntimeError("OLD_CALIBRATION_OOF_BINDING_CHANGED")
        if len(status["records"]) != 31 or len({r["name"] for r in status["records"]}) != 31:
            raise RuntimeError("OLD_CALIBRATION_ROSTER_CHANGED")
        if Counter(r["status"] for r in status["records"]) != {"TRAINED": 30, "FAILED": 1}:
            raise RuntimeError("OLD_CALIBRATION_COVERAGE_CHANGED")
        old_sample = historical_sample(whole)
        fit_rows = {r["receipt"]["rows"] for r in status["records"] if r["status"] == "TRAINED"}
        if fit_rows != {len(old_sample)}:
            raise RuntimeError("OLD_CALIBRATION_SAMPLE_NOT_REPRODUCED")
        full = equal_date_mean(whole)
        sampled = equal_date_mean(old_sample)
        delta = full - sampled
        if abs(delta * 10000.0 - EXPECTED_DELTA_BPS[year]) > 5e-7:
            raise RuntimeError("PREDECLARED_COMMON_DELTA_CHANGED")
        records[str(year)] = {"period": period, "fit_cutoff_exclusive": cutoff,
            "histories": history, "full_legal_rows": len(whole),
            "full_legal_days": int(whole.signal_date.nunique()), "old_sample_rows": len(old_sample),
            "full_equal_date_y_mean": full, "old_sample_equal_date_y_mean": sampled,
            "delta_decimal": delta, "delta_bps": delta * 10000.0,
            "last_label_end": str(whole.label_end_date.max()),
            "previous_history_rows_preserved": len(previous_keys), "nested_history_missing_rows": 0}
        previous_keys = current_keys
    value = {"schema_version": 1, "status": "PREPARED_NO_FIT",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "old_root": str(OLD), "unit": "raw one-session return decimal",
        "method": "same common delta added to every available member mu; no slope/scaler/p/uncertainty changes",
        "baseline_definition": "all legal OOF rows retained, equal total weight for each signal date",
        "years": records, "delta_decimal": {year: r["delta_decimal"] for year, r in records.items()},
        "source_bindings": bindings, "fit_calls": 0, "read_2026_rows": 0,
        "model_inference_calls": 0, "seed_searches": 0, "old_files_modified": False,
        "limitations": ["This corrects the common sampled target baseline; it does not refit slopes or recenter each model on its full-OOF prediction mean.",
                         "Frozen nonlinear fusion can change rankings when its inputs are shifted.",
                         "2026 was already exposed; this is not a new blind evaluation."]}
    destination = ROOT / "BASELINE_CORRECTION.json"
    value = _immutable_json(destination, value)
    receipt = {"status": "PASS_PRE2026_BASELINE_PREPARATION", "created_utc": value["created_utc"],
        "baseline_artifact": str(destination), "baseline_sha256": sha(destination),
        "oof_checks": checks, "fit_calls": 0, "read_2026_rows": 0, "model_inference_calls": 0,
        "numpy_version": np.__version__, "pandas_version": pd.__version__}
    _immutable_json(ROOT / "audits" / "BASELINE_PREPARE_RECEIPT.json", receipt)
    return value


def shift_member_mu(frame: pd.DataFrame, delta: float) -> pd.DataFrame:
    if not np.isfinite(delta):
        raise ValueError("NONFINITE_DELTA")
    result = frame.copy(deep=True)
    columns = [c for c in frame if c.endswith("__mu")]
    if not columns:
        raise ValueError("NO_MEMBER_MU_COLUMNS")
    for column in columns:
        values = frame[column].to_numpy(copy=True)
        if values.dtype != np.float64 or np.isinf(values).any():
            raise ValueError("INVALID_MEMBER_MU_DTYPE_OR_INFINITY")
        finite = np.isfinite(values)
        values[finite] += delta
        result[column] = values
    return result


def delta_for_year(year: int) -> float:
    """Shared public lookup for this batch, including the separate A2 adapter."""
    if year not in (2025, 2026):
        raise ValueError("ONLY_DECLARED_YEARS")
    value = float(read_json(ROOT / "BASELINE_CORRECTION.json")["delta_decimal"][str(year)])
    if not np.isfinite(value):
        raise ValueError("NONFINITE_DELTA")
    return value


# Public alias requested by the batch runner; preparation remains pre-freeze only.
makebaseline = prepare_baseline


def _verify_new_freeze() -> None:
    if not (ROOT / "FROZEN_BEFORE_2026.json").is_file():
        raise RuntimeError("NEW_BATCH_FREEZE_REQUIRED_BEFORE_2026")
    path = ROOT / "integrity.py"
    if not path.is_file():
        raise RuntimeError("NEW_BATCH_INTEGRITY_VERIFIER_REQUIRED")
    spec = importlib.util.spec_from_file_location("_baseline_new_integrity", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "verify_freeze", None)):
        raise RuntimeError("NEW_INTEGRITY_VERIFY_FREEZE_INTERFACE_REQUIRED")
    module.verify_freeze()


def _old_runtime():
    if str(OLD) not in sys.path:
        sys.path.insert(0, str(OLD))
    shared = importlib.import_module("shared")
    if Path(shared.ROOT).resolve() != OLD.resolve():
        raise RuntimeError("OLD_RUNTIME_ROOT_MUST_NOT_BE_REDIRECTED")
    market = importlib.import_module("market_runtime")
    cooperation = importlib.import_module("train_cooperation")
    calibration = importlib.import_module("calibration_fusion")
    return shared, market, cooperation, calibration


def make_predictions(year: int) -> dict:
    if year not in (2025, 2026):
        raise ValueError("ONLY_DECLARED_YEARS")
    if year == 2026:
        _verify_new_freeze()
    baseline = read_json(ROOT / "BASELINE_CORRECTION.json")
    for path, expected in baseline["source_bindings"].items():
        if sha(path) != expected:
            raise RuntimeError(f"BASELINE_SOURCE_CHANGED:{path}")
    out = ROOT / "predictions" / f"evaluation_{year}"
    if (out / "COMPLETE.json").exists():
        receipt = read_json(out / "COMPLETE.json")
        for name, expected in receipt["artifacts"].items():
            if sha(out / name) != expected:
                raise RuntimeError("PRESERVE_COMPLETED_NEW_PREDICTIONS")
        if sha(receipt["RISK_CACHE_SOURCE"]["path"]) != receipt["RISK_CACHE_SOURCE"]["sha256"]:
            raise RuntimeError("OLD_RISK_CACHE_CHANGED")
        return receipt
    if out.exists():
        raise RuntimeError("PRESERVE_INTERRUPTED_NEW_PREDICTIONS")
    old_out = OLD / "predictions" / f"evaluation_{year}"
    old_receipt = read_json(old_out / "COMPLETE.json")
    calibrated_path = old_out / "calibrated.parquet"
    risk_path = old_out / "risk_cache.npz"
    for path in [calibrated_path, risk_path, old_out / "STREAM_COVERAGE.csv"]:
        if sha(path) != old_receipt["artifacts"][path.name]:
            raise RuntimeError(f"OLD_EVALUATION_SOURCE_CHANGED:{path.name}")
    calibrated = pd.read_parquet(calibrated_path)
    shared, market_runtime, cooperation, calibration = _old_runtime()
    if set(c for c in calibrated if c.endswith("__mu")) != {name + "__mu" for name in shared.PREDICTORS}:
        raise RuntimeError("MEMBER_ROSTER_CHANGED")
    delta = delta_for_year(year)
    corrected = shift_member_mu(calibrated, delta)
    prepared = market_runtime.prepare_market(year)
    frame = prepared.panel.loc[prepared.panel.runtime_input_usable].reset_index(drop=True)
    if not frame[KEYS].equals(calibrated[KEYS].reset_index(drop=True)):
        raise RuntimeError("EXACT_OLD_PREDICTION_CONTEXT_KEYS_REQUIRED")
    context = frame[calibration.SPEC["context"]].to_numpy(float)
    stage = "validation" if year == 2025 else "final"
    runtime = cooperation.CooperationRuntime(stage)
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=2):
        streams = runtime.predict_streams(corrected, context)
    if len(runtime.stream_ids) != 152 or set(streams) != set(runtime.stream_ids):
        raise RuntimeError("DECLARED_152_STREAMS_REQUIRED")
    old_coverage = pd.read_csv(old_out / "STREAM_COVERAGE.csv").set_index("stream_id")
    d, n = len(prepared.market.dates), len(prepared.market.tickers)
    cube = np.full((d, len(runtime.stream_ids), n), np.nan, dtype=np.float64)
    ri = frame.signal_date.map(prepared.date_index).to_numpy(int)
    ci = frame.ticker.map(prepared.ticker_index).to_numpy(int)
    stream_frame = corrected[KEYS].copy()
    records = []
    for k, key in enumerate(runtime.stream_ids):
        values = np.asarray(streams[key], dtype=np.float64)
        if values.shape != (len(frame),) or np.isinf(values).any():
            raise RuntimeError("INVALID_FROZEN_FUSION_OUTPUT")
        available = bool(np.isfinite(values).all())
        status = "AVAILABLE" if available else "FAILED_MEMBER_OR_CALIBRATION"
        if status != old_coverage.loc[key, "status"]:
            raise RuntimeError("OLD_FAILURE_SET_MUST_BE_PRESERVED")
        cube[ri, k, ci] = values
        stream_frame[key] = values
        records.append({"stream_id": key, "status": status,
            "predictable_rows": int(np.isfinite(values).sum()), "candidate_context_rows": len(values),
            "failure": str(runtime.failures.get(key, ""))})
    counts = Counter(r["status"] for r in records)
    if counts != {"AVAILABLE": 129, "FAILED_MEMBER_OR_CALIBRATION": 23}:
        raise RuntimeError("DECLARED_STREAM_COVERAGE_CHANGED")
    out.mkdir(parents=True)
    corrected.to_parquet(out / "calibrated.parquet", index=False)
    stream_frame.to_parquet(out / "streams.parquet", index=False)
    np.savez_compressed(out / "forecast_cube.npz", mu=cube,
        stream_ids=np.asarray(runtime.stream_ids), dates=prepared.market.dates.to_numpy(), tickers=prepared.market.tickers)
    pd.DataFrame(records).to_csv(out / "STREAM_COVERAGE.csv", index=False)
    risk_source = {"path": str(risk_path.resolve()), "sha256": old_receipt["artifacts"]["risk_cache.npz"],
                   "copied": False, "recomputed": False}
    _immutable_json(out / "RISK_CACHE_SOURCE.json", risk_source)
    receipt = {"status": "COMPLETE", "year": year, "stage": stage,
        "fit_calls": 0, "fit_2026_rows": 0, "base_model_inference_calls": 0,
        "delta_decimal": delta, "context_rows": len(frame), "stream_counts": dict(counts),
        "streams": records, "RISK_CACHE_SOURCE": risk_source,
        "baseline_sha256": sha(ROOT / "BASELINE_CORRECTION.json"),
        "source_calibrated": {"path": str(calibrated_path), "sha256": old_receipt["artifacts"]["calibrated.parquet"]},
        "source_evaluation_receipt_sha256": sha(old_out / "COMPLETE.json"),
        "original_pool_formal_status": old_receipt["original_pool_formal_status"],
        "old_learned_artifacts_unchanged": True, "risk_reused_as_absolute_reference": True,
        "cooperation_interpretation": "frozen trained fusion response to one declared common input-intercept shift; no new fusion fit",
        "artifacts": {p.name: sha(p) for p in out.iterdir() if p.is_file()}}
    if year == 2026:
        _verify_new_freeze()
    _immutable_json(out / "COMPLETE.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--year", type=int, choices=[2025, 2026])
    args = parser.parse_args()
    if args.prepare == (args.year is not None):
        parser.error("choose exactly one of --prepare or --year")
    result = prepare_baseline() if args.prepare else make_predictions(args.year)
    print(json.dumps({"status": result["status"], "delta_decimal": result.get("delta_decimal"),
                      "fit_calls": result["fit_calls"]}, ensure_ascii=False), flush=True)
