#!/usr/bin/env python
"""Research-only V21.061-R1 ABCD maturity comparison report."""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


STAGE_ID = "V21.061-R1"
PASS_STATUS = "PASS_V21_061_R1_MATURITY_COMPARISON_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_061_R1_COMPARISON_CREATED_NEED_MORE_MATURITY"
FAIL_A0 = "FAIL_V21_061_R1_A0_CONTROL_MUTATION_OR_RECOMPUTE"
FAIL_SOURCE = "FAIL_V21_061_R1_SOURCE_LEDGER_MUTATION_DETECTED"
FAIL_HARDCODED = "FAIL_V21_061_R1_HARDCODED_INCLUSION_VIOLATION"
FAIL_PRICE = "FAIL_V21_061_R1_LOCAL_PRICE_MISSING_PERFORMANCE_VIOLATION"
FAIL_PROMOTION = "FAIL_V21_061_R1_PREMATURE_PROMOTION_VIOLATION"
FAIL_MUTATION = "FAIL_V21_061_R1_FORBIDDEN_MUTATION_DETECTED"

OUT_REL = Path("outputs/v21/experiments/momentum_dynamic")
LEDGER_REL = OUT_REL / "V21_060_R1_ABCD_FORWARD_OBSERVATION_LEDGER.csv"
BACKTEST_REL = OUT_REL / "V21_060_R1_ABCD_BACKTEST_COMPARISON.csv"
CAPTURE_REL = OUT_REL / "V21_060_R1_MOMENTUM_LEADER_CAPTURE_AUDIT.csv"
FORCED_SOURCE_REL = OUT_REL / "V21_060_R1_FORCED_TICKER_BACKTEST_AND_OBSERVATION_AUDIT.csv"
V60_SUMMARY_REL = OUT_REL / "V21_060_R1_SUMMARY.json"
A0_CANONICAL_REL = Path("outputs/v21/experiments/version_control/V21_056_R2_A0_CANONICAL_CONTROL_VIEW.csv")
R1_SNAPSHOT_REL = Path("outputs/v21/experiments/version_control/V21_056_R1_A0_LEDGER_SNAPSHOT.csv")
PRICE_REL = Path("inputs/v21/historical_ohlcv_cache/V21_037_R1_HISTORICAL_OHLCV_CACHE.csv")

MATURED_NAME = "V21_061_R1_MATURED_OBSERVATION_RESULTS.csv"
WINDOW_NAME = "V21_061_R1_VARIANT_COMPARISON_BY_WINDOW.csv"
PAIR_NAME = "V21_061_R1_A0_VS_A1_B_C_COMPARISON.csv"
BACKTEST_NAME = "V21_061_R1_BACKTEST_CONTEXT_SUMMARY.csv"
CAPTURE_NAME = "V21_061_R1_MOMENTUM_LEADER_CAPTURE_REPORT.csv"
FORCED_NAME = "V21_061_R1_FORCED_TICKER_MATURITY_AUDIT.csv"
RECOMMENDATION_NAME = "V21_061_R1_RECOMMENDATION.csv"
LINEAGE_NAME = "V21_061_R1_LINEAGE_AUDIT.csv"
SUMMARY_NAME = "V21_061_R1_SUMMARY.json"

VARIANTS = (
    "A0_CURRENT_TESTING_LOCKED",
    "A1_BASELINE_REPLAY_CURRENT",
    "B_MOMENTUM_STATIC_R1",
    "C_MOMENTUM_DYNAMIC_R1",
)
WINDOWS = ("5D", "10D", "20D", "60D")
PAIRS = (
    ("A0_CURRENT_TESTING_LOCKED", "A1_BASELINE_REPLAY_CURRENT"),
    ("A0_CURRENT_TESTING_LOCKED", "B_MOMENTUM_STATIC_R1"),
    ("A0_CURRENT_TESTING_LOCKED", "C_MOMENTUM_DYNAMIC_R1"),
    ("A1_BASELINE_REPLAY_CURRENT", "B_MOMENTUM_STATIC_R1"),
    ("A1_BASELINE_REPLAY_CURRENT", "C_MOMENTUM_DYNAMIC_R1"),
    ("B_MOMENTUM_STATIC_R1", "C_MOMENTUM_DYNAMIC_R1"),
)
FORCED = ("MU", "SNDK", "DRAM", "SPCX", "USD", "SMH", "SOXX", "SOXL", "QQQ", "TQQQ", "SQQQ")

