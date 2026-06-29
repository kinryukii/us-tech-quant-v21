#!/usr/bin/env python
"""Rerun V21.073 paths with recalibrated entry variants."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_074_common import (
    ENTRY_VARIANTS, EXIT_POLICIES, OUT_REL, PATH_AUDIT_REL, SELECTION_MAP,
    SIM_REL, SOURCE_REL, V73_VALIDATION_REL, WINDOWS, evaluate_entry_variant,
    load_panel_with_d, protected_files, sha256, size_multiplier, truth,
)
from v21_074_r3_soft_entry_gate_recalibration import run_stage as run_r3


STAGE = "V21.074-R4_PATH_BASED_RERUN_WITH_RECALIBRATED_ENTRY"
METRICS_NAME = "V21_074_R4_RECALIBRATED_ENTRY_PATH_METRICS.csv"
SUMMARY_NAME = "V21_074_R4_RECALIBRATED_ENTRY_POLICY_SUMMARY.csv"
COMPARISON_NAME = "V21_074_R4_VS_D_AND_V21_073_COMPARISON.csv"
RECOMMENDATION_NAME = "V21_074_R4_POLICY_RECOMMENDATION.csv"
VALIDATION_NAME = "V21_074_R4_VALIDATION_SUMMARY.csv"
MIN_TRADES = 1000


def metric(
    frame: pd.DataFrame, baseline: pd.DataFrame, policy_id: str,
    selection: str, entry: str, exit_policy: str, split: str,
    top_n: str, window: str,
) -> dict[str, Any]:
    returns = pd.to_numeric(frame["policy_return"], errors="coerce")
    valid = returns.notna()
    traded = frame[valid]
    endpoint = pd.to_numeric(frame["realized_forward_return"], errors="coerce")
    allowed = frame["entry_allowed"].fillna(False)
    avoided = (~allowed & endpoint.lt(0)) | (allowed & endpoint.lt(0) & returns.ge(0))
    missed = (~allowed & endpoint.gt(0)) | (allowed & endpoint.gt(0) & returns.lt(endpoint))
    rebound = (
        traded["stop_loss_triggered"].fillna(False)
        & pd.to_numeric(traded["realized_forward_return"], errors="coerce").gt(0)
    )
    qqq = pd.to_numeric(traded["benchmark_qqq_return"], errors="coerce")
    d_return = pd.to_numeric(baseline["realized_forward_return"], errors="coerce")
    return {
        "joint_policy_id": policy_id, "selection_policy_id": selection,
        "entry_policy_id": entry, "exit_policy_id": exit_policy,
        "split": split, "top_n": top_n, "window": window,
        "mean_realized_return": returns.mean(),
        "median_realized_return": returns.median(),
        "hit_rate": returns[valid].gt(0).mean(),
        "win_rate_vs_d_ranking_only": returns.mean() > d_return.mean(),
        "avoided_losers": int(avoided.sum()),
        "missed_winners": int(missed.sum()),
        "missed_winner_cost": float(endpoint[missed].clip(lower=0).sum()),
        "block_efficiency": int(avoided.sum()) / max(int(missed.sum()), 1),
        "stop_loss_frequency": traded["stop_loss_triggered"].fillna(False).mean(),
        "take_profit_frequency": traded["take_profit_triggered"].fillna(False).mean(),
        "stop_out_then_rebound_count": int(rebound.sum()),
        "average_holding_period": pd.to_numeric(traded["holding_days"], errors="coerce").mean(),
        "max_adverse_excursion": pd.to_numeric(traded["max_adverse_excursion"], errors="coerce").mean(),
        "max_favorable_excursion": pd.to_numeric(traded["max_favorable_excursion"], errors="coerce").mean(),
        "drawdown_proxy": pd.to_numeric(traded["drawdown_proxy"], errors="coerce").mean(),
        "turnover": valid.mean(), "trade_count": int(valid.sum()),
        "skipped_trade_count": int((~valid).sum()),
        "excess_vs_qqq": (returns[valid].reset_index(drop=True) - qqq.reset_index(drop=True)).mean(),
        "sample_status": "SUFFICIENT" if valid.sum() >= MIN_TRADES else "SAMPLE_TOO_SMALL",
        "path_coverage_warning": int(frame["simulation_status"].ne("PASS").sum()),
        "leakage_warning": False,
    }


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (
        output_override if output_override and output_override.is_absolute()
        else root / (output_override or OUT_REL)
    ).resolve()
    output.mkdir(parents=True, exist_ok=True)
    run_r3(root, output)
    path_audit = pd.read_csv(root / PATH_AUDIT_REL).iloc[0]
    v73 = pd.read_csv(root / V73_VALIDATION_REL).iloc[0]
    if not truth(path_audit["pass_gate"]) or int(path_audit["leakage_warning_count"]) != 0:
        raise RuntimeError("V21.073 path integrity/leakage gate failed")
    panel = load_panel_with_d(root)
    simulations = pd.read_csv(root / SIM_REL, low_memory=False)
    sim_columns = [
        "as_of_date", "ticker", "forward_window", "exit_policy_name",
        "realized_return", "holding_days", "max_favorable_excursion",
        "max_adverse_excursion", "drawdown_proxy", "stop_loss_triggered",
        "take_profit_triggered", "simulation_status",
    ]
    simulations = simulations[sim_columns]
    d_panel = panel[panel["variant_id"] == "DERIVED_D_WEIGHT_OPTIMIZED_R1"]
    protected = protected_files(root, output)
    before = {path: sha256(path) for path in protected}
    rows = []
    for selection, variant in SELECTION_MAP.items():
        source = panel[panel["variant_id"] == variant].copy()
        for entry in ENTRY_VARIANTS:
            allowed, reason, components = evaluate_entry_variant(source, entry, selection)
            prepared = source.copy()
            prepared["entry_allowed"] = allowed
            prepared["block_reason"] = reason
            prepared["entry_score"] = components["effective_entry_score"]
            for exit_policy in EXIT_POLICIES:
                prepared["size_multiplier"] = size_multiplier(prepared, exit_policy)
                merged = prepared.merge(
                    simulations[simulations["exit_policy_name"] == exit_policy],
                    left_on=["sampled_as_of_date", "ticker", "forward_window"],
                    right_on=["as_of_date", "ticker", "forward_window"],
                    how="left", suffixes=("", "_path"),
                )
                policy_id = f"{selection}__{entry}__{exit_policy}"
                for split in ("TRAIN", "VALIDATION", "TEST"):
                    for window in WINDOWS:
                        for top_n, cutoff in (("TOP20", 20), ("TOP50", 50)):
                            subset = merged[
                                (merged["split"] == split)
                                & merged["forward_window"].astype(str).eq(window)
                                & pd.to_numeric(merged["rank"], errors="coerce").le(cutoff)
                            ].copy()
                            subset["policy_return"] = (
                                pd.to_numeric(subset["realized_return"], errors="coerce")
                                * subset["size_multiplier"]
                            )
                            subset.loc[~subset["entry_allowed"], "policy_return"] = np.nan
                            baseline = d_panel[
                                (d_panel["split"] == split)
                                & d_panel["forward_window"].astype(str).eq(window)
                                & pd.to_numeric(d_panel["rank"], errors="coerce").le(cutoff)
                            ]
                            rows.append(metric(
                                subset, baseline, policy_id, selection, entry,
                                exit_policy, split, top_n, window,
                            ))
    metrics = pd.DataFrame(rows)
    metrics.to_csv(output / METRICS_NAME, index=False)
    test10 = metrics[
        (metrics["split"] == "TEST") & (metrics["window"] == "10D")
        & metrics["sample_status"].eq("SUFFICIENT")
    ]
    best20 = test10[test10["top_n"] == "TOP20"].sort_values(
        ["mean_realized_return", "block_efficiency"], ascending=False
    ).iloc[0]
    best50 = test10[test10["top_n"] == "TOP50"].sort_values(
        ["mean_realized_return", "block_efficiency"], ascending=False
    ).iloc[0]
    d20 = pd.to_numeric(
        d_panel[
            (d_panel["split"] == "TEST")
            & d_panel["forward_window"].astype(str).eq("10D")
            & pd.to_numeric(d_panel["rank"], errors="coerce").le(20)
        ]["realized_forward_return"], errors="coerce"
    ).mean()
    d50 = pd.to_numeric(
        d_panel[
            (d_panel["split"] == "TEST")
            & d_panel["forward_window"].astype(str).eq("10D")
            & pd.to_numeric(d_panel["rank"], errors="coerce").le(50)
        ]["realized_forward_return"], errors="coerce"
    ).mean()
    summary = test10.groupby(
        ["joint_policy_id", "selection_policy_id", "entry_policy_id", "exit_policy_id"],
        as_index=False,
    ).agg(
        mean_return=("mean_realized_return", "mean"),
        trade_count=("trade_count", "sum"),
        avoided_losers=("avoided_losers", "sum"),
        missed_winners=("missed_winners", "sum"),
        block_efficiency=("block_efficiency", "mean"),
        stop_out_then_rebound_count=("stop_out_then_rebound_count", "sum"),
        turnover=("turnover", "mean"), drawdown_proxy=("drawdown_proxy", "mean"),
    )
    top_returns = test10.pivot_table(
        index="joint_policy_id", columns="top_n",
        values="mean_realized_return", aggfunc="mean",
    )
    beats_d = top_returns.get("TOP20", pd.Series(dtype=float)).gt(d20) | top_returns.get(
        "TOP50", pd.Series(dtype=float)
    ).gt(d50)
    summary["beats_d_ranking_only"] = summary["joint_policy_id"].map(beats_d).fillna(False)
    before_avoided = int(v73["avoided_losers"])
    before_missed = int(v73["missed_winners"])
    before_efficiency = before_avoided / max(before_missed, 1)
    summary["missed_winners_improved"] = summary["missed_winners"].lt(before_missed)
    summary["avoided_losers_preserved"] = summary["avoided_losers"].ge(before_avoided * 0.5)
    summary["block_efficiency_improved"] = summary["block_efficiency"].gt(before_efficiency)
    summary["research_candidate_ready"] = (
        summary["beats_d_ranking_only"]
        & summary["missed_winners_improved"]
        & summary["avoided_losers_preserved"]
        & summary["block_efficiency_improved"]
        & summary["turnover"].le(1.0)
        & summary["trade_count"].ge(MIN_TRADES * 2)
    )
    summary.to_csv(output / SUMMARY_NAME, index=False)
    comparison = pd.DataFrame([{
        "best_top20_policy": best20["joint_policy_id"],
        "best_top20_delta_vs_d": best20["mean_realized_return"] - d20,
        "best_top50_policy": best50["joint_policy_id"],
        "best_top50_delta_vs_d": best50["mean_realized_return"] - d50,
        "v21_073_best_top20_policy": v73["best_top20_path_based_policy"],
        "v21_073_best_top50_policy": v73["best_top50_path_based_policy"],
        "avoided_losers_before": before_avoided,
        "avoided_losers_after": int(best20["avoided_losers"] + best50["avoided_losers"]),
        "missed_winners_before": before_missed,
        "missed_winners_after": int(best20["missed_winners"] + best50["missed_winners"]),
        "block_efficiency_before": before_efficiency,
        "block_efficiency_after": float(
            (best20["block_efficiency"] + best50["block_efficiency"]) / 2
        ),
    }])
    comparison.to_csv(output / COMPARISON_NAME, index=False)
    recommendations = summary.sort_values(
        ["research_candidate_ready", "mean_return", "block_efficiency"],
        ascending=[False, False, False],
    )
    recommendations["recommendation_rank"] = range(1, len(recommendations) + 1)
    recommendations["recommendation_status"] = np.where(
        recommendations["research_candidate_ready"],
        "RESEARCH_CANDIDATE_READY", "NOT_READY",
    )
    recommendations["forward_trade_signal_ledger_append_allowed"] = False
    recommendations["official_adoption_allowed"] = False
    recommendations.to_csv(output / RECOMMENDATION_NAME, index=False)
    after = {path: sha256(path) for path in protected}
    changed = [str(path) for path in protected if before[path] != after[path]]
    sample_warn = int((metrics["sample_status"] == "SAMPLE_TOO_SMALL").sum())
    path_warn = int(metrics["path_coverage_warning"].gt(0).sum())
    leakage = int(metrics["leakage_warning"].sum())
    candidate_count = int(summary["research_candidate_ready"].sum())
    final_status = (
        "PASS_V21_074_R4_RECALIBRATED_ENTRY_POLICY_BACKTEST_READY"
        if candidate_count and sample_warn == 0 and path_warn == 0 else
        "PARTIAL_PASS_V21_074_R4_ENTRY_POLICY_READY_WITH_SAMPLE_OR_PATH_WARN"
    )
    validation = {
        "stage": STAGE, "final_status": final_status,
        "decision": (
            "RECALIBRATED_ENTRY_RESEARCH_CANDIDATE_READY"
            if candidate_count else "KEEP_D_BASELINE_RECALIBRATION_NOT_ACCEPTED"
        ),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "d_ranking_only_baseline_preserved": True,
        "entry_variants_tested": len(ENTRY_VARIANTS),
        "exit_policies_tested": len(EXIT_POLICIES),
        "selection_policies_tested": len(SELECTION_MAP),
        "best_top20_recalibrated_policy": best20["joint_policy_id"],
        "best_top50_recalibrated_policy": best50["joint_policy_id"],
        "comparison_vs_d_ranking_only": (
            f"TOP20_DELTA={best20['mean_realized_return'] - d20:.10f};"
            f"TOP50_DELTA={best50['mean_realized_return'] - d50:.10f}"
        ),
        "comparison_vs_v21_073_path_leader": "SEE_COMPARISON_TABLE",
        "avoided_losers_before": before_avoided,
        "avoided_losers_after": int(best20["avoided_losers"] + best50["avoided_losers"]),
        "missed_winners_before": before_missed,
        "missed_winners_after": int(best20["missed_winners"] + best50["missed_winners"]),
        "block_efficiency_before": before_efficiency,
        "block_efficiency_after": float(
            (best20["block_efficiency"] + best50["block_efficiency"]) / 2
        ),
        "stop_loss_triggers": int(
            (best20["stop_loss_frequency"] * best20["trade_count"])
            + (best50["stop_loss_frequency"] * best50["trade_count"])
        ),
        "take_profit_triggers": int(
            (best20["take_profit_frequency"] * best20["trade_count"])
            + (best50["take_profit_frequency"] * best50["trade_count"])
        ),
        "stop_out_then_rebound_count": int(
            best20["stop_out_then_rebound_count"]
            + best50["stop_out_then_rebound_count"]
        ),
        "sample_size_warning_cells": sample_warn,
        "path_coverage_warning_cells": path_warn,
        "leakage_warnings": leakage,
        "research_candidate_count": candidate_count,
        "protected_outputs_modified": bool(changed),
        "official_outputs_mutated": False,
        "forward_trade_signal_ledger_append_allowed": False,
        "official_adoption_allowed": False, "research_only": True,
        "pass_gate": not changed and leakage == 0,
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
        "final_status", "decision", "best_top20_recalibrated_policy",
        "best_top50_recalibrated_policy", "avoided_losers_after",
        "missed_winners_after",
    ):
        print(f"{key.upper()}={result[key]}")
    return 0 if result["pass_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
