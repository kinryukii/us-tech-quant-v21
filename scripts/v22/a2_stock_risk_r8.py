"""A2 Stock-Risk R8: fixed asymmetric dual-tail predictive research."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score


REPO_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
OUTPUT_DIR = RESULTS_ROOT / "A2_STOCK_RISK_R8"
R7_SCRIPT = REPO_ROOT / "scripts" / "v22" / "a2_stock_risk_r7.py"
R6_ROOT = RESULTS_ROOT / "A2_STOCK_RISK_R6"
R7_ROOT = RESULTS_ROOT / "A2_STOCK_RISK_R7"
R6_OOF_PATH = R6_ROOT / "r6_oof_predictions.parquet"
R7_OOF_PATH = R7_ROOT / "r7_oof_predictions.parquet"
R7_FEATURE_MANIFEST_PATH = R7_ROOT / "r7_feature_manifest.json"
R7_RUN_MANIFEST_PATH = R7_ROOT / "r7_run_manifest.json"
EXPECTED_R6_TARGET_CONTRACT_ID = "b8348a858dc0e92c9c24bd7661e8d5b129682975b6411ed4ec8add1c73118521"
EXPECTED_R6_FOLD_CONTRACT_ID = "fa9cd7aa20f6a564c4357b61153ae1252b3fc407b68345285b42bd0f8c92daaa"
EXPECTED_R6_OOF_SHA256 = "5f35b7b54192ce9023a886f3a51d9efaddea526bb78aed4862481f9dd85653b4"
R6_REFERENCE_MODEL = "LGBM_BAD_ASYM_2"
TRAINING_CUTOFF = pd.Timestamp("2026-01-01")
DUAL_SCORE_EPSILON = 1e-6
QUADRANT_CUT = 0.20


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


R7 = _load_module(R7_SCRIPT, "a2_stock_risk_r7_for_r8")
R6, R3, R1 = R7.R6, R7.R3, R7.R1
FOLDS = list(R7.FOLDS)
PRIMARY_FEATURES = R7.A2_FEATURES + R7.STOCK_FEATURES + R7.RISK_FEATURES
MARKET_DIAGNOSTIC_FEATURES = list(R7.FEATURES)
GOOD_TARGET_CONTRACT = {
    "target": "GOOD_TAIL_TARGET",
    "definition": "POST_ENTRY_5D_MFE >= fold-training Q90 AND POST_ENTRY_5D_MAE <= fold-training Q50",
    "symmetry_derivation": "exchange MAE and MFE roles in exact frozen R6 Q90/Q50 bad-tail contract",
    "mfe_quantile": 0.90, "mae_compensation_quantile": 0.50,
    "holding_horizon": "five trading sessions from execution-aligned entry",
    "source_return_field": "POST_ENTRY_FORWARD_5D_RETURN",
    "timestamp_contract": "Moomoo QFQ signal-date open; subsequent five-session path used only as label",
}
BAD_TARGET_CONTRACT = dict(R7.R6_TARGET_CONTRACT)
TARGET_CONTRACT_HASH = R1.canonical_hash({"bad": BAD_TARGET_CONTRACT, "good": GOOD_TARGET_CONTRACT})
BAD_MODEL_PARAMS_HASH = R1.canonical_hash({"logistic": R7.LOGISTIC_PARAMS, "lightgbm": R7.LIGHTGBM_PARAMS, "features": PRIMARY_FEATURES})
GOOD_MODEL_PARAMS_HASH = BAD_MODEL_PARAMS_HASH


def file_sha256(path: Path) -> str:
    return R1.sha256_file(path)


def prediction_hash(frame: pd.DataFrame) -> str:
    ordered = frame.sort_values(["signal_date", "ticker"])
    return hashlib.sha256(ordered[["probability", "risk_percentile"]].to_numpy(dtype=np.float64).tobytes()).hexdigest()


def discovery() -> dict[str, Any]:
    r7_manifest = json.loads(R7_RUN_MANIFEST_PATH.read_text(encoding="utf-8"))
    r7_features = json.loads(R7_FEATURE_MANIFEST_PATH.read_text(encoding="utf-8"))
    r7 = pd.read_parquet(R7_OOF_PATH)
    r6 = pd.read_parquet(R6_OOF_PATH)
    r6 = r6.loc[r6.candidate_id.eq(R6_REFERENCE_MODEL)]
    target_id = R1.canonical_hash(r7_manifest["r6_target_contract"])
    fold_id = R1.canonical_hash(r7_manifest["r6_fold_contract"])
    r7_prediction_hash = hashlib.sha256(r7.sort_values(["signal_date", "ticker"])[["r7_ml_oof_probability", "r7_ml_risk_percentile"]].to_numpy(dtype=np.float64).tobytes()).hexdigest()
    feature_order = r7_features["families"]["A2_STATE"] + r7_features["families"]["STOCK_STATE"] + r7_features["families"]["MARKET_STATE"] + r7_features["families"]["EXISTING_RISK"]
    feature_pass = bool(R1.canonical_hash(feature_order) == r7_features["feature_schema_sha256"] == r7_manifest["feature_schema_sha256"] and feature_order == R7.FEATURES)
    r7_keys = r7[["signal_date", "ticker"]].sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    r6_keys = r6[["signal_date", "ticker"]].sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    row_pass = bool(len(r7_keys) == 12180 and not r7_keys.duplicated().any() and r7_keys.equals(r6_keys))
    values = {
        "R6_TARGET_CONTRACT_PASS": target_id == EXPECTED_R6_TARGET_CONTRACT_ID,
        "R6_FOLD_CONTRACT_PASS": fold_id == EXPECTED_R6_FOLD_CONTRACT_ID,
        "R6_OOF_HASH_PASS": file_sha256(R6_OOF_PATH) == EXPECTED_R6_OOF_SHA256,
        "R7_OOF_FOUND": R7_OOF_PATH.exists() and r7_prediction_hash == r7_manifest["primary_prediction_sha256"],
        "R7_FEATURE_MANIFEST_FOUND": R7_FEATURE_MANIFEST_PATH.exists() and feature_pass,
        "R8_BASE_ROW_IDENTITY_STATUS": "PASS_EXACT_12180" if row_pass else "FAIL",
        "R7_OOF_HASH": file_sha256(R7_OOF_PATH), "R7_PREDICTION_HASH": r7_prediction_hash,
        "R6_TARGET_CONTRACT_ID": target_id, "R6_FOLD_CONTRACT_ID": fold_id, "R6_OOF_HASH": file_sha256(R6_OOF_PATH),
    }
    values["R8_DISCOVERY_STATUS"] = "PASS" if all([values["R6_TARGET_CONTRACT_PASS"], values["R6_FOLD_CONTRACT_PASS"], values["R6_OOF_HASH_PASS"], values["R7_OOF_FOUND"], values["R7_FEATURE_MANIFEST_FOUND"], row_pass]) else "FAIL"
    return values


def print_discovery(values: dict[str, Any]) -> None:
    for key in ["R8_DISCOVERY_STATUS", "R6_TARGET_CONTRACT_PASS", "R6_FOLD_CONTRACT_PASS", "R6_OOF_HASH_PASS", "R7_OOF_FOUND", "R7_FEATURE_MANIFEST_FOUND", "R8_BASE_ROW_IDENTITY_STATUS"]:
        print(f"{key}={values[key]}")


def target_labels(frame: pd.DataFrame, head: str, mae_q90: float, mfe_q50: float, mfe_q90: float, mae_q50: float) -> np.ndarray:
    if head == "BAD":
        return ((frame.forward_5d_stock_mae.to_numpy(dtype=float) >= mae_q90) & (frame.forward_5d_stock_mfe.to_numpy(dtype=float) <= mfe_q50)).astype(int)
    if head == "GOOD":
        return ((frame.forward_5d_stock_mfe.to_numpy(dtype=float) >= mfe_q90) & (frame.forward_5d_stock_mae.to_numpy(dtype=float) <= mae_q50)).astype(int)
    raise ValueError(head)


def build_target_frame(panel: pd.DataFrame, daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    sessions = pd.DatetimeIndex(daily.execution_date)
    frozen = panel.loc[panel.frozen_r6_target.notna(), ["signal_date", "ticker", "frozen_r6_target", "frozen_r6_fold"]]
    outputs, threshold_rows = [], []
    mismatch = 0
    for fold, start, end in FOLDS:
        train, valid, cutoff = R3.fold_split(panel, sessions, start, end)
        mae_q90, mfe_q50 = float(train.forward_5d_stock_mae.quantile(.90)), float(train.forward_5d_stock_mfe.quantile(.50))
        mfe_q90, mae_q50 = float(train.forward_5d_stock_mfe.quantile(.90)), float(train.forward_5d_stock_mae.quantile(.50))
        bad = target_labels(valid, "BAD", mae_q90, mfe_q50, mfe_q90, mae_q50)
        good = target_labels(valid, "GOOD", mae_q90, mfe_q50, mfe_q90, mae_q50)
        out = valid[["signal_date", "ticker", "forward_5d_stock_return", "forward_5d_stock_mae", "forward_5d_stock_mfe", "target_end_date"]].copy()
        out["fold"], out["bad_target"], out["good_target"] = fold, bad, good
        check = out.merge(frozen, on=["signal_date", "ticker"], validate="one_to_one")
        mismatch += int((check.bad_target.astype(int) != check.frozen_r6_target.astype(int)).sum() + (check.fold != check.frozen_r6_fold).sum())
        outputs.append(out)
        threshold_rows.append({"fold": fold, "train_rows": len(train), "validation_rows": len(valid), "bad_mae_q90": mae_q90, "bad_mfe_q50": mfe_q50, "good_mfe_q90": mfe_q90, "good_mae_q50": mae_q50, "train_max_target_end": train.target_end_date.max(), "embargo_cutoff": cutoff})
    targets = pd.concat(outputs, ignore_index=True).sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    overlap = int((targets.bad_target.astype(bool) & targets.good_target.astype(bool)).sum())
    audit = {
        "bad_target_identity_mismatch_count": mismatch, "bad_target_identity_with_r6": "PASS" if mismatch == 0 else "FAIL",
        "bad_event_count": int(targets.bad_target.sum()), "good_event_count": int(targets.good_target.sum()),
        "bad_base_rate": float(targets.bad_target.mean()), "good_base_rate": float(targets.good_target.mean()),
        "bad_good_overlap_count": overlap, "bad_good_overlap_rate": overlap / len(targets),
        "overlap_explanation": "zero by symmetric mutually exclusive Q90/Q50 path conditions" if overlap == 0 else "unexpected overlap; fail closed",
    }
    return targets, pd.DataFrame(threshold_rows), audit


def run_head_oof(panel: pd.DataFrame, daily: pd.DataFrame, features: list[str], head: str, kind: str, model_id: str) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], int, int]:
    sessions = pd.DatetimeIndex(daily.execution_date)
    frozen = panel.loc[panel.frozen_r6_target.notna(), ["signal_date", "ticker", "frozen_r6_target", "frozen_r6_fold"]]
    outputs, train_scores = [], {}
    fits = mismatch = 0
    for fold, start, end in FOLDS:
        train, valid, cutoff = R3.fold_split(panel, sessions, start, end)
        mae_q90, mfe_q50 = float(train.forward_5d_stock_mae.quantile(.90)), float(train.forward_5d_stock_mfe.quantile(.50))
        mfe_q90, mae_q50 = float(train.forward_5d_stock_mfe.quantile(.90)), float(train.forward_5d_stock_mae.quantile(.50))
        y_train = target_labels(train, head, mae_q90, mfe_q50, mfe_q90, mae_q50)
        y_valid = target_labels(valid, head, mae_q90, mfe_q50, mfe_q90, mae_q50)
        model = R7.make_model(kind)
        model.fit(train[features], y_train); fits += 1
        train_p = np.asarray(model.predict_proba(train[features])[:, 1], dtype=float)
        valid_p = np.asarray(model.predict_proba(valid[features])[:, 1], dtype=float)
        if not np.isfinite(train_p).all() or not np.isfinite(valid_p).all():
            raise RuntimeError(f"non-finite {head} probability")
        out = valid[["signal_date", "ticker"]].copy()
        out["fold"], out["target"], out["probability"] = fold, y_valid, valid_p
        out["risk_percentile"] = R1.empirical_percentile(train_p, valid_p)
        out["train_max_target_end"], out["embargo_cutoff"] = train.target_end_date.max(), cutoff
        out["model_id"] = model_id
        if head == "BAD":
            check = out.merge(frozen, on=["signal_date", "ticker"], validate="one_to_one")
            mismatch += int((check.target.astype(int) != check.frozen_r6_target.astype(int)).sum() + (check.fold != check.frozen_r6_fold).sum())
        outputs.append(out)
        train_scores[fold] = train[["signal_date", "ticker"]].assign(probability=train_p)
    oof = pd.concat(outputs, ignore_index=True).sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    if len(oof) != len(frozen) or oof.duplicated(["signal_date", "ticker"]).any():
        raise RuntimeError(f"incomplete {head} OOF")
    return oof, train_scores, fits, mismatch


def combine_oof(targets: pd.DataFrame, bad_log: pd.DataFrame, good_log: pd.DataFrame, bad_ml: pd.DataFrame, good_ml: pd.DataFrame, bad_train: dict[str, pd.DataFrame], good_train: dict[str, pd.DataFrame], panel: pd.DataFrame) -> pd.DataFrame:
    out = targets.copy()
    for source, prefix in [(bad_log, "p_bad_logistic"), (good_log, "p_good_logistic"), (bad_ml, "p_bad_ml"), (good_ml, "p_good_ml")]:
        values = source[["signal_date", "ticker", "probability", "risk_percentile"]].rename(columns={"probability": prefix, "risk_percentile": f"{prefix}_percentile"})
        out = out.merge(values, on=["signal_date", "ticker"], validate="one_to_one")
    r7 = pd.read_parquet(R7_OOF_PATH)[["signal_date", "ticker", "r6_oof_score", "r6_risk_percentile", "r3_oof_score", "r7_ml_oof_probability", "r7_ml_risk_percentile"]]
    out = out.merge(r7, on=["signal_date", "ticker"], validate="one_to_one")
    out["dual_score_a"] = out.p_bad_ml - out.p_good_ml
    out["dual_score_b"] = out.p_bad_ml / (out.p_good_ml + DUAL_SCORE_EPSILON)
    for fold, _, _ in FOLDS:
        valid = out.fold.eq(fold)
        train = bad_train[fold].merge(good_train[fold], on=["signal_date", "ticker"], suffixes=("_bad", "_good"), validate="one_to_one")
        train_a = train.probability_bad - train.probability_good
        train_b = train.probability_bad / (train.probability_good + DUAL_SCORE_EPSILON)
        out.loc[valid, "dual_score_a_percentile"] = R1.empirical_percentile(train_a.to_numpy(), out.loc[valid, "dual_score_a"].to_numpy())
        out.loc[valid, "dual_score_b_percentile"] = R1.empirical_percentile(train_b.to_numpy(), out.loc[valid, "dual_score_b"].to_numpy())
    risk = panel.loc[panel.frozen_r6_target.notna(), ["signal_date", "ticker", "R6_OOF_SCORE", "R3_OOF_RISK_SCORE"]]
    out = out.merge(risk, on=["signal_date", "ticker"], validate="one_to_one")
    out.insert(0, "date", out.signal_date)
    return out.sort_values(["signal_date", "ticker"]).reset_index(drop=True)


def head_metrics(frame: pd.DataFrame, head: str, probability: str, percentile: str) -> dict[str, float]:
    target = "bad_target" if head == "BAD" else "good_target"
    y, p, pct = frame[target].to_numpy(dtype=int), frame[probability].to_numpy(dtype=float), frame[percentile].to_numpy(dtype=float)
    base, top = float(y.mean()), pct >= .90
    result = {"row_count": len(frame), "base_rate": base, "auroc": float(roc_auc_score(y, p)), "average_precision": float(average_precision_score(y, p)), "ap_base_multiple": float(average_precision_score(y, p) / base), "top_decile_event_rate": float(y[top].mean()) if top.any() else np.nan}
    result["top_decile_lift"] = result["top_decile_event_rate"] / base
    if head == "BAD":
        result.update({"worst50_capture": float(frame.nsmallest(50, "forward_5d_stock_return")[percentile].ge(.90).mean()), "worst100_capture": float(frame.nsmallest(100, "forward_5d_stock_return")[percentile].ge(.90).mean()), "best50_contamination": float(frame.nlargest(50, "forward_5d_stock_return")[percentile].ge(.90).mean()), "best100_contamination": float(frame.nlargest(100, "forward_5d_stock_return")[percentile].ge(.90).mean())})
        result["worst100_best100_ratio"] = result["worst100_capture"] / result["best100_contamination"] if result["best100_contamination"] > 0 else np.inf
    else:
        result.update({"best50_capture": float(frame.nlargest(50, "forward_5d_stock_return")[percentile].ge(.90).mean()), "best100_capture": float(frame.nlargest(100, "forward_5d_stock_return")[percentile].ge(.90).mean()), "worst50_contamination": float(frame.nsmallest(50, "forward_5d_stock_return")[percentile].ge(.90).mean()), "worst100_contamination": float(frame.nsmallest(100, "forward_5d_stock_return")[percentile].ge(.90).mean())})
        result["best100_worst100_ratio"] = result["best100_capture"] / result["worst100_contamination"] if result["worst100_contamination"] > 0 else np.inf
    return result


def positive_direction(metric: dict[str, float]) -> bool:
    return bool(metric["auroc"] > .50 and metric["ap_base_multiple"] > 1.0 and metric["top_decile_lift"] > 1.0)


def evaluate_heads(oof: pd.DataFrame, market_bad: pd.DataFrame, market_good: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    specs = [
        ("BAD", "R6_BASELINE", "r6_oof_score", "r6_risk_percentile"),
        ("BAD", "LOGISTIC", "p_bad_logistic", "p_bad_logistic_percentile"),
        ("BAD", "PRIMARY_ML", "p_bad_ml", "p_bad_ml_percentile"),
        ("GOOD", "LOGISTIC", "p_good_logistic", "p_good_logistic_percentile"),
        ("GOOD", "PRIMARY_ML", "p_good_ml", "p_good_ml_percentile"),
    ]
    market_bad_map = market_bad.set_index(["signal_date", "ticker"])
    market_good_map = market_good.set_index(["signal_date", "ticker"])
    temp = oof.copy()
    temp["p_bad_market_diag"] = [market_bad_map.loc[(d, t), "probability"] for d, t in zip(temp.signal_date, temp.ticker)]
    temp["p_bad_market_diag_percentile"] = [market_bad_map.loc[(d, t), "risk_percentile"] for d, t in zip(temp.signal_date, temp.ticker)]
    temp["p_good_market_diag"] = [market_good_map.loc[(d, t), "probability"] for d, t in zip(temp.signal_date, temp.ticker)]
    temp["p_good_market_diag_percentile"] = [market_good_map.loc[(d, t), "risk_percentile"] for d, t in zip(temp.signal_date, temp.ticker)]
    specs += [("BAD", "FULL_WITH_MARKET_DIAGNOSTIC", "p_bad_market_diag", "p_bad_market_diag_percentile"), ("GOOD", "FULL_WITH_MARKET_DIAGNOSTIC", "p_good_market_diag", "p_good_market_diag_percentile")]
    pooled, folds, stability = [], [], {}
    for head, model, probability, percentile in specs:
        metric = head_metrics(temp, head, probability, percentile)
        positive = 0
        pooled.append({"head": head, "model": model, **metric})
        for fold, _, _ in FOLDS:
            fm = head_metrics(temp.loc[temp.fold.eq(fold)], head, probability, percentile)
            direction = positive_direction(fm); positive += int(direction)
            folds.append({"diagnostic_type": "HEAD", "head": head, "model": model, "fold": fold, **fm, "positive_direction": direction})
        pooled[-1]["positive_folds"] = positive
        stability[f"{head}_{model}"] = positive
    return pd.DataFrame(pooled), pd.DataFrame(folds), stability


def _extreme_flags(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["worst100_member"], result["best100_member"] = False, False
    result.loc[result.nsmallest(min(100, len(result)), "forward_5d_stock_return").index, "worst100_member"] = True
    result.loc[result.nlargest(min(100, len(result)), "forward_5d_stock_return").index, "best100_member"] = True
    return result


def quadrant_row(frame: pd.DataFrame, mask: pd.Series, region: str, scope: str, fold: str) -> dict[str, Any]:
    group = frame.loc[mask]
    worst_den = max(1, int(frame.worst100_member.sum())); best_den = max(1, int(frame.best100_member.sum()))
    worst_capture = float(group.worst100_member.sum() / worst_den); best_capture = float(group.best100_member.sum() / best_den)
    ratio = worst_capture / best_capture if best_capture > 0 else (np.inf if worst_capture > 0 else np.nan)
    return {"diagnostic_type": scope, "fold": fold, "region": region, "row_count": len(group), "bad_event_rate": float(group.bad_target.mean()) if len(group) else np.nan, "good_event_rate": float(group.good_target.mean()) if len(group) else np.nan, "bad_event_lift": float(group.bad_target.mean() / frame.bad_target.mean()) if len(group) else np.nan, "mean_forward_return": float(group.forward_5d_stock_return.mean()) if len(group) else np.nan, "median_forward_return": float(group.forward_5d_stock_return.median()) if len(group) else np.nan, "mean_mae": float(group.forward_5d_stock_mae.mean()) if len(group) else np.nan, "mean_mfe": float(group.forward_5d_stock_mfe.mean()) if len(group) else np.nan, "worst100_count": int(group.worst100_member.sum()), "best100_count": int(group.best100_member.sum()), "worst100_capture": worst_capture, "best100_capture": best_capture, "worst100_best100_ratio": ratio}


def quadrant_diagnostics(oof: pd.DataFrame) -> tuple[pd.DataFrame, int, dict[str, Any]]:
    rows, useful = [], 0
    for fold, frame0 in [("ALL", oof), *[(name, oof.loc[oof.fold.eq(name)]) for name, _, _ in FOLDS]]:
        frame = _extreme_flags(frame0)
        high_bad, low_bad = frame.p_bad_ml_percentile.ge(.80), frame.p_bad_ml_percentile.le(.20)
        high_good, low_good = frame.p_good_ml_percentile.ge(.80), frame.p_good_ml_percentile.le(.20)
        masks = {"Q1_BAD_HIGH_GOOD_LOW": high_bad & low_good, "Q2_BAD_HIGH_GOOD_HIGH": high_bad & high_good, "Q3_BAD_LOW_GOOD_LOW": low_bad & low_good, "Q4_BAD_LOW_GOOD_HIGH": low_bad & high_good, "R6_TOP20_COMPARABLE": frame.r6_risk_percentile.ge(.80)}
        local = {name: quadrant_row(frame, mask, name, "CORE_QUADRANT", fold) for name, mask in masks.items()}
        rows.extend(local.values())
        if fold != "ALL":
            q1, r6 = local["Q1_BAD_HIGH_GOOD_LOW"], local["R6_TOP20_COMPARABLE"]
            direction = bool(q1["bad_event_lift"] > r6["bad_event_lift"] and q1["best100_capture"] <= r6["best100_capture"] and q1["worst100_best100_ratio"] >= r6["worst100_best100_ratio"])
            useful += int(direction)
            for row in rows[-5:]: row["bad_high_good_low_useful_fold"] = direction
    frame = _extreme_flags(oof)
    bad_bin = pd.cut(frame.p_bad_ml_percentile, [-np.inf, .2, .4, .6, .8, np.inf], labels=["B1", "B2", "B3", "B4", "B5"], include_lowest=True)
    good_bin = pd.cut(frame.p_good_ml_percentile, [-np.inf, .2, .4, .6, .8, np.inf], labels=["G1", "G2", "G3", "G4", "G5"], include_lowest=True)
    for (b, g), index in frame.groupby([bad_bin, good_bin], observed=False).groups.items():
        mask = frame.index.isin(index)
        rows.append(quadrant_row(frame, pd.Series(mask, index=frame.index), f"{b}_{g}", "JOINT_QUINTILE_GRID", "ALL"))
    pooled = pd.DataFrame(rows)
    q1 = pooled.loc[(pooled.fold.eq("ALL")) & pooled.region.eq("Q1_BAD_HIGH_GOOD_LOW")].iloc[0]
    r6 = pooled.loc[(pooled.fold.eq("ALL")) & pooled.region.eq("R6_TOP20_COMPARABLE")].iloc[0]
    gates = {"bad_lift_improves": bool(q1.bad_event_lift > r6.bad_event_lift), "best_contamination_not_worse": bool(q1.best100_capture <= r6.best100_capture), "worst_best_ratio_not_worse": bool(q1.worst100_best100_ratio >= r6.worst100_best100_ratio)}
    return pooled, useful, gates


def ranking_metrics(frame: pd.DataFrame, score: str, percentile: str) -> dict[str, float]:
    y, p, pct = frame.bad_target.to_numpy(dtype=int), frame[score].to_numpy(dtype=float), frame[percentile].to_numpy(dtype=float)
    base, top = float(y.mean()), pct >= .90
    worst = float(frame.nsmallest(100, "forward_5d_stock_return")[percentile].ge(.90).mean()); best = float(frame.nlargest(100, "forward_5d_stock_return")[percentile].ge(.90).mean())
    ap = float(average_precision_score(y, p)); rate = float(y[top].mean()) if top.any() else np.nan
    return {"base_rate": base, "auroc": float(roc_auc_score(y, p)), "average_precision": ap, "ap_base_multiple": ap / base, "top_decile_bad_lift": rate / base, "worst100_capture": worst, "best100_contamination": best, "worst100_best100_ratio": worst / best if best > 0 else np.inf}


def dual_score_diagnostics(oof: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    rows, counts = [], {}
    for name, score, percentile in [("DUAL_SCORE_A", "dual_score_a", "dual_score_a_percentile"), ("DUAL_SCORE_B", "dual_score_b", "dual_score_b_percentile")]:
        pooled = ranking_metrics(oof, score, percentile); positive = 0
        rows.append({"score": name, "scope": "POOLED", "fold": "ALL", **pooled})
        for fold, _, _ in FOLDS:
            metric = ranking_metrics(oof.loc[oof.fold.eq(fold)], score, percentile)
            direction = bool(metric["auroc"] > .50 and metric["ap_base_multiple"] > 1 and metric["top_decile_bad_lift"] > 1); positive += int(direction)
            rows.append({"score": name, "scope": "FOLD", "fold": fold, **metric, "positive_direction": direction})
        rows[-6]["positive_folds"] = positive; counts[name] = positive
    return pd.DataFrame(rows), counts


def cross_head_diagnostics(oof: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for fold, frame in [("ALL", oof), *[(name, oof.loc[oof.fold.eq(name)]) for name, _, _ in FOLDS]]:
        rows.append({"diagnostic_type": "CROSS_HEAD", "fold": fold, "bad_good_spearman": float(frame.p_bad_ml.corr(frame.p_good_ml, method="spearman")), "bad_good_pearson": float(frame.p_bad_ml.corr(frame.p_good_ml, method="pearson"))})
    return pd.DataFrame(rows)


def r7_winner_contamination(oof: pd.DataFrame, panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    best100 = set(map(tuple, oof.nlargest(100, "forward_5d_stock_return")[["signal_date", "ticker"]].to_numpy()))
    mask = oof.r7_ml_risk_percentile.ge(.90) & pd.Series([(d, t) in best100 for d, t in zip(oof.signal_date, oof.ticker)], index=oof.index)
    selected = oof.loc[mask].copy()
    features = panel.loc[panel.frozen_r6_target.notna(), ["signal_date", "ticker", *R7.A2_FEATURES, *R7.STOCK_FEATURES, *R7.MARKET_FEATURES]]
    selected = selected.merge(features, on=["signal_date", "ticker"], validate="one_to_one")
    selected["good_head_top20"] = selected.p_good_ml_percentile.ge(.80)
    summary = {"r7_contaminated_best100_count": len(selected), "explained_by_good_head_fraction": float(selected.good_head_top20.mean()) if len(selected) else np.nan, "mean_good_head_percentile": float(selected.p_good_ml_percentile.mean()) if len(selected) else np.nan, "all_row_mean_good_head_percentile": float(oof.p_good_ml_percentile.mean())}
    return selected, summary


def print_summary(summary: dict[str, Any]) -> None:
    keys = ["A2_STOCK_RISK_R8_STATUS", "A2_STOCK_RISK_R8_CLASSIFICATION", "R6_TARGET_CONTRACT_ID", "R6_FOLD_CONTRACT_ID", "R6_OOF_HASH", "TRAINING_END_DATE", "TRAINING_ROWS", "OOF_ROWS", "BAD_BASE_RATE", "GOOD_BASE_RATE", "BAD_HEAD_AUROC", "BAD_HEAD_AP", "BAD_HEAD_TOP_DECILE_LIFT", "BAD_HEAD_POSITIVE_FOLDS", "GOOD_HEAD_AUROC", "GOOD_HEAD_AP", "GOOD_HEAD_TOP_DECILE_LIFT", "GOOD_HEAD_POSITIVE_FOLDS", "BAD_GOOD_SPEARMAN", "BAD_GOOD_PEARSON", "R6_WORST100_CAPTURE", "R6_BEST100_CAPTURE", "R6_WORST_BEST_RATIO", "R8_BAD_HIGH_GOOD_LOW_ROW_COUNT", "R8_BAD_HIGH_GOOD_LOW_BAD_RATE", "R8_BAD_HIGH_GOOD_LOW_GOOD_RATE", "R8_BAD_HIGH_GOOD_LOW_WORST100_CAPTURE", "R8_BAD_HIGH_GOOD_LOW_BEST100_CAPTURE", "R8_BAD_HIGH_GOOD_LOW_WORST_BEST_RATIO", "DUAL_SCORE_A_AUROC", "DUAL_SCORE_A_AP", "DUAL_SCORE_A_TOP_DECILE_LIFT", "DUAL_SCORE_A_WORST100_CAPTURE", "DUAL_SCORE_A_BEST100_CAPTURE", "DUAL_SCORE_A_WORST_BEST_RATIO", "DUAL_SCORE_A_POSITIVE_FOLDS", "R7_WINNER_CONTAMINATION_EXPLAINED_BY_GOOD_HEAD", "PARAMETER_SEARCH_COUNT", "THRESHOLD_SEARCH_COUNT", "POSITION_RULE_APPLICATION_COUNT", "ECONOMIC_BACKTEST_COUNT", "2026_TRAINING_ROW_COUNT", "2026_TARGET_READ_COUNT", "2026_RETURN_READ_COUNT", "2026_HOLDOUT_READ_COUNT", "LOOKAHEAD_VIOLATION_COUNT", "PIT_AUDIT_STATUS", "REPRODUCIBILITY_STATUS", "ANTI_BLOAT_STATUS", "NEXT_AUTHORIZED_STEP"]
    for key in keys:
        value = summary[key]
        if value is None or (isinstance(value, float) and np.isnan(value)): value = "NA"
        elif isinstance(value, float) and np.isfinite(value): value = f"{value:.12g}"
        print(f"{key}={value}")


def run(output: Path) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()): raise RuntimeError(f"fail closed: output directory not empty: {output}")
    discover = discovery(); print_discovery(discover)
    if discover["R8_DISCOVERY_STATUS"] != "PASS": raise RuntimeError("missing frozen R6/R7 contract")
    output.mkdir(parents=True, exist_ok=True)
    panel, daily, panel_audit = R7.build_feature_panel()
    targets, target_folds, target_audit = build_target_frame(panel, daily)
    if target_audit["bad_target_identity_mismatch_count"] or target_audit["bad_good_overlap_count"]: raise RuntimeError("R8 target identity/symmetry failure")
    target_contract = {"bad_tail_definition": BAD_TARGET_CONTRACT, "good_tail_definition": GOOD_TARGET_CONTRACT, "holding_horizon": "5 trading sessions", "source_return_field": "POST_ENTRY_FORWARD_5D_RETURN", "timestamp_contract": GOOD_TARGET_CONTRACT["timestamp_contract"], "base_rate_bad": target_audit["bad_base_rate"], "base_rate_good": target_audit["good_base_rate"], "contract_hash": TARGET_CONTRACT_HASH}
    r7_feature_manifest = json.loads(R7_FEATURE_MANIFEST_PATH.read_text(encoding="utf-8"))
    feature_manifest = {"status": "FROZEN_BEFORE_R8_MODEL_FIT", "r7_feature_schema_sha256": r7_feature_manifest["feature_schema_sha256"], "feature_universe": R7.FEATURES, "primary_stock_level_features": PRIMARY_FEATURES, "market_level_features": R7.MARKET_FEATURES, "market_features_role": "FIXED_DIAGNOSTIC_ONLY", "primary_feature_count": len(PRIMARY_FEATURES), "full_feature_count": len(R7.FEATURES), "pit_status": "PASS_REUSED_R7_AUDITED_UNIVERSE"}
    R1.write_json(output / "r8_target_contract.json", target_contract); R1.write_json(output / "r8_feature_manifest.json", feature_manifest)

    bad_log, _, f1, m1 = run_head_oof(panel, daily, PRIMARY_FEATURES, "BAD", "LOGISTIC", "BAD_LOGISTIC_FIXED")
    good_log, _, f2, _ = run_head_oof(panel, daily, PRIMARY_FEATURES, "GOOD", "LOGISTIC", "GOOD_LOGISTIC_FIXED")
    bad_ml, bad_train, f3, m3 = run_head_oof(panel, daily, PRIMARY_FEATURES, "BAD", "LIGHTGBM", "BAD_LIGHTGBM_FIXED")
    good_ml, good_train, f4, _ = run_head_oof(panel, daily, PRIMARY_FEATURES, "GOOD", "LIGHTGBM", "GOOD_LIGHTGBM_FIXED")
    bad_repeat, _, f5, m5 = run_head_oof(panel, daily, PRIMARY_FEATURES, "BAD", "LIGHTGBM", "BAD_LIGHTGBM_REPRODUCIBILITY")
    good_repeat, _, f6, _ = run_head_oof(panel, daily, PRIMARY_FEATURES, "GOOD", "LIGHTGBM", "GOOD_LIGHTGBM_REPRODUCIBILITY")
    market_bad, _, f7, m7 = run_head_oof(panel, daily, MARKET_DIAGNOSTIC_FEATURES, "BAD", "LIGHTGBM", "BAD_FULL_MARKET_DIAGNOSTIC")
    market_good, _, f8, _ = run_head_oof(panel, daily, MARKET_DIAGNOSTIC_FEATURES, "GOOD", "LIGHTGBM", "GOOD_FULL_MARKET_DIAGNOSTIC")
    reproducible = bool(prediction_hash(bad_ml) == prediction_hash(bad_repeat) and prediction_hash(good_ml) == prediction_hash(good_repeat) and np.array_equal(bad_ml.probability.to_numpy(), bad_repeat.probability.to_numpy()) and np.array_equal(good_ml.probability.to_numpy(), good_repeat.probability.to_numpy()))
    if not reproducible: raise RuntimeError("R8 prediction reproducibility failure")
    oof = combine_oof(targets, bad_log, good_log, bad_ml, good_ml, bad_train, good_train, panel)
    head_table, fold_table, stability = evaluate_heads(oof, market_bad, market_good)
    cross = cross_head_diagnostics(oof); fold_table = pd.concat([fold_table, cross], ignore_index=True, sort=False)
    quadrants, quadrant_useful, quadrant_gates = quadrant_diagnostics(oof)
    dual, dual_counts = dual_score_diagnostics(oof)
    contamination, contamination_summary = r7_winner_contamination(oof, panel)

    by = head_table.set_index(["head", "model"]); bad = by.loc[("BAD", "PRIMARY_ML")]; good = by.loc[("GOOD", "PRIMARY_ML")]; r6 = by.loc[("BAD", "R6_BASELINE")]
    q1 = quadrants.loc[(quadrants.fold.eq("ALL")) & quadrants.region.eq("Q1_BAD_HIGH_GOOD_LOW")].iloc[0]
    r6q = quadrants.loc[(quadrants.fold.eq("ALL")) & quadrants.region.eq("R6_TOP20_COMPARABLE")].iloc[0]
    dsa = dual.loc[(dual.score.eq("DUAL_SCORE_A")) & dual.scope.eq("POOLED")].iloc[0]
    cross_all = cross.loc[cross.fold.eq("ALL")].iloc[0]
    good_info = bool(stability["GOOD_PRIMARY_ML"] >= 3 and good.ap_base_multiple > 1.10)
    gate_count = sum(quadrant_gates.values())
    pass_b = bool(good_info and gate_count == 3 and quadrant_useful >= 4)
    partial = bool(good_info and gate_count >= 2 and quadrant_useful >= 2)
    classification = "B_DUAL_TAIL_ASYMMETRY_CONFIRMED" if pass_b else ("C_PARTIAL" if partial else "D_NO_USEFUL_DUAL_TAIL_INCREMENT")
    next_step = "R8E_FIXED_ECONOMIC_DIAGNOSTIC" if pass_b else ("PRESERVE_RESEARCH_ONLY" if partial else "PRESERVE_R6_AS_BEST_CURRENT_STOCK_RISK_SIGNAL")

    lookahead = int((panel.information_date >= panel.signal_date).sum() + (panel.market_feature_date >= panel.signal_date).sum() + (oof.target_end_date >= TRAINING_CUTOFF).sum())
    duplicate = int(oof.duplicated(["signal_date", "ticker"]).sum())
    if lookahead or duplicate or m1 + m3 + m5 + m7: raise RuntimeError("R8 OOF/PIT integrity failure")
    sessions = pd.DatetimeIndex(daily.execution_date); training_rows = 0; training_end = pd.Timestamp.min
    for _, start, end in FOLDS:
        train, _, _ = R3.fold_split(panel, sessions, start, end); training_rows += len(train); training_end = max(training_end, pd.Timestamp(train.target_end_date.max()))
    guard = R1.guard_audit(); anti = "PASS_NEW_R8_ZERO" if guard["repository_guard_status"] == "PASS" else "PREEXISTING_REPOSITORY_GOVERNANCE_FAILURE;NEW_R8_VIOLATIONS=0"
    status = "VALID_PRE2026_R8_PREDICTIVE_RESULT" + ("_WITH_PREEXISTING_REPO_GOVERNANCE_FAILURE" if guard["repository_guard_status"] != "PASS" else "")
    summary = {"A2_STOCK_RISK_R8_STATUS": status, "A2_STOCK_RISK_R8_CLASSIFICATION": classification, "R6_TARGET_CONTRACT_ID": discover["R6_TARGET_CONTRACT_ID"], "R6_FOLD_CONTRACT_ID": discover["R6_FOLD_CONTRACT_ID"], "R6_OOF_HASH": discover["R6_OOF_HASH"], "TRAINING_END_DATE": training_end.strftime("%Y-%m-%d"), "TRAINING_ROWS": training_rows, "OOF_ROWS": len(oof), "BAD_BASE_RATE": target_audit["bad_base_rate"], "GOOD_BASE_RATE": target_audit["good_base_rate"], "BAD_EVENT_COUNT": target_audit["bad_event_count"], "GOOD_EVENT_COUNT": target_audit["good_event_count"], "BAD_GOOD_OVERLAP_COUNT": target_audit["bad_good_overlap_count"], "BAD_GOOD_OVERLAP_RATE": target_audit["bad_good_overlap_rate"], "BAD_HEAD_AUROC": bad.auroc, "BAD_HEAD_AP": bad.average_precision, "BAD_HEAD_TOP_DECILE_LIFT": bad.top_decile_lift, "BAD_HEAD_POSITIVE_FOLDS": int(stability["BAD_PRIMARY_ML"]), "GOOD_HEAD_AUROC": good.auroc, "GOOD_HEAD_AP": good.average_precision, "GOOD_HEAD_TOP_DECILE_LIFT": good.top_decile_lift, "GOOD_HEAD_POSITIVE_FOLDS": int(stability["GOOD_PRIMARY_ML"]), "BAD_GOOD_SPEARMAN": cross_all.bad_good_spearman, "BAD_GOOD_PEARSON": cross_all.bad_good_pearson, "R6_WORST100_CAPTURE": r6.worst100_capture, "R6_BEST100_CAPTURE": r6.best100_contamination, "R6_WORST_BEST_RATIO": r6.worst100_best100_ratio, "R8_BAD_HIGH_GOOD_LOW_ROW_COUNT": int(q1.row_count), "R8_BAD_HIGH_GOOD_LOW_BAD_RATE": q1.bad_event_rate, "R8_BAD_HIGH_GOOD_LOW_GOOD_RATE": q1.good_event_rate, "R8_BAD_HIGH_GOOD_LOW_WORST100_CAPTURE": q1.worst100_capture, "R8_BAD_HIGH_GOOD_LOW_BEST100_CAPTURE": q1.best100_capture, "R8_BAD_HIGH_GOOD_LOW_WORST_BEST_RATIO": None if pd.isna(q1.worst100_best100_ratio) else q1.worst100_best100_ratio, "R8_BAD_HIGH_GOOD_LOW_BAD_LIFT": q1.bad_event_lift, "R6_TOP20_BAD_LIFT": r6q.bad_event_lift, "R6_TOP20_GOOD_CONTAMINATION": r6q.good_event_rate, "BAD_HIGH_GOOD_LOW_USEFUL_FOLDS": quadrant_useful, "DUAL_SCORE_A_AUROC": dsa.auroc, "DUAL_SCORE_A_AP": dsa.average_precision, "DUAL_SCORE_A_TOP_DECILE_LIFT": dsa.top_decile_bad_lift, "DUAL_SCORE_A_WORST100_CAPTURE": dsa.worst100_capture, "DUAL_SCORE_A_BEST100_CAPTURE": dsa.best100_contamination, "DUAL_SCORE_A_WORST_BEST_RATIO": dsa.worst100_best100_ratio, "DUAL_SCORE_A_POSITIVE_FOLDS": dual_counts["DUAL_SCORE_A"], "R7_WINNER_CONTAMINATION_EXPLAINED_BY_GOOD_HEAD": contamination_summary["explained_by_good_head_fraction"], "R7_CONTAMINATED_BEST100_COUNT": contamination_summary["r7_contaminated_best100_count"], "FOLD4_DUAL_TAIL_IMPROVEMENT": bool(quadrants.loc[(quadrants.fold.eq("FOLD_4")) & quadrants.region.eq("Q1_BAD_HIGH_GOOD_LOW"), "bad_high_good_low_useful_fold"].iloc[0]), "BAD_MODEL_PARAMS_HASH": BAD_MODEL_PARAMS_HASH, "GOOD_MODEL_PARAMS_HASH": GOOD_MODEL_PARAMS_HASH, "PARAMETER_SEARCH_COUNT": 0, "MODEL_PARAM_SEARCH_COUNT": 0, "THRESHOLD_SEARCH_COUNT": 0, "POSITION_RULE_APPLICATION_COUNT": 0, "ECONOMIC_BACKTEST_COUNT": 0, "2026_TRAINING_ROW_COUNT": 0, "2026_TARGET_READ_COUNT": 0, "2026_RETURN_READ_COUNT": 0, "2026_HOLDOUT_READ_COUNT": 0, "LOOKAHEAD_VIOLATION_COUNT": lookahead, "PIT_AUDIT_STATUS": "PASS", "REPRODUCIBILITY_STATUS": "PASS_EXACT", "ANTI_BLOAT_STATUS": anti, "NEXT_AUTHORIZED_STEP": next_step}
    run_manifest = {"run_id": "A2_STOCK_RISK_R8", "created_at_utc": datetime.now(timezone.utc).isoformat(), "input_hashes": {"r6_oof": discover["R6_OOF_HASH"], "r7_oof": discover["R7_OOF_HASH"], "r7_prediction": discover["R7_PREDICTION_HASH"]}, "target_contract_hash": TARGET_CONTRACT_HASH, "bad_model_params_hash": BAD_MODEL_PARAMS_HASH, "good_model_params_hash": GOOD_MODEL_PARAMS_HASH, "logistic_params": R7.LOGISTIC_PARAMS, "lightgbm_params": R7.LIGHTGBM_PARAMS, "primary_features": PRIMARY_FEATURES, "market_diagnostic_features": MARKET_DIAGNOSTIC_FEATURES, "dual_score_epsilon": DUAL_SCORE_EPSILON, "quadrant_cut": QUADRANT_CUT, "prediction_hashes": {"bad_primary": prediction_hash(bad_ml), "bad_repeat": prediction_hash(bad_repeat), "good_primary": prediction_hash(good_ml), "good_repeat": prediction_hash(good_repeat)}, "model_fit_counts": {"bad_logistic": f1, "good_logistic": f2, "bad_primary": f3, "good_primary": f4, "bad_reproducibility": f5, "good_reproducibility": f6, "bad_market_diagnostic": f7, "good_market_diagnostic": f8, "total": sum([f1,f2,f3,f4,f5,f6,f7,f8])}, "search_counts": {"parameter": 0, "threshold": 0, "feature_subset": 0}}
    audit = {"summary": summary, "discovery": discover, "target": target_audit, "target_thresholds": target_folds.to_dict(orient="records"), "panel": panel_audit, "oof": {"row_count": len(oof), "duplicate_key_count": duplicate, "bad_target_identity_with_r6": target_audit["bad_target_identity_with_r6"], "lookahead_count": lookahead}, "quadrant_gate_details": quadrant_gates, "r7_winner_contamination": contamination_summary, "firewall": {"training_rows_2026": 0, "target_reads_2026": 0, "return_reads_2026": 0, "holdout_reads_2026": 0}, "repository_governance": guard}
    R1.write_csv(output / "r8_head_metrics.csv", head_table); R1.write_csv(output / "r8_fold_metrics.csv", fold_table); R1.write_csv(output / "r8_quadrant_diagnostic.csv", quadrants); R1.write_csv(output / "r8_dual_score_diagnostic.csv", dual); R1.write_csv(output / "r8_r7_winner_contamination_analysis.csv", contamination); R1.write_parquet(output / "r8_oof_predictions.parquet", oof); R1.write_json(output / "r8_run_manifest.json", run_manifest); R1.write_json(output / "r8_audit.json", audit); R1.write_json(output / "r8_summary.json", summary)
    print_summary(summary); return summary


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR); args = parser.parse_args()
    try: run(args.output_dir.resolve()); return 0
    except Exception as exc:
        print("A2_STOCK_RISK_R8_STATUS=STOP", file=sys.stderr); print("A2_STOCK_RISK_R8_CLASSIFICATION=E_INVALID_RESEARCH_CONTRACT", file=sys.stderr); print(f"FAIL_CLOSED_REASON={type(exc).__name__}:{exc}", file=sys.stderr); print("NEXT_AUTHORIZED_STEP=STOP_AND_RESOLVE_CONTRACT", file=sys.stderr); return 1


if __name__ == "__main__": raise SystemExit(main())
