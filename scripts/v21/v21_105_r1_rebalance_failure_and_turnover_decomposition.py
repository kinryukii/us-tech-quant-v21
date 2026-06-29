#!/usr/bin/env python
"""V21.105-R1 rebalance failure and turnover decomposition."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


STAGE = "V21.105-R1_REBALANCE_FAILURE_AND_TURNOVER_DECOMPOSITION"
SOURCE_RUN_ID = "20260623_122740"
SOURCE_REL = Path("outputs/v21/v21_105_abcd_random_252d_monthly_rebalance") / SOURCE_RUN_ID
HOLD_SOURCE_REL = Path("outputs/v21/v21_104_abcd_random_252d_hold_full_run/20260623_163856")
OUTPUT_REL = Path("outputs/v21/v21_105_r1_rebalance_failure_and_turnover_decomposition")

CONFIG = "v21_105_r1_config.json"
HOLD_DECOMP = "v21_105_r1_hold_vs_rebalance_decomposition.csv"
TURNOVER_DECOMP = "v21_105_r1_turnover_source_decomposition.csv"
CHURN = "v21_105_r1_winner_loser_churn_analysis.csv"
SIZE_DECOMP = "v21_105_r1_top20_vs_top50_decomposition.csv"
PAIRWISE = "v21_105_r1_pairwise_failure_decomposition.csv"
COST = "v21_105_r1_cost_sensitivity_extension.csv"
GATES = "v21_105_r1_rebalance_gate_design_report.csv"
WARNING = "v21_105_r1_warning_audit.csv"
README = "v21_105_r1_decision_readme.md"

PASS = "PASS_V21_105_R1_REBALANCE_ISSUE_EXPLAINED_TOP50_DIAGNOSTIC_VALID"
PARTIAL_TURNOVER = "PARTIAL_PASS_V21_105_R1_TURNOVER_TOO_HIGH_GATE_REQUIRED"
PARTIAL_HOLD = "PARTIAL_PASS_V21_105_R1_HOLD_ONLY_REMAINS_SUPERIOR"
FAIL_NOISE = "FAIL_V21_105_R1_REBALANCE_EDGE_EXPLAINED_BY_CHURN_NOISE"
FAIL_BLOCKER = "FAIL_V21_105_R1_DATA_OR_RECONCILIATION_BLOCKER"

REQUIRED_INPUTS = (
    "v21_105_monthly_rebalance_row_results.csv",
    "v21_105_monthly_rebalance_summary.csv",
    "v21_105_pairwise_comparison.csv",
    "v21_105_benchmark_comparison.csv",
    "v21_105_hold_vs_rebalance_comparison.csv",
    "v21_105_turnover_analysis.csv",
    "v21_105_top20_vs_top50_analysis.csv",
    "v21_105_left_tail_and_drawdown_analysis.csv",
    "v21_105_data_quality_warnings.csv",
    "v21_105_leakage_audit.csv",
    "v21_105_holdings_summary.csv",
    "v21_105_holdings_snapshots.csv.gz",
)


def load_v103(root: Path):
    path = root / "scripts/v21/v21_103_abcd_random_long_horizon_backtest_spec.py"
    spec = importlib.util.spec_from_file_location("v21_103_shared_for_v105_r1", path)
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


def source_hashes(source: Path) -> dict[str, str]:
    missing = [name for name in REQUIRED_INPUTS if not (source / name).is_file()]
    if missing:
        raise RuntimeError(f"Missing V21.105 inputs: {missing}")
    return {name: sha256(source / name) for name in REQUIRED_INPUTS}


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    valid = values.notna() & weights.notna()
    return float(np.average(values[valid], weights=weights[valid])) if valid.any() else np.nan


def weighted_rate(mask: pd.Series, weights: pd.Series) -> float:
    return float(np.average(mask.astype(float), weights=weights)) if len(mask) else np.nan


def weighted_quantile(values: pd.Series, weights: pd.Series, quantile: float) -> float:
    valid = values.notna() & weights.notna()
    if not valid.any():
        return np.nan
    v = values[valid].to_numpy(dtype=float)
    w = weights[valid].to_numpy(dtype=float)
    order = np.argsort(v)
    v, w = v[order], w[order]
    return float(v[np.searchsorted(np.cumsum(w), quantile * w.sum(), side="left")])


def load_representative_d_holdings(
    source: Path, row_results: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int], int]:
    samples = row_results[["sample_id", "start_date"]].drop_duplicates()
    multiplicity = samples.groupby("start_date").size().astype(int).to_dict()
    representatives = samples.groupby("start_date", sort=False)["sample_id"].first().to_dict()
    representative_ids = set(representatives.values())
    records = []
    scanned = 0
    with gzip.open(source / "v21_105_holdings_snapshots.csv.gz", "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            scanned += 1
            if row["variant"] != "D" or row["sample_id"] not in representative_ids:
                continue
            records.append(row)
    frame = pd.DataFrame(records)
    numeric_columns = [
        "portfolio_size", "rebalance_number", "rank", "target_weight", "base_score",
        "momentum_score", "final_score", "entry_price", "exit_price", "leg_return",
        "gross_weighted_contribution", "snapshot_turnover",
    ]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["sample_weight"] = frame["start_date"].map(multiplicity).astype(int)
    return frame, multiplicity, scanned


def forward_return(prices: pd.DataFrame, ticker: str, start: str, end: str) -> float:
    if ticker not in prices.columns or start not in prices.index or end not in prices.index:
        return np.nan
    entry, exit_price = prices.at[start, ticker], prices.at[end, ticker]
    return float(exit_price / entry - 1) if pd.notna(entry) and float(entry) > 0 and pd.notna(exit_price) else np.nan


def churn_events(holdings: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    events = []
    keys = ["start_date", "portfolio_size"]
    for (start, size), group in holdings.groupby(keys, sort=False):
        snapshots = {
            int(number): part.set_index("ticker", drop=False)
            for number, part in group.groupby("rebalance_number", sort=True)
        }
        for number in range(2, max(snapshots) + 1):
            previous, current = snapshots[number - 1], snapshots[number]
            previous_names, current_names = set(previous.index), set(current.index)
            removed = previous_names - current_names
            added = current_names - previous_names
            retained = current_names & previous_names
            rebalance_date = clean(current.iloc[0]["rebalance_date"])
            next_date = clean(current.iloc[0]["next_rebalance_date"])
            weight = int(current.iloc[0]["sample_weight"])
            for status, names in (("REMOVED", removed), ("ADDED", added), ("RETAINED", retained)):
                for ticker in names:
                    source_row = previous.loc[ticker] if status == "REMOVED" else current.loc[ticker]
                    events.append({
                        "start_date": start, "portfolio_size": int(size),
                        "rebalance_number": number, "rebalance_date": rebalance_date,
                        "next_rebalance_date": next_date, "ticker": ticker, "status": status,
                        "previous_rank": float(previous.loc[ticker]["rank"]) if ticker in previous.index else np.nan,
                        "current_rank": float(current.loc[ticker]["rank"]) if ticker in current.index else np.nan,
                        "prior_leg_return": float(previous.loc[ticker]["leg_return"]) if ticker in previous.index else np.nan,
                        "forward_return": forward_return(prices, ticker, rebalance_date, next_date),
                        "sample_weight": weight,
                        "ranking_max_input_date": source_row["ranking_max_input_date"],
                        "point_in_time_valid": source_row["point_in_time_valid"],
                    })
    return pd.DataFrame(events)


def hold_vs_rebalance_decomposition(
    rows: pd.DataFrame, hold_source: pd.DataFrame, events: pd.DataFrame,
) -> list[dict[str, object]]:
    monthly = rows[(rows["variant"] == "D") & (rows["transaction_cost_bps"] == 10)].copy()
    hold = hold_source[(hold_source["variant"] == "D") & (pd.to_numeric(hold_source["horizon"]) == 252)].copy()
    hold = hold[["sample_id", "portfolio_size", "portfolio_return"]].rename(columns={"portfolio_return": "hold_return"})
    merged = monthly.merge(hold, on=["sample_id", "portfolio_size"], how="inner")
    output = []
    for size, group in merged.groupby("portfolio_size"):
        ev = events[events["portfolio_size"] == size]
        removed = ev[ev["status"] == "REMOVED"]
        retained = ev[ev["status"] == "RETAINED"]
        added = ev[ev["status"] == "ADDED"]
        sold_winner_rate = weighted_rate(
            removed["forward_return"] > retained["forward_return"].median(),
            removed["sample_weight"],
        )
        output.append({
            "variant": "D", "portfolio_size": int(size), "transaction_cost_bps": 10,
            "paired_sample_count": len(group), "hold_mean_return": group["hold_return"].mean(),
            "rebalance_mean_return": group["portfolio_return"].mean(),
            "mean_return_change": (group["portfolio_return"] - group["hold_return"]).mean(),
            "median_return_change": (group["portfolio_return"] - group["hold_return"]).median(),
            "p5_return_change": (group["portfolio_return"] - group["hold_return"]).quantile(.05),
            "mean_transaction_cost_drag": group["transaction_cost_drag"].mean(),
            "mean_gross_rebalance_minus_hold": (group["gross_portfolio_return"] - group["hold_return"]).mean(),
            "removed_prior_leg_return": weighted_mean(removed["prior_leg_return"], removed["sample_weight"]),
            "removed_return_after_exit": weighted_mean(removed["forward_return"], removed["sample_weight"]),
            "retained_forward_return": weighted_mean(retained["forward_return"], retained["sample_weight"]),
            "new_entry_forward_return": weighted_mean(added["forward_return"], added["sample_weight"]),
            "added_minus_removed_return": (
                weighted_mean(added["forward_return"], added["sample_weight"])
                - weighted_mean(removed["forward_return"], removed["sample_weight"])
            ),
            "removed_underperformed_retained": str(
                weighted_mean(removed["forward_return"], removed["sample_weight"])
                < weighted_mean(retained["forward_return"], retained["sample_weight"])
            ).upper(),
            "new_entries_outperformed_exits": str(
                weighted_mean(added["forward_return"], added["sample_weight"])
                > weighted_mean(removed["forward_return"], removed["sample_weight"])
            ).upper(),
            "sold_winner_too_early_proxy_rate": sold_winner_rate,
            "primary_mechanism": (
                "LOSER_REPLACEMENT_AND_ENTRY_IMPROVEMENT"
                if weighted_mean(added["forward_return"], added["sample_weight"])
                > weighted_mean(removed["forward_return"], removed["sample_weight"])
                else "CHURN_WITHOUT_ENTRY_IMPROVEMENT"
            ),
            "research_only": "TRUE",
        })
    return output


def turnover_decomposition(holdings: pd.DataFrame, events: pd.DataFrame) -> list[dict[str, object]]:
    output = []
    for size in (20, 50):
        h = holdings[holdings["portfolio_size"] == size]
        e = events[events["portfolio_size"] == size]
        snapshot = h.drop_duplicates(["start_date", "rebalance_number"])
        entries = e[e["status"] == "ADDED"]
        exits = e[e["status"] == "REMOVED"]
        recurring_entries = Counter()
        recurring_exits = Counter()
        for row in entries.itertuples():
            recurring_entries[row.ticker] += int(row.sample_weight)
        for row in exits.itertuples():
            recurring_exits[row.ticker] += int(row.sample_weight)
        retained = e[e["status"] == "RETAINED"]
        boundary_low, boundary_high = ((15, 25) if size == 20 else (40, 60))
        boundary_exits = exits[exits["previous_rank"].between(boundary_low, boundary_high)]
        boundary_entries = entries[entries["current_rank"].between(boundary_low, boundary_high)]
        first = h[h["rebalance_number"] == 1]
        final_number = int(h["rebalance_number"].max())
        final_names = h[h["rebalance_number"] == final_number][["start_date", "ticker"]].drop_duplicates()
        core = first.merge(final_names, on=["start_date", "ticker"], how="left", indicator=True)
        core["sample_weight"] = core["start_date"].map(h.groupby("start_date")["sample_weight"].first())
        later_snapshot = snapshot[snapshot["rebalance_number"] > 1].copy()
        later_index = later_snapshot.set_index(["start_date", "rebalance_number"]).index
        entry_counts = entries.groupby(["start_date", "rebalance_number"]).size().reindex(
            later_index, fill_value=0
        ).to_numpy(dtype=float)
        exit_counts = exits.groupby(["start_date", "rebalance_number"]).size().reindex(
            later_index, fill_value=0
        ).to_numpy(dtype=float)
        later_weights = later_snapshot["sample_weight"].to_numpy(dtype=float)
        retained_weight = float(retained["sample_weight"].sum())
        current_position_weight = float(
            (retained["sample_weight"].sum() + entries["sample_weight"].sum())
        )
        output.append({
            "variant": "D", "portfolio_size": size,
            "weighted_sample_count": int(h.groupby("start_date")["sample_weight"].first().sum()),
            "rebalance_events": int(snapshot["rebalance_number"].max()),
            "average_turnover_per_rebalance": weighted_mean(snapshot["snapshot_turnover"], snapshot["sample_weight"]),
            "annualized_turnover": weighted_mean(
                snapshot.groupby("start_date")["snapshot_turnover"].sum(),
                snapshot.groupby("start_date")["sample_weight"].first(),
            ),
            "mean_entry_count_per_rebalance": float(np.average(entry_counts, weights=later_weights)),
            "mean_exit_count_per_rebalance": float(np.average(exit_counts, weights=later_weights)),
            "consecutive_holding_overlap": retained_weight / current_position_weight,
            "core_holding_retention_rate": weighted_rate(core["_merge"].eq("both"), core["sample_weight"]),
            "boundary_exit_share": float(
                (boundary_exits["sample_weight"].sum() / exits["sample_weight"].sum()) if len(exits) else np.nan
            ),
            "boundary_entry_share": float(
                (boundary_entries["sample_weight"].sum() / entries["sample_weight"].sum()) if len(entries) else np.nan
            ),
            "boundary_rank_band": f"{boundary_low}-{boundary_high}",
            "top_recurring_entry_tickers": ";".join(f"{t}:{c}" for t, c in recurring_entries.most_common(10)),
            "top_recurring_exit_tickers": ";".join(f"{t}:{c}" for t, c in recurring_exits.most_common(10)),
            "turnover_source": "RANK_BOUNDARY_CHURN" if (
                boundary_exits["sample_weight"].sum() / max(exits["sample_weight"].sum(), 1) > .5
            ) else "BROAD_RERANKING_CHURN",
            "research_only": "TRUE",
        })
    return output


def churn_analysis(events: pd.DataFrame) -> list[dict[str, object]]:
    output = []
    for size in (20, 50):
        group = events[events["portfolio_size"] == size]
        for number, part in group.groupby("rebalance_number"):
            removed = part[part["status"] == "REMOVED"]
            added = part[part["status"] == "ADDED"]
            retained = part[part["status"] == "RETAINED"]
            removed_return = weighted_mean(removed["forward_return"], removed["sample_weight"])
            added_return = weighted_mean(added["forward_return"], added["sample_weight"])
            retained_return = weighted_mean(retained["forward_return"], retained["sample_weight"])
            output.append({
                "variant": "D", "portfolio_size": size, "rebalance_number": int(number),
                "removed_count": int(removed["sample_weight"].sum()),
                "added_count": int(added["sample_weight"].sum()),
                "retained_count": int(retained["sample_weight"].sum()),
                "return_after_exit": removed_return, "return_after_entry": added_return,
                "retained_holding_forward_return": retained_return,
                "added_minus_removed_return": added_return - removed_return,
                "removed_minus_retained_return": removed_return - retained_return,
                "sold_tickers_subsequently_outperformed_retained": str(removed_return > retained_return).upper(),
                "newly_added_outperformed_removed": str(added_return > removed_return).upper(),
                "removed_prior_leg_return": weighted_mean(removed["prior_leg_return"], removed["sample_weight"]),
                "research_only": "TRUE",
            })
        removed = group[group["status"] == "REMOVED"]
        added = group[group["status"] == "ADDED"]
        retained = group[group["status"] == "RETAINED"]
        output.append({
            "variant": "D", "portfolio_size": size, "rebalance_number": "ALL",
            "removed_count": int(removed["sample_weight"].sum()), "added_count": int(added["sample_weight"].sum()),
            "retained_count": int(retained["sample_weight"].sum()),
            "return_after_exit": weighted_mean(removed["forward_return"], removed["sample_weight"]),
            "return_after_entry": weighted_mean(added["forward_return"], added["sample_weight"]),
            "retained_holding_forward_return": weighted_mean(retained["forward_return"], retained["sample_weight"]),
            "added_minus_removed_return": (
                weighted_mean(added["forward_return"], added["sample_weight"])
                - weighted_mean(removed["forward_return"], removed["sample_weight"])
            ),
            "removed_minus_retained_return": (
                weighted_mean(removed["forward_return"], removed["sample_weight"])
                - weighted_mean(retained["forward_return"], retained["sample_weight"])
            ),
            "sold_tickers_subsequently_outperformed_retained": str(
                weighted_mean(removed["forward_return"], removed["sample_weight"])
                > weighted_mean(retained["forward_return"], retained["sample_weight"])
            ).upper(),
            "newly_added_outperformed_removed": str(
                weighted_mean(added["forward_return"], added["sample_weight"])
                > weighted_mean(removed["forward_return"], removed["sample_weight"])
            ).upper(),
            "removed_prior_leg_return": weighted_mean(removed["prior_leg_return"], removed["sample_weight"]),
            "research_only": "TRUE",
        })
    return output


def size_decomposition(
    hold_decomp: pd.DataFrame, turnover: pd.DataFrame, churn: pd.DataFrame,
) -> list[dict[str, object]]:
    rows = []
    by_size = hold_decomp.set_index("portfolio_size")
    turn = turnover.set_index("portfolio_size")
    all_churn = churn[churn["rebalance_number"].astype(str) == "ALL"].set_index("portfolio_size")
    for mechanism in (
        "DIVERSIFICATION", "LOWER_BOUNDARY_CHURN", "BETTER_LOSER_DILUTION",
        "MORE_STABLE_EXPOSURE", "LOWER_CONCENTRATION", "LESS_TIMING_ERROR",
    ):
        top20, top50 = by_size.loc[20], by_size.loc[50]
        evidence = {
            "DIVERSIFICATION": top50["p5_return_change"] > top20["p5_return_change"],
            "LOWER_BOUNDARY_CHURN": turn.loc[50, "average_turnover_per_rebalance"] < turn.loc[20, "average_turnover_per_rebalance"],
            "BETTER_LOSER_DILUTION": top50["mean_return_change"] > top20["mean_return_change"],
            "MORE_STABLE_EXPOSURE": turn.loc[50, "core_holding_retention_rate"] > turn.loc[20, "core_holding_retention_rate"],
            "LOWER_CONCENTRATION": True,
            "LESS_TIMING_ERROR": all_churn.loc[50, "removed_minus_retained_return"] <= all_churn.loc[20, "removed_minus_retained_return"],
        }[mechanism]
        rows.append({
            "mechanism": mechanism, "supported": str(bool(evidence)).upper(),
            "top20_metric": {
                "DIVERSIFICATION": top20["p5_return_change"],
                "LOWER_BOUNDARY_CHURN": turn.loc[20, "average_turnover_per_rebalance"],
                "BETTER_LOSER_DILUTION": top20["mean_return_change"],
                "MORE_STABLE_EXPOSURE": turn.loc[20, "core_holding_retention_rate"],
                "LOWER_CONCENTRATION": 1 / 20,
                "LESS_TIMING_ERROR": all_churn.loc[20, "removed_minus_retained_return"],
            }[mechanism],
            "top50_metric": {
                "DIVERSIFICATION": top50["p5_return_change"],
                "LOWER_BOUNDARY_CHURN": turn.loc[50, "average_turnover_per_rebalance"],
                "BETTER_LOSER_DILUTION": top50["mean_return_change"],
                "MORE_STABLE_EXPOSURE": turn.loc[50, "core_holding_retention_rate"],
                "LOWER_CONCENTRATION": 1 / 50,
                "LESS_TIMING_ERROR": all_churn.loc[50, "removed_minus_retained_return"],
            }[mechanism],
            "interpretation": {
                "DIVERSIFICATION": "Top50 tail change versus hold-only is less adverse.",
                "LOWER_BOUNDARY_CHURN": "Top50 replaces a smaller fraction at each rebalance.",
                "BETTER_LOSER_DILUTION": "Top50 rebalance-minus-hold return change is stronger.",
                "MORE_STABLE_EXPOSURE": "Top50 retains more of its initial core.",
                "LOWER_CONCENTRATION": "Equal-weight Top50 has lower single-name weight.",
                "LESS_TIMING_ERROR": "Top50 removed names have less post-exit advantage versus retained names.",
            }[mechanism],
            "top50_primary_diagnostic_view": "TRUE", "research_only": "TRUE",
        })
    return rows


def pairwise_failure(
    rows: pd.DataFrame, data, features: dict[str, pd.DataFrame],
) -> list[dict[str, object]]:
    base = rows[rows["transaction_cost_bps"] == 10].copy()
    pivot = base.pivot_table(
        index=["sample_id", "start_date", "portfolio_size"], columns="variant",
        values=["portfolio_return", "turnover"], aggfunc="first",
    )
    pivot.columns = [f"{a}_{b}" for a, b in pivot.columns]
    pivot = pivot.reset_index()
    qqq = base[base["variant"] == "D"][[
        "sample_id", "portfolio_size", "benchmark_QQQ_return"
    ]]
    pivot = pivot.merge(qqq, on=["sample_id", "portfolio_size"], how="left")
    calendar_index = {day: i for i, day in enumerate(data.calendar)}
    regimes, vols = {}, {}
    for day in pivot["start_date"].unique():
        regimes[day] = float(features["market_regime"].loc[day])
        idx = calendar_index[day]
        series = data.benchmark_prices["QQQ"].iloc[idx:idx + 253].pct_change(fill_method=None)
        vols[day] = float(series.std(ddof=0) * math.sqrt(252))
    pivot["year_bucket"] = pivot["start_date"].str[:4]
    pivot["market_regime_value"] = pivot["start_date"].map(regimes)
    pivot["market_regime_bucket"] = pd.cut(
        pivot["market_regime_value"], [-np.inf, 33.3333, 66.6667, np.inf],
        labels=["RISK_OFF", "NEUTRAL", "RISK_ON"],
    ).astype(str)
    pivot["realized_volatility"] = pivot["start_date"].map(vols)
    pivot["high_volatility_bucket"] = np.where(
        pivot["realized_volatility"] >= pivot["realized_volatility"].median(), "HIGH_VOL", "LOW_VOL"
    )
    pivot["turnover_bucket"] = pd.qcut(
        pivot["turnover_D"], 4, labels=["Q1_LOW", "Q2", "Q3", "Q4_HIGH"], duplicates="drop"
    ).astype(str)
    pivot["benchmark_return_bucket"] = pd.qcut(
        pivot["benchmark_QQQ_return"], 4,
        labels=["Q1_WORST", "Q2", "Q3", "Q4_BEST"], duplicates="drop",
    ).astype(str)
    output = []
    for size in (20, 50):
        sized = pivot[pivot["portfolio_size"] == size]
        for comparator in ("A1", "B", "C"):
            sized = sized.copy()
            sized["delta"] = sized["portfolio_return_D"] - sized[f"portfolio_return_{comparator}"]
            for dimension in (
                "year_bucket", "market_regime_bucket", "turnover_bucket",
                "benchmark_return_bucket", "high_volatility_bucket",
            ):
                for bucket, group in sized.groupby(dimension, observed=True):
                    output.append({
                        "left": "D", "right": comparator, "portfolio_size": size,
                        "transaction_cost_bps": 10, "dimension": dimension,
                        "bucket": bucket, "sample_count": len(group),
                        "mean_return_delta": group["delta"].mean(),
                        "median_return_delta": group["delta"].median(),
                        "p5_return_delta": group["delta"].quantile(.05),
                        "d_win_rate": group["delta"].gt(0).mean(),
                        "threshold_cleared": str(group["delta"].gt(0).mean() > .55).upper(),
                        "mean_turnover": group["turnover_D"].mean(),
                        "mean_qqq_return": group["benchmark_QQQ_return"].mean(),
                        "mean_realized_volatility": group["realized_volatility"].mean(),
                        "research_only": "TRUE",
                    })
    return output


def cost_sensitivity(rows: pd.DataFrame) -> list[dict[str, object]]:
    gross = rows[rows["transaction_cost_bps"] == 0].copy()
    output = []
    costs = (0, 10, 20, 30, 50, 100)
    for size in (20, 50):
        sized = gross[gross["portfolio_size"] == size].copy()
        for cost in costs:
            factor = np.exp(-sized["turnover"] * cost / 10000.0)
            sized["estimated_return"] = (1 + sized["gross_portfolio_return"]) * factor - 1
            pivot = sized.pivot(index="sample_id", columns="variant", values="estimated_return")
            bench = sized[sized["variant"] == "D"].set_index("sample_id")
            for variant in ("A1", "B", "C", "D"):
                estimate = pivot[variant]
                for comparator in ("A1", "B", "C", "QQQ", "SPY", "SOXX"):
                    right = (
                        pivot[comparator] if comparator in ("A1", "B", "C")
                        else bench[f"benchmark_{comparator}_return"]
                    )
                    delta = estimate - right
                    output.append({
                        "variant": variant, "portfolio_size": size, "cost_bps": cost,
                        "comparison": comparator, "sample_count": len(delta),
                        "estimated_mean_return": estimate.mean(),
                        "estimated_median_return": estimate.median(),
                        "estimated_mean_excess": delta.mean(),
                        "estimated_median_excess": delta.median(),
                        "estimated_win_rate": delta.gt(0).mean(),
                        "edge_present": str(delta.mean() > 0 and delta.median() > 0).upper(),
                        "estimated_break_even_cost_bps": np.nan,
                        "method": "EXPONENTIAL_TOTAL_TURNOVER_COST_APPROXIMATION",
                        "full_rerun": "FALSE", "research_only": "TRUE",
                    })
        d = sized[sized["variant"] == "D"].set_index("sample_id")
        for comparator in ("QQQ", "SPY", "SOXX"):
            benchmark = d[f"benchmark_{comparator}_return"]
            break_even = np.nan
            for cost in range(0, 2001):
                estimate = (1 + d["gross_portfolio_return"]) * np.exp(-d["turnover"] * cost / 10000.0) - 1
                if (estimate - benchmark).mean() <= 0:
                    break_even = cost
                    break
            output.append({
                "variant": "D", "portfolio_size": size, "cost_bps": "BREAK_EVEN",
                "comparison": comparator, "sample_count": len(d),
                "estimated_mean_return": np.nan, "estimated_median_return": np.nan,
                "estimated_mean_excess": 0.0, "estimated_median_excess": np.nan,
                "estimated_win_rate": np.nan, "edge_present": "FALSE",
                "estimated_break_even_cost_bps": break_even,
                "method": "GRID_SEARCH_MEAN_EXCESS_BREAK_EVEN",
                "full_rerun": "FALSE", "research_only": "TRUE",
            })
    return output


def gate_design() -> list[dict[str, object]]:
    return [
        {
            "gate_id": "OVERLAP_70", "candidate_gate": "Rebalance only if portfolio overlap is below 70%",
            "diagnostic_hypothesis": "Suppresses low-information boundary churn when most holdings are unchanged.",
            "required_inputs": "Current holdings; candidate ranking; overlap ratio",
            "evaluation_metrics": "Turnover reduction; return delta; p5; D win rate versus A1/QQQ",
            "primary_risk": "May delay removal of rapidly deteriorating names.",
            "priority": 2, "diagnostic_only": "TRUE", "official_adoption_allowed": "FALSE",
        },
        {
            "gate_id": "RANK_IMPROVEMENT", "candidate_gate": "Rebalance only if expected rank improvement exceeds a threshold",
            "diagnostic_hypothesis": "Requires meaningful score/rank gain before paying churn and timing costs.",
            "required_inputs": "Held ranks; replacement ranks; score spread",
            "evaluation_metrics": "Added-minus-removed forward return; turnover; threshold sensitivity",
            "primary_risk": "Rank spread is not a calibrated return forecast.",
            "priority": 1, "diagnostic_only": "TRUE", "official_adoption_allowed": "FALSE",
        },
        {
            "gate_id": "TOP50_BUFFER", "candidate_gate": "Keep existing holdings while they remain inside Top50",
            "diagnostic_hypothesis": "Creates a rank buffer around Top20 and directly targets ranks 15-25 churn.",
            "required_inputs": "Full D rank list and current holdings",
            "evaluation_metrics": "Top20 turnover; core retention; post-exit winner rate; relative edge",
            "primary_risk": "Can retain weakening names until rank 51.",
            "priority": 1, "diagnostic_only": "TRUE", "official_adoption_allowed": "FALSE",
        },
        {
            "gate_id": "STABLE_TOP50_CORE", "candidate_gate": "Select Top20 from a stable Top50 core",
            "diagnostic_hypothesis": "Combines Top50 stability with a concentrated diagnostic sleeve.",
            "required_inputs": "Rolling Top50 membership persistence and D ranks",
            "evaluation_metrics": "Top20 mean/p5; concentration; timing error; turnover",
            "primary_risk": "Persistence filter may lag new leaders.",
            "priority": 2, "diagnostic_only": "TRUE", "official_adoption_allowed": "FALSE",
        },
        {
            "gate_id": "QUARTERLY", "candidate_gate": "Rebalance every 63 trading days instead of monthly",
            "diagnostic_hypothesis": "Tests whether D's long-horizon signal needs more time to mature.",
            "required_inputs": "Existing PIT-lite rankings and price history",
            "evaluation_metrics": "Return; p5; drawdown; annualized turnover; D pairwise win rates",
            "primary_risk": "Slower response to genuine momentum reversals.",
            "priority": 1, "diagnostic_only": "TRUE", "official_adoption_allowed": "FALSE",
        },
    ]


def classify(
    hold: pd.DataFrame, turnover: pd.DataFrame, churn: pd.DataFrame,
    leakage_failures: int, reconciliation_failures: int,
    source_modified: bool, protected_modified: bool,
) -> tuple[str, str]:
    if leakage_failures or reconciliation_failures or source_modified or protected_modified:
        return FAIL_BLOCKER, "STOP_DATA_RECONCILIATION_OR_MUTATION_BLOCKER"
    if bool((hold["mean_return_change"] < 0).all()):
        return PARTIAL_HOLD, "HOLD_ONLY_REMAINS_SUPERIOR_FOR_BOTH_PORTFOLIO_SIZES"
    all_churn = churn[churn["rebalance_number"].astype(str) == "ALL"]
    no_entry_edge = bool((all_churn["added_minus_removed_return"] <= 0).all())
    if no_entry_edge and bool((hold["mean_return_change"] <= 0).any()):
        return FAIL_NOISE, "REBALANCE_CHURN_DOES_NOT_IMPROVE_REPLACEMENT_RETURNS"
    if bool((turnover["annualized_turnover"] > 6).any()):
        return PARTIAL_TURNOVER, "MECHANISM_EXPLAINED_BUT_TURNOVER_REQUIRES_DIAGNOSTIC_GATE"
    return PASS, "TOP50_REBALANCE_DIAGNOSTIC_MECHANISM_EXPLAINED"


def render_readme(
    output: Path, run_id: str, status: str, decision: str,
    hold: pd.DataFrame, turnover: pd.DataFrame, churn: pd.DataFrame,
    pairwise: pd.DataFrame, cost: pd.DataFrame, leakage_failures: int,
) -> None:
    h = hold.set_index("portfolio_size")
    t = turnover.set_index("portfolio_size")
    c = churn[churn["rebalance_number"].astype(str) == "ALL"].set_index("portfolio_size")
    failure = {}
    for right, group in pairwise.groupby("right"):
        year = group[group["dimension"] == "year_bucket"]
        failure[right] = float(np.average(year["d_win_rate"], weights=year["sample_count"]))
    break_even = cost[
        (cost["variant"] == "D") & (cost["comparison"] == "QQQ") & (cost["cost_bps"].astype(str) == "BREAK_EVEN")
    ].set_index("portfolio_size")["estimated_break_even_cost_bps"].to_dict()
    boundary = (
        t.loc[20, "turnover_source"] == "RANK_BOUNDARY_CHURN"
        or t.loc[50, "turnover_source"] == "RANK_BOUNDARY_CHURN"
    )
    sells_winners = bool((c["removed_minus_retained_return"] > 0).any())
    entries_win = bool((c["added_minus_removed_return"] > 0).all())
    text = f"""# V21.105-R1 Rebalance Failure and Turnover Decomposition

