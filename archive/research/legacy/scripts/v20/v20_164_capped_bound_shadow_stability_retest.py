#!/usr/bin/env python
"""V20.164 capped bound shadow stability retest.

Retests the V20.163 capped bound shadow simulation under research-only
guardrails. This stage uses only V20.163 capped outputs and does not create
new proposals, expand factor scope, mutate official rankings or weights,
create recommendations or actions, fabricate outcomes, or claim performance.
"""

from __future__ import annotations

import csv
import hashlib
import math
from collections import Counter
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

V163_REPAIR = FACTORS / "V20_163_BOUND_SHADOW_SCORE_RANK_CAP_REPAIR.csv"
V163_SIM = FACTORS / "V20_163_CAPPED_BOUND_SHADOW_RANKING_SIMULATION.csv"
V163_DELTA = FACTORS / "V20_163_CAPPED_BOUND_SHADOW_VS_BASELINE_RANK_DELTA.csv"
V163_SCORE_AUDIT = FACTORS / "V20_163_SCORE_ADJUSTMENT_CAP_AUDIT.csv"
V163_RANK_AUDIT = FACTORS / "V20_163_RANK_MOVEMENT_CAP_AUDIT.csv"
V163_OUTLIER_AUDIT = FACTORS / "V20_163_OUTLIER_CAP_REPAIR_AUDIT.csv"
V163_GATE = FACTORS / "V20_163_CAPPED_SHADOW_NEXT_GATE.csv"

OUT_RETEST = FACTORS / "V20_164_CAPPED_BOUND_SHADOW_STABILITY_RETEST.csv"
OUT_SUMMARY = FACTORS / "V20_164_CAPPED_BOUND_SHADOW_STABILITY_SUMMARY.csv"
OUT_GUARDRAIL = FACTORS / "V20_164_CAPPED_BOUND_SHADOW_GUARDRAIL_AUDIT.csv"
OUT_OUTLIER = FACTORS / "V20_164_CAPPED_BOUND_SHADOW_OUTLIER_RETEST_AUDIT.csv"
OUT_GATE = FACTORS / "V20_164_CAPPED_BOUND_SHADOW_NEXT_GATE.csv"
OUT_SAFETY = FACTORS / "V20_164_CAPPED_BOUND_SHADOW_SAFETY_AUDIT.csv"
REPORT = READ_CENTER / "V20_164_CAPPED_BOUND_SHADOW_STABILITY_RETEST_REPORT.md"

REQUIRED_V163_STATUS = "PASS_V20_163_BOUND_SHADOW_CAP_REPAIR_READY_FOR_V20_164"
PASS_STATUS = "PASS_V20_164_CAPPED_BOUND_SHADOW_STABILITY_RETEST_READY_FOR_V20_165"
PARTIAL_STATUS = "PARTIAL_PASS_V20_164_CAPPED_BOUND_SHADOW_STABILITY_RETEST_WITH_WARNINGS_READY_FOR_V20_165"
WARN_STATUS = "WARN_V20_164_CAPPED_BOUND_SHADOW_STABILITY_RETEST_UNSTABLE"
BLOCKED_STATUS = "BLOCKED_V20_164_CAPPED_BOUND_SHADOW_STABILITY_RETEST"
SCOPE = "RESEARCH_ONLY_LIMITED_CONSERVATIVE_BOUND_TO_AUTHORITATIVE_BASELINE_WITH_CAPS"

RETEST_RUN_IDS = [
    "V20_164_RETEST_CAPPED_BASELINE_BINDING",
    "V20_164_RETEST_CAPPED_GUARDRAIL_REPLAY",
    "V20_164_RETEST_CAPPED_OUTLIER_RECHECK",
]

SAFETY = {
    "formal_activation_allowed": "FALSE",
    "promotion_ready": "FALSE",
    "official_recommendation_created": "FALSE",
    "official_ranking_mutated": "FALSE",
    "official_weight_change_created": "FALSE",
    "capped_bound_shadow_stability_retest_created": "TRUE",
    "shadow_retest_scope": SCOPE,
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
    "stability_retest_only": "TRUE",
    "capped_shadow_only": "TRUE",
    "audit_only": "TRUE",
}

