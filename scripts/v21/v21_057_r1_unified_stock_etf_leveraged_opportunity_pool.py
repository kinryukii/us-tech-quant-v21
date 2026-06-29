#!/usr/bin/env python
"""Create the research-only V21 unified stock/ETF opportunity universe."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable


STAGE_ID = "V21.057-R1"
PASS_STATUS = "PASS_V21_057_R1_UNIFIED_OPPORTUNITY_POOL_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_057_R1_UNIFIED_POOL_READY_WITH_DATA_WARN"
BLOCKED_AUDIT = "BLOCKED_V21_057_R1_FORCED_AUDIT_INCOMPLETE"
BLOCKED_POOL = "BLOCKED_V21_057_R1_UNIFIED_POOL_NOT_CREATED"
FAIL_STATUS = "FAIL_V21_057_R1_FORBIDDEN_MUTATION_DETECTED"

OUT_REL = Path("outputs/v21/unified_pool")
SEED_REL = Path("configs/v21/etf_universe_seed.csv")
STOCK_REL = Path("outputs/v18/candidates/V18_CURRENT_RANKED_CANDIDATES.csv")
A0_REL = Path("outputs/v21/experiments/version_control/V21_056_R2_A0_CANONICAL_CONTROL_VIEW.csv")
R1_SNAPSHOT_REL = Path("outputs/v21/experiments/version_control/V21_056_R1_A0_LEDGER_SNAPSHOT.csv")

POOL_NAME = "V21_057_R1_UNIFIED_OPPORTUNITY_POOL.csv"
ELIGIBLE_NAME = "V21_057_R1_ELIGIBLE_UNIFIED_POOL.csv"
SEED_AUDIT_NAME = "V21_057_R1_ETF_SEED_AUDIT.csv"
FORCED_NAME = "V21_057_R1_FORCED_TICKER_AUDIT.csv"
DUPLICATE_NAME = "V21_057_R1_DUPLICATE_TICKER_AUDIT.csv"
DATA_NAME = "V21_057_R1_DATA_AVAILABILITY_AUDIT.csv"
LINEAGE_NAME = "V21_057_R1_LINEAGE_AUDIT.csv"
SUMMARY_NAME = "V21_057_R1_SUMMARY.json"

FORCED = ("MU", "SNDK", "DRAM", "SMH", "SOXX", "SOXL", "USD", "QQQ", "TQQQ", "SQQQ")
POOL_FIELDS = [
    "ticker", "instrument_type", "asset_class", "theme", "underlying_index",
    "issuer", "leverage_multiplier", "direction", "is_inverse",
    "is_daily_reset", "is_leveraged", "is_core_market_proxy",
    "is_sector_proxy", "is_thematic_proxy", "selection_lane",
    "max_shadow_weight", "real_book_allowed", "nisa_candidate_allowed",
    "research_only", "source_membership", "source_candidate_path",
    "in_stock_candidate_universe", "in_etf_seed", "duplicate_ticker_resolved",
    "data_available", "price_available", "volume_available", "latest_price_date",
    "price_freshness_status", "eligible_for_unified_pool", "exclusion_reason",
    "tactical_only", "hedge_only", "daily_reset_risk_flag",
    "leverage_decay_risk_flag", "default_risk_size_bucket",
    "default_trade_permission", "notes",
]
FORCED_FIELDS = [
    "ticker", "present_in_stock_universe", "present_in_etf_seed",
    "present_in_unified_pool", "eligible_for_unified_pool", "instrument_type",
    "theme", "price_available", "volume_available", "latest_price_date",
    "price_freshness_status", "exclusion_reason", "source_membership",
    "research_only", "notes",
]
DATA_FIELDS = [
    "ticker", "instrument_type", "price_available", "volume_available",
    "latest_price_date", "price_freshness_status", "data_available",
    "eligible_for_unified_pool", "price_source", "research_only",
]


def clean(value: object) -> str:
    return str(value or "").strip()


def tf(value: object) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return "TRUE" if clean(value).upper() == "TRUE" else "FALSE"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


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


def valid_ticker(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", value))


def row_count(path: Path) -> int:
    return len(read_csv(path)[0])


def protected_hashes(root: Path) -> dict[str, dict[str, str]]:
    groups = {"a0": {}, "official": {}, "real_book": {}, "broker": {}}
    for target in (root / A0_REL, root / R1_SNAPSHOT_REL):
        if target.is_file():
            groups["a0"][rel(root, target)] = sha(target)
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


def differences(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))


def parse_date(value: object) -> date | None:
    try:
        return datetime.strptime(clean(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def price_map(root: Path, stock_rows: list[dict[str, str]]) -> tuple[dict[str, dict[str, str]], list[str]]:
    prices: dict[str, dict[str, str]] = {}
    sources: list[str] = []

    def add(ticker: str, day: str, has_price: bool, has_volume: bool, source: Path) -> None:
        ticker = ticker.upper()
        if not ticker or not day or not has_price:
            return
        current = prices.get(ticker)
        if current is None or day > current["latest_price_date"]:
            prices[ticker] = {
                "latest_price_date": day,
                "price_available": "TRUE",
                "volume_available": tf(has_volume),
                "price_source": rel(root, source),
            }
        elif day == current["latest_price_date"] and has_volume:
            current["volume_available"] = "TRUE"

    stock_path = root / STOCK_REL
    for row in stock_rows:
        ticker = clean(row.get("ticker")).upper()
        day = clean(row.get("latest_price_date"))
        has_price = bool(clean(row.get("latest_close")))
        add(ticker, day, has_price, False, stock_path)
    if stock_path.is_file():
        sources.append(rel(root, stock_path))

    consolidation = root / "outputs/v20/consolidation"
    certifications = []
    if consolidation.exists():
        certifications = sorted(
            consolidation.glob("V20_47_*_CURRENT_*_PRICE_CERTIFICATION.csv"),
            key=lambda path: path.name,
        )[-8:]
    for path in certifications:
        rows, _ = read_csv(path)
        for row in rows:
            ticker = clean(row.get("ticker")).upper()
            day = clean(row.get("latest_price_date"))
            status = clean(row.get("refresh_status") or row.get("certification_status")).upper()
            price = clean(row.get("latest_close") or row.get("close_like_price") or row.get("latest_adj_close"))
            volume = clean(row.get("latest_volume"))
            add(ticker, day, bool(price) and status not in {"FAILED", "MISSING"}, bool(volume), path)
        sources.append(rel(root, path))

    etf_cache = consolidation / "V20_98C_R2_CONTROLLED_ETF_PRICE_REFRESH_CACHE.csv"
    etf_rows, _ = read_csv(etf_cache)
    for row in etf_rows:
        status = clean(row.get("certification_status")).upper()
        add(
            clean(row.get("ticker")), clean(row.get("latest_price_date")),
            bool(clean(row.get("latest_price"))) and status == "CERTIFIED",
            False, etf_cache,
        )
    if etf_cache.is_file():
        sources.append(rel(root, etf_cache))

    depth_path = root / "outputs/v21/factors/V21_037_R1_HISTORICAL_OHLCV_TICKER_DEPTH_AFTER_INGESTION.csv"
    depth_rows, _ = read_csv(depth_path)
    for row in depth_rows:
        ticker = clean(row.get("ticker")).upper()
        day = clean(row.get("max_date"))
        count = int(clean(row.get("row_count")) or "0")
        add(ticker, day, count > 0, tf(row.get("volume_ma20_ready")) == "TRUE" or count > 0, depth_path)
    if depth_path.is_file():
        sources.append(rel(root, depth_path))
    return prices, sorted(set(sources))


def risk_fields(row: dict[str, str]) -> dict[str, str]:
    instrument = clean(row.get("instrument_type"))
    multiplier = abs(float(clean(row.get("leverage_multiplier")) or "1"))
    inverse = instrument == "INVERSE_ETF" or tf(row.get("is_inverse")) == "TRUE"
    leveraged = instrument == "LEVERAGED_LONG_ETF"
    if inverse:
        return {
            "tactical_only": "TRUE", "hedge_only": "TRUE",
            "daily_reset_risk_flag": "TRUE", "leverage_decay_risk_flag": "TRUE",
            "default_risk_size_bucket": "WATCH_ONLY",
            "default_trade_permission": "HEDGE_ONLY_RESEARCH",
        }
    if leveraged:
        return {
            "tactical_only": "TRUE", "hedge_only": "FALSE",
            "daily_reset_risk_flag": "TRUE", "leverage_decay_risk_flag": "TRUE",
            "default_risk_size_bucket": "HALF_SIZE_ONLY" if multiplier == 2 else "QUARTER_SIZE_ONLY",
            "default_trade_permission": "TACTICAL_ONLY_RESEARCH",
        }
    return {
        "tactical_only": "FALSE", "hedge_only": "FALSE",
        "daily_reset_risk_flag": "FALSE", "leverage_decay_risk_flag": "FALSE",
        "default_risk_size_bucket": "NORMAL_SIZE_ALLOWED",
        "default_trade_permission": "WATCH_ONLY_RESEARCH",
    }


def freshness(day_text: str, reference: date | None) -> str:
    day = parse_date(day_text)
    if not day:
        return "MISSING_PRICE"
    if not reference:
        return "UNKNOWN"
    return "FRESH" if (reference - day).days <= 3 else "STALE_WARN"


def run_stage(root: Path) -> dict[str, object]:
    root = root.resolve()
    out = root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    seed_path, stock_path, a0_path = root / SEED_REL, root / STOCK_REL, root / A0_REL
    before = protected_hashes(root)
    stock_rows, _ = read_csv(stock_path)
    seed_rows, seed_fields = read_csv(seed_path)
    a0_count = row_count(a0_path)
    prices, price_sources = price_map(root, stock_rows)
    reference_dates = [parse_date(row.get("latest_price_date")) for row in stock_rows]
    reference = max((day for day in reference_dates if day), default=None)

    stocks: dict[str, dict[str, str]] = {}
    for source in stock_rows:
        ticker = clean(source.get("ticker")).upper()
        if not valid_ticker(ticker):
            continue
        stocks[ticker] = {
            "ticker": ticker, "instrument_type": "STOCK", "asset_class": "EQUITY",
            "theme": "", "underlying_index": "", "issuer": "",
            "leverage_multiplier": "1", "direction": "LONG", "is_inverse": "FALSE",
            "is_daily_reset": "FALSE", "is_leveraged": "FALSE",
            "is_core_market_proxy": "FALSE", "is_sector_proxy": "FALSE",
            "is_thematic_proxy": "FALSE", "selection_lane": "STOCK_LANE",
            "max_shadow_weight": "", "real_book_allowed": "FALSE",
            "nisa_candidate_allowed": "TRUE", "research_only": "TRUE",
            "source_candidate_path": rel(root, stock_path),
            "notes": "Current stock candidate; existing rank/score lineage preserved and not recomputed.",
        }
    seeds = {clean(row.get("ticker")).upper(): {**row, "ticker": clean(row.get("ticker")).upper()} for row in seed_rows if valid_ticker(clean(row.get("ticker")).upper())}
    duplicates = sorted(set(stocks) & set(seeds))
    tickers = sorted(set(stocks) | set(seeds))
    pool: list[dict[str, object]] = []
    for ticker in tickers:
        in_stock, in_seed = ticker in stocks, ticker in seeds
        base = dict(seeds[ticker] if in_seed else stocks[ticker])
        base.update({
            "ticker": ticker,
            "source_membership": "STOCK_CANDIDATE|ETF_SEED" if in_stock and in_seed else "ETF_SEED" if in_seed else "STOCK_CANDIDATE",
            "source_candidate_path": rel(root, stock_path) if in_stock else rel(root, seed_path),
            "in_stock_candidate_universe": tf(in_stock),
            "in_etf_seed": tf(in_seed),
            "duplicate_ticker_resolved": tf(in_stock and in_seed),
            "research_only": "TRUE",
            "real_book_allowed": "FALSE",
        })
        evidence = prices.get(ticker, {})
        price_available = evidence.get("price_available", "FALSE")
        volume_available = evidence.get("volume_available", "FALSE")
        latest = evidence.get("latest_price_date", "")
        instrument = clean(base.get("instrument_type"))
        if instrument == "STOCK":
            eligible = valid_ticker(ticker) and ticker in stocks
        else:
            eligible = price_available == "TRUE"
        base.update({
            "data_available": price_available,
            "price_available": price_available,
            "volume_available": volume_available,
            "latest_price_date": latest,
            "price_freshness_status": freshness(latest, reference),
            "eligible_for_unified_pool": tf(eligible),
            "exclusion_reason": "" if eligible else "MISSING_PRICE_DATA",
            **risk_fields(base),
        })
        pool.append(base)

    write_csv(out / POOL_NAME, pool, POOL_FIELDS)
    write_csv(out / ELIGIBLE_NAME, (row for row in pool if row["eligible_for_unified_pool"] == "TRUE"), POOL_FIELDS)
    by_ticker = {clean(row["ticker"]): row for row in pool}
    seed_audit = []
    for seed in seed_rows:
        ticker = clean(seed.get("ticker")).upper()
        joined = by_ticker.get(ticker, {})
        seed_audit.append({
            **{field: seed.get(field, "") for field in seed_fields},
            "entered_unified_pool": tf(bool(joined)),
            "eligible_for_unified_pool": joined.get("eligible_for_unified_pool", "FALSE"),
            "price_available": joined.get("price_available", "FALSE"),
            "exclusion_reason": joined.get("exclusion_reason", "NOT_IN_UNIFIED_POOL"),
        })
    write_csv(out / SEED_AUDIT_NAME, seed_audit, seed_fields + ["entered_unified_pool", "eligible_for_unified_pool", "price_available", "exclusion_reason"])

    forced_rows = []
    for ticker in FORCED:
        row = by_ticker.get(ticker, {})
        forced_rows.append({
            "ticker": ticker,
            "present_in_stock_universe": tf(ticker in stocks),
            "present_in_etf_seed": tf(ticker in seeds),
            "present_in_unified_pool": tf(bool(row)),
            "eligible_for_unified_pool": row.get("eligible_for_unified_pool", "FALSE"),
            "instrument_type": row.get("instrument_type", ""),
            "theme": row.get("theme", ""),
            "price_available": row.get("price_available", "FALSE"),
            "volume_available": row.get("volume_available", "FALSE"),
            "latest_price_date": row.get("latest_price_date", ""),
            "price_freshness_status": row.get("price_freshness_status", "MISSING_PRICE"),
            "exclusion_reason": row.get("exclusion_reason", "NOT_IN_UNIFIED_POOL"),
            "source_membership": row.get("source_membership", ""),
            "research_only": "TRUE",
            "notes": row.get("notes", "Forced audit ticker retained even when absent from pool."),
        })
    write_csv(out / FORCED_NAME, forced_rows, FORCED_FIELDS)
    duplicate_rows = [{
        "ticker": ticker, "stock_candidate_path": rel(root, stock_path),
        "etf_seed_path": rel(root, seed_path), "resolution": "ETF_METADATA_PREFERRED",
        "kept_in_unified_pool": "TRUE", "research_only": "TRUE",
        "notes": "Single ticker row retained with richer ETF metadata.",
    } for ticker in duplicates]
    write_csv(out / DUPLICATE_NAME, duplicate_rows, ["ticker", "stock_candidate_path", "etf_seed_path", "resolution", "kept_in_unified_pool", "research_only", "notes"])
    write_csv(out / DATA_NAME, ({
        "ticker": row["ticker"], "instrument_type": row["instrument_type"],
        "price_available": row["price_available"], "volume_available": row["volume_available"],
        "latest_price_date": row["latest_price_date"], "price_freshness_status": row["price_freshness_status"],
        "data_available": row["data_available"], "eligible_for_unified_pool": row["eligible_for_unified_pool"],
        "price_source": prices.get(clean(row["ticker"]), {}).get("price_source", ""),
        "research_only": "TRUE",
    } for row in pool), DATA_FIELDS)

    after = protected_hashes(root)
    a0_changes = differences(before["a0"], after["a0"])
    official_changes = differences(before["official"], after["official"])
    real_changes = differences(before["real_book"], after["real_book"])
    broker_changes = differences(before["broker"], after["broker"])
    a0_modified = bool(a0_changes)
    official_modified = bool(official_changes)
    real_modified = bool(real_changes)
    broker_modified = bool(broker_changes)
    lineage = [
        {"lineage_item": "stock_candidate_source", "source_path": rel(root, stock_path), "row_count": len(stock_rows), "status": "READ_ONLY", "a0_modified": tf(a0_modified), "research_only": "TRUE", "notes": "Current V18 source used by V21.056-R2 lineage."},
        {"lineage_item": "etf_seed", "source_path": rel(root, seed_path), "row_count": len(seed_rows), "status": "LOADED", "a0_modified": tf(a0_modified), "research_only": "TRUE", "notes": "Research-only configured ETF universe."},
        {"lineage_item": "a0_canonical_control", "source_path": rel(root, a0_path), "row_count": a0_count, "status": "READ_ONLY_UNMODIFIED" if not a0_modified else "MUTATED", "a0_modified": tf(a0_modified), "research_only": "TRUE", "notes": "A0 rank/score lineage note: JOINED_FROM_CURRENT_V18_RANKING_SOURCE"},
        {"lineage_item": "a0_rank_score_lineage", "source_path": rel(root, stock_path), "row_count": len(stock_rows), "status": "PRESERVED", "a0_modified": tf(a0_modified), "research_only": "TRUE", "notes": "JOINED_FROM_CURRENT_V18_RANKING_SOURCE; no V21.057 rank or score computed."},
    ]
    lineage.extend({
        "lineage_item": "price_data_source", "source_path": source,
        "row_count": row_count(root / source), "status": "READ_ONLY",
        "a0_modified": tf(a0_modified), "research_only": "TRUE",
        "notes": "Local price/volume availability evidence."
    } for source in price_sources)
    write_csv(out / LINEAGE_NAME, lineage, ["lineage_item", "source_path", "row_count", "status", "a0_modified", "research_only", "notes"])

    type_counts = Counter(clean(row["instrument_type"]) for row in pool)
    forced_missing = len(set(FORCED) - {row["ticker"] for row in forced_rows})
    missing_price = sum(row["price_available"] != "TRUE" for row in pool)
    stale_price = sum(row["price_freshness_status"] == "STALE_WARN" for row in pool)
    seed_missing_price = sum(
        by_ticker.get(ticker, {}).get("price_available") != "TRUE" for ticker in seeds
    )
    forbidden = a0_modified or official_modified or real_modified or broker_modified
    pool_created = (out / POOL_NAME).is_file() and bool(pool)
    audit_complete = {row["ticker"] for row in forced_rows} == set(FORCED)
    if forbidden:
        final, decision = FAIL_STATUS, "STOP_AND_RESTORE_FORBIDDEN_MUTATION"
    elif not audit_complete:
        final, decision = BLOCKED_AUDIT, "FIX_FORCED_AUDIT_BEFORE_MOMENTUM_TRACKER"
    elif not pool_created:
        final, decision = BLOCKED_POOL, "FIX_UNIFIED_POOL_BEFORE_MOMENTUM_TRACKER"
    elif seed_missing_price:
        final, decision = PARTIAL_STATUS, "UNIFIED_POOL_READY_FOR_MOMENTUM_WITH_PRICE_DATA_WARN_REVIEW"
    else:
        final, decision = PASS_STATUS, "UNIFIED_POOL_READY_FOR_V21_058_MOMENTUM_TRACKER"
    summary = {
        "FINAL_STATUS": final, "DECISION": decision, "stage_id": STAGE_ID,
        "research_only": True, "official_use_allowed": False,
        "production_adoption_allowed": False, "broker_execution_allowed": False,
        "real_book_mutation_allowed": False,
        "stock_candidate_source_path": rel(root, stock_path),
        "a0_canonical_control_path": rel(root, a0_path),
        "a0_canonical_control_row_count": a0_count, "a0_modified": a0_modified,
        "total_unified_pool_count": len(pool),
        "eligible_unified_pool_count": sum(row["eligible_for_unified_pool"] == "TRUE" for row in pool),
        "stock_count": type_counts["STOCK"], "core_etf_count": type_counts["CORE_ETF"],
        "sector_etf_count": type_counts["SECTOR_ETF"], "thematic_etf_count": type_counts["THEMATIC_ETF"],
        "leveraged_long_etf_count": type_counts["LEVERAGED_LONG_ETF"],
        "inverse_etf_count": type_counts["INVERSE_ETF"], "forced_audit_count": len(forced_rows),
        "forced_audit_missing_count": forced_missing, "missing_price_count": missing_price,
        "stale_price_count": stale_price, "duplicate_ticker_count": len(duplicates),
        "official_mutation_detected": official_modified,
        "real_book_mutation_detected": real_modified,
        "broker_mutation_detected": broker_modified,
        "next_recommended_stage": "V21.058_MOMENTUM_TRACKER" if final in {PASS_STATUS, PARTIAL_STATUS} else "REPAIR_V21_057_R1_UNIFIED_POOL",
    }
    write_json(out / SUMMARY_NAME, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    summary = run_stage(args.root)
    print(json.dumps(summary, indent=2))
    return 1 if summary["FINAL_STATUS"] in {FAIL_STATUS, BLOCKED_AUDIT, BLOCKED_POOL} else 0


if __name__ == "__main__":
    raise SystemExit(main())
