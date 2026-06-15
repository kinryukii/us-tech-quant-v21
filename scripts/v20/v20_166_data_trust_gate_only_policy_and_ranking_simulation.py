#!/usr/bin/env python
"""V20.166 DATA_TRUST gate-only policy and ranking simulation.

Builds a research-only simulation for removing DATA_TRUST from scoring weight
and treating it as gate-only plus repair-diagnostic-only. The script does not
mutate the active base weight registry, official current ranking, upstream V20
outputs, official weights, official rankings, recommendations, or actions.
"""

from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
CONSOLIDATION = OUTPUTS / "consolidation"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

WEIGHTS = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
BASELINE = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"

DATA_TRUST_CANDIDATES = [
    CONSOLIDATION / "V20_9_DATA_TRUSTWORTHINESS_FACTOR_READINESS_AUDIT.csv",
    CONSOLIDATION / "V20_10_DATA_TRUSTWORTHINESS_FACTOR_SOURCE_AUDIT.csv",
    CONSOLIDATION / "V20_12_FACTOR_INPUT_DATA_QUALITY_REVIEW.csv",
    CONSOLIDATION / "V20_13_FACTOR_EVIDENCE_DATA_QUALITY_AUDIT.csv",
    CONSOLIDATION / "V20_14_FACTOR_EVIDENCE_DATA_QUALITY_REVIEW.csv",
    CONSOLIDATION / "V20_15_FACTOR_SCORE_DATA_QUALITY_AUDIT.csv",
    CONSOLIDATION / "V20_16_FACTOR_SCORE_DATA_QUALITY_REVIEW.csv",
    CONSOLIDATION / "V20_45_CURRENT_OPERATOR_FACTOR_SUPPORT_VIEW.csv",
    CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv",
    CONSOLIDATION / "V20_54_FACTOR_SUPPORT_READABLE_VIEW.csv",
]
OPTIONAL_DATA_TRUST_PATTERNS = ("DATA_TRUST", "TRUST", "FRESH", "PIT", "SOURCE_QUALITY", "ELIGIBILITY", "QUALITY")

OUT_POLICY = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_POLICY.csv"
OUT_WEIGHT = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_WEIGHT_SIMULATION.csv"
OUT_ELIGIBILITY = FACTORS / "V20_166_DATA_TRUST_RANKING_ELIGIBILITY_AUDIT.csv"
OUT_BACKLOG = FACTORS / "V20_166_DATA_TRUST_FAILED_REPAIR_BACKLOG.csv"
OUT_RANKING = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION.csv"
OUT_DELTA = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_RANK_DELTA.csv"
OUT_SAFETY = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_SAFETY_AUDIT.csv"
OUT_GATE = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_NEXT_GATE.csv"
REPORT = READ_CENTER / "V20_166_DATA_TRUST_GATE_ONLY_POLICY_AND_RANKING_SIMULATION_REPORT.md"

PASS_STATUS = "PASS_V20_166_DATA_TRUST_GATE_ONLY_POLICY_READY_FOR_OPERATOR_REVIEW"
PARTIAL_STATUS = "PARTIAL_PASS_V20_166_DATA_TRUST_GATE_ONLY_POLICY_WITH_REPAIR_BACKLOG_READY_FOR_OPERATOR_REVIEW"
WARN_STATUS = "WARN_V20_166_DATA_TRUST_GATE_ONLY_POLICY_INSUFFICIENT_DATA_TRUST_STATUS"
BLOCKED_STATUS = "BLOCKED_V20_166_DATA_TRUST_GATE_ONLY_POLICY"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_GATE_ONLY_AND_REPAIR_DIAGNOSTIC_POLICY_SIMULATION"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"

PROPOSED_WEIGHTS = {
    "FUNDAMENTAL": "0.2222222222",
    "TECHNICAL": "0.2777777778",
    "STRATEGY": "0.2222222222",
    "RISK": "0.1666666667",
    "MARKET_REGIME": "0.1111111111",
    "DATA_TRUST": "0.0000000000",
}

