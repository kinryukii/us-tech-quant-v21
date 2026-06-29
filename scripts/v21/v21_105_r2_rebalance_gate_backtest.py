#!/usr/bin/env python
"""V21.105-R2 diagnostic-only rebalance gate backtest."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


STAGE = "V21.105-R2_REBALANCE_GATE_BACKTEST"
SOURCE_RUN_ID = "20260623_122740"
SOURCE_R1_RUN_ID = "20260623_125503"
SOURCE_REL = Path("outputs/v21/v21_105_abcd_random_252d_monthly_rebalance") / SOURCE_RUN_ID
SOURCE_R1_REL = Path("outputs/v21/v21_105_r1_rebalance_failure_and_turnover_decomposition") / SOURCE_R1_RUN_ID
HOLD_REL = Path("outputs/v21/v21_104_abcd_random_252d_hold_full_run/20260623_163856")
OUTPUT_REL = Path("outputs/v21/v21_105_r2_rebalance_gate_backtest")

CONFIG = "v21_105_r2_config.json"
ROWS = "v21_105_r2_gate_row_results.csv"
SUMMARY = "v21_105_r2_gate_summary.csv"
VS_MONTHLY = "v21_105_r2_gate_vs_monthly_baseline.csv"
VS_HOLD = "v21_105_r2_gate_vs_hold_only.csv"
COST_ROBUST = "v21_105_r2_cost_robustness.csv"
CHURN = "v21_105_r2_churn_reduction_analysis.csv"
WINNERS = "v21_105_r2_winner_retention_analysis.csv"
SIZE_ANALYSIS = "v21_105_r2_top20_vs_top50_gate_analysis.csv"
LEAKAGE = "v21_105_r2_leakage_audit.csv"
WARNINGS = "v21_105_r2_data_quality_warnings.csv"
README = "v21_105_r2_decision_readme.md"

PASS = "PASS_V21_105_R2_GATE_CONFIRMS_REBALANCE_EDGE_RESEARCH_ONLY"
PARTIAL_TOP50 = "PARTIAL_PASS_V21_105_R2_TOP50_GATE_PROMISING_TURNOVER_REDUCED"
PARTIAL_HOLD = "PARTIAL_PASS_V21_105_R2_HOLD_ONLY_STILL_SUPERIOR"
PARTIAL_NO_GATE = "PARTIAL_PASS_V21_105_R2_NO_GATE_CLEARS_A1BC_THRESHOLD"
FAIL_CHURN = "FAIL_V21_105_R2_GATES_DO_NOT_REDUCE_CHURN_OR_RETURN"
FAIL_BLOCKER = "FAIL_V21_105_R2_LEAKAGE_OR_RECONCILIATION_BLOCKER"

COSTS = (0, 10, 20, 50, 100)
HORIZON = 252
MONTHLY = 21

SOURCE_FILES = (
    "v21_105_monthly_rebalance_row_results.csv",
    "v21_105_monthly_rebalance_summary.csv",
    "v21_105_sample_date_mapping.csv",
    "v21_105_leakage_audit.csv",
    "v21_105_data_quality_warnings.csv",
)
R1_FILES = (
    "v21_105_r1_turnover_source_decomposition.csv",
    "v21_105_r1_winner_loser_churn_analysis.csv",
    "v21_105_r1_warning_audit.csv",
)


@dataclass(frozen=True)
class GateSpec:
    gate_id: str
    gate_type: str
    portfolio_size: int
    interval: int = MONTHLY
    parameter: int | float | str = ""


def gate_specs() -> list[GateSpec]:
    specs = [
        GateSpec("UNCONDITIONAL_MONTHLY_BASELINE_TOP20", "UNCONDITIONAL", 20),
        GateSpec("UNCONDITIONAL_MONTHLY_BASELINE_TOP30", "UNCONDITIONAL", 30),
        GateSpec("UNCONDITIONAL_MONTHLY_BASELINE_TOP50", "UNCONDITIONAL", 50),
        GateSpec("QUARTERLY_REBALANCE_TOP20", "UNCONDITIONAL", 20, 63),
        GateSpec("QUARTERLY_REBALANCE_TOP50", "UNCONDITIONAL", 50, 63),
        GateSpec("TOP50_RETENTION_BUFFER_FOR_TOP20", "RETENTION_BUFFER", 20, MONTHLY, 50),
        GateSpec("TOP75_RETENTION_BUFFER_FOR_TOP50", "RETENTION_BUFFER", 50, MONTHLY, 75),
    ]
    for threshold in (10, 20, 30):
        for size in (20, 50):
            specs.append(GateSpec(f"RANK_IMPROVEMENT_{threshold}_TOP{size}", "RANK_IMPROVEMENT", size, MONTHLY, threshold))
    for threshold in (.70, .60, .50):
        label = int(threshold * 100)
        for size in (20, 50):
            specs.append(GateSpec(f"OVERLAP_THRESHOLD_{label}_TOP{size}", "OVERLAP_THRESHOLD", size, MONTHLY, threshold))
    for lookback in (1, 2, 3):
        for size in (20, 30):
            specs.append(GateSpec(f"HYBRID_STABLE_CORE_LB{lookback}_TOP{size}", "HYBRID_STABLE_CORE", size, MONTHLY, lookback))
    return specs


def load_v103(root: Path):
    path = root / "scripts/v21/v21_103_abcd_random_long_horizon_backtest_spec.py"
    spec = importlib.util.spec_from_file_location("v21_103_shared_for_v105_r2", path)
    if not spec or not spec.loader:
        raise RuntimeError("V21.103 shared implementation unavailable.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def clean(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text.lower() == "nan" else text


def truth(value: object) -> bool:
    return clean(value).upper() in {"TRUE", "1", "YES", "Y"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: Iterable[dict[str, object]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    fields = fields or (list(rows[0]) if rows else ["status"])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def immutable_output(root: Path, override: Path | None, run_id: str | None) -> tuple[Path, str]:
    identifier = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output = (override if override and override.is_absolute() else root / (override or OUTPUT_REL / identifier)).resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"Immutable output directory is non-empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    return output, identifier


def hashes(base: Path, names: tuple[str, ...]) -> dict[str, str]:
    missing = [name for name in names if not (base / name).is_file()]
    if missing:
        raise RuntimeError(f"Missing required files under {base}: {missing}")
    return {name: sha256(base / name) for name in names}


def select_gate(
    spec: GateSpec, ranking: pd.DataFrame, current: list[str],
    top50_history: list[list[str]],
) -> tuple[list[str], bool, float]:
    ordered = ranking["ticker"].astype(str).tolist()
    target = ordered[:spec.portfolio_size]
    if not current:
        return target, True, 0.0
    current_set, target_set = set(current), set(target)
    overlap = len(current_set & target_set) / spec.portfolio_size
    if spec.gate_type == "UNCONDITIONAL":
        return target, True, overlap
    if spec.gate_type == "RETENTION_BUFFER":
        buffer_set = set(ordered[:int(spec.parameter)])
        kept = [ticker for ticker in current if ticker in buffer_set]
        selected = kept + [ticker for ticker in ordered if ticker not in kept][:spec.portfolio_size - len(kept)]
        return selected, set(selected) != current_set, overlap
    if spec.gate_type == "OVERLAP_THRESHOLD":
        execute = overlap < float(spec.parameter)
        return (target if execute else current), execute, overlap
    if spec.gate_type == "RANK_IMPROVEMENT":
        ranks = {ticker: index + 1 for index, ticker in enumerate(ordered)}
        selected = list(current)
        incoming = [ticker for ticker in target if ticker not in current_set]
        removable = sorted(
            [ticker for ticker in selected if ticker not in target_set],
            key=lambda ticker: ranks.get(ticker, 10**9), reverse=True,
        )
        for candidate, held in zip(incoming, removable):
            if ranks.get(held, 10**9) - ranks[candidate] >= int(spec.parameter):
                selected[selected.index(held)] = candidate
        return selected, set(selected) != current_set, overlap
    if spec.gate_type == "HYBRID_STABLE_CORE":
        window = top50_history[-(int(spec.parameter) + 1):]
        frequency = Counter(ticker for snapshot in window for ticker in snapshot)
        candidates = sorted(
            set().union(*(set(snapshot) for snapshot in window)),
            key=lambda ticker: (-frequency[ticker], ordered.index(ticker) if ticker in ordered else 10**9, ticker),
        )
        selected = candidates[:spec.portfolio_size]
        if len(selected) < spec.portfolio_size:
            selected += [ticker for ticker in ordered if ticker not in selected][:spec.portfolio_size - len(selected)]
        return selected, set(selected) != current_set, overlap
    raise ValueError(f"Unknown gate type: {spec.gate_type}")


def leg_path(
    prices: pd.DataFrame, tickers: list[str], weights: dict[str, float],
    start_index: int, end_index: int,
) -> tuple[np.ndarray, dict[str, float], int]:
    available = [ticker for ticker in tickers if ticker in prices.columns]
    raw = prices[available].iloc[start_index:end_index + 1].copy()
    if raw.empty:
        return np.ones(end_index - start_index + 1), {}, len(tickers)
    valid = raw.iloc[0].notna() & raw.iloc[0].gt(0)
    valid_names = list(raw.columns[valid])
    missing = int(raw[available].isna().sum().sum())
    if not valid_names:
        return np.ones(len(raw)), {}, missing + len(tickers)
    normalized = raw[valid_names].divide(raw[valid_names].iloc[0], axis=1)
    usable_weights = {ticker: weights.get(ticker, 0.0) for ticker in valid_names}
    total = sum(usable_weights.values())
    if total <= 0:
        usable_weights = {ticker: 1.0 / len(valid_names) for ticker in valid_names}
    else:
        usable_weights = {ticker: weight / total for ticker, weight in usable_weights.items()}
    matrix_weights = pd.Series(usable_weights)
    path = normalized.mul(matrix_weights, axis=1).sum(axis=1, skipna=True).to_numpy(dtype=float)
    ending_values = {
        ticker: usable_weights[ticker] * float(normalized[ticker].iloc[-1])
        for ticker in valid_names if pd.notna(normalized[ticker].iloc[-1])
    }
    ending_total = sum(ending_values.values())
    end_weights = {ticker: value / ending_total for ticker, value in ending_values.items()} if ending_total > 0 else usable_weights
    return path, end_weights, missing


def forward_return(prices: pd.DataFrame, ticker: str, start: str, end: str) -> float:
    if ticker not in prices.columns:
        return np.nan
    entry, exit_price = prices.at[start, ticker], prices.at[end, ticker]
    return float(exit_price / entry - 1) if pd.notna(entry) and float(entry) > 0 and pd.notna(exit_price) else np.nan


def simulate(
    v103, data, features: dict[str, pd.DataFrame], start_date: str,
    spec: GateSpec, variant: str, rank_cache: dict[str, dict[str, pd.DataFrame]],
) -> tuple[dict[int, dict[str, object]], list[dict[str, object]]]:
    start_index = data.calendar.index(start_date)
    end_index = start_index + HORIZON
    offsets = list(range(0, HORIZON, spec.interval))
    benchmark = {}
    for ticker in ("QQQ", "SPY", "SOXX"):
        path = v103.benchmark_path(data, ticker, start_index, HORIZON)
        benchmark[ticker] = float(path[-1] - 1) if path.size else np.nan
    wealth = {cost: 1.0 for cost in COSTS}
    curves = {cost: [1.0] for cost in COSTS}
    gross_wealth = 1.0
    current: list[str] = []
    current_weights: dict[str, float] = {}
    initial: set[str] = set()
    top50_history: list[list[str]] = []
    turnover = 0.0
    rebalance_count = 0
    skipped_count = 0
    replacement_count = 0
    missing = 0
    max_input_date = ""
    pit_failures = 0
    events: list[dict[str, object]] = []
    for number, offset in enumerate(offsets, start=1):
        decision_index = start_index + offset
        next_index = min(end_index, decision_index + spec.interval)
        decision_date = data.calendar[decision_index]
        next_date = data.calendar[next_index]
        if decision_date not in rank_cache:
            rank_cache[decision_date] = v103.rank_variants(features, decision_date)
        ranking = rank_cache[decision_date][variant]
        input_date = clean(ranking["max_input_date"].max())
        max_input_date = max(max_input_date, input_date)
        pit_failures += int(input_date > decision_date)
        if variant == "D":
            top50_history.append(ranking.head(50)["ticker"].astype(str).tolist())
        previous_set = set(current)
        selected, execute, target_overlap = select_gate(spec, ranking, current, top50_history)
        selected_set = set(selected)
        if not current:
            execute = True
        if execute:
            target_weights = {ticker: 1.0 / len(selected) for ticker in selected}
            union = set(current_weights) | set(target_weights)
            leg_turnover = (
                sum(target_weights.values()) if not current_weights
                else .5 * sum(abs(target_weights.get(ticker, 0) - current_weights.get(ticker, 0)) for ticker in union)
            )
            rebalance_count += 1
            replacement_count += len(previous_set - selected_set)
        else:
            target_weights = dict(current_weights)
            selected = list(current)
            selected_set = set(selected)
            leg_turnover = 0.0
            skipped_count += 1
        if number == 1:
            initial = selected_set
        removed = previous_set - selected_set
        added = selected_set - previous_set
        retained = selected_set & previous_set
        turnover += leg_turnover
        path, end_weights, leg_missing = leg_path(
            data.candidate_prices, selected, target_weights, decision_index, next_index
        )
        missing += leg_missing
        leg_factor = float(path[-1])
        gross_wealth *= leg_factor
        for cost in COSTS:
            after_cost = wealth[cost] * (1 - leg_turnover * cost / 10000.0)
            curves[cost].append(after_cost)
            segment = after_cost * path
            curves[cost].extend(segment[1:].tolist())
            wealth[cost] = after_cost * leg_factor
        for status, names in (("REMOVED", removed), ("ADDED", added), ("RETAINED", retained)):
            for ticker in names:
                events.append({
                    "gate_id": spec.gate_id, "portfolio_size": spec.portfolio_size,
                    "rebalance_number": number, "status": status, "ticker": ticker,
                    "forward_return": forward_return(data.candidate_prices, ticker, decision_date, next_date),
                    "target_overlap": target_overlap, "executed": str(execute).upper(),
                })
        current = selected
        current_weights = end_weights
    results = {}
    for cost in COSTS:
        results[cost] = {
            "portfolio_return": wealth[cost] - 1, "gross_portfolio_return": gross_wealth - 1,
            "transaction_cost_drag": gross_wealth - wealth[cost],
            "max_drawdown": v103.max_drawdown(np.asarray(curves[cost], dtype=float)),
            "turnover": turnover, "annualized_turnover": turnover,
            "final_core_retention": len(initial & set(current)) / max(len(initial), 1),
            "rebalance_count": rebalance_count, "skipped_rebalance_count": skipped_count,
            "replacement_count": replacement_count, "decision_count": len(offsets),
            "missing_price_count": missing, "ranking_max_input_date": max_input_date,
            "point_in_time_valid": str(pit_failures == 0).upper(),
            "benchmark_QQQ_return": benchmark["QQQ"], "benchmark_SPY_return": benchmark["SPY"],
            "benchmark_SOXX_return": benchmark["SOXX"], "end_date": data.calendar[end_index],
        }
    return results, events


def weighted_event_summary(events: list[dict[str, object]]) -> dict[str, float]:
    frame = pd.DataFrame(events)
    if frame.empty:
        return {
            "removed_forward_return": np.nan, "added_forward_return": np.nan,
            "retained_forward_return": np.nan, "added_minus_removed_return": np.nan,
        }
    output = {}
    for status, label in (("REMOVED", "removed"), ("ADDED", "added"), ("RETAINED", "retained")):
        values = pd.to_numeric(frame.loc[frame["status"] == status, "forward_return"], errors="coerce")
        output[f"{label}_forward_return"] = values.mean()
    output["added_minus_removed_return"] = output["added_forward_return"] - output["removed_forward_return"]
    return output


def materialize(
    samples: pd.DataFrame,
    unique_gate: dict[str, dict[str, dict[int, dict[str, object]]]],
    unique_baselines: dict[str, dict[tuple[str, int, int], dict[str, object]]],
) -> list[dict[str, object]]:
    rows = []
    for sample in samples.to_dict("records"):
        start = clean(sample["start_date"])
        for spec in gate_specs():
            for cost in COSTS:
                result = unique_gate[start][spec.gate_id][cost]
                baselines = {
                    variant: unique_baselines[start][(variant, spec.portfolio_size, cost)]
                    for variant in ("A1", "B", "C")
                }
                row = {
                    "sample_id": sample["sample_id"], "source_sample_id": sample["source_sample_id"],
                    "seed": sample["seed"], "draw_index": sample["draw_index"], "start_date": start,
                    "end_date": result["end_date"], "gate_id": spec.gate_id, "gate_type": spec.gate_type,
                    "gate_parameter": spec.parameter, "variant": "D", "portfolio_size": spec.portfolio_size,
                    "rebalance_interval": spec.interval, "transaction_cost_bps": cost, **result,
                    "excess_vs_A1": result["portfolio_return"] - baselines["A1"]["portfolio_return"],
                    "excess_vs_B": result["portfolio_return"] - baselines["B"]["portfolio_return"],
                    "excess_vs_C": result["portfolio_return"] - baselines["C"]["portfolio_return"],
                    "excess_vs_QQQ": result["portfolio_return"] - result["benchmark_QQQ_return"],
                    "excess_vs_SPY": result["portfolio_return"] - result["benchmark_SPY_return"],
                    "excess_vs_SOXX": result["portfolio_return"] - result["benchmark_SOXX_return"],
                    "survivorship_bias_warning": "TRUE", "pit_factor_approximation_warning": "TRUE",
                    "research_only": "TRUE",
                }
                rows.append(row)
    return rows


def summaries(frame: pd.DataFrame) -> list[dict[str, object]]:
    output = []
    for keys, group in frame.groupby(["gate_id", "gate_type", "gate_parameter", "portfolio_size", "transaction_cost_bps"], dropna=False, sort=True):
        drawdown = group["max_drawdown"]
        output.append({
            "gate_id": keys[0], "gate_type": keys[1], "gate_parameter": keys[2],
            "portfolio_size": keys[3], "transaction_cost_bps": keys[4], "sample_count": len(group),
            "mean_return": group["portfolio_return"].mean(), "median_return": group["portfolio_return"].median(),
            "p5_return": group["portfolio_return"].quantile(.05), "p25_return": group["portfolio_return"].quantile(.25),
            "p75_return": group["portfolio_return"].quantile(.75), "p95_return": group["portfolio_return"].quantile(.95),
            **{f"win_rate_vs_{name}": group[f"excess_vs_{name}"].gt(0).mean() for name in ("A1", "B", "C", "QQQ", "SPY", "SOXX")},
            "mean_excess_vs_QQQ": group["excess_vs_QQQ"].mean(),
            "median_excess_vs_QQQ": group["excess_vs_QQQ"].median(),
            "p5_excess_vs_QQQ": group["excess_vs_QQQ"].quantile(.05),
            "mean_max_drawdown": drawdown.mean(), "median_max_drawdown": drawdown.median(),
            "p95_max_drawdown": drawdown.quantile(.95),
            "annualized_turnover": group["annualized_turnover"].mean(),
            "transaction_cost_drag": group["transaction_cost_drag"].mean(),
            "final_core_retention": group["final_core_retention"].mean(),
            "average_rebalance_count": group["rebalance_count"].mean(),
            "skipped_rebalance_count": group["skipped_rebalance_count"].mean(),
            "average_replacement_count": group["replacement_count"].mean(),
            "missing_price_count": int(group["missing_price_count"].sum()),
            "research_only": "TRUE",
        })
    return output


def comparisons(frame: pd.DataFrame, hold: pd.DataFrame) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    baseline = frame[frame["gate_type"] == "UNCONDITIONAL"].copy()
    baseline = baseline[baseline["rebalance_interval"] == MONTHLY]
    base_cols = [
        "sample_id", "portfolio_size", "transaction_cost_bps", "portfolio_return",
        "turnover", "max_drawdown", "excess_vs_A1", "excess_vs_B", "excess_vs_C",
        "excess_vs_QQQ", "p5_dummy",
    ]
    baseline["p5_dummy"] = baseline["portfolio_return"]
    baseline = baseline[base_cols].rename(columns={column: f"baseline_{column}" for column in base_cols if column not in ("sample_id", "portfolio_size", "transaction_cost_bps")})
    merged = frame.merge(baseline, on=["sample_id", "portfolio_size", "transaction_cost_bps"], how="left")
    monthly_rows = []
    for keys, group in merged.groupby(["gate_id", "portfolio_size", "transaction_cost_bps"], sort=True):
        monthly_rows.append({
            "gate_id": keys[0], "portfolio_size": keys[1], "transaction_cost_bps": keys[2],
            "sample_count": len(group),
            "mean_return_change": (group["portfolio_return"] - group["baseline_portfolio_return"]).mean(),
            "p5_return_change": group["portfolio_return"].quantile(.05) - group["baseline_portfolio_return"].quantile(.05),
            "mean_drawdown_change": group["max_drawdown"].mean() - group["baseline_max_drawdown"].mean(),
            "turnover_reduction": 1 - group["turnover"].mean() / group["baseline_turnover"].mean(),
            "win_rate_vs_QQQ_change": group["excess_vs_QQQ"].gt(0).mean() - group["baseline_excess_vs_QQQ"].gt(0).mean(),
            "win_rate_vs_A1_change": group["excess_vs_A1"].gt(0).mean() - group["baseline_excess_vs_A1"].gt(0).mean(),
            "win_rate_vs_B_change": group["excess_vs_B"].gt(0).mean() - group["baseline_excess_vs_B"].gt(0).mean(),
            "win_rate_vs_C_change": group["excess_vs_C"].gt(0).mean() - group["baseline_excess_vs_C"].gt(0).mean(),
            "improves_net_return": str((group["portfolio_return"] - group["baseline_portfolio_return"]).mean() > 0).upper(),
            "research_only": "TRUE",
        })
    hold_d = hold[(hold["variant"] == "D") & (pd.to_numeric(hold["horizon"]) == HORIZON)][
        ["sample_id", "portfolio_size", "portfolio_return", "max_drawdown", "excess_vs_QQQ"]
    ].rename(columns={
        "portfolio_return": "hold_return", "max_drawdown": "hold_max_drawdown",
        "excess_vs_QQQ": "hold_excess_vs_QQQ",
    })
    hold_merged = frame.merge(hold_d, on=["sample_id", "portfolio_size"], how="left")
    hold_rows = []
    for keys, group in hold_merged.groupby(["gate_id", "portfolio_size", "transaction_cost_bps"], sort=True):
        valid = group["hold_return"].notna()
        g = group[valid]
        hold_rows.append({
            "gate_id": keys[0], "portfolio_size": keys[1], "transaction_cost_bps": keys[2],
            "paired_sample_count": len(g), "gate_mean_return": g["portfolio_return"].mean(),
            "hold_mean_return": g["hold_return"].mean(),
            "mean_return_change": (g["portfolio_return"] - g["hold_return"]).mean(),
            "median_return_change": (g["portfolio_return"] - g["hold_return"]).median(),
            "p5_return_change": g["portfolio_return"].quantile(.05) - g["hold_return"].quantile(.05),
            "hold_p5_excess_vs_QQQ": g["hold_excess_vs_QQQ"].quantile(.05),
            "gate_p5_excess_vs_QQQ": g["excess_vs_QQQ"].quantile(.05),
            "p5_excess_vs_QQQ_change": (
                g["excess_vs_QQQ"].quantile(.05) - g["hold_excess_vs_QQQ"].quantile(.05)
            ),
            "mean_drawdown_change": g["max_drawdown"].mean() - g["hold_max_drawdown"].mean(),
            "gate_adds_value_over_hold": str((g["portfolio_return"] - g["hold_return"]).mean() > 0).upper(),
            "research_only": "TRUE",
        })
    return monthly_rows, hold_rows


def cost_robustness(summary: pd.DataFrame, hold_compare: pd.DataFrame) -> list[dict[str, object]]:
    output = []
    hold_lookup = hold_compare.set_index(["gate_id", "portfolio_size", "transaction_cost_bps"])
    for _, row in summary.iterrows():
        key = (row["gate_id"], row["portfolio_size"], row["transaction_cost_bps"])
        hold_delta = hold_lookup.loc[key, "mean_return_change"] if key in hold_lookup.index else np.nan
        promising = (
            row["win_rate_vs_QQQ"] > .55 and row["median_excess_vs_QQQ"] > 0
            and hold_delta >= -.03
        )
        output.append({
            "gate_id": row["gate_id"], "portfolio_size": row["portfolio_size"],
            "transaction_cost_bps": row["transaction_cost_bps"],
            "mean_return": row["mean_return"], "median_excess_vs_QQQ": row["median_excess_vs_QQQ"],
            "p5_excess_vs_QQQ": row["p5_excess_vs_QQQ"], "win_rate_vs_QQQ": row["win_rate_vs_QQQ"],
            "win_rate_vs_SOXX": row["win_rate_vs_SOXX"], "annualized_turnover": row["annualized_turnover"],
            "mean_return_change_vs_hold": hold_delta, "benchmark_edge_survives": str(promising).upper(),
            "research_only": "TRUE",
        })
    for (gate, size), group in summary.groupby(["gate_id", "portfolio_size"]):
        ordered = group.sort_values("transaction_cost_bps")
        failed = ordered[(ordered["mean_excess_vs_QQQ"] <= 0) | (ordered["median_excess_vs_QQQ"] <= 0)]
        output.append({
            "gate_id": gate, "portfolio_size": size, "transaction_cost_bps": "BREAK_EVEN_GRID",
            "estimated_edge_disappearance_bps": failed["transaction_cost_bps"].min() if not failed.empty else ">100",
            "benchmark_edge_survives": "N/A", "research_only": "TRUE",
        })
    return output


def churn_analysis(summary: pd.DataFrame, monthly: pd.DataFrame) -> list[dict[str, object]]:
    base = summary[(summary["gate_type"] == "UNCONDITIONAL") & (summary["gate_id"].str.contains("MONTHLY")) & (summary["transaction_cost_bps"] == 10)].set_index("portfolio_size")
    comp = monthly[monthly["transaction_cost_bps"] == 10].set_index(["gate_id", "portfolio_size"])
    output = []
    for _, row in summary[summary["transaction_cost_bps"] == 10].iterrows():
        baseline_size = row["portfolio_size"]
        baseline = base.loc[baseline_size]
        comparison = comp.loc[(row["gate_id"], row["portfolio_size"])]
        event_reduction = 1 - row["average_rebalance_count"] / baseline["average_rebalance_count"]
        replacement_reduction = 1 - row["average_replacement_count"] / max(baseline["average_replacement_count"], 1)
        output.append({
            "gate_id": row["gate_id"], "gate_type": row["gate_type"],
            "portfolio_size": row["portfolio_size"], "annualized_turnover": row["annualized_turnover"],
            "baseline_annualized_turnover": baseline["annualized_turnover"],
            "turnover_reduction": comparison["turnover_reduction"],
            "rebalance_event_reduction": event_reduction,
            "replacement_count_reduction": replacement_reduction,
            "final_core_retention": row["final_core_retention"],
            "core_retention_improvement": row["final_core_retention"] - baseline["final_core_retention"],
            "primary_churn_reduction_source": (
                "FEWER_REBALANCE_EVENTS" if event_reduction > replacement_reduction
                else "SMALLER_REPLACEMENT_COUNT_AND_HIGHER_RETENTION"
            ),
            "turnover_below_5x": str(row["annualized_turnover"] < 5).upper(),
            "research_only": "TRUE",
        })
    return output


def winner_analysis(
    event_summaries: dict[tuple[str, str], dict[str, float]], multiplicity: dict[str, int],
) -> list[dict[str, object]]:
    accum: dict[str, dict[str, list[tuple[float, int]]]] = {}
    for (start, gate), values in event_summaries.items():
        bucket = accum.setdefault(gate, {key: [] for key in values})
        for key, value in values.items():
            bucket[key].append((value, multiplicity[start]))
    output = []
    for gate, values in accum.items():
        result = {}
        for key, pairs in values.items():
            valid = [(value, weight) for value, weight in pairs if pd.notna(value)]
            result[key] = np.average([x[0] for x in valid], weights=[x[1] for x in valid]) if valid else np.nan
        output.append({
            "gate_id": gate, **result,
            "removed_minus_retained_return": result["removed_forward_return"] - result["retained_forward_return"],
            "reduces_selling_subsequent_winners": str(
                result["removed_forward_return"] <= result["retained_forward_return"]
            ).upper(),
            "new_entries_outperform_removed": str(result["added_minus_removed_return"] > 0).upper(),
            "research_only": "TRUE",
        })
    return output


def size_analysis(summary: pd.DataFrame) -> list[dict[str, object]]:
    output = []
    ten = summary[summary["transaction_cost_bps"] == 10]
    for gate_type, group in ten.groupby("gate_type"):
        top20 = group[group["portfolio_size"] == 20]
        top50 = group[group["portfolio_size"] == 50]
        if top20.empty or top50.empty:
            continue
        best20 = top20.sort_values(["win_rate_vs_QQQ", "mean_return"], ascending=False).iloc[0]
        best50 = top50.sort_values(["win_rate_vs_QQQ", "mean_return"], ascending=False).iloc[0]
        output.append({
            "gate_type": gate_type, "best_top20_gate": best20["gate_id"],
            "best_top50_gate": best50["gate_id"], "top20_mean_return": best20["mean_return"],
            "top50_mean_return": best50["mean_return"], "top20_p5_return": best20["p5_return"],
            "top50_p5_return": best50["p5_return"], "top20_win_rate_vs_QQQ": best20["win_rate_vs_QQQ"],
            "top50_win_rate_vs_QQQ": best50["win_rate_vs_QQQ"],
            "top20_turnover": best20["annualized_turnover"], "top50_turnover": best50["annualized_turnover"],
            "superior_size": "TOP50" if (
                best50["mean_return"] > best20["mean_return"] and best50["p5_return"] > best20["p5_return"]
            ) else "TOP20_OR_MIXED",
            "gated_top20_recovers_a1bc_threshold": str(
                min(best20["win_rate_vs_A1"], best20["win_rate_vs_B"], best20["win_rate_vs_C"]) > .55
            ).upper(),
            "research_only": "TRUE",
        })
    return output


def leakage_audit(frame: pd.DataFrame, source_modified: bool, r1_modified: bool, protected_modified: bool) -> list[dict[str, object]]:
    output = []
    for row in frame.to_dict("records"):
        valid = truth(row["point_in_time_valid"]) and clean(row["ranking_max_input_date"]) <= clean(row["end_date"])
        output.append({
            "sample_id": row["sample_id"], "gate_id": row["gate_id"],
            "portfolio_size": row["portfolio_size"], "transaction_cost_bps": row["transaction_cost_bps"],
            "start_date": row["start_date"], "ranking_max_input_date": row["ranking_max_input_date"],
            "ranking_inputs_lte_gate_decision_date": row["point_in_time_valid"],
            "forward_returns_start_after_gate_decision": "TRUE",
            "current_rankings_used": "FALSE", "event_risk_coefficients_used": "FALSE",
            "source_v21_105_modified": str(source_modified).upper(),
            "source_v21_105_r1_modified": str(r1_modified).upper(),
            "protected_outputs_modified": str(protected_modified).upper(),
            "point_in_time_valid": str(valid and not source_modified and not r1_modified and not protected_modified).upper(),
            "leakage_violation_reason": "" if valid else "PIT_RANKING_TIMESTAMP_FAILURE",
            "research_only": "TRUE",
        })
    return output


def classify(summary: pd.DataFrame, monthly: pd.DataFrame, hold: pd.DataFrame, leakage_failures: int, reconciliation_failures: int) -> tuple[str, str, pd.DataFrame]:
    ten = summary[summary["transaction_cost_bps"] == 10].copy()
    base_ids = ten["gate_type"].eq("UNCONDITIONAL") & ten["gate_id"].str.contains("MONTHLY")
    gates = ten[~base_ids].copy()
    monthly10 = monthly[monthly["transaction_cost_bps"] == 10][[
        "gate_id", "portfolio_size", "turnover_reduction",
        "win_rate_vs_A1_change", "win_rate_vs_B_change", "win_rate_vs_C_change",
    ]]
    hold10 = hold[hold["transaction_cost_bps"] == 10][
        ["gate_id", "portfolio_size", "mean_return_change", "p5_excess_vs_QQQ_change"]
    ]
    gates = gates.merge(monthly10, on=["gate_id", "portfolio_size"]).merge(hold10, on=["gate_id", "portfolio_size"])
    baseline_p5 = ten[base_ids].set_index("portfolio_size")["p5_excess_vs_QQQ"]
    gates["p5_baseline"] = gates["portfolio_size"].map(lambda size: baseline_p5.get(size, np.nan))
    gates["promising"] = (
        (gates["win_rate_vs_QQQ"] > .55) & (gates["median_excess_vs_QQQ"] > 0)
        & (gates["turnover_reduction"] >= .30)
        & (gates["p5_excess_vs_QQQ"] >= gates["p5_baseline"] - .05)
        & (gates["p5_excess_vs_QQQ_change"] >= -.05)
        & (gates["mean_return_change"] >= -.03)
    )
    monthly_changes = monthly10.set_index(["gate_id", "portfolio_size"])
    gates["improves_all_a1bc_win_rates"] = gates.apply(
        lambda row: all(
            monthly_changes.loc[(row["gate_id"], row["portfolio_size"]), f"win_rate_vs_{name}_change"] > 0
            for name in ("A1", "B", "C")
        ), axis=1,
    )
    twenty = summary[summary["transaction_cost_bps"] == 20].set_index(["gate_id", "portfolio_size"])
    gates["survives_20bps"] = gates.apply(
        lambda row: (
            (row["gate_id"], row["portfolio_size"]) in twenty.index
            and twenty.loc[(row["gate_id"], row["portfolio_size"]), "win_rate_vs_QQQ"] > .55
            and twenty.loc[(row["gate_id"], row["portfolio_size"]), "median_excess_vs_QQQ"] > 0
        ), axis=1,
    )
    gates["strong"] = (
        gates["promising"] & (gates[["win_rate_vs_A1", "win_rate_vs_B", "win_rate_vs_C"]].min(axis=1) > .55)
        & gates["improves_all_a1bc_win_rates"] & gates["survives_20bps"]
        & (gates["annualized_turnover"] < 5) & (gates["final_core_retention"] > .30)
    )
    if leakage_failures or reconciliation_failures:
        return FAIL_BLOCKER, "STOP_LEAKAGE_OR_RECONCILIATION_BLOCKER", gates
    if gates["strong"].any():
        return PASS, "AT_LEAST_ONE_GATE_CONFIRMS_STRONG_REBALANCE_EDGE", gates
    promising = gates[gates["promising"]]
    if not promising.empty and (promising["portfolio_size"] >= 30).any():
        return PARTIAL_TOP50, "TOP50_OR_BROAD_GATE_PROMISING_WITH_REDUCED_TURNOVER", gates
    if (gates["mean_return_change"] < 0).all():
        return PARTIAL_HOLD, "HOLD_ONLY_REMAINS_SUPERIOR_ACROSS_GATES", gates
    if not (gates[["win_rate_vs_A1", "win_rate_vs_B", "win_rate_vs_C"]].min(axis=1) > .55).any():
        return PARTIAL_NO_GATE, "NO_GATE_CLEARS_ALL_A1_B_C_WIN_RATE_THRESHOLDS", gates
    return FAIL_CHURN, "GATES_FAIL_TO_COMBINE_CHURN_REDUCTION_AND_RETURN", gates


def render_readme(
    output: Path, run_id: str, status: str, decision: str, candidates: pd.DataFrame,
    summary: pd.DataFrame, monthly: pd.DataFrame, hold: pd.DataFrame,
    winners: pd.DataFrame, leakage_failures: int,
) -> None:
    ten = summary[summary["transaction_cost_bps"] == 10]
    eligible = candidates[candidates["promising"]]
    ranking = eligible if not eligible.empty else candidates
    best = ranking.sort_values(
        ["promising", "win_rate_vs_QQQ", "mean_return", "turnover_reduction"],
        ascending=[False, False, False, False],
    ).iloc[0]
    top50_superior = ten[ten["portfolio_size"] == 50]["mean_return"].max() > ten[ten["portfolio_size"] == 20]["mean_return"].max()
    below5 = bool((candidates["annualized_turnover"] < 5).any())
    clears_abc = bool((candidates[["win_rate_vs_A1", "win_rate_vs_B", "win_rate_vs_C"]].min(axis=1) > .55).any())
    best_hold = hold[(hold["gate_id"] == best["gate_id"]) & (hold["portfolio_size"] == best["portfolio_size"]) & (hold["transaction_cost_bps"] == 10)].iloc[0]
    winner = winners[winners["gate_id"] == best["gate_id"]]
    winner_reduction = "NOT_AVAILABLE" if winner.empty else winner.iloc[0]["reduces_selling_subsequent_winners"]
    best_costs = summary[
        (summary["gate_id"] == best["gate_id"]) & (summary["portfolio_size"] == best["portfolio_size"])
    ].sort_values("transaction_cost_bps")
    failed_costs = best_costs[
        (best_costs["mean_excess_vs_QQQ"] <= 0) | (best_costs["median_excess_vs_QQQ"] <= 0)
    ]
    edge_disappears = str(int(failed_costs["transaction_cost_bps"].min())) + " bps" if not failed_costs.empty else ">100 bps"
    text = f"""# V21.105-R2 Diagnostic Rebalance Gate Backtest

