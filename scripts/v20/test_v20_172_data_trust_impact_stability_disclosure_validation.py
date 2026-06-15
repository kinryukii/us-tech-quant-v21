#!/usr/bin/env python
"""Tests for V20.172 DATA_TRUST impact/stability/disclosure validation."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_172_data_trust_impact_stability_disclosure_validation.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_172_DATA_TRUST_IMPACT_AUDIT.csv",
    FACTORS / "V20_172_DATA_TRUST_STABILITY_AUDIT.csv",
    FACTORS / "V20_172_DATA_TRUST_DISCLOSURE_AUDIT.csv",
    FACTORS / "V20_172_DATA_TRUST_DOWNSTREAM_CONSUMPTION_AUDIT.csv",
    FACTORS / "V20_172_OFFICIAL_USE_GUARD_AUDIT.csv",
    FACTORS / "V20_172_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_172_DATA_TRUST_IMPACT_STABILITY_DISCLOSURE_VALIDATION_REPORT.md",
]
PROTECTED = [
    CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv",
    FACTORS / "V20_171_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION.csv",
    FACTORS / "V20_171_NEXT_STAGE_GATE.csv",
]
PASS_STATUS = "PASS_V20_172_DATA_TRUST_IMPACT_STABILITY_DISCLOSURE_VALIDATION_READY_FOR_V20_173"

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


def test_data_trust_impact_stability_disclosure_validation() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PASS_STATUS,
        "BASELINE_CANDIDATE_COUNT=40",
        "SIMULATION_CANDIDATE_COUNT=40",
        "OFFICIAL_RANKING_SCORE_MUTATION_COUNT=0",
        "OFFICIAL_RANK_MUTATION_COUNT=0",
        "DATA_TRUST_SCORE_CONTRIBUTION_SUM=0.0000000000",
        "DATA_TRUST_NONZERO_WEIGHT_COUNT=0",
        "COMPLETE_DISCLOSURE_CANDIDATE_COUNT=40",
        "CANDIDATE_REMOVED_OR_REORDERED_COUNT=0",
        "DOWNSTREAM_AUDIT_METADATA_CONSUMPTION_PASS=TRUE",
        "IMPACT_GUARD_PASS=TRUE",
        "RANK_STABILITY_GUARD_PASS=TRUE",
        "ZERO_WEIGHT_GUARD_PASS=TRUE",
        "DISCLOSURE_GUARD_PASS=TRUE",
        "OFFICIAL_USE_GUARD_PASS=TRUE",
        "READY_FOR_V20_173_OPERATOR_DECISION_PACKET=TRUE",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "REAL_BOOK_USE_ALLOWED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "OFFICIAL_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    impact = read_csv(OUTPUTS[0])
    stability = read_csv(OUTPUTS[1])
    disclosure = read_csv(OUTPUTS[2])
    downstream = read_csv(OUTPUTS[3])
    official = read_csv(OUTPUTS[4])
    gate = read_csv(OUTPUTS[5])[0]
    assert len(impact) == 3
    assert len(stability) == 40
    assert len(disclosure) == 40
    assert len(downstream) == 1
    assert len(official) == 5
    assert all(row["impact_guard_pass"] == "TRUE" for row in impact)
    assert all(row["rank_stability_guard_pass"] == "TRUE" for row in stability)
    assert all(row["score_stability_guard_pass"] == "TRUE" for row in stability)
    assert all(row["disclosure_guard_pass"] == "TRUE" for row in disclosure)
    assert all(row["downstream_consumption_guard_pass"] == "TRUE" for row in downstream)
    assert all(row["official_use_guard_pass"] == "TRUE" for row in official)
    assert gate["final_status"] == PASS_STATUS
    assert gate["ready_for_v20_173_operator_decision_packet"] == "TRUE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert_safety([gate, *impact, *stability[:3], *disclosure[:3]])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "audit/gate-only" in report


if __name__ == "__main__":
    test_data_trust_impact_stability_disclosure_validation()
    print("PASS test_v20_172_data_trust_impact_stability_disclosure_validation")