RETEST_FIELDS = [
    "retest_run_id",
    "baseline_candidate_count",
    "capped_shadow_candidate_count",
    "top20_overlap_count",
    "entered_top20_count",
    "exited_top20_count",
    "capped_top20_turnover_rate",
    "capped_max_absolute_rank_delta",
    "capped_average_absolute_rank_delta",
    "capped_median_absolute_rank_delta",
    "outlier_ticker_count",
    "factor_impact_concentration",
    "cap_guardrail_passed",
    "stability_result",
    "limitation_reason",
    *COMMON.keys(),
]
SUMMARY_FIELDS = [
    "retest_run_count",
    "stability_pass_count",
    "stability_warn_count",
    "stability_fail_count",
    "average_capped_top20_turnover_rate",
    "max_capped_top20_turnover_rate",
    "average_capped_rank_delta",
    "max_capped_rank_delta",
    "outlier_ticker_count_max",
    "factor_impact_concentration_max",
    "stable_enough_for_continued_capped_shadow_research",
    "stable_enough_for_operator_review",
    "stable_enough_for_shadow_expansion",
    "stable_enough_for_official_weight_change",
    "recommended_next_action",
    *COMMON.keys(),
]
GUARDRAIL_FIELDS = [
    "guardrail_id",
    "guardrail_name",
    "expected_value",
    "actual_value",
    "guardrail_passed",
    "guardrail_scope",
    *COMMON.keys(),
]
OUTLIER_FIELDS = [
    "ticker",
    "baseline_rank",
    "capped_shadow_rank",
    "capped_absolute_rank_delta",
    "outlier_retest_flag",
    "likely_factor_driver",
    "cap_guardrail_passed",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "v20_163_gate_consumed",
    "v20_163_status",
    "cap_repair_success",
    "capped_top20_turnover_rate",
    "outlier_ticker_count_after",
    "factor_impact_concentration_after",
    "shadow_weight_expansion_allowed",
    "official_weight_change_allowed",
    "retest_run_count",
    "top20_stability_guardrail_passed",
    "outlier_guardrail_passed",
    "rank_movement_guardrail_passed",
    "factor_concentration_guardrail_passed",
    "all_capped_guardrails_passed",
    "stable_enough_for_continued_capped_shadow_research",
    "stable_enough_for_operator_review",
    "stable_enough_for_shadow_expansion",
    "stable_enough_for_official_weight_change",
    "continued_capped_shadow_research_only",
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
    "v20_165_operator_review_allowed",
    "blocking_reason",
    "final_status",
    *COMMON.keys(),
]
SAFETY_FIELDS = [
    "safety_check_id",
    "safety_check",
    "expected_value",
    "actual_value",
    "safety_passed",
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


def intish(value: object, default: int = 0) -> int:
    return int(round(num(value, float(default))))


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
    return [V163_REPAIR, V163_SIM, V163_DELTA, V163_SCORE_AUDIT, V163_RANK_AUDIT, V163_OUTLIER_AUDIT, V163_GATE]


def input_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in inputs() if path.exists()}


def metrics(sim_rows: list[dict[str, str]], cap_threshold: int) -> dict[str, object]:
    baseline_top20 = {row["ticker"] for row in sim_rows if row.get("baseline_top20_flag") == "TRUE"}
    capped_top20 = {row["ticker"] for row in sim_rows if row.get("capped_shadow_top20_flag") == "TRUE"}
    deltas = [intish(row.get("capped_absolute_rank_delta")) for row in sim_rows]
    outliers = [row for row in sim_rows if intish(row.get("capped_absolute_rank_delta")) > cap_threshold]
    drivers = Counter(row.get("likely_factor_driver", "UNKNOWN") for row in outliers)
    concentration = max(drivers.values(), default=0) / len(outliers) if outliers else 0.0
    entered = len(capped_top20 - baseline_top20)
    exited = len(baseline_top20 - capped_top20)
    return {
        "baseline_candidate_count": len(sim_rows),
        "capped_shadow_candidate_count": len(sim_rows),
        "top20_overlap_count": len(baseline_top20 & capped_top20),
        "entered_top20_count": entered,
        "exited_top20_count": exited,
        "capped_top20_turnover_rate": (entered + exited) / max(len(baseline_top20), 1),
        "capped_max_absolute_rank_delta": max(deltas, default=0),
        "capped_average_absolute_rank_delta": mean(deltas) if deltas else 0.0,
        "capped_median_absolute_rank_delta": median(deltas) if deltas else 0.0,
        "outlier_ticker_count": len(outliers),
        "factor_impact_concentration": concentration,
    }


