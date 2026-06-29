#!/usr/bin/env python
"""Research-only Nasdaq benchmark comparator for the V21.042-R1 backtest."""

from __future__ import annotations

import csv
import hashlib
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.042-R2_CURRENT_WEIGHT_RANDOM_ASOF_BENCHMARK_COMPARATOR"
PASS_STATUS = "PASS_V21_042_R2_CURRENT_WEIGHT_BENCHMARK_COMPARISON_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_042_R2_BENCHMARK_COMPARISON_LIMITED_COVERAGE"
BLOCKED_SOURCE_STATUS = "BLOCKED_V21_042_R2_BENCHMARK_SOURCE_NOT_FOUND"
BLOCKED_UPSTREAM_STATUS = "BLOCKED_V21_042_R2_UPSTREAM_BACKTEST_NOT_READY"

BEATS = "CURRENT_WEIGHT_BEATS_NASDAQ_BENCHMARK_RESEARCH_ONLY"
LAGS = "CURRENT_WEIGHT_LAGS_NASDAQ_BENCHMARK_RESEARCH_ONLY"
INCONCLUSIVE = "CURRENT_WEIGHT_VS_NASDAQ_INCONCLUSIVE_RESEARCH_ONLY"
BLOCKED = "BENCHMARK_COMPARISON_BLOCKED"

ROOT = Path(__file__).resolve().parents[2]
BACKTEST_DIR = ROOT / "outputs" / "v21" / "backtest"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

UPSTREAM = {
    "manifest": BACKTEST_DIR / "V21_042_R1_RANDOM_ASOF_SAMPLE_MANIFEST.csv",
    "panel": BACKTEST_DIR / "V21_042_R1_RANDOM_ASOF_BACKTEST_PANEL.csv",
    "per_date": BACKTEST_DIR / "V21_042_R1_RANDOM_ASOF_PER_DATE_METRICS.csv",
    "window_summary": BACKTEST_DIR / "V21_042_R1_RANDOM_ASOF_VARIANT_WINDOW_SUMMARY.csv",
    "decision": BACKTEST_DIR / "V21_042_R1_RANDOM_ASOF_DECISION_SUMMARY.csv",
    "leakage": BACKTEST_DIR / "V21_042_R1_RANDOM_ASOF_LEAKAGE_AUDIT.csv",
}

SOURCE_AUDIT_OUT = BACKTEST_DIR / "V21_042_R2_BENCHMARK_SOURCE_AUDIT.csv"
PANEL_OUT = BACKTEST_DIR / "V21_042_R2_RANDOM_ASOF_BENCHMARK_PANEL.csv"
SUMMARY_OUT = BACKTEST_DIR / "V21_042_R2_VARIANT_WINDOW_BENCHMARK_SUMMARY.csv"
PER_DATE_OUT = BACKTEST_DIR / "V21_042_R2_PER_DATE_BENCHMARK_COMPARISON.csv"
DECISION_OUT = BACKTEST_DIR / "V21_042_R2_BENCHMARK_DECISION_SUMMARY.csv"
REPORT_OUT = READ_CENTER_DIR / "V21_042_R2_CURRENT_WEIGHT_RANDOM_ASOF_BENCHMARK_COMPARATOR_REPORT.md"
CURRENT_REPORT_OUT = READ_CENTER_DIR / "CURRENT_V21_042_R2_CURRENT_WEIGHT_RANDOM_ASOF_BENCHMARK_COMPARATOR_REPORT.md"

WINDOWS = ["5D", "10D", "20D", "60D"]
VARIANTS = [
    "CURRENT_WEIGHT",
    "EQUAL_WEIGHT_BASELINE",
    "GLOBAL_RSI_CANDIDATE",
    "CURRENT_WEIGHT_PLUS_RSI_CANDIDATE",
]
CANONICAL_BENCHMARK_PRICES = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"
NORMALIZED_HISTORICAL_PRICES = ROOT / "outputs" / "v21" / "factors" / "V21_036_R1_HISTORICAL_OHLCV_NORMALIZED.csv"
BENCHMARK_CANDIDATES = [
    ("QQQ", CANONICAL_BENCHMARK_PRICES),
    ("QQQ", NORMALIZED_HISTORICAL_PRICES),
    ("NDX", CANONICAL_BENCHMARK_PRICES),
    ("NDX", NORMALIZED_HISTORICAL_PRICES),
    ("IXIC", CANONICAL_BENCHMARK_PRICES),
    ("IXIC", NORMALIZED_HISTORICAL_PRICES),
    ("^IXIC", CANONICAL_BENCHMARK_PRICES),
    ("^IXIC", NORMALIZED_HISTORICAL_PRICES),
    ("NASDAQ", CANONICAL_BENCHMARK_PRICES),
    ("NASDAQ", NORMALIZED_HISTORICAL_PRICES),
]

