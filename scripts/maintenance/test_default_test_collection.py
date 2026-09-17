"""Exercise pytest discovery using synthetic files; never import legacy research."""
import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_default_acceptance_keeps_reviewed_runtime_and_read_boundary_suites(pytestconfig):
    selected = set(pytestconfig.getini("testpaths"))
    required = {
        "tests/storage/test_storage_paths.py",
        "scripts/maintenance/test_storage_maintenance_entrypoints.py",
        "scripts/maintenance/test_default_test_collection.py",
        "scripts/maintenance/test_harness_preflight.py",
        "scripts/v22/test_v22_047_r1d_live_market_account_bridge.py",
        "scripts/v22/test_v22_047_r1e_windows_service_hardening.py",
    }
    assert required <= selected, f"Default development acceptance lost reviewed contracts: {sorted(required - selected)}"


def test_default_collection_excludes_unreviewed_imports_and_allows_explicit_paths(tmp_path, pytestconfig):
    config = Path(pytestconfig.inipath)
    selected = pytestconfig.getini("testpaths")
    assert selected, "default tests must be explicitly selected"
    shutil.copyfile(config, tmp_path / "pytest.ini")
    for relative in selected:
        target = tmp_path / relative
        assert not Path(relative).is_absolute() and target.resolve().is_relative_to(tmp_path.resolve())
        assert target.suffix == ".py", "directory discovery can import unreviewed research tests"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("def test_synthetic():\n    pass\n", encoding="utf-8")

    for relative in ["test_unreviewed_root.py", "tests/storage/test_unreviewed_storage.py",
                     "scripts/v20/test_unreviewed_research.py"]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("raise AssertionError('unreviewed module imported during collection')\n", encoding="utf-8")

    explicit = tmp_path / "scripts/v20/test_explicit_synthetic_integration.py"
    explicit.write_text(
        "from pathlib import Path\n"
        "Path(__file__).with_suffix('.observed').write_text('explicit synthetic import')\n"
        "def test_explicit():\n    pass\n", encoding="utf-8")
    environment = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1")
    # The child is a disposable synthetic repository, independent of caller flags
    # and plugin configuration. Retain the real testpaths and pythonpath settings.
    environment.pop("PYTEST_ADDOPTS", None)
    environment.pop("PYTEST_PLUGINS", None)
    command = [sys.executable, "-B", "-m", "pytest", "-q", "-o", f"cache_dir={tmp_path / '.pytest_cache'}"]
    default = subprocess.run(command, cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=30)
    assert default.returncode == 0, default.stdout + default.stderr
    assert f"{len(selected)} passed" in default.stdout
    assert not explicit.with_suffix(".observed").exists()

    opted_in = subprocess.run(command + [str(explicit)], cwd=tmp_path, env=environment,
                              capture_output=True, text=True, timeout=30)
    assert opted_in.returncode == 0, opted_in.stdout + opted_in.stderr
    assert "1 passed" in opted_in.stdout
    assert explicit.with_suffix(".observed").read_text(encoding="utf-8") == "explicit synthetic import"