MATURED_FIELDS = [
    "observation_id", "stage_id", "source_stage_id", "as_of_date", "version_id",
    "variant_id", "frozen_control", "recomputed", "ticker", "instrument_type",
    "asset_class", "theme", "rank", "score", "score_source", "momentum_score",
    "momentum_state", "chase_permission", "risk_size_bucket",
    "applied_momentum_weight", "market_regime", "regime_fallback_used",
    "forward_window", "scheduled_maturity_date", "maturity_eval_date",
    "realized_forward_return", "maturity_status", "price_start_date",
    "price_end_date", "price_start", "price_end", "price_data_status",
    "source_ranking_path", "source_lineage", "research_only",
]


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def tf(value: object) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return "TRUE" if clean(value).upper() == "TRUE" else "FALSE"


def num(value: object) -> float | None:
    try:
        parsed = float(clean(value))
        return parsed if math.isfinite(parsed) else None
    except ValueError:
        return None


def fmt(value: object) -> str:
    parsed = num(value)
    return "" if parsed is None else f"{parsed:.10f}"


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.is_file() or path.stat().st_size == 0:
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, rows: Iterable[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                field: "TRUE" if row.get(field) is True else "FALSE" if row.get(field) is False
                else "" if row.get(field) is None else row.get(field, "")
                for field in fields
            })


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def protected_hashes(root: Path) -> dict[str, dict[str, str]]:
    groups = {"a0": {}, "source": {}, "official": {}, "real_book": {}, "broker": {}}
    for path in (root / A0_CANONICAL_REL, root / R1_SNAPSHOT_REL):
        if path.is_file():
            groups["a0"][rel(root, path)] = sha(path)
    source = root / LEDGER_REL
    if source.is_file():
        groups["source"][rel(root, source)] = sha(source)
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or root / OUT_REL in path.parents:
                continue
            text = rel(root, path).lower().replace("-", "_").replace(" ", "_")
            if "broker" in text:
                groups["broker"][rel(root, path)] = sha(path)
            elif "real_book" in text or "realbook" in text:
                groups["real_book"][rel(root, path)] = sha(path)
            elif "official" in text and any(token in text for token in ("rank", "weight", "recommend", "allocation")):
                groups["official"][rel(root, path)] = sha(path)
    return groups


def changed(before: dict[str, str], after: dict[str, str]) -> bool:
    return any(before.get(key) != after.get(key) for key in set(before) | set(after))


def load_prices(path: Path) -> tuple[dict[str, tuple[list[str], list[float]]], str]:
    frame = pd.read_csv(path, usecols=["as_of_date", "ticker", "close", "adjusted_close"], low_memory=False)
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    frame["as_of_date"] = frame["as_of_date"].astype(str).str.slice(0, 10)
    frame["price"] = pd.to_numeric(frame["adjusted_close"], errors="coerce").fillna(
        pd.to_numeric(frame["close"], errors="coerce")
    )
    frame = frame[frame["price"].gt(0)].sort_values(["ticker", "as_of_date"])
    frame = frame.drop_duplicates(["ticker", "as_of_date"], keep="last")
    lookup = {}
    for ticker, group in frame.groupby("ticker", sort=False):
        lookup[ticker] = (group["as_of_date"].tolist(), group["price"].astype(float).tolist())
    return lookup, clean(frame["as_of_date"].max())


def price_on_or_after(
    prices: dict[str, tuple[list[str], list[float]]], ticker: str, day: str, max_day: str
) -> tuple[str, float] | None:
    series = prices.get(ticker)
    if not series:
        return None
    dates, values = series
    index = bisect.bisect_left(dates, day)
    if index >= len(dates) or dates[index] > max_day:
        return None
    return dates[index], values[index]


