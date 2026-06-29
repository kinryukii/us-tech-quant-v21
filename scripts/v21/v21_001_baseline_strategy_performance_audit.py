#!/usr/bin/env python
"""V21.001 baseline strategy performance audit.

Research-only audit of existing V20 ranking/label artifacts against local
price history. This script intentionally performs no downloads and mutates no
V20 files.
"""

from __future__ import annotations

import csv
import math
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import median


STAGE_NAME = "V21_001_BASELINE_STRATEGY_PERFORMANCE_AUDIT"
ROOT = Path(__file__).resolve().parents[2]
V20_DIR = ROOT / "outputs" / "v20"
AUDIT_DIR = ROOT / "outputs" / "v21" / "audit"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

INPUT_DISCOVERY = AUDIT_DIR / "V21_001_INPUT_DISCOVERY.csv"
RANKING_SNAPSHOT = AUDIT_DIR / "V21_001_BASELINE_RANKING_SNAPSHOT.csv"
FORWARD_ROWS = AUDIT_DIR / "V21_001_FORWARD_OUTCOME_ROWS.csv"
BUCKET_SUMMARY = AUDIT_DIR / "V21_001_BUCKET_PERFORMANCE_SUMMARY.csv"
LABEL_PERFORMANCE = AUDIT_DIR / "V21_001_LABEL_FORWARD_PERFORMANCE.csv"
BENCHMARK_RELATIVE = AUDIT_DIR / "V21_001_BENCHMARK_RELATIVE_PERFORMANCE.csv"
FAILURE_CASES = AUDIT_DIR / "V21_001_FAILURE_CASES_TOP_RANKED.csv"
NEXT_STAGE_GATE = AUDIT_DIR / "V21_001_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER_DIR / "V21_001_BASELINE_STRATEGY_PERFORMANCE_AUDIT_REPORT.md"

ALLOWED_FINAL_STATUSES = {
    "FAIL_V21_001_NO_RANKING_INPUT_FOUND",
    "PARTIAL_PASS_V21_001_DISCOVERY_READY_OUTCOME_DATA_INSUFFICIENT",
    "PARTIAL_PASS_V21_001_LIMITED_OUTCOME_EVIDENCE",
    "PASS_V21_001_BASELINE_AUDIT_READY_FOR_FACTOR_ABLATION",
}
SAFETY_FIELDS = [
    "official_weight_mutated",
    "official_recommendation_created",
    "real_book_signal_created",
    "broker_execution_supported",
    "trade_action_created",
    "shadow_weight_activated",
]
BENCHMARKS = ["QQQ", "SOXX", "SPY"]
LABEL_TERMS = [
    "near-entry",
    "overheat",
    "pullback review",
    "high-rank-not-buyable",
    "buy zone",
    "not buyable",
    "deep pullback",
    "fresh",
    "stale",
]
RANK_BUCKETS = [("Top 5", 5), ("Top 10", 10), ("Top 20", 20), ("Full ranked pool", None)]


def norm(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")


def parse_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() in {"NA", "N/A", "NONE", "NULL", "MISSING"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def parse_int(value: object) -> int | None:
    number = parse_float(value)
    if number is None:
        return None
    return int(number)


def parse_date_value(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10] if fmt != "%Y%m%d" else text[:8], fmt).date()
        except ValueError:
            continue
    return None


def read_header(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle).fieldnames or [])
    except (OSError, UnicodeDecodeError, csv.Error):
        return []


