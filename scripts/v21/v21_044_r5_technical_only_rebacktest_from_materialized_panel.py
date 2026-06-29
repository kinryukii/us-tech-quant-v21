#!/usr/bin/env python
"""Research-only technical-only rebacktest from the V21.044-R4 panel."""

from __future__ import annotations

import csv
import math
import random
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.044-R5_TECHNICAL_ONLY_REBACKTEST_FROM_MATERIALIZED_PANEL"
PASS_STATUS = "PASS_V21_044_R5_TECHNICAL_ONLY_REBACKTEST_READY"
OVERLAP_STATUS = "PARTIAL_PASS_V21_044_R5_TECHNICAL_ONLY_REBACKTEST_LIMITED_OVERLAP"
DEVIATION_STATUS = "PARTIAL_PASS_V21_044_R5_TECHNICAL_ONLY_REBACKTEST_WITH_MATERIAL_DEVIATION"
R4_BLOCKED = "BLOCKED_V21_044_R5_R4_TECHNICAL_PANEL_NOT_READY"
DATES_BLOCKED = "BLOCKED_V21_044_R5_NO_ELIGIBLE_TECHNICAL_ASOF_DATES"
PRICE_BLOCKED = "BLOCKED_V21_044_R5_PRICE_OR_BENCHMARK_SOURCE_NOT_FOUND"

REPRODUCES = "TECHNICAL_ONLY_REBACKTEST_REPRODUCES_PRIOR_QQQ_EDGE_RESEARCH_ONLY"
DIRECTIONAL = "TECHNICAL_ONLY_REBACKTEST_DIRECTIONALLY_SUPPORTS_PRIOR_QQQ_EDGE_RESEARCH_ONLY"
DIFFERS = "TECHNICAL_ONLY_REBACKTEST_MATERIALLY_DIFFERS_REVIEW_REQUIRED"
NO_SUPPORT = "TECHNICAL_ONLY_REBACKTEST_DOES_NOT_SUPPORT_PRIOR_EDGE"
KEEP_BLOCKED = "KEEP_FULL_WEIGHT_BLOCKED_AND_REPAIR_MISSING_FAMILIES"

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "outputs" / "v21" / "review"
BACKTEST = ROOT / "outputs" / "v21" / "backtest"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"
R4_PANEL = REVIEW / "V21_044_R4_TECHNICAL_ONLY_HISTORICAL_SCORE_PANEL.csv"
R4_ELIGIBLE = REVIEW / "V21_044_R4_TECHNICAL_ONLY_ELIGIBLE_ASOF_MANIFEST.csv"
R4_DECISION = REVIEW / "V21_044_R4_MATERIALIZATION_DECISION_SUMMARY.csv"
SAMPLE_MANIFEST = BACKTEST / "V21_042_R1_RANDOM_ASOF_SAMPLE_MANIFEST.csv"
PRIOR_WINDOW = BACKTEST / "V21_042_R1_RANDOM_ASOF_VARIANT_WINDOW_SUMMARY.csv"
PRIOR_BENCHMARK = BACKTEST / "V21_042_R2_VARIANT_WINDOW_BENCHMARK_SUMMARY.csv"
TICKER_PRICES = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
QQQ_PRICES = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"

PANEL_OUT = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_REBACKTEST_PANEL.csv"
SUMMARY_OUT = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_VARIANT_WINDOW_SUMMARY.csv"
QQQ_OUT = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_QQQ_BENCHMARK_COMPARISON.csv"
REPRO_OUT = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_REPRODUCTION_COMPARISON.csv"
LEAKAGE_OUT = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_LEAKAGE_AUDIT.csv"
DECISION_OUT = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_DECISION_SUMMARY.csv"
REPORT_OUT = READ_CENTER / "V21_044_R5_TECHNICAL_ONLY_REBACKTEST_FROM_MATERIALIZED_PANEL_REPORT.md"
CURRENT_REPORT_OUT = READ_CENTER / "CURRENT_V21_044_R5_TECHNICAL_ONLY_REBACKTEST_FROM_MATERIALIZED_PANEL_REPORT.md"

