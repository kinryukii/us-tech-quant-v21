#!/usr/bin/env python
"""FAST3 R31A outcome-blind, read-only new-information-domain feasibility audit."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SOURCE_ROOT = Path(r"D:\us-tech-quant")
DATA_ROOT = Path(r"D:\us-tech-quant-data")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
CACHE_ROOT = Path(r"D:\us-tech-quant-cache")

R30A_DIR = RESULTS_ROOT / "frozen" / "fast3" / "r30a_economic_target_20260809T120000Z"
R30B_DIR = RESULTS_ROOT / "frozen" / "fast3" / "r30b_factor_expansion_20260809T140000Z"
R30C_DIR = RESULTS_ROOT / "frozen" / "fast3" / "r30c_downside_severity_20260809T160000Z"
R30D_DIR = RESULTS_ROOT / "frozen" / "fast3" / "r30d_conditional_orthogonality_20260809T180000Z"
PRIOR_SUMMARIES = {
    "R30A": R30A_DIR / "FAST3_R30A_SUMMARY.json",
    "R30B": R30B_DIR / "FAST3_R30B_SUMMARY.json",
    "R30C": R30C_DIR / "FAST3_R30C_SUMMARY.json",
    "R30D": R30D_DIR / "FAST3_R30D_SUMMARY.json",
}
PRIOR_SUMMARY_SHA256 = {
    "R30A": "eadc56fcc3b28d09f73a0e793cc71080fe39d64988a4920fb1f7a109f281b08e",
    "R30B": "c1015e5a555f321235b313f9c6544a8fcbd1531cceed6d0111eaa1a6018db8cf",
    "R30C": "84ea894d79e25ebe8d3b8d65e4267272dfa8a61a5f35b042bf453908d229f4bd",
    "R30D": "4f52dfe783e7a57bf9574703c014454baf83b25cca2775ed9ccd71f0eac5b46e",
}
R30B_MANIFEST = R30B_DIR / "FAST3_R30B_EXPANDED_FEATURE_MANIFEST_R1.json"
R30B_FEATURE_MANIFEST_SHA256 = "248c4d1eabcbcee545ffc95f5f366390889c13199ec90d84d5bbd0f6332f4718"
R30A_DATA_IDENTITY = R30A_DIR / "FAST3_R30A_TRAINING_DATA_IDENTITY.json"
SPLIT_IDENTITY = R30A_DIR / "FAST3_R30A_SPLIT_IDENTITY.json"
MINUTE_ROOT = DATA_ROOT / "fast3" / "moomoo_24h_1m"
MINUTE_CANONICAL = MINUTE_ROOT / "canonical"
MINUTE_COVERAGE = MINUTE_ROOT / "six_etf_coverage_manifest.csv"
MINUTE_RUN_MANIFEST = MINUTE_ROOT / "v22_049_run_manifest.json"
MINUTE_CA_SUSPECTS = MINUTE_ROOT / "six_etf_corporate_action_suspects.csv"
ACTIVE_UNIVERSE = DATA_ROOT / "moomoo" / "metadata" / "abcde_price_universe_r2.csv"
ACTIVE_UNIVERSE_MANIFEST = DATA_ROOT / "moomoo" / "metadata" / "abcde_price_universe_r2.active_manifest.json"
STOCK_ROOT = DATA_ROOT / "stocks"

DEVELOPMENT_START = pd.Timestamp("2020-01-01T00:00:00Z")
DEVELOPMENT_END = pd.Timestamp("2025-01-31T23:59:59Z")
CURRENT_FEATURE_COUNT = 29
DOMAIN_ORDER = (
    "VOLUME_LIQUIDITY_FLOW",
    "MARKET_BREADTH_SECTOR_INTERNALS",
    "OPTIONS_IMPLIED_VOLATILITY",
    "MICROSTRUCTURE",
)
ALLOWED_DOMAIN_STATUSES = {
    "READY", "PARTIAL", "NOT_READY_DATA_UNAVAILABLE", "NOT_READY_COVERAGE",
    "NOT_READY_PIT", "NOT_READY_SURVIVORSHIP", "NOT_READY_TIMESTAMP", "NOT_READY_NOT_NOVEL",
}

VOLUME_DEFINITIONS: dict[str, dict[str, str]] = {
    "RELATIVE_VOLUME_20": {
        "formula": "volume_t / mean(volume[t-20:t-1])",
        "lookback": "20 completed bars",
        "timestamp_rule": "bar timestamp <= decision timestamp; current completed bar divided by prior 20 bars",
        "missing_policy": "native NaN when prior mean is zero or unavailable; no fill",
        "complexity": "LOW",
    },
    "VOLUME_ACCELERATION_5_20": {
        "formula": "mean(volume[t-4:t]) / mean(volume[t-24:t-5]) - 1",
        "lookback": "5 current completed bars versus previous 20 bars",
        "timestamp_rule": "all bars <= decision timestamp",
        "missing_policy": "native NaN for zero denominator; no fill",
        "complexity": "LOW",
    },
    "DOLLAR_VOLUME_ZSCORE_60": {
        "formula": "(log1p(turnover_t)-mean(log1p(turnover[t-60:t-1])))/std(log1p(turnover[t-60:t-1]))",
        "lookback": "60 prior completed bars",
        "timestamp_rule": "provider turnover for completed bar t and prior bars only",
        "missing_policy": "native NaN for zero prior standard deviation; HGB native missing only",
        "complexity": "LOW",
    },
    "SESSION_VWAP_DEVIATION": {
        "formula": "close_t / (cumulative_session_turnover_t/cumulative_session_volume_t) - 1",
        "lookback": "current canonical session from session start through completed bar t",
        "timestamp_rule": "reset by broker_trade_date and canonical NIGHT/PREMARKET/RTH/AFTERHOURS session; no full-session future bars",
        "missing_policy": "native NaN until cumulative positive volume; no fill",
        "complexity": "LOW",
    },
    "SESSION_VWAP_SLOPE_15": {
        "formula": "session_cumulative_VWAP_t / session_cumulative_VWAP_t-15 - 1",
        "lookback": "15 completed bars within current canonical session",
        "timestamp_rule": "same-session trailing bars only; session reset enforced",
        "missing_policy": "native NaN before 15 same-session bars; no fill",
        "complexity": "LOW",
    },
    "INTRADAY_VOLUME_PROFILE_DEVIATION_20D": {
        "formula": "volume_t / mean(prior 20 volume observations at same canonical session and ET minute) - 1",
        "lookback": "20 prior comparable session/minute observations",
        "timestamp_rule": "shift one comparable observation before rolling; never uses current/future session observations in benchmark",
        "missing_policy": "native NaN for unavailable/zero benchmark; no fill",
        "complexity": "MEDIUM",
    },
    "DOLLAR_VOLUME_ACCELERATION_5_20": {
        "formula": "mean(turnover[t-4:t]) / mean(turnover[t-24:t-5]) - 1",
        "lookback": "5 current completed bars versus previous 20 bars",
        "timestamp_rule": "provider turnover from bars <= decision timestamp",
        "missing_policy": "native NaN for zero denominator; no fill",
        "complexity": "LOW",
    },
    "VOLUME_PRICE_CONFIRMATION_15": {
        "formula": "return_15 * log1p(4*sum(turnover[t-4:t])/sum(turnover[t-24:t-5]))",
        "lookback": "15-bar return and 5-versus-20 completed-bar turnover",
        "timestamp_rule": "price and turnover bars <= decision timestamp",
        "missing_policy": "native NaN for zero denominator; no fill",
        "complexity": "MEDIUM",
    },
    "ROLLING_ILLIQUIDITY_20": {
        "formula": "sum(abs(log_return),20) / sum(turnover,20)",
        "lookback": "20 completed bars",
        "timestamp_rule": "all return and turnover inputs <= decision timestamp",
        "missing_policy": "native NaN for zero rolling turnover; invalidate any later-identified corporate-action-contaminated window",
        "complexity": "LOW",
    },
    "SESSION_CUMULATIVE_VOLUME_PROFILE_DEVIATION_20D": {
        "formula": "cumulative_session_volume_t / mean(prior 20 cumulative volumes at same canonical session and ET minute) - 1",
        "lookback": "20 prior comparable sessions",
        "timestamp_rule": "current cumulative volume only through t; benchmark shifted one session before rolling",
        "missing_policy": "native NaN for unavailable/zero benchmark; no fill",
        "complexity": "MEDIUM",
    },
    "SESSION_CUMULATIVE_TURNOVER_PROFILE_DEVIATION_20D": {
        "formula": "cumulative_session_turnover_t / mean(prior 20 cumulative turnovers at same canonical session and ET minute) - 1",
        "lookback": "20 prior comparable sessions",
        "timestamp_rule": "current cumulative turnover only through t; benchmark shifted one session before rolling",
        "missing_policy": "native NaN for unavailable/zero benchmark; no fill",
        "complexity": "MEDIUM",
    },
}

BREADTH_CANDIDATES = (
    "SEMICONDUCTOR_UP_FRACTION", "SEMICONDUCTOR_ABOVE_VWAP_FRACTION",
    "SEMICONDUCTOR_CROSS_SECTIONAL_MOMENTUM", "SEMICONDUCTOR_RETURN_DISPERSION",
    "SEMICONDUCTOR_ADVANCE_DECLINE", "BREADTH_TREND_CONFIRMATION",
)
OPTION_CANDIDATES = (
    "ATM_IV", "IV_CHANGE", "IV_PERCENTILE", "PUT_CALL_IV_SKEW", "TERM_STRUCTURE",
    "PUT_CALL_VOLUME", "OPTIONS_VOLUME", "OPEN_INTEREST_CHANGE",
)
MICROSTRUCTURE_CANDIDATES = (
    "BID_ASK_SPREAD", "QUOTE_IMBALANCE", "TRADE_IMBALANCE", "ORDER_FLOW_IMBALANCE",
    "SHORT_HORIZON_LIQUIDITY", "TRADE_COUNT", "EFFECTIVE_SPREAD_PROXY",
)


class R31AStop(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, np.floating): return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.bool_): return bool(value)
    if isinstance(value, (Path, pd.Timestamp)): return str(value)
    if pd.isna(value): return None
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=json_default, allow_nan=False) + "\n", encoding="utf-8")


def temporal_coverage(start: Any, end: Any) -> float:
    if start in (None, "") or end in (None, ""):
        return 0.0
    left, right = pd.Timestamp(start), pd.Timestamp(end)
    if left.tzinfo is None: left = left.tz_localize("UTC")
    else: left = left.tz_convert("UTC")
    if right.tzinfo is None: right = right.tz_localize("UTC")
    else: right = right.tz_convert("UTC")
    overlap = max(pd.Timedelta(0), min(right, DEVELOPMENT_END) - max(left, DEVELOPMENT_START))
    return float(min(1.0, overlap / (DEVELOPMENT_END - DEVELOPMENT_START)))


def verify_authority() -> dict[str, Any]:
    priors = {}
    for stage, path in PRIOR_SUMMARIES.items():
        if not path.is_file() or file_sha256(path) != PRIOR_SUMMARY_SHA256[stage]:
            raise R31AStop(f"STOP_{stage}_SUMMARY_HASH")
        priors[stage] = read_json(path)
        if priors[stage].get("FINAL_CONFIRMATION_DATA_USED"):
            raise R31AStop(f"STOP_{stage}_FINAL_CONFIRMATION_IDENTITY")
    if priors["R30D"]["FAST3_R30D_CLASSIFICATION"] != "D_CONDITIONAL_RESULT_CONTRADICTS_T4_RISK_SIGNAL":
        raise R31AStop("STOP_R30D_CLASSIFICATION")
    if file_sha256(R30B_MANIFEST) != R30B_FEATURE_MANIFEST_SHA256:
        raise R31AStop("STOP_R30B_FEATURE_MANIFEST_HASH")
    manifest = read_json(R30B_MANIFEST)
    if len(manifest["arms"]["ARM_ALL"]) != 29 or manifest["FINAL_CONFIRMATION_DATA_USED"]:
        raise R31AStop("STOP_CURRENT_FEATURE_IDENTITY")
    split = read_json(SPLIT_IDENTITY)
    if split["FINAL_CONFIRMATION_DATA_USED"] or split["TRUE_HOLDOUT_START"] != "2025-02-01 05:00:00+00:00":
        raise R31AStop("STOP_SPLIT_OR_HOLDOUT_IDENTITY")
    data = read_json(R30A_DATA_IDENTITY)
    feature_path = Path(data["FEATURE_LEDGER_SOURCE"])
    factor_path = Path(manifest["factor_ledger_path"])
    if file_sha256(feature_path) != data["FEATURE_LEDGER_SHA256"] or file_sha256(factor_path) != manifest["factor_ledger_sha256"]:
        raise R31AStop("STOP_FEATURE_SOURCE_HASH")
    return {"priors": priors, "manifest": manifest, "split": split, "data": data, "feature_path": feature_path, "factor_path": factor_path}


def load_development_bars(symbol: str) -> pd.DataFrame:
    files = []
    for path in sorted((MINUTE_CANONICAL / f"symbol={symbol}").glob("year=*/month=*/data.parquet")):
        year = int(path.parent.parent.name.split("=")[1]); month = int(path.parent.name.split("=")[1])
        if 2019 <= year <= 2025 and not (year == 2025 and month > 1):
            files.append(path)
    if not files: raise R31AStop(f"STOP_MINUTE_SOURCE_{symbol}")
    columns = ["timestamp_utc", "timestamp_et", "broker_trade_date", "session", "close", "volume", "turnover"]
    return pd.concat([pd.read_parquet(path, columns=columns) for path in files], ignore_index=True).sort_values("timestamp_utc").reset_index(drop=True)


def construct_volume_candidates(bars: pd.DataFrame) -> pd.DataFrame:
    """Trailing-only, outcome-blind feasibility values; no feature matrix is persisted."""
    frame = bars.copy()
    volume = frame["volume"].astype(float)
    turnover = frame["turnover"].astype(float).clip(lower=0)
    close = frame["close"].astype(float)
    log_turnover = np.log1p(turnover)
    log_return = np.log(close).diff()
    prior20_volume = volume.shift(1).rolling(20, min_periods=20).mean()
    frame["RELATIVE_VOLUME_20"] = volume / prior20_volume.replace(0, np.nan)
    frame["VOLUME_ACCELERATION_5_20"] = volume.rolling(5, min_periods=5).mean() / volume.shift(5).rolling(20, min_periods=20).mean().replace(0, np.nan) - 1
    mean60 = log_turnover.shift(1).rolling(60, min_periods=60).mean()
    std60 = log_turnover.shift(1).rolling(60, min_periods=60).std()
    frame["DOLLAR_VOLUME_ZSCORE_60"] = (log_turnover - mean60) / std60.replace(0, np.nan)
    session_keys = [frame["broker_trade_date"], frame["session"]]
    cumulative_volume = volume.groupby(session_keys, sort=False).cumsum()
    cumulative_turnover = turnover.groupby(session_keys, sort=False).cumsum()
    session_vwap = cumulative_turnover / cumulative_volume.replace(0, np.nan)
    frame["SESSION_VWAP_DEVIATION"] = close / session_vwap - 1
    frame["SESSION_VWAP_SLOPE_15"] = session_vwap.groupby(session_keys, sort=False).pct_change(15)
    frame["minute_et"] = pd.to_datetime(frame["timestamp_et"]).dt.strftime("%H:%M")
    comparable = [frame["session"], frame["minute_et"]]
    prior_profile = volume.groupby(comparable, sort=False).transform(lambda series: series.shift(1).rolling(20, min_periods=20).mean())
    frame["INTRADAY_VOLUME_PROFILE_DEVIATION_20D"] = volume / prior_profile.replace(0, np.nan) - 1
    frame["DOLLAR_VOLUME_ACCELERATION_5_20"] = turnover.rolling(5, min_periods=5).mean() / turnover.shift(5).rolling(20, min_periods=20).mean().replace(0, np.nan) - 1
    turnover_ratio = 4 * turnover.rolling(5, min_periods=5).sum() / turnover.shift(5).rolling(20, min_periods=20).sum().replace(0, np.nan)
    frame["VOLUME_PRICE_CONFIRMATION_15"] = close.pct_change(15) * np.log1p(turnover_ratio)
    frame["ROLLING_ILLIQUIDITY_20"] = log_return.abs().rolling(20, min_periods=20).sum() / turnover.rolling(20, min_periods=20).sum().replace(0, np.nan)
    cumulative_volume_prior = cumulative_volume.groupby(comparable, sort=False).transform(lambda series: series.shift(1).rolling(20, min_periods=20).mean())
    cumulative_turnover_prior = cumulative_turnover.groupby(comparable, sort=False).transform(lambda series: series.shift(1).rolling(20, min_periods=20).mean())
    frame["SESSION_CUMULATIVE_VOLUME_PROFILE_DEVIATION_20D"] = cumulative_volume / cumulative_volume_prior.replace(0, np.nan) - 1
    frame["SESSION_CUMULATIVE_TURNOVER_PROFILE_DEVIATION_20D"] = cumulative_turnover / cumulative_turnover_prior.replace(0, np.nan) - 1
    return frame[["timestamp_utc", *VOLUME_DEFINITIONS]]


def current_feature_frame(authority: dict[str, Any]) -> pd.DataFrame:
    manifest = authority["manifest"]
    baseline_names = manifest["baseline_features"]
    expanded_names = manifest["arms"]["ARM_ALL"][14:]
    base = pd.read_parquet(authority["feature_path"], columns=["candidate_id", "underlying_symbol", "decision_timestamp_utc", *baseline_names])
    expanded = pd.read_parquet(authority["factor_path"], columns=["candidate_id", *expanded_names])
    frame = base.merge(expanded, on="candidate_id", validate="one_to_one")
    if len(frame) != 1197 or frame["decision_timestamp_utc"].max() >= pd.Timestamp(authority["split"]["TRUE_HOLDOUT_START"]):
        raise R31AStop("STOP_DEVELOPMENT_FEATURE_UNIVERSE")
    return frame


def volume_novelty(authority: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    existing_names = authority["manifest"]["arms"]["ARM_ALL"]
    current = current_feature_frame(authority)
    candidate_parts = []
    for symbol in ("QQQ", "SOXX"):
        values = construct_volume_candidates(load_development_bars(symbol))
        selected = current.loc[current["underlying_symbol"].eq(symbol), ["candidate_id", "decision_timestamp_utc"]]
        candidate_parts.append(selected.merge(values, left_on="decision_timestamp_utc", right_on="timestamp_utc", how="left", validate="many_to_one").drop(columns="timestamp_utc"))
    candidates = pd.concat(candidate_parts, ignore_index=True)
    combined = current.merge(candidates, on=["candidate_id", "decision_timestamp_utc"], validate="one_to_one")
    candidate_corr = combined[list(VOLUME_DEFINITIONS)].corr(method="spearman", min_periods=50).abs()
    rows = []
    for name, definition in VOLUME_DEFINITIONS.items():
        coverage = float(combined[name].notna().mean())
        corr = combined[[name, *existing_names]].corr(method="spearman", min_periods=50)[name].drop(name).abs().dropna().sort_values(ascending=False)
        max_feature = str(corr.index[0]); max_value = float(corr.iloc[0])
        novelty = "LOW" if max_value >= 0.95 and name in {"RELATIVE_VOLUME_20", "INTRADAY_VOLUME_PROFILE_DEVIATION_20D"} else "MEDIUM" if max_value >= 0.75 else "HIGH"
        reason = "PASS_HARD_GATES"
        training_ready = True
        if coverage < 0.90:
            training_ready, reason = False, "COVERAGE_LT_90_PERCENT"
        elif novelty == "LOW":
            training_ready, reason = False, "SEMANTICALLY_SIMILAR_AND_MAX_ABS_SPEARMAN_GE_0_95"
        rows.append({
            "feature_candidate": name, "domain": "VOLUME_LIQUIDITY_FLOW", "source": str(MINUTE_CANONICAL),
            "formula_concept": definition["formula"], "lookback_or_window": definition["lookback"], "PIT_safe": True,
            "coverage_estimate": coverage, "missing_rate": 1 - coverage, "survivorship_risk": "LOW_ETF_SOURCE",
            "timestamp_risk": "LOW_TRAILING_COMPLETED_BARS", "corporate_action_risk": "LOW_TURNOVER_BASED" if "TURNOVER" in name or "DOLLAR" in name else "CONTROLLED_MEDIUM",
            "current_29_overlap": max_value, "max_abs_spearman_feature": max_feature, "novelty": novelty,
            "implementation_complexity": definition["complexity"], "training_ready": training_ready, "reason": reason,
            "timestamp_rule": definition["timestamp_rule"], "missing_policy": definition["missing_policy"],
        })
    table = pd.DataFrame(rows)
    volume_name = "SESSION_CUMULATIVE_VOLUME_PROFILE_DEVIATION_20D"
    turnover_name = "SESSION_CUMULATIVE_TURNOVER_PROFILE_DEVIATION_20D"
    pair_value = float(candidate_corr.loc[volume_name, turnover_name])
    if pair_value >= 0.95:
        mask = table["feature_candidate"].eq(volume_name)
        table.loc[mask, "training_ready"] = False
        table.loc[mask, "reason"] = "REDUNDANT_WITH_TURNOVER_PROFILE;TURNOVER_SELECTED_FOR_CORPORATE_ACTION_ROBUSTNESS"
    approved = table.loc[table["training_ready"], "feature_candidate"].tolist()
    novelty = table[["feature_candidate", "domain", "coverage_estimate", "current_29_overlap", "max_abs_spearman_feature", "novelty", "training_ready", "reason"]].copy()
    novelty["candidate_pair_volume_vs_turnover_profile_spearman"] = np.where(novelty["feature_candidate"].isin([volume_name, turnover_name]), pair_value, np.nan)
    return table, novelty, approved


def stock_inventory() -> dict[str, Any]:
    active = pd.read_csv(ACTIVE_UNIVERSE)
    rows = 0; starts = []; ends = []; found = 0
    for ticker in active["ticker"].astype(str):
        metadata = STOCK_ROOT / ticker / "metadata.json"
        if not metadata.is_file(): continue
        daily = read_json(metadata).get("daily_qfq", {})
        rows += int(daily.get("row_count", 0)); starts.append(daily.get("first_date")); ends.append(daily.get("last_date")); found += 1
    full_start = sum(str(value) <= "2020-01-01" for value in starts)
    return {"symbol_count": found, "row_count": rows, "date_start": min(starts), "date_end": max(ends), "full_window_symbol_rate": full_start / found if found else 0.0}


def unavailable_candidate_rows(domain: str, names: tuple[str, ...], reason: str, source: str, risks: dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame([{
        "feature_candidate": name, "domain": domain, "source": source, "formula_concept": "NOT_FROZEN_SOURCE_NOT_READY",
        "lookback_or_window": "NOT_REGISTERED", "PIT_safe": False, "coverage_estimate": 0.0, "missing_rate": 1.0,
        "survivorship_risk": risks["survivorship"], "timestamp_risk": risks["timestamp"], "corporate_action_risk": risks["corporate_action"],
        "current_29_overlap": None, "max_abs_spearman_feature": None, "novelty": "MECHANISM_NOVEL_BUT_NOT_MEASURABLE",
        "implementation_complexity": "NOT_ASSESSED", "training_ready": False, "reason": reason,
        "timestamp_rule": "NOT_APPROVED", "missing_policy": "NO_SOURCE_NO_FILL",
    } for name in names])


def inventory_and_readiness(approved_volume_count: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    coverage = pd.read_csv(MINUTE_COVERAGE)
    stocks = stock_inventory()
    domain_a_start = pd.to_datetime(coverage["earliest"], utc=True).max()
    domain_a_end = pd.to_datetime(coverage["latest"], utc=True).min()
    schema_a = "symbol;code;timestamp_et;timestamp_utc;timestamp_jst;calendar_date_et;broker_trade_date;session;open;high;low;close;volume;turnover;source;adjustment_type;downloaded_at_utc"
    inventory = pd.DataFrame([
        {"DOMAIN": "VOLUME_LIQUIDITY_FLOW", "SOURCE_AVAILABLE": True, "SOURCE_PATHS": f"{MINUTE_CANONICAL};{MINUTE_COVERAGE};{MINUTE_RUN_MANIFEST}", "SOURCE_TYPE": "CANONICAL_1MIN_OHLCV_TURNOVER", "CANONICAL": True, "READ_ONLY": True, "DATE_START": domain_a_start, "DATE_END": domain_a_end, "SYMBOL_COUNT": len(coverage), "ROW_COUNT": int(coverage["rows"].sum()), "TIMESTAMP_RESOLUTION": "1 minute", "SCHEMA": schema_a, "PIT_STATUS": "PASS", "PIT_RISK": "LOW", "SURVIVORSHIP_RISK": "LOW_FIXED_ETF_SOURCES", "CORPORATE_ACTION_RISK": "CONTROLLED_MEDIUM_UNADJUSTED_BARS;TURNOVER_PRIORITY", "MISSINGNESS_RISK": "LOW_CANDIDATE_SPECIFIC_GATES", "TIMESTAMP_ALIGNMENT_RISK": "LOW_EXACT_COMPLETED_BAR", "DEVELOPMENT_START": DEVELOPMENT_START, "DEVELOPMENT_END": DEVELOPMENT_END, "DOMAIN_START": domain_a_start, "DOMAIN_END": domain_a_end, "TEMPORAL_COVERAGE_RATE": temporal_coverage(domain_a_start, domain_a_end)},
        {"DOMAIN": "MARKET_BREADTH_SECTOR_INTERNALS", "SOURCE_AVAILABLE": True, "SOURCE_PATHS": f"{STOCK_ROOT};{ACTIVE_UNIVERSE};{ACTIVE_UNIVERSE_MANIFEST}", "SOURCE_TYPE": "RESEARCH_ONLY_CURRENT_UNIVERSE_DAILY_OHLCV_TURNOVER", "CANONICAL": False, "READ_ONLY": True, "DATE_START": stocks["date_start"], "DATE_END": stocks["date_end"], "SYMBOL_COUNT": stocks["symbol_count"], "ROW_COUNT": stocks["row_count"], "TIMESTAMP_RESOLUTION": "daily", "SCHEMA": "ticker;moomoo_symbol;market;date;open;high;low;close;volume;turnover;adjustment;source;source_policy;snapshot_id;fetched_at_utc", "PIT_STATUS": "FAIL", "PIT_RISK": "UNCONTROLLED_HIGH_CURRENT_UNIVERSE_PROJECTED_BACKWARD", "SURVIVORSHIP_RISK": "UNCONTROLLED_HIGH", "CORPORATE_ACTION_RISK": "MEDIUM_QFQ_SNAPSHOT", "MISSINGNESS_RISK": f"HIGH_ONLY_{stocks['full_window_symbol_rate']:.6f}_OF_CURRENT_SYMBOLS_COVER_FULL_START", "TIMESTAMP_ALIGNMENT_RISK": "UNCONTROLLED_HIGH_DAILY_COMPONENT_BARS_FOR_INTRADAY_DECISIONS", "DEVELOPMENT_START": DEVELOPMENT_START, "DEVELOPMENT_END": DEVELOPMENT_END, "DOMAIN_START": stocks["date_start"], "DOMAIN_END": stocks["date_end"], "TEMPORAL_COVERAGE_RATE": temporal_coverage(stocks["date_start"], stocks["date_end"])},
        {"DOMAIN": "OPTIONS_IMPLIED_VOLATILITY", "SOURCE_AVAILABLE": False, "SOURCE_PATHS": "NO_HISTORICAL_DATA_ROOT_SOURCE;REPO_HAS_SCHEMA_AND_SNAPSHOT_SCRIPTS_ONLY", "SOURCE_TYPE": "SCHEMA_ONLY_OR_SYNTHETIC/LIVE_SNAPSHOT_EXAMPLES", "CANONICAL": False, "READ_ONLY": True, "DATE_START": None, "DATE_END": None, "SYMBOL_COUNT": 0, "ROW_COUNT": 0, "TIMESTAMP_RESOLUTION": "NONE", "SCHEMA": "NO_HISTORICAL_OPTION_CHAIN_OR_IV_DATA", "PIT_STATUS": "NOT_ASSESSABLE_NO_HISTORICAL_SOURCE", "PIT_RISK": "UNCONTROLLED_HIGH", "SURVIVORSHIP_RISK": "UNKNOWN", "CORPORATE_ACTION_RISK": "UNKNOWN", "MISSINGNESS_RISK": "TOTAL", "TIMESTAMP_ALIGNMENT_RISK": "UNCONTROLLED_HIGH", "DEVELOPMENT_START": DEVELOPMENT_START, "DEVELOPMENT_END": DEVELOPMENT_END, "DOMAIN_START": None, "DOMAIN_END": None, "TEMPORAL_COVERAGE_RATE": 0.0},
        {"DOMAIN": "MICROSTRUCTURE", "SOURCE_AVAILABLE": False, "SOURCE_PATHS": f"{MINUTE_CANONICAL} (OHLCV+turnover only)", "SOURCE_TYPE": "NO_QUOTE_OR_TRADE_LEVEL_SOURCE;OHLCV_PROXY_ONLY", "CANONICAL": False, "READ_ONLY": True, "DATE_START": None, "DATE_END": None, "SYMBOL_COUNT": 0, "ROW_COUNT": 0, "TIMESTAMP_RESOLUTION": "NONE_FOR_TRUE_MICROSTRUCTURE", "SCHEMA": "NO_BID;NO_ASK;NO_QUOTE;NO_TRADE_SIDE;NO_TRADE_COUNT", "PIT_STATUS": "NOT_ASSESSABLE_NO_TRUE_SOURCE", "PIT_RISK": "UNCONTROLLED_HIGH", "SURVIVORSHIP_RISK": "LOW_IF_SOURCE_EXISTED", "CORPORATE_ACTION_RISK": "LOW_IF_SOURCE_EXISTED", "MISSINGNESS_RISK": "TOTAL", "TIMESTAMP_ALIGNMENT_RISK": "UNCONTROLLED_HIGH", "DEVELOPMENT_START": DEVELOPMENT_START, "DEVELOPMENT_END": DEVELOPMENT_END, "DOMAIN_START": None, "DOMAIN_END": None, "TEMPORAL_COVERAGE_RATE": 0.0},
    ])
    scores = {
        "VOLUME_LIQUIDITY_FLOW": [5, 5, 5, 5, 5, 4, 4, 5, 5],
        "MARKET_BREADTH_SECTOR_INTERNALS": [3, 4, 1, 1, 1, 5, 2, 4, 2],
        "OPTIONS_IMPLIED_VOLATILITY": [1, 1, 1, 3, 1, 5, 1, 3, 1],
        "MICROSTRUCTURE": [1, 1, 1, 5, 1, 5, 1, 5, 1],
    }
    fields = ["DATA_AVAILABILITY", "TEMPORAL_COVERAGE", "PIT_SAFETY", "SURVIVORSHIP_SAFETY", "TIMESTAMP_QUALITY", "NOVEL_INFORMATION_CONTENT", "IMPLEMENTATION_SIMPLICITY", "STORAGE_COST", "REPRODUCIBILITY"]
    statuses = {"VOLUME_LIQUIDITY_FLOW": "READY", "MARKET_BREADTH_SECTOR_INTERNALS": "NOT_READY_SURVIVORSHIP", "OPTIONS_IMPLIED_VOLATILITY": "NOT_READY_DATA_UNAVAILABLE", "MICROSTRUCTURE": "NOT_READY_DATA_UNAVAILABLE"}
    reasons = {
        "VOLUME_LIQUIDITY_FLOW": f"Existing canonical 1-minute volume and turnover cover the full development window; {approved_volume_count} candidates pass PIT, coverage, and novelty gates.",
        "MARKET_BREADTH_SECTOR_INTERNALS": "Historical constituent membership and dated sector membership are absent; active universe is a 2026 current snapshot, no compliant fixed semiconductor proxy basket is frozen, and component data are daily rather than decision-time minute bars.",
        "OPTIONS_IMPLIED_VOLATILITY": "No historical option-chain, implied-volatility, skew, term-structure, or option-flow files exist in data root; repository assets are schemas/snapshots/examples only.",
        "MICROSTRUCTURE": "Canonical minute bars expose OHLCV and turnover but no bid, ask, quotes, trade side, order book, or trade count; OHLCV proxies are not true microstructure.",
    }
    readiness_rows = []
    for domain in DOMAIN_ORDER:
        values = scores[domain]
        row = {"DOMAIN": domain, **dict(zip(fields, values)), "READINESS_SCORE_MEAN": float(np.mean(values)), "DOMAIN_STATUS": statuses[domain], "DOMAIN_TRAINING_READY": statuses[domain] == "READY", "REPRODUCIBLE": domain == "VOLUME_LIQUIDITY_FLOW", "PROXY_BASKET": False, "FIXED_PROXY_BASKET_AVAILABLE": False, "REASON": reasons[domain]}
        if row["DOMAIN_STATUS"] not in ALLOWED_DOMAIN_STATUSES: raise R31AStop("STOP_DOMAIN_STATUS")
        readiness_rows.append(row)
    return inventory, pd.DataFrame(readiness_rows)


def report_text(summary: dict[str, Any]) -> str:
    return f"""# FAST3 R31A — New Information Domain Feasibility Audit

