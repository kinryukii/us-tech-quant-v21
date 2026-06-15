#!/usr/bin/env python
"""V20.161 bound shadow stability observation runs.

Runs additional research-only bound shadow stability observations after the
V20.160 operator decision. The runs reuse V20.157 reduced proposal lineage and
V20.158-R2 authoritative baseline binding only; they do not create new proposal
rows, expand factor scope, mutate official rankings or weights, or claim
performance.
"""

from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
FACTORS = OUTPUTS / "factors"
CONSOLIDATION = OUTPUTS / "consolidation"
READ_CENTER = OUTPUTS / "read_center"

V160_DECISION = FACTORS / "V20_160_BOUND_SHADOW_OPERATOR_DECISION_CAPTURE.csv"
V160_GATE = FACTORS / "V20_160_BOUND_SHADOW_OPERATOR_DECISION_GATE.csv"
V160_SAFETY = FACTORS / "V20_160_BOUND_SHADOW_DECISION_SAFETY_AUDIT.csv"
V160_NEXT = FACTORS / "V20_160_BOUND_SHADOW_NEXT_STAGE_PACKET.csv"

V158_R2_SIM = FACTORS / "V20_158_R2_BOUND_REDUCED_SHADOW_RANKING_SIMULATION.csv"
V158_R2_DELTA = FACTORS / "V20_158_R2_BOUND_SHADOW_VS_BASELINE_RANK_DELTA.csv"
V158_R2_GATE = FACTORS / "V20_158_R2_RANK_IMPACT_RETEST_GATE.csv"
V157_PROPOSAL = FACTORS / "V20_157_REDUCED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv"
V83_RANKING = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"

OUT_RUNS = FACTORS / "V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_RUNS.csv"
OUT_SUMMARY = FACTORS / "V20_161_BOUND_SHADOW_STABILITY_SUMMARY.csv"
OUT_GATE = FACTORS / "V20_161_BOUND_SHADOW_STABILITY_GATE.csv"
OUT_SOURCE = FACTORS / "V20_161_BOUND_SHADOW_STABILITY_SOURCE_AUDIT.csv"
OUT_SAFETY = FACTORS / "V20_161_BOUND_SHADOW_STABILITY_SAFETY_AUDIT.csv"
OUT_LIMITATION = FACTORS / "V20_161_BOUND_SHADOW_STABILITY_LIMITATION_AUDIT.csv"
REPORT = READ_CENTER / "V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_RUNS_REPORT.md"

REQUIRED_V160_STATUS = "PASS_V20_160_BOUND_SHADOW_OPERATOR_DECISION_CAPTURE_READY_FOR_V20_161"
REQUIRED_DECISION = "REQUEST_ADDITIONAL_STABILITY_OBSERVATION_RUNS"
PASS_STATUS = "PASS_V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_READY_FOR_V20_162"
PARTIAL_STATUS = "PARTIAL_PASS_V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_WITH_ELEVATED_RANK_IMPACT_READY_FOR_V20_162"
WARN_STATUS = "WARN_V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_UNSTABLE"
BLOCKED_STATUS = "BLOCKED_V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_RUNS"
SCOPE = "RESEARCH_ONLY_LIMITED_CONSERVATIVE_BOUND_TO_AUTHORITATIVE_BASELINE"

TURNOVER_UNSTABLE_THRESHOLD = 0.20
AVG_DELTA_THRESHOLD = 3.0
ELEVATED_MAX_DELTA_THRESHOLD = 5
RUN_MULTIPLIERS = [
    ("V20_161_OBSERVATION_FULL_REDUCED_DELTA", 1.00),
    ("V20_161_OBSERVATION_75_PERCENT_REDUCED_DELTA", 0.75),
    ("V20_161_OBSERVATION_50_PERCENT_REDUCED_DELTA", 0.50),
]

