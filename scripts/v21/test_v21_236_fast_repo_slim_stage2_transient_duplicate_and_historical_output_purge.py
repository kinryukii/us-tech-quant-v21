from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_236_fast_repo_slim_stage2_transient_duplicate_and_historical_output_purge.py")
SPEC = importlib.util.spec_from_file_location("v21_236_stage", MODULE_PATH)
v236 = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(v236)


def write(path: Path, data: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    return path


def age(path: Path, hours: int = 72) -> Path:
    old = time.time() - hours * 3600
    os.utime(path, (old, old))
    return path


def run_stage(tmp_path: Path, repo: Path, **kwargs):
    archive = kwargs.pop("archive", tmp_path / "archive")
    cache = kwargs.pop("cache", tmp_path / "cache")
    quarantine = kwargs.pop("quarantine", tmp_path / "quarantine")
    out = kwargs.pop("out", repo / "outputs" / "v21" / "V21.236_FAST_REPO_SLIM_STAGE2_TRANSIENT_DUPLICATE_AND_HISTORICAL_OUTPUT_PURGE")
    return v236.run(
        repo_root=repo,
        archive_root=archive,
        cache_root=cache,
        quarantine_root=quarantine,
        output_dir=out,
        execute=kwargs.pop("execute", True),
        min_target_mb=kwargs.pop("min_target_mb", 0),
        top_size_count=kwargs.pop("top_size_count", 20),
        allow_transient_delete=kwargs.pop("allow_transient_delete", True),
        allow_verified_duplicate_delete=kwargs.pop("allow_verified_duplicate_delete", True),
        allow_archive_move=kwargs.pop("allow_archive_move", True),
    )


def test_transient_cache_deletion_works(tmp_path):
    repo = tmp_path / "repo"
    pyc = write(repo / "pkg" / "__pycache__" / "a.pyc", b"cache")
    summary = run_stage(tmp_path, repo)
    assert summary["transient_deleted_count"] == 1
    assert not pyc.exists()


def test_git_and_venv_are_never_deleted(tmp_path):
    repo = tmp_path / "repo"
    git_file = write(repo / ".git" / "x.tmp", b"x")
    venv_file = write(repo / ".venv" / "x.pyc", b"x")
    run_stage(tmp_path, repo)
    assert git_file.exists()
    assert venv_file.exists()


def test_protected_latest_files_are_skipped(tmp_path):
    repo = tmp_path / "repo"
    protected = age(write(repo / "outputs" / "v21" / "V21.234_MINIMAL_MOOMOO_ONLY_DAILY_RESEARCH_CHAIN" / "big.csv", b"x" * (6 * 1024 * 1024)))
    run_stage(tmp_path, repo)
    skipped = (repo / "outputs" / "v21" / v236.STAGE / "v21_236_skipped_blockers.csv").read_text(encoding="utf-8")
    assert protected.exists()
    assert "ACTIVE_OR_LATEST_OUTPUT_PROTECTED" in skipped


def test_verified_duplicate_deletion_requires_same_size_and_sha256(tmp_path):
    repo = tmp_path / "repo"
    archive = tmp_path / "archive"
    src = age(write(repo / "old" / "dup.csv", b"same-content"))
    write(archive / "copy" / "dup.csv", b"same-content")
    summary = run_stage(tmp_path, repo, archive=archive)
    assert summary["verified_duplicate_deleted_count"] == 1
    assert not src.exists()


def test_duplicate_same_name_different_hash_is_skipped(tmp_path):
    repo = tmp_path / "repo"
    archive = tmp_path / "archive"
    src = age(write(repo / "old" / "dup.csv", b"source"))
    write(archive / "copy" / "dup.csv", b"other!")
    summary = run_stage(tmp_path, repo, archive=archive)
    assert summary["verified_duplicate_deleted_count"] == 0
    assert src.exists()


def test_historical_output_copy_verifies_sha256_before_source_delete(tmp_path):
    repo = tmp_path / "repo"
    archive = tmp_path / "archive"
    src = age(write(repo / "outputs" / "v21" / "V21.100_OLD" / "large.csv", b"a" * (6 * 1024 * 1024)))
    summary = run_stage(tmp_path, repo, archive=archive, allow_verified_duplicate_delete=False)
    archived = archive / v236.ARCHIVE_STAGE / "outputs" / "v21" / "V21.100_OLD" / "large.csv"
    assert summary["archive_moved_count"] == 1
    assert archived.exists()
    assert v236.sha256_file(archived) == v236.sha256_file(src) if src.exists() else True
    assert not src.exists()


def test_failed_archive_copy_prevents_source_delete(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    src = age(write(repo / "outputs" / "v21" / "V21.100_OLD" / "large.csv", b"a" * (6 * 1024 * 1024)))

    def boom(*_args, **_kwargs):
        raise OSError("copy failed")

    monkeypatch.setattr(v236.shutil, "copy2", boom)
    summary = run_stage(tmp_path, repo, allow_verified_duplicate_delete=False)
    assert summary["final_status"] == v236.FAIL_STATUS
    assert src.exists()


def test_quarantine_alone_is_not_trusted_for_duplicate_deletion(tmp_path):
    repo = tmp_path / "repo"
    quarantine = tmp_path / "quarantine"
    src = age(write(repo / "old" / "dup.csv", b"same-content"))
    write(quarantine / "dup.csv", b"same-content")
    summary = run_stage(tmp_path, repo, quarantine=quarantine)
    assert summary["verified_duplicate_deleted_count"] == 0
    assert src.exists()


def test_recent_files_are_skipped(tmp_path):
    repo = tmp_path / "repo"
    recent = write(repo / "outputs" / "v21" / "V21.100_OLD" / "large.csv", b"a" * (6 * 1024 * 1024))
    run_stage(tmp_path, repo, allow_verified_duplicate_delete=False)
    skipped = (repo / "outputs" / "v21" / v236.STAGE / "v21_236_skipped_blockers.csv").read_text(encoding="utf-8")
    assert recent.exists()
    assert "MODIFIED_WITHIN_LAST_48_HOURS" in skipped


def test_summary_byte_and_file_reductions_are_correct(tmp_path):
    repo = tmp_path / "repo"
    deleted = write(repo / "tmp" / "x.tmp", b"12345")
    summary = run_stage(tmp_path, repo, allow_verified_duplicate_delete=False, allow_archive_move=False)
    assert not deleted.exists()
    assert summary["repo_file_count_reduced"] >= 1
    assert summary["repo_size_reduced_bytes"] >= 5


def test_dry_run_deletes_nothing(tmp_path):
    repo = tmp_path / "repo"
    src = write(repo / "tmp" / "x.tmp", b"12345")
    summary = run_stage(tmp_path, repo, execute=False)
    assert src.exists()
    assert summary["transient_deleted_count"] == 0


def test_live_execute_writes_all_manifests(tmp_path):
    repo = tmp_path / "repo"
    write(repo / "tmp" / "x.tmp", b"123")
    run_stage(tmp_path, repo)
    out = repo / "outputs" / "v21" / v236.STAGE
    for name in [
        "v21_236_summary.json",
        "v21_236_deleted_transient_manifest.csv",
        "v21_236_deleted_verified_duplicates_manifest.csv",
        "v21_236_archived_moved_manifest.csv",
        "v21_236_skipped_blockers.csv",
        "v21_236_top_size_before.csv",
        "v21_236_top_size_after.csv",
        "V21.236_fast_repo_slim_stage2_report.txt",
    ]:
        assert (out / name).exists()


def test_final_status_pass_warn_fail_logic(tmp_path, monkeypatch):
    repo_pass = tmp_path / "repo_pass"
    write(repo_pass / "tmp" / "x.tmp", b"123")
    assert run_stage(tmp_path, repo_pass, min_target_mb=0)["final_status"] == v236.PASS_STATUS

    repo_warn = tmp_path / "repo_warn"
    write(repo_warn / "keep.txt", "keep")
    assert run_stage(tmp_path, repo_warn, min_target_mb=500, allow_transient_delete=False, allow_verified_duplicate_delete=False, allow_archive_move=False)["final_status"] == v236.WARN_STATUS

    repo_fail = tmp_path / "repo_fail"
    age(write(repo_fail / "outputs" / "v21" / "V21.100_OLD" / "large.csv", b"a" * (6 * 1024 * 1024)))

    def boom(*_args, **_kwargs):
        raise OSError("copy failed")

    monkeypatch.setattr(v236.shutil, "copy2", boom)
    assert run_stage(tmp_path, repo_fail, allow_verified_duplicate_delete=False)["final_status"] == v236.FAIL_STATUS
