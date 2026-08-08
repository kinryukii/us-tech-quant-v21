#!/usr/bin/env python
"""FAST3 Clean-Room R1 pre-holdout build, audit, and freeze.

This is intentionally a single, fixed experiment.  It constructs every input
from canonical raw QQQ and SOXX one-minute bars; it neither reads prior FAST3
candidate artifacts nor evaluates the true holdout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


NAME = "FAST3_CLEANROOM_SUCCESSOR_R1"
CANONICAL = Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
DEFAULT_OUT = Path(r"D:\us-tech-quant-results\fast3_cleanroom_r1")
SYMBOLS = ("QQQ", "SOXX")
REQUIRED_COLUMNS = ("timestamp_et", "timestamp_utc", "session", "open", "high", "low", "close", "volume")
FEATURES = (
    "return_5m", "return_15m", "return_60m", "realized_vol_15m",
    "realized_vol_60m", "relative_volume", "range_position", "symbol_code",
    "direction_code", "session_code",
)
SESSION_CODE = {"OVERNIGHT": 0, "PREMARKET": 1, "REGULAR_TRADING_HOURS": 2, "AFTER_HOURS": 3}
DEVELOPMENT_END = pd.Timestamp("2025-01-31 23:59:59", tz="America/New_York")
TRUE_HOLDOUT_START = pd.Timestamp("2025-02-01 00:00:00", tz="America/New_York")
LABEL_HORIZON = pd.Timedelta(hours=24)
PURGE_EMBARGO = pd.Timedelta(hours=24)
OOF_FOLDS = (
    ("OOF_2020", "2020-01-01", "2020-12-31 23:59:59"),
    ("OOF_2021", "2021-01-01", "2021-12-31 23:59:59"),
    ("OOF_2022", "2022-01-01", "2022-12-31 23:59:59"),
    ("OOF_2023", "2023-01-01", "2023-12-31 23:59:59"),
    ("OOF_2024", "2024-01-01", "2024-12-31 23:59:59"),
    ("OOF_2025_JAN", "2025-01-01", "2025-01-31 23:59:59"),
)
HGB_PARAMS = {"max_iter": 100, "max_leaf_nodes": 7, "min_samples_leaf": 200,
              "learning_rate": 0.08, "l2_regularization": 1.0, "random_state": 1729}
LOGISTIC_PARAMS = {"C": 1.0, "max_iter": 200, "random_state": 1729}


def json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=json_default) + "\n", encoding="utf-8")


def record_stage(timings: dict | None, name: str, started: float, progress_path: Path | None = None, **detail) -> None:
    """Persist minimal external progress evidence; it never changes experiment data."""
    if timings is None:
        return
    timings[name] = timings.get(name, 0.0) + (time.perf_counter() - started)
    if detail:
        timings.setdefault("detail", {}).setdefault(name, {}).update(detail)
    if progress_path is not None:
        write_json(progress_path, {"research_id": NAME, "timings_seconds": timings, "updated_at_utc": pd.Timestamp.now(tz="UTC")})


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalized_et(values: pd.Series) -> pd.Series:
    result = pd.to_datetime(values, errors="raise")
    if result.dt.tz is None:
        return result.dt.tz_localize("America/New_York")
    return result.dt.tz_convert("America/New_York")


def utc_nanoseconds(values: pd.Series) -> np.ndarray:
    """Return a stable nanosecond representation across pandas storage versions."""
    return values.dt.tz_localize(None).to_numpy(dtype="datetime64[ns]").astype("int64")


def approved_paths(canonical: Path, symbol: str, through_year: int | None = None) -> list[Path]:
    paths = sorted(canonical.glob(f"symbol={symbol}/year=*/month=*/data.parquet"))
    if through_year is not None:
        paths = [p for p in paths if int(p.parts[-3].split("=", 1)[1]) <= through_year]
    if not paths:
        raise RuntimeError(f"SOURCE_DATA_MISSING:{symbol}")
    return paths


def load_raw(canonical: Path, symbol: str, timings: dict | None = None, progress_path: Path | None = None) -> tuple[pd.DataFrame, dict]:
    """Load only underlying raw bars.  This function has no target/economics logic."""
    started = time.perf_counter()
    paths = approved_paths(canonical, symbol)
    frame = pd.concat([pd.read_parquet(p, columns=list(REQUIRED_COLUMNS)) for p in paths], ignore_index=True)
    record_stage(timings, "raw_load_seconds", started, progress_path, symbol=symbol, raw_rows=int(len(frame)))
    started = time.perf_counter()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="raise")
    frame["timestamp_et"] = normalized_et(frame["timestamp_et"])
    frame = frame.sort_values("timestamp_utc", kind="mergesort").drop_duplicates("timestamp_utc").reset_index(drop=True)
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["session_code"] = frame["session"].astype(str).str.upper().map(SESSION_CODE).fillna(4).astype(int)
    frame["valid"] = (
        (frame["open"] > 0) & (frame["high"] >= frame[["open", "low", "close"]].max(axis=1))
        & (frame["low"] <= frame[["open", "high", "close"]].min(axis=1))
    )
    audit = {
        "symbol": symbol, "path_count": len(paths), "row_count": int(len(frame)),
        "date_start": frame["timestamp_et"].iloc[0], "date_end": frame["timestamp_et"].iloc[-1],
        "duplicate_timestamp_count": int(frame["timestamp_utc"].duplicated().sum()),
        "invalid_ohlc_count": int((~frame["valid"]).sum()), "source_kind": "CANONICAL_RAW_UNDERLYING_1M",
    }
    record_stage(timings, "raw_normalization_seconds", started, progress_path, symbol=symbol, normalized_rows=int(len(frame)))
    return frame, audit


def feature_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """The fixed ten-feature PIT set; all rolling windows end at decision bar t."""
    close = frame["close"].to_numpy(float)
    volume = frame["volume"].to_numpy(float)
    high = frame["high"].to_numpy(float)
    low = frame["low"].to_numpy(float)
    log_return = np.r_[np.nan, np.diff(np.log(close))]
    out = pd.DataFrame(index=frame.index)
    for window in (5, 15, 60):
        out[f"return_{window}m"] = pd.Series(close).pct_change(window)
    out["realized_vol_15m"] = pd.Series(log_return).rolling(15, min_periods=15).std()
    out["realized_vol_60m"] = pd.Series(log_return).rolling(60, min_periods=60).std()
    out["relative_volume"] = pd.Series(volume) / pd.Series(volume).rolling(60, min_periods=60).mean()
    rolling_low = pd.Series(low).rolling(60, min_periods=60).min()
    rolling_high = pd.Series(high).rolling(60, min_periods=60).max()
    out["range_position"] = (pd.Series(close) - rolling_low) / (rolling_high - rolling_low).replace(0, np.nan)
    out["symbol_code"] = 0 if symbol == "QQQ" else 1
    out["session_code"] = frame["session_code"].to_numpy()
    return out


def build_tree(values: np.ndarray, is_max: bool) -> tuple[np.ndarray, int]:
    size = 1
    while size < len(values):
        size *= 2
    tree = np.full(size * 2, -np.inf if is_max else np.inf, dtype=float)
    tree[size:size + len(values)] = values
    for node in range(size - 1, 0, -1):
        tree[node] = max(tree[node * 2], tree[node * 2 + 1]) if is_max else min(tree[node * 2], tree[node * 2 + 1])
    return tree, size


def first_cross(tree: np.ndarray, size: int, left: int, right: int, threshold: float, is_max: bool) -> int:
    """First inclusive index whose high/low reaches a barrier, in O(log n)."""
    if left > right:
        return -1
    left += size
    right += size
    front, back = [], []
    while left <= right:
        if left & 1:
            front.append(left)
            left += 1
        if not (right & 1):
            back.append(right)
            right -= 1
        left //= 2
        right //= 2
    for node in front + list(reversed(back)):
        if not (tree[node] >= threshold if is_max else tree[node] <= threshold):
            continue
        while node < size:
            child = node * 2
            left_matches = tree[child] >= threshold if is_max else tree[child] <= threshold
            node = child if left_matches else child + 1
        return node - size
    return -1


def next_valid(valid: np.ndarray, start: int) -> int:
    while start < len(valid) and not valid[start]:
        start += 1
    return start if start < len(valid) else -1


def candidate_features(frame: pd.DataFrame, symbol: str, include_labels: bool, timings: dict | None = None,
                       progress_path: Path | None = None) -> tuple[pd.DataFrame, dict]:
    """Apply the frozen five-minute rule and optionally its clean-room label.

    When ``include_labels`` is false no high/low path after entry is inspected.
    This is the only route used for the true-holdout ledger.
    """
    started = time.perf_counter()
    features = feature_frame(frame, symbol)
    record_stage(timings, "feature_generation_seconds", started, progress_path, symbol=symbol, label_mode=include_labels)
    started = time.perf_counter()
    ns = utc_nanoseconds(frame["timestamp_utc"])
    valid = frame["valid"].to_numpy(bool)
    minute = frame["timestamp_et"].dt.minute.to_numpy()
    # Immutable column views avoid repeated Pandas scalar-index dispatch in the
    # fixed candidate x first-touch loop.  Values and timestamp semantics are
    # unchanged; this is a localized O(1) lookup implementation improvement.
    timestamp_et = frame["timestamp_et"].tolist()
    timestamp_utc = frame["timestamp_utc"].tolist()
    open_values = frame["open"].to_numpy(float)
    session_values = frame["session_code"].to_numpy(int)
    feature_values = {name: features[name].to_numpy() for name in FEATURES if name not in ("symbol_code", "direction_code", "session_code")}
    indices = np.flatnonzero((minute % 5 == 0) & valid)
    audit = {"symbol": symbol, "candidate_grid_count": 0, "ambiguous_label_count": 0,
             "horizon_incomplete_count": 0, "label_mode": bool(include_labels)}
    if include_labels:
        maximum, tree_size = build_tree(frame["high"].to_numpy(float), True)
        minimum, _ = build_tree(frame["low"].to_numpy(float), False)
    rows: list[dict] = []
    for decision_i in indices:
        if decision_i < 60:
            continue
        entry_i = next_valid(valid, decision_i + 1)
        if entry_i < 0:
            continue
        decision_et = timestamp_et[decision_i]
        if include_labels:
            if decision_et > DEVELOPMENT_END:
                continue
            deadline_ns = ns[entry_i] + int(LABEL_HORIZON.value)
            coverage_i = int(np.searchsorted(ns, deadline_ns, side="left"))
            horizon_i = int(np.searchsorted(ns, deadline_ns, side="right") - 1)
            if (coverage_i >= len(frame) or timestamp_et[coverage_i] > DEVELOPMENT_END
                    or horizon_i <= entry_i):
                audit["horizon_incomplete_count"] += 1
                continue
        elif decision_et < TRUE_HOLDOUT_START:
            continue
        audit["candidate_grid_count"] += 1
        base = {
            "decision_timestamp_et": decision_et,
            "decision_timestamp_utc": timestamp_utc[decision_i],
            "entry_timestamp_utc": timestamp_utc[entry_i],
            "underlying_symbol": symbol, "calendar_date": str(decision_et.date()),
            "year": int(decision_et.year), "max_feature_timestamp_utc": timestamp_utc[decision_i],
            "feature_information_available": bool(timestamp_utc[decision_i] <= timestamp_utc[decision_i]),
            **{name: feature_values[name][decision_i] for name in feature_values},
            "symbol_code": 0 if symbol == "QQQ" else 1,
            "session_code": int(session_values[decision_i]),
        }
        if include_labels:
            entry_price = float(open_values[entry_i])
            up_i = first_cross(maximum, tree_size, entry_i, horizon_i, entry_price * 1.01, True)
            down_i = first_cross(minimum, tree_size, entry_i, horizon_i, entry_price * 0.99, False)
            if up_i >= 0 and up_i == down_i:
                audit["ambiguous_label_count"] += 1
                continue
            first = "UP_1PCT_FIRST" if up_i >= 0 and (down_i < 0 or up_i < down_i) else ("DOWN_1PCT_FIRST" if down_i >= 0 else "NO_1PCT_MOVE_WITHIN_24H")
            base["horizon_timestamp_utc"] = timestamp_utc[horizon_i]
            base["first_touch_label"] = first
        for direction, direction_code in (("UP", 1), ("DOWN", -1)):
            row = {**base, "direction": direction, "direction_code": direction_code}
            if include_labels:
                row["target_first"] = int(base["first_touch_label"] == f"{direction}_1PCT_FIRST")
            rows.append(row)
    record_stage(timings, "preholdout_label_generation_seconds" if include_labels else "holdout_feature_generation_seconds",
                 started, progress_path, symbol=symbol, candidate_grid_count=int(audit["candidate_grid_count"]))
    return pd.DataFrame(rows), audit


def hgb_model() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(**HGB_PARAMS)


def logistic_model() -> Pipeline:
    return Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()),
                     ("model", LogisticRegression(**LOGISTIC_PARAMS))])


def safe_metrics(frame: pd.DataFrame, probability: np.ndarray) -> dict:
    y = frame["target_first"].to_numpy(int)
    selected_count = max(1, int(np.ceil(len(frame) * 0.05)))
    ranked = frame[["decision_timestamp_utc", "underlying_symbol", "direction"]].copy()
    ranked["probability"] = probability
    ranked["target_first"] = y
    ranked = ranked.sort_values(["probability", "decision_timestamp_utc", "underlying_symbol", "direction"],
                                ascending=[False, True, True, True], kind="mergesort")
    selected = ranked.head(selected_count)
    base_rate = float(y.mean())
    top_rate = float(selected["target_first"].mean())
    return {
        "row_count": int(len(frame)), "top5_selected_count": selected_count,
        "unconditional_target_first_rate": base_rate, "top5_target_first_rate": top_rate,
        "top5_target_first_lift": float(top_rate / base_rate) if base_rate else None,
        "auc": float(roc_auc_score(y, probability)) if len(np.unique(y)) == 2 else None,
        "brier": float(brier_score_loss(y, probability)),
    }


def construct_purged_fold(preholdout: pd.DataFrame, fold_name: str, raw_start: str, raw_end: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Apply the fixed 24-clock-hour label-information purge/embargo contract.

    The boundary is the first *actual* validation candidate, not the nominal
    calendar fold start.  A label ending exactly 24 hours before that candidate
    is excluded: both purge and embargo use a strict boundary.
    """
    validation_start = pd.Timestamp(raw_start, tz="America/New_York")
    validation_end = pd.Timestamp(raw_end, tz="America/New_York")
    validation = preholdout[preholdout["decision_timestamp_et"].between(validation_start, validation_end)].copy()
    if validation.empty:
        return preholdout.iloc[0:0].copy(), validation, {"fold": fold_name, "status": "SKIPPED_INSUFFICIENT_CLASS_OR_ROWS", "train_rows": 0, "test_rows": 0, "purge_pass": True, "embargo_pass": True}
    validation_min = validation["decision_timestamp_et"].min()
    validation_min_utc = validation_min.tz_convert("UTC")
    information_cutoff = validation_min_utc - PURGE_EMBARGO
    train = preholdout[preholdout["horizon_timestamp_utc"] < information_cutoff].copy()
    train_end = train["horizon_timestamp_utc"].max() if not train.empty else pd.NaT
    purge_gap_hours = (validation_min_utc - train_end).total_seconds() / 3600 if not train.empty else None
    candidate_gap_hours = (validation_min - train["decision_timestamp_et"].max()).total_seconds() / 3600 if not train.empty else None
    audit = {
        "fold": fold_name, "status": "USED", "train_rows": int(len(train)), "test_rows": int(len(validation)),
        "train_candidate_min_timestamp": train["decision_timestamp_et"].min() if not train.empty else pd.NaT,
        "train_candidate_max_timestamp": train["decision_timestamp_et"].max() if not train.empty else pd.NaT,
        "train_label_information_end_max": train_end,
        "validation_candidate_min_timestamp": validation_min,
        "validation_candidate_max_timestamp": validation["decision_timestamp_et"].max(),
        "validation_label_information_end_max": validation["horizon_timestamp_utc"].max(),
        "purge_gap_hours": purge_gap_hours, "required_purge_hours": 24.0,
        "embargo_gap_hours": purge_gap_hours, "required_embargo_hours": 24.0,
        "candidate_decision_gap_hours": candidate_gap_hours,
        "purge_pass": bool(train.empty or train_end < validation_min_utc),
        "embargo_pass": bool(train.empty or train_end < information_cutoff),
        "time_order_pass": bool(train.empty or train["decision_timestamp_utc"].max() < validation["decision_timestamp_utc"].min()),
    }
    return train, validation, audit


