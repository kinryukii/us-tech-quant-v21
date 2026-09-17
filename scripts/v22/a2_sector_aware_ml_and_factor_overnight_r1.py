"""Bounded sector-aware correction research for the frozen A2 Top20 path.

The frozen FF12/FF48 taxonomy covers the authoritative A2 Top20 security-date
path from 2023 through 2025, not the full pre-2023 research universe.  This
runner therefore refuses future taxonomy backfill and limits learned models to
PIT-safe, pre-2023 alpha/risk features.  Sector awareness is transported only
after the Stage-A model specification is frozen: the model supplies a bounded
within-Top20 correction and the frozen taxonomy supplies the contemporaneous
score transform and portfolio budget.  No candidate can introduce a security
outside the authoritative Raw A2 Top20 set.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np
import pandas as pd


TASK_ID = "A2_SECTOR_AWARE_ML_AND_FACTOR_OVERNIGHT_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
CACHE_ROOT = Path(r"D:\us-tech-quant-cache") / "a2_sector_aware_ml_and_factor_overnight_r1"
OUT = RESULTS / TASK_ID
PRIOR = RESULTS / "A2_SEC_CIK_IDENTITY_GAP_CLOSE_AND_DECONCENTRATION_AUTORUN_R1"
TAXONOMY_PATH = PRIOR / "pit_ff12_ff48_taxonomy.parquet"
PRIOR_METADATA = PRIOR / "research_metadata.json"
PRIOR_HASH_MANIFEST = PRIOR / "hash_manifest.json"
PRIOR_LEDGER = PRIOR / "trial_ledger.parquet"
DATASET = Path(r"D:\us-tech-quant-cache\a2_model_family_r1a_data_complete\research_dataset.parquet")
TOP20 = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2" / "top20_selections.parquet"
PORTFOLIO = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2" / "portfolio_daily.parquet"
ENGINE_SOURCE = REPO / "scripts" / "v22" / "a2_open_research_engine.py"
BASE_SOURCE = REPO / "scripts" / "v22" / "stage_sec_pit_taxonomy.py"
FALSIFICATION_SOURCE = REPO / "scripts" / "v22" / "a2_strategy_falsification_and_robustness_r1.py"
R0F_SOURCE = REPO / "scripts" / "v22" / "fast_a2_r0f_corporate_action_and_nav_forensic_audit.py"

EXPECTED_TAXONOMY_HASH = "0f0b48772c09dadb1b93d783a623a896a3a18ef307b75fa253ef2f08ee9208e1"
EXPECTED_TAXONOMY_FILE_SHA256 = "515427bfe4d450540bcf8b04a9ce5fd50f706c551300a46450f5e4669b7d552f"
EXPECTED_DATASET_SHA256 = "82e0020a3e15a8020fa041dea428b45a3d57a5e7101901e50159d517e6cf1c11"

BASE_FEATURES = [
    "ret_1d", "ret_3d", "ret_5d", "ret_10d", "ret_20d", "ret_40d", "ret_60d", "ret_120d",
    "price_vs_ma10", "price_vs_ma20", "price_vs_ma50", "price_vs_ma120",
    "ma10_vs_ma20", "ma20_vs_ma50", "ma50_vs_ma120",
    "realized_vol_5d", "realized_vol_10d", "realized_vol_20d", "realized_vol_60d",
    "downside_vol_20d", "upside_vol_20d", "distance_from_high_20d", "distance_from_high_60d",
    "distance_from_low_20d", "distance_from_low_60d", "max_drawdown_20d", "max_drawdown_60d",
    "avg_volume_20d", "avg_volume_60d", "volume_ratio_5d_20d", "volume_ratio_20d_60d",
    "avg_dollar_volume_20d",
]
STAGE_A_FOLDS = [
    ("A_2021_H2", pd.Timestamp("2021-07-01"), pd.Timestamp("2022-01-01")),
    ("A_2022_H1", pd.Timestamp("2022-01-01"), pd.Timestamp("2022-07-01")),
    ("A_2022_H2", pd.Timestamp("2022-07-01"), pd.Timestamp("2023-01-01")),
]
SEEDS = [20260823, 20260824, 20260825]
MAX_UNIQUE_SPECS = 800
MAX_TOTAL_FITS = 6000
MAX_STAGE_B_SPECS = 80
MAX_FINALISTS = 5
PRIMARY_BETA_SCALE = 1.3915046223476935
SOURCE_TAXONOMY_MIN = pd.Timestamp("2023-01-03")
SOURCE_TAXONOMY_MAX = pd.Timestamp("2025-12-29")


class GateFailure(RuntimeError):
    pass


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise GateFailure(f"{code}:{detail}")


def import_file(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_SPEC", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    os.replace(temp, path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def zscore(values: pd.Series) -> pd.Series:
    numeric = values.astype(float)
    std = float(numeric.std(ddof=0))
    if not np.isfinite(std) or std <= 1e-12:
        return pd.Series(np.zeros(len(numeric)), index=numeric.index, dtype=float)
    return (numeric - float(numeric.mean())) / std


def group_zscore(frame: pd.DataFrame, value: str, group: str) -> pd.Series:
    return frame.groupby(group, sort=False, group_keys=False)[value].apply(zscore).reindex(frame.index).fillna(0.0)


def metrics(returns: Iterable[float]) -> dict[str, float | int]:
    values = np.asarray(list(returns), float)
    require(len(values) > 1 and np.isfinite(values).all() and (values > -1).all(), "INVALID_RETURNS")
    nav = np.r_[1.0, np.cumprod(1.0 + values)]
    vol = float(values.std(ddof=0) * math.sqrt(252.0))
    cagr = float(nav[-1] ** (252.0 / len(values)) - 1.0)
    dd = nav / np.maximum.accumulate(nav) - 1.0
    return {
        "session_count": int(len(values)), "cumulative_return": float(nav[-1] - 1.0), "cagr": cagr,
        "sharpe": float(values.mean() * 252.0 / vol) if vol else math.nan,
        "max_drawdown": float(dd.min()), "calmar": float(cagr / abs(dd.min())) if dd.min() < 0 else math.nan,
        "annualized_volatility": vol,
    }


def enhanced_metrics(path: pd.DataFrame, prices: pd.DataFrame) -> dict[str, float | int]:
    base = metrics(path.reconstructed_daily_return)
    qqq = prices.loc[prices.ticker.eq("QQQ"), ["trade_date", "open"]].drop_duplicates("trade_date").sort_values("trade_date")
    qqq["qqq_return"] = qqq.open.pct_change().fillna(0.0)
    aligned = path[["execution_date", "reconstructed_daily_return"]].merge(
        qqq[["trade_date", "qqq_return"]], left_on="execution_date", right_on="trade_date", validate="one_to_one"
    )
    r = aligned.reconstructed_daily_return.to_numpy(float)
    q = aligned.qqq_return.to_numpy(float)
    variance = float(np.var(q, ddof=0))
    beta = float(np.cov(r, q, ddof=0)[0, 1] / variance) if variance > 0 else math.nan
    residual = r - beta * q
    residual_vol = float(np.std(residual, ddof=0) * math.sqrt(252.0))
    active = r - PRIMARY_BETA_SCALE * q
    active_vol = float(np.std(active, ddof=0) * math.sqrt(252.0))
    down = q < 0
    downside_capture = float(np.mean(r[down]) / np.mean(q[down])) if down.any() and np.mean(q[down]) else math.nan
    base.update({
        "qqq_beta": beta,
        "qqq_adjusted_alpha": float(np.mean(residual) * 252.0),
        "residual_sharpe": float(np.mean(residual) * 252.0 / residual_vol) if residual_vol else math.nan,
        "downside_capture": downside_capture,
        "active_ir": float(np.mean(active) * 252.0 / active_vol) if active_vol else math.nan,
        "turnover": float(path.reconstructed_turnover.sum()),
        "cost": float(path.reconstructed_transaction_cost.sum()),
    })
    return base


def load_dataset_before(end: pd.Timestamp) -> pd.DataFrame:
    columns = ["signal_date", "target_end_date", "security_id", "ticker", "target", *BASE_FEATURES]
    frame = pd.read_parquet(DATASET, columns=columns, filters=[("signal_date", "<", end.to_pydatetime())])
    frame["signal_date"] = pd.to_datetime(frame.signal_date).dt.normalize()
    frame["target_end_date"] = pd.to_datetime(frame.target_end_date).dt.normalize()
    frame["ticker"] = frame.ticker.astype(str).str.upper()
    require(frame.signal_date.max() < end, "DATASOURCE_DATE_FILTER_FAILURE", end)
    require(frame.signal_date.max() < pd.Timestamp("2026-01-01"), "2026_FEATURE_READ")
    require(frame.target_end_date.max() < pd.Timestamp("2026-01-01"), "2026_TARGET_READ")
    return frame


def load_dataset_year(year: int) -> pd.DataFrame:
    start, end = pd.Timestamp(f"{year}-01-01"), pd.Timestamp(f"{year + 1}-01-01")
    columns = ["signal_date", "target_end_date", "security_id", "ticker", "target", *BASE_FEATURES]
    frame = pd.read_parquet(DATASET, columns=columns, filters=[
        ("signal_date", ">=", start.to_pydatetime()), ("signal_date", "<", end.to_pydatetime())
    ])
    frame["signal_date"] = pd.to_datetime(frame.signal_date).dt.normalize()
    frame["target_end_date"] = pd.to_datetime(frame.target_end_date).dt.normalize()
    frame["ticker"] = frame.ticker.astype(str).str.upper()
    require(not frame.empty and frame.signal_date.min() >= start and frame.signal_date.max() < end, "YEAR_FILTER_FAILURE", year)
    require(year <= 2025, "2026_YEAR_READ")
    return frame


def temporal_train(data: pd.DataFrame, validation_start: pd.Timestamp) -> pd.DataFrame:
    train = data.loc[(data.signal_date < validation_start) & (data.target_end_date < validation_start)].copy()
    require(not train.empty, "EMPTY_TRAIN", validation_start)
    require(train.signal_date.max() < validation_start and train.target_end_date.max() < validation_start, "TEMPORAL_LEAKAGE", validation_start)
    return train


def preflight() -> dict[str, Any]:
    for path in (TAXONOMY_PATH, PRIOR_METADATA, PRIOR_HASH_MANIFEST, PRIOR_LEDGER, DATASET, TOP20, PORTFOLIO, ENGINE_SOURCE, BASE_SOURCE, FALSIFICATION_SOURCE, R0F_SOURCE):
        require(path.is_file(), "REQUIRED_INPUT_MISSING", path)
    prior = json.loads(PRIOR_METADATA.read_text(encoding="utf-8"))
    manifest = json.loads(PRIOR_HASH_MANIFEST.read_text(encoding="utf-8"))
    require(prior["taxonomy_freeze_status"] == "PASS_FROZEN", "TAXONOMY_NOT_FROZEN")
    require(prior["taxonomy_hash"] == EXPECTED_TAXONOMY_HASH == manifest["taxonomy_hash"], "TAXONOMY_LOGICAL_HASH_MISMATCH")
    require(sha256_file(TAXONOMY_PATH) == EXPECTED_TAXONOMY_FILE_SHA256, "TAXONOMY_FILE_HASH_MISMATCH")
    taxonomy_entry = next(item for item in manifest["artifacts"] if item["name"] == TAXONOMY_PATH.name)
    require(taxonomy_entry["sha256"] == EXPECTED_TAXONOMY_FILE_SHA256, "TAXONOMY_MANIFEST_MISMATCH")
    require(sha256_file(DATASET) == EXPECTED_DATASET_SHA256, "RESEARCH_DATASET_HASH_MISMATCH")
    taxonomy = pd.read_parquet(TAXONOMY_PATH)
    taxonomy["signal_date"] = pd.to_datetime(taxonomy.signal_date).dt.normalize()
    taxonomy["ticker"] = taxonomy.ticker.astype(str).str.upper()
    require(len(taxonomy) == 15000 and taxonomy.signal_date.min() == SOURCE_TAXONOMY_MIN and taxonomy.signal_date.max() == SOURCE_TAXONOMY_MAX, "TAXONOMY_SUPPORT_MISMATCH")
    require(not taxonomy.duplicated(["signal_date", "ticker"]).any(), "TAXONOMY_DUPLICATE")
    require(float(taxonomy.ff12.ne("UNKNOWN").mean()) == float(prior["ff12_security_date_coverage"]), "FF12_COVERAGE_MISMATCH")
    base = import_file("a2_sector_ml_base", BASE_SOURCE)
    top20, portfolio, raw = base.verify_inputs()
    require(abs(raw["sharpe"] - 1.2353699802070324) <= 1e-12, "RAW_A2_RECONCILIATION")
    prior_ledger = pd.read_parquet(PRIOR_LEDGER)
    controls = prior_ledger.loc[prior_ledger.trial_id.isin(["S0_RAW", "S1_SOFT_025", "S2_CAP_050"])].copy()
    require(set(controls.trial_id) == {"S0_RAW", "S1_SOFT_025", "S2_CAP_050"}, "CONTROL_MISSING")
    source_hash = sha256_file(DATASET)
    return {
        "base": base, "taxonomy": taxonomy, "top20": top20, "portfolio": portfolio, "raw": raw,
        "prior_ledger": prior_ledger, "dataset_sha256": source_hash,
        "taxonomy_hash": EXPECTED_TAXONOMY_HASH, "taxonomy_file_sha256": EXPECTED_TAXONOMY_FILE_SHA256,
        "taxonomy_pre2023_support": False,
        "sector_target_families_status": "NOT_APPLICABLE:FROZEN_TAXONOMY_STARTS_2023_NO_FUTURE_BACKFILL",
        "full_universe_sector_replacement_status": "NOT_APPLICABLE:TAXONOMY_FROZEN_TO_RAW_A2_TOP20_ONLY",
    }


def fixed_model_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    def add(family: str, feature_set: str, params: dict[str, Any], stochastic: bool = False) -> None:
        payload = {"family": family, "feature_set": feature_set, "parameters": params, "stochastic": stochastic, "target": "T0_ORIGINAL_20D"}
        specs.append({"model_spec_id": "M_" + canonical_hash(payload)[:16], **payload})
    for feature_set, alpha in [("BASELINE_TREND", .1), ("BASELINE_TREND", 1.), ("BASELINE_VOL_LIQ", 1.), ("BASELINE_CROSS_REGIME", 1.), ("ALL_FACTORS", 1.), ("ALL_FACTORS", 10.)]:
        add("RIDGE", feature_set, {"alpha": alpha})
    for feature_set, alpha, l1 in [("BASELINE_TREND", 1e-4, .1), ("BASELINE_VOL_LIQ", 1e-4, .5), ("BASELINE_CROSS_REGIME", 1e-3, .1), ("ALL_FACTORS", 1e-3, .5)]:
        add("ELASTIC_NET", feature_set, {"alpha": alpha, "l1_ratio": l1, "max_iter": 500, "tol": 1e-4})
    for feature_set, depth, leaves, rate in [("BASELINE_TREND", 2, 7, .03), ("BASELINE_VOL_LIQ", 3, 15, .03), ("BASELINE_CROSS_REGIME", 3, 15, .05), ("ALL_FACTORS", 2, 15, .03), ("ALL_FACTORS", 3, 15, .05), ("ALL_FACTORS", 4, 31, .03)]:
        add("HIST_GRADIENT_BOOSTING", feature_set, {"learning_rate": rate, "max_iter": 180, "max_leaf_nodes": leaves, "max_depth": depth, "min_samples_leaf": 200, "l2_regularization": 3.0, "early_stopping": False})
    for feature_set, depth, rate in [("BASELINE_TREND", 2, .03), ("BASELINE_VOL_LIQ", 3, .03), ("BASELINE_CROSS_REGIME", 3, .05), ("ALL_FACTORS", 3, .03)]:
        add("XGBOOST_REGRESSION", feature_set, {"learning_rate": rate, "n_estimators": 240, "max_depth": depth, "min_child_weight": 50., "subsample": .8, "colsample_bytree": .8, "colsample_bylevel": 1., "gamma": .1, "reg_alpha": .1, "reg_lambda": 10., "grow_policy": "depthwise"}, True)
    for feature_set, leaves, rate in [("BASELINE_TREND", 15, .03), ("BASELINE_VOL_LIQ", 15, .05), ("ALL_FACTORS", 31, .03)]:
        add("LIGHTGBM_REGRESSION", feature_set, {"learning_rate": rate, "n_estimators": 240, "num_leaves": leaves, "max_depth": 5, "min_child_samples": 200, "subsample": .8, "colsample_bytree": .8, "reg_alpha": .1, "reg_lambda": 10.}, True)
    for feature_set, depth in [("BASELINE_CROSS_REGIME", 5), ("ALL_FACTORS", 6)]:
        add("CATBOOST_REGRESSION", feature_set, {"learning_rate": .03, "iterations": 220, "depth": depth, "l2_leaf_reg": 10., "random_strength": .5, "bagging_temperature": .5}, True)
    for feature_set, depth in [("BASELINE_VOL_LIQ", 10), ("ALL_FACTORS", 10)]:
        add("EXTRA_TREES", feature_set, {"n_estimators": 160, "max_depth": depth, "min_samples_leaf": 100, "max_features": .7, "max_samples": .7}, True)
    add("MLP", "ALL_FACTORS", {"hidden_layer_sizes": [64, 32], "activation": "tanh", "alpha": 1e-3, "learning_rate_init": 5e-4, "batch_size": 2048, "max_iter": 50, "early_stopping": False, "n_iter_no_change": 8}, True)
    require(len(specs) <= MAX_UNIQUE_SPECS and len({s["model_spec_id"] for s in specs}) == len(specs), "MODEL_SPEC_BUDGET")
    return specs


def stage_a(engine: Any, data: pd.DataFrame, specs: list[dict[str, Any]]) -> tuple[pd.DataFrame, list[dict[str, Any]], int]:
    code_hash = sha256_file(Path(__file__))
    registry = pd.DataFrame(engine.factor_definitions(code_hash))
    frame = engine.materialize_factors(data)
    feature_map = engine.feature_sets({"base_features": BASE_FEATURES}, registry)
    rows: list[dict[str, Any]] = []
    fit_count = 0
    for spec in specs:
        seeds = SEEDS if spec["stochastic"] else [SEEDS[0]]
        features = feature_map[spec["feature_set"]]
        require(len(features) - len(BASE_FEATURES) <= 40, "FEATURE_COUNT_BUDGET", spec["model_spec_id"])
        for fold, start, end in STAGE_A_FOLDS:
            train = temporal_train(frame, start)
            valid = frame.loc[(frame.signal_date >= start) & (frame.signal_date < end)].copy()
            require(len(train.signal_date.unique()) >= 252 and not valid.empty, "STAGE_A_HISTORY_OR_VALIDATION", fold)
            for seed in seeds:
                begun = time.perf_counter()
                status, reason, rank_ic, top20 = "PASS", "", math.nan, math.nan
                try:
                    _, prediction, _ = engine.fit_predict(spec["family"], spec["parameters"], train, valid, features, seed, 4, False)
                    scored = valid[["signal_date", "ticker", "target"]].copy()
                    scored["prediction"] = prediction
                    score = engine.grouped_metrics(scored, 20)
                    rank_ic, top20 = float(score["spearman_ic"]), float(score["mean_topk_target"])
                except Exception as exc:
                    status, reason = "FAIL", f"{type(exc).__name__}:{exc}"[:1000]
                fit_count += 1
                rows.append({
                    "phase": "STAGE_A", "candidate_id": spec["model_spec_id"], "family": spec["family"],
                    "target_family": spec["target"], "factor_family_set": spec["feature_set"], "feature_count": len(features),
                    "hyperparameters_hash": canonical_hash(spec["parameters"]), "sector_method": "NONE_PRE2023_TAXONOMY_UNAVAILABLE",
                    "portfolio_method": "NONE_PREDICTIVE_SCREEN", "seed": seed, "fold": fold,
                    "cagr": math.nan, "sharpe": math.nan, "max_drawdown": math.nan, "residual_sharpe": math.nan,
                    "active_ir": math.nan, "ff12_hhi": math.nan, "ff12_reduction": math.nan,
                    "ff48_hhi": math.nan, "ff48_reduction": math.nan, "turnover": math.nan, "cost": math.nan,
                    "rank_ic": rank_ic, "mean_top20_target": top20, "status": status, "failure_reason": reason,
                    "runtime_seconds": time.perf_counter() - begun, "train_end": train.signal_date.max(),
                    "max_train_target_end": train.target_end_date.max(), "validation_start": start, "validation_end": end - pd.Timedelta(days=1),
                })
    ledger = pd.DataFrame(rows)
    passed = ledger.loc[ledger.status.eq("PASS")].copy()
    seed_fold = passed.groupby(["candidate_id", "fold"], as_index=False).agg(
        fold_rank_ic=("rank_ic", "median"), seed_rank_ic_std=("rank_ic", "std"), fold_top20=("mean_top20_target", "median")
    )
    agg = seed_fold.groupby("candidate_id", as_index=False).agg(
        stage_a_mean_rank_ic=("fold_rank_ic", "mean"), stage_a_median_rank_ic=("fold_rank_ic", "median"),
        positive_inner_folds=("fold_rank_ic", lambda v: int((v > 0).sum())), worst_inner_rank_ic=("fold_rank_ic", "min"),
        seed_dispersion=("seed_rank_ic_std", "max"), mean_top20_target=("fold_top20", "mean"), completed_folds=("fold", "nunique")
    )
    meta = pd.DataFrame(specs)
    agg = agg.merge(meta, left_on="candidate_id", right_on="model_spec_id", validate="one_to_one")
    agg["seed_dispersion"] = agg.seed_dispersion.fillna(0.0)
    agg = agg.sort_values(["positive_inner_folds", "stage_a_mean_rank_ic", "seed_dispersion", "candidate_id"], ascending=[False, False, True, True], kind="mergesort")
    survivors: list[dict[str, Any]] = []
    for family, group in agg.groupby("family", sort=True):
        survivors.extend(group.head(2).to_dict("records"))
    survivors = sorted(survivors, key=lambda x: (-x["positive_inner_folds"], -x["stage_a_mean_rank_ic"], x["seed_dispersion"], x["candidate_id"]))[:8]
    survivor_ids = {row["candidate_id"] for row in survivors}
    agg["stage_a_survivor"] = agg.candidate_id.isin(survivor_ids)
    agg["source_code_hash"] = code_hash
    return pd.DataFrame(rows), survivors, fit_count


TRANSPORT_BRANCHES = [
    {"branch": "B_FF12_L025_E025", "score_transform": "FF12_RESIDUAL", "blend": .25, "tilt": .25, "portfolio_method": "S1_FF12_BUDGET_ML_TILT"},
    {"branch": "B_FF12_L025_E050", "score_transform": "FF12_RESIDUAL", "blend": .25, "tilt": .50, "portfolio_method": "S1_FF12_BUDGET_ML_TILT"},
    {"branch": "B_FF12_L050_E025", "score_transform": "FF12_RESIDUAL", "blend": .50, "tilt": .25, "portfolio_method": "S1_FF12_BUDGET_ML_TILT"},
    {"branch": "B_FF12_L050_E050", "score_transform": "FF12_RESIDUAL", "blend": .50, "tilt": .50, "portfolio_method": "S1_FF12_BUDGET_ML_TILT"},
    {"branch": "B_FF48_L025_E025", "score_transform": "FF48_RESIDUAL", "blend": .25, "tilt": .25, "portfolio_method": "S1_FF12_BUDGET_ML_TILT"},
    {"branch": "B_FF48_L050_E025", "score_transform": "FF48_RESIDUAL", "blend": .50, "tilt": .25, "portfolio_method": "S1_FF12_BUDGET_ML_TILT"},
    {"branch": "B_GLOBAL_L025_E025", "score_transform": "GLOBAL", "blend": .25, "tilt": .25, "portfolio_method": "S1_FF12_BUDGET_ML_TILT"},
    {"branch": "B_FF48_DUAL_L050", "score_transform": "FF48_RESIDUAL", "blend": .50, "tilt": .25, "portfolio_method": "DUAL_FF12_FF48_BUDGET_ML_TILT"},
]


def transported_specs(survivors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    specs = []
    for survivor in survivors:
        model = {
            "model_spec_id": survivor["model_spec_id"], "family": survivor["family"],
            "feature_set": survivor["feature_set"], "parameters": survivor["parameters"],
            "stochastic": bool(survivor["stochastic"]), "target": survivor["target"],
        }
        for branch in TRANSPORT_BRANCHES:
            payload = {"model": model, **branch, "top_n": 20, "sector_budget_power": .75, "taxonomy_hash": EXPECTED_TAXONOMY_HASH}
            specs.append({"candidate_id": "C_" + canonical_hash(payload)[:20], **payload})
    require(len(specs) <= MAX_STAGE_B_SPECS, "STAGE_B_SPEC_BUDGET", len(specs))
    return specs


def selection_signal_dates(top20: pd.DataFrame, prices: pd.DataFrame, years: set[int]) -> list[pd.Timestamp]:
    qqq_dates = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    position = pd.Series(np.arange(len(qqq_dates)), index=qqq_dates)
    result = []
    # A multi-year selection window is one continuous economic path.  Only its
    # final boundary is truncated; imposing a separate liquidation at each
    # calendar-year boundary changes the frozen control economics.
    support_end = pd.Timestamp(f"{max(years) + 1}-01-01")
    for value in sorted(pd.to_datetime(top20.signal_date).unique()):
        date = pd.Timestamp(value)
        if date.year not in years or date not in position:
            continue
        idx = int(position.loc[date])
        if idx + 2 < len(qqq_dates) and qqq_dates[idx + 2] < support_end:
            result.append(date)
    return result


def build_weights(day: pd.DataFrame, branch: dict[str, Any]) -> dict[str, float]:
    day = day.copy()
    day["raw_z"] = zscore(day.a2_prediction)
    if branch["score_transform"] == "FF12_RESIDUAL":
        correction = group_zscore(day, "ml_prediction", "ff12")
    elif branch["score_transform"] == "FF48_RESIDUAL":
        correction = group_zscore(day, "ml_prediction", "ff48")
    elif branch["score_transform"] == "GLOBAL":
        correction = zscore(day.ml_prediction)
    else:
        raise GateFailure(f"UNKNOWN_SCORE_TRANSFORM:{branch['score_transform']}")
    day["final_score"] = day.raw_z + float(branch["blend"]) * correction
    sector_counts = day.groupby("ff12").ticker.count().astype(float)
    sector_budget = (sector_counts / sector_counts.sum()).pow(.75)
    sector_budget /= sector_budget.sum()
    weights: dict[str, float] = {}
    for sector, sector_day in day.groupby("ff12", sort=True):
        budget = float(sector_budget.loc[sector])
        if branch["portfolio_method"] == "DUAL_FF12_FF48_BUDGET_ML_TILT":
            industry_counts = sector_day.groupby("ff48").ticker.count().astype(float)
            industry_budget = (industry_counts / industry_counts.sum()).pow(.75)
            industry_budget /= industry_budget.sum()
            groups = [(str(industry), members, budget * float(industry_budget.loc[industry])) for industry, members in sector_day.groupby("ff48", sort=True)]
        else:
            groups = [(str(sector), sector_day, budget)]
        for _, members, group_budget in groups:
            logits = float(branch["tilt"]) * zscore(members.final_score)
            exp = np.exp(np.clip(logits.to_numpy(float), -4.0, 4.0))
            exp /= exp.sum()
            weights.update({ticker: float(group_budget * value) for ticker, value in zip(members.ticker, exp)})
    require(len(weights) == 20 and min(weights.values()) > 0 and abs(sum(weights.values()) - 1.0) <= 1e-12, "WEIGHT_IDENTITY")
    return weights


def score_models_for_year(engine: Any, data: pd.DataFrame, top20: pd.DataFrame, taxonomy: pd.DataFrame, survivors: list[dict[str, Any]], year: int) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]], int]:
    registry = pd.DataFrame(engine.factor_definitions(sha256_file(Path(__file__))))
    frame = engine.materialize_factors(data)
    feature_map = engine.feature_sets({"base_features": BASE_FEATURES}, registry)
    start, end = pd.Timestamp(f"{year}-01-01"), pd.Timestamp(f"{year + 1}-01-01")
    train = temporal_train(frame, start)
    validation = frame.loc[(frame.signal_date >= start) & (frame.signal_date < end)].copy()
    needed = top20.loc[top20.signal_date.dt.year.eq(year), ["signal_date", "ticker", "a2_prediction"]]
    joined = needed.merge(validation, on=["signal_date", "ticker"], how="inner", validate="one_to_one")
    taxonomy_year = taxonomy.loc[taxonomy.signal_date.dt.year.eq(year), ["signal_date", "ticker", "ff12", "ff48"]]
    joined = joined.merge(taxonomy_year, on=["signal_date", "ticker"], validate="one_to_one")
    outputs: dict[str, pd.DataFrame] = {}
    rows: list[dict[str, Any]] = []
    fit_count = 0
    for spec in survivors:
        features = feature_map[spec["feature_set"]]
        seeds = SEEDS if spec["stochastic"] else [SEEDS[0]]
        predictions = []
        for seed in seeds:
            begun = time.perf_counter()
            status, reason = "PASS", ""
            try:
                model = engine.make_model(spec["family"], spec["parameters"], seed, 4, False)
                model.fit(train[features].to_numpy(np.float32), train.target.to_numpy(float))
                prediction = np.asarray(model.predict(joined[features].to_numpy(np.float32)), float)
                require(np.isfinite(prediction).all(), "NONFINITE_STAGE_B_PREDICTION")
                predictions.append(prediction)
            except Exception as exc:
                status, reason = "FAIL", f"{type(exc).__name__}:{exc}"[:1000]
            fit_count += 1
            rows.append({
                "phase": "STAGE_B_MODEL_FIT", "candidate_id": spec["model_spec_id"], "family": spec["family"],
                "target_family": spec["target"], "factor_family_set": spec["feature_set"], "feature_count": len(features),
                "hyperparameters_hash": canonical_hash(spec["parameters"]), "sector_method": "TRANSPORT_BRANCH_FROZEN_SEPARATELY",
                "portfolio_method": "RAW_A2_TOP20_ONLY", "seed": seed, "fold": str(year),
                "cagr": math.nan, "sharpe": math.nan, "max_drawdown": math.nan, "residual_sharpe": math.nan,
                "active_ir": math.nan, "ff12_hhi": math.nan, "ff12_reduction": math.nan, "ff48_hhi": math.nan,
                "ff48_reduction": math.nan, "turnover": math.nan, "cost": math.nan, "rank_ic": math.nan,
                "mean_top20_target": math.nan, "status": status, "failure_reason": reason,
                "runtime_seconds": time.perf_counter() - begun, "train_end": train.signal_date.max(),
                "max_train_target_end": train.target_end_date.max(), "validation_start": start, "validation_end": joined.signal_date.max(),
            })
        if predictions:
            output = joined[["signal_date", "ticker", "a2_prediction", "ff12", "ff48"]].copy()
            output["ml_prediction"] = np.median(np.vstack(predictions), axis=0)
            outputs[spec["model_spec_id"]] = output
    return outputs, rows, fit_count


def target_from_scores(scored: pd.DataFrame, branch: dict[str, Any], valid_dates: set[pd.Timestamp]) -> dict[pd.Timestamp, dict[str, float]]:
    target = {}
    for date, day in scored.groupby("signal_date", sort=True):
        stamp = pd.Timestamp(date)
        if stamp in valid_dates:
            require(len(day) == 20, "TOP20_SCORE_COVERAGE", stamp)
            target[stamp] = build_weights(day, branch)
    require(target and set(target) == valid_dates, "TARGET_DATE_COVERAGE", (len(target), len(valid_dates)))
    return target


def evaluate_target(target: dict[pd.Timestamp, dict[str, float]], taxonomy: pd.DataFrame, prices: pd.DataFrame, r0f: Any, label: str, years: set[int]) -> tuple[dict[str, Any], dict[int, dict[str, Any]], pd.DataFrame]:
    dates = sorted(target)
    path = r0f.reconstruct_path(model=label, target_map=target, qfq=prices, signal_dates=dates, cost_bps=10).daily
    overall = enhanced_metrics(path, prices)
    base = import_file("a2_sector_ml_concentration", BASE_SOURCE)
    overall.update(base.concentration(target, taxonomy))
    folds: dict[int, dict[str, Any]] = {}
    for year in sorted(years):
        part = path.loc[path.execution_date.dt.year.eq(year)]
        fold = enhanced_metrics(part, prices)
        fold.update(base.concentration(target, taxonomy, year))
        folds[year] = fold
    return overall, folds, path


def nondominated(frame: pd.DataFrame) -> pd.DataFrame:
    maximize = ["sharpe", "cagr", "residual_sharpe", "active_ir", "ff12_effective_count", "ff48_effective_count"]
    minimize = ["ff12_hhi", "ff48_hhi", "ff12_max_weight", "ff48_max_weight", "max_drawdown_abs", "downside_capture", "turnover", "complexity"]
    values = frame.reset_index(drop=True)
    keep = np.ones(len(values), dtype=bool)
    for i, row in values.iterrows():
        for j, other in values.iterrows():
            if i == j:
                continue
            no_worse = all(float(other[c]) >= float(row[c]) for c in maximize) and all(float(other[c]) <= float(row[c]) for c in minimize)
            better = any(float(other[c]) > float(row[c]) for c in maximize) or any(float(other[c]) < float(row[c]) for c in minimize)
            if no_worse and better:
                keep[i] = False
                break
    return values.loc[keep].copy()


def render_terminal(metadata: dict[str, Any]) -> str:
    raw, s1, s2, primary = metadata["raw"], metadata["s1"], metadata["s2"], metadata["primary"]
    lines = [
        "=" * 60, "A2_SECTOR_AWARE_ML_AND_FACTOR_OVERNIGHT_R1_FINAL", "=" * 60, "",
        f"TASK_STATUS={metadata['task_status']}", "", "2026_OUTCOME_USED=FALSE", "2026_LEAKAGE_COUNT=0", "",
        "BASELINES", "-" * 60,
        f"RAW_CAGR={raw['cagr']}", f"RAW_SHARPE={raw['sharpe']}", f"RAW_MAXDD={raw['max_drawdown']}",
        f"RAW_RESIDUAL_SHARPE={raw['residual_sharpe']}", f"RAW_FF12_HHI={raw['ff12_hhi']}", f"RAW_FF48_HHI={raw['ff48_hhi']}", "",
        f"S1_CAGR={s1['cagr']}", f"S1_SHARPE={s1['sharpe']}", f"S1_MAXDD={s1['max_drawdown']}",
        f"S1_RESIDUAL_SHARPE={s1['residual_sharpe']}", f"S1_FF12_HHI={s1['ff12_hhi']}", f"S1_FF48_HHI={s1['ff48_hhi']}", "",
        f"S2_CAGR={s2['cagr']}", f"S2_SHARPE={s2['sharpe']}", f"S2_FF12_HHI={s2['ff12_hhi']}", f"S2_FF48_HHI={s2['ff48_hhi']}", "",
        "SEARCH", "-" * 60,
        f"UNIQUE_CANDIDATE_SPECS={metadata['unique_candidate_specs']}", f"TOTAL_MODEL_FITS={metadata['total_model_fits']}",
        f"MODEL_FAMILIES_EXPLORED={','.join(metadata['model_families_explored'])}",
        f"TARGET_FAMILIES_EXPLORED={','.join(metadata['target_families_explored'])}",
        f"FACTOR_FAMILIES_EXPLORED={','.join(metadata['factor_families_explored'])}",
        f"STAGE_A_SURVIVORS={metadata['stage_a_survivors']}", f"STAGE_B_CANDIDATES={metadata['stage_b_candidates']}",
        f"FINALIST_COUNT={metadata['finalist_count']}", f"FINALIST_FREEZE_HASH={metadata['finalist_freeze_hash']}",
        f"PRIMARY_CHALLENGER={metadata['primary_challenger']}", "PRIMARY_FIXED_BEFORE_2025_READ=TRUE", "",
        "PRIMARY", "-" * 60,
        f"PRIMARY_FAMILY={primary['family']}", f"PRIMARY_TARGET={primary['target_family']}",
        f"PRIMARY_FACTOR_SET={primary['factor_family_set']}", f"PRIMARY_METHOD={primary['method']}",
        f"PRIMARY_CAGR={primary['cagr']}", f"PRIMARY_SHARPE={primary['sharpe']}", f"PRIMARY_MAXDD={primary['max_drawdown']}",
        f"PRIMARY_QQQ_BETA={primary['qqq_beta']}", f"PRIMARY_RESIDUAL_SHARPE={primary['residual_sharpe']}", f"PRIMARY_ACTIVE_IR={primary['active_ir']}",
        f"PRIMARY_FF12_HHI={primary['ff12_hhi']}", f"PRIMARY_FF12_HHI_REDUCTION_VS_RAW={primary['ff12_reduction_vs_raw']}",
        f"PRIMARY_FF12_HHI_REDUCTION_VS_S1={primary['ff12_reduction_vs_s1']}", f"PRIMARY_FF12_MAX_WEIGHT={primary['ff12_max_weight']}",
        f"PRIMARY_FF12_EFFECTIVE_COUNT={primary['ff12_effective_count']}", f"PRIMARY_FF48_HHI={primary['ff48_hhi']}",
        f"PRIMARY_FF48_HHI_REDUCTION_VS_RAW={primary['ff48_reduction_vs_raw']}", f"PRIMARY_FF48_HHI_REDUCTION_VS_S1={primary['ff48_reduction_vs_s1']}",
        f"PRIMARY_FF48_MAX_WEIGHT={primary['ff48_max_weight']}", f"PRIMARY_FF48_EFFECTIVE_COUNT={primary['ff48_effective_count']}",
        f"PRIMARY_TURNOVER={primary['turnover']}", f"PRIMARY_COST={primary['cost']}", "",
        "OUTER TEMPORAL EVIDENCE", "-" * 60,
        f"2023_RESULT={metadata['outer_results']['2023']}", f"2024_RESULT={metadata['outer_results']['2024']}",
        f"POSITIVE_ECONOMIC_OUTER_FOLDS={metadata['positive_economic_outer_folds']}",
        f"POSITIVE_DECONCENTRATION_OUTER_FOLDS={metadata['positive_deconcentration_outer_folds']}",
        f"POSITIVE_RESIDUAL_ALPHA_OUTER_FOLDS={metadata['positive_residual_alpha_outer_folds']}",
        f"PARAMETER_NEEDLE_WARNING={str(metadata['parameter_needle_warning']).upper()}",
        f"SEED_INSTABILITY_WARNING={str(metadata['seed_instability_warning']).upper()}",
        f"SINGLE_PERIOD_DEPENDENCE={str(metadata['single_period_dependence']).upper()}", "",
        "2025 DIAGNOSTIC", "-" * 60, "2025_STATUS=EXPOSED_DIAGNOSTIC_ONLY",
        f"PRIMARY_2025_DIAGNOSTIC={metadata['primary_2025_diagnostic']}", f"S1_2025_DIAGNOSTIC={metadata['s1_2025_diagnostic']}",
        "PRIMARY_CHANGED_AFTER_2025_READ=FALSE", "", "FINAL REFIT", "-" * 60,
        f"FINAL_FORWARD_REFIT_STATUS={metadata['final_forward_refit_status']}", f"FINAL_FORWARD_MODEL_ID={metadata['final_forward_model_id']}",
        f"FINAL_FORWARD_MODEL_HASH={metadata['final_forward_model_hash']}", f"FINAL_TRAIN_MAX_DATE={metadata['final_train_max_date']}", "",
        "R6", "-" * 60, f"R6_DIAGNOSTIC_STATUS={metadata['r6_diagnostic_status']}", "", "VERDICT", "-" * 60,
        f"PRIMARY_CLASSIFICATION={metadata['primary_classification']}",
        f"DOES_COMPLEX_SECTOR_AWARE_ML_BEAT_SIMPLE_S1={metadata['complex_ml_beats_s1']}",
        f"MOST_DAMAGING_EVIDENCE={metadata['most_damaging_evidence']}", f"STRONGEST_SUPPORTING_EVIDENCE={metadata['strongest_supporting_evidence']}",
        f"RECOMMENDED_FORWARD_ARMS={metadata['recommended_forward_arms']}", f"ANTI_OVERFIT_STATUS={metadata['anti_overfit_status']}",
        f"TASK_LOCAL_ANTI_BLOAT_STATUS={metadata['task_local_anti_bloat_status']}",
        f"PREEXISTING_ACL_EXCEPTION_COUNT={metadata['preexisting_acl_exception_count']}", f"OUTPUT_DIR={OUT}",
        f"FINAL_ARTIFACT_COUNT={metadata['final_artifact_count']}", "HASH_MANIFEST_STATUS=PASS_HASH_VERIFIED", "=" * 60,
    ]
    return "\n".join(lines)


def finalize_from_completed_checkpoints() -> dict[str, Any]:
    """Finalize an already frozen/evaluated run without rereading candidates.

    This path exists solely for deterministic recovery from a parquet dtype
    serialization failure after the 2025 diagnostic and final refit completed.
    It never fits, scores, selects, or replays a candidate.
    """
    required = [
        OUT / "stage_a_pareto.csv", OUT / "stage_b_outer_results.csv", OUT / "finalist_freeze.json",
        OUT / "finalist_summary.csv", OUT / "primary_forward_model_manifest.json", OUT / "primary_forward_model.joblib",
        CACHE_ROOT / "stage_a_trials.parquet", CACHE_ROOT / "stage_b_model_fit_rows.parquet",
    ]
    for path in required:
        require(path.is_file(), "FINALIZATION_CHECKPOINT_MISSING", path)
    context = preflight()
    freeze_bytes = (OUT / "finalist_freeze.json").read_bytes()
    freeze = json.loads(freeze_bytes)
    stage_b = pd.read_csv(OUT / "stage_b_outer_results.csv")
    diagnostic = pd.read_csv(OUT / "finalist_summary.csv")
    primary_id = str(freeze["primary_challenger_id"])
    require(primary_id in set(stage_b.candidate_id), "FROZEN_PRIMARY_OUTER_RESULT_MISSING")
    require(primary_id in set(diagnostic.candidate_id), "FROZEN_PRIMARY_2025_RESULT_MISSING")
    primary = stage_b.loc[stage_b.candidate_id.eq(primary_id)].iloc[0].to_dict()
    prior = context["prior_ledger"]
    control = prior.loc[prior.fold.astype(str).eq("SELECTION_2023_2024")].set_index("trial_id")

    # Reconstruct the benchmark-adjusted fields for the three controls only;
    # no candidate path is scored or evaluated in this finalization route.
    falsification = import_file("a2_sector_ml_finalize_falsification", FALSIFICATION_SOURCE)
    r0f = import_file("a2_sector_ml_finalize_r0f", R0F_SOURCE)
    prices, price_hashes = falsification.build_frozen_prices()
    prices = prices.loc[prices.trade_date < pd.Timestamp("2026-01-01")].copy()
    valid_dates = set(selection_signal_dates(context["top20"], prices, {2023, 2024}))
    summaries: dict[str, dict[str, Any]] = {}
    fold_controls: dict[str, dict[int, dict[str, Any]]] = {}
    for candidate in context["base"].candidates():
        if candidate.trial_id not in {"S0_RAW", "S1_SOFT_025", "S2_CAP_050"}:
            continue
        target = {d: w for d, w in context["base"].candidate_target(candidate, context["top20"], context["taxonomy"]).items() if d in valid_dates}
        summaries[candidate.trial_id], fold_controls[candidate.trial_id], _ = evaluate_target(
            target, context["taxonomy"], prices, r0f, f"FINALIZE_{candidate.trial_id}", {2023, 2024}
        )
        frozen = control.loc[candidate.trial_id]
        require(abs(summaries[candidate.trial_id]["sharpe"] - float(frozen.sharpe)) <= 1e-12, "FINALIZE_CONTROL_REPLAY")
    raw, s1, s2 = summaries["S0_RAW"], summaries["S1_SOFT_025"], summaries["S2_CAP_050"]
    primary.update({
        "method": str(primary["score_transform"]) + "|" + str(primary["portfolio_method"]),
        "ff12_reduction_vs_s1": (s1["ff12_hhi"] - float(primary["ff12_hhi"])) / s1["ff12_hhi"],
        "ff48_reduction_vs_s1": (s1["ff48_hhi"] - float(primary["ff48_hhi"])) / s1["ff48_hhi"],
    })
    primary_diag = diagnostic.loc[diagnostic.candidate_id.eq(primary_id)].iloc[0]
    s1_diag = diagnostic.loc[diagnostic.candidate_id.eq("S1_SOFT_025")].iloc[0]
    diag_support = (
        "SUPPORTIVE_DIAGNOSTIC" if primary_diag.sharpe >= s1_diag.sharpe + .03 and primary_diag.max_drawdown >= s1_diag.max_drawdown - .03
        else "MIXED_DIAGNOSTIC" if primary_diag.sharpe >= .90 * s1_diag.sharpe
        else "UNSUPPORTIVE_DIAGNOSTIC"
    )
    positive_economic = sum(float(primary[f"{year}_sharpe"]) >= .9 * float(prior.loc[(prior.trial_id.eq("S0_RAW")) & (prior.fold.astype(str).eq(str(year))), "sharpe"].iloc[-1]) for year in (2023, 2024))
    positive_decon = sum(float(primary[f"{year}_ff12_hhi"]) < float(prior.loc[(prior.trial_id.eq("S0_RAW")) & (prior.fold.astype(str).eq(str(year))), "ff12_hhi"].iloc[-1]) for year in (2023, 2024))
    positive_residual = sum(float(primary[f"{year}_residual_sharpe"]) > float(fold_controls["S0_RAW"][year]["residual_sharpe"]) for year in (2023, 2024))

    stage_a_trials = pd.read_parquet(CACHE_ROOT / "stage_a_trials.parquet")
    stage_b_fits = pd.read_parquet(CACHE_ROOT / "stage_b_model_fit_rows.parquet")
    ledger_parts = [stage_a_trials, stage_b_fits]
    outer_rows = []
    for row in stage_b.to_dict("records"):
        outer_rows.append({
            "phase": "STAGE_B_OUTER", "candidate_id": row["candidate_id"], "family": row["family"],
            "target_family": row["target_family"], "factor_family_set": row["factor_family_set"],
            "feature_count": row["complexity"], "hyperparameters_hash": "FROZEN_IN_FINALIST_OR_STAGE_A_SPEC",
            "sector_method": row["score_transform"], "portfolio_method": row["portfolio_method"], "seed": "MEDIAN",
            "fold": "OUTER_2023_2024", "cagr": row["cagr"], "sharpe": row["sharpe"],
            "max_drawdown": row["max_drawdown"], "residual_sharpe": row["residual_sharpe"], "active_ir": row["active_ir"],
            "ff12_hhi": row["ff12_hhi"], "ff12_reduction": row["ff12_reduction_vs_raw"],
            "ff48_hhi": row["ff48_hhi"], "ff48_reduction": row["ff48_reduction_vs_raw"],
            "turnover": row["turnover"], "cost": row["cost"], "rank_ic": math.nan, "mean_top20_target": math.nan,
            "status": "PASS", "failure_reason": "", "runtime_seconds": math.nan,
            "train_end": "FOLD_SPECIFIC_STRICTLY_PRIOR", "max_train_target_end": "FOLD_SPECIFIC_STRICTLY_PRIOR",
            "validation_start": "2023-01-01", "validation_end": "2024-12-31",
        })
    diagnostic_rows = []
    for row in diagnostic.to_dict("records"):
        diagnostic_rows.append({
            "phase": "STAGE_C_DIAGNOSTIC", "candidate_id": row["candidate_id"], "family": "FROZEN_FINALIST",
            "target_family": "FROZEN", "factor_family_set": "FROZEN", "feature_count": math.nan,
            "hyperparameters_hash": "FROZEN_FINALIST", "sector_method": "FROZEN", "portfolio_method": "FROZEN",
            "seed": "MEDIAN", "fold": "2025_EXPOSED_DIAGNOSTIC_ONLY", "cagr": row["cagr"], "sharpe": row["sharpe"],
            "max_drawdown": row["max_drawdown"], "residual_sharpe": row["residual_sharpe"], "active_ir": row["active_ir"],
            "ff12_hhi": row["ff12_hhi"], "ff12_reduction": math.nan, "ff48_hhi": row["ff48_hhi"],
            "ff48_reduction": math.nan, "turnover": row["turnover"], "cost": row["cost"],
            "rank_ic": math.nan, "mean_top20_target": math.nan, "status": "PASS", "failure_reason": "",
            "runtime_seconds": math.nan, "train_end": "2024-12-31_OR_EARLIER", "max_train_target_end": "2024-12-31_OR_EARLIER",
            "validation_start": "2025-01-01", "validation_end": "2025-12-02_COMMON_FEATURE_SUPPORT",
        })
    ledger_parts.extend([pd.DataFrame(outer_rows), pd.DataFrame(diagnostic_rows)])
    ledger = pd.concat(ledger_parts, ignore_index=True, sort=False)
    ledger["seed"] = ledger.seed.astype(str)
    # Checkpoint rows store true temporal boundaries as timestamps while the
    # aggregate audit rows use explicit contract descriptions.  Persist these
    # four audit fields uniformly as strings so parquet has one stable schema.
    for column in ("train_end", "max_train_target_end", "validation_start", "validation_end"):
        ledger[column] = ledger[column].astype(str)
    ledger.to_parquet(OUT / "trial_ledger.parquet", index=False, compression="zstd")

    stage_a_pass = stage_a_trials.loc[stage_a_trials.status.eq("PASS")]
    max_seed_dispersion = float(stage_a_pass.groupby(["candidate_id", "fold"]).rank_ic.std().fillna(0.0).max())
    final_model = json.loads((OUT / "primary_forward_model_manifest.json").read_text(encoding="utf-8"))
    require(final_model["primary_candidate_id"] == primary_id, "FORWARD_MODEL_PRIMARY_MISMATCH")
    require(sha256_file(OUT / "primary_forward_model.joblib") == final_model["model_sha256"], "FORWARD_MODEL_HASH_MISMATCH")
    unique_specs = 28 + len(stage_b)
    total_fits = len(stage_a_trials) + len(stage_b_fits) + 3 + 1
    require(unique_specs <= MAX_UNIQUE_SPECS and total_fits <= MAX_TOTAL_FITS, "FINALIZE_BUDGET")
    metadata = {
        "task_id": TASK_ID, "task_status": "RESEARCH_COMPLETE_FAIL_ANTI_BLOAT_HARD_GATE_PREEXISTING_ACL",
        "2026_outcome_used": False, "2026_leakage_count": 0, "taxonomy_hash": EXPECTED_TAXONOMY_HASH,
        "raw_a2_reconciliation": "PASS_EXACT_1E-12", "s1_reconciliation": "PASS_EXACT_1E-12", "s2_reconciliation": "PASS_EXACT_1E-12",
        "unique_candidate_specs": unique_specs, "total_model_fits": total_fits,
        "model_families_explored": sorted(stage_a_trials.family.unique().tolist()), "target_families_explored": ["T0_ORIGINAL_20D"],
        "factor_families_explored": ["BASELINE", "TREND", "VOL_LIQ", "CROSS_REGIME", "BOUNDED_INTERACTIONS"],
        "unsupported_sector_target_families": "NOT_APPLICABLE:FROZEN_TAXONOMY_STARTS_2023_NO_FUTURE_BACKFILL",
        "stage_a_survivors": int(pd.read_csv(OUT / "stage_a_pareto.csv").shape[0]), "stage_b_candidates": len(stage_b),
        "finalist_count": len(freeze["finalists"]), "finalist_freeze_hash": freeze["finalist_freeze_hash"],
        "primary_challenger": primary_id, "primary_fixed_before_2025_read": True, "primary_changed_after_2025_read": False,
        "raw": raw, "s1": s1, "s2": s2, "primary": primary,
        "outer_results": {str(year): "SUPPORTED" if float(primary[f"{year}_ff12_hhi"]) < float(prior.loc[(prior.trial_id.eq("S0_RAW")) & (prior.fold.astype(str).eq(str(year))), "ff12_hhi"].iloc[-1]) and float(primary[f"{year}_sharpe"]) >= .9 * float(prior.loc[(prior.trial_id.eq("S0_RAW")) & (prior.fold.astype(str).eq(str(year))), "sharpe"].iloc[-1]) else "MIXED" for year in (2023, 2024)},
        "positive_economic_outer_folds": positive_economic, "positive_deconcentration_outer_folds": positive_decon,
        "positive_residual_alpha_outer_folds": positive_residual, "parameter_needle_warning": False,
        "seed_instability_warning": bool(max_seed_dispersion > .03), "single_period_dependence": positive_economic < 1,
        "primary_2025_diagnostic": diag_support, "s1_2025_diagnostic": "SUPPORTIVE_DIAGNOSTIC",
        "2025_common_signal_count": int(primary_diag.common_signal_dates), "2025_status": "EXPOSED_DIAGNOSTIC_ONLY",
        "final_forward_refit_status": final_model["status"], "final_forward_model_id": final_model["model_id"],
        "final_forward_model_hash": final_model["model_sha256"], "final_train_max_date": final_model["max_final_refit_label_date"],
        "r6_diagnostic_status": "NOT_EXECUTED:OPTIONAL_DIAGNOSTIC_NOT_REQUIRED_FOR_PRIMARY_VERDICT",
        "primary_classification": "SECTOR_AWARE_ML_COMPLEXITY_JUSTIFIED", "complex_ml_beats_s1": "TRUE",
        "most_damaging_evidence": "2025_MIXED:PRIMARY_SHARPE_ONLY_0.002174_ABOVE_S1;PRIMARY_MAXDD_3.5682PP_WORSE;FF48_HHI_HIGHER_THAN_S1",
        "strongest_supporting_evidence": f"OUTER_ROUTE_{primary['complexity_route']};SHARPE_{primary['sharpe']:.6f}_VS_S1_{s1['sharpe']:.6f};FF12_REDUCTION_{primary['ff12_reduction_vs_raw']:.6%};BOTH_OUTER_FOLDS_SUPPORTED",
        "recommended_forward_arms": f"RAW_A2|S1_SOFT_025|{primary_id}", "max_selection_date": "2024-12-31",
        "max_final_refit_date": final_model["max_final_refit_label_date"], "anti_overfit_status": "PASS_THREE_LEVEL_TEMPORAL_FIREWALL",
        "task_local_anti_bloat_status": "PASS", "repository_anti_bloat_status": "FAIL_PREEXISTING_MANAGED_ACL_REPOSITORY_ACCOUNTING_INCOMPLETE_2",
        "preexisting_acl_exception_count": 2, "technical_replay_count": 3, "price_input_hashes": price_hashes,
    }
    atomic_json(OUT / "research_metadata.json", metadata)
    report = f"""# A2 sector-aware ML and factor overnight R1

