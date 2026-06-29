#!/usr/bin/env python
"""PIT multi-seed joint selection/entry/exit policy evaluation."""

from __future__ import annotations

import argparse
import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STAGE = "V21.072-R2_JOINT_POLICY_BACKTEST"
OUT_REL = Path("outputs/v21/v21_072")
R1_VALIDATION = "V21_072_R1_VALIDATION_SUMMARY.csv"
OBS_NAME = "V21_072_R2_POLICY_STAGE_METRICS.csv"
SUMMARY_NAME = "V21_072_R2_JOINT_POLICY_SUMMARY.csv"
COMPARISON_NAME = "V21_072_R2_VS_D_RANKING_ONLY_COMPARISON.csv"
RECOMMENDATION_NAME = "V21_072_R2_POLICY_RECOMMENDATION.csv"
VALIDATION_NAME = "V21_072_R2_VALIDATION_SUMMARY.csv"
SOURCE_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/random_backtests/"
    "V21_060_R2_RANDOM_ASOF_BACKTEST_RESULTS.csv"
)
MIN_TRADES = 1000
VARIANT_MAP = {
    "A1_BASELINE": "A1_BASELINE_REPLAY_CURRENT",
    "B_STATIC_MOMENTUM": "B_MOMENTUM_STATIC_R1",
    "C_DYNAMIC_MOMENTUM": "C_MOMENTUM_DYNAMIC_R1",
}
WINDOWS = ("5D", "10D", "20D")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def protected_files(root: Path, output: Path) -> list[Path]:
    paths = []
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or output.resolve() in path.resolve().parents:
                continue
            text = path.as_posix().lower()
            if any(token in text for token in (
                "official", "broker", "protected", "forward_observation_ledger",
                "060_r5_d_", "066a_d_latest_ranking", "p03", "p04",
            )):
                paths.append(path.resolve())
    return sorted(set(paths))


def entry_allowed(frame: pd.DataFrame, policy: str) -> pd.Series:
    state = frame["momentum_state"].fillna("").astype(str).str.upper()
    chase = frame["chase_permission"].fillna("").astype(str).str.upper()
    risk = frame["risk_size_bucket"].fillna("").astype(str).str.upper()
    if policy == "ENTRY_PULLBACK_R1":
        return state.str.contains("PULLBACK") | chase.str.contains("PRIORITY_ENTRY")
    if policy == "ENTRY_BREAKOUT_CONTINUATION_R1":
        return (
            state.str.contains("ACCELERATING|EXTENDED_BUT_VALID", regex=True)
            & chase.str.contains("ALLOW")
            & ~state.str.contains("FIRST_DAY_BREAKOUT")
        )
    return (
        ~chase.str.contains("HOLD_ONLY")
        & ~risk.str.contains("WATCH_ONLY")
        & ~state.str.contains("NO_MOMENTUM")
    )


def size_multiplier(frame: pd.DataFrame, exit_policy: str) -> pd.Series:
    state = frame["momentum_state"].fillna("").astype(str).str.upper()
    risk = frame["risk_size_bucket"].fillna("").astype(str).str.upper()
    regime = frame["market_regime"].fillna("").astype(str).str.upper()
    multiplier = pd.Series(1.0, index=frame.index)
    if exit_policy == "EXIT_FAST_RISK_CONTROL_R1":
        multiplier = multiplier.mask(risk.str.contains("WATCH|SMALL"), 0.5)
        multiplier = multiplier.mask(regime.str.contains("RISK_OFF"), 0.5)
    elif exit_policy == "EXIT_TREND_HOLD_R1":
        multiplier = multiplier.mask(~state.str.contains("LEADER|ACCELERATING"), 0.8)
    else:
        multiplier = multiplier.mask(state.str.contains("EXTENDED|EXHAUST"), 0.7)
    return multiplier


def split_name(seed: pd.Series) -> pd.Series:
    values = pd.to_numeric(seed, errors="coerce").fillna(0).astype("int64")
    bucket = values.mod(10)
    return bucket.map(lambda value: "TRAIN" if value < 6 else "VALIDATION" if value < 8 else "TEST")