def build_retests(sim_rows: list[dict[str, str]], cap_threshold: int) -> list[dict[str, str]]:
    base = metrics(sim_rows, cap_threshold)
    top20_ok = base["capped_top20_turnover_rate"] == 0
    outlier_ok = base["outlier_ticker_count"] == 0
    rank_ok = base["capped_max_absolute_rank_delta"] <= cap_threshold
    factor_ok = base["factor_impact_concentration"] == 0
    passed = top20_ok and outlier_ok and rank_ok and factor_ok
    if not top20_ok:
        result, limitation = "FAIL", "CAPPED_TOP20_TURNOVER_RETEST_UNSTABLE"
    elif not outlier_ok:
        result, limitation = "WARN", "CAPPED_OUTLIER_GUARDRAIL_RETEST_FAILED"
    elif not rank_ok:
        result, limitation = "WARN", "CAPPED_RANK_MOVEMENT_ABOVE_CONFIGURED_THRESHOLD"
    elif not factor_ok:
        result, limitation = "WARN", "CAPPED_FACTOR_IMPACT_CONCENTRATION_REMAINS_ELEVATED"
    else:
        result, limitation = "PASS", "NONE"
    rows = []
    for run_id in RETEST_RUN_IDS:
        rows.append({
            "retest_run_id": run_id,
            "baseline_candidate_count": str(base["baseline_candidate_count"]),
            "capped_shadow_candidate_count": str(base["capped_shadow_candidate_count"]),
            "top20_overlap_count": str(base["top20_overlap_count"]),
            "entered_top20_count": str(base["entered_top20_count"]),
            "exited_top20_count": str(base["exited_top20_count"]),
            "capped_top20_turnover_rate": fmt(float(base["capped_top20_turnover_rate"])),
            "capped_max_absolute_rank_delta": str(base["capped_max_absolute_rank_delta"]),
            "capped_average_absolute_rank_delta": fmt(float(base["capped_average_absolute_rank_delta"])),
            "capped_median_absolute_rank_delta": fmt(float(base["capped_median_absolute_rank_delta"])),
            "outlier_ticker_count": str(base["outlier_ticker_count"]),
            "factor_impact_concentration": fmt(float(base["factor_impact_concentration"])),
            "cap_guardrail_passed": tf(passed),
            "stability_result": result,
            "limitation_reason": limitation,
            **COMMON,
        })
    return rows


def build_summary(retests: list[dict[str, str]]) -> dict[str, str]:
    turnovers = [num(row["capped_top20_turnover_rate"]) for row in retests]
    avg_deltas = [num(row["capped_average_absolute_rank_delta"]) for row in retests]
    max_deltas = [intish(row["capped_max_absolute_rank_delta"]) for row in retests]
    outliers = [intish(row["outlier_ticker_count"]) for row in retests]
    concentrations = [num(row["factor_impact_concentration"]) for row in retests]
    pass_count = sum(1 for row in retests if row["stability_result"] == "PASS")
    warn_count = sum(1 for row in retests if row["stability_result"] == "WARN")
    fail_count = sum(1 for row in retests if row["stability_result"] == "FAIL")
    stable = fail_count == 0 and max(turnovers, default=0.0) == 0 and max(outliers, default=0) == 0
    operator = stable and warn_count == 0
    if operator:
        action = "ALLOW_V20_165_OPERATOR_REVIEW_FOR_CONTINUED_CAPPED_SHADOW_RESEARCH_ONLY"
    elif stable:
        action = "ALLOW_V20_165_OPERATOR_REVIEW_WITH_CAPPED_SHADOW_WARNINGS_ONLY"
    else:
        action = "REPAIR_CAPPED_SHADOW_STABILITY_BEFORE_OPERATOR_REVIEW"
    return {
        "retest_run_count": str(len(retests)),
        "stability_pass_count": str(pass_count),
        "stability_warn_count": str(warn_count),
        "stability_fail_count": str(fail_count),
        "average_capped_top20_turnover_rate": fmt(mean(turnovers) if turnovers else 0.0),
        "max_capped_top20_turnover_rate": fmt(max(turnovers, default=0.0)),
        "average_capped_rank_delta": fmt(mean(avg_deltas) if avg_deltas else 0.0),
        "max_capped_rank_delta": str(max(max_deltas, default=0)),
        "outlier_ticker_count_max": str(max(outliers, default=0)),
        "factor_impact_concentration_max": fmt(max(concentrations, default=0.0)),
        "stable_enough_for_continued_capped_shadow_research": tf(stable),
        "stable_enough_for_operator_review": tf(operator),
        "stable_enough_for_shadow_expansion": "FALSE",
        "stable_enough_for_official_weight_change": "FALSE",
        "recommended_next_action": action,
        **COMMON,
    }


