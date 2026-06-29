#!/usr/bin/env python
"""V21.095-R6 import PIT-timestamped manual event snapshots."""

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


OUT_REL = Path("outputs/v21")
BASE_LEDGER_REL = Path("outputs/v21/v21_095_r4_certified_event_snapshot_ledger.csv")
D_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/"
    "V21_060_R5_D_WEIGHT_OPTIMIZED_RANKING.csv"
)
RANDOM_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/random_backtests/"
    "V21_060_R2_RANDOM_ASOF_BACKTEST_RESULTS.csv"
)
IMPORT_SPECS = {
    "macro": Path("data/events/manual_import/macro"),
    "earnings": Path("data/events/manual_import/earnings"),
    "company_actions": Path("data/events/manual_import/company_actions"),
    "sector_events": Path("data/events/manual_import/sector_events"),
}
RAW_REL = Path("data/events/raw_snapshots")
MACRO_TYPES = {"macro_fomc", "macro_cpi", "macro_pce", "macro_nfp", "macro_gdp"}
TICKER_TYPES = {
    "ticker_earnings", "sector_key_earnings", "company_split",
    "company_financing", "company_regulatory", "company_lockup",
}
ALLOWED_TYPES = MACRO_TYPES | TICKER_TYPES
COMMON_REQUIRED = {
    "event_type", "event_name", "event_date", "event_time", "event_timezone",
    "source_name", "source_url_or_provider", "retrieval_timestamp_utc",
    "provider_available_date", "notes",
}
EARNINGS_REQUIRED = COMMON_REQUIRED | {"ticker", "earnings_session"}
CANONICAL = [
    "event_id", "event_type", "event_name", "event_date", "event_time",
    "event_timezone", "affected_ticker", "affected_sector", "earnings_session",
    "candidate_universe_member", "source_name", "source_url_or_provider",
    "retrieval_timestamp_utc", "provider_available_date",
    "known_as_of_timestamp", "raw_payload_hash", "normalized_row_hash",
    "source_confidence", "pit_certified", "pit_exclusion_reason",
    "historical_backtest_usable", "forward_observation_usable",
    "research_only", "notes",
]
OUTPUT_NAMES = (
    "v21_095_r6_manual_import_manifest.csv",
    "v21_095_r6_raw_snapshot_hash_manifest.csv",
    "v21_095_r6_macro_events_normalized.csv",
    "v21_095_r6_ticker_earnings_events_normalized.csv",
    "v21_095_r6_certified_event_snapshot_ledger.csv",
    "v21_095_r6_rejected_or_quarantined_import_rows.csv",
    "v21_095_r6_event_coverage_by_ticker.csv",
    "v21_095_r6_event_coverage_by_event_type.csv",
    "v21_095_r6_pit_certification_audit.csv",
    "v21_095_r6_import_pit_timestamped_event_snapshots_report.md",
    "v21_095_r6_import_pit_timestamped_event_snapshots_summary.json",
)


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_hash(row: dict[str, Any]) -> str:
    payload = json.dumps(row, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=json_default) + "\n", encoding="utf-8")


def markdown(title: str, summary: dict[str, Any], note: str) -> str:
    lines = [f"# {title}", ""]
    lines.extend(f"- {key}: `{value}`" for key, value in summary.items())
    lines.extend(["", note])
    return "\n".join(lines) + "\n"


def empty_events() -> pd.DataFrame:
    return pd.DataFrame(columns=CANONICAL)


def protected_snapshot(root: Path, output_paths: set[Path]) -> dict[str, str]:
    tokens = (
        "official", "broker", "protected", "forward_observation_ledger",
        "060_r5_d_", "066a_d_latest_ranking", "p03", "p04",
    )
    event_root = (root / "data/events").resolve()
    result = {}
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.resolve() in output_paths:
                continue
            if event_root in path.resolve().parents:
                continue
            if any(token in path.as_posix().lower() for token in tokens):
                result[path.relative_to(root).as_posix()] = sha256(path)
    return result