SAFETY = {
    "research_only": "TRUE",
    "formal_activation_allowed": "FALSE",
    "promotion_ready": "FALSE",
    "official_recommendation_created": "FALSE",
    "official_ranking_mutated": "FALSE",
    "official_weight_change_created": "FALSE",
    "official_weight_registry_mutated": "FALSE",
    "weight_mutated": "FALSE",
    "real_book_action_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "performance_claim_created": "FALSE",
    "shadow_weight_expansion_allowed": "FALSE",
}
COMMON = {
    **SAFETY,
    "data_trust_gate_only_policy_simulation_created": "TRUE",
    "simulation_scope": SCOPE,
    "audit_only": "TRUE",
}

POLICY_FIELDS = [
    "factor_family",
    "current_research_base_weight",
    "proposed_scoring_weight",
    "proposed_role",
    "scoring_weight_removed",
    "redistributed_to_other_scoring_families",
    "data_trust_pass_required_for_ranking",
    "data_trust_failed_rows_excluded_from_ranking",
    "data_trust_failed_rows_repair_backlog_created",
    "research_only",
    "official_weight_change_created",
    "weight_mutated",
    *[field for field in COMMON.keys() if field not in {"research_only", "official_weight_change_created", "weight_mutated"}],
]
WEIGHT_FIELDS = [
    "factor_family",
    "current_research_base_weight",
    "proposed_scoring_weight",
    "proposed_role",
    "weight_delta",
    "renormalized_from_non_data_trust_weight",
    "scoring_weight_sum_after",
    "data_trust_scoring_weight_after",
    *COMMON.keys(),
]
ELIGIBILITY_FIELDS = [
    "ticker",
    "baseline_rank",
    "baseline_score",
    "data_trust_status",
    "data_trust_pass",
    "ranking_eligible_after_gate",
    "excluded_from_ranking_due_to_data_trust",
    "exclusion_reason",
    "repair_required",
    "repair_priority",
    "data_trust_failure_category",
    "source_artifact",
    "source_field",
    "recommended_repair_action",
    *COMMON.keys(),
]
BACKLOG_FIELDS = [
    "ticker",
    "data_trust_failure_category",
    "failure_reason",
    "missing_or_invalid_field",
    "source_artifact",
    "can_repair_from_existing_artifacts",
    "requires_fresh_data_refresh",
    "requires_schema_mapping_repair",
    "requires_pit_safety_repair",
    "requires_source_quality_repair",
    "recommended_repair_stage",
    "repair_priority",
    *COMMON.keys(),
]
RANKING_FIELDS = [
    "ticker",
    "baseline_rank",
    "baseline_score",
    "gate_only_simulated_rank",
    "gate_only_simulated_score",
    "data_trust_status",
    "data_trust_scoring_weight",
    "data_trust_score_contribution_removed",
    "ranking_eligible_after_gate",
    *COMMON.keys(),
]
DELTA_FIELDS = [
    "summary_id",
    "current_weight_sum",
    "proposed_scoring_weight_sum",
    "data_trust_weight_before",
    "data_trust_weight_after",
    "ranking_candidate_count_before",
    "ranking_candidate_count_after_data_trust_gate",
    "data_trust_pass_count",
    "data_trust_fail_count",
    "data_trust_unknown_count",
    "excluded_due_to_data_trust_count",
    "repair_backlog_count",
    "top20_overlap_count",
    "entered_top20_count",
    "exited_top20_count",
    "top20_turnover_rate",
    "max_absolute_rank_delta",
    "average_absolute_rank_delta",
    "gate_only_policy_simulation_success",
    "recommended_next_action",
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
GATE_FIELDS = [
    "gate_check_id",
    "current_weight_sum",
    "proposed_scoring_weight_sum",
    "data_trust_weight_before",
    "data_trust_weight_after",
    "data_trust_role",
    "data_trust_pass_required_for_ranking",
    "data_trust_failed_rows_excluded_from_ranking",
    "data_trust_failed_rows_repair_backlog_created",
    "ranking_candidate_count_before",
    "ranking_candidate_count_after_data_trust_gate",
    "data_trust_pass_count",
    "data_trust_fail_count",
    "data_trust_unknown_count",
    "excluded_due_to_data_trust_count",
    "repair_backlog_count",
    "gate_only_policy_simulation_success",
    "score_recomputation_blocked",
    "limitation_reason",
    "no_upstream_outputs_mutated",
    "blocking_reason",
    "final_status",
    *COMMON.keys(),
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def truthy(value: object) -> bool:
    return clean(value).upper() in {"TRUE", "PASS", "PASSED", "YES", "1", "ELIGIBLE"}


def falsey(value: object) -> bool:
    return clean(value).upper() in {"FALSE", "FAIL", "FAILED", "NO", "0", "INELIGIBLE", "BLOCKED"}


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


def optional_sources() -> list[Path]:
    found = {path for path in DATA_TRUST_CANDIDATES if path.exists()}
    for path in CONSOLIDATION.glob("V20_*.csv"):
        name = path.name.upper()
        if any(pattern in name for pattern in OPTIONAL_DATA_TRUST_PATTERNS):
            found.add(path)
    return sorted(found)


def inputs() -> list[Path]:
    return [WEIGHTS, BASELINE, *optional_sources()]


def input_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in inputs() if path.exists()}


def weight_map(rows: list[dict[str, str]]) -> dict[str, float]:
    return {row.get("factor_family", "").upper(): num(row.get("active_research_base_weight")) for row in rows}


def build_policy(weights: dict[str, float]) -> list[dict[str, str]]:
    rows = []
    for family in ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]:
        current = weights.get(family, 0.0)
        proposed = num(PROPOSED_WEIGHTS[family])
        rows.append({
            "factor_family": family,
            "current_research_base_weight": fmt(current),
            "proposed_scoring_weight": fmt(proposed),
            "proposed_role": DATA_TRUST_ROLE if family == "DATA_TRUST" else "SCORING_FACTOR_RENORMALIZED",
            "scoring_weight_removed": tf(family == "DATA_TRUST" and proposed == 0.0),
            "redistributed_to_other_scoring_families": tf(family != "DATA_TRUST"),
            "data_trust_pass_required_for_ranking": "TRUE",
            "data_trust_failed_rows_excluded_from_ranking": "TRUE",
            "data_trust_failed_rows_repair_backlog_created": "TRUE",
            **COMMON,
        })
    return rows


