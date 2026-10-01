"""Fit the sealed native roster and produce chronological OOF predictions.

--fit performs no 2026 reads. --resume validates and reuses completed artifacts.
--predict-final requires the root's completed GLOBAL_FREEZE before any 2026 read.
Failures are recorded per member; no implementation is silently substituted.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

sys.dont_write_bytecode = True
import numpy as np
import pandas as pd

from common import ROOT, read, write, sha, clean
import data_contract as dc
import models_native as native

MODELS = ROOT / "models"
PREDICTIONS = ROOT / "predictions/native"
STAGES = {"early": "development", "validation": "validation", "final": "final"}
LOG_FIELDS = ["attempt", "stage", "model_id", "status", "started_utc", "ended_utc", "elapsed_seconds",
    "sample_count", "feature_count", "native_kind", "cutoff_exclusive", "train_signal_min", "train_signal_max",
    "train_label_end_max", "source_sha256", "sample_keys_sha256", "design_sha256", "code_sha256",
    "artifact", "artifact_sha256", "predictive_fit_calls", "statistical_target_heads", "warning_count", "error"]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+f".tmp.{os.getpid()}")
    write(temporary, value)
    os.replace(temporary, path)


def atomic_parquet(path, frame):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+f".tmp.{os.getpid()}")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)


def verify_design():
    contract = read(ROOT / "contract.json")
    lock = read(ROOT / "DESIGN_LOCK.json")
    if lock["contract_sha256"] != sha(ROOT / "contract.json") or lock.get("candidate_change_allowed") is not False:
        raise RuntimeError("NATIVE_DESIGN_LOCK_MISMATCH")
    if tuple(contract["models"]) != native.MODEL_IDS or tuple(contract["features"]) != dc.FEATURES:
        raise RuntimeError("NATIVE_ROSTER_OR_FEATURE_ORDER_MISMATCH")
    if contract["seed"] != native.SEED or contract["training_clip"] != [-.2, .2] or contract["target"] != "y_next_open":
        raise RuntimeError("NATIVE_TARGET_CONTRACT_MISMATCH")
    for stage, data_stage in STAGES.items():
        if contract["stages"][stage] != dc.STAGE_CUTOFFS[data_stage]:
            raise RuntimeError("NATIVE_STAGE_CLOCK_MISMATCH")
    if contract["sampling"]["max_rows"] != dc.MAX_TRAIN_KEYS or not contract["sampling"]["date_balanced"]:
        raise RuntimeError("NATIVE_SAMPLING_CONTRACT_MISMATCH")
    spec = contract["model_specs"]
    if (spec["linear"] != dict(ridge_alpha=10, elastic_alpha=.0001, l1_ratio=.35,
            huber_epsilon=1.35, huber_alpha=.01, huber_max_iter=500)
        or spec["boosted"] != dict(iterations=100, depth=3, leaves=15, min_leaf=100,
            l2=5, lr=.05, early_stopping=False)
        or spec["randomized_trees"] != dict(trees=100, depth=6, min_leaf=40)
        or spec["mlp"] != dict(hidden=[32, 16], epochs=20, early_stopping=False)
        or spec["torch"] != dict(epochs=12, batch=512, resnet_width=32, resnet_blocks=2,
            ft_token_dim=8, ft_heads=2, ft_layers=2)
        or spec["quantiles"] != [.1, .5, .9]
        or spec["ngboost"] != dict(iterations=100, depth=3, distribution="Normal")):
        raise RuntimeError("NATIVE_IMPLEMENTATION_SPEC_MISMATCH")
    ebm = native.specs()["ebm"]
    if any(ebm[k] != v for k, v in spec["ebm"].items()):
        raise RuntimeError("NATIVE_EBM_SPEC_MISMATCH")
    return contract, lock


def sealed_source_sha(path):
    """Keep the original learning lineage after a separately audited no-fit gate.

    Exact live and baseline source hashes must both match the recorded amendment.
    GLOBAL_FREEZE binds the actual current runtime files and this amendment too.
    """
    path = Path(path).resolve()
    current = sha(path)
    amendment_path = MODELS / "ZERO_FIT_GATE_AMENDMENT.json"
    if not amendment_path.exists():
        return current
    amendment = read(amendment_path)
    record = amendment["source_changes"].get(path.name)
    if record is None:
        return current
    if (amendment["new_fit_calls"] != 0 or amendment["learning_functions_unchanged"] is not True
        or current != record["after_sha256"]
        or sha(ROOT / record["before_snapshot"]) != record["before_sha256"]):
        raise RuntimeError("ZERO_FIT_GATE_AMENDMENT_SOURCE_DRIFT")
    return record["before_sha256"]


def implementation_lock():
    contract, lock = verify_design()
    paths = [ROOT / "models_native.py", Path(__file__).resolve(), ROOT / "data_contract.py",
             ROOT / "input/pre2026.parquet", ROOT / "INPUT_AUDIT.json"]
    source = {str(path): sealed_source_sha(path) for path in paths}
    keys = {stage: sha(ROOT / f"input/stage_{data_stage}_keys.parquet") for stage, data_stage in STAGES.items()}
    payload = dict(status="SEALED_BEFORE_NATIVE_REAL_FITS", design_sha256=lock["contract_sha256"],
        source_sha256=source, sample_keys_sha256=keys, specifications=native.specs(),
        models=list(native.MODEL_IDS), stages=contract["stages"], training_2026_rows=0,
        training_target="clipped next-open return, not action utility", created_utc=utc_now())
    path = MODELS / "IMPLEMENTATION_LOCK.json"
    if path.exists():
        old = read(path)
        for key in ["design_sha256", "source_sha256", "sample_keys_sha256", "specifications", "models", "stages"]:
            if old[key] != clean(payload[key]):
                raise RuntimeError(f"NATIVE_FROZEN_IMPLEMENTATION_DRIFT:{key}")
        return old
    atomic_json(path, payload)
    return payload


def append_log(row):
    """Independent stage journals avoid interleaved concurrent CSV writes."""
    path = MODELS / row["stage"] / "FIT_LOG.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({key: clean(row.get(key)) for key in LOG_FIELDS})
        stream.flush()


def consolidate():
    rows = []
    receipts = []
    for stage in STAGES:
        path = MODELS / stage / "FIT_LOG.csv"
        if path.exists():
            with path.open(encoding="utf-8", newline="") as stream:
                rows.extend(csv.DictReader(stream))
        for provider in native.MODEL_IDS:
            receipt = MODELS / stage / f"{provider}_FIT_RECEIPT.json"
            if receipt.exists():
                receipts.append(read(receipt))
    if rows:
        frame = pd.DataFrame(rows).sort_values(["stage", "started_utc", "model_id"])
        temporary = ROOT / f"FIT_LOG.csv.tmp.{os.getpid()}"
        frame.to_csv(temporary, index=False)
        os.replace(temporary, ROOT / "FIT_LOG.csv")
    passed = [r for r in receipts if r["status"] == "PASS"]
    failed = [r for r in receipts if r["status"] != "PASS"]
    summary = dict(status="PASS" if len(passed) == 93 else "PARTIAL_OR_FAILURE", expected_output_specs=93,
        completed_specs=len(passed), failed_specs=len(failed),
        predictive_fit_calls=sum(r.get("predictive_fit_calls", 0) for r in passed),
        statistical_target_heads=sum(r.get("statistical_target_heads", 0) for r in passed),
        stage_counts={stage: sum(r["stage"] == stage for r in passed) for stage in STAGES},
        no_2026_training=True, final_2026_predictions_not_created_by_fit=True,
        completed_artifacts={r["artifact"]: r["artifact_sha256"] for r in passed},
        failures=[dict(stage=r["stage"], model_id=r["model_id"], error=r.get("error")) for r in failed],
        receipt_paths=[str(MODELS / r["stage"] / f"{r['model_id']}_FIT_RECEIPT.json") for r in receipts],
        updated_utc=utc_now())
    atomic_json(MODELS / "TRAIN_RECEIPT.json", summary)
    return summary


def load_rank_relevance(stage, frame):
    # Compute quintiles on the full mature candidate cross-section, before sampling.
    full = pd.read_parquet(ROOT / "input/pre2026.parquet",
        columns=[*dc.KEY, "execution_date", "label_end_date", "label_available", "y_next_open"])
    cutoff = dc.STAGE_CUTOFFS[STAGES[stage]]
    full = full.loc[dc.maturity_mask(full, cutoff)].copy()
    full["relevance"] = native.relevance_for_dates(full.y_next_open, full.signal_date)
    joined = frame[dc.KEY].merge(full[[*dc.KEY, "relevance"]], on=dc.KEY, how="left", validate="one_to_one")
    if joined.relevance.isna().any():
        raise RuntimeError("RANK_FULL_STAGE_RELEVANCE_KEY_MISSING")
    return joined.relevance.to_numpy(np.int32)


def inference_frame(stage):
    if stage not in ("early", "validation"):
        raise ValueError("FIT_COMMAND_CANNOT_READ_FINAL_2026_INPUTS")
    year = 2024 if stage == "early" else 2025
    frame = dc.load_oof_frame(year, mature_only=False)
    # Labels never reach predictor inference, even though retained for later OOF supervision.
    return frame[[*dc.KEY, *dc.FEATURES]].copy()


def predict_member(stage, provider, frame, *, resume=False, global_freeze=None):
    path = PREDICTIONS / stage / f"{provider}.parquet"
    receipt_path = PREDICTIONS / stage / f"{provider}_PREDICT_RECEIPT.json"
    model_path = MODELS / stage / f"{provider}.joblib"
    fitted = read(MODELS / stage / f"{provider}_FIT_RECEIPT.json")
    if fitted["status"] != "PASS" or sha(model_path) != fitted["artifact_sha256"]:
        raise RuntimeError(f"NATIVE_MODEL_NOT_FROZEN_OR_MISSING:{stage}:{provider}")
    if path.exists() or receipt_path.exists():
        if not resume or not (path.exists() and receipt_path.exists()):
            raise FileExistsError(f"PRESERVE_EXISTING_NATIVE_PREDICTIONS:{stage}:{provider}")
        receipt = read(receipt_path)
        if receipt["model_sha256"] != fitted["artifact_sha256"] or receipt["predictions_sha256"] != sha(path):
            raise RuntimeError("NATIVE_RESUME_PREDICTION_HASH_MISMATCH")
        saved = pd.read_parquet(path, columns=dc.KEY)
        pd.testing.assert_frame_equal(saved.reset_index(drop=True), frame[dc.KEY].reset_index(drop=True))
        return receipt
    if stage == "final":
        # Both final entry points use the previously audited saved-forest policy.
        from predict_saved import deterministic_load
        bundle = deterministic_load(model_path)
    else:
        bundle = native.NativeBundle.load(model_path)
    started = time.monotonic()
    output = bundle.predict(frame)
    output = pd.concat([frame[dc.KEY].reset_index(drop=True), output], axis=1)
    output["provider"] = provider
    output["native_kind"] = native.kind_for(provider)
    output["base_cutoff"] = pd.Timestamp(fitted["cutoff_exclusive"])
    output["prediction_id"] = [hashlib.sha256(f"{stage}|{provider}|{d.date()}|{t}".encode()).hexdigest()
                               for d, t in frame[dc.KEY].itertuples(index=False, name=None)]
    if not output.signal_date.ge(output.base_cutoff).all() or output.duplicated(dc.KEY).any():
        raise RuntimeError("NATIVE_OOF_PREDICTION_TIME_OR_KEYS_FAILURE")
    atomic_parquet(path, output)
    receipt = dict(status="PASS", stage=stage, provider=provider, rows=len(output),
        full_inference_keys_preserved=True, labels_used_in_inference=False, adapter_refit=False,
        model_sha256=fitted["artifact_sha256"], predictions_sha256=sha(path),
        elapsed_seconds=time.monotonic()-started, signal_min=str(frame.signal_date.min().date()),
        signal_max=str(frame.signal_date.max().date()), base_cutoff=fitted["cutoff_exclusive"],
        output_semantics=native.specs()["adapters"], global_freeze_sha256=global_freeze,
        inference_jobs_override=1 if stage == "final" and provider in ("rf", "extra", "rf_cls") else None,
        created_utc=utc_now())
    atomic_json(receipt_path, receipt)
    print(json.dumps(dict(event="PREDICT_PASS", stage=stage, model_id=provider, rows=len(output),
                         seconds=receipt["elapsed_seconds"])), flush=True)
    return receipt


def fit_stage(stage, implementation, *, resume=False):
    if stage not in STAGES:
        raise ValueError("UNKNOWN_NATIVE_STAGE")
    frame = dc.stage_frame(STAGES[stage])
    relevance = load_rank_relevance(stage, frame)
    forecast_frame = inference_frame(stage) if stage != "final" else None
    folder = MODELS / stage
    folder.mkdir(parents=True, exist_ok=True)
    cutoff = dc.STAGE_CUTOFFS[STAGES[stage]]
    for provider in native.MODEL_IDS:
        artifact = folder / f"{provider}.joblib"
        receipt_path = folder / f"{provider}_FIT_RECEIPT.json"
        if artifact.exists() or receipt_path.exists():
            if not resume:
                raise FileExistsError(f"PRESERVE_EXISTING_NATIVE_MEMBER:{stage}:{provider}")
            if receipt_path.exists():
                old = read(receipt_path)
                if old["status"] != "PASS":
                    print(json.dumps(dict(event="SAVED_FAILURE_PRESERVED", stage=stage, model_id=provider,
                                          error=old.get("error"))), flush=True)
                    continue
                if not artifact.exists() or sha(artifact) != old["artifact_sha256"]:
                    raise RuntimeError("NATIVE_RESUME_ARTIFACT_HASH_MISMATCH")
                if old["implementation_lock_sha256"] != sha(MODELS / "IMPLEMENTATION_LOCK.json"):
                    raise RuntimeError("NATIVE_RESUME_IMPLEMENTATION_LOCK_MISMATCH")
                if forecast_frame is not None:
                    predict_member(stage, provider, forecast_frame, resume=True)
                print(json.dumps(dict(event="FIT_REUSE_PASS", stage=stage, model_id=provider)), flush=True)
                continue
            raise RuntimeError("ORPHAN_NATIVE_ARTIFACT_REQUIRES_AUDIT_NOT_REFIT")
        started_utc, timer = utc_now(), time.monotonic()
        kind = native.kind_for(provider)
        row = dict(attempt=1, stage=stage, model_id=provider, started_utc=started_utc,
            sample_count=len(frame), feature_count=len(dc.FEATURES), native_kind=kind,
            cutoff_exclusive=cutoff, train_signal_min=str(frame.signal_date.min().date()),
            train_signal_max=str(frame.signal_date.max().date()), train_label_end_max=str(frame.label_end_date.max().date()),
            source_sha256=implementation["source_sha256"][str(ROOT / "input/pre2026.parquet")],
            sample_keys_sha256=implementation["sample_keys_sha256"][stage],
            design_sha256=implementation["design_sha256"], code_sha256=sha(ROOT / "models_native.py"),
            artifact=str(artifact), statistical_target_heads=3 if kind == "quantile" else 1)
        print(json.dumps(dict(event="FIT_START", stage=stage, model_id=provider, rows=len(frame))), flush=True)
        try:
            bundle = native.NativeBundle.fit(provider, frame, frame.y_train.to_numpy(float),
                frame.sample_weight.to_numpy(float), list(dc.FEATURES),
                rank_relevance=relevance, dates=frame.signal_date)
            bundle.fit_receipt.update(row)
            temporary = artifact.with_name(artifact.name+f".tmp.{os.getpid()}")
            bundle.save(temporary)
            os.replace(temporary, artifact)
            # Restoration is checked on features only; never add another fit.
            original = bundle.predict(frame.iloc[:64])
            restored = native.NativeBundle.load(artifact).predict(frame.iloc[:64])
            pd.testing.assert_frame_equal(original, restored, check_exact=True)
            row.update(status="PASS", artifact_sha256=sha(artifact),
                predictive_fit_calls=bundle.fit_receipt["fit_calls"],
                warning_count=len(bundle.fit_receipt["warnings"]), error=None)
            receipt = dict(**row, fit_details=bundle.fit_receipt,
                implementation_lock_sha256=sha(MODELS / "IMPLEMENTATION_LOCK.json"),
                restoration_predictions_exact=True, restoration_rows=64,
                rank_relevance_scope="full mature stage candidate pool before frozen key sampling" if kind == "rank" else None,
                scaler_fit_calls=1 if bundle.scaler is not None else 0,
                adapter_fit_calls=1 if kind == "rank" else 0, no_2026_training=True)
        except Exception as exc:
            row.update(status="FAILED", artifact_sha256=sha(artifact) if artifact.exists() else None,
                predictive_fit_calls=None, warning_count=None, error=f"{type(exc).__name__}: {exc}")
            receipt = dict(**row, traceback=traceback.format_exc(), implementation_lock_sha256=sha(MODELS / "IMPLEMENTATION_LOCK.json"),
                           no_substitution=True, no_2026_training=True)
        row.update(ended_utc=utc_now(), elapsed_seconds=time.monotonic()-timer)
        receipt.update(ended_utc=row["ended_utc"], elapsed_seconds=row["elapsed_seconds"])
        atomic_json(receipt_path, receipt)
        append_log(row)
        print(json.dumps(dict(event="FIT_"+row["status"], stage=stage, model_id=provider,
                             seconds=row["elapsed_seconds"], error=row["error"])), flush=True)
        if row["status"] == "PASS" and forecast_frame is not None:
            try:
                predict_member(stage, provider, forecast_frame, resume=resume)
            except Exception as exc:
                atomic_json(PREDICTIONS / stage / f"{provider}_PREDICT_FAILURE.json",
                    dict(status="FAILED", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc(), created_utc=utc_now()))
                print(json.dumps(dict(event="PREDICT_FAILED", stage=stage, model_id=provider, error=str(exc))), flush=True)
    return consolidate()


def predict_final(*, resume=False):
    verify_design()
    freeze = ROOT / "GLOBAL_FREEZE.json"
    if not freeze.exists():
        raise RuntimeError("GLOBAL_FREEZE_REQUIRED_BEFORE_ANY_2026_READ")
    from freeze_batch import validate_global_freeze
    validate_global_freeze()
    implementation_lock()
    # Read only the feature snapshot, not prices, labels, accounts or strategy results.
    frame = pd.read_parquet(ROOT / "input/eval_2026/features.parquet", columns=[*dc.KEY, *dc.FEATURES])
    frame = frame.sort_values(dc.KEY, kind="stable").reset_index(drop=True)
    if not frame.signal_date.dt.year.eq(2026).all():
        raise RuntimeError("FINAL_INFERENCE_YEAR_MISMATCH")
    outputs = []
    for provider in native.MODEL_IDS:
        outputs.append(predict_member("final", provider, frame, resume=resume, global_freeze=sha(freeze)))
    atomic_json(PREDICTIONS / "final/PREDICTION_RECEIPT.json",
        dict(status="PASS", providers=len(outputs), rows_per_provider=len(frame),
             global_freeze_sha256=sha(freeze), outputs=outputs, no_fit=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fit", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--predict-final", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stage", choices=list(STAGES)+["all"], default="all")
    parser.add_argument("--consolidate", action="store_true")
    args = parser.parse_args()
    if args.predict_final:
        predict_final(resume=args.resume)
    elif args.fit or args.prepare:
        lock = implementation_lock()
        if args.fit:
            test_receipt = ROOT / "models/NATIVE_TEST_RECEIPT.json"
            if not test_receipt.exists() or read(test_receipt).get("status") != "PASS":
                raise RuntimeError("NATIVE_SYNTHETIC_TEST_PASS_REQUIRED_BEFORE_REAL_FITS")
            for stage in STAGES if args.stage == "all" else [args.stage]:
                fit_stage(stage, lock, resume=args.resume)
    elif args.consolidate:
        print(json.dumps(consolidate(), default=str), flush=True)
    else:
        parser.error("choose --prepare, --fit, --predict-final or --consolidate")


if __name__ == "__main__":
    main()
