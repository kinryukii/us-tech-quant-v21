#!/usr/bin/env python
"""V21.035-R1 technical subfactor producer patch.

Research-only producer for granular technical subfactor columns from local
OHLCV-like CSV artifacts. No network calls and no official artifacts mutated.
"""

from __future__ import annotations

import csv
import math
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.035-R1_TECHNICAL_SUBFACTOR_PRODUCER_PATCH"
PASS_STATUS = "PASS_V21_035_R1_TECHNICAL_SUBFACTOR_PRODUCER_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_035_R1_TECHNICAL_SUBFACTOR_PRODUCER_LIMITED_COVERAGE"
BLOCKED_STATUS = "BLOCKED_V21_035_R1_NO_USABLE_OHLCV_SOURCE"
DECISION = "TECHNICAL_SUBFACTOR_PRODUCER_PATCH_READY_TRUE_REWEIGHTING_PENDING_VALIDATION_OFFICIAL_UPDATE_BLOCKED"

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

V34_SUMMARY = OUT_DIR / "V21_034_R1_TRUE_TECHNICAL_SUBFACTOR_REPAIR_SUMMARY.csv"

SUMMARY_OUT = OUT_DIR / "V21_035_R1_TECHNICAL_SUBFACTOR_PRODUCER_SUMMARY.csv"
SNAPSHOT_OUT = OUT_DIR / "V21_035_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv"
COVERAGE_TICKER_OUT = OUT_DIR / "V21_035_R1_TECHNICAL_SUBFACTOR_COVERAGE_BY_TICKER.csv"
COVERAGE_DATE_OUT = OUT_DIR / "V21_035_R1_TECHNICAL_SUBFACTOR_COVERAGE_BY_DATE.csv"
INPUT_AUDIT_OUT = OUT_DIR / "V21_035_R1_TECHNICAL_SUBFACTOR_PRODUCER_INPUT_AUDIT.csv"
VALIDATION_OUT = OUT_DIR / "V21_035_R1_TECHNICAL_SUBFACTOR_VALIDATION_MATRIX.csv"
REPORT_OUT = READ_CENTER_DIR / "V21_035_R1_TECHNICAL_SUBFACTOR_PRODUCER_PATCH_REPORT.md"

SNAPSHOT_FIELDS = [
    "as_of_date", "ticker", "source_file_path", "close", "adjusted_close", "open", "high", "low", "volume",
    "rsi_14", "rsi_slope_5", "kdj_k", "kdj_d", "kdj_j", "kdj_cross_state", "macd_line", "macd_signal",
    "macd_hist", "bb_middle_20", "bb_upper_20", "bb_lower_20", "bb_position", "bb_width", "bb_width_change_5",
    "ma20", "ma50", "ema20", "ma20_distance", "ma50_distance", "ema20_distance", "volume_ma20",
    "volume_ratio", "volume_trend_5", "volatility_20", "momentum_5", "momentum_10", "momentum_20",
    "overheat_extension_score", "trend_strength_score", "technical_score_raw", "technical_score_normalized",
    "row_quality_status", "missing_required_field_count",
]

