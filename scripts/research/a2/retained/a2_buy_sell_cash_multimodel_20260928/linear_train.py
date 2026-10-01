"""Fresh, fixed-budget linear/tree action-value fits using only pre-2026 data.

The seven estimators share a capacity-aware one-step reward and fixed state /
action map.  These are joint action-value models, not sequential RL policies.
All fit inputs, sample keys, code and specifications are sealed before fitting.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
import warnings

import joblib
import numpy as np
import pandas as pd
import sklearn
from threadpoolctl import threadpool_limits


HERE = Path(__file__).resolve().parent
UPSTREAM = HERE.parent / "a2_latest_effective_joint_20260927"
CAPACITY = HERE.parent / "a2_capacity_in_training_paired_20260927"
DATA = UPSTREAM / "data/pre2026_joint_context.parquet"
OUT = HERE / "linear_artifacts"
EXPERIMENT = HERE / "EXPERIMENT_CONTRACT.md"
sys.path.insert(0, str(UPSTREAM))
sys.path.insert(0, str(CAPACITY))
import joint_linear_tree as original  # noqa: E402
import hgb_capacity_train as capacity  # noqa: E402

FEATURES = original.FEATURES
ACTIONS = original.ACTIONS
STATE_GRID = original.STATE_GRID
NAMES = original.NAMES
SPECS = original.SPECS
SEED = original.SEED
MAX_ROWS = 200_000
MULTIPLIER = len(ACTIONS) * len(STATE_GRID)
BASE_BUDGET = MAX_ROWS // MULTIPLIER
STAGES = {"validation": "2025-01-01", "final": "2026-01-01"}
mapped_features = original.mapped_features
predict_values = original.predict_values
allocate_joint_scores = original.allocate_joint_scores


def sha(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                               default=str, allow_nan=False), encoding="utf-8")


def read_frame() -> pd.DataFrame:
    required = ["signal_date", "ticker", "label_end_date", "label_available",
                "new_buy_eligible", "y_next_open", "quarter_effective_date",
                "next_quarter_effective_date", *FEATURES]
    frame = pd.read_parquet(DATA, columns=list(dict.fromkeys(required)))
    if frame.signal_date.isna().any() or not frame.signal_date.lt("2026-01-01").all():
        raise RuntimeError("NON_PRE2026_PHYSICAL_INPUT")
    if frame.ticker.isna().any() or frame.duplicated(["signal_date", "ticker"]).any():
        raise RuntimeError("INVALID_SOURCE_KEYS")
    frame = frame.loc[frame.label_available & frame.new_buy_eligible].copy()
    if (frame.label_end_date.isna().any()
            or not frame.label_end_date.gt(frame.signal_date).all()
            or not frame.label_end_date.lt("2026-01-01").all()):
        raise RuntimeError("LABEL_MATURITY_BOUNDARY_FAILURE")
    if (not frame.quarter_effective_date.le(frame.signal_date).all()
            or not (frame.next_quarter_effective_date.isna()
                    | frame.signal_date.lt(frame.next_quarter_effective_date)).all()):
        raise RuntimeError("LATEST_EFFECTIVE_13F_BOUNDARY_FAILURE")
    if (not np.isfinite(frame[["y_next_open", *FEATURES]].to_numpy(float)).all()
            or not frame.avg_dollar_volume_20d.gt(0).all()):
        raise RuntimeError("NONFINITE_OR_NONPOSITIVE_FIT_INPUT")
    return frame.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)


def quota(counts: pd.Series, budget: int) -> np.ndarray:
    """Counts-only water fill covers every mature day, then chronological slack."""
    counts = counts.to_numpy(dtype=np.int64)
    if len(counts) == 0 or len(counts) > budget or (counts <= 0).any():
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
    allocation[np.flatnonzero(allocation < counts)[:slack]] += 1
    assert allocation.sum() == min(budget, counts.sum())
    return allocation


def sample(frame: pd.DataFrame, cutoff: str,
           budget: int = BASE_BUDGET) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    eligible = frame.loc[(frame.signal_date >= "2023-01-01")
                         & (frame.signal_date < cutoff)
                         & (frame.label_end_date < cutoff)].copy()
    counts = eligible.groupby("signal_date", sort=True).size()
    allocation = quota(counts, budget)
    quotas = dict(zip(counts.index, allocation))
    eligible["_sample_hash"] = [
        hashlib.sha256(f"{SEED}|{d.date()}|{t}".encode("utf-8")).hexdigest()
        for d, t in zip(eligible.signal_date, eligible.ticker)]
    eligible = eligible.sort_values(["signal_date", "_sample_hash", "ticker"], kind="mergesort")
    selected = eligible.loc[eligible.groupby("signal_date", sort=False).cumcount().to_numpy()
                            < eligible.signal_date.map(quotas).to_numpy()].drop(columns="_sample_hash")
    selected = selected.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    if selected.signal_date.nunique() != len(counts) or selected.duplicated(["signal_date", "ticker"]).any():
        raise RuntimeError("SAMPLED_KEY_OR_DATE_COVERAGE_FAILURE")
    if len(selected) * MULTIPLIER > MAX_ROWS:
        raise RuntimeError("FIT_BUDGET_EXCEEDED")
    keys = selected[["signal_date", "ticker", "label_end_date"]].copy()
    audit = {"cutoff_exclusive": cutoff, "eligible_dates": len(counts),
             "selected_dates": int(selected.signal_date.nunique()),
             "eligible_base_rows": len(eligible), "selected_base_rows": len(selected),
             "counterfactual_rows": len(selected) * MULTIPLIER,
             "daily_quota_min": int(allocation.min()), "daily_quota_max": int(allocation.max()),
             "selected_signal_min": str(selected.signal_date.min().date()),
             "selected_signal_max": str(selected.signal_date.max().date()),
             "selected_label_end_max": str(selected.label_end_date.max().date()),
             "all_mature_eligible_dates_present": True}
    return selected, keys, audit


def frozen_paths() -> dict[str, Path]:
    return {"input": DATA, "experiment": EXPERIMENT,
            "training_code": Path(__file__).resolve(),
            "original_feature_and_estimators": UPSTREAM / "joint_linear_tree.py",
            "original_capacity_reward": CAPACITY / "hgb_capacity_train.py",
            "feature_registry": UPSTREAM / "models/model_registry.json"}


def prepare() -> dict:
    OUT.mkdir(exist_ok=True)
    if any(OUT.iterdir()):
        raise RuntimeError("PREPARE_REQUIRES_EMPTY_OUTPUT")
    frame = read_frame()
    stages = {}
    for stage, cutoff in STAGES.items():
        selected, keys, stages[stage] = sample(frame, cutoff)
        key_path = OUT / f"sample_keys_{stage}.parquet"
        keys.to_parquet(key_path, index=False)
        stages[stage]["sample_keys_sha256"] = sha(key_path)
        del selected, keys
    contract = {
        "status": "PRE_FIT_LOCKED", "design": "FRESH_SEVEN_CAPACITY_AWARE_JOINT_VALUE_MODELS",
        "frozen_sources": {name: {"path": str(path), "sha256": sha(path)}
                           for name, path in frozen_paths().items()},
        "source_sha256": sha(DATA), "features": FEATURES,
        "mapped_features": 106, "states": STATE_GRID, "actions": ACTIONS.tolist(),
        "estimator_specs": SPECS, "estimator_seed": SEED, "sampling_seed": SEED,
        "stages": stages, "maximum_counterfactual_rows_per_fit": MAX_ROWS,
        "base_budget": BASE_BUDGET, "fit_sequence": [f"{s}:{n}" for s in STAGES for n in NAMES],
        "sampling": "All mature eligible dates; count-only water fill; chronological slack; SHA256(seed|date|ticker) within day; no outcome-dependent selection",
        "reward": "actual_weight*clip(next_open_return,-.20,.20)-.001*abs(actual_weight-current)-.5*4*vol20^2*actual_weight^2",
        "capacity": "Buys actual=current+min(action-current,.01*signal_ADV/1000000); sells actual=action",
        "logistic_target": "Probability one-step net utility is strictly positive; not a return forecast",
        "quantile_risk_readout": "Sort Q10,Q50,Q90 per row, then Q50-.25*(Q50-Q10)",
        "elastic_numerics": {"initial_precompute_gram": True,
                             "repair_only_on_convergence_warning": True,
                             "maximum_repair_attempts": 1, "repair_max_iter": 25000,
                             "same_samples_target_scaler_alpha_l1_ratio": True,
                             "warm_start": True},
        "training_robust_return_clip": [-.20, .20], "evaluation_return_clip": None,
        "test2026_rows_read": 0, "hyperparameter_search_count": 0,
        "physical_isolation": "Fit reads only the pre2026 parquet; no test economic artifacts read",
        "runtime": {"python": platform.python_version(), "sklearn": sklearn.__version__,
                    "numpy": np.__version__, "pandas": pd.__version__}}
    write(OUT / "PRE_FIT_CONTRACT.json", contract)
    print(json.dumps({"status": "PRE_FIT_LOCKED", "stages": stages}), flush=True)
    return contract


def verify_contract(contract: dict) -> None:
    if contract["status"] != "PRE_FIT_LOCKED":
        raise RuntimeError("PRE_FIT_LOCK_MISSING")
    for name, entry in contract["frozen_sources"].items():
        if sha(Path(entry["path"])) != entry["sha256"]:
            raise RuntimeError(f"FROZEN_SOURCE_CHANGED:{name}")
    for stage, audit in contract["stages"].items():
        if sha(OUT / f"sample_keys_{stage}.parquet") != audit["sample_keys_sha256"]:
            raise RuntimeError(f"SAMPLE_KEYS_CHANGED:{stage}")


def fit_record(model, stage: str, name: str, artifact: Path, x, started, caught) -> dict:
    inner = model[-1] if hasattr(model, "steps") else model
    iterations = getattr(inner, "n_iter_", None)
    return {"stage": stage, "name": name, "train_rows": len(x),
            "model_input_features": x.shape[1], "fit_seconds": time.monotonic()-started,
            "artifact": str(artifact), "artifact_sha256": sha(artifact),
            "iterations": np.asarray(iterations).tolist() if iterations is not None else None,
            "dual_gap": float(inner.dual_gap_) if hasattr(inner, "dual_gap_") else None,
            "warnings": [{"category": w.category.__name__, "message": str(w.message)} for w in caught],
            "converged": not any(w.category.__name__ == "ConvergenceWarning" for w in caught)}


def train() -> dict:
    contract_path = OUT / "PRE_FIT_CONTRACT.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    verify_contract(contract)
    if (OUT / "FIT_RECEIPT.json").exists() or (OUT / "FIT_RECEIPT.partial.json").exists():
        raise RuntimeError("EXISTING_FITS_PRESERVED")
    frame = read_frame()
    receipt = {"status": "RUNNING", "fits": [], "numerical_repairs": [],
               "pre_fit_contract_sha256": sha(contract_path),
               "source_sha256": contract["source_sha256"], "stages": contract["stages"],
               "fit_calls": 0, "fit_calls_attempted": 0,
               "total_fit_calls_including_numerical_repairs": 0,
               "test2026_rows_read": 0, "hyperparameter_search_count": 0}
    for stage, cutoff in STAGES.items():
        selected, keys, audit = sample(frame, cutoff)
        if audit != {k: v for k, v in contract["stages"][stage].items() if k != "sample_keys_sha256"}:
            raise RuntimeError(f"SAMPLE_AUDIT_CHANGED:{stage}")
        if not pd.read_parquet(OUT / f"sample_keys_{stage}.parquet").equals(keys):
            raise RuntimeError(f"SAMPLE_KEY_CONTENT_CHANGED:{stage}")
        x, y, label_audit = capacity.expand_capacity(selected)
        x_hash = hashlib.sha256(x.tobytes()).hexdigest()
        y_hash = hashlib.sha256(y.tobytes()).hexdigest()
        del selected, keys
        gc.collect()
        for name in NAMES:
            model = original.estimator(name)
            if name == "elastic_net":
                # Exact Gram computation changes solver arithmetic, not its objective.
                model[-1].set_params(precompute=True)
            receipt["fit_calls_attempted"] += 1
            receipt["current_fit"] = f"{stage}:{name}"
            write(OUT / "FIT_RECEIPT.partial.json", receipt)
            started = time.monotonic()
            with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=2):
                warnings.simplefilter("always")
                model.fit(x, (y > 0).astype(np.int8) if name == "logistic" else y)
            artifact = OUT / f"{stage}_{name}.joblib"
            joblib.dump(model, artifact, compress=3)
            record = fit_record(model, stage, name, artifact, x, started, caught)
            record.update({"sample": audit, "matrix_sha256": x_hash,
                           "reward_sha256": y_hash, **label_audit})
            receipt["fits"].append(record)
            receipt["fit_calls"] = len(receipt["fits"])
            print(json.dumps({"fit": f"{stage}:{name}", "converged": record["converged"],
                              "seconds": round(record["fit_seconds"], 3)}), flush=True)
            if name == "elastic_net" and not record["converged"]:
                repair_contract = {
                    "status": "PRE_REPAIR_LOCKED", "stage": stage, "name": name,
                    "original_sha256": record["artifact_sha256"],
                    "pre_fit_contract_sha256": receipt["pre_fit_contract_sha256"],
                    "matrix_sha256": x_hash, "reward_sha256": y_hash,
                    "alpha": model[-1].alpha, "l1_ratio": model[-1].l1_ratio,
                    "reason": "ConvergenceWarning only; objective, scaler, data and features unchanged",
                    "maximum_attempts": 1, "max_iter": 25000, "warm_start": True}
                write(OUT / f"{stage}_elastic_repair_contract.json", repair_contract)
                model[-1].set_params(max_iter=25000, warm_start=True)
                receipt["fit_calls_attempted"] += 1
                started = time.monotonic()
                with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=2):
                    warnings.simplefilter("always")
                    model[-1].fit(model[0].transform(x), y)
                repaired_path = OUT / f"{stage}_elastic_net_repaired.joblib"
                joblib.dump(model, repaired_path, compress=3)
                repaired = fit_record(model, stage, name, repaired_path, x, started, caught)
                repaired.update({"original_artifact": str(artifact),
                                 "original_sha256": record["artifact_sha256"],
                                 "objective_and_data_unchanged": True,
                                 "matrix_sha256": x_hash, "reward_sha256": y_hash,
                                 "used_for_policy": repaired["converged"]})
                receipt["numerical_repairs"].append(repaired)
                print(json.dumps({"repair": f"{stage}:{name}", "converged": repaired["converged"],
                                  "seconds": round(repaired["fit_seconds"], 3)}), flush=True)
            if not np.isfinite(predict_values(model, name, x[:100])).all():
                raise RuntimeError(f"NONFINITE_FIT_PREDICTION:{stage}:{name}")
            receipt["total_fit_calls_including_numerical_repairs"] = len(receipt["fits"]) + len(receipt["numerical_repairs"])
            receipt.pop("current_fit")
            write(OUT / "FIT_RECEIPT.partial.json", receipt)
            del model
            gc.collect()
        del x, y
        gc.collect()
    verify_contract(contract)
    unresolved = []
    for record in receipt["fits"]:
        if not record["converged"] and not any(
                r["stage"] == record["stage"] and r["name"] == record["name"]
                and r["used_for_policy"] for r in receipt["numerical_repairs"]):
            unresolved.append(f"{record['stage']}:{record['name']}")
    receipt.update({"status": "PASS" if not unresolved else "COMPLETED_WITH_CONVERGENCE_WARNING",
                    "unresolved_convergence": unresolved,
                    "source_unchanged_after_fit": True, "code_unchanged_after_fit": True})
    write(OUT / "FIT_RECEIPT.json", receipt)
    print(json.dumps({"status": receipt["status"], "fit_calls": receipt["fit_calls"],
                      "total_fit_calls_including_numerical_repairs": receipt["total_fit_calls_including_numerical_repairs"]}), flush=True)
    return receipt


class JointActionValuePolicy(original.JointActionValuePolicy):
    """Reuse the frozen value-map/readout, loading this experiment's new weights."""
    def __init__(self, name: str, stage: str = "final"):
        if stage not in STAGES or name not in (*NAMES, "quantile_risk"):
            raise ValueError("UNKNOWN_POLICY_OR_STAGE")
        self.name, self.stage, self.models = name, stage, {}
        receipt = json.loads((OUT / "FIT_RECEIPT.json").read_text(encoding="utf-8"))
        if receipt["status"] != "PASS":
            raise RuntimeError("NEW_TRAINING_NOT_VERIFIED_COMPLETE")
        names = ("q10", "q50", "q90") if name == "quantile_risk" else (name,)
        for model_name in names:
            record = next(r for r in receipt["fits"] if r["stage"] == stage and r["name"] == model_name)
            repairs = [r for r in receipt["numerical_repairs"] if r["stage"] == stage
                       and r["name"] == model_name and r["used_for_policy"]]
            if repairs:
                record = repairs[-1]
            path = Path(record["artifact"])
            if path.parent.resolve() != OUT.resolve() or sha(path) != record["artifact_sha256"]:
                raise RuntimeError("NEW_POLICY_ARTIFACT_HASH_OR_PATH_FAILURE")
            self.models[model_name] = joblib.load(path)
        self.last_actions = None


def load_policy(name: str, stage: str = "final") -> JointActionValuePolicy:
    return JointActionValuePolicy(name, stage)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "train"))
    args = parser.parse_args()
    prepare() if args.phase == "prepare" else train()