def scan_imports(root: Path) -> pd.DataFrame:
    rows = []
    for category, directory in IMPORT_SPECS.items():
        path_dir = root / directory
        path_dir.mkdir(parents=True, exist_ok=True)
        required = COMMON_REQUIRED if category == "macro" else EARNINGS_REQUIRED
        for path in sorted(path_dir.rglob("*.csv")):
            columns: list[str] = []
            row_count = 0
            read_error = ""
            try:
                columns = list(pd.read_csv(path, nrows=0, low_memory=False).columns)
                row_count = len(pd.read_csv(path, low_memory=False))
            except Exception as exc:
                read_error = f"READ_ERROR:{type(exc).__name__}"
            normalized_columns = {str(column).strip().lower() for column in columns}
            missing = sorted(required - normalized_columns)
            safe = not read_error and not missing
            reason = read_error or (
                "MISSING_REQUIRED_COLUMNS:" + "|".join(missing) if missing else ""
            )
            rows.append({
                "import_path": path.relative_to(root).as_posix(),
                "source_category": category, "exists": path.is_file(),
                "file_size_bytes": path.stat().st_size,
                "last_modified_timestamp": datetime.fromtimestamp(
                    path.stat().st_mtime, timezone.utc
                ).isoformat(),
                "row_count": row_count, "columns_detected": "|".join(columns),
                "required_columns_present": not missing,
                "raw_file_hash": sha256(path),
                "safe_to_import": safe, "quarantine_reason": reason,
                "notes": "File-level schema validation only; rows receive separate PIT validation.",
            })
    return pd.DataFrame(rows, columns=[
        "import_path", "source_category", "exists", "file_size_bytes",
        "last_modified_timestamp", "row_count", "columns_detected",
        "required_columns_present", "raw_file_hash", "safe_to_import",
        "quarantine_reason", "notes",
    ])


def snapshot_files(
    root: Path, manifest: pd.DataFrame, run_date: str, run_ts: pd.Timestamp
) -> pd.DataFrame:
    rows = []
    for _, item in manifest[manifest["safe_to_import"].map(truth)].iterrows():
        source = root / item["import_path"]
        destination_dir = root / RAW_REL / run_date / item["source_category"]
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / source.name
        if destination.exists() and sha256(destination) != item["raw_file_hash"]:
            destination = destination_dir / f"{source.stem}__{item['raw_file_hash'][:12]}{source.suffix}"
        if not destination.exists():
            shutil.copy2(source, destination)
        snapshot_hash = sha256(destination)
        rows.append({
            "source_import_path": item["import_path"],
            "snapshot_path": destination.relative_to(root).as_posix(),
            "source_category": item["source_category"],
            "raw_file_hash": item["raw_file_hash"],
            "snapshot_file_hash": snapshot_hash,
            "hash_match": snapshot_hash == item["raw_file_hash"],
            "snapshot_timestamp_utc": run_ts.isoformat(),
            "notes": "Original filename preserved unless a same-day name collision had different content.",
        })
    return pd.DataFrame(rows, columns=[
        "source_import_path", "snapshot_path", "source_category", "raw_file_hash",
        "snapshot_file_hash", "hash_match", "snapshot_timestamp_utc", "notes",
    ])


def clean(value: Any) -> str:
    return "" if pd.isna(value) else str(value).strip()


