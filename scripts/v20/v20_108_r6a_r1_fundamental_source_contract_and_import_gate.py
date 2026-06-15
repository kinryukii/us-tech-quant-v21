#!/usr/bin/env python
"""V20.108-R6A-R1 fundamental source contract and import gate.

Defines the trusted local fundamental metric input contract and validates an
optional local input file. This research-only stage never fetches external
data, creates contribution scores, creates rankings, mutates weights, or
enables execution.
"""

from __future__ import annotations

import csv
import math
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R6A_CACHE = CONSOLIDATION / "V20_108_R6A_CONTROLLED_FUNDAMENTAL_METRIC_CACHE.csv"
R6A_SOURCE_AUDIT = CONSOLIDATION / "V20_108_R6A_FUNDAMENTAL_METRIC_SOURCE_AUDIT.csv"
R6A_CERT = CONSOLIDATION / "V20_108_R6A_FUNDAMENTAL_METRIC_COVERAGE_CERTIFICATION.csv"
R6A_REPAIR = CONSOLIDATION / "V20_108_R6A_FUNDAMENTAL_REFRESH_REPAIR_PLAN.csv"
R6_COVERAGE = CONSOLIDATION / "V20_108_R6_FUNDAMENTAL_COVERAGE_AFTER_BUILD.csv"
R5_PLAN = CONSOLIDATION / "V20_108_R5_MISSING_UPSTREAM_FACTOR_SCORE_STAGE_PLAN.csv"
R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
V50_CANDIDATES = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OPTIONAL_INPUTS = [
    ROOT / "data" / "v20" / "fundamental" / "V20_FUNDAMENTAL_METRIC_INPUT.csv",
    ROOT / "cache" / "v20" / "fundamental" / "V20_FUNDAMENTAL_METRIC_INPUT.csv",
    ROOT / "inputs" / "v20" / "fundamental" / "V20_FUNDAMENTAL_METRIC_INPUT.csv",
]
REQUIRED_UPSTREAMS = [
    R6A_CACHE,
    R6A_SOURCE_AUDIT,
    R6A_CERT,
    R6A_REPAIR,
    R6_COVERAGE,
    R5_PLAN,
    R4_SCORES,
    V50_CANDIDATES,
    V48_CANDIDATES,
    V49_RESEARCH,
    V49_OFFICIAL,
]

OUT_CONTRACT = CONSOLIDATION / "V20_108_R6A_R1_FUNDAMENTAL_SOURCE_CONTRACT.csv"
OUT_TEMPLATE = CONSOLIDATION / "V20_108_R6A_R1_FUNDAMENTAL_LOCAL_INPUT_TEMPLATE.csv"
OUT_IMPORT_AUDIT = CONSOLIDATION / "V20_108_R6A_R1_FUNDAMENTAL_IMPORT_GATE_AUDIT.csv"
OUT_PROVIDER_REQ = CONSOLIDATION / "V20_108_R6A_R1_FUNDAMENTAL_PROVIDER_CONFIG_REQUIREMENT.csv"
OUT_NEXT = CONSOLIDATION / "V20_108_R6A_R1_NEXT_REPAIR_ACTION.csv"
REPORT = READ_CENTER / "V20_108_R6A_R1_FUNDAMENTAL_SOURCE_CONTRACT_AND_IMPORT_GATE_REPORT.md"

PASS_CREATED = "PASS_V20_108_R6A_R1_FUNDAMENTAL_SOURCE_CONTRACT_AND_IMPORT_GATE_CREATED"
PARTIAL_WAITING = "PARTIAL_PASS_V20_108_R6A_R1_FUNDAMENTAL_IMPORT_GATE_WAITING_FOR_LOCAL_INPUT"
PASS_VALIDATED = "PASS_V20_108_R6A_R1_FUNDAMENTAL_LOCAL_INPUT_VALIDATED"

STALE_AFTER_DAYS = 90
CONTRACT_ID = "V20_108_R6A_R1_FUNDAMENTAL_SOURCE_CONTRACT"

