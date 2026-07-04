#!/usr/bin/env python
"""Tests for V20.9-R1 relative path and staging contract repair."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v20/v20_9_r1_relative_path_and_staging_contract_repair.py"
spec = importlib.util.spec_from_file_location("v20_9_r1", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_first(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return rows[0] if rows else {}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_scripts(root: Path) -> None:
    target = root / "scripts/v20"
    target.mkdir(parents=True, exist_ok=True)
    for name in (
        "v20_8_normalized_research_dataset_construction.py",
        "v20_9_factor_research_dataset_preparation.py",
        "run_v20_9_factor_research_dataset_preparation.ps1",
        "v20_9_r1_relative_path_and_staging_contract_repair.py",
    ):
        shutil.copy2(ROOT / "scripts/v20" / name, target / name)


def normalized_rows(count: int) -> list[dict[str, str]]:
    rows = []
    for idx in range(count):
        rows.append({
            "normalized_row_id": f"N{idx}",
            "input_artifact_id": f"IN{idx}",
            "lineage_binding_id": f"LB{idx}",
            "source_artifact_id": "SRC",
            "source_system": "accepted_v18_full_universe_result",
            "source_hash": "HASH",
            "run_id": "RUN",
            "sample_id": f"S{idx}",
            "ticker": f"T{idx}",
            "effective_observation_date": "2026-06-16",
            "effective_price_date": "2026-06-16",
            "effective_close": "100",
            "active_runtime_flag": "TRUE",
            "historical_reference_flag": "FALSE",
            "research_only_flag": "TRUE",
            "official_use_allowed": "FALSE",
            "normalized_dataset_version": "V20.8_NORMALIZED_RESEARCH_DATASET",
            "normalized_created_at_utc": "2026-06-19T00:00:00+00:00",
            "normalized_source_step": "V20.8",
            "allowed_for_factor_research_next": "TRUE",
            "allowed_for_backtest_now": "FALSE",
            "allowed_for_dynamic_weighting_now": "FALSE",
            "allowed_for_trading_now": "FALSE",
            "allowed_for_official_recommendation_now": "FALSE",
        })
    return rows


def write_v20_8_bundle(base: Path, count: int) -> None:
    c = base / "consolidation"
    ops = base / "ops"
    write_rows(c / "V20_8_NORMALIZED_RESEARCH_DATASET.csv", normalized_rows(count))
    write_rows(c / "V20_8_GATE_DECISION.csv", [{
        "status": "PASS_V20_8_NORMALIZED_RESEARCH_DATASET_CONSTRUCTED",
        "NORMALIZED_RESEARCH_DATASET_CREATED": "TRUE",
        "NORMALIZED_ROWS_CREATED": str(count),
        "READY_FOR_V20_9_FACTOR_RESEARCH_DATASET_PREPARATION_NEXT": "TRUE",
        "READY_FOR_BACKTEST_NEXT": "FALSE",
        "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
        "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
    }])
    write_rows(c / "V20_8_VALIDATION_SUMMARY.csv", [{
        "status": "PASS_V20_8_NORMALIZED_RESEARCH_DATASET_CONSTRUCTED",
        "normalized_research_dataset_created": "TRUE",
        "normalized_row_count": str(count),
        "ready_for_v20_9_factor_research_dataset_preparation_next": "TRUE",
        "ready_for_backtest_next": "FALSE",
        "ready_for_dynamic_weighting_next": "FALSE",
        "ready_for_trading_or_official_recommendation": "FALSE",
    }])
    write_rows(c / "V20_8_RESEARCH_ONLY_BOUNDARY_AUDIT.csv", [{"research_only_boundary_status": "PASS"}])
    ops.mkdir(parents=True, exist_ok=True)
    (ops / "V20_8_READ_FIRST.txt").write_text(
        "REPORTING_ONLY: FALSE\nRESEARCH_DATASET_CONSTRUCTION: TRUE\nNORMALIZED_RESEARCH_DATASET_CREATED: TRUE\n"
        f"NORMALIZED_ROWS_CREATED: {count}\nFACTOR_EVIDENCE_ROWS_CREATED: 0\nBACKTEST_ROWS_CREATED: 0\n"
        "DYNAMIC_WEIGHTING_ROWS_CREATED: 0\nTRADING_SIGNAL_ROWS_CREATED: 0\nOFFICIAL_RECOMMENDATION_ROWS_CREATED: 0\n"
        "BROKER_API_USED: FALSE\nORDER_EXECUTION_USED: FALSE\nSOURCE_MUTATION_USED: FALSE\nV21_OUTPUTS_CREATED: FALSE\n"
        "V19_21_OUTPUTS_CREATED: FALSE\nOFFICIAL_USE_ALLOWED: FALSE\n",
        encoding="utf-8",
    )


def fixture(root: Path, *, r3b_valid: bool = True, rows: int = 2) -> None:
    copy_scripts(root)
    d = root / "outputs/v20/diagnostics"
    c = root / "outputs/v20/consolidation"
    write_rows(d / "V20_16_R3B_SAFE_STAGED_RERUN_WRAPPER_SUMMARY.csv", [{
        "final_status": "BLOCKED_V20_16_R3B_ABSOLUTE_PRODUCTION_PATH_BINDING" if r3b_valid else "BLOCKED_OTHER",
        "decision": "BLOCK_STAGED_RERUN_ABSOLUTE_PRODUCTION_PATH_BINDING",
        "absolute_path_binding_detected": "TRUE",
        "earliest_failed_stage": "V20.9" if r3b_valid else "V20.10",
        "expected_eligible_row_count": str(rows),
        "certified_v20_7x_eligible_row_count": str(rows),
        "recommended_next_stage": "V20.8-R1_RELATIVE_PATH_AND_STAGING_CONTRACT_REPAIR",
    }])
    write_v20_8_bundle(root / "outputs/v20", rows)
    write_v20_8_bundle(root / "outputs/v20/staging/V20_8_R1_CONTRACT_SMOKE", rows)
    write_rows(c / "V20_9_FACTOR_RESEARCH_BASE_DATASET.csv", [{"ticker": "OLD", "effective_observation_date": "2026-06-15"}])
    write_rows(c / "V20_10_VALIDATION_SUMMARY.csv", [{"status": "OLD"}])
    write_rows(c / "V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv", [{"ticker": "T0", "effective_observation_date": "2026-06-16"}])
    write_rows(c / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv", [{"ticker": "T0", "rank": "1"}])


def run_v20_9(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/v20/v20_9_factor_research_dataset_preparation.py", *args],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=120,
    )


def test_r3b_absolute_binding_block_at_v20_9_is_detected() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, _ = module.run_repair(root)
        assert summary["source_v20_16_r3b_status"] == "BLOCKED_V20_16_R3B_ABSOLUTE_PRODUCTION_PATH_BINDING"
        assert summary["absolute_path_binding_before"] == "TRUE"


def test_v20_9_supports_input_and_output_override_after_repair() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        inp = root / "outputs/v20/staging/V20_8_R1_CONTRACT_SMOKE/consolidation/V20_8_NORMALIZED_RESEARCH_DATASET.csv"
        out = root / "outputs/v20/staging/manual9"
        proc = run_v20_9(root, "--input-path", str(inp), "--output-dir", str(out), "--staging-mode")
        assert proc.returncode == 0, proc.stderr + proc.stdout
        assert (out / "consolidation/V20_9_FACTOR_RESEARCH_BASE_DATASET.csv").exists()


def test_v20_9_staging_mode_writes_only_to_staging_directory() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        prod = root / "outputs/v20/consolidation/V20_9_FACTOR_RESEARCH_BASE_DATASET.csv"
        before = sha(prod)
        inp = root / "outputs/v20/staging/V20_8_R1_CONTRACT_SMOKE/consolidation/V20_8_NORMALIZED_RESEARCH_DATASET.csv"
        out = root / "outputs/v20/staging/only9"
        proc = run_v20_9(root, "--input-path", str(inp), "--output-dir", str(out), "--staging-mode")
        assert proc.returncode == 0
        assert sha(prod) == before
        assert all(str(path.resolve()).startswith(str(out.resolve())) for path in out.rglob("*") if path.is_file())


def test_v20_9_dry_run_no_production_write_does_not_mutate() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        prod = root / "outputs/v20/consolidation/V20_9_FACTOR_RESEARCH_BASE_DATASET.csv"
        before = sha(prod)
        proc = run_v20_9(root, "--dry-run")
        assert proc.returncode == 0
        assert sha(prod) == before


def test_default_production_behavior_remains_callable_without_overrides() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        proc = run_v20_9(root)
        assert proc.returncode == 0, proc.stderr + proc.stdout
        row = read_first(root / "outputs/v20/consolidation/V20_9_VALIDATION_SUMMARY.csv")
        assert row["production_write_allowed"] == "TRUE"
        assert row["eligible_row_count"] == "2"


def test_absolute_path_binding_removed_or_neutralized() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        audit = module.audit_contract(root)
        assert audit["absolute_path_binding"] is False
        assert audit["input_override"] and audit["output_override"] and audit["staging_mode"] and audit["dry_run"]


def test_staging_smoke_row_count_equals_staged_v20_8_input_count() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, _ = module.run_repair(root)
        assert summary["staging_smoke_pass"] == "TRUE"
        assert summary["staging_smoke_eligible_row_count"] == "2"
        assert summary["expected_vs_staging_smoke_delta"] == "0"


def test_repair_smoke_does_not_mutate_production_certified_or_protected() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        prod9 = root / "outputs/v20/consolidation/V20_9_FACTOR_RESEARCH_BASE_DATASET.csv"
        prod10 = root / "outputs/v20/consolidation/V20_10_VALIDATION_SUMMARY.csv"
        prod8 = root / "outputs/v20/consolidation/V20_8_NORMALIZED_RESEARCH_DATASET.csv"
        v7x = root / "outputs/v20/consolidation/V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv"
        official = root / "outputs/v20/consolidation/V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
        before = (sha(prod9), sha(prod10), sha(prod8), sha(v7x), sha(official))
        summary, _ = module.run_repair(root)
        assert before == (sha(prod9), sha(prod10), sha(prod8), sha(v7x), sha(official))
        assert summary["production_v20_9_outputs_mutated"] == "FALSE"
        assert summary["production_v20_10_to_v20_16_outputs_mutated"] == "FALSE"
        assert summary["production_v20_8_outputs_mutated"] == "FALSE"
        assert summary["certified_v20_7x_outputs_mutated"] == "FALSE"
        assert summary["protected_outputs_mutated"] == "FALSE"


def test_permissions_false_summary_fields_and_repeat_safe() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        first, _ = module.run_repair(root)
        second, _ = module.run_repair(root)
        assert first["final_status"] == second["final_status"]
        assert set(module.SUMMARY_FIELDS).issubset(second)
        for field in (
            "official_activation_allowed", "official_recommendation_allowed",
            "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
            "broker_execution_allowed", "trade_action_allowed",
        ):
            assert second[field] == "FALSE"


def test_blocks_invalid_r3b() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, r3b_valid=False)
        summary, _ = module.run_repair(root)
        assert summary["final_status"] == module.BLOCKED_R3B


if __name__ == "__main__":
    test_r3b_absolute_binding_block_at_v20_9_is_detected()
    test_v20_9_supports_input_and_output_override_after_repair()
    test_v20_9_staging_mode_writes_only_to_staging_directory()
    test_v20_9_dry_run_no_production_write_does_not_mutate()
    test_default_production_behavior_remains_callable_without_overrides()
    test_absolute_path_binding_removed_or_neutralized()
    test_staging_smoke_row_count_equals_staged_v20_8_input_count()
    test_repair_smoke_does_not_mutate_production_certified_or_protected()
    test_permissions_false_summary_fields_and_repeat_safe()
    test_blocks_invalid_r3b()
    print("PASS test_v20_9_r1_relative_path_and_staging_contract_repair")
