#!/usr/bin/env python
"""V20.98B-R2 research-only base weight template.

Creates inactive, operator-review-only factor family weight template rows after
R1 confirmed no authoritative numeric base weight source exists. It does not
activate, infer, mutate, or officialize any weights.
"""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R1_REGISTRY = CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv"
R1_GAP = CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_GAP_AUDIT.csv"
R1_COLUMN_MAP = CONSOLIDATION / "V20_98B_R1_FACTOR_COLUMN_TO_FAMILY_MAP.csv"
EXPOSURE = CONSOLIDATION / "V20_98B_RESEARCH_ONLY_FACTOR_WEIGHT_EXPOSURE.csv"
SUMMARY = CONSOLIDATION / "V20_98B_FACTOR_FAMILY_WEIGHT_SUMMARY.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

TEMPLATE = CONSOLIDATION / "V20_98B_R2_RESEARCH_ONLY_BASE_WEIGHT_TEMPLATE.csv"
VALIDATION = CONSOLIDATION / "V20_98B_R2_BASE_WEIGHT_TEMPLATE_VALIDATION.csv"
REVIEW_QUEUE = CONSOLIDATION / "V20_98B_R2_BASE_WEIGHT_OPERATOR_REVIEW_QUEUE.csv"
REPORT = READ_CENTER / "V20_98B_R2_RESEARCH_ONLY_BASE_WEIGHT_TEMPLATE_REPORT.md"

REQUIRED_FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]

TEMPLATE_FIELDS = [
    "factor_family",
    "factor_id",
    "factor_name",
    "template_row_type",
    "source_stage",
    "source_artifact",
    "source_column",
    "proposed_base_weight",
    "active_weight",
    "operator_review_required",
    "operator_approved",
    "weight_activation_allowed",
    "used_in_dynamic_reweighting",
    "v20_107_dynamic_reweighting_status",
    "source_rank_or_score_used_as_weight",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "is_official_weight",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
]

VALIDATION_FIELDS = [
    "validation_check",
    "validation_status",
    "details",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "is_official_weight",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
]

REVIEW_FIELDS = [
    "review_item_id",
    "factor_family",
    "factor_id",
    "review_reason",
    "operator_review_required",
    "operator_approved",
    "weight_activation_allowed",
    "used_in_dynamic_reweighting",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "is_official_weight",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], str]:
    if not path.exists():
        return [], "MISSING"
    if path.stat().st_size == 0:
        return [], "EMPTY"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = [{key: clean(value) for key, value in row.items()} for row in reader]
    except csv.Error:
        return [], "MALFORMED"
    return rows, "OK" if reader.fieldnames else "MALFORMED"


def first_row(path: Path) -> dict[str, str]:
    rows, status = read_csv(path)
    return rows[0] if status == "OK" and rows else {}


def safety() -> dict[str, str]:
    return {
        "research_only": "TRUE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
    }


def template_row(family: str, factor_id: str, factor_name: str, row_type: str, source_stage: str = "V20.98B-R2", source_artifact: str = "FAMILY_LEVEL_PLACEHOLDER", source_column: str = "NONE") -> dict[str, str]:
    return {
        "factor_family": family,
        "factor_id": factor_id,
        "factor_name": factor_name,
        "template_row_type": row_type,
        "source_stage": source_stage,
        "source_artifact": source_artifact,
        "source_column": source_column,
        "proposed_base_weight": "",
        "active_weight": "",
        "operator_review_required": "TRUE",
        "operator_approved": "FALSE",
        "weight_activation_allowed": "FALSE",
        "used_in_dynamic_reweighting": "FALSE",
        "v20_107_dynamic_reweighting_status": "BLOCKED_UNTIL_OPERATOR_APPROVED_ACTIVE_RESEARCH_WEIGHTS_EXIST",
        "source_rank_or_score_used_as_weight": "FALSE",
        **safety(),
    }


def infer_required_family(factor_family: str, factor_id: str) -> str:
    text = f"{factor_family} {factor_id}".upper()
    if "TECH" in text or "SCORE_REVIEW" in text:
        return "TECHNICAL"
    if "RISK" in text:
        return "RISK"
    if "REGIME" in text or "MARKET" in text:
        return "MARKET_REGIME"
    if "STRATEGY" in text or "ENTRY" in text:
        return "STRATEGY"
    if "DATA" in text or "TRUST" in text:
        return "DATA_TRUST"
    if "FUND" in text:
        return "FUNDAMENTAL"
    return ""


def build_template_rows() -> list[dict[str, str]]:
    exposure_rows, _status = read_csv(EXPOSURE)
    rows = [
        template_row(family, f"{family}_BASE_WEIGHT_PLACEHOLDER", f"{family} base weight placeholder", "FAMILY_LEVEL_PLACEHOLDER")
        for family in REQUIRED_FAMILIES
    ]
    seen_factor_ids = {row["factor_id"] for row in rows}
    for source in exposure_rows:
        factor_id = clean(source.get("factor_id"))
        if not factor_id or factor_id in seen_factor_ids:
            continue
        family = infer_required_family(clean(source.get("factor_family")), factor_id)
        if not family:
            continue
        rows.append(
            template_row(
                family,
                factor_id,
                clean(source.get("factor_name")) or factor_id,
                "DISCOVERED_FACTOR_CONTEXT_PLACEHOLDER",
                clean(source.get("source_stage")) or "UNKNOWN",
                clean(source.get("source_artifact")) or "UNKNOWN",
                clean(source.get("source_column")) or "NONE",
            )
        )
        seen_factor_ids.add(factor_id)
    return rows


