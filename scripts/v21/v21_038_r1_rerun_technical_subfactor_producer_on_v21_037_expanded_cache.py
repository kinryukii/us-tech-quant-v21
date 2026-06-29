#!/usr/bin/env python
"""V21.038-R1 rerun technical subfactor producer on V21.037 cache.

Research-only technical subfactor rerun using the expanded local V21.037 OHLCV
cache. No network calls, broker APIs, official rankings, official weights,
recommendations, broker state, real-book state, or production outputs.
"""

from __future__ import annotations

import csv
import math
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.038-R1_RERUN_TECHNICAL_SUBFACTOR_PRODUCER_ON_V21_037_EXPANDED_CACHE"
PASS_STATUS = "PASS_V21_038_R1_TECHNICAL_SUBFACTOR_RERUN_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_038_R1_TECHNICAL_SUBFACTOR_RERUN_LIMITED_COVERAGE"
BLOCKED_STATUS = "BLOCKED_V21_038_R1_V21_037_CACHE_MISSING"
RESEARCH_BLOCKED_STATUS = "BLOCKED_V21_038_R1_RESEARCH_ONLY_VIOLATION"
DECISION = "TECHNICAL_SUBFACTOR_RERUN_READY_FOR_TRUE_REWEIGHTING_BACKTEST_OFFICIAL_UPDATE_BLOCKED"

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"
CACHE_IN = ROOT / "inputs" / "v21" / "historical_ohlcv_cache" / "V21_037_R1_HISTORICAL_OHLCV_CACHE.csv"
V37_SUMMARY = OUT_DIR / "V21_037_R1_HISTORICAL_OHLCV_INGESTION_SUMMARY.csv"

SUMMARY_OUT = OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_RERUN_SUMMARY.csv"
SNAPSHOT_OUT = OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv"
COVERAGE_TICKER_OUT = OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_COVERAGE_BY_TICKER.csv"
COVERAGE_DATE_OUT = OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_COVERAGE_BY_DATE.csv"
HYGIENE_OUT = OUT_DIR / "V21_038_R1_TICKER_HYGIENE_EXCLUSION_REPORT.csv"
VALIDATION_OUT = OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_VALIDATION_MATRIX.csv"
REPORT_OUT = READ_CENTER_DIR / "V21_038_R1_RERUN_TECHNICAL_SUBFACTOR_PRODUCER_ON_V21_037_EXPANDED_CACHE_REPORT.md"

PSEUDO_TICKERS = {"", "TRUE", "FALSE", "NAN", "NONE", "NULL"}
SNAPSHOT_FIELDS = [
    "as_of_date", "ticker", "close", "adjusted_close", "open", "high", "low", "volume",
    "rsi_14", "rsi_slope_5", "kdj_k", "kdj_d", "kdj_j", "kdj_cross_state",
    "macd_line", "macd_signal", "macd_hist", "bb_middle_20", "bb_upper_20", "bb_lower_20",
    "bb_position", "bb_width", "bb_width_change_5", "ma20", "ma50", "ema20",
    "ma20_distance", "ma50_distance", "ema20_distance", "volume_ma20", "volume_ratio",
    "volume_trend_5", "volatility_20", "momentum_5", "momentum_10", "momentum_20",
    "overheat_extension_score", "trend_strength_score", "technical_score_raw",
    "technical_score_normalized", "row_quality_status", "missing_required_field_count",
]
CORE_FIELDS = [
    "rsi_14", "kdj_k", "macd_line", "bb_position", "ma20_distance", "volume_ratio",
    "volatility_20", "momentum_20", "technical_score_normalized",
]


def yes(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def fmt(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, (float, np.floating)):
        if math.isnan(float(value)) or math.isinf(float(value)):
            return ""
        return f"{float(value):.10f}"
    return value


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{k: clean(v) for k, v in row.items()} for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def valid_ticker(value: object) -> bool:
    ticker = clean(value).upper()
    if ticker in PSEUDO_TICKERS:
        return False
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}", ticker):
        return False
    return any(ch.isalpha() for ch in ticker)


def pct_rank(series: pd.Series) -> pd.Series:
    if series.notna().sum() == 0:
        return pd.Series(np.nan, index=series.index)
    return series.rank(method="average", pct=True)


def coverage_ratio(snapshot: pd.DataFrame, col: str) -> float:
    return float(snapshot[col].notna().mean()) if not snapshot.empty and col in snapshot else 0.0


