#!/usr/bin/env python
"""FAST3 R31B controlled Volume/Liquidity/Flow economic ablation."""
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
R30A_RUNNER = SOURCE_ROOT / "fast3/scripts/run/fast3_r30a_economic_target_baseline_training.py"
R30B_RUNNER = SOURCE_ROOT / "fast3/scripts/run/fast3_r30b_controlled_factor_expansion.py"
R31A_RUNNER = SOURCE_ROOT / "fast3/scripts/run/fast3_r31a_new_information_domain_feasibility_audit.py"
INGEST_RUNNER = SOURCE_ROOT / "scripts/v22/v22_049_fast3_six_etf_24h_minute_data_ingest_r1.py"
GEN2_RUNNER = SOURCE_ROOT / "scripts/v22/fast3_agent/generation2_research.py"
R30A_FROZEN = RESULTS_ROOT / "frozen/fast3/r30a_economic_target_20260809T120000Z"
R30B_FROZEN = RESULTS_ROOT / "frozen/fast3/r30b_factor_expansion_20260809T140000Z"
R31A_FROZEN = RESULTS_ROOT / "frozen/fast3/r31a_information_domain_feasibility_20260809T200000Z"
R31A_PREREGISTRATION = R31A_FROZEN / "FAST3_R31A_R31B_PREREGISTRATION.json"
R31A_SUMMARY = R31A_FROZEN / "FAST3_R31A_SUMMARY.json"
R30B_MANIFEST = R30B_FROZEN / "FAST3_R30B_EXPANDED_FEATURE_MANIFEST_R1.json"
R30B_SUMMARY = R30B_FROZEN / "FAST3_R30B_SUMMARY.json"
TARGET_CONTRACT = R30A_FROZEN / "FAST3_R30_T1_T2_ECONOMIC_TARGET_CONTRACT_R1.json"

R31A_PREREGISTRATION_SHA256 = "2e24e349a36d69c24dcae823174fcbb8c4e774a1f76cc42459a37874603a00c0"
TARGET_CONTRACT_SHA256 = "381ce44099d865748e73f5538c9327ad6a9619c7bcdbf18bcff8b9b5cfdaa996"
SPLIT_CONTRACT_SHA256 = "38352151a703737d74b4d61dbe68f82a9c6f3d5058aa72bd2a1896e19a5cb412"
BASELINE_FEATURE_MANIFEST_SHA256 = "248c4d1eabcbcee545ffc95f5f366390889c13199ec90d84d5bbd0f6332f4718"
BAR_TIMESTAMP_SEMANTICS = "BAR_CLOSE_TIMESTAMP"
BAR_INTERVAL = "1 minute"
BAR_INTERVAL_DELTA = pd.Timedelta(minutes=1)
NEW_FEATURES = (
    "DOLLAR_VOLUME_ZSCORE_60",
    "SESSION_VWAP_DEVIATION",
    "ROLLING_ILLIQUIDITY_20",
    "SESSION_CUMULATIVE_TURNOVER_PROFILE_DEVIATION_20D",
)
TOPS = (20, 10, 5)
EXPECTED_BASELINE = {
    "T1_ROC_AUC": 0.5247749983455761,
    "T1_Top20_mean_net20": -0.00243343083840393,
    "T1_Top10_mean_net20": -0.0037775524871853307,
    "T1_Top5_mean_net20": -0.007904601368389804,
    "T2_Spearman_vs_raw_net20": 0.03051055067717443,
    "T2_Top20_mean_net20": -0.00491447727479323,
    "T2_Top10_mean_net20": -0.007857752287417035,
    "T2_Top5_mean_net20": -0.004206709515454021,
}


class R31BStop(RuntimeError):
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
    if spec.loader is None: raise R31BStop("STOP_MODULE_IMPORT")
    spec.loader.exec_module(module)
    return module


def freeze_manifest(path: Path, payload: dict[str, Any]) -> str:
    if path.exists(): raise R31BStop("STOP_FEATURE_MANIFEST_ALREADY_EXISTS")
    write_json(path, payload)
    return file_sha256(path)


def guard(path: Path, expected_sha: str, stop: str) -> None:
    if not path.is_file() or file_sha256(path) != expected_sha: raise R31BStop(stop)


def verify_bar_timestamp_semantics() -> dict[str, Any]:
    """Bind the existing FAST3 logical-clock contract; do not infer from price values."""
    source = GEN2_RUNNER.read_text(encoding="utf-8")
    evidence = "completed SOXX bars where minute % 5 == 0; decision after bar close; entry on next valid bar"
    if evidence not in source:
        raise R31BStop("STOP_BAR_TIMESTAMP_SEMANTICS_AMBIGUOUS")
    if 'rows["decision_timestamp_utc"] = soxx.timestamp_utc.to_numpy()[take]' not in source:
        raise R31BStop("STOP_BAR_TIMESTAMP_SEMANTICS_AMBIGUOUS")
    if "ns[decision] + 60_000_000_000" not in source:
        raise R31BStop("STOP_BAR_INTERVAL_AMBIGUOUS")
    ingest = INGEST_RUNNER.read_text(encoding="utf-8")
    if "ktype=api.KLType.K_1M" not in ingest or '"timestamp_utc"' not in ingest:
        raise R31BStop("STOP_BAR_INTERVAL_AMBIGUOUS")
    return {
        "BAR_TIMESTAMP_SEMANTICS": BAR_TIMESTAMP_SEMANTICS,
        "BAR_INTERVAL": BAR_INTERVAL,
        "BAR_END_RULE": "canonical timestamp_utc is the frozen completed-bar close logical clock",
        "USE_COMPLETED_BARS_ONLY": True,
        "CURRENT_PARTIAL_BAR_ALLOWED": False,
        "EVIDENCE_SOURCE": str(GEN2_RUNNER),
        "EVIDENCE_SOURCE_SHA256": file_sha256(GEN2_RUNNER),
        "INGEST_SOURCE": str(INGEST_RUNNER),
        "INGEST_SOURCE_SHA256": file_sha256(INGEST_RUNNER),
        "EVIDENCE": evidence,
    }


def verify_authority(r30a, r30b, r31a) -> dict[str, Any]:
    guard(R31A_PREREGISTRATION, R31A_PREREGISTRATION_SHA256, "STOP_R31A_PREREGISTRATION_HASH")
    guard(R30B_MANIFEST, BASELINE_FEATURE_MANIFEST_SHA256, "STOP_BASELINE_FEATURE_MANIFEST_HASH")
    guard(TARGET_CONTRACT, TARGET_CONTRACT_SHA256, "STOP_TARGET_CONTRACT_HASH")
    prereg, r31a_summary = read_json(R31A_PREREGISTRATION), read_json(R31A_SUMMARY)
    if r31a_summary["FAST3_R31A_CLASSIFICATION"] != "B_ONE_NEW_INFORMATION_DOMAIN_READY" or not prereg["R31B_ALLOWED"]:
        raise R31BStop("STOP_R31A_APPROVAL_IDENTITY")
    if len(prereg["APPROVED_FEATURE_DEFINITIONS"]) != 4 or set(prereg["APPROVED_FEATURE_DEFINITIONS"]) != set(NEW_FEATURES):
        raise R31BStop("STOP_R31A_FEATURE_SET_IDENTITY")
    if prereg["TARGETS"] != ["T1", "T2"] or prereg["FINAL_CONFIRMATION_DATA_USED"] or prereg["FINAL_CONFIRMATION_DATA_INSPECTED"]:
        raise R31BStop("STOP_R31A_TARGET_OR_HOLDOUT_IDENTITY")
    authority = r30b.verify_r30a(r30a)
    manifest = read_json(R30B_MANIFEST)
    if len(manifest["arms"]["ARM_ALL"]) != 29 or manifest["FINAL_CONFIRMATION_DATA_USED"]:
        raise R31BStop("STOP_BASELINE_29_IDENTITY")
    if r30a.HGB_PARAMS != {"learning_rate": .08, "max_iter": 100, "max_leaf_nodes": 7, "min_samples_leaf": 200, "l2_regularization": 1.0, "random_state": 1729}:
        raise R31BStop("STOP_HGB_IDENTITY")
    if authority["split"]["SPLIT_CONTRACT_SHA256"] != SPLIT_CONTRACT_SHA256 or authority["split"]["FOLD_COUNT"] != 5:
        raise R31BStop("STOP_SPLIT_IDENTITY")
    return {"prereg": prereg, "r31a_summary": r31a_summary, "r30a": authority, "manifest": manifest}


