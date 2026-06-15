#!/usr/bin/env python
"""Tests for V20.165 capped bound shadow operator review."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_165_capped_bound_shadow_operator_review.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_PACKET = FACTORS / "V20_165_CAPPED_BOUND_SHADOW_OPERATOR_REVIEW_PACKET.csv"
OUT_REVIEW = FACTORS / "V20_165_CAPPED_BOUND_SHADOW_STABILITY_REVIEW.csv"
OUT_OPTIONS = FACTORS / "V20_165_CAPPED_BOUND_SHADOW_OPERATOR_OPTIONS.csv"
OUT_GATE = FACTORS / "V20_165_CAPPED_BOUND_SHADOW_NEXT_GATE.csv"
OUT_SAFETY = FACTORS / "V20_165_CAPPED_BOUND_SHADOW_SAFETY_AUDIT.csv"
OUT_REPORT = READ_CENTER / "V20_165_CAPPED_BOUND_SHADOW_OPERATOR_REVIEW_REPORT.md"
OUTPUTS = [OUT_PACKET, OUT_REVIEW, OUT_OPTIONS, OUT_GATE, OUT_SAFETY, OUT_REPORT]

EXPECTED_OPTIONS = {
    "APPROVE_CONTINUED_CAPPED_BOUND_SHADOW_RESEARCH_ONLY",
    "REQUEST_MORE_FORWARD_OUTCOMES_BEFORE_ANY_EXPANSION",
    "REQUEST_MORE_STABILITY_RETESTS",
    "REQUEST_SCORE_CAP_PARAMETER_REVIEW",
    "REJECT_CAPPED_SHADOW_DYNAMIC_WEIGHT_PATH_FOR_NOW",
}
REVIEW_COLUMNS = {
    "retest_run_count",
    "stability_pass_count",
    "stability_warn_count",
    "stability_fail_count",
    "max_capped_top20_turnover_rate",
    "max_capped_rank_delta",
    "outlier_ticker_count_max",
    "factor_impact_concentration_max",
    "all_capped_guardrails_passed",
    "stable_enough_for_continued_capped_shadow_research",
    "stable_enough_for_shadow_expansion",
    "stable_enough_for_official_weight_change",
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
        FACTORS / "V20_164_CAPPED_BOUND_SHADOW_STABILITY_RETEST.csv",
        FACTORS / "V20_164_CAPPED_BOUND_SHADOW_STABILITY_SUMMARY.csv",
        FACTORS / "V20_164_CAPPED_BOUND_SHADOW_GUARDRAIL_AUDIT.csv",
        FACTORS / "V20_164_CAPPED_BOUND_SHADOW_OUTLIER_RETEST_AUDIT.csv",
        FACTORS / "V20_164_CAPPED_BOUND_SHADOW_NEXT_GATE.csv",
        FACTORS / "V20_164_CAPPED_BOUND_SHADOW_SAFETY_AUDIT.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_165_operator_review_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.FACTORS = temp / "factors"
    module.READ_CENTER = temp / "read_center"
    for name in ["V164_RETEST", "V164_SUMMARY", "V164_GUARDRAIL", "V164_OUTLIER", "V164_GATE", "V164_SAFETY"]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.OUT_PACKET = module.FACTORS / module.OUT_PACKET.name
    module.OUT_REVIEW = module.FACTORS / module.OUT_REVIEW.name
    module.OUT_OPTIONS = module.FACTORS / module.OUT_OPTIONS.name
    module.OUT_GATE = module.FACTORS / module.OUT_GATE.name
    module.OUT_SAFETY = module.FACTORS / module.OUT_SAFETY.name
    module.REPORT = module.READ_CENTER / module.REPORT.name


def write_minimal_inputs(module, status_ok: bool = True) -> None:
    status = "PASS_V20_164_CAPPED_BOUND_SHADOW_STABILITY_RETEST_READY_FOR_V20_165" if status_ok else "WARN"
    write_csv(module.V164_RETEST, [{"retest_run_id": "R"}])
    write_csv(module.V164_SUMMARY, [{
        "retest_run_count": "3",
        "stability_pass_count": "3",
        "stability_warn_count": "0",
        "stability_fail_count": "0",
        "max_capped_top20_turnover_rate": "0.0000000000",
        "max_capped_rank_delta": "4",
        "outlier_ticker_count_max": "0",
        "factor_impact_concentration_max": "0.0000000000",
        "stable_enough_for_continued_capped_shadow_research": "TRUE",
        "stable_enough_for_shadow_expansion": "FALSE",
        "stable_enough_for_official_weight_change": "FALSE",
    }])
    write_csv(module.V164_GUARDRAIL, [{"guardrail_id": "G"}])
    write_csv(module.V164_OUTLIER, [{"ticker": "AAA"}])
    write_csv(module.V164_GATE, [{
        "final_status": status,
        "all_capped_guardrails_passed": "TRUE",
        "v20_165_operator_review_allowed": "TRUE",
        "shadow_weight_expansion_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
    }])
    write_csv(module.V164_SAFETY, [{"safety_check_id": "S"}])


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"
        if "capped_bound_shadow_operator_review_created" in row:
            assert row["capped_bound_shadow_operator_review_created"] == "TRUE"
        if "shadow_review_scope" in row:
            assert row["shadow_review_scope"] == "RESEARCH_ONLY_LIMITED_CONSERVATIVE_BOUND_TO_AUTHORITATIVE_BASELINE_WITH_CAPS"


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_165_CAPPED_BOUND_SHADOW_OPERATOR_REVIEW"


def test_blocked_wrong_v164_status_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module, status_ok=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_165_CAPPED_BOUND_SHADOW_OPERATOR_REVIEW"


def test_temp_operator_packet_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module)
        assert module.main() == 0
        review = read_csv(module.OUT_REVIEW)[0]
        packet = read_csv(module.OUT_PACKET)[0]
        options = read_csv(module.OUT_OPTIONS)
        gate = read_csv(module.OUT_GATE)[0]
        assert review["operator_input_required"] == "TRUE"
        assert review["selected_operator_option"] == "AWAITING_EXPLICIT_OPERATOR_REVIEW"
        assert packet["default_decision"] == "AWAITING_EXPLICIT_OPERATOR_REVIEW"
        assert {row["operator_option"] for row in options} == EXPECTED_OPTIONS
        assert all(row["selected_operator_option"] == "AWAITING_EXPLICIT_OPERATOR_REVIEW" for row in options)
        assert gate["final_status"] == "PASS_V20_165_CAPPED_BOUND_SHADOW_OPERATOR_REVIEW_AWAITING_OPERATOR_INPUT"


def test_capped_bound_shadow_operator_review() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.164 outputs were mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_165_CAPPED_BOUND_SHADOW_OPERATOR_REVIEW_AWAITING_OPERATOR_INPUT",
        "PARTIAL_PASS_V20_165_CAPPED_BOUND_SHADOW_REVIEW_REQUIRES_MORE_FORWARD_OUTCOMES",
        "WARN_V20_165_CAPPED_BOUND_SHADOW_NOT_READY_FOR_OPERATOR_REVIEW",
    ])
    for expected in [
        "V20_164_GATE_CONSUMED=TRUE",
        "V20_164_STATUS=PASS_V20_164_CAPPED_BOUND_SHADOW_STABILITY_RETEST_READY_FOR_V20_165",
        "ALL_CAPPED_GUARDRAILS_PASSED=TRUE",
        "V20_165_OPERATOR_REVIEW_ALLOWED=TRUE",
        "OPERATOR_REVIEW_REQUIRED=TRUE",
        "OPERATOR_INPUT_REQUIRED=TRUE",
        "SELECTED_OPERATOR_OPTION=AWAITING_EXPLICIT_OPERATOR_REVIEW",
        "SHADOW_WEIGHT_EXPANSION_ALLOWED=FALSE",
        "OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE",
        "FORMAL_ACTIVATION_ALLOWED=FALSE",
        "PROMOTION_READY=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "OFFICIAL_WEIGHTS_MUTATED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "REAL_BOOK_ACTION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_ACTION_CREATED=FALSE",
        "OUTCOMES_FABRICATED=0",
        "BENCHMARKS_FABRICATED=0",
        "PERFORMANCE_CLAIM_CREATED=FALSE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
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
    assert review[0]["operator_input_required"] == "TRUE"
    assert review[0]["selected_operator_option"] == "AWAITING_EXPLICIT_OPERATOR_REVIEW"
    assert review[0]["stable_enough_for_shadow_expansion"] == "FALSE"
    assert review[0]["stable_enough_for_official_weight_change"] == "FALSE"
    assert {row["operator_option"] for row in options} == EXPECTED_OPTIONS
    assert gate[0]["shadow_weight_expansion_allowed"] == "FALSE"
    assert gate[0]["official_weight_change_allowed"] == "FALSE"
    assert all(row["safety_passed"] == "TRUE" for row in safety)
    for rows in [packet, review, options, gate, safety]:
        assert_safety(rows)


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_wrong_v164_status_case()
    test_temp_operator_packet_case()
    test_capped_bound_shadow_operator_review()
    print("PASS_V20_165_CAPPED_BOUND_SHADOW_OPERATOR_REVIEW_TESTS")