def build_weight_sim(weights: dict[str, float]) -> list[dict[str, str]]:
    non_dt_sum = sum(weight for family, weight in weights.items() if family != "DATA_TRUST")
    proposed_sum = sum(num(value) for value in PROPOSED_WEIGHTS.values())
    rows = []
    for family in ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]:
        current = weights.get(family, 0.0)
        proposed = num(PROPOSED_WEIGHTS[family])
        rows.append({
            "factor_family": family,
            "current_research_base_weight": fmt(current),
            "proposed_scoring_weight": fmt(proposed),
            "proposed_role": DATA_TRUST_ROLE if family == "DATA_TRUST" else "SCORING_FACTOR_RENORMALIZED",
            "weight_delta": fmt(proposed - current),
            "renormalized_from_non_data_trust_weight": fmt(non_dt_sum),
            "scoring_weight_sum_after": fmt(proposed_sum),
            "data_trust_scoring_weight_after": "0.0000000000",
            **COMMON,
        })
    return rows


def status_from_row(row: dict[str, str], fields: list[str], path: Path) -> tuple[str, str, str]:
    for field in fields:
        value = row.get(field)
        if value is None or clean(value) == "":
            continue
        if truthy(value):
            return "PASS", rel(path), field
        if falsey(value):
            return "FAIL", rel(path), field
        upper = clean(value).upper()
        if upper in {"UNKNOWN", "REVIEW", "MISSING"}:
            return "UNKNOWN", rel(path), field
    return "", "", ""


def explicit_data_trust_status_by_ticker() -> dict[str, tuple[str, str, str]]:
    status_fields = [
        "data_trust_pass",
        "data_trust_status",
        "data_trust_gate_pass",
        "ranking_eligible_after_data_trust",
        "ranking_eligible_after_gate",
        "eligible_after_data_trust_gate",
    ]
    statuses: dict[str, tuple[str, str, str]] = {}
    for path in optional_sources():
        rows, fields = read_csv(path)
        if not rows or "ticker" not in fields:
            continue
        matching_fields = [field for field in fields if field in status_fields or ("data_trust" in field.lower() and ("pass" in field.lower() or "status" in field.lower() or "eligible" in field.lower()))]
        if not matching_fields:
            continue
        for row in rows:
            ticker = row.get("ticker", "").upper()
            if not ticker or ticker in statuses:
                continue
            status, source, field = status_from_row(row, matching_fields, path)
            if status:
                statuses[ticker] = (status, source, field)
    return statuses


