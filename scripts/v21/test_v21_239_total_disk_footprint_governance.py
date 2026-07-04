from __future__ import annotations

import gzip
import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_239_total_disk_footprint_governance.py")
SPEC = importlib.util.spec_from_file_location("v21_239_stage", MODULE_PATH)
v239 = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(v239)


def write(path: Path, data: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    return path


def run_stage(tmp_path: Path, repo: Path, archive: Path, cache: Path, quarantine: Path, **kwargs):
    return v239.run(
        repo_root=repo,
        archive_root=archive,
        cache_root=cache,
        quarantine_root=quarantine,
        output_dir=kwargs.pop("out", repo / "outputs" / "v21" / v239.STAGE),
        execute=kwargs.pop("execute", True),
        min_target_mb=kwargs.pop("min_target_mb", 0),
        top_size_count=kwargs.pop("top_size_count", 50),
        allow_archive_compress=kwargs.pop("allow_archive_compress", True),
        allow_archive_duplicate_delete=kwargs.pop("allow_archive_duplicate_delete", True),
        allow_quarantine_verified_delete=kwargs.pop("allow_quarantine_verified_delete", True),
        allow_cache_retention_delete=kwargs.pop("allow_cache_retention_delete", True),
        archive_compress_min_mb=kwargs.pop("archive_compress_min_mb", 0.000001),
        cache_retention_days=kwargs.pop("cache_retention_days", 0),
        quarantine_retention_days=kwargs.pop("quarantine_retention_days", 0),
    )


def roots(tmp_path: Path):
    return tmp_path / "repo", tmp_path / "archive", tmp_path / "cache", tmp_path / "quarantine"


def test_four_root_footprint_inventory_is_correct(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    write(repo / "a.txt", b"aa")
    write(archive / "b.txt", b"bbb")
    write(cache / "c.txt", b"cccc")
    write(quarantine / "d.txt", b"ddddd")
    summary = run_stage(tmp_path, repo, archive, cache, quarantine, allow_archive_compress=False, allow_archive_duplicate_delete=False, allow_quarantine_verified_delete=False, allow_cache_retention_delete=False)
    assert summary["repo_size_before_bytes"] == 2
    assert summary["archive_size_before_bytes"] == 3
    assert summary["cache_size_before_bytes"] == 4
    assert summary["quarantine_size_before_bytes"] == 5


def test_archive_uncompressed_file_gzip_compressed_and_original_deleted_after_verify(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    src = write(archive / "V21.236_FAST_REPO_SLIM_STAGE2" / "old" / "large.csv", b"x" * 100)
    source_hash = v239.sha256_file(src)
    summary = run_stage(tmp_path, repo, archive, cache, quarantine, allow_archive_duplicate_delete=False, allow_quarantine_verified_delete=False, allow_cache_retention_delete=False)
    gz = Path(str(src) + ".gz")
    assert summary["archive_compressed_count"] == 1
    assert not src.exists()
    assert gz.exists()
    assert v239.gzip_decompressed_sha256(gz) == source_hash


def test_failed_gzip_verification_prevents_original_deletion(tmp_path, monkeypatch):
    repo, archive, cache, quarantine = roots(tmp_path)
    src = write(archive / "V21.236_FAST_REPO_SLIM_STAGE2" / "old" / "large.csv", b"x" * 100)
    monkeypatch.setattr(v239, "gzip_decompressed_sha256", lambda _p: "bad")
    summary = run_stage(tmp_path, repo, archive, cache, quarantine, allow_archive_duplicate_delete=False, allow_quarantine_verified_delete=False, allow_cache_retention_delete=False)
    assert summary["final_status"] == v239.FAIL_STATUS
    assert src.exists()


def test_existing_gz_is_not_double_compressed(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    archive.mkdir(parents=True, exist_ok=True)
    with gzip.open(archive / "large.csv.gz", "wb") as handle:
        handle.write(b"x" * 100)
    summary = run_stage(tmp_path, repo, archive, cache, quarantine, allow_archive_duplicate_delete=False, allow_quarantine_verified_delete=False, allow_cache_retention_delete=False)
    assert summary["archive_compressed_count"] == 0
    assert not (archive / "large.csv.gz.gz").exists()


def test_archive_duplicate_deletion_retains_at_least_one_trusted_copy(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    a = write(archive / "a.bin", b"same")
    b = write(archive / "b.bin", b"same")
    summary = run_stage(tmp_path, repo, archive, cache, quarantine, allow_archive_compress=False, allow_quarantine_verified_delete=False, allow_cache_retention_delete=False)
    assert summary["archive_duplicate_deleted_count"] == 1
    assert a.exists() or b.exists()


def test_archive_duplicate_deletion_prefers_compressed_copy(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    gz = write(archive / "keep.gz", b"same-bytes")
    plain = write(archive / "delete.csv", b"same-bytes")
    run_stage(tmp_path, repo, archive, cache, quarantine, allow_archive_compress=False, allow_quarantine_verified_delete=False, allow_cache_retention_delete=False)
    assert gz.exists()
    assert not plain.exists()


def test_quarantine_file_deleted_only_when_trusted_duplicate_exists(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    write(repo / "trusted.bin", b"same")
    q = write(quarantine / "q.bin", b"same")
    summary = run_stage(tmp_path, repo, archive, cache, quarantine, allow_archive_compress=False, allow_archive_duplicate_delete=False, allow_cache_retention_delete=False)
    assert summary["quarantine_verified_deleted_count"] == 1
    assert not q.exists()


def test_quarantine_file_with_no_trusted_duplicate_is_skipped(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    q = write(quarantine / "q.bin", b"unique")
    summary = run_stage(tmp_path, repo, archive, cache, quarantine, allow_archive_compress=False, allow_archive_duplicate_delete=False, allow_cache_retention_delete=False)
    assert q.exists()
    assert summary["unique_copy_skipped_count"] == 1


def test_cache_tmp_selftest_files_deleted_under_allow_flag(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    tmp_file = write(cache / "tmp" / "x.tmp", b"x")
    selftest_file = write(cache / "selftest" / "y.dat", b"y")
    summary = run_stage(tmp_path, repo, archive, cache, quarantine, allow_archive_compress=False, allow_archive_duplicate_delete=False, allow_quarantine_verified_delete=False)
    assert summary["cache_retention_deleted_count"] == 2
    assert not tmp_file.exists()
    assert not selftest_file.exists()


def test_cache_registry_pointer_retention_policy_files_never_deleted(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    registry = write(cache / "registry" / "cache_registry.csv", b"x")
    pointer = write(cache / "tmp" / "pointer_manifest.json", b"x")
    retention = write(cache / "tmp" / "retention_policy.json", b"x")
    run_stage(tmp_path, repo, archive, cache, quarantine, allow_archive_compress=False, allow_archive_duplicate_delete=False, allow_quarantine_verified_delete=False)
    assert registry.exists()
    assert pointer.exists()
    assert retention.exists()


def test_dry_run_deletes_nothing(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    src = write(archive / "old.csv", b"x" * 100)
    summary = run_stage(tmp_path, repo, archive, cache, quarantine, execute=False, allow_archive_duplicate_delete=False, allow_quarantine_verified_delete=False, allow_cache_retention_delete=False)
    assert src.exists()
    assert summary["archive_compressed_count"] == 0


def test_repo_source_config_git_venv_active_canonical_files_are_protected(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    files = [
        write(repo / ".git" / "x", b"x"),
        write(repo / ".venv" / "x", b"x"),
        write(repo / "scripts" / "tool.py", b"x"),
        write(repo / "config" / "policy.json", b"x"),
        write(repo / "outputs" / "v20" / "price_history" / "canonical.csv", b"x"),
    ]
    run_stage(tmp_path, repo, archive, cache, quarantine)
    assert all(p.exists() for p in files)


def test_summary_total_size_reduction_is_correct(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    write(archive / "V21.236_FAST_REPO_SLIM_STAGE2" / "old.csv", b"x" * 100)
    summary = run_stage(tmp_path, repo, archive, cache, quarantine, allow_archive_duplicate_delete=False, allow_quarantine_verified_delete=False, allow_cache_retention_delete=False)
    assert summary["total_size_reduced_bytes"] == summary["total_size_before_bytes"] - summary["total_size_after_bytes"]
    assert summary["archive_compression_net_reduction_bytes"] > 0


def test_final_status_pass_warn_fail_logic(tmp_path, monkeypatch):
    repo_pass, archive_pass, cache_pass, quarantine_pass = roots(tmp_path / "pass")
    write(archive_pass / "V21.236_FAST_REPO_SLIM_STAGE2" / "old.csv", b"x" * 100)
    assert run_stage(tmp_path, repo_pass, archive_pass, cache_pass, quarantine_pass, min_target_mb=0, allow_archive_duplicate_delete=False, allow_quarantine_verified_delete=False, allow_cache_retention_delete=False)["final_status"] == v239.PASS_STATUS

    repo_warn, archive_warn, cache_warn, quarantine_warn = roots(tmp_path / "warn")
    write(repo_warn / "keep.txt", b"x")
    assert run_stage(tmp_path, repo_warn, archive_warn, cache_warn, quarantine_warn, min_target_mb=300, allow_archive_compress=False, allow_archive_duplicate_delete=False, allow_quarantine_verified_delete=False, allow_cache_retention_delete=False)["final_status"] == v239.WARN_STATUS

    repo_fail, archive_fail, cache_fail, quarantine_fail = roots(tmp_path / "fail")
    write(archive_fail / "V21.236_FAST_REPO_SLIM_STAGE2" / "old.csv", b"x" * 100)
    monkeypatch.setattr(v239, "gzip_decompressed_sha256", lambda _p: "bad")
    assert run_stage(tmp_path, repo_fail, archive_fail, cache_fail, quarantine_fail, allow_archive_duplicate_delete=False, allow_quarantine_verified_delete=False, allow_cache_retention_delete=False)["final_status"] == v239.FAIL_STATUS


def test_manifests_are_written_for_all_phases(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    write(archive / "old.csv", b"x" * 100)
    run_stage(tmp_path, repo, archive, cache, quarantine)
    out = repo / "outputs" / "v21" / v239.STAGE
    for name in [
        "v21_239_summary.json",
        "v21_239_four_root_footprint_before.csv",
        "v21_239_four_root_footprint_after.csv",
        "v21_239_combined_top_size_before.csv",
        "v21_239_combined_top_size_after.csv",
        "v21_239_archive_compressed_manifest.csv",
        "v21_239_archive_duplicate_deleted_manifest.csv",
        "v21_239_quarantine_verified_deleted_manifest.csv",
        "v21_239_cache_retention_deleted_manifest.csv",
        "v21_239_skipped_blockers.csv",
        "v21_239_remaining_blockers_by_bytes.csv",
        "v21_239_pointer_manifest.json",
        "V21.239_total_disk_footprint_governance_report.txt",
    ]:
        assert (out / name).exists()
