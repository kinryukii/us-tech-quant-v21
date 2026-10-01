"""Rebuild the authorized fixed annual A2 models; never fit on 2026 data.

The original annual binaries were not persisted. This helper preserves the
frozen inputs and fit specification and writes new, explicitly identified
artifacts. It does not calculate outcomes, select parameters, download inputs,
or claim prediction equivalence to the original OOF records.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import sklearn
from threadpoolctl import threadpool_limits


FREEZE_SHA = "398cff8076f8c761d87c12ce195ba98e9201209499caaaf7a14ae05ac1605125"
SOURCE_SHA = "fd4fe78d27bfbf57c89343d60550366ccf7fcbf3d6a65e7ef66f28405d050c19"
PARAMS_SOURCE_SHA = "75f332d09c76e4d4019a85e2a1afd514e2fb6649debfd9cd1ed9414c44c201bb"
FULL_MODEL_SHA = "4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b"
CUTOFF = pd.Timestamp("2026-01-01")


class ModelContractError(ValueError):
    pass


def _require(condition, code):
    if not condition:
        raise ModelContractError(code)


def _digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _verify(path, expected):
    path = Path(path)
    _require(path.is_file() and _digest(path) == expected, f"SOURCE_HASH_MISMATCH:{path.name}")
    return path


def _references(paths):
    baseline = paths.results_root / "A_VS_A2_QUARTERLY_13F_R1"
    return {
        "freeze": baseline / "audit/freeze_r1/frozen_baseline_manifest.json", "freeze_sha256": FREEZE_SHA,
        "training": baseline / "A2/training_matrix.parquet",
        "source": paths.repo_root / "scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py",
        "source_sha256": SOURCE_SHA,
        "params_source": paths.backtest_root / "research/a2/demo_2026_calendar_replay/source_snapshot/abcde_a2_nonlinear_alpha_baseline_r1.py",
        "params_source_sha256": PARAMS_SOURCE_SHA,
        "full_model": baseline / "A2/final_full_pre2026_hgb.joblib", "full_model_sha256": FULL_MODEL_SHA,
    }


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    _require(spec is not None and spec.loader is not None, "SOURCE_IMPORT_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _safe_output(paths, output_dir, refs):
    output_dir = Path(output_dir).resolve()
    roots = [Path(getattr(paths, key)).resolve() for key in ("backtest_root", "daily_root", "cache_root", "results_root")]
    _require(any(root in output_dir.parents for root in roots), "MODEL_OUTPUT_MUST_USE_EXTERNAL_RUN_DIRECTORY")
    frozen_root = Path(refs["training"]).resolve().parent.parent
    _require(output_dir != frozen_root and frozen_root not in output_dir.parents, "FROZEN_OUTPUT_FORBIDDEN")
    _require(not output_dir.is_symlink(), "MODEL_OUTPUT_SYMLINK_FORBIDDEN")
    return output_dir / "models"


def _date_index(training_path, features, expected_rows):
    """Prove the source is entirely pre-2026 before reading even training labels."""
    parquet = pq.ParquetFile(training_path)
    required = {"signal_date", "ticker", "target", "target_end_date", *features}
    columns = parquet.schema_arrow.names
    _require(required <= set(columns), "TRAINING_COLUMNS_MISSING")
    _require(parquet.metadata.num_rows == expected_rows, "TRAINING_TOTAL_ROW_COUNT_MISMATCH")
    for name in ("signal_date", "target_end_date"):
        position = columns.index(name)
        for number in range(parquet.metadata.num_row_groups):
            stats = parquet.metadata.row_group(number).column(position).statistics
            _require(stats is not None and stats.has_min_max and stats.null_count == 0, "TRAINING_DATE_BOUNDARY_UNPROVEN")
            _require(pd.Timestamp(stats.max) < CUTOFF, "TRAINING_2026_DATE_FORBIDDEN")
    index = parquet.read(columns=["signal_date", "ticker", "target_end_date"]).to_pandas()
    _require(not index.duplicated(["signal_date", "ticker"]).any(), "TRAINING_IDENTITY_DUPLICATE")
    for column in ("signal_date", "target_end_date"):
        index[column] = pd.to_datetime(index[column])
    _require(index.target_end_date.ge(index.signal_date).all(), "TRAINING_LABEL_PRECEDES_SIGNAL")
    return index


def _fold_info(index, vintage):
    year = int(vintage["year"])
    first = pd.Timestamp(vintage["prediction_min_date"])
    _require(year in (2023, 2024, 2025) and first.year == year, "INVALID_ANNUAL_VINTAGE")
    mask = index.signal_date.lt(pd.Timestamp(f"{year}-01-01")) & index.target_end_date.lt(first)
    part = index.loc[mask]
    _require(len(part) == int(vintage["training_row_count"]) and not part.empty, f"FOLD_ROW_COUNT_MISMATCH:{year}")
    info = {"train_start": str(part.signal_date.min().date()), "train_end": str(part.signal_date.max().date()),
            "labelmax": str(part.target_end_date.max().date()), "training_row_count": len(part),
            "prediction_min_date": str(first.date()), "year": year}
    _require(info["train_end"] == vintage["train_max_date"] and info["labelmax"] == vintage["train_target_end_max"],
             f"FOLD_CUTOFF_MISMATCH:{year}")
    _require(pd.Timestamp(info["train_end"]) < pd.Timestamp(f"{year}-01-01")
             and pd.Timestamp(info["labelmax"]) < first and pd.Timestamp(info["labelmax"]) < CUTOFF,
             f"FOLD_MATURITY_VIOLATION:{year}")
    return mask, info


def _read_resume(manifest_path, contract):
    if not manifest_path.exists():
        return None
    record = json.loads(manifest_path.read_text(encoding="utf-8"))
    fingerprint = record.pop("manifest_fingerprint", None)
    _require(fingerprint == _fingerprint(record), "MODEL_MANIFEST_FINGERPRINT_MISMATCH")
    _require(record.get("contract") == contract, "MODEL_RESUME_CONTRACT_MISMATCH")
    model_path = Path(record["artifact"]["path"])
    _require(model_path.resolve().parent == manifest_path.parent.resolve(), "MODEL_RESUME_PATH_MISMATCH")
    _verify(model_path, record["artifact"]["sha256"])
    return {**record["artifact"], "status": "REUSED", "manifest_path": str(manifest_path),
            "manifest_sha256": _digest(manifest_path), "manifest_fingerprint": fingerprint}


def _save_model(model, destination, contract):
    manifest_path = destination.with_suffix(".json")
    temporary = destination.with_suffix(".joblib.tmp")
    _require(not any(path.exists() for path in (destination, manifest_path, temporary)), "MODEL_OUTPUT_ALREADY_EXISTS")
    try:
        # Exclusive temporary creation prevents overwriting another incomplete run.
        with temporary.open("xb") as stream:
            joblib.dump(model, stream, compress=3)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    artifact = {"year": contract["year"], "path": str(destination), "sha256": _digest(destination),
                "train_start": contract["train_start"], "train_end": contract["train_end"],
                "labelmax": contract["labelmax"], "training_row_count": contract["training_row_count"],
                "feature_columns": contract["feature_columns"], "model_role": "REBUILT_ANNUAL_OOF_VINTAGE",
                "equivalence_status": "FIXED_SPEC_REBUILT_NOT_PREDICTION_EQUIVALENCE_VERIFIED",
                "lineage": contract["lineage"]}
    record = {"schema": "HISTORICAL_TOP40_MODEL_V1", "created_at": datetime.now(timezone.utc).isoformat(),
              "contract": contract, "artifact": artifact}
    record["manifest_fingerprint"] = _fingerprint(record)
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return {**artifact, "status": "BUILT", "manifest_path": str(manifest_path),
            "manifest_sha256": _digest(manifest_path), "manifest_fingerprint": record["manifest_fingerprint"]}


def build_models(paths, output_dir, years=(2023, 2024, 2025, 2026), execute=False):
    """Plan or materialize fixed annual models; the 2026 model is reference-only.

    Returns ``status``, ``artifacts`` (string year keys), ``feature_columns``,
    ``model_fit_count`` and input lineage. A repeat with identical contracts and
    valid per-model manifests reuses models without fitting. Nothing is written
    by execute=False. No prediction/return data is read in either mode.
    """
    years = tuple(sorted(set(int(year) for year in years)))
    _require(bool(years) and set(years) <= {2023, 2024, 2025, 2026}, "SUPPORTED_YEARS_2023_THROUGH_2026_ONLY")
    refs = _references(paths)
    freeze_path = _verify(refs["freeze"], refs["freeze_sha256"])
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    a2 = freeze["contracts"]["A2"]
    features = list(a2["feature_schema"])
    vintages = {int(row["year"]): row for row in a2["effective_model_vintages"]}
    _require(len(vintages) == 3 and set(vintages) == {2023, 2024, 2025}, "FROZEN_VINTAGE_SET_MISMATCH")
    hashes = {row["full_training_matrix_sha256"] for row in vintages.values()}
    _require(len(hashes) == 1, "TRAINING_HASH_CONFLICT")
    training_hash = next(iter(hashes))
    training_path = _verify(refs["training"], training_hash)
    source_path = _verify(refs["source"], refs["source_sha256"])
    params_path = _verify(refs["params_source"], refs["params_source_sha256"])
    _require(a2["source_fingerprint"] == refs["source_sha256"] and a2["prereg_fingerprint"] == refs["params_source_sha256"],
             "FROZEN_MODEL_SOURCE_BINDING_MISMATCH")
    source = _load_module(source_path, "historical_top40_frozen_features")
    params = _load_module(params_path, "historical_top40_frozen_params")
    _require(list(source.FEATURE_COLUMNS) == features and params.HGB_CONFIG == a2["hyperparameters"], "FROZEN_FEATURE_OR_PARAMS_MISMATCH")
    models_dir = _safe_output(paths, output_dir, refs)
    index = _date_index(training_path, features, int(a2["training_row_count"]))
    _verify(training_path, training_hash)
    lineage = {"freeze_path": str(freeze_path), "freeze_sha256": refs["freeze_sha256"],
               "training_matrix_path": str(training_path), "training_matrix_sha256": training_hash,
               "feature_source_path": str(source_path), "feature_source_sha256": refs["source_sha256"],
               "model_params_source_path": str(params_path), "model_params_source_sha256": refs["params_source_sha256"]}
    runtime = {"python": sys.version.split()[0], "numpy": np.__version__, "sklearn": sklearn.__version__,
               "joblib": joblib.__version__, "threadpool_limit": 1}
    artifacts, pending = {}, {}
    for year in years:
        if year == 2026:
            full = a2["supplemental_full_pre2026_model"]
            _require(full["sha256"] == refs["full_model_sha256"] and full["used_for_frozen_oof_predictions"] is False,
                     "FULL_MODEL_IDENTITY_MISMATCH")
            path = _verify(refs["full_model"], refs["full_model_sha256"])
            artifacts[str(year)] = {"status": "FROZEN_REFERENCE", "year": year, "path": str(path),
                "sha256": refs["full_model_sha256"], "train_start": str(index.signal_date.min().date()),
                "train_end": str(index.signal_date.max().date()), "labelmax": str(index.target_end_date.max().date()),
                "training_row_count": len(index), "feature_columns": features,
                "model_role": "FROZEN_FULL_PRE2026_FOR_2026_INFERENCE_ONLY", "lineage": lineage}
            continue
        mask, info = _fold_info(index, vintages[year])
        contract = {**info, "feature_columns": features, "hyperparameters": a2["hyperparameters"],
                    "original_vintage_fingerprint": vintages[year]["effective_model_vintage_fingerprint"],
                    "original_training_row_identity_sha256": vintages[year]["training_row_identity_sha256"],
                    "original_prediction_behavior_sha256": vintages[year]["prediction_behavior_sha256"],
                    "lineage": lineage, "runtime": runtime}
        destination = models_dir / f"a2_hgb_{year}.joblib"
        resumed = _read_resume(destination.with_suffix(".json"), contract)
        if resumed:
            artifacts[str(year)] = resumed
        else:
            artifacts[str(year)] = {**info, "status": "PLANNED", "path": str(destination), "sha256": None,
                                    "feature_columns": features, "lineage": lineage}
            pending[year] = (mask, contract, destination)
    fitted = 0
    if execute and pending:
        models_dir.mkdir(parents=True, exist_ok=True)
        lock = models_dir / ".build.lock"
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(descriptor)
        try:
            matrix = pq.read_table(training_path, columns=["signal_date", "ticker", *features, "target", "target_end_date"]).to_pandas()
            _verify(training_path, training_hash)
            _require(np.isfinite(matrix[features + ["target"]].to_numpy(float)).all(), "NONFINITE_FROZEN_TRAINING_INPUT")
            for year, (mask, contract, destination) in pending.items():
                # Use the original split implementation, without execute_stage's
                # evaluation metrics and without building or reading 2026 labels.
                training, _, split_audit = source.stage_rows(matrix, year)
                _require(training.index.equals(matrix.loc[mask].index), f"ORIGINAL_STAGE_SPLIT_MISMATCH:{year}")
                _require(int(split_audit["leakage_row_count"]) == 0, f"ORIGINAL_STAGE_LEAKAGE:{year}")
                model = params.make_hgb()
                _require(all(model.get_params().get(key) == value for key, value in params.HGB_CONFIG.items()), "MODEL_CONSTRUCTOR_PARAMS_MISMATCH")
                with threadpool_limits(limits=1):
                    model.fit(training[features].to_numpy(float), training.target.to_numpy(float))
                fitted += 1
                artifacts[str(year)] = _save_model(model, destination, contract)
            _verify(source_path, refs["source_sha256"])
            _verify(params_path, refs["params_source_sha256"])
        finally:
            lock.unlink()
    status = "PLANNED" if any(row["status"] == "PLANNED" for row in artifacts.values()) else "READY"
    return {"status": status, "artifacts": artifacts, "feature_columns": features, "lineage": lineage,
            "model_fit_count": fitted, "model_selection_count": 0, "training_rows_2026_plus": 0}