SOURCE_FIELDS = [
    "benchmark_symbol", "source_path", "source_status", "price_field", "source_row_count",
    "date_coverage_start", "date_coverage_end", "required_alignment_count",
    "available_alignment_count", "missing_date_count", "source_sha256", "notes",
]
PANEL_FIELDS = [
    "variant_name", "as_of_date", "forward_return_window", "benchmark_symbol",
    "benchmark_source_path", "benchmark_price_field", "benchmark_entry_date",
    "benchmark_forward_date", "benchmark_entry_price", "benchmark_forward_price",
    "benchmark_forward_return", "benchmark_alignment_status", "benchmark_alignment_warning",
    "top20_mean_forward_return", "top20_excess_vs_benchmark",
    "top50_mean_forward_return", "top50_excess_vs_benchmark",
    "top_decile_mean_forward_return", "top_decile_excess_vs_benchmark",
    "long_short_top_bottom_decile_spread", "long_short_spread_vs_benchmark",
]
SUMMARY_FIELDS = [
    "variant_name", "forward_return_window", "sampled_asof_count",
    "benchmark_available_asof_count", "top20_mean_forward_return",
    "benchmark_mean_forward_return", "top20_excess_vs_benchmark",
    "top20_median_excess_vs_benchmark", "top20_hit_rate_vs_benchmark",
    "positive_asof_ratio_vs_benchmark", "top50_excess_vs_benchmark",
    "top_decile_excess_vs_benchmark", "long_short_spread_vs_benchmark",
    "current_weight_vs_equal_weight_vs_benchmark_delta",
    "current_weight_plus_rsi_vs_current_weight_vs_benchmark_delta",
    "benchmark_missing_count", "benchmark_alignment_warning_count",
]


def fmt(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, (float, np.floating)):
        if not math.isfinite(float(value)):
            return ""
        return f"{float(value):.10f}"
    return value


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def first_row(path: Path) -> dict[str, str]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.DictReader(handle), {}) or {}


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def guardrails() -> dict[str, str]:
    return {
        "research_only": "TRUE",
        "official_adoption_allowed": "FALSE",
        "official_weight_mutation": "FALSE",
        "official_ranking_mutation": "FALSE",
        "real_book_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE",
        "shadow_adoption_allowed": "FALSE",
    }


def validate_upstream() -> tuple[bool, str]:
    missing = [relative(path) for path in UPSTREAM.values() if not path.exists() or path.stat().st_size == 0]
    if missing:
        return False, "MISSING_UPSTREAM_FILES=" + "|".join(missing)
    decision = first_row(UPSTREAM["decision"])
    if decision.get("final_status") != "PASS_V21_042_R1_CURRENT_WEIGHT_RANDOM_ASOF_BACKTEST_READY":
        return False, "UPSTREAM_FINAL_STATUS=" + decision.get("final_status", "MISSING")
    return True, "PASS_UPSTREAM_READY"


def normalize_price_source(path: Path, symbol: str) -> tuple[pd.DataFrame, str]:
    df = pd.read_csv(path, low_memory=False)
    names = {column.lower(): column for column in df.columns}
    symbol_col = names.get("symbol") or names.get("ticker")
    date_col = names.get("date") or names.get("as_of_date") or names.get("price_date")
    if not symbol_col or not date_col:
        return pd.DataFrame(), ""
    selected = df[df[symbol_col].astype(str).str.upper().str.strip() == symbol].copy()
    selected["benchmark_date"] = pd.to_datetime(selected[date_col], errors="coerce")
    adjusted_col = names.get("adjusted_close") or names.get("adj_close") or names.get("latest_adj_close")
    close_col = names.get("close") or names.get("latest_close") or names.get("close_like_price")
    price_field = ""
    if adjusted_col:
        adjusted = pd.to_numeric(selected[adjusted_col], errors="coerce")
        if (adjusted > 0).sum() >= 2:
            selected["benchmark_price"] = adjusted
            price_field = adjusted_col
    if not price_field and close_col:
        close = pd.to_numeric(selected[close_col], errors="coerce")
        if (close > 0).sum() >= 2:
            selected["benchmark_price"] = close
            price_field = close_col
    if not price_field:
        return pd.DataFrame(), ""
    selected = selected[
        selected["benchmark_date"].notna()
        & selected["benchmark_price"].notna()
        & (selected["benchmark_price"] > 0)
    ][["benchmark_date", "benchmark_price"]]
    selected = selected.sort_values("benchmark_date").drop_duplicates("benchmark_date", keep="last")
    return selected.reset_index(drop=True), price_field


