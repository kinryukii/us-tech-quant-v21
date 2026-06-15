from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "outputs" / "v20" / "ops"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

SOURCE_FULL = ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_FULL_RANKED_CANDIDATES.csv"
SOURCE_RANKED = ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_RANKED_CANDIDATES.csv"
SOURCE_TOP = ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_TOP_RANKED_CANDIDATES.csv"
SOURCE_READ_FIRST = ROOT / "outputs" / "v18" / "ops" / "V18_35D_READ_FIRST.txt"
PRICE_CACHE = ROOT / "state" / "v18" / "price_cache"
FACTOR_AUDIT = ROOT / "outputs" / "v18" / "factor_pack" / "V18_CURRENT_RAW105_FACTOR_PACK_RANKING_SOURCE_AUDIT.csv"
TECHNICAL_AUDIT = ROOT / "outputs" / "v18" / "technical_timing" / "V18_6A_CURRENT_TECHNICAL_TIMING_SOURCE_AUDIT.csv"
V20_47_SUMMARY = CONSOLIDATION / "V20_47_CONTROLLED_REFRESH_SUMMARY.csv"
PROVIDER_DIAGNOSTICS = CONSOLIDATION / "V20_47_PROVIDER_REFRESH_DIAGNOSTICS.csv"
V20_47_CANDIDATE_CERTIFICATION = CONSOLIDATION / "V20_47_CURRENT_CANDIDATE_PRICE_CERTIFICATION.csv"

OUT_STAGING = CONSOLIDATION / "V20_7V_ACTIVE_MARKET_SOURCE_STAGING.csv"
OUT_FIELD_AUDIT = CONSOLIDATION / "V20_7V_ACTIVE_MARKET_SOURCE_FIELD_AUDIT.csv"
OUT_LINEAGE_AUDIT = CONSOLIDATION / "V20_7V_ACTIVE_MARKET_SOURCE_LINEAGE_AUDIT.csv"
OUT_SOURCE_AUDIT = CONSOLIDATION / "V20_7V_SOURCE_AUDIT.csv"
OUT_SAMPLE_AUDIT = CONSOLIDATION / "V20_7V_ACTIVE_MARKET_SOURCE_SAMPLE_ID_AUDIT.csv"
OUT_PRECHECK = CONSOLIDATION / "V20_7V_ACTIVE_MARKET_SOURCE_CERTIFICATION_PRECHECK.csv"
OUT_DIAGNOSTICS = CONSOLIDATION / "V20_7V_PRECHECK_DIAGNOSTICS.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_7V_BLOCKER_REGISTER.csv"
OUT_NEXT = CONSOLIDATION / "V20_7V_NEXT_STEP_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_7V_VALIDATION_SUMMARY.csv"
OUT_EXCLUDED = CONSOLIDATION / "V20_7V_EXCLUDED_TICKERS.csv"

REPORT = READ_CENTER / "V20_7V_ACTIVE_MARKET_SOURCE_STAGING_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_ACTIVE_MARKET_SOURCE_STAGING.md"
READ_FIRST = OPS / "V20_7V_READ_FIRST.txt"

PATCH_VERSION = "V20.7V"
SOURCE_SYSTEM = "accepted_v18_full_universe_result"
SOURCE_VERSION_PREFIX = "V18.35D_CURRENT_FULL_UNIVERSE"
SOURCE_ARTIFACT_PREFIX = "V20_7V_CURRENT_V18_FULL_UNIVERSE"

STAGING_FIELDS = [
    "ticker",
    "observation_date",
    "signal_date",
    "price_date",
    "latest_price_date",
    "latest_close",
    "close",
    "rank",
    "composite_candidate_score",
    "factor_score",
    "technical_score",
    "source_artifact_id",
    "source_path",
    "source_hash",
    "run_id",
    "sample_id",
    "active_runtime_flag",
    "historical_reference_flag",
    "availability_date",
    "created_at_utc",
    "source_system",
    "source_version",
    "lineage_status",
    "pit_ready_candidate_flag",
    "stale_check_candidate_flag",
    "leakage_check_candidate_flag",
    "certification_candidate_flag",
]

CORE_PRECHECK_FIELDS = [
    "ticker",
    "observation_date",
    "signal_date",
    "price_date",
    "latest_price_date",
    "latest_close",
    "close",
    "rank",
    "composite_candidate_score",
    "source_artifact_id",
    "source_path",
    "source_hash",
    "run_id",
    "sample_id",
    "active_runtime_flag",
    "historical_reference_flag",
    "availability_date",
    "created_at_utc",
    "source_system",
    "source_version",
]

SAFETY_FLAGS = {
    "NORMALIZED_ROWS_CREATED": "0",
    "FACTOR_EVIDENCE_ROWS_CREATED": "0",
    "BACKTEST_ROWS_CREATED": "0",
    "DYNAMIC_WEIGHTING_ROWS_CREATED": "0",
    "TRADING_SIGNAL_ROWS_CREATED": "0",
    "OFFICIAL_RECOMMENDATION_ROWS_CREATED": "0",
    "BROKER_API_USED": "FALSE",
    "ORDER_EXECUTION_USED": "FALSE",
}

