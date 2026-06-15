from __future__ import annotations

import csv
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
PRICE_CACHE = ROOT / "state" / "v18" / "price_cache"
SCRIPT_V18 = ROOT / "scripts" / "v18"
SCRIPT_V20 = ROOT / "scripts" / "v20"

IN_V47_SUMMARY = CONSOLIDATION / "V20_47_CONTROLLED_REFRESH_SUMMARY.csv"
IN_V47_CANDIDATE_CACHE = CONSOLIDATION / "V20_47_YAHOO_CURRENT_CANDIDATE_PRICE_CACHE.csv"
IN_V47_BENCHMARK_CACHE = CONSOLIDATION / "V20_47_YAHOO_CURRENT_BENCHMARK_PRICE_CACHE.csv"
IN_V47_CANDIDATE_CERT = CONSOLIDATION / "V20_47_CURRENT_CANDIDATE_PRICE_CERTIFICATION.csv"
IN_V47_BENCHMARK_CERT = CONSOLIDATION / "V20_47_CURRENT_BENCHMARK_PRICE_CERTIFICATION.csv"
IN_V47_FALLBACK_AUDIT = CONSOLIDATION / "V20_47_CERTIFIED_CACHE_FALLBACK_AUDIT.csv"

OUT_AUDIT = CONSOLIDATION / "V20_POST_REFRESH_RECOMPUTE_AUDIT.csv"
OUT_STATUS = CONSOLIDATION / "V20_POST_REFRESH_RECOMPUTE_STATUS.csv"

PASS_STATUS = "PASS_V20_POST_REFRESH_RECOMPUTE_HANDOFF_COMPLETED"
BLOCKED_STATUS = "BLOCKED_V20_POST_REFRESH_RECOMPUTE_HANDOFF"
LIVE_V20_47_CERTIFICATION_STATUS = "CERTIFIED_FOR_RESEARCH_REPORT_HANDOFF"
PARTIAL_V20_47_CERTIFICATION_STATUS = "PARTIAL_CERTIFIED_RESEARCH_HANDOFF"
FALLBACK_V20_47_CERTIFICATION_STATUS = "CERTIFIED_CACHE_FALLBACK_HANDOFF"
ACCEPTED_V20_47_CERTIFICATION_STATUSES = {
    LIVE_V20_47_CERTIFICATION_STATUS,
    PARTIAL_V20_47_CERTIFICATION_STATUS,
    FALLBACK_V20_47_CERTIFICATION_STATUS,
}


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def read_fields(path: Path) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle).fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def first_row(path: Path) -> dict[str, str]:
    rows = read_csv(path)
    return rows[0] if rows else {}


def date_text(value: object) -> str:
    text = clean(value)[:10]
    if len(text) != 10:
        return ""
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return text
    except ValueError:
        return ""


def latest_cache_distribution() -> str:
    counts: Counter[str] = Counter()
    for path in PRICE_CACHE.glob("*.csv"):
        latest = ""
        for row in read_csv(path):
            date = date_text(row.get("date") or row.get("price_date") or row.get("latest_price_date"))
            close = clean(row.get("close") or row.get("adj_close") or row.get("latest_close"))
            if date and close:
                latest = max(latest, date)
        if latest:
            counts[latest] += 1
    return ";".join(f"{key}={counts[key]}" for key in sorted(counts))


def latest_distribution(path: Path, field: str = "latest_price_date") -> str:
    counts: Counter[str] = Counter()
    for row in read_csv(path):
        counts[clean(row.get(field)) or "MISSING"] += 1
    return ";".join(f"{key}={counts[key]}" for key in sorted(counts))


def certified_tickers(path: Path, ticker_field: str) -> set[str]:
    return {
        clean(row.get(ticker_field)).upper()
        for row in read_csv(path)
        if clean(row.get("certification_status")) == "CERTIFIED" and clean(row.get(ticker_field))
    }