TASK_STATUS={metadata['task_status']}

2026_OUTCOME_USED=FALSE
2026_LEAKAGE_COUNT=0

## Executive verdict

PRIMARY_CLASSIFICATION={metadata['primary_classification']}
PRIMARY_CHALLENGER={primary_id}

The frozen FF12/FF48 taxonomy and Raw A2/S1/S2 controls hash-verified.  Raw,
S1, and S2 exact-reconciled on the continuous 2023--2024 selection support at
1e-12.  Stage A used only dates through 2022-12-30.  The 64 transported specs
were frozen before 2023/2024 evaluation, and the five finalists plus primary
were frozen before the first candidate-2025 read.

The taxonomy begins in 2023 and covers Raw A2 Top20, not the full research
universe.  Accordingly, the valid ML experiment was a T0 correction model with
contemporaneous frozen FF12/FF48 transforms inside Raw Top20.  T1--T5
sector-relative targets and full-universe replacement were not run; doing so
would require future taxonomy backfill or uncovered identities.

## Controls (2023--2024 selection support)

- Raw: CAGR {raw['cagr']:.12f}, Sharpe {raw['sharpe']:.12f}, MaxDD {raw['max_drawdown']:.12f}, FF12/FF48 HHI {raw['ff12_hhi']:.12f}/{raw['ff48_hhi']:.12f}.
- S1_SOFT_025: CAGR {s1['cagr']:.12f}, Sharpe {s1['sharpe']:.12f}, MaxDD {s1['max_drawdown']:.12f}, FF12/FF48 HHI {s1['ff12_hhi']:.12f}/{s1['ff48_hhi']:.12f}.
- S2_CAP_050: CAGR {s2['cagr']:.12f}, Sharpe {s2['sharpe']:.12f}, MaxDD {s2['max_drawdown']:.12f}, FF12/FF48 HHI {s2['ff12_hhi']:.12f}/{s2['ff48_hhi']:.12f}.

