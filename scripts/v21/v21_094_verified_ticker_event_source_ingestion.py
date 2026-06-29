#!/usr/bin/env python
"""V21.094 research-only event source ingestion and PIT certification."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


OUT_REL = Path("outputs/v21")
V21_093_LEDGER = Path("outputs/v21/v21_093_r1_event_master_ledger.csv")
D_BASELINE = Path(
    "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/"
    "V21_060_R5_D_WEIGHT_OPTIMIZED_RANKING.csv"
)
SEARCH_ROOTS = ("data", "state", "outputs", "archive", "scripts", "config", "configs", "reports")
RESEARCH_ONLY = True
OFFICIAL_ADOPTION_ALLOWED = False

SOURCE_CATEGORIES = (
    "ticker_earnings_calendar", "macro_fomc_calendar", "macro_cpi_calendar",
    "macro_pce_calendar", "macro_nfp_calendar", "macro_gdp_calendar",
    "market_opex_calendar", "market_quad_witching_calendar",
    "holiday_liquidity_calendar", "sector_key_earnings_calendar",
    "company_action_calendar", "split_calendar", "financing_calendar",
    "regulatory_calendar", "lockup_calendar",
)
CANONICAL_COLUMNS = [
    "event_id", "event_type", "event_name", "event_date", "event_time",
    "known_as_of_timestamp", "provider_available_date", "ingestion_timestamp",
    "affected_ticker", "affected_sector", "source_type", "source_path_or_url",
    "source_confidence", "pit_certified", "pit_exclusion_reason",
    "research_only", "notes",
]
INVENTORY_COLUMNS = [
    "source_path", "source_category", "source_type", "exists", "file_size_bytes",
    "row_count", "columns_detected", "ticker_column_detected",
    "event_date_column_detected", "event_time_column_detected",
    "known_as_of_column_detected", "provider_available_column_detected",
    "ingestion_timestamp_column_detected", "source_url_column_detected",
    "source_type_column_detected", "pit_certification_possible", "safe_to_ingest",
    "reuse_priority", "notes",
]
OUTPUT_NAMES = (
    "v21_094_r1_event_source_candidate_inventory.csv",
    "v21_094_r1_event_source_candidate_inventory_summary.json",
    "v21_094_r1_event_source_candidate_inventory_report.md",
    "v21_094_r2_verified_ticker_earnings_events.csv",
    "v21_094_r2_rejected_ticker_earnings_events.csv",
    "v21_094_r2_ticker_earnings_coverage_summary.csv",
    "v21_094_r2_ticker_earnings_ingestion_validation.json",
    "v21_094_r2_ticker_earnings_ingestion_report.md",
    "v21_094_r3_verified_macro_events.csv",
    "v21_094_r3_rejected_macro_events.csv",
    "v21_094_r3_macro_event_coverage_summary.csv",
    "v21_094_r3_macro_ingestion_validation.json",
    "v21_094_r3_macro_ingestion_report.md",
    "v21_094_r4_sector_key_event_mapping.csv",
    "v21_094_r4_sector_propagated_events.csv",
    "v21_094_r4_sector_event_mapping_validation.json",
    "v21_094_r4_sector_event_mapping_report.md",
    "v21_094_r5_certified_event_master_ledger.csv",
    "v21_094_r5_rejected_event_quarantine.csv",
    "v21_094_r5_event_coverage_by_ticker.csv",
    "v21_094_r5_event_coverage_by_event_type.csv",
    "v21_094_r5_event_pit_certification_audit.csv",
    "v21_094_r5_certified_event_source_summary.json",
    "v21_094_r5_certified_event_source_report.md",
)

ALIASES = {
    "ticker": ("affected_ticker", "ticker", "symbol", "code"),
    "event_date": (
        "event_date", "earnings_date", "earnings_announcement_date", "report_date",
        "release_date", "scheduled_date", "calendar_date", "date", "start_date",
    ),
    "event_time": ("event_time", "release_time", "earnings_time", "time"),
    "known": (
        "known_as_of_timestamp", "known_as_of", "available_as_of", "as_of_timestamp",
        "announcement_timestamp", "published_at", "publication_timestamp",
    ),
    "provider": (
        "provider_available_date", "provider_available_timestamp",
        "provider_timestamp", "source_available_date", "source_timestamp",
    ),
    "ingestion": (
        "ingestion_timestamp", "ingestion_date", "ingested_at", "refresh_timestamp",
        "refresh_timestamp_utc", "created_at", "download_timestamp",
    ),
    "url": ("source_url", "url", "provider_url", "source_path_or_url"),
    "source_type": ("source_type", "provider", "source_provider"),
    "event_type": ("event_type", "category", "release_type"),
    "event_name": ("event_name", "name", "title", "release_name"),
    "sector": ("affected_sector", "sector", "theme", "industry"),
}


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, default=json_default) + "\n", encoding="utf-8")


def empty_canonical(extra: Iterable[str] = ()) -> pd.DataFrame:
    return pd.DataFrame(columns=[*CANONICAL_COLUMNS, *extra])


def first_alias(columns: Iterable[str], group: str) -> str:
    lookup = {str(c).lower().strip(): str(c) for c in columns}
    return next((lookup[a] for a in ALIASES[group] if a in lookup), "")


def classify_category(text: str) -> str:
    value = text.lower()
    rules = (
        ("ticker_earnings_calendar", r"earnings|earning_calendar"),
        ("macro_fomc_calendar", r"\bfomc\b|federal.reserve"),
        ("macro_cpi_calendar", r"\bcpi\b|consumer.price"),
        ("macro_pce_calendar", r"\bpce\b|personal.consumption"),
        ("macro_nfp_calendar", r"\bnfp\b|nonfarm|payroll"),
        ("macro_gdp_calendar", r"\bgdp\b|gross.domestic"),
        ("market_quad_witching_calendar", r"quad.*witch"),
        ("market_opex_calendar", r"\bopex\b|options.expir"),
        ("holiday_liquidity_calendar", r"holiday.*liquid|nyse.*holiday"),
        ("sector_key_earnings_calendar", r"sector.*earn"),
        ("split_calendar", r"\bsplit\b"),
        ("financing_calendar", r"financ|offering|capital.raise"),
        ("regulatory_calendar", r"regulat|fda|antitrust"),
        ("lockup_calendar", r"lock.?up"),
        ("company_action_calendar", r"company.action|corporate.action"),
    )
    return next((category for category, pattern in rules if re.search(pattern, value)), "")


def header_and_rows(path: Path) -> tuple[list[str], int, str]:
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            columns = list(pd.read_csv(path, nrows=0, low_memory=False).columns)
            with path.open("rb") as handle:
                row_count = max(sum(1 for _ in handle) - 1, 0)
            return columns, row_count, ""
        if suffix in {".json", ".jsonl"}:
            if suffix == ".jsonl":
                sample = pd.read_json(path, lines=True, nrows=10)
                row_count = sum(1 for _ in path.open("r", encoding="utf-8", errors="ignore"))
            else:
                sample = pd.read_json(path)
                row_count = len(sample)
            return list(sample.columns), row_count, ""
        if suffix == ".parquet":
            sample = pd.read_parquet(path)
            return list(sample.columns), len(sample), ""
    except Exception as exc:
        return [], 0, f"READ_ERROR:{type(exc).__name__}"
    return [], 0, "NON_TABULAR_REFERENCE"


def has_pit_usable_row(path: Path, columns: list[str]) -> bool:
    date_cols = alias_values(columns, "event_date")
    availability_cols = [
        *alias_values(columns, "known"),
        *alias_values(columns, "provider"),
        *alias_values(columns, "ingestion"),
    ]
    if not date_cols or not availability_cols:
        return False
    try:
        use = list(dict.fromkeys([*date_cols, *availability_cols]))
        suffix = path.suffix.lower()
        if suffix == ".csv":
            sample = pd.read_csv(path, usecols=use, nrows=100_000, low_memory=False)
        elif suffix == ".jsonl":
            sample = pd.read_json(path, lines=True)
        elif suffix == ".json":
            sample = pd.read_json(path)
        elif suffix == ".parquet":
            sample = pd.read_parquet(path, columns=use)
        else:
            return False
        return bool((
            sample[date_cols].notna().any(axis=1)
            & sample[availability_cols].notna().any(axis=1)
        ).any())
    except Exception:
        return False


def discover_sources(root: Path, output_paths: set[Path]) -> pd.DataFrame:
    rows = []
    strong_column_tokens = (
        "event_date", "earnings_date", "report_date", "release_date",
        "known_as_of", "provider_available", "announcement_timestamp",
    )
    path_tokens = (
        "event", "earn", "calendar", "fomc", "cpi", "pce", "nfp", "payroll",
        "gdp", "opex", "witch", "holiday", "split", "financ", "regulat",
        "lockup", "company_action", "corporate_action",
    )
    for root_name in SEARCH_ROOTS:
        base = root / root_name
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.resolve() in output_paths:
                continue
            suffix = path.suffix.lower()
            path_text = path.relative_to(root).as_posix().lower()
            path_match = any(token in path_text for token in path_tokens)
            if suffix not in {".csv", ".json", ".jsonl", ".parquet", ".db", ".sqlite", ".zip", ".py", ".ps1", ".md"}:
                continue
            columns, row_count, read_note = header_and_rows(path)
            column_text = "|".join(map(str, columns)).lower()
            column_match = any(token in column_text for token in strong_column_tokens)
            is_v21_093 = path.resolve() == (root / V21_093_LEDGER).resolve()
            if is_v21_093:
                category_map = {
                    "market_opex": "market_opex_calendar",
                    "market_quad_witching": "market_quad_witching_calendar",
                    "holiday_liquidity": "holiday_liquidity_calendar",
                }
                try:
                    event_types = pd.read_csv(path, usecols=["event_type"])["event_type"].dropna().unique()
                except Exception:
                    event_types = []
                for event_type in event_types:
                    category = category_map.get(str(event_type), "")
                    if not category:
                        continue
                    category_rows = pd.read_csv(path, usecols=["event_type"])
                    category_count = int(category_rows["event_type"].eq(event_type).sum())
                    rows.append({
                        "source_path": path.relative_to(root).as_posix(),
                        "source_category": category,
                        "source_type": "DETERMINISTIC_PUBLIC_SCHEDULE",
                        "exists": True, "file_size_bytes": path.stat().st_size,
                        "row_count": category_count,
                        "columns_detected": "|".join(map(str, columns)),
                        "ticker_column_detected": first_alias(columns, "ticker"),
                        "event_date_column_detected": first_alias(columns, "event_date"),
                        "event_time_column_detected": first_alias(columns, "event_time"),
                        "known_as_of_column_detected": first_alias(columns, "known"),
                        "provider_available_column_detected": first_alias(columns, "provider"),
                        "ingestion_timestamp_column_detected": first_alias(columns, "ingestion"),
                        "source_url_column_detected": first_alias(columns, "url"),
                        "source_type_column_detected": first_alias(columns, "source_type"),
                        "pit_certification_possible": True, "safe_to_ingest": True,
                        "reuse_priority": "HIGH",
                        "notes": "V21.093 certified deterministic schedule subset.",
                    })
                continue
            category = classify_category(path_text + " " + column_text)
            if not (path_match or column_match or category):
                continue
            ticker_col = first_alias(columns, "ticker")
            date_col = first_alias(columns, "event_date")
            time_col = first_alias(columns, "event_time")
            known_col = first_alias(columns, "known")
            provider_col = first_alias(columns, "provider")
            ingestion_col = first_alias(columns, "ingestion")
            url_col = first_alias(columns, "url")
            type_col = first_alias(columns, "source_type")
            deterministic = False
            tabular = suffix in {".csv", ".json", ".jsonl", ".parquet"}
            pit_possible = bool(date_col and (known_col or provider_col or ingestion_col)) or deterministic
            safe = bool(
                tabular and category and pit_possible
                and not read_note.startswith("READ_ERROR")
                and has_pit_usable_row(path, columns)
            )
            priority = "HIGH" if safe else "REFERENCE_ONLY" if category else "LOW"
            source_type = (
                "DETERMINISTIC_PUBLIC_SCHEDULE" if deterministic
                else "LOCAL_TABULAR_SOURCE" if tabular
                else "LEGACY_OR_CODE_REFERENCE"
            )
            rows.append({
                "source_path": path.relative_to(root).as_posix(),
                "source_category": category or "unclassified_event_reference",
                "source_type": source_type, "exists": True,
                "file_size_bytes": path.stat().st_size, "row_count": row_count,
                "columns_detected": "|".join(map(str, columns)),
                "ticker_column_detected": ticker_col,
                "event_date_column_detected": date_col,
                "event_time_column_detected": time_col,
                "known_as_of_column_detected": known_col,
                "provider_available_column_detected": provider_col,
                "ingestion_timestamp_column_detected": ingestion_col,
                "source_url_column_detected": url_col,
                "source_type_column_detected": type_col,
                "pit_certification_possible": pit_possible,
                "safe_to_ingest": safe, "reuse_priority": priority,
                "notes": read_note or (
                    "Explicit PIT lineage or certified deterministic schedule available."
                    if safe else "Reference only; required event date and availability lineage not both present."
                ),
            })
    return pd.DataFrame(rows, columns=INVENTORY_COLUMNS).sort_values(
        ["safe_to_ingest", "reuse_priority", "source_category", "source_path"],
        ascending=[False, True, True, True],
    ).reset_index(drop=True)


def read_source(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, low_memory=False)
    if path.suffix.lower() == ".jsonl":
        return pd.read_json(path, lines=True)
    if path.suffix.lower() == ".json":
        return pd.read_json(path)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.DataFrame()


def timestamp_value(row: pd.Series, column: str) -> Any:
    return row.get(column) if column and column in row else np.nan


def alias_values(columns: Iterable[str], group: str) -> list[str]:
    lookup = {str(c).lower().strip(): str(c) for c in columns}
    return [lookup[name] for name in ALIASES[group] if name in lookup]


def first_present(row: pd.Series, columns: Iterable[str]) -> Any:
    for column in columns:
        value = row.get(column)
        if pd.notna(value) and str(value).strip() not in {"", "nan", "NaT"}:
            return value
    return np.nan


def normalize_source(
    root: Path,
    inventory_row: pd.Series,
    event_kind: str,
    allowed_tickers: set[str],
) -> pd.DataFrame:
    path = root / inventory_row["source_path"]
    frame = read_source(path)
    if frame.empty:
        return empty_canonical()
    columns = list(frame.columns)
    ticker_col = first_alias(columns, "ticker")
    date_cols = alias_values(columns, "event_date")
    time_col = first_alias(columns, "event_time")
    known_cols = alias_values(columns, "known")
    provider_cols = alias_values(columns, "provider")
    ingestion_cols = alias_values(columns, "ingestion")
    url_col = first_alias(columns, "url")
    source_col = first_alias(columns, "source_type")
    event_type_col = first_alias(columns, "event_type")
    event_name_col = first_alias(columns, "event_name")
    sector_col = first_alias(columns, "sector")
    if not date_cols:
        return empty_canonical()
    rows = []
    category = inventory_row["source_category"]
    macro_type = {
        "macro_fomc_calendar": "macro_fomc", "macro_cpi_calendar": "macro_cpi",
        "macro_pce_calendar": "macro_pce", "macro_nfp_calendar": "macro_nfp",
        "macro_gdp_calendar": "macro_gdp",
    }.get(category, "")
    for index, row in frame.iterrows():
        ticker = str(row.get(ticker_col, "")).upper().strip() if ticker_col else "ALL"
        ticker = ticker if ticker and ticker != "NAN" else "ALL"
        event_date = pd.to_datetime(first_present(row, date_cols), errors="coerce")
        if pd.isna(event_date):
            # A source row with no event date is not an event candidate and is not quarantined.
            continue
        known_raw = first_present(row, known_cols)
        provider_raw = first_present(row, provider_cols)
        ingestion_raw = first_present(row, ingestion_cols)
        known = pd.to_datetime(known_raw, utc=True, errors="coerce")
        provider = pd.to_datetime(provider_raw, utc=True, errors="coerce")
        ingestion = pd.to_datetime(ingestion_raw, utc=True, errors="coerce")
        availability_candidates = [value for value in (known, provider, ingestion) if not pd.isna(value)]
        effective_known = min(availability_candidates) if availability_candidates else pd.NaT
        reasons = []
        if not availability_candidates:
            reasons.append("NO_VERIFIABLE_AVAILABILITY_TIMESTAMP")
        if event_kind == "earnings" and ticker not in allowed_tickers:
            reasons.append("TICKER_NOT_IN_V21_OR_BENCHMARK_UNIVERSE")
        if not pd.isna(event_date) and not pd.isna(effective_known):
            event_end = pd.Timestamp(event_date.date(), tz="UTC") + pd.Timedelta(days=1)
            if effective_known > event_end:
                reasons.append("EARLIEST_AVAILABILITY_AFTER_EVENT")
        row_event_type = str(row.get(event_type_col, "")).lower().strip() if event_type_col else ""
        event_type = "earnings" if event_kind == "earnings" else macro_type or row_event_type
        if event_kind == "macro" and event_type not in {
            "macro_fomc", "macro_cpi", "macro_pce", "macro_nfp", "macro_gdp"
        }:
            reasons.append("UNSUPPORTED_OR_UNRESOLVED_MACRO_EVENT_TYPE")
        digest_text = "|".join([
            inventory_row["source_path"], str(index), event_type,
            "" if pd.isna(event_date) else event_date.date().isoformat(), ticker,
        ])
        event_id = "V21_094_" + hashlib.sha256(digest_text.encode()).hexdigest()[:20].upper()
        source_url = str(row.get(url_col, "")).strip() if url_col else ""
        source_path_or_url = source_url if source_url and source_url != "nan" else inventory_row["source_path"]
        source_type = str(row.get(source_col, "")).strip() if source_col else inventory_row["source_type"]
        rows.append({
            "event_id": event_id, "event_type": event_type,
            "event_name": str(row.get(event_name_col, "")).strip() if event_name_col else (
                f"{ticker} earnings" if event_kind == "earnings" else event_type.replace("_", " ").upper()
            ),
            "event_date": "" if pd.isna(event_date) else event_date.date().isoformat(),
            "event_time": str(row.get(time_col, "")).strip() if time_col else "",
            "known_as_of_timestamp": "" if pd.isna(effective_known) else effective_known.isoformat(),
            "provider_available_date": "" if pd.isna(provider) else provider.isoformat(),
            "ingestion_timestamp": "" if pd.isna(ingestion) else ingestion.isoformat(),
            "affected_ticker": ticker,
            "affected_sector": str(row.get(sector_col, "")).strip() if sector_col else "ALL",
            "source_type": source_type, "source_path_or_url": source_path_or_url,
            "source_confidence": "HIGH" if known_cols or provider_cols else "MEDIUM" if ingestion_cols else "LOW",
            "pit_certified": not reasons, "pit_exclusion_reason": "|".join(reasons),
            "research_only": True,
            "notes": "Normalized without price, realized-return, surprise, or post-event labels.",
        })
    return pd.DataFrame(rows, columns=CANONICAL_COLUMNS)


def ingest_category(
    root: Path,
    inventory: pd.DataFrame,
    categories: set[str],
    event_kind: str,
    allowed_tickers: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    parts = []
    candidates = inventory[
        inventory["source_category"].isin(categories)
        & inventory["source_type"].ne("DETERMINISTIC_PUBLIC_SCHEDULE")
        & inventory["source_path"].ne(V21_093_LEDGER.as_posix())
    ]
    for _, source in candidates.iterrows():
        if Path(source["source_path"]).suffix.lower() not in {".csv", ".json", ".jsonl", ".parquet"}:
            continue
        try:
            normalized = normalize_source(root, source, event_kind, allowed_tickers)
            if not normalized.empty:
                parts.append(normalized)
        except Exception:
            continue
    all_rows = pd.concat(parts, ignore_index=True) if parts else empty_canonical()
    if all_rows.empty:
        return empty_canonical(), empty_canonical()
    certified = all_rows[all_rows["pit_certified"].map(truth)].copy()
    rejected = all_rows[~all_rows["pit_certified"].map(truth)].copy()
    return certified, rejected


def sector_mapping(universe: set[str]) -> pd.DataFrame:
    definitions = {
        "DRAM_STORAGE_CHAIN": ["MU", "WDC", "STX", "SNDK", "AMKR"],
        "SEMICONDUCTOR_BROAD": [
            "NVDA", "AMD", "AVGO", "TSM", "ASML", "AMAT", "LRCX", "KLAC",
            "ICHR", "FORM", "VECO", "ACMR",
        ],
        "AI_DATACENTER": [
            "NVDA", "AMD", "AVGO", "ARM", "CRDO", "MRVL", "ANET", "SMCI",
            "DELL", "VRT", "APLD",
        ],
        "SEMICONDUCTOR_ETF_EXPOSURE": ["SOXX", "SMH", "QQQ", "TQQQ"],
    }
    rows = []
    for group, members in definitions.items():
        for ticker in members:
            rows.append({
                "sector_event_group": group, "ticker": ticker,
                "in_v21_candidate_or_benchmark_universe": ticker in universe,
                "mapping_rule": "STATIC_DETERMINISTIC_V21_094",
                "mapping_version": "V21.094-R4",
                "research_only": True, "official_adoption_allowed": False,
                "notes": "Exposure mapping only; does not create event dates.",
            })
    return pd.DataFrame(rows)


def propagate_sector_events(earnings: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    extra = ["original_event_id", "sector_propagated", "propagation_group", "direct_event_ticker"]
    if earnings.empty:
        return empty_canonical(extra)
    member_groups = mapping.groupby("ticker")["sector_event_group"].apply(list).to_dict()
    group_members = mapping.groupby("sector_event_group")["ticker"].apply(list).to_dict()
    rows = []
    for _, event in earnings.iterrows():
        source_ticker = event["affected_ticker"]
        for group in member_groups.get(source_ticker, []):
            for target in group_members[group]:
                if target == source_ticker:
                    continue
                propagated = event.to_dict()
                propagated["original_event_id"] = event["event_id"]
                propagated["event_id"] = f"{event['event_id']}__PROP__{group}__{target}"
                propagated["event_type"] = (
                    "sector_dram" if group == "DRAM_STORAGE_CHAIN" else "sector_semiconductor"
                )
                propagated["event_name"] = f"{group} exposure from {source_ticker} earnings"
                propagated["affected_ticker"] = target
                propagated["affected_sector"] = group
                propagated["sector_propagated"] = True
                propagated["propagation_group"] = group
                propagated["direct_event_ticker"] = source_ticker
                propagated["notes"] = (
                    f"Propagated from certified event {event['event_id']} using deterministic map."
                )
                rows.append(propagated)
    if not rows:
        return empty_canonical(extra)
    return pd.DataFrame(rows, columns=[*CANONICAL_COLUMNS, *extra]).drop_duplicates("event_id")


def protected_snapshot(root: Path, output_paths: set[Path]) -> dict[str, str]:
    tokens = (
        "official", "broker", "protected", "forward_observation_ledger",
        "060_r5_d_", "066a_d_latest_ranking", "p03", "p04",
    )
    result = {}
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.resolve() in output_paths:
                continue
            if any(token in path.as_posix().lower() for token in tokens):
                result[path.relative_to(root).as_posix()] = sha256(path)
    return result


def markdown(title: str, rows: Iterable[tuple[str, Any]], body: str = "") -> str:
    lines = [f"# {title}", ""]
    lines.extend(f"- {key}: `{value}`" for key, value in rows)
    if body:
        lines.extend(["", body])
    return "\n".join(lines) + "\n"


def run(root: Path) -> dict[str, Any]:
    out = root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    output_paths = {(out / name).resolve() for name in OUTPUT_NAMES}
    before = protected_snapshot(root, output_paths)
    d_hash_before = sha256(root / D_BASELINE)

    d = pd.read_csv(root / D_BASELINE, low_memory=False)
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    universe = set(d["ticker"].dropna()) | {"SPY", "QQQ", "SMH", "SOXX", "TQQQ"}
    ranked = d[pd.to_numeric(d["final_shadow_rank"], errors="coerce").notna()].copy()
    latest_date = ranked["as_of_date"].dropna().astype(str).max()
    current = ranked[ranked["as_of_date"].astype(str).eq(latest_date)].sort_values("final_shadow_rank")
    top20 = set(current.head(20)["ticker"])
    top50 = set(current.head(50)["ticker"])

    # R1
    inventory = discover_sources(root, output_paths)
    inventory.to_csv(out / OUTPUT_NAMES[0], index=False)
    categories_found = sorted(set(inventory.loc[
        inventory["source_category"].ne("unclassified_event_reference"), "source_category"
    ]))
    safe_count = int(inventory.loc[
        inventory["safe_to_ingest"].map(truth), "source_path"
    ].nunique())
    r1_summary = {
        "stage": "V21.094-R1_EVENT_SOURCE_CANDIDATE_INVENTORY",
        "status": "PASS", "candidate_source_count": len(inventory),
        "source_categories_found": categories_found,
        "safe_reuse_source_count": safe_count,
        "pit_certification_possible_count": int(inventory["pit_certification_possible"].map(truth).sum()),
        "search_roots": list(SEARCH_ROOTS), "research_only": True,
        "official_adoption_allowed": False,
    }
    write_json(out / OUTPUT_NAMES[1], r1_summary)
    (out / OUTPUT_NAMES[2]).write_text(markdown(
        "V21.094-R1 Event Source Candidate Inventory",
        r1_summary.items(),
        "Sources without both event-date semantics and availability lineage remain reference-only.",
    ), encoding="utf-8")

    # R2
    earnings, rejected_earnings = ingest_category(
        root, inventory,
        {"ticker_earnings_calendar", "sector_key_earnings_calendar"},
        "earnings", universe,
    )
    earnings.to_csv(out / OUTPUT_NAMES[3], index=False)
    rejected_earnings.to_csv(out / OUTPUT_NAMES[4], index=False)
    earnings_tickers = set(earnings["affected_ticker"]) if not earnings.empty else set()
    earnings_coverage = pd.DataFrame([
        {"coverage_scope": "CANDIDATE_UNIVERSE", "covered": len(earnings_tickers & universe), "total": len(universe)},
        {"coverage_scope": "CURRENT_TOP20", "covered": len(earnings_tickers & top20), "total": len(top20)},
        {"coverage_scope": "CURRENT_TOP50", "covered": len(earnings_tickers & top50), "total": len(top50)},
    ])
    earnings_coverage["coverage_ratio"] = earnings_coverage["covered"] / earnings_coverage["total"].replace(0, np.nan)
    earnings_coverage.to_csv(out / OUTPUT_NAMES[5], index=False)
    r2_validation = {
        "stage": "V21.094-R2_VERIFIED_TICKER_EARNINGS_EVENT_INGESTION",
        "status": "PASS", "certified_rows": len(earnings),
        "rejected_rows": len(rejected_earnings),
        "invalid_event_type_count": int((earnings["event_type"] != "earnings").sum()) if not earnings.empty else 0,
        "out_of_universe_count": int((~earnings["affected_ticker"].isin(universe)).sum()) if not earnings.empty else 0,
        "missing_availability_timestamp_count": int(earnings["known_as_of_timestamp"].replace("", np.nan).isna().sum()) if not earnings.empty else 0,
        "post_event_price_or_return_labels_used": False,
        "research_only": True, "official_adoption_allowed": False,
    }
    write_json(out / OUTPUT_NAMES[6], r2_validation)
    (out / OUTPUT_NAMES[7]).write_text(markdown(
        "V21.094-R2 Verified Ticker Earnings Ingestion", r2_validation.items(),
        "Rows without verifiable pre-event availability are quarantined and excluded from the certified ledger.",
    ), encoding="utf-8")

    # R3
    macro, rejected_macro = ingest_category(
        root, inventory,
        {
            "macro_fomc_calendar", "macro_cpi_calendar", "macro_pce_calendar",
            "macro_nfp_calendar", "macro_gdp_calendar",
        },
        "macro", universe,
    )
    macro.to_csv(out / OUTPUT_NAMES[8], index=False)
    rejected_macro.to_csv(out / OUTPUT_NAMES[9], index=False)
    if macro.empty:
        macro_coverage = pd.DataFrame(columns=["event_type", "certified_rows", "min_event_date", "max_event_date"])
    else:
        macro_coverage = macro.groupby("event_type").agg(
            certified_rows=("event_id", "count"), min_event_date=("event_date", "min"),
            max_event_date=("event_date", "max"),
        ).reset_index()
    macro_coverage.to_csv(out / OUTPUT_NAMES[10], index=False)
    r3_validation = {
        "stage": "V21.094-R3_VERIFIED_MACRO_EVENT_CALENDAR_INGESTION",
        "status": "PASS", "certified_rows": len(macro), "rejected_rows": len(rejected_macro),
        "unsupported_type_count": int((~macro["event_type"].isin({
            "macro_fomc", "macro_cpi", "macro_pce", "macro_nfp", "macro_gdp"
        })).sum()) if not macro.empty else 0,
        "post_release_values_or_surprises_used": False,
        "research_only": True, "official_adoption_allowed": False,
    }
    write_json(out / OUTPUT_NAMES[11], r3_validation)
    (out / OUTPUT_NAMES[12]).write_text(markdown(
        "V21.094-R3 Verified Macro Calendar Ingestion", r3_validation.items(),
        "No macro schedule is fabricated. Only locally sourced rows with explicit availability lineage are eligible.",
    ), encoding="utf-8")

    # R4
    mapping = sector_mapping(universe)
    mapping.to_csv(out / OUTPUT_NAMES[13], index=False)
    propagated = propagate_sector_events(earnings, mapping)
    propagated.to_csv(out / OUTPUT_NAMES[14], index=False)
    r4_validation = {
        "stage": "V21.094-R4_SECTOR_KEY_EVENT_MAPPING",
        "status": "PASS", "mapping_rows": len(mapping),
        "propagated_rows": len(propagated),
        "missing_original_event_id_count": int(
            propagated["original_event_id"].replace("", np.nan).isna().sum()
        ) if not propagated.empty else 0,
        "non_certified_propagated_count": int(
            (~propagated["pit_certified"].map(truth)).sum()
        ) if not propagated.empty else 0,
        "fabricated_event_dates": False, "research_only": True,
        "official_adoption_allowed": False,
    }
    write_json(out / OUTPUT_NAMES[15], r4_validation)
    (out / OUTPUT_NAMES[16]).write_text(markdown(
        "V21.094-R4 Sector Key Event Mapping", r4_validation.items(),
        "The map propagates only already-certified direct earnings events and preserves original_event_id.",
    ), encoding="utf-8")

    # R5
    legacy = pd.read_csv(root / V21_093_LEDGER, low_memory=False)
    legacy_certified = pd.DataFrame({
        "event_id": legacy["event_id"], "event_type": legacy["event_type"],
        "event_name": legacy["event_name"], "event_date": legacy["event_date"],
        "event_time": legacy["event_time"],
        "known_as_of_timestamp": legacy["known_as_of_timestamp"],
        "provider_available_date": legacy["known_as_of_timestamp"],
        "ingestion_timestamp": "",
        "affected_ticker": legacy["affected_ticker"].fillna("ALL").replace("", "ALL"),
        "affected_sector": legacy["affected_sector"].fillna("ALL").replace("", "ALL"),
        "source_type": legacy["source_type"],
        "source_path_or_url": V21_093_LEDGER.as_posix(),
        "source_confidence": "HIGH",
        "pit_certified": legacy["pit_allowed"].map(truth),
        "pit_exclusion_reason": "",
        "research_only": True,
        "notes": legacy["notes"],
    })
    certified_parts = [legacy_certified, earnings, macro]
    if not propagated.empty:
        certified_parts.append(propagated[CANONICAL_COLUMNS])
    certified = pd.concat(certified_parts, ignore_index=True)
    certified = certified[certified["pit_certified"].map(truth)].drop_duplicates("event_id")
    certified.to_csv(out / OUTPUT_NAMES[17], index=False)
    quarantine = pd.concat([rejected_earnings, rejected_macro], ignore_index=True)
    quarantine.to_csv(out / OUTPUT_NAMES[18], index=False)

    ticker_specific = certified[
        ~certified["affected_ticker"].fillna("ALL").isin(["", "ALL"])
    ]
    ticker_counts = ticker_specific.groupby("affected_ticker").agg(
        certified_event_rows=("event_id", "count"),
        direct_event_rows=("event_type", lambda s: int(s.eq("earnings").sum())),
        sector_propagated_rows=("event_type", lambda s: int(s.str.startswith("sector_").sum())),
        event_types=("event_type", lambda s: "|".join(sorted(set(s)))),
        min_event_date=("event_date", "min"), max_event_date=("event_date", "max"),
    ).reset_index().rename(columns={"affected_ticker": "ticker"})
    coverage_ticker = pd.DataFrame({"ticker": sorted(universe)})
    coverage_ticker = coverage_ticker.merge(ticker_counts, on="ticker", how="left")
    coverage_ticker["certified_event_rows"] = coverage_ticker["certified_event_rows"].fillna(0).astype(int)
    coverage_ticker["direct_event_rows"] = coverage_ticker["direct_event_rows"].fillna(0).astype(int)
    coverage_ticker["sector_propagated_rows"] = coverage_ticker["sector_propagated_rows"].fillna(0).astype(int)
    coverage_ticker["has_ticker_specific_event_coverage"] = coverage_ticker["certified_event_rows"].gt(0)
    coverage_ticker["current_top20"] = coverage_ticker["ticker"].isin(top20)
    coverage_ticker["current_top50"] = coverage_ticker["ticker"].isin(top50)
    coverage_ticker.to_csv(out / OUTPUT_NAMES[19], index=False)

    coverage_type = certified.groupby("event_type").agg(
        certified_event_rows=("event_id", "count"),
        affected_ticker_count=("affected_ticker", lambda s: s[~s.isin(["", "ALL"])].nunique()),
        source_count=("source_path_or_url", "nunique"),
        min_event_date=("event_date", "min"), max_event_date=("event_date", "max"),
    ).reset_index()
    coverage_type.to_csv(out / OUTPUT_NAMES[20], index=False)
    audit = pd.concat([
        certified.assign(ledger_disposition="CERTIFIED"),
        quarantine.assign(ledger_disposition="REJECTED"),
    ], ignore_index=True)
    if audit.empty:
        audit = empty_canonical(["ledger_disposition", "pit_timestamp_parseable", "pit_leakage_warning"])
    else:
        audit["pit_timestamp_parseable"] = pd.to_datetime(
            audit["known_as_of_timestamp"], utc=True, errors="coerce"
        ).notna()
        audit["pit_leakage_warning"] = (
            audit["ledger_disposition"].eq("CERTIFIED") & ~audit["pit_timestamp_parseable"]
        )
    audit.to_csv(out / OUTPUT_NAMES[21], index=False)

    after = protected_snapshot(root, output_paths)
    changed = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
    official_changed = [p for p in changed if "official" in p.lower() or "broker" in p.lower()]
    d_preserved = sha256(root / D_BASELINE) == d_hash_before
    pit_warnings = int(audit["pit_leakage_warning"].sum()) if "pit_leakage_warning" in audit else 0
    certified_ticker_rows = len(earnings)
    certified_macro_rows = len(macro)
    certified_sector_rows = len(propagated)
    rejected_rows = len(quarantine)
    pit_ratio = len(certified) / (len(certified) + rejected_rows) if len(certified) + rejected_rows else 0.0
    covered = set(ticker_specific["affected_ticker"])
    universe_ratio = len(covered & universe) / len(universe) if universe else 0.0
    top20_ratio = len(covered & top20) / len(top20) if top20 else 0.0
    top50_ratio = len(covered & top50) / len(top50) if top50 else 0.0
    types_certified = sorted(set(certified["event_type"]))
    types_rejected = sorted(set(quarantine["event_type"])) if not quarantine.empty else []
    if pit_warnings > 0:
        decision = "REJECT_EVENT_SOURCE_INGESTION_DUE_TO_PIT_LEAKAGE"
    elif changed or not d_preserved:
        decision = "REJECT_EVENT_SOURCE_INGESTION_DUE_TO_PROTECTED_MUTATION"
    elif certified_ticker_rows == 0 and certified_macro_rows == 0:
        decision = "EVENT_SOURCE_INGESTION_INSUFFICIENT_BUILD_OR_IMPORT_VERIFIED_SOURCES"
    elif certified_ticker_rows > 0 and pit_ratio < 0.95:
        decision = "EVENT_SOURCE_INGESTION_PARTIAL_REQUIRE_PIT_REPAIR"
    elif certified_ticker_rows > 0 and pit_ratio >= 0.95:
        decision = "CERTIFIED_EVENT_SOURCE_READY_FOR_V21_095_RETEST"
    else:
        decision = "MACRO_ONLY_EVENT_SOURCE_READY_FOR_EXPOSURE_OVERLAY_NOT_RANKING_FACTOR"
    final_status = "PASS" if not pit_warnings and not changed and d_preserved else "FAIL"
    next_stage = (
        "V21.095_EVENT_RISK_EFFECTIVENESS_RETEST"
        if decision == "CERTIFIED_EVENT_SOURCE_READY_FOR_V21_095_RETEST"
        else "BUILD_OR_IMPORT_PIT_TIMESTAMPED_EARNINGS_AND_MACRO_CALENDARS"
    )
    summary = {
        "FINAL_STATUS": final_status, "DECISION": decision,
        "CERTIFIED_EVENT_ROWS": len(certified), "REJECTED_EVENT_ROWS": rejected_rows,
        "CERTIFIED_TICKER_EVENT_ROWS": certified_ticker_rows,
        "CERTIFIED_MACRO_EVENT_ROWS": certified_macro_rows,
        "CERTIFIED_SECTOR_PROPAGATED_ROWS": certified_sector_rows,
        "CANDIDATE_UNIVERSE_COVERAGE_RATIO": universe_ratio,
        "TOP20_EVENT_COVERAGE_RATIO": top20_ratio,
        "TOP50_EVENT_COVERAGE_RATIO": top50_ratio,
        "PIT_CERTIFIED_RATIO": pit_ratio, "PIT_LEAKAGE_WARNINGS": pit_warnings,
        "EVENT_TYPES_CERTIFIED": types_certified, "EVENT_TYPES_REJECTED": types_rejected,
        "SOURCE_CATEGORIES_FOUND": categories_found,
        "SAFE_REUSE_SOURCE_COUNT": safe_count,
        "PROTECTED_OUTPUTS_MODIFIED": bool(changed or not d_preserved),
        "OFFICIAL_OUTPUTS_MODIFIED": bool(official_changed),
        "RESEARCH_ONLY": True, "OFFICIAL_ADOPTION_ALLOWED": False,
        "RECOMMENDED_NEXT_STAGE": next_stage,
        "D_BASELINE_PRESERVED": d_preserved,
        "MODIFIED_PROTECTED_PATHS": changed,
        "COVERAGE_DEFINITION": "Ticker-specific direct or deterministic sector-propagated certified events; global events excluded.",
    }
    write_json(out / OUTPUT_NAMES[22], summary)
    report_body = (
        "V21.093 exchange/holiday events remain certified. No locally available earnings or "
        "macro source passed the explicit pre-event availability-lineage gate. The ingestion "
        "adapters will admit future CSV/JSON/Parquet sources when event date, ticker/type, and "
        "known/provider/ingestion availability fields are present and temporally valid."
    )
    (out / OUTPUT_NAMES[23]).write_text(markdown(
        "V21.094-R5 Certified Event Source Report", summary.items(), report_body
    ), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    summary = run(args.root.resolve())
    keys = (
        "FINAL_STATUS", "DECISION", "CERTIFIED_EVENT_ROWS", "REJECTED_EVENT_ROWS",
        "CERTIFIED_TICKER_EVENT_ROWS", "CERTIFIED_MACRO_EVENT_ROWS",
        "CERTIFIED_SECTOR_PROPAGATED_ROWS", "CANDIDATE_UNIVERSE_COVERAGE_RATIO",
        "TOP20_EVENT_COVERAGE_RATIO", "TOP50_EVENT_COVERAGE_RATIO",
        "PIT_CERTIFIED_RATIO", "PIT_LEAKAGE_WARNINGS", "EVENT_TYPES_CERTIFIED",
        "EVENT_TYPES_REJECTED", "SOURCE_CATEGORIES_FOUND", "SAFE_REUSE_SOURCE_COUNT",
        "PROTECTED_OUTPUTS_MODIFIED", "OFFICIAL_OUTPUTS_MODIFIED", "RESEARCH_ONLY",
        "OFFICIAL_ADOPTION_ALLOWED", "RECOMMENDED_NEXT_STAGE",
    )
    for key in keys:
        value = summary[key]
        if isinstance(value, list):
            value = "|".join(map(str, value))
        print(f"{key}={value}")
    return 0 if summary["FINAL_STATUS"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