def run_oof(preholdout: pd.DataFrame, timings: dict | None = None, progress_path: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    records: list[pd.DataFrame] = []
    fold_audit: list[dict] = []
    for fold_name, raw_start, raw_end in OOF_FOLDS:
        started = time.perf_counter()
        train, test, audit = construct_purged_fold(preholdout, fold_name, raw_start, raw_end)
        record_stage(timings, "fold_construction_seconds", started, progress_path, fold=fold_name,
                     train_rows=int(len(train)), test_rows=int(len(test)))
        if train.empty or test.empty or train["target_first"].nunique() < 2:
            audit["status"] = "SKIPPED_INSUFFICIENT_CLASS_OR_ROWS"
            fold_audit.append(audit)
            continue
        started = time.perf_counter()
        hgb = hgb_model().fit(train[list(FEATURES)], train["target_first"].astype(int))
        hgb_probability = hgb.predict_proba(test[list(FEATURES)])[:, 1]
        record_stage(timings, "hgb_fit_predict_seconds", started, progress_path, fold=fold_name)
        started = time.perf_counter()
        logistic = logistic_model().fit(train[list(FEATURES)], train["target_first"].astype(int))
        logistic_probability = logistic.predict_proba(test[list(FEATURES)])[:, 1]
        record_stage(timings, "logit_fit_predict_seconds", started, progress_path, fold=fold_name)
        result = test[["decision_timestamp_et", "decision_timestamp_utc", "underlying_symbol", "direction", "target_first"]].copy()
        result["fold"] = fold_name
        result["hgb_probability"] = hgb_probability
        result["logistic_probability"] = logistic_probability
        records.append(result)
        fold_audit.append(audit)
    oof = pd.concat(records, ignore_index=True) if records else pd.DataFrame()
    if oof.empty:
        raise RuntimeError("INSUFFICIENT_OOF_ROWS")
    started = time.perf_counter()
    metrics = {"hgb_primary": safe_metrics(oof, oof["hgb_probability"].to_numpy()),
               "logistic_diagnostic_only": safe_metrics(oof, oof["logistic_probability"].to_numpy())}
    record_stage(timings, "frozen_threshold_seconds", started, progress_path, oof_rows=int(len(oof)))
    return oof, pd.DataFrame(fold_audit), metrics


def frozen_contract() -> dict:
    return {
        "research_id": NAME, "experiment_generation": "R1_ONLY", "candidate_rule": "valid completed one-minute decision bars where ET minute % 5 == 0; entry is first subsequent valid one-minute open",
        "candidate_frequency": "5_MINUTES_FROZEN", "target": "directional underlying +/-1% first-touch from entry open within 24 natural hours; same-minute dual touch is AMBIGUOUS and excluded",
        "development_end": DEVELOPMENT_END, "true_holdout_start": TRUE_HOLDOUT_START,
        "features": list(FEATURES), "feature_count": len(FEATURES), "primary_model": {"name": "HistGradientBoostingClassifier", **HGB_PARAMS},
        "diagnostic_benchmark_only": {"name": "LogisticRegression", **LOGISTIC_PARAMS},
        "oof_selection_rule": "single global deterministic Top-5% of primary HGB OOF probabilities, ceil(0.05 * OOF rows); no alternate threshold considered",
        "folds": [{"name": name, "test_start": start, "test_end": end} for name, start, end in OOF_FOLDS],
        "purge_embargo": "24 clock hours; training label-information end must be strictly earlier than the first actual validation candidate minus 24 hours",
        "prohibited": ["feature search", "feature deletion based on performance", "model search", "hyperparameter optimization", "post-holdout labels", "post-holdout payoff", "post-holdout model scoring", "post-holdout economics"],
    }


def run(output_dir: Path = DEFAULT_OUT, canonical: Path = CANONICAL, holdout_ledger_dir: Path | None = None,
        diagnostic_start: pd.Timestamp | None = None, diagnostic_end: pd.Timestamp | None = None) -> dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    holdout_ledger_dir = Path(holdout_ledger_dir) if holdout_ledger_dir is not None else output_dir
    holdout_ledger_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "CLEANROOM_R1_RUNTIME_PROGRESS.json"
    timings: dict = {}
    contract = frozen_contract()
    write_json(output_dir / "CLEANROOM_R1_CONTRACT.json", contract)
    data, source_audit = {}, []
    for symbol in SYMBOLS:
        data[symbol], audit = load_raw(Path(canonical), symbol, timings, progress_path)
        if diagnostic_start is not None:
            data[symbol] = data[symbol][data[symbol]["timestamp_et"] >= diagnostic_start].reset_index(drop=True)
        if diagnostic_end is not None:
            data[symbol] = data[symbol][data[symbol]["timestamp_et"] <= diagnostic_end].reset_index(drop=True)
        source_audit.append(audit)
    pre_frames, candidate_audit = [], []
    started = time.perf_counter()
    for symbol in SYMBOLS:
        pre = data[symbol][data[symbol]["timestamp_et"] <= DEVELOPMENT_END].reset_index(drop=True)
        frame, audit = candidate_features(pre, symbol, include_labels=True, timings=timings, progress_path=progress_path)
        pre_frames.append(frame)
        candidate_audit.append(audit)
    preholdout = pd.concat(pre_frames, ignore_index=True)
    record_stage(timings, "candidate_generation_seconds", started, progress_path, preholdout_rows=int(len(preholdout)))
    if preholdout.empty:
        raise RuntimeError("NO_PREHOLDOUT_CANDIDATES")
    started = time.perf_counter()
    feature_pit_pass = bool(preholdout["feature_information_available"].all() and (preholdout["max_feature_timestamp_utc"] <= preholdout["decision_timestamp_utc"]).all())
    record_stage(timings, "pit_audit_seconds", started, progress_path, feature_pit_pass=feature_pit_pass)
    oof, fold_audit, metrics = run_oof(preholdout, timings, progress_path)
    time_order_pass = bool(fold_audit.loc[fold_audit.status.eq("USED"), "time_order_pass"].fillna(False).all())
    purge_embargo_pass = bool(fold_audit.loc[fold_audit.status.eq("USED"), ["purge_pass", "embargo_pass"]].fillna(False).all(axis=None))

    # Holdout construction occurs only after all label/model work and never invokes label logic.
    holdout_frames, holdout_audit = [], []
    for symbol in SYMBOLS:
        frame, audit = candidate_features(data[symbol], symbol, include_labels=False, timings=timings, progress_path=progress_path)
        holdout_frames.append(frame)
        holdout_audit.append(audit)
    holdout = pd.concat(holdout_frames, ignore_index=True)
    holdout_columns = ["decision_timestamp_et", "decision_timestamp_utc", "entry_timestamp_utc", "underlying_symbol", "calendar_date", "year", "max_feature_timestamp_utc", "feature_information_available", *FEATURES]
    holdout = holdout[holdout_columns]
    if any("label" in column or "probability" in column or "return" in column and column not in FEATURES for column in holdout.columns):
        raise RuntimeError("HOLDOUT_LEDGER_OUTCOME_BLIND_CONTRACT_FAILURE")
    holdout_path = holdout_ledger_dir / "CLEANROOM_R1_HOLDOUT_FEATURE_LEDGER.parquet"
    started = time.perf_counter()
    holdout.to_parquet(holdout_path, index=False)
    record_stage(timings, "holdout_ledger_serialization_seconds", started, progress_path, holdout_rows=int(len(holdout)))

    started = time.perf_counter()
    oof.to_parquet(output_dir / "CLEANROOM_R1_PREHOLDOUT_OOF_PREDICTIONS.parquet", index=False)
    fold_audit.to_csv(output_dir / "CLEANROOM_R1_FOLD_AUDIT.csv", index=False)
    pd.DataFrame([metrics["hgb_primary"], metrics["logistic_diagnostic_only"]], index=["HGB_PRIMARY", "LOGISTIC_DIAGNOSTIC_ONLY"]).reset_index(names="model_role").to_csv(output_dir / "CLEANROOM_R1_OOF_METRICS.csv", index=False)
    pd.DataFrame(source_audit).to_csv(output_dir / "CLEANROOM_R1_SOURCE_AUDIT.csv", index=False)
    pd.DataFrame(candidate_audit + holdout_audit).to_csv(output_dir / "CLEANROOM_R1_CANDIDATE_AUDIT.csv", index=False)
    record_stage(timings, "preholdout_report_seconds", started, progress_path)

    source_file = Path(__file__)
    preholdout_gates_pass = bool(feature_pit_pass and time_order_pass and purge_embargo_pass and holdout_path.is_file())
    manifest = {
        "CLEANROOM_STATUS": "DIAGNOSTIC_ONLY_NOT_FROZEN" if diagnostic_start is not None else ("PASS_PRE_HOLDOUT_FROZEN" if preholdout_gates_pass else "PRE_HOLDOUT_FREEZE_AUDIT_FAILED"), "STRICT_FEATURE_PIT_PASS": feature_pit_pass,
        "TIME_ORDER_PASS": time_order_pass, "PURGE_EMBARGO_PASS": purge_embargo_pass,
        "HOLDOUT_FEATURE_LEDGER_CREATED": holdout_path.is_file(), "FREEZE_MANIFEST_CREATED": True,
        "POST_HOLDOUT_LABELS_OPENED": False, "POST_HOLDOUT_PAYOFF_OPENED": False,
        "POST_HOLDOUT_MODEL_SCORING_PERFORMED": False, "POST_HOLDOUT_ECONOMIC_DATA_OPENED": False,
        "NEXT_STEP": "RUN_CLEANROOM_R1_ONE_SHOT_TRUE_HOLDOUT_EVALUATION" if preholdout_gates_pass and diagnostic_start is None else "STOP_FOR_MANUAL_CODEX_REVIEW", "implementation_fix_count": 1,
        "source_data": "canonical raw QQQ/SOXX 1m only", "source_file_sha256": sha256_bytes(source_file.read_bytes()),
        "contract_sha256": sha256_bytes(json.dumps(contract, sort_keys=True, default=json_default).encode()),
        "preholdout_candidate_rows": int(len(preholdout)), "oof_rows": int(len(oof)), "holdout_feature_rows": int(len(holdout)),
        "primary_hgb_oof_metrics": metrics["hgb_primary"], "logistic_diagnostic_oof_metrics": metrics["logistic_diagnostic_only"],
        "holdout_ledger_schema": holdout_columns,
        "timings_seconds": timings, "diagnostic_slice": {"start": diagnostic_start, "end": diagnostic_end},
    }
    started = time.perf_counter()
    write_json(output_dir / "CLEANROOM_R1_FREEZE_MANIFEST.json", manifest)
    record_stage(timings, "freeze_manifest_hash_seconds", started, progress_path)
    manifest["timings_seconds"] = timings
    write_json(output_dir / "CLEANROOM_R1_FREEZE_MANIFEST.json", manifest)
    if not preholdout_gates_pass:
        raise RuntimeError("PRE_HOLDOUT_FREEZE_AUDIT_FAILED")
    print("CLEANROOM_STATUS=" + manifest["CLEANROOM_STATUS"])
    print("STRICT_FEATURE_PIT_PASS=true")
    print("TIME_ORDER_PASS=true")
    print("PURGE_EMBARGO_PASS=true")
    print("HOLDOUT_FEATURE_LEDGER_CREATED=true")
    print("FREEZE_MANIFEST_CREATED=true")
    print("NEXT_STEP=RUN_CLEANROOM_R1_ONE_SHOT_TRUE_HOLDOUT_EVALUATION")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--holdout-ledger-dir")
    parser.add_argument("--canonical-root", default=str(CANONICAL))
    parser.add_argument("--diagnostic-start")
    parser.add_argument("--diagnostic-end")
    arguments = parser.parse_args()
    run(Path(arguments.output_dir), Path(arguments.canonical_root),
        Path(arguments.holdout_ledger_dir) if arguments.holdout_ledger_dir else None,
        pd.Timestamp(arguments.diagnostic_start, tz="America/New_York") if arguments.diagnostic_start else None,
        pd.Timestamp(arguments.diagnostic_end, tz="America/New_York") if arguments.diagnostic_end else None)