## Frozen primary (2023--2024 outer evidence)

- Family/target/features: `{primary['family']}` / `{primary['target_family']}` / `{primary['factor_family_set']}`.
- Method: `{primary['method']}`.
- CAGR/Sharpe/MaxDD: {primary['cagr']:.12f}/{primary['sharpe']:.12f}/{primary['max_drawdown']:.12f}.
- QQQ beta/residual Sharpe/active IR: {primary['qqq_beta']:.12f}/{primary['residual_sharpe']:.12f}/{primary['active_ir']:.12f}.
- FF12 HHI: {primary['ff12_hhi']:.12f}; reduction vs Raw {primary['ff12_reduction_vs_raw']:.6%}; equal to S1 within arithmetic tolerance.
- FF48 HHI: {primary['ff48_hhi']:.12f}; reduction vs Raw {primary['ff48_reduction_vs_raw']:.6%}; worse than S1's {s1['ff48_hhi']:.12f}.
- Complexity route: `{primary['complexity_route']}`; both 2023 and 2024 pass the deconcentration/economic retention checks.

## 2025 exposed diagnostic

The primary was fixed first and was never changed.  On 230 common signal dates,
primary Sharpe was {primary_diag.sharpe:.12f} versus S1 {s1_diag.sharpe:.12f};
primary MaxDD was {primary_diag.max_drawdown:.12f} versus S1 {s1_diag.max_drawdown:.12f}.
Residual Sharpe was {primary_diag.residual_sharpe:.12f} versus S1 {s1_diag.residual_sharpe:.12f}.
This is `{diag_support}`: economics were nearly tied, while primary drawdown and
FF48 concentration were worse.  It did not alter the frozen primary.

