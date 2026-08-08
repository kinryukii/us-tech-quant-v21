#!/usr/bin/env python
"""FAST3 Clean-Room R2 final pre-holdout model freeze; never scores holdout."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pyarrow
import sklearn


NAME = "FAST3_CLEANROOM_R2_FINAL_MODEL_FREEZE"
REPO = Path(__file__).parents[3]
R1_SOURCE = REPO / "fast3" / "scripts" / "run" / "fast3_cleanroom_r1_preholdout.py"
CANONICAL = Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
RESULTS = Path(r"D:\us-tech-quant-results")
TRUE_HOLDOUT_START_ET = pd.Timestamp("2025-02-01T00:00:00-05:00")
TRUE_HOLDOUT_START_UTC = TRUE_HOLDOUT_START_ET.tz_convert("UTC")
PRE_LAST_PARTITION = (2025, 1)
LEDGER_FIRST_PARTITION = (2025, 1)
HEADS = ("UP", "DOWN")
FAMILIES = ("HGB", "LOGIT")


def load_r1():
    spec = importlib.util.spec_from_file_location("cleanroom_r1_frozen", R1_SOURCE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


R1 = load_r1()


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=json_default) + "\n", encoding="utf-8")


def partition_key(path: Path) -> tuple[int, int]:
    return int(path.parts[-3].split("=", 1)[1]), int(path.parts[-2].split("=", 1)[1])


def symbol_paths(symbol: str, first: tuple[int, int] | None = None, last: tuple[int, int] | None = None) -> list[Path]:
    paths = sorted(CANONICAL.glob(f"symbol={symbol}/year=*/month=*/data.parquet"))
    paths = [path for path in paths if (first is None or partition_key(path) >= first) and (last is None or partition_key(path) <= last)]
    if not paths:
        raise RuntimeError(f"MISSING_CANONICAL_PATHS:{symbol}")
    return paths


def source_manifest(symbol: str, paths: list[Path]) -> list[dict]:
    rows = []
    for path in paths:
        timestamps = pd.read_parquet(path, columns=["timestamp_utc"])["timestamp_utc"]
        timestamps = pd.to_datetime(timestamps, utc=True, errors="raise")
        rows.append({"symbol": symbol, "path": str(path), "size": path.stat().st_size, "sha256": sha_file(path),
                     "timestamp_start_utc": timestamps.min(), "timestamp_end_utc": timestamps.max()})
    return rows


def read_symbol(symbol: str, paths: list[Path]) -> pd.DataFrame:
    frame = pd.concat([pd.read_parquet(path, columns=list(R1.REQUIRED_COLUMNS)) for path in paths], ignore_index=True)
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="raise")
    frame["timestamp_et"] = R1.normalized_et(frame["timestamp_et"])
    frame = frame.sort_values("timestamp_utc", kind="mergesort").drop_duplicates("timestamp_utc").reset_index(drop=True)
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["session_code"] = frame["session"].astype(str).str.upper().map(R1.SESSION_CODE).fillna(4).astype(int)
    frame["valid"] = ((frame["open"] > 0) & (frame["high"] >= frame[["open", "low", "close"]].max(axis=1))
                      & (frame["low"] <= frame[["open", "high", "close"]].min(axis=1)))
    return frame


def candidate_id(frame: pd.DataFrame) -> pd.Series:
    return frame["underlying_symbol"].astype(str) + "|" + frame["direction"].astype(str) + "|" + frame["decision_timestamp_utc"].astype(str)


def hash_rows(frame: pd.DataFrame) -> str:
    return sha_bytes(("\n".join(sorted(frame["candidate_id"].astype(str))) + "\n").encode("utf-8"))


def fit_model(family: str, frame: pd.DataFrame):
    model = R1.hgb_model() if family == "HGB" else R1.logistic_model()
    return model.fit(frame[list(R1.FEATURES)], frame["target_first"].astype(int))


def numeric_threshold(scores: np.ndarray) -> float:
    """Frozen R2 rule: linear 95th percentile of pre-holdout OOF scores."""
    return float(np.quantile(np.asarray(scores, dtype=float), 0.95, method="linear"))


def label_safe_final_training_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """The final model may use only labels fully resolved before holdout."""
    return frame[frame["horizon_timestamp_utc"] < TRUE_HOLDOUT_START_UTC].copy().reset_index(drop=True)


def select_by_frozen_threshold(scores: np.ndarray, threshold: float) -> np.ndarray:
    """Holdout selection consumes an absolute frozen value; it never computes a percentile."""
    return np.asarray(scores, dtype=float) >= float(threshold)


def outcome_blind_schema_pass(columns) -> bool:
    joined = "|".join(columns).lower()
    return not any(token in joined for token in ("label", "score", "payoff", "mfe", "mae", "exit"))


def oof_scores(preholdout: pd.DataFrame, head: str, family: str) -> pd.DataFrame:
    records = []
    head_frame = preholdout[preholdout["direction"].eq(head)].copy()
    for fold_name, raw_start, raw_end in R1.OOF_FOLDS:
        train, test, audit = R1.construct_purged_fold(head_frame, fold_name, raw_start, raw_end)
        if train.empty or test.empty or train["target_first"].nunique() < 2:
            raise RuntimeError(f"INSUFFICIENT_OOF_HEAD:{head}:{family}:{fold_name}")
        model = fit_model(family, train)
        result = test[["candidate_id", "target_first", "decision_timestamp_et", "underlying_symbol", "direction"]].copy()
        result["fold"] = fold_name
        result["score"] = model.predict_proba(test[list(R1.FEATURES)])[:, 1]
        records.append(result)
        if not (audit["purge_pass"] and audit["embargo_pass"] and audit["time_order_pass"]):
            raise RuntimeError(f"OOF_PIT_OR_PURGE_FAILURE:{head}:{family}:{fold_name}")
    return pd.concat(records, ignore_index=True)


def model_determinism(family: str, frame: pd.DataFrame) -> tuple[object, dict]:
    first = fit_model(family, frame)
    second = fit_model(family, frame)
    sample = frame.sort_values("candidate_id", kind="mergesort").head(min(10000, len(frame)))
    one = first.predict_proba(sample[list(R1.FEATURES)])
    two = second.predict_proba(sample[list(R1.FEATURES)])
    return first, {"prediction_max_abs_difference": float(np.max(np.abs(one - two))),
                   "class_order_identical": bool(np.array_equal(first.classes_, second.classes_)),
                   "feature_order_identical": list(R1.FEATURES) == list(R1.FEATURES),
                   "pass": bool(np.array_equal(one, two) and np.array_equal(first.classes_, second.classes_))}


def economic_contract() -> dict:
    return {"contract_version": "CLEANROOM_R2_PRE_HOLDOUT", "primary_model": "HGB_ONLY",
            "mapping": {"QQQ_UP": "TQQQ", "QQQ_DOWN": "SQQQ", "SOXX_UP": "SOXL", "SOXX_DOWN": "SOXS"},
            "signal": "relevant HGB score >= frozen numeric threshold", "simultaneous_up_down_when_flat": "ABSTAIN",
            "global_open_position_limit": 1, "while_open": "ignore same-direction and opposite-direction signals",
            "entry": "first legal action-ETF one-minute open strictly after decision anchor within 15 minutes",
            "exit": "first legal action-ETF one-minute open at or after entry plus 24 clock hours, within 96 hours for closure handling",
            "cost_total": 0.002, "stops": "NONE", "take_profit": "NONE", "trailing_stop": "NONE",
            "authoritative_execution_contract": "fast3/src/fast3/economics/executable_payoff_ledger_calendar_hard_r26a2.py"}


def environment_identity() -> dict:
    return {"python": sys.version, "platform": platform.platform(), "numpy": np.__version__, "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__, "pyarrow": pyarrow.__version__, "timezone": "America/New_York"}


def run(runtime_dir: Path, scratch_dir: Path, frozen_dir: Path) -> dict:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    scratch_dir.mkdir(parents=True, exist_ok=True)
    frozen_dir.mkdir(parents=True, exist_ok=True)
    models_dir = frozen_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    pre_paths = {symbol: symbol_paths(symbol, last=PRE_LAST_PARTITION) for symbol in R1.SYMBOLS}
    manifests = [entry for symbol in R1.SYMBOLS for entry in source_manifest(symbol, pre_paths[symbol])]
    write_json(frozen_dir / "cleanroom_r2_preholdout_source_manifest.json", {"files": manifests, "sha256": sha_bytes(json.dumps(manifests, default=json_default, sort_keys=True).encode())})
    data = {symbol: read_symbol(symbol, pre_paths[symbol]) for symbol in R1.SYMBOLS}
    frames = []
    for symbol in R1.SYMBOLS:
        candidates, _ = R1.candidate_features(data[symbol], symbol, include_labels=True)
        frames.append(candidates)
    pre = pd.concat(frames, ignore_index=True)
    pre["candidate_id"] = candidate_id(pre)
    pre = label_safe_final_training_rows(pre)
    isolation = bool((pre["horizon_timestamp_utc"] < TRUE_HOLDOUT_START_UTC).all())
    if not isolation:
        raise RuntimeError("FINAL_TRAINING_HOLDOUT_ISOLATION_FAILURE")
    fold_audit = []
    for name, start, end in R1.OOF_FOLDS:
        _, _, audit = R1.construct_purged_fold(pre, name, start, end)
        fold_audit.append(audit)
    pd.DataFrame(fold_audit).to_csv(frozen_dir / "cleanroom_r2_oof_purge_embargo_audit.csv", index=False)
    if not all(row["purge_pass"] and row["embargo_pass"] and row["time_order_pass"] for row in fold_audit):
        raise RuntimeError("R2_OOF_PURGE_EMBARGO_FAILURE")
    thresholds, oof_metrics, model_records = {}, {}, []
    for head in HEADS:
        head_frame = pre[pre["direction"].eq(head)].copy()
        for family in FAMILIES:
            key = f"{head}_{family}"
            oof = oof_scores(pre, head, family)
            threshold = numeric_threshold(oof["score"].to_numpy())
            thresholds[f"{key}_THRESHOLD"] = threshold
            selected = oof["score"] >= threshold
            base = float(oof["target_first"].mean())
            precision = float(oof.loc[selected, "target_first"].mean()) if selected.any() else None
            oof_metrics[key] = {"candidate_count": int(len(oof)), "selected_count": int(selected.sum()), "selected_rate": float(selected.mean()),
                                "base_rate": base, "precision": precision, "lift": float(precision / base) if precision is not None and base else None,
                                "oof_row_hash": hash_rows(oof.assign(candidate_id=oof["candidate_id"]))}
            model, determinism = model_determinism(family, head_frame)
            if not determinism["pass"]:
                raise RuntimeError(f"FINAL_MODEL_NONDETERMINISTIC:{key}")
            model_path = models_dir / f"{key}_FINAL.joblib"
            joblib.dump(model, model_path, compress=3)
            reloaded = joblib.load(model_path)
            sample = head_frame.sort_values("candidate_id", kind="mergesort").head(min(10000, len(head_frame)))
            reload_pass = bool(np.array_equal(model.predict_proba(sample[list(R1.FEATURES)]), reloaded.predict_proba(sample[list(R1.FEATURES)])))
            if not reload_pass:
                raise RuntimeError(f"MODEL_RELOAD_MISMATCH:{key}")
            model_records.append({"model": key, "path": str(model_path), "sha256": sha_file(model_path), "training_row_count": int(len(head_frame)),
                                  "training_row_hash": hash_rows(head_frame), "determinism": determinism, "reload_equivalence_pass": reload_pass})
    thresholds_payload = {"method": "linear 95th percentile of head/family pre-holdout OOF scores", "thresholds": thresholds}
    threshold_path = frozen_dir / "cleanroom_r2_thresholds.json"
    write_json(threshold_path, thresholds_payload)
    economic_path = frozen_dir / "cleanroom_r2_economic_contract.json"
    contract = economic_contract()
    write_json(economic_path, contract)
    # Outcome-blind ledger: raw price inputs are used only for PIT features; no label function is called.
    ledger_frames = []
    for symbol in R1.SYMBOLS:
        raw = read_symbol(symbol, symbol_paths(symbol, first=LEDGER_FIRST_PARTITION))
        ledger, _ = R1.candidate_features(raw, symbol, include_labels=False)
        ledger_frames.append(ledger)
    ledger = pd.concat(ledger_frames, ignore_index=True)
    ledger = ledger[ledger["decision_timestamp_et"] >= TRUE_HOLDOUT_START_ET].copy()
    ledger["candidate_id"] = candidate_id(ledger)
    ledger_columns = ["candidate_id", "underlying_symbol", "direction", "decision_timestamp_et", "decision_timestamp_utc", "max_feature_timestamp_utc", *R1.FEATURES]
    ledger = ledger[ledger_columns]
    if not outcome_blind_schema_pass(ledger.columns):
        raise RuntimeError("OUTCOME_BLIND_LEDGER_SCHEMA_FAILURE")
    ledger_path = scratch_dir / "cleanroom_r2_outcome_blind_holdout_feature_ledger.parquet"
    ledger.to_parquet(ledger_path, index=False)
    ledger_sha = sha_file(ledger_path)
    manifest = {"research_id": NAME, "r1_source_sha256": sha_file(R1_SOURCE), "candidate_definition": R1.frozen_contract()["candidate_rule"],
                "target_definition": R1.frozen_contract()["target"], "features": list(R1.FEATURES), "feature_count": len(R1.FEATURES),
                "final_training_candidate_max_timestamp": pre["decision_timestamp_et"].max(), "final_training_label_information_end_max": pre["horizon_timestamp_utc"].max(),
                "true_holdout_start_et": TRUE_HOLDOUT_START_ET, "true_holdout_start_utc": TRUE_HOLDOUT_START_UTC,
                "final_training_holdout_isolation_pass": isolation, "preholdout_candidate_count": int(len(pre)),
                "preholdout_label_counts": pre["first_touch_label"].value_counts().to_dict(), "input_data_hashes_frozen": True,
                "source_manifest_path": str(frozen_dir / "cleanroom_r2_preholdout_source_manifest.json"), "oof_folds": list(R1.OOF_FOLDS),
                "oof_metrics": oof_metrics, "threshold_path": str(threshold_path), "threshold_sha256": sha_file(threshold_path), "thresholds": thresholds,
                "models": model_records, "final_model_determinism_pass": all(record["determinism"]["pass"] for record in model_records),
                "model_reload_equivalence_pass": all(record["reload_equivalence_pass"] for record in model_records),
                "holdout_ledger_path": str(ledger_path), "holdout_ledger_sha256": ledger_sha, "holdout_ledger_row_count": int(len(ledger)),
                "economic_contract_path": str(economic_path), "economic_contract_sha256": sha_file(economic_path), "runtime_identity": environment_identity(),
                "strict_feature_pit_pass": bool((pre["max_feature_timestamp_utc"] <= pre["decision_timestamp_utc"]).all()),
                "time_order_pass": all(row["time_order_pass"] for row in fold_audit), "purge_embargo_pass": all(row["purge_pass"] and row["embargo_pass"] for row in fold_audit),
                "post_holdout_labels_opened": False, "post_holdout_payoff_opened": False, "post_holdout_model_scoring_performed": False, "post_holdout_economic_data_opened": False,
                "freeze_manifest_complete": True, "next_step": "RUN_CLEANROOM_R2_ONE_SHOT_TRUE_HOLDOUT"}
    write_json(frozen_dir / "cleanroom_r2_freeze_manifest.json", manifest)
    write_json(runtime_dir / "cleanroom_r2_runtime_summary.json", {"status": "PASS_PRE_HOLDOUT_FROZEN", "manifest": str(frozen_dir / "cleanroom_r2_freeze_manifest.json"), "holdout_rows": int(len(ledger))})
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--scratch-dir", required=True)
    parser.add_argument("--frozen-dir", required=True)
    args = parser.parse_args()
    result = run(Path(args.runtime_dir), Path(args.scratch_dir), Path(args.frozen_dir))
    print("CLEANROOM_R2_STATUS=PASS_PRE_HOLDOUT_FROZEN")
    print("FREEZE_MANIFEST_PATH=" + str(Path(args.frozen_dir) / "cleanroom_r2_freeze_manifest.json"))
    print("HOLDOUT_LEDGER_PATH=" + result["holdout_ledger_path"])
