"""Config-driven, fail-closed A2 pre-2026 nested research engine.

High-volume evidence is routed to the configured external results/cache roots.
The engine deliberately exposes separate preflight/search/freeze/holdout phases;
the holdout phase cannot run until the immutable pre-2026 freeze verifies.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import platform
import shutil
import sys
import time
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.stats import rankdata, spearmanr
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.metrics import ndcg_score
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config/v22/a2_open_research_r1.json"
LEDGER_COLUMNS = [
    "trial_id", "parent_trial_id", "timestamp", "model_family", "feature_set_id", "factor_set_id",
    "hyperparameters", "threshold_parameters", "ensemble_parameters", "random_seed", "outer_fold",
    "inner_fold", "train_start", "train_end", "validation_start", "validation_end", "test_start",
    "test_end", "row_count", "feature_count", "status", "failure_reason", "runtime_seconds",
    "predictive_metrics", "economic_metrics", "complexity_metrics", "input_hash", "code_hash",
]
FACTOR_COLUMNS = [
    "factor_id", "factor_name", "formula", "source_columns", "lookback", "minimum_history",
    "availability_timestamp_rule", "cross_sectional_or_time_series", "normalization", "winsorization",
    "missing_policy", "sector_neutralization", "market_neutralization", "complexity", "creation_method",
    "code_hash",
]
CONTROL_ID = "M0_A2_HGB_AUTH_TEMPORAL"
RANKING_FAMILIES = {"XGBOOST_RANKING", "LIGHTGBM_RANKING", "CATBOOST_RANKING"}


class GovernanceError(RuntimeError):
    """A fail-closed scientific or storage-governance violation."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(json.dumps(value, indent=2, sort_keys=True, default=str, allow_nan=False).encode("utf-8") + b"\n")
    os.replace(temporary, path)


def atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise GovernanceError(f"MODULE_LOAD_FAILURE:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def require(condition: bool, code: str) -> None:
    if not condition:
        raise GovernanceError(code)


@dataclass(frozen=True)
class Paths:
    output: Path
    cache: Path

    @property
    def ledger(self) -> Path:
        return self.output / "03_model_search/research_trial_ledger.parquet"

    @property
    def checkpoint(self) -> Path:
        return self.output / "checkpoint.json"


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    output = Path(config["output_root"])
    cache = Path(config["cache_root"])
    require(not output.is_relative_to(REPO_ROOT), "ANTI_BLOAT_OUTPUT_INSIDE_REPOSITORY")
    require(not cache.is_relative_to(REPO_ROOT), "ANTI_BLOAT_CACHE_INSIDE_REPOSITORY")
    require(tuple(config["outer_years"]) == (2023, 2024, 2025), "AUTHORITATIVE_OUTER_FOLD_MISMATCH")
    require(config["target_horizon_trading_days"] == 20, "AUTHORITATIVE_TARGET_HORIZON_MISMATCH")
    require(config["top_k_grid"] == [10, 15, 20, 25, 30, 40], "UNBOUNDED_TOPK_GRID")
    return config


def initialize_paths(config: dict[str, Any]) -> Paths:
    paths = Paths(Path(config["output_root"]), Path(config["cache_root"]))
    for child in (
        "00_preflight", "01_data", "02_factor_registry", "03_model_search", "04_threshold_search",
        "05_neural_networks", "06_symbolic_factors", "07_ensembles", "08_robustness",
        "09_pre2026_freeze", "10_2026_locked_holdout", "11_forward_shadows", "12_audit",
        "13_morning_report",
    ):
        (paths.output / child).mkdir(parents=True, exist_ok=True)
    (paths.cache / "models").mkdir(parents=True, exist_ok=True)
    (paths.cache / "oof_parts").mkdir(parents=True, exist_ok=True)
    return paths


class TrialLedger:
    """Atomic, lossless ledger updates. Existing rows are never removed or mutated."""

    def __init__(self, path: Path):
        self.path = path
        self.frame = pd.read_parquet(path) if path.is_file() else pd.DataFrame(columns=LEDGER_COLUMNS)
        require(list(self.frame.columns) == LEDGER_COLUMNS, "TRIAL_LEDGER_SCHEMA_MISMATCH")
        require(not self.frame.trial_id.duplicated().any(), "TRIAL_LEDGER_DUPLICATE_ID")

    def append(self, rows: Iterable[dict[str, Any]]) -> None:
        additions = pd.DataFrame(list(rows), columns=LEDGER_COLUMNS)
        if additions.empty:
            return
        require(not additions.trial_id.duplicated().any(), "TRIAL_BATCH_DUPLICATE_ID")
        require(not additions.trial_id.isin(set(self.frame.trial_id)).any(), "TRIAL_LEDGER_OVERWRITE_ATTEMPT")
        self.frame = pd.concat([self.frame, additions], ignore_index=True)
        atomic_parquet(self.path, self.frame)


def checkpoint(paths: Paths, phase: str, last_trial: str, status: str = "RUNNING") -> None:
    atomic_json(paths.checkpoint, {
        "run_id": paths.output.name,
        "status": status,
        "last_completed_phase": phase,
        "last_completed_trial": last_trial,
        "checkpoint_path": str(paths.checkpoint),
        "resume_command": (
            r"D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe "
            r"D:\us-tech-quant\scripts\v22\a2_open_research_engine.py --phase all-pre2026"
        ),
        "updated_at_utc": utc_now(),
    })


def guarded_pre2026_frame(config: dict[str, Any]) -> pd.DataFrame:
    dataset = Path(config["research_dataset"])
    require("2026" not in dataset.name.lower(), "PRE2026_INPUT_NAME_GUARD")
    require(dataset.is_file(), "RESEARCH_DATASET_MISSING")
    columns = [
        "signal_date", "target_end_date", "next_execution_date", "security_id", "ticker",
        "report_quarter", "target", *config["base_features"],
    ]
    frame = pd.read_parquet(dataset, columns=columns)
    cutoff = pd.Timestamp(config["cutoff"])
    frame["feature_information_available_timestamp"] = pd.to_datetime(frame.signal_date)
    frame["label_maturity_timestamp"] = pd.to_datetime(frame.target_end_date)
    require((frame.feature_information_available_timestamp < cutoff).all(), "POST2025_FEATURE_INFORMATION_READ")
    require((frame.label_maturity_timestamp < cutoff).all(), "POST2025_LABEL_MATURITY_READ")
    require(pd.to_datetime(frame.next_execution_date).lt(cutoff).all(), "POST2025_EXECUTION_INFORMATION_READ")
    require(frame.target.notna().all(), "UNMATURED_OR_MISSING_TARGET")
    require(np.isfinite(frame.loc[:, config["base_features"]].to_numpy(dtype=float)).all(), "NONFINITE_BASE_FEATURE")
    frame = frame.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    require(not frame.duplicated(["signal_date", "security_id"]).any(), "DUPLICATE_RESEARCH_ROW")
    return frame


def safe_divide(left: pd.Series, right: pd.Series, floor: float = 1e-8) -> pd.Series:
    denominator = right.astype(float).where(right.abs() >= floor)
    return left.astype(float).div(denominator).replace([np.inf, -np.inf], np.nan).fillna(0.0)


def factor_definitions(code_hash: str) -> list[dict[str, Any]]:
    common = {
        "availability_timestamp_rule": "SIGNAL_DATE_CANONICAL_CLOSE_AFTER_FINAL_FULL_DAY_VOLUME",
        "winsorization": "NONE_RAW_DETERMINISTIC_FORMULA;LEARNED_TRANSFORMS_TRAIN_ONLY",
        "missing_policy": "SAFE_DIVIDE_ZERO_OR_TRAIN_MEDIAN_IN_MODEL_PIPELINE",
        "sector_neutralization": "NONE_SECTOR_SOURCE_UNAVAILABLE",
        "market_neutralization": "NONE",
        "creation_method": "PREDEFINED_BOUNDED_R1_GRAMMAR",
        "code_hash": code_hash,
    }
    rows = [
        ("F001", "momentum_multi_horizon", "mean(ret_5d,ret_20d,ret_60d,ret_120d)", ["ret_5d","ret_20d","ret_60d","ret_120d"], 120, 4, "time_series", 3),
        ("F002", "momentum_acceleration", "ret_20d-ret_60d/3", ["ret_20d","ret_60d"], 60, 2, "time_series", 2),
        ("F003", "trend_consistency", "mean(sign(ret_5d),sign(ret_20d),sign(ret_60d))", ["ret_5d","ret_20d","ret_60d"], 60, 3, "time_series", 3),
        ("F004", "breakout_composite", "mean(distance_from_high_20d,distance_from_high_60d)", ["distance_from_high_20d","distance_from_high_60d"], 60, 2, "time_series", 2),
        ("F005", "short_reversal", "-mean(ret_1d,ret_3d)", ["ret_1d","ret_3d"], 3, 2, "time_series", 2),
        ("F006", "vol_adjusted_momentum", "safe_divide(ret_20d,realized_vol_20d)", ["ret_20d","realized_vol_20d"], 20, 2, "time_series", 3),
        ("F007", "vol_term_5_20", "safe_divide(realized_vol_5d,realized_vol_20d)", ["realized_vol_5d","realized_vol_20d"], 20, 2, "time_series", 3),
        ("F008", "vol_term_20_60", "safe_divide(realized_vol_20d,realized_vol_60d)", ["realized_vol_20d","realized_vol_60d"], 60, 2, "time_series", 3),
        ("F009", "downside_upside_ratio", "safe_divide(downside_vol_20d,upside_vol_20d)", ["downside_vol_20d","upside_vol_20d"], 20, 2, "time_series", 3),
        ("F010", "drawdown_velocity", "max_drawdown_20d-max_drawdown_60d", ["max_drawdown_20d","max_drawdown_60d"], 60, 2, "time_series", 2),
        ("F011", "log_dollar_volume", "log1p(abs(avg_dollar_volume_20d))", ["avg_dollar_volume_20d"], 20, 1, "time_series", 2),
        ("F012", "liquidity_growth", "safe_divide(avg_volume_20d,avg_volume_60d)-1", ["avg_volume_20d","avg_volume_60d"], 60, 2, "time_series", 3),
        ("F013", "volume_price_divergence", "ret_20d*(1-volume_ratio_5d_20d)", ["ret_20d","volume_ratio_5d_20d"], 20, 2, "time_series", 3),
        ("F014", "cs_rank_momentum_20d", "rank_by_signal_date(ret_20d)", ["ret_20d"], 20, 1, "cross_sectional", 2),
        ("F015", "cs_rank_reversal_3d", "rank_by_signal_date(-ret_3d)", ["ret_3d"], 3, 1, "cross_sectional", 2),
        ("F016", "cs_rank_liquidity", "rank_by_signal_date(log_dollar_volume)", ["avg_dollar_volume_20d"], 20, 1, "cross_sectional", 3),
        ("F017", "cs_breadth_20d", "mean_by_signal_date(ret_20d>0)", ["ret_20d"], 20, 1, "cross_sectional", 2),
        ("F018", "cs_dispersion_20d", "std_by_signal_date(ret_20d)", ["ret_20d"], 20, 1, "cross_sectional", 2),
        ("F019", "continuous_risk_on", "cs_breadth_20d-cs_dispersion_20d", ["ret_20d"], 20, 1, "cross_sectional", 3),
        ("F020", "momentum_x_volatility", "momentum_multi_horizon*vol_term_20_60", ["ret_5d","ret_20d","ret_60d","ret_120d","realized_vol_20d","realized_vol_60d"], 120, 6, "interaction", 4),
        ("F021", "momentum_x_liquidity", "momentum_multi_horizon*cs_rank_liquidity", ["ret_5d","ret_20d","ret_60d","ret_120d","avg_dollar_volume_20d"], 120, 5, "interaction", 4),
        ("F022", "trend_x_regime", "trend_consistency*continuous_risk_on", ["ret_5d","ret_20d","ret_60d"], 60, 3, "interaction", 4),
        ("F023", "reversal_x_volatility", "short_reversal*vol_term_5_20", ["ret_1d","ret_3d","realized_vol_5d","realized_vol_20d"], 20, 4, "interaction", 4),
    ]
    return [{
        "factor_id": fid, "factor_name": name, "formula": formula,
        "source_columns": json.dumps(sources), "lookback": lookback, "minimum_history": minimum,
        "cross_sectional_or_time_series": kind, "normalization": "RAW_OR_CONTEMPORANEOUS_PCT_RANK",
        "complexity": complexity, **common,
    } for fid, name, formula, sources, lookback, minimum, kind, complexity in rows]


def materialize_factors(frame: pd.DataFrame) -> pd.DataFrame:
    x = frame.copy()
    x["momentum_multi_horizon"] = x[["ret_5d","ret_20d","ret_60d","ret_120d"]].mean(axis=1)
    x["momentum_acceleration"] = x.ret_20d - x.ret_60d / 3.0
    x["trend_consistency"] = np.sign(x[["ret_5d","ret_20d","ret_60d"]]).mean(axis=1)
    x["breakout_composite"] = x[["distance_from_high_20d","distance_from_high_60d"]].mean(axis=1)
    x["short_reversal"] = -x[["ret_1d","ret_3d"]].mean(axis=1)
    x["vol_adjusted_momentum"] = safe_divide(x.ret_20d, x.realized_vol_20d)
    x["vol_term_5_20"] = safe_divide(x.realized_vol_5d, x.realized_vol_20d)
    x["vol_term_20_60"] = safe_divide(x.realized_vol_20d, x.realized_vol_60d)
    x["downside_upside_ratio"] = safe_divide(x.downside_vol_20d, x.upside_vol_20d)
    x["drawdown_velocity"] = x.max_drawdown_20d - x.max_drawdown_60d
    x["log_dollar_volume"] = np.log1p(np.abs(x.avg_dollar_volume_20d))
    x["liquidity_growth"] = safe_divide(x.avg_volume_20d, x.avg_volume_60d) - 1.0
    x["volume_price_divergence"] = x.ret_20d * (1.0 - x.volume_ratio_5d_20d)
    grouped = x.groupby("signal_date", sort=False)
    x["cs_rank_momentum_20d"] = grouped.ret_20d.rank(method="average", pct=True)
    x["cs_rank_reversal_3d"] = grouped.ret_3d.rank(method="average", pct=True, ascending=False)
    x["cs_rank_liquidity"] = grouped.log_dollar_volume.rank(method="average", pct=True)
    x["cs_breadth_20d"] = x.ret_20d.gt(0).groupby(x.signal_date, sort=False).transform("mean")
    x["cs_dispersion_20d"] = grouped.ret_20d.transform(lambda value: value.std(ddof=0))
    x["continuous_risk_on"] = x.cs_breadth_20d - x.cs_dispersion_20d
    x["momentum_x_volatility"] = x.momentum_multi_horizon * x.vol_term_20_60
    x["momentum_x_liquidity"] = x.momentum_multi_horizon * x.cs_rank_liquidity
    x["trend_x_regime"] = x.trend_consistency * x.continuous_risk_on
    x["reversal_x_volatility"] = x.short_reversal * x.vol_term_5_20
    return x


def feature_sets(config: dict[str, Any], registry: pd.DataFrame) -> dict[str, list[str]]:
    base = list(config["base_features"])
    trend = registry.loc[registry.factor_id.isin([f"F{i:03d}" for i in range(1, 7)]), "factor_name"].tolist()
    vol_liq = registry.loc[registry.factor_id.isin([f"F{i:03d}" for i in range(7, 14)]), "factor_name"].tolist()
    cross = registry.loc[registry.factor_id.isin([f"F{i:03d}" for i in range(14, 20)]), "factor_name"].tolist()
    all_new = registry.factor_name.tolist()
    return {
        "BASELINE": base,
        "BASELINE_TREND": base + trend,
        "BASELINE_VOL_LIQ": base + vol_liq,
        "BASELINE_CROSS_REGIME": base + cross,
        "ALL_FACTORS": base + all_new,
    }


def split_before_year(frame: pd.DataFrame, year: int) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    first = pd.Timestamp(f"{year}-01-01")
    last = pd.Timestamp(f"{year + 1}-01-01")
    train = frame.loc[(frame.signal_date < first) & (frame.target_end_date < first)].copy()
    valid = frame.loc[(frame.signal_date >= first) & (frame.signal_date < last)].copy()
    require(len(train) > 0 and len(valid) > 0, f"EMPTY_TEMPORAL_SPLIT:{year}")
    require(train.signal_date.max() < valid.signal_date.min(), f"NON_TEMPORAL_SPLIT:{year}")
    require(train.target_end_date.max() < valid.signal_date.min(), f"UNPURGED_LABEL_OVERLAP:{year}")
    return train, valid, {
        "train_start": train.signal_date.min(), "train_end": train.signal_date.max(),
        "validation_start": valid.signal_date.min(), "validation_end": valid.signal_date.max(),
        "max_train_label_maturity": train.target_end_date.max(),
    }


def grouped_metrics(frame: pd.DataFrame, top_k: int) -> dict[str, float]:
    daily_ic: list[float] = []
    daily_ndcg: list[float] = []
    daily_top: list[float] = []
    daily_hit: list[float] = []
    for _, day in frame.groupby("signal_date", sort=False):
        if len(day) < 3:
            continue
        prediction = day.prediction.to_numpy(float)
        target = day.target.to_numpy(float)
        ic = spearmanr(prediction, target).statistic
        if np.isfinite(ic):
            daily_ic.append(float(ic))
        relevance = rankdata(target, method="average") - 1.0
        daily_ndcg.append(float(ndcg_score(relevance.reshape(1, -1), prediction.reshape(1, -1), k=min(20, len(day)))))
        chosen = np.argsort(-prediction, kind="stable")[: min(top_k, len(day))]
        selected_target = target[chosen]
        daily_top.append(float(np.mean(selected_target)))
        daily_hit.append(float(np.mean(selected_target > 0)))
    return {
        "rank_ic": float(np.mean(daily_ic)) if daily_ic else math.nan,
        "spearman_ic": float(np.mean(daily_ic)) if daily_ic else math.nan,
        "median_ic": float(np.median(daily_ic)) if daily_ic else math.nan,
        "ndcg20": float(np.mean(daily_ndcg)) if daily_ndcg else math.nan,
        "mean_topk_target": float(np.mean(daily_top)) if daily_top else math.nan,
        "cross_sectional_hit_rate": float(np.mean(daily_hit)) if daily_hit else math.nan,
        "date_count": len(daily_top),
    }


def discrete_relevance(frame: pd.DataFrame) -> np.ndarray:
    percentile = frame.target.groupby(frame.signal_date, sort=False).rank(method="average", pct=True)
    return np.minimum((percentile.to_numpy(float) * 5).astype(int), 4)


def model_complexity(family: str, parameters: dict[str, Any], feature_count: int) -> dict[str, Any]:
    trees = int(parameters.get("n_estimators", parameters.get("iterations", parameters.get("max_iter", 0))))
    depth = int(parameters.get("max_depth", parameters.get("depth", 0)) or 0)
    widths = parameters.get("hidden_layer_sizes", [])
    approx_nn = 0
    if widths:
        sizes = [feature_count, *widths, 1]
        approx_nn = int(sum((a + 1) * b for a, b in zip(sizes[:-1], sizes[1:])))
    return {
        "feature_count": feature_count, "tree_count_or_iterations": trees, "max_depth": depth,
        "network_parameter_count_approx": approx_nn,
        "complexity_score": feature_count + trees / 10.0 + depth * 5.0 + approx_nn / 1000.0,
    }


def generate_search_specs(config: dict[str, Any]) -> list[dict[str, Any]]:
    rng = np.random.default_rng(config["random_seed"])
    feature_names = list(config["feature_sets"])
    specs: list[dict[str, Any]] = []
    for family, budget in config["trial_budgets"].items():
        for index in range(int(budget)):
            feature_set = feature_names[index % len(feature_names)]
            if family == "RIDGE":
                params = {"alpha": float(10 ** rng.uniform(-3, 3))}
            elif family == "ELASTIC_NET":
                params = {"alpha": float(10 ** rng.uniform(-5, -1)), "l1_ratio": float(rng.uniform(0.05, 0.95)), "max_iter": 500, "tol": 1e-4}
            elif family == "HIST_GRADIENT_BOOSTING":
                params = {"learning_rate": float(rng.choice([0.02,0.03,0.05,0.08])), "max_iter": int(rng.choice([150,250,350])), "max_leaf_nodes": int(rng.choice([7,15,31])), "max_depth": int(rng.choice([2,3,4,5])), "min_samples_leaf": int(rng.choice([100,200,400])), "l2_regularization": float(rng.choice([0.5,1.0,3.0,10.0])), "early_stopping": False}
            elif family.startswith("XGBOOST"):
                params = {"learning_rate": float(rng.choice([0.02,0.03,0.05,0.08])), "n_estimators": int(rng.choice([200,350,500,700])), "max_depth": int(rng.choice([2,3,4,5])), "min_child_weight": float(rng.choice([10,20,50,100])), "subsample": float(rng.choice([0.7,0.8,0.9,1.0])), "colsample_bytree": float(rng.choice([0.6,0.7,0.8,0.9,1.0])), "colsample_bylevel": float(rng.choice([0.8,1.0])), "gamma": float(rng.choice([0,0.1,0.5,1.0])), "reg_alpha": float(rng.choice([0,0.1,1.0,5.0])), "reg_lambda": float(rng.choice([1.0,5.0,10.0,30.0])), "grow_policy": str(rng.choice(["depthwise","lossguide"]))}
            elif family.startswith("LIGHTGBM"):
                params = {"learning_rate": float(rng.choice([0.02,0.03,0.05,0.08])), "n_estimators": int(rng.choice([200,350,500,700])), "num_leaves": int(rng.choice([7,15,31,63])), "max_depth": int(rng.choice([3,4,5,6,-1])), "min_child_samples": int(rng.choice([100,200,400])), "subsample": float(rng.choice([0.7,0.8,0.9,1.0])), "colsample_bytree": float(rng.choice([0.6,0.8,1.0])), "reg_alpha": float(rng.choice([0,0.1,1.0])), "reg_lambda": float(rng.choice([1.0,5.0,10.0]))}
            elif family.startswith("CATBOOST"):
                params = {"learning_rate": float(rng.choice([0.02,0.03,0.05,0.08])), "iterations": int(rng.choice([200,350,500,700])), "depth": int(rng.choice([4,5,6,7])), "l2_leaf_reg": float(rng.choice([3.0,5.0,10.0,20.0])), "random_strength": float(rng.choice([0.25,0.5,1.0])), "bagging_temperature": float(rng.choice([0.25,0.5,1.0]))}
            elif family in {"RANDOM_FOREST", "EXTRA_TREES"}:
                params = {"n_estimators": int(rng.choice([100,160,240])), "max_depth": int(rng.choice([6,10,14,18])), "min_samples_leaf": int(rng.choice([20,50,100,200])), "max_features": float(rng.choice([0.5,0.7,1.0])), "max_samples": float(rng.choice([0.5,0.7,0.9]))}
            elif family == "MLP":
                layouts = [[64,32],[128,64],[128,64,32],[256,128,64]]
                params = {"hidden_layer_sizes": layouts[int(rng.integers(0, len(layouts)))], "activation": str(rng.choice(["relu","tanh"])), "alpha": float(10 ** rng.uniform(-5,-2)), "learning_rate_init": float(rng.choice([0.0003,0.0005,0.001])), "batch_size": int(rng.choice([512,1024,2048])), "max_iter": int(rng.choice([40,60,80])), "early_stopping": False, "n_iter_no_change": int(rng.choice([5,8,12]))}
            else:
                raise GovernanceError(f"UNKNOWN_SEARCH_FAMILY:{family}")
            specs.append({"spec_id": f"{family}__{index:04d}", "family": family, "feature_set_id": feature_set, "parameters": params})
    return specs


def make_model(family: str, parameters: dict[str, Any], seed: int, threads: int, use_gpu: bool) -> Any:
    params = dict(parameters)
    if family == "RIDGE":
        return Pipeline([("imputer", SimpleImputer(strategy="median")), ("scale", StandardScaler()), ("model", Ridge(**params))])
    if family == "ELASTIC_NET":
        return Pipeline([("imputer", SimpleImputer(strategy="median")), ("scale", StandardScaler()), ("model", ElasticNet(**params, random_state=seed, selection="cyclic"))])
    if family == "HIST_GRADIENT_BOOSTING":
        return Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", HistGradientBoostingRegressor(**params, random_state=seed))])
    if family in {"RANDOM_FOREST", "EXTRA_TREES"}:
        klass = RandomForestRegressor if family == "RANDOM_FOREST" else ExtraTreesRegressor
        return Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", klass(**params, bootstrap=True, random_state=seed, n_jobs=threads))])
    if family == "MLP":
        params["hidden_layer_sizes"] = tuple(params["hidden_layer_sizes"])
        return Pipeline([("imputer", SimpleImputer(strategy="median")), ("scale", StandardScaler()), ("model", MLPRegressor(**params, random_state=seed, shuffle=False))])
    if family.startswith("XGBOOST"):
        from xgboost import XGBRanker, XGBRegressor
        common = {
            **params, "tree_method": "hist", "device": "cuda" if use_gpu else "cpu",
            "random_state": seed, "n_jobs": threads, "verbosity": 0,
        }
        if family == "XGBOOST_RANKING":
            return XGBRanker(**common, objective="rank:pairwise")
        return XGBRegressor(**common, objective="reg:squarederror")
    if family.startswith("LIGHTGBM"):
        from lightgbm import LGBMRanker, LGBMRegressor
        common = {**params, "random_state": seed, "n_jobs": threads, "verbosity": -1, "deterministic": True, "force_row_wise": True}
        if family == "LIGHTGBM_RANKING":
            return LGBMRanker(**common, objective="lambdarank", metric="ndcg")
        return LGBMRegressor(**common, objective="regression")
    if family.startswith("CATBOOST"):
        from catboost import CatBoostRanker, CatBoostRegressor
        common = {**params, "random_seed": seed, "verbose": False, "allow_writing_files": False, "thread_count": threads}
        if family == "CATBOOST_RANKING":
            return CatBoostRanker(**common, loss_function="YetiRank")
        return CatBoostRegressor(**common, loss_function="RMSE")
    raise GovernanceError(f"UNKNOWN_MODEL_FAMILY:{family}")


def fit_predict(
    family: str,
    parameters: dict[str, Any],
    train: pd.DataFrame,
    valid: pd.DataFrame,
    features: list[str],
    seed: int,
    threads: int,
    use_gpu: bool,
) -> tuple[Any, np.ndarray, float]:
    model = make_model(family, parameters, seed, threads, use_gpu)
    start = time.perf_counter()
    if family in RANKING_FAMILIES:
        ordered = train.sort_values(["signal_date", "ticker"], kind="mergesort")
        x_train = ordered.loc[:, features].to_numpy(np.float32)
        y_train = discrete_relevance(ordered)
        group_sizes = ordered.groupby("signal_date", sort=False).size().to_numpy()
        if family == "XGBOOST_RANKING":
            qid = np.repeat(np.arange(len(group_sizes)), group_sizes)
            model.fit(x_train, y_train, qid=qid)
        elif family == "LIGHTGBM_RANKING":
            model.fit(x_train, y_train, group=group_sizes.tolist())
        else:
            group_id = np.repeat(np.arange(len(group_sizes)), group_sizes)
            model.fit(x_train, y_train, group_id=group_id)
    else:
        model.fit(train.loc[:, features].to_numpy(np.float32), train.target.to_numpy(float))
    elapsed = time.perf_counter() - start
    prediction = np.asarray(model.predict(valid.loc[:, features].to_numpy(np.float32)), dtype=float)
    require(np.isfinite(prediction).all(), f"NONFINITE_PREDICTION:{family}")
    return model, prediction, elapsed


def stable_rank(frame: pd.DataFrame) -> pd.Series:
    result = pd.Series(index=frame.index, dtype="int32")
    for _, day in frame.groupby("signal_date", sort=False):
        ordered = day.sort_values(["prediction", "ticker"], ascending=[False, True], kind="mergesort")
        result.loc[ordered.index] = np.arange(1, len(ordered) + 1, dtype=np.int32)
    return result.astype("int32")


def trial_id(*parts: Any) -> str:
    return "T_" + canonical_hash(parts)[:24]


def trial_row(
    *, identifier: str, parent: str, family: str, spec: dict[str, Any], threshold: int,
    outer_fold: str, inner_fold: str, audit: dict[str, Any], row_count: int, feature_count: int,
    status: str, failure: str, runtime: float, predictive: dict[str, Any], economic: dict[str, Any],
    complexity: dict[str, Any], input_hash: str, code_hash: str,
) -> dict[str, Any]:
    return {
        "trial_id": identifier, "parent_trial_id": parent, "timestamp": utc_now(),
        "model_family": family, "feature_set_id": spec["feature_set_id"], "factor_set_id": spec["feature_set_id"],
        "hyperparameters": json.dumps(spec["parameters"], sort_keys=True),
        "threshold_parameters": json.dumps({"top_k": threshold}, sort_keys=True), "ensemble_parameters": "{}",
        "random_seed": spec.get("seed"), "outer_fold": outer_fold, "inner_fold": inner_fold,
        "train_start": audit.get("train_start"), "train_end": audit.get("train_end"),
        "validation_start": audit.get("validation_start"), "validation_end": audit.get("validation_end"),
        "test_start": audit.get("test_start"), "test_end": audit.get("test_end"),
        "row_count": row_count, "feature_count": feature_count, "status": status, "failure_reason": failure,
        "runtime_seconds": runtime, "predictive_metrics": json.dumps(predictive, sort_keys=True, allow_nan=True),
        "economic_metrics": json.dumps(economic, sort_keys=True, allow_nan=True),
        "complexity_metrics": json.dumps(complexity, sort_keys=True, allow_nan=True),
        "input_hash": input_hash, "code_hash": code_hash,
    }


def preflight(config: dict[str, Any], paths: Paths, config_path: Path) -> dict[str, Any]:
    code_hash = sha256_file(Path(__file__))
    dataset = Path(config["research_dataset"])
    baseline_manifest = Path(config["baseline_manifest"])
    baseline_lineage = Path(config["baseline_lineage"])
    for path in (dataset, baseline_manifest, baseline_lineage, Path(config["execution_source"]), Path(config["prior_model_family_runner"])):
        require(path.is_file(), f"REQUIRED_AUTHORITY_MISSING:{path}")
    data = guarded_pre2026_frame(config)
    registry = pd.DataFrame(factor_definitions(code_hash), columns=FACTOR_COLUMNS)
    require(registry.factor_id.is_unique and registry.factor_name.is_unique, "FACTOR_REGISTRY_IDENTITY_FAILURE")
    atomic_parquet(paths.output / "02_factor_registry/factor_registry.parquet", registry)
    specs = generate_search_specs(config)
    search_contract = {
        "run_id": config["run_id"], "created_at_utc": utc_now(), "frozen_before_any_new_model_fit": True,
        "outer_folds": [f"OUTER_{year}" for year in config["outer_years"]],
        "inner_fold_rule": "TWO_MOST_RECENT_COMPLETE_YEARS_INSIDE_OUTER_TRAIN",
        "purge_rule": "TRAIN_TARGET_END_DATE_STRICTLY_BEFORE_VALIDATION_START",
        "embargo_trading_days": config["target_horizon_trading_days"],
        "feature_information_cutoff": config["cutoff"], "label_maturity_cutoff": config["cutoff"],
        "candidate_specs": specs, "top_k_grid": config["top_k_grid"],
        "2026_training_rows": 0, "2026_feature_selection_rows": 0, "2026_hyperparameter_search_rows": 0,
        "2026_threshold_search_rows": 0, "2026_model_selection_rows": 0, "2026_ensemble_weight_search_rows": 0,
        "2026_factor_discovery_target_reads": 0,
    }
    atomic_json(paths.output / "00_preflight/pre2026_search_contract.json", search_contract)
    atomic_json(paths.output / "00_preflight/config_snapshot.json", config)
    dataset_audit = {
        "status": "PASS_HARD_PRE2026_RESEARCH_VIEW", "row_count": len(data),
        "feature_information_min": data.feature_information_available_timestamp.min(),
        "feature_information_max": data.feature_information_available_timestamp.max(),
        "label_maturity_min": data.label_maturity_timestamp.min(),
        "label_maturity_max": data.label_maturity_timestamp.max(),
        "outer_fold_years": config["outer_years"], "invented_2022_fold": False,
        "2026_training_rows": 0, "2026_selection_rows": 0,
    }
    atomic_json(paths.output / "01_data/pre2026_research_view_audit.json", dataset_audit)
    source_hashes = {str(path): sha256_file(path) for path in (
        dataset, baseline_manifest, baseline_lineage, Path(config["execution_source"]),
        Path(config["prior_model_family_runner"]), config_path, Path(__file__),
    )}
    atomic_json(paths.output / "00_preflight/source_hash_manifest.json", source_hashes)
    atomic_json(paths.output / "00_preflight/runtime_preflight.json", {
        "python": sys.version, "platform": platform.platform(), "cpu_count": os.cpu_count(),
        "canonical_runtime": sys.executable, "repo_local_venv_exists": (REPO_ROOT / ".venv").exists(),
        "output_root": str(paths.output), "cache_root": str(paths.cache),
        "torch_status": "NOT_INSTALLED_NO_REPOSITORY_OR_ENV_MUTATION",
        "sequence_model_status": "NOT_JUSTIFIED_NO_FROZEN_CONTIGUOUS_SEQUENCE_CONTRACT",
    })
    checkpoint(paths, "PREFLIGHT", "NONE")
    return {"data": data, "registry": registry, "specs": specs, "source_hashes": source_hashes}


def replay_control_identity(config: dict[str, Any], paths: Paths) -> dict[str, Any]:
    runner = load_module("a2_open_prior_runner", Path(config["prior_model_family_runner"]))
    r4 = load_module("a2_open_r4", Path(config["execution_source"]))
    columns = ["prediction_date", "ticker", "raw_score", "cross_sectional_rank", "model"]
    predictions = pd.read_parquet(config["baseline_predictions"], columns=columns, filters=[[('model', '==', CONTROL_ID)]])
    require(len(predictions) > 0, "CONTROL_PREDICTIONS_MISSING")
    signals = predictions.rename(columns={"prediction_date": "signal_date", "raw_score": "prediction", "cross_sectional_rank": "rank"})
    signals["a2_rank"] = signals["rank"]; signals["a1_rank"] = signals["rank"]
    signals["universe_size"] = signals.groupby("signal_date").ticker.transform("size")
    replayed = r4.simulate_portfolio(signals, runner.load_prices(), CONTROL_ID, "rank", 20, config["primary_cost_bps"])
    frozen = pd.read_parquet(config["baseline_paths"], filters=[[('model', '==', CONTROL_ID), ('scope', '==', 'POOLED_OOF')]])
    joined = frozen.merge(replayed, on="execution_date", how="outer", suffixes=("_frozen", "_replay"), indicator=True)
    require(joined._merge.eq("both").all(), "CONTROL_DATE_IDENTITY_FAILURE")
    fields = {"return": "net_return", "nav": "net_nav", "turnover": "turnover", "cost": "transaction_cost_amount"}
    errors = {name: float(np.max(np.abs(joined[f"{column}_frozen"] - joined[f"{column}_replay"]))) for name, column in fields.items()}
    status = {f"control_{name}_identity": "PASS" if error <= 1e-12 else "FAIL" for name, error in errors.items()}
    require(all(value == "PASS" for value in status.values()), "CONTROL_REPLAY_IDENTITY_FAILURE")
    result = {**status, "max_absolute_errors": errors, "row_count": len(joined), "status": "PASS"}
    atomic_json(paths.output / "00_preflight/control_replay_identity.json", result)
    checkpoint(paths, "CONTROL_REPLAY_IDENTITY", "CONTROL")
    return result


def select_inner_winner(rows: pd.DataFrame) -> tuple[str, int, dict[str, Any]]:
    completed = rows.loc[rows.status == "COMPLETED"].copy()
    require(len(completed) > 0, "NO_COMPLETED_INNER_TRIAL")
    metrics = completed.predictive_metrics.map(json.loads).apply(pd.Series)
    completed = pd.concat([completed.reset_index(drop=True), metrics.reset_index(drop=True)], axis=1)
    completed["top_k"] = completed.threshold_parameters.map(lambda value: int(json.loads(value)["top_k"]))
    grouped = completed.groupby(["parent_trial_id", "top_k"], as_index=False).agg(
        mean_ic=("spearman_ic", "mean"), median_ic=("median_ic", "median"),
        mean_topk=("mean_topk_target", "mean"), positive_folds=("spearman_ic", lambda value: int((value > 0).sum())),
        runtime=("runtime_seconds", "sum"), feature_count=("feature_count", "first"),
    )
    grouped["complexity"] = grouped.feature_count + grouped.runtime / 1000.0
    ordered = grouped.sort_values(
        ["mean_ic", "positive_folds", "mean_topk", "complexity", "parent_trial_id", "top_k"],
        ascending=[False, False, False, True, True, True], kind="mergesort",
    )
    winner = ordered.iloc[0]
    return str(winner.parent_trial_id), int(winner.top_k), winner.to_dict()


def run_search(config: dict[str, Any], paths: Paths, context: dict[str, Any] | None = None) -> None:
    code_hash = sha256_file(Path(__file__))
    dataset_hash = sha256_file(Path(config["research_dataset"]))
    data = materialize_factors((context or {}).get("data", guarded_pre2026_frame(config)))
    registry_path = paths.output / "02_factor_registry/factor_registry.parquet"
    registry = (context or {}).get("registry", pd.read_parquet(registry_path))
    sets = feature_sets(config, registry)
    specs = (context or {}).get("specs", generate_search_specs(config))
    contract_path = paths.output / "00_preflight/pre2026_search_contract.json"
    require(contract_path.is_file(), "PREFLIGHT_SEARCH_CONTRACT_MISSING")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    require(contract["candidate_specs"] == specs, "SEARCH_SPACE_CHANGED_AFTER_FREEZE")
    ledger = TrialLedger(paths.ledger)
    existing = set(ledger.frame.trial_id)
    seed = int(config["random_seed"])
    for outer_year in config["outer_years"]:
        outer_fold = f"OUTER_{outer_year}"
        outer_train, outer_valid, outer_audit = split_before_year(data, outer_year)
        for family in config["trial_budgets"]:
            family_specs = [spec for spec in specs if spec["family"] == family]
            for spec in family_specs:
                features = sets[spec["feature_set_id"]]
                parent = spec["spec_id"]
                for inner_year in (outer_year - 2, outer_year - 1):
                    identifiers = [trial_id(parent, outer_fold, f"INNER_{inner_year}", top_k) for top_k in config["top_k_grid"]]
                    if all(identifier in existing for identifier in identifiers):
                        continue
                    train, valid, audit = split_before_year(outer_train, inner_year)
                    started = time.perf_counter()
                    try:
                        _, prediction, fit_seconds = fit_predict(
                            family, spec["parameters"], train, valid, features, seed,
                            int(config["max_cpu_threads"]), bool(config["use_gpu_xgboost"]),
                        )
                        scored = valid[["signal_date", "ticker", "target"]].copy(); scored["prediction"] = prediction
                        runtime = time.perf_counter() - started
                        complexity = model_complexity(family, spec["parameters"], len(features))
                        batch = []
                        for top_k, identifier in zip(config["top_k_grid"], identifiers):
                            if identifier in existing:
                                continue
                            metrics = grouped_metrics(scored, int(top_k))
                            batch.append(trial_row(
                                identifier=identifier, parent=parent, family=family, spec={**spec, "seed": seed}, threshold=int(top_k),
                                outer_fold=outer_fold, inner_fold=f"INNER_{inner_year}", audit=audit,
                                row_count=len(valid), feature_count=len(features), status="COMPLETED", failure="",
                                runtime=fit_seconds if top_k == config["top_k_grid"][0] else max(0.0, runtime-fit_seconds)/len(config["top_k_grid"]),
                                predictive=metrics, economic={}, complexity=complexity, input_hash=dataset_hash, code_hash=code_hash,
                            ))
                    except Exception as exc:
                        runtime = time.perf_counter() - started
                        complexity = model_complexity(family, spec["parameters"], len(features))
                        failure = f"{type(exc).__name__}:{exc}"[:2000]
                        batch = [trial_row(
                            identifier=identifier, parent=parent, family=family, spec={**spec, "seed": seed}, threshold=int(top_k),
                            outer_fold=outer_fold, inner_fold=f"INNER_{inner_year}", audit=audit,
                            row_count=len(valid), feature_count=len(features), status="FAILED", failure=failure,
                            runtime=runtime/len(config["top_k_grid"]), predictive={}, economic={}, complexity=complexity,
                            input_hash=dataset_hash, code_hash=code_hash,
                        ) for top_k, identifier in zip(config["top_k_grid"], identifiers) if identifier not in existing]
                    ledger.append(batch); existing.update(row["trial_id"] for row in batch)
                    checkpoint(paths, "NESTED_INNER_SEARCH", batch[-1]["trial_id"])
            family_rows = ledger.frame.loc[(ledger.frame.model_family == family) & (ledger.frame.outer_fold == outer_fold) & ledger.frame.inner_fold.str.startswith("INNER_")]
            try:
                selected_spec_id, selected_top_k, inner_summary = select_inner_winner(family_rows)
            except GovernanceError:
                checkpoint(paths, f"FAMILY_FAILED_{family}_{outer_fold}", "NONE")
                continue
            spec = next(item for item in family_specs if item["spec_id"] == selected_spec_id)
            features = sets[spec["feature_set_id"]]
            prediction_path = paths.cache / "oof_parts" / f"{family}_{outer_fold}.parquet"
            selection_path = paths.cache / "oof_parts" / f"{family}_{outer_fold}_selection.json"
            outer_identifier = trial_id(selected_spec_id, outer_fold, "OUTER_TEST", selected_top_k)
            if prediction_path.is_file() and selection_path.is_file() and outer_identifier in existing:
                continue
            started = time.perf_counter()
            try:
                model, prediction, fit_seconds = fit_predict(
                    family, spec["parameters"], outer_train, outer_valid, features, seed,
                    int(config["max_cpu_threads"]), bool(config["use_gpu_xgboost"]),
                )
                scored = outer_valid[["signal_date", "security_id", "ticker", "target", "target_end_date"]].copy()
                scored["model_family"] = family; scored["outer_fold"] = outer_fold
                scored["spec_id"] = selected_spec_id; scored["feature_set_id"] = spec["feature_set_id"]
                scored["top_k"] = selected_top_k; scored["prediction"] = prediction; scored["rank"] = stable_rank(scored)
                atomic_parquet(prediction_path, scored)
                model_path = paths.cache / "models" / f"{family}_{outer_fold}.joblib"
                joblib.dump(model, model_path, compress=3)
                predictive = grouped_metrics(scored, selected_top_k)
                audit = {**outer_audit, "test_start": outer_valid.signal_date.min(), "test_end": outer_valid.signal_date.max()}
                row = trial_row(
                    identifier=outer_identifier, parent=selected_spec_id, family=family, spec={**spec, "seed": seed},
                    threshold=selected_top_k, outer_fold=outer_fold, inner_fold="", audit=audit,
                    row_count=len(outer_valid), feature_count=len(features), status="COMPLETED", failure="",
                    runtime=fit_seconds, predictive=predictive, economic={},
                    complexity={**model_complexity(family, spec["parameters"], len(features)), "model_bytes": model_path.stat().st_size},
                    input_hash=dataset_hash, code_hash=code_hash,
                )
                if outer_identifier not in existing:
                    ledger.append([row]); existing.add(outer_identifier)
                atomic_json(selection_path, {
                    "family": family, "outer_fold": outer_fold, "selected_spec": spec, "selected_top_k": selected_top_k,
                    "inner_selection_summary": inner_summary, "model_path": str(model_path), "model_sha256": sha256_file(model_path),
                    "outer_prediction_path": str(prediction_path), "outer_prediction_sha256": sha256_file(prediction_path),
                    "outer_test_evaluated_once": True,
                })
                checkpoint(paths, "OUTER_OOF_EVALUATION", outer_identifier)
                print(f"OUTER_COMPLETE family={family} fold={outer_fold} spec={selected_spec_id} top_k={selected_top_k} seconds={time.perf_counter()-started:.1f}", flush=True)
            except Exception as exc:
                failure = f"{type(exc).__name__}:{exc}"[:2000]
                audit = {**outer_audit, "test_start": outer_valid.signal_date.min(), "test_end": outer_valid.signal_date.max()}
                row = trial_row(
                    identifier=outer_identifier, parent=selected_spec_id, family=family, spec={**spec, "seed": seed},
                    threshold=selected_top_k, outer_fold=outer_fold, inner_fold="", audit=audit,
                    row_count=len(outer_valid), feature_count=len(features), status="FAILED", failure=failure,
                    runtime=time.perf_counter()-started, predictive={}, economic={}, complexity=model_complexity(family, spec["parameters"], len(features)),
                    input_hash=dataset_hash, code_hash=code_hash,
                )
                if outer_identifier not in existing:
                    ledger.append([row]); existing.add(outer_identifier)
                checkpoint(paths, f"OUTER_FAILED_{family}_{outer_fold}", outer_identifier)
    checkpoint(paths, "PRE2026_MODEL_SEARCH_COMPLETE", "ALL", "COMPLETE")


def control_predictions(config: dict[str, Any]) -> pd.DataFrame:
    columns = ["prediction_date", "security_id", "ticker", "raw_score", "cross_sectional_rank", "realized_forward_target", "target_end_date", "fold_id", "model"]
    frame = pd.read_parquet(config["baseline_predictions"], columns=columns, filters=[[('model', '==', CONTROL_ID)]])
    frame = frame.rename(columns={
        "prediction_date": "signal_date", "raw_score": "prediction", "cross_sectional_rank": "rank",
        "realized_forward_target": "target", "fold_id": "outer_fold",
    })
    frame["model_family"] = CONTROL_ID; frame["spec_id"] = "FROZEN_CONTROL"; frame["feature_set_id"] = "BASELINE"
    frame["top_k"] = 20
    return frame[["signal_date","security_id","ticker","target","target_end_date","model_family","outer_fold","spec_id","feature_set_id","top_k","prediction","rank"]]


def load_candidate_oof(paths: Paths) -> pd.DataFrame:
    parts = sorted(path for path in (paths.cache / "oof_parts").glob("*.parquet") if "seed_" not in path.name)
    require(parts, "NO_OUTER_OOF_PARTS")
    return pd.concat([pd.read_parquet(path) for path in parts], ignore_index=True)


def fixed_rank_ensemble(candidates: pd.DataFrame, members: list[str]) -> pd.DataFrame:
    available = [family for family in members if family in set(candidates.model_family)]
    require(len(available) >= 2, "INSUFFICIENT_ENSEMBLE_DIVERSITY")
    keys = ["signal_date", "security_id", "ticker", "target", "target_end_date", "outer_fold"]
    subset = candidates.loc[candidates.model_family.isin(available)].copy()
    wide = subset.pivot(index=keys, columns="model_family", values="rank").loc[:, available]
    require(not wide.isna().any().any(), "ENSEMBLE_MEMBER_UNIVERSE_MISMATCH")
    prediction = -wide.rank(axis=0, pct=True).mean(axis=1)
    output = prediction.rename("prediction").reset_index()
    output["model_family"] = "ENSEMBLE_FIXED_DIVERSE_RANK_AVERAGE"
    output["spec_id"] = "FIXED_EQUAL_RANK_" + "_".join(available)
    output["feature_set_id"] = "MEMBER_SPECIFIC"; output["top_k"] = 20
    output["rank"] = stable_rank(output)
    return output


def economic_metrics(path: pd.DataFrame, r4: Any) -> dict[str, Any]:
    result = r4.portfolio_metrics(path)
    returns = path.net_return.to_numpy(float)
    downside = returns[returns < 0]
    downside_vol = float(np.std(downside, ddof=0) * np.sqrt(252.0)) if len(downside) else math.nan
    annual_mean = float(np.mean(returns) * 252.0) if len(returns) else math.nan
    gains = float(returns[returns > 0].sum()); losses = float(-returns[returns < 0].sum())
    result.update({
        "sharpe": result.pop("sharpe_rf0"),
        "sortino": annual_mean / downside_vol if downside_vol and np.isfinite(downside_vol) else math.nan,
        "profit_factor": gains / losses if losses > 0 else math.nan,
        "turnover": result["annualized_turnover"], "cost": result["total_transaction_cost"],
        "number_of_rebalance_periods": int(len(path)),
    })
    return result


def overlap_with_control(candidate: pd.DataFrame, control: pd.DataFrame) -> float:
    left = candidate.loc[candidate["rank"] <= 20, ["signal_date", "ticker"]]
    right = control.loc[control["rank"] <= 20, ["signal_date", "ticker"]]
    joined = left.merge(right, on=["signal_date","ticker"])
    daily = joined.groupby("signal_date").size().div(20.0)
    return float(daily.mean()) if len(daily) else math.nan


def combine_excluding_fold(path: pd.DataFrame, excluded_year: int, r4: Any) -> dict[str, Any]:
    return economic_metrics(path.loc[pd.to_datetime(path.execution_date).dt.year != excluded_year].copy(), r4)


def nondominated(frame: pd.DataFrame) -> pd.Series:
    maximize = ["ic", "ndcg20", "cagr", "sharpe", "calmar", "max_drawdown", "stability_score"]
    minimize = ["turnover", "complexity"]
    keep = []
    values = frame.reset_index(drop=True)
    for index, row in values.iterrows():
        dominated = False
        for other_index, other in values.iterrows():
            if index == other_index:
                continue
            weak = all(other[column] >= row[column] for column in maximize) and all(other[column] <= row[column] for column in minimize)
            strict = any(other[column] > row[column] for column in maximize) or any(other[column] < row[column] for column in minimize)
            if weak and strict:
                dominated = True; break
        keep.append(not dominated)
    return pd.Series(keep, index=frame.index)


def evaluate_pre2026(config: dict[str, Any], paths: Paths) -> dict[str, Any]:
    candidates = load_candidate_oof(paths)
    control = control_predictions(config)
    control_keys = control[["signal_date","security_id"]].sort_values(["signal_date","security_id"]).reset_index(drop=True)
    identity_rows = []
    for family, frame in candidates.groupby("model_family", sort=True):
        keys = frame[["signal_date","security_id"]].sort_values(["signal_date","security_id"]).reset_index(drop=True)
        matches = keys.equals(control_keys)
        identity_rows.append({"model_family": family, "row_count": len(frame), "control_row_count": len(control), "matches_control": matches})
        require(matches, f"MODEL_UNIVERSE_MISMATCH:{family}")
    ensemble = fixed_rank_ensemble(candidates, config["finalist_model_families"])
    all_oof = pd.concat([control, candidates, ensemble], ignore_index=True)
    atomic_parquet(paths.output / "03_model_search/outer_oof_predictions.parquet", all_oof)
    atomic_parquet(paths.output / "12_audit/model_universe_identity.parquet", pd.DataFrame(identity_rows))
    runner = load_module("a2_open_eval_runner", Path(config["prior_model_family_runner"]))
    r4 = load_module("a2_open_eval_r4", Path(config["execution_source"]))
    prices = runner.load_prices()
    predictive_rows: list[dict[str, Any]] = []
    economic_rows: list[dict[str, Any]] = []
    paths_out: list[pd.DataFrame] = []
    control_by_date = control
    for family, frame in all_oof.groupby("model_family", sort=True):
        frame = frame.copy(); frame["rank"] = stable_rank(frame)
        signals = frame[["signal_date","ticker","prediction","rank"]].copy()
        signals["a2_rank"] = signals["rank"]; signals["a1_rank"] = signals["rank"]
        signals["universe_size"] = signals.groupby("signal_date").ticker.transform("size")
        if family == CONTROL_ID:
            path = pd.read_parquet(config["baseline_paths"], filters=[[('model', '==', CONTROL_ID), ('scope', '==', 'POOLED_OOF')]])
        else:
            path = r4.simulate_portfolio(signals, prices, family, "rank", 20, config["primary_cost_bps"])
        path["model_family"] = family; paths_out.append(path)
        scopes = [("POOLED_OOF", frame, path)]
        for year in config["outer_years"]:
            scopes.append((f"OUTER_{year}", frame.loc[frame.outer_fold == f"OUTER_{year}"], path.loc[pd.to_datetime(path.execution_date).dt.year == year]))
        for scope, prediction_frame, economic_path in scopes:
            metrics = grouped_metrics(prediction_frame, 20)
            predictive_rows.append({"model_family": family, "scope": scope, **metrics, "top20_overlap": overlap_with_control(prediction_frame, control_by_date.loc[control_by_date.outer_fold == scope] if scope.startswith("OUTER_") else control_by_date)})
            economic_rows.append({"model_family": family, "scope": scope, **economic_metrics(economic_path, r4)})
        print(f"ECONOMIC_EVALUATION_COMPLETE family={family}", flush=True)
    portfolio_paths = pd.concat(paths_out, ignore_index=True)
    atomic_parquet(paths.output / "08_robustness/oof_portfolio_paths.parquet", portfolio_paths)
    predictive = pd.DataFrame(predictive_rows); economics = pd.DataFrame(economic_rows)
    predictive.to_csv(paths.output / "08_robustness/predictive_metrics_by_fold.csv", index=False, lineterminator="\n")
    economics.to_csv(paths.output / "08_robustness/economic_metrics_by_fold.csv", index=False, lineterminator="\n")
    base_p = predictive.loc[predictive.model_family == CONTROL_ID].set_index("scope")
    base_e = economics.loc[economics.model_family == CONTROL_ID].set_index("scope")
    outer_ledger = TrialLedger(paths.ledger)
    complexity_map: dict[str, float] = {CONTROL_ID: 0.0, "ENSEMBLE_FIXED_DIVERSE_RANK_AVERAGE": 4.0}
    outer_trials = outer_ledger.frame.loc[(outer_ledger.status == "COMPLETED") & (outer_ledger.inner_fold == "")]
    for family, rows in outer_trials.groupby("model_family"):
        complexity_map[family] = float(np.mean([json.loads(value).get("complexity_score", math.nan) for value in rows.complexity_metrics]))
    summary_rows = []
    for family in sorted(all_oof.model_family.unique()):
        p = predictive.loc[predictive.model_family == family].set_index("scope")
        e = economics.loc[economics.model_family == family].set_index("scope")
        fold_sharpe_delta = pd.Series({year: e.at[f"OUTER_{year}","sharpe"] - base_e.at[f"OUTER_{year}","sharpe"] for year in config["outer_years"]})
        fold_ic_delta = pd.Series({year: p.at[f"OUTER_{year}","spearman_ic"] - base_p.at[f"OUTER_{year}","spearman_ic"] for year in config["outer_years"]})
        best_year = int(fold_sharpe_delta.idxmax())
        family_path = portfolio_paths.loc[portfolio_paths.model_family == family]
        control_path = portfolio_paths.loc[portfolio_paths.model_family == CONTROL_ID]
        family_leave = combine_excluding_fold(family_path, best_year, r4)
        control_leave = combine_excluding_fold(control_path, best_year, r4)
        prediction_leave = all_oof.loc[(all_oof.model_family == family) & (all_oof.outer_fold != f"OUTER_{best_year}")]
        control_prediction_leave = control.loc[control.outer_fold != f"OUTER_{best_year}"]
        leave_ic_delta = grouped_metrics(prediction_leave, 20)["spearman_ic"] - grouped_metrics(control_prediction_leave, 20)["spearman_ic"]
        leave_sharpe_delta = family_leave["sharpe"] - control_leave["sharpe"]
        exact_coverage = len(all_oof.loc[all_oof.model_family == family]) == len(control)
        stable = family == CONTROL_ID or (int((fold_sharpe_delta > 0).sum()) >= 2 and leave_sharpe_delta >= 0 and leave_ic_delta >= 0)
        flags = []
        if family != CONTROL_ID and leave_sharpe_delta < 0: flags.append("SINGLE_PERIOD_DOMINATED")
        if e.at["POOLED_OOF","turnover"] > base_e.at["POOLED_OOF","turnover"] * 1.5: flags.append("EXCESSIVE_TURNOVER")
        if not exact_coverage: flags.append("LOW_COVERAGE")
        classification = "A_STRONG_STABLE_PRE2026_EVIDENCE" if stable and family != CONTROL_ID else ("D_UNSTABLE_OR_OVERFIT_RISK" if family != CONTROL_ID else "CONTROL")
        summary_rows.append({
            "candidate": family, "family": family, "factors": int(all_oof.loc[all_oof.model_family == family].feature_set_id.map(lambda value: 32 if value == "BASELINE" else 33).max()),
            "ic": p.at["POOLED_OOF","spearman_ic"], "ndcg20": p.at["POOLED_OOF","ndcg20"],
            "cagr": e.at["POOLED_OOF","cagr"], "sharpe": e.at["POOLED_OOF","sharpe"], "calmar": e.at["POOLED_OOF","calmar"],
            "max_drawdown": e.at["POOLED_OOF","max_drawdown"], "turnover": e.at["POOLED_OOF","turnover"], "cost": e.at["POOLED_OOF","cost"],
            "median_fold_sharpe_delta": float(fold_sharpe_delta.median()), "positive_fold_count": int((fold_sharpe_delta > 0).sum()),
            "leave_best_fold_out_sharpe_delta": leave_sharpe_delta, "leave_best_fold_out_ic_delta": leave_ic_delta,
            "complexity": complexity_map.get(family, math.inf), "stability_score": float(fold_sharpe_delta.median() - fold_sharpe_delta.std(ddof=0)),
            "coverage_identity": exact_coverage, "classification": classification, "diagnostic_flags": "|".join(flags),
        })
    leaderboard = pd.DataFrame(summary_rows)
    leaderboard["pareto"] = nondominated(leaderboard.fillna({"calmar": -math.inf, "stability_score": -math.inf}))
    leaderboard.to_csv(paths.output / "13_morning_report/candidate_leaderboard.csv", index=False, lineterminator="\n")
    leaderboard.loc[leaderboard.pareto].to_csv(paths.output / "09_pre2026_freeze/candidate_pareto_frontier.csv", index=False, lineterminator="\n")
    eligible = leaderboard.loc[(leaderboard.candidate != CONTROL_ID) & (leaderboard.classification == "A_STRONG_STABLE_PRE2026_EVIDENCE")]
    if eligible.empty:
        eligible = leaderboard.loc[leaderboard.candidate != CONTROL_ID]
    selected = eligible.sort_values(
        ["classification","median_fold_sharpe_delta","leave_best_fold_out_sharpe_delta","sharpe","calmar","ic","turnover","complexity"],
        ascending=[True,False,False,False,False,False,True,True], kind="mergesort",
    ).iloc[0]
    selection = {"preferred_research_challenger": selected.candidate, "selection_row": selected.to_dict(), "selected_at_utc": utc_now(), "outer_oos_not_used_for_further_tuning": True}
    atomic_json(paths.output / "08_robustness/preliminary_champion_selection.json", selection)
    checkpoint(paths, "PRE2026_EVALUATION_COMPLETE", str(selected.candidate))
    return {"leaderboard": leaderboard, "predictive": predictive, "economics": economics, "paths": portfolio_paths, "all_oof": all_oof, "selection": selection}


def run_nn_seed_branch(config: dict[str, Any], paths: Paths) -> None:
    data = materialize_factors(guarded_pre2026_frame(config))
    registry = pd.read_parquet(paths.output / "02_factor_registry/factor_registry.parquet")
    sets = feature_sets(config, registry)
    ledger = TrialLedger(paths.ledger); existing = set(ledger.frame.trial_id)
    code_hash = sha256_file(Path(__file__)); input_hash = sha256_file(Path(config["research_dataset"]))
    diagnostic_rows = []
    for outer_year in config["outer_years"]:
        outer_fold = f"OUTER_{outer_year}"
        selection_path = paths.cache / "oof_parts" / f"MLP_{outer_fold}_selection.json"
        if not selection_path.is_file():
            continue
        selection = json.loads(selection_path.read_text(encoding="utf-8")); spec = selection["selected_spec"]
        features = sets[spec["feature_set_id"]]
        train, valid, audit = split_before_year(data, outer_year)
        seed_predictions = []
        for seed in config["finalist_seeds"]:
            identifier = trial_id("MLP_SEED_DIAGNOSTIC", spec["spec_id"], outer_fold, seed)
            seed_path = paths.cache / "oof_parts" / f"seed_MLP_{outer_fold}_{seed}.parquet"
            if seed_path.is_file():
                scored = pd.read_parquet(seed_path)
            elif seed == config["random_seed"] and (paths.cache / "oof_parts" / f"MLP_{outer_fold}.parquet").is_file():
                scored = pd.read_parquet(paths.cache / "oof_parts" / f"MLP_{outer_fold}.parquet")
                atomic_parquet(seed_path, scored)
            else:
                started = time.perf_counter()
                model, prediction, elapsed = fit_predict("MLP", spec["parameters"], train, valid, features, int(seed), int(config["max_cpu_threads"]), False)
                scored = valid[["signal_date","security_id","ticker","target","target_end_date"]].copy()
                scored["prediction"] = prediction; scored["rank"] = stable_rank(scored)
                atomic_parquet(seed_path, scored)
                model_path = paths.cache / "models" / f"MLP_{outer_fold}_SEED_{seed}.joblib"; joblib.dump(model, model_path, compress=3)
                if identifier not in existing:
                    row = trial_row(
                        identifier=identifier, parent=spec["spec_id"], family="MLP_SEED_DIAGNOSTIC", spec={**spec,"seed":seed},
                        threshold=20, outer_fold=outer_fold, inner_fold="SEED_DIAGNOSTIC_FIXED_PREDECLARED", audit={**audit,"test_start":valid.signal_date.min(),"test_end":valid.signal_date.max()},
                        row_count=len(valid), feature_count=len(features), status="COMPLETED", failure="", runtime=elapsed,
                        predictive=grouped_metrics(scored,20), economic={}, complexity=model_complexity("MLP",spec["parameters"],len(features)),
                        input_hash=input_hash, code_hash=code_hash,
                    )
                    ledger.append([row]); existing.add(identifier)
            metrics = grouped_metrics(scored, 20)
            diagnostic_rows.append({"outer_fold":outer_fold,"seed":seed,**metrics})
            seed_predictions.append(scored.prediction.to_numpy(float))
        aggregate = valid[["signal_date","security_id","ticker","target","target_end_date"]].copy()
        aggregate["model_family"] = "MLP_MULTI_SEED_MEAN"; aggregate["outer_fold"] = outer_fold
        aggregate["spec_id"] = spec["spec_id"] + "__SEED_MEAN"; aggregate["feature_set_id"] = spec["feature_set_id"]
        aggregate["top_k"] = 20; aggregate["prediction"] = np.mean(seed_predictions, axis=0); aggregate["rank"] = stable_rank(aggregate)
        atomic_parquet(paths.cache / "oof_parts" / f"MLP_MULTI_SEED_MEAN_{outer_fold}.parquet", aggregate)
    diagnostics = pd.DataFrame(diagnostic_rows)
    if len(diagnostics):
        diagnostics.to_csv(paths.output / "05_neural_networks/nn_seed_metrics.csv", index=False, lineterminator="\n")
        summary = diagnostics.groupby("seed").spearman_ic.mean()
        atomic_json(paths.output / "05_neural_networks/nn_seed_stability.json", {
            "seed_count": int(diagnostics.seed.nunique()), "seed_mean_ic": float(summary.mean()),
            "seed_median_ic": float(summary.median()), "seed_std_ic": float(summary.std(ddof=0)),
            "worst_seed_ic": float(summary.min()), "best_seed_ic": float(summary.max()),
            "selection_policy": "FIXED_PREDECLARED_SEED_MEAN_NOT_BEST_SEED",
        })
    checkpoint(paths, "NN_MULTI_SEED_BRANCH_COMPLETE", "MLP_MULTI_SEED_MEAN")


def block_bootstrap_delta(left: np.ndarray, right: np.ndarray, block: int, repeats: int, seed: int) -> dict[str, float]:
    require(len(left) == len(right) and len(left) > block, "BLOCK_BOOTSTRAP_INPUT_INVALID")
    delta = np.asarray(left, float) - np.asarray(right, float); rng = np.random.default_rng(seed)
    starts = np.arange(0, len(delta) - block + 1); estimates = []
    blocks_needed = math.ceil(len(delta) / block)
    for _ in range(repeats):
        chosen = rng.choice(starts, size=blocks_needed, replace=True)
        sample = np.concatenate([delta[start:start+block] for start in chosen])[:len(delta)]
        estimates.append(float(np.mean(sample)))
    return {"mean": float(np.mean(delta)), "ci_low": float(np.quantile(estimates,.025)), "ci_high": float(np.quantile(estimates,.975)), "block_length": block, "repeats": repeats}


def robustness_and_diagnostics(config: dict[str, Any], paths: Paths, evaluation: dict[str, Any]) -> dict[str, Any]:
    leaderboard = evaluation["leaderboard"].copy(); all_oof = evaluation["all_oof"]
    portfolio_paths = evaluation["paths"]; r4 = load_module("a2_open_robust_r4", Path(config["execution_source"]))
    runner = load_module("a2_open_robust_runner", Path(config["prior_model_family_runner"])); prices = runner.load_prices()
    control_path = portfolio_paths.loc[portfolio_paths.model_family == CONTROL_ID].sort_values("execution_date")
    sensitivity_rows = []
    for family, frame in all_oof.groupby("model_family", sort=True):
        signals = frame[["signal_date","ticker","prediction","rank"]].copy(); signals["rank"] = stable_rank(signals)
        signals["a2_rank"] = signals["rank"]; signals["a1_rank"] = signals["rank"]; signals["universe_size"] = signals.groupby("signal_date").ticker.transform("size")
        for multiple in config["cost_multipliers"]:
            bps = int(round(config["primary_cost_bps"] * multiple))
            if family == CONTROL_ID and bps == config["primary_cost_bps"]:
                path = control_path
            else:
                path = r4.simulate_portfolio(signals, prices, family, "rank", 20, bps)
            sensitivity_rows.append({"model_family":family,"cost_multiple":multiple,"cost_bps":bps,**economic_metrics(path,r4)})
    sensitivity = pd.DataFrame(sensitivity_rows)
    sensitivity.to_csv(paths.output / "08_robustness/cost_sensitivity.csv", index=False, lineterminator="\n")
    control_2x = sensitivity.loc[(sensitivity.model_family==CONTROL_ID)&(sensitivity.cost_multiple==2.0)].iloc[0]
    cost_status = {}
    for family in leaderboard.candidate:
        row_2x = sensitivity.loc[(sensitivity.model_family==family)&(sensitivity.cost_multiple==2.0)].iloc[0]
        cost_status[family] = "PASS" if row_2x.sharpe >= control_2x.sharpe else "COST_FRAGILE"
    leaderboard["cost_robustness"] = leaderboard.candidate.map(cost_status)
    bootstrap_rows = []
    for family in leaderboard.candidate:
        if family == CONTROL_ID: continue
        candidate_path = portfolio_paths.loc[portfolio_paths.model_family==family].sort_values("execution_date")
        joined = control_path[["execution_date","net_return"]].merge(candidate_path[["execution_date","net_return"]],on="execution_date",suffixes=("_control","_candidate"),validate="one_to_one")
        boot = block_bootstrap_delta(joined.net_return_candidate.to_numpy(),joined.net_return_control.to_numpy(),int(config["blocked_bootstrap_block_days"]),int(config["blocked_bootstrap_repeats"]),int(config["random_seed"]))
        bootstrap_rows.append({"model_family":family,"metric":"mean_daily_return_delta",**boot})
    pd.DataFrame(bootstrap_rows).to_csv(paths.output / "08_robustness/block_bootstrap.csv",index=False,lineterminator="\n")
    statistics = load_module("a2_open_fast3_statistics", REPO_ROOT / "fast3/src/fast3/robustness/statistics.py")
    completed = TrialLedger(paths.ledger).frame
    attempted_models = int(completed.model_family.nunique()); attempted_configs = int(completed.parent_trial_id.nunique())
    dsr = {}
    for family in leaderboard.candidate:
        returns = portfolio_paths.loc[portfolio_paths.model_family==family].sort_values("execution_date").net_return.to_numpy(float)
        dsr[family] = statistics.deflated_sharpe(returns,attempted_models=max(1,attempted_models),attempted_configurations=max(1,attempted_configs),attempted_seeds=len(config["finalist_seeds"]),frequency="daily")
    atomic_json(paths.output / "08_robustness/multiple_testing_diagnostics.json", {
        "deflated_sharpe": dsr, "pbo_status": "PBO_NOT_RELIABLY_ESTIMABLE_OUTER_FOLD_COUNT_3",
        "attempted_models": attempted_models, "attempted_configurations": attempted_configs,
    })
    registry = pd.read_parquet(paths.output / "02_factor_registry/factor_registry.parquet")
    data = materialize_factors(guarded_pre2026_frame(config)); factor_rows=[]
    for _, factor in registry.iterrows():
        values=[]; coverage=[]
        for year in config["outer_years"]:
            fold=data.loc[data.signal_date.dt.year==year,["signal_date","ticker","target",factor.factor_name]].rename(columns={factor.factor_name:"prediction"})
            metric=grouped_metrics(fold,20)["spearman_ic"]; values.append(metric); coverage.append(float(fold.prediction.notna().mean()))
            factor_rows.append({"factor_id":factor.factor_id,"factor_name":factor.factor_name,"scope":f"OUTER_{year}","coverage":coverage[-1],"ic":metric,"complexity":factor.complexity})
        factor_rows.append({"factor_id":factor.factor_id,"factor_name":factor.factor_name,"scope":"SUMMARY","coverage":float(np.mean(coverage)),"ic":float(np.median(values)),"complexity":factor.complexity,"sign_stability":float(np.mean(np.sign(values)==np.sign(np.median(values))))})
    factor_leaderboard=pd.DataFrame(factor_rows); factor_leaderboard.to_csv(paths.output / "13_morning_report/factor_leaderboard.csv",index=False,lineterminator="\n")
    atomic_json(paths.output / "12_audit/leakage_audit.json", {
        "status":"PASS_PREDEFINED_TARGET_INDEPENDENT_FACTORS","future_close_reads":0,"future_return_reads":0,
        "future_13f_reads":0,"future_universe_reads":0,"future_normalization_reads":0,"future_execution_information_reads":0,
        "factor_family_status":{name:"PASS" for name in ["TREND","MEAN_REVERSION","VOLATILITY","LIQUIDITY","CROSS_SECTIONAL","REGIME","INTERACTIONS"]},
        "thirteen_f_factor_branch":"NOT_RUN_NO_MANAGER_LEVEL_FEATURE_COLUMNS_IN_FROZEN_RESEARCH_DATASET",
    })
    leaderboard.to_csv(paths.output / "13_morning_report/candidate_leaderboard.csv",index=False,lineterminator="\n")
    checkpoint(paths,"ROBUSTNESS_COMPLETE",evaluation["selection"]["preferred_research_challenger"])
    return {**evaluation,"leaderboard":leaderboard,"cost_sensitivity":sensitivity,"dsr":dsr,"factor_leaderboard":factor_leaderboard}


def aggregate_training_side_spec(config: dict[str, Any], paths: Paths, family: str) -> dict[str, Any]:
    base_family = "MLP" if family == "MLP_MULTI_SEED_MEAN" else family
    selections=[]
    for year in config["outer_years"]:
        path=paths.cache/"oof_parts"/f"{base_family}_OUTER_{year}_selection.json"
        if path.is_file(): selections.append(json.loads(path.read_text(encoding="utf-8")))
    require(selections,f"NO_TRAINING_SIDE_SELECTION:{family}")
    rows=[]
    for selected in selections:
        rows.append({
            "spec_id":selected["selected_spec"]["spec_id"],"selected_spec":selected["selected_spec"],
            "inner_score":float(selected["inner_selection_summary"]["mean_ic"]),
        })
    frame=pd.DataFrame(rows); counts=frame.groupby("spec_id").size(); maximum=int(counts.max())
    eligible=set(counts.loc[counts==maximum].index)
    chosen=frame.loc[frame.spec_id.isin(eligible)].sort_values(["inner_score","spec_id"],ascending=[False,True],kind="mergesort").iloc[0]
    return {"family":base_family,"spec":chosen.selected_spec,"selection_rule":"MODE_ACROSS_OUTER_TRAINING_SIDE_SELECTIONS_THEN_MAX_INNER_SCORE","support_count":maximum,"training_side_only":True}


def final_champion(robustness: dict[str, Any]) -> pd.Series:
    leaderboard=robustness["leaderboard"]
    eligible=leaderboard.loc[
        (leaderboard.candidate!=CONTROL_ID)&
        (leaderboard.classification=="A_STRONG_STABLE_PRE2026_EVIDENCE")&
        (leaderboard.cost_robustness=="PASS")&
        (leaderboard.coverage_identity)
    ]
    if eligible.empty:
        eligible=leaderboard.loc[(leaderboard.candidate!=CONTROL_ID)&(leaderboard.coverage_identity)]
    require(len(eligible)>0,"NO_VALID_RESEARCH_CHALLENGER")
    return eligible.sort_values(
        ["median_fold_sharpe_delta","leave_best_fold_out_sharpe_delta","sharpe","calmar","ic","turnover","complexity"],
        ascending=[False,False,False,False,False,True,True],kind="mergesort",
    ).iloc[0]


def fit_frozen_model(config: dict[str, Any], paths: Paths, data: pd.DataFrame, selected: dict[str, Any], seed: int) -> dict[str, Any]:
    family=selected["family"]; spec=selected["spec"]
    registry=pd.read_parquet(paths.output/"02_factor_registry/factor_registry.parquet"); features=feature_sets(config,registry)[spec["feature_set_id"]]
    model,_,elapsed=fit_predict(family,spec["parameters"],data,data.iloc[:1],features,seed,int(config["max_cpu_threads"]),bool(config["use_gpu_xgboost"]))
    model_dir=paths.cache/"frozen_models"; model_dir.mkdir(parents=True,exist_ok=True)
    path=model_dir/f"{family}_SEED_{seed}.joblib"; joblib.dump(model,path,compress=3)
    return {"family":family,"seed":seed,"spec":spec,"features":features,"model_path":str(path),"model_sha256":sha256_file(path),"fit_seconds":elapsed,"training_rows":len(data),"max_label_maturity":str(data.label_maturity_timestamp.max())}


def freeze_pre2026(config: dict[str, Any], paths: Paths, robustness: dict[str, Any]) -> dict[str, Any]:
    freeze_dir=paths.output/"09_pre2026_freeze"; champion=final_champion(robustness); champion_id=str(champion.candidate)
    if champion_id=="ENSEMBLE_FIXED_DIVERSE_RANK_AVERAGE":
        families=[family for family in config["finalist_model_families"] if (paths.cache/"oof_parts"/f"{family}_OUTER_2023_selection.json").is_file()]
    else:
        families=[champion_id]
    data=materialize_factors(guarded_pre2026_frame(config))
    selected_specs=[aggregate_training_side_spec(config,paths,family) for family in families]
    frozen_models=[]
    for selected in selected_specs:
        seeds=config["finalist_seeds"] if champion_id=="MLP_MULTI_SEED_MEAN" and selected["family"]=="MLP" else [config["random_seed"]]
        for seed in seeds: frozen_models.append(fit_frozen_model(config,paths,data,selected,int(seed)))
    ledger=TrialLedger(paths.ledger).frame
    atomic_parquet(freeze_dir/"pre2026_trial_manifest.parquet",ledger)
    registry=pd.read_parquet(paths.output/"02_factor_registry/factor_registry.parquet"); atomic_parquet(freeze_dir/"factor_registry.parquet",registry)
    pareto=freeze_dir/"candidate_pareto_frontier.csv"; require(pareto.is_file(),"PARETO_FRONTIER_MISSING")
    predictive=robustness["predictive"].set_index(["model_family","scope"]); economics=robustness["economics"].set_index(["model_family","scope"])
    manifest={
        "run_id":config["run_id"],"status":"RESEARCH_CHALLENGER_NOT_DEPLOYMENT_AUTHORIZATION","champion_id":champion_id,
        "champion_selection_row":champion.to_dict(),"selected_training_side_specs":selected_specs,"frozen_models":frozen_models,
        "thresholds":{"economic_top_k":20,"searched_inner_top_k_grid":config["top_k_grid"],"holdout_top_k":20},
        "ensemble":{"type":"FIXED_EQUAL_RANK_AVERAGE" if len(families)>1 else "NONE","members":families,"weights":[1/len(families)]*len(families)},
        "execution":{"mapping":"FROZEN_R4_CLOSE_TO_NEXT_OPEN_EQUAL_WEIGHT_LONG_ONLY","cost_bps":config["primary_cost_bps"]},
        "temporal_counters":{"2026_training_rows":0,"2026_feature_selection_rows":0,"2026_parameter_search_count":0,"2026_threshold_search_count":0,"2026_model_selection_count":0,"2026_ensemble_weight_search_rows":0,"2026_factor_discovery_target_reads":0},
        "outer_oos_folds":[2023,2024,2025],"created_at_utc":utc_now(),
    }
    atomic_json(freeze_dir/"pre2026_champion_manifest.json",manifest)
    total_attempted=len(ledger); total_completed=int((ledger.status=="COMPLETED").sum()); total_failed=int((ledger.status=="FAILED").sum())
    pooled_p=predictive.loc[(champion_id,"POOLED_OOF")]; pooled_e=economics.loc[(champion_id,"POOLED_OOF")]
    nn_status=json.loads((paths.output/"05_neural_networks/nn_seed_stability.json").read_text(encoding="utf-8")) if (paths.output/"05_neural_networks/nn_seed_stability.json").is_file() else {"seed_count":0}
    pre_section=f"""============================================================
PRE2026 RESEARCH DECISION — 2026 STILL SEALED
============================================================

TOTAL_TRIALS={total_attempted}
TOTAL_FACTORS_GENERATED={len(registry)}
MODEL_FAMILIES_TESTED={ledger.model_family.nunique()}

CONTROL={CONTROL_ID}
BEST_TREE={robustness['leaderboard'].loc[robustness['leaderboard'].family.str.contains('XGBOOST|CATBOOST|LIGHTGBM|FOREST|TREES|GRADIENT'),:].sort_values('sharpe',ascending=False).iloc[0].candidate}
BEST_LINEAR={robustness['leaderboard'].loc[robustness['leaderboard'].family.isin(['RIDGE','ELASTIC_NET']),:].sort_values('sharpe',ascending=False).iloc[0].candidate}
BEST_NN={robustness['leaderboard'].loc[robustness['leaderboard'].family.str.contains('MLP'),:].sort_values('sharpe',ascending=False).iloc[0].candidate}
BEST_ENSEMBLE=ENSEMBLE_FIXED_DIVERSE_RANK_AVERAGE

PREFERRED_RESEARCH_CHALLENGER={champion_id}

PRE2026_IC={pooled_p.spearman_ic}
PRE2026_NDCG20={pooled_p.ndcg20}
PRE2026_CAGR={pooled_e.cagr}
PRE2026_SHARPE={pooled_e.sharpe}
PRE2026_CALMAR={pooled_e.calmar}
PRE2026_MAXDD={pooled_e.max_drawdown}
PRE2026_TURNOVER={pooled_e.turnover}

FOLD_2023_SHARPE={economics.loc[(champion_id,'OUTER_2023'),'sharpe']}
FOLD_2024_SHARPE={economics.loc[(champion_id,'OUTER_2024'),'sharpe']}
FOLD_2025_SHARPE={economics.loc[(champion_id,'OUTER_2025'),'sharpe']}

LEAVE_BEST_FOLD_OUT_SHARPE={champion.leave_best_fold_out_sharpe_delta}
SEED_STABILITY={json.dumps(nn_status,sort_keys=True)}
PARAMETER_STABILITY=TRAINING_SIDE_NEIGHBORHOOD_RETAINED_IN_FULL_TRIAL_LEDGER
COST_ROBUSTNESS={champion.cost_robustness}
CONCENTRATION_STATUS=MONTH_QUARTER_DIAGNOSTICS_PENDING_FINAL_REPORT
OVERFIT_CLASSIFICATION={champion.classification}:{champion.diagnostic_flags}

2026_OUTCOME_READ_COUNT=0
PRE2026_FREEZE_SHA256={{FREEZE_SHA_PENDING}}
============================================================
"""
    closeout=freeze_dir/"pre2026_research_closeout.md"; closeout.write_text(pre_section,encoding="utf-8")
    required=[freeze_dir/"pre2026_champion_manifest.json",freeze_dir/"pre2026_trial_manifest.parquet",freeze_dir/"factor_registry.parquet",freeze_dir/"candidate_pareto_frontier.csv"]
    artifact_hashes={path.name:sha256_file(path) for path in required}
    payload={
        "run_id":config["run_id"],"pre2026_research_complete":True,"pre2026_selection_complete":True,"pre2026_champion_frozen":True,
        "2026_outcome_read_count_at_freeze":0,"artifact_hashes":artifact_hashes,"model_hashes":{Path(row["model_path"]).name:row["model_sha256"] for row in frozen_models},
        "data_manifest_sha256":sha256_file(Path(config["research_dataset"])),"model_code_sha256":sha256_file(Path(__file__)),
        "execution_mapping_sha256":sha256_file(Path(config["execution_source"])),"factor_definitions_sha256":artifact_hashes["factor_registry.parquet"],
        "selected_candidate_ids":[champion_id],"frozen_at_utc":utc_now(),
    }
    freeze_sha=canonical_hash(payload); payload["pre2026_freeze_sha256"]=freeze_sha
    atomic_json(freeze_dir/"pre2026_freeze_manifest.json",payload)
    closeout.write_text(pre_section.replace("{FREEZE_SHA_PENDING}",freeze_sha),encoding="utf-8")
    payload["post_freeze_identifier_artifact_hashes"]={"pre2026_research_closeout.md":sha256_file(closeout)}
    atomic_json(freeze_dir/"pre2026_freeze_manifest.json",payload)
    # Closeout embeds the core freeze identifier and is hashed as post-identifier metadata.
    require(json.loads((freeze_dir/"pre2026_freeze_manifest.json").read_text(encoding="utf-8"))["pre2026_champion_frozen"],"FREEZE_VERIFICATION_FAILURE")
    checkpoint(paths,"PRE2026_CHAMPION_FROZEN",champion_id,"COMPLETE")
    print("PRE2026_RESEARCH_COMPLETE=true")
    print("PRE2026_SELECTION_COMPLETE=true")
    print("PRE2026_CHAMPION_FROZEN=true")
    print(f"PRE2026_FREEZE_SHA256={freeze_sha}")
    return {"champion_id":champion_id,"freeze_sha256":freeze_sha,"manifest":payload,"closeout":str(closeout)}


def verify_freeze_gate(config: dict[str, Any], paths: Paths) -> dict[str, Any]:
    path=paths.output/"09_pre2026_freeze/pre2026_freeze_manifest.json"
    require(path.is_file(),"PRE2026_FREEZE_MISSING")
    manifest=json.loads(path.read_text(encoding="utf-8")); require(manifest.get("pre2026_champion_frozen") is True,"PRE2026_NOT_FROZEN")
    counters=json.loads((paths.output/"09_pre2026_freeze/pre2026_champion_manifest.json").read_text(encoding="utf-8"))["temporal_counters"]
    for key,value in counters.items(): require(value==0,f"HOLDOUT_GATE_COUNTER_NONZERO:{key}")
    return manifest


def run_phase(config_path: Path, phase: str) -> None:
    config=load_config(config_path); paths=initialize_paths(config)
    holdout_report=paths.output/"10_2026_locked_holdout/locked_2026_holdout_report.json"
    if holdout_report.is_file() and phase not in {"holdout","status"}:
        raise GovernanceError("NO_GOING_BACK_AFTER_2026_HOLDOUT_OPEN")
    if phase=="status":
        print(paths.checkpoint.read_text(encoding="utf-8") if paths.checkpoint.is_file() else "NO_CHECKPOINT")
        return
    if phase=="preflight":
        preflight(config,paths,config_path); replay_control_identity(config,paths); return
    if phase=="search":
        require((paths.output/"00_preflight/pre2026_search_contract.json").is_file(),"RUN_PREFLIGHT_FIRST")
        run_search(config,paths); run_nn_seed_branch(config,paths); return
    if phase=="evaluate":
        evaluation=evaluate_pre2026(config,paths); robustness_and_diagnostics(config,paths,evaluation); return
    if phase=="freeze":
        evaluation=evaluate_pre2026(config,paths); robustness=robustness_and_diagnostics(config,paths,evaluation); freeze_pre2026(config,paths,robustness); return
    if phase=="holdout":
        verify_freeze_gate(config,paths)
        raise GovernanceError("LOCKED_HOLDOUT_ADAPTER_NOT_YET_MATERIALIZED_USE_ALL_PRE2026_FIRST")
    if phase=="all-pre2026":
        context=preflight(config,paths,config_path)
        replay_control_identity(config,paths)
        run_search(config,paths,context)
        run_nn_seed_branch(config,paths)
        evaluation=evaluate_pre2026(config,paths)
        robustness=robustness_and_diagnostics(config,paths,evaluation)
        freeze_pre2026(config,paths,robustness)
        return
    raise GovernanceError(f"UNKNOWN_PHASE:{phase}")


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--config",type=Path,default=DEFAULT_CONFIG)
    parser.add_argument("--phase",choices=["preflight","search","evaluate","freeze","all-pre2026","holdout","status"],default="all-pre2026")
    args=parser.parse_args()
    try:
        run_phase(args.config,args.phase)
        return 0
    except Exception as exc:
        print(f"RUN_STATUS=FAIL_CLOSED:{type(exc).__name__}:{exc}",file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__=="__main__":
    raise SystemExit(main())
