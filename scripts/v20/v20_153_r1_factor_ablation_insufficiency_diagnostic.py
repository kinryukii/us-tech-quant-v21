#!/usr/bin/env python
"""V20.153-R1 factor ablation insufficiency diagnostic.

Diagnoses why V20.153 factor ablation evidence remained insufficient. This is
diagnostic-only: it does not proceed to V20.154, create shadow weights, mutate
official weights, alter rankings, or fabricate outcomes/benchmarks/contribution
evidence.
"""

from __future__ import annotations

import csv
import hashlib
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

IN_MATRIX = FACTORS / "V20_153_FACTOR_ABLATION_MATRIX.csv"
IN_GATE = FACTORS / "V20_153_FACTOR_ABLATION_GATE.csv"
IN_SOURCE = FACTORS / "V20_153_FACTOR_ABLATION_SOURCE_AUDIT.csv"
IN_ELIGIBILITY = FACTORS / "V20_153_FACTOR_ABLATION_ELIGIBILITY_AUDIT.csv"
IN_GAP = FACTORS / "V20_153_FACTOR_ABLATION_GAP_AUDIT.csv"

OUT_DIAGNOSTIC = FACTORS / "V20_153_R1_FACTOR_ABLATION_INSUFFICIENCY_DIAGNOSTIC.csv"
OUT_BREAKDOWN = FACTORS / "V20_153_R1_FACTOR_ABLATION_BLOCKER_BREAKDOWN.csv"
OUT_REPAIR = FACTORS / "V20_153_R1_FACTOR_ABLATION_REPAIR_PLAN.csv"
OUT_NEXT_GATE = FACTORS / "V20_153_R1_FACTOR_ABLATION_NEXT_GATE.csv"
REPORT = READ_CENTER / "V20_153_R1_FACTOR_ABLATION_INSUFFICIENCY_DIAGNOSTIC_REPORT.md"

REQUIRED_V153_STATUS = "WARN_V20_153_INSUFFICIENT_FACTOR_ABLATION_EVIDENCE"
PASS_STATUS = "PASS_V20_153_R1_FACTOR_ABLATION_INSUFFICIENCY_DIAGNOSTIC_READY_FOR_REPAIR"
PARTIAL_STATUS = "PARTIAL_PASS_V20_153_R1_FACTOR_ABLATION_DIAGNOSTIC_WITH_UNREPAIRABLE_PENDING_OUTCOMES"
BLOCKED_STATUS = "BLOCKED_V20_153_R1_FACTOR_ABLATION_INSUFFICIENCY_DIAGNOSTIC"

MIN_ASOF = 4
MIN_OUTCOME = 4
MIN_BENCHMARK = 4
MIN_WINDOW = 2

SAFETY_FIELDS = [
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "official_weight_change_created",
    "shadow_weight_proposal_created",
    "weight_mutated",
    "real_book_action_created",
    "trade_action_created",
    "broker_execution_supported",
    "performance_claim_created",
]
SAFETY = {field: "FALSE" for field in SAFETY_FIELDS}
COMMON = {
    **SAFETY,
    "research_only": "TRUE",
    "staging_review_only": "TRUE",
    "diagnostic_only": "TRUE",
    "audit_only": "TRUE",
}

