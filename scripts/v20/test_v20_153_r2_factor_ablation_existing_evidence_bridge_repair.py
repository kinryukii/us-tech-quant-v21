#!/usr/bin/env python
"""Tests for V20.153-R2 factor ablation existing-evidence bridge repair."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_153_r2_factor_ablation_existing_evidence_bridge_repair.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
BACKTEST = ROOT / "outputs" / "v20" / "backtest"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_REPAIR = FACTORS / "V20_153_R2_FACTOR_ABLATION_EXISTING_EVIDENCE_BRIDGE_REPAIR.csv"
OUT_SOURCE = FACTORS / "V20_153_R2_FACTOR_ABLATION_BRIDGE_SOURCE_AUDIT.csv"
OUT_MATRIX = FACTORS / "V20_153_R2_FACTOR_ABLATION_REPAIRED_MATRIX.csv"
OUT_BLOCKERS = FACTORS / "V20_153_R2_FACTOR_ABLATION_REMAINING_BLOCKERS.csv"
OUT_GATE = FACTORS / "V20_153_R2_FACTOR_ABLATION_NEXT_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_153_R2_FACTOR_ABLATION_EXISTING_EVIDENCE_BRIDGE_REPAIR_REPORT.md"
OUTPUTS = [OUT_REPAIR, OUT_SOURCE, OUT_MATRIX, OUT_BLOCKERS, OUT_GATE, OUT_REPORT]

REPAIRED_COLUMNS = {
    "factor_family",
    "factor_name",
    "evidence_source",
    "as_of_sample_count",
    "forward_observation_count",
    "outcome_available_count",
    "pending_outcome_count",
    "benchmark_available_count",
    "positive_contribution_count",
    "negative_contribution_count",
    "neutral_contribution_count",
    "contribution_stability",
    "regime_coverage",
    "window_coverage",
    "usable_for_shadow_weight_proposal",
    "usable_for_official_weight_change",
    "exclusion_reason",
    "evidence_quality",
    "repair_source",
    "repair_applied",
    "remaining_blocker_reason",
}
SAFETY_FALSE_FIELDS = [
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "official_weight_change_created",
    "shadow_weight_proposal_created",
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
        FACTORS / "V20_153_R1_FACTOR_ABLATION_INSUFFICIENCY_DIAGNOSTIC.csv",
        FACTORS / "V20_153_R1_FACTOR_ABLATION_BLOCKER_BREAKDOWN.csv",
        FACTORS / "V20_153_R1_FACTOR_ABLATION_REPAIR_PLAN.csv",
        FACTORS / "V20_153_R1_FACTOR_ABLATION_NEXT_GATE.csv",
        FACTORS / "V20_153_FACTOR_ABLATION_MATRIX.csv",
        FACTORS / "V20_153_FACTOR_ABLATION_GATE.csv",
        FACTORS / "V20_153_FACTOR_ABLATION_SOURCE_AUDIT.csv",
        FACTORS / "V20_153_FACTOR_ABLATION_ELIGIBILITY_AUDIT.csv",
        FACTORS / "V20_153_FACTOR_ABLATION_GAP_AUDIT.csv",
        BACKTEST / "V20_152_RANDOM_AS_OF_BACKTEST_CACHE.csv",
        BACKTEST / "V20_152_RANDOM_AS_OF_BACKTEST_CACHE_GATE.csv",
        BACKTEST / "V20_152_RANDOM_AS_OF_SOURCE_AUDIT.csv",
        BACKTEST / "V20_152_RANDOM_AS_OF_ELIGIBILITY_AUDIT.csv",
        BACKTEST / "V20_152_RANDOM_AS_OF_GAP_REPAIR_PLAN.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_153_r2_factor_ablation_existing_evidence_bridge_repair_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.FACTORS = temp / "factors"
    module.BACKTEST = temp / "backtest"
    module.EVIDENCE = temp / "evidence"
    module.CONSOLIDATION = temp / "consolidation"
    module.OPS = temp / "ops"
    module.READ_CENTER = temp / "read_center"
    module.R1_DIAGNOSTIC = module.FACTORS / "V20_153_R1_FACTOR_ABLATION_INSUFFICIENCY_DIAGNOSTIC.csv"
    module.R1_BREAKDOWN = module.FACTORS / "V20_153_R1_FACTOR_ABLATION_BLOCKER_BREAKDOWN.csv"
    module.R1_REPAIR = module.FACTORS / "V20_153_R1_FACTOR_ABLATION_REPAIR_PLAN.csv"
    module.R1_GATE = module.FACTORS / "V20_153_R1_FACTOR_ABLATION_NEXT_GATE.csv"
    module.V153_MATRIX = module.FACTORS / "V20_153_FACTOR_ABLATION_MATRIX.csv"
    module.V153_GATE = module.FACTORS / "V20_153_FACTOR_ABLATION_GATE.csv"
    module.V153_SOURCE = module.FACTORS / "V20_153_FACTOR_ABLATION_SOURCE_AUDIT.csv"
    module.V153_ELIGIBILITY = module.FACTORS / "V20_153_FACTOR_ABLATION_ELIGIBILITY_AUDIT.csv"
    module.V153_GAP = module.FACTORS / "V20_153_FACTOR_ABLATION_GAP_AUDIT.csv"
    module.V152_CACHE = module.BACKTEST / "V20_152_RANDOM_AS_OF_BACKTEST_CACHE.csv"
    module.V152_GATE = module.BACKTEST / "V20_152_RANDOM_AS_OF_BACKTEST_CACHE_GATE.csv"
    module.V152_SOURCE = module.BACKTEST / "V20_152_RANDOM_AS_OF_SOURCE_AUDIT.csv"
    module.V152_ELIGIBILITY = module.BACKTEST / "V20_152_RANDOM_AS_OF_ELIGIBILITY_AUDIT.csv"
    module.V152_GAP = module.BACKTEST / "V20_152_RANDOM_AS_OF_GAP_REPAIR_PLAN.csv"
    module.OUT_REPAIR = module.FACTORS / "V20_153_R2_FACTOR_ABLATION_EXISTING_EVIDENCE_BRIDGE_REPAIR.csv"
    module.OUT_SOURCE_AUDIT = module.FACTORS / "V20_153_R2_FACTOR_ABLATION_BRIDGE_SOURCE_AUDIT.csv"
    module.OUT_MATRIX = module.FACTORS / "V20_153_R2_FACTOR_ABLATION_REPAIRED_MATRIX.csv"
    module.OUT_BLOCKERS = module.FACTORS / "V20_153_R2_FACTOR_ABLATION_REMAINING_BLOCKERS.csv"
    module.OUT_GATE = module.FACTORS / "V20_153_R2_FACTOR_ABLATION_NEXT_GATE.csv"
    module.REPORT = module.READ_CENTER / "V20_153_R2_FACTOR_ABLATION_EXISTING_EVIDENCE_BRIDGE_REPAIR_REPORT.md"


def copy_inputs(temp: Path) -> None:
    (temp / "factors").mkdir(parents=True, exist_ok=True)
    (temp / "backtest").mkdir(parents=True, exist_ok=True)
    for filename in [
        "V20_153_R1_FACTOR_ABLATION_INSUFFICIENCY_DIAGNOSTIC.csv",
        "V20_153_R1_FACTOR_ABLATION_BLOCKER_BREAKDOWN.csv",
        "V20_153_R1_FACTOR_ABLATION_REPAIR_PLAN.csv",
        "V20_153_R1_FACTOR_ABLATION_NEXT_GATE.csv",
        "V20_153_FACTOR_ABLATION_MATRIX.csv",
        "V20_153_FACTOR_ABLATION_GATE.csv",
        "V20_153_FACTOR_ABLATION_SOURCE_AUDIT.csv",
        "V20_153_FACTOR_ABLATION_ELIGIBILITY_AUDIT.csv",
        "V20_153_FACTOR_ABLATION_GAP_AUDIT.csv",
    ]:
        shutil.copy2(FACTORS / filename, temp / "factors" / filename)
    for filename in [
        "V20_152_RANDOM_AS_OF_BACKTEST_CACHE.csv",
        "V20_152_RANDOM_AS_OF_BACKTEST_CACHE_GATE.csv",
        "V20_152_RANDOM_AS_OF_SOURCE_AUDIT.csv",
        "V20_152_RANDOM_AS_OF_ELIGIBILITY_AUDIT.csv",
        "V20_152_RANDOM_AS_OF_GAP_REPAIR_PLAN.csv",
    ]:
        shutil.copy2(BACKTEST / filename, temp / "backtest" / filename)


def assert_safety_false(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"


def write_minimal_inputs(module, source: str) -> None:
    write_csv(module.R1_DIAGNOSTIC, [{"diagnostic_id": "D1"}])
    write_csv(module.R1_BREAKDOWN, [{"blocker_category": "MISSING_OUTCOME"}])
    write_csv(module.R1_REPAIR, [{"blocker_category": "MISSING_OUTCOME"}])
    write_csv(module.R1_GATE, [{"final_status": "PASS_V20_153_R1_FACTOR_ABLATION_INSUFFICIENCY_DIAGNOSTIC_READY_FOR_REPAIR"}])
    write_csv(module.V153_GATE, [{"final_status": "WARN_V20_153_INSUFFICIENT_FACTOR_ABLATION_EVIDENCE"}])
    write_csv(module.V152_GATE, [{"random_as_of_backtest_cache_status": "PARTIAL_PASS_V20_152_RANDOM_AS_OF_BACKTEST_CACHE_WITH_GAPS_READY_FOR_V20_153"}])
    write_csv(module.V153_MATRIX, [{
        "factor_family": "STRATEGY",
        "factor_name": "MULTI_WINDOW_STRATEGY_EVIDENCE",
        "evidence_source": source,
        "as_of_sample_count": "1",
        "forward_observation_count": "0",
        "outcome_available_count": "0",
        "pending_outcome_count": "0",
        "benchmark_available_count": "0",
        "positive_contribution_count": "0",
        "negative_contribution_count": "0",
        "neutral_contribution_count": "0",
        "contribution_stability": "UNKNOWN_NO_FACTOR_CONTRIBUTION_EVIDENCE",
        "regime_coverage": "NOT_APPLICABLE",
        "window_coverage": "1",
        "usable_for_shadow_weight_proposal": "FALSE",
        "usable_for_official_weight_change": "FALSE",
        "exclusion_reason": "INSUFFICIENT_OUTCOME_EVIDENCE",
        "evidence_quality": "INSUFFICIENT",
    }])
    write_csv(module.V153_SOURCE, [{"source_artifact": source}])
    write_csv(module.V153_ELIGIBILITY, [{"evidence_source": source}])
    write_csv(module.V153_GAP, [{"evidence_source": source, "gap_type": "INSUFFICIENT_OUTCOME_EVIDENCE"}])
    write_csv(module.V152_CACHE, [{"source_artifact": source, "usable_for_dynamic_weight_research": "TRUE", "usable_for_factor_ablation": "TRUE"}])
    write_csv(module.V152_SOURCE, [{"source_artifact": source}])
    write_csv(module.V152_ELIGIBILITY, [{"source_artifact": source}])
    write_csv(module.V152_GAP, [{"source_artifact": source, "gap_type": "X"}])


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        assert gate["final_status"] == "BLOCKED_V20_153_R2_FACTOR_ABLATION_BRIDGE_REPAIR"


def test_temp_bridge_repair_makes_shadow_eligible_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        source = temp / "V20_91_MULTI_WINDOW_STRATEGY_EVIDENCE_MATRIX.csv"
        source_text = str(source)
        write_csv(source, [
            {"signal_date": "2026-05-01", "as_of_date": "2026-05-15", "forward_window": "forward_1d", "row_level_return": "0.01", "benchmark_return": "0.00", "excess_return_vs_benchmark": "0.01"},
            {"signal_date": "2026-05-02", "as_of_date": "2026-05-15", "forward_window": "forward_5d", "row_level_return": "0.02", "benchmark_return": "0.00", "excess_return_vs_benchmark": "0.02"},
            {"signal_date": "2026-05-03", "as_of_date": "2026-05-15", "forward_window": "forward_10d", "row_level_return": "0.03", "benchmark_return": "0.00", "excess_return_vs_benchmark": "0.03"},
            {"signal_date": "2026-05-04", "as_of_date": "2026-05-15", "forward_window": "forward_20d", "row_level_return": "0.04", "benchmark_return": "0.00", "excess_return_vs_benchmark": "0.04"},
        ])
        write_minimal_inputs(module, source_text)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        matrix = read_csv(module.OUT_MATRIX)
        assert gate["final_status"] == "PASS_V20_153_R2_FACTOR_ABLATION_BRIDGE_REPAIR_READY_FOR_V20_154"
        assert gate["shadow_weight_research_eligible_count"] == "1"
        assert matrix[0]["usable_for_shadow_weight_proposal"] == "TRUE"
        assert matrix[0]["usable_for_official_weight_change"] == "FALSE"


def test_factor_ablation_existing_evidence_bridge_repair() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.152/V20.153/R1 outputs were mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_153_R2_FACTOR_ABLATION_BRIDGE_REPAIR_READY_FOR_V20_154",
        "PARTIAL_PASS_V20_153_R2_FACTOR_ABLATION_BRIDGE_REPAIR_WITH_LIMITED_SHADOW_ELIGIBILITY",
        "WARN_V20_153_R2_NO_REPAIRABLE_EXISTING_EVIDENCE_FOUND",
    ])
    for expected in [
        "NEW_BACKTEST_RESULTS_CREATED=FALSE",
        "OUTCOMES_FABRICATED=0",
        "BENCHMARKS_FABRICATED=0",
        "FACTOR_CONTRIBUTION_FABRICATED=0",
        "ELIGIBILITY_THRESHOLDS_LOWERED=FALSE",
        "SHADOW_WEIGHT_PROPOSAL_CREATED=FALSE",
        "OFFICIAL_WEIGHT_MUTATION=FALSE",
        "OFFICIAL_RANKING_CHANGES=FALSE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_TRUE_COUNT=0",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    repair = read_csv(OUT_REPAIR)
    source = read_csv(OUT_SOURCE)
    matrix = read_csv(OUT_MATRIX)
    blockers = read_csv(OUT_BLOCKERS)
    gate = read_csv(OUT_GATE)
    assert repair, "repair diagnostics must not be empty"
    assert source, "source audit must not be empty"
    assert matrix, "repaired matrix must not be empty"
    assert REPAIRED_COLUMNS.issubset(matrix[0].keys()), REPAIRED_COLUMNS - set(matrix[0].keys())
    assert all(row["usable_for_official_weight_change"] == "FALSE" for row in matrix)
    assert gate[0]["official_weight_change_eligible_count"] == "0"
    assert int(gate[0]["repaired_matrix_row_count"]) == len(matrix)
    assert int(gate[0]["remaining_blocker_count"]) == len(blockers)
    assert int(gate[0]["v20_152_dynamic_weight_usable_rows"]) >= int(gate[0]["v20_152_dynamic_weight_usable_rows_consumed_by_v20_153"])
    assert int(gate[0]["v20_152_factor_ablation_usable_rows"]) >= int(gate[0]["v20_152_factor_ablation_usable_rows_consumed_by_v20_153"])
    assert any(row["missing_outcome_alternate_field_found"] == "TRUE" for row in repair)
    assert any(row["missing_benchmark_alternate_field_found"] == "TRUE" for row in repair)
    assert any(row["contribution_attribution_recoverable"] == "TRUE" for row in repair)
    for rows in [repair, source, matrix, blockers, gate]:
        assert_safety_false(rows)


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_temp_bridge_repair_makes_shadow_eligible_case()
    test_factor_ablation_existing_evidence_bridge_repair()
    print("PASS_V20_153_R2_FACTOR_ABLATION_EXISTING_EVIDENCE_BRIDGE_REPAIR_TESTS")