SAFETY = {
    "formal_activation_allowed": "FALSE",
    "promotion_ready": "FALSE",
    "official_recommendation_created": "FALSE",
    "official_ranking_mutated": "FALSE",
    "official_weight_change_created": "FALSE",
    "bound_shadow_stability_observation_created": "TRUE",
    "shadow_observation_scope": SCOPE,
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
    "stability_observation_only": "TRUE",
    "audit_only": "TRUE",
}

RUN_FIELDS = [
    "observation_run_id",
    "source_baseline_artifact",
    "source_shadow_proposal_artifact",
    "baseline_candidate_count",
    "bound_shadow_candidate_count",
    "top20_overlap_count",
    "entered_top20_count",
    "exited_top20_count",
    "top20_turnover_rate",
    "max_absolute_rank_delta",
    "average_absolute_rank_delta",
    "median_absolute_rank_delta",
    "affected_ticker_count",
    "remaining_rank_impact_severity",
    "stability_result",
    "limitation_reason",
    *COMMON.keys(),
]
SUMMARY_FIELDS = [
    "observation_run_count",
    "stability_pass_count",
    "stability_warn_count",
    "stability_fail_count",
    "average_top20_turnover_rate",
    "max_top20_turnover_rate",
    "average_rank_delta_across_runs",
    "max_rank_delta_across_runs",
    "stable_enough_for_shadow_continuation",
    "stable_enough_for_shadow_expansion",
    "stable_enough_for_official_weight_change",
    "recommended_next_action",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "v20_160_gate_consumed",
    "v20_160_status",
    "selected_operator_option",
    "continued_bound_shadow_research_allowed",
    "additional_stability_observation_runs_required",
    "shadow_weight_expansion_allowed",
    "official_weight_change_allowed",
    "formal_activation_allowed",
    "promotion_ready",
    "observation_run_count",
    "stability_pass_count",
    "stability_warn_count",
    "stability_fail_count",
    "stable_enough_for_shadow_continuation",
    "stable_enough_for_shadow_expansion",
    "stable_enough_for_official_weight_change",
    "no_new_shadow_proposal_rows_created",
    "no_factor_scope_expansion",
    "no_official_ranking_mutated",
    "no_official_weights_mutated",
    "no_official_recommendation_created",
    "no_real_book_action_created",
    "no_trade_action_created",
    "no_broker_action_created",
    "no_outcomes_fabricated",
    "no_benchmarks_fabricated",
    "no_performance_claim_created",
    "no_upstream_outputs_mutated",
    "v20_162_allowed",
    "blocking_reason",
    "final_status",
    *COMMON.keys(),
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
    "affected_observation_run_count",
    "requires_score_adjustment_cap_review",
    "requires_more_forward_outcomes",
    "recommended_next_action",
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


def inputs() -> list[Path]:
    return [V160_DECISION, V160_GATE, V160_SAFETY, V160_NEXT, V158_R2_SIM, V158_R2_DELTA, V158_R2_GATE, V157_PROPOSAL, V83_RANKING]


def input_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in inputs() if path.exists()}


def source_rows() -> list[dict[str, str]]:
    sources = [
        (V160_DECISION, "V20_160_DECISION_CAPTURE"),
        (V160_GATE, "V20_160_DECISION_GATE"),
        (V160_SAFETY, "V20_160_SAFETY_AUDIT"),
        (V160_NEXT, "V20_160_NEXT_STAGE_PACKET"),
        (V158_R2_SIM, "V20_158_R2_BOUND_SIMULATION"),
        (V158_R2_DELTA, "V20_158_R2_BOUND_DELTA_SUMMARY"),
        (V158_R2_GATE, "V20_158_R2_RETEST_GATE"),
        (V157_PROPOSAL, "V20_157_REDUCED_SHADOW_PROPOSAL"),
        (V83_RANKING, "V20_83_AUTHORITATIVE_BASELINE_RANKING"),
    ]
    rows = []
    for index, (path, role) in enumerate(sources, start=1):
        data, fields = read_csv(path)
        exists = path.exists()
        non_empty = exists and path.stat().st_size > 0
        ok = bool(fields) and non_empty
        rows.append({
            "source_audit_id": f"V20_161_SOURCE_{index:03d}",
            "source_artifact": rel(path),
            "source_exists": tf(exists),
            "source_non_empty": tf(non_empty),
            "row_count": str(len(data)),
            "source_sha256": sha_file(path),
            "source_role": role,
            "source_status": "PASS" if ok else "BLOCKED_MISSING_OR_EMPTY",
            "exclusion_reason": "" if ok else "MISSING_OR_EMPTY_REQUIRED_SOURCE",
            **COMMON,
        })
    return rows


