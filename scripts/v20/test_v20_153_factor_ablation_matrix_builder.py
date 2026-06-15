#!/usr/bin/env python
"""Tests for V20.153 factor ablation matrix builder."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_153_factor_ablation_matrix_builder.py"
BACKTEST = ROOT / "outputs" / "v20" / "backtest"
OBSERVATIONS = ROOT / "outputs" / "v20" / "observations"
FACTORS = ROOT / "outputs" / "v20" / "factors"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_MATRIX = FACTORS / "V20_153_FACTOR_ABLATION_MATRIX.csv"
OUT_GATE = FACTORS / "V20_153_FACTOR_ABLATION_GATE.csv"
OUT_SOURCE = FACTORS / "V20_153_FACTOR_ABLATION_SOURCE_AUDIT.csv"
OUT_ELIGIBILITY = FACTORS / "V20_153_FACTOR_ABLATION_ELIGIBILITY_AUDIT.csv"
OUT_GAP = FACTORS / "V20_153_FACTOR_ABLATION_GAP_AUDIT.csv"
OUT_REPORT = READ_CENTER / "V20_153_FACTOR_ABLATION_MATRIX_REPORT.md"
OUTPUTS = [OUT_MATRIX, OUT_GATE, OUT_SOURCE, OUT_ELIGIBILITY, OUT_GAP, OUT_REPORT]

REQUIRED_MATRIX_COLUMNS = {
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
        BACKTEST / "V20_152_RANDOM_AS_OF_BACKTEST_CACHE.csv",
        BACKTEST / "V20_152_RANDOM_AS_OF_BACKTEST_CACHE_GATE.csv",
        BACKTEST / "V20_152_RANDOM_AS_OF_ELIGIBILITY_AUDIT.csv",
        BACKTEST / "V20_152_RANDOM_AS_OF_SOURCE_AUDIT.csv",
        OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_ACCUMULATION.csv",
        OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_ELIGIBILITY_AUDIT.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_153_factor_ablation_matrix_builder_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.BACKTEST = temp / "backtest"
    module.OBSERVATIONS = temp / "observations"
    module.FACTORS = temp / "factors"
    module.READ_CENTER = temp / "read_center"
    module.IN_CACHE = module.BACKTEST / "V20_152_RANDOM_AS_OF_BACKTEST_CACHE.csv"
    module.IN_V152_GATE = module.BACKTEST / "V20_152_RANDOM_AS_OF_BACKTEST_CACHE_GATE.csv"
    module.IN_V152_ELIGIBILITY = module.BACKTEST / "V20_152_RANDOM_AS_OF_ELIGIBILITY_AUDIT.csv"
    module.IN_V152_SOURCE = module.BACKTEST / "V20_152_RANDOM_AS_OF_SOURCE_AUDIT.csv"
    module.IN_V151_ACCUMULATION = module.OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_ACCUMULATION.csv"
    module.IN_V151_ELIGIBILITY = module.OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_ELIGIBILITY_AUDIT.csv"
    module.OUT_MATRIX = module.FACTORS / "V20_153_FACTOR_ABLATION_MATRIX.csv"
    module.OUT_GATE = module.FACTORS / "V20_153_FACTOR_ABLATION_GATE.csv"
    module.OUT_SOURCE_AUDIT = module.FACTORS / "V20_153_FACTOR_ABLATION_SOURCE_AUDIT.csv"
    module.OUT_ELIGIBILITY_AUDIT = module.FACTORS / "V20_153_FACTOR_ABLATION_ELIGIBILITY_AUDIT.csv"
    module.OUT_GAP_AUDIT = module.FACTORS / "V20_153_FACTOR_ABLATION_GAP_AUDIT.csv"
    module.REPORT = module.READ_CENTER / "V20_153_FACTOR_ABLATION_MATRIX_REPORT.md"


def copy_v152_inputs(temp: Path) -> None:
    target = temp / "backtest"
    target.mkdir(parents=True, exist_ok=True)
    for filename in [
        "V20_152_RANDOM_AS_OF_BACKTEST_CACHE.csv",
        "V20_152_RANDOM_AS_OF_BACKTEST_CACHE_GATE.csv",
        "V20_152_RANDOM_AS_OF_ELIGIBILITY_AUDIT.csv",
        "V20_152_RANDOM_AS_OF_SOURCE_AUDIT.csv",
    ]:
        shutil.copy2(BACKTEST / filename, target / filename)
    obs = temp / "observations"
    obs.mkdir(parents=True, exist_ok=True)
    for filename in [
        "V20_151_FORWARD_OBSERVATION_ACCUMULATION.csv",
        "V20_151_FORWARD_OBSERVATION_ELIGIBILITY_AUDIT.csv",
    ]:
        if (OBSERVATIONS / filename).exists():
            shutil.copy2(OBSERVATIONS / filename, obs / filename)


def assert_safety_false(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        assert gate["final_status"] == "BLOCKED_V20_153_FACTOR_ABLATION_MATRIX_BUILDER"
        assert gate["v20_154_factor_ablation_review_allowed"] == "FALSE"


def test_blocked_invalid_v152_gate_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_v152_inputs(temp)
        patch_module_to_temp(module, temp)
        gate = read_csv(module.IN_V152_GATE)
        gate[0]["random_as_of_backtest_cache_status"] = "BLOCKED_V20_152_RANDOM_AS_OF_BACKTEST_CACHE_REPAIR"
        write_csv(module.IN_V152_GATE, gate)
        assert module.main() == 0
        out_gate = read_csv(module.OUT_GATE)[0]
        assert out_gate["final_status"] == "BLOCKED_V20_153_FACTOR_ABLATION_MATRIX_BUILDER"


def test_temp_shadow_eligible_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        source = temp / "evidence" / "V20_91_MULTI_WINDOW_STRATEGY_EVIDENCE_MATRIX.csv"
        source_rel = str(source)
        write_csv(source, [
            {"as_of_date": "2026-05-01", "ticker": "A", "forward_window": "5d", "excess_return": "0.10"},
            {"as_of_date": "2026-05-02", "ticker": "B", "forward_window": "5d", "excess_return": "0.11"},
            {"as_of_date": "2026-05-03", "ticker": "C", "forward_window": "10d", "excess_return": "0.12"},
            {"as_of_date": "2026-05-04", "ticker": "D", "forward_window": "10d", "excess_return": "0.13"},
        ])
        write_csv(module.IN_CACHE, [
            {"as_of_date": "2026-05-01", "forward_window": "5d", "source_artifact": source_rel, "ticker_count": "1", "benchmark_available": "TRUE", "outcome_available": "TRUE", "pit_safe": "TRUE", "usable_for_factor_ablation": "TRUE", "usable_for_dynamic_weight_research": "TRUE"},
            {"as_of_date": "2026-05-02", "forward_window": "5d", "source_artifact": source_rel, "ticker_count": "1", "benchmark_available": "TRUE", "outcome_available": "TRUE", "pit_safe": "TRUE", "usable_for_factor_ablation": "TRUE", "usable_for_dynamic_weight_research": "TRUE"},
            {"as_of_date": "2026-05-03", "forward_window": "10d", "source_artifact": source_rel, "ticker_count": "1", "benchmark_available": "TRUE", "outcome_available": "TRUE", "pit_safe": "TRUE", "usable_for_factor_ablation": "TRUE", "usable_for_dynamic_weight_research": "TRUE"},
            {"as_of_date": "2026-05-04", "forward_window": "10d", "source_artifact": source_rel, "ticker_count": "1", "benchmark_available": "TRUE", "outcome_available": "TRUE", "pit_safe": "TRUE", "usable_for_factor_ablation": "TRUE", "usable_for_dynamic_weight_research": "TRUE"},
        ])
        write_csv(module.IN_V152_GATE, [{"random_as_of_backtest_cache_status": "PASS_V20_152_RANDOM_AS_OF_BACKTEST_CACHE_READY_FOR_V20_153", "staging_review_allowed": "TRUE", "formal_activation_allowed": "FALSE", "promotion_ready": "FALSE"}])
        write_csv(module.IN_V152_ELIGIBILITY, [{"source_artifact": source_rel, "eligible_for_cache": "TRUE"}])
        write_csv(module.IN_V152_SOURCE, [{"source_artifact": source_rel, "source_cache_status": "USABLE"}])
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        matrix = read_csv(module.OUT_MATRIX)
        assert gate["final_status"] == "PASS_V20_153_FACTOR_ABLATION_MATRIX_READY_FOR_V20_154"
        assert matrix[0]["usable_for_shadow_weight_proposal"] == "TRUE"
        assert matrix[0]["usable_for_official_weight_change"] == "FALSE"


def test_factor_ablation_matrix_builder() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "V20.151/V20.152 inputs were mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_153_FACTOR_ABLATION_MATRIX_READY_FOR_V20_154",
        "PARTIAL_PASS_V20_153_FACTOR_ABLATION_MATRIX_WITH_LIMITED_EVIDENCE_READY_FOR_V20_154",
        "WARN_V20_153_INSUFFICIENT_FACTOR_ABLATION_EVIDENCE",
    ])
    for expected in [
        "V20_152_GATE_CONSUMED=TRUE",
        "V20_152_ALLOWED_FOR_V20_153=TRUE",
        "STAGING_REVIEW_ALLOWED=TRUE",
        "FORMAL_ACTIVATION_ALLOWED=FALSE",
        "PROMOTION_READY=FALSE",
        "OFFICIAL_WEIGHT_CHANGE_ELIGIBLE_COUNT=0",
        "FACTOR_PERFORMANCE_FABRICATED=0",
        "RETURNS_FABRICATED=0",
        "OUTCOMES_FABRICATED=0",
        "BENCHMARKS_FABRICATED=0",
        "OFFICIAL_WEIGHT_CHANGE_CREATED=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_TRUE_COUNT=0",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    matrix = read_csv(OUT_MATRIX)
    gate = read_csv(OUT_GATE)
    source = read_csv(OUT_SOURCE)
    eligibility = read_csv(OUT_ELIGIBILITY)
    gaps = read_csv(OUT_GAP)
    assert matrix, "matrix must not be empty"
    assert source, "source audit must not be empty"
    assert eligibility, "eligibility audit must not be empty"
    assert REQUIRED_MATRIX_COLUMNS.issubset(matrix[0].keys()), REQUIRED_MATRIX_COLUMNS - set(matrix[0].keys())
    assert all(row["usable_for_official_weight_change"] == "FALSE" for row in matrix)
    assert all(row["eligible_for_official_weight_change"] == "FALSE" for row in eligibility)
    assert all(row["exclusion_reason"] for row in matrix if row["usable_for_shadow_weight_proposal"] == "FALSE")
    assert int(gate[0]["matrix_row_count"]) == len(matrix)
    assert int(gate[0]["source_audit_row_count"]) == len(source)
    assert int(gate[0]["gap_count"]) == len(gaps)
    assert gate[0]["official_weight_change_eligible_count"] == "0"
    assert gate[0]["formal_activation_allowed"] == "FALSE"
    assert gate[0]["promotion_ready"] == "FALSE"
    assert gate[0]["official_weight_change_created"] == "FALSE"
    for rows in [matrix, gate, source, eligibility, gaps]:
        assert_safety_false(rows)


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_invalid_v152_gate_case()
    test_temp_shadow_eligible_case()
    test_factor_ablation_matrix_builder()
    print("PASS_V20_153_FACTOR_ABLATION_MATRIX_BUILDER_TESTS")
