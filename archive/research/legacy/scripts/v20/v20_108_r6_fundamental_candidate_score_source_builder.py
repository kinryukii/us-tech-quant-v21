#!/usr/bin/env python
"""V20.108-R6 fundamental candidate score source builder.

Discovers and materializes research-only ticker-level FUNDAMENTAL contribution
scores only when real numeric fundamental source columns exist. If no safe
source exists, it preserves all candidates with blank contributions and an
explicit blocker classification.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R5_STAGE_PLAN = CONSOLIDATION / "V20_108_R5_MISSING_UPSTREAM_FACTOR_SCORE_STAGE_PLAN.csv"
R5_GAP_MAP = CONSOLIDATION / "V20_108_R5_FACTOR_FAMILY_GAP_TO_STAGE_MAP.csv"
R5_SOURCE_REQ = CONSOLIDATION / "V20_108_R5_UPSTREAM_SOURCE_REQUIREMENT_AUDIT.csv"
R5_RESOLUTION = CONSOLIDATION / "V20_108_R5_SHADOW_RERANK_BLOCKER_RESOLUTION_PLAN.csv"
R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
R4_COVERAGE = CONSOLIDATION / "V20_108_R4_CANDIDATE_CONTRIBUTION_COVERAGE_AFTER_MATERIALIZATION.csv"
R3_PLAN = CONSOLIDATION / "V20_108_R3_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZATION_PLAN.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V48_FACTORS = CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv"
V50_CANDIDATES = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
V50_FACTORS = CONSOLIDATION / "V20_50_FACTOR_RESEARCH_CONTEXT_PACKET.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_SOURCE = CONSOLIDATION / "V20_108_R6_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE.csv"
OUT_COLUMN_AUDIT = CONSOLIDATION / "V20_108_R6_FUNDAMENTAL_SOURCE_COLUMN_AUDIT.csv"
OUT_MATERIAL_AUDIT = CONSOLIDATION / "V20_108_R6_FUNDAMENTAL_SCORE_MATERIALIZATION_AUDIT.csv"
OUT_COVERAGE = CONSOLIDATION / "V20_108_R6_FUNDAMENTAL_COVERAGE_AFTER_BUILD.csv"
REPORT = READ_CENTER / "V20_108_R6_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE_REPORT.md"

PASS_STATUS = "PASS_V20_108_R6_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE_BUILDER"
PARTIAL_STATUS = "PARTIAL_PASS_V20_108_R6_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE_BUILDER_WITH_PARTIAL_COVERAGE"
BLOCKED_STATUS = "BLOCKED_V20_108_R6_NO_SAFE_FUNDAMENTAL_CANDIDATE_SOURCE_FOUND"

SOURCE_FIELDS = [
    "ticker", "baseline_rank", "fundamental_contribution",
    "fundamental_raw_columns_used", "fundamental_normalization_method",
    "fundamental_source_artifact", "fundamental_source_stage",
    "fundamental_source_status", "fundamental_materialization_status",
    "missing_reason", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "is_official_ranking", "is_official_weight",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]

COLUMN_AUDIT_FIELDS = [
    "source_artifact", "source_exists", "source_non_empty", "ticker_column_available",
    "candidate_rows_found", "detected_fundamental_numeric_columns",
    "detected_family_level_only_columns", "rejected_columns", "rejection_reason",
    "source_rank_or_score_present", "source_rank_or_score_used_as_fundamental",
    "materialization_allowed", "materialization_blocker_reason", "validation_status",
    "validation_reason", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]

MATERIAL_AUDIT_FIELDS = [
    "factor_family", "candidate_count", "materialization_attempted",
    "materialized_candidate_count", "missing_candidate_count",
    "source_artifacts_used", "source_columns_used", "normalization_method",
    "used_source_rank_or_score", "used_baseline_rank", "used_proxy",
    "fabricated_values_created", "materialization_status", "validation_status",
    "validation_reason", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]

COVERAGE_FIELDS = [
    "factor_family", "required_candidate_count", "materialized_candidate_count",
    "missing_candidate_count", "coverage_ratio", "contribution_coverage_status",
    "usable_for_shadow_rerank", "missing_reason", "recommended_next_stage",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]

FUNDAMENTAL_TERMS = [
    "fundamental", "valuation", "profit", "margin", "growth", "cash_flow",
    "cashflow", "free_cash", "capex", "liquidity", "balance", "debt",
    "revenue", "earnings", "ebit", "ebitda", "pe_ratio", "p_e",
    "price_to", "book", "sales", "roe", "roa", "roic", "gross_margin",
    "operating_margin",
]
REJECTED_RANK_COLUMNS = {"source_rank_or_score", "baseline_rank", "rank", "report_rank", "factor_pack_rank"}
TICKER_COLUMNS = ("ticker", "normalized_ticker", "ticker_or_candidate_id", "display_name_or_ticker", "symbol")


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


def fmt(value: float) -> str:
    return f"{value:.10f}"


def ticker_value(row: dict[str, str]) -> str:
    for key in TICKER_COLUMNS:
        if clean(row.get(key)):
            return clean(row.get(key))
    return ""


def source_stage(path: Path) -> str:
    name = path.name
    if name.startswith("V20_"):
        parts = name.split("_", 2)
        return f"{parts[0]}.{parts[1]}" if len(parts) > 1 else "V20"
    if name.startswith("V18_"):
        return "V18"
    if name.startswith("V19_"):
        return "V19"
    return "DISCOVERED"


def discover_sources() -> list[Path]:
    seeds = [
        R5_STAGE_PLAN, R5_GAP_MAP, R5_SOURCE_REQ, R5_RESOLUTION, R4_SCORES,
        R4_COVERAGE, R3_PLAN, V48_CANDIDATES, V48_FACTORS, V50_CANDIDATES,
        V50_FACTORS, V49_RESEARCH, V49_OFFICIAL,
    ]
    found: list[Path] = []
    for root_pattern in (
        (CONSOLIDATION, "*FUNDAMENTAL*.csv"),
        (ROOT / "outputs" / "v20" / "evidence", "*FUNDAMENTAL*.csv"),
    ):
        root, pattern = root_pattern
        if root.exists():
            found.extend(root.glob(pattern))
    for root in (ROOT / "outputs" / "v19", ROOT / "outputs" / "v18", ROOT / "outputs" / "backtest", ROOT / "data", ROOT / "cache"):
        if root.exists():
            found.extend(root.rglob("*.csv"))
    excluded = {OUT_SOURCE.resolve(), OUT_COLUMN_AUDIT.resolve(), OUT_MATERIAL_AUDIT.resolve(), OUT_COVERAGE.resolve()}
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


def is_fundamental_column(column: str) -> bool:
    name = column.lower()
    if name in REJECTED_RANK_COLUMNS:
        return False
    if name == "fundamental_contribution":
        return True
    return any(term in name for term in FUNDAMENTAL_TERMS)


def normalize(values: dict[str, list[tuple[float, Path, str]]]) -> dict[str, tuple[float, Path, str]]:
    raw = {
        ticker: (sum(v for v, _, _ in items) / len(items), items[0][1], ";".join(sorted({col for _, _, col in items})))
        for ticker, items in values.items()
        if items
    }
    if not raw:
        return {}
    nums = [v for v, _, _ in raw.values()]
    low, high = min(nums), max(nums)
    if high == low:
        return {ticker: (1.0, path, cols) for ticker, (_, path, cols) in raw.items()}
    return {ticker: ((value - low) / (high - low), path, cols) for ticker, (value, path, cols) in raw.items()}


def main() -> int:
    candidates, _, _ = read_csv(R4_SCORES)
    candidate_tickers = {row["ticker"] for row in candidates if row.get("ticker")}
    raw_values: dict[str, list[tuple[float, Path, str]]] = defaultdict(list)
    column_audits: list[dict[str, str]] = []

    for path in discover_sources():
        rows, status, fields = read_csv(path)
        exists = path.exists()
        ticker_available = any(field in fields for field in TICKER_COLUMNS)
        source_rank_present = "source_rank_or_score" in fields
        candidate_rows_found = 0
        rejected = [field for field in fields if field in REJECTED_RANK_COLUMNS]
        family_level_cols = [field for field in fields if field in {"factor_family", "factor_category"} and not ticker_available]
        detected_cols: list[str] = []
        if status == "OK" and rows and ticker_available:
            for row in rows:
                ticker = ticker_value(row)
                if ticker not in candidate_tickers:
                    continue
                candidate_rows_found += 1
                for field in fields:
                    if not is_fundamental_column(field):
                        continue
                    value = num(row.get(field))
                    if value is None:
                        continue
                    raw_values[ticker].append((value, path, field))
                    if field not in detected_cols:
                        detected_cols.append(field)
        allowed = bool(detected_cols)
        if allowed:
            blocker = ""
            rejection_reason = ""
            classification_reason = "REAL_TICKER_LEVEL_NUMERIC_FUNDAMENTAL_COLUMNS_FOUND"
        elif family_level_cols:
            blocker = "FAMILY_LEVEL_ONLY_NOT_CANDIDATE_MATERIALIZABLE"
            rejection_reason = "FAMILY_LEVEL_ONLY_NOT_TICKER_LEVEL"
            classification_reason = blocker
        else:
            blocker = "NO_REAL_TICKER_LEVEL_NUMERIC_FUNDAMENTAL_COLUMNS"
            rejection_reason = "NO_SAFE_FUNDAMENTAL_CANDIDATE_LEVEL_NUMERIC_COLUMNS"
            classification_reason = blocker
        column_audits.append({
            "source_artifact": rel(path),
            "source_exists": tf(exists),
            "source_non_empty": tf(exists and path.stat().st_size > 0),
            "ticker_column_available": tf(ticker_available),
            "candidate_rows_found": str(candidate_rows_found),
            "detected_fundamental_numeric_columns": ";".join(sorted(detected_cols)),
            "detected_family_level_only_columns": ";".join(family_level_cols),
            "rejected_columns": ";".join(sorted(set(rejected))),
            "rejection_reason": rejection_reason,
            "source_rank_or_score_present": tf(source_rank_present),
            "source_rank_or_score_used_as_fundamental": "FALSE",
            "materialization_allowed": tf(allowed),
            "materialization_blocker_reason": blocker,
            "validation_status": "PASS",
            "validation_reason": classification_reason,
            **safety(),
        })

    normalized = normalize(raw_values)
    score_rows: list[dict[str, str]] = []
    for candidate in candidates:
        ticker = candidate.get("ticker", "")
        if ticker in normalized:
            value, source_path, columns = normalized[ticker]
            contribution = fmt(value)
            source_artifact = rel(source_path)
            stage = source_stage(source_path)
            source_status = "REAL_TICKER_LEVEL_NUMERIC_FUNDAMENTAL_SOURCE"
            material_status = "MATERIALIZED_REAL_FUNDAMENTAL_CONTRIBUTION"
            missing_reason = ""
            norm_method = "MIN_MAX_NORMALIZED_AVERAGE_OF_REAL_NUMERIC_FUNDAMENTAL_COLUMNS"
        else:
            contribution = ""
            columns = ""
            source_artifact = ""
            stage = ""
            source_status = "MISSING_CANDIDATE_LEVEL_FUNDAMENTAL_SOURCE"
            material_status = "NOT_MATERIALIZED"
            missing_reason = "MISSING_CANDIDATE_LEVEL_FUNDAMENTAL_SOURCE"
            norm_method = "NO_FUNDAMENTAL_SOURCE_TO_NORMALIZE"
        score_rows.append({
            "ticker": ticker,
            "baseline_rank": candidate.get("baseline_rank", ""),
            "fundamental_contribution": contribution,
            "fundamental_raw_columns_used": columns,
            "fundamental_normalization_method": norm_method,
            "fundamental_source_artifact": source_artifact,
            "fundamental_source_stage": stage,
            "fundamental_source_status": source_status,
            "fundamental_materialization_status": material_status,
            "missing_reason": missing_reason,
            **safety(extra=True),
        })

    materialized = sum(1 for row in score_rows if row["fundamental_contribution"])
    total = len(score_rows)
    missing = total - materialized
    ratio = materialized / total if total else 0.0
    if materialized == total and total:
        status = PASS_STATUS
        coverage_status = "COMPLETE"
        missing_reason = ""
        next_stage = "V20.108-R7_STRATEGY_CANDIDATE_SCORE_SOURCE_BUILDER"
    elif materialized > 0:
        status = PARTIAL_STATUS
        coverage_status = "PARTIAL"
        missing_reason = "PARTIAL_REAL_TICKER_LEVEL_FUNDAMENTAL_SOURCE_COVERAGE"
        next_stage = "V20.108-R6_FUNDAMENTAL_SOURCE_COVERAGE_REPAIR"
    else:
        status = BLOCKED_STATUS
        coverage_status = "MISSING"
        missing_reason = "MISSING_CANDIDATE_LEVEL_FUNDAMENTAL_SOURCE"
        next_stage = "V20.108-R6_FUNDAMENTAL_UPSTREAM_SOURCE_REPAIR_REQUIRED"

    material_audit = [{
        "factor_family": "FUNDAMENTAL",
        "candidate_count": str(total),
        "materialization_attempted": tf(materialized > 0),
        "materialized_candidate_count": str(materialized),
        "missing_candidate_count": str(missing),
        "source_artifacts_used": ";".join(sorted({row["fundamental_source_artifact"] for row in score_rows if row["fundamental_source_artifact"]})),
        "source_columns_used": ";".join(sorted({col for row in score_rows for col in row["fundamental_raw_columns_used"].split(";") if col})),
        "normalization_method": "MIN_MAX_NORMALIZED_AVERAGE_OF_REAL_NUMERIC_FUNDAMENTAL_COLUMNS" if materialized else "NO_NORMALIZATION_NO_SAFE_SOURCE",
        "used_source_rank_or_score": "FALSE",
        "used_baseline_rank": "FALSE",
        "used_proxy": "FALSE",
        "fabricated_values_created": "FALSE",
        "materialization_status": coverage_status,
        "validation_status": "PASS" if materialized else "BLOCKED",
        "validation_reason": "REAL_TICKER_LEVEL_FUNDAMENTAL_COLUMNS_ONLY" if materialized else "NO_SAFE_FUNDAMENTAL_CANDIDATE_SOURCE_FOUND",
        **safety(),
    }]
    coverage_rows = [{
        "factor_family": "FUNDAMENTAL",
        "required_candidate_count": str(total),
        "materialized_candidate_count": str(materialized),
        "missing_candidate_count": str(missing),
        "coverage_ratio": fmt(ratio),
        "contribution_coverage_status": coverage_status,
        "usable_for_shadow_rerank": tf(materialized == total and total > 0),
        "missing_reason": missing_reason,
        "recommended_next_stage": next_stage,
        **safety(),
    }]

    write_csv(OUT_SOURCE, SOURCE_FIELDS, score_rows)
    write_csv(OUT_COLUMN_AUDIT, COLUMN_AUDIT_FIELDS, column_audits)
    write_csv(OUT_MATERIAL_AUDIT, MATERIAL_AUDIT_FIELDS, material_audit)
    write_csv(OUT_COVERAGE, COVERAGE_FIELDS, coverage_rows)

    lines = [
        "# V20.108-R6 Fundamental Candidate Score Source Builder",
        "",
        "## Current Result",
        f"- wrapper_status: {status}",
        f"- candidate_count: {total}",
        f"- materialized_candidate_count: {materialized}",
        f"- missing_candidate_count: {missing}",
        "- source_rank_or_score_used_as_fundamental: FALSE",
        "- baseline_rank_used_as_fundamental: FALSE",
        "- proxy_values_activated: FALSE",
        "- fabricated_values_created: FALSE",
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
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(status)
    print(f"CANDIDATE_COUNT={total}")
    print(f"MATERIALIZED_CANDIDATE_COUNT={materialized}")
    print(f"MISSING_CANDIDATE_COUNT={missing}")
    print("SOURCE_RANK_OR_SCORE_USED_AS_FUNDAMENTAL=FALSE")
    print("BASELINE_RANK_USED_AS_FUNDAMENTAL=FALSE")
    print("PROXY_VALUES_ACTIVATED=FALSE")
    print("FABRICATED_VALUES_CREATED=FALSE")
    print("SHADOW_RERANK_OUTPUT_CREATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print(f"OUTPUT_SCORE_SOURCE={rel(OUT_SOURCE)}")
    print(f"OUTPUT_COLUMN_AUDIT={rel(OUT_COLUMN_AUDIT)}")
    print(f"OUTPUT_MATERIALIZATION_AUDIT={rel(OUT_MATERIAL_AUDIT)}")
    print(f"OUTPUT_COVERAGE={rel(OUT_COVERAGE)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