EXCLUDED_FIELDS = [
    "ticker",
    "rank",
    "latest_price_date",
    "latest_close",
    "composite_candidate_score",
    "exclusion_reason",
    "supporting_reason",
    "provider_refresh_status",
    "provider_failure_reason",
    "provider_exception_type",
    "provider_exception_message",
    "factor_exclusion_reason",
    "technical_exclusion_reason",
    "factor_price_history_row_count",
    "technical_price_history_row_count",
    "source_path",
    "source_hash",
    "run_id",
    "created_at_utc",
    "quarantine_status",
]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean(value: object) -> str:
    return str(value or "").strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def date_distribution(rows: list[dict[str, str]], field: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        value = clean(row.get(field))
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))


def parse_date_text(value: object) -> str:
    text = clean(value)[:10]
    if len(text) != 10:
        return ""
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return text
    except ValueError:
        return ""


def expected_market_date_from(rows: list[dict[str, str]]) -> str:
    dates = sorted({
        parse_date_text(row.get("latest_price_date") or row.get("price_date") or row.get("signal_date") or row.get("observation_date"))
        for row in rows
    })
    dates = [date for date in dates if date]
    return dates[-1] if dates else ""


def distribution_text(dist: dict[str, int]) -> str:
    return ";".join(f"{key}={value}" for key, value in dist.items())


def deterministic_sample_id(row: dict[str, str], source_hash: str, run_id: str) -> str:
    basis = "|".join([
        clean(row.get("ticker")).upper(),
        clean(row.get("latest_price_date")),
        clean(row.get("rank")),
        clean(row.get("source_artifact_id")),
        source_hash,
        run_id,
    ])
    return "V20_7V_SAMPLE_" + sha256_text(basis)[:24].upper()


def latest_price_cache_row(ticker: str) -> dict[str, str]:
    path = PRICE_CACHE / f"{ticker.upper()}.csv"
    rows, _ = read_csv(path)
    parsed = [
        row for row in rows
        if parse_date_text(row.get("date")) and clean(row.get("close") or row.get("adj_close"))
    ]
    if not parsed:
        return {}
    parsed.sort(key=lambda row: parse_date_text(row.get("date")))
    row = dict(parsed[-1])
    row["_source_file"] = rel(path)
    return row


def rows_by_ticker(path: Path) -> dict[str, dict[str, str]]:
    rows, _ = read_csv(path)
    return {
        clean(row.get("ticker")).upper(): row
        for row in rows
        if clean(row.get("ticker"))
    }


def first_row(path: Path) -> dict[str, str]:
    rows, _ = read_csv(path)
    return rows[0] if rows else {}


def provider_status_by_ticker() -> dict[str, dict[str, str]]:
    provider_rows = rows_by_ticker(PROVIDER_DIAGNOSTICS)
    summary = first_row(V20_47_SUMMARY)
    fallback_handoff = (
        clean(summary.get("certification_status")) == "CERTIFIED_CACHE_FALLBACK_HANDOFF"
        and clean(summary.get("fallback_used")).upper() == "TRUE"
    )
    if not fallback_handoff:
        return provider_rows

    certification_rows, _ = read_csv(V20_47_CANDIDATE_CERTIFICATION)
    for cert in certification_rows:
        ticker = clean(cert.get("ticker")).upper()
        if not ticker or clean(cert.get("certification_status")) != "CERTIFIED":
            continue
        provider_rows[ticker] = {
            "ticker": ticker,
            "refresh_status": "CERTIFIED_CACHE_FALLBACK",
            "failure_reason": "",
            "exception_type": "",
            "exception_message": "",
        }
    return provider_rows


def exclusion_threshold_for(source_count: int) -> int:
    if source_count <= 0:
        return 0
    return max(1, int(source_count * 0.05))


def build_exclusion_reason(
    row: dict[str, str],
    expected_market_date: str,
    provider: dict[str, str],
    factor: dict[str, str],
    technical: dict[str, str],
) -> tuple[str, str]:
    reasons: list[str] = []
    supporting: list[str] = []
    ticker = clean(row.get("ticker")).upper()
    latest_date = clean(row.get("latest_price_date"))
    latest_close = clean(row.get("latest_close"))
    composite_score = clean(row.get("composite_candidate_score"))
    rank = clean(row.get("rank"))

    provider_failed = clean(provider.get("refresh_status")).upper() == "FAILED" or bool(clean(provider.get("failure_reason")))
    factor_reason = clean(factor.get("exclusion_reason"))
    technical_reason = clean(technical.get("exclusion_reason"))

    if expected_market_date and latest_date != expected_market_date:
        reasons.append("STALE_PRICE_DATE_OR_PROVIDER_REFRESH_FAILED" if provider_failed else "STALE_PRICE_DATE")
        supporting.append(f"latest_price_date={latest_date or 'MISSING'} expected_market_date={expected_market_date}")
    if provider_failed:
        reasons.append("PROVIDER_REFRESH_FAILED")
        supporting.append(f"provider_failure_reason={clean(provider.get('failure_reason')) or 'UNKNOWN'}")
    if not latest_date or not latest_close:
        reasons.append("MISSING_LATEST_PRICE")
    if not composite_score:
        if factor_reason or technical_reason:
            reasons.append("MISSING_COMPOSITE_CANDIDATE_SCORE_INSUFFICIENT_HISTORY")
        else:
            reasons.append("MISSING_COMPOSITE_CANDIDATE_SCORE")
    if not rank:
        reasons.append("MISSING_RANK")
    if factor_reason:
        supporting.append(f"factor_exclusion_reason={factor_reason}")
    if technical_reason:
        supporting.append(f"technical_exclusion_reason={technical_reason}")
    if ticker and clean(factor.get("price_history_row_count")):
        supporting.append(f"factor_price_history_row_count={clean(factor.get('price_history_row_count'))}")
    if ticker and clean(technical.get("price_history_row_count")):
        supporting.append(f"technical_price_history_row_count={clean(technical.get('price_history_row_count'))}")

    deduped_reasons = list(dict.fromkeys(reasons))
    deduped_supporting = list(dict.fromkeys(supporting))
    return ";".join(deduped_reasons), ";".join(deduped_supporting)


