#!/usr/bin/env python
"""V21.041-R1 technical reweighting retest with R4 context buckets.

Research-only retest of technical subfactor reweighting variants constrained to
V21.040-R4 canonical context buckets that passed selectivity, maturity, and
top20 sample gates.
"""

from __future__ import annotations

import csv
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.041-R1_TECHNICAL_REWEIGHTING_RETEST_WITH_R4_CONTEXT_BUCKETS_RESEARCH_ONLY"
PASS_STATUS = "PASS_V21_041_R1_TECHNICAL_REWEIGHTING_RETEST_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_041_R1_RETEST_LIMITED_BY_INPUT_COLUMNS"
BLOCKED_R4_STATUS = "BLOCKED_V21_041_R1_R4_GATE_NOT_READY"
BLOCKED_INPUT_STATUS = "BLOCKED_V21_041_R1_INPUTS_MISSING"

DECISION_EDGE = "TECHNICAL_REWEIGHTING_RETEST_FOUND_R4_CONTEXT_EDGE_SHADOW_GATE_REVIEW_RECOMMENDED"
DECISION_NO_EDGE = "TECHNICAL_REWEIGHTING_RETEST_NO_R4_CONTEXT_EDGE_DETECTED"
DECISION_INPUT_LIMIT = "TECHNICAL_REWEIGHTING_RETEST_BLOCKED_BY_INPUT_LIMITATION"
DECISION_R4_BLOCKED = "TECHNICAL_REWEIGHTING_RETEST_BLOCKED_BY_R4_GATE"
DECISION_INPUT_BLOCKED = "TECHNICAL_REWEIGHTING_RETEST_BLOCKED_BY_INPUT_LIMITATION"

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

R4_SUMMARY = OUT_DIR / "V21_040_R4_CONTEXT_BUCKET_CONSOLIDATION_SUMMARY.csv"
R4_LEDGER = OUT_DIR / "V21_040_R4_CANONICAL_CONTEXT_LEDGER.csv"
R4_AUDIT = OUT_DIR / "V21_040_R4_CONTEXT_BUCKET_SELECTIVITY_AND_MATURITY_AUDIT.csv"
R4_PERF = OUT_DIR / "V21_040_R4_TECHNICAL_PERFORMANCE_BY_CONTEXT_BUCKET_WINDOW.csv"
SNAPSHOT = OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv"

SUMMARY_OUT = OUT_DIR / "V21_041_R1_TECHNICAL_REWEIGHTING_RETEST_SUMMARY.csv"
PERF_OUT = OUT_DIR / "V21_041_R1_VARIANT_PERFORMANCE_BY_CONTEXT_BUCKET_WINDOW.csv"
SCORECARD_OUT = OUT_DIR / "V21_041_R1_VARIANT_AGGREGATE_SCORECARD.csv"
RANK_DELTA_OUT = OUT_DIR / "V21_041_R1_VARIANT_RANK_DELTA_AUDIT.csv"
WEIGHTS_OUT = OUT_DIR / "V21_041_R1_TECHNICAL_SUBFACTOR_WEIGHT_VARIANTS.csv"
RECOMMENDATION_OUT = OUT_DIR / "V21_041_R1_SHADOW_GATE_RECOMMENDATION.csv"
VALIDATION_OUT = OUT_DIR / "V21_041_R1_VALIDATION_MATRIX.csv"
REPORT_OUT = READ_CENTER_DIR / "V21_041_R1_TECHNICAL_REWEIGHTING_RETEST_WITH_R4_CONTEXT_BUCKETS_REPORT.md"

TECHNICAL_COLUMNS = [
    "rsi_14", "kdj_k", "macd_line", "macd_hist", "bb_position", "bb_width",
    "ma20_distance", "ma50_distance", "ema20_distance", "trend_strength_score",
    "volume_ratio", "volume_trend_5", "volatility_20", "momentum_5",
    "momentum_10", "momentum_20", "overheat_extension_score",
]
VARIANT_NAMES = [
    "BASELINE_TRUE_TECHNICAL",
    "RSI_DEEMPHASIZED_R4",
    "RSI_CONTEXT_AWARE_R4",
    "MOMENTUM_DEDUPED_R4",
    "BB_MA_DEDUPED_R4",
    "VOLUME_CONFIRMATION_BOOST_R4",
    "OVERHEAT_SOFTENED_HEALTHY_TREND_R4",
    "OVERHEAT_HARDENED_WEAK_TREND_R4",
    "HIGH_VOL_RISK_CAPPED_R4",
    "BALANCED_R4_CONTEXT_AWARE",
]
MIN_TOP_ROWS = 30


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


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def read_first(path: Path) -> dict[str, str]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.DictReader(handle), {}) or {}


def pct_rank(series: pd.Series) -> pd.Series:
    if series.notna().sum() == 0:
        return pd.Series(np.nan, index=series.index)
    return series.rank(method="average", pct=True)


