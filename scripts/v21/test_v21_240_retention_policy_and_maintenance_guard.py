from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_240_retention_policy_and_maintenance_guard.py")
SPEC = importlib.util.spec_from_file_location("v21_240_stage", MODULE_PATH)
v240 = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(v240)


def write(path: Path, data: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    return path


def roots(tmp_path: Path):
    return tmp_path / "repo", tmp_path / "archive", tmp_path / "cache", tmp_path / "quarantine"


def budgets(**overrides):
    base = {
        "repo_warning_mb": 1, "repo_hard_mb": 2,
        "archive_warning_mb": 1, "archive_hard_mb": 2,
        "cache_warning_mb": 1, "cache_hard_mb": 2,
        "quarantine_warning_mb": 1, "quarantine_hard_mb": 2,
        "total_warning_mb": 4, "total_hard_mb": 8,
    }
    base.update(overrides)
    return base


def run_stage(tmp_path: Path, repo: Path, archive: Path, cache: Path, quarantine: Path, **kwargs):
    return v240.run(
        repo_root=repo,
        archive_root=archive,
        cache_root=cache,
        quarantine_root=quarantine,
        output_dir=kwargs.pop("out", repo / "outputs" / "v21" / v240.STAGE),
        execute=kwargs.pop("execute", True),
        audit_only=kwargs.pop("audit_only", False),
        top_size_count=kwargs.pop("top_size_count", 50),
        budgets=kwargs.pop("budgets", budgets()),
        allow_archive_compress=kwargs.pop("allow_archive_compress", True),
        allow_archive_duplicate_delete=kwargs.pop("allow_archive_duplicate_delete", True),
        allow_quarantine_verified_delete=kwargs.pop("allow_quarantine_verified_delete", True),
        allow_cache_retention_delete=kwargs.pop("allow_cache_retention_delete", True),
        archive_compress_min_mb=kwargs.pop("archive_compress_min_mb", 0.000001),
        repo_large_file_warning_mb=kwargs.pop("repo_large_file_warning_mb", 0.000001),
        repo_large_file_hard_mb=kwargs.pop("repo_large_file_hard_mb", 0.00001),
        cache_retention_days=kwargs.pop("cache_retention_days", 0),
        quarantine_retention_days=kwargs.pop("quarantine_retention_days", 0),
        recent_file_protection_hours=kwargs.pop("recent_file_protection_hours", 0),
    )


def test_retention_policy_created_and_existing_policy_backed_up(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    existing = write(cache / "retention_policy" / "v21_240_retention_policy.json", "{}")
    run_stage(tmp_path, repo, archive, cache, quarantine)
    assert existing.exists()
    assert list(existing.parent.glob("v21_240_retention_policy.backup_*.json"))
    snapshot = repo / "outputs" / "v21" / v240.STAGE / "v21_240_retention_policy_snapshot.json"
    assert json.loads(snapshot.read_text(encoding="utf-8"))["policy_version"] == "V21.240"


def test_four_root_footprint_budget_status_ok_warn_fail(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    write(repo / "small.txt", b"x")
    ok = run_stage(tmp_path, repo, archive, cache, quarantine, budgets=budgets(repo_warning_mb=10, repo_hard_mb=20))
    assert ok["repo_budget_status"] == "OK"
    warn = run_stage(tmp_path, repo, archive, cache, quarantine, budgets=budgets(repo_warning_mb=0.0000001, repo_hard_mb=20))
    assert warn["repo_budget_status"] == "WARN_SIZE_BUDGET"
    fail = run_stage(tmp_path, repo, archive, cache, quarantine, budgets=budgets(repo_warning_mb=0.0000001, repo_hard_mb=0.0000001))
    assert fail["repo_budget_status"] == "FAIL_SIZE_BUDGET"


def test_repo_large_file_audit_flags_ungoverned_without_deleting(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    large = write(repo / "outputs" / "v20" / "other" / "large.csv", b"x" * 100)
    summary = run_stage(tmp_path, repo, archive, cache, quarantine)
    assert large.exists()
    assert summary["guard_violation_count"] == 1


def test_protected_ohlcv_files_classified_active_lineage(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    p = write(repo / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv", b"x" * 100)
    run_stage(tmp_path, repo, archive, cache, quarantine)
    audit = (repo / "outputs" / "v21" / v240.STAGE / "v21_240_repo_large_file_governance_audit.csv").read_text(encoding="utf-8")
    assert p.exists()
    assert "ACTIVE_CANONICAL_LINEAGE" in audit


def test_archive_compression_verifies_before_delete(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    src = write(archive / "old.csv", b"x" * 100)
    digest = v240.sha256_file(src)
    summary = run_stage(tmp_path, repo, archive, cache, quarantine, allow_archive_duplicate_delete=False, allow_quarantine_verified_delete=False, allow_cache_retention_delete=False)
    gz = Path(str(src) + ".gz")
    assert summary["archive_compressed_count"] == 1
    assert not src.exists()
    assert v240.gzip_decompressed_sha256(gz) == digest


def test_failed_gzip_verification_prevents_original_delete(tmp_path, monkeypatch):
    repo, archive, cache, quarantine = roots(tmp_path)
    src = write(archive / "old.csv", b"x" * 100)
    monkeypatch.setattr(v240, "gzip_decompressed_sha256", lambda _p: "bad")
    summary = run_stage(tmp_path, repo, archive, cache, quarantine, allow_archive_duplicate_delete=False, allow_quarantine_verified_delete=False, allow_cache_retention_delete=False)
    assert summary["final_status"] == v240.FAIL_ERROR
    assert src.exists()


def test_existing_gz_not_double_compressed(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    archive.mkdir(parents=True)
    with gzip.open(archive / "old.csv.gz", "wb") as handle:
        handle.write(b"x" * 100)
    run_stage(tmp_path, repo, archive, cache, quarantine, allow_archive_duplicate_delete=False, allow_quarantine_verified_delete=False, allow_cache_retention_delete=False)
    assert not (archive / "old.csv.gz.gz").exists()


def test_archive_duplicate_deletion_retains_one_copy(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    a = write(archive / "a.bin", b"same")
    b = write(archive / "b.bin", b"same")
    summary = run_stage(tmp_path, repo, archive, cache, quarantine, allow_archive_compress=False, allow_quarantine_verified_delete=False, allow_cache_retention_delete=False)
    assert summary["archive_duplicate_deleted_count"] == 1
    assert a.exists() or b.exists()


def test_archive_duplicate_deletion_respects_pointer_preference(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    keep = write(archive / "keep.bin", b"same")
    delete = write(archive / "delete.bin", b"same")
    write(repo / "outputs" / "v21" / "V21.239_TOTAL_DISK_FOOTPRINT_GOVERNANCE" / "pointer.json", json.dumps({"path": str(keep)}))
    run_stage(tmp_path, repo, archive, cache, quarantine, allow_archive_compress=False, allow_quarantine_verified_delete=False, allow_cache_retention_delete=False)
    assert keep.exists()
    assert not delete.exists()


def test_quarantine_deleted_only_with_trusted_duplicate(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    write(repo / "trusted.bin", b"same")
    q = write(quarantine / "q.bin", b"same")
    summary = run_stage(tmp_path, repo, archive, cache, quarantine, allow_archive_compress=False, allow_archive_duplicate_delete=False, allow_cache_retention_delete=False)
    assert summary["quarantine_verified_deleted_count"] == 1
    assert not q.exists()


def test_quarantine_unique_file_skipped(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    q = write(quarantine / "q.bin", b"unique")
    summary = run_stage(tmp_path, repo, archive, cache, quarantine, allow_archive_compress=False, allow_archive_duplicate_delete=False, allow_cache_retention_delete=False)
    assert q.exists()
    assert summary["unique_copy_skipped_count"] == 1


def test_cache_tmp_selftest_deleted_under_allow_flag(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    a = write(cache / "tmp" / "x.tmp", b"x")
    b = write(cache / "selftest" / "y.dat", b"y")
    summary = run_stage(tmp_path, repo, archive, cache, quarantine, allow_archive_compress=False, allow_archive_duplicate_delete=False, allow_quarantine_verified_delete=False)
    assert summary["cache_retention_deleted_count"] == 2
    assert not a.exists() and not b.exists()


def test_cache_registry_retention_pointer_canonical_never_deleted(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    files = [
        write(cache / "registry" / "registry.csv", b"x"),
        write(cache / "retention_policy" / "policy.json", b"x"),
        write(cache / "tmp" / "pointer_manifest.json", b"x"),
        write(cache / "canonical" / "moomoo_ohlcv" / "canonical_moomoo_ohlcv_daily_qfq.csv", b"x"),
    ]
    run_stage(tmp_path, repo, archive, cache, quarantine)
    assert all(p.exists() for p in files)


def test_dry_run_deletes_nothing(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    src = write(archive / "old.csv", b"x" * 100)
    summary = run_stage(tmp_path, repo, archive, cache, quarantine, execute=False, allow_archive_duplicate_delete=False, allow_quarantine_verified_delete=False, allow_cache_retention_delete=False)
    assert src.exists()
    assert summary["archive_compressed_count"] == 0


def test_execute_writes_all_manifests(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    write(archive / "old.csv", b"x" * 100)
    run_stage(tmp_path, repo, archive, cache, quarantine)
    out = repo / "outputs" / "v21" / v240.STAGE
    for name in [
        "v21_240_summary.json", "v21_240_retention_policy_snapshot.json",
        "v21_240_four_root_footprint_before.csv", "v21_240_four_root_footprint_after.csv",
        "v21_240_combined_top_size_before.csv", "v21_240_combined_top_size_after.csv",
        "v21_240_repo_large_file_governance_audit.csv", "v21_240_guard_violations.csv",
        "v21_240_archive_compressed_manifest.csv", "v21_240_archive_duplicate_deleted_manifest.csv",
        "v21_240_quarantine_verified_deleted_manifest.csv", "v21_240_cache_retention_deleted_manifest.csv",
        "v21_240_skipped_blockers.csv", "v21_240_remaining_blockers_by_bytes.csv",
        "v21_240_pointer_manifest.json", "V21.240_retention_policy_and_maintenance_guard_report.txt",
    ]:
        assert (out / name).exists()


def test_repo_source_config_git_venv_scripts_protected(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    files = [
        write(repo / ".git" / "x", b"x"),
        write(repo / ".venv" / "x", b"x"),
        write(repo / "scripts" / "x.py", b"x"),
        write(repo / "config" / "x.json", b"x"),
    ]
    run_stage(tmp_path, repo, archive, cache, quarantine)
    assert all(p.exists() for p in files)


def test_summary_reduction_and_budget_statuses(tmp_path):
    repo, archive, cache, quarantine = roots(tmp_path)
    write(archive / "old.csv", b"x" * 100)
    summary = run_stage(tmp_path, repo, archive, cache, quarantine, budgets=budgets(archive_warning_mb=10, archive_hard_mb=20))
    assert summary["total_size_reduced_bytes"] == summary["total_size_before_bytes"] - summary["total_size_after_bytes"]
    assert summary["archive_budget_status"] == "OK"


def test_final_status_pass_warn_fail_logic(tmp_path, monkeypatch):
    repo_ok, archive_ok, cache_ok, quarantine_ok = roots(tmp_path / "ok")
    assert run_stage(tmp_path, repo_ok, archive_ok, cache_ok, quarantine_ok)["final_status"] == v240.PASS_OK
    repo_warn, archive_warn, cache_warn, quarantine_warn = roots(tmp_path / "warn")
    write(repo_warn / "x.bin", b"x")
    assert run_stage(tmp_path, repo_warn, archive_warn, cache_warn, quarantine_warn, budgets=budgets(repo_warning_mb=0.0000001, repo_hard_mb=20))["final_status"] == v240.WARN_BUDGET
    repo_fail, archive_fail, cache_fail, quarantine_fail = roots(tmp_path / "fail")
    write(repo_fail / "x.bin", b"x" * 100)
    assert run_stage(tmp_path, repo_fail, archive_fail, cache_fail, quarantine_fail, budgets=budgets(repo_warning_mb=0.0000001, repo_hard_mb=0.0000001))["final_status"] == v240.FAIL_BUDGET
    repo_err, archive_err, cache_err, quarantine_err = roots(tmp_path / "err")
    write(archive_err / "old.csv", b"x" * 100)
    monkeypatch.setattr(v240, "gzip_decompressed_sha256", lambda _p: "bad")
    assert run_stage(tmp_path, repo_err, archive_err, cache_err, quarantine_err, allow_archive_duplicate_delete=False, allow_quarantine_verified_delete=False, allow_cache_retention_delete=False)["final_status"] == v240.FAIL_ERROR