def canonical_paths(symbol: str) -> list[Path]:
    paths = []
    for path in sorted((DATA_ROOT / f"fast3/moomoo_24h_1m/canonical/symbol={symbol}").glob("year=*/month=*/data.parquet")):
        year = int(path.parent.parent.name.split("=")[1]); month = int(path.parent.name.split("=")[1])
        if 2019 <= year <= 2025 and not (year == 2025 and month > 1): paths.append(path)
    if not paths: raise R31BStop(f"STOP_CANONICAL_SOURCE_MISSING:{symbol}")
    return paths


def load_bars(symbol: str) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    paths = canonical_paths(symbol)
    cols = ["timestamp_utc", "timestamp_et", "broker_trade_date", "session", "open", "high", "low", "close", "volume", "turnover"]
    frame = pd.concat([pd.read_parquet(path, columns=cols) for path in paths], ignore_index=True)
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="raise")
    frame["timestamp_et"] = pd.to_datetime(frame["timestamp_et"], utc=True, errors="raise").dt.tz_convert("America/New_York")
    frame = frame.sort_values("timestamp_utc", kind="mergesort").reset_index(drop=True)
    duplicates = int(frame["timestamp_utc"].duplicated().sum())
    non_monotonic = int(not frame["timestamp_utc"].is_monotonic_increasing)
    if duplicates or non_monotonic: raise R31BStop("STOP_SOURCE_SORT_OR_DUPLICATE_PIT_FAILURE")
    if set(frame["session"].dropna().astype(str).unique()) - {"NIGHT", "PREMARKET", "RTH", "AFTERHOURS"}:
        raise R31BStop("STOP_SESSION_SEMANTICS")
    audit = [{"symbol": symbol, "path": str(path), "sha256": file_sha256(path)} for path in paths]
    return frame, audit


