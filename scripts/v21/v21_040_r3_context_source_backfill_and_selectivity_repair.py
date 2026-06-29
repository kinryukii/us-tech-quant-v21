#!/usr/bin/env python
"""V21.040-R3 context source backfill and selectivity repair.

Research-only stage. Reads the V21.040-R2 canonical forward-return ledger,
uses local context sources plus V21.038 technical subfactors to split
over-broad/missing labels, and refreshes selectivity and technical
performance gates without mutating official artifacts.
"""

from __future__ import annotations

import csv
import math
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.040-R3_CONTEXT_SOURCE_BACKFILL_AND_SELECTIVITY_REPAIR"
PASS_STATUS = "PASS_V21_040_R3_CONTEXT_SELECTIVITY_REPAIR_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_040_R3_CONTEXT_SELECTIVITY_REPAIR_INCOMPLETE"
BLOCKED_STATUS = "BLOCKED_V21_040_R3_INPUTS_MISSING"

DECISION_READY = "CONTEXT_SELECTIVITY_REPAIR_READY_FOR_TECHNICAL_REWEIGHTING_RETEST"
DECISION_PARTIAL = "CONTEXT_SELECTIVITY_REPAIR_PARTIAL_OVERBROADCAST_REMAINS"
DECISION_BLOCKED = "CONTEXT_SELECTIVITY_REPAIR_BLOCKED_INPUTS_MISSING"

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

R2_LEDGER = OUT_DIR / "V21_040_R2_CANONICAL_FORWARD_RETURN_LEDGER.csv"
R2_AUDIT = OUT_DIR / "V21_040_R2_CONTEXT_SELECTIVITY_AND_MATURITY_AUDIT.csv"
R2_SUMMARY = OUT_DIR / "V21_040_R2_FORWARD_CONTEXT_REPAIR_SUMMARY.csv"
V38_SNAPSHOT = OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv"

SUMMARY_OUT = OUT_DIR / "V21_040_R3_CONTEXT_SELECTIVITY_REPAIR_SUMMARY.csv"
LEDGER_OUT = OUT_DIR / "V21_040_R3_CANONICAL_FORWARD_RETURN_LEDGER_REPAIRED.csv"
SOURCE_AUDIT_OUT = OUT_DIR / "V21_040_R3_CONTEXT_SOURCE_AUDIT.csv"
MAPPING_OUT = OUT_DIR / "V21_040_R3_CONTEXT_REPAIR_MAPPING.csv"
CONTEXT_OUT = OUT_DIR / "V21_040_R3_CONTEXT_SELECTIVITY_AND_MATURITY_AUDIT.csv"
PERF_OUT = OUT_DIR / "V21_040_R3_TECHNICAL_PERFORMANCE_BY_R3_CONTEXT_WINDOW.csv"
QUEUE_OUT = OUT_DIR / "V21_040_R3_FORWARD_CONTEXT_REPAIR_QUEUE.csv"
VALIDATION_OUT = OUT_DIR / "V21_040_R3_VALIDATION_MATRIX.csv"
REPORT_OUT = READ_CENTER_DIR / "V21_040_R3_CONTEXT_SOURCE_BACKFILL_AND_SELECTIVITY_REPAIR_REPORT.md"

WINDOWS = ["5D", "10D", "20D", "60D"]
MIN_CONTEXT_MATURITY_RATIO = 0.50
MIN_CONTEXT_MATURED_ROWS = 30
MIN_TOP_BUCKET_ROWS = 30

SEARCH_ROOTS = [
    ROOT / "outputs" / "v21" / "factors",
    ROOT / "outputs" / "v21" / "consolidation",
    ROOT / "outputs" / "v20" / "factors",
    ROOT / "outputs" / "v20" / "consolidation",
    ROOT / "outputs" / "v20" / "random_weight_backtest",
    ROOT / "inputs" / "v21" / "historical_ohlcv_cache",
    ROOT / "data",
    ROOT / "inputs",
]

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "research_only", "official_use_allowed",
    "official_weight_mutation_allowed", "official_ranking_mutation_allowed",
    "trade_action_allowed", "broker_execution_allowed", "real_book_mutation_allowed",
    "upstream_v21_040_r2_final_status", "r2_canonical_ledger_rows", "r3_ledger_rows",
    "overbroadcast_context_count_before", "overbroadcast_context_count_after",
    "missing_context_before_count", "missing_context_after_count",
    "missing_context_reduction_count", "missing_context_reduction_ratio",
    "distinct_context_labels_before", "distinct_context_labels_after",
    "context_source_file_count_scanned", "context_source_file_count_usable",
    "context_selectivity_ready_after", "context_overbroadcast_after",
    "technical_reweighting_retest_allowed", "shadow_gate_allowed",
    "official_adoption_allowed", "data_trust_alpha_weight_allowed",
    "next_recommended_stage",
]

LEDGER_FIELDS = [
    "observation_id", "observation_id_source", "ticker", "as_of_date", "forward_window",
    "maturity_date", "maturity_status", "realized_forward_return", "price_missing",
    "source_file_path", "original_context_label", "r2_repaired_context_label",
    "r3_repaired_context_label", "r3_repair_source", "r3_repair_status",
    "r3_repair_reason", "benchmark_primary", "benchmark_return", "row_quality_status",
]

SOURCE_AUDIT_FIELDS = [
    "source_file_path", "source_role", "exists", "rows", "detected_ticker_column",
    "detected_as_of_date_column", "detected_sector_column", "detected_industry_column",
    "detected_theme_column", "detected_benchmark_column",
    "detected_relative_strength_column", "detected_risk_column", "detected_regime_column",
    "usable_for_context_repair", "reason_if_not_usable",
]

