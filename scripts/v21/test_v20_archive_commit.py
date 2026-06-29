#!/usr/bin/env python
"""Tests for V20_ARCHIVE_COMMIT."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v20_archive_commit.py"
spec = importlib.util.spec_from_file_location("v20_archive_commit", SCRIPT)
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


def manifest_row(path: str, package: str = "v20-legacy-outputs", *, protected: str = "FALSE", active: str = "FALSE") -> dict[str, str]:
    return {
        "file_path": path, "file_type": "csv", "size_mb": "0.001",
        "last_modified": "2026-06-19T00:00:00+00:00",
        "archive_class": "LEGACY_V20_OUTPUT", "archive_reason": "fixture",
        "proposed_archive_package": package, "protected_flag": protected,
        "active_v21_dependency_flag": active, "historical_reference_flag": "FALSE",
        "future_delete_candidate_flag": "FALSE", "risk_level": "LOW",
    }


def fixture(
    root: Path,
    *,
    ready: bool = True,
    unsafe: bool = False,
    protected_overlap: bool = False,
    isolation_bad: str = "",
) -> dict[str, Path]:
    out = root / "outputs/v21/migration"
    (root / "outputs/v20/diagnostics").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v20/read_center").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v20/price_history").mkdir(parents=True, exist_ok=True)
    (root / "scripts/v21").mkdir(parents=True, exist_ok=True)
    source = root / "outputs/v20/diagnostics/V20_A.csv"
    source.write_text("x\n1\n", encoding="utf-8")
    keep = root / "outputs/v20/read_center/V20_16_R4_CLOSEOUT.md"
    keep.write_text("# keep\n", encoding="utf-8")
    protected = root / "outputs/v20/price_history/V20_RAW_PRICE_HISTORY.csv"
    protected.write_text("date,close\n", encoding="utf-8")
    active = root / "scripts/v21/current.py"
    active.write_text("VALUE = 1\n", encoding="utf-8")
    if isolation_bad == "script":
        active.write_text('SRC = "scripts/v20/a.py"\n', encoding="utf-8")
    elif isolation_bad == "output":
        active.write_text('SRC = "outputs/v20/a.csv"\n', encoding="utf-8")
    elif isolation_bad == "stale":
        active.write_text('SRC = "outputs/v20/V20_16_A.csv"\n', encoding="utf-8")

    write_rows(out / module.DRY_RUN_SUMMARY, [{
        "final_status": "PARTIAL_PASS_V20_ARCHIVE_DRY_RUN_READY_WITH_KEEP_REFERENCES" if ready else "BLOCKED",
        "ready_for_v20_archive_commit": "TRUE" if ready else "FALSE",
        "unsafe_archive_candidate_count": "0",
        "source_isolation_pass": "TRUE",
        "v21_active_current_reads_v20_scripts": "FALSE",
        "v21_active_current_reads_v20_outputs": "FALSE",
        "v21_active_current_reads_v20_8_to_v20_16_stale_downstream": "FALSE",
        "v20_outputs_mutated": "FALSE", "v21_current_outputs_mutated": "FALSE",
        "protected_outputs_mutated": "FALSE", "archive_candidate_count": "1",
        "keep_reference_count": "1", "protected_never_archive_count": "1",
        "future_delete_candidate_count": "1",
    }])
    candidate = manifest_row("outputs/v20/diagnostics/V20_A.csv", active="TRUE" if unsafe else "FALSE")
    write_rows(out / module.ARCHIVE_MANIFEST, [candidate])
    write_rows(out / module.KEEP_MANIFEST, [manifest_row("outputs/v20/read_center/V20_16_R4_CLOSEOUT.md")])
    protected_path = "outputs/v20/diagnostics/V20_A.csv" if protected_overlap else "outputs/v20/price_history/V20_RAW_PRICE_HISTORY.csv"
    write_rows(out / module.PROTECTED_MANIFEST, [manifest_row(protected_path, protected="TRUE")])
    write_rows(out / module.DELETE_QUEUE, [manifest_row("outputs/v20/staging/V20_TEMP.csv")])
    write_rows(out / module.PACKAGE_PLAN, [{
        "package_name": "v20-legacy-outputs", "package_scope": "LEGACY_V20_OUTPUT",
        "file_count": "1", "estimated_size_mb": "0.001", "package_reason": "fixture",
    }])
    write_rows(out / module.RISK_AUDIT, [{
        "risk_id": "SOURCE_INPUT", "status": "PASS", "severity": "LOW",
        "file_path": "", "finding": "ok", "mitigation": "",
    }])
    write_rows(out / module.ISOLATION_SUMMARY, [{
        "source_isolation_pass": "TRUE",
        "v21_active_current_reads_v20_scripts": "FALSE",
        "v21_active_current_reads_v20_outputs": "FALSE",
        "v21_active_current_reads_v20_8_to_v20_16_stale_downstream": "FALSE",
    }])
    return {"source": source, "keep": keep, "protected": protected, "active": active}


def test_ready_unsafe_and_protected_overlap_block() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, ready=False)
        summary, _ = module.run_archive_commit(root)
        assert summary["final_status"] == module.BLOCKED_INPUT
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, unsafe=True)
        summary, _ = module.run_archive_commit(root)
        assert summary["final_status"] == module.BLOCKED_UNSAFE
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, protected_overlap=True)
        summary, _ = module.run_archive_commit(root)
        assert summary["final_status"] == module.BLOCKED_PROTECTED_ATTEMPT


def test_copy_relative_path_hash_keep_protected_and_repeat_safe() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        before = {name: sha(path) for name, path in paths.items()}
        first, rows = module.run_archive_commit(root)
        archived = root / module.ARCHIVE_ROOT_REL / "outputs/v20/diagnostics/V20_A.csv"
        assert archived.is_file()
        assert sha(archived) == sha(paths["source"])
        assert before == {name: sha(path) for name, path in paths.items()}
        assert first["final_status"] == module.PASS_STATUS
        assert first["archive_copy_success_count"] == 1
        assert first["archive_hash_validated_count"] == 1
        assert first["keep_reference_validation_pass"] == "TRUE"
        assert first["protected_path_archived_count"] == 0
        assert first["protected_path_validation_pass"] == "TRUE"
        assert paths["source"].exists() and paths["keep"].exists()
        assert first["files_deleted_or_moved"] == "FALSE"
        assert first["source_files_mutated"] == "FALSE"
        assert first["v20_outputs_mutated"] == "FALSE"
        assert first["v21_current_outputs_mutated"] == "FALSE"
        assert first["protected_outputs_mutated"] == "FALSE"
        assert rows["packages"][0]["package_status"] == "PASS"
        second, _ = module.run_archive_commit(root)
        assert second["final_status"] == first["final_status"]
        assert second["archive_copy_success_count"] == 1
        assert set(module.SUMMARY_FIELDS).issubset(second)
        for field in (
            "official_activation_allowed", "official_recommendation_allowed",
            "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
            "broker_execution_allowed", "trade_action_allowed",
        ):
            assert second[field] == "FALSE"


def test_hash_mismatch_missing_copy_and_source_isolation_regression() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        def corrupt(archive_root: Path) -> None:
            (archive_root / "outputs/v20/diagnostics/V20_A.csv").write_text("bad\n", encoding="utf-8")
        summary, _ = module.run_archive_commit(root, after_copy_hook=corrupt)
        assert summary["final_status"] == module.BLOCKED_HASH
        assert summary["archive_hash_mismatch_count"] == 1
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        def remove(archive_root: Path) -> None:
            (archive_root / "outputs/v20/diagnostics/V20_A.csv").unlink()
        summary, _ = module.run_archive_commit(root, after_copy_hook=remove)
        assert summary["final_status"] == module.BLOCKED_COPY
        assert summary["missing_archive_copy_count"] == 1
    for kind, field in (
        ("script", "v21_active_current_reads_v20_scripts_after_archive"),
        ("output", "v21_active_current_reads_v20_outputs_after_archive"),
        ("stale", "v21_active_current_reads_v20_8_to_v20_16_stale_downstream_after_archive"),
    ):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); fixture(root, isolation_bad=kind)
            summary, _ = module.run_archive_commit(root)
            assert summary["final_status"] == module.BLOCKED_ISOLATION
            assert summary[field] == "TRUE"


def test_mutation_guards() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        summary, _ = module.run_archive_commit(root, mutation_hook=lambda: paths["source"].write_text("changed\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_V20
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        summary, _ = module.run_archive_commit(root, mutation_hook=lambda: paths["active"].write_text("CHANGED=1\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_FILE
        assert summary["source_files_mutated"] == "TRUE"
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        summary, _ = module.run_archive_commit(root, mutation_hook=lambda: paths["protected"].write_text("changed\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_PROTECTED


if __name__ == "__main__":
    test_ready_unsafe_and_protected_overlap_block()
    test_copy_relative_path_hash_keep_protected_and_repeat_safe()
    test_hash_mismatch_missing_copy_and_source_isolation_regression()
    test_mutation_guards()
    print("PASS test_v20_archive_commit")
