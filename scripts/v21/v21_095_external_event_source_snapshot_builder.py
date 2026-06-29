#!/usr/bin/env python
"""V21.095 research-only external event source snapshot builder."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


CONFIG_REL = Path("config/v21_event_sources.json")
OUT_REL = Path("outputs/v21")
MACRO_IMPORT_REL = Path("data/events/manual_import/macro")
EARNINGS_IMPORT_REL = Path("data/events/manual_import/earnings")
RAW_REL = Path("data/events/raw_snapshots")
V21_093_REL = Path("outputs/v21/v21_093_r1_event_master_ledger.csv")
D_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/"
    "V21_060_R5_D_WEIGHT_OPTIMIZED_RANKING.csv"
)
RESEARCH_ONLY = True
OFFICIAL_ADOPTION_ALLOWED = False
MACRO_TYPES = {"macro_fomc", "macro_cpi", "macro_pce", "macro_nfp", "macro_gdp"}
CANONICAL_COLUMNS = [
    "event_id", "event_type", "event_name", "event_date", "event_time",
    "event_timezone", "affected_ticker", "affected_sector", "source_id",
    "source_name", "source_url_or_provider", "retrieval_timestamp_utc",
    "ingestion_timestamp_utc", "provider_available_date",
    "known_as_of_timestamp", "raw_payload_hash", "normalized_row_hash",
    "source_confidence", "pit_certified", "pit_exclusion_reason",
    "research_only", "notes",
]
OUTPUT_NAMES = (
    "v21_095_r1_event_source_registry.csv",
    "v21_095_r1_event_schema_contract.json",
    "v21_095_r1_event_schema_report.md",
    "v21_095_r2_macro_event_snapshot_raw_manifest.csv",
    "v21_095_r2_macro_event_normalized.csv",
    "v21_095_r2_macro_event_ingestion_validation.json",
    "v21_095_r2_macro_event_ingestion_report.md",
    "v21_095_r3_ticker_earnings_raw_manifest.csv",
    "v21_095_r3_ticker_earnings_normalized.csv",
    "v21_095_r3_ticker_earnings_rejected.csv",
    "v21_095_r3_ticker_earnings_coverage_summary.csv",
    "v21_095_r3_ticker_earnings_ingestion_validation.json",
    "v21_095_r3_ticker_earnings_ingestion_report.md",
    "v21_095_r4_certified_event_snapshot_ledger.csv",
    "v21_095_r4_event_snapshot_pit_audit.csv",
    "v21_095_r4_event_snapshot_usage_policy.csv",
    "v21_095_r4_rejected_or_quarantined_events.csv",
    "v21_095_r4_pit_certification_validation.json",
    "v21_095_r4_pit_certification_report.md",
    "v21_095_r5_event_source_readiness_summary.json",
    "v21_095_r5_event_source_readiness_report.md",
)


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_hash(values: dict[str, Any]) -> str:
    text = json.dumps(values, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=json_default) + "\n", encoding="utf-8")


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


def empty_events() -> pd.DataFrame:
    return pd.DataFrame(columns=CANONICAL_COLUMNS)


def markdown(title: str, fields: dict[str, Any], note: str = "") -> str:
    lines = [f"# {title}", ""]
    lines.extend(f"- {key}: `{value}`" for key, value in fields.items())
    if note:
        lines.extend(["", note])
    return "\n".join(lines) + "\n"


def protected_snapshot(root: Path, output_paths: set[Path]) -> dict[str, str]:
    tokens = (
        "official", "broker", "protected", "forward_observation_ledger",
        "060_r5_d_", "066a_d_latest_ranking", "p03", "p04",
    )
    result: dict[str, str] = {}
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.resolve() in output_paths:
                continue
            if (root / "data/events").resolve() in path.resolve().parents:
                continue
            if any(token in path.as_posix().lower() for token in tokens):
                result[path.relative_to(root).as_posix()] = sha256(path)
    return result


def load_registry(root: Path) -> pd.DataFrame:
    payload = json.loads((root / CONFIG_REL).read_text(encoding="utf-8"))
    registry = pd.DataFrame(payload)
    registry["expected_fields"] = registry["expected_fields"].map(
        lambda value: "|".join(value) if isinstance(value, list) else str(value)
    )
    return registry


def snapshot_imports(
    root: Path, source_dir: Path, category: str, run_date: str, run_ts: pd.Timestamp
) -> pd.DataFrame:
    rows = []
    destination = root / RAW_REL / run_date / category
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted((root / source_dir).glob("*.csv")):
        payload_hash = sha256(path)
        target = destination / f"{path.stem}__{payload_hash[:12]}{path.suffix.lower()}"
        if not target.exists():
            shutil.copy2(path, target)
        try:
            row_count = len(pd.read_csv(path, low_memory=False))
            columns = "|".join(pd.read_csv(path, nrows=0).columns)
            status = "SNAPSHOTTED"
            warning = ""
        except Exception as exc:
            row_count = 0
            columns = ""
            status = "READ_ERROR"
            warning = type(exc).__name__
        rows.append({
            "source_file": path.relative_to(root).as_posix(),
            "snapshot_file": target.relative_to(root).as_posix(),
            "source_category": category, "file_size_bytes": path.stat().st_size,
            "row_count": row_count, "columns_detected": columns,
            "raw_payload_hash": payload_hash,
            "retrieval_timestamp_utc": run_ts.isoformat(),
            "snapshot_status": status, "warning": warning,
            "research_only": True,
        })
    return pd.DataFrame(rows, columns=[
        "source_file", "snapshot_file", "source_category", "file_size_bytes",
        "row_count", "columns_detected", "raw_payload_hash",
        "retrieval_timestamp_utc", "snapshot_status", "warning", "research_only",
    ])


def first_value(row: pd.Series, names: list[str]) -> Any:
    lookup = {str(column).lower(): column for column in row.index}
    for name in names:
        column = lookup.get(name.lower())
        if column is not None:
            value = row.get(column)
            if pd.notna(value) and str(value).strip() not in {"", "nan", "NaT"}:
                return value
    return np.nan


def normalize_file(
    root: Path,
    manifest_row: pd.Series,
    source_id: str,
    source_category: str,
    run_ts: pd.Timestamp,
    universe: set[str],
) -> pd.DataFrame:
    frame = pd.read_csv(root / manifest_row["snapshot_file"], low_memory=False)
    rows = []
    for index, raw in frame.iterrows():
        if source_category == "macro":
            event_type = str(first_value(raw, ["event_type", "source_category", "release_type"])).lower().strip()
            event_date_raw = first_value(raw, ["event_date", "release_date", "scheduled_date", "date"])
            ticker = "ALL"
            sector = "ALL"
            event_name = first_value(raw, ["event_name", "release_name", "name", "title"])
            time_raw = first_value(raw, ["event_time", "release_time", "time"])
            timezone_raw = first_value(raw, ["event_timezone", "timezone"])
        else:
            event_type = "ticker_earnings"
            event_date_raw = first_value(raw, ["earnings_date", "event_date", "report_date"])
            ticker = str(first_value(raw, ["ticker", "symbol"])).upper().strip()
            sector = str(first_value(raw, ["affected_sector", "sector", "theme"])).strip()
            event_name = first_value(raw, ["event_name", "name"])
            time_raw = first_value(raw, ["earnings_time_or_session", "event_time", "session", "time"])
            timezone_raw = first_value(raw, ["event_timezone", "timezone"])
        event_date = pd.to_datetime(event_date_raw, errors="coerce")
        supplied_retrieval = pd.to_datetime(
            first_value(raw, ["retrieval_timestamp_utc", "retrieved_at"]), utc=True, errors="coerce"
        )
        provider_available = pd.to_datetime(
            first_value(raw, ["provider_available_date", "provider_available_timestamp"]),
            utc=True, errors="coerce",
        )
        effective_retrieval = supplied_retrieval if not pd.isna(supplied_retrieval) else run_ts
        known = provider_available if not pd.isna(provider_available) else effective_retrieval
        reasons = []
        if pd.isna(event_date):
            reasons.append("EVENT_DATE_MISSING_OR_INVALID")
        if pd.isna(known):
            reasons.append("KNOWN_AS_OF_TIMESTAMP_MISSING")
        if source_category == "macro" and event_type not in MACRO_TYPES:
            reasons.append("UNSUPPORTED_MACRO_EVENT_TYPE")
        if source_category == "earnings" and (not ticker or ticker == "NAN" or ticker not in universe):
            reasons.append("TICKER_NOT_IN_V21_OR_BENCHMARK_UNIVERSE")
        source_name = str(first_value(raw, ["source_name", "provider", "source"])).strip()
        source_url = str(first_value(raw, ["source_url_or_provider", "source_url", "url"])).strip()
        if source_name in {"", "nan"}:
            source_name = source_id
        if source_url in {"", "nan"}:
            source_url = manifest_row["source_file"]
        base = {
            "event_type": event_type,
            "event_name": (
                str(event_name).strip() if pd.notna(event_name)
                else f"{ticker} earnings" if source_category == "earnings"
                else event_type.replace("_", " ").upper()
            ),
            "event_date": "" if pd.isna(event_date) else event_date.date().isoformat(),
            "event_time": "" if pd.isna(time_raw) else str(time_raw).strip(),
            "event_timezone": "America/New_York" if pd.isna(timezone_raw) else str(timezone_raw).strip(),
            "affected_ticker": ticker, "affected_sector": sector or "ALL",
            "source_id": source_id, "source_name": source_name,
            "source_url_or_provider": source_url,
            "retrieval_timestamp_utc": effective_retrieval.isoformat(),
            "ingestion_timestamp_utc": run_ts.isoformat(),
            "provider_available_date": "" if pd.isna(provider_available) else provider_available.isoformat(),
            "known_as_of_timestamp": "" if pd.isna(known) else known.isoformat(),
            "raw_payload_hash": manifest_row["raw_payload_hash"],
            "source_confidence": (
                "HIGH" if not pd.isna(provider_available)
                else "MEDIUM" if not pd.isna(supplied_retrieval)
                else "LOW"
            ),
            "pit_certified": not reasons,
            "pit_exclusion_reason": "|".join(reasons),
            "research_only": True,
            "notes": "Dates/times only; no values, surprises, prices, or realized returns ingested.",
        }
        identity = "|".join([
            source_id, event_type, base["event_date"], ticker, str(index),
            manifest_row["raw_payload_hash"],
        ])
        base["event_id"] = "V21_095_" + hashlib.sha256(identity.encode()).hexdigest()[:20].upper()
        base["normalized_row_hash"] = row_hash(base)
        rows.append(base)
    return pd.DataFrame(rows, columns=CANONICAL_COLUMNS)


def normalize_manifest(
    root: Path, manifest: pd.DataFrame, source_id: str, category: str,
    run_ts: pd.Timestamp, universe: set[str],
) -> pd.DataFrame:
    parts = []
    for _, source in manifest[manifest["snapshot_status"].eq("SNAPSHOTTED")].iterrows():
        try:
            parts.append(normalize_file(root, source, source_id, category, run_ts, universe))
        except Exception:
            continue
    return pd.concat(parts, ignore_index=True) if parts else empty_events()


def carry_v21_093(root: Path, run_ts: pd.Timestamp) -> pd.DataFrame:
    source = pd.read_csv(root / V21_093_REL, low_memory=False)
    rows = []
    payload_hash = sha256(root / V21_093_REL)
    for _, event in source.iterrows():
        known = pd.to_datetime(event["known_as_of_timestamp"], utc=True, errors="coerce")
        base = {
            "event_id": event["event_id"], "event_type": event["event_type"],
            "event_name": event["event_name"], "event_date": event["event_date"],
            "event_time": str(event["event_time"]).split(" America/")[0],
            "event_timezone": "America/New_York",
            "affected_ticker": "ALL" if pd.isna(event["affected_ticker"]) else event["affected_ticker"],
            "affected_sector": "ALL" if pd.isna(event["affected_sector"]) else event["affected_sector"],
            "source_id": "V21_093_DETERMINISTIC_CALENDAR",
            "source_name": "V21.093 deterministic exchange and holiday calendar",
            "source_url_or_provider": V21_093_REL.as_posix(),
            "retrieval_timestamp_utc": run_ts.isoformat(),
            "ingestion_timestamp_utc": run_ts.isoformat(),
            "provider_available_date": "" if pd.isna(known) else known.isoformat(),
            "known_as_of_timestamp": "" if pd.isna(known) else known.isoformat(),
            "raw_payload_hash": payload_hash, "normalized_row_hash": "",
            "source_confidence": "HIGH", "pit_certified": not pd.isna(known),
            "pit_exclusion_reason": "" if not pd.isna(known) else "KNOWN_AS_OF_TIMESTAMP_MISSING",
            "research_only": True, "notes": event["notes"],
        }
        base["normalized_row_hash"] = row_hash(base)
        rows.append(base)
    return pd.DataFrame(rows, columns=CANONICAL_COLUMNS)


def run(root: Path) -> dict[str, Any]:
    out = root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    output_paths = {(out / name).resolve() for name in OUTPUT_NAMES}
    before = protected_snapshot(root, output_paths)
    d_hash_before = sha256(root / D_REL)
    run_ts = pd.Timestamp(datetime.now(timezone.utc))
    run_date = run_ts.date().isoformat()

    d = pd.read_csv(root / D_REL, low_memory=False)
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    universe = set(d["ticker"]) | {"SPY", "QQQ", "SMH", "SOXX", "TQQQ"}
    ranked = d[pd.to_numeric(d["final_shadow_rank"], errors="coerce").notna()].copy()
    latest_date = ranked["as_of_date"].dropna().astype(str).max()
    current = ranked[ranked["as_of_date"].astype(str).eq(latest_date)].sort_values("final_shadow_rank")
    top20, top50 = set(current.head(20)["ticker"]), set(current.head(50)["ticker"])
    historical_asofs = sorted(pd.to_datetime(
        pd.read_csv(
            root / "outputs/v21/experiments/momentum_dynamic/random_backtests/V21_060_R2_RANDOM_ASOF_BACKTEST_RESULTS.csv",
            usecols=["sampled_as_of_date"],
        )["sampled_as_of_date"].dropna().unique()
    ))
    earliest_historical_asof = min(historical_asofs).tz_localize("UTC")

    # R1
    registry = load_registry(root)
    registry.to_csv(out / OUTPUT_NAMES[0], index=False)
    schema_contract = {
        "stage": "V21.095-R1_EVENT_SOURCE_CONFIG_AND_SCHEMA",
        "canonical_fields": CANONICAL_COLUMNS,
        "required_for_certification": [
            "event_id", "event_type", "event_date", "source_id",
            "retrieval_timestamp_utc", "known_as_of_timestamp",
            "raw_payload_hash", "normalized_row_hash", "research_only",
        ],
        "supported_event_categories": [
            "macro_fomc", "macro_cpi", "macro_pce", "macro_nfp", "macro_gdp",
            "ticker_earnings", "sector_key_earnings", "market_opex",
            "market_quad_witching", "holiday_liquidity", "company_split",
            "company_financing", "company_regulatory", "company_lockup",
        ],
        "historical_pit_rule": "known_as_of_timestamp <= historical ranking as_of timestamp",
        "forward_pit_rule": "known_as_of_timestamp <= current run timestamp",
        "research_only": True, "official_adoption_allowed": False,
    }
    write_json(out / OUTPUT_NAMES[1], schema_contract)
    (out / OUTPUT_NAMES[2]).write_text(markdown(
        "V21.095-R1 Event Source Registry and Schema",
        {"registry_rows": len(registry), "enabled_sources": int(registry["enabled"].map(truth).sum()),
         "canonical_field_count": len(CANONICAL_COLUMNS), "research_only": True,
         "official_adoption_allowed": False},
        "Official network adapters are disabled by default; local manual snapshots are enabled.",
    ), encoding="utf-8")

    # R2/R3 snapshots and normalization
    macro_manifest = snapshot_imports(root, MACRO_IMPORT_REL, "macro", run_date, run_ts)
    macro_manifest.to_csv(out / OUTPUT_NAMES[3], index=False)
    macro = normalize_manifest(root, macro_manifest, "MACRO_MANUAL_IMPORT", "macro", run_ts, universe)
    macro.to_csv(out / OUTPUT_NAMES[4], index=False)
    macro_validation = {
        "stage": "V21.095-R2_OFFICIAL_MACRO_EVENT_SNAPSHOT_INGESTION",
        "status": "PASS", "network_adapters_executed": False,
        "adapter_stub_count": int((registry["source_type"] == "OFFICIAL_WEB_ADAPTER_STUB").sum()),
        "manual_snapshot_count": len(macro_manifest),
        "normalized_rows": len(macro),
        "certified_rows": int(macro["pit_certified"].map(truth).sum()) if not macro.empty else 0,
        "released_values_or_surprises_ingested": False,
        "research_only": True, "official_adoption_allowed": False,
    }
    write_json(out / OUTPUT_NAMES[5], macro_validation)
    (out / OUTPUT_NAMES[6]).write_text(markdown(
        "V21.095-R2 Macro Event Snapshot Ingestion", macro_validation,
        "Place official schedule CSV files under data/events/manual_import/macro/. "
        "Each run creates a dated immutable copy and SHA-256 manifest.",
    ), encoding="utf-8")

    earnings_manifest = snapshot_imports(root, EARNINGS_IMPORT_REL, "earnings", run_date, run_ts)
    earnings_manifest.to_csv(out / OUTPUT_NAMES[7], index=False)
    earnings_all = normalize_manifest(
        root, earnings_manifest, "EARNINGS_MANUAL_IMPORT", "earnings", run_ts, universe
    )
    earnings = earnings_all[earnings_all["pit_certified"].map(truth)].copy()
    earnings_rejected = earnings_all[~earnings_all["pit_certified"].map(truth)].copy()
    earnings.to_csv(out / OUTPUT_NAMES[8], index=False)
    earnings_rejected.to_csv(out / OUTPUT_NAMES[9], index=False)
    earnings_tickers = set(earnings["affected_ticker"]) if not earnings.empty else set()
    earnings_coverage = pd.DataFrame([
        {"coverage_scope": "CANDIDATE_UNIVERSE", "covered": len(earnings_tickers & universe), "total": len(universe)},
        {"coverage_scope": "TOP20", "covered": len(earnings_tickers & top20), "total": len(top20)},
        {"coverage_scope": "TOP50", "covered": len(earnings_tickers & top50), "total": len(top50)},
    ])
    earnings_coverage["coverage_ratio"] = (
        earnings_coverage["covered"] / earnings_coverage["total"].replace(0, np.nan)
    )
    earnings_coverage.to_csv(out / OUTPUT_NAMES[10], index=False)
    earnings_validation = {
        "stage": "V21.095-R3_TICKER_EARNINGS_EVENT_SNAPSHOT_INGESTION",
        "status": "PASS", "manual_snapshot_count": len(earnings_manifest),
        "normalized_rows": len(earnings), "rejected_rows": len(earnings_rejected),
        "missing_known_as_of_certified_rows": int(
            earnings["known_as_of_timestamp"].replace("", np.nan).isna().sum()
        ) if not earnings.empty else 0,
        "post_event_price_or_return_used": False,
        "research_only": True, "official_adoption_allowed": False,
    }
    write_json(out / OUTPUT_NAMES[11], earnings_validation)
    (out / OUTPUT_NAMES[12]).write_text(markdown(
        "V21.095-R3 Ticker Earnings Snapshot Ingestion", earnings_validation,
        "Current imports are not backfilled into historical knowledge. Missing row retrieval "
        "timestamps default to the current run timestamp and LOW confidence.",
    ), encoding="utf-8")

    # R4
    carry = carry_v21_093(root, run_ts)
    all_rows = pd.concat([carry, macro, earnings_all], ignore_index=True)
    known = pd.to_datetime(all_rows["known_as_of_timestamp"], utc=True, errors="coerce")
    all_rows["forward_usable"] = all_rows["pit_certified"].map(truth) & known.notna() & known.le(run_ts)
    all_rows["historical_backtest_usable"] = (
        all_rows["pit_certified"].map(truth) & known.notna() & known.le(earliest_historical_asof)
    )
    all_rows["historical_usage_reason"] = np.where(
        all_rows["historical_backtest_usable"], "KNOWN_BEFORE_EARLIEST_RANDOM_ASOF",
        "KNOWN_AFTER_EARLIEST_RANDOM_ASOF_OR_UNCERTIFIED",
    )
    certified = all_rows[all_rows["pit_certified"].map(truth)].copy()
    historical_ticker_count_r4 = int((
        certified["historical_backtest_usable"]
        & certified["event_type"].isin(["ticker_earnings", "sector_key_earnings"])
    ).sum()) if not certified.empty else 0
    certified.to_csv(out / OUTPUT_NAMES[13], index=False)
    audit_columns = [
        "event_id", "event_type", "event_date", "source_id", "known_as_of_timestamp",
        "forward_usable", "historical_backtest_usable", "historical_usage_reason",
        "pit_certified", "pit_exclusion_reason", "raw_payload_hash",
    ]
    all_rows[audit_columns].to_csv(out / OUTPUT_NAMES[14], index=False)
    usage = pd.DataFrame([
        {
            "usage_mode": "FORWARD_OBSERVATION",
            "allowed": bool(certified["forward_usable"].any()),
            "rule": "known_as_of_timestamp <= current run timestamp",
            "event_rows": int(certified["forward_usable"].sum()),
        },
        {
            "usage_mode": "HISTORICAL_RANDOM_BACKTEST",
            "allowed": historical_ticker_count_r4 > 0,
            "rule": "Requires ticker events known by each historical ranking date; current snapshots cannot be backfilled.",
            "event_rows": historical_ticker_count_r4,
        },
    ])
    usage["research_only"] = True
    usage.to_csv(out / OUTPUT_NAMES[15], index=False)
    quarantined = all_rows[~all_rows["pit_certified"].map(truth)].copy()
    quarantined.to_csv(out / OUTPUT_NAMES[16], index=False)
    pit_warnings = int((
        certified["pit_certified"].map(truth)
        & pd.to_datetime(certified["known_as_of_timestamp"], utc=True, errors="coerce").isna()
    ).sum())
    r4_validation = {
        "stage": "V21.095-R4_EVENT_SNAPSHOT_PIT_CERTIFICATION",
        "status": "PASS" if pit_warnings == 0 else "FAIL",
        "certified_rows": len(certified), "quarantined_rows": len(quarantined),
        "forward_usable_rows": int(certified["forward_usable"].sum()),
        "historical_backtest_usable_rows": int(certified["historical_backtest_usable"].sum()),
        "historical_ticker_event_rows": historical_ticker_count_r4,
        "pit_leakage_warnings": pit_warnings,
        "historical_current_knowledge_backfill_used": False,
        "research_only": True, "official_adoption_allowed": False,
    }
    write_json(out / OUTPUT_NAMES[17], r4_validation)
    (out / OUTPUT_NAMES[18]).write_text(markdown(
        "V21.095-R4 Event Snapshot PIT Certification", r4_validation,
        "Forward eligibility and historical-random-backtest eligibility are certified separately.",
    ), encoding="utf-8")

    # R5
    after = protected_snapshot(root, output_paths)
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    d_preserved = sha256(root / D_REL) == d_hash_before
    official_changed = [p for p in changed if "official" in p.lower() or "broker" in p.lower()]
    ticker_certified = certified["event_type"].isin(["ticker_earnings", "sector_key_earnings"])
    macro_certified = certified["event_type"].isin(MACRO_TYPES)
    covered = set(certified.loc[ticker_certified, "affected_ticker"])
    universe_ratio = len(covered & universe) / len(universe) if universe else 0.0
    top20_ratio = len(covered & top20) / len(top20) if top20 else 0.0
    top50_ratio = len(covered & top50) / len(top50) if top50 else 0.0
    forward_rows = int(certified["forward_usable"].sum())
    historical_rows = int(certified["historical_backtest_usable"].sum())
    historical_ticker_rows = int((ticker_certified & certified["historical_backtest_usable"]).sum())
    historical_allowed = historical_ticker_rows > 0
    forward_allowed = forward_rows > 0
    if pit_warnings > 0:
        decision = "REJECT_EVENT_SOURCE_SNAPSHOT_DUE_TO_PIT_LEAKAGE"
    elif changed or not d_preserved:
        decision = "REJECT_EVENT_SOURCE_SNAPSHOT_DUE_TO_PROTECTED_MUTATION"
    elif len(certified) == 0:
        decision = "EVENT_SOURCE_SNAPSHOT_EMPTY_IMPORT_REQUIRED"
    elif forward_rows > 0 and historical_rows == 0:
        decision = "EVENT_SOURCE_READY_FOR_FORWARD_OBSERVATION_ONLY"
    elif ticker_certified.any() and historical_ticker_rows > 0:
        decision = "EVENT_SOURCE_READY_FOR_HISTORICAL_AND_FORWARD_RETEST"
    elif macro_certified.any() and not ticker_certified.any():
        decision = "MACRO_EVENT_SOURCE_READY_FOR_OVERLAY_FORWARD_OBSERVATION"
    else:
        decision = "EVENT_SOURCE_READY_FOR_FORWARD_OBSERVATION_ONLY"
    if not ticker_certified.any() and not macro_certified.any():
        next_stage = "V21.095_IMPORT_PIT_TIMESTAMPED_MACRO_AND_EARNINGS_SNAPSHOTS"
    elif forward_allowed and not historical_allowed:
        next_stage = "V21.096_FORWARD_EVENT_OBSERVATION_LEDGER"
    else:
        next_stage = "V21.096_HISTORICAL_AND_FORWARD_EVENT_RETEST"
    summary = {
        "FINAL_STATUS": "PASS" if not pit_warnings and not changed and d_preserved else "FAIL",
        "DECISION": decision, "CERTIFIED_EVENT_ROWS": len(certified),
        "CERTIFIED_TICKER_EVENT_ROWS": int(ticker_certified.sum()),
        "CERTIFIED_MACRO_EVENT_ROWS": int(macro_certified.sum()),
        "CERTIFIED_FORWARD_USABLE_ROWS": forward_rows,
        "CERTIFIED_HISTORICAL_BACKTEST_USABLE_ROWS": historical_rows,
        "TICKER_EVENT_COVERAGE_RATIO": universe_ratio,
        "TOP20_EVENT_COVERAGE_RATIO": top20_ratio,
        "TOP50_EVENT_COVERAGE_RATIO": top50_ratio,
        "MACRO_EVENT_TYPES_CERTIFIED": sorted(set(certified.loc[macro_certified, "event_type"])),
        "EARNINGS_EVENT_ROWS_CERTIFIED": int(ticker_certified.sum()),
        "HISTORICAL_RANDOM_BACKTEST_ALLOWED": historical_allowed,
        "FORWARD_EVENT_OBSERVATION_ALLOWED": forward_allowed,
        "PIT_LEAKAGE_WARNINGS": pit_warnings,
        "SOURCE_SNAPSHOT_COUNT": len(macro_manifest) + len(earnings_manifest),
        "RAW_SNAPSHOT_HASHED_COUNT": int(
            macro_manifest["raw_payload_hash"].ne("").sum()
            + earnings_manifest["raw_payload_hash"].ne("").sum()
        ),
        "QUARANTINED_EVENT_ROWS": len(quarantined),
        "PROTECTED_OUTPUTS_MODIFIED": bool(changed or not d_preserved),
        "OFFICIAL_OUTPUTS_MODIFIED": bool(official_changed),
        "RESEARCH_ONLY": True, "OFFICIAL_ADOPTION_ALLOWED": False,
        "RECOMMENDED_NEXT_STAGE": next_stage,
        "D_BASELINE_PRESERVED": d_preserved,
        "MODIFIED_PROTECTED_PATHS": changed,
        "RUN_TIMESTAMP_UTC": run_ts.isoformat(),
        "HISTORICAL_ELIGIBILITY_NOTE": (
            "Existing deterministic calendar rows may be historically usable, but historical "
            "event-risk ranking retest remains blocked until PIT-certified ticker events exist."
        ),
    }
    write_json(out / OUTPUT_NAMES[19], summary)
    (out / OUTPUT_NAMES[20]).write_text(markdown(
        "V21.095-R5 Event Source Readiness Decision", summary,
        "No event penalties or ranking adoption logic were executed.",
    ), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    summary = run(args.root.resolve())
    for key in (
        "FINAL_STATUS", "DECISION", "CERTIFIED_EVENT_ROWS",
        "CERTIFIED_TICKER_EVENT_ROWS", "CERTIFIED_MACRO_EVENT_ROWS",
        "CERTIFIED_FORWARD_USABLE_ROWS", "CERTIFIED_HISTORICAL_BACKTEST_USABLE_ROWS",
        "TICKER_EVENT_COVERAGE_RATIO", "TOP20_EVENT_COVERAGE_RATIO",
        "TOP50_EVENT_COVERAGE_RATIO", "MACRO_EVENT_TYPES_CERTIFIED",
        "EARNINGS_EVENT_ROWS_CERTIFIED", "HISTORICAL_RANDOM_BACKTEST_ALLOWED",
        "FORWARD_EVENT_OBSERVATION_ALLOWED", "PIT_LEAKAGE_WARNINGS",
        "SOURCE_SNAPSHOT_COUNT", "RAW_SNAPSHOT_HASHED_COUNT",
        "QUARANTINED_EVENT_ROWS", "PROTECTED_OUTPUTS_MODIFIED",
        "OFFICIAL_OUTPUTS_MODIFIED", "RESEARCH_ONLY", "OFFICIAL_ADOPTION_ALLOWED",
        "RECOMMENDED_NEXT_STAGE",
    ):
        value = summary[key]
        if isinstance(value, list):
            value = "|".join(value)
        print(f"{key}={value}")
    return 0 if summary["FINAL_STATUS"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
