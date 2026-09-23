#!/usr/bin/env python
"""V20.104 research-only random as-of backtest batch runner.

Samples historical as-of dates deterministically and attaches forward outcome
and benchmark-comparison evidence from local historical price caches. The stage
does not infer historical ranks from current ranks, does not fabricate missing
prices, does not mutate weights, does not create dynamic weights, and does not
execute V20.107.
"""

from __future__ import annotations

import csv
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
STATE_PRICE_CACHE = ROOT / "state" / "v18" / "price_cache"

R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
V98C_AUDIT = CONSOLIDATION / "V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDIT.csv"
V98C_MATRIX = CONSOLIDATION / "V20_98C_ETF_PAIR_RELATIVE_STRENGTH_MATRIX.csv"
V98C_SCAFFOLD = CONSOLIDATION / "V20_98C_ETF_REGIME_FACTOR_MULTIPLIER_SCAFFOLD.csv"
R2_ETF_CACHE = CONSOLIDATION / "V20_98C_R2_CONTROLLED_ETF_PRICE_REFRESH_CACHE.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V48_FACTORS = CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv"
V48_BENCHMARK = CONSOLIDATION / "V20_48_REFRESHED_BENCHMARK_CONTEXT_VIEW.csv"
V50_CANDIDATES = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_BATCH = CONSOLIDATION / "V20_104_RANDOM_ASOF_BACKTEST_BATCH_RUNS.csv"
OUT_INPUT_AUDIT = CONSOLIDATION / "V20_104_RANDOM_ASOF_SNAPSHOT_INPUT_AUDIT.csv"
OUT_OUTCOME = CONSOLIDATION / "V20_104_RANDOM_ASOF_FORWARD_OUTCOME_MATRIX.csv"
OUT_BENCHMARK = CONSOLIDATION / "V20_104_RANDOM_ASOF_BENCHMARK_COMPARISON.csv"
OUT_PIT = CONSOLIDATION / "V20_104_RANDOM_ASOF_PIT_SAFETY_AUDIT.csv"
REPORT = READ_CENTER / "V20_104_RANDOM_ASOF_BACKTEST_BATCH_REPORT.md"

STAGE = "V20.104_RANDOM_ASOF_BACKTEST_BATCH_RUNNER"
PASS_STATUS = "PASS_V20_104_RANDOM_ASOF_BACKTEST_BATCH_RUNNER"
PARTIAL_STATUS = "PARTIAL_PASS_V20_104_RANDOM_ASOF_BACKTEST_BATCH_RUNNER_WITH_LIMITED_HISTORICAL_COVERAGE"
BLOCKED_STATUS = "BLOCKED_V20_104_NO_PIT_SAFE_RANDOM_ASOF_INPUTS"
RANDOM_SEED = 20104
DEFAULT_SAMPLE_COUNT = 30
MIN_SAMPLE_COUNT = 10
FORWARD_WINDOWS = [5, 10, 20, 60, 120]
BENCHMARKS = ["SPY", "QQQ"]

BATCH_FIELDS = [
    "batch_run_id",
    "random_seed",
    "as_of_date",
    "sample_index",
    "snapshot_source_status",
    "candidate_count",
    "factor_context_available",
    "benchmark_context_available",
    "etf_regime_context_available",
    "pit_safety_status",
    "forward_windows_requested",
    "forward_windows_available",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "is_official_weight",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
    "dynamic_factor_weight_created",
    "v20_107_execution_status",
]

INPUT_AUDIT_FIELDS = [
    "input_check_id",
    "source_artifact",
    "artifact_exists",
    "artifact_non_empty",
    "row_count",
    "historical_price_source",
    "pit_safe_for_random_asof",
    "input_status",
    "input_reason",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "is_official_weight",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
    "dynamic_factor_weight_created",
    "v20_107_execution_status",
]

OUTCOME_FIELDS = [
    "batch_run_id",
    "as_of_date",
    "ticker",
    "candidate_rank",
    "candidate_score_source",
    "forward_window",
    "entry_price_asof",
    "exit_price_forward",
    "forward_return",
    "outcome_available",
    "outcome_status",
    "pit_safe",
    "missing_reason",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "is_official_weight",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
    "dynamic_factor_weight_created",
    "v20_107_execution_status",
]

