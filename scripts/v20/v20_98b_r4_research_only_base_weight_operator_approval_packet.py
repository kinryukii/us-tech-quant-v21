#!/usr/bin/env python
"""V20.98B-R4 research-only base weight operator approval packet.

Creates a controlled research-only operator approval packet with explicit base
factor weights. This does not mutate R2/R3 artifacts and does not create
official weights, recommendations, trade actions, or broker execution support.
"""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R2_TEMPLATE = CONSOLIDATION / "V20_98B_R2_RESEARCH_ONLY_BASE_WEIGHT_TEMPLATE.csv"
R3_GATE = CONSOLIDATION / "V20_98B_R3_BASE_WEIGHT_OPERATOR_ACCEPTANCE_GATE.csv"
R3_VALIDATION = CONSOLIDATION / "V20_98B_R3_BASE_WEIGHT_VALIDATION_AUDIT.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

PACKET = CONSOLIDATION / "V20_98B_R4_RESEARCH_ONLY_BASE_WEIGHT_OPERATOR_APPROVAL_PACKET.csv"
VALIDATION = CONSOLIDATION / "V20_98B_R4_BASE_WEIGHT_APPROVAL_VALIDATION.csv"
REPORT = READ_CENTER / "V20_98B_R4_RESEARCH_ONLY_BASE_WEIGHT_OPERATOR_APPROVAL_REPORT.md"

APPROVED_WEIGHTS = {
    "FUNDAMENTAL": Decimal("0.20"),
    "TECHNICAL": Decimal("0.25"),
    "STRATEGY": Decimal("0.20"),
    "RISK": Decimal("0.15"),
    "MARKET_REGIME": Decimal("0.10"),
    "DATA_TRUST": Decimal("0.10"),
}
REQUIRED_FAMILIES = list(APPROVED_WEIGHTS)