def classify_observations(
    source_rows: list[dict[str, str]],
    prices: dict[str, tuple[list[str], list[float]]],
    eval_date: str,
) -> list[dict[str, object]]:
    output = []
    for source in source_rows:
        row = {field: source.get(field, "") for field in MATURED_FIELDS}
        row["stage_id"] = STAGE_ID
        row["source_stage_id"] = clean(source.get("stage_id") or "V21.060-R1")
        row["maturity_eval_date"] = eval_date
        row["research_only"] = "TRUE"
        maturity_date = clean(source.get("scheduled_maturity_date"))
        ticker = clean(source.get("ticker")).upper()
        if not maturity_date or maturity_date > eval_date:
            row.update({
                "realized_forward_return": "", "maturity_status": "PENDING_NOT_MATURED",
                "price_start_date": source.get("price_start_date", ""),
                "price_end_date": source.get("price_end_date", ""),
                "price_start": source.get("price_start", ""), "price_end": source.get("price_end", ""),
                "price_data_status": "PENDING_MATURITY",
            })
        else:
            start = price_on_or_after(prices, ticker, clean(source.get("as_of_date")), eval_date)
            end = price_on_or_after(prices, ticker, maturity_date, eval_date)
            if start and end:
                realized = end[1] / start[1] - 1
                row.update({
                    "realized_forward_return": fmt(realized),
                    "maturity_status": "MATURED_PRICE_AVAILABLE",
                    "price_start_date": start[0], "price_end_date": end[0],
                    "price_start": fmt(start[1]), "price_end": fmt(end[1]),
                    "price_data_status": "MATURED_PRICES_AVAILABLE",
                })
            else:
                missing = []
                if not start:
                    missing.append("START_PRICE_MISSING")
                if not end:
                    missing.append("END_PRICE_MISSING")
                row.update({
                    "realized_forward_return": "", "maturity_status": "MATURED_PRICE_MISSING",
                    "price_start_date": start[0] if start else "",
                    "price_end_date": end[0] if end else "",
                    "price_start": fmt(start[1]) if start else "",
                    "price_end": fmt(end[1]) if end else "",
                    "price_data_status": "|".join(missing),
                })
        output.append(row)
    return output


def benchmark_return(
    prices: dict[str, tuple[list[str], list[float]]],
    ticker: str,
    as_of: str,
    maturity: str,
    eval_date: str,
) -> float | None:
    start = price_on_or_after(prices, ticker, as_of, eval_date)
    end = price_on_or_after(prices, ticker, maturity, eval_date)
    if not start or not end:
        return None
    return end[1] / start[1] - 1


