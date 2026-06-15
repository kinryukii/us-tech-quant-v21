#!/usr/bin/env python
"""Tests for V20.177 DATA_TRUST multiday daily runner observation plan."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_177_data_trust_multiday_daily_runner_observation_plan.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_177_DATA_TRUST_MULTIDAY_OBSERVATION_PLAN.csv",
    FACTORS / "V20_177_DATA_TRUST_CLOSEOUT_ELIGIBILITY_AUDIT.csv",
    FACTORS / "V20_177_DATA_TRUST_PER_RUN_GUARDRAIL_TEMPLATE.csv",
    FACTORS / "V20_177_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_177_DATA_TRUST_MULTIDAY_DAILY_RUNNER_OBSERVATION_PLAN_REPORT.md",
]
PROTECTED = [
    CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv",
    FACTORS / "V20_176_NEXT_STAGE_GATE.csv",
]
PASS_STATUS = "PASS_V20_177_DATA_TRUST_MULTIDAY_OBSERVATION_PLAN_READY_FOR_V20_178_RUN_1"
RECOMMENDED_PATH = "CONTINUE_MULTIDAY_SHADOW_OBSERVATION"

SAFETY_FALSE_FIELDS = [
    "formal_activation_allowed", "promotion_ready", "official_recommendation_created",
    "official_ranking_mutated", "official_weight_change_created",
    "official_weight_registry_mutated", "weight_mutated", "real_book_action_created",
    "trade_action_created", "broker_execution_supported", "performance_claim_created",
    "shadow_weight_expansion_allowed",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_hashes() -> dict[Path, str]:
    return {path: digest(path) for path in PROTECTED if path.exists()}


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE"
        if "data_trust_scoring_weight" in row:
            assert row["data_trust_scoring_weight"] == "0.0000000000"
        if "data_trust_role" in row:
            assert row["data_trust_role"] == "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"


def test_data_trust_multiday_daily_runner_observation_plan() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PASS_STATUS,
        "BASELINE_CANDIDATE_COUNT=40",
        f"RECOMMENDED_PATH={RECOMMENDED_PATH}",
        "OBSERVATION_RUN_REQUIRED_COUNT=3",
        "READY_FOR_V20_178_MULTIDAY_OBSERVATION_RUN_1=TRUE",
        "READY_FOR_IMMEDIATE_CLOSEOUT=FALSE",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "REAL_BOOK_USE_ALLOWED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "OFFICIAL_WEIGHT_MUTATION_ALLOWED=FALSE",
        "DATA_TRUST_ZERO_WEIGHT=TRUE",
        "DATA_TRUST_GATE_ONLY=TRUE",
        "DATA_TRUST_AUDIT_ONLY=TRUE",
        "OFFICIAL_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    plan = read_csv(OUTPUTS[0])
    closeout = read_csv(OUTPUTS[1])
    template = read_csv(OUTPUTS[2])
    gate = read_csv(OUTPUTS[3])[0]
    assert len(plan) == 3
    assert len(closeout) == 2
    assert len(template) == 9
    assert all(row["recommended_path"] == RECOMMENDED_PATH for row in plan)
    assert all(row["data_trust_zero_weight"] == "TRUE" for row in plan)
    assert all(row["required_each_run"] == "TRUE" for row in template)
    assert any(row["closeout_option"] == "CONTINUE_MULTIDAY_SHADOW_OBSERVATION" and row["recommended_now"] == "TRUE" for row in closeout)
    assert gate["final_status"] == PASS_STATUS
    assert gate["ready_for_v20_178_multiday_observation_run_1"] == "TRUE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert_safety([gate, *plan, *closeout, *template[:3]])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "conservative multiday shadow observation" in report


if __name__ == "__main__":
    test_data_trust_multiday_daily_runner_observation_plan()
    print("PASS test_v20_177_data_trust_multiday_daily_runner_observation_plan")
