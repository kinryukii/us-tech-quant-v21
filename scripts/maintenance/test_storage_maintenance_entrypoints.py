"""Synthetic checks: no real research, cache, migration, or broker access."""
from __future__ import annotations

import importlib.util
import ast
import json
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest


R1E_INFRASTRUCTURE_SOURCES = (
    "install_v22_047_r1e_tasks.ps1", "start_v22_047_r1e_service.ps1",
    "start_v22_047_r1e_ui.ps1", "status_v22_047_r1e_service.ps1",
    "stop_v22_047_r1e_service.ps1",
    "v22_047_r1d_live_market_account_bridge.py", "v22_047_r1e_windows_service_hardening.py",
)


def _retired_development_component(value):
    return any(part.casefold() in {"data-layer-workspace", "data-gap-audit"}
               for part in re.split(r"[\\/]", value))


def test_infrastructure_sources_do_not_reintroduce_retired_development_paths(tmp_path, pytestconfig):
    """Inspect source literals only; never import or execute production scripts.

    This is a bounded regression for the retired personal source trees, not a
    complete dependency analyzer. Runtime relocation is exercised by R1E tests.
    New source files within these infrastructure directories join automatically.
    """
    repo = Path(pytestconfig.rootpath)
    sources = []
    for relative in ("scripts/common", "scripts/storage", "scripts/maintenance"):
        directory = repo / relative
        assert directory.is_dir(), f"Missing infrastructure source directory: {relative}"
        sources.extend(path for path in directory.rglob("*") if path.is_file()
                       and path.suffix.lower() in {".py", ".ps1"}
                       and not path.name.startswith("test_"))
    sources.extend(repo / "scripts/v22" / name for name in R1E_INFRASTRUCTURE_SOURCES)
    violations = []
    for path in sources:
        if path.suffix.lower() != ".py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        violations.extend(f"{path.relative_to(repo)}:{node.lineno}" for node in ast.walk(tree)
                          if isinstance(node, ast.Constant) and isinstance(node.value, str)
                          and _retired_development_component(node.value))

    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell, "PowerShell is required to validate the Windows entrypoint contract"
    source_list = tmp_path / "source-paths.json"
    source_list.write_text(json.dumps([str(path) for path in sources if path.suffix.lower() == ".ps1"]),
                           encoding="utf-8")
    parser = tmp_path / "parse-source-literals.ps1"
    parser.write_text(r'''
param($SourceList)
$ErrorActionPreference = 'Stop'
$rows = @()
foreach ($source in (Get-Content -LiteralPath $SourceList -Raw | ConvertFrom-Json)) {
    $tokens = $null; $errors = $null
    $tree = [System.Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw "Invalid PowerShell source: $source" }
    foreach ($node in $tree.FindAll({param($n)
        $n -is [System.Management.Automation.Language.StringConstantExpressionAst] -or
        $n -is [System.Management.Automation.Language.ExpandableStringExpressionAst]
    }, $true)) {
        $rows += [pscustomobject]@{ path=$source; line=$node.Extent.StartLineNumber; value=$node.Value }
    }
}
ConvertTo-Json -InputObject @($rows) -Compress
''', encoding="utf-8-sig")
    result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(parser), str(source_list)], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode == 0, result.stderr
    violations.extend(f"{Path(row['path']).relative_to(repo)}:{row['line']}"
                      for row in json.loads(result.stdout)
                      if _retired_development_component(row["value"]))
    assert not violations, "Use the canonical storage modules/resolver, not retired personal copies: " + ", ".join(violations)


