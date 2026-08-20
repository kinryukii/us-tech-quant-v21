"""A2 Risk OS R2: pre-registered portfolio-level economic timing research.

R2 preserves frozen A2, frozen R6, and frozen R1.  It uses one portfolio-date
observation, a fixed forward-20-session BASE_R6 downside target, purged
walk-forward OOF predictions, and a single pre-registered de-risk mapping.
2026 outcomes are never read unless the frozen pre-2026 A/B gate passes.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import joblib
import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUTPUT = RESULTS / "A2_RISK_OS_R2"
R1_SCRIPT = REPO / "scripts" / "v22" / "a2_risk_os_r1.py"
R1_ROOT = RESULTS / "A2_RISK_OS_R1"
R1_RESTORE = R1_ROOT / "COVARIANCE_RESTORE_R1"
R1_CONTRACT = R1_ROOT / "risk_os_r1_contract.json"
R1_CONTRACT_SHA256 = "058dbbed6d5880da8f0bb0e0fbb921f669d62465ced64711cacd80eb939d997e"
R1_GEOMETRY = R1_RESTORE / "risk_os_r1_portfolio_geometry.parquet"
R1_WEIGHTS = R1_RESTORE / "risk_os_r1_weight_attribution.parquet"
POLICY = REPO / "docs" / "governance" / "ANTI_BLOAT_POLICY.md"
GUARD = REPO / "fast3" / "scripts" / "audit" / "run_fast3_guard.py"
CONTRACT_PATH = OUTPUT / "risk_os_r2_contract.json"
FEATURE_MANIFEST_PATH = OUTPUT / "risk_os_r2_feature_manifest.json"
TRAINING_CUTOFF = pd.Timestamp("2026-01-01")
TARGET_HORIZON = 20
PURGE_SESSIONS = 20
BASE_COST = 0.001
MISSINGNESS_LIMIT = 0.20
PLACEBO_COUNT = 300
RNG_SEED = 20260819

PRIMARY_MAPPING = [(0.60, 1.00), (0.80, 0.90), (0.95, 0.75), (1.01, 0.60)]
SENSITIVITY_MAPPING = [(0.60, 1.00), (0.80, 0.95), (0.95, 0.85), (1.01, 0.70)]


def _import(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_FAILURE:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


R1 = _import("a2_risk_os_r2_r1", R1_SCRIPT)


def sha256_file(path: Path) -> str:
    return R1.sha256_file(path)


def canonical_hash(value: Any) -> str:
    return R1.canonical_hash(value)


def write_json(path: Path, value: Any) -> None:
    R1.write_json(path, value)


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    R1.write_csv(path, frame)


def write_parquet(path: Path, frame: pd.DataFrame) -> None:
    R1.write_parquet(path, frame)


def finite_corr(x: pd.Series, y: pd.Series, method: str = "spearman") -> float:
    mask = np.isfinite(x.to_numpy(float)) & np.isfinite(y.to_numpy(float))
    if mask.sum() < 3 or x.loc[mask].nunique() < 2 or y.loc[mask].nunique() < 2:
        return np.nan
    return float(spearmanr(x.loc[mask], y.loc[mask]).statistic if method == "spearman" else pearsonr(x.loc[mask], y.loc[mask]).statistic)


def series_fingerprint(series: pd.Series) -> str:
    digest = hashlib.sha256()
    digest.update(pd.util.hash_pandas_object(series, index=True).to_numpy(np.uint64).tobytes())
    return digest.hexdigest()


def frozen_identity() -> dict[str, Any]:
    if not POLICY.is_file() or not R1_CONTRACT.is_file() or sha256_file(R1_CONTRACT) != R1_CONTRACT_SHA256:
        raise RuntimeError("FROZEN_R1_IDENTITY_FAILURE")
    identity = R1.frozen_identity()
    required = [R1_GEOMETRY, R1_WEIGHTS, R1.COVARIANCE_PANEL, R1.COVARIANCE_MANIFEST]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("MISSING_REPAIRED_R1_INPUT:" + ",".join(missing))
    covariance_manifest = json.loads(R1.COVARIANCE_MANIFEST.read_text(encoding="utf-8"))
    if covariance_manifest["panel_sha256"] != sha256_file(R1.COVARIANCE_PANEL):
        raise RuntimeError("COVARIANCE_PANEL_IDENTITY_FAILURE")
    return {
        **identity,
        "r1_contract_sha256": R1_CONTRACT_SHA256,
        "r1_geometry_sha256": sha256_file(R1_GEOMETRY),
        "r1_weights_sha256": sha256_file(R1_WEIGHTS),
        "covariance_panel_sha256": covariance_manifest["panel_sha256"],
    }


def base_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    weights = pd.read_parquet(R1_WEIGHTS)
    weights["signal_date"] = pd.to_datetime(weights.signal_date)
    weights["information_date"] = pd.to_datetime(weights.information_date)
    r6_state = pd.read_parquet(
        R1.R6_OOF,
        columns=["candidate_id", "signal_date", "ticker", "universe_size", "RET_5D"],
    )
    r6_state = r6_state.loc[r6_state.candidate_id.eq(R1.R6_REFERENCE_MODEL)].drop(columns="candidate_id")
    r6_state["signal_date"] = pd.to_datetime(r6_state.signal_date)
    weights = weights.merge(r6_state, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    if weights.signal_date.ge(TRAINING_CUTOFF).any() or weights.groupby("signal_date").size().ne(20).any():
        raise RuntimeError("BASE_R6_WEIGHT_CONTRACT_FAILURE")
    expected = weights.base_a2_weight * np.where(weights.risk_percentile.ge(.90), .50, 1.0)
    if not np.allclose(expected, weights.r6_adjusted_weight, atol=0, rtol=0):
        raise RuntimeError("FROZEN_R6_MAPPING_IDENTITY_FAILURE")
    positions = pd.read_parquet(R1.R3.POSITION_LEDGER_PATH, columns=["date", "ticker", "raw_return"])
    positions["date"] = pd.to_datetime(positions.date)
    base_daily = R1.simulate(R1.target_maps(weights, "r6_adjusted_weight"), positions, BASE_COST)
    base_daily["date"] = pd.to_datetime(base_daily.date)
    if base_daily.date.ge(TRAINING_CUTOFF).any():
        raise RuntimeError("2026_BASE_RETURN_READ_FAILURE")
    return weights, positions, base_daily


def forward_targets(decision_dates: pd.Series, base_daily: pd.DataFrame) -> pd.DataFrame:
    returns = base_daily.set_index("date").daily_return.sort_index()
    dates = returns.index
    rows: list[dict[str, Any]] = []
    for date in pd.to_datetime(decision_dates).sort_values().unique():
        future = returns.loc[returns.index > date]
        if len(future) < TARGET_HORIZON:
            continue
        path20 = future.iloc[:20]
        cumulative = (1 + path20).cumprod() - 1
        equity = pd.concat([pd.Series([1.0]), (1 + path20).cumprod().reset_index(drop=True)], ignore_index=True)
        maxdd = float((equity / equity.cummax() - 1).min())
        worst5 = min(float((1 + path20.iloc[i:i + 5]).prod() - 1) for i in range(16))
        path10 = future.iloc[:10]
        cumulative10 = (1 + path10).cumprod() - 1
        row = {
            "signal_date": pd.Timestamp(date),
            "target_end_date": pd.Timestamp(path20.index[-1]),
            "forward_20d_worst_cum_return": float(cumulative.min()),
            "Y_RISK_20": float(-cumulative.min()),
            "forward_20d_cumulative_return": float(cumulative.iloc[-1]),
            "forward_20d_max_drawdown": maxdd,
            "worst_5d_inside_20d": worst5,
            "forward_10d_worst_cum_return": float(cumulative10.min()),
            "forward_40d_worst_cum_return": np.nan,
        }
        if len(future) >= 40:
            cumulative40 = (1 + future.iloc[:40]).cumprod() - 1
            row["forward_40d_worst_cum_return"] = float(cumulative40.min())
        rows.append(row)
    targets = pd.DataFrame(rows)
    if targets.empty or targets.target_end_date.ge(TRAINING_CUTOFF).any():
        raise RuntimeError("TARGET_MATURITY_OR_CUTOFF_FAILURE")
    return targets


def trailing_base_features(dates: pd.DataFrame, base_daily: pd.DataFrame) -> pd.DataFrame:
    daily = base_daily.set_index("date").daily_return.sort_index()
    equity = (1 + daily).cumprod()
    rows = []
    for row in dates.itertuples(index=False):
        hist = daily.loc[daily.index <= row.information_date]
        eq = equity.loc[equity.index <= row.information_date]
        item: dict[str, Any] = {"signal_date": row.signal_date}
        for horizon in [1, 5, 20]:
            item[f"BASE_R6_RETURN_{horizon}D"] = float((1 + hist.iloc[-horizon:]).prod() - 1) if len(hist) >= horizon else np.nan
        item["BASE_R6_DRAWDOWN"] = float(eq.iloc[-1] / eq.cummax().iloc[-1] - 1) if len(eq) else np.nan
        item["BASE_R6_REALIZED_VOL_20D"] = float(hist.iloc[-20:].std(ddof=1) * np.sqrt(252)) if len(hist) >= 20 else np.nan
        item["BASE_R6_POSITIVE_DAY_FRACTION_20D"] = float(hist.iloc[-20:].gt(0).mean()) if len(hist) >= 20 else np.nan
        rows.append(item)
    return pd.DataFrame(rows)


def market_features() -> tuple[pd.DataFrame, dict[str, str]]:
    prices, available = R1.load_market_prices(True)
    pivot = prices.pivot(index="trade_date", columns="ticker", values="close").sort_index()
    out = pd.DataFrame(index=pivot.index)
    transformations: dict[str, str] = {}
    for ticker in available:
        close = pivot[ticker].astype(float)
        ret = close.pct_change(fill_method=None)
        for horizon in [1, 5, 20]:
            name = f"{ticker}_RETURN_{horizon}D"
            out[name] = close.pct_change(horizon, fill_method=None)
            transformations[name] = f"close.pct_change({horizon})"
        for horizon in [20, 60]:
            name = f"{ticker}_DISTANCE_MA_{horizon}D"
            out[name] = close / close.rolling(horizon, min_periods=horizon).mean() - 1
            transformations[name] = f"close/rolling_mean({horizon})-1"
        for horizon in [5, 20, 60]:
            name = f"{ticker}_REALIZED_VOL_{horizon}D"
            out[name] = ret.rolling(horizon, min_periods=horizon).std(ddof=1) * np.sqrt(252)
            transformations[name] = f"annualized_std(return,{horizon})"
        out[f"{ticker}_VOL_RATIO_5_20"] = out[f"{ticker}_REALIZED_VOL_5D"] / out[f"{ticker}_REALIZED_VOL_20D"].replace(0, np.nan)
        out[f"{ticker}_VOL_ACCELERATION"] = out[f"{ticker}_REALIZED_VOL_5D"] - out[f"{ticker}_REALIZED_VOL_20D"]
        transformations[f"{ticker}_VOL_RATIO_5_20"] = "realized_vol_5d/realized_vol_20d"
        transformations[f"{ticker}_VOL_ACCELERATION"] = "realized_vol_5d-realized_vol_20d"
    vix = pd.read_parquet(R1.VIX_PATH, columns=["DATE", "CLOSE"]).rename(columns={"DATE": "trade_date", "CLOSE": "VIX_LEVEL"})
    vix["trade_date"] = pd.to_datetime(vix.trade_date)
    vix = vix.loc[vix.trade_date.lt(TRAINING_CUTOFF)].sort_values("trade_date")
    vix["VIX_CHANGE_1D"] = vix.VIX_LEVEL.pct_change(fill_method=None)
    vix["VIX_CHANGE_5D"] = vix.VIX_LEVEL.pct_change(5, fill_method=None)
    vix["VIX_PERCENTILE_20D"] = vix.VIX_LEVEL.rolling(20, min_periods=20).apply(lambda x: (np.sum(x[:-1] < x[-1]) + .5 * np.sum(x[:-1] == x[-1])) / (len(x) - 1), raw=True)
    vix["VIX_PERCENTILE_60D"] = vix.VIX_LEVEL.rolling(60, min_periods=60).apply(lambda x: (np.sum(x[:-1] < x[-1]) + .5 * np.sum(x[:-1] == x[-1])) / (len(x) - 1), raw=True)
    for column in ["VIX_LEVEL", "VIX_CHANGE_1D", "VIX_CHANGE_5D", "VIX_PERCENTILE_20D", "VIX_PERCENTILE_60D"]:
        transformations[column] = "authoritative VIX backward-looking transform"
    out = out.reset_index().merge(vix, on="trade_date", how="left", validate="one_to_one")
    return out, transformations


def weighted_geometry(weights: pd.DataFrame) -> pd.DataFrame:
    panel = pd.read_parquet(R1.COVARIANCE_PANEL, columns=["trade_date", "canonical_ticker", "return"])
    panel["trade_date"] = pd.to_datetime(panel.trade_date)
    pivot = panel.pivot(index="trade_date", columns="canonical_ticker", values="return").sort_index()
    market, _ = R1.market_state(True)
    market_returns = market.set_index("trade_date")[[c for c in ["SPY_return_1d", "QQQ_return_1d", "SOXX_return_1d"] if c in market]]
    calendar = pd.DatetimeIndex(market.trade_date.drop_duplicates().sort_values())
    rows = []
    for signal_date, group in weights.groupby("signal_date", sort=True):
        information_date = pd.Timestamp(group.information_date.iloc[0])
        legal = calendar[calendar <= information_date][-60:]
        tickers = group.ticker.astype(str).tolist()
        history = pivot.reindex(index=legal, columns=tickers).dropna(how="any")
        if len(history) < 40:
            continue
        cov = history.cov().to_numpy(float) * 252
        w = group.set_index("ticker").reindex(tickers).r6_adjusted_weight.to_numpy(float)
        item: dict[str, Any] = {
            "signal_date": signal_date,
            "BASE_R6_PORTFOLIO_REALIZED_VOL": float(np.sqrt(w @ cov @ w)),
        }
        for ticker in ["SPY", "QQQ", "SOXX"]:
            column = f"{ticker}_return_1d"
            aligned = market_returns[column].reindex(history.index)
            port = history.mul(w, axis=1).sum(axis=1)
            variance = float(aligned.var(ddof=1))
            item[f"BASE_R6_BETA_{ticker}"] = float(port.cov(aligned) / variance) if variance > 0 else np.nan
        rows.append(item)
    return pd.DataFrame(rows)


def feature_table(weights: pd.DataFrame, base_daily: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, list[str]]]:
    base_dates = weights[["signal_date", "information_date"]].drop_duplicates().sort_values("signal_date")
    geometry = pd.read_parquet(R1_GEOMETRY)
    geometry["signal_date"] = pd.to_datetime(geometry.signal_date)
    geometry["information_date"] = pd.to_datetime(geometry.information_date)
    geometry_columns = [
        "average_pairwise_correlation", "median_pairwise_correlation", "effective_independent_bets",
        "top_eigenvalue_concentration", "max_correlation_cluster_share",
    ]
    geom = geometry[["signal_date", "information_date"] + geometry_columns].copy()
    for column in geometry_columns:
        geom[f"{column}_CHANGE_5"] = geom[column].diff(5)
        geom[f"{column}_CHANGE_20"] = geom[column].diff(20)
    geom["CORRELATION_ACCELERATION"] = geom["average_pairwise_correlation_CHANGE_5"] - geom["average_pairwise_correlation_CHANGE_20"] / 4
    weighted = weighted_geometry(weights)
    geom = geom.merge(weighted, on="signal_date", how="left", validate="one_to_one")
    geom["BASE_R6_PORTFOLIO_VOL_CHANGE_5"] = geom.BASE_R6_PORTFOLIO_REALIZED_VOL.diff(5)
    market, market_transforms = market_features()
    frame = base_dates.merge(geom, on=["signal_date", "information_date"], how="left", validate="one_to_one")
    frame = frame.merge(market, left_on="information_date", right_on="trade_date", how="left", validate="one_to_one").drop(columns="trade_date")
    frame["CORRELATION_X_MARKET_STRESS"] = frame.average_pairwise_correlation * frame.VIX_PERCENTILE_60D

    aggregate_rows = []
    previous_names: set[str] | None = None
    for date, group in weights.groupby("signal_date", sort=True):
        group = group.sort_values("A2_RANK")
        scores = group.A2_PREDICTION.astype(float)
        risks = group.predicted_bad_asymmetry_risk.astype(float)
        base_weight = group.base_a2_weight.astype(float)
        normalized_risk = base_weight * risks.clip(lower=0)
        names = set(group.ticker.astype(str))
        aggregate_rows.append({
            "signal_date": date,
            "A2_SCORE_MEAN": scores.mean(), "A2_SCORE_MEDIAN": scores.median(), "A2_SCORE_STD": scores.std(ddof=1),
            "A2_TOP1_MINUS_TOP20": scores.iloc[0] - scores.iloc[-1],
            "A2_TOP5_MINUS_BOTTOM5": scores.iloc[:5].mean() - scores.iloc[-5:].mean(),
            "A2_UNIVERSE_SIZE": group.universe_size.iloc[0] if "universe_size" in group else np.nan,
            "A2_CANDIDATE_TURNOVER": np.nan if previous_names is None else 1 - len(names & previous_names) / 20,
            "A2_SELECTED_RET5_DISPERSION": group.RET_5D.std(ddof=1),
            "R6_WEIGHTED_MEAN": np.average(risks, weights=base_weight), "R6_MEDIAN": risks.median(), "R6_MAX": risks.max(),
            "R6_WEIGHTED_STD": np.sqrt(np.average((risks - np.average(risks, weights=base_weight)) ** 2, weights=base_weight)),
            "R6_HIGH_DECILE_WEIGHT_SHARE": base_weight.loc[group.risk_percentile.ge(.90)].sum() / base_weight.sum(),
            "R6_HIGH_DECILE_NAME_SHARE": group.risk_percentile.ge(.90).mean(),
            "R6_TOP_QUARTILE_WEIGHT_SHARE": base_weight.loc[group.risk_percentile.ge(.75)].sum() / base_weight.sum(),
            "R6_SCORE_DISPERSION": risks.std(ddof=1),
            "R6_WEIGHTED_RISK_CONCENTRATION": float(((normalized_risk / normalized_risk.sum()) ** 2).sum()) if normalized_risk.sum() > 0 else np.nan,
        })
        previous_names = names
    aggregate = pd.DataFrame(aggregate_rows)
    aggregate["R6_WEIGHTED_MEAN_CHANGE"] = aggregate.R6_WEIGHTED_MEAN.diff()
    aggregate["R6_HIGH_RISK_SHARE_CHANGE"] = aggregate.R6_HIGH_DECILE_WEIGHT_SHARE.diff()
    frame = frame.merge(aggregate, on="signal_date", validate="one_to_one")
    frame = frame.merge(trailing_base_features(base_dates, base_daily), on="signal_date", validate="one_to_one")

    identifiers = {"signal_date", "information_date"}
    market_cols = [c for c in market.columns if c != "trade_date"]
    geometry_cols = [c for c in frame if c in geometry_columns or "CHANGE" in c and any(g in c for g in geometry_columns) or c in ["CORRELATION_ACCELERATION", "CORRELATION_X_MARKET_STRESS", "BASE_R6_PORTFOLIO_REALIZED_VOL", "BASE_R6_PORTFOLIO_VOL_CHANGE_5", "BASE_R6_BETA_SPY", "BASE_R6_BETA_QQQ", "BASE_R6_BETA_SOXX"]]
    a2_cols = [c for c in frame if c.startswith("A2_") or c.startswith("BASE_R6_RETURN_") or c in ["BASE_R6_DRAWDOWN", "BASE_R6_REALIZED_VOL_20D", "BASE_R6_POSITIVE_DAY_FRACTION_20D"]]
    r6_cols = [c for c in frame if c.startswith("R6_")]
    families = {"MARKET": market_cols, "GEOMETRY": geometry_cols, "A2_STATE": a2_cols, "R6_AGGREGATE": r6_cols}
    all_features = [c for columns in families.values() for c in columns]
    all_features = list(dict.fromkeys(all_features))
    manifest: list[dict[str, Any]] = []
    removed: set[str] = set()
    seen_hashes: dict[str, str] = {}
    for family, columns in families.items():
        kept = []
        for column in columns:
            missing = float(frame[column].isna().mean())
            nonfinite = int((~np.isfinite(pd.to_numeric(frame[column], errors="coerce"))).sum())
            fingerprint = series_fingerprint(frame[column])
            reason = None
            if missing > MISSINGNESS_LIMIT:
                reason = "EXCESSIVE_STRUCTURAL_MISSINGNESS"
            elif frame[column].dropna().nunique() <= 1:
                reason = "CONSTANT_VALUE"
            elif fingerprint in seen_hashes:
                reason = f"DUPLICATE_IDENTITY_OF:{seen_hashes[fingerprint]}"
            if reason:
                removed.add(column)
            else:
                kept.append(column); seen_hashes[fingerprint] = column
            source = str(R1.PRICE_ROOT if family == "MARKET" and not column.startswith("VIX") else R1.VIX_PATH if column.startswith("VIX") else R1_GEOMETRY if family == "GEOMETRY" else R1_WEIGHTS)
            manifest.append({
                "feature_name": column, "family": family, "source_path": source,
                "timestamp_contract": "completed information_date close strictly before signal_date execution",
                "transformation": market_transforms.get(column, "fixed backward-looking portfolio-date aggregation"),
                "minimum_history": 60 if "60" in column or family == "GEOMETRY" else 20 if "20" in column else 1,
                "missing_count": int(frame[column].isna().sum()), "missingness_rate": missing,
                "nonfinite_count": nonfinite, "pit_proof": "PASS_BACKWARD_LOOKING_ASOF_INFORMATION_DATE",
                "fingerprint": fingerprint, "included": reason is None, "removal_reason": reason,
            })
        families[family] = kept
    selected = [c for columns in families.values() for c in columns]
    if frame[selected].shape[1] == 0 or frame.signal_date.duplicated().any() or frame.information_date.ge(frame.signal_date).any():
        raise RuntimeError("FEATURE_CONTRACT_FAILURE")
    return frame[list(identifiers) + selected].sort_values("signal_date"), manifest, families


def contract_payload(identity: dict[str, Any], families: dict[str, list[str]], sources: dict[str, str]) -> dict[str, Any]:
    return {
        "experiment_id": "A2_RISK_OS_R2", "role": "PORTFOLIO_LEVEL_SYSTEMIC_DERISK_TIMING",
        "base_strategy": "FROZEN_A2_PLUS_FROZEN_R6", "training_cutoff_exclusive": "2026-01-01",
        "identity": identity, "source_fingerprints": sources,
        "sample_unit": "ONE_PORTFOLIO_DECISION_DATE",
        "primary_target": {"name": "Y_RISK_20", "formula": "-min(cumulative BASE_R6 net return horizons 1..20)", "horizon_sessions": 20, "cost_rate": BASE_COST},
        "secondary_targets": ["forward_20d_cumulative_return", "forward_20d_max_drawdown", "worst_5d_inside_20d", "forward_10d_worst_cum_return", "forward_40d_worst_cum_return"],
        "feature_families": families, "missingness_exclusion_threshold": MISSINGNESS_LIMIT,
        "fold_rule": "R6 frozen temporal boundaries FOLD_2..FOLD_5; expanding train strictly earlier; training target_end < validation_start",
        "purge_sessions": PURGE_SESSIONS, "embargo_rule": "no later observations enter expanding training; overlapping labels purged by target_end",
        "models": {
            "RIDGE_FIXED": {"alpha": 10.0, "imputer": "train median", "scaler": "train standard"},
            "HGB_FIXED": {"learning_rate": .05, "max_iter": 160, "max_leaf_nodes": 7, "min_samples_leaf": 20, "l2_regularization": 2.0},
            "LGBM_FIXED": {"n_estimators": 160, "learning_rate": .03, "num_leaves": 7, "max_depth": 3, "min_child_samples": 20, "reg_lambda": 2.0, "subsample": .8, "colsample_bytree": .8},
            "CATBOOST_FIXED": {"iterations": 160, "learning_rate": .03, "depth": 3, "l2_leaf_reg": 5.0, "loss_function": "RMSE"},
        },
        "model_selection": "highest pooled OOF Spearman subject to all 4 folds positive and no fold Spearman<-0.10; prefer lower complexity within 0.02; otherwise best is diagnostic only",
        "primary_exposure_mapping": PRIMARY_MAPPING, "sensitivity_mapping": SENSITIVITY_MAPPING,
        "mapping_authority": "de-risk only; multiplier<=1; no mapping search",
        "matched_control": "fold-local constant multiplier with exact same mean gross exposure",
        "placebo": {"count": PLACEBO_COUNT, "method": "deterministic circular timing shifts preserving exposure serial structure", "seed": RNG_SEED},
        "costs": {"BASELINE": .001, "TWO_X": .002, "ADVERSE": .003},
        "economic_useful_fold": "dynamic Sharpe>=matched-0.03 AND at least two of cumulative return,MaxDD,Calmar,ES5 improve",
        "gates": {
            "A_PRE2026_STRONG_TIMING_VALUE": {"predictive_spearman_gt": 0, "positive_predictive_folds": 4, "sharpe_delta": .05, "calmar_delta": .10, "mdd_not_worse": True, "es5_not_worse": True, "cagr_delta_min": -.02, "positive_economic_folds": 4, "placebo_above_median": True},
            "B_PRE2026_USEFUL_TIMING_VALUE": {"predictive_spearman_gt": 0, "positive_predictive_folds_min": 3, "sharpe_delta_min": 0, "two_of_mdd_calmar_es_improve": True, "cagr_delta_min": -.03, "positive_economic_folds_min": 3, "placebo_above_median": True},
            "C": "predictive Spearman>0, >=3 positive folds and top-bottom severity spread>0, but economics fail",
            "D": "predictive/economic evidence insufficient", "E": "integrity/PIT/evidence failure",
        },
        "prospective_authorization": "only pre2026 A/B after deployment freeze; otherwise outcome reads zero",
        "output_root": str(OUTPUT), "parameter_search_count": 0, "threshold_search_count": 0,
    }


def freeze_contract(payload: dict[str, Any]) -> str:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(R1.safe(payload), indent=2, sort_keys=True, allow_nan=False).encode("utf-8")
    if CONTRACT_PATH.exists() and CONTRACT_PATH.read_bytes() != encoded:
        raise RuntimeError("FROZEN_R2_CONTRACT_MISMATCH")
    if not CONTRACT_PATH.exists():
        temp = CONTRACT_PATH.with_name(f".{CONTRACT_PATH.name}.{uuid.uuid4().hex}.tmp")
        temp.write_bytes(encoded); os.replace(temp, CONTRACT_PATH)
    return sha256_file(CONTRACT_PATH)


def folds(panel: pd.DataFrame) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    assignments = []
    for name, start, end in R1.R3.FOLDS[1:]:
        start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
        train = panel.loc[(panel.signal_date < start_ts) & (panel.target_end_date < start_ts)]
        valid = panel.loc[panel.signal_date.between(start_ts, end_ts)]
        if len(train) < 30 or len(valid) < 20:
            raise RuntimeError(f"INSUFFICIENT_PURGED_FOLD:{name}:{len(train)}:{len(valid)}")
        leakage = int((train.target_end_date >= valid.signal_date.min()).sum())
        rows.append({
            "fold": name, "train_start": train.signal_date.min(), "train_end": train.signal_date.max(),
            "train_target_end_max": train.target_end_date.max(), "validation_start": valid.signal_date.min(),
            "validation_end": valid.signal_date.max(), "train_rows": len(train), "validation_rows": len(valid),
            "purge_sessions": PURGE_SESSIONS, "overlap_leakage_count": leakage,
        })
        for date in valid.signal_date:
            assignments.append({"signal_date": date, "fold": name})
    manifest = pd.DataFrame(rows)
    if len(manifest) != 4 or manifest.overlap_leakage_count.sum() != 0:
        raise RuntimeError("FOLD_CONTRACT_FAILURE")
    return rows, pd.DataFrame(assignments)


@dataclass(frozen=True)
class Candidate:
    name: str
    complexity: int
    factory: Callable[[], Any]


def candidates() -> list[Candidate]:
    from lightgbm import LGBMRegressor
    from catboost import CatBoostRegressor
    return [
        Candidate("RIDGE_FIXED", 0, lambda: Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()), ("model", Ridge(alpha=10.0))])),
        Candidate("HGB_FIXED", 1, lambda: Pipeline([("impute", SimpleImputer(strategy="median")), ("model", HistGradientBoostingRegressor(learning_rate=.05, max_iter=160, max_leaf_nodes=7, min_samples_leaf=20, l2_regularization=2.0, random_state=RNG_SEED))])),
        Candidate("LGBM_FIXED", 2, lambda: Pipeline([("impute", SimpleImputer(strategy="median")), ("model", LGBMRegressor(n_estimators=160, learning_rate=.03, num_leaves=7, max_depth=3, min_child_samples=20, reg_lambda=2.0, subsample=.8, colsample_bytree=.8, random_state=RNG_SEED, deterministic=True, force_col_wise=True, verbosity=-1, n_jobs=1))])),
        Candidate("CATBOOST_FIXED", 3, lambda: Pipeline([("impute", SimpleImputer(strategy="median")), ("model", CatBoostRegressor(iterations=160, learning_rate=.03, depth=3, l2_leaf_reg=5.0, loss_function="RMSE", random_seed=RNG_SEED, verbose=False, thread_count=1, allow_writing_files=False))])),
    ]


def empirical_percentile(reference: np.ndarray, values: np.ndarray) -> np.ndarray:
    reference = np.sort(np.asarray(reference, float))
    return np.searchsorted(reference, np.asarray(values, float), side="right") / len(reference)


def predictive_metrics(frame: pd.DataFrame, score: str = "prediction") -> dict[str, Any]:
    y, pred = frame.Y_RISK_20.astype(float), frame[score].astype(float)
    q1 = frame.loc[frame.risk_percentile < .20, "Y_RISK_20"].mean()
    q5 = frame.loc[frame.risk_percentile >= .80, "Y_RISK_20"].mean()
    bins = pd.cut(frame.risk_percentile, [-1e-9, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.000001], labels=False)
    deciles = frame.assign(decile=bins).groupby("decile", observed=True).Y_RISK_20.mean()
    return {
        "spearman": finite_corr(pred, y), "pearson": finite_corr(pred, y, "pearson"),
        "mae": float(mean_absolute_error(y, pred)), "rmse": float(np.sqrt(mean_squared_error(y, pred))),
        "bottom_quintile_severity": float(q1), "top_quintile_severity": float(q5),
        "q5_minus_q1_severity": float(q5 - q1),
        "risk_decile_monotonicity": finite_corr(pd.Series(deciles.index, dtype=float), deciles.reset_index(drop=True)),
    }


def run_candidate(panel: pd.DataFrame, features: list[str], candidate: Candidate, fold_rows: list[dict[str, Any]]) -> tuple[pd.DataFrame, list[Any]]:
    pieces, fitted = [], []
    for fold in fold_rows:
        start = pd.Timestamp(fold["validation_start"]); end = pd.Timestamp(fold["validation_end"])
        train = panel.loc[(panel.signal_date < start) & (panel.target_end_date < start)].copy()
        valid = panel.loc[panel.signal_date.between(start, end)].copy()
        model = candidate.factory()
        # Managed Windows sandboxes can reject worker-pipe creation even for
        # thread backends.  One native thread is deterministic and preserves
        # the frozen estimator parameters; it is an execution constraint, not
        # a model/hyperparameter change.
        with threadpool_limits(limits=1):
            model.fit(train[features], train.Y_RISK_20)
            train_prediction = model.predict(train[features])
            valid["prediction"] = model.predict(valid[features])
        valid["risk_percentile"] = empirical_percentile(train_prediction, valid.prediction.to_numpy())
        valid["fold"] = fold["fold"]
        pieces.append(valid); fitted.append((model, train, valid))
    return pd.concat(pieces, ignore_index=True).sort_values("signal_date"), fitted


def model_comparison(panel: pd.DataFrame, features: list[str], fold_rows: list[dict[str, Any]]) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict[str, list[Any]]]:
    rows, predictions, fits = [], {}, {}
    for candidate in candidates():
        oof, fitted = run_candidate(panel, features, candidate, fold_rows)
        predictions[candidate.name] = oof; fits[candidate.name] = fitted
        metric = predictive_metrics(oof)
        fold_spearman = [finite_corr(part.prediction, part.Y_RISK_20) for _, part in oof.groupby("fold")]
        rows.append({"model": candidate.name, "complexity": candidate.complexity, **metric, "positive_predictive_folds": int(sum(value > 0 for value in fold_spearman)), "minimum_fold_spearman": float(np.nanmin(fold_spearman)), "fold_spearman_json": json.dumps(fold_spearman)})
    return pd.DataFrame(rows), predictions, fits


def select_model(comparison: pd.DataFrame) -> tuple[str, bool]:
    eligible = comparison.loc[(comparison.positive_predictive_folds.eq(4)) & (comparison.minimum_fold_spearman.ge(-.10))].copy()
    diagnostic_only = eligible.empty
    pool = comparison if eligible.empty else eligible
    best = pool.sort_values("spearman", ascending=False).iloc[0]
    simpler = pool.loc[(pool.complexity < best.complexity) & (pool.spearman >= best.spearman - .02)]
    if len(simpler):
        best = simpler.sort_values(["complexity", "spearman"], ascending=[True, False]).iloc[0]
    return str(best.model), diagnostic_only


def ablations(panel: pd.DataFrame, families: dict[str, list[str]], fold_rows: list[dict[str, Any]]) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    groups = {
        "A_MARKET_ONLY": families["MARKET"],
        "B_MARKET_GEOMETRY": families["MARKET"] + families["GEOMETRY"],
        "C_MARKET_GEOMETRY_A2": families["MARKET"] + families["GEOMETRY"] + families["A2_STATE"],
        "D_FULL_WITH_R6": sum(families.values(), []),
        "E_R6_ONLY": families["R6_AGGREGATE"],
    }
    candidate = next(c for c in candidates() if c.name == "HGB_FIXED")
    rows = []
    predictions: dict[str, pd.DataFrame] = {}
    for name, columns in groups.items():
        oof, _ = run_candidate(panel, columns, candidate, fold_rows)
        predictions[name] = oof
        fold_values = [finite_corr(part.prediction, part.Y_RISK_20) for _, part in oof.groupby("fold")]
        rows.append({"ablation": name, "feature_count": len(columns), **predictive_metrics(oof), "positive_predictive_folds": int(sum(v > 0 for v in fold_values))})
    return pd.DataFrame(rows), predictions


def fixed_score_diagnostics(panel: pd.DataFrame, fold_rows: list[dict[str, Any]]) -> pd.DataFrame:
    scores = {
        "VIX_ONLY": "VIX_LEVEL", "REALIZED_VOL_ONLY": "SPY_REALIZED_VOL_20D",
        "CORRELATION_LEVEL": "average_pairwise_correlation",
        "CORRELATION_CHANGE": "average_pairwise_correlation_CHANGE_5",
        "CORRELATION_ACCELERATION": "CORRELATION_ACCELERATION",
        "CORRELATION_X_MARKET_STRESS": "CORRELATION_X_MARKET_STRESS",
    }
    rows = []
    for name, column in scores.items():
        pieces = []
        for fold in fold_rows:
            start, end = pd.Timestamp(fold["validation_start"]), pd.Timestamp(fold["validation_end"])
            train = panel.loc[(panel.signal_date < start) & (panel.target_end_date < start)]
            valid = panel.loc[panel.signal_date.between(start, end)].copy()
            train_values = train[column].fillna(train[column].median()).to_numpy(float)
            valid["prediction"] = valid[column].fillna(train[column].median())
            valid["risk_percentile"] = empirical_percentile(train_values, valid.prediction.to_numpy())
            valid["fold"] = fold["fold"]; pieces.append(valid)
        oof = pd.concat(pieces, ignore_index=True)
        fold_values = [finite_corr(part.prediction, part.Y_RISK_20) for _, part in oof.groupby("fold")]
        rows.append({"benchmark": name, "feature": column, **predictive_metrics(oof), "positive_predictive_folds": int(sum(v > 0 for v in fold_values)), "fold_spearman_json": json.dumps(fold_values)})
    return pd.DataFrame(rows)


def mapping(percentile: pd.Series, rules: list[tuple[float, float]]) -> np.ndarray:
    values = np.ones(len(percentile))
    lower = 0.0
    for upper, multiplier in rules:
        mask = percentile.ge(lower) & percentile.lt(upper)
        values[mask] = multiplier
        lower = upper
    return values


def strategy_metrics(sim: pd.DataFrame, cost_rate: float) -> dict[str, Any]:
    metric = R1.metrics(sim.daily_return, sim)
    downside = metric["downside_deviation"]
    metric["sortino"] = float(sim.daily_return.mean() * 252 / downside) if downside > 0 else np.nan
    metric["transaction_cost_proxy"] = float(sim.turnover.sum() * cost_rate)
    metric["derisk_state_changes"] = int(sim.target_exposure.diff().abs().gt(1e-12).sum())
    metric["exposure_p05"] = float(sim.target_exposure.quantile(.05)); metric["exposure_p95"] = float(sim.target_exposure.quantile(.95))
    return metric


def economic_evaluation(oof: pd.DataFrame, weights: pd.DataFrame, positions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    dates = oof[["signal_date", "fold", "risk_percentile"]].drop_duplicates().sort_values("signal_date")
    dates["primary_multiplier"] = mapping(dates.risk_percentile, PRIMARY_MAPPING)
    dates["sensitivity_multiplier"] = mapping(dates.risk_percentile, SENSITIVITY_MAPPING)
    selected = weights.loc[weights.signal_date.isin(dates.signal_date)].merge(dates, on="signal_date", validate="many_to_one")
    selected["raw_weight"] = selected.base_a2_weight
    selected["base_r6_weight"] = selected.r6_adjusted_weight
    selected["dynamic_weight"] = selected.base_r6_weight * selected.primary_multiplier
    selected["sensitivity_weight"] = selected.base_r6_weight * selected.sensitivity_multiplier
    exposures = selected.groupby(["signal_date", "fold"]).agg(base=("base_r6_weight", "sum"), dynamic=("dynamic_weight", "sum")).reset_index()
    evaluated_dates = set(sorted(exposures.signal_date)[1:])
    fold_constants = {}
    for fold, group in exposures.loc[exposures.signal_date.isin(evaluated_dates)].groupby("fold"):
        fold_constants[fold] = float(group.dynamic.mean() / group.base.mean())
    selected["matched_multiplier"] = selected.fold.map(fold_constants)
    selected["matched_multiplier"] = selected.matched_multiplier.fillna(next(iter(fold_constants.values())))
    selected["matched_weight"] = selected.base_r6_weight * selected.matched_multiplier
    columns = {"RAW_A2": "raw_weight", "BASE_R6": "base_r6_weight", "R2_DYNAMIC": "dynamic_weight", "MATCHED_CONSTANT": "matched_weight", "R2_SENSITIVITY": "sensitivity_weight"}
    simulations: dict[str, pd.DataFrame] = {}
    metric_rows = []
    for cost_name, cost in {"BASELINE": .001, "TWO_X": .002, "ADVERSE": .003}.items():
        for name, column in columns.items():
            sim = R1.simulate(R1.target_maps(selected, column), positions, cost)
            sim["fold"] = sim.date.map(dates.set_index("signal_date").fold)
            if cost_name == "BASELINE": simulations[name] = sim
            metric_rows.append({"cost_case": cost_name, "cost_rate": cost, "strategy": name, **strategy_metrics(sim, cost)})
    dynamic, matched = simulations["R2_DYNAMIC"], simulations["MATCHED_CONSTANT"]
    matched_error = float(abs(dynamic.target_exposure.mean() - matched.target_exposure.mean()))
    fold_rows = []
    useful = []
    for fold in dates.fold.unique():
        local = {}
        for name, sim in simulations.items():
            part = sim.loc[sim.fold.eq(fold)]
            if len(part) < 20:
                continue
            local[name] = strategy_metrics(part, BASE_COST)
            fold_rows.append({"fold": fold, "strategy": name, **local[name]})
        d, m = local["R2_DYNAMIC"], local["MATCHED_CONSTANT"]
        improvements = sum([d["total_return"] > m["total_return"], d["maximum_drawdown"] > m["maximum_drawdown"], d["calmar"] > m["calmar"], d["expected_shortfall_5"] > m["expected_shortfall_5"]])
        useful.append({"fold": fold, "economically_useful": bool(d["sharpe"] >= m["sharpe"] - .03 and improvements >= 2), "improvement_count": improvements, "sharpe_delta": d["sharpe"] - m["sharpe"]})
    fold_table = pd.DataFrame(fold_rows).merge(pd.DataFrame(useful), on="fold", how="left")
    matched_table = exposures.assign(matched_multiplier=exposures.fold.map(fold_constants), matched=lambda x: x.base * x.matched_multiplier)
    if matched_error > 1e-12 or selected.dynamic_weight.gt(selected.base_r6_weight + 1e-15).any():
        raise RuntimeError(f"MATCHED_OR_LEVERAGE_FAILURE:{matched_error}")
    return pd.DataFrame(metric_rows), fold_table, matched_table, simulations


def timing_placebos(oof: pd.DataFrame, weights: pd.DataFrame, positions: pd.DataFrame, actual: dict[str, pd.DataFrame]) -> pd.DataFrame:
    dates = oof[["signal_date", "risk_percentile"]].drop_duplicates().sort_values("signal_date")
    multipliers = mapping(dates.risk_percentile, PRIMARY_MAPPING)
    selected = weights.loc[weights.signal_date.isin(dates.signal_date)].copy()
    base_by_date = selected.groupby("signal_date").r6_adjusted_weight.sum()
    actual_matched = actual["MATCHED_CONSTANT"]
    matched_metric = strategy_metrics(actual_matched, BASE_COST)
    rng = np.random.default_rng(RNG_SEED)
    valid_shifts = np.arange(20, len(dates) - 20)
    shifts = rng.choice(valid_shifts, size=PLACEBO_COUNT, replace=True)
    rows = []
    for index, shift in enumerate(shifts):
        shifted = np.roll(multipliers, int(shift))
        map_by_date = dict(zip(dates.signal_date, shifted))
        placebo = selected.copy()
        placebo["placebo_weight"] = placebo.r6_adjusted_weight * placebo.signal_date.map(map_by_date)
        sim = R1.simulate(R1.target_maps(placebo, "placebo_weight"), positions, BASE_COST)
        metric = strategy_metrics(sim, BASE_COST)
        rows.append({"permutation": index, "circular_shift": int(shift), "cagr_delta": metric["cagr"] - matched_metric["cagr"], "sharpe_delta": metric["sharpe"] - matched_metric["sharpe"], "mdd_delta": metric["maximum_drawdown"] - matched_metric["maximum_drawdown"], "calmar_delta": metric["calmar"] - matched_metric["calmar"], "es5_delta": metric["expected_shortfall_5"] - matched_metric["expected_shortfall_5"]})
    return pd.DataFrame(rows)


def block_bootstrap(frame: pd.DataFrame, x: str, y: str, block: int, count: int = 500) -> dict[str, float]:
    rng = np.random.default_rng(RNG_SEED + block)
    n = len(frame); values = []
    starts = np.arange(max(1, n - block + 1))
    for _ in range(count):
        indexes = []
        while len(indexes) < n:
            start = int(rng.choice(starts)); indexes.extend(range(start, min(start + block, n)))
        sample = frame.iloc[indexes[:n]]
        values.append(finite_corr(sample[x], sample[y]))
    return {"block": block, "count": count, "lower_2_5": float(np.nanquantile(values, .025)), "median": float(np.nanmedian(values)), "upper_97_5": float(np.nanquantile(values, .975))}


def economic_block_bootstrap(dynamic: pd.DataFrame, matched: pd.DataFrame, block: int, count: int = 500) -> dict[str, float]:
    rng = np.random.default_rng(RNG_SEED + 100 + block)
    n = len(dynamic); starts = np.arange(max(1, n - block + 1)); values = []
    for _ in range(count):
        indexes = []
        while len(indexes) < n:
            start = int(rng.choice(starts)); indexes.extend(range(start, min(start + block, n)))
        indexes = indexes[:n]
        d = dynamic.daily_return.iloc[indexes].to_numpy(float)
        m = matched.daily_return.iloc[indexes].to_numpy(float)
        d_sharpe = d.mean() / d.std(ddof=1) * np.sqrt(252) if d.std(ddof=1) > 0 else np.nan
        m_sharpe = m.mean() / m.std(ddof=1) * np.sqrt(252) if m.std(ddof=1) > 0 else np.nan
        values.append(d_sharpe - m_sharpe)
    return {"block": block, "count": count, "metric": "paired_sharpe_delta", "lower_2_5": float(np.nanquantile(values, .025)), "median": float(np.nanmedian(values)), "upper_97_5": float(np.nanquantile(values, .975))}


def risk_buckets(oof: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    # Candidate OOF frames retain the feature columns used at prediction time.
    # Avoid a second merge that would suffix identical feature names.
    merged = oof.copy()
    boundaries = [-1e-9, .2, .4, .6, .8, .95, 1.000001]
    labels = ["00_20", "20_40", "40_60", "60_80", "80_95", "95_100"]
    merged["risk_bucket"] = pd.cut(merged.risk_percentile, boundaries, labels=labels)
    columns = ["Y_RISK_20", "forward_20d_cumulative_return", "forward_20d_max_drawdown", "worst_5d_inside_20d", "VIX_LEVEL", "SPY_REALIZED_VOL_20D", "average_pairwise_correlation", "average_pairwise_correlation_CHANGE_5", "R6_WEIGHTED_MEAN"]
    aggregations = {column: "mean" for column in columns}
    table = merged.groupby("risk_bucket", observed=True).agg(row_count=("signal_date", "size"), **{f"mean_{column}": (column, func) for column, func in aggregations.items()}).reset_index()
    return table


def permutation_importances(fits: list[Any], features: list[str]) -> pd.DataFrame:
    rows = []
    for index, (model, _train, valid) in enumerate(fits):
        result = permutation_importance(model, valid[features], valid.Y_RISK_20, scoring="neg_mean_absolute_error", n_repeats=10, random_state=RNG_SEED + index, n_jobs=1)
        for feature, value in zip(features, result.importances_mean):
            rows.append({"fold_index": index + 1, "feature": feature, "importance": float(value)})
    return pd.DataFrame(rows).groupby("feature").importance.agg(["mean", "std"]).reset_index().sort_values("mean", ascending=False)


def classify(comparison: pd.DataFrame, selected: str, economic: pd.DataFrame, folds_economic: pd.DataFrame, placebo: pd.DataFrame, diagnostic_only: bool) -> tuple[str, dict[str, Any]]:
    pred = comparison.set_index("model").loc[selected]
    base = economic.loc[(economic.cost_case.eq("BASELINE"))].set_index("strategy")
    dynamic, matched = base.loc["R2_DYNAMIC"], base.loc["MATCHED_CONSTANT"]
    useful = int(folds_economic.loc[folds_economic.strategy.eq("R2_DYNAMIC")].economically_useful.fillna(False).sum())
    placebo_median = float(placebo.sharpe_delta.median())
    placebo_percentile = float((placebo.sharpe_delta < dynamic.sharpe - matched.sharpe).mean())
    values = {
        "predictive_spearman": float(pred.spearman), "positive_predictive_folds": int(pred.positive_predictive_folds),
        "top_bottom_severity_spread": float(pred.q5_minus_q1_severity), "dynamic_minus_matched_sharpe": float(dynamic.sharpe - matched.sharpe),
        "dynamic_minus_matched_calmar": float(dynamic.calmar - matched.calmar), "dynamic_minus_matched_mdd": float(dynamic.maximum_drawdown - matched.maximum_drawdown),
        "dynamic_minus_matched_es5": float(dynamic.expected_shortfall_5 - matched.expected_shortfall_5), "dynamic_minus_matched_cagr": float(dynamic.cagr - matched.cagr),
        "positive_economic_folds": useful, "placebo_median_sharpe_delta": placebo_median, "actual_sharpe_delta_placebo_percentile": placebo_percentile,
    }
    placebo_positive = values["dynamic_minus_matched_sharpe"] > placebo_median
    a = bool(values["predictive_spearman"] > 0 and values["positive_predictive_folds"] == 4 and values["top_bottom_severity_spread"] > 0 and values["dynamic_minus_matched_sharpe"] >= .05 and values["dynamic_minus_matched_calmar"] >= .10 and values["dynamic_minus_matched_mdd"] >= 0 and values["dynamic_minus_matched_es5"] >= 0 and values["dynamic_minus_matched_cagr"] >= -.02 and useful == 4 and placebo_positive and not diagnostic_only)
    risk_improvements = sum([values["dynamic_minus_matched_mdd"] > 0, values["dynamic_minus_matched_calmar"] > 0, values["dynamic_minus_matched_es5"] > 0])
    b = bool(values["predictive_spearman"] > 0 and values["positive_predictive_folds"] >= 3 and values["dynamic_minus_matched_sharpe"] >= 0 and risk_improvements >= 2 and values["dynamic_minus_matched_cagr"] >= -.03 and useful >= 3 and placebo_positive and not diagnostic_only)
    c = bool(values["predictive_spearman"] > 0 and values["positive_predictive_folds"] >= 3 and values["top_bottom_severity_spread"] > 0)
    classification = "A_PRE2026_STRONG_TIMING_VALUE" if a else "B_PRE2026_USEFUL_TIMING_VALUE" if b else "C_PREDICTIVE_ONLY_ECONOMIC_UNCONFIRMED" if c else "D_NO_USEFUL_TIMING_SIGNAL"
    return classification, values


def run() -> dict[str, Any]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    identity = frozen_identity()
    weights, positions, base_daily = base_inputs()
    targets = forward_targets(weights.signal_date.drop_duplicates(), base_daily)
    features, feature_manifest, families = feature_table(weights, base_daily)
    panel = features.merge(targets, on="signal_date", validate="one_to_one")
    if panel.signal_date.duplicated().any() or panel.signal_date.ge(TRAINING_CUTOFF).any() or panel.information_date.ge(panel.signal_date).any():
        raise RuntimeError("PANEL_PIT_FAILURE")
    write_json(FEATURE_MANIFEST_PATH, {"features": feature_manifest, "families": families, "included_feature_count": sum(map(len, families.values())), "removed_feature_count": sum(not x["included"] for x in feature_manifest), "outcome_driven_removal_count": 0})
    source_paths = [R1_CONTRACT, R1_GEOMETRY, R1_WEIGHTS, R1.COVARIANCE_PANEL, R1.R6_OOF, R1.R3.POSITION_LEDGER_PATH, R1.VIX_PATH]
    source_fingerprints = {str(path): sha256_file(path) for path in source_paths}
    contract_sha = freeze_contract(contract_payload(identity, families, source_fingerprints))
    fold_rows, assignment = folds(panel)
    write_json(OUTPUT / "risk_os_r2_fold_manifest.json", {"folds": R1.safe(fold_rows), "fold_count": 4, "alignment": "R6_FOLD_2_TO_FOLD_5_EXACT_BOUNDARIES", "fold_1_disposition": "TRAINING_HISTORY_ONLY_NO_EARLIER_R6_OOF_ROWS"})
    full_features = sum(families.values(), [])
    comparison, predictions, fits = model_comparison(panel, full_features, fold_rows)
    selected, diagnostic_only = select_model(comparison)
    selected_oof = predictions[selected].copy()
    selected_oof = selected_oof.merge(assignment, on="signal_date", suffixes=("", "_contract"), validate="one_to_one")
    if not selected_oof.fold.eq(selected_oof.fold_contract).all():
        raise RuntimeError("OOF_FOLD_IDENTITY_FAILURE")
    selected_oof = selected_oof.drop(columns="fold_contract")
    selected_freeze = {"selected_model": selected, "diagnostic_only_due_predictive_gate": diagnostic_only, "selection_rule": json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))["model_selection"], "contract_sha256": contract_sha, "feature_schema_hash": canonical_hash(full_features), "exposure_mapping_hash": canonical_hash(PRIMARY_MAPPING)}
    write_json(OUTPUT / "risk_os_r2_selected_model_freeze.json", selected_freeze)
    selected_freeze["freeze_sha256"] = sha256_file(OUTPUT / "risk_os_r2_selected_model_freeze.json")
    ablation, ablation_predictions = ablations(panel, families, fold_rows)
    simple = fixed_score_diagnostics(panel, fold_rows)
    comparison_out = pd.concat([comparison.assign(comparison_type="MODEL"), simple.rename(columns={"benchmark": "model"}).assign(comparison_type="SIMPLE_RULE")], ignore_index=True, sort=False)
    economic, fold_economic, matched, simulations = economic_evaluation(selected_oof, weights, positions)
    placebo = timing_placebos(selected_oof, weights, positions, simulations)
    classification, gate_values = classify(comparison, selected, economic, fold_economic, placebo, diagnostic_only)
    authorized = classification.startswith("A_") or classification.startswith("B_")
    if authorized:
        raise RuntimeError("PRE2026_GATE_PASSED_REQUIRES_SEPARATE_IMPLEMENTED_FREEZE_BEFORE_2026")
    buckets = risk_buckets(selected_oof, features)
    importance = permutation_importances(fits[selected], full_features)
    bootstrap = [block_bootstrap(selected_oof, "prediction", "Y_RISK_20", block) for block in [20, 40]]
    economic_bootstrap = [economic_block_bootstrap(simulations["R2_DYNAMIC"], simulations["MATCHED_CONSTANT"], block) for block in [20, 40]]
    base_metrics = economic.loc[economic.cost_case.eq("BASELINE")].set_index("strategy")
    return_retention = float(base_metrics.loc["R2_DYNAMIC", "total_return"] / base_metrics.loc["BASE_R6", "total_return"]) if base_metrics.loc["BASE_R6", "total_return"] > 0 else np.nan
    matched_error = float(abs(simulations["R2_DYNAMIC"].target_exposure.mean() - simulations["MATCHED_CONSTANT"].target_exposure.mean()))
    r6_incremental = ablation.loc[ablation.ablation.isin(["C_MARKET_GEOMETRY_A2", "D_FULL_WITH_R6"])].copy()
    r6_incremental["spearman_delta_vs_without_r6"] = r6_incremental.spearman - float(r6_incremental.loc[r6_incremental.ablation.eq("C_MARKET_GEOMETRY_A2"), "spearman"].iloc[0])
    for ablation_name in ["C_MARKET_GEOMETRY_A2", "D_FULL_WITH_R6"]:
        local_economic, _local_folds, _local_matched, _local_sim = economic_evaluation(ablation_predictions[ablation_name], weights, positions)
        local = local_economic.loc[local_economic.cost_case.eq("BASELINE")].set_index("strategy")
        row_mask = r6_incremental.ablation.eq(ablation_name)
        for metric in ["cagr", "sharpe", "maximum_drawdown", "calmar", "expected_shortfall_5"]:
            r6_incremental.loc[row_mask, f"dynamic_minus_matched_{metric}"] = float(local.loc["R2_DYNAMIC", metric] - local.loc["MATCHED_CONSTANT", metric])
    r1_hypothesis = simple.loc[simple.benchmark.str.startswith("CORRELATION")].copy()
    fold_predictive_rows = []
    for fold, part in selected_oof.groupby("fold"):
        fold_predictive_rows.append({"fold": fold, **predictive_metrics(part), "direction_positive": finite_corr(part.prediction, part.Y_RISK_20) > 0})
    predictive_table = pd.DataFrame([{"scope": "POOLED", "model": selected, **predictive_metrics(selected_oof)}] + [{"scope": row.pop("fold"), "model": selected, **row} for row in fold_predictive_rows])
    oof_columns = ["signal_date", "information_date", "target_end_date", "fold", "Y_RISK_20", "forward_20d_worst_cum_return", "forward_20d_cumulative_return", "forward_20d_max_drawdown", "worst_5d_inside_20d", "forward_10d_worst_cum_return", "forward_40d_worst_cum_return", "prediction", "risk_percentile"]
    write_parquet(OUTPUT / "risk_os_r2_oof_predictions.parquet", selected_oof[oof_columns])
    write_csv(OUTPUT / "risk_os_r2_model_comparison.csv", comparison_out)
    write_csv(OUTPUT / "risk_os_r2_feature_family_ablation.csv", ablation)
    write_csv(OUTPUT / "risk_os_r2_predictive_metrics.csv", predictive_table)
    write_csv(OUTPUT / "risk_os_r2_risk_bucket_analysis.csv", buckets)
    write_csv(OUTPUT / "risk_os_r2_economic_metrics.csv", economic)
    write_csv(OUTPUT / "risk_os_r2_fold_economics.csv", fold_economic)
    write_csv(OUTPUT / "risk_os_r2_matched_exposure.csv", matched)
    write_csv(OUTPUT / "risk_os_r2_placebo_summary.csv", placebo)
    write_csv(OUTPUT / "risk_os_r2_r6_incremental_analysis.csv", r6_incremental)
    write_csv(OUTPUT / "risk_os_r2_r1_hypothesis_analysis.csv", r1_hypothesis)
    write_csv(OUTPUT / "risk_os_r2_feature_importance.csv", importance)
    guard_run = subprocess.run([sys.executable, str(GUARD)], cwd=REPO, text=True, capture_output=True, check=False)
    try:
        guard = json.loads(guard_run.stdout)
    except json.JSONDecodeError:
        guard = {"status": "ERROR", "violations": ["GUARD_OUTPUT_UNREADABLE"]}
    new_r2_violations = [item for item in guard.get("violations", []) if "a2_risk_os_r2" in str(item).lower()]
    audit = {
        "frozen_a2_unchanged": frozen_identity()["a2_hash_manifest_sha256"] == identity["a2_hash_manifest_sha256"],
        "frozen_r6_unchanged": sha256_file(R1.R6_OOF) == R1.R6_OOF_SHA256 and sha256_file(R1.R6_DEPLOY) == R1.R6_DEPLOY_SHA256,
        "frozen_r1_unchanged": sha256_file(R1_CONTRACT) == R1_CONTRACT_SHA256,
        "training_cutoff_exclusive": "2026-01-01", "2026_training_rows": 0, "2026_outcome_read_count": 0,
        "2026_parameter_search_count": 0, "2026_threshold_search_count": 0, "parameter_search_count": 0, "threshold_search_count": 0,
        "lookahead_violation_count": int((panel.information_date >= panel.signal_date).sum()),
        "target_overlap_leakage_count": int(sum(x["overlap_leakage_count"] for x in fold_rows)),
        "duplicate_portfolio_date_count": int(panel.signal_date.duplicated().sum()), "matched_exposure_error": matched_error,
        "maximum_multiplier": float(mapping(selected_oof.risk_percentile, PRIMARY_MAPPING).max()), "leverage_increase_count": 0,
        "feature_outcome_driven_removal_count": 0, "contract_sha256": contract_sha,
        "block_bootstrap": bootstrap, "economic_block_bootstrap": economic_bootstrap,
        "model_fit_count": len(candidates()) * len(fold_rows) + 5 * len(fold_rows),
        "2026_R2_OUTCOME_READ_COUNT": 0,
        "anti_bloat": {"repository_guard_status": guard.get("status"), "repository_guard_violation_count": len(guard.get("violations", [])), "new_r2_violation_count": len(new_r2_violations), "new_r2_violations": new_r2_violations},
    }
    write_json(OUTPUT / "risk_os_r2_audit.json", audit)
    selected_row = comparison.set_index("model").loc[selected]
    summary = {
        "A2_RISK_OS_R2_STATUS": "STOP_PRE2026_GATE_NOT_PASSED",
        "A2_RISK_OS_R2_PRE2026_CLASSIFICATION": classification,
        "A2_RISK_OS_R2_SELECTED_MODEL": selected,
        "A2_RISK_OS_R2_CONTRACT_SHA256": contract_sha,
        "A2_RISK_OS_R2_OOF_SAMPLE_COUNT": len(selected_oof),
        "A2_RISK_OS_R2_POSITIVE_PREDICTIVE_FOLDS": int(selected_row.positive_predictive_folds),
        "A2_RISK_OS_R2_POSITIVE_ECONOMIC_FOLDS": gate_values["positive_economic_folds"],
        "A2_RISK_OS_R2_AVG_DYNAMIC_EXPOSURE": float(simulations["R2_DYNAMIC"].target_exposure.mean()),
        "A2_RISK_OS_R2_MATCHED_EXPOSURE_ERROR": matched_error,
        "A2_RISK_OS_R2_2026_AUTHORIZED": False, "2026_R2_OUTCOME_READ_COUNT": 0,
        "A2_RISK_OS_R2_FINAL_CLASSIFICATION": classification,
        "NEXT_AUTHORIZED_STEP": "PRESERVE_R2_RESEARCH_HISTORY_AND_STOP;DO_NOT_OPEN_2026",
        "training_date_range": [str(panel.signal_date.min().date()), str(panel.signal_date.max().date())],
        "portfolio_date_samples": len(panel), "target_maturity_count": len(targets), "missing_feature_dates": int(panel[full_features].isna().any(axis=1).sum()),
        "usable_oof_dates": len(selected_oof), "fold_count": len(fold_rows), "selected_model_diagnostic_only": diagnostic_only,
        "predictive_metrics": R1.safe(selected_row.to_dict()), "economic_gate_values": gate_values,
        "return_retention_vs_base_r6": return_retention, "block_bootstrap": bootstrap, "economic_block_bootstrap": economic_bootstrap,
        "placebo_actual_sharpe_delta_percentile": gate_values["actual_sharpe_delta_placebo_percentile"],
        "prospective_authorization_reason": "PRE2026_A_OR_B_REQUIRED;NOT_MET", "2026_outcomes_opened": False,
        "ANTI_BLOAT_STATUS": "PASS_NEW_R2_ZERO" if not new_r2_violations else "FAIL_NEW_R2_VIOLATIONS",
        "PREEXISTING_REPOSITORY_GUARD_STATUS": guard.get("status"),
    }
    write_json(OUTPUT / "risk_os_r2_final_summary.json", summary)
    artifact_hashes = {path.name: sha256_file(path) for path in sorted(OUTPUT.iterdir()) if path.is_file() and path.name != "risk_os_r2_run_manifest.json"}
    write_json(OUTPUT / "risk_os_r2_run_manifest.json", {"run_id": f"A2_RISK_OS_R2_{contract_sha[:12]}", "code_fingerprint": sha256_file(Path(__file__)), "config_fingerprint": contract_sha, "source_fingerprints": source_fingerprints, "artifact_hashes": artifact_hashes, "data_cutoff_exclusive": "2026-01-01", "classification": classification, "next_authorized_step": summary["NEXT_AUTHORIZED_STEP"]})
    return summary


def print_summary(summary: dict[str, Any]) -> None:
    keys = ["A2_RISK_OS_R2_STATUS", "A2_RISK_OS_R2_PRE2026_CLASSIFICATION", "A2_RISK_OS_R2_SELECTED_MODEL", "A2_RISK_OS_R2_CONTRACT_SHA256", "A2_RISK_OS_R2_OOF_SAMPLE_COUNT", "A2_RISK_OS_R2_POSITIVE_PREDICTIVE_FOLDS", "A2_RISK_OS_R2_POSITIVE_ECONOMIC_FOLDS", "A2_RISK_OS_R2_AVG_DYNAMIC_EXPOSURE", "A2_RISK_OS_R2_MATCHED_EXPOSURE_ERROR", "A2_RISK_OS_R2_2026_AUTHORIZED", "2026_R2_OUTCOME_READ_COUNT", "A2_RISK_OS_R2_FINAL_CLASSIFICATION", "NEXT_AUTHORIZED_STEP"]
    for key in keys:
        print(f"{key}={summary[key]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    try:
        if not args.run:
            parser.error("--run is required")
        summary = run(); print_summary(summary); return 0
    except Exception as exc:
        print(f"A2_RISK_OS_R2_STATUS=STOP_FAIL_CLOSED\nA2_RISK_OS_R2_PRE2026_CLASSIFICATION=E_INVALID_OR_INSUFFICIENT_EVIDENCE\nERROR={type(exc).__name__}:{exc}\n2026_R2_OUTCOME_READ_COUNT=0\nNEXT_AUTHORIZED_STEP=STOP_AND_RESOLVE_R2_INTEGRITY", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
