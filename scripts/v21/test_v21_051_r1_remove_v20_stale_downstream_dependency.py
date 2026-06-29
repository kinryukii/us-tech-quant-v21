#!/usr/bin/env python
"""Tests for V21.051-R1 stale V20 downstream dependency removal."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_051_r1_remove_v20_stale_downstream_dependency.py"
spec = importlib.util.spec_from_file_location("v21_051_r1", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(root: Path, *, unsafe: bool = False) -> tuple[Path, Path, Path]:
    (root / "scripts/v21").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v21/migration").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v21/context").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v20/consolidation").mkdir(parents=True, exist_ok=True)
    (root / "data/raw").mkdir(parents=True, exist_ok=True)
    write_rows(root / "outputs/v21/migration/V21_050_R1_V20_DEPENDENCY_MIGRATION_AND_CLEANUP_DRY_RUN_SUMMARY.csv", [{
        "final_status": "BLOCKED_V21_050_R1_V20_STALE_DOWNSTREAM_DEPENDENCY_FOUND",
        "recommended_next_stage": "V21_051_R1_REMOVE_V20_STALE_DOWNSTREAM_DEPENDENCY",
    }])
    write_rows(root / "outputs/v21/migration/V21_050_R1_V20_DEPENDENCY_AUDIT_BY_FILE.csv", [{
        "file_path": "outputs/v20/consolidation/V20_15_LIMITED_FACTOR_SCORE_LAYER.csv",
        "stale_lineage_risk": "HIGH",
        "reference_type": "V20_OUTPUT",
        "referenced_by_v21": "outputs/v21/review/V21_OLD_REPORT.csv|scripts/v21/v21_active_safe.py",
    }])
    write_rows(root / "outputs/v21/context/V21_048_R1_REPAIRED_CONTEXT_OBSERVATION_LEDGER.csv", [{"ticker": "A"}])
    write_rows(root / "outputs/v21/context/V21_049_R1_REPAIRED_CONTEXT_MATURITY_EVALUATION_SUMMARY.csv", [{"final_status": "PENDING"}])
    v20 = root / "outputs/v20/consolidation/V20_15_LIMITED_FACTOR_SCORE_LAYER.csv"
    official = root / "outputs/v20/consolidation/V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
    write_rows(v20, [{"ticker": "A"}])
    write_rows(official, [{"ticker": "A", "rank": "1"}])
    write_rows(root / "data/raw/price_universe.csv", [{"ticker": "A"}])
    safe_script = root / "scripts/v21/v21_active_safe.py"
    safe_script.write_text(
        'SOURCE = "outputs/v20/consolidation/V20_15_LIMITED_FACTOR_SCORE_LAYER.csv"\n'
        'RAW = "data/raw/price_universe.csv"\n',
        encoding="utf-8",
    )
    unsafe_script = root / "scripts/v21/v21_active_unsafe.py"
    if unsafe:
        unsafe_script.write_text('SOURCE = "outputs/v20/consolidation/V20_10_GATE_DECISION.csv"\n', encoding="utf-8")
    historical = root / "outputs/v21/review/V21_OLD_REPORT.csv"
    write_rows(historical, [{"source": "outputs/v20/consolidation/V20_8_NORMALIZED_RESEARCH_DATASET.csv"}])
    return safe_script, v20, official


def test_v21_050_block_read_and_stale_detected() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, repl, _ = module.run_repair(root)
        assert summary["source_v21_050_status"] == "BLOCKED_V21_050_R1_V20_STALE_DOWNSTREAM_DEPENDENCY_FOUND"
        assert summary["stale_dependency_found_before"] == "TRUE"
        assert repl


def test_safe_replacement_applied_and_shared_raw_preserved() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); script, _, _ = fixture(root)
        summary, _, _ = module.run_repair(root)
        text = script.read_text(encoding="utf-8")
        assert module.V21_NATIVE_LEDGER in text
        assert "data/raw/price_universe.csv" in text
        assert summary["v21_native_replacement_count"] == 1
        assert summary["shared_data_dependency_found_after"] == "TRUE"


def test_no_files_deleted_or_moved_and_outputs_not_mutated() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); _, v20, official = fixture(root)
        before_files = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
        before_hashes = (sha(v20), sha(official), sha(root / "outputs/v21/context/V21_048_R1_REPAIRED_CONTEXT_OBSERVATION_LEDGER.csv"))
        summary, _, _ = module.run_repair(root)
        after_files = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
        assert before_files.issubset(after_files)
        assert summary["files_deleted_or_moved"] == "FALSE"
        assert before_hashes == (sha(v20), sha(official), sha(root / "outputs/v21/context/V21_048_R1_REPAIRED_CONTEXT_OBSERVATION_LEDGER.csv"))
        assert summary["v20_outputs_mutated"] == "FALSE"
        assert summary["v21_current_outputs_mutated"] == "FALSE"
        assert summary["protected_outputs_mutated"] == "FALSE"


def test_remaining_active_stale_dependency_blocks() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, unsafe=True)
        summary, _, _ = module.run_repair(root)
        assert summary["final_status"] == module.BLOCKED_UNSAFE
        assert summary["stale_dependency_remaining_count"] == 1


def test_historical_manual_review_can_remain() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, _, audit = module.run_repair(root)
        assert summary["final_status"] == module.PARTIAL_STATUS
        assert summary["stale_dependency_reference_count_after"] == 0
        assert any(row["active_current_source"] == "FALSE" and row["manual_review_required"] == "TRUE" for row in audit)


def test_protected_mutation_detection_permissions_fields_and_repeat_safe() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); _, _, official = fixture(root)
        summary, _, _ = module.run_repair(root, protected_mutation_hook=lambda: official.write_text("ticker,rank\nA,2\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_PROTECTED
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        first, _, _ = module.run_repair(root)
        second, _, _ = module.run_repair(root)
        assert first["final_status"] == second["final_status"]
        assert set(module.SUMMARY_FIELDS).issubset(second)
        for field in (
            "official_activation_allowed", "official_recommendation_allowed",
            "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
            "broker_execution_allowed", "trade_action_allowed",
        ):
            assert second[field] == "FALSE"


if __name__ == "__main__":
    test_v21_050_block_read_and_stale_detected()
    test_safe_replacement_applied_and_shared_raw_preserved()
    test_no_files_deleted_or_moved_and_outputs_not_mutated()
    test_remaining_active_stale_dependency_blocks()
    test_historical_manual_review_can_remain()
    test_protected_mutation_detection_permissions_fields_and_repeat_safe()
    print("PASS test_v21_051_r1_remove_v20_stale_downstream_dependency")
