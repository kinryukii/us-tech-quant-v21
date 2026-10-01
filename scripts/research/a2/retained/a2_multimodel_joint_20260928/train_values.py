"""Fourteen fresh fixed fits on physically pre-2026 inputs only."""
from __future__ import annotations

import gc
import json
import platform
import time
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.metrics import log_loss, mean_pinball_loss, mean_squared_error, roc_auc_score
from threadpoolctl import threadpool_limits

import values as v

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "a2_latest_effective_joint_20260927/data/pre2026_joint_context.parquet"
CONTRACT = ROOT / "EXPERIMENT_CONTRACT.md"
OUT = v.OUT
STAGES = {"validation": "2025-01-01", "final": "2026-01-01"}
MULTIPLIER = len(v.ACTIONS)*len(v.STATE_GRID)
BASE_BUDGET = v.MAX_ROWS // MULTIPLIER


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False,
                                   default=str, allow_nan=False), encoding="utf-8")


def validate_frame(frame):
    if (frame.signal_date.isna().any() or frame.ticker.isna().any()
            or not frame.signal_date.lt("2026-01-01").all()):
        raise RuntimeError("NON_PRE2026_PHYSICAL_SIGNAL")
    if frame.duplicated(["signal_date", "ticker"]).any():
        raise RuntimeError("DUPLICATE_SOURCE_KEY")
    if frame.label_end_date.dropna().ge("2026-01-01").any():
        raise RuntimeError("INVALID_MATURE_LABEL_BOUNDARY")
    frame = frame.loc[frame.label_available & frame.new_buy_eligible].copy()
    if (frame.label_end_date.isna().any() or not frame.label_end_date.lt("2026-01-01").all()
            or not frame.label_end_date.gt(frame.signal_date).all()):
        raise RuntimeError("INVALID_MATURE_LABEL_BOUNDARY")
    if (not np.isfinite(frame[["y_next_open", *v.FEATURES]].to_numpy(float)).all()
            or not frame.avg_dollar_volume_20d.gt(0).all()):
        raise RuntimeError("NONFINITE_OR_NONPOSITIVE_TRAINING_INPUT")
    return frame.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)


def read_frame():
    columns = list(dict.fromkeys(["signal_date", "ticker", "label_end_date", "label_available",
                                 "new_buy_eligible", "y_next_open", *v.FEATURES]))
    return validate_frame(pd.read_parquet(SOURCE, columns=columns))


def quota(counts, budget):
    counts = np.asarray(counts, dtype=np.int64)
    if len(counts) > budget or len(counts) == 0 or (counts <= 0).any():
        raise RuntimeError("DATE_COVERAGE_BUDGET_INFEASIBLE")
    lo, hi = 1, int(counts.max())
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if int(np.minimum(counts, mid).sum()) <= budget:
            lo = mid
        else:
            hi = mid-1
    result = np.minimum(counts, lo)
    slack = budget-int(result.sum())
    for i in np.flatnonzero(result < counts)[:slack]:
        result[i] += 1
    assert (result >= 1).all() and (result <= counts).all()
    assert result.sum() == min(budget, counts.sum())
    return result


def sample(frame, cutoff, budget=BASE_BUDGET):
    if pd.Timestamp(cutoff) > pd.Timestamp("2026-01-01"):
        raise ValueError("CUTOFF_AFTER_TRAINING_BOUNDARY")
    eligible = frame.loc[frame.signal_date.ge("2023-01-01") & frame.signal_date.lt(cutoff)
                         & frame.label_end_date.lt(cutoff)].copy()
    counts = eligible.groupby("signal_date", sort=True).size()
    allocation = quota(counts.to_numpy(), budget)
    quotas = dict(zip(counts.index, allocation))
    eligible["_hash"] = [__import__("hashlib").sha256(f"{v.SEED}|{d.date()}|{t}".encode()).hexdigest()
                         for d, t in zip(eligible.signal_date, eligible.ticker)]
    eligible = eligible.sort_values(["signal_date", "_hash", "ticker"], kind="mergesort")
    selected = eligible.loc[eligible.groupby("signal_date", sort=False).cumcount().to_numpy()
                            < eligible.signal_date.map(quotas).to_numpy()].drop(columns="_hash")
    selected = selected.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    assert selected.signal_date.nunique() == len(counts)
    assert selected.label_end_date.max() < pd.Timestamp(cutoff)
    assert not selected.duplicated(["signal_date", "ticker"]).any()
    assert len(selected)*MULTIPLIER <= budget*MULTIPLIER
    audit = dict(cutoff_exclusive=cutoff, eligible_dates=len(counts),
                 selected_dates=int(selected.signal_date.nunique()), eligible_base_rows=len(eligible),
                 selected_base_rows=len(selected), counterfactual_rows=len(selected)*MULTIPLIER,
                 daily_quota_min=int(allocation.min()), daily_quota_max=int(allocation.max()),
                 signal_min=str(selected.signal_date.min().date()), signal_max=str(selected.signal_date.max().date()),
                 label_end_max=str(selected.label_end_date.max().date()),
                 all_mature_dates_present=True, sampling_seed=v.SEED)
    return selected, audit


