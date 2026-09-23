#!/usr/bin/env python
"""Tests for V20.159 bound reduced shadow simulation operator review."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_159_bound_reduced_shadow_simulation_operator_review.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_PACKET = FACTORS / "V20_159_BOUND_SHADOW_OPERATOR_REVIEW_PACKET.csv"
OUT_REVIEW = FACTORS / "V20_159_BOUND_SHADOW_STABILITY_REVIEW.csv"
OUT_OPTIONS = FACTORS / "V20_159_BOUND_SHADOW_OPERATOR_OPTIONS.csv"
OUT_GATE = FACTORS / "V20_159_BOUND_SHADOW_NEXT_GATE.csv"
OUT_SAFETY = FACTORS / "V20_159_BOUND_SHADOW_SAFETY_AUDIT.csv"
OUT_REPORT = READ_CENTER / "V20_159_BOUND_REDUCED_SHADOW_SIMULATION_OPERATOR_REVIEW_REPORT.md"
OUTPUTS = [OUT_PACKET, OUT_REVIEW, OUT_OPTIONS, OUT_GATE, OUT_SAFETY, OUT_REPORT]

REVIEW_COLUMNS = {
    "baseline_candidate_count",
    "bound_shadow_candidate_count",
    "bound_top20_turnover_rate",
    "bound_max_absolute_rank_delta",
    "bound_average_absolute_rank_delta",
    "binding_repair_improved_rank_stability",
    "remaining_rank_impact_severity",
    "prior_unbound_top20_turnover_rate_if_available",
    "prior_unbound_average_absolute_rank_delta_if_available",
    "stability_review_result",
    "operator_review_required",
    "continued_bound_shadow_research_allowed",
    "shadow_weight_expansion_allowed",
    "official_weight_change_allowed",
    "required_next_action",
}
OPTIONS = {
    "APPROVE_CONTINUED_BOUND_SHADOW_RESEARCH_ONLY",
    "REQUEST_MORE_FORWARD_OUTCOMES_BEFORE_EXPANSION",
    "REQUEST_ADDITIONAL_STABILITY_OBSERVATION_RUNS",
    "REQUEST_SCORE_ADJUSTMENT_CAP_REPAIR",
    "REJECT_SHADOW_DYNAMIC_WEIGHT_PATH_FOR_NOW",
}
SAFETY_FALSE_FIELDS = [
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "official_weight_change_created",
    "shadow_weight_expansion_allowed",
    "weight_mutated",
    "real_book_action_created",
    "trade_action_created",
    "broker_execution_supported",
    "performance_claim_created",
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
        FACTORS / "V20_158_R2_AUTHORITATIVE_BASELINE_SCORE_BINDING_REPAIR.csv",
        FACTORS / "V20_158_R2_BOUND_REDUCED_SHADOW_RANKING_SIMULATION.csv",
        FACTORS / "V20_158_R2_BOUND_SHADOW_VS_BASELINE_RANK_DELTA.csv",
        FACTORS / "V20_158_R2_BASELINE_BINDING_AUDIT.csv",
        FACTORS / "V20_158_R2_SCORE_ADJUSTMENT_AUDIT.csv",
        FACTORS / "V20_158_R2_RANK_IMPACT_RETEST_GATE.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_159_bound_review_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.FACTORS = temp / "factors"
    module.READ_CENTER = temp / "read_center"
    for name in ["IN_REPAIR", "IN_SIM", "IN_DELTA", "IN_BINDING", "IN_ADJUST", "IN_GATE"]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.OUT_PACKET = module.FACTORS / module.OUT_PACKET.name
    module.OUT_REVIEW = module.FACTORS / module.OUT_REVIEW.name
    module.OUT_OPTIONS = module.FACTORS / module.OUT_OPTIONS.name
    module.OUT_GATE = module.FACTORS / module.OUT_GATE.name
    module.OUT_SAFETY = module.FACTORS / module.OUT_SAFETY.name
    module.REPORT = module.READ_CENTER / module.REPORT.name


def write_minimal_inputs(module, status_ok: bool = True, severity: str = "ELEVATED") -> None:
    write_csv(module.IN_REPAIR, [{"repair_id": "R1"}])
    write_csv(module.IN_SIM, [{"ticker": "AAA", "official_ranking_mutated": "FALSE", "official_weight_change_created": "FALSE"}])
    write_csv(module.IN_BINDING, [{"ticker": "AAA"}])
    write_csv(module.IN_ADJUST, [{"ticker": "AAA"}])
    write_csv(module.IN_DELTA, [{
        "baseline_candidate_count": "2",
        "bound_shadow_candidate_count": "2",
        "bound_top20_turnover_rate": "0.0000000000",
        "bound_max_absolute_rank_delta": "1",
        "bound_average_absolute_rank_delta": "0.5000000000",
        "binding_repair_improved_rank_stability": "TRUE",
        "remaining_rank_impact_severity": severity,
        "prior_unbound_top20_turnover_rate_if_available": "0.9000000000",
        "prior_unbound_average_absolute_rank_delta_if_available": "13.5750000000",
    }])
    write_csv(module.IN_GATE, [{
        "final_status": "PASS_V20_158_R2_AUTHORITATIVE_BASELINE_BINDING_REPAIR_READY_FOR_V20_159" if status_ok else "PARTIAL_PASS_V20_158_R2_BASELINE_BINDING_REPAIR_WITH_REMAINING_INSTABILITY",
        "v20_159_allowed": "TRUE" if status_ok else "FALSE",
        "binding_repair_improved_rank_stability": "TRUE",
        "official_ranking_mutated": "FALSE",
        "official_weight_change_created": "FALSE",
        "performance_claim_created": "FALSE",
    }])


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"
        if "bound_reduced_shadow_ranking_simulation_created" in row:
            assert row["bound_reduced_shadow_ranking_simulation_created"] == "TRUE"
        if "shadow_review_scope" in row:
            assert row["shadow_review_scope"] == "RESEARCH_ONLY_LIMITED_CONSERVATIVE_BOUND_TO_AUTHORITATIVE_BASELINE"


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_159_BOUND_SHADOW_OPERATOR_REVIEW"


def test_blocked_wrong_r2_status_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        write_minimal_inputs(module, status_ok=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_159_BOUND_SHADOW_OPERATOR_REVIEW"


def test_temp_operator_review_packet_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        write_minimal_inputs(module)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        packet = read_csv(module.OUT_PACKET)[0]
        options = read_csv(module.OUT_OPTIONS)
        assert gate["final_status"] == "PASS_V20_159_BOUND_SHADOW_OPERATOR_REVIEW_PACKET_AWAITING_OPERATOR_INPUT"
        assert packet["operator_input_required"] == "TRUE"
        assert packet["selected_operator_option"] == "AWAITING_EXPLICIT_OPERATOR_REVIEW"
        assert {row["operator_option"] for row in options} == OPTIONS


def test_bound_reduced_shadow_simulation_operator_review() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.158-R2 outputs were mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_159_BOUND_SHADOW_OPERATOR_REVIEW_PACKET_AWAITING_OPERATOR_INPUT",
        "PARTIAL_PASS_V20_159_BOUND_SHADOW_REVIEW_REQUIRES_MORE_FORWARD_OUTCOMES",
        "WARN_V20_159_BOUND_SHADOW_STILL_TOO_UNSTABLE_FOR_OPERATOR_APPROVAL",
    ])
    for expected in [
        "V20_158_R2_GATE_CONSUMED=TRUE",
        "V20_159_ALLOWED_FROM_R2=TRUE",
        "BINDING_REPAIR_IMPROVED_RANK_STABILITY=TRUE",
        "OPERATOR_INPUT_REQUIRED=TRUE",
        "SELECTED_OPERATOR_OPTION=AWAITING_EXPLICIT_OPERATOR_REVIEW",
        "SHADOW_WEIGHT_EXPANSION_ALLOWED=FALSE",
        "OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "OFFICIAL_WEIGHTS_MUTATED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "REAL_BOOK_ACTION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_ACTION_CREATED=FALSE",
        "PERFORMANCE_CLAIM_CREATED=FALSE",
        "OUTCOMES_FABRICATED=0",
        "BENCHMARKS_FABRICATED=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_TRUE_COUNT=0",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    packet = read_csv(OUT_PACKET)
    review = read_csv(OUT_REVIEW)
    options = read_csv(OUT_OPTIONS)
    gate = read_csv(OUT_GATE)
    safety = read_csv(OUT_SAFETY)
    assert packet and review and options and gate and safety
    assert REVIEW_COLUMNS.issubset(review[0].keys()), REVIEW_COLUMNS - set(review[0].keys())
    assert {row["operator_option"] for row in options} == OPTIONS
    assert packet[0]["operator_input_required"] == "TRUE"
    assert packet[0]["selected_operator_option"] == "AWAITING_EXPLICIT_OPERATOR_REVIEW"
    assert gate[0]["selected_operator_option"] == "AWAITING_EXPLICIT_OPERATOR_REVIEW"
    assert gate[0]["official_weight_change_allowed"] == "FALSE"
    for rows in [packet, review, options, gate, safety]:
        assert_safety(rows)


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_wrong_r2_status_case()
    test_temp_operator_review_packet_case()
    test_bound_reduced_shadow_simulation_operator_review()
    print("PASS_V20_159_BOUND_REDUCED_SHADOW_SIMULATION_OPERATOR_REVIEW_TESTS")