DIAGNOSTIC_FIELDS = [
    "diagnostic_id",
    "factor_family",
    "factor_name",
    "evidence_source",
    "missing_outcome_blocker",
    "missing_benchmark_blocker",
    "pending_forward_observation_blocker",
    "insufficient_as_of_sample_blocker",
    "insufficient_regime_coverage_blocker",
    "insufficient_window_coverage_blocker",
    "insufficient_contribution_attribution_blocker",
    "pit_safety_issue_blocker",
    "evidence_quality_threshold_blocker",
    "conservative_threshold_only_blocker",
    "blocker_count",
    "primary_blocker",
    "structurally_usable_except_threshold",
    "repairability_status",
    "exclusion_reason",
    *COMMON.keys(),
]
BREAKDOWN_FIELDS = [
    "blocker_category",
    "blocked_row_count",
    "affected_factor_family_count",
    "affected_evidence_source_count",
    "can_repair_from_existing_artifacts",
    "requires_future_forward_outcomes",
    "requires_new_backtest_generation",
    "safe_to_repair_without_fabrication",
    *COMMON.keys(),
]
REPAIR_FIELDS = [
    "blocker_category",
    "affected_row_count",
    "required_repair_action",
    "can_repair_from_existing_artifacts",
    "requires_future_forward_outcomes",
    "requires_new_backtest_generation",
    "safe_to_repair_without_fabrication",
    "recommended_next_stage",
    *COMMON.keys(),
]
NEXT_GATE_FIELDS = [
    "gate_check_id",
    "v20_153_gate_consumed",
    "v20_153_required_warn_status_confirmed",
    "v20_154_shadow_dynamic_weight_proposal_allowed",
    *SAFETY_FIELDS,
    "diagnostic_row_count",
    "missing_outcome_blocked_row_count",
    "missing_benchmark_blocked_row_count",
    "pending_forward_observation_blocked_row_count",
    "insufficient_as_of_sample_blocked_row_count",
    "insufficient_regime_coverage_blocked_row_count",
    "insufficient_window_coverage_blocked_row_count",
    "insufficient_contribution_attribution_blocked_row_count",
    "pit_safety_issue_blocked_row_count",
    "evidence_quality_threshold_blocked_row_count",
    "conservative_threshold_only_blocked_row_count",
    "repair_plan_row_count",
    "no_outcomes_fabricated",
    "no_benchmarks_fabricated",
    "no_factor_contribution_fabricated",
    "no_eligibility_thresholds_lowered",
    "no_shadow_weights_created",
    "no_official_weight_mutation",
    "no_official_ranking_changes",
    "no_upstream_outputs_mutated",
    "blocking_reason",
    "final_status",
    "research_only",
    "staging_review_only",
    "diagnostic_only",
    "audit_only",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def truthy(value: object) -> bool:
    return clean(value).upper() == "TRUE"


def num_int(value: object) -> int:
    try:
        return int(float(clean(value) or "0"))
    except ValueError:
        return 0


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
    return [IN_MATRIX, IN_GATE, IN_SOURCE, IN_ELIGIBILITY, IN_GAP]


def upstream_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in upstream_inputs() if path.exists()}


def source_pit_issue_map(source_rows: list[dict[str, str]]) -> dict[str, bool]:
    return {row.get("source_artifact", ""): "PIT" in row.get("exclusion_reason", "").upper() for row in source_rows}


