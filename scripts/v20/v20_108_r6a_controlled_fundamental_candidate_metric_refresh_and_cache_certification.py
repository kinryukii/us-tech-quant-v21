#!/usr/bin/env python
"""V20.108-R6A controlled fundamental metric cache certification.

Builds a research-only raw/semi-raw fundamental metric cache when real
ticker-level metrics exist locally or a controlled refresh is explicitly
configured. This stage never creates contribution scores, proxies, shadow
reranks, official rankings, recommendations, trades, or weights.
"""

from __future__ import annotations

import csv
import math
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R6_SOURCE = CONSOLIDATION / "V20_108_R6_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE.csv"
R6_COLUMN_AUDIT = CONSOLIDATION / "V20_108_R6_FUNDAMENTAL_SOURCE_COLUMN_AUDIT.csv"
R6_MATERIAL_AUDIT = CONSOLIDATION / "V20_108_R6_FUNDAMENTAL_SCORE_MATERIALIZATION_AUDIT.csv"
R6_COVERAGE = CONSOLIDATION / "V20_108_R6_FUNDAMENTAL_COVERAGE_AFTER_BUILD.csv"
R5_STAGE_PLAN = CONSOLIDATION / "V20_108_R5_MISSING_UPSTREAM_FACTOR_SCORE_STAGE_PLAN.csv"
R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
V50_CANDIDATES = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_CACHE = CONSOLIDATION / "V20_108_R6A_CONTROLLED_FUNDAMENTAL_METRIC_CACHE.csv"
OUT_AUDIT = CONSOLIDATION / "V20_108_R6A_FUNDAMENTAL_METRIC_SOURCE_AUDIT.csv"
OUT_CERT = CONSOLIDATION / "V20_108_R6A_FUNDAMENTAL_METRIC_COVERAGE_CERTIFICATION.csv"
OUT_REPAIR = CONSOLIDATION / "V20_108_R6A_FUNDAMENTAL_REFRESH_REPAIR_PLAN.csv"
REPORT = READ_CENTER / "V20_108_R6A_CONTROLLED_FUNDAMENTAL_METRIC_REFRESH_REPORT.md"

PASS_STATUS = "PASS_V20_108_R6A_CONTROLLED_FUNDAMENTAL_CANDIDATE_METRIC_REFRESH_CERTIFIED"
PARTIAL_STATUS = "PARTIAL_PASS_V20_108_R6A_CONTROLLED_FUNDAMENTAL_CANDIDATE_METRIC_REFRESH_WITH_PARTIAL_COVERAGE"
BLOCKED_NOT_CONFIGURED = "BLOCKED_V20_108_R6A_NO_FUNDAMENTAL_REFRESH_SOURCE_CONFIGURED"
BLOCKED_FAILED = "BLOCKED_V20_108_R6A_FUNDAMENTAL_REFRESH_FAILED"

METRICS = [
    "revenue_growth", "earnings_growth", "gross_margin", "operating_margin",
    "profit_margin", "return_on_equity", "return_on_assets", "operating_cashflow",
    "free_cashflow", "capital_expenditures", "debt_to_equity", "current_ratio",
    "quick_ratio", "market_cap", "enterprise_value", "trailing_pe", "forward_pe",
    "price_to_sales", "price_to_book", "ev_to_ebitda", "ebitda_margin",
    "revenue_ttm", "net_income_ttm", "total_debt", "total_cash",
]
METRIC_GROUPS = [
    "growth", "profitability", "margin", "quality", "valuation", "cash_flow",
    "balance_sheet", "liquidity", "capex",
]
TICKER_COLUMNS = ("ticker", "normalized_ticker", "ticker_or_candidate_id", "display_name_or_ticker", "symbol")
RANK_COLUMNS = {"source_rank_or_score", "baseline_rank", "rank", "report_rank", "factor_pack_rank"}
MINIMUM_METRIC_THRESHOLD = 5

CACHE_FIELDS = [
    "ticker", "baseline_rank", "metric_source_status", "metric_source_artifact",
    "metric_source_provider", "metric_source_timestamp", "refresh_timestamp_utc",
    "freshness_status", *METRICS, "missing_metric_count",
    "present_numeric_metric_count", "fundamental_metric_certification_status",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "is_official_ranking", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]