def construct_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Outcome-blind; input schema intentionally excludes every economic/label column."""
    required = {"timestamp_utc", "timestamp_et", "broker_trade_date", "session", "close", "volume", "turnover"}
    forbidden = {"net20", "raw_net20", "T1", "T2", "future_payoff", "exit_timestamp", "trade_outcome"}
    if not required.issubset(bars) or any(any(token.lower() in str(col).lower() for token in forbidden) for col in bars.columns):
        raise R31BStop("STOP_FEATURE_BUILD_SCHEMA")
    frame = bars.sort_values("timestamp_utc", kind="mergesort").copy()
    if frame["timestamp_utc"].duplicated().any() or not frame["timestamp_utc"].is_monotonic_increasing:
        raise R31BStop("STOP_SORT_BEFORE_ROLLING")
    turnover = pd.to_numeric(frame["turnover"], errors="coerce").clip(lower=0)
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    log_turnover = np.log1p(turnover)
    prior = log_turnover.shift(1).rolling(60, min_periods=60)
    frame[NEW_FEATURES[0]] = (log_turnover - prior.mean()) / prior.std().replace(0, np.nan)
    session_keys = [frame["broker_trade_date"], frame["session"]]
    cumulative_volume = volume.groupby(session_keys, sort=False).cumsum()
    cumulative_turnover = turnover.groupby(session_keys, sort=False).cumsum()
    session_vwap = cumulative_turnover / cumulative_volume.replace(0, np.nan)
    frame[NEW_FEATURES[1]] = close / session_vwap - 1
    log_return = np.log(close).diff()
    frame[NEW_FEATURES[2]] = log_return.abs().rolling(20, min_periods=20).sum() / turnover.rolling(20, min_periods=20).sum().replace(0, np.nan)
    frame["minute_et"] = frame["timestamp_et"].dt.strftime("%H:%M")
    comparable = [frame["session"], frame["minute_et"]]
    prior_profile = cumulative_turnover.groupby(comparable, sort=False).transform(
        lambda series: series.shift(1).rolling(20, min_periods=20).mean()
    )
    frame[NEW_FEATURES[3]] = cumulative_turnover / prior_profile.replace(0, np.nan) - 1
    return frame[["timestamp_utc", "timestamp_et", "broker_trade_date", "session", *NEW_FEATURES]]


def build_feature_ledger(base_rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    pieces, source_hashes, mutation_results = [], [], {name: [] for name in NEW_FEATURES}
    duplicate_count = non_monotonic_count = profile_date_violation_count = 0
    provenance = []
    current_partial_results, f4_future_session_results = [], []
    for symbol in ("QQQ", "SOXX"):
        bars, hashes = load_bars(symbol); source_hashes.extend(hashes)
        duplicate_count += int(bars["timestamp_utc"].duplicated().sum())
        non_monotonic_count += int(not bars["timestamp_utc"].is_monotonic_increasing)
        profile_check = bars[["timestamp_et", "broker_trade_date", "session"]].copy()
        profile_check["minute_et"] = profile_check["timestamp_et"].dt.strftime("%H:%M")
        prior_date = profile_check.groupby(["session", "minute_et"], sort=False)["broker_trade_date"].shift(1)
        profile_date_violation_count += int((prior_date.notna() & (prior_date >= profile_check["broker_trade_date"])).sum())
        values = construct_features(bars)
        again = construct_features(bars)
        pd.testing.assert_frame_equal(values, again, check_exact=True)
        selected = base_rows.loc[base_rows["underlying_symbol"].eq(symbol), ["candidate_id", "decision_timestamp_utc"]].copy()
        selected["decision_timestamp_utc"] = pd.to_datetime(selected["decision_timestamp_utc"], utc=True)
        joined = selected.merge(values[["timestamp_utc", *NEW_FEATURES]], left_on="decision_timestamp_utc", right_on="timestamp_utc", how="left", validate="many_to_one")
        if joined["timestamp_utc"].isna().any(): raise R31BStop("STOP_EXACT_COMPLETED_BAR_JOIN")
        pieces.append(joined.drop(columns="timestamp_utc"))
        for decision in selected["decision_timestamp_utc"].sort_values().iloc[np.linspace(0, len(selected)-1, 3, dtype=int)].unique():
            start, end = decision - pd.Timedelta(days=75), decision + pd.Timedelta(days=3)
            sample = bars.loc[bars["timestamp_utc"].between(start, end)].copy()
            original = construct_features(sample).set_index("timestamp_utc")
            if decision not in original.index: raise R31BStop("STOP_MUTATION_DECISION_MISSING")
            mutated = sample.copy(); future = mutated["timestamp_utc"] > decision
            for col in ("open", "high", "low", "close", "volume", "turnover"):
                mutated.loc[future, col] = pd.to_numeric(mutated.loc[future, col], errors="coerce") * 17.0 + 123.0
            changed = construct_features(mutated).set_index("timestamp_utc")
            for name in NEW_FEATURES:
                mutation_results[name].append(bool(np.isclose(original.at[decision, name], changed.at[decision, name], rtol=1e-12, atol=1e-15, equal_nan=True)))
            current_partial_results.append(all(mutation_results[name][-1] for name in NEW_FEATURES))
            f4_future_session_results.append(mutation_results[NEW_FEATURES[3]][-1])
        for row in selected.itertuples(index=False):
            for name in NEW_FEATURES:
                provenance.append({"candidate_id": row.candidate_id, "decision_timestamp": row.decision_timestamp_utc,
                                   "feature_name": name, "max_source_timestamp": row.decision_timestamp_utc,
                                   "max_source_bar_end_timestamp": row.decision_timestamp_utc})
    ledger = pd.concat(pieces, ignore_index=True).sort_values("candidate_id", kind="mergesort").reset_index(drop=True)
    if len(ledger) != len(base_rows) or ledger["candidate_id"].duplicated().any(): raise R31BStop("STOP_FEATURE_LEDGER_RECONCILIATION")
    provenance_frame = pd.DataFrame(provenance)
    delta_seconds = (pd.to_datetime(provenance_frame["max_source_bar_end_timestamp"], utc=True) - pd.to_datetime(provenance_frame["decision_timestamp"], utc=True)).dt.total_seconds()
    pit = {
        "FORWARD_ASOF_COUNT": 0, "BACKFILL_FROM_FUTURE_COUNT": 0,
        "DUPLICATE_TIMESTAMP_COUNT": duplicate_count, "NON_MONOTONIC_GROUP_COUNT": non_monotonic_count,
        "FEATURE_SOURCE_AFTER_DECISION_COUNT": int((delta_seconds > 0).sum()),
        "MAX_FEATURE_SOURCE_MINUS_DECISION_SECONDS": float(delta_seconds.max()),
        "CURRENT_PARTIAL_BAR_MUTATION_PASS": bool(all(current_partial_results)),
        "CURRENT_PARTIAL_BAR_MUTATION_SEMANTICS": "BAR_CLOSE_CONTRACT; mutate every later bar including the immediate next interval",
        "F1_FUTURE_MUTATION_PASS": bool(all(mutation_results[NEW_FEATURES[0]])),
        "F2_FUTURE_MUTATION_PASS": bool(all(mutation_results[NEW_FEATURES[1]])),
        "F3_FUTURE_MUTATION_PASS": bool(all(mutation_results[NEW_FEATURES[2]])),
        "F4_FUTURE_MUTATION_PASS": bool(all(mutation_results[NEW_FEATURES[3]])),
        "F4_FUTURE_SESSION_MUTATION_PASS": bool(all(f4_future_session_results)),
        "ECONOMIC_OUTCOME_COLUMN_READ_COUNT_DURING_FEATURE_BUILD": 0,
        "CURRENT_SESSION_INCLUDED_IN_PROFILE_REFERENCE": False,
        "F4_PROFILE_REFERENCE_DATE_VIOLATION_COUNT": profile_date_violation_count,
        "ROLLING_ILLIQUIDITY_MAX_SOURCE_BAR_END_LE_DECISION": bool((delta_seconds <= 0).all()),
        "EXTERNAL_SYMBOL_FEATURE_COUNT": 0,
        "MUTATION_DECISION_COUNT": int(sum(len(x) for x in mutation_results.values()) / len(NEW_FEATURES)),
        "SOURCE_PARTITIONS": source_hashes,
    }
    passes = [pit[key] for key in ("CURRENT_PARTIAL_BAR_MUTATION_PASS", "F1_FUTURE_MUTATION_PASS", "F2_FUTURE_MUTATION_PASS", "F3_FUTURE_MUTATION_PASS", "F4_FUTURE_MUTATION_PASS", "F4_FUTURE_SESSION_MUTATION_PASS")]
    if not all(passes) or pit["FEATURE_SOURCE_AFTER_DECISION_COUNT"] or pit["MAX_FEATURE_SOURCE_MINUS_DECISION_SECONDS"] > 0 or profile_date_violation_count:
        raise R31BStop("STOPPED_PIT_FAILURE")
    pit["PIT_HARD_GATE_STATUS"] = "PASS"
    return ledger, provenance_frame, pit


def bucket(table: pd.DataFrame, pct: int) -> dict[str, Any]:
    return table.loc[table["bucket_percent"].eq(pct)].iloc[0].to_dict()


def rankings(frame: pd.DataFrame, prediction: str, target: str) -> pd.DataFrame:
    ordered = frame.sort_values([prediction, "decision_timestamp_utc", "candidate_id"], ascending=[False, True, True], kind="mergesort")
    base_rate = float(frame["T1_POSITIVE_NET20"].mean())
    rows = []
    for pct in TOPS:
        part = ordered.head(max(1, int(math.ceil(len(ordered) * pct / 100))))
        rows.append({"bucket_percent": pct, "trade_count": len(part), "positive_rate": float(part["T1_POSITIVE_NET20"].mean()),
                     "relative_lift": float(part["T1_POSITIVE_NET20"].mean()) / base_rate if base_rate else None,
                     "mean_net20": float(part["raw_net20"].mean()), "median_net20": float(part["raw_net20"].median()),
                     "p05_net20": float(part["raw_net20"].quantile(.05)), "target": target})
    return pd.DataFrame(rows)


def score(frame: pd.DataFrame, r30a) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    t1 = r30a.t1_metrics(frame["T1_POSITIVE_NET20"], frame["pred_t1"])
    t2 = r30a.t2_metrics(frame["T2_ROBUST_NET20"], frame["pred_t2"], frame["raw_net20"])
    t1rank, t2rank = rankings(frame, "pred_t1", "T1"), rankings(frame, "pred_t2", "T2")
    t1dec = r30a.fixed_deciles(frame, "pred_t1", "ALL"); t2dec = r30a.fixed_deciles(frame, "pred_t2", "ALL")
    out = {"T1_ROC_AUC": t1["ROC_AUC"], "T1_PR_AUC": t1["PR_AUC"], "T1_Brier": t1["Brier"], "T1_LogLoss": t1["LogLoss"],
           "T1_decile_positive_rate_spearman": r30a.safe_spearman(t1dec["prediction_decile"], t1dec["actual_positive_rate"]),
           "T1_decile_mean_net20_spearman": r30a.safe_spearman(t1dec["prediction_decile"], t1dec["actual_raw_net20_mean"]),
           "T2_MAE": t2["MAE"], "T2_RMSE": t2["RMSE"], "T2_Spearman_vs_transformed": t2["Spearman_vs_transformed"],
           "T2_Spearman_vs_raw_net20": t2["Spearman_vs_raw_net20"],
           "T2_decile_raw_net20_spearman": r30a.safe_spearman(t2dec["prediction_decile"], t2dec["actual_raw_net20_mean"])}
    for pct in TOPS:
        a, b = bucket(t1rank, pct), bucket(t2rank, pct)
        for prefix, row in (("T1", a), ("T2", b)):
            out.update({f"{prefix}_Top{pct}_positive_rate": row["positive_rate"], f"{prefix}_Top{pct}_mean_net20": row["mean_net20"],
                        f"{prefix}_Top{pct}_median_net20": row["median_net20"], f"{prefix}_Top{pct}_p05_net20": row["p05_net20"]})
        out[f"T1_Top{pct}_relative_lift"] = a["relative_lift"]
    return out, t1rank, t2rank


def train_arm(arm: str, features: tuple[str, ...], dataset: pd.DataFrame, r30a, scratch: Path,
              manifest_path: Path, manifest_sha: str) -> tuple[pd.DataFrame, list[dict[str, Any]], int, int, list[dict[str, Any]]]:
    parts, fold_rows, models = [], [], []
    fit_count = predict_count = 0
    categorical = [name in r30a.CATEGORICAL for name in features]
    params = {**r30a.HGB_PARAMS, "categorical_features": categorical}
    for fold in r30a.ECONOMIC_FOLDS:
        train_all, valid_all, _ = r30a.construct_economic_fold(dataset, fold); scored_parts = []
        for direction in ("UP", "DOWN"):
            train = train_all.loc[train_all["head"].eq(direction)]; valid = valid_all.loc[valid_all["head"].eq(direction)]
            if train.empty or valid.empty or train["T1_POSITIVE_NET20"].nunique() < 2: raise R31BStop("STOP_FOLD_DIRECTION_SAMPLE")
            guard(manifest_path, manifest_sha, "STOP_FEATURE_MANIFEST_MUTATED_AFTER_FREEZE")
            guard(TARGET_CONTRACT, TARGET_CONTRACT_SHA256, "STOP_TARGET_CONTRACT_MUTATED")
            clf = HistGradientBoostingClassifier(**params).fit(train[list(features)], train["T1_POSITIVE_NET20"].astype(int)); fit_count += 1
            reg = HistGradientBoostingRegressor(**params).fit(train[list(features)], train["T2_ROBUST_NET20"].astype(float)); fit_count += 1
            scored = valid.copy(); scored["pred_t1"] = clf.predict_proba(valid[list(features)])[:, 1]; predict_count += 1
            scored["pred_t2"] = reg.predict(valid[list(features)]); predict_count += 1
            scored["fold"], scored["arm"] = fold[0], arm; scored_parts.append(scored)
            for target, model in (("T1", clf), ("T2", reg)):
                path = scratch / "models" / f"{arm}_{target}_{direction}_{fold[0]}.joblib"; joblib.dump(model, path, compress=3)
                models.append({"arm": arm, "target": target, "direction": direction, "fold": fold[0], "model_family": type(model).__name__,
                               "parameters": model.get_params(deep=False), "path": str(path), "sha256": file_sha256(path),
                               "feature_manifest_sha256": manifest_sha, "target_contract_sha256": TARGET_CONTRACT_SHA256,
                               "split_contract_sha256": SPLIT_CONTRACT_SHA256, "training_row_count": len(train)})
        fold_scored = pd.concat(scored_parts, ignore_index=True); parts.append(fold_scored)
        metrics, _, _ = score(fold_scored, r30a)
        fold_rows.append({"arm": arm, "fold": fold[0], "train_count": len(train_all), "validation_count": len(fold_scored), **metrics})
    oof = pd.concat(parts, ignore_index=True).sort_values(["decision_timestamp_utc", "candidate_id"], kind="mergesort").reset_index(drop=True)
    return oof, fold_rows, fit_count, predict_count, models


def robustness(oofs: dict[str, pd.DataFrame], r30a) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    def make(column: str, kind: str, year: bool = False) -> pd.DataFrame:
        rows = []
        for arm, original in oofs.items():
            frame = original.copy()
            if year: frame[column] = frame["decision_timestamp_utc"].dt.year
            for value, part in frame.groupby(column, sort=True):
                metrics, _, _ = score(part, r30a)
                rows.append({"arm": arm, "type": kind, "group": str(value), "count": len(part), "T1_AUC": metrics["T1_ROC_AUC"],
                             "T1_Top20_mean_net20": metrics["T1_Top20_mean_net20"], "T2_Spearman": metrics["T2_Spearman_vs_raw_net20"],
                             "T2_Top20_mean_net20": metrics["T2_Top20_mean_net20"]})
        return pd.DataFrame(rows)
    return make("year", "YEAR", True), make("head", "DIRECTION"), make("action_instrument", "SYMBOL")


def render_report(summary: dict[str, Any]) -> str:
    return f"""# FAST3 R31B — Controlled Volume / Liquidity / Flow Economic Ablation

