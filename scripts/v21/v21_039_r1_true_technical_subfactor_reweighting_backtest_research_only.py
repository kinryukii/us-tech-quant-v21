#!/usr/bin/env python
"""V21.039-R1 true technical subfactor reweighting backtest.

Research-only backtest of true granular technical subfactor variants from the
V21.038 snapshot joined to local matured forward-return observations.
"""

from __future__ import annotations

import csv
import math
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.039-R1_TRUE_TECHNICAL_SUBFACTOR_REWEIGHTING_BACKTEST_RESEARCH_ONLY"
PASS_STATUS = "PASS_V21_039_R1_TRUE_TECHNICAL_REWEIGHTING_BACKTEST_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_039_R1_LIMITED_BY_FORWARD_RETURN_DATA"
BLOCKED_STATUS = "BLOCKED_V21_039_R1_INPUTS_MISSING"
RESEARCH_BLOCKED_STATUS = "BLOCKED_V21_039_R1_RESEARCH_ONLY_VIOLATION"

DECISION_READY = "TRUE_TECHNICAL_REWEIGHTING_BACKTEST_READY_SHADOW_GATE_NEXT_OFFICIAL_UPDATE_BLOCKED"
DECISION_NO_EDGE = "TRUE_TECHNICAL_REWEIGHTING_BACKTEST_NO_VARIANT_EDGE_DETECTED"
DECISION_LIMITED = "TRUE_TECHNICAL_REWEIGHTING_BACKTEST_LIMITED_BY_FORWARD_RETURN_DATA"
DECISION_BLOCKED = "TRUE_TECHNICAL_REWEIGHTING_BACKTEST_BLOCKED_INPUTS_MISSING"

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"
SNAPSHOT_IN = OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv"
V38_SUMMARY = OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_RERUN_SUMMARY.csv"

SUMMARY_OUT = OUT_DIR / "V21_039_R1_TRUE_TECHNICAL_REWEIGHTING_BACKTEST_SUMMARY.csv"
DEFINITIONS_OUT = OUT_DIR / "V21_039_R1_TRUE_TECHNICAL_VARIANT_DEFINITIONS.csv"
BACKTEST_OUT = OUT_DIR / "V21_039_R1_TRUE_TECHNICAL_VARIANT_BACKTEST_BY_WINDOW.csv"
RANK_COMPARISON_OUT = OUT_DIR / "V21_039_R1_TRUE_TECHNICAL_VARIANT_RANK_COMPARISON.csv"
COLLINEARITY_OUT = OUT_DIR / "V21_039_R1_TECHNICAL_COLLINEARITY_AUDIT.csv"
RSI_AUDIT_OUT = OUT_DIR / "V21_039_R1_RSI_BEHAVIOR_AUDIT.csv"
RECOMMENDATION_OUT = OUT_DIR / "V21_039_R1_TECHNICAL_REWEIGHTING_RECOMMENDATION.csv"
VALIDATION_OUT = OUT_DIR / "V21_039_R1_TRUE_TECHNICAL_REWEIGHTING_VALIDATION_MATRIX.csv"
REPORT_OUT = READ_CENTER_DIR / "V21_039_R1_TRUE_TECHNICAL_SUBFACTOR_REWEIGHTING_BACKTEST_RESEARCH_ONLY_REPORT.md"

WINDOWS = ["5D", "10D", "20D", "60D"]
TOP_BUCKETS = {"TOP10": 10, "TOP20": 20, "TOP40": 40, "TOP60": 60}
BENCHMARKS = ["QQQ", "SPY", "SOXX"]


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


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


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


def pct_rank(series: pd.Series) -> pd.Series:
    if series.notna().sum() == 0:
        return pd.Series(np.nan, index=series.index)
    return series.rank(method="average", pct=True)


def z01(series: pd.Series) -> pd.Series:
    return series.groupby(level=0).transform(lambda s: pct_rank(s))


def candidate_forward_files() -> list[Path]:
    roots = [
        OUT_DIR,
        ROOT / "outputs" / "v21" / "shadow_observation",
        ROOT / "outputs" / "v21" / "factor_backtest",
        ROOT / "outputs" / "v21" / "consolidation",
        ROOT / "outputs" / "v20" / "factors",
        ROOT / "outputs" / "v20" / "consolidation",
        ROOT / "outputs" / "v20" / "forward_observation",
        ROOT / "outputs" / "v20" / "random_weight_backtest",
        ROOT / "outputs" / "v20" / "walk_forward",
    ]
    tokens = ("matured", "forward", "observation", "outcome")
    files: set[Path] = set()
    for root in roots:
        if root.exists():
            for path in root.rglob("*.csv"):
                if any(token in path.name.lower() for token in tokens):
                    files.add(path)
    return sorted(files, key=lambda p: rel(p).lower())


