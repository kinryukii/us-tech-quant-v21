#!/usr/bin/env python
"""Tests for V20.150 staging review packet."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_150_staging_review_packet.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
STAGING = ROOT / "outputs" / "v20" / "staging"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_PACKET = STAGING / "V20_150_STAGING_REVIEW_PACKET.csv"
OUT_GATE = STAGING / "V20_150_STAGING_REVIEW_GATE.csv"
OUT_BOUNDARY = STAGING / "V20_150_PROMOTION_BOUNDARY_AUDIT.csv"
OUT_SAFETY = STAGING / "V20_150_SAFETY_CONSTRAINT_AUDIT.csv"
OUT_REPORT = READ_CENTER / "V20_150_STAGING_REVIEW_PACKET_REPORT.md"
OUTPUTS = [OUT_PACKET, OUT_GATE, OUT_BOUNDARY, OUT_SAFETY, OUT_REPORT]
UPSTREAM = sorted(
    path
    for path in CONSOLIDATION.glob("V20_*")
    if path.is_file() and any(path.name.startswith(f"V20_{stage}_") for stage in range(109, 150))
)
REQUIRED_COLUMNS = {
    OUT_PACKET: {"selected_repair_scenario_id", "source_operator_decision_record_id", "source_operator_decision_status", "selected_operator_action", "staging_review_allowed", "formal_activation_allowed", "promotion_ready", "evidence_acceptance", "operator_acceptance", "staging_review_scope", "allowed_staging_review_action", "ticker_rows_created"},
    OUT_GATE: {"selected_repair_scenario_id", "v20_149_gate_consumed", "v20_150_staging_review_packet_allowed_by_v149", "source_operator_decision_status", "staging_review_packet_created", "staging_review_allowed", "formal_activation_allowed", "promotion_ready", "v20_151_staging_review_allowed", "staging_review_packet_status"},
    OUT_BOUNDARY: {"boundary_name", "boundary_required_value", "boundary_observed_value", "boundary_passed", "boundary_reason"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_constraint_passed"},
}
PROHIBITED_FALSE_FIELDS = ["official_recommendation_created", "official_ranking_created", "official_weight_created", "real_book_action_created", "trade_action_created", "broker_action_created", "authoritative_overwrite_created", "weight_mutated", "performance_claim_created", "formal_activation_allowed", "promotion_ready"]


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
    spec = importlib.util.spec_from_file_location("v20_150_staging_review_packet_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    mapping = {
        "IN_DECISION": "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_DECISION.csv",
        "IN_INPUT": "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_INPUT_AUDIT.csv",
        "IN_RECORD": "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_RECORD.csv",
        "IN_VALIDATION": "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_VALIDATION_AUDIT.csv",
        "IN_CONSEQUENCE": "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CONSEQUENCE_AUDIT.csv",
        "IN_SAFETY": "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_SAFETY_BOUNDARY_AUDIT.csv",
        "IN_GATE": "V20_149_NEXT_STAGE_GATE.csv",
    }
    for attr, filename in mapping.items():
        setattr(module, attr, temp / filename)
    module.REQUIRED_INPUTS = [getattr(module, attr) for attr in mapping]
    module.UPSTREAM_HASH_INPUTS = module.REQUIRED_INPUTS
    module.OUT_PACKET = temp / "V20_150_STAGING_REVIEW_PACKET.csv"
    module.OUT_GATE = temp / "V20_150_STAGING_REVIEW_GATE.csv"
    module.OUT_BOUNDARY = temp / "V20_150_PROMOTION_BOUNDARY_AUDIT.csv"
    module.OUT_SAFETY = temp / "V20_150_SAFETY_CONSTRAINT_AUDIT.csv"
    module.REPORT = temp / "V20_150_STAGING_REVIEW_PACKET_REPORT.md"


def copy_required_inputs(temp: Path) -> None:
    for filename in [
        "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_DECISION.csv",
        "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_INPUT_AUDIT.csv",
        "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_RECORD.csv",
        "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_VALIDATION_AUDIT.csv",
        "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CONSEQUENCE_AUDIT.csv",
        "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_SAFETY_BOUNDARY_AUDIT.csv",
        "V20_149_NEXT_STAGE_GATE.csv",
    ]:
        shutil.copy2(CONSOLIDATION / filename, temp / filename)


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        assert gate["staging_review_packet_status"] == "BLOCKED_V20_150_STAGING_REVIEW_PACKET"
        assert gate["v20_151_staging_review_allowed"] == "FALSE"


def test_gate_must_allow_v20_150() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        gate = read_csv(module.IN_GATE)
        gate[0]["v20_150_staging_review_packet_allowed"] = "FALSE"
        write_csv(module.IN_GATE, gate)
        assert module.main() == 0
        out_gate = read_csv(module.OUT_GATE)[0]
        assert out_gate["staging_review_packet_status"] == "BLOCKED_V20_150_STAGING_REVIEW_PACKET"
        assert out_gate["v20_151_staging_review_allowed"] == "FALSE"


def test_formal_activation_cannot_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        records = read_csv(module.IN_RECORD)
        records[0]["formal_activation_allowed"] = "TRUE"
        write_csv(module.IN_RECORD, records)
        assert module.main() == 0
        out_gate = read_csv(module.OUT_GATE)[0]
        boundary = read_csv(module.OUT_BOUNDARY)
        assert out_gate["staging_review_packet_status"] == "BLOCKED_V20_150_STAGING_REVIEW_PACKET"
        assert any(row["boundary_name"] == "formal_activation_allowed" and row["boundary_passed"] == "FALSE" for row in boundary)


def test_staging_review_packet() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.149 outputs were mutated"
    stdout = result.stdout
    for expected in [
        "PASS_V20_150_STAGING_REVIEW_PACKET_READY_FOR_V20_151",
        "V20_149_GATE_CONSUMED=TRUE",
        "V20_150_STAGING_REVIEW_PACKET_ALLOWED_BY_V149=TRUE",
        "OPERATOR_DECISION_STATUS=APPROVED_FOR_STAGING_REVIEW_ONLY",
        "STAGING_REVIEW_ALLOWED=TRUE",
        "FORMAL_ACTIVATION_ALLOWED=FALSE",
        "PROMOTION_READY=FALSE",
        "EVIDENCE_ACCEPTANCE=TRUE",
        "OPERATOR_ACCEPTANCE=TRUE",
        "STAGING_REVIEW_PACKET_ROW_COUNT=1",
        "PROMOTION_BOUNDARY_AUDIT_PASSED=TRUE",
        "SAFETY_CONSTRAINT_AUDIT_PASSED=TRUE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_151_STAGING_REVIEW_ALLOWED=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"

    packet = read_csv(OUT_PACKET)
    gate = read_csv(OUT_GATE)
    boundary = read_csv(OUT_BOUNDARY)
    safety = read_csv(OUT_SAFETY)
    p = packet[0]
    g = gate[0]
    assert len(packet) == 1
    assert p["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert p["source_operator_decision_status"] == "APPROVED_FOR_STAGING_REVIEW_ONLY"
    assert p["staging_review_allowed"] == "TRUE"
    assert p["formal_activation_allowed"] == "FALSE"
    assert p["promotion_ready"] == "FALSE"
    assert p["staging_review_scope"] == "STAGING_REVIEW_PACKET_ONLY_NOT_FORMAL_ACTIVATION_NOT_OFFICIAL_PROMOTION"
    assert g["staging_review_packet_status"] == "PASS_V20_150_STAGING_REVIEW_PACKET_READY_FOR_V20_151"
    assert g["v20_151_staging_review_allowed"] == "TRUE"
    assert g["promotion_ready"] == "FALSE"
    assert all(row["boundary_passed"] == "TRUE" for row in boundary)
    assert all(row["observed_true_count"] == "0" and row["safety_constraint_passed"] == "TRUE" for row in safety)
    for rows in [packet, gate, boundary, safety]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_gate_must_allow_v20_150()
    test_formal_activation_cannot_pass()
    test_staging_review_packet()
    print("PASS_V20_150_STAGING_REVIEW_PACKET_TESTS")

