#!/usr/bin/env python
"""Tests for V20.147 promotion-readiness packet."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_147_promotion_readiness_packet.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
PACKET_SCOPE = "PROMOTION_READINESS_PACKET_ONLY_NOT_OFFICIAL_PROMOTION"
NEXT_REVIEW_ACTION = "OPERATOR_REVIEW_OF_PROMOTION_READINESS_PACKET"

OUT_DECISION = CONSOLIDATION / "V20_147_PROMOTION_READINESS_PACKET_DECISION.csv"
OUT_PACKET = CONSOLIDATION / "V20_147_PROMOTION_READINESS_PACKET.csv"
OUT_MANIFEST = CONSOLIDATION / "V20_147_PROMOTION_READINESS_EVIDENCE_MANIFEST.csv"
OUT_LIMITATION = CONSOLIDATION / "V20_147_PROMOTION_READINESS_LIMITATION_SUMMARY.csv"
OUT_SAFETY = CONSOLIDATION / "V20_147_PROMOTION_READINESS_PACKET_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_147_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_147_PROMOTION_READINESS_PACKET_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_PACKET, OUT_MANIFEST, OUT_LIMITATION, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = sorted(
    path
    for path in CONSOLIDATION.glob("V20_*")
    if path.is_file() and any(path.name.startswith(f"V20_{stage}_") for stage in range(109, 147))
)
REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_146_gate_consumed", "v20_147_promotion_readiness_packet_allowed_by_v146", "v20_146_final_status", "selected_repair_scenario_id", "promotion_readiness_recheck_passed", "promotion_readiness_packet_row_count", "evidence_manifest_row_count", "limitation_summary_row_count", "packet_scope_valid", "allowed_next_review_action_valid", "evidence_acceptance", "operator_acceptance", "promotion_ready", "v20_148_promotion_readiness_operator_review_allowed", "promotion_readiness_packet_status"},
    OUT_PACKET: {"selected_repair_scenario_id", "source_recheck_status", "promotion_readiness_recheck_passed", "evidence_acceptance", "operator_acceptance", "accepted_blocker_count", "rejected_blocker_count", "more_evidence_required_blocker_count", "limitation_count", "criteria_pass_count", "criteria_fail_count", "remaining_limitation_summary", "readiness_packet_scope", "allowed_next_review_action", "promotion_ready", "ticker_rows_created"},
    OUT_MANIFEST: {"source_stage", "source_artifact", "source_record_id", "blocker_id", "blocker_category", "manifest_role", "promotion_ready"},
    OUT_LIMITATION: {"source_limitation_acceptance_audit_id", "blocker_id", "blocker_category", "selected_human_action", "limitation_accepted_for_recheck_only", "acceptance_scope", "human_rationale_present", "limitation_summary", "evidence_acceptance", "operator_acceptance", "promotion_ready"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_146_gate_consumed", "selected_repair_scenario_id", "promotion_readiness_packet_created", "promotion_readiness_recheck_passed", "promotion_ready", "evidence_acceptance", "operator_acceptance", "v20_148_promotion_readiness_operator_review_allowed", "promotion_readiness_packet_status"},
}
PROHIBITED_FALSE_FIELDS = ["accepted_weight_created", "real_book_weight_created", "official_weight_created", "official_ranking_created", "official_recommendation_created", "trade_action_created", "broker_action_created", "authoritative_overwrite_created", "weight_mutated", "performance_claim_created", "promotion_ready"]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    assert rows
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def upstream_hashes() -> dict[Path, str]:
    return {path: digest(path) for path in UPSTREAM if path.exists()}


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    bad = [row for row in rows if row.get(field) not in {"", "FALSE"}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def load_module():
    spec = importlib.util.spec_from_file_location("v20_147_promotion_readiness_packet_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    mapping = {
        "IN_DECISION": "V20_146_PROMOTION_READINESS_RECHECK_DECISION.csv",
        "IN_DISPOSITION": "V20_146_BLOCKER_DISPOSITION_AUDIT.csv",
        "IN_LIMITATION": "V20_146_LIMITATION_ACCEPTANCE_AUDIT.csv",
        "IN_CRITERIA": "V20_146_PROMOTION_READINESS_CRITERIA_AUDIT.csv",
        "IN_SAFETY": "V20_146_PROMOTION_READINESS_RECHECK_SAFETY_BOUNDARY_AUDIT.csv",
        "IN_GATE": "V20_146_NEXT_STAGE_GATE.csv",
        "IN_V145_RECORD": "V20_145_FINAL_HUMAN_DECISION_RECORD.csv",
        "IN_V144_PACKET": "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET.csv",
        "IN_V141_COVERAGE": "V20_141_THIRD_ROUND_BLOCKER_COVERAGE_AUDIT.csv",
        "IN_V133_REMAINING": "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS.csv",
    }
    for attr, filename in mapping.items():
        setattr(module, attr, temp / filename)
    module.REQUIRED_INPUTS = [getattr(module, attr) for attr in mapping]
    module.UPSTREAM_HASH_INPUTS = module.REQUIRED_INPUTS
    module.OUT_DECISION = temp / "V20_147_PROMOTION_READINESS_PACKET_DECISION.csv"
    module.OUT_PACKET = temp / "V20_147_PROMOTION_READINESS_PACKET.csv"
    module.OUT_MANIFEST = temp / "V20_147_PROMOTION_READINESS_EVIDENCE_MANIFEST.csv"
    module.OUT_LIMITATION_SUMMARY = temp / "V20_147_PROMOTION_READINESS_LIMITATION_SUMMARY.csv"
    module.OUT_SAFETY = temp / "V20_147_PROMOTION_READINESS_PACKET_SAFETY_BOUNDARY_AUDIT.csv"
    module.OUT_GATE = temp / "V20_147_NEXT_STAGE_GATE.csv"
    module.REPORT = temp / "V20_147_PROMOTION_READINESS_PACKET_REPORT.md"


def copy_required_inputs(temp: Path) -> None:
    for filename in [
        "V20_146_PROMOTION_READINESS_RECHECK_DECISION.csv",
        "V20_146_BLOCKER_DISPOSITION_AUDIT.csv",
        "V20_146_LIMITATION_ACCEPTANCE_AUDIT.csv",
        "V20_146_PROMOTION_READINESS_CRITERIA_AUDIT.csv",
        "V20_146_PROMOTION_READINESS_RECHECK_SAFETY_BOUNDARY_AUDIT.csv",
        "V20_146_NEXT_STAGE_GATE.csv",
        "V20_145_FINAL_HUMAN_DECISION_RECORD.csv",
        "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET.csv",
        "V20_141_THIRD_ROUND_BLOCKER_COVERAGE_AUDIT.csv",
        "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS.csv",
    ]:
        shutil.copy2(CONSOLIDATION / filename, temp / filename)


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["promotion_readiness_packet_status"] == "BLOCKED_V20_147_PROMOTION_READINESS_PACKET"
        assert decision["v20_148_promotion_readiness_operator_review_allowed"] == "FALSE"
        assert decision["promotion_ready"] == "FALSE"


def test_recheck_passed_required_for_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        decision = read_csv(module.IN_DECISION)
        decision[0]["promotion_readiness_recheck_passed"] = "FALSE"
        write_csv(module.IN_DECISION, decision)
        assert module.main() == 0
        output = read_csv(module.OUT_DECISION)[0]
        assert output["promotion_readiness_packet_status"] == "BLOCKED_V20_147_PROMOTION_READINESS_PACKET"
        assert output["promotion_readiness_recheck_passed"] == "FALSE"


def test_official_scope_cannot_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        module.PACKET_SCOPE = "OFFICIAL_PROMOTION_PACKET"
        assert module.main() == 0
        output = read_csv(module.OUT_DECISION)[0]
        packet = read_csv(module.OUT_PACKET)[0]
        assert output["promotion_readiness_packet_status"] == "BLOCKED_V20_147_PROMOTION_READINESS_PACKET"
        assert packet["readiness_packet_scope"] != PACKET_SCOPE


def test_blocked_input_cases_produce_blocked_not_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        gate = read_csv(module.IN_GATE)
        gate[0]["v20_147_promotion_readiness_packet_allowed"] = "FALSE"
        write_csv(module.IN_GATE, gate)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["promotion_readiness_packet_status"] == "BLOCKED_V20_147_PROMOTION_READINESS_PACKET"
        assert decision["v20_148_promotion_readiness_operator_review_allowed"] == "FALSE"


def test_promotion_readiness_packet() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.146 outputs were mutated"
    stdout = result.stdout
    for expected in [
        "PASS_V20_147_PROMOTION_READINESS_PACKET_READY_FOR_V20_148",
        "V20_146_GATE_CONSUMED=TRUE",
        "V20_147_PROMOTION_READINESS_PACKET_ALLOWED_BY_V146=TRUE",
        "V20_146_FINAL_STATUS=PASS_V20_146_PROMOTION_READINESS_RECHECK_READY_FOR_V20_147",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "PROMOTION_READINESS_RECHECK_PASSED=TRUE",
        "PROMOTION_READINESS_PACKET_ROW_COUNT=1",
        "PACKET_SCOPE_VALID=TRUE",
        "ALLOWED_NEXT_REVIEW_ACTION_VALID=TRUE",
        "EVIDENCE_ACCEPTANCE=TRUE",
        "OPERATOR_ACCEPTANCE=TRUE",
        "PROMOTION_READY=FALSE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_ALLOWED=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"

    decision = read_csv(OUT_DECISION)
    packet = read_csv(OUT_PACKET)
    manifest = read_csv(OUT_MANIFEST)
    limitation = read_csv(OUT_LIMITATION)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    d = decision[0]
    p = packet[0]
    assert d["promotion_readiness_packet_status"] == "PASS_V20_147_PROMOTION_READINESS_PACKET_READY_FOR_V20_148"
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert len(packet) == 1
    assert p["readiness_packet_scope"] == PACKET_SCOPE
    assert p["allowed_next_review_action"] == NEXT_REVIEW_ACTION
    assert p["promotion_readiness_recheck_passed"] == "TRUE"
    assert p["evidence_acceptance"] == "TRUE"
    assert p["operator_acceptance"] == "TRUE"
    assert p["promotion_ready"] == "FALSE"
    assert int(p["accepted_blocker_count"]) == 2
    assert int(p["rejected_blocker_count"]) == 0
    assert int(p["more_evidence_required_blocker_count"]) == 0
    assert manifest
    roles = {row["manifest_role"] for row in manifest}
    assert {"BLOCKER_SOURCE", "THIRD_ROUND_BLOCKER_COVERAGE", "FINAL_HUMAN_CONFIRMATION_PACKET", "FINAL_HUMAN_DECISION_RECORD", "BLOCKER_DISPOSITION", "PROMOTION_READINESS_CRITERIA"}.issubset(roles)
    assert limitation
    assert all(row["limitation_accepted_for_recheck_only"] == "TRUE" and row["promotion_ready"] == "FALSE" for row in limitation)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["v20_148_promotion_readiness_operator_review_allowed"] == "TRUE"
    assert gate[0]["promotion_ready"] == "FALSE"
    for rows in [decision, packet, manifest, limitation, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_recheck_passed_required_for_pass()
    test_official_scope_cannot_pass()
    test_blocked_input_cases_produce_blocked_not_pass()
    test_promotion_readiness_packet()
    print("PASS_V20_147_PROMOTION_READINESS_PACKET_TESTS")