def realized_weight(current, action, adv_dollars):
    adv = np.asarray(adv_dollars, dtype=float)
    if not np.isfinite(adv).all() or not (adv > 0).all():
        raise ValueError("ADV_MUST_BE_FINITE_POSITIVE")
    if action > current:
        return current + np.minimum(action-current, v.CAPACITY_FRACTION*adv/v.NOMINAL_CASH)
    return np.full_like(adv, action)


def counterfactual(frame, robust_training=False):
    raw = frame[v.FEATURES].to_numpy(float)
    forward = frame.y_next_open.to_numpy(float)
    if robust_training:
        forward = np.clip(forward, -.20, .20)
    vol = frame.realized_vol_20d.to_numpy(float)
    adv = frame.avg_dollar_volume_20d.to_numpy(float)
    n = len(frame)
    blocks_x, blocks_y, limited = [], [], 0
    for current, cash, age in v.STATE_GRID:
        for action in v.ACTIONS:
            actual = realized_weight(current, float(action), adv)
            if action > current:
                limited += int((actual < action-1e-12).sum())
            blocks_x.append(v.mapped_features(raw, np.full(n, current), np.full(n, cash),
                                              np.full(n, age), np.full(n, action)))
            blocks_y.append(actual*forward-v.COST*np.abs(actual-current)
                            -.5*v.RISK_AVERSION*vol**2*actual**2)
    x, y = np.concatenate(blocks_x), np.concatenate(blocks_y)
    assert x.shape == (n*MULTIPLIER, 106) and np.isfinite(x).all() and np.isfinite(y).all()
    return x, y, dict(capacity_limited_buy_labels=limited, robust_training=robust_training,
                     training_return_clip=[-.20, .20] if robust_training else None)


def metrics(name, y, prediction):
    if name == "logistic":
        return {"roc_auc": float(roc_auc_score(y > 0, prediction)),
                "log_loss": float(log_loss(y > 0, prediction))}
    if name.startswith("q"):
        return {"pinball_loss": float(mean_pinball_loss(y, prediction, alpha=float(name[1:])/100))}
    return {"mse": float(mean_squared_error(y, prediction))}