METRIC_GROUP_BY_COLUMN = {
    "revenue_growth": "growth",
    "earnings_growth": "growth",
    "gross_margin": "margin",
    "operating_margin": "margin",
    "profit_margin": "profitability",
    "return_on_equity": "quality",
    "return_on_assets": "quality",
    "operating_cashflow": "cash_flow",
    "free_cashflow": "cash_flow",
    "capital_expenditures": "capex",
    "debt_to_equity": "balance_sheet",
    "current_ratio": "liquidity",
    "quick_ratio": "liquidity",
    "market_cap": "valuation",
    "enterprise_value": "valuation",
    "trailing_pe": "valuation",
    "forward_pe": "valuation",
    "price_to_sales": "valuation",
    "price_to_book": "valuation",
    "ev_to_ebitda": "valuation",
    "ebitda_margin": "margin",
    "revenue_ttm": "growth",
    "net_income_ttm": "profitability",
    "total_debt": "balance_sheet",
    "total_cash": "balance_sheet",
}
METRICS = list(METRIC_GROUP_BY_COLUMN)
REQUIRED_INPUT_COLUMNS = ["ticker", "metric_source_provider", "metric_source_timestamp", *METRICS]
TEMPLATE_FIELDS = [
    "ticker", "baseline_rank", "metric_source_provider", "metric_source_timestamp", *METRICS,
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "is_official_ranking", "is_official_weight", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]
CONTRACT_FIELDS = [
    "contract_id", "metric_group", "metric_name", "required_column",
    "accepted_data_type", "required_for_minimum_certification", "stale_after_days",
    "allow_missing", "imputation_allowed", "contribution_score_created",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "is_official_weight", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]
IMPORT_AUDIT_FIELDS = [
    "import_path", "input_file_exists", "input_file_non_empty",
    "candidate_count_required", "candidate_count_found", "ticker_coverage_count",
    "missing_ticker_count", "numeric_metric_columns_present",
    "non_numeric_metric_columns_rejected", "source_timestamp_available",
    "stale_rows_rejected", "source_rank_or_score_present",
    "source_rank_or_score_used_as_fundamental", "baseline_rank_used_as_fundamental",
    "fabricated_values_created", "import_gate_status", "import_gate_blocker_reason",
    "recommended_next_stage", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]
PROVIDER_FIELDS = [
    "provider_config_id", "refresh_provider_name", "refresh_allowed_flag",
    "refresh_allowed_flag_required_value", "provider_credentials_required",
    "provider_rate_limit_handling_required", "provider_output_cache_path",
    "refresh_execution_allowed_in_this_stage", "unsafe_action_forbidden",
    "recommended_refresh_stage", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]