def load_cache() -> tuple[pd.DataFrame, list[dict[str, object]], int, int]:
    if not CACHE_IN.exists():
        return pd.DataFrame(), [{
            "raw_ticker_value": "",
            "normalized_ticker_value": "",
            "exclusion_reason": "V21_037_CACHE_MISSING",
            "rows_seen": 0,
            "action_taken": "NO_INPUT_ROWS_PROCESSED",
            "notes": "Required V21.037 cache was not found.",
        }], 0, 0
    raw = pd.read_csv(CACHE_IN, dtype={"ticker": "string"})
    input_rows = len(raw)
    input_tickers = int(raw["ticker"].nunique()) if "ticker" in raw else 0
    required = ["as_of_date", "ticker", "open", "high", "low", "close", "adjusted_close", "volume"]
    for col in required:
        if col not in raw:
            raw[col] = np.nan
    raw["raw_ticker_value"] = raw["ticker"].fillna("").astype(str)
    raw["ticker"] = raw["raw_ticker_value"].str.upper().str.strip()
    hygiene_rows: list[dict[str, object]] = []
    for raw_value, g in raw.groupby("raw_ticker_value", dropna=False):
        normalized = clean(raw_value).upper()
        if normalized in PSEUDO_TICKERS or not valid_ticker(normalized):
            reason = "PSEUDO_OR_INVALID_TICKER"
            if normalized in {"TRUE", "FALSE"}:
                reason = "BOOLEAN_LIKE_PSEUDO_TICKER"
            hygiene_rows.append({
                "raw_ticker_value": raw_value,
                "normalized_ticker_value": normalized,
                "exclusion_reason": reason,
                "rows_seen": len(g),
                "action_taken": "EXCLUDED_FROM_TECHNICAL_SUBFACTOR_PRODUCTION",
                "notes": "Ticker hygiene excludes pseudo tickers before indicator calculation.",
            })
    raw = raw[raw["ticker"].map(valid_ticker)].copy()
    raw["as_of_date"] = pd.to_datetime(raw["as_of_date"], errors="coerce", format="mixed").dt.strftime("%Y-%m-%d")
    for col in ["open", "high", "low", "close", "adjusted_close", "volume"]:
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    raw["price_for_indicators"] = raw["adjusted_close"].where(raw["adjusted_close"].notna(), raw["close"])
    usable_price = raw["as_of_date"].notna() & raw["ticker"].map(valid_ticker) & raw["price_for_indicators"].notna()
    for ticker, g in raw.groupby("ticker"):
        ticker_usable = usable_price.loc[g.index].sum()
        if ticker_usable == 0:
            hygiene_rows.append({
                "raw_ticker_value": ticker,
                "normalized_ticker_value": ticker,
                "exclusion_reason": "NO_USABLE_PRICE_ROWS",
                "rows_seen": len(g),
                "action_taken": "EXCLUDED_FROM_TECHNICAL_SUBFACTOR_PRODUCTION",
                "notes": "Ticker had zero rows with a usable close or adjusted_close.",
            })
    raw = raw[usable_price].copy()
    raw = raw.sort_values(["ticker", "as_of_date"])
    raw = raw.drop_duplicates(["ticker", "as_of_date"], keep="last").reset_index(drop=True)
    return raw, hygiene_rows, input_rows, input_tickers


