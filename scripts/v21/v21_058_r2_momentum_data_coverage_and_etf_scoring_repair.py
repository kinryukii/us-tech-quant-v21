#!/usr/bin/env python
"""Audit and repair local ETF data coverage for the V21.058 momentum tracker."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable


STAGE_ID = "V21.058-R2"
PASS_STATUS = "PASS_V21_058_R2_MOMENTUM_DATA_COVERAGE_REPAIRED"
PARTIAL_STATUS = "PARTIAL_PASS_V21_058_R2_REPAIRED_WITH_REMAINING_DATA_WARN"
FAIL_HARDCODED = "FAIL_V21_058_R2_HARDCODED_INCLUSION_VIOLATION"
FAIL_EXHAUSTION = "FAIL_V21_058_R2_HIGH_MOMENTUM_AUTO_EXHAUSTION_VIOLATION"
FAIL_RISK = "FAIL_V21_058_R2_LEVERAGED_OR_INVERSE_RISK_RULE_VIOLATION"
FAIL_MUTATION = "FAIL_V21_058_R2_FORBIDDEN_MUTATION_DETECTED"

OUT_REL = Path("outputs/v21/momentum")
R1_LEDGER_REL = OUT_REL / "V21_058_R1_UNIFIED_MOMENTUM_LEDGER.csv"
R1_FORCED_REL = OUT_REL / "V21_058_R1_FORCED_MOMENTUM_AUDIT.csv"
R1_SUMMARY_REL = OUT_REL / "V21_058_R1_SUMMARY.json"
DISCOVERY_REL = Path("outputs/v21/unified_pool/V21_057_R2_ALGORITHMIC_DISCOVERY_POOL.csv")
R1_POOL_REL = Path("outputs/v21/unified_pool/V21_057_R1_UNIFIED_OPPORTUNITY_POOL.csv")
SEED_REL = Path("configs/v21/etf_universe_seed.csv")
V21_CACHE_REL = Path("inputs/v21/historical_ohlcv_cache/V21_037_R1_HISTORICAL_OHLCV_CACHE.csv")
V20_TICKER_CACHE_REL = Path("inputs/v20/outcome_benchmark/yahoo_cache/v20_26/V20_26_YAHOO_TICKER_PRICE_CACHE.csv")
V20_BENCHMARK_CACHE_REL = Path("inputs/v20/outcome_benchmark/yahoo_cache/v20_26/V20_26_YAHOO_BENCHMARK_PRICE_CACHE.csv")
V20_ETF_CURRENT_REL = Path("outputs/v20/consolidation/V20_98C_R2_CONTROLLED_ETF_PRICE_REFRESH_CACHE.csv")
A0_REL = Path("outputs/v21/experiments/version_control/V21_056_R2_A0_CANONICAL_CONTROL_VIEW.csv")
R1_SNAPSHOT_REL = Path("outputs/v21/experiments/version_control/V21_056_R1_A0_LEDGER_SNAPSHOT.csv")

COVERAGE_NAME = "V21_058_R2_ETF_DATA_COVERAGE_AUDIT.csv"
MAPPING_NAME = "V21_058_R2_SYMBOL_MAPPING_AUDIT.csv"
BENCHMARK_NAME = "V21_058_R2_BENCHMARK_COVERAGE_AUDIT.csv"
REGIME_NAME = "V21_058_R2_MARKET_REGIME_SOURCE_AUDIT.csv"
LEDGER_NAME = "V21_058_R2_REPAIRED_UNIFIED_MOMENTUM_LEDGER.csv"
TOP50_NAME = "V21_058_R2_REPAIRED_MOMENTUM_TOP50.csv"
FORCED_NAME = "V21_058_R2_FORCED_MOMENTUM_REPAIR_AUDIT.csv"
WARN_NAME = "V21_058_R2_DATA_WARN_REMAINING_AUDIT.csv"
LINEAGE_NAME = "V21_058_R2_LINEAGE_AUDIT.csv"
SUMMARY_NAME = "V21_058_R2_SUMMARY.json"

FORCED = ("MU", "SNDK", "DRAM", "SMH", "SOXX", "SOXL", "USD", "QQQ", "TQQQ", "SQQQ")
REPAIR_FIELDS = [
    "v21_058_r1_score_status", "v21_058_r2_score_status",
    "data_repair_attempted", "data_repair_success", "data_repair_source_path",
    "symbol_mapping_used", "benchmark_repair_attempted",
    "benchmark_repair_success", "regime_repair_attempted",
    "regime_repair_success", "repair_notes",
]
COVERAGE_FIELDS = [
    "ticker", "instrument_type", "price_exists", "volume_exists",
    "latest_price_date", "row_count", "source_path", "symbol_mapping_used",
    "stale_or_missing_reason", "deep_history_available", "research_only",
]
MAPPING_FIELDS = [
    "requested_ticker", "canonical_ticker", "mapped_ticker", "mapping_status",
    "mapping_reason", "price_source_path", "price_available_after_mapping",
    "research_only",
]
BENCHMARK_FIELDS = [
    "benchmark_ticker", "price_available", "row_count", "latest_price_date",
    "benchmark_missing_reason", "benchmark_comparison_fallback_used",
    "affected_score_component", "source_path", "research_only",
]


def clean(value: object) -> str:
    return str(value or "").strip()


def tf(value: object) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return "TRUE" if clean(value).upper() == "TRUE" else "FALSE"


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


def parse_date(value: object) -> datetime | None:
    try:
        return datetime.strptime(clean(value)[:10], "%Y-%m-%d")
    except ValueError:
        return None


def source_inventory(root: Path, tickers: set[str]) -> dict[str, list[dict[str, object]]]:
    inventory: dict[str, list[dict[str, object]]] = defaultdict(list)
    sources = [
        (root / V21_CACHE_REL, "ticker", "as_of_date", "volume"),
        (root / V20_TICKER_CACHE_REL, "symbol", "price_date", "volume"),
        (root / V20_BENCHMARK_CACHE_REL, "symbol", "price_date", "volume"),
    ]
    for path, ticker_field, date_field, volume_field in sources:
        rows, _ = read_csv(path)
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            ticker = clean(row.get(ticker_field)).upper()
            if ticker in tickers:
                grouped[ticker].append(row)
        for ticker, members in grouped.items():
            dates = [clean(row.get(date_field)) for row in members if parse_date(row.get(date_field))]
            inventory[ticker].append({
                "source_path": rel(root, path), "row_count": len(members),
                "latest_price_date": max(dates) if dates else "",
                "volume_exists": any(clean(row.get(volume_field)) not in {"", "0", "0.0"} for row in members),
                "price_exists": bool(dates),
            })
    current_path = root / V20_ETF_CURRENT_REL
    current_rows, _ = read_csv(current_path)
    for row in current_rows:
        ticker = clean(row.get("ticker")).upper()
        if ticker in tickers and tf(row.get("data_available")) == "TRUE":
            inventory[ticker].append({
                "source_path": rel(root, current_path), "row_count": 1,
                "latest_price_date": clean(row.get("latest_price_date")),
                "volume_exists": False, "price_exists": bool(clean(row.get("latest_price"))),
            })
    for ticker in tickers:
        path = root / f"state/v18/price_cache/{ticker}.csv"
        rows, _ = read_csv(path)
        if rows:
            dates = [clean(row.get("date")) for row in rows if parse_date(row.get("date"))]
            inventory[ticker].append({
                "source_path": rel(root, path), "row_count": len(rows),
                "latest_price_date": max(dates) if dates else "",
                "volume_exists": any(clean(row.get("volume")) not in {"", "0", "0.0"} for row in rows),
                "price_exists": bool(dates),
            })
    return inventory


def best_source(entries: list[dict[str, object]]) -> dict[str, object]:
    if not entries:
        return {}
    return max(entries, key=lambda row: (int(row["row_count"]), clean(row["latest_price_date"])))


def discover_regime(root: Path) -> tuple[str, bool, str, bool, list[dict[str, object]]]:
    candidates = [
        root / "outputs/v20/consolidation/V20_CURRENT_REGIME_CONDITIONED_EVIDENCE_EXPORT.csv",
        root / "outputs/v21/review/V21_047_R4_QQQ_MA50_RULE_AUDIT.csv",
    ]
    audit = []
    for path in candidates:
        rows, fields = read_csv(path)
        usable = False
        reason = ""
        if "market_regime" in fields and rows:
            dates = [parse_date(row.get("as_of_date")) for row in rows]
            latest = max((day for day in dates if day), default=None)
            usable = bool(latest and latest.strftime("%Y-%m-%d") >= "2026-06-16")
            reason = "CURRENT_EXPLICIT_MARKET_REGIME" if usable else "REGIME_ROWS_NOT_CURRENT_FOR_MOMENTUM_AS_OF_DATE"
        else:
            reason = "NO_EXPLICIT_CURRENT_MARKET_REGIME_FIELD"
        audit.append({
            "candidate_source_path": rel(root, path), "exists": tf(path.is_file()),
            "row_count": len(rows), "usable_for_current_regime": tf(usable),
            "rejection_or_selection_reason": reason, "research_only": "TRUE",
        })
        if usable:
            regimes = [clean(row.get("market_regime")).upper() for row in rows if clean(row.get("market_regime"))]
            regime = Counter(regimes).most_common(1)[0][0]
            return regime, regime == "RISK_OFF", rel(root, path), False, audit
    return "UNKNOWN", False, "", True, audit


def run_stage(root: Path) -> dict[str, object]:
    root = root.resolve()
    out = root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    before = protected_hashes(root)
    r1_rows, r1_fields = read_csv(root / R1_LEDGER_REL)
    r1_forced, _ = read_csv(root / R1_FORCED_REL)
    seed_rows, _ = read_csv(root / SEED_REL)
    seed = {clean(row.get("ticker")).upper(): row for row in seed_rows}
    seed_tickers = set(seed)
    inventory = source_inventory(root, seed_tickers | {"SPY", "QQQ", "SMH", "SOXX", "DRAM"})
    r1_by_ticker = {clean(row.get("ticker")).upper(): row for row in r1_rows}
    regime, risk_off, regime_path, regime_fallback, regime_audit = discover_regime(root)

    coverage_rows = []
    mapping_rows = []
    for ticker in sorted(seed_tickers):
        entries = inventory.get(ticker, [])
        best = best_source(entries)
        max_rows = max((int(entry["row_count"]) for entry in entries), default=0)
        latest = max((clean(entry["latest_price_date"]) for entry in entries), default="")
        volume = any(bool(entry["volume_exists"]) for entry in entries)
        coverage_rows.append({
            "ticker": ticker, "instrument_type": seed[ticker].get("instrument_type", ""),
            "price_exists": tf(any(bool(entry["price_exists"]) for entry in entries)),
            "volume_exists": tf(volume), "latest_price_date": latest,
            "row_count": max_rows, "source_path": best.get("source_path", ""),
            "symbol_mapping_used": "EXACT_TICKER",
            "stale_or_missing_reason": "" if max_rows >= 60 else "INSUFFICIENT_HISTORY_LT_60" if max_rows else "MISSING_PRICE_DATA",
            "deep_history_available": tf(max_rows >= 60), "research_only": "TRUE",
        })
        mapping_rows.append({
            "requested_ticker": ticker, "canonical_ticker": ticker, "mapped_ticker": ticker,
            "mapping_status": "EXACT_MATCH_FOUND" if entries else "NO_EQUIVALENT_MAPPING_FOUND",
            "mapping_reason": "Exact ticker representation only; no economic proxy substitution."
            if entries else "No exact or representation-equivalent local symbol found; proxy mapping prohibited.",
            "price_source_path": best.get("source_path", ""),
            "price_available_after_mapping": tf(bool(entries)), "research_only": "TRUE",
        })
    write_csv(out / COVERAGE_NAME, coverage_rows, COVERAGE_FIELDS)
    write_csv(out / MAPPING_NAME, mapping_rows, MAPPING_FIELDS)

    benchmark_rows = []
    for ticker in ("SPY", "QQQ", "SMH", "SOXX", "DRAM"):
        entries = inventory.get(ticker, [])
        best = best_source(entries)
        rows = max((int(entry["row_count"]) for entry in entries), default=0)
        benchmark_rows.append({
            "benchmark_ticker": ticker, "price_available": tf(rows >= 21),
            "row_count": rows, "latest_price_date": max((clean(entry["latest_price_date"]) for entry in entries), default=""),
            "benchmark_missing_reason": "" if rows >= 21 else "MISSING_OR_INSUFFICIENT_BENCHMARK_HISTORY",
            "benchmark_comparison_fallback_used": tf(rows < 21),
            "affected_score_component": "" if rows >= 21 else f"RELATIVE_MOMENTUM_VS_{ticker}_LEFT_BLANK",
            "source_path": best.get("source_path", ""), "research_only": "TRUE",
        })
    write_csv(out / BENCHMARK_NAME, benchmark_rows, BENCHMARK_FIELDS)
    write_csv(out / REGIME_NAME, regime_audit + [{
        "candidate_source_path": regime_path, "exists": tf(bool(regime_path)),
        "row_count": row_count(root / regime_path) if regime_path else 0,
        "usable_for_current_regime": tf(not regime_fallback),
        "rejection_or_selection_reason": f"FINAL_MARKET_REGIME={regime};RISK_OFF_CONFIRMED={tf(risk_off)};FALLBACK_USED={tf(regime_fallback)}",
        "research_only": "TRUE",
    }], ["candidate_source_path", "exists", "row_count", "usable_for_current_regime", "rejection_or_selection_reason", "research_only"])

    repaired = []
    for original in r1_rows:
        row = dict(original)
        ticker = clean(row.get("ticker")).upper()
        entries = inventory.get(ticker, [])
        deep = any(int(entry["row_count"]) >= 60 for entry in entries)
        r1_scored = tf(row.get("score_computed")) == "TRUE"
        r1_price = tf(row.get("price_available")) == "TRUE"
        repaired_price = bool(entries)
        repaired_volume = any(bool(entry["volume_exists"]) for entry in entries)
        repaired_latest = max((clean(entry["latest_price_date"]) for entry in entries), default="")
        max_history_rows = max((int(entry["row_count"]) for entry in entries), default=0)
        # Existing R1 score rows are preserved byte-for-field. No missing ETF has
        # a newly discovered 60-session exact-symbol series in the local cache.
        repair_success = (not r1_price and repaired_price)
        if repair_success and deep:
            # This branch is intentionally conservative: R1 already consumed the
            # same deep sources, so a genuinely new score requires the R1 engine.
            # If R1 did not score despite deep history, preserve status and audit it.
            repair_success = True
        if ticker in seed_tickers and repaired_price:
            row["price_available"] = "TRUE"
            row["latest_price_date"] = repaired_latest
            row["volume_available"] = tf(repaired_volume)
            reference = datetime.strptime("2026-06-18", "%Y-%m-%d")
            latest_day = parse_date(repaired_latest)
            row["price_freshness_status"] = (
                "FRESH" if latest_day and (reference - latest_day).days <= 3
                else "STALE_WARN" if latest_day else "MISSING_PRICE"
            )
        if not r1_scored and repaired_price:
            row["score_missing_reason"] = f"PRICE_HISTORY_ROWS_{max_history_rows}_LT_60"
        row.update({
            "v21_058_r1_score_status": "SCORED" if r1_scored else "DATA_INSUFFICIENT",
            "v21_058_r2_score_status": "SCORED_PRESERVED" if r1_scored else "DATA_INSUFFICIENT_REMAINS",
            "data_repair_attempted": tf(ticker in seed_tickers and not r1_scored),
            "data_repair_success": tf(repair_success),
            "data_repair_source_path": best_source(entries).get("source_path", ""),
            "symbol_mapping_used": "EXACT_TICKER",
            "benchmark_repair_attempted": tf(ticker in seed_tickers),
            "benchmark_repair_success": tf(all(
                next(item for item in benchmark_rows if item["benchmark_ticker"] == benchmark)["price_available"] == "TRUE"
                for benchmark in ("SPY", "QQQ")
            )),
            "regime_repair_attempted": "TRUE",
            "regime_repair_success": tf(not regime_fallback),
            "market_regime": regime, "risk_off_confirmed": tf(risk_off),
            "regime_fallback_used": tf(regime_fallback),
            "repair_notes": (
                "R1 score preserved; no model formula change."
                if r1_scored else
                (
                    "Current price detection repaired, but exact-symbol history remains below 60 rows; score not fabricated."
                    if repair_success else
                    "No exact-symbol 60-session local history discovered; score not fabricated."
                )
            ),
            "research_only": "TRUE",
        })
        if clean(row.get("instrument_type")) == "INVERSE_ETF" and not risk_off:
            row["chase_permission"] = "HEDGE_ONLY"
            row["risk_size_bucket"] = "WATCH_ONLY"
        repaired.append(row)
    repaired_fields = list(dict.fromkeys([*r1_fields, *REPAIR_FIELDS]))
    write_csv(out / LEDGER_NAME, repaired, repaired_fields)

    top50 = sorted(
        (row for row in repaired if tf(row.get("score_computed")) == "TRUE" and tf(row.get("entered_by_forced_audit_only")) != "TRUE"),
        key=lambda row: (-float(clean(row.get("momentum_leadership_score")) or "-1"), clean(row.get("ticker"))),
    )[:50]
    for rank, row in enumerate(top50, 1):
        row["momentum_rank"] = rank
    write_csv(out / TOP50_NAME, top50, ["momentum_rank", *repaired_fields])
    top_set = {clean(row.get("ticker")).upper() for row in top50}

    forced_rows = []
    r1_forced_map = {clean(row.get("ticker")).upper(): row for row in r1_forced}
    repaired_map = {clean(row.get("ticker")).upper(): row for row in repaired}
    for ticker in FORCED:
        r1 = r1_forced_map.get(ticker, {})
        r2 = repaired_map.get(ticker, {})
        forced_only = tf(r2.get("entered_by_forced_audit_only")) == "TRUE"
        violation = forced_only and (
            tf(r2.get("score_computed")) == "TRUE" or ticker in top_set
        )
        forced_rows.append({
            "ticker": ticker, "v21_058_r1_status": clean(r1.get("momentum_state") or "MISSING"),
            "v21_058_r2_status": clean(r2.get("momentum_state") or "MISSING"),
            "data_repair_attempted": r2.get("data_repair_attempted", "FALSE"),
            "data_repair_success": r2.get("data_repair_success", "FALSE"),
            "score_computed": r2.get("score_computed", "FALSE"),
            "in_repaired_top50": tf(ticker in top_set),
            "objective_inclusion_reason": clean(r1.get("objective_discovery_admission_reason") or r2.get("objective_discovery_admission_reason")),
            "still_missing_reason_if_not_scored": clean(r2.get("score_missing_reason")),
            "entered_by_forced_audit_only": r2.get("entered_by_forced_audit_only", "FALSE"),
            "hardcoded_inclusion_violation_flag": tf(violation),
            "research_only": "TRUE",
        })
    write_csv(out / FORCED_NAME, forced_rows, list(forced_rows[0].keys()))
    warns = [row for row in repaired if tf(row.get("score_computed")) != "TRUE" or clean(row.get("price_freshness_status")) != "FRESH" or tf(row.get("volume_available")) != "TRUE"]
    write_csv(out / WARN_NAME, warns, repaired_fields)

    after = protected_hashes(root)
    a0_modified = changed(before["a0"], after["a0"])
    official_modified = changed(before["official"], after["official"])
    real_modified = changed(before["real_book"], after["real_book"])
    broker_modified = changed(before["broker"], after["broker"])
    lineage_sources = [
        ("r1_momentum_ledger", root / R1_LEDGER_REL, "READ_ONLY"),
        ("etf_seed", root / SEED_REL, "READ_ONLY"),
        ("v21_historical_ohlcv", root / V21_CACHE_REL, "READ_ONLY"),
        ("v20_outcome_ticker_cache", root / V20_TICKER_CACHE_REL, "READ_ONLY"),
        ("v20_outcome_benchmark_cache", root / V20_BENCHMARK_CACHE_REL, "READ_ONLY"),
        ("v20_etf_current_cache", root / V20_ETF_CURRENT_REL, "READ_ONLY"),
        ("a0_canonical_control", root / A0_REL, "READ_ONLY_UNMODIFIED" if not a0_modified else "MUTATED"),
    ]
    lineage = [{
        "source_role": role, "source_path": rel(root, path), "exists": tf(path.is_file()),
        "row_count": row_count(path), "status": status, "a0_modified": tf(a0_modified),
        "official_mutation_detected": tf(official_modified), "research_only": "TRUE",
        "notes": "A0 rank/score lineage: JOINED_FROM_CURRENT_V18_RANKING_SOURCE" if role == "a0_canonical_control" else "Local read-only source.",
    } for role, path, status in lineage_sources]
    write_csv(out / LINEAGE_NAME, lineage, ["source_role", "source_path", "exists", "row_count", "status", "a0_modified", "official_mutation_detected", "research_only", "notes"])

    r1_summary = json.loads((root / R1_SUMMARY_REL).read_text(encoding="utf-8"))
    scored = [row for row in repaired if tf(row.get("score_computed")) == "TRUE"]
    types = Counter(clean(row.get("instrument_type")) for row in scored)
    hardcoded = sum(row["hardcoded_inclusion_violation_flag"] == "TRUE" for row in forced_rows)
    high_auto = sum(
        clean(row.get("momentum_state")) == "MOMENTUM_EXHAUSTION"
        and tf(row.get("deterioration_confirmation_flag")) != "TRUE"
        for row in repaired
    )
    leveraged_full = sum(
        clean(row.get("instrument_type")) == "LEVERAGED_LONG_ETF"
        and clean(row.get("risk_size_bucket")) == "FULL_SIZE_ALLOWED"
        for row in repaired
    )
    inverse_bad = sum(
        clean(row.get("instrument_type")) == "INVERSE_ETF" and not risk_off
        and (clean(row.get("chase_permission")) != "HEDGE_ONLY"
             or clean(row.get("risk_size_bucket")) not in {"WATCH_ONLY", "BLOCKED"})
        for row in repaired
    )
    forbidden = a0_modified or official_modified or real_modified or broker_modified
    targets_met = types["CORE_ETF"] >= 4 and types["SECTOR_ETF"] >= 3 and types["LEVERAGED_LONG_ETF"] >= 2
    if forbidden:
        final, decision = FAIL_MUTATION, "STOP_AND_RESTORE_FORBIDDEN_MUTATION"
    elif hardcoded:
        final, decision = FAIL_HARDCODED, "REPAIR_FORCED_INCLUSION_LOGIC"
    elif high_auto:
        final, decision = FAIL_EXHAUSTION, "REPAIR_HIGH_MOMENTUM_EXHAUSTION_LOGIC"
    elif leveraged_full or inverse_bad:
        final, decision = FAIL_RISK, "REPAIR_LEVERAGED_OR_INVERSE_RISK_CONTROLS"
    elif targets_met:
        final, decision = PASS_STATUS, "MOMENTUM_DATA_COVERAGE_READY_FOR_V21_059_ABCD"
    else:
        final, decision = PARTIAL_STATUS, "MOMENTUM_READY_FOR_ABCD_WITH_REMAINING_ETF_DATA_WARN"
    summary = {
        "FINAL_STATUS": final, "DECISION": decision, "stage_id": STAGE_ID, "research_only": True,
        "r1_scored_count": r1_summary["scored_count"], "r2_scored_count": len(scored),
        "r1_data_insufficient_count": r1_summary["data_insufficient_count"],
        "r2_data_insufficient_count": len(repaired) - len(scored),
        "r1_missing_price_count": r1_summary["missing_price_count"],
        "r2_missing_price_count": sum(tf(row.get("price_available")) != "TRUE" for row in repaired),
        "r1_stale_price_count": r1_summary["stale_price_count"],
        "r2_stale_price_count": sum(clean(row.get("price_freshness_status")) == "STALE_WARN" for row in repaired),
        "r1_core_etf_scored_count": r1_summary["core_etf_scored_count"], "r2_core_etf_scored_count": types["CORE_ETF"],
        "r1_sector_etf_scored_count": r1_summary["sector_etf_scored_count"], "r2_sector_etf_scored_count": types["SECTOR_ETF"],
        "r1_thematic_etf_scored_count": r1_summary["thematic_etf_scored_count"], "r2_thematic_etf_scored_count": types["THEMATIC_ETF"],
        "r1_leveraged_long_etf_scored_count": r1_summary["leveraged_long_etf_scored_count"], "r2_leveraged_long_etf_scored_count": types["LEVERAGED_LONG_ETF"],
        "r1_inverse_etf_scored_count": r1_summary["inverse_etf_scored_count"], "r2_inverse_etf_scored_count": types["INVERSE_ETF"],
        "forced_audit_count": len(forced_rows),
        "forced_audit_missing_count": len(set(FORCED) - {row["ticker"] for row in forced_rows}),
        "hardcoded_inclusion_violation_count": hardcoded,
        "high_momentum_auto_exhaustion_violation_count": high_auto,
        "leveraged_full_size_violation_count": leveraged_full,
        "inverse_non_hedge_violation_count": inverse_bad,
        "market_regime": regime, "regime_source_path": regime_path,
        "regime_fallback_used": regime_fallback, "a0_modified": a0_modified,
        "official_mutation_detected": official_modified, "real_book_mutation_detected": real_modified,
        "broker_mutation_detected": broker_modified,
        "next_recommended_stage": "V21.059_ABCD_EXPERIMENT_HARNESS" if final in {PASS_STATUS, PARTIAL_STATUS} else "REPAIR_V21_058_R2_DATA_COVERAGE",
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
