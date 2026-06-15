#!/usr/bin/env python
"""V20.92 evidence blocker gap resolver.

This research-only resolver reads the V20.89 required path manifest plus the
V20.82-R5 and V20.84-R2 detail outputs. It creates a precise category-level
gap table for the next evidence fixes without mutating upstream artifacts.
"""

from __future__ import annotations

import csv
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "outputs" / "v20" / "evidence"

PASS_STATUS = "PASS_V20_92_EVIDENCE_BLOCKER_GAP_RESOLVER_CREATED"

REQUIRED_MANIFEST = EVIDENCE / "V20_CURRENT_REQUIRED_EVIDENCE_PATH_MANIFEST.csv"
V20_82_R5_DETAIL = EVIDENCE / "V20_CURRENT_MULTI_PATH_VALIDATION_DETAIL.csv"
V20_84_R2_DETAIL = EVIDENCE / "V20_CURRENT_REQUIRED_PATH_INTEGRATION_DETAIL.csv"
V20_90_ETF = EVIDENCE / "V20_CURRENT_ETF_ROTATION_EVIDENCE_TABLE.csv"
V20_91_MULTI_WINDOW = EVIDENCE / "V20_CURRENT_MULTI_WINDOW_STRATEGY_EVIDENCE_MATRIX.csv"

VERSIONED_RESOLVER = EVIDENCE / "V20_92_EVIDENCE_BLOCKER_GAP_RESOLVER.csv"
VERSIONED_SUMMARY = EVIDENCE / "V20_92_EVIDENCE_BLOCKER_GAP_RESOLVER_SUMMARY.md"
CURRENT_RESOLVER = EVIDENCE / "V20_CURRENT_EVIDENCE_BLOCKER_GAP_RESOLVER.csv"
CURRENT_SUMMARY = EVIDENCE / "V20_CURRENT_EVIDENCE_BLOCKER_GAP_RESOLVER_SUMMARY.md"

REQUIRED_COLUMNS = [
    "category",
    "manifest_status",
    "v20_82_validation_status",
    "v20_84_integration_status",
    "blocker_status",
    "blocker_reason",
    "missing_source_file",
    "missing_alias",
    "missing_schema_fields",
    "missing_certification",
    "missing_row_count",
    "missing_unique_ticker_count",
    "missing_benchmark_count",
    "missing_regime_count",
    "recommended_next_stage",
    "recommended_fix_type",
    "blocking_if_missing",
    "research_only",
    "official_recommendation_created",
    "official_weight_mutated",
    "trade_action_created",
]

PATH_ID_TO_CATEGORY = {
    "certified_etf_rotation_evidence": "etf_rotation_evidence",
    "multi_window_strategy_evidence": "multi_window_strategy_evidence",
    "regime_conditioned_evidence": "regime_conditioned_evidence",
    "downside_risk_evidence": "downside_risk_evidence",
    "benchmark_comparison_evidence": "benchmark_comparison_evidence",
    "score_lineage_evidence": "score_lineage_evidence",
    "ranking_delta_diagnostic_evidence": "ranking_delta_diagnostic_evidence",
    "acceptance_proof_evidence": "acceptance_proof_evidence",
}

NEXT_STAGE_BY_CATEGORY = {
    "etf_rotation_evidence": "V20.90_ETF_ROTATION_EVIDENCE_BUILDER",
    "multi_window_strategy_evidence": "V20.91_MULTI_WINDOW_STRATEGY_EVIDENCE_MATRIX",
    "regime_conditioned_evidence": "V20.86_REGIME_CONDITIONED_EVIDENCE_EXPORT",
    "downside_risk_evidence": "V20.87_DOWNSIDE_RISK_EVIDENCE_EXPORT",
    "benchmark_comparison_evidence": "V20.88_BENCHMARK_COMPARISON_EVIDENCE_EXPORT",
    "score_lineage_evidence": "V20.83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_EXPORT",
    "ranking_delta_diagnostic_evidence": "V20.82_RANKING_DELTA_DIAGNOSTIC_SCHEMA_REPAIR",
    "acceptance_proof_evidence": "V20.82_ACCEPTANCE_PROOF_SCHEMA_REPAIR",
}


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    if not path.exists():
        return [], [], "MISSING_FILE"
    if path.stat().st_size == 0:
        return [], [], "EMPTY_FILE"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            return [dict(row) for row in reader], list(reader.fieldnames or []), "OK"
    except csv.Error:
        return [], [], "MALFORMED_CSV"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def normalize_detail_status(value: str) -> str:
    text = clean(value).upper()
    if text in {"PASSED", "INTEGRATED", "PASS"}:
        return "PASS"
    if text == "WARN":
        return "WARN"
    if text == "BLOCKED":
        return "BLOCKED"
    return "BLOCKED" if not text else text


