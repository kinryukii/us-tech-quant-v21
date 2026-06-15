#!/usr/bin/env python
"""V20.94 evidence chain closure and promotion preflight gate.

Research-only gate that confirms V20.93/V20.82-R5/V20.84-R2 closed the
required evidence chain, while keeping all promotion and trading paths blocked.
"""

from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "outputs" / "v20" / "evidence"
OPS = ROOT / "outputs" / "v20" / "ops"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

PASS_STATUS = "PASS_EVIDENCE_CHAIN_CLOSED_PROMOTION_STILL_BLOCKED"
BLOCKED_RESEARCH_ONLY_STATUS = "BLOCKED_PROMOTION_PREFLIGHT_RESEARCH_ONLY"
BLOCKED_MULTI_RUN_STATUS = "BLOCKED_INSUFFICIENT_MULTI_RUN_HISTORY"
BLOCKED_OFFICIAL_RECOMMENDATION_STATUS = "BLOCKED_OFFICIAL_RECOMMENDATION_NOT_READY"
BLOCKED_DYNAMIC_WEIGHT_STATUS = "BLOCKED_DYNAMIC_WEIGHT_NOT_PROMOTED"
BLOCKED_EVIDENCE_CHAIN_STATUS = "BLOCKED_REQUIRED_EVIDENCE_CATEGORY_MISSING"

V20_93_REPAIR_DETAIL = EVIDENCE / "V20_CURRENT_EVIDENCE_SCHEMA_REPAIR_DETAIL.csv"
V20_93_REPAIR_SUMMARY = EVIDENCE / "V20_CURRENT_EVIDENCE_SCHEMA_REPAIR_SUMMARY.md"
V20_82_R5_DETAIL = EVIDENCE / "V20_CURRENT_MULTI_PATH_VALIDATION_DETAIL.csv"
V20_82_R5_MANIFEST = OPS / "V20_CURRENT_MULTI_PATH_STRATEGY_BENCHMARK_VALIDATION_MANIFEST.json"
V20_84_R2_DETAIL = EVIDENCE / "V20_CURRENT_REQUIRED_PATH_INTEGRATION_DETAIL.csv"
V20_84_R2_MANIFEST = OPS / "V20_CURRENT_CERTIFIED_MULTI_PATH_EVIDENCE_EXPORT_MANIFEST.json"

DETAIL = EVIDENCE / "V20_94_EVIDENCE_CHAIN_CLOSURE_PROMOTION_PREFLIGHT_DETAIL.csv"
SUMMARY = EVIDENCE / "V20_94_EVIDENCE_CHAIN_CLOSURE_PROMOTION_PREFLIGHT_SUMMARY.md"
DETAIL_ALIAS = EVIDENCE / "V20_CURRENT_EVIDENCE_CHAIN_CLOSURE_PROMOTION_PREFLIGHT_DETAIL.csv"
SUMMARY_ALIAS = EVIDENCE / "V20_CURRENT_EVIDENCE_CHAIN_CLOSURE_PROMOTION_PREFLIGHT_SUMMARY.md"

REQUIRED_EVIDENCE_COUNTS = {
    "regime_conditioned_evidence": 24,
    "downside_risk_evidence": 24,
    "benchmark_comparison_evidence": 24,
    "acceptance_proof_evidence": 2,
}
OPTIONAL_EVIDENCE_COUNTS = {
    "ranking_delta_diagnostic_evidence": 40,
}
COUNT_FIELD_BY_CATEGORY = {
    "ranking_delta_diagnostic_evidence": "attached_row_count",
}

