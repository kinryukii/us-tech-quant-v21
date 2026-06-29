#!/usr/bin/env python
"""V21.040-R4 context bucket consolidation and retest eligibility gate.

Research-only stage. Consolidates fragmented V21.040-R3 labels into canonical
context buckets, refreshes context selectivity/maturity/sample gates, and
decides whether technical reweighting retest may reopen.
"""

from __future__ import annotations

import csv
import math
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.040-R4_CONTEXT_BUCKET_CONSOLIDATION_AND_RETEST_ELIGIBILITY_GATE"
PASS_STATUS = "PASS_V21_040_R4_CONTEXT_BUCKET_CONSOLIDATION_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_040_R4_CONTEXT_BUCKET_CONSOLIDATION_INCOMPLETE"
BLOCKED_STATUS = "BLOCKED_V21_040_R4_INPUTS_MISSING"

DECISION_READY = "CONTEXT_BUCKET_CONSOLIDATION_READY_FOR_TECHNICAL_REWEIGHTING_RETEST"
DECISION_MATURITY = "CONTEXT_BUCKET_CONSOLIDATION_PARTIAL_MORE_MATURITY_REQUIRED"
DECISION_BLOCKED_QUALITY = "CONTEXT_BUCKET_CONSOLIDATION_BLOCKED_OVERBROADCAST_OR_OVERFRAGMENTATION"
DECISION_BLOCKED_INPUTS = "CONTEXT_BUCKET_CONSOLIDATION_BLOCKED_INPUTS_MISSING"

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

R3_LEDGER = OUT_DIR / "V21_040_R3_CANONICAL_FORWARD_RETURN_LEDGER_REPAIRED.csv"
R3_AUDIT = OUT_DIR / "V21_040_R3_CONTEXT_SELECTIVITY_AND_MATURITY_AUDIT.csv"
R3_PERF = OUT_DIR / "V21_040_R3_TECHNICAL_PERFORMANCE_BY_R3_CONTEXT_WINDOW.csv"
R3_SUMMARY = OUT_DIR / "V21_040_R3_CONTEXT_SELECTIVITY_REPAIR_SUMMARY.csv"
V38_SNAPSHOT = OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv"

SUMMARY_OUT = OUT_DIR / "V21_040_R4_CONTEXT_BUCKET_CONSOLIDATION_SUMMARY.csv"
LEDGER_OUT = OUT_DIR / "V21_040_R4_CANONICAL_CONTEXT_LEDGER.csv"
MAPPING_OUT = OUT_DIR / "V21_040_R4_CONTEXT_BUCKET_MAPPING.csv"
AUDIT_OUT = OUT_DIR / "V21_040_R4_CONTEXT_BUCKET_SELECTIVITY_AND_MATURITY_AUDIT.csv"
PERF_OUT = OUT_DIR / "V21_040_R4_TECHNICAL_PERFORMANCE_BY_CONTEXT_BUCKET_WINDOW.csv"
GATE_OUT = OUT_DIR / "V21_040_R4_RETEST_ELIGIBILITY_GATE.csv"
QUEUE_OUT = OUT_DIR / "V21_040_R4_CONTEXT_REPAIR_QUEUE.csv"
REPORT_OUT = READ_CENTER_DIR / "V21_040_R4_CONTEXT_BUCKET_CONSOLIDATION_AND_RETEST_ELIGIBILITY_GATE_REPORT.md"

WINDOWS = ["5D", "10D", "20D", "60D"]
MIN_MATURITY_RATIO = 0.60
MIN_MATURED_ROWS = 100
MIN_TOP20_ROWS = 30

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "research_only", "official_use_allowed",
    "official_weight_mutation_allowed", "official_ranking_mutation_allowed",
    "trade_action_allowed", "broker_execution_allowed", "real_book_mutation_allowed",
    "upstream_v21_040_r3_final_status", "r3_ledger_rows", "r4_ledger_rows",
    "r3_distinct_context_labels", "r4_distinct_context_buckets",
    "missing_context_count", "overbroadcast_context_count",
    "too_narrow_context_count_before", "too_narrow_context_count_after",
    "low_maturity_context_count_before", "low_maturity_context_count_after",
    "canonical_bucket_count_selective_sufficient", "canonical_bucket_count_interpretable",
    "technical_reweighting_retest_allowed", "shadow_gate_allowed",
    "official_adoption_allowed", "data_trust_alpha_weight_allowed",
    "next_recommended_stage",
]

LEDGER_FIELDS = [
    "observation_id", "ticker", "as_of_date", "forward_window", "maturity_date",
    "maturity_status", "realized_forward_return", "price_missing", "r3_context_label",
    "canonical_context_bucket", "bucket_rule_id", "bucket_source_components",
    "bucket_consolidation_status", "benchmark_primary", "benchmark_return",
    "row_quality_status",
]

