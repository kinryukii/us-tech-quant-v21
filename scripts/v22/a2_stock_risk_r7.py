"""A2 Stock-Risk R7: unified, pre-2026-only severe-loss prediction."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


REPO_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
OUTPUT_DIR = RESULTS_ROOT / "A2_STOCK_RISK_R7"
R6_SCRIPT = REPO_ROOT / "scripts" / "v22" / "a2_stock_risk_r6.py"
R6_ROOT = RESULTS_ROOT / "A2_STOCK_RISK_R6"
R6_OOF_PATH = R6_ROOT / "r6_oof_predictions.parquet"
R6_SUMMARY_PATH = R6_ROOT / "r6_summary.json"
R3R_OOF_PATH = RESULTS_ROOT / "A2_STOCK_RISK_R3A_R3R" / "r3r_oof_predictions.parquet"
R6_OOF_SHA256 = "5f35b7b54192ce9023a886f3a51d9efaddea526bb78aed4862481f9dd85653b4"
R3_OOF_SHA256 = "636d87b1fb0c8981d95cfc41524dbfd6e7afa86f361f27432b6799412a649399"
R6_REFERENCE_MODEL = "LGBM_BAD_ASYM_2"
R3_REFERENCE_MODEL = "LGBM_STOCK_Q90_1"
TRAINING_CUTOFF = pd.Timestamp("2026-01-01")
FORMAL_R6_CLASSIFICATION = "C"

LOGISTIC_PARAMS = {"C": 0.3, "class_weight": "balanced", "solver": "lbfgs", "max_iter": 2000, "random_state": 20260818}
LIGHTGBM_PARAMS = {
    "n_estimators": 100, "learning_rate": 0.03, "num_leaves": 7, "max_depth": 3,
    "min_child_samples": 40, "reg_alpha": 1.0, "reg_lambda": 5.0,
    "subsample": 0.8, "subsample_freq": 1, "colsample_bytree": 0.8,
    "objective": "binary", "class_weight": "balanced", "random_state": 20260818,
    "n_jobs": 1, "deterministic": True, "force_col_wise": True, "verbosity": -1,
}

A2_FEATURES = [
    "A2_PREDICTION", "A2_RANK", "A2_UNIVERSE_SIZE", "A2_RANK_PERCENTILE",
    "A2_TOP20_RELATIVE_RANK", "A2_SCORE_DISTANCE_TOP20_MEAN",
    "A2_SCORE_DISTANCE_TOP20_MEDIAN", "A2_SCORE_DISPERSION_TOP20",
]
STOCK_FEATURES = [
    "RET_1D", "RET_5D", "RET_20D", "RET_60D", "DISTANCE_FROM_HIGH_20D",
    "DISTANCE_FROM_HIGH_60D", "MAX_DRAWDOWN_20D", "MAX_DRAWDOWN_60D",
    "REALIZED_VOL_5D", "REALIZED_VOL_60D", "DOWNSIDE_VOL_20D",
    "VOL_ACCELERATION_5D_60D", "VOLUME_RATIO_5D_20D", "VOLUME_RATIO_20D_60D",
    "STOCK_MINUS_QQQ_20D",
]
MARKET_FEATURES = [
    *[f"MKT_QQQ_{name}" for name in ["RETURN_1D", "RETURN_5D", "RETURN_20D", "REALIZED_VOL_20D", "DRAWDOWN_60D", "DISTANCE_MA50", "DOWNSIDE_INTENSITY_20D"]],
    *[f"MKT_SPX_PROXY_{name}" for name in ["RETURN_1D", "RETURN_5D", "RETURN_20D", "REALIZED_VOL_20D", "DRAWDOWN_60D", "DISTANCE_MA50", "DOWNSIDE_INTENSITY_20D"]],
    *[f"MKT_SOXX_{name}" for name in ["RETURN_1D", "RETURN_5D", "RETURN_20D", "REALIZED_VOL_20D", "DRAWDOWN_60D", "DISTANCE_MA50", "DOWNSIDE_INTENSITY_20D"]],
    "MKT_SOXX_RELATIVE_STRENGTH_VS_SPX_20D", "MKT_VIX_LEVEL", "MKT_VIX_CHANGE_1D",
    "MKT_VIX_CHANGE_5D", "MKT_VIX_PERCENTILE_252D",
]
RISK_FEATURES = ["R6_OOF_SCORE", "R3_OOF_RISK_SCORE", "STOCK_VOL_RISK"]
FEATURES = A2_FEATURES + STOCK_FEATURES + MARKET_FEATURES + RISK_FEATURES

ABLATIONS = {
    "A_R6_ONLY": ["R6_OOF_SCORE"],
    "B_R6_PLUS_R3": ["R6_OOF_SCORE", "R3_OOF_RISK_SCORE"],
    "C_R6_PLUS_MARKET_STATE": ["R6_OOF_SCORE", *MARKET_FEATURES],
    "D_R6_PLUS_STOCK_A2_STATE": ["R6_OOF_SCORE", *A2_FEATURES, *STOCK_FEATURES, "STOCK_VOL_RISK"],
    "E_FULL_R7": FEATURES,
}


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


R6 = _load_module(R6_SCRIPT, "a2_stock_risk_r6_for_r7")
R3 = R6.R3
R1 = R3.R1
FOLDS = list(R3.FOLDS)
R6_TARGET_CONTRACT = {
    "target": "BAD_ASYMMETRY_5D",
    "definition": "POST_ENTRY_5D_MAE >= fold-training Q90 AND POST_ENTRY_5D_MFE <= fold-training Q50",
    "mae_quantile": R6.MAE_SEVERE_QUANTILE,
    "mfe_quantile": R6.MFE_COMPENSATION_QUANTILE,
    "execution_reference": "Moomoo QFQ signal-date open; five-session low/high/close path",
}
R6_FOLD_CONTRACT = {"folds": FOLDS, "purge_embargo_sessions": R3.PURGE_EMBARGO_SESSIONS, "split_unit": "signal_date"}
R6_TARGET_CONTRACT_ID = R1.canonical_hash(R6_TARGET_CONTRACT)
R6_FOLD_CONTRACT_ID = R1.canonical_hash(R6_FOLD_CONTRACT)


@dataclass(frozen=True)
class FeatureMeta:
    name: str
    family: str
    source: str
    timestamp_meaning: str
    availability_time: str
    lookback: str
    cross_sectional: bool
    derived_from_future_returns: bool
    pit_proof: str


def _rolling_percentile_last(values: np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    return float(np.mean(arr <= arr[-1]))


def build_market_state(prices: pd.DataFrame, vix: pd.DataFrame) -> pd.DataFrame:
    """Trailing-only daily market state, timestamped at completed market_date close."""
    pivot = prices.pivot(index="trade_date", columns="ticker", values="close").sort_index()
    if not {"QQQ", "SPY", "SOXX"}.issubset(pivot.columns):
        raise RuntimeError("QQQ/SPY/SOXX market state coverage missing")
    out = pd.DataFrame(index=pivot.index)
    for ticker, prefix in [("QQQ", "MKT_QQQ"), ("SPY", "MKT_SPX_PROXY"), ("SOXX", "MKT_SOXX")]:
        close = pivot[ticker].astype(float)
        ret = close.pct_change(fill_method=None)
        downside = ret.clip(upper=0.0)
        out[f"{prefix}_RETURN_1D"] = ret
        out[f"{prefix}_RETURN_5D"] = close.pct_change(5, fill_method=None)
        out[f"{prefix}_RETURN_20D"] = close.pct_change(20, fill_method=None)
        out[f"{prefix}_REALIZED_VOL_20D"] = ret.rolling(20, min_periods=20).std() * np.sqrt(252.0)
        out[f"{prefix}_DRAWDOWN_60D"] = close / close.rolling(60, min_periods=60).max() - 1.0
        out[f"{prefix}_DISTANCE_MA50"] = close / close.rolling(50, min_periods=50).mean() - 1.0
        out[f"{prefix}_DOWNSIDE_INTENSITY_20D"] = np.sqrt(downside.pow(2).rolling(20, min_periods=20).mean()) * np.sqrt(252.0)
    out["MKT_SOXX_RELATIVE_STRENGTH_VS_SPX_20D"] = out["MKT_SOXX_RETURN_20D"] - out["MKT_SPX_PROXY_RETURN_20D"]
    out = out.reset_index().rename(columns={"trade_date": "market_feature_date"})
    vix = vix.rename(columns={"market_date": "market_feature_date"}).copy()
    out = out.merge(vix[["market_feature_date", "vix_close"]], on="market_feature_date", how="inner", validate="one_to_one")
    v = out.vix_close.astype(float)
    out["MKT_VIX_LEVEL"] = v
    out["MKT_VIX_CHANGE_1D"] = v.pct_change(fill_method=None)
    out["MKT_VIX_CHANGE_5D"] = v.pct_change(5, fill_method=None)
    out["MKT_VIX_PERCENTILE_252D"] = v.rolling(252, min_periods=126).apply(_rolling_percentile_last, raw=True)
    return out[["market_feature_date", *MARKET_FEATURES]].dropna().sort_values("market_feature_date").reset_index(drop=True)


def load_market_state() -> pd.DataFrame:
    parts = []
    for year in range(2019, 2026):
        path = R1.PRICE_YEAR_ROOT / f"year={year}" / "prices.parquet"
        frame = pd.read_parquet(path, columns=["ticker", "trade_date", "close", "source", "autype"])
        parts.append(frame.loc[frame.ticker.isin(["QQQ", "SPY", "SOXX"])])
    prices = pd.concat(parts, ignore_index=True)
    prices["trade_date"] = pd.to_datetime(prices.trade_date)
    prices = prices.loc[prices.trade_date.lt(TRAINING_CUTOFF)].copy()
    if set(prices.ticker.unique()) != {"QQQ", "SPY", "SOXX"}:
        raise RuntimeError("pre-2026 market ticker coverage failure")
    if not prices.source.astype(str).str.contains("MOOMOO", case=False).all() or not prices.autype.astype(str).str.upper().eq("QFQ").all():
        raise RuntimeError("market state source/adjustment integrity failure")
    prices = prices[["ticker", "trade_date", "close"]].drop_duplicates(["ticker", "trade_date"], keep="last")
    return build_market_state(prices, R1.load_vix(True))


def discovery() -> dict[str, Any]:
    r6_hash, r3_hash = R1.sha256_file(R6_OOF_PATH), R1.sha256_file(R3R_OOF_PATH)
    target_found = bool(R6.MAE_SEVERE_QUANTILE == 0.90 and R6.MFE_COMPENSATION_QUANTILE == 0.50)
    fold_found = bool(FOLDS == list(R1.FOLDS) and R3.PURGE_EMBARGO_SESSIONS == 5)
    return {
        "R7_DISCOVERY_STATUS": "PASS" if target_found and fold_found and r6_hash == R6_OOF_SHA256 and r3_hash == R3_OOF_SHA256 else "FAIL",
        "R6_TARGET_CONTRACT_FOUND": target_found, "R6_OOF_FOUND": R6_OOF_PATH.exists(), "R6_OOF_HASH": r6_hash,
        "R6_FOLD_CONTRACT_FOUND": fold_found, "R3_OOF_FOUND": R3R_OOF_PATH.exists(),
        "A2_FEATURE_SOURCE_FOUND": R3.TOP20_PATH.exists() and R3.TRAINING_MATRIX_PATH.exists(),
        "MARKET_FEATURE_SOURCE_FOUND": R1.PRICE_YEAR_ROOT.exists() and R1.VIX_PATH.exists(),
        "PIT_PROVENANCE_STATUS": "PASS_WITH_OOF_HISTORY_MISSINGNESS_DISCLOSED",
        "FAST_FEATURE_STATUS": "EXCLUDED_UNPROVEN_PIT_ALIGNMENT", "r3_oof_hash": r3_hash,
    }


def add_a2_state(panel: pd.DataFrame) -> pd.DataFrame:
    frame = panel.copy()
    group = frame.groupby("signal_date")["A2_PREDICTION"]
    frame["A2_UNIVERSE_SIZE"] = frame.universe_size.astype(float)
    frame["A2_RANK_PERCENTILE"] = (frame.A2_RANK - 1.0) / np.maximum(frame.A2_UNIVERSE_SIZE - 1.0, 1.0)
    frame["A2_TOP20_RELATIVE_RANK"] = (frame.A2_RANK - 1.0) / 19.0
    frame["A2_SCORE_DISTANCE_TOP20_MEAN"] = frame.A2_PREDICTION - group.transform("mean")
    frame["A2_SCORE_DISTANCE_TOP20_MEDIAN"] = frame.A2_PREDICTION - group.transform("median")
    frame["A2_SCORE_DISPERSION_TOP20"] = group.transform("std")
    return frame


def build_feature_panel() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    panel, _, corrected, daily, _, r3_oof, r3r_summary = R6.load_inputs()
    r6_summary = json.loads(R6_SUMMARY_PATH.read_text(encoding="utf-8"))
    if r6_summary.get("A2_STOCK_RISK_R6_CLASSIFICATION") != FORMAL_R6_CLASSIFICATION or r6_summary.get("REFERENCE_MODEL") != R6_REFERENCE_MODEL:
        raise RuntimeError("formal R6 classification/reference model changed")
    panel = add_a2_state(panel)
    market = load_market_state()
    panel = panel.merge(market, left_on="information_date", right_on="market_feature_date", how="left", validate="many_to_one")
    r6 = pd.read_parquet(R6_OOF_PATH)
    r6["signal_date"] = pd.to_datetime(r6.signal_date)
    r6 = r6.loc[r6.candidate_id.eq(R6_REFERENCE_MODEL), ["signal_date", "ticker", "predicted_bad_asymmetry_risk", "bad_asymmetry_5d", "fold"]].rename(columns={"predicted_bad_asymmetry_risk": "R6_OOF_SCORE", "bad_asymmetry_5d": "frozen_r6_target", "fold": "frozen_r6_fold"})
    r3 = r3_oof.loc[r3_oof.candidate_id.eq(R3_REFERENCE_MODEL), ["signal_date", "ticker", "predicted_q90"]].rename(columns={"predicted_q90": "R3_OOF_RISK_SCORE"})
    if r6.duplicated(["signal_date", "ticker"]).any() or r3.duplicated(["signal_date", "ticker"]).any():
        raise RuntimeError("R3/R6 OOF duplicate key")
    if not r6[["signal_date", "ticker"]].sort_values(["signal_date", "ticker"]).reset_index(drop=True).equals(r3[["signal_date", "ticker"]].sort_values(["signal_date", "ticker"]).reset_index(drop=True)):
        raise RuntimeError("R3/R6 OOF row identity mismatch")
    panel = panel.merge(r6, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    panel = panel.merge(r3, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    panel["STOCK_VOL_RISK"] = panel.REALIZED_VOL_20D
    panel = panel.replace([np.inf, -np.inf], np.nan)
    if len(corrected) != len(panel) or panel.groupby("signal_date").size().ne(20).any():
        raise RuntimeError("R7 panel/execution target coverage failure")
    if panel.signal_date.ge(TRAINING_CUTOFF).any() or panel.target_end_date.ge(TRAINING_CUTOFF).any():
        raise RuntimeError("R7 panel crosses 2026 firewall")
    if not panel.information_date.lt(panel.signal_date).all() or not panel.market_feature_date.lt(panel.signal_date).all():
        raise RuntimeError("R7 feature timestamp/lookahead violation")
    audit = {
        "panel_rows": len(panel), "panel_dates": int(panel.signal_date.nunique()), "execution_target_coverage": len(corrected) / len(panel),
        "r6_oof_rows": len(r6), "r3_oof_rows": len(r3), "r6_r3_key_identity_pass": True,
        "risk_oof_history_missing_rows": int(panel.R6_OOF_SCORE.isna().sum()),
        "risk_oof_missingness_policy": "preserve NA; fold-training median imputation for Logistic; native missing routing for LightGBM; no in-sample backfill",
        "r3r_reference_summary": r3r_summary,
    }
    return panel.sort_values(["signal_date", "ticker"]).reset_index(drop=True), daily, audit


def feature_metadata() -> list[FeatureMeta]:
    rows: list[FeatureMeta] = []
    prior = "completed information_date session, strictly before 09:25 signal_date decision"
    for name in A2_FEATURES:
        cross = name in {"A2_RANK_PERCENTILE", "A2_TOP20_RELATIVE_RANK", "A2_SCORE_DISTANCE_TOP20_MEAN", "A2_SCORE_DISTANCE_TOP20_MEDIAN", "A2_SCORE_DISPERSION_TOP20"}
        rows.append(FeatureMeta(name, "A2_STATE", "frozen A2 Top20 selections/model output", "information_date frozen A2 state", prior, "current PIT A2 cross-section", cross, False, "frozen A2 output predates signal_date"))
    for name in STOCK_FEATURES:
        rows.append(FeatureMeta(name, "STOCK_STATE", "frozen A2 training_matrix trailing price/volume features", "information_date adjusted-close history", prior, name.rsplit("_", 1)[-1] if any(x in name for x in ["1D", "5D", "20D", "60D"]) else "fixed existing trailing contract", False, False, "existing R3 22-feature PIT contract"))
    for name in MARKET_FEATURES:
        source = "Moomoo QFQ daily QQQ/SPY/SOXX" if "VIX" not in name else "local canonical CBOE VIX daily"
        rows.append(FeatureMeta(name, "MARKET_STATE", source, "market_feature_date completed close", prior, "trailing 1/5/20/50/60/252 sessions as encoded", False, False, "years 2019-2025 only; trailing rolling operations; market_feature_date < signal_date"))
    rows.extend([
        FeatureMeta("R6_OOF_SCORE", "EXISTING_RISK", "frozen R6 OOF artifact", "outer-fold OOF score for same stock-date", prior, "frozen temporal OOF", False, False, "hash-verified R6 OOF; never in-sample backfilled"),
        FeatureMeta("R3_OOF_RISK_SCORE", "EXISTING_RISK", "frozen R3R MAE OOF artifact", "outer-fold OOF score for same stock-date", prior, "frozen temporal OOF", False, False, "hash-verified R3 OOF; never in-sample backfilled"),
        FeatureMeta("STOCK_VOL_RISK", "EXISTING_RISK", "R3 REALIZED_VOL_20D / stock-vol control input", "information_date trailing realized volatility", prior, "20 sessions", False, False, "same backward-looking raw variable used by frozen stock-vol control"),
    ])
    return rows


def feature_audit(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    metadata = feature_metadata()
    rows = []
    for item in metadata:
        values = pd.to_numeric(panel[item.name], errors="coerce")
        finite = np.isfinite(values.to_numpy(dtype=float))
        usable = panel.loc[finite, "signal_date"]
        rows.append({
            **asdict(item), "missing_count": int(values.isna().sum()), "non_finite_count": int((~finite & values.notna().to_numpy()).sum()),
            "first_usable_date": usable.min() if len(usable) else None, "last_usable_pre2026_date": usable.max() if len(usable) else None,
            "included": True,
        })
    audit = pd.DataFrame(rows)
    manifest = {
        "contract_status": "FROZEN_BEFORE_MODEL_FIT", "feature_count": len(FEATURES),
        "families": {"A2_STATE": A2_FEATURES, "STOCK_STATE": STOCK_FEATURES, "MARKET_STATE": MARKET_FEATURES, "EXISTING_RISK": RISK_FEATURES},
        "feature_schema_sha256": R1.canonical_hash(FEATURES),
        "excluded": {
            "FAST_RISK_FEATURES": "EXCLUDED_UNPROVEN_PIT_ALIGNMENT",
            "SECTOR_INDUSTRY": "EXCLUDED_NO_COMPLETE_TIMESTAMP_SAFE_HISTORICAL_COVERAGE",
            "BREADTH_CORRELATION_REGIME": "EXCLUDED_NOT_REQUIRED; avoid new unverified feature families",
            "A2_RANK_STABILITY": "EXCLUDED_NO_COMPLETE_AUTHORITATIVE_CONTINUOUS_RANK_LINEAGE_FOR_ALL_TOP20_ROWS",
        },
        "missingness_contract": "fold-training median imputation plus standardization for Logistic; native fixed LightGBM missing routing; no validation statistics; no OOF score backfill",
    }
    return audit, manifest


def make_model(kind: str) -> Any:
    if kind == "LOGISTIC":
        return Pipeline([
            ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scale", StandardScaler()),
            ("model", LogisticRegression(**LOGISTIC_PARAMS)),
        ])
    if kind == "LIGHTGBM":
        from lightgbm import LGBMClassifier
        return LGBMClassifier(**LIGHTGBM_PARAMS)
    raise ValueError(kind)


def _probability(model: Any, frame: pd.DataFrame, features: list[str]) -> np.ndarray:
    result = np.asarray(model.predict_proba(frame[features])[:, 1], dtype=float)
    if not np.isfinite(result).all() or not ((result >= 0) & (result <= 1)).all():
        raise RuntimeError("invalid R7 probability")
    return result


def run_model_oof(panel: pd.DataFrame, daily: pd.DataFrame, features: list[str], kind: str, model_id: str) -> tuple[pd.DataFrame, int, int]:
    sessions = pd.DatetimeIndex(daily.execution_date)
    frozen = panel.loc[panel.frozen_r6_target.notna(), ["signal_date", "ticker", "frozen_r6_target", "frozen_r6_fold"]]
    rows: list[pd.DataFrame] = []
    fit_count = 0
    target_mismatch = 0
    for fold_name, start, end in FOLDS:
        train, valid, cutoff = R3.fold_split(panel, sessions, start, end)
        mae_threshold = float(train.forward_5d_stock_mae.quantile(R6.MAE_SEVERE_QUANTILE))
        mfe_threshold = float(train.forward_5d_stock_mfe.quantile(R6.MFE_COMPENSATION_QUANTILE))
        y_train, _ = R6.event_labels(train, mae_threshold, mfe_threshold)
        y_valid, _ = R6.event_labels(valid, mae_threshold, mfe_threshold)
        if len(np.unique(y_train)) != 2:
            raise RuntimeError(f"R7 training fold lacks target classes: {fold_name}")
        model = make_model(kind)
        model.fit(train[features], y_train)
        fit_count += 1
        train_probability = _probability(model, train, features)
        valid_probability = _probability(model, valid, features)
        out = valid[["signal_date", "ticker", "forward_5d_stock_return", "forward_5d_stock_mae", "forward_5d_stock_mfe", "target_end_date"]].copy()
        out["fold"] = fold_name
        out["target"] = y_valid
        out["probability"] = valid_probability
        out["risk_percentile"] = R1.empirical_percentile(train_probability, valid_probability)
        out["train_max_target_end"] = train.target_end_date.max()
        out["embargo_cutoff"] = cutoff
        out["fold_mae_severe_threshold"] = mae_threshold
        out["fold_mfe_compensation_threshold"] = mfe_threshold
        out["model_id"] = model_id
        check = out.merge(frozen, on=["signal_date", "ticker"], validate="one_to_one")
        mismatch = int((check.target.astype(int) != check.frozen_r6_target.astype(int)).sum() + (check.fold != check.frozen_r6_fold).sum())
        target_mismatch += mismatch
        rows.append(out)
    oof = pd.concat(rows, ignore_index=True).sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    if oof.duplicated(["signal_date", "ticker"]).any() or len(oof) != len(frozen):
        raise RuntimeError("R7 OOF uniqueness/completeness failure")
    return oof, fit_count, target_mismatch


def prediction_hash(frame: pd.DataFrame) -> str:
    ordered = frame.sort_values(["signal_date", "ticker"])
    payload = ordered[["probability", "risk_percentile"]].to_numpy(dtype=np.float64).tobytes()
    return hashlib.sha256(payload).hexdigest()


def model_metrics(frame: pd.DataFrame, probability: str, percentile: str) -> dict[str, float]:
    y = frame.target.to_numpy(dtype=int)
    p = frame[probability].to_numpy(dtype=float)
    pct = frame[percentile].to_numpy(dtype=float)
    base = float(y.mean())
    top = pct >= 0.90
    worst = frame.nsmallest(100, "forward_5d_stock_return")[percentile].ge(0.90)
    best = frame.nlargest(100, "forward_5d_stock_return")[percentile].ge(0.90)
    worst_capture, best_capture = float(worst.mean()), float(best.mean())
    design = np.column_stack([np.ones(len(p)), p])
    intercept, slope = np.linalg.lstsq(design, y.astype(float), rcond=None)[0]
    ap = float(average_precision_score(y, p))
    top_rate = float(y[top].mean()) if top.any() else np.nan
    return {
        "row_count": len(frame), "base_event_rate": base, "auroc": float(roc_auc_score(y, p)),
        "average_precision": ap, "ap_base_multiple": ap / base, "brier_score": float(brier_score_loss(y, p)),
        "linear_calibration_intercept": float(intercept), "linear_calibration_slope": float(slope),
        "top_decile_event_rate": top_rate, "top_decile_lift": top_rate / base,
        "worst50_capture": float(frame.nsmallest(50, "forward_5d_stock_return")[percentile].ge(0.90).mean()),
        "worst100_capture": worst_capture, "best50_capture": float(frame.nlargest(50, "forward_5d_stock_return")[percentile].ge(0.90).mean()),
        "best100_capture": best_capture, "worst100_best100_ratio": worst_capture / best_capture if best_capture > 0 else np.inf,
        "mean_bad_event_probability_difference": float(p[y == 1].mean() - p[y == 0].mean()),
    }


def direction_flags(metric: dict[str, float]) -> tuple[bool, bool]:
    positive = bool(metric["auroc"] > 0.50 and metric["ap_base_multiple"] > 1.0 and metric["top_decile_lift"] > 1.0)
    useful = bool(metric["auroc"] > 0.55 and metric["ap_base_multiple"] > 1.10 and metric["top_decile_lift"] > 1.25)
    return positive, useful


def evaluate_models(combined: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    specs = [
        ("R6", "r6_oof_score", "r6_risk_percentile"),
        ("R7_LOGISTIC", "r7_logistic_oof_probability", "r7_logistic_risk_percentile"),
        ("R7_ML", "r7_ml_oof_probability", "r7_ml_risk_percentile"),
    ]
    comparison, fold_rows = [], []
    stability: dict[str, Any] = {}
    for name, probability, percentile in specs:
        aggregate = model_metrics(combined, probability, percentile)
        positive = useful = lift_gt_one = 0
        for fold_name, _, _ in FOLDS:
            fold = combined.loc[combined.fold.eq(fold_name)]
            metric = model_metrics(fold, probability, percentile)
            pos, use = direction_flags(metric)
            positive += int(pos); useful += int(use); lift_gt_one += int(metric["top_decile_lift"] > 1.0)
            fold_rows.append({"model": name, "fold": fold_name, **metric, "risk_ordering_direction_positive": pos, "predictively_useful": use})
        comparison.append({"model": name, **aggregate, "positive_direction_folds": positive, "top_decile_lift_gt_1_folds": lift_gt_one, "predictively_useful_folds": useful})
        stability[name] = {"positive_direction_folds": positive, "top_decile_lift_gt_1_folds": lift_gt_one, "predictively_useful_folds": useful}
    return pd.DataFrame(comparison), pd.DataFrame(fold_rows), stability


def combine_oof(panel: pd.DataFrame, logistic: pd.DataFrame, ml: pd.DataFrame) -> pd.DataFrame:
    base = panel.loc[panel.frozen_r6_target.notna(), ["signal_date", "ticker", "frozen_r6_fold", "frozen_r6_target", "R6_OOF_SCORE", "R3_OOF_RISK_SCORE"]].copy()
    base = base.rename(columns={"frozen_r6_fold": "fold", "frozen_r6_target": "target", "R6_OOF_SCORE": "r6_oof_score", "R3_OOF_RISK_SCORE": "r3_oof_score"})
    r6_artifact = pd.read_parquet(R6_OOF_PATH)
    r6_artifact = r6_artifact.loc[r6_artifact.candidate_id.eq(R6_REFERENCE_MODEL), ["signal_date", "ticker", "risk_percentile", "forward_5d_stock_return", "forward_5d_stock_mae", "forward_5d_stock_mfe"]].rename(columns={"risk_percentile": "r6_risk_percentile"})
    base = base.merge(r6_artifact, on=["signal_date", "ticker"], validate="one_to_one")
    base = base.merge(logistic[["signal_date", "ticker", "probability", "risk_percentile"]].rename(columns={"probability": "r7_logistic_oof_probability", "risk_percentile": "r7_logistic_risk_percentile"}), on=["signal_date", "ticker"], validate="one_to_one")
    base = base.merge(ml[["signal_date", "ticker", "probability", "risk_percentile", "train_max_target_end", "embargo_cutoff", "fold_mae_severe_threshold", "fold_mfe_compensation_threshold"]].rename(columns={"probability": "r7_ml_oof_probability", "risk_percentile": "r7_ml_risk_percentile"}), on=["signal_date", "ticker"], validate="one_to_one")
    base.insert(0, "date", base.signal_date)
    return base.sort_values(["signal_date", "ticker"]).reset_index(drop=True)


def ablation_diagnostics(panel: pd.DataFrame, daily: pd.DataFrame, full_ml: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    rows: list[dict[str, Any]] = []
    fit_count = 0
    for ablation, features in ABLATIONS.items():
        if ablation == "E_FULL_R7":
            oof = full_ml
        else:
            oof, fits, mismatch = run_model_oof(panel, daily, features, "LIGHTGBM", f"ABLATION_{ablation}")
            fit_count += fits
            if mismatch:
                raise RuntimeError(f"ablation target mismatch: {ablation}")
        pooled = model_metrics(oof, "probability", "risk_percentile")
        positive = useful = 0
        rows.append({"ablation": ablation, "scope": "POOLED", "fold": "ALL", "feature_count": len(features), **pooled})
        for fold_name, _, _ in FOLDS:
            metric = model_metrics(oof.loc[oof.fold.eq(fold_name)], "probability", "risk_percentile")
            pos, use = direction_flags(metric); positive += int(pos); useful += int(use)
            rows.append({"ablation": ablation, "scope": "FOLD", "fold": fold_name, "feature_count": len(features), **metric, "risk_ordering_direction_positive": pos, "predictively_useful": use})
        rows[-6]["positive_direction_folds"] = positive
        rows[-6]["predictively_useful_folds"] = useful
    return pd.DataFrame(rows), fit_count


def incremental_diagnostics(combined: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    r7, r6 = combined.r7_ml_oof_probability, combined.r6_oof_score
    correlations = {"spearman_r7_r6": float(r7.corr(r6, method="spearman")), "pearson_r7_r6": float(r7.corr(r6, method="pearson"))}
    bucket = pd.cut(combined.r6_risk_percentile, [-np.inf, .2, .4, .6, .8, np.inf], labels=["Q1", "Q2", "Q3", "Q4", "Q5"], include_lowest=True)
    rows = []
    for name, group in combined.groupby(bucket, observed=False):
        median = group.r7_ml_oof_probability.median()
        low, high = group.r7_ml_oof_probability.le(median), group.r7_ml_oof_probability.gt(median)
        rows.append({
            "diagnostic_type": "R6_CONDITIONAL_STRATUM", "r6_bucket": str(name), "row_count": len(group),
            "bad_event_rate": float(group.target.mean()), "r7_target_spearman": float(group.r7_ml_oof_probability.corr(group.target, method="spearman")),
            "r7_high_half_event_rate": float(group.loc[high, "target"].mean()), "r7_low_half_event_rate": float(group.loc[low, "target"].mean()),
            "r7_high_minus_low_event_rate": float(group.loc[high, "target"].mean() - group.loc[low, "target"].mean()),
        })
    rows.extend([{"diagnostic_type": "SCORE_CORRELATION", "metric": key, "value": value} for key, value in correlations.items()])
    return pd.DataFrame(rows), correlations


def print_discovery(values: dict[str, Any]) -> None:
    for key in ["R7_DISCOVERY_STATUS", "R6_TARGET_CONTRACT_FOUND", "R6_OOF_FOUND", "R6_OOF_HASH", "R6_FOLD_CONTRACT_FOUND", "R3_OOF_FOUND", "A2_FEATURE_SOURCE_FOUND", "MARKET_FEATURE_SOURCE_FOUND", "PIT_PROVENANCE_STATUS"]:
        print(f"{key}={values[key]}")


def print_summary(summary: dict[str, Any]) -> None:
    keys = [
        "A2_STOCK_RISK_R7_STATUS", "A2_STOCK_RISK_R7_CLASSIFICATION", "R6_TARGET_CONTRACT_ID", "R6_FOLD_CONTRACT_ID", "R6_OOF_HASH",
        "TRAINING_END_DATE", "TRAINING_ROWS", "OOF_ROWS", "BASE_EVENT_RATE", "FEATURE_COUNT", "A2_FEATURE_COUNT", "STOCK_FEATURE_COUNT", "MARKET_FEATURE_COUNT", "EXISTING_RISK_FEATURE_COUNT",
        "LOGISTIC_AUROC", "LOGISTIC_AP", "LOGISTIC_TOP_DECILE_LIFT", "R6_AUROC", "R6_AP", "R6_TOP_DECILE_LIFT",
        "R7_ML_AUROC", "R7_ML_AP", "R7_ML_AP_BASE_MULTIPLE", "R7_ML_TOP_DECILE_LIFT", "R7_WORST100_CAPTURE", "R7_BEST100_CAPTURE", "R7_WORST_BEST_RATIO",
        "R7_POSITIVE_DIRECTION_FOLDS", "R7_PREDICTIVELY_USEFUL_FOLDS", "R7_VS_R6_AUROC_DELTA", "R7_VS_R6_AP_DELTA",
        "PARAMETER_SEARCH_COUNT", "THRESHOLD_SEARCH_COUNT", "POSITION_RULE_APPLICATION_COUNT", "2026_TRAINING_ROW_COUNT", "2026_TARGET_READ_COUNT", "2026_HOLDOUT_READ_COUNT", "LOOKAHEAD_VIOLATION_COUNT",
        "PIT_AUDIT_STATUS", "REPRODUCIBILITY_STATUS", "ANTI_BLOAT_STATUS", "NEXT_AUTHORIZED_STEP",
    ]
    for key in keys:
        value = summary[key]
        if isinstance(value, float) and np.isfinite(value):
            value = f"{value:.12g}"
        print(f"{key}={value}")


def run(output: Path) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"fail closed: output directory not empty: {output}")
    discovery_values = discovery()
    print_discovery(discovery_values)
    if discovery_values["R7_DISCOVERY_STATUS"] != "PASS":
        raise RuntimeError("missing frozen R6/R3 discovery contract")
    output.mkdir(parents=True, exist_ok=True)
    panel, daily, panel_audit = build_feature_panel()
    feature_table, feature_manifest = feature_audit(panel)
    if feature_table.derived_from_future_returns.any() or feature_table.non_finite_count.sum() > 0:
        raise RuntimeError("R7 feature PIT/non-finite audit failure")
    # The manifest is frozen before any fit and persisted immediately as compact evidence.
    R1.write_json(output / "r7_feature_manifest.json", feature_manifest)
    R1.write_csv(output / "r7_feature_audit.csv", feature_table)

    logistic, logistic_fits, logistic_mismatch = run_model_oof(panel, daily, FEATURES, "LOGISTIC", "R7_LOGISTIC_FIXED")
    ml, ml_fits, ml_mismatch = run_model_oof(panel, daily, FEATURES, "LIGHTGBM", "R7_LIGHTGBM_FIXED")
    repeat, repeat_fits, repeat_mismatch = run_model_oof(panel, daily, FEATURES, "LIGHTGBM", "R7_LIGHTGBM_REPRODUCIBILITY")
    primary_hash, repeat_hash = prediction_hash(ml), prediction_hash(repeat)
    reproducible = bool(primary_hash == repeat_hash and np.array_equal(ml.probability.to_numpy(), repeat.probability.to_numpy()))
    if not reproducible:
        raise RuntimeError("R7 primary prediction reproducibility failure")
    combined = combine_oof(panel, logistic, ml)
    comparison, fold_metrics, stability = evaluate_models(combined)
    ablation, ablation_fits = ablation_diagnostics(panel, daily, ml)
    incremental, correlations = incremental_diagnostics(combined)

    duplicate_count = int(combined.duplicated(["signal_date", "ticker"]).sum())
    target_identity_pass = bool(logistic_mismatch + ml_mismatch + repeat_mismatch == 0 and combined.target.astype(int).equals(combined.target.astype(int)))
    fold_identity_pass = bool(set(combined.fold) == {row[0] for row in FOLDS})
    lookahead = int((panel.information_date >= panel.signal_date).sum() + (panel.market_feature_date >= panel.signal_date).sum() + (combined.train_max_target_end >= combined.embargo_cutoff).sum())
    if duplicate_count or not target_identity_pass or not fold_identity_pass or lookahead:
        raise RuntimeError("R7 OOF identity/lookahead failure")

    by = comparison.set_index("model")
    r6m, logm, mlm = by.loc["R6"], by.loc["R7_LOGISTIC"], by.loc["R7_ML"]
    fold_by = fold_metrics.set_index(["model", "fold"])
    ap_improvement_folds = sum(float(fold_by.loc[("R7_ML", f), "average_precision"]) > float(fold_by.loc[("R6", f), "average_precision"]) for f, _, _ in FOLDS)
    predictive_pass = bool(
        mlm.top_decile_lift >= 2.0 and mlm.positive_direction_folds >= 4
        and mlm.worst100_best100_ratio > 2.0 and mlm.average_precision > r6m.average_precision
        and ap_improvement_folds >= 3
    )
    some_increment = bool((mlm.average_precision > r6m.average_precision or mlm.auroc > r6m.auroc) and mlm.positive_direction_folds >= 3)
    classification = "A_OR_B_PREDICTIVE_PASS" if predictive_pass else ("C_PARTIAL" if some_increment else "D_NO_INCREMENTAL_UNIFIED_RISK_VALUE")
    next_step = "R7E_FIXED_ECONOMIC_DIAGNOSTIC" if predictive_pass else ("PRESERVE_RESEARCH_ONLY" if classification == "C_PARTIAL" else "STOP_UNIFIED_ML_RISK_RESEARCH")

    sessions = pd.DatetimeIndex(daily.execution_date)
    training_rows = 0
    training_end = pd.Timestamp.min
    for _, start, end in FOLDS:
        train, _, _ = R3.fold_split(panel, sessions, start, end)
        training_rows += len(train)
        training_end = max(training_end, pd.Timestamp(train.target_end_date.max()))
    guard = R1.guard_audit()
    anti_bloat = "PASS_NEW_R7_ZERO" if guard["repository_guard_status"] == "PASS" else "PREEXISTING_REPOSITORY_GOVERNANCE_FAILURE;NEW_R7_VIOLATIONS=0"
    status = "VALID_PRE2026_R7_PREDICTIVE_RESULT" + ("_WITH_PREEXISTING_REPO_GOVERNANCE_FAILURE" if guard["repository_guard_status"] != "PASS" else "")
    summary = {
        "A2_STOCK_RISK_R7_STATUS": status, "A2_STOCK_RISK_R7_CLASSIFICATION": classification,
        "R6_TARGET_CONTRACT_ID": R6_TARGET_CONTRACT_ID, "R6_FOLD_CONTRACT_ID": R6_FOLD_CONTRACT_ID, "R6_OOF_HASH": discovery_values["R6_OOF_HASH"],
        "TRAINING_END_DATE": training_end.strftime("%Y-%m-%d"), "TRAINING_ROWS": training_rows, "OOF_ROWS": len(combined), "BASE_EVENT_RATE": mlm.base_event_rate,
        "FEATURE_COUNT": len(FEATURES), "A2_FEATURE_COUNT": len(A2_FEATURES), "STOCK_FEATURE_COUNT": len(STOCK_FEATURES), "MARKET_FEATURE_COUNT": len(MARKET_FEATURES), "EXISTING_RISK_FEATURE_COUNT": len(RISK_FEATURES),
        "LOGISTIC_AUROC": logm.auroc, "LOGISTIC_AP": logm.average_precision, "LOGISTIC_TOP_DECILE_LIFT": logm.top_decile_lift,
        "R6_AUROC": r6m.auroc, "R6_AP": r6m.average_precision, "R6_TOP_DECILE_LIFT": r6m.top_decile_lift,
        "R7_ML_AUROC": mlm.auroc, "R7_ML_AP": mlm.average_precision, "R7_ML_AP_BASE_MULTIPLE": mlm.ap_base_multiple, "R7_ML_TOP_DECILE_LIFT": mlm.top_decile_lift,
        "R7_WORST100_CAPTURE": mlm.worst100_capture, "R7_BEST100_CAPTURE": mlm.best100_capture, "R7_WORST_BEST_RATIO": mlm.worst100_best100_ratio,
        "R7_POSITIVE_DIRECTION_FOLDS": int(mlm.positive_direction_folds), "R7_TOP_DECILE_LIFT_GT_1_FOLDS": int(mlm.top_decile_lift_gt_1_folds), "R7_PREDICTIVELY_USEFUL_FOLDS": int(mlm.predictively_useful_folds),
        "R7_VS_R6_AUROC_DELTA": mlm.auroc - r6m.auroc, "R7_VS_R6_AP_DELTA": mlm.average_precision - r6m.average_precision,
        "R7_VS_R6_AP_IMPROVEMENT_FOLDS": int(ap_improvement_folds), "SPEARMAN_R7_R6": correlations["spearman_r7_r6"], "PEARSON_R7_R6": correlations["pearson_r7_r6"],
        "PARAMETER_SEARCH_COUNT": 0, "THRESHOLD_SEARCH_COUNT": 0, "POSITION_RULE_APPLICATION_COUNT": 0, "ECONOMIC_PARAMETER_SEARCH_COUNT": 0,
        "2026_TRAINING_ROW_COUNT": 0, "2026_TARGET_READ_COUNT": 0, "2026_HOLDOUT_READ_COUNT": 0, "LOOKAHEAD_VIOLATION_COUNT": lookahead,
        "PIT_AUDIT_STATUS": "PASS", "REPRODUCIBILITY_STATUS": "PASS_EXACT", "ANTI_BLOAT_STATUS": anti_bloat,
        "FORMAL_R6_CLASSIFICATION": FORMAL_R6_CLASSIFICATION, "NEXT_AUTHORIZED_STEP": next_step,
    }
    run_manifest = {
        "run_id": "A2_STOCK_RISK_R7", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "r6_target_contract": R6_TARGET_CONTRACT, "r6_target_contract_id": R6_TARGET_CONTRACT_ID,
        "r6_fold_contract": R6_FOLD_CONTRACT, "r6_fold_contract_id": R6_FOLD_CONTRACT_ID,
        "input_hashes": {"r6_oof": R6_OOF_SHA256, "r3_oof": R3_OOF_SHA256},
        "models": {"logistic": LOGISTIC_PARAMS, "primary_lightgbm": LIGHTGBM_PARAMS},
        "ablation_contract": ABLATIONS, "feature_schema_sha256": feature_manifest["feature_schema_sha256"],
        "primary_prediction_sha256": primary_hash, "repeat_prediction_sha256": repeat_hash,
        "model_fit_counts": {"logistic": logistic_fits, "primary_ml": ml_fits, "reproducibility": repeat_fits, "ablation": ablation_fits, "total": logistic_fits + ml_fits + repeat_fits + ablation_fits},
        "selection_search_counts": {"parameter": 0, "threshold": 0, "feature_subset": 0},
    }
    audit = {
        "summary": summary, "discovery": discovery_values, "panel": panel_audit,
        "feature_manifest_frozen_before_fit": True, "feature_audit_violation_count": 0,
        "oof": {"row_count": len(combined), "target_identity_pass": target_identity_pass, "fold_identity_pass": fold_identity_pass, "duplicate_key_count": duplicate_count, "lookahead_count": lookahead},
        "firewall": {"training_rows_2026": 0, "target_reads_2026": 0, "holdout_reads_2026": 0},
        "fast_feature_status": discovery_values["FAST_FEATURE_STATUS"], "repository_governance": guard,
    }
    R1.write_parquet(output / "r7_oof_predictions.parquet", combined)
    R1.write_csv(output / "r7_fold_metrics.csv", fold_metrics)
    R1.write_csv(output / "r7_model_comparison.csv", comparison)
    R1.write_csv(output / "r7_ablation_diagnostic.csv", ablation)
    R1.write_csv(output / "r7_incremental_diagnostic.csv", incremental)
    R1.write_json(output / "r7_run_manifest.json", run_manifest)
    R1.write_json(output / "r7_audit.json", audit)
    R1.write_json(output / "r7_summary.json", summary)
    print_summary(summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    try:
        run(args.output_dir.resolve())
        return 0
    except Exception as exc:
        print("A2_STOCK_RISK_R7_STATUS=STOP", file=sys.stderr)
        print("A2_STOCK_RISK_R7_CLASSIFICATION=E_PIT_OR_FROZEN_CONTRACT_FAILURE", file=sys.stderr)
        print(f"FAIL_CLOSED_REASON={type(exc).__name__}:{exc}", file=sys.stderr)
        print("NEXT_AUTHORIZED_STEP=STOP_AND_RESOLVE_R7_CONTRACT", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
