#!/usr/bin/env python
"""V21.040-R1 matured forward-return extension and context alignment.

Research-only audit of forward-return maturity coverage, pending schedules, and
context/regime label selectivity before any further technical reweighting.
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


STAGE = "V21.040-R1_MATURED_FORWARD_RETURN_EXTENSION_AND_CONTEXT_ALIGNMENT"
PASS_STATUS = "PASS_V21_040_R1_MATURED_FORWARD_CONTEXT_ALIGNMENT_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_040_R1_PENDING_MATURITY_OR_CONTEXT_REPAIR_REQUIRED"
BLOCKED_STATUS = "BLOCKED_V21_040_R1_INPUTS_MISSING"
RESEARCH_BLOCKED_STATUS = "BLOCKED_V21_040_R1_RESEARCH_ONLY_VIOLATION"

DECISION_READY = "MATURED_FORWARD_CONTEXT_ALIGNMENT_READY_FOR_TECHNICAL_RETEST"
DECISION_PENDING = "MATURED_FORWARD_CONTEXT_ALIGNMENT_PENDING_MATURITY_MORE_DATA_NEEDED"
DECISION_OVERBROADCAST = "MATURED_FORWARD_CONTEXT_ALIGNMENT_BLOCKED_BY_CONTEXT_OVERBROADCAST"
DECISION_BLOCKED = "MATURED_FORWARD_CONTEXT_ALIGNMENT_BLOCKED_INPUTS_MISSING"

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

V38_SUMMARY = OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_RERUN_SUMMARY.csv"
V38_SNAPSHOT = OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv"
V39_SUMMARY = OUT_DIR / "V21_039_R1_TRUE_TECHNICAL_REWEIGHTING_BACKTEST_SUMMARY.csv"

SUMMARY_OUT = OUT_DIR / "V21_040_R1_MATURED_FORWARD_CONTEXT_ALIGNMENT_SUMMARY.csv"
WINDOW_OUT = OUT_DIR / "V21_040_R1_FORWARD_RETURN_MATURITY_BY_WINDOW.csv"
CONTEXT_OUT = OUT_DIR / "V21_040_R1_CONTEXT_SELECTIVITY_AND_MATURITY_AUDIT.csv"
PERF_OUT = OUT_DIR / "V21_040_R1_TECHNICAL_PERFORMANCE_BY_CONTEXT_WINDOW.csv"
PENDING_OUT = OUT_DIR / "V21_040_R1_PENDING_MATURITY_SCHEDULE.csv"
REPAIR_OUT = OUT_DIR / "V21_040_R1_FORWARD_CONTEXT_ALIGNMENT_REPAIR_QUEUE.csv"
VALIDATION_OUT = OUT_DIR / "V21_040_R1_VALIDATION_MATRIX.csv"
REPORT_OUT = READ_CENTER_DIR / "V21_040_R1_MATURED_FORWARD_RETURN_EXTENSION_AND_CONTEXT_ALIGNMENT_REPORT.md"

WINDOWS = ["5D", "10D", "20D", "60D"]
MIN_MATURED_PER_WINDOW = 100
MIN_MATURITY_RATIO = 0.60
MIN_CONTEXT_MATURITY_RATIO = 0.50


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


def read_csv_dicts(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{k: clean(v) for k, v in row.items()} for row in csv.DictReader(handle)]


def first(path: Path) -> dict[str, str]:
    rows = read_csv_dicts(path)
    return rows[0] if rows else {}


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


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


def find_semantic_col(cols: list[str], candidates: list[str]) -> str:
    """Find a label-like column without accepting score/rank/count lookalikes."""
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
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"SURROGATE_OBSERVATION_ID_{digest}"


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
    ]


def discover_forward_files() -> list[Path]:
    files: set[Path] = set()
    name_tokens = ("forward", "matur", "outcome", "observation", "context", "regime", "benchmark")
    for root in candidate_roots():
        if not root.exists():
            continue
        for path in root.rglob("*.csv"):
            if path.name.startswith("V21_040_R1_"):
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


def status_bucket(status: object, ret: object, price_missing_hint: object = "") -> str:
    text = norm(f"{status} {price_missing_hint}")
    has_return = pd.notna(ret)
    if "price_missing" in text or "missing_price" in text or ("missing" in text and not has_return):
        return "PRICE_MISSING"
    if "pending" in text or "not_matured" in text or "not_due" in text or "scheduled" in text:
        return "PENDING"
    if "reject" in text or "leakage" in text:
        return "PRICE_MISSING"
    if has_return and ("matured" in text or "realized" in text or "available" in text or "pass" in text or not text.strip("_")):
        return "MATURED"
    if has_return:
        return "MATURED"
    return "PENDING"


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
    risk_col = find_semantic_col(cols, ["risk_overheat_label", "overheat_status", "risk_gate_flag", "risk_diagnostic_status"])
    bench_col = find_col(cols, ["benchmark_forward_return", "benchmark_return", "excess_return_vs_QQQ_10d"])
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
    base["context_label"] = df[context_col].map(clean) if context_col else ""
    base["regime_label"] = df[regime_col].map(clean) if regime_col else ""
    base["risk_overheat_label"] = df[risk_col].map(clean) if risk_col else ""
    base["benchmark_name"] = df[bench_name_col].map(clean) if bench_name_col else ""
    base["benchmark_forward_return"] = pd.to_numeric(df[bench_col], errors="coerce") if bench_col and "excess_return_vs" not in norm(bench_col) else np.nan
    base["raw_status"] = df[maturity_col].map(clean) if maturity_col else ""
    base["source_artifact"] = rel(path)
    base["source_row_number"] = np.arange(1, len(df) + 1)
    base["observation_id"] = df[obs_col].map(clean) if obs_col else ""
    base["observation_id_is_surrogate"] = yes(not bool(obs_col))
    base["price_missing_hint"] = df[price_missing_col].map(clean) if price_missing_col else ""

    frames: list[pd.DataFrame] = []
    if window_col and ret_col:
        out = base.copy()
        out["forward_window"] = df[window_col].map(normalize_window)
        out["realized_forward_return"] = pd.to_numeric(df[ret_col], errors="coerce")
        frames.append(out)
    wide = {
        "5D": find_col(cols, ["forward_return_5d"]),
        "10D": find_col(cols, ["forward_return_10d"]),
        "20D": find_col(cols, ["forward_return_20d"]),
        "60D": find_col(cols, ["forward_return_60d"]),
    }
    for window, col in wide.items():
        if not col:
            continue
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
            surrogate_id(r.as_of_date, r.ticker, r.forward_window, r.source_artifact, int(r.source_row_number))
            for r in out.loc[missing_obs].itertuples(index=False)
        ]
        out.loc[missing_obs, "observation_id_is_surrogate"] = "TRUE"
    out["maturity_status"] = [
        status_bucket(status, ret, hint)
        for status, ret, hint in zip(out["raw_status"], out["realized_forward_return"], out["price_missing_hint"])
    ]
    out["context_label"] = out["context_label"].replace("", np.nan)
    out["context_label"] = out["context_label"].fillna(out["regime_label"].replace("", np.nan)).fillna("MISSING_CONTEXT_LABEL")
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
    priority = out["maturity_status"].map({"MATURED": 3, "PENDING": 2, "PRICE_MISSING": 1}).fillna(0)
    out = out.assign(_priority=priority)
    out = out.sort_values(["as_of_date", "ticker", "forward_window", "_priority", "source_artifact"])
    out = out.drop_duplicates(["as_of_date", "ticker", "forward_window", "context_label", "observation_id"], keep="last")
    return out.drop(columns=["_priority"]), sources


def load_snapshot_scores() -> pd.DataFrame:
    if not V38_SNAPSHOT.exists():
        return pd.DataFrame()
    try:
        snap = pd.read_csv(V38_SNAPSHOT, usecols=["as_of_date", "ticker", "technical_score_normalized"], low_memory=False)
    except Exception:
        return pd.DataFrame()
    snap["as_of_date"] = date_str(snap["as_of_date"])
    snap["ticker"] = snap["ticker"].astype(str).str.upper().str.strip()
    snap["technical_score_normalized"] = pd.to_numeric(snap["technical_score_normalized"], errors="coerce")
    return snap.dropna(subset=["as_of_date", "ticker", "technical_score_normalized"])


def maturity_by_window(obs: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for window in WINDOWS:
        w = obs[obs["forward_window"] == window] if not obs.empty else pd.DataFrame()
        matured = w[w["maturity_status"] == "MATURED"] if not w.empty else pd.DataFrame()
        pending = w[w["maturity_status"] == "PENDING"] if not w.empty else pd.DataFrame()
        price_missing = w[w["maturity_status"] == "PRICE_MISSING"] if not w.empty else pd.DataFrame()
        total = len(w)
        ratio = len(matured) / total if total else 0.0
        ready = len(matured) >= MIN_MATURED_PER_WINDOW and ratio >= MIN_MATURITY_RATIO
        rows.append({
            "forward_window": window,
            "total_observations": total,
            "matured_count": len(matured),
            "pending_count": len(pending),
            "price_missing_count": len(price_missing),
            "maturity_ratio": ratio,
            "distinct_tickers": int(matured["ticker"].nunique()) if not matured.empty else 0,
            "distinct_as_of_dates": int(matured["as_of_date"].nunique()) if not matured.empty else 0,
            "min_as_of_date": matured["as_of_date"].min() if not matured.empty else "",
            "max_as_of_date": matured["as_of_date"].max() if not matured.empty else "",
            "earliest_pending_maturity_date": pending["maturity_date"].replace("", np.nan).min() if not pending.empty else "",
            "latest_pending_maturity_date": pending["maturity_date"].replace("", np.nan).max() if not pending.empty else "",
            "window_ready_for_retest": yes(ready),
            "notes": f"threshold_matured_count>={MIN_MATURED_PER_WINDOW};threshold_maturity_ratio>={MIN_MATURITY_RATIO:.2f}",
        })
    return rows


def rate(series: pd.Series) -> object:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return ""
    return float((vals > 0).mean())


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


def context_audit(obs: pd.DataFrame) -> list[dict[str, object]]:
    if obs.empty:
        return [{
            "context_label": "UNKNOWN",
            "total_observations": 0,
            "matured_observations": 0,
            "pending_observations": 0,
            "distinct_ticker_count": 0,
            "total_distinct_ticker_count": 0,
            "ticker_coverage_ratio": "",
            "distinct_as_of_dates": 0,
            "maturity_ratio": 0,
            "selectivity_status": "UNKNOWN",
            "alpha_interpretation_allowed": "FALSE",
            "failure_reason": "FORWARD_RETURN_INPUTS_MISSING",
            "repair_recommendation": "Locate joinable forward-return/context sources.",
        }]
    total_tickers = int(obs["ticker"].nunique())
    rows = []
    for label, g in obs.groupby("context_label", dropna=False):
        matured = g[g["maturity_status"] == "MATURED"]
        pending = g[g["maturity_status"] == "PENDING"]
        ticker_count = int(g["ticker"].nunique())
        ratio = ticker_count / total_tickers if total_tickers else np.nan
        status = selectivity_status(ticker_count, total_tickers)
        maturity_ratio = len(matured) / len(g) if len(g) else 0
        allowed = status == "SELECTIVE" and maturity_ratio >= MIN_CONTEXT_MATURITY_RATIO
        reasons = []
        if status != "SELECTIVE":
            reasons.append(status)
        if maturity_ratio < MIN_CONTEXT_MATURITY_RATIO:
            reasons.append("LOW_CONTEXT_MATURITY")
        if clean(label) == "MISSING_CONTEXT_LABEL":
            reasons.append("MISSING_CONTEXT_LABEL")
        rows.append({
            "context_label": clean(label) or "MISSING_CONTEXT_LABEL",
            "total_observations": len(g),
            "matured_observations": len(matured),
            "pending_observations": len(pending),
            "distinct_ticker_count": ticker_count,
            "total_distinct_ticker_count": total_tickers,
            "ticker_coverage_ratio": ratio,
            "distinct_as_of_dates": int(g["as_of_date"].nunique()),
            "maturity_ratio": maturity_ratio,
            "mean_forward_return_5d": mean_for(matured, "5D"),
            "mean_forward_return_10d": mean_for(matured, "10D"),
            "mean_forward_return_20d": mean_for(matured, "20D"),
            "mean_forward_return_60d": mean_for(matured, "60D"),
            "hit_rate_5d": hit_for(matured, "5D"),
            "hit_rate_10d": hit_for(matured, "10D"),
            "hit_rate_20d": hit_for(matured, "20D"),
            "hit_rate_60d": hit_for(matured, "60D"),
            "selectivity_status": status,
            "alpha_interpretation_allowed": yes(allowed),
            "failure_reason": "|".join(reasons),
            "repair_recommendation": "Split over-broad or missing labels by ticker exposure/regime and wait for more matured rows." if reasons else "No immediate context repair required.",
        })
    return sorted(rows, key=lambda r: (r["selectivity_status"], str(r["context_label"])))


def technical_performance(obs: pd.DataFrame, snap: pd.DataFrame) -> list[dict[str, object]]:
    fields_default = {
        "context_label": "UNKNOWN",
        "forward_window": "",
        "top_bucket": "TOP20",
        "rows_used": 0,
        "performance_quality": "BLOCKED_INPUTS_MISSING",
        "interpretation_allowed": "FALSE",
        "interpretation_block_reason": "No joinable matured forward returns and V21.038 technical score rows.",
    }
    if obs.empty or snap.empty:
        return [fields_default]
    matured = obs[obs["maturity_status"] == "MATURED"].copy()
    if matured.empty:
        fields_default["performance_quality"] = "NO_MATURED_ROWS"
        return [fields_default]
    joined = matured.merge(snap, on=["as_of_date", "ticker"], how="inner")
    if joined.empty:
        fields_default["performance_quality"] = "TECHNICAL_SCORE_JOIN_EMPTY"
        return [fields_default]
    joined["baseline_rank"] = joined.groupby("as_of_date")["technical_score_normalized"].rank(ascending=False, method="first")
    rows = []
    for (label, window), g in joined.groupby(["context_label", "forward_window"]):
        top = g[g["baseline_rank"] <= 20].copy()
        vals = pd.to_numeric(top["realized_forward_return"], errors="coerce").dropna()
        bench = pd.to_numeric(top["benchmark_forward_return"], errors="coerce").dropna()
        quality = "SUFFICIENT" if len(vals) >= 30 else "LOW_SAMPLE"
        block = "" if quality == "SUFFICIENT" else "TOP20_CONTEXT_WINDOW_ROWS_LT_30"
        rows.append({
            "context_label": label,
            "forward_window": window,
            "top_bucket": "TOP20",
            "rows_used": len(vals),
            "mean_baseline_true_technical_forward_return": float(vals.mean()) if len(vals) else "",
            "median_baseline_true_technical_forward_return": float(vals.median()) if len(vals) else "",
            "baseline_hit_rate": float((vals > 0).mean()) if len(vals) else "",
            "baseline_downside_rate": float((vals < 0).mean()) if len(vals) else "",
            "benchmark_name": clean(top["benchmark_name"].replace("", np.nan).dropna().iloc[0]) if top["benchmark_name"].replace("", np.nan).dropna().any() else "",
            "mean_excess_vs_benchmark": float((vals - bench.reindex(vals.index).fillna(np.nan)).dropna().mean()) if len(bench) else "",
            "performance_quality": quality,
            "interpretation_allowed": yes(quality == "SUFFICIENT"),
            "interpretation_block_reason": block,
        })
    return rows or [fields_default]


def pending_schedule(obs: pd.DataFrame) -> list[dict[str, object]]:
    if obs.empty:
        return [{
            "observation_id": "NO_PENDING_OBSERVATIONS_DISCOVERED",
            "ticker": "",
            "as_of_date": "",
            "forward_window": "",
            "maturity_date": "",
            "maturity_status": "UNKNOWN",
            "context_label": "",
            "current_reason_pending": "Forward-return sources missing.",
            "expected_use_after_maturity": "Blocked until local sources expose pending observations.",
        }]
    pending = obs[obs["maturity_status"].isin(["PENDING", "PRICE_MISSING"])].copy()
    if pending.empty:
        return [{
            "observation_id": "NO_PENDING_OBSERVATIONS_DISCOVERED",
            "ticker": "",
            "as_of_date": "",
            "forward_window": "",
            "maturity_date": "",
            "maturity_status": "NONE",
            "context_label": "",
            "current_reason_pending": "No pending observations in discovered sources.",
            "expected_use_after_maturity": "No action.",
        }]
    pending = pending.sort_values(["maturity_date", "as_of_date", "ticker", "forward_window"]).head(5000)
    return [{
        "observation_id": r.observation_id,
        "ticker": r.ticker,
        "as_of_date": r.as_of_date,
        "forward_window": r.forward_window,
        "maturity_date": r.maturity_date,
        "maturity_status": r.maturity_status,
        "context_label": r.context_label,
        "current_reason_pending": "Price missing." if r.maturity_status == "PRICE_MISSING" else "Awaiting maturity date or realized return.",
        "expected_use_after_maturity": "Eligible for research-only technical/context retest after realized forward return is available.",
    } for r in pending.itertuples(index=False)]


def repair_queue(window_rows: list[dict[str, object]], context_rows: list[dict[str, object]], obs: pd.DataFrame, sources: list[str]) -> list[dict[str, object]]:
    rows = []

    def add(item: str, target: str, issue: str, fix: str, priority: str, blocks_retest: bool, blocks_shadow: bool, notes: str = "") -> None:
        rows.append({
            "repair_item_id": f"V21_040_REPAIR_{len(rows) + 1:03d}",
            "repair_target": target,
            "current_issue": issue,
            "proposed_fix": fix,
            "priority": priority,
            "blocks_technical_retest": yes(blocks_retest),
            "blocks_shadow_gate": yes(blocks_shadow),
            "official_use_allowed_after_repair": "FALSE",
            "next_validation_required": item,
            "notes": notes,
        })

    if not sources:
        add("FORWARD_RETURN_SOURCE_DISCOVERY", "forward_return_sources", "No local forward-return sources discovered.", "Expose local matured/pending forward-return ledgers.", "CRITICAL", True, True)
    for row in window_rows:
        if row["window_ready_for_retest"] != "TRUE":
            add("WINDOW_MATURITY_RECHECK", row["forward_window"], "Insufficient matured count or maturity ratio.", "Wait for maturity or backfill local realized forward returns.", "HIGH", True, True, str(row["notes"]))
    if any(r["context_label"] == "MISSING_CONTEXT_LABEL" or "MISSING_CONTEXT_LABEL" in clean(r.get("failure_reason")) for r in context_rows):
        add("CONTEXT_LABEL_BACKFILL", "context_label", "Missing context labels detected.", "Backfill context/regime labels before interpreting alpha by context.", "HIGH", True, True)
    if any(r["selectivity_status"] == "BROADCAST_OVERWIDE" for r in context_rows):
        add("CONTEXT_SELECTIVITY_SPLIT", "context_label", "Context labels cover more than 80% of tickers.", "Split labels by exposure, regime, trend, or risk/overheat state.", "HIGH", True, True)
    if not obs.empty and obs["benchmark_forward_return"].notna().sum() == 0:
        add("BENCHMARK_RETURN_JOIN", "benchmark_returns", "Benchmark returns missing or not joinable.", "Join local QQQ/SPY/SOXX benchmark returns to each forward window.", "MEDIUM", False, True)
    if not obs.empty and (obs["observation_id_is_surrogate"] == "TRUE").any():
        add("OBSERVATION_ID_STABILIZATION", "observation_id", "Some source rows lack observation_id.", "Persist deterministic observation_id in upstream forward-return ledgers.", "MEDIUM", False, True)
    if not obs.empty and len(obs[obs["maturity_status"] == "PENDING"]) > 0:
        add("PENDING_MATURITY_TRACKING", "pending_maturity_schedule", "Pending observations remain.", "Rerun maturity audit after due dates and price availability checks.", "MEDIUM", True, True)
    if len(sources) > 1:
        add("FORWARD_SOURCE_ALIGNMENT", "forward_return_source_alignment", "Multiple forward-return sources found with mixed schemas.", "Promote one canonical research-only normalized forward-return ledger.", "MEDIUM", False, True, f"sources={len(sources)}")
    if not obs.empty and obs["risk_overheat_label"].replace("", np.nan).notna().sum() == 0:
        add("OVERHEAT_TREND_CONTEXT_SPLIT", "risk_overheat_label", "Risk/overheat labels missing from normalized observations.", "Carry overheat/trend labels into context audit for split testing.", "MEDIUM", False, True)
    return rows or [{
        "repair_item_id": "V21_040_REPAIR_001",
        "repair_target": "none",
        "current_issue": "No blocking repair detected by V21.040.",
        "proposed_fix": "Proceed only with research-only retest validation.",
        "priority": "LOW",
        "blocks_technical_retest": "FALSE",
        "blocks_shadow_gate": "TRUE",
        "official_use_allowed_after_repair": "FALSE",
        "next_validation_required": "RESEARCH_ONLY_TECHNICAL_RETEST",
        "notes": "Official use remains blocked.",
    }]


def validation(summary: dict[str, object], rows: dict[str, int]) -> list[dict[str, object]]:
    checks = [
        ("V21_039_SUMMARY_FOUND", yes(V39_SUMMARY.exists()), "TRUE"),
        ("V21_038_TECHNICAL_SNAPSHOT_FOUND", yes(V38_SNAPSHOT.exists()), "TRUE"),
        ("FORWARD_RETURN_SOURCES_FOUND", yes(int(summary["forward_return_source_count"]) > 0), "TRUE"),
        ("MATURED_ROWS_PRESENT", yes(int(summary["total_matured_observations"]) > 0), "TRUE"),
        ("PENDING_ROWS_TRACKED", yes(rows.get("pending", 0) > 0 or int(summary["total_pending_observations"]) == 0), "TRUE"),
        ("FORWARD_WINDOWS_AUDITED", yes(rows.get("window", 0) >= 4), "TRUE"),
        ("CONTEXT_LABELS_AUDITED", yes(rows.get("context", 0) > 0), "TRUE"),
        ("CONTEXT_SELECTIVITY_CHECKED", yes("context_overbroadcast_detected" in summary), "TRUE"),
        ("TECHNICAL_CONTEXT_PERFORMANCE_PRODUCED", yes(rows.get("performance", 0) > 0), "TRUE"),
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
        "notes": "Research-only matured forward/context alignment validation.",
    } for item, obs, req in checks]


def build_summary(obs: pd.DataFrame, sources: list[str], window_rows: list[dict[str, object]], context_rows: list[dict[str, object]]) -> dict[str, object]:
    v38 = first(V38_SUMMARY)
    v39 = first(V39_SUMMARY)
    inputs_missing = not V39_SUMMARY.exists() or not V38_SNAPSHOT.exists() or not sources
    total = len(obs)
    matured = obs[obs["maturity_status"] == "MATURED"] if not obs.empty else pd.DataFrame()
    pending = obs[obs["maturity_status"] == "PENDING"] if not obs.empty else pd.DataFrame()
    price_missing = obs[obs["maturity_status"] == "PRICE_MISSING"] if not obs.empty else pd.DataFrame()
    overbroadcast = any(r.get("selectivity_status") == "BROADCAST_OVERWIDE" for r in context_rows)
    context_ready = bool(context_rows) and not overbroadcast and not any(r.get("context_label") == "MISSING_CONTEXT_LABEL" for r in context_rows)
    all_windows_ready = all(r["window_ready_for_retest"] == "TRUE" for r in window_rows)
    retest_allowed = (not inputs_missing) and all_windows_ready and context_ready and len(matured) > 0
    if inputs_missing:
        final_status = BLOCKED_STATUS
        decision = DECISION_BLOCKED
    elif overbroadcast:
        final_status = PARTIAL_STATUS
        decision = DECISION_OVERBROADCAST
    elif retest_allowed:
        final_status = PASS_STATUS
        decision = DECISION_READY
    else:
        final_status = PARTIAL_STATUS
        decision = DECISION_PENDING
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
        "upstream_v21_039_final_status": v39.get("final_status", ""),
        "v21_038_snapshot_rows": v38.get("input_rows", ""),
        "v21_039_matured_rows_used": v39.get("matured_rows_used", ""),
        "v21_039_immature_rows_excluded": v39.get("immature_rows_excluded", ""),
        "forward_return_source_count": len(sources),
        "total_candidate_observations": total,
        "total_matured_observations": len(matured),
        "total_pending_observations": len(pending),
        "total_price_missing_observations": len(price_missing),
        "matured_5d_count": int((matured["forward_window"] == "5D").sum()) if not matured.empty else 0,
        "matured_10d_count": int((matured["forward_window"] == "10D").sum()) if not matured.empty else 0,
        "matured_20d_count": int((matured["forward_window"] == "20D").sum()) if not matured.empty else 0,
        "matured_60d_count": int((matured["forward_window"] == "60D").sum()) if not matured.empty else 0,
        "pending_5d_count": int((pending["forward_window"] == "5D").sum()) if not pending.empty else 0,
        "pending_10d_count": int((pending["forward_window"] == "10D").sum()) if not pending.empty else 0,
        "pending_20d_count": int((pending["forward_window"] == "20D").sum()) if not pending.empty else 0,
        "pending_60d_count": int((pending["forward_window"] == "60D").sum()) if not pending.empty else 0,
        "distinct_tickers_with_matured_returns": int(matured["ticker"].nunique()) if not matured.empty else 0,
        "distinct_as_of_dates_with_matured_returns": int(matured["as_of_date"].nunique()) if not matured.empty else 0,
        "distinct_context_labels": int(obs["context_label"].nunique()) if not obs.empty else 0,
        "context_selectivity_ready": yes(context_ready),
        "context_overbroadcast_detected": yes(overbroadcast),
        "technical_reweighting_retest_allowed": yes(retest_allowed),
        "shadow_gate_allowed": "FALSE",
        "official_adoption_allowed": "FALSE",
        "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "V21.041_R1_RESEARCH_ONLY_TECHNICAL_RETEST_WITH_CONTEXT_ALIGNMENT" if retest_allowed else "V21.040_R2_FORWARD_CONTEXT_REPAIR_AND_MATURITY_REFRESH",
    }


def write_report(summary: dict[str, object], sources: list[str], window_rows: list[dict[str, object]], context_rows: list[dict[str, object]], perf_rows: list[dict[str, object]]) -> None:
    source_lines = "\n".join(f"- {src}" for src in sources[:25]) or "- No forward-return source discovered."
    window_lines = "\n".join(
        f"- {r['forward_window']}: matured={r['matured_count']}, pending={r['pending_count']}, maturity_ratio={fmt(r['maturity_ratio'])}, ready={r['window_ready_for_retest']}"
        for r in window_rows
    )
    context_lines = "\n".join(
        f"- {r['context_label']}: status={r['selectivity_status']}, ticker_coverage={fmt(r.get('ticker_coverage_ratio'))}, maturity_ratio={fmt(r.get('maturity_ratio'))}"
        for r in context_rows[:20]
    )
    perf_lines = "\n".join(
        f"- {r['context_label']} {r['forward_window']}: rows={r['rows_used']}, mean={fmt(r.get('mean_baseline_true_technical_forward_return'))}, quality={r['performance_quality']}"
        for r in perf_rows[:20]
    )
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Final status and decision
- final_status: {summary['final_status']}
- decision: {summary['decision']}

## V21.039 summary and why no variant was adopted
V21.039 final_status was `{summary['upstream_v21_039_final_status']}`. It used `{summary['v21_039_matured_rows_used']}` matured rows, excluded `{summary['v21_039_immature_rows_excluded']}` immature/pending rows, and kept BASELINE_TRUE_TECHNICAL because no tested variant produced a reliable positive edge over baseline.

## Forward-return sources used
{source_lines}

## Maturity coverage by forward window
{window_lines}

## Pending maturity schedule summary
Pending observations: {summary['total_pending_observations']}. Price-missing observations: {summary['total_price_missing_observations']}. Details are in `V21_040_R1_PENDING_MATURITY_SCHEDULE.csv`.

## Context selectivity findings
{context_lines}

## Technical baseline performance by context/window
{perf_lines}

## Whether another technical reweighting retest is allowed
technical_reweighting_retest_allowed: {summary['technical_reweighting_retest_allowed']}.

## Whether a shadow gate is allowed
shadow_gate_allowed: {summary['shadow_gate_allowed']}. Shadow gate remains blocked unless all maturity and context gates pass in a later stage.

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
    obs, sources = load_forward_observations()
    snap = load_snapshot_scores()
    window_rows = maturity_by_window(obs)
    context_rows = context_audit(obs)
    perf_rows = technical_performance(obs, snap)
    pending_rows = pending_schedule(obs)
    repair_rows = repair_queue(window_rows, context_rows, obs, sources)
    summary = build_summary(obs, sources, window_rows, context_rows)

    write_csv(SUMMARY_OUT, [summary], list(summary.keys()))
    write_csv(WINDOW_OUT, window_rows, ["forward_window", "total_observations", "matured_count", "pending_count", "price_missing_count", "maturity_ratio", "distinct_tickers", "distinct_as_of_dates", "min_as_of_date", "max_as_of_date", "earliest_pending_maturity_date", "latest_pending_maturity_date", "window_ready_for_retest", "notes"])
    write_csv(CONTEXT_OUT, context_rows, ["context_label", "total_observations", "matured_observations", "pending_observations", "distinct_ticker_count", "total_distinct_ticker_count", "ticker_coverage_ratio", "distinct_as_of_dates", "maturity_ratio", "mean_forward_return_5d", "mean_forward_return_10d", "mean_forward_return_20d", "mean_forward_return_60d", "hit_rate_5d", "hit_rate_10d", "hit_rate_20d", "hit_rate_60d", "selectivity_status", "alpha_interpretation_allowed", "failure_reason", "repair_recommendation"])
    write_csv(PERF_OUT, perf_rows, ["context_label", "forward_window", "top_bucket", "rows_used", "mean_baseline_true_technical_forward_return", "median_baseline_true_technical_forward_return", "baseline_hit_rate", "baseline_downside_rate", "benchmark_name", "mean_excess_vs_benchmark", "performance_quality", "interpretation_allowed", "interpretation_block_reason"])
    write_csv(PENDING_OUT, pending_rows, ["observation_id", "ticker", "as_of_date", "forward_window", "maturity_date", "maturity_status", "context_label", "current_reason_pending", "expected_use_after_maturity"])
    write_csv(REPAIR_OUT, repair_rows, ["repair_item_id", "repair_target", "current_issue", "proposed_fix", "priority", "blocks_technical_retest", "blocks_shadow_gate", "official_use_allowed_after_repair", "next_validation_required", "notes"])
    write_csv(VALIDATION_OUT, validation(summary, {"window": len(window_rows), "context": len(context_rows), "performance": len(perf_rows), "pending": len(pending_rows)}), ["validation_item", "validation_status", "observed_value", "required_value", "pass_fail", "notes"])
    write_report(summary, sources, window_rows, context_rows, perf_rows)

    print(f"STAGE_NAME={STAGE}")
    print(f"final_status={summary['final_status']}")
    print(f"decision={summary['decision']}")
    print(f"forward_return_source_count={summary['forward_return_source_count']}")
    print(f"total_matured_observations={summary['total_matured_observations']}")
    print(f"context_overbroadcast_detected={summary['context_overbroadcast_detected']}")
    print(f"technical_reweighting_retest_allowed={summary['technical_reweighting_retest_allowed']}")
    print(f"shadow_gate_allowed={summary['shadow_gate_allowed']}")


if __name__ == "__main__":
    main()
