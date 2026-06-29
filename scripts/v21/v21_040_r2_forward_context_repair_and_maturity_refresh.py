#!/usr/bin/env python
"""V21.040-R2 forward context repair and maturity refresh.

Research-only repair stage that builds a canonical forward-return ledger,
derives selective context labels from local evidence where defensible, and
hardens context interpretation gates.
"""

from __future__ import annotations

import csv
import hashlib
import math
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.040-R2_FORWARD_CONTEXT_REPAIR_AND_MATURITY_REFRESH"
PASS_STATUS = "PASS_V21_040_R2_FORWARD_CONTEXT_REPAIR_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_040_R2_CONTEXT_REPAIR_INCOMPLETE"
BLOCKED_STATUS = "BLOCKED_V21_040_R2_INPUTS_MISSING"
RESEARCH_BLOCKED_STATUS = "BLOCKED_V21_040_R2_RESEARCH_ONLY_VIOLATION"

DECISION_READY = "FORWARD_CONTEXT_REPAIR_READY_FOR_TECHNICAL_REWEIGHTING_RETEST"
DECISION_PARTIAL = "FORWARD_CONTEXT_REPAIR_PARTIAL_MISSING_CONTEXT_REMAINS"
DECISION_OVERBROADCAST = "FORWARD_CONTEXT_REPAIR_BLOCKED_CONTEXT_OVERBROADCAST_REMAINS"
DECISION_BLOCKED = "FORWARD_CONTEXT_REPAIR_BLOCKED_INPUTS_MISSING"

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

V38_SNAPSHOT = OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv"
V39_SUMMARY = OUT_DIR / "V21_039_R1_TRUE_TECHNICAL_REWEIGHTING_BACKTEST_SUMMARY.csv"
R1_SUMMARY = OUT_DIR / "V21_040_R1_MATURED_FORWARD_CONTEXT_ALIGNMENT_SUMMARY.csv"

SUMMARY_OUT = OUT_DIR / "V21_040_R2_FORWARD_CONTEXT_REPAIR_SUMMARY.csv"
LEDGER_OUT = OUT_DIR / "V21_040_R2_CANONICAL_FORWARD_RETURN_LEDGER.csv"
MAPPING_OUT = OUT_DIR / "V21_040_R2_CONTEXT_REPAIR_MAPPING.csv"
CONTEXT_OUT = OUT_DIR / "V21_040_R2_CONTEXT_SELECTIVITY_AND_MATURITY_AUDIT.csv"
PERF_OUT = OUT_DIR / "V21_040_R2_TECHNICAL_PERFORMANCE_BY_REPAIRED_CONTEXT_WINDOW.csv"
PENDING_OUT = OUT_DIR / "V21_040_R2_PENDING_MATURITY_REFRESH.csv"
REPAIR_OUT = OUT_DIR / "V21_040_R2_FORWARD_CONTEXT_REPAIR_QUEUE.csv"
VALIDATION_OUT = OUT_DIR / "V21_040_R2_VALIDATION_MATRIX.csv"
REPORT_OUT = READ_CENTER_DIR / "V21_040_R2_FORWARD_CONTEXT_REPAIR_AND_MATURITY_REFRESH_REPORT.md"

WINDOWS = ["5D", "10D", "20D", "60D"]
MIN_CONTEXT_MATURITY_RATIO = 0.50
MIN_CONTEXT_MATURED_ROWS = 30
MIN_TOP_BUCKET_ROWS = 30


def yes(value: bool) -> str:
    return "TRUE" if bool(value) else "FALSE"


