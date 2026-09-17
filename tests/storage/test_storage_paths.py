"""Synthetic relocation checks for the existing Python and PowerShell resolvers."""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def relocated(tmp_path, monkeypatch):
    keys = ("repo_root", "data_root", "cache_root", "daily_root", "backtest_root", "results_root", "envs_root")
    for key in keys:
        monkeypatch.delenv("USTQ_" + key.upper(), raising=False)
    monkeypatch.delenv("USTQ_PYTHON_EXE", raising=False)
    repo = tmp_path / "relocated repo 日本語"
    (repo / "config").mkdir(parents=True)
    cfg = {key: str(tmp_path / "external" / key) for key in keys}
    cfg["repo_root"] = str(tmp_path / "old repo no longer present")
    (repo / "config/storage_paths.json").write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    spec = importlib.util.spec_from_file_location("relocation_resolver", ROOT / "scripts/common/storage_paths.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return repo, cfg, module


@pytest.mark.parametrize("conflicting_env", [False, True])
def test_explicit_python_root_wins_over_copied_config_and_environment(relocated, monkeypatch, conflicting_env):
    repo, cfg, module = relocated
    if conflicting_env:
        monkeypatch.setenv("USTQ_REPO_ROOT", cfg["repo_root"])
    resolved = module.resolve(repo_root=repo)
    assert resolved.repo_root == repo.resolve()
    assert not Path(cfg["repo_root"]).exists()
    for key in cfg.keys() - {"repo_root"}:
        assert getattr(resolved, key) == Path(cfg[key]).resolve()


def test_environment_selected_root_still_works(relocated, monkeypatch):
    repo, cfg, module = relocated
    monkeypatch.setenv("USTQ_REPO_ROOT", str(repo))
    assert module.resolve().repo_root == repo.resolve()


def test_other_root_overrides_keep_their_precedence(relocated, monkeypatch, tmp_path):
    repo, cfg, module = relocated
    monkeypatch.setenv("USTQ_CACHE_ROOT", str(tmp_path / "env-cache"))
    assert module.resolve(repo).cache_root == tmp_path / "env-cache"
    assert module.resolve(repo, cache_root=tmp_path / "argument-cache").cache_root == tmp_path / "argument-cache"


def test_selected_root_is_used_for_nesting_validation(relocated):
    repo, cfg, module = relocated
    with pytest.raises(ValueError, match="must not nest repo_root"):
        module.resolve(repo, data_root=repo / "data")


@pytest.mark.parametrize("conflicting_env", [False, True])
def test_powershell_explicit_root_and_python_agree(relocated, monkeypatch, tmp_path, conflicting_env):
    repo, cfg, module = relocated
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        pytest.skip("PowerShell not installed")
    if conflicting_env:
        monkeypatch.setenv("USTQ_REPO_ROOT", cfg["repo_root"])
    cache = tmp_path / "cache override 日本語"
    monkeypatch.setenv("USTQ_CACHE_ROOT", str(cache))
    driver = tmp_path / "resolve.ps1"
    driver.write_text(
        "param([string]$Resolver, [string]$SelectedRepo)\n"
        "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)\n"
        ". $Resolver\nGet-UstqStoragePaths -RepoRoot $SelectedRepo | ConvertTo-Json -Compress\n",
        encoding="utf-8",
    )
    result = subprocess.run([
        shell, "-NoProfile", "-NonInteractive", "-File", str(driver),
        "-Resolver", str(ROOT / "scripts/common/storage_paths.ps1"), "-SelectedRepo", str(repo),
    ], capture_output=True, check=True)
    actual = json.loads(result.stdout.decode("utf-8-sig"))
    assert Path(actual["repo_root"]) == repo.resolve()
    expected = module.resolve(repo)
    for key in cfg:
        assert Path(actual[key]) == getattr(expected, key)
    assert Path(actual["python_exe"]) == expected.python_exe
