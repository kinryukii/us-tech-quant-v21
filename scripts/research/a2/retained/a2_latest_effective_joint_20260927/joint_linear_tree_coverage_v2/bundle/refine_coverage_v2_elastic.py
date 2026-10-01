"""Single same-objective numerical continuation for unconverged v2 ElasticNet."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
import warnings

import joblib
import numpy as np
from sklearn.metrics import mean_squared_error
from threadpoolctl import threadpool_limits

import joint_linear_tree as original
import retrain_coverage_v2 as v2


CONTRACT = v2.OUT / "ELASTIC_REPAIR_PRE_FIT_CONTRACT.json"
BACKUP = v2.OUT / "FIT_RECEIPT_BEFORE_NUMERICAL_REPAIR.json"
PARTIAL = v2.OUT / "ELASTIC_REPAIR.partial.json"


def prepare():
    if CONTRACT.exists() or BACKUP.exists() or PARTIAL.exists():
        raise RuntimeError("REPAIR_PREP_ALREADY_EXISTS")
    receipt_path = v2.OUT / "FIT_RECEIPT.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "PASS" and receipt["fit_calls"] == 14
    pending = [r["stage"] for r in receipt["fits"] if r["name"] == "elastic_net" and not r["converged"]]
    assert pending == ["validation", "final"], pending
    original_hash = v2.sha(receipt_path)
    BACKUP.write_bytes(receipt_path.read_bytes())
    contract = {"status": "PRE_REPAIR_LOCKED", "reason": "ConvergenceWarning only; no objective, labels, samples, alpha or l1_ratio change",
                "main_fit_receipt_sha256": original_hash,
                "main_pre_fit_contract_sha256": v2.sha(v2.OUT / "PRE_FIT_CONTRACT.json"),
                "source_sha256": v2.sha(v2.DATA),
                "repair_code_sha256": v2.sha(Path(__file__)),
                "original_training_code_sha256": v2.sha(v2.BUNDLE / "retrain_coverage_v2.py"),
                "stages": pending, "precompute_gram": True, "warm_start": True,
                "extra_max_iterations": 25000,
                "maximum_attempts_per_stage": 1,
                "alpha": original.SPECS["elastic_net"]["alpha"],
                "l1_ratio": original.SPECS["elastic_net"]["l1_ratio"],
                "test2026_data_mounted": False}
    v2.write(CONTRACT, contract)
    print(json.dumps({"status": contract["status"], "stages": pending,
                      "main_receipt_sha256": original_hash}), flush=True)


def run():
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if contract["status"] != "PRE_REPAIR_LOCKED":
        raise RuntimeError("NO_REPAIR_LOCK")
    if v2.sha(v2.DATA) != contract["source_sha256"] or v2.sha(Path(__file__)) != contract["repair_code_sha256"]:
        raise RuntimeError("REPAIR_CODE_OR_INPUT_CHANGED")
    if v2.sha(BACKUP) != contract["main_fit_receipt_sha256"]:
        raise RuntimeError("MAIN_RECEIPT_BACKUP_CHANGED")
    main = json.loads(BACKUP.read_text(encoding="utf-8"))
    if PARTIAL.exists():
        repairs = json.loads(PARTIAL.read_text(encoding="utf-8"))
    else:
        repairs = []
    done = {r["stage"] for r in repairs}
    frame = v2.read_frame()
    for stage in contract["stages"]:
        if stage in done:
            continue
        record = next(r for r in main["fits"] if r["stage"] == stage and r["name"] == "elastic_net")
        artifact = v2.OUT / Path(record["artifact"]).name
        if v2.sha(artifact) != record["artifact_sha256"]:
            raise RuntimeError("ORIGINAL_V2_MODEL_CHANGED")
        sample, keys, audit = v2.sample(frame, v2.STAGES[stage])
        saved_keys = v2.OUT / f"sample_keys_{stage}.parquet"
        if v2.sha(saved_keys) != main["stages"][stage]["sample_keys_sha256"]:
            raise RuntimeError("REPAIR_SAMPLE_KEYS_CHANGED")
        if audit["counterfactual_rows"] != record["train_rows"]:
            raise RuntimeError("REPAIR_SAMPLE_COUNT_CHANGED")
        x, y, _ = original.counterfactual(sample, robust_training=True)
        pipeline = joblib.load(artifact)
        model = pipeline[-1]
        assert model.alpha == contract["alpha"] and model.l1_ratio == contract["l1_ratio"]
        model.set_params(precompute=True, max_iter=contract["extra_max_iterations"], warm_start=True)
        start = time.monotonic()
        with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=2):
            warnings.simplefilter("always")
            model.fit(pipeline[0].transform(x), y)
        converged = not any(w.category.__name__ == "ConvergenceWarning" for w in caught)
        refined = v2.OUT / f"{stage}_elastic_net_gram_refined.joblib"
        joblib.dump(pipeline, refined, compress=3)
        repair = {"stage": stage, "name": "elastic_net", "original_artifact": str(artifact),
                  "original_sha256": record["artifact_sha256"], "artifact": str(refined),
                  "artifact_sha256": v2.sha(refined), "fit_seconds": time.monotonic() - start,
                  "iterations": int(model.n_iter_), "dual_gap": float(model.dual_gap_),
                  "converged": converged, "used_for_policy": converged,
                  "objective_and_data_unchanged": True, "additional_fit_calls": 1,
                  "warnings": [{"category": w.category.__name__, "message": str(w.message)} for w in caught]}
        if stage == "validation":
            validation = frame.loc[frame.signal_date.dt.year.eq(2025)]
            vsample, _, _ = v2.sample(validation, "2026-01-01")
            vx, vy, _ = original.counterfactual(vsample)
            pred = original.predict_values(pipeline, "elastic_net", vx)
            repair["validation_mse"] = float(mean_squared_error(vy, pred))
        repairs.append(repair)
        v2.write(PARTIAL, repairs)
        print(json.dumps({"stage": stage, "converged": converged,
                          "iterations": repair["iterations"]}), flush=True)
    receipt_path = v2.OUT / "FIT_RECEIPT.json"
    if v2.sha(receipt_path) != contract["main_fit_receipt_sha256"]:
        raise RuntimeError("MAIN_FIT_RECEIPT_CHANGED_BEFORE_REPAIR_FINALIZATION")
    updated = dict(main)
    updated["numerical_repairs"] = repairs
    updated["total_fit_calls_including_numerical_repairs"] = updated["fit_calls"] + len(repairs)
    if any(r["stage"] == "validation" and r["used_for_policy"] for r in repairs):
        fixed = next(r for r in repairs if r["stage"] == "validation")
        updated["validation_metrics_before_numerical_repair"] = {"elastic_net": updated["validation_metrics"]["elastic_net"]}
        updated["validation_metrics"]["elastic_net"] = {"mse": fixed["validation_mse"]}
    v2.write(receipt_path, updated)
    v2.write(v2.OUT / "ELASTIC_REPAIR_RECEIPT.json", {"status": "PASS", "repairs": repairs,
                                                         "additional_fit_calls": len(repairs)})
    print(json.dumps({"status": "PASS", "additional_fit_calls": len(repairs)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "train"))
    args = parser.parse_args()
    prepare() if args.phase == "prepare" else run()