def manifest_index(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {clean(row.get("path_id")): row for row in rows if clean(row.get("path_id"))}


def r5_index(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {clean(row.get("validation_category")): row for row in rows if clean(row.get("validation_category"))}


def r2_index(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {clean(row.get("integration_category")): row for row in rows if clean(row.get("integration_category"))}


def combined_blocker_status(manifest_row: dict[str, str], r5_row: dict[str, str], r2_row: dict[str, str]) -> str:
    statuses = [
        normalize_detail_status(clean(r5_row.get("validation_status"))),
        normalize_detail_status(clean(r2_row.get("integration_status"))),
    ]
    manifest_status = clean(manifest_row.get("current_status")).upper()
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if "WARN" in statuses or manifest_status == "WARN":
        return "WARN"
    return "PASS"


def joined_reason(manifest_row: dict[str, str], r5_row: dict[str, str], r2_row: dict[str, str], status: str) -> str:
    reasons = [
        clean(r2_row.get("integration_blocker_reason")),
        clean(r5_row.get("category_blocker_reason")),
        clean(manifest_row.get("missing_reason")),
    ]
    useful = [reason for reason in reasons if reason and reason != "NA"]
    if useful:
        return " | ".join(dict.fromkeys(useful))
    return "NA" if status == "PASS" else "UNCLASSIFIED_EVIDENCE_GAP"


def missing_schema_fields(reason: str) -> str:
    marker = "MISSING_SCHEMA_FIELDS:"
    if marker not in reason:
        return "NA"
    return reason.split(marker, 1)[1].split(" | ", 1)[0]


def recommended_fix_type(reason: str, status: str) -> str:
    upper = reason.upper()
    if status == "PASS":
        return "NO_FIX_REQUIRED"
    if "MISSING_REQUIRED_PATH" in upper or "MISSING_FILE" in upper or "MISSING_ALIAS" in upper:
        return "SOURCE_PATH_GAP"
    if "CERTIFICATION" in upper and "MISSING_SCHEMA_FIELDS" not in upper:
        return "CERTIFICATION_GAP"
    if any(token in upper for token in ["INSUFFICIENT", "PARTIAL", "NO_ATTACHED_ROWS", "ROW_COUNT", "UNIQUE_TICKER", "BENCHMARK_COUNT", "REGIME_COUNT"]):
        return "COVERAGE_GAP"
    if "MISSING_SCHEMA_FIELDS" in upper:
        return "SCHEMA_GAP"
    return "COVERAGE_GAP" if status in {"WARN", "BLOCKED"} else "NO_FIX_REQUIRED"


def build_rows() -> list[dict[str, str]]:
    manifest_rows, _, _manifest_status = read_csv(REQUIRED_MANIFEST)
    r5_rows, _, _r5_status = read_csv(V20_82_R5_DETAIL)
    r2_rows, _, _r2_status = read_csv(V20_84_R2_DETAIL)
    manifests = manifest_index(manifest_rows)
    r5 = r5_index(r5_rows)
    r2 = r2_index(r2_rows)
    output: list[dict[str, str]] = []

    for path_id, category in PATH_ID_TO_CATEGORY.items():
        manifest_row = manifests.get(path_id, {})
        r5_row = r5.get(category, {})
        r2_row = r2.get(category, {})
        status = combined_blocker_status(manifest_row, r5_row, r2_row)
        reason = joined_reason(manifest_row, r5_row, r2_row, status)
        fix_type = recommended_fix_type(reason, status)
        missing_file_reason = status in {"WARN", "BLOCKED"} and fix_type == "SOURCE_PATH_GAP"
        missing_cert = status in {"WARN", "BLOCKED"} and fix_type == "CERTIFICATION_GAP"
        missing_schema = missing_schema_fields(reason)
        attached = int(clean(r2_row.get("attached_row_count") or r5_row.get("attached_row_count") or "0") or 0)
        certified = int(clean(r2_row.get("certified_row_count") or r5_row.get("certified_row_count") or "0") or 0)
        output.append(
            {
                "category": category,
                "manifest_status": clean(manifest_row.get("current_status")) or "MISSING_MANIFEST_ROW",
                "v20_82_validation_status": clean(r5_row.get("validation_status")) or "MISSING_V20_82_R5_ROW",
                "v20_84_integration_status": clean(r2_row.get("integration_status")) or "MISSING_V20_84_R2_ROW",
                "blocker_status": status,
                "blocker_reason": reason,
                "missing_source_file": tf(missing_file_reason and not Path(ROOT / clean(manifest_row.get("expected_source_file"))).exists()),
                "missing_alias": tf(missing_file_reason and not Path(ROOT / clean(manifest_row.get("expected_current_alias"))).exists()),
                "missing_schema_fields": missing_schema,
                "missing_certification": tf(missing_cert or (status in {"WARN", "BLOCKED"} and attached > 0 and certified == 0 and missing_schema == "NA")),
                "missing_row_count": tf("ROW_COUNT" in reason.upper() or "NO_ATTACHED_ROWS" in reason.upper()),
                "missing_unique_ticker_count": tf("UNIQUE_TICKER" in reason.upper()),
                "missing_benchmark_count": tf("BENCHMARK_COUNT" in reason.upper()),
                "missing_regime_count": tf("REGIME_COUNT" in reason.upper()),
                "recommended_next_stage": NEXT_STAGE_BY_CATEGORY[category],
                "recommended_fix_type": fix_type,
                "blocking_if_missing": clean(manifest_row.get("blocking_if_missing")) or ("FALSE" if clean(manifest_row.get("required_level")) == "OPTIONAL" else "TRUE"),
                "research_only": "TRUE",
                "official_recommendation_created": "FALSE",
                "official_weight_mutated": "FALSE",
                "trade_action_created": "FALSE",
            }
        )
    return output


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def summary_text(rows: list[dict[str, str]], created_at: str) -> str:
    pass_count = sum(row["blocker_status"] == "PASS" for row in rows)
    warn_count = sum(row["blocker_status"] == "WARN" for row in rows)
    blocked_count = sum(row["blocker_status"] == "BLOCKED" for row in rows)
    blocked = [row["category"] for row in rows if row["blocker_status"] == "BLOCKED"]
    stages = sorted({row["recommended_next_stage"] for row in rows if row["blocker_status"] in {"WARN", "BLOCKED"}})
    return "\n".join(
        [
            "# V20.92 Evidence Blocker Gap Resolver Summary",
            "",
            f"- final_status: {PASS_STATUS}",
            f"- created_at_utc: {created_at}",
            f"- pass_count: {pass_count}",
            f"- warn_count: {warn_count}",
            f"- blocked_count: {blocked_count}",
            f"- blocked_categories: {'|'.join(blocked) if blocked else 'NONE'}",
            f"- recommended_next_stages: {'|'.join(stages) if stages else 'NONE'}",
            "- research_only: TRUE",
            "- official_recommendation_created: FALSE",
            "- official_weight_mutated: FALSE",
            "- trade_action_created: FALSE",
            "",
        ]
    )


def write_outputs(rows: list[dict[str, str]]) -> None:
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_csv(VERSIONED_RESOLVER, rows)
    VERSIONED_SUMMARY.write_text(summary_text(rows, created_at), encoding="utf-8")
    shutil.copyfile(VERSIONED_RESOLVER, CURRENT_RESOLVER)
    shutil.copyfile(VERSIONED_SUMMARY, CURRENT_SUMMARY)


def main() -> int:
    rows = build_rows()
    write_outputs(rows)
    print(PASS_STATUS)
    print(f"PASS_COUNT={sum(row['blocker_status'] == 'PASS' for row in rows)}")
    print(f"WARN_COUNT={sum(row['blocker_status'] == 'WARN' for row in rows)}")
    print(f"BLOCKED_COUNT={sum(row['blocker_status'] == 'BLOCKED' for row in rows)}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("OFFICIAL_WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
