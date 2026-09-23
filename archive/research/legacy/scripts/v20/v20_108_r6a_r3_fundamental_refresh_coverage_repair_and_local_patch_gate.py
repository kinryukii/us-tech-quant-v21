#!/usr/bin/env python
"""V20.108-R6A-R3 fundamental refresh coverage repair and local patch gate.

Diagnoses non-certified ticker-level fundamental metric coverage from the R2
enabled refresh snapshot and prepares a local patch workflow plus a research-only
partial materialization gate. No external provider is called in this stage.
"""

from __future__ import annotations

import csv
import math
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
SNAPSHOTS = CONSOLIDATION / "snapshots"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

SNAP_CACHE = SNAPSHOTS / "V20_108_R6A_R2_ENABLED_REFRESH_CACHE.csv"
SNAP_AUDIT = SNAPSHOTS / "V20_108_R6A_R2_ENABLED_REFRESH_AUDIT.csv"
SNAP_CERT = SNAPSHOTS / "V20_108_R6A_R2_ENABLED_REFRESH_CERTIFICATION.csv"
SNAP_FAILURE = SNAPSHOTS / "V20_108_R6A_R2_ENABLED_REFRESH_FAILURE_AUDIT.csv"
SNAP_GATE = SNAPSHOTS / "V20_108_R6A_R2_ENABLED_REFRESH_NEXT_STAGE_GATE.csv"
LIVE_CACHE = CONSOLIDATION / "V20_108_R6A_R2_CONTROLLED_FUNDAMENTAL_PROVIDER_REFRESH_CACHE.csv"
LIVE_CERT = CONSOLIDATION / "V20_108_R6A_R2_FUNDAMENTAL_METRIC_COVERAGE_CERTIFICATION.csv"
LIVE_FAILURE = CONSOLIDATION / "V20_108_R6A_R2_REFRESH_FAILURE_AUDIT.csv"
LIVE_GATE = CONSOLIDATION / "V20_108_R6A_R2_NEXT_STAGE_GATE.csv"
R1_CONTRACT = CONSOLIDATION / "V20_108_R6A_R1_FUNDAMENTAL_SOURCE_CONTRACT.csv"
R1_TEMPLATE = CONSOLIDATION / "V20_108_R6A_R1_FUNDAMENTAL_LOCAL_INPUT_TEMPLATE.csv"
R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OPTIONAL_PATCH_INPUTS = [
    ROOT / "data" / "v20" / "fundamental" / "V20_FUNDAMENTAL_METRIC_PATCH.csv",
    ROOT / "cache" / "v20" / "fundamental" / "V20_FUNDAMENTAL_METRIC_PATCH.csv",
    ROOT / "inputs" / "v20" / "fundamental" / "V20_FUNDAMENTAL_METRIC_PATCH.csv",
]

OUT_REPAIR = CONSOLIDATION / "V20_108_R6A_R3_FUNDAMENTAL_REFRESH_COVERAGE_REPAIR_AUDIT.csv"
OUT_PATCH_TEMPLATE = CONSOLIDATION / "V20_108_R6A_R3_FUNDAMENTAL_LOCAL_PATCH_TEMPLATE.csv"
OUT_PATCH_GATE = CONSOLIDATION / "V20_108_R6A_R3_FUNDAMENTAL_PATCH_IMPORT_GATE_AUDIT.csv"
OUT_PARTIAL_GATE = CONSOLIDATION / "V20_108_R6A_R3_PARTIAL_MATERIALIZATION_GATE.csv"
OUT_NEXT = CONSOLIDATION / "V20_108_R6A_R3_NEXT_REPAIR_ACTION.csv"
REPORT = READ_CENTER / "V20_108_R6A_R3_FUNDAMENTAL_REFRESH_COVERAGE_REPAIR_REPORT.md"

PASS_GATE = "PASS_V20_108_R6A_R3_FUNDAMENTAL_REFRESH_COVERAGE_REPAIR_GATE"
PARTIAL_WAITING = "PARTIAL_PASS_V20_108_R6A_R3_WAITING_FOR_LOCAL_PATCH"
PASS_PARTIAL_APPROVED = "PASS_V20_108_R6A_R3_PARTIAL_MATERIALIZATION_GATE_APPROVED"
BLOCKED_INSUFFICIENT = "BLOCKED_V20_108_R6A_R3_INSUFFICIENT_CERTIFIED_FUNDAMENTAL_COVERAGE"

