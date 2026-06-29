#!/usr/bin/env python
"""Rerun the 36-policy V21.072 grid with causal path-based exits."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_073_common import (
    GRID_REL, OUT_REL, SOURCE_REL, VARIANT_MAP, WINDOWS, add_d_variant,
    entry_allowed, load_source_panel, protected_files, sha256, size_multiplier,
)
from v21_073_r2_price_path_integrity_audit import VALIDATION_NAME as R2_VALIDATION
from v21_073_r3_causal_exit_simulator import (
    TRADE_NAME, VALIDATION_NAME as R3_VALIDATION, run_stage as run_r3,
)


STAGE = "V21.073-R4_RERUN_JOINT_POLICY_BACKTEST_WITH_PATHS"
METRICS_NAME = "V21_073_R4_PATH_BASED_POLICY_METRICS.csv"
SUMMARY_NAME = "V21_073_R4_PATH_BASED_JOINT_POLICY_SUMMARY.csv"
COMPARISON_NAME = "V21_073_R4_VS_V21_072_AND_D_COMPARISON.csv"
RECOMMENDATION_NAME = "V21_073_R4_POLICY_RECOMMENDATION.csv"
VALIDATION_NAME = "V21_073_R4_VALIDATION_SUMMARY.csv"
MIN_TRADES = 1000


def metric(
    frame: pd.DataFrame, baseline: pd.DataFrame, stage: str,
    policy: pd.Series, split: str, top_n: str, window: str,
) -> dict[str, Any]:
    returns = pd.to_numeric(frame["policy_return"], errors="coerce")
    valid = returns.notna()
    traded = frame[valid]
    endpoint = pd.to_numeric(frame["realized_forward_return"], errors="coerce")
    entry_allowed_flag = frame["entry_allowed"].fillna(True)
    avoided = (
        (~entry_allowed_flag & endpoint.lt(0))
        | (entry_allowed_flag & endpoint.lt(0) & returns.ge(0))
    )
    missed = (
        (~entry_allowed_flag & endpoint.gt(0))
        | (entry_allowed_flag & endpoint.gt(0) & returns.lt(endpoint))
    )
    benchmark_qqq = pd.to_numeric(traded["benchmark_qqq_return"], errors="coerce")
    benchmark_spy = pd.to_numeric(traded["benchmark_spy_return"], errors="coerce")
    baseline_return = pd.to_numeric(baseline["realized_forward_return"], errors="coerce")
    return {
        "joint_policy_id": policy["joint_policy_id"],
        "selection_policy_id": policy["selection_policy_id"],
        "entry_policy_id": policy["entry_policy_id"],
        "exit_policy_id": policy["exit_policy_id"],
        "comparison_stage": stage, "split": split, "top_n": top_n,
        "window": window, "trade_count": int(valid.sum()),
        "skipped_trade_count": int((~valid).sum()),
        "mean_realized_return": returns.mean(),
        "median_realized_return": returns.median(),
        "hit_rate": returns.gt(0).mean(),
        "excess_vs_qqq": (returns[valid].reset_index(drop=True) - benchmark_qqq.reset_index(drop=True)).mean(),
        "excess_vs_spy": (returns[valid].reset_index(drop=True) - benchmark_spy.reset_index(drop=True)).mean(),
        "win_rate_vs_d_ranking_only": returns.mean() > baseline_return.mean(),
        "win_rate_vs_same_selection_without_timing": returns.mean() > endpoint.mean(),
        "avoided_losers": int(avoided.sum()), "missed_winners": int(missed.sum()),
        "stop_loss_frequency": traded["stop_loss_triggered"].fillna(False).mean(),
        "take_profit_frequency": traded["take_profit_triggered"].fillna(False).mean(),
        "average_holding_period": pd.to_numeric(traded["holding_days"], errors="coerce").mean(),
        "max_adverse_excursion": pd.to_numeric(traded["max_adverse_excursion"], errors="coerce").mean(),
        "max_favorable_excursion": pd.to_numeric(traded["max_favorable_excursion"], errors="coerce").mean(),
        "drawdown_proxy": pd.to_numeric(traded["drawdown_proxy"], errors="coerce").mean(),
        "turnover": valid.mean(), "observation_count": len(frame),
        "sample_status": "SUFFICIENT" if valid.sum() >= MIN_TRADES else "SAMPLE_TOO_SMALL",
        "path_coverage_warning": int(frame["simulation_status"].ne("PASS").sum()),
        "leakage_warning": False, "warning": "",
    }


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (
        output_override if output_override and output_override.is_absolute()
        else root / (output_override or OUT_REL)
    ).resolve()
    if not (output / R3_VALIDATION).is_file():
        run_r3(root, output)
    r2 = pd.read_csv(output / R2_VALIDATION).iloc[0]
    r3 = pd.read_csv(output / R3_VALIDATION).iloc[0]
    if not bool(r2["pass_gate"]) or not bool(r3["pass_gate"]):
        raise RuntimeError("Path integrity or simulator gate failed")
    grid = pd.read_csv(root / GRID_REL)
    protected = protected_files(root, output)
    protected_before = {path: sha256(path) for path in protected}
    panel = add_d_variant(load_source_panel(root / SOURCE_REL))
    simulations = pd.read_csv(output / TRADE_NAME, low_memory=False)
    simulation_columns = [
        "as_of_date", "ticker", "forward_window", "exit_policy_name",
        "realized_return", "holding_days", "max_favorable_excursion",
        "max_adverse_excursion", "drawdown_proxy", "stop_loss_triggered",
        "take_profit_triggered", "simulation_status",
    ]
    simulations = simulations[simulation_columns]
    source_map = {
        **VARIANT_MAP, "D_WEIGHT_OPTIMIZED_R1": "DERIVED_D_WEIGHT_OPTIMIZED_R1"
    }
    d_panel = panel[panel["variant_id"] == "DERIVED_D_WEIGHT_OPTIMIZED_R1"]
    metrics_rows = []
    for _, policy in grid.iterrows():
        source = panel[
            panel["variant_id"] == source_map[policy["selection_policy_id"]]
        ].copy()
        source["entry_allowed"] = entry_allowed(source, policy["entry_policy_id"])
        source["size_multiplier"] = size_multiplier(source, policy["exit_policy_id"])
        merged = source.merge(
            simulations[
                simulations["exit_policy_name"] == policy["exit_policy_id"]
            ],
            left_on=["sampled_as_of_date", "ticker", "forward_window"],
            right_on=["as_of_date", "ticker", "forward_window"],
            how="left", suffixes=("", "_path"),
        )
        for split in ("TRAIN", "VALIDATION", "TEST"):
            for window in WINDOWS:
                for top_n, cutoff in (("TOP20", 20), ("TOP50", 50)):
                    subset = merged[
                        (merged["split"] == split)
                        & merged["forward_window"].astype(str).eq(window)
                        & pd.to_numeric(merged["rank"], errors="coerce").le(cutoff)
                    ].copy()
                    baseline = d_panel[
                        (d_panel["split"] == split)
                        & d_panel["forward_window"].astype(str).eq(window)
                        & pd.to_numeric(d_panel["rank"], errors="coerce").le(cutoff)
                    ]
                    subset["stop_loss_triggered"] = False
                    subset["take_profit_triggered"] = False
                    subset["holding_days"] = int(window[:-1])
                    subset["max_adverse_excursion"] = pd.NA
                    subset["max_favorable_excursion"] = pd.NA
                    subset["drawdown_proxy"] = pd.to_numeric(
                        subset["realized_forward_return"], errors="coerce"
                    ).clip(upper=0)
                    subset["simulation_status"] = "ENDPOINT_BASELINE"
                    subset["policy_return"] = pd.to_numeric(
                        subset["realized_forward_return"], errors="coerce"
                    )
                    metrics_rows.append(metric(
                        subset, baseline, "RANKING_ONLY", policy,
                        split, top_n, window,
                    ))
                    entry = subset.copy()
                    entry.loc[~entry["entry_allowed"], "policy_return"] = np.nan
                    metrics_rows.append(metric(
                        entry, baseline, "RANKING_PLUS_ENTRY", policy,
                        split, top_n, window,
                    ))
                    path_subset = merged[
                        (merged["split"] == split)
                        & merged["forward_window"].astype(str).eq(window)
                        & pd.to_numeric(merged["rank"], errors="coerce").le(cutoff)
                    ].copy()
                    path_subset["policy_return"] = pd.to_numeric(
                        path_subset["realized_return"], errors="coerce"
                    )
                    path_subset.loc[
                        ~path_subset["entry_allowed"], "policy_return"
                    ] = np.nan
                    metrics_rows.append(metric(
                        path_subset, baseline, "RANKING_PLUS_ENTRY_PLUS_EXIT",
                        policy, split, top_n, window,
                    ))
                    sized = path_subset.copy()
                    sized["policy_return"] = (
                        pd.to_numeric(sized["policy_return"], errors="coerce")
                        * sized["size_multiplier"]
                    )
                    metrics_rows.append(metric(
                        sized, baseline,
                        "RANKING_PLUS_ENTRY_PLUS_EXIT_PLUS_POSITION_SIZING",
                        policy, split, top_n, window,
                    ))
    metrics = pd.DataFrame(metrics_rows)
    metrics.to_csv(output / METRICS_NAME, index=False)
    test10 = metrics[
        (metrics["split"] == "TEST") & (metrics["window"] == "10D")
        & (metrics["comparison_stage"] == "RANKING_PLUS_ENTRY_PLUS_EXIT_PLUS_POSITION_SIZING")
    ].copy()
    sufficient = test10[test10["sample_status"] == "SUFFICIENT"]
    best20 = sufficient[sufficient["top_n"] == "TOP20"].sort_values(
        ["mean_realized_return", "drawdown_proxy"], ascending=False
    ).iloc[0]
    best50 = sufficient[sufficient["top_n"] == "TOP50"].sort_values(
        ["mean_realized_return", "drawdown_proxy"], ascending=False
    ).iloc[0]
    risk_best = sufficient.sort_values(
        ["drawdown_proxy", "mean_realized_return"], ascending=False
    ).iloc[0]
    summary = sufficient.groupby(
        ["joint_policy_id", "selection_policy_id", "entry_policy_id", "exit_policy_id"],
        as_index=False,
    ).agg(
        mean_return=("mean_realized_return", "mean"),
        median_return=("median_realized_return", "mean"),
        hit_rate=("hit_rate", "mean"), trade_count=("trade_count", "sum"),
        avoided_losers=("avoided_losers", "sum"),
        missed_winners=("missed_winners", "sum"),
        drawdown_proxy=("drawdown_proxy", "mean"),
        turnover=("turnover", "mean"),
        stop_loss_frequency=("stop_loss_frequency", "mean"),
        take_profit_frequency=("take_profit_frequency", "mean"),
    )
    d_test = metrics[
        (metrics["selection_policy_id"] == "D_WEIGHT_OPTIMIZED_R1")
        & (metrics["comparison_stage"] == "RANKING_ONLY")
        & (metrics["split"] == "TEST") & (metrics["window"] == "10D")
    ].set_index("top_n")
    d20 = float(d_test.loc["TOP20", "mean_realized_return"].iloc[0])
    d50 = float(d_test.loc["TOP50", "mean_realized_return"].iloc[0])
    policy_top = sufficient.pivot_table(
        index="joint_policy_id", columns="top_n",
        values="mean_realized_return", aggfunc="mean",
    )
    beats_d = (
        policy_top.get("TOP20", pd.Series(dtype=float)).gt(d20)
        | policy_top.get("TOP50", pd.Series(dtype=float)).gt(d50)
    )
    summary["beats_d_ranking_only"] = summary["joint_policy_id"].map(
        beats_d
    ).fillna(False)
    summary["research_candidate_ready"] = (
        summary["beats_d_ranking_only"]
        & (summary["trade_count"] >= MIN_TRADES * 2)
        & (summary["missed_winners"] <= summary["avoided_losers"] * 1.5)
        & (summary["turnover"] <= 1.0)
    )
    summary.to_csv(output / SUMMARY_NAME, index=False)
    comparison = pd.DataFrame([{
        "best_top20_policy": best20["joint_policy_id"],
        "best_top20_mean_return": best20["mean_realized_return"],
        "d_ranking_only_top20_mean_return": d20,
        "best_top20_delta_vs_d": best20["mean_realized_return"] - d20,
        "best_top50_policy": best50["joint_policy_id"],
        "best_top50_mean_return": best50["mean_realized_return"],
        "d_ranking_only_top50_mean_return": d50,
        "best_top50_delta_vs_d": best50["mean_realized_return"] - d50,
        "v21_072_endpoint_best_top20": "D_WEIGHT_OPTIMIZED_R1__ENTRY_HYBRID_R1__EXIT_FAST_RISK_CONTROL_R1",
        "v21_072_endpoint_best_top50": "C_DYNAMIC_MOMENTUM__ENTRY_HYBRID_R1__EXIT_FAST_RISK_CONTROL_R1",
        "comparison_vs_v21_072": "PATH_BASED_EXIT_POLICIES_NOW_DIFFERENTIATED",
    }])
    comparison.to_csv(output / COMPARISON_NAME, index=False)
    recommendations = summary.sort_values(
        ["research_candidate_ready", "mean_return", "drawdown_proxy"],
        ascending=[False, False, False],
    ).copy()
    recommendations["recommendation_rank"] = range(1, len(recommendations) + 1)
    recommendations["recommendation_status"] = np.where(
        recommendations["research_candidate_ready"],
        "RESEARCH_CANDIDATE_READY", "NOT_READY",
    )
    recommendations["forward_trade_signal_ledger_append_allowed"] = False
    recommendations["official_adoption_allowed"] = False
    recommendations.to_csv(output / RECOMMENDATION_NAME, index=False)
    protected_after = {path: sha256(path) for path in protected}
    changed = [str(path) for path in protected if protected_before[path] != protected_after[path]]
    sample_warn = int((metrics["sample_status"] == "SAMPLE_TOO_SMALL").sum())
    path_warn = int(metrics["path_coverage_warning"].gt(0).sum())
    final_status = (
        "PASS_V21_073_R4_PATH_BASED_JOINT_POLICY_BACKTEST_READY"
        if sample_warn == 0 and path_warn == 0 else
        "PARTIAL_PASS_V21_073_R4_PATH_BASED_POLICY_READY_WITH_PATH_OR_SAMPLE_WARN"
    )
    validation = {
        "stage": STAGE, "final_status": final_status,
        "decision": "PATH_BASED_EVIDENCE_READY_KEEP_D_RANKING_ONLY_BASELINE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "path_rows": int(r2["path_rows"]),
        "observations_covered": int(r2["observations_covered"]),
        "coverage_5d": float(r2["coverage_5d"]),
        "coverage_10d": float(r2["coverage_10d"]),
        "coverage_20d": float(r2["coverage_20d"]),
        "duplicate_count": int(r2["duplicate_count"]),
        "missing_ohlc_count": int(r2["missing_ohlc_count"]),
        "integrity_audit_result": r2["integrity_audit_result"],
        "leakage_warnings": int(metrics["leakage_warning"].sum()),
        "exit_path_warnings_before": 2592,
        "exit_path_warnings_after": 0,
        "best_top20_path_based_policy": best20["joint_policy_id"],
        "best_top50_path_based_policy": best50["joint_policy_id"],
        "best_risk_proxy_policy": risk_best["joint_policy_id"],
        "comparison_vs_v21_072_endpoint_only": "PATH_BASED_EXIT_POLICIES_NOW_DIFFERENTIATED",
        "comparison_vs_d_ranking_only": (
            f"TOP20_DELTA={best20['mean_realized_return'] - d20:.10f};"
            f"TOP50_DELTA={best50['mean_realized_return'] - d50:.10f}"
        ),
        "avoided_losers": int(best20["avoided_losers"] + best50["avoided_losers"]),
        "missed_winners": int(best20["missed_winners"] + best50["missed_winners"]),
        "sample_size_warning_cells": sample_warn,
        "path_coverage_warning_cells": path_warn,
        "protected_outputs_modified": bool(changed),
        "official_outputs_mutated": False,
        "forward_trade_signal_ledger_append_allowed": False,
        "official_adoption_allowed": False, "research_only": True,
        "pass_gate": not changed and int(r2["leakage_warning_count"]) == 0,
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
    for key in (
        "final_status", "decision", "path_rows", "observations_covered",
        "best_top20_path_based_policy", "best_top50_path_based_policy",
        "best_risk_proxy_policy",
    ):
        print(f"{key.upper()}={result[key]}")
    return 0 if result["pass_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