WINDOWS = {"5D": 5, "10D": 10, "20D": 20, "60D": 60}
NEW_SAMPLE_SEED = 21045
PRIOR_FALLBACK = {"5D": 0.00976, "10D": 0.00801, "20D": 0.03685, "60D": 0.19328}

PANEL_FIELDS = [
    "as_of_date", "ticker", "family", "technical_only_score", "technical_only_rank",
    "forward_return_window", "price_source_path", "price_field", "price_entry_date",
    "forward_price_date", "entry_price", "forward_price", "realized_forward_return",
    "price_alignment_status", "price_alignment_warning", "benchmark_symbol",
    "benchmark_source_path", "benchmark_price_field", "benchmark_entry_date",
    "benchmark_forward_date", "benchmark_forward_return", "benchmark_alignment_status",
    "benchmark_alignment_warning", "point_in_time_safe", "leakage_violation_reason",
    "included_in_performance_aggregation",
]
SUMMARY_FIELDS = [
    "variant_name", "forward_return_window", "sampled_asof_count",
    "benchmark_available_asof_count", "total_scored_rows", "top20_mean_forward_return",
    "top20_median_forward_return", "top20_hit_rate_absolute", "universe_mean_forward_return",
    "top20_excess_vs_universe", "top20_excess_vs_QQQ", "top20_hit_rate_vs_QQQ",
    "positive_asof_ratio_vs_QQQ", "top50_excess_vs_universe", "top50_excess_vs_QQQ",
    "top_decile_excess_vs_universe", "top_decile_excess_vs_QQQ",
    "bottom_decile_mean_forward_return", "long_short_top_bottom_decile_spread",
    "rank_ic_spearman_mean", "rank_ic_spearman_median", "price_missing_count",
    "missing_return_count", "benchmark_missing_count", "leakage_violation_count",
]


def guardrails() -> dict[str, str]:
    return {
        "research_only": "TRUE",
        "technical_only_backtest": "TRUE",
        "full_weight_rebacktest_allowed_now": "FALSE",
        "official_adoption_allowed": "FALSE",
        "official_weight_mutation": "FALSE",
        "official_ranking_mutation": "FALSE",
        "real_book_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE",
        "shadow_adoption_allowed": "FALSE",
    }


def clean(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def fmt(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, (float, np.floating)):
        return "" if not math.isfinite(float(value)) else f"{float(value):.10f}"
    return value


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def read_csv(path: Path, **kwargs: object) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False, **kwargs)


def first_row(path: Path) -> dict[str, str]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.DictReader(handle), {}) or {}


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def validate_r4() -> tuple[bool, str]:
    required = [R4_PANEL, R4_ELIGIBLE, R4_DECISION]
    missing = [relative(path) for path in required if not path.exists() or path.stat().st_size == 0]
    if missing:
        return False, "MISSING_R4_ARTIFACTS=" + "|".join(missing)
    decision = first_row(R4_DECISION)
    if decision.get("final_status") != "PASS_V21_044_R4_TECHNICAL_ONLY_MATERIALIZATION_READY_FULL_WEIGHT_BLOCKED":
        return False, "R4_FINAL_STATUS=" + decision.get("final_status", "")
    if decision.get("technical_only_backtest_allowed_next", "").upper() != "TRUE":
        return False, "R4_TECHNICAL_ONLY_BACKTEST_NOT_ALLOWED"
    return True, ""


def sample_dates(panel_dates: list[str]) -> tuple[list[str], str, int, int]:
    eligible = set(panel_dates)
    if SAMPLE_MANIFEST.exists():
        manifest = read_csv(SAMPLE_MANIFEST)
        manifest_dates = sorted(set(pd.to_datetime(manifest["as_of_date"], errors="coerce").dropna().dt.strftime("%Y-%m-%d")))
        overlap = [date for date in manifest_dates if date in eligible]
        return overlap, "REUSED_V21_042_R1_SAMPLE_MANIFEST", len(manifest_dates), len(overlap)
    dates = sorted(eligible)
    rng = random.Random(NEW_SAMPLE_SEED)
    selected = sorted(rng.sample(dates, min(50, len(dates)))) if dates else []
    return selected, f"NEW_DETERMINISTIC_SAMPLE_SEED_{NEW_SAMPLE_SEED}", 0, 0


