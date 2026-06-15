#!/usr/bin/env python
"""Tests for V20.109-R2 shadow weight repair simulation."""

from __future__ import annotations

import csv
import subprocess
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_109_r2_research_only_shadow_weight_repair_simulation.py"
OUT_SCENARIOS = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R2_SHADOW_WEIGHT_REPAIR_SIMULATION_SCENARIOS.csv"
OUT_CHANGE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R2_SIMULATED_WEIGHT_CHANGE_AUDIT.csv"
OUT_RATIONALE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R2_REPAIR_SCENARIO_RATIONALE_AUDIT.csv"
OUT_VALIDATION = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R2_WEIGHT_SIMULATION_VALIDATION.csv"
OUT_GATE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R2_NEXT_STAGE_GATE.csv"
OUT_REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_109_R2_RESEARCH_ONLY_SHADOW_WEIGHT_REPAIR_SIMULATION_REPORT.md"
WEIGHT_FIELDS = ["fundamental_weight","technical_weight","strategy_weight","risk_weight","market_regime_weight","data_trust_weight"]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    assert rows
    bad = [row for row in rows if row.get(field) not in {"FALSE", ""}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def test_weight_repair_simulation() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert any(s in stdout for s in [
        "PASS_V20_109_R2_RESEARCH_ONLY_SHADOW_WEIGHT_REPAIR_SIMULATION",
        "PARTIAL_PASS_V20_109_R2_WEIGHT_REPAIR_SIMULATION_WITH_LIMITED_EVIDENCE",
        "BLOCKED_V20_109_R2_MISSING_REPAIR_PLAN_INPUTS",
    ])
    for expected in [
        "CURRENT_DYNAMIC_WEIGHT_SUM=1.0000000000",
        "CURRENT_DYNAMIC_WEIGHT_SUM_VALID=TRUE",
        "ALL_SIMULATED_WEIGHT_SUMS_VALID=TRUE",
        "NEW_WEIGHTS_CREATED=FALSE",
        "NEW_RERANK_CREATED=FALSE",
        "V20_110_ACCEPTANCE_GATE_ALLOWED=FALSE",
        "V20_109_R3_SIMULATED_RERANK_ALLOWED=TRUE",
        "OFFICIAL_WEIGHT_CREATED=FALSE",
        "ACTIVE_WEIGHT_MUTATED=FALSE",
        "V20_107_WEIGHT_MUTATED=FALSE",
        "V20_98B_R5_WEIGHT_MUTATED=FALSE",
        "OFFICIAL_RANKING_CREATED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED=FALSE",
        "OFFICIAL_PROMOTION_ALLOWED=FALSE",
        "IS_OFFICIAL_WEIGHT=FALSE",
    ]:
        assert expected in stdout

    for path in [OUT_SCENARIOS, OUT_CHANGE, OUT_RATIONALE, OUT_VALIDATION, OUT_GATE, OUT_REPORT]:
        assert path.exists(), f"missing output {path}"

    scenarios = read_csv(OUT_SCENARIOS)
    changes = read_csv(OUT_CHANGE)
    rationale = read_csv(OUT_RATIONALE)
    validation = read_csv(OUT_VALIDATION)
    gate = read_csv(OUT_GATE)
    assert len(scenarios) >= 1
    assert len(changes) == len(scenarios) * 6
    assert len(rationale) == len(scenarios)
    expected_types = {
        "BASELINE_CURRENT_DYNAMIC_WEIGHTS_REFERENCE",
        "LOWER_RISK_WEIGHT_SCENARIO",
        "HIGHER_STRATEGY_WEIGHT_SCENARIO",
        "HIGHER_FUNDAMENTAL_WEIGHT_SCENARIO",
        "LOWER_MARKET_REGIME_WEIGHT_SCENARIO",
        "CONSERVATIVE_TOPN_STABILITY_SCENARIO",
        "LONG_WINDOW_REPAIR_SCENARIO",
        "BALANCED_REPAIR_SCENARIO",
    }
    assert expected_types <= {row["scenario_type"] for row in scenarios}
    for row in scenarios:
        total = sum(Decimal(row[field]) for field in WEIGHT_FIELDS)
        assert total == Decimal("1.0000000000")
        assert row["weight_sum"] == "1.0000000000"
        assert row["weight_sum_valid"] == "TRUE"
        assert Decimal(row["max_family_weight"]) <= Decimal(row["max_family_weight_cap"])
        assert row["max_family_weight_cap_valid"] == "TRUE"
        assert Decimal(row["risk_weight"]) > 0
        assert Decimal(row["market_regime_weight"]) > 0
        assert Decimal(row["data_trust_weight"]) > 0
        assert row["simulation_only"] == "TRUE"
        for field in ["official_weight_created","active_weight_mutated","v20_107_weight_mutated","v20_98b_r5_weight_mutated","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]:
            assert row[field] == "FALSE"

    assert validation[0]["valid_scenario_count"] == str(len(scenarios))
    assert validation[0]["new_weights_created"] == "FALSE"
    assert validation[0]["new_rerank_created"] == "FALSE"
    assert validation[0]["official_weight_created"] == "FALSE"
    assert validation[0]["performance_effectiveness_claim_created"] == "FALSE"
    assert gate[0]["v20_110_acceptance_gate_allowed"] == "FALSE"
    assert gate[0]["v20_109_r3_simulated_rerank_allowed"] == "TRUE"
    assert gate[0]["new_weights_created"] == "FALSE"
    assert gate[0]["new_rerank_created"] == "FALSE"

    for rows in [scenarios, changes, rationale, validation, gate]:
        for field in ["official_recommendation_created","trade_action_created","broker_execution_supported","official_promotion_allowed"]:
            if field in rows[0]:
                assert_false(rows, field)
        for field in ["official_weight_created","active_weight_mutated","v20_107_weight_mutated","v20_98b_r5_weight_mutated","new_weights_created","new_rerank_created","performance_effectiveness_claim_created","weight_mutated"]:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_weight_repair_simulation()
    print("PASS_V20_109_R2_WEIGHT_REPAIR_SIMULATION_TESTS")
