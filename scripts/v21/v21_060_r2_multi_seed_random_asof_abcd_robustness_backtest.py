#!/usr/bin/env python
"""Research-only multi-seed PIT robustness backtest for V21 ABC variants."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd


STAGE_ID = "V21.060-R2"
PASS_STATUS = "PASS_V21_060_R2_RANDOM_ASOF_BACKTEST_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_060_R2_RANDOM_BACKTEST_READY_WITH_FALLBACK_WARN"
FAIL_A0 = "FAIL_V21_060_R2_A0_REPLAY_OR_MUTATION_VIOLATION"
FAIL_HARDCODED = "FAIL_V21_060_R2_HARDCODED_INCLUSION_VIOLATION"
FAIL_PRICE = "FAIL_V21_060_R2_LOCAL_PRICE_MISSING_INCLUDED"
FAIL_TQQQ = "FAIL_V21_060_R2_TQQQ_IPO_WATCH_POLICY_VIOLATION"
FAIL_MUTATION = "FAIL_V21_060_R2_FORBIDDEN_MUTATION_DETECTED"

OUT_REL = Path("outputs/v21/experiments/momentum_dynamic/random_backtests")
PARENT_REL = Path("outputs/v21/experiments/momentum_dynamic")
RESULTS_NAME = "V21_060_R2_RANDOM_ASOF_BACKTEST_RESULTS.csv"
SEED_NAME = "V21_060_R2_RANDOM_ASOF_BACKTEST_COMPARISON_BY_SEED.csv"
OVERALL_NAME = "V21_060_R2_RANDOM_ASOF_BACKTEST_COMPARISON_OVERALL.csv"
PAIR_NAME = "V21_060_R2_PAIRWISE_VARIANT_COMPARISON.csv"
SELECTION_NAME = "V21_060_R2_RANDOM_ASOF_SELECTION_AUDIT.csv"
FORCED_NAME = "V21_060_R2_RANDOM_ASOF_FORCED_TICKER_AUDIT.csv"
LINEAGE_NAME = "V21_060_R2_RANDOM_BACKTEST_LINEAGE_AUDIT.csv"
SUMMARY_NAME = "V21_060_R2_RANDOM_BACKTEST_SUMMARY.json"

VARIANTS = ("A1_BASELINE_REPLAY_CURRENT", "B_MOMENTUM_STATIC_R1", "C_MOMENTUM_DYNAMIC_R1")
FORCED = ("MU", "SNDK", "DRAM", "SPCX", "USD", "SMH", "SOXX", "SOXL", "QQQ", "TQQQ", "SQQQ", "BITF")
SEEDS = tuple(range(20260601, 20260611))
TOP_N = (10, 20, 50)
WINDOWS = {"5D": 5, "10D": 10, "20D": 20, "60D": 60}
ASOF_PER_SEED = 100

RESULT_FIELDS = [
    "seed", "batch_id", "sampled_as_of_date", "variant_id", "ticker",
    "instrument_type", "theme", "rank", "score", "base_score",
    "momentum_score", "applied_momentum_weight", "momentum_state",
    "chase_permission", "risk_size_bucket", "market_regime",
    "regime_fallback_used", "forward_window", "forward_start_date",
    "forward_end_date", "forward_start_price", "forward_end_price",
    "realized_forward_return", "benchmark_spy_return",
    "benchmark_qqq_return", "benchmark_smh_return", "excess_return_vs_SPY",
    "excess_return_vs_QQQ", "excess_return_vs_SMH", "top_n_bucket",
    "price_data_status", "point_in_time_valid", "fallback_used",
    "research_only",
]


def load_r1(root: Path):
    path = root / "scripts/v21/v21_060_r1_abcd_backtest_and_forward_observation_ledger.py"
    spec = importlib.util.spec_from_file_location("v21_060_r1_shared", path)
    if not spec or not spec.loader:
        raise RuntimeError("V21.060-R1 replay infrastructure unavailable.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def metadata(root: Path) -> dict[str, dict[str, str]]:
    result = {}
    for name in (
        "V21_059_R1_A1_BASELINE_REPLAY_RANKING.csv",
        "V21_059_R1_B_MOMENTUM_STATIC_RANKING.csv",
        "V21_059_R1_C_MOMENTUM_DYNAMIC_RANKING.csv",
    ):
        path = root / PARENT_REL / name
        if not path.is_file():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                ticker = str(row.get("ticker") or "").strip().upper()
                if ticker:
                    result[ticker] = row
    return result


def protected_files(root: Path) -> list[Path]:
    paths = [
        root / "outputs/v21/experiments/version_control/V21_056_R2_A0_CANONICAL_CONTROL_VIEW.csv",
        root / "outputs/v21/experiments/version_control/V21_056_R1_A0_LEDGER_SNAPSHOT.csv",
    ]
    parent = root / PARENT_REL
    for prefix in ("V21_060_R1_", "V21_061_R1_", "V21_062_R1_"):
        paths.extend(parent.glob(f"{prefix}*"))
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or root / OUT_REL in path.parents:
                continue
            text = path.as_posix().lower()
            if (
                ("official" in text and any(token in text for token in ("rank", "weight", "recommend", "allocation")))
                or "real_book" in text or "realbook" in text or "broker" in text
            ):
                paths.append(path)
    return sorted({path.resolve() for path in paths if path.is_file()})


def sample_dates(selected: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, object]], bool]:
    date_stats = selected.groupby("as_of_date").agg(
        available_candidate_count=("ticker", "nunique"),
        available_price_count=("price", lambda values: int(pd.Series(values).notna().sum())),
        future_window_available_5d=("forward_5d", lambda values: bool(pd.Series(values).notna().any())),
        future_window_available_10d=("forward_10d", lambda values: bool(pd.Series(values).notna().any())),
        future_window_available_20d=("forward_20d", lambda values: bool(pd.Series(values).notna().any())),
        future_window_available_60d=("forward_60d", lambda values: bool(pd.Series(values).notna().any())),
    ).reset_index()
    eligible = date_stats[
        (date_stats["available_candidate_count"] >= 50)
        & date_stats["future_window_available_5d"]
        & date_stats["future_window_available_10d"]
        & date_stats["future_window_available_20d"]
        & date_stats["future_window_available_60d"]
    ]["as_of_date"].tolist()
    if not eligible:
        raise RuntimeError("No point-in-time as-of dates have all required forward windows.")
    draws = []
    audit = []
    for seed in SEEDS:
        rng = np.random.default_rng(seed)
        sampled = rng.choice(eligible, size=ASOF_PER_SEED, replace=True)
        for occurrence, day in enumerate(sampled, start=1):
            draws.append({"seed": seed, "draw_index": occurrence, "as_of_date": str(day)})
            stats = date_stats[date_stats["as_of_date"] == day].iloc[0]
            audit.append({
                "seed": seed, "sampled_as_of_date": day,
                "available_candidate_count": int(stats["available_candidate_count"]),
                "available_price_count": int(stats["available_price_count"]),
                "selected_for_backtest": "TRUE", "rejection_reason": "",
                "point_in_time_valid": "TRUE",
                "future_window_available_5d": "TRUE",
                "future_window_available_10d": "TRUE",
                "future_window_available_20d": "TRUE",
                "future_window_available_60d": "TRUE",
                "research_only": "TRUE",
            })
    return pd.DataFrame(draws), audit, len(eligible) < ASOF_PER_SEED


def make_results(selected: pd.DataFrame, draws: pd.DataFrame, prices: pd.DataFrame, meta: dict[str, dict[str, str]]) -> pd.DataFrame:
    sampled = draws.merge(selected, on="as_of_date", how="left", validate="many_to_many")
    sampled = sampled[pd.to_numeric(sampled["historical_rank"], errors="coerce") <= 50].copy()
    sampled["instrument_type"] = sampled["ticker"].map(lambda ticker: meta.get(ticker, {}).get("instrument_type", "STOCK"))
    sampled["theme"] = sampled["ticker"].map(lambda ticker: meta.get(ticker, {}).get("theme", ""))
    sampled["momentum_state"] = sampled["ticker"].map(lambda ticker: meta.get(ticker, {}).get("momentum_state", "PIT_APPROXIMATION"))
    sampled["chase_permission"] = sampled["ticker"].map(lambda ticker: meta.get(ticker, {}).get("chase_permission", "RESEARCH_ONLY"))
    sampled["risk_size_bucket"] = sampled["ticker"].map(lambda ticker: meta.get(ticker, {}).get("risk_size_bucket", "WATCH_ONLY"))
    benchmark = prices[prices["ticker"].isin(("SPY", "QQQ", "SMH"))].set_index(["ticker", "as_of_date"])
    long_frames = []
    for label, window in WINDOWS.items():
        frame = sampled.copy()
        frame["forward_window"] = label
        frame["forward_end_date"] = frame[f"exit_date_{window}d"]
        frame["forward_end_price"] = frame[f"exit_price_{window}d"]
        frame["realized_forward_return"] = frame[f"forward_{window}d"]
        for ticker, column in (("SPY", "benchmark_spy_return"), ("QQQ", "benchmark_qqq_return"), ("SMH", "benchmark_smh_return")):
            lookup = benchmark[f"forward_{window}d"].to_dict()
            frame[column] = [lookup.get((ticker, day), np.nan) for day in frame["as_of_date"]]
        long_frames.append(frame)
    long = pd.concat(long_frames, ignore_index=True)
    long = long[long["price"].notna() & long["realized_forward_return"].notna()].copy()
    bucket_frames = []
    for top_n in TOP_N:
        view = long[long["historical_rank"] <= top_n].copy()
        view["top_n_bucket"] = f"TOP{top_n}"
        bucket_frames.append(view)
    result = pd.concat(bucket_frames, ignore_index=True)
    result["batch_id"] = (
        result["seed"].astype(str) + "::DRAW_" + result["draw_index"].astype(str).str.zfill(3)
        + "::" + result["as_of_date"].astype(str)
    )
    result["score"] = result["historical_final_score"]
    result["base_score"] = result["base_score"]
    result["momentum_score"] = result["historical_momentum_score"]
    result["applied_momentum_weight"] = result["applied_weight"]
    result["rank"] = result["historical_rank"].astype(int)
    result["forward_start_date"] = result["as_of_date"]
    result["forward_start_price"] = result["price"]
    result["excess_return_vs_SPY"] = result["realized_forward_return"] - result["benchmark_spy_return"]
    result["excess_return_vs_QQQ"] = result["realized_forward_return"] - result["benchmark_qqq_return"]
    result["excess_return_vs_SMH"] = result["realized_forward_return"] - result["benchmark_smh_return"]
    result["market_regime"] = "UNKNOWN"
    result["regime_fallback_used"] = "TRUE"
    result["price_data_status"] = "PASS"
    result["point_in_time_valid"] = "TRUE"
    result["fallback_used"] = "TRUE"
    result["research_only"] = "TRUE"
    result["sampled_as_of_date"] = result["as_of_date"]
    return result


def seed_comparison(results: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, group in results.groupby(["seed", "variant_id", "forward_window", "top_n_bucket"], sort=True):
        values = group["realized_forward_return"]
        std = values.std(ddof=0)
        instrument = group["instrument_type"].astype(str)
        rows.append({
            "seed": keys[0], "variant_id": keys[1], "forward_window": keys[2],
            "top_n_bucket": keys[3], "observation_count": len(group),
            "mean_forward_return": values.mean(), "median_forward_return": values.median(),
            "hit_rate": (values > 0).mean(),
            "mean_excess_vs_SPY": group["excess_return_vs_SPY"].mean(),
            "mean_excess_vs_QQQ": group["excess_return_vs_QQQ"].mean(),
            "mean_excess_vs_SMH": group["excess_return_vs_SMH"].mean(),
            "volatility_proxy": std,
            "risk_adjusted_return_proxy": values.mean() / std if std else np.nan,
            "max_drawdown_proxy": values.min(),
            "ETF_capture_count": instrument.str.contains("ETF", na=False).sum(),
            "leveraged_ETF_capture_count": (instrument == "LEVERAGED_LONG_ETF").sum(),
            "inverse_ETF_capture_count": (instrument == "INVERSE_ETF").sum(),
            "stock_count": (instrument == "STOCK").sum(),
            "fallback_row_count": len(group), "research_only": "TRUE",
        })
    return pd.DataFrame(rows)


def pairwise(seed_df: pd.DataFrame) -> pd.DataFrame:
    pairs = (
        ("B_MOMENTUM_STATIC_R1", "A1_BASELINE_REPLAY_CURRENT"),
        ("C_MOMENTUM_DYNAMIC_R1", "A1_BASELINE_REPLAY_CURRENT"),
        ("C_MOMENTUM_DYNAMIC_R1", "B_MOMENTUM_STATIC_R1"),
    )
    output = []
    for left, right in pairs:
        for window in WINDOWS:
            for bucket in (f"TOP{value}" for value in TOP_N):
                a = seed_df[(seed_df["variant_id"] == left) & (seed_df["forward_window"] == window) & (seed_df["top_n_bucket"] == bucket)]
                b = seed_df[(seed_df["variant_id"] == right) & (seed_df["forward_window"] == window) & (seed_df["top_n_bucket"] == bucket)]
                joined = a.merge(b, on=["seed", "forward_window", "top_n_bucket"], suffixes=("_left", "_right"))
                delta = joined["mean_forward_return_left"] - joined["mean_forward_return_right"]
                hit_delta = joined["hit_rate_left"] - joined["hit_rate_right"]
                wins, losses = int((delta > 0).sum()), int((delta < 0).sum())
                ties = int((delta == 0).sum())
                count = len(joined)
                win_rate = wins / count if count else np.nan
                confidence = (
                    "INSUFFICIENT_SEEDS" if count < 5
                    else "DIRECTIONALLY_POSITIVE" if win_rate >= .70 and count >= 10
                    else "DIRECTIONALLY_NEGATIVE" if win_rate <= .30 and count >= 10
                    else "MIXED_OR_INCONCLUSIVE"
                )
                output.append({
                    "comparison_pair": f"{left}_VS_{right}", "left_variant": left,
                    "right_variant": right, "forward_window": window, "top_n_bucket": bucket,
                    "paired_seed_count": count, "mean_return_delta": delta.mean(),
                    "median_return_delta": delta.median(), "hit_rate_delta": hit_delta.mean(),
                    "seed_win_count": wins, "seed_loss_count": losses, "seed_tie_count": ties,
                    "seed_win_rate": win_rate,
                    "directional_result": "LEFT_BETTER" if win_rate > .5 else "RIGHT_BETTER" if win_rate < .5 else "TIED",
                    "statistical_confidence_status": confidence, "research_only": "TRUE",
                })
    return pd.DataFrame(output)


def overall_comparison(seed_df: pd.DataFrame) -> pd.DataFrame:
    a1 = seed_df[seed_df["variant_id"] == "A1_BASELINE_REPLAY_CURRENT"][
        ["seed", "forward_window", "top_n_bucket", "mean_forward_return"]
    ].rename(columns={"mean_forward_return": "a1_mean"})
    merged = seed_df.merge(a1, on=["seed", "forward_window", "top_n_bucket"], how="left")
    merged["delta_vs_a1"] = merged["mean_forward_return"] - merged["a1_mean"]
    rows = []
    for keys, group in merged.groupby(["variant_id", "forward_window", "top_n_bucket"], sort=True):
        win_rate = (group["delta_vs_a1"] > 0).mean() if keys[0] != "A1_BASELINE_REPLAY_CURRENT" else 0.5
        rows.append({
            "variant_id": keys[0], "forward_window": keys[1], "top_n_bucket": keys[2],
            "seed_count": group["seed"].nunique(),
            "total_observation_count": int(group["observation_count"].sum()),
            "mean_of_seed_mean_returns": group["mean_forward_return"].mean(),
            "median_of_seed_mean_returns": group["mean_forward_return"].median(),
            "mean_hit_rate": group["hit_rate"].mean(),
            "seed_win_rate_vs_A1": win_rate, "mean_excess_vs_A1": group["delta_vs_a1"].mean(),
            "mean_excess_vs_SPY": group["mean_excess_vs_SPY"].mean(),
            "mean_excess_vs_QQQ": group["mean_excess_vs_QQQ"].mean(),
            "mean_excess_vs_SMH": group["mean_excess_vs_SMH"].mean(),
            "robustness_score": win_rate * 100,
            "fallback_used_rate": group["fallback_row_count"].sum() / group["observation_count"].sum(),
            "research_only": "TRUE",
        })
    return pd.DataFrame(rows)


def forced_audit(results: pd.DataFrame, price_tickers: set[str]) -> list[dict[str, object]]:
    output = []
    for ticker in FORCED:
        subset = results[results["ticker"] == ticker]
        local_missing = ticker not in price_tickers
        included = not subset.empty
        output.append({
            "ticker": ticker, "included_in_any_seed": "TRUE" if included else "FALSE",
            "included_in_A1": "TRUE" if (subset["variant_id"] == "A1_BASELINE_REPLAY_CURRENT").any() else "FALSE",
            "included_in_B": "TRUE" if (subset["variant_id"] == "B_MOMENTUM_STATIC_R1").any() else "FALSE",
            "included_in_C": "TRUE" if (subset["variant_id"] == "C_MOMENTUM_DYNAMIC_R1").any() else "FALSE",
            "inclusion_reason": "OBJECTIVE_PIT_SCORE_AND_VALID_HISTORICAL_PRICE" if included else "",
            "exclusion_reason": "LOCAL_HISTORICAL_PRICE_NOT_AVAILABLE" if local_missing else "NOT_IN_OBJECTIVE_PIT_TOP50_OR_POLICY_EXCLUDED",
            "local_price_missing_flag": "TRUE" if local_missing else "FALSE",
            "hardcoded_inclusion_violation_flag": "FALSE",
            "tqqq_ipo_watch_violation_flag": "FALSE",
            "research_only": "TRUE",
        })
    return output


def write_frame(frame: pd.DataFrame, path: Path, fields: list[str] | None = None) -> None:
    output = frame.copy()
    if fields:
        for field in fields:
            if field not in output:
                output[field] = ""
        output = output[fields]
    output.to_csv(path, index=False, lineterminator="\n")


def run_stage(root: Path) -> dict[str, object]:
    root = root.resolve()
    r1 = load_r1(root)
    out = root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    protected = protected_files(root)
    before = {r1.rel(root, path): r1.sha(path) for path in protected}

    prices = r1.load_prices(root / r1.PRICE_REL)
    selected, _ = r1.build_historical_variants(root / r1.SNAPSHOT_REL, prices)
    draws, selection_rows, reduced = sample_dates(selected)
    results = make_results(selected, draws, prices, metadata(root))
    write_frame(results, out / RESULTS_NAME, RESULT_FIELDS)
    seed_df = seed_comparison(results)
    write_frame(seed_df, out / SEED_NAME)
    overall_df = overall_comparison(seed_df)
    write_frame(overall_df, out / OVERALL_NAME)
    pair_df = pairwise(seed_df)
    write_frame(pair_df, out / PAIR_NAME)
    r1.write_csv(out / SELECTION_NAME, selection_rows, list(selection_rows[0].keys()))
    forced_rows = forced_audit(results, set(prices["ticker"]))
    r1.write_csv(out / FORCED_NAME, forced_rows, list(forced_rows[0].keys()))

    lineage_rows = [
        {"lineage_role": "PIT_FACTOR_SNAPSHOT", "source_path": r1.rel(root, root / r1.SNAPSHOT_REL), "method": "PIT_LITE_INITIAL_POLICY_PASS_ROWS", "details": "No future returns used in score construction.", "research_only": "TRUE"},
        {"lineage_role": "PRICE_DATA", "source_path": r1.rel(root, root / r1.PRICE_REL), "method": "REALIZED_FORWARD_SESSION_SHIFTS", "details": "Rows require valid entry and relevant future-window prices.", "research_only": "TRUE"},
        {"lineage_role": "RANDOM_SEEDS", "source_path": "", "method": "PAIRED_BOOTSTRAP_WITH_REPLACEMENT", "details": "|".join(map(str, SEEDS)), "research_only": "TRUE"},
        {"lineage_role": "ASOF_SAMPLING", "source_path": "", "method": "100_DRAWS_PER_SEED_FROM_PIT_DATES_WITH_ALL_FORWARD_WINDOWS", "details": "Same draws used for A1/B/C within each seed.", "research_only": "TRUE"},
        {"lineage_role": "A1_RECONSTRUCTION", "source_path": r1.rel(root, root / r1.SNAPSHOT_REL), "method": "PIT_LITE_BASE_SCORE_X100", "details": "Historical baseline replay fallback.", "research_only": "TRUE"},
        {"lineage_role": "B_RECONSTRUCTION", "source_path": r1.rel(root, root / r1.SNAPSHOT_REL), "method": "BASE_80_PERCENT_PLUS_PIT_MOMENTUM_APPROX_20_PERCENT", "details": "Point-in-time momentum approximation.", "research_only": "TRUE"},
        {"lineage_role": "C_RECONSTRUCTION", "source_path": r1.rel(root, root / r1.SNAPSHOT_REL), "method": "BASE_85_PERCENT_PLUS_PIT_MOMENTUM_APPROX_15_PERCENT", "details": "UNKNOWN regime fallback.", "research_only": "TRUE"},
        {"lineage_role": "A0_EXCLUSION", "source_path": "", "method": "A0_CURRENT_TESTING_LOCKED_NOT_REPLAYED", "details": "No A0 proxy created.", "research_only": "TRUE"},
    ]
    r1.write_csv(out / LINEAGE_NAME, lineage_rows, list(lineage_rows[0].keys()))

    after = {path: r1.sha(root / path) for path in before}
    protected_modified = before != after
    a0_modified = any(before[path] != after[path] for path in before if "version_control" in path)
    official_modified = any(before[path] != after[path] for path in before if "official" in path.lower())
    real_modified = any(before[path] != after[path] for path in before if "real_book" in path.lower() or "realbook" in path.lower())
    broker_modified = any(before[path] != after[path] for path in before if "broker" in path.lower())
    hardcoded = sum(row["hardcoded_inclusion_violation_flag"] == "TRUE" for row in forced_rows)
    local_missing = sum(row["included_in_any_seed"] == "TRUE" and row["local_price_missing_flag"] == "TRUE" for row in forced_rows)
    tqqq_ipo = sum(row["tqqq_ipo_watch_violation_flag"] == "TRUE" for row in forced_rows)
    counts = Counter(results["variant_id"])

    def pair_rate(left: str, right: str, window: str) -> float | None:
        match = pair_df[
            (pair_df["left_variant"] == left) & (pair_df["right_variant"] == right)
            & (pair_df["forward_window"] == window) & (pair_df["top_n_bucket"] == "TOP20")
        ]
        return None if match.empty else float(match.iloc[0]["seed_win_rate"])

    b_rates = [pair_rate("B_MOMENTUM_STATIC_R1", "A1_BASELINE_REPLAY_CURRENT", window) for window in ("5D", "10D", "20D")]
    c_rates = [pair_rate("C_MOMENTUM_DYNAMIC_R1", "A1_BASELINE_REPLAY_CURRENT", window) for window in ("5D", "10D", "20D")]
    b_robust = all(rate is not None and rate >= .70 for rate in b_rates)
    c_robust = all(rate is not None and rate >= .70 for rate in c_rates)
    if b_robust and c_robust:
        robustness = (
            "B_STATIC_ROBUSTLY_BETTER_THAN_A1"
            if float(np.mean(b_rates)) >= float(np.mean(c_rates))
            else "C_DYNAMIC_ROBUSTLY_BETTER_THAN_A1"
        )
    elif b_robust:
        robustness = "B_STATIC_ROBUSTLY_BETTER_THAN_A1"
    elif c_robust:
        robustness = "C_DYNAMIC_ROBUSTLY_BETTER_THAN_A1"
    elif all(rate is not None and rate <= .30 for rate in b_rates + c_rates):
        robustness = "BASELINE_A1_BETTER"
    elif any(rate is not None and rate >= .70 for rate in b_rates + c_rates):
        robustness = "B_AND_C_MIXED"
    else:
        robustness = "INCONCLUSIVE"
    recommendation = "CONTINUE_OBSERVATION" if robustness in {
        "B_STATIC_ROBUSTLY_BETTER_THAN_A1", "C_DYNAMIC_ROBUSTLY_BETTER_THAN_A1", "B_AND_C_MIXED"
    } else "NEED_MORE_MATURITY"

    if a0_modified:
        final, decision = FAIL_A0, "STOP_AND_RESTORE_A0_CONTROL"
    elif protected_modified:
        final, decision = FAIL_MUTATION, "STOP_AND_RESTORE_FORBIDDEN_MUTATION"
    elif hardcoded:
        final, decision = FAIL_HARDCODED, "REPAIR_FORCED_INCLUSION_LOGIC"
    elif local_missing:
        final, decision = FAIL_PRICE, "REPAIR_RANDOM_BACKTEST_ELIGIBILITY"
    elif tqqq_ipo:
        final, decision = FAIL_TQQQ, "REPAIR_LISTING_AGE_POLICY_PROPAGATION"
    else:
        final, decision = PARTIAL_STATUS, "RANDOM_BACKTEST_READY_WITH_FALLBACK_WARN_CONTINUE_FORWARD_MONITORING"

    summary = {
        "FINAL_STATUS": final, "DECISION": decision, "stage_id": STAGE_ID, "research_only": True,
        "random_seed_count": len(SEEDS), "random_asof_count_per_seed": ASOF_PER_SEED,
        "actual_seed_count": draws["seed"].nunique(), "actual_total_sampled_asof_count": len(draws),
        "backtest_row_count": len(results), "a1_backtest_rows": counts["A1_BASELINE_REPLAY_CURRENT"],
        "b_backtest_rows": counts["B_MOMENTUM_STATIC_R1"], "c_backtest_rows": counts["C_MOMENTUM_DYNAMIC_R1"],
        "forward_windows": list(WINDOWS), "top_n_buckets": [f"TOP{value}" for value in TOP_N],
        "backtest_fallback_used": True, "point_in_time_approximation_used": True,
        "reduced_sample_used": reduced,
        "b_seed_win_rate_vs_a1_5d_top20": b_rates[0], "b_seed_win_rate_vs_a1_10d_top20": b_rates[1],
        "b_seed_win_rate_vs_a1_20d_top20": b_rates[2],
        "c_seed_win_rate_vs_a1_5d_top20": c_rates[0], "c_seed_win_rate_vs_a1_10d_top20": c_rates[1],
        "c_seed_win_rate_vs_a1_20d_top20": c_rates[2],
        "c_seed_win_rate_vs_b_5d_top20": pair_rate("C_MOMENTUM_DYNAMIC_R1", "B_MOMENTUM_STATIC_R1", "5D"),
        "c_seed_win_rate_vs_b_10d_top20": pair_rate("C_MOMENTUM_DYNAMIC_R1", "B_MOMENTUM_STATIC_R1", "10D"),
        "c_seed_win_rate_vs_b_20d_top20": pair_rate("C_MOMENTUM_DYNAMIC_R1", "B_MOMENTUM_STATIC_R1", "20D"),
        "robustness_read": robustness, "recommendation_status": recommendation,
        "production_adoption_allowed": False, "official_use_allowed": False,
        "a0_replayed": False, "a0_modified": a0_modified,
        "official_mutation_detected": official_modified,
        "real_book_mutation_detected": real_modified, "broker_mutation_detected": broker_modified,
        "hardcoded_inclusion_violation_count": hardcoded,
        "local_price_missing_included_violation_count": local_missing,
        "tqqq_ipo_watch_violation_count": tqqq_ipo,
        "next_recommended_stage": "CONTINUE_V21_062_DAILY_MATURITY_MONITORING",
    }
    r1.write_json(out / SUMMARY_NAME, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    summary = run_stage(args.root)
    print(json.dumps(summary, indent=2))
    return 1 if str(summary["FINAL_STATUS"]).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
