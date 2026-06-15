#!/usr/bin/env python
"""Tests for V20.118 promotion blocker recheck."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_118_promotion_blocker_recheck.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_DECISION = CONSOLIDATION / "V20_118_PROMOTION_BLOCKER_RECHECK_DECISION.csv"
OUT_STATUS = CONSOLIDATION / "V20_118_BLOCKER_STATUS_RECHECK_AUDIT.csv"
OUT_EVIDENCE = CONSOLIDATION / "V20_118_BLOCKER_RESOLUTION_EVIDENCE_AUDIT.csv"
OUT_REMAINING = CONSOLIDATION / "V20_118_REMAINING_BLOCKER_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_118_PROMOTION_BOUNDARY_SAFETY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_118_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_118_PROMOTION_BLOCKER_RECHECK_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_STATUS, OUT_EVIDENCE, OUT_REMAINING, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = [CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117"]]
UPSTREAM.append(CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv")

REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_117_gate_consumed", "selected_repair_scenario_id", "remaining_blocker_count", "promotion_ready", "operator_review_package_allowed", "promotion_blocker_recheck_status"},
    OUT_STATUS: {"blocker_category", "blocker_resolved", "blocker_status", "promotion_ready"},
    OUT_EVIDENCE: {"blocker_category", "valid_resolution_evidence", "evidence_status"},
    OUT_REMAINING: {"blocker_category", "operator_review_required", "promotion_ready"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_117_gate_consumed", "selected_repair_scenario_id", "promotion_ready", "v20_119_operator_review_package_allowed", "promotion_blocker_recheck_status"},
}
PROHIBITED_FALSE_FIELDS = [
    "accepted_weight_created", "accepted_weights_created", "real_book_weight_created", "real_book_action_created",
    "official_weight_created", "official_weights_created", "official_ranking_created", "official_rankings_created",
    "official_recommendation_created", "official_recommendations_created", "trade_action_created", "trade_actions_created",
    "broker_action_created", "broker_actions_created", "authoritative_overwrite_created", "authoritative_overwrites_created",
    "authoritative_ranking_overwritten", "weight_mutated", "weight_mutations_created",
    "performance_claim_created", "performance_claims_created", "performance_effectiveness_claim_created",
    "official_promotion_allowed", "is_official_weight",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def upstream_hashes() -> dict[Path, str]:
    return {path: digest(path) for path in UPSTREAM if path.exists()}


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    bad = [row for row in rows if row.get(field) not in {"", "FALSE"}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def load_module():
    spec = importlib.util.spec_from_file_location("v20_118_promotion_blocker_recheck_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        for name in ["IN_DECISION", "IN_REGISTRY", "IN_SUMMARY", "IN_CONSISTENCY", "IN_SAFETY", "IN_GATE"]:
            setattr(module, name, temp / f"missing_{name}.csv")
        module.REQUIRED_INPUTS = [module.IN_DECISION, module.IN_REGISTRY, module.IN_SUMMARY, module.IN_CONSISTENCY, module.IN_SAFETY, module.IN_GATE]
        module.OUT_DECISION = temp / "V20_118_PROMOTION_BLOCKER_RECHECK_DECISION.csv"
        module.OUT_STATUS = temp / "V20_118_BLOCKER_STATUS_RECHECK_AUDIT.csv"
        module.OUT_EVIDENCE = temp / "V20_118_BLOCKER_RESOLUTION_EVIDENCE_AUDIT.csv"
        module.OUT_REMAINING = temp / "V20_118_REMAINING_BLOCKER_AUDIT.csv"
        module.OUT_SAFETY = temp / "V20_118_PROMOTION_BOUNDARY_SAFETY_AUDIT.csv"
        module.OUT_GATE = temp / "V20_118_NEXT_STAGE_GATE.csv"
        module.REPORT = temp / "V20_118_PROMOTION_BLOCKER_RECHECK_REPORT.md"
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["promotion_blocker_recheck_status"] == "BLOCKED_V20_118_PROMOTION_BLOCKER_RECHECK"
        assert blocked["promotion_ready"] == "FALSE"


def test_promotion_blocker_recheck() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.117 outputs were mutated"
    stdout = result.stdout
    assert "PARTIAL_PASS_V20_118_PROMOTION_BLOCKERS_REMAIN_READY_FOR_OPERATOR_REVIEW_PACKAGE" in stdout
    for expected in [
        "V20_117_GATE_CONSUMED=TRUE",
        "V20_118_PROMOTION_BLOCKER_RECHECK_ALLOWED_BY_V117=TRUE",
        "V20_117_FINAL_STATUS=PASS_V20_117_MULTI_RUN_SHADOW_OBSERVATION_READY_FOR_V20_118",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "BLOCKER_STATUS_RECHECK_CREATED=TRUE",
        "BLOCKER_RESOLUTION_EVIDENCE_CREATED=TRUE",
        "REMAINING_BLOCKER_AUDIT_CREATED=TRUE",
        "ALL_REQUIRED_BLOCKERS_RESOLVED=FALSE",
        "PROMOTION_READY=FALSE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_119_OPERATOR_REVIEW_PACKAGE_ALLOWED=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows or path == OUT_REMAINING, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"
    decision = read_csv(OUT_DECISION)
    status = read_csv(OUT_STATUS)
    evidence = read_csv(OUT_EVIDENCE)
    remaining = read_csv(OUT_REMAINING)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["promotion_ready"] == "FALSE"
    assert int(d["remaining_blocker_count"]) > 0
    assert d["promotion_blocker_recheck_status"] == "PARTIAL_PASS_V20_118_PROMOTION_BLOCKERS_REMAIN_READY_FOR_OPERATOR_REVIEW_PACKAGE"
    assert status and any(row["blocker_resolved"] == "FALSE" for row in status)
    assert evidence and any(row["valid_resolution_evidence"] == "FALSE" for row in evidence)
    assert remaining and all(row["promotion_ready"] == "FALSE" for row in remaining)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["v20_119_operator_review_package_allowed"] == "TRUE"
    assert gate[0]["promotion_ready"] == "FALSE"
    all_resolved = d["all_required_blockers_resolved"] == "TRUE"
    assert (d["promotion_blocker_recheck_status"] == "PASS_V20_118_PROMOTION_BLOCKER_RECHECK_READY_FOR_V20_119") == all_resolved
    for rows in [decision, status, evidence, remaining, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_promotion_blocker_recheck()
    print("PASS_V20_118_PROMOTION_BLOCKER_RECHECK_TESTS")
