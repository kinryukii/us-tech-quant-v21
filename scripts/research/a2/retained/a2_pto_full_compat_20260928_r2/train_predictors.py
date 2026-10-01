"""Train all predeclared predictors using physically isolated pre-2026 data."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
import traceback

import joblib
import numpy as np
import pandas as pd

from shared import ROOT, PRE_PANEL, FEATURES, STAGES, SEED, fit_frame, read_json, write_json, sha
from predictors import (NAMES, POINT_NAMES, PROBABILITY_NAMES, QUANTILE_NAMES,
                        DISTRIBUTION_NAMES, RANK_NAMES, RUNTIME, hyperparameters, fit, predict_raw)

MODEL_ROOT = ROOT / "models"
PREDICTION_ROOT = ROOT / "predictions"
OOF_WINDOWS = {"inner": ("2023H2", "2023-07-01", "2024-01-01"),
               "early": ("2024", "2024-01-01", "2025-01-01"),
               "validation": ("2025", "2025-01-01", "2026-01-01")}


def output_columns(name):
    if name in PROBABILITY_NAMES: return ["p"]
    if name in QUANTILE_NAMES: return ["q10", "q50", "q90"]
    if name in DISTRIBUTION_NAMES: return ["location", "scale"] + (["raw_log_scale"] if name == "cat_uncertainty" else [])
    if name in RANK_NAMES: return ["rank"]
    return ["raw"]


def load_stage_status(stage):
    directory = MODEL_ROOT / stage
    path = directory / "FIT_STATUS.json"
    return read_json(path) if path.exists() else None


def update_batch_status():
    stages = {stage: load_stage_status(stage) for stage in STAGES}
    complete = all(value is not None and value.get("complete") for value in stages.values())
    failed = [{"stage": stage, "name": record["name"], "failure": record.get("failure")}
              for stage, value in stages.items() if value is not None
              for record in value.get("fits", []) if record.get("status") == "FAILED"]
    write_json(ROOT / "PREDICTOR_FIT_STATUS.json", {
        "status": "COMPLETE_WITH_FAILURES" if complete and failed else "COMPLETE" if complete else "RUNNING",
        "logical_specifications": 31, "physical_specifications_per_stage": 43,
        "stages": list(STAGES), "scheduled_physical_fits": 172, "fit_2026_rows": 0,
        "hyperparameter_searches": 0, "seed": SEED, "failures": failed,
        "stage_status": {stage: value["status"] if value else "NOT_STARTED" for stage, value in stages.items()},
        "logical_completed": sum(len(value.get("fits", [])) for value in stages.values() if value),
        "physical_completed": sum(sum(len(r.get("physical_fit_records", [])) for r in value.get("fits", [])) + len(value.get("active_physical_fit_records", [])) for value in stages.values() if value),
        "physical_successful": sum(sum(sum(h["status"] == "TRAINED" for h in r.get("physical_fit_records", [])) for r in value.get("fits", [])) for value in stages.values() if value),
        "physical_failed": sum(sum(sum(h["status"] == "FAILED" for h in r.get("physical_fit_records", [])) for r in value.get("fits", [])) for value in stages.values() if value),
        "runtime": RUNTIME})


def train_stage(stage):
    if stage not in STAGES: raise ValueError(f"UNKNOWN_STAGE:{stage}")
    directory = MODEL_ROOT / stage
    directory.mkdir(parents=True, exist_ok=True)
    frame, keys = fit_frame(stage)
    if frame.empty: raise RuntimeError(f"EMPTY_TRAIN_STAGE:{stage}")
    if not frame.label_end_date.lt(STAGES[stage]).all() or not frame.signal_date.lt(STAGES[stage]).all():
        raise RuntimeError("TRAIN_CLOCK_BOUNDARY")
    key_path = directory / "sample_keys.parquet"
    if key_path.exists():
        old = pd.read_parquet(key_path)
        if not old.equals(keys): raise RuntimeError("TRAIN_SAMPLE_KEYS_CHANGED")
    else:
        keys.to_parquet(key_path, index=False)
    source_hashes = {"pre_panel": sha(PRE_PANEL), "predictors": sha(ROOT / "predictors.py"),
                     "trainer": sha(Path(__file__)), "bootstrap": sha(ROOT / "runtime_bootstrap.py"),
                     "shared": sha(ROOT / "shared.py"), "contract": sha(ROOT / "EXPERIMENT_CONTRACT.md")}
    previous = load_stage_status(stage)
    if previous is not None:
        if previous["source_hashes"] != source_hashes or previous["sample_keys_sha256"] != sha(key_path):
            raise RuntimeError("PRESERVE_FROZEN_TRAINING_CONTRACT")
        receipt = previous
    else:
        receipt = dict(stage=stage, status="RUNNING", complete=False, cutoff_exclusive=STAGES[stage], process_id=os.getpid(),
                       fit_2026_rows=0, test_2026_rows_read=0, rows=len(frame),
                       signal_min=str(frame.signal_date.min()), signal_max=str(frame.signal_date.max()),
                       label_end_max=str(frame.label_end_date.max()), sample_keys_sha256=sha(key_path),
                       sample_keys=str(key_path), source_hashes=source_hashes, feature_order=FEATURES,
                       seed=SEED, scheduled_logical_fits=31, scheduled_physical_fits=43,
                       standardizer_fit_source="exact shared stage sample", target="raw next-open-to-following-open return decimal; no target clipping",
                       fits=[])
    x, y, dates = frame[FEATURES].to_numpy(float), frame.y_next_open.to_numpy(float), frame.signal_date.to_numpy()
    existing = {record["name"]: record for record in receipt["fits"]}
    for name in NAMES:
        path = directory / f"{name}.joblib"
        if name in existing:
            old = existing[name]
            if old["status"] == "TRAINED" and (not path.exists() or sha(path) != old["artifact_sha256"]):
                raise RuntimeError(f"FROZEN_MODEL_CHANGED:{stage}:{name}")
            continue
        if path.exists(): raise RuntimeError(f"UNREGISTERED_MODEL_PRESERVE:{stage}:{name}")
        started = time.monotonic()
        partial_path = directory / f"{name}.partial.joblib"
        record = dict(name=name, physical_specs=3 if name in QUANTILE_NAMES else 1,
                      hyperparameters=hyperparameters(name), stage=stage, cutoff_exclusive=STAGES[stage],
                      fit_2026_rows=0, sample_keys_sha256=receipt["sample_keys_sha256"],
                      input_shape=list(x.shape), statistical_outputs=output_columns(name))
        print(json.dumps({"status": "FIT_STARTED", "stage": stage, "name": name, "rows": len(frame)}), flush=True)
        def checkpoint(partial):
            joblib.dump(partial, partial_path, compress=3)
            receipt["active_name"] = name
            receipt["active_partial_artifact"] = str(partial_path)
            receipt["active_partial_sha256"] = sha(partial_path)
            receipt["active_physical_fit_records"] = partial.fit_status
            write_json(directory / "FIT_STATUS.json", receipt)
            update_batch_status()
            print(json.dumps({"status": "PHYSICAL_FIT_CHECKPOINT", "stage": stage, "name": name,
                              "completed_heads": len(partial.fit_status),
                              "head_status": partial.fit_status[-1]["status"]}), flush=True)
        try:
            partial = None
            if partial_path.exists():
                if receipt.get("active_name") != name or receipt.get("active_partial_sha256") != sha(partial_path):
                    raise RuntimeError("UNREGISTERED_PARTIAL_PRESERVE")
                partial = joblib.load(partial_path)
            model = fit(name, x, y, dates, checkpoint=checkpoint, resume=partial)
            record["physical_fit_records"] = model.fit_status
            failed_heads = [head for head in model.fit_status if head["status"] != "TRAINED"]
            if failed_heads:
                failed_path = directory / f"{name}.failed.joblib"
                joblib.dump(model, failed_path, compress=3)
                record["failed_artifact"] = str(failed_path)
                record["failed_artifact_sha256"] = sha(failed_path)
                raise RuntimeError("PHYSICAL_SPEC_FAILED:" + "; ".join(head["failure"]["message"] for head in failed_heads))
            probe = predict_raw(model, x[:256], dates[:256])
            joblib.dump(model, path, compress=3)
            record.update(status="TRAINED", artifact=str(path), artifact_sha256=sha(path),
                          physical_fit_records=model.fit_status,
                          convergence=[r["convergence"] for r in model.fit_status],
                          output_shapes={key: list(value.shape) for key, value in probe.items()},
                          scaler_mean_sha256=__import__("hashlib").sha256(model.scaler.mean_.tobytes()).hexdigest(),
                          scaler_scale_sha256=__import__("hashlib").sha256(model.scaler.scale_.tobytes()).hexdigest())
        except Exception as exc:
            record.update(status="FAILED", failure={"exception": type(exc).__name__, "message": str(exc),
                                                   "traceback": traceback.format_exc()}, convergence="FAILED",
                          output_shapes={}, artifact=None)
        record["seconds"] = time.monotonic()-started
        for key in ("active_name", "active_partial_artifact", "active_partial_sha256", "active_physical_fit_records"):
            receipt.pop(key, None)
        receipt["fits"].append(record)
        write_json(directory / "FIT_STATUS.json", receipt)
        update_batch_status()
        print(json.dumps({"status": record["status"], "stage": stage, "name": name,
                          "seconds": round(record["seconds"], 3), "failure": record.get("failure", {}).get("message")}), flush=True)
    receipt["complete"] = len(receipt["fits"]) == len(NAMES)
    receipt["status"] = "COMPLETE_WITH_FAILURES" if any(r["status"] == "FAILED" for r in receipt["fits"]) else "COMPLETE"
    receipt["physical_specs_completed"] = sum(r["physical_specs"] for r in receipt["fits"])
    write_json(directory / "FIT_STATUS.json", receipt)
    update_batch_status()
    if stage in OOF_WINDOWS: generate_oof(stage)
    return receipt


def generate_oof(stage):
    label, first, cutoff = OOF_WINDOWS[stage]
    status = load_stage_status(stage)
    if status is None or not status["complete"]: raise RuntimeError("BASE_STAGE_NOT_COMPLETE")
    panel = pd.read_parquet(PRE_PANEL)
    if not panel.signal_date.lt("2026-01-01").all(): raise RuntimeError("OOF_SOURCE_CONTAINS_2026")
    keep = panel.signal_date.ge(first) & panel.signal_date.lt(cutoff) & panel.label_available & panel.label_end_date.lt(cutoff)
    keep &= np.isfinite(panel[FEATURES+['y_next_open']].to_numpy(float)).all(axis=1)
    frame = panel.loc[keep].sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    if not frame.signal_date.ge(STAGES[stage]).all(): raise RuntimeError("OOF_BASE_TRAIN_OVERLAP")
    result = frame[["signal_date", "ticker", "y_next_open", "label_end_date"]].copy()
    x, dates = frame[FEATURES].to_numpy(float), frame.signal_date.to_numpy()
    paths = {}
    failures = []
    for record in status["fits"]:
        name = record["name"]
        if record["status"] == "TRAINED":
            path = Path(record["artifact"])
            if sha(path) != record["artifact_sha256"]: raise RuntimeError("OOF_MODEL_HASH_CHANGED")
            raw = predict_raw(joblib.load(path), x, dates)
            paths[name] = record["artifact_sha256"]
            for column, values in raw.items(): result[f"{name}__{column}"] = values
        else:
            failures.append(name)
            for column in output_columns(name): result[f"{name}__{column}"] = np.nan
    PREDICTION_ROOT.mkdir(parents=True, exist_ok=True)
    path = PREDICTION_ROOT / f"raw_oof_{label}.parquet"
    if path.exists():
        old = pd.read_parquet(path)
        if not old.equals(result): raise RuntimeError("PRESERVE_EXISTING_OOF")
    else: result.to_parquet(path, index=False)
    write_json(PREDICTION_ROOT / f"raw_oof_{label}_receipt.json", dict(
        status="COMPLETE_WITH_FAILURES" if failures else "COMPLETE", base_stage=stage,
        base_fit_cutoff_exclusive=STAGES[stage], oof_first=first, oof_last_exclusive=cutoff,
        rows=len(result), stock_dates=len(result), output_shape=list(result.shape),
        signal_min=str(frame.signal_date.min()), signal_max=str(frame.signal_date.max()),
        label_end_max=str(frame.label_end_date.max()), input_sha256=sha(PRE_PANEL),
        artifacts=paths, failed_predictors=failures, file=str(path), sha256=sha(path),
        fit_calls=0, fit_2026_rows=0, read_2026_rows=0, raw_statistical_objects_preserved=True))
    print(json.dumps({"status": "OOF_SAVED", "stage": stage, "rows": len(result), "file": str(path)}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=list(STAGES))
    parser.add_argument("--oof-only", action="store_true")
    args = parser.parse_args()
    for stage in [args.stage] if args.stage else STAGES:
        generate_oof(stage) if args.oof_only else train_stage(stage)


if __name__ == "__main__": main()
