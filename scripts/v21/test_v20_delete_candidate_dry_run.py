#!/usr/bin/env python
"""Tests for V20_DELETE_CANDIDATE_DRY_RUN."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v20_delete_candidate_dry_run.py"
spec = importlib.util.spec_from_file_location("v20_delete_candidate_dry_run", SCRIPT)
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


def queue_row(path: str) -> dict[str, str]:
    return {
        "file_path": path, "file_type": "csv", "size_mb": "0.000004",
        "last_modified": "2026-06-19T00:00:00+00:00",
        "archive_class": "FUTURE_DELETE_CANDIDATE_DRY_RUN_ONLY",
        "archive_reason": "fixture", "proposed_archive_package": "",
        "protected_flag": "FALSE", "active_v21_dependency_flag": "FALSE",
        "historical_reference_flag": "FALSE",
        "future_delete_candidate_flag": "TRUE", "risk_level": "MEDIUM",
    }


def fixture(
    root: Path,
    *,
    ready: bool = True,
    missing_archive: bool = False,
    hash_mismatch: bool = False,
    keep_overlap: bool = False,
    protected_overlap: bool = False,
    active_overlap: bool = False,
    isolation_bad: bool = False,
) -> dict[str, Path]:
    out = root / "outputs/v21/migration"
    source = root / "outputs/v20/staging/V20_TEMP.csv"
    archive = root / "archive/v20_legacy_archive/outputs/v20/staging/V20_TEMP.csv"
    source.parent.mkdir(parents=True, exist_ok=True)
    archive.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("x\n", encoding="utf-8")
    if not missing_archive:
        archive.write_text("bad\n" if hash_mismatch else "x\n", encoding="utf-8")
    active = root / "scripts/v21/current.py"
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_text(
        'SRC = "outputs/v20/staging/V20_TEMP.csv"\n'
        if active_overlap else
        'SRC = "outputs/v20/V20_16_OTHER.csv"\n'
        if isolation_bad else "VALUE = 1\n",
        encoding="utf-8",
    )
    official = root / "outputs/v20/V20_OFFICIAL_RANKING.csv"
    official.write_text("ticker,rank\nA,1\n", encoding="utf-8")
    source_hash = sha(source)
    archive_hash = sha(archive) if archive.exists() else ""
    write_rows(out / module.COMMIT_SUMMARY, [{
        "final_status": "PASS_V20_ARCHIVE_COMMITTED_READY_FOR_DELETE_CANDIDATE_DRY_RUN" if ready else "BLOCKED",
        "ready_for_v20_delete_candidate_dry_run": "TRUE" if ready else "FALSE",
        "archive_root": "archive/v20_legacy_archive",
        "archive_copy_success_count": "1", "archive_copy_failure_count": "0",
        "archive_hash_mismatch_count": "0", "missing_archive_copy_count": "0",
        "protected_path_archived_count": "0", "source_isolation_pass_after_archive": "TRUE",
        "v20_outputs_mutated": "FALSE", "v21_current_outputs_mutated": "FALSE",
        "protected_outputs_mutated": "FALSE",
    }])
    write_rows(out / module.COPY_LOG, [{
        "source_path": "outputs/v20/staging/V20_TEMP.csv",
        "archive_path": "archive/v20_legacy_archive/outputs/v20/staging/V20_TEMP.csv",
        "source_size_bytes": "2", "archive_size_bytes": "2",
        "source_hash": source_hash, "archive_hash": archive_hash,
        "copy_status": "COPIED", "error": "",
    }])
    write_rows(out / module.HASH_MANIFEST, [{
        "source_path": "outputs/v20/staging/V20_TEMP.csv",
        "archive_path": "archive/v20_legacy_archive/outputs/v20/staging/V20_TEMP.csv",
        "source_hash": source_hash, "archive_hash": archive_hash,
        "source_size_bytes": "2", "archive_size_bytes": "2",
        "hash_match": "TRUE" if not missing_archive and not hash_mismatch else "FALSE",
        "validation_status": "PASS" if not missing_archive and not hash_mismatch else "MISSING_ARCHIVE_COPY" if missing_archive else "HASH_MISMATCH",
    }])
    write_rows(out / module.PACKAGE_MANIFEST, [{"package_name": "temp", "package_status": "PASS"}])
    write_rows(out / module.COMMIT_AUDIT, [{"validation_item": "SOURCE_INPUTS", "status": "PASS", "count": "0", "details": "ok"}])
    write_rows(out / module.COMMIT_KEEP_VALIDATION, [{"file_path": "keep.md", "validation_status": "PASS"}])
    write_rows(out / module.COMMIT_PROTECTED_VALIDATION, [{"file_path": "protected.csv", "validation_status": "PASS"}])
    write_rows(out / module.DELETE_QUEUE, [queue_row("outputs/v20/staging/V20_TEMP.csv")])
    keep_path = "outputs/v20/staging/V20_TEMP.csv" if keep_overlap else "outputs/v20/read_center/KEEP.md"
    protected_path = "outputs/v20/staging/V20_TEMP.csv" if protected_overlap else "outputs/v20/V20_OFFICIAL_RANKING.csv"
    write_rows(out / module.KEEP_MANIFEST, [queue_row(keep_path)])
    write_rows(out / module.PROTECTED_MANIFEST, [queue_row(protected_path)])
    write_rows(out / module.ISOLATION_SUMMARY, [{"source_isolation_pass": "TRUE"}])
    return {"source": source, "archive": archive, "active": active, "official": official}


def test_ready_archive_and_overlap_blockers() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, ready=False)
        summary, _ = module.run_delete_candidate_dry_run(root)
        assert summary["final_status"] == module.BLOCKED_INPUT
    for option, expected in (
        ("missing_archive", module.BLOCKED_ARCHIVE),
        ("hash_mismatch", module.BLOCKED_ARCHIVE),
        ("keep_overlap", module.BLOCKED_OVERLAP),
        ("protected_overlap", module.BLOCKED_OVERLAP),
        ("active_overlap", module.BLOCKED_ACTIVE),
    ):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); fixture(root, **{option: True})
            summary, _ = module.run_delete_candidate_dry_run(root)
            assert summary["final_status"] == expected


def test_source_isolation_regression_blocks() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, isolation_bad=True)
        summary, _ = module.run_delete_candidate_dry_run(root)
        assert summary["final_status"] == module.BLOCKED_ISOLATION
        assert summary["source_isolation_pass"] == "FALSE"


def test_success_no_mutation_permissions_outputs_and_repeat_safe() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        before = {name: sha(path) for name, path in paths.items()}
        first, rows = module.run_delete_candidate_dry_run(root)
        assert first["final_status"] == module.PASS_STATUS
        assert first["deletion_candidate_count"] == 1
        assert first["archive_validated_deletion_candidate_count"] == 1
        assert first["ready_for_v20_delete_commit"] == "TRUE"
        assert rows["manifest"][0]["deletion_candidate_status"] == "SAFE_DELETE_CANDIDATE_DRY_RUN_ONLY"
        assert before == {name: sha(path) for name, path in paths.items()}
        for field in (
            "files_deleted_or_moved", "files_archived", "files_copied",
            "source_files_mutated", "v20_outputs_mutated",
            "v21_current_outputs_mutated", "protected_outputs_mutated",
            "deletion_allowed", "archive_allowed", "migration_allowed",
            "official_activation_allowed", "official_recommendation_allowed",
            "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
            "broker_execution_allowed", "trade_action_allowed",
        ):
            assert first[field] == "FALSE"
        assert set(module.SUMMARY_FIELDS).issubset(first)
        for name in module.OUTPUT_NAMES:
            base = root / ("outputs/v21/read_center" if name.endswith(".md") else "outputs/v21/migration")
            assert (base / name).exists()
        second, _ = module.run_delete_candidate_dry_run(root)
        assert second["final_status"] == first["final_status"]
        assert second["deletion_candidate_count"] == first["deletion_candidate_count"]


def test_mutation_guards() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        summary, _ = module.run_delete_candidate_dry_run(root, mutation_hook=lambda: paths["source"].write_text("changed\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_V20
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        summary, _ = module.run_delete_candidate_dry_run(root, mutation_hook=lambda: paths["active"].write_text("CHANGED=1\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_FILE
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        summary, _ = module.run_delete_candidate_dry_run(root, mutation_hook=lambda: paths["official"].write_text("ticker,rank\nA,2\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_PROTECTED


if __name__ == "__main__":
    test_ready_archive_and_overlap_blockers()
    test_source_isolation_regression_blocks()
    test_success_no_mutation_permissions_outputs_and_repeat_safe()
    test_mutation_guards()
    print("PASS test_v20_delete_candidate_dry_run")