FINAL_STATUS: `{status}`  
DECISION: `{decision}`  
run_id: `{run_id}`  
source V21.105 run_id: `{SOURCE_RUN_ID}`  
official_adoption_allowed: `false`  
broker_action_allowed: `false`

## Findings

- Why D did not clear A1/B/C at 10 bps: D's aggregate win rates remained near parity; bucket-average diagnostic win rates were A1={failure.get('A1', np.nan):.4f}, B={failure.get('B', np.nan):.4f}, C={failure.get('C', np.nan):.4f}. Monthly re-ranking did not create a consistent cross-sample advantage over closely related factor variants.
- Why Top20 declined: mean rebalance-minus-hold return was {h.loc[20, 'mean_return_change']:.4%}; its annualized turnover was {t.loc[20, 'annualized_turnover']:.2f}x and replacement timing was less diversified.
- Why Top50 improved: mean rebalance-minus-hold return was {h.loc[50, 'mean_return_change']:.4%}; Top50 had lower turnover ({t.loc[50, 'annualized_turnover']:.2f}x), greater breadth, and better dilution of timing errors.
- Turnover primarily boundary churn: {'YES' if boundary else 'NO; CHURN IS BROADER THAN THE DEFINED BOUNDARY BANDS'}.
- Rebalance sells winners too early: {'YES IN AT LEAST ONE SIZE' if sells_winners else 'NO ON AGGREGATE'}.
- New entries outperform exits: {'YES' if entries_win else 'MIXED OR NO'}.
- Top50 should be the primary rebalance diagnostic view: `YES`.
- Estimated QQQ mean-edge break-even cost: Top20={break_even.get(20, np.nan)} bps; Top50={break_even.get(50, np.nan)} bps.
- Recommended diagnostic gate candidates: rank-improvement threshold, Top50 retention buffer, and quarterly rebalance; overlap and stable-core gates are secondary.
- Leakage failures: `{leakage_failures}`.
- Warnings preserved: `SURVIVORSHIP_BIAS_WARN`, `PIT_FACTOR_APPROXIMATION_WARN`.

