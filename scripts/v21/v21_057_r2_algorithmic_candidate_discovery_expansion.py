#!/usr/bin/env python
"""Expand the V21 unified pool using objective local-data discovery filters."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Iterable


STAGE_ID = "V21.057-R2"
PASS_STATUS = "PASS_V21_057_R2_ALGORITHMIC_DISCOVERY_POOL_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_057_R2_DISCOVERY_READY_WITH_DATA_WARN"
FAIL_HARDCODED = "FAIL_V21_057_R2_HARDCODED_INCLUSION_VIOLATION"
FAIL_MUTATION = "FAIL_V21_057_R2_FORBIDDEN_MUTATION_DETECTED"

OUT_REL = Path("outputs/v21/unified_pool")
R1_POOL_REL = OUT_REL / "V21_057_R1_UNIFIED_OPPORTUNITY_POOL.csv"
STOCK_REL = Path("outputs/v18/candidates/V18_CURRENT_RANKED_CANDIDATES.csv")
SEED_REL = Path("configs/v21/etf_universe_seed.csv")
PRICE_REL = Path("inputs/v21/historical_ohlcv_cache/V21_037_R1_HISTORICAL_OHLCV_CACHE.csv")
DEPTH_REL = Path("outputs/v21/factors/V21_037_R1_HISTORICAL_OHLCV_TICKER_DEPTH_AFTER_INGESTION.csv")
METADATA_REL = Path("outputs/v20/consolidation/snapshots/V20_108_R8_R2_ENABLED_METADATA_CACHE.csv")
A0_REL = Path("outputs/v21/experiments/version_control/V21_056_R2_A0_CANONICAL_CONTROL_VIEW.csv")
R1_SNAPSHOT_REL = Path("outputs/v21/experiments/version_control/V21_056_R1_A0_LEDGER_SNAPSHOT.csv")

POOL_NAME = "V21_057_R2_ALGORITHMIC_DISCOVERY_POOL.csv"
ELIGIBLE_NAME = "V21_057_R2_ELIGIBLE_DISCOVERY_POOL.csv"
FORCED_NAME = "V21_057_R2_FORCED_AUDIT_DISCOVERY_EXPLANATION.csv"
SOURCE_NAME = "V21_057_R2_DISCOVERY_SOURCE_AUDIT.csv"
SUMMARY_NAME = "V21_057_R2_SUMMARY.json"

FORCED = ("MU", "SNDK", "DRAM", "SMH", "SOXX", "SOXL", "USD", "QQQ", "TQQQ", "SQQQ")
THEME_TERMS = (
    "semiconductor", "memory", "dram", "nand", "ai hardware",
    "artificial intelligence hardware", "data center", "datacenter",
    "storage product", "solid-state drive", "solid state drive",
)
POOL_FIELDS = [
    "ticker", "instrument_type", "source_membership",
    "entered_by_existing_candidate_universe", "entered_by_price_universe_discovery",
    "entered_by_relative_strength_discovery", "entered_by_theme_discovery",
    "entered_by_etf_seed", "entered_by_forced_audit_only",
    "eligible_for_unified_pool", "price_available", "volume_available",
    "latest_price_date", "price_freshness_status", "liquidity_filter_pass",
    "relative_strength_filter_pass", "theme_filter_pass",
    "discovery_filter_pass_count", "exclusion_reason", "research_only",
]
FORCED_FIELDS = POOL_FIELDS + ["objective_admission_reason", "forced_audit_effect"]
SOURCE_FIELDS = [
    "source_role", "source_path", "exists", "row_count", "usable",
    "fields_used", "research_only", "notes",
]


def clean(value: object) -> str:
    return str(value or "").strip()


def tf(value: object) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return "TRUE" if clean(value).upper() == "TRUE" else "FALSE"


def valid_ticker(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", value))


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
    if not path.is_file():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return sum(1 for _ in reader)


def parse_day(value: object) -> date | None:
    try:
        return datetime.strptime(clean(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


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


def differences(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))


def safe_float(value: object) -> float | None:
    try:
        parsed = float(clean(value))
        return parsed if math.isfinite(parsed) else None
    except ValueError:
        return None


def load_price_diagnostics(path: Path) -> tuple[dict[str, dict[str, object]], int]:
    series: dict[str, list[tuple[str, float, float | None]]] = defaultdict(list)
    rows_read = 0
    if not path.is_file():
        return {}, 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            rows_read += 1
            ticker = clean(row.get("ticker")).upper()
            day = clean(row.get("as_of_date"))
            price = safe_float(row.get("adjusted_close")) or safe_float(row.get("close"))
            volume = safe_float(row.get("volume"))
            if valid_ticker(ticker) and parse_day(day) and price is not None and price > 0:
                series[ticker].append((day, price, volume))
    for ticker in series:
        series[ticker].sort(key=lambda item: item[0])
    benchmark_returns: dict[str, dict[int, float]] = {}
    for benchmark in ("SPY", "QQQ"):
        values = series.get(benchmark, [])
        benchmark_returns[benchmark] = {
            window: values[-1][1] / values[-window - 1][1] - 1
            for window in (5, 10, 20) if len(values) > window
        }
    diagnostics: dict[str, dict[str, object]] = {}
    for ticker, values in series.items():
        returns = {
            window: values[-1][1] / values[-window - 1][1] - 1
            for window in (5, 10, 20) if len(values) > window
        }
        rs_passes = []
        for window, ticker_return in returns.items():
            comparisons = [
                ticker_return - benchmark_returns[benchmark][window]
                for benchmark in ("SPY", "QQQ")
                if window in benchmark_returns[benchmark]
            ]
            if comparisons:
                rs_passes.append(max(comparisons) > 0)
        recent_volumes = [value for _, _, value in values[-20:] if value is not None and value >= 0]
        avg_volume = sum(recent_volumes) / len(recent_volumes) if recent_volumes else None
        diagnostics[ticker] = {
            "history_rows": len(values),
            "latest_price_date": values[-1][0],
            "volume_available": bool(recent_volumes),
            "average_recent_volume": avg_volume,
            "liquidity_pass": avg_volume is not None and avg_volume >= 100_000,
            "relative_strength_pass": any(rs_passes),
            "relative_strength_available": bool(rs_passes),
        }
    return diagnostics, rows_read


def theme_map(path: Path) -> tuple[dict[str, bool], int]:
    rows, _ = read_csv(path)
    result: dict[str, bool] = {}
    for row in rows:
        ticker = clean(row.get("ticker")).upper()
        text = " ".join(clean(row.get(field)).lower() for field in (
            "sector", "industry", "industry_key", "sector_key", "category",
            "theme_hint", "business_summary",
        ))
        result[ticker] = any(term in text for term in THEME_TERMS)
    return result, len(rows)


def run_stage(root: Path) -> dict[str, object]:
    root = root.resolve()
    out = root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    before = protected_hashes(root)

    r1_rows, _ = read_csv(root / R1_POOL_REL)
    stock_rows, _ = read_csv(root / STOCK_REL)
    seed_rows, _ = read_csv(root / SEED_REL)
    depth_rows, _ = read_csv(root / DEPTH_REL)
    metadata, metadata_count = theme_map(root / METADATA_REL)
    price_diag, price_rows = load_price_diagnostics(root / PRICE_REL)

    r1 = {clean(row.get("ticker")).upper(): row for row in r1_rows if valid_ticker(clean(row.get("ticker")).upper())}
    existing = {clean(row.get("ticker")).upper() for row in stock_rows if valid_ticker(clean(row.get("ticker")).upper())}
    seeds = {clean(row.get("ticker")).upper(): row for row in seed_rows if valid_ticker(clean(row.get("ticker")).upper())}
    depth_tickers = {
        clean(row.get("ticker")).upper() for row in depth_rows
        if valid_ticker(clean(row.get("ticker")).upper()) and int(clean(row.get("row_count")) or "0") > 0
    }
    universe = sorted(set(r1) | set(existing) | set(seeds) | set(price_diag) | set(metadata) | set(FORCED))
    reference_days = [parse_day(diag.get("latest_price_date")) for diag in price_diag.values()]
    reference = max((day for day in reference_days if day), default=None)

    output: list[dict[str, object]] = []
    for ticker in universe:
        prior = r1.get(ticker, {})
        diag = price_diag.get(ticker, {})
        in_existing = ticker in existing
        in_seed = ticker in seeds
        in_price = ticker in price_diag or ticker in depth_tickers
        historical_price_available = bool(diag)
        price_available = historical_price_available or tf(prior.get("price_available")) == "TRUE"
        volume_available = bool(diag.get("volume_available")) or tf(prior.get("volume_available")) == "TRUE"
        latest = clean(diag.get("latest_price_date")) or clean(prior.get("latest_price_date"))
        latest_day = parse_day(latest)
        fresh = bool(reference and latest_day and (reference - latest_day).days <= 5)
        liquidity_pass = bool(diag.get("liquidity_pass"))
        rs_pass = bool(diag.get("relative_strength_pass"))
        theme_pass = bool(metadata.get(ticker))
        history_pass = int(diag.get("history_rows") or 0) >= 21
        price_discovery = in_price and historical_price_available and history_pass and fresh and volume_available and liquidity_pass
        rs_discovery = price_discovery and rs_pass
        theme_discovery = price_discovery and theme_pass
        objective_entry = in_existing or in_seed or price_discovery or rs_discovery or theme_discovery
        forced_only = ticker in FORCED and not objective_entry

        prior_eligible = tf(prior.get("eligible_for_unified_pool")) == "TRUE"
        new_objective_eligible = price_discovery and (rs_discovery or theme_discovery)
        eligible = (prior_eligible or (not in_existing and not in_seed and new_objective_eligible)) and not forced_only
        instrument_type = clean(prior.get("instrument_type"))
        if not instrument_type:
            instrument_type = clean(seeds.get(ticker, {}).get("instrument_type")) or "STOCK"
        source_parts = []
        if in_existing:
            source_parts.append("EXISTING_CANDIDATE_UNIVERSE")
        if in_price:
            source_parts.append("LOCAL_PRICE_UNIVERSE")
        if rs_discovery:
            source_parts.append("RELATIVE_STRENGTH_DISCOVERY")
        if theme_discovery:
            source_parts.append("THEME_DISCOVERY")
        if in_seed:
            source_parts.append("ETF_SEED")
        if forced_only:
            source_parts.append("FORCED_AUDIT_DIAGNOSTIC_ONLY")
        passes = sum((price_discovery, rs_discovery, theme_discovery))
        reasons = []
        if not price_available:
            reasons.append("MISSING_PRICE_DATA")
        elif not history_pass:
            reasons.append("INSUFFICIENT_PRICE_HISTORY")
        elif not fresh:
            reasons.append("STALE_PRICE_DATA")
        if price_available and not volume_available:
            reasons.append("VOLUME_UNAVAILABLE")
        elif volume_available and not liquidity_pass:
            reasons.append("LIQUIDITY_FILTER_NOT_PASSED")
        if price_discovery and not (rs_discovery or theme_discovery) and not prior_eligible:
            reasons.append("NO_RELATIVE_STRENGTH_OR_THEME_ADMISSION")
        if forced_only:
            reasons.append("FORCED_AUDIT_ONLY_NO_ELIGIBILITY")
        if not eligible and not reasons:
            reasons.append("OBJECTIVE_DISCOVERY_FILTER_NOT_PASSED")
        output.append({
            "ticker": ticker,
            "instrument_type": instrument_type,
            "source_membership": "|".join(source_parts),
            "entered_by_existing_candidate_universe": tf(in_existing),
            "entered_by_price_universe_discovery": tf(price_discovery),
            "entered_by_relative_strength_discovery": tf(rs_discovery),
            "entered_by_theme_discovery": tf(theme_discovery),
            "entered_by_etf_seed": tf(in_seed),
            "entered_by_forced_audit_only": tf(forced_only),
            "eligible_for_unified_pool": tf(eligible),
            "price_available": tf(price_available),
            "volume_available": tf(volume_available),
            "latest_price_date": latest,
            "price_freshness_status": "FRESH" if fresh else "STALE_WARN" if price_available else "MISSING_PRICE",
            "liquidity_filter_pass": tf(liquidity_pass),
            "relative_strength_filter_pass": tf(rs_pass),
            "theme_filter_pass": tf(theme_pass),
            "discovery_filter_pass_count": passes,
            "exclusion_reason": "" if eligible else "|".join(reasons),
            "research_only": "TRUE",
        })

    write_csv(out / POOL_NAME, output, POOL_FIELDS)
    write_csv(out / ELIGIBLE_NAME, (row for row in output if row["eligible_for_unified_pool"] == "TRUE"), POOL_FIELDS)
    by_ticker = {clean(row["ticker"]): row for row in output}
    forced_rows = []
    for ticker in FORCED:
        row = dict(by_ticker[ticker])
        objective = []
        if row["entered_by_existing_candidate_universe"] == "TRUE":
            objective.append("EXISTING_CANDIDATE_UNIVERSE")
        if row["entered_by_etf_seed"] == "TRUE":
            objective.append("ETF_SEED")
        if row["entered_by_relative_strength_discovery"] == "TRUE":
            objective.append("POSITIVE_RELATIVE_STRENGTH")
        if row["entered_by_theme_discovery"] == "TRUE":
            objective.append("THEME_WITH_SUFFICIENT_DATA")
        row["objective_admission_reason"] = "|".join(objective) or row["exclusion_reason"]
        row["forced_audit_effect"] = "DIAGNOSTIC_ONLY_NO_OVERRIDE_NO_BOOST"
        forced_rows.append(row)
    write_csv(out / FORCED_NAME, forced_rows, FORCED_FIELDS)

    sources = [
        ("r1_unified_pool", root / R1_POOL_REL, "ticker|instrument_type|eligibility", bool(r1_rows)),
        ("existing_stock_candidates", root / STOCK_REL, "ticker", bool(stock_rows)),
        ("etf_seed", root / SEED_REL, "ticker|instrument_type", bool(seed_rows)),
        ("historical_ohlcv", root / PRICE_REL, "as_of_date|ticker|adjusted_close|close|volume", bool(price_diag)),
        ("historical_depth", root / DEPTH_REL, "ticker|row_count|max_date", bool(depth_rows)),
        ("theme_metadata", root / METADATA_REL, "ticker|sector|industry|business_summary", bool(metadata_count)),
        ("a0_control_read_only_guard", root / A0_REL, "file_hash_only", (root / A0_REL).is_file()),
    ]
    source_rows = [{
        "source_role": role, "source_path": rel(root, path), "exists": tf(path.is_file()),
        "row_count": price_rows if role == "historical_ohlcv" else row_count(path),
        "usable": tf(usable), "fields_used": fields, "research_only": "TRUE",
        "notes": "Read-only local source; no network fetch, ranking, or momentum score created.",
    } for role, path, fields, usable in sources]
    write_csv(out / SOURCE_NAME, source_rows, SOURCE_FIELDS)

    after = protected_hashes(root)
    a0_modified = bool(differences(before["a0"], after["a0"]))
    official_modified = bool(differences(before["official"], after["official"]))
    real_modified = bool(differences(before["real_book"], after["real_book"]))
    broker_modified = bool(differences(before["broker"], after["broker"]))
    violations = [
        row for row in output
        if row["entered_by_forced_audit_only"] == "TRUE" and row["eligible_for_unified_pool"] == "TRUE"
    ]
    forced_eligible = sum(by_ticker[ticker]["eligible_for_unified_pool"] == "TRUE" for ticker in FORCED)
    data_warn = any(
        row["price_available"] != "TRUE" or row["volume_available"] != "TRUE"
        for row in output
        if row["entered_by_existing_candidate_universe"] == "TRUE"
        or row["entered_by_etf_seed"] == "TRUE"
        or row["entered_by_forced_audit_only"] == "TRUE"
    )
    if a0_modified or official_modified or real_modified or broker_modified:
        final, decision = FAIL_MUTATION, "STOP_AND_RESTORE_FORBIDDEN_MUTATION"
    elif violations:
        final, decision = FAIL_HARDCODED, "REPAIR_DISCOVERY_TO_REMOVE_FORCED_INCLUSION"
    elif data_warn:
        final, decision = PARTIAL_STATUS, "DISCOVERY_READY_FOR_MOMENTUM_WITH_DATA_WARN"
    else:
        final, decision = PASS_STATUS, "ALGORITHMIC_DISCOVERY_READY_FOR_V21_058_MOMENTUM_TRACKER"
    summary = {
        "FINAL_STATUS": final,
        "DECISION": decision,
        "stage_id": STAGE_ID,
        "total_discovery_pool_count": len(output),
        "eligible_discovery_pool_count": sum(row["eligible_for_unified_pool"] == "TRUE" for row in output),
        "existing_candidate_count": sum(row["entered_by_existing_candidate_universe"] == "TRUE" for row in output),
        "price_universe_discovery_count": sum(row["entered_by_price_universe_discovery"] == "TRUE" for row in output),
        "relative_strength_discovery_count": sum(row["entered_by_relative_strength_discovery"] == "TRUE" for row in output),
        "theme_discovery_count": sum(row["entered_by_theme_discovery"] == "TRUE" for row in output),
        "etf_seed_count": sum(row["entered_by_etf_seed"] == "TRUE" for row in output),
        "forced_audit_only_count": sum(row["entered_by_forced_audit_only"] == "TRUE" for row in output),
        "forced_audit_eligible_count": forced_eligible,
        "forced_audit_ineligible_count": len(FORCED) - forced_eligible,
        "hardcoded_inclusion_violation_count": len(violations),
        "a0_modified": a0_modified,
        "official_mutation_detected": official_modified,
        "real_book_mutation_detected": real_modified,
        "broker_mutation_detected": broker_modified,
        "research_only": True,
        "next_recommended_stage": "V21.058_MOMENTUM_TRACKER" if final in {PASS_STATUS, PARTIAL_STATUS} else "REPAIR_V21_057_R2_DISCOVERY",
    }
    write_json(out / SUMMARY_NAME, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    summary = run_stage(args.root)
    print(json.dumps(summary, indent=2))
    return 1 if summary["FINAL_STATUS"] in {FAIL_HARDCODED, FAIL_MUTATION} else 0


if __name__ == "__main__":
    raise SystemExit(main())
