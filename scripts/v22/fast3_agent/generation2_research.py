#!/usr/bin/env python
"""FAST3 Generation 2: exposure audit, split freeze, and PIT baseline research.

The audit phase reads only canonical schema and timestamp/date metadata.  The
research phase refuses to run until that immutable contract exists and loads
only the frozen Development and Validation months; it cannot load Confirmation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


NAME = "FAST3_GENERATION2_SOXX_DIRECTIONAL_BASELINE_R1"
CANONICAL = Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
DEFAULT_OUT = Path(r"D:\us-tech-quant-results\fast3_autoresearch_generation2")
SYMBOLS = ("QQQ", "SOXX", "TQQQ", "SQQQ", "SOXL", "SOXS")
REQUIRED = ("timestamp_et", "timestamp_utc", "broker_trade_date", "session", "open", "high", "low", "close", "volume")
OLD_DEV_END = pd.Timestamp("2023-06-30", tz="America/New_York")
OLD_VAL_START = pd.Timestamp("2023-07-08", tz="America/New_York")
OLD_VAL_END = pd.Timestamp("2025-01-31", tz="America/New_York")
RANDOM_WINDOWS = (
    (pd.Timestamp("2024-05-16", tz="America/New_York"), pd.Timestamp("2024-10-27", tz="America/New_York")),
    (pd.Timestamp("2023-07-20", tz="America/New_York"), pd.Timestamp("2023-12-27", tz="America/New_York")),
    (pd.Timestamp("2023-11-29", tz="America/New_York"), pd.Timestamp("2024-05-08", tz="America/New_York")),
)
FEATURES = ("soxx_ret_5m", "soxx_ret_15m", "soxx_ret_30m", "soxx_ret_60m", "soxx_rvol_15m", "soxx_rvol_60m", "soxx_vol_15m", "soxx_vol_60m", "qqq_ret_15m", "soxx_qqq_rel_15m", "session_code")
VIX_FEATURES = ("vix_prev_day_return", "vix_pctl_252_prior", "vix_long_regime_allowed_p80", "vix_short_regime_elevated_p50")
VIX_PRIOR_DAY_FEATURES = Path(r"D:\us-tech-quant-data\fast3\vix_cboe_daily\features\vix_prior_day_regime_features.parquet")
SESSION_CODE = {"OVERNIGHT": 0, "PREMARKET": 1, "REGULAR_TRADING_HOURS": 2, "AFTER_HOURS": 3}


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return str(value)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")


def sha256_json(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default).encode("utf-8")).hexdigest()


def utc_epoch_ns(values) -> np.ndarray:
    """Return nanoseconds independent of Pandas' internal datetime resolution."""
    timestamps = pd.to_datetime(values, utc=True)
    raw = timestamps.astype("int64").to_numpy(dtype=np.int64)
    unit = getattr(timestamps.dtype, "unit", "ns")
    multiplier = {"s": 1_000_000_000, "ms": 1_000_000, "us": 1_000, "ns": 1}[unit]
    return raw * multiplier


def partition_paths(canonical: Path, symbol: str) -> list[Path]:
    paths = sorted(canonical.glob(f"symbol={symbol}/year=*/month=*/data.parquet"))
    if not paths:
        raise RuntimeError(f"SOURCE_DATA_MISSING:{symbol}")
    return paths


def month_key(path: Path) -> tuple[int, int]:
    return int(path.parts[-3].split("=")[1]), int(path.parts[-2].split("=")[1])


def canonical_date_metadata(canonical: Path) -> tuple[dict[str, list[pd.Timestamp]], list[dict]]:
    """Read only date/timestamp metadata; no OHLC/volume values are examined."""
    dates: dict[str, list[pd.Timestamp]] = {}
    audit: list[dict] = []
    for symbol in SYMBOLS:
        paths = partition_paths(canonical, symbol)
        parts = []
        for path in paths:
            part = pd.read_parquet(path, columns=["timestamp_et", "broker_trade_date"])
            ts = pd.to_datetime(part["timestamp_et"], errors="raise")
            parts.append(pd.Series(ts.dt.normalize().unique()))
        all_dates = pd.DatetimeIndex(pd.concat(parts, ignore_index=True).unique()).sort_values()
        dates[symbol] = list(all_dates)
        audit.append({"symbol": symbol, "partition_count": len(paths), "schema_required_fields": list(REQUIRED), "date_start": all_dates.min(), "date_end": all_dates.max(), "date_count": len(all_dates), "mode": "METADATA_ONLY_NO_OHLC_EXAMINATION"})
    return dates, audit


def prior_status_for_day(day: pd.Timestamp) -> str:
    if day <= OLD_DEV_END:
        return "PREVIOUSLY_USED_DEVELOPMENT"
    if OLD_VAL_START <= day <= OLD_VAL_END:
        if any(start <= day <= end for start, end in RANDOM_WINDOWS):
            return "PREVIOUSLY_USED_RANDOMIZED_SELECTION"
        return "PREVIOUSLY_USED_VALIDATION"
    if OLD_DEV_END < day < OLD_VAL_START:
        return "INELIGIBLE_OR_AMBIGUOUS"
    return "PREVIOUSLY_UNREAD_ELIGIBLE"


def freeze_contract(common_dates: pd.DatetimeIndex) -> dict:
    eligible = common_dates[common_dates > OLD_VAL_END]
    months = pd.PeriodIndex(eligible, freq="M").unique().sort_values()
    complete = []
    for month in months:
        month_days = eligible[pd.PeriodIndex(eligible, freq="M") == month]
        if len(month_days) >= 10:
            complete.append(month)
    usable = len(complete) - 2  # one whole calendar month embargo between each split
    if usable < 9:
        raise RuntimeError("FAIL_INSUFFICIENT_UNEXPOSED_DATA_FOR_GENERATION2")
    development_months = int(np.floor(usable * 0.60))
    validation_months = int(np.floor(usable * 0.20))
    confirmation_months = usable - development_months - validation_months
    if min(development_months, validation_months, confirmation_months) < 3:
        raise RuntimeError("FAIL_INSUFFICIENT_UNEXPOSED_DATA_FOR_GENERATION2")
    dev = complete[:development_months]
    first_embargo = complete[development_months]
    val_start_i = development_months + 1
    val = complete[val_start_i:val_start_i + validation_months]
    second_embargo = complete[val_start_i + validation_months]
    conf = complete[val_start_i + validation_months + 1:val_start_i + validation_months + 1 + confirmation_months]
    if len(conf) != confirmation_months:
        raise RuntimeError("FAIL_INSUFFICIENT_UNEXPOSED_DATA_FOR_GENERATION2")
    return {
        "research_id": NAME,
        "contract_status": "FROZEN_BEFORE_GENERATION2_ECONOMIC_RESULTS",
        "method": "common-date chronology; full calendar-month splits; one full calendar-month embargo (at least five trading days); 60/20/20 allocation after embargo months",
        "prior_generation_exposure_cutoff": OLD_VAL_END,
        "development_start": dev[0].start_time.tz_localize("America/New_York"),
        "development_end": dev[-1].end_time.tz_localize("America/New_York"),
        "first_embargo_start": first_embargo.start_time.tz_localize("America/New_York"),
        "first_embargo_end": first_embargo.end_time.tz_localize("America/New_York"),
        "validation_start": val[0].start_time.tz_localize("America/New_York"),
        "validation_end": val[-1].end_time.tz_localize("America/New_York"),
        "second_embargo_start": second_embargo.start_time.tz_localize("America/New_York"),
        "second_embargo_end": second_embargo.end_time.tz_localize("America/New_York"),
        "confirmation_start": conf[0].start_time.tz_localize("America/New_York"),
        "confirmation_end": conf[-1].end_time.tz_localize("America/New_York"),
        "label_horizons_minutes": [15, 30, 60, 120],
        "primary_label": "SOXX 60-minute next-valid-bar directional return",
        "execution": "SOXL for LONG / SOXS for SHORT; next valid open entry and 60-minute first valid open exit; 10bps base and 20bps stress round-trip cost",
        "candidate_grid": "completed SOXX bars where minute % 5 == 0; decision after bar close; entry on next valid bar",
        "features": list(FEATURES),
        "models": ["unconditional", "linear logistic regression C=1.0 with Development-only imputation/scaling"],
        "selection": "No model or action threshold selection from Validation in iteration 1; fixed 0.55/0.45 LONG/SHORT/FLAT action thresholds.",
        "randomized_oos": {"seed": 20260801, "window_trading_days": 10, "iterations": 20, "purpose": "chronological Validation robustness only; no retuning"},
        "confirmation_read_count": 0,
        "broker_action_allowed": False,
        "live_trading_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
    }


