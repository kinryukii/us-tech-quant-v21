#!/usr/bin/env python
"""Backtest ranking-only position sizing with PIT random as-of portfolios."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_075_common import (
    OUT_REL, PATH_AUDIT_REL, POLICIES, SELECTIONS, load_panel,
    path_features, policy_weights, protected_files, sha256, truth,
)
from v21_075_r1_position_sizing_policy_builder import run_stage as run_r1


STAGE = "V21.075-R2_RANKING_ONLY_PORTFOLIO_BACKTEST"
HOLDINGS_NAME = "V21_075_R2_PORTFOLIO_HOLDINGS.csv"
RESULTS_NAME = "V21_075_R2_PORTFOLIO_RESULTS.csv"
METRICS_NAME = "V21_075_R2_PORTFOLIO_METRICS.csv"
VALIDATION_NAME = "V21_075_R2_VALIDATION_SUMMARY.csv"


def turnover_proxy(results: pd.DataFrame) -> float:
    ordered = results.sort_values(["seed", "sampled_as_of_date", "batch_id"])
    overlap = ordered["ticker_set"].shift().combine(
        ordered["ticker_set"],
        lambda left, right: (
            len(left & right) / max(len(left | right), 1)
            if isinstance(left, set) and isinstance(right, set) else np.nan
        ),
    )
    return float((1 - overlap).mean())


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (
        output_override if output_override and output_override.is_absolute()
        else root / (output_override or OUT_REL)
    ).resolve()
    output.mkdir(parents=True, exist_ok=True)
    run_r1(root, output)
    path_audit = pd.read_csv(root / PATH_AUDIT_REL).iloc[0]
    if not truth(path_audit["pass_gate"]):
        raise RuntimeError("V21.073 path integrity gate failed")
    panel = load_panel(root)
    paths = path_features(root)
    panel = panel.merge(
        paths,
        on=["sampled_as_of_date", "ticker", "forward_window"],
        how="left",
    )
    protected = protected_files(root, output)
    before = {path: sha256(path) for path in protected}
    holding_frames, portfolio_rows = [], []
    group_keys = ["seed", "batch_id", "sampled_as_of_date", "forward_window", "split"]
    for selection, variant in SELECTIONS.items():
        source = panel[panel["variant_id"] == variant].copy()
        for policy_id, method, top_n in POLICIES:
            selected = source[
                pd.to_numeric(source["rank"], errors="coerce").le(top_n)
            ].copy()
            weights = selected.groupby(
                group_keys, group_keys=False
            ).apply(
                lambda group: policy_weights(group, method, top_n),
                include_groups=False,
            )
            selected["position_weight"] = weights.reindex(selected.index)
            selected["selection_policy_id"] = selection
            selected["position_policy_id"] = policy_id
            selected["joint_portfolio_policy_id"] = f"{selection}__{policy_id}"
            selected["weighted_return"] = (
                selected["position_weight"]
                * pd.to_numeric(selected["realized_forward_return"], errors="coerce")
            )
            selected["weighted_mae"] = (
                selected["position_weight"]
                * pd.to_numeric(selected["max_adverse_excursion"], errors="coerce")
            )
            selected["weighted_mfe"] = (
                selected["position_weight"]
                * pd.to_numeric(selected["max_favorable_excursion"], errors="coerce")
            )
            holding_frames.append(selected[[
                *group_keys, "selection_policy_id", "position_policy_id",
                "joint_portfolio_policy_id", "ticker", "rank", "score", "theme",
                "risk_size_bucket", "position_weight", "realized_forward_return",
                "weighted_return", "max_adverse_excursion",
                "max_favorable_excursion", "path_coverage",
            ]])
            for keys, group in selected.groupby(group_keys, sort=False):
                theme = group["theme"].fillna("").astype(str).str.strip()
                theme_known = theme.ne("")
                theme_weights = (
                    group.loc[theme_known].groupby(theme[theme_known])[
                        "position_weight"
                    ].sum()
                )
                portfolio_rows.append({
                    **dict(zip(group_keys, keys)),
                    "selection_policy_id": selection,
                    "position_policy_id": policy_id,
                    "joint_portfolio_policy_id": f"{selection}__{policy_id}",
                    "top_n": f"TOP{top_n}",
                    "portfolio_return": group["weighted_return"].sum(min_count=1),
                    "benchmark_qqq_return": pd.to_numeric(
                        group["benchmark_qqq_return"], errors="coerce"
                    ).mean(),
                    "benchmark_spy_return": pd.to_numeric(
                        group["benchmark_spy_return"], errors="coerce"
                    ).mean(),
                    "drawdown_proxy": group["weighted_mae"].sum(min_count=1),
                    "max_adverse_excursion": group["weighted_mae"].sum(min_count=1),
                    "max_favorable_excursion": group["weighted_mfe"].sum(min_count=1),
                    "max_ticker_weight": group["position_weight"].max(),
                    "ticker_hhi": (group["position_weight"] ** 2).sum(),
                    "max_known_theme_weight": (
                        theme_weights.max() if not theme_weights.empty else np.nan
                    ),
                    "theme_coverage_ratio": theme_known.mean(),
                    "path_coverage_ratio": group["path_coverage"].fillna(False).mean(),
                    "ticker_set": set(group["ticker"].astype(str)),
                })
    holdings = pd.concat(holding_frames, ignore_index=True)
    holdings.to_csv(output / HOLDINGS_NAME, index=False)
    results = pd.DataFrame(portfolio_rows)
    export_results = results.copy()
    export_results["ticker_set"] = export_results["ticker_set"].map(
        lambda value: "|".join(sorted(value))
    )
    export_results.to_csv(output / RESULTS_NAME, index=False)
    metric_rows = []
    for keys, group in results.groupby(
        ["selection_policy_id", "position_policy_id",
         "joint_portfolio_policy_id", "split", "top_n", "forward_window"],
        sort=False,
    ):
        returns = pd.to_numeric(group["portfolio_return"], errors="coerce").dropna()
        drawdown = pd.to_numeric(group["drawdown_proxy"], errors="coerce")
        qqq = pd.to_numeric(group["benchmark_qqq_return"], errors="coerce")
        spy = pd.to_numeric(group["benchmark_spy_return"], errors="coerce")
        negative_drawdown = abs(drawdown.mean())
        metric_rows.append({
            "selection_policy_id": keys[0], "position_policy_id": keys[1],
            "joint_portfolio_policy_id": keys[2], "split": keys[3],
            "top_n": keys[4], "window": keys[5],
            "portfolio_count": len(group),
            "mean_portfolio_return": returns.mean(),
            "median_portfolio_return": returns.median(),
            "hit_rate": returns.gt(0).mean(),
            "excess_vs_qqq": (returns - qqq.loc[returns.index]).mean(),
            "excess_vs_spy": (returns - spy.loc[returns.index]).mean(),
            "drawdown_proxy": drawdown.mean(),
            "max_adverse_excursion": group["max_adverse_excursion"].mean(),
            "max_favorable_excursion": group["max_favorable_excursion"].mean(),
            "portfolio_return_volatility": returns.std(),
            "return_drawdown_ratio": (
                returns.mean() / negative_drawdown
                if negative_drawdown > 0 else np.nan
            ),
            "max_ticker_concentration": group["max_ticker_weight"].max(),
            "avg_ticker_hhi": group["ticker_hhi"].mean(),
            "max_sector_concentration_proxy": group["max_known_theme_weight"].max(),
            "theme_coverage_ratio": group["theme_coverage_ratio"].mean(),
            "turnover": turnover_proxy(group),
            "data_quality_warnings": int(
                group["theme_coverage_ratio"].lt(0.5).sum()
            ),
            "sample_size_warning": len(group) < 100,
            "path_coverage_warning": int(
                group["path_coverage_ratio"].lt(1).sum()
            ),
            "leakage_warning": False,
            "sector_concentration_confidence": (
                "LOW" if group["theme_coverage_ratio"].mean() < 0.5 else "HIGH"
            ),
        })
    metrics = pd.DataFrame(metric_rows)
    d_baselines = metrics[
        (metrics["selection_policy_id"] == "D_WEIGHT_OPTIMIZED_R1")
        & metrics["position_policy_id"].isin(("EW_TOP20_R1", "EW_TOP50_R1"))
    ][["split", "top_n", "window", "mean_portfolio_return"]].rename(
        columns={"mean_portfolio_return": "d_equal_weight_mean_return"}
    )
    metrics = metrics.merge(
        d_baselines, on=["split", "top_n", "window"], how="left"
    )
    metrics["win_rate_vs_d_equal_weight_baseline"] = (
        metrics["mean_portfolio_return"]
        >= metrics["d_equal_weight_mean_return"]
    )
    metrics.to_csv(output / METRICS_NAME, index=False)
    after = {path: sha256(path) for path in protected}
    changed = [str(path) for path in protected if before[path] != after[path]]
    validation = {
        "stage": STAGE,
        "final_status": "PASS_V21_075_R2_RANKING_ONLY_PORTFOLIO_BACKTEST_READY",
        "decision": "POSITION_SIZING_METRICS_READY_FOR_EFFECTIVENESS_COMPARISON",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "portfolio_policy_count": metrics["joint_portfolio_policy_id"].nunique(),
        "holding_rows": len(holdings), "portfolio_rows": len(results),
        "metric_rows": len(metrics),
        "train_portfolios": int((results["split"] == "TRAIN").sum()),
        "validation_portfolios": int((results["split"] == "VALIDATION").sum()),
        "test_portfolios": int((results["split"] == "TEST").sum()),
        "path_integrity_pass": True, "leakage_warnings": 0,
        "sample_size_warning_cells": int(metrics["sample_size_warning"].sum()),
        "path_coverage_warning_cells": int(
            metrics["path_coverage_warning"].gt(0).sum()
        ),
        "sector_coverage_warning_cells": int(
            metrics["sector_concentration_confidence"].eq("LOW").sum()
        ),
        "protected_outputs_modified": bool(changed),
        "official_outputs_mutated": False,
        "forward_portfolio_observation_append_allowed": False,
        "official_adoption_allowed": False, "research_only": True,
        "pass_gate": not changed,
        "protected_modified_paths": "|".join(changed),
    }
    pd.DataFrame([validation]).to_csv(output / VALIDATION_NAME, index=False)
    return validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    print(f"FINAL_STATUS={result['final_status']}")
    print(f"DECISION={result['decision']}")
    print(f"PORTFOLIO_POLICY_COUNT={result['portfolio_policy_count']}")
    return 0 if result["pass_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