def clean(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def fmt(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, (float, np.floating)):
        if math.isnan(float(value)) or math.isinf(float(value)):
            return ""
        return f"{float(value):.10f}"
    return value


def norm(text: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", clean(text).lower()).strip("_")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def read_csv_dicts(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{k: clean(v) for k, v in row.items()} for row in csv.DictReader(handle)]


def first(path: Path) -> dict[str, str]:
    rows = read_csv_dicts(path)
    return rows[0] if rows else {}


def header(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return next(csv.reader(handle), [])
    except (OSError, UnicodeDecodeError, StopIteration):
        return []


def find_col(cols: list[str], candidates: list[str]) -> str:
    by_norm = {norm(col): col for col in cols}
    for candidate in candidates:
        key = norm(candidate)
        if key in by_norm:
            return by_norm[key]
    for col in cols:
        ncol = norm(col)
        for candidate in candidates:
            if norm(candidate) in ncol:
                return col
    return ""


def find_semantic_col(cols: list[str], candidates: list[str]) -> str:
    by_norm = {norm(col): col for col in cols}
    for candidate in candidates:
        key = norm(candidate)
        if key in by_norm:
            return by_norm[key]
    rejected_tokens = ("score", "rank", "count", "return", "ratio", "weight", "price", "date")
    for col in cols:
        ncol = norm(col)
        if any(token in ncol for token in rejected_tokens):
            continue
        for candidate in candidates:
            if norm(candidate) in ncol:
                return col
    return ""


def normalize_window(value: object) -> str:
    text = clean(value).upper().replace("_", "").replace(" ", "")
    text = text.replace("DAYS", "D").replace("DAY", "D")
    if text in {"5", "10", "20", "60"}:
        return f"{text}D"
    return text


def date_str(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", format="mixed").dt.strftime("%Y-%m-%d")


def surrogate_id(as_of_date: object, ticker: object, window: object, source: object, row_number: int) -> str:
    raw = "|".join([clean(as_of_date), clean(ticker).upper(), normalize_window(window), clean(source), str(row_number)])
    return "SURROGATE_OBSERVATION_ID_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def status_bucket(status: object, ret: object, price_missing_hint: object = "") -> str:
    text = norm(f"{status} {price_missing_hint}")
    has_return = pd.notna(ret)
    if "price_missing" in text or "missing_price" in text or ("missing" in text and not has_return):
        return "PRICE_MISSING"
    if "pending" in text or "not_matured" in text or "not_due" in text or "scheduled" in text:
        return "PENDING"
    if "reject" in text or "leakage" in text:
        return "PRICE_MISSING"
    if has_return:
        return "MATURED"
    return "UNKNOWN"


def candidate_roots() -> list[Path]:
    return [
        ROOT / "outputs" / "v21" / "factors",
        ROOT / "outputs" / "v21" / "consolidation",
        ROOT / "outputs" / "v21" / "read_center",
        ROOT / "outputs" / "v21" / "shadow_observation",
        ROOT / "outputs" / "v21" / "factor_backtest",
        ROOT / "outputs" / "v21" / "ablation",
        ROOT / "outputs" / "v21" / "audit",
        ROOT / "outputs" / "v20" / "factors",
        ROOT / "outputs" / "v20" / "consolidation",
        ROOT / "outputs" / "v20" / "random_weight_backtest",
        ROOT / "outputs" / "v20" / "forward_observation",
        ROOT / "outputs" / "v20" / "walk_forward",
        ROOT / "inputs" / "v21" / "historical_ohlcv_cache",
    ]


def discover_forward_files() -> list[Path]:
    files: set[Path] = set()
    name_tokens = ("forward", "matur", "outcome", "observation", "context", "regime", "benchmark")
    for root in candidate_roots():
        if not root.exists():
            continue
        for path in root.rglob("*.csv"):
            if path.name.startswith("V21_040_R"):
                continue
            if not any(token in path.name.lower() for token in name_tokens):
                continue
            cols = header(path)
            ncols = {norm(c) for c in cols}
            has_key = bool({"ticker", "symbol"} & ncols) and bool({"as_of_date", "signal_date", "date"} & ncols)
            has_long = bool({"forward_window", "forward_return_window"} & ncols) and bool(
                {"realized_forward_return", "forward_return", "ticker_forward_return", "row_level_return"} & ncols
            )
            has_wide = any(c in ncols for c in ("forward_return_5d", "forward_return_10d", "forward_return_20d", "forward_return_60d"))
            has_schedule = bool({"maturity_status", "observation_status", "outcome_status", "due_date", "scheduled_observation_date"} & ncols)
            if has_key and (has_long or has_wide or has_schedule):
                files.add(path)
    return sorted(files, key=lambda p: rel(p).lower())


def source_priority(source: object) -> int:
    text = clean(source).lower()
    if "v21_030_realized_forward_returns" in text:
        return 100
    if "v21_030" in text or "v21_033" in text:
        return 90
    if "v20_204" in text:
        return 80
    if "v20_201" in text:
        return 70
    if "ablation" in text or "audit" in text:
        return 40
    return 50


def normalize_forward_file(path: Path) -> pd.DataFrame:
    cols = header(path)
    if not cols:
        return pd.DataFrame()
    date_col = find_col(cols, ["as_of_date", "signal_date", "date"])
    ticker_col = find_col(cols, ["ticker", "symbol"])
    window_col = find_col(cols, ["forward_return_window", "forward_window", "window"])
    ret_col = find_col(cols, ["realized_forward_return", "forward_return", "ticker_forward_return", "row_level_return"])
    maturity_col = find_col(cols, ["maturity_status", "observation_status", "outcome_status", "diagnostic_status", "eligibility_status"])
    due_col = find_col(cols, ["maturity_date", "due_date", "scheduled_observation_date", "exit_date"])
    obs_col = find_col(cols, ["observation_id", "trial_id", "benchmark_return_id", "comparison_id"])
    context_col = find_semantic_col(cols, ["context_label", "context_key", "context_combination", "regime_label", "regime_bucket", "market_regime"])
    regime_col = find_semantic_col(cols, ["regime_label", "regime_bucket", "market_regime", "qqq_trend_regime"])
    bench_col = find_col(cols, ["benchmark_forward_return", "benchmark_return"])
    bench_name_col = find_semantic_col(cols, ["benchmark_name", "benchmark", "benchmark_ticker", "benchmark_symbol"])
    price_missing_col = find_col(cols, ["price_missing", "forward_price_available", "data_available", "future_price_available"])
    if not date_col or not ticker_col:
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return pd.DataFrame()
    base = pd.DataFrame()
    base["as_of_date"] = date_str(df[date_col])
    base["ticker"] = df[ticker_col].astype(str).str.upper().str.strip()
    base["maturity_date"] = date_str(df[due_col]) if due_col else ""
    base["original_context_label"] = df[context_col].map(clean) if context_col else ""
    base["regime_label"] = df[regime_col].map(clean) if regime_col else ""
    base["benchmark_primary"] = df[bench_name_col].map(clean) if bench_name_col else ""
    base["benchmark_return"] = pd.to_numeric(df[bench_col], errors="coerce") if bench_col else np.nan
    base["raw_status"] = df[maturity_col].map(clean) if maturity_col else ""
    base["source_file_path"] = rel(path)
    base["source_priority"] = source_priority(path)
    base["source_row_number"] = np.arange(1, len(df) + 1)
    base["observation_id"] = df[obs_col].map(clean) if obs_col else ""
    base["observation_id_source"] = "ORIGINAL" if obs_col else "SURROGATE"
    base["price_missing_hint"] = df[price_missing_col].map(clean) if price_missing_col else ""

    frames: list[pd.DataFrame] = []
    if window_col and ret_col:
        out = base.copy()
        out["forward_window"] = df[window_col].map(normalize_window)
        out["realized_forward_return"] = pd.to_numeric(df[ret_col], errors="coerce")
        frames.append(out)
    for window, col in {
        "5D": find_col(cols, ["forward_return_5d"]),
        "10D": find_col(cols, ["forward_return_10d"]),
        "20D": find_col(cols, ["forward_return_20d"]),
        "60D": find_col(cols, ["forward_return_60d"]),
    }.items():
        if col:
            out = base.copy()
            out["forward_window"] = window
            out["realized_forward_return"] = pd.to_numeric(df[col], errors="coerce")
            frames.append(out)
    if not frames and window_col:
        out = base.copy()
        out["forward_window"] = df[window_col].map(normalize_window)
        out["realized_forward_return"] = np.nan
        frames.append(out)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out[out["forward_window"].isin(WINDOWS)].copy()
    out = out.dropna(subset=["as_of_date"])
    out = out[out["ticker"].ne("")]
    if out.empty:
        return out
    missing_obs = out["observation_id"].map(clean).eq("")
    if missing_obs.any():
        out.loc[missing_obs, "observation_id"] = [
            surrogate_id(r.as_of_date, r.ticker, r.forward_window, r.source_file_path, int(r.source_row_number))
            for r in out.loc[missing_obs].itertuples(index=False)
        ]
        out.loc[missing_obs, "observation_id_source"] = "SURROGATE"
    out["maturity_status"] = [
        status_bucket(status, ret, hint)
        for status, ret, hint in zip(out["raw_status"], out["realized_forward_return"], out["price_missing_hint"])
    ]
    out["price_missing"] = yes(False)
    out.loc[out["maturity_status"].eq("PRICE_MISSING"), "price_missing"] = "TRUE"
    out["original_context_label"] = out["original_context_label"].replace("", np.nan)
    out["original_context_label"] = out["original_context_label"].fillna(out["regime_label"].replace("", np.nan)).fillna("MISSING_CONTEXT_LABEL")
    return out


def load_forward_observations() -> tuple[pd.DataFrame, list[str]]:
    frames = []
    sources = []
    for path in discover_forward_files():
        df = normalize_forward_file(path)
        if not df.empty:
            frames.append(df)
            sources.append(rel(path))
    if not frames:
        return pd.DataFrame(), []
    out = pd.concat(frames, ignore_index=True)
    maturity_priority = out["maturity_status"].map({"MATURED": 4, "PENDING": 3, "PRICE_MISSING": 2, "UNKNOWN": 1}).fillna(0)
    out = out.assign(_maturity_priority=maturity_priority)
    out = out.sort_values(["as_of_date", "ticker", "forward_window", "original_context_label", "_maturity_priority", "source_priority", "source_file_path"])
    out = out.drop_duplicates(["as_of_date", "ticker", "forward_window", "original_context_label", "observation_id"], keep="last")
    return out.drop(columns=["_maturity_priority"]), sources


def load_technical_snapshot() -> pd.DataFrame:
    if not V38_SNAPSHOT.exists():
        return pd.DataFrame()
    try:
        cols = pd.read_csv(V38_SNAPSHOT, nrows=0).columns.tolist()
        use = [c for c in [
            "as_of_date", "ticker", "technical_score_normalized", "rsi_14", "bb_position",
            "ma20_distance", "ma50_distance", "ema20_distance", "volatility_20", "trend_strength_score",
        ] if c in cols]
        snap = pd.read_csv(V38_SNAPSHOT, usecols=use, low_memory=False)
    except Exception:
        return pd.DataFrame()
    if snap.empty or not {"as_of_date", "ticker"}.issubset(snap.columns):
        return pd.DataFrame()
    snap["as_of_date"] = date_str(snap["as_of_date"])
    snap["ticker"] = snap["ticker"].astype(str).str.upper().str.strip()
    for col in snap.columns:
        if col not in {"as_of_date", "ticker"}:
            snap[col] = pd.to_numeric(snap[col], errors="coerce")
    return snap.dropna(subset=["as_of_date", "ticker"])


def derive_context(row: pd.Series) -> tuple[str, str, str, str]:
    original = clean(row.get("original_context_label")) or "MISSING_CONTEXT_LABEL"
    if original != "MISSING_CONTEXT_LABEL":
        return original, "ORIGINAL_CONTEXT_LABEL", "ORIGINAL_CONTEXT_LABEL", "Original context label preserved."
    if pd.isna(row.get("technical_score_normalized")):
        return "MISSING_CONTEXT_LABEL", "NO_REPAIR_SOURCE", "REPAIR_PENDING", "No joinable V21.038 technical subfactor row."
    trend = row.get("trend_strength_score")
    rsi = row.get("rsi_14")
    bb = row.get("bb_position")
    volatility = row.get("volatility_20")
    ma_vals = [row.get("ma20_distance"), row.get("ma50_distance"), row.get("ema20_distance")]
    ma_vals = [float(v) for v in ma_vals if pd.notna(v)]
    avg_abs_ma = float(np.mean(np.abs(ma_vals))) if ma_vals else np.nan
    pieces = []
    if pd.notna(rsi) and float(rsi) >= 70:
        pieces.append("RSI_OVERHEAT_HEALTHY_TREND" if pd.notna(trend) and float(trend) >= 0.55 else "RSI_OVERHEAT_WEAK_TREND")
    elif pd.notna(trend):
        pieces.append("TECH_TREND_HEALTHY" if float(trend) >= 0.55 else "TECH_TREND_WEAK")
    if (pd.notna(bb) and (float(bb) >= 0.85 or float(bb) <= 0.15)) or (pd.notna(avg_abs_ma) and avg_abs_ma >= 0.08):
        pieces.append("BB_MA_EXTENSION_HIGH")
    elif pd.notna(bb) or pd.notna(avg_abs_ma):
        pieces.append("BB_MA_EXTENSION_NORMAL")
    if pd.notna(volatility):
        pieces.append("HIGH_VOLATILITY" if float(volatility) >= float(row.get("volatility_date_p70", np.inf)) else "NORMAL_VOLATILITY")
    if not pieces:
        return "MISSING_CONTEXT_LABEL", "NO_REPAIR_SOURCE", "REPAIR_PENDING", "Technical subfactor row lacks context-derivation fields."
    return "__".join(pieces[:3]), "V21_038_TRUE_TECHNICAL_SUBFACTORS", "REPAIRED_DERIVED", "Derived from local V21.038 technical trend/RSI/BB-MA/volatility fields."


def repair_context(obs: pd.DataFrame, snap: pd.DataFrame) -> pd.DataFrame:
    if obs.empty:
        return obs.copy()
    out = obs.copy()
    if not snap.empty:
        snap2 = snap.copy()
        if "volatility_20" in snap2:
            snap2["volatility_date_p70"] = snap2.groupby("as_of_date")["volatility_20"].transform(lambda s: s.quantile(0.70))
        out = out.merge(snap2, on=["as_of_date", "ticker"], how="left")
    else:
        out["technical_score_normalized"] = np.nan
    derived = out.apply(derive_context, axis=1, result_type="expand")
    out["repaired_context_label"] = derived[0]
    out["repaired_context_source"] = derived[1]
    out["context_repair_status"] = derived[2]
    out["context_repair_reason"] = derived[3]
    return out


def canonical_ledger(obs: pd.DataFrame) -> pd.DataFrame:
    if obs.empty:
        return pd.DataFrame()
    out = obs.copy()
    out["row_quality_status"] = np.where(
        out["ticker"].ne("") & out["as_of_date"].notna() & out["forward_window"].isin(WINDOWS),
        "PASS_CANONICAL_RESEARCH_LEDGER",
        "FAIL_MISSING_REQUIRED_FIELD",
    )
    fields = [
        "observation_id", "observation_id_source", "ticker", "as_of_date", "forward_window", "maturity_date",
        "maturity_status", "realized_forward_return", "price_missing", "source_file_path", "source_priority",
        "original_context_label", "repaired_context_label", "repaired_context_source", "context_repair_status",
        "context_repair_reason", "benchmark_primary", "benchmark_return", "row_quality_status",
    ]
    out = out.sort_values(["as_of_date", "ticker", "forward_window", "repaired_context_label", "source_priority", "source_file_path"])
    out = out.drop_duplicates(["ticker", "as_of_date", "forward_window", "repaired_context_label", "observation_id"], keep="last")
    return out[fields]


def mean_for(df: pd.DataFrame, window: str) -> object:
    vals = pd.to_numeric(df.loc[df["forward_window"] == window, "realized_forward_return"], errors="coerce").dropna()
    return "" if vals.empty else float(vals.mean())


def hit_for(df: pd.DataFrame, window: str) -> object:
    vals = pd.to_numeric(df.loc[df["forward_window"] == window, "realized_forward_return"], errors="coerce").dropna()
    return "" if vals.empty else float((vals > 0).mean())


def selectivity_status(count: int, total: int) -> str:
    if total <= 0:
        return "UNKNOWN"
    ratio = count / total
    if count == 0:
        return "EMPTY"
    if ratio < 0.02:
        return "TOO_NARROW"
    if ratio <= 0.80:
        return "SELECTIVE"
    return "BROADCAST_OVERWIDE"


def context_audit(ledger: pd.DataFrame) -> list[dict[str, object]]:
    if ledger.empty:
        return [{
            "repaired_context_label": "UNKNOWN", "total_observations": 0, "matured_observations": 0,
            "pending_observations": 0, "price_missing_observations": 0, "distinct_ticker_count": 0,
            "total_distinct_ticker_count": 0, "ticker_coverage_ratio": "", "distinct_as_of_dates": 0,
            "maturity_ratio": 0, "maturity_status": "UNKNOWN", "selectivity_status": "UNKNOWN",
            "alpha_interpretation_allowed": "FALSE", "failure_reason": "CANONICAL_LEDGER_MISSING",
            "repair_recommendation": "Create canonical research-only forward-return ledger.",
        }]
    total_tickers = int(ledger["ticker"].nunique())
    rows = []
    for label, g in ledger.groupby("repaired_context_label", dropna=False):
        matured = g[g["maturity_status"] == "MATURED"]
        pending = g[g["maturity_status"] == "PENDING"]
        price_missing = g[g["maturity_status"] == "PRICE_MISSING"]
        ticker_count = int(g["ticker"].nunique())
        ticker_ratio = ticker_count / total_tickers if total_tickers else np.nan
        sel = selectivity_status(ticker_count, total_tickers)
        maturity_ratio = len(matured) / len(g) if len(g) else 0.0
        maturity = "SUFFICIENT" if len(matured) >= MIN_CONTEXT_MATURED_ROWS and maturity_ratio >= MIN_CONTEXT_MATURITY_RATIO else "LOW_CONTEXT_MATURITY"
        reasons = []
        if clean(label) == "MISSING_CONTEXT_LABEL":
            reasons.append("MISSING_CONTEXT_LABEL")
        if sel != "SELECTIVE":
            reasons.append(sel)
        if maturity != "SUFFICIENT":
            reasons.append(maturity)
        allowed = clean(label) != "MISSING_CONTEXT_LABEL" and sel == "SELECTIVE" and maturity == "SUFFICIENT"
        rows.append({
            "repaired_context_label": clean(label) or "MISSING_CONTEXT_LABEL",
            "total_observations": len(g),
            "matured_observations": len(matured),
            "pending_observations": len(pending),
            "price_missing_observations": len(price_missing),
            "distinct_ticker_count": ticker_count,
            "total_distinct_ticker_count": total_tickers,
            "ticker_coverage_ratio": ticker_ratio,
            "distinct_as_of_dates": int(g["as_of_date"].nunique()),
            "maturity_ratio": maturity_ratio,
            "matured_5d_count": int((matured["forward_window"] == "5D").sum()),
            "matured_10d_count": int((matured["forward_window"] == "10D").sum()),
            "matured_20d_count": int((matured["forward_window"] == "20D").sum()),
            "matured_60d_count": int((matured["forward_window"] == "60D").sum()),
            "mean_forward_return_5d": mean_for(matured, "5D"),
            "mean_forward_return_10d": mean_for(matured, "10D"),
            "mean_forward_return_20d": mean_for(matured, "20D"),
            "mean_forward_return_60d": mean_for(matured, "60D"),
            "hit_rate_5d": hit_for(matured, "5D"),
            "hit_rate_10d": hit_for(matured, "10D"),
            "hit_rate_20d": hit_for(matured, "20D"),
            "hit_rate_60d": hit_for(matured, "60D"),
            "selectivity_status": sel,
            "maturity_status": maturity,
            "alpha_interpretation_allowed": yes(allowed),
            "failure_reason": "|".join(reasons),
            "repair_recommendation": "Keep blocked from alpha interpretation; split/backfill with stronger context evidence." if reasons else "Eligible for research-only interpretation.",
        })
    return sorted(rows, key=lambda r: (r["alpha_interpretation_allowed"], r["selectivity_status"], str(r["repaired_context_label"])))


def mapping_rows(ledger: pd.DataFrame) -> list[dict[str, object]]:
    if ledger.empty:
        return [{
            "original_context_label": "UNKNOWN", "repaired_context_label": "UNKNOWN", "repair_rule_id": "NO_LEDGER",
            "repair_source_fields": "", "rows_affected": 0, "distinct_tickers": 0, "ticker_coverage_ratio": "",
            "maturity_ratio": 0, "repair_status": "BLOCKED_INPUTS_MISSING", "interpretation_allowed_after_repair": "FALSE",
            "notes": "Canonical ledger missing.",
        }]
    total_tickers = int(ledger["ticker"].nunique())
    audit_by_label = {r["repaired_context_label"]: r for r in context_audit(ledger)}
    rows = []
    for (original, repaired, source, status), g in ledger.groupby(["original_context_label", "repaired_context_label", "repaired_context_source", "context_repair_status"], dropna=False):
        matured = g[g["maturity_status"] == "MATURED"]
        rows.append({
            "original_context_label": original,
            "repaired_context_label": repaired,
            "repair_rule_id": source,
            "repair_source_fields": "rsi_14|trend_strength_score|bb_position|ma20_distance|ma50_distance|ema20_distance|volatility_20" if source == "V21_038_TRUE_TECHNICAL_SUBFACTORS" else source,
            "rows_affected": len(g),
            "distinct_tickers": int(g["ticker"].nunique()),
            "ticker_coverage_ratio": int(g["ticker"].nunique()) / total_tickers if total_tickers else "",
            "maturity_ratio": len(matured) / len(g) if len(g) else 0,
            "repair_status": status,
            "interpretation_allowed_after_repair": audit_by_label.get(repaired, {}).get("alpha_interpretation_allowed", "FALSE"),
            "notes": clean(g["context_repair_reason"].iloc[0]) if "context_repair_reason" in g else "",
        })
    return rows


def technical_performance(ledger: pd.DataFrame, snap: pd.DataFrame, context_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    default = {
        "repaired_context_label": "UNKNOWN", "forward_window": "", "top_bucket": "TOP20", "rows_used": 0,
        "performance_quality": "BLOCKED_INPUTS_MISSING", "interpretation_allowed": "FALSE",
        "interpretation_block_reason": "No joinable matured ledger and V21.038 technical scores.",
    }
    if ledger.empty or snap.empty:
        return [default]
    allowed_by_context = {r["repaired_context_label"]: r for r in context_rows}
    matured = ledger[ledger["maturity_status"] == "MATURED"].copy()
    joined = matured.merge(snap[["as_of_date", "ticker", "technical_score_normalized"]], on=["as_of_date", "ticker"], how="inner")
    if joined.empty:
        default["performance_quality"] = "TECHNICAL_SCORE_JOIN_EMPTY"
        return [default]
    joined["baseline_rank"] = joined.groupby("as_of_date")["technical_score_normalized"].rank(ascending=False, method="first")
    rows = []
    for (label, window), g in joined.groupby(["repaired_context_label", "forward_window"]):
        top = g[g["baseline_rank"] <= 20].copy()
        vals = pd.to_numeric(top["realized_forward_return"], errors="coerce").dropna()
        bench = pd.to_numeric(top["benchmark_return"], errors="coerce").dropna()
        quality = "SUFFICIENT" if len(vals) >= MIN_TOP_BUCKET_ROWS else "LOW_SAMPLE"
        blocks = []
        context_gate = allowed_by_context.get(label, {})
        if label == "MISSING_CONTEXT_LABEL":
            blocks.append("MISSING_CONTEXT_LABEL")
        if context_gate.get("selectivity_status") == "BROADCAST_OVERWIDE":
            blocks.append("BROADCAST_OVERWIDE")
        if context_gate.get("maturity_status") == "LOW_CONTEXT_MATURITY":
            blocks.append("LOW_CONTEXT_MATURITY")
        if context_gate.get("alpha_interpretation_allowed") != "TRUE":
            blocks.append("CONTEXT_ALPHA_INTERPRETATION_BLOCKED")
        if len(vals) < MIN_TOP_BUCKET_ROWS:
            blocks.append("TOP20_CONTEXT_WINDOW_ROWS_LT_30")
        allowed = not blocks and quality == "SUFFICIENT"
        rows.append({
            "repaired_context_label": label,
            "forward_window": window,
            "top_bucket": "TOP20",
            "rows_used": len(vals),
            "mean_baseline_true_technical_forward_return": float(vals.mean()) if len(vals) else "",
            "median_baseline_true_technical_forward_return": float(vals.median()) if len(vals) else "",
            "baseline_hit_rate": float((vals > 0).mean()) if len(vals) else "",
            "baseline_downside_rate": float((vals < 0).mean()) if len(vals) else "",
            "benchmark_name": clean(top["benchmark_primary"].replace("", np.nan).dropna().iloc[0]) if top["benchmark_primary"].replace("", np.nan).dropna().any() else "",
            "mean_excess_vs_benchmark": float((vals - bench.reindex(vals.index).fillna(np.nan)).dropna().mean()) if len(bench) else "",
            "performance_quality": quality,
            "interpretation_allowed": yes(allowed),
            "interpretation_block_reason": "|".join(dict.fromkeys(blocks)),
        })
    return rows or [default]


def pending_refresh(ledger: pd.DataFrame) -> list[dict[str, object]]:
    if ledger.empty:
        return [{
            "observation_id": "NO_PENDING_OBSERVATIONS_DISCOVERED", "ticker": "", "as_of_date": "",
            "forward_window": "", "maturity_date": "", "maturity_status": "UNKNOWN", "repaired_context_label": "",
            "current_reason_pending": "Canonical ledger missing.", "expected_use_after_maturity": "Blocked until ledger exists.",
        }]
    pending = ledger[ledger["maturity_status"].isin(["PENDING", "PRICE_MISSING", "UNKNOWN"])].copy()
    if pending.empty:
        return [{
            "observation_id": "NO_PENDING_OBSERVATIONS_DISCOVERED", "ticker": "", "as_of_date": "",
            "forward_window": "", "maturity_date": "", "maturity_status": "NONE", "repaired_context_label": "",
            "current_reason_pending": "No pending observations in canonical ledger.", "expected_use_after_maturity": "No action.",
        }]
    pending = pending.sort_values(["maturity_date", "as_of_date", "ticker", "forward_window"]).head(5000)
    return [{
        "observation_id": r.observation_id,
        "ticker": r.ticker,
        "as_of_date": r.as_of_date,
        "forward_window": r.forward_window,
        "maturity_date": r.maturity_date,
        "maturity_status": r.maturity_status,
        "repaired_context_label": r.repaired_context_label,
        "current_reason_pending": "Price missing." if r.maturity_status == "PRICE_MISSING" else "Awaiting maturity date or realized return.",
        "expected_use_after_maturity": "Eligible for research-only context/technical retest only if context gates pass.",
    } for r in pending.itertuples(index=False)]


def repair_queue(summary: dict[str, object], context_rows: list[dict[str, object]], ledger: pd.DataFrame) -> list[dict[str, object]]:
    rows = []

    def add(target: str, issue: str, fix: str, priority: str, blocks_retest: bool, blocks_shadow: bool, validation: str, notes: str = "") -> None:
        rows.append({
            "repair_item_id": f"V21_040_R2_REPAIR_{len(rows) + 1:03d}",
            "repair_target": target,
            "current_issue": issue,
            "proposed_fix": fix,
            "priority": priority,
            "blocks_technical_retest": yes(blocks_retest),
            "blocks_shadow_gate": yes(blocks_shadow),
            "official_use_allowed_after_repair": "FALSE",
            "next_validation_required": validation,
            "notes": notes,
        })

    if summary["missing_context_after_count"] not in {"0", 0}:
        add("context_label", "Some rows remain MISSING_CONTEXT_LABEL.", "Add defensible ticker/date context evidence before alpha interpretation.", "HIGH", True, True, "MISSING_CONTEXT_REPAIR_REFRESH")
    if summary["context_overbroadcast_after"] == "TRUE":
        add("context_selectivity", "At least one repaired context remains over-broadcast.", "Split broad contexts into narrower exposure/regime/technical states.", "HIGH", True, True, "CONTEXT_SELECTIVITY_RECHECK")
    if len(ledger[ledger["maturity_status"] == "PENDING"]) > 0:
        add("pending_maturity", "Pending observations remain.", "Refresh after due dates and price availability checks.", "MEDIUM", True, True, "PENDING_MATURITY_REFRESH")
    if (ledger["observation_id_source"] == "SURROGATE").any() if not ledger.empty else False:
        add("observation_id", "Some rows use surrogate observation IDs.", "Persist original observation_id upstream.", "MEDIUM", False, True, "OBSERVATION_ID_STABILITY_CHECK")
    if not rows:
        add("none", "No R2 repair blocker detected.", "Proceed to research-only technical reweighting retest.", "LOW", False, True, "RESEARCH_ONLY_RETEST", "Official use remains blocked.")
    return rows


def build_summary(raw: pd.DataFrame, ledger: pd.DataFrame, sources: list[str], context_rows: list[dict[str, object]]) -> dict[str, object]:
    r1 = first(R1_SUMMARY)
    inputs_missing = not R1_SUMMARY.exists() or not V38_SNAPSHOT.exists() or not sources or ledger.empty
    before_missing = int((raw["original_context_label"] == "MISSING_CONTEXT_LABEL").sum()) if not raw.empty else 0
    after_missing = int((ledger["repaired_context_label"] == "MISSING_CONTEXT_LABEL").sum()) if not ledger.empty else 0
    missing_reduction = max(before_missing - after_missing, 0)
    missing_ratio = missing_reduction / before_missing if before_missing else 0
    matured = ledger[ledger["maturity_status"] == "MATURED"] if not ledger.empty else pd.DataFrame()
    pending = ledger[ledger["maturity_status"] == "PENDING"] if not ledger.empty else pd.DataFrame()
    over_after = any(r["selectivity_status"] == "BROADCAST_OVERWIDE" for r in context_rows)
    context_ready = bool(context_rows) and not over_after and after_missing == 0 and any(r["alpha_interpretation_allowed"] == "TRUE" for r in context_rows)
    retest_allowed = (not inputs_missing) and context_ready and len(matured) > 0
    if inputs_missing:
        final_status = BLOCKED_STATUS
        decision = DECISION_BLOCKED
    elif over_after:
        final_status = PARTIAL_STATUS
        decision = DECISION_OVERBROADCAST
    elif retest_allowed:
        final_status = PASS_STATUS
        decision = DECISION_READY
    else:
        final_status = PARTIAL_STATUS
        decision = DECISION_PARTIAL
    return {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "research_only": "TRUE",
        "official_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "real_book_mutation_allowed": "FALSE",
        "upstream_v21_040_r1_final_status": r1.get("final_status", ""),
        "canonical_forward_ledger_created": yes(not ledger.empty),
        "canonical_forward_ledger_rows": len(ledger),
        "source_count_used": len(sources),
        "total_observations_before_repair": len(raw),
        "total_observations_after_repair": len(ledger),
        "missing_context_before_count": before_missing,
        "missing_context_after_count": after_missing,
        "missing_context_reduction_count": missing_reduction,
        "missing_context_reduction_ratio": missing_ratio,
        "distinct_context_labels_before": int(raw["original_context_label"].nunique()) if not raw.empty else 0,
        "distinct_context_labels_after": int(ledger["repaired_context_label"].nunique()) if not ledger.empty else 0,
        "context_overbroadcast_before": r1.get("context_overbroadcast_detected", ""),
        "context_overbroadcast_after": yes(over_after),
        "context_selectivity_ready_after": yes(context_ready),
        "total_matured_observations": len(matured),
        "total_pending_observations": len(pending),
        "matured_5d_count": int((matured["forward_window"] == "5D").sum()) if not matured.empty else 0,
        "matured_10d_count": int((matured["forward_window"] == "10D").sum()) if not matured.empty else 0,
        "matured_20d_count": int((matured["forward_window"] == "20D").sum()) if not matured.empty else 0,
        "matured_60d_count": int((matured["forward_window"] == "60D").sum()) if not matured.empty else 0,
        "technical_reweighting_retest_allowed": yes(retest_allowed),
        "shadow_gate_allowed": "FALSE",
        "official_adoption_allowed": "FALSE",
        "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "V21.041_R1_TECHNICAL_REWEIGHTING_RETEST_WITH_REPAIRED_CONTEXTS_RESEARCH_ONLY" if retest_allowed else "V21.040_R3_CONTEXT_SOURCE_BACKFILL_AND_SELECTIVITY_REPAIR",
    }


def validation(summary: dict[str, object], ledger: pd.DataFrame, context_rows: list[dict[str, object]], perf_rows: list[dict[str, object]], pending_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    missing_blocked = all(r["alpha_interpretation_allowed"] == "FALSE" for r in context_rows if r["repaired_context_label"] == "MISSING_CONTEXT_LABEL")
    broadcast_blocked = all(r["alpha_interpretation_allowed"] == "FALSE" for r in context_rows if r["selectivity_status"] == "BROADCAST_OVERWIDE")
    low_mat_blocked = all(r["alpha_interpretation_allowed"] == "FALSE" for r in context_rows if r["maturity_status"] == "LOW_CONTEXT_MATURITY")
    checks = [
        ("V21_040_R1_SUMMARY_FOUND", yes(R1_SUMMARY.exists()), "TRUE"),
        ("V21_038_TECHNICAL_SNAPSHOT_FOUND", yes(V38_SNAPSHOT.exists()), "TRUE"),
        ("FORWARD_RETURN_SOURCES_FOUND", yes(int(summary["source_count_used"]) > 0), "TRUE"),
        ("CANONICAL_FORWARD_LEDGER_CREATED", summary["canonical_forward_ledger_created"], "TRUE"),
        ("MISSING_CONTEXT_REPAIR_ATTEMPTED", yes("context_repair_status" in ledger.columns and len(ledger) > 0), "TRUE"),
        ("CONTEXT_SELECTIVITY_CHECKED", yes(len(context_rows) > 0), "TRUE"),
        ("MISSING_CONTEXT_INTERPRETATION_BLOCKED", yes(missing_blocked), "TRUE"),
        ("BROADCAST_CONTEXT_INTERPRETATION_BLOCKED", yes(broadcast_blocked), "TRUE"),
        ("LOW_MATURITY_CONTEXT_INTERPRETATION_BLOCKED", yes(low_mat_blocked), "TRUE"),
        ("TECHNICAL_CONTEXT_PERFORMANCE_PRODUCED", yes(len(perf_rows) > 0), "TRUE"),
        ("PENDING_MATURITY_REFRESH_PRODUCED", yes(len(pending_rows) > 0), "TRUE"),
        ("NO_OFFICIAL_MUTATION", "TRUE", "TRUE"),
        ("RESEARCH_ONLY_TRUE", summary["research_only"], "TRUE"),
        ("DATA_TRUST_ALPHA_FALSE", summary["data_trust_alpha_weight_allowed"], "FALSE"),
    ]
    return [{
        "validation_item": item,
        "validation_status": "PASS" if str(obs) == req else "FAIL",
        "observed_value": obs,
        "required_value": req,
        "pass_fail": "PASS" if str(obs) == req else "FAIL",
        "notes": "Research-only forward/context repair validation.",
    } for item, obs, req in checks]


def write_report(summary: dict[str, object], sources: list[str], mapping: list[dict[str, object]], context_rows: list[dict[str, object]], perf_rows: list[dict[str, object]]) -> None:
    source_lines = "\n".join(f"- {src}" for src in sources[:25]) or "- No sources discovered."
    mapping_lines = "\n".join(f"- {r['repair_rule_id']} -> {r['repaired_context_label']}: rows={r['rows_affected']}" for r in mapping[:20])
    context_lines = "\n".join(f"- {r['repaired_context_label']}: selectivity={r['selectivity_status']}, maturity={r['maturity_status']}, allowed={r['alpha_interpretation_allowed']}" for r in context_rows[:20])
    perf_lines = "\n".join(f"- {r['repaired_context_label']} {r['forward_window']}: rows={r['rows_used']}, quality={r['performance_quality']}, allowed={r['interpretation_allowed']}" for r in perf_rows[:20])
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Final status and decision
- final_status: {summary['final_status']}
- decision: {summary['decision']}

## V21.040-R1 blocker summary
V21.040-R1 final_status was `{summary['upstream_v21_040_r1_final_status']}`. The R1 blocker was over-broadcast/missing context labels, with technical retest and shadow gate blocked.

## Canonical forward-return ledger construction
canonical_forward_ledger_created: {summary['canonical_forward_ledger_created']}; rows: {summary['canonical_forward_ledger_rows']}; sources used: {summary['source_count_used']}.

{source_lines}

## Context repair rules used
{mapping_lines}

## Missing context before/after
Before: {summary['missing_context_before_count']}; after: {summary['missing_context_after_count']}; reduction: {summary['missing_context_reduction_count']} ({fmt(summary['missing_context_reduction_ratio'])}).

## Context selectivity and maturity after repair
{context_lines}

## Technical performance by repaired context/window
{perf_lines}

## Whether technical reweighting retest is allowed
technical_reweighting_retest_allowed: {summary['technical_reweighting_retest_allowed']}.

## Whether shadow gate remains blocked
shadow_gate_allowed: {summary['shadow_gate_allowed']}. Shadow gate remains blocked unless all data/context gates pass in a later stage.

## Why official mutation remains blocked
Official mutation remains blocked because this stage is research-only, official use is FALSE, official weight and ranking mutation are FALSE, trade/broker/real-book actions are FALSE, official adoption is FALSE, and data-trust alpha weight remains FALSE.

## Next recommended stage
{summary['next_recommended_stage']}
"""
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(report, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    raw, sources = load_forward_observations()
    snap = load_technical_snapshot()
    repaired = repair_context(raw, snap)
    ledger = canonical_ledger(repaired)
    context_rows = context_audit(ledger)
    mapping = mapping_rows(ledger)
    perf_rows = technical_performance(ledger, snap, context_rows)
    pending_rows = pending_refresh(ledger)
    summary = build_summary(raw, ledger, sources, context_rows)
    repair_rows = repair_queue(summary, context_rows, ledger)

    write_csv(SUMMARY_OUT, [summary], list(summary.keys()))
    write_csv(LEDGER_OUT, ledger.replace({np.nan: None}).to_dict("records") if not ledger.empty else [{"observation_id": "", "row_quality_status": "CANONICAL_LEDGER_EMPTY"}], ["observation_id", "observation_id_source", "ticker", "as_of_date", "forward_window", "maturity_date", "maturity_status", "realized_forward_return", "price_missing", "source_file_path", "source_priority", "original_context_label", "repaired_context_label", "repaired_context_source", "context_repair_status", "context_repair_reason", "benchmark_primary", "benchmark_return", "row_quality_status"])
    write_csv(MAPPING_OUT, mapping, ["original_context_label", "repaired_context_label", "repair_rule_id", "repair_source_fields", "rows_affected", "distinct_tickers", "ticker_coverage_ratio", "maturity_ratio", "repair_status", "interpretation_allowed_after_repair", "notes"])
    write_csv(CONTEXT_OUT, context_rows, ["repaired_context_label", "total_observations", "matured_observations", "pending_observations", "price_missing_observations", "distinct_ticker_count", "total_distinct_ticker_count", "ticker_coverage_ratio", "distinct_as_of_dates", "maturity_ratio", "matured_5d_count", "matured_10d_count", "matured_20d_count", "matured_60d_count", "mean_forward_return_5d", "mean_forward_return_10d", "mean_forward_return_20d", "mean_forward_return_60d", "hit_rate_5d", "hit_rate_10d", "hit_rate_20d", "hit_rate_60d", "selectivity_status", "maturity_status", "alpha_interpretation_allowed", "failure_reason", "repair_recommendation"])
    write_csv(PERF_OUT, perf_rows, ["repaired_context_label", "forward_window", "top_bucket", "rows_used", "mean_baseline_true_technical_forward_return", "median_baseline_true_technical_forward_return", "baseline_hit_rate", "baseline_downside_rate", "benchmark_name", "mean_excess_vs_benchmark", "performance_quality", "interpretation_allowed", "interpretation_block_reason"])
    write_csv(PENDING_OUT, pending_rows, ["observation_id", "ticker", "as_of_date", "forward_window", "maturity_date", "maturity_status", "repaired_context_label", "current_reason_pending", "expected_use_after_maturity"])
    write_csv(REPAIR_OUT, repair_rows, ["repair_item_id", "repair_target", "current_issue", "proposed_fix", "priority", "blocks_technical_retest", "blocks_shadow_gate", "official_use_allowed_after_repair", "next_validation_required", "notes"])
    write_csv(VALIDATION_OUT, validation(summary, ledger, context_rows, perf_rows, pending_rows), ["validation_item", "validation_status", "observed_value", "required_value", "pass_fail", "notes"])
    write_report(summary, sources, mapping, context_rows, perf_rows)

    print(f"STAGE_NAME={STAGE}")
    print(f"final_status={summary['final_status']}")
    print(f"decision={summary['decision']}")
    print(f"canonical_forward_ledger_rows={summary['canonical_forward_ledger_rows']}")
    print(f"missing_context_before_count={summary['missing_context_before_count']}")
    print(f"missing_context_after_count={summary['missing_context_after_count']}")
    print(f"context_overbroadcast_after={summary['context_overbroadcast_after']}")
    print(f"technical_reweighting_retest_allowed={summary['technical_reweighting_retest_allowed']}")
    print(f"shadow_gate_allowed={summary['shadow_gate_allowed']}")


if __name__ == "__main__":
    main()
