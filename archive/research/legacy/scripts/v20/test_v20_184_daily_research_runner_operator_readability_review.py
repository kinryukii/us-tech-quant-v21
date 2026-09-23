#!/usr/bin/env python
"""Tests for V20.184 daily research runner operator readability review."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_184_daily_research_runner_operator_readability_review.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_184_OPERATOR_READABILITY_AUDIT.csv",
    FACTORS / "V20_184_DATA_TRUST_MISLEADING_LANGUAGE_AUDIT.csv",
    FACTORS / "V20_184_OPERATOR_DISPLAY_RECOMMENDATION.csv",
    FACTORS / "V20_184_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_184_DAILY_RESEARCH_RUNNER_OPERATOR_READABILITY_REVIEW_REPORT.md",
]
PROTECTED = [
    FACTORS / "V20_183_DATA_TRUST_READ_CENTER_INTEGRATION_AUDIT.csv",
    FACTORS / "V20_183_DATA_TRUST_READ_CENTER_DISPLAY_SAMPLE.csv",
    FACTORS / "V20_183_OFFICIAL_USE_GUARD_AUDIT.csv",
    FACTORS / "V20_183_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_183_DAILY_RESEARCH_RUNNER_READ_CENTER_INTEGRATION_REPORT.md",
]
PASS_STATUS = "PASS_V20_184_DAILY_RESEARCH_RUNNER_OPERATOR_READABILITY_REVIEW_READY_FOR_V20_185_RELEASE_PACKET"
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


def test_daily_research_runner_operator_readability_review() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PASS_STATUS,
        "DISPLAY_CANDIDATE_COUNT=40",
        "READABILITY_PASS=TRUE",
        "MISLEADING_LANGUAGE_GUARD_PASS=TRUE",
        "OFFICIAL_USE_DISCLOSURE_PASS=TRUE",
        "CANDIDATE_LEVEL_STATUS_PRESENT=TRUE",
        "AGGREGATE_STATUS_PRESENT=TRUE",
        "OFFICIAL_RANKING_SCORE_PARTICIPATION_IMPLIED=FALSE",
        "RANK_ORDER_CHANGE_IMPLIED=FALSE",
        "REAL_BOOK_OR_OFFICIAL_RECOMMENDATION_PERMISSION_IMPLIED=FALSE",
        "READY_FOR_V20_185_DAILY_RUNNER_FINAL_GATE_ONLY_RELEASE_PACKET=TRUE",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "REAL_BOOK_USE_ALLOWED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "OFFICIAL_WEIGHT_MUTATION_ALLOWED=FALSE",
        "DATA_TRUST_ZERO_WEIGHT=TRUE",
        "DATA_TRUST_GATE_ONLY=TRUE",
        "DATA_TRUST_AUDIT_ONLY=TRUE",
        "DATA_TRUST_SHADOW_OBSERVATION_CONTINUED=TRUE",
        "OFFICIAL_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    readability = read_csv(OUTPUTS[0])
    misleading = read_csv(OUTPUTS[1])
    recommendation = read_csv(OUTPUTS[2])
    gate = read_csv(OUTPUTS[3])[0]

    assert all(row["readability_check_passed"] == "TRUE" for row in readability)
    assert all(row["misleading_language_detected"] == "FALSE" for row in misleading)
    assert all(row["guard_passed"] == "TRUE" for row in misleading)
    assert len(recommendation) == 1
    assert recommendation[0]["operator_display_recommendation"] == "KEEP_DATA_TRUST_READ_CENTER_STATUS_VISIBLE_AS_ZERO_WEIGHT_GATE_ONLY_AUDIT_METADATA"
    assert recommendation[0]["recommendation_status"] == "APPROVED_FOR_RELEASE_PACKET"
    assert recommendation[0]["ready_for_release_packet"] == "TRUE"
    assert gate["final_status"] == PASS_STATUS
    assert gate["readability_pass"] == "TRUE"
    assert gate["misleading_language_guard_pass"] == "TRUE"
    assert gate["official_use_disclosure_pass"] == "TRUE"
    assert gate["candidate_level_status_present"] == "TRUE"
    assert gate["aggregate_status_present"] == "TRUE"
    assert gate["official_ranking_score_participation_implied"] == "FALSE"
    assert gate["rank_order_change_implied"] == "FALSE"
    assert gate["real_book_or_official_recommendation_permission_implied"] == "FALSE"
    assert gate["ready_for_v20_185_daily_runner_final_gate_only_release_packet"] == "TRUE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert gate["real_book_use_allowed"] == "FALSE"
    assert gate["official_recommendation_created"] == "FALSE"
    assert gate["official_weight_mutation_allowed"] == "FALSE"
    assert_safety([gate, *readability[:3], *misleading, *recommendation])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "Operator readability review confirms DATA_TRUST" in report


if __name__ == "__main__":
    test_daily_research_runner_operator_readability_review()
    print("PASS test_v20_184_daily_research_runner_operator_readability_review")