def resolve_benchmark() -> tuple[str, Path | None, pd.DataFrame, str, list[dict[str, object]]]:
    audits: list[dict[str, object]] = []
    for symbol, path in BENCHMARK_CANDIDATES:
        if not path.exists():
            audits.append({
                "benchmark_symbol": symbol, "source_path": relative(path),
                "source_status": "CANDIDATE_NOT_FOUND", "notes": "Local candidate does not exist.",
            })
            continue
        try:
            prices, price_field = normalize_price_source(path, symbol)
        except (OSError, ValueError, pd.errors.ParserError) as exc:
            audits.append({
                "benchmark_symbol": symbol, "source_path": relative(path),
                "source_status": "CANDIDATE_READ_ERROR", "source_sha256": sha256(path),
                "notes": type(exc).__name__,
            })
            continue
        if len(prices) < 2:
            audits.append({
                "benchmark_symbol": symbol, "source_path": relative(path),
                "source_status": "CANDIDATE_NO_VALID_DAILY_PRICES", "source_sha256": sha256(path),
                "source_row_count": len(prices), "notes": "No usable positive adjusted-close or close series.",
            })
            continue
        audits.append({
            "benchmark_symbol": symbol, "source_path": relative(path), "source_status": "USED_LOCAL_BENCHMARK_SOURCE",
            "price_field": price_field, "source_row_count": len(prices),
            "date_coverage_start": prices["benchmark_date"].min().strftime("%Y-%m-%d"),
            "date_coverage_end": prices["benchmark_date"].max().strftime("%Y-%m-%d"),
            "source_sha256": sha256(path),
            "notes": "Adjusted close preferred; close used only when adjusted close is unavailable.",
        })
        return symbol, path, prices, price_field, audits
    return "", None, pd.DataFrame(), "", audits


def alignment(prices: pd.DataFrame, as_of_date: str, window: str) -> dict[str, object]:
    horizon = int(window[:-1])
    target = pd.Timestamp(as_of_date)
    eligible = prices.index[prices["benchmark_date"] >= target].tolist()
    if not eligible:
        return {
            "benchmark_alignment_status": "MISSING_ENTRY_DATE",
            "benchmark_alignment_warning": "NO_BENCHMARK_DATE_ON_OR_AFTER_AS_OF_DATE",
        }
    entry_idx = eligible[0]
    forward_idx = entry_idx + horizon
    entry = prices.iloc[entry_idx]
    warning = ""
    if entry["benchmark_date"] > target:
        warning = "ENTRY_ROLLED_FORWARD_TO_NEXT_BENCHMARK_SESSION"
    if forward_idx >= len(prices):
        return {
            "benchmark_entry_date": entry["benchmark_date"].strftime("%Y-%m-%d"),
            "benchmark_entry_price": float(entry["benchmark_price"]),
            "benchmark_alignment_status": "MISSING_FORWARD_DATE",
            "benchmark_alignment_warning": warning or "INSUFFICIENT_FORWARD_BENCHMARK_SESSIONS",
        }
    forward = prices.iloc[forward_idx]
    return {
        "benchmark_entry_date": entry["benchmark_date"].strftime("%Y-%m-%d"),
        "benchmark_forward_date": forward["benchmark_date"].strftime("%Y-%m-%d"),
        "benchmark_entry_price": float(entry["benchmark_price"]),
        "benchmark_forward_price": float(forward["benchmark_price"]),
        "benchmark_forward_return": float(forward["benchmark_price"] / entry["benchmark_price"] - 1.0),
        "benchmark_alignment_status": "AVAILABLE",
        "benchmark_alignment_warning": warning,
    }


def number(row: pd.Series | dict[str, object], key: str) -> float:
    value = pd.to_numeric(row.get(key), errors="coerce")
    return float(value) if pd.notna(value) else np.nan