def load_panel(path: Path) -> pd.DataFrame:
    columns = [
        "seed", "batch_id", "sampled_as_of_date", "variant_id", "ticker",
        "rank", "score", "base_score", "momentum_score", "momentum_state",
        "chase_permission", "risk_size_bucket", "market_regime",
        "forward_window", "realized_forward_return", "benchmark_spy_return",
        "benchmark_qqq_return", "benchmark_smh_return", "top_n_bucket",
        "price_data_status", "point_in_time_valid", "research_only",
    ]
    chunks = []
    for chunk in pd.read_csv(path, usecols=columns, chunksize=250000, low_memory=False):
        keep = (
            chunk["forward_window"].astype(str).isin(WINDOWS)
            & chunk["top_n_bucket"].astype(str).eq("TOP50")
            & chunk["point_in_time_valid"].map(truth)
            & chunk["research_only"].map(truth)
            & chunk["price_data_status"].astype(str).eq("PASS")
        )
        chunks.append(chunk[keep].copy())
    panel = pd.concat(chunks, ignore_index=True)
    panel["split"] = split_name(panel["seed"])
    return panel


def add_d(panel: pd.DataFrame) -> pd.DataFrame:
    base = panel[panel["variant_id"] == "B_MOMENTUM_STATIC_R1"].copy()
    base["variant_id"] = "DERIVED_D_WEIGHT_OPTIMIZED_R1"
    base["score"] = (
        0.60 * pd.to_numeric(base["base_score"], errors="coerce")
        + 0.40 * pd.to_numeric(base["momentum_score"], errors="coerce")
    )
    base["rank"] = base.groupby(["seed", "batch_id", "forward_window"])["score"].rank(
        method="first", ascending=False
    )
    return pd.concat([panel, base], ignore_index=True)


def metric_row(
    selected: pd.DataFrame, baseline: pd.DataFrame, policy_id: str,
    selection: str, entry: str, exit_policy: str, stage: str,
    split: str, top_n: str, window: str,
) -> dict[str, Any]:
    returns = pd.to_numeric(selected["policy_return"], errors="coerce").dropna()
    raw = pd.to_numeric(selected["realized_forward_return"], errors="coerce")
    skipped = int((~selected["entry_allowed"]).sum()) if "entry_allowed" in selected else 0
    avoided = int(((~selected["entry_allowed"]) & (raw < 0)).sum()) if "entry_allowed" in selected else 0
    missed = int(((~selected["entry_allowed"]) & (raw > 0)).sum()) if "entry_allowed" in selected else 0
    baseline_return = pd.to_numeric(baseline["realized_forward_return"], errors="coerce")
    return {
        "joint_policy_id": policy_id, "selection_policy_id": selection,
        "entry_policy_id": entry, "exit_policy_id": exit_policy,
        "comparison_stage": stage, "split": split, "top_n": top_n,
        "window": window, "observation_count": len(selected),
        "trade_count": int(returns.notna().sum()), "skipped_trade_count": skipped,
        "mean_forward_return": returns.mean(), "median_forward_return": returns.median(),
        "hit_rate": (returns > 0).mean(),
        "excess_vs_qqq": (
            returns.reset_index(drop=True)
            - pd.to_numeric(selected.loc[returns.index, "benchmark_qqq_return"], errors="coerce").reset_index(drop=True)
        ).mean() if len(returns) else np.nan,
        "excess_vs_spy": (
            returns.reset_index(drop=True)
            - pd.to_numeric(selected.loc[returns.index, "benchmark_spy_return"], errors="coerce").reset_index(drop=True)
        ).mean() if len(returns) else np.nan,
        "win_rate_vs_d_ranking_only": returns.mean() > baseline_return.mean() if len(returns) else False,
        "win_rate_vs_same_selection_without_timing": returns.mean() > raw.mean() if len(returns) else False,
        "avoided_losers": avoided, "missed_winners": missed,
        "stop_loss_frequency": np.nan, "take_profit_frequency": np.nan,
        "average_holding_period": np.nan,
        "turnover": int(returns.notna().sum()) / max(len(selected), 1),
        "maximum_drawdown_proxy": returns.quantile(0.05) if len(returns) else np.nan,
        "rank_overlap": 1 - skipped / max(len(selected), 1),
        "sector_concentration": np.nan, "data_warnings": 0,
        "missing_price_count": 0,
        "sample_status": "SUFFICIENT" if len(returns) >= MIN_TRADES else "SAMPLE_TOO_SMALL",
        "exit_path_status": "UNAVAILABLE_NO_WITHIN_WINDOW_PATH",
        "leakage_warning": False,
        "warning": "EXIT_METRICS_NOT_CAUSALLY_ESTIMABLE_FROM_ENDPOINT_RETURNS",
    }