NEXT_FIELDS = [
    "repair_action_id", "wrapper_status", "import_gate_status", "blocker_reason",
    "next_required_action", "recommended_next_stage", "v20_49_research_only_gate_status",
    "v20_49_official_promotion_gate_status", "fundamental_contribution_scores_created",
    "shadow_rerank_output_created", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "is_official_ranking", "is_official_weight",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
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
    candidates = [text, text.replace("Z", "+00:00")]
    for candidate in candidates:
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


def load_candidates() -> list[dict[str, str]]:
    rows, _, status = read_csv(R4_SCORES)
    if status == "OK" and rows:
        return [{"ticker": row.get("ticker", ""), "baseline_rank": row.get("baseline_rank", "")} for row in rows if row.get("ticker")]
    rows, _, status = read_csv(V48_CANDIDATES)
    if status == "OK" and rows:
        return [
            {"ticker": row.get("normalized_ticker") or row.get("ticker_or_candidate_id", ""), "baseline_rank": row.get("report_rank", "")}
            for row in rows
            if row.get("normalized_ticker") or row.get("ticker_or_candidate_id")
        ]
    return []


def gate_status(path_exists: bool, valid: bool, blocker: str) -> str:
    if valid:
        return "PASS_LOCAL_FUNDAMENTAL_INPUT_VALIDATED"
    if not path_exists:
        return "WAITING_FOR_TRUSTED_LOCAL_FUNDAMENTAL_INPUT"
    return "BLOCKED_LOCAL_FUNDAMENTAL_INPUT_CONTRACT_VALIDATION_FAILED" if blocker else "WAITING_FOR_TRUSTED_LOCAL_FUNDAMENTAL_INPUT"


def build_contract() -> list[dict[str, str]]:
    rows = []
    for metric, group in METRIC_GROUP_BY_COLUMN.items():
        rows.append({
            "contract_id": CONTRACT_ID,
            "metric_group": group,
            "metric_name": metric,
            "required_column": metric,
            "accepted_data_type": "NUMERIC_FLOAT_OR_INTEGER",
            "required_for_minimum_certification": "TRUE",
            "stale_after_days": str(STALE_AFTER_DAYS),
            "allow_missing": "FALSE",
            "imputation_allowed": "FALSE",
            "contribution_score_created": "FALSE",
            "is_official_weight": "FALSE",
            **safety(),
        })
    return rows


def build_template(candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for candidate in candidates:
        row = {"ticker": candidate["ticker"], "baseline_rank": candidate.get("baseline_rank", "")}
        row.update({"metric_source_provider": "", "metric_source_timestamp": ""})
        row.update({metric: "" for metric in METRICS})
        row.update(safety(extra=True))
        rows.append(row)
    return rows


def validate_input(path: Path, candidates: list[dict[str, str]], now: datetime) -> dict[str, str]:
    rows, fields, status = read_csv(path)
    required_tickers = {row["ticker"] for row in candidates}
    found_tickers = {row.get("ticker", "") for row in rows if row.get("ticker")}
    missing_tickers = required_tickers - found_tickers
    metric_fields_present = [metric for metric in METRICS if metric in fields]
    rejected: set[str] = set()
    rows_with_timestamp = 0
    stale_rows = 0
    rows_with_numeric_metric = 0
    for row in rows:
        has_numeric = False
        for metric in metric_fields_present:
            value = clean(row.get(metric))
            if not value:
                continue
            if is_number(value):
                has_numeric = True
            else:
                rejected.add(metric)
        if has_numeric:
            rows_with_numeric_metric += 1
        parsed = parse_timestamp(row.get("metric_source_timestamp", ""))
        if parsed is not None:
            rows_with_timestamp += 1
            if (now - parsed).days > STALE_AFTER_DAYS:
                stale_rows += 1
    missing_required_columns = [column for column in REQUIRED_INPUT_COLUMNS if column not in fields]
    blockers = []
    if status != "OK":
        blockers.append(status)
    if missing_required_columns:
        blockers.append("MISSING_REQUIRED_COLUMNS=" + ";".join(missing_required_columns))
    if missing_tickers:
        blockers.append("MISSING_CANDIDATE_TICKERS")
    if rejected:
        blockers.append("NON_NUMERIC_METRIC_VALUES")
    if rows_with_timestamp < len(rows):
        blockers.append("MISSING_OR_INVALID_SOURCE_TIMESTAMPS")
    if stale_rows:
        blockers.append("STALE_SOURCE_ROWS")
    if rows_with_numeric_metric < len(required_tickers):
        blockers.append("INSUFFICIENT_NUMERIC_METRIC_AVAILABILITY")
    valid = bool(rows) and not blockers and len(found_tickers & required_tickers) == len(required_tickers)
    return {
        "import_path": rel(path),
        "input_file_exists": tf(path.exists()),
        "input_file_non_empty": tf(path.exists() and path.stat().st_size > 0),
        "candidate_count_required": str(len(candidates)),
        "candidate_count_found": str(len(found_tickers)),
        "ticker_coverage_count": str(len(found_tickers & required_tickers)),
        "missing_ticker_count": str(len(missing_tickers)),
        "numeric_metric_columns_present": ";".join(metric_fields_present),
        "non_numeric_metric_columns_rejected": ";".join(sorted(rejected)),
        "source_timestamp_available": str(rows_with_timestamp),
        "stale_rows_rejected": str(stale_rows),
        "source_rank_or_score_present": tf("source_rank_or_score" in fields),
        "source_rank_or_score_used_as_fundamental": "FALSE",
        "baseline_rank_used_as_fundamental": "FALSE",
        "fabricated_values_created": "FALSE",
        "import_gate_status": gate_status(path.exists(), valid, ";".join(blockers)),
        "import_gate_blocker_reason": ";".join(blockers),
        "recommended_next_stage": "V20.108-R6A-R2_TRUSTED_LOCAL_FUNDAMENTAL_INPUT_IMPORT" if valid else "PROVIDE_TRUSTED_LOCAL_FUNDAMENTAL_INPUT_AND_RERUN_R6A_R1",
        **safety(),
    }


def empty_input_audit(path: Path, candidates: list[dict[str, str]]) -> dict[str, str]:
    return {
        "import_path": rel(path),
        "input_file_exists": "FALSE",
        "input_file_non_empty": "FALSE",
        "candidate_count_required": str(len(candidates)),
        "candidate_count_found": "0",
        "ticker_coverage_count": "0",
        "missing_ticker_count": str(len(candidates)),
        "numeric_metric_columns_present": "",
        "non_numeric_metric_columns_rejected": "",
        "source_timestamp_available": "0",
        "stale_rows_rejected": "0",
        "source_rank_or_score_present": "FALSE",
        "source_rank_or_score_used_as_fundamental": "FALSE",
        "baseline_rank_used_as_fundamental": "FALSE",
        "fabricated_values_created": "FALSE",
        "import_gate_status": "WAITING_FOR_TRUSTED_LOCAL_FUNDAMENTAL_INPUT",
        "import_gate_blocker_reason": "LOCAL_INPUT_FILE_NOT_PRESENT",
        "recommended_next_stage": "PROVIDE_TRUSTED_LOCAL_FUNDAMENTAL_INPUT_AND_RERUN_R6A_R1",
        **safety(),
    }


def status_from_audits(audits: list[dict[str, str]]) -> str:
    if any(row["import_gate_status"] == "PASS_LOCAL_FUNDAMENTAL_INPUT_VALIDATED" for row in audits):
        return PASS_VALIDATED
    if all(row["input_file_exists"] == "FALSE" for row in audits):
        return PARTIAL_WAITING
    return PASS_CREATED


def first_value(path: Path, field: str, default: str) -> str:
    rows, _, status = read_csv(path)
    if status == "OK" and rows:
        return rows[0].get(field, default) or default
    return default


def upstream_read_statuses() -> list[dict[str, str]]:
    statuses = []
    for path in REQUIRED_UPSTREAMS:
        rows, fields, status = read_csv(path)
        statuses.append({
            "path": rel(path),
            "read_status": status,
            "row_count": str(len(rows)),
            "column_count": str(len(fields)),
        })
    return statuses


def main() -> int:
    now = datetime.now(timezone.utc)
    candidates = load_candidates()
    contract_rows = build_contract()
    template_rows = build_template(candidates)
    import_audits = [
        validate_input(path, candidates, now) if path.exists() else empty_input_audit(path, candidates)
        for path in OPTIONAL_INPUTS
    ]
    upstream_reads = upstream_read_statuses()
    wrapper_status = status_from_audits(import_audits)
    best_audit = next(
        (row for row in import_audits if row["import_gate_status"] == "PASS_LOCAL_FUNDAMENTAL_INPUT_VALIDATED"),
        import_audits[0],
    )

    provider_rows = [{
        "provider_config_id": "V20_108_R6A_R1_PROVIDER_REQUIREMENT_001",
        "refresh_provider_name": "TRUSTED_FUNDAMENTAL_DATA_PROVIDER_TO_BE_CONFIGURED",
        "refresh_allowed_flag": "ENABLE_FUNDAMENTAL_REFRESH",
        "refresh_allowed_flag_required_value": "TRUE",
        "provider_credentials_required": "TRUE",
        "provider_rate_limit_handling_required": "TRUE",
        "provider_output_cache_path": rel(ROOT / "cache" / "v20" / "fundamental" / "V20_FUNDAMENTAL_METRIC_INPUT.csv"),
        "refresh_execution_allowed_in_this_stage": "FALSE",
        "unsafe_action_forbidden": "External refresh, fabricated metrics, source_rank_or_score metrics, baseline_rank metrics, contribution scores, rankings, recommendations, trades, and weight mutation are forbidden in R6A-R1.",
        "recommended_refresh_stage": "V20.108-R6A-R2_CONTROLLED_PROVIDER_REFRESH_AFTER_OPERATOR_CONFIGURATION",
        **safety(),
    }]
    research_gate = first_value(V49_RESEARCH, "research_only_gate_status", "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE")
    official_gate = first_value(V49_OFFICIAL, "official_promotion_gate_status", "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE")
    next_rows = [{
        "repair_action_id": "V20_108_R6A_R1_NEXT_REPAIR_ACTION_001",
        "wrapper_status": wrapper_status,
        "import_gate_status": best_audit["import_gate_status"],
        "blocker_reason": best_audit["import_gate_blocker_reason"],
        "next_required_action": "Populate one trusted local fundamental metric input CSV with all 315 candidates, source provider, fresh timestamps, and accepted numeric metric fields." if wrapper_status != PASS_VALIDATED else "Proceed to trusted local input import without creating contribution scores in this stage.",
        "recommended_next_stage": best_audit["recommended_next_stage"],
        "v20_49_research_only_gate_status": research_gate,
        "v20_49_official_promotion_gate_status": official_gate,
        "fundamental_contribution_scores_created": "FALSE",
        "shadow_rerank_output_created": "FALSE",
        **safety(extra=True),
    }]

    write_csv(OUT_CONTRACT, CONTRACT_FIELDS, contract_rows)
    write_csv(OUT_TEMPLATE, TEMPLATE_FIELDS, template_rows)
    write_csv(OUT_IMPORT_AUDIT, IMPORT_AUDIT_FIELDS, import_audits)
    write_csv(OUT_PROVIDER_REQ, PROVIDER_FIELDS, provider_rows)
    write_csv(OUT_NEXT, NEXT_FIELDS, next_rows)

    report_lines = [
        "# V20.108-R6A-R1 Fundamental Source Contract And Import Gate Report",
        "",
        "## Current Result",
        f"- wrapper_status: {wrapper_status}",
        f"- candidate_count_required: {len(candidates)}",
        f"- local_input_template_rows: {len(template_rows)}",
        f"- import_gate_status: {best_audit['import_gate_status']}",
        f"- v20_49_research_only_gate_status: {research_gate}",
        f"- v20_49_official_promotion_gate_status: {official_gate}",
        "- external_data_fetched: FALSE",
        "- provider_refresh_executed: FALSE",
        "- fundamental_contribution_scores_created: FALSE",
        "- shadow_rerank_output_created: FALSE",
        "- source_rank_or_score_used_as_fundamental: FALSE",
        "- baseline_rank_used_as_fundamental: FALSE",
        "- fabricated_values_created: FALSE",
        "",
        "## Contract",
        f"- required_metric_columns: {';'.join(METRICS)}",
        f"- stale_after_days: {STALE_AFTER_DAYS}",
        "- accepted_data_type: NUMERIC_FLOAT_OR_INTEGER",
        "- required_refresh_flag_for_future_provider_stage: ENABLE_FUNDAMENTAL_REFRESH=TRUE",
        "- refresh_execution_allowed_in_this_stage: FALSE",
        "",
        "## Upstream Read Audit",
        *[
            f"- {row['path']}: {row['read_status']} rows={row['row_count']} columns={row['column_count']}"
            for row in upstream_reads
        ],
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
    REPORT.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(wrapper_status)
    print(f"CANDIDATE_COUNT={len(candidates)}")
    print(f"LOCAL_INPUT_TEMPLATE_ROWS={len(template_rows)}")
    print(f"IMPORT_GATE_STATUS={best_audit['import_gate_status']}")
    print("EXTERNAL_DATA_FETCHED=FALSE")
    print("PROVIDER_REFRESH_EXECUTED=FALSE")
    print("FUNDAMENTAL_CONTRIBUTION_SCORES_CREATED=FALSE")
    print("SOURCE_RANK_OR_SCORE_USED_AS_FUNDAMENTAL=FALSE")
    print("BASELINE_RANK_USED_AS_FUNDAMENTAL=FALSE")
    print("FABRICATED_VALUES_CREATED=FALSE")
    print("SHADOW_RERANK_OUTPUT_CREATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("IS_OFFICIAL_WEIGHT=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print(f"OUTPUT_CONTRACT={rel(OUT_CONTRACT)}")
    print(f"OUTPUT_TEMPLATE={rel(OUT_TEMPLATE)}")
    print(f"OUTPUT_IMPORT_AUDIT={rel(OUT_IMPORT_AUDIT)}")
    print(f"OUTPUT_PROVIDER_REQUIREMENT={rel(OUT_PROVIDER_REQ)}")
    print(f"OUTPUT_NEXT_REPAIR_ACTION={rel(OUT_NEXT)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
