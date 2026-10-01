"""Fixed, time-purged meta learners for saved base OOF predictions.

No model is fitted on import. --write-design only materializes the fixed design.
Actual preparation and training require the root's immutable DESIGN_LOCK.json.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import warnings

sys.dont_write_bytecode = True
import joblib
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "meta_artifacts"
INPUT = ROOT / "OOF_WITH_CONTEXT.parquet"
P_COLS = ["p_ridge", "p_hgb", "p_mlp"]
G_COLS = ["g_ret20mean", "g_vol20mean", "g_breadth_ma20", "g_disagreement"]
KEY_COLS = ["signal_date", "ticker"]
LABEL_COLS = ["target", "target_end_date", "target_context_available", "base_cutoff"]
SEED = 20260928
PRIOR = np.array([.2, .5, .3])
STAGES = {"validation": "2025-07-01", "final": "2026-01-01"}
TRAIN_METHODS = ["learned_fixed", "stack_ridge", "stack_mlp", "conditional_gate",
                 "ridge_then_hgb", "hgb_then_ridge"]
SCORE_METHODS = ["fixed_pred", *TRAIN_METHODS]

DESIGN = {
    "version": "FIXED_META_DESIGN_R1", "seed": SEED,
    "base_prediction_columns_in_order": P_COLS, "gate_context_columns_in_order": G_COLS,
    "labels_never_in_inference_features": True,
    "stage_cutoffs_exclusive": STAGES, "base_cutoff_lte_signal_date": True,
    "all_target_end_dates_strictly_before_stage_cutoff": True,
    "oof_signal_years_only": [2024, 2025], "fixed_selected_key_cap_per_stage": 40000,
    "selection": "equal_date_quota_waterfill_then_SHA256_of_seed_stage_date_ticker; no target magnitude ranking",
    "sample_weight": "n_selected/(n_dates*n_selected_on_date); equal total date weight; sum=n_selected",
    "scalers": "StandardScaler weighted population moments on selected training rows only",
    "sklearn_training_threadpool_limit": 2,
    "training_target_clip": [-.3, .3], "base_oof_predictions_clipped": False,
    "prediction_output_clipped": False, "score_order": "ridge,hgb,mlp",
    "fixed_pred": {"coefficients": PRIOR.tolist()},
    "learned_fixed": {"objective": "weighted_MSE(P/0.1 @ coefficients,target_clipped/0.1)+0.001*sum((coefficients-prior)^2)",
        "prior": PRIOR.tolist(), "bounds": [.05, .85], "sum": 1.,
        "solver": "SLSQP", "initial": PRIOR.tolist(), "maxiter": 1000, "ftol": 1e-12},
    "stack_ridge": {"input": P_COLS, "alpha": 100., "solver": "auto", "standard_scaler": True},
    "stack_mlp": {"input": P_COLS, "hidden_layer_sizes": [8], "activation": "relu", "solver": "adam",
        "alpha": .1, "batch_size": 256, "learning_rate_init": .001, "max_iter": 80,
        "early_stopping": False, "n_iter_no_change": 81, "random_state": SEED, "standard_scaler": True},
    "conditional_gate": {"input": G_COLS, "hidden": [8], "activation": "tanh", "outputs": 3,
        "coefficients": "0.05+0.85*softmax(logits)", "epochs": 120, "batch": "full",
        "optimizer": "Adam", "learning_rate": .01, "gradient_clip_norm": 2.,
        "objective": "weighted_MSE(sum(coefficients*P)/0.1,target_clipped/0.1)+0.001*weighted_mean(sum((coefficients-prior)^2))",
        "init": "torch_default_Linear_seeded", "dtype": "float32", "CPU_threads": 1,
        "deterministic_algorithms": True, "standard_scaler": True, "final_epoch_only": True},
    "ridge_then_hgb": {"input": P_COLS+G_COLS, "target": "target_clipped-p_ridge", "max_iter": 100,
        "max_depth": 2, "max_leaf_nodes": 7, "min_samples_leaf": 200, "l2_regularization": 5.,
        "learning_rate": .05, "early_stopping": False, "random_state": SEED,
        "standard_scaler": False, "output": "p_ridge+residual_prediction"},
    "hgb_then_ridge": {"input": P_COLS+G_COLS, "target": "target_clipped-p_hgb", "alpha": 100.,
        "solver": "auto", "standard_scaler": True, "output": "p_hgb+residual_prediction"},
    "decision_blend": {"coefficients_from": "learned_fixed", "new_fit": False,
        "mapping": "main policy combines three base TOP20 target vectors; not weighted scores followed by TOP20"},
    "total_predictive_fits_or_solves": 12, "fits_per_stage": 6,
    "no_2026_data_or_results": True, "no_hyperparameter_threshold_seed_search": True,
    "in_sample_metrics": "training diagnostics only; no method selection or claims of out-of-sample performance",
}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def write_once(path, value):
    path = Path(path)
    text = json_text(value)
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise RuntimeError(f"FROZEN_ARTIFACT_CONFLICT:{path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def write_design():
    path = ARTIFACTS / "META_DESIGN.json"
    write_once(path, DESIGN)
    return path


def check_lock(lock_path=None):
    design_path = write_design()
    lock_path = Path(lock_path or ROOT / "DESIGN_LOCK.json")
    if not lock_path.is_file():
        raise RuntimeError("ROOT_DESIGN_LOCK_REQUIRED_BEFORE_META_PREPARATION_OR_FITS")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("status") != "LOCKED_BEFORE_NEW_FITS" or lock.get("fit_enabled") is not True:
        raise RuntimeError("ROOT_DESIGN_DOES_NOT_AUTHORIZE_NEW_FITS")
    if lock.get("meta_design_sha256") != sha(design_path):
        raise RuntimeError("ROOT_LOCK_META_DESIGN_HASH_MISMATCH")
    return lock_path, lock


def key_hash(stage, date, ticker):
    value = f"{SEED}|{stage}|{pd.Timestamp(date).date().isoformat()}|{ticker}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def equal_date_quotas(counts, cap, stage):
    """Waterfill approximately equal daily quotas without target-dependent choices."""
    cap = min(int(cap), int(counts.sum()))
    keys = list(counts.index)
    date_order = sorted(keys, key=lambda d: key_hash(stage, d, "DATE_QUOTA"))
    quota = dict.fromkeys(keys, 0)
    remaining = cap
    while remaining:
        available = [d for d in date_order if quota[d] < int(counts.loc[d])]
        if not available:
            break
        # Assign one complete quota level where possible, then deterministic remainder.
        step = max(1, remaining // len(available))
        for date in available:
            take = min(step, int(counts.loc[date])-quota[date], remaining)
            quota[date] += take
            remaining -= take
            if remaining == 0:
                break
    if sum(quota.values()) != cap:
        raise AssertionError("QUOTA_COUNT_MISMATCH")
    return quota


def select_stage(frame, stage, cap=40000):
    """Return selected training records and complete per-key exclusion reasons."""
    if stage not in STAGES:
        raise ValueError(f"UNKNOWN_META_STAGE:{stage}")
    required = KEY_COLS + P_COLS + G_COLS + LABEL_COLS
    missing = sorted(set(required)-set(frame.columns))
    if missing:
        raise ValueError(f"META_INPUT_COLUMNS_MISSING:{missing}")
    data = frame[required].copy().reset_index(drop=True)
    for name in ["signal_date", "target_end_date", "base_cutoff"]:
        data[name] = pd.to_datetime(data[name], errors="coerce")
    if data.duplicated(KEY_COLS).any():
        raise ValueError("DUPLICATE_META_OOF_KEY")
    if data.signal_date.isna().any() or not data.signal_date.dt.year.isin([2024, 2025]).all():
        raise ValueError("META_SOURCE_MUST_ONLY_CONTAIN_2024_2025_SIGNALS")
    if not data.ticker.map(lambda x: isinstance(x, str) and bool(x.strip())).all():
        raise ValueError("INVALID_META_OOF_TICKER")
    if data.base_cutoff.isna().any() or data.base_cutoff.gt(data.signal_date).any():
        raise ValueError("OOF_BASE_CUTOFF_AFTER_SIGNAL_OR_UNKNOWN")
    required_base_cutoff = data.signal_date.dt.year.map({2024: pd.Timestamp("2024-01-01"),
                                                      2025: pd.Timestamp("2025-01-01")})
    if not data.base_cutoff.eq(required_base_cutoff).all():
        raise ValueError("OOF_BASE_CUTOFF_MUST_MATCH_FIXED_ANNUAL_OOF_VINTAGE")
    # Date contexts are market state, not ticker-specific label-derived observations.
    for name in G_COLS:
        finite = np.isfinite(pd.to_numeric(data[name], errors="coerce"))
        if data.loc[finite].groupby("signal_date")[name].nunique().gt(1).any():
            raise ValueError(f"GATE_CONTEXT_NOT_CONSTANT_WITHIN_DATE:{name}")
    cutoff = pd.Timestamp(STAGES[stage])
    reasons = pd.Series("", index=data.index, dtype=str)

    def exclude(mask, reason):
        reasons.loc[mask] = reasons.loc[mask].map(lambda old: old + "|" + reason if old else reason)

    exclude(data.signal_date.ge(cutoff), "SIGNAL_NOT_BEFORE_STAGE_CUTOFF")
    exclude(data.target_end_date.isna(), "TARGET_END_UNKNOWN")
    exclude(data.target_end_date.ge(cutoff), "TARGET_NOT_MATURE_BEFORE_STAGE_CUTOFF")
    exclude(data.target_end_date.le(data.signal_date), "TARGET_END_NOT_AFTER_SIGNAL")
    exclude(~data.target_context_available.fillna(False).astype(bool), "TARGET_CONTEXT_UNAVAILABLE")
    for name in ["target", *P_COLS, *G_COLS]:
        data[name] = pd.to_numeric(data[name], errors="coerce")
        exclude(~np.isfinite(data[name]), "NONFINITE_" + name.upper())
    eligible = data.loc[reasons.eq("")].copy()
    if eligible.empty:
        raise ValueError(f"NO_ELIGIBLE_META_TRAINING_KEYS:{stage}")
    eligible["selection_hash"] = [key_hash(stage, d, t) for d, t in eligible[KEY_COLS].itertuples(index=False, name=None)]
    counts = eligible.groupby("signal_date").size()
    quotas = equal_date_quotas(counts, cap, stage)
    selected_indices = []
    for date, group in eligible.groupby("signal_date", sort=True):
        selected_indices.extend(group.sort_values(["selection_hash", "ticker"], kind="stable").head(quotas[date]).index)
    exclude(reasons.eq("") & ~data.index.isin(selected_indices), "FIXED_DATE_BALANCED_HASH_CAP")
    selected = eligible.loc[selected_indices].sort_values(KEY_COLS, kind="stable").copy()
    n, dates = len(selected), selected.signal_date.nunique()
    selected["sample_weight"] = n / (dates * selected.groupby("signal_date").signal_date.transform("size"))
    selected["target_clipped_for_training"] = selected.target.clip(-.3, .3)
    selected["meta_stage"] = stage
    selected["meta_cutoff"] = cutoff
    exclusions = data.loc[reasons.ne(""), KEY_COLS + ["target_end_date", "base_cutoff", "target_context_available"]].copy()
    exclusions["exclusion_reasons"] = reasons.loc[exclusions.index]
    exclusions["meta_stage"] = stage
    exclusions["meta_cutoff"] = cutoff
    if len(selected)+len(exclusions) != len(data):
        raise AssertionError("SELECTED_EXCLUDED_PARTITION_FAILED")
    if not selected.target_end_date.lt(cutoff).all() or not selected.base_cutoff.le(selected.signal_date).all():
        raise AssertionError("META_TEMPORAL_PURGE_FAILED")
    if not np.isclose(selected.sample_weight.sum(), n):
        raise AssertionError("DATE_WEIGHT_NORMALIZATION_FAILED")
    return selected.reset_index(drop=True), exclusions.reset_index(drop=True)


def prepare(input_path=INPUT, lock_path=None):
    lock_path, lock = check_lock(lock_path)
    input_path = Path(input_path).resolve()
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    if (ARTIFACTS / "TRAIN_RECEIPT.json").exists():
        raise RuntimeError("COMPLETED_META_TRAINING_PRESERVED")
    input_hash = sha(input_path)
    required = KEY_COLS + P_COLS + G_COLS + LABEL_COLS
    frame = pd.read_parquet(input_path, columns=required)
    outputs, stages = {}, {}
    for stage in STAGES:
        selected, exclusions = select_stage(frame, stage)
        selected_path = ARTIFACTS / f"SELECTED_KEYS_{stage}.parquet"
        excluded_path = ARTIFACTS / f"ALL_EXCLUSIONS_{stage}.parquet"
        for path, df in [(selected_path, selected), (excluded_path, exclusions)]:
            if path.exists():
                old = pd.read_parquet(path)
                pd.testing.assert_frame_equal(old, df)
            else:
                df.to_parquet(path, index=False)
            outputs[str(path)] = sha(path)
        stage_counts = selected.groupby("signal_date").agg(selected_keys=("ticker", "size"), total_weight=("sample_weight", "sum"))
        stages[stage] = {"cutoff_exclusive": STAGES[stage], "selected_keys": len(selected),
            "selected_dates": len(stage_counts), "all_excluded_keys": len(exclusions),
            "selected_signal_min": str(selected.signal_date.min().date()), "selected_signal_max": str(selected.signal_date.max().date()),
            "selected_target_end_max": str(selected.target_end_date.max().date()),
            "selected_base_cutoff_max": str(selected.base_cutoff.max().date()),
            "selected_keys_per_date_min": int(stage_counts.selected_keys.min()),
            "selected_keys_per_date_max": int(stage_counts.selected_keys.max()),
            "date_total_weight_min": float(stage_counts.total_weight.min()),
            "date_total_weight_max": float(stage_counts.total_weight.max()),
            "target_clipped_count": int(selected.target.ne(selected.target_clipped_for_training).sum()),
            "exclusion_reason_counts": exclusions.exclusion_reasons.str.split("|").explode().value_counts().astype(int).to_dict()}
    if sha(input_path) != input_hash:
        raise RuntimeError("OOF_INPUT_CHANGED_DURING_PREPARATION")
    contract = {"status": "META_PRE_FIT_LOCKED", "design_sha256": sha(ARTIFACTS/"META_DESIGN.json"),
        "root_lock_path": str(lock_path.resolve()), "root_lock_sha256": sha(lock_path),
        "source_path": str(input_path), "source_sha256": input_hash,
        "meta_source_sha256": sha(__file__), "training_artifact_sha256": outputs,
        "source_rows": len(frame), "stages": stages,
        "runtime_versions": {name: importlib.metadata.version(name) for name in ["numpy", "pandas", "scikit-learn", "scipy", "torch"]},
        "model_fits_started": 0, "planned_predictive_fits_or_solves": 12,
        "all_features_in_training": P_COLS+G_COLS, "targets_available_only_in_training": LABEL_COLS,
        "no_2026_rows": True, "fit_choice_depends_on_2026": False}
    write_once(ARTIFACTS / "META_PRE_FIT.json", contract)
    return contract


def normalized_weights(values):
    weights = np.asarray(values, dtype=float)
    if weights.ndim != 1 or not np.isfinite(weights).all() or np.any(weights <= 0):
        raise ValueError("INVALID_META_SAMPLE_WEIGHTS")
    return weights / weights.sum()


def fit_convex(P, y, sample_weight):
    weights = normalized_weights(sample_weight)
    x, target = P/.1, y/.1
    def objective(c):
        residual = x@c-target
        return float(weights@(residual**2) + .001*np.sum((c-PRIOR)**2))
    def gradient(c):
        return 2*x.T@(weights*(x@c-target)) + .002*(c-PRIOR)
    result = minimize(objective, PRIOR.copy(), method="SLSQP", jac=gradient,
        bounds=[(.05, .85)]*3, constraints={"type": "eq", "fun": lambda c: c.sum()-1,
            "jac": lambda c: np.ones(3)}, options={"ftol": 1e-12, "maxiter": 1000, "disp": False})
    if not result.success or not np.isclose(result.x.sum(), 1., atol=1e-9) or np.any(result.x<.05-1e-9) or np.any(result.x>.85+1e-9):
        raise RuntimeError(f"FIXED_CONVEX_SOLVE_FAILED:{result.message}")
    return result.x, {"optimizer": "SLSQP", "success": bool(result.success), "iterations": int(result.nit),
                      "objective": float(result.fun), "coefficients": result.x.tolist()}


def fit_gate(P, G, y, sample_weight):
    # Torch is training-only. Inference reads plain numpy parameters.
    import torch
    torch.manual_seed(SEED)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    scaler = StandardScaler().fit(G, sample_weight=sample_weight)
    z = torch.tensor(scaler.transform(G), dtype=torch.float32)
    p = torch.tensor(P, dtype=torch.float32)
    target = torch.tensor(y, dtype=torch.float32)
    weight = torch.tensor(normalized_weights(sample_weight), dtype=torch.float32)
    prior = torch.tensor(PRIOR, dtype=torch.float32)
    network = torch.nn.Sequential(torch.nn.Linear(4, 8), torch.nn.Tanh(), torch.nn.Linear(8, 3))
    optimizer = torch.optim.Adam(network.parameters(), lr=.01)
    losses = []
    for epoch in range(120):
        optimizer.zero_grad(set_to_none=True)
        coeff = .05 + .85*torch.softmax(network(z), dim=1)
        prediction = torch.sum(coeff*p, dim=1)
        loss = torch.sum(weight*((prediction-target)/.1)**2) + .001*torch.sum(weight*torch.sum((coeff-prior)**2, dim=1))
        if not torch.isfinite(loss):
            raise RuntimeError("NONFINITE_FIXED_GATE_TRAINING_LOSS")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(network.parameters(), 2.)
        optimizer.step()
        losses.append(float(loss.detach()))
    params = {"mean": scaler.mean_, "scale": scaler.scale_,
        "w1": network[0].weight.detach().numpy(), "b1": network[0].bias.detach().numpy(),
        "w2": network[2].weight.detach().numpy(), "b2": network[2].bias.detach().numpy()}
    numpy_prediction, coeff = predict_gate(params, P, G)
    with torch.no_grad():
        torch_prediction = torch.sum((.05+.85*torch.softmax(network(z), dim=1))*p, dim=1).numpy()
    error = float(np.max(np.abs(numpy_prediction-torch_prediction)))
    if error > 1e-6:
        raise AssertionError(f"GATE_NUMPY_TORCH_PARITY_FAILED:{error}")
    receipt = {"epochs": 120, "final_epoch_only": True, "loss_by_epoch": losses,
        "numpy_torch_max_prediction_error": error, "coefficient_min": float(coeff.min()),
        "coefficient_max": float(coeff.max()), "coefficient_sum_error_max": float(np.max(np.abs(coeff.sum(axis=1)-1.)))}
    return params, receipt


def validate_inputs(P, G):
    P, G = np.asarray(P, dtype=float), np.asarray(G, dtype=float)
    if P.ndim != 2 or P.shape[1] != 3 or G.ndim != 2 or G.shape != (len(P), 4):
        raise ValueError("META_PREDICT_REQUIRES_N_BY_3_P_AND_N_BY_4_G")
    if not np.isfinite(P).all() or not np.isfinite(G).all():
        raise ValueError("NONFINITE_META_INFERENCE_FEATURE")
    return P, G


def predict_gate(params, P, G):
    P, G = validate_inputs(P, G)
    z = ((G-params["mean"])/params["scale"]).astype(np.float32)
    hidden = np.tanh(z@params["w1"].T+params["b1"])
    logits = hidden@params["w2"].T+params["b2"]
    logits -= logits.max(axis=1, keepdims=True)
    probs = np.exp(logits)
    coeff = .05+.85*probs/probs.sum(axis=1, keepdims=True)
    return np.sum(P*coeff, axis=1), coeff


def diagnostic_metrics(prediction, target_clipped, target_raw, sample_weight):
    weights = normalized_weights(sample_weight)
    return {"status": "IN_SAMPLE_TRAINING_DIAGNOSTIC_ONLY_NOT_FOR_MODEL_SELECTION",
        "weighted_mse_clipped_target": float(weights@((prediction-target_clipped)**2)),
        "weighted_mse_unclipped_target_diagnostic": float(weights@((prediction-target_raw)**2)),
        "weighted_prediction_mean": float(weights@prediction),
        "prediction_min": float(np.min(prediction)), "prediction_max": float(np.max(prediction))}


class FrozenMeta:
    """Frozen stage inference; decision_blend uses .coefficients in main policy."""
    def __init__(self, stage, artifacts=ARTIFACTS):
        if stage not in STAGES:
            raise ValueError(f"UNKNOWN_META_STAGE:{stage}")
        self.stage, self.folder = stage, Path(artifacts)/stage
        receipt_path = self.folder / "STAGE_RECEIPT.json"
        if not receipt_path.is_file():
            raise RuntimeError(f"META_STAGE_NOT_TRAINED:{stage}")
        self.receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if self.receipt.get("status") != "PASS" or self.receipt.get("predictive_fits_or_solves") != 6:
            raise RuntimeError("META_STAGE_RECEIPT_NOT_COMPLETE")
        if self.receipt.get("stage") != stage or self.receipt.get("cutoff_exclusive") != STAGES[stage]:
            raise RuntimeError("META_STAGE_RECEIPT_STAGE_OR_CUTOFF_MISMATCH")
        for filename, digest in self.receipt["artifact_sha256"].items():
            if sha(self.folder/filename) != digest:
                raise RuntimeError(f"FROZEN_META_ARTIFACT_HASH_MISMATCH:{filename}")
        learned = json.loads((self.folder/"learned_fixed.json").read_text(encoding="utf-8"))
        if learned.get("stage") != stage or learned.get("cutoff_exclusive") != STAGES[stage]:
            raise RuntimeError("LEARNED_FIXED_STAGE_OR_CUTOFF_MISMATCH")
        self.coefficients = np.asarray(learned["coefficients"])
        self.models = {}
        for method in ["stack_ridge", "stack_mlp", "ridge_then_hgb", "hgb_then_ridge"]:
            bundle = joblib.load(self.folder/(method+".joblib"))
            if bundle.get("stage") != stage or bundle.get("cutoff_exclusive") != STAGES[stage]:
                raise RuntimeError(f"META_BUNDLE_STAGE_OR_CUTOFF_MISMATCH:{method}")
            self.models[method] = bundle
        with np.load(self.folder/"conditional_gate.npz", allow_pickle=False) as arrays:
            if ("_stage" not in arrays.files or "_cutoff_exclusive" not in arrays.files
                    or arrays["_stage"].item() != stage or arrays["_cutoff_exclusive"].item() != STAGES[stage]):
                raise RuntimeError("META_GATE_STAGE_OR_CUTOFF_MISMATCH")
            self.gate = {key: arrays[key].copy() for key in arrays.files if not key.startswith("_")}

    def gate_weights(self, G):
        G = np.asarray(G, dtype=float)
        if G.ndim != 2 or G.shape[1] != 4 or not np.isfinite(G).all():
            raise ValueError("GATE_WEIGHTS_REQUIRE_FINITE_N_BY_4_CONTEXT")
        if len(G) == 0:
            return np.empty((0, 3), dtype=float)
        return predict_gate(self.gate, np.zeros((len(G), 3)), G)[1]

    def predict(self, method, P, G):
        if method == "decision_blend":
            raise ValueError("DECISION_BLEND_REQUIRES_BASE_TOP20_TARGET_VECTORS_AND_META_COEFFICIENTS_NOT_SCORE_FUSION")
        P, G = validate_inputs(P, G)
        if len(P) == 0:
            return np.empty(0, dtype=float)
        if method == "fixed_pred":
            return P@PRIOR
        if method == "learned_fixed":
            return P@self.coefficients
        if method == "conditional_gate":
            return predict_gate(self.gate, P, G)[0]
        if method not in self.models:
            raise ValueError(f"UNKNOWN_META_METHOD:{method}")
        bundle = self.models[method]
        X = P if method in ["stack_ridge", "stack_mlp"] else np.column_stack([P, G])
        transformed = bundle["scaler"].transform(X) if bundle["scaler"] is not None else X
        result = bundle["model"].predict(transformed)
        if method == "ridge_then_hgb":
            result = result+P[:, 0]
        if method == "hgb_then_ridge":
            result = result+P[:, 1]
        return result


def load_meta(stage):
    return FrozenMeta(stage)


def fit_all(input_path=INPUT, lock_path=None):
    """Called only after explicit root authorization; exactly six models per stage."""
    contract = prepare(input_path, lock_path)
    started_path = ARTIFACTS/"FIT_STARTED.json"
    if started_path.exists():
        raise RuntimeError("META_FIT_ALREADY_STARTED_PARTIAL_OR_COMPLETE_REQUIRES_INSPECTION")
    for stage in STAGES:
        if (ARTIFACTS/stage).exists():
            raise RuntimeError(f"META_STAGE_DIRECTORY_ALREADY_EXISTS:{stage}")
    write_once(started_path, {"status": "FIXED_12_FITS_STARTED", "pre_fit_sha256": sha(ARTIFACTS/"META_PRE_FIT.json"),
        "design_sha256": sha(ARTIFACTS/"META_DESIGN.json"), "meta_source_sha256": sha(__file__),
        "root_lock_sha256": contract["root_lock_sha256"]})
    stage_receipts = {}
    for stage in STAGES:
        folder = ARTIFACTS/stage
        folder.mkdir()
        selected_path = ARTIFACTS/f"SELECTED_KEYS_{stage}.parquet"
        data = pd.read_parquet(selected_path)
        P, G = data[P_COLS].to_numpy(float), data[G_COLS].to_numpy(float)
        y, w = data.target_clipped_for_training.to_numpy(float), data.sample_weight.to_numpy(float)
        raw_y = data.target.to_numpy(float)
        artifact_files, fit_receipts = [], []
        for method in TRAIN_METHODS:
            note = {}
            with warnings.catch_warnings(record=True) as captured:
                warnings.simplefilter("always")
                if method == "learned_fixed":
                    coefficients, note = fit_convex(P, y, w)
                    model_path = folder/"learned_fixed.json"
                    write_once(model_path, {"coefficients": coefficients.tolist(), "prior": PRIOR.tolist(),
                                           "stage": stage, "cutoff_exclusive": STAGES[stage]})
                    prediction = P@coefficients
                elif method == "conditional_gate":
                    params, note = fit_gate(P, G, y, w)
                    model_path = folder/"conditional_gate.npz"
                    np.savez(model_path, **params, _stage=np.array(stage), _cutoff_exclusive=np.array(STAGES[stage]))
                    prediction = predict_gate(params, P, G)[0]
                else:
                    X = P if method in ["stack_ridge", "stack_mlp"] else np.column_stack([P, G])
                    scaler = None if method == "ridge_then_hgb" else StandardScaler().fit(X, sample_weight=w)
                    transformed = X if scaler is None else scaler.transform(X)
                    if method in ["stack_ridge", "hgb_then_ridge"]:
                        model = Ridge(alpha=100., solver="auto")
                    elif method == "stack_mlp":
                        model = MLPRegressor(hidden_layer_sizes=(8,), alpha=.1, max_iter=80, batch_size=256,
                            early_stopping=False, n_iter_no_change=81, random_state=SEED,
                            activation="relu", solver="adam", learning_rate_init=.001)
                    else:
                        model = HistGradientBoostingRegressor(max_iter=100, max_depth=2, max_leaf_nodes=7,
                            min_samples_leaf=200, l2_regularization=5., learning_rate=.05,
                            early_stopping=False, random_state=SEED)
                    train_target = y-P[:, 0] if method == "ridge_then_hgb" else y-P[:, 1] if method == "hgb_then_ridge" else y
                    with threadpool_limits(limits=2):
                        model.fit(transformed, train_target, sample_weight=w)
                    model_path = folder/(method+".joblib")
                    joblib.dump({"model": model, "scaler": scaler, "input_columns": P_COLS if X.shape[1] == 3 else P_COLS+G_COLS,
                                 "stage": stage, "cutoff_exclusive": STAGES[stage]}, model_path)
                    prediction = model.predict(transformed)
                    if method == "ridge_then_hgb":
                        prediction += P[:, 0]
                    if method == "hgb_then_ridge":
                        prediction += P[:, 1]
                    if getattr(model, "n_iter_", None) is not None:
                        note["actual_iterations"] = int(model.n_iter_)
                    if method == "stack_mlp" and model.n_iter_ != 80:
                        raise AssertionError("FIXED_STACK_MLP_DID_NOT_RUN_80_ITERATIONS")
                    if method == "ridge_then_hgb" and model.n_iter_ != 100:
                        raise AssertionError("FIXED_RESIDUAL_HGB_DID_NOT_RUN_100_ITERATIONS")
            if not np.isfinite(prediction).all():
                raise RuntimeError(f"NONFINITE_META_TRAINING_PREDICTION:{stage}:{method}")
            fit_receipt = {"stage": stage, "method": method, "model_fit_or_solve_count": 1,
                "sample_weight_used": True, "sample_weight_sum": float(w.sum()), "training_keys": len(data),
                "training_dates": int(data.signal_date.nunique()), "cutoff_exclusive": STAGES[stage],
                "selected_keys_sha256": sha(selected_path), "pre_fit_sha256": sha(ARTIFACTS/"META_PRE_FIT.json"),
                "artifact": model_path.name, "artifact_sha256": sha(model_path), "details": note,
                "warnings": [str(item.message) for item in captured],
                "training_diagnostics": diagnostic_metrics(prediction, y, raw_y, w),
                "metric_based_selection_or_refit": False, "2026_data_consumed": False}
            receipt_path = folder/(method+"_FIT_RECEIPT.json")
            write_once(receipt_path, fit_receipt)
            artifact_files.extend([model_path, receipt_path]); fit_receipts.append(fit_receipt)
        stage_receipt = {"status": "PASS", "stage": stage, "cutoff_exclusive": STAGES[stage],
            "predictive_fits_or_solves": 6, "selected_keys_sha256": sha(selected_path),
            "artifact_sha256": {path.name: sha(path) for path in artifact_files},
            "all_training_diagnostics_in_sample_only": True}
        write_once(folder/"STAGE_RECEIPT.json", stage_receipt)
        frozen = FrozenMeta(stage)
        for method in SCORE_METHODS:
            inference = frozen.predict(method, P, G)
            if len(inference) != len(P) or not np.isfinite(inference).all():
                raise AssertionError(f"FROZEN_META_LOAD_PREDICT_FAILED:{stage}:{method}")
        stage_receipts[stage] = {"receipt_sha256": sha(folder/"STAGE_RECEIPT.json"), "predictive_fits_or_solves": 6}
    if sha(contract["source_path"]) != contract["source_sha256"] or sha(contract["root_lock_path"]) != contract["root_lock_sha256"]:
        raise RuntimeError("SOURCE_OR_ROOT_LOCK_CHANGED_DURING_META_TRAINING")
    if sha(__file__) != contract["meta_source_sha256"]:
        raise RuntimeError("META_TRAINING_CODE_CHANGED_AFTER_PRE_FIT")
    receipt = {"status": "PASS", "stages": stage_receipts, "predictive_fits_or_solves": 12,
        "no_2026_data_or_results": True, "inputs_unchanged": True,
        "root_design_lock_unchanged": True, "no_metric_based_selection": True,
        "pre_fit_sha256": sha(ARTIFACTS/"META_PRE_FIT.json"),
        "meta_design_sha256": sha(ARTIFACTS/"META_DESIGN.json"),
        "source_sha256": sha(__file__), "in_sample_metrics_are_training_diagnostics_only": True}
    write_once(ARTIFACTS/"TRAIN_RECEIPT.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write-design", action="store_true")
    action.add_argument("--prepare", action="store_true")
    action.add_argument("--fit", action="store_true")
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--lock", type=Path, default=ROOT/"DESIGN_LOCK.json")
    args = parser.parse_args()
    if args.write_design:
        path = write_design()
        print(json_text({"status": "DESIGN_ONLY_NO_FITS", "path": str(path), "sha256": sha(path)}))
    elif args.prepare:
        print(json_text(prepare(args.input, args.lock)))
    else:
        print(json_text(fit_all(args.input, args.lock)))


if __name__ == "__main__":
    main()