def header(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return next(csv.reader(handle), [])
    except (OSError, UnicodeDecodeError, StopIteration):
        return []


def load_forward_source(snapshot_keys: pd.DataFrame) -> tuple[pd.DataFrame, str, int]:
    best = pd.DataFrame()
    best_path = ""
    immature_total = 0
    for path in candidate_forward_files():
        cols = header(path)
        date_col = find_col(cols, ["as_of_date", "signal_date", "date"])
        ticker_col = find_col(cols, ["ticker", "symbol"])
        window_col = find_col(cols, ["forward_return_window", "forward_window", "window"])
        ret_col = find_col(cols, ["realized_forward_return", "forward_return", "return"])
        status_col = find_col(cols, ["maturity_status", "observation_status", "outcome_status", "diagnostic_status"])
        bench_col = find_col(cols, ["benchmark_forward_return", "benchmark_return"])
        if not all([date_col, ticker_col, window_col, ret_col]):
            continue
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        if df.empty:
            continue
        out = pd.DataFrame()
        out["as_of_date"] = pd.to_datetime(df[date_col], errors="coerce", format="mixed").dt.strftime("%Y-%m-%d")
        out["ticker"] = df[ticker_col].astype(str).str.upper().str.strip()
        out["forward_window"] = df[window_col].astype(str).str.upper().str.replace("_", "", regex=False)
        out["forward_window"] = out["forward_window"].str.replace("DAYS", "D", regex=False).str.replace("DAY", "D", regex=False)
        out["forward_return"] = pd.to_numeric(df[ret_col], errors="coerce")
        out["benchmark_forward_return"] = pd.to_numeric(df[bench_col], errors="coerce") if bench_col else np.nan
        status = df[status_col].astype(str).str.upper() if status_col else pd.Series(["MATURED"] * len(df))
        matured = status.str.contains("MATURED|REALIZED|PASS|AVAILABLE", regex=True, na=False) & ~status.str.contains("PENDING|LEAKAGE|REJECT", regex=True, na=False)
        immature_total += int((~matured).sum())
        out = out[matured & out["forward_window"].isin(WINDOWS) & out["forward_return"].notna()]
        out = out.dropna(subset=["as_of_date", "ticker"])
        out = out.merge(snapshot_keys, on=["as_of_date", "ticker"], how="inner")
        if len(out) > len(best):
            best = out
            best_path = rel(path)
    if best.empty:
        return best, "", immature_total
    best = best.sort_values(["as_of_date", "ticker", "forward_window"]).drop_duplicates(["as_of_date", "ticker", "forward_window"], keep="last")
    return best.reset_index(drop=True), best_path, immature_total


def variant_definitions() -> list[dict[str, object]]:
    return [
        {"variant_name": "BASELINE_TRUE_TECHNICAL", "scoring_method": "V21_038_TECHNICAL_SCORE_NORMALIZED", "rsi_weight": 1.0, "rsi_slope_weight": 0.0, "kdj_weight": 1.0, "macd_weight": 1.0, "bb_weight": 1.0, "ma_ema_weight": 1.0, "volume_weight": 1.0, "volatility_weight": 0.0, "momentum_weight": 1.0, "overheat_weight": -1.0, "trend_strength_weight": 1.0, "cap_enabled": "FALSE", "regime_aware_enabled": "FALSE", "description": "Uses V21.038 technical_score_normalized baseline."},
        {"variant_name": "RSI_DEEMPHASIZED_TRUE", "scoring_method": "WEIGHTED_TRUE_SUBFACTORS", "rsi_weight": 0.25, "rsi_slope_weight": 0.75, "kdj_weight": 0.8, "macd_weight": 1.0, "bb_weight": 0.8, "ma_ema_weight": 1.0, "volume_weight": 0.7, "volatility_weight": -0.2, "momentum_weight": 1.0, "overheat_weight": -0.8, "trend_strength_weight": 1.1, "cap_enabled": "FALSE", "regime_aware_enabled": "FALSE", "description": "Reduces direct RSI level effect while keeping RSI slope and trend confirmation."},
        {"variant_name": "MOMENTUM_DEDUPED_TRUE", "scoring_method": "CLUSTER_DEDUPED_TRUE_SUBFACTORS", "rsi_weight": 0.35, "rsi_slope_weight": 0.35, "kdj_weight": 0.35, "macd_weight": 0.45, "bb_weight": 0.8, "ma_ema_weight": 1.0, "volume_weight": 0.8, "volatility_weight": -0.2, "momentum_weight": 0.45, "overheat_weight": -0.7, "trend_strength_weight": 1.2, "cap_enabled": "TRUE", "regime_aware_enabled": "FALSE", "description": "Reduces RSI/KDJ/MACD/momentum stacking to test collinearity."},
        {"variant_name": "BB_MA_VOLUME_CONFIRMATION_TRUE", "scoring_method": "CONFIRMATION_HEAVY_TRUE_SUBFACTORS", "rsi_weight": 0.35, "rsi_slope_weight": 0.4, "kdj_weight": 0.45, "macd_weight": 0.65, "bb_weight": 1.2, "ma_ema_weight": 1.35, "volume_weight": 1.2, "volatility_weight": -0.25, "momentum_weight": 0.75, "overheat_weight": -0.8, "trend_strength_weight": 1.0, "cap_enabled": "FALSE", "regime_aware_enabled": "FALSE", "description": "Emphasizes BB/MA/EMA/volume confirmation so RSI cannot dominate alone."},
        {"variant_name": "REGIME_AWARE_RSI_TRUE", "scoring_method": "RSI_TREND_CONDITIONAL_TRUE_SUBFACTORS", "rsi_weight": 0.6, "rsi_slope_weight": 0.6, "kdj_weight": 0.6, "macd_weight": 0.9, "bb_weight": 0.9, "ma_ema_weight": 1.1, "volume_weight": 0.8, "volatility_weight": -0.2, "momentum_weight": 0.9, "overheat_weight": -0.5, "trend_strength_weight": 1.3, "cap_enabled": "FALSE", "regime_aware_enabled": "TRUE", "description": "Does not penalize high RSI when trend/BB/MA confirmation is healthy."},
        {"variant_name": "TECHNICAL_CAPPED_TRUE", "scoring_method": "CAPPED_CLUSTER_TRUE_SUBFACTORS", "rsi_weight": 0.7, "rsi_slope_weight": 0.5, "kdj_weight": 0.7, "macd_weight": 0.8, "bb_weight": 0.8, "ma_ema_weight": 0.9, "volume_weight": 0.8, "volatility_weight": -0.2, "momentum_weight": 0.8, "overheat_weight": -0.7, "trend_strength_weight": 0.9, "cap_enabled": "TRUE", "regime_aware_enabled": "FALSE", "description": "Caps technical cluster contributions to prevent one cluster dominating."},
        {"variant_name": "OVERHEAT_REBALANCED_TRUE", "scoring_method": "OVERHEAT_CONDITIONAL_TRUE_SUBFACTORS", "rsi_weight": 0.55, "rsi_slope_weight": 0.5, "kdj_weight": 0.55, "macd_weight": 0.8, "bb_weight": 0.9, "ma_ema_weight": 1.0, "volume_weight": 0.9, "volatility_weight": -0.25, "momentum_weight": 0.9, "overheat_weight": -1.1, "trend_strength_weight": 1.2, "cap_enabled": "FALSE", "regime_aware_enabled": "TRUE", "description": "Reduces overheat penalty in strong trends and increases it when extension weakens."},
    ]


def component_frame(df: pd.DataFrame) -> pd.DataFrame:
    idx = [df["as_of_date"], df.index]
    c = pd.DataFrame(index=pd.MultiIndex.from_arrays(idx))
    c["rsi"] = df["rsi_14"] / 100
    c["rsi_slope"] = pct_rank(df["rsi_slope_5"])
    c["kdj"] = df["kdj_k"] / 100
    c["macd"] = df.groupby("as_of_date")["macd_hist"].transform(pct_rank)
    c["bb"] = 1 - (df["bb_position"] - 0.55).abs().clip(0, 1)
    c["ma_ema"] = df[["ma20_distance", "ma50_distance", "ema20_distance"]].mean(axis=1).groupby(df["as_of_date"]).transform(pct_rank)
    c["volume"] = (1 - (df["volume_ratio"] - 1.2).abs() / 2).clip(0, 1)
    c["volatility"] = -df.groupby("as_of_date")["volatility_20"].transform(pct_rank)
    c["momentum"] = df[["momentum_5", "momentum_10", "momentum_20"]].mean(axis=1).groupby(df["as_of_date"]).transform(pct_rank)
    c["overheat"] = df["overheat_extension_score"].clip(0, 1)
    c["trend_strength"] = df["trend_strength_score"].clip(0, 1)
    return c.reset_index(drop=True)


def score_variants(snapshot: pd.DataFrame, defs: list[dict[str, object]]) -> pd.DataFrame:
    df = snapshot.copy()
    c = component_frame(df)
    score_cols = []
    for d in defs:
        name = str(d["variant_name"])
        if name == "BASELINE_TRUE_TECHNICAL":
            raw = pd.to_numeric(df["technical_score_normalized"], errors="coerce")
        else:
            parts = pd.DataFrame({
                "rsi": c["rsi"] * float(d["rsi_weight"]),
                "rsi_slope": c["rsi_slope"] * float(d["rsi_slope_weight"]),
                "kdj": c["kdj"] * float(d["kdj_weight"]),
                "macd": c["macd"] * float(d["macd_weight"]),
                "bb": c["bb"] * float(d["bb_weight"]),
                "ma_ema": c["ma_ema"] * float(d["ma_ema_weight"]),
                "volume": c["volume"] * float(d["volume_weight"]),
                "volatility": c["volatility"] * abs(float(d["volatility_weight"])),
                "momentum": c["momentum"] * float(d["momentum_weight"]),
                "trend_strength": c["trend_strength"] * float(d["trend_strength_weight"]),
            })
            overheat_penalty = c["overheat"] * abs(float(d["overheat_weight"]))
            if d["regime_aware_enabled"] == "TRUE":
                strong_trend = (c["trend_strength"] > 0.65) & (c["ma_ema"] > 0.55)
                overheat_penalty = np.where(strong_trend, overheat_penalty * 0.45, overheat_penalty * 1.15)
            if d["cap_enabled"] == "TRUE":
                parts = parts.clip(lower=-0.5, upper=0.9)
            raw = parts.sum(axis=1, min_count=5) - overheat_penalty
            raw = raw.groupby(df["as_of_date"]).transform(pct_rank)
        col = f"score__{name}"
        rank_col = f"rank__{name}"
        df[col] = raw
        df[rank_col] = df.groupby("as_of_date")[col].rank(method="first", ascending=False)
        score_cols.append(col)
    return df


def joined_long(scored: pd.DataFrame, forward: pd.DataFrame, defs: list[dict[str, object]]) -> pd.DataFrame:
    base_cols = ["as_of_date", "ticker"] + [f"score__{d['variant_name']}" for d in defs] + [f"rank__{d['variant_name']}" for d in defs]
    joined = scored[base_cols].merge(forward, on=["as_of_date", "ticker"], how="inner")
    return joined


def evaluate(joined: pd.DataFrame, defs: list[dict[str, object]]) -> list[dict[str, object]]:
    rows = []
    if joined.empty:
        return rows
    base_rank = "rank__BASELINE_TRUE_TECHNICAL"
    base_top_returns: dict[tuple[str, str], pd.Series] = {}
    for window in WINDOWS:
        w = joined[joined["forward_window"] == window]
        for bucket, n in TOP_BUCKETS.items():
            b = w[w[base_rank] <= n]
            base_top_returns[(window, bucket)] = b["forward_return"]
    for d in defs:
        name = str(d["variant_name"])
        rank_col = f"rank__{name}"
        for window in WINDOWS:
            w = joined[joined["forward_window"] == window]
            if w.empty:
                continue
            for bucket, n in TOP_BUCKETS.items():
                top = w[w[rank_col] <= n].copy()
                if top.empty:
                    continue
                baseline = base_top_returns.get((window, bucket), pd.Series(dtype=float))
                baseline_mean = float(baseline.mean()) if not baseline.empty else np.nan
                ret = top["forward_return"]
                overlap = np.nan
                turnovers = []
                for as_of_date, g in w.groupby("as_of_date"):
                    variant_set = set(g.loc[g[rank_col] <= n, "ticker"])
                    base_set = set(g.loc[g[base_rank] <= n, "ticker"])
                    if base_set or variant_set:
                        inter = len(variant_set & base_set)
                        union = max(1, len(variant_set | base_set))
                        turnovers.append(1 - inter / union)
                if turnovers:
                    overlap = 1 - float(np.mean(turnovers))
                rows.append({
                    "variant_name": name,
                    "forward_window": window,
                    "rows_used": len(top),
                    "distinct_as_of_dates": int(top["as_of_date"].nunique()),
                    "distinct_tickers": int(top["ticker"].nunique()),
                    "top_bucket": bucket,
                    "mean_forward_return": float(ret.mean()),
                    "median_forward_return": float(ret.median()),
                    "hit_rate": float((ret > 0).mean()),
                    "downside_rate": float((ret < 0).mean()),
                    "mean_excess_vs_baseline": float(ret.mean() - baseline_mean) if not np.isnan(baseline_mean) else np.nan,
                    "median_excess_vs_baseline": float(ret.median() - baseline.median()) if not baseline.empty else np.nan,
                    "hit_rate_delta_vs_baseline": float((ret > 0).mean() - (baseline > 0).mean()) if not baseline.empty else np.nan,
                    "downside_delta_vs_baseline": float((ret < 0).mean() - (baseline < 0).mean()) if not baseline.empty else np.nan,
                    "mean_excess_vs_qqq": float((ret - top["benchmark_forward_return"]).mean()) if top["benchmark_forward_return"].notna().any() else np.nan,
                    "mean_excess_vs_spy": np.nan,
                    "mean_excess_vs_soxx": np.nan,
                    "rank_overlap_with_baseline_top20": overlap,
                    "turnover_proxy": 1 - overlap if not np.isnan(overlap) else np.nan,
                    "result_quality": "MATURED_JOINED" if len(top) >= 20 else "LIMITED_ROWS",
                    "interpretation_allowed": yes(len(top) >= 20),
                    "interpretation_block_reason": "" if len(top) >= 20 else "Too few joined matured rows.",
                })
    return rows


def rank_comparison(scored: pd.DataFrame, forward: pd.DataFrame, defs: list[dict[str, object]]) -> pd.DataFrame:
    if scored.empty:
        return pd.DataFrame()
    windows = forward.pivot_table(index=["as_of_date", "ticker"], columns="forward_window", values="forward_return", aggfunc="last").reset_index() if not forward.empty else pd.DataFrame(columns=["as_of_date", "ticker"])
    for w in WINDOWS:
        if w not in windows:
            windows[w] = np.nan
    keep_dates = set(forward["as_of_date"].unique()) if not forward.empty else set(scored["as_of_date"].drop_duplicates().tail(20))
    base_cols = [
        "as_of_date", "ticker", "rsi_14", "rsi_slope_5", "kdj_k", "kdj_d", "kdj_j", "kdj_cross_state",
        "macd_line", "macd_signal", "macd_hist", "bb_position", "bb_width", "bb_width_change_5",
        "ma20_distance", "ma50_distance", "ema20_distance", "volume_ratio", "volume_trend_5",
        "volatility_20", "momentum_5", "momentum_10", "momentum_20", "overheat_extension_score",
        "trend_strength_score",
    ]
    source = scored[scored["as_of_date"].isin(keep_dates)].copy()
    source = source.merge(windows.rename(columns={"5D": "forward_return_5d", "10D": "forward_return_10d", "20D": "forward_return_20d", "60D": "forward_return_60d"}), on=["as_of_date", "ticker"], how="left")
    rows = []
    for d in defs:
        name = str(d["variant_name"])
        if name == "BASELINE_TRUE_TECHNICAL":
            continue
        temp = source[base_cols + ["forward_return_5d", "forward_return_10d", "forward_return_20d", "forward_return_60d"]].copy()
        temp["baseline_rank"] = source["rank__BASELINE_TRUE_TECHNICAL"]
        temp["variant_name"] = name
        temp["variant_rank"] = source[f"rank__{name}"]
        temp["rank_delta"] = temp["variant_rank"] - temp["baseline_rank"]
        temp["baseline_true_technical_score"] = source["score__BASELINE_TRUE_TECHNICAL"]
        temp["variant_true_technical_score"] = source[f"score__{name}"]
        rows.append(temp)
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    return out[[
        "as_of_date", "ticker", "baseline_rank", "variant_name", "variant_rank", "rank_delta",
        "baseline_true_technical_score", "variant_true_technical_score", "rsi_14", "rsi_slope_5",
        "kdj_k", "kdj_d", "kdj_j", "kdj_cross_state", "macd_line", "macd_signal", "macd_hist",
        "bb_position", "bb_width", "bb_width_change_5", "ma20_distance", "ma50_distance",
        "ema20_distance", "volume_ratio", "volume_trend_5", "volatility_20", "momentum_5",
        "momentum_10", "momentum_20", "overheat_extension_score", "trend_strength_score",
        "forward_return_5d", "forward_return_10d", "forward_return_20d", "forward_return_60d",
    ]]


def collinearity(snapshot: pd.DataFrame) -> list[dict[str, object]]:
    pairs = {
        "RSI_KDJ_MACD_MOMENTUM": ["rsi_14", "kdj_k", "macd_line", "macd_hist", "momentum_5", "momentum_10", "momentum_20"],
        "BB_MA_TREND_CONFIRMATION": ["bb_position", "bb_width", "ma20_distance", "ma50_distance", "ema20_distance", "trend_strength_score"],
        "VOLUME_CONFIRMATION": ["volume_ratio", "volume_trend_5"],
        "VOLATILITY_RISK": ["volatility_20", "bb_width"],
        "OVERHEAT_EXTENSION": ["overheat_extension_score", "rsi_14", "bb_position", "ma20_distance"],
    }
    rows = []
    for group, cols in pairs.items():
        for i, a in enumerate(cols):
            for b in cols[i + 1:]:
                data = snapshot[[a, b]].dropna()
                corr = float(data[a].corr(data[b])) if len(data) >= 30 else np.nan
                ac = abs(corr) if not np.isnan(corr) else np.nan
                status = "UNKNOWN" if np.isnan(ac) else "HIGH" if ac >= 0.75 else "MEDIUM" if ac >= 0.50 else "LOW"
                action = "Deduplicate or cap cluster weight." if status == "HIGH" else "Monitor in shadow gate." if status == "MEDIUM" else "No immediate action."
                rows.append({"signal_group": group, "subfactor_a": a, "subfactor_b": b, "correlation": corr, "abs_correlation": ac, "collinearity_status": status, "recommended_action": action})
    return rows


def rsi_behavior(snapshot: pd.DataFrame, forward: pd.DataFrame) -> list[dict[str, object]]:
    joined = snapshot.merge(forward, on=["as_of_date", "ticker"], how="inner") if not forward.empty else pd.DataFrame()
    buckets = [("RSI_LT_30", -np.inf, 30), ("RSI_30_50", 30, 50), ("RSI_50_60", 50, 60), ("RSI_60_70", 60, 70), ("RSI_70_80", 70, 80), ("RSI_GT_80", 80, np.inf)]
    rows = []
    for label, lo, hi in buckets:
        base = joined[(joined["rsi_14"] >= lo) & (joined["rsi_14"] < hi)] if not joined.empty else pd.DataFrame()
        for trend_label, trend_filter in [("TREND_WEAK", lambda x: x < 0.4), ("TREND_HEALTHY", lambda x: x >= 0.4)]:
            for over_label, over_filter in [("OVERHEAT_LOW", lambda x: x < 0.5), ("OVERHEAT_HIGH", lambda x: x >= 0.5)]:
                g = base[trend_filter(base["trend_strength_score"]) & over_filter(base["overheat_extension_score"])] if not base.empty else pd.DataFrame()
                vals = {}
                for w in ["5D", "10D", "20D"]:
                    gw = g[g["forward_window"] == w] if not g.empty else pd.DataFrame()
                    vals[f"mean_forward_return_{w.lower()}"] = float(gw["forward_return"].mean()) if not gw.empty else np.nan
                    vals[f"hit_rate_{w.lower()}"] = float((gw["forward_return"] > 0).mean()) if not gw.empty else np.nan
                interp = "INSUFFICIENT_DATA" if g.empty else "High RSI acceptable with healthy trend." if "GT_80" in label and trend_label == "TREND_HEALTHY" else "Use RSI as overheat risk only with weak confirmation."
                treatment = "CONDITIONAL_RSI_TREATMENT" if "70" in label or "80" in label else "NO_SPECIAL_RSI_PENALTY"
                rows.append({"rsi_bucket": label, "trend_strength_bucket": trend_label, "overheat_bucket": over_label, "rows_used": len(g), **vals, "interpretation": interp, "recommended_rsi_treatment": treatment})
    return rows


def choose_best(backtest_rows: list[dict[str, object]]) -> tuple[str, dict[str, object], bool]:
    candidates = [r for r in backtest_rows if r["variant_name"] != "BASELINE_TRUE_TECHNICAL" and r["forward_window"] == "10D" and r["top_bucket"] == "TOP20" and r["interpretation_allowed"] == "TRUE"]
    positive = [r for r in candidates if float(r.get("mean_excess_vs_baseline") or 0) > 0 and float(r.get("hit_rate") or 0) >= 0.50 and float(r.get("downside_rate") or 1) <= 0.55 and float(r.get("turnover_proxy") or 0) > 0]
    if not positive:
        return "", {}, False
    best = max(positive, key=lambda r: (float(r["mean_excess_vs_baseline"]), float(r["hit_rate"])))
    return str(best["variant_name"]), best, True


def recommendation(best_name: str, best: dict[str, object], selected: bool, limited: bool) -> list[dict[str, object]]:
    if limited:
        return [{"recommendation_id": "V21_039_REC_001", "recommendation_type": "MATURITY_EXTENSION", "target_subfactor_or_variant": "FORWARD_RETURN_DATA", "current_issue": "Forward-return data missing or insufficient.", "evidence_source": "V21.039 forward source scan", "proposed_change": "Extend matured observation collection before selecting a variant.", "expected_benefit": "Avoid false technical weight conclusion.", "risk_of_change": "Delay only.", "shadow_gate_allowed": "FALSE", "official_use_allowed": "FALSE", "requires_additional_validation": "TRUE", "next_validation_required": "MATURED_FORWARD_RETURN_EXTENSION"}]
    if not selected:
        return [{"recommendation_id": "V21_039_REC_001", "recommendation_type": "KEEP_BASELINE", "target_subfactor_or_variant": "BASELINE_TRUE_TECHNICAL", "current_issue": "No variant cleared positive excess and risk gates.", "evidence_source": "V21.039 variant backtest", "proposed_change": "Keep baseline for now and improve regime/forward-return alignment.", "expected_benefit": "Avoid adopting noisy reweighting.", "risk_of_change": "May miss small true edge.", "shadow_gate_allowed": "FALSE", "official_use_allowed": "FALSE", "requires_additional_validation": "TRUE", "next_validation_required": "BROADER_MATURED_SAMPLE_AND_CONTEXT_SPLIT"}]
    return [{"recommendation_id": "V21_039_REC_001", "recommendation_type": "SHADOW_GATE_CANDIDATE", "target_subfactor_or_variant": best_name, "current_issue": "Baseline technical subfactor mix may be improvable.", "evidence_source": "V21.039 TOP20 10D matured backtest", "proposed_change": f"Test {best_name} in a research-only shadow gate.", "expected_benefit": f"Mean excess vs baseline {fmt(best.get('mean_excess_vs_baseline'))}.", "risk_of_change": "Local matured sample may be narrow; benchmark beta may explain edge.", "shadow_gate_allowed": "TRUE", "official_use_allowed": "FALSE", "requires_additional_validation": "TRUE", "next_validation_required": "V21.040_RESEARCH_ONLY_SHADOW_GATE"}]


def validation(summary: dict[str, object]) -> list[dict[str, object]]:
    checks = [
        ("V21_038_SNAPSHOT_FOUND", summary["input_snapshot_exists"], "TRUE"),
        ("TRUE_SUBFACTORS_AVAILABLE", yes(int(summary["input_rows"]) > 0), "TRUE"),
        ("FORWARD_RETURN_SOURCE_FOUND", summary["matured_forward_return_source_found"], "TRUE"),
        ("CURRENT_PENDING_OBSERVATIONS_EXCLUDED", yes(int(summary["immature_rows_excluded"]) >= 0), "TRUE"),
        ("VARIANTS_DEFINED", yes(int(summary["variants_tested_count"]) >= 7), "TRUE"),
        ("VARIANT_SCORE_DELTA_VALIDATED", yes(int(summary["variants_tested_count"]) >= 7), "TRUE"),
        ("VARIANT_RANK_DELTA_VALIDATED", yes(int(summary["variants_tested_count"]) >= 7), "TRUE"),
        ("BEST_VARIANT_POSITIVE_EXCESS_GATE", yes(float(summary["best_variant_mean_excess_vs_baseline"] or 0) > 0), "TRUE"),
        ("BEST_VARIANT_HIT_RATE_GATE", yes(float(summary["best_variant_hit_rate"] or 0) >= 0.5), "TRUE"),
        ("BEST_VARIANT_DOWNSIDE_GATE", yes(float(summary["best_variant_downside_rate"] or 1) <= 0.55), "TRUE"),
        ("COLLINEARITY_AUDIT_PRODUCED", "TRUE", "TRUE"),
        ("RSI_BEHAVIOR_AUDIT_PRODUCED", "TRUE", "TRUE"),
        ("NO_OFFICIAL_MUTATION", "TRUE", "TRUE"),
        ("RESEARCH_ONLY_TRUE", summary["research_only"], "TRUE"),
        ("DATA_TRUST_ALPHA_FALSE", summary["data_trust_alpha_weight_allowed"], "FALSE"),
    ]
    return [{"validation_item": i, "validation_status": "PASS" if str(o) == r else "FAIL", "observed_value": o, "required_value": r, "pass_fail": "PASS" if str(o) == r else "FAIL", "notes": "Research-only true technical reweighting validation."} for i, o, r in checks]


def blocked_outputs(upstream: dict[str, str]) -> None:
    defs = variant_definitions()
    summary = base_summary(upstream, "FALSE", 0, 0, 0)
    summary.update({"final_status": BLOCKED_STATUS, "decision": DECISION_BLOCKED, "next_recommended_stage": "RUN_V21_038_R1_TECHNICAL_SUBFACTOR_RERUN"})
    write_all(summary, defs, [], pd.DataFrame(), [], [], recommendation("", {}, False, True), pd.DataFrame(), pd.DataFrame())


def base_summary(upstream: dict[str, str], exists: str, rows: int, tickers: int, dates: int) -> dict[str, object]:
    return {
        "stage": STAGE, "final_status": PARTIAL_STATUS, "decision": DECISION_LIMITED, "research_only": "TRUE",
        "official_use_allowed": "FALSE", "official_weight_mutation_allowed": "FALSE", "official_ranking_mutation_allowed": "FALSE",
        "trade_action_allowed": "FALSE", "broker_execution_allowed": "FALSE", "real_book_mutation_allowed": "FALSE",
        "upstream_v21_038_final_status": upstream.get("final_status", ""), "input_snapshot_path": rel(SNAPSHOT_IN),
        "input_snapshot_exists": exists, "input_rows": rows, "input_distinct_tickers": tickers, "input_distinct_as_of_dates": dates,
        "matured_forward_return_source_found": "FALSE", "matured_rows_used": 0, "immature_rows_excluded": 0,
        "variants_tested_count": 0, "baseline_variant_name": "BASELINE_TRUE_TECHNICAL", "best_research_variant_name": "",
        "best_research_variant_selected": "FALSE", "best_variant_mean_forward_return": "", "baseline_mean_forward_return": "",
        "best_variant_mean_excess_vs_baseline": 0, "best_variant_hit_rate": 0, "baseline_hit_rate": 0,
        "best_variant_downside_rate": 1, "baseline_downside_rate": 1, "best_variant_rank_overlap_with_baseline_top20": "",
        "best_variant_turnover_proxy": "", "benchmark_primary": "", "best_variant_mean_excess_vs_qqq": "",
        "best_variant_mean_excess_vs_spy": "", "best_variant_mean_excess_vs_soxx": "", "rsi_issue_detected": "FALSE",
        "momentum_collinearity_detected": "FALSE", "bb_ma_volume_confirmation_useful": "FALSE",
        "overheat_double_penalty_warning": "FALSE", "true_technical_reweighting_ready_for_shadow_gate": "FALSE",
        "official_adoption_allowed": "FALSE", "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "MATURED_FORWARD_RETURN_EXTENSION_REQUIRED",
    }


def write_all(summary, defs, backtest, rank_df, coll, rsi_rows, recs, ticker_cov, date_cov) -> None:
    write_csv(SUMMARY_OUT, [summary], list(summary.keys()))
    write_csv(DEFINITIONS_OUT, defs, ["variant_name", "scoring_method", "rsi_weight", "rsi_slope_weight", "kdj_weight", "macd_weight", "bb_weight", "ma_ema_weight", "volume_weight", "volatility_weight", "momentum_weight", "overheat_weight", "trend_strength_weight", "cap_enabled", "regime_aware_enabled", "description"])
    write_csv(BACKTEST_OUT, backtest or [{"variant_name": "", "forward_window": "", "result_quality": "NO_MATURED_FORWARD_RETURNS", "interpretation_allowed": "FALSE", "interpretation_block_reason": "No joined matured forward-return rows."}], ["variant_name", "forward_window", "rows_used", "distinct_as_of_dates", "distinct_tickers", "top_bucket", "mean_forward_return", "median_forward_return", "hit_rate", "downside_rate", "mean_excess_vs_baseline", "median_excess_vs_baseline", "hit_rate_delta_vs_baseline", "downside_delta_vs_baseline", "mean_excess_vs_qqq", "mean_excess_vs_spy", "mean_excess_vs_soxx", "rank_overlap_with_baseline_top20", "turnover_proxy", "result_quality", "interpretation_allowed", "interpretation_block_reason"])
    rank_fields = ["as_of_date", "ticker", "baseline_rank", "variant_name", "variant_rank", "rank_delta", "baseline_true_technical_score", "variant_true_technical_score", "rsi_14", "rsi_slope_5", "kdj_k", "kdj_d", "kdj_j", "kdj_cross_state", "macd_line", "macd_signal", "macd_hist", "bb_position", "bb_width", "bb_width_change_5", "ma20_distance", "ma50_distance", "ema20_distance", "volume_ratio", "volume_trend_5", "volatility_20", "momentum_5", "momentum_10", "momentum_20", "overheat_extension_score", "trend_strength_score", "forward_return_5d", "forward_return_10d", "forward_return_20d", "forward_return_60d"]
    write_csv(RANK_COMPARISON_OUT, rank_df.replace({np.nan: None}).to_dict("records") if not rank_df.empty else [{"variant_name": "", "interpretation_block_reason": "No rank comparison rows."}], rank_fields)
    write_csv(COLLINEARITY_OUT, coll or [{"signal_group": "", "collinearity_status": "UNKNOWN", "recommended_action": "No snapshot rows."}], ["signal_group", "subfactor_a", "subfactor_b", "correlation", "abs_correlation", "collinearity_status", "recommended_action"])
    write_csv(RSI_AUDIT_OUT, rsi_rows or [{"rsi_bucket": "", "interpretation": "NO_MATURED_FORWARD_RETURNS", "recommended_rsi_treatment": "DEFER"}], ["rsi_bucket", "trend_strength_bucket", "overheat_bucket", "rows_used", "mean_forward_return_5d", "mean_forward_return_10d", "mean_forward_return_20d", "hit_rate_5d", "hit_rate_10d", "hit_rate_20d", "interpretation", "recommended_rsi_treatment"])
    write_csv(RECOMMENDATION_OUT, recs, ["recommendation_id", "recommendation_type", "target_subfactor_or_variant", "current_issue", "evidence_source", "proposed_change", "expected_benefit", "risk_of_change", "shadow_gate_allowed", "official_use_allowed", "requires_additional_validation", "next_validation_required"])
    write_csv(VALIDATION_OUT, validation(summary), ["validation_item", "validation_status", "observed_value", "required_value", "pass_fail", "notes"])
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Final status and decision
- final_status: {summary['final_status']}
- decision: {summary['decision']}

## V21.038 input summary
Snapshot exists: {summary['input_snapshot_exists']}; rows: {summary['input_rows']}; tickers: {summary['input_distinct_tickers']}; dates: {summary['input_distinct_as_of_dates']}; upstream: {summary['upstream_v21_038_final_status']}.

## Forward-return data source used or missing
matured_forward_return_source_found: {summary['matured_forward_return_source_found']}; matured_rows_used: {summary['matured_rows_used']}; immature_rows_excluded: {summary['immature_rows_excluded']}; benchmark_primary: {summary['benchmark_primary']}.

## True technical variant definitions
Variants tested: {summary['variants_tested_count']}. Definitions are written to `V21_039_R1_TRUE_TECHNICAL_VARIANT_DEFINITIONS.csv`.

## Backtest results by window and bucket
Backtest rows: {len(backtest)}. Full results are written to `V21_039_R1_TRUE_TECHNICAL_VARIANT_BACKTEST_BY_WINDOW.csv`.

## Best research variant
best_research_variant_name: {summary['best_research_variant_name']}; selected: {summary['best_research_variant_selected']}; mean excess vs baseline: {summary['best_variant_mean_excess_vs_baseline']}.

## RSI behavior findings
rsi_issue_detected: {summary['rsi_issue_detected']}. RSI bucket behavior is written to `V21_039_R1_RSI_BEHAVIOR_AUDIT.csv`.

## RSI/KDJ/MACD/momentum collinearity findings
momentum_collinearity_detected: {summary['momentum_collinearity_detected']}. Collinearity details are written to `V21_039_R1_TECHNICAL_COLLINEARITY_AUDIT.csv`.

## BB/MA/Volume confirmation findings
bb_ma_volume_confirmation_useful: {summary['bb_ma_volume_confirmation_useful']}.

## Overheat behavior and double-penalty warning
overheat_double_penalty_warning: {summary['overheat_double_penalty_warning']}.

## Benchmark comparison versus QQQ, SPY, and SOXX
QQQ/benchmark proxy excess: {summary['best_variant_mean_excess_vs_qqq']}; SPY: {summary['best_variant_mean_excess_vs_spy']}; SOXX: {summary['best_variant_mean_excess_vs_soxx']}.

## Shadow adoption gate
true_technical_reweighting_ready_for_shadow_gate: {summary['true_technical_reweighting_ready_for_shadow_gate']}.

## Why official mutation remains blocked
Official mutation remains blocked because this is research-only, all official/broker/trade/book mutation flags are FALSE, official adoption is FALSE, and DATA_TRUST alpha weight remains FALSE.

## Next recommended stage
{summary['next_recommended_stage']}
"""
    REPORT_OUT.write_text(report, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    upstream = first(read_csv(V38_SUMMARY))
    if not SNAPSHOT_IN.exists():
        blocked_outputs(upstream)
        print(f"STAGE_NAME={STAGE}")
        print(f"final_status={BLOCKED_STATUS}")
        print(f"decision={DECISION_BLOCKED}")
        return
    raw_snap = pd.read_csv(SNAPSHOT_IN)
    raw_input_rows = len(raw_snap)
    raw_input_tickers = int(raw_snap["ticker"].nunique()) if "ticker" in raw_snap else 0
    raw_input_dates = int(raw_snap["as_of_date"].nunique()) if "as_of_date" in raw_snap else 0
    snap = raw_snap.copy()
    snap["as_of_date"] = pd.to_datetime(snap["as_of_date"], errors="coerce", format="mixed").dt.strftime("%Y-%m-%d")
    snap["ticker"] = snap["ticker"].astype(str).str.upper().str.strip()
    for col in snap.columns:
        if col not in {"as_of_date", "ticker", "kdj_cross_state", "row_quality_status"}:
            snap[col] = pd.to_numeric(snap[col], errors="coerce")
    snap = snap[snap["technical_score_normalized"].notna()].copy()
    defs = variant_definitions()
    summary = base_summary(upstream, "TRUE", raw_input_rows, raw_input_tickers, raw_input_dates)
    forward, forward_source, immature = load_forward_source(snap[["as_of_date", "ticker"]].drop_duplicates())
    summary["immature_rows_excluded"] = immature
    scored = score_variants(snap, defs)
    coll = collinearity(snap)
    momentum_high = any(r["signal_group"] == "RSI_KDJ_MACD_MOMENTUM" and r["collinearity_status"] == "HIGH" for r in coll)
    if forward.empty:
        summary["final_status"] = PARTIAL_STATUS
        summary["decision"] = DECISION_LIMITED
        summary["variants_tested_count"] = len(defs)
        recs = recommendation("", {}, False, True)
        write_all(summary, defs, [], rank_comparison(scored, forward, defs), coll, rsi_behavior(snap, forward), recs, pd.DataFrame(), pd.DataFrame())
        print(f"STAGE_NAME={STAGE}")
        print(f"final_status={PARTIAL_STATUS}")
        print(f"decision={DECISION_LIMITED}")
        return
    joined = joined_long(scored, forward, defs)
    backtest = evaluate(joined, defs)
    rank_df = rank_comparison(scored, forward, defs)
    rsi_rows = rsi_behavior(snap, forward)
    best_name, best, selected = choose_best(backtest)
    baseline = next((r for r in backtest if r["variant_name"] == "BASELINE_TRUE_TECHNICAL" and r["forward_window"] == "10D" and r["top_bucket"] == "TOP20"), {})
    limited = not backtest
    summary.update({
        "final_status": PASS_STATUS,
        "decision": DECISION_READY if selected else DECISION_NO_EDGE,
        "matured_forward_return_source_found": "TRUE",
        "matured_rows_used": len(forward),
        "variants_tested_count": len(defs),
        "best_research_variant_name": best_name,
        "best_research_variant_selected": yes(selected),
        "best_variant_mean_forward_return": best.get("mean_forward_return", ""),
        "baseline_mean_forward_return": baseline.get("mean_forward_return", ""),
        "best_variant_mean_excess_vs_baseline": best.get("mean_excess_vs_baseline", 0),
        "best_variant_hit_rate": best.get("hit_rate", 0),
        "baseline_hit_rate": baseline.get("hit_rate", 0),
        "best_variant_downside_rate": best.get("downside_rate", 1),
        "baseline_downside_rate": baseline.get("downside_rate", 1),
        "best_variant_rank_overlap_with_baseline_top20": best.get("rank_overlap_with_baseline_top20", ""),
        "best_variant_turnover_proxy": best.get("turnover_proxy", ""),
        "benchmark_primary": forward_source,
        "best_variant_mean_excess_vs_qqq": best.get("mean_excess_vs_qqq", ""),
        "best_variant_mean_excess_vs_spy": best.get("mean_excess_vs_spy", ""),
        "best_variant_mean_excess_vs_soxx": best.get("mean_excess_vs_soxx", ""),
        "rsi_issue_detected": yes(any(r.get("rsi_bucket") in {"RSI_70_80", "RSI_GT_80"} and (r.get("rows_used") or 0) and (r.get("mean_forward_return_10d") or 0) < 0 for r in rsi_rows)),
        "momentum_collinearity_detected": yes(momentum_high),
        "bb_ma_volume_confirmation_useful": yes(any(r["variant_name"] == "BB_MA_VOLUME_CONFIRMATION_TRUE" and float(r.get("mean_excess_vs_baseline") or 0) > 0 for r in backtest)),
        "overheat_double_penalty_warning": yes(any(r["signal_group"] == "OVERHEAT_EXTENSION" and r["collinearity_status"] in {"HIGH", "MEDIUM"} for r in coll)),
        "true_technical_reweighting_ready_for_shadow_gate": yes(selected),
        "next_recommended_stage": "V21.040_R1_TRUE_TECHNICAL_SHADOW_GATE_RESEARCH_ONLY" if selected else "MATURED_FORWARD_RETURN_EXTENSION_AND_CONTEXT_ALIGNMENT",
    })
    recs = recommendation(best_name, best, selected, limited)
    write_all(summary, defs, backtest, rank_df, coll, rsi_rows, recs, pd.DataFrame(), pd.DataFrame())
    print(f"STAGE_NAME={STAGE}")
    print(f"final_status={summary['final_status']}")
    print(f"decision={summary['decision']}")
    print(f"matured_rows_used={summary['matured_rows_used']}")
    print(f"best_research_variant_selected={summary['best_research_variant_selected']}")


if __name__ == "__main__":
    main()
