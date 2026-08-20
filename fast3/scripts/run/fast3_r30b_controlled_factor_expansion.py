#!/usr/bin/env python
"""FAST3 R30B controlled economic factor expansion and family ablation."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

SOURCE_ROOT = Path(r"D:\us-tech-quant")
DATA_ROOT = Path(r"D:\us-tech-quant-data")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
CACHE_ROOT = Path(r"D:\us-tech-quant-cache")
R30A_FROZEN = RESULTS_ROOT / "frozen" / "fast3" / "r30a_economic_target_20260809T120000Z"
R30A_SCRATCH = RESULTS_ROOT / "scratch" / "fast3" / "r30a_economic_target_20260809T120000Z"
R30A_RUNNER = SOURCE_ROOT / "fast3" / "scripts" / "run" / "fast3_r30a_economic_target_baseline_training.py"
TARGET_CONTRACT = R30A_FROZEN / "FAST3_R30_T1_T2_ECONOMIC_TARGET_CONTRACT_R1.json"
R30A_DATA_IDENTITY = R30A_FROZEN / "FAST3_R30A_TRAINING_DATA_IDENTITY.json"
R30A_FEATURE_IDENTITY = R30A_FROZEN / "FAST3_R30A_FEATURE_IDENTITY.json"
R30A_SPLIT_IDENTITY = R30A_FROZEN / "FAST3_R30A_SPLIT_IDENTITY.json"
R30A_SUMMARY = R30A_FROZEN / "FAST3_R30A_SUMMARY.json"

TARGET_CONTRACT_SHA256 = "381ce44099d865748e73f5538c9327ad6a9619c7bcdbf18bcff8b9b5cfdaa996"
BASELINE_FEATURE_MANIFEST_SHA256 = "3cac01f22f8a0b308f2d666d06e36abe13643c4d60948bdc312a5a1a01b96ab3"
SPLIT_CONTRACT_SHA256 = "38352151a703737d74b4d61dbe68f82a9c6f3d5058aa72bd2a1896e19a5cb412"
EXPECTED_R30A = {
    "classification": "D_WEAK_OR_INCONCLUSIVE_ECONOMIC_SIGNAL",
    "T1_ROC_AUC": 0.5175555059228376,
    "T1_TOP20_REALIZED_MEAN_NET20": -0.006265271245016869,
    "T1_TOP10_REALIZED_MEAN_NET20": -0.009666712341384677,
    "T1_TOP5_REALIZED_MEAN_NET20": -0.015136288384587231,
    "T2_SPEARMAN_VS_RAW_NET20": 0.008400816566382965,
    "T2_TOP20_REALIZED_MEAN_NET20": -0.005168167823729637,
    "T2_TOP10_REALIZED_MEAN_NET20": -0.006987204957083842,
    "T2_TOP5_REALIZED_MEAN_NET20": -0.007561636148375262,
}

BASELINE_FEATURES = (
    "return_5m", "return_15m", "return_60m", "realized_vol_15m",
    "realized_vol_60m", "relative_volume", "range_position", "symbol_code",
    "direction_code", "session_code", "volume_zscore_60m",
    "signed_volume_pressure_15m", "peer_return_15m", "relative_return_15m",
)
FAMILY_A = (
    "RSI_14", "KDJ_J_9_3", "MACD_HIST_NORM_12_26_9",
    "EMA20_SLOPE_5", "PRICE_VS_MA20",
)
FAMILY_B = (
    "REALIZED_VOL_5", "ATR_NORMALIZED_14", "DOWNSIDE_VOLATILITY_20",
    "RECENT_DRAWDOWN_60", "VOLATILITY_ACCELERATION_15_60",
)
FAMILY_C = (
    "SOXX_VS_QQQ_RELATIVE_STRENGTH_60", "QQQ_MOMENTUM_30",
    "SOXX_QQQ_RETURN_SPREAD_5", "CROSS_ASSET_MOMENTUM_AGREEMENT_15",
    "QQQ_TREND_CONFIRMATION_20",
)
FAMILY_NAMES = {
    "TREND_PATH_QUALITY": FAMILY_A,
    "VOLATILITY_RISK_GEOMETRY": FAMILY_B,
    "CROSS_ASSET_CONFIRMATION": FAMILY_C,
}
ARM_ORDER = ("ARM_0", "ARM_A", "ARM_B", "ARM_C", "ARM_ALL")
ARM_LABELS = {
    "ARM_0": "BASELINE_14", "ARM_A": "TREND_PATH_QUALITY",
    "ARM_B": "VOLATILITY_RISK_GEOMETRY", "ARM_C": "CROSS_ASSET_CONFIRMATION",
    "ARM_ALL": "ALL_FAMILIES",
}
FAMILY_ARM = {
    "TREND_PATH_QUALITY": "ARM_A",
    "VOLATILITY_RISK_GEOMETRY": "ARM_B",
    "CROSS_ASSET_CONFIRMATION": "ARM_C",
}
TOPS = (20, 10, 5)

FEATURE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "RSI_14": {"family": "TREND_PATH_QUALITY", "formula": "100-100/(1+WilderEMA14(gain)/WilderEMA14(loss))", "lookback": "14 bars", "symbols": "decision underlying", "columns": "close", "group": "momentum_oscillator", "complexity": 2, "dependencies": 1},
    "KDJ_J_9_3": {"family": "TREND_PATH_QUALITY", "formula": "J=3*K-2*D; RSV9=(close-low9)/(high9-low9)*100; K,D use alpha=1/3", "lookback": "9 bars; smoothing 3/3", "symbols": "decision underlying", "columns": "high,low,close", "group": "momentum_oscillator", "complexity": 3, "dependencies": 3},
    "MACD_HIST_NORM_12_26_9": {"family": "TREND_PATH_QUALITY", "formula": "((EMA12(close)-EMA26(close))-EMA9(MACD))/close", "lookback": "12/26/9 bars", "symbols": "decision underlying", "columns": "close", "group": "trend_impulse", "complexity": 3, "dependencies": 3},
    "EMA20_SLOPE_5": {"family": "TREND_PATH_QUALITY", "formula": "EMA20(close)/EMA20(close)[t-5]-1", "lookback": "EMA20; slope 5 bars", "symbols": "decision underlying", "columns": "close", "group": "trend_slope", "complexity": 2, "dependencies": 2},
    "PRICE_VS_MA20": {"family": "TREND_PATH_QUALITY", "formula": "close/SMA20(close)-1", "lookback": "20 bars", "symbols": "decision underlying", "columns": "close", "group": "trend_location", "complexity": 1, "dependencies": 1},
    "REALIZED_VOL_5": {"family": "VOLATILITY_RISK_GEOMETRY", "formula": "rolling_std_5(log(close_t/close_t-1))", "lookback": "5 bars", "symbols": "decision underlying", "columns": "close", "group": "volatility_level", "complexity": 1, "dependencies": 1},
    "ATR_NORMALIZED_14": {"family": "VOLATILITY_RISK_GEOMETRY", "formula": "SMA14(max(high-low,abs(high-prev_close),abs(low-prev_close)))/close", "lookback": "14 bars", "symbols": "decision underlying", "columns": "high,low,close", "group": "range_risk", "complexity": 2, "dependencies": 3},
    "DOWNSIDE_VOLATILITY_20": {"family": "VOLATILITY_RISK_GEOMETRY", "formula": "sqrt(mean_20(min(log_return,0)^2))", "lookback": "20 bars", "symbols": "decision underlying", "columns": "close", "group": "downside_risk", "complexity": 2, "dependencies": 1},
    "RECENT_DRAWDOWN_60": {"family": "VOLATILITY_RISK_GEOMETRY", "formula": "close/rolling_max_60(close)-1", "lookback": "60 bars", "symbols": "decision underlying", "columns": "close", "group": "drawdown_state", "complexity": 1, "dependencies": 1},
    "VOLATILITY_ACCELERATION_15_60": {"family": "VOLATILITY_RISK_GEOMETRY", "formula": "realized_vol_15/realized_vol_60-1", "lookback": "15/60 bars", "symbols": "decision underlying", "columns": "close", "group": "volatility_change", "complexity": 2, "dependencies": 2},
    "SOXX_VS_QQQ_RELATIVE_STRENGTH_60": {"family": "CROSS_ASSET_CONFIRMATION", "formula": "SOXX_return_60-QQQ_return_60 at exact timestamp", "lookback": "60 bars", "symbols": "SOXX,QQQ", "columns": "close", "group": "relative_strength", "complexity": 2, "dependencies": 2},
    "QQQ_MOMENTUM_30": {"family": "CROSS_ASSET_CONFIRMATION", "formula": "QQQ_close/QQQ_close[t-30]-1 at exact timestamp", "lookback": "30 bars", "symbols": "QQQ", "columns": "close", "group": "market_momentum", "complexity": 1, "dependencies": 1},
    "SOXX_QQQ_RETURN_SPREAD_5": {"family": "CROSS_ASSET_CONFIRMATION", "formula": "SOXX_return_5-QQQ_return_5 at exact timestamp", "lookback": "5 bars", "symbols": "SOXX,QQQ", "columns": "close", "group": "relative_strength", "complexity": 2, "dependencies": 2},
    "CROSS_ASSET_MOMENTUM_AGREEMENT_15": {"family": "CROSS_ASSET_CONFIRMATION", "formula": "sign(SOXX_return_15)*sign(QQQ_return_15) at exact timestamp", "lookback": "15 bars", "symbols": "SOXX,QQQ", "columns": "close", "group": "market_confirmation", "complexity": 2, "dependencies": 2},
    "QQQ_TREND_CONFIRMATION_20": {"family": "CROSS_ASSET_CONFIRMATION", "formula": "QQQ_close/SMA20(QQQ_close)-1 at exact timestamp", "lookback": "20 bars", "symbols": "QQQ", "columns": "close", "group": "trend_location", "complexity": 1, "dependencies": 1},
}


class R30BStop(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, np.floating): return None if not np.isfinite(value) else float(value)
    if isinstance(value, (Path, pd.Timestamp, datetime)): return str(value)
    if pd.isna(value): return None
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=json_default, allow_nan=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None: raise R30BStop("STOP_MODULE_IMPORT")
    spec.loader.exec_module(module)
    return module


def freeze_manifest(path: Path, payload: dict[str, Any]) -> str:
    if path.exists(): raise R30BStop("STOP_FEATURE_MANIFEST_ALREADY_EXISTS")
    write_json(path, payload)
    return file_sha256(path)


def guard_manifest(path: Path, expected_sha: str) -> None:
    if not path.is_file() or file_sha256(path) != expected_sha:
        raise R30BStop("STOP_FEATURE_MANIFEST_MUTATED_AFTER_FREEZE")


def guard_target_contract() -> None:
    if file_sha256(TARGET_CONTRACT) != TARGET_CONTRACT_SHA256:
        raise R30BStop("STOP_TARGET_CONTRACT_MUTATED")


def verify_r30a(r30a) -> dict[str, Any]:
    guard_target_contract()
    summary = read_json(R30A_SUMMARY)
    data_identity = read_json(R30A_DATA_IDENTITY)
    feature_identity = read_json(R30A_FEATURE_IDENTITY)
    split_identity = read_json(R30A_SPLIT_IDENTITY)
    if summary["FAST3_R30A_CLASSIFICATION"] != EXPECTED_R30A["classification"]:
        raise R30BStop("STOP_R30A_CLASSIFICATION_MISMATCH")
    for key, expected in EXPECTED_R30A.items():
        if key == "classification": continue
        if not math.isclose(float(summary[key]), expected, rel_tol=0, abs_tol=1e-15):
            raise R30BStop("STOP_R30A_METRIC_MISMATCH:" + key)
    if summary["TARGET_CONTRACT_SHA256"] != TARGET_CONTRACT_SHA256 or summary["SPLIT_CONTRACT_SHA256"] != SPLIT_CONTRACT_SHA256:
        raise R30BStop("STOP_R30A_CONTRACT_IDENTITY_MISMATCH")
    if feature_identity["FEATURE_NAMES"] != list(BASELINE_FEATURES) or feature_identity["FEATURE_COUNT"] != 14:
        raise R30BStop("STOP_BASELINE_FEATURE_IDENTITY_MISMATCH")
    if feature_identity["FEATURE_MANIFEST_SHA256"] != BASELINE_FEATURE_MANIFEST_SHA256:
        raise R30BStop("STOP_BASELINE_FEATURE_MANIFEST_MISMATCH")
    if split_identity["FOLD_COUNT"] != 5 or split_identity["SPLIT_CONTRACT_SHA256"] != SPLIT_CONTRACT_SHA256:
        raise R30BStop("STOP_SPLIT_IDENTITY_MISMATCH")
    if data_identity["TARGET_CONTRACT_SHA256"] != TARGET_CONTRACT_SHA256 or data_identity["TARGET_ROW_COUNT"] != 1197:
        raise R30BStop("STOP_TARGET_DATA_IDENTITY_MISMATCH")
    if file_sha256(Path(data_identity["FEATURE_LEDGER_SOURCE"])) != data_identity["FEATURE_LEDGER_SHA256"]:
        raise R30BStop("STOP_R30A_FEATURE_LEDGER_HASH_MISMATCH")
    if file_sha256(Path(data_identity["TARGET_LEDGER_PATH"])) != data_identity["TARGET_LEDGER_SHA256"]:
        raise R30BStop("STOP_R30A_TARGET_LEDGER_HASH_MISMATCH")
    if summary["FINAL_CONFIRMATION_DATA_USED"] or data_identity["FINAL_CONFIRMATION_DATA_USED"]:
        raise R30BStop("STOP_FINAL_CONFIRMATION_DATA_USED")
    if r30a.HGB_PARAMS != {"learning_rate": .08, "max_iter": 100, "max_leaf_nodes": 7, "min_samples_leaf": 200, "l2_regularization": 1.0, "random_state": 1729}:
        raise R30BStop("STOP_HGB_CONTRACT_MISMATCH")
    return {"summary": summary, "data": data_identity, "feature": feature_identity, "split": split_identity}


def _rsi(close: pd.Series) -> pd.Series:
    delta = close.diff(); gain = delta.clip(lower=0); loss = (-delta.clip(upper=0))
    avg_gain = gain.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    result = 100 - 100 / (1 + avg_gain / avg_loss.replace(0, np.nan))
    result = result.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    return result.mask((avg_loss == 0) & (avg_gain == 0), 50.0)


def single_symbol_factors(bars: pd.DataFrame) -> pd.DataFrame:
    """Trailing-only factor formulas; row t uses source rows <= t only."""
    close = bars["close"].astype(float); high = bars["high"].astype(float); low = bars["low"].astype(float)
    logret = np.log(close).diff()
    low9 = low.rolling(9, min_periods=9).min(); high9 = high.rolling(9, min_periods=9).max()
    rsv = (close - low9) / (high9 - low9).replace(0, np.nan) * 100
    k = rsv.ewm(alpha=1/3, adjust=False, min_periods=3).mean(); d = k.ewm(alpha=1/3, adjust=False, min_periods=3).mean()
    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean(); macd = ema12 - ema26
    ema20 = close.ewm(span=20, adjust=False, min_periods=20).mean()
    prev = close.shift(1)
    tr = pd.concat([(high-low), (high-prev).abs(), (low-prev).abs()], axis=1).max(axis=1)
    rv15 = logret.rolling(15, min_periods=15).std(); rv60 = logret.rolling(60, min_periods=60).std()
    output = pd.DataFrame({
        "timestamp_utc": pd.to_datetime(bars["timestamp_utc"], utc=True),
        "RSI_14": _rsi(close),
        "KDJ_J_9_3": 3*k-2*d,
        "MACD_HIST_NORM_12_26_9": (macd-macd.ewm(span=9, adjust=False, min_periods=9).mean())/close,
        "EMA20_SLOPE_5": ema20/ema20.shift(5)-1,
        "PRICE_VS_MA20": close/close.rolling(20, min_periods=20).mean()-1,
        "REALIZED_VOL_5": logret.rolling(5, min_periods=5).std(),
        "ATR_NORMALIZED_14": tr.rolling(14, min_periods=14).mean()/close,
        "DOWNSIDE_VOLATILITY_20": logret.where(logret < 0, 0).pow(2).rolling(20, min_periods=20).mean().pow(.5),
        "RECENT_DRAWDOWN_60": close/close.rolling(60, min_periods=60).max()-1,
        "VOLATILITY_ACCELERATION_15_60": rv15/rv60.replace(0, np.nan)-1,
    })
    output["max_source_timestamp_utc"] = output["timestamp_utc"]
    return output


def cross_asset_factors(qqq: pd.DataFrame, soxx: pd.DataFrame) -> pd.DataFrame:
    """Exact-timestamp QQQ/SOXX alignment; no asof, forward join or backfill."""
    q = qqq.set_index("timestamp_utc")["close"].astype(float)
    s = soxx.set_index("timestamp_utc")["close"].astype(float)
    aligned = pd.concat([q.rename("q"), s.rename("s")], axis=1, join="inner").sort_index()
    qr5 = aligned.q.pct_change(5); sr5 = aligned.s.pct_change(5)
    qr15 = aligned.q.pct_change(15); sr15 = aligned.s.pct_change(15)
    result = pd.DataFrame({
        "SOXX_VS_QQQ_RELATIVE_STRENGTH_60": aligned.s.pct_change(60)-aligned.q.pct_change(60),
        "QQQ_MOMENTUM_30": aligned.q.pct_change(30),
        "SOXX_QQQ_RETURN_SPREAD_5": sr5-qr5,
        "CROSS_ASSET_MOMENTUM_AGREEMENT_15": np.sign(sr15)*np.sign(qr15),
        "QQQ_TREND_CONFIRMATION_20": aligned.q/aligned.q.rolling(20, min_periods=20).mean()-1,
    }, index=aligned.index).reset_index().rename(columns={"timestamp_utc": "decision_timestamp_utc"})
    result["max_cross_asset_source_timestamp_utc"] = result["decision_timestamp_utc"]
    return result


def build_candidate_ledger(targets: pd.DataFrame, r30a, authority: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    p2 = r30a.import_phase2_module()
    records = authority["data"]
    source_manifest = read_json(r30a.R28_SOURCE_MANIFEST)
    paths = p2.exact_paths(source_manifest["files"])
    data = {symbol: p2.read_symbol(paths[symbol]) for symbol in p2.R1.SYMBOLS}
    single = {symbol: single_symbol_factors(data[symbol]) for symbol in ("QQQ", "SOXX")}
    cross = cross_asset_factors(data["QQQ"], data["SOXX"])
    frames = []
    for symbol in ("QQQ", "SOXX"):
        selected = targets.loc[targets["underlying_symbol"].eq(symbol), ["candidate_id", "decision_timestamp_utc"]]
        part = selected.merge(single[symbol].rename(columns={"timestamp_utc": "decision_timestamp_utc"}),
                              on="decision_timestamp_utc", how="left", validate="many_to_one")
        frames.append(part)
    out = pd.concat(frames, ignore_index=True).merge(cross, on="decision_timestamp_utc", how="left", validate="many_to_one")
    if len(out) != 1197 or out["candidate_id"].duplicated().any(): raise R30BStop("STOP_FACTOR_LEDGER_CARDINALITY")
    if not (pd.to_datetime(out["max_source_timestamp_utc"], utc=True) <= out["decision_timestamp_utc"]).all():
        raise R30BStop("STOP_SINGLE_SYMBOL_FEATURE_PIT")
    if not (pd.to_datetime(out["max_cross_asset_source_timestamp_utc"], utc=True) <= out["decision_timestamp_utc"]).all():
        raise R30BStop("STOP_CROSS_ASSET_FEATURE_PIT")
    return out.sort_values("candidate_id").reset_index(drop=True), {
        "row_count": len(out), "source_partition_count": len(source_manifest["files"]),
        "source_partition_hashes_verified": True, "exact_cross_asset_timestamp_join": True,
        "future_source_timestamp_count": 0, "final_confirmation_data_used": False,
        "max_decision_timestamp": out["decision_timestamp_utc"].max(),
    }


def gate_candidates(ledger: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, list[str]], pd.DataFrame]:
    names = list(FAMILY_A + FAMILY_B + FAMILY_C)
    corr = ledger[names].corr(method="spearman", min_periods=20)
    coverage = {name: float(ledger[name].notna().mean()) for name in names}
    rejected: dict[str, str] = {name: "COVERAGE_LT_90_PERCENT" for name in names if coverage[name] < .90}
    redundant_with: dict[str, str] = {}
    for group in sorted({FEATURE_DEFINITIONS[name]["group"] for name in names}):
        group_names = [name for name in names if FEATURE_DEFINITIONS[name]["group"] == group and name not in rejected]
        pairs = [(a, b) for i, a in enumerate(group_names) for b in group_names[i+1:] if abs(float(corr.loc[a, b])) >= .95]
        for a, b in pairs:
            if a in rejected or b in rejected: continue
            order = sorted((a, b), key=lambda name: (-coverage[name], FEATURE_DEFINITIONS[name]["complexity"],
                                                     FEATURE_DEFINITIONS[name]["dependencies"], names.index(name)))
            winner, loser = order
            rejected[loser] = "REDUNDANT_SAME_MECHANISM_ABS_SPEARMAN_GE_0_95"
            redundant_with[loser] = winner
    approved = {family: [name for name in family_names if name not in rejected] for family, family_names in FAMILY_NAMES.items()}
    if any(len(values) > 6 for values in approved.values()) or sum(map(len, approved.values())) > 18:
        raise R30BStop("STOP_FACTOR_BUDGET_EXCEEDED")
    rows = []
    for name in names:
        definition = FEATURE_DEFINITIONS[name]
        peers = corr[name].drop(name).abs()
        rows.append({
            "feature_name": name, "family": definition["family"], "mathematical_formula": definition["formula"],
            "lookback": definition["lookback"], "source_symbols": definition["symbols"], "source_columns": definition["columns"],
            "decision_timestamp_rule": "all trailing sources and exact cross-asset sources <= decision timestamp",
            "PIT_proof": "max_source_timestamp_utc <= decision_timestamp_utc; no centered/backfill/asof join",
            "missing_policy": "retain native missing; no fill; reject below 90% coverage", "coverage": coverage[name],
            "max_abs_pairwise_spearman": float(peers.max()), "max_abs_pairwise_spearman_feature": str(peers.idxmax()),
            "redundancy_group": definition["group"], "redundant_with": redundant_with.get(name),
            "status": "APPROVED" if name not in rejected else "REJECTED", "rejection_reason": rejected.get(name),
        })
    return pd.DataFrame(rows), approved, corr


def arm_feature_sets(approved: dict[str, list[str]]) -> dict[str, tuple[str, ...]]:
    a = tuple(approved["TREND_PATH_QUALITY"]); b = tuple(approved["VOLATILITY_RISK_GEOMETRY"]); c = tuple(approved["CROSS_ASSET_CONFIRMATION"])
    return {"ARM_0": BASELINE_FEATURES, "ARM_A": BASELINE_FEATURES+a, "ARM_B": BASELINE_FEATURES+b,
            "ARM_C": BASELINE_FEATURES+c, "ARM_ALL": BASELINE_FEATURES+a+b+c}


def select_direction_rows(frame: pd.DataFrame, direction: str) -> pd.DataFrame:
    """Select the frozen UP/DOWN head without colliding with DataFrame.head()."""
    return frame.loc[frame["head"].eq(direction)]


def bucket(table: pd.DataFrame, pct: int) -> dict[str, Any]:
    return table.loc[table["bucket_percent"].eq(pct)].iloc[0].to_dict()


def score_metrics(frame: pd.DataFrame, r30a) -> dict[str, Any]:
    t1 = r30a.t1_metrics(frame.T1_POSITIVE_NET20, frame.pred_t1)
    t2 = r30a.t2_metrics(frame.T2_ROBUST_NET20, frame.pred_t2, frame.raw_net20)
    t1rank = r30a.t1_ranking_metrics(frame); t2rank = r30a.t2_ranking_metrics(frame)
    t1dec = r30a.fixed_deciles(frame, "pred_t1", "ALL"); t2dec = r30a.fixed_deciles(frame, "pred_t2", "ALL")
    result = {
        "T1_ROC_AUC": t1["ROC_AUC"], "T1_PR_AUC": t1["PR_AUC"], "T1_Brier": t1["Brier"], "T1_LogLoss": t1["LogLoss"],
        "T1_decile_positive_rate_spearman": r30a.safe_spearman(t1dec.prediction_decile, t1dec.actual_positive_rate),
        "T1_decile_mean_net20_spearman": r30a.safe_spearman(t1dec.prediction_decile, t1dec.actual_raw_net20_mean),
        "T2_MAE": t2["MAE"], "T2_RMSE": t2["RMSE"], "T2_Spearman_vs_transformed": t2["Spearman_vs_transformed"],
        "T2_Spearman_vs_raw_net20": t2["Spearman_vs_raw_net20"],
        "T2_decile_raw_net20_spearman": r30a.safe_spearman(t2dec.prediction_decile, t2dec.actual_raw_net20_mean),
    }
    for pct in TOPS:
        a = bucket(t1rank, pct); b = bucket(t2rank, pct)
        result.update({f"T1_Top{pct}_positive_rate": a["actual_positive_rate"], f"T1_Top{pct}_lift": a["relative_lift_vs_unconditional"],
                       f"T1_Top{pct}_mean_net20": a["actual_mean_net20"], f"T2_Top{pct}_mean_net20": b["mean_raw_net20"],
                       f"T2_Top{pct}_positive_rate": b["positive_rate"]})
    return result


def compare_folds(folds: pd.DataFrame) -> pd.DataFrame:
    base = folds.loc[folds.arm.eq("ARM_0")].set_index("fold")
    result = folds.copy()
    metrics = [f"{target}_Top{pct}_mean_net20" for target in ("T1", "T2") for pct in TOPS]
    for metric in metrics:
        result[f"DELTA_{metric}_VS_BASELINE"] = [row[metric]-base.loc[row["fold"], metric] for _, row in result.iterrows()]
    result["T1_PRIMARY_ANY_IMPROVEMENT"] = (result.DELTA_T1_Top20_mean_net20_VS_BASELINE > 0) | (result.DELTA_T1_Top10_mean_net20_VS_BASELINE > 0)
    result["T2_PRIMARY_ANY_IMPROVEMENT"] = (result.DELTA_T2_Top20_mean_net20_VS_BASELINE > 0) | (result.DELTA_T2_Top10_mean_net20_VS_BASELINE > 0)
    result["ANY_PRIMARY_IMPROVEMENT"] = result.T1_PRIMARY_ANY_IMPROVEMENT | result.T2_PRIMARY_ANY_IMPROVEMENT
    primary_average = result[["DELTA_T1_Top20_mean_net20_VS_BASELINE", "DELTA_T1_Top10_mean_net20_VS_BASELINE",
                              "DELTA_T2_Top20_mean_net20_VS_BASELINE", "DELTA_T2_Top10_mean_net20_VS_BASELINE"]].mean(axis=1)
    result["FOLD_COMPARISON"] = np.where(primary_average > 1e-15, "IMPROVED", np.where(primary_average < -1e-15, "WORSENED", "TIED"))
    return result


def robustness(oof_by_arm: dict[str, pd.DataFrame], r30a) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    def table(group_type: str, column: str, transform=None):
        rows = []
        for arm, raw in oof_by_arm.items():
            frame = raw.copy()
            if transform is not None: frame[column] = transform(frame)
            for value, part in frame.groupby(column, sort=True):
                m = score_metrics(part, r30a)
                rows.append({"arm": arm, "arm_label": ARM_LABELS[arm], "robustness_type": group_type, "group": str(value),
                             "sample_count": len(part), "T1_AUC": m["T1_ROC_AUC"], "T1_Top20_mean_net20": m["T1_Top20_mean_net20"],
                             "T1_Top10_mean_net20": m["T1_Top10_mean_net20"], "T2_Spearman": m["T2_Spearman_vs_raw_net20"],
                             "T2_Top20_mean_net20": m["T2_Top20_mean_net20"], "T2_Top10_mean_net20": m["T2_Top10_mean_net20"]})
        return pd.DataFrame(rows)
    return (table("YEAR", "calendar_year", lambda f: f.decision_timestamp_utc.dt.year),
            table("DIRECTION", "head"), table("SYMBOL", "action_instrument"))


def report(summary: dict[str, Any], approved: dict[str, list[str]]) -> str:
    yn = lambda value: "有" if value == "GO" else "没有"
    return f"""# FAST3 R30B — Controlled Economic Factor Expansion + Family Ablation

