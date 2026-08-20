#!/usr/bin/env python
"""FAST3 R43D frozen pre-decision path-shape family incremental OOF test."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
AUTHORITATIVE_ROOT = RESULTS / "frozen/fast3/r43d_path_shape_information_family_incremental_test_r1"
STAGING_ROOT = RESULTS / "scratch/fast3/.r43d_path_shape_information_family_incremental_test_r1.staging"
R43C_SOURCE = REPO / "fast3/scripts/run/fast3_r43c_regime_information_family_incremental_test_r1.py"
R43C_SOURCE_SHA256 = "862f5d73712a8c960605b6407827ad560a82d7e9ee2cc9dc971f67e98be22c5c"


def load_shared():
    spec = importlib.util.spec_from_file_location("r43c_shared_metrics_for_r43d", R43C_SOURCE)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None: raise RuntimeError("STOP_SHARED_METRIC_SOURCE_LOAD")
    spec.loader.exec_module(module)
    return module


C = load_shared()
R43C_ROOT = RESULTS / "frozen/fast3/r43c_regime_information_family_incremental_test_r1"
R43C_SUMMARY = R43C_ROOT / "FAST3_R43C_SUMMARY.json"
R43C_FEATURE_MANIFEST = R43C_ROOT / "FAST3_R43C_REGIME_FEATURE_MANIFEST.json"
R43C_SUMMARY_SHA256 = "4659c2a5823f979736a894493ea41c0bfe3c9c5c7ff08c2114016b06e4df0053"
R43C_MANIFEST_SHA256 = "c1cbfcf948018cc701f447748764e3dc650dd1d053703fa9c708cdab6aaa1780"

BASELINE_FEATURES = C.BASELINE_FEATURES
BASELINE_FEATURES_SHA256 = C.R43B_FEATURES_SHA256
PATH_FEATURES = (
    "return_acceleration_5v15", "trend_efficiency_15m", "trend_efficiency_60m",
    "predecision_mfe_15m", "predecision_mae_15m",
    "drawdown_from_favorable_extreme_15m", "close_location_15m",
    "directional_path_consistency_15m",
)
ALL_FEATURES = BASELINE_FEATURES + PATH_FEATURES
CATEGORICAL_FEATURES = C.CATEGORICAL_FEATURES
HGB_STRUCTURE = C.HGB_STRUCTURE
BLOCKS = C.BLOCKS
VALIDATION_FOLDS = C.VALIDATION_FOLDS
QUINTILES = C.QUINTILES
BASELINE_REFERENCE = C.BASELINE_REFERENCE


class IdentityStop(RuntimeError):
    pass


class PITContractStop(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return C.sha256(path)


def write_json(path: Path, value: Any) -> None:
    C.write_json(path, value)


def isolation_snapshot() -> dict[str, Any]:
    return {
        "R42R": C.tree_hashes(C.R42R_ROOT), "R43A": C.tree_hashes(C.R43A_ROOT),
        "R43B": C.tree_hashes(C.R43B_ROOT), "R43C": C.tree_hashes(R43C_ROOT),
        "R28_MODELS": C.tree_hashes(C.R28_MODELS_ROOT),
        "R28_RUNTIME": C.tree_hashes(C.R28_PROSPECTIVE_RUNTIME, True),
        "R28_SEALED": C.tree_hashes(C.R28_PROSPECTIVE_SEALED, True),
    }


def verify_contracts() -> tuple[dict[str, Any], dict[str, str]]:
    if sha256(R43C_SOURCE) != R43C_SOURCE_SHA256: raise IdentityStop("STOP_SHARED_METRIC_SOURCE_HASH")
    if sha256(C.R42R_PREREG) != C.R42R_SHA256: raise IdentityStop("STOP_R42R_HASH")
    if sha256(C.R43A_CONTRACT) != C.R43A_SHA256: raise IdentityStop("STOP_R43A_HASH")
    expected = dict(C.EXPECTED_HASHES)
    paths = {
        "R43B_SUMMARY": C.R43B_SUMMARY, "R43B_PREREG": C.R43B_PREREG,
        "R43B_FEATURE_IDENTITY": C.R43B_FEATURE_IDENTITY, "R43B_PREDICTIONS": C.R43B_PREDICTIONS,
        "R43B_FOLD_SCHEDULE": C.R43B_FOLD_SCHEDULE, "R43B_ACCEPTANCE": C.R43B_ACCEPTANCE,
        "R28_SOURCE_MANIFEST": C.R28_SOURCE_MANIFEST, "R36_LEDGER": C.R36_LEDGER,
    }
    actual = {name: sha256(path) for name, path in paths.items()}
    if actual != {name: expected[name] for name in paths}: raise IdentityStop("STOP_R43B_OR_SOURCE_HASH")
    if sha256(R43C_SUMMARY) != R43C_SUMMARY_SHA256 or sha256(R43C_FEATURE_MANIFEST) != R43C_MANIFEST_SHA256:
        raise IdentityStop("STOP_R43C_IDENTITY")
    r43b = json.loads(C.R43B_SUMMARY.read_text(encoding="utf-8"))
    r43b_prereg = json.loads(C.R43B_PREREG.read_text(encoding="utf-8"))
    r43c = json.loads(R43C_SUMMARY.read_text(encoding="utf-8"))
    if (r43b["BASELINE_FEATURES_SHA256"] != BASELINE_FEATURES_SHA256
            or tuple(r43b["BASELINE_FEATURES"]) != BASELINE_FEATURES
            or r43b_prereg["HGB_BASELINE_CONFIG"] != HGB_STRUCTURE
            or r43b_prereg["OOF_FOLD_COUNT"] != 5
            or r43b_prereg["FUTURE_FAMILY_MIN_DELTA_SPEARMAN"] != .02
            or r43b_prereg["FUTURE_FAMILY_MIN_DELTA_Q5_Q1"] != .0005):
        raise IdentityStop("STOP_R43B_BASELINE_CONTRACT")
    if (r43c["FAST3_R43C_CLASSIFICATION"] != "C_REGIME_INFORMATION_NOT_INCREMENTALLY_USEFUL"
            or r43c["REGIME_FAMILY_RETAINED"] is not False):
        raise IdentityStop("STOP_R43C_EXCLUSION_CONTRACT")
    source_hashes = {**actual, "R43C_SOURCE": sha256(R43C_SOURCE),
                     "R43C_SUMMARY": sha256(R43C_SUMMARY), "R43C_FEATURE_MANIFEST": sha256(R43C_FEATURE_MANIFEST)}
    return r43b, source_hashes


def feature_manifest(created_at: str, source_hashes: dict[str, str]) -> dict[str, Any]:
    common = {
        "directional_orientation": "direction_sign=+1 UP,-1 DOWN; positive means favorable where orientation applies",
        "source_symbol": "candidate_id underlying_symbol (QQQ or SOXX)",
        "missing_policy": "HGB_NATIVE_NAN; no imputation, row deletion, or missing indicator",
        "PIT_rule": "all source bars are completed and source timestamp <= decision_ts",
    }
    features = [
        {"name": "return_acceleration_5v15", "formula": "sign*(P_t/P_t-5-1) - sign*(P_t/P_t-15-1)/3",
         "window": "t-15m through t", "minimum_history": "15 one-minute returns", **common},
        {"name": "trend_efficiency_15m", "formula": "abs(P_t-P_t-15)/sum_{j=t-14..t}(abs(P_j-P_j-1)); zero denominator->NaN",
         "window": "t-15m through t", "minimum_history": "15 one-minute returns",
         **{**common, "directional_orientation": "direction invariant absolute path efficiency; identical formula for UP/DOWN"}},
        {"name": "trend_efficiency_60m", "formula": "abs(P_t-P_t-60)/sum_{j=t-59..t}(abs(P_j-P_j-1)); zero denominator->NaN",
         "window": "t-60m through t", "minimum_history": "60 one-minute returns",
         **{**common, "directional_orientation": "direction invariant absolute path efficiency; identical formula for UP/DOWN"}},
        {"name": "predecision_mfe_15m", "formula": "max_{j=t-15..t}(sign*(P_j/P_t-15-1))",
         "window": "t-15m through t", "minimum_history": "15 one-minute returns", **common},
        {"name": "predecision_mae_15m", "formula": "min_{j=t-15..t}(sign*(P_j/P_t-15-1)); no absolute value",
         "window": "t-15m through t", "minimum_history": "15 one-minute returns", **common},
        {"name": "drawdown_from_favorable_extreme_15m", "formula": "sign*(P_t/P_t-15-1)-predecision_mfe_15m",
         "window": "t-15m through t", "minimum_history": "15 one-minute returns", **common},
        {"name": "close_location_15m", "formula": "raw=(P_t-min(low_t-15..t))/(max(high_t-15..t)-min(low_t-15..t)); UP=raw, DOWN=1-raw; flat range->NaN",
         "window": "t-15m through t", "minimum_history": "16 completed OHLC bars",
         **{**common, "directional_orientation": "UP raw location; DOWN one minus raw location; higher is favorable"}},
        {"name": "directional_path_consistency_15m", "formula": "count(sign*one_minute_return>0)/count(valid one_minute_return); unweighted",
         "window": "15 completed one-minute returns ending at t", "minimum_history": "10 valid one-minute returns", **common},
    ]
    return {
        "CONTRACT_ID": "FAST3_R43D_PATH_SHAPE_INFORMATION_FAMILY_INCREMENTAL_TEST_R1",
        "CREATED_AT_UTC": created_at, "STATUS": "FROZEN_BEFORE_R43D_TARGET_READ_AND_MODEL_FIT",
        "PATH_SHAPE_FEATURE_COUNT": 8, "PATH_SHAPE_FEATURES": features,
        "PATH_SHAPE_FEATURE_NAMES": list(PATH_FEATURES), "MAX_NEW_FEATURE_COUNT": 8,
        "INTERACTIONS_ALLOWED": False, "FEATURE_SELECTION_ALLOWED": False,
        "REGIME_OR_VIX_FEATURES_ALLOWED": False, "R43C_REGIME_FAMILY_EXCLUDED": True,
        "BASELINE_FEATURES": list(BASELINE_FEATURES), "BASELINE_FEATURES_SHA256": BASELINE_FEATURES_SHA256,
        "PATH_MODEL_FEATURE_COUNT": len(ALL_FEATURES), "MODEL_FAMILY": "sklearn HistGradientBoosting",
        "MODEL_CONFIG": HGB_STRUCTURE, "OOF_FOLDS": list(VALIDATION_FOLDS),
        "INCREMENTAL_GATE": {"MIN_DELTA_SPEARMAN": .02, "MIN_DELTA_Q5_Q1": .0005,
                             "MAJORITY_FOLD_NON_DEGRADATION": ">=3/5", "TAIL_ROBUSTNESS_REQUIRED_IF_RAW_POSITIVE": True},
        "FOLD_NON_DEGRADATION_RULE": (
            "raw Spearman comparison when both exist; constant baseline is zero-information reference; both constant unchanged; "
            "nonnegative path Spearman versus constant is non-degraded; negative is degraded"
        ),
        "ABSOLUTE_GATE": {"SPEARMAN": .05, "Q5_Q1": ">0", "ORDERING": ["MONOTONIC_POSITIVE", "MOSTLY_POSITIVE"],
                          "FOLD_STABILITY": ">half positive among >=3 standard evaluable folds"},
        "STRONG_GATE": {"SPEARMAN": .10, "Q5_Q1": .001, "Q5_MEAN": ">0", "FOLD_STABILITY": True,
                        "TAIL_ROBUSTNESS": True},
        "HARMFUL_RULE": "both directions delta Spearman<=-0.02 and delta Q5-Q1<=-0.0005 and >=3/5 folds degraded",
        "SECONDARY_TARGET_IS_SUPPORTING_ONLY": True, "BASELINE_REFIT_ALLOWED": False,
        "MODEL_FIT_BUDGET": 20, "FULL_SAMPLE_REFIT_ALLOWED": False,
        "R43A_TARGET_CONTRACT_SHA256": C.R43A_SHA256, "R42R_PREREGISTRATION_SHA256": C.R42R_SHA256,
        "R43C_REGIME_FEATURE_MANIFEST_SHA256": R43C_MANIFEST_SHA256,
        "SOURCE_SHA256": source_hashes, "RESEARCH_CHOICE_CHANGED_AFTER_RESULT": False,
    }


def load_symbol_bars() -> dict[str, pd.DataFrame]:
    manifest = json.loads(C.R28_SOURCE_MANIFEST.read_text(encoding="utf-8"))
    output = {}
    for symbol in ("QQQ", "SOXX"):
        records = [row for row in manifest["files"] if row["symbol"] == symbol]
        if len(records) != 79: raise IdentityStop(f"STOP_SOURCE_FILE_COUNT:{symbol}")
        for row in records:
            path = Path(row["path"])
            if not path.is_file() or sha256(path).lower() != row["sha256"].lower():
                raise IdentityStop(f"STOP_SOURCE_HASH:{path}")
        columns = ["timestamp_utc", "open", "high", "low", "close", "volume"]
        frame = pd.concat([pd.read_parquet(row["path"], columns=columns) for row in records], ignore_index=True)
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="raise")
        frame = frame.sort_values("timestamp_utc", kind="mergesort").drop_duplicates("timestamp_utc").reset_index(drop=True)
        for column in ("open", "high", "low", "close", "volume"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        valid = ((frame["open"] > 0) & (frame["close"] > 0) & (frame["volume"] >= 0)
                 & (frame["high"] >= frame[["open", "low", "close"]].max(axis=1))
                 & (frame["low"] <= frame[["open", "high", "close"]].min(axis=1)))
        if frame["timestamp_utc"].duplicated().any() or not valid.all():
            raise PITContractStop(f"STOP_CANONICAL_BAR_INTEGRITY:{symbol}")
        output[symbol] = frame
    return output


def path_values(close: np.ndarray, high: np.ndarray, low: np.ndarray, index: int, sign: int) -> dict[str, float]:
    if index < 60: return {name: np.nan for name in PATH_FEATURES}
    p = np.asarray(close[index - 60:index + 1], float)
    h15 = np.asarray(high[index - 15:index + 1], float)
    l15 = np.asarray(low[index - 15:index + 1], float)
    p15, p60 = p[-16:], p
    r5 = sign * (p[-1] / p[-6] - 1.0); r15 = sign * (p[-1] / p[-16] - 1.0)
    def efficiency(values: np.ndarray) -> float:
        denominator = float(np.abs(np.diff(values)).sum())
        return np.nan if denominator == 0 else float(abs(values[-1] - values[0]) / denominator)
    oriented_path = sign * (p15 / p15[0] - 1.0)
    mfe = float(np.max(oriented_path)); mae = float(np.min(oriented_path))
    range_low, range_high = float(np.min(l15)), float(np.max(h15))
    raw_location = np.nan if range_high == range_low else float((p[-1] - range_low) / (range_high - range_low))
    location = raw_location if sign == 1 or np.isnan(raw_location) else 1.0 - raw_location
    returns = p15[1:] / p15[:-1] - 1.0; valid = np.isfinite(returns)
    consistency = np.nan if int(valid.sum()) < 10 else float((sign * returns[valid] > 0).mean())
    return {
        "return_acceleration_5v15": float(r5 - r15 / 3.0),
        "trend_efficiency_15m": efficiency(p15), "trend_efficiency_60m": efficiency(p60),
        "predecision_mfe_15m": mfe, "predecision_mae_15m": mae,
        "drawdown_from_favorable_extreme_15m": float(r15 - mfe),
        "close_location_15m": location, "directional_path_consistency_15m": consistency,
    }


def materialize_path_features(identity: pd.DataFrame, bars: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    identity = identity[["candidate_id", "decision_timestamp_utc", "direction"]].copy()
    identity["decision_timestamp_utc"] = pd.to_datetime(identity["decision_timestamp_utc"], utc=True, errors="raise")
    identity["source_symbol"] = identity["candidate_id"].astype(str).str.split("|").str[0]
    if not identity["source_symbol"].isin(["QQQ", "SOXX"]).all(): raise IdentityStop("STOP_CANDIDATE_SOURCE_SYMBOL")
    rows, violation_count = [], 0
    for symbol, part in identity.groupby("source_symbol", sort=True):
        source = bars[symbol]; timestamps = source["timestamp_utc"].to_numpy(dtype="datetime64[ns]")
        if len(np.unique(timestamps)) != len(timestamps): raise PITContractStop("STOP_SOURCE_TIMESTAMP_DUPLICATE")
        positions = pd.Series(np.arange(len(source)), index=source["timestamp_utc"]).reindex(part["decision_timestamp_utc"])
        if positions.isna().any(): raise IdentityStop(f"STOP_DECISION_TIMESTAMP_MATCH:{symbol}")
        close = source["close"].to_numpy(float); high = source["high"].to_numpy(float); low = source["low"].to_numpy(float)
        for row, source_index in zip(part.itertuples(index=False), positions.astype(int)):
            sign = 1 if row.direction == "UP" else -1
            values = path_values(close, high, low, source_index, sign)
            maximum = source.iloc[source_index]["timestamp_utc"]
            if maximum > row.decision_timestamp_utc: violation_count += 1
            rows.append({"candidate_id": row.candidate_id, **values, "max_source_timestamp_utc": maximum})
    output = pd.DataFrame(rows)
    if len(output) != len(identity) or output["candidate_id"].duplicated().any(): raise IdentityStop("STOP_PATH_FEATURE_ROW_IDENTITY")
    audit_rows = []
    windows = {"return_acceleration_5v15": "[t-15m,t]", "trend_efficiency_15m": "[t-15m,t]",
               "trend_efficiency_60m": "[t-60m,t]", "predecision_mfe_15m": "[t-15m,t]",
               "predecision_mae_15m": "[t-15m,t]", "drawdown_from_favorable_extreme_15m": "[t-15m,t]",
               "close_location_15m": "[t-15m,t]", "directional_path_consistency_15m": "15 returns ending t"}
    for name in PATH_FEATURES:
        audit_rows.append({"feature_name": name, "source_window": windows[name], "max_allowed_timestamp": "decision_ts inclusive",
                           "pit_violation_count": violation_count, "pit_status": "PASS" if violation_count == 0 else "FAIL",
                           "valid_count": int(output[name].notna().sum()), "missing_count": int(output[name].isna().sum())})
    if violation_count: raise PITContractStop("STOP_PATH_FEATURE_FUTURE_BAR")
    return output, pd.DataFrame(audit_rows), {
        "PATH_FEATURE_PIT_VIOLATION_COUNT": violation_count,
        "FEATURE_VALID_COUNTS": {name: int(output[name].notna().sum()) for name in PATH_FEATURES},
        "FEATURE_MISSING_COUNTS": {name: int(output[name].isna().sum()) for name in PATH_FEATURES},
        "SOURCE_TIMESTAMP_MATCH_COUNT": len(output),
    }


def model_config(kind: str) -> dict[str, Any]:
    config = dict(HGB_STRUCTURE)
    config["categorical_features"] = [name in CATEGORICAL_FEATURES for name in ALL_FEATURES]
    config["loss"] = "squared_error" if kind == "regressor" else "log_loss"
    return config


def make_model(kind: str):
    config = model_config(kind)
    return HistGradientBoostingRegressor(**config) if kind == "regressor" else HistGradientBoostingClassifier(**config)


def run_oof(frame: pd.DataFrame, model_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    model_dir.mkdir(parents=True); predictions, manifest = [], []; reg_fits = cls_fits = 0
    for fold in VALIDATION_FOLDS:
        position = BLOCKS.index(fold)
        for direction in ("UP", "DOWN"):
            train = frame.loc[frame["direction"].eq(direction) & frame["validation_slice"].isin(BLOCKS[:position])]
            valid = frame.loc[frame["direction"].eq(direction) & frame["validation_slice"].eq(fold)]
            if train.empty or valid.empty or train["realized_positive_majority"].nunique() != 2:
                raise IdentityStop(f"STOP_OOF_TRAIN:{direction}:{fold}")
            reg = make_model("regressor"); reg.fit(train.loc[:, ALL_FEATURES], train["realized_y_econ"]); reg_fits += 1
            cls = make_model("classifier"); cls.fit(train.loc[:, ALL_FEATURES], train["realized_positive_majority"]); cls_fits += 1
            reg_path = model_dir / f"{direction}_{fold}_PATH_PRIMARY_REGRESSOR.joblib"
            cls_path = model_dir / f"{direction}_{fold}_PATH_SECONDARY_CLASSIFIER.joblib"
            joblib.dump(reg, reg_path, compress=3); joblib.dump(cls, cls_path, compress=3)
            manifest.extend([
                {"direction": direction, "fold": fold, "role": "PATH_PRIMARY_REGRESSOR", "path": f"models/{reg_path.name}", "sha256": sha256(reg_path)},
                {"direction": direction, "fold": fold, "role": "PATH_SECONDARY_CLASSIFIER", "path": f"models/{cls_path.name}", "sha256": sha256(cls_path)},
            ])
            out = valid[["candidate_id", "decision_timestamp_utc", "validation_slice", "direction", "realized_y_econ", "realized_positive_majority"]].copy()
            out["predicted_y_econ"] = reg.predict(valid.loc[:, ALL_FEATURES])
            out["predicted_positive_majority_probability"] = cls.predict_proba(valid.loc[:, ALL_FEATURES])[:, 1]
            predictions.append(out)
    counts = {"PRIMARY_REGRESSION_FIT_COUNT": reg_fits, "SECONDARY_CLASSIFICATION_FIT_COUNT": cls_fits,
              "MODEL_FIT_COUNT": reg_fits + cls_fits, "FULL_SAMPLE_REFIT_COUNT": 0, "BASELINE_REFIT_COUNT": 0}
    if counts["MODEL_FIT_COUNT"] != 20: raise IdentityStop("STOP_MODEL_FIT_BUDGET")
    return pd.concat(predictions, ignore_index=True), pd.DataFrame(manifest), counts


def paired_path_folds(baseline: pd.DataFrame, predictions: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    table, flags = C.paired_folds(baseline, predictions)
    table = table.rename(columns={column: column.replace("regime_", "path_") for column in table.columns})
    for direction in flags:
        flags[direction]["PATH_FOLD_STABILITY"] = flags[direction]["REGIME_FOLD_STABILITY"]
    return table, flags


def evaluate(primary: pd.DataFrame, tails: pd.DataFrame, fold_flags: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], str, bool, str]:
    flags: dict[str, Any] = {}; accepted, absolute, strong = False, False, False; harmful_heads = []; accepted_heads = []
    for direction in ("UP", "DOWN"):
        row = primary.loc[primary["direction"].eq(direction)].iloc[0]
        delta_s = float(row["spearman"] - BASELINE_REFERENCE[direction]["spearman"])
        delta_q = float(row["q5_q1"] - BASELINE_REFERENCE[direction]["q5_q1"])
        tail = tails.loc[tails["direction"].eq(direction), "tail_robustness"].iloc[0]
        tail_incremental_ok = bool(tail) if pd.notna(tail) else True
        stable = fold_flags[direction]["PATH_FOLD_STABILITY"]
        incremental = bool(delta_s >= .02 and delta_q >= .0005
                           and fold_flags[direction]["MAJORITY_FOLD_NON_DEGRADATION"] and tail_incremental_ok)
        absolute_head = bool(row["spearman"] >= .05 and row["q5_q1"] > 0
                             and row["ordering"] in ("MONOTONIC_POSITIVE", "MOSTLY_POSITIVE") and stable)
        strong_head = bool(row["spearman"] >= .10 and row["q5_q1"] >= .001 and row["q5_mean"] > 0
                           and stable and pd.notna(tail) and bool(tail))
        harmful_heads.append(bool(delta_s <= -.02 and delta_q <= -.0005 and fold_flags[direction]["FOLD_DEGRADATION_COUNT"] >= 3))
        if incremental: accepted_heads.append(direction)
        flags.update({f"{direction}_DELTA_SPEARMAN": delta_s, f"{direction}_DELTA_Q5_Q1": delta_q,
                      f"{direction}_PATH_PRIMARY_INCREMENTAL_ACCEPTANCE": incremental,
                      f"{direction}_PATH_ABSOLUTE_ECONOMIC_SIGNAL": absolute_head,
                      f"{direction}_PATH_STRONG_ECONOMIC_SIGNAL": strong_head})
        accepted |= incremental; absolute |= absolute_head; strong |= strong_head
    harmful = bool(all(harmful_heads))
    classification = ("B_PATH_SHAPE_ESTABLISHES_ABSOLUTE_ECONOMIC_SIGNAL" if accepted and absolute else
                      "A_PATH_SHAPE_INFORMATION_INCREMENTALLY_USEFUL" if accepted else
                      "D_PATH_SHAPE_INFORMATION_HARMFUL" if harmful else
                      "C_PATH_SHAPE_INFORMATION_NOT_INCREMENTALLY_USEFUL")
    accepted_direction = "BOTH" if len(accepted_heads) == 2 else f"{accepted_heads[0]}_ONLY" if accepted_heads else "NONE"
    flags.update({"PATH_PRIMARY_INCREMENTAL_ACCEPTANCE": accepted, "PATH_ABSOLUTE_ECONOMIC_SIGNAL": absolute,
                  "PATH_STRONG_ECONOMIC_SIGNAL": strong})
    return flags, classification, accepted, accepted_direction


def render_terminal(summary: dict[str, Any]) -> str:
    keys = ["FAST3_R43D_STATUS", "FAST3_R43D_CLASSIFICATION", "FAST3_R43D_DECISION",
            "PATH_SHAPE_FEATURE_COUNT", "PATH_SHAPE_FEATURES", "R43D_PATH_SHAPE_FEATURE_MANIFEST_SHA256",
            "R43C_REGIME_FAMILY_EXCLUDED", "TARGET_ROW_IDENTITY_UNCHANGED", "OOF_FOLD_IDENTITY_MATCH",
            "PATH_FEATURE_PIT_VIOLATION_COUNT", "UP_BASELINE_SPEARMAN", "UP_PATH_SPEARMAN", "UP_DELTA_SPEARMAN",
            "DOWN_BASELINE_SPEARMAN", "DOWN_PATH_SPEARMAN", "DOWN_DELTA_SPEARMAN",
            "UP_BASELINE_Q5_Q1", "UP_PATH_Q5_Q1", "UP_DELTA_Q5_Q1",
            "DOWN_BASELINE_Q5_Q1", "DOWN_PATH_Q5_Q1", "DOWN_DELTA_Q5_Q1",
            "UP_PATH_PRIMARY_INCREMENTAL_ACCEPTANCE", "DOWN_PATH_PRIMARY_INCREMENTAL_ACCEPTANCE",
            "UP_PATH_ABSOLUTE_ECONOMIC_SIGNAL", "DOWN_PATH_ABSOLUTE_ECONOMIC_SIGNAL", "PATH_STRONG_ECONOMIC_SIGNAL",
            "UP_FOLDS_WITH_POSITIVE_DELTA_SPEARMAN", "DOWN_FOLDS_WITH_POSITIVE_DELTA_SPEARMAN",
            "UP_FOLDS_WITH_POSITIVE_DELTA_Q5_Q1", "DOWN_FOLDS_WITH_POSITIVE_DELTA_Q5_Q1",
            "UP_BASELINE_SECONDARY_AUROC", "UP_PATH_SECONDARY_AUROC",
            "DOWN_BASELINE_SECONDARY_AUROC", "DOWN_PATH_SECONDARY_AUROC",
            "PATH_SHAPE_FAMILY_RETAINED", "ACCEPTED_DIRECTION", "MODEL_FIT_COUNT", "FULL_SAMPLE_REFIT_COUNT",
            "R43A_TARGET_CONTRACT_SHA256_VERIFIED", "R43B_BASELINE_FEATURES_SHA256_VERIFIED",
            "R42R_PREREGISTRATION_SHA256_VERIFIED", "R28_PROSPECTIVE_LINE_ISOLATION",
            "PIT_STATUS", "OOF_INTEGRITY_STATUS", "TARGET_CONTRACT_STATUS", "STORAGE_CONTRACT_STATUS", "NEXT_STAGE"]
    def show(value: Any) -> str:
        if isinstance(value, bool): return str(value).lower()
        if isinstance(value, (list, dict)): return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        if value is None or (isinstance(value, float) and not np.isfinite(value)): return "NOT_AVAILABLE"
        return str(value)
    return "\n".join(f"{key}={show(summary[key])}" for key in keys)


def execute() -> dict[str, Any]:
    if AUTHORITATIVE_ROOT.exists(): raise IdentityStop("STOP_AUTHORITATIVE_R43D_ALREADY_EXISTS")
    if STAGING_ROOT.exists(): raise IdentityStop("STOP_R43D_STAGING_ALREADY_EXISTS")
    before = isolation_snapshot(); r43b, source_hashes = verify_contracts()
    STAGING_ROOT.mkdir(parents=True)
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    contract = feature_manifest(created_at, source_hashes)
    manifest_path = STAGING_ROOT / "FAST3_R43D_PATH_SHAPE_FEATURE_MANIFEST.json"
    write_json(manifest_path, contract); manifest_hash = sha256(manifest_path)

    frame, baseline, schedule = C.load_frame_and_baseline()
    bars = load_symbol_bars()
    path_features, pit_table, feature_audit = materialize_path_features(frame, bars)
    frame = frame.merge(path_features.drop(columns="max_source_timestamp_utc"), on="candidate_id", validate="one_to_one")
    if any(name in frame.columns for name in C.REGIME_FEATURES): raise IdentityStop("STOP_R43C_FEATURE_CONTAMINATION")
    predictions, model_manifest, fit_counts = run_oof(frame, STAGING_ROOT / "models")
    predictions["primary_quintile"] = C.stable_quintiles(predictions, "predicted_y_econ")
    predictions["secondary_quintile"] = C.stable_quintiles(predictions, "predicted_positive_majority_probability")
    primary, quintiles, tails = C.primary_metrics(predictions)
    fold_table, fold_flags = paired_path_folds(baseline, predictions)
    secondary, secondary_quintiles = C.secondary_metrics(predictions)
    diagnostic_rows = []
    for feature in PATH_FEATURES:
        row = {"feature_name": feature}
        for direction in ("UP", "DOWN"):
            part = frame.loc[frame["direction"].eq(direction)]
            row[f"{direction.lower()}_univariate_spearman"] = C.correlation(part[feature], part["realized_y_econ"])
        diagnostic_rows.append(row)
    diagnostic = pd.DataFrame(diagnostic_rows)
    flags, classification, retained, accepted_direction = evaluate(primary, tails, fold_flags)

    baseline_ids, path_ids = set(baseline["candidate_id"]), set(predictions["candidate_id"])
    exact_match = len(baseline_ids & path_ids); row_identity = baseline_ids == path_ids and len(predictions) == 998
    if not row_identity: raise IdentityStop("STOP_PATH_DATA_IDENTITY_FAILURE")
    if set(schedule["fold"]) != set(predictions["validation_slice"]): raise IdentityStop("STOP_FOLD_IDENTITY")
    summary: dict[str, Any] = {
        "FAST3_R43D_STATUS": "PASS", "FAST3_R43D_CLASSIFICATION": classification,
        "FAST3_R43D_DECISION": "R43E_CROSS_ASSET_INFORMATION_FAMILY_INCREMENTAL_TEST",
        "NEXT_STAGE": "R43E_CROSS_ASSET_INFORMATION_FAMILY_INCREMENTAL_TEST",
        "CREATED_AT_UTC": created_at, "PATH_SHAPE_FEATURE_COUNT": len(PATH_FEATURES),
        "PATH_SHAPE_FEATURES": list(PATH_FEATURES), "R43D_PATH_SHAPE_FEATURE_MANIFEST_SHA256": manifest_hash,
        "R43C_REGIME_FAMILY_EXCLUDED": True, "BASELINE_FEATURES_SHA256": BASELINE_FEATURES_SHA256,
        "PATH_MODEL_FEATURE_COUNT": len(ALL_FEATURES), "BASELINE_ROW_COUNT": len(baseline),
        "PATH_MODEL_ROW_COUNT": len(predictions), "EXACT_ROW_MATCH_COUNT": exact_match,
        "TARGET_ROW_IDENTITY_UNCHANGED": row_identity, "OOF_FOLD_IDENTITY_MATCH": True, "OOF_FOLD_COUNT": 5,
        "R43B_MODEL_CONFIG_EXACT_MATCH": True, "HGB_PATH_CONFIG": {"regressor": model_config("regressor"), "classifier": model_config("classifier")},
        "PATH_SHAPE_FAMILY_RETAINED": retained, "ACCEPTED_DIRECTION": accepted_direction,
        "SECONDARY_TARGET_IS_SUPPORTING_ONLY": True, **fit_counts, **feature_audit, **flags,
        "R43A_TARGET_CONTRACT_SHA256_VERIFIED": True, "R43B_BASELINE_FEATURES_SHA256_VERIFIED": True,
        "R42R_PREREGISTRATION_SHA256_VERIFIED": True, "R28_MODEL_CHANGED": False, "R28_FEATURE_CHANGED": False,
        "R28_THRESHOLD_CHANGED": False, "R28_CONFIRMATION_LEDGER_CHANGED": False,
        "PIT_STATUS": "PASS_ALL_EIGHT_PATH_FEATURES_MAX_SOURCE_TIMESTAMP_LE_DECISION_TS",
        "OOF_INTEGRITY_STATUS": "PASS_EXACT_R43B_FIVE_EXPANDING_FOLDS_NO_SHUFFLE",
        "TARGET_CONTRACT_STATUS": "PASS_R43A_EXACT_HASH_TARGET_UNCHANGED",
        "STORAGE_CONTRACT_STATUS": "PASS_FAST3_STORAGE_CONTRACT_R1_EXTERNAL_GENERATION_RESEARCH_ONLY",
        "RESEARCH_CHOICE_CHANGED_AFTER_RESULT": False, "PARAMETER_SEARCH_COUNT": 0, "FEATURE_SELECTION_COUNT": 0,
        "BRANCH": subprocess.check_output(["git", "branch", "--show-current"], cwd=REPO, text=True).strip(),
        "HEAD": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
    }
    paired_secondary = []
    for direction in ("UP", "DOWN"):
        p = primary.loc[primary["direction"].eq(direction)].iloc[0]
        s = secondary.loc[secondary["direction"].eq(direction)].iloc[0]
        base_auc = r43b[f"{direction}_SECONDARY_AUROC"]; base_pr = r43b[f"{direction}_SECONDARY_PR_AUC"]
        base_brier = r43b[f"{direction}_SECONDARY_BRIER_SCORE"]
        summary.update({
            f"{direction}_BASELINE_SPEARMAN": BASELINE_REFERENCE[direction]["spearman"], f"{direction}_PATH_SPEARMAN": p["spearman"],
            f"{direction}_BASELINE_Q5_Q1": BASELINE_REFERENCE[direction]["q5_q1"], f"{direction}_PATH_Q5_Q1": p["q5_q1"],
            f"{direction}_PATH_Q1_REALIZED_Y_ECON_MEAN": p["q1_mean"], f"{direction}_PATH_Q5_REALIZED_Y_ECON_MEAN": p["q5_mean"],
            f"{direction}_PATH_ORDERING": p["ordering"], f"{direction}_PATH_PEARSON": p["pearson"],
            f"{direction}_PATH_MAE": p["mae"], f"{direction}_PATH_RMSE": p["rmse"], f"{direction}_PATH_R2": p["r2"],
            f"{direction}_FOLDS_WITH_POSITIVE_DELTA_SPEARMAN": fold_flags[direction]["FOLDS_WITH_POSITIVE_DELTA_SPEARMAN"],
            f"{direction}_FOLDS_WITH_POSITIVE_DELTA_Q5_Q1": fold_flags[direction]["FOLDS_WITH_POSITIVE_DELTA_Q5_Q1"],
            f"{direction}_FOLD_NON_DEGRADATION_COUNT": fold_flags[direction]["FOLD_NON_DEGRADATION_COUNT"],
            f"{direction}_MAJORITY_FOLD_NON_DEGRADATION": fold_flags[direction]["MAJORITY_FOLD_NON_DEGRADATION"],
            f"{direction}_BASELINE_SECONDARY_AUROC": base_auc, f"{direction}_PATH_SECONDARY_AUROC": s["auroc"],
            f"{direction}_DELTA_SECONDARY_AUROC": float(s["auroc"] - base_auc),
            f"{direction}_BASELINE_SECONDARY_PR_AUC": base_pr, f"{direction}_PATH_SECONDARY_PR_AUC": s["pr_auc"],
            f"{direction}_DELTA_SECONDARY_PR_AUC": float(s["pr_auc"] - base_pr),
            f"{direction}_BASELINE_SECONDARY_BRIER": base_brier, f"{direction}_PATH_SECONDARY_BRIER": s["brier"],
            f"{direction}_DELTA_SECONDARY_BRIER": float(s["brier"] - base_brier),
        })
        paired_secondary.append({"direction": direction, "baseline_auroc": base_auc, "path_auroc": s["auroc"],
                                 "delta_auroc": s["auroc"] - base_auc, "baseline_pr_auc": base_pr,
                                 "path_pr_auc": s["pr_auc"], "delta_pr_auc": s["pr_auc"] - base_pr,
                                 "baseline_brier": base_brier, "path_brier": s["brier"], "delta_brier": s["brier"] - base_brier})
    after = isolation_snapshot()
    if before != after: raise IdentityStop("STOP_FROZEN_LINE_MUTATION")
    summary["R28_PROSPECTIVE_LINE_ISOLATION"] = True; summary["FROZEN_ISOLATION_TREE_SHA256"] = before

    path_features.to_parquet(STAGING_ROOT / "FAST3_R43D_PATH_FEATURE_VALUES.parquet", index=False)
    pit_table.to_csv(STAGING_ROOT / "FAST3_R43D_PATH_FEATURE_PIT_AUDIT.csv", index=False)
    predictions.to_parquet(STAGING_ROOT / "FAST3_R43D_OOF_PREDICTIONS.parquet", index=False)
    model_manifest.to_csv(STAGING_ROOT / "FAST3_R43D_MODEL_MANIFEST.csv", index=False)
    primary.to_csv(STAGING_ROOT / "FAST3_R43D_PRIMARY_METRICS.csv", index=False)
    quintiles.to_csv(STAGING_ROOT / "FAST3_R43D_PRIMARY_QUINTILES.csv", index=False)
    tails.to_csv(STAGING_ROOT / "FAST3_R43D_TAIL_ROBUSTNESS.csv", index=False)
    fold_table.to_csv(STAGING_ROOT / "FAST3_R43D_FOLD_PAIRED_COMPARISON.csv", index=False)
    secondary.to_csv(STAGING_ROOT / "FAST3_R43D_SECONDARY_METRICS.csv", index=False)
    secondary_quintiles.to_csv(STAGING_ROOT / "FAST3_R43D_SECONDARY_QUINTILES.csv", index=False)
    pd.DataFrame(paired_secondary).to_csv(STAGING_ROOT / "FAST3_R43D_SECONDARY_PAIRED_METRICS.csv", index=False)
    diagnostic.to_csv(STAGING_ROOT / "FAST3_R43D_PATH_UNIVARIATE_DIAGNOSTIC.csv", index=False)
    write_json(STAGING_ROOT / "FAST3_R43D_SUMMARY.json", summary)
    report = ["# FAST3 R43D Path-Shape Information Family Incremental Test R1", "",
              f"- Classification: `{classification}`", f"- Family retained: `{retained}`", f"- Accepted direction: `{accepted_direction}`",
              f"- Model fits: `{fit_counts['MODEL_FIT_COUNT']}` path OOF only; baseline reused; no full-sample refit.", "",
              "Eight atomic pre-decision path features were frozen before target read and model fit. No future bar, regime feature, interaction, target, row, fold, model, or parameter search was used.", "",
              "## Terminal summary", "", "```text", render_terminal(summary), "```", ""]
    (STAGING_ROOT / "FAST3_R43D_REPORT.md").write_text("\n".join(report), encoding="utf-8")
    AUTHORITATIVE_ROOT.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(STAGING_ROOT), str(AUTHORITATIVE_ROOT)); summary["ARTIFACT_ROOT"] = str(AUTHORITATIVE_ROOT)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--execute", action="store_true"); args = parser.parse_args()
    if not args.execute: print("FAST3_R43D_STATUS=READY_REQUIRES_EXECUTE"); return 0
    try: summary = execute()
    except IdentityStop as exc:
        print("FAST3_R43D_STATUS=STOP\nFAST3_R43D_CLASSIFICATION=E_PATH_DATA_IDENTITY_FAILURE")
        print(f"FAST3_R43D_DECISION={exc}"); return 2
    except PITContractStop as exc:
        print("FAST3_R43D_STATUS=STOP\nFAST3_R43D_CLASSIFICATION=F_PIT_OR_CONTRACT_FAILURE")
        print(f"FAST3_R43D_DECISION={exc}"); return 2
    print(render_terminal(summary)); print(f"ARTIFACT_ROOT={summary['ARTIFACT_ROOT']}"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