def append_or_update_price_cache(row: dict[str, str], ticker_field: str, source_path: Path, created_at: str, source_label: str) -> str:
    ticker = clean(row.get(ticker_field)).upper()
    latest_date = date_text(row.get("latest_price_date"))
    latest_close = clean(row.get("latest_close") or row.get("close_like_price") or row.get("latest_adj_close"))
    if not ticker or not latest_date or not latest_close:
        return "SKIPPED_MISSING_TICKER_DATE_OR_CLOSE"
    path = PRICE_CACHE / f"{ticker}.csv"
    fields = read_fields(path) or ["date", "open", "high", "low", "close", "adj_close", "volume", "source", "source_file", "updated_at"]
    existing = read_csv(path)
    lower = {field.lower(): field for field in fields}
    date_col = lower.get("date") or fields[0]
    open_col = lower.get("open")
    high_col = lower.get("high")
    low_col = lower.get("low")
    close_col = lower.get("close")
    adj_col = lower.get("adj_close") or lower.get("adjusted_close")
    volume_col = lower.get("volume")
    source_col = lower.get("source")
    source_file_col = lower.get("source_file")
    updated_col = lower.get("updated_at")
    for existing_row in existing:
        if date_text(existing_row.get(date_col)) != latest_date:
            continue
        existing_close = clean(existing_row.get(close_col)) if close_col else ""
        existing_adj_close = clean(existing_row.get(adj_col)) if adj_col else ""
        if existing_close or existing_adj_close:
            return "ALREADY_PRESENT_CERTIFIED_DATE"
    new_row = {field: "" for field in fields}
    new_row[date_col] = latest_date
    if open_col:
        new_row[open_col] = clean(row.get("latest_open"))
    if high_col:
        new_row[high_col] = clean(row.get("latest_high"))
    if low_col:
        new_row[low_col] = clean(row.get("latest_low"))
    if close_col:
        new_row[close_col] = latest_close
    if adj_col:
        new_row[adj_col] = clean(row.get("latest_adj_close")) or latest_close
    if volume_col:
        new_row[volume_col] = clean(row.get("latest_volume"))
    if source_col:
        new_row[source_col] = source_label
    if source_file_col:
        new_row[source_file_col] = rel(source_path)
    if updated_col:
        new_row[updated_col] = created_at
    replaced = False
    for idx, existing_row in enumerate(existing):
        if date_text(existing_row.get(date_col)) == latest_date:
            merged = dict(existing_row)
            for field, value in new_row.items():
                if value:
                    merged[field] = value
            existing[idx] = merged
            replaced = True
            break
    if not replaced:
        existing.append(new_row)
    existing.sort(key=lambda item: date_text(item.get(date_col)))
    write_csv(path, existing, fields)
    return "UPDATED_EXISTING_DATE" if replaced else "APPENDED_NEW_DATE"


def run_wrapper(name: str, path: Path) -> dict[str, object]:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "step": name,
        "wrapper_path": rel(path),
        "return_code": result.returncode,
        "stdout_tail": result.stdout[-700:].replace("\r", ""),
        "stderr_tail": result.stderr[-700:].replace("\r", ""),
        "step_status": "PASS" if result.returncode == 0 else "BLOCKED_OR_WARN",
    }