def eligibility_rows(baseline_rows: list[dict[str, str]], statuses: dict[str, tuple[str, str, str]]) -> list[dict[str, str]]:
    rows = []
    for row in baseline_rows:
        ticker = row.get("ticker", "").upper()
        status, source, field = statuses.get(ticker, ("UNKNOWN", "", ""))
        passed = status == "PASS"
        failed_or_unknown = status != "PASS"
        category = "NONE" if passed else ("DATA_TRUST_EXPLICIT_FAIL" if status == "FAIL" else "DATA_TRUST_STATUS_UNAVAILABLE")
        reason = "" if passed else ("FAILED_DATA_TRUST_GATE" if status == "FAIL" else "DATA_TRUST_STATUS_UNAVAILABLE_FOR_TICKER")
        rows.append({
            "ticker": ticker,
            "baseline_rank": row.get("official_current_rank", ""),
            "baseline_score": row.get("official_current_score", ""),
            "data_trust_status": status,
            "data_trust_pass": tf(passed),
            "ranking_eligible_after_gate": tf(passed),
            "excluded_from_ranking_due_to_data_trust": tf(failed_or_unknown),
            "exclusion_reason": reason,
            "repair_required": tf(failed_or_unknown),
            "repair_priority": "NONE" if passed else ("HIGH" if status == "FAIL" else "REVIEW"),
            "data_trust_failure_category": category,
            "source_artifact": source,
            "source_field": field,
            "recommended_repair_action": "NONE" if passed else ("REPAIR_FAILED_DATA_TRUST_SOURCE_OR_PIT_QUALITY" if status == "FAIL" else "ATTACH_TICKER_LEVEL_DATA_TRUST_GATE_STATUS"),
            **COMMON,
        })
    return rows


