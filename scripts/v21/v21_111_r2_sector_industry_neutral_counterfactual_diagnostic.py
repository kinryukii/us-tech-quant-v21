#!/usr/bin/env python
"""V21.111-R2 sector/industry-neutral D counterfactual diagnostic."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


STAGE = "V21.111-R2_SECTOR_INDUSTRY_NEUTRAL_COUNTERFACTUAL_DIAGNOSTIC"
ARCHIVE_REL = Path("outputs/v21/V21.108_latest_data_multi_strategy_rerun/R2_archived_latest_strategy_rankings")
V111_REL = Path("outputs/v21/V21.111_D_FAILURE_MODE_DECOMPOSITION")
R1_REL = Path("outputs/v21/V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT")
OUTPUT_REL = Path("outputs/v21/V21.111_R2_SECTOR_INDUSTRY_NEUTRAL_COUNTERFACTUAL_DIAGNOSTIC")
STRATEGIES = ["A1_BASELINE_CONTROL", "B_STATIC_MOMENTUM_BLEND", "C_DYNAMIC_MOMENTUM_BLEND", "D_WEIGHT_OPTIMIZED_R1"]
REPORT = "V21.111_R2_SECTOR_INDUSTRY_NEUTRAL_COUNTERFACTUAL_DIAGNOSTIC_REPORT.md"
SUMMARY = "V21.111_R2_SECTOR_INDUSTRY_NEUTRAL_COUNTERFACTUAL_DIAGNOSTIC_SUMMARY.json"
MANIFEST = "V21.111_R2_SECTOR_INDUSTRY_NEUTRAL_COUNTERFACTUAL_DIAGNOSTIC_MANIFEST.csv"


CSV_FIELDS: dict[str, list[str]] = {
    "input_inventory.csv": ["source_name", "path", "exists", "row_count", "hash", "min_rank", "max_rank", "notes"],
    "raw_d_top20.csv": [],
    "raw_d_top50.csv": [],
    "d_sector_neutral_percentile_ranking.csv": [],
    "d_sector_quota_counterfactual_top20.csv": [],
    "d_sector_quota_counterfactual_top50.csv": [],
    "d_industry_neutral_percentile_ranking.csv": [],
    "d_industry_quota_counterfactual_top20.csv": [],
    "d_industry_quota_counterfactual_top50.csv": [],
    "raw_vs_sector_neutral_overlap.csv": ["method", "view", "overlap_count", "raw_count", "counterfactual_count", "overlap_ratio", "removed_tickers", "added_tickers", "notes"],
    "raw_vs_industry_neutral_overlap.csv": ["method", "view", "overlap_count", "raw_count", "counterfactual_count", "overlap_ratio", "removed_tickers", "added_tickers", "notes"],
    "displacement_top20.csv": ["method", "neutralization_type", "change_type", "ticker", "sector", "industry", "raw_rank", "counterfactual_rank", "raw_final_score", "notes"],
    "displacement_top50.csv": ["method", "neutralization_type", "change_type", "ticker", "sector", "industry", "raw_rank", "counterfactual_rank", "raw_final_score", "notes"],
    "score_sacrifice_summary.csv": ["method", "neutralization_type", "view", "raw_avg_final_score", "counterfactual_avg_final_score", "score_sacrifice", "removed_avg_final_score", "added_avg_final_score", "notes"],
    "concentration_reduction_summary.csv": ["portfolio", "view", "top_sector_name", "top_sector_weight", "top_industry_name", "top_industry_weight", "sector_hhi", "industry_hhi", "technology_weight", "semiconductor_equipment_materials_weight", "d_only_vs_a1_count", "score_concentration_warning", "notes"],
    "counterfactual_exposure_comparison.csv": ["portfolio", "view", "exposure_type", "bucket", "count", "weight", "notes"],
    "counterfactual_vs_A1_B_C_overlap.csv": ["portfolio", "view", "comparison_strategy", "overlap_count", "overlap_ratio", "more_similar_to_a1_than_raw", "notes"],
    "counterfactual_identity_summary.csv": ["portfolio", "view", "avg_momentum_score", "avg_relative_momentum_score", "raw_avg_momentum_score", "momentum_identity_preserved", "notes"],
    "neutralization_diagnostic_classification.csv": ["classification", "severity", "evidence", "research_only"],
    "neutralization_diagnostic_summary.csv": ["classification", "event_count", "max_severity", "notes"],
}


def clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none"} else text


def truth(value: Any) -> bool:
    return clean(value).upper() in {"TRUE", "1", "YES", "Y"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    if not fields:
        fields = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    def default(value: Any) -> Any:
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            return None if np.isnan(value) else float(value)
        if isinstance(value, np.bool_):
            return bool(value)
        if pd.isna(value):
            return None
        raise TypeError(type(value).__name__)
    path.write_text(json.dumps(payload, indent=2, default=default) + "\n", encoding="utf-8")


def read_frame(path: Path | None) -> pd.DataFrame:
    if not path or not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def discover_latest(root: Path, patterns: list[str], required: set[str] | None = None) -> Path | None:
    found: list[tuple[float, Path]] = []
    for pattern in patterns:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            if required:
                try:
                    cols = set(pd.read_csv(path, nrows=1).columns)
                except Exception:
                    continue
                if not required.issubset(cols):
                    continue
            found.append((path.stat().st_mtime, path))
    return max(found)[1] if found else None


def immutable_output(root: Path, override: Path | None) -> Path:
    out = (override if override and override.is_absolute() else root / (override or OUTPUT_REL)).resolve()
    out.mkdir(parents=True, exist_ok=True)
    allowed = {*CSV_FIELDS.keys(), REPORT, SUMMARY, MANIFEST}
    unmanaged = [p.name for p in out.iterdir() if p.is_file() and p.name not in allowed]
    if unmanaged:
        raise RuntimeError(f"Output directory contains unmanaged files: {unmanaged}")
    return out


def inventory(root: Path, source_name: str, path: Path | None, notes: str) -> dict[str, Any]:
    if not path:
        return {"source_name": source_name, "path": "", "exists": False, "row_count": 0, "hash": "", "min_rank": "", "max_rank": "", "notes": notes}
    resolved = path if path.is_absolute() else root / path
    rel = resolved.relative_to(root).as_posix() if resolved.exists() and resolved.is_relative_to(root) else str(path)
    if not resolved.is_file():
        return {"source_name": source_name, "path": rel, "exists": False, "row_count": 0, "hash": "", "min_rank": "", "max_rank": "", "notes": notes}
    try:
        frame = pd.read_csv(resolved, low_memory=False)
        min_rank = pd.to_numeric(frame["rank"], errors="coerce").min() if "rank" in frame else ""
        max_rank = pd.to_numeric(frame["rank"], errors="coerce").max() if "rank" in frame else ""
        rows = len(frame)
    except Exception as exc:
        rows, min_rank, max_rank = 0, "", ""
        notes = f"{notes}; read_error={exc}"
    return {"source_name": source_name, "path": rel, "exists": True, "row_count": rows, "hash": sha256(resolved), "min_rank": min_rank, "max_rank": max_rank, "notes": notes}


def load_rankings(root: Path) -> tuple[dict[str, dict[str, pd.DataFrame]], dict[str, Path]]:
    frames: dict[str, dict[str, pd.DataFrame]] = {}
    paths: dict[str, Path] = {}
    for strategy in STRATEGIES:
        frames[strategy] = {}
        for view, name in {"top20": "top20_ranking.csv", "top50": "top50_ranking.csv", "full": "full_ranking.csv"}.items():
            path = root / ARCHIVE_REL / strategy / name
            paths[f"{strategy}_{view}"] = path
            frame = read_frame(path)
            if not frame.empty and "ticker" in frame:
                frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
                frame["strategy"] = strategy
                frame["view"] = view
            frames[strategy][view] = frame
    return frames, paths


def augment(frame: pd.DataFrame, classification: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if result.empty or "ticker" not in result:
        return result
    if not classification.empty and "ticker" in classification:
        cols = [c for c in ["ticker", "sector", "industry", "sub_industry", "theme_tags", "is_etf", "classification_quality_flag"] if c in classification]
        cls = classification[cols].drop_duplicates("ticker", keep="last").copy()
        cls["ticker"] = cls["ticker"].astype(str).str.upper().str.strip()
        result = result.merge(cls, on="ticker", how="left")
    for col in ["rank", "final_score", "base_score", "momentum_score", "relative_momentum_score"]:
        if col in result:
            result[col] = pd.to_numeric(result[col], errors="coerce")
    if "eligible_flag" not in result:
        result["eligible_flag"] = True
    return result


def add_diag_flags(frame: pd.DataFrame, method: str) -> pd.DataFrame:
    result = frame.copy()
    result["counterfactual_method"] = method
    result["diagnostic_only"] = True
    result["research_only"] = True
    result["official_adoption_allowed"] = False
    result["broker_action_allowed"] = False
    result["trade_instruction"] = False
    result["rank_mutation_applied_to_source"] = False
    return result


def topn(frame: pd.DataFrame, n: int) -> pd.DataFrame:
    return frame.sort_values(["rank", "ticker"], na_position="last").head(n).copy()


def topn_counterfactual(frame: pd.DataFrame, n: int) -> pd.DataFrame:
    return frame.sort_values(["counterfactual_rank", "ticker"], na_position="last").head(n).copy()


def eligible_universe(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "eligible_flag" in result:
        result = result[result["eligible_flag"].map(lambda x: truth(x) or clean(x).lower() == "true")]
    return result.dropna(subset=["final_score"])


def percentile_ranking(frame: pd.DataFrame, group_col: str, method: str) -> pd.DataFrame:
    result = frame.copy()
    result[group_col] = result[group_col].fillna("UNCLASSIFIED").astype(str)
    result[f"within_{group_col}_score_percentile"] = result.groupby(group_col)["final_score"].rank(pct=True, method="average")
    result = result.sort_values([f"within_{group_col}_score_percentile", "final_score", "ticker"], ascending=[False, False, True]).reset_index(drop=True)
    result["counterfactual_rank"] = np.arange(1, len(result) + 1)
    return add_diag_flags(result, method)


def quotas(frame: pd.DataFrame, group_col: str, n: int) -> dict[str, int]:
    weights = frame[group_col].fillna("UNCLASSIFIED").astype(str).value_counts(normalize=True).to_dict()
    raw = {k: v * n for k, v in weights.items()}
    base = {k: int(np.floor(v)) for k, v in raw.items()}
    remainder = n - sum(base.values())
    for k, _ in sorted(raw.items(), key=lambda kv: (kv[1] - np.floor(kv[1]), kv[1]), reverse=True)[:remainder]:
        base[k] += 1
    return {k: v for k, v in base.items() if v > 0}


def quota_selection(frame: pd.DataFrame, group_col: str, n: int, method: str) -> pd.DataFrame:
    work = frame.copy()
    work[group_col] = work[group_col].fillna("UNCLASSIFIED").astype(str)
    selected_idx: list[int] = []
    for bucket, quota in quotas(work, group_col, n).items():
        group = work[work[group_col].eq(bucket)].sort_values(["final_score", "ticker"], ascending=[False, True])
        selected_idx.extend(group.head(quota).index.tolist())
    selected = work.loc[sorted(set(selected_idx))].copy()
    if len(selected) < n:
        fill = work.drop(index=selected.index).sort_values(["final_score", "ticker"], ascending=[False, True]).head(n - len(selected))
        selected = pd.concat([selected, fill], ignore_index=False)
    selected = selected.sort_values(["final_score", "ticker"], ascending=[False, True]).head(n).reset_index(drop=True)
    selected["counterfactual_rank"] = np.arange(1, len(selected) + 1)
    selected["quota_group_column"] = group_col
    selected["quota_target_size"] = n
    return add_diag_flags(selected, method)


def bucket_stats(frame: pd.DataFrame, column: str) -> tuple[str, float, pd.Series]:
    if frame.empty or column not in frame:
        return "MISSING", 0.0, pd.Series(dtype=float)
    counts = frame[column].fillna("UNCLASSIFIED").astype(str).value_counts()
    if counts.empty:
        return "MISSING", 0.0, counts
    return str(counts.index[0]), float(counts.iloc[0] / len(frame)), counts


def hhi(counts: pd.Series) -> float:
    values = pd.to_numeric(counts, errors="coerce").dropna()
    total = values.sum()
    if total <= 0:
        return 0.0
    shares = values / total
    return float((shares ** 2).sum())


def concentration_row(name: str, view: str, frame: pd.DataFrame, a1: pd.DataFrame) -> dict[str, Any]:
    sector, sector_w, sector_counts = bucket_stats(frame, "sector")
    industry, industry_w, industry_counts = bucket_stats(frame, "industry")
    sectors = frame["sector"].fillna("UNCLASSIFIED").astype(str) if "sector" in frame else pd.Series(dtype=str)
    industries = frame["industry"].fillna("UNCLASSIFIED").astype(str) if "industry" in frame else pd.Series(dtype=str)
    a1_tickers = set(a1["ticker"]) if not a1.empty and "ticker" in a1 else set()
    d_only = len(set(frame["ticker"]) - a1_tickers) if "ticker" in frame else 0
    tech_w = float(sectors.eq("Technology").mean()) if len(sectors) else 0.0
    semi_w = float(industries.eq("Semiconductor Equipment & Materials").mean()) if len(industries) else 0.0
    top_sector_scores = frame.loc[sectors.eq(sector), "final_score"] if "final_score" in frame and len(sectors) else pd.Series(dtype=float)
    rest_scores = frame.loc[~sectors.eq(sector), "final_score"] if "final_score" in frame and len(sectors) else pd.Series(dtype=float)
    score_warning = bool(len(rest_scores) and top_sector_scores.mean() - rest_scores.mean() > 2.0)
    return {
        "portfolio": name, "view": view, "top_sector_name": sector, "top_sector_weight": sector_w,
        "top_industry_name": industry, "top_industry_weight": industry_w,
        "sector_hhi": hhi(sector_counts), "industry_hhi": hhi(industry_counts),
        "technology_weight": tech_w,
        "semiconductor_equipment_materials_weight": semi_w,
        "d_only_vs_a1_count": d_only,
        "score_concentration_warning": score_warning,
        "notes": "diagnostic_only_exposure",
    }


def exposure_rows(name: str, view: str, frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for exposure_type, col in [("sector", "sector"), ("industry", "industry")]:
        if col not in frame or frame.empty:
            continue
        for bucket, count in frame[col].fillna("UNCLASSIFIED").astype(str).value_counts().items():
            rows.append({"portfolio": name, "view": view, "exposure_type": exposure_type, "bucket": bucket, "count": int(count), "weight": float(count / len(frame)), "notes": "diagnostic_only"})
    return rows


def overlap(raw: pd.DataFrame, cf: pd.DataFrame, method: str, view: str) -> dict[str, Any]:
    raw_set = set(raw["ticker"])
    cf_set = set(cf["ticker"])
    return {
        "method": method, "view": view, "overlap_count": len(raw_set & cf_set),
        "raw_count": len(raw_set), "counterfactual_count": len(cf_set),
        "overlap_ratio": len(raw_set & cf_set) / len(raw_set) if raw_set else 0.0,
        "removed_tickers": ",".join(sorted(raw_set - cf_set)),
        "added_tickers": ",".join(sorted(cf_set - raw_set)),
        "notes": "diagnostic_only_no_source_mutation",
    }


def displacement(raw: pd.DataFrame, cf: pd.DataFrame, method: str, neutral_type: str, view: str) -> list[dict[str, Any]]:
    rows = []
    raw_idx = raw.set_index("ticker", drop=False)
    cf_idx = cf.set_index("ticker", drop=False)
    for ticker in sorted(set(raw_idx.index) - set(cf_idx.index)):
        r = raw_idx.loc[ticker]
        rows.append({"method": method, "neutralization_type": neutral_type, "change_type": "REMOVED_FROM_RAW_D", "ticker": ticker, "sector": r.get("sector", ""), "industry": r.get("industry", ""), "raw_rank": r.get("rank", ""), "counterfactual_rank": "", "raw_final_score": r.get("final_score", ""), "notes": view})
    for ticker in sorted(set(cf_idx.index) - set(raw_idx.index)):
        r = cf_idx.loc[ticker]
        rows.append({"method": method, "neutralization_type": neutral_type, "change_type": "ADDED_TO_COUNTERFACTUAL", "ticker": ticker, "sector": r.get("sector", ""), "industry": r.get("industry", ""), "raw_rank": r.get("rank", ""), "counterfactual_rank": r.get("counterfactual_rank", ""), "raw_final_score": r.get("final_score", ""), "notes": view})
    return rows


def sacrifice(raw: pd.DataFrame, cf: pd.DataFrame, method: str, neutral_type: str, view: str) -> dict[str, Any]:
    raw_set, cf_set = set(raw["ticker"]), set(cf["ticker"])
    removed = raw[raw["ticker"].isin(raw_set - cf_set)]
    added = cf[cf["ticker"].isin(cf_set - raw_set)]
    raw_avg = raw["final_score"].mean()
    cf_avg = cf["final_score"].mean()
    return {
        "method": method, "neutralization_type": neutral_type, "view": view,
        "raw_avg_final_score": raw_avg, "counterfactual_avg_final_score": cf_avg,
        "score_sacrifice": raw_avg - cf_avg,
        "removed_avg_final_score": removed["final_score"].mean() if len(removed) else "",
        "added_avg_final_score": added["final_score"].mean() if len(added) else "",
        "notes": "positive score_sacrifice means lower average raw D score after neutralization",
    }


def strategy_overlap(portfolio: str, view: str, cf: pd.DataFrame, rankings: dict[str, dict[str, pd.DataFrame]], raw_overlap_a1: int) -> list[dict[str, Any]]:
    rows = []
    cf_set = set(cf["ticker"])
    for strategy in STRATEGIES[:3]:
        other = rankings[strategy][view]
        other_set = set(other["ticker"]) if not other.empty else set()
        count = len(cf_set & other_set)
        rows.append({
            "portfolio": portfolio, "view": view, "comparison_strategy": strategy,
            "overlap_count": count, "overlap_ratio": count / len(cf_set) if cf_set else 0.0,
            "more_similar_to_a1_than_raw": bool(strategy == "A1_BASELINE_CONTROL" and count > raw_overlap_a1),
            "notes": "diagnostic_only",
        })
    return rows


def identity_row(portfolio: str, view: str, cf: pd.DataFrame, raw: pd.DataFrame) -> dict[str, Any]:
    avg_m = cf["momentum_score"].mean() if "momentum_score" in cf else np.nan
    raw_m = raw["momentum_score"].mean() if "momentum_score" in raw else np.nan
    avg_rs = cf["relative_momentum_score"].mean() if "relative_momentum_score" in cf else np.nan
    preserved = bool(pd.notna(avg_m) and pd.notna(raw_m) and avg_m >= raw_m * 0.90)
    return {"portfolio": portfolio, "view": view, "avg_momentum_score": avg_m, "avg_relative_momentum_score": avg_rs, "raw_avg_momentum_score": raw_m, "momentum_identity_preserved": preserved, "notes": "diagnostic_only"}


def classify(required_ok: bool, raw20: dict[str, Any], sector20: dict[str, Any], industry20: dict[str, Any], sector_overlap20: int, industry_overlap20: int, sector_sac: float, industry_sac: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, bool]]:
    rows = []
    flags = {"raw_sector_beta": False, "cross_sector": False, "large_sacrifice": False}
    if not required_ok:
        rows.append({"classification": "CLASSIFICATION_DATA_INSUFFICIENT", "severity": "BLOCKER", "evidence": "Missing sector/industry/final_score columns.", "research_only": True})
        rows.append({"classification": "SCORE_COLUMNS_INSUFFICIENT", "severity": "BLOCKER", "evidence": "Required score columns unavailable.", "research_only": True})
    raw_tech = float(raw20["technology_weight"])
    sector_tech = float(sector20["technology_weight"])
    industry_tech = float(industry20["technology_weight"])
    raw_semi = float(raw20["semiconductor_equipment_materials_weight"])
    if raw_tech >= .70 and sector_overlap20 <= 10 and sector_tech <= raw_tech - .20:
        flags["raw_sector_beta"] = True
        rows.append({"classification": "RAW_D_SECTOR_BETA_DOMINANT", "severity": "WARN", "evidence": f"raw_tech={raw_tech:.4f}; sector_neutral_tech={sector_tech:.4f}; overlap={sector_overlap20}", "research_only": True})
    if raw_semi >= .30 and industry_overlap20 <= 12:
        rows.append({"classification": "RAW_D_INDUSTRY_CLUSTER_DOMINANT", "severity": "WARN", "evidence": f"raw_semi_equipment={raw_semi:.4f}; industry_overlap={industry_overlap20}", "research_only": True})
    if sector_sac > 2.0 or industry_sac > 2.0:
        flags["large_sacrifice"] = True
        rows.append({"classification": "NEUTRALIZATION_CAUSES_LARGE_SCORE_SACRIFICE", "severity": "WARN", "evidence": f"sector_sacrifice={sector_sac:.4f}; industry_sacrifice={industry_sac:.4f}", "research_only": True})
    if sector_overlap20 >= 8 and sector_tech < raw_tech and not flags["large_sacrifice"]:
        flags["cross_sector"] = True
        rows.append({"classification": "D_HAS_CROSS_SECTOR_ALPHA_CANDIDATES", "severity": "INFO", "evidence": f"sector_overlap={sector_overlap20}; tech_reduction={raw_tech-sector_tech:.4f}", "research_only": True})
        rows.append({"classification": "NEUTRALIZATION_REDUCES_CONCENTRATION_WITH_ACCEPTABLE_SCORE_SACRIFICE", "severity": "INFO", "evidence": f"sector_sacrifice={sector_sac:.4f}", "research_only": True})
    if sector_overlap20 < 8 or industry_overlap20 < 8:
        rows.append({"classification": "COUNTERFACTUAL_TOO_DIFFERENT_FROM_D", "severity": "WARN", "evidence": f"sector_overlap={sector_overlap20}; industry_overlap={industry_overlap20}", "research_only": True})
    grouped: dict[str, list[str]] = {}
    rank = {"INFO": 0, "WARN": 1, "BLOCKER": 2}
    for row in rows:
        grouped.setdefault(row["classification"], []).append(row["severity"])
    summary = [{"classification": key, "event_count": len(vals), "max_severity": max(vals, key=lambda v: rank[v]), "notes": "diagnostic_only"} for key, vals in sorted(grouped.items())]
    return rows, summary, flags


def manifest_rows(out: Path) -> list[dict[str, Any]]:
    return [{"file": p.name, "path": p.as_posix(), "bytes": p.stat().st_size, "sha256": sha256(p), "research_only": True} for p in sorted(out.iterdir()) if p.is_file()]


def run(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    out = immutable_output(root, output_override)
    started = datetime.now(timezone.utc).isoformat()
    rankings, paths = load_rankings(root)
    class_path = discover_latest(root, ["outputs/v21/v21_078/*CLASSIFICATION_MASTER*.csv", "outputs/v21/v21_076/*CLASSIFICATION_MASTER*.csv"], {"ticker"})
    classification = read_frame(class_path)
    if not classification.empty and "ticker" in classification:
        classification["ticker"] = classification["ticker"].astype(str).str.upper().str.strip()
    inputs = [
        inventory(root, "v21_111_summary", root / V111_REL / "V21.111_D_FAILURE_MODE_DECOMPOSITION_SUMMARY.json", "prior V21.111 read-only summary"),
        inventory(root, "v21_111_r1_summary", root / R1_REL / "V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT_SUMMARY.json", "prior R1 read-only summary"),
        inventory(root, "classification_master", class_path, "sector/industry classification source"),
    ]
    for key, path in paths.items():
        inputs.append(inventory(root, key, path, "V21.108 archived ranking source"))
    for strategy in STRATEGIES:
        inputs.append(inventory(root, f"{strategy}_warnings", root / ARCHIVE_REL / strategy / "warnings.csv", "warning preservation source"))

    aug = {s: {v: augment(rankings[s][v], classification) for v in ["top20", "top50", "full"]} for s in STRATEGIES}
    d_full = eligible_universe(aug["D_WEIGHT_OPTIMIZED_R1"]["full"])
    required_ok = {"ticker", "final_score", "sector", "industry", "rank"}.issubset(d_full.columns) and not d_full[["sector", "industry", "final_score"]].isna().all().any()
    raw20 = add_diag_flags(topn(aug["D_WEIGHT_OPTIMIZED_R1"]["top20"], 20), "RAW_D_BASELINE_PRESERVED")
    raw50 = add_diag_flags(topn(aug["D_WEIGHT_OPTIMIZED_R1"]["top50"], 50), "RAW_D_BASELINE_PRESERVED")
    sector_pct = percentile_ranking(d_full, "sector", "SECTOR_WITHIN_PERCENTILE")
    industry_pct = percentile_ranking(d_full, "industry", "INDUSTRY_WITHIN_PERCENTILE")
    sector_q20 = quota_selection(d_full, "sector", 20, "SECTOR_UNIVERSE_QUOTA_TOP20")
    sector_q50 = quota_selection(d_full, "sector", 50, "SECTOR_UNIVERSE_QUOTA_TOP50")
    industry_q20 = quota_selection(d_full, "industry", 20, "INDUSTRY_UNIVERSE_QUOTA_TOP20")
    industry_q50 = quota_selection(d_full, "industry", 50, "INDUSTRY_UNIVERSE_QUOTA_TOP50")

    outputs: dict[str, list[dict[str, Any]]] = {
        "input_inventory.csv": inputs,
        "raw_d_top20.csv": raw20.to_dict("records"),
        "raw_d_top50.csv": raw50.to_dict("records"),
        "d_sector_neutral_percentile_ranking.csv": sector_pct.to_dict("records"),
        "d_sector_quota_counterfactual_top20.csv": sector_q20.to_dict("records"),
        "d_sector_quota_counterfactual_top50.csv": sector_q50.to_dict("records"),
        "d_industry_neutral_percentile_ranking.csv": industry_pct.to_dict("records"),
        "d_industry_quota_counterfactual_top20.csv": industry_q20.to_dict("records"),
        "d_industry_quota_counterfactual_top50.csv": industry_q50.to_dict("records"),
    }
    raw_a1_20_overlap = len(set(raw20["ticker"]) & set(aug["A1_BASELINE_CONTROL"]["top20"]["ticker"]))
    raw_a1_50_overlap = len(set(raw50["ticker"]) & set(aug["A1_BASELINE_CONTROL"]["top50"]["ticker"]))
    outputs["raw_vs_sector_neutral_overlap.csv"] = [overlap(raw20, sector_q20, "SECTOR_UNIVERSE_QUOTA", "top20"), overlap(raw50, sector_q50, "SECTOR_UNIVERSE_QUOTA", "top50")]
    outputs["raw_vs_industry_neutral_overlap.csv"] = [overlap(raw20, industry_q20, "INDUSTRY_UNIVERSE_QUOTA", "top20"), overlap(raw50, industry_q50, "INDUSTRY_UNIVERSE_QUOTA", "top50")]
    outputs["displacement_top20.csv"] = displacement(raw20, sector_q20, "SECTOR_UNIVERSE_QUOTA", "sector", "top20") + displacement(raw20, industry_q20, "INDUSTRY_UNIVERSE_QUOTA", "industry", "top20")
    outputs["displacement_top50.csv"] = displacement(raw50, sector_q50, "SECTOR_UNIVERSE_QUOTA", "sector", "top50") + displacement(raw50, industry_q50, "INDUSTRY_UNIVERSE_QUOTA", "industry", "top50")
    outputs["score_sacrifice_summary.csv"] = [
        sacrifice(raw20, sector_q20, "SECTOR_UNIVERSE_QUOTA", "sector", "top20"),
        sacrifice(raw50, sector_q50, "SECTOR_UNIVERSE_QUOTA", "sector", "top50"),
        sacrifice(raw20, industry_q20, "INDUSTRY_UNIVERSE_QUOTA", "industry", "top20"),
        sacrifice(raw50, industry_q50, "INDUSTRY_UNIVERSE_QUOTA", "industry", "top50"),
    ]
    portfolios = {
        "RAW_D": {"top20": raw20, "top50": raw50},
        "SECTOR_NEUTRAL_QUOTA": {"top20": sector_q20, "top50": sector_q50},
        "INDUSTRY_NEUTRAL_QUOTA": {"top20": industry_q20, "top50": industry_q50},
        "SECTOR_NEUTRAL_PERCENTILE": {"top20": topn_counterfactual(sector_pct, 20), "top50": topn_counterfactual(sector_pct, 50)},
        "INDUSTRY_NEUTRAL_PERCENTILE": {"top20": topn_counterfactual(industry_pct, 20), "top50": topn_counterfactual(industry_pct, 50)},
    }
    conc, exposure, xs, identity = [], [], [], []
    for pname, views in portfolios.items():
        for view, frame in views.items():
            a1 = aug["A1_BASELINE_CONTROL"][view]
            conc.append(concentration_row(pname, view, frame, a1))
            exposure.extend(exposure_rows(pname, view, frame))
            raw_a1 = raw_a1_20_overlap if view == "top20" else raw_a1_50_overlap
            xs.extend(strategy_overlap(pname, view, frame, aug, raw_a1))
            identity.append(identity_row(pname, view, frame, raw20 if view == "top20" else raw50))
    outputs["concentration_reduction_summary.csv"] = conc
    outputs["counterfactual_exposure_comparison.csv"] = exposure
    outputs["counterfactual_vs_A1_B_C_overlap.csv"] = xs
    outputs["counterfactual_identity_summary.csv"] = identity

    raw20c = next(r for r in conc if r["portfolio"] == "RAW_D" and r["view"] == "top20")
    raw50c = next(r for r in conc if r["portfolio"] == "RAW_D" and r["view"] == "top50")
    sector20c = next(r for r in conc if r["portfolio"] == "SECTOR_NEUTRAL_QUOTA" and r["view"] == "top20")
    industry20c = next(r for r in conc if r["portfolio"] == "INDUSTRY_NEUTRAL_QUOTA" and r["view"] == "top20")
    sector_overlap20 = outputs["raw_vs_sector_neutral_overlap.csv"][0]["overlap_count"]
    industry_overlap20 = outputs["raw_vs_industry_neutral_overlap.csv"][0]["overlap_count"]
    sector_sac = float(outputs["score_sacrifice_summary.csv"][0]["score_sacrifice"])
    industry_sac = float(outputs["score_sacrifice_summary.csv"][2]["score_sacrifice"])
    classes, class_summary, flags = classify(required_ok, raw20c, sector20c, industry20c, sector_overlap20, industry_overlap20, sector_sac, industry_sac)
    outputs["neutralization_diagnostic_classification.csv"] = classes
    outputs["neutralization_diagnostic_summary.csv"] = class_summary

    if not required_ok:
        final_status, decision = "PARTIAL_PASS", "D_NEUTRAL_COUNTERFACTUAL_PARTIAL_MISSING_REQUIRED_COLUMNS"
    elif flags["large_sacrifice"]:
        final_status, decision = "WARN", "D_NEUTRAL_COUNTERFACTUAL_WARN_LARGE_SCORE_SACRIFICE"
    elif flags["raw_sector_beta"]:
        final_status, decision = "WARN", "D_NEUTRAL_COUNTERFACTUAL_WARN_RAW_D_SECTOR_BETA_DOMINANT"
    else:
        final_status, decision = "PASS", "D_NEUTRAL_COUNTERFACTUAL_PASS_CROSS_SECTOR_SIGNAL_PRESENT"

    for name, fields in CSV_FIELDS.items():
        write_csv(out / name, outputs.get(name, []), fields)

    warning_blob = ""
    for strategy in STRATEGIES:
        p = root / ARCHIVE_REL / strategy / "warnings.csv"
        if p.is_file():
            warning_blob += read_frame(p).to_csv(index=False)
    preserved = [f"{token} warning present in V21.108 warning inputs and preserved read-only." for token in ["BITF", "PSTG"] if token in warning_blob]
    if not preserved:
        preserved = ["No BITF/PSTG token found in available warning files."]
    next_step = (
        "repair ranking schema/classification columns before continuing" if not required_ok else
        "wait for V21.109 forward maturity, then test V21.114 risk-control diagnostic only" if flags["raw_sector_beta"] else
        "continue V21.109 forward maturity tracking"
    )
    summary = {
        "stage": STAGE, "generated_at_utc": started, "final_status": final_status, "decision": decision,
        "research_only": True, "official_adoption_allowed": False, "broker_action_allowed": False,
        "protected_outputs_modified": False, "official_outputs_modified": False, "source_ranking_files_modified": False,
        "model_weights_changed": False, "trade_instructions_produced": False,
        "output_dir": out.relative_to(root).as_posix() if out.is_relative_to(root) else str(out),
        "required_columns_available": required_ok,
        "raw_d_top20_tech_weight": raw20c["technology_weight"],
        "raw_d_top50_tech_weight": raw50c["technology_weight"],
        "raw_d_top20_top_industry": raw20c["top_industry_name"],
        "raw_d_top20_top_industry_weight": raw20c["top_industry_weight"],
        "sector_neutral_top20_overlap_with_raw_d": sector_overlap20,
        "industry_neutral_top20_overlap_with_raw_d": industry_overlap20,
        "sector_neutral_tech_weight": sector20c["technology_weight"],
        "industry_neutral_tech_weight": industry20c["technology_weight"],
        "sector_neutral_score_sacrifice": sector_sac,
        "industry_neutral_score_sacrifice": industry_sac,
        "raw_d_sector_beta_dominant": flags["raw_sector_beta"],
        "cross_sector_signal_present": flags["cross_sector"],
        "large_score_sacrifice_warning": flags["large_sacrifice"],
        "warnings": preserved,
        "next_recommended_step": next_step,
    }
    write_json(out / SUMMARY, summary)
    report = [
        f"# {STAGE}", "",
        f"FINAL_STATUS: {final_status}",
        f"DECISION: {decision}", "",
        "## Controls",
        "- research_only = true",
        "- official_adoption_allowed = false",
        "- broker_action_allowed = false",
        "- protected_outputs_modified = false",
        "- Counterfactual rankings are diagnostic-only and are not live filters, caps, trades, or official ranks.", "",
        "## Input Inventory",
        f"- Inventory rows: {len(inputs)}", "",
        "## Raw D Baseline",
        f"- Top20 Technology weight: {raw20c['technology_weight']}",
        f"- Top50 Technology weight: {raw50c['technology_weight']}",
        f"- Top20 top industry: {raw20c['top_industry_name']} ({raw20c['top_industry_weight']})", "",
        "## Sector-Neutral Counterfactual",
        f"- Top20 overlap with raw D: {sector_overlap20}",
        f"- Technology weight: {sector20c['technology_weight']}",
        f"- Score sacrifice: {sector_sac}", "",
        "## Industry-Neutral Counterfactual",
        f"- Top20 overlap with raw D: {industry_overlap20}",
        f"- Technology weight: {industry20c['technology_weight']}",
        f"- Score sacrifice: {industry_sac}", "",
        "## Diagnostics",
        "- See overlap, displacement, score sacrifice, concentration reduction, cross-strategy overlap, and identity CSVs.",
        f"- Classification rows: {len(classes)}", "",
        "## Preserved Warnings",
        *[f"- {w}" for w in preserved], "",
        "## Next Recommended Step",
        f"- {next_step}",
    ]
    (out / REPORT).write_text("\n".join(report) + "\n", encoding="utf-8")
    write_csv(out / MANIFEST, manifest_rows(out), ["file", "path", "bytes", "sha256", "research_only"])
    write_csv(out / MANIFEST, manifest_rows(out), ["file", "path", "bytes", "sha256", "research_only"])

    print(f"FINAL_STATUS: {final_status}")
    print(f"DECISION: {decision}")
    print(f"RAW_D_TOP20_TECH_WEIGHT: {raw20c['technology_weight']}")
    print(f"RAW_D_TOP50_TECH_WEIGHT: {raw50c['technology_weight']}")
    print(f"RAW_D_TOP20_TOP_INDUSTRY: {raw20c['top_industry_name']}")
    print(f"RAW_D_TOP20_TOP_INDUSTRY_WEIGHT: {raw20c['top_industry_weight']}")
    print(f"SECTOR_NEUTRAL_TOP20_OVERLAP_WITH_RAW_D: {sector_overlap20}")
    print(f"INDUSTRY_NEUTRAL_TOP20_OVERLAP_WITH_RAW_D: {industry_overlap20}")
    print(f"SECTOR_NEUTRAL_TECH_WEIGHT: {sector20c['technology_weight']}")
    print(f"INDUSTRY_NEUTRAL_TECH_WEIGHT: {industry20c['technology_weight']}")
    print(f"SECTOR_NEUTRAL_SCORE_SACRIFICE: {sector_sac}")
    print(f"INDUSTRY_NEUTRAL_SCORE_SACRIFICE: {industry_sac}")
    print(f"RAW_D_SECTOR_BETA_DOMINANT: {str(flags['raw_sector_beta']).lower()}")
    print(f"CROSS_SECTOR_SIGNAL_PRESENT: {str(flags['cross_sector']).lower()}")
    print(f"LARGE_SCORE_SACRIFICE_WARNING: {str(flags['large_sacrifice']).lower()}")
    print("RESEARCH_ONLY: true")
    print("OFFICIAL_ADOPTION_ALLOWED: false")
    print("BROKER_ACTION_ALLOWED: false")
    print("PROTECTED_OUTPUTS_MODIFIED: false")
    print(f"REPORT_PATH: {(out / REPORT).relative_to(root).as_posix() if (out / REPORT).is_relative_to(root) else out / REPORT}")
    print(f"SUMMARY_PATH: {(out / SUMMARY).relative_to(root).as_posix() if (out / SUMMARY).is_relative_to(root) else out / SUMMARY}")
    print(f"MANIFEST_PATH: {(out / MANIFEST).relative_to(root).as_posix() if (out / MANIFEST).is_relative_to(root) else out / MANIFEST}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    run(args.root.resolve(), args.output_dir)


if __name__ == "__main__":
    main()
