#!/usr/bin/env python
"""V21.105 full random 252D monthly-rebalance A1/B/C/D backtest."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


STAGE = "V21.105_ABCD_RANDOM_252D_MONTHLY_REBALANCE_BACKTEST"
OUTPUT_REL = Path("outputs/v21/v21_105_abcd_random_252d_monthly_rebalance")
SOURCE_RUN_ID = "20260623_163856"
SOURCE_R1_RUN_ID = "20260623_165210"
SOURCE_R2_RUN_ID = "20260623_170358"
SOURCE_REL = Path("outputs/v21/v21_104_abcd_random_252d_hold_full_run") / SOURCE_RUN_ID
SOURCE_R1_REL = Path("outputs/v21/v21_104_r1_d_long_horizon_edge_decomposition") / SOURCE_R1_RUN_ID
SOURCE_R2_REL = Path("outputs/v21/v21_104_r2_holdings_persistence_and_ticker_contribution") / SOURCE_R2_RUN_ID

CONFIG = "v21_105_config.json"
MAPPING = "v21_105_sample_date_mapping.csv"
ROWS = "v21_105_monthly_rebalance_row_results.csv"
SUMMARY = "v21_105_monthly_rebalance_summary.csv"
PAIRWISE = "v21_105_pairwise_comparison.csv"
BENCHMARK = "v21_105_benchmark_comparison.csv"
HOLD_COMPARE = "v21_105_hold_vs_rebalance_comparison.csv"
TURNOVER = "v21_105_turnover_analysis.csv"
SIZE_COMPARE = "v21_105_top20_vs_top50_analysis.csv"
TAIL = "v21_105_left_tail_and_drawdown_analysis.csv"
WARNINGS = "v21_105_data_quality_warnings.csv"
LEAKAGE = "v21_105_leakage_audit.csv"
HOLDINGS_SUMMARY = "v21_105_holdings_summary.csv"
HOLDINGS_GZ = "v21_105_holdings_snapshots.csv.gz"
README = "v21_105_decision_readme.md"

PASS = "PASS_V21_105_D_REBALANCE_EDGE_CONFIRMED_RESEARCH_ONLY"
PARTIAL_COST = "PARTIAL_PASS_V21_105_D_REBALANCE_EDGE_EXISTS_BUT_TURNOVER_OR_COST_WARN"
PARTIAL_HOLD = "PARTIAL_PASS_V21_105_D_HOLD_ONLY_BETTER_THAN_REBALANCE"
PARTIAL_NO_EDGE = "PARTIAL_PASS_V21_105_NO_CLEAR_D_REBALANCE_EDGE_KEEP_HOLD_ONLY_VIEW"
FAIL_UNDERPERFORM = "FAIL_V21_105_D_REBALANCE_UNDERPERFORMS_A1_OR_QQQ"
FAIL_BLOCKER = "FAIL_V21_105_LEAKAGE_OR_DATA_QUALITY_BLOCKER"

VARIANTS = ("A1", "B", "C", "D")
SIZES = (20, 50)
COSTS = (0, 10, 20)
HORIZON = 252
INTERVAL = 21
PAIR_LIST = (("D", "A1"), ("D", "B"), ("D", "C"), ("D", "QQQ"), ("D", "SPY"), ("D", "SOXX"))

SOURCE_FILES = (
    "v21_104_abcd_random_sample_dates.csv",
    "v21_104_abcd_252d_hold_row_results.csv",
    "v21_104_abcd_252d_hold_summary.csv",
    "v21_104_abcd_252d_hold_leakage_audit.csv",
    "v21_104_abcd_252d_hold_data_quality_warnings.csv",
)

ROW_FIELDS = [
    "sample_id", "source_sample_id", "seed", "draw_index", "start_date", "end_date",
    "mode", "variant", "portfolio_size", "horizon", "rebalance_interval",
    "transaction_cost_bps", "portfolio_return", "gross_portfolio_return",
    "transaction_cost_drag", "benchmark_QQQ_return", "benchmark_SPY_return",
    "benchmark_SOXX_return", "excess_vs_A1", "excess_vs_B", "excess_vs_C",
    "excess_vs_D", "excess_vs_QQQ", "excess_vs_SPY", "excess_vs_SOXX",
    "max_drawdown", "gross_max_drawdown", "turnover", "annualized_turnover",
    "rebalance_count", "missing_price_count", "ranking_max_input_date",
    "forward_return_starts_after_rebalance", "point_in_time_valid",
    "survivorship_bias_warning", "pit_factor_approximation_warning", "research_only",
]

SUMMARY_FIELDS = [
    "variant", "portfolio_size", "transaction_cost_bps", "sample_count",
    "mean_return", "median_return", "p5_return", "p25_return", "p75_return",
    "p95_return", "worst_sample_return", "best_sample_return",
    "mean_excess_vs_A1", "median_excess_vs_A1", "p5_excess_vs_A1",
    "mean_excess_vs_QQQ", "median_excess_vs_QQQ", "p5_excess_vs_QQQ",
    "mean_excess_vs_SPY", "median_excess_vs_SPY", "mean_excess_vs_SOXX",
    "median_excess_vs_SOXX", "win_rate_vs_A1", "win_rate_vs_B",
    "win_rate_vs_C", "win_rate_vs_D", "win_rate_vs_QQQ", "win_rate_vs_SPY",
    "win_rate_vs_SOXX", "mean_max_drawdown", "median_max_drawdown",
    "p95_max_drawdown", "mean_turnover", "median_turnover", "p95_turnover",
    "annualized_turnover", "transaction_cost_drag", "missing_price_count",
    "leakage_warning_count", "survivorship_bias_warning_count",
    "pit_factor_approximation_warning_count",
]

HOLDING_FIELDS = [
    "sample_id", "source_sample_id", "seed", "draw_index", "start_date",
    "variant", "portfolio_size", "rebalance_number", "rebalance_date",
    "next_rebalance_date", "rank", "ticker", "target_weight", "base_score",
    "momentum_score", "final_score", "momentum_weight", "entry_price",
    "exit_price", "leg_return", "gross_weighted_contribution",
    "in_previous_snapshot", "holding_persisted", "snapshot_turnover",
    "ranking_max_input_date", "forward_return_starts_after_rebalance",
    "point_in_time_valid", "price_status", "survivorship_bias_warning",
    "pit_factor_approximation_warning", "research_only",
]


def load_v103(root: Path):
    path = root / "scripts/v21/v21_103_abcd_random_long_horizon_backtest_spec.py"
    spec = importlib.util.spec_from_file_location("v21_103_shared_for_v105", path)
    if not spec or not spec.loader:
        raise RuntimeError("V21.103 shared implementation cannot be loaded.")
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


def write_csv(path: Path, rows: Iterable[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def source_hashes(source: Path) -> dict[str, str]:
    missing = [name for name in SOURCE_FILES if not (source / name).is_file()]
    if missing:
        raise RuntimeError(f"Missing V21.104 source files: {missing}")
    return {name: sha256(source / name) for name in SOURCE_FILES}


def numeric(frame: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    for column in columns:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def simulate_unique(
    v103, data, features: dict[str, pd.DataFrame], start_date: str,
    rank_cache: dict[str, dict[str, pd.DataFrame]],
) -> tuple[dict[tuple[str, int, int], dict[str, object]], dict[tuple[str, int], list[dict[str, object]]]]:
    start_index = data.calendar.index(start_date)
    end_index = start_index + HORIZON
    offsets = list(range(0, HORIZON, INTERVAL))
    benchmark = {}
    for ticker in ("QQQ", "SPY", "SOXX"):
        path = v103.benchmark_path(data, ticker, start_index, HORIZON)
        benchmark[ticker] = float(path[-1] - 1) if path.size else np.nan
    results: dict[tuple[str, int, int], dict[str, object]] = {}
    snapshots: dict[tuple[str, int], list[dict[str, object]]] = {}
    for variant in VARIANTS:
        for size in SIZES:
            gross_wealth = 1.0
            gross_curve = [1.0]
            cost_wealth = {cost: 1.0 for cost in COSTS}
            cost_curves = {cost: [1.0] for cost in COSTS}
            previous: set[str] = set()
            previous_weights: dict[str, float] = {}
            total_turnover = 0.0
            missing = 0
            pit_failures = 0
            max_input_date = ""
            snapshot_rows: list[dict[str, object]] = []
            for number, offset in enumerate(offsets, start=1):
                rebalance_index = start_index + offset
                next_index = min(end_index, rebalance_index + INTERVAL)
                rebalance_date = data.calendar[rebalance_index]
                next_date = data.calendar[next_index]
                if rebalance_date not in rank_cache:
                    rank_cache[rebalance_date] = v103.rank_variants(features, rebalance_date)
                ranking = rank_cache[rebalance_date][variant].head(size).copy()
                selected_list = ranking["ticker"].astype(str).tolist()
                selected = set(selected_list)
                input_date = clean(ranking["max_input_date"].max())
                max_input_date = max(max_input_date, input_date)
                if input_date > rebalance_date:
                    pit_failures += 1
                raw = data.candidate_prices[selected_list].iloc[rebalance_index:next_index + 1].copy()
                start_prices = raw.iloc[0]
                valid = start_prices.notna() & start_prices.gt(0)
                valid_tickers = list(start_prices.index[valid])
                target_weights = {
                    ticker: 1.0 / len(valid_tickers) for ticker in valid_tickers
                } if valid_tickers else {}
                if not previous_weights:
                    leg_turnover = float(sum(target_weights.values()))
                else:
                    union = set(previous_weights) | set(target_weights)
                    leg_turnover = 0.5 * sum(
                        abs(target_weights.get(ticker, 0.0) - previous_weights.get(ticker, 0.0))
                        for ticker in union
                    )
                total_turnover += leg_turnover
                missing += int(raw[selected_list].isna().sum().sum())
                if not valid_tickers:
                    leg_path = np.ones(next_index - rebalance_index + 1)
                    end_weights: dict[str, float] = {}
                else:
                    normalized = raw[valid_tickers].divide(raw[valid_tickers].iloc[0], axis=1)
                    leg_path = normalized.mean(axis=1, skipna=True).fillna(1.0).to_numpy(dtype=float)
                    ending = normalized.iloc[-1].replace([np.inf, -np.inf], np.nan).dropna()
                    ending_sum = float(ending.sum())
                    end_weights = (
                        (ending / ending_sum).to_dict() if ending_sum > 0 else target_weights
                    )
                leg_factor = float(leg_path[-1])
                gross_segment = gross_wealth * leg_path
                gross_curve.extend(gross_segment[1:].tolist())
                gross_wealth *= leg_factor
                for cost in COSTS:
                    cost_fraction = leg_turnover * cost / 10000.0
                    after_cost = cost_wealth[cost] * (1.0 - cost_fraction)
                    cost_curves[cost].append(after_cost)
                    segment = after_cost * leg_path
                    cost_curves[cost].extend(segment[1:].tolist())
                    cost_wealth[cost] = after_cost * leg_factor
                next_selected: set[str] = set()
                if next_index < end_index:
                    if next_date not in rank_cache:
                        rank_cache[next_date] = v103.rank_variants(features, next_date)
                    next_selected = set(rank_cache[next_date][variant].head(size)["ticker"].astype(str))
                weight = 1.0 / len(valid_tickers) if valid_tickers else np.nan
                for record in ranking.to_dict("records"):
                    ticker = clean(record["ticker"])
                    entry = raw.at[rebalance_date, ticker] if ticker in raw.columns else np.nan
                    exit_price = raw.at[next_date, ticker] if ticker in raw.columns else np.nan
                    price_ok = pd.notna(entry) and float(entry) > 0 and pd.notna(exit_price)
                    leg_return = float(exit_price / entry - 1) if price_ok else np.nan
                    snapshot_rows.append({
                        "variant": variant, "portfolio_size": size,
                        "rebalance_number": number, "rebalance_date": rebalance_date,
                        "next_rebalance_date": next_date, "rank": int(record["rank"]),
                        "ticker": ticker, "target_weight": weight if ticker in valid_tickers else 0.0,
                        "base_score": record["base_score"], "momentum_score": record["momentum_score"],
                        "final_score": record["score"], "momentum_weight": record["momentum_weight"],
                        "entry_price": entry, "exit_price": exit_price, "leg_return": leg_return,
                        "gross_weighted_contribution": weight * leg_return if price_ok else np.nan,
                        "in_previous_snapshot": str(ticker in previous).upper(),
                        "holding_persisted": str(ticker in next_selected).upper(),
                        "snapshot_turnover": leg_turnover, "ranking_max_input_date": input_date,
                        "forward_return_starts_after_rebalance": "TRUE",
                        "point_in_time_valid": str(input_date <= rebalance_date).upper(),
                        "price_status": "PASS" if price_ok else "MISSING_ENTRY_OR_EXIT_PRICE",
                        "survivorship_bias_warning": "TRUE",
                        "pit_factor_approximation_warning": "TRUE", "research_only": "TRUE",
                    })
                previous = selected
                previous_weights = end_weights
            snapshots[(variant, size)] = snapshot_rows
            gross_return = gross_wealth - 1.0
            for cost in COSTS:
                results[(variant, size, cost)] = {
                    "portfolio_return": cost_wealth[cost] - 1.0,
                    "gross_portfolio_return": gross_return,
                    "transaction_cost_drag": gross_wealth - cost_wealth[cost],
                    "max_drawdown": v103.max_drawdown(np.asarray(cost_curves[cost], dtype=float)),
                    "gross_max_drawdown": v103.max_drawdown(np.asarray(gross_curve, dtype=float)),
                    "turnover": total_turnover,
                    "annualized_turnover": total_turnover * 252.0 / HORIZON,
                    "rebalance_count": len(offsets), "missing_price_count": missing,
                    "ranking_max_input_date": max_input_date,
                    "point_in_time_valid": str(pit_failures == 0).upper(),
                    "benchmark_QQQ_return": benchmark["QQQ"],
                    "benchmark_SPY_return": benchmark["SPY"],
                    "benchmark_SOXX_return": benchmark["SOXX"],
                    "end_date": data.calendar[end_index],
                }
    return results, snapshots


def materialize_rows(
    samples: pd.DataFrame, unique_results: dict[str, dict[tuple[str, int, int], dict[str, object]]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for sample in samples.to_dict("records"):
        start = clean(sample["start_date"])
        per_start = unique_results[start]
        for size in SIZES:
            for cost in COSTS:
                returns = {variant: float(per_start[(variant, size, cost)]["portfolio_return"]) for variant in VARIANTS}
                for variant in VARIANTS:
                    result = per_start[(variant, size, cost)]
                    row = {
                        "sample_id": sample["sample_id"], "source_sample_id": sample["source_sample_id"],
                        "seed": sample["seed"], "draw_index": sample["draw_index"],
                        "start_date": start, "end_date": result["end_date"],
                        "mode": "RANDOM_252D_MONTHLY_REBALANCE", "variant": variant,
                        "portfolio_size": size, "horizon": HORIZON,
                        "rebalance_interval": INTERVAL, "transaction_cost_bps": cost,
                        **result, "survivorship_bias_warning": "TRUE",
                        "pit_factor_approximation_warning": "TRUE",
                        "forward_return_starts_after_rebalance": "TRUE", "research_only": "TRUE",
                    }
                    for comparison in VARIANTS:
                        row[f"excess_vs_{comparison}"] = float(result["portfolio_return"]) - returns[comparison]
                    row["excess_vs_QQQ"] = float(result["portfolio_return"]) - float(result["benchmark_QQQ_return"])
                    row["excess_vs_SPY"] = float(result["portfolio_return"]) - float(result["benchmark_SPY_return"])
                    row["excess_vs_SOXX"] = float(result["portfolio_return"]) - float(result["benchmark_SOXX_return"])
                    rows.append(row)
    return rows


def summaries(frame: pd.DataFrame) -> list[dict[str, object]]:
    output = []
    for keys, group in frame.groupby(["variant", "portfolio_size", "transaction_cost_bps"], sort=True):
        values = group["portfolio_return"].dropna()
        drawdown = group["max_drawdown"].dropna()
        output.append({
            "variant": keys[0], "portfolio_size": keys[1], "transaction_cost_bps": keys[2],
            "sample_count": len(values), "mean_return": values.mean(), "median_return": values.median(),
            "p5_return": values.quantile(.05), "p25_return": values.quantile(.25),
            "p75_return": values.quantile(.75), "p95_return": values.quantile(.95),
            "worst_sample_return": values.min(), "best_sample_return": values.max(),
            "mean_excess_vs_A1": group["excess_vs_A1"].mean(),
            "median_excess_vs_A1": group["excess_vs_A1"].median(),
            "p5_excess_vs_A1": group["excess_vs_A1"].quantile(.05),
            "mean_excess_vs_QQQ": group["excess_vs_QQQ"].mean(),
            "median_excess_vs_QQQ": group["excess_vs_QQQ"].median(),
            "p5_excess_vs_QQQ": group["excess_vs_QQQ"].quantile(.05),
            "mean_excess_vs_SPY": group["excess_vs_SPY"].mean(),
            "median_excess_vs_SPY": group["excess_vs_SPY"].median(),
            "mean_excess_vs_SOXX": group["excess_vs_SOXX"].mean(),
            "median_excess_vs_SOXX": group["excess_vs_SOXX"].median(),
            **{f"win_rate_vs_{name}": group[f"excess_vs_{name}"].gt(0).mean() for name in (*VARIANTS, "QQQ", "SPY", "SOXX")},
            "mean_max_drawdown": drawdown.mean(), "median_max_drawdown": drawdown.median(),
            "p95_max_drawdown": drawdown.quantile(.95),
            "mean_turnover": group["turnover"].mean(), "median_turnover": group["turnover"].median(),
            "p95_turnover": group["turnover"].quantile(.95),
            "annualized_turnover": group["annualized_turnover"].mean(),
            "transaction_cost_drag": group["transaction_cost_drag"].mean(),
            "missing_price_count": int(group["missing_price_count"].sum()),
            "leakage_warning_count": int((group["point_in_time_valid"] != "TRUE").sum()),
            "survivorship_bias_warning_count": int((group["survivorship_bias_warning"] == "TRUE").sum()),
            "pit_factor_approximation_warning_count": int((group["pit_factor_approximation_warning"] == "TRUE").sum()),
        })
    return output


def comparison_value(group: pd.DataFrame, name: str) -> pd.Series:
    if name in VARIANTS:
        return group[name]
    return group[f"benchmark_{name}_return"]


def pairwise(frame: pd.DataFrame) -> list[dict[str, object]]:
    pivot = frame.pivot_table(
        index=["sample_id", "portfolio_size", "transaction_cost_bps"],
        columns="variant", values="portfolio_return", aggfunc="first",
    ).reset_index()
    bench = frame[frame["variant"].eq("A1")][[
        "sample_id", "portfolio_size", "transaction_cost_bps",
        "benchmark_QQQ_return", "benchmark_SPY_return", "benchmark_SOXX_return",
    ]]
    pivot = pivot.merge(bench, on=["sample_id", "portfolio_size", "transaction_cost_bps"], how="left")
    output = []
    for (size, cost), group in pivot.groupby(["portfolio_size", "transaction_cost_bps"], sort=True):
        for left, right in PAIR_LIST:
            lv, rv = comparison_value(group, left), comparison_value(group, right)
            valid = lv.notna() & rv.notna()
            delta = lv[valid] - rv[valid]
            output.append({
                "portfolio_size": size, "transaction_cost_bps": cost, "left": left, "right": right,
                "paired_sample_count": len(delta), "left_mean_return": lv[valid].mean(),
                "right_mean_return": rv[valid].mean(), "mean_return_delta": delta.mean(),
                "median_return_delta": delta.median(), "p5_return_delta": delta.quantile(.05),
                "left_win_count": int(delta.gt(0).sum()), "right_win_count": int(delta.lt(0).sum()),
                "tie_count": int(delta.eq(0).sum()), "left_win_rate": delta.gt(0).mean(),
                "right_win_rate": delta.lt(0).mean(),
                "directional_result": "LEFT_BETTER" if delta.gt(0).sum() > delta.lt(0).sum() else "RIGHT_BETTER",
                "research_only": "TRUE",
            })
    return output


def benchmark_comparison(frame: pd.DataFrame) -> list[dict[str, object]]:
    output = []
    for keys, group in frame.groupby(["variant", "portfolio_size", "transaction_cost_bps"], sort=True):
        for name in ("QQQ", "SPY", "SOXX"):
            excess = group[f"excess_vs_{name}"].dropna()
            output.append({
                "variant": keys[0], "portfolio_size": keys[1], "transaction_cost_bps": keys[2],
                "benchmark": name, "sample_count": len(excess),
                "mean_variant_return": group.loc[excess.index, "portfolio_return"].mean(),
                "mean_benchmark_return": group.loc[excess.index, f"benchmark_{name}_return"].mean(),
                "mean_excess_return": excess.mean(), "median_excess_return": excess.median(),
                "p5_excess_return": excess.quantile(.05), "win_rate_vs_benchmark": excess.gt(0).mean(),
                "research_only": "TRUE",
            })
    return output


def hold_comparison(frame: pd.DataFrame, hold: pd.DataFrame) -> list[dict[str, object]]:
    hold = hold[pd.to_numeric(hold["horizon"], errors="coerce").eq(HORIZON)].copy()
    hold = hold.rename(columns={
        "portfolio_return": "hold_return", "max_drawdown": "hold_max_drawdown",
        "excess_vs_QQQ": "hold_excess_vs_QQQ",
        "excess_vs_A1": "hold_excess_vs_A1",
        "excess_vs_semiconductor_benchmark": "hold_excess_vs_SOXX",
    })
    merged = frame.merge(hold[[
        "sample_id", "variant", "portfolio_size", "hold_return", "hold_max_drawdown",
        "hold_excess_vs_QQQ", "hold_excess_vs_A1", "hold_excess_vs_SOXX",
    ]], on=["sample_id", "variant", "portfolio_size"], how="inner")
    output = []
    for keys, group in merged.groupby(["variant", "portfolio_size", "transaction_cost_bps"], sort=True):
        reb = group["portfolio_return"]
        output.append({
            "variant": keys[0], "portfolio_size": keys[1], "transaction_cost_bps": keys[2],
            "paired_sample_count": len(group), "hold_mean_return": group["hold_return"].mean(),
            "rebalance_mean_return": reb.mean(), "mean_return_change": (reb - group["hold_return"]).mean(),
            "hold_median_return": group["hold_return"].median(), "rebalance_median_return": reb.median(),
            "median_return_change": reb.median() - group["hold_return"].median(),
            "hold_p5_return": group["hold_return"].quantile(.05), "rebalance_p5_return": reb.quantile(.05),
            "p5_return_change": reb.quantile(.05) - group["hold_return"].quantile(.05),
            "hold_win_rate_vs_QQQ": group["hold_excess_vs_QQQ"].gt(0).mean(),
            "rebalance_win_rate_vs_QQQ": group["excess_vs_QQQ"].gt(0).mean(),
            "win_rate_vs_QQQ_change": group["excess_vs_QQQ"].gt(0).mean() - group["hold_excess_vs_QQQ"].gt(0).mean(),
            "hold_p5_excess_vs_QQQ": group["hold_excess_vs_QQQ"].quantile(.05),
            "rebalance_p5_excess_vs_QQQ": group["excess_vs_QQQ"].quantile(.05),
            "p5_excess_vs_QQQ_change": (
                group["excess_vs_QQQ"].quantile(.05) - group["hold_excess_vs_QQQ"].quantile(.05)
            ),
            "hold_win_rate_vs_A1": group["hold_excess_vs_A1"].gt(0).mean(),
            "rebalance_win_rate_vs_A1": group["excess_vs_A1"].gt(0).mean(),
            "win_rate_vs_A1_change": group["excess_vs_A1"].gt(0).mean() - group["hold_excess_vs_A1"].gt(0).mean(),
            "hold_mean_max_drawdown": group["hold_max_drawdown"].mean(),
            "rebalance_mean_max_drawdown": group["max_drawdown"].mean(),
            "mean_drawdown_change": group["max_drawdown"].mean() - group["hold_max_drawdown"].mean(),
            "hold_mean_excess_vs_SOXX": group["hold_excess_vs_SOXX"].mean(),
            "rebalance_mean_excess_vs_SOXX": group["excess_vs_SOXX"].mean(),
            "soxx_gap_change": group["excess_vs_SOXX"].mean() - group["hold_excess_vs_SOXX"].mean(),
            "monthly_rebalance_improved": str((reb - group["hold_return"]).mean() > 0).upper(),
            "research_only": "TRUE",
        })
    return output


def turnover_analysis(frame: pd.DataFrame) -> list[dict[str, object]]:
    base = frame[frame["transaction_cost_bps"].eq(0)]
    output = []
    for keys, group in base.groupby(["variant", "portfolio_size"], sort=True):
        matching = frame[(frame["variant"] == keys[0]) & (frame["portfolio_size"] == keys[1])]
        drag10 = matching[matching["transaction_cost_bps"].eq(10)]["transaction_cost_drag"].mean()
        drag20 = matching[matching["transaction_cost_bps"].eq(20)]["transaction_cost_drag"].mean()
        output.append({
            "variant": keys[0], "portfolio_size": keys[1], "sample_count": len(group),
            "mean_turnover": group["turnover"].mean(), "median_turnover": group["turnover"].median(),
            "p75_turnover": group["turnover"].quantile(.75), "p95_turnover": group["turnover"].quantile(.95),
            "average_annualized_turnover": group["annualized_turnover"].mean(),
            "mean_cost_drag_10bps": drag10, "mean_cost_drag_20bps": drag20,
            "turnover_acceptable": str(group["annualized_turnover"].mean() <= 6.0).upper(),
            "research_only": "TRUE",
        })
    return output


def size_analysis(summary: pd.DataFrame) -> list[dict[str, object]]:
    output = []
    for (variant, cost), group in summary.groupby(["variant", "transaction_cost_bps"], sort=True):
        indexed = group.set_index("portfolio_size")
        if not {20, 50}.issubset(indexed.index):
            continue
        t20, t50 = indexed.loc[20], indexed.loc[50]
        output.append({
            "variant": variant, "transaction_cost_bps": cost,
            "top20_mean_return": t20["mean_return"], "top50_mean_return": t50["mean_return"],
            "top20_mean_excess_vs_QQQ": t20["mean_excess_vs_QQQ"],
            "top50_mean_excess_vs_QQQ": t50["mean_excess_vs_QQQ"],
            "top20_win_rate_vs_QQQ": t20["win_rate_vs_QQQ"],
            "top50_win_rate_vs_QQQ": t50["win_rate_vs_QQQ"],
            "stronger_relative_edge": "TOP20" if t20["mean_excess_vs_QQQ"] > t50["mean_excess_vs_QQQ"] else "TOP50",
            "top20_p5_return": t20["p5_return"], "top50_p5_return": t50["p5_return"],
            "top20_mean_max_drawdown": t20["mean_max_drawdown"],
            "top50_mean_max_drawdown": t50["mean_max_drawdown"],
            "better_stability": "TOP20" if (t20["p5_return"], t20["mean_max_drawdown"]) > (t50["p5_return"], t50["mean_max_drawdown"]) else "TOP50",
            "research_only": "TRUE",
        })
    return output


def tail_analysis(frame: pd.DataFrame) -> list[dict[str, object]]:
    output = []
    for keys, group in frame.groupby(["variant", "portfolio_size", "transaction_cost_bps"], sort=True):
        output.append({
            "variant": keys[0], "portfolio_size": keys[1], "transaction_cost_bps": keys[2],
            "sample_count": len(group), "p1_return": group["portfolio_return"].quantile(.01),
            "p5_return": group["portfolio_return"].quantile(.05),
            "worst_return": group["portfolio_return"].min(),
            "mean_max_drawdown": group["max_drawdown"].mean(),
            "median_max_drawdown": group["max_drawdown"].median(),
            "p95_severity_max_drawdown": group["max_drawdown"].quantile(.05),
            "worst_max_drawdown": group["max_drawdown"].min(),
            "p5_excess_vs_A1": group["excess_vs_A1"].quantile(.05),
            "p5_excess_vs_QQQ": group["excess_vs_QQQ"].quantile(.05),
            "p5_excess_vs_SOXX": group["excess_vs_SOXX"].quantile(.05),
            "left_tail_weakness_vs_A1": str(group["excess_vs_A1"].quantile(.05) < -.05).upper(),
            "left_tail_weakness_vs_QQQ": str(group["excess_vs_QQQ"].quantile(.05) < -.30).upper(),
            "research_only": "TRUE",
        })
    return output


def holdings_summary(
    samples: pd.DataFrame, snapshots: dict[str, dict[tuple[str, int], list[dict[str, object]]]],
) -> list[dict[str, object]]:
    multiplicity = samples.groupby("start_date").size().to_dict()
    accum: dict[tuple[str, int, int], dict[str, float]] = {}
    for start, per_start in snapshots.items():
        count = int(multiplicity[start])
        for (variant, size), records in per_start.items():
            frame = pd.DataFrame(records)
            for number, group in frame.groupby("rebalance_number"):
                key = (variant, size, int(number))
                bucket = accum.setdefault(key, {
                    "weighted_samples": 0, "positions": 0, "persisted": 0,
                    "turnover_sum": 0.0, "missing": 0, "unique_tickers_sum": 0,
                })
                bucket["weighted_samples"] += count
                bucket["positions"] += len(group) * count
                bucket["persisted"] += int(group["holding_persisted"].eq("TRUE").sum()) * count
                bucket["turnover_sum"] += float(group["snapshot_turnover"].iloc[0]) * count
                bucket["missing"] += int(group["price_status"].ne("PASS").sum()) * count
                bucket["unique_tickers_sum"] += group["ticker"].nunique() * count
    output = []
    for (variant, size, number), bucket in sorted(accum.items()):
        samples_n = bucket["weighted_samples"]
        output.append({
            "variant": variant, "portfolio_size": size, "rebalance_number": number,
            "sample_count": samples_n, "holding_rows": int(bucket["positions"]),
            "mean_unique_ticker_count": bucket["unique_tickers_sum"] / samples_n,
            "holding_persistence_rate": bucket["persisted"] / bucket["positions"],
            "mean_snapshot_turnover": bucket["turnover_sum"] / samples_n,
            "missing_price_warning_count": int(bucket["missing"]), "research_only": "TRUE",
        })
    return output


def write_holdings_gz(
    path: Path, samples: pd.DataFrame,
    snapshots: dict[str, dict[tuple[str, int], list[dict[str, object]]]],
) -> int:
    count = 0
    with gzip.open(path, "wt", encoding="utf-8", newline="", compresslevel=6) as handle:
        writer = csv.DictWriter(handle, fieldnames=HOLDING_FIELDS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for sample in samples.to_dict("records"):
            prefix = {
                "sample_id": sample["sample_id"], "source_sample_id": sample["source_sample_id"],
                "seed": sample["seed"], "draw_index": sample["draw_index"],
                "start_date": sample["start_date"],
            }
            for records in snapshots[clean(sample["start_date"])].values():
                for record in records:
                    writer.writerow({**prefix, **record})
                    count += 1
    return count


def leakage_audit(
    frame: pd.DataFrame, source_modified: bool, protected_modified: bool,
) -> list[dict[str, object]]:
    output = []
    for row in frame.to_dict("records"):
        valid = truth(row["point_in_time_valid"]) and truth(row["forward_return_starts_after_rebalance"])
        output.append({
            "sample_id": row["sample_id"], "variant": row["variant"],
            "portfolio_size": row["portfolio_size"], "transaction_cost_bps": row["transaction_cost_bps"],
            "start_date": row["start_date"], "ranking_max_input_date": row["ranking_max_input_date"],
            "ranking_inputs_lte_each_rebalance_date": row["point_in_time_valid"],
            "forward_return_starts_strictly_after_rebalance_date": row["forward_return_starts_after_rebalance"],
            "current_ranking_used": "FALSE", "event_risk_coefficients_used": "FALSE",
            "future_label_used": "FALSE", "source_outputs_modified": str(source_modified).upper(),
            "protected_outputs_modified": str(protected_modified).upper(),
            "point_in_time_valid": str(valid and not source_modified and not protected_modified).upper(),
            "leakage_violation_reason": "" if valid else "PIT_TIMESTAMP_OR_FORWARD_RETURN_BOUNDARY_FAILURE",
            "research_only": "TRUE",
        })
    return output


def classify(
    summary: pd.DataFrame, hold_compare: pd.DataFrame, leakage_failures: int,
    source_modified: bool, protected_modified: bool,
) -> tuple[str, str, dict[str, Any]]:
    if leakage_failures or source_modified or protected_modified:
        return FAIL_BLOCKER, "STOP_LEAKAGE_OR_OUTPUT_MUTATION_BLOCKER", {}
    d10 = summary[(summary["variant"] == "D") & (summary["transaction_cost_bps"] == 10)]
    hold10 = hold_compare[(hold_compare["variant"] == "D") & (hold_compare["transaction_cost_bps"] == 10)]
    candidates = d10[
        (d10["win_rate_vs_A1"] > .55) & (d10["win_rate_vs_QQQ"] > .55)
        & (d10["median_excess_vs_QQQ"] > 0)
    ]
    p5_ok = bool((hold10["p5_excess_vs_QQQ_change"] >= -.05).any())
    cost_ok = bool((d10["mean_excess_vs_QQQ"] > 0).any())
    materially_hold_better = bool(
        ((hold10["mean_return_change"] < -.03) & (hold10["median_return_change"] < -.03)).any()
    )
    underperform = bool(((d10["mean_excess_vs_A1"] < 0) | (d10["mean_excess_vs_QQQ"] < 0)).all())
    high_turnover = bool((d10["annualized_turnover"] > 6.0).all())
    facts = {
        "promising_portfolio_sizes_10bps": sorted(candidates["portfolio_size"].astype(int).tolist()),
        "p5_not_materially_worse_than_hold": p5_ok, "transaction_cost_does_not_erase_edge": cost_ok,
        "monthly_rebalance_materially_worse_than_hold": materially_hold_better,
        "high_turnover_warning": high_turnover,
    }
    if underperform:
        return FAIL_UNDERPERFORM, "D_REBALANCE_UNDERPERFORMS_A1_OR_QQQ_AT_10BPS", facts
    if materially_hold_better:
        return PARTIAL_HOLD, "D_HOLD_ONLY_RESULTS_ARE_MATERIALLY_BETTER_THAN_MONTHLY_REBALANCE", facts
    if not candidates.empty and p5_ok and cost_ok:
        if high_turnover or bool((candidates["transaction_cost_drag"] > .03).any()):
            return PARTIAL_COST, "D_REBALANCE_EDGE_EXISTS_WITH_TURNOVER_OR_COST_WARNING", facts
        return PASS, "D_REBALANCE_EDGE_CONFIRMED_AT_10BPS_RESEARCH_ONLY", facts
    return PARTIAL_NO_EDGE, "D_DOES_NOT_CLEAR_ALL_REBALANCE_PROMISE_THRESHOLDS", facts


def render_readme(
    output: Path, run_id: str, status: str, decision: str, facts: dict[str, Any],
    summary: pd.DataFrame, hold_compare: pd.DataFrame, turnover: pd.DataFrame,
    leakage_failures: int, sample_count: int, holdings_rows: int,
) -> None:
    def metric(size: int, column: str) -> float:
        row = summary[(summary["variant"] == "D") & (summary["portfolio_size"] == size) & (summary["transaction_cost_bps"] == 10)]
        return float(row.iloc[0][column]) if not row.empty else np.nan

    def beat(name: str) -> str:
        values = [metric(size, f"win_rate_vs_{name}") for size in SIZES]
        best = max(values)
        return f"{'YES' if best > .55 else 'NO'} (best Top20/Top50 win rate at 10 bps={best:.4f}; required >0.55)"

    d_hold = hold_compare[(hold_compare["variant"] == "D") & (hold_compare["transaction_cost_bps"] == 10)]
    improved_sizes = d_hold.loc[d_hold["mean_return_change"] > 0, "portfolio_size"].astype(int).tolist()
    worsened_sizes = d_hold.loc[d_hold["mean_return_change"] <= 0, "portfolio_size"].astype(int).tolist()
    if improved_sizes and worsened_sizes:
        improved_text = f"MIXED (improved Top{','.join(map(str, improved_sizes))}; hurt Top{','.join(map(str, worsened_sizes))})"
    else:
        improved_text = "YES" if improved_sizes else "NO"
    d_turn = turnover[turnover["variant"].eq("D")]
    acceptable = bool(d_turn["turnover_acceptable"].eq("TRUE").any())
    left_tail = any(metric(size, "p5_excess_vs_QQQ") < -.30 for size in SIZES)
    text = f"""# V21.105 A1/B/C/D Random 252D Monthly-Rebalance Backtest

