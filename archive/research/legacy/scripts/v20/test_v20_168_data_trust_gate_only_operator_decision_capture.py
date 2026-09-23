#!/usr/bin/env python
"""Tests for V20.168 DATA_TRUST gate-only operator decision capture."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_168_data_trust_gate_only_operator_decision_capture.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_DECISION = FACTORS / "V20_168_DATA_TRUST_GATE_ONLY_OPERATOR_DECISION_CAPTURE.csv"
OUT_GATE = FACTORS / "V20_168_DATA_TRUST_GATE_ONLY_DECISION_GATE.csv"
OUT_SAFETY = FACTORS / "V20_168_DATA_TRUST_GATE_ONLY_DECISION_SAFETY_AUDIT.csv"
OUT_DIRECT_MAPPING = FACTORS / "V20_168_DATA_TRUST_DIRECT_MAPPING_REQUIREMENT_PACKET.csv"
OUT_NEXT_STAGE = FACTORS / "V20_168_DATA_TRUST_NEXT_STAGE_PACKET.csv"
OUT_REPORT = READ_CENTER / "V20_168_DATA_TRUST_GATE_ONLY_OPERATOR_DECISION_CAPTURE_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_GATE, OUT_SAFETY, OUT_DIRECT_MAPPING, OUT_NEXT_STAGE, OUT_REPORT]

SELECTED_OPTION = "APPROVE_DATA_TRUST_GATE_ONLY_RESEARCH_POLICY_WITH_DIRECT_MAPPING_REQUIRED"
PASS_STATUS = "PASS_V20_168_DATA_TRUST_GATE_ONLY_OPERATOR_DECISION_CAPTURE_READY_FOR_V20_169"
SAFETY_FALSE_FIELDS = [
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "official_weight_change_created",
    "official_weight_registry_mutated",
    "weight_mutated",
    "real_book_action_created",
    "trade_action_created",
    "broker_execution_supported",
    "performance_claim_created",
    "shadow_weight_expansion_allowed",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    assert rows
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def upstream_hashes() -> dict[Path, str]:
    paths = [
        FACTORS / "V20_167_DATA_TRUST_GATE_ONLY_OPERATOR_REVIEW_PACKET.csv",
        FACTORS / "V20_167_DATA_TRUST_GATE_ONLY_POLICY_REVIEW.csv",
        FACTORS / "V20_167_DATA_TRUST_MAPPING_LIMITATION_REVIEW.csv",
        FACTORS / "V20_167_DATA_TRUST_OPERATOR_OPTIONS.csv",
        FACTORS / "V20_167_DATA_TRUST_GATE_ONLY_NEXT_GATE.csv",
        FACTORS / "V20_167_DATA_TRUST_GATE_ONLY_SAFETY_AUDIT.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_168_decision_capture_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.FACTORS = temp / "factors"
    module.READ_CENTER = temp / "read_center"
    for name in ["V167_PACKET", "V167_POLICY", "V167_MAPPING", "V167_OPTIONS", "V167_GATE", "V167_SAFETY"]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    for name in ["OUT_DECISION", "OUT_GATE", "OUT_SAFETY", "OUT_DIRECT_MAPPING", "OUT_NEXT_STAGE"]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.REPORT = module.READ_CENTER / module.REPORT.name


def write_minimal_inputs(module, status_ok: bool = True) -> None:
    status = "PARTIAL_PASS_V20_167_DATA_TRUST_GATE_ONLY_REVIEW_WITH_MAPPING_LIMITATIONS" if status_ok else "WARN"
    write_csv(module.V167_PACKET, [{"packet_id": "P"}])
    write_csv(module.V167_POLICY, [{
        "data_trust_scoring_weight_after": "0.0000000000",
        "data_trust_role": "GATE_ONLY_AND_REPAIR_DIAGNOSTIC",
        "direct_ticker_mapping_count": "0",
        "inferred_from_artifact_mapping_count": "40",
        "mapping_confidence_limitation_flag": "TRUE",
    }])
    write_csv(module.V167_MAPPING, [{
        "direct_ticker_mapping_required_before_official_use": "TRUE",
        "direct_ticker_mapping_count": "0",
        "inferred_from_artifact_mapping_count": "40",
        "mapping_confidence_limitation_flag": "TRUE",
    }])
    write_csv(module.V167_OPTIONS, [{"operator_option": SELECTED_OPTION, "option_available": "TRUE"}])
    write_csv(module.V167_GATE, [{
        "final_status": status,
        "official_ranking_mutated": "FALSE",
        "official_weight_change_created": "FALSE",
    }])
    write_csv(module.V167_SAFETY, [{"safety_check_id": "S"}])


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"
        if "data_trust_scoring_weight" in row:
            assert row["data_trust_scoring_weight"] == "0.0000000000"
        if "data_trust_role" in row:
            assert row["data_trust_role"] == "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_168_DATA_TRUST_GATE_ONLY_OPERATOR_DECISION_CAPTURE"


def test_blocked_wrong_v167_status_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module, status_ok=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_168_DATA_TRUST_GATE_ONLY_OPERATOR_DECISION_CAPTURE"


def test_temp_decision_capture_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        gate = read_csv(module.OUT_GATE)[0]
        direct = read_csv(module.OUT_DIRECT_MAPPING)[0]
        assert decision["selected_operator_option"] == SELECTED_OPTION
        assert decision["data_trust_gate_only_research_policy_approved"] == "TRUE"
        assert decision["official_weight_change_allowed"] == "FALSE"
        assert decision["official_ranking_mutation_allowed"] == "FALSE"
        assert direct["inferred_mapping_sufficient_for_official_use"] == "FALSE"
        assert gate["final_status"] == PASS_STATUS


def test_data_trust_gate_only_operator_decision_capture() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.167 outputs were mutated"
    stdout = result.stdout
    for expected in [
        PASS_STATUS,
        "V20_167_GATE_CONSUMED=TRUE",
        f"SELECTED_OPERATOR_OPTION={SELECTED_OPTION}",
        "OPERATOR_DECISION_STATUS=APPROVED_RESEARCH_ONLY_WITH_DIRECT_MAPPING_REQUIRED",
        "DATA_TRUST_GATE_ONLY_RESEARCH_POLICY_APPROVED=TRUE",
        "DATA_TRUST_SCORING_WEIGHT_AFTER=0.0000000000",
        "DATA_TRUST_ROLE_AFTER=GATE_ONLY_AND_REPAIR_DIAGNOSTIC",
        "DATA_TRUST_FAIL_UNKNOWN_EXCLUSION_REQUIRED=TRUE",
        "REPAIR_BACKLOG_REQUIRED_FOR_FAILED_OR_UNKNOWN_ROWS=TRUE",
        "DIRECT_TICKER_MAPPING_REQUIRED_BEFORE_OFFICIAL_USE=TRUE",
        "DIRECT_TICKER_MAPPING_COUNT=0",
        "INFERRED_FROM_ARTIFACT_MAPPING_COUNT=40",
        "MAPPING_CONFIDENCE_LIMITATION_FLAG=TRUE",
        "OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE",
        "OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE",
        "FORMAL_ACTIVATION_ALLOWED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "REAL_BOOK_ACTION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "PERFORMANCE_CLAIM_CREATED=FALSE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    decision = read_csv(OUT_DECISION)
    gate = read_csv(OUT_GATE)
    safety = read_csv(OUT_SAFETY)
    direct = read_csv(OUT_DIRECT_MAPPING)
    next_stage = read_csv(OUT_NEXT_STAGE)
    assert decision and gate and safety and direct and next_stage
    assert decision[0]["selected_operator_option"] == SELECTED_OPTION
    assert decision[0]["operator_decision_status"] == "APPROVED_RESEARCH_ONLY_WITH_DIRECT_MAPPING_REQUIRED"
    assert decision[0]["data_trust_gate_only_research_policy_approved"] == "TRUE"
    assert decision[0]["official_weight_change_allowed"] == "FALSE"
    assert decision[0]["official_ranking_mutation_allowed"] == "FALSE"
    assert gate[0]["final_status"] == PASS_STATUS
    assert direct[0]["inferred_mapping_sufficient_for_official_use"] == "FALSE"
    assert next_stage[0]["research_only_continuation_allowed"] == "TRUE"
    assert all(row["safety_passed"] == "TRUE" for row in safety)
    for rows in [decision, gate, safety, direct, next_stage]:
        assert_safety(rows)
    assert "research-only continuation" in OUT_REPORT.read_text(encoding="utf-8")


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_wrong_v167_status_case()
    test_temp_decision_capture_case()
    test_data_trust_gate_only_operator_decision_capture()
    print("PASS_V20_168_DATA_TRUST_GATE_ONLY_OPERATOR_DECISION_CAPTURE_TESTS")