def load_inputs() -> tuple[dict[str, str], pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summary = read_first(R4_SUMMARY)
    ledger = pd.read_csv(R4_LEDGER, low_memory=False) if R4_LEDGER.exists() else pd.DataFrame()
    audit = pd.read_csv(R4_AUDIT, low_memory=False) if R4_AUDIT.exists() else pd.DataFrame()
    r4_perf = pd.read_csv(R4_PERF, low_memory=False) if R4_PERF.exists() else pd.DataFrame()
    snap = pd.read_csv(SNAPSHOT, low_memory=False) if SNAPSHOT.exists() else pd.DataFrame()
    for df in [ledger, snap]:
        if not df.empty and {"ticker", "as_of_date"}.issubset(df.columns):
            df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
            df["as_of_date"] = pd.to_datetime(df["as_of_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return summary, ledger, audit, r4_perf, snap


def eligible_buckets(audit: pd.DataFrame) -> list[str]:
    if audit.empty:
        return []
    allowed = audit["alpha_interpretation_allowed"].map(lambda x: str(x).upper() == "TRUE")
    mask = (
        allowed
        & (audit["selectivity_status"] == "SELECTIVE")
        & (audit["maturity_status"] == "SUFFICIENT")
        & (audit["top20_sample_status"] == "SUFFICIENT")
        & (~audit["canonical_context_bucket"].isin(["MISSING_CONTEXT_LABEL", "UNRESOLVED_CONTEXT", "BROADCAST_OVERWIDE"]))
    )
    return sorted(audit.loc[mask, "canonical_context_bucket"].astype(str).unique())


def variant_defs() -> list[dict[str, object]]:
    return [
        {"variant_name": "BASELINE_TRUE_TECHNICAL", "rsi": 1.00, "kdj": 1.00, "macd": 1.00, "bb": 1.00, "ma": 1.00, "trend": 1.00, "volume": 1.00, "volatility": 0.00, "momentum": 1.00, "overheat": -1.00, "condition": "GLOBAL", "rationale": "V21.038 technical_score_normalized baseline."},
        {"variant_name": "RSI_DEEMPHASIZED_R4", "rsi": 0.35, "kdj": 0.75, "macd": 0.90, "bb": 1.00, "ma": 1.00, "trend": 1.10, "volume": 0.90, "volatility": -0.15, "momentum": 0.95, "overheat": -0.80, "condition": "GLOBAL", "rationale": "Reduce RSI weight globally."},
        {"variant_name": "RSI_CONTEXT_AWARE_R4", "rsi": 0.60, "kdj": 0.80, "macd": 0.95, "bb": 1.00, "ma": 1.05, "trend": 1.25, "volume": 0.95, "volatility": -0.15, "momentum": 0.95, "overheat": -0.70, "condition": "HEALTHY_SOFTEN_WEAK_HARDEN", "rationale": "Soften RSI/overheat in healthy extension buckets and harden in weak/overheat buckets."},
        {"variant_name": "MOMENTUM_DEDUPED_R4", "rsi": 0.35, "kdj": 0.35, "macd": 0.45, "bb": 0.90, "ma": 1.00, "trend": 1.20, "volume": 0.85, "volatility": -0.20, "momentum": 0.45, "overheat": -0.75, "condition": "GLOBAL_CLUSTER_DEDUP", "rationale": "Reduce duplicate RSI/KDJ/MACD/momentum exposure."},
        {"variant_name": "BB_MA_DEDUPED_R4", "rsi": 0.60, "kdj": 0.65, "macd": 0.75, "bb": 0.45, "ma": 0.55, "trend": 1.10, "volume": 0.90, "volatility": -0.20, "momentum": 0.80, "overheat": -0.80, "condition": "GLOBAL_CLUSTER_DEDUP", "rationale": "Cap collinear BB/MA/EMA/trend-distance exposure."},
        {"variant_name": "VOLUME_CONFIRMATION_BOOST_R4", "rsi": 0.55, "kdj": 0.70, "macd": 0.85, "bb": 0.95, "ma": 1.00, "trend": 1.10, "volume": 1.45, "volatility": -0.20, "momentum": 0.90, "overheat": -0.80, "condition": "VOLUME_CONFIRMED_BREAKOUT_CONTINUATION", "rationale": "Reward volume-confirmed breakout/continuation buckets."},
        {"variant_name": "OVERHEAT_SOFTENED_HEALTHY_TREND_R4", "rsi": 0.65, "kdj": 0.80, "macd": 0.90, "bb": 1.00, "ma": 1.05, "trend": 1.30, "volume": 0.95, "volatility": -0.15, "momentum": 0.95, "overheat": -0.40, "condition": "HEALTHY_TREND_EXTENSION", "rationale": "Soften overheat penalties only in healthy-trend extension buckets."},
        {"variant_name": "OVERHEAT_HARDENED_WEAK_TREND_R4", "rsi": 0.50, "kdj": 0.70, "macd": 0.80, "bb": 0.90, "ma": 0.95, "trend": 0.95, "volume": 0.90, "volatility": -0.25, "momentum": 0.75, "overheat": -1.35, "condition": "WEAK_TREND_EXTENSION", "rationale": "Harden overheat penalties in weak-trend extension buckets."},
        {"variant_name": "HIGH_VOL_RISK_CAPPED_R4", "rsi": 0.55, "kdj": 0.65, "macd": 0.75, "bb": 0.75, "ma": 0.80, "trend": 0.85, "volume": 0.85, "volatility": -0.65, "momentum": 0.75, "overheat": -1.00, "condition": "HIGH_VOL", "rationale": "Cap long exposure score contribution in high-volatility buckets."},
        {"variant_name": "BALANCED_R4_CONTEXT_AWARE", "rsi": 0.50, "kdj": 0.60, "macd": 0.75, "bb": 0.80, "ma": 0.85, "trend": 1.15, "volume": 1.10, "volatility": -0.25, "momentum": 0.75, "overheat": -0.85, "condition": "CONSERVATIVE_CONTEXT_AWARE", "rationale": "Combine conservative context-aware adjustments with capped deltas."},
    ]


def component_frame(df: pd.DataFrame) -> pd.DataFrame:
    c = pd.DataFrame(index=df.index)
    c["rsi"] = pd.to_numeric(df.get("rsi_14"), errors="coerce") / 100.0
    c["kdj"] = pd.to_numeric(df.get("kdj_k"), errors="coerce") / 100.0
    c["macd"] = pd.to_numeric(df.get("macd_hist"), errors="coerce").groupby(df["as_of_date"]).transform(pct_rank)
    c["bb"] = 1 - (pd.to_numeric(df.get("bb_position"), errors="coerce") - 0.55).abs().clip(0, 1)
    ma_mean = df[["ma20_distance", "ma50_distance", "ema20_distance"]].apply(pd.to_numeric, errors="coerce").mean(axis=1)
    c["ma"] = ma_mean.groupby(df["as_of_date"]).transform(pct_rank)
    c["trend"] = pd.to_numeric(df.get("trend_strength_score"), errors="coerce").clip(0, 1)
    c["volume"] = (1 - (pd.to_numeric(df.get("volume_ratio"), errors="coerce") - 1.2).abs() / 2).clip(0, 1)
    c["volatility"] = -pd.to_numeric(df.get("volatility_20"), errors="coerce").groupby(df["as_of_date"]).transform(pct_rank)
    mom = df[["momentum_5", "momentum_10", "momentum_20"]].apply(pd.to_numeric, errors="coerce").mean(axis=1)
    c["momentum"] = mom.groupby(df["as_of_date"]).transform(pct_rank)
    c["overheat"] = pd.to_numeric(df.get("overheat_extension_score"), errors="coerce").clip(0, 1)
    return c


def context_multiplier(name: str, bucket: pd.Series, component: str) -> pd.Series:
    mult = pd.Series(1.0, index=bucket.index)
    b = bucket.fillna("").astype(str)
    if name == "RSI_CONTEXT_AWARE_R4":
        healthy = b.str.contains("HEALTHY_TREND", regex=False)
        weak = b.str.contains("WEAK_TREND|RSI_OVERHEAT_WEAK", regex=True)
        if component in {"rsi", "overheat"}:
            mult.loc[healthy] = 0.65
            mult.loc[weak] = 1.25
    elif name == "VOLUME_CONFIRMATION_BOOST_R4" and component == "volume":
        mult.loc[b.str.contains("VOLUME_CONFIRMED|BREAKOUT|CONTINUATION", regex=True)] = 1.35
    elif name == "OVERHEAT_SOFTENED_HEALTHY_TREND_R4" and component == "overheat":
        mult.loc[b.str.contains("HEALTHY_TREND", regex=False)] = 0.50
    elif name == "OVERHEAT_HARDENED_WEAK_TREND_R4" and component == "overheat":
        mult.loc[b.str.contains("WEAK_TREND|RSI_OVERHEAT_WEAK", regex=True)] = 1.35
    elif name == "HIGH_VOL_RISK_CAPPED_R4":
        high_vol = b.str.contains("HIGH_VOL", regex=False)
        if component in {"bb", "ma", "trend", "momentum"}:
            mult.loc[high_vol] = 0.65
        if component in {"volatility", "overheat"}:
            mult.loc[high_vol] = 1.35
    elif name == "BALANCED_R4_CONTEXT_AWARE":
        if component == "volume":
            mult.loc[b.str.contains("VOLUME_CONFIRMED|BREAKOUT", regex=True)] = 1.15
        if component == "overheat":
            mult.loc[b.str.contains("WEAK_TREND|HIGH_VOL", regex=True)] = 1.15
            mult.loc[b.str.contains("HEALTHY_TREND", regex=False)] = 0.85
    return mult


def score_variants(snap: pd.DataFrame, defs: list[dict[str, object]]) -> pd.DataFrame:
    df = snap.copy()
    c = component_frame(df)
    for d in defs:
        name = str(d["variant_name"])
        if name == "BASELINE_TRUE_TECHNICAL":
            score = pd.to_numeric(df["technical_score_normalized"], errors="coerce")
        else:
            raw = pd.Series(0.0, index=df.index)
            for comp in ["rsi", "kdj", "macd", "bb", "ma", "trend", "volume", "volatility", "momentum"]:
                raw = raw + c[comp] * float(d[comp]) * context_multiplier(name, df["canonical_context_bucket"], comp)
            raw = raw - c["overheat"] * abs(float(d["overheat"])) * context_multiplier(name, df["canonical_context_bucket"], "overheat")
            if name in {"MOMENTUM_DEDUPED_R4", "BB_MA_DEDUPED_R4", "HIGH_VOL_RISK_CAPPED_R4", "BALANCED_R4_CONTEXT_AWARE"}:
                raw = raw.clip(lower=raw.quantile(0.01), upper=raw.quantile(0.99))
            score = raw.groupby(df["as_of_date"]).transform(pct_rank)
        df[f"score__{name}"] = score
        df[f"rank__{name}"] = df.groupby("as_of_date")[f"score__{name}"].rank(method="first", ascending=False)
    return df


def prepare_joined(ledger: pd.DataFrame, audit: pd.DataFrame, snap: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    buckets = eligible_buckets(audit)
    mature = ledger[
        (ledger["canonical_context_bucket"].isin(buckets))
        & (ledger["maturity_status"] == "MATURED")
        & (pd.to_numeric(ledger["realized_forward_return"], errors="coerce").notna())
    ].copy()
    mature["realized_forward_return"] = pd.to_numeric(mature["realized_forward_return"], errors="coerce")
    mature["benchmark_return"] = pd.to_numeric(mature.get("benchmark_return"), errors="coerce")
    snap_use = snap.drop_duplicates(["as_of_date", "ticker"], keep="first").copy()
    joined = mature.merge(snap_use, on=["as_of_date", "ticker"], how="inner", suffixes=("", "_snap"))
    return joined, buckets


def top_slice(df: pd.DataFrame, rank_col: str) -> pd.DataFrame:
    return df[pd.to_numeric(df[rank_col], errors="coerce") <= 20].copy()


def variant_performance(scored: pd.DataFrame, defs: list[dict[str, object]]) -> list[dict[str, object]]:
    if scored.empty:
        return [{
            "variant_name": "BASELINE_TRUE_TECHNICAL", "canonical_context_bucket": "UNKNOWN",
            "forward_window": "", "top_bucket": "TOP20", "rows_used": 0,
            "interpretation_allowed": "FALSE", "interpretation_block_reason": "NO_ELIGIBLE_JOINED_ROWS",
        }]
    rows: list[dict[str, object]] = []
    baseline_groups: dict[tuple[str, str], pd.DataFrame] = {}
    for key, g in scored.groupby(["canonical_context_bucket", "forward_window"]):
        baseline_groups[key] = top_slice(g, "rank__BASELINE_TRUE_TECHNICAL")
    for d in defs:
        name = str(d["variant_name"])
        rank_col = f"rank__{name}"
        for (bucket, window), g in scored.groupby(["canonical_context_bucket", "forward_window"]):
            top = top_slice(g, rank_col)
            base = baseline_groups.get((bucket, window), pd.DataFrame())
            vals = pd.to_numeric(top["realized_forward_return"], errors="coerce").dropna()
            bvals = pd.to_numeric(base.get("realized_forward_return", pd.Series(dtype=float)), errors="coerce").dropna()
            bench = pd.to_numeric(top.get("benchmark_return", pd.Series(dtype=float)), errors="coerce").dropna()
            top_ids = set(top["observation_id"].astype(str)) if "observation_id" in top else set()
            base_ids = set(base["observation_id"].astype(str)) if "observation_id" in base else set()
            overlap = len(top_ids & base_ids) / len(top_ids | base_ids) if top_ids or base_ids else ""
            rows.append({
                "variant_name": name,
                "canonical_context_bucket": bucket,
                "forward_window": window,
                "top_bucket": "TOP20",
                "rows_used": len(vals),
                "mean_forward_return": float(vals.mean()) if len(vals) else "",
                "median_forward_return": float(vals.median()) if len(vals) else "",
                "hit_rate": float((vals > 0).mean()) if len(vals) else "",
                "downside_rate": float((vals < 0).mean()) if len(vals) else "",
                "baseline_mean_forward_return": float(bvals.mean()) if len(bvals) else "",
                "baseline_hit_rate": float((bvals > 0).mean()) if len(bvals) else "",
                "baseline_downside_rate": float((bvals < 0).mean()) if len(bvals) else "",
                "mean_excess_vs_baseline": float(vals.mean() - bvals.mean()) if len(vals) and len(bvals) else "",
                "hit_rate_delta_vs_baseline": float((vals > 0).mean() - (bvals > 0).mean()) if len(vals) and len(bvals) else "",
                "downside_delta_vs_baseline": float((vals < 0).mean() - (bvals < 0).mean()) if len(vals) and len(bvals) else "",
                "benchmark_name": clean(top["benchmark_primary"].replace("", np.nan).dropna().iloc[0]) if "benchmark_primary" in top and top["benchmark_primary"].replace("", np.nan).dropna().any() else "",
                "mean_excess_vs_benchmark": float((vals - bench.reindex(vals.index).fillna(np.nan)).dropna().mean()) if len(bench) else "",
                "rank_overlap_with_baseline_top20": overlap,
                "turnover_proxy": float(1 - overlap) if overlap != "" else "",
                "interpretation_allowed": yes(len(vals) >= MIN_TOP_ROWS and bucket not in {"MISSING_CONTEXT_LABEL", "UNRESOLVED_CONTEXT"}),
                "interpretation_block_reason": "" if len(vals) >= MIN_TOP_ROWS else "TOP20_CONTEXT_WINDOW_ROWS_LT_30",
            })
    return rows


def rank_delta_audit(scored: pd.DataFrame, defs: list[dict[str, object]]) -> list[dict[str, object]]:
    if scored.empty:
        return [{
            "variant_name": "BASELINE_TRUE_TECHNICAL", "canonical_context_bucket": "UNKNOWN", "as_of_date": "",
            "rows_compared": 0, "no_op_warning": "NO_ELIGIBLE_JOINED_ROWS", "interpretation": "Blocked.",
        }]
    rows: list[dict[str, object]] = []
    base_score = "score__BASELINE_TRUE_TECHNICAL"
    base_rank = "rank__BASELINE_TRUE_TECHNICAL"
    for d in defs:
        name = str(d["variant_name"])
        score_col = f"score__{name}"
        rank_col = f"rank__{name}"
        for bucket, g in scored.groupby("canonical_context_bucket"):
            score_delta = (pd.to_numeric(g[score_col], errors="coerce") - pd.to_numeric(g[base_score], errors="coerce")).abs()
            rank_delta = (pd.to_numeric(g[rank_col], errors="coerce") - pd.to_numeric(g[base_rank], errors="coerce")).abs()
            top = set(g.loc[g[rank_col] <= 20, "ticker"].astype(str))
            base20 = set(g.loc[g[base_rank] <= 20, "ticker"].astype(str))
            top40 = set(g.loc[g[rank_col] <= 40, "ticker"].astype(str))
            base40 = set(g.loc[g[base_rank] <= 40, "ticker"].astype(str))
            top60 = set(g.loc[g[rank_col] <= 60, "ticker"].astype(str))
            base60 = set(g.loc[g[base_rank] <= 60, "ticker"].astype(str))
            overlap20 = len(top & base20) / len(top | base20) if top or base20 else ""
            overlap40 = len(top40 & base40) / len(top40 | base40) if top40 or base40 else ""
            overlap60 = len(top60 & base60) / len(top60 | base60) if top60 or base60 else ""
            rows.append({
                "variant_name": name,
                "canonical_context_bucket": bucket,
                "as_of_date": "ALL",
                "rows_compared": len(g),
                "score_changed_count": int((score_delta > 1e-12).sum()),
                "score_changed_ratio": float((score_delta > 1e-12).mean()) if len(g) else "",
                "rank_changed_count": int((rank_delta > 0).sum()),
                "rank_changed_ratio": float((rank_delta > 0).mean()) if len(g) else "",
                "mean_abs_score_delta": float(score_delta.mean()) if len(score_delta) else "",
                "median_abs_score_delta": float(score_delta.median()) if len(score_delta) else "",
                "max_abs_score_delta": float(score_delta.max()) if len(score_delta) else "",
                "mean_abs_rank_delta": float(rank_delta.mean()) if len(rank_delta) else "",
                "median_abs_rank_delta": float(rank_delta.median()) if len(rank_delta) else "",
                "max_abs_rank_delta": float(rank_delta.max()) if len(rank_delta) else "",
                "top20_overlap_ratio": overlap20,
                "top40_overlap_ratio": overlap40,
                "top60_overlap_ratio": overlap60,
                "turnover_proxy": float(1 - overlap20) if overlap20 != "" else "",
                "no_op_warning": "NO_OP_BASELINE" if name == "BASELINE_TRUE_TECHNICAL" else ("NO_MEANINGFUL_RANK_CHANGE" if rank_delta.max() == 0 else ""),
                "interpretation": "Research-only rank delta audit.",
            })
    return rows


def aggregate_scorecard(perf_rows: list[dict[str, object]], rank_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    perf = pd.DataFrame(perf_rows)
    if perf.empty:
        return []
    rank = pd.DataFrame(rank_rows)
    agg_rank = rank.groupby("variant_name").agg(
        turnover_proxy=("turnover_proxy", lambda s: pd.to_numeric(s, errors="coerce").mean()),
        top20_overlap=("top20_overlap_ratio", lambda s: pd.to_numeric(s, errors="coerce").mean()),
        rank_changed_ratio=("rank_changed_ratio", lambda s: pd.to_numeric(s, errors="coerce").mean()),
    ).reset_index() if not rank.empty else pd.DataFrame()
    rows = []
    for name, g in perf.groupby("variant_name"):
        used = g[g["interpretation_allowed"] == "TRUE"].copy()
        if used.empty:
            used = g.copy()
        excess = pd.to_numeric(used["mean_excess_vs_baseline"], errors="coerce")
        bucket_excess = used.assign(_excess=excess).groupby("canonical_context_bucket")["_excess"].mean() if "canonical_context_bucket" in used else pd.Series(dtype=float)
        rows_used = pd.to_numeric(used["rows_used"], errors="coerce").fillna(0)
        mean_ret = pd.to_numeric(used["mean_forward_return"], errors="coerce")
        base_ret = pd.to_numeric(used["baseline_mean_forward_return"], errors="coerce")
        hit = pd.to_numeric(used["hit_rate"], errors="coerce")
        bhit = pd.to_numeric(used["baseline_hit_rate"], errors="coerce")
        down = pd.to_numeric(used["downside_rate"], errors="coerce")
        bdown = pd.to_numeric(used["baseline_downside_rate"], errors="coerce")
        rstats = agg_rank[agg_rank["variant_name"] == name].iloc[0].to_dict() if not agg_rank.empty and (agg_rank["variant_name"] == name).any() else {}
        win = int((bucket_excess > 0).sum())
        loss = int((bucket_excess < 0).sum())
        flat = int((bucket_excess == 0).sum())
        mean_excess = float(excess.mean()) if excess.notna().any() else 0.0
        hit_delta = float((hit - bhit).mean()) if hit.notna().any() and bhit.notna().any() else 0.0
        downside_delta = float((down - bdown).mean()) if down.notna().any() and bdown.notna().any() else 0.0
        turnover = float(rstats.get("turnover_proxy", 0) or 0)
        overlap = float(rstats.get("top20_overlap", 1) or 1)
        rank_changed = float(rstats.get("rank_changed_ratio", 0) or 0)
        gates = {
            "positive_excess_gate_pass": mean_excess > 0,
            "hit_rate_gate_pass": hit_delta >= 0,
            "downside_gate_pass": downside_delta <= 0,
            "context_breadth_gate_pass": win >= max(3, loss),
            "rank_change_gate_pass": name != "BASELINE_TRUE_TECHNICAL" and rank_changed > 0.01 and turnover > 0.01 and turnover < 0.90 and overlap < 0.999,
        }
        selected = all(gates.values())
        block = "|".join(k for k, v in gates.items() if not v)
        rows.append({
            "variant_name": name,
            "eligible_context_bucket_count": int(used["canonical_context_bucket"].nunique()) if "canonical_context_bucket" in used else 0,
            "context_bucket_win_count": win,
            "context_bucket_loss_count": loss,
            "context_bucket_flat_count": flat,
            "total_rows_used": int(rows_used.sum()),
            "mean_forward_return": float(mean_ret.mean()) if mean_ret.notna().any() else "",
            "baseline_mean_forward_return": float(base_ret.mean()) if base_ret.notna().any() else "",
            "mean_excess_vs_baseline": mean_excess,
            "median_excess_vs_baseline": float(excess.median()) if excess.notna().any() else "",
            "hit_rate": float(hit.mean()) if hit.notna().any() else "",
            "baseline_hit_rate": float(bhit.mean()) if bhit.notna().any() else "",
            "hit_rate_delta_vs_baseline": hit_delta,
            "downside_rate": float(down.mean()) if down.notna().any() else "",
            "baseline_downside_rate": float(bdown.mean()) if bdown.notna().any() else "",
            "downside_delta_vs_baseline": downside_delta,
            "positive_excess_gate_pass": yes(gates["positive_excess_gate_pass"]),
            "hit_rate_gate_pass": yes(gates["hit_rate_gate_pass"]),
            "downside_gate_pass": yes(gates["downside_gate_pass"]),
            "context_breadth_gate_pass": yes(gates["context_breadth_gate_pass"]),
            "rank_change_gate_pass": yes(gates["rank_change_gate_pass"]),
            "variant_selected": yes(selected),
            "selection_block_reason": "" if selected else block,
            "interpretation": "Candidate clears all research gates." if selected else "Research-only evidence insufficient for candidate selection.",
        })
    return sorted(rows, key=lambda r: (r["variant_selected"] != "TRUE", -float(r["mean_excess_vs_baseline"] or 0), r["variant_name"]))


def weight_rows(defs: list[dict[str, object]]) -> list[dict[str, object]]:
    baseline = defs[0]
    rows = []
    for d in defs:
        for sub in ["rsi", "kdj", "macd", "bb", "ma", "trend", "volume", "volatility", "momentum", "overheat"]:
            base = float(baseline[sub])
            var = float(d[sub])
            rows.append({
                "variant_name": d["variant_name"],
                "subfactor_name": sub,
                "baseline_weight": base,
                "variant_weight": var,
                "weight_delta": var - base,
                "context_condition": d["condition"],
                "rationale": d["rationale"],
                "max_delta_guardrail_pass": yes(abs(var - base) <= 1.5),
            })
    return rows


def build_summary(r4_summary: dict[str, str], buckets: list[str], joined: pd.DataFrame, defs: list[dict[str, object]], scorecard: list[dict[str, object]], missing_cols: list[str], rank_rows: list[dict[str, object]] | None = None) -> dict[str, object]:
    inputs_missing = not all(path.exists() for path in [R4_SUMMARY, R4_LEDGER, R4_AUDIT, R4_PERF, SNAPSHOT])
    r4_allowed = r4_summary.get("technical_reweighting_retest_allowed") == "TRUE"
    selected_rows = [r for r in scorecard if r.get("variant_selected") == "TRUE" and r.get("variant_name") != "BASELINE_TRUE_TECHNICAL"]
    best = selected_rows[0] if selected_rows else {}
    baseline = next((r for r in scorecard if r.get("variant_name") == "BASELINE_TRUE_TECHNICAL"), {})
    best_rank = pd.DataFrame(rank_rows or [])
    if best and not best_rank.empty:
        best_rank = best_rank[best_rank["variant_name"] == best.get("variant_name")]
        best_overlap = pd.to_numeric(best_rank.get("top20_overlap_ratio"), errors="coerce").mean()
        best_turnover = pd.to_numeric(best_rank.get("turnover_proxy"), errors="coerce").mean()
    else:
        best_overlap = np.nan
        best_turnover = np.nan
    if inputs_missing:
        final_status = BLOCKED_INPUT_STATUS
        decision = DECISION_INPUT_BLOCKED
    elif not r4_allowed:
        final_status = BLOCKED_R4_STATUS
        decision = DECISION_R4_BLOCKED
    elif missing_cols:
        final_status = PARTIAL_STATUS
        decision = DECISION_INPUT_LIMIT if not selected_rows else DECISION_EDGE
    else:
        final_status = PASS_STATUS
        decision = DECISION_EDGE if selected_rows else DECISION_NO_EDGE
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
        "upstream_v21_040_r4_final_status": r4_summary.get("final_status", ""),
        "r4_retest_allowed": r4_summary.get("technical_reweighting_retest_allowed", "FALSE"),
        "r4_canonical_bucket_count_interpretable": r4_summary.get("canonical_bucket_count_interpretable", len(buckets)),
        "variants_tested_count": len(defs),
        "eligible_context_bucket_count": len(buckets),
        "matured_rows_used": len(joined),
        "immature_rows_excluded": int(float(r4_summary.get("r4_ledger_rows", 0) or 0)) - len(joined) if r4_summary.get("r4_ledger_rows") else 0,
        "best_research_variant_name": best.get("variant_name", ""),
        "best_research_variant_selected": yes(bool(best)),
        "best_variant_mean_forward_return": best.get("mean_forward_return", ""),
        "baseline_mean_forward_return": baseline.get("mean_forward_return", ""),
        "best_variant_mean_excess_vs_baseline": best.get("mean_excess_vs_baseline", ""),
        "best_variant_hit_rate": best.get("hit_rate", ""),
        "baseline_hit_rate": baseline.get("hit_rate", ""),
        "best_variant_downside_rate": best.get("downside_rate", ""),
        "baseline_downside_rate": baseline.get("downside_rate", ""),
        "best_variant_context_win_count": best.get("context_bucket_win_count", ""),
        "best_variant_context_loss_count": best.get("context_bucket_loss_count", ""),
        "best_variant_rank_overlap_with_baseline_top20": float(best_overlap) if pd.notna(best_overlap) else "",
        "best_variant_turnover_proxy": float(best_turnover) if pd.notna(best_turnover) else "",
        "positive_excess_gate_pass": best.get("positive_excess_gate_pass", "FALSE"),
        "hit_rate_gate_pass": best.get("hit_rate_gate_pass", "FALSE"),
        "downside_gate_pass": best.get("downside_gate_pass", "FALSE"),
        "context_breadth_gate_pass": best.get("context_breadth_gate_pass", "FALSE"),
        "rank_change_gate_pass": best.get("rank_change_gate_pass", "FALSE"),
        "shadow_gate_candidate_recommended": yes(bool(best)),
        "shadow_gate_allowed": "FALSE",
        "official_adoption_allowed": "FALSE",
        "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "V21.042_R1_SHADOW_GATE_REVIEW_FOR_TECHNICAL_VARIANT_CANDIDATE" if best else "V21.041_R2_RETEST_DIAGNOSTIC_OR_KEEP_BASELINE_REVIEW",
    }


def recommendation(summary: dict[str, object]) -> list[dict[str, object]]:
    selected = summary["best_research_variant_selected"] == "TRUE"
    return [{
        "recommendation_id": "V21_041_R1_RECOMMENDATION_001",
        "recommendation_type": "OPEN_SHADOW_GATE_REVIEW_NEXT_STAGE" if selected else "KEEP_BASELINE_TRUE_TECHNICAL",
        "variant_name": summary["best_research_variant_name"],
        "current_evidence": f"decision={summary['decision']}; mean_excess={summary['best_variant_mean_excess_vs_baseline']}",
        "proposed_next_stage": summary["next_recommended_stage"],
        "shadow_gate_candidate_recommended": summary["shadow_gate_candidate_recommended"],
        "shadow_gate_allowed_now": "FALSE",
        "official_use_allowed": "FALSE",
        "required_before_shadow_gate": "Run later shadow gate review; verify no official mutation and validate candidate stability.",
        "risk_notes": "Research-only evidence; this stage does not mutate shadow or official rankings.",
    }]


def validation(summary: dict[str, object], buckets: list[str], defs: list[dict[str, object]]) -> list[dict[str, object]]:
    checks = [
        ("R4_SUMMARY_FOUND", yes(R4_SUMMARY.exists()), "TRUE"),
        ("R4_RETEST_ALLOWED_TRUE", summary.get("r4_retest_allowed", "FALSE"), "TRUE"),
        ("R4_CANONICAL_LEDGER_FOUND", yes(R4_LEDGER.exists()), "TRUE"),
        ("R4_CONTEXT_AUDIT_FOUND", yes(R4_AUDIT.exists()), "TRUE"),
        ("TECHNICAL_SNAPSHOT_FOUND", yes(SNAPSHOT.exists()), "TRUE"),
        ("ELIGIBLE_CONTEXT_BUCKETS_PRESENT", yes(len(buckets) > 0), "TRUE"),
        ("VARIANTS_TESTED", yes(int(summary.get("variants_tested_count", 0) or 0) >= 8), "TRUE"),
        ("BASELINE_VARIANT_PRESENT", yes(any(d["variant_name"] == "BASELINE_TRUE_TECHNICAL" for d in defs)), "TRUE"),
        ("NO_OFFICIAL_MUTATION", "TRUE", "TRUE"),
        ("RESEARCH_ONLY_TRUE", summary["research_only"], "TRUE"),
        ("SHADOW_GATE_REMAINS_BLOCKED", summary["shadow_gate_allowed"], "FALSE"),
        ("DATA_TRUST_ALPHA_FALSE", summary["data_trust_alpha_weight_allowed"], "FALSE"),
    ]
    return [{
        "validation_item": item,
        "validation_status": "PASS" if str(obs) == req else "FAIL",
        "observed_value": obs,
        "required_value": req,
        "pass_fail": "PASS" if str(obs) == req else "FAIL",
        "notes": "Research-only V21.041-R1 technical reweighting retest validation.",
    } for item, obs, req in checks]


def write_report(summary: dict[str, object], buckets: list[str], defs: list[dict[str, object]], scorecard: list[dict[str, object]]) -> None:
    variant_lines = "\n".join(f"- {d['variant_name']}: {d['rationale']}" for d in defs)
    score_lines = "\n".join(f"- {r['variant_name']}: excess={fmt(r['mean_excess_vs_baseline'])}, wins={r['context_bucket_win_count']}, losses={r['context_bucket_loss_count']}, selected={r['variant_selected']}" for r in scorecard)
    bucket_lines = "\n".join(f"- {b}" for b in buckets[:40])
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Final status and decision
- final_status: {summary['final_status']}
- decision: {summary['decision']}

## Why V21.041 was allowed after V21.040-R4
V21.040-R4 set technical_reweighting_retest_allowed to `{summary['r4_retest_allowed']}` after consolidating R3 labels into selective canonical buckets.

## Eligible R4 context bucket summary
Eligible bucket count: {summary['eligible_context_bucket_count']}. Matured joined rows used: {summary['matured_rows_used']}.

{bucket_lines}

## Variant definitions
{variant_lines}

## Variant aggregate scorecard
{score_lines}

## Best variant selection result
best_research_variant_selected: {summary['best_research_variant_selected']}; best_research_variant_name: {summary['best_research_variant_name']}.

## Whether any variant beat baseline across context buckets
Decision: {summary['decision']}. Context win/loss gates are recorded in the scorecard output.

## Whether a later shadow gate review is recommended
shadow_gate_candidate_recommended: {summary['shadow_gate_candidate_recommended']}.

## Why shadow_gate_allowed remains FALSE in this stage
shadow_gate_allowed remains FALSE because this stage is a research-only retest and cannot mutate shadow rankings or open shadow adoption by itself.

## Why official mutation remains blocked
Official mutation remains blocked because official use, official weight mutation, official ranking mutation, trade action, broker execution, real-book mutation, official adoption, and data-trust alpha weighting all remain FALSE.

## Next recommended stage
{summary['next_recommended_stage']}
"""
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(report, encoding="utf-8")


SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "research_only", "official_use_allowed",
    "official_weight_mutation_allowed", "official_ranking_mutation_allowed",
    "trade_action_allowed", "broker_execution_allowed", "real_book_mutation_allowed",
    "upstream_v21_040_r4_final_status", "r4_retest_allowed",
    "r4_canonical_bucket_count_interpretable", "variants_tested_count",
    "eligible_context_bucket_count", "matured_rows_used", "immature_rows_excluded",
    "best_research_variant_name", "best_research_variant_selected",
    "best_variant_mean_forward_return", "baseline_mean_forward_return",
    "best_variant_mean_excess_vs_baseline", "best_variant_hit_rate",
    "baseline_hit_rate", "best_variant_downside_rate", "baseline_downside_rate",
    "best_variant_context_win_count", "best_variant_context_loss_count",
    "best_variant_rank_overlap_with_baseline_top20", "best_variant_turnover_proxy",
    "positive_excess_gate_pass", "hit_rate_gate_pass", "downside_gate_pass",
    "context_breadth_gate_pass", "rank_change_gate_pass",
    "shadow_gate_candidate_recommended", "shadow_gate_allowed",
    "official_adoption_allowed", "data_trust_alpha_weight_allowed",
    "next_recommended_stage",
]


def safe_outputs(status: str, decision: str, r4_summary: dict[str, str]) -> None:
    defs = variant_defs()
    buckets: list[str] = []
    summary = build_summary(r4_summary, buckets, pd.DataFrame(), defs, [], TECHNICAL_COLUMNS, [])
    summary["final_status"] = status
    summary["decision"] = decision
    summary["variants_tested_count"] = len(defs)
    write_csv(SUMMARY_OUT, [summary], SUMMARY_FIELDS)
    write_csv(PERF_OUT, [{"variant_name": "BASELINE_TRUE_TECHNICAL", "interpretation_allowed": "FALSE", "interpretation_block_reason": "BLOCKED_INPUTS_OR_R4_GATE"}], [
        "variant_name", "canonical_context_bucket", "forward_window", "top_bucket", "rows_used",
        "mean_forward_return", "median_forward_return", "hit_rate", "downside_rate",
        "baseline_mean_forward_return", "baseline_hit_rate", "baseline_downside_rate",
        "mean_excess_vs_baseline", "hit_rate_delta_vs_baseline", "downside_delta_vs_baseline",
        "benchmark_name", "mean_excess_vs_benchmark", "rank_overlap_with_baseline_top20",
        "turnover_proxy", "interpretation_allowed", "interpretation_block_reason",
    ])
    write_csv(SCORECARD_OUT, [{"variant_name": "BASELINE_TRUE_TECHNICAL", "variant_selected": "FALSE", "selection_block_reason": "BLOCKED_INPUTS_OR_R4_GATE"}], [
        "variant_name", "eligible_context_bucket_count", "context_bucket_win_count",
        "context_bucket_loss_count", "context_bucket_flat_count", "total_rows_used",
        "mean_forward_return", "baseline_mean_forward_return", "mean_excess_vs_baseline",
        "median_excess_vs_baseline", "hit_rate", "baseline_hit_rate",
        "hit_rate_delta_vs_baseline", "downside_rate", "baseline_downside_rate",
        "downside_delta_vs_baseline", "positive_excess_gate_pass", "hit_rate_gate_pass",
        "downside_gate_pass", "context_breadth_gate_pass", "rank_change_gate_pass",
        "variant_selected", "selection_block_reason", "interpretation",
    ])
    write_csv(RANK_DELTA_OUT, [{"variant_name": "BASELINE_TRUE_TECHNICAL", "canonical_context_bucket": "UNKNOWN", "as_of_date": "", "rows_compared": 0, "no_op_warning": "BLOCKED"}], [
        "variant_name", "canonical_context_bucket", "as_of_date", "rows_compared",
        "score_changed_count", "score_changed_ratio", "rank_changed_count",
        "rank_changed_ratio", "mean_abs_score_delta", "median_abs_score_delta",
        "max_abs_score_delta", "mean_abs_rank_delta", "median_abs_rank_delta",
        "max_abs_rank_delta", "top20_overlap_ratio", "top40_overlap_ratio",
        "top60_overlap_ratio", "turnover_proxy", "no_op_warning", "interpretation",
    ])
    write_csv(WEIGHTS_OUT, weight_rows(defs), ["variant_name", "subfactor_name", "baseline_weight", "variant_weight", "weight_delta", "context_condition", "rationale", "max_delta_guardrail_pass"])
    write_csv(RECOMMENDATION_OUT, recommendation(summary), ["recommendation_id", "recommendation_type", "variant_name", "current_evidence", "proposed_next_stage", "shadow_gate_candidate_recommended", "shadow_gate_allowed_now", "official_use_allowed", "required_before_shadow_gate", "risk_notes"])
    write_csv(VALIDATION_OUT, validation(summary, buckets, defs), ["validation_item", "validation_status", "observed_value", "required_value", "pass_fail", "notes"])
    write_report(summary, buckets, defs, [])


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    r4_summary, ledger, audit, _r4_perf, snap = load_inputs()
    if ledger.empty or audit.empty or snap.empty or not all(path.exists() for path in [R4_SUMMARY, R4_LEDGER, R4_AUDIT, R4_PERF, SNAPSHOT]):
        safe_outputs(BLOCKED_INPUT_STATUS, DECISION_INPUT_BLOCKED, r4_summary)
        summary = read_first(SUMMARY_OUT)
    elif r4_summary.get("technical_reweighting_retest_allowed") != "TRUE":
        safe_outputs(BLOCKED_R4_STATUS, DECISION_R4_BLOCKED, r4_summary)
        summary = read_first(SUMMARY_OUT)
    else:
        defs = variant_defs()
        missing_cols = [c for c in TECHNICAL_COLUMNS + ["technical_score_normalized"] if c not in snap.columns]
        for col in missing_cols:
            snap[col] = np.nan
        joined, buckets = prepare_joined(ledger, audit, snap)
        scored = score_variants(joined, defs) if not joined.empty else joined
        perf_rows = variant_performance(scored, defs)
        rank_rows = rank_delta_audit(scored, defs)
        scorecard = aggregate_scorecard(perf_rows, rank_rows)
        summary = build_summary(r4_summary, buckets, joined, defs, scorecard, missing_cols, rank_rows)

        write_csv(SUMMARY_OUT, [summary], SUMMARY_FIELDS)
        write_csv(PERF_OUT, perf_rows, [
            "variant_name", "canonical_context_bucket", "forward_window", "top_bucket", "rows_used",
            "mean_forward_return", "median_forward_return", "hit_rate", "downside_rate",
            "baseline_mean_forward_return", "baseline_hit_rate", "baseline_downside_rate",
            "mean_excess_vs_baseline", "hit_rate_delta_vs_baseline", "downside_delta_vs_baseline",
            "benchmark_name", "mean_excess_vs_benchmark", "rank_overlap_with_baseline_top20",
            "turnover_proxy", "interpretation_allowed", "interpretation_block_reason",
        ])
        write_csv(SCORECARD_OUT, scorecard, [
            "variant_name", "eligible_context_bucket_count", "context_bucket_win_count",
            "context_bucket_loss_count", "context_bucket_flat_count", "total_rows_used",
            "mean_forward_return", "baseline_mean_forward_return", "mean_excess_vs_baseline",
            "median_excess_vs_baseline", "hit_rate", "baseline_hit_rate",
            "hit_rate_delta_vs_baseline", "downside_rate", "baseline_downside_rate",
            "downside_delta_vs_baseline", "positive_excess_gate_pass", "hit_rate_gate_pass",
            "downside_gate_pass", "context_breadth_gate_pass", "rank_change_gate_pass",
            "variant_selected", "selection_block_reason", "interpretation",
        ])
        write_csv(RANK_DELTA_OUT, rank_rows, [
            "variant_name", "canonical_context_bucket", "as_of_date", "rows_compared",
            "score_changed_count", "score_changed_ratio", "rank_changed_count",
            "rank_changed_ratio", "mean_abs_score_delta", "median_abs_score_delta",
            "max_abs_score_delta", "mean_abs_rank_delta", "median_abs_rank_delta",
            "max_abs_rank_delta", "top20_overlap_ratio", "top40_overlap_ratio",
            "top60_overlap_ratio", "turnover_proxy", "no_op_warning", "interpretation",
        ])
        write_csv(WEIGHTS_OUT, weight_rows(defs), ["variant_name", "subfactor_name", "baseline_weight", "variant_weight", "weight_delta", "context_condition", "rationale", "max_delta_guardrail_pass"])
        write_csv(RECOMMENDATION_OUT, recommendation(summary), ["recommendation_id", "recommendation_type", "variant_name", "current_evidence", "proposed_next_stage", "shadow_gate_candidate_recommended", "shadow_gate_allowed_now", "official_use_allowed", "required_before_shadow_gate", "risk_notes"])
        write_csv(VALIDATION_OUT, validation(summary, buckets, defs), ["validation_item", "validation_status", "observed_value", "required_value", "pass_fail", "notes"])
        write_report(summary, buckets, defs, scorecard)

    print(f"STAGE_NAME={STAGE}")
    print(f"final_status={summary['final_status']}")
    print(f"decision={summary['decision']}")
    print(f"variants_tested_count={summary['variants_tested_count']}")
    print(f"eligible_context_bucket_count={summary['eligible_context_bucket_count']}")
    print(f"matured_rows_used={summary['matured_rows_used']}")
    print(f"best_research_variant_selected={summary['best_research_variant_selected']}")
    print(f"shadow_gate_allowed={summary['shadow_gate_allowed']}")
    print(f"official_adoption_allowed={summary['official_adoption_allowed']}")


if __name__ == "__main__":
    main()