PREFLIGHT_INPUTS = {
    "multi_run_history_sufficiency": [
        CONSOLIDATION / "V20_64_MULTI_RUN_EVIDENCE_ACCUMULATION_SUMMARY.csv",
        EVIDENCE / "V20_CURRENT_MULTI_RUN_EVIDENCE_ACCUMULATION_SUMMARY.csv",
    ],
    "rolling_evidence_ledger_sufficiency": [
        CONSOLIDATION / "V20_58_ROLLING_EVIDENCE_LEDGER.csv",
        EVIDENCE / "V20_CURRENT_ROLLING_EVIDENCE_LEDGER.csv",
    ],
    "shadow_feedback_stability": [
        CONSOLIDATION / "V20_64_SHADOW_FEEDBACK_STABILITY_TABLE.csv",
        EVIDENCE / "V20_CURRENT_SHADOW_FEEDBACK_STABILITY_TABLE.csv",
    ],
    "candidate_dynamic_weight_promotion_readiness": [
        CONSOLIDATION / "V20_66_CANDIDATE_WEIGHT_UPDATE_DRY_RUN.csv",
        EVIDENCE / "V20_CURRENT_CANDIDATE_WEIGHT_UPDATE_DRY_RUN.csv",
    ],
    "official_recommendation_readiness": [
        CONSOLIDATION / "V20_51_OFFICIAL_RECOMMENDATION_READINESS.csv",
        EVIDENCE / "V20_CURRENT_OFFICIAL_RECOMMENDATION_READINESS.csv",
    ],
    "promotion_readiness": [
        CONSOLIDATION / "V20_65_PROPOSAL_PROMOTION_READINESS_GATE.csv",
        EVIDENCE / "V20_CURRENT_PROPOSAL_PROMOTION_READINESS_GATE.csv",
    ],
}

DETAIL_FIELDS = [
    "record_type",
    "check_name",
    "required_level",
    "source_file",
    "source_status",
    "readable_count",
    "minimum_required_count",
    "check_status",
    "blocker_active",
    "blocker_reason",
    "evidence_chain_closure_status",
    "promotion_preflight_status",
    "research_only",
    "promotion_allowed",
    "nasdaq_hurdle_passed",
    "official_recommendation_created",
    "official_weight_mutated",
    "trade_action_created",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    if not path.exists():
        return [], [], "MISSING_FILE"
    if path.stat().st_size == 0:
        return [], [], "EMPTY_FILE"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            rows = [{key: clean(value) for key, value in row.items()} for row in reader]
    except csv.Error:
        return [], [], "MALFORMED_CSV"
    if not fields:
        return [], [], "MALFORMED_CSV"
    return rows, fields, "OK"


def read_json(path: Path) -> tuple[dict[str, object], str]:
    if not path.exists():
        return {}, "MISSING_FILE"
    if path.stat().st_size == 0:
        return {}, "EMPTY_FILE"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}, "MALFORMED_JSON"
    return (payload, "OK") if isinstance(payload, dict) else ({}, "MALFORMED_JSON")


def index_by(rows: list[dict[str, str]], field: str) -> dict[str, dict[str, str]]:
    return {clean(row.get(field)): row for row in rows if clean(row.get(field))}


def int_value(value: object) -> int:
    try:
        return int(clean(value) or "0")
    except ValueError:
        return 0


def safety_flags() -> dict[str, str]:
    return {
        "research_only": "TRUE",
        "promotion_allowed": "FALSE",
        "nasdaq_hurdle_passed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
    }


def base_row(record_type: str, check_name: str, required_level: str, source_file: str, source_status: str, readable_count: int, minimum: int, status: str, blocker: bool, reason: str) -> dict[str, str]:
    row = {
        "record_type": record_type,
        "check_name": check_name,
        "required_level": required_level,
        "source_file": source_file,
        "source_status": source_status,
        "readable_count": str(readable_count),
        "minimum_required_count": str(minimum),
        "check_status": status,
        "blocker_active": tf(blocker),
        "blocker_reason": reason,
        "evidence_chain_closure_status": "",
        "promotion_preflight_status": "",
    }
    row.update(safety_flags())
    return row


def detail_count(row: dict[str, str], category: str) -> int:
    field = COUNT_FIELD_BY_CATEGORY.get(category, "certified_row_count")
    return int_value(row.get(field))