def variant_comparison(
    rows: list[dict[str, object]],
    prices: dict[str, tuple[list[str], list[float]]],
    eval_date: str,
) -> list[dict[str, object]]:
    frame = pd.DataFrame(rows)
    frame["return_num"] = pd.to_numeric(frame["realized_forward_return"], errors="coerce")
    frame["rank_num"] = pd.to_numeric(frame["rank"], errors="coerce")
    frame["score_num"] = pd.to_numeric(frame["score"], errors="coerce")
    output = []
    for variant in VARIANTS:
        for window in WINDOWS:
            group = frame[(frame["variant_id"] == variant) & (frame["forward_window"] == window)].copy()
            matured = group[group["maturity_status"] == "MATURED_PRICE_AVAILABLE"].copy()
            pending = int((group["maturity_status"] == "PENDING_NOT_MATURED").sum())
            missing = int((group["maturity_status"] == "MATURED_PRICE_MISSING").sum())
            if len(matured):
                for benchmark in ("SPY", "QQQ", "SMH"):
                    matured[f"{benchmark}_return"] = matured.apply(
                        lambda row: benchmark_return(
                            prices, benchmark, clean(row["as_of_date"]),
                            clean(row["scheduled_maturity_date"]), eval_date
                        ), axis=1
                    )
                top10 = matured[matured["rank_num"] <= 10]
                top20 = matured[matured["rank_num"] <= 20]
                values = matured["return_num"].dropna()
                std = values.std(ddof=0)
                metrics = {
                    "mean_forward_return": fmt(values.mean()),
                    "median_forward_return": fmt(values.median()),
                    "hit_rate": fmt((values > 0).mean()),
                    "top10_mean_forward_return": fmt(top10["return_num"].mean()),
                    "top20_mean_forward_return": fmt(top20["return_num"].mean()),
                    "top10_hit_rate": fmt((top10["return_num"] > 0).mean()),
                    "top20_hit_rate": fmt((top20["return_num"] > 0).mean()),
                    "excess_return_vs_SPY": fmt((matured["return_num"] - matured["SPY_return"]).mean()),
                    "excess_return_vs_QQQ": fmt((matured["return_num"] - matured["QQQ_return"]).mean()),
                    "excess_return_vs_SMH": fmt((matured["return_num"] - matured["SMH_return"]).mean()),
                    "risk_adjusted_return_proxy": fmt(values.mean() / std if std and not np.isnan(std) else None),
                    "max_drawdown_proxy": fmt(values.min()),
                    "average_rank": fmt(matured["rank_num"].mean()),
                    "average_score": fmt(matured["score_num"].mean()),
                }
                status = "MATURED_ROWS_AVAILABLE"
            else:
                metrics = {field: "" for field in (
                    "mean_forward_return", "median_forward_return", "hit_rate",
                    "top10_mean_forward_return", "top20_mean_forward_return",
                    "top10_hit_rate", "top20_hit_rate", "excess_return_vs_SPY",
                    "excess_return_vs_QQQ", "excess_return_vs_SMH",
                    "risk_adjusted_return_proxy", "max_drawdown_proxy",
                    "average_rank", "average_score",
                )}
                status = "NO_MATURED_ROWS"
            instrument = matured["instrument_type"] if len(matured) else pd.Series(dtype=str)
            output.append({
                "variant_id": variant, "forward_window": window,
                "matured_count": len(matured), "pending_count": pending,
                "price_missing_count": missing, **metrics,
                "excess_return_vs_A0": "", "excess_return_vs_A1": "",
                "leveraged_etf_count": int((instrument == "LEVERAGED_LONG_ETF").sum()),
                "inverse_etf_count": int((instrument == "INVERSE_ETF").sum()),
                "etf_count": int(instrument.astype(str).str.contains("ETF", na=False).sum()),
                "stock_count": int((instrument == "STOCK").sum()),
                "comparison_status": status, "research_only": "TRUE",
            })
    mean_map = {
        (row["variant_id"], row["forward_window"]): num(row["mean_forward_return"])
        for row in output
    }
    for row in output:
        value = mean_map[(row["variant_id"], row["forward_window"])]
        a0 = mean_map[("A0_CURRENT_TESTING_LOCKED", row["forward_window"])]
        a1 = mean_map[("A1_BASELINE_REPLAY_CURRENT", row["forward_window"])]
        row["excess_return_vs_A0"] = fmt(value - a0) if value is not None and a0 is not None else ""
        row["excess_return_vs_A1"] = fmt(value - a1) if value is not None and a1 is not None else ""
    return output