AUDIT_FIELDS = [
    "canonical_context_bucket", "total_observations", "matured_observations",
    "pending_observations", "price_missing_observations", "distinct_ticker_count",
    "total_distinct_ticker_count", "ticker_coverage_ratio", "distinct_as_of_dates",
    "maturity_ratio", "matured_5d_count", "matured_10d_count", "matured_20d_count",
    "matured_60d_count", "mean_forward_return_5d", "mean_forward_return_10d",
    "mean_forward_return_20d", "mean_forward_return_60d", "hit_rate_5d",
    "hit_rate_10d", "hit_rate_20d", "hit_rate_60d", "selectivity_status",
    "maturity_status", "top20_sample_status", "alpha_interpretation_allowed",
    "failure_reason", "repair_recommendation",
]

PERF_FIELDS = [
    "canonical_context_bucket", "forward_window", "top_bucket", "rows_used",
    "mean_baseline_true_technical_forward_return",
    "median_baseline_true_technical_forward_return", "baseline_hit_rate",
    "baseline_downside_rate", "benchmark_name", "mean_excess_vs_benchmark",
    "performance_quality", "interpretation_allowed", "interpretation_block_reason",
]


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


def selectivity_status(ticker_ratio: object, ticker_count: int) -> str:
    if ticker_count == 0:
        return "EMPTY"
    ratio = pd.to_numeric(pd.Series([ticker_ratio]), errors="coerce").iloc[0]
    if pd.isna(ratio):
        return "UNKNOWN"
    if ratio < 0.02:
        return "TOO_NARROW"
    if ratio <= 0.80:
        return "SELECTIVE"
    return "BROADCAST_OVERWIDE"


def token_present(label: str, token: str) -> bool:
    return token in label.upper()


def parse_sector(label: str) -> str:
    for sector in ["SECTOR_SEMI", "SECTOR_SOFTWARE", "SECTOR_CLOUD", "SECTOR_FINANCIAL", "SECTOR_INDUSTRIAL", "SECTOR_OTHER"]:
        if sector in label:
            return sector
    return ""


def parse_rel(label: str) -> str:
    if "RELSTRONG_VS_SOXX" in label:
        return "RELSTRONG"
    if "RELWEAK_VS_SOXX" in label:
        return "RELWEAK"
    if "RELSTRONG_VS_QQQ" in label:
        return "RELSTRONG"
    if "RELWEAK_VS_QQQ" in label:
        return "RELWEAK"
    return ""


def parse_action(label: str) -> str:
    if "BREAKOUT" in label:
        return "BREAKOUT"
    if "PULLBACK" in label:
        return "PULLBACK"
    if "TREND_CONTINUATION" in label:
        return "CONTINUATION"
    return ""


def parse_volume(label: str) -> str:
    if "VOLUME_CONFIRMED" in label:
        return "VOLUME_CONFIRMED"
    if "VOLUME_WEAK" in label:
        return "VOLUME_WEAK"
    return ""


def parse_rsi(label: str) -> str:
    for bucket in ["RSI_GT_80", "RSI_70_80", "RSI_60_70", "RSI_50_60", "RSI_LT_50"]:
        if bucket in label:
            return bucket
    return ""


def base_family(label: str) -> str:
    u = label.upper()
    if u == "MISSING_CONTEXT_LABEL":
        return "MISSING_CONTEXT_LABEL"
    if "NO_TECH_CONTEXT" in u:
        sector = parse_sector(u) or "SECTOR_UNKNOWN"
        return f"NO_TECH_CONTEXT_SECTOR_ONLY__{sector}"
    if "QQQ_UPTREND" in u or "SPY_UPTREND" in u or "SECTOR_UPTREND" in u or "SEMICONDUCTOR_UPTREND" in u or "RISK_ON" in u or "REGIME" in u:
        return "ORIGINAL_LOW_MATURITY_CONTEXT"
    if "RSI_OVERHEAT_HEALTHY_TREND" in u:
        if "BB_MA_EXTENSION_HIGH" in u and "HIGH_VOLATILITY" in u:
            return "RSI_OVERHEAT_HEALTHY_TREND_EXTENSION_HIGH_VOL"
        if "BB_MA_EXTENSION_HIGH" in u:
            return "RSI_OVERHEAT_HEALTHY_TREND_EXTENSION_NORMAL_VOL"
        return "RSI_OVERHEAT_HEALTHY_TREND_NORMAL_EXTENSION"
    if "RSI_OVERHEAT_WEAK_TREND" in u:
        if "BB_MA_EXTENSION_HIGH" in u and "HIGH_VOLATILITY" in u:
            return "RSI_OVERHEAT_WEAK_TREND_EXTENSION_HIGH_VOL"
        if "BB_MA_EXTENSION_HIGH" in u:
            return "RSI_OVERHEAT_WEAK_TREND_EXTENSION_NORMAL_VOL"
        return "RSI_OVERHEAT_WEAK_TREND_NORMAL_EXTENSION"
    if "TECH_TREND_HEALTHY" in u:
        if "BB_MA_EXTENSION_HIGH" in u and "HIGH_VOLATILITY" in u:
            return "HEALTHY_TREND_EXTENSION_HIGH_VOL"
        if "BB_MA_EXTENSION_HIGH" in u:
            return "HEALTHY_TREND_EXTENSION_NORMAL_VOL"
        return "HEALTHY_TREND_NORMAL_EXTENSION"
    if "TECH_TREND_WEAK" in u:
        if "BB_MA_EXTENSION_HIGH" in u and "HIGH_VOLATILITY" in u:
            return "WEAK_TREND_EXTENSION_HIGH_VOL"
        if "BB_MA_EXTENSION_HIGH" in u:
            return "WEAK_TREND_EXTENSION_NORMAL_VOL"
        return "WEAK_TREND_NORMAL_EXTENSION"
    return "UNRESOLVED_CONTEXT"