BENCHMARK_FIELDS = [
    "batch_run_id",
    "as_of_date",
    "ticker",
    "forward_window",
    "ticker_forward_return",
    "benchmark_ticker",
    "benchmark_forward_return",
    "alpha_vs_benchmark",
    "relative_outperformance_status",
    "benchmark_data_available",
    "benchmark_missing_reason",
    "pit_safe",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "is_official_weight",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
    "dynamic_factor_weight_created",
    "v20_107_execution_status",
]

PIT_FIELDS = [
    "pit_check_id",
    "as_of_date",
    "ticker",
    "forward_window",
    "snapshot_data_date",
    "forward_outcome_date",
    "snapshot_date_lte_asof",
    "forward_date_gt_asof",
    "future_factor_data_used",
    "pit_safety_status",
    "pit_safety_reason",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "is_official_weight",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
    "dynamic_factor_weight_created",
    "v20_107_execution_status",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def safety(include_weight: bool = False) -> dict[str, str]:
    row = {
        "research_only": "TRUE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
    }
    if include_weight:
        row["is_official_weight"] = "FALSE"
        row["dynamic_factor_weight_created"] = "FALSE"
        row["v20_107_execution_status"] = "NOT_RUN"
    return row


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], str]:
    if not path.exists():
        return [], "MISSING"
    if path.stat().st_size == 0:
        return [], "EMPTY"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [{key: clean(value) for key, value in row.items()} for row in reader]
        return rows, "OK" if reader.fieldnames else "MALFORMED"


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_float(value: object) -> float | None:
    try:
        number = float(clean(value))
    except ValueError:
        return None
    return number if number > 0 else None


def price_file_for(ticker: str) -> Path:
    return STATE_PRICE_CACHE / f"{ticker.upper()}.csv"


def load_price_series(ticker: str) -> dict[str, float]:
    path = price_file_for(ticker)
    rows, status = read_csv(path)
    if status != "OK":
        return {}
    series: dict[str, float] = {}
    for row in rows:
        date = clean(row.get("date") or row.get("price_date"))[:10]
        price = parse_float(row.get("adj_close") or row.get("adjusted_close") or row.get("close"))
        if date and price is not None:
            series[date] = price
    return dict(sorted(series.items()))


def candidate_universe() -> list[str]:
    rows, status = read_csv(V50_CANDIDATES)
    if status != "OK":
        rows, status = read_csv(V48_CANDIDATES)
    seen: set[str] = set()
    tickers: list[str] = []
    for row in rows:
        ticker = clean(row.get("normalized_ticker") or row.get("ticker_or_candidate_id") or row.get("display_name_or_ticker")).upper()
        if ticker and ticker not in seen and price_file_for(ticker).exists():
            seen.add(ticker)
            tickers.append(ticker)
    return tickers


def row_count(path: Path) -> int:
    rows, status = read_csv(path)
    return len(rows) if status == "OK" else 0


def discover_historical_artifacts() -> list[Path]:
    roots = [
        ROOT / "outputs" / "v20",
        ROOT / "outputs" / "v18",
        ROOT / "outputs" / "v19",
        ROOT / "outputs" / "backtest",
        ROOT / "data",
        ROOT / "cache",
        STATE_PRICE_CACHE,
    ]
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        try:
            for path in root.rglob("*.csv"):
                name = path.name.lower()
                if any(token in name for token in ["price", "backtest", "historical", "cache"]):
                    found.append(path)
        except OSError:
            continue
    return sorted(found)


