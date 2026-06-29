#!/usr/bin/env python
"""Apply objective limited-history and IPO-watch momentum policy."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable


STAGE_ID = "V21.058-R3"
PASS_STATUS = "PASS_V21_058_R3_NEWLY_LISTED_MOMENTUM_POLICY_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_058_R3_READY_WITH_LOCAL_PRICE_DATA_WARN"
FAIL_HARDCODED = "FAIL_V21_058_R3_HARDCODED_INCLUSION_VIOLATION"
FAIL_POLICY = "FAIL_V21_058_R3_LIMITED_HISTORY_POLICY_VIOLATION"
FAIL_MUTATION = "FAIL_V21_058_R3_FORBIDDEN_MUTATION_DETECTED"

OUT_REL = Path("outputs/v21/momentum")
R2_LEDGER_REL = OUT_REL / "V21_058_R2_REPAIRED_UNIFIED_MOMENTUM_LEDGER.csv"
R2_TOP50_REL = OUT_REL / "V21_058_R2_REPAIRED_MOMENTUM_TOP50.csv"
R2_FORCED_REL = OUT_REL / "V21_058_R2_FORCED_MOMENTUM_REPAIR_AUDIT.csv"
R2_SUMMARY_REL = OUT_REL / "V21_058_R2_SUMMARY.json"
DISCOVERY_REL = Path("outputs/v21/unified_pool/V21_057_R2_ALGORITHMIC_DISCOVERY_POOL.csv")
PRICE_REL = Path("inputs/v21/historical_ohlcv_cache/V21_037_R1_HISTORICAL_OHLCV_CACHE.csv")
V20_TICKER_REL = Path("inputs/v20/outcome_benchmark/yahoo_cache/v20_26/V20_26_YAHOO_TICKER_PRICE_CACHE.csv")
V20_BENCHMARK_REL = Path("inputs/v20/outcome_benchmark/yahoo_cache/v20_26/V20_26_YAHOO_BENCHMARK_PRICE_CACHE.csv")
A0_REL = Path("outputs/v21/experiments/version_control/V21_056_R2_A0_CANONICAL_CONTROL_VIEW.csv")
R1_SNAPSHOT_REL = Path("outputs/v21/experiments/version_control/V21_056_R1_A0_LEDGER_SNAPSHOT.csv")

POLICY_NAME = "V21_058_R3_NEWLY_LISTED_POLICY_AUDIT.csv"
SPACEX_NAME = "V21_058_R3_SPACEX_SPCX_ALIAS_AND_DATA_AUDIT.csv"
LEDGER_NAME = "V21_058_R3_NEWLY_LISTED_MOMENTUM_LEDGER.csv"
BOARD_NAME = "V21_058_R3_NEWLY_LISTED_MOMENTUM_BOARD.csv"
TOP50_NAME = "V21_058_R3_REPAIRED_MOMENTUM_TOP50.csv"
FORCED_NAME = "V21_058_R3_FORCED_DIAGNOSTIC_AUDIT.csv"
LINEAGE_NAME = "V21_058_R3_LINEAGE_AUDIT.csv"
SUMMARY_NAME = "V21_058_R3_SUMMARY.json"

FORCED = ("SPCX", "DRAM", "USD", "MU", "SNDK", "SMH", "SOXX", "SOXL", "QQQ", "TQQQ", "SQQQ")
R3_FIELDS = [
    "newly_listed_policy_bucket", "listing_age_price_rows",
    "full_history_score_available", "limited_history_score_available",
    "ipo_watch_score_available", "limited_history_flag", "ipo_watch_flag",
    "skipped_full_history_indicators", "return_since_first_available_close",
    "relative_return_vs_SPY_since_listing", "relative_return_vs_QQQ_since_listing",
    "ipo_early_momentum_score", "limited_history_momentum_score",
    "full_history_momentum_score", "final_momentum_score_for_r3",
    "r3_score_status", "r3_score_scope", "r3_risk_size_cap", "r3_notes",
]


def clean(value: object) -> str:
    return str(value or "").strip()


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


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.10f}"


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


def row_count(path: Path) -> int:
    return len(read_csv(path)[0])


def protected_hashes(root: Path) -> dict[str, dict[str, str]]:
    groups = {"a0": {}, "official": {}, "real_book": {}, "broker": {}}
    for path in (root / A0_REL, root / R1_SNAPSHOT_REL):
        if path.is_file():
            groups["a0"][rel(root, path)] = sha(path)
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
            elif "official" in text and any(word in text for word in ("rank", "weight", "recommend", "allocation")):
                groups["official"][rel(root, path)] = sha(path)
    return groups


def changed(before: dict[str, str], after: dict[str, str]) -> bool:
    return any(before.get(key) != after.get(key) for key in set(before) | set(after))


def series_inventory(root: Path, tickers: set[str]) -> tuple[dict[str, list[tuple[str, float, float | None]]], list[str]]:
    series: dict[str, dict[str, tuple[float, float | None]]] = defaultdict(dict)
    used_sources: list[str] = []
    source_specs = [
        (root / PRICE_REL, "ticker", "as_of_date", ("adjusted_close", "close"), "volume"),
        (root / V20_TICKER_REL, "symbol", "price_date", ("adjusted_close", "close"), "volume"),
        (root / V20_BENCHMARK_REL, "symbol", "price_date", ("adjusted_close", "close"), "volume"),
    ]
    for path, ticker_field, date_field, price_fields, volume_field in source_specs:
        rows, _ = read_csv(path)
        matched = False
        for row in rows:
            ticker = clean(row.get(ticker_field)).upper()
            if ticker not in tickers:
                continue
            price = next((num(row.get(field)) for field in price_fields if num(row.get(field)) is not None), None)
            day = clean(row.get(date_field))[:10]
            try:
                datetime.strptime(day, "%Y-%m-%d")
            except ValueError:
                continue
            if price is not None and price > 0:
                series[ticker][day] = (price, num(row.get(volume_field)))
                matched = True
        if matched:
            used_sources.append(rel(root, path))
    for ticker in tickers:
        path = root / f"state/v18/price_cache/{ticker}.csv"
        rows, _ = read_csv(path)
        if rows:
            for row in rows:
                day = clean(row.get("date"))[:10]
                price = num(row.get("adj_close")) or num(row.get("close"))
                if price is not None and price > 0:
                    series[ticker][day] = (price, num(row.get("volume")))
            used_sources.append(rel(root, path))
    return {
        ticker: [(day, price, volume) for day, (price, volume) in sorted(values.items())]
        for ticker, values in series.items()
    }, sorted(set(used_sources))


def policy_bucket(rows: int) -> str:
    if rows >= 60:
        return "FULL_HISTORY_SCORING"
    if rows >= 20:
        return "LIMITED_HISTORY_SCORING"
    if rows >= 5:
        return "IPO_EARLY_MOMENTUM_WATCH"
    return "DATA_INSUFFICIENT"


def period_return(values: list[tuple[str, float, float | None]], window: int) -> float | None:
    return values[-1][1] / values[-window - 1][1] - 1 if len(values) > window else None


def benchmark_listing_return(
    benchmark: list[tuple[str, float, float | None]],
    start_day: str,
    end_day: str,
) -> float | None:
    selected = [item for item in benchmark if start_day <= item[0] <= end_day]
    return selected[-1][1] / selected[0][1] - 1 if len(selected) >= 2 else None


def limited_score(values: list[tuple[str, float, float | None]], spy: list, qqq: list) -> tuple[float, dict[str, float | None]]:
    since = values[-1][1] / values[0][1] - 1
    returns = {window: period_return(values, window) for window in (3, 5, 10, 20)}
    spy_return = benchmark_listing_return(spy, values[0][0], values[-1][0])
    qqq_return = benchmark_listing_return(qqq, values[0][0], values[-1][0])
    relative = [since - benchmark for benchmark in (spy_return, qqq_return) if benchmark is not None]
    ma5 = sum(item[1] for item in values[-5:]) / 5
    ma10 = sum(item[1] for item in values[-10:]) / 10 if len(values) >= 10 else ma5
    ma20 = sum(item[1] for item in values[-20:]) / 20 if len(values) >= 20 else ma10
    trend = sum((values[-1][1] > ma5, values[-1][1] > ma10, values[-1][1] > ma20)) / 3
    return_component = np_clip(50 + 200 * np_mean([value for value in returns.values() if value is not None] + [since]), 0, 100)
    relative_component = np_clip(50 + 250 * np_mean(relative), 0, 100) if relative else 50
    score = 0.55 * return_component + 0.30 * relative_component + 0.15 * trend * 100
    return score, {"since": since, "spy": spy_return, "qqq": qqq_return, **{f"r{window}": value for window, value in returns.items()}}


def ipo_score(values: list[tuple[str, float, float | None]], spy: list, qqq: list) -> tuple[float, dict[str, float | None]]:
    since = values[-1][1] / values[0][1] - 1
    r3, r5 = period_return(values, 3), period_return(values, 5)
    spy_return = benchmark_listing_return(spy, values[0][0], values[-1][0])
    qqq_return = benchmark_listing_return(qqq, values[0][0], values[-1][0])
    relative = [since - benchmark for benchmark in (spy_return, qqq_return) if benchmark is not None]
    recent_volumes = [item[2] for item in values[-3:] if item[2] is not None]
    earlier_volumes = [item[2] for item in values[:-3] if item[2] is not None]
    volume_ratio = (
        np_mean(recent_volumes) / np_mean(earlier_volumes)
        if recent_volumes and earlier_volumes and np_mean(earlier_volumes) > 0 else None
    )
    strength = np_clip(50 + 250 * np_mean([value for value in (since, r3, r5) if value is not None]), 0, 100)
    relative_component = np_clip(50 + 250 * np_mean(relative), 0, 100) if relative else 50
    volume_component = np_clip(50 + 25 * ((volume_ratio or 1) - 1), 0, 100)
    score = 0.55 * strength + 0.30 * relative_component + 0.15 * volume_component
    return score, {"since": since, "spy": spy_return, "qqq": qqq_return, "r3": r3, "r5": r5, "volume_ratio": volume_ratio}


def np_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def np_clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def run_stage(root: Path) -> dict[str, object]:
    root = root.resolve()
    out = root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    before = protected_hashes(root)
    r2_rows, r2_fields = read_csv(root / R2_LEDGER_REL)
    discovery_rows, _ = read_csv(root / DISCOVERY_REL)
    discovery = {clean(row.get("ticker")).upper(): row for row in discovery_rows}
    tickers = {clean(row.get("ticker")).upper() for row in r2_rows} | {"SPCX", "SPY", "QQQ"}
    series, price_sources = series_inventory(root, tickers)
    spy, qqq = series.get("SPY", []), series.get("QQQ", [])

    ledger = [dict(row) for row in r2_rows]
    if "SPCX" not in {clean(row.get("ticker")).upper() for row in ledger}:
        ledger.append({
            "ticker": "SPCX", "instrument_type": "STOCK", "asset_class": "EQUITY",
            "source_membership": "SPACEX_ALIAS_DIAGNOSTIC_ONLY",
            "entered_by_existing_candidate_universe": "FALSE",
            "entered_by_price_universe_discovery": "FALSE",
            "entered_by_relative_strength_discovery": "FALSE",
            "entered_by_theme_discovery": "FALSE", "entered_by_etf_seed": "FALSE",
            "entered_by_forced_audit_only": "TRUE",
            "objective_discovery_admission_reason": "NO_LOCAL_PRICE_DATA_OBJECTIVE_DISCOVERY_NOT_MET",
            "eligible_for_unified_pool": "FALSE", "price_available": "FALSE",
            "volume_available": "FALSE", "price_freshness_status": "MISSING_PRICE",
            "score_computed": "FALSE", "score_missing_reason": "MISSING_PRICE_DATA",
            "momentum_state": "DATA_INSUFFICIENT", "chase_permission": "WATCH_ONLY_DATA_WARN",
            "risk_size_bucket": "WATCH_ONLY", "market_regime": "UNKNOWN",
            "risk_off_confirmed": "FALSE", "regime_fallback_used": "TRUE", "research_only": "TRUE",
        })

    for row in ledger:
        ticker = clean(row.get("ticker")).upper()
        values = series.get(ticker, [])
        count = len(values)
        bucket = policy_bucket(count)
        is_full = bucket == "FULL_HISTORY_SCORING"
        is_limited = bucket == "LIMITED_HISTORY_SCORING"
        is_ipo = bucket == "IPO_EARLY_MOMENTUM_WATCH"
        full_score = num(row.get("momentum_leadership_score")) if is_full and tf(row.get("score_computed")) == "TRUE" else None
        limited = ipo = None
        stats: dict[str, float | None] = {"since": None, "spy": None, "qqq": None}
        if is_limited:
            limited, stats = limited_score(values, spy, qqq)
        elif is_ipo:
            ipo, stats = ipo_score(values, spy, qqq)
        instrument = clean(row.get("instrument_type"))
        leverage = abs(num(row.get("leverage_multiplier")) or 1)
        if is_limited:
            cap = "QUARTER_SIZE_ONLY" if instrument == "LEVERAGED_LONG_ETF" or leverage > 1 else "HALF_SIZE_ONLY"
            row["risk_size_bucket"] = cap
            row["momentum_state"] = "LEADER_CONTINUING" if (limited or 0) >= 60 else "MOMENTUM_DECAY"
            row["chase_permission"] = "ALLOW_SMALL_SIZE_CHASE" if (limited or 0) >= 65 else "WATCH_ONLY_DATA_WARN"
        elif is_ipo:
            cap = "QUARTER_SIZE_ONLY"
            row["risk_size_bucket"] = cap
            row["momentum_state"] = "IPO_EARLY_MOMENTUM_WATCH"
            objective_strong = (ipo or 0) >= 70 and bool(values) and all(item[2] is not None for item in values)
            row["chase_permission"] = "ALLOW_SMALL_SIZE_CHASE" if objective_strong else "WATCH_ONLY_DATA_WARN"
        elif is_full:
            cap = clean(row.get("risk_size_bucket"))
        else:
            cap = "WATCH_ONLY"
            row["momentum_state"] = "DATA_INSUFFICIENT"
            row["chase_permission"] = "HEDGE_ONLY" if instrument == "INVERSE_ETF" else "WATCH_ONLY_DATA_WARN"
            row["risk_size_bucket"] = "WATCH_ONLY"
        if instrument == "INVERSE_ETF" and tf(row.get("risk_off_confirmed")) != "TRUE":
            row["chase_permission"], row["risk_size_bucket"] = "HEDGE_ONLY", "WATCH_ONLY"
            cap = "WATCH_ONLY"
        row.update({
            "newly_listed_policy_bucket": bucket,
            "listing_age_price_rows": count,
            "full_history_score_available": tf(full_score is not None),
            "limited_history_score_available": tf(limited is not None),
            "ipo_watch_score_available": tf(ipo is not None),
            "limited_history_flag": tf(is_limited),
            "ipo_watch_flag": tf(is_ipo),
            "skipped_full_history_indicators": (
                "" if is_full else
                "MA50|MA60|NEW_60D_HIGH|DRAWDOWN_FROM_60D_HIGH" if is_limited else
                "MA10|MA20|MA50|MA60|RSI14|MACD|NEW_20D_HIGH|NEW_60D_HIGH|FULL_MOMENTUM_LEADERSHIP_SCORE"
                if is_ipo else "ALL_MOMENTUM_INDICATORS"
            ),
            "return_since_first_available_close": fmt(stats.get("since")),
            "relative_return_vs_SPY_since_listing": fmt(
                stats.get("since") - stats.get("spy")
                if stats.get("since") is not None and stats.get("spy") is not None else None
            ),
            "relative_return_vs_QQQ_since_listing": fmt(
                stats.get("since") - stats.get("qqq")
                if stats.get("since") is not None and stats.get("qqq") is not None else None
            ),
            "ipo_early_momentum_score": fmt(ipo),
            "limited_history_momentum_score": fmt(limited),
            "full_history_momentum_score": fmt(full_score),
            "final_momentum_score_for_r3": fmt(full_score if full_score is not None else limited),
            "r3_score_status": (
                "FULL_HISTORY_SCORE_PRESERVED" if full_score is not None else
                "LIMITED_HISTORY_SCORE_COMPUTED" if limited is not None else
                "IPO_WATCH_SCORE_COMPUTED_NON_TOP50" if ipo is not None else
                "DATA_INSUFFICIENT"
            ),
            "r3_score_scope": (
                "COMPARABLE_FULL_HISTORY" if full_score is not None else
                "COMPARABLE_LIMITED_HISTORY_WITH_RISK_CAP" if limited is not None else
                "SEPARATE_IPO_WATCH_BOARD_ONLY" if ipo is not None else "UNSCORED"
            ),
            "r3_risk_size_cap": cap,
            "r3_notes": (
                "Existing full-history score preserved." if is_full else
                "Limited-history indicators only; unsupported full-history fields remain unavailable." if is_limited else
                "IPO early-watch score is diagnostic and excluded from combined Top50." if is_ipo else
                "Fewer than five exact-symbol price rows; no score fabricated."
            ),
            "research_only": "TRUE",
        })

    fields = list(dict.fromkeys([*r2_fields, *R3_FIELDS]))
    write_csv(out / LEDGER_NAME, ledger, fields)
    board = [row for row in ledger if row["newly_listed_policy_bucket"] != "FULL_HISTORY_SCORING"]
    write_csv(out / BOARD_NAME, board, fields)
    top50 = sorted(
        (
            row for row in ledger
            if row["r3_score_scope"] in {"COMPARABLE_FULL_HISTORY", "COMPARABLE_LIMITED_HISTORY_WITH_RISK_CAP"}
            and tf(row.get("entered_by_forced_audit_only")) != "TRUE"
            and num(row.get("final_momentum_score_for_r3")) is not None
        ),
        key=lambda row: (-float(row["final_momentum_score_for_r3"]), clean(row.get("ticker"))),
    )[:50]
    for rank, row in enumerate(top50, 1):
        row["momentum_rank"] = rank
    write_csv(out / TOP50_NAME, top50, ["momentum_rank", *fields])
    top_set = {clean(row.get("ticker")).upper() for row in top50}

    policy_rows = [
        {"newly_listed_policy_bucket": "FULL_HISTORY_SCORING", "minimum_rows": 60, "maximum_rows": "", "ranking_scope": "COMBINED_TOP50", "risk_cap": "TYPE_AWARE_EXISTING_CAP", "research_only": "TRUE", "notes": "Existing V21.058-R2 full-history score preserved."},
        {"newly_listed_policy_bucket": "LIMITED_HISTORY_SCORING", "minimum_rows": 20, "maximum_rows": 59, "ranking_scope": "COMBINED_TOP50_IF_OBJECTIVE_SCORE_QUALIFIES", "risk_cap": "HALF_SIZE_OR_QUARTER_IF_LEVERAGED", "research_only": "TRUE", "notes": "No MA50/60D indicators; limited score explicitly labeled."},
        {"newly_listed_policy_bucket": "IPO_EARLY_MOMENTUM_WATCH", "minimum_rows": 5, "maximum_rows": 19, "ranking_scope": "SEPARATE_WATCH_BOARD_ONLY", "risk_cap": "QUARTER_SIZE_ONLY", "research_only": "TRUE", "notes": "No full momentum leadership score."},
        {"newly_listed_policy_bucket": "DATA_INSUFFICIENT", "minimum_rows": 0, "maximum_rows": 4, "ranking_scope": "UNSCORED", "risk_cap": "WATCH_ONLY", "research_only": "TRUE", "notes": "No price fabrication."},
    ]
    write_csv(out / POLICY_NAME, policy_rows, list(policy_rows[0].keys()))

    spcx_values = series.get("SPCX", [])
    spcx_bucket = policy_bucket(len(spcx_values))
    aliases = ("SpaceX", "Space X", "Space Exploration Technologies")
    alias_rows = [{
        "requested_alias": alias, "canonical_company_name": "Space Exploration Technologies",
        "expected_ticker": "SPCX", "local_ticker_found": tf(bool(spcx_values)),
        "price_data_found": tf(bool(spcx_values)), "price_row_count": len(spcx_values),
        "latest_price_date": spcx_values[-1][0] if spcx_values else "",
        "listing_age_price_rows": len(spcx_values), "newly_listed_policy_bucket": spcx_bucket,
        "eligible_for_limited_history_scoring": tf(len(spcx_values) >= 20),
        "eligible_for_ipo_watch": tf(5 <= len(spcx_values) < 20),
        "exclusion_reason": "" if len(spcx_values) >= 5 else "MISSING_OR_FEWER_THAN_5_LOCAL_PRICE_ROWS",
        "research_only": "TRUE",
    } for alias in aliases]
    write_csv(out / SPACEX_NAME, alias_rows, list(alias_rows[0].keys()))

    by_ticker = {clean(row.get("ticker")).upper(): row for row in ledger}
    forced_rows = []
    for ticker in FORCED:
        row = by_ticker.get(ticker, {})
        forced_only = tf(row.get("entered_by_forced_audit_only")) == "TRUE"
        scored = clean(row.get("r3_score_status")) not in {"", "DATA_INSUFFICIENT"}
        violation = forced_only and (scored or ticker in top_set)
        forced_rows.append({
            "ticker": ticker, "present_in_r3_ledger": tf(bool(row)),
            "entered_by_forced_audit_only": tf(forced_only),
            "newly_listed_policy_bucket": row.get("newly_listed_policy_bucket", "DATA_INSUFFICIENT"),
            "listing_age_price_rows": row.get("listing_age_price_rows", 0),
            "r3_score_status": row.get("r3_score_status", "DATA_INSUFFICIENT"),
            "r3_score_scope": row.get("r3_score_scope", "UNSCORED"),
            "final_momentum_score_for_r3": row.get("final_momentum_score_for_r3", ""),
            "in_r3_top50": tf(ticker in top_set),
            "objective_inclusion_reason": row.get("objective_discovery_admission_reason", ""),
            "hardcoded_inclusion_violation_flag": tf(violation),
            "notes": "Diagnostic membership creates no eligibility, score, or Top50 override.",
            "research_only": "TRUE",
        })
    write_csv(out / FORCED_NAME, forced_rows, list(forced_rows[0].keys()))

    after = protected_hashes(root)
    a0_modified = changed(before["a0"], after["a0"])
    official_modified = changed(before["official"], after["official"])
    real_modified = changed(before["real_book"], after["real_book"])
    broker_modified = changed(before["broker"], after["broker"])
    lineage_sources = [
        ("r2_repaired_momentum_ledger", root / R2_LEDGER_REL),
        ("r2_repaired_top50", root / R2_TOP50_REL),
        ("algorithmic_discovery_pool", root / DISCOVERY_REL),
        ("v21_historical_ohlcv", root / PRICE_REL),
        ("v20_outcome_ticker_cache", root / V20_TICKER_REL),
        ("v20_outcome_benchmark_cache", root / V20_BENCHMARK_REL),
        ("a0_canonical_control", root / A0_REL),
    ]
    lineage = [{
        "source_role": role, "source_path": rel(root, path), "exists": tf(path.is_file()),
        "row_count": row_count(path), "status": "READ_ONLY_UNMODIFIED",
        "a0_modified": tf(a0_modified), "official_mutation_detected": tf(official_modified),
        "research_only": "TRUE", "notes": "No source mutation; exact-symbol local data only.",
    } for role, path in lineage_sources]
    lineage.extend({
        "source_role": "per_symbol_price_cache", "source_path": source,
        "exists": "TRUE", "row_count": row_count(root / source),
        "status": "READ_ONLY", "a0_modified": tf(a0_modified),
        "official_mutation_detected": tf(official_modified), "research_only": "TRUE",
        "notes": "Exact-symbol cache used for listing-age classification.",
    } for source in price_sources if source.startswith("state/"))
    write_csv(out / LINEAGE_NAME, lineage, ["source_role", "source_path", "exists", "row_count", "status", "a0_modified", "official_mutation_detected", "research_only", "notes"])

    hardcoded = sum(row["hardcoded_inclusion_violation_flag"] == "TRUE" for row in forced_rows)
    forced_only_rows = [row for row in ledger if tf(row.get("entered_by_forced_audit_only")) == "TRUE"]
    forced_only_scored = sum(clean(row.get("r3_score_status")) not in {"", "DATA_INSUFFICIENT"} for row in forced_only_rows)
    forced_only_top50 = sum(clean(row.get("ticker")).upper() in top_set for row in forced_only_rows)
    policy_violation = sum(
        (row["newly_listed_policy_bucket"] != "FULL_HISTORY_SCORING" and row["full_history_score_available"] == "TRUE")
        or (row["newly_listed_policy_bucket"] == "IPO_EARLY_MOMENTUM_WATCH" and row["risk_size_bucket"] == "FULL_SIZE_ALLOWED")
        for row in ledger
    )
    high_auto = sum(
        clean(row.get("momentum_state")) == "MOMENTUM_EXHAUSTION"
        and tf(row.get("deterioration_confirmation_flag")) != "TRUE"
        for row in ledger
    )
    leveraged_full = sum(
        clean(row.get("instrument_type")) == "LEVERAGED_LONG_ETF"
        and clean(row.get("risk_size_bucket")) == "FULL_SIZE_ALLOWED"
        for row in ledger
    )
    inverse_bad = sum(
        clean(row.get("instrument_type")) == "INVERSE_ETF"
        and tf(row.get("risk_off_confirmed")) != "TRUE"
        and (clean(row.get("chase_permission")) != "HEDGE_ONLY"
             or clean(row.get("risk_size_bucket")) not in {"WATCH_ONLY", "BLOCKED"})
        for row in ledger
    )
    forbidden = a0_modified or official_modified or real_modified or broker_modified
    bucket_counts = Counter(row["newly_listed_policy_bucket"] for row in ledger)
    spcx = by_ticker["SPCX"]
    dram = by_ticker.get("DRAM", {})
    if forbidden:
        final, decision = FAIL_MUTATION, "STOP_AND_RESTORE_FORBIDDEN_MUTATION"
    elif hardcoded or forced_only_scored or forced_only_top50:
        final, decision = FAIL_HARDCODED, "REPAIR_FORCED_INCLUSION_LOGIC"
    elif policy_violation:
        final, decision = FAIL_POLICY, "REPAIR_LIMITED_HISTORY_POLICY"
    elif (not spcx_values) or not series.get("DRAM"):
        final, decision = PARTIAL_STATUS, "READY_FOR_ABCD_WITH_NEWLY_LISTED_PRICE_DATA_WARN"
    else:
        final, decision = PASS_STATUS, "NEWLY_LISTED_POLICY_READY_FOR_V21_059_ABCD"
    r2_summary = json.loads((root / R2_SUMMARY_REL).read_text(encoding="utf-8"))
    summary = {
        "FINAL_STATUS": final, "DECISION": decision, "stage_id": STAGE_ID, "research_only": True,
        "r2_scored_count": r2_summary["r2_scored_count"],
        "r3_full_history_scored_count": sum(row["full_history_score_available"] == "TRUE" for row in ledger),
        "r3_limited_history_scored_count": sum(row["limited_history_score_available"] == "TRUE" for row in ledger),
        "r3_ipo_watch_count": sum(row["ipo_watch_score_available"] == "TRUE" for row in ledger),
        "r3_data_insufficient_count": bucket_counts["DATA_INSUFFICIENT"],
        "newly_listed_candidate_count": bucket_counts["LIMITED_HISTORY_SCORING"] + bucket_counts["IPO_EARLY_MOMENTUM_WATCH"],
        "spcx_local_price_found": bool(spcx_values), "spcx_price_row_count": len(spcx_values),
        "spcx_newly_listed_policy_bucket": spcx["newly_listed_policy_bucket"],
        "spcx_score_status": spcx["r3_score_status"], "spcx_in_top50": "SPCX" in top_set,
        "dram_newly_listed_policy_bucket": dram.get("newly_listed_policy_bucket", "DATA_INSUFFICIENT"),
        "dram_score_status": dram.get("r3_score_status", "DATA_INSUFFICIENT"), "dram_in_top50": "DRAM" in top_set,
        "hardcoded_inclusion_violation_count": hardcoded,
        "forced_audit_only_scored_count": forced_only_scored,
        "forced_audit_only_top50_count": forced_only_top50,
        "limited_history_policy_violation_count": policy_violation,
        "high_momentum_auto_exhaustion_violation_count": high_auto,
        "leveraged_full_size_violation_count": leveraged_full,
        "inverse_non_hedge_violation_count": inverse_bad,
        "a0_modified": a0_modified, "official_mutation_detected": official_modified,
        "real_book_mutation_detected": real_modified, "broker_mutation_detected": broker_modified,
        "next_recommended_stage": "V21.059_ABCD_EXPERIMENT_HARNESS" if final in {PASS_STATUS, PARTIAL_STATUS} else "REPAIR_V21_058_R3_POLICY",
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