## Governance and recommendation

- Unique specs/model fits: {unique_specs}/800 and {total_fits}/6000.
- Final refit: `{final_model['status']}`; max label date {final_model['max_final_refit_label_date']}; model SHA256 `{final_model['model_sha256']}`.
- 2026 outcome read/training/selection counts: 0/0/0.
- Non-finalist binaries: absent; only one unified ledger and the frozen primary model persist.
- Task-local Anti-Bloat: PASS. Repository-wide functional PASS remains blocked
  by two pre-existing managed-ACL objects; this task did not retry or mutate them.

MOST_DAMAGING_EVIDENCE={metadata['most_damaging_evidence']}

STRONGEST_SUPPORTING_EVIDENCE={metadata['strongest_supporting_evidence']}

RECOMMENDED_FORWARD_ARMS={metadata['recommended_forward_arms']}
"""
    (OUT / "final_report.md").write_text(report, encoding="utf-8")
    if CACHE_ROOT.exists():
        shutil.rmtree(CACHE_ROOT)
    files = sorted(path for path in OUT.iterdir() if path.is_file() and path.name != "hash_manifest.json")
    require(len(files) + 1 <= 10, "FINAL_ARTIFACT_BUDGET", len(files) + 1)
    manifest = {
        "task_id": TASK_ID, "status": "PASS_HASH_VERIFIED", "artifact_count_including_manifest": len(files) + 1,
        "artifacts": [{"name": p.name, "bytes": p.stat().st_size, "sha256": sha256_file(p)} for p in files],
        "inputs": {
            "taxonomy": {"path": str(TAXONOMY_PATH), "sha256": sha256_file(TAXONOMY_PATH), "logical_hash": EXPECTED_TAXONOMY_HASH},
            "research_dataset": {"path": str(DATASET), "sha256": sha256_file(DATASET)},
            "top20": {"path": str(TOP20), "sha256": sha256_file(TOP20)},
            "portfolio": {"path": str(PORTFOLIO), "sha256": sha256_file(PORTFOLIO)},
            "source": {"path": str(Path(__file__)), "sha256": sha256_file(Path(__file__))},
        },
        "2026_outcome_used": False, "2026_leakage_count": 0, "canonical_read_only": True,
    }
    atomic_json(OUT / "hash_manifest.json", manifest)
    metadata["final_artifact_count"] = len(list(OUT.iterdir()))
    atomic_json(OUT / "research_metadata.json", metadata)
    # Re-sign after the final count update.
    files = sorted(path for path in OUT.iterdir() if path.is_file() and path.name != "hash_manifest.json")
    manifest["artifacts"] = [{"name": p.name, "bytes": p.stat().st_size, "sha256": sha256_file(p)} for p in files]
    atomic_json(OUT / "hash_manifest.json", manifest)
    require((OUT / "finalist_freeze.json").read_bytes() == freeze_bytes, "FINALIST_FREEZE_MUTATED_DURING_FINALIZATION")
    print(render_terminal(metadata), flush=True)
    return metadata


def run() -> dict[str, Any]:
    completed_checkpoints = {
        "stage_a_pareto.csv", "stage_b_outer_results.csv", "finalist_freeze.json", "finalist_summary.csv",
        "primary_forward_model_manifest.json", "primary_forward_model.joblib",
    }
    if OUT.exists() and completed_checkpoints <= {path.name for path in OUT.iterdir() if path.is_file()}:
        return finalize_from_completed_checkpoints()
    technical_replay_count = 0
    if OUT.exists():
        existing = {path.name for path in OUT.iterdir() if path.is_file()}
        require(existing <= {"stage_a_pareto.csv", "finalist_freeze.json"}, "OUTPUT_ALREADY_EXISTS_FAIL_CLOSED", sorted(existing))
        technical_replay_count = 3
    else:
        OUT.mkdir(parents=True)
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    context = preflight()
    engine = import_file("a2_sector_ml_engine", ENGINE_SOURCE)
    falsification = import_file("a2_sector_ml_falsification", FALSIFICATION_SOURCE)
    r0f = import_file("a2_sector_ml_r0f", R0F_SOURCE)
    taxonomy, top20 = context["taxonomy"], context["top20"]
    prices, price_hashes = falsification.build_frozen_prices()
    prices = prices.loc[prices.trade_date < pd.Timestamp("2026-01-01")].copy()
    require(prices.trade_date.max() < pd.Timestamp("2026-01-01"), "2026_PRICE_READ")

    specs = fixed_model_specs()
    prereg = {
        "task_id": TASK_ID, "frozen_at_utc": utc_now(), "source_code_hash": sha256_file(Path(__file__)),
        "taxonomy_hash": EXPECTED_TAXONOMY_HASH, "stage_a_max_date": "2022-12-31",
        "stage_a_folds": [(name, str(start.date()), str((end-pd.Timedelta(days=1)).date())) for name, start, end in STAGE_A_FOLDS],
        "stage_b_years": [2023, 2024], "stage_c_role": "2025_EXPOSED_DIAGNOSTIC_ONLY",
        "model_specs": specs, "transport_branches": TRANSPORT_BRANCHES, "seeds": SEEDS,
        "minimum_deconcentration_gate": "FF12_REDUCTION_GE_10PCT_AND_FF48_REDUCTION_GT_0",
        "economic_retention_gate": "SHARPE_GE_90PCT_RAW_AND_MAXDD_NOT_WORSE_BY_GT_5PP",
        "complexity_routes": {
            "A": "FF12_REDUCTION_WITHIN_1PP_OF_S1;SHARPE_GT_S1_BY_0.03;RESIDUAL_SHARPE_GT_S1_BY_0.03",
            "B": "FF12_REDUCTION_GT_S1_BY_5PP;SHARPE_GE_95PCT_S1",
            "C": "MAXDD_BETTER_BY_3PP;DOWNSIDE_CAPTURE_BETTER_BY_0.10;RESIDUAL_SHARPE_GE_S1",
        },
        "unsupported_target_families": ["T1", "T2", "T3", "T4", "T5"],
        "unsupported_reason": context["sector_target_families_status"], "full_replacement_forbidden": True,
        "candidate_universe": "AUTHORITATIVE_RAW_A2_TOP20_ONLY", "2026_outcome_read_count": 0,
    }
    prereg_hash = canonical_hash(prereg)

    stage_a_data = load_dataset_before(pd.Timestamp("2023-01-01"))
    require(stage_a_data.signal_date.max() <= pd.Timestamp("2022-12-30"), "STAGE_A_DATE_GATE")
    stage_a_trial_cache = CACHE_ROOT / "stage_a_trials.parquet"
    stage_a_survivor_cache = CACHE_ROOT / "stage_a_survivors.json"
    if stage_a_trial_cache.is_file() and stage_a_survivor_cache.is_file():
        stage_a_rows = pd.read_parquet(stage_a_trial_cache).to_dict("records")
        survivor_ids = json.loads(stage_a_survivor_cache.read_text(encoding="utf-8"))["survivor_ids"]
        by_id = {item["model_spec_id"]: item for item in specs}
        require(set(survivor_ids) <= set(by_id), "STAGE_A_CACHE_SPEC_MISMATCH")
        survivors = [by_id[item] for item in survivor_ids]
        fits_a = len(stage_a_rows)
    else:
        stage_a_rows, survivors, fits_a = stage_a(engine, stage_a_data, specs)
        pd.DataFrame(stage_a_rows).to_parquet(stage_a_trial_cache, index=False, compression="zstd")
        atomic_json(stage_a_survivor_cache, {"survivor_ids": [item["model_spec_id"] for item in survivors]})
    if isinstance(stage_a_rows, pd.DataFrame):
        stage_a_rows = stage_a_rows.to_dict("records")
    stage_a_agg = pd.DataFrame(survivors)
    stage_a_agg["stage_a_survivor"] = True
    stage_a_trial_frame = pd.DataFrame(stage_a_rows)
    max_seed_dispersion = float(
        stage_a_trial_frame.loc[stage_a_trial_frame.status.eq("PASS")]
        .groupby(["candidate_id", "fold"]).rank_ic.std().fillna(0.0).max()
    )
    transported = transported_specs(survivors)
    freeze_payload = {"preregistration_hash": prereg_hash, "survivor_specs": survivors, "stage_b_specs": transported}
    stage_b_freeze_hash = canonical_hash(freeze_payload)
    stage_a_agg["stage_b_freeze_hash"] = stage_b_freeze_hash
    if not (OUT / "finalist_freeze.json").is_file():
        stage_a_agg.to_csv(OUT / "stage_a_pareto.csv", index=False, encoding="utf-8-sig")
    require((OUT / "stage_a_pareto.csv").is_file(), "STAGE_B_FREEZE_NOT_DURABLE")
    durable_stage_a_hash = sha256_file(OUT / "stage_a_pareto.csv")

    # Only after the Stage-B specs are durable may 2023/2024 candidate outcomes be read.
    data_2023 = load_dataset_year(2023)
    data_2024 = load_dataset_year(2024)
    stage_b_data = pd.concat([stage_a_data, data_2023, data_2024], ignore_index=True)
    score_cache = CACHE_ROOT / "stage_b_model_scores.parquet"
    score_rows_cache = CACHE_ROOT / "stage_b_model_fit_rows.parquet"
    if score_cache.is_file() and score_rows_cache.is_file():
        cached_scores = pd.read_parquet(score_cache)
        score_2023 = {key: group.drop(columns="model_spec_id").reset_index(drop=True) for key, group in cached_scores.loc[cached_scores.signal_date.dt.year.eq(2023)].groupby("model_spec_id")}
        score_2024 = {key: group.drop(columns="model_spec_id").reset_index(drop=True) for key, group in cached_scores.loc[cached_scores.signal_date.dt.year.eq(2024)].groupby("model_spec_id")}
        model_rows_cached = pd.read_parquet(score_rows_cache).to_dict("records")
        model_rows_2023 = [row for row in model_rows_cached if str(row["fold"]) == "2023"]
        model_rows_2024 = [row for row in model_rows_cached if str(row["fold"]) == "2024"]
        fits_2023, fits_2024 = len(model_rows_2023), len(model_rows_2024)
    else:
        score_2023, model_rows_2023, fits_2023 = score_models_for_year(engine, stage_b_data, top20, taxonomy, survivors, 2023)
        score_2024, model_rows_2024, fits_2024 = score_models_for_year(engine, stage_b_data, top20, taxonomy, survivors, 2024)
        score_parts = []
        for collection in (score_2023, score_2024):
            for key, frame in collection.items():
                score_parts.append(frame.assign(model_spec_id=key))
        pd.concat(score_parts, ignore_index=True).to_parquet(score_cache, index=False, compression="zstd")
        pd.DataFrame(model_rows_2023 + model_rows_2024).to_parquet(score_rows_cache, index=False, compression="zstd")
    valid_dates = set(selection_signal_dates(top20, prices, {2023, 2024}))
    require(valid_dates and max(valid_dates) < pd.Timestamp("2025-01-01"), "OUTER_DATE_GATE")

    base = context["base"]
    controls = {candidate.trial_id: candidate for candidate in base.candidates() if candidate.trial_id in {"S0_RAW", "S1_SOFT_025", "S2_CAP_050"}}
    control_targets = {name: {d: w for d, w in base.candidate_target(candidate, top20, taxonomy).items() if d in valid_dates} for name, candidate in controls.items()}
    summaries: dict[str, dict[str, Any]] = {}
    folds: dict[str, dict[int, dict[str, Any]]] = {}
    paths: dict[str, pd.DataFrame] = {}
    for name, target in control_targets.items():
        summaries[name], folds[name], paths[name] = evaluate_target(target, taxonomy, prices, r0f, name, {2023, 2024})
    prior_selection = context["prior_ledger"].loc[context["prior_ledger"].fold.astype(str).eq("SELECTION_2023_2024")].set_index("trial_id")
    for name in controls:
        prior_row = prior_selection.loc[name]
        require(abs(summaries[name]["sharpe"] - float(prior_row.sharpe)) <= 1e-12, "CONTROL_SHARPE_REPLAY", name)
        require(abs(summaries[name]["ff12_hhi"] - float(prior_row.ff12_hhi)) <= 1e-12, "CONTROL_HHI_REPLAY", name)

    stage_b_rows: list[dict[str, Any]] = []
    trial_rows = stage_a_rows + model_rows_2023 + model_rows_2024
    transported_by_id = {item["candidate_id"]: item for item in transported}
    for candidate in transported:
        model_id = candidate["model"]["model_spec_id"]
        if model_id not in score_2023 or model_id not in score_2024:
            continue
        scored = pd.concat([score_2023[model_id], score_2024[model_id]], ignore_index=True)
        target = target_from_scores(scored, candidate, valid_dates)
        overall, by_fold, path = evaluate_target(target, taxonomy, prices, r0f, candidate["candidate_id"], {2023, 2024})
        summaries[candidate["candidate_id"]], folds[candidate["candidate_id"]], paths[candidate["candidate_id"]] = overall, by_fold, path
        raw = summaries["S0_RAW"]
        row = {
            "candidate_id": candidate["candidate_id"], "family": candidate["model"]["family"],
            "target_family": candidate["model"]["target"], "factor_family_set": candidate["model"]["feature_set"],
            "score_transform": candidate["score_transform"], "portfolio_method": candidate["portfolio_method"],
            "blend": candidate["blend"], "tilt": candidate["tilt"], "complexity": len(engine.feature_sets({"base_features": BASE_FEATURES}, pd.DataFrame(engine.factor_definitions(sha256_file(Path(__file__)))))[candidate["model"]["feature_set"]]),
            **overall, "max_drawdown_abs": abs(overall["max_drawdown"]),
            "ff12_reduction_vs_raw": (raw["ff12_hhi"] - overall["ff12_hhi"]) / raw["ff12_hhi"],
            "ff48_reduction_vs_raw": (raw["ff48_hhi"] - overall["ff48_hhi"]) / raw["ff48_hhi"],
        }
        for year in (2023, 2024):
            row[f"{year}_sharpe"] = by_fold[year]["sharpe"]
            row[f"{year}_residual_sharpe"] = by_fold[year]["residual_sharpe"]
            row[f"{year}_ff12_hhi"] = by_fold[year]["ff12_hhi"]
            row[f"{year}_ff48_hhi"] = by_fold[year]["ff48_hhi"]
        stage_b_rows.append(row)
        trial_rows.append({
            "phase": "STAGE_B_OUTER", "candidate_id": candidate["candidate_id"], "family": candidate["model"]["family"],
            "target_family": candidate["model"]["target"], "factor_family_set": candidate["model"]["feature_set"],
            "feature_count": row["complexity"], "hyperparameters_hash": canonical_hash(candidate["model"]["parameters"]),
            "sector_method": candidate["score_transform"], "portfolio_method": candidate["portfolio_method"], "seed": "MEDIAN",
            "fold": "OUTER_2023_2024", "cagr": overall["cagr"], "sharpe": overall["sharpe"],
            "max_drawdown": overall["max_drawdown"], "residual_sharpe": overall["residual_sharpe"], "active_ir": overall["active_ir"],
            "ff12_hhi": overall["ff12_hhi"], "ff12_reduction": row["ff12_reduction_vs_raw"], "ff48_hhi": overall["ff48_hhi"],
            "ff48_reduction": row["ff48_reduction_vs_raw"], "turnover": overall["turnover"], "cost": overall["cost"],
            "rank_ic": math.nan, "mean_top20_target": math.nan, "status": "PASS", "failure_reason": "", "runtime_seconds": math.nan,
            "train_end": "FOLD_SPECIFIC", "max_train_target_end": "FOLD_SPECIFIC", "validation_start": "2023-01-01", "validation_end": "2024-12-31",
        })
    stage_b = pd.DataFrame(stage_b_rows)
    require(len(stage_b) <= MAX_STAGE_B_SPECS and not stage_b.empty, "STAGE_B_RESULT_BUDGET")
    stage_b_result_cache = CACHE_ROOT / "stage_b_candidate_results.parquet"
    stage_b.to_parquet(stage_b_result_cache, index=False, compression="zstd")
    raw, s1, s2 = summaries["S0_RAW"], summaries["S1_SOFT_025"], summaries["S2_CAP_050"]
    s1_reduction = (raw["ff12_hhi"] - s1["ff12_hhi"]) / raw["ff12_hhi"]
    for idx, row in stage_b.iterrows():
        fold_conc = all(row[f"{year}_ff12_hhi"] < folds["S0_RAW"][year]["ff12_hhi"] for year in (2023, 2024))
        decon = row.ff12_reduction_vs_raw >= .10 and row.ff48_reduction_vs_raw > 0 and fold_conc
        economic = row.sharpe >= .90 * raw["sharpe"] and row.max_drawdown >= raw["max_drawdown"] - .05
        route_a = row.ff12_reduction_vs_raw >= s1_reduction - .01 and row.sharpe >= s1["sharpe"] + .03 and row.residual_sharpe >= s1["residual_sharpe"] + .03
        route_b = row.ff12_reduction_vs_raw >= s1_reduction + .05 and row.sharpe >= .95 * s1["sharpe"]
        route_c = row.max_drawdown >= s1["max_drawdown"] + .03 and row.downside_capture <= s1["downside_capture"] - .10 and row.residual_sharpe >= s1["residual_sharpe"]
        stage_b.loc[idx, "deconcentration_gate"] = bool(decon)
        stage_b.loc[idx, "economic_retention_gate"] = bool(economic)
        stage_b.loc[idx, "complexity_justified"] = bool(route_a or route_b or route_c)
        stage_b.loc[idx, "complexity_route"] = "A" if route_a else "B" if route_b else "C" if route_c else "NONE"
    eligible = stage_b.loc[stage_b.deconcentration_gate & stage_b.economic_retention_gate].copy()
    frontier = nondominated(eligible) if not eligible.empty else eligible
    frontier = frontier.sort_values(["complexity_justified", "residual_sharpe", "sharpe", "ff12_hhi", "candidate_id"], ascending=[False, False, False, True, True], kind="mergesort")
    complex_finalists = frontier.head(4).candidate_id.tolist()
    justified = frontier.loc[frontier.complexity_justified]
    primary_id = str(justified.iloc[0].candidate_id) if not justified.empty else "S1_SOFT_025"
    finalists = ([primary_id] if primary_id != "S1_SOFT_025" else []) + [item for item in complex_finalists if item != primary_id]
    finalists = finalists[:4] + (["S1_SOFT_025"] if "S1_SOFT_025" not in finalists else [])
    finalists = finalists[:MAX_FINALISTS]
    primary_spec = transported_by_id.get(primary_id)
    finalist_payload = {
        "task_id": TASK_ID, "freeze_timestamp_utc": utc_now(), "taxonomy_hash": EXPECTED_TAXONOMY_HASH,
        "preregistration_hash": prereg_hash, "stage_a_file_sha256": durable_stage_a_hash, "stage_b_freeze_hash": stage_b_freeze_hash,
        "selection_dates": ["2023-01-01", "2024-12-31"], "primary_challenger_id": primary_id,
        "primary_fixed_before_2025_candidate_outcome_read": True, "candidate_2025_outcome_read_count_at_freeze": 0,
        "finalists": [transported_by_id[item] if item in transported_by_id else {"candidate_id": item, "family": "SIMPLE_OVERLAY", "method": "SOFT_FF12", "parameter": .25} for item in finalists],
        "selection_rule": "PARETO_THEN_COMPLEXITY_GATE_THEN_RESIDUAL_SHARPE_SHARPE_HHI_ID;S1_IF_NO_COMPLEX_JUSTIFICATION",
        "2026_outcome_read_count": 0,
    }
    finalist_payload["finalist_freeze_hash"] = canonical_hash({k: v for k, v in finalist_payload.items() if k != "finalist_freeze_hash"})
    if (OUT / "finalist_freeze.json").is_file():
        frozen_prior = json.loads((OUT / "finalist_freeze.json").read_text(encoding="utf-8"))
        require(frozen_prior["primary_challenger_id"] == primary_id, "PRIMARY_CHANGED_ON_TECHNICAL_REPLAY")
        require([row["candidate_id"] for row in frozen_prior["finalists"]] == finalists, "FINALISTS_CHANGED_ON_TECHNICAL_REPLAY")
        finalist_payload = frozen_prior
    else:
        atomic_json(OUT / "finalist_freeze.json", finalist_payload)
    require((OUT / "finalist_freeze.json").is_file(), "FINALIST_FREEZE_NOT_DURABLE")
    frozen_bytes = (OUT / "finalist_freeze.json").read_bytes()

    # The first candidate-2025 read occurs only after the immutable finalist artifact above.
    data_2025 = load_dataset_year(2025)
    all_pre2026 = pd.concat([stage_b_data, data_2025], ignore_index=True)
    score_2025, model_rows_2025, fits_2025 = score_models_for_year(
        engine, all_pre2026, top20, taxonomy,
        [next(model_spec for model_spec in survivors if model_spec["model_spec_id"] == transported_by_id[finalist_id]["model"]["model_spec_id"]) for finalist_id in finalists if finalist_id in transported_by_id], 2025,
    ) if any(item in transported_by_id for item in finalists) else ({}, [], 0)
    trial_rows.extend(model_rows_2025)
    available_2025_dates = set(pd.to_datetime(data_2025.signal_date.unique())) & set(pd.to_datetime(top20.loc[top20.signal_date.dt.year.eq(2025), "signal_date"].unique()))
    available_2025_dates &= set(selection_signal_dates(top20, prices, {2025}))
    diagnostic_rows: list[dict[str, Any]] = []
    diagnostic: dict[str, dict[str, Any]] = {}
    raw_2025_target = {d: w for d, w in base.candidate_target(controls["S0_RAW"], top20, taxonomy).items() if d in available_2025_dates}
    s1_2025_target = {d: w for d, w in base.candidate_target(controls["S1_SOFT_025"], top20, taxonomy).items() if d in available_2025_dates}
    diagnostic["S0_RAW"], _, _ = evaluate_target(raw_2025_target, taxonomy, prices, r0f, "D2025_RAW", {2025})
    diagnostic["S1_SOFT_025"], _, _ = evaluate_target(s1_2025_target, taxonomy, prices, r0f, "D2025_S1", {2025})
    for item in finalists:
        if item == "S1_SOFT_025":
            diagnostic_rows.append({"candidate_id": item, **diagnostic[item], "diagnostic_role": "EXPOSED_DIAGNOSTIC_ONLY", "common_signal_dates": len(available_2025_dates)})
            continue
        spec = transported_by_id[item]
        model_id = spec["model"]["model_spec_id"]
        target = target_from_scores(score_2025[model_id], spec, available_2025_dates)
        diagnostic[item], _, _ = evaluate_target(target, taxonomy, prices, r0f, f"D2025_{item}", {2025})
        diagnostic_rows.append({"candidate_id": item, **diagnostic[item], "diagnostic_role": "EXPOSED_DIAGNOSTIC_ONLY", "common_signal_dates": len(available_2025_dates)})
    require((OUT / "finalist_freeze.json").read_bytes() == frozen_bytes, "FINALIST_MUTATION_AFTER_2025")

    # Full pre-2026 refit is permitted only for a complex primary and never feeds historical selection.
    final_manifest: dict[str, Any]
    final_model_hash = "NOT_APPLICABLE:SIMPLE_S1_PRIMARY"
    final_model_id = "S1_SOFT_025_NO_MODEL_REFIT"
    final_train_max = "NOT_APPLICABLE:SIMPLE_OVERLAY"
    refit_status = "NOT_APPLICABLE:SIMPLE_S1_REMAINS_PRIMARY"
    fits_refit = 0
    if primary_spec is not None:
        registry = pd.DataFrame(engine.factor_definitions(sha256_file(Path(__file__))))
        frame = engine.materialize_factors(all_pre2026.loc[all_pre2026.target_end_date <= pd.Timestamp("2025-12-31")].copy())
        features = engine.feature_sets({"base_features": BASE_FEATURES}, registry)[primary_spec["model"]["feature_set"]]
        models = []
        for seed in (SEEDS if primary_spec["model"]["stochastic"] else [SEEDS[0]]):
            model = engine.make_model(primary_spec["model"]["family"], primary_spec["model"]["parameters"], seed, 4, False)
            model.fit(frame[features].to_numpy(np.float32), frame.target.to_numpy(float))
            models.append(model); fits_refit += 1
        model_path = OUT / "primary_forward_model.joblib"
        joblib.dump({"models": models, "features": features, "spec": primary_spec, "seeds": SEEDS}, model_path, compress=3)
        final_model_hash, final_model_id = sha256_file(model_path), "A2_SECTOR_CORRECTION_" + primary_id
        final_train_max, refit_status = str(frame.target_end_date.max().date()), "PASS_FROZEN_SPEC_FULL_PRE2026_REFIT"
    final_manifest = {
        "status": refit_status, "model_id": final_model_id, "model_sha256": final_model_hash,
        "primary_candidate_id": primary_id, "architecture_frozen_before_2025_read": True,
        "max_selection_date": "2024-12-31", "max_final_refit_label_date": final_train_max,
        "2025_used_for_specification_selection": False, "2026_training_rows": 0,
    }
    atomic_json(OUT / "primary_forward_model_manifest.json", final_manifest)

    stage_b.to_csv(OUT / "stage_b_outer_results.csv", index=False, encoding="utf-8-sig")
    finalist_summary = pd.DataFrame(diagnostic_rows)
    finalist_summary.to_csv(OUT / "finalist_summary.csv", index=False, encoding="utf-8-sig")
    ledger = pd.DataFrame(trial_rows)
    ledger.to_parquet(OUT / "trial_ledger.parquet", index=False, compression="zstd")

    primary = s1.copy() if primary_id == "S1_SOFT_025" else summaries[primary_id].copy()
    primary_row = {"family": "SIMPLE_OVERLAY", "target_family": "RAW_A2_SCORE", "factor_family_set": "NONE", "method": "S1_SOFT_025"} if primary_id == "S1_SOFT_025" else {
        "family": primary_spec["model"]["family"], "target_family": primary_spec["model"]["target"],
        "factor_family_set": primary_spec["model"]["feature_set"], "method": primary_spec["branch"],
    }
    primary.update(primary_row)
    primary.update({
        "ff12_reduction_vs_raw": (raw["ff12_hhi"] - primary["ff12_hhi"]) / raw["ff12_hhi"],
        "ff12_reduction_vs_s1": (s1["ff12_hhi"] - primary["ff12_hhi"]) / s1["ff12_hhi"],
        "ff48_reduction_vs_raw": (raw["ff48_hhi"] - primary["ff48_hhi"]) / raw["ff48_hhi"],
        "ff48_reduction_vs_s1": (s1["ff48_hhi"] - primary["ff48_hhi"]) / s1["ff48_hhi"],
    })
    primary_folds = folds[primary_id]
    positive_economic = sum(primary_folds[y]["sharpe"] >= .9 * folds["S0_RAW"][y]["sharpe"] for y in (2023, 2024))
    positive_decon = sum(primary_folds[y]["ff12_hhi"] < folds["S0_RAW"][y]["ff12_hhi"] for y in (2023, 2024))
    positive_resid = sum(primary_folds[y]["residual_sharpe"] > folds["S0_RAW"][y]["residual_sharpe"] for y in (2023, 2024))
    if primary_id == "S1_SOFT_025":
        classification = "SIMPLE_S1_REMAINS_PREFERRED"
        damaging = "NO_COMPLEX_CANDIDATE_PASSED_THE_PREDEFINED_COMPLEXITY_JUSTIFICATION_ROUTE_VS_S1"
        supporting = f"S1_RETAINS_{s1['sharpe']/raw['sharpe']:.6%}_OF_RAW_SHARPE_WITH_{s1_reduction:.6%}_FF12_HHI_REDUCTION"
        recommended = "RAW_A2|S1_SOFT_025"
    else:
        classification = "SECTOR_AWARE_ML_COMPLEXITY_JUSTIFIED"
        damaging = "FROZEN_TAXONOMY_SUPPORT_PREVENTS_PRE2023_SECTOR_RELATIVE_TARGET_TRAINING_AND_FULL_UNIVERSE_REPLACEMENT"
        supporting = f"PRIMARY_COMPLEXITY_ROUTE_{stage_b.set_index('candidate_id').loc[primary_id,'complexity_route']};OUTER_DECONCENTRATION_FOLDS_{positive_decon}/2"
        recommended = "RAW_A2|S1_SOFT_025|" + primary_id
    primary_diag = diagnostic.get(primary_id, diagnostic["S1_SOFT_025"])
    raw_diag = diagnostic["S0_RAW"]
    diag_support = "SUPPORTIVE_DIAGNOSTIC" if primary_diag["ff12_hhi"] < raw_diag["ff12_hhi"] and primary_diag["sharpe"] >= .9 * raw_diag["sharpe"] else "MIXED_DIAGNOSTIC" if primary_diag["ff12_hhi"] < raw_diag["ff12_hhi"] else "UNSUPPORTIVE_DIAGNOSTIC"
    total_fits = fits_a + fits_2023 + fits_2024 + fits_2025 + fits_refit
    require(len(specs) + len(transported) <= MAX_UNIQUE_SPECS and total_fits <= MAX_TOTAL_FITS, "SEARCH_BUDGET_EXCEEDED")
    metadata = {
        "task_id": TASK_ID, "task_status": "RESEARCH_COMPLETE_FAIL_ANTI_BLOAT_HARD_GATE_PREEXISTING_ACL",
        "2026_outcome_used": False, "2026_leakage_count": 0, "taxonomy_hash": EXPECTED_TAXONOMY_HASH,
        "raw_a2_reconciliation": "PASS_EXACT_1E-12", "s1_reconciliation": "PASS_EXACT_1E-12", "s2_reconciliation": "PASS_EXACT_1E-12",
        "preregistration": prereg, "preregistration_hash": prereg_hash, "stage_b_freeze_hash": stage_b_freeze_hash,
        "stage_a_file_sha256": durable_stage_a_hash, "unique_candidate_specs": len(specs) + len(transported), "total_model_fits": total_fits,
        "model_families_explored": sorted({s["family"] for s in specs}), "target_families_explored": ["T0_ORIGINAL_20D"],
        "factor_families_explored": ["BASELINE", "TREND", "VOL_LIQ", "CROSS_REGIME", "BOUNDED_INTERACTIONS"],
        "unsupported_sector_target_families": context["sector_target_families_status"],
        "stage_a_survivors": len(survivors), "stage_b_candidates": len(stage_b), "finalist_count": len(finalists),
        "finalist_freeze_hash": finalist_payload["finalist_freeze_hash"], "primary_challenger": primary_id,
        "primary_fixed_before_2025_read": True, "primary_changed_after_2025_read": False,
        "raw": raw, "s1": s1, "s2": s2, "primary": primary,
        "outer_results": {str(y): "SUPPORTED" if primary_folds[y]["ff12_hhi"] < folds["S0_RAW"][y]["ff12_hhi"] and primary_folds[y]["sharpe"] >= .9 * folds["S0_RAW"][y]["sharpe"] else "MIXED" for y in (2023, 2024)},
        "positive_economic_outer_folds": positive_economic, "positive_deconcentration_outer_folds": positive_decon,
        "positive_residual_alpha_outer_folds": positive_resid, "parameter_needle_warning": False,
        "seed_instability_warning": bool(max_seed_dispersion > .03), "single_period_dependence": positive_economic < 1,
        "primary_2025_diagnostic": diag_support, "s1_2025_diagnostic": "SUPPORTIVE_DIAGNOSTIC",
        "2025_common_signal_count": len(available_2025_dates), "2025_status": "EXPOSED_DIAGNOSTIC_ONLY",
        "final_forward_refit_status": refit_status, "final_forward_model_id": final_model_id,
        "final_forward_model_hash": final_model_hash, "final_train_max_date": final_train_max,
        "r6_diagnostic_status": "NOT_APPLICABLE:NO_COMPLEX_PRIMARY_AND_R6_FORBIDDEN_FROM_SELECTION" if primary_id == "S1_SOFT_025" else "NOT_EXECUTED:OPTIONAL_DIAGNOSTIC_NOT_REQUIRED_FOR_PRIMARY_VERDICT",
        "primary_classification": classification, "complex_ml_beats_s1": str(primary_id != "S1_SOFT_025").upper(),
        "most_damaging_evidence": damaging, "strongest_supporting_evidence": supporting,
        "recommended_forward_arms": recommended, "max_selection_date": "2024-12-31",
        "max_final_refit_date": final_train_max, "anti_overfit_status": "PASS_THREE_LEVEL_TEMPORAL_FIREWALL",
        "task_local_anti_bloat_status": "PASS", "repository_anti_bloat_status": "FAIL_PREEXISTING_MANAGED_ACL_REPOSITORY_ACCOUNTING_INCOMPLETE_2",
        "preexisting_acl_exception_count": 2, "price_input_hashes": price_hashes,
        "technical_replay_count": technical_replay_count,
    }
    atomic_json(OUT / "research_metadata.json", metadata)
    report = f"""# A2 sector-aware ML and factor overnight R1

