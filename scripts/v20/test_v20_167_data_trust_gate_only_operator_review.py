#!/usr/bin/env python
"""Tests for V20.167 DATA_TRUST gate-only operator review."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_167_data_trust_gate_only_operator_review.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_PACKET = FACTORS / "V20_167_DATA_TRUST_GATE_ONLY_OPERATOR_REVIEW_PACKET.csv"
OUT_POLICY = FACTORS / "V20_167_DATA_TRUST_GATE_ONLY_POLICY_REVIEW.csv"
OUT_MAPPING = FACTORS / "V20_167_DATA_TRUST_MAPPING_LIMITATION_REVIEW.csv"
OUT_OPTIONS = FACTORS / "V20_167_DATA_TRUST_OPERATOR_OPTIONS.csv"
OUT_GATE = FACTORS / "V20_167_DATA_TRUST_GATE_ONLY_NEXT_GATE.csv"
OUT_SAFETY = FACTORS / "V20_167_DATA_TRUST_GATE_ONLY_SAFETY_AUDIT.csv"
OUT_REPORT = READ_CENTER / "V20_167_DATA_TRUST_GATE_ONLY_OPERATOR_REVIEW_REPORT.md"
OUTPUTS = [OUT_PACKET, OUT_POLICY, OUT_MAPPING, OUT_OPTIONS, OUT_GATE, OUT_SAFETY, OUT_REPORT]

EXPECTED_OPTIONS = {
    "APPROVE_DATA_TRUST_GATE_ONLY_RESEARCH_POLICY_WITH_DIRECT_MAPPING_REQUIRED",
    "REQUEST_DIRECT_TICKER_LEVEL_DATA_TRUST_MAPPING_REPAIR",
    "REQUEST_MORE_DATA_TRUST_SOURCE_AUDIT",
    "REJECT_DATA_TRUST_GATE_ONLY_POLICY_FOR_NOW",
    "KEEP_DATA_TRUST_AS_SCORING_WEIGHT_FOR_NOW",
}
REVIEW_COLUMNS = {
    "data_trust_scoring_weight_before",
    "data_trust_scoring_weight_after",
    "data_trust_role",
    "proposed_scoring_weight_sum",
    "baseline_candidate_count",
    "data_trust_pass_count",
    "data_trust_fail_count",
    "data_trust_unknown_count",
    "direct_ticker_mapping_count",
    "inferred_from_artifact_mapping_count",
    "mapping_confidence_limitation_flag",
    "bound_top20_turnover_rate",
    "bound_max_absolute_rank_delta",
    "baseline_binding_success",
    "gate_only_policy_research_ready",
    "direct_ticker_mapping_required_before_official_use",
    "operator_review_required",
    "operator_input_required",
    "selected_operator_option",
    "recommended_next_action",
}
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
        FACTORS / "V20_166_R3_DATA_TRUST_SCORE_LINEAGE_AUDIT.csv",
        FACTORS / "V20_166_R3_DATA_TRUST_WEIGHT_BINDING_AUDIT.csv",
        FACTORS / "V20_166_R3_DATA_TRUST_SCORE_NORMALIZATION_AUDIT.csv",
        FACTORS / "V20_166_R3_DATA_TRUST_BASELINE_BINDING_REPAIR.csv",
        FACTORS / "V20_166_R3_BOUND_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION.csv",
        FACTORS / "V20_166_R3_BOUND_DATA_TRUST_GATE_ONLY_RANK_DELTA.csv",
        FACTORS / "V20_166_R3_MAPPING_CONFIDENCE_LIMITATION_AUDIT.csv",
        FACTORS / "V20_166_R3_DATA_TRUST_NEXT_GATE.csv",
        FACTORS / "V20_166_R1_DATA_TRUST_TICKER_STATUS.csv",
        FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_MAPPING_CONFIDENCE_AUDIT.csv",
        FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_SAFETY_AUDIT.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_167_operator_review_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.FACTORS = temp / "factors"
    module.READ_CENTER = temp / "read_center"
    for name in [
        "R3_LINEAGE", "R3_WEIGHT_BINDING", "R3_NORMALIZATION", "R3_REPAIR",
        "R3_SIM", "R3_DELTA", "R3_MAPPING", "R3_GATE", "R1_STATUS",
        "R2_MAPPING", "R2_SAFETY",
    ]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    for name in ["OUT_PACKET", "OUT_POLICY", "OUT_MAPPING", "OUT_OPTIONS", "OUT_GATE", "OUT_SAFETY"]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.REPORT = module.READ_CENTER / module.REPORT.name


def write_minimal_inputs(module, status_ok: bool = True) -> None:
    status = (
        "PARTIAL_PASS_V20_166_R3_DATA_TRUST_BASELINE_BINDING_WITH_MAPPING_LIMITATIONS_READY_FOR_V20_167"
        if status_ok else "WARN"
    )
    diag = {
        "diagnostic_id": "D",
        "baseline_candidate_count": "40",
        "gate_only_candidate_count": "40",
        "baseline_weight_sum": "1.0000000000",
        "proposed_gate_only_weight_sum": "1.0000000000",
        "data_trust_weight_before": "0.1000000000",
        "data_trust_weight_after": "0.0000000000",
    }
    for path in [module.R3_LINEAGE, module.R3_WEIGHT_BINDING, module.R3_NORMALIZATION, module.R3_REPAIR]:
        write_csv(path, [diag])
    write_csv(module.R3_SIM, [{"ticker": "AAA", "score_binding_success": "TRUE"}])
    write_csv(module.R3_MAPPING, [{"mapping_review_id": "M", "mapping_confidence_limitation_flag": "TRUE"}])
    write_csv(module.R3_DELTA, [{
        "summary_id": "S",
        "baseline_candidate_count": "40",
        "bound_gate_only_candidate_count": "40",
        "data_trust_pass_count": "40",
        "data_trust_fail_count": "0",
        "data_trust_unknown_count": "0",
        "direct_ticker_mapping_count": "0",
        "inferred_from_artifact_mapping_count": "40",
        "mapping_confidence_limitation_flag": "TRUE",
        "bound_top20_turnover_rate": "0.0000000000",
        "bound_max_absolute_rank_delta": "0",
        "baseline_binding_improved_rank_stability": "TRUE",
        "ready_for_operator_review": "TRUE",
    }])
    write_csv(module.R3_GATE, [{
        "final_status": status,
        "ready_for_operator_review": "TRUE",
        "data_trust_scoring_weight": "0.0000000000",
        "data_trust_role": "GATE_ONLY_AND_REPAIR_DIAGNOSTIC",
        "official_ranking_mutated": "FALSE",
        "official_weight_change_created": "FALSE",
    }])


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"
        if "data_trust_role" in row:
            assert row["data_trust_role"] == "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
        if "data_trust_scoring_weight" in row:
            assert row["data_trust_scoring_weight"] == "0.0000000000"


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_167_DATA_TRUST_GATE_ONLY_OPERATOR_REVIEW"


def test_blocked_wrong_r3_status_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module, status_ok=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_167_DATA_TRUST_GATE_ONLY_OPERATOR_REVIEW"


def test_temp_operator_packet_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module)
        assert module.main() == 0
        review = read_csv(module.OUT_POLICY)[0]
        mapping = read_csv(module.OUT_MAPPING)[0]
        options = read_csv(module.OUT_OPTIONS)
        gate = read_csv(module.OUT_GATE)[0]
        assert review["operator_input_required"] == "TRUE"
        assert review["selected_operator_option"] == "AWAITING_EXPLICIT_OPERATOR_REVIEW"
        assert review["direct_ticker_mapping_required_before_official_use"] == "TRUE"
        assert mapping["official_promotion_sufficient"] == "FALSE"
        assert {row["operator_option"] for row in options} == EXPECTED_OPTIONS
        assert gate["final_status"] == "PARTIAL_PASS_V20_167_DATA_TRUST_GATE_ONLY_REVIEW_WITH_MAPPING_LIMITATIONS"


def test_data_trust_gate_only_operator_review() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.166-R3/R2/R1 outputs were mutated"
    stdout = result.stdout
    assert "PARTIAL_PASS_V20_167_DATA_TRUST_GATE_ONLY_REVIEW_WITH_MAPPING_LIMITATIONS" in stdout
    for expected in [
        "V20_166_R3_GATE_CONSUMED=TRUE",
        "DATA_TRUST_SCORING_WEIGHT_AFTER=0.0000000000",
        "DATA_TRUST_ROLE=GATE_ONLY_AND_REPAIR_DIAGNOSTIC",
        "BASELINE_CANDIDATE_COUNT=40",
        "DATA_TRUST_PASS_COUNT=40",
        "DIRECT_TICKER_MAPPING_COUNT=0",
        "INFERRED_FROM_ARTIFACT_MAPPING_COUNT=40",
        "MAPPING_CONFIDENCE_LIMITATION_FLAG=TRUE",
        "BOUND_TOP20_TURNOVER_RATE=0.0000000000",
        "BOUND_MAX_ABSOLUTE_RANK_DELTA=0",
        "OPERATOR_REVIEW_REQUIRED=TRUE",
        "OPERATOR_INPUT_REQUIRED=TRUE",
        "SELECTED_OPERATOR_OPTION=AWAITING_EXPLICIT_OPERATOR_REVIEW",
        "FORMAL_ACTIVATION_ALLOWED=FALSE",
        "PROMOTION_READY=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "OFFICIAL_WEIGHT_CHANGE_CREATED=FALSE",
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
    packet = read_csv(OUT_PACKET)
    policy = read_csv(OUT_POLICY)
    mapping = read_csv(OUT_MAPPING)
    options = read_csv(OUT_OPTIONS)
    gate = read_csv(OUT_GATE)
    safety = read_csv(OUT_SAFETY)
    assert packet and policy and mapping and options and gate and safety
    assert REVIEW_COLUMNS.issubset(policy[0].keys()), REVIEW_COLUMNS - set(policy[0].keys())
    assert policy[0]["operator_input_required"] == "TRUE"
    assert policy[0]["selected_operator_option"] == "AWAITING_EXPLICIT_OPERATOR_REVIEW"
    assert policy[0]["mapping_confidence_limitation_flag"] == "TRUE"
    assert policy[0]["direct_ticker_mapping_required_before_official_use"] == "TRUE"
    assert mapping[0]["official_promotion_sufficient"] == "FALSE"
    assert {row["operator_option"] for row in options} == EXPECTED_OPTIONS
    assert gate[0]["final_status"] == "PARTIAL_PASS_V20_167_DATA_TRUST_GATE_ONLY_REVIEW_WITH_MAPPING_LIMITATIONS"
    assert all(row["safety_passed"] == "TRUE" for row in safety)
    for rows in [packet, policy, mapping, options, gate, safety]:
        assert_safety(rows)
    assert "direct ticker-level evidence" in OUT_REPORT.read_text(encoding="utf-8")


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_wrong_r3_status_case()
    test_temp_operator_packet_case()
    test_data_trust_gate_only_operator_review()
    print("PASS_V20_167_DATA_TRUST_GATE_ONLY_OPERATOR_REVIEW_TESTS")
