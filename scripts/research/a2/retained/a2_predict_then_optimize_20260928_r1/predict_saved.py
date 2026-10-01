"""Zero-fit restoration audit and deterministic saved-forest inference.

The native fitting implementation remains frozen. This patch changes only the
in-memory number of prediction jobs for saved RF/Extra/RF-classifier objects.
Original artifacts and initial failed bitwise audits are retained verbatim.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import time

import numpy as np
import pandas as pd

from common import ROOT, read, sha
import data_contract as dc
import models_native as native
import train_models as trainer

FORESTS = ("rf", "extra", "rf_cls")
ORIGINAL_LOAD = native.NativeBundle.load


def deterministic_load(path):
    bundle = ORIGINAL_LOAD(path)
    if bundle.model_id in FORESTS:
        if not hasattr(bundle.estimator_object, "n_jobs"):
            raise RuntimeError("FOREST_PREDICTION_JOB_CONTROL_MISSING")
        bundle.estimator_object.n_jobs = 1
    return bundle


def patch_binding():
    lock = trainer.implementation_lock()
    payload = dict(status="ZERO_FIT_INFERENCE_REPAIR", implementation_lock_sha256=sha(trainer.MODELS / "IMPLEMENTATION_LOCK.json"),
        fit_code_sha256=lock["source_sha256"][str(ROOT / "models_native.py")],
        inference_patch_sha256=trainer.sealed_source_sha(Path(__file__)), original_artifacts_unchanged=True,
        affected_models=list(FORESTS), training_jobs=2, inference_jobs=1, new_fit_calls=0,
        reason="parallel forest prediction addition order creates floating-point last-bit differences",
        prediction_reduction_policy="native forest predict with n_jobs=1; fixed tree accumulation order")
    path = trainer.MODELS / "INFERENCE_REPAIR_BINDING.json"
    if path.exists() and read(path) != payload:
        raise RuntimeError("FROZEN_INFERENCE_REPAIR_BINDING_DRIFT")
    if not path.exists():
        trainer.atomic_json(path, payload)
    return payload


def repair_stage(stage):
    binding = patch_binding()
    frame = dc.stage_frame(trainer.STAGES[stage])
    audit_frame = frame.iloc[:4096]
    records = []
    for provider in FORESTS:
        receipt_path = trainer.MODELS / stage / f"{provider}_FIT_RECEIPT.json"
        artifact = trainer.MODELS / stage / f"{provider}.joblib"
        if not (receipt_path.exists() and artifact.exists()):
            continue
        old = read(receipt_path)
        audit_path = trainer.MODELS / stage / "restore_audit" / f"{provider}_RESTORE_NUMERIC_AUDIT.json"
        if audit_path.exists():
            audited = read(audit_path)
            if audited["artifact_sha256"] != sha(artifact):
                raise RuntimeError("NUMERIC_AUDIT_ARTIFACT_DRIFT")
            records.append(audited)
            continue
        if sha(artifact) != old["artifact_sha256"]:
            raise RuntimeError("NUMERIC_AUDIT_SAVED_MODEL_HASH_MISMATCH")
        lock = read(trainer.MODELS / "IMPLEMENTATION_LOCK.json")
        if (old["design_sha256"] != lock["design_sha256"]
            or old["source_sha256"] != lock["source_sha256"][str(ROOT / "input/pre2026.parquet")]
            or old["sample_keys_sha256"] != lock["sample_keys_sha256"][stage]):
            raise RuntimeError("NUMERIC_AUDIT_TRAINING_CONTRACT_MISMATCH")
        if old["status"] != "PASS" and not str(old.get("error", "")).startswith("AssertionError: DataFrame"):
            raise RuntimeError("NUMERIC_AUDIT_CANNOT_RECLASSIFY_A_REAL_FIT_FAILURE")
        parallel = ORIGINAL_LOAD(artifact).predict(audit_frame)
        first, second = deterministic_load(artifact), deterministic_load(artifact)
        sequential = first.predict(audit_frame)
        restored = second.predict(audit_frame)
        pd.testing.assert_frame_equal(sequential, restored, check_exact=True)
        delta = parallel.select_dtypes(include="number").to_numpy()-sequential.select_dtypes(include="number").to_numpy()
        finite = delta[np.isfinite(delta)]
        maximum = float(np.max(np.abs(finite))) if len(finite) else 0.
        rms = float(np.sqrt(np.mean(finite**2))) if len(finite) else 0.
        if maximum > 1e-15 or rms > 1e-15:
            raise RuntimeError(f"FOREST_REDUCTION_CHANGE_EXCEEDS_DECLARED_NUMERIC_TOLERANCE:{maximum}")
        initial = trainer.MODELS / stage / "restore_audit" / f"{provider}_INITIAL_RECEIPT.json"
        initial.parent.mkdir(parents=True, exist_ok=True)
        if initial.exists():
            raise FileExistsError("PRESERVE_EXISTING_INITIAL_RESTORE_AUDIT")
        shutil.copyfile(receipt_path, initial)
        detail = first.fit_receipt
        audit = dict(status="RESTORE_NUMERIC_AUDIT_PASS", stage=stage, model_id=provider,
            artifact_sha256=sha(artifact), initial_receipt_path=str(initial), initial_receipt_sha256=sha(initial),
            initial_status=old["status"], rows=len(audit_frame), parallel_vs_sequential_max_absolute_error=maximum,
            parallel_vs_sequential_RMS=rms, declared_tolerance=1e-15,
            sequential_restoration_bitwise_exact=True, fit_calls_performed_by_audit=0,
            actual_original_predictive_fit_calls=detail["fit_calls"],
            implementation_lock_sha256=binding["implementation_lock_sha256"],
            inference_patch_sha256=binding["inference_patch_sha256"], created_utc=trainer.utc_now())
        trainer.atomic_json(audit_path, audit)
        corrected = dict(old)
        corrected.update(status="PASS", error=None, fit_details=detail,
            predictive_fit_calls=detail["fit_calls"], warning_count=len(detail["warnings"]),
            restoration_predictions_exact=True, restoration_rows=len(audit_frame),
            restoration_policy="bitwise exact with native saved forest single-job inference",
            numeric_audit_path=str(audit_path), numeric_audit_sha256=sha(audit_path),
            initial_restore_failure_preserved=str(initial), no_retraining=True)
        trainer.atomic_json(receipt_path, corrected)
        if stage != "final":
            native.NativeBundle.load = staticmethod(deterministic_load)
            trainer.predict_member(stage, provider, trainer.inference_frame(stage), resume=True)
            native.NativeBundle.load = ORIGINAL_LOAD
            prediction_receipt = trainer.PREDICTIONS / stage / f"{provider}_PREDICT_RECEIPT.json"
            predicted = read(prediction_receipt)
            predicted.update(inference_jobs_override=1, inference_patch_sha256=binding["inference_patch_sha256"],
                             adapter_refit=False, model_artifact_unchanged=True)
            trainer.atomic_json(prediction_receipt, predicted)
        records.append(audit)
        print(json.dumps(dict(event="RESTORE_NUMERIC_AUDIT_PASS", stage=stage, model_id=provider,
                             error_max=maximum, no_fit=True)), flush=True)
    trainer.consolidate()
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repair-forests", action="store_true")
    parser.add_argument("--predict-final", action="store_true")
    parser.add_argument("--stage", choices=list(trainer.STAGES)+["all"], default="all")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.repair_forests:
        for stage in trainer.STAGES if args.stage == "all" else [args.stage]:
            repair_stage(stage)
    elif args.predict_final:
        from freeze_batch import validate_global_freeze
        validate_global_freeze()
        binding = patch_binding()
        native.NativeBundle.load = staticmethod(deterministic_load)
        trainer.predict_final(resume=args.resume)
        native.NativeBundle.load = ORIGINAL_LOAD
        trainer.atomic_json(trainer.PREDICTIONS / "final/INFERENCE_REPAIR_RECEIPT.json", binding)
    else:
        parser.error("choose --repair-forests or --predict-final")


if __name__ == "__main__":
    main()
