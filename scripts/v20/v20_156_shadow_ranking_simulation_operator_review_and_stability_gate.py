#!/usr/bin/env python
"""V20.156 shadow ranking simulation operator review and stability gate.

Builds a research-only stability review and operator review packet for the
V20.155 limited shadow ranking simulation. This stage does not mutate official
rankings, official weights, recommendations, real-book actions, trades, broker
actions, performance claims, or upstream V20.109-V20.155 outputs.
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

IN_SIM = FACTORS / "V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION.csv"
IN_DELTA = FACTORS / "V20_155_SHADOW_VS_BASELINE_RANK_DELTA.csv"
IN_GATE = FACTORS / "V20_155_SHADOW_RANKING_SIMULATION_GATE.csv"
IN_SOURCE = FACTORS / "V20_155_SHADOW_RANKING_SOURCE_AUDIT.csv"
IN_SAFETY = FACTORS / "V20_155_SHADOW_RANKING_SAFETY_AUDIT.csv"
IN_LIMITATION = FACTORS / "V20_155_SHADOW_RANKING_LIMITATION_AUDIT.csv"

OUT_REVIEW = FACTORS / "V20_156_SHADOW_RANKING_STABILITY_REVIEW.csv"
OUT_OPERATOR = FACTORS / "V20_156_SHADOW_RANKING_OPERATOR_REVIEW_PACKET.csv"
OUT_GUARDRAIL = FACTORS / "V20_156_SHADOW_RANKING_IMPACT_GUARDRAIL_AUDIT.csv"
OUT_LOW_CONF = FACTORS / "V20_156_SHADOW_RANKING_LOW_CONFIDENCE_AUDIT.csv"
OUT_GATE = FACTORS / "V20_156_SHADOW_RANKING_NEXT_GATE.csv"
REPORT = READ_CENTER / "V20_156_SHADOW_RANKING_SIMULATION_OPERATOR_REVIEW_AND_STABILITY_GATE_REPORT.md"

V155_ALLOWED = {
    "PASS_V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION_READY_FOR_V20_156",
    "PARTIAL_PASS_V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION_WITH_LIMITATIONS_READY_FOR_V20_156",
}
PASS_STATUS = "PASS_V20_156_SHADOW_RANKING_STABILITY_REVIEW_READY_FOR_OPERATOR_INPUT"
PARTIAL_STATUS = "PARTIAL_PASS_V20_156_SHADOW_RANKING_STABILITY_REVIEW_REQUIRES_DELTA_REDUCTION"
WARN_STATUS = "WARN_V20_156_SHADOW_RANKING_IMPACT_TOO_UNSTABLE_FOR_EXPANSION"
BLOCKED_STATUS = "BLOCKED_V20_156_SHADOW_RANKING_STABILITY_REVIEW"
SCOPE = "RESEARCH_ONLY_LIMITED"

HIGH_TURNOVER_THRESHOLD = 0.30
HIGH_AVG_DELTA_THRESHOLD = 8.0
EXTREME_MAX_DELTA_THRESHOLD = 25

SAFETY_FIELDS = [
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "official_weight_change_created",
    "shadow_weight_proposal_created",
    "shadow_ranking_simulation_created",
    "shadow_review_scope",
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
    "shadow_ranking_simulation_created": "TRUE",
    "shadow_review_scope": SCOPE,
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
    "operator_review_gate_only": "TRUE",
    "audit_only": "TRUE",
}

REVIEW_FIELDS = [
    "baseline_candidate_count",
    "shadow_candidate_count",
    "proposal_row_count",
    "low_confidence_proposal_count",
    "top20_overlap_count",
    "entered_top20_count",
    "exited_top20_count",
    "top20_turnover_rate",
    "max_absolute_rank_delta",
    "average_absolute_rank_delta",
    "affected_ticker_count",
    "score_recomputation_performed",
    "rank_impact_proxy_used",
    "rank_impact_severity",
    "stability_review_result",
    "operator_review_required",
    "allow_continued_shadow_research",
    "allow_shadow_weight_expansion",
    "allow_official_weight_change",
    "required_next_action",
    *COMMON.keys(),
]
OPERATOR_FIELDS = [
    "operator_option_id",
    "operator_option",
    "option_available",
    "recommended",
    "option_reason",
    *COMMON.keys(),
]
GUARDRAIL_FIELDS = [
    "guardrail_id",
    "guardrail_name",
    "observed_value",
    "threshold_value",
    "risk_level",
    "guardrail_passed",
    "guardrail_reason",
    *COMMON.keys(),
]
LOW_CONF_FIELDS = [
    "low_confidence_audit_id",
    "ticker",
    "proposal_confidence_level",
    "evidence_quality",
    "rank_delta",
    "score_delta",
    "low_confidence_reason",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "v20_155_gate_consumed",
    "v20_155_status",
    "v20_155_allowed_for_v20_156",
    *SAFETY_FIELDS,
    "confidence_risk",
    "rank_churn_risk",
    "rank_instability_risk",
    "outlier_rank_impact_risk",
    "operator_review_required",
    "allow_continued_shadow_research",
    "allow_shadow_weight_expansion",
    "allow_official_weight_change",
    "no_official_ranking_mutated",
    "no_official_weights_mutated",
    "no_official_recommendation_created",
    "no_real_book_action_created",
    "no_trade_action_created",
    "no_broker_action_created",
    "no_performance_claim_created",
    "no_outcomes_fabricated",
    "no_benchmarks_fabricated",
    "no_upstream_outputs_mutated",
    "required_next_action",
    "blocking_reason",
    "final_status",
    "research_only",
    "staging_review_only",
    "operator_review_gate_only",
    "audit_only",
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
    return [IN_SIM, IN_DELTA, IN_GATE, IN_SOURCE, IN_SAFETY, IN_LIMITATION]


def upstream_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in upstream_inputs() if path.exists()}


def risk_level(condition: bool) -> str:
    return "HIGH" if condition else "LOW"


def severity(high_count: int) -> str:
    if high_count >= 3:
        return "EXTREME"
    if high_count >= 2:
        return "HIGH"
    if high_count == 1:
        return "ELEVATED"
    return "LOW"


def build_review(summary: dict[str, str], gate: dict[str, str]) -> tuple[dict[str, str], dict[str, bool]]:
    proposal_count = int(num(summary.get("proposal_row_count")))
    low_count = int(num(summary.get("low_confidence_proposal_count")))
    entered = int(num(summary.get("entered_top20_count")))
    exited = int(num(summary.get("exited_top20_count")))
    baseline_count = int(num(summary.get("baseline_candidate_count")))
    top20_turnover = (entered + exited) / 20 if baseline_count else 0.0
    avg_delta = num(summary.get("average_absolute_rank_delta"))
    max_delta = num(summary.get("max_absolute_rank_delta"))
    risks = {
        "confidence": proposal_count > 0 and low_count == proposal_count,
        "churn": top20_turnover >= HIGH_TURNOVER_THRESHOLD,
        "instability": avg_delta >= HIGH_AVG_DELTA_THRESHOLD,
        "outlier": max_delta >= EXTREME_MAX_DELTA_THRESHOLD,
    }
    high_count = sum(1 for value in risks.values() if value)
    sev = severity(high_count)
    safety_ok = all([
        gate.get("no_official_ranking_mutated") == "TRUE",
        gate.get("no_official_weights_mutated") == "TRUE",
        gate.get("no_official_recommendation_created") == "TRUE",
        gate.get("no_real_book_action_created") == "TRUE",
        gate.get("no_trade_action_created") == "TRUE",
        gate.get("no_broker_action_created") == "TRUE",
        gate.get("no_performance_claim_created") == "TRUE",
        gate.get("no_upstream_outputs_mutated") == "TRUE",
    ])
    allow_continued = safety_ok
    allow_expansion = safety_ok and high_count == 0 and low_count == 0
    if risks["outlier"] or (risks["churn"] and risks["instability"]):
        result = "UNSTABLE_FOR_EXPANSION"
        next_action = "REQUEST_SHADOW_WEIGHT_DELTA_REDUCTION"
    elif risks["confidence"]:
        result = "REQUIRES_OPERATOR_REVIEW_LOW_CONFIDENCE"
        next_action = "REQUEST_MORE_FORWARD_OUTCOMES_BEFORE_EXPANSION"
    elif high_count:
        result = "REQUIRES_DELTA_REDUCTION"
        next_action = "REQUEST_SHADOW_WEIGHT_DELTA_REDUCTION"
    else:
        result = "STABLE_FOR_CONTINUED_SHADOW_RESEARCH"
        next_action = "APPROVE_CONTINUED_SHADOW_RESEARCH_ONLY"
    review = {
        "baseline_candidate_count": summary.get("baseline_candidate_count", "0"),
        "shadow_candidate_count": summary.get("shadow_candidate_count", "0"),
        "proposal_row_count": summary.get("proposal_row_count", "0"),
        "low_confidence_proposal_count": summary.get("low_confidence_proposal_count", "0"),
        "top20_overlap_count": summary.get("top20_overlap_count", "0"),
        "entered_top20_count": summary.get("entered_top20_count", "0"),
        "exited_top20_count": summary.get("exited_top20_count", "0"),
        "top20_turnover_rate": f"{top20_turnover:.10f}",
        "max_absolute_rank_delta": summary.get("max_absolute_rank_delta", "0"),
        "average_absolute_rank_delta": summary.get("average_absolute_rank_delta", "0"),
        "affected_ticker_count": summary.get("affected_ticker_count", "0"),
        "score_recomputation_performed": gate.get("score_recomputation_performed", "FALSE"),
        "rank_impact_proxy_used": gate.get("rank_impact_proxy_used", "FALSE"),
        "rank_impact_severity": sev,
        "stability_review_result": result,
        "operator_review_required": "TRUE",
        "allow_continued_shadow_research": tf(allow_continued),
        "allow_shadow_weight_expansion": tf(allow_expansion),
        "allow_official_weight_change": "FALSE",
        "required_next_action": next_action,
        **COMMON,
    }
    return review, risks


def guardrails(review: dict[str, str], risks: dict[str, bool]) -> list[dict[str, str]]:
    specs = [
        ("CONFIDENCE_RISK", "confidence", review["low_confidence_proposal_count"], f"< {review['proposal_row_count']} low-confidence proposals"),
        ("RANK_CHURN_RISK", "churn", review["top20_turnover_rate"], f"< {HIGH_TURNOVER_THRESHOLD:.2f}"),
        ("RANK_INSTABILITY_RISK", "instability", review["average_absolute_rank_delta"], f"< {HIGH_AVG_DELTA_THRESHOLD:.2f}"),
        ("OUTLIER_RANK_IMPACT_RISK", "outlier", review["max_absolute_rank_delta"], f"< {EXTREME_MAX_DELTA_THRESHOLD}"),
        ("OFFICIAL_WEIGHT_CHANGE_BLOCK", "official", "FALSE", "FALSE"),
        ("SHADOW_EXPANSION_GATE", "expansion", review["allow_shadow_weight_expansion"], "TRUE only when impact acceptable"),
    ]
    rows = []
    for index, (name, key, observed, threshold) in enumerate(specs, start=1):
        high = risks.get(key, False)
        if key == "official":
            high = False
        if key == "expansion":
            high = review["allow_shadow_weight_expansion"] != "TRUE"
        rows.append({
            "guardrail_id": f"V20_156_GUARDRAIL_{index:03d}",
            "guardrail_name": name,
            "observed_value": observed,
            "threshold_value": threshold,
            "risk_level": "HIGH" if high else "LOW",
            "guardrail_passed": tf(not high),
            "guardrail_reason": f"{name}_HIGH" if high else f"{name}_PASS",
            **COMMON,
        })
    return rows


def operator_packet(review: dict[str, str]) -> list[dict[str, str]]:
    recommended = review["required_next_action"]
    options = [
        ("APPROVE_CONTINUED_SHADOW_RESEARCH_ONLY", "TRUE", "Continue research-only observation without expansion or official changes."),
        ("REQUEST_SHADOW_WEIGHT_DELTA_REDUCTION", "TRUE", "Ask for smaller shadow deltas before another ranking simulation."),
        ("REQUEST_MORE_FORWARD_OUTCOMES_BEFORE_EXPANSION", "TRUE", "Wait for additional forward outcomes before expanding shadow scope."),
        ("REJECT_SHADOW_DYNAMIC_WEIGHT_PATH_FOR_NOW", "TRUE", "Stop the shadow dynamic weighting path for now."),
    ]
    rows = []
    for index, (option, available, reason) in enumerate(options, start=1):
        rows.append({
            "operator_option_id": f"V20_156_OPERATOR_OPTION_{index:03d}",
            "operator_option": option,
            "option_available": available,
            "recommended": tf(option == recommended),
            "option_reason": reason,
            **COMMON,
        })
    return rows


def low_confidence_rows(sim_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for row in sim_rows:
        if row.get("proposal_confidence_level") not in {"LOW", "LIMITED"}:
            continue
        rows.append({
            "low_confidence_audit_id": f"V20_156_LOW_CONFIDENCE_{len(rows)+1:04d}",
            "ticker": row.get("ticker", ""),
            "proposal_confidence_level": row.get("proposal_confidence_level", ""),
            "evidence_quality": row.get("evidence_quality", ""),
            "rank_delta": row.get("rank_delta", ""),
            "score_delta": row.get("score_delta", ""),
            "low_confidence_reason": "V20_154_PROPOSAL_CONFIDENCE_LOW_OR_LIMITED",
            **COMMON,
        })
    return rows


def safety_issue_count(groups: list[list[dict[str, str]]]) -> int:
    count = 0
    for rows in groups:
        for row in rows:
            for field in SAFETY_FIELDS:
                if field in {"shadow_weight_proposal_created", "shadow_ranking_simulation_created"}:
                    if row.get(field) != "TRUE":
                        count += 1
                elif field == "shadow_review_scope":
                    if row.get(field) != SCOPE:
                        count += 1
                elif truthy(row.get(field)):
                    count += 1
    return count


def write_report(status: str, review: dict[str, str] | None = None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.156 Shadow Ranking Simulation Operator Review And Stability Gate Report",
        "",
        f"- wrapper_status: {status}",
        "- shadow_review_scope: RESEARCH_ONLY_LIMITED",
        "- official_weight_change_created: FALSE",
        "- official_ranking_mutated: FALSE",
    ]
    if review:
        lines.extend([
            f"- rank_impact_severity: {review['rank_impact_severity']}",
            f"- stability_review_result: {review['stability_review_result']}",
            f"- required_next_action: {review['required_next_action']}",
            f"- allow_continued_shadow_research: {review['allow_continued_shadow_research']}",
            f"- allow_shadow_weight_expansion: {review['allow_shadow_weight_expansion']}",
        ])
    lines.append("")
    lines.append("This stage is an operator review gate only. It does not mutate authoritative rankings, weights, recommendations, trades, broker actions, or upstream outputs.")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_156_SHADOW_RANKING_NEXT_GATE_001",
        "v20_155_gate_consumed": "FALSE",
        "v20_155_status": "",
        "v20_155_allowed_for_v20_156": "FALSE",
        **SAFETY,
        "confidence_risk": "UNKNOWN",
        "rank_churn_risk": "UNKNOWN",
        "rank_instability_risk": "UNKNOWN",
        "outlier_rank_impact_risk": "UNKNOWN",
        "operator_review_required": "TRUE",
        "allow_continued_shadow_research": "FALSE",
        "allow_shadow_weight_expansion": "FALSE",
        "allow_official_weight_change": "FALSE",
        "no_official_ranking_mutated": "TRUE",
        "no_official_weights_mutated": "TRUE",
        "no_official_recommendation_created": "TRUE",
        "no_real_book_action_created": "TRUE",
        "no_trade_action_created": "TRUE",
        "no_broker_action_created": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_outcomes_fabricated": "TRUE",
        "no_benchmarks_fabricated": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "required_next_action": "REJECT_SHADOW_DYNAMIC_WEIGHT_PATH_FOR_NOW",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        "research_only": "TRUE",
        "staging_review_only": "TRUE",
        "operator_review_gate_only": "TRUE",
        "audit_only": "TRUE",
    }
    write_csv(OUT_REVIEW, REVIEW_FIELDS, [])
    write_csv(OUT_OPERATOR, OPERATOR_FIELDS, [])
    write_csv(OUT_GUARDRAIL, GUARDRAIL_FIELDS, [])
    write_csv(OUT_LOW_CONF, LOW_CONF_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(BLOCKED_STATUS)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = upstream_hashes()
    missing = [path for path in upstream_inputs() if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_V20_155_OUTPUTS:" + ";".join(rel(path) for path in missing))
    sim_rows, _ = read_csv(IN_SIM)
    summary_rows, _ = read_csv(IN_DELTA)
    gate_rows, _ = read_csv(IN_GATE)
    if not all([sim_rows, summary_rows, gate_rows]):
        return emit_blocked("EMPTY_REQUIRED_V20_155_OUTPUTS")
    v155_status = gate_rows[0].get("final_status", "")
    allowed = v155_status in V155_ALLOWED and truthy(gate_rows[0].get("v20_156_shadow_review_allowed"))
    if not allowed:
        return emit_blocked("V20_155_STATUS_NOT_ALLOWED_FOR_V20_156")

    review, risks = build_review(summary_rows[0], gate_rows[0])
    guardrail_rows = guardrails(review, risks)
    operator_rows = operator_packet(review)
    low_rows = low_confidence_rows(sim_rows)
    upstream_mutated = before != upstream_hashes()
    safety_count = safety_issue_count([[review], guardrail_rows, operator_rows, low_rows])
    if upstream_mutated or safety_count:
        status = BLOCKED_STATUS
        blocking = "SAFETY_OR_UPSTREAM_MUTATION_FAILURE"
    elif risks["outlier"] or (risks["churn"] and risks["instability"]):
        status = WARN_STATUS
        blocking = ""
    elif risks["confidence"] or risks["churn"] or risks["instability"]:
        status = PARTIAL_STATUS
        blocking = ""
    else:
        status = PASS_STATUS
        blocking = ""
    gate = {
        "gate_check_id": "V20_156_SHADOW_RANKING_NEXT_GATE_001",
        "v20_155_gate_consumed": "TRUE",
        "v20_155_status": v155_status,
        "v20_155_allowed_for_v20_156": tf(allowed),
        **SAFETY,
        "confidence_risk": risk_level(risks["confidence"]),
        "rank_churn_risk": risk_level(risks["churn"]),
        "rank_instability_risk": risk_level(risks["instability"]),
        "outlier_rank_impact_risk": risk_level(risks["outlier"]),
        "operator_review_required": review["operator_review_required"],
        "allow_continued_shadow_research": review["allow_continued_shadow_research"],
        "allow_shadow_weight_expansion": review["allow_shadow_weight_expansion"],
        "allow_official_weight_change": "FALSE",
        "no_official_ranking_mutated": "TRUE",
        "no_official_weights_mutated": "TRUE",
        "no_official_recommendation_created": "TRUE",
        "no_real_book_action_created": "TRUE",
        "no_trade_action_created": "TRUE",
        "no_broker_action_created": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_outcomes_fabricated": "TRUE",
        "no_benchmarks_fabricated": "TRUE",
        "no_upstream_outputs_mutated": tf(not upstream_mutated),
        "required_next_action": review["required_next_action"],
        "blocking_reason": blocking,
        "final_status": status,
        "research_only": "TRUE",
        "staging_review_only": "TRUE",
        "operator_review_gate_only": "TRUE",
        "audit_only": "TRUE",
    }
    write_csv(OUT_REVIEW, REVIEW_FIELDS, [review])
    write_csv(OUT_OPERATOR, OPERATOR_FIELDS, operator_rows)
    write_csv(OUT_GUARDRAIL, GUARDRAIL_FIELDS, guardrail_rows)
    write_csv(OUT_LOW_CONF, LOW_CONF_FIELDS, low_rows)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(status, review)

    print(status)
    print("V20_155_GATE_CONSUMED=TRUE")
    print(f"V20_155_ALLOWED_FOR_V20_156={tf(allowed)}")
    print(f"CONFIDENCE_RISK={gate['confidence_risk']}")
    print(f"RANK_CHURN_RISK={gate['rank_churn_risk']}")
    print(f"RANK_INSTABILITY_RISK={gate['rank_instability_risk']}")
    print(f"OUTLIER_RANK_IMPACT_RISK={gate['outlier_rank_impact_risk']}")
    print(f"OPERATOR_REVIEW_REQUIRED={review['operator_review_required']}")
    print(f"ALLOW_CONTINUED_SHADOW_RESEARCH={review['allow_continued_shadow_research']}")
    print(f"ALLOW_SHADOW_WEIGHT_EXPANSION={review['allow_shadow_weight_expansion']}")
    print("ALLOW_OFFICIAL_WEIGHT_CHANGE=FALSE")
    print(f"REQUIRED_NEXT_ACTION={review['required_next_action']}")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("OFFICIAL_WEIGHTS_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_ACTION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_ACTION_CREATED=FALSE")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print("OUTCOMES_FABRICATED=0")
    print("BENCHMARKS_FABRICATED=0")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    print(f"SAFETY_TRUE_COUNT={safety_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