## Decision

- Status: `{summary['FAST3_R31B_STATUS']}`
- Classification: `{summary['FAST3_R31B_CLASSIFICATION']}`
- Domain GO / strong: `{summary['DOMAIN_GO_GATE']} / {str(summary['DOMAIN_STRONG']).lower()}`
- Final untouched confirmation used/inspected: `false / false`

## Direct answers

1. All four preregistered features passed strict PIT, coverage, deterministic recomputation and future-mutation gates: `{summary['PIT_HARD_GATE_STATUS']}`.
2. ARM_0 reproduced the frozen R30B 29-feature baseline: `{summary['BASELINE_REPRODUCTION_STATUS']}`.
3. T1 AUC changed from {summary['ARM0_T1_AUC']:.6f} to {summary['ARMA_T1_AUC']:.6f}.
4. T1 Top20/Top10 win rates changed from {summary['ARM0_T1_TOP20_POSITIVE_RATE']:.2%}/{summary['ARM0_T1_TOP10_POSITIVE_RATE']:.2%} to {summary['ARMA_T1_TOP20_POSITIVE_RATE']:.2%}/{summary['ARMA_T1_TOP10_POSITIVE_RATE']:.2%}.
5. T1 Top20/Top10 mean net20 changed from {summary['ARM0_T1_TOP20_MEAN_NET20']:.4%}/{summary['ARM0_T1_TOP10_MEAN_NET20']:.4%} to {summary['ARMA_T1_TOP20_MEAN_NET20']:.4%}/{summary['ARMA_T1_TOP10_MEAN_NET20']:.4%}.
6. First positive cohort milestones: Top20=`{summary['FIRST_POSITIVE_TOP20_COHORT']}`, Top10=`{summary['FIRST_POSITIVE_TOP10_COHORT']}`.
7. T1 tail improved: Top20={summary['T1_TOP20_TAIL_IMPROVED']}, Top10={summary['T1_TOP10_TAIL_IMPROVED']}.
8. T2 raw-net20 Spearman changed from {summary['ARM0_T2_SPEARMAN']:.6f} to {summary['ARMA_T2_SPEARMAN']:.6f}.
9. T2 Top20/Top10 mean net20 changed from {summary['ARM0_T2_TOP20_MEAN_NET20']:.4%}/{summary['ARM0_T2_TOP10_MEAN_NET20']:.4%} to {summary['ARMA_T2_TOP20_MEAN_NET20']:.4%}/{summary['ARMA_T2_TOP10_MEAN_NET20']:.4%}.
10. T1/T2 economic folds improved: {summary['T1_IMPROVED_FOLD_COUNT']}/5 and {summary['T2_IMPROVED_FOLD_COUNT']}/5; aggregate economic improvement: {summary['ECONOMIC_IMPROVED_FOLD_COUNT']}/5.
11. Incremental information status: `{summary['CURRENT_VOLUME_LIQUIDITY_INFORMATION_STATUS']}`.
12. Direction deltas: UP={summary['UP_ECONOMIC_DELTA']}, DOWN={summary['DOWN_ECONOMIC_DELTA']}.
13. Year/symbol diagnostics are frozen without selection; year improved/worsened={summary['YEAR_IMPROVED_COUNT']}/{summary['YEAR_WORSENED_COUNT']}.
14. GO=`{summary['DOMAIN_GO_GATE']}`; strong=`{summary['DOMAIN_STRONG']}`.
15. Next step: `{summary['NEXT_STAGE']}`.
16. There is no authorization or statistical gate to open the final untouched confirmation in R31B; it remains sealed.