FINAL_STATUS: `{status}`  
DECISION: `{decision}`  
run_id: `{run_id}`  
source V21.104 run_id: `{SOURCE_RUN_ID}`  
source V21.104-R1 run_id: `{SOURCE_R1_RUN_ID}`  
source V21.104-R2 run_id: `{SOURCE_R2_RUN_ID}`  
sample_count: `{sample_count}`  
transaction cost scenarios: `0, 10, 20 bps`  
official_adoption_allowed: `false`  
broker_action_allowed: `false`

## Decision summary

- D beat A1: {beat("A1")}
- D beat B: {beat("B")}
- D beat C: {beat("C")}
- D beat QQQ: {beat("QQQ")}
- D beat SOXX: {beat("SOXX")}
- Monthly rebalance improved over hold-only: {improved_text}
- Turnover acceptable: {'YES' if acceptable else 'NO'}
- Transaction costs erased the edge: {'NO' if facts.get("transaction_cost_does_not_erase_edge") else 'YES'}
- D has left-tail or drawdown weakness: {'YES' if left_tail else 'NO MATERIAL QQQ LEFT-TAIL WEAKNESS'}
- Leakage failures: {leakage_failures}
- Holdings snapshot rows: {holdings_rows}
- Warnings preserved: `SURVIVORSHIP_BIAS_WARN`, `PIT_FACTOR_APPROXIMATION_WARN`