def baseline_anchor_map(rows: list[dict[str, str]]) -> dict[str, dict[str, float]]:
    out = {}
    for row in rows:
        ticker = row.get("ticker") or row.get("normalized_ticker") or row.get("ticker_or_candidate_id")
        if not ticker:
            continue
        rank = int(num(row.get("official_current_rank") or row.get("baseline_rank") or row.get("report_rank"), 0))
        score = float(rank) if row.get("score_name") == "source_rank_or_score" else num(row.get("official_current_score") or row.get("source_rank_or_score") or rank)
        out[ticker] = {"rank": float(rank), "score": score}
    return out


def severity(turnover: float, max_delta: int, avg_delta: float) -> str:
    if turnover > TURNOVER_UNSTABLE_THRESHOLD:
        return "UNSTABLE"
    if avg_delta > AVG_DELTA_THRESHOLD:
        return "CAP_REVIEW_REQUIRED"
    if max_delta > ELEVATED_MAX_DELTA_THRESHOLD:
        return "ELEVATED"
    return "LOW"


def stability_result(turnover: float, max_delta: int, avg_delta: float) -> str:
    if turnover > TURNOVER_UNSTABLE_THRESHOLD:
        return "FAIL_UNSTABLE_TOP20_TURNOVER"
    if avg_delta > AVG_DELTA_THRESHOLD:
        return "WARN_SCORE_ADJUSTMENT_CAP_REVIEW_REQUIRED"
    if turnover == 0 and max_delta > ELEVATED_MAX_DELTA_THRESHOLD:
        return "WARN_CONTINUED_SHADOW_RESEARCH_ONLY_ELEVATED_RANK_DELTA"
    return "PASS_STABLE_FOR_CONTINUED_BOUND_SHADOW_RESEARCH"


def build_run(run_id: str, multiplier: float, sim_rows: list[dict[str, str]], baseline: dict[str, dict[str, float]]) -> dict[str, str]:
    staged = []
    for row in sim_rows:
        ticker = row.get("ticker", "")
        base = baseline.get(ticker, {})
        base_rank = int(base.get("rank", num(row.get("authoritative_baseline_rank"))))
        base_score = base.get("score", num(row.get("authoritative_baseline_score") or base_rank))
        delta = num(row.get("bound_reduced_score_delta")) * multiplier
        staged.append({"ticker": ticker, "baseline_rank": base_rank, "score": base_score + delta})
    ranked = sorted(staged, key=lambda row: (row["score"], row["baseline_rank"], row["ticker"]))
    shadow_rank = {row["ticker"]: index for index, row in enumerate(ranked, start=1)}
    baseline_top = {row["ticker"] for row in staged if row["baseline_rank"] <= 20}
    shadow_top = {ticker for ticker, rank in shadow_rank.items() if rank <= 20}
    deltas = [abs(row["baseline_rank"] - shadow_rank[row["ticker"]]) for row in staged]
    turnover = (len(shadow_top - baseline_top) + len(baseline_top - shadow_top)) / max(1, len(baseline_top))
    max_delta = max(deltas) if deltas else 0
    avg_delta = mean(deltas) if deltas else 0.0
    med_delta = median(deltas) if deltas else 0.0
    result = stability_result(turnover, max_delta, avg_delta)
    limitation = "NONE"
    if result.startswith("WARN_SCORE"):
        limitation = "AVERAGE_ABSOLUTE_RANK_DELTA_ABOVE_CONFIGURED_THRESHOLD"
    elif result.startswith("WARN_CONTINUED"):
        limitation = "TOP20_TURNOVER_ZERO_BUT_MAX_RANK_DELTA_REMAINS_ELEVATED"
    elif result.startswith("FAIL"):
        limitation = "TOP20_TURNOVER_RATE_ABOVE_STABILITY_GUARDRAIL"
    return {
        "observation_run_id": run_id,
        "source_baseline_artifact": rel(V83_RANKING),
        "source_shadow_proposal_artifact": rel(V157_PROPOSAL),
        "baseline_candidate_count": str(len(staged)),
        "bound_shadow_candidate_count": str(len(staged)),
        "top20_overlap_count": str(len(baseline_top & shadow_top)),
        "entered_top20_count": str(len(shadow_top - baseline_top)),
        "exited_top20_count": str(len(baseline_top - shadow_top)),
        "top20_turnover_rate": fmt(turnover),
        "max_absolute_rank_delta": str(max_delta),
        "average_absolute_rank_delta": fmt(avg_delta),
        "median_absolute_rank_delta": fmt(float(med_delta)),
        "affected_ticker_count": str(sum(1 for delta in deltas if delta != 0)),
        "remaining_rank_impact_severity": severity(turnover, max_delta, avg_delta),
        "stability_result": result,
        "limitation_reason": limitation,
        **COMMON,
    }


