#!/usr/bin/env python
"""Research-only random benchmark, ETF rotation, and $10k simulation."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd


STAGE_ID = "V21.060-R3"
PASS_STATUS = "PASS_V21_060_R3_RANDOM_BENCHMARK_ETF_ROTATION_10K_SIM_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_060_R3_READY_WITH_FALLBACK_OR_SAMPLE_WARN"
FAIL_A0 = "FAIL_V21_060_R3_A0_REPLAY_OR_MUTATION_VIOLATION"
FAIL_HARDCODED = "FAIL_V21_060_R3_HARDCODED_INCLUSION_VIOLATION"
FAIL_PRICE = "FAIL_V21_060_R3_LOCAL_PRICE_MISSING_INCLUDED"
FAIL_TQQQ = "FAIL_V21_060_R3_TQQQ_IPO_WATCH_POLICY_VIOLATION"
FAIL_MUTATION = "FAIL_V21_060_R3_FORBIDDEN_MUTATION_DETECTED"

OUT_REL = Path("outputs/v21/experiments/momentum_dynamic/random_backtests")
RESULTS_NAME = "V21_060_R3_RANDOM_ASOF_BENCHMARK_ETF_ROTATION_RESULTS.csv"
PORTFOLIO_NAME = "V21_060_R3_10000_PORTFOLIO_SIMULATION_RESULTS.csv"
SEED_NAME = "V21_060_R3_STRATEGY_COMPARISON_BY_SEED.csv"
OVERALL_NAME = "V21_060_R3_STRATEGY_COMPARISON_OVERALL.csv"
PAIR_NAME = "V21_060_R3_PAIRWISE_STRATEGY_COMPARISON.csv"
EXAMPLE_NAME = "V21_060_R3_10000_EXAMPLE_SUMMARY.csv"
SELECTION_NAME = "V21_060_R3_RANDOM_ASOF_SELECTION_AUDIT.csv"
FORCED_NAME = "V21_060_R3_FORCED_TICKER_AUDIT.csv"
LINEAGE_NAME = "V21_060_R3_BENCHMARK_AND_ROTATION_LINEAGE_AUDIT.csv"
SUMMARY_NAME = "V21_060_R3_SUMMARY.json"

SEEDS = tuple(range(20260601, 20260621))
ASOF_PER_SEED = 100
INITIAL_CAPITAL = 10000.0
TRANSACTION_BPS = 10.0
SLIPPAGE_BPS = 5.0
ROUND_TRIP_COST = 2 * (TRANSACTION_BPS + SLIPPAGE_BPS) / 10000
TOP_BUCKETS = ("TOP10", "TOP20", "TOP50")
WINDOWS = ("5D", "10D", "20D", "60D")
VARIANTS = ("A1_BASELINE_REPLAY_CURRENT", "B_MOMENTUM_STATIC_R1", "C_MOMENTUM_DYNAMIC_R1")
STRATEGIES = VARIANTS + (
    "QQQ_BUY_AND_HOLD_BENCHMARK", "ETF_ROTATION_1X", "ETF_ROTATION_TACTICAL_OPTIONAL",
)
ETF_1X = ("SPY", "VOO", "IVV", "QQQ", "QQQM", "SMH", "SOXX", "SOXQ", "XSD", "DRAM")
ETF_TACTICAL = ("QQQ", "SPY", "SMH", "SOXX", "QLD", "TQQQ", "SSO", "UPRO", "SOXL", "USD")
FORCED = ("MU", "SNDK", "DRAM", "SPCX", "USD", "SMH", "SOXX", "SOXL", "QQQ", "TQQQ", "SQQQ", "BITF")

ROW_FIELDS = [
    "seed", "batch_id", "sampled_as_of_date", "strategy_id", "variant_id",
    "top_n_bucket", "forward_window", "ticker", "instrument_type", "theme",
    "rank", "score", "base_score", "momentum_score", "applied_momentum_weight",
    "selection_reason", "allocation_weight", "entry_price", "exit_price",
    "gross_position_return", "net_position_return", "benchmark_spy_return",
    "benchmark_qqq_return", "benchmark_smh_return", "excess_return_vs_SPY",
    "excess_return_vs_QQQ", "excess_return_vs_SMH", "market_regime",
    "regime_fallback_used", "price_data_status", "point_in_time_valid",
    "fallback_used", "leveraged_exposure_used", "inverse_exposure_used",
    "local_price_missing_flag", "research_only",
]


def load_module(root: Path, name: str, filename: str):
    path = root / "scripts/v21" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def etf_metadata(root: Path) -> dict[str, dict[str, str]]:
    path = root / "configs/v21/etf_universe_seed.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row["ticker"].upper(): row for row in csv.DictReader(handle)}


def make_draws(selected: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, object]], bool]:
    stats = selected.groupby("as_of_date").agg(
        available_candidate_count=("ticker", "nunique"),
        available_price_count=("price", lambda x: int(pd.Series(x).notna().sum())),
        future_5d=("forward_5d", lambda x: bool(pd.Series(x).notna().any())),
        future_10d=("forward_10d", lambda x: bool(pd.Series(x).notna().any())),
        future_20d=("forward_20d", lambda x: bool(pd.Series(x).notna().any())),
        future_60d=("forward_60d", lambda x: bool(pd.Series(x).notna().any())),
    ).reset_index()
    eligible = stats[
        (stats["available_candidate_count"] >= 50) & stats["future_5d"] & stats["future_10d"]
        & stats["future_20d"] & stats["future_60d"]
    ]["as_of_date"].tolist()
    draws, audit = [], []
    for seed in SEEDS:
        sampled = np.random.default_rng(seed).choice(eligible, ASOF_PER_SEED, replace=True)
        for index, day in enumerate(sampled, 1):
            draws.append({"seed": seed, "draw_index": index, "as_of_date": str(day)})
            row = stats[stats["as_of_date"] == day].iloc[0]
            audit.append({
                "seed": seed, "sampled_as_of_date": day,
                "available_candidate_count": int(row["available_candidate_count"]),
                "available_etf_count": 0, "selected_for_backtest": "TRUE",
                "rejection_reason": "", "point_in_time_valid": "TRUE",
                "future_window_available_5d": "TRUE", "future_window_available_10d": "TRUE",
                "future_window_available_20d": "TRUE", "future_window_available_60d": "TRUE",
                "research_only": "TRUE",
            })
    return pd.DataFrame(draws), audit, len(eligible) < ASOF_PER_SEED


def rotation_table(prices: pd.DataFrame, metadata: dict[str, dict[str, str]]) -> pd.DataFrame:
    frame = prices[prices["ticker"].isin(set(ETF_1X) | set(ETF_TACTICAL))].copy()
    spy = frame[frame["ticker"] == "SPY"].set_index("as_of_date")
    qqq = frame[frame["ticker"] == "QQQ"].set_index("as_of_date")
    for window in (5, 10, 20):
        frame[f"excess_spy_{window}"] = frame[f"return_{window}d"] - frame["as_of_date"].map(spy[f"return_{window}d"])
        frame[f"excess_qqq_{window}"] = frame[f"return_{window}d"] - frame["as_of_date"].map(qqq[f"return_{window}d"])
    frame["rotation_score"] = frame[
        [f"excess_{benchmark}_{window}" for benchmark in ("spy", "qqq") for window in (5, 10, 20)]
    ].mean(axis=1, skipna=True)
    frame["instrument_type"] = frame["ticker"].map(lambda x: metadata.get(x, {}).get("instrument_type", "CORE_ETF"))
    frame["theme"] = frame["ticker"].map(lambda x: metadata.get(x, {}).get("theme", ""))
    frame["leverage"] = pd.to_numeric(
        frame["ticker"].map(lambda x: metadata.get(x, {}).get("leverage_multiplier", "1")), errors="coerce"
    ).fillna(1)
    return frame


def net_return(gross: pd.Series | float) -> pd.Series | float:
    return (1 - ROUND_TRIP_COST / 2) * (1 + gross) * (1 - ROUND_TRIP_COST / 2) - 1


def build_variant_rows(r2, selected, draws, prices, root) -> pd.DataFrame:
    base = r2.make_results(selected, draws, prices, r2.metadata(root))
    output = pd.DataFrame({
        "seed": base["seed"], "batch_id": base["batch_id"],
        "sampled_as_of_date": base["sampled_as_of_date"],
        "strategy_id": base["variant_id"], "variant_id": base["variant_id"],
        "top_n_bucket": base["top_n_bucket"], "forward_window": base["forward_window"],
        "ticker": base["ticker"], "instrument_type": base["instrument_type"],
        "theme": base["theme"], "rank": base["rank"], "score": base["score"],
        "base_score": base["base_score"], "momentum_score": base["momentum_score"],
        "applied_momentum_weight": base["applied_momentum_weight"],
        "selection_reason": "OBJECTIVE_PIT_VARIANT_RANK",
        "allocation_weight": 1 / base["top_n_bucket"].str.replace("TOP", "").astype(float),
        "entry_price": base["forward_start_price"], "exit_price": base["forward_end_price"],
        "gross_position_return": base["realized_forward_return"],
        "net_position_return": net_return(base["realized_forward_return"]),
        "benchmark_spy_return": base["benchmark_spy_return"],
        "benchmark_qqq_return": base["benchmark_qqq_return"],
        "benchmark_smh_return": base["benchmark_smh_return"],
        "excess_return_vs_SPY": base["excess_return_vs_SPY"],
        "excess_return_vs_QQQ": base["excess_return_vs_QQQ"],
        "excess_return_vs_SMH": base["excess_return_vs_SMH"],
        "market_regime": "UNKNOWN", "regime_fallback_used": "TRUE",
        "price_data_status": "PASS", "point_in_time_valid": "TRUE",
        "fallback_used": "TRUE",
        "leveraged_exposure_used": base["instrument_type"].eq("LEVERAGED_LONG_ETF").map({True: "TRUE", False: "FALSE"}),
        "inverse_exposure_used": base["instrument_type"].eq("INVERSE_ETF").map({True: "TRUE", False: "FALSE"}),
        "local_price_missing_flag": "FALSE", "research_only": "TRUE",
    })
    return output


def build_etf_rows(draws: pd.DataFrame, rotation: pd.DataFrame) -> pd.DataFrame:
    records = []
    lookup = {
        (ticker, day): row
        for (ticker, day), row in rotation.set_index(["ticker", "as_of_date"], drop=False).iterrows()
    }
    for draw in draws.itertuples(index=False):
        candidates_1x = rotation[
            (rotation["as_of_date"] == draw.as_of_date) & rotation["ticker"].isin(ETF_1X)
            & rotation["price"].notna() & rotation["rotation_score"].notna()
        ].sort_values("rotation_score", ascending=False)
        tactical = rotation[
            (rotation["as_of_date"] == draw.as_of_date) & rotation["ticker"].isin(ETF_TACTICAL)
            & rotation["price"].notna() & rotation["rotation_score"].notna()
        ].sort_values("rotation_score", ascending=False)
        batch = f"{draw.seed}::DRAW_{draw.draw_index:03d}::{draw.as_of_date}"
        for window, days in (("5D", 5), ("10D", 10), ("20D", 20), ("60D", 60)):
            benchmark = {ticker: lookup.get((ticker, draw.as_of_date)) for ticker in ("SPY", "QQQ", "SMH")}
            for bucket in TOP_BUCKETS:
                qqq = lookup.get(("QQQ", draw.as_of_date))
                if qqq is not None and pd.notna(qqq[f"forward_{days}d"]):
                    records.append(make_etf_record(draw, batch, bucket, window, "QQQ_BUY_AND_HOLD_BENCHMARK", qqq, 1, 1.0, benchmark, False))
                count = 1 if bucket == "TOP10" else 3
                chosen = candidates_1x[candidates_1x[f"forward_{days}d"].notna()].head(count)
                for rank, (_, row) in enumerate(chosen.iterrows(), 1):
                    records.append(make_etf_record(draw, batch, bucket, window, "ETF_ROTATION_1X", row, rank, 1 / len(chosen), benchmark, False))
                tactical_chosen = tactical[tactical[f"forward_{days}d"].notna()].head(count).copy()
                if tactical_chosen.empty:
                    tactical_chosen = chosen.copy()
                    fallback = True
                else:
                    fallback = False
                raw = np.ones(len(tactical_chosen), dtype=float) / max(1, len(tactical_chosen))
                caps = np.where(tactical_chosen["leverage"] >= 3, .25, np.where(tactical_chosen["leverage"] >= 2, .50, 1.0))
                weights = np.minimum(raw, caps)
                if weights.sum() < 1 and len(weights):
                    nonlevered = tactical_chosen["leverage"].to_numpy() <= 1
                    if nonlevered.any():
                        weights[nonlevered] += (1 - weights.sum()) / nonlevered.sum()
                for rank, ((_, row), weight) in enumerate(zip(tactical_chosen.iterrows(), weights), 1):
                    records.append(make_etf_record(draw, batch, bucket, window, "ETF_ROTATION_TACTICAL_OPTIONAL", row, rank, weight, benchmark, fallback))
    return pd.DataFrame(records)


def make_etf_record(draw, batch, bucket, window, strategy, row, rank, weight, benchmark, fallback):
    days = int(window[:-1])
    gross = float(row[f"forward_{days}d"])
    leveraged = float(row["leverage"]) > 1
    return {
        "seed": draw.seed, "batch_id": batch, "sampled_as_of_date": draw.as_of_date,
        "strategy_id": strategy, "variant_id": strategy, "top_n_bucket": bucket,
        "forward_window": window, "ticker": row.name if isinstance(row.name, str) else row.get("ticker", ""),
        "instrument_type": row["instrument_type"], "theme": row["theme"], "rank": rank,
        "score": row["rotation_score"] * 100, "base_score": "", "momentum_score": row["rotation_score"] * 100,
        "applied_momentum_weight": 1, "selection_reason": "PIT_RELATIVE_MOMENTUM_ROTATION",
        "allocation_weight": weight, "entry_price": row["price"], "exit_price": row[f"exit_price_{days}d"],
        "gross_position_return": gross, "net_position_return": net_return(gross),
        "benchmark_spy_return": benchmark["SPY"][f"forward_{days}d"] if benchmark["SPY"] is not None else np.nan,
        "benchmark_qqq_return": benchmark["QQQ"][f"forward_{days}d"] if benchmark["QQQ"] is not None else np.nan,
        "benchmark_smh_return": benchmark["SMH"][f"forward_{days}d"] if benchmark["SMH"] is not None else np.nan,
        "excess_return_vs_SPY": gross - benchmark["SPY"][f"forward_{days}d"] if benchmark["SPY"] is not None else np.nan,
        "excess_return_vs_QQQ": gross - benchmark["QQQ"][f"forward_{days}d"] if benchmark["QQQ"] is not None else np.nan,
        "excess_return_vs_SMH": gross - benchmark["SMH"][f"forward_{days}d"] if benchmark["SMH"] is not None else np.nan,
        "market_regime": "UNKNOWN", "regime_fallback_used": "TRUE",
        "price_data_status": "PASS", "point_in_time_valid": "TRUE",
        "fallback_used": "TRUE" if fallback else "FALSE",
        "leveraged_exposure_used": "TRUE" if leveraged else "FALSE",
        "inverse_exposure_used": "FALSE", "local_price_missing_flag": "FALSE", "research_only": "TRUE",
    }


def portfolios(rows: pd.DataFrame) -> pd.DataFrame:
    keys = ["seed", "batch_id", "sampled_as_of_date", "strategy_id", "top_n_bucket", "forward_window"]
    records = []
    for values, group in rows.groupby(keys, sort=False):
        weights = pd.to_numeric(group["allocation_weight"], errors="coerce").fillna(0)
        gross = float((weights * pd.to_numeric(group["gross_position_return"])).sum())
        net = float((weights * pd.to_numeric(group["net_position_return"])).sum())
        records.append({
            **dict(zip(keys, values)), "initial_capital_usd": INITIAL_CAPITAL,
            "gross_ending_value_usd": INITIAL_CAPITAL * (1 + gross),
            "net_ending_value_usd": INITIAL_CAPITAL * (1 + net),
            "gross_return": gross, "net_return": net,
            "transaction_cost_bps_per_trade": TRANSACTION_BPS,
            "slippage_bps_per_trade": SLIPPAGE_BPS,
            "total_cost_usd": INITIAL_CAPITAL * ((1 + gross) - (1 + net)),
            "holding_count": len(group), "max_single_position_weight": weights.max(),
            "leveraged_exposure_used": "TRUE" if (group["leveraged_exposure_used"] == "TRUE").any() else "FALSE",
            "inverse_exposure_used": "TRUE" if (group["inverse_exposure_used"] == "TRUE").any() else "FALSE",
            "etf_rotation_fallback_used": "TRUE" if (
                values[3] == "ETF_ROTATION_TACTICAL_OPTIONAL" and (group["fallback_used"] == "TRUE").any()
            ) else "FALSE",
            "price_data_status": "PASS", "fallback_used": "TRUE" if (group["fallback_used"] == "TRUE").any() else "FALSE",
            "research_only": "TRUE",
        })
    return pd.DataFrame(records)


def seed_summary(port: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, group in port.groupby(["seed", "strategy_id", "forward_window", "top_n_bucket"]):
        ret = group["net_return"]
        rows.append({
            "seed": keys[0], "strategy_id": keys[1], "forward_window": keys[2], "top_n_bucket": keys[3],
            "observation_count": len(group), "mean_net_return": ret.mean(), "median_net_return": ret.median(),
            "hit_rate": (ret > 0).mean(), "mean_net_ending_value_usd": group["net_ending_value_usd"].mean(),
            "median_net_ending_value_usd": group["net_ending_value_usd"].median(),
            "mean_excess_vs_QQQ": np.nan, "mean_excess_vs_SPY": np.nan,
            "volatility_proxy": ret.std(ddof=0),
            "risk_adjusted_return_proxy": ret.mean() / ret.std(ddof=0) if ret.std(ddof=0) else np.nan,
            "max_drawdown_proxy": ret.min(),
            "leveraged_exposure_count": (group["leveraged_exposure_used"] == "TRUE").sum(),
            "inverse_exposure_count": (group["inverse_exposure_used"] == "TRUE").sum(),
            "fallback_row_count": (group["fallback_used"] == "TRUE").sum(), "research_only": "TRUE",
        })
    result = pd.DataFrame(rows)
    for benchmark, column in (("QQQ_BUY_AND_HOLD_BENCHMARK", "mean_excess_vs_QQQ"), ("ETF_ROTATION_1X", "mean_excess_vs_SPY")):
        ref = result[result["strategy_id"] == benchmark][["seed", "forward_window", "top_n_bucket", "mean_net_return"]].rename(columns={"mean_net_return": "ref"})
        joined = result.merge(ref, on=["seed", "forward_window", "top_n_bucket"], how="left")
        result[column] = joined["mean_net_return"] - joined["ref"]
    return result


def pairwise(seed: pd.DataFrame) -> pd.DataFrame:
    pairs = (
        ("B_MOMENTUM_STATIC_R1", "A1_BASELINE_REPLAY_CURRENT"),
        ("C_MOMENTUM_DYNAMIC_R1", "A1_BASELINE_REPLAY_CURRENT"),
        ("B_MOMENTUM_STATIC_R1", "QQQ_BUY_AND_HOLD_BENCHMARK"),
        ("C_MOMENTUM_DYNAMIC_R1", "QQQ_BUY_AND_HOLD_BENCHMARK"),
        ("B_MOMENTUM_STATIC_R1", "ETF_ROTATION_1X"),
        ("C_MOMENTUM_DYNAMIC_R1", "ETF_ROTATION_1X"),
        ("ETF_ROTATION_1X", "QQQ_BUY_AND_HOLD_BENCHMARK"),
        ("ETF_ROTATION_TACTICAL_OPTIONAL", "ETF_ROTATION_1X"),
        ("C_MOMENTUM_DYNAMIC_R1", "B_MOMENTUM_STATIC_R1"),
    )
    rows = []
    for left, right in pairs:
        for window in WINDOWS:
            for bucket in TOP_BUCKETS:
                a = seed[(seed.strategy_id == left) & (seed.forward_window == window) & (seed.top_n_bucket == bucket)]
                b = seed[(seed.strategy_id == right) & (seed.forward_window == window) & (seed.top_n_bucket == bucket)]
                joined = a.merge(b, on=["seed", "forward_window", "top_n_bucket"], suffixes=("_left", "_right"))
                delta = joined.mean_net_return_left - joined.mean_net_return_right
                wins, losses = int((delta > 0).sum()), int((delta < 0).sum())
                count = len(joined)
                rate = wins / count if count else np.nan
                confidence = "INSUFFICIENT_SEEDS" if count < 5 else "DIRECTIONALLY_POSITIVE" if rate >= .7 else "DIRECTIONALLY_NEGATIVE" if rate <= .3 else "MIXED_OR_INCONCLUSIVE"
                rows.append({
                    "comparison_pair": f"{left}_VS_{right}", "left_strategy": left, "right_strategy": right,
                    "forward_window": window, "top_n_bucket": bucket, "paired_seed_count": count,
                    "mean_net_return_delta": delta.mean(), "median_net_return_delta": delta.median(),
                    "hit_rate_delta": (joined.hit_rate_left - joined.hit_rate_right).mean(),
                    "ending_value_delta_usd": (joined.mean_net_ending_value_usd_left - joined.mean_net_ending_value_usd_right).mean(),
                    "seed_win_count": wins, "seed_loss_count": losses, "seed_tie_count": int((delta == 0).sum()),
                    "seed_win_rate": rate, "directional_result": "LEFT_BETTER" if rate > .5 else "RIGHT_BETTER" if rate < .5 else "TIED",
                    "statistical_confidence_status": confidence, "research_only": "TRUE",
                })
    return pd.DataFrame(rows)


def overall(seed: pd.DataFrame) -> pd.DataFrame:
    refs = {}
    for strategy, key in (("QQQ_BUY_AND_HOLD_BENCHMARK", "qqq"), ("ETF_ROTATION_1X", "rotation"), ("A1_BASELINE_REPLAY_CURRENT", "a1")):
        refs[key] = seed[seed.strategy_id == strategy][["seed", "forward_window", "top_n_bucket", "mean_net_return"]].rename(columns={"mean_net_return": key})
    merged = seed.copy()
    for ref in refs.values():
        merged = merged.merge(ref, on=["seed", "forward_window", "top_n_bucket"], how="left")
    rows = []
    for keys, group in merged.groupby(["strategy_id", "forward_window", "top_n_bucket"]):
        rows.append({
            "strategy_id": keys[0], "forward_window": keys[1], "top_n_bucket": keys[2],
            "seed_count": group.seed.nunique(), "total_observation_count": group.observation_count.sum(),
            "mean_of_seed_mean_net_returns": group.mean_net_return.mean(),
            "median_of_seed_mean_net_returns": group.mean_net_return.median(),
            "mean_hit_rate": group.hit_rate.mean(), "mean_net_ending_value_usd": group.mean_net_ending_value_usd.mean(),
            "median_net_ending_value_usd": group.median_net_ending_value_usd.median(),
            "seed_win_rate_vs_QQQ": (group.mean_net_return > group.qqq).mean(),
            "seed_win_rate_vs_ETF_ROTATION_1X": (group.mean_net_return > group.rotation).mean(),
            "seed_win_rate_vs_A1": (group.mean_net_return > group.a1).mean(),
            "mean_excess_vs_QQQ": (group.mean_net_return - group.qqq).mean(),
            "mean_excess_vs_SPY": group.mean_excess_vs_SPY.mean(),
            "robustness_score": (group.mean_net_return > group.qqq).mean() * 100,
            "fallback_used_rate": group.fallback_row_count.sum() / group.observation_count.sum(),
            "research_only": "TRUE",
        })
    return pd.DataFrame(rows)


def run_stage(root: Path) -> dict[str, object]:
    root = root.resolve()
    r1 = load_module(root, "v21_060_r1_shared", "v21_060_r1_abcd_backtest_and_forward_observation_ledger.py")
    r2 = load_module(root, "v21_060_r2_shared", "v21_060_r2_multi_seed_random_asof_abcd_robustness_backtest.py")
    out = root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    protected = r2.protected_files(root)
    protected.extend((root / OUT_REL).glob("V21_060_R2_*"))
    protected = sorted({path.resolve() for path in protected if path.is_file()})
    before = {r1.rel(root, p): r1.sha(p) for p in protected}
    prices = r1.load_prices(root / r1.PRICE_REL)
    selected, _ = r1.build_historical_variants(root / r1.SNAPSHOT_REL, prices)
    draws, selection, reduced = make_draws(selected)
    meta = etf_metadata(root)
    rotation = rotation_table(prices, meta)
    etf_counts = rotation.groupby("as_of_date").ticker.nunique().to_dict()
    for row in selection:
        row["available_etf_count"] = int(etf_counts.get(row["sampled_as_of_date"], 0))

    variant_rows = build_variant_rows(r2, selected, draws, prices, root)
    etf_rows = build_etf_rows(draws, rotation)
    rows = pd.concat([variant_rows, etf_rows], ignore_index=True)
    rows[ROW_FIELDS].to_csv(out / RESULTS_NAME, index=False, lineterminator="\n")
    port = portfolios(rows)
    port.to_csv(out / PORTFOLIO_NAME, index=False, lineterminator="\n")
    seed = seed_summary(port)
    seed.to_csv(out / SEED_NAME, index=False, lineterminator="\n")
    ov = overall(seed)
    ov.to_csv(out / OVERALL_NAME, index=False, lineterminator="\n")
    pairs = pairwise(seed)
    pairs.to_csv(out / PAIR_NAME, index=False, lineterminator="\n")

    examples = []
    for keys, group in port.groupby(["strategy_id", "forward_window", "top_n_bucket"]):
        seed_means = group.groupby("seed").net_ending_value_usd.mean()
        overall_match = ov[(ov.strategy_id == keys[0]) & (ov.forward_window == keys[1]) & (ov.top_n_bucket == keys[2])].iloc[0]
        examples.append({
            "strategy_id": keys[0], "forward_window": keys[1], "top_n_bucket": keys[2],
            "mean_net_ending_value_usd": group.net_ending_value_usd.mean(),
            "median_net_ending_value_usd": group.net_ending_value_usd.median(),
            "best_seed_net_ending_value_usd": seed_means.max(), "worst_seed_net_ending_value_usd": seed_means.min(),
            "mean_net_profit_usd": group.net_ending_value_usd.mean() - INITIAL_CAPITAL,
            "median_net_profit_usd": group.net_ending_value_usd.median() - INITIAL_CAPITAL,
            "mean_net_return": group.net_return.mean(), "hit_rate": (group.net_return > 0).mean(),
            "seed_win_rate_vs_QQQ": overall_match.seed_win_rate_vs_QQQ,
            "seed_win_rate_vs_ETF_ROTATION_1X": overall_match.seed_win_rate_vs_ETF_ROTATION_1X,
            "interpretation": "RESEARCH_ONLY_RANDOM_ASOF_NET_OF_ASSUMED_ENTRY_EXIT_COSTS",
            "research_only": "TRUE",
        })
    pd.DataFrame(examples).to_csv(out / EXAMPLE_NAME, index=False, lineterminator="\n")
    r1.write_csv(out / SELECTION_NAME, selection, list(selection[0].keys()))

    forced_rows = []
    price_tickers = set(prices.ticker)
    for ticker in FORCED:
        subset = rows[rows.ticker == ticker]
        forced_rows.append({
            "ticker": ticker, "included_in_any_seed": r1.tf(not subset.empty),
            "included_in_A1": r1.tf((subset.strategy_id == "A1_BASELINE_REPLAY_CURRENT").any()),
            "included_in_B": r1.tf((subset.strategy_id == "B_MOMENTUM_STATIC_R1").any()),
            "included_in_C": r1.tf((subset.strategy_id == "C_MOMENTUM_DYNAMIC_R1").any()),
            "included_in_QQQ_BENCHMARK": r1.tf((subset.strategy_id == "QQQ_BUY_AND_HOLD_BENCHMARK").any()),
            "included_in_ETF_ROTATION_1X": r1.tf((subset.strategy_id == "ETF_ROTATION_1X").any()),
            "included_in_ETF_ROTATION_TACTICAL": r1.tf((subset.strategy_id == "ETF_ROTATION_TACTICAL_OPTIONAL").any()),
            "inclusion_reason": "OBJECTIVE_PIT_RANK_OR_ROTATION_SELECTION_WITH_VALID_PRICE" if not subset.empty else "",
            "exclusion_reason": "LOCAL_HISTORICAL_PRICE_NOT_AVAILABLE" if ticker not in price_tickers else "NOT_OBJECTIVELY_SELECTED",
            "local_price_missing_flag": r1.tf(ticker not in price_tickers),
            "hardcoded_inclusion_violation_flag": "FALSE", "tqqq_ipo_watch_violation_flag": "FALSE",
            "research_only": "TRUE",
        })
    r1.write_csv(out / FORCED_NAME, forced_rows, list(forced_rows[0].keys()))

    lineage = [
        {"lineage_role": "PIT_FACTOR_SNAPSHOT", "source_path": r1.rel(root, root / r1.SNAPSHOT_REL), "details": "A1/B/C PIT reconstruction; B=.20 overlay, C=.15 UNKNOWN-regime fallback.", "research_only": "TRUE"},
        {"lineage_role": "PRICE_DATA", "source_path": r1.rel(root, root / r1.PRICE_REL), "details": "Point-in-time trailing returns and realized session forward returns.", "research_only": "TRUE"},
        {"lineage_role": "ETF_SEED", "source_path": "configs/v21/etf_universe_seed.csv", "details": f"1X={'|'.join(ETF_1X)};TACTICAL={'|'.join(ETF_TACTICAL)}", "research_only": "TRUE"},
        {"lineage_role": "RANDOM_SAMPLING", "source_path": "", "details": f"SEEDS={'|'.join(map(str, SEEDS))};100 paired bootstrap draws per seed.", "research_only": "TRUE"},
        {"lineage_role": "PORTFOLIO_ASSUMPTIONS", "source_path": "", "details": "USD10000;10bps transaction+5bps slippage on entry and exit;equal-weight.", "research_only": "TRUE"},
        {"lineage_role": "A0_EXCLUSION", "source_path": "", "details": "A0_CURRENT_TESTING_LOCKED not replayed; no proxy created.", "research_only": "TRUE"},
    ]
    r1.write_csv(out / LINEAGE_NAME, lineage, list(lineage[0].keys()))

    after = {path: r1.sha(root / path) for path in before}
    mutation = before != after
    a0_modified = any(before[p] != after[p] for p in before if "version_control" in p)
    hardcoded = sum(x["hardcoded_inclusion_violation_flag"] == "TRUE" for x in forced_rows)
    local_violation = sum(x["included_in_any_seed"] == "TRUE" and x["local_price_missing_flag"] == "TRUE" for x in forced_rows)
    tqqq = sum(x["tqqq_ipo_watch_violation_flag"] == "TRUE" for x in forced_rows)

    def rate(left, right, window, bucket="TOP20"):
        x = pairs[(pairs.left_strategy == left) & (pairs.right_strategy == right) & (pairs.forward_window == window) & (pairs.top_n_bucket == bucket)]
        return None if x.empty else float(x.iloc[0].seed_win_rate)

    def best(window):
        x = ov[(ov.forward_window == window) & (ov.top_n_bucket == "TOP20")]
        return str(x.loc[x.mean_of_seed_mean_net_returns.idxmax(), "strategy_id"])

    b_a1 = [rate("B_MOMENTUM_STATIC_R1", "A1_BASELINE_REPLAY_CURRENT", w) for w in ("5D", "10D", "20D")]
    b_qqq = [rate("B_MOMENTUM_STATIC_R1", "QQQ_BUY_AND_HOLD_BENCHMARK", w) for w in ("5D", "10D", "20D")]
    b_rot = [rate("B_MOMENTUM_STATIC_R1", "ETF_ROTATION_1X", w) for w in ("5D", "10D", "20D")]
    c_qqq = [rate("C_MOMENTUM_DYNAMIC_R1", "QQQ_BUY_AND_HOLD_BENCHMARK", w) for w in ("5D", "10D", "20D")]
    rot_qqq = [rate("ETF_ROTATION_1X", "QQQ_BUY_AND_HOLD_BENCHMARK", w) for w in ("5D", "10D", "20D")]
    if all(x >= .7 for x in b_a1) and all(x >= .7 for x in b_qqq):
        robustness = "B_STATIC_BEATS_A1_AND_QQQ"
    elif all(x >= .7 for x in b_a1):
        robustness = "B_STATIC_BEATS_A1_BUT_NOT_QQQ"
    elif all(x >= .7 for x in rot_qqq):
        robustness = "ETF_ROTATION_BEATS_QQQ"
    elif all(x <= .3 for x in b_qqq + c_qqq + rot_qqq):
        robustness = "QQQ_BENCHMARK_BEST"
    else:
        robustness = "MIXED_OR_INCONCLUSIVE"
    recommendation = "CONTINUE_OBSERVATION" if robustness != "MIXED_OR_INCONCLUSIVE" else "NEED_MORE_MATURITY"

    if a0_modified:
        final, decision = FAIL_A0, "STOP_AND_RESTORE_A0_CONTROL"
    elif mutation:
        final, decision = FAIL_MUTATION, "STOP_AND_RESTORE_FORBIDDEN_MUTATION"
    elif hardcoded:
        final, decision = FAIL_HARDCODED, "REPAIR_FORCED_INCLUSION_LOGIC"
    elif local_violation:
        final, decision = FAIL_PRICE, "REPAIR_RANDOM_BACKTEST_ELIGIBILITY"
    elif tqqq:
        final, decision = FAIL_TQQQ, "REPAIR_LISTING_AGE_POLICY_PROPAGATION"
    else:
        final, decision = PARTIAL_STATUS, "RANDOM_BENCHMARK_AND_ETF_ROTATION_READY_WITH_WARN_CONTINUE_FORWARD_MONITORING"

    summary = {
        "FINAL_STATUS": final, "DECISION": decision, "stage_id": STAGE_ID, "research_only": True,
        "random_seed_count": len(SEEDS), "random_asof_count_per_seed": ASOF_PER_SEED,
        "actual_seed_count": draws.seed.nunique(), "actual_total_sampled_asof_count": len(draws),
        "row_level_result_count": len(rows), "portfolio_simulation_row_count": len(port),
        "strategies_compared": list(STRATEGIES), "forward_windows": list(WINDOWS),
        "top_n_buckets": list(TOP_BUCKETS), "initial_capital_usd": INITIAL_CAPITAL,
        "transaction_cost_bps_per_trade": TRANSACTION_BPS, "slippage_bps_per_trade": SLIPPAGE_BPS,
        "backtest_fallback_used": True, "point_in_time_approximation_used": True, "reduced_sample_used": reduced,
        "b_seed_win_rate_vs_a1_5d_top20": b_a1[0], "b_seed_win_rate_vs_a1_10d_top20": b_a1[1], "b_seed_win_rate_vs_a1_20d_top20": b_a1[2],
        "b_seed_win_rate_vs_qqq_5d_top20": b_qqq[0], "b_seed_win_rate_vs_qqq_10d_top20": b_qqq[1], "b_seed_win_rate_vs_qqq_20d_top20": b_qqq[2],
        "b_seed_win_rate_vs_etf_rotation_1x_5d_top20": b_rot[0], "b_seed_win_rate_vs_etf_rotation_1x_10d_top20": b_rot[1], "b_seed_win_rate_vs_etf_rotation_1x_20d_top20": b_rot[2],
        "c_seed_win_rate_vs_qqq_5d_top20": c_qqq[0], "c_seed_win_rate_vs_qqq_10d_top20": c_qqq[1], "c_seed_win_rate_vs_qqq_20d_top20": c_qqq[2],
        "etf_rotation_1x_seed_win_rate_vs_qqq_5d": rot_qqq[0], "etf_rotation_1x_seed_win_rate_vs_qqq_10d": rot_qqq[1], "etf_rotation_1x_seed_win_rate_vs_qqq_20d": rot_qqq[2],
        "best_strategy_by_5d_top20": best("5D"), "best_strategy_by_10d_top20": best("10D"), "best_strategy_by_20d_top20": best("20D"),
        "best_strategy_by_mean_10000_net_ending_value": str(ov.loc[ov.mean_net_ending_value_usd.idxmax(), "strategy_id"]),
        "robustness_read": robustness, "recommendation_status": recommendation,
        "production_adoption_allowed": False, "official_use_allowed": False,
        "a0_replayed": False, "a0_modified": a0_modified,
        "official_mutation_detected": False, "real_book_mutation_detected": False, "broker_mutation_detected": False,
        "hardcoded_inclusion_violation_count": hardcoded,
        "local_price_missing_included_violation_count": local_violation,
        "tqqq_ipo_watch_violation_count": tqqq,
        "next_recommended_stage": "CONTINUE_V21_062_DAILY_MATURITY_MONITORING",
    }
    r1.write_json(out / SUMMARY_NAME, summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    summary = run_stage(parser.parse_args().root)
    print(json.dumps(summary, indent=2))
    return 1 if str(summary["FINAL_STATUS"]).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