def build_outputs(
    symbol: str,
    source_path: Path,
    prices: pd.DataFrame,
    price_field: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], int]:
    metrics = pd.read_csv(UPSTREAM["per_date"], low_memory=False)
    metrics = metrics[metrics["variant_name"].isin(VARIANTS) & metrics["forward_return_window"].isin(WINDOWS)].copy()
    alignments: dict[tuple[str, str], dict[str, object]] = {}
    for date, window in metrics[["as_of_date", "forward_return_window"]].drop_duplicates().itertuples(index=False):
        alignments[(str(date), str(window))] = alignment(prices, str(date), str(window))

    per_date_rows: list[dict[str, object]] = []
    for _, r in metrics.iterrows():
        aligned = alignments[(str(r["as_of_date"]), str(r["forward_return_window"]))]
        benchmark_return = number(aligned, "benchmark_forward_return")
        top20 = number(r, "mean_forward_return_top20")
        top50 = number(r, "mean_forward_return_top50")
        top_decile = number(r, "mean_forward_return_top_decile")
        spread = number(r, "long_short_top_bottom_decile_spread")
        row = {
            "variant_name": r["variant_name"],
            "as_of_date": r["as_of_date"],
            "forward_return_window": r["forward_return_window"],
            "benchmark_symbol": symbol,
            "benchmark_source_path": relative(source_path),
            "benchmark_price_field": price_field,
            **aligned,
            "top20_mean_forward_return": top20,
            "top20_excess_vs_benchmark": top20 - benchmark_return,
            "top50_mean_forward_return": top50,
            "top50_excess_vs_benchmark": top50 - benchmark_return,
            "top_decile_mean_forward_return": top_decile,
            "top_decile_excess_vs_benchmark": top_decile - benchmark_return,
            "long_short_top_bottom_decile_spread": spread,
            "long_short_spread_vs_benchmark": spread - benchmark_return,
        }
        per_date_rows.append(row)

    panel_rows = list(per_date_rows)
    per_date = pd.DataFrame(per_date_rows)
    raw_panel = pd.read_csv(UPSTREAM["panel"], low_memory=False)
    raw_panel = raw_panel[raw_panel["variant_name"].isin(VARIANTS)].copy()
    raw_panel["rank"] = pd.to_numeric(raw_panel["rank"], errors="coerce")
    raw_panel["realized_forward_return"] = pd.to_numeric(raw_panel["realized_forward_return"], errors="coerce")
    constituent_hits: dict[tuple[str, str], float] = {}
    for (variant, window), group in raw_panel.groupby(["variant_name", "forward_return_window"]):
        comparisons: list[pd.Series] = []
        for date, date_group in group[group["rank"] <= 20].groupby("as_of_date"):
            benchmark_return = number(alignments.get((str(date), str(window)), {}), "benchmark_forward_return")
            if pd.notna(benchmark_return):
                comparisons.append(date_group["realized_forward_return"].dropna() > benchmark_return)
        if comparisons:
            constituent_hits[(variant, window)] = float(pd.concat(comparisons).mean())

    summary_rows: list[dict[str, object]] = []
    for (variant, window), group in per_date.groupby(["variant_name", "forward_return_window"]):
        available = group[pd.to_numeric(group["benchmark_forward_return"], errors="coerce").notna()].copy()
        excess20 = pd.to_numeric(available["top20_excess_vs_benchmark"], errors="coerce")
        row = {
            "variant_name": variant,
            "forward_return_window": window,
            "sampled_asof_count": int(group["as_of_date"].nunique()),
            "benchmark_available_asof_count": int(available["as_of_date"].nunique()),
            "top20_mean_forward_return": pd.to_numeric(available["top20_mean_forward_return"], errors="coerce").mean(),
            "benchmark_mean_forward_return": pd.to_numeric(available["benchmark_forward_return"], errors="coerce").mean(),
            "top20_excess_vs_benchmark": excess20.mean(),
            "top20_median_excess_vs_benchmark": excess20.median(),
            "top20_hit_rate_vs_benchmark": constituent_hits.get((variant, window), np.nan),
            "positive_asof_ratio_vs_benchmark": (excess20 > 0).mean() if excess20.notna().any() else np.nan,
            "top50_excess_vs_benchmark": pd.to_numeric(available["top50_excess_vs_benchmark"], errors="coerce").mean(),
            "top_decile_excess_vs_benchmark": pd.to_numeric(available["top_decile_excess_vs_benchmark"], errors="coerce").mean(),
            "long_short_spread_vs_benchmark": pd.to_numeric(available["long_short_spread_vs_benchmark"], errors="coerce").mean(),
            "benchmark_missing_count": int(group["benchmark_forward_return"].isna().sum()),
            "benchmark_alignment_warning_count": int(group["benchmark_alignment_warning"].fillna("").ne("").sum()),
        }
        summary_rows.append(row)

    lookup = {(r["variant_name"], r["forward_return_window"]): r for r in summary_rows}
    for row in summary_rows:
        window = row["forward_return_window"]
        current = lookup.get(("CURRENT_WEIGHT", window), {})
        equal = lookup.get(("EQUAL_WEIGHT_BASELINE", window), {})
        plus = lookup.get(("CURRENT_WEIGHT_PLUS_RSI_CANDIDATE", window), {})
        row["current_weight_vs_equal_weight_vs_benchmark_delta"] = (
            number(current, "top20_excess_vs_benchmark") - number(equal, "top20_excess_vs_benchmark")
        )
        row["current_weight_plus_rsi_vs_current_weight_vs_benchmark_delta"] = (
            number(plus, "top20_excess_vs_benchmark") - number(current, "top20_excess_vs_benchmark")
        )
    total_missing = sum(int(r["benchmark_missing_count"]) for r in summary_rows)
    return panel_rows, per_date_rows, summary_rows, total_missing