def count_rows(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return max(sum(1 for _ in handle) - 1, 0)
    except (OSError, UnicodeDecodeError):
        return 0


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def detect_field(columns: list[str], candidates: list[str]) -> str | None:
    by_norm = {norm(col): col for col in columns}
    for candidate in candidates:
        if norm(candidate) in by_norm:
            return by_norm[norm(candidate)]
    for col in columns:
        normalized = norm(col)
        if any(norm(candidate) in normalized for candidate in candidates):
            return col
    return None


def artifact_type(path: Path, columns: list[str]) -> str:
    name = path.name.lower()
    if "topn_selection" in name or "topn_selections" in name:
        return "ranking_topn_selection"
    if "candidate" in name or "research_view" in name:
        return "candidate_or_research_view"
    if "ranking" in name or "ranked" in name:
        return "ranking"
    if {"symbol", "date", "close"}.issubset({norm(col) for col in columns}):
        return "price_history"
    return "other_csv"


def is_shadow_or_mutation_artifact(path: Path) -> bool:
    name = str(path).lower()
    return any(token in name for token in ["shadow", "simulated_weight", "dynamic_weight"])


def discover_inputs() -> tuple[list[dict[str, object]], list[Path]]:
    discovery: list[dict[str, object]] = []
    selected: list[Path] = []
    for path in sorted(V20_DIR.rglob("*.csv")) if V20_DIR.exists() else []:
        columns = read_header(path)
        row_count = count_rows(path) if columns else 0
        exists_non_empty = path.exists() and path.stat().st_size > 0 and row_count > 0
        ticker_col = detect_field(columns, ["ticker", "symbol", "ticker_or_candidate_id", "display_name_or_ticker"])
        rank_col = detect_field(columns, ["rank", "report_rank", "pit_lite_rank"])
        score_col = detect_field(columns, ["score", "composite score", "composite_score", "pit_lite_score", "source_rank_or_score"])
        asof_col = detect_field(columns, ["as_of_date", "signal_date", "date", "snapshot_date"])
        atype = artifact_type(path, columns)
        usable = bool(exists_non_empty and ticker_col and (rank_col or score_col) and not is_shadow_or_mutation_artifact(path))
        preferred = usable and (
            atype == "ranking_topn_selection"
            or ("current" in path.name.lower() and atype in {"ranking", "candidate_or_research_view"})
            or ("candidate" in path.name.lower() and "research_view" in path.name.lower())
        )
        if preferred:
            selected.append(path)
        reason = "selected usable non-shadow ranking/candidate artifact" if preferred else "not selected"
        if usable and not preferred:
            reason = "usable but lower-priority ranking/candidate artifact"
        if is_shadow_or_mutation_artifact(path):
            reason = "excluded shadow/dynamic/simulated artifact"
        if not exists_non_empty:
            validation = "EMPTY_OR_HEADER_ONLY"
        elif usable:
            validation = "PASS_USABLE_RANKING_SCHEMA"
        else:
            validation = "NOT_RANKING_SCHEMA"
        discovery.append(
            {
                "artifact_path": str(path.relative_to(ROOT)),
                "artifact_type": atype,
                "exists_non_empty": str(bool(exists_non_empty)).upper(),
                "row_count": row_count,
                "detected_columns": "|".join(columns),
                "selected_for_audit": str(bool(preferred)).upper(),
                "selection_reason": reason,
                "validation_status": validation,
                "_has_asof": bool(asof_col),
            }
        )
    selected_with_asof = [path for path in selected if detect_field(read_header(path), ["as_of_date", "signal_date", "date", "snapshot_date"])]
    return discovery, (selected_with_asof or selected)


def infer_asof_from_path(path: Path) -> str:
    match = re.search(r"(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)", path.name)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()


def labels_from_row(row: dict[str, str], columns: list[str]) -> tuple[list[str], str]:
    label_cols = [
        col for col in columns
        if any(token in norm(col) for token in ["label", "status", "zone", "overheat", "near_entry", "pullback", "buyable", "fresh", "stale"])
    ]
    raw_parts: list[str] = []
    labels: set[str] = set()
    for col in label_cols:
        text = str(row.get(col, "")).strip()
        if not text:
            continue
        raw_parts.append(f"{col}={text}")
        lower_text = text.lower().replace("_", "-")
        lower_col = col.lower().replace("_", "-")
        for term in LABEL_TERMS:
            if term in lower_text or term in lower_col:
                labels.add(term)
        if text.upper() == "TRUE":
            for term in LABEL_TERMS:
                if term in lower_col:
                    labels.add(term)
    return sorted(labels), "; ".join(raw_parts)


def load_ranking_snapshot(paths: list[Path]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for path in paths:
        columns = read_header(path)
        ticker_col = detect_field(columns, ["ticker", "symbol", "ticker_or_candidate_id", "display_name_or_ticker"])
        rank_col = detect_field(columns, ["rank", "report_rank", "pit_lite_rank"])
        score_col = detect_field(columns, ["score", "composite score", "composite_score", "pit_lite_score", "source_rank_or_score"])
        asof_col = detect_field(columns, ["as_of_date", "signal_date", "date", "snapshot_date"])
        if not ticker_col or not (rank_col or score_col):
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle):
                ticker = str(raw.get(ticker_col, "")).strip().upper()
                if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", ticker):
                    continue
                as_of = str(raw.get(asof_col, "")).strip() if asof_col else infer_asof_from_path(path)
                as_of_date = parse_date_value(as_of)
                if not as_of_date:
                    continue
                rank = parse_int(raw.get(rank_col)) if rank_col else None
                score = parse_float(raw.get(score_col)) if score_col else None
                if rank is None and score is None:
                    continue
                source = str(path.relative_to(ROOT))
                key = (as_of_date.isoformat(), ticker, source)
                if key in seen:
                    continue
                seen.add(key)
                detected_labels, raw_status = labels_from_row(raw, columns)
                rows.append(
                    {
                        "as_of_date": as_of_date.isoformat(),
                        "source_artifact": source,
                        "ticker": ticker,
                        "rank": rank if rank is not None else "",
                        "score": "" if score is None else f"{score:.10f}",
                        "detected_score_field": score_col or "",
                        "detected_label_fields": "|".join(detected_labels),
                        "raw_status_summary": raw_status,
                    }
                )
    rows.sort(key=lambda item: (item["as_of_date"], item["source_artifact"], parse_int(item["rank"]) or 999999, str(item["ticker"])))
    # Keep one baseline row per as-of/ticker, preferring lower rank and then higher score.
    best: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        key = (str(row["as_of_date"]), str(row["ticker"]))
        prior = best.get(key)
        if prior is None:
            best[key] = row
            continue
        old_rank = parse_int(prior["rank"]) or 999999
        new_rank = parse_int(row["rank"]) or 999999
        old_score = parse_float(prior["score"]) or -999999.0
        new_score = parse_float(row["score"]) or -999999.0
        if (new_rank, -new_score) < (old_rank, -old_score):
            best[key] = row
    return sorted(best.values(), key=lambda item: (item["as_of_date"], parse_int(item["rank"]) or 999999, str(item["ticker"])))


def discover_price_files() -> list[Path]:
    candidates: list[Path] = []
    for base in [ROOT / "data", ROOT / "outputs"]:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.csv")):
            cols = read_header(path)
            normalized = {norm(col) for col in cols}
            if "date" in normalized and ("close" in normalized or "adjusted_close" in normalized) and ("symbol" in normalized or "ticker" in normalized):
                candidates.append(path)
    preferred = [path for path in candidates if "canonical" in path.name.lower() and "ohlcv" in path.name.lower()]
    return preferred or candidates


def load_prices(tickers: set[str]) -> dict[str, list[dict[str, object]]]:
    prices: dict[str, dict[date, dict[str, object]]] = defaultdict(dict)
    for path in discover_price_files():
        cols = read_header(path)
        ticker_col = detect_field(cols, ["symbol", "ticker"])
        date_col = detect_field(cols, ["date"])
        close_col = detect_field(cols, ["adjusted_close", "adj_close", "close"])
        high_col = detect_field(cols, ["high"])
        low_col = detect_field(cols, ["low"])
        if not ticker_col or not date_col or not close_col:
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                ticker = str(row.get(ticker_col, "")).strip().upper()
                if ticker not in tickers:
                    continue
                d = parse_date_value(row.get(date_col))
                close = parse_float(row.get(close_col))
                if d is None or close is None or close <= 0:
                    continue
                prices[ticker][d] = {
                    "date": d,
                    "close": close,
                    "high": parse_float(row.get(high_col)) or close,
                    "low": parse_float(row.get(low_col)) or close,
                    "source_artifact": str(path.relative_to(ROOT)),
                }
    return {ticker: sorted(by_date.values(), key=lambda item: item["date"]) for ticker, by_date in prices.items()}


def first_index_on_or_after(series: list[dict[str, object]], as_of: date) -> int | None:
    for index, row in enumerate(series):
        if row["date"] >= as_of:
            return index
    return None


def compute_outcome(series: list[dict[str, object]], as_of: date) -> dict[str, object]:
    result: dict[str, object] = {
        "entry_price": "",
        "entry_price_date": "",
        "forward_return_5d": "UNAVAILABLE_INSUFFICIENT_FUTURE_DATA",
        "forward_return_10d": "UNAVAILABLE_INSUFFICIENT_FUTURE_DATA",
        "forward_return_20d": "UNAVAILABLE_INSUFFICIENT_FUTURE_DATA",
        "max_drawdown_10d": "UNAVAILABLE_INSUFFICIENT_FUTURE_DATA",
        "max_gain_10d": "UNAVAILABLE_INSUFFICIENT_FUTURE_DATA",
        "outcome_status": "MISSING_LOCAL_PRICE_HISTORY",
    }
    idx = first_index_on_or_after(series, as_of)
    if idx is None:
        return result
    entry = parse_float(series[idx]["close"])
    if entry is None or entry <= 0:
        return result
    result["entry_price"] = f"{entry:.10f}"
    result["entry_price_date"] = series[idx]["date"].isoformat()
    available_any = False
    for horizon in [5, 10, 20]:
        out_col = f"forward_return_{horizon}d"
        target = idx + horizon
        if target < len(series):
            exit_price = parse_float(series[target]["close"])
            if exit_price is not None:
                result[out_col] = f"{(exit_price / entry - 1.0):.10f}"
                available_any = True
    if idx + 10 < len(series):
        window = series[idx + 1 : idx + 11]
        lows = [parse_float(row["low"]) for row in window]
        highs = [parse_float(row["high"]) for row in window]
        lows = [value for value in lows if value is not None]
        highs = [value for value in highs if value is not None]
        if lows:
            result["max_drawdown_10d"] = f"{(min(lows) / entry - 1.0):.10f}"
        if highs:
            result["max_gain_10d"] = f"{(max(highs) / entry - 1.0):.10f}"
    result["outcome_status"] = "PASS_FORWARD_OUTCOME_AVAILABLE" if available_any else "INSUFFICIENT_FUTURE_DATA"
    return result


def add_forward_outcomes(snapshot: list[dict[str, object]], prices: dict[str, list[dict[str, object]]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    benchmark_cache: dict[tuple[str, str], dict[str, object]] = {}
    for row in snapshot:
        as_of = parse_date_value(row["as_of_date"])
        ticker = str(row["ticker"])
        outcome = compute_outcome(prices.get(ticker, []), as_of) if as_of else {}
        out = dict(row)
        out.update(outcome)
        for benchmark in BENCHMARKS:
            bkey = (benchmark, str(row["as_of_date"]))
            if bkey not in benchmark_cache:
                benchmark_cache[bkey] = compute_outcome(prices.get(benchmark, []), as_of) if as_of else {}
            for horizon in [5, 10, 20]:
                base_ret = parse_float(out.get(f"forward_return_{horizon}d"))
                bench_ret = parse_float(benchmark_cache[bkey].get(f"forward_return_{horizon}d"))
                col = f"excess_return_vs_{benchmark}_{horizon}d"
                out[col] = f"{(base_ret - bench_ret):.10f}" if base_ret is not None and bench_ret is not None else "UNAVAILABLE_MISSING_BENCHMARK_OR_FORWARD_DATA"
        rows.append(out)
    return rows


def numeric_values(rows: list[dict[str, object]], field: str) -> list[float]:
    return [value for value in (parse_float(row.get(field)) for row in rows) if value is not None]


def summarize_rows(name: str, rows: list[dict[str, object]]) -> dict[str, object]:
    ret10 = numeric_values(rows, "forward_return_10d")
    return {
        "bucket": name,
        "evaluated_row_count": len(ret10),
        "average_forward_return_5d": avg(numeric_values(rows, "forward_return_5d")),
        "average_forward_return_10d": avg(ret10),
        "average_forward_return_20d": avg(numeric_values(rows, "forward_return_20d")),
        "median_forward_return_10d": fmt(median(ret10)) if ret10 else "",
        "hit_rate_10d": fmt(sum(1 for value in ret10 if value > 0) / len(ret10)) if ret10 else "",
        "average_max_drawdown_10d": avg(numeric_values(rows, "max_drawdown_10d")),
        "average_max_gain_10d": avg(numeric_values(rows, "max_gain_10d")),
    }


def avg(values: list[float]) -> str:
    return fmt(sum(values) / len(values)) if values else ""


def fmt(value: float) -> str:
    return f"{value:.10f}"


def bucket_summary(forward_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    by_date: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in forward_rows:
        by_date[str(row["as_of_date"])].append(row)
    for bucket_name, limit in RANK_BUCKETS:
        bucket_rows: list[dict[str, object]] = []
        for rows in by_date.values():
            ranked = sorted(rows, key=lambda item: parse_int(item.get("rank")) or 999999)
            bucket_rows.extend(ranked[:limit] if limit else ranked)
        output.append(summarize_rows(bucket_name, bucket_rows))
    return output


def benchmark_summary(forward_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    by_date: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in forward_rows:
        by_date[str(row["as_of_date"])].append(row)
    for bucket_name, limit in RANK_BUCKETS:
        bucket_rows: list[dict[str, object]] = []
        for date_rows in by_date.values():
            ranked = sorted(date_rows, key=lambda item: parse_int(item.get("rank")) or 999999)
            bucket_rows.extend(ranked[:limit] if limit else ranked)
        out = {"bucket": bucket_name, "evaluated_row_count": len(numeric_values(bucket_rows, "forward_return_10d"))}
        for benchmark in BENCHMARKS:
            for horizon in [5, 10, 20]:
                out[f"excess_return_vs_{benchmark}_{horizon}d"] = avg(numeric_values(bucket_rows, f"excess_return_vs_{benchmark}_{horizon}d"))
        rows.append(out)
    return rows


def label_summary(forward_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for label in LABEL_TERMS:
        label_rows = [
            row for row in forward_rows
            if label in str(row.get("detected_label_fields", "")).lower()
            or label in str(row.get("raw_status_summary", "")).lower().replace("_", "-")
        ]
        summary = summarize_rows(label, label_rows)
        summary["label_or_status"] = summary.pop("bucket")
        output.append(summary)
    return output


def failure_cases(forward_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for row in forward_rows:
        rank = parse_int(row.get("rank"))
        if rank is None or rank > 20:
            continue
        ret10 = parse_float(row.get("forward_return_10d"))
        labels = f"{row.get('detected_label_fields', '')} {row.get('raw_status_summary', '')}".lower().replace("_", "-")
        failures: list[tuple[str, str]] = []
        if ret10 is not None and ret10 < 0:
            failures.append(("High-ranked names that lost money afterward", "Top-ranked row had negative 10-day forward return."))
        for benchmark in BENCHMARKS:
            excess = parse_float(row.get(f"excess_return_vs_{benchmark}_10d"))
            if excess is not None and excess < 0:
                failures.append((f"High-ranked names that underperformed {benchmark}", f"Top-ranked row lagged {benchmark} over the 10-day horizon."))
        if "near-entry" in labels and ret10 is not None and ret10 <= 0:
            failures.append(("Near-entry names that failed afterward", "Near-entry label did not produce positive 10-day forward return."))
        if "overheat" in labels and ret10 is not None and ret10 > 0:
            failures.append(("Overheat names that continued rising afterward", "Overheat label was followed by positive 10-day forward return."))
        if "pullback review" in labels and ret10 is not None and ret10 <= 0:
            failures.append(("Pullback-review names that did not rebound", "Pullback-review label did not rebound over 10 trading days."))
        for failure_type, note in failures:
            benchmark_result = []
            for benchmark in BENCHMARKS:
                value = parse_float(row.get(f"excess_return_vs_{benchmark}_10d"))
                if value is not None:
                    benchmark_result.append(f"{benchmark}_10d_excess={value:.4f}")
            cases.append(
                {
                    "as_of_date": row.get("as_of_date", ""),
                    "ticker": row.get("ticker", ""),
                    "rank": row.get("rank", ""),
                    "score": row.get("score", ""),
                    "label_or_status": row.get("detected_label_fields") or row.get("raw_status_summary", ""),
                    "forward_return_5d": row.get("forward_return_5d", ""),
                    "forward_return_10d": row.get("forward_return_10d", ""),
                    "forward_return_20d": row.get("forward_return_20d", ""),
                    "benchmark_relative_result": "; ".join(benchmark_result) or "UNAVAILABLE",
                    "failure_type": failure_type,
                    "diagnosis_note": note,
                }
            )
    return cases


def build_strategy_diagnosis(bucket_rows: list[dict[str, object]], label_rows: list[dict[str, object]], benchmark_rows: list[dict[str, object]], evaluated: int) -> str:
    if evaluated == 0:
        return "insufficient outcome data: no usable forward returns were available from local price files."
    signals: list[str] = []
    top10 = next((row for row in bucket_rows if row["bucket"] == "Top 10"), {})
    full = next((row for row in bucket_rows if row["bucket"] == "Full ranked pool"), {})
    top10_ret = parse_float(top10.get("average_forward_return_10d"))
    full_ret = parse_float(full.get("average_forward_return_10d"))
    if top10_ret is not None and full_ret is not None and top10_ret <= full_ret:
        signals.append("ranking model weakness")
    if top10_ret is not None and top10_ret < 0:
        signals.append("entry timing weakness")
    by_label = {str(row.get("label_or_status")): row for row in label_rows}
    if parse_float(by_label.get("near-entry", {}).get("average_forward_return_10d")) is not None and parse_float(by_label["near-entry"].get("average_forward_return_10d")) <= 0:
        signals.append("near-entry label weakness")
    if parse_float(by_label.get("overheat", {}).get("average_forward_return_10d")) is not None and parse_float(by_label["overheat"].get("average_forward_return_10d")) > 0:
        signals.append("overheat logic weakness")
    if parse_float(by_label.get("pullback review", {}).get("average_forward_return_10d")) is not None and parse_float(by_label["pullback review"].get("average_forward_return_10d")) <= 0:
        signals.append("pullback logic weakness")
    top10_bench = next((row for row in benchmark_rows if row["bucket"] == "Top 10"), {})
    if any((parse_float(top10_bench.get(f"excess_return_vs_{benchmark}_10d")) or 0) < 0 for benchmark in BENCHMARKS):
        signals.append("benchmark-relative underperformance")
    if not signals:
        signals.append("no major weakness proven by available evidence")
    if evaluated < 30:
        signals.append("insufficient outcome data")
    return "; ".join(dict.fromkeys(signals)) + "."


def next_action(final_status: str, diagnosis: str) -> str:
    if "NO_RANKING" in final_status:
        return "Repair V20 ranking/candidate artifact availability before V21 optimization."
    if "insufficient outcome data" in diagnosis or "OUTCOME_DATA_INSUFFICIENT" in final_status:
        return "Proceed to V21.002_OUTCOME_COLLECTION_AND_SNAPSHOT_ARCHIVE."
    if "near-entry label weakness" in diagnosis:
        return "Redesign near-entry logic before promoting additional strategy layers."
    if "overheat logic weakness" in diagnosis:
        return "Redesign overheat logic and audit strong-trend false blocks."
    if "pullback logic weakness" in diagnosis:
        return "Redesign pullback detection and rebound criteria."
    if "entry timing weakness" in diagnosis:
        return "Proceed to V21.002_ENTRY_TIMING_OPTIMIZATION."
    return "Proceed to V21.002_FACTOR_ABLATION_AUDIT."


def make_report(gate: dict[str, object], discovery: list[dict[str, object]], snapshot: list[dict[str, object]], forward_rows: list[dict[str, object]], bucket_rows: list[dict[str, object]], benchmark_rows: list[dict[str, object]], label_rows: list[dict[str, object]], failure_rows: list[dict[str, object]]) -> None:
    selected_count = sum(1 for row in discovery if row.get("selected_for_audit") == "TRUE")
    lines = [
        "# V21.001 Baseline Strategy Performance Audit",
        "",
        "## Final status",
        f"final_status: {gate['final_status']}",
        f"evaluated_forward_rows: {gate['evaluated_forward_rows']}",
        f"evaluated_as_of_date_count: {gate['evaluated_as_of_date_count']}",
        "",
        "## Input discovery",
        f"Discovered {len(discovery)} V20 CSV artifacts; selected {selected_count} ranking/candidate artifacts for audit.",
        "",
        "## Ranking coverage",
        f"Baseline ranking snapshot rows: {len(snapshot)}.",
        "",
        "## Forward outcome coverage",
        f"Forward outcome rows: {len(forward_rows)}. Evaluated rows use available 10-day local outcomes only.",
        "",
        "## Bucket performance summary",
        markdown_table(bucket_rows[:4], ["bucket", "evaluated_row_count", "average_forward_return_10d", "hit_rate_10d"]),
        "",
        "## Benchmark-relative performance",
        markdown_table(benchmark_rows[:4], ["bucket", "excess_return_vs_QQQ_10d", "excess_return_vs_SOXX_10d", "excess_return_vs_SPY_10d"]),
        "",
        "## Label forward-performance audit",
        markdown_table(label_rows, ["label_or_status", "evaluated_row_count", "average_forward_return_10d", "hit_rate_10d"]),
        "",
        "## Failure cases",
        f"Failure-case rows: {len(failure_rows)}.",
        "",
        "## Strategy diagnosis",
        f"strategy diagnosis: {gate['strategy_diagnosis']}",
        "",
        "## Next recommended action",
        f"next recommended action: {gate['next_recommended_action']}",
        "",
        "## Safety confirmation",
    ]
    lines.extend([f"- {field}: {gate[field]}" for field in SAFETY_FIELDS])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def markdown_table(rows: list[dict[str, object]], fields: list[str]) -> str:
    if not rows:
        return "No rows available."
    lines = ["| " + " | ".join(fields) + " |", "| " + " | ".join(["---"] * len(fields)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(field, "")) for field in fields) + " |")
    return "\n".join(lines)


def main() -> int:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    discovery, selected_paths = discover_inputs()
    snapshot = load_ranking_snapshot(selected_paths)
    tickers = {str(row["ticker"]) for row in snapshot} | set(BENCHMARKS)
    prices = load_prices(tickers) if snapshot else {}
    forward_rows = add_forward_outcomes(snapshot, prices) if snapshot else []
    bucket_rows = bucket_summary(forward_rows)
    benchmark_rows = benchmark_summary(forward_rows)
    label_rows = label_summary(forward_rows)
    failure_rows = failure_cases(forward_rows)

    evaluated_forward_rows = len(numeric_values(forward_rows, "forward_return_10d"))
    evaluated_dates = len({str(row["as_of_date"]) for row in forward_rows if parse_float(row.get("forward_return_10d")) is not None})
    benchmark_coverage_status = "PASS_BENCHMARK_LOCAL_DATA_AVAILABLE" if all(prices.get(symbol) for symbol in BENCHMARKS) else "PARTIAL_MISSING_BENCHMARK_LOCAL_DATA"
    label_coverage_status = "PASS_LABEL_FIELDS_DETECTED" if any(row.get("detected_label_fields") or row.get("raw_status_summary") for row in snapshot) else "PARTIAL_NO_LABEL_FIELDS_DETECTED"
    if not snapshot:
        final_status = "FAIL_V21_001_NO_RANKING_INPUT_FOUND"
    elif evaluated_forward_rows == 0:
        final_status = "PARTIAL_PASS_V21_001_DISCOVERY_READY_OUTCOME_DATA_INSUFFICIENT"
    elif evaluated_forward_rows < 30 or evaluated_dates < 3:
        final_status = "PARTIAL_PASS_V21_001_LIMITED_OUTCOME_EVIDENCE"
    else:
        final_status = "PASS_V21_001_BASELINE_AUDIT_READY_FOR_FACTOR_ABLATION"
    diagnosis = build_strategy_diagnosis(bucket_rows, label_rows, benchmark_rows, evaluated_forward_rows)
    action = next_action(final_status, diagnosis)
    gate = {
        "stage_name": STAGE_NAME,
        "final_status": final_status,
        "evaluated_forward_rows": evaluated_forward_rows,
        "evaluated_as_of_date_count": evaluated_dates,
        "benchmark_coverage_status": benchmark_coverage_status,
        "label_audit_coverage_status": label_coverage_status,
        "strategy_diagnosis": diagnosis,
        "next_recommended_action": action,
    }
    gate.update({field: "FALSE" for field in SAFETY_FIELDS})

    write_csv(INPUT_DISCOVERY, discovery, ["artifact_path", "artifact_type", "exists_non_empty", "row_count", "detected_columns", "selected_for_audit", "selection_reason", "validation_status"])
    write_csv(RANKING_SNAPSHOT, snapshot, ["as_of_date", "source_artifact", "ticker", "rank", "score", "detected_score_field", "detected_label_fields", "raw_status_summary"])
    forward_fields = ["as_of_date", "source_artifact", "ticker", "rank", "score", "detected_label_fields", "raw_status_summary", "entry_price", "entry_price_date", "forward_return_5d", "forward_return_10d", "forward_return_20d", "max_drawdown_10d", "max_gain_10d", "outcome_status"]
    for benchmark in BENCHMARKS:
        for horizon in [5, 10, 20]:
            forward_fields.append(f"excess_return_vs_{benchmark}_{horizon}d")
    write_csv(FORWARD_ROWS, forward_rows, forward_fields)
    summary_fields = ["bucket", "evaluated_row_count", "average_forward_return_5d", "average_forward_return_10d", "average_forward_return_20d", "median_forward_return_10d", "hit_rate_10d", "average_max_drawdown_10d", "average_max_gain_10d"]
    write_csv(BUCKET_SUMMARY, bucket_rows, summary_fields)
    label_fields = ["label_or_status", "evaluated_row_count", "average_forward_return_5d", "average_forward_return_10d", "average_forward_return_20d", "median_forward_return_10d", "hit_rate_10d", "average_max_drawdown_10d", "average_max_gain_10d"]
    write_csv(LABEL_PERFORMANCE, label_rows, label_fields)
    bench_fields = ["bucket", "evaluated_row_count"] + [f"excess_return_vs_{benchmark}_{horizon}d" for benchmark in BENCHMARKS for horizon in [5, 10, 20]]
    write_csv(BENCHMARK_RELATIVE, benchmark_rows, bench_fields)
    write_csv(FAILURE_CASES, failure_rows, ["as_of_date", "ticker", "rank", "score", "label_or_status", "forward_return_5d", "forward_return_10d", "forward_return_20d", "benchmark_relative_result", "failure_type", "diagnosis_note"])
    write_csv(NEXT_STAGE_GATE, [gate], ["stage_name", "final_status", "evaluated_forward_rows", "evaluated_as_of_date_count", "benchmark_coverage_status", "label_audit_coverage_status", "strategy_diagnosis", "next_recommended_action"] + SAFETY_FIELDS)
    make_report(gate, discovery, snapshot, forward_rows, bucket_rows, benchmark_rows, label_rows, failure_rows)

    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_status={final_status}")
    print(f"evaluated_forward_rows={evaluated_forward_rows}")
    print(f"evaluated_as_of_date_count={evaluated_dates}")
    print(f"next_recommended_action={action}")
    return 0 if final_status in ALLOWED_FINAL_STATUSES else 1


if __name__ == "__main__":
    raise SystemExit(main())
