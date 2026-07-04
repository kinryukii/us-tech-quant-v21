from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_202_repo_safe_cleanup_audit_and_cache_purge.py"
WRAPPER = ROOT / "scripts/v21/run_v21_202_repo_safe_cleanup_audit_and_cache_purge.ps1"


def load_module():
    spec = importlib.util.spec_from_file_location("v21_202", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    touch(root / "scripts/v21/__pycache__/x.pyc")
    touch(root / "scripts/v21/a.pyo")
    touch(root / ".pytest_cache/CACHEDIR.TAG")
    touch(root / "pytest_tmp/run.tmp")
    touch(root / "outputs/v21/pytest_tmp_abc/foo.tmp")
    touch(root / ".venv/Lib/site-packages/__pycache__/keep.pyc")
    touch(root / "outputs/v21/V21.197_FINAL/current.csv")
    touch(root / "outputs/v21/V21.199_R4/current.json")
    touch(root / "outputs/v21/V21.150_OLD/history.csv", "old")
    touch(root / "scripts/v21/v21_197_keep.py")
    touch(root / "scripts/v21/v21_199_keep.py")
    touch(root / "data/raw.csv")
    touch(root / "outputs/v20/price_history/CANONICAL_HISTORICAL_OHLCV.csv")
    return root


def test_dry_run_does_not_delete_cache_candidates(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    summary = module.run(root, execute=False)
    assert summary["final_status"] == "PASS_V21_202_DRY_RUN_CLEANUP_PLAN_READY"
    assert (root / "scripts/v21/__pycache__").exists()
    assert (root / ".pytest_cache").exists()
    assert (root / "pytest_tmp").exists()
    assert (root / "scripts/v21/a.pyo").exists()


def test_execute_deletes_pycache_and_pyc_pyo_outside_venv(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    touch(root / "pkg/__pycache__/mod.pyc")
    touch(root / "pkg/file.pyc")
    touch(root / "pkg/file.pyo")
    module.run(root, execute=True)
    assert not (root / "pkg/__pycache__").exists()
    assert not (root / "pkg/file.pyc").exists()
    assert not (root / "pkg/file.pyo").exists()


def test_execute_deletes_pytest_tmp_directories(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    module.run(root, execute=True)
    assert not (root / "pytest_tmp").exists()
    assert not (root / "outputs/v21/pytest_tmp_abc").exists()


def test_venv_is_never_deleted(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    module.run(root, execute=True, include_venv=True)
    assert (root / ".venv").exists()
    assert (root / ".venv/Lib/site-packages/__pycache__/keep.pyc").exists()


def test_protected_current_outputs_are_never_deleted(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    module.run(root, execute=True)
    assert (root / "outputs/v21/V21.197_FINAL/current.csv").exists()
    assert (root / "outputs/v21/V21.199_R4/current.json").exists()


def test_protected_scripts_are_never_deleted(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    module.run(root, execute=True)
    assert (root / "scripts/v21/v21_197_keep.py").exists()
    assert (root / "scripts/v21/v21_199_keep.py").exists()


def test_archive_candidates_are_listed_not_moved_or_deleted(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    module.run(root, execute=True)
    archive = rows(root / module.OUT_REL / "cleanup_archive_candidates.csv")
    assert any(r["path"] == "outputs/v21/V21.150_OLD" for r in archive)
    assert (root / "outputs/v21/V21.150_OLD/history.csv").exists()


def test_access_denied_during_deletion_is_recorded(tmp_path, monkeypatch):
    module = load_module()
    root = make_repo(tmp_path)
    denied = touch(root / "blocked.pyc")

    def deny_unlink(self):
        if self == denied:
            raise PermissionError("locked")
        return original_unlink(self)

    original_unlink = Path.unlink
    monkeypatch.setattr(Path, "unlink", deny_unlink)
    summary = module.run(root, execute=True)
    assert summary["final_status"] == "WARN_V21_202_CACHE_PURGE_PARTIAL_ACCESS_DENIED"
    denied_rows = rows(root / module.OUT_REL / "cleanup_access_denied_log.csv")
    assert any(r["path"] == "blocked.pyc" and r["error_type"] == "PermissionError" for r in denied_rows)
    assert denied.exists()


def test_protected_path_deletion_attempt_raises(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    candidate = {
        "path": "outputs/v21/V21.197_FINAL/current.csv",
        "candidate_type": "forced",
        "size_bytes": 1,
        "file_count": 1,
        "delete_allowed": True,
    }
    with pytest.raises(RuntimeError):
        module.delete_candidate(candidate, root, execute=True)


def test_summary_json_contains_required_fields(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    summary = module.run(root, execute=False)
    for key in ["final_status", "final_decision", "delete_allowed_total", "deleted_total", "access_denied_total"]:
        assert key in summary


def test_wrapper_exists_and_references_venv_python():
    assert WRAPPER.is_file()
    text = WRAPPER.read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in text
    assert "-Execute" in text or "$Execute" in text


def test_top_outputs_v21_size_summary_is_generated(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    module.run(root, execute=False)
    summary_rows = rows(root / module.OUT_REL / "repo_size_summary.csv")
    assert any(r["scope"] == "outputs/v21_child" and r["path"] == "outputs/v21/V21.150_OLD" for r in summary_rows)