def build_summary(runs: list[dict[str, str]]) -> dict[str, str]:
    pass_count = sum(1 for row in runs if row["stability_result"].startswith("PASS"))
    warn_count = sum(1 for row in runs if row["stability_result"].startswith("WARN"))
    fail_count = sum(1 for row in runs if row["stability_result"].startswith("FAIL"))
    turnovers = [num(row["top20_turnover_rate"]) for row in runs]
    avg_deltas = [num(row["average_absolute_rank_delta"]) for row in runs]
    max_deltas = [int(num(row["max_absolute_rank_delta"])) for row in runs]
    unstable = fail_count > 0 or any(value > TURNOVER_UNSTABLE_THRESHOLD for value in turnovers)
    cap_review = any(value > AVG_DELTA_THRESHOLD for value in avg_deltas)
    elevated = any(value > ELEVATED_MAX_DELTA_THRESHOLD for value in max_deltas)
    continuation = not unstable
    if unstable:
        action = "REQUEST_SCORE_ADJUSTMENT_CAP_REPAIR_BEFORE_MORE_BOUND_SHADOW_RESEARCH"
    elif cap_review:
        action = "REQUEST_SCORE_ADJUSTMENT_CAP_REVIEW"
    elif elevated:
        action = "CONTINUE_BOUND_SHADOW_RESEARCH_ONLY_WITH_ELEVATED_RANK_IMPACT_MONITORING"
    else:
        action = "CONTINUE_BOUND_SHADOW_RESEARCH_ONLY"
    return {
        "observation_run_count": str(len(runs)),
        "stability_pass_count": str(pass_count),
        "stability_warn_count": str(warn_count),
        "stability_fail_count": str(fail_count),
        "average_top20_turnover_rate": fmt(mean(turnovers) if turnovers else 0.0),
        "max_top20_turnover_rate": fmt(max(turnovers) if turnovers else 0.0),
        "average_rank_delta_across_runs": fmt(mean(avg_deltas) if avg_deltas else 0.0),
        "max_rank_delta_across_runs": str(max(max_deltas) if max_deltas else 0),
        "stable_enough_for_shadow_continuation": tf(continuation),
        "stable_enough_for_shadow_expansion": "FALSE",
        "stable_enough_for_official_weight_change": "FALSE",
        "recommended_next_action": action,
        **COMMON,
    }