def audit_phase(output: Path, canonical: Path) -> dict:
    dates, source_audit = canonical_date_metadata(canonical)
    common = pd.DatetimeIndex(sorted(set(dates["SOXX"]).intersection(*[set(dates[s]) for s in SYMBOLS if s != "SOXX"])))
    contract = freeze_contract(common)
    contract["contract_sha256"] = sha256_json(contract)
    ledger = pd.DataFrame({"calendar_date_et": common, "generation2_data_usage": [prior_status_for_day(day) for day in common]})
    ledger["generation2_frozen_role"] = "OUTSIDE_GENERATION2_SPLITS"
    for role, start_key, end_key in (("DEVELOPMENT", "development_start", "development_end"), ("EMBARGO", "first_embargo_start", "first_embargo_end"), ("VALIDATION", "validation_start", "validation_end"), ("EMBARGO", "second_embargo_start", "second_embargo_end"), ("CONFIRMATION_UNREAD", "confirmation_start", "confirmation_end")):
        ledger.loc[ledger.calendar_date_et.between(pd.Timestamp(contract[start_key]), pd.Timestamp(contract[end_key])), "generation2_frozen_role"] = role
    ledger["prior_evidence_note"] = np.where(ledger.generation2_data_usage.eq("PREVIOUSLY_UNREAD_ELIGIBLE"), "No prior V22.080B fitting, selection, Validation, randomized-OOS, or Confirmation use recorded. V22.080A atlas observation is not used as model-selection evidence.", "Classified from immutable V22.080B split and randomized-window manifests.")
    ledger.to_csv(output / "generation2_data_usage_ledger.csv", index=False)
    write_json(output / "generation2_source_metadata_audit.json", {"source_audit": source_audit, "common_date_start": common.min(), "common_date_end": common.max(), "common_date_count": len(common), "ohlc_examination": "NOT_PERFORMED_IN_AUDIT_PHASE"})
    write_json(output / "generation2_split_contract.json", contract)
    write_json(output / "generation2_audit_checkpoint.json", {"current_status": "SPLIT_FROZEN_AWAITING_DEVELOPMENT_VALIDATION_RESEARCH", "confirmation_read_count": 0, "contract_sha256": contract["contract_sha256"], "next_exact_action": "python scripts/v22/fast3_agent/generation2_research.py --phase research", "known_failures": [], "source_date_range": {"start": common.min(), "end": common.max()}})
    return contract