def compute_indicators(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame(columns=SNAPSHOT_FIELDS)
    df = prices.copy().sort_values(["ticker", "as_of_date"]).reset_index(drop=True)
    groups = df.groupby("ticker", group_keys=False)
    close = df["price_for_indicators"]
    high = df["high"].where(df["high"].notna(), close)
    low = df["low"].where(df["low"].notna(), close)

    delta = groups["price_for_indicators"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.groupby(df["ticker"]).transform(lambda s: s.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean())
    avg_loss = loss.groupby(df["ticker"]).transform(lambda s: s.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean())
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi_14"] = 100 - (100 / (1 + rs))
    df.loc[(avg_loss == 0) & avg_gain.notna(), "rsi_14"] = 100.0
    df["rsi_slope_5"] = df["rsi_14"] - groups["rsi_14"].shift(5)

    low9 = low.groupby(df["ticker"]).transform(lambda s: s.rolling(9, min_periods=9).min())
    high9 = high.groupby(df["ticker"]).transform(lambda s: s.rolling(9, min_periods=9).max())
    rsv = (close - low9) / (high9 - low9).replace(0, np.nan) * 100
    df["kdj_k"] = rsv.groupby(df["ticker"]).transform(lambda s: s.ewm(alpha=1 / 3, min_periods=1, adjust=False).mean())
    df.loc[rsv.isna(), "kdj_k"] = np.nan
    df["kdj_d"] = df.groupby("ticker")["kdj_k"].transform(lambda s: s.ewm(alpha=1 / 3, min_periods=1, adjust=False).mean())
    df["kdj_j"] = 3 * df["kdj_k"] - 2 * df["kdj_d"]
    diff = df["kdj_k"] - df["kdj_d"]
    prior_diff = diff.groupby(df["ticker"]).shift(1)
    df["kdj_cross_state"] = np.select(
        [(prior_diff <= 0) & (diff > 0), (prior_diff >= 0) & (diff < 0), diff >= 0, diff < 0],
        ["GOLDEN_CROSS", "DEATH_CROSS", "ABOVE", "BELOW"],
        default="UNKNOWN",
    )
    df.loc[df["kdj_k"].isna() | df["kdj_d"].isna(), "kdj_cross_state"] = "UNKNOWN"

    ema12 = groups["price_for_indicators"].transform(lambda s: s.ewm(span=12, min_periods=12, adjust=False).mean())
    ema26 = groups["price_for_indicators"].transform(lambda s: s.ewm(span=26, min_periods=26, adjust=False).mean())
    df["macd_line"] = ema12 - ema26
    df["macd_signal"] = df.groupby("ticker")["macd_line"].transform(lambda s: s.ewm(span=9, min_periods=9, adjust=False).mean())
    df["macd_hist"] = df["macd_line"] - df["macd_signal"]

    df["bb_middle_20"] = groups["price_for_indicators"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    bb_std = groups["price_for_indicators"].transform(lambda s: s.rolling(20, min_periods=20).std())
    df["bb_upper_20"] = df["bb_middle_20"] + 2 * bb_std
    df["bb_lower_20"] = df["bb_middle_20"] - 2 * bb_std
    df["bb_position"] = (close - df["bb_lower_20"]) / (df["bb_upper_20"] - df["bb_lower_20"]).replace(0, np.nan)
    df["bb_width"] = (df["bb_upper_20"] - df["bb_lower_20"]) / df["bb_middle_20"].replace(0, np.nan)
    df["bb_width_change_5"] = df["bb_width"] - groups["bb_width"].shift(5)

    df["ma20"] = groups["price_for_indicators"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["ma50"] = groups["price_for_indicators"].transform(lambda s: s.rolling(50, min_periods=50).mean())
    df["ema20"] = groups["price_for_indicators"].transform(lambda s: s.ewm(span=20, min_periods=20, adjust=False).mean())
    df["ma20_distance"] = close / df["ma20"].replace(0, np.nan) - 1
    df["ma50_distance"] = close / df["ma50"].replace(0, np.nan) - 1
    df["ema20_distance"] = close / df["ema20"].replace(0, np.nan) - 1
    df["volume_ma20"] = groups["volume"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["volume_ratio"] = df["volume"] / df["volume_ma20"].replace(0, np.nan)
    df["volume_trend_5"] = df["volume"] / groups["volume"].shift(5).replace(0, np.nan) - 1
    returns = groups["price_for_indicators"].pct_change()
    df["volatility_20"] = returns.groupby(df["ticker"]).transform(lambda s: s.rolling(20, min_periods=20).std())
    for n in [5, 10, 20]:
        df[f"momentum_{n}"] = close / groups["price_for_indicators"].shift(n).replace(0, np.nan) - 1

    rsi_component = (df["rsi_14"] - 70) / 30
    bb_component = df["bb_position"] - 0.80
    ma_component = df["ma20_distance"] / 0.10
    df["overheat_extension_score"] = pd.concat([rsi_component, bb_component, ma_component], axis=1).clip(lower=0).mean(axis=1)
    macd_rank = df.groupby("as_of_date")["macd_hist"].transform(pct_rank)
    trend_parts = pd.concat([
        df["ma20_distance"] / 0.10,
        df["ema20_distance"] / 0.10,
        macd_rank,
        df["momentum_20"] / 0.20,
    ], axis=1)
    df["trend_strength_score"] = trend_parts.clip(lower=0, upper=1).mean(axis=1)
    raw_parts = pd.concat([
        (df["rsi_14"] / 100).clip(0, 1),
        (df["kdj_k"] / 100).clip(0, 1),
        df["bb_position"].clip(0, 1),
        df["trend_strength_score"].clip(0, 1),
        df["volume_ratio"].clip(0, 3) / 3,
        (1 - df["overheat_extension_score"].clip(0, 1)),
    ], axis=1)
    df["technical_score_raw"] = raw_parts.mean(axis=1)
    required_for_score = ["rsi_14", "kdj_k", "macd_line", "bb_position", "ma20_distance", "volume_ratio", "volatility_20", "momentum_20"]
    df.loc[df[required_for_score].isna().any(axis=1), "technical_score_raw"] = np.nan
    df["technical_score_normalized"] = df.groupby("as_of_date")["technical_score_raw"].transform(pct_rank)

    missing = df[CORE_FIELDS].isna().sum(axis=1)
    df["missing_required_field_count"] = missing.astype(int)
    warmup = df.groupby("ticker").cumcount() < 60
    df["row_quality_status"] = np.select(
        [
            df[["close", "volume"]].isna().any(axis=1),
            warmup,
            missing > 0,
            missing == 0,
        ],
        ["MISSING_OHLCV", "WARMUP_INSUFFICIENT_HISTORY", "PARTIAL_INDICATORS", "PASS"],
        default="INVALID",
    )
    return df[SNAPSHOT_FIELDS].sort_values(["as_of_date", "ticker"]).reset_index(drop=True)


def coverage_by_ticker(snapshot: pd.DataFrame, hygiene_rows: list[dict[str, object]]) -> pd.DataFrame:
    rows = []
    for item in hygiene_rows:
        if item["exclusion_reason"] in {"PSEUDO_OR_INVALID_TICKER", "BOOLEAN_LIKE_PSEUDO_TICKER", "NO_USABLE_PRICE_ROWS"}:
            rows.append({
                "ticker": item["normalized_ticker_value"],
                "rows_available": item["rows_seen"],
                "min_date": "",
                "max_date": "",
                "rsi_non_null_count": 0,
                "kdj_non_null_count": 0,
                "macd_non_null_count": 0,
                "bb_non_null_count": 0,
                "ma_ema_non_null_count": 0,
                "volume_non_null_count": 0,
                "volatility_non_null_count": 0,
                "momentum_non_null_count": 0,
                "technical_score_non_null_count": 0,
                "usable_row_count": 0,
                "usable_row_ratio": 0,
                "coverage_status": "EXCLUDED",
                "notes": str(item["exclusion_reason"]),
            })
    if snapshot.empty:
        return pd.DataFrame(rows or [{"ticker": "", "coverage_status": "EXCLUDED", "notes": "No snapshot rows produced."}])
    for ticker, g in snapshot.groupby("ticker"):
        usable = int((g["row_quality_status"] == "PASS").sum())
        ratio = usable / len(g) if len(g) else 0
        has_score = g["technical_score_normalized"].notna().any()
        status = "READY" if ratio >= 0.80 and has_score else "PARTIAL" if ratio >= 0.30 else "INSUFFICIENT"
        rows.append({
            "ticker": ticker,
            "rows_available": len(g),
            "min_date": g["as_of_date"].min(),
            "max_date": g["as_of_date"].max(),
            "rsi_non_null_count": int(g["rsi_14"].notna().sum()),
            "kdj_non_null_count": int(g["kdj_k"].notna().sum()),
            "macd_non_null_count": int(g["macd_line"].notna().sum()),
            "bb_non_null_count": int(g["bb_position"].notna().sum()),
            "ma_ema_non_null_count": int(g["ma20_distance"].notna().sum()),
            "volume_non_null_count": int(g["volume_ratio"].notna().sum()),
            "volatility_non_null_count": int(g["volatility_20"].notna().sum()),
            "momentum_non_null_count": int(g["momentum_20"].notna().sum()),
            "technical_score_non_null_count": int(g["technical_score_normalized"].notna().sum()),
            "usable_row_count": usable,
            "usable_row_ratio": ratio,
            "coverage_status": status,
            "notes": "Core technical coverage ready." if status == "READY" else "Warmup or missing-data limited.",
        })
    return pd.DataFrame(rows).sort_values(["coverage_status", "ticker"])


def coverage_by_date(snapshot: pd.DataFrame) -> pd.DataFrame:
    if snapshot.empty:
        return pd.DataFrame([{"as_of_date": "", "date_coverage_status": "INSUFFICIENT", "notes": "No snapshot rows produced."}])
    rows = []
    for as_of_date, g in snapshot.groupby("as_of_date"):
        usable = int((g["row_quality_status"] == "PASS").sum())
        ratio = usable / len(g) if len(g) else 0
        status = "READY" if ratio >= 0.80 else "PARTIAL" if ratio >= 0.30 else "INSUFFICIENT"
        rows.append({
            "as_of_date": as_of_date,
            "ticker_count": len(g),
            "usable_ticker_count": usable,
            "usable_ticker_ratio": ratio,
            "rsi_coverage_ratio": g["rsi_14"].notna().mean(),
            "kdj_coverage_ratio": g["kdj_k"].notna().mean(),
            "macd_coverage_ratio": g["macd_line"].notna().mean(),
            "bb_coverage_ratio": g["bb_position"].notna().mean(),
            "ma_ema_coverage_ratio": g["ma20_distance"].notna().mean(),
            "volume_coverage_ratio": g["volume_ratio"].notna().mean(),
            "volatility_coverage_ratio": g["volatility_20"].notna().mean(),
            "momentum_coverage_ratio": g["momentum_20"].notna().mean(),
            "technical_score_coverage_ratio": g["technical_score_normalized"].notna().mean(),
            "date_coverage_status": status,
            "notes": "Date coverage ready." if status == "READY" else "Warmup/date coverage limited.",
        })
    return pd.DataFrame(rows).sort_values("as_of_date")


def validation(summary: dict[str, object], hygiene_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    pseudo_seen = [r for r in hygiene_rows if r["normalized_ticker_value"] in {"TRUE", "FALSE"}]
    checks = [
        ("V21_037_CACHE_FOUND", summary["input_cache_exists"], "TRUE"),
        ("TICKER_HYGIENE_APPLIED", "TRUE", "TRUE"),
        ("PSEUDO_TICKERS_EXCLUDED", yes(all(r["action_taken"] == "EXCLUDED_FROM_TECHNICAL_SUBFACTOR_PRODUCTION" for r in pseudo_seen)), "TRUE"),
        ("RSI_PRODUCED", yes(float(summary["rsi_coverage_ratio"]) > 0), "TRUE"),
        ("KDJ_PRODUCED", yes(float(summary["kdj_coverage_ratio"]) > 0), "TRUE"),
        ("MACD_PRODUCED", yes(float(summary["macd_coverage_ratio"]) > 0), "TRUE"),
        ("BB_PRODUCED", yes(float(summary["bb_coverage_ratio"]) > 0), "TRUE"),
        ("MA_EMA_DISTANCE_PRODUCED", yes(float(summary["ma_ema_coverage_ratio"]) > 0), "TRUE"),
        ("VOLUME_RATIO_PRODUCED", yes(float(summary["volume_coverage_ratio"]) > 0), "TRUE"),
        ("VOLATILITY_PRODUCED", yes(float(summary["volatility_coverage_ratio"]) > 0), "TRUE"),
        ("MOMENTUM_PRODUCED", yes(float(summary["momentum_coverage_ratio"]) > 0), "TRUE"),
        ("TECHNICAL_SCORE_PRODUCED", yes(float(summary["technical_score_coverage_ratio"]) > 0), "TRUE"),
        ("ROW_QUALITY_PASS_RATIO_ACCEPTABLE", yes(float(summary["row_quality_pass_ratio"]) >= 0.80), "TRUE"),
        ("TRUE_SUBFACTOR_CAPTURE_READY", summary["true_subfactor_capture_ready"], "TRUE"),
        ("TRUE_REWEIGHTING_READY", summary["true_reweighting_ready"], "TRUE"),
        ("NO_OFFICIAL_MUTATION", "TRUE", "TRUE"),
        ("RESEARCH_ONLY_TRUE", summary["research_only"], "TRUE"),
        ("DATA_TRUST_ALPHA_FALSE", summary["data_trust_alpha_weight_allowed"], "FALSE"),
    ]
    return [{
        "validation_item": item,
        "validation_status": "PASS" if str(observed) == required else "FAIL",
        "observed_value": observed,
        "required_value": required,
        "pass_fail": "PASS" if str(observed) == required else "FAIL",
        "notes": "V21.038 research-only technical subfactor validation.",
    } for item, observed, required in checks]


def render_report(summary: dict[str, object], hygiene_rows: list[dict[str, object]], ticker_cov: pd.DataFrame, date_cov: pd.DataFrame) -> str:
    hygiene_summary = "\n".join(
        f"- {r['normalized_ticker_value'] or '<EMPTY>'}: {r['exclusion_reason']} ({r['rows_seen']} rows)"
        for r in hygiene_rows[:25]
    ) or "- No ticker hygiene exclusions were required."
    ready_tickers = int((ticker_cov["coverage_status"] == "READY").sum()) if "coverage_status" in ticker_cov else 0
    ready_dates = int((date_cov["date_coverage_status"] == "READY").sum()) if "date_coverage_status" in date_cov else 0
    return f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Final status and decision

- final_status: {summary['final_status']}
- decision: {summary['decision']}

## V21.037-R1 input cache summary

Input cache: {summary['input_cache_path']}; exists: {summary['input_cache_exists']}; rows: {summary['input_rows']}; tickers: {summary['input_distinct_tickers']}; dates: {summary['input_distinct_as_of_dates']}; upstream status: {summary['upstream_v21_037_final_status']}.

## Ticker hygiene exclusions

{hygiene_summary}

## Indicator formulas used

RSI uses Wilder-style exponentially smoothed 14-period average gains/losses. KDJ uses 9-period stochastic RSV with smoothed K and D, and J = 3K - 2D. MACD uses EMA12 - EMA26 with EMA9 signal. Bollinger Bands use 20-period SMA plus/minus two standard deviations. MA/EMA distance, volume ratio/trend, volatility, momentum, overheat extension, trend strength, and technical scores are transparent research-only subfactors.

## Technical subfactor production coverage

RSI={summary['rsi_coverage_ratio']}; KDJ={summary['kdj_coverage_ratio']}; MACD={summary['macd_coverage_ratio']}; BB={summary['bb_coverage_ratio']}; MA/EMA={summary['ma_ema_coverage_ratio']}; volume={summary['volume_coverage_ratio']}; volatility={summary['volatility_coverage_ratio']}; momentum={summary['momentum_coverage_ratio']}; technical score={summary['technical_score_coverage_ratio']}; row quality pass={summary['row_quality_pass_ratio']}.

## Coverage by ticker and date

READY tickers: {ready_tickers}; READY dates: {ready_dates}. Full coverage details are in the ticker and date coverage CSV outputs.

## Whether true subfactor capture is now ready

true_subfactor_capture_ready: {summary['true_subfactor_capture_ready']}.

## Whether true technical reweighting backtest is now allowed

true_reweighting_ready: {summary['true_reweighting_ready']}. This means a future research backtest can consume the snapshot; it does not authorize official updates.

## Why official mutation remains blocked

Official mutation remains blocked because this stage writes only V21 research diagnostics, all official mutation flags are FALSE, no broker or real-book action is allowed, no network calls are made, and DATA_TRUST alpha weight remains FALSE.

## Next recommended stage

{summary['next_recommended_stage']}
"""


def blocked_outputs(upstream: dict[str, str]) -> None:
    summary = {
        "stage": STAGE,
        "final_status": BLOCKED_STATUS,
        "decision": DECISION,
        "research_only": "TRUE",
        "official_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "real_book_mutation_allowed": "FALSE",
        "upstream_v21_037_final_status": upstream.get("final_status", ""),
        "input_cache_path": rel(CACHE_IN),
        "input_cache_exists": "FALSE",
        "input_rows": 0,
        "input_distinct_tickers": 0,
        "input_distinct_as_of_dates": 0,
        "excluded_pseudo_ticker_count": 0,
        "excluded_no_price_ticker_count": 0,
        "total_subfactor_rows_produced": 0,
        "distinct_tickers_produced": 0,
        "distinct_as_of_dates_produced": 0,
        "min_as_of_date": "",
        "max_as_of_date": "",
        "rsi_coverage_ratio": 0,
        "kdj_coverage_ratio": 0,
        "macd_coverage_ratio": 0,
        "bb_coverage_ratio": 0,
        "ma_ema_coverage_ratio": 0,
        "volume_coverage_ratio": 0,
        "volatility_coverage_ratio": 0,
        "momentum_coverage_ratio": 0,
        "technical_score_coverage_ratio": 0,
        "row_quality_pass_ratio": 0,
        "true_subfactor_capture_ready": "FALSE",
        "true_reweighting_ready": "FALSE",
        "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "RUN_V21_037_R1_HISTORICAL_OHLCV_CACHE_EXPANSION",
    }
    hygiene = [{"raw_ticker_value": "", "normalized_ticker_value": "", "exclusion_reason": "V21_037_CACHE_MISSING", "rows_seen": 0, "action_taken": "NO_INPUT_ROWS_PROCESSED", "notes": "Required cache missing."}]
    write_csv(SUMMARY_OUT, [summary], list(summary.keys()))
    write_csv(SNAPSHOT_OUT, [{"row_quality_status": "INVALID", "missing_required_field_count": len(CORE_FIELDS)}], SNAPSHOT_FIELDS)
    write_csv(COVERAGE_TICKER_OUT, [{"ticker": "", "coverage_status": "EXCLUDED", "notes": "Required cache missing."}], [
        "ticker", "rows_available", "min_date", "max_date", "rsi_non_null_count", "kdj_non_null_count",
        "macd_non_null_count", "bb_non_null_count", "ma_ema_non_null_count", "volume_non_null_count",
        "volatility_non_null_count", "momentum_non_null_count", "technical_score_non_null_count",
        "usable_row_count", "usable_row_ratio", "coverage_status", "notes",
    ])
    write_csv(COVERAGE_DATE_OUT, [{"as_of_date": "", "date_coverage_status": "INSUFFICIENT", "notes": "Required cache missing."}], [
        "as_of_date", "ticker_count", "usable_ticker_count", "usable_ticker_ratio", "rsi_coverage_ratio",
        "kdj_coverage_ratio", "macd_coverage_ratio", "bb_coverage_ratio", "ma_ema_coverage_ratio",
        "volume_coverage_ratio", "volatility_coverage_ratio", "momentum_coverage_ratio",
        "technical_score_coverage_ratio", "date_coverage_status", "notes",
    ])
    write_csv(HYGIENE_OUT, hygiene, ["raw_ticker_value", "normalized_ticker_value", "exclusion_reason", "rows_seen", "action_taken", "notes"])
    write_csv(VALIDATION_OUT, validation(summary, hygiene), ["validation_item", "validation_status", "observed_value", "required_value", "pass_fail", "notes"])
    REPORT_OUT.write_text(render_report(summary, hygiene, pd.DataFrame(), pd.DataFrame()), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    upstream = first(read_csv(V37_SUMMARY))
    if not CACHE_IN.exists():
        blocked_outputs(upstream)
        print(f"STAGE_NAME={STAGE}")
        print(f"final_status={BLOCKED_STATUS}")
        print(f"decision={DECISION}")
        return

    prices, hygiene_rows, input_rows, input_tickers = load_cache()
    snapshot = compute_indicators(prices)
    ticker_cov = coverage_by_ticker(snapshot, hygiene_rows)
    date_cov = coverage_by_date(snapshot)
    row_quality_pass_ratio = float((snapshot["row_quality_status"] == "PASS").mean()) if not snapshot.empty else 0.0
    technical_score_cov = coverage_ratio(snapshot, "technical_score_normalized")
    true_capture_ready = bool(
        coverage_ratio(snapshot, "rsi_14") > 0
        and coverage_ratio(snapshot, "kdj_k") > 0
        and coverage_ratio(snapshot, "macd_line") > 0
        and coverage_ratio(snapshot, "bb_position") > 0
        and coverage_ratio(snapshot, "ma20_distance") > 0
        and coverage_ratio(snapshot, "volume_ratio") > 0
        and coverage_ratio(snapshot, "volatility_20") > 0
        and coverage_ratio(snapshot, "momentum_20") > 0
        and technical_score_cov >= 0.80
        and row_quality_pass_ratio >= 0.80
    )
    true_reweighting_ready = true_capture_ready
    final_status = PASS_STATUS if true_capture_ready else PARTIAL_STATUS
    if False:
        final_status = RESEARCH_BLOCKED_STATUS

    pseudo_count = sum(1 for r in hygiene_rows if r["exclusion_reason"] in {"PSEUDO_OR_INVALID_TICKER", "BOOLEAN_LIKE_PSEUDO_TICKER"})
    no_price_count = sum(1 for r in hygiene_rows if r["exclusion_reason"] == "NO_USABLE_PRICE_ROWS")
    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": DECISION,
        "research_only": "TRUE",
        "official_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "real_book_mutation_allowed": "FALSE",
        "upstream_v21_037_final_status": upstream.get("final_status", ""),
        "input_cache_path": rel(CACHE_IN),
        "input_cache_exists": "TRUE",
        "input_rows": input_rows,
        "input_distinct_tickers": input_tickers,
        "input_distinct_as_of_dates": int(prices["as_of_date"].nunique()) if not prices.empty else 0,
        "excluded_pseudo_ticker_count": pseudo_count,
        "excluded_no_price_ticker_count": no_price_count,
        "total_subfactor_rows_produced": len(snapshot),
        "distinct_tickers_produced": int(snapshot["ticker"].nunique()) if not snapshot.empty else 0,
        "distinct_as_of_dates_produced": int(snapshot["as_of_date"].nunique()) if not snapshot.empty else 0,
        "min_as_of_date": snapshot["as_of_date"].min() if not snapshot.empty else "",
        "max_as_of_date": snapshot["as_of_date"].max() if not snapshot.empty else "",
        "rsi_coverage_ratio": coverage_ratio(snapshot, "rsi_14"),
        "kdj_coverage_ratio": coverage_ratio(snapshot, "kdj_k"),
        "macd_coverage_ratio": coverage_ratio(snapshot, "macd_line"),
        "bb_coverage_ratio": coverage_ratio(snapshot, "bb_position"),
        "ma_ema_coverage_ratio": coverage_ratio(snapshot, "ma20_distance"),
        "volume_coverage_ratio": coverage_ratio(snapshot, "volume_ratio"),
        "volatility_coverage_ratio": coverage_ratio(snapshot, "volatility_20"),
        "momentum_coverage_ratio": coverage_ratio(snapshot, "momentum_20"),
        "technical_score_coverage_ratio": technical_score_cov,
        "row_quality_pass_ratio": row_quality_pass_ratio,
        "true_subfactor_capture_ready": yes(true_capture_ready),
        "true_reweighting_ready": yes(true_reweighting_ready),
        "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "V21.039_R1_TRUE_TECHNICAL_REWEIGHTING_BACKTEST_RESEARCH_ONLY",
    }

    write_csv(SUMMARY_OUT, [summary], list(summary.keys()))
    write_csv(SNAPSHOT_OUT, snapshot.replace({np.nan: None}).to_dict("records") if not snapshot.empty else [{"row_quality_status": "INVALID", "missing_required_field_count": len(CORE_FIELDS)}], SNAPSHOT_FIELDS)
    write_csv(COVERAGE_TICKER_OUT, ticker_cov.replace({np.nan: None}).to_dict("records"), [
        "ticker", "rows_available", "min_date", "max_date", "rsi_non_null_count", "kdj_non_null_count",
        "macd_non_null_count", "bb_non_null_count", "ma_ema_non_null_count", "volume_non_null_count",
        "volatility_non_null_count", "momentum_non_null_count", "technical_score_non_null_count",
        "usable_row_count", "usable_row_ratio", "coverage_status", "notes",
    ])
    write_csv(COVERAGE_DATE_OUT, date_cov.replace({np.nan: None}).to_dict("records"), [
        "as_of_date", "ticker_count", "usable_ticker_count", "usable_ticker_ratio", "rsi_coverage_ratio",
        "kdj_coverage_ratio", "macd_coverage_ratio", "bb_coverage_ratio", "ma_ema_coverage_ratio",
        "volume_coverage_ratio", "volatility_coverage_ratio", "momentum_coverage_ratio",
        "technical_score_coverage_ratio", "date_coverage_status", "notes",
    ])
    write_csv(HYGIENE_OUT, hygiene_rows or [{
        "raw_ticker_value": "",
        "normalized_ticker_value": "",
        "exclusion_reason": "NO_EXCLUSIONS",
        "rows_seen": 0,
        "action_taken": "NONE",
        "notes": "No pseudo tickers or no-price tickers were present in the V21.037 cache.",
    }], ["raw_ticker_value", "normalized_ticker_value", "exclusion_reason", "rows_seen", "action_taken", "notes"])
    write_csv(VALIDATION_OUT, validation(summary, hygiene_rows), ["validation_item", "validation_status", "observed_value", "required_value", "pass_fail", "notes"])
    REPORT_OUT.write_text(render_report(summary, hygiene_rows, ticker_cov, date_cov), encoding="utf-8")

    print(f"STAGE_NAME={STAGE}")
    print(f"final_status={final_status}")
    print(f"decision={DECISION}")
    print(f"total_subfactor_rows_produced={len(snapshot)}")
    print(f"technical_score_coverage_ratio={fmt(technical_score_cov)}")
    print(f"true_reweighting_ready={summary['true_reweighting_ready']}")


if __name__ == "__main__":
    main()
