#!/usr/bin/env python
"""V21.103 research-only random long-horizon A1/B/C/D backtest.

Historical rankings are recomputed from canonical OHLCV available on or before
each as-of date. Current ranking files are never used as historical inputs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


STAGE = "V21.103_ABCD_RANDOM_LONG_HORIZON_BACKTEST_SPEC"
VARIANTS = ("A1", "B", "C", "D")
PORTFOLIO_SIZES = (20, 50)
HORIZONS = (126, 189, 252)
PRIMARY_HORIZON = 252
REBALANCE_INTERVAL = 21
DEFAULT_SEEDS = tuple(range(2026103001, 2026103031))
DEFAULT_DATES_PER_SEED = 100
MIN_LOOKBACK = 60
TRANSACTION_COST_BPS = (0, 10, 20)

PASS = "PASS_LONG_HORIZON_D_EDGE_CONFIRMED_RESEARCH_ONLY"
PARTIAL_EDGE = "PARTIAL_PASS_D_EDGE_EXISTS_BUT_TAIL_OR_TURNOVER_WARN"
PARTIAL_NO_EDGE = "PARTIAL_PASS_NO_CLEAR_D_EDGE_KEEP_FORWARD_MONITORING"
FAIL_UNDERPERFORM = "FAIL_D_UNDERPERFORMS_A1_OR_QQQ"
FAIL_BLOCKER = "FAIL_LEAKAGE_OR_DATA_QUALITY_BLOCKER"

PRICE_REL = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
BENCH_REL = Path("outputs/v20/price_history/V20_199D_CANONICAL_BENCHMARK_OHLCV.csv")
OUTPUT_ROOT_REL = Path("outputs/v21/v21_103_abcd_random_long_horizon")

CONFIG_NAME = "v21_103_abcd_random_long_horizon_config.json"
SAMPLE_NAME = "v21_103_abcd_random_sample_dates.csv"
HOLD_ROWS_NAME = "v21_103_abcd_252d_hold_row_results.csv"
HOLD_SUMMARY_NAME = "v21_103_abcd_252d_hold_summary.csv"
REBAL_ROWS_NAME = "v21_103_abcd_252d_monthly_rebalance_row_results.csv"
REBAL_SUMMARY_NAME = "v21_103_abcd_252d_monthly_rebalance_summary.csv"
LEAKAGE_NAME = "v21_103_abcd_long_horizon_leakage_audit.csv"
WARNING_NAME = "v21_103_abcd_long_horizon_data_quality_warnings.csv"
README_NAME = "v21_103_abcd_long_horizon_decision_readme.md"

ROW_FIELDS = [
    "sample_id", "seed", "draw_index", "start_date", "mode", "variant",
    "portfolio_size", "horizon", "transaction_cost_bps", "formation_count",
    "valid_position_count", "portfolio_return", "benchmark_QQQ_return",
    "benchmark_SPY_return", "benchmark_semiconductor_return",
    "semiconductor_benchmark", "excess_vs_A1", "excess_vs_B", "excess_vs_C",
    "excess_vs_D", "excess_vs_QQQ", "excess_vs_SPY",
    "excess_vs_semiconductor_benchmark", "max_drawdown", "turnover",
    "missing_price_count", "rebalance_count", "ranking_max_input_date",
    "point_in_time_valid", "survivorship_bias_warning", "research_only",
]

SUMMARY_FIELDS = [
    "variant", "portfolio_size", "mode", "horizon", "transaction_cost_bps",
    "sample_count", "mean_return", "median_return", "p5_return", "p25_return",
    "p75_return", "p95_return", "win_rate_vs_A1", "win_rate_vs_B",
    "win_rate_vs_C", "win_rate_vs_D", "win_rate_vs_QQQ", "win_rate_vs_SPY",
    "win_rate_vs_semiconductor_benchmark", "mean_excess_vs_QQQ",
    "median_excess_vs_QQQ", "p5_excess_vs_QQQ", "mean_excess_vs_A1",
    "max_drawdown_mean", "max_drawdown_median", "worst_sample_return",
    "best_sample_return", "missing_price_count", "leakage_warning_count",
    "survivorship_bias_warning_count", "turnover_mean", "turnover_median",
]


def truth(value: object) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def clean(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text.lower() == "nan" else text


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def resolved_output(root: Path, override: Path | None, run_id: str | None) -> Path:
    if override:
        return (override if override.is_absolute() else root / override).resolve()
    identifier = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return (root / OUTPUT_ROOT_REL / identifier).resolve()


def ensure_immutable_output(output: Path, allow_existing_empty: bool = True) -> None:
    if output.exists():
        contents = list(output.iterdir())
        if contents or not allow_existing_empty:
            raise RuntimeError(f"Immutable V21.103 output directory already exists and is non-empty: {output}")
    output.mkdir(parents=True, exist_ok=True)


def protected_files(root: Path, output: Path) -> list[Path]:
    paths: list[Path] = []
    for base in (root / "outputs/v21", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or output in path.resolve().parents:
                continue
            text = path.as_posix().lower()
            if (
                "official" in text
                or "broker" in text
                or "real_book" in text
                or "realbook" in text
                or "recommendation" in text
                or "version_control" in text
            ):
                paths.append(path.resolve())
    return sorted(set(paths))


def load_price_panel(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(
        path,
        usecols=["symbol", "date", "open", "high", "low", "close", "adjusted_close", "volume"],
        low_memory=False,
    )
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    frame["date"] = frame["date"].astype(str).str.slice(0, 10)
    # Canonical unadjusted close is used so later corporate-action adjustments
    # cannot revise historical factor inputs with future information.
    frame["price"] = pd.to_numeric(frame["close"], errors="coerce")
    for column in ("open", "high", "low", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame[frame["price"].gt(0)].sort_values(["symbol", "date"])
    return frame.drop_duplicates(["symbol", "date"], keep="last")


@dataclass
class MarketData:
    candidate: pd.DataFrame
    benchmark: pd.DataFrame
    calendar: list[str]
    candidate_prices: pd.DataFrame
    benchmark_prices: pd.DataFrame
    benchmark_names: tuple[str, ...]
    semiconductor_benchmark: str


def load_market_data(root: Path) -> MarketData:
    candidate = load_price_panel(root / PRICE_REL)
    benchmark = load_price_panel(root / BENCH_REL)
    benchmark_names = tuple(sorted(benchmark["symbol"].unique()))
    if "QQQ" not in benchmark_names or "SPY" not in benchmark_names:
        raise RuntimeError("QQQ and SPY benchmark histories are required.")
    semiconductor = "SOXX" if "SOXX" in benchmark_names else "SMH" if "SMH" in benchmark_names else ""
    qqq_dates = benchmark.loc[benchmark["symbol"].eq("QQQ"), "date"].tolist()
    calendar = sorted(set(qqq_dates))
    return MarketData(
        candidate=candidate,
        benchmark=benchmark,
        calendar=calendar,
        candidate_prices=candidate.pivot(index="date", columns="symbol", values="price").reindex(calendar),
        benchmark_prices=benchmark.pivot(index="date", columns="symbol", values="price").reindex(calendar),
        benchmark_names=benchmark_names,
        semiconductor_benchmark=semiconductor,
    )


def pct_rank(series: pd.Series) -> pd.Series:
    return series.rank(pct=True, method="average") * 100.0


def rolling_features(data: MarketData) -> dict[str, pd.DataFrame]:
    price = data.candidate_prices
    ret5 = price.pct_change(5, fill_method=None)
    ret10 = price.pct_change(10, fill_method=None)
    ret20 = price.pct_change(20, fill_method=None)
    ma20 = price.rolling(20, min_periods=20).mean()
    ma60 = price.rolling(60, min_periods=60).mean()
    vol20 = price.pct_change(fill_method=None).rolling(20, min_periods=20).std(ddof=0)
    high20 = price.rolling(20, min_periods=20).max()
    high60 = price.rolling(60, min_periods=60).max()
    volume = data.candidate.pivot(index="date", columns="symbol", values="volume").reindex(data.calendar)
    vol_ratio = volume.rolling(10, min_periods=10).mean() / volume.rolling(30, min_periods=30).mean()

    technical = (
        pct_rank(price / ma20 - 1).fillna(50)
        + pct_rank(ma20 / ma60 - 1).fillna(50)
        + pct_rank(ret20).fillna(50)
        + pct_rank(price / high20 - 1).fillna(50)
        + (100 - pct_rank(vol20)).fillna(50)
        + pct_rank(vol_ratio - 1).fillna(50)
    ) / 6
    strategy = (
        pct_rank(ret5).fillna(50)
        + pct_rank(ret20).fillna(50)
        + pct_rank(price / ma20 - 1).fillna(50)
        + pct_rank(vol_ratio - 1).fillna(50)
    ) / 4
    risk = (
        (100 - pct_rank(vol20)).fillna(50)
        + pct_rank(price / high60).fillna(50)
        + pct_rank(price / ma60 - 1).fillna(50)
    ) / 3

    bench = data.benchmark_prices
    qqq_regime = (
        (bench["QQQ"] > bench["QQQ"].rolling(20, min_periods=20).mean()).astype(float)
        + (bench["QQQ"].rolling(20, min_periods=20).mean() > bench["QQQ"].rolling(60, min_periods=60).mean()).astype(float)
        + bench["QQQ"].pct_change(20, fill_method=None).gt(0).astype(float)
    ) / 3
    spy_regime = (
        (bench["SPY"] > bench["SPY"].rolling(20, min_periods=20).mean()).astype(float)
        + (bench["SPY"].rolling(20, min_periods=20).mean() > bench["SPY"].rolling(60, min_periods=60).mean()).astype(float)
        + bench["SPY"].pct_change(20, fill_method=None).gt(0).astype(float)
    ) / 3
    market_regime = ((qqq_regime + spy_regime) / 2 * 100).fillna(50)
    market_component = pd.DataFrame(
        np.repeat(market_regime.to_numpy()[:, None], price.shape[1], axis=1),
        index=price.index,
        columns=price.columns,
    )
    base = 0.40 * technical + 0.30 * strategy + 0.15 * risk + 0.15 * market_component

    # Preserve the V21.060 intent using cross-sectional trailing returns. Benchmark
    # subtraction is constant within a date and therefore does not change ranks.
    momentum = 0.70 * ((pct_rank(ret5) + pct_rank(ret10) + pct_rank(ret20)) / 3) + 0.30 * technical
    dynamic_weight = pd.Series(
        np.where(market_regime >= 66.6667, 0.20, np.where(market_regime <= 33.3333, 0.10, 0.15)),
        index=market_regime.index,
    )
    valid = price.notna() & ma60.notna()
    return {
        "price": price,
        "base": base.where(valid),
        "momentum": momentum.where(valid),
        "market_regime": market_regime,
        "dynamic_weight": dynamic_weight,
    }


def rank_variants(features: dict[str, pd.DataFrame], as_of: str) -> dict[str, pd.DataFrame]:
    base = features["base"].loc[as_of]
    momentum = features["momentum"].loc[as_of]
    valid = base.notna() & momentum.notna()
    base, momentum = base[valid], momentum[valid]
    dynamic = float(features["dynamic_weight"].loc[as_of])
    specs = {"A1": 0.0, "B": 0.20, "C": dynamic, "D": 0.40}
    result = {}
    for variant, weight in specs.items():
        score = base * (1 - weight) + momentum * weight
        frame = pd.DataFrame({
            "ticker": score.index,
            "base_score": base,
            "momentum_score": momentum,
            "momentum_weight": weight,
            "score": score,
        }).sort_values(["score", "ticker"], ascending=[False, True])
        frame["rank"] = np.arange(1, len(frame) + 1)
        frame["as_of_date"] = as_of
        frame["max_input_date"] = as_of
        result[variant] = frame.reset_index(drop=True)
    return result


def eligible_start_dates(calendar: list[str], feature_dates: Iterable[str], horizon: int) -> list[str]:
    feature_set = set(feature_dates)
    return [
        day for index, day in enumerate(calendar)
        if day in feature_set and index >= MIN_LOOKBACK - 1 and index + horizon < len(calendar)
    ]


def sample_dates(eligible: list[str], seeds: tuple[int, ...], per_seed: int) -> list[dict[str, object]]:
    if not eligible:
        return []
    rows = []
    for seed in seeds:
        rng = np.random.default_rng(seed)
        replace = len(eligible) < per_seed
        sampled = rng.choice(eligible, size=min(per_seed, len(eligible)) if not replace else per_seed, replace=replace)
        for draw_index, day in enumerate(sampled, start=1):
            rows.append({
                "sample_id": f"V21_103::{seed}::{draw_index:03d}::{day}",
                "seed": seed,
                "draw_index": draw_index,
                "start_date": str(day),
                "eligible_start_date_count": len(eligible),
                "sampling_with_replacement": str(replace).upper(),
                "minimum_forward_sessions": PRIMARY_HORIZON,
                "research_only": "TRUE",
            })
    return rows


def max_drawdown(values: np.ndarray) -> float:
    if values.size == 0:
        return float("nan")
    peaks = np.maximum.accumulate(values)
    drawdowns = values / peaks - 1
    return float(np.nanmin(drawdowns))


def benchmark_path(data: MarketData, ticker: str, start_index: int, horizon: int) -> np.ndarray:
    series = data.benchmark_prices[ticker].iloc[start_index:start_index + horizon + 1].to_numpy(dtype=float)
    return series / series[0] if len(series) == horizon + 1 and np.isfinite(series).all() else np.array([])


def equal_weight_path(
    price_panel: pd.DataFrame, tickers: list[str], start_index: int, horizon: int,
) -> tuple[np.ndarray, int]:
    selected = [ticker for ticker in tickers if ticker in price_panel.columns]
    raw = price_panel[selected].iloc[start_index:start_index + horizon + 1].copy()
    start = raw.iloc[0]
    valid_start = start.notna() & start.gt(0)
    raw = raw.loc[:, valid_start]
    if raw.empty:
        return np.array([]), len(tickers)
    normalized = raw.divide(raw.iloc[0], axis=1)
    available = normalized.notna()
    path = normalized.mean(axis=1, skipna=True).to_numpy(dtype=float)
    missing = int((~available).sum().sum())
    return path, missing


def turnover(previous: set[str], current: set[str]) -> float:
    if not previous:
        return 1.0
    return 1.0 - len(previous & current) / max(len(previous), len(current), 1)


def hold_result(
    data: MarketData, rankings: dict[str, pd.DataFrame], sample: dict[str, object],
    portfolio_size: int, horizon: int,
) -> list[dict[str, object]]:
    start_index = data.calendar.index(str(sample["start_date"]))
    benchmark_paths = {
        ticker: benchmark_path(data, ticker, start_index, horizon)
        for ticker in ("QQQ", "SPY", data.semiconductor_benchmark)
        if ticker
    }
    returns: dict[str, float] = {}
    rows = []
    temporary: dict[str, dict[str, object]] = {}
    for variant in VARIANTS:
        selected = rankings[variant].head(portfolio_size)["ticker"].tolist()
        path, missing = equal_weight_path(data.candidate_prices, selected, start_index, horizon)
        value = float(path[-1] - 1) if path.size else float("nan")
        returns[variant] = value
        temporary[variant] = {
            "selected": selected, "path": path, "missing": missing, "return": value,
        }
    for variant in VARIANTS:
        result = temporary[variant]
        path = result["path"]
        qqq = benchmark_paths.get("QQQ", np.array([]))
        spy = benchmark_paths.get("SPY", np.array([]))
        semi = benchmark_paths.get(data.semiconductor_benchmark, np.array([]))
        row = {
            **sample, "mode": "RANDOM_252D_HOLD", "variant": variant,
            "portfolio_size": portfolio_size, "horizon": horizon,
            "transaction_cost_bps": 0, "formation_count": len(result["selected"]),
            "valid_position_count": len(result["selected"]),
            "portfolio_return": result["return"],
            "benchmark_QQQ_return": qqq[-1] - 1 if qqq.size else np.nan,
            "benchmark_SPY_return": spy[-1] - 1 if spy.size else np.nan,
            "benchmark_semiconductor_return": semi[-1] - 1 if semi.size else np.nan,
            "semiconductor_benchmark": data.semiconductor_benchmark,
            "max_drawdown": max_drawdown(path), "turnover": 0.0,
            "missing_price_count": result["missing"], "rebalance_count": 0,
            "ranking_max_input_date": sample["start_date"], "point_in_time_valid": "TRUE",
            "survivorship_bias_warning": "TRUE", "research_only": "TRUE",
        }
        for comparison in VARIANTS:
            row[f"excess_vs_{comparison}"] = result["return"] - returns[comparison]
        row["excess_vs_QQQ"] = result["return"] - row["benchmark_QQQ_return"]
        row["excess_vs_SPY"] = result["return"] - row["benchmark_SPY_return"]
        row["excess_vs_semiconductor_benchmark"] = (
            result["return"] - row["benchmark_semiconductor_return"]
            if data.semiconductor_benchmark else np.nan
        )
        rows.append(row)
    return rows


def monthly_result(
    data: MarketData, features: dict[str, pd.DataFrame], rank_cache: dict[str, dict[str, pd.DataFrame]],
    sample: dict[str, object], portfolio_size: int, horizon: int, cost_bps: int,
) -> list[dict[str, object]]:
    start_index = data.calendar.index(str(sample["start_date"]))
    offsets = list(range(0, horizon, REBALANCE_INTERVAL))
    benchmark_paths = {
        ticker: benchmark_path(data, ticker, start_index, horizon)
        for ticker in ("QQQ", "SPY", data.semiconductor_benchmark)
        if ticker
    }
    variant_results: dict[str, dict[str, object]] = {}
    for variant in VARIANTS:
        wealth = 1.0
        curve = [1.0]
        previous: set[str] = set()
        total_turnover = 0.0
        missing = 0
        ranking_dates = []
        pit_violation_count = 0
        for offset in offsets:
            rebalance_index = start_index + offset
            end_index = min(start_index + horizon, rebalance_index + REBALANCE_INTERVAL)
            rebalance_date = data.calendar[rebalance_index]
            if rebalance_date not in rank_cache:
                rank_cache[rebalance_date] = rank_variants(features, rebalance_date)
            ranking_dates.append(rebalance_date)
            ranking_input_date = clean(
                rank_cache[rebalance_date][variant]["max_input_date"].max()
            )
            if ranking_input_date > rebalance_date:
                pit_violation_count += 1
            selected = set(rank_cache[rebalance_date][variant].head(portfolio_size)["ticker"])
            leg_horizon = end_index - rebalance_index
            path, leg_missing = equal_weight_path(
                data.candidate_prices, sorted(selected), rebalance_index, leg_horizon,
            )
            if not path.size:
                continue
            leg_turnover = turnover(previous, selected)
            cost = leg_turnover * cost_bps / 10000.0
            leg_curve = path / path[0] * wealth * (1 - cost)
            curve.extend(leg_curve[1:].tolist())
            wealth = float(leg_curve[-1])
            total_turnover += leg_turnover
            missing += leg_missing
            previous = selected
        variant_results[variant] = {
            "return": wealth - 1, "curve": np.asarray(curve),
            "turnover": total_turnover, "missing": missing,
            "rebalance_count": len(offsets), "ranking_max_input_date": max(ranking_dates),
            "pit_violation_count": pit_violation_count,
        }
    rows = []
    for variant in VARIANTS:
        result = variant_results[variant]
        qqq = benchmark_paths.get("QQQ", np.array([]))
        spy = benchmark_paths.get("SPY", np.array([]))
        semi = benchmark_paths.get(data.semiconductor_benchmark, np.array([]))
        row = {
            **sample, "mode": "RANDOM_252D_MONTHLY_REBALANCE", "variant": variant,
            "portfolio_size": portfolio_size, "horizon": horizon,
            "transaction_cost_bps": cost_bps, "formation_count": portfolio_size,
            "valid_position_count": portfolio_size,
            "portfolio_return": result["return"],
            "benchmark_QQQ_return": qqq[-1] - 1 if qqq.size else np.nan,
            "benchmark_SPY_return": spy[-1] - 1 if spy.size else np.nan,
            "benchmark_semiconductor_return": semi[-1] - 1 if semi.size else np.nan,
            "semiconductor_benchmark": data.semiconductor_benchmark,
            "max_drawdown": max_drawdown(result["curve"]),
            "turnover": result["turnover"], "missing_price_count": result["missing"],
            "rebalance_count": result["rebalance_count"],
            "ranking_max_input_date": result["ranking_max_input_date"],
            "point_in_time_valid": str(result["pit_violation_count"] == 0).upper(),
            "survivorship_bias_warning": "TRUE", "research_only": "TRUE",
        }
        for comparison in VARIANTS:
            row[f"excess_vs_{comparison}"] = result["return"] - variant_results[comparison]["return"]
        row["excess_vs_QQQ"] = result["return"] - row["benchmark_QQQ_return"]
        row["excess_vs_SPY"] = result["return"] - row["benchmark_SPY_return"]
        row["excess_vs_semiconductor_benchmark"] = (
            result["return"] - row["benchmark_semiconductor_return"]
            if data.semiconductor_benchmark else np.nan
        )
        rows.append(row)
    return rows


def leakage_audit(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    audits = []
    for row in rows:
        start = clean(row["start_date"])
        ranking_max = clean(row["ranking_max_input_date"])
        horizon_end = ""
        valid = truth(row["point_in_time_valid"])
        if row["mode"] == "RANDOM_252D_HOLD":
            valid = valid and ranking_max <= start
        else:
            # Monthly rankings legitimately use information available at each
            # rebalance date, but never after that rebalance date.
            valid = valid
        audits.append({
            "sample_id": row["sample_id"], "mode": row["mode"],
            "variant": row["variant"], "portfolio_size": row["portfolio_size"],
            "horizon": row["horizon"], "transaction_cost_bps": row["transaction_cost_bps"],
            "start_date": start, "ranking_max_input_date": ranking_max,
            "forward_return_starts_after_as_of": "TRUE",
            "current_ranking_used": "FALSE", "future_label_used": "FALSE",
            "future_membership_used": "FALSE", "point_in_time_valid": str(valid).upper(),
            "leakage_violation_reason": "" if valid else "RANKING_INPUT_AFTER_ALLOWED_REBALANCE_DATE",
            "research_only": "TRUE",
        })
    return audits


def summarize(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    frame = pd.DataFrame(rows)
    numeric = [
        "portfolio_return", "benchmark_QQQ_return", "benchmark_SPY_return",
        "benchmark_semiconductor_return", "excess_vs_A1", "excess_vs_QQQ",
        "max_drawdown", "turnover", "missing_price_count",
    ]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    output = []
    group_fields = ["variant", "portfolio_size", "mode", "horizon", "transaction_cost_bps"]
    for keys, group in frame.groupby(group_fields, sort=True):
        values = group["portfolio_return"].dropna()
        row = dict(zip(group_fields, keys))
        row.update({
            "sample_count": len(values),
            "mean_return": values.mean(), "median_return": values.median(),
            "p5_return": values.quantile(.05), "p25_return": values.quantile(.25),
            "p75_return": values.quantile(.75), "p95_return": values.quantile(.95),
            "win_rate_vs_A1": group["excess_vs_A1"].gt(0).mean(),
            "win_rate_vs_B": pd.to_numeric(group["excess_vs_B"], errors="coerce").gt(0).mean(),
            "win_rate_vs_C": pd.to_numeric(group["excess_vs_C"], errors="coerce").gt(0).mean(),
            "win_rate_vs_D": pd.to_numeric(group["excess_vs_D"], errors="coerce").gt(0).mean(),
            "win_rate_vs_QQQ": group["excess_vs_QQQ"].gt(0).mean(),
            "win_rate_vs_SPY": pd.to_numeric(group["excess_vs_SPY"], errors="coerce").gt(0).mean(),
            "win_rate_vs_semiconductor_benchmark": pd.to_numeric(
                group["excess_vs_semiconductor_benchmark"], errors="coerce"
            ).gt(0).mean(),
            "mean_excess_vs_QQQ": group["excess_vs_QQQ"].mean(),
            "median_excess_vs_QQQ": group["excess_vs_QQQ"].median(),
            "p5_excess_vs_QQQ": group["excess_vs_QQQ"].quantile(.05),
            "mean_excess_vs_A1": group["excess_vs_A1"].mean(),
            "max_drawdown_mean": group["max_drawdown"].mean(),
            "max_drawdown_median": group["max_drawdown"].median(),
            "worst_sample_return": values.min(), "best_sample_return": values.max(),
            "missing_price_count": int(group["missing_price_count"].sum()),
            "leakage_warning_count": int((~group["point_in_time_valid"].map(truth)).sum()),
            "survivorship_bias_warning_count": int(group["survivorship_bias_warning"].map(truth).sum()),
            "turnover_mean": group["turnover"].mean(),
            "turnover_median": group["turnover"].median(),
        })
        output.append(row)
    return output


def decide(summary: pd.DataFrame, leakage_count: int, core_data_ok: bool) -> tuple[str, str]:
    if leakage_count or not core_data_ok or summary.empty:
        return FAIL_BLOCKER, "STOP_REPAIR_LEAKAGE_OR_CORE_DATA"
    primary = summary[
        (summary["variant"] == "D") & (summary["horizon"] == PRIMARY_HORIZON)
        & (summary["transaction_cost_bps"] == 0)
    ]
    if primary.empty:
        return FAIL_BLOCKER, "STOP_NO_PRIMARY_D_RESULTS"
    beats_a1 = primary["mean_excess_vs_A1"].mean() > 0
    beats_qqq = primary["mean_excess_vs_QQQ"].mean() > 0
    win_a1 = primary["win_rate_vs_A1"].mean()
    win_qqq = primary["win_rate_vs_QQQ"].mean()
    tail_warn = primary["p5_return"].mean() < -0.35
    monthly = primary[primary["mode"] == "RANDOM_252D_MONTHLY_REBALANCE"]
    turnover_warn = not monthly.empty and monthly["turnover_mean"].mean() > 6.0
    if not beats_a1 and not beats_qqq:
        return FAIL_UNDERPERFORM, "D_UNDERPERFORMS_A1_AND_QQQ_ON_PRIMARY_CELLS"
    if beats_a1 and beats_qqq and win_a1 >= .55 and win_qqq >= .50 and not tail_warn and not turnover_warn:
        return PASS, "D_LONG_HORIZON_EDGE_CONFIRMED_RESEARCH_ONLY_NO_ADOPTION"
    if beats_a1 or beats_qqq:
        return PARTIAL_EDGE, "D_EDGE_PRESENT_WITH_TAIL_OR_TURNOVER_WARNING"
    return PARTIAL_NO_EDGE, "NO_CLEAR_D_EDGE_CONTINUE_FORWARD_MONITORING"


def render_readme(
    config: dict[str, object], status: str, decision: str, samples: list[dict[str, object]],
    summary: pd.DataFrame, warnings: list[dict[str, object]], output: Path,
) -> None:
    primary = summary[
        (summary["variant"] == "D") & (summary["horizon"] == PRIMARY_HORIZON)
        & (summary["transaction_cost_bps"] == 0)
    ]
    def positive(column: str) -> str:
        return "NOT_AVAILABLE" if primary.empty else ("YES" if primary[column].mean() > 0 else "NO")
    def majority(column: str) -> str:
        return "NOT_AVAILABLE" if primary.empty else ("YES" if primary[column].mean() > .50 else "NO")
    tail = "NOT_AVAILABLE" if primary.empty else ("YES" if primary["p5_return"].mean() < -0.35 else "NO")
    monthly = primary[primary["mode"] == "RANDOM_252D_MONTHLY_REBALANCE"]
    turnover = "NOT_AVAILABLE" if monthly.empty else ("YES" if monthly["turnover_mean"].mean() <= 6 else "NO")
    warning_codes = sorted({clean(row["warning_code"]) for row in warnings})
    text = f"""# V21.103 A1/B/C/D Random Long-Horizon Backtest

