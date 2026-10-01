"""Seven fixed 2023-only first-layer fits for temporal OOF stacking.

This separately contracted stage never changes the completed base fits. Its
normalizers are fitted by fresh model pipelines on the early sample only.
"""
from __future__ import annotations

import gc
import json
import time
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

import values as v
import train_values as base

ROOT = Path(__file__).resolve().parent
OUT = ROOT/"ensemble_artifacts/early_values"
CONTRACT = ROOT/"ENSEMBLE_CONTRACT.md"
CUTOFF = "2024-01-01"


def train():
    if not CONTRACT.is_file():
        raise RuntimeError("MISSING_ENSEMBLE_CONTRACT")
    completed = json.loads((v.OUT/"FIT_RECEIPT.json").read_text(encoding="utf-8"))
    if completed["status"] != "PASS" or len(completed["fits"]) != 14:
        raise RuntimeError("BASE_FITS_NOT_COMPLETE")
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT/"PRE_FIT_CONTRACT.json").exists() or list(OUT.glob("*.joblib")):
        raise RuntimeError("EARLY_FITS_ALREADY_STARTED_PRESERVE")
    columns = list(dict.fromkeys(["signal_date", "ticker", "label_end_date", "label_available",
                                 "new_buy_eligible", "y_next_open", *v.FEATURES]))
    # Read only early rows, not later-year targets or observations.
    raw = pd.read_parquet(base.SOURCE, columns=columns, filters=[
        ("signal_date", ">=", pd.Timestamp("2023-01-01")),
        ("signal_date", "<", pd.Timestamp(CUTOFF)),
        ("label_end_date", "<", pd.Timestamp(CUTOFF))])
    frame = base.validate_frame(raw)
    selected, audit = base.sample(frame, CUTOFF)
    del raw, frame
    keys = OUT/"sample_keys_early.parquet"
    selected[["signal_date", "ticker", "label_end_date"]].to_parquet(keys, index=False)
    audit["sample_keys_sha256"] = v.sha(keys)
    source_sha = v.sha(base.SOURCE)
    spec = dict(status="PRE_FIT_LOCKED", stage="early", cutoff_exclusive=CUTOFF,
        source=str(base.SOURCE), source_sha256=source_sha,
        ensemble_contract_sha256=v.sha(CONTRACT),
        base_fit_receipt_sha256=v.sha(v.OUT/"FIT_RECEIPT.json"),
        feature_order=v.FEATURES, parameters=v.SPECS, seed=v.SEED,
        fresh_initialization=True, prior_weights_loaded=False, sample=audit,
        scheduled_fits=7, max_counterfactual_rows=v.MAX_ROWS,
        fold_prediction_year=2024, fit_2024_or_later_rows=0, fit_2026_rows=0,
        reward="identical base.capacity counterfactual with training-only +/-20% return clip",
        sampling="all mature 2023 dates; count-only waterfill; SHA256(seed|date|ticker)",
        scaler="each fresh linear pipeline fits solely its early 2023 sample",
        numerical_repair="Elastic only, same samples/objective/scaler; at most one 25000-iteration warm continuation",
        code_sha256={p.name:v.sha(p) for p in [ROOT/"values.py", ROOT/"train_values.py", Path(__file__)]})
    base.write(OUT/"PRE_FIT_CONTRACT.json", spec)
    x, y, label_audit = base.counterfactual(selected, robust_training=True)
    del selected
    gc.collect()
    receipt = dict(status="RUNNING", stage="early", fits=[], sample=audit,
        pre_fit_contract_sha256=v.sha(OUT/"PRE_FIT_CONTRACT.json"), source_sha256=source_sha,
        fit_calls_completed=0, numerical_repair_fit_calls=0,
        fit_2024_or_later_rows=0, fit_2026_rows=0, test_2026_rows_read=0,
        hyperparameter_search_count=0, fold_prediction_year=2024)
    for name in v.NAMES:
        model = v.estimator(name)
        started = time.monotonic()
        print(json.dumps({"status":"FIT_STARTED", "stage":"early", "name":name, "rows":len(x)}), flush=True)
        with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=2):
            warnings.simplefilter("always")
            model.fit(x, (y > 0).astype(int) if name == "logistic" else y)
        converged = not any(w.category.__name__ == "ConvergenceWarning" for w in caught)
        original_warnings = [{"category":w.category.__name__, "message":str(w.message)} for w in caught]
        repair = None
        if name == "elastic_net" and not converged:
            initial_iterations = int(model[-1].n_iter_)
            model[-1].set_params(precompute=True, max_iter=25000, warm_start=True)
            with warnings.catch_warnings(record=True) as repaired, threadpool_limits(limits=2):
                warnings.simplefilter("always")
                model[-1].fit(model[0].transform(x), y)
            converged = not any(w.category.__name__ == "ConvergenceWarning" for w in repaired)
            repair = dict(objective_and_data_unchanged=True, initial_iterations=initial_iterations,
                final_iterations=int(model[-1].n_iter_), final_dual_gap=float(model[-1].dual_gap_),
                max_iter=25000, warnings=[{"category":w.category.__name__, "message":str(w.message)} for w in repaired])
            receipt["numerical_repair_fit_calls"] += 1
        path = OUT/f"early_{name}.joblib"
        joblib.dump(model, path, compress=3)
        estimator = model[-1] if hasattr(model, "steps") else model
        record = dict(stage="early", name=name, artifact=str(path.resolve()), artifact_sha256=v.sha(path),
            train_signal_max=audit["signal_max"], train_label_end_max=audit["label_end_max"],
            train_rows=len(x), independent_stock_date_rows=len(x)//base.MULTIPLIER,
            sampling=audit, label_audit=label_audit, converged=converged,
            fit_warnings=original_warnings, numerical_repair=repair,
            iterations=np.asarray(getattr(estimator, "n_iter_", [])).tolist(),
            fit_seconds=time.monotonic()-started, fit_2024_or_later_rows=0, fit_2026_rows=0)
        if hasattr(estimator, "dual_gap_"):
            record["dual_gap"] = float(estimator.dual_gap_)
        receipt["fits"].append(record)
        receipt["fit_calls_completed"] += 1
        base.write(OUT/"FIT_RECEIPT.partial.json", receipt)
        print(json.dumps({"status":"FIT_COMPLETE", "stage":"early", "name":name,
                          "seconds":record["fit_seconds"], "converged":converged}), flush=True)
        if not converged:
            raise RuntimeError(f"EARLY_MODEL_NOT_CONVERGED:{name}")
        del model
        gc.collect()
    if v.sha(base.SOURCE) != source_sha or v.sha(CONTRACT) != spec["ensemble_contract_sha256"]:
        raise RuntimeError("EARLY_SOURCE_OR_CONTRACT_CHANGED")
    if v.sha(v.OUT/"FIT_RECEIPT.json") != spec["base_fit_receipt_sha256"]:
        raise RuntimeError("BASE_FITS_CHANGED")
    for name, expected in spec["code_sha256"].items():
        if v.sha(ROOT/name) != expected:
            raise RuntimeError(f"EARLY_SOURCE_CODE_CHANGED:{name}")
    receipt.update(status="PASS", model_count=7, all_converged=True, sources_unchanged=True)
    base.write(OUT/"FIT_RECEIPT.json", receipt)
    print(json.dumps({"status":"PASS", "stage":"early", "model_count":7,
                      "fit_2024_or_later_rows":0, "fit_2026_rows":0}), flush=True)


if __name__ == "__main__":
    train()
