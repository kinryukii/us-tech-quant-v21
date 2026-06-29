#!/usr/bin/env python
"""V21.111-R3 research-only exposure-adjusted alpha retention diagnostic."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


STAGE = "V21.111-R3_EXPOSURE_ADJUSTED_ALPHA_RETENTION_DIAGNOSTIC"
OUTPUT_REL = Path("outputs/v21/V21.111_R3_EXPOSURE_ADJUSTED_ALPHA_RETENTION_DIAGNOSTIC")
SUMMARY_JSON = "V21.111_R3_EXPOSURE_ADJUSTED_ALPHA_RETENTION_DIAGNOSTIC_summary.json"
REPORT_TXT = "V21.111_R3_EXPOSURE_ADJUSTED_ALPHA_RETENTION_DIAGNOSTIC_report.txt"
RAW_D_STRATEGY = "D_WEIGHT_OPTIMIZED_R1"

PROTECTED_RELS = [
    Path("outputs/v21/V21.108_latest_data_multi_strategy_rerun"),
    Path("outputs/v21/V21.111_D_FAILURE_MODE_DECOMPOSITION"),
    Path("outputs/v21/V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT"),
    Path("outputs/v21/V21.111_R2_SECTOR_INDUSTRY_NEUTRAL_COUNTERFACTUAL_DIAGNOSTIC"),
    Path("outputs/v20"),
    Path("archive"),
]

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "research_only", "official_adoption_allowed",
    "broker_action_allowed", "protected_outputs_modified", "raw_d_input_path",
    "metadata_input_path", "rows_loaded", "eligible_rows", "raw_top20_largest_sector",
    "raw_top20_largest_sector_weight", "raw_top50_largest_sector_weight",
    "raw_top20_largest_industry", "raw_top20_largest_industry_weight",
    "raw_top50_largest_industry_weight", "variants_tested", "strong_variants",
    "useful_diagnostic_variants", "too_destructive_variants", "best_variant_id",
    "best_variant_classification", "best_top20_overlap_with_raw",
    "best_top50_overlap_with_raw", "best_spearman_corr",
    "best_top20_raw_score_retention_ratio", "best_top20_largest_sector_weight",
    "best_top20_largest_industry_weight", "best_sector_concentration_reduction",
    "best_industry_concentration_reduction", "forward_data_available",
    "matured_observations", "source_files_modified", "protected_paths_verified",
]


def clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none"} else text


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    if fields is None:
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


def rel(root: Path, path: Path | None) -> str:
    if not path:
        return ""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def read_frame(path: Path | None) -> pd.DataFrame:
    if not path or not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def snapshot_path(path: Path) -> dict[str, tuple[int, int, str]]:
    if not path.exists():
        return {}
    files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
    snapshot: dict[str, tuple[int, int, str]] = {}
    for item in files:
        stat = item.stat()
        snapshot[str(item.resolve())] = (int(stat.st_mtime_ns), int(stat.st_size), sha256(item))
    return snapshot


def snapshot_protected(root: Path) -> dict[str, dict[str, tuple[int, int, str]]]:
    return {p.as_posix(): snapshot_path(root / p) for p in PROTECTED_RELS if (root / p).exists()}


def protected_modified(before: dict[str, dict[str, tuple[int, int, str]]], root: Path) -> bool:
    return before != snapshot_protected(root)


def immutable_output(root: Path, override: Path | None) -> Path:
    output = (override if override and override.is_absolute() else root / (override or OUTPUT_REL)).resolve()
    allowed_root = (root / OUTPUT_REL).resolve()
    if output != allowed_root and override is None:
        raise RuntimeError(f"Unexpected output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    allowed = {
        "raw_d_exposure_summary.csv",
        "exposure_adjustment_grid_results.csv",
        "best_exposure_adjusted_top20.csv",
        "best_exposure_adjusted_top50.csv",
        "raw_vs_best_overlap.csv",
        "rank_displacement_detail.csv",
        "concentration_reduction_summary.csv",
        "optional_forward_comparison.csv",
        SUMMARY_JSON,
        REPORT_TXT,
    }
    unmanaged = [p.name for p in output.iterdir() if p.is_file() and p.name not in allowed]
    if unmanaged:
        raise RuntimeError(f"Output directory contains unmanaged files: {unmanaged}")
    return output


def normalize_ranking(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    rename = {}
    if "final_rank" in result and "rank" not in result:
        rename["final_rank"] = "rank"
    if "score" in result and "final_score" not in result:
        rename["score"] = "final_score"
    result = result.rename(columns=rename)
    if "ticker" in result:
        result["ticker"] = result["ticker"].astype(str).str.upper().str.strip()
    for column in ["rank", "final_score"]:
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    if "rank" not in result and "final_score" in result:
        result = result.sort_values(["final_score", "ticker"], ascending=[False, True]).reset_index(drop=True)
        result["rank"] = np.arange(1, len(result) + 1)
    return result


def viable_raw_d(path: Path) -> bool:
    try:
        cols = set(pd.read_csv(path, nrows=1).columns)
    except Exception:
        return False
    has_score = bool({"final_score", "score"} & cols)
    has_rank = bool({"rank", "final_rank"} & cols) or has_score
    return "ticker" in cols and has_score and has_rank


def discover_raw_d_ranking(root: Path) -> Path | None:
    preferred = root / "outputs/v21/V21.108_latest_data_multi_strategy_rerun/R2_archived_latest_strategy_rankings/D_WEIGHT_OPTIMIZED_R1/full_ranking.csv"
    if preferred.is_file() and viable_raw_d(preferred):
        return preferred
    patterns = [
        "outputs/v21/V21.102*/**/*D*raw*ranking*.csv",
        "outputs/v21/V21.102*/**/*D_WEIGHT_OPTIMIZED_R1*.csv",
        "outputs/v21/**/V21.102*/**/*ranking*.csv",
        "outputs/v21/V21.111_D_FAILURE_MODE_DECOMPOSITION/**/*raw*d*top*.csv",
        "outputs/v21/**/*D_WEIGHT_OPTIMIZED_R1*ranking*.csv",
        "outputs/v21/**/D_WEIGHT_OPTIMIZED_R1/full_ranking.csv",
    ]
    candidates: list[tuple[int, Path]] = []
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file() and viable_raw_d(path):
                candidates.append((int(path.stat().st_mtime_ns), path))
    return max(candidates)[1] if candidates else None


def discover_metadata(root: Path) -> Path | None:
    patterns = [
        "outputs/v21/v21_078/*CLASSIFICATION_MASTER*.csv",
        "outputs/v21/v21_076/*CLASSIFICATION_MASTER*.csv",
        "outputs/v21/**/*classification*master*.csv",
        "outputs/v21/**/*metadata*.csv",
        "outputs/v21/**/*universe*.csv",
    ]
    candidates: list[tuple[int, Path]] = []
    for pattern in patterns:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            try:
                cols = set(pd.read_csv(path, nrows=1).columns)
            except Exception:
                continue
            if {"ticker", "sector", "industry"}.issubset(cols):
                candidates.append((int(path.stat().st_mtime_ns), path))
    return max(candidates)[1] if candidates else None


def attach_metadata(raw: pd.DataFrame, metadata: pd.DataFrame) -> pd.DataFrame:
    result = raw.copy()
    if {"sector", "industry"}.issubset(result.columns) and not result[["sector", "industry"]].isna().any().any():
        return result
    if metadata.empty or "ticker" not in metadata:
        return result
    meta_cols = [c for c in ["ticker", "sector", "industry"] if c in metadata]
    meta = metadata[meta_cols].copy().drop_duplicates("ticker", keep="last")
    meta["ticker"] = meta["ticker"].astype(str).str.upper().str.strip()
    drop_cols = [c for c in ["sector", "industry"] if c in result.columns]
    result = result.drop(columns=drop_cols).merge(meta, on="ticker", how="left")
    return result


def eligible_universe(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "eligible_flag" in result:
        flag = result["eligible_flag"].astype(str).str.upper().isin(["TRUE", "1", "YES", "Y"])
        result = result[flag]
    result = result.dropna(subset=["ticker", "rank", "final_score"]).copy()
    result["sector"] = result["sector"].map(clean)
    result["industry"] = result["industry"].map(clean)
    return result.sort_values(["rank", "ticker"], ascending=[True, True]).reset_index(drop=True)


def bucket_weights(frame: pd.DataFrame, column: str) -> dict[str, float]:
    if frame.empty or column not in frame:
        return {}
    counts = frame[column].fillna("UNCLASSIFIED").astype(str).replace("", "UNCLASSIFIED").value_counts()
    total = counts.sum()
    return {str(k): float(v / total) for k, v in counts.items()} if total else {}


def hhi(weights: dict[str, float]) -> float:
    return float(sum(v * v for v in weights.values()))


def exposure_stats(frame: pd.DataFrame, n: int, label: str) -> dict[str, Any]:
    top = frame.sort_values(["rank", "ticker"]).head(n)
    sector = bucket_weights(top, "sector")
    industry = bucket_weights(top, "industry")
    largest_sector = max(sector.items(), key=lambda kv: kv[1]) if sector else ("MISSING", 0.0)
    largest_industry = max(industry.items(), key=lambda kv: kv[1]) if industry else ("MISSING", 0.0)
    return {
        "view": label,
        "count": len(top),
        "largest_sector": largest_sector[0],
        "largest_sector_weight": largest_sector[1],
        "largest_industry": largest_industry[0],
        "largest_industry_weight": largest_industry[1],
        "sector_hhi": hhi(sector),
        "industry_hhi": hhi(industry),
        "technology_weight": sector.get("Technology", 0.0),
        "semiconductor_equipment_materials_weight": industry.get("Semiconductor Equipment & Materials", 0.0),
    }


def exposure_rows(frame: pd.DataFrame, n: int, label: str) -> list[dict[str, Any]]:
    rows = []
    top = frame.sort_values(["rank", "ticker"]).head(n)
    for kind, col in [("sector", "sector"), ("industry", "industry")]:
        weights = bucket_weights(top, col)
        for bucket, weight in sorted(weights.items(), key=lambda kv: (-kv[1], kv[0])):
            rows.append({"view": label, "exposure_type": kind, "bucket": bucket, "weight": weight, "count": int(round(weight * len(top)))})
    stats = exposure_stats(frame, n, label)
    rows.append({"view": label, "exposure_type": "summary", "bucket": "largest_sector", "weight": stats["largest_sector_weight"], "count": stats["largest_sector"]})
    rows.append({"view": label, "exposure_type": "summary", "bucket": "largest_industry", "weight": stats["largest_industry_weight"], "count": stats["largest_industry"]})
    rows.append({"view": label, "exposure_type": "summary", "bucket": "sector_hhi", "weight": stats["sector_hhi"], "count": ""})
    rows.append({"view": label, "exposure_type": "summary", "bucket": "industry_hhi", "weight": stats["industry_hhi"], "count": ""})
    return rows


def raw_score_retention_ratio(raw_scores: pd.Series, adjusted_scores: pd.Series) -> float:
    raw_mean = float(pd.to_numeric(raw_scores, errors="coerce").mean())
    adjusted_mean = float(pd.to_numeric(adjusted_scores, errors="coerce").mean())
    if not np.isfinite(raw_mean) or raw_mean == 0:
        return 0.0
    return adjusted_mean / raw_mean


def spearman_corr(left: pd.Series, right: pd.Series) -> float:
    data = pd.DataFrame({"left": left, "right": right}).dropna()
    if len(data) < 2:
        return 0.0
    return float(data["left"].rank(method="average").corr(data["right"].rank(method="average")))


def adjusted_rank_view(adjusted: pd.DataFrame) -> pd.DataFrame:
    return adjusted.drop(columns=["rank"], errors="ignore").rename(columns={"adjusted_rank": "rank"})


def classify_variant(
    top20_overlap: int,
    top50_overlap: int,
    top20_retention: float,
    spearman: float,
    sector_reduction: float,
    industry_reduction: float,
) -> str:
    if top20_overlap < 10 or top20_retention < 0.85 or spearman < 0.80:
        return "TOO_DESTRUCTIVE"
    if (
        top20_overlap >= 14
        and top50_overlap >= 35
        and top20_retention >= 0.95
        and spearman >= 0.90
        and sector_reduction >= 0.15
        and industry_reduction >= 0.10
    ):
        return "STRONG"
    if (
        top20_overlap >= 12
        and top50_overlap >= 30
        and top20_retention >= 0.90
        and spearman >= 0.85
        and sector_reduction >= 0.10
        and industry_reduction >= 0.05
    ):
        return "USEFUL_DIAGNOSTIC"
    return "WEAK_OR_AMBIGUOUS"


def build_adjusted(frame: pd.DataFrame, params: dict[str, float], raw20_sector: dict[str, float], raw50_sector: dict[str, float], raw20_industry: dict[str, float], raw50_industry: dict[str, float]) -> pd.DataFrame:
    result = frame.copy()
    scores = pd.to_numeric(result["final_score"], errors="coerce")
    std = float(scores.std(ddof=0))
    result["raw_score_z"] = 0.0 if std == 0 else (scores - float(scores.mean())) / std
    result["sector_excess"] = result["sector"].map(lambda s: max(0.0, raw20_sector.get(clean(s), 0.0) - params["sector_top20_target"]) + max(0.0, raw50_sector.get(clean(s), 0.0) - params["sector_top50_target"]))
    result["industry_excess"] = result["industry"].map(lambda s: max(0.0, raw20_industry.get(clean(s), 0.0) - params["industry_top20_target"]) + max(0.0, raw50_industry.get(clean(s), 0.0) - params["industry_top50_target"]))
    result["adjusted_score"] = result["raw_score_z"] - params["sector_lambda"] * result["sector_excess"] - params["industry_lambda"] * result["industry_excess"]
    result = result.sort_values(["adjusted_score", "final_score", "ticker"], ascending=[False, False, True]).reset_index(drop=True)
    result["adjusted_rank"] = np.arange(1, len(result) + 1)
    return result


def evaluate_variant(frame: pd.DataFrame, adjusted: pd.DataFrame, params: dict[str, float], variant_id: str, raw20: pd.DataFrame, raw50: pd.DataFrame, raw20_stats: dict[str, Any], raw50_stats: dict[str, Any]) -> dict[str, Any]:
    adj20 = adjusted.head(20).copy()
    adj50 = adjusted.head(50).copy()
    raw20_set, raw50_set = set(raw20["ticker"]), set(raw50["ticker"])
    top20_overlap = len(raw20_set & set(adj20["ticker"]))
    top50_overlap = len(raw50_set & set(adj50["ticker"]))
    rank_map = frame.set_index("ticker")["rank"]
    adj_rank_map = adjusted.set_index("ticker")["adjusted_rank"]
    aligned = pd.DataFrame({"raw_rank": rank_map, "adjusted_rank": adj_rank_map}).dropna()
    spearman = spearman_corr(aligned["raw_rank"], aligned["adjusted_rank"])
    try:
        kendall = float(aligned["raw_rank"].corr(aligned["adjusted_rank"], method="kendall"))
    except Exception:
        kendall = np.nan
    top20_retention = raw_score_retention_ratio(raw20["final_score"], adj20["final_score"])
    top50_retention = raw_score_retention_ratio(raw50["final_score"], adj50["final_score"])
    displacement = (aligned["adjusted_rank"] - aligned["raw_rank"]).abs()
    adjusted_ranked = adjusted_rank_view(adjusted)
    adj20_stats = exposure_stats(adjusted_ranked, 20, "adjusted_top20")
    adj50_stats = exposure_stats(adjusted_ranked, 50, "adjusted_top50")
    sector_reduction = float(raw20_stats["largest_sector_weight"] - adj20_stats["largest_sector_weight"])
    industry_reduction = float(raw20_stats["largest_industry_weight"] - adj20_stats["largest_industry_weight"])
    classification = classify_variant(top20_overlap, top50_overlap, top20_retention, spearman, sector_reduction, industry_reduction)
    return {
        "variant_id": variant_id,
        **params,
        "top20_overlap_with_raw": top20_overlap,
        "top50_overlap_with_raw": top50_overlap,
        "spearman_rank_corr": spearman,
        "kendall_rank_corr": kendall,
        "mean_raw_final_score_adjusted_top20": float(adj20["final_score"].mean()),
        "mean_raw_final_score_raw_top20": float(raw20["final_score"].mean()),
        "top20_raw_score_retention_ratio": top20_retention,
        "top50_raw_score_retention_ratio": top50_retention,
        "average_rank_displacement": float(displacement.mean()),
        "max_rank_displacement": float(displacement.max()),
        "raw_top20_pushed_out_count": 20 - top20_overlap,
        "adjusted_top20_largest_sector_weight": adj20_stats["largest_sector_weight"],
        "adjusted_top50_largest_sector_weight": adj50_stats["largest_sector_weight"],
        "adjusted_top20_largest_industry_weight": adj20_stats["largest_industry_weight"],
        "adjusted_top50_largest_industry_weight": adj50_stats["largest_industry_weight"],
        "sector_hhi_reduction": raw20_stats["sector_hhi"] - adj20_stats["sector_hhi"],
        "industry_hhi_reduction": raw20_stats["industry_hhi"] - adj20_stats["industry_hhi"],
        "technology_top20_weight": adj20_stats["technology_weight"],
        "technology_top50_weight": adj50_stats["technology_weight"],
        "semiconductor_equipment_materials_top20_weight": adj20_stats["semiconductor_equipment_materials_weight"],
        "semiconductor_equipment_materials_top50_weight": adj50_stats["semiconductor_equipment_materials_weight"],
        "top20_largest_sector_reduction": sector_reduction,
        "top20_largest_industry_reduction": industry_reduction,
        "alpha_retention_score": 0.35 * (top20_overlap / 20) + 0.25 * (top50_overlap / 50) + 0.25 * top20_retention + 0.15 * spearman,
        "classification": classification,
    }


def choose_best(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    eligible = [r for r in results if r["classification"] != "TOO_DESTRUCTIVE"]
    if not eligible:
        return None
    class_rank = {"STRONG": 3, "USEFUL_DIAGNOSTIC": 2, "WEAK_OR_AMBIGUOUS": 1}
    return max(
        eligible,
        key=lambda r: (
            class_rank.get(r["classification"], 0),
            r["alpha_retention_score"],
            r["top20_largest_sector_reduction"] + r["top20_largest_industry_reduction"],
        ),
    )


def grid_params() -> Iterable[dict[str, float]]:
    for values in product([0.60, 0.70, 0.80], [0.45, 0.55, 0.65], [0.20, 0.25, 0.30], [0.15, 0.20, 0.25], [0.05, 0.10, 0.15, 0.20, 0.30], [0.05, 0.10, 0.15, 0.20]):
        yield dict(zip(["sector_top20_target", "sector_top50_target", "industry_top20_target", "industry_top50_target", "sector_lambda", "industry_lambda"], values))


def blocked_summary(root: Path, out: Path, before: dict[str, dict[str, tuple[int, int, str]]], raw_path: Path | None, metadata_path: Path | None, raw: pd.DataFrame) -> dict[str, Any]:
    modified = protected_modified(before, root)
    summary = {field: None for field in SUMMARY_FIELDS}
    summary.update({
        "stage": STAGE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "final_status": "PARTIAL_PASS_V21_111_R3_BLOCKED_MISSING_EXPOSURE_METADATA",
        "decision": "EXPOSURE_ADJUSTED_ALPHA_RETENTION_BLOCKED_METADATA",
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": modified,
        "raw_d_input_path": rel(root, raw_path),
        "metadata_input_path": rel(root, metadata_path),
        "rows_loaded": int(len(raw)),
        "eligible_rows": 0,
        "variants_tested": 0,
        "strong_variants": 0,
        "useful_diagnostic_variants": 0,
        "too_destructive_variants": 0,
        "forward_data_available": False,
        "matured_observations": 0,
        "source_files_modified": modified,
        "protected_paths_verified": list(before.keys()),
        "output_dir": rel(root, out),
    })
    write_csv(out / "raw_d_exposure_summary.csv", [{"status": summary["final_status"], "missing_fields": "sector,industry"}])
    write_csv(out / "exposure_adjustment_grid_results.csv", [])
    write_csv(out / "best_exposure_adjusted_top20.csv", [])
    write_csv(out / "best_exposure_adjusted_top50.csv", [])
    write_csv(out / "raw_vs_best_overlap.csv", [])
    write_csv(out / "rank_displacement_detail.csv", [])
    write_csv(out / "concentration_reduction_summary.csv", [])
    write_json(out / SUMMARY_JSON, summary)
    (out / REPORT_TXT).write_text(
        f"{STAGE}\nFINAL_STATUS={summary['final_status']}\nDECISION={summary['decision']}\nMissing sector/industry exposure metadata after attempted join.\n",
        encoding="utf-8",
    )
    return summary


def run(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    out = immutable_output(root, output_override)
    before = snapshot_protected(root)
    raw_path = discover_raw_d_ranking(root)
    raw = normalize_ranking(read_frame(raw_path))
    metadata_path = discover_metadata(root)
    metadata = read_frame(metadata_path)
    raw = attach_metadata(raw, metadata)
    missing_meta = not {"ticker", "rank", "final_score", "sector", "industry"}.issubset(raw.columns) or raw[["sector", "industry"]].isna().any().any()
    if raw.empty or missing_meta:
        summary = blocked_summary(root, out, before, raw_path, metadata_path, raw)
        print(f"FINAL_STATUS={summary['final_status']}")
        print(f"DECISION={summary['decision']}")
        print(f"OUTPUT_DIR={rel(root, out)}")
        return summary

    eligible = eligible_universe(raw)
    raw20, raw50 = eligible.head(20).copy(), eligible.head(50).copy()
    raw20_stats = exposure_stats(eligible, 20, "raw_top20")
    raw50_stats = exposure_stats(eligible, 50, "raw_top50")
    raw20_sector, raw50_sector = bucket_weights(raw20, "sector"), bucket_weights(raw50, "sector")
    raw20_industry, raw50_industry = bucket_weights(raw20, "industry"), bucket_weights(raw50, "industry")

    results: list[dict[str, Any]] = []
    adjusted_by_id: dict[str, pd.DataFrame] = {}
    for idx, params in enumerate(grid_params(), start=1):
        variant_id = f"R3_GRID_{idx:04d}"
        adjusted = build_adjusted(eligible, params, raw20_sector, raw50_sector, raw20_industry, raw50_industry)
        adjusted_by_id[variant_id] = adjusted
        results.append(evaluate_variant(eligible, adjusted, params, variant_id, raw20, raw50, raw20_stats, raw50_stats))

    best = choose_best(results)
    if best is None:
        best = max(results, key=lambda r: r["alpha_retention_score"]) if results else {}
    best_adjusted = adjusted_by_id.get(best.get("variant_id", ""), pd.DataFrame())
    best20 = best_adjusted.head(20).copy()
    best50 = best_adjusted.head(50).copy()

    strong = sum(1 for r in results if r["classification"] == "STRONG")
    useful = sum(1 for r in results if r["classification"] == "USEFUL_DIAGNOSTIC")
    destructive = sum(1 for r in results if r["classification"] == "TOO_DESTRUCTIVE")
    if strong:
        final_status = "PASS_V21_111_R3_STRONG_ALPHA_RETENTION_WITH_CONCENTRATION_REDUCTION"
        decision = "EXPOSURE_ADJUSTED_D_SHADOW_RANKING_CANDIDATE_RESEARCH_ONLY"
    elif useful:
        final_status = "PARTIAL_PASS_V21_111_R3_USEFUL_DIAGNOSTIC_VARIANT_FOUND"
        decision = "EXPOSURE_ADJUSTED_D_USEFUL_DIAGNOSTIC_RESEARCH_ONLY"
    else:
        final_status = "WARN_V21_111_R3_NO_USEFUL_EXPOSURE_ADJUSTED_VARIANT"
        decision = "RAW_D_CONCENTRATION_CONFIRMED_SOFT_ADJUSTMENT_NOT_USEFUL"

    raw_exposure = exposure_rows(eligible, 20, "raw_top20") + exposure_rows(eligible, 50, "raw_top50")
    write_csv(out / "raw_d_exposure_summary.csv", raw_exposure)
    write_csv(out / "exposure_adjustment_grid_results.csv", results)
    write_csv(out / "best_exposure_adjusted_top20.csv", best20.to_dict("records"))
    write_csv(out / "best_exposure_adjusted_top50.csv", best50.to_dict("records"))

    raw_top20_set, raw_top50_set = set(raw20["ticker"]), set(raw50["ticker"])
    overlap_rows = []
    for view, raw_set, best_frame in [("top20", raw_top20_set, best20), ("top50", raw_top50_set, best50)]:
        best_set = set(best_frame["ticker"])
        overlap_rows.append({
            "view": view,
            "overlap_count": len(raw_set & best_set),
            "raw_only_tickers": ",".join(sorted(raw_set - best_set)),
            "adjusted_only_tickers": ",".join(sorted(best_set - raw_set)),
        })
    write_csv(out / "raw_vs_best_overlap.csv", overlap_rows)

    displacement = eligible[["ticker", "rank", "final_score", "sector", "industry"]].merge(
        best_adjusted[["ticker", "adjusted_rank", "adjusted_score", "sector_excess", "industry_excess"]],
        on="ticker",
        how="left",
    )
    displacement["rank_displacement"] = displacement["adjusted_rank"] - displacement["rank"]
    write_csv(out / "rank_displacement_detail.csv", displacement.to_dict("records"))
    concentration_rows = [
        {"metric": "top20_largest_sector_reduction", "raw": raw20_stats["largest_sector_weight"], "best": best["adjusted_top20_largest_sector_weight"], "reduction": best["top20_largest_sector_reduction"]},
        {"metric": "top20_largest_industry_reduction", "raw": raw20_stats["largest_industry_weight"], "best": best["adjusted_top20_largest_industry_weight"], "reduction": best["top20_largest_industry_reduction"]},
        {"metric": "sector_hhi_reduction", "raw": raw20_stats["sector_hhi"], "best": raw20_stats["sector_hhi"] - best["sector_hhi_reduction"], "reduction": best["sector_hhi_reduction"]},
        {"metric": "industry_hhi_reduction", "raw": raw20_stats["industry_hhi"], "best": raw20_stats["industry_hhi"] - best["industry_hhi_reduction"], "reduction": best["industry_hhi_reduction"]},
    ]
    write_csv(out / "concentration_reduction_summary.csv", concentration_rows)

    modified = protected_modified(before, root)
    summary = {
        "stage": STAGE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "final_status": final_status,
        "decision": decision,
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": modified,
        "raw_d_input_path": rel(root, raw_path),
        "metadata_input_path": rel(root, metadata_path),
        "rows_loaded": int(len(raw)),
        "eligible_rows": int(len(eligible)),
        "raw_top20_largest_sector": raw20_stats["largest_sector"],
        "raw_top20_largest_sector_weight": raw20_stats["largest_sector_weight"],
        "raw_top50_largest_sector_weight": raw50_stats["largest_sector_weight"],
        "raw_top20_largest_industry": raw20_stats["largest_industry"],
        "raw_top20_largest_industry_weight": raw20_stats["largest_industry_weight"],
        "raw_top50_largest_industry_weight": raw50_stats["largest_industry_weight"],
        "variants_tested": len(results),
        "strong_variants": strong,
        "useful_diagnostic_variants": useful,
        "too_destructive_variants": destructive,
        "best_variant_id": best.get("variant_id", ""),
        "best_variant_classification": best.get("classification", ""),
        "best_top20_overlap_with_raw": best.get("top20_overlap_with_raw", 0),
        "best_top50_overlap_with_raw": best.get("top50_overlap_with_raw", 0),
        "best_spearman_corr": best.get("spearman_rank_corr", 0.0),
        "best_top20_raw_score_retention_ratio": best.get("top20_raw_score_retention_ratio", 0.0),
        "best_top20_largest_sector_weight": best.get("adjusted_top20_largest_sector_weight", 0.0),
        "best_top20_largest_industry_weight": best.get("adjusted_top20_largest_industry_weight", 0.0),
        "best_sector_concentration_reduction": best.get("top20_largest_sector_reduction", 0.0),
        "best_industry_concentration_reduction": best.get("top20_largest_industry_reduction", 0.0),
        "forward_data_available": False,
        "matured_observations": 0,
        "source_files_modified": modified,
        "protected_paths_verified": list(before.keys()),
        "output_dir": rel(root, out),
    }
    write_json(out / SUMMARY_JSON, summary)
    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        f"raw_d_input_path={summary['raw_d_input_path']}",
        f"metadata_input_path={summary['metadata_input_path']}",
        f"raw_top20_largest_sector={summary['raw_top20_largest_sector']} ({summary['raw_top20_largest_sector_weight']})",
        f"raw_top20_largest_industry={summary['raw_top20_largest_industry']} ({summary['raw_top20_largest_industry_weight']})",
        f"variants_tested={len(results)}",
        f"best_variant_id={summary['best_variant_id']}",
        f"best_variant_classification={summary['best_variant_classification']}",
        f"best_top20_overlap_with_raw={summary['best_top20_overlap_with_raw']}",
        f"best_top50_overlap_with_raw={summary['best_top50_overlap_with_raw']}",
        f"best_top20_raw_score_retention_ratio={summary['best_top20_raw_score_retention_ratio']}",
        f"best_sector_concentration_reduction={summary['best_sector_concentration_reduction']}",
        f"best_industry_concentration_reduction={summary['best_industry_concentration_reduction']}",
        "FORWARD_DATA_AVAILABLE=false",
        "MATURED_OBSERVATIONS=0",
        f"protected_outputs_modified={str(modified).lower()}",
    ]
    (out / REPORT_TXT).write_text("\n".join(report) + "\n", encoding="utf-8")

    print(f"FINAL_STATUS={final_status}")
    print(f"DECISION={decision}")
    print(f"RAW_D_TOP20_LARGEST_SECTOR={summary['raw_top20_largest_sector']}:{summary['raw_top20_largest_sector_weight']}")
    print(f"RAW_D_TOP20_LARGEST_INDUSTRY={summary['raw_top20_largest_industry']}:{summary['raw_top20_largest_industry_weight']}")
    print(f"BEST_VARIANT_ID={summary['best_variant_id']}")
    print(f"BEST_VARIANT_CLASSIFICATION={summary['best_variant_classification']}")
    print(f"BEST_TOP20_OVERLAP_WITH_RAW={summary['best_top20_overlap_with_raw']}")
    print(f"BEST_TOP50_OVERLAP_WITH_RAW={summary['best_top50_overlap_with_raw']}")
    print(f"BEST_TOP20_RAW_SCORE_RETENTION_RATIO={summary['best_top20_raw_score_retention_ratio']}")
    print(f"BEST_SECTOR_CONCENTRATION_REDUCTION={summary['best_sector_concentration_reduction']}")
    print(f"BEST_INDUSTRY_CONCENTRATION_REDUCTION={summary['best_industry_concentration_reduction']}")
    print("FORWARD_DATA_AVAILABLE=false")
    print("MATURED_OBSERVATIONS=0")
    print("RESEARCH_ONLY=true")
    print("OFFICIAL_ADOPTION_ALLOWED=false")
    print("BROKER_ACTION_ALLOWED=false")
    print(f"PROTECTED_OUTPUTS_MODIFIED={str(modified).lower()}")
    print(f"OUTPUT_DIR={rel(root, out)}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    run(args.root, args.output_dir)


if __name__ == "__main__":
    main()