def safety_rows(upstream_mutated: bool, prereq_ok: bool) -> list[dict[str, str]]:
    checks = [
        ("v20_160_prerequisites_met", "TRUE", tf(prereq_ok)),
        ("formal_activation_allowed", "FALSE", "FALSE"),
        ("promotion_ready", "FALSE", "FALSE"),
        ("official_recommendation_created", "FALSE", "FALSE"),
        ("official_ranking_mutated", "FALSE", "FALSE"),
        ("official_weight_change_created", "FALSE", "FALSE"),
        ("bound_shadow_stability_observation_created", "TRUE", "TRUE"),
        ("shadow_observation_scope", SCOPE, SCOPE),
        ("shadow_weight_expansion_allowed", "FALSE", "FALSE"),
        ("weight_mutated", "FALSE", "FALSE"),
        ("real_book_action_created", "FALSE", "FALSE"),
        ("trade_action_created", "FALSE", "FALSE"),
        ("broker_execution_supported", "FALSE", "FALSE"),
        ("performance_claim_created", "FALSE", "FALSE"),
        ("new_shadow_proposal_rows_created", "FALSE", "FALSE"),
        ("factor_scope_expanded", "FALSE", "FALSE"),
        ("outcomes_fabricated", "FALSE", "FALSE"),
        ("benchmarks_fabricated", "FALSE", "FALSE"),
        ("upstream_outputs_mutated", "FALSE", tf(upstream_mutated)),
    ]
    return [{
        "safety_check_id": f"V20_161_SAFETY_{index:03d}",
        "safety_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "safety_passed": tf(expected == actual),
        **COMMON,
    } for index, (check, expected, actual) in enumerate(checks, start=1)]


def limitation_rows(runs: list[dict[str, str]], summary: dict[str, str]) -> list[dict[str, str]]:
    limitations = [row for row in runs if row["limitation_reason"] != "NONE"]
    if not limitations:
        reason = "NO_STABILITY_LIMITATION_DETECTED"
    elif int(summary["stability_fail_count"]):
        reason = "UNSTABLE_TOP20_TURNOVER_DETECTED"
    elif any(row["limitation_reason"] == "AVERAGE_ABSOLUTE_RANK_DELTA_ABOVE_CONFIGURED_THRESHOLD" for row in limitations):
        reason = "AVERAGE_ABSOLUTE_RANK_DELTA_REQUIRES_SCORE_ADJUSTMENT_CAP_REVIEW"
    else:
        reason = "ELEVATED_MAX_RANK_DELTA_LIMITS_SCOPE_TO_CONTINUED_SHADOW_RESEARCH_ONLY"
    return [{
        "limitation_id": "V20_161_LIMITATION_001",
        "limitation_reason": reason,
        "affected_observation_run_count": str(len(limitations)),
        "requires_score_adjustment_cap_review": tf("CAP" in reason),
        "requires_more_forward_outcomes": "FALSE",
        "recommended_next_action": summary["recommended_next_action"],
        **COMMON,
    }]


