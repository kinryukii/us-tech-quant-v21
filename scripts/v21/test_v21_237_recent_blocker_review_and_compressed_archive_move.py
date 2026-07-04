from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_237_recent_blocker_review_and_compressed_archive_move.py")
SPEC = importlib.util.spec_from_file_location("v21_237_stage", MODULE_PATH)
v237 = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(v237)


def write(path: Path, data: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    return path


def run_stage(tmp_path: Path, repo: Path, **kwargs):
    return v237.run(
        repo_root=repo,
        archive_root=kwargs.pop("archive", tmp_path / "archive"),
        cache_root=kwargs.pop("cache", tmp_path / "cache"),
        quarantine_root=kwargs.pop("quarantine", tmp_path / "quarantine"),
        output_dir=kwargs.pop("out", repo / "outputs" / "v21" / v237.STAGE),
        execute=kwargs.pop("execute", True),
        min_target_mb=kwargs.pop("min_target_mb", 0),
        top_size_count=kwargs.pop("top_size_count", 20),
        allow_recent_audit_csv_archive=kwargs.pop("allow_recent_audit_csv_archive", True),
        allow_canonical_backup_prune=kwargs.pop("allow_canonical_backup_prune", True),
        canonical_backup_retain_count=kwargs.pop("canonical_backup_retain_count", 2),
    )


def audit_file(repo: Path, name: str = "blocker_triage_master.csv", data: bytes = b"audit,data\n" * 5) -> Path:
    return write(repo / "outputs" / "v21" / "V21.229_R1_ACTIVE_DATA_SOURCE_BLOCKER_TRIAGE_AND_ENFORCEMENT" / name, data)


def backup_file(repo: Path, name: str, data: bytes = b"date,close\n" * 5) -> Path:
    return write(repo / v237.BACKUP_DIR / name, data)


def test_gzip_archive_move_verifies_decompressed_sha256_before_source_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(v237, "MIN_AUDIT_BYTES", 1)
    repo = tmp_path / "repo"
    src = audit_file(repo)
    source_hash = v237.sha256_file(src)
    summary = run_stage(tmp_path, repo, allow_canonical_backup_prune=False)
    manifest = list((repo / "outputs" / "v21" / v237.STAGE / "v21_237_recent_audit_csv_archived_manifest.csv").read_text(encoding="utf-8").splitlines())
    assert summary["recent_audit_csv_archived_count"] == 1
    assert not src.exists()
    assert source_hash in "\n".join(manifest)
    assert "True" in "\n".join(manifest)


def test_failed_gzip_verification_prevents_source_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(v237, "MIN_AUDIT_BYTES", 1)
    repo = tmp_path / "repo"
    src = audit_file(repo)
    monkeypatch.setattr(v237, "gzip_decompressed_sha256", lambda _p: "bad")
    summary = run_stage(tmp_path, repo, allow_canonical_backup_prune=False)
    assert summary["final_status"] == v237.FAIL_STATUS
    assert src.exists()


def test_dry_run_deletes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(v237, "MIN_AUDIT_BYTES", 1)
    repo = tmp_path / "repo"
    src = audit_file(repo)
    summary = run_stage(tmp_path, repo, execute=False, allow_canonical_backup_prune=False)
    assert src.exists()
    assert summary["recent_audit_csv_archived_count"] == 0


def test_v21_229_recent_audit_csv_larger_than_threshold_is_archived_and_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(v237, "MIN_AUDIT_BYTES", 10)
    repo = tmp_path / "repo"
    src = audit_file(repo, data=b"x" * 20)
    summary = run_stage(tmp_path, repo, allow_canonical_backup_prune=False)
    assert not src.exists()
    assert summary["recent_audit_csv_archived_original_bytes"] == 20


def test_files_outside_v21_229_target_directories_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(v237, "MIN_AUDIT_BYTES", 1)
    repo = tmp_path / "repo"
    outside = write(repo / "outputs" / "v21" / "V21.100_OLD" / "large.csv", b"x" * 100)
    summary = run_stage(tmp_path, repo, allow_canonical_backup_prune=False)
    assert outside.exists()
    assert summary["recent_audit_csv_archived_count"] == 0


def test_canonical_backups_retain_newest_n_files(tmp_path):
    repo = tmp_path / "repo"
    oldest = backup_file(repo, "a.csv", b"a")
    middle = backup_file(repo, "b.csv", b"b")
    newest = backup_file(repo, "c.csv", b"c")
    summary = run_stage(tmp_path, repo, allow_recent_audit_csv_archive=False, canonical_backup_retain_count=2)
    assert not oldest.exists()
    assert middle.exists()
    assert newest.exists()
    assert summary["canonical_backup_retained_count"] == 2


def test_older_canonical_backups_are_gzip_archived_and_removed(tmp_path):
    repo = tmp_path / "repo"
    old = backup_file(repo, "a.csv", b"old backup")
    backup_file(repo, "b.csv", b"new backup")
    summary = run_stage(tmp_path, repo, allow_recent_audit_csv_archive=False, canonical_backup_retain_count=1)
    assert not old.exists()
    assert summary["canonical_backup_archived_count"] == 1


def test_active_canonical_price_file_is_never_touched(tmp_path):
    repo = tmp_path / "repo"
    active = write(repo / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv", b"x" * 100)
    run_stage(tmp_path, repo)
    assert active.exists()


def test_archive_cache_quarantine_files_are_never_deleted(tmp_path, monkeypatch):
    monkeypatch.setattr(v237, "MIN_AUDIT_BYTES", 1)
    repo = tmp_path / "repo"
    archive = tmp_path / "archive"
    cache = tmp_path / "cache"
    quarantine = tmp_path / "quarantine"
    archive_file = write(archive / "keep.csv", b"a")
    cache_file = write(cache / "keep.csv", b"c")
    quarantine_file = write(quarantine / "keep.csv", b"q")
    audit_file(repo)
    run_stage(tmp_path, repo, archive=archive, cache=cache, quarantine=quarantine, allow_canonical_backup_prune=False)
    assert archive_file.exists()
    assert cache_file.exists()
    assert quarantine_file.exists()


def test_pointer_manifest_contains_original_sha256_and_gzip_path(tmp_path, monkeypatch):
    monkeypatch.setattr(v237, "MIN_AUDIT_BYTES", 1)
    repo = tmp_path / "repo"
    src = audit_file(repo)
    source_hash = v237.sha256_file(src)
    run_stage(tmp_path, repo, allow_canonical_backup_prune=False)
    payload = json.loads((repo / "outputs" / "v21" / v237.STAGE / "v21_237_pointer_manifest.json").read_text(encoding="utf-8"))
    assert payload["pointers"][0]["original_sha256"] == source_hash
    assert payload["pointers"][0]["archive_gzip_path"].endswith(".gz")


def test_summary_byte_reductions_and_gzip_bytes_are_correct(tmp_path, monkeypatch):
    monkeypatch.setattr(v237, "MIN_AUDIT_BYTES", 1)
    repo = tmp_path / "repo"
    audit_file(repo, data=b"x" * 1024)
    summary = run_stage(tmp_path, repo, allow_canonical_backup_prune=False)
    assert summary["repo_size_reduced_bytes"] >= 1024
    assert summary["recent_audit_csv_archive_gzip_bytes"] > 0
    assert summary["estimated_net_disk_reduction_bytes"] > 0


def test_final_status_pass_warn_fail_logic(tmp_path, monkeypatch):
    monkeypatch.setattr(v237, "MIN_AUDIT_BYTES", 1)
    repo_pass = tmp_path / "repo_pass"
    audit_file(repo_pass, data=b"x" * 100)
    assert run_stage(tmp_path, repo_pass, min_target_mb=0, allow_canonical_backup_prune=False)["final_status"] == v237.PASS_STATUS

    repo_warn = tmp_path / "repo_warn"
    write(repo_warn / "keep.txt", "keep")
    assert run_stage(tmp_path, repo_warn, min_target_mb=400, allow_recent_audit_csv_archive=False, allow_canonical_backup_prune=False)["final_status"] == v237.WARN_STATUS

    repo_fail = tmp_path / "repo_fail"
    audit_file(repo_fail, data=b"x" * 100)
    monkeypatch.setattr(v237, "gzip_decompressed_sha256", lambda _p: "bad")
    assert run_stage(tmp_path, repo_fail, allow_canonical_backup_prune=False)["final_status"] == v237.FAIL_STATUS


def test_git_venv_scripts_config_are_protected(tmp_path, monkeypatch):
    monkeypatch.setattr(v237, "MIN_AUDIT_BYTES", 1)
    repo = tmp_path / "repo"
    git_file = write(repo / ".git" / "x.csv", b"x")
    venv_file = write(repo / ".venv" / "x.csv", b"x")
    script_file = write(repo / "scripts" / "tool.csv", b"x")
    config_file = write(repo / "config" / "policy.csv", b"x")
    run_stage(tmp_path, repo)
    assert git_file.exists()
    assert venv_file.exists()
    assert script_file.exists()
    assert config_file.exists()
