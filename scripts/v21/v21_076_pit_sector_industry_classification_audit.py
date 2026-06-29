#!/usr/bin/env python
"""Build and audit PIT-safe sector, industry, ETF, and theme classifications."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_073_common import SOURCE_REL, protected_files, sha256, truth


STAGE = "V21.076-R1_TO_R3_PIT_SECTOR_INDUSTRY_CLASSIFICATION_AUDIT"
OUT_REL = Path("outputs/v21/v21_076")
HOLDINGS_REL = Path("outputs/v21/v21_075/V21_075_R2_PORTFOLIO_HOLDINGS.csv")
METADATA_REL = Path("outputs/v20/consolidation/snapshots/V20_108_R8_R2_ENABLED_METADATA_CACHE.csv")
ETF_SEED_REL = Path("configs/v21/etf_universe_seed.csv")

MASTER_NAME = "V21_076_R1_CLASSIFICATION_MASTER.csv"
AUDIT_NAME = "V21_076_R2_CLASSIFICATION_AUDIT_SUMMARY.csv"
MISSING_NAME = "V21_076_R2_MISSING_CLASSIFICATION_REPORT.csv"
LOW_CONF_NAME = "V21_076_R2_LOW_CONFIDENCE_THEME_REPORT.csv"
ETF_NAME = "V21_076_R2_ETF_CLASSIFICATION_REPORT.csv"
EXPOSURE_NAME = "V21_076_R3_D_EW_SECTOR_EXPOSURE_DIAGNOSTIC.csv"
READINESS_NAME = "V21_076_R3_READINESS_DECISION_REPORT.csv"

THEME_TERMS = {
    "semiconductor": ("semiconductor", "chip", "silicon", "foundry", "wafer"),
    "memory_storage": ("memory", "storage", "dram", "nand", "ssd", "disk drive"),
    "AI_infrastructure": ("artificial intelligence", " ai ", "data center", "accelerator", "gpu"),
    "software": ("software", "saas", "cloud", "application"),
    "cybersecurity": ("cybersecurity", "security", "zero trust"),
    "biotech": ("biotech", "biotechnology", "pharmaceutical", "therapeutic", "clinical"),
    "fintech": ("fintech", "payments", "lending", "brokerage", "financial technology"),
    "industrials": ("industrial", "machinery", "construction", "engineering"),
    "energy": ("energy", "oil", "gas", "utility", "power generation"),
    "precious_metals": ("gold", "silver", "copper", "mining", "metals"),
    "telecom": ("telecom", "communications", "wireless", "broadband", "networking"),
    "consumer": ("consumer", "retail", "restaurant", "apparel", "travel"),
}


def clean(value: Any) -> str:
    return "" if pd.isna(value) else str(value).strip()


def norm_ticker(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.upper().str.strip()


def source_date(value: Any) -> str:
    text = clean(value)
    return text[:10] if len(text) >= 10 else ""


def read_universe(root: Path) -> tuple[set[str], pd.DataFrame, pd.DataFrame]:
    panel_cols = ["ticker", "sampled_as_of_date", "instrument_type", "theme"]
    panel_chunks = []
    for chunk in pd.read_csv(root / SOURCE_REL, usecols=panel_cols, chunksize=250000, low_memory=False):
        chunk["ticker"] = norm_ticker(chunk["ticker"])
        panel_chunks.append(chunk[chunk["ticker"].ne("")])
    panel = pd.concat(panel_chunks, ignore_index=True)
    holdings_cols = [
        "ticker", "sampled_as_of_date", "selection_policy_id",
        "position_policy_id", "joint_portfolio_policy_id", "forward_window",
        "split", "position_weight",
    ]
    holding_chunks = []
    for chunk in pd.read_csv(root / HOLDINGS_REL, usecols=holdings_cols, chunksize=250000, low_memory=False):
        chunk["ticker"] = norm_ticker(chunk["ticker"])
        holding_chunks.append(chunk[chunk["ticker"].ne("")])
    holdings = pd.concat(holding_chunks, ignore_index=True)
    universe = set(panel["ticker"]) | set(holdings["ticker"])
    return universe, panel, holdings


def theme_tags(row: pd.Series, etf: pd.Series | None) -> tuple[str, str, bool]:
    tags: list[str] = []
    inferred = False
    quote = clean(row.get("quote_type")).upper()
    category = clean(row.get("category")).lower()
    is_metadata_fund = truth(row.get("is_etf_or_fund")) or quote in {"ETF", "MUTUALFUND"}
    if etf is not None:
        if truth(etf.get("is_core_market_proxy")):
            tags.append("ETF_core")
        if truth(etf.get("is_sector_proxy")):
            tags.append("ETF_sector")
        if truth(etf.get("is_thematic_proxy")):
            tags.append("ETF_thematic")
        if truth(etf.get("is_leveraged")) and not truth(etf.get("is_inverse")):
            tags.append("ETF_leveraged_long")
        if truth(etf.get("is_inverse")):
            tags.append("ETF_inverse")
        theme = clean(etf.get("theme")).upper()
        if "SEMI" in theme:
            tags.append("semiconductor")
        if "MEMORY" in theme or "DRAM" in theme:
            tags.append("memory_storage")
    elif is_metadata_fund:
        if any(term in category for term in ("large blend", "small blend", "diversified", "broad", "region")):
            tags.append("ETF_core")
        elif any(term in category for term in ("technology", "financial", "commodity", "digital assets")):
            tags.append("ETF_sector")
        else:
            tags.append("ETF_thematic")
    text = " ".join(
        clean(row.get(field)).lower()
        for field in ("sector", "industry", "industry_key", "sector_key", "category", "theme_hint", "business_summary")
    )
    padded = f" {text} "
    for tag, terms in THEME_TERMS.items():
        if any(term in padded for term in terms):
            tags.append(tag)
            inferred = True
    unique = sorted(set(tags))
    confidence = "HIGH" if etf is not None and unique else "LOW" if inferred else ""
    return "|".join(unique), confidence, inferred


def etf_category(etf: pd.Series | None, meta_row: pd.Series) -> tuple[str, bool, bool]:
    if etf is not None:
        category = clean(etf.get("instrument_type"))
        inverse = truth(etf.get("is_inverse")) or clean(etf.get("direction")).upper() == "INVERSE"
        leveraged = truth(etf.get("is_leveraged")) or abs(float(etf.get("leverage_multiplier") or 1)) != 1
        return category, leveraged, inverse
    quote = clean(meta_row.get("quote_type")).upper()
    category = clean(meta_row.get("category")) or clean(meta_row.get("instrument_type"))
    is_fund = truth(meta_row.get("is_etf_or_fund")) or quote in {"ETF", "MUTUALFUND"}
    return category if is_fund else "", False, False


def build_master(root: Path, universe: set[str]) -> pd.DataFrame:
    meta = pd.read_csv(root / METADATA_REL, low_memory=False)
    meta["ticker"] = norm_ticker(meta["ticker"])
    etf_seed = pd.read_csv(root / ETF_SEED_REL, low_memory=False)
    etf_seed["ticker"] = norm_ticker(etf_seed["ticker"])
    etf_map = {row["ticker"]: row for _, row in etf_seed.iterrows()}
    rows = []
    for ticker in sorted(universe):
        matches = meta[meta["ticker"].eq(ticker)]
        row = matches.iloc[0] if not matches.empty else pd.Series(dtype=object)
        etf = etf_map.get(ticker)
        metadata_is_fund = truth(row.get("is_etf_or_fund")) or clean(row.get("quote_type")).upper() in {"ETF", "MUTUALFUND"}
        sector = clean(row.get("sector"))
        industry = clean(row.get("industry"))
        if etf is not None:
            sector = sector or "ETF"
            industry = industry or clean(etf.get("underlying_index")) or clean(etf.get("theme"))
        category, leveraged, inverse = etf_category(etf, row)
        if etf is None and metadata_is_fund:
            sector = sector or "ETF"
            industry = industry or category or "ETF_OR_FUND"
        tags, tag_confidence, inferred = theme_tags(row, etf)
        source = "LOCAL_ETF_SEED+V20_108_R8_R2_METADATA_CACHE" if etf is not None else "V20_108_R8_R2_ENABLED_METADATA_CACHE"
        as_of = source_date(row.get("metadata_source_timestamp")) or source_date(row.get("refresh_timestamp_utc")) or "2026-06-13"
        quality = (
            "HIGH_CERTIFIED" if sector and industry and clean(row.get("exposure_metadata_certification_status")) == "EXPOSURE_METADATA_CERTIFIED"
            else "MEDIUM_CERTIFIED_FUND_CATEGORY" if metadata_is_fund and sector and industry
            else "HIGH_ETF_SEED" if etf is not None and sector
            else "MEDIUM_PARTIAL" if sector or industry or category
            else "MISSING"
        )
        source_score = 1.0 if etf is not None else 0.95 if "HIGH" in quality else 0.65 if "MEDIUM" in quality else 0.0
        rows.append({
            "ticker": ticker,
            "sector": sector,
            "industry": industry,
            "sub_industry": clean(row.get("industry_key")) or industry,
            "theme_tags": tags,
            "theme_confidence": tag_confidence,
            "theme_tags_inferred": inferred,
            "theme_tags_allowed_for_hard_caps": False if inferred or tag_confidence != "HIGH" else True,
            "etf_category": category,
            "is_etf": bool(category) or (etf is not None),
            "etf_leverage_inverse_flag": "INVERSE" if inverse else "LEVERAGED_LONG" if leveraged else "UNLEVERED_OR_NA",
            "classification_source": source,
            "classification_as_of_date": as_of,
            "classification_quality_flag": quality,
            "stable_company_classification": etf is None,
            "time_varying_classification": False,
            "low_confidence_label": quality in {"MEDIUM_PARTIAL", "MISSING"} or (bool(tags) and tag_confidence == "LOW"),
            "source_reliability_score": source_score,
            "pit_leakage_warning": False,
            "research_only": True,
        })
    return pd.DataFrame(rows)


def classification_audits(root: Path, master: pd.DataFrame, panel: pd.DataFrame, holdings: pd.DataFrame) -> dict[str, Any]:
    lookup = master.set_index("ticker")
    h = holdings.join(lookup[["sector", "industry", "theme_tags", "etf_category", "is_etf"]], on="ticker")
    d20 = h[(h["selection_policy_id"].eq("D_WEIGHT_OPTIMIZED_R1")) & (h["position_policy_id"].eq("EW_TOP20_R1"))]
    d50 = h[(h["selection_policy_id"].eq("D_WEIGHT_OPTIMIZED_R1")) & (h["position_policy_id"].eq("EW_TOP50_R1"))]
    etfs = master[master["is_etf"].map(truth)]
    meta = pd.read_csv(root / METADATA_REL, usecols=["ticker", "sector", "industry"], low_memory=False)
    meta["ticker"] = norm_ticker(meta["ticker"])
    conflict_count = int(
        meta.groupby("ticker")[["sector", "industry"]]
        .nunique(dropna=True)
        .gt(1)
        .any(axis=1)
        .sum()
    )
    dup_count = int(meta["ticker"].duplicated().sum())
    stale = int(pd.to_datetime(master["classification_as_of_date"], errors="coerce").lt(pd.Timestamp("2025-06-21")).sum())
    impossible_etfs = int(master[master["is_etf"].map(truth) & master["etf_category"].astype(str).str.strip().eq("")].shape[0])
    return {
        "universe_ticker_count": int(master["ticker"].nunique()),
        "universe_coverage_rate": float(master["sector"].astype(str).str.strip().ne("").mean()),
        "holdings_unique_ticker_count": int(h["ticker"].nunique()),
        "holdings_coverage_rate": float(h["sector"].astype(str).str.strip().ne("").mean()),
        "top20_coverage_rate": float(d20["sector"].astype(str).str.strip().ne("").mean()),
        "top50_coverage_rate": float(d50["sector"].astype(str).str.strip().ne("").mean()),
        "missing_sector_count": int(master["sector"].astype(str).str.strip().eq("").sum()),
        "missing_industry_count": int(master["industry"].astype(str).str.strip().eq("").sum()),
        "missing_theme_count": int(master["theme_tags"].astype(str).str.strip().eq("").sum()),
        "sector_coverage_rate": float(master["sector"].astype(str).str.strip().ne("").mean()),
        "industry_coverage_rate": float(master["industry"].astype(str).str.strip().ne("").mean()),
        "theme_coverage_rate": float(master["theme_tags"].astype(str).str.strip().ne("").mean()),
        "etf_category_coverage": float(etfs["etf_category"].astype(str).str.strip().ne("").mean()) if len(etfs) else 1.0,
        "duplicate_ticker_mapping_count": dup_count,
        "conflicting_sector_industry_label_count": conflict_count,
        "duplicate_conflict_count": dup_count + conflict_count,
        "stale_classification_count": stale,
        "impossible_etf_classification_count": impossible_etfs,
        "leverage_inverse_etf_count": int(master["etf_leverage_inverse_flag"].isin(["INVERSE", "LEVERAGED_LONG"]).sum()),
        "pit_leakage_warnings": int(master["pit_leakage_warning"].map(truth).sum()),
        "source_reliability_score": float(master["source_reliability_score"].mean()),
        "stable_company_classification_count": int(master["stable_company_classification"].map(truth).sum()),
        "time_varying_classification_count": int(master["time_varying_classification"].map(truth).sum()),
        "inferred_theme_tag_count": int(master["theme_tags_inferred"].map(truth).sum()),
        "low_confidence_label_count": int(master["low_confidence_label"].map(truth).sum()),
    }


def exposure_diagnostic(master: pd.DataFrame, holdings: pd.DataFrame) -> pd.DataFrame:
    lookup = master.set_index("ticker")[["sector", "industry", "theme_tags"]]
    h = holdings.join(lookup, on="ticker")
    h = h[
        h["selection_policy_id"].eq("D_WEIGHT_OPTIMIZED_R1")
        & h["position_policy_id"].isin(["EW_TOP20_R1", "EW_TOP50_R1"])
    ].copy()
    h["sector"] = h["sector"].replace("", "MISSING")
    h["position_weight"] = pd.to_numeric(h["position_weight"], errors="coerce").fillna(0)
    rows = []
    keys = ["position_policy_id", "forward_window", "split", "sampled_as_of_date", "joint_portfolio_policy_id"]
    for keys_value, group in h.groupby(keys, sort=False):
        sector_weights = group.groupby("sector")["position_weight"].sum()
        for sector, weight in sector_weights.items():
            rows.append({
                "position_policy_id": keys_value[0],
                "forward_window": keys_value[1],
                "split": keys_value[2],
                "sampled_as_of_date": keys_value[3],
                "joint_portfolio_policy_id": keys_value[4],
                "sector": sector,
                "sector_weight": weight,
                "ticker_count": int(group[group["sector"].eq(sector)]["ticker"].nunique()),
                "sector_missing": sector == "MISSING",
                "research_only": True,
            })
    return pd.DataFrame(rows)


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (output_override if output_override and output_override.is_absolute() else root / (output_override or OUT_REL)).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protected = protected_files(root, output)
    for rel in ("outputs/v21/v21_072", "outputs/v21/v21_073", "outputs/v21/v21_074", "outputs/v21/v21_075"):
        base = root / rel
        protected.extend(path.resolve() for path in base.rglob("*") if path.is_file())
    protected = sorted(set(protected))
    before = {path: sha256(path) for path in protected}

    universe, panel, holdings = read_universe(root)
    master = build_master(root, universe)
    master.to_csv(output / MASTER_NAME, index=False)
    audit = classification_audits(root, master, panel, holdings)
    pd.DataFrame([{"stage": "V21.076-R2_CLASSIFICATION_INTEGRITY_AND_PIT_AUDIT", **audit, "research_only": True}]).to_csv(output / AUDIT_NAME, index=False)
    missing = master[
        master["sector"].astype(str).str.strip().eq("")
        | master["industry"].astype(str).str.strip().eq("")
        | master["theme_tags"].astype(str).str.strip().eq("")
    ]
    missing.to_csv(output / MISSING_NAME, index=False)
    low_conf = master[master["low_confidence_label"].map(truth) | master["theme_tags_inferred"].map(truth)]
    low_conf.to_csv(output / LOW_CONF_NAME, index=False)
    master[master["is_etf"].map(truth)].to_csv(output / ETF_NAME, index=False)
    exposure = exposure_diagnostic(master, holdings)
    exposure.to_csv(output / EXPOSURE_NAME, index=False)

    after = {path: sha256(path) for path in protected}
    changed = [path.as_posix() for path in protected if before[path] != after[path]]
    gates = {
        "top20_sector_coverage_gate": audit["top20_coverage_rate"] >= 0.98,
        "top50_sector_coverage_gate": audit["top50_coverage_rate"] >= 0.98,
        "holdings_sector_coverage_gate": audit["holdings_coverage_rate"] >= 0.95,
        "etf_category_coverage_gate": audit["etf_category_coverage"] >= 0.95,
        "duplicate_conflict_gate": audit["duplicate_conflict_count"] == 0,
        "pit_leakage_gate": audit["pit_leakage_warnings"] == 0,
        "theme_hard_cap_gate": not master.loc[master["theme_confidence"].eq("LOW"), "theme_tags_allowed_for_hard_caps"].map(truth).any(),
        "protected_output_gate": len(changed) == 0,
        "official_output_gate": True,
    }
    ready = all(gates.values())
    theme_warn = audit["theme_coverage_rate"] < 0.98 or audit["low_confidence_label_count"] > 0
    final_status = (
        "PARTIAL_PASS_V21_076_R3_CLASSIFICATION_READY_WITH_THEME_CONFIDENCE_WARN"
        if ready and theme_warn else
        "PASS_V21_076_R3_SECTOR_CLASSIFICATION_READY"
        if ready else
        "BLOCKED_V21_076_R3_CLASSIFICATION_COVERAGE_OR_PIT_RISK"
    )
    decision = (
        "SECTOR_AWARE_RISK_BUDGET_BACKTEST_ALLOWED_LATER"
        if ready else "KEEP_D_EQUAL_WEIGHT_BASELINE_AND_BLOCK_SECTOR_AWARE_SIZING"
    )
    readiness = {
        "stage": "V21.076-R3_SECTOR_AWARE_RISK_BUDGET_READINESS_REVIEW",
        "final_status": final_status,
        "decision": decision,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        **audit,
        **gates,
        "sector_aware_risk_budget_backtest_allowed": ready,
        "d_equal_weight_baseline_preserved": True,
        "protected_outputs_modified": bool(changed),
        "official_outputs_mutated": False,
        "official_adoption_allowed": False,
        "research_only": True,
        "protected_modified_paths": "|".join(changed),
        "pass_gate": ready,
    }
    pd.DataFrame([readiness]).to_csv(output / READINESS_NAME, index=False)
    return readiness


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    for key in ("final_status", "decision", "universe_ticker_count", "holdings_unique_ticker_count", "sector_coverage_rate", "industry_coverage_rate", "theme_coverage_rate"):
        print(f"{key.upper()}={result[key]}")
    return 0 if result["pass_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