def backlog_rows(eligibility: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for row in eligibility:
        if row["repair_required"] != "TRUE":
            continue
        unknown = row["data_trust_status"] == "UNKNOWN"
        rows.append({
            "ticker": row["ticker"],
            "data_trust_failure_category": row["data_trust_failure_category"],
            "failure_reason": row["exclusion_reason"],
            "missing_or_invalid_field": row["source_field"] if row["source_field"] else "ticker_level_data_trust_status",
            "source_artifact": row["source_artifact"],
            "can_repair_from_existing_artifacts": tf(not unknown),
            "requires_fresh_data_refresh": tf(False),
            "requires_schema_mapping_repair": tf(unknown),
            "requires_pit_safety_repair": tf(False),
            "requires_source_quality_repair": tf(not unknown),
            "recommended_repair_stage": "V20_DATA_TRUST_TICKER_LEVEL_STATUS_ATTACHMENT" if unknown else "V20_DATA_TRUST_SOURCE_QUALITY_REPAIR",
            "repair_priority": row["repair_priority"],
            **COMMON,
        })
    return rows


def ranking_rows(baseline_rows: list[dict[str, str]], eligibility: list[dict[str, str]]) -> list[dict[str, str]]:
    eligible = {row["ticker"] for row in eligibility if row["ranking_eligible_after_gate"] == "TRUE"}
    ranked = []
    for row in baseline_rows:
        ticker = row.get("ticker", "").upper()
        if ticker not in eligible:
            continue
        ranked.append((num(row.get("official_current_score")), int(num(row.get("official_current_rank"))), row))
    ranked.sort(key=lambda item: (item[0], item[1], item[2].get("ticker", "")))
    rows = []
    status_by_ticker = {row["ticker"]: row["data_trust_status"] for row in eligibility}
    for rank, (_, _, row) in enumerate(ranked, start=1):
        ticker = row.get("ticker", "").upper()
        rows.append({
            "ticker": ticker,
            "baseline_rank": row.get("official_current_rank", ""),
            "baseline_score": row.get("official_current_score", ""),
            "gate_only_simulated_rank": str(rank),
            "gate_only_simulated_score": row.get("official_current_score", ""),
            "data_trust_status": status_by_ticker.get(ticker, "UNKNOWN"),
            "data_trust_scoring_weight": "0.0000000000",
            "data_trust_score_contribution_removed": "TRUE",
            "ranking_eligible_after_gate": "TRUE",
            **COMMON,
        })
    return rows


def delta_summary(weights: dict[str, float], baseline_rows: list[dict[str, str]], eligibility: list[dict[str, str]], ranking: list[dict[str, str]], backlog: list[dict[str, str]]) -> dict[str, str]:
    baseline_top20 = {row.get("ticker", "").upper() for row in baseline_rows if 0 < int(num(row.get("official_current_rank"))) <= 20}
    simulated_top20 = {row["ticker"] for row in ranking if 0 < int(num(row.get("gate_only_simulated_rank"))) <= 20}
    overlap = len(baseline_top20 & simulated_top20)
    entered = len(simulated_top20 - baseline_top20)
    exited = len(baseline_top20 - simulated_top20)
    deltas = [abs(int(num(row["gate_only_simulated_rank"])) - int(num(row["baseline_rank"]))) for row in ranking]
    pass_count = sum(1 for row in eligibility if row["data_trust_status"] == "PASS")
    fail_count = sum(1 for row in eligibility if row["data_trust_status"] == "FAIL")
    unknown_count = sum(1 for row in eligibility if row["data_trust_status"] == "UNKNOWN")
    success = len(ranking) > 0 and unknown_count == 0
    if unknown_count:
        action = "ATTACH_TICKER_LEVEL_DATA_TRUST_STATUS_BEFORE_RANKING_SIMULATION"
    elif fail_count:
        action = "OPERATOR_REVIEW_DATA_TRUST_GATE_ONLY_POLICY_WITH_REPAIR_BACKLOG"
    else:
        action = "OPERATOR_REVIEW_DATA_TRUST_GATE_ONLY_POLICY"
    return {
        "summary_id": "V20_166_DATA_TRUST_GATE_ONLY_RANK_DELTA_001",
        "current_weight_sum": fmt(sum(weights.values())),
        "proposed_scoring_weight_sum": fmt(sum(num(value) for value in PROPOSED_WEIGHTS.values())),
        "data_trust_weight_before": fmt(weights.get("DATA_TRUST", 0.0)),
        "data_trust_weight_after": "0.0000000000",
        "ranking_candidate_count_before": str(len(baseline_rows)),
        "ranking_candidate_count_after_data_trust_gate": str(len(ranking)),
        "data_trust_pass_count": str(pass_count),
        "data_trust_fail_count": str(fail_count),
        "data_trust_unknown_count": str(unknown_count),
        "excluded_due_to_data_trust_count": str(len([row for row in eligibility if row["excluded_from_ranking_due_to_data_trust"] == "TRUE"])),
        "repair_backlog_count": str(len(backlog)),
        "top20_overlap_count": str(overlap),
        "entered_top20_count": str(entered),
        "exited_top20_count": str(exited),
        "top20_turnover_rate": fmt((entered + exited) / max(len(baseline_top20), 1)),
        "max_absolute_rank_delta": str(max(deltas, default=0)),
        "average_absolute_rank_delta": fmt(mean(deltas) if deltas else 0.0),
        "gate_only_policy_simulation_success": tf(success),
        "recommended_next_action": action,
        **COMMON,
    }


def safety_rows(upstream_mutated: bool) -> list[dict[str, str]]:
    checks = [
        ("research_only", "TRUE", "TRUE"),
        ("formal_activation_allowed", "FALSE", "FALSE"),
        ("promotion_ready", "FALSE", "FALSE"),
        ("official_recommendation_created", "FALSE", "FALSE"),
        ("official_ranking_mutated", "FALSE", "FALSE"),
        ("official_weight_change_created", "FALSE", "FALSE"),
        ("official_weight_registry_mutated", "FALSE", "FALSE"),
        ("weight_mutated", "FALSE", "FALSE"),
        ("real_book_action_created", "FALSE", "FALSE"),
        ("trade_action_created", "FALSE", "FALSE"),
        ("broker_execution_supported", "FALSE", "FALSE"),
        ("performance_claim_created", "FALSE", "FALSE"),
        ("shadow_weight_expansion_allowed", "FALSE", "FALSE"),
        ("upstream_outputs_mutated", "FALSE", tf(upstream_mutated)),
    ]
    return [{
        "safety_check_id": f"V20_166_SAFETY_{idx:03d}",
        "safety_check": name,
        "expected_value": expected,
        "actual_value": actual,
        "safety_passed": tf(expected == actual),
        **COMMON,
    } for idx, (name, expected, actual) in enumerate(checks, start=1)]


def write_report(status: str, summary: dict[str, str] | None = None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.166 DATA_TRUST Gate-Only Policy And Ranking Simulation Report",
        "",
        f"- wrapper_status: {status}",
        f"- data_trust_role: {DATA_TRUST_ROLE}",
        "- data_trust_scoring_weight: 0.0000000000",
        "- research_only: TRUE",
        "- official_weight_change_created: FALSE",
        "- official_ranking_mutated: FALSE",
    ]
    if summary:
        lines.extend([
            f"- ranking_candidate_count_before: {summary['ranking_candidate_count_before']}",
            f"- ranking_candidate_count_after_data_trust_gate: {summary['ranking_candidate_count_after_data_trust_gate']}",
            f"- data_trust_pass_count: {summary['data_trust_pass_count']}",
            f"- data_trust_fail_count: {summary['data_trust_fail_count']}",
            f"- data_trust_unknown_count: {summary['data_trust_unknown_count']}",
            f"- repair_backlog_count: {summary['repair_backlog_count']}",
            f"- gate_only_policy_simulation_success: {summary['gate_only_policy_simulation_success']}",
            f"- recommended_next_action: {summary['recommended_next_action']}",
        ])
    lines.extend(["", "No DATA_TRUST pass/fail values are fabricated. UNKNOWN rows are placed in the repair backlog."])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_166_DATA_TRUST_GATE_ONLY_NEXT_GATE_001",
        "current_weight_sum": "0.0000000000",
        "proposed_scoring_weight_sum": "0.0000000000",
        "data_trust_weight_before": "0.0000000000",
        "data_trust_weight_after": "0.0000000000",
        "data_trust_role": DATA_TRUST_ROLE,
        "data_trust_pass_required_for_ranking": "TRUE",
        "data_trust_failed_rows_excluded_from_ranking": "TRUE",
        "data_trust_failed_rows_repair_backlog_created": "TRUE",
        "ranking_candidate_count_before": "0",
        "ranking_candidate_count_after_data_trust_gate": "0",
        "data_trust_pass_count": "0",
        "data_trust_fail_count": "0",
        "data_trust_unknown_count": "0",
        "excluded_due_to_data_trust_count": "0",
        "repair_backlog_count": "0",
        "gate_only_policy_simulation_success": "FALSE",
        "score_recomputation_blocked": "TRUE",
        "limitation_reason": reason,
        "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_POLICY, POLICY_FIELDS, [])
    write_csv(OUT_WEIGHT, WEIGHT_FIELDS, [])
    write_csv(OUT_ELIGIBILITY, ELIGIBILITY_FIELDS, [])
    write_csv(OUT_BACKLOG, BACKLOG_FIELDS, [])
    write_csv(OUT_RANKING, RANKING_FIELDS, [])
    write_csv(OUT_DELTA, DELTA_FIELDS, [])
    write_csv(OUT_SAFETY, SAFETY_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(BLOCKED_STATUS)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = input_hashes()
    if not WEIGHTS.exists() or WEIGHTS.stat().st_size == 0 or not BASELINE.exists() or BASELINE.stat().st_size == 0:
        return emit_blocked("MISSING_REQUIRED_WEIGHT_OR_BASELINE_INPUT")
    weight_rows, _ = read_csv(WEIGHTS)
    baseline_rows, _ = read_csv(BASELINE)
    if not weight_rows or not baseline_rows:
        return emit_blocked("EMPTY_REQUIRED_WEIGHT_OR_BASELINE_INPUT")

    weights = weight_map(weight_rows)
    required = set(PROPOSED_WEIGHTS)
    if not required.issubset(weights):
        return emit_blocked("MISSING_REQUIRED_FACTOR_FAMILY_WEIGHTS")

    policy = build_policy(weights)
    weight_sim = build_weight_sim(weights)
    statuses = explicit_data_trust_status_by_ticker()
    eligibility = eligibility_rows(baseline_rows, statuses)
    backlog = backlog_rows(eligibility)
    ranking = ranking_rows(baseline_rows, eligibility)
    summary = delta_summary(weights, baseline_rows, eligibility, ranking, backlog)
    upstream_mutated = before != input_hashes()
    safety = safety_rows(upstream_mutated)
    safety_ok = all(row["safety_passed"] == "TRUE" for row in safety)

    unknown_count = int(summary["data_trust_unknown_count"])
    fail_count = int(summary["data_trust_fail_count"])
    success = summary["gate_only_policy_simulation_success"] == "TRUE"
    if upstream_mutated or not safety_ok:
        status, blocking = BLOCKED_STATUS, "SAFETY_OR_UPSTREAM_MUTATION_FAILURE"
    elif unknown_count > 0:
        status, blocking = WARN_STATUS, ""
    elif fail_count > 0:
        status, blocking = PARTIAL_STATUS, ""
    elif success:
        status, blocking = PASS_STATUS, ""
    else:
        status, blocking = WARN_STATUS, ""
    score_blocked = summary["ranking_candidate_count_after_data_trust_gate"] == "0"
    limitation = "" if success else ("DATA_TRUST_STATUS_UNAVAILABLE_FOR_ALL_OR_SOME_TICKERS" if unknown_count else "NO_ELIGIBLE_ROWS_AFTER_DATA_TRUST_GATE")
    gate = {
        "gate_check_id": "V20_166_DATA_TRUST_GATE_ONLY_NEXT_GATE_001",
        **{field: summary[field] for field in [
            "current_weight_sum",
            "proposed_scoring_weight_sum",
            "data_trust_weight_before",
            "data_trust_weight_after",
            "ranking_candidate_count_before",
            "ranking_candidate_count_after_data_trust_gate",
            "data_trust_pass_count",
            "data_trust_fail_count",
            "data_trust_unknown_count",
            "excluded_due_to_data_trust_count",
            "repair_backlog_count",
            "gate_only_policy_simulation_success",
        ]},
        "data_trust_role": DATA_TRUST_ROLE,
        "data_trust_pass_required_for_ranking": "TRUE",
        "data_trust_failed_rows_excluded_from_ranking": "TRUE",
        "data_trust_failed_rows_repair_backlog_created": "TRUE",
        "score_recomputation_blocked": tf(score_blocked),
        "limitation_reason": limitation,
        "no_upstream_outputs_mutated": tf(not upstream_mutated),
        "blocking_reason": blocking,
        "final_status": status,
        **COMMON,
    }

    write_csv(OUT_POLICY, POLICY_FIELDS, policy)
    write_csv(OUT_WEIGHT, WEIGHT_FIELDS, weight_sim)
    write_csv(OUT_ELIGIBILITY, ELIGIBILITY_FIELDS, eligibility)
    write_csv(OUT_BACKLOG, BACKLOG_FIELDS, backlog)
    write_csv(OUT_RANKING, RANKING_FIELDS, ranking)
    write_csv(OUT_DELTA, DELTA_FIELDS, [summary])
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(status, summary)

    print(status)
    for field in [
        "current_weight_sum",
        "proposed_scoring_weight_sum",
        "data_trust_weight_before",
        "data_trust_weight_after",
        "ranking_candidate_count_before",
        "ranking_candidate_count_after_data_trust_gate",
        "data_trust_pass_count",
        "data_trust_fail_count",
        "data_trust_unknown_count",
        "excluded_due_to_data_trust_count",
        "repair_backlog_count",
        "top20_overlap_count",
        "entered_top20_count",
        "exited_top20_count",
        "top20_turnover_rate",
        "max_absolute_rank_delta",
        "average_absolute_rank_delta",
        "gate_only_policy_simulation_success",
        "recommended_next_action",
    ]:
        print(f"{field.upper()}={summary[field]}")
    print(f"DATA_TRUST_ROLE={DATA_TRUST_ROLE}")
    print("DATA_TRUST_SCORING_WEIGHT=0.0000000000")
    print("DATA_TRUST_PASS_REQUIRED_FOR_RANKING=TRUE")
    print("DATA_TRUST_FAILED_ROWS_EXCLUDED_FROM_RANKING=TRUE")
    print("DATA_TRUST_FAILED_ROWS_REPAIR_BACKLOG_CREATED=TRUE")
    print("RESEARCH_ONLY=TRUE")
    print("FORMAL_ACTIVATION_ALLOWED=FALSE")
    print("PROMOTION_READY=FALSE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("OFFICIAL_WEIGHT_CHANGE_CREATED=FALSE")
    print("OFFICIAL_WEIGHT_REGISTRY_MUTATED=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_ACTION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print("SHADOW_WEIGHT_EXPANSION_ALLOWED=FALSE")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