@pytest.mark.parametrize("suffix,source", (
    (".py", "from pathlib import Path\nreader = Path('data-layer-workspace') / 'scripts/storage/storage_r2a.py'\n"),
    (".ps1", "$reader = Join-Path $RepoRoot 'data-gap-audit/rebuild_yahoo_lineage.py'\n"),
))
def test_new_infrastructure_source_cannot_silently_restore_personal_copy_dependency(tmp_path, suffix, source):
    repo = tmp_path / "synthetic repository"
    for directory in ("scripts/common", "scripts/storage", "scripts/maintenance", "scripts/v22"):
        (repo / directory).mkdir(parents=True)
    for name in R1E_INFRASTRUCTURE_SOURCES:
        (repo / "scripts/v22" / name).write_text("# Synthetic source only; never execute\n", encoding="utf-8")
    added = repo / "scripts/maintenance" / ("new_entry" + suffix)
    added.write_text(source, encoding="utf-8")
    with pytest.raises(AssertionError, match="canonical storage modules/resolver"):
        test_infrastructure_sources_do_not_reintroduce_retired_development_paths(
            tmp_path, types.SimpleNamespace(rootpath=repo))
    added.write_text("# A historical data-layer-workspace reference in commentary is not a dependency.\n",
                     encoding="utf-8")
    test_infrastructure_sources_do_not_reintroduce_retired_development_paths(
        tmp_path, types.SimpleNamespace(rootpath=repo))


def load_audit():
    path = Path(__file__).with_name("audit_repo_size_r1.py")
    spec = importlib.util.spec_from_file_location("storage_audit_entrypoint", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("complete,violations,passed", [
    (True, [], True), (False, [], False),
    (True, ["repository_worktree_budget:314572800"], False),
])
def test_audit_uses_existing_budget_and_rejects_incomplete_accounting(monkeypatch, complete, violations, passed):
    guard = types.ModuleType("fast3.scripts.audit.run_fast3_guard")
    guard.repository_policy = lambda: {"preferred_bytes": 150, "required_maximum_bytes": 300}
    guard.repository_budget = lambda root: {
        "repository_worktree_bytes": 160, "git_database_bytes": 20,
        "accounting_complete": complete, "violations": violations, "oversized_files": [],
    }
    monkeypatch.setitem(sys.modules, guard.__name__, guard)
    report = load_audit().audit(Path("synthetic"))
    assert report["hard_limit_bytes"] == 300
    assert report["repo_size_bytes"] == 180
    assert report["hard_limit_passed"] is passed
    assert report["size_is_lower_bound"] is (not complete)
    assert report["soft_warning"] is True


@pytest.mark.parametrize("flags,expected,success", [
    (["-AllSafe"], ["audit:", "retention:"], True),
    (["-Audit"], ["audit:"], True),
    (["-Verify"], ["migrate:-VerifyOnly"], True),
    (["-Migrate"], ["migrate:-Execute"], True),
    (["-AllSafe", "-Migrate"], [], False),
    (["-AllSafe", "-RetentionExecute"], [], False),
])
def test_powershell_dispatch_is_read_only_unless_explicit(tmp_path, flags, expected, success):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        pytest.skip("PowerShell is required for dispatch checks")
    source = Path(__file__).with_name("run_storage_maintenance_r1.ps1")
    driver = tmp_path / source.name
    shutil.copyfile(source, driver)
    for filename, name in [
        ("run_audit_repo_size_r1.ps1", "audit"),
        ("run_enforce_retention_policy_r1.ps1", "retention"),
        ("run_migrate_storage_layout_r1.ps1", "migrate"),
    ]:
        (tmp_path / filename).write_text(
            f"'{name}:' + ($args -join ',') | Add-Content -LiteralPath (Join-Path $PSScriptRoot 'calls.txt')\n",
            encoding="utf-8",
        )
    result = subprocess.run([shell, "-NoProfile", "-File", str(driver), *flags], capture_output=True)
    assert (result.returncode == 0) is success, result.stderr
    calls = tmp_path / "calls.txt"
    assert (calls.read_text(encoding="utf-8-sig").splitlines() if calls.exists() else []) == expected


def test_failed_audit_stops_before_explicit_migration(tmp_path):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        pytest.skip("PowerShell is required for dispatch checks")
    source = Path(__file__).with_name("run_storage_maintenance_r1.ps1")
    driver = tmp_path / source.name
    shutil.copyfile(source, driver)
    (tmp_path / "run_audit_repo_size_r1.ps1").write_text("exit 7\n", encoding="utf-8")
    (tmp_path / "run_migrate_storage_layout_r1.ps1").write_text(
        "'called' | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'mutation.txt')\n", encoding="utf-8")
    result = subprocess.run([shell, "-NoProfile", "-File", str(driver), "-Audit", "-Migrate"], capture_output=True)
    assert result.returncode != 0
    assert not (tmp_path / "mutation.txt").exists()