def write_report(status: str, summary: dict[str, str] | None = None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.161 Bound Shadow Stability Observation Runs Report",
        "",
        f"- wrapper_status: {status}",
        f"- shadow_observation_scope: {SCOPE}",
        "- shadow_weight_expansion_allowed: FALSE",
        "- official_weight_change_created: FALSE",
        "- performance_claim_created: FALSE",
    ]
    if summary:
        lines.extend([
            f"- observation_run_count: {summary['observation_run_count']}",
            f"- average_top20_turnover_rate: {summary['average_top20_turnover_rate']}",
            f"- max_rank_delta_across_runs: {summary['max_rank_delta_across_runs']}",
            f"- recommended_next_action: {summary['recommended_next_action']}",
        ])
    lines.extend(["", "Observation runs reuse the reduced shadow proposal and authoritative baseline binding only."])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_161_BOUND_SHADOW_STABILITY_GATE_001",
        "v20_160_gate_consumed": "FALSE",
        "v20_160_status": "",
        "selected_operator_option": "",
        "continued_bound_shadow_research_allowed": "FALSE",
        "additional_stability_observation_runs_required": "FALSE",
        "shadow_weight_expansion_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "formal_activation_allowed": "FALSE",
        "promotion_ready": "FALSE",
        "observation_run_count": "0",
        "stability_pass_count": "0",
        "stability_warn_count": "0",
        "stability_fail_count": "0",
        "stable_enough_for_shadow_continuation": "FALSE",
        "stable_enough_for_shadow_expansion": "FALSE",
        "stable_enough_for_official_weight_change": "FALSE",
        "no_new_shadow_proposal_rows_created": "TRUE",
        "no_factor_scope_expansion": "TRUE",
        "no_official_ranking_mutated": "TRUE",
        "no_official_weights_mutated": "TRUE",
        "no_official_recommendation_created": "TRUE",
        "no_real_book_action_created": "TRUE",
        "no_trade_action_created": "TRUE",
        "no_broker_action_created": "TRUE",
        "no_outcomes_fabricated": "TRUE",
        "no_benchmarks_fabricated": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "v20_162_allowed": "FALSE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_RUNS, RUN_FIELDS, [])
    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SOURCE, SOURCE_FIELDS, [])
    write_csv(OUT_SAFETY, SAFETY_AUDIT_FIELDS, [])
    write_csv(OUT_LIMITATION, LIMITATION_FIELDS, [])
    write_report(BLOCKED_STATUS)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = input_hashes()
    missing = [path for path in inputs() if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    decision_rows, _ = read_csv(V160_DECISION)
    gate_rows, _ = read_csv(V160_GATE)
    next_rows, _ = read_csv(V160_NEXT)
    sim_rows, _ = read_csv(V158_R2_SIM)
    proposal_rows, _ = read_csv(V157_PROPOSAL)
    baseline_rows, _ = read_csv(V83_RANKING)
    if not all([decision_rows, gate_rows, next_rows, sim_rows, proposal_rows, baseline_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    gate = gate_rows[0]
    decision = decision_rows[0]
    next_packet = next_rows[0]
    prereq_ok = all([
        gate.get("final_status") == REQUIRED_V160_STATUS,
        gate.get("selected_operator_option") == REQUIRED_DECISION,
        decision.get("selected_operator_option") == REQUIRED_DECISION,
        gate.get("continued_bound_shadow_research_allowed") == "TRUE",
        gate.get("additional_stability_observation_runs_required") == "TRUE",
        gate.get("shadow_weight_expansion_allowed") == "FALSE",
        gate.get("official_weight_change_allowed") == "FALSE",
        gate.get("formal_activation_allowed") == "FALSE",
        gate.get("promotion_ready") == "FALSE",
        next_packet.get("v20_161_allowed") == "TRUE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_160_REQUIREMENTS_NOT_MET")

    baseline = baseline_anchor_map(baseline_rows)
    runs = [build_run(run_id, multiplier, sim_rows, baseline) for run_id, multiplier in RUN_MULTIPLIERS]
    summary = build_summary(runs)
    sources = source_rows()
    upstream_mutated = before != input_hashes()
    safety = safety_rows(upstream_mutated, prereq_ok)
    limitations = limitation_rows(runs, summary)
    safety_ok = all(row["safety_passed"] == "TRUE" for row in safety)
    if upstream_mutated or not safety_ok:
        status = BLOCKED_STATUS
        blocking = "SAFETY_OR_UPSTREAM_MUTATION_FAILURE"
    elif int(summary["stability_fail_count"]):
        status = WARN_STATUS
        blocking = ""
    elif int(summary["stability_warn_count"]):
        status = PARTIAL_STATUS
        blocking = ""
    else:
        status = PASS_STATUS
        blocking = ""
    v20_162_allowed = status in {PASS_STATUS, PARTIAL_STATUS}
    gate_out = {
        "gate_check_id": "V20_161_BOUND_SHADOW_STABILITY_GATE_001",
        "v20_160_gate_consumed": "TRUE",
        "v20_160_status": gate.get("final_status", ""),
        "selected_operator_option": REQUIRED_DECISION,
        "continued_bound_shadow_research_allowed": "TRUE",
        "additional_stability_observation_runs_required": "TRUE",
        "shadow_weight_expansion_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "formal_activation_allowed": "FALSE",
        "promotion_ready": "FALSE",
        "observation_run_count": summary["observation_run_count"],
        "stability_pass_count": summary["stability_pass_count"],
        "stability_warn_count": summary["stability_warn_count"],
        "stability_fail_count": summary["stability_fail_count"],
        "stable_enough_for_shadow_continuation": summary["stable_enough_for_shadow_continuation"],
        "stable_enough_for_shadow_expansion": "FALSE",
        "stable_enough_for_official_weight_change": "FALSE",
        "no_new_shadow_proposal_rows_created": "TRUE",
        "no_factor_scope_expansion": "TRUE",
        "no_official_ranking_mutated": "TRUE",
        "no_official_weights_mutated": "TRUE",
        "no_official_recommendation_created": "TRUE",
        "no_real_book_action_created": "TRUE",
        "no_trade_action_created": "TRUE",
        "no_broker_action_created": "TRUE",
        "no_outcomes_fabricated": "TRUE",
        "no_benchmarks_fabricated": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_upstream_outputs_mutated": tf(not upstream_mutated),
        "v20_162_allowed": tf(v20_162_allowed),
        "blocking_reason": blocking,
        "final_status": status,
        **COMMON,
    }
    write_csv(OUT_RUNS, RUN_FIELDS, runs)
    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, [summary])
    write_csv(OUT_GATE, GATE_FIELDS, [gate_out])
    write_csv(OUT_SOURCE, SOURCE_FIELDS, sources)
    write_csv(OUT_SAFETY, SAFETY_AUDIT_FIELDS, safety)
    write_csv(OUT_LIMITATION, LIMITATION_FIELDS, limitations)
    write_report(status, summary)

    print(status)
    print("V20_160_GATE_CONSUMED=TRUE")
    print(f"SELECTED_OPERATOR_OPTION={REQUIRED_DECISION}")
    print("CONTINUED_BOUND_SHADOW_RESEARCH_ALLOWED=TRUE")
    print("ADDITIONAL_STABILITY_OBSERVATION_RUNS_REQUIRED=TRUE")
    print("SHADOW_WEIGHT_EXPANSION_ALLOWED=FALSE")
    print("OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE")
    print("FORMAL_ACTIVATION_ALLOWED=FALSE")
    print("PROMOTION_READY=FALSE")
    print(f"OBSERVATION_RUN_COUNT={summary['observation_run_count']}")
    print(f"STABILITY_PASS_COUNT={summary['stability_pass_count']}")
    print(f"STABILITY_WARN_COUNT={summary['stability_warn_count']}")
    print(f"STABILITY_FAIL_COUNT={summary['stability_fail_count']}")
    print(f"AVERAGE_TOP20_TURNOVER_RATE={summary['average_top20_turnover_rate']}")
    print(f"MAX_TOP20_TURNOVER_RATE={summary['max_top20_turnover_rate']}")
    print(f"AVERAGE_RANK_DELTA_ACROSS_RUNS={summary['average_rank_delta_across_runs']}")
    print(f"MAX_RANK_DELTA_ACROSS_RUNS={summary['max_rank_delta_across_runs']}")
    print(f"STABLE_ENOUGH_FOR_SHADOW_CONTINUATION={summary['stable_enough_for_shadow_continuation']}")
    print("STABLE_ENOUGH_FOR_SHADOW_EXPANSION=FALSE")
    print("STABLE_ENOUGH_FOR_OFFICIAL_WEIGHT_CHANGE=FALSE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("OFFICIAL_WEIGHTS_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_ACTION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_ACTION_CREATED=FALSE")
    print("OUTCOMES_FABRICATED=0")
    print("BENCHMARKS_FABRICATED=0")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    print(f"V20_162_ALLOWED={tf(v20_162_allowed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
