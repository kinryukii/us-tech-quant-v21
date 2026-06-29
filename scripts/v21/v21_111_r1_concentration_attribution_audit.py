#!/usr/bin/env python
"""V21.111-R1 research-only concentration attribution audit for D."""

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


STAGE = "V21.111-R1_CONCENTRATION_ATTRIBUTION_AUDIT"
ARCHIVE_REL = Path("outputs/v21/V21.108_latest_data_multi_strategy_rerun/R2_archived_latest_strategy_rankings")
V111_REL = Path("outputs/v21/V21.111_D_FAILURE_MODE_DECOMPOSITION")
OUTPUT_REL = Path("outputs/v21/V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT")
STRATEGIES = [
    "A1_BASELINE_CONTROL",
    "B_STATIC_MOMENTUM_BLEND",
    "C_DYNAMIC_MOMENTUM_BLEND",
    "D_WEIGHT_OPTIMIZED_R1",
]
SUMMARY_JSON = "V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT_SUMMARY.json"
REPORT_MD = "V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT_REPORT.md"
MANIFEST_CSV = "V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT_MANIFEST.csv"

CSV_SCHEMAS: dict[str, list[str]] = {
    "input_inventory.csv": ["source_name", "path", "exists", "row_count", "hash", "notes"],
    "sector_concentration_top20.csv": ["strategy", "sector", "count", "weight", "rank", "top_sector_name", "top_sector_weight", "sector_hhi", "notes"],
    "sector_concentration_top50.csv": ["strategy", "sector", "count", "weight", "rank", "top_sector_name", "top_sector_weight", "sector_hhi", "notes"],
    "industry_concentration_top20.csv": ["strategy", "industry", "count", "weight", "rank", "top_industry_name", "top_industry_weight", "industry_hhi", "notes"],
    "industry_concentration_top50.csv": ["strategy", "industry", "count", "weight", "rank", "top_industry_name", "top_industry_weight", "industry_hhi", "notes"],
    "concentration_comparison_A1_B_C_D.csv": [
        "strategy", "view", "count", "top_sector_name", "top_sector_weight", "sector_hhi",
        "top_industry_name", "top_industry_weight", "industry_hhi", "top_theme_name",
        "top_theme_weight", "classification_coverage_ratio", "notes",
    ],
    "d_only_vs_a1_concentration.csv": [
        "comparison", "view", "ticker_count", "tickers", "top_sector_name", "top_sector_weight",
        "top_industry_name", "top_industry_weight", "avg_final_score", "avg_base_score",
        "avg_momentum_score", "avg_rs", "avg_volatility", "stale_or_missing_ratio",
        "data_trust_warning_ratio", "notes",
    ],
    "d_only_vs_b_c_concentration.csv": [
        "comparison", "view", "ticker_count", "tickers", "top_sector_name", "top_sector_weight",
        "top_industry_name", "top_industry_weight", "avg_final_score", "avg_base_score",
        "avg_momentum_score", "avg_rs", "avg_volatility", "stale_or_missing_ratio",
        "data_trust_warning_ratio", "notes",
    ],
    "d_only_ticker_profile.csv": [
        "comparison", "view", "ticker", "rank", "sector", "industry", "theme_tags",
        "final_score", "base_score", "momentum_score", "rs_score", "volatility_score",
        "latest_price_date", "warning_flags", "data_warning_label", "stale_or_missing_flag",
        "data_trust_warning_flag", "notes",
    ],
    "score_concentration_attribution.csv": [
        "view", "score_source", "top_sector_name", "top_sector_average", "rest_average",
        "top_sector_minus_rest", "top_sector_selected_count", "rest_selected_count",
        "top_sector_score_share", "dominance_type", "notes",
    ],
    "sector_score_advantage.csv": [
        "strategy", "view", "sector", "count", "avg_final_score", "avg_base_score",
        "avg_momentum_score", "avg_rs", "avg_volatility", "score_advantage_vs_rest",
        "score_advantage_vs_universe", "notes",
    ],
    "industry_score_advantage.csv": [
        "strategy", "view", "industry", "count", "avg_final_score", "avg_base_score",
        "avg_momentum_score", "avg_rs", "avg_volatility", "score_advantage_vs_rest",
        "score_advantage_vs_universe", "notes",
    ],
    "eligible_universe_sector_baseline.csv": ["sector", "eligible_count", "eligible_weight", "hhi", "top_sector_name", "top_sector_weight", "notes"],
    "eligible_universe_industry_baseline.csv": ["industry", "eligible_count", "eligible_weight", "hhi", "top_industry_name", "top_industry_weight", "notes"],
    "d_overweight_vs_universe.csv": ["view", "sector", "d_weight", "universe_weight", "overweight", "material_overweight_flag", "notes"],
    "concentration_cause_classification.csv": ["cause", "view", "severity", "evidence", "research_only"],
    "concentration_cause_summary.csv": ["cause", "event_count", "max_severity", "notes"],
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


def inventory_row(source_name: str, root: Path, path: Path | None, notes: str) -> dict[str, Any]:
    if not path:
        return {"source_name": source_name, "path": "", "exists": False, "row_count": 0, "hash": "", "notes": notes}
    resolved = path if path.is_absolute() else root / path
    rel = resolved.relative_to(root).as_posix() if resolved.exists() and resolved.is_relative_to(root) else str(path)
    if not resolved.is_file():
        return {"source_name": source_name, "path": rel, "exists": False, "row_count": 0, "hash": "", "notes": notes}
    try:
        rows = len(pd.read_csv(resolved, low_memory=False))
    except Exception as exc:
        rows = 0
        notes = f"{notes}; read_error={exc}"
    return {"source_name": source_name, "path": rel, "exists": True, "row_count": rows, "hash": sha256(resolved), "notes": notes}


def discover_latest(root: Path, patterns: list[str], required_cols: set[str] | None = None) -> Path | None:
    candidates: list[tuple[float, Path]] = []
    for pattern in patterns:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            if required_cols:
                try:
                    cols = set(pd.read_csv(path, nrows=1).columns)
                except Exception:
                    continue
                if not required_cols.issubset(cols):
                    continue
            candidates.append((path.stat().st_mtime, path))
    return max(candidates)[1] if candidates else None


def immutable_output(root: Path, override: Path | None) -> Path:
    output = (override if override and override.is_absolute() else root / (override or OUTPUT_REL)).resolve()
    output.mkdir(parents=True, exist_ok=True)
    allowed = {*CSV_SCHEMAS.keys(), SUMMARY_JSON, REPORT_MD, MANIFEST_CSV}
    unmanaged = [p.name for p in output.iterdir() if p.is_file() and p.name not in allowed]
    if unmanaged:
        raise RuntimeError(f"Output directory contains unmanaged files: {unmanaged}")
    return output


def num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series([np.nan] * len(frame), index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def hhi(counts: pd.Series) -> float:
    values = pd.to_numeric(counts, errors="coerce").dropna()
    total = values.sum()
    if total <= 0:
        return 0.0
    shares = values / total
    return float((shares ** 2).sum())


def load_rankings(root: Path) -> tuple[dict[str, dict[str, pd.DataFrame]], dict[str, Path]]:
    frames: dict[str, dict[str, pd.DataFrame]] = {}
    paths: dict[str, Path] = {}
    for strategy in STRATEGIES:
        frames[strategy] = {}
        for view, filename in {"top20": "top20_ranking.csv", "top50": "top50_ranking.csv", "full": "full_ranking.csv"}.items():
            path = root / ARCHIVE_REL / strategy / filename
            paths[f"{strategy}_{view}"] = path
            frame = read_frame(path)
            if not frame.empty and "ticker" in frame:
                frame["strategy"] = strategy
                frame["view"] = view
                frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
            frames[strategy][view] = frame
    return frames, paths


def augment(frame: pd.DataFrame, classification: pd.DataFrame, explainability: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if result.empty or "ticker" not in result:
        return result
    if not classification.empty and "ticker" in classification:
        cls_cols = [
            c for c in [
                "ticker", "sector", "industry", "sub_industry", "theme_tags", "asset_type",
                "is_etf", "classification_quality_flag", "low_confidence_label",
                "source_reliability_score", "pit_leakage_warning",
            ] if c in classification
        ]
        cls = classification[cls_cols].copy().drop_duplicates("ticker", keep="last")
        cls["ticker"] = cls["ticker"].astype(str).str.upper().str.strip()
        result = result.merge(cls, on="ticker", how="left")
    if not explainability.empty and "ticker" in explainability:
        exp_cols = [
            c for c in [
                "ticker", "technical__relative_strength", "technical__volatility",
                "risk__volatility_penalty", "data_trust_score_raw", "data_trust__warning_flag",
                "component_coverage_ratio",
            ] if c in explainability
        ]
        if len(exp_cols) > 1:
            exp = explainability[exp_cols].copy().drop_duplicates("ticker", keep="last")
            exp["ticker"] = exp["ticker"].astype(str).str.upper().str.strip()
            result = result.merge(exp, on="ticker", how="left")
    return result


def top_bucket(frame: pd.DataFrame, column: str) -> tuple[str, float, pd.Series]:
    if frame.empty or column not in frame:
        return "MISSING", 0.0, pd.Series(dtype=float)
    values = frame[column].fillna("UNCLASSIFIED").astype(str)
    counts = values.value_counts(dropna=False)
    if counts.empty:
        return "MISSING", 0.0, counts
    return str(counts.index[0]), float(counts.iloc[0] / len(frame)), counts


def concentration_breakdown(frame: pd.DataFrame, column: str, strategy: str, label: str) -> list[dict[str, Any]]:
    name, weight, counts = top_bucket(frame, column)
    metric_hhi = hhi(counts)
    rows = []
    for idx, (bucket, count) in enumerate(counts.items(), start=1):
        row = {
            "strategy": strategy,
            label: bucket,
            "count": int(count),
            "weight": float(count / len(frame)) if len(frame) else 0.0,
            "rank": idx,
            f"top_{label}_name": name,
            f"top_{label}_weight": weight,
            f"{label}_hhi": metric_hhi,
            "notes": "research_only",
        }
        rows.append(row)
    return rows


def theme_top(frame: pd.DataFrame) -> tuple[str, float]:
    if frame.empty or "theme_tags" not in frame:
        return "MISSING", 0.0
    exploded: list[str] = []
    for value in frame["theme_tags"].fillna("UNCLASSIFIED").astype(str):
        parts = [part.strip() for part in value.replace("|", ",").split(",") if part.strip()]
        exploded.extend(parts or ["UNCLASSIFIED"])
    if not exploded:
        return "MISSING", 0.0
    counts = pd.Series(exploded).value_counts()
    return str(counts.index[0]), float(counts.iloc[0] / len(frame))


def comparison_row(strategy: str, view: str, frame: pd.DataFrame) -> dict[str, Any]:
    sector, sector_weight, sector_counts = top_bucket(frame, "sector")
    industry, industry_weight, industry_counts = top_bucket(frame, "industry")
    theme, theme_weight = theme_top(frame)
    coverage = 0.0
    if "sector" in frame and "industry" in frame and len(frame):
        coverage = float((frame["sector"].notna() & frame["industry"].notna()).mean())
    return {
        "strategy": strategy, "view": view, "count": len(frame),
        "top_sector_name": sector, "top_sector_weight": sector_weight, "sector_hhi": hhi(sector_counts),
        "top_industry_name": industry, "top_industry_weight": industry_weight, "industry_hhi": hhi(industry_counts),
        "top_theme_name": theme, "top_theme_weight": theme_weight,
        "classification_coverage_ratio": coverage,
        "notes": "research_only_current_snapshot",
    }


def stale_flag(frame: pd.DataFrame) -> pd.Series:
    flag = pd.Series(False, index=frame.index)
    if "latest_price_date" in frame:
        latest = pd.to_datetime(frame["latest_price_date"], errors="coerce")
        flag = flag | latest.isna() | (latest < latest.max())
    for col in ["warning_flags", "data_warning_label", "price_data_status"]:
        if col in frame:
            flag = flag | frame[col].astype(str).str.contains("STALE|MISSING|BITF|PSTG", case=False, na=False)
    return flag


def data_trust_flag(frame: pd.DataFrame) -> pd.Series:
    flag = pd.Series(False, index=frame.index)
    for col in ["data_trust__warning_flag", "pit_leakage_warning", "low_confidence_label"]:
        if col in frame:
            flag = flag | frame[col].map(truth)
    for col in ["data_warning_label", "warning_flags"]:
        if col in frame:
            flag = flag | frame[col].astype(str).replace("nan", "").str.strip().ne("")
    return flag


def d_only_summary(d: pd.DataFrame, other: pd.DataFrame, comparison: str, view: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    other_tickers = set(other["ticker"]) if not other.empty and "ticker" in other else set()
    d_only = d[~d["ticker"].isin(other_tickers)].copy() if not d.empty else pd.DataFrame()
    sector, sector_weight, _ = top_bucket(d_only, "sector")
    industry, industry_weight, _ = top_bucket(d_only, "industry")
    rs_col = "technical__relative_strength" if "technical__relative_strength" in d_only else "relative_momentum_score"
    vol_col = "technical__volatility" if "technical__volatility" in d_only else "risk__volatility_penalty"
    stale = stale_flag(d_only) if not d_only.empty else pd.Series(dtype=bool)
    trust = data_trust_flag(d_only) if not d_only.empty else pd.Series(dtype=bool)
    summary = {
        "comparison": comparison, "view": view, "ticker_count": len(d_only),
        "tickers": ",".join(d_only["ticker"].astype(str).tolist()) if not d_only.empty else "",
        "top_sector_name": sector, "top_sector_weight": sector_weight,
        "top_industry_name": industry, "top_industry_weight": industry_weight,
        "avg_final_score": num(d_only, "final_score").mean() if not d_only.empty else "",
        "avg_base_score": num(d_only, "base_score").mean() if not d_only.empty else "",
        "avg_momentum_score": num(d_only, "momentum_score").mean() if not d_only.empty else "",
        "avg_rs": num(d_only, rs_col).mean() if not d_only.empty else "",
        "avg_volatility": num(d_only, vol_col).mean() if not d_only.empty else "",
        "stale_or_missing_ratio": float(stale.mean()) if len(stale) else 0.0,
        "data_trust_warning_ratio": float(trust.mean()) if len(trust) else 0.0,
        "notes": "D-only relative to comparison strategy or strategy union",
    }
    profiles = []
    for _, row in d_only.iterrows():
        profiles.append({
            "comparison": comparison, "view": view, "ticker": row.get("ticker", ""),
            "rank": row.get("rank", ""), "sector": row.get("sector", ""),
            "industry": row.get("industry", ""), "theme_tags": row.get("theme_tags", ""),
            "final_score": row.get("final_score", ""), "base_score": row.get("base_score", ""),
            "momentum_score": row.get("momentum_score", ""),
            "rs_score": row.get(rs_col, ""), "volatility_score": row.get(vol_col, ""),
            "latest_price_date": row.get("latest_price_date", ""),
            "warning_flags": row.get("warning_flags", ""),
            "data_warning_label": row.get("data_warning_label", ""),
            "stale_or_missing_flag": bool(stale.loc[row.name]) if row.name in stale.index else False,
            "data_trust_warning_flag": bool(trust.loc[row.name]) if row.name in trust.index else False,
            "notes": "research_only_no_rank_mutation",
        })
    return summary, profiles


def score_rows(strategy: str, view: str, selected: pd.DataFrame, universe: pd.DataFrame, column: str, label: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sector_rows: list[dict[str, Any]] = []
    industry_rows: list[dict[str, Any]] = []
    for bucket_col, out in [("sector", sector_rows), ("industry", industry_rows)]:
        if selected.empty or bucket_col not in selected:
            continue
        for bucket, group in selected.groupby(bucket_col, dropna=False):
            rest = selected[selected[bucket_col].ne(bucket)]
            uni = universe[universe[bucket_col].eq(bucket)] if bucket_col in universe else pd.DataFrame()
            out.append({
                "strategy": strategy, "view": view, bucket_col: clean(bucket) or "UNCLASSIFIED",
                "count": len(group),
                "avg_final_score": num(group, "final_score").mean(),
                "avg_base_score": num(group, "base_score").mean(),
                "avg_momentum_score": num(group, "momentum_score").mean(),
                "avg_rs": num(group, "relative_momentum_score").mean(),
                "avg_volatility": num(group, "risk__volatility_penalty").mean() if "risk__volatility_penalty" in group else "",
                "score_advantage_vs_rest": num(group, column).mean() - num(rest, column).mean() if len(rest) else "",
                "score_advantage_vs_universe": num(group, column).mean() - num(uni, column).mean() if len(uni) else "",
                "notes": f"{label}_score_advantage",
            })
    return sector_rows, industry_rows


def score_attribution(d: pd.DataFrame, universe: pd.DataFrame, view: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    top_sector, _, _ = top_bucket(d, "sector")
    for column, label in [("final_score", "final"), ("momentum_score", "momentum"), ("base_score", "base")]:
        if column not in d or "sector" not in d:
            continue
        top = d[d["sector"].fillna("UNCLASSIFIED").astype(str).eq(top_sector)]
        rest = d[~d.index.isin(top.index)]
        total = num(d, column).sum()
        top_sum = num(top, column).sum()
        advantage = num(top, column).mean() - num(rest, column).mean() if len(rest) else np.nan
        dominance = "COUNT_DOMINANCE"
        if pd.notna(advantage) and advantage > 2.0:
            dominance = "SCORE_ADVANTAGE_AND_COUNT"
        elif pd.notna(advantage) and advantage > 0:
            dominance = "MILD_SCORE_ADVANTAGE_AND_COUNT"
        rows.append({
            "view": view, "score_source": label, "top_sector_name": top_sector,
            "top_sector_average": num(top, column).mean(),
            "rest_average": num(rest, column).mean() if len(rest) else "",
            "top_sector_minus_rest": advantage if pd.notna(advantage) else "",
            "top_sector_selected_count": len(top), "rest_selected_count": len(rest),
            "top_sector_score_share": float(top_sum / total) if total else "",
            "dominance_type": dominance,
            "notes": "D selected holdings only; no score mutation",
        })
    return rows


def universe_baseline(universe: pd.DataFrame, column: str, label: str) -> list[dict[str, Any]]:
    if universe.empty or column not in universe:
        return []
    values = universe[column].fillna("UNCLASSIFIED").astype(str)
    counts = values.value_counts()
    top_name = str(counts.index[0]) if len(counts) else "MISSING"
    top_weight = float(counts.iloc[0] / len(universe)) if len(counts) else 0.0
    metric_hhi = hhi(counts)
    rows = []
    for bucket, count in counts.items():
        rows.append({
            label: bucket, "eligible_count": int(count),
            "eligible_weight": float(count / len(universe)),
            "hhi": metric_hhi,
            f"top_{label}_name": top_name,
            f"top_{label}_weight": top_weight,
            "notes": "eligible_flag true where column exists; otherwise full D ranking universe",
        })
    return rows


def overweight_rows(d_views: dict[str, pd.DataFrame], universe: pd.DataFrame) -> list[dict[str, Any]]:
    if universe.empty or "sector" not in universe:
        return []
    uni_weights = universe["sector"].fillna("UNCLASSIFIED").astype(str).value_counts(normalize=True).to_dict()
    rows = []
    for view, frame in d_views.items():
        if frame.empty or "sector" not in frame:
            continue
        d_weights = frame["sector"].fillna("UNCLASSIFIED").astype(str).value_counts(normalize=True).to_dict()
        for sector, d_weight in sorted(d_weights.items()):
            u_weight = float(uni_weights.get(sector, 0.0))
            overweight = float(d_weight - u_weight)
            rows.append({
                "view": view, "sector": sector, "d_weight": d_weight,
                "universe_weight": u_weight, "overweight": overweight,
                "material_overweight_flag": overweight >= 0.20,
                "notes": "D selected weight minus eligible universe weight",
            })
    return rows


def classify(summary_rows: list[dict[str, Any]], d_only_rows: list[dict[str, Any]], score_attr: list[dict[str, Any]], classification_available: bool, universe_top_sector_weight: float, overweights: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, bool]]:
    events: list[dict[str, Any]] = []
    flags = {"d_only": False, "score": False, "classification": classification_available}
    d_rows = [r for r in summary_rows if r["strategy"] == "D_WEIGHT_OPTIMIZED_R1"]
    for row in d_rows:
        view = row["view"]
        sector = clean(row["top_sector_name"])
        industry = clean(row["top_industry_name"])
        sector_weight = float(row["top_sector_weight"])
        industry_weight = float(row["top_industry_weight"])
        evidence = f"top_sector={sector}; weight={sector_weight:.4f}; top_industry={industry}; industry_weight={industry_weight:.4f}"
        if not classification_available:
            events.append({"cause": "CLASSIFICATION_DATA_INSUFFICIENT", "view": view, "severity": "BLOCKER", "evidence": "sector/industry classification unavailable or sparse", "research_only": True})
        if any(key in sector.lower() for key in ["technology", "information technology", "tech"]):
            events.append({"cause": "BROAD_TECH_CONCENTRATION", "view": view, "severity": "WARN" if sector_weight >= .50 else "INFO", "evidence": evidence, "research_only": True})
        if "semiconductor" in f"{sector} {industry}".lower():
            events.append({"cause": "SEMICONDUCTOR_CONCENTRATION", "view": view, "severity": "WARN" if sector_weight >= .50 or industry_weight >= .30 else "INFO", "evidence": evidence, "research_only": True})
        if any(key in f"{sector} {industry}".lower() for key in ["storage", "memory"]):
            events.append({"cause": "STORAGE_CONCENTRATION", "view": view, "severity": "WARN", "evidence": evidence, "research_only": True})
        if sector_weight <= universe_top_sector_weight + 0.05:
            events.append({"cause": "UNIVERSE_BASELINE_CONCENTRATED", "view": view, "severity": "INFO", "evidence": f"D sector weight={sector_weight:.4f}; universe top sector={universe_top_sector_weight:.4f}", "research_only": True})
    for row in d_only_rows:
        if float(row["top_sector_weight"]) >= .60 and int(row["ticker_count"]) > 0:
            flags["d_only"] = True
            events.append({"cause": "D_ONLY_NAMES_CONCENTRATED", "view": row["view"], "severity": "WARN", "evidence": f"{row['comparison']} top_sector={row['top_sector_name']} weight={row['top_sector_weight']}", "research_only": True})
    for row in score_attr:
        adv = row.get("top_sector_minus_rest")
        if clean(adv) and float(adv) > 0:
            cause = "MOMENTUM_SCORE_SECTOR_CLUSTERING" if row["score_source"] == "momentum" else "BASE_SCORE_SECTOR_CLUSTERING" if row["score_source"] == "base" else "SCORE_ADVANTAGE_CONCENTRATED"
            severity = "WARN" if float(adv) >= 2.0 else "INFO"
            if severity == "WARN":
                flags["score"] = True
            events.append({"cause": cause, "view": row["view"], "severity": severity, "evidence": f"{row['score_source']} top_sector_minus_rest={adv}", "research_only": True})
    for row in overweights:
        if row["material_overweight_flag"]:
            events.append({"cause": "SCORE_ADVANTAGE_CONCENTRATED", "view": row["view"], "severity": "WARN", "evidence": f"{row['sector']} overweight_vs_universe={row['overweight']}", "research_only": True})
    if not events:
        events.append({"cause": "CLASSIFICATION_DATA_INSUFFICIENT", "view": "", "severity": "INFO", "evidence": "No concentration cause identified from available columns", "research_only": True})
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(event["cause"], []).append(event)
    severity_rank = {"INFO": 0, "WARN": 1, "BLOCKER": 2}
    summary = []
    for cause, items in sorted(grouped.items()):
        max_sev = max((item["severity"] for item in items), key=lambda s: severity_rank[s])
        summary.append({"cause": cause, "event_count": len(items), "max_severity": max_sev, "notes": "research_only_cause_classification"})
    return events, summary, flags


def manifest_rows(output: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(output.iterdir()):
        if path.is_file():
            rows.append({"file": path.name, "path": path.as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path), "research_only": True})
    return rows


def run(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    output = immutable_output(root, output_override)
    started = datetime.now(timezone.utc).isoformat()
    rankings, ranking_paths = load_rankings(root)
    classification_path = discover_latest(root, ["outputs/v21/v21_078/*CLASSIFICATION_MASTER*.csv", "outputs/v21/v21_076/*CLASSIFICATION_MASTER*.csv"], {"ticker"})
    explainability_path = discover_latest(root, ["outputs/v21/explainability/*FACTOR_EXPLAINABILITY*.csv"], {"ticker"})
    v111_summary = root / V111_REL / "V21.111_D_FAILURE_MODE_DECOMPOSITION_SUMMARY.json"
    v111_report = root / V111_REL / "V21.111_D_FAILURE_MODE_DECOMPOSITION_REPORT.md"
    v111_manifest = root / V111_REL / "V21.111_D_FAILURE_MODE_DECOMPOSITION_MANIFEST.csv"
    warning_paths = {f"{strategy}_warnings": root / ARCHIVE_REL / strategy / "warnings.csv" for strategy in STRATEGIES}

    inventory = [
        inventory_row("v21_111_summary", root, v111_summary, "prior concentration warning summary"),
        inventory_row("v21_111_report", root, v111_report, "prior report read-only input"),
        inventory_row("v21_111_manifest", root, v111_manifest, "prior manifest read-only input"),
        inventory_row("classification_master", root, classification_path, "sector/industry/theme source"),
        inventory_row("factor_explainability", root, explainability_path, "optional RS/volatility/data trust source"),
    ]
    for key, path in ranking_paths.items():
        inventory.append(inventory_row(key, root, path, "V21.108-R2 archived ranking input"))
    for key, path in warning_paths.items():
        inventory.append(inventory_row(key, root, path, "warning preservation input"))

    classification = read_frame(classification_path)
    explainability = read_frame(explainability_path)
    if not classification.empty and "ticker" in classification:
        classification["ticker"] = classification["ticker"].astype(str).str.upper().str.strip()
    if not explainability.empty and "ticker" in explainability:
        explainability["ticker"] = explainability["ticker"].astype(str).str.upper().str.strip()

    augmented: dict[str, dict[str, pd.DataFrame]] = {}
    for strategy in STRATEGIES:
        augmented[strategy] = {}
        for view in ["top20", "top50", "full"]:
            augmented[strategy][view] = augment(rankings[strategy][view], classification, explainability)

    sector_top20: list[dict[str, Any]] = []
    sector_top50: list[dict[str, Any]] = []
    industry_top20: list[dict[str, Any]] = []
    industry_top50: list[dict[str, Any]] = []
    comparison: list[dict[str, Any]] = []
    for strategy in STRATEGIES:
        for view in ["top20", "top50"]:
            frame = augmented[strategy][view]
            comparison.append(comparison_row(strategy, view, frame))
            sector_rows = concentration_breakdown(frame, "sector", strategy, "sector")
            industry_rows = concentration_breakdown(frame, "industry", strategy, "industry")
            if view == "top20":
                sector_top20.extend(sector_rows)
                industry_top20.extend(industry_rows)
            else:
                sector_top50.extend(sector_rows)
                industry_top50.extend(industry_rows)

    d_only_a1: list[dict[str, Any]] = []
    d_only_bc: list[dict[str, Any]] = []
    d_only_profiles: list[dict[str, Any]] = []
    for view in ["top20", "top50"]:
        d_frame = augmented["D_WEIGHT_OPTIMIZED_R1"][view]
        a1_row, a1_profiles = d_only_summary(d_frame, augmented["A1_BASELINE_CONTROL"][view], "D_ONLY_VS_A1", view)
        d_only_a1.append(a1_row)
        d_only_profiles.extend(a1_profiles)
        bc_union = pd.concat([augmented["B_STATIC_MOMENTUM_BLEND"][view], augmented["C_DYNAMIC_MOMENTUM_BLEND"][view]], ignore_index=True)
        bc_row, bc_profiles = d_only_summary(d_frame, bc_union, "D_ONLY_VS_B_C_UNION", view)
        d_only_bc.append(bc_row)
        d_only_profiles.extend(bc_profiles)

    eligible = augmented["D_WEIGHT_OPTIMIZED_R1"]["full"].copy()
    if "eligible_flag" in eligible:
        eligible = eligible[eligible["eligible_flag"].map(lambda x: truth(x) or clean(x).lower() == "true")]
    universe_sector = universe_baseline(eligible, "sector", "sector")
    universe_industry = universe_baseline(eligible, "industry", "industry")
    overweights = overweight_rows({"top20": augmented["D_WEIGHT_OPTIMIZED_R1"]["top20"], "top50": augmented["D_WEIGHT_OPTIMIZED_R1"]["top50"]}, eligible)
    universe_top_sector_weight = max([float(r["top_sector_weight"]) for r in universe_sector], default=0.0)

    score_attr: list[dict[str, Any]] = []
    sector_adv: list[dict[str, Any]] = []
    industry_adv: list[dict[str, Any]] = []
    for view in ["top20", "top50"]:
        d_frame = augmented["D_WEIGHT_OPTIMIZED_R1"][view]
        score_attr.extend(score_attribution(d_frame, eligible, view))
        for strategy in STRATEGIES:
            s_rows, i_rows = score_rows(strategy, view, augmented[strategy][view], eligible, "final_score", "final")
            sector_adv.extend(s_rows)
            industry_adv.extend(i_rows)

    classification_coverage = [float(r["classification_coverage_ratio"]) for r in comparison if r["strategy"] == "D_WEIGHT_OPTIMIZED_R1"]
    classification_available = bool(classification_coverage and min(classification_coverage) >= 0.80)
    causes, cause_summary, cause_flags = classify(comparison, d_only_a1 + d_only_bc, score_attr, classification_available, universe_top_sector_weight, overweights)

    d20 = next(r for r in comparison if r["strategy"] == "D_WEIGHT_OPTIMIZED_R1" and r["view"] == "top20")
    d50 = next(r for r in comparison if r["strategy"] == "D_WEIGHT_OPTIMIZED_R1" and r["view"] == "top50")
    d20_overweight = max([float(r["overweight"]) for r in overweights if r["view"] == "top20" and r["sector"] == d20["top_sector_name"]], default=0.0)
    material_sector_warning = float(d20["top_sector_weight"]) >= 0.70 and d20_overweight >= 0.20
    if not classification_available:
        final_status = "PARTIAL_PASS"
        decision = "D_CONCENTRATION_ATTRIBUTION_PARTIAL_MISSING_CLASSIFICATION_DATA"
    elif material_sector_warning:
        final_status = "WARN"
        decision = "D_CONCENTRATION_ATTRIBUTION_WARN_SECTOR_OR_INDUSTRY_CLUSTERING"
    elif cause_flags["d_only"]:
        final_status = "WARN"
        decision = "D_CONCENTRATION_ATTRIBUTION_WARN_D_ONLY_CLUSTERING"
    else:
        final_status = "PASS"
        decision = "D_CONCENTRATION_ATTRIBUTION_PASS_CONCENTRATION_EXPLAINED_LOW_INCREMENTAL_RISK"

    outputs = {
        "input_inventory.csv": inventory,
        "sector_concentration_top20.csv": sector_top20,
        "sector_concentration_top50.csv": sector_top50,
        "industry_concentration_top20.csv": industry_top20,
        "industry_concentration_top50.csv": industry_top50,
        "concentration_comparison_A1_B_C_D.csv": comparison,
        "d_only_vs_a1_concentration.csv": d_only_a1,
        "d_only_vs_b_c_concentration.csv": d_only_bc,
        "d_only_ticker_profile.csv": d_only_profiles,
        "score_concentration_attribution.csv": score_attr,
        "sector_score_advantage.csv": sector_adv,
        "industry_score_advantage.csv": industry_adv,
        "eligible_universe_sector_baseline.csv": universe_sector,
        "eligible_universe_industry_baseline.csv": universe_industry,
        "d_overweight_vs_universe.csv": overweights,
        "concentration_cause_classification.csv": causes,
        "concentration_cause_summary.csv": cause_summary,
    }
    for name, fields in CSV_SCHEMAS.items():
        write_csv(output / name, outputs[name], fields)

    warning_text = []
    warning_blob = ""
    for path in warning_paths.values():
        if path.is_file():
            warning_blob += read_frame(path).to_csv(index=False)
    for token in ["BITF", "PSTG"]:
        if token in warning_blob:
            warning_text.append(f"{token} warning present in V21.108 warning inputs and preserved read-only.")
    if not warning_text:
        warning_text.append("No BITF/PSTG token found in available warning files.")

    score_warning = any(row["severity"] == "WARN" and row["cause"] in {"MOMENTUM_SCORE_SECTOR_CLUSTERING", "BASE_SCORE_SECTOR_CLUSTERING", "SCORE_ADVANTAGE_CONCENTRATED"} for row in causes)
    next_step = (
        "repair classification data before risk-control design" if not classification_available else
        "continue V21.109 forward maturity tracking and later design V21.114 risk-control diagnostic only after matured data exists" if final_status == "WARN" else
        "continue forward maturity tracking"
    )
    summary = {
        "stage": STAGE,
        "generated_at_utc": started,
        "final_status": final_status,
        "decision": decision,
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": False,
        "official_outputs_modified": False,
        "source_ranking_files_modified": False,
        "model_weights_changed": False,
        "trade_instructions_produced": False,
        "output_dir": output.relative_to(root).as_posix() if output.is_relative_to(root) else str(output),
        "d_top20_top_sector": d20["top_sector_name"],
        "d_top20_top_sector_weight": d20["top_sector_weight"],
        "d_top50_top_sector": d50["top_sector_name"],
        "d_top50_top_sector_weight": d50["top_sector_weight"],
        "d_top20_top_industry": d20["top_industry_name"],
        "d_top20_top_industry_weight": d20["top_industry_weight"],
        "d_top50_top_industry": d50["top_industry_name"],
        "d_top50_top_industry_weight": d50["top_industry_weight"],
        "d_vs_universe_top_sector_overweight": d20_overweight,
        "d_only_concentration_warning": cause_flags["d_only"],
        "score_concentration_warning": score_warning,
        "classification_data_available": classification_available,
        "concentration_warning": material_sector_warning or cause_flags["d_only"] or score_warning,
        "warnings": warning_text,
        "next_recommended_step": next_step,
    }
    write_json(output / SUMMARY_JSON, summary)

    report = [
        f"# {STAGE}",
        "",
        f"FINAL_STATUS: {final_status}",
        f"DECISION: {decision}",
        "",
        "## Controls",
        "- research_only = true",
        "- official_adoption_allowed = false",
        "- broker_action_allowed = false",
        "- protected_outputs_modified = false",
        "- No cap, filter, penalty, rebalance, rank mutation, model-weight change, or trade instruction was produced.",
        "",
        "## Input Inventory",
        f"- Inventory rows: {len(inventory)}",
        f"- Classification data available: {str(classification_available).lower()}",
        "",
        "## D Top20/Top50 Concentration Summary",
        f"- D Top20 top sector: {d20['top_sector_name']} ({float(d20['top_sector_weight']):.4f})",
        f"- D Top50 top sector: {d50['top_sector_name']} ({float(d50['top_sector_weight']):.4f})",
        f"- D Top20 top industry: {d20['top_industry_name']} ({float(d20['top_industry_weight']):.4f})",
        f"- D Top50 top industry: {d50['top_industry_name']} ({float(d50['top_industry_weight']):.4f})",
        "",
        "## A1/B/C/D Comparison",
        "- See concentration_comparison_A1_B_C_D.csv plus sector/industry concentration CSVs.",
        "",
        "## D-Only Concentration",
        f"- D-only concentration warning: {str(cause_flags['d_only']).lower()}",
        "- See d_only_vs_a1_concentration.csv, d_only_vs_b_c_concentration.csv, and d_only_ticker_profile.csv.",
        "",
        "## Score-Source Attribution",
        f"- Score concentration warning: {str(score_warning).lower()}",
        "- See score_concentration_attribution.csv, sector_score_advantage.csv, and industry_score_advantage.csv.",
        "",
        "## Universe Baseline Comparison",
        f"- Universe top sector weight: {universe_top_sector_weight:.4f}",
        f"- D Top20 overweight versus universe top sector: {d20_overweight:.4f}",
        "",
        "## Concentration Cause Classification",
        f"- Cause rows: {len(causes)}",
        f"- Summary rows: {len(cause_summary)}",
        "",
        "## Preserved Warnings",
        *[f"- {item}" for item in warning_text],
        "",
        "## Next Recommended Step",
        f"- {next_step}",
    ]
    (output / REPORT_MD).write_text("\n".join(report) + "\n", encoding="utf-8")

    write_csv(output / MANIFEST_CSV, manifest_rows(output), ["file", "path", "bytes", "sha256", "research_only"])
    write_csv(output / MANIFEST_CSV, manifest_rows(output), ["file", "path", "bytes", "sha256", "research_only"])

    print(f"FINAL_STATUS: {final_status}")
    print(f"DECISION: {decision}")
    print(f"D_TOP20_TOP_SECTOR: {d20['top_sector_name']}")
    print(f"D_TOP20_TOP_SECTOR_WEIGHT: {d20['top_sector_weight']}")
    print(f"D_TOP50_TOP_SECTOR: {d50['top_sector_name']}")
    print(f"D_TOP50_TOP_SECTOR_WEIGHT: {d50['top_sector_weight']}")
    print(f"D_TOP20_TOP_INDUSTRY: {d20['top_industry_name']}")
    print(f"D_TOP20_TOP_INDUSTRY_WEIGHT: {d20['top_industry_weight']}")
    print(f"D_TOP50_TOP_INDUSTRY: {d50['top_industry_name']}")
    print(f"D_TOP50_TOP_INDUSTRY_WEIGHT: {d50['top_industry_weight']}")
    print(f"D_VS_UNIVERSE_TOP_SECTOR_OVERWEIGHT: {d20_overweight}")
    print(f"D_ONLY_CONCENTRATION_WARNING: {str(cause_flags['d_only']).lower()}")
    print(f"SCORE_CONCENTRATION_WARNING: {str(score_warning).lower()}")
    print(f"CLASSIFICATION_DATA_AVAILABLE: {str(classification_available).lower()}")
    print("RESEARCH_ONLY: true")
    print("OFFICIAL_ADOPTION_ALLOWED: false")
    print("BROKER_ACTION_ALLOWED: false")
    print("PROTECTED_OUTPUTS_MODIFIED: false")
    print(f"REPORT_PATH: {(output / REPORT_MD).relative_to(root).as_posix() if (output / REPORT_MD).is_relative_to(root) else output / REPORT_MD}")
    print(f"SUMMARY_PATH: {(output / SUMMARY_JSON).relative_to(root).as_posix() if (output / SUMMARY_JSON).is_relative_to(root) else output / SUMMARY_JSON}")
    print(f"MANIFEST_PATH: {(output / MANIFEST_CSV).relative_to(root).as_posix() if (output / MANIFEST_CSV).is_relative_to(root) else output / MANIFEST_CSV}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    run(args.root.resolve(), args.output_dir)


if __name__ == "__main__":
    main()