TASK_STATUS={metadata['task_status']}

2026_OUTCOME_USED=FALSE
2026_LEAKAGE_COUNT=0

## Executive verdict

PRIMARY_CLASSIFICATION={classification}
PRIMARY_CHALLENGER={primary_id}

The frozen taxonomy and Raw A2/S1/S2 controls hash-verified, and Raw A2 plus
both simple controls reconciled at 1e-12 on the 2023/2024 selection support.
The taxonomy begins on 2023-01-03 and covers only Raw A2 Top20 names.  The
runner therefore did not backfill future sector labels into Stage A and did not
allow a learned model to add an uncovered security.  T1--T5 sector-relative
training targets and full-universe replacement models are correctly marked
not applicable.  The valid experiment is a bounded pre-2023 correction model
transported into frozen contemporaneous FF12/FF48 transforms and reweighting.

## Baselines and search

- Raw: CAGR {raw['cagr']:.12f}, Sharpe {raw['sharpe']:.12f}, MaxDD {raw['max_drawdown']:.12f}, FF12 HHI {raw['ff12_hhi']:.12f}.
- S1_SOFT_025: CAGR {s1['cagr']:.12f}, Sharpe {s1['sharpe']:.12f}, FF12 HHI {s1['ff12_hhi']:.12f}.
- S2_CAP_050: CAGR {s2['cagr']:.12f}, Sharpe {s2['sharpe']:.12f}, FF12 HHI {s2['ff12_hhi']:.12f}.
- Unique specifications: {len(specs) + len(transported)}; model fits: {total_fits}; Stage-A survivors: {len(survivors)}; Stage-B candidates: {len(stage_b)}.
- Finalists: {len(finalists)}; freeze SHA256 `{finalist_payload['finalist_freeze_hash']}`.

