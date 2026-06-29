#!/usr/bin/env python
"""Tests for the V20 delete-candidate gap repair and commit."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v20_delete_candidate_archive_gap_repair_and_commit.py"
spec = importlib.util.spec_from_file_location("gap_commit", SCRIPT)
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


def row(path: str) -> dict[str, str]:
    return {"file_path": path, "size_mb": "0.00001", "future_delete_candidate_flag": "TRUE"}


def fixture(
    root: Path,
    *,
    valid_dry: bool = True,
    valid_archive: bool = True,
    keep_overlap: bool = False,
    protected_overlap: bool = False,
    active_overlap: bool = False,
    isolation_bad: bool = False,
) -> dict[str, object]:
    out = root / "outputs/v21/migration"
    queue_paths = []
    for index in range(module.EXPECTED_QUEUE_COUNT):
        prefix = "scripts/v20" if index < 20 else "outputs/v20/staging"
        path = f"{prefix}/candidate_{index:03d}.tmp"
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{index}\n", encoding="utf-8")
        queue_paths.append(path)
    keep = root / "outputs/v20/read_center/V20_16_R4_CLOSEOUT.md"
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_text("# keep\n", encoding="utf-8")
    protected = root / "outputs/v20/V20_OFFICIAL_RANKING.csv"
    protected.write_text("ticker,rank\nA,1\n", encoding="utf-8")
    unrelated = root / "outputs/v20/unrelated.csv"
    unrelated.write_text("safe\n", encoding="utf-8")
    active = root / "scripts/v21/current.py"
    active.parent.mkdir(parents=True, exist_ok=True)
    if active_overlap:
        active.write_text(f'SRC = "{queue_paths[0]}"\n', encoding="utf-8")
    elif isolation_bad:
        active.write_text('SRC = "outputs/v20/V20_16_OTHER.csv"\n', encoding="utf-8")
    else:
        active.write_text("VALUE = 1\n", encoding="utf-8")

    write_rows(out / module.DRY_SUMMARY, [{
        "final_status": "BLOCKED_V20_DELETE_CANDIDATE_DRY_RUN_ARCHIVE_VALIDATION_FAILED" if valid_dry else "PASS",
        "candidate_queue_count": "117", "missing_archive_for_deletion_candidate_count": "117",
        "keep_reference_overlap_count": "0", "protected_overlap_count": "0",
        "active_v21_dependency_overlap_count": "0", "source_isolation_pass": "TRUE",
        "v20_outputs_mutated": "FALSE", "v21_current_outputs_mutated": "FALSE",
        "protected_outputs_mutated": "FALSE",
    }])
    write_rows(out / module.ARCHIVE_SUMMARY, [{
        "final_status": "PASS_V20_ARCHIVE_COMMITTED_READY_FOR_DELETE_CANDIDATE_DRY_RUN" if valid_archive else "BLOCKED",
        "source_isolation_pass_after_archive": "TRUE", "protected_path_archived_count": "0",
        "archive_hash_mismatch_count": "0", "missing_archive_copy_count": "0",
    }])
    write_rows(out / module.QUEUE, [row(path) for path in queue_paths])
    keep_path = queue_paths[0] if keep_overlap else "outputs/v20/read_center/V20_16_R4_CLOSEOUT.md"
    protected_path = queue_paths[1] if protected_overlap else "outputs/v20/V20_OFFICIAL_RANKING.csv"
    write_rows(out / module.KEEP, [row(keep_path)])
    write_rows(out / module.PROTECTED, [row(protected_path)])
    write_rows(out / module.ARCHIVE_HASHES, [{"source_path": "outputs/v20/legacy.csv", "hash_match": "TRUE"}])
    write_rows(out / module.ISOLATION_SUMMARY, [{"source_isolation_pass": "TRUE"}])
    return {
        "queue": queue_paths, "keep": keep, "protected": protected,
        "unrelated": unrelated, "active": active,
    }


def test_required_states_and_overlaps_block() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, valid_dry=False)
        summary, _ = module.run_commit(root)
        assert summary["final_status"] == module.BLOCKED_INPUT
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, valid_archive=False)
        summary, _ = module.run_commit(root)
        assert summary["final_status"] == module.BLOCKED_INPUT
    for option, expected in (
        ("keep_overlap", module.BLOCKED_OVERLAP),
        ("protected_overlap", module.BLOCKED_OVERLAP),
        ("active_overlap", module.BLOCKED_ACTIVE),
        ("isolation_bad", module.BLOCKED_ISOLATION),
    ):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); fixture(root, **{option: True})
            summary, _ = module.run_commit(root)
            assert summary["final_status"] == expected
            assert all((root / path).exists() for path in fixture_paths(root))


def fixture_paths(root: Path) -> list[str]:
    rows, _ = module.read_csv(root / "outputs/v21/migration" / module.QUEUE)
    return [item["file_path"] for item in rows]


def test_hash_mismatch_blocks_before_delete() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        def corrupt(gap_root: Path) -> None:
            (gap_root / "scripts/v20/candidate_000.tmp").write_text("bad\n", encoding="utf-8")
        summary, _ = module.run_commit(root, before_delete_hook=corrupt)
        assert summary["final_status"] == module.BLOCKED_ARCHIVE
        assert summary["delete_attempt_count"] == 0
        assert all((root / path).exists() for path in fixture_paths(root))


def test_exact_deletion_boundary_archives_post_validation_and_repeat_safe() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        protected_hash = sha(paths["protected"])
        unrelated_hash = sha(paths["unrelated"])
        first, rows = module.run_commit(root)
        assert first["final_status"] == module.PASS_STATUS
        assert first["candidate_queue_count"] == 117
        assert first["gap_archive_hash_validated_count"] == 117
        assert first["delete_attempt_count"] == 117
        assert first["delete_success_count"] == 117
        assert first["deleted_file_count"] == 117
        assert all(not (root / path).exists() for path in paths["queue"])
        assert all((root / module.GAP_ARCHIVE_ROOT_REL / path).exists() for path in paths["queue"])
        assert paths["unrelated"].exists() and sha(paths["unrelated"]) == unrelated_hash
        assert paths["keep"].exists()
        assert paths["protected"].exists() and sha(paths["protected"]) == protected_hash
        assert first["source_isolation_pass_after_delete"] == "TRUE"
        assert first["post_delete_validation_pass"] == "TRUE"
        assert len(rows["rollback"]) == 117
        assert set(module.SUMMARY_FIELDS).issubset(first)
        for field in (
            "official_activation_allowed", "official_recommendation_allowed",
            "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
            "broker_execution_allowed", "trade_action_allowed",
        ):
            assert first[field] == "FALSE"
        second, _ = module.run_commit(root)
        assert second["final_status"] == module.PASS_STATUS
        assert second["delete_attempt_count"] == 0
        assert second["delete_success_count"] == 117
        assert second["deleted_file_count"] == 0


def test_post_delete_missing_archive_and_protected_mutation_block() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        def remove_archive(gap_root: Path) -> None:
            (gap_root / "scripts/v20/candidate_000.tmp").unlink()
        summary, _ = module.run_commit(root, after_delete_hook=remove_archive)
        assert summary["final_status"] == module.BLOCKED_POST
        assert summary["post_delete_validation_pass"] == "FALSE"
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        def mutate_protected(_: Path) -> None:
            paths["protected"].write_text("ticker,rank\nA,2\n", encoding="utf-8")
        summary, _ = module.run_commit(root, after_delete_hook=mutate_protected)
        assert summary["final_status"] == module.BLOCKED_PROTECTED


if __name__ == "__main__":
    test_required_states_and_overlaps_block()
    test_hash_mismatch_blocks_before_delete()
    test_exact_deletion_boundary_archives_post_validation_and_repeat_safe()
    test_post_delete_missing_archive_and_protected_mutation_block()
    print("PASS test_v20_delete_candidate_archive_gap_repair_and_commit")