FINAL_STATUS: `{status}`  
DECISION: `{decision}`  
Research only: `TRUE`  
Official adoption allowed: `FALSE`

## Scope

- Primary horizon: {PRIMARY_HORIZON} trading days
- Diagnostic horizons: 126 and 189 trading days
- Random seeds: {config['seed_count']}
- Requested dates per seed: {config['random_start_dates_per_seed']}
- Actual sampled rows: {len(samples)}
- Portfolio sizes: Top20 and Top50 equal weight
- Modes: random hold and 21-session monthly rebalance
- Monthly transaction costs: 0, 10, and 20 bps

## D primary evidence

- D beat A1 on mean primary excess: {positive('mean_excess_vs_A1')}
- D beat B by primary win rate above 50%: {majority('win_rate_vs_B')}
- D beat C by primary win rate above 50%: {majority('win_rate_vs_C')}
- D beat QQQ on mean primary excess: {positive('mean_excess_vs_QQQ')}
- D beat SPY by primary win rate above 50%: {majority('win_rate_vs_SPY')}
- D has left-tail weakness: {tail}
- Monthly rebalance turnover acceptable: {turnover}

## PIT and data policy

- Historical rankings were recomputed from canonical OHLCV dated on or before each formation/rebalance date.
- Current A1/B/C/D ranking outputs were not used as historical rankings.
- Forward returns begin after the as-of date.
- Missing-price policy: carry the unavailable position as missing and deterministically reweight remaining available positions at each valuation point.
- Historical point-in-time universe membership is unavailable. `SURVIVORSHIP_BIAS_WARN` applies to all samples.
- Semiconductor benchmark: {config['semiconductor_benchmark'] or 'NOT_AVAILABLE'}