def choose_decision(summary_rows: list[dict[str, object]]) -> str:
    current = {
        row["forward_return_window"]: number(row, "top20_excess_vs_benchmark")
        for row in summary_rows if row["variant_name"] == "CURRENT_WEIGHT"
    }
    core = [current[w] for w in ["5D", "10D", "20D"] if w in current and pd.notna(current[w])]
    if len(core) < 2:
        return INCONCLUSIVE
    positive = sum(value > 0 for value in core)
    negative = sum(value < 0 for value in core)
    if float(np.mean(core)) > 0 and positive >= 2:
        return BEATS
    if float(np.mean(core)) < 0 and negative >= 2:
        return LAGS
    return INCONCLUSIVE


def decision_row(
    final_status: str,
    decision: str,
    symbol: str = "",
    source_path: Path | None = None,
    price_field: str = "",
    summary_rows: list[dict[str, object]] | None = None,
    notes: str = "",
) -> dict[str, object]:
    summary_rows = summary_rows or []
    current = [r for r in summary_rows if r.get("variant_name") == "CURRENT_WEIGHT"]
    return {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        **guardrails(),
        "benchmark_symbol": symbol,
        "benchmark_source_path": relative(source_path) if source_path else "",
        "benchmark_price_field": price_field,
        "benchmark_date_coverage_start": "",
        "benchmark_date_coverage_end": "",
        "benchmark_missing_count": sum(int(r.get("benchmark_missing_count", 0)) for r in current),
        "current_weight_top20_excess_vs_benchmark_5D": next((r["top20_excess_vs_benchmark"] for r in current if r["forward_return_window"] == "5D"), ""),
        "current_weight_top20_excess_vs_benchmark_10D": next((r["top20_excess_vs_benchmark"] for r in current if r["forward_return_window"] == "10D"), ""),
        "current_weight_top20_excess_vs_benchmark_20D": next((r["top20_excess_vs_benchmark"] for r in current if r["forward_return_window"] == "20D"), ""),
        "current_weight_top20_excess_vs_benchmark_60D": next((r["top20_excess_vs_benchmark"] for r in current if r["forward_return_window"] == "60D"), ""),
        "notes": notes,
    }


def write_report(decision: dict[str, object], summary_rows: list[dict[str, object]]) -> None:
    lines = []
    for row in summary_rows:
        lines.append(
            f"- {row['variant_name']} {row['forward_return_window']}: "
            f"top20_excess={fmt(row.get('top20_excess_vs_benchmark'))}, "
            f"hit_rate={fmt(row.get('top20_hit_rate_vs_benchmark'))}, "
            f"available={row.get('benchmark_available_asof_count', 0)}/{row.get('sampled_asof_count', 0)}"
        )
    table = "\n".join(lines) if lines else "- Benchmark comparison unavailable."
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Result
- final_status: {decision['final_status']}
- decision: {decision['decision']}
- benchmark_symbol: {decision['benchmark_symbol']}
- benchmark_source_path: {decision['benchmark_source_path']}
- benchmark_price_field: {decision['benchmark_price_field']}