FINAL_STATUS: `{status}`  
DECISION: `{decision}`  
run_id: `{run_id}`  
source V21.105 run_id: `{SOURCE_RUN_ID}`  
source V21.105-R1 run_id: `{SOURCE_R1_RUN_ID}`  
official_adoption_allowed: `false`  
broker_action_allowed: `false`

## Decision summary

- Best gate: `{best['gate_id']}` (Top{int(best['portfolio_size'])}, 10 bps).
- Best gate promising under required rule: `{str(bool(best['promising'])).upper()}`.
- Top50 remains superior: `{'YES' if top50_superior else 'NO OR MIXED'}`.
- Any gate annualized turnover below 5x: `{'YES' if below5 else 'NO'}`.
- D clears A1/B/C >55% under any gate: `{'YES' if clears_abc else 'NO'}`.
- Best-gate QQQ edge survives: `{'YES' if best['win_rate_vs_QQQ'] > .55 and best['median_excess_vs_QQQ'] > 0 else 'NO'}`.
- Best-gate SOXX win rate: `{best['win_rate_vs_SOXX']:.4f}`.
- Best-gate QQQ edge disappearance on tested cost grid: `{edge_disappears}`.
- Hold-only remains superior to best gate: `{'YES' if best_hold['mean_return_change'] < 0 else 'NO'}`.
- Best gate reduces selling subsequent winners: `{winner_reduction}`.
- Best-gate turnover reduction versus monthly: `{best['turnover_reduction']:.2%}`.
- Best-gate annualized turnover: `{best['annualized_turnover']:.2f}x`.
- Leakage failures: `{leakage_failures}`.
- Warnings preserved: `SURVIVORSHIP_BIAS_WARN`, `PIT_FACTOR_APPROXIMATION_WARN`.

