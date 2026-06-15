#!/usr/bin/env python
"""V20.157 shadow weight delta reduction repair.

Shrinks V20.154 research-only shadow deltas after V20.156 identified unstable
ranking impact. This stage creates a reduced shadow proposal only; it does not
create new proposal rows, add factors, mutate official weights/rankings, or
fabricate evidence.
"""

from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

V156_REVIEW = FACTORS / "V20_156_SHADOW_RANKING_STABILITY_REVIEW.csv"
V156_OPERATOR = FACTORS / "V20_156_SHADOW_RANKING_OPERATOR_REVIEW_PACKET.csv"
V156_GUARDRAIL = FACTORS / "V20_156_SHADOW_RANKING_IMPACT_GUARDRAIL_AUDIT.csv"
V156_LOW_CONF = FACTORS / "V20_156_SHADOW_RANKING_LOW_CONFIDENCE_AUDIT.csv"
V156_GATE = FACTORS / "V20_156_SHADOW_RANKING_NEXT_GATE.csv"

V154_PROPOSAL = FACTORS / "V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv"
V154_GATE = FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_GATE.csv"
V154_SAFETY = FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_SAFETY_AUDIT.csv"

OUT_REPAIR = FACTORS / "V20_157_SHADOW_WEIGHT_DELTA_REDUCTION_REPAIR.csv"
OUT_PROPOSAL = FACTORS / "V20_157_REDUCED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv"
OUT_GATE = FACTORS / "V20_157_DELTA_REDUCTION_GATE.csv"
OUT_SOURCE = FACTORS / "V20_157_DELTA_REDUCTION_SOURCE_AUDIT.csv"
OUT_SAFETY = FACTORS / "V20_157_DELTA_REDUCTION_SAFETY_AUDIT.csv"
OUT_LIMITATION = FACTORS / "V20_157_DELTA_REDUCTION_LIMITATION_AUDIT.csv"
REPORT = READ_CENTER / "V20_157_SHADOW_WEIGHT_DELTA_REDUCTION_REPAIR_REPORT.md"

REQUIRED_V156_STATUS = "WARN_V20_156_SHADOW_RANKING_IMPACT_TOO_UNSTABLE_FOR_EXPANSION"
PASS_STATUS = "PASS_V20_157_SHADOW_WEIGHT_DELTA_REDUCTION_READY_FOR_V20_158"
PARTIAL_STATUS = "PARTIAL_PASS_V20_157_SHADOW_WEIGHT_DELTA_REDUCTION_WITH_LIMITED_CONFIDENCE_READY_FOR_V20_158"
WARN_STATUS = "WARN_V20_157_NO_REDUCIBLE_SHADOW_DELTAS_FOUND"
BLOCKED_STATUS = "BLOCKED_V20_157_SHADOW_WEIGHT_DELTA_REDUCTION_REPAIR"
SCOPE = "RESEARCH_ONLY_LIMITED_CONSERVATIVE"

SAFETY_FIELDS = [
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "official_weight_change_created",
    "shadow_weight_proposal_created",
    "reduced_shadow_weight_proposal_created",
    "reduced_shadow_weight_proposal_scope",
    "shadow_weight_expansion_allowed",
    "weight_mutated",
    "real_book_action_created",
    "trade_action_created",
    "broker_execution_supported",
    "performance_claim_created",
]
SAFETY = {
    "formal_activation_allowed": "FALSE",
    "promotion_ready": "FALSE",
    "official_recommendation_created": "FALSE",
    "official_ranking_mutated": "FALSE",
    "official_weight_change_created": "FALSE",
    "shadow_weight_proposal_created": "TRUE",
    "reduced_shadow_weight_proposal_created": "TRUE",
    "reduced_shadow_weight_proposal_scope": SCOPE,
    "shadow_weight_expansion_allowed": "FALSE",
    "weight_mutated": "FALSE",
    "real_book_action_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "performance_claim_created": "FALSE",
}
COMMON = {
    **SAFETY,
    "research_only": "TRUE",
    "staging_review_only": "TRUE",
    "delta_reduction_repair_only": "TRUE",
    "audit_only": "TRUE",
}

