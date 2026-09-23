#!/usr/bin/env python
"""Tests for V20.166 DATA_TRUST gate-only policy and ranking simulation."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_166_data_trust_gate_only_policy_and_ranking_simulation.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
FACTORS = ROOT / "outputs" / "v20" / "factors"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_POLICY = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_POLICY.csv"
OUT_WEIGHT = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_WEIGHT_SIMULATION.csv"
OUT_ELIGIBILITY = FACTORS / "V20_166_DATA_TRUST_RANKING_ELIGIBILITY_AUDIT.csv"
OUT_BACKLOG = FACTORS / "V20_166_DATA_TRUST_FAILED_REPAIR_BACKLOG.csv"
OUT_RANKING = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION.csv"
OUT_DELTA = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_RANK_DELTA.csv"
OUT_SAFETY = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_SAFETY_AUDIT.csv"
OUT_GATE = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_NEXT_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_166_DATA_TRUST_GATE_ONLY_POLICY_AND_RANKING_SIMULATION_REPORT.md"
OUTPUTS = [OUT_POLICY, OUT_WEIGHT, OUT_ELIGIBILITY, OUT_BACKLOG, OUT_RANKING, OUT_DELTA, OUT_SAFETY, OUT_GATE, OUT_REPORT]

POLICY_COLUMNS = {
    "factor_family",
    "current_research_base_weight",
    "proposed_scoring_weight",
    "proposed_role",
    "scoring_weight_removed",
    "redistributed_to_other_scoring_families",
    "data_trust_pass_required_for_ranking",
    "data_trust_failed_rows_excluded_from_ranking",
    "data_trust_failed_rows_repair_backlog_created",
    "research_only",
    "official_weight_change_created",
    "weight_mutated",
}
ELIGIBILITY_COLUMNS = {
    "ticker",
    "baseline_rank",
    "baseline_score",
    "data_trust_status",
    "data_trust_pass",
    "ranking_eligible_after_gate",
    "excluded_from_ranking_due_to_data_trust",
    "exclusion_reason",
    "repair_required",
    "repair_priority",
    "data_trust_failure_category",
    "source_artifact",
    "source_field",
    "recommended_repair_action",
}
BACKLOG_COLUMNS = {
    "ticker",
    "data_trust_failure_category",
    "failure_reason",
    "missing_or_invalid_field",
    "source_artifact",
    "can_repair_from_existing_artifacts",
    "requires_fresh_data_refresh",
    "requires_schema_mapping_repair",
    "requires_pit_safety_repair",
    "requires_source_quality_repair",
    "recommended_repair_stage",
    "repair_priority",
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
        CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv",
        CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_166_data_trust_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.CONSOLIDATION = temp / "consolidation"
    module.FACTORS = temp / "factors"
    module.READ_CENTER = temp / "read_center"
    module.WEIGHTS = module.CONSOLIDATION / module.WEIGHTS.name
    module.BASELINE = module.CONSOLIDATION / module.BASELINE.name
    status_source = module.CONSOLIDATION / "V20_TEMP_DATA_TRUST_TICKER_STATUS.csv"
    module.DATA_TRUST_CANDIDATES = [status_source]
    module.OUT_POLICY = module.FACTORS / module.OUT_POLICY.name
    module.OUT_WEIGHT = module.FACTORS / module.OUT_WEIGHT.name
    module.OUT_ELIGIBILITY = module.FACTORS / module.OUT_ELIGIBILITY.name
    module.OUT_BACKLOG = module.FACTORS / module.OUT_BACKLOG.name
    module.OUT_RANKING = module.FACTORS / module.OUT_RANKING.name
    module.OUT_DELTA = module.FACTORS / module.OUT_DELTA.name
    module.OUT_SAFETY = module.FACTORS / module.OUT_SAFETY.name
    module.OUT_GATE = module.FACTORS / module.OUT_GATE.name
    module.REPORT = module.READ_CENTER / module.REPORT.name


def write_minimal_inputs(module, include_status: bool = True) -> None:
    write_csv(module.WEIGHTS, [
        {"factor_family": "FUNDAMENTAL", "active_research_base_weight": "0.20"},
        {"factor_family": "TECHNICAL", "active_research_base_weight": "0.25"},
        {"factor_family": "STRATEGY", "active_research_base_weight": "0.20"},
        {"factor_family": "RISK", "active_research_base_weight": "0.15"},
        {"factor_family": "MARKET_REGIME", "active_research_base_weight": "0.10"},
        {"factor_family": "DATA_TRUST", "active_research_base_weight": "0.10"},
    ])
    write_csv(module.BASELINE, [
        {"ticker": "AAA", "official_current_rank": "1", "official_current_score": "1.0"},
        {"ticker": "BBB", "official_current_rank": "2", "official_current_score": "2.0"},
        {"ticker": "CCC", "official_current_rank": "3", "official_current_score": "3.0"},
    ])
    if include_status:
        write_csv(module.DATA_TRUST_CANDIDATES[0], [
            {"ticker": "AAA", "data_trust_status": "PASS"},
            {"ticker": "BBB", "data_trust_status": "FAIL"},
            {"ticker": "CCC", "data_trust_status": "PASS"},
        ])


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        assert row.get("research_only", "TRUE") == "TRUE"
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_166_DATA_TRUST_GATE_ONLY_POLICY"


def test_temp_explicit_status_gate_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module, include_status=True)
        assert module.main() == 0
        policy = read_csv(module.OUT_POLICY)
        eligibility = read_csv(module.OUT_ELIGIBILITY)
        backlog = read_csv(module.OUT_BACKLOG)
        ranking = read_csv(module.OUT_RANKING)
        summary = read_csv(module.OUT_DELTA)[0]
        gate = read_csv(module.OUT_GATE)[0]
        assert len(policy) == 6
        dt = next(row for row in policy if row["factor_family"] == "DATA_TRUST")
        assert dt["proposed_scoring_weight"] == "0.0000000000"
        assert dt["proposed_role"] == "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
        assert next(row for row in eligibility if row["ticker"] == "BBB")["ranking_eligible_after_gate"] == "FALSE"
        assert len(backlog) == 1
        assert {row["ticker"] for row in ranking} == {"AAA", "CCC"}
        assert summary["data_trust_pass_count"] == "2"
        assert summary["data_trust_fail_count"] == "1"
        assert summary["data_trust_unknown_count"] == "0"
        assert gate["final_status"] == "PARTIAL_PASS_V20_166_DATA_TRUST_GATE_ONLY_POLICY_WITH_REPAIR_BACKLOG_READY_FOR_OPERATOR_REVIEW"


def test_temp_unknown_status_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module, include_status=False)
        assert module.main() == 0
        summary = read_csv(module.OUT_DELTA)[0]
        ranking = read_csv(module.OUT_RANKING)
        gate = read_csv(module.OUT_GATE)[0]
        assert summary["data_trust_unknown_count"] == "3"
        assert summary["ranking_candidate_count_after_data_trust_gate"] == "0"
        assert ranking == []
        assert gate["final_status"] == "WARN_V20_166_DATA_TRUST_GATE_ONLY_POLICY_INSUFFICIENT_DATA_TRUST_STATUS"


def test_data_trust_gate_only_policy_and_ranking_simulation() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream base weight registry or official ranking was mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_166_DATA_TRUST_GATE_ONLY_POLICY_READY_FOR_OPERATOR_REVIEW",
        "PARTIAL_PASS_V20_166_DATA_TRUST_GATE_ONLY_POLICY_WITH_REPAIR_BACKLOG_READY_FOR_OPERATOR_REVIEW",
        "WARN_V20_166_DATA_TRUST_GATE_ONLY_POLICY_INSUFFICIENT_DATA_TRUST_STATUS",
    ])
    for expected in [
        "DATA_TRUST_ROLE=GATE_ONLY_AND_REPAIR_DIAGNOSTIC",
        "DATA_TRUST_SCORING_WEIGHT=0.0000000000",
        "DATA_TRUST_PASS_REQUIRED_FOR_RANKING=TRUE",
        "DATA_TRUST_FAILED_ROWS_EXCLUDED_FROM_RANKING=TRUE",
        "DATA_TRUST_FAILED_ROWS_REPAIR_BACKLOG_CREATED=TRUE",
        "RESEARCH_ONLY=TRUE",
        "FORMAL_ACTIVATION_ALLOWED=FALSE",
        "PROMOTION_READY=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "OFFICIAL_WEIGHT_CHANGE_CREATED=FALSE",
        "OFFICIAL_WEIGHT_REGISTRY_MUTATED=FALSE",
        "WEIGHT_MUTATED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "REAL_BOOK_ACTION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "PERFORMANCE_CLAIM_CREATED=FALSE",
        "SHADOW_WEIGHT_EXPANSION_ALLOWED=FALSE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    policy = read_csv(OUT_POLICY)
    weight = read_csv(OUT_WEIGHT)
    eligibility = read_csv(OUT_ELIGIBILITY)
    backlog = read_csv(OUT_BACKLOG)
    summary = read_csv(OUT_DELTA)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    assert policy and weight and eligibility and summary and safety and gate
    assert POLICY_COLUMNS.issubset(policy[0].keys()), POLICY_COLUMNS - set(policy[0].keys())
    assert ELIGIBILITY_COLUMNS.issubset(eligibility[0].keys()), ELIGIBILITY_COLUMNS - set(eligibility[0].keys())
    if backlog:
        assert BACKLOG_COLUMNS.issubset(backlog[0].keys()), BACKLOG_COLUMNS - set(backlog[0].keys())
    dt = next(row for row in policy if row["factor_family"] == "DATA_TRUST")
    assert dt["proposed_scoring_weight"] == "0.0000000000"
    assert dt["scoring_weight_removed"] == "TRUE"
    assert gate[0]["data_trust_weight_after"] == "0.0000000000"
    assert gate[0]["official_weight_registry_mutated"] == "FALSE"
    assert all(row["safety_passed"] == "TRUE" for row in safety)
    for rows in [policy, weight, eligibility, backlog, summary, safety, gate]:
        assert_safety(rows)


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_temp_explicit_status_gate_case()
    test_temp_unknown_status_case()
    test_data_trust_gate_only_policy_and_ranking_simulation()
    print("PASS_V20_166_DATA_TRUST_GATE_ONLY_POLICY_AND_RANKING_SIMULATION_TESTS")