## Research boundary

All gates are diagnostic-only. Rankings were recomputed at each historical gate decision using PIT-lite inputs no later than that date. Event-risk coefficients and current ranking outputs were not used. No official strategy, weight, broker action, or protected output was modified.
"""
    (output / README).write_text(text, encoding="utf-8")


def run_stage(root: Path, output: Path, run_id: str) -> dict[str, object]:
    root, output = root.resolve(), output.resolve()
    source, source_r1 = (root / SOURCE_REL).resolve(), (root / SOURCE_R1_REL).resolve()
    hold_dir = (root / HOLD_REL).resolve()
    v103 = load_v103(root)
    source_before, r1_before = hashes(source, SOURCE_FILES), hashes(source_r1, R1_FILES)
    protected = v103.protected_files(root, output)
    protected_before = {path: sha256(path) for path in protected}
    warnings = [
        {"warning_code": "SURVIVORSHIP_BIAS_WARN", "severity": "MEDIUM", "status": "PRESERVED",
         "details": "Historical PIT universe membership remains unavailable.", "research_only": "TRUE"},
        {"warning_code": "PIT_FACTOR_APPROXIMATION_WARN", "severity": "MEDIUM", "status": "PRESERVED",
         "details": "Historical full-factor inputs remain approximated by PIT-lite factors.", "research_only": "TRUE"},
    ]
    try:
        mapping = pd.read_csv(source / "v21_105_sample_date_mapping.csv")
        samples = mapping.rename(columns={"v21_105_sample_id": "sample_id"})[
            ["sample_id", "source_sample_id", "seed", "draw_index", "start_date"]
        ]
        multiplicity = samples.groupby("start_date").size().astype(int).to_dict()
        data = v103.load_market_data(root)
        features = v103.rolling_features(data)
        rank_cache: dict[str, dict[str, pd.DataFrame]] = {}
        unique_gate: dict[str, dict[str, dict[int, dict[str, object]]]] = {}
        unique_baselines: dict[str, dict[tuple[str, int, int], dict[str, object]]] = {}
        event_summaries: dict[tuple[str, str], dict[str, float]] = {}
        baseline_specs = {
            size: GateSpec(f"BASELINE_{variant}_TOP{size}", "UNCONDITIONAL", size)
            for size in (20, 50) for variant in ("A1",)
        }
        for start in sorted(samples["start_date"].astype(str).unique()):
            unique_gate[start] = {}
            unique_baselines[start] = {}
            for spec in gate_specs():
                result, events = simulate(v103, data, features, start, spec, "D", rank_cache)
                unique_gate[start][spec.gate_id] = result
                event_summaries[(start, spec.gate_id)] = weighted_event_summary(events)
            for variant in ("A1", "B", "C"):
                for size in (20, 30, 50):
                    spec = GateSpec(f"BASELINE_{variant}_TOP{size}", "UNCONDITIONAL", size)
                    result, _ = simulate(v103, data, features, start, spec, variant, rank_cache)
                    for cost in COSTS:
                        unique_baselines[start][(variant, size, cost)] = result[cost]
        rows = materialize(samples, unique_gate, unique_baselines)
        frame = pd.DataFrame(rows)
        numeric_columns = [
            "portfolio_size", "transaction_cost_bps", "portfolio_return", "gross_portfolio_return",
            "transaction_cost_drag", "max_drawdown", "turnover", "annualized_turnover",
            "final_core_retention", "rebalance_count", "skipped_rebalance_count",
            "replacement_count", "benchmark_QQQ_return", "benchmark_SPY_return",
            "benchmark_SOXX_return", "excess_vs_A1", "excess_vs_B", "excess_vs_C",
            "excess_vs_QQQ", "excess_vs_SPY", "excess_vs_SOXX",
        ]
        for column in numeric_columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        summary_rows = summaries(frame)
        summary_frame = pd.DataFrame(summary_rows)
        hold_source = pd.read_csv(hold_dir / "v21_104_abcd_252d_hold_row_results.csv", low_memory=False)
        for column in ("portfolio_size", "horizon", "portfolio_return", "max_drawdown", "excess_vs_QQQ"):
            hold_source[column] = pd.to_numeric(hold_source[column], errors="coerce")
        monthly_rows, hold_rows = comparisons(frame, hold_source)
        monthly_frame, hold_frame = pd.DataFrame(monthly_rows), pd.DataFrame(hold_rows)
        cost_rows = cost_robustness(summary_frame, hold_frame)
        churn_rows = churn_analysis(summary_frame, monthly_frame)
        winner_rows = winner_analysis(event_summaries, multiplicity)
        size_rows = size_analysis(summary_frame)

        source_after, r1_after = hashes(source, SOURCE_FILES), hashes(source_r1, R1_FILES)
        protected_after = {path: sha256(path) for path in protected}
        source_modified, r1_modified = source_before != source_after, r1_before != r1_after
        protected_modified = any(protected_before[path] != protected_after[path] for path in protected)
        audit_rows = leakage_audit(frame, source_modified, r1_modified, protected_modified)
        leakage_failures = sum(not truth(row["point_in_time_valid"]) for row in audit_rows)
        source_rows = pd.read_csv(source / "v21_105_monthly_rebalance_row_results.csv", low_memory=False)
        source_base = source_rows[
            (source_rows["variant"] == "D") & (source_rows["transaction_cost_bps"].isin([0, 10, 20]))
        ][["sample_id", "portfolio_size", "transaction_cost_bps", "portfolio_return"]]
        r2_base = frame[
            frame["gate_id"].str.contains("UNCONDITIONAL_MONTHLY_BASELINE")
            & frame["transaction_cost_bps"].isin([0, 10, 20])
        ][["sample_id", "portfolio_size", "transaction_cost_bps", "portfolio_return"]]
        reconciled = r2_base.merge(source_base, on=["sample_id", "portfolio_size", "transaction_cost_bps"], suffixes=("_r2", "_source"))
        reconciliation_failures = int(
            (reconciled["portfolio_return_r2"] - reconciled["portfolio_return_source"]).abs().gt(1e-10).sum()
            + (len(reconciled) != 18000)
        )
        status, decision, candidates = classify(
            summary_frame, monthly_frame, hold_frame, leakage_failures, reconciliation_failures
        )
        warnings.extend([
            {"warning_code": "SOURCE_OUTPUTS_MODIFIED", "severity": "HIGH" if source_modified or r1_modified else "INFO",
             "status": str(source_modified or r1_modified).upper(), "details": "V21.105 and R1 source hash audit.", "research_only": "TRUE"},
            {"warning_code": "PROTECTED_OUTPUTS_MODIFIED", "severity": "HIGH" if protected_modified else "INFO",
             "status": str(protected_modified).upper(), "details": "Protected-output hash audit.", "research_only": "TRUE"},
            {"warning_code": "LEAKAGE_FAILURES", "severity": "HIGH" if leakage_failures else "INFO",
             "status": leakage_failures, "details": "PIT gate-decision audit.", "research_only": "TRUE"},
            {"warning_code": "RECONCILIATION_FAILURES", "severity": "HIGH" if reconciliation_failures else "INFO",
             "status": reconciliation_failures, "details": "Unconditional monthly baseline versus V21.105.", "research_only": "TRUE"},
        ])
        config = {
            "stage": STAGE, "run_id": run_id, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_v21_105_run_id": SOURCE_RUN_ID, "source_v21_105_r1_run_id": SOURCE_R1_RUN_ID,
            "sample_count": len(samples), "unique_start_dates": len(multiplicity),
            "gate_count": len(gate_specs()), "gate_specs": [spec.__dict__ for spec in gate_specs()],
            "transaction_cost_bps": list(COSTS), "benchmarks": ["QQQ", "SPY", "SOXX"],
            "holdings_snapshots_persisted": False,
            "holdings_snapshot_note": "Optional snapshot omitted; compact gate event summaries persisted.",
            "event_risk_integrated": False, "official_adoption_allowed": False,
            "broker_action_allowed": False, "research_only": True,
        }
        write_json(output / CONFIG, config)
        write_csv(output / ROWS, rows)
        write_csv(output / SUMMARY, summary_rows)
        write_csv(output / VS_MONTHLY, monthly_rows)
        write_csv(output / VS_HOLD, hold_rows)
        write_csv(output / COST_ROBUST, cost_rows)
        write_csv(output / CHURN, churn_rows)
        write_csv(output / WINNERS, winner_rows)
        write_csv(output / SIZE_ANALYSIS, size_rows)
        write_csv(output / LEAKAGE, audit_rows)
        write_csv(output / WARNINGS, warnings)
        render_readme(
            output, run_id, status, decision, candidates, summary_frame,
            monthly_frame, hold_frame, pd.DataFrame(winner_rows), leakage_failures,
        )
    except Exception as exc:
        status, decision = FAIL_BLOCKER, "STOP_EXECUTION_OR_DATA_BLOCKER"
        leakage_failures, reconciliation_failures = 0, 1
        source_modified = source_before != hashes(source, SOURCE_FILES)
        r1_modified = r1_before != hashes(source_r1, R1_FILES)
        protected_after = {path: sha256(path) for path in protected}
        protected_modified = any(protected_before[path] != protected_after[path] for path in protected)
        warnings.append({"warning_code": "EXECUTION_BLOCKER", "severity": "HIGH", "status": "TRUE",
                         "details": str(exc), "research_only": "TRUE"})
        write_json(output / CONFIG, {"stage": STAGE, "run_id": run_id, "execution_error": str(exc),
                                     "official_adoption_allowed": False, "broker_action_allowed": False})
        for name in (ROWS, SUMMARY, VS_MONTHLY, VS_HOLD, COST_ROBUST, CHURN, WINNERS, SIZE_ANALYSIS, LEAKAGE):
            write_csv(output / name, [], ["status"])
        write_csv(output / WARNINGS, warnings)
        (output / README).write_text(
            f"# V21.105-R2\n\nFINAL_STATUS: `{status}`  \nDECISION: `{decision}`  \n"
            f"source V21.105 run_id: `{SOURCE_RUN_ID}`  \nsource V21.105-R1 run_id: `{SOURCE_R1_RUN_ID}`  \n"
            f"official_adoption_allowed: `false`  \nbroker_action_allowed: `false`\n\nBlocking error: {exc}\n",
            encoding="utf-8",
        )
    result = {
        "FINAL_STATUS": status, "DECISION": decision, "RUN_ID": run_id,
        "SOURCE_V21_105_RUN_ID": SOURCE_RUN_ID, "SOURCE_V21_105_R1_RUN_ID": SOURCE_R1_RUN_ID,
        "LEAKAGE_FAILURES": leakage_failures, "RECONCILIATION_FAILURES": reconciliation_failures,
        "SOURCE_OUTPUTS_MODIFIED": source_modified or r1_modified,
        "PROTECTED_OUTPUTS_MODIFIED": protected_modified, "OUTPUT_DIR": output.as_posix(),
        "OFFICIAL_ADOPTION_ALLOWED": False, "BROKER_ACTION_ALLOWED": False,
    }
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    output, run_id = immutable_output(args.root.resolve(), args.output_dir, args.run_id)
    result = run_stage(args.root, output, run_id)
    return 1 if str(result["FINAL_STATUS"]).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