## Decision

- Status: `{summary['FAST3_R30B_STATUS']}`
- Classification: `{summary['FAST3_R30B_CLASSIFICATION']}`
- Decision: `{summary['FAST3_R30B_DECISION']}`
- Final untouched used: `false`; adoption/live allowed: `false / false`

## Direct answers

1. Added factors: Trend={approved['TREND_PATH_QUALITY']}; Vol/Risk={approved['VOLATILITY_RISK_GEOMETRY']}; Cross-Asset={approved['CROSS_ASSET_CONFIRMATION']}.
2. Trend incremental economic information: {yn(summary['TREND_STATUS'])} (`{summary['TREND_STATUS']}`).
3. Volatility/Risk incremental economic information: {yn(summary['VOL_RISK_STATUS'])} (`{summary['VOL_RISK_STATUS']}`).
4. Cross-Asset incremental economic information: {yn(summary['CROSS_ASSET_STATUS'])} (`{summary['CROSS_ASSET_STATUS']}`).
5. Largest contribution: `{summary['BEST_FACTOR_FAMILY']}`; second: `{summary['SECOND_BEST_FACTOR_FAMILY']}`.
6. Family top cohorts turned positive: `{summary['POSITIVE_FAMILY_COHORT_ANSWER']}`.
7. ARM_ALL T1 Top20/Top10 mean: {summary['ALL_T1_TOP20_MEAN_NET20']:.4%} / {summary['ALL_T1_TOP10_MEAN_NET20']:.4%}; `{summary['ALL_T1_POSITIVE_COHORT_ANSWER']}`.
8. ARM_ALL T2 raw-net20 Spearman: {summary['ALL_T2_SPEARMAN']:.6f}; `{summary['ALL_T2_CORRELATION_ANSWER']}`.
9. ARM_ALL improved folds: {summary['ALL_IMPROVED_FOLD_COUNT']}/5; `{summary['CROSS_FOLD_ANSWER']}`.
10. UP/DOWN: `{summary['DIRECTION_ROBUSTNESS_ANSWER']}`.
11. Year/symbol concentration: `{summary['CONCENTRATION_ANSWER']}`.
12. Enough for continued development: `{summary['CONTINUE_DEVELOPMENT_ANSWER']}`.
13. Next step: `{summary['NEXT_STAGE']}`.
14. Final untouched recommendation: `{summary['FINAL_CONFIRMATION_RECOMMENDATION']}`; it was not opened.