def build_input_audit(tickers: list[str], discovered: list[Path]) -> list[dict[str, str]]:
    required = [
        R5_REGISTRY,
        V98C_AUDIT,
        V98C_MATRIX,
        V98C_SCAFFOLD,
        R2_ETF_CACHE,
        V48_CANDIDATES,
        V48_FACTORS,
        V48_BENCHMARK,
        V50_CANDIDATES,
        V49_RESEARCH,
        V49_OFFICIAL,
        STATE_PRICE_CACHE,
    ]
    rows: list[dict[str, str]] = []
    for index, path in enumerate(required, start=1):
        exists = path.exists()
        non_empty = exists and (path.is_dir() or path.stat().st_size > 0)
        count = len(list(path.glob("*.csv"))) if path.is_dir() else row_count(path)
        historical = path == STATE_PRICE_CACHE
        rows.append(
            {
                "input_check_id": f"V20_104_INPUT_{index:03d}",
                "source_artifact": rel(path),
                "artifact_exists": tf(exists),
                "artifact_non_empty": tf(non_empty),
                "row_count": str(count),
                "historical_price_source": tf(historical),
                "pit_safe_for_random_asof": tf(historical and bool(tickers)),
                "input_status": "PASS" if exists and non_empty else "WARN_MISSING_OR_EMPTY",
                "input_reason": "STATE_V18_PRICE_CACHE_USED_FOR_HISTORICAL_FORWARD_OUTCOMES"
                if historical
                else "CONTEXT_READ_ONLY_NO_WEIGHT_OR_RECOMMENDATION_MUTATION",
                **safety(include_weight=True),
            }
        )
    rows.append(
        {
            "input_check_id": f"V20_104_INPUT_{len(required) + 1:03d}",
            "source_artifact": "DISCOVERED_HISTORICAL_ARTIFACTS",
            "artifact_exists": tf(bool(discovered)),
            "artifact_non_empty": tf(bool(discovered)),
            "row_count": str(len(discovered)),
            "historical_price_source": "TRUE",
            "pit_safe_for_random_asof": tf(bool(tickers)),
            "input_status": "PASS" if discovered else "WARN_NO_DISCOVERED_HISTORICAL_ARTIFACTS",
            "input_reason": "DISCOVERED_LOCAL_HISTORICAL_ARTIFACTS_WITH_STATE_PRICE_CACHE_FALLBACK",
            **safety(include_weight=True),
        }
    )
    return rows


def date_at_offset(dates: list[str], as_of: str, offset: int) -> str:
    try:
        idx = dates.index(as_of)
    except ValueError:
        return ""
    target = idx + offset
    return dates[target] if 0 <= target < len(dates) else ""


def format_return(value: float | None) -> str:
    return "" if value is None else f"{value:.10f}"