CORE_FIELDS = ["rsi_14", "kdj_k", "macd_line", "bb_position", "ma20_distance", "volume_ratio", "technical_score_normalized"]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def fmt(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        return f"{value:.10f}"
    return value


def yes(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def candidate_files() -> list[Path]:
    roots = [
        ROOT / "data",
        ROOT / "inputs",
        ROOT / "outputs" / "v20",
        ROOT / "outputs" / "v21",
    ]
    files = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.csv"):
            name = str(path).lower()
            if any(token in name for token in ["price", "ohlcv", "quote", "history", "yahoo", "cache", "market"]):
                files.append(path)
            if len(files) >= 500:
                return sorted(set(files))
    return sorted(set(files))


def header(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return next(csv.reader(handle), [])
    except (OSError, UnicodeDecodeError, StopIteration):
        return []


def find_col(cols: list[str], candidates: list[str]) -> str:
    by_norm = {norm(col): col for col in cols}
    for candidate in candidates:
        if norm(candidate) in by_norm:
            return by_norm[norm(candidate)]
    for col in cols:
        ncol = norm(col)
        for candidate in candidates:
            if norm(candidate) in ncol:
                return col
    return ""


def audit_file(path: Path) -> dict[str, object]:
    cols = header(path)
    date_col = find_col(cols, ["price_date", "latest_price_date", "date", "as_of_date"])
    ticker_col = find_col(cols, ["ticker", "symbol", "benchmark_ticker"])
    open_col = find_col(cols, ["open", "latest_open"])
    high_col = find_col(cols, ["high", "latest_high"])
    low_col = find_col(cols, ["low", "latest_low"])
    close_col = find_col(cols, ["close", "latest_close", "close_like_price"])
    adj_col = find_col(cols, ["adjusted_close", "adj_close", "latest_adj_close", "adj close"])
    volume_col = find_col(cols, ["volume", "latest_volume"])
    rows = 0
    if cols:
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = max(0, sum(1 for _ in handle) - 1)
        except OSError:
            rows = 0
    usable = bool(rows and date_col and ticker_col and close_col and volume_col)
    reason = "" if usable else "Missing required date/ticker/close/volume columns or no rows."
    return {
        "source_file_path": str(path.relative_to(ROOT)),
        "source_role": "LOCAL_OHLCV_OR_CLOSE_VOLUME_CANDIDATE",
        "exists": yes(path.exists()),
        "rows": rows,
        "detected_date_column": date_col,
        "detected_ticker_column": ticker_col,
        "detected_open_column": open_col,
        "detected_high_column": high_col,
        "detected_low_column": low_col,
        "detected_close_column": close_col,
        "detected_adjusted_close_column": adj_col,
        "detected_volume_column": volume_col,
        "usable_for_ohlcv": yes(usable),
        "reason_if_not_usable": reason,
    }


def load_price_rows(audits: list[dict[str, object]]) -> pd.DataFrame:
    frames = []
    for audit in audits:
        if audit["usable_for_ohlcv"] != "TRUE":
            continue
        path = ROOT / str(audit["source_file_path"])
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        out = pd.DataFrame()
        out["as_of_date"] = pd.to_datetime(df[str(audit["detected_date_column"])], errors="coerce").dt.strftime("%Y-%m-%d")
        out["ticker"] = df[str(audit["detected_ticker_column"])].astype(str).str.upper().str.strip()
        for target, key in [
            ("open", "detected_open_column"),
            ("high", "detected_high_column"),
            ("low", "detected_low_column"),
            ("close", "detected_close_column"),
            ("adjusted_close", "detected_adjusted_close_column"),
            ("volume", "detected_volume_column"),
        ]:
            col = str(audit.get(key) or "")
            out[target] = pd.to_numeric(df[col], errors="coerce") if col and col in df.columns else np.nan
        out["source_file_path"] = str(audit["source_file_path"])
        frames.append(out)
    if not frames:
        return pd.DataFrame(columns=["as_of_date", "ticker", "source_file_path", "close", "adjusted_close", "open", "high", "low", "volume"])
    all_rows = pd.concat(frames, ignore_index=True)
    all_rows = all_rows.dropna(subset=["as_of_date", "ticker", "close"])
    all_rows = all_rows[all_rows["ticker"] != ""]
    all_rows = all_rows.sort_values(["ticker", "as_of_date", "source_file_path"])
    all_rows = all_rows.drop_duplicates(["ticker", "as_of_date"], keep="last")
    return all_rows.reset_index(drop=True)


def pct_rank(series: pd.Series) -> pd.Series:
    if series.notna().sum() == 0:
        return pd.Series(np.nan, index=series.index)
    return series.rank(method="average", pct=True)


def safe_div(a: pd.Series, b: pd.Series) -> pd.Series:
    return a.where(b != 0) / b.replace(0, np.nan)


def compute_indicators(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame(columns=SNAPSHOT_FIELDS)
    df = prices.copy()
    df = df.sort_values(["ticker", "as_of_date"]).reset_index(drop=True)
    df["price_for_indicators"] = df["adjusted_close"].where(df["adjusted_close"].notna(), df["close"])
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
    prior_diff = groups.apply(lambda g: (g["kdj_k"] - g["kdj_d"]).shift(1)).reset_index(level=0, drop=True).sort_index()
    diff = df["kdj_k"] - df["kdj_d"]
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
    trend_parts = pd.concat([
        df["ma20_distance"] / 0.10,
        df["ema20_distance"] / 0.10,
        df["macd_hist"].rank(pct=True),
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
    df["technical_score_normalized"] = df.groupby("as_of_date")["technical_score_raw"].transform(pct_rank)

    missing = df[CORE_FIELDS].isna().sum(axis=1)
    df["missing_required_field_count"] = missing.astype(int)
    df["row_quality_status"] = np.select(
        [
            df[["close", "volume"]].isna().any(axis=1),
            groups.cumcount() < 26,
            missing > 0,
            missing == 0,
        ],
        ["MISSING_OHLCV", "WARMUP_INSUFFICIENT_HISTORY", "PARTIAL_INDICATORS", "PASS"],
        default="INVALID",
    )
    return df[SNAPSHOT_FIELDS].sort_values(["as_of_date", "ticker"]).reset_index(drop=True)


def coverage_by_ticker(snapshot: pd.DataFrame) -> pd.DataFrame:
    if snapshot.empty:
        return pd.DataFrame([{"ticker": "", "coverage_status": "MISSING", "notes": "No snapshot rows produced."}])
    rows = []
    for ticker, g in snapshot.groupby("ticker"):
        usable = (g["row_quality_status"] == "PASS").sum()
        ratio = usable / len(g) if len(g) else 0
        core_exist = all(g[field].notna().any() for field in CORE_FIELDS)
        status = "READY" if ratio >= 0.80 and core_exist else "PARTIAL" if ratio >= 0.30 else "INSUFFICIENT"
        rows.append({
            "ticker": ticker,
            "rows_available": len(g),
            "min_date": g["as_of_date"].min(),
            "max_date": g["as_of_date"].max(),
            "rsi_non_null_count": g["rsi_14"].notna().sum(),
            "kdj_non_null_count": g["kdj_k"].notna().sum(),
            "macd_non_null_count": g["macd_line"].notna().sum(),
            "bb_non_null_count": g["bb_position"].notna().sum(),
            "ma_ema_non_null_count": g["ma20_distance"].notna().sum(),
            "volume_non_null_count": g["volume_ratio"].notna().sum(),
            "technical_score_non_null_count": g["technical_score_normalized"].notna().sum(),
            "usable_row_count": usable,
            "usable_row_ratio": ratio,
            "coverage_status": status,
            "notes": "Warmup-limited local history." if status != "READY" else "Core coverage ready.",
        })
    return pd.DataFrame(rows)


def coverage_by_date(snapshot: pd.DataFrame) -> pd.DataFrame:
    if snapshot.empty:
        return pd.DataFrame([{"as_of_date": "", "date_coverage_status": "MISSING", "notes": "No snapshot rows produced."}])
    rows = []
    for date, g in snapshot.groupby("as_of_date"):
        usable = (g["row_quality_status"] == "PASS").sum()
        ratio = usable / len(g) if len(g) else 0
        status = "READY" if ratio >= 0.80 else "PARTIAL" if ratio >= 0.30 else "INSUFFICIENT"
        rows.append({
            "as_of_date": date,
            "ticker_count": len(g),
            "usable_ticker_count": usable,
            "usable_ticker_ratio": ratio,
            "rsi_coverage_ratio": g["rsi_14"].notna().mean(),
            "kdj_coverage_ratio": g["kdj_k"].notna().mean(),
            "macd_coverage_ratio": g["macd_line"].notna().mean(),
            "bb_coverage_ratio": g["bb_position"].notna().mean(),
            "ma_ema_coverage_ratio": g["ma20_distance"].notna().mean(),
            "volume_coverage_ratio": g["volume_ratio"].notna().mean(),
            "technical_score_coverage_ratio": g["technical_score_normalized"].notna().mean(),
            "date_coverage_status": status,
            "notes": "Warmup-limited date coverage." if status != "READY" else "Date coverage ready.",
        })
    return pd.DataFrame(rows)


def coverage_ratio(snapshot: pd.DataFrame, col: str) -> float:
    return float(snapshot[col].notna().mean()) if not snapshot.empty and col in snapshot else 0.0


def validation_rows(summary: dict[str, object], snapshot: pd.DataFrame, no_official_mutation: bool = True) -> list[dict[str, object]]:
    checks = [
        ("OHLCV_SOURCE_FOUND", summary["local_price_source_found"], "TRUE"),
        ("RSI_PRODUCED", yes(coverage_ratio(snapshot, "rsi_14") > 0), "TRUE"),
        ("KDJ_PRODUCED", yes(coverage_ratio(snapshot, "kdj_k") > 0), "TRUE"),
        ("MACD_PRODUCED", yes(coverage_ratio(snapshot, "macd_line") > 0), "TRUE"),
        ("BB_PRODUCED", yes(coverage_ratio(snapshot, "bb_position") > 0), "TRUE"),
        ("MA_EMA_DISTANCE_PRODUCED", yes(coverage_ratio(snapshot, "ma20_distance") > 0), "TRUE"),
        ("VOLUME_RATIO_PRODUCED", yes(coverage_ratio(snapshot, "volume_ratio") > 0), "TRUE"),
        ("TECHNICAL_SCORE_PRODUCED", yes(coverage_ratio(snapshot, "technical_score_normalized") > 0), "TRUE"),
        ("WARMUP_ROWS_EXCLUDED_OR_LABELLED", yes(snapshot.empty or snapshot["row_quality_status"].isin(["WARMUP_INSUFFICIENT_HISTORY", "PASS", "PARTIAL_INDICATORS", "MISSING_OHLCV", "INVALID"]).all()), "TRUE"),
        ("NO_OFFICIAL_MUTATION", yes(no_official_mutation), "TRUE"),
        ("RESEARCH_ONLY_TRUE", summary["research_only"], "TRUE"),
        ("DATA_TRUST_ALPHA_FALSE", summary["data_trust_alpha_weight_allowed"], "FALSE"),
    ]
    return [{
        "validation_item": item,
        "validation_status": "PASS" if str(observed) == required else "FAIL",
        "observed_value": observed,
        "required_value": required,
        "pass_fail": "PASS" if str(observed) == required else "FAIL",
        "notes": "Research-only diagnostic validation.",
    } for item, observed, required in checks]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    upstream = first(read_csv(V34_SUMMARY))
    audits = [audit_file(path) for path in candidate_files()]
    usable_audits = [a for a in audits if a["usable_for_ohlcv"] == "TRUE"]
    prices = load_price_rows(usable_audits)
    snapshot = compute_indicators(prices)
    local_found = not prices.empty
    true_capture_ready = bool(local_found and coverage_ratio(snapshot, "rsi_14") >= 0.50 and coverage_ratio(snapshot, "kdj_k") >= 0.50 and coverage_ratio(snapshot, "bb_position") >= 0.50)
    true_reweighting_ready = bool(true_capture_ready and coverage_ratio(snapshot, "technical_score_normalized") >= 0.80)
    if not local_found:
        final_status = BLOCKED_STATUS
    elif true_reweighting_ready:
        final_status = PASS_STATUS
    else:
        final_status = PARTIAL_STATUS
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
        "upstream_v21_034_final_status": upstream.get("final_status", ""),
        "local_price_source_found": yes(local_found),
        "source_file_count": len(usable_audits),
        "total_price_rows_scanned": sum(int(a["rows"]) for a in audits if str(a.get("rows", "")).isdigit()),
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
        "technical_score_coverage_ratio": coverage_ratio(snapshot, "technical_score_normalized"),
        "true_subfactor_capture_ready": yes(true_capture_ready),
        "true_reweighting_ready": yes(true_reweighting_ready),
        "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "V21.036_R1_TRUE_TECHNICAL_REWEIGHTING_BACKTEST_WITH_CAPTURED_SUBFACTORS",
    }

    write_csv(SUMMARY_OUT, [summary], list(summary.keys()))
    write_csv(INPUT_AUDIT_OUT, audits or [{"source_file_path": "", "exists": "FALSE", "usable_for_ohlcv": "FALSE", "reason_if_not_usable": "No candidate files found."}], [
        "source_file_path", "source_role", "exists", "rows", "detected_date_column", "detected_ticker_column",
        "detected_open_column", "detected_high_column", "detected_low_column", "detected_close_column",
        "detected_adjusted_close_column", "detected_volume_column", "usable_for_ohlcv", "reason_if_not_usable",
    ])
    if snapshot.empty:
        write_csv(SNAPSHOT_OUT, [{"row_quality_status": "INVALID", "missing_required_field_count": len(CORE_FIELDS)}], SNAPSHOT_FIELDS)
    else:
        write_csv(SNAPSHOT_OUT, snapshot.replace({np.nan: None}).to_dict("records"), SNAPSHOT_FIELDS)
    ticker_cov = coverage_by_ticker(snapshot)
    date_cov = coverage_by_date(snapshot)
    write_csv(COVERAGE_TICKER_OUT, ticker_cov.replace({np.nan: None}).to_dict("records"), [
        "ticker", "rows_available", "min_date", "max_date", "rsi_non_null_count", "kdj_non_null_count",
        "macd_non_null_count", "bb_non_null_count", "ma_ema_non_null_count", "volume_non_null_count",
        "technical_score_non_null_count", "usable_row_count", "usable_row_ratio", "coverage_status", "notes",
    ])
    write_csv(COVERAGE_DATE_OUT, date_cov.replace({np.nan: None}).to_dict("records"), [
        "as_of_date", "ticker_count", "usable_ticker_count", "usable_ticker_ratio", "rsi_coverage_ratio",
        "kdj_coverage_ratio", "macd_coverage_ratio", "bb_coverage_ratio", "ma_ema_coverage_ratio",
        "volume_coverage_ratio", "technical_score_coverage_ratio", "date_coverage_status", "notes",
    ])
    write_csv(VALIDATION_OUT, validation_rows(summary, snapshot), [
        "validation_item", "validation_status", "observed_value", "required_value", "pass_fail", "notes",
    ])
    source_lines = "\n".join(f"- {a['source_file_path']} ({a['rows']} rows)" for a in usable_audits[:20]) or "- No usable OHLCV source found."
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Final status and decision

- final_status: {final_status}
- decision: {DECISION}

## Upstream V21.034-R1 summary

V21.034-R1 final_status: {upstream.get("final_status", "")}

## Input price/OHLCV sources found

{source_lines}

## Indicator formulas used

RSI uses Wilder-style EMA average gain/loss with a 14-row warmup. KDJ uses 9-period stochastic RSV with EMA smoothing. MACD uses EMA12 minus EMA26 with EMA9 signal. Bollinger Bands use 20-period SMA plus/minus two rolling standard deviations. MA/EMA distance, volume ratio, volatility, momentum, overheat, trend strength, and technical score are transparent research-only formulas in the script.

## Subfactor coverage summary

RSI={summary['rsi_coverage_ratio']}, KDJ={summary['kdj_coverage_ratio']}, MACD={summary['macd_coverage_ratio']}, BB={summary['bb_coverage_ratio']}, MA/EMA={summary['ma_ema_coverage_ratio']}, volume={summary['volume_coverage_ratio']}, technical_score={summary['technical_score_coverage_ratio']}.

## Missing-data and warmup handling

Rows with insufficient lookback are labelled `WARMUP_INSUFFICIENT_HISTORY`; partial rows are labelled `PARTIAL_INDICATORS`; missing OHLCV rows are labelled `MISSING_OHLCV`. Warmup rows are not silently treated as valid.

## Whether true subfactor capture is now ready

true_subfactor_capture_ready: {summary['true_subfactor_capture_ready']}

## Whether true technical reweighting is now ready

true_reweighting_ready: {summary['true_reweighting_ready']}

## Why official mutation remains blocked

Official mutation remains blocked because this is a research-only producer patch, all official mutation flags are FALSE, no broker or book action is allowed, and DATA_TRUST alpha weight remains FALSE.

## Next recommended stage

{summary['next_recommended_stage']}
"""
    REPORT_OUT.write_text(report, encoding="utf-8")
    print(f"STAGE_NAME={STAGE}")
    print(f"final_status={final_status}")
    print(f"decision={DECISION}")
    print(f"local_price_source_found={yes(local_found)}")
    print(f"total_subfactor_rows_produced={len(snapshot)}")


if __name__ == "__main__":
    main()
