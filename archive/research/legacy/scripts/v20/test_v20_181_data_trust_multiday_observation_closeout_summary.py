#!/usr/bin/env python
"""Tests for V20.181 DATA_TRUST multiday observation closeout summary."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_181_data_trust_multiday_observation_closeout_summary.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_181_DATA_TRUST_MULTIDAY_OBSERVATION_3RUN_SUMMARY.csv",
    FACTORS / "V20_181_DATA_TRUST_AGGREGATE_GUARDRAIL_SUMMARY.csv",
    FACTORS / "V20_181_DATA_TRUST_RUN_TO_RUN_STABILITY_SUMMARY.csv",
    FACTORS / "V20_181_DATA_TRUST_CLOSEOUT_DECISION_EVIDENCE_PACKET.csv",
    FACTORS / "V20_181_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_181_DATA_TRUST_MULTIDAY_OBSERVATION_CLOSEOUT_SUMMARY_REPORT.md",
]
PROTECTED = [
    FACTORS / "V20_177_DATA_TRUST_MULTIDAY_OBSERVATION_PLAN.csv",
    FACTORS / "V20_177_DATA_TRUST_PER_RUN_GUARDRAIL_TEMPLATE.csv",
    FACTORS / "V20_177_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_178_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_1.csv",
    FACTORS / "V20_178_DATA_TRUST_RUN_1_CANDIDATE_DISCLOSURE_AUDIT.csv",
    FACTORS / "V20_178_DATA_TRUST_RUN_1_ZERO_WEIGHT_NO_MUTATION_AUDIT.csv",
    FACTORS / "V20_178_DATA_TRUST_RUN_1_OFFICIAL_USE_GUARD_AUDIT.csv",
    FACTORS / "V20_178_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_179_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_2.csv",
    FACTORS / "V20_179_DATA_TRUST_RUN_2_CANDIDATE_DISCLOSURE_AUDIT.csv",
    FACTORS / "V20_179_DATA_TRUST_RUN_2_ZERO_WEIGHT_NO_MUTATION_AUDIT.csv",
    FACTORS / "V20_179_DATA_TRUST_RUN_2_OFFICIAL_USE_GUARD_AUDIT.csv",
    FACTORS / "V20_179_DATA_TRUST_RUN_2_VS_RUN_1_COMPARISON_AUDIT.csv",
    FACTORS / "V20_179_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_180_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_3.csv",
    FACTORS / "V20_180_DATA_TRUST_RUN_3_CANDIDATE_DISCLOSURE_AUDIT.csv",
    FACTORS / "V20_180_DATA_TRUST_RUN_3_ZERO_WEIGHT_NO_MUTATION_AUDIT.csv",
    FACTORS / "V20_180_DATA_TRUST_RUN_3_OFFICIAL_USE_GUARD_AUDIT.csv",
    FACTORS / "V20_180_DATA_TRUST_RUN_3_VS_RUN_1_RUN_2_COMPARISON_AUDIT.csv",
    FACTORS / "V20_180_NEXT_STAGE_GATE.csv",
]
PASS_STATUS = "PASS_V20_181_DATA_TRUST_MULTIDAY_OBSERVATION_CLOSEOUT_SUMMARY_READY_FOR_V20_182_OPERATOR_DECISION"

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


def test_data_trust_multiday_observation_closeout_summary() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PASS_STATUS,
        "PLANNED_OBSERVATION_RUN_COUNT=3",
        "COMPLETED_OBSERVATION_RUN_COUNT=3",
        "MULTIDAY_OBSERVATION_COMPLETE=TRUE",
        "AGGREGATE_GUARDRAIL_PASS=TRUE",
        "RUN_TO_RUN_STABILITY_PASS=TRUE",
        "RUN_TO_RUN_DATA_TRUST_CAUSED_RANKING_MUTATION_COUNT=0",
        "ALL_DISCLOSURE_GUARDS_PASS=TRUE",
        "ALL_NO_MUTATION_GUARDS_PASS=TRUE",
        "ALL_ZERO_WEIGHT_GUARDS_PASS=TRUE",
        "ALL_OFFICIAL_USE_GUARDS_PASS=TRUE",
        "DATA_TRUST_ZERO_WEIGHT=TRUE",
        "DATA_TRUST_GATE_ONLY=TRUE",
        "DATA_TRUST_AUDIT_ONLY=TRUE",
        "DATA_TRUST_SHADOW_OBSERVATION_ONLY=TRUE",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "REAL_BOOK_USE_ALLOWED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "OFFICIAL_WEIGHT_MUTATION_ALLOWED=FALSE",
        "READY_FOR_V20_182_DATA_TRUST_GATE_ONLY_CLOSEOUT_OPERATOR_DECISION=TRUE",
        "OFFICIAL_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    summary = read_csv(OUTPUTS[0])
    guardrail = read_csv(OUTPUTS[1])
    stability = read_csv(OUTPUTS[2])
    evidence = read_csv(OUTPUTS[3])
    gate = read_csv(OUTPUTS[4])[0]

    assert len(summary) == 3
    assert [row["run_sequence"] for row in summary] == ["1", "2", "3"]
    assert all(row["candidate_count"] == "40" for row in summary)
    assert all(row["data_trust_disclosure_candidate_count"] == "40" for row in summary)
    assert all(row["disclosure_guard_pass"] == "TRUE" for row in summary)
    assert all(row["no_mutation_guard_pass"] == "TRUE" for row in summary)
    assert all(row["zero_weight_guard_pass"] == "TRUE" for row in summary)
    assert all(row["official_use_guard_pass"] == "TRUE" for row in summary)
    assert all(row["data_trust_score_contribution_sum"] == "0.0000000000" for row in summary)
    assert all(row["data_trust_nonzero_weight_count"] == "0" for row in summary)
    assert all(row["ready_for_official_use"] == "FALSE" for row in summary)
    assert all(row["real_book_use_allowed"] == "FALSE" for row in summary)
    assert all(row["official_recommendation_created"] == "FALSE" for row in summary)
    assert all(row["official_weight_mutation_allowed"] == "FALSE" for row in summary)
    assert all(row["aggregate_guardrail_pass"] == "TRUE" for row in guardrail)
    assert all(row["run_to_run_stability_pass"] == "TRUE" for row in stability)
    assert all(row["condition_pass"] == "TRUE" for row in evidence)
    assert gate["final_status"] == PASS_STATUS
    assert gate["multiday_observation_complete"] == "TRUE"
    assert gate["aggregate_guardrail_pass"] == "TRUE"
    assert gate["run_to_run_stability_pass"] == "TRUE"
    assert gate["run_to_run_data_trust_caused_ranking_mutation_count"] == "0"
    assert gate["ready_for_v20_182_data_trust_gate_only_closeout_operator_decision"] == "TRUE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert gate["real_book_use_allowed"] == "FALSE"
    assert gate["official_recommendation_created"] == "FALSE"
    assert gate["official_weight_mutation_allowed"] == "FALSE"
    assert_safety([gate, *summary, *guardrail[:3], *stability[:3], *evidence[:3]])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "3-run DATA_TRUST shadow observation sequence is closed out" in report


if __name__ == "__main__":
    test_data_trust_multiday_observation_closeout_summary()
    print("PASS test_v20_181_data_trust_multiday_observation_closeout_summary")