def train():
    OUT.mkdir(exist_ok=True)
    if (OUT / "PRE_FIT_CONTRACT.json").exists() or (OUT / "FIT_RECEIPT.json").exists():
        raise RuntimeError("EXISTING_NEW_BATCH_FITS_PRESERVED")
    if v.FEATURES != json.loads(v.FEATURE_SOURCE.read_text(encoding="utf-8"))["feature_order"]:
        raise RuntimeError("FEATURE_ORDER_DRIFT")
    frame = read_frame()
    picked, audits = {}, {}
    for stage, cutoff in [*STAGES.items(), ("validation_metrics", "2026-01-01")]:
        source = frame.loc[frame.signal_date.dt.year.eq(2025)] if stage == "validation_metrics" else frame
        picked[stage], audits[stage] = sample(source, cutoff)
        key_path = OUT / f"sample_keys_{stage}.parquet"
        picked[stage][["signal_date", "ticker", "label_end_date"]].to_parquet(key_path, index=False)
        audits[stage]["sample_keys_sha256"] = v.sha(key_path)
    source_sha = v.sha(SOURCE)
    contract = dict(status="PRE_FIT_LOCKED", experiment_contract_sha256=v.sha(CONTRACT),
        source=str(SOURCE), source_sha256=source_sha, features=v.FEATURES,
        feature_registry_sha256=v.sha(v.FEATURE_SOURCE), seed=v.SEED, specs=v.SPECS,
        states=v.STATE_GRID, actions=v.ACTIONS.tolist(), stages=audits,
        max_counterfactual_rows=v.MAX_ROWS, fresh_initialization=True,
        counterfactual_reward="actual_weight*clipped_next_open_return - .001*abs(actual_weight-current) - .5*4*vol20^2*actual_weight^2",
        capacity_formula="buy: current+min(action-current, .01*signal_adv_dollars/1000000); sell: action",
        limitation="fixed nominal 1000000-dollar single-security one-step approximation; portfolio ledger evaluates dynamic cash and capacity",
        sampling="count-only all-date waterfill; SHA256(seed|date|ticker) within-date selection",
        hyperparameter_search_count=0, scheduled_model_fits=14, fit_2026_rows=0,
        elastic_numerical_policy="Gram precompute initially; only same objective/data warm-start max_iter=25000 once if ConvergenceWarning",
        code_sha256={p.name:v.sha(p) for p in [ROOT/"values.py", ROOT/"train_values.py"]},
        python=platform.python_version(), sklearn=sklearn.__version__)
    write(OUT/"PRE_FIT_CONTRACT.json", contract)
    del frame
    gc.collect()
    vx, vy, validation_label_audit = counterfactual(picked.pop("validation_metrics"), robust_training=False)
    receipt = dict(status="RUNNING", fits=[], fit_calls_completed=0, numerical_repair_fit_calls=0,
                   fit_2026_rows=0, test_2026_rows_read=0, hyperparameter_search_count=0,
                   pre_fit_contract_sha256=v.sha(OUT/"PRE_FIT_CONTRACT.json"), source_sha256=source_sha,
                   stages=audits, validation_metrics={}, validation_label_audit=validation_label_audit)
    for stage in STAGES:
        tx, ty, label_audit = counterfactual(picked.pop(stage), robust_training=True)
        assert len(tx) <= v.MAX_ROWS
        for name in v.NAMES:
            model = v.estimator(name)
            started = time.monotonic()
            print(json.dumps({"status":"FIT_STARTED", "stage":stage, "name":name, "rows":len(tx)}), flush=True)
            with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=2):
                warnings.simplefilter("always")
                model.fit(tx, (ty > 0).astype(int) if name == "logistic" else ty)
            fit_warnings = [{"category":w.category.__name__, "message":str(w.message)} for w in caught]
            converged = not any(w.category.__name__ == "ConvergenceWarning" for w in caught)
            repair = None
            if name == "elastic_net" and not converged:
                initial_iterations = int(model[-1].n_iter_)
                initial_gap = float(model[-1].dual_gap_)
                model[-1].set_params(precompute=True, max_iter=25000, warm_start=True)
                with warnings.catch_warnings(record=True) as repaired_warnings, threadpool_limits(limits=2):
                    warnings.simplefilter("always")
                    model[-1].fit(model[0].transform(tx), ty)
                converged = not any(w.category.__name__ == "ConvergenceWarning" for w in repaired_warnings)
                repair = dict(reason="ConvergenceWarning", objective_and_data_unchanged=True,
                    initial_iterations=initial_iterations, initial_dual_gap=initial_gap, max_iter=25000,
                    final_iterations=int(model[-1].n_iter_), final_dual_gap=float(model[-1].dual_gap_),
                    warnings=[{"category":w.category.__name__, "message":str(w.message)} for w in repaired_warnings])
                receipt["numerical_repair_fit_calls"] += 1
            path = OUT/f"{stage}_{name}.joblib"
            joblib.dump(model, path, compress=3)
            estimator = model[-1] if hasattr(model, "steps") else model
            record = dict(stage=stage, name=name, artifact=str(path.resolve()), artifact_sha256=v.sha(path),
                          train_rows=len(tx), independent_stock_date_rows=len(tx)//MULTIPLIER,
                          model_input_features=tx.shape[1], fit_seconds=time.monotonic()-started,
                          train_signal_max=audits[stage]["signal_max"], train_label_end_max=audits[stage]["label_end_max"],
                          sampling=audits[stage], label_audit=label_audit, converged=converged,
                          fit_warnings=fit_warnings, numerical_repair=repair,
                          iterations=np.asarray(getattr(estimator, "n_iter_", [])).tolist(), fit_2026_rows=0)
            if hasattr(estimator, "dual_gap_"):
                record["dual_gap"] = float(estimator.dual_gap_)
            receipt["fits"].append(record)
            receipt["fit_calls_completed"] += 1
            if stage == "validation":
                receipt["validation_metrics"][name] = metrics(name, vy, v.predict_values(model, name, vx))
            write(OUT/"FIT_RECEIPT.partial.json", receipt)
            print(json.dumps({"status":"FIT_COMPLETE", "stage":stage, "name":name,
                              "seconds":record["fit_seconds"], "converged":converged}), flush=True)
            del model
            gc.collect()
            if not converged:
                raise RuntimeError(f"MODEL_DID_NOT_CONVERGE:{stage}:{name}")
        del tx, ty
        gc.collect()
    if v.sha(SOURCE) != source_sha or v.sha(CONTRACT) != contract["experiment_contract_sha256"]:
        raise RuntimeError("FROZEN_SOURCE_OR_CONTRACT_CHANGED_DURING_TRAINING")
    for name, expected in contract["code_sha256"].items():
        if v.sha(ROOT/name) != expected:
            raise RuntimeError(f"TRAINING_CODE_CHANGED:{name}")
    receipt.update(status="PASS", model_count=len(receipt["fits"]), sources_unchanged=True,
                   all_converged=all(r["converged"] for r in receipt["fits"]))
    write(OUT/"FIT_RECEIPT.json", receipt)
    print(json.dumps({"status":"PASS", "model_count":len(receipt["fits"]), "fit_2026_rows":0}), flush=True)


if __name__ == "__main__":
    train()
