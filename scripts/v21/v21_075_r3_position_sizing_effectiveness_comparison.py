#!/usr/bin/env python
"""Compare ranking-only sizing policies and apply research acceptance gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from v21_075_common import OUT_REL, truth
from v21_075_r2_ranking_only_portfolio_backtest import (
    METRICS_NAME, VALIDATION_NAME as R2_VALIDATION, run_stage as run_r2,
)


STAGE = "V21.075-R3_POSITION_SIZING_EFFECTIVENESS_COMPARISON"
COMPARISON_NAME = "V21_075_R3_POSITION_SIZING_EFFECTIVENESS_COMPARISON.csv"
RECOMMENDATION_NAME = "V21_075_R3_POSITION_SIZING_RECOMMENDATION.csv"
VALIDATION_NAME = "V21_075_R3_VALIDATION_SUMMARY.csv"


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, object]:
    root = root.resolve()
    output = (
        output_override if output_override and output_override.is_absolute()
        else root / (output_override or OUT_REL)
    ).resolve()
    if not (output / R2_VALIDATION).is_file():
        run_r2(root, output)
    r2 = pd.read_csv(output / R2_VALIDATION).iloc[0]
    metrics = pd.read_csv(output / METRICS_NAME, low_memory=False)
    test10 = metrics[
        (metrics["split"] == "TEST") & (metrics["window"] == "10D")
        & metrics["selection_policy_id"].eq("D_WEIGHT_OPTIMIZED_R1")
    ].copy()
    baseline = test10[
        test10["position_policy_id"].isin(("EW_TOP20_R1", "EW_TOP50_R1"))
    ][["top_n", "mean_portfolio_return", "drawdown_proxy",
       "return_drawdown_ratio", "turnover"]].set_index("top_n")
    test10["baseline_return"] = test10["top_n"].map(
        baseline["mean_portfolio_return"]
    )
    test10["baseline_drawdown"] = test10["top_n"].map(
        baseline["drawdown_proxy"]
    )
    test10["baseline_ratio"] = test10["top_n"].map(
        baseline["return_drawdown_ratio"]
    )
    test10["baseline_turnover"] = test10["top_n"].map(baseline["turnover"])
    test10["raw_return_delta"] = (
        test10["mean_portfolio_return"] - test10["baseline_return"]
    )
    test10["drawdown_improvement"] = (
        test10["drawdown_proxy"] - test10["baseline_drawdown"]
    )
    test10["risk_adjusted_improvement"] = (
        test10["return_drawdown_ratio"] - test10["baseline_ratio"]
    )
    test10["ticker_concentration_warning"] = (
        test10["max_ticker_concentration"] > np.where(
            test10["top_n"].eq("TOP20"), 0.10, 0.05
        ) + 1e-9
    )
    test10["sector_concentration_warning"] = (
        test10["sector_concentration_confidence"].eq("HIGH")
        & test10["max_sector_concentration_proxy"].gt(
            np.where(test10["top_n"].eq("TOP20"), 0.30, 0.20)
        )
    )
    test10["turnover_warning"] = (
        test10["turnover"] > test10["baseline_turnover"] + 0.10
    )
    test10["research_candidate_ready"] = (
        test10["raw_return_delta"].ge(-0.0005)
        & (
            test10["drawdown_improvement"].gt(0)
            | test10["risk_adjusted_improvement"].gt(0)
        )
        & ~test10["ticker_concentration_warning"]
        & ~test10["sector_concentration_warning"]
        & ~test10["turnover_warning"]
        & ~test10["sample_size_warning"].map(
            lambda value: str(value).upper() == "TRUE"
        )
    )
    test10.to_csv(output / COMPARISON_NAME, index=False)
    recommendations = test10.sort_values(
        ["research_candidate_ready", "return_drawdown_ratio",
         "mean_portfolio_return"],
        ascending=[False, False, False],
    ).copy()
    recommendations["recommendation_rank"] = range(1, len(recommendations) + 1)
    recommendations["recommendation_status"] = np.where(
        recommendations["research_candidate_ready"],
        "RESEARCH_CANDIDATE_READY", "NOT_READY",
    )
    recommendations["forward_portfolio_observation_append_allowed"] = False
    recommendations["official_adoption_allowed"] = False
    recommendations.to_csv(output / RECOMMENDATION_NAME, index=False)
    best_raw = test10.sort_values(
        ["mean_portfolio_return", "return_drawdown_ratio"],
        ascending=False,
    ).iloc[0]
    best_risk = test10.sort_values(
        ["return_drawdown_ratio", "mean_portfolio_return"],
        ascending=False,
    ).iloc[0]
    candidate_count = int(test10["research_candidate_ready"].sum())
    warning_count = int(
        test10["ticker_concentration_warning"].sum()
        + test10["sector_concentration_warning"].sum()
        + test10["turnover_warning"].sum()
    )
    final_status = (
        "PASS_V21_075_R3_POSITION_SIZING_BACKTEST_READY"
        if candidate_count and warning_count == 0
        else "PARTIAL_PASS_V21_075_R3_POSITION_SIZING_READY_WITH_RISK_OR_SAMPLE_WARN"
    )
    validation = {
        "stage": STAGE, "final_status": final_status,
        "decision": (
            "POSITION_SIZING_RESEARCH_CANDIDATE_READY"
            if candidate_count else "KEEP_D_EQUAL_WEIGHT_BASELINE"
        ),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "d_ranking_only_baseline_preserved": True,
        "position_policies_tested": int(
            metrics["position_policy_id"].nunique()
        ),
        "top20_result": (
            recommendations[
                recommendations["top_n"] == "TOP20"
            ].iloc[0]["joint_portfolio_policy_id"]
        ),
        "top50_result": (
            recommendations[
                recommendations["top_n"] == "TOP50"
            ].iloc[0]["joint_portfolio_policy_id"]
        ),
        "best_raw_return_policy": best_raw["joint_portfolio_policy_id"],
        "best_risk_adjusted_policy": best_risk["joint_portfolio_policy_id"],
        "comparison_vs_d_equal_weight_baseline": (
            f"BEST_RAW_DELTA={best_raw['raw_return_delta']:.10f};"
            f"BEST_RISK_RATIO_DELTA={best_risk['risk_adjusted_improvement']:.10f}"
        ),
        "comparison_vs_v21_074_recalibrated_entry": (
            "RANKING_ONLY_SIZING_PRESERVES_ALL_CANDIDATES_NO_ENTRY_SKIP"
        ),
        "drawdown_proxy_improvement": best_risk["drawdown_improvement"],
        "concentration_warnings": int(
            test10["ticker_concentration_warning"].sum()
            + test10["sector_concentration_warning"].sum()
        ),
        "turnover_warnings": int(test10["turnover_warning"].sum()),
        "sample_size_warning_cells": int(r2["sample_size_warning_cells"]),
        "path_coverage_warning_cells": int(r2["path_coverage_warning_cells"]),
        "leakage_warnings": int(r2["leakage_warnings"]),
        "research_candidate_count": candidate_count,
        "protected_outputs_modified": truth(r2["protected_outputs_modified"]),
        "official_outputs_mutated": False,
        "forward_portfolio_observation_append_allowed": False,
        "official_adoption_allowed": False, "research_only": True,
        "pass_gate": truth(r2["pass_gate"]) and int(r2["leakage_warnings"]) == 0,
    }
    pd.DataFrame([validation]).to_csv(output / VALIDATION_NAME, index=False)
    return validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    for key in (
        "final_status", "decision", "best_raw_return_policy",
        "best_risk_adjusted_policy",
    ):
        print(f"{key.upper()}={result[key]}")
    return 0 if result["pass_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