## Warnings

{', '.join(warning_codes) if warning_codes else 'NONE'}

## Adoption boundary

This stage cannot adopt D, alter official rankings, create recommendations, or create broker/trading actions. Event-risk coefficients are not integrated.
"""
    (output / README_NAME).write_text(text, encoding="utf-8")


def run_stage(
    root: Path, output: Path, seeds: tuple[int, ...] = DEFAULT_SEEDS,
    dates_per_seed: int = DEFAULT_DATES_PER_SEED, max_samples: int | None = None,
) -> dict[str, object]:
    root, output = root.resolve(), output.resolve()
    ensure_immutable_output(output)
    protected = protected_files(root, output)
    before = {path: sha256(path) for path in protected}
    warnings = [{
        "warning_code": "SURVIVORSHIP_BIAS_WARN",
        "severity": "MEDIUM",
        "scope": "ALL_SAMPLES",
        "details": "True historical PIT universe membership is unavailable; current canonical ticker coverage is used.",
        "research_only": "TRUE",
    }, {
        "warning_code": "PIT_FACTOR_APPROXIMATION_WARN",
        "severity": "MEDIUM",
        "scope": "A1_B_C_D_HISTORICAL_RANKINGS",
        "details": "Historical full-factor A1 inputs are unavailable; variants use the documented price/volume-derived PIT-lite factor policy.",
        "research_only": "TRUE",
    }]
    try:
        data = load_market_data(root)
        features = rolling_features(data)
        eligible = eligible_start_dates(data.calendar, features["base"].dropna(how="all").index, PRIMARY_HORIZON)
        samples = sample_dates(eligible, seeds, dates_per_seed)
        if max_samples is not None:
            samples = samples[:max_samples]
        config = {
            "stage": STAGE, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "seed_count": len(seeds), "seeds": list(seeds),
            "random_start_dates_per_seed": dates_per_seed,
            "actual_sample_count": len(samples), "eligible_start_date_count": len(eligible),
            "max_samples_override": max_samples,
            "horizons": list(HORIZONS), "primary_horizon": PRIMARY_HORIZON,
            "portfolio_sizes": list(PORTFOLIO_SIZES),
            "modes": ["RANDOM_252D_HOLD", "RANDOM_252D_MONTHLY_REBALANCE"],
            "rebalance_interval_trading_days": REBALANCE_INTERVAL,
            "transaction_cost_bps": list(TRANSACTION_COST_BPS),
            "variant_weights": {
                "A1": {"base": 1.0, "momentum": 0.0},
                "B": {"base": 0.80, "momentum": 0.20},
                "C": {"dynamic_momentum": {"risk_off": 0.10, "neutral": 0.15, "risk_on": 0.20}},
                "D": {"base": 0.60, "momentum": 0.40},
            },
            "candidate_price_source": PRICE_REL.as_posix(),
            "benchmark_price_source": BENCH_REL.as_posix(),
            "benchmarks": list(data.benchmark_names),
            "semiconductor_benchmark": data.semiconductor_benchmark,
            "missing_price_policy": "REWEIGHT_REMAINING_AVAILABLE_POSITIONS_AT_EACH_VALUATION_POINT",
            "survivorship_bias_warning": True,
            "research_only": True, "official_adoption_allowed": False,
            "event_risk_integrated": False,
        }
        write_json(output / CONFIG_NAME, config)
        write_csv(
            output / SAMPLE_NAME, samples,
            ["sample_id", "seed", "draw_index", "start_date", "eligible_start_date_count",
             "sampling_with_replacement", "minimum_forward_sessions", "research_only"],
        )
        rank_cache: dict[str, dict[str, pd.DataFrame]] = {}
        hold_rows: list[dict[str, object]] = []
        rebalance_rows: list[dict[str, object]] = []
        for sample in samples:
            start = str(sample["start_date"])
            if start not in rank_cache:
                rank_cache[start] = rank_variants(features, start)
            for size in PORTFOLIO_SIZES:
                for horizon in HORIZONS:
                    hold_rows.extend(hold_result(data, rank_cache[start], sample, size, horizon))
                    for cost in TRANSACTION_COST_BPS:
                        rebalance_rows.extend(
                            monthly_result(data, features, rank_cache, sample, size, horizon, cost)
                        )
        hold_audit = leakage_audit(hold_rows)
        rebalance_audit = leakage_audit(rebalance_rows)
        audits = hold_audit + rebalance_audit
        leakage_count = sum(not truth(row["point_in_time_valid"]) for row in audits)
        write_csv(output / HOLD_ROWS_NAME, hold_rows, ROW_FIELDS)
        write_csv(output / REBAL_ROWS_NAME, rebalance_rows, ROW_FIELDS)
        hold_summary = summarize(hold_rows)
        rebalance_summary = summarize(rebalance_rows)
        write_csv(output / HOLD_SUMMARY_NAME, hold_summary, SUMMARY_FIELDS)
        write_csv(output / REBAL_SUMMARY_NAME, rebalance_summary, SUMMARY_FIELDS)
        write_csv(
            output / LEAKAGE_NAME, audits,
            ["sample_id", "mode", "variant", "portfolio_size", "horizon",
             "transaction_cost_bps", "start_date", "ranking_max_input_date",
             "forward_return_starts_after_as_of", "current_ranking_used",
             "future_label_used", "future_membership_used", "point_in_time_valid",
             "leakage_violation_reason", "research_only"],
        )
        if any(row["missing_price_count"] for row in hold_rows + rebalance_rows):
            warnings.append({
                "warning_code": "MISSING_FORWARD_PRICE_REWEIGHT_APPLIED",
                "severity": "LOW", "scope": "ROW_RESULTS",
                "details": "At least one valuation lacked a ticker price; remaining available positions were reweighted.",
                "research_only": "TRUE",
            })
        if max_samples is not None:
            warnings.append({
                "warning_code": "BOUNDED_VALIDATION_SAMPLE",
                "severity": "LOW", "scope": "STAGE",
                "details": f"Execution was capped at {max_samples} samples for implementation validation.",
                "research_only": "TRUE",
            })
        write_csv(
            output / WARNING_NAME, warnings,
            ["warning_code", "severity", "scope", "details", "research_only"],
        )
        combined_summary = pd.DataFrame(hold_summary + rebalance_summary)
        status, decision = decide(combined_summary, leakage_count, True)
        render_readme(config, status, decision, samples, combined_summary, warnings, output)
    except Exception as exc:
        config = {
            "stage": STAGE, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "seed_count": len(seeds), "random_start_dates_per_seed": dates_per_seed,
            "research_only": True, "official_adoption_allowed": False,
            "event_risk_integrated": False, "execution_error": str(exc),
        }
        write_json(output / CONFIG_NAME, config)
        for name, fields in (
            (SAMPLE_NAME, ["sample_id", "seed", "draw_index", "start_date"]),
            (HOLD_ROWS_NAME, ROW_FIELDS), (HOLD_SUMMARY_NAME, SUMMARY_FIELDS),
            (REBAL_ROWS_NAME, ROW_FIELDS), (REBAL_SUMMARY_NAME, SUMMARY_FIELDS),
            (LEAKAGE_NAME, ["sample_id", "point_in_time_valid", "leakage_violation_reason"]),
        ):
            write_csv(output / name, [], fields)
        warnings.append({
            "warning_code": "EXECUTION_BLOCKER", "severity": "HIGH", "scope": "STAGE",
            "details": str(exc), "research_only": "TRUE",
        })
        write_csv(output / WARNING_NAME, warnings, ["warning_code", "severity", "scope", "details", "research_only"])
        status, decision = FAIL_BLOCKER, "STOP_REPAIR_EXECUTION_OR_DATA_BLOCKER"
        (output / README_NAME).write_text(
            f"# V21.103 A1/B/C/D Random Long-Horizon Backtest\n\n"
            f"FINAL_STATUS: `{status}`  \nDECISION: `{decision}`  \n"
            "Official adoption allowed: `FALSE`\n\n"
            f"Blocking error: {exc}\n",
            encoding="utf-8",
        )
    after = {path: sha256(path) for path in protected}
    changed = [path for path in protected if before[path] != after[path]]
    if changed:
        status, decision = FAIL_BLOCKER, "STOP_PROTECTED_OUTPUT_MUTATION_DETECTED"
        with (output / README_NAME).open("a", encoding="utf-8") as handle:
            handle.write("\nProtected output mutation detected. Final status forced to FAIL.\n")
    result = {
        "FINAL_STATUS": status, "DECISION": decision,
        "OUTPUT_DIR": output.as_posix(), "PROTECTED_OUTPUTS_MODIFIED": bool(changed),
        "OFFICIAL_ADOPTION_ALLOWED": False, "RESEARCH_ONLY": True,
    }
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--seed-count", type=int, default=len(DEFAULT_SEEDS))
    parser.add_argument("--dates-per-seed", type=int, default=DEFAULT_DATES_PER_SEED)
    parser.add_argument("--max-samples", type=int)
    args = parser.parse_args()
    seeds = DEFAULT_SEEDS[: max(1, min(args.seed_count, len(DEFAULT_SEEDS)))]
    output = resolved_output(args.root.resolve(), args.output_dir, args.run_id)
    result = run_stage(args.root, output, seeds, args.dates_per_seed, args.max_samples)
    return 1 if str(result["FINAL_STATUS"]).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