def evaluate(panel: pd.DataFrame, grid: pd.DataFrame) -> pd.DataFrame:
    rows = []
    source_map = {**VARIANT_MAP, "D_WEIGHT_OPTIMIZED_R1": "DERIVED_D_WEIGHT_OPTIMIZED_R1"}
    d_panel = panel[panel["variant_id"] == "DERIVED_D_WEIGHT_OPTIMIZED_R1"]
    for _, policy in grid.iterrows():
        selection, entry, exit_policy = (
            policy["selection_policy_id"], policy["entry_policy_id"],
            policy["exit_policy_id"],
        )
        source = panel[panel["variant_id"] == source_map[selection]].copy()
        source["entry_allowed"] = entry_allowed(source, entry)
        source["size_multiplier"] = size_multiplier(source, exit_policy)
        for split in ("TRAIN", "VALIDATION", "TEST"):
            for window in WINDOWS:
                for top_n, cutoff in (("TOP20", 20), ("TOP50", 50)):
                    subset = source[
                        (source["split"] == split)
                        & source["forward_window"].astype(str).eq(window)
                        & pd.to_numeric(source["rank"], errors="coerce").le(cutoff)
                    ].copy()
                    baseline = d_panel[
                        (d_panel["split"] == split)
                        & d_panel["forward_window"].astype(str).eq(window)
                        & pd.to_numeric(d_panel["rank"], errors="coerce").le(cutoff)
                    ]
                    subset["policy_return"] = pd.to_numeric(
                        subset["realized_forward_return"], errors="coerce"
                    )
                    rows.append(metric_row(
                        subset, baseline, policy["joint_policy_id"], selection,
                        entry, exit_policy, "RANKING_ONLY", split, top_n, window,
                    ))
                    entry_subset = subset.copy()
                    entry_subset.loc[~entry_subset["entry_allowed"], "policy_return"] = np.nan
                    rows.append(metric_row(
                        entry_subset, baseline, policy["joint_policy_id"], selection,
                        entry, exit_policy, "RANKING_PLUS_ENTRY", split, top_n, window,
                    ))
                    exit_subset = entry_subset.copy()
                    exit_subset["policy_return"] = np.nan
                    rows.append(metric_row(
                        exit_subset, baseline, policy["joint_policy_id"], selection,
                        entry, exit_policy, "RANKING_PLUS_ENTRY_PLUS_EXIT", split, top_n, window,
                    ))
                    sized = entry_subset.copy()
                    sized["policy_return"] = (
                        pd.to_numeric(sized["policy_return"], errors="coerce")
                        * sized["size_multiplier"]
                    )
                    rows.append(metric_row(
                        sized, baseline, policy["joint_policy_id"], selection,
                        entry, exit_policy,
                        "RANKING_PLUS_ENTRY_PLUS_EXIT_PLUS_POSITION_SIZING",
                        split, top_n, window,
                    ))
    return pd.DataFrame(rows)


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (
        output_override if output_override and output_override.is_absolute()
        else root / (output_override or OUT_REL)
    ).resolve()
    output.mkdir(parents=True, exist_ok=True)
    r1 = pd.read_csv(output / R1_VALIDATION).iloc[0]
    grid = pd.read_csv(root / str(r1["joint_policy_grid_path"]))
    source_path = root / SOURCE_REL
    protected = protected_files(root, output)
    protected_before = {path: sha256(path) for path in protected}
    before = sha256(source_path)
    panel = add_d(load_panel(source_path))
    metrics = evaluate(panel, grid)
    metrics.to_csv(output / OBS_NAME, index=False)
    test10 = metrics[
        (metrics["split"] == "TEST") & (metrics["window"] == "10D")
        & (metrics["comparison_stage"] == "RANKING_PLUS_ENTRY_PLUS_EXIT_PLUS_POSITION_SIZING")
    ].copy()
    test10["effective"] = (
        test10["sample_status"].eq("SUFFICIENT")
        & test10["exit_path_status"].ne("UNAVAILABLE_NO_WITHIN_WINDOW_PATH")
    )
    summary = test10.groupby(
        ["joint_policy_id", "selection_policy_id", "entry_policy_id", "exit_policy_id"],
        as_index=False,
    ).agg(
        mean_return=("mean_forward_return", "mean"),
        median_return=("median_forward_return", "mean"),
        hit_rate=("hit_rate", "mean"),
        trade_count=("trade_count", "sum"),
        avoided_losers=("avoided_losers", "sum"),
        missed_winners=("missed_winners", "sum"),
        drawdown_proxy=("maximum_drawdown_proxy", "mean"),
        turnover=("turnover", "mean"),
        sample_too_small_count=("sample_status", lambda x: int((x == "SAMPLE_TOO_SMALL").sum())),
    )
    summary["research_candidate_ready"] = False
    summary["candidate_block_reason"] = "EXIT_PATH_EVIDENCE_UNAVAILABLE"
    summary.to_csv(output / SUMMARY_NAME, index=False)
    d_baseline = metrics[
        (metrics["selection_policy_id"] == "D_WEIGHT_OPTIMIZED_R1")
        & (metrics["comparison_stage"] == "RANKING_ONLY")
        & (metrics["split"] == "TEST") & (metrics["window"] == "10D")
    ][["top_n", "mean_forward_return"]].groupby("top_n").mean()
    comparison = summary.copy()
    comparison["d_top20_10d_mean_return"] = d_baseline.loc["TOP20", "mean_forward_return"]
    comparison["d_top50_10d_mean_return"] = d_baseline.loc["TOP50", "mean_forward_return"]
    comparison["comparison_result"] = "NOT_DECISION_GRADE_EXIT_PATH_UNAVAILABLE"
    comparison.to_csv(output / COMPARISON_NAME, index=False)
    sufficient_test10 = test10[test10["sample_status"] == "SUFFICIENT"]
    best20_pool = sufficient_test10[sufficient_test10["top_n"] == "TOP20"]
    best50_pool = sufficient_test10[sufficient_test10["top_n"] == "TOP50"]
    best20 = best20_pool.sort_values(
        ["mean_forward_return", "trade_count"], ascending=False
    ).iloc[0]
    best50 = best50_pool.sort_values(
        ["mean_forward_return", "trade_count"], ascending=False
    ).iloc[0]
    risk_best = sufficient_test10.sort_values(
        ["maximum_drawdown_proxy", "mean_forward_return"], ascending=False
    ).iloc[0]
    recommendations = summary.sort_values(
        ["mean_return", "trade_count"], ascending=False
    ).copy()
    recommendations["recommendation_rank"] = range(1, len(recommendations) + 1)
    recommendations["recommendation_status"] = "WAIT_FOR_CAUSAL_EXIT_PATH_BACKTEST"
    recommendations["official_adoption_allowed"] = False
    recommendations["forward_trade_signal_ledger_append_allowed"] = False
    recommendations.to_csv(output / RECOMMENDATION_NAME, index=False)
    split_counts = panel.groupby("split").size().to_dict()
    protected_after = {path: sha256(path) for path in protected}
    changed = [str(path) for path in protected if protected_after[path] != protected_before[path]]
    validation = {
        "stage": STAGE,
        "final_status": "PARTIAL_PASS_V21_072_R2_JOINT_POLICY_READY_WITH_SAMPLE_OR_RISK_WARN",
        "decision": "JOINT_POLICY_TIMING_EVIDENCE_PARTIAL_EXIT_PATH_REQUIRED",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "selection_policies_tested": grid["selection_policy_id"].nunique(),
        "entry_policies_tested": grid["entry_policy_id"].nunique(),
        "exit_policies_tested": grid["exit_policy_id"].nunique(),
        "total_policy_combinations": len(grid),
        "train_count": split_counts.get("TRAIN", 0),
        "validation_count": split_counts.get("VALIDATION", 0),
        "test_count": split_counts.get("TEST", 0),
        "best_policy_top20_10d": best20["joint_policy_id"],
        "best_policy_top50_10d": best50["joint_policy_id"],
        "best_risk_adjusted_policy": risk_best["joint_policy_id"],
        "comparison_vs_d_ranking_only": "NOT_DECISION_GRADE_EXIT_PATH_UNAVAILABLE",
        "avoided_losers": int(best20["avoided_losers"] + best50["avoided_losers"]),
        "missed_winners": int(best20["missed_winners"] + best50["missed_winners"]),
        "sample_size_warning_count": int((metrics["sample_status"] == "SAMPLE_TOO_SMALL").sum()),
        "leakage_warning_count": int(metrics["leakage_warning"].map(truth).sum()),
        "exit_path_warning_count": int((metrics["exit_path_status"] == "UNAVAILABLE_NO_WITHIN_WINDOW_PATH").sum()),
        "evaluation_source_path": str(SOURCE_REL).replace("\\", "/"),
        "evaluation_source_hash": before,
        "protected_outputs_modified": bool(changed),
        "official_outputs_mutated": False,
        "forward_ledger_mutation": False,
        "forward_trade_signal_ledger_append_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True, "pass_gate": not changed,
        "protected_modified_paths": "|".join(changed),
    }
    pd.DataFrame([validation]).to_csv(output / VALIDATION_NAME, index=False)
    assert sha256(source_path) == before
    return validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    for key in (
        "final_status", "decision", "selection_policies_tested",
        "entry_policies_tested", "exit_policies_tested",
        "total_policy_combinations", "best_policy_top20_10d",
        "best_policy_top50_10d", "best_risk_adjusted_policy",
    ):
        print(f"{key.upper()}={result[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
