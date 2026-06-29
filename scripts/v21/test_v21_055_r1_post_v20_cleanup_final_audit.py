#!/usr/bin/env python
"""Tests for V21.055-R1 post-V20 cleanup final audit."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_055_r1_post_v20_cleanup_final_audit.py"
spec = importlib.util.spec_from_file_location("v21_055_r1", SCRIPT)
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


def fixture(
    root: Path, *, missing_input: bool = False, active: bool = False,
    archive_bad: bool = False, gap_missing: bool = False,
    original_present: bool = False, unapproved: bool = False,
    keep_missing: bool = False, protected_missing: bool = False,
    repeat_accounting: bool = True,
) -> dict[str, Path]:
    out = root / "outputs/v21/migration"
    archive = root / "archive/v20_legacy_archive/outputs/v20/A.csv"
    gap_root = root / "archive/v20_legacy_archive/delete_candidate_gap_repair"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text("main\n", encoding="utf-8")
    queue = []
    gap_rows = []
    delete_rows = []
    rollback_rows = []
    for index in range(117):
        original_rel = f"outputs/v20/staging/candidate_{index:03d}.tmp"
        archive_rel = f"archive/v20_legacy_archive/delete_candidate_gap_repair/{original_rel}"
        gap = root / archive_rel
        gap.parent.mkdir(parents=True, exist_ok=True)
        if not (gap_missing and index == 0):
            gap.write_text(f"{index}\n", encoding="utf-8")
        expected = sha(gap) if gap.exists() else hashlib.sha256(f"{index}\n".encode()).hexdigest()
        if original_present and index == 0:
            original = root / original_rel
            original.parent.mkdir(parents=True, exist_ok=True)
            original.write_text("0\n", encoding="utf-8")
        queue.append({"file_path": original_rel})
        gap_rows.append({"original_path": original_rel, "archive_path": archive_rel, "original_hash": expected, "archive_hash": expected, "hash_match": "TRUE"})
        delete_rows.append({"file_path": original_rel, "delete_status": "ALREADY_DELETED_REPEAT_SAFE"})
        rollback_rows.append({"original_path": original_rel, "archive_path": archive_rel, "original_hash": expected, "archive_hash": expected, "delete_status": "ALREADY_DELETED_REPEAT_SAFE"})
    if unapproved:
        delete_rows.append({"file_path": "outputs/v20/not_approved.csv", "delete_status": "DELETED"})
    keep = root / "outputs/v20/read_center/KEEP.md"
    keep.parent.mkdir(parents=True, exist_ok=True)
    if not keep_missing:
        keep.write_text("keep\n", encoding="utf-8")
    protected = root / "outputs/v20/V20_OFFICIAL_RANKING.csv"
    protected.parent.mkdir(parents=True, exist_ok=True)
    if not protected_missing:
        protected.write_text("official\n", encoding="utf-8")
    shared = root / "outputs/shared/manifest/A.csv"
    shared.parent.mkdir(parents=True, exist_ok=True)
    shared.write_text("shared\n", encoding="utf-8")
    active_file = root / "scripts/v21/current.py"
    active_file.parent.mkdir(parents=True, exist_ok=True)
    active_file.write_text('SRC="outputs/v20/A.csv"\n' if active else "VALUE=1\n", encoding="utf-8")

    write_rows(out / module.DELETE_SUMMARY, [{
        "final_status": "PASS_V20_DELETE_CANDIDATES_ARCHIVED_AND_DELETED",
        "delete_attempt_count": "0" if repeat_accounting else "117",
        "delete_success_count": "117", "deleted_file_count": "0" if repeat_accounting else "117",
    }])
    write_rows(out / module.GAP_COPY_LOG, [{"source_path": queue[0]["file_path"], "copy_status": "SOURCE_ALREADY_DELETED_ARCHIVE_VALIDATED"}])
    write_rows(out / module.GAP_HASHES, gap_rows)
    write_rows(out / module.DELETE_LOG, delete_rows)
    write_rows(out / module.POST_DELETE_AUDIT, [{"validation_item": "POST", "status": "PASS"}])
    write_rows(out / module.ROLLBACK, rollback_rows)
    write_rows(out / module.ARCHIVE_SUMMARY, [{"final_status": "PASS_V20_ARCHIVE_COMMITTED_READY_FOR_DELETE_CANDIDATE_DRY_RUN"}])
    expected_main = "bad" if archive_bad else sha(archive)
    write_rows(out / module.ARCHIVE_HASHES, [{"source_path": "outputs/v20/A.csv", "archive_path": "archive/v20_legacy_archive/outputs/v20/A.csv", "source_hash": expected_main}])
    write_rows(out / module.KEEP_VALIDATION, [{"file_path": "outputs/v20/read_center/KEEP.md", "hash_after": sha(keep) if keep.exists() else ""}])
    write_rows(out / module.PROTECTED_VALIDATION, [{"file_path": "outputs/v20/V20_OFFICIAL_RANKING.csv", "archive_path": "archive/v20_legacy_archive/outputs/v20/V20_OFFICIAL_RANKING.csv"}])
    write_rows(out / module.ISOLATION_SUMMARY, [{"final_status": "PARTIAL_PASS_V21_054_R1_SOURCE_ISOLATION_CONFIRMED_HISTORICAL_REFERENCES_REMAIN", "source_isolation_pass": "TRUE"}])
    write_rows(out / module.SHARED_HASHES, [{"target_path": "outputs/shared/manifest/A.csv", "target_hash": sha(shared), "source_path": "outputs/v20/A.csv"}])
    write_rows(out / module.QUEUE, queue)
    if missing_input:
        (out / module.ARCHIVE_SUMMARY).unlink()
    return {"archive": archive, "keep": keep, "protected": protected, "shared": shared, "active": active_file}


def test_blockers() -> None:
    cases = [
        ({"missing_input": True}, module.BLOCKED_INPUT),
        ({"active": True}, module.BLOCKED_ISOLATION),
        ({"archive_bad": True}, module.BLOCKED_ARCHIVE),
        ({"gap_missing": True}, module.BLOCKED_DELETE),
        ({"original_present": True}, module.BLOCKED_DELETE),
        ({"unapproved": True}, module.BLOCKED_UNAPPROVED),
        ({"keep_missing": True}, module.BLOCKED_KEEP),
        ({"protected_missing": True}, module.BLOCKED_PROTECTED),
    ]
    for options, expected in cases:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); fixture(root, **options)
            summary, _ = module.run_audit(root)
            assert summary["final_status"] == expected, (options, summary["final_status"])
            assert summary["cleanup_complete"] == "FALSE"


def test_reconciliation_no_mutation_permissions_and_repeat_safe() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root, repeat_accounting=True)
        before = {name: sha(path) for name, path in paths.items()}
        first, rows = module.run_audit(root)
        assert first["final_status"] == module.PARTIAL_STATUS
        assert first["delete_stat_discrepancy_found"] == "TRUE"
        assert first["delete_stat_discrepancy_reconciled"] == "TRUE"
        assert first["final_deleted_candidate_count"] == 117
        assert first["cleanup_complete"] == "TRUE"
        assert before == {name: sha(path) for name, path in paths.items()}
        assert any(row["status"] == "RECONCILED" for row in rows["reconciliation"])
        for field in (
            "files_deleted_or_moved_in_this_stage",
            "files_archived_or_copied_in_this_stage",
            "source_files_mutated_in_this_stage",
            "v20_outputs_mutated_in_this_stage",
            "v21_current_outputs_mutated_in_this_stage",
            "protected_outputs_mutated",
            "official_activation_allowed", "official_recommendation_allowed",
            "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
            "broker_execution_allowed", "trade_action_allowed",
        ):
            assert first[field] == "FALSE"
        assert set(module.SUMMARY_FIELDS).issubset(first)
        second, _ = module.run_audit(root)
        assert second["final_status"] == first["final_status"]
        assert second["cleanup_complete"] == "TRUE"


def test_clean_accounting_pass_and_mutation_detection() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, repeat_accounting=False)
        summary, _ = module.run_audit(root)
        assert summary["final_status"] == module.PASS_STATUS
        assert summary["delete_stat_discrepancy_found"] == "FALSE"
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        summary, _ = module.run_audit(root, mutation_hook=lambda: paths["protected"].write_text("changed\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_PROTECTED


if __name__ == "__main__":
    test_blockers()
    test_reconciliation_no_mutation_permissions_and_repeat_safe()
    test_clean_accounting_pass_and_mutation_detection()
    print("PASS test_v21_055_r1_post_v20_cleanup_final_audit")