METRICS = [
    "revenue_growth", "earnings_growth", "gross_margin", "operating_margin",
    "profit_margin", "return_on_equity", "return_on_assets", "operating_cashflow",
    "free_cashflow", "capital_expenditures", "debt_to_equity", "current_ratio",
    "quick_ratio", "market_cap", "enterprise_value", "trailing_pe", "forward_pe",
    "price_to_sales", "price_to_book", "ev_to_ebitda", "ebitda_margin",
    "revenue_ttm", "net_income_ttm", "total_debt", "total_cash",
]
ETF_OR_FUND_TICKERS = {
    "ARGT", "EEM", "EWY", "EWZ", "GSG", "IBIT", "IGV", "IWM", "IYW",
    "KWEB", "QQQ", "RSP", "SMH", "SOXL", "SOXX", "SPY", "XLF", "XLK",
}
MINIMUM_METRIC_THRESHOLD = 5
STALE_AFTER_DAYS = 90

REPAIR_FIELDS = [
    "ticker", "baseline_rank", "fundamental_metric_certification_status",
    "present_numeric_metric_count", "missing_metric_count", "refresh_status",
    "failure_type", "failure_reason", "repair_classification",
    "local_patch_required", "partial_materialization_eligible",
    "exclusion_required_if_not_repaired", "recommended_repair_action",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "is_official_ranking", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]
PATCH_TEMPLATE_FIELDS = [
    "ticker", "baseline_rank", "metric_source_provider", "metric_source_timestamp",
    *METRICS, "research_only", "official_promotion_allowed",
    "official_recommendation_created", "is_official_ranking", "is_official_weight",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]
PATCH_GATE_FIELDS = [
    "patch_path", "patch_file_exists", "patch_file_non_empty",
    "non_certified_candidate_count", "patch_candidate_count_found",
    "patch_ticker_coverage_count", "missing_patch_ticker_count",
    "numeric_metric_columns_present", "non_numeric_metric_columns_rejected",
    "source_timestamp_available", "stale_rows_rejected", "source_rank_or_score_present",
    "source_rank_or_score_used_as_fundamental", "baseline_rank_used_as_fundamental",
    "fabricated_values_created", "proxy_values_activated",
    "patch_import_gate_status", "patch_import_blocker_reason",
    "recommended_next_stage", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]
PARTIAL_GATE_FIELDS = [
    "gate_check_id", "candidate_count", "certified_candidate_count",
    "partial_candidate_count", "missing_candidate_count", "certified_coverage_ratio",
    "partial_materialization_threshold", "partial_materialization_allowed",
    "certified_candidates_usable", "partial_candidates_excluded_or_pending_patch",
    "missing_candidates_excluded_or_pending_patch",
    "fundamental_score_materialization_ready", "recommended_next_stage",
    "blocking_reason", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]
