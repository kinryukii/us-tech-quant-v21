#!/usr/bin/env python
"""Research-only V21.080 entry/exit vs QQQ and $10k simulation report."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_073_common import protected_files, sha256, truth


STAGE = "V21.080-R1_R2_ENTRY_EXIT_VS_QQQ_10K_REPORT"
OUT_REL = Path("outputs/v21/v21_080")
V73_METRICS_REL = Path("outputs/v21/v21_073/V21_073_R4_PATH_BASED_POLICY_METRICS.csv")
V73_VALIDATION_REL = Path("outputs/v21/v21_073/V21_073_R4_VALIDATION_SUMMARY.csv")
V74_METRICS_REL = Path("outputs/v21/v21_074/V21_074_R4_RECALIBRATED_ENTRY_PATH_METRICS.csv")
V74_VALIDATION_REL = Path("outputs/v21/v21_074/V21_074_R4_VALIDATION_SUMMARY.csv")
V75_METRICS_REL = Path("outputs/v21/v21_075/V21_075_R2_PORTFOLIO_METRICS.csv")

SUMMARY_NAME = "V21_080_R1_ENTRY_EXIT_VS_QQQ_RANDOM_BACKTEST_SUMMARY.csv"
SIM_NAME = "V21_080_R2_10K_SIMULATION_REPORT.csv"
READINESS_NAME = "V21_080_R2_READINESS_DECISION_REPORT.csv"

INITIAL_CAPITAL = 10000.0
V73_TOP20 = "D_WEIGHT_OPTIMIZED_R1__ENTRY_HYBRID_R1__EXIT_PROFIT_PROTECT_R1"
V73_TOP50 = "C_DYNAMIC_MOMENTUM__ENTRY_HYBRID_R1__EXIT_TREND_HOLD_R1"
V74_TOP20 = "D_WEIGHT_OPTIMIZED_R1__ENTRY_HYBRID_BALANCED_R1__EXIT_PROFIT_PROTECT_R1"
V74_TOP50 = "B_STATIC_MOMENTUM__ENTRY_HYBRID_RELAXED_R1__EXIT_TREND_HOLD_R1"


def safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return np.nan


def metric_row(
    source_stage: str,
    policy_id: str,
    top_n: str,
    window: str,
    split: str,
    portfolio_count: Any,
    mean_return: Any,
    median_return: Any,
    hit_rate: Any,
    drawdown_proxy: Any,
    excess_vs_qqq: Any = np.nan,
    excess_vs_spy: Any = np.nan,
    avoided_losers: Any = "",
    missed_winners: Any = "",
    stop_loss_triggers: Any = "",
    take_profit_triggers: Any = "",
    leakage_warnings: Any = 0,
    sample_size_warnings: Any = 0,
    interpretation: str = "",
) -> dict[str, Any]:
    mean = safe_float(mean_return)
    drawdown = safe_float(drawdown_proxy)
    ex_qqq = safe_float(excess_vs_qqq)
    ex_spy = safe_float(excess_vs_spy)
    return {
        "source_stage": source_stage,
        "policy_id": policy_id,
        "top_n": top_n,
        "forward_window": window,
        "split": split,
        "portfolio_count": portfolio_count,
        "mean_return": mean,
        "median_return": safe_float(median_return),
        "hit_rate": safe_float(hit_rate),
        "drawdown_proxy": drawdown,
        "return_drawdown_ratio": mean / abs(drawdown) if pd.notna(mean) and pd.notna(drawdown) and drawdown < 0 else np.nan,
        "excess_vs_qqq": ex_qqq,
        "excess_vs_spy": ex_spy,
        "qqq_benchmark_return": mean - ex_qqq if pd.notna(mean) and pd.notna(ex_qqq) else np.nan,
        "spy_benchmark_return": mean - ex_spy if pd.notna(mean) and pd.notna(ex_spy) else np.nan,
        "qqq_comparison_status": "available" if pd.notna(mean) and pd.notna(ex_qqq) else "unavailable",
        "spy_comparison_status": "available" if pd.notna(mean) and pd.notna(ex_spy) else "unavailable",
        "avoided_losers": avoided_losers,
        "missed_winners": missed_winners,
        "stop_loss_triggers": stop_loss_triggers,
        "take_profit_triggers": take_profit_triggers,
        "leakage_warnings": int(safe_float(leakage_warnings) if pd.notna(safe_float(leakage_warnings)) else 0),
        "sample_size_warnings": sample_size_warnings,
        "interpretation": interpretation,
        "research_only": True,
    }


def build_summary(root: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    v75 = pd.read_csv(root / V75_METRICS_REL, low_memory=False)
    d_rows = v75[
        v75["selection_policy_id"].eq("D_WEIGHT_OPTIMIZED_R1")
        & v75["position_policy_id"].isin(["EW_TOP20_R1", "EW_TOP50_R1"])
        & v75["split"].eq("TEST")
    ]
    for _, r in d_rows.iterrows():
        rows.append(metric_row(
            "V21.075_D_EQUAL_WEIGHT_BASELINE",
            f"D_WEIGHT_OPTIMIZED_R1__{r['position_policy_id']}",
            r["top_n"],
            r["window"],
            r["split"],
            r["portfolio_count"],
            r["mean_portfolio_return"],
            r["median_portfolio_return"],
            r["hit_rate"],
            r["drawdown_proxy"],
            r["excess_vs_qqq"],
            r["excess_vs_spy"],
            leakage_warnings=r.get("leakage_warning", 0),
            sample_size_warnings=r.get("sample_size_warning", False),
            interpretation="Current accepted D ranking-only equal-weight baseline.",
        ))
    v73_val = pd.read_csv(root / V73_VALIDATION_REL).iloc[0]
    v73 = pd.read_csv(root / V73_METRICS_REL, low_memory=False)
    v73 = v73[
        v73["joint_policy_id"].isin([V73_TOP20, V73_TOP50])
        & v73["comparison_stage"].eq("RANKING_PLUS_ENTRY_PLUS_EXIT_PLUS_POSITION_SIZING")
        & v73["split"].eq("TEST")
    ]
    for _, r in v73.iterrows():
        if (r["joint_policy_id"] == V73_TOP20 and r["top_n"] != "TOP20") or (r["joint_policy_id"] == V73_TOP50 and r["top_n"] != "TOP50"):
            continue
        rows.append(metric_row(
            "V21.073_PATH_BASED_ENTRY_EXIT",
            r["joint_policy_id"],
            r["top_n"],
            r["window"],
            r["split"],
            r["trade_count"],
            r["mean_realized_return"],
            r["median_realized_return"],
            r["hit_rate"],
            r["drawdown_proxy"],
            r["excess_vs_qqq"],
            r["excess_vs_spy"],
            avoided_losers=r["avoided_losers"],
            missed_winners=r["missed_winners"],
            stop_loss_triggers=r["stop_loss_frequency"],
            take_profit_triggers=r["take_profit_frequency"],
            leakage_warnings=r["leakage_warning"],
            sample_size_warnings=r["sample_status"],
            interpretation="V21.073 path-based leader; did not beat D ranking-only baseline.",
        ))
    v74 = pd.read_csv(root / V74_METRICS_REL, low_memory=False)
    v74_val = pd.read_csv(root / V74_VALIDATION_REL).iloc[0]
    v74 = v74[
        v74["joint_policy_id"].isin([V74_TOP20, V74_TOP50])
        & v74["split"].eq("TEST")
    ]
    for _, r in v74.iterrows():
        if (r["joint_policy_id"] == V74_TOP20 and r["top_n"] != "TOP20") or (r["joint_policy_id"] == V74_TOP50 and r["top_n"] != "TOP50"):
            continue
        rows.append(metric_row(
            "V21.074_RECALIBRATED_ENTRY_EXIT",
            r["joint_policy_id"],
            r["top_n"],
            r["window"],
            r["split"],
            r["trade_count"],
            r["mean_realized_return"],
            r["median_realized_return"],
            r["hit_rate"],
            r["drawdown_proxy"],
            r["excess_vs_qqq"],
            np.nan,
            avoided_losers=r["avoided_losers"],
            missed_winners=r["missed_winners"],
            stop_loss_triggers=r["stop_loss_frequency"],
            take_profit_triggers=r["take_profit_frequency"],
            leakage_warnings=r["leakage_warning"],
            sample_size_warnings=r["sample_status"],
            interpretation="V21.074 recalibrated entry/exit leader; recalibration not accepted.",
        ))
    summary = pd.DataFrame(rows)
    benchmark_rows = []
    for _, r in summary[summary["qqq_comparison_status"].eq("available")].iterrows():
        benchmark_rows.append(metric_row(
            "BENCHMARK_RECONSTRUCTED_FROM_EXCESS",
            "QQQ_BENCHMARK",
            r["top_n"],
            r["forward_window"],
            r["split"],
            r["portfolio_count"],
            r["qqq_benchmark_return"],
            r["qqq_benchmark_return"],
            np.nan,
            np.nan,
            0.0,
            np.nan,
            leakage_warnings=0,
            sample_size_warnings="BENCHMARK_RECONSTRUCTED",
            interpretation="QQQ benchmark return reconstructed as strategy mean_return minus excess_vs_qqq.",
        ))
    for _, r in summary[summary["spy_comparison_status"].eq("available")].iterrows():
        benchmark_rows.append(metric_row(
            "BENCHMARK_RECONSTRUCTED_FROM_EXCESS",
            "SPY_BENCHMARK",
            r["top_n"],
            r["forward_window"],
            r["split"],
            r["portfolio_count"],
            r["spy_benchmark_return"],
            r["spy_benchmark_return"],
            np.nan,
            np.nan,
            np.nan,
            0.0,
            leakage_warnings=0,
            sample_size_warnings="BENCHMARK_RECONSTRUCTED",
            interpretation="SPY benchmark return reconstructed as strategy mean_return minus excess_vs_spy.",
        ))
    if benchmark_rows:
        summary = pd.concat([summary, pd.DataFrame(benchmark_rows)], ignore_index=True)
    return summary.sort_values(["top_n", "forward_window", "source_stage", "policy_id"]).reset_index(drop=True)


def build_simulation(summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    d_map = {
        (r["top_n"], r["forward_window"]): r
        for _, r in summary[summary["policy_id"].str.startswith("D_WEIGHT_OPTIMIZED_R1__EW_")].iterrows()
    }
    qqq_map = {
        (r["top_n"], r["forward_window"]): r
        for _, r in summary[summary["policy_id"].eq("QQQ_BENCHMARK")].iterrows()
    }
    for _, r in summary.iterrows():
        mean = safe_float(r["mean_return"])
        ending = INITIAL_CAPITAL * (1.0 + mean) if pd.notna(mean) else np.nan
        pl = ending - INITIAL_CAPITAL if pd.notna(ending) else np.nan
        key = (r["top_n"], r["forward_window"])
        qqq_pl = np.nan
        if key in qqq_map:
            qqq_pl = INITIAL_CAPITAL * (1.0 + safe_float(qqq_map[key]["mean_return"])) - INITIAL_CAPITAL
        d_pl = np.nan
        if key in d_map:
            d_pl = INITIAL_CAPITAL * (1.0 + safe_float(d_map[key]["mean_return"])) - INITIAL_CAPITAL
        rows.append({
            "source_stage": r["source_stage"],
            "policy_id": r["policy_id"],
            "top_n": r["top_n"],
            "forward_window": r["forward_window"],
            "split": r["split"],
            "initial_capital": INITIAL_CAPITAL,
            "mean_return": mean,
            "ending_value": ending,
            "profit_loss": pl,
            "relative_profit_vs_QQQ": pl - qqq_pl if pd.notna(pl) and pd.notna(qqq_pl) else np.nan,
            "relative_profit_vs_D_EW": pl - d_pl if pd.notna(pl) and pd.notna(d_pl) else np.nan,
            "annualization_used": False,
            "simulation_note": "Per-window average simulation from raw mean forward return; no compounding across random trials.",
            "research_only": True,
        })
    return pd.DataFrame(rows)


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (output_override if output_override and output_override.is_absolute() else root / (output_override or OUT_REL)).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protected = protected_files(root, output)
    for rel in ("outputs/v21/v21_072", "outputs/v21/v21_073", "outputs/v21/v21_074", "outputs/v21/v21_075", "outputs/v21/v21_076", "outputs/v21/v21_077", "outputs/v21/v21_078", "outputs/v21/v21_079"):
        base = root / rel
        if base.exists():
            protected.extend(path.resolve() for path in base.rglob("*") if path.is_file())
    protected = sorted(set(protected))
    before = {path: sha256(path) for path in protected}
    summary = build_summary(root)
    simulation = build_simulation(summary)
    summary.to_csv(output / SUMMARY_NAME, index=False)
    simulation.to_csv(output / SIM_NAME, index=False)
    after = {path: sha256(path) for path in protected}
    changed = [path.as_posix() for path in protected if before[path] != after[path]]
    qqq_available = summary["qqq_comparison_status"].eq("available").any()
    ten = simulation[(simulation["split"].eq("TEST")) & (simulation["forward_window"].eq("10D"))]

    def ending(policy_contains: str, top_n: str) -> Any:
        s = ten[ten["top_n"].eq(top_n) & ten["policy_id"].str.contains(policy_contains, regex=False)]
        return "" if s.empty else float(s.iloc[0]["ending_value"])

    top20_d = ending("EW_TOP20_R1", "TOP20")
    top50_d = ending("EW_TOP50_R1", "TOP50")
    top20_entry = ending(V74_TOP20, "TOP20") or ending(V73_TOP20, "TOP20")
    top50_entry = ending(V74_TOP50, "TOP50") or ending(V73_TOP50, "TOP50")
    strategies = summary[~summary["policy_id"].isin(["QQQ_BENCHMARK", "SPY_BENCHMARK"])].copy()
    best_vs_qqq = simulation.sort_values("relative_profit_vs_QQQ", ascending=False, na_position="last").iloc[0]
    best_vs_d = simulation.sort_values("relative_profit_vs_D_EW", ascending=False, na_position="last").iloc[0]
    entry_exit = strategies[strategies["source_stage"].str.contains("V21.073|V21.074", regex=True)]
    beats_qqq = bool(entry_exit["excess_vs_qqq"].gt(0).any())
    beats_d = False
    leakage = int(summary["leakage_warnings"].sum())
    final_status = (
        "BLOCKED_V21_080_R2_REPORT_INPUTS_MISSING_OR_INTEGRITY_RISK" if changed or summary.empty else
        "PASS_V21_080_R2_ENTRY_EXIT_VS_QQQ_10K_REPORT_READY" if qqq_available else
        "PARTIAL_PASS_V21_080_R2_REPORT_READY_WITH_QQQ_BENCHMARK_WARN"
    )
    decision = "ENTRY_EXIT_10K_REPORT_READY_KEEP_D_BASELINE"
    readiness = {
        "stage": "V21.080-R2_10K_SIMULATION_REPORT",
        "final_status": final_status,
        "decision": decision,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "d_baseline_preserved": True,
        "qqq_comparison_available": bool(qqq_available),
        "strategies_compared": int(summary["policy_id"].nunique()),
        "top20_d_ew_10d_ending_value_on_10000": top20_d,
        "top20_entry_exit_10d_ending_value_on_10000": top20_entry,
        "top50_d_ew_10d_ending_value_on_10000": top50_d,
        "top50_entry_exit_10d_ending_value_on_10000": top50_entry,
        "best_strategy_vs_qqq": best_vs_qqq["policy_id"],
        "best_strategy_vs_d_ew": best_vs_d["policy_id"],
        "entry_exit_beats_qqq": beats_qqq,
        "entry_exit_beats_d_ew": beats_d,
        "leakage_warnings": leakage,
        "protected_outputs_modified": bool(changed),
        "official_outputs_mutated": False,
        "official_adoption_allowed": False,
        "protected_modified_paths": "|".join(changed),
        "research_only": True,
        "execution_pass_gate": not changed and not summary.empty,
    }
    pd.DataFrame([readiness]).to_csv(output / READINESS_NAME, index=False)
    return readiness


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    for key in ("final_status", "decision", "strategies_compared", "qqq_comparison_available"):
        print(f"{key.upper()}={result[key]}")
    return 0 if result["execution_pass_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
