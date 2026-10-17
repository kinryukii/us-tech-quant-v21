"""Synthetic relocation checks for the existing Python and PowerShell resolvers."""
import importlib.util
import json
import os
from types import SimpleNamespace
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


def test_official_raw_archive_is_an_explicit_allowed_source_root(relocated, monkeypatch, tmp_path):
    _, _, module = relocated
    cache = tmp_path / "cache"
    archive = tmp_path / "cold archive"
    outside = tmp_path / "unrelated"
    for root in (cache, archive, outside):
        root.mkdir()
    monkeypatch.setenv("USTQ_OFFICIAL_RAW_ARCHIVE_ROOT", str(archive))
    assert module.is_authorized_official_raw_path(cache / "source.zip", cache)
    assert module.is_authorized_official_raw_path(archive / "source.zip", cache)
    assert not module.is_authorized_official_raw_path(outside / "source.zip", cache)


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



def _directory_link(link, target):
    """Use ordinary Windows junctions; no symlink privilege or ACL changes."""
    target.mkdir(parents=True, exist_ok=True)
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        link.symlink_to(target, target_is_directory=True)
        return
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell, "PowerShell is required for synthetic junction checks"
    driver = link.parent / (link.name + "-create-junction.ps1")
    driver.write_text(
        "param($Link, $Target)\nNew-Item -ItemType Junction -Path $Link -Target $Target -ErrorAction Stop | Out-Null\n",
        encoding="utf-8-sig",
    )
    subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File", str(driver), str(link), str(target)],
                   capture_output=True, check=True, timeout=30)


def _windows_powershell_execution_policy_denied(shell_name, returncode, error):
    # Windows PowerShell wraps long-path diagnostics even within a word.
    compact_error = ''.join(error.split()).casefold()
    return (shell_name == 'powershell' and bool(returncode)
            and 'runningscriptsisdisabled' in compact_error
            and 'unauthorizedaccess' in compact_error)


def _powershell_check(tmp_path, repo, body, *, shell_name=None):
    shell = shutil.which(shell_name) if shell_name else (shutil.which("pwsh") or shutil.which("powershell"))
    if not shell:
        pytest.skip("PowerShell not installed")
    driver = tmp_path / "storage-guard-check.ps1"
    driver.write_text(
        "param($Resolver, $SelectedRepo)\n$ErrorActionPreference = 'Stop'\n"
        "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)\n"
        ". $Resolver\n$env:USTQ_REPO_ROOT = $SelectedRepo\n" + body,
        encoding="utf-8-sig",
    )
    result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File", str(driver),
                             str(ROOT / "scripts/common/storage_paths.ps1"), str(repo)],
                            capture_output=True, timeout=30)
    error = result.stderr.decode("utf-8", errors="replace")
    if _windows_powershell_execution_policy_denied(shell_name, result.returncode, error):
        pytest.skip("Windows PowerShell execution policy denies -File; policy was preserved")
    assert result.returncode == 0, error
    return json.loads(result.stdout.decode("utf-8-sig"))


@pytest.mark.parametrize("kind", ["data", "cache", "daily", "backtest", "results"])
@pytest.mark.parametrize("absolute", [False, True])
def test_kind_path_rejects_cross_root_escape(relocated, monkeypatch, kind, absolute):
    repo, cfg, module = relocated
    monkeypatch.setenv("USTQ_REPO_ROOT", str(repo))
    destination = Path(cfg["daily_root"] if kind != "daily" else cfg["results_root"]) / "unwritten.json"
    part = str(destination) if absolute else "../" + destination.parent.name + "/" + destination.name
    with pytest.raises(ValueError, match="must stay within its configured root"):
        getattr(module, "resolve_" + kind + "_path")(part)
    assert not destination.exists()


@pytest.mark.parametrize("target_key", ["repo_root", "data_root", "daily_root"])
def test_output_guard_resolves_junction_and_uncreated_suffix(relocated, monkeypatch, tmp_path, target_key):
    repo, cfg, module = relocated
    monkeypatch.setenv("USTQ_REPO_ROOT", str(repo))
    paths = module.resolve(repo)
    link = paths.results_root / "link"
    target = getattr(paths, target_key)
    _directory_link(link, target)
    output = link / "new folder" / "unwritten.json"
    with pytest.raises(ValueError):
        module.resolve_results_path("link", "new folder", "unwritten.json")
    with pytest.raises(ValueError):
        module.assert_safe_output_path(output, kind="results", paths=paths)
    assert not (target / "new folder").exists()
    actual = _powershell_check(tmp_path, repo, r"""
$paths = Get-UstqStoragePaths -RepoRoot $SelectedRepo
try { Assert-UstqExternalPath (Join-Path $paths.results_root 'link\new folder\unwritten.json') -Kind results; $rejected = $false }
catch { $rejected = $true; $reason = $_.Exception.Message }
@{ rejected=$rejected; reason=$reason } | ConvertTo-Json -Compress
""")
    assert actual["rejected"], actual
    assert actual["reason"].startswith(("REPO_PATH_REJECTED:", "CANONICAL_DATA_OUTPUT_REJECTED:", "OUTPUT_OUTSIDE_CONFIGURED_ROOT:"))


