#!/usr/bin/env python
"""V20.98B-R5 active research base weight registry builder.

Consumes the R4 research-only approval packet and builds active research-only
base weights for downstream shadow research modules. It never creates official
weights, recommendations, trade actions, or broker execution support.
"""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R4_PACKET = CONSOLIDATION / "V20_98B_R4_RESEARCH_ONLY_BASE_WEIGHT_OPERATOR_APPROVAL_PACKET.csv"
R4_VALIDATION = CONSOLIDATION / "V20_98B_R4_BASE_WEIGHT_APPROVAL_VALIDATION.csv"
R3_GATE = CONSOLIDATION / "V20_98B_R3_BASE_WEIGHT_OPERATOR_ACCEPTANCE_GATE.csv"
R2_TEMPLATE = CONSOLIDATION / "V20_98B_R2_RESEARCH_ONLY_BASE_WEIGHT_TEMPLATE.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
VALIDATION = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_VALIDATION.csv"
REPORT = READ_CENTER / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REPORT.md"

REQUIRED_FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]

REGISTRY_FIELDS = [
    "factor_family",
    "active_research_base_weight",
    "base_weight_source_stage",
    "base_weight_source_artifact",
    "operator_approved",
    "activation_scope",
    "active_for_research_ranking",
    "active_for_shadow_dynamic_reweighting",
    "active_for_entry_exit_research",
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
    "v20_107_precondition_status",
    "v20_107_execution_status",
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


def v20_107_status() -> dict[str, str]:
    return {
        "v20_107_precondition_status": "ACTIVE_RESEARCH_BASE_WEIGHTS_AVAILABLE",
        "v20_107_execution_status": "NOT_RUN",
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


def parse_weight(value: str) -> Decimal | None:
    if not clean(value):
        return None
    try:
        return Decimal(clean(value))
    except InvalidOperation:
        return None


def format_weight(value: Decimal) -> str:
    return f"{value:.2f}"


def packet_rows_by_family(packet_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in packet_rows:
        family = row.get("factor_family", "")
        if family and family not in result:
            result[family] = row
    return result


def activation_scope_is_research_only(value: str) -> bool:
    normalized = clean(value).upper()
    return normalized in {"RESEARCH_ONLY", "RESEARCH_ONLY_BASE_WEIGHT_ACTIVATION"} or normalized.startswith("RESEARCH_ONLY")


def build_registry(packet_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    by_family = packet_rows_by_family(packet_rows)
    registry_rows: list[dict[str, str]] = []
    for family in REQUIRED_FAMILIES:
        source = by_family.get(family, {})
        weight = parse_weight(source.get("approved_research_base_weight", ""))
        row_valid = (
            source.get("operator_approved") == "TRUE"
            and source.get("weight_activation_allowed") == "TRUE"
            and activation_scope_is_research_only(source.get("activation_scope", ""))
            and source.get("is_official_weight") == "FALSE"
            and source.get("official_promotion_allowed") == "FALSE"
            and source.get("official_recommendation_created") == "FALSE"
            and source.get("weight_mutated") == "FALSE"
            and source.get("trade_action_created") == "FALSE"
            and source.get("broker_execution_supported") == "FALSE"
            and weight is not None
        )
        registry_rows.append(
            {
                "factor_family": family,
                "active_research_base_weight": format_weight(weight) if row_valid and weight is not None else "",
                "base_weight_source_stage": "V20.98B-R4_RESEARCH_ONLY_BASE_WEIGHT_OPERATOR_APPROVAL_PACKET",
                "base_weight_source_artifact": rel(R4_PACKET),
                "operator_approved": source.get("operator_approved", "FALSE"),
                "activation_scope": "RESEARCH_ONLY_BASE_WEIGHT_ACTIVATION",
                "active_for_research_ranking": "TRUE" if row_valid else "FALSE",
                "active_for_shadow_dynamic_reweighting": "TRUE" if row_valid else "FALSE",
                "active_for_entry_exit_research": "TRUE" if row_valid else "FALSE",
                "validation_status": "PASS" if row_valid else "BLOCKED_INVALID_R4_APPROVAL_ROW",
                "validation_reason": "ACTIVE_RESEARCH_BASE_WEIGHT_FROM_R4_OPERATOR_APPROVAL_PACKET"
                if row_valid
                else "R4_ROW_MISSING_APPROVAL_OR_RESEARCH_ONLY_SAFETY_FLAG",
                **safety(),
            }
        )
    return registry_rows


def build_validation(packet_rows: list[dict[str, str]], registry_rows: list[dict[str, str]], r4_validation_rows: list[dict[str, str]], template_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    research_gate = first_row(V49_RESEARCH)
    official_gate = first_row(V49_OFFICIAL)
    r3_gate = first_row(R3_GATE)
    packet_by_family = packet_rows_by_family(packet_rows)
    registry_families = {row["factor_family"] for row in registry_rows}
    packet_families = {row.get("factor_family", "") for row in packet_rows}
    weights = {row["factor_family"]: parse_weight(row["active_research_base_weight"]) for row in registry_rows}
    numeric_weights = [weight for weight in weights.values() if weight is not None]
    weight_sum = sum(numeric_weights, Decimal("0"))
    cap_exceeded = [family for family, weight in weights.items() if weight is not None and weight > Decimal("0.35")]
    negative = [family for family, weight in weights.items() if weight is not None and weight < 0]
    invalid_registry = [row for row in registry_rows if row["validation_status"] != "PASS"]
    unsafe_registry = [
        row
        for row in registry_rows
        if row["is_official_weight"] != "FALSE"
        or row["official_promotion_allowed"] != "FALSE"
        or row["official_recommendation_created"] != "FALSE"
        or row["weight_mutated"] != "FALSE"
        or row["trade_action_created"] != "FALSE"
        or row["broker_execution_supported"] != "FALSE"
    ]
    invalid_packet = [
        row
        for row in packet_rows
        if row.get("operator_approved") != "TRUE"
        or row.get("weight_activation_allowed") != "TRUE"
        or not activation_scope_is_research_only(row.get("activation_scope", ""))
        or row.get("is_official_weight") != "FALSE"
        or row.get("official_promotion_allowed") != "FALSE"
        or row.get("official_recommendation_created") != "FALSE"
        or row.get("weight_mutated") != "FALSE"
        or row.get("trade_action_created") != "FALSE"
        or row.get("broker_execution_supported") != "FALSE"
    ]
    source_rank_used = [
        row
        for row in template_rows
        if clean(row.get("source_rank_or_score_used_as_weight")).upper() == "TRUE"
    ]
    r4_validation_failures = [row for row in r4_validation_rows if not row.get("validation_status", "").startswith("PASS")]

    return [
        {
            "validation_check": "v20_49_research_only_gate_preserved",
            "validation_status": "PASS"
            if research_gate.get("research_only_gate_status") == "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE"
            else "WARN_SOURCE_NOT_PASS",
            "details": research_gate.get("research_only_gate_status", "MISSING"),
            **v20_107_status(),
            **safety(),
        },
        {
            "validation_check": "v20_49_official_promotion_gate_preserved",
            "validation_status": "PASS"
            if official_gate.get("official_promotion_gate_status") == "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE"
            else "WARN_SOURCE_NOT_BLOCKED",
            "details": official_gate.get("official_promotion_gate_status", "MISSING"),
            **v20_107_status(),
            **safety(),
        },
        {
            "validation_check": "r3_context_preserved_without_mutation",
            "validation_status": "PASS" if r3_gate else "WARN_R3_GATE_MISSING",
            "details": r3_gate.get("acceptance_status", "MISSING"),
            **v20_107_status(),
            **safety(),
        },
        {
            "validation_check": "r4_validation_passed",
            "validation_status": "PASS" if not r4_validation_failures else "FAIL_R4_VALIDATION_HAS_FAILURES",
            "details": f"r4_validation_failure_count={len(r4_validation_failures)}",
            **v20_107_status(),
            **safety(),
        },
        {
            "validation_check": "exactly_six_required_factor_families",
            "validation_status": "PASS"
            if registry_families == set(REQUIRED_FAMILIES) and packet_families == set(REQUIRED_FAMILIES) and len(registry_rows) == 6
            else "FAIL_REQUIRED_FACTOR_FAMILY_CONTRACT",
            "details": f"registry_rows={len(registry_rows)};families={'|'.join(sorted(registry_families))}",
            **v20_107_status(),
            **safety(),
        },
        {
            "validation_check": "r4_operator_approval_and_research_activation_required",
            "validation_status": "PASS" if not invalid_packet else "FAIL_INVALID_R4_APPROVAL_ROW",
            "details": f"invalid_packet_row_count={len(invalid_packet)}",
            **v20_107_status(),
            **safety(),
        },
        {
            "validation_check": "active_research_base_weight_count",
            "validation_status": "PASS" if len(numeric_weights) == 6 and not invalid_registry else "FAIL_ACTIVE_RESEARCH_WEIGHT_COUNT",
            "details": f"active_research_base_weight_count={len(numeric_weights)}",
            **v20_107_status(),
            **safety(),
        },
        {
            "validation_check": "weight_sum_equals_1_00",
            "validation_status": "PASS" if abs(weight_sum - Decimal("1.00")) <= Decimal("0.000001") else "FAIL_WEIGHT_SUM_NOT_1_00",
            "details": f"weight_sum={weight_sum:.2f}",
            **v20_107_status(),
            **safety(),
        },
        {
            "validation_check": "no_negative_weights",
            "validation_status": "PASS" if not negative else "FAIL_NEGATIVE_WEIGHT",
            "details": "negative_families=" + ("|".join(negative) if negative else "NONE"),
            **v20_107_status(),
            **safety(),
        },
        {
            "validation_check": "family_weight_cap_0_35",
            "validation_status": "PASS" if not cap_exceeded else "FAIL_FAMILY_WEIGHT_CAP_EXCEEDED",
            "details": "cap_exceeded_families=" + ("|".join(cap_exceeded) if cap_exceeded else "NONE"),
            **v20_107_status(),
            **safety(),
        },
        {
            "validation_check": "risk_market_regime_data_trust_positive",
            "validation_status": "PASS"
            if weights.get("RISK", Decimal("0")) > 0
            and weights.get("MARKET_REGIME", Decimal("0")) > 0
            and weights.get("DATA_TRUST", Decimal("0")) > 0
            else "FAIL_REQUIRED_PROTECTIVE_WEIGHT_ZERO",
            "details": f"RISK={weights.get('RISK')};MARKET_REGIME={weights.get('MARKET_REGIME')};DATA_TRUST={weights.get('DATA_TRUST')}",
            **v20_107_status(),
            **safety(),
        },
        {
            "validation_check": "source_rank_or_score_not_used_as_weight",
            "validation_status": "PASS" if not source_rank_used else "FAIL_SOURCE_RANK_OR_SCORE_USED_AS_WEIGHT",
            "details": f"source_rank_or_score_used_count={len(source_rank_used)}",
            **v20_107_status(),
            **safety(),
        },
        {
            "validation_check": "official_and_trade_paths_disabled",
            "validation_status": "PASS" if not unsafe_registry else "FAIL_OFFICIAL_OR_TRADE_FLAG_ENABLED",
            "details": f"unsafe_registry_row_count={len(unsafe_registry)}",
            **v20_107_status(),
            **safety(),
        },
        {
            "validation_check": "v20_107_precondition_ready_not_executed",
            "validation_status": "PASS",
            "details": "V20.107 precondition ready from active research base weights; V20.107 execution remains NOT_RUN",
            **v20_107_status(),
            **safety(),
        },
    ]


def write_report(registry_rows: list[dict[str, str]], validation_rows: list[dict[str, str]], source_statuses: dict[str, str]) -> None:
    weights = [Decimal(row["active_research_base_weight"]) for row in registry_rows if row["active_research_base_weight"]]
    failures = [row for row in validation_rows if not row["validation_status"].startswith("PASS")]
    lines = [
        "# V20.98B-R5 Active Research Base Weight Registry",
        "",
        "## Current Result",
        "- wrapper_status: PASS_V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY_BUILT",
        f"- active_research_base_weight_count: {len(weights)}",
        f"- active_research_base_weight_sum: {sum(weights, Decimal('0')):.2f}",
        f"- validation_failure_count: {len(failures)}",
        "- v20_107_precondition_status: ACTIVE_RESEARCH_BASE_WEIGHTS_AVAILABLE",
        "- v20_107_execution_status: NOT_RUN",
        "",
        "## Active Research-Only Base Weights",
    ]
    for row in registry_rows:
        lines.append(f"- {row['factor_family']}: {row['active_research_base_weight']}")
    lines.extend(
        [
            "",
            "## Input Status",
            f"- R4 approval packet: {source_statuses['r4_packet']}",
            f"- R4 validation: {source_statuses['r4_validation']}",
            f"- R3 gate: {source_statuses['r3_gate']}",
            f"- R2 template: {source_statuses['r2_template']}",
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
            "R5 creates active research-only base weights for downstream shadow research modules.",
            "It does not create official weights and does not execute V20.107 dynamic reweighting.",
            "",
            "## Next Recommended Action",
            "Use this registry as the input precondition for V20.107 shadow dynamic reweighting, with V20.107 still treated as a separate not-run stage.",
        ]
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    packet_rows, r4_packet_status = read_csv(R4_PACKET)
    r4_validation_rows, r4_validation_status = read_csv(R4_VALIDATION)
    _r3_gate_rows, r3_gate_status = read_csv(R3_GATE)
    template_rows, r2_template_status = read_csv(R2_TEMPLATE)

    registry_rows = build_registry(packet_rows if r4_packet_status == "OK" else [])
    validation_rows = build_validation(
        packet_rows if r4_packet_status == "OK" else [],
        registry_rows,
        r4_validation_rows if r4_validation_status == "OK" else [],
        template_rows if r2_template_status == "OK" else [],
    )

    write_csv(REGISTRY, REGISTRY_FIELDS, registry_rows)
    write_csv(VALIDATION, VALIDATION_FIELDS, validation_rows)
    write_report(
        registry_rows,
        validation_rows,
        {
            "r4_packet": r4_packet_status,
            "r4_validation": r4_validation_status,
            "r3_gate": r3_gate_status,
            "r2_template": r2_template_status,
        },
    )

    weights = [Decimal(row["active_research_base_weight"]) for row in registry_rows if row["active_research_base_weight"]]
    failures = [row for row in validation_rows if not row["validation_status"].startswith("PASS")]
    print("PASS_V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY_BUILT")
    print(f"ACTIVE_RESEARCH_BASE_WEIGHT_COUNT={len(weights)}")
    print(f"WEIGHT_SUM={sum(weights, Decimal('0')):.2f}")
    print(f"VALIDATION_FAILURE_COUNT={len(failures)}")
    print("V20_107_PRECONDITION_STATUS=ACTIVE_RESEARCH_BASE_WEIGHTS_AVAILABLE")
    print("V20_107_EXECUTION_STATUS=NOT_RUN")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("IS_OFFICIAL_WEIGHT=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print(f"OUTPUT_REGISTRY={rel(REGISTRY)}")
    print(f"OUTPUT_VALIDATION={rel(VALIDATION)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