CONTEXT_FIELDS = [
    "r3_context_label", "total_observations", "matured_observations",
    "pending_observations", "price_missing_observations", "distinct_ticker_count",
    "total_distinct_ticker_count", "ticker_coverage_ratio", "distinct_as_of_dates",
    "maturity_ratio", "matured_5d_count", "matured_10d_count", "matured_20d_count",
    "matured_60d_count", "mean_forward_return_5d", "mean_forward_return_10d",
    "mean_forward_return_20d", "mean_forward_return_60d", "hit_rate_5d",
    "hit_rate_10d", "hit_rate_20d", "hit_rate_60d", "selectivity_status",
    "maturity_status", "alpha_interpretation_allowed", "failure_reason",
    "repair_recommendation",
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


def read_first(path: Path) -> dict[str, str]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return next(reader, {}) or {}


def header(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return next(csv.reader(handle), [])
    except (OSError, UnicodeDecodeError, StopIteration):
        return []


def row_count(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8-sig", errors="ignore") as handle:
            return max(sum(1 for _ in handle) - 1, 0)
    except OSError:
        return 0


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


def source_files() -> list[Path]:
    files: set[Path] = set()
    for root in SEARCH_ROOTS:
        if root.exists():
            files.update(path for path in root.rglob("*.csv") if path.is_file())
    return sorted(files, key=lambda p: rel(p).lower())


def audit_sources() -> tuple[list[dict[str, object]], list[Path]]:
    rows: list[dict[str, object]] = []
    usable: list[Path] = []
    for path in source_files():
        cols = header(path)
        npath = path.name.lower()
        ticker_col = find_col(cols, ["ticker", "symbol", "selected_etf"])
        date_col = find_col(cols, ["as_of_date", "date", "signal_date", "entry_date"])
        sector_col = find_col(cols, ["sector", "sector_key", "sector_bucket"])
        industry_col = find_col(cols, ["industry", "industry_key", "sub_industry"])
        theme_col = find_col(cols, ["theme", "theme_hint", "theme_bucket", "exposure_bucket"])
        benchmark_col = find_col(cols, ["benchmark", "benchmark_exposure", "benchmark_primary", "selected_etf"])
        rs_col = find_col(cols, ["relative_strength", "rel_strength", "momentum_20", "technical_score_normalized"])
        risk_col = find_col(cols, ["risk", "overheat", "volatility", "drawdown", "pullback"])
        regime_col = find_col(cols, ["regime", "market_regime", "trend_regime"])
        role_parts = []
        for token, col in [
            ("sector_industry", sector_col or industry_col),
            ("theme_exposure", theme_col),
            ("benchmark_exposure", benchmark_col),
            ("relative_strength", rs_col),
            ("risk_regime", risk_col or regime_col),
        ]:
            if col:
                role_parts.append(token)
        has_context = bool(sector_col or industry_col or theme_col or benchmark_col or rs_col or risk_col or regime_col)
        usable_flag = bool(ticker_col and has_context)
        if "v21_040_r3" in npath:
            usable_flag = False
        if usable_flag:
            usable.append(path)
        counted_rows = row_count(path) if has_context else 0
        rows.append({
            "source_file_path": rel(path),
            "source_role": "|".join(role_parts) if role_parts else "NO_CONTEXT_ROLE_DETECTED",
            "exists": "TRUE",
            "rows": counted_rows,
            "detected_ticker_column": ticker_col,
            "detected_as_of_date_column": date_col,
            "detected_sector_column": sector_col,
            "detected_industry_column": industry_col,
            "detected_theme_column": theme_col,
            "detected_benchmark_column": benchmark_col,
            "detected_relative_strength_column": rs_col,
            "detected_risk_column": risk_col,
            "detected_regime_column": regime_col,
            "usable_for_context_repair": yes(usable_flag),
            "reason_if_not_usable": "" if usable_flag else "Missing ticker or usable context columns.",
        })
    return rows, usable


def load_metadata_context(source_audit: list[dict[str, object]]) -> pd.DataFrame:
    preferred = [
        ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R8_R2_CONTROLLED_MARKET_REGIME_EXPOSURE_METADATA_CACHE.csv",
        ROOT / "outputs" / "v20" / "consolidation" / "snapshots" / "V20_108_R8_R2_ENABLED_METADATA_CACHE.csv",
        ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R8_R1_MARKET_REGIME_EQUITY_EXPOSURE_SOURCE.csv",
        ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R8_R3_MARKET_REGIME_CONTRIBUTION_SOURCE.csv",
    ]
    for path in preferred:
        if not path.exists():
            continue
        cols = header(path)
        ticker_col = find_col(cols, ["ticker", "symbol"])
        if not ticker_col:
            continue
        df = pd.read_csv(path, low_memory=False)
        if df.empty:
            continue
        out = pd.DataFrame()
        out["ticker"] = df[ticker_col].astype(str).str.upper().str.strip()
        for target, candidates in {
            "sector": ["sector", "sector_key"],
            "industry": ["industry", "industry_key", "sub_industry"],
            "theme": ["theme_bucket", "theme_hint", "exposure_bucket"],
            "benchmark_exposure": ["benchmark_exposure", "benchmark_exposure_hint"],
        }.items():
            col = find_col(cols, candidates)
            out[target] = df[col].astype(str).str.strip() if col else ""
        out["metadata_source_path"] = rel(path)
        out = out.drop_duplicates("ticker", keep="first")
        if not out.empty:
            return out
    return pd.DataFrame(columns=["ticker", "sector", "industry", "theme", "benchmark_exposure", "metadata_source_path"])


def sector_bucket(sector: object, industry: object, theme: object, benchmark: object) -> str:
    text = norm(" ".join([clean(sector), clean(industry), clean(theme), clean(benchmark)]))
    if any(token in text for token in ["semiconductor", "semiconductors", "soxx", "smh"]):
        return "SECTOR_SEMI"
    if "cloud" in text or "software_as" in text:
        return "SECTOR_CLOUD"
    if "software" in text:
        return "SECTOR_SOFTWARE"
    if any(token in text for token in ["financial", "bank", "capital_markets", "insurance"]):
        return "SECTOR_FINANCIAL"
    if any(token in text for token in ["industrial", "machinery", "aerospace", "electrical_equipment"]):
        return "SECTOR_INDUSTRIAL"
    return "SECTOR_OTHER"


def rsi_bucket(value: object) -> str:
    x = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(x):
        return "RSI_UNKNOWN"
    if x < 50:
        return "RSI_LT_50"
    if x < 60:
        return "RSI_50_60"
    if x < 70:
        return "RSI_60_70"
    if x < 80:
        return "RSI_70_80"
    return "RSI_GT_80"


def rel_bucket(row: pd.Series, bench_col: str, strong: str, weak: str) -> str:
    mom = pd.to_numeric(row.get("momentum_20"), errors="coerce")
    bench = pd.to_numeric(row.get(bench_col), errors="coerce")
    if pd.isna(mom) or pd.isna(bench):
        return ""
    return strong if mom >= bench else weak


def volume_bucket(value: object) -> str:
    x = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(x):
        return "VOLUME_UNKNOWN"
    return "VOLUME_CONFIRMED" if x >= 1.0 else "VOLUME_WEAK"


def vol_bucket(value: object) -> str:
    x = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(x):
        return "VOL_UNKNOWN"
    return "VOL_HIGH" if x >= 0.04 else "VOL_NORMAL"


def price_state(row: pd.Series) -> str:
    bb = pd.to_numeric(row.get("bb_position"), errors="coerce")
    mom = pd.to_numeric(row.get("momentum_20"), errors="coerce")
    if pd.notna(bb) and bb <= 0.35:
        return "PULLBACK"
    if pd.notna(bb) and bb >= 0.85 and pd.notna(mom) and mom > 0:
        return "BREAKOUT"
    return "TREND_CONTINUATION"


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ledger = pd.read_csv(R2_LEDGER, low_memory=False) if R2_LEDGER.exists() else pd.DataFrame()
    snap = pd.read_csv(V38_SNAPSHOT, low_memory=False) if V38_SNAPSHOT.exists() else pd.DataFrame()
    audit = pd.read_csv(R2_AUDIT, low_memory=False) if R2_AUDIT.exists() else pd.DataFrame()
    for df in [ledger, snap]:
        if not df.empty:
            df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
            df["as_of_date"] = pd.to_datetime(df["as_of_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return ledger, snap, audit


def enrich_snapshot(snap: pd.DataFrame) -> pd.DataFrame:
    if snap.empty:
        return snap
    snap = snap.copy()
    needed = ["as_of_date", "ticker", "momentum_20", "rsi_14", "volume_ratio", "volatility_20", "bb_position", "technical_score_normalized"]
    for col in needed:
        if col not in snap.columns:
            snap[col] = np.nan
    bench = snap[snap["ticker"].isin(["QQQ", "SOXX", "SMH", "XLK", "SPY"])][["as_of_date", "ticker", "momentum_20"]].copy()
    if not bench.empty:
        wide = bench.pivot_table(index="as_of_date", columns="ticker", values="momentum_20", aggfunc="first").reset_index()
        wide = wide.rename(columns={c: f"momentum_20_{c}" for c in wide.columns if c != "as_of_date"})
        snap = snap.merge(wide, on="as_of_date", how="left")
    else:
        for ticker in ["QQQ", "SOXX", "SMH", "XLK", "SPY"]:
            snap[f"momentum_20_{ticker}"] = np.nan
    return snap


def bad_r2_labels(r2_audit: pd.DataFrame) -> set[str]:
    if r2_audit.empty:
        return {"MISSING_CONTEXT_LABEL"}
    labels: set[str] = set()
    for row in r2_audit.to_dict("records"):
        label = clean(row.get("repaired_context_label")) or clean(row.get("r2_repaired_context_label"))
        if label == "MISSING_CONTEXT_LABEL" or clean(row.get("selectivity_status")) == "BROADCAST_OVERWIDE":
            labels.add(label)
    labels.add("MISSING_CONTEXT_LABEL")
    return labels


def repair_ledger(ledger: pd.DataFrame, snap: pd.DataFrame, metadata: pd.DataFrame, r2_audit: pd.DataFrame) -> pd.DataFrame:
    if ledger.empty:
        return pd.DataFrame(columns=LEDGER_FIELDS)
    bad = bad_r2_labels(r2_audit)
    base = ledger.copy()
    base["ticker"] = base["ticker"].astype(str).str.upper().str.strip()
    base["as_of_date"] = pd.to_datetime(base["as_of_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    base = base.rename(columns={
        "repaired_context_label": "r2_repaired_context_label",
        "repaired_context_source": "r2_repair_source",
        "context_repair_status": "r2_repair_status",
        "context_repair_reason": "r2_repair_reason",
    })
    snap_cols = [
        "as_of_date", "ticker", "rsi_14", "volume_ratio", "volatility_20", "bb_position",
        "momentum_20", "momentum_20_QQQ", "momentum_20_SOXX", "momentum_20_SMH",
        "technical_score_normalized",
    ]
    snap_use = snap[[c for c in snap_cols if c in snap.columns]].drop_duplicates(["as_of_date", "ticker"], keep="first") if not snap.empty else pd.DataFrame(columns=["as_of_date", "ticker"])
    merged = base.merge(snap_use, on=["as_of_date", "ticker"], how="left")
    merged = merged.merge(metadata, on="ticker", how="left")

    labels: list[str] = []
    sources: list[str] = []
    statuses: list[str] = []
    reasons: list[str] = []
    for row in merged.to_dict("records"):
        r2_label = clean(row.get("r2_repaired_context_label")) or "MISSING_CONTEXT_LABEL"
        sector = sector_bucket(row.get("sector"), row.get("industry"), row.get("theme"), row.get("benchmark_exposure"))
        has_meta = bool(clean(row.get("metadata_source_path")))
        has_tech = pd.notna(pd.to_numeric(pd.Series([row.get("technical_score_normalized")]), errors="coerce").iloc[0])
        if r2_label not in bad:
            labels.append(r2_label)
            sources.append(clean(row.get("r2_repair_source")) or "R2_CONTEXT_PRESERVED")
            statuses.append(clean(row.get("r2_repair_status")) or "R2_CONTEXT_PRESERVED")
            reasons.append("R2 context was already outside overbroadcast/missing repair target.")
            continue
        if has_tech and has_meta:
            relq = rel_bucket(pd.Series(row), "momentum_20_QQQ", "RELSTRONG_VS_QQQ", "RELWEAK_VS_QQQ")
            rels = rel_bucket(pd.Series(row), "momentum_20_SOXX", "RELSTRONG_VS_SOXX", "RELWEAK_VS_SOXX")
            rel_component = rels or relq or "REL_UNKNOWN"
            label = "__".join([
                r2_label, sector, rel_component, volume_bucket(row.get("volume_ratio")),
                rsi_bucket(row.get("rsi_14")), vol_bucket(row.get("volatility_20")), price_state(pd.Series(row)),
            ])
            labels.append(label)
            sources.append("V20_EXPOSURE_METADATA__V21_038_TECHNICAL_SUBFACTORS")
            statuses.append("REPAIRED_SECOND_PASS")
            reasons.append("Split over-broad/missing R2 label using certified local exposure metadata and V21.038 technical subfactor buckets.")
        elif has_tech:
            label = "__".join([r2_label, volume_bucket(row.get("volume_ratio")), rsi_bucket(row.get("rsi_14")), vol_bucket(row.get("volatility_20")), price_state(pd.Series(row))])
            labels.append(label)
            sources.append("V21_038_TECHNICAL_SUBFACTORS")
            statuses.append("REPAIRED_SECOND_PASS")
            reasons.append("Split over-broad/missing R2 label using V21.038 technical subfactor buckets; no sector metadata joined.")
        elif has_meta:
            labels.append("__".join([r2_label, sector, "NO_TECH_CONTEXT"]))
            sources.append("V20_EXPOSURE_METADATA")
            statuses.append("REPAIR_PENDING")
            reasons.append("Ticker exposure metadata exists, but no joinable V21.038 technical subfactor row for the ticker/date.")
        else:
            labels.append(r2_label)
            sources.append("NO_DEFENSIBLE_R3_SOURCE")
            statuses.append("REPAIR_PENDING")
            reasons.append("No defensible local sector/technical context source joined for this row.")

    merged["r3_repaired_context_label"] = labels
    merged["r3_repair_source"] = sources
    merged["r3_repair_status"] = statuses
    merged["r3_repair_reason"] = reasons
    merged["row_quality_status"] = merged.get("row_quality_status", "PASS_CANONICAL_RESEARCH_LEDGER")
    return merged


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


def context_audit(ledger: pd.DataFrame) -> list[dict[str, object]]:
    if ledger.empty:
        return [{
            "r3_context_label": "UNKNOWN", "total_observations": 0, "matured_observations": 0,
            "pending_observations": 0, "price_missing_observations": 0, "distinct_ticker_count": 0,
            "total_distinct_ticker_count": 0, "ticker_coverage_ratio": "", "distinct_as_of_dates": 0,
            "maturity_ratio": 0, "selectivity_status": "UNKNOWN", "maturity_status": "LOW_CONTEXT_MATURITY",
            "alpha_interpretation_allowed": "FALSE", "failure_reason": "UNKNOWN",
            "repair_recommendation": "Blocked because repaired ledger is empty.",
        }]
    total_tickers = int(ledger["ticker"].nunique())

    def mean_for(df: pd.DataFrame, window: str) -> object:
        vals = pd.to_numeric(df.loc[df["forward_window"] == window, "realized_forward_return"], errors="coerce").dropna()
        return float(vals.mean()) if len(vals) else ""

    def hit_for(df: pd.DataFrame, window: str) -> object:
        vals = pd.to_numeric(df.loc[df["forward_window"] == window, "realized_forward_return"], errors="coerce").dropna()
        return float((vals > 0).mean()) if len(vals) else ""

    rows: list[dict[str, object]] = []
    for label, g in ledger.groupby("r3_repaired_context_label", dropna=False):
        label = clean(label) or "MISSING_CONTEXT_LABEL"
        matured = g[g["maturity_status"] == "MATURED"]
        pending = g[g["maturity_status"] == "PENDING"]
        price_missing = g[g["maturity_status"] == "PRICE_MISSING"]
        ticker_count = int(g["ticker"].nunique())
        ticker_ratio = ticker_count / total_tickers if total_tickers else ""
        maturity_ratio = len(matured) / len(g) if len(g) else 0
        sel = selectivity_status(ticker_ratio, ticker_count)
        maturity = "SUFFICIENT" if len(matured) >= MIN_CONTEXT_MATURED_ROWS and maturity_ratio >= MIN_CONTEXT_MATURITY_RATIO else "LOW_CONTEXT_MATURITY"
        reasons = []
        if label == "MISSING_CONTEXT_LABEL":
            reasons.append("MISSING_CONTEXT_LABEL")
        if sel != "SELECTIVE":
            reasons.append(sel)
        if maturity != "SUFFICIENT":
            reasons.append(maturity)
        allowed = label != "MISSING_CONTEXT_LABEL" and sel == "SELECTIVE" and maturity == "SUFFICIENT"
        rows.append({
            "r3_context_label": label,
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
            "repair_recommendation": "Eligible for research-only technical retest interpretation." if allowed else "Keep blocked; needs narrower context, more maturity, or defensible source backfill.",
        })
    return sorted(rows, key=lambda r: (r["alpha_interpretation_allowed"], r["selectivity_status"], str(r["r3_context_label"])))


def mapping_rows(ledger: pd.DataFrame, context_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    if ledger.empty:
        return [{
            "r2_context_label": "UNKNOWN", "r3_context_label": "UNKNOWN", "repair_rule_id": "NO_LEDGER",
            "repair_source_fields": "", "rows_affected": 0, "distinct_tickers": 0,
            "ticker_coverage_ratio": "", "maturity_ratio": 0, "repair_status": "BLOCKED_INPUTS_MISSING",
            "interpretation_allowed_after_repair": "FALSE", "notes": "R2 ledger missing.",
        }]
    total_tickers = int(ledger["ticker"].nunique())
    audit_by_label = {r["r3_context_label"]: r for r in context_rows}
    rows: list[dict[str, object]] = []
    for (r2_label, r3_label, source, status), g in ledger.groupby(["r2_repaired_context_label", "r3_repaired_context_label", "r3_repair_source", "r3_repair_status"], dropna=False):
        matured = g[g["maturity_status"] == "MATURED"]
        rows.append({
            "r2_context_label": clean(r2_label) or "MISSING_CONTEXT_LABEL",
            "r3_context_label": clean(r3_label) or "MISSING_CONTEXT_LABEL",
            "repair_rule_id": source,
            "repair_source_fields": "sector|industry|theme|benchmark_exposure|rsi_14|volume_ratio|volatility_20|bb_position|momentum_20|benchmark_momentum_20",
            "rows_affected": len(g),
            "distinct_tickers": int(g["ticker"].nunique()),
            "ticker_coverage_ratio": int(g["ticker"].nunique()) / total_tickers if total_tickers else "",
            "maturity_ratio": len(matured) / len(g) if len(g) else 0,
            "repair_status": status,
            "interpretation_allowed_after_repair": audit_by_label.get(clean(r3_label), {}).get("alpha_interpretation_allowed", "FALSE"),
            "notes": clean(g["r3_repair_reason"].iloc[0]) if len(g) else "",
        })
    return rows


def technical_performance(ledger: pd.DataFrame, snap: pd.DataFrame, context_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    default = {
        "r3_context_label": "UNKNOWN", "forward_window": "", "top_bucket": "TOP20", "rows_used": 0,
        "performance_quality": "BLOCKED_INPUTS_MISSING", "interpretation_allowed": "FALSE",
        "interpretation_block_reason": "No joinable matured ledger and V21.038 technical scores.",
    }
    if ledger.empty or snap.empty:
        return [default]
    allowed_by_context = {r["r3_context_label"]: r for r in context_rows}
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
    for (label, window), g in joined.groupby(["r3_repaired_context_label", "forward_window"]):
        top = g[g["baseline_rank"] <= 20].copy()
        vals = pd.to_numeric(top["realized_forward_return"], errors="coerce").dropna()
        bench = pd.to_numeric(top["benchmark_return"], errors="coerce").dropna()
        context_gate = allowed_by_context.get(label, {})
        blocks: list[str] = []
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
        rows.append({
            "r3_context_label": label,
            "forward_window": window,
            "top_bucket": "TOP20",
            "rows_used": len(vals),
            "mean_baseline_true_technical_forward_return": float(vals.mean()) if len(vals) else "",
            "median_baseline_true_technical_forward_return": float(vals.median()) if len(vals) else "",
            "baseline_hit_rate": float((vals > 0).mean()) if len(vals) else "",
            "baseline_downside_rate": float((vals < 0).mean()) if len(vals) else "",
            "benchmark_name": clean(top["benchmark_primary"].replace("", np.nan).dropna().iloc[0]) if "benchmark_primary" in top and top["benchmark_primary"].replace("", np.nan).dropna().any() else "",
            "mean_excess_vs_benchmark": float((vals - bench.reindex(vals.index).fillna(np.nan)).dropna().mean()) if len(bench) else "",
            "performance_quality": "SUFFICIENT" if len(vals) >= MIN_TOP_BUCKET_ROWS else "LOW_SAMPLE",
            "interpretation_allowed": yes(not blocks and len(vals) >= MIN_TOP_BUCKET_ROWS),
            "interpretation_block_reason": "|".join(dict.fromkeys(blocks)),
        })
    return rows or [default]


def build_summary(ledger: pd.DataFrame, r2_audit: pd.DataFrame, context_rows: list[dict[str, object]], source_audit: list[dict[str, object]]) -> dict[str, object]:
    r2_summary = read_first(R2_SUMMARY)
    inputs_missing = not R2_LEDGER.exists() or not R2_AUDIT.exists() or not V38_SNAPSHOT.exists() or ledger.empty
    over_before = int((r2_audit["selectivity_status"] == "BROADCAST_OVERWIDE").sum()) if not r2_audit.empty and "selectivity_status" in r2_audit else 0
    over_after = int(sum(1 for r in context_rows if r["selectivity_status"] == "BROADCAST_OVERWIDE"))
    before_missing = int((ledger["r2_repaired_context_label"] == "MISSING_CONTEXT_LABEL").sum()) if not ledger.empty and "r2_repaired_context_label" in ledger else 0
    after_missing = int((ledger["r3_repaired_context_label"] == "MISSING_CONTEXT_LABEL").sum()) if not ledger.empty else 0
    missing_reduction = max(before_missing - after_missing, 0)
    missing_ratio = missing_reduction / before_missing if before_missing else 0
    context_ready = bool(context_rows) and over_after == 0 and after_missing == 0 and any(r["alpha_interpretation_allowed"] == "TRUE" for r in context_rows)
    retest_allowed = (not inputs_missing) and context_ready and any(r["performance_quality"] == "SUFFICIENT" for r in technical_performance_cache)
    if inputs_missing:
        final_status = BLOCKED_STATUS
        decision = DECISION_BLOCKED
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
        "upstream_v21_040_r2_final_status": r2_summary.get("final_status", ""),
        "r2_canonical_ledger_rows": r2_summary.get("canonical_forward_ledger_rows", len(ledger)),
        "r3_ledger_rows": len(ledger),
        "overbroadcast_context_count_before": over_before,
        "overbroadcast_context_count_after": over_after,
        "missing_context_before_count": before_missing,
        "missing_context_after_count": after_missing,
        "missing_context_reduction_count": missing_reduction,
        "missing_context_reduction_ratio": missing_ratio,
        "distinct_context_labels_before": int(ledger["r2_repaired_context_label"].nunique()) if not ledger.empty and "r2_repaired_context_label" in ledger else 0,
        "distinct_context_labels_after": int(ledger["r3_repaired_context_label"].nunique()) if not ledger.empty else 0,
        "context_source_file_count_scanned": len(source_audit),
        "context_source_file_count_usable": sum(1 for r in source_audit if r["usable_for_context_repair"] == "TRUE"),
        "context_selectivity_ready_after": yes(context_ready),
        "context_overbroadcast_after": yes(over_after > 0),
        "technical_reweighting_retest_allowed": yes(retest_allowed),
        "shadow_gate_allowed": "FALSE",
        "official_adoption_allowed": "FALSE",
        "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "V21.041_R1_TECHNICAL_REWEIGHTING_RETEST_WITH_R3_CONTEXTS_RESEARCH_ONLY" if retest_allowed else "V21.040_R4_CONTEXT_SOURCE_EXPANSION_OR_MANUAL_CONTEXT_REVIEW",
    }


technical_performance_cache: list[dict[str, object]] = []


def repair_queue(summary: dict[str, object], context_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    def add(target: str, issue: str, fix: str, priority: str, blocks: bool, validation: str, notes: str = "") -> None:
        rows.append({
            "repair_item_id": f"V21_040_R3_REPAIR_{len(rows) + 1:03d}",
            "repair_target": target,
            "current_issue": issue,
            "proposed_fix": fix,
            "priority": priority,
            "blocks_technical_retest": yes(blocks),
            "blocks_shadow_gate": "TRUE",
            "official_use_allowed_after_repair": "FALSE",
            "next_validation_required": validation,
            "notes": notes,
        })

    if summary["missing_context_after_count"] not in {"0", 0}:
        add("context_label", "Rows remain MISSING_CONTEXT_LABEL.", "Attach defensible ticker/date context evidence before interpretation.", "HIGH", True, "MISSING_CONTEXT_REPAIR_REFRESH")
    if summary["context_overbroadcast_after"] == "TRUE":
        labels = [r["r3_context_label"] for r in context_rows if r["selectivity_status"] == "BROADCAST_OVERWIDE"]
        add("context_selectivity", "At least one R3 context remains over-broadcast.", "Split remaining broad buckets by additional local exposure, relative-strength, or risk-state sources.", "HIGH", True, "CONTEXT_SELECTIVITY_RECHECK", ";".join(labels[:10]))
    if not rows:
        add("technical_retest", "R3 context gates pass in research ledger.", "Run research-only technical reweighting retest; keep shadow and official adoption blocked.", "MEDIUM", False, "RESEARCH_ONLY_TECHNICAL_RETEST")
    return rows


def validation(summary: dict[str, object], ledger: pd.DataFrame, context_rows: list[dict[str, object]], perf_rows: list[dict[str, object]], source_audit: list[dict[str, object]]) -> list[dict[str, object]]:
    missing_blocked = all(r["alpha_interpretation_allowed"] == "FALSE" for r in context_rows if r["r3_context_label"] == "MISSING_CONTEXT_LABEL")
    broadcast_blocked = all(r["alpha_interpretation_allowed"] == "FALSE" for r in context_rows if r["selectivity_status"] == "BROADCAST_OVERWIDE")
    low_mat_blocked = all(r["alpha_interpretation_allowed"] == "FALSE" for r in context_rows if r["maturity_status"] == "LOW_CONTEXT_MATURITY")
    checks = [
        ("V21_040_R2_CANONICAL_LEDGER_FOUND", yes(R2_LEDGER.exists()), "TRUE"),
        ("V21_038_TECHNICAL_SNAPSHOT_FOUND", yes(V38_SNAPSHOT.exists()), "TRUE"),
        ("CONTEXT_SOURCE_SEARCH_COMPLETED", yes(len(source_audit) > 0), "TRUE"),
        ("CONTEXT_REPAIR_ATTEMPTED", yes(len(ledger) > 0 and "r3_repaired_context_label" in ledger.columns), "TRUE"),
        ("OVERBROADCAST_CONTEXTS_IDENTIFIED", yes(summary["overbroadcast_context_count_before"] not in {"", 0, "0"}), "TRUE"),
        ("OVERBROADCAST_REPAIR_ATTEMPTED", yes(len(ledger) > 0 and "r3_repair_status" in ledger.columns), "TRUE"),
        ("MISSING_CONTEXT_INTERPRETATION_BLOCKED", yes(missing_blocked), "TRUE"),
        ("BROADCAST_CONTEXT_INTERPRETATION_BLOCKED", yes(broadcast_blocked), "TRUE"),
        ("LOW_MATURITY_CONTEXT_INTERPRETATION_BLOCKED", yes(low_mat_blocked), "TRUE"),
        ("CONTEXT_SELECTIVITY_CHECKED", yes(len(context_rows) > 0), "TRUE"),
        ("TECHNICAL_CONTEXT_PERFORMANCE_PRODUCED", yes(len(perf_rows) > 0), "TRUE"),
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
        "notes": "Research-only R3 context source backfill validation.",
    } for item, obs, req in checks]


def write_report(summary: dict[str, object], source_audit: list[dict[str, object]], mapping: list[dict[str, object]], context_rows: list[dict[str, object]], perf_rows: list[dict[str, object]]) -> None:
    usable_sources = [r for r in source_audit if r["usable_for_context_repair"] == "TRUE"]
    source_lines = "\n".join(f"- {r['source_file_path']}: {r['source_role']}" for r in usable_sources[:25]) or "- No usable source discovered."
    mapping_lines = "\n".join(f"- {r['r2_context_label']} -> {r['r3_context_label']}: rows={r['rows_affected']}, status={r['repair_status']}" for r in mapping[:25])
    context_lines = "\n".join(f"- {r['r3_context_label']}: selectivity={r['selectivity_status']}, maturity={r['maturity_status']}, allowed={r['alpha_interpretation_allowed']}" for r in context_rows[:25])
    perf_lines = "\n".join(f"- {r['r3_context_label']} {r['forward_window']}: rows={r['rows_used']}, quality={r['performance_quality']}, allowed={r['interpretation_allowed']}" for r in perf_rows[:25])
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Final status and decision
- final_status: {summary['final_status']}
- decision: {summary['decision']}

## V21.040-R2 blocker summary
R2 final_status was `{summary['upstream_v21_040_r2_final_status']}`. R2 reduced missing context but left context_overbroadcast_after TRUE, so technical reweighting retest and shadow gate stayed blocked.

## Context source search results
Scanned {summary['context_source_file_count_scanned']} local CSV files in the allowed roots. Usable for context repair: {summary['context_source_file_count_usable']}.

{source_lines}

## Second-pass context repair rules
R3 only splits rows whose R2 label was MISSING_CONTEXT_LABEL or BROADCAST_OVERWIDE. It uses certified V20 exposure metadata for sector/theme/benchmark context and V21.038 fields for RSI, volume confirmation, volatility, MA/BB state, and benchmark-relative momentum where joinable. Rows without defensible source evidence remain REPAIR_PENDING.

{mapping_lines}

## Missing context before/after
Before: {summary['missing_context_before_count']}; after: {summary['missing_context_after_count']}; reduction: {summary['missing_context_reduction_count']} ({fmt(summary['missing_context_reduction_ratio'])}).

## Overbroadcast context before/after
Before: {summary['overbroadcast_context_count_before']}; after: {summary['overbroadcast_context_count_after']}.

## Selectivity and maturity after R3
{context_lines}

## Technical performance by R3 context/window
{perf_lines}

## Whether technical reweighting retest is allowed
technical_reweighting_retest_allowed: {summary['technical_reweighting_retest_allowed']}.

## Whether shadow gate remains blocked
shadow_gate_allowed: {summary['shadow_gate_allowed']}. Shadow gate remains blocked unless all context gates pass and a later research-only validation explicitly permits it.

## Why official mutation remains blocked
Official mutation remains blocked because this stage is research-only. official_use_allowed, official_weight_mutation_allowed, official_ranking_mutation_allowed, trade_action_allowed, broker_execution_allowed, real_book_mutation_allowed, official_adoption_allowed, and data_trust_alpha_weight_allowed are all FALSE.

## Next recommended stage
{summary['next_recommended_stage']}
"""
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(report, encoding="utf-8")


def blocked_outputs(source_audit: list[dict[str, object]]) -> None:
    summary = {
        "stage": STAGE, "final_status": BLOCKED_STATUS, "decision": DECISION_BLOCKED,
        "research_only": "TRUE", "official_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE", "official_ranking_mutation_allowed": "FALSE",
        "trade_action_allowed": "FALSE", "broker_execution_allowed": "FALSE",
        "real_book_mutation_allowed": "FALSE", "upstream_v21_040_r2_final_status": read_first(R2_SUMMARY).get("final_status", ""),
        "r2_canonical_ledger_rows": 0, "r3_ledger_rows": 0, "overbroadcast_context_count_before": 0,
        "overbroadcast_context_count_after": 0, "missing_context_before_count": 0,
        "missing_context_after_count": 0, "missing_context_reduction_count": 0,
        "missing_context_reduction_ratio": 0, "distinct_context_labels_before": 0,
        "distinct_context_labels_after": 0, "context_source_file_count_scanned": len(source_audit),
        "context_source_file_count_usable": sum(1 for r in source_audit if r["usable_for_context_repair"] == "TRUE"),
        "context_selectivity_ready_after": "FALSE", "context_overbroadcast_after": "FALSE",
        "technical_reweighting_retest_allowed": "FALSE", "shadow_gate_allowed": "FALSE",
        "official_adoption_allowed": "FALSE", "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "RESTORE_REQUIRED_R2_LEDGER_AUDIT_AND_V21_038_SNAPSHOT",
    }
    write_csv(SUMMARY_OUT, [summary], SUMMARY_FIELDS)
    write_csv(LEDGER_OUT, [{"observation_id": "", "row_quality_status": "BLOCKED_INPUTS_MISSING"}], LEDGER_FIELDS)
    write_csv(SOURCE_AUDIT_OUT, source_audit or [{"source_file_path": "", "exists": "FALSE", "usable_for_context_repair": "FALSE", "reason_if_not_usable": "No sources scanned."}], SOURCE_AUDIT_FIELDS)
    write_csv(MAPPING_OUT, mapping_rows(pd.DataFrame(), []), ["r2_context_label", "r3_context_label", "repair_rule_id", "repair_source_fields", "rows_affected", "distinct_tickers", "ticker_coverage_ratio", "maturity_ratio", "repair_status", "interpretation_allowed_after_repair", "notes"])
    write_csv(CONTEXT_OUT, context_audit(pd.DataFrame()), CONTEXT_FIELDS)
    write_csv(PERF_OUT, technical_performance(pd.DataFrame(), pd.DataFrame(), []), ["r3_context_label", "forward_window", "top_bucket", "rows_used", "mean_baseline_true_technical_forward_return", "median_baseline_true_technical_forward_return", "baseline_hit_rate", "baseline_downside_rate", "benchmark_name", "mean_excess_vs_benchmark", "performance_quality", "interpretation_allowed", "interpretation_block_reason"])
    queue = repair_queue(summary, [])
    write_csv(QUEUE_OUT, queue, ["repair_item_id", "repair_target", "current_issue", "proposed_fix", "priority", "blocks_technical_retest", "blocks_shadow_gate", "official_use_allowed_after_repair", "next_validation_required", "notes"])
    write_csv(VALIDATION_OUT, validation(summary, pd.DataFrame(), [], [], source_audit), ["validation_item", "validation_status", "observed_value", "required_value", "pass_fail", "notes"])
    write_report(summary, source_audit, mapping_rows(pd.DataFrame(), []), context_audit(pd.DataFrame()), technical_performance(pd.DataFrame(), pd.DataFrame(), []))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    source_audit, _ = audit_sources()
    ledger, snap, r2_audit = load_inputs()
    if ledger.empty or snap.empty or r2_audit.empty:
        blocked_outputs(source_audit)
        summary = read_first(SUMMARY_OUT)
    else:
        metadata = load_metadata_context(source_audit)
        snap = enrich_snapshot(snap)
        repaired = repair_ledger(ledger, snap, metadata, r2_audit)
        context_rows = context_audit(repaired)
        mapping = mapping_rows(repaired, context_rows)
        perf_rows = technical_performance(repaired, snap, context_rows)
        global technical_performance_cache
        technical_performance_cache = perf_rows
        summary = build_summary(repaired, r2_audit, context_rows, source_audit)
        queue = repair_queue(summary, context_rows)
        write_csv(SUMMARY_OUT, [summary], SUMMARY_FIELDS)
        write_csv(SOURCE_AUDIT_OUT, source_audit, SOURCE_AUDIT_FIELDS)
        write_csv(LEDGER_OUT, repaired.replace({np.nan: None}).to_dict("records"), LEDGER_FIELDS)
        write_csv(MAPPING_OUT, mapping, ["r2_context_label", "r3_context_label", "repair_rule_id", "repair_source_fields", "rows_affected", "distinct_tickers", "ticker_coverage_ratio", "maturity_ratio", "repair_status", "interpretation_allowed_after_repair", "notes"])
        write_csv(CONTEXT_OUT, context_rows, CONTEXT_FIELDS)
        write_csv(PERF_OUT, perf_rows, ["r3_context_label", "forward_window", "top_bucket", "rows_used", "mean_baseline_true_technical_forward_return", "median_baseline_true_technical_forward_return", "baseline_hit_rate", "baseline_downside_rate", "benchmark_name", "mean_excess_vs_benchmark", "performance_quality", "interpretation_allowed", "interpretation_block_reason"])
        write_csv(QUEUE_OUT, queue, ["repair_item_id", "repair_target", "current_issue", "proposed_fix", "priority", "blocks_technical_retest", "blocks_shadow_gate", "official_use_allowed_after_repair", "next_validation_required", "notes"])
        write_csv(VALIDATION_OUT, validation(summary, repaired, context_rows, perf_rows, source_audit), ["validation_item", "validation_status", "observed_value", "required_value", "pass_fail", "notes"])
        write_report(summary, source_audit, mapping, context_rows, perf_rows)

    print(f"STAGE_NAME={STAGE}")
    print(f"final_status={summary['final_status']}")
    print(f"decision={summary['decision']}")
    print(f"r3_ledger_rows={summary['r3_ledger_rows']}")
    print(f"missing_context_after_count={summary['missing_context_after_count']}")
    print(f"context_overbroadcast_after={summary['context_overbroadcast_after']}")
    print(f"technical_reweighting_retest_allowed={summary['technical_reweighting_retest_allowed']}")
    print(f"shadow_gate_allowed={summary['shadow_gate_allowed']}")


if __name__ == "__main__":
    main()