def normalize_rows(
    root: Path,
    snapshot_manifest: pd.DataFrame,
    universe: set[str],
    run_ts: pd.Timestamp,
    historical_min: pd.Timestamp,
    historical_max: pd.Timestamp,
    recent_buffer_days: int = 7,
) -> pd.DataFrame:
    rows = []
    for _, source in snapshot_manifest[snapshot_manifest["hash_match"].map(truth)].iterrows():
        frame = pd.read_csv(root / source["snapshot_path"], low_memory=False)
        frame.columns = [str(column).strip().lower() for column in frame.columns]
        category = source["source_category"]
        for index, raw in frame.iterrows():
            event_type = clean(raw.get("event_type")).lower()
            event_date = pd.to_datetime(raw.get("event_date"), errors="coerce")
            retrieval = pd.to_datetime(
                raw.get("retrieval_timestamp_utc"), utc=True, errors="coerce"
            )
            provider = pd.to_datetime(
                raw.get("provider_available_date"), utc=True, errors="coerce"
            )
            # Provider availability can move known-as-of earlier only when explicitly supplied
            # and earlier than the retrieval timestamp.
            if not pd.isna(provider) and not pd.isna(retrieval) and provider < retrieval:
                known = provider
                confidence = "HIGH"
                historical_evidence = True
            else:
                known = retrieval
                confidence = "MEDIUM" if not pd.isna(retrieval) else "LOW"
                historical_evidence = False
            ticker = "ALL" if category == "macro" else clean(raw.get("ticker")).upper()
            sector = "ALL" if category == "macro" else clean(raw.get("affected_sector")) or "ALL"
            reasons = []
            if event_type not in ALLOWED_TYPES:
                reasons.append("INVALID_EVENT_TYPE")
            if category == "macro" and event_type not in MACRO_TYPES:
                reasons.append("NON_MACRO_TYPE_IN_MACRO_IMPORT")
            if category != "macro" and event_type not in TICKER_TYPES:
                reasons.append("NON_TICKER_TYPE_IN_TICKER_IMPORT")
            if pd.isna(event_date):
                reasons.append("EVENT_DATE_MISSING_OR_INVALID")
            if pd.isna(retrieval):
                reasons.append("RETRIEVAL_TIMESTAMP_UTC_MISSING_OR_INVALID")
            if pd.isna(known):
                reasons.append("KNOWN_AS_OF_TIMESTAMP_MISSING")
            if category != "macro" and not ticker:
                reasons.append("TICKER_MISSING")
            if not pd.isna(provider) and not pd.isna(retrieval) and provider > retrieval:
                reasons.append("PROVIDER_AVAILABLE_AFTER_RETRIEVAL_IGNORED")
            pit_certified = not any(reason for reason in reasons if reason != "PROVIDER_AVAILABLE_AFTER_RETRIEVAL_IGNORED")
            historical_usable = bool(
                pit_certified
                and historical_evidence
                and known <= historical_max
                and event_date.tz_localize("UTC") >= historical_min - pd.Timedelta(days=7)
                and event_date.tz_localize("UTC") <= historical_max + pd.Timedelta(days=7)
            )
            forward_usable = bool(
                pit_certified
                and known <= run_ts
                and event_date.date() >= (run_ts - pd.Timedelta(days=recent_buffer_days)).date()
            )
            base = {
                "event_type": event_type,
                "event_name": clean(raw.get("event_name")),
                "event_date": "" if pd.isna(event_date) else event_date.date().isoformat(),
                "event_time": clean(raw.get("event_time")),
                "event_timezone": clean(raw.get("event_timezone")),
                "affected_ticker": ticker, "affected_sector": sector,
                "earnings_session": clean(raw.get("earnings_session")),
                "candidate_universe_member": ticker in universe if ticker != "ALL" else False,
                "source_name": clean(raw.get("source_name")),
                "source_url_or_provider": clean(raw.get("source_url_or_provider")),
                "retrieval_timestamp_utc": "" if pd.isna(retrieval) else retrieval.isoformat(),
                "provider_available_date": "" if pd.isna(provider) else provider.isoformat(),
                "known_as_of_timestamp": "" if pd.isna(known) else known.isoformat(),
                "raw_payload_hash": source["raw_file_hash"],
                "normalized_row_hash": "",
                "source_confidence": confidence, "pit_certified": pit_certified,
                "pit_exclusion_reason": "|".join(reasons),
                "historical_backtest_usable": historical_usable,
                "forward_observation_usable": forward_usable,
                "research_only": True, "notes": clean(raw.get("notes")),
            }
            identity = "|".join([
                source["raw_file_hash"], str(index), event_type, base["event_date"], ticker
            ])
            base["event_id"] = "V21_095_R6_" + hashlib.sha256(
                identity.encode("utf-8")
            ).hexdigest()[:20].upper()
            base["normalized_row_hash"] = normalized_hash(base)
            rows.append(base)
    return pd.DataFrame(rows, columns=CANONICAL) if rows else empty_events()


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
    random_dates = pd.to_datetime(pd.read_csv(
        root / RANDOM_REL, usecols=["sampled_as_of_date"]
    )["sampled_as_of_date"].dropna().unique(), utc=True)
    historical_min, historical_max = random_dates.min(), random_dates.max()

    manifest = scan_imports(root)
    manifest.to_csv(out / OUTPUT_NAMES[0], index=False)
    snapshots = snapshot_files(root, manifest, run_date, run_ts)
    snapshots.to_csv(out / OUTPUT_NAMES[1], index=False)
    normalized = normalize_rows(
        root, snapshots, universe, run_ts, historical_min, historical_max
    )
    certified_mask = normalized["pit_certified"].map(truth).astype(bool)
    certified_new = normalized.loc[certified_mask].copy()
    quarantined = normalized.loc[~certified_mask].copy()
    macro = certified_new.loc[certified_new["event_type"].isin(MACRO_TYPES)].copy()
    ticker_events = certified_new.loc[certified_new["event_type"].isin(TICKER_TYPES)].copy()
    macro.to_csv(out / OUTPUT_NAMES[2], index=False)
    ticker_events.to_csv(out / OUTPUT_NAMES[3], index=False)

    base = pd.read_csv(root / BASE_LEDGER_REL, low_memory=False)
    base["earnings_session"] = ""
    base["candidate_universe_member"] = base["affected_ticker"].isin(universe)
    base["forward_observation_usable"] = base["forward_usable"].map(truth)
    for column in CANONICAL:
        if column not in base:
            base[column] = ""
    base_canonical = base[CANONICAL].copy()
    merged = pd.concat([base_canonical, certified_new], ignore_index=True)
    merged = merged.drop_duplicates("event_id", keep="last")
    merged.to_csv(out / OUTPUT_NAMES[4], index=False)

    file_rejections = manifest.loc[~manifest["safe_to_import"].map(truth).astype(bool)].copy()
    if not file_rejections.empty:
        file_rows = []
        for _, item in file_rejections.iterrows():
            row = {column: "" for column in CANONICAL}
            row.update({
                "event_id": "FILE_QUARANTINE_" + item["raw_file_hash"][:20].upper(),
                "source_name": item["import_path"],
                "raw_payload_hash": item["raw_file_hash"],
                "source_confidence": "NONE", "pit_certified": False,
                "pit_exclusion_reason": item["quarantine_reason"],
                "research_only": True,
                "notes": "File-level quarantine; no row normalization attempted.",
            })
            file_rows.append(row)
        quarantined = pd.concat(
            [quarantined, pd.DataFrame(file_rows, columns=CANONICAL)], ignore_index=True
        )
    quarantined.to_csv(out / OUTPUT_NAMES[5], index=False)

    covered = set(merged.loc[
        merged["event_type"].isin(TICKER_TYPES) & merged["pit_certified"].map(truth),
        "affected_ticker",
    ])
    coverage_ticker = pd.DataFrame({"ticker": sorted(universe)})
    counts = merged[
        merged["affected_ticker"].isin(universe) & merged["pit_certified"].map(truth)
    ].groupby("affected_ticker").agg(
        certified_event_rows=("event_id", "count"),
        event_types=("event_type", lambda values: "|".join(sorted(set(values)))),
        forward_usable_rows=("forward_observation_usable", lambda values: int(values.map(truth).sum())),
        historical_usable_rows=("historical_backtest_usable", lambda values: int(values.map(truth).sum())),
    ).reset_index().rename(columns={"affected_ticker": "ticker"})
    coverage_ticker = coverage_ticker.merge(counts, on="ticker", how="left")
    coverage_ticker["certified_event_rows"] = coverage_ticker["certified_event_rows"].fillna(0).astype(int)
    coverage_ticker["current_top20"] = coverage_ticker["ticker"].isin(top20)
    coverage_ticker["current_top50"] = coverage_ticker["ticker"].isin(top50)
    coverage_ticker.to_csv(out / OUTPUT_NAMES[6], index=False)
    coverage_type = merged.groupby("event_type", dropna=False).agg(
        event_rows=("event_id", "count"),
        pit_certified_rows=("pit_certified", lambda values: int(values.map(truth).sum())),
        forward_usable_rows=("forward_observation_usable", lambda values: int(values.map(truth).sum())),
        historical_usable_rows=("historical_backtest_usable", lambda values: int(values.map(truth).sum())),
        affected_ticker_count=("affected_ticker", lambda values: values[~values.isin(["", "ALL"])].nunique()),
    ).reset_index()
    coverage_type.to_csv(out / OUTPUT_NAMES[7], index=False)

    audit = pd.concat([
        normalized.assign(import_disposition=np.where(
            normalized["pit_certified"].map(truth), "CERTIFIED", "QUARANTINED"
        )),
        base_canonical.assign(import_disposition="EXISTING_V21_095_LEDGER"),
    ], ignore_index=True)
    audit["known_timestamp_parseable"] = pd.to_datetime(
        audit["known_as_of_timestamp"], utc=True, errors="coerce"
    ).notna()
    audit["pit_leakage_warning"] = (
        audit["pit_certified"].map(truth) & ~audit["known_timestamp_parseable"]
    )
    audit.to_csv(out / OUTPUT_NAMES[8], index=False)

    after = protected_snapshot(root, output_paths)
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    d_preserved = sha256(root / D_REL) == d_hash_before
    official_changed = [path for path in changed if "official" in path.lower() or "broker" in path.lower()]
    warnings = int(audit["pit_leakage_warning"].sum())
    total_certified = int(merged["pit_certified"].map(truth).sum())
    new_ticker = int(certified_new["event_type"].isin(TICKER_TYPES).sum())
    new_macro = int(certified_new["event_type"].isin(MACRO_TYPES).sum())
    forward_rows = int(merged["forward_observation_usable"].map(truth).sum())
    historical_rows = int(merged["historical_backtest_usable"].map(truth).sum())
    historical_ticker = int((
        merged["historical_backtest_usable"].map(truth)
        & merged["event_type"].isin(TICKER_TYPES)
    ).sum())
    files_found, files_imported = len(manifest), len(snapshots)
    pit_ratio = (
        len(certified_new) / len(normalized) if len(normalized)
        else 1.0 if files_found == 0 else 0.0
    )
    if warnings > 0:
        decision = "REJECT_IMPORT_DUE_TO_PIT_LEAKAGE"
    elif changed or not d_preserved:
        decision = "REJECT_IMPORT_DUE_TO_PROTECTED_MUTATION"
    elif files_found == 0:
        decision = "NO_MANUAL_EVENT_IMPORT_FILES_FOUND"
    elif len(certified_new) == 0:
        decision = "MANUAL_EVENT_IMPORT_FOUND_BUT_NO_CERTIFIED_ROWS"
    elif new_ticker > 0 and historical_ticker > 0:
        decision = "EVENT_SNAPSHOTS_READY_FOR_FORWARD_AND_HISTORICAL_RETEST"
    else:
        decision = "PIT_TIMESTAMPED_EVENT_SNAPSHOTS_IMPORTED_READY_FOR_FORWARD_OBSERVATION"
    historical_allowed = historical_ticker > 0
    forward_allowed = bool(
        new_ticker > 0 or new_macro > 0
    ) and bool(certified_new["forward_observation_usable"].map(truth).any())
    next_stage = (
        "ADD_PIT_TIMESTAMPED_CSV_FILES_TO_DATA_EVENTS_MANUAL_IMPORT"
        if files_found == 0
        else "V21.096_FORWARD_EVENT_OBSERVATION_LEDGER"
        if not historical_allowed
        else "V21.096_HISTORICAL_AND_FORWARD_EVENT_RETEST"
    )
    summary = {
        "FINAL_STATUS": "PASS" if not warnings and not changed and d_preserved else "FAIL",
        "DECISION": decision, "MANUAL_IMPORT_FILES_FOUND": files_found,
        "MANUAL_IMPORT_FILES_IMPORTED": files_imported,
        "RAW_SNAPSHOT_HASHED_COUNT": int(snapshots["hash_match"].map(truth).sum()),
        "CERTIFIED_EVENT_ROWS_TOTAL": total_certified,
        "CERTIFIED_EVENT_ROWS_NEW": len(certified_new),
        "CERTIFIED_TICKER_EVENT_ROWS": new_ticker,
        "CERTIFIED_MACRO_EVENT_ROWS": new_macro,
        "CERTIFIED_FORWARD_USABLE_ROWS": forward_rows,
        "CERTIFIED_HISTORICAL_BACKTEST_USABLE_ROWS": historical_rows,
        "TICKER_EVENT_COVERAGE_RATIO": len(covered & universe) / len(universe) if universe else 0.0,
        "TOP20_EVENT_COVERAGE_RATIO": len(covered & top20) / len(top20) if top20 else 0.0,
        "TOP50_EVENT_COVERAGE_RATIO": len(covered & top50) / len(top50) if top50 else 0.0,
        "MACRO_EVENT_TYPES_CERTIFIED": sorted(set(macro["event_type"])),
        "EARNINGS_EVENT_ROWS_CERTIFIED": int(
            certified_new["event_type"].isin({"ticker_earnings", "sector_key_earnings"}).sum()
        ),
        "QUARANTINED_EVENT_ROWS": len(quarantined),
        "PIT_CERTIFIED_RATIO": pit_ratio, "PIT_LEAKAGE_WARNINGS": warnings,
        "HISTORICAL_RANDOM_BACKTEST_ALLOWED": historical_allowed,
        "FORWARD_EVENT_OBSERVATION_ALLOWED": forward_allowed,
        "PROTECTED_OUTPUTS_MODIFIED": bool(changed or not d_preserved),
        "OFFICIAL_OUTPUTS_MODIFIED": bool(official_changed),
        "RESEARCH_ONLY": True, "OFFICIAL_ADOPTION_ALLOWED": False,
        "RECOMMENDED_NEXT_STAGE": next_stage,
        "D_BASELINE_PRESERVED": d_preserved, "MODIFIED_PROTECTED_PATHS": changed,
        "RUN_TIMESTAMP_UTC": run_ts.isoformat(),
    }
    write_json(out / OUTPUT_NAMES[10], summary)
    (out / OUTPUT_NAMES[9]).write_text(markdown(
        "V21.095-R6 Import PIT-Timestamped Event Snapshots", summary,
        "No ranking penalties, D-baseline changes, or adoption logic were executed.",
    ), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    summary = run(args.root.resolve())
    for key in (
        "FINAL_STATUS", "DECISION", "MANUAL_IMPORT_FILES_FOUND",
        "MANUAL_IMPORT_FILES_IMPORTED", "RAW_SNAPSHOT_HASHED_COUNT",
        "CERTIFIED_EVENT_ROWS_TOTAL", "CERTIFIED_EVENT_ROWS_NEW",
        "CERTIFIED_TICKER_EVENT_ROWS", "CERTIFIED_MACRO_EVENT_ROWS",
        "CERTIFIED_FORWARD_USABLE_ROWS", "CERTIFIED_HISTORICAL_BACKTEST_USABLE_ROWS",
        "TICKER_EVENT_COVERAGE_RATIO", "TOP20_EVENT_COVERAGE_RATIO",
        "TOP50_EVENT_COVERAGE_RATIO", "MACRO_EVENT_TYPES_CERTIFIED",
        "EARNINGS_EVENT_ROWS_CERTIFIED", "QUARANTINED_EVENT_ROWS",
        "PIT_CERTIFIED_RATIO", "PIT_LEAKAGE_WARNINGS",
        "HISTORICAL_RANDOM_BACKTEST_ALLOWED", "FORWARD_EVENT_OBSERVATION_ALLOWED",
        "PROTECTED_OUTPUTS_MODIFIED", "OFFICIAL_OUTPUTS_MODIFIED",
        "RESEARCH_ONLY", "OFFICIAL_ADOPTION_ALLOWED", "RECOMMENDED_NEXT_STAGE",
    ):
        value = summary[key]
        if isinstance(value, list):
            value = "|".join(value)
        print(f"{key}={value}")
    return 0 if summary["FINAL_STATUS"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