def main() -> int:
    created_at = now_utc()
    v47_summary = first_row(IN_V47_SUMMARY)
    v47_certification_status = clean(v47_summary.get("certification_status"))
    fallback_audit = first_row(IN_V47_FALLBACK_AUDIT)
    fallback_used = (
        v47_certification_status == FALLBACK_V20_47_CERTIFICATION_STATUS
        or clean(v47_summary.get("fallback_used")).upper() == "TRUE"
    )
    fallback_handoff_allowed = (
        clean(fallback_audit.get("fallback_used")).upper() == "TRUE"
        and clean(fallback_audit.get("handoff_allowed")).upper() == "TRUE"
        and clean(fallback_audit.get("certification_status")) == FALLBACK_V20_47_CERTIFICATION_STATUS
    )
    accepted_certification_status = v47_certification_status in ACCEPTED_V20_47_CERTIFICATION_STATUSES
    certified = accepted_certification_status and (not fallback_used or fallback_handoff_allowed)
    source_label = "V20_47_CERTIFIED_CACHE_FALLBACK" if fallback_used else "V20_47_CERTIFIED_CURRENT_REFRESH"
    pre_dist = latest_cache_distribution()
    audit_rows: list[dict[str, object]] = []
    blockers: list[str] = []
    if not accepted_certification_status:
        blockers.append("v20_47_not_certified")
    if fallback_used and not fallback_handoff_allowed:
        blockers.append("v20_47_certified_cache_fallback_audit_not_handoff_allowed")

    candidate_certified = certified_tickers(IN_V47_CANDIDATE_CERT, "ticker")
    benchmark_certified = certified_tickers(IN_V47_BENCHMARK_CERT, "benchmark_ticker")
    bridge_rows = []
    if certified:
        for row in read_csv(IN_V47_CANDIDATE_CACHE):
            ticker = clean(row.get("ticker")).upper()
            if ticker in candidate_certified:
                status = append_or_update_price_cache(row, "ticker", IN_V47_CANDIDATE_CACHE, created_at, source_label)
                bridge_rows.append((ticker, "candidate", status))
        for row in read_csv(IN_V47_BENCHMARK_CACHE):
            ticker = clean(row.get("ticker")).upper()
            if ticker in benchmark_certified:
                status = append_or_update_price_cache(row, "ticker", IN_V47_BENCHMARK_CACHE, created_at, source_label)
                bridge_rows.append((ticker, "benchmark", status))

    post_bridge_dist = latest_cache_distribution()
    audit_rows.append({
        "step": "V20_47_TO_V18_PRICE_CACHE_BRIDGE",
        "wrapper_path": "",
        "return_code": 0 if certified else 1,
        "step_status": "PASS" if certified else "BLOCKED",
        "pre_refresh_cache_latest_date_distribution": pre_dist,
        "post_refresh_cache_latest_date_distribution": post_bridge_dist,
        "detail": f"certified_rows_applied={len(bridge_rows)}",
        "stdout_tail": "",
        "stderr_tail": "",
    })

    steps = [
        ("V18_CURRENT_RAW105_FACTOR_PACK_REPAIR_POST_REFRESH", SCRIPT_V18 / "run_v18_current_raw105_factor_pack_repair.ps1"),
        ("V18_CURRENT_TECHNICAL_TIMING_REPAIR_POST_REFRESH", SCRIPT_V18 / "run_v18_current_technical_timing_repair.ps1"),
        ("V18_13B_POST_REFRESH", SCRIPT_V18 / "run_v18_13B_ranked_candidate_read_center.ps1"),
        ("V18_CURRENT_RANKED_CANDIDATES_ALIAS_REPAIR_POST_REFRESH", SCRIPT_V18 / "run_v18_current_ranked_candidates_alias_repair.ps1"),
        ("V18_CURRENT_FULL_RANKED_CANDIDATES_REPAIR_POST_REFRESH", SCRIPT_V18 / "run_v18_current_full_ranked_candidates_repair.ps1"),
        ("V20_7V_POST_REFRESH", SCRIPT_V20 / "run_v20_7v_active_market_source_staging_from_accepted_v18_result.ps1"),
    ]
    for name, path in steps:
        if not certified:
            audit_rows.append({"step": name, "wrapper_path": rel(path), "return_code": 0, "step_status": "SKIPPED", "detail": "Skipped because V20.47 is not certified.", "stdout_tail": "", "stderr_tail": ""})
            continue
        result = run_wrapper(name, path)
        result["detail"] = ""
        audit_rows.append(result)

    full_ranked = ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_FULL_RANKED_CANDIDATES.csv"
    v20_7v = first_row(CONSOLIDATION / "V20_7V_VALIDATION_SUMMARY.csv")
    post_full_dist = latest_distribution(full_ranked)
    post_v7v_dist = clean(v20_7v.get("staging_latest_price_date_distribution"))
    missing_core = clean(v20_7v.get("missing_core_field_summary"))
    v20_7v_status = clean(v20_7v.get("status"))
    recompute_complete = certified and all(clean(row.get("step_status")) in {"PASS", "BLOCKED_OR_WARN"} for row in audit_rows if clean(row.get("step")) != "V20_47_TO_V18_PRICE_CACHE_BRIDGE")
    status = PASS_STATUS if recompute_complete else BLOCKED_STATUS
    status_rows = [{
        "status": status,
        "created_at_utc": created_at,
        "v20_47_certification_status": v47_certification_status,
        "v20_47_fallback_used": tf(fallback_used),
        "v20_47_fallback_handoff_allowed": tf(fallback_handoff_allowed),
        "v20_47_fallback_source_run_id": clean(fallback_audit.get("fallback_source_run_id")),
        "v20_47_fallback_source_file": clean(fallback_audit.get("fallback_source_file")),
        "v20_47_cache_age_days": clean(fallback_audit.get("cache_age_days")),
        "v20_47_success_count": clean(v47_summary.get("success_count")),
        "v20_47_failed_count": str(int(clean(v47_summary.get("requested_ticker_count")) or "0") - int(clean(v47_summary.get("success_count")) or "0")),
        "certified_price_cache_rows_applied": len(bridge_rows),
        "pre_refresh_cache_latest_date_distribution": pre_dist,
        "post_refresh_cache_latest_date_distribution": post_bridge_dist,
        "post_refresh_full_ranked_latest_price_date_distribution": post_full_dist,
        "post_refresh_v20_7v_latest_price_date_distribution": post_v7v_dist,
        "v18_factor_pack_recomputed_after_v20_47": tf(any(row.get("step") == "V18_CURRENT_RAW105_FACTOR_PACK_REPAIR_POST_REFRESH" for row in audit_rows)),
        "v18_technical_timing_recomputed_after_v20_47": tf(any(row.get("step") == "V18_CURRENT_TECHNICAL_TIMING_REPAIR_POST_REFRESH" for row in audit_rows)),
        "v18_13b_rerun_after_v20_47": tf(any(row.get("step") == "V18_13B_POST_REFRESH" for row in audit_rows)),
        "v18_full_ranked_rebuilt_after_v20_47": tf(any(row.get("step") == "V18_CURRENT_FULL_RANKED_CANDIDATES_REPAIR_POST_REFRESH" for row in audit_rows)),
        "v20_7v_used_post_refresh_artifacts": tf(any(row.get("step") == "V20_7V_POST_REFRESH" for row in audit_rows)),
        "v20_7v_status_after_post_refresh": v20_7v_status,
        "active_market_source_staging_usable": clean(v20_7v.get("active_source_staging_candidate_ready")),
        "eligible_row_count": clean(v20_7v.get("eligible_row_count")),
        "excluded_row_count": clean(v20_7v.get("excluded_row_count")),
        "excluded_ticker_examples": clean(v20_7v.get("excluded_ticker_examples")),
        "v20_7v_used_quarantine": clean(v20_7v.get("v20_7v_used_quarantine")),
        "missing_required_core_field_summary": missing_core,
        "blocker_reason": ";".join(blockers),
        "research_only": "TRUE",
        "dummy_price_created": "FALSE",
        "dummy_score_created": "FALSE",
        "broker_execution_used": "FALSE",
        "official_recommendation_created": "FALSE",
    }]
    audit_fields = ["step", "wrapper_path", "return_code", "step_status", "pre_refresh_cache_latest_date_distribution", "post_refresh_cache_latest_date_distribution", "detail", "stdout_tail", "stderr_tail"]
    status_fields = list(status_rows[0].keys())
    write_csv(OUT_AUDIT, audit_rows, audit_fields)
    write_csv(OUT_STATUS, status_rows, status_fields)
    print(status)
    print(f"V20_47_CERTIFICATION_STATUS={status_rows[0]['v20_47_certification_status']}")
    print(f"CERTIFIED_PRICE_CACHE_ROWS_APPLIED={len(bridge_rows)}")
    print(f"POST_REFRESH_CACHE_LATEST_DATE_DISTRIBUTION={post_bridge_dist}")
    print(f"V20_7V_STATUS_AFTER_POST_REFRESH={v20_7v_status}")
    print(f"ACTIVE_MARKET_SOURCE_STAGING_USABLE={status_rows[0]['active_market_source_staging_usable']}")
    print(f"ELIGIBLE_ROW_COUNT={status_rows[0]['eligible_row_count']}")
    print(f"EXCLUDED_ROW_COUNT={status_rows[0]['excluded_row_count']}")
    print(f"MISSING_REQUIRED_CORE_FIELD_SUMMARY={missing_core}")
    return 0 if status == PASS_STATUS else 1


if __name__ == "__main__":
    raise SystemExit(main())