## Variant/window comparison
{table}

## Method
- Local cached daily benchmark prices only.
- Entry is the first benchmark session on or after the sampled as-of date.
- Forward date is N benchmark trading sessions after entry for 5D, 10D, 20D, and 60D.
- Missing benchmark observations remain missing and are never replaced with zero.
- `top20_hit_rate_vs_benchmark` is constituent-level; `positive_asof_ratio_vs_benchmark` is date-level.

## Guardrails
research_only = TRUE
official_adoption_allowed = FALSE
official_weight_mutation = FALSE
official_ranking_mutation = FALSE
real_book_action_allowed = FALSE
broker_execution_allowed = FALSE
trade_action_allowed = FALSE
shadow_gate_allowed = FALSE
shadow_adoption_allowed = FALSE
"""
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(report, encoding="utf-8")
    CURRENT_REPORT_OUT.write_text(report, encoding="utf-8")


def write_blocked(status: str, notes: str, source_rows: list[dict[str, object]]) -> None:
    if not source_rows:
        source_rows = [{
            "benchmark_symbol": "", "source_path": "", "source_status": "BLOCKED",
            "notes": notes,
        }]
    write_csv(SOURCE_AUDIT_OUT, source_rows, SOURCE_FIELDS)
    write_csv(PANEL_OUT, [], PANEL_FIELDS)
    write_csv(PER_DATE_OUT, [], PANEL_FIELDS)
    write_csv(SUMMARY_OUT, [], SUMMARY_FIELDS)
    decision = decision_row(status, BLOCKED, notes=notes)
    write_csv(DECISION_OUT, [decision], list(decision.keys()))
    write_report(decision, [])
    print(f"final_status={status}")
    print(f"decision={BLOCKED}")


def main() -> None:
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    upstream_ok, upstream_notes = validate_upstream()
    if not upstream_ok:
        write_blocked(BLOCKED_UPSTREAM_STATUS, upstream_notes, [])
        return

    symbol, source_path, prices, price_field, source_rows = resolve_benchmark()
    if source_path is None:
        write_blocked(BLOCKED_SOURCE_STATUS, "No valid local QQQ/Nasdaq daily price source was resolved.", source_rows)
        return

    panel_rows, per_date_rows, summary_rows, total_missing = build_outputs(
        symbol, source_path, prices, price_field
    )
    required_count = len({
        (row["as_of_date"], row["forward_return_window"])
        for row in per_date_rows
    })
    available_count = len({
        (row["as_of_date"], row["forward_return_window"])
        for row in per_date_rows if pd.notna(row.get("benchmark_forward_return"))
    })
    used = next(row for row in source_rows if row["source_status"] == "USED_LOCAL_BENCHMARK_SOURCE")
    used["required_alignment_count"] = required_count
    used["available_alignment_count"] = available_count
    used["missing_date_count"] = required_count - available_count

    coverage_ratio = available_count / required_count if required_count else 0.0
    final_status = PASS_STATUS if total_missing == 0 and coverage_ratio == 1.0 else PARTIAL_STATUS
    decision_value = choose_decision(summary_rows) if available_count else INCONCLUSIVE
    decision = decision_row(
        final_status, decision_value, symbol, source_path, price_field, summary_rows,
        notes=f"benchmark_alignment_coverage={available_count}/{required_count}",
    )
    decision["benchmark_date_coverage_start"] = used["date_coverage_start"]
    decision["benchmark_date_coverage_end"] = used["date_coverage_end"]

    write_csv(SOURCE_AUDIT_OUT, source_rows, SOURCE_FIELDS)
    write_csv(PANEL_OUT, panel_rows, PANEL_FIELDS)
    write_csv(PER_DATE_OUT, per_date_rows, PANEL_FIELDS)
    write_csv(SUMMARY_OUT, summary_rows, SUMMARY_FIELDS)
    write_csv(DECISION_OUT, [decision], list(decision.keys()))
    write_report(decision, summary_rows)

    print(f"STAGE_NAME={STAGE}")
    print(f"final_status={final_status}")
    print(f"decision={decision_value}")
    print(f"benchmark_symbol={symbol}")
    print(f"benchmark_source_path={relative(source_path)}")


if __name__ == "__main__":
    main()