def _read_range(canonical: Path, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Only opens monthly files wholly before Confirmation and filters to frozen ranges."""
    frames = []
    confirmation_month = (end + pd.offsets.MonthBegin(1)).to_period("M")
    for path in partition_paths(canonical, symbol):
        if pd.Period(year=month_key(path)[0], month=month_key(path)[1], freq="M") > confirmation_month:
            continue
        frame = pd.read_parquet(path, columns=list(REQUIRED))
        frame["timestamp_et"] = pd.to_datetime(frame["timestamp_et"], errors="raise")
        frame = frame[(frame.timestamp_et >= start) & (frame.timestamp_et <= end)].copy()
        if not frame.empty:
            frames.append(frame)
    if not frames:
        raise RuntimeError(f"SOURCE_DATA_MISSING_RANGE:{symbol}")
    out = pd.concat(frames, ignore_index=True)
    out["timestamp_utc"] = pd.to_datetime(out["timestamp_utc"], utc=True, errors="raise")
    out = out.sort_values("timestamp_utc", kind="mergesort").drop_duplicates("timestamp_utc").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["valid"] = (out.open > 0) & (out.high >= out[["open", "low", "close"]].max(axis=1)) & (out.low <= out[["open", "high", "close"]].min(axis=1))
    out["session_code"] = out.session.astype(str).str.upper().map(SESSION_CODE).fillna(4).astype(int)
    return out


def _asof_feature(source: pd.DataFrame, target_ns: np.ndarray, column: str) -> np.ndarray:
    ns = utc_epoch_ns(source.timestamp_utc)
    values = source[column].to_numpy(float)
    index = np.searchsorted(ns, target_ns, side="right") - 1
    out = np.full(len(target_ns), np.nan)
    good = index >= 0
    out[good] = values[index[good]]
    return out


def _next_index(ns: np.ndarray, target_ns: np.ndarray) -> np.ndarray:
    return np.searchsorted(ns, target_ns, side="left")


def make_samples(soxx: pd.DataFrame, qqq: pd.DataFrame, contract: dict) -> pd.DataFrame:
    close = soxx.close.to_numpy(float)
    ret1 = np.r_[np.nan, np.diff(np.log(close))]
    features = pd.DataFrame(index=soxx.index)
    for horizon in (5, 15, 30, 60):
        features[f"soxx_ret_{horizon}m"] = pd.Series(close).pct_change(horizon)
    features["soxx_rvol_15m"] = pd.Series(soxx.volume).rolling(15, min_periods=15).mean()
    features["soxx_rvol_60m"] = pd.Series(soxx.volume).rolling(60, min_periods=60).mean()
    features["soxx_rvol_15m"] = soxx.volume / features["soxx_rvol_15m"]
    features["soxx_rvol_60m"] = soxx.volume / features["soxx_rvol_60m"]
    features["soxx_vol_15m"] = pd.Series(ret1).rolling(15, min_periods=15).std()
    features["soxx_vol_60m"] = pd.Series(ret1).rolling(60, min_periods=60).std()
    ns = utc_epoch_ns(soxx.timestamp_utc)
    qqq_close = _asof_feature(qqq, ns, "close")
    qqq_ret15 = pd.Series(qqq_close).pct_change(15).to_numpy()
    features["qqq_ret_15m"] = qqq_ret15
    features["soxx_qqq_rel_15m"] = features["soxx_ret_15m"] - qqq_ret15
    features["session_code"] = soxx.session_code
    grid = (soxx.timestamp_et.dt.minute.to_numpy() % 5 == 0) & soxx.valid.to_numpy() & (np.arange(len(soxx)) >= 60)
    decision = np.flatnonzero(grid)
    entry = _next_index(ns, ns[decision] + 60_000_000_000)
    rows = pd.DataFrame({"decision_i": decision, "entry_i": entry})
    rows = rows[rows.entry_i < len(soxx)].copy()
    entry = rows.entry_i.to_numpy()
    for horizon in (15, 30, 60, 120):
        exit_i = _next_index(ns, ns[entry] + horizon * 60_000_000_000)
        valid = exit_i < len(soxx)
        label = np.full(len(rows), np.nan)
        label[valid] = soxx.open.to_numpy(float)[exit_i[valid]] / soxx.open.to_numpy(float)[entry[valid]] - 1.0
        rows[f"soxx_return_{horizon}m"] = label
        rows[f"label_up_{horizon}m"] = (label > 0).astype(float)
    take = rows.decision_i.to_numpy()
    for feature in FEATURES:
        rows[feature] = features[feature].to_numpy()[take]
    rows["decision_timestamp_et"] = soxx.timestamp_et.to_numpy()[take]
    rows["decision_timestamp_utc"] = soxx.timestamp_utc.to_numpy()[take]
    rows["entry_timestamp_utc"] = soxx.timestamp_utc.to_numpy()[rows.entry_i.to_numpy()]
    rows["calendar_date"] = pd.to_datetime(rows.decision_timestamp_et).dt.normalize()
    rows = rows.dropna(subset=list(FEATURES) + ["soxx_return_60m"]).reset_index(drop=True)
    val_start = pd.Timestamp(contract["validation_start"])
    val_end = pd.Timestamp(contract["validation_end"])
    dev_start = pd.Timestamp(contract["development_start"])
    dev_end = pd.Timestamp(contract["development_end"])
    rows["split"] = np.where(rows.decision_timestamp_et.between(dev_start, dev_end), "DEVELOPMENT", np.where(rows.decision_timestamp_et.between(val_start, val_end), "VALIDATION", "EXCLUDED"))
    return rows[rows.split.ne("EXCLUDED")].reset_index(drop=True)


def mapped_execution(samples: pd.DataFrame, soxl: pd.DataFrame, soxs: pd.DataFrame, probabilities: np.ndarray, threshold: float = .55) -> pd.DataFrame:
    probabilities = np.asarray(probabilities, dtype=float)
    result = samples[["decision_timestamp_et", "entry_timestamp_utc", "calendar_date", "split"]].copy()
    result["probability_up"] = probabilities
    result["action"] = np.where(probabilities >= threshold, "LONG", np.where(probabilities <= 1.0 - threshold, "SHORT", "FLAT"))
    result["execution_etf"] = np.where(result.action.eq("LONG"), "SOXL", np.where(result.action.eq("SHORT"), "SOXS", None))
    result["gross_return"] = np.nan
    result["execution_status"] = np.where(result.action.eq("FLAT"), "NO_TRADE", "NOT_COMPUTED")
    for etf_name, etf in (("SOXL", soxl), ("SOXS", soxs)):
        mask = result.execution_etf.eq(etf_name).to_numpy()
        if not mask.any():
            continue
        ns = utc_epoch_ns(etf.timestamp_utc)
        entry_target = utc_epoch_ns(result.loc[mask, "entry_timestamp_utc"])
        entry_i = _next_index(ns, entry_target)
        exit_i = _next_index(ns, entry_target + 60 * 60 * 1_000_000_000)
        good = (entry_i < len(etf)) & (exit_i < len(etf)) & ((ns[entry_i] - entry_target) <= 60_000_000_000)
        values = np.full(mask.sum(), np.nan)
        values[good] = etf.open.to_numpy(float)[exit_i[good]] / etf.open.to_numpy(float)[entry_i[good]] - 1.0
        # A 30% one-hour move in a 3x ETF is a source-integrity exception, not a
        # tradable outcome.  This broad, pre-economic fail-closed guard prevents
        # unadjusted split/reverse-split discontinuities from becoming P&L.
        abnormal = good.copy()
        abnormal[good] = np.abs(values[good]) > .30
        values[abnormal] = np.nan
        result.loc[mask, "gross_return"] = values
        status = np.where(~good, "EXECUTION_TIMESTAMP_OR_PRICE_INVALID", np.where(abnormal, "ABNORMAL_RETURN_DATA_QUALITY_GATE", "SUCCESS"))
        result.loc[mask, "execution_status"] = status
    result["net_return_10bps"] = result.gross_return - .001
    result["net_return_20bps"] = result.gross_return - .002
    return result


def metrics(frame: pd.DataFrame) -> dict:
    selected = frame[frame.action.ne("FLAT") & frame.net_return_10bps.notna()].copy()
    if selected.empty:
        return {"candidate_count": len(frame), "trade_count": 0, "execution_data_quality_exclusion_count": int(frame.execution_status.eq("ABNORMAL_RETURN_DATA_QUALITY_GATE").sum()), "mean_net_return_10bps": None, "mean_net_return_20bps": None, "positive_month_ratio": None, "max_drawdown": None}
    daily = selected.groupby("calendar_date").net_return_10bps.sum()
    cumulative = daily.cumsum()
    drawdown = cumulative - cumulative.cummax()
    monthly = selected.groupby(pd.to_datetime(selected.calendar_date).dt.to_period("M")).net_return_10bps.sum()
    return {"candidate_count": int(len(frame)), "trade_count": int(len(selected)), "execution_data_quality_exclusion_count": int(frame.execution_status.eq("ABNORMAL_RETURN_DATA_QUALITY_GATE").sum()), "mean_net_return_10bps": float(selected.net_return_10bps.mean()), "mean_net_return_20bps": float(selected.net_return_20bps.mean()), "positive_month_ratio": float((monthly >= 0).mean()), "max_drawdown": float(abs(drawdown.min())), "long_trade_count": int(selected.action.eq("LONG").sum()), "short_trade_count": int(selected.action.eq("SHORT").sum())}


def randomized_windows(execution: pd.DataFrame, contract: dict) -> pd.DataFrame:
    val = execution[execution.split.eq("VALIDATION")].copy()
    days = np.array(sorted(val.calendar_date.unique()))
    config = contract["randomized_oos"]
    rng = np.random.default_rng(config["seed"])
    rows = []
    length = config["window_trading_days"]
    if len(days) < length:
        return pd.DataFrame(rows)
    for i in range(1, config["iterations"] + 1):
        start_i = int(rng.integers(0, len(days) - length + 1))
        days_i = days[start_i:start_i + length]
        window = val[val.calendar_date.isin(days_i)]
        m = metrics(window)
        rows.append({"iteration_id": i, "random_seed": config["seed"], "window_start": days_i[0], "window_end": days_i[-1], **m, "decision": "ROBUSTNESS_EVIDENCE_ONLY_NO_RETUNING"})
    return pd.DataFrame(rows)


def load_vix_prior_day_features(path: Path, contract: dict) -> pd.DataFrame:
    """Load only pre-Confirmation daily VIX features with a prior-day cutoff."""
    if not path.is_file():
        raise RuntimeError("SOURCE_DATA_MISSING:VIX_PRIOR_DAY_FEATURES")
    start = pd.Timestamp(contract["development_start"]).tz_localize(None).normalize()
    end = pd.Timestamp(contract["validation_end"]).tz_localize(None).normalize()
    columns = ["trade_date", "feature_information_cutoff", *VIX_FEATURES]
    frame = pd.read_parquet(path, columns=columns, filters=[("trade_date", ">=", start), ("trade_date", "<=", end)])
    if frame.empty:
        raise RuntimeError("SOURCE_DATA_MISSING_RANGE:VIX_PRIOR_DAY_FEATURES")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    frame["feature_information_cutoff"] = pd.to_datetime(frame["feature_information_cutoff"], errors="raise").dt.normalize()
    if (frame.feature_information_cutoff >= frame.trade_date).any():
        raise RuntimeError("VIX_PRIOR_DAY_PIT_VIOLATION")
    if frame.trade_date.max() > end:
        raise RuntimeError("CONFIRMATION_ISOLATION_VIOLATION")
    for feature in VIX_FEATURES:
        frame[feature] = pd.to_numeric(frame[feature], errors="coerce")
    return frame[["trade_date", *VIX_FEATURES]].drop_duplicates("trade_date", keep="last")


def add_vix_prior_day_features(samples: pd.DataFrame, vix: pd.DataFrame) -> pd.DataFrame:
    """Join VIX by decision date; unavailable daily observations fail closed as FLAT."""
    result = samples.copy()
    result["trade_date"] = pd.to_datetime(result.calendar_date).dt.tz_localize(None).dt.normalize()
    result = result.merge(vix, on="trade_date", how="left", validate="many_to_one")
    return result.drop(columns="trade_date")


def research_phase(output: Path, canonical: Path) -> dict:
    contract_path = output / "generation2_split_contract.json"
    if not contract_path.exists():
        raise RuntimeError("GENERATION2_SPLIT_CONTRACT_MISSING")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if contract.get("confirmation_read_count") != 0:
        raise RuntimeError("CONFIRMATION_ISOLATION_VIOLATION")
    start = pd.Timestamp(contract["development_start"])
    end = pd.Timestamp(contract["validation_end"])
    # End is before Confirmation by a full calendar-month embargo: this is the guard.
    data = {symbol: _read_range(canonical, symbol, start, end) for symbol in ("SOXX", "QQQ", "SOXL", "SOXS")}
    samples = make_samples(data["SOXX"], data["QQQ"], contract)
    dev = samples[samples.split.eq("DEVELOPMENT")].copy()
    val = samples[samples.split.eq("VALIDATION")].copy()
    if min(len(dev), len(val)) < 1000:
        raise RuntimeError("INSUFFICIENT_VALIDATION_SAMPLE")
    model = Pipeline([("imputer", SimpleImputer(strategy="median")), ("scale", StandardScaler()), ("model", LogisticRegression(C=1.0, max_iter=300, random_state=20260801))])
    model.fit(dev[list(FEATURES)], dev.label_up_60m.astype(int))
    for frame in (dev, val):
        frame["probability_up"] = model.predict_proba(frame[list(FEATURES)])[:, 1]
    validation_auc = float(roc_auc_score(val.label_up_60m.astype(int), val.probability_up))
    validation_brier = float(brier_score_loss(val.label_up_60m.astype(int), val.probability_up))
    execution = pd.concat([mapped_execution(frame, data["SOXL"], data["SOXS"], frame.probability_up.to_numpy()) for frame in (dev, val)], ignore_index=True)
    dev_exec = execution.iloc[:len(dev)].copy(); dev_exec["split"] = "DEVELOPMENT"
    val_exec = execution.iloc[len(dev):].copy(); val_exec["split"] = "VALIDATION"
    execution = pd.concat([dev_exec, val_exec], ignore_index=True)
    windows = randomized_windows(execution, contract)
    dev_m, val_m = metrics(dev_exec), metrics(val_exec)
    robust = bool(not windows.empty and windows.mean_net_return_10bps.notna().all() and (windows.mean_net_return_10bps > 0).mean() >= .65 and val_m["mean_net_return_20bps"] is not None and val_m["mean_net_return_20bps"] > 0)
    decision = "PASS_CANDIDATE_READY_FOR_CONFIRMATION" if robust else "FAIL_NO_ROBUST_EDGE"
    summary = {"research_id": NAME, "iteration_id": "GEN2_ITERATION_002_EXECUTION_DATA_QUALITY_GUARD", "parent_iteration": "GEN2_ITERATION_001_LINEAR_SOXX_MULTISCALE_BASELINE", "hypothesis": "A fail-closed 60-minute abnormal-return data-quality gate removes corporate-action discontinuities without creating or selecting a predictive signal.", "changed_component": "Execution-data integrity repair: reject SOXL/SOXS returns whose absolute 60-minute gross return exceeds 30%; model, labels, split, features, and action thresholds unchanged.", "contract_sha256": contract["contract_sha256"], "confirmation_read_count": 0, "development_metrics": dev_m, "validation_metrics": val_m, "validation_auc": validation_auc, "validation_brier": validation_brier, "random_window_count": int(len(windows)), "positive_random_window_ratio": float((windows.mean_net_return_10bps > 0).mean()) if not windows.empty else None, "decision": decision, "broker_action_allowed": False, "live_trading_allowed": False, "official_adoption_allowed": False, "research_only": True}
    windows.to_csv(output / "generation2_iteration_002_random_window_metrics.csv", index=False)
    pd.DataFrame([summary]).to_json(output / "generation2_iteration_002_metrics.json", orient="records", indent=2, default_handler=str)
    write_json(output / "generation2_iteration_002_summary.json", summary)
    registry_path = output / "generation2_experiment_registry.csv"
    prior_registry = pd.read_csv(registry_path) if registry_path.exists() else pd.DataFrame()
    registry = pd.concat([prior_registry, pd.DataFrame([{"iteration_id": summary["iteration_id"], "hypothesis": summary["hypothesis"], "changed_component": summary["changed_component"], "window_contract_sha256": contract["contract_sha256"], "tests": "pending focused pytest at runner level", "decision": decision, "next_allowed_research": "factor ablation or calibrated abstention diagnosis; Confirmation prohibited"}])], ignore_index=True)
    registry.to_csv(registry_path, index=False)
    write_json(output / "generation2_checkpoint.json", {"current_status": decision, "current_champion": None, "last_completed_iteration": 1, "confirmation_read_count": 0, "completed_backtests": "Generation 2 linear Development/Validation baseline and 20 fixed-seed chronological Validation windows", "known_failures": [] if robust else ["Iteration 1 did not clear the predeclared robust post-cost Validation gate."], "next_exact_action": "Review iteration 1 factor/abstention diagnostics; do not read Confirmation.", "exact_resume_command": "python scripts/v22/fast3_agent/generation2_research.py --phase research", "contract_sha256": contract["contract_sha256"]})
    return summary


def abstention_phase(output: Path, canonical: Path) -> dict:
    """Development-only calibration of a small pre-registered abstention grid."""
    contract = json.loads((output / "generation2_split_contract.json").read_text(encoding="utf-8"))
    if contract.get("confirmation_read_count") != 0:
        raise RuntimeError("CONFIRMATION_ISOLATION_VIOLATION")
    start, end = pd.Timestamp(contract["development_start"]), pd.Timestamp(contract["validation_end"])
    data = {symbol: _read_range(canonical, symbol, start, end) for symbol in ("SOXX", "QQQ", "SOXL", "SOXS")}
    samples = make_samples(data["SOXX"], data["QQQ"], contract)
    dev, val = samples[samples.split.eq("DEVELOPMENT")].copy(), samples[samples.split.eq("VALIDATION")].copy()
    model = Pipeline([("imputer", SimpleImputer(strategy="median")), ("scale", StandardScaler()), ("model", LogisticRegression(C=1.0, max_iter=300, random_state=20260801))])
    model.fit(dev[list(FEATURES)], dev.label_up_60m.astype(int))
    dev["probability_up"] = model.predict_proba(dev[list(FEATURES)])[:, 1]
    val["probability_up"] = model.predict_proba(val[list(FEATURES)])[:, 1]
    thresholds = (.52, .55, .58, .60, .65)
    dev_trials = []
    executions = {}
    for threshold in thresholds:
        execution = mapped_execution(dev, data["SOXL"], data["SOXS"], dev.probability_up.to_numpy(), threshold)
        executions[threshold] = execution
        dev_trials.append({"threshold": threshold, **metrics(execution)})
    table = pd.DataFrame(dev_trials)
    eligible = table[table.trade_count >= 500].sort_values(["mean_net_return_10bps", "threshold"], ascending=[False, True])
    if eligible.empty:
        raise RuntimeError("INSUFFICIENT_DEVELOPMENT_ACTION_SAMPLE")
    selected_threshold = float(eligible.iloc[0].threshold)
    val_execution = mapped_execution(val, data["SOXL"], data["SOXS"], val.probability_up.to_numpy(), selected_threshold)
    val_execution["split"] = "VALIDATION"
    windows = randomized_windows(val_execution, contract)
    dev_m, val_m = metrics(executions[selected_threshold]), metrics(val_execution)
    robust = bool(not windows.empty and (windows.mean_net_return_10bps > 0).mean() >= .65 and (windows.mean_net_return_20bps > 0).mean() >= .65 and val_m["mean_net_return_10bps"] > 0 and val_m["mean_net_return_20bps"] > 0)
    decision = "PASS_CANDIDATE_READY_FOR_CONFIRMATION" if robust else "FAIL_NO_ROBUST_EDGE"
    summary = {"research_id": NAME, "iteration_id": "GEN2_ITERATION_003_DEVELOPMENT_ONLY_CALIBRATED_ABSTENTION", "parent_iteration": "GEN2_ITERATION_002_EXECUTION_DATA_QUALITY_GUARD", "hypothesis": "A pre-registered symmetric LONG/SHORT/FLAT probability threshold selected solely from unused Generation 2 Development economics can reduce low-confidence losses and improve Validation post-cost expectancy.", "changed_component": "Development-only selection from the fixed threshold grid [0.52, 0.55, 0.58, 0.60, 0.65], minimum 500 Development trades; all other model, feature, label, split, and execution settings unchanged.", "selection_metric": "highest Development 10bps mean net return; deterministic lower threshold tie-break", "selected_threshold": selected_threshold, "development_threshold_trials": table.to_dict(orient="records"), "contract_sha256": contract["contract_sha256"], "confirmation_read_count": 0, "development_metrics": dev_m, "validation_metrics": val_m, "random_window_count": int(len(windows)), "positive_random_window_ratio_10bps": float((windows.mean_net_return_10bps > 0).mean()) if not windows.empty else None, "positive_random_window_ratio_20bps": float((windows.mean_net_return_20bps > 0).mean()) if not windows.empty else None, "decision": decision, "broker_action_allowed": False, "live_trading_allowed": False, "official_adoption_allowed": False, "research_only": True}
    table.to_csv(output / "generation2_iteration_003_development_threshold_trials.csv", index=False)
    windows.to_csv(output / "generation2_iteration_003_random_window_metrics.csv", index=False)
    write_json(output / "generation2_iteration_003_summary.json", summary)
    registry_path = output / "generation2_experiment_registry.csv"
    registry = pd.read_csv(registry_path)
    registry = pd.concat([registry, pd.DataFrame([{"iteration_id": summary["iteration_id"], "hypothesis": summary["hypothesis"], "changed_component": summary["changed_component"], "window_contract_sha256": contract["contract_sha256"], "tests": "focused pytest at runner level", "decision": decision, "next_allowed_research": "one compact nonlinear challenger only if the threshold baseline supplies a plausible post-cost direction; otherwise stop after reporting failures"}])], ignore_index=True)
    registry.to_csv(registry_path, index=False)
    write_json(output / "generation2_checkpoint.json", {"current_status": decision, "current_champion": None, "last_completed_iteration": 3, "confirmation_read_count": 0, "completed_backtests": "Generation 2 baseline, execution data-quality repair, and Development-only calibrated abstention Validation evaluation", "known_failures": [] if robust else ["Baseline and Development-selected abstention did not clear the predeclared robust post-cost Validation gate."], "next_exact_action": "Run only the pre-registered compact nonlinear challenger if this iteration has a plausible OOS direction; Confirmation remains prohibited.", "exact_resume_command": "python scripts/v22/fast3_agent/generation2_research.py --phase abstention", "contract_sha256": contract["contract_sha256"]})
    return summary


def nonlinear_phase(output: Path, canonical: Path) -> dict:
    """One compact, regularized nonlinear challenger after the linear baseline."""
    contract = json.loads((output / "generation2_split_contract.json").read_text(encoding="utf-8"))
    if contract.get("confirmation_read_count") != 0:
        raise RuntimeError("CONFIRMATION_ISOLATION_VIOLATION")
    start, end = pd.Timestamp(contract["development_start"]), pd.Timestamp(contract["validation_end"])
    data = {symbol: _read_range(canonical, symbol, start, end) for symbol in ("SOXX", "QQQ", "SOXL", "SOXS")}
    samples = make_samples(data["SOXX"], data["QQQ"], contract)
    dev, val = samples[samples.split.eq("DEVELOPMENT")].copy(), samples[samples.split.eq("VALIDATION")].copy()
    model = Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", HistGradientBoostingClassifier(max_iter=80, max_leaf_nodes=7, min_samples_leaf=500, learning_rate=.05, l2_regularization=5.0, random_state=20260801))])
    model.fit(dev[list(FEATURES)], dev.label_up_60m.astype(int))
    dev["probability_up"] = model.predict_proba(dev[list(FEATURES)])[:, 1]
    val["probability_up"] = model.predict_proba(val[list(FEATURES)])[:, 1]
    thresholds = (.52, .55, .58, .60, .65)
    trials, dev_execs = [], {}
    for threshold in thresholds:
        execution = mapped_execution(dev, data["SOXL"], data["SOXS"], dev.probability_up.to_numpy(), threshold)
        dev_execs[threshold] = execution
        trials.append({"threshold": threshold, **metrics(execution)})
    table = pd.DataFrame(trials)
    eligible = table[table.trade_count >= 500].sort_values(["mean_net_return_10bps", "threshold"], ascending=[False, True])
    if eligible.empty:
        raise RuntimeError("INSUFFICIENT_DEVELOPMENT_ACTION_SAMPLE")
    selected_threshold = float(eligible.iloc[0].threshold)
    val_execution = mapped_execution(val, data["SOXL"], data["SOXS"], val.probability_up.to_numpy(), selected_threshold)
    val_execution["split"] = "VALIDATION"
    windows = randomized_windows(val_execution, contract)
    dev_m, val_m = metrics(dev_execs[selected_threshold]), metrics(val_execution)
    robust = bool(not windows.empty and (windows.mean_net_return_10bps > 0).mean() >= .65 and (windows.mean_net_return_20bps > 0).mean() >= .65 and val_m["mean_net_return_10bps"] > 0 and val_m["mean_net_return_20bps"] > 0)
    decision = "PASS_CANDIDATE_READY_FOR_CONFIRMATION" if robust else "FAIL_NO_ROBUST_EDGE"
    summary = {"research_id": NAME, "iteration_id": "GEN2_ITERATION_004_COMPACT_NONLINEAR_CHALLENGER", "parent_iteration": "GEN2_ITERATION_003_DEVELOPMENT_ONLY_CALIBRATED_ABSTENTION", "hypothesis": "A compact regularized nonlinear interaction model can improve PIT SOXX directional separation enough to survive fixed post-cost Validation and randomized chronological windows.", "changed_component": "Replaced the linear classifier with a predeclared HistGradientBoosting model (80 iterations, 7 leaves, minimum leaf 500, learning rate 0.05, L2 5.0); Development-only abstention selection and all other contracts unchanged.", "selected_threshold": selected_threshold, "development_threshold_trials": table.to_dict(orient="records"), "contract_sha256": contract["contract_sha256"], "confirmation_read_count": 0, "development_metrics": dev_m, "validation_metrics": val_m, "validation_auc": float(roc_auc_score(val.label_up_60m.astype(int), val.probability_up)), "validation_brier": float(brier_score_loss(val.label_up_60m.astype(int), val.probability_up)), "random_window_count": int(len(windows)), "positive_random_window_ratio_10bps": float((windows.mean_net_return_10bps > 0).mean()) if not windows.empty else None, "positive_random_window_ratio_20bps": float((windows.mean_net_return_20bps > 0).mean()) if not windows.empty else None, "decision": decision, "broker_action_allowed": False, "live_trading_allowed": False, "official_adoption_allowed": False, "research_only": True}
    table.to_csv(output / "generation2_iteration_004_development_threshold_trials.csv", index=False)
    windows.to_csv(output / "generation2_iteration_004_random_window_metrics.csv", index=False)
    write_json(output / "generation2_iteration_004_summary.json", summary)
    registry_path = output / "generation2_experiment_registry.csv"
    registry = pd.read_csv(registry_path)
    registry = pd.concat([registry, pd.DataFrame([{"iteration_id": summary["iteration_id"], "hypothesis": summary["hypothesis"], "changed_component": summary["changed_component"], "window_contract_sha256": contract["contract_sha256"], "tests": "focused pytest at runner level", "decision": decision, "next_allowed_research": "factor ablation only; Confirmation prohibited unless all pre-Confirmation gates pass"}])], ignore_index=True)
    registry.to_csv(registry_path, index=False)
    write_json(output / "generation2_checkpoint.json", {"current_status": decision, "current_champion": None, "last_completed_iteration": 4, "confirmation_read_count": 0, "completed_backtests": "Generation 2 linear baseline, data-quality repair, Development-only abstention, and compact nonlinear challenger", "known_failures": [] if robust else ["No executed Generation 2 candidate has cleared robust post-cost Validation."], "next_exact_action": "Run a single pre-registered feature-group ablation if a materially distinct factor hypothesis remains; Confirmation remains prohibited.", "exact_resume_command": "python scripts/v22/fast3_agent/generation2_research.py --phase nonlinear", "contract_sha256": contract["contract_sha256"]})
    return summary


def soxx_only_ablation_phase(output: Path, canonical: Path) -> dict:
    """A single feature-group ablation: remove QQQ cross-asset inputs."""
    contract = json.loads((output / "generation2_split_contract.json").read_text(encoding="utf-8"))
    if contract.get("confirmation_read_count") != 0:
        raise RuntimeError("CONFIRMATION_ISOLATION_VIOLATION")
    start, end = pd.Timestamp(contract["development_start"]), pd.Timestamp(contract["validation_end"])
    data = {symbol: _read_range(canonical, symbol, start, end) for symbol in ("SOXX", "QQQ", "SOXL", "SOXS")}
    samples = make_samples(data["SOXX"], data["QQQ"], contract)
    dev, val = samples[samples.split.eq("DEVELOPMENT")].copy(), samples[samples.split.eq("VALIDATION")].copy()
    features = tuple(x for x in FEATURES if x not in {"qqq_ret_15m", "soxx_qqq_rel_15m"})
    model = Pipeline([("imputer", SimpleImputer(strategy="median")), ("scale", StandardScaler()), ("model", LogisticRegression(C=1.0, max_iter=300, random_state=20260801))])
    model.fit(dev[list(features)], dev.label_up_60m.astype(int))
    dev["probability_up"] = model.predict_proba(dev[list(features)])[:, 1]
    val["probability_up"] = model.predict_proba(val[list(features)])[:, 1]
    thresholds = (.52, .55, .58, .60, .65)
    trials, dev_execs = [], {}
    for threshold in thresholds:
        execution = mapped_execution(dev, data["SOXL"], data["SOXS"], dev.probability_up.to_numpy(), threshold)
        dev_execs[threshold] = execution
        trials.append({"threshold": threshold, **metrics(execution)})
    table = pd.DataFrame(trials)
    eligible = table[table.trade_count >= 500].sort_values(["mean_net_return_10bps", "threshold"], ascending=[False, True])
    if eligible.empty:
        raise RuntimeError("INSUFFICIENT_DEVELOPMENT_ACTION_SAMPLE")
    selected_threshold = float(eligible.iloc[0].threshold)
    val_execution = mapped_execution(val, data["SOXL"], data["SOXS"], val.probability_up.to_numpy(), selected_threshold)
    val_execution["split"] = "VALIDATION"
    windows = randomized_windows(val_execution, contract)
    dev_m, val_m = metrics(dev_execs[selected_threshold]), metrics(val_execution)
    robust = bool(not windows.empty and (windows.mean_net_return_10bps > 0).mean() >= .65 and (windows.mean_net_return_20bps > 0).mean() >= .65 and val_m["mean_net_return_10bps"] > 0 and val_m["mean_net_return_20bps"] > 0)
    decision = "PASS_CANDIDATE_READY_FOR_CONFIRMATION" if robust else "FAIL_NO_ROBUST_EDGE"
    summary = {"research_id": NAME, "iteration_id": "GEN2_ITERATION_005_SOXX_ONLY_FACTOR_ABLATION", "parent_iteration": "GEN2_ITERATION_003_DEVELOPMENT_ONLY_CALIBRATED_ABSTENTION", "hypothesis": "QQQ relative-strength features add noise to short-horizon SOXX direction; removing that single feature group can improve post-cost Validation robustness.", "changed_component": "Removed only qqq_ret_15m and soxx_qqq_rel_15m from the linear Development-only calibrated-abstention baseline.", "features": list(features), "selected_threshold": selected_threshold, "development_threshold_trials": table.to_dict(orient="records"), "contract_sha256": contract["contract_sha256"], "confirmation_read_count": 0, "development_metrics": dev_m, "validation_metrics": val_m, "validation_auc": float(roc_auc_score(val.label_up_60m.astype(int), val.probability_up)), "validation_brier": float(brier_score_loss(val.label_up_60m.astype(int), val.probability_up)), "random_window_count": int(len(windows)), "positive_random_window_ratio_10bps": float((windows.mean_net_return_10bps > 0).mean()) if not windows.empty else None, "positive_random_window_ratio_20bps": float((windows.mean_net_return_20bps > 0).mean()) if not windows.empty else None, "decision": decision, "broker_action_allowed": False, "live_trading_allowed": False, "official_adoption_allowed": False, "research_only": True}
    table.to_csv(output / "generation2_iteration_005_development_threshold_trials.csv", index=False)
    windows.to_csv(output / "generation2_iteration_005_random_window_metrics.csv", index=False)
    write_json(output / "generation2_iteration_005_summary.json", summary)
    registry_path = output / "generation2_experiment_registry.csv"
    registry = pd.read_csv(registry_path)
    registry = pd.concat([registry, pd.DataFrame([{"iteration_id": summary["iteration_id"], "hypothesis": summary["hypothesis"], "changed_component": summary["changed_component"], "window_contract_sha256": contract["contract_sha256"], "tests": "focused pytest at runner level", "decision": decision, "next_allowed_research": "create concise Generation 2 progress report and preserve zero-read Confirmation checkpoint"}])], ignore_index=True)
    registry.to_csv(registry_path, index=False)
    write_json(output / "generation2_checkpoint.json", {"current_status": decision, "current_champion": None, "last_completed_iteration": 5, "confirmation_read_count": 0, "completed_backtests": "Generation 2 linear baseline, execution data-quality repair, Development-only abstention, compact nonlinear challenger, and SOXX-only cross-asset ablation", "known_failures": [] if robust else ["All completed Generation 2 candidates fail at least one predeclared post-cost or randomized-OOS robustness gate."], "next_exact_action": "Inspect only local VIX sources for timestamped point-in-time availability before registering any fresh VIX-factor experiment; do not repeat iteration 5 and do not read Confirmation.", "exact_resume_command": "rg --files D:\\us-tech-quant D:\\us-tech-quant-results | rg -i 'vix|volatility.*index'", "contract_sha256": contract["contract_sha256"]})
    return summary


def vix_prior_day_phase(output: Path, canonical: Path, vix_path: Path) -> dict:
    """One registered challenger using only CBOE's already-available prior-day VIX fields."""
    contract = json.loads((output / "generation2_split_contract.json").read_text(encoding="utf-8"))
    if contract.get("confirmation_read_count") != 0:
        raise RuntimeError("CONFIRMATION_ISOLATION_VIOLATION")
    start, end = pd.Timestamp(contract["development_start"]), pd.Timestamp(contract["validation_end"])
    data = {symbol: _read_range(canonical, symbol, start, end) for symbol in ("SOXX", "QQQ", "SOXL", "SOXS")}
    samples = add_vix_prior_day_features(make_samples(data["SOXX"], data["QQQ"], contract), load_vix_prior_day_features(vix_path, contract))
    features = (*FEATURES, *VIX_FEATURES)
    dev, val = samples[samples.split.eq("DEVELOPMENT")].copy(), samples[samples.split.eq("VALIDATION")].copy()
    model = Pipeline([("imputer", SimpleImputer(strategy="median")), ("scale", StandardScaler()), ("model", LogisticRegression(C=1.0, max_iter=300, random_state=20260801))])
    model.fit(dev[list(features)], dev.label_up_60m.astype(int))
    dev["probability_up"] = model.predict_proba(dev[list(features)])[:, 1]
    val["probability_up"] = model.predict_proba(val[list(features)])[:, 1]
    thresholds = (.52, .55, .58, .60, .65)
    trials, dev_execs = [], {}
    for threshold in thresholds:
        execution = mapped_execution(dev, data["SOXL"], data["SOXS"], dev.probability_up.to_numpy(), threshold)
        dev_execs[threshold] = execution
        trials.append({"threshold": threshold, **metrics(execution)})
    table = pd.DataFrame(trials)
    eligible = table[table.trade_count >= 500].sort_values(["mean_net_return_10bps", "threshold"], ascending=[False, True])
    if eligible.empty:
        raise RuntimeError("INSUFFICIENT_DEVELOPMENT_ACTION_SAMPLE")
    selected_threshold = float(eligible.iloc[0].threshold)
    val_execution = mapped_execution(val, data["SOXL"], data["SOXS"], val.probability_up.to_numpy(), selected_threshold)
    val_execution["split"] = "VALIDATION"
    windows = randomized_windows(val_execution, contract)
    dev_m, val_m = metrics(dev_execs[selected_threshold]), metrics(val_execution)
    robust = bool(not windows.empty and (windows.mean_net_return_10bps > 0).mean() >= .65 and (windows.mean_net_return_20bps > 0).mean() >= .65 and val_m["mean_net_return_10bps"] > 0 and val_m["mean_net_return_20bps"] > 0)
    decision = "PASS_CANDIDATE_READY_FOR_CONFIRMATION" if robust else "FAIL_NO_ROBUST_EDGE"
    summary = {"research_id": NAME, "iteration_id": "GEN2_ITERATION_006_VIX_PRIOR_DAY_REGIME_CHALLENGER", "parent_iteration": "GEN2_ITERATION_005_SOXX_ONLY_FACTOR_ABLATION", "hypothesis": "CBOE VIX values made available before the decision date can identify SOXX volatility regimes where the existing PIT directional features have better post-cost execution performance.", "changed_component": "Added only validated prior-day CBOE VIX return, percentile, and two prior-day regime flags; no intraday VIX, split, label, cost, execution, or threshold-grid change.", "features": list(features), "vix_information_contract": "Each VIX feature has feature_information_cutoff strictly before trade_date; intraday VIX is unavailable and unused.", "selection_metric": "highest Development 10bps mean net return; deterministic lower threshold tie-break", "selected_threshold": selected_threshold, "development_threshold_trials": table.to_dict(orient="records"), "contract_sha256": contract["contract_sha256"], "confirmation_read_count": 0, "development_metrics": dev_m, "validation_metrics": val_m, "validation_auc": float(roc_auc_score(val.label_up_60m.astype(int), val.probability_up)), "validation_brier": float(brier_score_loss(val.label_up_60m.astype(int), val.probability_up)), "random_window_count": int(len(windows)), "positive_random_window_ratio_10bps": float((windows.mean_net_return_10bps > 0).mean()) if not windows.empty else None, "positive_random_window_ratio_20bps": float((windows.mean_net_return_20bps > 0).mean()) if not windows.empty else None, "decision": decision, "broker_action_allowed": False, "live_trading_allowed": False, "official_adoption_allowed": False, "research_only": True}
    table.to_csv(output / "generation2_iteration_006_development_threshold_trials.csv", index=False)
    windows.to_csv(output / "generation2_iteration_006_random_window_metrics.csv", index=False)
    write_json(output / "generation2_iteration_006_summary.json", summary)
    registry_path = output / "generation2_experiment_registry.csv"
    registry = pd.read_csv(registry_path)
    registry = pd.concat([registry, pd.DataFrame([{"iteration_id": summary["iteration_id"], "hypothesis": summary["hypothesis"], "changed_component": summary["changed_component"], "window_contract_sha256": contract["contract_sha256"], "tests": "focused pytest plus VIX prior-day PIT cutoff test", "decision": decision, "next_allowed_research": "Confirmation only if every pre-Confirmation gate passes; otherwise finalize the bounded Generation 2 negative result."}])], ignore_index=True)
    registry.to_csv(registry_path, index=False)
    write_json(output / "generation2_checkpoint.json", {"current_status": decision, "current_champion": "GEN2_ITERATION_006_VIX_PRIOR_DAY_REGIME_CHALLENGER" if robust else None, "last_completed_iteration": 6, "confirmation_read_count": 0, "completed_backtests": "Generation 2 baseline, data-quality repair, Development-only abstention, compact nonlinear challenger, SOXX-only ablation, and validated-prior-day VIX regime challenger", "known_failures": [] if robust else ["No completed Generation 2 candidate has cleared every predeclared post-cost Validation and randomized-OOS robustness gate."], "next_exact_action": "Freeze champion and evaluate Confirmation once." if robust else "Finalize Generation 2 as FAIL_NO_ROBUST_EDGE; Confirmation remains unread.", "exact_resume_command": "python scripts/v22/fast3_agent/generation2_research.py --phase vix-prior-day", "contract_sha256": contract["contract_sha256"]})
    return summary


def finalize_phase(output: Path) -> dict:
    """Write the terminal Generation 2 record without accessing Confirmation."""
    contract = json.loads((output / "generation2_split_contract.json").read_text(encoding="utf-8"))
    if contract.get("confirmation_read_count") != 0:
        raise RuntimeError("CONFIRMATION_ISOLATION_VIOLATION")
    registry = pd.read_csv(output / "generation2_experiment_registry.csv")
    if registry.decision.eq("PASS_CANDIDATE_READY_FOR_CONFIRMATION").any():
        raise RuntimeError("CONFIRMATION_REQUIRED_FOR_FROZEN_CHAMPION")
    vix_summary = json.loads((output / "generation2_iteration_006_summary.json").read_text(encoding="utf-8"))
    if vix_summary.get("decision") != "FAIL_NO_ROBUST_EDGE":
        raise RuntimeError("GENERATION2_TERMINAL_DECISION_NOT_ESTABLISHED")
    summary = {
        "research_id": NAME,
        "final_status": "FAIL_NO_ROBUST_EDGE",
        "final_decision": "GENERATION2_NO_PRECONFIRMATION_CANDIDATE_CLEARED_POST_COST_AND_CHRONOLOGICAL_ROBUSTNESS_GATES",
        "stop_reason": f"All {len(registry)} recorded Generation 2 candidates failed at least one fixed Validation net-expectancy or randomized chronological-window gate; Confirmation is prohibited.",
        "completed_iteration_count": int(len(registry)),
        "current_champion": None,
        "confirmation_read_count": 0,
        "contract_sha256": contract["contract_sha256"],
        "validation_period": {"start": contract["validation_start"], "end": contract["validation_end"]},
        "confirmation_period_unread": {"start": contract["confirmation_start"], "end": contract["confirmation_end"]},
        "final_registered_challenger": {key: vix_summary[key] for key in ("iteration_id", "decision", "selected_threshold", "validation_metrics", "positive_random_window_ratio_10bps", "positive_random_window_ratio_20bps", "random_window_count", "vix_information_contract")},
        "broker_action_allowed": False,
        "live_trading_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
        "prospective_shadow_allowed": False,
        "recommended_next_command": "NONE_FAST3_GENERATION2_RESEARCH_STOPPED",
        "output_paths": {"registry": str(output / "generation2_experiment_registry.csv"), "checkpoint": str(output / "generation2_final_checkpoint.json"), "report": str(output / "generation2_final_report.md")},
    }
    report = "\n".join((
        "# FAST3 Generation 2 final research report",
        "",
        "- FINAL_STATUS=FAIL_NO_ROBUST_EDGE",
        "- FINAL_DECISION=GENERATION2_NO_PRECONFIRMATION_CANDIDATE_CLEARED_POST_COST_AND_CHRONOLOGICAL_ROBUSTNESS_GATES",
        "- Confirmation read count: 0 (unread by design)",
        "- Prospective shadow allowed: false",
        "",
        "## Final registered challenger",
        "",
        f"- Iteration: {vix_summary['iteration_id']}",
        f"- Validation 10bps expectancy: {vix_summary['validation_metrics']['mean_net_return_10bps']:.10f}",
        f"- Validation 20bps expectancy: {vix_summary['validation_metrics']['mean_net_return_20bps']:.10f}",
        f"- Positive chronological windows: {vix_summary['positive_random_window_ratio_10bps']:.2%} at 10bps; {vix_summary['positive_random_window_ratio_20bps']:.2%} at 20bps.",
        "",
        "The VIX inputs were daily prior-day features with strictly prior information cutoffs. Intraday VIX was unavailable and was not substituted. No model, threshold, or split was adjusted after Validation.",
        "",
        "## Safety",
        "",
        "No orders were generated. Broker action, live trading, official adoption, and prospective shadow remain disabled.",
        "",
    ))
    write_json(output / "generation2_final_summary.json", summary)
    (output / "generation2_final_report.md").write_text(report, encoding="utf-8")
    checkpoint = {"current_status": summary["final_status"], "current_champion": None, "last_completed_iteration": 6, "confirmation_read_count": 0, "completed_backtests": f"{len(registry)} recorded Generation 2 Development/Validation candidates", "known_failures": [summary["stop_reason"]], "next_exact_action": "No permitted continuation in Generation 2; await genuinely new future data for a separate generation.", "exact_resume_command": "NONE_FAST3_GENERATION2_RESEARCH_STOPPED", "contract_sha256": contract["contract_sha256"]}
    write_json(output / "generation2_final_checkpoint.json", checkpoint)
    write_json(output / "generation2_checkpoint.json", checkpoint)
    return {"decision": summary["final_status"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("audit", "research", "abstention", "nonlinear", "soxx-only", "vix-prior-day", "finalize"), required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--canonical-root", default=str(CANONICAL))
    args = parser.parse_args()
    output = Path(args.output_dir); output.mkdir(parents=True, exist_ok=True)
    if args.phase == "audit":
        result = audit_phase(output, Path(args.canonical_root))
    elif args.phase == "research":
        result = research_phase(output, Path(args.canonical_root))
    elif args.phase == "abstention":
        result = abstention_phase(output, Path(args.canonical_root))
    elif args.phase == "nonlinear":
        result = nonlinear_phase(output, Path(args.canonical_root))
    elif args.phase == "soxx-only":
        result = soxx_only_ablation_phase(output, Path(args.canonical_root))
    elif args.phase == "vix-prior-day":
        result = vix_prior_day_phase(output, Path(args.canonical_root), VIX_PRIOR_DAY_FEATURES)
    else:
        result = finalize_phase(output)
    print("FINAL_STATUS=" + (result.get("decision") or result.get("contract_status")))
    print("CONFIRMATION_READ_COUNT=0")
    print("OUTPUT_DIRECTORY=" + str(output))


if __name__ == "__main__":
    main()
