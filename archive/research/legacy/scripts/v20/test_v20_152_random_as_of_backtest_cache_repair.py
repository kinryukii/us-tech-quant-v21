#!/usr/bin/env python
"""Tests for V20.152 random-as-of backtest cache repair."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_152_random_as_of_backtest_cache_repair.py"
OBSERVATIONS = ROOT / "outputs" / "v20" / "observations"
BACKTEST = ROOT / "outputs" / "v20" / "backtest"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_CACHE = BACKTEST / "V20_152_RANDOM_AS_OF_BACKTEST_CACHE.csv"
OUT_GATE = BACKTEST / "V20_152_RANDOM_AS_OF_BACKTEST_CACHE_GATE.csv"
OUT_SOURCE = BACKTEST / "V20_152_RANDOM_AS_OF_SOURCE_AUDIT.csv"
OUT_ELIGIBILITY = BACKTEST / "V20_152_RANDOM_AS_OF_ELIGIBILITY_AUDIT.csv"
OUT_GAP = BACKTEST / "V20_152_RANDOM_AS_OF_GAP_REPAIR_PLAN.csv"
OUT_REPORT = READ_CENTER / "V20_152_RANDOM_AS_OF_BACKTEST_CACHE_REPAIR_REPORT.md"
OUTPUTS = [OUT_CACHE, OUT_GATE, OUT_SOURCE, OUT_ELIGIBILITY, OUT_GAP, OUT_REPORT]

REQUIRED_CACHE_COLUMNS = {
    "as_of_date",
    "forward_window",
    "source_artifact",
    "ticker_count",
    "benchmark_available",
    "outcome_available",
    "pit_safe",
    "usable_for_factor_ablation",
    "usable_for_dynamic_weight_research",
    "exclusion_reason",
    "evidence_quality",
    "data_freshness_status",
}
REQUIRED_SAFETY_FALSE = [
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
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
    roots = [
        ROOT / "outputs" / "v20" / "consolidation",
        ROOT / "outputs" / "v20" / "evidence",
        ROOT / "outputs" / "v20" / "evidence_coverage",
        ROOT / "outputs" / "v20" / "observations",
        ROOT / "outputs" / "v20" / "ops",
    ]
    paths: list[Path] = []
    for root in roots:
        if root.exists():
            paths.extend(path for path in root.glob("V20_*") if path.is_file())
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_152_random_as_of_backtest_cache_repair_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.CONSOLIDATION = temp / "consolidation"
    module.EVIDENCE = temp / "evidence"
    module.EVIDENCE_COVERAGE = temp / "evidence_coverage"
    module.OBSERVATIONS = temp / "observations"
    module.OPS = temp / "ops"
    module.READ_CENTER = temp / "read_center"
    module.BACKTEST = temp / "backtest"
    module.INPUTS = temp / "inputs"
    module.IN_V151_GATE = module.OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_GATE.csv"
    module.IN_V151_ACCUMULATION = module.OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_ACCUMULATION.csv"
    module.IN_V151_SOURCE = module.OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_SOURCE_AUDIT.csv"
    module.IN_V151_ELIGIBILITY = module.OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_ELIGIBILITY_AUDIT.csv"
    module.OUT_CACHE = module.BACKTEST / "V20_152_RANDOM_AS_OF_BACKTEST_CACHE.csv"
    module.OUT_GATE = module.BACKTEST / "V20_152_RANDOM_AS_OF_BACKTEST_CACHE_GATE.csv"
    module.OUT_SOURCE_AUDIT = module.BACKTEST / "V20_152_RANDOM_AS_OF_SOURCE_AUDIT.csv"
    module.OUT_ELIGIBILITY_AUDIT = module.BACKTEST / "V20_152_RANDOM_AS_OF_ELIGIBILITY_AUDIT.csv"
    module.OUT_GAP_PLAN = module.BACKTEST / "V20_152_RANDOM_AS_OF_GAP_REPAIR_PLAN.csv"
    module.REPORT = module.READ_CENTER / "V20_152_RANDOM_AS_OF_BACKTEST_CACHE_REPAIR_REPORT.md"
    module.DISCOVERY_ROOTS = [module.CONSOLIDATION, module.EVIDENCE, module.EVIDENCE_COVERAGE, module.OPS, module.INPUTS / "random_asof", module.INPUTS / "outcome_benchmark"]


def copy_v151_inputs(temp: Path) -> None:
    target = temp / "observations"
    target.mkdir(parents=True, exist_ok=True)
    for filename in [
        "V20_151_FORWARD_OBSERVATION_GATE.csv",
        "V20_151_FORWARD_OBSERVATION_ACCUMULATION.csv",
        "V20_151_FORWARD_OBSERVATION_SOURCE_AUDIT.csv",
        "V20_151_FORWARD_OBSERVATION_ELIGIBILITY_AUDIT.csv",
    ]:
        shutil.copy2(OBSERVATIONS / filename, target / filename)


def assert_safety_false(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in REQUIRED_SAFETY_FALSE:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"


def test_blocked_missing_v151_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        assert gate["random_as_of_backtest_cache_status"] == "BLOCKED_V20_152_RANDOM_AS_OF_BACKTEST_CACHE_REPAIR"
        assert gate["v20_153_random_as_of_review_allowed"] == "FALSE"


def test_blocked_invalid_v151_gate_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_v151_inputs(temp)
        patch_module_to_temp(module, temp)
        gate = read_csv(module.IN_V151_GATE)
        gate[0]["forward_observation_accumulation_status"] = "BLOCKED_V20_151_FORWARD_OBSERVATION_ACCUMULATION"
        write_csv(module.IN_V151_GATE, gate)
        assert module.main() == 0
        out_gate = read_csv(module.OUT_GATE)[0]
        assert out_gate["random_as_of_backtest_cache_status"] == "BLOCKED_V20_152_RANDOM_AS_OF_BACKTEST_CACHE_REPAIR"


def test_temp_cache_repair_classification_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_v151_inputs(temp)
        patch_module_to_temp(module, temp)
        sample = module.CONSOLIDATION / "V20_35_R2_EXPLORATORY_ROW_LEVEL_RETURNS.csv"
        write_csv(sample, [
            {
                "signal_date": "2026-05-01",
                "ticker": "MSFT",
                "forward_window": "20",
                "ticker_forward_return": "0.10",
                "spy_forward_return": "0.05",
                "factor_asof_check_passed": "TRUE",
                "outcome_date_after_signal_date": "TRUE",
            },
            {
                "signal_date": "2026-05-01",
                "ticker": "AAPL",
                "forward_window": "20",
                "ticker_forward_return": "0.04",
                "spy_forward_return": "0.05",
                "factor_asof_check_passed": "TRUE",
                "outcome_date_after_signal_date": "TRUE",
            },
        ])
        write_csv(module.EVIDENCE / "V20_91_MULTI_WINDOW_STRATEGY_EVIDENCE_MATRIX.csv", [
            {
                "as_of_date": "2026-05-15",
                "ticker": "MELI",
                "holding_window": "forward_5d",
                "forward_return": "-0.05",
                "benchmark_ticker": "QQQ",
                "benchmark_forward_return": "-0.01",
                "certification_status": "CERTIFIED_MULTI_WINDOW_STRATEGY_EVIDENCE",
                "research_only": "TRUE",
            }
        ])
        assert module.main() == 0
        cache = read_csv(module.OUT_CACHE)
        source = read_csv(module.OUT_SOURCE_AUDIT)
        gate = read_csv(module.OUT_GATE)[0]
        assert gate["random_as_of_backtest_cache_status"] in {
            "PASS_V20_152_RANDOM_AS_OF_BACKTEST_CACHE_READY_FOR_V20_153",
            "PARTIAL_PASS_V20_152_RANDOM_AS_OF_BACKTEST_CACHE_WITH_GAPS_READY_FOR_V20_153",
        }
        assert any(row["usable_for_dynamic_weight_research"] == "TRUE" for row in cache)
        assert any(row["source_cache_status"] == "USABLE" for row in source)
        assert_safety_false(cache)
        assert_safety_false(source)


def test_random_as_of_backtest_cache_repair() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20 outputs were mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_152_RANDOM_AS_OF_BACKTEST_CACHE_READY_FOR_V20_153",
        "PARTIAL_PASS_V20_152_RANDOM_AS_OF_BACKTEST_CACHE_WITH_GAPS_READY_FOR_V20_153",
        "WARN_V20_152_NO_USABLE_RANDOM_AS_OF_CACHE_FOUND",
    ])
    for expected in [
        "V20_151_GATE_CONSUMED=TRUE",
        "V20_151_ALLOWED_FOR_V20_152=TRUE",
        "STAGING_REVIEW_ALLOWED=TRUE",
        "FORMAL_ACTIVATION_ALLOWED=FALSE",
        "PROMOTION_READY=FALSE",
        "TICKER_ROWS_FABRICATED=0",
        "HISTORICAL_PRICES_FABRICATED=0",
        "BENCHMARK_RETURNS_FABRICATED=0",
        "OUTCOMES_FABRICATED=0",
        "PERFORMANCE_CLAIM_CREATED=FALSE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_TRUE_COUNT=0",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    cache = read_csv(OUT_CACHE)
    gate = read_csv(OUT_GATE)
    source = read_csv(OUT_SOURCE)
    eligibility = read_csv(OUT_ELIGIBILITY)
    gaps = read_csv(OUT_GAP)
    assert gate, "empty gate"
    assert source, "source audit must mark discovered historical artifacts"
    assert eligibility, "eligibility audit must not be empty"
    assert REQUIRED_CACHE_COLUMNS.issubset(cache[0].keys()), REQUIRED_CACHE_COLUMNS - set(cache[0].keys())
    assert {row["source_cache_status"] for row in source}.issubset({"USABLE", "PARTIAL", "INELIGIBLE"})
    assert any(row["source_stage"] in {"V20.35.R1", "V20.35.R2", "V20.82", "V20.84", "V20.89", "V20.90", "V20.91", "V20.92", "V20.93"} for row in source)
    assert any(row["source_cache_status"] in {"USABLE", "PARTIAL"} for row in source)
    assert all(row["exclusion_reason"] for row in source if row["source_cache_status"] != "USABLE")
    assert all(row["exclusion_reason"] for row in eligibility if row["eligible_for_cache"] == "FALSE")
    assert int(gate[0]["source_artifact_count"]) == len(source)
    assert int(gate[0]["cache_row_count"]) == len(cache)
    assert int(gate[0]["gap_count"]) == len(gaps)
    assert gate[0]["formal_activation_allowed"] == "FALSE"
    assert gate[0]["promotion_ready"] == "FALSE"
    assert gate[0]["official_recommendation_created"] == "FALSE"
    assert gate[0]["performance_claim_created"] == "FALSE"
    for rows in [cache, gate, source, eligibility, gaps]:
        assert_safety_false(rows)


if __name__ == "__main__":
    test_blocked_missing_v151_case()
    test_blocked_invalid_v151_gate_case()
    test_temp_cache_repair_classification_case()
    test_random_as_of_backtest_cache_repair()
    print("PASS_V20_152_RANDOM_AS_OF_BACKTEST_CACHE_REPAIR_TESTS")