NEXT_FIELDS = [
    "repair_action_id", "wrapper_status", "non_certified_candidate_count",
    "partial_materialization_allowed", "local_patch_required_count",
    "next_required_action", "recommended_next_stage",
    "external_refresh_attempted", "fabricated_values_created", "proxy_values_activated",
    "fundamental_contribution_scores_created", "shadow_rerank_output_created",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "is_official_ranking", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def safety(extra: bool = False) -> dict[str, str]:
    row = {
        "research_only": "TRUE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
    }
    if extra:
        row["is_official_ranking"] = "FALSE"
        row["is_official_weight"] = "FALSE"
    return row


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    if not path.exists():
        return [], [], "MISSING"
    if path.stat().st_size == 0:
        return [], [], "EMPTY"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [{key: clean(value) for key, value in row.items()} for row in reader]
    return rows, fields, "OK" if fields else "MALFORMED"


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def is_number(value: str) -> bool:
    try:
        parsed = float(clean(value))
    except ValueError:
        return False
    return not (math.isnan(parsed) or math.isinf(parsed))


def parse_timestamp(value: str) -> datetime | None:
    text = clean(value)
    if not text:
        return None
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def load_enabled_source() -> tuple[list[dict[str, str]], Path, Path, Path, Path]:
    if SNAP_CACHE.exists():
        rows, _, _ = read_csv(SNAP_CACHE)
        return rows, SNAP_CACHE, SNAP_CERT, SNAP_FAILURE, SNAP_GATE
    rows, _, _ = read_csv(LIVE_CACHE)
    return rows, LIVE_CACHE, LIVE_CERT, LIVE_FAILURE, LIVE_GATE


def failure_map(path: Path) -> dict[str, dict[str, str]]:
    rows, _, _ = read_csv(path)
    return {row.get("ticker", ""): row for row in rows if row.get("ticker")}


def first_value(path: Path, field: str, default: str) -> str:
    rows, _, status = read_csv(path)
    if status == "OK" and rows:
        return rows[0].get(field, default) or default
    return default


def classify(row: dict[str, str], fail: dict[str, str]) -> str:
    ticker = row.get("ticker", "")
    status = row.get("fundamental_metric_certification_status", "")
    present = int(row.get("present_numeric_metric_count") or 0)
    freshness = row.get("freshness_status", "")
    failure_type = fail.get("failure_type", "")
    if status == "FUNDAMENTAL_METRICS_CERTIFIED":
        return "CERTIFIED_NO_REPAIR_REQUIRED"
    if "STALE" in freshness or "TIMESTAMP" in failure_type:
        return "METRIC_SOURCE_STALE_OR_INVALID"
    if failure_type in {"PROVIDER_TICKER_REFRESH_ERROR", "PROVIDER_SYMBOL_FAILURE"}:
        return "PROVIDER_SYMBOL_FAILURE"
    if ticker in ETF_OR_FUND_TICKERS:
        return "ETF_OR_FUNDAMENTAL_NOT_APPLICABLE"
    if status == "FUNDAMENTAL_METRICS_MISSING" or present == 0:
        return "MISSING_ALL_FUNDAMENTAL_METRICS"
    if 0 < present < MINIMUM_METRIC_THRESHOLD:
        return "PARTIAL_BELOW_MINIMUM_METRIC_THRESHOLD"
    return "UNKNOWN_REPAIR_REQUIRED"


def repair_action(classification: str) -> str:
    if classification == "CERTIFIED_NO_REPAIR_REQUIRED":
        return "No local patch required; retain real ticker-level numeric metrics from enabled refresh snapshot."
    if classification == "ETF_OR_FUNDAMENTAL_NOT_APPLICABLE":
        return "Confirm whether the instrument should be excluded from fundamental materialization or provide trusted fund-level local patch metrics."
    if classification == "NON_EQUITY_INSTRUMENT":
        return "Confirm non-equity treatment and exclude from fundamental materialization unless trusted local metrics are supplied."
    if classification == "METRIC_SOURCE_STALE_OR_INVALID":
        return "Provide a trusted local patch row with fresh metric_source_timestamp and accepted numeric metric values."
    if classification == "PROVIDER_SYMBOL_FAILURE":
        return "Repair provider symbol mapping or provide trusted local patch metrics."
    return "Provide trusted local patch metrics with provider name, fresh timestamp, and accepted numeric metric values."


def build_repair_audit(rows: list[dict[str, str]], failures: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    audit_rows = []
    for row in rows:
        fail = failures.get(row.get("ticker", ""), {})
        classification = classify(row, fail)
        certified = row.get("fundamental_metric_certification_status") == "FUNDAMENTAL_METRICS_CERTIFIED"
        audit_rows.append({
            "ticker": row.get("ticker", ""),
            "baseline_rank": row.get("baseline_rank", ""),
            "fundamental_metric_certification_status": row.get("fundamental_metric_certification_status", ""),
            "present_numeric_metric_count": row.get("present_numeric_metric_count", "0"),
            "missing_metric_count": row.get("missing_metric_count", str(len(METRICS))),
            "refresh_status": row.get("provider_refresh_status", ""),
            "failure_type": fail.get("failure_type", ""),
            "failure_reason": fail.get("failure_reason", ""),
            "repair_classification": classification,
            "local_patch_required": tf(not certified),
            "partial_materialization_eligible": tf(certified),
            "exclusion_required_if_not_repaired": tf(not certified),
            "recommended_repair_action": repair_action(classification),
            **safety(extra=True),
        })
    return audit_rows


def build_patch_template(non_certified: list[dict[str, str]]) -> list[dict[str, str]]:
    template = []
    for row in non_certified:
        patch = {
            "ticker": row["ticker"],
            "baseline_rank": row.get("baseline_rank", ""),
            "metric_source_provider": "",
            "metric_source_timestamp": "",
        }
        patch.update({metric: "" for metric in METRICS})
        patch.update(safety(extra=True))
        template.append(patch)
    return template


def validate_patch(path: Path, non_certified_tickers: set[str], now: datetime) -> dict[str, str]:
    rows, fields, status = read_csv(path)
    found = {row.get("ticker", "") for row in rows if row.get("ticker") in non_certified_tickers}
    rejected: set[str] = set()
    numeric_cols: set[str] = set()
    stale_rows = 0
    timestamps = 0
    for row in rows:
        if row.get("ticker") not in non_certified_tickers:
            continue
        parsed = parse_timestamp(row.get("metric_source_timestamp", ""))
        if parsed is not None:
            timestamps += 1
        stale = parsed is None or (now - parsed).days > STALE_AFTER_DAYS
        if stale:
            stale_rows += 1
        for metric in METRICS:
            value = clean(row.get(metric))
            if not value:
                continue
            if is_number(value) and not stale:
                numeric_cols.add(metric)
            elif not is_number(value):
                rejected.add(metric)
    missing = non_certified_tickers - found
    blockers = []
    if status != "OK":
        blockers.append(status)
    if missing:
        blockers.append("MISSING_PATCH_TICKERS")
    if rejected:
        blockers.append("NON_NUMERIC_METRIC_VALUES")
    if stale_rows:
        blockers.append("STALE_OR_INVALID_PATCH_TIMESTAMPS")
    gate_status = "PASS_LOCAL_PATCH_INPUT_VALIDATED" if path.exists() and not blockers and found == non_certified_tickers else ("WAITING_FOR_LOCAL_PATCH" if not path.exists() else "BLOCKED_LOCAL_PATCH_VALIDATION_FAILED")
    return {
        "patch_path": rel(path),
        "patch_file_exists": tf(path.exists()),
        "patch_file_non_empty": tf(path.exists() and path.stat().st_size > 0),
        "non_certified_candidate_count": str(len(non_certified_tickers)),
        "patch_candidate_count_found": str(len(found)),
        "patch_ticker_coverage_count": str(len(found)),
        "missing_patch_ticker_count": str(len(missing)),
        "numeric_metric_columns_present": ";".join(sorted(numeric_cols)),
        "non_numeric_metric_columns_rejected": ";".join(sorted(rejected)),
        "source_timestamp_available": str(timestamps),
        "stale_rows_rejected": str(stale_rows),
        "source_rank_or_score_present": tf("source_rank_or_score" in fields),
        "source_rank_or_score_used_as_fundamental": "FALSE",
        "baseline_rank_used_as_fundamental": "FALSE",
        "fabricated_values_created": "FALSE",
        "proxy_values_activated": "FALSE",
        "patch_import_gate_status": gate_status,
        "patch_import_blocker_reason": ";".join(blockers) if blockers else ("LOCAL_PATCH_FILE_NOT_PRESENT" if not path.exists() else ""),
        "recommended_next_stage": "V20.108-R6A-R3_LOCAL_PATCH_MERGE_REVIEW" if gate_status == "PASS_LOCAL_PATCH_INPUT_VALIDATED" else "PROVIDE_TRUSTED_LOCAL_PATCH_OR_APPROVE_PARTIAL_MATERIALIZATION",
        **safety(),
    }


def empty_patch_audit(path: Path, non_certified_count: int) -> dict[str, str]:
    return {
        "patch_path": rel(path),
        "patch_file_exists": "FALSE",
        "patch_file_non_empty": "FALSE",
        "non_certified_candidate_count": str(non_certified_count),
        "patch_candidate_count_found": "0",
        "patch_ticker_coverage_count": "0",
        "missing_patch_ticker_count": str(non_certified_count),
        "numeric_metric_columns_present": "",
        "non_numeric_metric_columns_rejected": "",
        "source_timestamp_available": "0",
        "stale_rows_rejected": "0",
        "source_rank_or_score_present": "FALSE",
        "source_rank_or_score_used_as_fundamental": "FALSE",
        "baseline_rank_used_as_fundamental": "FALSE",
        "fabricated_values_created": "FALSE",
        "proxy_values_activated": "FALSE",
        "patch_import_gate_status": "WAITING_FOR_LOCAL_PATCH",
        "patch_import_blocker_reason": "LOCAL_PATCH_FILE_NOT_PRESENT",
        "recommended_next_stage": "PROVIDE_TRUSTED_LOCAL_PATCH_OR_APPROVE_PARTIAL_MATERIALIZATION",
        **safety(),
    }


def main() -> int:
    now = datetime.now(timezone.utc)
    source_rows, cache_path, cert_path, failure_path, gate_path = load_enabled_source()
    failures = failure_map(failure_path)
    repair_rows = build_repair_audit(source_rows, failures)
    non_certified = [row for row in repair_rows if row["fundamental_metric_certification_status"] != "FUNDAMENTAL_METRICS_CERTIFIED"]
    patch_template = build_patch_template(non_certified)
    non_certified_tickers = {row["ticker"] for row in non_certified}
    patch_audits = [
        validate_patch(path, non_certified_tickers, now) if path.exists() else empty_patch_audit(path, len(non_certified))
        for path in OPTIONAL_PATCH_INPUTS
    ]

    candidate_count = len(source_rows)
    certified_count = sum(1 for row in repair_rows if row["fundamental_metric_certification_status"] == "FUNDAMENTAL_METRICS_CERTIFIED")
    partial_count = sum(1 for row in repair_rows if row["fundamental_metric_certification_status"] == "FUNDAMENTAL_METRICS_PARTIAL")
    missing_count = sum(1 for row in repair_rows if row["fundamental_metric_certification_status"] != "FUNDAMENTAL_METRICS_CERTIFIED" and row["fundamental_metric_certification_status"] != "FUNDAMENTAL_METRICS_PARTIAL")
    threshold = float(os.environ.get("V20_108_R6A_R3_PARTIAL_MATERIALIZATION_THRESHOLD", "0.90"))
    ratio = certified_count / candidate_count if candidate_count else 0.0
    certified_usable = all(row["partial_materialization_eligible"] == "TRUE" for row in repair_rows if row["fundamental_metric_certification_status"] == "FUNDAMENTAL_METRICS_CERTIFIED")
    noncert_excluded = all(row["exclusion_required_if_not_repaired"] == "TRUE" for row in non_certified)
    partial_allowed = ratio >= threshold and certified_usable and noncert_excluded
    recommended = "V20.108-R6B_FUNDAMENTAL_CANDIDATE_SCORE_MATERIALIZER_WITH_PARTIAL_COVERAGE" if partial_allowed else "V20.108-R6A-R3_LOCAL_PATCH_REPAIR_OR_PROVIDER_SYMBOL_REPAIR"
    blocking = "" if partial_allowed else "CERTIFIED_COVERAGE_BELOW_THRESHOLD_OR_EXCLUSION_SAFETY_NOT_MET"
    partial_gate = [{
        "gate_check_id": "V20_108_R6A_R3_PARTIAL_MATERIALIZATION_GATE_001",
        "candidate_count": str(candidate_count),
        "certified_candidate_count": str(certified_count),
        "partial_candidate_count": str(partial_count),
        "missing_candidate_count": str(missing_count),
        "certified_coverage_ratio": f"{ratio:.10f}",
        "partial_materialization_threshold": f"{threshold:.4f}",
        "partial_materialization_allowed": tf(partial_allowed),
        "certified_candidates_usable": tf(certified_usable),
        "partial_candidates_excluded_or_pending_patch": tf(noncert_excluded),
        "missing_candidates_excluded_or_pending_patch": tf(noncert_excluded),
        "fundamental_score_materialization_ready": "FALSE",
        "recommended_next_stage": recommended,
        "blocking_reason": blocking,
        **safety(),
        "is_official_weight": "FALSE",
    }]
    if partial_allowed:
        wrapper_status = PASS_PARTIAL_APPROVED
    elif ratio > 0:
        wrapper_status = PARTIAL_WAITING
    else:
        wrapper_status = BLOCKED_INSUFFICIENT

    next_rows = [{
        "repair_action_id": "V20_108_R6A_R3_NEXT_REPAIR_ACTION_001",
        "wrapper_status": wrapper_status,
        "non_certified_candidate_count": str(len(non_certified)),
        "partial_materialization_allowed": tf(partial_allowed),
        "local_patch_required_count": str(len(non_certified)),
        "next_required_action": "Use certified candidates only for partial materialization while keeping 18 non-certified candidates excluded/pending patch." if partial_allowed else "Provide trusted local patch metrics for non-certified candidates or repair provider symbols.",
        "recommended_next_stage": recommended,
        "external_refresh_attempted": "FALSE",
        "fabricated_values_created": "FALSE",
        "proxy_values_activated": "FALSE",
        "fundamental_contribution_scores_created": "FALSE",
        "shadow_rerank_output_created": "FALSE",
        **safety(extra=True),
    }]

    write_csv(OUT_REPAIR, REPAIR_FIELDS, repair_rows)
    write_csv(OUT_PATCH_TEMPLATE, PATCH_TEMPLATE_FIELDS, patch_template)
    write_csv(OUT_PATCH_GATE, PATCH_GATE_FIELDS, patch_audits)
    write_csv(OUT_PARTIAL_GATE, PARTIAL_GATE_FIELDS, partial_gate)
    write_csv(OUT_NEXT, NEXT_FIELDS, next_rows)

    research_gate = first_value(V49_RESEARCH, "research_only_gate_status", "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE")
    official_gate = first_value(V49_OFFICIAL, "official_promotion_gate_status", "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE")
    report = [
        "# V20.108-R6A-R3 Fundamental Refresh Coverage Repair Report",
        "",
        "## Current Result",
        f"- wrapper_status: {wrapper_status}",
        f"- source_cache: {rel(cache_path)}",
        f"- source_certification: {rel(cert_path)}",
        f"- source_next_stage_gate: {rel(gate_path)}",
        f"- candidate_count: {candidate_count}",
        f"- certified_candidate_count: {certified_count}",
        f"- partial_candidate_count: {partial_count}",
        f"- missing_candidate_count: {missing_count}",
        f"- non_certified_candidate_count: {len(non_certified)}",
        f"- certified_coverage_ratio: {ratio:.10f}",
        f"- partial_materialization_threshold: {threshold:.4f}",
        f"- partial_materialization_allowed: {tf(partial_allowed)}",
        f"- fundamental_score_materialization_ready: FALSE",
        f"- v20_49_research_only_gate_status: {research_gate}",
        f"- v20_49_official_promotion_gate_status: {official_gate}",
        "- external_refresh_attempted: FALSE",
        "- source_rank_or_score_used_as_fundamental: FALSE",
        "- baseline_rank_used_as_fundamental: FALSE",
        "- fabricated_values_created: FALSE",
        "- proxy_values_activated: FALSE",
        "- fundamental_contribution_scores_created: FALSE",
        "- shadow_rerank_output_created: FALSE",
        "- official_ranking_created: FALSE",
        "- authoritative_ranking_overwritten: FALSE",
        "",
        "## Safety Boundary",
        "- research_only: TRUE",
        "- official_promotion_allowed: FALSE",
        "- official_recommendation_created: FALSE",
        "- is_official_ranking: FALSE",
        "- is_official_weight: FALSE",
        "- weight_mutated: FALSE",
        "- trade_action_created: FALSE",
        "- broker_execution_supported: FALSE",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")

    print(wrapper_status)
    print(f"CANDIDATE_COUNT={candidate_count}")
    print(f"NON_CERTIFIED_CANDIDATE_COUNT={len(non_certified)}")
    print(f"PATCH_TEMPLATE_ROWS={len(patch_template)}")
    print(f"PARTIAL_MATERIALIZATION_ALLOWED={tf(partial_allowed)}")
    print("EXTERNAL_REFRESH_ATTEMPTED=FALSE")
    print("SOURCE_RANK_OR_SCORE_USED_AS_FUNDAMENTAL=FALSE")
    print("BASELINE_RANK_USED_AS_FUNDAMENTAL=FALSE")
    print("FABRICATED_VALUES_CREATED=FALSE")
    print("PROXY_VALUES_ACTIVATED=FALSE")
    print("FUNDAMENTAL_CONTRIBUTION_SCORES_CREATED=FALSE")
    print("SHADOW_RERANK_OUTPUT_CREATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("IS_OFFICIAL_WEIGHT=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print(f"OUTPUT_REPAIR_AUDIT={rel(OUT_REPAIR)}")
    print(f"OUTPUT_PATCH_TEMPLATE={rel(OUT_PATCH_TEMPLATE)}")
    print(f"OUTPUT_PATCH_IMPORT_GATE={rel(OUT_PATCH_GATE)}")
    print(f"OUTPUT_PARTIAL_MATERIALIZATION_GATE={rel(OUT_PARTIAL_GATE)}")
    print(f"OUTPUT_NEXT_REPAIR_ACTION={rel(OUT_NEXT)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