def row_blockers(row: dict[str, str], pit_map: dict[str, bool]) -> dict[str, bool]:
    reason = row.get("exclusion_reason", "").upper()
    asof = num_int(row.get("as_of_sample_count"))
    outcome = num_int(row.get("outcome_available_count"))
    pending = num_int(row.get("pending_outcome_count"))
    benchmark = num_int(row.get("benchmark_available_count"))
    windows = num_int(row.get("window_coverage"))
    positive = num_int(row.get("positive_contribution_count"))
    negative = num_int(row.get("negative_contribution_count"))
    neutral = num_int(row.get("neutral_contribution_count"))
    contribution_total = positive + negative + neutral
    regime = row.get("regime_coverage", "")
    family = row.get("factor_family", "")
    pit_issue = "PIT" in reason or pit_map.get(row.get("evidence_source", ""), False)
    blockers = {
        "MISSING_OUTCOME": "INSUFFICIENT_OUTCOME" in reason or outcome < MIN_OUTCOME,
        "MISSING_BENCHMARK": "INSUFFICIENT_BENCHMARK" in reason or benchmark < MIN_BENCHMARK,
        "PENDING_FORWARD_OBSERVATION": pending > 0,
        "INSUFFICIENT_AS_OF_SAMPLE": "INSUFFICIENT_AS_OF" in reason or asof < MIN_ASOF,
        "INSUFFICIENT_REGIME_COVERAGE": family == "MARKET_REGIME" and regime != "PRESENT",
        "INSUFFICIENT_WINDOW_COVERAGE": windows < MIN_WINDOW,
        "INSUFFICIENT_CONTRIBUTION_ATTRIBUTION": "NO_FACTOR_CONTRIBUTION" in reason or contribution_total == 0 or row.get("contribution_stability") in {"UNKNOWN_NO_FACTOR_CONTRIBUTION_EVIDENCE", "LOW"},
        "PIT_SAFETY_ISSUE": pit_issue,
        "EVIDENCE_QUALITY_THRESHOLD": row.get("evidence_quality") != "HIGH",
    }
    structural_blockers = [
        "MISSING_OUTCOME",
        "MISSING_BENCHMARK",
        "PENDING_FORWARD_OBSERVATION",
        "INSUFFICIENT_AS_OF_SAMPLE",
        "INSUFFICIENT_REGIME_COVERAGE",
        "INSUFFICIENT_WINDOW_COVERAGE",
        "INSUFFICIENT_CONTRIBUTION_ATTRIBUTION",
        "PIT_SAFETY_ISSUE",
    ]
    blockers["CONSERVATIVE_THRESHOLD_ONLY"] = blockers["EVIDENCE_QUALITY_THRESHOLD"] and not any(blockers[key] for key in structural_blockers)
    return blockers


def primary_blocker(blockers: dict[str, bool]) -> str:
    order = [
        "PENDING_FORWARD_OBSERVATION",
        "MISSING_OUTCOME",
        "MISSING_BENCHMARK",
        "INSUFFICIENT_AS_OF_SAMPLE",
        "INSUFFICIENT_CONTRIBUTION_ATTRIBUTION",
        "INSUFFICIENT_WINDOW_COVERAGE",
        "INSUFFICIENT_REGIME_COVERAGE",
        "PIT_SAFETY_ISSUE",
        "EVIDENCE_QUALITY_THRESHOLD",
        "CONSERVATIVE_THRESHOLD_ONLY",
    ]
    return next((key for key in order if blockers.get(key)), "NO_BLOCKER_DETECTED")