def manifest_missing_required(manifest: dict[str, object]) -> list[str]:
    value = manifest.get("missing_required_evidence_categories")
    if isinstance(value, list):
        return [clean(item) for item in value if clean(item)]
    if isinstance(value, str):
        return [] if value in {"", "NONE", "[]"} else [item for item in value.split("|") if item]
    return []


def build_evidence_rows(
    r5_detail_path: Path = V20_82_R5_DETAIL,
    r2_detail_path: Path = V20_84_R2_DETAIL,
    r5_manifest_path: Path = V20_82_R5_MANIFEST,
    r2_manifest_path: Path = V20_84_R2_MANIFEST,
    repair_detail_path: Path = V20_93_REPAIR_DETAIL,
    repair_summary_path: Path = V20_93_REPAIR_SUMMARY,
) -> tuple[list[dict[str, str]], str, list[str], dict[str, int]]:
    r5_rows, _, r5_status = read_csv(r5_detail_path)
    r2_rows, _, r2_status = read_csv(r2_detail_path)
    repair_rows, _, repair_status = read_csv(repair_detail_path)
    repair_summary_status = "OK" if repair_summary_path.exists() and repair_summary_path.stat().st_size > 0 else "MISSING_FILE"
    r5_manifest, r5_manifest_status = read_json(r5_manifest_path)
    r2_manifest, r2_manifest_status = read_json(r2_manifest_path)
    r5 = index_by(r5_rows, "validation_category")
    r2 = index_by(r2_rows, "integration_category")
    rows: list[dict[str, str]] = []
    missing_required: list[str] = []
    counts: dict[str, int] = {}

    r5_passed = r5_manifest_status == "OK" and clean(r5_manifest.get("status")) == "PASS_V20_82_R5_MULTI_PATH_EVIDENCE_VALIDATED"
    r2_passed = r2_manifest_status == "OK" and clean(r2_manifest.get("status")) == "PASS_V20_84_R2_REQUIRED_EVIDENCE_PATHS_INTEGRATED"
    missing_required.extend(manifest_missing_required(r5_manifest))
    missing_required.extend(manifest_missing_required(r2_manifest))
    if not r5_passed:
        missing_required.append("v20_82_r5_pass_status")
    if not r2_passed:
        missing_required.append("v20_84_r2_pass_status")

    repair_ok = repair_status == "OK" and repair_summary_status == "OK" and bool(repair_rows)
    if not repair_ok:
        missing_required.append("v20_93_schema_repair_evidence")
    rows.append(base_row("EVIDENCE_CHAIN_STAGE", "v20_93_schema_repair_detail_readable", "REQUIRED", rel(repair_detail_path), repair_status, len(repair_rows), 1, "PASSED" if repair_ok else "BLOCKED", not repair_ok, "NA" if repair_ok else "V20_93_REPAIR_DETAIL_OR_SUMMARY_NOT_READABLE"))
    rows.append(base_row("EVIDENCE_CHAIN_STAGE", "v20_93_schema_repair_summary_readable", "REQUIRED", rel(repair_summary_path), repair_summary_status, 1 if repair_summary_status == "OK" else 0, 1, "PASSED" if repair_summary_status == "OK" else "BLOCKED", repair_summary_status != "OK", "NA" if repair_summary_status == "OK" else "V20_93_REPAIR_SUMMARY_NOT_READABLE"))
    rows.append(base_row("EVIDENCE_CHAIN_STAGE", "v20_82_r5_passed", "REQUIRED", rel(r5_manifest_path), r5_manifest_status, 1 if r5_passed else 0, 1, "PASSED" if r5_passed else "BLOCKED", not r5_passed, "NA" if r5_passed else "V20_82_R5_NOT_PASSED"))
    rows.append(base_row("EVIDENCE_CHAIN_STAGE", "v20_84_r2_passed", "REQUIRED", rel(r2_manifest_path), r2_manifest_status, 1 if r2_passed else 0, 1, "PASSED" if r2_passed else "BLOCKED", not r2_passed, "NA" if r2_passed else "V20_84_R2_NOT_PASSED"))

    for category, minimum in REQUIRED_EVIDENCE_COUNTS.items():
        r5_row = r5.get(category, {})
        r2_row = r2.get(category, {})
        readable = max(detail_count(r5_row, category), detail_count(r2_row, category))
        counts[category] = readable
        r5_ok = clean(r5_row.get("validation_status")) == "PASSED"
        r2_ok = clean(r2_row.get("integration_status")) == "INTEGRATED"
        status = "PASSED" if readable >= minimum and r5_ok and r2_ok else "BLOCKED"
        if status == "BLOCKED":
            missing_required.append(category)
        source = clean(r2_row.get("bound_source_file") or r5_row.get("source_file") or "NA")
        rows.append(base_row("REQUIRED_EVIDENCE_CATEGORY", category, "REQUIRED", source, clean(r2_row.get("source_status") or r5_row.get("source_status") or "MISSING_ROW"), readable, minimum, status, status == "BLOCKED", "NA" if status == "PASSED" else f"{category.upper()}_MISSING_OR_NOT_INTEGRATED"))

    for category, minimum in OPTIONAL_EVIDENCE_COUNTS.items():
        r5_row = r5.get(category, {})
        r2_row = r2.get(category, {})
        readable = max(detail_count(r5_row, category), detail_count(r2_row, category))
        counts[category] = readable
        source = clean(r2_row.get("bound_source_file") or r5_row.get("source_file") or "NA")
        status = "WARN" if readable >= minimum else "BLOCKED"
        rows.append(base_row("OPTIONAL_DIAGNOSTIC", category, "OPTIONAL", source, clean(r2_row.get("source_status") or r5_row.get("source_status") or "MISSING_ROW"), readable, minimum, status, False, "OPTIONAL_RANKING_DELTA_PARTIAL_DIAGNOSTIC_READABLE" if status == "WARN" else "OPTIONAL_RANKING_DELTA_NOT_READABLE"))

    unique_missing = sorted(set(item for item in missing_required if item))
    if unique_missing:
        closure_status = BLOCKED_EVIDENCE_CHAIN_STATUS
    else:
        closure_status = "PASS_EVIDENCE_CHAIN_CLOSED_WITH_OPTIONAL_WARN"
    for row in rows:
        row["evidence_chain_closure_status"] = closure_status
    return rows, closure_status, unique_missing, counts


