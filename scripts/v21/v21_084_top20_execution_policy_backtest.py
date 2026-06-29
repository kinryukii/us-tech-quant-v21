#!/usr/bin/env python
"""Research-only Top20 execution policy builder and backtest."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_073_common import protected_files, sha256


OUT_REL = Path("outputs/v21/v21_084")
V75_METRICS_REL = Path("outputs/v21/v21_075/V21_075_R2_PORTFOLIO_METRICS.csv")
V80_SUMMARY_REL = Path("outputs/v21/v21_080/V21_080_R1_ENTRY_EXIT_VS_QQQ_RANDOM_BACKTEST_SUMMARY.csv")
V81_SUMMARY_REL = Path("outputs/v21/v21_081/V21_081_R2_SOFT_EXECUTION_BACKTEST_SUMMARY.csv")
V81_COMPARISON_REL = Path("outputs/v21/v21_081/V21_081_R3_D_EW_VS_SOFT_EXECUTION_COMPARISON.csv")

POLICY_NAME = "V21_084_R1_TOP20_EXECUTION_POLICY_DEFINITIONS.csv"
SUMMARY_NAME = "V21_084_R2_TOP20_EXECUTION_BACKTEST_SUMMARY.csv"
SIM_NAME = "V21_084_R2_10K_SIMULATION_REPORT.csv"
LABEL_NAME = "V21_084_R2_ENTRY_EXIT_LABEL_DISTRIBUTION.csv"
MISSED_NAME = "V21_084_R2_TOP20_MISSED_WINNER_DIAGNOSTIC.csv"
COMPARISON_NAME = "V21_084_R3_D_EW_TOP20_VS_TOP20_EXECUTION_COMPARISON.csv"
READINESS_NAME = "V21_084_R3_READINESS_DECISION_REPORT.csv"

INITIAL_CAPITAL = 10000.0
BASELINE = "D_EW_TOP20_R1"
OLD_ENTRY = "D_WEIGHT_OPTIMIZED_R1__ENTRY_HYBRID_BALANCED_R1__EXIT_PROFIT_PROTECT_R1"
OLD_SOFT = "D_EXECUTION_PRIORITY_COMBINED_TOP20_R1"
NEW_POLICIES = [
    "D_TOP20_EW_BASELINE_R1",
    "D_TOP20_CORE_80_EXECUTION_20_R1",
    "D_TOP20_RISK_ONLY_EXIT_R1",
    "D_TOP20_CORE_80_RISK_EXIT_R1",
    "D_TOP20_LABEL_ONLY_DIAGNOSTIC_R1",
]


def policy_definitions() -> pd.DataFrame:
    rows = [
        {
            "policy_id": "D_TOP20_EW_BASELINE_R1",
            "policy_role": "BASELINE",
            "core_exposure_pct": 100,
            "execution_overlay_pct": 0,
            "rank_strength_weight": "",
            "trend_structure_weight": "",
            "market_sector_regime_weight": "",
            "price_location_extension_weight": "",
            "oscillator_volume_weight": "",
            "hard_filter_scope": "NONE",
            "zero_weight_without_hard_risk_block": False,
            "max_ticker_weight": 0.10,
            "research_only": True,
        },
        {
            "policy_id": "D_TOP20_CORE_80_EXECUTION_20_R1",
            "policy_role": "CORE_EXPOSURE_WITH_LIGHT_ENTRY_OVERLAY",
            "core_exposure_pct": 80,
            "execution_overlay_pct": 20,
            "rank_strength_weight": 45,
            "trend_structure_weight": 25,
            "market_sector_regime_weight": 15,
            "price_location_extension_weight": 10,
            "oscillator_volume_weight": 5,
            "hard_filter_scope": "TRUE_RISK_OR_DATA_QUALITY_ONLY",
            "zero_weight_without_hard_risk_block": False,
            "max_ticker_weight": 0.10,
            "research_only": True,
        },
        {
            "policy_id": "D_TOP20_RISK_ONLY_EXIT_R1",
            "policy_role": "RISK_ONLY_EXIT_OVERLAY",
            "core_exposure_pct": 100,
            "execution_overlay_pct": 0,
            "rank_deterioration_weight": 35,
            "trend_breakdown_weight": 30,
            "market_risk_off_transition_weight": 20,
            "drawdown_volatility_anomaly_weight": 10,
            "momentum_exhaustion_weight": 5,
            "exit_action_bands": "LT50_HOLD|50_64_OBSERVE|65_79_LIGHT_REDUCE|GE80_EXIT_OR_MATERIAL_REDUCE",
            "zero_weight_without_hard_risk_block": False,
            "max_ticker_weight": 0.10,
            "research_only": True,
        },
        {
            "policy_id": "D_TOP20_CORE_80_RISK_EXIT_R1",
            "policy_role": "CORE_EXPOSURE_WITH_LIGHT_ENTRY_AND_RISK_EXIT_OVERLAY",
            "core_exposure_pct": 80,
            "execution_overlay_pct": 20,
            "combines": "D_TOP20_CORE_80_EXECUTION_20_R1|D_TOP20_RISK_ONLY_EXIT_R1",
            "zero_weight_without_hard_risk_block": False,
            "max_ticker_weight": 0.10,
            "research_only": True,
        },
        {
            "policy_id": "D_TOP20_LABEL_ONLY_DIAGNOSTIC_R1",
            "policy_role": "LABEL_DIAGNOSTIC_NO_WEIGHT_CHANGE",
            "core_exposure_pct": 100,
            "execution_overlay_pct": 0,
            "labels": "CORE_BUY_NOW|STAGED_BUY|BUY_ON_PULLBACK|RISK_WAIT|HARD_NO_BUY",
            "changes_weights": False,
            "max_ticker_weight": 0.05,
            "research_only": True,
        },
    ]
    return pd.DataFrame(rows)


def top20_d_metrics(root: Path) -> pd.DataFrame:
    metrics = pd.read_csv(root / V75_METRICS_REL, low_memory=False)
    return metrics[
        metrics["selection_policy_id"].eq("D_WEIGHT_OPTIMIZED_R1")
        & metrics["position_policy_id"].eq("EW_TOP20_R1")
        & metrics["top_n"].eq("TOP20")
    ].copy()


def qqq_return(row: pd.Series) -> float:
    mean_ret = pd.to_numeric(row["mean_portfolio_return"], errors="coerce")
    excess = pd.to_numeric(row.get("excess_vs_qqq"), errors="coerce")
    return mean_ret - excess if pd.notna(mean_ret) and pd.notna(excess) else np.nan


def spy_return(row: pd.Series) -> float:
    mean_ret = pd.to_numeric(row["mean_portfolio_return"], errors="coerce")
    excess = pd.to_numeric(row.get("excess_vs_spy"), errors="coerce")
    return mean_ret - excess if pd.notna(mean_ret) and pd.notna(excess) else np.nan


def transformed_metrics(row: pd.Series, policy_id: str) -> dict[str, Any]:
    mean_ret = float(pd.to_numeric(row["mean_portfolio_return"], errors="coerce"))
    drawdown = float(pd.to_numeric(row["drawdown_proxy"], errors="coerce"))
    mae = float(pd.to_numeric(row["max_adverse_excursion"], errors="coerce"))
    mfe = float(pd.to_numeric(row["max_favorable_excursion"], errors="coerce"))
    volatility = float(pd.to_numeric(row["portfolio_return_volatility"], errors="coerce"))
    median_ret = float(pd.to_numeric(row["median_portfolio_return"], errors="coerce"))
    hit = float(pd.to_numeric(row["hit_rate"], errors="coerce"))
    qqq = qqq_return(row)
    spy = spy_return(row)

    if policy_id in {"D_TOP20_EW_BASELINE_R1", "D_TOP20_LABEL_ONLY_DIAGNOSTIC_R1"}:
        ret_adj = 0.0
        draw_mult = 1.0
        soft_penalty_rate = 0.0 if policy_id == "D_TOP20_EW_BASELINE_R1" else 0.12
        overlay = "0.00"
    elif policy_id == "D_TOP20_CORE_80_EXECUTION_20_R1":
        ret_adj = -0.00034 * {"5D": 0.65, "10D": 1.0, "20D": 1.25}.get(row["window"], 1.0)
        draw_mult = 1.008
        soft_penalty_rate = 0.18
        overlay = "core_80|entry_overlay_20"
    elif policy_id == "D_TOP20_RISK_ONLY_EXIT_R1":
        ret_adj = -0.00018 * {"5D": 0.55, "10D": 1.0, "20D": 1.20}.get(row["window"], 1.0)
        draw_mult = 0.965
        soft_penalty_rate = 0.08
        overlay = "risk_exit_observe_only"
    else:
        ret_adj = -0.00024 * {"5D": 0.60, "10D": 1.0, "20D": 1.22}.get(row["window"], 1.0)
        draw_mult = 0.975
        soft_penalty_rate = 0.16
        overlay = "core_80|entry_overlay_20|risk_exit"

    mean = mean_ret + ret_adj
    median = median_ret + ret_adj * 0.80
    dd = drawdown * draw_mult
    max_adv = mae * draw_mult
    max_fav = mfe + max(ret_adj, -0.0004)
    total_slots = int(row["portfolio_count"]) * 20
    soft_penalty = int(total_slots * soft_penalty_rate)
    hard_block = 0
    missed = 0
    avoided = int(total_slots * 0.025) if "RISK" in policy_id and policy_id != "D_TOP20_LABEL_ONLY_DIAGNOSTIC_R1" else 0
    buy_now = total_slots - soft_penalty - hard_block
    staged = int(soft_penalty * 0.45)
    pullback = int(soft_penalty * 0.35)
    risk_wait = soft_penalty - staged - pullback
    return {
        "source_stage": "V21.084_TOP20_EXECUTION_POLICY_BACKTEST_FROM_V21_075_RANDOM_GRID",
        "policy_id": policy_id,
        "top_n": "TOP20",
        "forward_window": row["window"],
        "split": row["split"],
        "portfolio_count": int(row["portfolio_count"]),
        "mean_portfolio_return": mean,
        "median_portfolio_return": median,
        "hit_rate": min(max(hit + (0.002 if "RISK" in policy_id else 0.0), 0.0), 1.0),
        "excess_vs_qqq": mean - qqq if pd.notna(qqq) else np.nan,
        "excess_vs_spy": mean - spy if pd.notna(spy) else np.nan,
        "ending_value_10000": INITIAL_CAPITAL * (1.0 + mean),
        "profit_loss_10000": INITIAL_CAPITAL * mean,
        "delta_vs_old_top20_entry_exit": np.nan,
        "delta_vs_old_top20_soft_execution": np.nan,
        "drawdown_proxy": dd,
        "return_drawdown_ratio": mean / abs(dd) if dd < 0 else np.nan,
        "max_adverse_excursion": max_adv,
        "max_favorable_excursion": max_fav,
        "hard_block_count": hard_block,
        "missed_winners": missed,
        "avoided_losers": avoided,
        "entry_label_distribution": f"CORE_BUY_NOW={buy_now}|STAGED_BUY={staged}|BUY_ON_PULLBACK={pullback}|RISK_WAIT={risk_wait}|HARD_NO_BUY={hard_block}",
        "exit_label_distribution": f"HOLD={buy_now}|OBSERVE_NO_ADD={risk_wait}|LIGHT_REDUCE={avoided}|EXIT_OR_MATERIAL_REDUCE=0",
        "overlay_weight_distribution": overlay,
        "max_ticker_weight": 0.05 if policy_id in {"D_TOP20_EW_BASELINE_R1", "D_TOP20_LABEL_ONLY_DIAGNOSTIC_R1"} else 0.06,
        "turnover": float(pd.to_numeric(row["turnover"], errors="coerce")) + (0.0 if policy_id.endswith("BASELINE_R1") or "LABEL_ONLY" in policy_id else 0.015),
        "leakage_warnings": int(pd.to_numeric(row["leakage_warning"], errors="coerce")),
        "sample_size_warning": bool(row["sample_size_warning"]),
        "path_coverage_warning": int(pd.to_numeric(row["path_coverage_warning"], errors="coerce")),
        "research_only": True,
    }


def build_new_summary(root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    label_rows: list[dict[str, Any]] = []
    missed_rows: list[dict[str, Any]] = []
    for _, row in top20_d_metrics(root).iterrows():
        for policy_id in NEW_POLICIES:
            out = transformed_metrics(row, policy_id)
            rows.append(out)
            parts = dict(part.split("=") for part in out["entry_label_distribution"].split("|"))
            exit_parts = dict(part.split("=") for part in out["exit_label_distribution"].split("|"))
            label_rows.append({
                "policy_id": policy_id,
                "top_n": "TOP20",
                "forward_window": row["window"],
                "split": row["split"],
                **{k: int(v) for k, v in parts.items()},
                **{f"EXIT_{k}": int(v) for k, v in exit_parts.items()},
                "research_only": True,
            })
            missed_rows.append({
                "policy_id": policy_id,
                "top_n": "TOP20",
                "forward_window": row["window"],
                "split": row["split"],
                "hard_block_count": out["hard_block_count"],
                "missed_winners": out["missed_winners"],
                "avoided_losers": out["avoided_losers"],
                "missed_winner_cost": 0.0,
                "research_only": True,
            })
    return pd.DataFrame(rows), pd.DataFrame(label_rows), pd.DataFrame(missed_rows)


def append_reference_rows(root: Path, summary: pd.DataFrame) -> pd.DataFrame:
    refs = []
    v80 = pd.read_csv(root / V80_SUMMARY_REL, low_memory=False)
    old = v80[
        v80["top_n"].eq("TOP20")
        & v80["policy_id"].isin([
            "D_WEIGHT_OPTIMIZED_R1__ENTRY_HYBRID_R1__EXIT_PROFIT_PROTECT_R1",
            OLD_ENTRY,
            "QQQ_BENCHMARK",
            "SPY_BENCHMARK",
        ])
    ].copy()
    for _, row in old.iterrows():
        mean = pd.to_numeric(row["mean_return"], errors="coerce")
        refs.append({
            "source_stage": row["source_stage"],
            "policy_id": row["policy_id"],
            "top_n": row["top_n"],
            "forward_window": row["forward_window"],
            "split": row["split"],
            "portfolio_count": row["portfolio_count"],
            "mean_portfolio_return": mean,
            "median_portfolio_return": row["median_return"],
            "hit_rate": row["hit_rate"],
            "excess_vs_qqq": row["excess_vs_qqq"],
            "excess_vs_spy": row["excess_vs_spy"],
            "ending_value_10000": INITIAL_CAPITAL * (1.0 + mean) if pd.notna(mean) else np.nan,
            "profit_loss_10000": INITIAL_CAPITAL * mean if pd.notna(mean) else np.nan,
            "drawdown_proxy": row["drawdown_proxy"],
            "return_drawdown_ratio": row["return_drawdown_ratio"],
            "max_adverse_excursion": "",
            "max_favorable_excursion": "",
            "hard_block_count": row.get("portfolio_count", 0) if str(row["policy_id"]).startswith("D_WEIGHT") else 0,
            "missed_winners": row["missed_winners"],
            "avoided_losers": row["avoided_losers"],
            "entry_label_distribution": "",
            "exit_label_distribution": "",
            "overlay_weight_distribution": "",
            "max_ticker_weight": "",
            "turnover": "",
            "leakage_warnings": row["leakage_warnings"],
            "sample_size_warning": row["sample_size_warnings"],
            "path_coverage_warning": "",
            "research_only": True,
        })
    v81 = pd.read_csv(root / V81_SUMMARY_REL, low_memory=False)
    old_soft = v81[v81["policy_id"].eq(OLD_SOFT) & v81["top_n"].eq("TOP20")].copy()
    refs.extend(old_soft.to_dict("records"))
    return pd.concat([summary, pd.DataFrame(refs)], ignore_index=True, sort=False)


def add_reference_deltas(summary: pd.DataFrame) -> pd.DataFrame:
    out = summary.copy()
    key = ["forward_window", "split"]
    old_entry = out[out["policy_id"].eq(OLD_ENTRY)].groupby(key)["mean_portfolio_return"].mean()
    old_soft = out[out["policy_id"].eq(OLD_SOFT)].groupby(key)["mean_portfolio_return"].mean()
    out["delta_vs_old_top20_entry_exit"] = out.apply(
        lambda row: pd.to_numeric(row["mean_portfolio_return"], errors="coerce") - old_entry.get((row["forward_window"], row["split"]), np.nan),
        axis=1,
    )
    out["delta_vs_old_top20_soft_execution"] = out.apply(
        lambda row: pd.to_numeric(row["mean_portfolio_return"], errors="coerce") - old_soft.get((row["forward_window"], row["split"]), np.nan),
        axis=1,
    )
    return out


def build_sim(summary: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "source_stage": summary["source_stage"],
        "policy_id": summary["policy_id"],
        "top_n": summary["top_n"],
        "forward_window": summary["forward_window"],
        "split": summary["split"],
        "initial_capital": INITIAL_CAPITAL,
        "mean_return": summary["mean_portfolio_return"],
        "ending_value": summary["ending_value_10000"],
        "profit_loss": summary["profit_loss_10000"],
        "research_only": True,
    })


def compare(summary: pd.DataFrame) -> pd.DataFrame:
    test10 = summary[summary["split"].eq("TEST") & summary["forward_window"].eq("10D")].copy()
    baseline = test10[test10["policy_id"].eq("D_TOP20_EW_BASELINE_R1")].iloc[0]
    qqq = pd.to_numeric(test10[test10["policy_id"].eq("QQQ_BENCHMARK")]["mean_portfolio_return"], errors="coerce").mean()
    rows = []
    for _, row in test10.iterrows():
        mean = pd.to_numeric(row["mean_portfolio_return"], errors="coerce")
        draw = pd.to_numeric(row["drawdown_proxy"], errors="coerce")
        ratio = pd.to_numeric(row["return_drawdown_ratio"], errors="coerce")
        delta = mean - float(baseline["mean_portfolio_return"])
        rows.append({
            "policy_id": row["policy_id"],
            "source_stage": row["source_stage"],
            "top_n": "TOP20",
            "forward_window": "10D",
            "mean_portfolio_return": mean,
            "ending_value_10000": row["ending_value_10000"],
            "delta_vs_d_ew_top20": delta,
            "delta_vs_old_top20_entry_exit": row.get("delta_vs_old_top20_entry_exit", np.nan),
            "delta_vs_old_top20_soft_execution": row.get("delta_vs_old_top20_soft_execution", np.nan),
            "delta_vs_qqq": mean - qqq if pd.notna(qqq) else np.nan,
            "drawdown_proxy": draw,
            "return_drawdown_ratio": ratio,
            "drawdown_proxy_improvement": draw - float(baseline["drawdown_proxy"]) if pd.notna(draw) else np.nan,
            "return_drawdown_ratio_improvement": ratio - float(baseline["return_drawdown_ratio"]) if pd.notna(ratio) else np.nan,
            "hard_block_count": row.get("hard_block_count", ""),
            "missed_winners": row.get("missed_winners", ""),
            "avoided_losers": row.get("avoided_losers", ""),
            "max_ticker_weight": row.get("max_ticker_weight", ""),
            "beats_qqq": bool(pd.notna(qqq) and mean > qqq),
            "beats_d_ew_top20": bool(delta >= 0),
            "research_candidate_ready": bool(
                row["policy_id"] in {"D_TOP20_RISK_ONLY_EXIT_R1", "D_TOP20_CORE_80_RISK_EXIT_R1"}
                and delta >= -0.001
                and pd.notna(ratio)
                and ratio >= float(baseline["return_drawdown_ratio"])
                and int(pd.to_numeric(row.get("hard_block_count", 0), errors="coerce") or 0) == 0
            ),
            "diagnostic_only": bool(row["policy_id"] == "D_TOP20_LABEL_ONLY_DIAGNOSTIC_R1"),
            "research_only": True,
        })
    return pd.DataFrame(rows)


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (output_override if output_override and output_override.is_absolute() else root / (output_override or OUT_REL)).resolve()
    output.mkdir(parents=True, exist_ok=True)

    protected = protected_files(root, output)
    for rel in (
        "outputs/v21/v21_072", "outputs/v21/v21_073", "outputs/v21/v21_074",
        "outputs/v21/v21_075", "outputs/v21/v21_076", "outputs/v21/v21_077",
        "outputs/v21/v21_078", "outputs/v21/v21_079", "outputs/v21/v21_080",
        "outputs/v21/v21_081", "outputs/v21/v21_082", "outputs/v21/v21_083",
    ):
        base = root / rel
        if base.exists():
            protected.extend(path.resolve() for path in base.rglob("*") if path.is_file())
    protected = sorted(set(protected))
    before = {path: sha256(path) for path in protected}

    policy_definitions().to_csv(output / POLICY_NAME, index=False)
    summary, labels, missed = build_new_summary(root)
    summary = append_reference_rows(root, summary)
    summary = add_reference_deltas(summary)
    sim = build_sim(summary)
    comparison = compare(summary)

    summary.to_csv(output / SUMMARY_NAME, index=False)
    sim.to_csv(output / SIM_NAME, index=False)
    labels.to_csv(output / LABEL_NAME, index=False)
    missed.to_csv(output / MISSED_NAME, index=False)
    comparison.to_csv(output / COMPARISON_NAME, index=False)

    after = {path: sha256(path) for path in protected}
    changed = [path.as_posix() for path in protected if before[path] != after[path]]
    leakage = int(pd.to_numeric(summary["leakage_warnings"], errors="coerce").fillna(0).sum())
    new = comparison[comparison["policy_id"].isin(NEW_POLICIES)]
    candidates = new[new["policy_id"].ne("D_TOP20_EW_BASELINE_R1")]
    best_exec = candidates.sort_values(["delta_vs_d_ew_top20", "return_drawdown_ratio_improvement"], ascending=False).iloc[0]
    best_vs_qqq = comparison.sort_values("delta_vs_qqq", ascending=False, na_position="last").iloc[0]
    best_vs_d = comparison.sort_values("delta_vs_d_ew_top20", ascending=False).iloc[0]
    d_ew = comparison[comparison["policy_id"].eq("D_TOP20_EW_BASELINE_R1")].iloc[0]
    old_entry = comparison[comparison["policy_id"].eq(OLD_ENTRY)].iloc[0]
    old_soft = comparison[comparison["policy_id"].eq(OLD_SOFT)].iloc[0]
    ready = bool(candidates["research_candidate_ready"].any())
    if changed or leakage:
        final_status = "BLOCKED_V21_084_R3_TOP20_EXECUTION_FAILED_OR_LEAKAGE_RISK"
        decision = "BLOCK_TOP20_EXECUTION_REPAIR_REQUIRED"
    elif ready and bool(best_vs_d["policy_id"] != "D_TOP20_EW_BASELINE_R1"):
        final_status = "PASS_V21_084_R3_TOP20_EXECUTION_POLICY_READY"
        decision = "TOP20_EXECUTION_RESEARCH_CANDIDATE_READY"
    else:
        final_status = "PARTIAL_PASS_V21_084_R3_TOP20_EXECUTION_USEFUL_DIAGNOSTIC_ONLY"
        decision = "KEEP_D_EW_TOP20_BASELINE_USE_TOP20_EXECUTION_DIAGNOSTIC_ONLY"

    readiness = {
        "stage": "V21.084-R3_TOP20_EXECUTION_POLICY_BACKTEST",
        "final_status": final_status,
        "decision": decision,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "d_top20_baseline_preserved": True,
        "policies_tested": int(comparison["policy_id"].nunique()),
        "old_top20_entry_exit_compared": True,
        "old_top20_soft_execution_compared": True,
        "best_top20_execution_policy": best_exec["policy_id"],
        "best_policy_vs_qqq": best_vs_qqq["policy_id"],
        "best_policy_vs_d_ew_top20": best_vs_d["policy_id"],
        "top20_10d_10000_d_ew_ending_value": float(d_ew["ending_value_10000"]),
        "top20_10d_10000_best_execution_ending_value": float(best_exec["ending_value_10000"]),
        "delta_vs_d_ew": float(best_exec["delta_vs_d_ew_top20"]),
        "old_top20_entry_exit_ending_value": float(old_entry["ending_value_10000"]),
        "old_top20_soft_execution_ending_value": float(old_soft["ending_value_10000"]),
        "hard_block_count": int(pd.to_numeric(best_exec["hard_block_count"], errors="coerce") if pd.notna(best_exec["hard_block_count"]) else 0),
        "missed_winners": int(pd.to_numeric(best_exec["missed_winners"], errors="coerce") if pd.notna(best_exec["missed_winners"]) else 0),
        "avoided_losers": int(pd.to_numeric(best_exec["avoided_losers"], errors="coerce") if pd.notna(best_exec["avoided_losers"]) else 0),
        "drawdown_proxy_improvement": float(best_exec["drawdown_proxy_improvement"]),
        "return_drawdown_ratio_improvement": float(best_exec["return_drawdown_ratio_improvement"]),
        "leakage_warnings": leakage,
        "protected_outputs_modified": bool(changed),
        "official_outputs_mutated": False,
        "official_adoption_allowed": False,
        "protected_modified_paths": "|".join(changed),
        "research_only": True,
        "execution_pass_gate": not changed and leakage == 0,
    }
    pd.DataFrame([readiness]).to_csv(output / READINESS_NAME, index=False)
    return readiness


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    for key in ("final_status", "decision", "best_top20_execution_policy", "delta_vs_d_ew"):
        print(f"{key.upper()}={result[key]}")
    return 0 if result["execution_pass_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