## Method boundaries

- The exact V21.104 sample IDs and dates were reused.
- Rankings were recomputed at each 21-trading-day rebalance using inputs timestamped no later than that date.
- Forward price changes begin after each rebalance timestamp.
- Portfolios are equal-weighted at each rebalance; costs are charged against realized one-way replacement turnover, including initial formation.
- Event-risk coefficients and current ranking outputs were not used.
- Historical universe membership remains unavailable, and PIT factors remain approximate.

## Classification facts

```json
{json.dumps(facts, indent=2)}
```

This result is research-only. It cannot authorize official adoption or broker action.
"""
    (output / README).write_text(text, encoding="utf-8")


def run_stage(root: Path, output: Path, run_id: str, max_samples: int | None = None) -> dict[str, object]:
    root, output = root.resolve(), output.resolve()
    v103 = load_v103(root)
    source = (root / SOURCE_REL).resolve()
    source_before = source_hashes(source)
    protected = v103.protected_files(root, output)
    protected_before = {path: sha256(path) for path in protected}
    warnings = [
        {"warning_code": "SURVIVORSHIP_BIAS_WARN", "severity": "MEDIUM", "scope": "ALL_SAMPLES",
         "details": "Historical PIT universe membership is unavailable.", "research_only": "TRUE"},
        {"warning_code": "PIT_FACTOR_APPROXIMATION_WARN", "severity": "MEDIUM", "scope": "ALL_RANKINGS",
         "details": "Historical full-factor inputs are unavailable; V21.103/V21.104 PIT-lite factors are used.", "research_only": "TRUE"},
    ]
    samples = pd.DataFrame()
    rows: list[dict[str, object]] = []
    holdings_rows = 0
    try:
        data = v103.load_market_data(root)
        if data.semiconductor_benchmark != "SOXX":
            raise RuntimeError("SOXX benchmark is required.")
        features = v103.rolling_features(data)
        source_samples = pd.read_csv(source / "v21_104_abcd_random_sample_dates.csv", dtype={"start_date": str})
        source_samples["source_sample_id"] = source_samples["sample_id"]
        samples = source_samples.copy()
        if max_samples is not None:
            samples = samples.head(max_samples).copy()
            warnings.append({"warning_code": "MAX_SAMPLES_VALIDATION_OVERRIDE", "severity": "MEDIUM", "scope": "STAGE",
                             "details": f"Run capped at {max_samples} samples.", "research_only": "TRUE"})
        samples["v21_105_sample_id"] = samples["sample_id"]
        samples["mapping_status"] = "EXACT_V21_104_SAMPLE_REUSED"
        samples["monthly_rebalance_eligible"] = "TRUE"
        samples["filter_reason"] = ""
        mapping_fields = [
            "v21_105_sample_id", "source_sample_id", "seed", "draw_index", "start_date",
            "mapping_status", "monthly_rebalance_eligible", "filter_reason",
        ]
        mapping_rows = samples.rename(columns={"sample_id": "_sample_id"}).to_dict("records")
        write_csv(output / MAPPING, mapping_rows, mapping_fields)
        samples = samples.rename(columns={"v21_105_sample_id": "sample_id_v105"})
        samples["sample_id"] = samples["sample_id_v105"]

        config = {
            "stage": STAGE, "run_id": run_id, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_v21_104_run_id": SOURCE_RUN_ID, "source_v21_104_r1_run_id": SOURCE_R1_RUN_ID,
            "source_v21_104_r2_run_id": SOURCE_R2_RUN_ID, "configured_sample_count": 3000,
            "actual_sample_count": len(samples), "sample_dates_reused_exactly": True,
            "simulation_length_trading_days": HORIZON, "rebalance_interval_trading_days": INTERVAL,
            "rebalance_events": HORIZON // INTERVAL, "variants": list(VARIANTS),
            "portfolio_sizes": list(SIZES), "benchmarks": ["QQQ", "SPY", "SOXX"],
            "transaction_cost_bps": list(COSTS), "weighting": "EQUAL_WEIGHT_AT_EACH_REBALANCE",
            "turnover_definition": "ONE_MINUS_OVERLAP_SHARE; INITIAL_FORMATION_EQUALS_1.0",
            "event_risk_integrated": False, "current_rankings_used": False,
            "holdings_format": "csv.gz", "official_adoption_allowed": False,
            "broker_action_allowed": False, "research_only": True,
        }
        write_json(output / CONFIG, config)

        rank_cache: dict[str, dict[str, pd.DataFrame]] = {}
        unique_results: dict[str, dict[tuple[str, int, int], dict[str, object]]] = {}
        snapshots: dict[str, dict[tuple[str, int], list[dict[str, object]]]] = {}
        for start in sorted(samples["start_date"].astype(str).unique()):
            unique_results[start], snapshots[start] = simulate_unique(v103, data, features, start, rank_cache)
        rows = materialize_rows(samples, unique_results)
        frame = numeric(pd.DataFrame(rows), [
            "portfolio_size", "transaction_cost_bps", "portfolio_return", "gross_portfolio_return",
            "transaction_cost_drag", "benchmark_QQQ_return", "benchmark_SPY_return",
            "benchmark_SOXX_return", "excess_vs_A1", "excess_vs_B", "excess_vs_C",
            "excess_vs_D", "excess_vs_QQQ", "excess_vs_SPY", "excess_vs_SOXX",
            "max_drawdown", "turnover", "annualized_turnover", "missing_price_count",
        ])
        summary_rows = summaries(frame)
        summary_frame = pd.DataFrame(summary_rows)
        pair_rows = pairwise(frame)
        benchmark_rows = benchmark_comparison(frame)
        hold_source = pd.read_csv(source / "v21_104_abcd_252d_hold_row_results.csv", low_memory=False)
        hold_rows = hold_comparison(frame, hold_source)
        hold_frame = pd.DataFrame(hold_rows)
        turnover_rows = turnover_analysis(frame)
        turnover_frame = pd.DataFrame(turnover_rows)
        size_rows = size_analysis(summary_frame)
        tail_rows = tail_analysis(frame)
        holdings_summary_rows = holdings_summary(samples, snapshots)

        write_csv(output / ROWS, rows, ROW_FIELDS)
        write_csv(output / SUMMARY, summary_rows, SUMMARY_FIELDS)
        write_csv(output / PAIRWISE, pair_rows, list(pair_rows[0]))
        write_csv(output / BENCHMARK, benchmark_rows, list(benchmark_rows[0]))
        write_csv(output / HOLD_COMPARE, hold_rows, list(hold_rows[0]))
        write_csv(output / TURNOVER, turnover_rows, list(turnover_rows[0]))
        write_csv(output / SIZE_COMPARE, size_rows, list(size_rows[0]))
        write_csv(output / TAIL, tail_rows, list(tail_rows[0]))
        write_csv(output / HOLDINGS_SUMMARY, holdings_summary_rows, list(holdings_summary_rows[0]))
        holdings_rows = write_holdings_gz(output / HOLDINGS_GZ, samples, snapshots)

        if int(frame["missing_price_count"].sum()) > 0:
            warnings.append({"warning_code": "MISSING_PRICE_WARN", "severity": "LOW", "scope": "ROW_RESULTS",
                             "details": f"Missing price observations counted: {int(frame['missing_price_count'].sum())}.",
                             "research_only": "TRUE"})
        source_after = source_hashes(source)
        protected_after = {path: sha256(path) for path in protected}
        source_modified = source_before != source_after
        protected_modified = any(protected_before[path] != protected_after[path] for path in protected)
        audit_rows = leakage_audit(frame, source_modified, protected_modified)
        leakage_failures = sum(not truth(row["point_in_time_valid"]) for row in audit_rows)
        write_csv(output / LEAKAGE, audit_rows, list(audit_rows[0]))
        write_csv(output / WARNINGS, warnings, ["warning_code", "severity", "scope", "details", "research_only"])
        status, decision, facts = classify(summary_frame, hold_frame, leakage_failures, source_modified, protected_modified)
        render_readme(output, run_id, status, decision, facts, summary_frame, hold_frame,
                      turnover_frame, leakage_failures, len(samples), holdings_rows)
    except Exception as exc:
        status, decision, leakage_failures = FAIL_BLOCKER, "STOP_EXECUTION_OR_DATA_QUALITY_BLOCKER", 0
        source_modified = source_before != source_hashes(source)
        protected_after = {path: sha256(path) for path in protected}
        protected_modified = any(protected_before[path] != protected_after[path] for path in protected)
        warnings.append({"warning_code": "EXECUTION_BLOCKER", "severity": "HIGH", "scope": "STAGE",
                         "details": str(exc), "research_only": "TRUE"})
        write_csv(output / WARNINGS, warnings, ["warning_code", "severity", "scope", "details", "research_only"])
        for name, fields in (
            (MAPPING, ["v21_105_sample_id", "source_sample_id", "start_date"]),
            (ROWS, ROW_FIELDS), (SUMMARY, SUMMARY_FIELDS), (PAIRWISE, ["left", "right"]),
            (BENCHMARK, ["variant", "benchmark"]), (HOLD_COMPARE, ["variant", "portfolio_size"]),
            (TURNOVER, ["variant", "portfolio_size"]), (SIZE_COMPARE, ["variant"]),
            (TAIL, ["variant"]), (LEAKAGE, ["sample_id", "point_in_time_valid"]),
            (HOLDINGS_SUMMARY, ["variant", "portfolio_size"]),
        ):
            if not (output / name).exists():
                write_csv(output / name, [], fields)
        if not (output / CONFIG).exists():
            write_json(output / CONFIG, {"stage": STAGE, "run_id": run_id, "execution_error": str(exc),
                                         "official_adoption_allowed": False, "broker_action_allowed": False})
        if not (output / HOLDINGS_GZ).exists():
            with gzip.open(output / HOLDINGS_GZ, "wt", encoding="utf-8", newline="") as handle:
                csv.DictWriter(handle, fieldnames=HOLDING_FIELDS).writeheader()
        (output / README).write_text(
            f"# V21.105 Monthly Rebalance\n\nFINAL_STATUS: `{status}`  \nDECISION: `{decision}`  \n"
            f"run_id: `{run_id}`  \nofficial_adoption_allowed: `false`  \nbroker_action_allowed: `false`\n\n"
            f"Blocking error: {exc}\n", encoding="utf-8")
    result = {
        "FINAL_STATUS": status, "DECISION": decision, "RUN_ID": run_id,
        "SAMPLE_COUNT": len(samples), "RESULT_ROWS": len(rows), "HOLDINGS_ROWS": holdings_rows,
        "LEAKAGE_FAILURES": leakage_failures, "SOURCE_OUTPUTS_MODIFIED": source_modified,
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
    parser.add_argument("--max-samples", type=int)
    args = parser.parse_args()
    output, run_id = immutable_output(args.root.resolve(), args.output_dir, args.run_id)
    result = run_stage(args.root, output, run_id, args.max_samples)
    return 1 if str(result["FINAL_STATUS"]).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
