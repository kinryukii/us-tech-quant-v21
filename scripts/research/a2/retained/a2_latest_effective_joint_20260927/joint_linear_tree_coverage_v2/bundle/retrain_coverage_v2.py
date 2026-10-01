"""Fixed date-complete sampling revision of the joint linear/tree fits.

Run only with the physically pre-2026 joint parquet mounted at /data and a
private output mounted at /out. The frozen v1 implementation is imported only
for its feature mapping, labels, estimators and prediction diagnostics.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import resource
import time
import warnings

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import log_loss, mean_pinball_loss, mean_squared_error, roc_auc_score
from threadpoolctl import threadpool_limits

import joint_linear_tree as original


DATA = Path("/data/pre2026_joint.parquet")
OUT = Path("/out")
BUNDLE = Path(__file__).resolve().parent
MULTIPLIER = len(original.ACTIONS) * len(original.STATE_GRID)
BASE_BUDGET = original.MAX_ROWS // MULTIPLIER
STAGES = {"validation": "2025-01-01", "final": "2026-01-01"}
REQUIRED = ["signal_date", "ticker", "label_end_date", "label_available",
            "new_buy_eligible", "y_next_open", *original.FEATURES]


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    default=str, allow_nan=False), encoding="utf-8")


def read_frame():
    frame = pd.read_parquet(DATA, columns=REQUIRED)
    assert frame.signal_date.notna().all() and frame.ticker.notna().all()
    assert frame.signal_date.lt("2026-01-01").all(), "NON_PRE2026_SIGNAL_IN_PHYSICAL_INPUT"
    assert not frame.duplicated(["signal_date", "ticker"]).any(), "DUPLICATE_INPUT_KEY"
    frame = frame.loc[frame.label_available & frame.new_buy_eligible].copy()
    frame = frame.rename(columns={"y_next_open": "joint_return"})
    frame = frame.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    assert frame.label_end_date.notna().all(), "UNKNOWN_MATURE_LABEL_END"
    assert frame.label_end_date.gt(frame.signal_date).all(), "BAD_LABEL_END"
    assert frame.label_end_date.lt("2026-01-01").all(), "LABEL_CROSSES_2026"
    assert np.isfinite(frame[["joint_return", *original.FEATURES]].to_numpy(float)).all(), "NONFINITE_TRAINING_INPUT"
    return frame


def quota(counts, budget):
    """Water-fill all dates from counts alone, then chronologically assign slack."""
    counts = counts.to_numpy(dtype=np.int64)
    if len(counts) > budget or (counts <= 0).any():
        raise RuntimeError("DATE_COVERAGE_BUDGET_INFEASIBLE")
    lo, hi = 1, int(counts.max())
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if int(np.minimum(counts, mid).sum()) <= budget:
            lo = mid
        else:
            hi = mid - 1
    allocation = np.minimum(counts, lo)
    slack = budget - int(allocation.sum())
    for i in np.flatnonzero(allocation < counts)[:slack]:
        allocation[i] += 1
    assert (allocation >= 1).all() and (allocation <= counts).all()
    assert allocation.sum() == min(budget, counts.sum())
    return allocation


def sample(frame, cutoff):
    eligible = frame.loc[(frame.signal_date >= "2023-01-01") &
                         (frame.signal_date < cutoff) &
                         (frame.label_end_date < cutoff)].copy()
    assert not eligible.empty and not eligible.duplicated(["signal_date", "ticker"]).any()
    counts = eligible.groupby("signal_date", sort=True).size()
    allocation = quota(counts, BASE_BUDGET)
    quotas = dict(zip(counts.index, allocation))
    # The seed, date and security key alone determine within-day order.
    hashes = [hashlib.sha256(f"{original.SEED}|{d.date()}|{t}".encode("utf-8")).hexdigest()
              for d, t in zip(eligible.signal_date, eligible.ticker)]
    eligible["_sample_hash"] = hashes
    eligible = eligible.sort_values(["signal_date", "_sample_hash", "ticker"], kind="mergesort")
    selected = eligible.loc[eligible.groupby("signal_date", sort=False).cumcount().to_numpy() <
                            eligible.signal_date.map(quotas).to_numpy()].drop(columns="_sample_hash")
    selected = selected.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    assert selected.signal_date.nunique() == len(counts), "LOST_ELIGIBLE_DATE"
    assert not selected.duplicated(["signal_date", "ticker"]).any(), "DUPLICATE_SAMPLED_KEY"
    assert len(selected) * MULTIPLIER <= original.MAX_ROWS
    assert selected.label_end_date.max() < pd.Timestamp(cutoff)
    keys = selected[["signal_date", "ticker", "label_end_date"]].copy()
    selected_counts = selected.groupby("signal_date", sort=True).size()
    assert np.array_equal(selected_counts.to_numpy(), allocation)
    audit = {"cutoff_exclusive": cutoff, "eligible_dates": len(counts),
             "selected_dates": int(selected.signal_date.nunique()),
             "eligible_base_rows": len(eligible), "selected_base_rows": len(selected),
             "counterfactual_rows": len(selected) * MULTIPLIER,
             "daily_quota_min": int(allocation.min()), "daily_quota_max": int(allocation.max()),
             "selected_signal_min": str(selected.signal_date.min().date()),
             "selected_signal_max": str(selected.signal_date.max().date()),
             "selected_label_end_max": str(selected.label_end_date.max().date()),
             "sample_key_unique": True, "all_mature_eligible_dates_present": True}
    return selected, keys, audit


def prepared():
    physical_dates = pd.read_parquet(DATA, columns=["signal_date", "label_end_date"])
    assert physical_dates.signal_date.lt("2026-01-01").all(), "NON_PRE2026_PHYSICAL_INPUT"
    physical_signal_min = str(physical_dates.signal_date.min().date())
    physical_signal_max = str(physical_dates.signal_date.max().date())
    del physical_dates
    frame = read_frame()
    selected = {}
    audits = {}
    for stage, cutoff in [*STAGES.items(), ("validation_metrics", "2026-01-01")]:
        if stage == "validation_metrics":
            subset = frame.loc[frame.signal_date.dt.year.eq(2025)]
        else:
            subset = frame
        selected[stage], keys, audits[stage] = sample(subset, cutoff)
        path = OUT / f"sample_keys_{stage}.parquet"
        keys.to_parquet(path, index=False)
        audits[stage]["sample_keys_sha256"] = sha(path)
        del subset, keys
    contract = {"status": "PRE_FIT_LOCKED", "revision": "DATE_COMPLETE_WITHIN_DAY_HASH_V2",
                "scientific_change": "Replaces whole-date subsampling with all eligible dates and deterministic within-day security sampling",
                "original_models_unchanged": False,
                "original_frozen_artifacts_preserved": True,
                "input": str(DATA), "input_sha256": sha(DATA),
                "input_physical_signal_min": physical_signal_min,
                "input_physical_signal_max": physical_signal_max,
                "retained_mature_signal_max": str(frame.signal_date.max().date()),
                "code_sha256": {name: sha(BUNDLE / name) for name in
                                ("joint_linear_tree.py", "retrain_coverage_v2.py", "v2_policy.py", "models/model_registry.json")},
                "feature_names": original.FEATURES, "states": original.STATE_GRID,
                "actions": original.ACTIONS.tolist(), "seed": original.SEED,
                "estimator_specs": original.SPECS, "cost": original.COST,
                "risk_aversion": original.RISK_AVERSION,
                "maximum_counterfactual_rows_per_fit": original.MAX_ROWS,
                "counterfactual_multiplier": MULTIPLIER, "base_budget": BASE_BUDGET,
                "sampling": "Per stage use every eligible mature signal date. Allocate base row budget by count-only water-fill. Distribute final slack chronologically; within each date choose SHA256(seed|YYYY-MM-DD|ticker) ascending. Never use label magnitude, model score or 2026 values for quotas.",
                "fit_sequence": [f"{stage}:{name}" for stage in STAGES for name in original.NAMES],
                "additional_search": 0, "test2026_data_mounted": False,
                "stages": audits}
    write(OUT / "PRE_FIT_CONTRACT.json", contract)
    del selected, frame
    gc.collect()
    return contract


def verify_contract(contract):
    if contract["status"] != "PRE_FIT_LOCKED":
        raise RuntimeError("NO_PRE_FIT_LOCK")
    if sha(DATA) != contract["input_sha256"]:
        raise RuntimeError("PRE2026_SOURCE_CHANGED")
    for name, expected in contract["code_sha256"].items():
        if sha(BUNDLE / name) != expected:
            raise RuntimeError(f"BUNDLE_CODE_CHANGED:{name}")
    for stage, audit in contract["stages"].items():
        if sha(OUT / f"sample_keys_{stage}.parquet") != audit["sample_keys_sha256"]:
            raise RuntimeError(f"SAMPLE_KEYS_CHANGED:{stage}")


def run_fits():
    contract = json.loads((OUT / "PRE_FIT_CONTRACT.json").read_text(encoding="utf-8"))
    verify_contract(contract)
    if (OUT / "FIT_RECEIPT.json").exists() or (OUT / "FIT_RECEIPT.partial.json").exists():
        raise RuntimeError("EXISTING_V2_FIT_RECEIPT_PRESERVED")
    frame = read_frame()
    picked = {}
    for stage, cutoff in [*STAGES.items(), ("validation_metrics", "2026-01-01")]:
        subset = frame.loc[frame.signal_date.dt.year.eq(2025)] if stage == "validation_metrics" else frame
        picked[stage], keys, audit = sample(subset, cutoff)
        if audit != {k: v for k, v in contract["stages"][stage].items() if k != "sample_keys_sha256"}:
            raise RuntimeError(f"SAMPLE_AUDIT_CHANGED:{stage}")
        stored = pd.read_parquet(OUT / f"sample_keys_{stage}.parquet")
        if not stored.equals(keys):
            raise RuntimeError(f"SAMPLE_KEYS_CHANGED:{stage}")
        del keys, stored
    del frame
    gc.collect()
    receipt = {"status": "RUNNING", "revision": contract["revision"], "fits": [],
               "fit_calls": 0, "source_sha256": contract["input_sha256"],
               "pre_fit_contract_sha256": sha(OUT / "PRE_FIT_CONTRACT.json"),
               "test2026_rows_read": 0, "hyperparameter_search_count": 0,
               "stages": contract["stages"], "validation_metrics": {},
               "runtime": {"image_id": os.getenv("R1_FIXED_IMAGE_ID"),
                           "memory_limit_bytes": int(Path("/sys/fs/cgroup/memory.max").read_text())}}
    # Hold at most one training matrix and one bounded validation matrix.
    vx, vy, _ = original.counterfactual(picked.pop("validation_metrics"))
    for stage in STAGES:
        train = picked.pop(stage)
        tx, ty, _ = original.counterfactual(train, robust_training=True)
        del train
        gc.collect()
        for name in original.NAMES:
            start = time.monotonic()
            model = original.estimator(name)
            with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=2):
                warnings.simplefilter("always")
                model.fit(tx, (ty > 0).astype(np.int8) if name == "logistic" else ty)
            artifact = OUT / f"{stage}_{name}.joblib"
            joblib.dump(model, artifact, compress=3)
            inner = model[-1] if hasattr(model, "steps") else model
            iters = getattr(inner, "n_iter_", None)
            fit_record = {"stage": stage, "name": name, "train_rows": len(tx),
                          "fit_seconds": time.monotonic() - start,
                          "artifact": str(artifact), "artifact_sha256": sha(artifact),
                          "iterations": np.asarray(iters).tolist() if iters is not None else None,
                          "warnings": [{"category": w.category.__name__, "message": str(w.message)} for w in caught],
                          "converged": not any(w.category.__name__ == "ConvergenceWarning" for w in caught)}
            receipt["fits"].append(fit_record)
            receipt["fit_calls"] = len(receipt["fits"])
            if stage == "validation":
                pred = original.predict_values(model, name, vx)
                if name == "logistic":
                    metric = {"roc_auc": float(roc_auc_score(vy > 0, pred)),
                              "log_loss": float(log_loss(vy > 0, pred))}
                elif name.startswith("q"):
                    metric = {"pinball_loss": float(mean_pinball_loss(vy, pred, alpha=float(name[1:]) / 100))}
                else:
                    metric = {"mse": float(mean_squared_error(vy, pred))}
                receipt["validation_metrics"][name] = metric
                del pred
            write(OUT / "FIT_RECEIPT.partial.json", receipt)
            print(json.dumps({"fit": f"{stage}:{name}", "fit_calls": receipt["fit_calls"],
                              "seconds": round(fit_record["fit_seconds"], 2)}), flush=True)
            del model, inner
            gc.collect()
        del tx, ty
        if stage == "validation":
            del vx, vy
        gc.collect()
    receipt["status"] = "PASS"
    receipt["peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    receipt["source_unchanged_after_fit"] = sha(DATA) == contract["input_sha256"]
    receipt["code_unchanged_after_fit"] = all(sha(BUNDLE / n) == h for n, h in contract["code_sha256"].items())
    write(OUT / "FIT_RECEIPT.json", receipt)
    print(json.dumps({"status": "PASS", "fit_calls": receipt["fit_calls"],
                      "peak_rss_kib": receipt["peak_rss_kib"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "train"))
    args = parser.parse_args()
    if args.phase == "prepare":
        if any(OUT.iterdir()):
            raise RuntimeError("PREPARE_REQUIRES_EMPTY_OUTPUT")
        result = prepared()
        print(json.dumps({"status": result["status"], "stages": result["stages"]}), flush=True)
    else:
        run_fits()