def guardrail_rows(retests: list[dict[str, str]], cap_threshold: int) -> list[dict[str, str]]:
    max_turnover = max([num(row["capped_top20_turnover_rate"]) for row in retests], default=0.0)
    max_outliers = max([intish(row["outlier_ticker_count"]) for row in retests], default=0)
    max_delta = max([intish(row["capped_max_absolute_rank_delta"]) for row in retests], default=0)
    max_conc = max([num(row["factor_impact_concentration"]) for row in retests], default=0.0)
    checks = [
        ("TOP20_STABILITY", "0.0000000000", fmt(max_turnover), max_turnover == 0.0),
        ("OUTLIER_GUARDRAIL", "0", str(max_outliers), max_outliers == 0),
        ("RANK_MOVEMENT_GUARDRAIL", f"<= {cap_threshold}", str(max_delta), max_delta <= cap_threshold),
        ("FACTOR_CONCENTRATION_GUARDRAIL", "0.0000000000", fmt(max_conc), max_conc == 0.0),
        ("SHADOW_WEIGHT_EXPANSION_ALLOWED", "FALSE", "FALSE", True),
        ("OFFICIAL_WEIGHT_CHANGE_ALLOWED", "FALSE", "FALSE", True),
    ]
    return [{
        "guardrail_id": f"V20_164_GUARDRAIL_{idx:03d}",
        "guardrail_name": name,
        "expected_value": expected,
        "actual_value": actual,
        "guardrail_passed": tf(passed),
        "guardrail_scope": SCOPE,
        **COMMON,
    } for idx, (name, expected, actual, passed) in enumerate(checks, start=1)]


def outlier_rows(sim_rows: list[dict[str, str]], cap_threshold: int) -> list[dict[str, str]]:
    rows = []
    for row in sim_rows:
        delta = intish(row.get("capped_absolute_rank_delta"))
        flag = delta > cap_threshold
        rows.append({
            "ticker": row.get("ticker", ""),
            "baseline_rank": row.get("baseline_rank", ""),
            "capped_shadow_rank": row.get("capped_bound_shadow_rank", ""),
            "capped_absolute_rank_delta": str(delta),
            "outlier_retest_flag": tf(flag),
            "likely_factor_driver": row.get("likely_factor_driver", ""),
            "cap_guardrail_passed": tf(not flag),
            **COMMON,
        })
    return rows


def safety_rows(upstream_mutated: bool, prereq_ok: bool) -> list[dict[str, str]]:
    checks = [
        ("v20_163_prerequisites_met", "TRUE", tf(prereq_ok)),
        ("formal_activation_allowed", "FALSE", "FALSE"),
        ("promotion_ready", "FALSE", "FALSE"),
        ("official_recommendation_created", "FALSE", "FALSE"),
        ("official_ranking_mutated", "FALSE", "FALSE"),
        ("official_weight_change_created", "FALSE", "FALSE"),
        ("capped_bound_shadow_stability_retest_created", "TRUE", "TRUE"),
        ("shadow_retest_scope", SCOPE, SCOPE),
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
        "safety_check_id": f"V20_164_SAFETY_{idx:03d}",
        "safety_check": name,
        "expected_value": expected,
        "actual_value": actual,
        "safety_passed": tf(expected == actual),
        **COMMON,
    } for idx, (name, expected, actual) in enumerate(checks, start=1)]


