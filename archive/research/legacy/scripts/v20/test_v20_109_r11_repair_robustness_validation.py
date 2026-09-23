#!/usr/bin/env python
"""Tests for V20.109-R11 repair robustness validation."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_109_r11_repair_robustness_validation.py"
OUT_VALIDATION = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv"
OUT_PERSISTENCE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R11_120D_TOP20_REPAIR_PERSISTENCE_AUDIT.csv"
OUT_QUALITY = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R11_BASELINE_QUALITY_ROBUSTNESS_AUDIT.csv"
OUT_STABILITY = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R11_TOP20_TOP40_STABILITY_ROBUSTNESS_AUDIT.csv"
OUT_COMPONENT = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R11_COMPONENT_DEVIATION_ROBUSTNESS_AUDIT.csv"
OUT_FRAGILITY = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R11_SCENARIO_FRAGILITY_AUDIT.csv"
OUT_SELECTION = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R11_SCENARIO_FINAL_SELECTION_CANDIDATE.csv"
OUT_GATE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R11_NEXT_STAGE_GATE.csv"
OUT_REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION_REPORT.md"

OUTPUTS = [
    OUT_VALIDATION,
    OUT_PERSISTENCE,
    OUT_QUALITY,
    OUT_STABILITY,
    OUT_COMPONENT,
    OUT_FRAGILITY,
    OUT_SELECTION,
    OUT_GATE,
    OUT_REPORT,
]

SAFETY_FIELDS = [
    "accepted_weight_created",
    "official_weight_created",
    "new_weights_created",
    "new_official_rerank_created",
    "official_ranking_created",
    "official_recommendation_created",
    "trade_action_created",
    "broker_execution_supported",
    "performance_effectiveness_claim_created",
    "authoritative_ranking_overwritten",
    "official_promotion_allowed",
    "is_official_weight",
    "weight_mutated",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    assert rows
    bad = [row for row in rows if row.get(field) not in {"FALSE", ""}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def test_repair_robustness_validation() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION_READY_FOR_V20_110",
        "PARTIAL_PASS_V20_109_R11_ROBUSTNESS_VALIDATION_WITH_LIMITED_EVIDENCE",
        "BLOCKED_V20_109_R11_MISSING_REQUIRED_R10_R2_INPUTS",
        "BLOCKED_V20_109_R11_NO_ROBUST_REPAIR_SCENARIO",
        "WARN_V20_109_R11_REPAIR_EFFECTIVE_BUT_FRAGILE",
        "WARN_V20_109_R11_REPAIR_ROBUST_BUT_ACCEPTANCE_NEEDS_GUARD",
    ])
    for expected in [
        "R10_R2_GATE_CONSUMED=TRUE",
        "EVALUATED_VALIDATED_REPAIR_SCENARIO_COUNT=7",
        "EXCLUDED_UNVALIDATED_REPAIR_SCENARIO_COUNT=1",
        "DUPLICATE_RANK_COUNT=0",
        "MISSING_RANK_COUNT=0",
        "ACCEPTED_WEIGHT_CREATED=FALSE",
        "OFFICIAL_WEIGHT_CREATED=FALSE",
        "NEW_WEIGHTS_CREATED=FALSE",
        "NEW_OFFICIAL_RERANK_CREATED=FALSE",
        "OFFICIAL_RANKING_CREATED=FALSE",
        "AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED=FALSE",
        "OFFICIAL_PROMOTION_ALLOWED=FALSE",
        "IS_OFFICIAL_WEIGHT=FALSE",
        "WEIGHT_MUTATED=FALSE",
    ]:
        assert expected in stdout

    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    validation = read_csv(OUT_VALIDATION)
    persistence = read_csv(OUT_PERSISTENCE)
    quality = read_csv(OUT_QUALITY)
    stability = read_csv(OUT_STABILITY)
    component = read_csv(OUT_COMPONENT)
    fragility = read_csv(OUT_FRAGILITY)
    selection = read_csv(OUT_SELECTION)
    gate = read_csv(OUT_GATE)

    v = validation[0]
    assert v["r10_r2_gate_consumed"] == "TRUE"
    assert v["r10_r2_r11_allowed"] == "TRUE"
    assert v["input_repair_scenario_count"] == "8"
    assert v["evaluated_validated_repair_scenario_count"] == "7"
    assert v["excluded_unvalidated_repair_scenario_count"] == "1"
    assert v["duplicate_rank_count"] == "0"
    assert v["missing_rank_count"] == "0"

    evaluated_ids = {row["repair_scenario_id"] for row in persistence}
    assert len(evaluated_ids) == 7
    assert "R10_R2_REPAIR_008_REPAIR_ABORT_THRESHOLD_DIAGNOSTIC" not in evaluated_ids
    assert len(quality) == 7
    assert {row["baseline_quality_robustly_preserved"] for row in quality}.issubset({"TRUE", "FALSE"})
    assert len(stability) == 14
    assert {int(row["top_n"]) for row in stability} == {20, 40}
    assert len(component) == 42
    assert {row["factor_family"] for row in component} == {
        "fundamental",
        "technical",
        "strategy",
        "risk",
        "market_regime",
        "data_trust",
    }
    assert len(fragility) == 7
    assert {row["scenario_fragile"] for row in fragility}.issubset({"TRUE", "FALSE"})

    if gate[0]["v20_110_acceptance_gate_allowed"] == "TRUE":
        assert int(gate[0]["robust_repair_scenario_count"]) >= 1
        assert selection[0]["selected_for_v20_110_review"] == "TRUE"
        assert selection[0]["selected_repair_scenario_id"]
    else:
        assert selection[0]["selected_for_v20_110_review"] == "FALSE"
        assert gate[0]["next_recommended_action"] in {
            "V20.109-R12_ROBUSTNESS_FAILURE_REPAIR",
            "V20.109-R12_SCENARIO_SELECTION_GUARD",
        }

    for rows in [validation, persistence, quality, stability, component, fragility, selection, gate]:
        for field in SAFETY_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_repair_robustness_validation()
    print("PASS_V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION_TESTS")