def canonical_bucket(label: object) -> tuple[str, str, str, str]:
    raw = clean(label) or "MISSING_CONTEXT_LABEL"
    u = raw.upper()
    family = base_family(u)
    if family in {"MISSING_CONTEXT_LABEL", "UNRESOLVED_CONTEXT", "ORIGINAL_LOW_MATURITY_CONTEXT"}:
        return family, "CANONICAL_DIRECT_BLOCKED_CONTEXT", raw, "BLOCKED_CONTEXT"
    if family.startswith("NO_TECH_CONTEXT"):
        return family, "CANONICAL_NO_TECH_SECTOR_CONTEXT", raw, "CONSOLIDATED_NO_TECH_CONTEXT"

    sector = parse_sector(u)
    rel = parse_rel(u)
    action = parse_action(u)
    volume = parse_volume(u)
    rsi = parse_rsi(u)
    components = [family]
    if sector:
        components.append(sector)
    if rel:
        components.append(rel)
    if action:
        components.append(action)
    if volume == "VOLUME_CONFIRMED":
        components.append(volume)
    if rsi in {"RSI_70_80", "RSI_GT_80"}:
        components.append("RSI_ELEVATED")
    bucket = "__".join(components)
    return bucket, "CANONICAL_TECHNICAL_CONTEXT_BUCKET", "|".join([c for c in [family, sector, rel, action, volume, rsi] if c]), "CONSOLIDATED_CANONICAL_BUCKET"


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ledger = pd.read_csv(R3_LEDGER, low_memory=False) if R3_LEDGER.exists() else pd.DataFrame()
    audit = pd.read_csv(R3_AUDIT, low_memory=False) if R3_AUDIT.exists() else pd.DataFrame()
    r3_perf = pd.read_csv(R3_PERF, low_memory=False) if R3_PERF.exists() else pd.DataFrame()
    snap = pd.read_csv(V38_SNAPSHOT, low_memory=False) if V38_SNAPSHOT.exists() else pd.DataFrame()
    for df in [ledger, snap]:
        if not df.empty and {"ticker", "as_of_date"}.issubset(df.columns):
            df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
            df["as_of_date"] = pd.to_datetime(df["as_of_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return ledger, audit, r3_perf, snap


def build_ledger(r3: pd.DataFrame) -> pd.DataFrame:
    if r3.empty:
        return pd.DataFrame(columns=LEDGER_FIELDS)
    rows = []
    for label in r3["r3_repaired_context_label"].fillna("MISSING_CONTEXT_LABEL").astype(str):
        rows.append(canonical_bucket(label))
    out = pd.DataFrame({
        "observation_id": r3.get("observation_id", ""),
        "ticker": r3.get("ticker", ""),
        "as_of_date": r3.get("as_of_date", ""),
        "forward_window": r3.get("forward_window", ""),
        "maturity_date": r3.get("maturity_date", ""),
        "maturity_status": r3.get("maturity_status", ""),
        "realized_forward_return": r3.get("realized_forward_return", ""),
        "price_missing": r3.get("price_missing", ""),
        "r3_context_label": r3.get("r3_repaired_context_label", "MISSING_CONTEXT_LABEL"),
        "canonical_context_bucket": [r[0] for r in rows],
        "bucket_rule_id": [r[1] for r in rows],
        "bucket_source_components": [r[2] for r in rows],
        "bucket_consolidation_status": [r[3] for r in rows],
        "benchmark_primary": r3.get("benchmark_primary", ""),
        "benchmark_return": r3.get("benchmark_return", ""),
        "row_quality_status": r3.get("row_quality_status", "PASS_CANONICAL_RESEARCH_LEDGER"),
    })
    return out


def technical_performance(ledger: pd.DataFrame, snap: pd.DataFrame) -> list[dict[str, object]]:
    default = {
        "canonical_context_bucket": "UNKNOWN", "forward_window": "", "top_bucket": "TOP20",
        "rows_used": 0, "performance_quality": "BLOCKED_INPUTS_MISSING",
        "interpretation_allowed": "FALSE",
        "interpretation_block_reason": "No joinable matured ledger and V21.038 technical scores.",
    }
    if ledger.empty or snap.empty or "technical_score_normalized" not in snap.columns:
        return [default]
    matured = ledger[ledger["maturity_status"] == "MATURED"].copy()
    snap_use = snap[["as_of_date", "ticker", "technical_score_normalized"]].drop_duplicates(["as_of_date", "ticker"], keep="first")
    snap_use = snap_use.rename(columns={"technical_score_normalized": "baseline_technical_score_normalized"})
    joined = matured.merge(snap_use, on=["as_of_date", "ticker"], how="inner")
    if joined.empty:
        default["performance_quality"] = "TECHNICAL_SCORE_JOIN_EMPTY"
        return [default]
    joined["baseline_technical_score_normalized"] = pd.to_numeric(joined["baseline_technical_score_normalized"], errors="coerce")
    joined["baseline_rank"] = joined.groupby("as_of_date")["baseline_technical_score_normalized"].rank(ascending=False, method="first")
    rows: list[dict[str, object]] = []
    for (bucket, window), g in joined.groupby(["canonical_context_bucket", "forward_window"]):
        top = g[g["baseline_rank"] <= 20].copy()
        vals = pd.to_numeric(top["realized_forward_return"], errors="coerce").dropna()
        bench = pd.to_numeric(top["benchmark_return"], errors="coerce").dropna()
        blocks: list[str] = []
        if bucket in {"MISSING_CONTEXT_LABEL", "UNRESOLVED_CONTEXT"}:
            blocks.append(bucket)
        if len(vals) < MIN_TOP20_ROWS:
            blocks.append("TOP20_CONTEXT_WINDOW_ROWS_LT_30")
        rows.append({
            "canonical_context_bucket": bucket,
            "forward_window": window,
            "top_bucket": "TOP20",
            "rows_used": len(vals),
            "mean_baseline_true_technical_forward_return": float(vals.mean()) if len(vals) else "",
            "median_baseline_true_technical_forward_return": float(vals.median()) if len(vals) else "",
            "baseline_hit_rate": float((vals > 0).mean()) if len(vals) else "",
            "baseline_downside_rate": float((vals < 0).mean()) if len(vals) else "",
            "benchmark_name": clean(top["benchmark_primary"].replace("", np.nan).dropna().iloc[0]) if top["benchmark_primary"].replace("", np.nan).dropna().any() else "",
            "mean_excess_vs_benchmark": float((vals - bench.reindex(vals.index).fillna(np.nan)).dropna().mean()) if len(bench) else "",
            "performance_quality": "SUFFICIENT" if len(vals) >= MIN_TOP20_ROWS else "LOW_SAMPLE",
            "interpretation_allowed": yes(not blocks and len(vals) >= MIN_TOP20_ROWS),
            "interpretation_block_reason": "|".join(dict.fromkeys(blocks)),
        })
    return rows or [default]


def audit_buckets(ledger: pd.DataFrame, perf_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    if ledger.empty:
        return [{
            "canonical_context_bucket": "UNKNOWN", "total_observations": 0, "matured_observations": 0,
            "pending_observations": 0, "price_missing_observations": 0, "distinct_ticker_count": 0,
            "total_distinct_ticker_count": 0, "ticker_coverage_ratio": "", "distinct_as_of_dates": 0,
            "maturity_ratio": 0, "selectivity_status": "UNKNOWN", "maturity_status": "LOW_CONTEXT_MATURITY",
            "top20_sample_status": "LOW_SAMPLE", "alpha_interpretation_allowed": "FALSE",
            "failure_reason": "UNKNOWN", "repair_recommendation": "Blocked because R4 ledger is empty.",
        }]
    top20_by_bucket: dict[str, int] = {}
    for row in perf_rows:
        bucket = clean(row.get("canonical_context_bucket"))
        rows_used = int(float(row.get("rows_used") or 0))
        top20_by_bucket[bucket] = max(top20_by_bucket.get(bucket, 0), rows_used)
    total_tickers = int(ledger["ticker"].nunique())

    def mean_for(df: pd.DataFrame, window: str) -> object:
        vals = pd.to_numeric(df.loc[df["forward_window"] == window, "realized_forward_return"], errors="coerce").dropna()
        return float(vals.mean()) if len(vals) else ""

    def hit_for(df: pd.DataFrame, window: str) -> object:
        vals = pd.to_numeric(df.loc[df["forward_window"] == window, "realized_forward_return"], errors="coerce").dropna()
        return float((vals > 0).mean()) if len(vals) else ""

    rows: list[dict[str, object]] = []
    for bucket, g in ledger.groupby("canonical_context_bucket", dropna=False):
        bucket = clean(bucket) or "UNRESOLVED_CONTEXT"
        matured = g[g["maturity_status"] == "MATURED"]
        pending = g[g["maturity_status"] == "PENDING"]
        price_missing = g[g["maturity_status"] == "PRICE_MISSING"]
        ticker_count = int(g["ticker"].nunique())
        ticker_ratio = ticker_count / total_tickers if total_tickers else ""
        maturity_ratio = len(matured) / len(g) if len(g) else 0
        sel = selectivity_status(ticker_ratio, ticker_count)
        mat = "SUFFICIENT" if maturity_ratio >= MIN_MATURITY_RATIO and len(matured) >= MIN_MATURED_ROWS else "LOW_CONTEXT_MATURITY"
        top20 = "SUFFICIENT" if top20_by_bucket.get(bucket, 0) >= MIN_TOP20_ROWS else "LOW_SAMPLE"
        reasons: list[str] = []
        if bucket in {"MISSING_CONTEXT_LABEL", "UNRESOLVED_CONTEXT"}:
            reasons.append(bucket)
        if sel != "SELECTIVE":
            reasons.append(sel)
        if mat != "SUFFICIENT":
            reasons.append(mat)
        if top20 != "SUFFICIENT":
            reasons.append(top20)
        allowed = bucket not in {"MISSING_CONTEXT_LABEL", "UNRESOLVED_CONTEXT"} and sel == "SELECTIVE" and mat == "SUFFICIENT" and top20 == "SUFFICIENT"
        rows.append({
            "canonical_context_bucket": bucket,
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
            "maturity_status": mat,
            "top20_sample_status": top20,
            "alpha_interpretation_allowed": yes(allowed),
            "failure_reason": "|".join(reasons),
            "repair_recommendation": "Eligible for research-only technical retest." if allowed else "Keep blocked or review consolidation/maturity before retest.",
        })
    return sorted(rows, key=lambda r: (r["alpha_interpretation_allowed"], r["selectivity_status"], str(r["canonical_context_bucket"])))


def mapping_rows(ledger: pd.DataFrame, audit_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    if ledger.empty:
        return [{
            "r3_context_label": "UNKNOWN", "canonical_context_bucket": "UNKNOWN",
            "bucket_rule_id": "NO_LEDGER", "rows_affected": 0, "distinct_tickers": 0,
            "ticker_coverage_ratio": "", "maturity_ratio": 0, "source_components": "",
            "consolidation_status": "BLOCKED_INPUTS_MISSING",
            "interpretation_allowed_after_consolidation": "FALSE", "notes": "R3 ledger missing.",
        }]
    total_tickers = int(ledger["ticker"].nunique())
    allowed_by_bucket = {r["canonical_context_bucket"]: r["alpha_interpretation_allowed"] for r in audit_rows}
    rows: list[dict[str, object]] = []
    for (r3_label, bucket, rule, comps, status), g in ledger.groupby(["r3_context_label", "canonical_context_bucket", "bucket_rule_id", "bucket_source_components", "bucket_consolidation_status"], dropna=False):
        matured = g[g["maturity_status"] == "MATURED"]
        rows.append({
            "r3_context_label": clean(r3_label) or "MISSING_CONTEXT_LABEL",
            "canonical_context_bucket": clean(bucket) or "UNRESOLVED_CONTEXT",
            "bucket_rule_id": rule,
            "rows_affected": len(g),
            "distinct_tickers": int(g["ticker"].nunique()),
            "ticker_coverage_ratio": int(g["ticker"].nunique()) / total_tickers if total_tickers else "",
            "maturity_ratio": len(matured) / len(g) if len(g) else 0,
            "source_components": comps,
            "consolidation_status": status,
            "interpretation_allowed_after_consolidation": allowed_by_bucket.get(clean(bucket), "FALSE"),
            "notes": "Deterministic R4 canonical bucket consolidation.",
        })
    return rows


def build_summary(ledger: pd.DataFrame, r3_audit: pd.DataFrame, audit_rows: list[dict[str, object]]) -> dict[str, object]:
    r3_summary = read_first(R3_SUMMARY)
    inputs_missing = ledger.empty or not R3_LEDGER.exists() or not R3_AUDIT.exists() or not R3_PERF.exists() or not V38_SNAPSHOT.exists()
    over_count = sum(1 for r in audit_rows if r["selectivity_status"] == "BROADCAST_OVERWIDE")
    too_before = int((r3_audit["selectivity_status"] == "TOO_NARROW").sum()) if not r3_audit.empty and "selectivity_status" in r3_audit else 0
    too_after = sum(1 for r in audit_rows if r["selectivity_status"] == "TOO_NARROW")
    low_before = int((r3_audit["maturity_status"] == "LOW_CONTEXT_MATURITY").sum()) if not r3_audit.empty and "maturity_status" in r3_audit else 0
    low_after = sum(1 for r in audit_rows if r["maturity_status"] == "LOW_CONTEXT_MATURITY")
    selective_sufficient = sum(1 for r in audit_rows if r["selectivity_status"] == "SELECTIVE" and r["maturity_status"] == "SUFFICIENT" and r["top20_sample_status"] == "SUFFICIENT")
    interpretable = sum(1 for r in audit_rows if r["alpha_interpretation_allowed"] == "TRUE")
    missing_count = int(ledger["canonical_context_bucket"].isin(["MISSING_CONTEXT_LABEL", "UNRESOLVED_CONTEXT"]).sum()) if not ledger.empty else 0
    retest_allowed = (not inputs_missing) and over_count == 0 and interpretable > 0
    if inputs_missing:
        final_status = BLOCKED_STATUS
        decision = DECISION_BLOCKED_INPUTS
    elif over_count > 0 or too_after > max(too_before, 0) or interpretable == 0:
        final_status = PARTIAL_STATUS
        decision = DECISION_BLOCKED_QUALITY
    elif not retest_allowed:
        final_status = PARTIAL_STATUS
        decision = DECISION_MATURITY
    else:
        final_status = PASS_STATUS
        decision = DECISION_READY
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
        "upstream_v21_040_r3_final_status": r3_summary.get("final_status", ""),
        "r3_ledger_rows": r3_summary.get("r3_ledger_rows", len(ledger)),
        "r4_ledger_rows": len(ledger),
        "r3_distinct_context_labels": r3_summary.get("distinct_context_labels_after", ledger["r3_context_label"].nunique() if not ledger.empty else 0),
        "r4_distinct_context_buckets": int(ledger["canonical_context_bucket"].nunique()) if not ledger.empty else 0,
        "missing_context_count": missing_count,
        "overbroadcast_context_count": over_count,
        "too_narrow_context_count_before": too_before,
        "too_narrow_context_count_after": too_after,
        "low_maturity_context_count_before": low_before,
        "low_maturity_context_count_after": low_after,
        "canonical_bucket_count_selective_sufficient": selective_sufficient,
        "canonical_bucket_count_interpretable": interpretable,
        "technical_reweighting_retest_allowed": yes(retest_allowed),
        "shadow_gate_allowed": "FALSE",
        "official_adoption_allowed": "FALSE",
        "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "V21.041_R1_TECHNICAL_REWEIGHTING_RETEST_WITH_R4_CONTEXT_BUCKETS_RESEARCH_ONLY" if retest_allowed else "V21.040_R5_CONTEXT_BUCKET_MATURITY_REFRESH_OR_MANUAL_BUCKET_REVIEW",
    }


def gate_rows(summary: dict[str, object], audit_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    top20_ok = any(r["top20_sample_status"] == "SUFFICIENT" for r in audit_rows)
    checks = [
        ("R3_LEDGER_FOUND", yes(R3_LEDGER.exists()), "TRUE"),
        ("CONTEXT_BUCKETS_CREATED", yes(int(summary["r4_distinct_context_buckets"] or 0) > 0), "TRUE"),
        ("OVERBROADCAST_ELIMINATED", yes(int(summary["overbroadcast_context_count"] or 0) == 0), "TRUE"),
        ("MISSING_CONTEXT_CONTROLLED", yes(int(summary["missing_context_count"] or 0) <= 25), "TRUE"),
        ("TOO_NARROW_REDUCED", yes(int(summary["too_narrow_context_count_after"] or 0) <= int(summary["too_narrow_context_count_before"] or 0)), "TRUE"),
        ("LOW_MATURITY_REDUCED", yes(int(summary["low_maturity_context_count_after"] or 0) < int(summary["low_maturity_context_count_before"] or 0)), "TRUE"),
        ("SELECTIVE_SUFFICIENT_BUCKETS_PRESENT", yes(int(summary["canonical_bucket_count_selective_sufficient"] or 0) > 0), "TRUE"),
        ("TOP20_SAMPLE_SUFFICIENT", yes(top20_ok), "TRUE"),
        ("TECHNICAL_REWEIGHTING_RETEST_ALLOWED", summary["technical_reweighting_retest_allowed"], "TRUE" if summary["technical_reweighting_retest_allowed"] == "TRUE" else "FALSE"),
        ("SHADOW_GATE_REMAINS_BLOCKED", summary["shadow_gate_allowed"], "FALSE"),
        ("OFFICIAL_MUTATION_BLOCKED", "TRUE", "TRUE"),
        ("RESEARCH_ONLY_TRUE", summary["research_only"], "TRUE"),
        ("DATA_TRUST_ALPHA_FALSE", summary["data_trust_alpha_weight_allowed"], "FALSE"),
    ]
    return [{
        "gate_item": item,
        "gate_status": "PASS" if str(obs) == req else "FAIL",
        "observed_value": obs,
        "required_value": req,
        "pass_fail": "PASS" if str(obs) == req else "FAIL",
        "notes": "Research-only R4 retest eligibility gate.",
    } for item, obs, req in checks]


def repair_queue(summary: dict[str, object], audit_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    def add(target: str, issue: str, fix: str, priority: str, blocks_retest: bool, notes: str = "") -> None:
        rows.append({
            "repair_item_id": f"V21_040_R4_REPAIR_{len(rows) + 1:03d}",
            "repair_target": target,
            "current_issue": issue,
            "proposed_fix": fix,
            "priority": priority,
            "blocks_technical_retest": yes(blocks_retest),
            "blocks_shadow_gate": "TRUE",
            "official_use_allowed_after_repair": "FALSE",
            "next_validation_required": "R4_CONTEXT_BUCKET_GATE_REFRESH",
            "notes": notes,
        })

    if summary["overbroadcast_context_count"] not in {"0", 0}:
        add("canonical_context_bucket", "At least one canonical bucket is over-broadcast.", "Split only the over-broad bucket by sector/relative-strength/action while preserving maturity.", "HIGH", True)
    if summary["canonical_bucket_count_interpretable"] in {"0", 0}:
        add("canonical_context_bucket", "No canonical bucket is selective, mature, and top20-sample sufficient.", "Refresh maturity or review bucket granularity.", "HIGH", True)
    low = [r["canonical_context_bucket"] for r in audit_rows if r["maturity_status"] == "LOW_CONTEXT_MATURITY"]
    if low:
        add("context_maturity", "Some canonical buckets remain low maturity.", "Wait for additional maturity or consolidate only economically adjacent buckets.", "MEDIUM", False, ";".join(low[:10]))
    if not rows:
        add("technical_retest", "R4 retest eligibility gate passed.", "Proceed to research-only technical reweighting retest; keep shadow and official adoption blocked.", "LOW", False)
    return rows


def write_report(summary: dict[str, object], audit_rows: list[dict[str, object]], perf_rows: list[dict[str, object]]) -> None:
    context_lines = "\n".join(f"- {r['canonical_context_bucket']}: selectivity={r['selectivity_status']}, maturity={r['maturity_status']}, top20={r['top20_sample_status']}, allowed={r['alpha_interpretation_allowed']}" for r in audit_rows[:30])
    perf_lines = "\n".join(f"- {r['canonical_context_bucket']} {r['forward_window']}: rows={r['rows_used']}, quality={r['performance_quality']}, allowed={r['interpretation_allowed']}" for r in perf_rows[:30])
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Final status and decision
- final_status: {summary['final_status']}
- decision: {summary['decision']}

## V21.040-R3 blocker summary
R3 final_status was `{summary['upstream_v21_040_r3_final_status']}`. It reduced missing context sharply and eliminated overbroadcast, but it expanded context labels from {summary['r3_distinct_context_labels']} R3 labels into many low-maturity fragments.

## Why R3 overbroadcast was fixed but retest remained blocked
R3 split broad buckets enough to remove BROADCAST_OVERWIDE, but many resulting labels were too narrow, low maturity, or lacked top20 technical-score samples. R4 consolidates those fragments into canonical research buckets.

## Canonical bucket consolidation method
R4 deterministically parses R3 labels into trend health, BB/MA extension state, volatility state, sector group, relative strength, volume confirmation, RSI elevation, and breakout/pullback/continuation components. Missing or no-tech rows remain blocked research context buckets and are not used for retest interpretation.

## Context bucket selectivity and maturity after consolidation
{context_lines}

## Technical performance by canonical bucket/window
{perf_lines}

## Retest eligibility gate result
technical_reweighting_retest_allowed: {summary['technical_reweighting_retest_allowed']}; interpretable buckets: {summary['canonical_bucket_count_interpretable']}; overbroadcast buckets: {summary['overbroadcast_context_count']}.

## Whether technical reweighting retest is allowed
technical_reweighting_retest_allowed: {summary['technical_reweighting_retest_allowed']}.

## Why shadow gate remains blocked or not
shadow_gate_allowed: {summary['shadow_gate_allowed']}. This stage can only reopen the research retest; the shadow gate remains blocked until a later completed retest validates adoption criteria.

## Why official mutation remains blocked
Official mutation remains blocked because this stage is research-only and all official-use, official-weight, official-ranking, recommendation, trade, broker, real-book, official-adoption, and data-trust alpha permissions remain FALSE.

## Next recommended stage
{summary['next_recommended_stage']}
"""
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(report, encoding="utf-8")


def blocked_outputs() -> None:
    summary = {
        "stage": STAGE, "final_status": BLOCKED_STATUS, "decision": DECISION_BLOCKED_INPUTS,
        "research_only": "TRUE", "official_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE", "official_ranking_mutation_allowed": "FALSE",
        "trade_action_allowed": "FALSE", "broker_execution_allowed": "FALSE",
        "real_book_mutation_allowed": "FALSE", "upstream_v21_040_r3_final_status": read_first(R3_SUMMARY).get("final_status", ""),
        "r3_ledger_rows": 0, "r4_ledger_rows": 0, "r3_distinct_context_labels": 0,
        "r4_distinct_context_buckets": 0, "missing_context_count": 0, "overbroadcast_context_count": 0,
        "too_narrow_context_count_before": 0, "too_narrow_context_count_after": 0,
        "low_maturity_context_count_before": 0, "low_maturity_context_count_after": 0,
        "canonical_bucket_count_selective_sufficient": 0, "canonical_bucket_count_interpretable": 0,
        "technical_reweighting_retest_allowed": "FALSE", "shadow_gate_allowed": "FALSE",
        "official_adoption_allowed": "FALSE", "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "RESTORE_REQUIRED_R3_LEDGER_AUDIT_PERFORMANCE_AND_V21_038_SNAPSHOT",
    }
    audit = audit_buckets(pd.DataFrame(), [])
    perf = technical_performance(pd.DataFrame(), pd.DataFrame())
    write_csv(SUMMARY_OUT, [summary], SUMMARY_FIELDS)
    write_csv(LEDGER_OUT, [{"observation_id": "", "row_quality_status": "BLOCKED_INPUTS_MISSING"}], LEDGER_FIELDS)
    write_csv(MAPPING_OUT, mapping_rows(pd.DataFrame(), audit), ["r3_context_label", "canonical_context_bucket", "bucket_rule_id", "rows_affected", "distinct_tickers", "ticker_coverage_ratio", "maturity_ratio", "source_components", "consolidation_status", "interpretation_allowed_after_consolidation", "notes"])
    write_csv(AUDIT_OUT, audit, AUDIT_FIELDS)
    write_csv(PERF_OUT, perf, PERF_FIELDS)
    write_csv(GATE_OUT, gate_rows(summary, audit), ["gate_item", "gate_status", "observed_value", "required_value", "pass_fail", "notes"])
    write_csv(QUEUE_OUT, repair_queue(summary, audit), ["repair_item_id", "repair_target", "current_issue", "proposed_fix", "priority", "blocks_technical_retest", "blocks_shadow_gate", "official_use_allowed_after_repair", "next_validation_required", "notes"])
    write_report(summary, audit, perf)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    r3, r3_audit, _r3_perf, snap = load_inputs()
    if r3.empty or r3_audit.empty or snap.empty or not R3_PERF.exists():
        blocked_outputs()
        summary = read_first(SUMMARY_OUT)
    else:
        ledger = build_ledger(r3)
        perf_rows = technical_performance(ledger, snap)
        audit_rows = audit_buckets(ledger, perf_rows)
        mapping = mapping_rows(ledger, audit_rows)
        summary = build_summary(ledger, r3_audit, audit_rows)
        queue = repair_queue(summary, audit_rows)
        write_csv(SUMMARY_OUT, [summary], SUMMARY_FIELDS)
        write_csv(LEDGER_OUT, ledger.replace({np.nan: None}).to_dict("records"), LEDGER_FIELDS)
        write_csv(MAPPING_OUT, mapping, ["r3_context_label", "canonical_context_bucket", "bucket_rule_id", "rows_affected", "distinct_tickers", "ticker_coverage_ratio", "maturity_ratio", "source_components", "consolidation_status", "interpretation_allowed_after_consolidation", "notes"])
        write_csv(AUDIT_OUT, audit_rows, AUDIT_FIELDS)
        write_csv(PERF_OUT, perf_rows, PERF_FIELDS)
        write_csv(GATE_OUT, gate_rows(summary, audit_rows), ["gate_item", "gate_status", "observed_value", "required_value", "pass_fail", "notes"])
        write_csv(QUEUE_OUT, queue, ["repair_item_id", "repair_target", "current_issue", "proposed_fix", "priority", "blocks_technical_retest", "blocks_shadow_gate", "official_use_allowed_after_repair", "next_validation_required", "notes"])
        write_report(summary, audit_rows, perf_rows)

    print(f"STAGE_NAME={STAGE}")
    print(f"final_status={summary['final_status']}")
    print(f"decision={summary['decision']}")
    print(f"r4_ledger_rows={summary['r4_ledger_rows']}")
    print(f"r4_distinct_context_buckets={summary['r4_distinct_context_buckets']}")
    print(f"overbroadcast_context_count={summary['overbroadcast_context_count']}")
    print(f"canonical_bucket_count_interpretable={summary['canonical_bucket_count_interpretable']}")
    print(f"technical_reweighting_retest_allowed={summary['technical_reweighting_retest_allowed']}")
    print(f"shadow_gate_allowed={summary['shadow_gate_allowed']}")


if __name__ == "__main__":
    main()