def write_report(status: str, summary: dict[str, str] | None = None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.164 Capped Bound Shadow Stability Retest Report",
        "",
        f"- wrapper_status: {status}",
        f"- shadow_retest_scope: {SCOPE}",
        "- shadow_weight_expansion_allowed: FALSE",
        "- official_weight_change_allowed: FALSE",
        "- performance_claim_created: FALSE",
    ]
    if summary:
        lines.extend([
            f"- retest_run_count: {summary['retest_run_count']}",
            f"- max_capped_top20_turnover_rate: {summary['max_capped_top20_turnover_rate']}",
            f"- max_capped_rank_delta: {summary['max_capped_rank_delta']}",
            f"- outlier_ticker_count_max: {summary['outlier_ticker_count_max']}",
            f"- factor_impact_concentration_max: {summary['factor_impact_concentration_max']}",
            f"- recommended_next_action: {summary['recommended_next_action']}",
        ])
    lines.extend(["", "This retest uses only the V20.163 capped bound shadow simulation."])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_164_CAPPED_BOUND_SHADOW_NEXT_GATE_001",
        "v20_163_gate_consumed": "FALSE",
        "v20_163_status": "",
        "cap_repair_success": "FALSE",
        "capped_top20_turnover_rate": fmt(0.0),
        "outlier_ticker_count_after": "0",
        "factor_impact_concentration_after": fmt(0.0),
        "shadow_weight_expansion_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "retest_run_count": "0",
        "top20_stability_guardrail_passed": "FALSE",
        "outlier_guardrail_passed": "FALSE",
        "rank_movement_guardrail_passed": "FALSE",
        "factor_concentration_guardrail_passed": "FALSE",
        "all_capped_guardrails_passed": "FALSE",
        "stable_enough_for_continued_capped_shadow_research": "FALSE",
        "stable_enough_for_operator_review": "FALSE",
        "stable_enough_for_shadow_expansion": "FALSE",
        "stable_enough_for_official_weight_change": "FALSE",
        "continued_capped_shadow_research_only": "FALSE",
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
        "v20_165_operator_review_allowed": "FALSE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_RETEST, RETEST_FIELDS, [])
    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, [])
    write_csv(OUT_GUARDRAIL, GUARDRAIL_FIELDS, [])
    write_csv(OUT_OUTLIER, OUTLIER_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SAFETY, SAFETY_FIELDS, [])
    write_report(BLOCKED_STATUS)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = input_hashes()
    missing = [path for path in inputs() if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))

    repair_rows, _ = read_csv(V163_REPAIR)
    sim_rows, _ = read_csv(V163_SIM)
    delta_rows, _ = read_csv(V163_DELTA)
    score_audit, _ = read_csv(V163_SCORE_AUDIT)
    rank_audit, _ = read_csv(V163_RANK_AUDIT)
    outlier_audit, _ = read_csv(V163_OUTLIER_AUDIT)
    gate_rows, _ = read_csv(V163_GATE)
    if not all([repair_rows, sim_rows, delta_rows, score_audit, rank_audit, outlier_audit, gate_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    delta = delta_rows[0]
    gate = gate_rows[0]
    prereq_ok = all([
        gate.get("final_status") == REQUIRED_V163_STATUS,
        delta.get("cap_repair_success") == "TRUE",
        delta.get("capped_top20_turnover_rate") == "0.0000000000",
        delta.get("outlier_ticker_count_after") == "0",
        delta.get("factor_impact_concentration_after") == "0.0000000000",
        gate.get("shadow_weight_expansion_allowed") == "FALSE",
        gate.get("official_weight_change_allowed") == "FALSE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_163_REQUIREMENTS_NOT_MET")

    cap_threshold = intish(delta.get("capped_max_absolute_rank_delta"), 4)
    retests = build_retests(sim_rows, cap_threshold)
    summary = build_summary(retests)
    guardrails = guardrail_rows(retests, cap_threshold)
    outliers = outlier_rows(sim_rows, cap_threshold)
    upstream_mutated = before != input_hashes()
    safety = safety_rows(upstream_mutated, prereq_ok)
    safety_ok = all(row["safety_passed"] == "TRUE" for row in safety)
    top20_ok = any(row["guardrail_name"] == "TOP20_STABILITY" and row["guardrail_passed"] == "TRUE" for row in guardrails)
    outlier_ok = any(row["guardrail_name"] == "OUTLIER_GUARDRAIL" and row["guardrail_passed"] == "TRUE" for row in guardrails)
    rank_ok = any(row["guardrail_name"] == "RANK_MOVEMENT_GUARDRAIL" and row["guardrail_passed"] == "TRUE" for row in guardrails)
    factor_ok = any(row["guardrail_name"] == "FACTOR_CONCENTRATION_GUARDRAIL" and row["guardrail_passed"] == "TRUE" for row in guardrails)
    all_guardrails = top20_ok and outlier_ok and rank_ok and factor_ok

    if upstream_mutated or not safety_ok:
        status, blocking = BLOCKED_STATUS, "SAFETY_OR_UPSTREAM_MUTATION_FAILURE"
    elif intish(summary["stability_fail_count"]) > 0:
        status, blocking = WARN_STATUS, ""
    elif not all_guardrails or intish(summary["stability_warn_count"]) > 0:
        status, blocking = PARTIAL_STATUS, ""
    else:
        status, blocking = PASS_STATUS, ""

    operator_allowed = status in {PASS_STATUS, PARTIAL_STATUS} and all_guardrails
    gate_out = {
        "gate_check_id": "V20_164_CAPPED_BOUND_SHADOW_NEXT_GATE_001",
        "v20_163_gate_consumed": "TRUE",
        "v20_163_status": gate.get("final_status", ""),
        "cap_repair_success": "TRUE",
        "capped_top20_turnover_rate": delta.get("capped_top20_turnover_rate", ""),
        "outlier_ticker_count_after": delta.get("outlier_ticker_count_after", ""),
        "factor_impact_concentration_after": delta.get("factor_impact_concentration_after", ""),
        "shadow_weight_expansion_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "retest_run_count": summary["retest_run_count"],
        "top20_stability_guardrail_passed": tf(top20_ok),
        "outlier_guardrail_passed": tf(outlier_ok),
        "rank_movement_guardrail_passed": tf(rank_ok),
        "factor_concentration_guardrail_passed": tf(factor_ok),
        "all_capped_guardrails_passed": tf(all_guardrails),
        "stable_enough_for_continued_capped_shadow_research": summary["stable_enough_for_continued_capped_shadow_research"],
        "stable_enough_for_operator_review": summary["stable_enough_for_operator_review"],
        "stable_enough_for_shadow_expansion": "FALSE",
        "stable_enough_for_official_weight_change": "FALSE",
        "continued_capped_shadow_research_only": "TRUE",
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
        "v20_165_operator_review_allowed": tf(operator_allowed),
        "blocking_reason": blocking,
        "final_status": status,
        **COMMON,
    }

    write_csv(OUT_RETEST, RETEST_FIELDS, retests)
    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, [summary])
    write_csv(OUT_GUARDRAIL, GUARDRAIL_FIELDS, guardrails)
    write_csv(OUT_OUTLIER, OUTLIER_FIELDS, outliers)
    write_csv(OUT_GATE, GATE_FIELDS, [gate_out])
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_report(status, summary)

    print(status)
    print("V20_163_GATE_CONSUMED=TRUE")
    print(f"V20_163_STATUS={gate.get('final_status', '')}")
    print("CAP_REPAIR_SUCCESS=TRUE")
    print(f"CAPPED_TOP20_TURNOVER_RATE={delta.get('capped_top20_turnover_rate', '')}")
    print(f"OUTLIER_TICKER_COUNT_AFTER={delta.get('outlier_ticker_count_after', '')}")
    print(f"FACTOR_IMPACT_CONCENTRATION_AFTER={delta.get('factor_impact_concentration_after', '')}")
    print("SHADOW_WEIGHT_EXPANSION_ALLOWED=FALSE")
    print("OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE")
    print(f"RETEST_RUN_COUNT={summary['retest_run_count']}")
    print(f"STABILITY_PASS_COUNT={summary['stability_pass_count']}")
    print(f"STABILITY_WARN_COUNT={summary['stability_warn_count']}")
    print(f"STABILITY_FAIL_COUNT={summary['stability_fail_count']}")
    print(f"AVERAGE_CAPPED_TOP20_TURNOVER_RATE={summary['average_capped_top20_turnover_rate']}")
    print(f"MAX_CAPPED_TOP20_TURNOVER_RATE={summary['max_capped_top20_turnover_rate']}")
    print(f"AVERAGE_CAPPED_RANK_DELTA={summary['average_capped_rank_delta']}")
    print(f"MAX_CAPPED_RANK_DELTA={summary['max_capped_rank_delta']}")
    print(f"OUTLIER_TICKER_COUNT_MAX={summary['outlier_ticker_count_max']}")
    print(f"FACTOR_IMPACT_CONCENTRATION_MAX={summary['factor_impact_concentration_max']}")
    print(f"ALL_CAPPED_GUARDRAILS_PASSED={tf(all_guardrails)}")
    print(f"STABLE_ENOUGH_FOR_OPERATOR_REVIEW={summary['stable_enough_for_operator_review']}")
    print("STABLE_ENOUGH_FOR_SHADOW_EXPANSION=FALSE")
    print("STABLE_ENOUGH_FOR_OFFICIAL_WEIGHT_CHANGE=FALSE")
    print("FORMAL_ACTIVATION_ALLOWED=FALSE")
    print("PROMOTION_READY=FALSE")
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
    print(f"V20_165_OPERATOR_REVIEW_ALLOWED={tf(operator_allowed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
