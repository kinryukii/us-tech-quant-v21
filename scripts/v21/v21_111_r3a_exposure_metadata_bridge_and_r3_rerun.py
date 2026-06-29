#!/usr/bin/env python
"""V21.111-R3A exposure metadata bridge and R3 rerun."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v21_111_r3_exposure_adjusted_alpha_retention_diagnostic as r3


STAGE = "V21.111-R3A_EXPOSURE_METADATA_BRIDGE_AND_R3_RERUN"
OUTPUT_REL = Path("outputs/v21/V21.111_R3A_EXPOSURE_METADATA_BRIDGE_AND_R3_RERUN")
RERUN_DIRNAME = "r3_rerun"
RAW_D_REL = Path("outputs/v21/V21.108_latest_data_multi_strategy_rerun/R2_archived_latest_strategy_rankings/D_WEIGHT_OPTIMIZED_R1/full_ranking.csv")
SUMMARY_JSON = "V21.111_R3A_EXPOSURE_METADATA_BRIDGE_AND_R3_RERUN_summary.json"
REPORT_TXT = "V21.111_R3A_EXPOSURE_METADATA_BRIDGE_AND_R3_RERUN_report.txt"

PROTECTED_RELS = [
    Path("outputs/v21/V21.108_latest_data_multi_strategy_rerun"),
    Path("outputs/v21/V21.111_D_FAILURE_MODE_DECOMPOSITION"),
    Path("outputs/v21/V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT"),
    Path("outputs/v21/V21.111_R2_SECTOR_INDUSTRY_NEUTRAL_COUNTERFACTUAL_DIAGNOSTIC"),
    Path("outputs/v21/V21.111_R3_EXPOSURE_ADJUSTED_ALPHA_RETENTION_DIAGNOSTIC"),
    Path("outputs/v20"),
    Path("archive"),
]

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "research_only", "official_adoption_allowed",
    "broker_action_allowed", "protected_outputs_modified", "raw_d_input_path",
    "selected_metadata_source_path", "metadata_candidates_scanned",
    "metadata_usable_candidates", "rows_loaded", "eligible_rows", "sector_coverage_ratio",
    "industry_coverage_ratio", "raw_top20_largest_sector",
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

TICKER_ALIASES = ["ticker", "symbol", "Ticker", "Symbol"]
SECTOR_ALIASES = ["sector", "Sector", "gics_sector", "GICS Sector", "sector_name"]
INDUSTRY_ALIASES = ["industry", "Industry", "gics_industry", "GICS Industry", "industry_name"]
SEARCH_ROOTS = [Path("data"), Path("inputs"), Path("outputs/v21"), Path("archive"), Path("outputs/v20")]
NAME_TOKENS = ["universe", "metadata", "profile", "sector", "industry", "ticker", "fundamental", "company", "snapshot", "screen", "ranking"]


def snapshot_protected(root: Path) -> dict[str, dict[str, tuple[int, int, str]]]:
    return {p.as_posix(): r3.snapshot_path(root / p) for p in PROTECTED_RELS if (root / p).exists()}


def protected_modified(before: dict[str, dict[str, tuple[int, int, str]]], root: Path) -> bool:
    return before != snapshot_protected(root)


def rel(root: Path, path: Path | None) -> str:
    return r3.rel(root, path)


def output_dir(root: Path, override: Path | None = None) -> Path:
    out = (override if override and override.is_absolute() else root / (override or OUTPUT_REL)).resolve()
    out.mkdir(parents=True, exist_ok=True)
    return out


def alias(columns: list[str], aliases: list[str]) -> str:
    lower = {c.lower().strip(): c for c in columns}
    for item in aliases:
        if item in columns:
            return item
        found = lower.get(item.lower().strip())
        if found:
            return found
    return ""


def candidate_files(root: Path, output: Path) -> list[Path]:
    files: list[Path] = []
    for search_root in SEARCH_ROOTS:
        base = root / search_root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.resolve().is_relative_to(output.resolve()):
                continue
            suffix = path.suffix.lower()
            name = path.name.lower()
            if suffix not in {".csv", ".parquet"}:
                continue
            if any(token in name for token in NAME_TOKENS):
                files.append(path)
    return sorted(set(files))


def read_candidate(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def inspect_candidate(path: Path, raw_tickers: set[str], root: Path) -> dict[str, Any]:
    row: dict[str, Any] = {
        "file_path": rel(root, path),
        "rows": 0,
        "available_ticker_column": "",
        "available_sector_column": "",
        "available_industry_column": "",
        "ticker_overlap": 0,
        "non_null_sector_count": 0,
        "non_null_industry_count": 0,
        "sector_coverage_ratio": 0.0,
        "industry_coverage_ratio": 0.0,
        "usable": False,
        "reason": "",
        "source_tier": source_tier(path, root),
        "looks_top20_summary": looks_top_summary(path),
    }
    try:
        frame = read_candidate(path)
    except Exception as exc:
        row["reason"] = f"read_error={exc}"
        return row
    row["rows"] = int(len(frame))
    ticker_col = alias(list(frame.columns), TICKER_ALIASES)
    sector_col = alias(list(frame.columns), SECTOR_ALIASES)
    industry_col = alias(list(frame.columns), INDUSTRY_ALIASES)
    row["available_ticker_column"] = ticker_col
    row["available_sector_column"] = sector_col
    row["available_industry_column"] = industry_col
    if not ticker_col:
        row["reason"] = "missing_ticker_column"
        return row
    tickers = frame[ticker_col].astype(str).str.upper().str.strip()
    mask = tickers.isin(raw_tickers)
    row["ticker_overlap"] = int(mask.sum())
    if sector_col:
        row["non_null_sector_count"] = int(frame.loc[mask, sector_col].map(r3.clean).ne("").sum())
        row["sector_coverage_ratio"] = row["non_null_sector_count"] / len(raw_tickers) if raw_tickers else 0.0
    if industry_col:
        row["non_null_industry_count"] = int(frame.loc[mask, industry_col].map(r3.clean).ne("").sum())
        row["industry_coverage_ratio"] = row["non_null_industry_count"] / len(raw_tickers) if raw_tickers else 0.0
    if row["sector_coverage_ratio"] >= 0.80 and row["industry_coverage_ratio"] >= 0.70:
        row["usable"] = True
        row["reason"] = "usable"
    elif not sector_col or not industry_col:
        row["reason"] = "missing_sector_or_industry_column"
    else:
        row["reason"] = "coverage_below_threshold"
    return row


def source_tier(path: Path, root: Path) -> int:
    text = rel(root, path).lower()
    if text.startswith("outputs/v21"):
        return 4
    if text.startswith("data") or text.startswith("inputs"):
        return 3
    if text.startswith("archive"):
        return 2
    if text.startswith("outputs/v20"):
        return 1
    return 0


def looks_top_summary(path: Path) -> bool:
    text = path.name.lower()
    return "top20" in text or "top_20" in text or "top-20" in text


def select_best_candidate(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    usable = [r for r in rows if bool(r.get("usable"))]
    if not usable:
        return None
    full_universe_exists = any(not r.get("looks_top20_summary") for r in usable)
    if full_universe_exists:
        usable = [r for r in usable if not r.get("looks_top20_summary")]
    return max(
        usable,
        key=lambda r: (
            int(r.get("ticker_overlap", 0)),
            float(r.get("industry_coverage_ratio", 0.0)),
            float(r.get("sector_coverage_ratio", 0.0)),
            int(r.get("source_tier", 0)),
            int(r.get("rows", 0)),
        ),
    )


def discover_metadata(root: Path, raw: pd.DataFrame, out: Path) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    raw_tickers = set(raw["ticker"].astype(str).str.upper().str.strip())
    rows = [inspect_candidate(path, raw_tickers, root) for path in candidate_files(root, out)]
    return rows, select_best_candidate(rows)


def build_bridge(root: Path, raw: pd.DataFrame, selected: dict[str, Any] | None) -> pd.DataFrame:
    result = raw.copy()
    result = result.rename(columns={"rank": "raw_rank", "final_score": "raw_final_score"})
    for col in ["sector", "industry"]:
        if col in result:
            result = result.drop(columns=[col])
    if not selected:
        result["sector"] = ""
        result["industry"] = ""
        result["metadata_source_path"] = ""
        result["metadata_join_status"] = "NO_USABLE_METADATA_SOURCE"
        return result[["ticker", "raw_rank", "raw_final_score", "sector", "industry", "metadata_source_path", "metadata_join_status"]]
    path = root / selected["file_path"]
    meta = read_candidate(path)
    ticker_col = selected["available_ticker_column"]
    sector_col = selected["available_sector_column"]
    industry_col = selected["available_industry_column"]
    join = meta[[ticker_col, sector_col, industry_col]].copy()
    join.columns = ["ticker", "sector", "industry"]
    join["ticker"] = join["ticker"].astype(str).str.upper().str.strip()
    join = join.drop_duplicates("ticker", keep="last")
    result = result.merge(join, on="ticker", how="left")
    result["metadata_source_path"] = selected["file_path"]
    result["metadata_join_status"] = np.where(
        result["sector"].map(r3.clean).ne("") & result["industry"].map(r3.clean).ne(""),
        "JOINED",
        "MISSING_EXPOSURE",
    )
    return result[["ticker", "raw_rank", "raw_final_score", "sector", "industry", "metadata_source_path", "metadata_join_status"]]


def r3_input_from_bridge(bridge: pd.DataFrame) -> pd.DataFrame:
    frame = bridge.rename(columns={"raw_rank": "rank", "raw_final_score": "final_score"}).copy()
    frame["eligible_flag"] = True
    return frame[["ticker", "rank", "final_score", "sector", "industry", "eligible_flag"]]


def write_empty_outputs(out: Path) -> None:
    rerun = out / RERUN_DIRNAME
    rerun.mkdir(parents=True, exist_ok=True)
    for name in [
        "raw_d_exposure_summary.csv",
        "exposure_adjustment_grid_results.csv",
        "best_exposure_adjusted_top20.csv",
        "best_exposure_adjusted_top50.csv",
        "raw_vs_best_overlap.csv",
        "rank_displacement_detail.csv",
        "concentration_reduction_summary.csv",
    ]:
        r3.write_csv(rerun / name, [])


def execute_r3_rerun(frame: pd.DataFrame, out: Path) -> dict[str, Any]:
    rerun = out / RERUN_DIRNAME
    rerun.mkdir(parents=True, exist_ok=True)
    eligible = r3.eligible_universe(frame)
    raw20, raw50 = eligible.head(20).copy(), eligible.head(50).copy()
    raw20_stats = r3.exposure_stats(eligible, 20, "raw_top20")
    raw50_stats = r3.exposure_stats(eligible, 50, "raw_top50")
    raw20_sector, raw50_sector = r3.bucket_weights(raw20, "sector"), r3.bucket_weights(raw50, "sector")
    raw20_industry, raw50_industry = r3.bucket_weights(raw20, "industry"), r3.bucket_weights(raw50, "industry")

    results: list[dict[str, Any]] = []
    adjusted_by_id: dict[str, pd.DataFrame] = {}
    for idx, params in enumerate(r3.grid_params(), start=1):
        variant_id = f"R3A_GRID_{idx:04d}"
        adjusted = r3.build_adjusted(eligible, params, raw20_sector, raw50_sector, raw20_industry, raw50_industry)
        adjusted_by_id[variant_id] = adjusted
        results.append(r3.evaluate_variant(eligible, adjusted, params, variant_id, raw20, raw50, raw20_stats, raw50_stats))
    best = r3.choose_best(results)
    if best is None:
        best = max(results, key=lambda item: item["alpha_retention_score"]) if results else {}
    best_adjusted = adjusted_by_id.get(best.get("variant_id", ""), pd.DataFrame())
    best20, best50 = best_adjusted.head(20).copy(), best_adjusted.head(50).copy()

    r3.write_csv(rerun / "raw_d_exposure_summary.csv", r3.exposure_rows(eligible, 20, "raw_top20") + r3.exposure_rows(eligible, 50, "raw_top50"))
    r3.write_csv(rerun / "exposure_adjustment_grid_results.csv", results)
    r3.write_csv(rerun / "best_exposure_adjusted_top20.csv", best20.to_dict("records"))
    r3.write_csv(rerun / "best_exposure_adjusted_top50.csv", best50.to_dict("records"))
    overlap_rows = []
    for view, raw_set, best_frame in [("top20", set(raw20["ticker"]), best20), ("top50", set(raw50["ticker"]), best50)]:
        best_set = set(best_frame["ticker"])
        overlap_rows.append({"view": view, "overlap_count": len(raw_set & best_set), "raw_only_tickers": ",".join(sorted(raw_set - best_set)), "adjusted_only_tickers": ",".join(sorted(best_set - raw_set))})
    r3.write_csv(rerun / "raw_vs_best_overlap.csv", overlap_rows)
    displacement = eligible[["ticker", "rank", "final_score", "sector", "industry"]].merge(
        best_adjusted[["ticker", "adjusted_rank", "adjusted_score", "sector_excess", "industry_excess"]],
        on="ticker",
        how="left",
    )
    displacement["rank_displacement"] = displacement["adjusted_rank"] - displacement["rank"]
    r3.write_csv(rerun / "rank_displacement_detail.csv", displacement.to_dict("records"))
    r3.write_csv(rerun / "concentration_reduction_summary.csv", [
        {"metric": "top20_largest_sector_reduction", "raw": raw20_stats["largest_sector_weight"], "best": best.get("adjusted_top20_largest_sector_weight", 0), "reduction": best.get("top20_largest_sector_reduction", 0)},
        {"metric": "top20_largest_industry_reduction", "raw": raw20_stats["largest_industry_weight"], "best": best.get("adjusted_top20_largest_industry_weight", 0), "reduction": best.get("top20_largest_industry_reduction", 0)},
        {"metric": "sector_hhi_reduction", "raw": raw20_stats["sector_hhi"], "best": raw20_stats["sector_hhi"] - best.get("sector_hhi_reduction", 0), "reduction": best.get("sector_hhi_reduction", 0)},
        {"metric": "industry_hhi_reduction", "raw": raw20_stats["industry_hhi"], "best": raw20_stats["industry_hhi"] - best.get("industry_hhi_reduction", 0), "reduction": best.get("industry_hhi_reduction", 0)},
    ])
    return {"eligible": eligible, "raw20_stats": raw20_stats, "raw50_stats": raw50_stats, "results": results, "best": best}


def status_for(results: list[dict[str, Any]]) -> tuple[str, str, int, int, int]:
    strong = sum(1 for item in results if item["classification"] == "STRONG")
    useful = sum(1 for item in results if item["classification"] == "USEFUL_DIAGNOSTIC")
    destructive = sum(1 for item in results if item["classification"] == "TOO_DESTRUCTIVE")
    if strong:
        return "PASS_V21_111_R3A_STRONG_ALPHA_RETENTION_WITH_CONCENTRATION_REDUCTION", "EXPOSURE_ADJUSTED_D_SHADOW_RANKING_CANDIDATE_RESEARCH_ONLY", strong, useful, destructive
    if useful:
        return "PARTIAL_PASS_V21_111_R3A_USEFUL_DIAGNOSTIC_VARIANT_FOUND", "EXPOSURE_ADJUSTED_D_USEFUL_DIAGNOSTIC_RESEARCH_ONLY", strong, useful, destructive
    return "WARN_V21_111_R3A_NO_USEFUL_EXPOSURE_ADJUSTED_VARIANT", "RAW_D_CONCENTRATION_CONFIRMED_SOFT_ADJUSTMENT_NOT_USEFUL", strong, useful, destructive


def base_summary(root: Path, before: dict[str, dict[str, tuple[int, int, str]]], raw: pd.DataFrame, rows: list[dict[str, Any]], selected: dict[str, Any] | None, bridge: pd.DataFrame, modified: bool) -> dict[str, Any]:
    sector_cov = float(bridge["sector"].map(r3.clean).ne("").sum() / len(raw)) if len(raw) else 0.0
    industry_cov = float(bridge["industry"].map(r3.clean).ne("").sum() / len(raw)) if len(raw) else 0.0
    return {field: None for field in SUMMARY_FIELDS} | {
        "stage": STAGE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": modified,
        "raw_d_input_path": RAW_D_REL.as_posix(),
        "selected_metadata_source_path": selected["file_path"] if selected else "",
        "metadata_candidates_scanned": len(rows),
        "metadata_usable_candidates": sum(1 for item in rows if item.get("usable")),
        "rows_loaded": int(len(raw)),
        "eligible_rows": 0,
        "sector_coverage_ratio": sector_cov,
        "industry_coverage_ratio": industry_cov,
        "variants_tested": 0,
        "strong_variants": 0,
        "useful_diagnostic_variants": 0,
        "too_destructive_variants": 0,
        "forward_data_available": False,
        "matured_observations": 0,
        "source_files_modified": modified,
        "protected_paths_verified": list(before.keys()),
    }


def run(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    out = output_dir(root, output_override)
    before = snapshot_protected(root)
    raw_path = root / RAW_D_REL
    raw = r3.normalize_ranking(r3.read_frame(raw_path))
    rows, selected = discover_metadata(root, raw, out)
    bridge = build_bridge(root, raw, selected)
    r3.write_csv(out / "metadata_discovery_report.csv", rows)
    r3.write_csv(out / "bridged_raw_d_with_exposure.csv", bridge.to_dict("records"))

    sector_cov = float(bridge["sector"].map(r3.clean).ne("").sum() / len(raw)) if len(raw) else 0.0
    industry_cov = float(bridge["industry"].map(r3.clean).ne("").sum() / len(raw)) if len(raw) else 0.0
    sufficient = sector_cov >= 0.80 and industry_cov >= 0.70
    modified = protected_modified(before, root)
    if not sufficient:
        write_empty_outputs(out)
        summary = base_summary(root, before, raw, rows, selected, bridge, modified)
        summary.update({
            "final_status": "PARTIAL_PASS_V21_111_R3A_METADATA_BRIDGE_INSUFFICIENT",
            "decision": "R3_RERUN_BLOCKED_METADATA_COVERAGE_INSUFFICIENT",
        })
    else:
        rerun = execute_r3_rerun(r3_input_from_bridge(bridge), out)
        final_status, decision, strong, useful, destructive = status_for(rerun["results"])
        best = rerun["best"]
        raw20_stats, raw50_stats = rerun["raw20_stats"], rerun["raw50_stats"]
        modified = protected_modified(before, root)
        summary = base_summary(root, before, raw, rows, selected, bridge, modified)
        summary.update({
            "final_status": final_status,
            "decision": decision,
            "eligible_rows": int(len(rerun["eligible"])),
            "raw_top20_largest_sector": raw20_stats["largest_sector"],
            "raw_top20_largest_sector_weight": raw20_stats["largest_sector_weight"],
            "raw_top50_largest_sector_weight": raw50_stats["largest_sector_weight"],
            "raw_top20_largest_industry": raw20_stats["largest_industry"],
            "raw_top20_largest_industry_weight": raw20_stats["largest_industry_weight"],
            "raw_top50_largest_industry_weight": raw50_stats["largest_industry_weight"],
            "variants_tested": len(rerun["results"]),
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
        })
    summary["output_dir"] = rel(root, out)
    r3.write_json(out / SUMMARY_JSON, summary)
    report = [
        STAGE,
        f"FINAL_STATUS={summary['final_status']}",
        f"DECISION={summary['decision']}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        f"selected_metadata_source_path={summary['selected_metadata_source_path']}",
        f"sector_coverage_ratio={summary['sector_coverage_ratio']}",
        f"industry_coverage_ratio={summary['industry_coverage_ratio']}",
        f"raw_top20_largest_sector={summary.get('raw_top20_largest_sector')}",
        f"raw_top20_largest_industry={summary.get('raw_top20_largest_industry')}",
        f"best_variant_classification={summary.get('best_variant_classification')}",
        "forward_data_available=false",
        "matured_observations=0",
        f"protected_outputs_modified={str(summary['protected_outputs_modified']).lower()}",
    ]
    (out / REPORT_TXT).write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"FINAL_STATUS={summary['final_status']}")
    print(f"DECISION={summary['decision']}")
    print(f"SELECTED_METADATA_SOURCE={summary['selected_metadata_source_path']}")
    print(f"SECTOR_COVERAGE_RATIO={summary['sector_coverage_ratio']}")
    print(f"INDUSTRY_COVERAGE_RATIO={summary['industry_coverage_ratio']}")
    print(f"BEST_VARIANT_CLASSIFICATION={summary.get('best_variant_classification') or ''}")
    print(f"BEST_TOP20_OVERLAP_WITH_RAW={summary.get('best_top20_overlap_with_raw') or ''}")
    print(f"BEST_TOP50_OVERLAP_WITH_RAW={summary.get('best_top50_overlap_with_raw') or ''}")
    print(f"OUTPUT_DIR={summary['output_dir']}")
    print(f"PROTECTED_OUTPUTS_MODIFIED={str(summary['protected_outputs_modified']).lower()}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    run(args.root, args.output_dir)


if __name__ == "__main__":
    main()
