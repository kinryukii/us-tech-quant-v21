#!/usr/bin/env python
"""Tests for V20.109-R7 additional conservative simulation repair."""

from __future__ import annotations

import csv
import subprocess
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_109_r7_additional_simulation_or_conservative_weight_repair.py"
OUT_SCENARIOS = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R7_ADDITIONAL_SIMULATION_SCENARIOS.csv"
OUT_RATIONALE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R7_CONSERVATIVE_REPAIR_RATIONALE_AUDIT.csv"
OUT_TARGET = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R7_PRIOR_FAILURE_AREA_TARGETING_AUDIT.csv"
OUT_CHANGE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R7_SECOND_ROUND_WEIGHT_CHANGE_AUDIT.csv"
OUT_VALIDATION = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R7_SIMULATION_SCENARIO_VALIDATION.csv"
OUT_GATE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R7_NEXT_STAGE_GATE.csv"
OUT_REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_109_R7_ADDITIONAL_SIMULATION_OR_CONSERVATIVE_WEIGHT_REPAIR_REPORT.md"

WEIGHTS = ["fundamental_weight","technical_weight","strategy_weight","risk_weight","market_regime_weight","data_trust_weight"]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    assert rows
    bad = [row for row in rows if row.get(field) not in {"FALSE", ""}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def test_additional_simulation_or_conservative_weight_repair() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_109_R7_ADDITIONAL_SIMULATION_OR_CONSERVATIVE_WEIGHT_REPAIR",
        "PARTIAL_PASS_V20_109_R7_ADDITIONAL_SIMULATION_WITH_LIMITED_EVIDENCE",
        "BLOCKED_V20_109_R7_MISSING_R6_STRESS_TEST_INPUTS",
    ])
    for expected in [
        "PARENT_SCENARIO_ID=SIM_004",
        "PRIOR_FAILURE_AREA=120D_TOP20",
        "TARGETED_FORWARD_WINDOW=120D",
        "TARGETED_TOPN_GROUP=20",
        "SCENARIO_COUNT=8",
        "VALID_SCENARIO_COUNT=8",
        "PRIOR_FAILURE_AREA_TARGETED_COUNT=8",
        "CURRENT_DYNAMIC_WEIGHT_SUM=1.0000000000",
        "CURRENT_DYNAMIC_WEIGHT_SUM_VALID=TRUE",
        "NEW_WEIGHTS_CREATED=FALSE",
        "NEW_RERANK_CREATED=FALSE",
        "ACCEPTED_WEIGHT_CREATED=FALSE",
        "OFFICIAL_WEIGHT_CREATED=FALSE",
        "ACTIVE_WEIGHT_MUTATED=FALSE",
        "V20_107_WEIGHT_MUTATED=FALSE",
        "V20_98B_R5_WEIGHT_MUTATED=FALSE",
        "OFFICIAL_RANKING_CREATED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED=FALSE",
        "V20_110_ACCEPTANCE_GATE_ALLOWED=FALSE",
        "V20_109_R8_SECOND_ROUND_SIMULATED_RERANK_ALLOWED=TRUE",
        "OFFICIAL_PROMOTION_ALLOWED=FALSE",
        "IS_OFFICIAL_WEIGHT=FALSE",
    ]:
        assert expected in stdout

    for path in [OUT_SCENARIOS, OUT_RATIONALE, OUT_TARGET, OUT_CHANGE, OUT_VALIDATION, OUT_GATE, OUT_REPORT]:
        assert path.exists(), f"missing output {path}"

    scenarios = read_csv(OUT_SCENARIOS)
    rationale = read_csv(OUT_RATIONALE)
    target = read_csv(OUT_TARGET)
    change = read_csv(OUT_CHANGE)
    validation = read_csv(OUT_VALIDATION)
    gate = read_csv(OUT_GATE)

    assert len(scenarios) == 8
    assert len(rationale) == 8
    assert len(target) == 8
    assert len(change) == 8 * 6
    assert all(row["parent_scenario_id"] == "SIM_004" for row in scenarios)
    assert all(row["targets_prior_failure_area"] == "TRUE" for row in scenarios)
    assert all(row["targeted_forward_window"] == "120D" for row in scenarios)
    assert all(row["targeted_topn_group"] == "20" for row in scenarios)
    assert all(row["prior_failure_area"] == "120D_TOP20" for row in target)

    for row in scenarios:
        assert all(row[field] != "" for field in WEIGHTS)
        total = sum(Decimal(row[field]) for field in WEIGHTS)
        assert total == Decimal("1.0000000000")
        assert row["weight_sum"] == "1.0000000000"
        assert row["weight_sum_valid"] == "TRUE"
        assert Decimal(row["max_family_weight"]) <= Decimal("0.3500000000")
        assert row["max_family_weight_cap_valid"] == "TRUE"
        assert row["risk_weight_positive"] == "TRUE"
        assert row["market_regime_weight_positive"] == "TRUE"
        assert row["data_trust_weight_positive"] == "TRUE"
        assert row["simulation_only"] == "TRUE"
        assert row["official_weight_created"] == "FALSE"
        assert row["accepted_weight_created"] == "FALSE"
        assert row["active_weight_mutated"] == "FALSE"
        assert row["v20_107_weight_mutated"] == "FALSE"
        assert row["v20_98b_r5_weight_mutated"] == "FALSE"

    v = validation[0]
    assert v["scenario_count"] == "8"
    assert v["valid_scenario_count"] == "8"
    assert v["invalid_scenario_count"] == "0"
    assert v["current_dynamic_weight_sum"] == "1.0000000000"
    assert v["current_dynamic_weight_sum_valid"] == "TRUE"
    assert v["all_simulated_weight_sums_valid"] == "TRUE"
    assert v["all_required_families_present"] == "TRUE"
    assert v["all_family_caps_valid"] == "TRUE"
    assert v["all_required_positive_weights_valid"] == "TRUE"
    assert v["prior_failure_area_targeted_count"] == "8"
    assert v["new_rerank_created"] == "FALSE"

    assert gate[0]["additional_simulation_scenarios_created"] == "TRUE"
    assert gate[0]["v20_109_r8_second_round_simulated_rerank_allowed"] == "TRUE"
    assert gate[0]["v20_110_acceptance_gate_allowed"] == "FALSE"

    for rows in [scenarios, rationale, target, change, validation, gate]:
        for field in [
            "official_weight_created",
            "accepted_weight_created",
            "new_weights_created",
            "new_rerank_created",
            "active_weight_mutated",
            "v20_107_weight_mutated",
            "v20_98b_r5_weight_mutated",
            "official_ranking_created",
            "official_recommendation_created",
            "trade_action_created",
            "broker_execution_supported",
            "performance_effectiveness_claim_created",
            "official_promotion_allowed",
            "is_official_weight",
            "weight_mutated",
        ]:
            if field in rows[0]:
                assert_false(rows, field)
        if "diagnostic_only" in rows[0]:
            assert all(row["diagnostic_only"] == "TRUE" for row in rows)


if __name__ == "__main__":
    test_additional_simulation_or_conservative_weight_repair()
    print("PASS_V20_109_R7_ADDITIONAL_SIMULATION_OR_CONSERVATIVE_WEIGHT_REPAIR_TESTS")
