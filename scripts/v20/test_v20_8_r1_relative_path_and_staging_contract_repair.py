#!/usr/bin/env python
"""Tests for V20.8-R1 relative path and staging contract repair."""

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
SCRIPT = ROOT / "scripts/v20/v20_8_r1_relative_path_and_staging_contract_repair.py"
spec = importlib.util.spec_from_file_location("v20_8_r1", SCRIPT)
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
        "run_v20_8_normalized_research_dataset_construction.ps1",
        "v20_8_r1_relative_path_and_staging_contract_repair.py",
    ):
        shutil.copy2(ROOT / "scripts/v20" / name, target / name)


def fixture(root: Path, *, r3b_valid: bool = True, rows: int = 2) -> None:
    copy_scripts(root)
    d = root / "outputs/v20/diagnostics"
    c = root / "outputs/v20/consolidation"
    ops = root / "outputs/v20/ops"
    write_rows(d / "V20_16_R3B_SAFE_STAGED_RERUN_WRAPPER_SUMMARY.csv", [{
        "final_status": "BLOCKED_V20_16_R3B_ABSOLUTE_PRODUCTION_PATH_BINDING" if r3b_valid else "BLOCKED_OTHER",
        "decision": "BLOCK_STAGED_RERUN_ABSOLUTE_PRODUCTION_PATH_BINDING",
        "absolute_path_binding_detected": "TRUE",
        "earliest_failed_stage": "V20.8" if r3b_valid else "V20.9",
        "expected_eligible_row_count": str(rows),
        "certified_v20_7x_eligible_row_count": str(rows),
        "recommended_next_stage": "V20.8-R1_RELATIVE_PATH_AND_STAGING_CONTRACT_REPAIR",
    }])
    binding = []
    for idx in range(rows):
        binding.append({
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
            "allowed_for_v20_8_input": "TRUE",
        })
    write_rows(c / "V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv", binding)
    write_rows(c / "V20_7X_GATE_DECISION.csv", [{
        "status": "PASS_V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING_READY",
        "ACTIVE_MARKET_INPUT_LINEAGE_BOUND": "TRUE",
        "READY_FOR_V20_8_NORMALIZED_RESEARCH_DATASET_NEXT": "TRUE",
        "V20_8_REMAINS_BLOCKED": "FALSE",
    }])
    write_rows(c / "V20_7X_INPUT_READINESS_FOR_V20_8_AUDIT.csv", [{
        "readiness_status": "PASS",
        "active_market_input_lineage_bound": "TRUE",
        "certified_source_accepted": "TRUE",
    }])
    write_rows(c / "V20_7X_VALIDATION_SUMMARY.csv", [{
        "status": "PASS_V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING_READY",
        "ready_for_v20_8_normalized_research_dataset_next": "TRUE",
        "v20_8_remains_blocked": "FALSE",
    }])
    ops.mkdir(parents=True, exist_ok=True)
    (ops / "V20_7X_READ_FIRST.txt").write_text("LINEAGE_BINDING_RETRY_ONLY: TRUE\nV20_8_OUTPUTS_CREATED: FALSE\n", encoding="utf-8")
    write_rows(c / "V20_8_NORMALIZED_RESEARCH_DATASET.csv", [{"ticker": "OLD", "effective_observation_date": "2026-06-15"}])
    write_rows(c / "V20_9_FACTOR_RESEARCH_BASE_DATASET.csv", [{"ticker": "OLD", "effective_observation_date": "2026-06-15"}])
    write_rows(c / "V20_16_GATE_DECISION.csv", [{"eligible_row_count": "99"}])
    write_rows(c / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv", [{"ticker": "T0", "rank": "1"}])


def run_v20_8(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/v20/v20_8_normalized_research_dataset_construction.py", *args],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=120,
    )


def test_r3b_absolute_binding_block_is_detected() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, _ = module.run_repair(root)
        assert summary["source_v20_16_r3b_status"] == "BLOCKED_V20_16_R3B_ABSOLUTE_PRODUCTION_PATH_BINDING"
        assert summary["absolute_path_binding_before"] == "TRUE"


def test_v20_8_supports_input_and_output_override_after_repair() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        out = root / "outputs/v20/staging/manual"
        proc = run_v20_8(root, "--input-path", "outputs/v20/consolidation/V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv", "--output-dir", str(out), "--staging-mode")
        assert proc.returncode == 0, proc.stderr + proc.stdout
        assert (out / "consolidation/V20_8_NORMALIZED_RESEARCH_DATASET.csv").exists()


def test_v20_8_staging_mode_writes_only_to_staging_directory() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        prod = root / "outputs/v20/consolidation/V20_8_NORMALIZED_RESEARCH_DATASET.csv"
        before = sha(prod)
        out = root / "outputs/v20/staging/only"
        proc = run_v20_8(root, "--output-dir", str(out), "--staging-mode")
        assert proc.returncode == 0
        assert sha(prod) == before
        assert all(str(path.resolve()).startswith(str(out.resolve())) for path in out.rglob("*") if path.is_file())


def test_v20_8_dry_run_no_production_write_does_not_mutate() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        prod = root / "outputs/v20/consolidation/V20_8_NORMALIZED_RESEARCH_DATASET.csv"
        before = sha(prod)
        proc = run_v20_8(root, "--dry-run")
        assert proc.returncode == 0
        assert sha(prod) == before


def test_default_production_behavior_remains_callable_without_overrides() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        proc = run_v20_8(root)
        assert proc.returncode == 0, proc.stderr + proc.stdout
        row = read_first(root / "outputs/v20/consolidation/V20_8_VALIDATION_SUMMARY.csv")
        assert row["production_write_allowed"] == "TRUE"
        assert row["eligible_row_count"] == "2"


def test_absolute_path_binding_removed_or_neutralized() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        audit = module.audit_contract(root)
        assert audit["absolute_path_binding"] is False
        assert audit["input_override"] and audit["output_override"] and audit["staging_mode"] and audit["dry_run"]


def test_staging_smoke_row_count_equals_expected_certified_count() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, _ = module.run_repair(root)
        assert summary["staging_smoke_pass"] == "TRUE"
        assert summary["staging_smoke_eligible_row_count"] == "2"
        assert summary["expected_eligible_row_count"] == "2"
        assert summary["expected_vs_staging_smoke_delta"] == "0"


def test_repair_smoke_does_not_mutate_production_certified_or_protected() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        prod8 = root / "outputs/v20/consolidation/V20_8_NORMALIZED_RESEARCH_DATASET.csv"
        prod9 = root / "outputs/v20/consolidation/V20_9_FACTOR_RESEARCH_BASE_DATASET.csv"
        v7x = root / "outputs/v20/consolidation/V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv"
        official = root / "outputs/v20/consolidation/V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
        before = (sha(prod8), sha(prod9), sha(v7x), sha(official))
        summary, _ = module.run_repair(root)
        assert before == (sha(prod8), sha(prod9), sha(v7x), sha(official))
        assert summary["production_v20_8_outputs_mutated"] == "FALSE"
        assert summary["production_v20_9_to_v20_16_outputs_mutated"] == "FALSE"
        assert summary["certified_v20_7x_outputs_mutated"] == "FALSE"
        assert summary["protected_outputs_mutated"] == "FALSE"


def test_permissions_false_and_required_summary_fields_present() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, _ = module.run_repair(root)
        for field in (
            "official_activation_allowed", "official_recommendation_allowed",
            "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
            "broker_execution_allowed", "trade_action_allowed",
        ):
            assert summary[field] == "FALSE"
        assert set(module.SUMMARY_FIELDS).issubset(summary)


def test_blocks_invalid_r3b_and_repeat_safe() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, r3b_valid=False)
        summary, _ = module.run_repair(root)
        assert summary["final_status"] == module.BLOCKED_R3B
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        first, _ = module.run_repair(root)
        second, _ = module.run_repair(root)
        assert first["final_status"] == second["final_status"]
        assert second["production_v20_8_outputs_mutated"] == "FALSE"


if __name__ == "__main__":
    test_r3b_absolute_binding_block_is_detected()
    test_v20_8_supports_input_and_output_override_after_repair()
    test_v20_8_staging_mode_writes_only_to_staging_directory()
    test_v20_8_dry_run_no_production_write_does_not_mutate()
    test_default_production_behavior_remains_callable_without_overrides()
    test_absolute_path_binding_removed_or_neutralized()
    test_staging_smoke_row_count_equals_expected_certified_count()
    test_repair_smoke_does_not_mutate_production_certified_or_protected()
    test_permissions_false_and_required_summary_fields_present()
    test_blocks_invalid_r3b_and_repeat_safe()
    print("PASS test_v20_8_r1_relative_path_and_staging_contract_repair")
