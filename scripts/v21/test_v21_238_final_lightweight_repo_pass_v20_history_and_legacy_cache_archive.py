from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_238_final_lightweight_repo_pass_v20_history_and_legacy_cache_archive.py")
SPEC = importlib.util.spec_from_file_location("v21_238_stage", MODULE_PATH)
v238 = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(v238)


def write(path: Path, data: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    return path


def run_stage(tmp_path: Path, repo: Path, **kwargs):
    return v238.run(
        repo_root=repo,
        archive_root=kwargs.pop("archive", tmp_path / "archive"),
        cache_root=kwargs.pop("cache", tmp_path / "cache"),
        quarantine_root=kwargs.pop("quarantine", tmp_path / "quarantine"),
        output_dir=kwargs.pop("out", repo / "outputs" / "v21" / v238.STAGE),
        execute=kwargs.pop("execute", True),
        min_target_mb=kwargs.pop("min_target_mb", 0),
        top_size_count=kwargs.pop("top_size_count", 20),
        allow_v21_229_extra_inventory_archive=kwargs.pop("allow_v21_229_extra_inventory_archive", True),
        allow_v20_history_archive=kwargs.pop("allow_v20_history_archive", True),
        allow_legacy_state_cache_archive=kwargs.pop("allow_legacy_state_cache_archive", True),
        legacy_cache_min_mb=kwargs.pop("legacy_cache_min_mb", 0.000001),
        v20_history_min_mb=kwargs.pop("v20_history_min_mb", 0.000001),
    )


def inventory_file(repo: Path, name: str = "yahoo_string_inventory.csv", data: bytes = b"yahoo,audit\n" * 5) -> Path:
    return write(repo / "outputs" / "v21" / "V21.229_MOOMOO_ONLY_DATA_SOURCE_POLICY_GATE" / name, data)


def v20_file(repo: Path, name: str = "V20_199B_R1_FORWARD_RETURNS.csv", data: bytes = b"r\n" * 5) -> Path:
    return write(repo / "outputs" / "v20" / "backtest" / name, data)


def legacy_file(repo: Path, name: str = "VMC.csv", data: bytes = b"price\n" * 5) -> Path:
    return write(repo / "state" / "v18" / "price_cache" / name, data)


def test_v21_229_inventory_archive_verifies_decompressed_sha256_before_delete(tmp_path):
    repo = tmp_path / "repo"
    src = inventory_file(repo)
    source_hash = v238.sha256_file(src)
    summary = run_stage(tmp_path, repo, allow_v20_history_archive=False, allow_legacy_state_cache_archive=False)
    assert summary["v21_229_extra_inventory_archived_count"] == 1
    assert not src.exists()
    payload = json.loads((repo / "outputs" / "v21" / v238.STAGE / "v21_238_pointer_manifest.json").read_text(encoding="utf-8"))
    assert payload["pointers"][0]["original_sha256"] == source_hash


def test_failed_gzip_verification_prevents_source_delete(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    src = inventory_file(repo)
    monkeypatch.setattr(v238, "gzip_decompressed_sha256", lambda _p: "bad")
    summary = run_stage(tmp_path, repo, allow_v20_history_archive=False, allow_legacy_state_cache_archive=False)
    assert summary["final_status"] == v238.FAIL_STATUS
    assert src.exists()


def test_dry_run_deletes_nothing(tmp_path):
    repo = tmp_path / "repo"
    src = inventory_file(repo)
    summary = run_stage(tmp_path, repo, execute=False, allow_v20_history_archive=False, allow_legacy_state_cache_archive=False)
    assert src.exists()
    assert summary["v21_229_extra_inventory_archived_count"] == 0


def test_v20_backtest_consolidation_csv_over_threshold_archived_and_removed(tmp_path):
    repo = tmp_path / "repo"
    src = v20_file(repo, data=b"x" * 100)
    summary = run_stage(tmp_path, repo, allow_v21_229_extra_inventory_archive=False, allow_legacy_state_cache_archive=False)
    assert not src.exists()
    assert summary["v20_history_archived_count"] == 1


def test_outputs_v20_price_history_canonical_files_never_touched(tmp_path):
    repo = tmp_path / "repo"
    canonical = write(repo / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv", b"x" * 100)
    trade_plan = write(repo / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV_RAW_TRADE_PLAN.csv", b"x" * 100)
    run_stage(tmp_path, repo)
    assert canonical.exists()
    assert trade_plan.exists()


def test_state_v18_price_cache_legacy_csv_over_threshold_archived_and_removed(tmp_path):
    repo = tmp_path / "repo"
    src = legacy_file(repo, data=b"x" * 100)
    summary = run_stage(tmp_path, repo, allow_v21_229_extra_inventory_archive=False, allow_v20_history_archive=False)
    assert not src.exists()
    assert summary["legacy_state_cache_archived_count"] == 1


def test_active_referenced_file_is_skipped(tmp_path):
    repo = tmp_path / "repo"
    src = v20_file(repo, data=b"x" * 100)
    write(repo / "outputs" / "v21" / "V21.237_RECENT_BLOCKER_REVIEW_AND_COMPRESSED_ARCHIVE_MOVE" / "manifest.json", json.dumps({"active": v238.rel(src, repo)}))
    summary = run_stage(tmp_path, repo, allow_v21_229_extra_inventory_archive=False, allow_legacy_state_cache_archive=False)
    assert src.exists()
    assert summary["skipped_count"] == 1


def test_archive_cache_quarantine_files_are_never_deleted(tmp_path):
    repo = tmp_path / "repo"
    archive = tmp_path / "archive"
    cache = tmp_path / "cache"
    quarantine = tmp_path / "quarantine"
    archive_file = write(archive / "keep.csv", b"a")
    cache_file = write(cache / "keep.csv", b"c")
    quarantine_file = write(quarantine / "keep.csv", b"q")
    inventory_file(repo)
    run_stage(tmp_path, repo, archive=archive, cache=cache, quarantine=quarantine, allow_v20_history_archive=False, allow_legacy_state_cache_archive=False)
    assert archive_file.exists()
    assert cache_file.exists()
    assert quarantine_file.exists()


def test_pointer_manifest_contains_original_sha256_gzip_path_and_relative_source_path(tmp_path):
    repo = tmp_path / "repo"
    src = inventory_file(repo)
    source_hash = v238.sha256_file(src)
    run_stage(tmp_path, repo, allow_v20_history_archive=False, allow_legacy_state_cache_archive=False)
    payload = json.loads((repo / "outputs" / "v21" / v238.STAGE / "v21_238_pointer_manifest.json").read_text(encoding="utf-8"))
    pointer = payload["pointers"][0]
    assert pointer["relative_path"].endswith("yahoo_string_inventory.csv")
    assert pointer["archive_gzip_path"].endswith(".gz")
    assert pointer["original_sha256"] == source_hash


def test_summary_byte_reductions_and_gzip_bytes_are_correct(tmp_path):
    repo = tmp_path / "repo"
    inventory_file(repo, data=b"x" * 1024)
    summary = run_stage(tmp_path, repo, allow_v20_history_archive=False, allow_legacy_state_cache_archive=False)
    assert summary["repo_size_reduced_bytes"] >= 1024
    assert summary["v21_229_extra_inventory_gzip_bytes"] > 0
    assert summary["estimated_net_disk_reduction_bytes"] > 0


def test_protected_large_files_audit_includes_canonical_historical_ohlcv_files(tmp_path):
    repo = tmp_path / "repo"
    write(repo / "inputs" / "v21" / "historical_ohlcv_cache" / "V21_037_R1_HISTORICAL_OHLCV_CACHE.csv", b"x")
    write(repo / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv", b"x")
    run_stage(tmp_path, repo, allow_v21_229_extra_inventory_archive=False, allow_v20_history_archive=False, allow_legacy_state_cache_archive=False)
    audit = (repo / "outputs" / "v21" / v238.STAGE / "v21_238_protected_large_files_audit.csv").read_text(encoding="utf-8")
    assert "V21_037_R1_HISTORICAL_OHLCV_CACHE.csv" in audit
    assert "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv" in audit


def test_final_status_pass_warn_fail_logic(tmp_path, monkeypatch):
    repo_pass = tmp_path / "repo_pass"
    inventory_file(repo_pass, data=b"x" * 100)
    assert run_stage(tmp_path, repo_pass, min_target_mb=0, allow_v20_history_archive=False, allow_legacy_state_cache_archive=False)["final_status"] == v238.PASS_STATUS

    repo_warn = tmp_path / "repo_warn"
    write(repo_warn / "keep.txt", "keep")
    assert run_stage(tmp_path, repo_warn, min_target_mb=150, allow_v21_229_extra_inventory_archive=False, allow_v20_history_archive=False, allow_legacy_state_cache_archive=False)["final_status"] == v238.WARN_STATUS

    repo_fail = tmp_path / "repo_fail"
    inventory_file(repo_fail, data=b"x" * 100)
    monkeypatch.setattr(v238, "gzip_decompressed_sha256", lambda _p: "bad")
    assert run_stage(tmp_path, repo_fail, allow_v20_history_archive=False, allow_legacy_state_cache_archive=False)["final_status"] == v238.FAIL_STATUS


def test_git_venv_scripts_config_are_protected(tmp_path):
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
