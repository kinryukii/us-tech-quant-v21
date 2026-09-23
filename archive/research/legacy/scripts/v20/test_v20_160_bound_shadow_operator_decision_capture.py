#!/usr/bin/env python
"""Tests for V20.160 bound shadow operator decision capture."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_160_bound_shadow_operator_decision_capture.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_DECISION = FACTORS / "V20_160_BOUND_SHADOW_OPERATOR_DECISION_CAPTURE.csv"
OUT_GATE = FACTORS / "V20_160_BOUND_SHADOW_OPERATOR_DECISION_GATE.csv"
OUT_SAFETY = FACTORS / "V20_160_BOUND_SHADOW_DECISION_SAFETY_AUDIT.csv"
OUT_NEXT = FACTORS / "V20_160_BOUND_SHADOW_NEXT_STAGE_PACKET.csv"
OUT_REPORT = READ_CENTER / "V20_160_BOUND_SHADOW_OPERATOR_DECISION_CAPTURE_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_GATE, OUT_SAFETY, OUT_NEXT, OUT_REPORT]

SAFETY_FALSE_FIELDS = [
    "shadow_weight_expansion_allowed",
    "official_weight_change_allowed",
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "official_weight_change_created",
    "real_book_action_created",
    "trade_action_created",
    "broker_execution_supported",
    "performance_claim_created",
]
TRUE_FIELDS = [
    "continued_bound_shadow_research_allowed",
    "additional_stability_observation_runs_required",
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
        FACTORS / "V20_159_BOUND_SHADOW_OPERATOR_REVIEW_PACKET.csv",
        FACTORS / "V20_159_BOUND_SHADOW_STABILITY_REVIEW.csv",
        FACTORS / "V20_159_BOUND_SHADOW_OPERATOR_OPTIONS.csv",
        FACTORS / "V20_159_BOUND_SHADOW_NEXT_GATE.csv",
        FACTORS / "V20_159_BOUND_SHADOW_SAFETY_AUDIT.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_160_decision_capture_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.FACTORS = temp / "factors"
    module.READ_CENTER = temp / "read_center"
    for name in ["IN_PACKET", "IN_REVIEW", "IN_OPTIONS", "IN_GATE", "IN_SAFETY"]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.OUT_DECISION = module.FACTORS / module.OUT_DECISION.name
    module.OUT_GATE = module.FACTORS / module.OUT_GATE.name
    module.OUT_SAFETY = module.FACTORS / module.OUT_SAFETY.name
    module.OUT_NEXT = module.FACTORS / module.OUT_NEXT.name
    module.REPORT = module.READ_CENTER / module.REPORT.name


def write_minimal_inputs(module, status_ok: bool = True, option_available: bool = True) -> None:
    write_csv(module.IN_PACKET, [{
        "operator_input_required": "TRUE",
        "selected_operator_option": "AWAITING_EXPLICIT_OPERATOR_REVIEW",
    }])
    write_csv(module.IN_REVIEW, [{"required_next_action": "REQUEST_ADDITIONAL_STABILITY_OBSERVATION_RUNS"}])
    write_csv(module.IN_OPTIONS, [{
        "operator_option": "REQUEST_ADDITIONAL_STABILITY_OBSERVATION_RUNS",
        "option_available": "TRUE" if option_available else "FALSE",
    }])
    write_csv(module.IN_GATE, [{
        "final_status": "PASS_V20_159_BOUND_SHADOW_OPERATOR_REVIEW_PACKET_AWAITING_OPERATOR_INPUT" if status_ok else "WARN_V20_159_BOUND_SHADOW_STILL_TOO_UNSTABLE_FOR_OPERATOR_APPROVAL",
        "operator_input_required": "TRUE",
        "selected_operator_option": "AWAITING_EXPLICIT_OPERATOR_REVIEW",
    }])
    write_csv(module.IN_SAFETY, [{"safety_check_id": "S1"}])


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"
        for field in TRUE_FIELDS:
            if field in row:
                assert row[field] == "TRUE", f"{field} is not TRUE in {row}"


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_160_BOUND_SHADOW_OPERATOR_DECISION_CAPTURE"


def test_blocked_wrong_v159_status_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        write_minimal_inputs(module, status_ok=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_160_BOUND_SHADOW_OPERATOR_DECISION_CAPTURE"


def test_blocked_option_unavailable_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        write_minimal_inputs(module, option_available=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_160_BOUND_SHADOW_OPERATOR_DECISION_CAPTURE"


def test_temp_decision_capture_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        write_minimal_inputs(module)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        gate = read_csv(module.OUT_GATE)[0]
        next_packet = read_csv(module.OUT_NEXT)[0]
        assert gate["final_status"] == "PASS_V20_160_BOUND_SHADOW_OPERATOR_DECISION_CAPTURE_READY_FOR_V20_161"
        assert decision["selected_operator_option"] == "REQUEST_ADDITIONAL_STABILITY_OBSERVATION_RUNS"
        assert decision["operator_decision_captured"] == "TRUE"
        assert next_packet["v20_161_allowed"] == "TRUE"
        assert_safety([decision, gate, next_packet])


def test_bound_shadow_operator_decision_capture() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.159 outputs were mutated"
    stdout = result.stdout
    assert "PASS_V20_160_BOUND_SHADOW_OPERATOR_DECISION_CAPTURE_READY_FOR_V20_161" in stdout
    for expected in [
        "V20_159_GATE_CONSUMED=TRUE",
        "V20_159_STATUS_ALLOWED=TRUE",
        "SELECTED_OPERATOR_OPTION=REQUEST_ADDITIONAL_STABILITY_OBSERVATION_RUNS",
        "OPERATOR_DECISION_CAPTURED=TRUE",
        "CONTINUED_BOUND_SHADOW_RESEARCH_ALLOWED=TRUE",
        "ADDITIONAL_STABILITY_OBSERVATION_RUNS_REQUIRED=TRUE",
        "SHADOW_WEIGHT_EXPANSION_ALLOWED=FALSE",
        "OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE",
        "FORMAL_ACTIVATION_ALLOWED=FALSE",
        "PROMOTION_READY=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "OFFICIAL_WEIGHT_CHANGE_CREATED=FALSE",
        "REAL_BOOK_ACTION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "PERFORMANCE_CLAIM_CREATED=FALSE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "V20_161_ALLOWED=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    decision = read_csv(OUT_DECISION)
    gate = read_csv(OUT_GATE)
    safety = read_csv(OUT_SAFETY)
    next_packet = read_csv(OUT_NEXT)
    assert decision and gate and safety and next_packet
    assert decision[0]["selected_operator_option"] == "REQUEST_ADDITIONAL_STABILITY_OBSERVATION_RUNS"
    assert gate[0]["final_status"] == "PASS_V20_160_BOUND_SHADOW_OPERATOR_DECISION_CAPTURE_READY_FOR_V20_161"
    assert next_packet[0]["v20_161_allowed"] == "TRUE"
    assert all(row["safety_passed"] == "TRUE" for row in safety)
    for rows in [decision, gate, safety, next_packet]:
        assert_safety(rows)


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_wrong_v159_status_case()
    test_blocked_option_unavailable_case()
    test_temp_decision_capture_case()
    test_bound_shadow_operator_decision_capture()
    print("PASS_V20_160_BOUND_SHADOW_OPERATOR_DECISION_CAPTURE_TESTS")