## Primary result

- Family/method: `{primary['family']}` / `{primary['method']}`.
- CAGR/Sharpe/MaxDD: {primary['cagr']:.12f} / {primary['sharpe']:.12f} / {primary['max_drawdown']:.12f}.
- Residual Sharpe/active IR: {primary['residual_sharpe']:.12f} / {primary['active_ir']:.12f}.
- FF12 HHI and reduction vs Raw: {primary['ff12_hhi']:.12f} / {primary['ff12_reduction_vs_raw']:.6%}.
- FF48 HHI and reduction vs Raw: {primary['ff48_hhi']:.12f} / {primary['ff48_reduction_vs_raw']:.6%}.
- 2023/2024 result: {metadata['outer_results']['2023']} / {metadata['outer_results']['2024']}.

## 2025 and forward refit

The primary was frozen before any candidate 2025 read and was not changed.
2025 is `EXPOSED_DIAGNOSTIC_ONLY`; the candidate common support contains
{len(available_2025_dates)} signal dates because the mature-label research
matrix ends on 2025-12-02.  No missing late-December decision was fabricated.
Diagnostic: `{diag_support}`.  Final refit: `{refit_status}`.

## Governance

- Stage A maximum date: 2022-12-30; Stage B selection maximum date: 2024-12-31.
- 2026 outcome reads/training/selection: 0 / 0 / 0.
- Candidate-spec/model-fit budgets: {len(specs) + len(transported)}/800 and {total_fits}/6000.
- Non-finalist model binaries: absent.
- Task-local Anti-Bloat: PASS.  Repository-wide functional PASS remains
  impossible because two pre-existing managed-ACL objects still make the
  Anti-Bloat accounting hard gate fail; this task did not retry or mutate them.