def first_existing(paths: list[Path]) -> tuple[Path | None, str]:
    for path in paths:
        if path.exists() and path.stat().st_size > 0:
            return path, "OK"
    return None, "MISSING_OPTIONAL"


def build_promotion_rows(closure_status: str) -> tuple[list[dict[str, str]], str, list[str]]:
    rows: list[dict[str, str]] = []
    blockers = [
        "promotion_preflight_research_only",
        "multi_run_history_sufficiency",
        "rolling_evidence_ledger_sufficiency",
        "shadow_feedback_stability",
        "candidate_dynamic_weight_promotion_readiness",
        "official_recommendation_readiness",
        "nasdaq_benchmark_hurdle_status",
        "operator_acceptance_requirement",
        "safety_state",
    ]
    final_status = PASS_STATUS if closure_status.startswith("PASS_") else BLOCKED_EVIDENCE_CHAIN_STATUS

    rows.append(base_row("PROMOTION_PREFLIGHT_BLOCKER", "promotion_preflight_research_only", "REQUIRED", "NA", "RESEARCH_ONLY_GUARDRAIL", 0, 1, "BLOCKED", True, BLOCKED_RESEARCH_ONLY_STATUS))
    for check_name in ["multi_run_history_sufficiency", "rolling_evidence_ledger_sufficiency", "shadow_feedback_stability", "candidate_dynamic_weight_promotion_readiness", "official_recommendation_readiness", "promotion_readiness"]:
        source, source_status = first_existing(PREFLIGHT_INPUTS[check_name])
        reason = {
            "multi_run_history_sufficiency": BLOCKED_MULTI_RUN_STATUS,
            "rolling_evidence_ledger_sufficiency": "BLOCKED_ROLLING_EVIDENCE_LEDGER_NOT_SUFFICIENT",
            "shadow_feedback_stability": "BLOCKED_SHADOW_FEEDBACK_STABILITY_NOT_PROVEN",
            "candidate_dynamic_weight_promotion_readiness": BLOCKED_DYNAMIC_WEIGHT_STATUS,
            "official_recommendation_readiness": BLOCKED_OFFICIAL_RECOMMENDATION_STATUS,
            "promotion_readiness": "BLOCKED_PROMOTION_READINESS_NOT_OPERATOR_ACCEPTED",
        }[check_name]
        status = "WARN" if source_status == "MISSING_OPTIONAL" else "BLOCKED"
        rows.append(base_row("PROMOTION_PREFLIGHT_BLOCKER", check_name, "OPTIONAL_UPSTREAM", rel(source) if source else "NA", source_status, 0, 1, status, True, reason if source_status == "OK" else f"{reason}_OPTIONAL_SOURCE_MISSING"))
    rows.append(base_row("PROMOTION_PREFLIGHT_BLOCKER", "nasdaq_benchmark_hurdle_status", "REQUIRED", rel(V20_82_R5_MANIFEST), "OK", 0, 1, "BLOCKED", True, "NASDAQ_HURDLE_PASSED_FALSE"))
    rows.append(base_row("PROMOTION_PREFLIGHT_BLOCKER", "operator_acceptance_requirement", "REQUIRED", "NA", "PENDING_OPERATOR_ACCEPTANCE", 0, 1, "BLOCKED", True, "OPERATOR_ACCEPTANCE_REQUIRED_BEFORE_PROMOTION_ALLOWED_TRUE"))
    rows.append(base_row("PROMOTION_PREFLIGHT_BLOCKER", "safety_state", "REQUIRED", "NA", "SAFE_RESEARCH_ONLY", 1, 1, "PASSED", False, "NO_OFFICIAL_OR_TRADE_MUTATION_CREATED"))

    for row in rows:
        row["evidence_chain_closure_status"] = closure_status
        row["promotion_preflight_status"] = final_status
    return rows, final_status, blockers


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DETAIL_FIELDS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, status: str, closure_status: str, promotion_status: str, counts: dict[str, int], missing_required: list[str], blockers: list[str], rows: list[dict[str, str]]) -> None:
    optional_warns = [row["check_name"] for row in rows if row["record_type"] == "OPTIONAL_DIAGNOSTIC" and row["check_status"] == "WARN"]
    lines = [
        "# V20.94 Evidence Chain Closure and Promotion Preflight Gate",
        "",
        "## Evidence Chain Status",
        f"- final_status: {status}",
        f"- evidence_chain_closure_status: {closure_status}",
        f"- missing_required_evidence_categories: {'|'.join(missing_required) if missing_required else 'NONE'}",
        "",
        "## Required Evidence Category Counts",
        f"- readable_regime_evidence_count: {counts.get('regime_conditioned_evidence', 0)}",
        f"- readable_downside_risk_evidence_count: {counts.get('downside_risk_evidence', 0)}",
        f"- readable_benchmark_comparison_evidence_count: {counts.get('benchmark_comparison_evidence', 0)}",
        f"- readable_acceptance_proof_evidence_count: {counts.get('acceptance_proof_evidence', 0)}",
        f"- readable_ranking_delta_diagnostic_evidence_count: {counts.get('ranking_delta_diagnostic_evidence', 0)}",
        "",
        "## Optional WARN Diagnostics",
        f"- optional_warn_diagnostics: {'|'.join(optional_warns) if optional_warns else 'NONE'}",
        "- ranking_delta_diagnostic_evidence_optional_warn_blocks_closure: FALSE",
        "",
        "## Remaining Promotion Blockers",
        f"- promotion_preflight_status: {promotion_status}",
    ]
    lines.extend(f"- {blocker}" for blocker in blockers)
    lines.append("- missing_optional_upstream_file_warns:")
    optional_missing = [
        row
        for row in rows
        if row["record_type"] == "PROMOTION_PREFLIGHT_BLOCKER"
        and row["required_level"] == "OPTIONAL_UPSTREAM"
        and row["source_status"] == "MISSING_OPTIONAL"
    ]
    if optional_missing:
        lines.extend(f"  - WARN {row['check_name']}: {row['blocker_reason']}" for row in optional_missing)
    else:
        lines.append("  - NONE")
    lines.extend(
        [
            "",
            "## Safety Confirmation",
            "- promotion_allowed: FALSE",
            "- nasdaq_hurdle_passed: FALSE",
            "- official_recommendation_created: FALSE",
            "- official_weight_mutated: FALSE",
            "- trade_action_created: FALSE",
            "",
            "## Recommended Next Stages",
            "- Accumulate sufficient multi-run and rolling evidence history.",
            "- Stabilize shadow feedback diagnostics.",
            "- Promote candidate dynamic weights only through a separate approved gate.",
            "- Produce official recommendation readiness proof before any future promotion.",
            "- Obtain explicit operator acceptance before promotion_allowed can ever become TRUE.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def run_gate() -> tuple[list[dict[str, str]], str, str, str, dict[str, int], list[str], list[str]]:
    evidence_rows, closure_status, missing_required, counts = build_evidence_rows()
    promotion_rows, promotion_status, blockers = build_promotion_rows(closure_status)
    rows = evidence_rows + promotion_rows
    final_status = promotion_status if closure_status.startswith("PASS_") else BLOCKED_EVIDENCE_CHAIN_STATUS
    for row in rows:
        row["evidence_chain_closure_status"] = closure_status
        row["promotion_preflight_status"] = promotion_status
    return rows, final_status, closure_status, promotion_status, counts, missing_required, blockers


def main() -> int:
    rows, final_status, closure_status, promotion_status, counts, missing_required, blockers = run_gate()
    write_csv(DETAIL, rows)
    write_summary(SUMMARY, final_status, closure_status, promotion_status, counts, missing_required, blockers, rows)
    shutil.copyfile(DETAIL, DETAIL_ALIAS)
    shutil.copyfile(SUMMARY, SUMMARY_ALIAS)

    print(final_status)
    print(f"EVIDENCE_CHAIN_CLOSURE_STATUS={closure_status}")
    print(f"PROMOTION_PREFLIGHT_STATUS={promotion_status}")
    print(f"READABLE_REGIME_EVIDENCE_COUNT={counts.get('regime_conditioned_evidence', 0)}")
    print(f"READABLE_DOWNSIDE_RISK_EVIDENCE_COUNT={counts.get('downside_risk_evidence', 0)}")
    print(f"READABLE_BENCHMARK_COMPARISON_EVIDENCE_COUNT={counts.get('benchmark_comparison_evidence', 0)}")
    print(f"READABLE_ACCEPTANCE_PROOF_EVIDENCE_COUNT={counts.get('acceptance_proof_evidence', 0)}")
    print(f"READABLE_RANKING_DELTA_DIAGNOSTIC_EVIDENCE_COUNT={counts.get('ranking_delta_diagnostic_evidence', 0)}")
    print(f"MISSING_REQUIRED_EVIDENCE_CATEGORIES={'|'.join(missing_required) if missing_required else 'NONE'}")
    print(f"REMAINING_BLOCKERS={'|'.join(blockers)}")
    print("PROMOTION_ALLOWED=FALSE")
    print("NASDAQ_HURDLE_PASSED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("OFFICIAL_WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    return 0 if final_status in {PASS_STATUS, BLOCKED_RESEARCH_ONLY_STATUS, BLOCKED_MULTI_RUN_STATUS, BLOCKED_OFFICIAL_RECOMMENDATION_STATUS, BLOCKED_DYNAMIC_WEIGHT_STATUS} else 1


if __name__ == "__main__":
    raise SystemExit(main())