def main() -> int:
    batch_run_id = "V20_104_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    discovered = discover_historical_artifacts()
    tickers = candidate_universe()
    benchmark_series = {ticker: load_price_series(ticker) for ticker in BENCHMARKS}
    ticker_series = {ticker: load_price_series(ticker) for ticker in tickers}
    tickers = [ticker for ticker in tickers if ticker_series.get(ticker)]
    input_rows = build_input_audit(tickers, discovered)

    spy_dates = list(benchmark_series.get("SPY", {}).keys())
    qqq_dates = set(benchmark_series.get("QQQ", {}).keys())
    eligible_dates: list[str] = []
    for date in spy_dates:
        if date not in qqq_dates:
            continue
        if all(date_at_offset(spy_dates, date, window) for window in FORWARD_WINDOWS):
            eligible_dates.append(date)
    rng = random.Random(RANDOM_SEED)
    sample_size = min(DEFAULT_SAMPLE_COUNT, len(eligible_dates))
    selected_dates = sorted(rng.sample(eligible_dates, sample_size)) if sample_size else []

    batch_rows: list[dict[str, str]] = []
    outcome_rows: list[dict[str, str]] = []
    benchmark_rows: list[dict[str, str]] = []
    pit_rows: list[dict[str, str]] = []
    outcomes_by_key: dict[tuple[str, str, str, str], str] = {}

    for sample_index, as_of in enumerate(selected_dates, start=1):
        available_windows = [f"{window}D" for window in FORWARD_WINDOWS if date_at_offset(spy_dates, as_of, window)]
        batch_rows.append(
            {
                "batch_run_id": batch_run_id,
                "random_seed": str(RANDOM_SEED),
                "as_of_date": as_of,
                "sample_index": str(sample_index),
                "snapshot_source_status": "PIT_SAFE_PRICE_SNAPSHOT_ONLY_NO_HISTORICAL_RANK_USED",
                "candidate_count": str(len(tickers)),
                "factor_context_available": "FALSE",
                "benchmark_context_available": tf(bool(benchmark_series.get("SPY")) and bool(benchmark_series.get("QQQ"))),
                "etf_regime_context_available": tf(row_count(V98C_AUDIT) > 0 and row_count(R2_ETF_CACHE) > 0),
                "pit_safety_status": "PASS",
                "forward_windows_requested": "|".join(f"{window}D" for window in FORWARD_WINDOWS),
                "forward_windows_available": "|".join(available_windows),
                **safety(include_weight=True),
            }
        )
        for ticker in tickers:
            series = ticker_series[ticker]
            entry = series.get(as_of)
            for window in FORWARD_WINDOWS:
                window_label = f"{window}D"
                exit_date = date_at_offset(spy_dates, as_of, window)
                exit_price = series.get(exit_date) if exit_date else None
                pit_safe = bool(entry is not None and exit_date and exit_date > as_of)
                outcome_available = entry is not None and exit_price is not None and pit_safe
                forward_return = (exit_price / entry - 1) if outcome_available and entry else None
                missing_reason = "" if outcome_available else "MISSING_ENTRY_OR_FORWARD_PRICE"
                outcome_rows.append(
                    {
                        "batch_run_id": batch_run_id,
                        "as_of_date": as_of,
                        "ticker": ticker,
                        "candidate_rank": "UNRANKED",
                        "candidate_score_source": "NO_HISTORICAL_RANK_OR_SCORE_USED",
                        "forward_window": window_label,
                        "entry_price_asof": "" if entry is None else str(entry),
                        "exit_price_forward": "" if exit_price is None else str(exit_price),
                        "forward_return": format_return(forward_return),
                        "outcome_available": tf(outcome_available),
                        "outcome_status": "PASS" if outcome_available else "MISSING_HISTORICAL_PRICE_COVERAGE",
                        "pit_safe": tf(pit_safe),
                        "missing_reason": missing_reason,
                        **safety(include_weight=True),
                    }
                )
                outcomes_by_key[(as_of, ticker, window_label, "RETURN")] = format_return(forward_return)
                pit_rows.append(
                    {
                        "pit_check_id": f"V20_104_PIT_{len(pit_rows) + 1:06d}",
                        "as_of_date": as_of,
                        "ticker": ticker,
                        "forward_window": window_label,
                        "snapshot_data_date": as_of if entry is not None else "",
                        "forward_outcome_date": exit_date,
                        "snapshot_date_lte_asof": tf(entry is not None),
                        "forward_date_gt_asof": tf(pit_safe),
                        "future_factor_data_used": "FALSE",
                        "pit_safety_status": "PASS" if pit_safe else "BLOCKED",
                        "pit_safety_reason": "SNAPSHOT_DATE_LTE_ASOF_AND_FORWARD_DATE_GT_ASOF"
                        if pit_safe
                        else "MISSING_SNAPSHOT_PRICE_OR_NON_FORWARD_OUTCOME_DATE",
                        **safety(include_weight=True),
                    }
                )
                for benchmark in BENCHMARKS:
                    bench_series = benchmark_series.get(benchmark, {})
                    bench_entry = bench_series.get(as_of)
                    bench_exit = bench_series.get(exit_date) if exit_date else None
                    bench_available = bench_entry is not None and bench_exit is not None and pit_safe
                    bench_return = (bench_exit / bench_entry - 1) if bench_available and bench_entry else None
                    alpha = forward_return - bench_return if forward_return is not None and bench_return is not None else None
                    benchmark_rows.append(
                        {
                            "batch_run_id": batch_run_id,
                            "as_of_date": as_of,
                            "ticker": ticker,
                            "forward_window": window_label,
                            "ticker_forward_return": format_return(forward_return),
                            "benchmark_ticker": benchmark,
                            "benchmark_forward_return": format_return(bench_return),
                            "alpha_vs_benchmark": format_return(alpha),
                            "relative_outperformance_status": "OUTPERFORMED"
                            if alpha is not None and alpha > 0
                            else ("UNDERPERFORMED_OR_EQUAL" if alpha is not None else "NOT_AVAILABLE"),
                            "benchmark_data_available": tf(bench_available),
                            "benchmark_missing_reason": "" if bench_available else "MISSING_BENCHMARK_ENTRY_OR_FORWARD_PRICE",
                            "pit_safe": tf(pit_safe),
                            **safety(include_weight=True),
                        }
                    )

    if not selected_dates:
        status = BLOCKED_STATUS
    elif len(selected_dates) < MIN_SAMPLE_COUNT:
        status = PARTIAL_STATUS
    elif any(row["outcome_available"] != "TRUE" for row in outcome_rows):
        status = PARTIAL_STATUS
    else:
        status = PASS_STATUS

    write_csv(OUT_BATCH, BATCH_FIELDS, batch_rows)
    write_csv(OUT_INPUT_AUDIT, INPUT_AUDIT_FIELDS, input_rows)
    write_csv(OUT_OUTCOME, OUTCOME_FIELDS, outcome_rows)
    write_csv(OUT_BENCHMARK, BENCHMARK_FIELDS, benchmark_rows)
    write_csv(OUT_PIT, PIT_FIELDS, pit_rows)

    report_lines = [
        "# V20.104 Random As-Of Backtest Batch Runner",
        "",
        "## Current Result",
        f"- wrapper_status: {status}",
        f"- batch_run_id: {batch_run_id}",
        f"- random_seed: {RANDOM_SEED}",
        f"- selected_sample_count: {len(selected_dates)}",
        f"- candidate_symbol_count: {len(tickers)}",
        f"- forward_windows: {'|'.join(f'{window}D' for window in FORWARD_WINDOWS)}",
        f"- forward_outcome_rows: {len(outcome_rows)}",
        f"- benchmark_comparison_rows: {len(benchmark_rows)}",
        f"- pit_safety_rows: {len(pit_rows)}",
        "- V20.107: NOT_RUN",
        "",
        "## PIT Safety",
        "- snapshot data date is constrained to as_of_date or earlier.",
        "- forward outcome dates are required to be after as_of_date.",
        "- current candidate ranks are not used as historical ranks.",
        "- factor_context_available: FALSE",
        "",
        "## Safety Boundary",
        "- research_only: TRUE",
        "- official_promotion_allowed: FALSE",
        "- official_recommendation_created: FALSE",
        "- is_official_weight: FALSE",
        "- weight_mutated: FALSE",
        "- trade_action_created: FALSE",
        "- broker_execution_supported: FALSE",
        "- dynamic_factor_weight_created: FALSE",
        "- v20_107_execution_status: NOT_RUN",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(status)
    print(f"BATCH_RUN_ID={batch_run_id}")
    print(f"RANDOM_SEED={RANDOM_SEED}")
    print(f"SAMPLE_COUNT={len(selected_dates)}")
    print(f"CANDIDATE_COUNT={len(tickers)}")
    print(f"FORWARD_WINDOWS={'|'.join(f'{window}D' for window in FORWARD_WINDOWS)}")
    print(f"FORWARD_OUTCOME_ROWS={len(outcome_rows)}")
    print(f"BENCHMARK_COMPARISON_ROWS={len(benchmark_rows)}")
    print(f"PIT_SAFETY_ROWS={len(pit_rows)}")
    print("DYNAMIC_FACTOR_WEIGHT_CREATED=FALSE")
    print("V20_107_EXECUTION_STATUS=NOT_RUN")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print(f"OUTPUT_BATCH_RUNS={rel(OUT_BATCH)}")
    print(f"OUTPUT_INPUT_AUDIT={rel(OUT_INPUT_AUDIT)}")
    print(f"OUTPUT_FORWARD_OUTCOME={rel(OUT_OUTCOME)}")
    print(f"OUTPUT_BENCHMARK_COMPARISON={rel(OUT_BENCHMARK)}")
    print(f"OUTPUT_PIT_AUDIT={rel(OUT_PIT)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