def split_eligible_and_excluded(
    staging_rows: list[dict[str, str]],
    expected_market_date: str,
    source_hash: str,
    run_id: str,
    created_at: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    provider_by_ticker = provider_status_by_ticker()
    factor_by_ticker = rows_by_ticker(FACTOR_AUDIT)
    technical_by_ticker = rows_by_ticker(TECHNICAL_AUDIT)
    eligible: list[dict[str, str]] = []
    excluded: list[dict[str, str]] = []

    for row in staging_rows:
        ticker = clean(row.get("ticker")).upper()
        provider = provider_by_ticker.get(ticker, {})
        factor = factor_by_ticker.get(ticker, {})
        technical = technical_by_ticker.get(ticker, {})
        exclusion_reason, supporting_reason = build_exclusion_reason(row, expected_market_date, provider, factor, technical)
        if not exclusion_reason:
            eligible.append(row)
            continue
        excluded.append({
            "ticker": ticker,
            "rank": clean(row.get("rank")),
            "latest_price_date": clean(row.get("latest_price_date")),
            "latest_close": clean(row.get("latest_close")),
            "composite_candidate_score": clean(row.get("composite_candidate_score")),
            "exclusion_reason": exclusion_reason,
            "supporting_reason": supporting_reason,
            "provider_refresh_status": clean(provider.get("refresh_status")),
            "provider_failure_reason": clean(provider.get("failure_reason")),
            "provider_exception_type": clean(provider.get("exception_type")),
            "provider_exception_message": clean(provider.get("exception_message")),
            "factor_exclusion_reason": clean(factor.get("exclusion_reason")),
            "technical_exclusion_reason": clean(technical.get("exclusion_reason")),
            "factor_price_history_row_count": clean(factor.get("price_history_row_count")),
            "technical_price_history_row_count": clean(technical.get("price_history_row_count")),
            "source_path": rel(SOURCE_FULL),
            "source_hash": source_hash,
            "run_id": run_id,
            "created_at_utc": created_at,
            "quarantine_status": "EXCLUDED_FROM_ACTIVE_MARKET_SOURCE_STAGING",
        })
    return eligible, excluded


def build_staging_rows(
    source_rows: list[dict[str, str]],
    source_hash: str,
    run_id: str,
    created_at: str,
    source_artifact_id: str,
    source_version: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    source_path = rel(SOURCE_FULL)
    for source in source_rows:
        ticker = clean(source.get("ticker")).upper()
        latest_date = clean(source.get("latest_price_date"))
        latest_close = clean(source.get("latest_close"))
        price_repair_source = ""
        if ticker and (not latest_date or not latest_close):
            cache = latest_price_cache_row(ticker)
            if cache:
                latest_date = latest_date or parse_date_text(cache.get("date"))
                latest_close = latest_close or clean(cache.get("close") or cache.get("adj_close"))
                price_repair_source = clean(cache.get("_source_file"))
        row = {
            "ticker": ticker,
            "observation_date": latest_date,
            "signal_date": latest_date,
            "price_date": latest_date,
            "latest_price_date": latest_date,
            "latest_close": latest_close,
            "close": latest_close,
            "rank": clean(source.get("rank")),
            "composite_candidate_score": clean(source.get("composite_candidate_score")),
            "factor_score": clean(source.get("factor_score")),
            "technical_score": clean(source.get("technical_score")),
            "source_artifact_id": source_artifact_id,
            "source_path": source_path,
            "source_hash": source_hash,
            "run_id": run_id,
            "active_runtime_flag": "TRUE",
            "historical_reference_flag": "FALSE",
            "availability_date": latest_date,
            "created_at_utc": created_at,
            "source_system": SOURCE_SYSTEM,
            "source_version": source_version,
            "lineage_status": "LINEAGE_BOUND_TO_ACCEPTED_V18_SOURCE_HASH",
            "pit_ready_candidate_flag": "TRUE",
            "stale_check_candidate_flag": "TRUE",
            "leakage_check_candidate_flag": "TRUE",
            "certification_candidate_flag": "TRUE",
            "price_repair_source": price_repair_source,
        }
        row["sample_id"] = deterministic_sample_id(row, source_hash, run_id)
        rows.append(row)
    return rows


def build_field_audit(rows: list[dict[str, str]], source_fields: list[str]) -> list[dict[str, str]]:
    audit_rows: list[dict[str, str]] = []
    source_field_set = set(source_fields)
    for field in STAGING_FIELDS:
        non_empty = sum(1 for row in rows if clean(row.get(field)))
        required = field in CORE_PRECHECK_FIELDS
        source_present = field in source_field_set
        status = "PASS" if (not required or non_empty == len(rows)) else "BLOCKED"
        if field in {"factor_score", "technical_score"} and non_empty == 0:
            status = "WARN_OPTIONAL_SCORE_DETAIL_NOT_PRESENT_IN_ACCEPTED_V18_ALIAS"
        audit_rows.append({
            "field_name": field,
            "required_for_certification_precheck": tf(required),
            "present_in_v18_source": tf(source_present),
            "present_in_staging": "TRUE",
            "non_empty_row_count": str(non_empty),
            "total_row_count": str(len(rows)),
            "field_audit_status": status,
            "notes": "Derived or bound by V20.7V staging layer." if not source_present else "Copied from accepted V18 source.",
        })
    return audit_rows


def missing_core_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    return {
        field: sum(1 for row in rows if not clean(row.get(field)))
        for field in CORE_PRECHECK_FIELDS
    }


def build_precheck(rows: list[dict[str, str]], expected_market_date: str) -> tuple[list[dict[str, str]], list[str]]:
    blockers: list[str] = []
    checks: list[dict[str, str]] = []

    def add(check_id: str, name: str, passed: bool, details: str, blocker: str = "") -> None:
        if not passed and blocker:
            blockers.append(blocker)
        checks.append({
            "check_id": check_id,
            "check_name": name,
            "check_status": "PASS" if passed else "BLOCKED",
            "details": details,
            "blocker_reason": "" if passed else blocker,
        })

    row_count = len(rows)
    date_dist = date_distribution(rows, "latest_price_date")
    sample_ids = [clean(row.get("sample_id")) for row in rows]
    tickers = [clean(row.get("ticker")) for row in rows]
    missing_counts = missing_core_counts(rows)
    missing_summary = ";".join(f"{field}={count}" for field, count in missing_counts.items() if count)
    date_gate_ok = bool(expected_market_date) and date_dist == {expected_market_date: row_count}

    add("PRE-001", "source_row_count_full_universe_scale", row_count >= 300, f"row_count={row_count}", "Staging row count is below full-universe scale.")
    add("PRE-002", "latest_price_date_clean", date_gate_ok, f"expected_market_date={expected_market_date};observed={distribution_text(date_dist)}", f"latest_price_date distribution is not clean {expected_market_date or 'UNKNOWN'}.")
    add("PRE-003", "required_core_fields_non_empty", all(count == 0 for count in missing_counts.values()), f"missing_core_field_counts={missing_summary or 'NONE'}", "One or more core precheck fields are empty.")
    add("PRE-004", "active_runtime_flags", all(clean(row.get("active_runtime_flag")).upper() == "TRUE" for row in rows), "active_runtime_flag TRUE for staged rows", "active_runtime_flag must be TRUE for staged cert candidate rows.")
    add("PRE-005", "historical_reference_flags", all(clean(row.get("historical_reference_flag")).upper() == "FALSE" for row in rows), "historical_reference_flag FALSE for staged rows", "historical_reference_flag must be FALSE for active source candidate rows.")
    add("PRE-006", "sample_id_unique", len(sample_ids) == len(set(sample_ids)) == row_count, f"unique_sample_ids={len(set(sample_ids))}", "sample_id values are missing or duplicated.")
    add("PRE-007", "ticker_unique", len(tickers) == len(set(tickers)) == row_count, f"unique_tickers={len(set(tickers))}", "Ticker values are missing or duplicated.")
    add("PRE-008", "lineage_bound_to_source_hash", all(clean(row.get("source_hash")) for row in rows), "source_hash present for every staged row", "source_hash is missing for staged rows.")
    return checks, blockers


def build_diagnostics(rows: list[dict[str, str]], expected_market_date: str) -> list[dict[str, str]]:
    date_dist = date_distribution(rows, "latest_price_date")
    stale_rows = [
        row for row in rows
        if expected_market_date and clean(row.get("latest_price_date")) != expected_market_date
    ]
    missing_latest_price_rows = [
        row for row in rows
        if not clean(row.get("latest_price_date")) or not clean(row.get("latest_close"))
    ]
    missing_counts = missing_core_counts(rows)
    examples = []
    for row in stale_rows[:10]:
        examples.append(f"{clean(row.get('ticker'))}:{clean(row.get('latest_price_date')) or 'MISSING'}")
    missing_examples = []
    for row in missing_latest_price_rows[:10]:
        missing_examples.append(f"{clean(row.get('ticker'))}:date={clean(row.get('latest_price_date')) or 'MISSING'},close={clean(row.get('latest_close')) or 'MISSING'}")
    field_rows = []
    for field, count in missing_counts.items():
        sample = [
            clean(row.get("ticker"))
            for row in rows
            if not clean(row.get(field))
        ][:10]
        field_rows.append({
            "diagnostic_type": "missing_core_field",
            "field_name": field,
            "missing_count": str(count),
            "sample_tickers": ",".join(sample),
            "expected_market_date": expected_market_date,
            "observed_latest_price_date_distribution": distribution_text(date_dist),
            "stale_ticker_count": str(len(stale_rows)),
            "missing_latest_price_count": str(len(missing_latest_price_rows)),
            "stale_examples": ",".join(examples),
            "missing_latest_price_examples": ",".join(missing_examples),
        })
    return field_rows


def md_table(fields: list[str], rows: list[dict[str, str]], limit: int = 20) -> str:
    lines = ["| " + " | ".join(fields) + " |", "| " + " | ".join(["---"] * len(fields)) + " |"]
    for row in rows[:limit]:
        lines.append("| " + " | ".join(clean(row.get(field)).replace("|", "/") for field in fields) + " |")
    if len(rows) > limit:
        lines.append(f"| ... | {len(rows) - limit} more rows omitted |" + " |" * max(0, len(fields) - 2))
    return "\n".join(lines)


def main() -> int:
    created_at = now_utc()
    source_rows, source_fields = read_csv(SOURCE_FULL)
    ranked_rows, _ = read_csv(SOURCE_RANKED)
    top_rows, _ = read_csv(SOURCE_TOP)

    source_exists = SOURCE_FULL.exists()
    source_hash = sha256_file(SOURCE_FULL) if source_exists else ""
    expected_market_date = expected_market_date_from(source_rows)
    market_date_token = expected_market_date.replace("-", "") if expected_market_date else "UNKNOWN_DATE"
    source_version = f"{SOURCE_VERSION_PREFIX}_{market_date_token}"
    source_artifact_id = f"{SOURCE_ARTIFACT_PREFIX}_{market_date_token}"
    run_id = f"V20_7V_CURRENT_V18_{market_date_token}_{source_hash[:12].upper()}" if source_hash else "V20_7V_CURRENT_V18_SOURCE_MISSING"

    source_staging_rows = build_staging_rows(source_rows, source_hash, run_id, created_at, source_artifact_id, source_version) if source_exists else []
    staging_rows, excluded_rows = split_eligible_and_excluded(source_staging_rows, expected_market_date, source_hash, run_id, created_at)
    field_audit_rows = build_field_audit(staging_rows, source_fields)
    precheck_rows, precheck_blockers = build_precheck(staging_rows, expected_market_date)
    diagnostic_rows = build_diagnostics(staging_rows, expected_market_date)

    full_dist = date_distribution(source_rows, "latest_price_date")
    ranked_dist = date_distribution(ranked_rows, "latest_price_date")
    top_dist = date_distribution(top_rows, "latest_price_date")
    staging_dist = date_distribution(staging_rows, "latest_price_date")
    full_source_staging_dist = date_distribution(source_staging_rows, "latest_price_date")
    source_read_first_exists = SOURCE_READ_FIRST.exists()
    stale_ticker_count = sum(1 for row in staging_rows if expected_market_date and clean(row.get("latest_price_date")) != expected_market_date)
    missing_latest_price_count = sum(1 for row in staging_rows if not clean(row.get("latest_price_date")) or not clean(row.get("latest_close")))
    missing_core_summary = ";".join(
        f"{field}={count}" for field, count in missing_core_counts(staging_rows).items() if count
    ) or "NONE"
    excluded_count = len(excluded_rows)
    excluded_threshold = exclusion_threshold_for(len(source_rows))
    excluded_with_reasons = all(clean(row.get("exclusion_reason")) for row in excluded_rows)
    eligible_row_count = len(staging_rows)
    partial_staging_allowed = excluded_count <= excluded_threshold and excluded_with_reasons
    if excluded_count > excluded_threshold:
        precheck_blockers.append(f"Excluded row count {excluded_count} exceeds threshold {excluded_threshold}.")
    if excluded_count and not excluded_with_reasons:
        precheck_blockers.append("One or more excluded rows are missing exclusion_reason.")
    precheck_rows.extend([
        {
            "check_id": "PRE-009",
            "check_name": "excluded_rows_within_threshold",
            "check_status": "PASS" if excluded_count <= excluded_threshold else "BLOCKED",
            "details": f"excluded_row_count={excluded_count};exclusion_threshold={excluded_threshold}",
            "blocker_reason": "" if excluded_count <= excluded_threshold else f"Excluded row count {excluded_count} exceeds threshold {excluded_threshold}.",
        },
        {
            "check_id": "PRE-010",
            "check_name": "excluded_rows_have_reasons",
            "check_status": "PASS" if excluded_with_reasons else "BLOCKED",
            "details": f"excluded_row_count={excluded_count}",
            "blocker_reason": "" if excluded_with_reasons else "One or more excluded rows are missing exclusion_reason.",
        },
    ])
    for excluded in excluded_rows:
        diagnostic_rows.append({
            "diagnostic_type": "excluded_ticker",
            "field_name": clean(excluded.get("exclusion_reason")),
            "missing_count": "",
            "sample_tickers": clean(excluded.get("ticker")),
            "expected_market_date": expected_market_date,
            "observed_latest_price_date_distribution": distribution_text(staging_dist),
            "stale_ticker_count": str(stale_ticker_count),
            "missing_latest_price_count": str(missing_latest_price_count),
            "stale_examples": "",
            "missing_latest_price_examples": clean(excluded.get("supporting_reason")),
        })

    lineage_status = "PASS" if source_exists and len(source_rows) == (len(staging_rows) + len(excluded_rows)) and source_hash else "BLOCKED"
    active_source_staging_ready = lineage_status == "PASS" and not precheck_blockers and partial_staging_allowed
    certification_retry_allowed = active_source_staging_ready
    v20_8_blocked = True

    lineage_rows = [{
        "source_artifact_id": source_artifact_id,
        "source_system": SOURCE_SYSTEM,
        "source_version": source_version,
        "source_path": rel(SOURCE_FULL),
        "source_exists": tf(source_exists),
        "source_hash": source_hash,
        "hash_algorithm": "SHA256",
        "hash_computed_read_only": tf(bool(source_hash)),
        "run_id": run_id,
        "source_row_count": str(len(source_rows)),
        "staging_row_count": str(len(staging_rows)),
        "eligible_row_count": str(eligible_row_count),
        "excluded_row_count": str(excluded_count),
        "exclusion_threshold": str(excluded_threshold),
        "excluded_tickers_path": rel(OUT_EXCLUDED),
        "expected_market_date": expected_market_date,
        "source_latest_price_date_distribution": distribution_text(full_dist),
        "source_staging_latest_price_date_distribution_before_exclusion": distribution_text(full_source_staging_dist),
        "crosscheck_ranked_row_count": str(len(ranked_rows)),
        "crosscheck_ranked_latest_price_date_distribution": distribution_text(ranked_dist),
        "crosscheck_top_row_count": str(len(top_rows)),
        "crosscheck_top_latest_price_date_distribution": distribution_text(top_dist),
        "v18_35d_read_first_exists": tf(source_read_first_exists),
        "lineage_status": lineage_status,
    }]

    source_audit_rows = [{
        "source_path": rel(SOURCE_FULL),
        "source_role": "V20_7V_PRIMARY_CURRENT_FULL_RANKED_SOURCE",
        "source_exists": tf(source_exists),
        "source_hash": source_hash,
        "source_row_count": str(len(source_rows)),
        "source_field_count": str(len(source_fields)),
        "expected_market_date": expected_market_date,
        "observed_latest_price_date_distribution": distribution_text(full_dist),
        "full_source_staging_latest_price_date_distribution_before_exclusion": distribution_text(full_source_staging_dist),
        "staging_row_count": str(len(staging_rows)),
        "eligible_row_count": str(eligible_row_count),
        "excluded_row_count": str(excluded_count),
        "excluded_ticker_count": str(excluded_count),
        "exclusion_threshold": str(excluded_threshold),
        "excluded_tickers_path": rel(OUT_EXCLUDED),
        "excluded_ticker_examples": ",".join(clean(row.get("ticker")) for row in excluded_rows[:10]),
        "v20_7v_used_quarantine": tf(bool(excluded_rows)),
        "staging_latest_price_date_distribution": distribution_text(staging_dist),
        "stale_ticker_count": str(stale_ticker_count),
        "missing_latest_price_count": str(missing_latest_price_count),
        "missing_core_field_summary": missing_core_summary,
        "no_dummy_price": "TRUE",
        "no_dummy_score": "TRUE",
        "source_audit_status": "PASS" if active_source_staging_ready else "BLOCKED_OR_REVIEW_NEEDED",
    }]

    sample_rows = [{
        "sample_id": row["sample_id"],
        "ticker": row["ticker"],
        "rank": row["rank"],
        "observation_date": row["observation_date"],
        "source_artifact_id": row["source_artifact_id"],
        "source_hash": row["source_hash"],
        "run_id": row["run_id"],
        "sample_id_method": "sha256(ticker|latest_price_date|rank|source_artifact_id|source_hash|run_id)[0:24]",
        "sample_id_status": "PASS",
    } for row in staging_rows]

    blocker_rows: list[dict[str, str]] = []
    for i, blocker in enumerate(precheck_blockers, 1):
        blocker_rows.append({
            "blocker_id": f"V20_7V_BLOCKER_{i:03d}",
            "blocker_scope": "ACTIVE_MARKET_SOURCE_STAGING",
            "blocker_status": "OPEN",
            "blocker_reason": blocker,
            "blocks_v20_7s_retry": "TRUE",
            "blocks_v20_8": "TRUE",
        })
    blocker_rows.append({
        "blocker_id": "V20_7V_BLOCKER_V20_8_001",
        "blocker_scope": "V20_8_ENTRY",
        "blocker_status": "OPEN",
        "blocker_reason": "V20.8 remains blocked until V20.7S/7U certification is explicitly retried and passes.",
        "blocks_v20_7s_retry": "FALSE",
        "blocks_v20_8": "TRUE",
    })

    next_rows = [{
        "decision_id": "V20_7V_NEXT_STEP",
        "active_source_staging_candidate_ready": tf(active_source_staging_ready),
        "v20_7s_certification_retry_allowed_next": tf(certification_retry_allowed),
        "v20_7u_lineage_binding_retry_allowed_next": tf(certification_retry_allowed),
        "v20_8_entry_allowed": "FALSE",
        "v20_8_blocked_reason": "V20.7S/7U certification has not been explicitly retried and passed for this staged source.",
        "next_recommended_action": "RUN_V20_7S_7U_CERTIFICATION_RETRY" if certification_retry_allowed else "RESOLVE_V20_7V_PRECHECK_BLOCKERS",
    }]

    validation_rows = [{
        "status": "PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY" if active_source_staging_ready else "BLOCKED_V20_7V_PRECHECK_REVIEW_NEEDED",
        "patch_version": PATCH_VERSION,
        "source_path": rel(SOURCE_FULL),
        "source_hash": source_hash,
        "run_id": run_id,
        "expected_market_date": expected_market_date,
        "source_row_count": str(len(source_rows)),
        "staging_row_count": str(len(staging_rows)),
        "eligible_row_count": str(eligible_row_count),
        "excluded_row_count": str(excluded_count),
        "excluded_ticker_count": str(excluded_count),
        "exclusion_threshold": str(excluded_threshold),
        "excluded_tickers_path": rel(OUT_EXCLUDED),
        "excluded_ticker_examples": ",".join(clean(row.get("ticker")) for row in excluded_rows[:10]),
        "v20_7v_used_quarantine": tf(bool(excluded_rows)),
        "staging_latest_price_date_distribution": distribution_text(staging_dist),
        "source_staging_latest_price_date_distribution_before_exclusion": distribution_text(full_source_staging_dist),
        "stale_ticker_count": str(stale_ticker_count),
        "missing_latest_price_count": str(missing_latest_price_count),
        "missing_core_field_summary": missing_core_summary,
        "field_audit_row_count": str(len(field_audit_rows)),
        "lineage_audit_row_count": str(len(lineage_rows)),
        "source_audit_row_count": str(len(source_audit_rows)),
        "precheck_diagnostic_row_count": str(len(diagnostic_rows)),
        "sample_id_audit_row_count": str(len(sample_rows)),
        "precheck_row_count": str(len(precheck_rows)),
        "blocker_count": str(len([row for row in blocker_rows if row["blocks_v20_7s_retry"] == "TRUE"])),
        "active_source_staging_candidate_ready": tf(active_source_staging_ready),
        "active_market_source_staging_usable": tf(active_source_staging_ready),
        "v20_7s_certification_retry_allowed_next": tf(certification_retry_allowed),
        "v20_8_entry_allowed": "FALSE",
        "no_dummy_price": "TRUE",
        "no_dummy_score": "TRUE",
        **SAFETY_FLAGS,
    }]

    write_csv(OUT_STAGING, staging_rows, STAGING_FIELDS)
    write_csv(OUT_EXCLUDED, excluded_rows, EXCLUDED_FIELDS)
    write_csv(OUT_FIELD_AUDIT, field_audit_rows, ["field_name", "required_for_certification_precheck", "present_in_v18_source", "present_in_staging", "non_empty_row_count", "total_row_count", "field_audit_status", "notes"])
    write_csv(OUT_LINEAGE_AUDIT, lineage_rows, list(lineage_rows[0].keys()))
    write_csv(OUT_SOURCE_AUDIT, source_audit_rows, list(source_audit_rows[0].keys()))
    write_csv(OUT_SAMPLE_AUDIT, sample_rows, ["sample_id", "ticker", "rank", "observation_date", "source_artifact_id", "source_hash", "run_id", "sample_id_method", "sample_id_status"])
    write_csv(OUT_PRECHECK, precheck_rows, ["check_id", "check_name", "check_status", "details", "blocker_reason"])
    write_csv(OUT_DIAGNOSTICS, diagnostic_rows, list(diagnostic_rows[0].keys()))
    write_csv(OUT_BLOCKERS, blocker_rows, ["blocker_id", "blocker_scope", "blocker_status", "blocker_reason", "blocks_v20_7s_retry", "blocks_v20_8"])
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))
    write_csv(OUT_VALIDATION, validation_rows, list(validation_rows[0].keys()))

    report = "\n".join([
        "# V20.7V Active Market Source Staging From Accepted V18 Result",
        "",
        f"- STATUS: `{validation_rows[0]['status']}`",
        f"- source: `{rel(SOURCE_FULL)}`",
        f"- source hash: `{source_hash}`",
        f"- run_id: `{run_id}`",
        f"- staging rows: `{len(staging_rows)}`",
        f"- eligible row count: `{eligible_row_count}`",
        f"- excluded row count: `{excluded_count}`",
        f"- exclusion threshold: `{excluded_threshold}`",
        f"- excluded tickers: `{','.join(clean(row.get('ticker')) for row in excluded_rows[:20]) or 'NONE'}`",
        f"- excluded tickers path: `{rel(OUT_EXCLUDED)}`",
        f"- V20.7V used quarantine: `{tf(bool(excluded_rows))}`",
        f"- expected_market_date: `{expected_market_date}`",
        f"- latest_price_date distribution: `{distribution_text(staging_dist)}`",
        f"- stale ticker count: `{stale_ticker_count}`",
        f"- missing latest price count: `{missing_latest_price_count}`",
        f"- missing core field summary: `{missing_core_summary}`",
        f"- active source staging candidate ready: `{tf(active_source_staging_ready)}`",
        f"- V20.7S/7U retry allowed next: `{tf(certification_retry_allowed)}`",
        "- V20.8 entry allowed: `FALSE`",
        "",
        "## Safety Flags",
        md_table(["flag", "value"], [{"flag": key, "value": value} for key, value in SAFETY_FLAGS.items()], limit=20),
        "",
        "## Certification Precheck",
        md_table(["check_id", "check_name", "check_status", "details", "blocker_reason"], precheck_rows, limit=20),
        "",
        "## Excluded / Quarantined Tickers",
        md_table(["ticker", "exclusion_reason", "supporting_reason", "provider_failure_reason", "factor_exclusion_reason", "technical_exclusion_reason"], excluded_rows, limit=30),
        "",
        "## Diagnostics",
        md_table(["diagnostic_type", "field_name", "missing_count", "sample_tickers", "stale_ticker_count", "missing_latest_price_count", "stale_examples"], diagnostic_rows, limit=30),
        "",
        "## Lineage",
        md_table(["source_artifact_id", "source_path", "source_hash", "source_row_count", "staging_row_count", "lineage_status"], lineage_rows, limit=5),
        "",
        "This layer stages the accepted V18 full-universe result only. It does not create normalized data, factor evidence, backtest rows, dynamic weighting rows, trading signals, recommendations, broker calls, or orders.",
        "",
    ])
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)

    read_first_lines = [
        f"STATUS: {validation_rows[0]['status']}",
        f"PATCH_VERSION: {PATCH_VERSION}",
        f"SOURCE_SYSTEM: {SOURCE_SYSTEM}",
        f"SOURCE_VERSION: {source_version}",
        f"SOURCE_PATH: {rel(SOURCE_FULL)}",
        f"SOURCE_HASH: {source_hash}",
        f"RUN_ID: {run_id}",
        f"EXPECTED_MARKET_DATE: {expected_market_date}",
        f"STAGING_ROW_COUNT: {len(staging_rows)}",
        f"ELIGIBLE_ROW_COUNT: {eligible_row_count}",
        f"EXCLUDED_ROW_COUNT: {excluded_count}",
        f"EXCLUDED_TICKER_COUNT: {excluded_count}",
        f"EXCLUSION_THRESHOLD: {excluded_threshold}",
        f"EXCLUDED_TICKER_EXAMPLES: {','.join(clean(row.get('ticker')) for row in excluded_rows[:10])}",
        f"V20_7V_USED_QUARANTINE: {tf(bool(excluded_rows))}",
        f"STAGING_LATEST_PRICE_DATE_DISTRIBUTION: {distribution_text(staging_dist)}",
        f"SOURCE_STAGING_LATEST_PRICE_DATE_DISTRIBUTION_BEFORE_EXCLUSION: {distribution_text(full_source_staging_dist)}",
        f"STALE_TICKER_COUNT: {stale_ticker_count}",
        f"MISSING_LATEST_PRICE_COUNT: {missing_latest_price_count}",
        f"MISSING_CORE_FIELD_SUMMARY: {missing_core_summary}",
        f"ACTIVE_SOURCE_STAGING_CANDIDATE_READY: {tf(active_source_staging_ready)}",
        f"V20_7S_CERTIFICATION_RETRY_ALLOWED_NEXT: {tf(certification_retry_allowed)}",
        "V20_8_ENTRY_ALLOWED: FALSE",
        "V20_8_REMAINS_BLOCKED: TRUE",
    ]
    read_first_lines.extend(f"{key}: {value}" for key, value in SAFETY_FLAGS.items())
    read_first_lines.extend([
        f"STAGING_CSV: {rel(OUT_STAGING)}",
        f"EXCLUDED_TICKERS_CSV: {rel(OUT_EXCLUDED)}",
        f"FIELD_AUDIT_CSV: {rel(OUT_FIELD_AUDIT)}",
        f"LINEAGE_AUDIT_CSV: {rel(OUT_LINEAGE_AUDIT)}",
        f"SOURCE_AUDIT_CSV: {rel(OUT_SOURCE_AUDIT)}",
        f"SAMPLE_ID_AUDIT_CSV: {rel(OUT_SAMPLE_AUDIT)}",
        f"CERTIFICATION_PRECHECK_CSV: {rel(OUT_PRECHECK)}",
        f"PRECHECK_DIAGNOSTICS_CSV: {rel(OUT_DIAGNOSTICS)}",
        f"BLOCKER_REGISTER_CSV: {rel(OUT_BLOCKERS)}",
        f"NEXT_STEP_DECISION_CSV: {rel(OUT_NEXT)}",
        f"VALIDATION_SUMMARY_CSV: {rel(OUT_VALIDATION)}",
        f"REPORT: {rel(REPORT)}",
        f"CURRENT_REPORT: {rel(CURRENT_REPORT)}",
        "",
    ])
    write_text(READ_FIRST, "\n".join(read_first_lines))

    for key, value in validation_rows[0].items():
        print(f"{key.upper()}: {value}")
    print(f"READ_FIRST: {READ_FIRST}")
    return 0 if active_source_staging_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
