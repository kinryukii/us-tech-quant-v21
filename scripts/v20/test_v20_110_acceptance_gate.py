#!/usr/bin/env python
"""Tests for V20.110 acceptance gate."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_110_acceptance_gate.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_DECISION = CONSOLIDATION / "V20_110_ACCEPTANCE_GATE_DECISION.csv"
OUT_SELECTED_AUDIT = CONSOLIDATION / "V20_110_SELECTED_REPAIR_SCENARIO_ACCEPTANCE_AUDIT.csv"
OUT_PRIOR_FAILURE_AUDIT = CONSOLIDATION / "V20_110_PRIOR_FAILURE_REPAIR_ACCEPTANCE_AUDIT.csv"
OUT_BASELINE_AUDIT = CONSOLIDATION / "V20_110_BASELINE_QUALITY_ACCEPTANCE_AUDIT.csv"
OUT_SAFETY_AUDIT = CONSOLIDATION / "V20_110_SAFETY_BOUNDARY_AUDIT.csv"
OUT_MANIFEST = CONSOLIDATION / "V20_110_ACCEPTANCE_CANDIDATE_MANIFEST.csv"
OUT_GATE = CONSOLIDATION / "V20_110_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_110_ACCEPTANCE_GATE_REPORT.md"

OUTPUTS = [
    OUT_DECISION,
    OUT_SELECTED_AUDIT,
    OUT_PRIOR_FAILURE_AUDIT,
    OUT_BASELINE_AUDIT,
    OUT_SAFETY_AUDIT,
    OUT_MANIFEST,
    OUT_GATE,
    OUT_REPORT,
]

SAFETY_FALSE_FIELDS = [
    "accepted_weight_created",
    "official_weight_created",
    "official_weights_created",
    "new_weights_created",
    "new_official_rerank_created",
    "official_ranking_created",
    "official_recommendation_created",
    "trade_action_created",
    "broker_action_created",
    "broker_execution_supported",
    "performance_claim_created",
    "performance_effectiveness_claim_created",
    "authoritative_overwrite_created",
    "authoritative_ranking_overwritten",
    "official_promotion_allowed",
    "is_official_weight",
    "weight_mutated",
    "accepted_weights_created",
    "official_rankings_created",
    "official_recommendations_created",
    "trade_actions_created",
    "broker_actions_created",
    "authoritative_overwrites_created",
    "weight_mutations_created",
    "performance_claims_created",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    bad = [row for row in rows if row.get(field) not in {"", "FALSE"}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def test_acceptance_gate() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_110_ACCEPTANCE_GATE_READY_FOR_V20_111",
        "WARN_V20_110_ACCEPTANCE_GATE_READY_WITH_GUARD",
        "BLOCKED_V20_110_MISSING_REQUIRED_R11_INPUTS",
        "BLOCKED_V20_110_R11_DID_NOT_ALLOW_ACCEPTANCE_GATE",
        "BLOCKED_V20_110_SELECTED_SCENARIO_NOT_ROBUST",
        "BLOCKED_V20_110_SAFETY_BOUNDARY_VIOLATION",
        "BLOCKED_V20_110_ACCEPTANCE_GATE_REQUIREMENTS_NOT_MET",
    ])
    for expected in [
        "R11_NEXT_STAGE_GATE_CONSUMED=TRUE",
        "R11_V20_110_ACCEPTANCE_GATE_ALLOWED=TRUE",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_PASSED_ROBUSTNESS_VALIDATION=TRUE",
        "REPAIR_120D_TOP20_PERSISTENCE_ACCEPTED=TRUE",
        "BASELINE_QUALITY_ROBUSTNESS_ACCEPTED=TRUE",
        "TOP20_STABILITY_ROBUSTNESS_ACCEPTED=TRUE",
        "TOP40_STABILITY_ROBUSTNESS_ACCEPTED=TRUE",
        "COMPONENT_DEVIATION_ROBUSTNESS_ACCEPTED=TRUE",
        "SCENARIO_FRAGILITY_AUDIT_CONSUMED=TRUE",
        "SCENARIO_FRAGILE=FALSE",
        "DUPLICATE_RANK_COUNT=0",
        "MISSING_RANK_COUNT=0",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "ACCEPTED_WEIGHT_CREATED=FALSE",
        "OFFICIAL_WEIGHT_CREATED=FALSE",
        "OFFICIAL_WEIGHTS_CREATED=FALSE",
        "NEW_WEIGHTS_CREATED=FALSE",
        "NEW_OFFICIAL_RERANK_CREATED=FALSE",
        "OFFICIAL_RANKING_CREATED=FALSE",
        "AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE",
        "AUTHORITATIVE_OVERWRITE_CREATED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "PERFORMANCE_CLAIM_CREATED=FALSE",
        "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED=FALSE",
        "WEIGHT_MUTATED=FALSE",
    ]:
        assert expected in stdout, expected

    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    decision = read_csv(OUT_DECISION)
    selected = read_csv(OUT_SELECTED_AUDIT)
    prior = read_csv(OUT_PRIOR_FAILURE_AUDIT)
    baseline = read_csv(OUT_BASELINE_AUDIT)
    safety = read_csv(OUT_SAFETY_AUDIT)
    manifest = read_csv(OUT_MANIFEST)
    gate = read_csv(OUT_GATE)

    d = decision[0]
    assert d["r11_next_stage_gate_consumed"] == "TRUE"
    assert d["r11_v20_110_acceptance_gate_allowed"] == "TRUE"
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["selected_scenario_exists"] == "TRUE"
    assert d["selected_scenario_passed_robustness_validation"] == "TRUE"
    assert int(d["robust_repair_scenario_count"]) >= 1
    assert d["robust_repair_scenario_count_requirement_met"] == "TRUE"
    assert d["repair_120d_top20_persistence_accepted"] == "TRUE"
    assert d["baseline_quality_robustness_accepted"] == "TRUE"
    assert d["top20_stability_robustness_accepted"] == "TRUE"
    assert d["top40_stability_robustness_accepted"] == "TRUE"
    assert d["component_deviation_robustness_accepted"] == "TRUE"
    assert d["scenario_fragility_audit_consumed"] == "TRUE"
    assert d["scenario_fragile"] == "FALSE"
    assert d["duplicate_rank_count"] == "0"
    assert d["missing_rank_count"] == "0"
    assert d["safety_boundary_audit_passed"] == "TRUE"
    assert d["acceptance_candidate_manifest_created"] == "TRUE"
    assert d["v20_111_shadow_acceptance_review_allowed"] == "TRUE"

    assert selected[0]["selected_scenario_matches_expected"] == "TRUE"
    assert selected[0]["selected_scenario_passed_robustness_validation"] == "TRUE"
    assert prior[0]["repair_120d_top20_persistence_accepted"] == "TRUE"
    assert baseline[0]["baseline_quality_robustness_accepted"] == "TRUE"
    assert safety[0]["safety_boundary_audit_passed"] == "TRUE"
    assert safety[0]["no_official_action_or_weight_mutation_created"] == "TRUE"
    assert manifest[0]["candidate_manifest_type"] == "SHADOW_ACCEPTANCE_REVIEW_CANDIDATE_ONLY"
    assert manifest[0]["acceptance_candidate_created"] == "TRUE"
    assert gate[0]["v20_111_shadow_acceptance_review_allowed"] == "TRUE"
    assert gate[0]["r11_v20_110_acceptance_gate_allowed"] == "TRUE"

    strict_conditions = [
        d["r11_v20_110_acceptance_gate_allowed"] == "TRUE",
        d["selected_scenario_exists"] == "TRUE",
        d["selected_scenario_passed_robustness_validation"] == "TRUE",
        d["repair_120d_top20_persistence_accepted"] == "TRUE",
        d["baseline_quality_robustness_accepted"] == "TRUE",
        d["top20_stability_robustness_accepted"] == "TRUE",
        d["top40_stability_robustness_accepted"] == "TRUE",
        d["component_deviation_robustness_accepted"] == "TRUE",
        d["scenario_fragile"] == "FALSE",
        d["duplicate_rank_count"] == "0",
        d["missing_rank_count"] == "0",
        d["safety_boundary_audit_passed"] == "TRUE",
    ]
    assert (d["v20_111_shadow_acceptance_review_allowed"] == "TRUE") == all(strict_conditions)

    for rows in [decision, selected, prior, baseline, safety, manifest, gate]:
        for field in SAFETY_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_acceptance_gate()
    print("PASS_V20_110_ACCEPTANCE_GATE_TESTS")
