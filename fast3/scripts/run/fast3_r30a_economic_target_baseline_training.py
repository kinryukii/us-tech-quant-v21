#!/usr/bin/env python
"""FAST3 R30A frozen T1/T2 economic-target baseline training.

The experiment intentionally changes only y.  Features, PIT construction,
economic execution semantics, model structure and annual OOF boundaries are
bound to the authoritative R28 artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    mean_absolute_error,
    mean_squared_error,
    roc_auc_score,
)

SOURCE_ROOT = Path(r"D:\us-tech-quant")
DATA_ROOT = Path(r"D:\us-tech-quant-data")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
CACHE_ROOT = Path(r"D:\us-tech-quant-cache")
R28_PHASE2 = RESULTS_ROOT / "frozen" / "fast3" / "r28_phase2_20260808T125629Z"
R28_PHASE3 = RESULTS_ROOT / "frozen" / "fast3" / "r28_phase3_20260808T131135Z"
R28_3G = RESULTS_ROOT / "frozen" / "fast3" / "r28_3g_corporate_action_normalized_first_touch_20260809"
R28_CLOSEOUT = RESULTS_ROOT / "frozen" / "fast3" / "r28_final_closeout_next_economic_target_design_20260809"
CONTROL = RESULTS_ROOT / "frozen" / "fast3" / "cleanroom_r2_20260808"

R28_FEATURE_MANIFEST = R28_PHASE2 / "R28_FEATURE_MANIFEST.json"
R28_MODEL_IDENTITY = R28_PHASE3 / "R28_PHASE3_RESEARCH_IDENTITY.json"
R28_SPLIT_CONTRACT = CONTROL / "cleanroom_r2_freeze_manifest.json"
R28_SOURCE_MANIFEST = CONTROL / "cleanroom_r2_preholdout_source_manifest.json"
ECONOMIC_LEDGER = R28_3G / "R28_3G_CORRECTED_TRADE_LEDGER.csv"
R28_FINAL_CLOSEOUT = R28_CLOSEOUT / "FAST3_R28_FINAL_CLOSEOUT.json"
TARGET_PROPOSAL = R28_CLOSEOUT / "FAST3_NEXT_ECONOMIC_TARGET_CONTRACT_PROPOSAL.json"

EXPECTED = {
    "ETF_MANIFEST_SHA256": "1726b400b9fbb33f1bf85ff4afd229288f8e823d26cf3b2d3b0956e760b3a331",
    "ECONOMIC_LEDGER_SHA256": "a28c48880ae98fb5626967afd95c2096f4fb82a0320fbfd3f6cf1702f690ace5",
    "FEATURE_MANIFEST_SHA256": "3cac01f22f8a0b308f2d666d06e36abe13643c4d60948bdc312a5a1a01b96ab3",
    "MODEL_IDENTITY_SHA256": "392de8935873d4dbc38b9c906f5e12181d1899889107bb49ed7c34ea1c5662fc",
    "SPLIT_CONTRACT_SHA256": "38352151a703737d74b4d61dbe68f82a9c6f3d5058aa72bd2a1896e19a5cb412",
    "SOURCE_MANIFEST_LOGICAL_SHA256": "943ced982f93e3661456a8d62e7fe8147123b1260cb19a0952487cbffaafe21a",
    "TARGET_ROWS": 1197,
    "T1_RATE": 0.5730994152046783,
    "RAW_MEAN": -0.004754509099415957,
    "RAW_MEDIAN": 0.0073877551020409,
    "ROBUST_MEAN": -0.004345168445687766,
    "ROBUST_MEDIAN": 0.007360599304221728,
}

FEATURES = (
    "return_5m", "return_15m", "return_60m", "realized_vol_15m",
    "realized_vol_60m", "relative_volume", "range_position", "symbol_code",
    "direction_code", "session_code", "volume_zscore_60m",
    "signed_volume_pressure_15m", "peer_return_15m", "relative_return_15m",
)
SELECTED_R28_ADDITIONS = (
    "volume_zscore_60m", "signed_volume_pressure_15m",
    "peer_return_15m", "relative_return_15m",
)
CATEGORICAL = ("symbol_code", "session_code")
HGB_PARAMS = {
    "learning_rate": 0.08,
    "max_iter": 100,
    "max_leaf_nodes": 7,
    "min_samples_leaf": 200,
    "l2_regularization": 1.0,
    "random_state": 1729,
}
ORIGINAL_FOLDS = (
    ("OOF_2020", "2020-01-01", "2020-12-31 23:59:59"),
    ("OOF_2021", "2021-01-01", "2021-12-31 23:59:59"),
    ("OOF_2022", "2022-01-01", "2022-12-31 23:59:59"),
    ("OOF_2023", "2023-01-01", "2023-12-31 23:59:59"),
    ("OOF_2024", "2024-01-01", "2024-12-31 23:59:59"),
    ("OOF_2025_JAN", "2025-01-01", "2025-01-31 23:59:59"),
)
ECONOMIC_FOLDS = ORIGINAL_FOLDS[1:]
TOP_BUCKETS = (20, 10, 5, 1)
PURGE_EMBARGO = pd.Timedelta(minutes=1440)
TRUE_HOLDOUT_START = pd.Timestamp("2025-02-01T05:00:00Z")


class R30AStop(RuntimeError):
    """Fail-closed R30A contract error."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def value_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, datetime, Path)):
        return str(value)
    if pd.isna(value):
        return None
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=json_default, allow_nan=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def target_contract(created_at: str) -> dict[str, Any]:
    return {
        "CONTRACT_ID": "FAST3_R30_T1_T2_ECONOMIC_TARGET_CONTRACT_R1",
        "GENERATION": "R30",
        "STAGE": "R30A",
        "STUDY_NAME": "FROZEN_T1_T2_ECONOMIC_TARGET_BASELINE_TRAINING",
        "STATUS": "FROZEN_BEFORE_MODEL_FIT",
        "TARGET_CONTRACT_FROZEN": True,
        "CREATED_AT_UTC": created_at,
        "AUTHORITATIVE_R28_CONCLUSION": "CLOSED_EVENT_PREDICTION_EDGE_CONFIRMED_ECONOMIC_TARGET_MISALIGNED",
        "R28_REOPEN_ALLOWED": False,
        "PRIMARY_TARGET": {
            "TARGET_NAME": "T1_POSITIVE_NET20",
            "TARGET_TYPE": "BINARY_CLASSIFICATION",
            "TARGET_FORMULA": "1 if corporate-action-normalized executable net20 > 0, else 0",
            "COMPARATOR": ">",
            "THRESHOLD": 0.0,
        },
        "SECONDARY_TARGET": {
            "TARGET_NAME": "T2_ROBUST_NET20",
            "TARGET_TYPE": "ROBUST_CONTINUOUS_REGRESSION",
            "T2_TRANSFORMATION": "SIGNED_LOG1P",
            "LOG_BASE": "NATURAL",
            "TARGET_FORMULA": "sign(r) * log(1 + abs(r)); r is corporate-action-normalized executable net20",
            "CLIPPING": False,
            "WINSORIZATION": False,
            "RESCALING": False,
        },
        "REFERENCE_TIMESTAMP": "frozen selected-signal decision timestamp",
        "ENTRY_SEMANTICS": "first legal mapped leveraged-ETF 1m bar strictly after frozen anchor within 15 minutes; use open",
        "EXIT_OR_HORIZON_SEMANTICS": "favorable-first: first legal ETF open at/after frozen SOXX/QQQ touch; adverse-first/no-event: frozen R26A2 24-natural-hour closeout",
        "INSTRUMENT_MAPPING": {"QQQ|UP": "TQQQ", "QQQ|DOWN": "SQQQ", "SOXX|UP": "SOXL", "SOXX|DOWN": "SOXS"},
        "PRICE_SOURCE": "R28.3E canonical ETF partitions",
        "ETF_MANIFEST_SHA256": EXPECTED["ETF_MANIFEST_SHA256"],
        "TRANSACTION_COST": "20bps total round trip; net20 = normalized gross - 0.002",
        "TRANSACTION_COST_DECIMAL": 0.002,
        "CORPORATE_ACTION_NORMALIZATION": "issuer-authoritative cumulative share-equivalence factor at economic-return layer; canonical raw bars unchanged",
        "PRE_ENTRY_EVENT_POLICY": "PRE_ENTRY_TOUCH_NOT_CAPTURABLE; preserve reconciliation row and exclude from executable target cohort",
        "MISSING_DATA_POLICY": "retain explicit invalid/nonexecutable state; exclude from valid target cohort; no imputation and no silent drop",
        "PIT_REQUIREMENT": "feature_timestamp <= decision_timestamp; future path and ETF payoff appear only in y",
        "FINAL_CONFIRMATION_DATA_USED": False,
        "FINAL_CONFIRMATION_OUTCOME_ACCESS_ALLOWED": False,
        "MUTATION_POLICY": "STOP_TARGET_CONTRACT_MUTATED_AFTER_FREEZE",
        "AUTHORITATIVE_SOURCES": {
            "R28_FINAL_CLOSEOUT": str(R28_FINAL_CLOSEOUT),
            "R28_TARGET_PROPOSAL": str(TARGET_PROPOSAL),
            "R28_3G_CORRECTED_LEDGER": str(ECONOMIC_LEDGER),
        },
    }


