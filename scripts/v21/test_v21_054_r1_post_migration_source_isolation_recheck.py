#!/usr/bin/env python
"""Tests for V21.054-R1 post-migration source isolation recheck."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_054_r1_post_migration_source_isolation_recheck.py"
spec = importlib.util.spec_from_file_location("v21_054_r1", SCRIPT)
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


def fixture(root: Path, *, committed: bool = True, missing: bool = False, mismatch: bool = False, active: str = "", historical: bool = True) -> dict[str, Path]:
    out = root / "outputs/v21/migration"
    out.mkdir(parents=True, exist_ok=True)
    (root / "outputs/shared/manifest").mkdir(parents=True, exist_ok=True)
    (root / "scripts/v21").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v21/read_center").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v20/consolidation").mkdir(parents=True, exist_ok=True)
    target = root / "outputs/shared/manifest/A.csv"
    target.write_text("alpha\n", encoding="utf-8")
    expected = hashlib.sha256(target.read_bytes()).hexdigest()
    if mismatch:
        target.write_text("changed\n", encoding="utf-8")
    if missing:
        target.unlink()
    write_rows(out / "V21_053_R2_SHARED_DEPENDENCY_MIGRATION_COMMIT_SUMMARY.csv", [{
        "final_status": "PASS_V21_053_R2_SHARED_DEPENDENCY_MIGRATION_COMMITTED" if committed else "BLOCKED",
        "copy_failure_count": "0",
        "copied_file_count": "1",
        "v20_outputs_mutated": "FALSE",
        "v21_current_outputs_mutated": "FALSE",
        "protected_outputs_mutated": "FALSE",
        "post_migration_v21_reads_v20_scripts": "FALSE",
        "post_migration_v21_reads_v20_outputs_as_current_source": "FALSE",
        "post_migration_shared_dependency_ok": "TRUE",
    }])
    write_rows(out / "V21_053_R2_TARGET_HASH_MANIFEST.csv", [{
        "target_path": "outputs/shared/manifest/A.csv",
        "source_path": "outputs/v20/consolidation/A.csv",
        "source_hash": expected,
        "target_hash": expected,
        "hash_match": "TRUE",
    }])
    active_file = root / "scripts/v21/v21_active.py"
    active_file.write_text("VALUE = 1\n", encoding="utf-8")
    if active == "script":
        active_file.write_text('SRC = "scripts/v20/helper.py"\n', encoding="utf-8")
    elif active == "output":
        active_file.write_text('SRC = "outputs/v20/consolidation/V20_7X.csv"\n', encoding="utf-8")
    elif active == "stale":
        active_file.write_text('SRC = "outputs/v20/consolidation/V20_16_GATE_DECISION.csv"\n', encoding="utf-8")
    if historical:
        (root / "outputs/v21/read_center/history.md").write_text("outputs/v20/consolidation/V20_108_FACTOR.csv\noutputs/v20/consolidation/V20_166_FACTOR.csv\n", encoding="utf-8")
    v20 = root / "outputs/v20/consolidation/V20_16_GATE_DECISION.csv"
    official = root / "outputs/v20/consolidation/V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
    v20.write_text("ticker\nA\n", encoding="utf-8")
    official.write_text("ticker,rank\nA,1\n", encoding="utf-8")
    return {"target": target, "v20": v20, "official": official, "active": active_file, "v21_current": out / "V21_053_R2_SHARED_DEPENDENCY_MIGRATION_COMMIT_SUMMARY.csv"}


def test_committed_state_required_missing_and_hash_mismatch_block() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, committed=False)
        summary, _ = module.run_recheck(root)
        assert summary["final_status"] == module.BLOCKED_INPUT
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, missing=True)
        summary, _ = module.run_recheck(root)
        assert summary["final_status"] == module.BLOCKED_TARGET
        assert summary["missing_copied_target_count"] == 1
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, mismatch=True)
        summary, _ = module.run_recheck(root)
        assert summary["final_status"] == module.BLOCKED_TARGET
        assert summary["copied_file_hash_mismatch_count"] == 1


def test_active_dependency_blockers_and_exact_stage_matching() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, active="script")
        summary, _ = module.run_recheck(root)
        assert summary["final_status"] == module.BLOCKED_ACTIVE
        assert summary["v21_active_current_reads_v20_scripts"] == "TRUE"
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, active="output")
        summary, _ = module.run_recheck(root)
        assert summary["final_status"] == module.BLOCKED_ACTIVE
        assert summary["v21_active_current_reads_v20_outputs"] == "TRUE"
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, active="stale")
        summary, _ = module.run_recheck(root)
        assert summary["final_status"] == module.BLOCKED_STALE
        assert summary["v21_active_current_reads_v20_8_to_v20_16_stale_downstream"] == "TRUE"
    assert not module.corrected_stale_stage_reference("V20_108_FACTOR.csv")
    assert not module.corrected_stale_stage_reference("V20_166_FACTOR.csv")


def test_historical_refs_do_not_block_and_archive_ready() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, historical=True)
        summary, _ = module.run_recheck(root)
        assert summary["final_status"] == module.PARTIAL_STATUS
        assert summary["source_isolation_pass"] == "TRUE"
        assert summary["ready_for_v20_archive_dry_run"] == "TRUE"
        assert summary["ready_for_v20_delete_candidate_dry_run"] == "FALSE"
        assert int(summary["harmless_historical_v20_reference_count"]) >= 1


def test_no_file_operations_or_mutations_and_repeat_safe() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        before_files = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
        before_hashes = (sha(paths["v20"]), sha(paths["official"]), sha(paths["active"]), sha(paths["v21_current"]))
        summary, _ = module.run_recheck(root)
        after_files = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
        assert before_files.issubset(after_files)
        assert before_hashes == (sha(paths["v20"]), sha(paths["official"]), sha(paths["active"]), sha(paths["v21_current"]))
        assert summary["files_deleted_or_moved"] == "FALSE"
        assert summary["files_archived"] == "FALSE"
        assert summary["files_copied"] == "FALSE"
        assert summary["source_files_mutated"] == "FALSE"
        assert summary["v20_outputs_mutated"] == "FALSE"
        assert summary["v21_current_outputs_mutated"] == "FALSE"
        assert summary["protected_outputs_mutated"] == "FALSE"
        first = summary
        second, _ = module.run_recheck(root)
        assert first["final_status"] == second["final_status"]
        assert set(module.SUMMARY_FIELDS).issubset(second)
        for name in (
            "V21_054_R1_ACTIVE_SOURCE_DEPENDENCY_AUDIT.csv",
            "V21_054_R1_HARMLESS_HISTORICAL_V20_REFERENCES.csv",
            "V21_054_R1_SHARED_TARGET_VALIDATION_AUDIT.csv",
            "V21_054_R1_V20_ARCHIVE_READINESS_AUDIT.csv",
        ):
            assert (root / "outputs/v21/migration" / name).exists()
        for field in (
            "official_activation_allowed", "official_recommendation_allowed",
            "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
            "broker_execution_allowed", "trade_action_allowed",
        ):
            assert second[field] == "FALSE"
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        summary, _ = module.run_recheck(root, protected_mutation_hook=lambda: paths["official"].write_text("ticker,rank\nA,2\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_PROTECTED


if __name__ == "__main__":
    test_committed_state_required_missing_and_hash_mismatch_block()
    test_active_dependency_blockers_and_exact_stage_matching()
    test_historical_refs_do_not_block_and_archive_ready()
    test_no_file_operations_or_mutations_and_repeat_safe()
    print("PASS test_v21_054_r1_post_migration_source_isolation_recheck")