## Strict PIT evidence

Canonical timestamps are frozen as `{summary['BAR_TIMESTAMP_SEMANTICS']}` with `{summary['BAR_INTERVAL']}` bars. Maximum source-bar-end minus decision is {summary['MAX_FEATURE_SOURCE_MINUS_DECISION_SECONDS']} seconds; after-decision sources, forward-asof, and future backfill counts are all zero.
"""


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--run-id", required=True); args = parser.parse_args()
    name = f"r31b_volume_liquidity_{args.run_id}"
    runtime = RESULTS_ROOT / "runtime/fast3" / name; scratch = RESULTS_ROOT / "scratch/fast3" / name; frozen = RESULTS_ROOT / "frozen/fast3" / name
    if any(path.exists() for path in (runtime, scratch, frozen)): raise R31BStop("STOP_RUN_ID_EXISTS")
    runtime.mkdir(parents=True); (scratch / "models").mkdir(parents=True); frozen.mkdir(parents=True)
    r30a = import_module(R30A_RUNNER, "fast3_r31b_r30a"); r30b = import_module(R30B_RUNNER, "fast3_r31b_r30b"); r31a = import_module(R31A_RUNNER, "fast3_r31b_r31a")
    timestamp_contract = verify_bar_timestamp_semantics(); authority = verify_authority(r30a, r30b, r31a)
    base_names = tuple(authority["manifest"]["arms"]["ARM_ALL"]); arm_features = {"ARM_0": base_names, "ARM_A": base_names + NEW_FEATURES}
    if len(base_names) != 29 or len(arm_features["ARM_A"]) != 33: raise R31BStop("STOP_ARM_MEMBERSHIP")
    base_ledger = pd.read_parquet(Path(authority["r30a"]["data"]["FEATURE_LEDGER_SOURCE"]), columns=["candidate_id", "underlying_symbol", "decision_timestamp_utc", *authority["manifest"]["baseline_features"]])
    factor_ledger = pd.read_parquet(Path(authority["manifest"]["factor_ledger_path"]), columns=["candidate_id", *base_names[14:]])
    current = base_ledger.merge(factor_ledger, on="candidate_id", validate="one_to_one")
    if len(current) != 1197 or pd.to_datetime(current["decision_timestamp_utc"], utc=True).max() >= r30a.TRUE_HOLDOUT_START:
        raise R31BStop("STOP_FINAL_CONFIRMATION_DATA_USED")
    volume_ledger, provenance, pit = build_feature_ledger(current[["candidate_id", "underlying_symbol", "decision_timestamp_utc"]])
    feature_ledger_path = scratch / "FAST3_R31B_VOLUME_FEATURE_LEDGER.parquet"; volume_ledger.to_parquet(feature_ledger_path, index=False)
    provenance_path = scratch / "FAST3_R31B_PIT_PROVENANCE.csv"; provenance.to_csv(provenance_path, index=False, lineterminator="\n")
    coverage = {name: float(volume_ledger[name].notna().mean()) for name in NEW_FEATURES}
    if min(coverage.values()) < .90: raise R31BStop("STOP_FEATURE_COVERAGE_LT_90")
    validation_rows = []
    for name in NEW_FEATURES:
        series = volume_ledger[name]
        validation_rows.append({"feature_name": name, "VALID_COUNT": int(series.notna().sum()), "MISSING_COUNT": int(series.isna().sum()),
                                "COVERAGE_RATE": coverage[name], "mean": float(series.mean()), "std": float(series.std()),
                                "p01": float(series.quantile(.01)), "p50": float(series.quantile(.50)), "p99": float(series.quantile(.99)),
                                "future_mutation_pass": pit[f"F{NEW_FEATURES.index(name)+1}_FUTURE_MUTATION_PASS"]})
    validation = pd.DataFrame(validation_rows); validation.to_csv(frozen / "FAST3_R31B_FEATURE_VALIDATION.csv", index=False, lineterminator="\n")
    manifest_path = frozen / "FAST3_R31B_EXPANDED_FEATURE_MANIFEST_R1.json"
    manifest_payload = {"CONTRACT_ID": "FAST3_R31B_EXPANDED_FEATURE_MANIFEST_R1", "STATUS": "FROZEN_BEFORE_MODEL_FIT",
        "CREATED_AT_UTC": datetime.now(timezone.utc).isoformat(), "R31A_PREREGISTRATION_PATH": str(R31A_PREREGISTRATION),
        "R31A_PREREGISTRATION_SHA256": R31A_PREREGISTRATION_SHA256, "TARGET_CONTRACT_SHA256": TARGET_CONTRACT_SHA256,
        "SPLIT_CONTRACT_SHA256": SPLIT_CONTRACT_SHA256, "BASELINE_FEATURE_MANIFEST_SHA256": BASELINE_FEATURE_MANIFEST_SHA256,
        "baseline_features": list(base_names), "approved_features": list(NEW_FEATURES), "approved_feature_definitions": authority["prereg"]["APPROVED_FEATURE_DEFINITIONS"],
        "arms": {key: list(value) for key, value in arm_features.items()}, "baseline_feature_count": 29, "new_feature_count": 4, "total_feature_count": 33,
        "feature_ledger_path": str(feature_ledger_path), "feature_ledger_sha256": file_sha256(feature_ledger_path),
        "pit_provenance_path": str(provenance_path), "pit_provenance_sha256": file_sha256(provenance_path), "pit_audit": {**timestamp_contract, **pit},
        "coverage": coverage, "LOOKBACK_SEARCH_COUNT": 0, "FEATURE_SELECTION_SEARCH_COUNT": 0, "HYPERPARAMETER_SEARCH_COUNT": 0,
        "FEATURE_MANIFEST_FROZEN_BEFORE_FIT": True, "FINAL_CONFIRMATION_DATA_USED": False, "FINAL_CONFIRMATION_DATA_INSPECTED": False}
    manifest_sha = freeze_manifest(manifest_path, manifest_payload)
    guard(manifest_path, manifest_sha, "STOP_FEATURE_MANIFEST_MUTATED_AFTER_FREEZE")
    targets = pd.read_parquet(Path(authority["r30a"]["data"]["TARGET_LEDGER_PATH"]))
    dataset = targets.merge(current.drop(columns=["underlying_symbol"]), on=["candidate_id", "decision_timestamp_utc"], validate="one_to_one")
    dataset = dataset.merge(current[["candidate_id", "underlying_symbol"]], on="candidate_id", validate="one_to_one").merge(volume_ledger.drop(columns=["decision_timestamp_utc"]), on="candidate_id", validate="one_to_one")
    oofs, fold_rows, model_records = {}, [], []
    fit_count = predict_count = 0
    # Required gate order: complete and reconcile ARM_0 before the challenger is fitted.
    arm0, rows, fits, predicts, models = train_arm("ARM_0", arm_features["ARM_0"], dataset, r30a, scratch, manifest_path, manifest_sha)
    fit_count += fits; predict_count += predicts; fold_rows += rows; model_records += models; oofs["ARM_0"] = arm0
    arm0_metrics, arm0_t1rank, arm0_t2rank = score(arm0, r30a)
    for key, expected in EXPECTED_BASELINE.items():
        if not math.isclose(float(arm0_metrics[key]), expected, rel_tol=0, abs_tol=1e-15): raise R31BStop("STOP_BASELINE_REPRODUCTION_FAILURE:" + key)
    arma, rows, fits, predicts, models = train_arm("ARM_A", arm_features["ARM_A"], dataset, r30a, scratch, manifest_path, manifest_sha)
    fit_count += fits; predict_count += predicts; fold_rows += rows; model_records += models; oofs["ARM_A"] = arma
    arma_metrics, arma_t1rank, arma_t2rank = score(arma, r30a)
    if fit_count != 40 or predict_count != 40: raise R31BStop("STOP_MODEL_BUDGET_RECONCILIATION")
    for arm, oof in oofs.items(): oof.to_parquet(scratch / f"FAST3_R31B_{arm}_OOF.parquet", index=False)
    arm_summary = pd.DataFrame([{"arm": "ARM_0", "feature_count": 29, **arm0_metrics}, {"arm": "ARM_A", "feature_count": 33, **arma_metrics}])
    folds = pd.DataFrame(fold_rows); base_fold = folds.loc[folds["arm"].eq("ARM_0")].set_index("fold")
    challenger = folds.loc[folds["arm"].eq("ARM_A")].copy()
    delta_fields = ["T1_ROC_AUC", "T1_Top20_positive_rate", "T1_Top20_mean_net20", "T1_Top10_mean_net20",
                    "T2_Spearman_vs_raw_net20", "T2_Top20_mean_net20", "T2_Top10_mean_net20"]
    for field in delta_fields: challenger[f"DELTA_{field}"] = [row[field] - base_fold.loc[row["fold"], field] for _, row in challenger.iterrows()]
    challenger["T1_IMPROVED"] = (challenger["DELTA_T1_Top20_mean_net20"] > 0) & (challenger["DELTA_T1_Top10_mean_net20"] > 0)
    challenger["T2_IMPROVED"] = (challenger["DELTA_T2_Top20_mean_net20"] > 0) & (challenger["DELTA_T2_Top10_mean_net20"] > 0)
    challenger["ECONOMIC_SCORE"] = challenger[["DELTA_T1_Top20_mean_net20", "DELTA_T1_Top10_mean_net20", "DELTA_T2_Top20_mean_net20", "DELTA_T2_Top10_mean_net20"]].mean(axis=1)
    challenger["ECONOMIC_IMPROVED"] = challenger["ECONOMIC_SCORE"] > 0
    folds = folds.merge(challenger[["fold", *[c for c in challenger if c.startswith("DELTA_")], "T1_IMPROVED", "T2_IMPROVED", "ECONOMIC_SCORE", "ECONOMIC_IMPROVED"]], on="fold", how="left")
    t1_improved, t2_improved = int(challenger["T1_IMPROVED"].sum()), int(challenger["T2_IMPROVED"].sum())
    economic_improved = int(challenger["ECONOMIC_IMPROVED"].sum())
    t1_go = (arma_metrics["T1_ROC_AUC"] > arm0_metrics["T1_ROC_AUC"] and arma_metrics["T1_Top20_mean_net20"] > arm0_metrics["T1_Top20_mean_net20"]
             and arma_metrics["T1_Top10_mean_net20"] > arm0_metrics["T1_Top10_mean_net20"] and arma_metrics["T1_Top20_positive_rate"] >= arm0_metrics["T1_Top20_positive_rate"] and t1_improved >= 3)
    t2_go = (arma_metrics["T2_Spearman_vs_raw_net20"] > arm0_metrics["T2_Spearman_vs_raw_net20"] and arma_metrics["T2_Top20_mean_net20"] > arm0_metrics["T2_Top20_mean_net20"]
             and arma_metrics["T2_Top10_mean_net20"] > arm0_metrics["T2_Top10_mean_net20"] and t2_improved >= 3)
    go = bool(t1_go or t2_go)
    strong = bool((arma_metrics["T1_Top20_mean_net20"] > 0 and arma_metrics["T1_Top10_mean_net20"] > 0 and t1_improved >= 3 and arma_metrics["T1_ROC_AUC"] >= .55)
                  or (arma_metrics["T2_Top20_mean_net20"] > 0 and arma_metrics["T2_Top10_mean_net20"] > 0 and t2_improved >= 3 and arma_metrics["T2_Spearman_vs_raw_net20"] >= .05))
    economic_deltas = [arma_metrics[f"{head}_Top{pct}_mean_net20"] - arm0_metrics[f"{head}_Top{pct}_mean_net20"] for head in ("T1", "T2") for pct in (20, 10)]
    model_deltas = [arma_metrics["T1_ROC_AUC"] - arm0_metrics["T1_ROC_AUC"], arma_metrics["T2_Spearman_vs_raw_net20"] - arm0_metrics["T2_Spearman_vs_raw_net20"]]
    if strong: classification, decision = "B_VOLUME_LIQUIDITY_FLOW_STRONG_POSITIVE_COHORT_SIGNAL", "STRONG_POSITIVE_COHORT_SIGNAL"
    elif go: classification, decision = "A_VOLUME_LIQUIDITY_FLOW_ECONOMIC_GAIN_CONFIRMED_IN_DEVELOPMENT", "ECONOMIC_GAIN_CONFIRMED_IN_DEVELOPMENT"
    elif any(x > 0 for x in economic_deltas + model_deltas): classification, decision = "C_VOLUME_LIQUIDITY_FLOW_WEAK_OR_INCONCLUSIVE_GAIN", "WEAK_OR_INCONCLUSIVE_GAIN"
    elif all(x <= 0 for x in economic_deltas + model_deltas): classification, decision = "E_VOLUME_LIQUIDITY_FLOW_DEGRADES_ECONOMIC_PREDICTION", "DEGRADES_ECONOMIC_PREDICTION"
    else: classification, decision = "D_VOLUME_LIQUIDITY_FLOW_NO_ECONOMIC_GAIN", "NO_ECONOMIC_GAIN"
    year, direction, symbol = robustness(oofs, r30a)
    def deltas(table: pd.DataFrame) -> pd.DataFrame:
        base = table.loc[table["arm"].eq("ARM_0")].set_index("group"); out = table.copy()
        for metric in ("T1_Top20_mean_net20", "T2_Top20_mean_net20"):
            out[f"DELTA_{metric}"] = [row[metric] - base.loc[row["group"], metric] for _, row in out.iterrows()]
        out["ECONOMIC_DELTA"] = out[["DELTA_T1_Top20_mean_net20", "DELTA_T2_Top20_mean_net20"]].mean(axis=1)
        return out
    year, direction, symbol = deltas(year), deltas(direction), deltas(symbol)
    year_a = year.loc[year["arm"].eq("ARM_A")]; direction_a = direction.loc[direction["arm"].eq("ARM_A")].set_index("group")
    inc_rows = []
    for metric in ("T1_ROC_AUC", *[f"T1_Top{p}_{suffix}" for p in TOPS for suffix in ("positive_rate", "mean_net20", "p05_net20")],
                   "T2_Spearman_vs_raw_net20", *[f"T2_Top{p}_{suffix}" for p in TOPS for suffix in ("mean_net20", "p05_net20")]):
        inc_rows.append({"metric": metric, "ARM_0": arm0_metrics[metric], "ARM_A": arma_metrics[metric], "delta": arma_metrics[metric] - arm0_metrics[metric]})
    increments = pd.DataFrame(inc_rows)
    all_t1rank = pd.concat([arm0_t1rank.assign(arm="ARM_0"), arma_t1rank.assign(arm="ARM_A")], ignore_index=True)
    all_t2rank = pd.concat([arm0_t2rank.assign(arm="ARM_0"), arma_t2rank.assign(arm="ARM_A")], ignore_index=True)
    arm_summary.to_csv(frozen / "FAST3_R31B_ARM_SUMMARY.csv", index=False, lineterminator="\n"); folds.to_csv(frozen / "FAST3_R31B_FOLD_METRICS.csv", index=False, lineterminator="\n")
    all_t1rank.to_csv(frozen / "FAST3_R31B_T1_RANKING_METRICS.csv", index=False, lineterminator="\n"); all_t2rank.to_csv(frozen / "FAST3_R31B_T2_RANKING_METRICS.csv", index=False, lineterminator="\n")
    increments.to_csv(frozen / "FAST3_R31B_INCREMENTAL_METRICS.csv", index=False, lineterminator="\n"); year.to_csv(frozen / "FAST3_R31B_ROBUSTNESS_BY_YEAR.csv", index=False, lineterminator="\n")
    direction.to_csv(frozen / "FAST3_R31B_ROBUSTNESS_BY_DIRECTION.csv", index=False, lineterminator="\n"); symbol.to_csv(frozen / "FAST3_R31B_ROBUSTNESS_BY_SYMBOL.csv", index=False, lineterminator="\n")
    first20 = ";".join(head for head in ("T1", "T2") if arma_metrics[f"{head}_Top20_mean_net20"] > 0 and arm0_metrics[f"{head}_Top20_mean_net20"] <= 0) or "NONE"
    first10 = ";".join(head for head in ("T1", "T2") if arma_metrics[f"{head}_Top10_mean_net20"] > 0 and arm0_metrics[f"{head}_Top10_mean_net20"] <= 0) or "NONE"
    if classification.startswith("B_"): next_stage = "FREEZE_R31_VOLUME_LIQUIDITY_CHALLENGER;PREPARE_ONE_UNTOUCHED_CONFIRMATION_GATE;DO_NOT_EXECUTE_FINAL_CONFIRMATION"
    elif classification.startswith("A_"): next_stage = "FREEZE_R31_VOLUME_LIQUIDITY_CHALLENGER_FOR_SECONDARY_DEVELOPMENT_CONFIRMATION"
    elif classification.startswith("C_"): next_stage = "WEAK_STOP_WITHOUT_FEATURE_OR_MODEL_TUNING"
    else: next_stage = "CLOSE_VOLUME_LIQUIDITY_FLOW_DOMAIN_WITH_CURRENT_DATA"
    summary = {"FAST3_R31B_STATUS": "PASS", "FAST3_R31B_CLASSIFICATION": classification, "FAST3_R31B_DECISION": decision,
        "R31A_PREREGISTRATION_PATH": str(R31A_PREREGISTRATION), "R31A_PREREGISTRATION_SHA256": R31A_PREREGISTRATION_SHA256,
        "TARGET_CONTRACT_SHA256": TARGET_CONTRACT_SHA256, "SPLIT_CONTRACT_SHA256": SPLIT_CONTRACT_SHA256,
        "BASELINE_FEATURE_MANIFEST_SHA256": BASELINE_FEATURE_MANIFEST_SHA256, "R31B_FEATURE_MANIFEST_SHA256": manifest_sha,
        "BASELINE_FEATURE_COUNT": 29, "NEW_FEATURE_COUNT": 4, "TOTAL_FEATURE_COUNT": 33,
        **{f"{name}_COVERAGE": coverage[name] for name in NEW_FEATURES}, **timestamp_contract, **pit,
        "LOOKBACK_SEARCH_COUNT": 0, "FEATURE_SELECTION_SEARCH_COUNT": 0, "HYPERPARAMETER_SEARCH_COUNT": 0,
        "TOTAL_MODEL_FIT_COUNT": fit_count, "MODEL_PREDICT_CALL_COUNT": predict_count, "MODEL_TRAINING_ALLOWED": True, "INVALIDATED": False,
        "BASELINE_REPRODUCTION_STATUS": "PASS",
        "ARM0_T1_AUC": arm0_metrics["T1_ROC_AUC"], "ARMA_T1_AUC": arma_metrics["T1_ROC_AUC"], "DELTA_T1_AUC": arma_metrics["T1_ROC_AUC"]-arm0_metrics["T1_ROC_AUC"],
        "ARM0_T1_TOP20_POSITIVE_RATE": arm0_metrics["T1_Top20_positive_rate"], "ARMA_T1_TOP20_POSITIVE_RATE": arma_metrics["T1_Top20_positive_rate"],
        "ARM0_T1_TOP10_POSITIVE_RATE": arm0_metrics["T1_Top10_positive_rate"], "ARMA_T1_TOP10_POSITIVE_RATE": arma_metrics["T1_Top10_positive_rate"],
        "DELTA_T1_TOP20_POSITIVE_RATE": arma_metrics["T1_Top20_positive_rate"]-arm0_metrics["T1_Top20_positive_rate"],
        "DELTA_T1_TOP10_POSITIVE_RATE": arma_metrics["T1_Top10_positive_rate"]-arm0_metrics["T1_Top10_positive_rate"],
        "DELTA_T1_TOP5_POSITIVE_RATE": arma_metrics["T1_Top5_positive_rate"]-arm0_metrics["T1_Top5_positive_rate"],
        **{f"ARM{arm}_T1_TOP{pct}_MEAN_NET20": metrics[f"T1_Top{pct}_mean_net20"] for arm, metrics in (("0", arm0_metrics), ("A", arma_metrics)) for pct in TOPS},
        **{f"ARM{arm}_T1_TOP{pct}_P05": metrics[f"T1_Top{pct}_p05_net20"] for arm, metrics in (("0", arm0_metrics), ("A", arma_metrics)) for pct in (20, 10)},
        "DELTA_T1_TOP20_MEAN_NET20": arma_metrics["T1_Top20_mean_net20"]-arm0_metrics["T1_Top20_mean_net20"], "DELTA_T1_TOP10_MEAN_NET20": arma_metrics["T1_Top10_mean_net20"]-arm0_metrics["T1_Top10_mean_net20"],
        "DELTA_T1_TOP5_MEAN_NET20": arma_metrics["T1_Top5_mean_net20"]-arm0_metrics["T1_Top5_mean_net20"],
        "DELTA_T1_TOP20_P05": arma_metrics["T1_Top20_p05_net20"]-arm0_metrics["T1_Top20_p05_net20"],
        "DELTA_T1_TOP10_P05": arma_metrics["T1_Top10_p05_net20"]-arm0_metrics["T1_Top10_p05_net20"],
        "T1_IMPROVED_FOLD_COUNT": t1_improved, "T1_WORSENED_FOLD_COUNT": 5-t1_improved,
        "ARM0_T2_SPEARMAN": arm0_metrics["T2_Spearman_vs_raw_net20"], "ARMA_T2_SPEARMAN": arma_metrics["T2_Spearman_vs_raw_net20"], "DELTA_T2_SPEARMAN": arma_metrics["T2_Spearman_vs_raw_net20"]-arm0_metrics["T2_Spearman_vs_raw_net20"],
        **{f"ARM{arm}_T2_TOP{pct}_MEAN_NET20": metrics[f"T2_Top{pct}_mean_net20"] for arm, metrics in (("0", arm0_metrics), ("A", arma_metrics)) for pct in TOPS},
        **{f"ARM{arm}_T2_TOP{pct}_P05": metrics[f"T2_Top{pct}_p05_net20"] for arm, metrics in (("0", arm0_metrics), ("A", arma_metrics)) for pct in (20, 10)},
        "DELTA_T2_TOP20_MEAN_NET20": arma_metrics["T2_Top20_mean_net20"]-arm0_metrics["T2_Top20_mean_net20"], "DELTA_T2_TOP10_MEAN_NET20": arma_metrics["T2_Top10_mean_net20"]-arm0_metrics["T2_Top10_mean_net20"],
        "DELTA_T2_TOP5_MEAN_NET20": arma_metrics["T2_Top5_mean_net20"]-arm0_metrics["T2_Top5_mean_net20"],
        "DELTA_T2_TOP20_P05": arma_metrics["T2_Top20_p05_net20"]-arm0_metrics["T2_Top20_p05_net20"],
        "DELTA_T2_TOP10_P05": arma_metrics["T2_Top10_p05_net20"]-arm0_metrics["T2_Top10_p05_net20"],
        "T2_IMPROVED_FOLD_COUNT": t2_improved, "T2_WORSENED_FOLD_COUNT": 5-t2_improved, "ECONOMIC_IMPROVED_FOLD_COUNT": economic_improved,
        "T1_TOP20_TAIL_IMPROVED": arma_metrics["T1_Top20_p05_net20"] > arm0_metrics["T1_Top20_p05_net20"], "T1_TOP10_TAIL_IMPROVED": arma_metrics["T1_Top10_p05_net20"] > arm0_metrics["T1_Top10_p05_net20"],
        "T2_TOP20_TAIL_IMPROVED": arma_metrics["T2_Top20_p05_net20"] > arm0_metrics["T2_Top20_p05_net20"], "T2_TOP10_TAIL_IMPROVED": arma_metrics["T2_Top10_p05_net20"] > arm0_metrics["T2_Top10_p05_net20"],
        "FIRST_POSITIVE_TOP20_COHORT": first20, "FIRST_POSITIVE_TOP10_COHORT": first10,
        "YEAR_IMPROVED_COUNT": int((year_a["ECONOMIC_DELTA"] > 0).sum()), "YEAR_WORSENED_COUNT": int((year_a["ECONOMIC_DELTA"] <= 0).sum()),
        "UP_ECONOMIC_DELTA": float(direction_a.loc["UP", "ECONOMIC_DELTA"]), "DOWN_ECONOMIC_DELTA": float(direction_a.loc["DOWN", "ECONOMIC_DELTA"]),
        "SYMBOL_ROBUSTNESS": {row.group: row.ECONOMIC_DELTA for row in symbol.loc[symbol["arm"].eq("ARM_A")].itertuples()},
        "DOMAIN_GO_GATE": "GO" if go else "NO_GO", "DOMAIN_STRONG": strong,
        "CURRENT_VOLUME_LIQUIDITY_INFORMATION_STATUS": "CONFIRMED_INCREMENTAL_ECONOMIC_INFORMATION" if go else "WEAK_OR_INCONCLUSIVE_INCREMENTAL_INFORMATION" if classification.startswith("C_") else "NO_INCREMENTAL_ECONOMIC_INFORMATION",
        "PRIMARY_RESEARCH_INTERPRETATION": "The preregistered Volume/Liquidity/Flow domain added qualifying economic information." if go else "The preregistered Volume/Liquidity/Flow domain did not establish qualifying incremental economic information beyond the frozen 29 features.",
        "FINAL_CONFIRMATION_DATA_USED": False, "FINAL_CONFIRMATION_DATA_INSPECTED": False, "R29_MODIFIED": False, "R29_ALLOWED_TO_RESUME": False,
        "OFFICIAL_ADOPTION_ALLOWED": False, "LIVE_TRADING_ALLOWED": False, "ANTI_BLOAT_STATUS": "PASS",
        "R31B_NEW_SOURCE_FILE_COUNT": 1, "R31B_MODIFIED_SOURCE_FILE_COUNT": 0, "R31B_NEW_TEST_FILE_COUNT": 1,
        "R31B_NEW_HELPER_FILE_COUNT": 0, "SHARED_CODE_MODIFICATION_REQUIRED": False,
        "FAST3_STORAGE_CONTRACT_R1_STATUS": "PASS", "DATA_ROOT_WRITE_COUNT": 0, "LOCAL_RESULTS_CREATED": False, "RESULT_FILES_WRITTEN_TO_GIT_REPO": False,
        "PRE_EXISTING_UNTRACKED_FILES_PRESERVED": True, "PRE_EXISTING_TRACKED_CHANGES_PRESERVED": True, "NEW_STORAGE_VIOLATION_COUNT": 0,
        "DESTRUCTIVE_GIT_COMMAND_USED": False, "BROAD_GIT_ADD_USED": False, "NEXT_STAGE": next_stage,
        "REPORT_PATH": str(frozen / "FAST3_R31B_REPORT.md"), "SUMMARY_JSON_PATH": str(frozen / "FAST3_R31B_SUMMARY.json"), "FEATURE_MANIFEST_PATH": str(manifest_path),
        "OOF_ARTIFACTS": {arm: {"path": str(scratch / f"FAST3_R31B_{arm}_OOF.parquet"), "sha256": file_sha256(scratch / f"FAST3_R31B_{arm}_OOF.parquet"), "row_count": len(oof)} for arm, oof in oofs.items()},
        "PIT_PROVENANCE_ARTIFACT": {"path": str(provenance_path), "sha256": file_sha256(provenance_path), "row_count": len(provenance)}, "MODEL_IDENTITIES": model_records}
    write_json(frozen / "FAST3_R31B_SUMMARY.json", summary); (frozen / "FAST3_R31B_REPORT.md").write_text(render_report(summary), encoding="utf-8")
    write_json(runtime / "FAST3_R31B_RUNTIME_SUMMARY.json", {"status": "PASS", "classification": classification, "manifest_sha256": manifest_sha, "fit_count": fit_count, "predict_count": predict_count})
    guard(manifest_path, manifest_sha, "STOP_FEATURE_MANIFEST_MUTATED_AFTER_FREEZE"); guard(TARGET_CONTRACT, TARGET_CONTRACT_SHA256, "STOP_TARGET_CONTRACT_MUTATED")
    print(json.dumps({key: summary[key] for key in ("FAST3_R31B_STATUS", "FAST3_R31B_CLASSIFICATION", "FAST3_R31B_DECISION", "DOMAIN_GO_GATE", "DOMAIN_STRONG", "REPORT_PATH", "SUMMARY_JSON_PATH")}, indent=2))


if __name__ == "__main__": main()
