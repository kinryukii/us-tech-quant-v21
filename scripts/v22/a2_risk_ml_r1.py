"""A2 RISK-ML-R1: compact PIT-safe tail-risk overlay research runner.

This runner consumes the immutable A2 daily replay. It never reconstructs,
refits, or changes the frozen A2 alpha model. Generated evidence is written
only to the approved external results root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# The managed Windows sandbox denies joblib's worker-pipe creation. These
# single-thread limits change only execution mechanics, not any model contract.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

import joblib
import matplotlib
import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


REPO_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
OUTPUT_DIR = RESULTS_ROOT / "A2_RISK_ML_R1"
BASELINE_ROOT = RESULTS_ROOT / "A_VS_A2_QUARTERLY_13F_R1"
FREEZE_DIR = BASELINE_ROOT / "audit" / "freeze_r1"
BASELINE_MANIFEST = FREEZE_DIR / "frozen_baseline_manifest.json"
HASH_MANIFEST = FREEZE_DIR / "frozen_artifact_hashes.csv"
A2_DAILY = BASELINE_ROOT / "A2" / "portfolio_daily.parquet"
HOLDOUT_DAILY = (
    RESULTS_ROOT
    / "A_A2_2026_PRE_RISK_HOLDOUT_R1"
    / "a_a2_vs_qqq_20260615_latest_daily.parquet"
)
PRICE_YEAR_ROOT = Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq")
PRICE_POINTER = Path(
    r"D:\us-tech-quant-daily\current\V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD\canonical_snapshot_pointer.json"
)
VIX_PATH = Path(r"D:\us-tech-quant-data\fast3\vix_cboe_daily\canonical\vix_daily.parquet")
GUARD_PATH = REPO_ROOT / "fast3" / "scripts" / "audit" / "run_fast3_guard.py"
CANONICAL_PYTHON = Path(r"D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe")

FROZEN_BASELINE_NAME = "A_A2_QUARTERLY_13F_CLEAN_BASELINE_R1"
FROZEN_BASELINE_STATUS = "FROZEN_RESEARCH_BASELINE"
RISK_DECISION_TIMESTAMP = "09:25 America/New_York on signal_date"
FEATURE_INFORMATION_CUTOFF = "prior US trading session completed by 16:15 America/New_York"
TRAINING_CUTOFF = pd.Timestamp("2026-01-01")
HOLDOUT_START = pd.Timestamp("2026-06-15")
OVERLAY_COST_RATE = 0.001  # frozen 10 bps round-trip contract
PREEXISTING_GUARD_COUNT = 38
PREEXISTING_GUARD_SHA256 = "1f6cefd59d40cb9727dff018aec7fd7b0bd25f4f964cf9df6bc48110f4958fd3"

FEATURES = [
    "VIX_LEVEL",
    "VIX_CHANGE_1D",
    "VIX_CHANGE_5D",
    "VIX_PERCENTILE_252D",
    "QQQ_REALIZED_VOL_20D",
    "QQQ_RETURN_5D",
    "QQQ_RETURN_20D",
    "QQQ_DRAWDOWN_60D",
    "QQQ_DISTANCE_MA50",
    "SPY_REALIZED_VOL_20D",
    "SPY_RETURN_5D",
    "SPY_RETURN_20D",
    "SPY_DRAWDOWN_60D",
    "SPY_DISTANCE_MA50",
]

FOLDS = [
    ("FOLD_1", "2023-07-03", "2023-09-29"),
    ("FOLD_2", "2023-10-02", "2023-12-29"),
    ("FOLD_3", "2024-01-02", "2024-06-28"),
    ("FOLD_4", "2024-07-01", "2024-12-31"),
    ("FOLD_5", "2025-01-02", "2025-12-31"),
]


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    family: str
    params: dict[str, Any]


CANDIDATES = [
    Candidate("LOGIT_C03", "LogisticRegression", {"C": 0.3}),
    Candidate("LOGIT_C10", "LogisticRegression", {"C": 1.0}),
    Candidate(
        "HGB_SHALLOW_1",
        "HistGradientBoostingClassifier",
        {"learning_rate": 0.05, "max_iter": 80, "max_leaf_nodes": 7, "max_depth": 3, "min_samples_leaf": 30, "l2_regularization": 5.0},
    ),
    Candidate(
        "HGB_SHALLOW_2",
        "HistGradientBoostingClassifier",
        {"learning_rate": 0.03, "max_iter": 120, "max_leaf_nodes": 15, "max_depth": 4, "min_samples_leaf": 40, "l2_regularization": 10.0},
    ),
    Candidate(
        "LGBM_SHALLOW_1",
        "LightGBMClassifier",
        {"n_estimators": 100, "learning_rate": 0.03, "num_leaves": 7, "max_depth": 3, "min_child_samples": 30, "reg_alpha": 1.0, "reg_lambda": 5.0},
    ),
    Candidate(
        "LGBM_SHALLOW_2",
        "LightGBMClassifier",
        {"n_estimators": 150, "learning_rate": 0.03, "num_leaves": 15, "max_depth": 4, "min_child_samples": 40, "reg_alpha": 1.0, "reg_lambda": 10.0},
    ),
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def write_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(clean_json(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(tmp, index=False)
    os.replace(tmp, path)


def write_parquet(path: Path, frame: pd.DataFrame) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def verify_frozen_baseline() -> dict[str, Any]:
    manifest = json.loads(BASELINE_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("frozen_baseline_name") != FROZEN_BASELINE_NAME:
        raise RuntimeError("frozen baseline name mismatch")
    if manifest.get("status") != FROZEN_BASELINE_STATUS:
        raise RuntimeError("frozen baseline status mismatch")
    expected_manifest_hash = manifest["artifact_hash_manifest"]["sha256"]
    if sha256_file(HASH_MANIFEST) != expected_manifest_hash:
        raise RuntimeError("frozen hash-manifest digest mismatch")
    hashes = pd.read_csv(HASH_MANIFEST)
    failures: list[str] = []
    for row in hashes.itertuples(index=False):
        path = Path(row.absolute_path)
        if not path.is_file() or sha256_file(path) != row.sha256:
            failures.append(str(path))
    if failures:
        raise RuntimeError(f"frozen artifact verification failed: {failures}")
    a2_row = hashes.loc[hashes["artifact_id"].eq("a2_returns")].iloc[0]
    if Path(a2_row["absolute_path"]) != A2_DAILY:
        raise RuntimeError("authoritative A2 return artifact path mismatch")
    return {
        "baseline_name": FROZEN_BASELINE_NAME,
        "baseline_status": FROZEN_BASELINE_STATUS,
        "verified_artifact_count": int(len(hashes)),
        "hash_failure_count": 0,
        "a2_daily_sha256": str(a2_row["sha256"]),
        "cost_bps_round_trip": manifest["contracts"]["evaluation"]["cost_bps_round_trip"],
    }


def load_pre2026_prices() -> pd.DataFrame:
    parts = []
    for year in range(2019, 2026):
        path = PRICE_YEAR_ROOT / f"year={year}" / "prices.parquet"
        part = pd.read_parquet(path, columns=["ticker", "trade_date", "close", "source", "autype"])
        parts.append(part.loc[part["ticker"].isin(["QQQ", "SPY"])])
    data = pd.concat(parts, ignore_index=True)
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    data = data.loc[data["trade_date"].lt(TRAINING_CUTOFF)].copy()
    if set(data["ticker"].unique()) != {"QQQ", "SPY"}:
        raise RuntimeError("pre-2026 Moomoo QQQ/SPY coverage missing")
    if not data["source"].astype(str).str.contains("MOOMOO", case=False).all():
        raise RuntimeError("non-Moomoo price source in pre-2026 matrix")
    if not data["autype"].astype(str).str.upper().eq("QFQ").all():
        raise RuntimeError("non-QFQ price row in pre-2026 matrix")
    return data[["ticker", "trade_date", "close"]].drop_duplicates(["ticker", "trade_date"], keep="last")


def load_vix(before_2026_only: bool) -> pd.DataFrame:
    filters = [("DATE", "<", TRAINING_CUTOFF)] if before_2026_only else None
    data = pd.read_parquet(VIX_PATH, columns=["DATE", "CLOSE"], filters=filters)
    data = data.rename(columns={"DATE": "market_date", "CLOSE": "vix_close"})
    data["market_date"] = pd.to_datetime(data["market_date"])
    if before_2026_only:
        data = data.loc[data["market_date"].lt(TRAINING_CUTOFF)]
    return data.sort_values("market_date").drop_duplicates("market_date", keep="last")


def _rolling_percentile_last(values: np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    return float(np.mean(arr <= arr[-1]))


def build_market_features(prices: pd.DataFrame, vix: pd.DataFrame) -> pd.DataFrame:
    pivot = prices.pivot(index="trade_date", columns="ticker", values="close").sort_index()
    if not {"QQQ", "SPY"}.issubset(pivot.columns):
        raise RuntimeError("QQQ/SPY feature inputs missing")
    out = pd.DataFrame(index=pivot.index)
    for ticker in ["QQQ", "SPY"]:
        close = pivot[ticker].astype(float)
        ret = close.pct_change(fill_method=None)
        out[f"{ticker}_REALIZED_VOL_20D"] = ret.rolling(20, min_periods=20).std() * np.sqrt(252.0)
        out[f"{ticker}_RETURN_5D"] = close.pct_change(5, fill_method=None)
        out[f"{ticker}_RETURN_20D"] = close.pct_change(20, fill_method=None)
        out[f"{ticker}_DRAWDOWN_60D"] = close / close.rolling(60, min_periods=60).max() - 1.0
        out[f"{ticker}_DISTANCE_MA50"] = close / close.rolling(50, min_periods=50).mean() - 1.0
    out = out.reset_index().rename(columns={"trade_date": "market_date"})
    out = out.merge(vix, on="market_date", how="inner", validate="one_to_one")
    v = out["vix_close"].astype(float)
    out["VIX_LEVEL"] = v
    out["VIX_CHANGE_1D"] = v.pct_change(fill_method=None)
    out["VIX_CHANGE_5D"] = v.pct_change(5, fill_method=None)
    out["VIX_PERCENTILE_252D"] = v.rolling(252, min_periods=126).apply(_rolling_percentile_last, raw=True)
    return out[["market_date", *FEATURES]].dropna().sort_values("market_date").reset_index(drop=True)


def load_a2_training_matrix(features: pd.DataFrame) -> pd.DataFrame:
    raw = pd.read_parquet(A2_DAILY)
    raw = raw.rename(columns={"execution_date": "signal_date", "reconstructed_daily_return": "a2_return"})
    raw["signal_date"] = pd.to_datetime(raw["signal_date"])
    raw = raw.sort_values("signal_date").reset_index(drop=True)
    if raw["signal_date"].max() >= TRAINING_CUTOFF:
        raise RuntimeError("authoritative historical A2 artifact contains 2026 rows")
    raw["target_date"] = raw["signal_date"].shift(-1)
    raw["target_return"] = raw["a2_return"].shift(-1)
    joined = pd.merge_asof(
        raw.sort_values("signal_date"),
        features.sort_values("market_date"),
        left_on="signal_date",
        right_on="market_date",
        direction="backward",
        allow_exact_matches=False,
    )
    joined = joined.dropna(subset=["target_date", "target_return", *FEATURES]).copy()
    joined = joined.loc[joined["target_date"].lt(TRAINING_CUTOFF)].reset_index(drop=True)
    if not joined["market_date"].lt(joined["signal_date"]).all():
        raise RuntimeError("feature timing contract violation")
    return joined[["signal_date", "market_date", "target_date", "target_return", *FEATURES]]


def make_model(candidate: Candidate) -> Any:
    if candidate.family == "LogisticRegression":
        return Pipeline(
            [
                ("scale", StandardScaler()),
                ("model", LogisticRegression(C=candidate.params["C"], class_weight="balanced", solver="lbfgs", max_iter=2000, random_state=20260818)),
            ]
        )
    if candidate.family == "HistGradientBoostingClassifier":
        return HistGradientBoostingClassifier(
            **candidate.params,
            class_weight="balanced",
            early_stopping=False,
            random_state=20260818,
        )
    if candidate.family == "LightGBMClassifier":
        try:
            from lightgbm import LGBMClassifier
        except ImportError as exc:
            raise RuntimeError("LightGBM was preregistered because it was present, but import failed") from exc
        return LGBMClassifier(
            **candidate.params,
            objective="binary",
            class_weight="balanced",
            subsample=0.8,
            subsample_freq=1,
            colsample_bytree=0.8,
            random_state=20260818,
            n_jobs=1,
            deterministic=True,
            force_col_wise=True,
            verbosity=-1,
        )
    raise ValueError(candidate.family)


def empirical_percentile(reference: np.ndarray, values: np.ndarray) -> np.ndarray:
    ordered = np.sort(np.asarray(reference, dtype=float))
    return np.searchsorted(ordered, np.asarray(values, dtype=float), side="right") / len(ordered)


def direct_multiplier(percentiles: np.ndarray) -> np.ndarray:
    p = np.asarray(percentiles, dtype=float)
    return np.select([p <= 0.70, p <= 0.85, p <= 0.95], [1.0, 0.75, 0.50], default=0.25).astype(float)


def slow_reentry_multiplier(direct: np.ndarray) -> np.ndarray:
    levels = np.array([0.25, 0.50, 0.75, 1.00])
    result = np.empty(len(direct), dtype=float)
    previous = 1.0
    for i, target in enumerate(np.asarray(direct, dtype=float)):
        if target < previous:
            current = target
        elif target > previous:
            current = levels[min(int(np.searchsorted(levels, previous)) + 1, len(levels) - 1)]
            current = min(current, target)
        else:
            current = target
        result[i] = current
        previous = current
    return result


def controlled_returns(raw_return: np.ndarray, multiplier: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    previous = np.r_[1.0, np.asarray(multiplier, dtype=float)[:-1]]
    turnover = 0.5 * np.abs(np.asarray(multiplier, dtype=float) - previous)
    result = np.asarray(multiplier, dtype=float) * np.asarray(raw_return, dtype=float) - turnover * OVERLAY_COST_RATE
    return result, turnover


def performance_metrics(returns: pd.Series | np.ndarray) -> dict[str, float]:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) == 0:
        return {k: np.nan for k in ["total_return", "annualized_return", "volatility", "sharpe", "maximum_drawdown", "calmar", "profit_factor", "positive_day_pct", "worst_day", "expected_shortfall_5"]}
    equity = np.cumprod(1.0 + r)
    total = float(equity[-1] - 1.0)
    ann = float(equity[-1] ** (252.0 / len(r)) - 1.0) if equity[-1] > 0 else np.nan
    vol = float(np.std(r, ddof=1) * np.sqrt(252.0)) if len(r) > 1 else np.nan
    sharpe = float(np.mean(r) / np.std(r, ddof=1) * np.sqrt(252.0)) if len(r) > 1 and np.std(r, ddof=1) > 0 else np.nan
    peak = np.maximum.accumulate(np.r_[1.0, equity])
    dd = np.r_[1.0, equity] / peak - 1.0
    mdd = float(dd.min())
    calmar = float(ann / abs(mdd)) if mdd < 0 and np.isfinite(ann) else np.nan
    gains = float(r[r > 0].sum())
    losses = float(-r[r < 0].sum())
    pf = gains / losses if losses > 0 else np.inf
    cutoff = np.quantile(r, 0.05)
    return {
        "total_return": total,
        "annualized_return": ann,
        "volatility": vol,
        "sharpe": sharpe,
        "maximum_drawdown": mdd,
        "calmar": calmar,
        "profit_factor": float(pf),
        "positive_day_pct": float(np.mean(r > 0)),
        "worst_day": float(r.min()),
        "expected_shortfall_5": float(r[r <= cutoff].mean()),
    }


def predictive_metrics(y: np.ndarray, score: np.ndarray) -> dict[str, float]:
    y = np.asarray(y, dtype=int)
    score = np.clip(np.asarray(score, dtype=float), 1e-8, 1 - 1e-8)
    return {
        "auroc": float(roc_auc_score(y, score)),
        "average_precision": float(average_precision_score(y, score)),
        "brier_score": float(brier_score_loss(y, score)),
        "log_loss": float(log_loss(y, score, labels=[0, 1])),
        "base_tail_frequency": float(y.mean()),
    }


def risk_diagnostics(frame: pd.DataFrame) -> dict[str, float]:
    decile = np.clip(np.ceil(frame["risk_percentile"].to_numpy() * 10), 1, 10).astype(int)
    y = frame["y_tail_1d"].to_numpy(dtype=int)
    ret = frame["target_return"].to_numpy(dtype=float)
    base = float(y.mean())
    def rate(mask: np.ndarray) -> float:
        return float(y[mask].mean()) if np.any(mask) else np.nan

    result: dict[str, float] = {
        "tail_rate_decile_10": rate(decile == 10),
        "tail_rate_decile_9": rate(decile == 9),
        "tail_rate_bottom_80_percent": rate(decile <= 8),
    }
    result["top_decile_tail_lift"] = result["tail_rate_decile_10"] / base if base > 0 else np.nan
    for d in range(1, 11):
        result[f"mean_next_return_decile_{d}"] = float(ret[decile == d].mean()) if np.any(decile == d) else np.nan
        result[f"tail_rate_decile_{d}"] = float(y[decile == d].mean()) if np.any(decile == d) else np.nan
    return result


def economic_comparison(raw: np.ndarray, controlled: np.ndarray, turnover: np.ndarray) -> dict[str, float]:
    raw_m = performance_metrics(raw)
    ctl_m = performance_metrics(controlled)
    retention = ctl_m["total_return"] / raw_m["total_return"] if raw_m["total_return"] > 0 else np.nan
    mdd_reduction = 1.0 - abs(ctl_m["maximum_drawdown"]) / abs(raw_m["maximum_drawdown"]) if raw_m["maximum_drawdown"] < 0 else np.nan
    es_improvement = 1.0 - abs(ctl_m["expected_shortfall_5"]) / abs(raw_m["expected_shortfall_5"]) if raw_m["expected_shortfall_5"] < 0 else np.nan
    result = {f"raw_{k}": v for k, v in raw_m.items()}
    result.update({f"controlled_{k}": v for k, v in ctl_m.items()})
    result.update(
        {
            "return_retention": retention,
            "mdd_reduction": mdd_reduction,
            "expected_shortfall_5_improvement": es_improvement,
            "sharpe_delta": ctl_m["sharpe"] - raw_m["sharpe"],
            "exposure_turnover": float(np.sum(turnover)),
        }
    )
    return result


def run_oof(matrix: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, int]:
    predictions: list[pd.DataFrame] = []
    fit_count = 0
    for candidate in CANDIDATES:
        for fold_name, start_text, end_text in FOLDS:
            start, end = pd.Timestamp(start_text), pd.Timestamp(end_text)
            train = matrix.loc[matrix["target_date"].lt(start)].copy()
            valid = matrix.loc[matrix["target_date"].between(start, end)].copy()
            if len(train) < 100 or len(valid) < 20:
                raise RuntimeError(f"insufficient chronological data for {fold_name}")
            if train["target_date"].max() >= valid["target_date"].min():
                raise RuntimeError(f"walk-forward time violation in {fold_name}")
            threshold = float(train["target_return"].quantile(0.10))
            y_train = train["target_return"].le(threshold).astype(int)
            y_valid = valid["target_return"].le(threshold).astype(int)
            model = make_model(candidate)
            model.fit(train[FEATURES], y_train)
            fit_count += 1
            train_score = model.predict_proba(train[FEATURES])[:, 1]
            valid_score = model.predict_proba(valid[FEATURES])[:, 1]
            valid["candidate_id"] = candidate.candidate_id
            valid["model_family"] = candidate.family
            valid["fold"] = fold_name
            valid["fold_tail_threshold"] = threshold
            valid["y_tail_1d"] = y_valid.to_numpy()
            valid["y_negative_1d"] = valid["target_return"].lt(0).astype(int)
            valid["risk_score"] = valid_score
            valid["risk_percentile"] = empirical_percentile(train_score, valid_score)
            predictions.append(valid)
    oof = pd.concat(predictions, ignore_index=True).sort_values(["candidate_id", "target_date"]).reset_index(drop=True)
    comparison_rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        candidate_frame = oof.loc[oof["candidate_id"].eq(candidate.candidate_id)].copy()
        direct = direct_multiplier(candidate_frame["risk_percentile"].to_numpy())
        slow = slow_reentry_multiplier(direct)
        for mapping, multipliers in [("DIRECT_MAPPING", direct), ("SLOW_REENTRY_MAPPING", slow)]:
            controlled, turnover = controlled_returns(candidate_frame["target_return"].to_numpy(), multipliers)
            candidate_frame[f"{mapping}_multiplier"] = multipliers
            candidate_frame[f"{mapping}_controlled_return"] = controlled
            candidate_frame[f"{mapping}_exposure_turnover"] = turnover
            pred = predictive_metrics(candidate_frame["y_tail_1d"], candidate_frame["risk_score"])
            diag = risk_diagnostics(candidate_frame)
            econ = economic_comparison(candidate_frame["target_return"].to_numpy(), controlled, turnover)
            benefit_folds = 0
            direction_folds = 0
            for fold_name, _, _ in FOLDS:
                fold = candidate_frame.loc[candidate_frame["fold"].eq(fold_name)]
                fm = predictive_metrics(fold["y_tail_1d"], fold["risk_score"])
                fd = risk_diagnostics(fold)
                fe = economic_comparison(
                    fold["target_return"].to_numpy(),
                    fold[f"{mapping}_controlled_return"].to_numpy(),
                    fold[f"{mapping}_exposure_turnover"].to_numpy(),
                )
                return_ok = fe["controlled_total_return"] >= (0.5 * fe["raw_total_return"] if fe["raw_total_return"] > 0 else fe["raw_total_return"] - 0.05)
                downside_better = (
                    abs(fe["controlled_maximum_drawdown"]) < abs(fe["raw_maximum_drawdown"])
                    or fe["controlled_expected_shortfall_5"] > fe["raw_expected_shortfall_5"]
                )
                benefit = bool(return_ok and downside_better)
                benefit_folds += int(benefit)
                direction_folds += int(fd["top_decile_tail_lift"] > 1.0)
                fold_rows.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "model_family": candidate.family,
                        "mapping": mapping,
                        "fold": fold_name,
                        **fm,
                        **fd,
                        **fe,
                        "tail_event_precision": fd["tail_rate_decile_10"],
                        "downside_benefit_without_catastrophic_return_loss": benefit,
                    }
                )
            qualifies_a = (
                econ["return_retention"] >= 0.85
                and (econ["mdd_reduction"] >= 0.15 or econ["expected_shortfall_5_improvement"] >= 0.20)
                and econ["sharpe_delta"] > 0
                and diag["top_decile_tail_lift"] >= 1.25
                and benefit_folds >= 4
                and direction_folds >= 3
                and pred["log_loss"] < 1.5
            )
            strong_b = (
                econ["return_retention"] >= 0.75
                and econ["sharpe_delta"] > 0
                and (econ["mdd_reduction"] > 0 or econ["expected_shortfall_5_improvement"] > 0)
                and diag["top_decile_tail_lift"] >= 1.25
                and benefit_folds >= 3
                and direction_folds >= 3
                and pred["log_loss"] < 1.5
            )
            qualification = "A" if qualifies_a else "STRONG_B" if strong_b else "D" if econ["return_retention"] < 0.50 else "C"
            comparison_rows.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "model_family": candidate.family,
                    "params_json": json.dumps(candidate.params, sort_keys=True),
                    "mapping": mapping,
                    **pred,
                    **diag,
                    **econ,
                    "benefit_fold_count": benefit_folds,
                    "predictive_direction_fold_count": direction_folds,
                    "qualification": qualification,
                }
            )
        mask = oof["candidate_id"].eq(candidate.candidate_id)
        for mapping in ["DIRECT_MAPPING", "SLOW_REENTRY_MAPPING"]:
            for suffix in ["multiplier", "controlled_return", "exposure_turnover"]:
                oof.loc[mask, f"{mapping}_{suffix}"] = candidate_frame[f"{mapping}_{suffix}"].to_numpy()
    return oof, pd.DataFrame(comparison_rows), pd.DataFrame(fold_rows), fit_count


def select_candidate(comparison: pd.DataFrame) -> tuple[pd.Series | None, str]:
    family_rank = {"LogisticRegression": 0, "HistGradientBoostingClassifier": 1, "LightGBMClassifier": 2}
    for qualification, classification in [("A", "A"), ("STRONG_B", "B")]:
        eligible = comparison.loc[comparison["qualification"].eq(qualification)].copy()
        if not eligible.empty:
            eligible["family_rank"] = eligible["model_family"].map(family_rank)
            simplest = eligible["family_rank"].min()
            eligible = eligible.loc[eligible["family_rank"].eq(simplest)]
            eligible = eligible.sort_values(
                ["sharpe_delta", "average_precision", "top_decile_tail_lift", "candidate_id", "mapping"],
                ascending=[False, False, False, True, True],
            )
            return eligible.iloc[0], classification
    classification = "D" if comparison["qualification"].eq("D").all() else "C"
    return None, classification


def diagnostic_reference(comparison: pd.DataFrame) -> pd.Series:
    """Choose a non-frozen reporting row using the simplicity/default rules."""
    family_rank = {"LogisticRegression": 0, "HistGradientBoostingClassifier": 1, "LightGBMClassifier": 2}
    frame = comparison.copy()
    frame["family_rank"] = frame["model_family"].map(family_rank)
    frame["mapping_rank"] = frame["mapping"].map({"DIRECT_MAPPING": 0, "SLOW_REENTRY_MAPPING": 1})
    simplest = frame["family_rank"].min()
    frame = frame.loc[frame["family_rank"].eq(simplest)]
    return frame.sort_values(
        ["sharpe_delta", "average_precision", "mapping_rank", "candidate_id"],
        ascending=[False, False, True, True],
    ).iloc[0]


def final_fit(matrix: pd.DataFrame, selected: pd.Series) -> tuple[Any, float, np.ndarray, int]:
    candidate = next(c for c in CANDIDATES if c.candidate_id == selected["candidate_id"])
    threshold = float(matrix["target_return"].quantile(0.10))
    y = matrix["target_return"].le(threshold).astype(int)
    model = make_model(candidate)
    model.fit(matrix[FEATURES], y)
    scores = model.predict_proba(matrix[FEATURES])[:, 1]
    score_cuts = np.quantile(scores, [0.70, 0.85, 0.95])
    return model, threshold, score_cuts, 1


def load_postfreeze_market(pre_prices: pd.DataFrame, pre_vix: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    pointer = json.loads(PRICE_POINTER.read_text(encoding="utf-8"))
    if pointer.get("source_policy") != "MOOMOO_ONLY" or pointer.get("external_fallback_used"):
        raise RuntimeError("canonical holdout price policy is not Moomoo-only")
    current = pd.read_csv(pointer["canonical_qfq_path"], usecols=["ticker", "date", "close", "adjustment", "source", "source_policy"])
    current["trade_date"] = pd.to_datetime(current.pop("date"))
    current = current.loc[current["ticker"].isin(["QQQ", "SPY"]) & current["trade_date"].ge(TRAINING_CUTOFF)].copy()
    if not current["source"].astype(str).str.contains("MOOMOO", case=False).all():
        raise RuntimeError("non-Moomoo price row opened after freeze")
    if not current["adjustment"].astype(str).str.upper().eq("QFQ").all():
        raise RuntimeError("non-QFQ holdout price row")
    if not current["source_policy"].astype(str).eq("MOOMOO_ONLY").all():
        raise RuntimeError("non-canonical holdout price policy row")
    prices = pd.concat([pre_prices, current[["ticker", "trade_date", "close"]]], ignore_index=True)
    prices = prices.drop_duplicates(["ticker", "trade_date"], keep="last")
    vix = pd.concat([pre_vix, load_vix(False).loc[lambda x: x["market_date"].ge(TRAINING_CUTOFF)]], ignore_index=True)
    vix = vix.drop_duplicates("market_date", keep="last")
    return build_market_features(prices, vix), {
        "canonical_snapshot_id": pointer["snapshot_id"],
        "canonical_qfq_path": pointer["canonical_qfq_path"],
        "price_max_date": current["trade_date"].max(),
        "vix_max_date": vix["market_date"].max(),
    }


def holdout_run(model: Any, train_scores: np.ndarray, mapping: str, market_features: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    raw = pd.read_parquet(HOLDOUT_DAILY)
    raw["date"] = pd.to_datetime(raw["date"])
    raw = raw.loc[raw["date"].ge(HOLDOUT_START)].sort_values("date").reset_index(drop=True)
    signals = pd.DataFrame({"signal_date": raw["date"].iloc[:-1], "target_date": raw["date"].iloc[1:]})
    signals["raw_a2_return"] = raw["A2_daily_return"].iloc[1:].to_numpy()
    signals["qqq_return"] = raw["QQQ_daily_return"].iloc[1:].to_numpy()
    signals = pd.merge_asof(
        signals.sort_values("signal_date"),
        market_features.sort_values("market_date"),
        left_on="signal_date",
        right_on="market_date",
        direction="backward",
        allow_exact_matches=False,
    ).dropna(subset=FEATURES)
    if not signals["market_date"].lt(signals["signal_date"]).all():
        raise RuntimeError("2026 feature timing violation")
    score = model.predict_proba(signals[FEATURES])[:, 1]
    percentile = empirical_percentile(train_scores, score)
    direct = direct_multiplier(percentile)
    slow = slow_reentry_multiplier(direct)
    chosen = direct if mapping == "DIRECT_MAPPING" else slow
    controlled, turnover = controlled_returns(signals["raw_a2_return"].to_numpy(), chosen)
    signals["risk_score"] = score
    signals["risk_percentile"] = percentile
    signals["direct_multiplier"] = direct
    signals["slow_reentry_multiplier"] = slow
    signals["risk_multiplier"] = chosen
    signals["exposure_change_turnover"] = turnover
    signals["controlled_a2_return"] = controlled
    result = signals.rename(columns={"target_date": "date"})[
        ["date", "signal_date", "market_date", "risk_score", "risk_percentile", "direct_multiplier", "slow_reentry_multiplier", "risk_multiplier", "exposure_change_turnover", "raw_a2_return", "controlled_a2_return", "qqq_return"]
    ].copy()
    base = pd.DataFrame(
        [{"date": HOLDOUT_START, "signal_date": pd.NaT, "market_date": pd.NaT, "risk_score": np.nan, "risk_percentile": np.nan, "direct_multiplier": 1.0, "slow_reentry_multiplier": 1.0, "risk_multiplier": 1.0, "exposure_change_turnover": 0.0, "raw_a2_return": 0.0, "controlled_a2_return": 0.0, "qqq_return": 0.0}]
    )
    result = pd.concat([base, result], ignore_index=True).sort_values("date").reset_index(drop=True)
    result["raw_a2_equity"] = 100.0 * (1.0 + result["raw_a2_return"]).cumprod()
    result["controlled_a2_equity"] = 100.0 * (1.0 + result["controlled_a2_return"]).cumprod()
    result["qqq_equity"] = 100.0 * (1.0 + result["qqq_return"]).cumprod()
    for prefix in ["raw_a2", "controlled_a2", "qqq"]:
        result[f"{prefix}_drawdown"] = result[f"{prefix}_equity"] / result[f"{prefix}_equity"].cummax() - 1.0
    return result, {
        "raw_available_end_date": raw["date"].max(),
        "scored_end_date": result["date"].max(),
        "unscored_raw_row_count_after_scored_end": int(raw["date"].gt(result["date"].max()).sum()),
    }


def relative_metrics(strategy: np.ndarray, benchmark: np.ndarray) -> dict[str, float]:
    s, b = np.asarray(strategy, dtype=float), np.asarray(benchmark, dtype=float)
    active = s - b
    beta = float(np.cov(s, b, ddof=1)[0, 1] / np.var(b, ddof=1)) if np.var(b, ddof=1) > 0 else np.nan
    ir = float(np.mean(active) / np.std(active, ddof=1) * np.sqrt(252.0)) if np.std(active, ddof=1) > 0 else np.nan
    up, down = b > 0, b < 0
    return {
        "beta_vs_qqq": beta,
        "information_ratio_vs_qqq": ir,
        "upside_capture_vs_qqq": float(s[up].sum() / b[up].sum()) if b[up].sum() != 0 else np.nan,
        "downside_capture_vs_qqq": float(s[down].sum() / b[down].sum()) if b[down].sum() != 0 else np.nan,
    }


def guard_audit() -> dict[str, Any]:
    proc = subprocess.run([str(CANONICAL_PYTHON), str(GUARD_PATH)], cwd=REPO_ROOT, text=True, capture_output=True, check=False)
    payload = json.loads(proc.stdout)
    violations = sorted(payload.get("violations", []))
    digest = hashlib.sha256(("\n".join(violations) + "\n").encode()).hexdigest()
    exact_preexisting_match = len(violations) == PREEXISTING_GUARD_COUNT and digest == PREEXISTING_GUARD_SHA256
    return {
        "repository_guard_status": payload.get("status"),
        "preexisting_violation_count": PREEXISTING_GUARD_COUNT,
        "post_run_violation_count": len(violations),
        "preexisting_violation_set_sha256": PREEXISTING_GUARD_SHA256,
        "post_run_violation_set_sha256": digest,
        "preexisting_violation_set_unchanged": exact_preexisting_match,
        "new_risk_r1_repo_violation_count": 0 if exact_preexisting_match else 1,
        "preexisting_violations": violations if exact_preexisting_match else [],
        "access_errors": next((c.get("access_errors", []) for c in payload.get("checks", []) if c.get("name") == "repository_budget"), []),
    }


def plot_results(output: Path, selected_oof: pd.DataFrame | None, mapping: str | None, holdout: pd.DataFrame | None) -> None:
    panels = 2 if holdout is not None and selected_oof is not None else 1
    fig, axes = plt.subplots(panels, 1, figsize=(10, 4.2 * panels), constrained_layout=True)
    axes = np.atleast_1d(axes)
    idx = 0
    if selected_oof is not None and mapping is not None:
        raw_eq = 100 * (1 + selected_oof["target_return"]).cumprod()
        ctl_eq = 100 * (1 + selected_oof[f"{mapping}_controlled_return"]).cumprod()
        axes[idx].plot(selected_oof["target_date"], raw_eq, label="A2 raw", linewidth=1.5)
        axes[idx].plot(selected_oof["target_date"], ctl_eq, label="A2 risk-controlled", linewidth=1.5)
        axes[idx].set_title("Pre-2026 walk-forward OOF equity")
        idx += 1
    if holdout is not None:
        axes[idx].plot(holdout["date"], holdout["raw_a2_equity"], label="A2 raw", linewidth=1.5)
        axes[idx].plot(holdout["date"], holdout["controlled_a2_equity"], label="A2 risk-controlled", linewidth=1.5)
        axes[idx].plot(holdout["date"], holdout["qqq_equity"], label="QQQ", linewidth=1.5)
        axes[idx].set_title("Frozen 2026 prospective holdout equity")
    for ax in axes:
        ax.set_ylabel("Equity (start = 100)")
        ax.set_xlabel("Date")
        ax.grid(alpha=0.25)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(handles, labels)
    fig.savefig(output / "risk_ml_r1_equity_curve.png", dpi=170)
    plt.close(fig)

    fig, axes = plt.subplots(panels, 1, figsize=(10, 4.2 * panels), constrained_layout=True)
    axes = np.atleast_1d(axes)
    idx = 0
    if selected_oof is not None and mapping is not None:
        raw_eq = (1 + selected_oof["target_return"]).cumprod()
        ctl_eq = (1 + selected_oof[f"{mapping}_controlled_return"]).cumprod()
        axes[idx].plot(selected_oof["target_date"], raw_eq / raw_eq.cummax() - 1, label="A2 raw", linewidth=1.5)
        axes[idx].plot(selected_oof["target_date"], ctl_eq / ctl_eq.cummax() - 1, label="A2 risk-controlled", linewidth=1.5)
        axes[idx].set_title("Pre-2026 walk-forward OOF drawdown")
        idx += 1
    if holdout is not None:
        axes[idx].plot(holdout["date"], holdout["raw_a2_drawdown"], label="A2 raw", linewidth=1.5)
        axes[idx].plot(holdout["date"], holdout["controlled_a2_drawdown"], label="A2 risk-controlled", linewidth=1.5)
        axes[idx].plot(holdout["date"], holdout["qqq_drawdown"], label="QQQ", linewidth=1.5)
        axes[idx].set_title("Frozen 2026 prospective holdout drawdown")
    for ax in axes:
        ax.set_ylabel("Drawdown")
        ax.set_xlabel("Date")
        ax.grid(alpha=0.25)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(handles, labels)
    fig.savefig(output / "risk_ml_r1_drawdown_curve.png", dpi=170)
    plt.close(fig)


def _fmt(value: Any) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "NOT_RUN"
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value)


def print_console(summary: dict[str, Any]) -> None:
    ordered = [
        "A2_RISK_ML_R1_STATUS", "A2_RISK_ML_R1_CLASSIFICATION", "SELECTED_MODEL", "FEATURE_COUNT", "TRAINING_END_DATE", "OOF_FOLD_COUNT",
        "OOF_AUROC", "OOF_AVERAGE_PRECISION", "OOF_TOP_DECILE_TAIL_LIFT", "RAW_A2_OOF_RETURN", "CONTROLLED_A2_OOF_RETURN", "RETURN_RETENTION",
        "RAW_A2_OOF_MDD", "CONTROLLED_A2_OOF_MDD", "MDD_REDUCTION", "RAW_A2_OOF_SHARPE", "CONTROLLED_A2_OOF_SHARPE",
        "HOLDOUT_START_DATE", "HOLDOUT_END_DATE", "RAW_A2_2026_RETURN", "CONTROLLED_A2_2026_RETURN", "QQQ_2026_RETURN",
        "RAW_A2_2026_MDD", "CONTROLLED_A2_2026_MDD", "QQQ_2026_MDD", "RAW_A2_2026_DOWNSIDE_CAPTURE", "CONTROLLED_A2_2026_DOWNSIDE_CAPTURE",
        "RAW_A2_2026_UPSIDE_CAPTURE", "CONTROLLED_A2_2026_UPSIDE_CAPTURE", "TRAINING_DATA_2026_COUNT", "OPTUNA_TRIAL_COUNT", "LOOKAHEAD_VIOLATION_COUNT",
        "NEW_RISK_R1_REPO_VIOLATION_COUNT", "NEXT_AUTHORIZED_STEP",
    ]
    for key in ordered:
        print(f"{key}={_fmt(summary.get(key))}")


def repair_existing_nonfreeze_reporting(output: Path) -> dict[str, Any]:
    """Repair C/D presentation from persisted OOF rows; performs zero fits/2026 reads."""
    required = [
        output / "risk_ml_r1_summary.json",
        output / "risk_ml_r1_audit.json",
        output / "risk_ml_r1_model_comparison.csv",
        output / "risk_ml_r1_oof_predictions.parquet",
        output / "risk_ml_r1_selected_model_manifest.json",
    ]
    if not all(path.is_file() for path in required):
        raise RuntimeError("non-freeze reporting repair requires completed persisted OOF evidence")
    summary = json.loads((output / "risk_ml_r1_summary.json").read_text(encoding="utf-8"))
    audit = json.loads((output / "risk_ml_r1_audit.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "risk_ml_r1_selected_model_manifest.json").read_text(encoding="utf-8"))
    if summary.get("A2_RISK_ML_R1_CLASSIFICATION") not in {"C", "D"}:
        raise RuntimeError("repair is limited to a valid non-freeze classification")
    if manifest.get("status") != "NOT_FROZEN_2026_NOT_OPENED":
        raise RuntimeError("repair refused because a model was frozen or 2026 may have been opened")
    holdout = pd.read_csv(output / "risk_ml_r1_2026_holdout.csv")
    if not holdout.empty:
        raise RuntimeError("repair refused because holdout output is not empty")
    comparison = pd.read_csv(output / "risk_ml_r1_model_comparison.csv")
    oof = pd.read_parquet(output / "risk_ml_r1_oof_predictions.parquet")
    reporting = diagnostic_reference(comparison)
    reporting_row = reporting.to_dict()
    selected_oof = oof.loc[oof["candidate_id"].eq(reporting["candidate_id"])].sort_values("target_date").copy()
    superseded = {
        name: sha256_file(output / name)
        for name in ["risk_ml_r1_summary.json", "risk_ml_r1_audit.json", "risk_ml_r1_selected_model_manifest.json", "risk_ml_r1_equity_curve.png", "risk_ml_r1_drawdown_curve.png"]
    }
    manifest["diagnostic_reference_model"] = reporting["candidate_id"]
    manifest["diagnostic_reference_mapping"] = reporting["mapping"]
    manifest["reporting_repair"] = "PRESENTATION_ONLY_ZERO_FITS_ZERO_2026_READS"
    write_json(output / "risk_ml_r1_selected_model_manifest.json", manifest)
    plot_results(output, selected_oof, reporting["mapping"], None)
    summary.update(
        {
            "OOF_REFERENCE_MODEL": reporting_row["candidate_id"],
            "OOF_REFERENCE_MAPPING": reporting_row["mapping"],
            "OOF_AUROC": reporting_row["auroc"],
            "OOF_AVERAGE_PRECISION": reporting_row["average_precision"],
            "OOF_TOP_DECILE_TAIL_LIFT": reporting_row["top_decile_tail_lift"],
            "RAW_A2_OOF_RETURN": reporting_row["raw_total_return"],
            "CONTROLLED_A2_OOF_RETURN": reporting_row["controlled_total_return"],
            "RETURN_RETENTION": reporting_row["return_retention"],
            "RAW_A2_OOF_MDD": reporting_row["raw_maximum_drawdown"],
            "CONTROLLED_A2_OOF_MDD": reporting_row["controlled_maximum_drawdown"],
            "MDD_REDUCTION": reporting_row["mdd_reduction"],
            "RAW_A2_OOF_SHARPE": reporting_row["raw_sharpe"],
            "CONTROLLED_A2_OOF_SHARPE": reporting_row["controlled_sharpe"],
            "oof_diagnostic_reference": reporting_row,
            "reporting_repair": "PRESENTATION_ONLY_ZERO_FITS_ZERO_2026_READS",
        }
    )
    audit["reporting_repair"] = {
        "status": "PASS",
        "reason": "non-freeze console/chart path originally omitted diagnostic OOF reference",
        "model_fit_count": 0,
        "holdout_read_count": 0,
        "parameter_or_threshold_change_count": 0,
        "superseded_artifact_sha256": superseded,
    }
    write_json(output / "risk_ml_r1_audit.json", audit)
    write_json(output / "risk_ml_r1_summary.json", summary)
    print_console(summary)
    return summary


def run(output: Path) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"fail closed: external output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    baseline_audit = verify_frozen_baseline()
    pre_prices = load_pre2026_prices()
    pre_vix = load_vix(True)
    market = build_market_features(pre_prices, pre_vix)
    matrix = load_a2_training_matrix(market)
    if len(FEATURES) > 20 or len({c.family for c in CANDIDATES}) > 3 or len(CANDIDATES) > 9:
        raise RuntimeError("preregistered complexity cap violated")
    oof, comparison, fold_metrics, fit_count = run_oof(matrix)
    selected, classification = select_candidate(comparison)
    reporting = selected if selected is not None else diagnostic_reference(comparison)

    feature_manifest = {
        "feature_count": len(FEATURES),
        "features": FEATURES,
        "feature_schema_sha256": canonical_hash(FEATURES),
        "risk_decision_timestamp": RISK_DECISION_TIMESTAMP,
        "feature_information_cutoff": FEATURE_INFORMATION_CUTOFF,
        "alignment": "feature market_date strictly precedes signal_date; target is next A2 trading-day net return",
        "sources": {
            "QQQ_SPY": "Moomoo canonical QFQ yearly parquet through 2025; promoted canonical Moomoo QFQ snapshot only after freeze",
            "VIX": str(VIX_PATH),
            "SPX_PROXY": "SPY used because no trusted local SPX cash-index series was required; name retains SPY explicitly",
        },
        "dropped_families": {
            "VIX_TERM_STRUCTURE": "no trustworthy local term-structure history",
            "HYG_LQD": "canonical Moomoo store has no HYG/LQD coverage",
            "TREASURY_RATE_SHOCK": "canonical Moomoo store has no trustworthy selected Treasury proxy coverage",
            "MOVE": "no trustworthy local PIT series",
            "BREADTH": "no compact trustworthy PIT breadth series selected",
        },
    }
    write_json(output / "risk_ml_r1_feature_manifest.json", feature_manifest)

    holdout: pd.DataFrame | None = None
    holdout_meta: dict[str, Any] = {}
    selected_oof: pd.DataFrame | None = None
    selected_manifest: dict[str, Any]
    final_fit_count = 0
    model_fit_count_after_freeze = 0
    holdout_metrics: dict[str, Any] = {}
    if selected is not None:
        model, final_threshold, score_cuts, final_fit_count = final_fit(matrix, selected)
        train_scores = model.predict_proba(matrix[FEATURES])[:, 1]
        model_path = output / "risk_ml_r1_selected_model.joblib"
        joblib.dump(
            {
                "model": model,
                "features": FEATURES,
                "final_tail_threshold": final_threshold,
                "training_score_quantiles_70_85_95": score_cuts,
                "mapping": selected["mapping"],
                "timing_contract": {"risk_decision_timestamp": RISK_DECISION_TIMESTAMP, "feature_information_cutoff": FEATURE_INFORMATION_CUTOFF},
            },
            model_path,
        )
        frozen_at = datetime.now(timezone.utc).isoformat()
        selected_manifest = {
            "status": "FROZEN_BEFORE_2026_OPEN",
            "frozen_at_utc": frozen_at,
            "selected_model": selected["candidate_id"],
            "model_family": selected["model_family"],
            "hyperparameters": next(c.params for c in CANDIDATES if c.candidate_id == selected["candidate_id"]),
            "feature_list": FEATURES,
            "feature_schema_sha256": canonical_hash(FEATURES),
            "training_cutoff_contract": "target_date < 2026-01-01",
            "training_end_date": matrix["target_date"].max(),
            "target_definition": "next trading-day frozen A2 net return <= training-only 10th percentile",
            "final_tail_threshold": final_threshold,
            "score_quantiles_70_85_95": score_cuts.tolist(),
            "exposure_mapping": {"0-70": 1.0, "70-85": 0.75, "85-95": 0.50, "95-100": 0.25},
            "hysteresis_choice": selected["mapping"],
            "model_artifact_path": model_path,
            "model_artifact_sha256": sha256_file(model_path),
            "model_fit_count_after_freeze": 0,
            "classification_at_freeze": classification,
        }
        write_json(output / "risk_ml_r1_selected_model_manifest.json", selected_manifest)
        # The freeze witness is durable before any 2026 feature/outcome artifact is opened.
        market_post, market_meta = load_postfreeze_market(pre_prices, pre_vix)
        holdout, holdout_meta = holdout_run(model, train_scores, selected["mapping"], market_post)
        holdout_meta.update(market_meta)
        write_csv(output / "risk_ml_r1_2026_holdout.csv", holdout)
        selected_oof = oof.loc[oof["candidate_id"].eq(selected["candidate_id"])].sort_values("target_date").copy()
        h_raw = performance_metrics(holdout["raw_a2_return"].iloc[1:])
        h_ctl = performance_metrics(holdout["controlled_a2_return"].iloc[1:])
        h_qqq = performance_metrics(holdout["qqq_return"].iloc[1:])
        rel_raw = relative_metrics(holdout["raw_a2_return"].iloc[1:].to_numpy(), holdout["qqq_return"].iloc[1:].to_numpy())
        rel_ctl = relative_metrics(holdout["controlled_a2_return"].iloc[1:].to_numpy(), holdout["qqq_return"].iloc[1:].to_numpy())
        holdout_metrics = {"raw_a2": h_raw, "controlled_a2": h_ctl, "qqq": h_qqq, "raw_relative": rel_raw, "controlled_relative": rel_ctl}
    else:
        selected_manifest = {
            "status": "NOT_FROZEN_2026_NOT_OPENED",
            "reason": "No candidate reached A or strong B under preregistered OOF rules",
            "classification": classification,
            "diagnostic_reference_model": reporting["candidate_id"],
            "diagnostic_reference_mapping": reporting["mapping"],
        }
        write_json(output / "risk_ml_r1_selected_model_manifest.json", selected_manifest)
        write_csv(output / "risk_ml_r1_2026_holdout.csv", pd.DataFrame(columns=["date", "status", "reason"]))
        selected_oof = oof.loc[oof["candidate_id"].eq(reporting["candidate_id"])].sort_values("target_date").copy()

    write_parquet(output / "risk_ml_r1_oof_predictions.parquet", oof)
    write_csv(output / "risk_ml_r1_model_comparison.csv", comparison)
    write_csv(output / "risk_ml_r1_fold_metrics.csv", fold_metrics)
    plot_results(output, selected_oof, reporting["mapping"], holdout)

    guard = guard_audit()
    lookahead_count = int((matrix["market_date"] >= matrix["signal_date"]).sum())
    training_2026_count = int(matrix["target_date"].ge(TRAINING_CUTOFF).sum())
    integrity_fail = any([lookahead_count, training_2026_count, guard["new_risk_r1_repo_violation_count"]])
    final_classification = "E" if integrity_fail else classification
    status = "INVALID_INTEGRITY_FAILURE" if integrity_fail else "VALID_ECONOMIC_RESULT_WITH_PREEXISTING_REPO_GOVERNANCE_FAILURE"
    selected_row = selected.to_dict() if selected is not None else {}
    reporting_row = reporting.to_dict()
    audit = {
        "status": status,
        "economic_classification": classification,
        "final_classification": final_classification,
        "baseline": baseline_audit,
        "anti_overfit": {
            "TRAINING_ROWS": len(matrix),
            "VALIDATION_ROWS": int(len(oof) / len(CANDIDATES)),
            "FEATURE_COUNT": len(FEATURES),
            "MODEL_FAMILY_COUNT": len({c.family for c in CANDIDATES}),
            "TOTAL_CANDIDATE_CONFIG_COUNT": len(CANDIDATES),
            "OOF_FOLD_COUNT": len(FOLDS),
            "TRAINING_DATA_2026_COUNT": training_2026_count,
            "2026_USED_FOR_FEATURE_SELECTION_COUNT": 0,
            "2026_USED_FOR_PARAMETER_SELECTION_COUNT": 0,
            "2026_USED_FOR_THRESHOLD_SELECTION_COUNT": 0,
            "RANDOM_CV_COUNT": 0,
            "OPTUNA_TRIAL_COUNT": 0,
            "LOOKAHEAD_VIOLATION_COUNT": lookahead_count,
            "OOF_MODEL_FIT_COUNT": fit_count,
            "FINAL_MODEL_FIT_COUNT": final_fit_count,
            "MODEL_FIT_COUNT_AFTER_FREEZE": model_fit_count_after_freeze,
            "PRE_FREEZE_TECHNICAL_RETRY_COMPLETED_FIT_COUNT": 21,
            "PRE_FREEZE_TECHNICAL_RETRY_FAILED_FIT_COUNT": 2,
            "PRE_FREEZE_TECHNICAL_RETRY_REASON": "managed Windows sandbox denied sklearn joblib worker-pipe creation; execution was constrained to one thread without changing any candidate configuration",
        },
        "timing": {"RISK_DECISION_TIMESTAMP": RISK_DECISION_TIMESTAMP, "FEATURE_INFORMATION_CUTOFF": FEATURE_INFORMATION_CUTOFF},
        "governance": guard,
        "holdout": holdout_meta,
        "exceptions": [],
    }
    write_json(output / "risk_ml_r1_audit.json", audit)

    summary = {
        "A2_RISK_ML_R1_STATUS": status,
        "A2_RISK_ML_R1_CLASSIFICATION": final_classification,
        "SELECTED_MODEL": selected_row.get("candidate_id", "NONE_NOT_FROZEN"),
        "FEATURE_COUNT": len(FEATURES),
        "TRAINING_END_DATE": matrix["target_date"].max().date().isoformat(),
        "OOF_FOLD_COUNT": len(FOLDS),
        "OOF_REFERENCE_MODEL": reporting_row.get("candidate_id"),
        "OOF_REFERENCE_MAPPING": reporting_row.get("mapping"),
        "OOF_AUROC": reporting_row.get("auroc"),
        "OOF_AVERAGE_PRECISION": reporting_row.get("average_precision"),
        "OOF_TOP_DECILE_TAIL_LIFT": reporting_row.get("top_decile_tail_lift"),
        "RAW_A2_OOF_RETURN": reporting_row.get("raw_total_return"),
        "CONTROLLED_A2_OOF_RETURN": reporting_row.get("controlled_total_return"),
        "RETURN_RETENTION": reporting_row.get("return_retention"),
        "RAW_A2_OOF_MDD": reporting_row.get("raw_maximum_drawdown"),
        "CONTROLLED_A2_OOF_MDD": reporting_row.get("controlled_maximum_drawdown"),
        "MDD_REDUCTION": reporting_row.get("mdd_reduction"),
        "RAW_A2_OOF_SHARPE": reporting_row.get("raw_sharpe"),
        "CONTROLLED_A2_OOF_SHARPE": reporting_row.get("controlled_sharpe"),
        "HOLDOUT_START_DATE": HOLDOUT_START.date().isoformat() if holdout is not None else None,
        "HOLDOUT_END_DATE": holdout["date"].max().date().isoformat() if holdout is not None else None,
        "RAW_A2_2026_RETURN": holdout_metrics.get("raw_a2", {}).get("total_return"),
        "CONTROLLED_A2_2026_RETURN": holdout_metrics.get("controlled_a2", {}).get("total_return"),
        "QQQ_2026_RETURN": holdout_metrics.get("qqq", {}).get("total_return"),
        "RAW_A2_2026_MDD": holdout_metrics.get("raw_a2", {}).get("maximum_drawdown"),
        "CONTROLLED_A2_2026_MDD": holdout_metrics.get("controlled_a2", {}).get("maximum_drawdown"),
        "QQQ_2026_MDD": holdout_metrics.get("qqq", {}).get("maximum_drawdown"),
        "RAW_A2_2026_DOWNSIDE_CAPTURE": holdout_metrics.get("raw_relative", {}).get("downside_capture_vs_qqq"),
        "CONTROLLED_A2_2026_DOWNSIDE_CAPTURE": holdout_metrics.get("controlled_relative", {}).get("downside_capture_vs_qqq"),
        "RAW_A2_2026_UPSIDE_CAPTURE": holdout_metrics.get("raw_relative", {}).get("upside_capture_vs_qqq"),
        "CONTROLLED_A2_2026_UPSIDE_CAPTURE": holdout_metrics.get("controlled_relative", {}).get("upside_capture_vs_qqq"),
        "TRAINING_DATA_2026_COUNT": training_2026_count,
        "OPTUNA_TRIAL_COUNT": 0,
        "LOOKAHEAD_VIOLATION_COUNT": lookahead_count,
        "NEW_RISK_R1_REPO_VIOLATION_COUNT": guard["new_risk_r1_repo_violation_count"],
        "NEXT_AUTHORIZED_STEP": "REVIEW_FROZEN_R1_EVIDENCE;DO_NOT_START_R2" if selected is not None else "STOP_NO_FREEZE;DO_NOT_START_R2",
        "selected_model_manifest": selected_manifest,
        "oof_selected": selected_row,
        "oof_diagnostic_reference": reporting_row,
        "holdout_metrics": holdout_metrics,
        "audit_path": output / "risk_ml_r1_audit.json",
        "results_root": output,
    }
    write_json(output / "risk_ml_r1_summary.json", summary)
    print_console(summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--repair-nonfreeze-reporting", action="store_true")
    args = parser.parse_args()
    try:
        if args.repair_nonfreeze_reporting:
            repair_existing_nonfreeze_reporting(args.output_dir.resolve())
        else:
            run(args.output_dir.resolve())
        return 0
    except Exception as exc:
        print(f"A2_RISK_ML_R1_STATUS=FAIL_CLOSED", file=sys.stderr)
        print(f"A2_RISK_ML_R1_CLASSIFICATION=E", file=sys.stderr)
        print(f"FAIL_CLOSED_REASON={type(exc).__name__}:{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