def build_diagnostics(matrix_rows: list[dict[str, str]], source_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    pit_map = source_pit_issue_map(source_rows)
    diagnostics: list[dict[str, str]] = []
    for index, row in enumerate(matrix_rows, start=1):
        blockers = row_blockers(row, pit_map)
        blocker_count = sum(1 for value in blockers.values() if value)
        structurally_usable = blockers["CONSERVATIVE_THRESHOLD_ONLY"]
        pending = blockers["PENDING_FORWARD_OBSERVATION"]
        diagnostics.append({
            "diagnostic_id": f"V20_153_R1_FACTOR_ABLATION_DIAGNOSTIC_{index:04d}",
            "factor_family": row.get("factor_family", ""),
            "factor_name": row.get("factor_name", ""),
            "evidence_source": row.get("evidence_source", ""),
            "missing_outcome_blocker": tf(blockers["MISSING_OUTCOME"]),
            "missing_benchmark_blocker": tf(blockers["MISSING_BENCHMARK"]),
            "pending_forward_observation_blocker": tf(pending),
            "insufficient_as_of_sample_blocker": tf(blockers["INSUFFICIENT_AS_OF_SAMPLE"]),
            "insufficient_regime_coverage_blocker": tf(blockers["INSUFFICIENT_REGIME_COVERAGE"]),
            "insufficient_window_coverage_blocker": tf(blockers["INSUFFICIENT_WINDOW_COVERAGE"]),
            "insufficient_contribution_attribution_blocker": tf(blockers["INSUFFICIENT_CONTRIBUTION_ATTRIBUTION"]),
            "pit_safety_issue_blocker": tf(blockers["PIT_SAFETY_ISSUE"]),
            "evidence_quality_threshold_blocker": tf(blockers["EVIDENCE_QUALITY_THRESHOLD"]),
            "conservative_threshold_only_blocker": tf(blockers["CONSERVATIVE_THRESHOLD_ONLY"]),
            "blocker_count": str(blocker_count),
            "primary_blocker": primary_blocker(blockers),
            "structurally_usable_except_threshold": tf(structurally_usable),
            "repairability_status": "REQUIRES_FUTURE_FORWARD_OUTCOMES" if pending else "REPAIRABLE_FROM_EXISTING_OR_NEW_BACKTEST_EVIDENCE",
            "exclusion_reason": row.get("exclusion_reason", ""),
            **COMMON,
        })
    return diagnostics


def count_flag(rows: list[dict[str, str]], field: str) -> int:
    return sum(1 for row in rows if row.get(field) == "TRUE")


def build_breakdown(diagnostics: list[dict[str, str]]) -> list[dict[str, str]]:
    specs = [
        ("MISSING_OUTCOME", "missing_outcome_blocker", "FALSE", "FALSE", "TRUE"),
        ("MISSING_BENCHMARK", "missing_benchmark_blocker", "FALSE", "FALSE", "TRUE"),
        ("PENDING_FORWARD_OBSERVATION", "pending_forward_observation_blocker", "FALSE", "TRUE", "TRUE"),
        ("INSUFFICIENT_AS_OF_SAMPLE", "insufficient_as_of_sample_blocker", "TRUE", "FALSE", "TRUE"),
        ("INSUFFICIENT_REGIME_COVERAGE", "insufficient_regime_coverage_blocker", "TRUE", "FALSE", "TRUE"),
        ("INSUFFICIENT_WINDOW_COVERAGE", "insufficient_window_coverage_blocker", "TRUE", "FALSE", "TRUE"),
        ("INSUFFICIENT_CONTRIBUTION_ATTRIBUTION", "insufficient_contribution_attribution_blocker", "TRUE", "FALSE", "TRUE"),
        ("PIT_SAFETY_ISSUE", "pit_safety_issue_blocker", "TRUE", "FALSE", "TRUE"),
        ("EVIDENCE_QUALITY_THRESHOLD", "evidence_quality_threshold_blocker", "TRUE", "FALSE", "TRUE"),
        ("CONSERVATIVE_THRESHOLD_ONLY", "conservative_threshold_only_blocker", "TRUE", "FALSE", "TRUE"),
    ]
    rows: list[dict[str, str]] = []
    for category, field, existing, future, safe in specs:
        affected = [row for row in diagnostics if row.get(field) == "TRUE"]
        rows.append({
            "blocker_category": category,
            "blocked_row_count": str(len(affected)),
            "affected_factor_family_count": str(len({row["factor_family"] for row in affected})),
            "affected_evidence_source_count": str(len({row["evidence_source"] for row in affected})),
            "can_repair_from_existing_artifacts": existing,
            "requires_future_forward_outcomes": future,
            "requires_new_backtest_generation": "TRUE" if category in {"MISSING_OUTCOME", "MISSING_BENCHMARK", "INSUFFICIENT_AS_OF_SAMPLE", "INSUFFICIENT_WINDOW_COVERAGE"} else "FALSE",
            "safe_to_repair_without_fabrication": safe,
            **COMMON,
        })
    return rows


def build_repair_plan(breakdown: list[dict[str, str]]) -> list[dict[str, str]]:
    actions = {
        "MISSING_OUTCOME": "Attach certified outcome evidence or run a new non-fabricating random-as-of backtest when data exists.",
        "MISSING_BENCHMARK": "Attach certified benchmark evidence from existing cache or regenerate benchmark comparison without fabricating returns.",
        "PENDING_FORWARD_OBSERVATION": "Wait for forward windows to mature; do not infer outcomes early.",
        "INSUFFICIENT_AS_OF_SAMPLE": "Expand as-of sample coverage from existing eligible artifacts or generate additional PIT-safe samples.",
        "INSUFFICIENT_REGIME_COVERAGE": "Bind existing regime-conditioned evidence or run a dedicated regime coverage repair.",
        "INSUFFICIENT_WINDOW_COVERAGE": "Add existing certified forward-window evidence or run a non-fabricating multi-window backtest.",
        "INSUFFICIENT_CONTRIBUTION_ATTRIBUTION": "Attach explicit factor contribution/alpha attribution evidence; do not infer signs from unrelated fields.",
        "PIT_SAFETY_ISSUE": "Repair point-in-time source certification before using rows for factor ablation.",
        "EVIDENCE_QUALITY_THRESHOLD": "Improve evidence quality through certified inputs; thresholds must not be silently lowered.",
        "CONSERVATIVE_THRESHOLD_ONLY": "Route to operator-reviewed threshold policy check without changing eligibility automatically.",
    }
    plans: list[dict[str, str]] = []
    for row in breakdown:
        affected = int(row["blocked_row_count"])
        if affected == 0:
            continue
        category = row["blocker_category"]
        plans.append({
            "blocker_category": category,
            "affected_row_count": str(affected),
            "required_repair_action": actions[category],
            "can_repair_from_existing_artifacts": row["can_repair_from_existing_artifacts"],
            "requires_future_forward_outcomes": row["requires_future_forward_outcomes"],
            "requires_new_backtest_generation": row["requires_new_backtest_generation"],
            "safe_to_repair_without_fabrication": row["safe_to_repair_without_fabrication"],
            "recommended_next_stage": "V20.153_R2_PENDING_OUTCOME_WAIT_OR_OBSERVATION_REFRESH" if row["requires_future_forward_outcomes"] == "TRUE" else "V20.153_R2_FACTOR_ABLATION_EVIDENCE_REPAIR",
            **COMMON,
        })
    return plans


def safety_true_count(groups: list[list[dict[str, str]]]) -> int:
    return sum(1 for rows in groups for row in rows for field in SAFETY_FIELDS if truthy(row.get(field)))


def write_report(status: str, diagnostics: int, repair_rows: int, pending_count: int) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.153-R1 Factor Ablation Insufficiency Diagnostic Report",
        "",
        f"- wrapper_status: {status}",
        f"- diagnostic_row_count: {diagnostics}",
        f"- repair_plan_row_count: {repair_rows}",
        f"- pending_forward_observation_blocked_row_count: {pending_count}",
        "- V20_154_SHADOW_DYNAMIC_WEIGHT_PROPOSAL_ALLOWED: FALSE",
        "- shadow_weight_proposal_created: FALSE",
        "- official_weight_change_created: FALSE",
        "",
        "This diagnostic explains the V20.153 insufficient-evidence warning. It does not fabricate evidence, lower thresholds, create shadow weights, mutate official weights, or proceed to V20.154.",
    ]) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_153_R1_FACTOR_ABLATION_NEXT_GATE_001",
        "v20_153_gate_consumed": "FALSE",
        "v20_153_required_warn_status_confirmed": "FALSE",
        "v20_154_shadow_dynamic_weight_proposal_allowed": "FALSE",
        **SAFETY,
        "diagnostic_row_count": "0",
        "missing_outcome_blocked_row_count": "0",
        "missing_benchmark_blocked_row_count": "0",
        "pending_forward_observation_blocked_row_count": "0",
        "insufficient_as_of_sample_blocked_row_count": "0",
        "insufficient_regime_coverage_blocked_row_count": "0",
        "insufficient_window_coverage_blocked_row_count": "0",
        "insufficient_contribution_attribution_blocked_row_count": "0",
        "pit_safety_issue_blocked_row_count": "0",
        "evidence_quality_threshold_blocked_row_count": "0",
        "conservative_threshold_only_blocked_row_count": "0",
        "repair_plan_row_count": "0",
        "no_outcomes_fabricated": "TRUE",
        "no_benchmarks_fabricated": "TRUE",
        "no_factor_contribution_fabricated": "TRUE",
        "no_eligibility_thresholds_lowered": "TRUE",
        "no_shadow_weights_created": "TRUE",
        "no_official_weight_mutation": "TRUE",
        "no_official_ranking_changes": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        "research_only": "TRUE",
        "staging_review_only": "TRUE",
        "diagnostic_only": "TRUE",
        "audit_only": "TRUE",
    }
    write_csv(OUT_DIAGNOSTIC, DIAGNOSTIC_FIELDS, [])
    write_csv(OUT_BREAKDOWN, BREAKDOWN_FIELDS, [])
    write_csv(OUT_REPAIR, REPAIR_FIELDS, [])
    write_csv(OUT_NEXT_GATE, NEXT_GATE_FIELDS, [gate])
    write_report(BLOCKED_STATUS, 0, 0, 0)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = upstream_hashes()
    missing = [path for path in upstream_inputs() if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_V20_153_OUTPUTS:" + ";".join(rel(path) for path in missing))
    matrix_rows, _ = read_csv(IN_MATRIX)
    gate_rows, _ = read_csv(IN_GATE)
    source_rows, _ = read_csv(IN_SOURCE)
    eligibility_rows, _ = read_csv(IN_ELIGIBILITY)
    gap_rows, _ = read_csv(IN_GAP)
    if not all([matrix_rows, gate_rows, source_rows, eligibility_rows, gap_rows]):
        return emit_blocked("EMPTY_REQUIRED_V20_153_OUTPUTS")
    v153_status = clean(gate_rows[0].get("final_status")) or clean(gate_rows[0].get("factor_ablation_matrix_status"))
    if v153_status != REQUIRED_V153_STATUS:
        return emit_blocked("V20_153_STATUS_NOT_WARN_INSUFFICIENT_FACTOR_ABLATION_EVIDENCE")

    diagnostics = build_diagnostics(matrix_rows, source_rows)
    breakdown = build_breakdown(diagnostics)
    repair_plan = build_repair_plan(breakdown)
    safety_count = safety_true_count([diagnostics, breakdown, repair_plan])
    after = upstream_hashes()
    upstream_mutated = before != after
    pending_count = count_flag(diagnostics, "pending_forward_observation_blocker")
    if safety_count or upstream_mutated:
        status = BLOCKED_STATUS
        blocking = "SAFETY_OR_UPSTREAM_MUTATION_FAILURE"
    elif pending_count > 0:
        status = PARTIAL_STATUS
        blocking = ""
    else:
        status = PASS_STATUS
        blocking = ""
    gate = {
        "gate_check_id": "V20_153_R1_FACTOR_ABLATION_NEXT_GATE_001",
        "v20_153_gate_consumed": "TRUE",
        "v20_153_required_warn_status_confirmed": "TRUE",
        "v20_154_shadow_dynamic_weight_proposal_allowed": "FALSE",
        **SAFETY,
        "diagnostic_row_count": str(len(diagnostics)),
        "missing_outcome_blocked_row_count": str(count_flag(diagnostics, "missing_outcome_blocker")),
        "missing_benchmark_blocked_row_count": str(count_flag(diagnostics, "missing_benchmark_blocker")),
        "pending_forward_observation_blocked_row_count": str(pending_count),
        "insufficient_as_of_sample_blocked_row_count": str(count_flag(diagnostics, "insufficient_as_of_sample_blocker")),
        "insufficient_regime_coverage_blocked_row_count": str(count_flag(diagnostics, "insufficient_regime_coverage_blocker")),
        "insufficient_window_coverage_blocked_row_count": str(count_flag(diagnostics, "insufficient_window_coverage_blocker")),
        "insufficient_contribution_attribution_blocked_row_count": str(count_flag(diagnostics, "insufficient_contribution_attribution_blocker")),
        "pit_safety_issue_blocked_row_count": str(count_flag(diagnostics, "pit_safety_issue_blocker")),
        "evidence_quality_threshold_blocked_row_count": str(count_flag(diagnostics, "evidence_quality_threshold_blocker")),
        "conservative_threshold_only_blocked_row_count": str(count_flag(diagnostics, "conservative_threshold_only_blocker")),
        "repair_plan_row_count": str(len(repair_plan)),
        "no_outcomes_fabricated": "TRUE",
        "no_benchmarks_fabricated": "TRUE",
        "no_factor_contribution_fabricated": "TRUE",
        "no_eligibility_thresholds_lowered": "TRUE",
        "no_shadow_weights_created": "TRUE",
        "no_official_weight_mutation": "TRUE",
        "no_official_ranking_changes": "TRUE",
        "no_upstream_outputs_mutated": tf(not upstream_mutated),
        "blocking_reason": blocking,
        "final_status": status,
        "research_only": "TRUE",
        "staging_review_only": "TRUE",
        "diagnostic_only": "TRUE",
        "audit_only": "TRUE",
    }
    write_csv(OUT_DIAGNOSTIC, DIAGNOSTIC_FIELDS, diagnostics)
    write_csv(OUT_BREAKDOWN, BREAKDOWN_FIELDS, breakdown)
    write_csv(OUT_REPAIR, REPAIR_FIELDS, repair_plan)
    write_csv(OUT_NEXT_GATE, NEXT_GATE_FIELDS, [gate])
    write_report(status, len(diagnostics), len(repair_plan), pending_count)

    print(status)
    print("V20_153_GATE_CONSUMED=TRUE")
    print("V20_153_REQUIRED_WARN_STATUS_CONFIRMED=TRUE")
    print("V20_154_SHADOW_DYNAMIC_WEIGHT_PROPOSAL_ALLOWED=FALSE")
    print(f"DIAGNOSTIC_ROW_COUNT={len(diagnostics)}")
    print(f"MISSING_OUTCOME_BLOCKED_ROW_COUNT={gate['missing_outcome_blocked_row_count']}")
    print(f"MISSING_BENCHMARK_BLOCKED_ROW_COUNT={gate['missing_benchmark_blocked_row_count']}")
    print(f"PENDING_FORWARD_OBSERVATION_BLOCKED_ROW_COUNT={pending_count}")
    print(f"INSUFFICIENT_AS_OF_SAMPLE_BLOCKED_ROW_COUNT={gate['insufficient_as_of_sample_blocked_row_count']}")
    print(f"INSUFFICIENT_REGIME_COVERAGE_BLOCKED_ROW_COUNT={gate['insufficient_regime_coverage_blocked_row_count']}")
    print(f"INSUFFICIENT_WINDOW_COVERAGE_BLOCKED_ROW_COUNT={gate['insufficient_window_coverage_blocked_row_count']}")
    print(f"INSUFFICIENT_CONTRIBUTION_ATTRIBUTION_BLOCKED_ROW_COUNT={gate['insufficient_contribution_attribution_blocked_row_count']}")
    print(f"PIT_SAFETY_ISSUE_BLOCKED_ROW_COUNT={gate['pit_safety_issue_blocked_row_count']}")
    print(f"EVIDENCE_QUALITY_THRESHOLD_BLOCKED_ROW_COUNT={gate['evidence_quality_threshold_blocked_row_count']}")
    print(f"CONSERVATIVE_THRESHOLD_ONLY_BLOCKED_ROW_COUNT={gate['conservative_threshold_only_blocked_row_count']}")
    print("OUTCOMES_FABRICATED=0")
    print("BENCHMARKS_FABRICATED=0")
    print("FACTOR_CONTRIBUTION_FABRICATED=0")
    print("ELIGIBILITY_THRESHOLDS_LOWERED=FALSE")
    print("SHADOW_WEIGHTS_CREATED=FALSE")
    print("OFFICIAL_WEIGHT_MUTATION=FALSE")
    print("OFFICIAL_RANKING_CHANGES=FALSE")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    print(f"SAFETY_TRUE_COUNT={safety_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