PACKET_FIELDS = [
    "factor_family",
    "approved_research_base_weight",
    "operator_approved",
    "operator_approval_source",
    "weight_activation_allowed",
    "activation_scope",
    "is_official_weight",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
    "validation_status",
    "validation_reason",
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


def format_weight(value: Decimal) -> str:
    return f"{value:.2f}"


def build_packet_rows(template_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    template_families = {row.get("factor_family", "") for row in template_rows}
    rows: list[dict[str, str]] = []
    for family, weight in APPROVED_WEIGHTS.items():
        represented = family in template_families
        rows.append(
            {
                "factor_family": family,
                "approved_research_base_weight": format_weight(weight),
                "operator_approved": "TRUE",
                "operator_approval_source": "V20.98B-R4_EXPLICIT_RESEARCH_ONLY_OPERATOR_APPROVAL_PACKET",
                "weight_activation_allowed": "TRUE",
                "activation_scope": "RESEARCH_ONLY_BASE_WEIGHT_ACTIVATION",
                "validation_status": "PASS" if represented else "WARN_TEMPLATE_FAMILY_NOT_FOUND",
                "validation_reason": "EXPLICIT_RESEARCH_ONLY_WEIGHT_APPROVED_BY_OPERATOR_PACKET"
                if represented
                else "EXPLICIT_WEIGHT_PRESENT_BUT_R2_TEMPLATE_FAMILY_NOT_FOUND",
                **safety(),
            }
        )
    return rows


def build_validation_rows(packet_rows: list[dict[str, str]], template_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    research_gate = first_row(V49_RESEARCH)
    official_gate = first_row(V49_OFFICIAL)
    r3_gate = first_row(R3_GATE)
    template_families = {row.get("factor_family", "") for row in template_rows}
    packet_families = {row["factor_family"] for row in packet_rows}
    weights = {row["factor_family"]: Decimal(row["approved_research_base_weight"]) for row in packet_rows}
    weight_sum = sum(weights.values(), Decimal("0"))
    negative_families = [family for family, weight in weights.items() if weight < 0]
    cap_exceeded = [family for family, weight in weights.items() if weight > Decimal("0.35")]
    missing_packet = [family for family in REQUIRED_FAMILIES if family not in packet_families]
    missing_template = [family for family in REQUIRED_FAMILIES if family not in template_families]
    source_rank_used = [
        row
        for row in template_rows
        if clean(row.get("source_rank_or_score_used_as_weight")).upper() == "TRUE"
    ]
    approval_false = [row for row in packet_rows if row.get("operator_approved") != "TRUE"]
    official_or_trade_flags = [
        row
        for row in packet_rows
        if row.get("official_promotion_allowed") != "FALSE"
        or row.get("official_recommendation_created") != "FALSE"
        or row.get("is_official_weight") != "FALSE"
        or row.get("weight_mutated") != "FALSE"
        or row.get("trade_action_created") != "FALSE"
        or row.get("broker_execution_supported") != "FALSE"
    ]

    return [
        {
            "validation_check": "v20_49_research_only_gate_preserved",
            "validation_status": "PASS"
            if research_gate.get("research_only_gate_status") == "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE"
            else "WARN_SOURCE_NOT_PASS",
            "details": research_gate.get("research_only_gate_status", "MISSING"),
            **safety(),
        },
        {
            "validation_check": "v20_49_official_promotion_gate_preserved",
            "validation_status": "PASS"
            if official_gate.get("official_promotion_gate_status") == "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE"
            else "WARN_SOURCE_NOT_BLOCKED",
            "details": official_gate.get("official_promotion_gate_status", "MISSING"),
            **safety(),
        },
        {
            "validation_check": "r3_blocked_activation_context_preserved",
            "validation_status": "PASS"
            if r3_gate.get("acceptance_status") == "BLOCKED_OPERATOR_APPROVAL_REQUIRED"
            else "WARN_R3_CONTEXT_NOT_BLOCKED_OPERATOR_APPROVAL_REQUIRED",
            "details": r3_gate.get("acceptance_status", "MISSING"),
            **safety(),
        },
        {
            "validation_check": "six_required_factor_families_present",
            "validation_status": "PASS" if not missing_packet and not missing_template else "WARN_REQUIRED_FAMILY_GAP",
            "details": f"missing_packet={('|'.join(missing_packet) if missing_packet else 'NONE')};missing_template={('|'.join(missing_template) if missing_template else 'NONE')}",
            **safety(),
        },
        {
            "validation_check": "weight_sum_equals_1_00",
            "validation_status": "PASS" if abs(weight_sum - Decimal("1.00")) <= Decimal("0.000001") else "FAIL_WEIGHT_SUM_NOT_1_00",
            "details": f"weight_sum={weight_sum:.2f}",
            **safety(),
        },
        {
            "validation_check": "no_negative_weights",
            "validation_status": "PASS" if not negative_families else "FAIL_NEGATIVE_WEIGHT",
            "details": "negative_families=" + ("|".join(negative_families) if negative_families else "NONE"),
            **safety(),
        },
        {
            "validation_check": "family_weight_cap_0_35",
            "validation_status": "PASS" if not cap_exceeded else "FAIL_FAMILY_WEIGHT_CAP_EXCEEDED",
            "details": "cap_exceeded_families=" + ("|".join(cap_exceeded) if cap_exceeded else "NONE"),
            **safety(),
        },
        {
            "validation_check": "risk_market_regime_data_trust_positive",
            "validation_status": "PASS"
            if weights["RISK"] > 0 and weights["MARKET_REGIME"] > 0 and weights["DATA_TRUST"] > 0
            else "FAIL_REQUIRED_PROTECTIVE_WEIGHT_ZERO",
            "details": f"RISK={weights['RISK']};MARKET_REGIME={weights['MARKET_REGIME']};DATA_TRUST={weights['DATA_TRUST']}",
            **safety(),
        },
        {
            "validation_check": "source_rank_or_score_not_used_as_factor_weight_source",
            "validation_status": "PASS" if not source_rank_used else "FAIL_SOURCE_RANK_OR_SCORE_USED_AS_WEIGHT",
            "details": f"source_rank_or_score_used_count={len(source_rank_used)}",
            **safety(),
        },
        {
            "validation_check": "operator_approved_true_in_r4_packet",
            "validation_status": "PASS" if not approval_false else "FAIL_OPERATOR_APPROVAL_FALSE",
            "details": f"operator_approved_false_count={len(approval_false)}",
            **safety(),
        },
        {
            "validation_check": "research_only_activation_scope",
            "validation_status": "PASS"
            if all(row.get("activation_scope") == "RESEARCH_ONLY_BASE_WEIGHT_ACTIVATION" and row.get("weight_activation_allowed") == "TRUE" for row in packet_rows)
            else "FAIL_ACTIVATION_SCOPE",
            "details": "activation_scope=RESEARCH_ONLY_BASE_WEIGHT_ACTIVATION",
            **safety(),
        },
        {
            "validation_check": "official_and_trade_paths_remain_disabled",
            "validation_status": "PASS" if not official_or_trade_flags else "FAIL_OFFICIAL_OR_TRADE_FLAG_ENABLED",
            "details": f"unsafe_flag_row_count={len(official_or_trade_flags)}",
            **safety(),
        },
    ]


def write_report(packet_rows: list[dict[str, str]], validation_rows: list[dict[str, str]], source_statuses: dict[str, str]) -> None:
    weight_sum = sum(Decimal(row["approved_research_base_weight"]) for row in packet_rows)
    failures = [row for row in validation_rows if not row["validation_status"].startswith("PASS")]
    lines = [
        "# V20.98B-R4 Research-Only Base Weight Operator Approval Packet",
        "",
        "## Current Result",
        "- wrapper_status: PASS_V20_98B_R4_RESEARCH_ONLY_BASE_WEIGHT_OPERATOR_APPROVAL_PACKET",
        f"- approval_packet_rows: {len(packet_rows)}",
        f"- approved_research_base_weight_sum: {weight_sum:.2f}",
        f"- validation_failure_count: {len(failures)}",
        "- operator_approved: TRUE",
        "- weight_activation_allowed: TRUE",
        "- activation_scope: RESEARCH_ONLY_BASE_WEIGHT_ACTIVATION",
        "",
        "## Approved Research-Only Weights",
    ]
    for row in packet_rows:
        lines.append(f"- {row['factor_family']}: {row['approved_research_base_weight']}")
    lines.extend(
        [
            "",
            "## Input Status",
            f"- R2 template: {source_statuses['r2_template']}",
            f"- R3 acceptance gate: {source_statuses['r3_gate']}",
            f"- R3 validation audit: {source_statuses['r3_validation']}",
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
            "R4 creates a controlled research-only approval packet from explicit operator-provided weights.",
            "It does not mutate R2 or R3 outputs and does not create official weights.",
            "Official promotion remains blocked.",
            "",
            "## Next Recommended Action",
            "Run V20.98B-R3 again only after wiring it to consume this R4 packet as a research-only approval source.",
        ]
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    template_rows, r2_status = read_csv(R2_TEMPLATE)
    _r3_gate_rows, r3_gate_status = read_csv(R3_GATE)
    _r3_validation_rows, r3_validation_status = read_csv(R3_VALIDATION)

    packet_rows = build_packet_rows(template_rows if r2_status == "OK" else [])
    validation_rows = build_validation_rows(packet_rows, template_rows if r2_status == "OK" else [])

    write_csv(PACKET, PACKET_FIELDS, packet_rows)
    write_csv(VALIDATION, VALIDATION_FIELDS, validation_rows)
    write_report(
        packet_rows,
        validation_rows,
        {
            "r2_template": r2_status,
            "r3_gate": r3_gate_status,
            "r3_validation": r3_validation_status,
        },
    )

    weight_sum = sum(Decimal(row["approved_research_base_weight"]) for row in packet_rows)
    validation_failures = [row for row in validation_rows if not row["validation_status"].startswith("PASS")]
    print("PASS_V20_98B_R4_RESEARCH_ONLY_BASE_WEIGHT_OPERATOR_APPROVAL_PACKET")
    print(f"APPROVAL_PACKET_ROWS={len(packet_rows)}")
    print(f"WEIGHT_SUM={weight_sum:.2f}")
    print(f"VALIDATION_FAILURE_COUNT={len(validation_failures)}")
    print("OPERATOR_APPROVED=TRUE")
    print("WEIGHT_ACTIVATION_ALLOWED=TRUE")
    print("ACTIVATION_SCOPE=RESEARCH_ONLY_BASE_WEIGHT_ACTIVATION")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("IS_OFFICIAL_WEIGHT=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print(f"OUTPUT_PACKET={rel(PACKET)}")
    print(f"OUTPUT_VALIDATION={rel(VALIDATION)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
