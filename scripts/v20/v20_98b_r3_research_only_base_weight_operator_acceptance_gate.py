#!/usr/bin/env python
"""V20.98B-R3 research-only base weight operator acceptance gate.

Validates whether the inactive R2 research-only base weight template can be
accepted into an active research-only base weight registry. This stage never
creates official weights, recommendations, trade actions, or promotion status.
"""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R2_TEMPLATE = CONSOLIDATION / "V20_98B_R2_RESEARCH_ONLY_BASE_WEIGHT_TEMPLATE.csv"
R2_VALIDATION = CONSOLIDATION / "V20_98B_R2_BASE_WEIGHT_TEMPLATE_VALIDATION.csv"
R2_REVIEW_QUEUE = CONSOLIDATION / "V20_98B_R2_BASE_WEIGHT_OPERATOR_REVIEW_QUEUE.csv"
R1_REGISTRY = CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

ACCEPTANCE_GATE = CONSOLIDATION / "V20_98B_R3_BASE_WEIGHT_OPERATOR_ACCEPTANCE_GATE.csv"
ACTIVE_REGISTRY = CONSOLIDATION / "V20_98B_R3_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
VALIDATION_AUDIT = CONSOLIDATION / "V20_98B_R3_BASE_WEIGHT_VALIDATION_AUDIT.csv"
REPORT = READ_CENTER / "V20_98B_R3_BASE_WEIGHT_OPERATOR_ACCEPTANCE_REPORT.md"

REQUIRED_FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
ZERO_REQUIRED_FAMILIES = {
    "RISK": "BLOCKED_RISK_WEIGHT_ZERO",
    "DATA_TRUST": "BLOCKED_DATA_TRUST_WEIGHT_ZERO",
    "MARKET_REGIME": "BLOCKED_MARKET_REGIME_WEIGHT_ZERO",
}

SAFETY_FIELDS = [
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "is_official_weight",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
]

GATE_FIELDS = [
    "stage",
    "acceptance_status",
    "v20_49_research_only_gate_status",
    "v20_49_official_promotion_gate_status",
    "required_factor_families_present",
    "missing_factor_families",
    "operator_approval_required_count",
    "operator_approved_count",
    "missing_template_weight_count",
    "active_research_base_weight_count",
    "weight_sum",
    "weight_sum_status",
    "family_zero_weight_blockers",
    "family_weight_cap_blockers",
    "v20_107_dynamic_reweighting_status",
    "next_recommended_action",
    *SAFETY_FIELDS,
]

ACTIVE_FIELDS = [
    "factor_family",
    "factor_id",
    "factor_name",
    "template_row_type",
    "template_weight",
    "operator_approved",
    "active_research_base_weight",
    "active_research_base_weight_created",
    "activation_status",
    "v20_107_dynamic_reweighting_status",
    *SAFETY_FIELDS,
]