REPAIR_FIELDS = [
    "factor_family",
    "factor_name",
    "evidence_source",
    "original_shadow_proposed_weight",
    "original_proposed_delta",
    "reduced_shadow_proposed_weight",
    "reduced_proposed_delta",
    "original_max_allowed_delta",
    "reduced_max_allowed_delta",
    "reduction_multiplier",
    "confidence_level",
    "evidence_quality",
    "rank_impact_severity_from_v20_156",
    "top20_turnover_rate_from_v20_156",
    "delta_reduction_reason",
    "conservative_mode_applied",
    "usable_for_reduced_shadow_simulation",
    "usable_for_official_weight_change",
    "official_weight_change_blocked_reason",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "v20_156_gate_consumed",
    "v20_156_status",
    "required_next_action_confirmed",
    "continued_shadow_research_confirmed",
    "shadow_weight_expansion_blocked",
    "official_weight_change_blocked",
    *SAFETY_FIELDS,
    "input_proposal_row_count",
    "reduced_proposal_row_count",
    "reducible_delta_count",
    "limited_confidence_row_count",
    "low_confidence_row_count",
    "max_reduction_multiplier",
    "official_weight_change_eligible_count",
    "no_delta_increase_detected",
    "no_new_proposal_rows_created",
    "no_new_factor_included",
    "no_official_weight_mutation",
    "no_official_ranking_mutation",
    "no_official_recommendation_created",
    "no_real_book_action_created",
    "no_trade_action_created",
    "no_broker_action_created",
    "no_outcomes_fabricated",
    "no_benchmarks_fabricated",
    "no_factor_contribution_fabricated",
    "no_performance_claim_created",
    "no_upstream_outputs_mutated",
    "v20_158_reduced_shadow_simulation_allowed",
    "blocking_reason",
    "final_status",
    "research_only",
    "staging_review_only",
    "delta_reduction_repair_only",
    "audit_only",
]
SOURCE_FIELDS = [
    "source_audit_id",
    "source_artifact",
    "source_exists",
    "source_non_empty",
    "row_count",
    "source_sha256",
    "source_role",
    "source_status",
    "exclusion_reason",
    *COMMON.keys(),
]
SAFETY_AUDIT_FIELDS = [
    "safety_check_id",
    "safety_check",
    "expected_value",
    "actual_value",
    "safety_passed",
    *COMMON.keys(),
]
LIMITATION_FIELDS = [
    "limitation_id",
    "limitation_reason",
    "affected_row_count",
    "requires_operator_review",
    "recommended_next_stage",
    *COMMON.keys(),
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def truthy(value: object) -> bool:
    return clean(value).upper() == "TRUE"


def num(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(clean(value))
    except ValueError:
        return default
    return default if math.isnan(parsed) or math.isinf(parsed) else parsed


def fmt(value: float) -> str:
    return f"{value:.10f}"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists() or path.stat().st_size == 0:
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{key: clean(value) for key, value in row.items()} for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def sha_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def upstream_inputs() -> list[Path]:
    return [V156_REVIEW, V156_OPERATOR, V156_GUARDRAIL, V156_LOW_CONF, V156_GATE, V154_PROPOSAL, V154_GATE, V154_SAFETY]


def upstream_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in upstream_inputs() if path.exists()}


def source_audit_rows() -> list[dict[str, str]]:
    sources = [
        (V156_REVIEW, "V20_156_STABILITY_REVIEW"),
        (V156_OPERATOR, "V20_156_OPERATOR_PACKET"),
        (V156_GUARDRAIL, "V20_156_GUARDRAIL_AUDIT"),
        (V156_LOW_CONF, "V20_156_LOW_CONFIDENCE_AUDIT"),
        (V156_GATE, "V20_156_NEXT_GATE"),
        (V154_PROPOSAL, "V20_154_SHADOW_PROPOSAL"),
        (V154_GATE, "V20_154_PROPOSAL_GATE"),
        (V154_SAFETY, "V20_154_SAFETY_AUDIT"),
    ]
    rows = []
    for index, (path, role) in enumerate(sources, start=1):
        data, fields = read_csv(path)
        exists = path.exists()
        non_empty = exists and path.stat().st_size > 0
        ok = bool(fields) and non_empty
        rows.append({
            "source_audit_id": f"V20_157_SOURCE_AUDIT_{index:03d}",
            "source_artifact": rel(path),
            "source_exists": tf(exists),
            "source_non_empty": tf(non_empty),
            "row_count": str(len(data)),
            "source_sha256": sha_file(path),
            "source_role": role,
            "source_status": "PASS" if ok else "BLOCKED_MISSING_OR_EMPTY",
            "exclusion_reason": "" if ok else "MISSING_OR_EMPTY_SOURCE",
            **COMMON,
        })
    return rows


def multiplier_for(confidence: str, severity: str) -> float:
    if severity == "EXTREME":
        return 0.25
    if confidence == "LOW":
        return 0.25
    if confidence == "LIMITED":
        return 0.35
    return 0.50


def build_repair_rows(proposals: list[dict[str, str]], review: dict[str, str]) -> list[dict[str, str]]:
    severity = review.get("rank_impact_severity", "")
    turnover = review.get("top20_turnover_rate", "")
    rows = []
    for proposal in proposals:
        original_delta = num(proposal.get("proposed_delta"))
        current_weight = num(proposal.get("current_research_weight"))
        multiplier = multiplier_for(proposal.get("confidence_level", ""), severity)
        reduced_delta = original_delta * multiplier
        reduced_weight = current_weight + reduced_delta
        original_max = abs(num(proposal.get("max_allowed_delta")))
        reduced_max = original_max * multiplier
        reason = "EXTREME_RANK_IMPACT_FORCE_0_25_MULTIPLIER" if severity == "EXTREME" else f"{proposal.get('confidence_level')}_CONFIDENCE_DELTA_REDUCTION"
        rows.append({
            "factor_family": proposal.get("factor_family", ""),
            "factor_name": proposal.get("factor_name", ""),
            "evidence_source": proposal.get("evidence_source", ""),
            "original_shadow_proposed_weight": proposal.get("shadow_proposed_weight", ""),
            "original_proposed_delta": fmt(original_delta),
            "reduced_shadow_proposed_weight": fmt(reduced_weight),
            "reduced_proposed_delta": fmt(reduced_delta),
            "original_max_allowed_delta": fmt(original_max),
            "reduced_max_allowed_delta": fmt(reduced_max),
            "reduction_multiplier": fmt(multiplier),
            "confidence_level": proposal.get("confidence_level", ""),
            "evidence_quality": proposal.get("evidence_quality", ""),
            "rank_impact_severity_from_v20_156": severity,
            "top20_turnover_rate_from_v20_156": turnover,
            "delta_reduction_reason": reason,
            "conservative_mode_applied": "TRUE",
            "usable_for_reduced_shadow_simulation": tf(abs(original_delta) > 0),
            "usable_for_official_weight_change": "FALSE",
            "official_weight_change_blocked_reason": "OFFICIAL_WEIGHT_CHANGE_NOT_ALLOWED_V20_157_RESEARCH_ONLY_CONSERVATIVE_REPAIR",
            **COMMON,
        })
    return rows


def safety_audit_rows(upstream_mutated: bool, delta_increase: bool, official_true: bool, row_count_ok: bool, factors_ok: bool) -> list[dict[str, str]]:
    checks = [
        ("formal_activation_allowed", "FALSE", "FALSE"),
        ("promotion_ready", "FALSE", "FALSE"),
        ("official_recommendation_created", "FALSE", "FALSE"),
        ("official_ranking_mutated", "FALSE", "FALSE"),
        ("official_weight_change_created", "FALSE", "FALSE"),
        ("shadow_weight_proposal_created", "TRUE", "TRUE"),
        ("reduced_shadow_weight_proposal_created", "TRUE", "TRUE"),
        ("reduced_shadow_weight_proposal_scope", SCOPE, SCOPE),
        ("shadow_weight_expansion_allowed", "FALSE", "FALSE"),
        ("delta_increase_detected", "FALSE", tf(delta_increase)),
        ("official_weight_change_eligible", "FALSE", tf(official_true)),
        ("new_proposal_rows_created", "FALSE", tf(not row_count_ok)),
        ("new_factor_included", "FALSE", tf(not factors_ok)),
        ("upstream_outputs_mutated", "FALSE", tf(upstream_mutated)),
    ]
    rows = []
    for index, (check, expected, actual) in enumerate(checks, start=1):
        rows.append({
            "safety_check_id": f"V20_157_SAFETY_{index:03d}",
            "safety_check": check,
            "expected_value": expected,
            "actual_value": actual,
            "safety_passed": tf(expected == actual),
            **COMMON,
        })
    return rows


def safety_issue_count(groups: list[list[dict[str, str]]]) -> int:
    count = 0
    for rows in groups:
        for row in rows:
            for field in SAFETY_FIELDS:
                if field in {"shadow_weight_proposal_created", "reduced_shadow_weight_proposal_created"}:
                    if row.get(field) != "TRUE":
                        count += 1
                elif field == "reduced_shadow_weight_proposal_scope":
                    if row.get(field) != SCOPE:
                        count += 1
                elif field == "shadow_weight_expansion_allowed":
                    if row.get(field) != "FALSE":
                        count += 1
                elif truthy(row.get(field)):
                    count += 1
    return count


def limitation_rows(repair_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    limited = sum(1 for row in repair_rows if row["confidence_level"] in {"LOW", "LIMITED"})
    return [{
        "limitation_id": "V20_157_LIMITATION_001",
        "limitation_reason": "LIMITED_CONFIDENCE_REDUCED_SHADOW_PROPOSAL_REQUIRES_RE_SIMULATION",
        "affected_row_count": str(limited),
        "requires_operator_review": "TRUE",
        "recommended_next_stage": "V20.158_REDUCED_SHADOW_WEIGHT_RANKING_SIMULATION",
        **COMMON,
    }]


def write_report(status: str, row_count: int, max_multiplier: float) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.157 Shadow Weight Delta Reduction Repair Report",
        "",
        f"- wrapper_status: {status}",
        f"- reduced_proposal_row_count: {row_count}",
        f"- max_reduction_multiplier: {fmt(max_multiplier)}",
        f"- reduced_shadow_weight_proposal_scope: {SCOPE}",
        "- official_weight_change_created: FALSE",
        "- shadow_weight_expansion_allowed: FALSE",
        "",
        "The repair only reduces existing V20.154 deltas and preserves research-only conservative scope.",
    ]) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_157_DELTA_REDUCTION_GATE_001",
        "v20_156_gate_consumed": "FALSE",
        "v20_156_status": "",
        "required_next_action_confirmed": "FALSE",
        "continued_shadow_research_confirmed": "FALSE",
        "shadow_weight_expansion_blocked": "FALSE",
        "official_weight_change_blocked": "FALSE",
        **SAFETY,
        "input_proposal_row_count": "0",
        "reduced_proposal_row_count": "0",
        "reducible_delta_count": "0",
        "limited_confidence_row_count": "0",
        "low_confidence_row_count": "0",
        "max_reduction_multiplier": "0",
        "official_weight_change_eligible_count": "0",
        "no_delta_increase_detected": "TRUE",
        "no_new_proposal_rows_created": "TRUE",
        "no_new_factor_included": "TRUE",
        "no_official_weight_mutation": "TRUE",
        "no_official_ranking_mutation": "TRUE",
        "no_official_recommendation_created": "TRUE",
        "no_real_book_action_created": "TRUE",
        "no_trade_action_created": "TRUE",
        "no_broker_action_created": "TRUE",
        "no_outcomes_fabricated": "TRUE",
        "no_benchmarks_fabricated": "TRUE",
        "no_factor_contribution_fabricated": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "v20_158_reduced_shadow_simulation_allowed": "FALSE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        "research_only": "TRUE",
        "staging_review_only": "TRUE",
        "delta_reduction_repair_only": "TRUE",
        "audit_only": "TRUE",
    }
    write_csv(OUT_REPAIR, REPAIR_FIELDS, [])
    write_csv(OUT_PROPOSAL, REPAIR_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SOURCE, SOURCE_FIELDS, [])
    write_csv(OUT_SAFETY, SAFETY_AUDIT_FIELDS, [])
    write_csv(OUT_LIMITATION, LIMITATION_FIELDS, [])
    write_report(BLOCKED_STATUS, 0, 0)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = upstream_hashes()
    missing = [path for path in upstream_inputs() if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    review_rows, _ = read_csv(V156_REVIEW)
    gate_rows, _ = read_csv(V156_GATE)
    proposal_rows, _ = read_csv(V154_PROPOSAL)
    if not all([review_rows, gate_rows, proposal_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    review = review_rows[0]
    gate_in = gate_rows[0]
    v156_status = gate_in.get("final_status", "")
    req_ok = gate_in.get("required_next_action") == "REQUEST_SHADOW_WEIGHT_DELTA_REDUCTION" and review.get("required_next_action") == "REQUEST_SHADOW_WEIGHT_DELTA_REDUCTION"
    continued_ok = gate_in.get("allow_continued_shadow_research") == "TRUE" and review.get("allow_continued_shadow_research") == "TRUE"
    expansion_blocked = gate_in.get("allow_shadow_weight_expansion") == "FALSE" and review.get("allow_shadow_weight_expansion") == "FALSE"
    official_blocked = gate_in.get("allow_official_weight_change") == "FALSE" and review.get("allow_official_weight_change") == "FALSE"
    if v156_status != REQUIRED_V156_STATUS or not all([req_ok, continued_ok, expansion_blocked, official_blocked]):
        return emit_blocked("V20_156_GATE_REQUIREMENTS_NOT_MET")
    official_true = any(row.get("usable_for_official_weight_change") == "TRUE" for row in proposal_rows)
    if official_true:
        return emit_blocked("OFFICIAL_WEIGHT_CHANGE_ELIGIBILITY_TRUE_IN_INPUT")

    repair_rows = build_repair_rows(proposal_rows, review)
    source_rows = source_audit_rows()
    upstream_mutated = before != upstream_hashes()
    delta_increase = any(abs(num(row["reduced_proposed_delta"])) > abs(num(row["original_proposed_delta"])) + 1e-12 for row in repair_rows)
    row_count_ok = len(repair_rows) == len(proposal_rows)
    factors_ok = {row["factor_family"] for row in repair_rows} == {row["factor_family"] for row in proposal_rows}
    safety_rows = safety_audit_rows(upstream_mutated, delta_increase, official_true, row_count_ok, factors_ok)
    limitations = limitation_rows(repair_rows)
    safety_count = safety_issue_count([repair_rows, source_rows, safety_rows, limitations])
    reducible_count = sum(1 for row in proposal_rows if abs(num(row.get("proposed_delta"))) > 0)
    limited_count = sum(1 for row in repair_rows if row["confidence_level"] == "LIMITED")
    low_count = sum(1 for row in repair_rows if row["confidence_level"] == "LOW")
    max_multiplier = max([num(row["reduction_multiplier"]) for row in repair_rows], default=0.0)
    if upstream_mutated or delta_increase or official_true or not row_count_ok or not factors_ok or safety_count:
        status = BLOCKED_STATUS
        blocking = "SAFETY_OR_DELTA_RULE_FAILURE"
    elif reducible_count == 0:
        status = WARN_STATUS
        blocking = ""
    elif low_count or limited_count:
        status = PARTIAL_STATUS
        blocking = ""
    else:
        status = PASS_STATUS
        blocking = ""
    next_allowed = status in {PASS_STATUS, PARTIAL_STATUS}
    gate = {
        "gate_check_id": "V20_157_DELTA_REDUCTION_GATE_001",
        "v20_156_gate_consumed": "TRUE",
        "v20_156_status": v156_status,
        "required_next_action_confirmed": tf(req_ok),
        "continued_shadow_research_confirmed": tf(continued_ok),
        "shadow_weight_expansion_blocked": tf(expansion_blocked),
        "official_weight_change_blocked": tf(official_blocked),
        **SAFETY,
        "input_proposal_row_count": str(len(proposal_rows)),
        "reduced_proposal_row_count": str(len(repair_rows)),
        "reducible_delta_count": str(reducible_count),
        "limited_confidence_row_count": str(limited_count),
        "low_confidence_row_count": str(low_count),
        "max_reduction_multiplier": fmt(max_multiplier),
        "official_weight_change_eligible_count": str(sum(1 for row in repair_rows if row["usable_for_official_weight_change"] == "TRUE")),
        "no_delta_increase_detected": tf(not delta_increase),
        "no_new_proposal_rows_created": tf(row_count_ok),
        "no_new_factor_included": tf(factors_ok),
        "no_official_weight_mutation": "TRUE",
        "no_official_ranking_mutation": "TRUE",
        "no_official_recommendation_created": "TRUE",
        "no_real_book_action_created": "TRUE",
        "no_trade_action_created": "TRUE",
        "no_broker_action_created": "TRUE",
        "no_outcomes_fabricated": "TRUE",
        "no_benchmarks_fabricated": "TRUE",
        "no_factor_contribution_fabricated": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_upstream_outputs_mutated": tf(not upstream_mutated),
        "v20_158_reduced_shadow_simulation_allowed": tf(next_allowed),
        "blocking_reason": blocking,
        "final_status": status,
        "research_only": "TRUE",
        "staging_review_only": "TRUE",
        "delta_reduction_repair_only": "TRUE",
        "audit_only": "TRUE",
    }
    write_csv(OUT_REPAIR, REPAIR_FIELDS, repair_rows)
    write_csv(OUT_PROPOSAL, REPAIR_FIELDS, repair_rows)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SOURCE, SOURCE_FIELDS, source_rows)
    write_csv(OUT_SAFETY, SAFETY_AUDIT_FIELDS, safety_rows)
    write_csv(OUT_LIMITATION, LIMITATION_FIELDS, limitations)
    write_report(status, len(repair_rows), max_multiplier)

    print(status)
    print("V20_156_GATE_CONSUMED=TRUE")
    print(f"REQUIRED_NEXT_ACTION_CONFIRMED={tf(req_ok)}")
    print(f"CONTINUED_SHADOW_RESEARCH_CONFIRMED={tf(continued_ok)}")
    print(f"SHADOW_WEIGHT_EXPANSION_BLOCKED={tf(expansion_blocked)}")
    print(f"OFFICIAL_WEIGHT_CHANGE_BLOCKED={tf(official_blocked)}")
    print(f"INPUT_PROPOSAL_ROW_COUNT={len(proposal_rows)}")
    print(f"REDUCED_PROPOSAL_ROW_COUNT={len(repair_rows)}")
    print(f"REDUCIBLE_DELTA_COUNT={reducible_count}")
    print(f"MAX_REDUCTION_MULTIPLIER={fmt(max_multiplier)}")
    print(f"OFFICIAL_WEIGHT_CHANGE_ELIGIBLE_COUNT={gate['official_weight_change_eligible_count']}")
    print(f"DELTA_INCREASE_DETECTED={tf(delta_increase)}")
    print(f"NEW_PROPOSAL_ROWS_CREATED={tf(not row_count_ok)}")
    print(f"NEW_FACTOR_INCLUDED={tf(not factors_ok)}")
    print("OFFICIAL_WEIGHT_MUTATION=FALSE")
    print("OFFICIAL_RANKING_MUTATION=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_ACTION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_ACTION_CREATED=FALSE")
    print("OUTCOMES_FABRICATED=0")
    print("BENCHMARKS_FABRICATED=0")
    print("FACTOR_CONTRIBUTION_FABRICATED=0")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print(f"REDUCED_SHADOW_WEIGHT_PROPOSAL_SCOPE={SCOPE}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    print(f"SAFETY_TRUE_COUNT={safety_count}")
    print(f"V20_158_REDUCED_SHADOW_SIMULATION_ALLOWED={tf(next_allowed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
