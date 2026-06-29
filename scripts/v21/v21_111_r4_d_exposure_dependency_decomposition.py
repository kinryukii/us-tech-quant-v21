#!/usr/bin/env python
"""V21.111-R4 D exposure dependency decomposition diagnostic."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v21_111_r3_exposure_adjusted_alpha_retention_diagnostic as r3


STAGE = "V21.111-R4_D_EXPOSURE_DEPENDENCY_DECOMPOSITION"
OUTPUT_REL = Path("outputs/v21/V21.111_R4_D_EXPOSURE_DEPENDENCY_DECOMPOSITION")
RAW_D_REL = Path("outputs/v21/V21.108_latest_data_multi_strategy_rerun/R2_archived_latest_strategy_rankings/D_WEIGHT_OPTIMIZED_R1/full_ranking.csv")
BRIDGED_REL = Path("outputs/v21/V21.111_R3A_EXPOSURE_METADATA_BRIDGE_AND_R3_RERUN/bridged_raw_d_with_exposure.csv")
FALLBACK_METADATA_REL = Path("outputs/v21/V21.111_R2_SECTOR_INDUSTRY_NEUTRAL_COUNTERFACTUAL_DIAGNOSTIC/d_industry_neutral_percentile_ranking.csv")
SUMMARY_JSON = "V21.111_R4_D_EXPOSURE_DEPENDENCY_DECOMPOSITION_summary.json"
REPORT_TXT = "V21.111_R4_D_EXPOSURE_DEPENDENCY_DECOMPOSITION_report.txt"

PROTECTED_RELS = [
    Path("outputs/v21/V21.108_latest_data_multi_strategy_rerun"),
    Path("outputs/v21/V21.111_D_FAILURE_MODE_DECOMPOSITION"),
    Path("outputs/v21/V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT"),
    Path("outputs/v21/V21.111_R2_SECTOR_INDUSTRY_NEUTRAL_COUNTERFACTUAL_DIAGNOSTIC"),
    Path("outputs/v21/V21.111_R3_EXPOSURE_ADJUSTED_ALPHA_RETENTION_DIAGNOSTIC"),
    Path("outputs/v21/V21.111_R3A_EXPOSURE_METADATA_BRIDGE_AND_R3_RERUN"),
    Path("outputs/v20"),
    Path("archive"),
]

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "research_only", "official_adoption_allowed",
    "broker_action_allowed", "protected_outputs_modified", "raw_d_input_path",
    "exposure_metadata_input_path", "rows_loaded", "eligible_rows",
    "factor_detail_available", "raw_top20_largest_sector",
    "raw_top20_largest_sector_weight", "raw_top50_largest_sector_weight",
    "raw_top20_largest_industry", "raw_top20_largest_industry_weight",
    "raw_top50_largest_industry_weight", "exposure_only_combined_top20_overlap",
    "exposure_only_combined_top50_overlap", "exposure_only_combined_spearman_corr",
    "exposure_only_combined_score_retention_ratio",
    "raw_top20_median_within_sector_percentile",
    "raw_top20_median_within_industry_percentile", "residual_combined_top20_overlap",
    "residual_combined_top50_overlap", "residual_combined_top20_largest_sector_weight",
    "residual_combined_top20_largest_industry_weight",
    "residual_combined_score_retention_ratio", "dependency_classification",
    "forward_data_available", "matured_observations", "source_files_modified",
    "protected_paths_verified",
]

FACTOR_COLUMNS = [
    "base_score", "momentum_score", "fundamental_score", "technical_score", "strategy_score",
    "risk_score", "market_regime_score", "data_trust_score", "rs_score", "momentum_component",
    "rsi", "kdj", "macd", "bb", "breakout", "volume", "volatility",
]


def snapshot_protected(root: Path) -> dict[str, dict[str, tuple[int, int, str]]]:
    return {p.as_posix(): r3.snapshot_path(root / p) for p in PROTECTED_RELS if (root / p).exists()}


def protected_modified(before: dict[str, dict[str, tuple[int, int, str]]], root: Path) -> bool:
    return before != snapshot_protected(root)


def output_dir(root: Path, override: Path | None = None) -> Path:
    out = (override if override and override.is_absolute() else root / (override or OUTPUT_REL)).resolve()
    out.mkdir(parents=True, exist_ok=True)
    return out


def normalize_bridge(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    rename = {}
    if "rank" in result and "raw_rank" not in result:
        rename["rank"] = "raw_rank"
    if "final_score" in result and "raw_final_score" not in result:
        rename["final_score"] = "raw_final_score"
    result = result.rename(columns=rename)
    if "ticker" in result:
        result["ticker"] = result["ticker"].astype(str).str.upper().str.strip()
    for col in ["raw_rank", "raw_final_score"]:
        if col in result:
            result[col] = pd.to_numeric(result[col], errors="coerce")
    return result


def load_inputs(root: Path) -> tuple[pd.DataFrame, Path | None, bool]:
    raw_path = root / RAW_D_REL
    raw = r3.normalize_ranking(r3.read_frame(raw_path))
    if raw.empty:
        return pd.DataFrame(), None, False
    factor_available = any(c in raw.columns for c in FACTOR_COLUMNS)
    bridge_path = root / BRIDGED_REL
    if bridge_path.is_file():
        bridge = normalize_bridge(r3.read_frame(bridge_path))
        cols = ["ticker", "raw_rank", "raw_final_score", "sector", "industry"]
        extras = [c for c in FACTOR_COLUMNS if c in raw.columns]
        merged = bridge[[c for c in cols if c in bridge.columns]].merge(raw[["ticker", *extras]], on="ticker", how="left") if extras else bridge
        return merged, bridge_path, factor_available
    fallback = root / FALLBACK_METADATA_REL
    if fallback.is_file():
        meta = normalize_bridge(r3.read_frame(fallback))
        exposure_cols = [c for c in ["ticker", "sector", "industry"] if c in meta.columns]
        merged = raw.rename(columns={"rank": "raw_rank", "final_score": "raw_final_score"}).merge(
            meta[exposure_cols].drop_duplicates("ticker", keep="last"), on="ticker", how="left"
        )
        return merged, fallback, factor_available
    return pd.DataFrame(), None, factor_available


def eligible_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"ticker", "raw_rank", "raw_final_score", "sector", "industry"}
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame()
    result = frame.copy()
    result["sector"] = result["sector"].map(r3.clean)
    result["industry"] = result["industry"].map(r3.clean)
    result = result.dropna(subset=["ticker", "raw_rank", "raw_final_score"])
    result = result[result["sector"].ne("") & result["industry"].ne("")]
    return result.sort_values(["raw_rank", "ticker"]).reset_index(drop=True)


def dependency_summary(frame: pd.DataFrame, group_col: str) -> list[dict[str, Any]]:
    top20 = set(frame.nsmallest(20, "raw_rank")["ticker"])
    top50 = set(frame.nsmallest(50, "raw_rank")["ticker"])
    total = len(frame)
    rows = []
    for bucket, group in frame.groupby(group_col, dropna=False):
        count = len(group)
        top20_count = int(group["ticker"].isin(top20).sum())
        top50_count = int(group["ticker"].isin(top50).sum())
        universe_weight = count / total if total else 0.0
        row = {
            group_col: bucket,
            "universe_count": count,
            "universe_weight": universe_weight,
            "top20_count": top20_count,
            "top20_weight": top20_count / 20,
            "top50_count": top50_count,
            "top50_weight": top50_count / 50,
            "mean_raw_score": float(group["raw_final_score"].mean()),
            "median_raw_score": float(group["raw_final_score"].median()),
            "max_raw_score": float(group["raw_final_score"].max()),
            "min_raw_score": float(group["raw_final_score"].min()),
            "mean_raw_rank": float(group["raw_rank"].mean()),
            "best_raw_rank": float(group["raw_rank"].min()),
            "worst_raw_rank": float(group["raw_rank"].max()),
            "overrepresentation_top20": (top20_count / 20 - universe_weight),
            "overrepresentation_top50": (top50_count / 50 - universe_weight),
        }
        rows.append(row)
    return sorted(rows, key=lambda r: (-r["top20_weight"], str(r[group_col])))


def add_within_ranks(frame: pd.DataFrame, group_col: str, min_count: int, rank_col: str, pct_col: str) -> pd.DataFrame:
    counts = frame[group_col].value_counts()
    work = frame[frame[group_col].isin(counts[counts >= min_count].index)].copy()
    work[rank_col] = work.groupby(group_col)["raw_final_score"].rank(method="first", ascending=False)
    work["_group_count"] = work.groupby(group_col)["ticker"].transform("count")
    work[pct_col] = 1.0 - ((work[rank_col] - 1.0) / (work["_group_count"] - 1.0).replace(0, np.nan))
    work[pct_col] = work[pct_col].fillna(1.0)
    work["is_raw_top20"] = work["raw_rank"] <= 20
    work["is_raw_top50"] = work["raw_rank"] <= 50
    return work.drop(columns=["_group_count"]).sort_values([group_col, rank_col, "ticker"]).reset_index(drop=True)


def within_alpha_summary(detail: pd.DataFrame, group_col: str, pct_col: str) -> list[dict[str, Any]]:
    rows = []
    for bucket, group in detail.groupby(group_col):
        top20 = group[group["is_raw_top20"]]
        top50 = group[group["is_raw_top50"]]
        rows.append({
            group_col: bucket,
            "bucket_count": len(group),
            "raw_top20_count": len(top20),
            "raw_top50_count": len(top50),
            "raw_top20_median_percentile": float(top20[pct_col].median()) if not top20.empty else np.nan,
            "raw_top50_median_percentile": float(top50[pct_col].median()) if not top50.empty else np.nan,
            "top_percentile_top20_count": int((top20[pct_col] >= 0.75).sum()),
            "top_percentile_top50_count": int((top50[pct_col] >= 0.75).sum()),
        })
    return rows


def exposure_only_rankings(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    work = frame.copy()
    work["sector_mean_score"] = work.groupby("sector")["raw_final_score"].transform("mean")
    work["industry_mean_score"] = work.groupby("industry")["raw_final_score"].transform("mean")
    work["combined_exposure_score"] = work["sector_mean_score"] + work["industry_mean_score"]
    variants = {
        "sector_mean_score": "sector_mean_score",
        "industry_mean_score": "industry_mean_score",
        "combined_exposure_score": "combined_exposure_score",
    }
    ranked = {}
    for name, col in variants.items():
        result = work.sort_values([col, "raw_final_score", "ticker"], ascending=[False, False, True]).reset_index(drop=True)
        result["predicted_rank"] = np.arange(1, len(result) + 1)
        ranked[name] = result
    return ranked


def compare_ranking(frame: pd.DataFrame, ranked: pd.DataFrame, variant: str, score_col: str = "predicted_rank") -> dict[str, Any]:
    raw20 = set(frame.nsmallest(20, "raw_rank")["ticker"])
    raw50 = set(frame.nsmallest(50, "raw_rank")["ticker"])
    pred20 = set(ranked.nsmallest(20, score_col)["ticker"])
    pred50 = set(ranked.nsmallest(50, score_col)["ticker"])
    aligned = frame[["ticker", "raw_rank"]].merge(ranked[["ticker", score_col]], on="ticker", how="inner")
    mean_raw20 = frame.nsmallest(20, "raw_rank")["raw_final_score"].mean()
    mean_pred20 = ranked.nsmallest(20, score_col)["raw_final_score"].mean()
    try:
        kendall = float(aligned["raw_rank"].corr(aligned[score_col], method="kendall"))
    except Exception:
        kendall = np.nan
    return {
        "variant": variant,
        "top20_overlap": len(raw20 & pred20),
        "top50_overlap": len(raw50 & pred50),
        "spearman_rank_corr": r3.spearman_corr(aligned["raw_rank"], aligned[score_col]),
        "kendall_rank_corr": kendall,
        "mean_raw_score_top20": float(mean_pred20),
        "raw_score_retention_ratio": float(mean_pred20 / mean_raw20) if mean_raw20 else 0.0,
    }


def residual_rankings(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    scores = pd.to_numeric(work["raw_final_score"], errors="coerce")
    std = float(scores.std(ddof=0))
    work["raw_score_z"] = 0.0 if std == 0 else (scores - float(scores.mean())) / std
    work["sector_mean_z"] = work.groupby("sector")["raw_score_z"].transform("mean")
    work["industry_mean_z"] = work.groupby("industry")["raw_score_z"].transform("mean")
    work["sector_residual"] = work["raw_score_z"] - work["sector_mean_z"]
    work["industry_residual"] = work["raw_score_z"] - work["industry_mean_z"]
    work["combined_residual"] = work["raw_score_z"] - 0.5 * work["sector_mean_z"] - 0.5 * work["industry_mean_z"]
    for col in ["sector_residual", "industry_residual", "combined_residual"]:
        rank_col = f"{col}_rank"
        work = work.sort_values([col, "raw_final_score", "ticker"], ascending=[False, False, True]).reset_index(drop=True)
        work[rank_col] = np.arange(1, len(work) + 1)
    return work.sort_values("raw_rank").reset_index(drop=True)


def residual_comparison(frame: pd.DataFrame, residual: pd.DataFrame, rank_col: str, variant: str) -> dict[str, Any]:
    raw20 = set(frame.nsmallest(20, "raw_rank")["ticker"])
    raw50 = set(frame.nsmallest(50, "raw_rank")["ticker"])
    top20 = residual.nsmallest(20, rank_col)
    top50 = residual.nsmallest(50, rank_col)
    raw_mean = frame.nsmallest(20, "raw_rank")["raw_final_score"].mean()
    return {
        "variant": variant,
        "top20_overlap": len(raw20 & set(top20["ticker"])),
        "top50_overlap": len(raw50 & set(top50["ticker"])),
        "top20_largest_sector_weight": r3.exposure_stats(top20.rename(columns={"raw_rank": "rank"}), 20, "residual_top20")["largest_sector_weight"],
        "top20_largest_industry_weight": r3.exposure_stats(top20.rename(columns={"raw_rank": "rank"}), 20, "residual_top20")["largest_industry_weight"],
        "mean_raw_score_top20": float(top20["raw_final_score"].mean()),
        "raw_score_retention_ratio": float(top20["raw_final_score"].mean() / raw_mean) if raw_mean else 0.0,
        "average_rank_displacement": float((top20[rank_col] - top20["raw_rank"]).abs().mean()),
    }


def classify_dependency(combined_overlap: int, combined_spearman: float, sector_pct: float, industry_pct: float) -> str:
    if combined_overlap >= 14 or combined_spearman >= 0.85:
        return "EXPOSURE_DOMINATED"
    if 8 <= combined_overlap <= 13 and sector_pct >= 0.75 and industry_pct >= 0.70:
        return "MIXED_EXPOSURE_AND_SELECTION"
    if combined_overlap < 8 and sector_pct >= 0.80 and industry_pct >= 0.75:
        return "SELECTION_WITHIN_CONCENTRATED_EXPOSURE"
    return "UNRESOLVED"


def status_for(classification: str) -> tuple[str, str]:
    if classification == "EXPOSURE_DOMINATED":
        return "WARN_V21_111_R4_D_EXPOSURE_DOMINATED", "D_ALPHA_LIKELY_EXPOSURE_DOMINATED_RESEARCH_ONLY"
    if classification == "MIXED_EXPOSURE_AND_SELECTION":
        return "PARTIAL_PASS_V21_111_R4_MIXED_EXPOSURE_AND_SELECTION", "D_ALPHA_MIXED_EXPOSURE_AND_STOCK_SELECTION_RESEARCH_ONLY"
    if classification == "SELECTION_WITHIN_CONCENTRATED_EXPOSURE":
        return "PASS_V21_111_R4_SELECTION_WITHIN_CONCENTRATED_EXPOSURE", "D_HAS_WITHIN_EXPOSURE_SELECTION_SIGNAL_RESEARCH_ONLY"
    return "PARTIAL_PASS_V21_111_R4_UNRESOLVED_DEPENDENCY", "D_EXPOSURE_DEPENDENCY_UNRESOLVED_RESEARCH_ONLY"


def blocked_summary(root: Path, out: Path, before: dict[str, Any], reason: str) -> dict[str, Any]:
    modified = protected_modified(before, root)
    summary = {field: None for field in SUMMARY_FIELDS}
    summary.update({
        "stage": STAGE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "final_status": "PARTIAL_PASS_V21_111_R4_BLOCKED_MISSING_REQUIRED_INPUT",
        "decision": "D_EXPOSURE_DEPENDENCY_BLOCKED_INPUT_MISSING",
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": modified,
        "raw_d_input_path": RAW_D_REL.as_posix(),
        "exposure_metadata_input_path": "",
        "rows_loaded": 0,
        "eligible_rows": 0,
        "factor_detail_available": False,
        "forward_data_available": False,
        "matured_observations": 0,
        "source_files_modified": modified,
        "protected_paths_verified": list(before.keys()),
        "blocker_reason": reason,
        "output_dir": r3.rel(root, out),
    })
    for name in [
        "sector_dependency_summary.csv", "industry_dependency_summary.csv",
        "within_sector_rank_detail.csv", "within_sector_alpha_summary.csv",
        "within_industry_rank_detail.csv", "within_industry_alpha_summary.csv",
        "exposure_only_baseline_comparison.csv", "residual_stock_selection_rankings.csv",
        "residual_vs_raw_d_comparison.csv",
    ]:
        r3.write_csv(out / name, [])
    r3.write_json(out / SUMMARY_JSON, summary)
    (out / REPORT_TXT).write_text(f"{STAGE}\nFINAL_STATUS={summary['final_status']}\nDECISION={summary['decision']}\n{reason}\n", encoding="utf-8")
    return summary


def run(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    out = output_dir(root, output_override)
    before = snapshot_protected(root)
    loaded, metadata_path, factor_available = load_inputs(root)
    frame = eligible_frame(loaded)
    if frame.empty or metadata_path is None:
        summary = blocked_summary(root, out, before, "raw D or exposure metadata unavailable")
        print(f"FINAL_STATUS={summary['final_status']}")
        print(f"DECISION={summary['decision']}")
        print(f"OUTPUT_DIR={summary['output_dir']}")
        return summary

    sector_rows = dependency_summary(frame, "sector")
    industry_rows = dependency_summary(frame, "industry")
    sector_detail = add_within_ranks(frame, "sector", 5, "within_sector_rank", "within_sector_percentile")
    industry_detail = add_within_ranks(frame, "industry", 3, "within_industry_rank", "within_industry_percentile")
    sector_alpha = within_alpha_summary(sector_detail, "sector", "within_sector_percentile")
    industry_alpha = within_alpha_summary(industry_detail, "industry", "within_industry_percentile")
    exposure_ranked = exposure_only_rankings(frame)
    exposure_comparisons = [
        compare_ranking(frame, exposure_ranked["sector_mean_score"], "sector_mean_score"),
        compare_ranking(frame, exposure_ranked["industry_mean_score"], "industry_mean_score"),
        compare_ranking(frame, exposure_ranked["combined_exposure_score"], "combined_exposure_score"),
    ]
    residual = residual_rankings(frame)
    residual_rows = [
        residual_comparison(frame, residual, "sector_residual_rank", "sector_residual"),
        residual_comparison(frame, residual, "industry_residual_rank", "industry_residual"),
        residual_comparison(frame, residual, "combined_residual_rank", "combined_residual"),
    ]

    r3.write_csv(out / "sector_dependency_summary.csv", sector_rows)
    r3.write_csv(out / "industry_dependency_summary.csv", industry_rows)
    r3.write_csv(out / "within_sector_rank_detail.csv", sector_detail.to_dict("records"))
    r3.write_csv(out / "within_sector_alpha_summary.csv", sector_alpha)
    r3.write_csv(out / "within_industry_rank_detail.csv", industry_detail.to_dict("records"))
    r3.write_csv(out / "within_industry_alpha_summary.csv", industry_alpha)
    r3.write_csv(out / "exposure_only_baseline_comparison.csv", exposure_comparisons)
    r3.write_csv(out / "residual_stock_selection_rankings.csv", residual.to_dict("records"))
    r3.write_csv(out / "residual_vs_raw_d_comparison.csv", residual_rows)

    raw20 = frame.nsmallest(20, "raw_rank")
    sector_pct = sector_detail[sector_detail["ticker"].isin(raw20["ticker"])]["within_sector_percentile"].median()
    industry_pct = industry_detail[industry_detail["ticker"].isin(raw20["ticker"])]["within_industry_percentile"].median()
    combined = next(row for row in exposure_comparisons if row["variant"] == "combined_exposure_score")
    residual_combined = next(row for row in residual_rows if row["variant"] == "combined_residual")
    classification = classify_dependency(combined["top20_overlap"], combined["spearman_rank_corr"], float(sector_pct), float(industry_pct))
    final_status, decision = status_for(classification)
    raw20_stats = r3.exposure_stats(frame.rename(columns={"raw_rank": "rank"}), 20, "raw_top20")
    raw50_stats = r3.exposure_stats(frame.rename(columns={"raw_rank": "rank"}), 50, "raw_top50")
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
        "raw_d_input_path": RAW_D_REL.as_posix(),
        "exposure_metadata_input_path": r3.rel(root, metadata_path),
        "rows_loaded": int(len(loaded)),
        "eligible_rows": int(len(frame)),
        "factor_detail_available": factor_available,
        "raw_top20_largest_sector": raw20_stats["largest_sector"],
        "raw_top20_largest_sector_weight": raw20_stats["largest_sector_weight"],
        "raw_top50_largest_sector_weight": raw50_stats["largest_sector_weight"],
        "raw_top20_largest_industry": raw20_stats["largest_industry"],
        "raw_top20_largest_industry_weight": raw20_stats["largest_industry_weight"],
        "raw_top50_largest_industry_weight": raw50_stats["largest_industry_weight"],
        "exposure_only_combined_top20_overlap": combined["top20_overlap"],
        "exposure_only_combined_top50_overlap": combined["top50_overlap"],
        "exposure_only_combined_spearman_corr": combined["spearman_rank_corr"],
        "exposure_only_combined_score_retention_ratio": combined["raw_score_retention_ratio"],
        "raw_top20_median_within_sector_percentile": float(sector_pct),
        "raw_top20_median_within_industry_percentile": float(industry_pct),
        "residual_combined_top20_overlap": residual_combined["top20_overlap"],
        "residual_combined_top50_overlap": residual_combined["top50_overlap"],
        "residual_combined_top20_largest_sector_weight": residual_combined["top20_largest_sector_weight"],
        "residual_combined_top20_largest_industry_weight": residual_combined["top20_largest_industry_weight"],
        "residual_combined_score_retention_ratio": residual_combined["raw_score_retention_ratio"],
        "dependency_classification": classification,
        "forward_data_available": False,
        "matured_observations": 0,
        "source_files_modified": modified,
        "protected_paths_verified": list(before.keys()),
        "output_dir": r3.rel(root, out),
    }
    r3.write_json(out / SUMMARY_JSON, summary)
    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"dependency_classification={classification}",
        f"exposure_only_combined_top20_overlap={combined['top20_overlap']}",
        f"exposure_only_combined_top50_overlap={combined['top50_overlap']}",
        f"exposure_only_combined_spearman_corr={combined['spearman_rank_corr']}",
        f"raw_top20_median_within_sector_percentile={float(sector_pct)}",
        f"raw_top20_median_within_industry_percentile={float(industry_pct)}",
        f"residual_combined_top20_overlap={residual_combined['top20_overlap']}",
        f"residual_combined_top50_overlap={residual_combined['top50_overlap']}",
        "forward_data_available=false",
        "matured_observations=0",
        f"protected_outputs_modified={str(modified).lower()}",
    ]
    (out / REPORT_TXT).write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"FINAL_STATUS={final_status}")
    print(f"DECISION={decision}")
    print(f"DEPENDENCY_CLASSIFICATION={classification}")
    print(f"EXPOSURE_ONLY_COMBINED_TOP20_OVERLAP={combined['top20_overlap']}")
    print(f"EXPOSURE_ONLY_COMBINED_TOP50_OVERLAP={combined['top50_overlap']}")
    print(f"EXPOSURE_ONLY_COMBINED_SPEARMAN_CORR={combined['spearman_rank_corr']}")
    print(f"RAW_TOP20_MEDIAN_WITHIN_SECTOR_PERCENTILE={float(sector_pct)}")
    print(f"RAW_TOP20_MEDIAN_WITHIN_INDUSTRY_PERCENTILE={float(industry_pct)}")
    print(f"RESIDUAL_COMBINED_TOP20_OVERLAP={residual_combined['top20_overlap']}")
    print(f"RESIDUAL_COMBINED_TOP50_OVERLAP={residual_combined['top50_overlap']}")
    print("FORWARD_DATA_AVAILABLE=false")
    print("MATURED_OBSERVATIONS=0")
    print(f"OUTPUT_DIR={summary['output_dir']}")
    print(f"PROTECTED_OUTPUTS_MODIFIED={str(modified).lower()}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    run(args.root, args.output_dir)


if __name__ == "__main__":
    main()