AUDIT_FIELDS = [
    "validation_check",
    "validation_status",
    "blocker_id",
    "details",
    *SAFETY_FIELDS,
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


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
            if not reader.fieldnames:
                return [], "MALFORMED"
            return rows, "OK"
    except csv.Error:
        return [], "MALFORMED"


def first_row(path: Path) -> dict[str, str]:
    rows, status = read_csv(path)
    return rows[0] if status == "OK" and rows else {}


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_weight(row: dict[str, str]) -> Decimal | None:
    value = clean(row.get("template_weight")) or clean(row.get("proposed_base_weight"))
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def required_family_rows(template_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for family in REQUIRED_FAMILIES:
        family_rows = [row for row in template_rows if row.get("factor_family") == family]
        placeholder = [row for row in family_rows if row.get("template_row_type") == "FAMILY_LEVEL_PLACEHOLDER"]
        if placeholder:
            selected.append(placeholder[0])
        elif family_rows:
            selected.append(family_rows[0])
    return selected


def primary_status(blockers: list[str]) -> str:
    precedence = [
        "BLOCKED_REQUIRED_FACTOR_FAMILY_MISSING",
        "BLOCKED_OPERATOR_APPROVAL_REQUIRED",
        "BLOCKED_MISSING_TEMPLATE_WEIGHT",
        "BLOCKED_WEIGHT_SUM_INVALID",
        "BLOCKED_RISK_WEIGHT_ZERO",
        "BLOCKED_DATA_TRUST_WEIGHT_ZERO",
        "BLOCKED_MARKET_REGIME_WEIGHT_ZERO",
        "BLOCKED_FAMILY_WEIGHT_CAP_EXCEEDED",
    ]
    for blocker in precedence:
        if blocker in blockers:
            return blocker
    return "PASS_V20_98B_R3_RESEARCH_ONLY_BASE_WEIGHT_ACCEPTED"


def percent_weight(value: Decimal, basis: str) -> Decimal:
    return value * Decimal("100") if basis == "DECIMAL_1" else value


def evaluate(template_rows: list[dict[str, str]]) -> tuple[dict[str, str], list[dict[str, str]], list[dict[str, str]]]:
    research_gate = first_row(V49_RESEARCH)
    official_gate = first_row(V49_OFFICIAL)
    selected_rows = required_family_rows(template_rows)
    selected_families = {row.get("factor_family", "") for row in selected_rows}
    missing_families = [family for family in REQUIRED_FAMILIES if family not in selected_families]
    approval_required_rows = [row for row in selected_rows if row.get("operator_review_required", "TRUE") == "TRUE"]
    approved_rows = [row for row in selected_rows if row.get("operator_approved") == "TRUE"]
    parsed_weights = {row.get("factor_family", ""): parse_weight(row) for row in selected_rows}
    missing_weight_families = [family for family, value in parsed_weights.items() if value is None]

    blockers: list[str] = []
    if missing_families:
        blockers.append("BLOCKED_REQUIRED_FACTOR_FAMILY_MISSING")
    if len(approved_rows) < len(selected_rows):
        blockers.append("BLOCKED_OPERATOR_APPROVAL_REQUIRED")
    if missing_weight_families:
        blockers.append("BLOCKED_MISSING_TEMPLATE_WEIGHT")

    numeric_weights = [value for value in parsed_weights.values() if value is not None]
    weight_sum = sum(numeric_weights, Decimal("0"))
    weight_basis = ""
    weight_sum_status = "NOT_EVALUATED_MISSING_TEMPLATE_WEIGHT"
    if not missing_weight_families and len(numeric_weights) == len(REQUIRED_FAMILIES):
        if abs(weight_sum - Decimal("1")) <= Decimal("0.000001"):
            weight_sum_status = "PASS_WEIGHT_SUM_DECIMAL_1"
            weight_basis = "DECIMAL_1"
        elif abs(weight_sum - Decimal("100")) <= Decimal("0.000001"):
            weight_sum_status = "PASS_WEIGHT_SUM_PERCENT_100"
            weight_basis = "PERCENT_100"
        else:
            blockers.append("BLOCKED_WEIGHT_SUM_INVALID")
            weight_sum_status = "BLOCKED_WEIGHT_SUM_INVALID"

    zero_blockers: list[str] = []
    cap_blockers: list[str] = []
    if weight_basis:
        for family, blocker in ZERO_REQUIRED_FAMILIES.items():
            value = parsed_weights.get(family)
            if value is not None and value == 0:
                zero_blockers.append(blocker)
                blockers.append(blocker)
        for family, value in parsed_weights.items():
            if value is not None and percent_weight(value, weight_basis) > Decimal("35"):
                cap_blockers.append(family)
        if cap_blockers:
            blockers.append("BLOCKED_FAMILY_WEIGHT_CAP_EXCEEDED")

    acceptance_status = primary_status(blockers)
    accepted = acceptance_status.startswith("PASS_")
    dynamic_status = (
        "ELIGIBLE_FOR_V20_107_SHADOW_DYNAMIC_REWEIGHTING_INPUT"
        if accepted
        else "BLOCKED_UNTIL_ACCEPTED_ACTIVE_RESEARCH_BASE_WEIGHTS_EXIST"
    )

    active_rows: list[dict[str, str]] = []
    for row in selected_rows:
        family = row.get("factor_family", "")
        weight = parsed_weights.get(family)
        active_rows.append(
            {
                "factor_family": family,
                "factor_id": row.get("factor_id", ""),
                "factor_name": row.get("factor_name", ""),
                "template_row_type": row.get("template_row_type", ""),
                "template_weight": "" if weight is None else str(weight),
                "operator_approved": row.get("operator_approved", "FALSE"),
                "active_research_base_weight": str(weight) if accepted and weight is not None else "",
                "active_research_base_weight_created": tf(accepted and weight is not None),
                "activation_status": acceptance_status,
                "v20_107_dynamic_reweighting_status": dynamic_status,
                **safety(),
            }
        )

    audit_rows = [
        {
            "validation_check": "v20_49_research_only_gate_preserved",
            "validation_status": "PASS"
            if research_gate.get("research_only_gate_status") == "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE"
            else "WARN_SOURCE_NOT_PASS",
            "blocker_id": "",
            "details": research_gate.get("research_only_gate_status", "MISSING"),
            **safety(),
        },
        {
            "validation_check": "v20_49_official_promotion_gate_preserved",
            "validation_status": "PASS"
            if official_gate.get("official_promotion_gate_status") == "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE"
            else "WARN_SOURCE_NOT_BLOCKED",
            "blocker_id": "",
            "details": official_gate.get("official_promotion_gate_status", "MISSING"),
            **safety(),
        },
        {
            "validation_check": "required_factor_families_present",
            "validation_status": "PASS" if not missing_families else "BLOCKED_REQUIRED_FACTOR_FAMILY_MISSING",
            "blocker_id": "" if not missing_families else "BLOCKED_REQUIRED_FACTOR_FAMILY_MISSING",
            "details": "missing=" + ("|".join(missing_families) if missing_families else "NONE"),
            **safety(),
        },
        {
            "validation_check": "operator_approval_required_before_activation",
            "validation_status": "PASS" if len(approved_rows) == len(selected_rows) and selected_rows else "BLOCKED_OPERATOR_APPROVAL_REQUIRED",
            "blocker_id": "" if len(approved_rows) == len(selected_rows) and selected_rows else "BLOCKED_OPERATOR_APPROVAL_REQUIRED",
            "details": f"operator_approved_count={len(approved_rows)};required_count={len(selected_rows)}",
            **safety(),
        },
        {
            "validation_check": "template_weight_present",
            "validation_status": "PASS" if not missing_weight_families else "BLOCKED_MISSING_TEMPLATE_WEIGHT",
            "blocker_id": "" if not missing_weight_families else "BLOCKED_MISSING_TEMPLATE_WEIGHT",
            "details": "missing_template_weight_families=" + ("|".join(missing_weight_families) if missing_weight_families else "NONE"),
            **safety(),
        },
        {
            "validation_check": "weight_sum_valid",
            "validation_status": weight_sum_status,
            "blocker_id": "BLOCKED_WEIGHT_SUM_INVALID" if weight_sum_status == "BLOCKED_WEIGHT_SUM_INVALID" else "",
            "details": f"weight_sum={weight_sum}",
            **safety(),
        },
        {
            "validation_check": "required_risk_family_weights_nonzero",
            "validation_status": "PASS" if weight_basis and not zero_blockers else ("NOT_EVALUATED_MISSING_TEMPLATE_WEIGHT" if not weight_basis else ";".join(zero_blockers)),
            "blocker_id": ";".join(zero_blockers),
            "details": "zero_blockers=" + ("|".join(zero_blockers) if zero_blockers else "NONE"),
            **safety(),
        },
        {
            "validation_check": "family_weight_cap_not_exceeded",
            "validation_status": "PASS" if weight_basis and not cap_blockers else ("NOT_EVALUATED_MISSING_TEMPLATE_WEIGHT" if not weight_basis else "BLOCKED_FAMILY_WEIGHT_CAP_EXCEEDED"),
            "blocker_id": "BLOCKED_FAMILY_WEIGHT_CAP_EXCEEDED" if cap_blockers else "",
            "details": "cap_exceeded_families=" + ("|".join(cap_blockers) if cap_blockers else "NONE"),
            **safety(),
        },
        {
            "validation_check": "official_weight_not_created",
            "validation_status": "PASS",
            "blocker_id": "",
            "details": "is_official_weight=FALSE",
            **safety(),
        },
        {
            "validation_check": "v20_107_dynamic_reweighting_status",
            "validation_status": dynamic_status,
            "blocker_id": "" if accepted else "BLOCKED_UNTIL_ACCEPTED_ACTIVE_RESEARCH_BASE_WEIGHTS_EXIST",
            "details": f"active_research_base_weight_count={sum(1 for row in active_rows if row['active_research_base_weight_created'] == 'TRUE')}",
            **safety(),
        },
    ]

    gate_row = {
        "stage": "V20.98B-R3_RESEARCH_ONLY_BASE_WEIGHT_OPERATOR_ACCEPTANCE_GATE",
        "acceptance_status": acceptance_status,
        "v20_49_research_only_gate_status": research_gate.get("research_only_gate_status", "MISSING"),
        "v20_49_official_promotion_gate_status": official_gate.get("official_promotion_gate_status", "MISSING"),
        "required_factor_families_present": tf(not missing_families),
        "missing_factor_families": ";".join(missing_families),
        "operator_approval_required_count": str(len(approval_required_rows)),
        "operator_approved_count": str(len(approved_rows)),
        "missing_template_weight_count": str(len(missing_weight_families)),
        "active_research_base_weight_count": str(sum(1 for row in active_rows if row["active_research_base_weight_created"] == "TRUE")),
        "weight_sum": str(weight_sum),
        "weight_sum_status": weight_sum_status,
        "family_zero_weight_blockers": ";".join(zero_blockers),
        "family_weight_cap_blockers": ";".join(cap_blockers),
        "v20_107_dynamic_reweighting_status": dynamic_status,
        "next_recommended_action": "OPERATOR_REVIEW_AND_APPROVE_RESEARCH_ONLY_TEMPLATE_WEIGHTS"
        if not accepted
        else "RUN_V20_107_SHADOW_DYNAMIC_REWEIGHTING_WHEN_REQUIRED",
        **safety(),
    }
    return gate_row, active_rows, audit_rows


def write_report(gate_row: dict[str, str], template_status: str, validation_status: str, review_status: str, registry_status: str) -> None:
    lines = [
        "# V20.98B-R3 Research-Only Base Weight Operator Acceptance Gate",
        "",
        "## Current Result",
        f"- wrapper_status: PASS_V20_98B_R3_RESEARCH_ONLY_BASE_WEIGHT_OPERATOR_ACCEPTANCE_GATE",
        f"- acceptance_status: {gate_row['acceptance_status']}",
        f"- v20_49_research_only_gate_status: {gate_row['v20_49_research_only_gate_status']}",
        f"- v20_49_official_promotion_gate_status: {gate_row['v20_49_official_promotion_gate_status']}",
        f"- active_research_base_weight_count: {gate_row['active_research_base_weight_count']}",
        f"- missing_template_weight_count: {gate_row['missing_template_weight_count']}",
        f"- operator_approved_count: {gate_row['operator_approved_count']}",
        f"- weight_sum_status: {gate_row['weight_sum_status']}",
        f"- v20_107_dynamic_reweighting_status: {gate_row['v20_107_dynamic_reweighting_status']}",
        "",
        "## Input Status",
        f"- R2 template: {template_status}",
        f"- R2 validation: {validation_status}",
        f"- R2 review queue: {review_status}",
        f"- R1 source registry: {registry_status}",
        "",
        "## Safety Boundary",
        "- research_only: TRUE",
        "- official_promotion_allowed: FALSE",
        "- official_recommendation_created: FALSE",
        "- is_official_weight: FALSE",
        "- weight_mutated: FALSE",
        "- trade_action_created: FALSE",
        "- broker_execution_supported: FALSE",
        "",
        "## Interpretation",
        "R3 validates whether operator-approved research-only template weights can become active research base weights.",
        "The current R2 template is intentionally inactive, has no approved operator weights, and therefore remains blocked.",
        "This does not resolve official promotion blockers and does not create official weights.",
        "",
        "## Next Recommended Action",
        f"{gate_row['next_recommended_action']}.",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    template_rows, template_status = read_csv(R2_TEMPLATE)
    _validation_rows, validation_status = read_csv(R2_VALIDATION)
    _review_rows, review_status = read_csv(R2_REVIEW_QUEUE)
    _registry_rows, registry_status = read_csv(R1_REGISTRY)

    gate_row, active_rows, audit_rows = evaluate(template_rows if template_status == "OK" else [])

    write_csv(ACCEPTANCE_GATE, GATE_FIELDS, [gate_row])
    write_csv(ACTIVE_REGISTRY, ACTIVE_FIELDS, active_rows)
    write_csv(VALIDATION_AUDIT, AUDIT_FIELDS, audit_rows)
    write_report(gate_row, template_status, validation_status, review_status, registry_status)

    print("PASS_V20_98B_R3_RESEARCH_ONLY_BASE_WEIGHT_OPERATOR_ACCEPTANCE_GATE")
    print(f"ACCEPTANCE_STATUS={gate_row['acceptance_status']}")
    print(f"V20_49_RESEARCH_ONLY_GATE_STATUS={gate_row['v20_49_research_only_gate_status']}")
    print(f"V20_49_OFFICIAL_PROMOTION_GATE_STATUS={gate_row['v20_49_official_promotion_gate_status']}")
    print(f"ACTIVE_RESEARCH_BASE_WEIGHT_COUNT={gate_row['active_research_base_weight_count']}")
    print(f"MISSING_TEMPLATE_WEIGHT_COUNT={gate_row['missing_template_weight_count']}")
    print(f"OPERATOR_APPROVED_COUNT={gate_row['operator_approved_count']}")
    print(f"OFFICIAL_PROMOTION_ALLOWED={gate_row['official_promotion_allowed']}")
    print(f"IS_OFFICIAL_WEIGHT={gate_row['is_official_weight']}")
    print(f"WEIGHT_MUTATED={gate_row['weight_mutated']}")
    print(f"TRADE_ACTION_CREATED={gate_row['trade_action_created']}")
    print(f"V20_107_DYNAMIC_REWEIGHTING_STATUS={gate_row['v20_107_dynamic_reweighting_status']}")
    print(f"OUTPUT_ACCEPTANCE_GATE={rel(ACCEPTANCE_GATE)}")
    print(f"OUTPUT_ACTIVE_REGISTRY={rel(ACTIVE_REGISTRY)}")
    print(f"OUTPUT_VALIDATION_AUDIT={rel(VALIDATION_AUDIT)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