def build_validation_rows(template_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    families = {row["factor_family"] for row in template_rows}
    active = [row for row in template_rows if clean(row.get("active_weight")).upper() == "TRUE" or clean(row.get("active_weight")) not in {"", "FALSE"}]
    source_rank_used = [row for row in template_rows if row["source_rank_or_score_used_as_weight"] == "TRUE"]
    approved = [row for row in template_rows if row["operator_approved"] == "TRUE"]
    activation = [row for row in template_rows if row["weight_activation_allowed"] == "TRUE"]
    dynamic = [row for row in template_rows if row["used_in_dynamic_reweighting"] == "TRUE"]
    return [
        {
            "validation_check": "required_factor_families_present",
            "validation_status": "PASS" if set(REQUIRED_FAMILIES).issubset(families) else "FAIL",
            "details": "|".join(sorted(families)),
            **safety(),
        },
        {
            "validation_check": "template_rows_not_active_weights",
            "validation_status": "PASS" if not active else "FAIL",
            "details": f"active_weight_row_count={len(active)}",
            **safety(),
        },
        {
            "validation_check": "source_rank_or_score_not_used_as_weight",
            "validation_status": "PASS" if not source_rank_used else "FAIL",
            "details": f"source_rank_or_score_used_as_weight_count={len(source_rank_used)}",
            **safety(),
        },
        {
            "validation_check": "operator_approval_required_before_activation",
            "validation_status": "PASS" if not approved and not activation else "FAIL",
            "details": f"operator_approved_count={len(approved)};weight_activation_allowed_count={len(activation)}",
            **safety(),
        },
        {
            "validation_check": "v20_107_dynamic_reweighting_blocked",
            "validation_status": "PASS" if not dynamic else "FAIL",
            "details": f"used_in_dynamic_reweighting_count={len(dynamic)}",
            **safety(),
        },
        {
            "validation_check": "official_promotion_remains_blocked",
            "validation_status": "PASS",
            "details": "official_promotion_allowed=FALSE",
            **safety(),
        },
    ]


def build_review_queue(template_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for index, row in enumerate(template_rows, start=1):
        output.append(
            {
                "review_item_id": f"V20_98B_R2_REVIEW_{index:03d}",
                "factor_family": row["factor_family"],
                "factor_id": row["factor_id"],
                "review_reason": "Operator must provide/approve research-only base weight before any activation or dynamic reweighting.",
                "operator_review_required": "TRUE",
                "operator_approved": "FALSE",
                "weight_activation_allowed": "FALSE",
                "used_in_dynamic_reweighting": "FALSE",
                **safety(),
            }
        )
    return output


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_report(template_rows: list[dict[str, str]], validation_rows: list[dict[str, str]], statuses: dict[str, str]) -> None:
    lines = [
        "# V20.98B-R2 Research-Only Base Weight Template",
        "",
        "## Gate Context",
        f"- v20_49_research_only_gate_status: {statuses['research_status']}",
        f"- v20_49_official_promotion_gate_status: {statuses['official_status']}",
        "- research_only: TRUE",
        "- official_promotion_allowed: FALSE",
        "- official_recommendation_created: FALSE",
        "- is_official_weight: FALSE",
        "- weight_mutated: FALSE",
        "- trade_action_created: FALSE",
        "- broker_execution_supported: FALSE",
        "",
        "## Template Status",
        f"- template_row_count: {len(template_rows)}",
        "- active_weight_enabled: FALSE",
        "- operator_review_required: TRUE",
        "- operator_approved: FALSE",
        "- weight_activation_allowed: FALSE",
        "- used_in_dynamic_reweighting: FALSE",
        "- V20.107 shadow dynamic reweighting remains blocked until operator-approved active research weights exist.",
        "",
        "## Required Families",
    ]
    for family in REQUIRED_FAMILIES:
        lines.append(f"- {family}")
    lines.extend(["", "## Validation"])
    for row in validation_rows:
        lines.append(f"- {row['validation_check']}: {row['validation_status']} ({row['details']})")
    lines.extend(
        [
            "",
            "No weights are activated or inferred from source_rank_or_score, candidate rank order, or score columns.",
            "",
        ]
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def run() -> dict[str, str]:
    research = first_row(V49_RESEARCH)
    official = first_row(V49_OFFICIAL)
    template_rows = build_template_rows()
    validation_rows = build_validation_rows(template_rows)
    review_rows = build_review_queue(template_rows)
    write_csv(TEMPLATE, template_rows, TEMPLATE_FIELDS)
    write_csv(VALIDATION, validation_rows, VALIDATION_FIELDS)
    write_csv(REVIEW_QUEUE, review_rows, REVIEW_FIELDS)
    statuses = {
        "research_status": clean(research.get("research_only_gate_status")),
        "official_status": clean(official.get("official_promotion_gate_status")),
        "template_row_count": str(len(template_rows)),
        "validation_pass_count": str(sum(1 for row in validation_rows if row["validation_status"] == "PASS")),
    }
    write_report(template_rows, validation_rows, statuses)
    return statuses


def main() -> int:
    statuses = run()
    print("PASS_V20_98B_R2_RESEARCH_ONLY_BASE_WEIGHT_TEMPLATE")
    print(f"V20_49_RESEARCH_ONLY_GATE_STATUS={statuses['research_status']}")
    print(f"V20_49_OFFICIAL_PROMOTION_GATE_STATUS={statuses['official_status']}")
    print(f"TEMPLATE_ROW_COUNT={statuses['template_row_count']}")
    print(f"VALIDATION_PASS_COUNT={statuses['validation_pass_count']}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("IS_OFFICIAL_WEIGHT=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("USED_IN_DYNAMIC_REWEIGHTING=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
