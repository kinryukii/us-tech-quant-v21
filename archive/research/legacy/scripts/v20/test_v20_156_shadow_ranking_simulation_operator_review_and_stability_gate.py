#!/usr/bin/env python
"""Tests for V20.156 shadow ranking simulation operator review gate."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_156_shadow_ranking_simulation_operator_review_and_stability_gate.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_REVIEW = FACTORS / "V20_156_SHADOW_RANKING_STABILITY_REVIEW.csv"
OUT_OPERATOR = FACTORS / "V20_156_SHADOW_RANKING_OPERATOR_REVIEW_PACKET.csv"
OUT_GUARDRAIL = FACTORS / "V20_156_SHADOW_RANKING_IMPACT_GUARDRAIL_AUDIT.csv"
OUT_LOW_CONF = FACTORS / "V20_156_SHADOW_RANKING_LOW_CONFIDENCE_AUDIT.csv"
OUT_GATE = FACTORS / "V20_156_SHADOW_RANKING_NEXT_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_156_SHADOW_RANKING_SIMULATION_OPERATOR_REVIEW_AND_STABILITY_GATE_REPORT.md"
OUTPUTS = [OUT_REVIEW, OUT_OPERATOR, OUT_GUARDRAIL, OUT_LOW_CONF, OUT_GATE, OUT_REPORT]

REVIEW_COLUMNS = {
    "baseline_candidate_count",
    "shadow_candidate_count",
    "proposal_row_count",
    "low_confidence_proposal_count",
    "top20_overlap_count",
    "entered_top20_count",
    "exited_top20_count",
    "top20_turnover_rate",
    "max_absolute_rank_delta",
    "average_absolute_rank_delta",
    "affected_ticker_count",
    "score_recomputation_performed",
    "rank_impact_proxy_used",
    "rank_impact_severity",
    "stability_review_result",
    "operator_review_required",
    "allow_continued_shadow_research",
    "allow_shadow_weight_expansion",
    "allow_official_weight_change",
    "required_next_action",
}
OPTIONS = {
    "APPROVE_CONTINUED_SHADOW_RESEARCH_ONLY",
    "REQUEST_SHADOW_WEIGHT_DELTA_REDUCTION",
    "REQUEST_MORE_FORWARD_OUTCOMES_BEFORE_EXPANSION",
    "REJECT_SHADOW_DYNAMIC_WEIGHT_PATH_FOR_NOW",
}
SAFETY_FALSE_FIELDS = [
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "official_weight_change_created",
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
        FACTORS / "V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION.csv",
        FACTORS / "V20_155_SHADOW_VS_BASELINE_RANK_DELTA.csv",
        FACTORS / "V20_155_SHADOW_RANKING_SIMULATION_GATE.csv",
        FACTORS / "V20_155_SHADOW_RANKING_SOURCE_AUDIT.csv",
        FACTORS / "V20_155_SHADOW_RANKING_SAFETY_AUDIT.csv",
        FACTORS / "V20_155_SHADOW_RANKING_LIMITATION_AUDIT.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_156_shadow_ranking_simulation_operator_review_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.FACTORS = temp / "factors"
    module.READ_CENTER = temp / "read_center"
    module.IN_SIM = module.FACTORS / "V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION.csv"
    module.IN_DELTA = module.FACTORS / "V20_155_SHADOW_VS_BASELINE_RANK_DELTA.csv"
    module.IN_GATE = module.FACTORS / "V20_155_SHADOW_RANKING_SIMULATION_GATE.csv"
    module.IN_SOURCE = module.FACTORS / "V20_155_SHADOW_RANKING_SOURCE_AUDIT.csv"
    module.IN_SAFETY = module.FACTORS / "V20_155_SHADOW_RANKING_SAFETY_AUDIT.csv"
    module.IN_LIMITATION = module.FACTORS / "V20_155_SHADOW_RANKING_LIMITATION_AUDIT.csv"
    module.OUT_REVIEW = module.FACTORS / "V20_156_SHADOW_RANKING_STABILITY_REVIEW.csv"
    module.OUT_OPERATOR = module.FACTORS / "V20_156_SHADOW_RANKING_OPERATOR_REVIEW_PACKET.csv"
    module.OUT_GUARDRAIL = module.FACTORS / "V20_156_SHADOW_RANKING_IMPACT_GUARDRAIL_AUDIT.csv"
    module.OUT_LOW_CONF = module.FACTORS / "V20_156_SHADOW_RANKING_LOW_CONFIDENCE_AUDIT.csv"
    module.OUT_GATE = module.FACTORS / "V20_156_SHADOW_RANKING_NEXT_GATE.csv"
    module.REPORT = module.READ_CENTER / "V20_156_SHADOW_RANKING_SIMULATION_OPERATOR_REVIEW_AND_STABILITY_GATE_REPORT.md"


def copy_inputs(temp: Path) -> None:
    (temp / "factors").mkdir(parents=True, exist_ok=True)
    for filename in [
        "V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION.csv",
        "V20_155_SHADOW_VS_BASELINE_RANK_DELTA.csv",
        "V20_155_SHADOW_RANKING_SIMULATION_GATE.csv",
        "V20_155_SHADOW_RANKING_SOURCE_AUDIT.csv",
        "V20_155_SHADOW_RANKING_SAFETY_AUDIT.csv",
        "V20_155_SHADOW_RANKING_LIMITATION_AUDIT.csv",
    ]:
        shutil.copy2(FACTORS / filename, temp / "factors" / filename)


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"
        if "shadow_weight_proposal_created" in row:
            assert row["shadow_weight_proposal_created"] == "TRUE"
        if "shadow_ranking_simulation_created" in row:
            assert row["shadow_ranking_simulation_created"] == "TRUE"
        if "shadow_review_scope" in row:
            assert row["shadow_review_scope"] == "RESEARCH_ONLY_LIMITED"


def write_minimal_inputs(module, low_conf: bool = False, unstable: bool = False) -> None:
    conf = "LIMITED" if low_conf else "MEDIUM"
    rank_delta = "30" if unstable else "0"
    write_csv(module.IN_SIM, [{
        "ticker": "AAA",
        "proposal_confidence_level": conf,
        "evidence_quality": "LIMITED" if low_conf else "HIGH",
        "rank_delta": rank_delta,
        "score_delta": "0.01",
    }])
    write_csv(module.IN_DELTA, [{
        "baseline_candidate_count": "20",
        "shadow_candidate_count": "20",
        "proposal_row_count": "1",
        "low_confidence_proposal_count": "1" if low_conf else "0",
        "top20_overlap_count": "20" if not unstable else "10",
        "entered_top20_count": "0" if not unstable else "5",
        "exited_top20_count": "0" if not unstable else "5",
        "max_absolute_rank_delta": "0" if not unstable else "30",
        "average_absolute_rank_delta": "0.0" if not unstable else "10.0",
        "affected_ticker_count": "1",
    }])
    write_csv(module.IN_GATE, [{
        "final_status": "PASS_V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION_READY_FOR_V20_156",
        "v20_156_shadow_review_allowed": "TRUE",
        "score_recomputation_performed": "TRUE",
        "rank_impact_proxy_used": "FALSE",
        "no_official_ranking_mutated": "TRUE",
        "no_official_weights_mutated": "TRUE",
        "no_official_recommendation_created": "TRUE",
        "no_real_book_action_created": "TRUE",
        "no_trade_action_created": "TRUE",
        "no_broker_action_created": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
    }])
    write_csv(module.IN_SOURCE, [{"source_audit_id": "S1"}])
    write_csv(module.IN_SAFETY, [{"safety_check_id": "A1"}])
    write_csv(module.IN_LIMITATION, [{"limitation_id": "L1"}])


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        assert gate["final_status"] == "BLOCKED_V20_156_SHADOW_RANKING_STABILITY_REVIEW"


def test_temp_stable_review_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        write_minimal_inputs(module, low_conf=False, unstable=False)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        review = read_csv(module.OUT_REVIEW)[0]
        options = read_csv(module.OUT_OPERATOR)
        assert gate["final_status"] == "PASS_V20_156_SHADOW_RANKING_STABILITY_REVIEW_READY_FOR_OPERATOR_INPUT"
        assert review["allow_continued_shadow_research"] == "TRUE"
        assert review["allow_shadow_weight_expansion"] == "TRUE"
        assert review["allow_official_weight_change"] == "FALSE"
        assert {row["operator_option"] for row in options} == OPTIONS


def test_temp_unstable_review_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        write_minimal_inputs(module, low_conf=True, unstable=True)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        review = read_csv(module.OUT_REVIEW)[0]
        assert gate["final_status"] == "WARN_V20_156_SHADOW_RANKING_IMPACT_TOO_UNSTABLE_FOR_EXPANSION"
        assert gate["confidence_risk"] == "HIGH"
        assert gate["rank_churn_risk"] == "HIGH"
        assert gate["rank_instability_risk"] == "HIGH"
        assert gate["outlier_rank_impact_risk"] == "HIGH"
        assert review["allow_shadow_weight_expansion"] == "FALSE"


def test_shadow_ranking_simulation_operator_review_and_stability_gate() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.155 outputs were mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_156_SHADOW_RANKING_STABILITY_REVIEW_READY_FOR_OPERATOR_INPUT",
        "PARTIAL_PASS_V20_156_SHADOW_RANKING_STABILITY_REVIEW_REQUIRES_DELTA_REDUCTION",
        "WARN_V20_156_SHADOW_RANKING_IMPACT_TOO_UNSTABLE_FOR_EXPANSION",
    ])
    for expected in [
        "V20_155_GATE_CONSUMED=TRUE",
        "V20_155_ALLOWED_FOR_V20_156=TRUE",
        "ALLOW_OFFICIAL_WEIGHT_CHANGE=FALSE",
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
    review = read_csv(OUT_REVIEW)
    operator = read_csv(OUT_OPERATOR)
    guardrail = read_csv(OUT_GUARDRAIL)
    low_conf = read_csv(OUT_LOW_CONF)
    gate = read_csv(OUT_GATE)
    assert review, "review output must not be empty"
    assert operator, "operator packet must not be empty"
    assert guardrail, "guardrail audit must not be empty"
    assert low_conf, "low-confidence audit must not be empty for current limited proposals"
    assert REVIEW_COLUMNS.issubset(review[0].keys()), REVIEW_COLUMNS - set(review[0].keys())
    assert {row["operator_option"] for row in operator} == OPTIONS
    assert gate[0]["allow_official_weight_change"] == "FALSE"
    assert review[0]["allow_official_weight_change"] == "FALSE"
    assert gate[0]["no_official_ranking_mutated"] == "TRUE"
    assert gate[0]["no_official_weights_mutated"] == "TRUE"
    for rows in [review, operator, guardrail, low_conf, gate]:
        assert_safety(rows)


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_temp_stable_review_case()
    test_temp_unstable_review_case()
    test_shadow_ranking_simulation_operator_review_and_stability_gate()
    print("PASS_V20_156_SHADOW_RANKING_SIMULATION_OPERATOR_REVIEW_AND_STABILITY_GATE_TESTS")
