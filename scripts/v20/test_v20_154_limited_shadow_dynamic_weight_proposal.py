#!/usr/bin/env python
"""Tests for V20.154 limited shadow dynamic weight proposal."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_154_limited_shadow_dynamic_weight_proposal.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_PROPOSAL = FACTORS / "V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv"
OUT_GATE = FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_GATE.csv"
OUT_SOURCE = FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_SOURCE_AUDIT.csv"
OUT_SAFETY = FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_SAFETY_AUDIT.csv"
OUT_BLOCKED = FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_BLOCKED_OFFICIAL_AUDIT.csv"
OUT_REPORT = READ_CENTER / "V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL_REPORT.md"
OUTPUTS = [OUT_PROPOSAL, OUT_GATE, OUT_SOURCE, OUT_SAFETY, OUT_BLOCKED, OUT_REPORT]

PROPOSAL_COLUMNS = {
    "factor_family",
    "factor_name",
    "evidence_source",
    "current_research_weight",
    "shadow_proposed_weight",
    "proposed_delta",
    "max_allowed_delta",
    "evidence_quality",
    "contribution_stability",
    "as_of_sample_count",
    "forward_observation_count",
    "outcome_available_count",
    "benchmark_available_count",
    "pending_outcome_count",
    "repair_source",
    "confidence_level",
    "proposal_reason",
    "usable_for_shadow_weight_proposal",
    "usable_for_official_weight_change",
    "official_weight_change_blocked_reason",
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
        FACTORS / "V20_153_R2_FACTOR_ABLATION_EXISTING_EVIDENCE_BRIDGE_REPAIR.csv",
        FACTORS / "V20_153_R2_FACTOR_ABLATION_BRIDGE_SOURCE_AUDIT.csv",
        FACTORS / "V20_153_R2_FACTOR_ABLATION_REPAIRED_MATRIX.csv",
        FACTORS / "V20_153_R2_FACTOR_ABLATION_REMAINING_BLOCKERS.csv",
        FACTORS / "V20_153_R2_FACTOR_ABLATION_NEXT_GATE.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_154_limited_shadow_dynamic_weight_proposal_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.FACTORS = temp / "factors"
    module.CONSOLIDATION = temp / "consolidation"
    module.READ_CENTER = temp / "read_center"
    module.IN_REPAIR = module.FACTORS / "V20_153_R2_FACTOR_ABLATION_EXISTING_EVIDENCE_BRIDGE_REPAIR.csv"
    module.IN_SOURCE = module.FACTORS / "V20_153_R2_FACTOR_ABLATION_BRIDGE_SOURCE_AUDIT.csv"
    module.IN_MATRIX = module.FACTORS / "V20_153_R2_FACTOR_ABLATION_REPAIRED_MATRIX.csv"
    module.IN_BLOCKERS = module.FACTORS / "V20_153_R2_FACTOR_ABLATION_REMAINING_BLOCKERS.csv"
    module.IN_GATE = module.FACTORS / "V20_153_R2_FACTOR_ABLATION_NEXT_GATE.csv"
    module.BASE_WEIGHT_REGISTRY = module.CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
    module.OUT_PROPOSAL = module.FACTORS / "V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv"
    module.OUT_GATE = module.FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_GATE.csv"
    module.OUT_SOURCE_AUDIT = module.FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_SOURCE_AUDIT.csv"
    module.OUT_SAFETY_AUDIT = module.FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_SAFETY_AUDIT.csv"
    module.OUT_BLOCKED_OFFICIAL = module.FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_BLOCKED_OFFICIAL_AUDIT.csv"
    module.REPORT = module.READ_CENTER / "V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL_REPORT.md"


def copy_inputs(temp: Path) -> None:
    (temp / "factors").mkdir(parents=True, exist_ok=True)
    (temp / "consolidation").mkdir(parents=True, exist_ok=True)
    for filename in [
        "V20_153_R2_FACTOR_ABLATION_EXISTING_EVIDENCE_BRIDGE_REPAIR.csv",
        "V20_153_R2_FACTOR_ABLATION_BRIDGE_SOURCE_AUDIT.csv",
        "V20_153_R2_FACTOR_ABLATION_REPAIRED_MATRIX.csv",
        "V20_153_R2_FACTOR_ABLATION_REMAINING_BLOCKERS.csv",
        "V20_153_R2_FACTOR_ABLATION_NEXT_GATE.csv",
    ]:
        shutil.copy2(FACTORS / filename, temp / "factors" / filename)
    shutil.copy2(CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv", temp / "consolidation" / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv")


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"
        if "shadow_weight_proposal_created" in row:
            assert row["shadow_weight_proposal_created"] == "TRUE"
        if "shadow_weight_proposal_scope" in row:
            assert row["shadow_weight_proposal_scope"] == "RESEARCH_ONLY_LIMITED"


def write_minimal_inputs(module, official_true: bool = False) -> None:
    write_csv(module.IN_REPAIR, [{"bridge_repair_id": "R1"}])
    write_csv(module.IN_SOURCE, [{"source_audit_id": "S1"}])
    write_csv(module.IN_BLOCKERS, [{"remaining_blocker_id": "B1"}])
    write_csv(module.IN_GATE, [{"final_status": "PASS_V20_153_R2_FACTOR_ABLATION_BRIDGE_REPAIR_READY_FOR_V20_154"}])
    write_csv(module.IN_MATRIX, [{
        "factor_family": "RISK",
        "factor_name": "DOWNSIDE_RISK_EVIDENCE",
        "evidence_source": "source.csv",
        "as_of_sample_count": "4",
        "forward_observation_count": "3",
        "outcome_available_count": "24",
        "benchmark_available_count": "24",
        "pending_outcome_count": "0",
        "positive_contribution_count": "1",
        "negative_contribution_count": "8",
        "neutral_contribution_count": "0",
        "contribution_stability": "MEDIUM",
        "evidence_quality": "HIGH",
        "repair_source": "source.csv",
        "usable_for_shadow_weight_proposal": "TRUE",
        "usable_for_official_weight_change": "TRUE" if official_true else "FALSE",
    }])
    write_csv(module.BASE_WEIGHT_REGISTRY, [{"factor_family": "RISK", "active_research_base_weight": "0.15", "is_official_weight": "FALSE"}])


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        assert gate["final_status"] == "BLOCKED_V20_154_SHADOW_DYNAMIC_WEIGHT_PROPOSAL"


def test_blocked_official_eligibility_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        write_minimal_inputs(module, official_true=True)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        blocked = read_csv(module.OUT_BLOCKED_OFFICIAL)
        assert gate["final_status"] == "BLOCKED_V20_154_SHADOW_DYNAMIC_WEIGHT_PROPOSAL"
        assert gate["official_weight_change_eligible_input_count"] == "1"
        assert blocked and blocked[0]["official_weight_change_blocked_reason"] == "BLOCKED_INPUT_OFFICIAL_WEIGHT_CHANGE_ELIGIBILITY_TRUE"


def test_temp_limited_shadow_proposal_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        write_minimal_inputs(module)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        proposal = read_csv(module.OUT_PROPOSAL)
        assert gate["final_status"] == "PARTIAL_PASS_V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL_WITH_LOW_CONFIDENCE_READY_FOR_V20_155"
        assert proposal[0]["usable_for_shadow_weight_proposal"] == "TRUE"
        assert proposal[0]["usable_for_official_weight_change"] == "FALSE"
        assert float(proposal[0]["proposed_delta"]) < 0
        assert abs(float(proposal[0]["proposed_delta"])) <= float(proposal[0]["max_allowed_delta"])


def test_limited_shadow_dynamic_weight_proposal() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.153-R2 outputs were mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL_READY_FOR_V20_155",
        "PARTIAL_PASS_V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL_WITH_LOW_CONFIDENCE_READY_FOR_V20_155",
        "WARN_V20_154_NO_SHADOW_ELIGIBLE_FACTORS_FOUND",
    ])
    for expected in [
        "V20_153_R2_GATE_CONSUMED=TRUE",
        "V20_153_R2_ALLOWED_FOR_V20_154=TRUE",
        "OFFICIAL_WEIGHT_CHANGE_ELIGIBLE_INPUT_COUNT=0",
        "OFFICIAL_WEIGHT_CHANGE_CREATED=FALSE",
        "OFFICIAL_WEIGHTS_MUTATED=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "REAL_BOOK_ACTION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_ACTION_CREATED=FALSE",
        "OUTCOMES_FABRICATED=0",
        "BENCHMARKS_FABRICATED=0",
        "FACTOR_CONTRIBUTION_FABRICATED=0",
        "ELIGIBILITY_THRESHOLDS_LOWERED=FALSE",
        "PERFORMANCE_CLAIM_CREATED=FALSE",
        "SHADOW_WEIGHT_PROPOSAL_CREATED=TRUE",
        "SHADOW_WEIGHT_PROPOSAL_SCOPE=RESEARCH_ONLY_LIMITED",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_TRUE_COUNT=0",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    proposal = read_csv(OUT_PROPOSAL)
    gate = read_csv(OUT_GATE)
    source = read_csv(OUT_SOURCE)
    safety = read_csv(OUT_SAFETY)
    blocked = read_csv(OUT_BLOCKED)
    assert proposal, "proposal must not be empty for current R2 eligible rows"
    assert source, "source audit must not be empty"
    assert safety, "safety audit must not be empty"
    assert blocked, "blocked official audit must cover matrix rows"
    assert PROPOSAL_COLUMNS.issubset(proposal[0].keys()), PROPOSAL_COLUMNS - set(proposal[0].keys())
    assert all(row["usable_for_shadow_weight_proposal"] == "TRUE" for row in proposal)
    assert all(row["usable_for_official_weight_change"] == "FALSE" for row in proposal)
    assert all(row["confidence_level"] in {"LOW", "LIMITED", "MEDIUM"} for row in proposal)
    assert all(abs(float(row["proposed_delta"])) <= float(row["max_allowed_delta"]) + 1e-12 for row in proposal)
    assert gate[0]["official_weight_change_eligible_input_count"] == "0"
    assert int(gate[0]["proposal_row_count"]) == len(proposal)
    assert gate[0]["official_weight_change_created"] == "FALSE"
    for rows in [proposal, gate, source, safety, blocked]:
        assert_safety(rows)


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_official_eligibility_case()
    test_temp_limited_shadow_proposal_case()
    test_limited_shadow_dynamic_weight_proposal()
    print("PASS_V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL_TESTS")