def normalize_prices(path: Path, symbol_filter: str | None = None) -> tuple[pd.DataFrame, str]:
    df = read_csv(path)
    names = {column.lower(): column for column in df.columns}
    symbol_col = names.get("symbol") or names.get("ticker")
    date_col = names.get("date") or names.get("as_of_date")
    adjusted = names.get("adjusted_close") or names.get("adj_close")
    close = names.get("close")
    if not symbol_col or not date_col or not (adjusted or close):
        return pd.DataFrame(), ""
    if symbol_filter:
        df = df[df[symbol_col].astype(str).str.upper().str.strip() == symbol_filter].copy()
    price_col = adjusted if adjusted and (pd.to_numeric(df[adjusted], errors="coerce") > 0).sum() >= 2 else close
    if not price_col:
        return pd.DataFrame(), ""
    out = pd.DataFrame({
        "ticker": df[symbol_col].astype(str).str.upper().str.strip(),
        "date": pd.to_datetime(df[date_col], errors="coerce"),
        "price": pd.to_numeric(df[price_col], errors="coerce"),
    })
    out = out[out["date"].notna() & out["price"].notna() & (out["price"] > 0)]
    out = out.sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"], keep="last")
    return out.reset_index(drop=True), price_col


def price_lookup(prices: pd.DataFrame) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    result = {}
    for ticker, group in prices.groupby("ticker", sort=False):
        result[str(ticker)] = (
            group["date"].to_numpy(dtype="datetime64[ns]"),
            group["price"].to_numpy(dtype=float),
        )
    return result


def align(series: tuple[np.ndarray, np.ndarray] | None, as_of: str, horizon: int) -> dict[str, object]:
    if series is None:
        return {"status": "MISSING_TICKER_PRICE_SERIES", "warning": ""}
    dates, values = series
    target = np.datetime64(as_of)
    entry_idx = int(np.searchsorted(dates, target, side="left"))
    if entry_idx >= len(dates):
        return {"status": "MISSING_ENTRY_DATE", "warning": ""}
    forward_idx = entry_idx + horizon
    warning = "ENTRY_ROLLED_FORWARD_TO_NEXT_SESSION" if dates[entry_idx] > target else ""
    base = {
        "entry_date": pd.Timestamp(dates[entry_idx]).strftime("%Y-%m-%d"),
        "entry_price": float(values[entry_idx]),
        "warning": warning,
    }
    if forward_idx >= len(dates):
        return {**base, "status": "MISSING_FORWARD_DATE"}
    return {
        **base,
        "forward_date": pd.Timestamp(dates[forward_idx]).strftime("%Y-%m-%d"),
        "forward_price": float(values[forward_idx]),
        "return": float(values[forward_idx] / values[entry_idx] - 1.0),
        "status": "AVAILABLE",
    }


