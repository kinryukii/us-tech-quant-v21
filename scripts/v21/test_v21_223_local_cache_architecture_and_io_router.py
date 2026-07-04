from __future__ import annotations

import csv
import importlib.util
import os
from pathlib import Path


HELPER_PATH = Path(__file__).with_name("v21_cache_io.py")
helper_spec = importlib.util.spec_from_file_location("v21_cache_io", HELPER_PATH)
cache_io = importlib.util.module_from_spec(helper_spec)
assert helper_spec.loader is not None
helper_spec.loader.exec_module(cache_io)

MODULE_PATH = Path(__file__).with_name("v21_223_local_cache_architecture_and_io_router.py")
spec = importlib.util.spec_from_file_location("v21_223", MODULE_PATH)
v223 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v223)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")


def make_repo(tmp_path: Path, *, protected: bool = True) -> Path:
    root = tmp_path / "repo"
    touch(root / ".venv/Scripts/python.exe")
    touch(root / "scripts/v21/current.py")
    if protected:
        touch(root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
        for name in [
            "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
            "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
            "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
        ]:
            touch(root / "outputs/v21" / name / "summary.json")
    return root


def test_default_cache_root_when_env_absent(monkeypatch):
    monkeypatch.delenv("V21_CACHE_ROOT", raising=False)
    assert str(cache_io.get_cache_root()).lower().endswith("us-tech-quant-cache")


def test_env_var_overrides_cache_root(monkeypatch, tmp_path):
    monkeypatch.setenv("V21_CACHE_ROOT", str(tmp_path / "cache"))
    assert cache_io.get_cache_root() == (tmp_path / "cache").resolve()


def test_cache_layout_registry_and_retention_initialized(monkeypatch, tmp_path):
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("V21_CACHE_ROOT", str(cache_root))
    info = cache_io.ensure_cache_layout()
    assert info["cache_layout_dir_count"] == len(cache_io.CACHE_LAYOUT_DIRS)
    assert (cache_root / "data/raw/moomoo").exists()
    assert (cache_root / "index/cache_registry.csv").exists()
    assert (cache_root / "index/cache_retention_policy.csv").exists()


def test_large_artifact_routes_to_cache_and_compact_to_repo(monkeypatch):
    monkeypatch.delenv("V21_KEEP_FULL_ARTIFACTS", raising=False)
    assert cache_io.should_write_to_cache("full_panel.csv", size_bytes=6 * 1024 * 1024)
    assert not cache_io.should_write_to_cache("summary.json", size_bytes=1024, artifact_role="RUN_RESULT_COMPACT")


def test_pointer_manifest_resolves(monkeypatch, tmp_path):
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("V21_CACHE_ROOT", str(cache_root))
    cache_io.ensure_cache_layout()
    artifact = cache_root / "tmp/test.txt"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("x", encoding="utf-8")
    run_id = cache_io.new_run_id("TEST")
    cache_io.register_cache_artifact(artifact, "TEMP_CACHE", "DELETE_ON_NEXT_CLEANUP", run_id, "TEST", {})
    pointer = cache_io.write_pointer_manifest(tmp_path / "repo_out", artifact, "TEMP_CACHE", run_id, {})
    rows = read_csv(pointer)
    assert Path(rows[-1]["cache_artifact_path"]).exists()


def test_safe_relative_path_blocks_traversal():
    try:
        cache_io.safe_relative_path("../bad")
    except ValueError:
        pass
    else:
        raise AssertionError("path traversal was not blocked")


def test_protected_path_missing_produces_fail(monkeypatch, tmp_path):
    monkeypatch.setenv("V21_CACHE_ROOT", str(tmp_path / "cache"))
    root = make_repo(tmp_path, protected=False)
    summary = v223.run(root, out_dir=root / "out")
    assert summary["final_status"] == "FAIL_V21_223_PROTECTED_PATH_MISSING"


def test_no_delete_broker_price_or_canonical_mutation(monkeypatch, tmp_path):
    monkeypatch.setenv("V21_CACHE_ROOT", str(tmp_path / "cache"))
    root = make_repo(tmp_path)
    summary = v223.run(root, out_dir=root / "out")
    assert summary["deletion_performed"] is False
    assert summary["moomoo_broker_connection_performed"] is False
    assert summary["price_refresh_performed"] is False
    assert summary["canonical_mutation_performed"] is False


def test_summary_report_artifacts_written(monkeypatch, tmp_path):
    monkeypatch.setenv("V21_CACHE_ROOT", str(tmp_path / "cache"))
    root = make_repo(tmp_path)
    out = root / "out"
    summary = v223.run(root, out_dir=out)
    assert summary["final_status"] == "PASS_V21_223_LOCAL_CACHE_IO_ROUTER_READY"
    for name in [
        "v21_223_summary.json",
        "V21.223_local_cache_architecture_and_io_router_report.txt",
        "local_cache_layout_manifest.csv",
        "cache_registry_schema.csv",
        "cache_retention_policy.csv",
        "cache_io_helper_selftest.csv",
        "repo_output_pointer_policy.csv",
        "protected_path_presence_check.csv",
        "migration_readiness_plan.csv",
    ]:
        assert (out / name).exists()


def test_unhandled_exception_produces_fail(monkeypatch, tmp_path):
    monkeypatch.setenv("V21_CACHE_ROOT", str(tmp_path / "cache"))
    root = make_repo(tmp_path)
    summary = v223.run(root, out_dir=root / "out", simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_223_CACHE_IO_ROUTER_EXCEPTION"
