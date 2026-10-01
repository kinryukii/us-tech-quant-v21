"""Fit the prespecified capacity-aware HGB arm on coverage-v2 sample keys.

The old source, sampler, model, and account artifacts are read only. This is a
one-security, one-step reward approximation at the frozen $1m nominal account
size; the actual portfolio execution remains the holding-aware engine.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import sys
import time
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits


ROOT = Path(__file__).resolve().parent
UPSTREAM = ROOT.parent / "a2_latest_effective_joint_20260927"
V2 = UPSTREAM / "joint_linear_tree_coverage_v2"
DATA = UPSTREAM / "data" / "pre2026_joint.parquet"
OUT = ROOT / "hgb_capacity_artifacts"
EXPERIMENT = ROOT / "EXPERIMENT_CONTRACT.md"
sys.path.insert(0, str(UPSTREAM))
import joint_linear_tree as original  # noqa: E402


EXPECTED = {
    "source": "5895dbca36064a7ea7a9ab66fbe47c5b1dfc2ab5e6cef61d53cd23e447b09b0e",
    "original_code": "8ca19e3811f72957729fea4d4c880ef89b2b88990089851184cacdee00cab324",
    "v2_contract": "1eb5e59daef313239a5b9081d0e537addce3db60e0b0d5df2085a3c249d6fe13",
    "v2_fit": "134375a68a8fef04381aeb8d2e5731dfdbce7dbada265a3918c0c3487452505c",
    "validation_keys": "df0950e590be15091a74de7b3d4e6b440dee11dff554153897d49821908314b8",
    "final_keys": "f22767e8ae1d500a1d32535780149a9f9b7ce0b41a2775349ef8115c255c4f46",
    "validation_control": "327fbaa760fd8106e5ca2709892811c512c2a64e6a3de9171745bcad4493d89d",
    "final_control": "91da0afd687a091ad6f84daa6dff6c219c6286e1cd273e8add39c88b4179103e",
}
STAGES = {"validation": "2025-01-01", "final": "2026-01-01"}
NOMINAL_CASH = 1_000_000.0
CAPACITY_FRACTION = 0.01
COUNTERFACTUAL_ROWS = 199_995


def sha(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False,
                               allow_nan=False, default=str), encoding="utf-8")


def check_frozen_sources() -> dict:
    if not EXPERIMENT.is_file():
        raise RuntimeError("MISSING_EXPERIMENT_CONTRACT")
    paths = {
        "source": DATA,
        "original_code": UPSTREAM / "joint_linear_tree.py",
        "v2_contract": V2 / "out" / "PRE_FIT_CONTRACT.json",
        "v2_fit": V2 / "out" / "FIT_RECEIPT.json",
        "validation_keys": V2 / "out" / "sample_keys_validation.parquet",
        "final_keys": V2 / "out" / "sample_keys_final.parquet",
        "validation_control": V2 / "out" / "validation_hgb.joblib",
        "final_control": V2 / "out" / "final_hgb.joblib",
    }
    for name, path in paths.items():
        if sha(path) != EXPECTED[name]:
            raise RuntimeError(f"FROZEN_SOURCE_HASH_MISMATCH:{name}")
    v2_contract = json.loads(paths["v2_contract"].read_text(encoding="utf-8"))
    v2_fit = json.loads(paths["v2_fit"].read_text(encoding="utf-8"))
    if (v2_contract["status"] != "PRE_FIT_LOCKED" or v2_fit["status"] != "PASS"
            or v2_contract["input_sha256"] != EXPECTED["source"]
            or v2_fit["test2026_rows_read"] != 0):
        raise RuntimeError("V2_TRAINING_RECEIPT_INCOMPATIBLE")
    if original.COST != 0.001 or original.RISK_AVERSION != 4.0:
        raise RuntimeError("ORIGINAL_REWARD_PARAMETERS_CHANGED")
    if len(original.FEATURES) != 32 or len(original.ACTIONS) != 5 or len(original.STATE_GRID) != 3:
        raise RuntimeError("ORIGINAL_FEATURE_OR_GRID_CHANGED")
    return {name: {"path": str(path), "sha256": EXPECTED[name]} for name, path in paths.items()}


def read_selected(stage: str) -> tuple[pd.DataFrame, dict]:
    if stage not in STAGES:
        raise ValueError("UNKNOWN_STAGE")
    needed = list(dict.fromkeys(["signal_date", "ticker", "label_end_date", "label_available",
                                 "new_buy_eligible", "y_next_open", *original.FEATURES]))
    frame = pd.read_parquet(DATA, columns=needed)
    keys = pd.read_parquet(V2 / "out" / f"sample_keys_{stage}.parquet")
    if frame.duplicated(["signal_date", "ticker"]).any() or keys.duplicated(["signal_date", "ticker"]).any():
        raise RuntimeError("DUPLICATE_SAMPLE_OR_SOURCE_KEY")
    if len(keys) != 13_333:
        raise RuntimeError("SAMPLE_BUDGET_CHANGED")
    selected = keys.merge(frame, on=["signal_date", "ticker", "label_end_date"],
                          how="left", validate="one_to_one", indicator=True)
    if not selected["_merge"].eq("both").all():
        raise RuntimeError("SAMPLE_KEY_NOT_IN_FROZEN_SOURCE")
    selected = selected.drop(columns="_merge").sort_values(["signal_date", "ticker"], kind="mergesort")
    selected = selected.reset_index(drop=True)
    cutoff = pd.Timestamp(STAGES[stage])
    if (not selected.signal_date.ge("2023-01-01").all()
            or not selected.signal_date.lt(cutoff).all()
            or not selected.label_end_date.lt(cutoff).all()
            or not selected.label_end_date.gt(selected.signal_date).all()
            or not (selected.label_available & selected.new_buy_eligible).all()):
        raise RuntimeError("TRAINING_TIME_OR_ELIGIBILITY_FAILURE")
    numeric = selected[["y_next_open", *original.FEATURES]].to_numpy(dtype=float)
    if not np.isfinite(numeric).all() or not selected.avg_dollar_volume_20d.gt(0).all():
        raise RuntimeError("NONFINITE_OR_NONPOSITIVE_TRAINING_INPUT")
    expected_dates = 500 if stage == "validation" else 750
    if selected.signal_date.nunique() != expected_dates:
        raise RuntimeError("DATE_COVERAGE_CHANGED")
    audit = {"sample_keys_sha256": EXPECTED[f"{stage}_keys"],
             "base_rows": len(selected), "mature_dates": expected_dates,
             "signal_min": str(selected.signal_date.min().date()),
             "signal_max": str(selected.signal_date.max().date()),
             "label_end_max": str(selected.label_end_date.max().date()),
             "cutoff_exclusive": STAGES[stage]}
    return selected, audit


def realized_weight(current: float, action: float, adv_dollars: np.ndarray) -> np.ndarray:
    """One-step achievable single-name weight at the fixed nominal $1m NAV."""
    adv = np.asarray(adv_dollars, dtype=float)
    if not np.isfinite(adv).all() or not (adv > 0).all():
        raise ValueError("ADV_MUST_BE_FINITE_POSITIVE")
    if action > current:
        return current + np.minimum(action - current, CAPACITY_FRACTION * adv / NOMINAL_CASH)
    return np.full_like(adv, action)


def expand_capacity(selected: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, dict]:
    """Keep requested-action X identical to v2; change only achievable reward."""
    raw = selected[original.FEATURES].to_numpy(dtype=float)
    forward = np.clip(selected.y_next_open.to_numpy(dtype=float), -0.20, 0.20)
    vol = selected.realized_vol_20d.to_numpy(dtype=float)
    adv = selected.avg_dollar_volume_20d.to_numpy(dtype=float)
    n = len(selected)
    blocks_x, blocks_y = [], []
    constrained = 0
    for current, cash, age in original.STATE_GRID:
        for action in original.ACTIONS:
            actual = realized_weight(current, float(action), adv)
            if action > current:
                constrained += int(np.count_nonzero(actual < action - 1e-12))
            blocks_x.append(original.mapped_features(raw, np.full(n, current),
                           np.full(n, cash), np.full(n, age), np.full(n, action)))
            blocks_y.append(actual * forward - original.COST * np.abs(actual - current)
                            - 0.5 * original.RISK_AVERSION * vol**2 * actual**2)
    x, y = np.concatenate(blocks_x), np.concatenate(blocks_y)
    if x.shape != (n * 15, 106) or y.shape != (n * 15,) or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise RuntimeError("BAD_COUNTERFACTUAL_MATRIX")
    return x, y, {"capacity_limited_buy_labels": constrained,
                  "capacity_formula": "current + min(action-current, 0.01*signal_adv_dollars/1000000) for buys; sell=action",
                  "training_nominal_cash": NOMINAL_CASH,
                  "capacity_fraction": CAPACITY_FRACTION}


def prepare() -> None:
    if (OUT / "PRE_FIT_CONTRACT.json").exists() or (OUT / "FIT_RECEIPT.json").exists():
        raise RuntimeError("EXISTING_HGB_CAPACITY_CONTRACT_PRESERVED")
    frozen = check_frozen_sources()
    audits = {}
    for stage in STAGES:
        selected, audits[stage] = read_selected(stage)
        del selected
        gc.collect()
    OUT.mkdir(exist_ok=True)
    spec = {"status": "PRE_FIT_LOCKED", "design": "HGB_CAPACITY_ONE_STEP_NOMINAL_1M",
            "experiment_contract_sha256": sha(EXPERIMENT),
            "training_code_sha256": sha(Path(__file__)),
            "frozen_sources": frozen, "stages": audits,
            "feature_count": 32, "mapped_feature_count": 106,
            "state_count": 3, "action_count": 5,
            "counterfactual_rows_per_fit": COUNTERFACTUAL_ROWS,
            "training_nominal_cash": NOMINAL_CASH, "capacity_fraction": CAPACITY_FRACTION,
            "one_way_cost": original.COST, "risk_aversion": original.RISK_AVERSION,
            "hgb_spec": original.SPECS["hgb"],
            "test2026_rows_read": 0, "hyperparameter_search_count": 0,
            "fit_calls": 0}
    write_json(OUT / "PRE_FIT_CONTRACT.json", spec)
    print(json.dumps({"status": spec["status"], "fit_calls": 0, "stages": audits}))


def fit() -> None:
    spec_path = OUT / "PRE_FIT_CONTRACT.json"
    if not spec_path.is_file():
        raise RuntimeError("RUN_PREPARE_BEFORE_FIT")
    if (OUT / "FIT_RECEIPT.json").exists() or (OUT / "FIT_RECEIPT.partial.json").exists():
        raise RuntimeError("EXISTING_HGB_CAPACITY_FIT_PRESERVED")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if (spec["status"] != "PRE_FIT_LOCKED" or spec["training_code_sha256"] != sha(Path(__file__))
            or spec["experiment_contract_sha256"] != sha(EXPERIMENT)
            or spec["counterfactual_rows_per_fit"] != COUNTERFACTUAL_ROWS):
        raise RuntimeError("PRE_FIT_CONTRACT_CHANGED")
    if check_frozen_sources() != spec["frozen_sources"]:
        raise RuntimeError("FROZEN_SOURCES_CHANGED_AFTER_PREPARE")
    receipt = {"status": "RUNNING", "design": spec["design"],
               "pre_fit_contract_sha256": sha(spec_path), "fit_calls_attempted": 0,
               "fit_calls_completed": 0, "fits": [], "test2026_rows_read": 0,
               "hyperparameter_search_count": 0}
    for stage in STAGES:
        artifact = OUT / f"{stage}_hgb.joblib"
        if artifact.exists():
            raise RuntimeError(f"EXISTING_MODEL_PRESERVED:{artifact.name}")
        selected, audit = read_selected(stage)
        if audit != spec["stages"][stage]:
            raise RuntimeError(f"SAMPLE_AUDIT_CHANGED:{stage}")
        x, y, label_audit = expand_capacity(selected)
        del selected
        gc.collect()
        if len(x) != COUNTERFACTUAL_ROWS:
            raise RuntimeError("TRAINING_ROW_BUDGET_CHANGED")
        model = original.estimator("hgb")
        receipt["fit_calls_attempted"] += 1
        receipt["current_fit"] = stage
        write_json(OUT / "FIT_RECEIPT.partial.json", receipt)
        start = time.monotonic()
        with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=2):
            warnings.simplefilter("always")
            model.fit(x, y)
        elapsed = time.monotonic() - start
        joblib.dump(model, artifact, compress=3)
        receipt["fits"].append({"stage": stage, "name": "hgb", "sample": audit,
                                "train_rows": len(x), "model_input_features": x.shape[1],
                                "fit_seconds": elapsed, "iterations": int(model.n_iter_),
                                "warnings": [{"category": w.category.__name__, "message": str(w.message)} for w in caught],
                                "artifact": str(artifact), "artifact_sha256": sha(artifact),
                                **label_audit})
        receipt["fit_calls_completed"] += 1
        receipt.pop("current_fit")
        write_json(OUT / "FIT_RECEIPT.partial.json", receipt)
        print(json.dumps({"fit": stage, "rows": len(x), "iterations": int(model.n_iter_)}), flush=True)
        del model, x, y
        gc.collect()
    receipt["status"] = "PASS"
    receipt["source_unchanged_after_fit"] = check_frozen_sources() == spec["frozen_sources"]
    receipt["code_unchanged_after_fit"] = sha(Path(__file__)) == spec["training_code_sha256"]
    write_json(OUT / "FIT_RECEIPT.json", receipt)
    print(json.dumps({"status": "PASS", "fit_calls_completed": receipt["fit_calls_completed"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "fit"])
    args = parser.parse_args()
    prepare() if args.mode == "prepare" else fit()