def build_panel(
    scores: pd.DataFrame,
    dates: list[str],
    ticker_lookup: dict[str, tuple[np.ndarray, np.ndarray]],
    benchmark_series: tuple[np.ndarray, np.ndarray],
    ticker_price_field: str,
    benchmark_price_field: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    selected = scores[scores["as_of_date"].isin(dates)].copy()
    selected["technical_only_score"] = pd.to_numeric(selected["technical_only_score"], errors="coerce")
    selected["technical_only_rank"] = pd.to_numeric(selected["technical_only_rank"], errors="coerce")
    if selected["technical_only_rank"].isna().any():
        selected = selected.sort_values(["as_of_date", "technical_only_score", "ticker"], ascending=[True, False, True])
        selected["technical_only_rank"] = selected.groupby("as_of_date").cumcount() + 1
    panel_rows: list[dict[str, object]] = []
    leakage_rows: list[dict[str, object]] = []
    benchmark_cache = {
        (date, window): align(benchmark_series, date, horizon)
        for date in dates for window, horizon in WINDOWS.items()
    }
    for row in selected.itertuples(index=False):
        safe = (
            str(row.family).upper() == "TECHNICAL"
            and str(row.point_in_time_safe).upper() == "TRUE"
            and clean(row.leakage_violation_reason) == ""
            and pd.Timestamp(row.factor_date) <= pd.Timestamp(row.as_of_date)
        )
        for window, horizon in WINDOWS.items():
            ticker_aligned = align(ticker_lookup.get(str(row.ticker)), str(row.as_of_date), horizon)
            benchmark_aligned = benchmark_cache[(str(row.as_of_date), window)]
            included = safe and ticker_aligned.get("status") == "AVAILABLE"
            leakage_reason = "" if safe else "R4_PANEL_ROW_NOT_POINT_IN_TIME_SAFE"
            panel_rows.append({
                "as_of_date": row.as_of_date,
                "ticker": row.ticker,
                "family": "TECHNICAL",
                "technical_only_score": row.technical_only_score,
                "technical_only_rank": row.technical_only_rank,
                "forward_return_window": window,
                "price_source_path": relative(TICKER_PRICES),
                "price_field": ticker_price_field,
                "price_entry_date": ticker_aligned.get("entry_date", ""),
                "forward_price_date": ticker_aligned.get("forward_date", ""),
                "entry_price": ticker_aligned.get("entry_price", ""),
                "forward_price": ticker_aligned.get("forward_price", ""),
                "realized_forward_return": ticker_aligned.get("return", ""),
                "price_alignment_status": ticker_aligned.get("status", ""),
                "price_alignment_warning": ticker_aligned.get("warning", ""),
                "benchmark_symbol": "QQQ",
                "benchmark_source_path": relative(QQQ_PRICES),
                "benchmark_price_field": benchmark_price_field,
                "benchmark_entry_date": benchmark_aligned.get("entry_date", ""),
                "benchmark_forward_date": benchmark_aligned.get("forward_date", ""),
                "benchmark_forward_return": benchmark_aligned.get("return", ""),
                "benchmark_alignment_status": benchmark_aligned.get("status", ""),
                "benchmark_alignment_warning": benchmark_aligned.get("warning", ""),
                "point_in_time_safe": "TRUE" if safe else "FALSE",
                "leakage_violation_reason": leakage_reason,
                "included_in_performance_aggregation": "TRUE" if included else "FALSE",
            })
            leakage_rows.append({
                "as_of_date": row.as_of_date,
                "ticker": row.ticker,
                "family": "TECHNICAL",
                "factor_date": row.factor_date,
                "forward_return_window": window,
                "point_in_time_safe": "TRUE" if safe else "FALSE",
                "leakage_violation_reason": leakage_reason,
                "included_in_performance_aggregation": "TRUE" if included else "FALSE",
            })
    return panel_rows, leakage_rows


def per_date_metrics(panel: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    safe = panel[panel["included_in_performance_aggregation"] == "TRUE"].copy()
    safe["realized_forward_return"] = pd.to_numeric(safe["realized_forward_return"], errors="coerce")
    safe["benchmark_forward_return"] = pd.to_numeric(safe["benchmark_forward_return"], errors="coerce")
    safe["technical_only_rank"] = pd.to_numeric(safe["technical_only_rank"], errors="coerce")
    for (date, window), group in safe.groupby(["as_of_date", "forward_return_window"]):
        returns = group["realized_forward_return"].dropna()
        n = len(group)
        decile_n = max(int(math.ceil(n * 0.1)), 1)
        top20 = group[group["technical_only_rank"] <= 20]["realized_forward_return"].dropna()
        top50 = group[group["technical_only_rank"] <= 50]["realized_forward_return"].dropna()
        top_decile = group.nsmallest(decile_n, "technical_only_rank")["realized_forward_return"].dropna()
        bottom_decile = group.nlargest(decile_n, "technical_only_rank")["realized_forward_return"].dropna()
        benchmark = group["benchmark_forward_return"].dropna()
        benchmark_return = float(benchmark.iloc[0]) if not benchmark.empty else np.nan
        ic_group = group[["technical_only_score", "realized_forward_return"]].dropna()
        ic = ic_group.corr(method="spearman").iloc[0, 1] if len(ic_group) >= 3 else np.nan
        rows.append({
            "as_of_date": date,
            "forward_return_window": window,
            "scored_count": n,
            "universe_mean_forward_return": returns.mean(),
            "top20_mean_forward_return": top20.mean(),
            "top20_median_forward_return": top20.median(),
            "top20_hit_rate_absolute": (top20 > 0).mean(),
            "top50_mean_forward_return": top50.mean(),
            "top_decile_mean_forward_return": top_decile.mean(),
            "bottom_decile_mean_forward_return": bottom_decile.mean(),
            "long_short_top_bottom_decile_spread": top_decile.mean() - bottom_decile.mean(),
            "benchmark_forward_return": benchmark_return,
            "top20_excess_vs_universe": top20.mean() - returns.mean(),
            "top20_excess_vs_QQQ": top20.mean() - benchmark_return,
            "top50_excess_vs_universe": top50.mean() - returns.mean(),
            "top50_excess_vs_QQQ": top50.mean() - benchmark_return,
            "top_decile_excess_vs_universe": top_decile.mean() - returns.mean(),
            "top_decile_excess_vs_QQQ": top_decile.mean() - benchmark_return,
            "rank_ic_spearman": ic,
        })
    return rows


def summarize(panel: pd.DataFrame, per_date: pd.DataFrame, leakage: pd.DataFrame, sampled_count: int) -> list[dict[str, object]]:
    rows = []
    for window in WINDOWS:
        dates = per_date[per_date["forward_return_window"] == window].copy()
        raw = panel[panel["forward_return_window"] == window].copy()
        raw["technical_only_rank"] = pd.to_numeric(raw["technical_only_rank"], errors="coerce")
        raw["realized_forward_return"] = pd.to_numeric(raw["realized_forward_return"], errors="coerce")
        raw["benchmark_forward_return"] = pd.to_numeric(raw["benchmark_forward_return"], errors="coerce")
        top20_raw = raw[
            (raw["included_in_performance_aggregation"] == "TRUE")
            & (raw["technical_only_rank"] <= 20)
            & raw["realized_forward_return"].notna()
            & raw["benchmark_forward_return"].notna()
        ]
        rows.append({
            "variant_name": "TECHNICAL_ONLY_MATERIALIZED",
            "forward_return_window": window,
            "sampled_asof_count": sampled_count,
            "benchmark_available_asof_count": int(dates.loc[dates["benchmark_forward_return"].notna(), "as_of_date"].nunique()),
            "total_scored_rows": int((raw["included_in_performance_aggregation"] == "TRUE").sum()),
            "top20_mean_forward_return": dates["top20_mean_forward_return"].mean(),
            "top20_median_forward_return": dates["top20_median_forward_return"].median(),
            "top20_hit_rate_absolute": dates["top20_hit_rate_absolute"].mean(),
            "universe_mean_forward_return": dates["universe_mean_forward_return"].mean(),
            "top20_excess_vs_universe": dates["top20_excess_vs_universe"].mean(),
            "top20_excess_vs_QQQ": dates["top20_excess_vs_QQQ"].mean(),
            "top20_hit_rate_vs_QQQ": (
                top20_raw["realized_forward_return"] > top20_raw["benchmark_forward_return"]
            ).mean() if not top20_raw.empty else np.nan,
            "positive_asof_ratio_vs_QQQ": (dates["top20_excess_vs_QQQ"] > 0).mean() if not dates.empty else np.nan,
            "top50_excess_vs_universe": dates["top50_excess_vs_universe"].mean(),
            "top50_excess_vs_QQQ": dates["top50_excess_vs_QQQ"].mean(),
            "top_decile_excess_vs_universe": dates["top_decile_excess_vs_universe"].mean(),
            "top_decile_excess_vs_QQQ": dates["top_decile_excess_vs_QQQ"].mean(),
            "bottom_decile_mean_forward_return": dates["bottom_decile_mean_forward_return"].mean(),
            "long_short_top_bottom_decile_spread": dates["long_short_top_bottom_decile_spread"].mean(),
            "rank_ic_spearman_mean": dates["rank_ic_spearman"].mean(),
            "rank_ic_spearman_median": dates["rank_ic_spearman"].median(),
            "price_missing_count": int(raw["price_alignment_status"].ne("AVAILABLE").sum()),
            "missing_return_count": int(raw["realized_forward_return"].isna().sum()),
            "benchmark_missing_count": int(
                raw.loc[raw["benchmark_forward_return"].isna(), "as_of_date"].nunique()
            ),
            "leakage_violation_count": int(
                ((leakage["forward_return_window"] == window) & (leakage["point_in_time_safe"] != "TRUE")).sum()
            ),
        })
    return rows


def prior_values() -> dict[str, float]:
    prior = read_csv(PRIOR_BENCHMARK)
    values = dict(PRIOR_FALLBACK)
    if not prior.empty:
        current = prior[prior["variant_name"] == "CURRENT_WEIGHT"]
        for row in current.to_dict("records"):
            value = pd.to_numeric(pd.Series([row.get("top20_excess_vs_benchmark")]), errors="coerce").iloc[0]
            if pd.notna(value):
                values[str(row["forward_return_window"])] = float(value)
    return values


def reproduction_rows(summary: list[dict[str, object]]) -> list[dict[str, object]]:
    prior = prior_values()
    rows = []
    for row in summary:
        window = str(row["forward_return_window"])
        r5 = float(row["top20_excess_vs_QQQ"]) if pd.notna(row["top20_excess_vs_QQQ"]) else np.nan
        previous = prior[window]
        difference = r5 - previous if pd.notna(r5) else np.nan
        absolute = abs(difference) if pd.notna(difference) else np.nan
        if pd.isna(r5):
            status = "MATERIAL_DEVIATION"
        elif absolute <= 0.0025:
            status = "EXACT_OR_NEAR_MATCH"
        elif np.sign(r5) == np.sign(previous) and absolute <= 0.02:
            status = "DIRECTIONALLY_CONSISTENT"
        elif np.sign(r5) == np.sign(previous):
            status = "MATERIAL_DEVIATION"
        else:
            status = "CONTRADICTION"
        rows.append({
            "forward_return_window": window,
            "r5_excess_vs_QQQ": r5,
            "prior_v21_042_r2_excess_vs_QQQ": previous,
            "difference": difference,
            "absolute_difference": absolute,
            "reproduction_status": status,
        })
    return rows


def choose_decision(reproduction: list[dict[str, object]]) -> tuple[str, str]:
    statuses = [row["reproduction_status"] for row in reproduction]
    if "CONTRADICTION" in statuses:
        return DEVIATION_STATUS, NO_SUPPORT
    if "MATERIAL_DEVIATION" in statuses:
        return DEVIATION_STATUS, DIFFERS
    if all(status == "EXACT_OR_NEAR_MATCH" for status in statuses):
        return PASS_STATUS, REPRODUCES
    return PASS_STATUS, DIRECTIONAL


def write_report(decision: dict[str, object], summary: list[dict[str, object]], reproduction: list[dict[str, object]]) -> None:
    metric_lines = "\n".join(
        f"- {row['forward_return_window']}: excess_vs_QQQ={fmt(row['top20_excess_vs_QQQ'])}, "
        f"hit_rate_vs_QQQ={fmt(row['top20_hit_rate_vs_QQQ'])}"
        for row in summary
    )
    repro_lines = "\n".join(
        f"- {row['forward_return_window']}: prior={fmt(row['prior_v21_042_r2_excess_vs_QQQ'])}, "
        f"R5={fmt(row['r5_excess_vs_QQQ'])}, difference={fmt(row['difference'])}, "
        f"status={row['reproduction_status']}"
        for row in reproduction
    )
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Decision
- final_status: {decision['final_status']}
- decision: {decision['decision']}
- R4 technical panel status: {decision['r4_technical_panel_status']}
- technical materialized row count used: {decision['technical_panel_row_count_used']}
- sampled as-of count: {decision['sampled_asof_count']}
- overlap with V21.042-R1 manifest: {decision['sample_manifest_overlap_count']}/{decision['prior_manifest_asof_count']}

## QQQ Results
{metric_lines}

## Reproduction Comparison
{repro_lines}

## Full-Weight Block
This is a Technical-only result. Fundamental, Strategy, Risk, Market Regime, and Data Trust remain unmaterialized. No full-weight score or neutral fill was used.

## Limitations
- Uses local cached ticker and QQQ adjusted-close prices only.
- Forward returns advance by trading sessions independently for each ticker.
- Missing ticker and benchmark returns remain missing and are excluded.
- Technical-only evidence must not be interpreted as full-system evidence.

## Recommended Next Stage
{decision['recommended_next_stage']}

## Guardrails
research_only = TRUE
technical_only_backtest = TRUE
full_weight_rebacktest_allowed_now = FALSE
official_adoption_allowed = FALSE
official_weight_mutation = FALSE
official_ranking_mutation = FALSE
real_book_action_allowed = FALSE
broker_execution_allowed = FALSE
trade_action_allowed = FALSE
shadow_gate_allowed = FALSE
shadow_adoption_allowed = FALSE
"""
    READ_CENTER.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(report, encoding="utf-8")
    CURRENT_REPORT_OUT.write_text(report, encoding="utf-8")


def write_blocked(status: str, reason: str) -> None:
    write_csv(PANEL_OUT, [], PANEL_FIELDS)
    write_csv(SUMMARY_OUT, [], SUMMARY_FIELDS)
    write_csv(QQQ_OUT, [], ["benchmark_symbol", "benchmark_source_path", "benchmark_price_field", "coverage_start", "coverage_end", "benchmark_row_count", "benchmark_missing_count", "source_status"])
    write_csv(REPRO_OUT, [], ["forward_return_window", "r5_excess_vs_QQQ", "prior_v21_042_r2_excess_vs_QQQ", "difference", "absolute_difference", "reproduction_status"])
    write_csv(LEAKAGE_OUT, [], ["as_of_date", "ticker", "family", "factor_date", "forward_return_window", "point_in_time_safe", "leakage_violation_reason", "included_in_performance_aggregation"])
    decision = {
        "stage": STAGE, "final_status": status, "decision": KEEP_BLOCKED,
        "technical_panel_row_count_used": 0, "sampled_asof_count": 0,
        "sample_manifest_overlap_count": 0, "prior_manifest_asof_count": 0,
        "r4_technical_panel_status": reason, "recommended_next_stage": "V21.044-R5B_PRICE_BENCHMARK_SOURCE_REPAIR",
        **guardrails(),
    }
    write_csv(DECISION_OUT, [decision], list(decision.keys()))
    write_report(decision, [], [])
    print(f"final_status={status}")
    print(f"decision={KEEP_BLOCKED}")


def main() -> None:
    BACKTEST.mkdir(parents=True, exist_ok=True)
    ready, reason = validate_r4()
    if not ready:
        write_blocked(R4_BLOCKED, reason)
        return
    scores = read_csv(R4_PANEL)
    panel_dates = sorted(set(scores["as_of_date"].astype(str)))
    dates, sample_source, prior_manifest_count, overlap_count = sample_dates(panel_dates)
    if not dates:
        write_blocked(DATES_BLOCKED, "NO_OVERLAPPING_ELIGIBLE_DATES")
        return
    ticker_prices, ticker_field = normalize_prices(TICKER_PRICES)
    qqq_prices, qqq_field = normalize_prices(QQQ_PRICES, "QQQ")
    if ticker_prices.empty or qqq_prices.empty:
        write_blocked(PRICE_BLOCKED, "LOCAL_TICKER_OR_QQQ_PRICE_SOURCE_INVALID")
        return
    ticker_lookup = price_lookup(ticker_prices)
    qqq_lookup = price_lookup(qqq_prices)
    panel_rows, leakage_rows = build_panel(
        scores, dates, ticker_lookup, qqq_lookup["QQQ"], ticker_field, qqq_field
    )
    panel_df = pd.DataFrame(panel_rows)
    leakage_df = pd.DataFrame(leakage_rows)
    per_date = pd.DataFrame(per_date_metrics(panel_df))
    summary = summarize(panel_df, per_date, leakage_df, len(dates))
    reproduction = reproduction_rows(summary)
    final_status, decision_value = choose_decision(reproduction)
    if prior_manifest_count and overlap_count < prior_manifest_count and final_status == PASS_STATUS:
        final_status = OVERLAP_STATUS

    qqq_rows = [{
        "benchmark_symbol": "QQQ",
        "benchmark_source_path": relative(QQQ_PRICES),
        "benchmark_price_field": qqq_field,
        "coverage_start": qqq_prices["date"].min().strftime("%Y-%m-%d"),
        "coverage_end": qqq_prices["date"].max().strftime("%Y-%m-%d"),
        "benchmark_row_count": len(qqq_prices),
        "benchmark_missing_count": sum(int(row["benchmark_missing_count"]) for row in summary),
        "source_status": "USED_LOCAL_QQQ_SOURCE",
    }]
    statuses = "|".join(f"{row['forward_return_window']}={row['reproduction_status']}" for row in reproduction)
    recommended = (
        "V21.044-R6_TECHNICAL_ONLY_SHADOW_OBSERVATION_CONTINUITY_GATE"
        if decision_value in {REPRODUCES, DIRECTIONAL}
        else "V21.044-R5A_TECHNICAL_REBACKTEST_RECONCILIATION_AUDIT"
    )
    decision = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision_value,
        "r4_technical_panel_status": first_row(R4_DECISION).get("final_status", ""),
        "technical_panel_row_count_used": int(scores[scores["as_of_date"].isin(dates)].shape[0]),
        "sampled_asof_count": len(dates),
        "sample_source": sample_source,
        "sample_seed_if_new": NEW_SAMPLE_SEED if "NEW_" in sample_source else "",
        "sample_manifest_overlap_count": overlap_count,
        "prior_manifest_asof_count": prior_manifest_count,
        "ticker_price_source_path": relative(TICKER_PRICES),
        "ticker_price_field": ticker_field,
        "benchmark_symbol": "QQQ",
        "benchmark_source_path": relative(QQQ_PRICES),
        "benchmark_price_field": qqq_field,
        "reproduction_status_summary": statuses,
        "full_weight_remains_blocked": "TRUE",
        "recommended_next_stage": recommended,
        **guardrails(),
    }
    for row in summary:
        window = row["forward_return_window"]
        decision[f"top20_excess_vs_QQQ_{window}"] = row["top20_excess_vs_QQQ"]
        decision[f"top20_hit_rate_vs_QQQ_{window}"] = row["top20_hit_rate_vs_QQQ"]

    write_csv(PANEL_OUT, panel_rows, PANEL_FIELDS)
    write_csv(SUMMARY_OUT, summary, SUMMARY_FIELDS)
    write_csv(QQQ_OUT, qqq_rows, list(qqq_rows[0].keys()))
    write_csv(REPRO_OUT, reproduction, ["forward_return_window", "r5_excess_vs_QQQ", "prior_v21_042_r2_excess_vs_QQQ", "difference", "absolute_difference", "reproduction_status"])
    write_csv(LEAKAGE_OUT, leakage_rows, ["as_of_date", "ticker", "family", "factor_date", "forward_return_window", "point_in_time_safe", "leakage_violation_reason", "included_in_performance_aggregation"])
    write_csv(DECISION_OUT, [decision], list(decision.keys()))
    write_report(decision, summary, reproduction)

    excess_summary = "|".join(f"{row['forward_return_window']}={fmt(row['top20_excess_vs_QQQ'])}" for row in summary)
    print(f"final_status={final_status}")
    print(f"decision={decision_value}")
    print(f"sampled_asof_count={len(dates)}")
    print(f"qqq_excess_summary={excess_summary}")
    print(f"reproduction_status={statuses}")


if __name__ == "__main__":
    main()