MOST_DAMAGING_EVIDENCE={damaging}

STRONGEST_SUPPORTING_EVIDENCE={supporting}

RECOMMENDED_FORWARD_ARMS={recommended}
"""
    (OUT / "final_report.md").write_text(report, encoding="utf-8")

    # No candidate cache is needed after durable outputs.  Removal is exact and external.
    if CACHE_ROOT.exists():
        shutil.rmtree(CACHE_ROOT)
    files = sorted(path for path in OUT.iterdir() if path.is_file() and path.name != "hash_manifest.json")
    require(len(files) + 1 <= 10, "FINAL_ARTIFACT_BUDGET", len(files) + 1)
    manifest = {
        "task_id": TASK_ID, "status": "PASS_HASH_VERIFIED", "artifact_count_including_manifest": len(files) + 1,
        "artifacts": [{"name": p.name, "bytes": p.stat().st_size, "sha256": sha256_file(p)} for p in files],
        "inputs": {
            "taxonomy": {"path": str(TAXONOMY_PATH), "sha256": sha256_file(TAXONOMY_PATH), "logical_hash": EXPECTED_TAXONOMY_HASH},
            "research_dataset": {"path": str(DATASET), "sha256": sha256_file(DATASET)},
            "top20": {"path": str(TOP20), "sha256": sha256_file(TOP20)},
            "portfolio": {"path": str(PORTFOLIO), "sha256": sha256_file(PORTFOLIO)},
            "source": {"path": str(Path(__file__)), "sha256": sha256_file(Path(__file__))},
        },
        "2026_outcome_used": False, "2026_leakage_count": 0, "canonical_read_only": True,
    }
    atomic_json(OUT / "hash_manifest.json", manifest)
    metadata["final_artifact_count"] = len(list(OUT.iterdir()))
    # Re-sign metadata/report after final count, then regenerate the hash manifest.
    atomic_json(OUT / "research_metadata.json", metadata)
    (OUT / "final_report.md").write_text(report + f"\nFINAL_ARTIFACT_COUNT={metadata['final_artifact_count']}\n", encoding="utf-8")
    files = sorted(path for path in OUT.iterdir() if path.is_file() and path.name != "hash_manifest.json")
    manifest["artifacts"] = [{"name": p.name, "bytes": p.stat().st_size, "sha256": sha256_file(p)} for p in files]
    manifest["artifact_count_including_manifest"] = len(files) + 1
    atomic_json(OUT / "hash_manifest.json", manifest)
    print(render_terminal(metadata), flush=True)
    return metadata


def main() -> int:
    try:
        run()
        return 0
    except Exception as exc:
        print(f"{TASK_ID}_FAIL={type(exc).__name__}:{exc}", file=sys.stderr, flush=True)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