@pytest.mark.parametrize("target_key", ["data_root", "repo_root"])
def test_direct_storage_paths_cannot_hide_physical_root_alias(relocated, tmp_path, target_key):
    repo, cfg, module = relocated
    alias = tmp_path / "cache alias"
    _directory_link(alias, repo if target_key == "repo_root" else Path(cfg[target_key]))
    expected_error = "must not nest repo_root" if target_key == "repo_root" else "must be distinct"
    paths = module.StoragePaths(**{key: Path(value) for key, value in cfg.items()} | {"repo_root": repo, "cache_root": alias})
    with pytest.raises(ValueError, match=expected_error):
        module.validate(paths)
    with pytest.raises(ValueError, match=expected_error):
        module.resolve(repo, cache_root=alias)
    cfg["cache_root"] = str(alias)
    (repo / "config/storage_paths.json").write_text(json.dumps(cfg), encoding="utf-8")
    actual = _powershell_check(tmp_path, repo, r"""
try { Get-UstqStoragePaths -RepoRoot $SelectedRepo | Out-Null; $rejected = $false }
catch { $rejected = $true; $reason = $_.Exception.Message }
@{ rejected=$rejected; reason=$reason } | ConvertTo-Json -Compress
""")
    assert actual["rejected"]
    expected_prefix = "STORAGE_ROOT_NESTS_REPO:" if target_key == "repo_root" else "STORAGE_ROOTS_ALIAS_OR_NEST:"
    assert actual["reason"].startswith(expected_prefix)


def test_writable_initialization_leaves_data_and_envs_untouched(relocated, monkeypatch):
    repo, _, module = relocated
    paths = module.resolve(repo)
    touched = []
    original_mkdir = Path.mkdir

    def mkdir_output_only(path, *args, **kwargs):
        if path == paths.data_root or path == paths.envs_root:
            pytest.fail("read-only data/environment initialization attempted")
        touched.append(path)
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir_output_only)
    monkeypatch.setattr(module.os, "access", lambda path, mode: True)
    monkeypatch.setattr(module.shutil, "disk_usage", lambda path: SimpleNamespace(free=2 * 1024**3))
    module.validate(paths, require_writable=True)
    assert not paths.data_root.exists()
    assert not paths.envs_root.exists()
    assert all(getattr(paths, key + "_root").is_dir() for key in module.OUTPUT_KINDS)
    assert paths.data_root not in touched and paths.envs_root not in touched


@pytest.mark.parametrize("key", ["repo_root", "data_root", "envs_root"])
def test_output_guard_rejects_protected_roots_and_their_descendants(relocated, key):
    repo, _, module = relocated
    paths = module.resolve(repo)
    for output in (getattr(paths, key), getattr(paths, key) / "unwritten.json"):
        with pytest.raises(ValueError):
            module.assert_safe_output_path(output, paths=paths)


def test_output_guard_checks_kind_and_rejects_unapproved_external_path(relocated, tmp_path):
    repo, _, module = relocated
    paths = module.resolve(repo)
    module.assert_safe_output_path(paths.results_root / "report.json", kind="results", paths=paths)
    with pytest.raises(ValueError, match="configured results root"):
        module.assert_safe_output_path(paths.daily_root / "report.json", kind="results", paths=paths)
    with pytest.raises(ValueError, match="configured artifact root"):
        module.assert_safe_output_path(tmp_path / "unapproved" / "report.json", paths=paths)
    with pytest.raises(ValueError, match="unsupported output kind"):
        module.assert_safe_output_path(paths.results_root / "report.json", kind="data", paths=paths)


@pytest.mark.parametrize("shell_name", ["pwsh", "powershell"])
def test_powershell_checks_equal_repo_root_and_purpose_containment(relocated, tmp_path, shell_name):
    repo, _, _ = relocated
    actual = _powershell_check(tmp_path, repo, r"""
$paths = Get-UstqStoragePaths -RepoRoot $SelectedRepo
$checks = @{}
foreach ($key in 'repo_root','data_root','envs_root') {
    try { Assert-UstqExternalPath $paths[$key]; $checks[$key] = $false }
    catch { $checks[$key] = $true }
}
try { Assert-UstqExternalPath (Join-Path $paths.daily_root 'report.json') -Kind results; $checks.wrong_kind = $false }
catch { $checks.wrong_kind = $true }
Assert-UstqExternalPath (Join-Path $paths.results_root 'report.json') -Kind results
$checks | ConvertTo-Json -Compress
""", shell_name=shell_name)
    assert all(actual.values()), actual


def test_windows_powershell_policy_denial_handles_real_long_path_wrapping():
    # Same word-boundary wrapping observed in the preserved default-suite failure.
    error = (
        'File D:\\us-tech-quant-cache\\_maintenance\\DEMO_ALL_CHARTS_REFRESH_20261004\\manual_followup_20261005\\final_default_valida\r\n'
        'tion\\pytest_temp\\test_powershell_checks_equal_r1\\storage-guard-check.ps1 cannot be loaded because running scripts is di\r\n'
        'sabled on this system.\r\n'
        '    + FullyQualifiedErrorId : UnauthorizedAccess\r\n'
    )
    assert _windows_powershell_execution_policy_denied('powershell', 1, error)


@pytest.mark.parametrize('shell_name,returncode,error', [
    ('pwsh', 1, 'running scripts is disabled; UnauthorizedAccess'),
    ('powershell', 0, 'running scripts is disabled; UnauthorizedAccess'),
    ('powershell', 1, 'Access to the path is denied; UnauthorizedAccess'),
    ('powershell', 1, 'running scripts is disabled; UnexpectedToken'),
    ('powershell', 1, 'UnexpectedToken in synthetic test script'),
    ('powershell', 1, 'UnauthorizedAccess: other permission denied'),
])
def test_other_powershell_errors_are_not_execution_policy_skips(shell_name, returncode, error):
    assert not _windows_powershell_execution_policy_denied(shell_name, returncode, error)