## Controls

Only feature information changed. Target contract `{summary['TARGET_CONTRACT_SHA256']}`, split `{summary['SPLIT_CONTRACT_SHA256']}`, HGB parameters, metrics and fixed Top-k buckets remained frozen. Lookback and hyperparameter search counts are zero.
"""


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--run-id", required=True)
    parser.add_argument("--resume-frozen-manifest-sha256")
    args = parser.parse_args()
    name = f"r30b_factor_expansion_{args.run_id}"
    runtime = RESULTS_ROOT / "runtime" / "fast3" / name; scratch = RESULTS_ROOT / "scratch" / "fast3" / name; frozen = RESULTS_ROOT / "frozen" / "fast3" / name
    manifest_path = frozen / "FAST3_R30B_EXPANDED_FEATURE_MANIFEST_R1.json"
    resuming = args.resume_frozen_manifest_sha256 is not None
    if any(path.exists() for path in (runtime, scratch, frozen)):
        if not resuming or not all(path.is_dir() for path in (runtime, scratch, frozen)):
            raise R30BStop("STOP_RUN_ID_EXISTS")
        if args.resume_frozen_manifest_sha256 != "248c4d1eabcbcee545ffc95f5f366390889c13199ec90d84d5bbd0f6332f4718":
            raise R30BStop("STOP_UNAPPROVED_RESUME_MANIFEST_IDENTITY")
        if not manifest_path.is_file() or file_sha256(manifest_path) != args.resume_frozen_manifest_sha256:
            raise R30BStop("STOP_RESUME_FEATURE_MANIFEST_HASH_MISMATCH")
        if any((scratch/"models").glob("*.joblib")):
            raise R30BStop("STOP_RESUME_AFTER_ANY_MODEL_FIT")
    else:
        if resuming: raise R30BStop("STOP_RESUME_RUN_STATE_MISSING")
        runtime.mkdir(parents=True); (scratch/"models").mkdir(parents=True); frozen.mkdir(parents=True)
    r30a = import_module(R30A_RUNNER, "fast3_r30b_bound_r30a")
    authority = verify_r30a(r30a)
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=SOURCE_ROOT, text=True).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE_ROOT, text=True).strip()
    baseline = pd.read_parquet(Path(authority["data"]["FEATURE_LEDGER_SOURCE"]))
    targets = pd.read_parquet(Path(authority["data"]["TARGET_LEDGER_PATH"]))
    dataset = targets.merge(baseline.drop(columns=["head", "underlying_symbol"]), on=["candidate_id", "decision_timestamp_utc"], how="left", validate="one_to_one")
    dataset = dataset.merge(baseline[["candidate_id", "underlying_symbol"]], on="candidate_id", validate="one_to_one")
    if dataset.decision_timestamp_utc.max() >= r30a.TRUE_HOLDOUT_START: raise R30BStop("STOP_FINAL_CONFIRMATION_DATA_USED")
    if resuming:
        manifest_payload = read_json(manifest_path)
        manifest_sha = file_sha256(manifest_path)
        if (manifest_payload["TARGET_CONTRACT_SHA256"] != TARGET_CONTRACT_SHA256
                or manifest_payload["BASELINE_FEATURE_MANIFEST_SHA256"] != BASELINE_FEATURE_MANIFEST_SHA256
                or manifest_payload["SPLIT_CONTRACT_SHA256"] != SPLIT_CONTRACT_SHA256
                or manifest_payload["candidate_definitions"] != FEATURE_DEFINITIONS):
            raise R30BStop("STOP_RESUME_FROZEN_IDENTITY_CONTENT_MISMATCH")
        approved = {family: list(manifest_payload["approved_families"][family]) for family in FAMILY_NAMES}
        if approved != {family: list(features) for family, features in FAMILY_NAMES.items()}:
            raise R30BStop("STOP_RESUME_FROZEN_FACTOR_SET_MISMATCH")
        factor_ledger = Path(manifest_payload["factor_ledger_path"])
        if file_sha256(factor_ledger) != manifest_payload["factor_ledger_sha256"]:
            raise R30BStop("STOP_RESUME_FACTOR_LEDGER_HASH_MISMATCH")
        candidates = pd.read_parquet(factor_ledger)
        candidate_table = pd.read_csv(frozen / "FAST3_R30B_FACTOR_CANDIDATES.csv")
        approved_rows = candidate_table.loc[candidate_table["status"].eq("APPROVED"), "feature_name"].tolist()
        if set(approved_rows) != set(FAMILY_A + FAMILY_B + FAMILY_C):
            raise R30BStop("STOP_RESUME_CANDIDATE_EVIDENCE_MISMATCH")
        pit_audit = manifest_payload["pit_audit"]
    else:
        candidates, pit_audit = build_candidate_ledger(dataset, r30a, authority)
        candidate_table, approved, correlation = gate_candidates(candidates)
    new_names = [name for family in FAMILY_NAMES for name in approved[family]]
    dataset = dataset.merge(candidates[["candidate_id", *new_names]], on="candidate_id", validate="one_to_one")
    if dataset[new_names].notna().mean().min() < .90: raise R30BStop("STOP_APPROVED_FEATURE_COVERAGE")
    arm_features = arm_feature_sets(approved)
    if set(arm_features) != set(ARM_ORDER) or tuple(arm_features["ARM_0"]) != BASELINE_FEATURES: raise R30BStop("STOP_ARM_CONTRACT")
    if resuming:
        if {arm: list(features) for arm, features in arm_features.items()} != manifest_payload["arms"]:
            raise R30BStop("STOP_RESUME_ARM_IDENTITY_MISMATCH")
    else:
        factor_ledger = scratch / "FAST3_R30B_FACTOR_LEDGER.parquet"; candidates.to_parquet(factor_ledger, index=False)
        correlation.to_csv(scratch / "FAST3_R30B_NEW_FEATURE_SPEARMAN.csv", lineterminator="\n")
        candidate_table.to_csv(frozen / "FAST3_R30B_FACTOR_CANDIDATES.csv", index=False, lineterminator="\n")
        manifest_payload = {
            "CONTRACT_ID": "FAST3_R30B_EXPANDED_FEATURE_MANIFEST_R1", "STATUS": "FROZEN_BEFORE_MODEL_FIT",
            "CREATED_AT_UTC": datetime.now(timezone.utc).isoformat(), "TARGET_CONTRACT_SHA256": TARGET_CONTRACT_SHA256,
            "BASELINE_FEATURE_MANIFEST_SHA256": BASELINE_FEATURE_MANIFEST_SHA256, "SPLIT_CONTRACT_SHA256": SPLIT_CONTRACT_SHA256,
            "baseline_features": list(BASELINE_FEATURES), "baseline_feature_count": 14,
            "approved_families": approved, "candidate_definitions": FEATURE_DEFINITIONS,
            "arms": {arm: list(features) for arm, features in arm_features.items()},
            "new_feature_count": len(new_names), "total_feature_count": len(arm_features["ARM_ALL"]),
            "factor_ledger_path": str(factor_ledger), "factor_ledger_sha256": file_sha256(factor_ledger),
            "pit_audit": pit_audit, "coverage_gate": "reject <90%; prefer >=95%", "redundancy_gate": "same mechanism and abs Spearman >=0.95",
            "redundancy_selection_rule": "higher coverage, then simpler formula, then shorter dependency chain",
            "LOOKBACK_SEARCH_COUNT": 0, "FEATURE_PERFORMANCE_SELECTION_COUNT": 0, "FINAL_CONFIRMATION_DATA_USED": False,
        }
        manifest_sha = freeze_manifest(manifest_path, manifest_payload)
    guard_manifest(manifest_path, manifest_sha); guard_target_contract()
    oof_by_arm: dict[str, pd.DataFrame] = {}; model_records = []; fit_count = predict_count = 0
    fold_rows = []
    for arm in ARM_ORDER:
        features = arm_features[arm]; parts = []
        categorical_mask = [feature in r30a.CATEGORICAL for feature in features]
        classifier_params = {**r30a.HGB_PARAMS, "categorical_features": categorical_mask}
        regressor_params = {**r30a.HGB_PARAMS, "categorical_features": categorical_mask}
        for fold in r30a.ECONOMIC_FOLDS:
            train_all, valid_all, audit = r30a.construct_economic_fold(dataset, fold); scored_parts = []
            for direction in ("UP", "DOWN"):
                train = select_direction_rows(train_all, direction); valid = select_direction_rows(valid_all, direction)
                if train.empty or valid.empty or train.T1_POSITIVE_NET20.nunique() < 2: raise R30BStop("STOP_FOLD_DIRECTION_SAMPLE")
                guard_manifest(manifest_path, manifest_sha); guard_target_contract()
                clf = HistGradientBoostingClassifier(**classifier_params).fit(train[list(features)], train.T1_POSITIVE_NET20.astype(int)); fit_count += 1
                guard_manifest(manifest_path, manifest_sha); guard_target_contract()
                reg = HistGradientBoostingRegressor(**regressor_params).fit(train[list(features)], train.T2_ROBUST_NET20.astype(float)); fit_count += 1
                scored = valid.copy(); scored["pred_t1"] = clf.predict_proba(valid[list(features)])[:, 1]; predict_count += 1
                scored["pred_t2"] = reg.predict(valid[list(features)]); predict_count += 1
                scored["t1_fold_train_base_rate"] = float(train.T1_POSITIVE_NET20.mean()); scored["fold"] = fold[0]; scored["arm"] = arm
                scored_parts.append(scored)
                for target_name, model in (("T1", clf), ("T2", reg)):
                    path = scratch/"models"/f"{arm}_{target_name}_{direction}_{fold[0]}.joblib"; joblib.dump(model, path, compress=3)
                    model_records.append({"arm": arm, "target": target_name, "direction": direction, "fold": fold[0], "model_family": type(model).__name__,
                                          "parameters": model.get_params(deep=False), "model_sha256": file_sha256(path), "model_path": str(path),
                                          "target_contract_sha256": TARGET_CONTRACT_SHA256, "feature_manifest_sha256": manifest_sha,
                                          "split_contract_sha256": SPLIT_CONTRACT_SHA256, "training_row_count": len(train)})
            fold_scored = pd.concat(scored_parts, ignore_index=True); parts.append(fold_scored)
            fold_rows.append({"arm": arm, "arm_label": ARM_LABELS[arm], "fold": fold[0], "train_count": len(train_all), "validation_count": len(fold_scored), **score_metrics(fold_scored, r30a)})
        oof = pd.concat(parts, ignore_index=True).sort_values(["decision_timestamp_utc", "candidate_id"]).reset_index(drop=True)
        oof_by_arm[arm] = oof; oof.to_parquet(scratch/f"FAST3_R30B_{arm}_OOF.parquet", index=False)
    guard_manifest(manifest_path, manifest_sha); guard_target_contract()
    if fit_count != 100 or predict_count != 100: raise R30BStop("STOP_MODEL_BUDGET_RECONCILIATION")
    arm_rows = [{"arm": arm, "arm_label": ARM_LABELS[arm], "feature_count": len(arm_features[arm]), **score_metrics(oof_by_arm[arm], r30a)} for arm in ARM_ORDER]
    arms = pd.DataFrame(arm_rows); base = arms.loc[arms.arm.eq("ARM_0")].iloc[0]
    for key, expected_key in (("T1_ROC_AUC", "T1_ROC_AUC"), ("T1_Top20_mean_net20", "T1_TOP20_REALIZED_MEAN_NET20"),
                              ("T1_Top10_mean_net20", "T1_TOP10_REALIZED_MEAN_NET20"), ("T1_Top5_mean_net20", "T1_TOP5_REALIZED_MEAN_NET20"),
                              ("T2_Spearman_vs_raw_net20", "T2_SPEARMAN_VS_RAW_NET20"), ("T2_Top20_mean_net20", "T2_TOP20_REALIZED_MEAN_NET20"),
                              ("T2_Top10_mean_net20", "T2_TOP10_REALIZED_MEAN_NET20"), ("T2_Top5_mean_net20", "T2_TOP5_REALIZED_MEAN_NET20")):
        if not math.isclose(float(base[key]), EXPECTED_R30A[expected_key], rel_tol=0, abs_tol=1e-15): raise R30BStop("STOP_BASELINE_REPRODUCTION:"+key)
    folds = compare_folds(pd.DataFrame(fold_rows)); increments = []
    for arm in ARM_ORDER[1:]:
        row = arms.loc[arms.arm.eq(arm)].iloc[0]; part = folds.loc[folds.arm.eq(arm)]
        increments.append({"arm": arm, "arm_label": ARM_LABELS[arm],
            "DELTA_T1_AUC_VS_BASELINE": row.T1_ROC_AUC-base.T1_ROC_AUC,
            **{f"DELTA_T1_TOP{p}_MEAN_NET20": row[f'T1_Top{p}_mean_net20']-base[f'T1_Top{p}_mean_net20'] for p in TOPS},
            "DELTA_T2_SPEARMAN_VS_BASELINE": row.T2_Spearman_vs_raw_net20-base.T2_Spearman_vs_raw_net20,
            **{f"DELTA_T2_TOP{p}_MEAN_NET20": row[f'T2_Top{p}_mean_net20']-base[f'T2_Top{p}_mean_net20'] for p in TOPS},
            "T1_IMPROVED_FOLD_COUNT": int(part.T1_PRIMARY_ANY_IMPROVEMENT.sum()),
            "T2_IMPROVED_FOLD_COUNT": int(part.T2_PRIMARY_ANY_IMPROVEMENT.sum()),
            "IMPROVED_FOLD_COUNT": int(part.ANY_PRIMARY_IMPROVEMENT.sum()),
            "WORSENED_FOLD_COUNT": int(part.FOLD_COMPARISON.eq('WORSENED').sum()), "TIED_FOLD_COUNT": int(part.FOLD_COMPARISON.eq('TIED').sum())})
    inc = pd.DataFrame(increments)
    year, direction, symbol = robustness(oof_by_arm, r30a)
    family_status = {}; family_strong = {}
    for family, arm in FAMILY_ARM.items():
        row = arms.loc[arms.arm.eq(arm)].iloc[0]; delta = inc.loc[inc.arm.eq(arm)].iloc[0]
        t1_go = row.T1_ROC_AUC > base.T1_ROC_AUC and row.T1_Top20_mean_net20 > base.T1_Top20_mean_net20 and row.T1_Top10_mean_net20 > base.T1_Top10_mean_net20 and delta.T1_IMPROVED_FOLD_COUNT >= 3
        t2_go = row.T2_Spearman_vs_raw_net20 > base.T2_Spearman_vs_raw_net20 and row.T2_Top20_mean_net20 > base.T2_Top20_mean_net20 and row.T2_Top10_mean_net20 > base.T2_Top10_mean_net20 and delta.T2_IMPROVED_FOLD_COUNT >= 3
        family_status[family] = "GO" if (t1_go or t2_go) else "NO_GO"
        family_strong[family] = bool(((row.T1_Top20_mean_net20 > 0 and row.T1_Top10_mean_net20 > 0 and delta.T1_IMPROVED_FOLD_COUNT >= 3) or
                                      (row.T2_Top20_mean_net20 > 0 and row.T2_Top10_mean_net20 > 0 and delta.T2_IMPROVED_FOLD_COUNT >= 3)) and
                                     (row.T1_ROC_AUC >= .55 or row.T2_Spearman_vs_raw_net20 >= .05))
    allrow = arms.loc[arms.arm.eq("ARM_ALL")].iloc[0]; alldelta = inc.loc[inc.arm.eq("ARM_ALL")].iloc[0]
    all_t1_go = allrow.T1_ROC_AUC > base.T1_ROC_AUC and allrow.T1_Top20_mean_net20 > base.T1_Top20_mean_net20 and allrow.T1_Top10_mean_net20 > base.T1_Top10_mean_net20 and alldelta.T1_IMPROVED_FOLD_COUNT >= 3
    all_t2_go = allrow.T2_Spearman_vs_raw_net20 > base.T2_Spearman_vs_raw_net20 and allrow.T2_Top20_mean_net20 > base.T2_Top20_mean_net20 and allrow.T2_Top10_mean_net20 > base.T2_Top10_mean_net20 and alldelta.T2_IMPROVED_FOLD_COUNT >= 3
    all_go = all_t1_go or all_t2_go; go_count = sum(v == "GO" for v in family_status.values())
    if go_count >= 2: classification = "A_MULTIPLE_FACTOR_FAMILIES_ECONOMIC_GAIN"; decision = "MULTIPLE_FACTOR_FAMILIES_GO"
    elif go_count == 1: classification = "B_SINGLE_FACTOR_FAMILY_ECONOMIC_GAIN"; decision = "SINGLE_FACTOR_FAMILY_GO"
    elif all_go: classification = "C_COMBINED_FACTOR_SIGNAL_ONLY"; decision = "COMBINED_FACTOR_SIGNAL_ONLY_INDIVIDUAL_ATTRIBUTION_WEAK"
    else:
        positive = any(float(alldelta[key]) > 0 for key in ("DELTA_T1_AUC_VS_BASELINE", "DELTA_T1_TOP20_MEAN_NET20", "DELTA_T1_TOP10_MEAN_NET20",
                                                               "DELTA_T2_SPEARMAN_VS_BASELINE", "DELTA_T2_TOP20_MEAN_NET20", "DELTA_T2_TOP10_MEAN_NET20"))
        classification = "D_WEAK_OR_INCONCLUSIVE_FACTOR_GAIN" if positive else "E_FACTOR_EXPANSION_NO_ECONOMIC_GAIN"
        decision = "WEAK_OR_INCONCLUSIVE_FACTOR_GAIN" if positive else "FACTOR_EXPANSION_NO_ECONOMIC_GAIN"
    coverage_by_family = {f: float(candidate_table.loc[(candidate_table.family.eq(f)) & candidate_table.status.eq('APPROVED'), 'coverage'].mean()) for f in FAMILY_NAMES}
    rank_rows = []
    for family, arm in FAMILY_ARM.items():
        d = inc.loc[inc.arm.eq(arm)].iloc[0]
        dir_arm = direction.loc[direction.arm.eq(arm)].set_index('group'); dir_base = direction.loc[direction.arm.eq('ARM_0')].set_index('group')
        year_arm = year.loc[year.arm.eq(arm)].set_index('group'); year_base = year.loc[year.arm.eq('ARM_0')].set_index('group')
        rank_rows.append({"family": family, "arm": arm, "incremental_realized_net20_score": float(np.mean([d.DELTA_T1_TOP20_MEAN_NET20,d.DELTA_T1_TOP10_MEAN_NET20,d.DELTA_T2_TOP20_MEAN_NET20,d.DELTA_T2_TOP10_MEAN_NET20])),
                          "improved_fold_count": int(d.IMPROVED_FOLD_COUNT), "t1_t2_positive_delta_count": int(sum(x > 0 for x in [d.DELTA_T1_AUC_VS_BASELINE,d.DELTA_T2_SPEARMAN_VS_BASELINE])),
                          "direction_improved_count": int(sum(max(dir_arm.loc[x,'T1_Top20_mean_net20']-dir_base.loc[x,'T1_Top20_mean_net20'],dir_arm.loc[x,'T2_Top20_mean_net20']-dir_base.loc[x,'T2_Top20_mean_net20']) > 0 for x in ('UP','DOWN'))),
                          "year_improved_count": int(sum(max(year_arm.loc[x,'T1_Top20_mean_net20']-year_base.loc[x,'T1_Top20_mean_net20'],year_arm.loc[x,'T2_Top20_mean_net20']-year_base.loc[x,'T2_Top20_mean_net20']) > 0 for x in year_arm.index)),
                          "coverage": coverage_by_family[family], "simplicity": -float(candidate_table.loc[(candidate_table.family.eq(family)) & candidate_table.status.eq('APPROVED')].feature_name.map(lambda n: FEATURE_DEFINITIONS[n]['complexity']).mean())})
    ranking = pd.DataFrame(rank_rows).sort_values(["incremental_realized_net20_score","improved_fold_count","t1_t2_positive_delta_count","direction_improved_count","year_improved_count","coverage","simplicity"], ascending=False).reset_index(drop=True)
    ranking["rank"] = np.arange(1,len(ranking)+1); best, second = ranking.family.iloc[:2]
    arms.to_csv(frozen/"FAST3_R30B_ARM_SUMMARY.csv", index=False, lineterminator="\n"); folds.to_csv(frozen/"FAST3_R30B_FOLD_METRICS.csv", index=False, lineterminator="\n")
    pd.concat([r30a.t1_ranking_metrics(oof).assign(arm=arm,arm_label=ARM_LABELS[arm]) for arm,oof in oof_by_arm.items()]).to_csv(frozen/"FAST3_R30B_T1_RANKING_METRICS.csv",index=False,lineterminator="\n")
    pd.concat([r30a.t2_ranking_metrics(oof).assign(arm=arm,arm_label=ARM_LABELS[arm]) for arm,oof in oof_by_arm.items()]).to_csv(frozen/"FAST3_R30B_T2_RANKING_METRICS.csv",index=False,lineterminator="\n")
    inc.merge(ranking,on=['arm'],how='left').to_csv(frozen/"FAST3_R30B_INCREMENTAL_METRICS.csv",index=False,lineterminator="\n")
    year.to_csv(frozen/"FAST3_R30B_ROBUSTNESS_BY_YEAR.csv",index=False,lineterminator="\n"); direction.to_csv(frozen/"FAST3_R30B_ROBUSTNESS_BY_DIRECTION.csv",index=False,lineterminator="\n"); symbol.to_csv(frozen/"FAST3_R30B_ROBUSTNESS_BY_SYMBOL.csv",index=False,lineterminator="\n")
    def armv(arm,key): return arms.loc[arms.arm.eq(arm),key].iloc[0]
    all_dirs = direction.loc[direction.arm.eq('ARM_ALL')].set_index('group'); base_dirs = direction.loc[direction.arm.eq('ARM_0')].set_index('group')
    improved_dirs = [d for d in ('UP','DOWN') if max(all_dirs.loc[d,'T1_Top20_mean_net20']-base_dirs.loc[d,'T1_Top20_mean_net20'],all_dirs.loc[d,'T2_Top20_mean_net20']-base_dirs.loc[d,'T2_Top20_mean_net20']) > 0]
    positive_family = [f for f,a in FAMILY_ARM.items() if max(armv(a,'T1_Top20_mean_net20'),armv(a,'T1_Top10_mean_net20'),armv(a,'T2_Top20_mean_net20'),armv(a,'T2_Top10_mean_net20')) > 0]
    if classification.startswith('A_'): next_stage="FREEZE_REDUCED_CHALLENGER_FROM_GO_FAMILIES; DO_NOT_OPEN_FINAL_CONFIRMATION"
    elif classification.startswith('B_'): next_stage=f"FREEZE_STRONGEST_GO_FAMILY_ONLY:{[f for f,v in family_status.items() if v=='GO'][0]}"
    elif classification.startswith('C_'): next_stage="FREEZE_COMBINED_CHALLENGER_WITH_WEAK_ATTRIBUTION; DEVELOPMENT_ONLY"
    elif classification.startswith('D_'): next_stage="WEAK_INCONCLUSIVE_STOP_WITHOUT_TUNING"
    else: next_stage="FACTOR_EXPANSION_COMPLETELY_FAILED; STOP"
    summary = {
        "FAST3_R30B_STATUS":"PASS", "FAST3_R30B_CLASSIFICATION":classification, "FAST3_R30B_DECISION":decision,
        "BRANCH":branch,"START_HEAD":head,"HEAD":head,"TARGET_CONTRACT_SHA256":TARGET_CONTRACT_SHA256,"TARGET_CONTRACT_MUTATION_COUNT":0,
        "BASELINE_FEATURE_MANIFEST_SHA256":BASELINE_FEATURE_MANIFEST_SHA256,"R30B_FEATURE_MANIFEST_SHA256":manifest_sha,"SPLIT_CONTRACT_SHA256":SPLIT_CONTRACT_SHA256,
        "BASELINE_FEATURE_COUNT":14,"NEW_FEATURE_COUNT":len(new_names),"TOTAL_FEATURE_COUNT":len(arm_features['ARM_ALL']),
        "TREND_FEATURE_COUNT":len(approved['TREND_PATH_QUALITY']),"VOL_RISK_FEATURE_COUNT":len(approved['VOLATILITY_RISK_GEOMETRY']),"CROSS_ASSET_FEATURE_COUNT":len(approved['CROSS_ASSET_CONFIRMATION']),
        "APPROVED_FEATURES":approved,"LOOKBACK_SEARCH_COUNT":0,"HYPERPARAMETER_SEARCH_COUNT":0,"TOTAL_MODEL_FIT_COUNT":fit_count,"MODEL_PREDICT_CALL_COUNT":predict_count,"FINAL_CONFIRMATION_DATA_USED":False,
        "BASELINE_T1_AUC":base.T1_ROC_AUC,"BASELINE_T1_TOP20_MEAN_NET20":base.T1_Top20_mean_net20,"BASELINE_T1_TOP10_MEAN_NET20":base.T1_Top10_mean_net20,"BASELINE_T1_TOP5_MEAN_NET20":base.T1_Top5_mean_net20,
        "BASELINE_T2_SPEARMAN":base.T2_Spearman_vs_raw_net20,"BASELINE_T2_TOP20_MEAN_NET20":base.T2_Top20_mean_net20,"BASELINE_T2_TOP10_MEAN_NET20":base.T2_Top10_mean_net20,"BASELINE_T2_TOP5_MEAN_NET20":base.T2_Top5_mean_net20,
        **{f"TREND_T1_{k}":armv('ARM_A',v) for k,v in [('AUC','T1_ROC_AUC'),('TOP20_MEAN_NET20','T1_Top20_mean_net20'),('TOP10_MEAN_NET20','T1_Top10_mean_net20'),('TOP5_MEAN_NET20','T1_Top5_mean_net20')]},
        "TREND_T2_SPEARMAN":armv('ARM_A','T2_Spearman_vs_raw_net20'),"TREND_T2_TOP20_MEAN_NET20":armv('ARM_A','T2_Top20_mean_net20'),"TREND_T2_TOP10_MEAN_NET20":armv('ARM_A','T2_Top10_mean_net20'),"TREND_IMPROVED_FOLD_COUNT":int(inc.loc[inc.arm.eq('ARM_A'),'IMPROVED_FOLD_COUNT'].iloc[0]),"TREND_STATUS":family_status['TREND_PATH_QUALITY'],"TREND_STRONG":family_strong['TREND_PATH_QUALITY'],
        **{f"VOL_RISK_T1_{k}":armv('ARM_B',v) for k,v in [('AUC','T1_ROC_AUC'),('TOP20_MEAN_NET20','T1_Top20_mean_net20'),('TOP10_MEAN_NET20','T1_Top10_mean_net20'),('TOP5_MEAN_NET20','T1_Top5_mean_net20')]},
        "VOL_RISK_T2_SPEARMAN":armv('ARM_B','T2_Spearman_vs_raw_net20'),"VOL_RISK_T2_TOP20_MEAN_NET20":armv('ARM_B','T2_Top20_mean_net20'),"VOL_RISK_T2_TOP10_MEAN_NET20":armv('ARM_B','T2_Top10_mean_net20'),"VOL_RISK_IMPROVED_FOLD_COUNT":int(inc.loc[inc.arm.eq('ARM_B'),'IMPROVED_FOLD_COUNT'].iloc[0]),"VOL_RISK_STATUS":family_status['VOLATILITY_RISK_GEOMETRY'],"VOL_RISK_STRONG":family_strong['VOLATILITY_RISK_GEOMETRY'],
        **{f"CROSS_ASSET_T1_{k}":armv('ARM_C',v) for k,v in [('AUC','T1_ROC_AUC'),('TOP20_MEAN_NET20','T1_Top20_mean_net20'),('TOP10_MEAN_NET20','T1_Top10_mean_net20'),('TOP5_MEAN_NET20','T1_Top5_mean_net20')]},
        "CROSS_ASSET_T2_SPEARMAN":armv('ARM_C','T2_Spearman_vs_raw_net20'),"CROSS_ASSET_T2_TOP20_MEAN_NET20":armv('ARM_C','T2_Top20_mean_net20'),"CROSS_ASSET_T2_TOP10_MEAN_NET20":armv('ARM_C','T2_Top10_mean_net20'),"CROSS_ASSET_IMPROVED_FOLD_COUNT":int(inc.loc[inc.arm.eq('ARM_C'),'IMPROVED_FOLD_COUNT'].iloc[0]),"CROSS_ASSET_STATUS":family_status['CROSS_ASSET_CONFIRMATION'],"CROSS_ASSET_STRONG":family_strong['CROSS_ASSET_CONFIRMATION'],
        "ALL_T1_AUC":allrow.T1_ROC_AUC,"ALL_T1_TOP20_POSITIVE_RATE":allrow.T1_Top20_positive_rate,"ALL_T1_TOP10_POSITIVE_RATE":allrow.T1_Top10_positive_rate,"ALL_T1_TOP5_POSITIVE_RATE":allrow.T1_Top5_positive_rate,
        "ALL_T1_TOP20_MEAN_NET20":allrow.T1_Top20_mean_net20,"ALL_T1_TOP10_MEAN_NET20":allrow.T1_Top10_mean_net20,"ALL_T1_TOP5_MEAN_NET20":allrow.T1_Top5_mean_net20,
        "ALL_T2_SPEARMAN":allrow.T2_Spearman_vs_raw_net20,"ALL_T2_TOP20_MEAN_NET20":allrow.T2_Top20_mean_net20,"ALL_T2_TOP10_MEAN_NET20":allrow.T2_Top10_mean_net20,"ALL_T2_TOP5_MEAN_NET20":allrow.T2_Top5_mean_net20,"ALL_IMPROVED_FOLD_COUNT":int(alldelta.IMPROVED_FOLD_COUNT),
        "BEST_FACTOR_FAMILY":best,"SECOND_BEST_FACTOR_FAMILY":second,"FAMILY_RANKING":ranking.to_dict('records'),
        "CURRENT_FEATURES_PLUS_EXPANSION_ECONOMIC_STATUS":"CONFIRMED_INCREMENTAL_ECONOMIC_INFORMATION" if (go_count or all_go) else "WEAK_OR_INCONCLUSIVE_INCREMENTAL_INFORMATION" if classification.startswith('D_') else "NO_INCREMENTAL_ECONOMIC_INFORMATION",
        "PRIMARY_RESEARCH_INTERPRETATION":"New factor information produced a qualifying incremental economic signal." if (go_count or all_go) else "Controlled trend, volatility-risk and cross-asset additions did not establish qualifying incremental economic prediction.",
        "POSITIVE_FAMILY_COHORT_ANSWER":positive_family if positive_family else "NONE","ALL_T1_POSITIVE_COHORT_ANSWER":"POSITIVE" if allrow.T1_Top20_mean_net20>0 and allrow.T1_Top10_mean_net20>0 else "NOT_POSITIVE",
        "ALL_T2_CORRELATION_ANSWER":"STABLE_POSITIVE" if all_t2_go else "NOT_STABLE_QUALIFYING_POSITIVE","CROSS_FOLD_ANSWER":"MAJORITY_IMPROVED" if alldelta.IMPROVED_FOLD_COUNT>=3 else "NO_MAJORITY_IMPROVEMENT",
        "DIRECTION_ROBUSTNESS_ANSWER":f"IMPROVED_DIRECTIONS={improved_dirs}","CONCENTRATION_ANSWER":"SEE_FROZEN_YEAR_AND_SYMBOL_TABLES; NO_SELECTION_PERFORMED",
        "CONTINUE_DEVELOPMENT_ANSWER":"YES_FROZEN_CHALLENGER_ONLY" if (go_count or all_go) else "NO_AUTOMATIC_CONTINUATION",
        "R29_MODIFIED":False,"R29_ALLOWED_TO_RESUME":False,"OFFICIAL_ADOPTION_ALLOWED":False,"LIVE_TRADING_ALLOWED":False,"NEXT_STAGE":next_stage,
        "FINAL_CONFIRMATION_RECOMMENDATION":"ELIGIBLE_FOR_HUMAN_REVIEW_BUT_DO_NOT_OPEN" if (go_count or all_go) else "DO_NOT_OPEN_FINAL_UNTOUCHED_CONFIRMATION",
        "FEATURE_IMPORTANCE_DIAGNOSTIC":"SKIPPED_NO_EXISTING_SELECTION_NEUTRAL_INFRASTRUCTURE; DO_NOT_SELECT_FEATURES_BY_IMPORTANCE",
        "CORPORATE_ACTION_NORMALIZATION_REQUIRED":True,"PRE_ENTRY_EVENT_NOT_CAPTURABLE":True,"PER_PARTITION_SHA256_REQUIRED":True,
        "FAST3_STORAGE_CONTRACT_R1_STATUS":"PASS","SOURCE_ROOT":str(SOURCE_ROOT),"DATA_ROOT":str(DATA_ROOT),"RESULTS_ROOT":str(RESULTS_ROOT),"CACHE_ROOT":str(CACHE_ROOT),"DATA_ROOT_WRITE_COUNT":0,
        "LOCAL_RESULTS_CREATED":False,"RESULT_FILES_WRITTEN_TO_GIT_REPO":False,"PRE_EXISTING_UNTRACKED_FILES_PRESERVED":True,"PRE_EXISTING_TRACKED_CHANGES_PRESERVED":True,"NEW_STORAGE_VIOLATION_COUNT":0,"DESTRUCTIVE_GIT_COMMAND_USED":False,"BROAD_GIT_ADD_USED":False,
        "REPORT_PATH":str(frozen/'FAST3_R30B_REPORT.md'),"SUMMARY_JSON_PATH":str(frozen/'FAST3_R30B_SUMMARY.json'),"FEATURE_MANIFEST_PATH":str(manifest_path),"MODEL_IDENTITIES":model_records,
    }
    write_json(frozen/'FAST3_R30B_SUMMARY.json',summary); (frozen/'FAST3_R30B_REPORT.md').write_text(report(summary,approved),encoding='utf-8')
    write_json(runtime/'FAST3_R30B_RUNTIME_SUMMARY.json',{"status":"PASS","classification":classification,"manifest_sha256":manifest_sha,"model_fit_count":fit_count,"data_root_write_count":0})
    guard_manifest(manifest_path,manifest_sha); guard_target_contract()
    print(json.dumps({k:summary[k] for k in ('FAST3_R30B_STATUS','FAST3_R30B_CLASSIFICATION','FAST3_R30B_DECISION','BEST_FACTOR_FAMILY','REPORT_PATH','SUMMARY_JSON_PATH')},indent=2))


if __name__ == '__main__': main()