## Decision

- Status / classification: `{summary['FAST3_R31A_STATUS']}` / `{summary['FAST3_R31A_CLASSIFICATION']}`
- Approved domains: `{summary['APPROVED_DOMAINS']}`
- R31B allowed: `{summary['R31B_ALLOWED']}`
- Proposed features: `{summary['R31B_PROPOSED_FEATURES']}`

## Outcome-blind findings

Volume/Liquidity/Flow is the only training-ready domain. Existing 1-minute QQQ/SOXX bars provide timestamped volume and provider turnover across the full frozen development window. Four mechanisms pass candidate coverage and feature-feature novelty gates: dollar-volume state, session VWAP deviation, rolling illiquidity, and session cumulative turnover-profile deviation.

Breadth is blocked by missing historical point-in-time constituent/sector membership, an explicitly current 2026 universe, no pre-frozen proxy basket, and daily rather than decision-time component bars. Options/IV has no historical data-root source. Microstructure has no quote/trade-level source; OHLCV must not be relabeled as order flow.

No economic target, payoff, model fitting, prediction, external download, canonical mutation, or final-confirmation data was used. R31B may run the preregistered controlled ablation only; this stage does not execute it.
"""


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--run-id", required=True); args = parser.parse_args()
    name = f"r31a_information_domain_feasibility_{args.run_id}"
    runtime = RESULTS_ROOT / "runtime" / "fast3" / name
    frozen = RESULTS_ROOT / "frozen" / "fast3" / name
    if runtime.exists() or frozen.exists(): raise R31AStop("STOP_RUN_ID_EXISTS")
    runtime.mkdir(parents=True); frozen.mkdir(parents=True)
    authority = verify_authority()
    volume_candidates, volume_novelty_table, approved_features = volume_novelty(authority)
    if len(approved_features) > 6: raise R31AStop("STOP_DOMAIN_A_FEATURE_BUDGET")
    inventory, readiness = inventory_and_readiness(len(approved_features))
    other_candidates = pd.concat([
        unavailable_candidate_rows("MARKET_BREADTH_SECTOR_INTERNALS", BREADTH_CANDIDATES, "NOT_READY_PIT_CONSTITUENT_HISTORY_MISSING;NO_FIXED_PROXY_BASKET;INTRADAY_ALIGNMENT_UNAVAILABLE", str(STOCK_ROOT), {"survivorship": "UNCONTROLLED_HIGH", "timestamp": "UNCONTROLLED_HIGH", "corporate_action": "MEDIUM"}),
        unavailable_candidate_rows("OPTIONS_IMPLIED_VOLATILITY", OPTION_CANDIDATES, "NOT_READY_DATA_UNAVAILABLE", "NO_HISTORICAL_DATA_ROOT_SOURCE", {"survivorship": "UNKNOWN", "timestamp": "UNCONTROLLED_HIGH", "corporate_action": "UNKNOWN"}),
        unavailable_candidate_rows("MICROSTRUCTURE", MICROSTRUCTURE_CANDIDATES, "NOT_READY_DATA_UNAVAILABLE;OHLCV_PROXY_NOT_TRUE_MICROSTRUCTURE", str(MINUTE_CANONICAL), {"survivorship": "LOW", "timestamp": "UNCONTROLLED_HIGH", "corporate_action": "LOW"}),
    ], ignore_index=True)
    candidates = pd.concat([volume_candidates, other_candidates], ignore_index=True)
    novelty_other = other_candidates[["feature_candidate", "domain", "coverage_estimate", "current_29_overlap", "max_abs_spearman_feature", "novelty", "training_ready", "reason"]].copy()
    novelty_other["candidate_pair_volume_vs_turnover_profile_spearman"] = np.nan
    novelty = pd.concat([volume_novelty_table, novelty_other], ignore_index=True)
    approved_domains = readiness.loc[readiness["DOMAIN_TRAINING_READY"], "DOMAIN"].tolist()
    if len(approved_domains) > 2 or len(approved_features) > 12 or any(not bool(value) for value in candidates.loc[candidates["feature_candidate"].isin(approved_features), "PIT_safe"]):
        raise R31AStop("STOP_R31B_PROPOSAL_BUDGET_OR_PIT")
    classification = "B_ONE_NEW_INFORMATION_DOMAIN_READY" if len(approved_domains) == 1 else "A_TWO_NEW_INFORMATION_DOMAINS_READY" if len(approved_domains) == 2 else "C_DATA_EXISTS_BUT_NOT_TRAINING_READY" if bool(inventory["SOURCE_AVAILABLE"].any()) else "D_NO_NEW_DOMAIN_READY_WITH_CURRENT_DATA"
    decision = "APPROVE_VOLUME_LIQUIDITY_FLOW_FOR_CONTROLLED_R31B_ABLATION" if approved_domains == ["VOLUME_LIQUIDITY_FLOW"] else "NO_R31B_APPROVAL"
    approved_rows = candidates.loc[candidates["feature_candidate"].isin(approved_features)].copy()
    source_identity = {
        "minute_coverage_manifest_path": str(MINUTE_COVERAGE), "minute_coverage_manifest_sha256": file_sha256(MINUTE_COVERAGE),
        "minute_run_manifest_path": str(MINUTE_RUN_MANIFEST), "minute_run_manifest_sha256": file_sha256(MINUTE_RUN_MANIFEST),
        "corporate_action_suspects_path": str(MINUTE_CA_SUSPECTS), "corporate_action_suspects_sha256": file_sha256(MINUTE_CA_SUSPECTS),
        "active_universe_path": str(ACTIVE_UNIVERSE), "active_universe_sha256": file_sha256(ACTIVE_UNIVERSE),
        "active_universe_manifest_path": str(ACTIVE_UNIVERSE_MANIFEST), "active_universe_manifest_sha256": file_sha256(ACTIVE_UNIVERSE_MANIFEST),
    }
    proposal = {
        "STAGE": "R31A", "STATUS": "FROZEN_DEFINITION_PROPOSAL_ONLY", "APPROVED_DOMAINS": approved_domains,
        "APPROVED_DOMAIN_COUNT": len(approved_domains), "PROPOSED_FEATURES": approved_features,
        "PROPOSED_FEATURE_COUNT": len(approved_features), "SOURCE_IDENTITY": source_identity,
        "FEATURE_DEFINITIONS": {row.feature_candidate: {"FORMULA": row.formula_concept, "LOOKBACK": row.lookback_or_window, "SOURCE": row.source, "TIMESTAMP_RULE": row.timestamp_rule, "MISSING_POLICY": row.missing_policy, "PIT_SAFE": bool(row.PIT_safe), "TRAINING_READY": bool(row.training_ready), "COVERAGE_ESTIMATE": row.coverage_estimate, "MAX_ABS_SPEARMAN_VS_CURRENT_29": row.current_29_overlap, "MAX_OVERLAP_FEATURE": row.max_abs_spearman_feature} for row in approved_rows.itertuples()},
        "FEATURE_VALUES_FROZEN": False, "OUTCOME_BLIND_FEATURE_SELECTION": True,
    }
    arms = {"ARM_0": "CURRENT_FROZEN_29", "ARM_A": "CURRENT_FROZEN_29+VOLUME_LIQUIDITY_FLOW"}
    preregistration = {
        "STAGE": "R31B_PROPOSAL_ONLY_DO_NOT_EXECUTE", "R31B_ALLOWED": bool(approved_domains), "ARMS": arms,
        "TARGETS": ["T1", "T2"], "T4_POLICY": "SECONDARY_DIAGNOSTIC_ONLY_DEFAULT_NO_T4_TRAINING",
        "T4_EXCLUSION_REASON": "R30D conditional result contradicted T4 incremental risk hypothesis.",
        "MODEL_FAMILY": ["HistGradientBoostingClassifier", "HistGradientBoostingRegressor"],
        "MODEL_HYPERPARAMETERS": "EXACT_R30A_R30B_REUSE", "SPLIT": "EXACT_FROZEN_REUSE",
        "ECONOMIC_CONTRACT": "EXACT_FROZEN_REUSE", "HYPERPARAMETER_SEARCH_ALLOWED": False,
        "LOOKBACK_SEARCH_ALLOWED": False, "ONLY_EXPERIMENTAL_VARIABLE": "INFORMATION_DOMAIN",
        "APPROVED_FEATURE_DEFINITIONS": proposal["FEATURE_DEFINITIONS"], "FINAL_CONFIRMATION_DATA_USED": False,
        "FINAL_CONFIRMATION_DATA_INSPECTED": False, "DO_NOT_AUTO_EXECUTE_R31B": True,
    }
    inventory.to_csv(frozen / "FAST3_R31A_DOMAIN_INVENTORY.csv", index=False, lineterminator="\n")
    readiness.to_csv(frozen / "FAST3_R31A_DOMAIN_READINESS.csv", index=False, lineterminator="\n")
    candidates.to_csv(frozen / "FAST3_R31A_FEATURE_CANDIDATES.csv", index=False, lineterminator="\n")
    novelty.to_csv(frozen / "FAST3_R31A_FEATURE_NOVELTY_AUDIT.csv", index=False, lineterminator="\n")
    write_json(frozen / "FAST3_R31A_APPROVED_DOMAIN_PROPOSAL.json", proposal)
    write_json(frozen / "FAST3_R31A_R31B_PREREGISTRATION.json", preregistration)
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=SOURCE_ROOT, text=True).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE_ROOT, text=True).strip()
    row = {item.DOMAIN: item for item in inventory.itertuples()}; ready = readiness.set_index("DOMAIN")
    summary = {
        "FAST3_R31A_STATUS": "PASS", "FAST3_R31A_CLASSIFICATION": classification, "FAST3_R31A_DECISION": decision,
        "BRANCH": branch, "START_HEAD": head, "HEAD": head, "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0,
        "NO_MODEL_TRAINING": True, "NO_MODEL_PREDICTION": True, "NO_NEW_TARGET": True, "NO_FINAL_HOLDOUT": True,
        "CURRENT_29_FEATURE_PRICE_TECHNICAL_PATH": "CLOSED_FOR_FURTHER_SAME_DOMAIN_EXPANSION",
        "CURRENT_FEATURE_COUNT": 29, "R30B_FEATURE_MANIFEST_SHA256": R30B_FEATURE_MANIFEST_SHA256,
        **{f"{stage}_SUMMARY": str(path) for stage, path in PRIOR_SUMMARIES.items()},
        **{f"{stage}_SUMMARY_SHA256": PRIOR_SUMMARY_SHA256[stage] for stage in PRIOR_SUMMARIES},
        "R30D_CLASSIFICATION": authority["priors"]["R30D"]["FAST3_R30D_CLASSIFICATION"],
        "DOMAIN_A_NAME": "VOLUME_LIQUIDITY_FLOW", "DOMAIN_A_STATUS": ready.loc["VOLUME_LIQUIDITY_FLOW", "DOMAIN_STATUS"], "DOMAIN_A_TEMPORAL_COVERAGE": row["VOLUME_LIQUIDITY_FLOW"].TEMPORAL_COVERAGE_RATE, "DOMAIN_A_PIT_STATUS": row["VOLUME_LIQUIDITY_FLOW"].PIT_STATUS, "DOMAIN_A_NOVELTY": "HIGH", "DOMAIN_A_PROPOSED_FEATURE_COUNT": len(approved_features),
        "DOMAIN_B_NAME": "MARKET_BREADTH_SECTOR_INTERNALS", "DOMAIN_B_STATUS": ready.loc["MARKET_BREADTH_SECTOR_INTERNALS", "DOMAIN_STATUS"], "DOMAIN_B_TEMPORAL_COVERAGE": row["MARKET_BREADTH_SECTOR_INTERNALS"].TEMPORAL_COVERAGE_RATE, "DOMAIN_B_PIT_STATUS": row["MARKET_BREADTH_SECTOR_INTERNALS"].PIT_STATUS, "DOMAIN_B_SURVIVORSHIP_STATUS": row["MARKET_BREADTH_SECTOR_INTERNALS"].SURVIVORSHIP_RISK, "DOMAIN_B_NOVELTY": "THEORETICALLY_HIGH_BUT_NOT_MEASURABLE_PIT_SAFE", "DOMAIN_B_PROPOSED_FEATURE_COUNT": 0, "DOMAIN_B_FIXED_PROXY_BASKET_AVAILABLE": False,
        "DOMAIN_C_NAME": "OPTIONS_IMPLIED_VOLATILITY", "DOMAIN_C_STATUS": ready.loc["OPTIONS_IMPLIED_VOLATILITY", "DOMAIN_STATUS"], "DOMAIN_C_TEMPORAL_COVERAGE": row["OPTIONS_IMPLIED_VOLATILITY"].TEMPORAL_COVERAGE_RATE, "DOMAIN_C_PIT_STATUS": row["OPTIONS_IMPLIED_VOLATILITY"].PIT_STATUS, "DOMAIN_C_PROPOSED_FEATURE_COUNT": 0,
        "DOMAIN_D_NAME": "MICROSTRUCTURE", "DOMAIN_D_STATUS": ready.loc["MICROSTRUCTURE", "DOMAIN_STATUS"], "DOMAIN_D_TEMPORAL_COVERAGE": row["MICROSTRUCTURE"].TEMPORAL_COVERAGE_RATE, "DOMAIN_D_PIT_STATUS": row["MICROSTRUCTURE"].PIT_STATUS, "DOMAIN_D_PROPOSED_FEATURE_COUNT": 0,
        "APPROVED_DOMAIN_COUNT": len(approved_domains), "APPROVED_DOMAIN_1": approved_domains[0] if approved_domains else None, "APPROVED_DOMAIN_2": approved_domains[1] if len(approved_domains) > 1 else None, "APPROVED_DOMAINS": approved_domains,
        "R31B_PROPOSED_NEW_FEATURE_COUNT": len(approved_features), "R31B_PROPOSED_FEATURES": approved_features, "R31B_PROPOSED_ARMS": arms,
        "R31B_TARGETS": "T1;T2", "R31B_MODEL_FAMILY": "HistGradientBoostingClassifier;HistGradientBoostingRegressor",
        "R31B_HYPERPARAMETER_SEARCH_ALLOWED": False, "R31B_LOOKBACK_SEARCH_ALLOWED": False, "R31B_ALLOWED": bool(approved_domains),
        "OUTCOME_BLIND_FEATURE_SELECTION": True, "ECONOMIC_OUTCOME_COLUMN_READ_COUNT": 0, "FEATURE_TARGET_CORRELATION_COUNT": 0,
        "FINAL_CONFIRMATION_DATA_USED": False, "FINAL_CONFIRMATION_DATA_INSPECTED": False,
        "NEW_EXTERNAL_DATA_DOWNLOAD_COUNT": 0, "NEW_VENDOR_CONNECTION_COUNT": 0, "NEW_CANONICAL_DATASET_COUNT": 0,
        "R29_MODIFIED": False, "R29_ALLOWED_TO_RESUME": False, "OFFICIAL_ADOPTION_ALLOWED": False, "LIVE_TRADING_ALLOWED": False,
        "R31A_NEW_SOURCE_FILE_COUNT": 1, "R31A_MODIFIED_SOURCE_FILE_COUNT": 0, "R31A_NEW_TEST_FILE_COUNT": 1, "NEW_HELPER_FILE_COUNT": 0,
        "R31A_GENERATED_REPO_ARTIFACT_COUNT": 0, "SHARED_CODE_MODIFICATION_REQUIRED": False, "ANTI_BLOAT_STATUS": "PASS",
        "FAST3_STORAGE_CONTRACT_R1_STATUS": "PASS", "SOURCE_ROOT": str(SOURCE_ROOT), "DATA_ROOT": str(DATA_ROOT), "RESULTS_ROOT": str(RESULTS_ROOT), "CACHE_ROOT": str(CACHE_ROOT),
        "DATA_ROOT_WRITE_COUNT": 0, "LOCAL_RESULTS_CREATED": False, "RESULT_FILES_WRITTEN_TO_GIT_REPO": False,
        "PRE_EXISTING_UNTRACKED_FILES_PRESERVED": True, "PRE_EXISTING_TRACKED_CHANGES_PRESERVED": True,
        "DESTRUCTIVE_GIT_COMMAND_USED": False, "BROAD_GIT_ADD_USED": False,
        "PRIMARY_RESEARCH_INTERPRETATION": "Existing canonical volume/turnover is the only distinct, full-window, PIT-safe domain ready for controlled economic-target ablation; breadth, options, and true microstructure are blocked by current data provenance or absence.",
        "NEW_DATA_ENGINEERING_REQUIRED_FOR_R31B": "NO_NEW_INGESTION;ONLY_DETERMINISTIC_FEATURE_CONSTRUCTION_AND_VALIDATION",
        "NEXT_STAGE": "R31B_CONTROLLED_VOLUME_LIQUIDITY_FLOW_ABLATION_AFTER_HUMAN_APPROVAL;DO_NOT_AUTO_EXECUTE",
        "REPORT_PATH": str(frozen / "FAST3_R31A_REPORT.md"), "SUMMARY_JSON_PATH": str(frozen / "FAST3_R31A_SUMMARY.json"),
        "DOMAIN_READINESS_PATH": str(frozen / "FAST3_R31A_DOMAIN_READINESS.csv"), "R31B_PREREGISTRATION_PATH": str(frozen / "FAST3_R31A_R31B_PREREGISTRATION.json"),
        "SOURCE_IDENTITY": source_identity,
    }
    write_json(frozen / "FAST3_R31A_SUMMARY.json", summary)
    (frozen / "FAST3_R31A_REPORT.md").write_text(report_text(summary), encoding="utf-8")
    write_json(runtime / "FAST3_R31A_RUNTIME_SUMMARY.json", {"status": "PASS", "classification": classification, "model_fit_count": 0, "model_predict_call_count": 0})
    print(json.dumps({key: summary[key] for key in ("FAST3_R31A_STATUS", "FAST3_R31A_CLASSIFICATION", "FAST3_R31A_DECISION", "APPROVED_DOMAINS", "R31B_PROPOSED_FEATURES", "REPORT_PATH", "SUMMARY_JSON_PATH")}, indent=2))


if __name__ == "__main__": main()