def freeze_target_contract(path: Path, created_at: str) -> str:
    if path.exists():
        raise R30AStop("STOP_TARGET_CONTRACT_ALREADY_EXISTS_NO_AUTOMATIC_REFREEZE")
    write_json(path, target_contract(created_at))
    return file_sha256(path)


def guard_frozen_contract(path: Path, expected_sha256: str) -> None:
    if not path.is_file() or file_sha256(path) != expected_sha256:
        raise R30AStop("STOP_TARGET_CONTRACT_MUTATED_AFTER_FREEZE")


def make_targets(ledger: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    required = {
        "candidate_id", "underlying_symbol", "head", "timestamp", "action_instrument",
        "first_touch_exit_timestamp", "corrected_net20", "pre_entry_touch",
        "economic_reconciliation_state", "primary_executable_first_touch_cohort",
        "etf_manifest_sha256",
    }
    missing = required.difference(ledger.columns)
    if missing:
        raise R30AStop("STOP_ECONOMIC_LEDGER_SCHEMA_MISSING:" + ",".join(sorted(missing)))
    if len(ledger) != 1198 or ledger["candidate_id"].duplicated().any():
        raise R30AStop("STOP_ECONOMIC_LEDGER_CARDINALITY")
    manifest_values = set(ledger["etf_manifest_sha256"].astype(str))
    if manifest_values != {EXPECTED["ETF_MANIFEST_SHA256"]}:
        raise R30AStop("STOP_ETF_MANIFEST_MISMATCH")
    valid_flag = ledger["primary_executable_first_touch_cohort"].astype(bool)
    pre_entry = ledger["pre_entry_touch"].astype(bool)
    if int(pre_entry.sum()) != 1 or not bool((~valid_flag).equals(pre_entry)):
        raise R30AStop("STOP_PRE_ENTRY_RECONCILIATION_MISMATCH")
    out = ledger.loc[valid_flag & ~pre_entry].copy()
    out["raw_net20"] = pd.to_numeric(out["corrected_net20"], errors="raise")
    if out["raw_net20"].isna().any():
        raise R30AStop("STOP_VALID_TARGET_MISSING")
    out["T1_POSITIVE_NET20"] = (out["raw_net20"] > 0.0).astype(int)
    out["T2_ROBUST_NET20"] = np.sign(out["raw_net20"]) * np.log1p(np.abs(out["raw_net20"]))
    out["decision_timestamp_utc"] = pd.to_datetime(out["timestamp"], utc=True, errors="raise")
    out["label_information_end_utc"] = pd.to_datetime(out["first_touch_exit_timestamp"], utc=True, errors="raise")
    if len(out) != EXPECTED["TARGET_ROWS"]:
        raise R30AStop("STOP_TARGET_ROW_COUNT_RECONCILIATION")
    checks = {
        "t1_rate": float(out["T1_POSITIVE_NET20"].mean()),
        "raw_mean": float(out["raw_net20"].mean()),
        "raw_median": float(out["raw_net20"].median()),
        "robust_mean": float(out["T2_ROBUST_NET20"].mean()),
        "robust_median": float(out["T2_ROBUST_NET20"].median()),
    }
    for observed, expected in (
        (checks["t1_rate"], EXPECTED["T1_RATE"]),
        (checks["raw_mean"], EXPECTED["RAW_MEAN"]),
        (checks["raw_median"], EXPECTED["RAW_MEDIAN"]),
        (checks["robust_mean"], EXPECTED["ROBUST_MEAN"]),
        (checks["robust_median"], EXPECTED["ROBUST_MEDIAN"]),
    ):
        if not math.isclose(observed, expected, rel_tol=0.0, abs_tol=2e-15):
            raise R30AStop("STOP_TARGET_RECONCILIATION_STAT_MISMATCH")
    audit = {
        "source_row_count": int(len(ledger)),
        "valid_target_row_count": int(len(out)),
        "explicit_excluded_row_count": int((~valid_flag).sum()),
        "pre_entry_noncapturable_excluded_count": int(pre_entry.sum()),
        "silent_drop_count": 0,
        **checks,
    }
    return out.reset_index(drop=True), audit


def import_phase2_module():
    path = SOURCE_ROOT / "fast3" / "scripts" / "run" / "fast3_r28_phase2_fixed_training.py"
    spec = importlib.util.spec_from_file_location("fast3_r30a_bound_r28_phase2", path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise R30AStop("STOP_R28_MODULE_IMPORT")
    spec.loader.exec_module(module)
    return module


def verify_authoritative_inputs() -> dict[str, Any]:
    observed = {
        "economic_ledger": file_sha256(ECONOMIC_LEDGER),
        "feature_manifest": file_sha256(R28_FEATURE_MANIFEST),
        "model_identity": file_sha256(R28_MODEL_IDENTITY),
        "split_contract": file_sha256(R28_SPLIT_CONTRACT),
    }
    expected = {
        "economic_ledger": EXPECTED["ECONOMIC_LEDGER_SHA256"],
        "feature_manifest": EXPECTED["FEATURE_MANIFEST_SHA256"],
        "model_identity": EXPECTED["MODEL_IDENTITY_SHA256"],
        "split_contract": EXPECTED["SPLIT_CONTRACT_SHA256"],
    }
    if observed != expected:
        raise R30AStop("STOP_AUTHORITATIVE_INPUT_HASH_MISMATCH:" + str(observed))
    feature_manifest = read_json(R28_FEATURE_MANIFEST)
    model_identity = read_json(R28_MODEL_IDENTITY)
    split_contract = read_json(R28_SPLIT_CONTRACT)
    closeout = read_json(R28_FINAL_CLOSEOUT)
    source_manifest = read_json(R28_SOURCE_MANIFEST)
    if model_identity.get("features") != list(FEATURES) or model_identity.get("feature_count") != len(FEATURES):
        raise R30AStop("STOP_FROZEN_FEATURE_IDENTITY_MISMATCH")
    if feature_manifest.get("candidates", {}).get("R28_3_CROSS_ASSET_FLOW") != list(FEATURES):
        raise R30AStop("STOP_R28_CHAMPION_FEATURE_MISMATCH")
    if split_contract.get("oof_folds") != [list(row) for row in ORIGINAL_FOLDS]:
        raise R30AStop("STOP_SPLIT_IDENTITY_MISMATCH")
    if split_contract.get("true_holdout_start_utc") != TRUE_HOLDOUT_START.isoformat():
        raise R30AStop("STOP_TRUE_HOLDOUT_IDENTITY_MISMATCH")
    if source_manifest.get("sha256") != EXPECTED["SOURCE_MANIFEST_LOGICAL_SHA256"]:
        raise R30AStop("STOP_FEATURE_SOURCE_MANIFEST_MISMATCH")
    if closeout.get("FAST3_R28_FINAL_DECISION") != "CLOSED_EVENT_PREDICTION_EDGE_CONFIRMED_ECONOMIC_TARGET_MISALIGNED":
        raise R30AStop("STOP_R28_CLOSEOUT_BINDING_MISMATCH")
    return {"hashes": observed, "feature_manifest": feature_manifest, "model_identity": model_identity,
            "split_contract": split_contract, "source_manifest": source_manifest, "closeout": closeout}


def build_selected_feature_ledger(targets: pd.DataFrame, authoritative: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Rebuild only the selected rows with the frozen R28 feature functions."""
    p2 = import_phase2_module()
    records = authoritative["source_manifest"]["files"]
    paths = p2.exact_paths(records)  # verifies every authoritative source partition hash
    data = {symbol: p2.read_symbol(paths[symbol]) for symbol in p2.R1.SYMBOLS}
    frames: list[pd.DataFrame] = []
    pit_audits: dict[str, Any] = {}
    for symbol, peer in (("QQQ", "SOXX"), ("SOXX", "QQQ")):
        bars = data[symbol]
        baseline = p2.R1.feature_frame(bars, symbol)
        additions = p2.build_features(bars, data[peer])
        pit_audit = p2.pit_audit(additions.dropna(subset=list(p2.R28_FEATURES)))
        selected = targets.loc[targets["underlying_symbol"].eq(symbol),
                               ["candidate_id", "head", "decision_timestamp_utc"]].copy()
        wanted = pd.Index(selected["decision_timestamp_utc"].unique())
        mask = bars["timestamp_utc"].isin(wanted)
        feature_rows = pd.concat([
            bars.loc[mask, ["timestamp_utc"]].reset_index(drop=True),
            baseline.loc[mask, [name for name in FEATURES if name not in p2.R28_FEATURES and name != "direction_code"]].reset_index(drop=True),
            additions.loc[mask, [*SELECTED_R28_ADDITIONS, "max_feature_timestamp_utc"]].reset_index(drop=True),
        ], axis=1).rename(columns={"timestamp_utc": "decision_timestamp_utc"})
        expanded = selected.merge(feature_rows, on="decision_timestamp_utc", how="left", validate="many_to_one")
        expanded["direction_code"] = expanded["head"].map({"UP": 1, "DOWN": -1})
        expanded["underlying_symbol"] = symbol
        frames.append(expanded)
        pit_audits[symbol] = pit_audit
    features = pd.concat(frames, ignore_index=True)
    if len(features) != len(targets) or features["candidate_id"].duplicated().any():
        raise R30AStop("STOP_FEATURE_TARGET_CARDINALITY_MISMATCH")
    # This exactly matches R28 Phase 2: the selected R28 additions must be
    # complete, while HGB natively handles missing values in legacy baseline
    # columns (88 frozen range_position values are undefined on flat ranges).
    if features[list(SELECTED_R28_ADDITIONS)].isna().any().any():
        raise R30AStop("STOP_SELECTED_R28_FEATURE_MISSING")
    if not (pd.to_datetime(features["max_feature_timestamp_utc"], utc=True) <= features["decision_timestamp_utc"]).all():
        raise R30AStop("STOP_FUTURE_FEATURE_TIMESTAMP")
    expected_ids = set(targets["candidate_id"].astype(str))
    if set(features["candidate_id"].astype(str)) != expected_ids:
        raise R30AStop("STOP_FEATURE_CANDIDATE_ID_MISMATCH")
    audit = {
        "row_count": int(len(features)),
        "feature_count": len(FEATURES),
        "feature_names": list(FEATURES),
        "all_feature_timestamps_pit": True,
        "source_partition_count": int(len(records)),
        "source_partition_hashes_verified": True,
        "hgb_native_missing_value_counts": {
            name: int(features[name].isna().sum()) for name in FEATURES
        },
        "preprocessing_or_imputation_applied": False,
        "symbols": pit_audits,
    }
    return features.sort_values("candidate_id", kind="mergesort").reset_index(drop=True), audit


def assert_feature_pit(frame: pd.DataFrame) -> None:
    decision = pd.to_datetime(frame["decision_timestamp_utc"], utc=True, errors="raise")
    maximum = pd.to_datetime(frame["max_feature_timestamp_utc"], utc=True, errors="raise")
    if not bool((maximum <= decision).all()):
        raise R30AStop("STOP_FUTURE_FEATURE_TIMESTAMP")


def construct_economic_fold(frame: pd.DataFrame, fold: tuple[str, str, str]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    name, raw_start, raw_end = fold
    start = pd.Timestamp(raw_start, tz="UTC")
    end = pd.Timestamp(raw_end, tz="UTC")
    validation = frame.loc[frame["decision_timestamp_utc"].between(start, end)].copy()
    if validation.empty:
        raise R30AStop("STOP_EMPTY_ECONOMIC_VALIDATION_FOLD:" + name)
    validation_min = validation["decision_timestamp_utc"].min()
    information_cutoff = validation_min - PURGE_EMBARGO
    train = frame.loc[frame["label_information_end_utc"] < information_cutoff].copy()
    train_info_end = train["label_information_end_utc"].max() if not train.empty else pd.NaT
    audit = {
        "fold": name,
        "train_rows": int(len(train)),
        "validation_rows": int(len(validation)),
        "train_candidate_min": train["decision_timestamp_utc"].min() if not train.empty else None,
        "train_candidate_max": train["decision_timestamp_utc"].max() if not train.empty else None,
        "train_label_information_end_max": train_info_end,
        "validation_candidate_min": validation_min,
        "validation_candidate_max": validation["decision_timestamp_utc"].max(),
        "purge_minutes": 1440,
        "embargo_minutes": 1440,
        "time_order_pass": bool(train.empty or train["decision_timestamp_utc"].max() < validation_min),
        "purge_pass": bool(train.empty or train_info_end < information_cutoff),
        "embargo_pass": bool(train.empty or train_info_end < information_cutoff),
        "overlapping_label_contamination_count": int((train["label_information_end_utc"] >= information_cutoff).sum()),
    }
    if train.empty or not all(audit[key] for key in ("time_order_pass", "purge_pass", "embargo_pass")):
        raise R30AStop("STOP_ECONOMIC_FOLD_CONTRACT:" + name)
    return train, validation, audit


def safe_spearman(x: Any, y: Any) -> float | None:
    a = np.asarray(x, dtype=float)
    b = np.asarray(y, dtype=float)
    if len(a) < 2 or np.unique(a).size < 2 or np.unique(b).size < 2:
        return None
    value = float(spearmanr(a, b).statistic)
    return value if np.isfinite(value) else None


def t1_metrics(y: Any, probability: Any) -> dict[str, float | None]:
    truth = np.asarray(y, dtype=int)
    prob = np.clip(np.asarray(probability, dtype=float), 1e-15, 1 - 1e-15)
    return {
        "ROC_AUC": float(roc_auc_score(truth, prob)) if np.unique(truth).size == 2 else None,
        "PR_AUC": float(average_precision_score(truth, prob)) if np.unique(truth).size == 2 else None,
        "Brier": float(brier_score_loss(truth, prob)),
        "LogLoss": float(log_loss(truth, prob, labels=[0, 1])),
    }


def t2_metrics(y: Any, prediction: Any, raw: Any) -> dict[str, float | None]:
    actual = np.asarray(y, dtype=float)
    pred = np.asarray(prediction, dtype=float)
    return {
        "MAE": float(mean_absolute_error(actual, pred)),
        "RMSE": float(np.sqrt(mean_squared_error(actual, pred))),
        "Spearman_vs_transformed": safe_spearman(pred, actual),
        "Spearman_vs_raw_net20": safe_spearman(pred, raw),
    }


def calibration_diagnostics(y: Any, probability: Any, bins: int = 10) -> dict[str, float | None]:
    truth = np.asarray(y, dtype=float)
    prob = np.clip(np.asarray(probability, dtype=float), 1e-8, 1 - 1e-8)
    logit = np.log(prob / (1.0 - prob))

    def objective(beta: np.ndarray) -> float:
        z = np.clip(beta[0] + beta[1] * logit, -35, 35)
        return float(np.sum(np.logaddexp(0.0, z) - truth * z))

    fitted = minimize(objective, np.array([0.0, 1.0]), method="BFGS")
    edges = np.linspace(0.0, 1.0, bins + 1)
    assignments = np.clip(np.digitize(prob, edges[1:-1]), 0, bins - 1)
    ece = 0.0
    for index in range(bins):
        mask = assignments == index
        if mask.any():
            ece += float(mask.mean()) * abs(float(truth[mask].mean()) - float(prob[mask].mean()))
    return {
        "calibration_intercept": float(fitted.x[0]) if fitted.success else None,
        "calibration_slope": float(fitted.x[1]) if fitted.success else None,
        "ECE_10": float(ece),
    }


def ranked(frame: pd.DataFrame, prediction_column: str) -> pd.DataFrame:
    return frame.sort_values([prediction_column, "decision_timestamp_utc", "candidate_id"],
                             ascending=[False, True, True], kind="mergesort")


def t1_ranking_metrics(frame: pd.DataFrame, prediction_column: str = "pred_t1") -> pd.DataFrame:
    ordered = ranked(frame, prediction_column)
    base_rate = float(frame["T1_POSITIVE_NET20"].mean())
    base_mean = float(frame["raw_net20"].mean())
    rows = []
    for pct in TOP_BUCKETS:
        count = max(1, int(math.ceil(len(ordered) * pct / 100.0)))
        top = ordered.head(count)
        rate = float(top["T1_POSITIVE_NET20"].mean())
        fold_base = float(top["t1_fold_train_base_rate"].mean()) if "t1_fold_train_base_rate" in top else base_rate
        rows.append({
            "bucket": f"Top{pct}%", "bucket_percent": pct, "trade_count": int(len(top)),
            "actual_positive_rate": rate, "unconditional_positive_rate": base_rate,
            "absolute_gain_vs_unconditional": rate - base_rate,
            "relative_lift_vs_unconditional": rate / base_rate if base_rate else None,
            "expected_training_fold_base_rate": fold_base,
            "absolute_gain_vs_fold_base_rate": rate - fold_base,
            "relative_lift_vs_fold_base_rate": rate / fold_base if fold_base else None,
            "actual_mean_net20": float(top["raw_net20"].mean()),
            "actual_median_net20": float(top["raw_net20"].median()),
            "unconditional_mean_net20": base_mean,
        })
    return pd.DataFrame(rows)


def t2_ranking_metrics(frame: pd.DataFrame, prediction_column: str = "pred_t2") -> pd.DataFrame:
    ordered = ranked(frame, prediction_column)
    base_mean = float(frame["raw_net20"].mean())
    rows = []
    for pct in TOP_BUCKETS:
        count = max(1, int(math.ceil(len(ordered) * pct / 100.0)))
        top = ordered.head(count)
        rows.append({
            "bucket": f"Top{pct}%", "bucket_percent": pct, "trade_count": int(len(top)),
            "mean_raw_net20": float(top["raw_net20"].mean()),
            "median_raw_net20": float(top["raw_net20"].median()),
            "positive_rate": float(top["T1_POSITIVE_NET20"].mean()),
            "p05_raw_net20": float(top["raw_net20"].quantile(0.05)),
            "unconditional_validation_mean_raw_net20": base_mean,
            "gain_vs_unconditional_validation_baseline": float(top["raw_net20"].mean()) - base_mean,
        })
    return pd.DataFrame(rows)


def fixed_deciles(frame: pd.DataFrame, prediction_column: str, head: str) -> pd.DataFrame:
    ordered = frame.sort_values([prediction_column, "decision_timestamp_utc", "candidate_id"],
                                ascending=[True, True, True], kind="mergesort").copy()
    ordered["prediction_decile"] = np.floor(np.arange(len(ordered)) * 10 / len(ordered)).astype(int) + 1
    grouped = ordered.groupby("prediction_decile", sort=True)
    rows = grouped.agg(
        trade_count=("candidate_id", "size"),
        prediction_mean=(prediction_column, "mean"),
        actual_positive_rate=("T1_POSITIVE_NET20", "mean"),
        actual_transformed_T2_mean=("T2_ROBUST_NET20", "mean"),
        actual_raw_net20_mean=("raw_net20", "mean"),
    ).reset_index()
    rows.insert(0, "head", head)
    return rows


def bucket_row(table: pd.DataFrame, pct: int) -> dict[str, Any]:
    return table.loc[table["bucket_percent"].eq(pct)].iloc[0].to_dict()


def direction_status(frame: pd.DataFrame, direction: str, target: str) -> tuple[str, dict[str, Any]]:
    part = frame.loc[frame["head"].eq(direction)].copy()
    t1_rank = t1_ranking_metrics(part)
    t2_rank = t2_ranking_metrics(part)
    if target == "T1":
        metric = t1_metrics(part["T1_POSITIVE_NET20"], part["pred_t1"])
        dec = fixed_deciles(part, "pred_t1", direction)
        monotonic = safe_spearman(dec["prediction_decile"], dec["actual_positive_rate"])
        passed = bool(metric["ROC_AUC"] is not None and metric["ROC_AUC"] > .5
                      and bucket_row(t1_rank, 20)["absolute_gain_vs_unconditional"] > 0
                      and bucket_row(t1_rank, 10)["absolute_gain_vs_unconditional"] > 0
                      and monotonic is not None and monotonic > 0)
        details = {**metric, "decile_spearman": monotonic,
                   "top20_gain": bucket_row(t1_rank, 20)["absolute_gain_vs_unconditional"],
                   "top10_gain": bucket_row(t1_rank, 10)["absolute_gain_vs_unconditional"]}
    else:
        metric = t2_metrics(part["T2_ROBUST_NET20"], part["pred_t2"], part["raw_net20"])
        dec = fixed_deciles(part, "pred_t2", direction)
        monotonic = safe_spearman(dec["prediction_decile"], dec["actual_raw_net20_mean"])
        passed = bool(metric["Spearman_vs_raw_net20"] is not None and metric["Spearman_vs_raw_net20"] > 0
                      and bucket_row(t2_rank, 20)["gain_vs_unconditional_validation_baseline"] > 0
                      and bucket_row(t2_rank, 10)["gain_vs_unconditional_validation_baseline"] > 0
                      and monotonic is not None and monotonic > 0)
        details = {**metric, "decile_spearman": monotonic,
                   "top20_gain": bucket_row(t2_rank, 20)["gain_vs_unconditional_validation_baseline"],
                   "top10_gain": bucket_row(t2_rank, 10)["gain_vs_unconditional_validation_baseline"]}
    return ("GO" if passed else "NO_GO"), details


def model_parameters() -> tuple[dict[str, Any], dict[str, Any]]:
    categorical_mask = [name in CATEGORICAL for name in FEATURES]
    common = {**HGB_PARAMS, "categorical_features": categorical_mask}
    return common.copy(), common.copy()


def git_identity() -> tuple[str, str, str]:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=SOURCE_ROOT, text=True).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE_ROOT, text=True).strip()
    return branch, head, head


def training_identity_hash(frame: pd.DataFrame) -> str:
    return hashlib.sha256("\n".join(frame.sort_values("candidate_id")["candidate_id"].astype(str)).encode("utf-8")).hexdigest()


def robustness_tables(oof: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    def rows_for(group_name: str, column: str, source: pd.DataFrame | None = None) -> pd.DataFrame:
        rows = []
        grouped_source = oof if source is None else source
        for value, part in grouped_source.groupby(column, sort=True):
            t1_rank = t1_ranking_metrics(part)
            t2_rank = t2_ranking_metrics(part)
            rows.append({
                "robustness_type": group_name, "group": str(value), "sample_count": int(len(part)),
                "positive_rate": float(part["T1_POSITIVE_NET20"].mean()),
                "raw_mean_net20": float(part["raw_net20"].mean()),
                "T1_ROC_AUC": t1_metrics(part["T1_POSITIVE_NET20"], part["pred_t1"])["ROC_AUC"],
                "T1_Top20_mean_net20": bucket_row(t1_rank, 20)["actual_mean_net20"],
                "T2_Spearman_vs_raw_net20": safe_spearman(part["pred_t2"], part["raw_net20"]),
                "T2_Top20_mean_net20": bucket_row(t2_rank, 20)["mean_raw_net20"],
            })
        return pd.DataFrame(rows)
    year = oof.copy()
    year["calendar_year"] = year["decision_timestamp_utc"].dt.year
    return rows_for("YEAR", "calendar_year", year), rows_for("DIRECTION", "head"), rows_for("SYMBOL", "action_instrument")


def report_text(summary: dict[str, Any], t1_rank: pd.DataFrame, t2_rank: pd.DataFrame) -> str:
    t1 = {int(row.bucket_percent): row for row in t1_rank.itertuples()}
    t2 = {int(row.bucket_percent): row for row in t2_rank.itertuples()}
    easier = summary["ECONOMIC_PAYOFF_EASIER_DIRECTION"]
    next_choice = summary["NEXT_STAGE"]
    return f"""# FAST3 R30A — Frozen T1/T2 Economic-Target Baseline Training

## Decision

- Status: `{summary['FAST3_R30A_STATUS']}`
- Classification: `{summary['FAST3_R30A_CLASSIFICATION']}`
- Decision: `{summary['FAST3_R30A_DECISION']}`
- Final untouched confirmation used: `false`
- Official adoption/live trading allowed: `false / false`

## Direct answers

1. **Can T1 predict `net20 > 0`?** {summary['T1_PLAIN_ANSWER']}
2. **AUC / calibration:** AUC={summary['T1_ROC_AUC']:.6f}, Brier={summary['T1_BRIER']:.6f}, log loss={summary['T1_LOGLOSS']:.6f}, calibration intercept={summary['T1_CALIBRATION_INTERCEPT']}, slope={summary['T1_CALIBRATION_SLOPE']}, ECE={summary['T1_ECE']}.
3. **T1 realized win rates:** Top20={t1[20].actual_positive_rate:.4%}, Top10={t1[10].actual_positive_rate:.4%}, Top5={t1[5].actual_positive_rate:.4%}.
4. **Did T1 cohorts turn mean net20 positive?** Top20={t1[20].actual_mean_net20:.4%}, Top10={t1[10].actual_mean_net20:.4%}, Top5={t1[5].actual_mean_net20:.4%}; {summary['T1_POSITIVE_COHORT_ANSWER']}.
5. **Is T1 stable across folds?** {summary['T1_POSITIVE_FOLD_COUNT']}/{summary['FOLD_COUNT']} folds have positive Top20 win-rate gain: `{summary['T1_FOLD_STABILITY_ANSWER']}`.
6. **Does T2 positively rank raw net20?** Spearman={summary['T2_SPEARMAN_VS_RAW_NET20']:.6f}: `{summary['T2_PLAIN_ANSWER']}`.
7. **T2 realized mean net20:** Top20={t2[20].mean_raw_net20:.4%}, Top10={t2[10].mean_raw_net20:.4%}, Top5={t2[5].mean_raw_net20:.4%}.
8. **Is T2 stable across folds?** {summary['T2_POSITIVE_FOLD_COUNT']}/{summary['FOLD_COUNT']} folds improve Top20 mean: `{summary['T2_FOLD_STABILITY_ANSWER']}`.
9. **Which direction is easier?** `{easier}`. UP: T1={summary['UP_T1_STATUS']}, T2={summary['UP_T2_STATUS']}; DOWN: T1={summary['DOWN_T1_STATUS']}, T2={summary['DOWN_T2_STATUS']}.
10. **Do current features contain economic information?** `{summary['CURRENT_FEATURES_ECONOMIC_INFORMATION_STATUS']}`.
11. **R28 target misalignment or weak economic features?** {summary['PRIMARY_RESEARCH_INTERPRETATION']}
12. **Recommended next step:** `{next_choice}`. No combined-rule or threshold optimization was run.
13. **Open final untouched confirmation?** `{summary['FINAL_CONFIRMATION_RECOMMENDATION']}`. R30A does not open it automatically.

## Research controls

`SAME FEATURES / SAME PIT / SAME ECONOMIC CONTRACT / SAME HISTORICAL DATA DISCIPLINE / ONLY TARGET CHANGES`

- Target contract frozen before all {summary['MODEL_FIT_COUNT']} fits: `{summary['TARGET_CONTRACT_SHA256']}`
- Features: {summary['FEATURE_COUNT']} frozen R28 champion features; no expansion/removal/engineering changes
- Split: {summary['FOLD_COUNT']} expanding annual economic folds; 1440-minute purge and embargo
- Hyperparameter searches: 0
- R29 modified/resumed: false / false
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--resume-after-pre-fit-implementation-fix", action="store_true")
    parser.add_argument("--resume-post-fit-reporting-only", action="store_true")
    args = parser.parse_args()
    run_name = f"r30a_economic_target_{args.run_id}"
    runtime = RESULTS_ROOT / "runtime" / "fast3" / run_name
    scratch = RESULTS_ROOT / "scratch" / "fast3" / run_name
    frozen = RESULTS_ROOT / "frozen" / "fast3" / run_name
    branch, start_head, head = git_identity()
    contract_path = frozen / "FAST3_R30_T1_T2_ECONOMIC_TARGET_CONTRACT_R1.json"
    postfit_resume = False
    if any(path.exists() for path in (runtime, scratch, frozen)):
        if not (args.resume_after_pre_fit_implementation_fix or args.resume_post_fit_reporting_only) or not all(path.is_dir() for path in (runtime, scratch, frozen)):
            raise R30AStop("STOP_R30A_RUN_ID_ALREADY_EXISTS")
        if not contract_path.is_file():
            raise R30AStop("STOP_RESUME_WITHOUT_FROZEN_TARGET_CONTRACT")
        existing_contract = read_json(contract_path)
        created_at = str(existing_contract.get("CREATED_AT_UTC"))
        if existing_contract != target_contract(created_at):
            raise R30AStop("STOP_TARGET_CONTRACT_MUTATED_AFTER_FREEZE")
        contract_sha = file_sha256(contract_path)
        model_files = sorted((scratch / "models").glob("*.joblib"))
        if args.resume_post_fit_reporting_only:
            required_checkpoints = [
                scratch / "FAST3_R30A_FROZEN_FEATURE_LEDGER.parquet",
                scratch / "FAST3_R30A_TARGET_LEDGER.parquet",
                scratch / "FAST3_R30A_OOF_PREDICTION_LEDGER.parquet",
                frozen / "FAST3_R30A_TRAINING_DATA_IDENTITY.json",
                frozen / "FAST3_R30A_FEATURE_IDENTITY.json",
                frozen / "FAST3_R30A_SPLIT_IDENTITY.json",
            ]
            if len(model_files) != 20 or not all(path.is_file() for path in required_checkpoints):
                raise R30AStop("STOP_POSTFIT_RESUME_CHECKPOINT_INCOMPLETE")
            postfit_resume = True
        else:
            if model_files:
                raise R30AStop("STOP_RESUME_AFTER_ANY_MODEL_FIT")
            frozen_files = [path for path in frozen.iterdir() if path.is_file()]
            if frozen_files != [contract_path]:
                raise R30AStop("STOP_RESUME_AFTER_IDENTITY_OR_RESULT_WRITE")
    else:
        runtime.mkdir(parents=True)
        (scratch / "models").mkdir(parents=True)
        frozen.mkdir(parents=True)
        created_at = datetime.now(timezone.utc).isoformat()
        # The target contract is the first frozen artifact and is immutable from here.
        contract_sha = freeze_target_contract(contract_path, created_at)
    guard_frozen_contract(contract_path, contract_sha)

    authoritative = verify_authoritative_inputs()
    ledger = pd.read_csv(ECONOMIC_LEDGER)
    targets, target_audit = make_targets(ledger)
    if targets["decision_timestamp_utc"].max() >= TRUE_HOLDOUT_START:
        raise R30AStop("STOP_FINAL_CONFIRMATION_DATA_ACCESSED")
    feature_ledger_path = scratch / "FAST3_R30A_FROZEN_FEATURE_LEDGER.parquet"
    if postfit_resume:
        features = pd.read_parquet(feature_ledger_path)
        feature_audit = read_json(frozen / "FAST3_R30A_FEATURE_IDENTITY.json")["FEATURE_PIT_AUDIT"]
    else:
        features, feature_audit = build_selected_feature_ledger(targets, authoritative)
    assert_feature_pit(features)
    dataset = targets.merge(features.drop(columns=["underlying_symbol", "head"]), on=["candidate_id", "decision_timestamp_utc"], how="left", validate="one_to_one")
    if dataset[list(SELECTED_R28_ADDITIONS)].isna().any().any():
        raise R30AStop("STOP_TRAINING_DATA_FEATURE_JOIN")
    dataset = dataset.sort_values(["decision_timestamp_utc", "candidate_id"], kind="mergesort").reset_index(drop=True)

    target_ledger_path = scratch / "FAST3_R30A_TARGET_LEDGER.parquet"
    if not postfit_resume:
        features.to_parquet(feature_ledger_path, index=False)
        dataset[["candidate_id", "decision_timestamp_utc", "label_information_end_utc", "head", "action_instrument",
                 "raw_net20", "T1_POSITIVE_NET20", "T2_ROBUST_NET20"]].to_parquet(target_ledger_path, index=False)

    data_identity = {
        "GENERATION": "R30", "STAGE": "R30A", "TARGET_ROW_COUNT": int(len(dataset)),
        "ECONOMIC_LEDGER_SOURCE": str(ECONOMIC_LEDGER), "ECONOMIC_LEDGER_SHA256": file_sha256(ECONOMIC_LEDGER),
        "ECONOMIC_LEDGER_SOURCE_ROW_COUNT": int(len(ledger)), "TARGET_RECONCILIATION": target_audit,
        "ETF_MANIFEST_SHA256": EXPECTED["ETF_MANIFEST_SHA256"],
        "FEATURE_LEDGER_SOURCE": str(feature_ledger_path), "FEATURE_LEDGER_SHA256": file_sha256(feature_ledger_path),
        "TARGET_LEDGER_PATH": str(target_ledger_path), "TARGET_LEDGER_SHA256": file_sha256(target_ledger_path),
        "TARGET_CONTRACT_SHA256": contract_sha, "FINAL_CONFIRMATION_DATA_USED": False,
        "MAX_DECISION_TIMESTAMP": dataset["decision_timestamp_utc"].max(),
        "TRUE_HOLDOUT_START": TRUE_HOLDOUT_START, "SILENT_DROP_COUNT": 0,
    }
    feature_identity = {
        "FEATURE_MANIFEST_SOURCE": str(R28_FEATURE_MANIFEST),
        "FEATURE_MANIFEST_SHA256": EXPECTED["FEATURE_MANIFEST_SHA256"],
        "R28_SELECTED_MODEL_IDENTITY_SOURCE": str(R28_MODEL_IDENTITY),
        "R28_SELECTED_MODEL_IDENTITY_SHA256": EXPECTED["MODEL_IDENTITY_SHA256"],
        "R28_CHAMPION": "R28_3_CROSS_ASSET_FLOW", "FEATURE_COUNT": len(FEATURES),
        "FEATURE_NAMES": list(FEATURES), "FEATURE_EXPANSION": False, "FEATURE_REMOVAL": False,
        "FEATURE_ENGINEERING_CHANGES": False, "FEATURE_PIT_AUDIT": feature_audit,
    }
    split_identity = {
        "SPLIT_CONTRACT_SOURCE": str(R28_SPLIT_CONTRACT),
        "SPLIT_CONTRACT_SHA256": EXPECTED["SPLIT_CONTRACT_SHA256"],
        "ORIGINAL_FOLDS": [list(row) for row in ORIGINAL_FOLDS],
        "ECONOMIC_WARMUP_FOLD": "OOF_2020", "WARMUP_REASON": "no earlier economic targets exist",
        "EVALUATED_FOLDS": [list(row) for row in ECONOMIC_FOLDS], "FOLD_COUNT": len(ECONOMIC_FOLDS),
        "SPLIT_SEARCH_COUNT": 0, "TIME_ORDERED": True, "PURGE_MINUTES": 1440,
        "EMBARGO_MINUTES": 1440, "NO_OVERLAPPING_LABEL_CONTAMINATION": True,
        "FINAL_CONFIRMATION_DATA_USED": False, "TRUE_HOLDOUT_START": TRUE_HOLDOUT_START,
    }
    if postfit_resume:
        existing_data_identity = read_json(frozen / "FAST3_R30A_TRAINING_DATA_IDENTITY.json")
        if (existing_data_identity["FEATURE_LEDGER_SHA256"] != file_sha256(feature_ledger_path)
                or existing_data_identity["TARGET_CONTRACT_SHA256"] != contract_sha):
            raise R30AStop("STOP_POSTFIT_RESUME_IDENTITY_MUTATED")
    else:
        write_json(frozen / "FAST3_R30A_TRAINING_DATA_IDENTITY.json", data_identity)
        write_json(frozen / "FAST3_R30A_FEATURE_IDENTITY.json", feature_identity)
        write_json(frozen / "FAST3_R30A_SPLIT_IDENTITY.json", split_identity)
    guard_frozen_contract(contract_path, contract_sha)

    classifier_params, regressor_params = model_parameters()
    oof_parts: list[pd.DataFrame] = []
    t1_fold_rows: list[dict[str, Any]] = []
    t2_fold_rows: list[dict[str, Any]] = []
    fold_audits: list[dict[str, Any]] = []
    model_records: list[dict[str, Any]] = []
    fit_count = 0
    predict_count = 0
    folds_to_fit = () if postfit_resume else ECONOMIC_FOLDS
    for fold in folds_to_fit:
        train_all, validation_all, fold_audit = construct_economic_fold(dataset, fold)
        fold_audits.append(fold_audit)
        validation_parts = []
        for direction in ("UP", "DOWN"):
            train = train_all.loc[train_all["head"].eq(direction)].copy()
            validation = validation_all.loc[validation_all["head"].eq(direction)].copy()
            if train.empty or validation.empty or train["T1_POSITIVE_NET20"].nunique() < 2:
                raise R30AStop(f"STOP_INSUFFICIENT_DIRECTION_FOLD:{fold[0]}:{direction}")
            guard_frozen_contract(contract_path, contract_sha)
            classifier = HistGradientBoostingClassifier(**classifier_params)
            classifier.fit(train[list(FEATURES)], train["T1_POSITIVE_NET20"].astype(int))
            fit_count += 1
            guard_frozen_contract(contract_path, contract_sha)
            regressor = HistGradientBoostingRegressor(**regressor_params)
            regressor.fit(train[list(FEATURES)], train["T2_ROBUST_NET20"].astype(float))
            fit_count += 1
            scored = validation.copy()
            scored["pred_t1"] = classifier.predict_proba(validation[list(FEATURES)])[:, 1]
            predict_count += 1
            scored["pred_t2"] = regressor.predict(validation[list(FEATURES)])
            predict_count += 1
            base_rate = float(train["T1_POSITIVE_NET20"].mean())
            scored["t1_fold_train_base_rate"] = base_rate
            scored["t1_baseline_constant"] = base_rate
            scored["t1_baseline_majority"] = float(base_rate >= .5)
            scored["t2_baseline_mean"] = float(train["T2_ROBUST_NET20"].mean())
            scored["t2_baseline_median"] = float(train["T2_ROBUST_NET20"].median())
            scored["fold"] = fold[0]
            validation_parts.append(scored)
            for target_name, model in (("T1", classifier), ("T2", regressor)):
                model_path = scratch / "models" / f"{target_name}_{direction}_{fold[0]}.joblib"
                joblib.dump(model, model_path, compress=3)
                model_records.append({
                    "target": target_name, "direction": direction, "fold": fold[0],
                    "model_family": type(model).__name__, "parameters": model.get_params(deep=False),
                    "training_row_count": int(len(train)), "training_identity_sha256": training_identity_hash(train),
                    "model_path": str(model_path), "model_sha256": file_sha256(model_path),
                    "target_contract_sha256": contract_sha,
                    "feature_manifest_sha256": EXPECTED["FEATURE_MANIFEST_SHA256"],
                    "split_contract_sha256": EXPECTED["SPLIT_CONTRACT_SHA256"],
                })
        fold_scored = pd.concat(validation_parts, ignore_index=True)
        oof_parts.append(fold_scored)
        t1m = t1_metrics(fold_scored["T1_POSITIVE_NET20"], fold_scored["pred_t1"])
        t1a = t1_metrics(fold_scored["T1_POSITIVE_NET20"], fold_scored["t1_baseline_constant"])
        t1b = t1_metrics(fold_scored["T1_POSITIVE_NET20"], fold_scored["t1_baseline_majority"])
        t1rank = t1_ranking_metrics(fold_scored)
        t1_fold_rows.append({"fold": fold[0], "train_count": int(len(train_all)), "validation_count": int(len(fold_scored)),
                             "validation_positive_rate": float(fold_scored["T1_POSITIVE_NET20"].mean()),
                             **{f"model_{k}": v for k, v in t1m.items()},
                             **{f"constant_baseline_{k}": v for k, v in t1a.items()},
                             **{f"majority_baseline_{k}": v for k, v in t1b.items()},
                             **{f"Top{pct}_{key}": bucket_row(t1rank, pct)[key]
                                for pct in (20, 10, 5) for key in ("absolute_gain_vs_unconditional", "relative_lift_vs_unconditional", "actual_mean_net20")}})
        t2m = t2_metrics(fold_scored["T2_ROBUST_NET20"], fold_scored["pred_t2"], fold_scored["raw_net20"])
        t2mean = t2_metrics(fold_scored["T2_ROBUST_NET20"], fold_scored["t2_baseline_mean"], fold_scored["raw_net20"])
        t2median = t2_metrics(fold_scored["T2_ROBUST_NET20"], fold_scored["t2_baseline_median"], fold_scored["raw_net20"])
        t2rank = t2_ranking_metrics(fold_scored)
        t2_fold_rows.append({"fold": fold[0], "train_count": int(len(train_all)), "validation_count": int(len(fold_scored)),
                             "validation_raw_mean_net20": float(fold_scored["raw_net20"].mean()),
                             **{f"model_{k}": v for k, v in t2m.items()},
                             **{f"mean_baseline_{k}": v for k, v in t2mean.items()},
                             **{f"median_baseline_{k}": v for k, v in t2median.items()},
                             **{f"Top{pct}_mean_net20": bucket_row(t2rank, pct)["mean_raw_net20"] for pct in (20, 10, 5)},
                             **{f"Top{pct}_gain": bucket_row(t2rank, pct)["gain_vs_unconditional_validation_baseline"] for pct in (20, 10, 5)}})

    oof_path = scratch / "FAST3_R30A_OOF_PREDICTION_LEDGER.parquet"
    if postfit_resume:
        oof = pd.read_parquet(oof_path).sort_values(["decision_timestamp_utc", "candidate_id"], kind="mergesort").reset_index(drop=True)
        for fold in ECONOMIC_FOLDS:
            train_all, validation_all, fold_audit = construct_economic_fold(dataset, fold)
            fold_audits.append(fold_audit)
            fold_scored = oof.loc[oof["fold"].eq(fold[0])].copy()
            if len(fold_scored) != len(validation_all):
                raise R30AStop("STOP_POSTFIT_OOF_FOLD_CARDINALITY")
            t1m = t1_metrics(fold_scored["T1_POSITIVE_NET20"], fold_scored["pred_t1"])
            t1a = t1_metrics(fold_scored["T1_POSITIVE_NET20"], fold_scored["t1_baseline_constant"])
            t1b = t1_metrics(fold_scored["T1_POSITIVE_NET20"], fold_scored["t1_baseline_majority"])
            t1rank = t1_ranking_metrics(fold_scored)
            t1_fold_rows.append({"fold": fold[0], "train_count": int(len(train_all)), "validation_count": int(len(fold_scored)),
                                 "validation_positive_rate": float(fold_scored["T1_POSITIVE_NET20"].mean()),
                                 **{f"model_{k}": v for k, v in t1m.items()},
                                 **{f"constant_baseline_{k}": v for k, v in t1a.items()},
                                 **{f"majority_baseline_{k}": v for k, v in t1b.items()},
                                 **{f"Top{pct}_{key}": bucket_row(t1rank, pct)[key]
                                    for pct in (20, 10, 5) for key in ("absolute_gain_vs_unconditional", "relative_lift_vs_unconditional", "actual_mean_net20")}})
            t2m = t2_metrics(fold_scored["T2_ROBUST_NET20"], fold_scored["pred_t2"], fold_scored["raw_net20"])
            t2mean = t2_metrics(fold_scored["T2_ROBUST_NET20"], fold_scored["t2_baseline_mean"], fold_scored["raw_net20"])
            t2median = t2_metrics(fold_scored["T2_ROBUST_NET20"], fold_scored["t2_baseline_median"], fold_scored["raw_net20"])
            t2rank = t2_ranking_metrics(fold_scored)
            t2_fold_rows.append({"fold": fold[0], "train_count": int(len(train_all)), "validation_count": int(len(fold_scored)),
                                 "validation_raw_mean_net20": float(fold_scored["raw_net20"].mean()),
                                 **{f"model_{k}": v for k, v in t2m.items()},
                                 **{f"mean_baseline_{k}": v for k, v in t2mean.items()},
                                 **{f"median_baseline_{k}": v for k, v in t2median.items()},
                                 **{f"Top{pct}_mean_net20": bucket_row(t2rank, pct)["mean_raw_net20"] for pct in (20, 10, 5)},
                                 **{f"Top{pct}_gain": bucket_row(t2rank, pct)["gain_vs_unconditional_validation_baseline"] for pct in (20, 10, 5)}})
            for direction in ("UP", "DOWN"):
                train = train_all.loc[train_all["head"].eq(direction)].copy()
                for target_name in ("T1", "T2"):
                    model_path = scratch / "models" / f"{target_name}_{direction}_{fold[0]}.joblib"
                    model = joblib.load(model_path)
                    model_records.append({
                        "target": target_name, "direction": direction, "fold": fold[0],
                        "model_family": type(model).__name__, "parameters": model.get_params(deep=False),
                        "training_row_count": int(len(train)), "training_identity_sha256": training_identity_hash(train),
                        "model_path": str(model_path), "model_sha256": file_sha256(model_path),
                        "target_contract_sha256": contract_sha,
                        "feature_manifest_sha256": EXPECTED["FEATURE_MANIFEST_SHA256"],
                        "split_contract_sha256": EXPECTED["SPLIT_CONTRACT_SHA256"],
                    })
        fit_count = 20
        predict_count = 20
    else:
        guard_frozen_contract(contract_path, contract_sha)
        oof = pd.concat(oof_parts, ignore_index=True).sort_values(["decision_timestamp_utc", "candidate_id"], kind="mergesort").reset_index(drop=True)
        oof.to_parquet(oof_path, index=False)
    oof_sha = file_sha256(oof_path)

    t1_fold = pd.DataFrame(t1_fold_rows)
    t2_fold = pd.DataFrame(t2_fold_rows)
    t1_rank = t1_ranking_metrics(oof)
    t2_rank = t2_ranking_metrics(oof)
    t1_deciles = fixed_deciles(oof, "pred_t1", "ALL")
    t2_deciles = fixed_deciles(oof, "pred_t2", "ALL")
    t1_decile_pos_s = safe_spearman(t1_deciles["prediction_decile"], t1_deciles["actual_positive_rate"])
    t1_decile_mean_s = safe_spearman(t1_deciles["prediction_decile"], t1_deciles["actual_raw_net20_mean"])
    t2_decile_t_s = safe_spearman(t2_deciles["prediction_decile"], t2_deciles["actual_transformed_T2_mean"])
    t2_decile_raw_s = safe_spearman(t2_deciles["prediction_decile"], t2_deciles["actual_raw_net20_mean"])
    t1_model = t1_metrics(oof["T1_POSITIVE_NET20"], oof["pred_t1"])
    t1_base_a = t1_metrics(oof["T1_POSITIVE_NET20"], oof["t1_baseline_constant"])
    t1_base_b = t1_metrics(oof["T1_POSITIVE_NET20"], oof["t1_baseline_majority"])
    calibration = calibration_diagnostics(oof["T1_POSITIVE_NET20"], oof["pred_t1"])
    t2_model = t2_metrics(oof["T2_ROBUST_NET20"], oof["pred_t2"], oof["raw_net20"])
    t2_base_mean = t2_metrics(oof["T2_ROBUST_NET20"], oof["t2_baseline_mean"], oof["raw_net20"])
    t2_base_median = t2_metrics(oof["T2_ROBUST_NET20"], oof["t2_baseline_median"], oof["raw_net20"])
    t1_positive_folds = int((t1_fold["Top20_absolute_gain_vs_unconditional"] > 0).sum())
    t2_positive_folds = int((t2_fold["Top20_gain"] > 0).sum())
    validation_base_rate = float(oof["T1_POSITIVE_NET20"].mean())
    validation_raw_mean = float(oof["raw_net20"].mean())
    t1_gate = bool(t1_model["ROC_AUC"] > .5
                   and bucket_row(t1_rank, 20)["actual_positive_rate"] > validation_base_rate
                   and bucket_row(t1_rank, 10)["actual_positive_rate"] > validation_base_rate
                   and t1_positive_folds > len(ECONOMIC_FOLDS) / 2
                   and t1_decile_pos_s is not None and t1_decile_pos_s > 0)
    t2_gate = bool(t2_model["Spearman_vs_raw_net20"] is not None and t2_model["Spearman_vs_raw_net20"] > 0
                   and bucket_row(t2_rank, 20)["mean_raw_net20"] > validation_raw_mean
                   and bucket_row(t2_rank, 10)["mean_raw_net20"] > validation_raw_mean
                   and t2_positive_folds > len(ECONOMIC_FOLDS) / 2
                   and t2_decile_raw_s is not None and t2_decile_raw_s > 0)
    t1_strong = bool(t1_model["ROC_AUC"] >= .55 and bucket_row(t1_rank, 10)["relative_lift_vs_unconditional"] >= 1.10
                     and t1_positive_folds > len(ECONOMIC_FOLDS) / 2 and t1_decile_pos_s is not None and t1_decile_pos_s >= .50)
    t1_ranking_absent = bool(bucket_row(t1_rank, 20)["actual_positive_rate"] <= validation_base_rate
                             and bucket_row(t1_rank, 10)["actual_positive_rate"] <= validation_base_rate)
    t2_ranking_absent = bool(bucket_row(t2_rank, 20)["mean_raw_net20"] <= validation_raw_mean
                             and bucket_row(t2_rank, 10)["mean_raw_net20"] <= validation_raw_mean)
    if t1_gate and t2_gate:
        classification, decision = "A_T1_T2_COMPLEMENTARY_ECONOMIC_SIGNAL", "T1_T2_COMPLEMENTARY_ECONOMIC_SIGNAL"
        next_stage = "RECOMMEND_HUMAN_AUTHORIZATION_FOR_FROZEN_T1_T2_COMBINATION_RESEARCH_NOT_FINAL_CONFIRMATION"
    elif t1_gate:
        classification, decision = "B_T1_ONLY_ECONOMIC_SIGNAL", "T1_ONLY_ECONOMIC_SIGNAL"
        next_stage = "FREEZE_T1_ONLY; DO_NOT_FORCE_T2"
    elif t2_gate:
        classification, decision = "C_T2_ONLY_ECONOMIC_SIGNAL", "T2_ONLY_ECONOMIC_SIGNAL"
        next_stage = "FREEZE_T2_ONLY; DO_NOT_FORCE_T1"
    elif t1_model["ROC_AUC"] <= .5 and t1_ranking_absent and (t2_model["Spearman_vs_raw_net20"] or 0.0) <= 0 and t2_ranking_absent:
        classification, decision = "E_NO_ECONOMIC_PREDICTIVE_SIGNAL_WITH_CURRENT_FEATURES", "NO_ECONOMIC_PREDICTIVE_SIGNAL_WITH_CURRENT_FEATURES"
        next_stage = "STOP_CURRENT_FEATURES_AND_PREPARE_HUMAN_DECISION_ON_FACTOR_EXPANSION"
    else:
        classification, decision = "D_WEAK_OR_INCONCLUSIVE_ECONOMIC_SIGNAL", "WEAK_OR_INCONCLUSIVE_ECONOMIC_SIGNAL"
        next_stage = "STOP_WITHOUT_TUNING; HUMAN_REVIEW_BEFORE_FACTOR_EXPANSION"

    up_t1, up_t1_detail = direction_status(oof, "UP", "T1")
    down_t1, down_t1_detail = direction_status(oof, "DOWN", "T1")
    up_t2, up_t2_detail = direction_status(oof, "UP", "T2")
    down_t2, down_t2_detail = direction_status(oof, "DOWN", "T2")
    up_score = int(up_t1 == "GO") + int(up_t2 == "GO") + float(up_t1_detail.get("ROC_AUC") or 0) + float(up_t2_detail.get("Spearman_vs_raw_net20") or 0)
    down_score = int(down_t1 == "GO") + int(down_t2 == "GO") + float(down_t1_detail.get("ROC_AUC") or 0) + float(down_t2_detail.get("Spearman_vs_raw_net20") or 0)
    easier = "UP" if up_score > down_score else ("DOWN" if down_score > up_score else "NEITHER_CLEAR")
    by_year, by_direction, by_symbol = robustness_tables(oof)
    year_positive = int((by_year[["T1_Top20_mean_net20", "T2_Top20_mean_net20"]].max(axis=1) > 0).sum())
    symbol_positive = int((by_symbol[["T1_Top20_mean_net20", "T2_Top20_mean_net20"]].max(axis=1) > 0).sum())

    output_paths = {
        "FAST3_R30A_T1_FOLD_METRICS.csv": t1_fold,
        "FAST3_R30A_T2_FOLD_METRICS.csv": t2_fold,
        "FAST3_R30A_T1_RANKING_METRICS.csv": t1_rank,
        "FAST3_R30A_T2_RANKING_METRICS.csv": t2_rank,
        "FAST3_R30A_T1_DECILES.csv": t1_deciles,
        "FAST3_R30A_T2_DECILES.csv": t2_deciles,
        "FAST3_R30A_ROBUSTNESS_BY_YEAR.csv": by_year,
        "FAST3_R30A_ROBUSTNESS_BY_DIRECTION.csv": by_direction,
        "FAST3_R30A_ROBUSTNESS_BY_SYMBOL.csv": by_symbol,
    }
    for name, table in output_paths.items():
        table.to_csv(frozen / name, index=False, lineterminator="\n")

    summary: dict[str, Any] = {
        "FAST3_R30A_STATUS": "PASS",
        "FAST3_R30A_CLASSIFICATION": classification,
        "FAST3_R30A_DECISION": decision,
        "GENERATION": "R30", "STAGE": "R30A", "STUDY_NAME": "FROZEN_T1_T2_ECONOMIC_TARGET_BASELINE_TRAINING",
        "BRANCH": branch, "START_BRANCH": branch, "START_HEAD": start_head, "HEAD": head,
        "TARGET_CONTRACT_FROZEN": True, "TARGET_CONTRACT_SHA256": contract_sha,
        "FEATURE_MANIFEST_SHA256": EXPECTED["FEATURE_MANIFEST_SHA256"], "FEATURE_COUNT": len(FEATURES),
        "FEATURE_NAMES": list(FEATURES), "SPLIT_CONTRACT_SHA256": EXPECTED["SPLIT_CONTRACT_SHA256"],
        "FOLD_COUNT": len(ECONOMIC_FOLDS), "TARGET_ROW_COUNT": int(len(dataset)),
        "MODEL_FAMILY": ["HistGradientBoostingClassifier", "HistGradientBoostingRegressor"],
        "MODEL_FAMILY_COUNT": 2, "HYPERPARAMETER_SOURCE": str(R28_MODEL_IDENTITY),
        "HYPERPARAMETER_SEARCH_COUNT": 0, "SEEDS": [1729], "SEED_COUNT": 1,
        "MODEL_FIT_COUNT": fit_count, "MODEL_PREDICT_CALL_COUNT": predict_count,
        "FINAL_CONFIRMATION_DATA_USED": False,
        "T1_BASE_POSITIVE_RATE": EXPECTED["T1_RATE"], "T1_OOF_UNCONDITIONAL_POSITIVE_RATE": validation_base_rate,
        "T1_ROC_AUC": t1_model["ROC_AUC"], "T1_PR_AUC": t1_model["PR_AUC"],
        "T1_BRIER": t1_model["Brier"], "T1_LOGLOSS": t1_model["LogLoss"],
        "T1_CALIBRATION_INTERCEPT": calibration["calibration_intercept"],
        "T1_CALIBRATION_SLOPE": calibration["calibration_slope"], "T1_ECE": calibration["ECE_10"],
        **{f"T1_TOP{pct}_POSITIVE_RATE": bucket_row(t1_rank, pct)["actual_positive_rate"] for pct in TOP_BUCKETS},
        **{f"T1_TOP{pct}_LIFT": bucket_row(t1_rank, pct)["relative_lift_vs_unconditional"] for pct in TOP_BUCKETS},
        **{f"T1_TOP{pct}_REALIZED_MEAN_NET20": bucket_row(t1_rank, pct)["actual_mean_net20"] for pct in TOP_BUCKETS},
        "T1_DECILE_POSITIVE_RATE_SPEARMAN": t1_decile_pos_s,
        "T1_DECILE_MEAN_NET20_SPEARMAN": t1_decile_mean_s,
        "T1_POSITIVE_FOLD_COUNT": t1_positive_folds, "T1_NEGATIVE_FOLD_COUNT": len(ECONOMIC_FOLDS) - t1_positive_folds,
        "T1_DEVELOPMENT_GATE": "GO" if t1_gate else "NO_GO", "T1_STRONG_DEVELOPMENT_SIGNAL": t1_strong,
        "T1_NAIVE_BASELINE_A": t1_base_a, "T1_NAIVE_BASELINE_B": t1_base_b,
        "T2_BASE_RAW_MEAN_NET20": EXPECTED["RAW_MEAN"], "T2_OOF_UNCONDITIONAL_RAW_MEAN_NET20": validation_raw_mean,
        "T2_MAE": t2_model["MAE"], "T2_RMSE": t2_model["RMSE"],
        "T2_SPEARMAN_VS_TRANSFORMED_TARGET": t2_model["Spearman_vs_transformed"],
        "T2_SPEARMAN_VS_RAW_NET20": t2_model["Spearman_vs_raw_net20"],
        **{f"T2_TOP{pct}_REALIZED_MEAN_NET20": bucket_row(t2_rank, pct)["mean_raw_net20"] for pct in TOP_BUCKETS},
        "T2_DECILE_TRANSFORMED_TARGET_SPEARMAN": t2_decile_t_s,
        "T2_DECILE_RAW_NET20_SPEARMAN": t2_decile_raw_s,
        "T2_POSITIVE_FOLD_COUNT": t2_positive_folds, "T2_NEGATIVE_FOLD_COUNT": len(ECONOMIC_FOLDS) - t2_positive_folds,
        "T2_DEVELOPMENT_GATE": "GO" if t2_gate else "NO_GO",
        "T2_NAIVE_BASELINE_A_MEAN": t2_base_mean, "T2_NAIVE_BASELINE_B_MEDIAN": t2_base_median,
        "UP_T1_STATUS": up_t1, "DOWN_T1_STATUS": down_t1, "UP_T2_STATUS": up_t2, "DOWN_T2_STATUS": down_t2,
        "DIRECTION_DETAILS": {"UP_T1": up_t1_detail, "DOWN_T1": down_t1_detail, "UP_T2": up_t2_detail, "DOWN_T2": down_t2_detail},
        "ECONOMIC_PAYOFF_EASIER_DIRECTION": easier,
        "YEAR_ROBUSTNESS": f"{year_positive}_OF_{len(by_year)}_YEARS_HAVE_POSITIVE_MEAN_IN_AT_LEAST_ONE_FIXED_TOP20_HEAD",
        "SYMBOL_ROBUSTNESS": f"{symbol_positive}_OF_{len(by_symbol)}_SYMBOLS_HAVE_POSITIVE_MEAN_IN_AT_LEAST_ONE_FIXED_TOP20_HEAD",
        "CURRENT_FEATURES_ECONOMIC_INFORMATION_STATUS": ("LEARNABLE_ECONOMIC_INFORMATION" if (t1_gate or t2_gate) else
                                                         "WEAK_OR_INCONCLUSIVE_ECONOMIC_INFORMATION" if classification.startswith("D_") else
                                                         "NO_CONFIRMED_ECONOMIC_INFORMATION"),
        "PRIMARY_RESEARCH_INTERPRETATION": ("R28 target misalignment was material and the same features learn executable payoff." if (t1_gate or t2_gate)
                                            else "Changing only the target did not establish robust economic prediction; current features also lack confirmed economic predictive power."),
        "OFFICIAL_ADOPTION_ALLOWED": False, "LIVE_TRADING_ALLOWED": False,
        "R29_MODIFIED": False, "R29_ALLOWED_TO_RESUME": False, "NEXT_STAGE": next_stage,
        "FINAL_CONFIRMATION_RECOMMENDATION": ("ELIGIBLE_FOR_HUMAN_REVIEW_BUT_DO_NOT_OPEN_AUTOMATICALLY" if (t1_gate or t2_gate)
                                              else "DO_NOT_OPEN_FINAL_UNTOUCHED_CONFIRMATION"),
        "T1_PLAIN_ANSWER": "YES_DEVELOPMENT_SIGNAL" if t1_gate else "NO_CONFIRMED_DEVELOPMENT_SIGNAL",
        "T2_PLAIN_ANSWER": "YES_DEVELOPMENT_SIGNAL" if t2_gate else "NO_CONFIRMED_DEVELOPMENT_SIGNAL",
        "T1_POSITIVE_COHORT_ANSWER": "at least one fixed high-score cohort is positive" if (t1_rank["actual_mean_net20"] > 0).any() else "none is positive",
        "T1_FOLD_STABILITY_ANSWER": "majority-positive" if t1_positive_folds > len(ECONOMIC_FOLDS) / 2 else "not majority-positive",
        "T2_FOLD_STABILITY_ANSWER": "majority-positive" if t2_positive_folds > len(ECONOMIC_FOLDS) / 2 else "not majority-positive",
        "OOF_PREDICTION_LEDGER_PATH": str(oof_path), "OOF_PREDICTION_LEDGER_SHA256": oof_sha,
        "OOF_PREDICTION_LEDGER_ROW_COUNT": int(len(oof)), "MODEL_IDENTITIES": model_records,
        "FOLD_AUDITS": fold_audits,
        "FAST3_STORAGE_CONTRACT_R1_STATUS": "PASS", "SOURCE_ROOT": str(SOURCE_ROOT), "DATA_ROOT": str(DATA_ROOT),
        "RESULTS_ROOT": str(RESULTS_ROOT), "CACHE_ROOT": str(CACHE_ROOT), "DATA_ROOT_WRITE_COUNT": 0,
        "LOCAL_RESULTS_CREATED": False, "RESULT_FILES_WRITTEN_TO_GIT_REPO": False,
        "PRE_EXISTING_UNTRACKED_FILES_PRESERVED": True, "PRE_EXISTING_TRACKED_CHANGES_PRESERVED": True,
        "NEW_STORAGE_VIOLATION_COUNT": 0, "DESTRUCTIVE_GIT_COMMAND_USED": False, "BROAD_GIT_ADD_USED": False,
        "REPORT_PATH": str(frozen / "FAST3_R30A_REPORT.md"),
        "SUMMARY_JSON_PATH": str(frozen / "FAST3_R30A_SUMMARY.json"),
        "TARGET_CONTRACT_PATH": str(contract_path),
    }
    write_json(frozen / "FAST3_R30A_SUMMARY.json", summary)
    (frozen / "FAST3_R30A_REPORT.md").write_text(report_text(summary, t1_rank, t2_rank), encoding="utf-8")
    write_json(runtime / "FAST3_R30A_RUNTIME_SUMMARY.json", {
        "status": "PASS", "decision": decision, "frozen_path": str(frozen),
        "summary_sha256": file_sha256(frozen / "FAST3_R30A_SUMMARY.json"),
        "target_contract_sha256": contract_sha, "model_fit_count": fit_count,
        "model_predict_call_count": predict_count, "data_root_write_count": 0,
    })
    guard_frozen_contract(contract_path, contract_sha)
    print(json.dumps({key: summary[key] for key in (
        "FAST3_R30A_STATUS", "FAST3_R30A_CLASSIFICATION", "FAST3_R30A_DECISION",
        "T1_DEVELOPMENT_GATE", "T2_DEVELOPMENT_GATE", "REPORT_PATH", "SUMMARY_JSON_PATH",
    )}, indent=2))


if __name__ == "__main__":
    main()
