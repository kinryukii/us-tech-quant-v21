#!/usr/bin/env python
"""Tests for V20.146 promotion-readiness recheck."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_146_promotion_readiness_recheck.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_DECISION = CONSOLIDATION / "V20_146_PROMOTION_READINESS_RECHECK_DECISION.csv"
OUT_DISPOSITION = CONSOLIDATION / "V20_146_BLOCKER_DISPOSITION_AUDIT.csv"
OUT_LIMITATION = CONSOLIDATION / "V20_146_LIMITATION_ACCEPTANCE_AUDIT.csv"
OUT_CRITERIA = CONSOLIDATION / "V20_146_PROMOTION_READINESS_CRITERIA_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_146_PROMOTION_READINESS_RECHECK_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_146_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_146_PROMOTION_READINESS_RECHECK_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_DISPOSITION, OUT_LIMITATION, OUT_CRITERIA, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = sorted(
    path
    for path in CONSOLIDATION.glob("V20_*")
    if path.is_file() and any(path.name.startswith(f"V20_{stage}_") for stage in range(109, 146))
)
REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_145_gate_consumed", "v20_146_promotion_readiness_recheck_allowed_by_v145", "v20_145_final_status", "selected_repair_scenario_id", "final_human_decision_record_count", "blocker_disposition_row_count", "limitation_acceptance_row_count", "promotion_readiness_criteria_row_count", "all_remaining_blockers_have_explicit_human_decisions", "all_human_decisions_valid", "no_reject_keep_blocked", "no_more_evidence_required", "promotion_readiness_recheck_passed", "promotion_ready", "v20_147_promotion_readiness_packet_allowed", "promotion_readiness_recheck_status"},
    OUT_DISPOSITION: {"source_final_human_decision_record_id", "blocker_id", "blocker_category", "selected_human_action", "blocker_disposition", "promotion_readiness_recheck_passed", "evidence_acceptance", "operator_acceptance", "promotion_ready", "ticker_rows_created"},
    OUT_LIMITATION: {"source_final_human_decision_record_id", "blocker_id", "blocker_category", "selected_human_action", "human_rationale_present", "limitation_accepted_for_recheck_only", "acceptance_scope", "evidence_acceptance", "operator_acceptance", "promotion_ready"},
    OUT_CRITERIA: {"criterion_name", "criterion_passed", "criterion_observed_value", "criterion_required_value", "criterion_failure_blocks_pass", "promotion_readiness_recheck_passed", "promotion_ready"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_145_gate_consumed", "selected_repair_scenario_id", "promotion_readiness_recheck_passed", "promotion_ready", "evidence_acceptance", "operator_acceptance", "v20_147_promotion_readiness_packet_allowed", "promotion_readiness_recheck_status"},
}
PROHIBITED_FALSE_FIELDS = ["official_recommendation_created", "official_ranking_created", "official_weight_created", "real_book_weight_created", "real_book_action_created", "trade_action_created", "broker_action_created", "authoritative_overwrite_created", "weight_mutated", "performance_claim_created", "promotion_ready"]


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
    spec = importlib.util.spec_from_file_location("v20_146_promotion_readiness_recheck_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    mapping = {
        "IN_DECISION": "V20_145_FINAL_HUMAN_DECISION_CAPTURE_DECISION.csv",
        "IN_INPUT_AUDIT": "V20_145_FINAL_HUMAN_DECISION_INPUT_AUDIT.csv",
        "IN_INPUT_FALLBACK": "V20_145_EXPLICIT_HUMAN_DECISION_INPUT.csv",
        "IN_RECORD": "V20_145_FINAL_HUMAN_DECISION_RECORD.csv",
        "IN_VALIDATION": "V20_145_FINAL_HUMAN_DECISION_VALIDATION_AUDIT.csv",
        "IN_CONSEQUENCE": "V20_145_FINAL_HUMAN_DECISION_CONSEQUENCE_AUDIT.csv",
        "IN_SAFETY": "V20_145_FINAL_HUMAN_DECISION_SAFETY_BOUNDARY_AUDIT.csv",
        "IN_GATE": "V20_145_NEXT_STAGE_GATE.csv",
        "IN_PACKET": "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET.csv",
        "IN_REMAINING": "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS.csv",
        "IN_COVERAGE": "V20_141_THIRD_ROUND_BLOCKER_COVERAGE_AUDIT.csv",
    }
    for attr, filename in mapping.items():
        setattr(module, attr, temp / filename)
    module.REQUIRED_INPUTS = [getattr(module, attr) for attr in ["IN_DECISION", "IN_RECORD", "IN_VALIDATION", "IN_CONSEQUENCE", "IN_SAFETY", "IN_GATE", "IN_PACKET", "IN_REMAINING", "IN_COVERAGE"]]
    module.UPSTREAM_HASH_INPUTS = module.REQUIRED_INPUTS + [module.IN_INPUT_FALLBACK]
    module.OUT_DECISION = temp / "V20_146_PROMOTION_READINESS_RECHECK_DECISION.csv"
    module.OUT_DISPOSITION = temp / "V20_146_BLOCKER_DISPOSITION_AUDIT.csv"
    module.OUT_LIMITATION = temp / "V20_146_LIMITATION_ACCEPTANCE_AUDIT.csv"
    module.OUT_CRITERIA = temp / "V20_146_PROMOTION_READINESS_CRITERIA_AUDIT.csv"
    module.OUT_SAFETY = temp / "V20_146_PROMOTION_READINESS_RECHECK_SAFETY_BOUNDARY_AUDIT.csv"
    module.OUT_GATE = temp / "V20_146_NEXT_STAGE_GATE.csv"
    module.REPORT = temp / "V20_146_PROMOTION_READINESS_RECHECK_REPORT.md"


def copy_required_inputs(temp: Path) -> None:
    for filename in [
        "V20_145_FINAL_HUMAN_DECISION_CAPTURE_DECISION.csv",
        "V20_145_EXPLICIT_HUMAN_DECISION_INPUT.csv",
        "V20_145_FINAL_HUMAN_DECISION_RECORD.csv",
        "V20_145_FINAL_HUMAN_DECISION_VALIDATION_AUDIT.csv",
        "V20_145_FINAL_HUMAN_DECISION_CONSEQUENCE_AUDIT.csv",
        "V20_145_FINAL_HUMAN_DECISION_SAFETY_BOUNDARY_AUDIT.csv",
        "V20_145_NEXT_STAGE_GATE.csv",
        "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET.csv",
        "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS.csv",
        "V20_141_THIRD_ROUND_BLOCKER_COVERAGE_AUDIT.csv",
    ]:
        shutil.copy2(CONSOLIDATION / filename, temp / filename)


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["promotion_readiness_recheck_status"] == "BLOCKED_V20_146_PROMOTION_READINESS_RECHECK"
        assert decision["v20_147_promotion_readiness_packet_allowed"] == "FALSE"
        assert decision["promotion_ready"] == "FALSE"


def test_missing_explicit_human_input_prevents_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        input_rows = read_csv(module.IN_INPUT_FALLBACK)
        write_csv(module.IN_INPUT_FALLBACK, input_rows[:-1])
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["promotion_readiness_recheck_status"] != "PASS_V20_146_PROMOTION_READINESS_RECHECK_READY_FOR_V20_147"
        assert decision["all_remaining_blockers_have_explicit_human_decisions"] == "FALSE"
        assert decision["promotion_ready"] == "FALSE"


def test_reject_or_more_evidence_prevents_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        records = read_csv(module.IN_RECORD)
        records[0]["selected_human_action"] = "REJECT_KEEP_BLOCKED"
        records[0]["evidence_acceptance"] = "FALSE"
        records[0]["operator_acceptance"] = "TRUE"
        write_csv(module.IN_RECORD, records)
        inputs = read_csv(module.IN_INPUT_FALLBACK)
        inputs[0]["selected_human_action"] = "REJECT_KEEP_BLOCKED"
        write_csv(module.IN_INPUT_FALLBACK, inputs)
        validation = read_csv(module.IN_VALIDATION)
        validation[0]["selected_human_action"] = "REJECT_KEEP_BLOCKED"
        write_csv(module.IN_VALIDATION, validation)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        disposition = read_csv(module.OUT_DISPOSITION)
        assert decision["promotion_readiness_recheck_status"] == "PARTIAL_PASS_V20_146_PROMOTION_READINESS_RECHECK_FAILED_BLOCKERS_REMAIN"
        assert decision["v20_147_promotion_readiness_packet_allowed"] == "FALSE"
        assert any(row["blocker_disposition"] == "BLOCKED_BY_OPERATOR_REJECTION" for row in disposition)


def test_blocked_input_cases_produce_blocked_not_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        gate = read_csv(module.IN_GATE)
        gate[0]["v20_146_promotion_readiness_recheck_allowed"] = "FALSE"
        write_csv(module.IN_GATE, gate)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["promotion_readiness_recheck_status"] == "BLOCKED_V20_146_PROMOTION_READINESS_RECHECK"
        assert decision["v20_147_promotion_readiness_packet_allowed"] == "FALSE"


def test_promotion_readiness_recheck() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.145 outputs were mutated"
    stdout = result.stdout
    for expected in [
        "PASS_V20_146_PROMOTION_READINESS_RECHECK_READY_FOR_V20_147",
        "V20_145_GATE_CONSUMED=TRUE",
        "V20_146_PROMOTION_READINESS_RECHECK_ALLOWED_BY_V145=TRUE",
        "V20_145_FINAL_STATUS=PASS_V20_145_FINAL_HUMAN_DECISION_CAPTURE_READY_FOR_PROMOTION_READINESS_RECHECK",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "FINAL_HUMAN_DECISION_RECORD_COUNT=2",
        "BLOCKER_DISPOSITION_ROW_COUNT=2",
        "LIMITATION_ACCEPTANCE_ROW_COUNT=2",
        "PROMOTION_READINESS_CRITERIA_ROW_COUNT=10",
        "ALL_REMAINING_BLOCKERS_HAVE_EXPLICIT_HUMAN_DECISIONS=TRUE",
        "ALL_HUMAN_DECISIONS_VALID=TRUE",
        "NO_REJECT_KEEP_BLOCKED=TRUE",
        "NO_MORE_EVIDENCE_REQUIRED=TRUE",
        "ALL_ACCEPT_WITH_LIMITATION_ROWS_HAVE_HUMAN_RATIONALE=TRUE",
        "EVIDENCE_ACCEPTANCE=TRUE",
        "OPERATOR_ACCEPTANCE=TRUE",
        "PROMOTION_READINESS_RECHECK_PASSED=TRUE",
        "PROMOTION_READY=FALSE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_147_PROMOTION_READINESS_PACKET_ALLOWED=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"

    decision = read_csv(OUT_DECISION)
    disposition = read_csv(OUT_DISPOSITION)
    limitation = read_csv(OUT_LIMITATION)
    criteria = read_csv(OUT_CRITERIA)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    records = read_csv(CONSOLIDATION / "V20_145_FINAL_HUMAN_DECISION_RECORD.csv")
    d = decision[0]
    assert d["promotion_readiness_recheck_status"] == "PASS_V20_146_PROMOTION_READINESS_RECHECK_READY_FOR_V20_147"
    assert d["promotion_readiness_recheck_passed"] == "TRUE"
    assert d["promotion_ready"] == "FALSE"
    assert len(disposition) == len(records)
    assert all(row["blocker_disposition"] == "LIMITATION_ACCEPTED_FOR_PROMOTION_READINESS_RECHECK_ONLY" for row in disposition)
    assert all(row["evidence_acceptance"] == "TRUE" and row["operator_acceptance"] == "TRUE" and row["promotion_ready"] == "FALSE" for row in disposition)
    assert limitation
    assert len(limitation) == len(records)
    assert all(row["limitation_accepted_for_recheck_only"] == "TRUE" and row["human_rationale_present"] == "TRUE" for row in limitation)
    assert criteria
    assert all(row["criterion_passed"] == "TRUE" and row["promotion_ready"] == "FALSE" for row in criteria)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["v20_147_promotion_readiness_packet_allowed"] == "TRUE"
    assert gate[0]["promotion_readiness_recheck_passed"] == "TRUE"
    assert gate[0]["promotion_ready"] == "FALSE"
    for rows in [decision, disposition, limitation, criteria, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_missing_explicit_human_input_prevents_pass()
    test_reject_or_more_evidence_prevents_pass()
    test_blocked_input_cases_produce_blocked_not_pass()
    test_promotion_readiness_recheck()
    print("PASS_V20_146_PROMOTION_READINESS_RECHECK_TESTS")