AUDIT_FIELDS = [
    "source_artifact", "source_exists", "source_non_empty", "source_provider",
    "source_refresh_allowed", "ticker_column_available", "candidate_rows_found",
    "numeric_metric_columns_found", "non_numeric_metric_columns_rejected",
    "stale_metric_columns_rejected", "source_rank_or_score_present",
    "source_rank_or_score_used_as_fundamental", "baseline_rank_used_as_fundamental",
    "fabricated_values_created", "source_classification_status", "validation_status",
    "validation_reason", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]

CERT_FIELDS = [
    "coverage_check_id", "required_candidate_count", "candidate_count",
    "certified_candidate_count", "partial_candidate_count", "missing_candidate_count",
    "refresh_not_configured_count", "refresh_failed_count", "required_metric_count",
    "minimum_metric_threshold", "candidates_meeting_minimum_metric_threshold",
    "coverage_ratio", "fundamental_metric_cache_status",
    "fundamental_score_materialization_ready", "recommended_next_stage",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "is_official_ranking", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]

REPAIR_FIELDS = [
    "repair_id", "blocker_type", "blocker_reason", "affected_candidate_count",
    "affected_metric_group", "required_repair_action", "acceptable_source_type",
    "unsafe_action_forbidden", "recommended_next_stage_after_repair", "research_only",
    "official_promotion_allowed", "official_recommendation_created", "weight_mutated",
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


def read_csv(path: Path) -> tuple[list[dict[str, str]], str, list[str]]:
    if not path.exists():
        return [], "MISSING", []
    if path.stat().st_size == 0:
        return [], "EMPTY", []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [{key: clean(value) for key, value in row.items()} for row in reader]
    return rows, "OK" if fields else "MALFORMED", fields


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def num(value: object) -> float | None:
    try:
        parsed = float(clean(value))
    except ValueError:
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def ticker_value(row: dict[str, str]) -> str:
    for key in TICKER_COLUMNS:
        if clean(row.get(key)):
            return clean(row.get(key))
    return ""


def load_candidates() -> list[dict[str, str]]:
    rows, status, _ = read_csv(R4_SCORES)
    if status == "OK" and rows:
        return [{"ticker": row["ticker"], "baseline_rank": row.get("baseline_rank", "")} for row in rows]
    rows, status, _ = read_csv(V48_CANDIDATES)
    if status == "OK":
        return [{"ticker": row.get("normalized_ticker") or row.get("ticker_or_candidate_id"), "baseline_rank": row.get("report_rank", "")} for row in rows]
    return []


def discover_sources() -> list[Path]:
    seeds = [
        R6_SOURCE, R6_COLUMN_AUDIT, R6_MATERIAL_AUDIT, R6_COVERAGE, R5_STAGE_PLAN,
        R4_SCORES, V50_CANDIDATES, V48_CANDIDATES, V49_RESEARCH, V49_OFFICIAL,
    ]
    found: list[Path] = []
    for root in (ROOT / "data", ROOT / "cache", ROOT / "outputs" / "v20", ROOT / "outputs" / "v19", ROOT / "outputs" / "v18", ROOT / "outputs" / "backtest"):
        if root.exists():
            found.extend(root.rglob("*.csv"))
    excluded = {OUT_CACHE.resolve(), OUT_AUDIT.resolve(), OUT_CERT.resolve(), OUT_REPAIR.resolve()}
    ordered: list[Path] = []
    seen: set[Path] = set()
    for path in seeds + sorted(found):
        resolved = path.resolve()
        if resolved in excluded:
            continue
        if resolved not in seen:
            seen.add(resolved)
            ordered.append(path)
    return ordered


def source_provider(path: Path) -> str:
    parts = [part.lower() for part in path.parts]
    if "cache" in parts:
        return "LOCAL_CACHE"
    if "data" in parts:
        return "LOCAL_DATA"
    if "outputs" in parts:
        return "LOCAL_OUTPUT_ARTIFACT"
    return "LOCAL_FILE"


def build_metric_index(candidates: list[dict[str, str]], refresh_allowed: bool) -> tuple[dict[str, dict[str, tuple[str, Path]]], list[dict[str, str]]]:
    candidate_tickers = {row["ticker"] for row in candidates if row.get("ticker")}
    metric_index: dict[str, dict[str, tuple[str, Path]]] = {ticker: {} for ticker in candidate_tickers}
    audits: list[dict[str, str]] = []
    for path in discover_sources():
        rows, status, fields = read_csv(path)
        exists = path.exists()
        ticker_available = any(field in fields for field in TICKER_COLUMNS)
        source_rank_present = "source_rank_or_score" in fields
        candidate_rows_found = 0
        numeric_cols: set[str] = set()
        non_numeric_cols: set[str] = set()
        if status == "OK" and rows and ticker_available:
            metric_cols = [field for field in fields if field.lower() in METRICS]
            for row in rows:
                ticker = ticker_value(row)
                if ticker not in candidate_tickers:
                    continue
                candidate_rows_found += 1
                for col in metric_cols:
                    value = clean(row.get(col))
                    if not value:
                        continue
                    parsed = num(value)
                    metric = col.lower()
                    if parsed is None:
                        non_numeric_cols.add(col)
                        continue
                    numeric_cols.add(col)
                    if metric not in metric_index[ticker]:
                        metric_index[ticker][metric] = (value, path)
        if numeric_cols:
            classification = "LOCAL_TICKER_LEVEL_NUMERIC_FUNDAMENTAL_METRICS_FOUND"
            validation = "PASS"
            reason = "REAL_NUMERIC_TICKER_LEVEL_METRICS_AVAILABLE"
        elif candidate_rows_found:
            classification = "TICKER_ROWS_FOUND_NO_ACCEPTED_NUMERIC_FUNDAMENTAL_METRICS"
            validation = "WARN"
            reason = "NO_ACCEPTED_NUMERIC_METRIC_COLUMNS"
        else:
            classification = "NO_USABLE_FUNDAMENTAL_METRIC_SOURCE"
            validation = "PASS"
            reason = "NO_CANDIDATE_LEVEL_ACCEPTED_METRICS"
        audits.append({
            "source_artifact": rel(path),
            "source_exists": tf(exists),
            "source_non_empty": tf(exists and path.stat().st_size > 0),
            "source_provider": source_provider(path),
            "source_refresh_allowed": tf(refresh_allowed),
            "ticker_column_available": tf(ticker_available),
            "candidate_rows_found": str(candidate_rows_found),
            "numeric_metric_columns_found": ";".join(sorted(numeric_cols)),
            "non_numeric_metric_columns_rejected": ";".join(sorted(non_numeric_cols)),
            "stale_metric_columns_rejected": "",
            "source_rank_or_score_present": tf(source_rank_present),
            "source_rank_or_score_used_as_fundamental": "FALSE",
            "baseline_rank_used_as_fundamental": "FALSE",
            "fabricated_values_created": "FALSE",
            "source_classification_status": classification,
            "validation_status": validation,
            "validation_reason": reason,
            **safety(),
        })
    return metric_index, audits


def main() -> int:
    refresh_allowed = os.environ.get("ENABLE_FUNDAMENTAL_REFRESH", "").upper() == "TRUE"
    provider = clean(os.environ.get("FUNDAMENTAL_REFRESH_PROVIDER"))
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    candidates = load_candidates()
    metric_index, source_audits = build_metric_index(candidates, refresh_allowed)

    any_local_metrics = any(values for values in metric_index.values())
    refresh_failed = refresh_allowed and not provider and not any_local_metrics
    cache_rows: list[dict[str, str]] = []
    for candidate in candidates:
        ticker = candidate["ticker"]
        metrics = metric_index.get(ticker, {})
        present_count = len(metrics)
        missing_count = len(METRICS) - present_count
        source_paths = sorted({rel(path) for _, path in metrics.values()})
        providers = sorted({source_provider(path) for _, path in metrics.values()})
        if present_count >= MINIMUM_METRIC_THRESHOLD:
            cert = "FUNDAMENTAL_METRICS_CERTIFIED"
        elif present_count > 0:
            cert = "FUNDAMENTAL_METRICS_PARTIAL"
        elif refresh_failed:
            cert = "FUNDAMENTAL_REFRESH_FAILED"
        elif not refresh_allowed:
            cert = "FUNDAMENTAL_REFRESH_NOT_CONFIGURED"
        else:
            cert = "FUNDAMENTAL_METRICS_MISSING"
        row = {
            "ticker": ticker,
            "baseline_rank": candidate.get("baseline_rank", ""),
            "metric_source_status": cert,
            "metric_source_artifact": ";".join(source_paths),
            "metric_source_provider": ";".join(providers) if providers else ("CONFIGURED_PROVIDER_MISSING" if refresh_failed else ""),
            "metric_source_timestamp": "",
            "refresh_timestamp_utc": now,
            "freshness_status": "CURRENT_LOCAL_SOURCE" if present_count else ("REFRESH_FAILED" if refresh_failed else "NO_SOURCE_REFRESH_NOT_CONFIGURED"),
            "missing_metric_count": str(missing_count),
            "present_numeric_metric_count": str(present_count),
            "fundamental_metric_certification_status": cert,
            **safety(extra=True),
        }
        for metric in METRICS:
            row[metric] = metrics.get(metric, ("", Path()))[0] if metric in metrics else ""
        cache_rows.append(row)

    certified_count = sum(1 for row in cache_rows if row["fundamental_metric_certification_status"] == "FUNDAMENTAL_METRICS_CERTIFIED")
    partial_count = sum(1 for row in cache_rows if row["fundamental_metric_certification_status"] == "FUNDAMENTAL_METRICS_PARTIAL")
    failed_count = sum(1 for row in cache_rows if row["fundamental_metric_certification_status"] == "FUNDAMENTAL_REFRESH_FAILED")
    not_configured_count = sum(1 for row in cache_rows if row["fundamental_metric_certification_status"] == "FUNDAMENTAL_REFRESH_NOT_CONFIGURED")
    missing_count = len(cache_rows) - certified_count - partial_count - failed_count - not_configured_count
    threshold_count = certified_count
    ready = certified_count == len(cache_rows) and bool(cache_rows)
    if ready:
        status = PASS_STATUS
        cache_status = "FUNDAMENTAL_METRIC_CACHE_CERTIFIED"
        next_stage = "V20.108-R6B_FUNDAMENTAL_METRIC_TO_CONTRIBUTION_SCORE_BUILDER"
    elif certified_count or partial_count:
        status = PARTIAL_STATUS
        cache_status = "FUNDAMENTAL_METRIC_CACHE_PARTIAL"
        next_stage = "V20.108-R6A_FUNDAMENTAL_METRIC_COVERAGE_REPAIR"
    elif refresh_failed:
        status = BLOCKED_FAILED
        cache_status = "FUNDAMENTAL_REFRESH_FAILED"
        next_stage = "V20.108-R6A_CONFIGURE_VALID_FUNDAMENTAL_PROVIDER"
    else:
        status = BLOCKED_NOT_CONFIGURED
        cache_status = "FUNDAMENTAL_REFRESH_NOT_CONFIGURED"
        next_stage = "V20.108-R6A_CONFIGURE_LOCAL_OR_APPROVED_FUNDAMENTAL_SOURCE"

    cert_rows = [{
        "coverage_check_id": "V20_108_R6A_CERTIFICATION_001",
        "required_candidate_count": str(len(candidates)),
        "candidate_count": str(len(cache_rows)),
        "certified_candidate_count": str(certified_count),
        "partial_candidate_count": str(partial_count),
        "missing_candidate_count": str(missing_count),
        "refresh_not_configured_count": str(not_configured_count),
        "refresh_failed_count": str(failed_count),
        "required_metric_count": str(len(METRICS)),
        "minimum_metric_threshold": str(MINIMUM_METRIC_THRESHOLD),
        "candidates_meeting_minimum_metric_threshold": str(threshold_count),
        "coverage_ratio": f"{(certified_count / len(cache_rows) if cache_rows else 0.0):.10f}",
        "fundamental_metric_cache_status": cache_status,
        "fundamental_score_materialization_ready": tf(ready),
        "recommended_next_stage": next_stage,
        **safety(extra=True),
    }]

    repair_rows = []
    if not ready:
        repair_rows.append({
            "repair_id": "V20_108_R6A_REPAIR_001",
            "blocker_type": cache_status,
            "blocker_reason": "No configured local or approved controlled provider supplied ticker-level numeric fundamental metrics." if not any_local_metrics else "Partial ticker-level numeric fundamental metric coverage.",
            "affected_candidate_count": str(len(cache_rows) - certified_count),
            "affected_metric_group": ";".join(METRIC_GROUPS),
            "required_repair_action": "Provide a trusted local CSV/cache with ticker plus accepted numeric fundamental metric columns, or explicitly configure an approved controlled refresh provider.",
            "acceptable_source_type": "LOCAL_CSV_OR_CACHE;APPROVED_CONTROLLED_REFRESH_PROVIDER",
            "unsafe_action_forbidden": "Do not fabricate metrics, use source_rank_or_score, baseline_rank, proxy values, or create contribution scores in R6A.",
            "recommended_next_stage_after_repair": "V20.108-R6A_CONTROLLED_FUNDAMENTAL_CANDIDATE_METRIC_REFRESH_AND_CACHE_CERTIFICATION_RERUN",
            **safety(),
        })

    write_csv(OUT_CACHE, CACHE_FIELDS, cache_rows)
    write_csv(OUT_AUDIT, AUDIT_FIELDS, source_audits)
    write_csv(OUT_CERT, CERT_FIELDS, cert_rows)
    write_csv(OUT_REPAIR, REPAIR_FIELDS, repair_rows)

    lines = [
        "# V20.108-R6A Controlled Fundamental Metric Refresh Report",
        "",
        "## Current Result",
        f"- wrapper_status: {status}",
        f"- candidate_count: {len(cache_rows)}",
        f"- certified_candidate_count: {certified_count}",
        f"- partial_candidate_count: {partial_count}",
        f"- refresh_not_configured_count: {not_configured_count}",
        f"- refresh_failed_count: {failed_count}",
        "- fundamental_contribution_created: FALSE",
        "- shadow_rerank_output_created: FALSE",
        "- source_rank_or_score_used_as_fundamental: FALSE",
        "- baseline_rank_used_as_fundamental: FALSE",
        "- fabricated_values_created: FALSE",
        "- proxy_values_activated: FALSE",
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
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(status)
    print(f"CANDIDATE_COUNT={len(cache_rows)}")
    print(f"CERTIFIED_CANDIDATE_COUNT={certified_count}")
    print(f"PARTIAL_CANDIDATE_COUNT={partial_count}")
    print(f"REFRESH_NOT_CONFIGURED_COUNT={not_configured_count}")
    print(f"REFRESH_FAILED_COUNT={failed_count}")
    print(f"FUNDAMENTAL_SCORE_MATERIALIZATION_READY={tf(ready)}")
    print("FUNDAMENTAL_CONTRIBUTION_CREATED=FALSE")
    print("SHADOW_RERANK_OUTPUT_CREATED=FALSE")
    print("SOURCE_RANK_OR_SCORE_USED_AS_FUNDAMENTAL=FALSE")
    print("BASELINE_RANK_USED_AS_FUNDAMENTAL=FALSE")
    print("FABRICATED_VALUES_CREATED=FALSE")
    print("PROXY_VALUES_ACTIVATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("IS_OFFICIAL_WEIGHT=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print(f"OUTPUT_CACHE={rel(OUT_CACHE)}")
    print(f"OUTPUT_AUDIT={rel(OUT_AUDIT)}")
    print(f"OUTPUT_CERTIFICATION={rel(OUT_CERT)}")
    print(f"OUTPUT_REPAIR_PLAN={rel(OUT_REPAIR)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