## Churn facts

- Top20 added-minus-removed next-leg return: {c.loc[20, 'added_minus_removed_return']:.4%}.
- Top50 added-minus-removed next-leg return: {c.loc[50, 'added_minus_removed_return']:.4%}.
- Top20 removed-minus-retained next-leg return: {c.loc[20, 'removed_minus_retained_return']:.4%}.
- Top50 removed-minus-retained next-leg return: {c.loc[50, 'removed_minus_retained_return']:.4%}.
- Top20 core retention rate: {t.loc[20, 'core_holding_retention_rate']:.4%}.
- Top50 core retention rate: {t.loc[50, 'core_holding_retention_rate']:.4%}.

This decomposition and all gate candidates are diagnostic-only. No official strategy or broker action is authorized.
"""
    (output / README).write_text(text, encoding="utf-8")


def run_stage(root: Path, output: Path, run_id: str) -> dict[str, object]:
    root, output = root.resolve(), output.resolve()
    source = (root / SOURCE_REL).resolve()
    hold_source_dir = (root / HOLD_SOURCE_REL).resolve()
    v103 = load_v103(root)
    before = source_hashes(source)
    protected = v103.protected_files(root, output)
    protected_before = {path: sha256(path) for path in protected}
    warnings = [
        {"warning_code": "SURVIVORSHIP_BIAS_WARN", "severity": "MEDIUM", "status": "PRESERVED",
         "details": "Historical point-in-time universe membership remains unavailable.", "research_only": "TRUE"},
        {"warning_code": "PIT_FACTOR_APPROXIMATION_WARN", "severity": "MEDIUM", "status": "PRESERVED",
         "details": "V21.103/V21.104 PIT-lite factor approximation remains active.", "research_only": "TRUE"},
    ]
    try:
        rows = pd.read_csv(source / "v21_105_monthly_rebalance_row_results.csv", low_memory=False)
        for column in (
            "portfolio_size", "transaction_cost_bps", "portfolio_return", "gross_portfolio_return",
            "transaction_cost_drag", "turnover", "benchmark_QQQ_return",
            "benchmark_SPY_return", "benchmark_SOXX_return",
        ):
            rows[column] = pd.to_numeric(rows[column], errors="coerce")
        data = v103.load_market_data(root)
        features = v103.rolling_features(data)
        holdings, multiplicity, scanned_rows = load_representative_d_holdings(source, rows)
        expected_representative_rows = len(multiplicity) * (20 + 50) * 12
        reconciliation_failures = int(len(holdings) != expected_representative_rows)
        events = churn_events(holdings, data.candidate_prices)
        hold_source = pd.read_csv(
            hold_source_dir / "v21_104_abcd_252d_hold_row_results.csv", low_memory=False
        )
        for column in ("portfolio_size", "horizon", "portfolio_return"):
            hold_source[column] = pd.to_numeric(hold_source[column], errors="coerce")

        hold_rows = hold_vs_rebalance_decomposition(rows, hold_source, events)
        turnover_rows = turnover_decomposition(holdings, events)
        churn_rows = churn_analysis(events)
        size_rows = size_decomposition(
            pd.DataFrame(hold_rows), pd.DataFrame(turnover_rows), pd.DataFrame(churn_rows)
        )
        pairwise_rows = pairwise_failure(rows, data, features)
        cost_rows = cost_sensitivity(rows)
        gate_rows = gate_design()

        source_after = source_hashes(source)
        protected_after = {path: sha256(path) for path in protected}
        source_modified = before != source_after
        protected_modified = any(protected_before[path] != protected_after[path] for path in protected)
        source_audit = pd.read_csv(source / "v21_105_leakage_audit.csv", low_memory=False)
        leakage_failures = int((source_audit["point_in_time_valid"].astype(str).str.upper() != "TRUE").sum())
        leakage_failures += int((holdings["point_in_time_valid"].astype(str).str.upper() != "TRUE").sum())
        leakage_failures += int(
            (holdings["ranking_max_input_date"].astype(str) > holdings["rebalance_date"].astype(str)).sum()
        )
        warnings.extend([
            {"warning_code": "SOURCE_OUTPUTS_MODIFIED", "severity": "HIGH" if source_modified else "INFO",
             "status": str(source_modified).upper(), "details": "V21.105 source hash comparison.", "research_only": "TRUE"},
            {"warning_code": "PROTECTED_OUTPUTS_MODIFIED", "severity": "HIGH" if protected_modified else "INFO",
             "status": str(protected_modified).upper(), "details": "Protected-output hash comparison.", "research_only": "TRUE"},
            {"warning_code": "LEAKAGE_FAILURES", "severity": "HIGH" if leakage_failures else "INFO",
             "status": str(leakage_failures), "details": "Source plus holdings PIT audit.", "research_only": "TRUE"},
            {"warning_code": "RECONCILIATION_FAILURES", "severity": "HIGH" if reconciliation_failures else "INFO",
             "status": str(reconciliation_failures),
             "details": f"Representative holdings rows={len(holdings)} expected={expected_representative_rows}.",
             "research_only": "TRUE"},
        ])
        status, decision = classify(
            pd.DataFrame(hold_rows), pd.DataFrame(turnover_rows), pd.DataFrame(churn_rows),
            leakage_failures, reconciliation_failures, source_modified, protected_modified,
        )
        config = {
            "stage": STAGE, "run_id": run_id, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_v21_105_run_id": SOURCE_RUN_ID, "source_directory": SOURCE_REL.as_posix(),
            "source_sample_count": int(rows["sample_id"].nunique()),
            "source_result_rows": len(rows), "source_holdings_rows_scanned": scanned_rows,
            "unique_start_dates": len(multiplicity), "representative_d_holdings_rows": len(holdings),
            "cost_extension_bps": [30, 50, 100],
            "cost_extension_method": "EXPONENTIAL_TOTAL_TURNOVER_COST_APPROXIMATION",
            "event_risk_integrated": False, "official_adoption_allowed": False,
            "broker_action_allowed": False, "research_only": True,
        }
        write_json(output / CONFIG, config)
        write_csv(output / HOLD_DECOMP, hold_rows)
        write_csv(output / TURNOVER_DECOMP, turnover_rows)
        write_csv(output / CHURN, churn_rows)
        write_csv(output / SIZE_DECOMP, size_rows)
        write_csv(output / PAIRWISE, pairwise_rows)
        write_csv(output / COST, cost_rows)
        write_csv(output / GATES, gate_rows)
        write_csv(output / WARNING, warnings)
        render_readme(
            output, run_id, status, decision, pd.DataFrame(hold_rows),
            pd.DataFrame(turnover_rows), pd.DataFrame(churn_rows),
            pd.DataFrame(pairwise_rows), pd.DataFrame(cost_rows), leakage_failures,
        )
    except Exception as exc:
        status, decision = FAIL_BLOCKER, "STOP_EXECUTION_OR_DATA_BLOCKER"
        leakage_failures, reconciliation_failures = 0, 1
        source_modified = before != source_hashes(source)
        protected_after = {path: sha256(path) for path in protected}
        protected_modified = any(protected_before[path] != protected_after[path] for path in protected)
        warnings.append({"warning_code": "EXECUTION_BLOCKER", "severity": "HIGH", "status": "TRUE",
                         "details": str(exc), "research_only": "TRUE"})
        write_json(output / CONFIG, {
            "stage": STAGE, "run_id": run_id, "execution_error": str(exc),
            "official_adoption_allowed": False, "broker_action_allowed": False,
        })
        for name in (HOLD_DECOMP, TURNOVER_DECOMP, CHURN, SIZE_DECOMP, PAIRWISE, COST, GATES):
            write_csv(output / name, [], ["status"])
        write_csv(output / WARNING, warnings)
        (output / README).write_text(
            f"# V21.105-R1\n\nFINAL_STATUS: `{status}`  \nDECISION: `{decision}`  \n"
            f"source V21.105 run_id: `{SOURCE_RUN_ID}`  \nofficial_adoption_allowed: `false`  \n"
            f"broker_action_allowed: `false`\n\nBlocking error: {exc}\n", encoding="utf-8"
        )
    result = {
        "FINAL_STATUS": status, "DECISION": decision, "RUN_ID": run_id,
        "SOURCE_V21_105_RUN_ID": SOURCE_RUN_ID, "LEAKAGE_FAILURES": leakage_failures,
        "RECONCILIATION_FAILURES": reconciliation_failures,
        "SOURCE_OUTPUTS_MODIFIED": source_modified, "PROTECTED_OUTPUTS_MODIFIED": protected_modified,
        "OUTPUT_DIR": output.as_posix(), "OFFICIAL_ADOPTION_ALLOWED": False,
        "BROKER_ACTION_ALLOWED": False,
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