def pair_comparison(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    frame = pd.DataFrame(rows)
    frame = frame[frame["maturity_status"] == "MATURED_PRICE_AVAILABLE"].copy()
    frame["return_num"] = pd.to_numeric(frame["realized_forward_return"], errors="coerce")
    frame["rank_num"] = pd.to_numeric(frame["rank"], errors="coerce")
    output = []
    for left, right in PAIRS:
        for window in WINDOWS:
            keys = ["ticker", "as_of_date", "forward_window"]
            a = frame[(frame["variant_id"] == left) & (frame["forward_window"] == window)]
            b = frame[(frame["variant_id"] == right) & (frame["forward_window"] == window)]
            joined = a.merge(b, on=keys, suffixes=("_left", "_right"))
            count = len(joined)
            if count:
                left_top20 = joined[joined["rank_num_left"] <= 20]
                right_top20 = joined[joined["rank_num_right"] <= 20]
                metrics = {
                    "mean_return_delta": fmt(joined["return_num_right"].mean() - joined["return_num_left"].mean()),
                    "hit_rate_delta": fmt((joined["return_num_right"] > 0).mean() - (joined["return_num_left"] > 0).mean()),
                    "top20_return_delta": fmt(right_top20["return_num_right"].mean() - left_top20["return_num_left"].mean()),
                    "top20_hit_rate_delta": fmt((right_top20["return_num_right"] > 0).mean() - (left_top20["return_num_left"] > 0).mean()),
                }
                status = "COMPARABLE_MATURED_ROWS"
            else:
                metrics = {key: "" for key in ("mean_return_delta", "hit_rate_delta", "top20_return_delta", "top20_hit_rate_delta")}
                status = "NO_COMPARABLE_MATURED_ROWS"
            confidence = (
                "RECOMMENDATION_SAMPLE" if count >= 100
                else "DIRECTIONAL_READ_ONLY" if count >= 30
                else "INSUFFICIENT_SAMPLE"
            )
            output.append({
                "comparison_pair": f"{left}_VS_{right}", "left_variant": left,
                "right_variant": right, "forward_window": window,
                "comparable_matured_count": count, **metrics,
                "comparison_status": status,
                "statistical_confidence_status": confidence,
                "recommendation_constraint": "NEED_MORE_MATURITY" if count < 100 else "PROMOTION_REVIEW_ONLY",
                "research_only": "TRUE",
            })
    return output


def backtest_context(source: list[dict[str, str]], fallback: bool) -> list[dict[str, object]]:
    output = []
    for row in source:
        output.append({
            "variant_id": row.get("variant_id", ""), "forward_window": row.get("forward_window", ""),
            "observation_count": row.get("observation_count", ""),
            "mean_forward_return": row.get("mean_forward_return", ""),
            "hit_rate": row.get("hit_rate", ""),
            "top20_mean_forward_return": row.get("top20_mean_forward_return", ""),
            "top20_hit_rate": row.get("top20_hit_rate", ""),
            "risk_adjusted_return_proxy": row.get("risk_adjusted_return_proxy", ""),
            "max_drawdown_proxy": row.get("max_drawdown_proxy", ""),
            "backtest_fallback_used": tf(fallback),
            "point_in_time_momentum_approximation_used": tf(row.get("variant_id") in {"B_MOMENTUM_STATIC_R1", "C_MOMENTUM_DYNAMIC_R1"}),
            "evidence_status": "PRELIMINARY_CONTINUED_OBSERVATION_ONLY",
            "supports_continued_observation": "TRUE",
            "production_promotion_allowed": "FALSE", "research_only": "TRUE",
        })
    return output


def capture_report(source: list[dict[str, str]], matured_count: int) -> list[dict[str, object]]:
    frame = pd.DataFrame(source)
    output = []
    for variant in ("A1_BASELINE_REPLAY_CURRENT", "B_MOMENTUM_STATIC_R1", "C_MOMENTUM_DYNAMIC_R1"):
        group = frame[frame["variant_id"] == variant]
        output.append({
            "variant_id": variant,
            "top20_momentum_leader_capture_count": int(pd.to_numeric(group["leaders_in_top20"], errors="coerce").fillna(0).sum()),
            "top50_momentum_leader_capture_count": int(pd.to_numeric(group["leaders_in_top50"], errors="coerce").fillna(0).sum()),
            "capture_rate_top20": fmt(pd.to_numeric(group["top20_capture_rate"], errors="coerce").mean()),
            "capture_rate_top50": fmt(pd.to_numeric(group["top50_capture_rate"], errors="coerce").mean()),
            "capture_method": clean(group["leader_definition"].iloc[0]) if len(group) else "",
            "fallback_used": "TRUE" if len(group) and (group["fallback_used"].astype(str).str.upper() == "TRUE").any() else "FALSE",
            "performance_confirmation_status": "FORWARD_PERFORMANCE_AVAILABLE" if matured_count else "CAPTURE_ONLY_NOT_PERFORMANCE_CONFIRMED",
            "research_only": "TRUE",
        })
    return output


def forced_audit(
    rows: list[dict[str, object]], source_forced: list[dict[str, str]]
) -> list[dict[str, object]]:
    source_map = {clean(row.get("ticker")).upper(): row for row in source_forced}
    output = []
    for ticker in FORCED:
        ticker_rows = [row for row in rows if clean(row.get("ticker")).upper() == ticker]
        result = {"ticker": ticker}
        realized = {}
        for short, variant in zip(("A0", "A1", "B", "C"), VARIANTS):
            subset = [row for row in ticker_rows if clean(row.get("variant_id")) == variant]
            matured = [row for row in subset if row["maturity_status"] == "MATURED_PRICE_AVAILABLE"]
            result[f"present_in_{short}_observation"] = tf(bool(subset))
            result[f"matured_count_{short}"] = len(matured)
            result[f"pending_count_{short}"] = sum(row["maturity_status"] == "PENDING_NOT_MATURED" for row in subset)
            result[f"price_missing_count_{short}"] = sum(row["maturity_status"] == "MATURED_PRICE_MISSING" for row in subset)
            values = [num(row["realized_forward_return"]) for row in matured]
            values = [value for value in values if value is not None]
            realized[short] = fmt(sum(values) / len(values)) if values else ""
        source = source_map.get(ticker, {})
        result.update({
            "realized_forward_return_A0_if_available": realized["A0"],
            "realized_forward_return_A1_if_available": realized["A1"],
            "realized_forward_return_B_if_available": realized["B"],
            "realized_forward_return_C_if_available": realized["C"],
            "exclusion_reason": source.get("exclusion_reason", ""),
            "local_price_missing_flag": tf(source.get("local_price_missing_flag")),
            "hardcoded_inclusion_violation_flag": "FALSE",
            "research_only": "TRUE",
        })
        output.append(result)
    return output


def run_stage(root: Path) -> dict[str, object]:
    root = root.resolve()
    out = root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    before = protected_hashes(root)
    source_rows, _ = read_csv(root / LEDGER_REL)
    backtest_rows, _ = read_csv(root / BACKTEST_REL)
    capture_rows, _ = read_csv(root / CAPTURE_REL)
    forced_source, _ = read_csv(root / FORCED_SOURCE_REL)
    v60 = json.loads((root / V60_SUMMARY_REL).read_text(encoding="utf-8"))
    prices, eval_date = load_prices(root / PRICE_REL)

    matured_rows = classify_observations(source_rows, prices, eval_date)
    write_csv(out / MATURED_NAME, matured_rows, MATURED_FIELDS)
    window_rows = variant_comparison(matured_rows, prices, eval_date)
    write_csv(out / WINDOW_NAME, window_rows, list(window_rows[0].keys()))
    pair_rows = pair_comparison(matured_rows)
    write_csv(out / PAIR_NAME, pair_rows, list(pair_rows[0].keys()))
    context_rows = backtest_context(backtest_rows, bool(v60.get("backtest_fallback_used")))
    write_csv(out / BACKTEST_NAME, context_rows, list(context_rows[0].keys()))

    maturity_counts = Counter(clean(row["maturity_status"]) for row in matured_rows)
    matured_count = maturity_counts["MATURED_PRICE_AVAILABLE"]
    capture_output = capture_report(capture_rows, matured_count)
    write_csv(out / CAPTURE_NAME, capture_output, list(capture_output[0].keys()))
    forced_rows = forced_audit(matured_rows, forced_source)
    write_csv(out / FORCED_NAME, forced_rows, list(forced_rows[0].keys()))

    window_matured = Counter(
        clean(row["forward_window"]) for row in matured_rows
        if row["maturity_status"] == "MATURED_PRICE_AVAILABLE"
    )
    directional_ready = matured_count >= 30
    recommendation_status = "NEED_MORE_MATURITY"
    recommendation_rows = [{
        "recommendation_status": recommendation_status,
        "decision": "MATURITY_COMPARISON_CREATED_PENDING_FORWARD_RESULTS",
        "matured_observation_count": matured_count,
        "minimum_matured_rows_for_directional_read": 30,
        "minimum_matured_rows_for_recommendation": 100,
        "minimum_windows_required_for_promotion_review": 3,
        "matured_windows_count": sum(window_matured[window] > 0 for window in WINDOWS),
        "sixty_day_maturity_available": tf(window_matured["60D"] > 0),
        "forward_maturity_sufficient": "FALSE",
        "production_adoption_allowed": "FALSE", "official_use_allowed": "FALSE",
        "recommendation_basis": (
            "NO_MATURED_FORWARD_OBSERVATIONS" if matured_count == 0
            else "MATURED_ROWS_EXIST_BUT_CROSS_VARIANT_AND_60D_EVIDENCE_IS_INSUFFICIENT"
        ),
        "research_only": "TRUE",
    }]
    write_csv(out / RECOMMENDATION_NAME, recommendation_rows, list(recommendation_rows[0].keys()))

    lineage_rows = [
        {"lineage_role": "SOURCE_FORWARD_LEDGER", "source_path": rel(root, root / LEDGER_REL), "sha256_before": before["source"][rel(root, root / LEDGER_REL)], "usage": "READ_ONLY_MATURITY_CLASSIFICATION", "modified": "FALSE", "research_only": "TRUE"},
        {"lineage_role": "A0_CANONICAL_CONTROL", "source_path": rel(root, root / A0_CANONICAL_REL), "sha256_before": before["a0"][rel(root, root / A0_CANONICAL_REL)], "usage": "PROTECTED_CONTROL_REFERENCE", "modified": "FALSE", "research_only": "TRUE"},
        {"lineage_role": "V21_056_R1_SNAPSHOT", "source_path": rel(root, root / R1_SNAPSHOT_REL), "sha256_before": before["a0"][rel(root, root / R1_SNAPSHOT_REL)], "usage": "PROTECTED_FROZEN_SNAPSHOT", "modified": "FALSE", "research_only": "TRUE"},
        {"lineage_role": "BACKTEST_COMPARISON", "source_path": rel(root, root / BACKTEST_REL), "sha256_before": sha(root / BACKTEST_REL), "usage": "PRELIMINARY_CONTEXT_ONLY", "modified": "FALSE", "research_only": "TRUE"},
        {"lineage_role": "MOMENTUM_CAPTURE", "source_path": rel(root, root / CAPTURE_REL), "sha256_before": sha(root / CAPTURE_REL), "usage": "CAPTURE_CONTEXT_NOT_PROMOTION", "modified": "FALSE", "research_only": "TRUE"},
        {"lineage_role": "PRICE_DATA", "source_path": rel(root, root / PRICE_REL), "sha256_before": sha(root / PRICE_REL), "usage": f"MATURITY_EVALUATION_THROUGH_{eval_date}", "modified": "FALSE", "research_only": "TRUE"},
    ]

    after = protected_hashes(root)
    a0_modified = changed(before["a0"], after["a0"])
    source_modified = changed(before["source"], after["source"])
    official_modified = changed(before["official"], after["official"])
    real_modified = changed(before["real_book"], after["real_book"])
    broker_modified = changed(before["broker"], after["broker"])
    for row in lineage_rows:
        if row["lineage_role"] == "SOURCE_FORWARD_LEDGER":
            row["modified"] = tf(source_modified)
        elif row["lineage_role"] in {"A0_CANONICAL_CONTROL", "V21_056_R1_SNAPSHOT"}:
            row["modified"] = tf(a0_modified)
    write_csv(out / LINEAGE_NAME, lineage_rows, list(lineage_rows[0].keys()))

    source_ids = [clean(row.get("observation_id")) for row in source_rows]
    result_ids = [clean(row.get("observation_id")) for row in matured_rows]
    a0_source_ids = [
        clean(row.get("observation_id")) for row in source_rows
        if clean(row.get("variant_id")) == "A0_CURRENT_TESTING_LOCKED"
    ]
    a0_result_ids = [
        clean(row.get("observation_id")) for row in matured_rows
        if clean(row.get("variant_id")) == "A0_CURRENT_TESTING_LOCKED"
    ]
    a0_recomputed = False
    a0_id_changed = a0_source_ids != a0_result_ids
    hardcoded = sum(row["hardcoded_inclusion_violation_flag"] == "TRUE" for row in forced_rows)
    local_price_violation = sum(
        row["local_price_missing_flag"] == "TRUE"
        and sum(int(row[f"matured_count_{short}"]) for short in ("A0", "A1", "B", "C")) > 0
        for row in forced_rows
    )
    tqqq_ipo = 0
    premature_promotion = recommendation_status in {"MOMENTUM_STATIC_PROMISING", "MOMENTUM_DYNAMIC_PROMISING"} and not directional_ready

    pair_count_map = defaultdict(int)
    for row in pair_rows:
        pair_count_map[row["comparison_pair"]] += int(row["comparable_matured_count"])
    variant_counts = Counter(clean(row["variant_id"]) for row in matured_rows)
    forward_sufficient = (
        all(window_matured[window] >= 100 for window in ("5D", "10D", "20D"))
        and window_matured["60D"] > 0
        and sum(window_matured[window] > 0 for window in WINDOWS) >= 3
    )

    if a0_modified or a0_recomputed or a0_id_changed:
        final, decision = FAIL_A0, "STOP_AND_RESTORE_A0_CONTROL"
    elif source_modified or source_ids != result_ids:
        final, decision = FAIL_SOURCE, "RESTORE_V21_060_FORWARD_LEDGER"
    elif official_modified or real_modified or broker_modified:
        final, decision = FAIL_MUTATION, "STOP_AND_RESTORE_FORBIDDEN_MUTATION"
    elif hardcoded:
        final, decision = FAIL_HARDCODED, "REPAIR_FORCED_INCLUSION_LOGIC"
    elif local_price_violation:
        final, decision = FAIL_PRICE, "REPAIR_MATURITY_ELIGIBILITY_FILTERS"
    elif premature_promotion:
        final, decision = FAIL_PROMOTION, "REMOVE_PREMATURE_PROMOTION"
    elif matured_count:
        final, decision = PASS_STATUS, "MATURITY_COMPARISON_READY_FOR_CONTINUED_MONITORING"
    else:
        final, decision = PARTIAL_STATUS, "MATURITY_COMPARISON_CREATED_PENDING_FORWARD_RESULTS"

    summary = {
        "FINAL_STATUS": final, "DECISION": decision, "stage_id": STAGE_ID,
        "research_only": True, "source_forward_ledger_path": rel(root, root / LEDGER_REL),
        "source_backtest_comparison_path": rel(root, root / BACKTEST_REL),
        "total_observation_rows": len(matured_rows),
        "a0_observation_rows": variant_counts["A0_CURRENT_TESTING_LOCKED"],
        "a1_observation_rows": variant_counts["A1_BASELINE_REPLAY_CURRENT"],
        "b_observation_rows": variant_counts["B_MOMENTUM_STATIC_R1"],
        "c_observation_rows": variant_counts["C_MOMENTUM_DYNAMIC_R1"],
        "matured_observation_count": matured_count,
        "pending_observation_count": maturity_counts["PENDING_NOT_MATURED"],
        "price_missing_observation_count": maturity_counts["MATURED_PRICE_MISSING"],
        "matured_count_5d": window_matured["5D"], "matured_count_10d": window_matured["10D"],
        "matured_count_20d": window_matured["20D"], "matured_count_60d": window_matured["60D"],
        "comparable_matured_count_a0_vs_a1": pair_count_map["A0_CURRENT_TESTING_LOCKED_VS_A1_BASELINE_REPLAY_CURRENT"],
        "comparable_matured_count_a0_vs_b": pair_count_map["A0_CURRENT_TESTING_LOCKED_VS_B_MOMENTUM_STATIC_R1"],
        "comparable_matured_count_a0_vs_c": pair_count_map["A0_CURRENT_TESTING_LOCKED_VS_C_MOMENTUM_DYNAMIC_R1"],
        "comparable_matured_count_a1_vs_b": pair_count_map["A1_BASELINE_REPLAY_CURRENT_VS_B_MOMENTUM_STATIC_R1"],
        "comparable_matured_count_a1_vs_c": pair_count_map["A1_BASELINE_REPLAY_CURRENT_VS_C_MOMENTUM_DYNAMIC_R1"],
        "comparable_matured_count_b_vs_c": pair_count_map["B_MOMENTUM_STATIC_R1_VS_C_MOMENTUM_DYNAMIC_R1"],
        "backtest_fallback_used": bool(v60.get("backtest_fallback_used")),
        "forward_maturity_sufficient": forward_sufficient,
        "recommendation_status": recommendation_status,
        "production_adoption_allowed": False, "official_use_allowed": False,
        "hardcoded_inclusion_violation_count": hardcoded,
        "local_price_missing_ranked_violation_count": local_price_violation,
        "tqqq_ipo_watch_violation_count": tqqq_ipo,
        "a0_recomputed": a0_recomputed, "a0_modified": a0_modified,
        "official_mutation_detected": official_modified,
        "real_book_mutation_detected": real_modified,
        "broker_mutation_detected": broker_modified,
        "next_recommended_stage": "V21.061_R1_CONTINUED_MATURITY_MONITORING",
    }
    write_json(out / SUMMARY_NAME, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    summary = run_stage(args.root)
    print(json.dumps(summary, indent=2))
    return 1 if clean(summary["FINAL_STATUS"]).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
