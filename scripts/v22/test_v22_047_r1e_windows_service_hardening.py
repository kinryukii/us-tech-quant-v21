from __future__ import annotations
import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE / "v22_047_r1e_windows_service_hardening.py"
spec = importlib.util.spec_from_file_location("v22_047_r1e_test", MODULE_PATH)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)


def test_revision_and_loopback_contract():
    assert m.REVISION == "V22.047_R1E"
    assert m.HOST == "127.0.0.1" and m.PORT == 8765
    assert m.ALLOWED_EXECUTION_SYMBOLS == ("US.IQQ", "US.TQQQ", "US.SQQQ")


def test_no_broker_mutation_calls():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not set(m.BROKER_MUTATION_APIS).intersection(called)


def test_power_state_chinese_available_sleep_and_hibernate():
    text = "此系统上有以下睡眠状态:\n 待机 (S0)\n 休眠\n此系统上没有以下睡眠状态:\n待机 (S3)"
    result = m.power_state(text, ac_status=1)
    assert result["ac_connected"] is True
    assert result["system_sleep_allowed"] is True
    assert result["system_hibernate_allowed"] is True
    assert result["POWER_SAFE_FOR_BACKGROUND_TRADING"] is False
    assert result["power_policy_modified"] is False


def test_power_safe_only_when_ac_and_no_sleep_states():
    text = "The following sleep states are not available on this system: Standby (S3) Hibernate"
    result = m.power_state(text, ac_status=1)
    assert result["POWER_SAFE_FOR_BACKGROUND_TRADING"] is True


def test_unknown_exposure_detected():
    account = {"positions_detail":[{"code":"US.IQQ","qty":1},{"code":"US.AAPL","qty":2}],
               "open_orders":[{"code":"US.TQQQ"},{"code":"US.MSFT"}]}
    positions, orders = m.unknown_exposure(account)
    assert positions == ["US.AAPL"] and orders == ["US.MSFT"]


def test_degraded_latch_never_auto_clears(tmp_path):
    paths = m.Paths.for_repo(tmp_path); m.initialize(paths)
    first = m.latch_degraded(paths, ["UNKNOWN_POSITION"])
    second = m.latch_degraded(paths, ["UNKNOWN_OPEN_ORDER"])
    assert first["active"] is True and second["automatic_clear_allowed"] is False
    assert second["reasons"] == ["UNKNOWN_OPEN_ORDER", "UNKNOWN_POSITION"]


def make_repo(tmp_path: Path) -> m.Paths:
    repo = tmp_path / "repo"; (repo/"config").mkdir(parents=True); (repo/"scripts"/"v22").mkdir(parents=True)
    (repo/"config"/"moomoo_opend_connection.json").write_text(json.dumps({"host":"127.0.0.1","port":18441}),encoding="utf-8")
    return m.Paths.for_repo(repo)


def test_connection_rejects_wrong_port(tmp_path):
    paths = make_repo(tmp_path)
    paths.profile.write_text(json.dumps({"host":"127.0.0.1","port":11111}),encoding="utf-8")
    with pytest.raises(m.R1EError, match="18441"):
        m.connection(paths)


def test_enforce_shadow_replaces_live(tmp_path):
    paths = make_repo(tmp_path); m.initialize(paths); paths.r1d_output.mkdir(parents=True)
    m.atomic_json(paths.r1d_output/"switch_state.json", {"mode":"LIVE"})
    assert m.enforce_shadow_default(paths) == "SHADOW"
    assert m.read_json(paths.r1d_output/"switch_state.json")["mode"] == "SHADOW"
    assert m.read_json(paths.r1d_output/"emergency_stop.json")["active"] is False


def test_degraded_shadow_display_blocks_authorization(tmp_path):
    paths = make_repo(tmp_path); m.initialize(paths); paths.r1d_output.mkdir(parents=True)
    m.latch_degraded(paths,["UNKNOWN_POSITION"])
    m.enforce_shadow_default(paths)
    assert m.read_json(paths.r1d_output/"switch_state.json")["mode"] == "SHADOW"
    assert m.read_json(paths.r1d_output/"emergency_stop.json")["active"] is True


def test_dashboard_v2_required_sections_and_truth_labels():
    for text in ("SYSTEM","MARKET","STRATEGY","ACCOUNT","QQQ BENCHMARK","AUDIT","STRATEGY_NOT_CONFIGURED",
                 "SHADOW_ONLY","LIVE_NOT_AVAILABLE","PAPER_NOT_AVAILABLE","POWER STATE","EMERGENCY STOP"):
        assert text in m.DASHBOARD_HTML


def test_task_scripts_have_required_triggers_and_no_power_mutation():
    install = (HERE/"install_v22_047_r1e_tasks.ps1").read_text(encoding="utf-8")
    assert "-AtStartup" in install and "-AtLogOn" in install and "IgnoreNew" in install
    assert "127.0.0.1:18441" in install and 'default_mode = "SHADOW"' in install
    combined = "\n".join(p.read_text(encoding="utf-8") for p in HERE.glob("*v22_047_r1e*.ps1"))
    assert "powercfg /set" not in combined.lower()


def test_full_repo_categories_are_exact():
    runner = (HERE/"run_v22_047_r1e_full_repo_probe.py").read_text(encoding="utf-8")
    for category in ("PRE_EXISTING_BASELINE_FAILURE","ENVIRONMENT_DEPENDENT_FAILURE","PROTECTED_LEGACY_FAILURE",
                     "R1D_OR_R1E_REGRESSION","UNKNOWN_REQUIRES_REVIEW"):
        assert category in runner


def test_process_alive_current_process_uses_r1d_contract():
    fake = SimpleNamespace(SingleInstance=SimpleNamespace(alive=lambda pid: pid == os.getpid()))
    assert m.process_alive(fake, os.getpid()) is True


def test_start_engine_rejects_duplicate(tmp_path, monkeypatch):
    paths = make_repo(tmp_path); m.initialize(paths); (paths.r1d_output/"runtime").mkdir(parents=True)
    (paths.r1d_output/"runtime"/"engine.lock").write_text("123",encoding="ascii")
    fake = SimpleNamespace(SingleInstance=SimpleNamespace(alive=lambda pid: pid == 123))
    pid, started = m.start_engine(paths, fake)
    assert pid == 123 and started is False


def test_summary_is_always_shadow_and_broker_blocked(tmp_path, monkeypatch):
    paths = make_repo(tmp_path); m.initialize(paths); paths.r1d_output.mkdir(parents=True)
    m.atomic_json(paths.r1d_output/"strategy_decision.json", {"strategy_configured":False,"strategy_reason_code":"STRATEGY_NOT_CONFIGURED"})
    m.atomic_json(paths.r1d_output/"control_decision.json", {"r1b_control_component_called":True})
    m.atomic_json(paths.r1d_output/"switch_state.json", {"mode":"SHADOW"})
    monkeypatch.setattr(m,"power_state",lambda:{"POWER_SAFE_FOR_BACKGROUND_TRADING":False,"power_policy_modified":False})
    result = m.write_summary(paths,"RUNNING",{"watchdog_status":"HEALTHY"})
    assert result["final_status"] == "R1E_PASS_SHADOW_AUTOSTART_AND_DASHBOARD_READY"
    assert result["effective_execution_mode"] == "SHADOW_ONLY"
    assert result["strategy_configured"] is False
    assert result["broker_action_allowed"] is False and result["trade_api_called"] is False


def test_output_directory_is_gitignored():
    ignore = (HERE.parents[1]/".gitignore").read_text(encoding="utf-8")
    assert "outputs/" in ignore


def test_strategy_plugin_remains_exactly_unconfigured():
    plugin_path = HERE/"v22_047_r1b_strategy_plugin_template.py"
    sp = importlib.util.spec_from_file_location("r1e_strategy_check",plugin_path); assert sp and sp.loader
    plugin = importlib.util.module_from_spec(sp); sp.loader.exec_module(plugin)
    decision = plugin.generate_decision({})
    assert decision["action"] == "HOLD" and decision["symbol"] is None
    assert decision["target_notional_usd"] == 0 and decision["reason_code"] == "STRATEGY_NOT_CONFIGURED"


RUNTIME_SCRIPTS = (
    "install_v22_047_r1e_tasks.ps1", "start_v22_047_r1e_service.ps1",
    "start_v22_047_r1e_ui.ps1", "status_v22_047_r1e_service.ps1",
)


def _runtime_repo(tmp_path, monkeypatch):
    # Neither the legacy environment nor the stale configured checkout exists.
    repo = tmp_path / "new checkout 中文"
    (repo / "config").mkdir(parents=True)
    (repo / "scripts/common").mkdir(parents=True)
    (repo / "scripts/v22").mkdir(parents=True)
    shutil.copyfile(HERE.parents[1] / "scripts/common/storage_paths.ps1",
                    repo / "scripts/common/storage_paths.ps1")
    for name in RUNTIME_SCRIPTS:
        shutil.copyfile(HERE / name, repo / "scripts/v22" / name)
    roots = {key: str(tmp_path / key) for key in
             ("data_root", "cache_root", "daily_root", "backtest_root", "results_root", "envs_root")}
    roots["repo_root"] = str(tmp_path / "removed old checkout")
    roots["envs_root"] = str(tmp_path / "external environments 中文")
    (repo / "config/storage_paths.json").write_text(json.dumps(roots), encoding="utf-8")
    runtime = Path(roots["envs_root"]) / "us-tech-quant-main/Scripts/python.exe"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"synthetic path marker; never execute")
    for key in [key for key in os.environ if key.startswith("USTQ_")]:
        monkeypatch.delenv(key)
    assert not (repo / ".venv").exists()
    assert not Path(roots["repo_root"]).exists()
    return repo, runtime


def _powershell(tmp_path, source, *arguments):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        pytest.skip("PowerShell is required for Windows entrypoint checks")
    harness = tmp_path / "runtime_harness.ps1"
    harness.write_text(source, encoding="utf-8-sig")
    return subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-File", str(harness), *map(str, arguments)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)


@pytest.mark.parametrize("name", RUNTIME_SCRIPTS)
@pytest.mark.parametrize("runtime_exists", (True, False))
def test_entrypoints_resolve_external_runtime_before_side_effects(tmp_path, monkeypatch, name, runtime_exists):
    repo, runtime = _runtime_repo(tmp_path, monkeypatch)
    if not runtime_exists:
        runtime.unlink()
    # Execute each real entrypoint's configuration prefix through $Main. This
    # includes dot-sourcing the canonical resolver; process/service code is not
    # admitted. The separate installer test below executes the entire installer.
    result = _powershell(tmp_path, r'''
param($RepoRoot, $Name)
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$source = Join-Path $RepoRoot ('scripts/v22/' + $Name)
$tree = [System.Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Invalid PowerShell' }
$main = $tree.EndBlock.Statements | Where-Object {
    $_ -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $_.Left.Extent.Text -eq '$Main'
} | Select-Object -First 1
if ($null -eq $main) { throw 'Missing main binding' }
$prefix = [IO.File]::ReadAllText($source).Substring(0, $main.Extent.EndOffset)
$prefix += "`n[ordered]@{python=`$Python; main=`$Main} | ConvertTo-Json -Compress"
& ([scriptblock]::Create($prefix)) -RepoRoot $RepoRoot
''', repo, name)
    if runtime_exists:
        assert result.returncode == 0, result.stderr
        dispatch = json.loads(result.stdout.strip())
        assert Path(dispatch["python"]) == runtime
        assert Path(dispatch["main"]) == repo / "scripts/v22/v22_047_r1e_windows_service_hardening.py"
    else:
        assert result.returncode != 0
        assert "Python not found:" in result.stderr
    assert not (repo / "outputs").exists()
    assert not (repo / ".venv").exists()


def test_installer_registers_external_runtime_with_unchanged_arguments(tmp_path, monkeypatch):
    repo, _ = _runtime_repo(tmp_path, monkeypatch)
    monkeypatch.setenv("USTQ_PYTHON_EXE", sys.executable)
    main = repo / "scripts/v22/v22_047_r1e_windows_service_hardening.py"
    main.write_text("raise RuntimeError('SYNTHETIC_SERVICE_MUST_NOT_RUN')\n", encoding="utf-8")
    actions_file = tmp_path / "registered_actions.json"
    result = _powershell(tmp_path, r'''
param($RepoRoot, $ActionsFile)
$ErrorActionPreference = 'Stop'
$global:SyntheticScheduledTasks = [ordered]@{}
function New-ScheduledTaskAction {
    param($Execute, $Argument, $WorkingDirectory)
    [pscustomobject]@{Execute=$Execute; Arguments=$Argument; WorkingDirectory=$WorkingDirectory}
}
function New-ScheduledTaskSettingsSet { [pscustomobject]@{} }
function New-ScheduledTaskTrigger { [pscustomobject]@{Delay=''} }
function New-ScheduledTaskPrincipal { [pscustomobject]@{} }
function New-ScheduledTask {
    param($Action, $Trigger, $Settings, $Principal, $Description)
    [pscustomobject]@{Action=$Action}
}
function Register-ScheduledTask {
    param($TaskName, $InputObject, [switch]$Force, $ErrorAction)
    $global:SyntheticScheduledTasks[$TaskName] = $InputObject.Action
}
function Get-ScheduledTask {
    param($TaskName, $ErrorAction)
    foreach ($name in $global:SyntheticScheduledTasks.Keys) {
        if ($name -like $TaskName) { [pscustomobject]@{TaskName=$name; State='SYNTHETIC'} }
    }
}
& (Join-Path $RepoRoot 'scripts/v22/install_v22_047_r1e_tasks.ps1') -RepoRoot $RepoRoot -TaskPrefix 'SYNTHETIC'
$global:SyntheticScheduledTasks | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ActionsFile -Encoding utf8
''', repo, actions_file)
    assert result.returncode == 0, result.stdout + result.stderr
    actions = json.loads(actions_file.read_text(encoding="utf-8-sig"))
    assert set(actions) == {"SYNTHETIC-Service-Startup", "SYNTHETIC-Service-Logon", "SYNTHETIC-Dashboard-OnDemand"}
    for name, action in actions.items():
        command = "ui" if name.endswith("OnDemand") else "service"
        expected = f'"{main}" {command} --repo-root "{repo}"'
        if command == "service":
            expected += " --wait-seconds 1800"
        assert Path(action["Execute"]) == Path(sys.executable)
        assert action["Arguments"] == expected
        assert Path(action["WorkingDirectory"]) == repo
    assert not (repo / ".venv").exists()


def test_quote_probe_uses_no_history_and_isolated_sdk_output(tmp_path):
    paths = make_repo(tmp_path)
    calls = []
    output = tmp_path / "acceptance"

    class Bridge:
        def __init__(self, profile, destination, age):
            calls.append((profile, destination, age))

        def market_snapshot(self, *, include_history):
            assert include_history is False
            return {"snapshot_ready": True}

    fake = SimpleNamespace(load_connection_profile=lambda path: {"path": path}, MoomooReadOnlyBridge=Bridge)
    assert m.quote_probe(paths, fake, output_dir=output) == (True, "QUOTE_API_OK")
    assert calls == [({"path": paths.profile}, output, 15.0)]
    assert not output.exists() and not paths.output.exists()


@pytest.mark.parametrize("status,watchdog", [
    ("FAILED", "HEALTHY"), ("WAITING_FOR_NETWORK", "HEALTHY"),
    ("WAITING_FOR_OPEND", None), ("WAITING_FOR_QUOTE_API", "DEGRADED"),
    ("STARTING", None), ("STOPPING", "HEALTHY"), ("RUNNING", "DEGRADED"), ("RUNNING", None),
])
def test_nonready_summary_never_claims_pass(tmp_path, monkeypatch, status, watchdog):
    paths = make_repo(tmp_path)
    monkeypatch.setattr(m, "power_state", lambda: {"POWER_SAFE_FOR_BACKGROUND_TRADING": False})
    result = m.write_summary(paths, status, {"watchdog_status": watchdog} if watchdog else None)
    assert "PASS" not in result["final_status"]
    assert status in result["final_status"]
    assert result["service_status"] == status


def _startup_check_storage(paths, tmp_path, monkeypatch):
    for key in [key for key in os.environ if key.startswith("USTQ_")]:
        monkeypatch.delenv(key)
    common = paths.repo / "scripts/common"
    common.mkdir(parents=True)
    shutil.copyfile(HERE.parents[1] / "scripts/common/storage_paths.py", common / "storage_paths.py")
    roots = {key: str(tmp_path / key) for key in
             ("data_root", "cache_root", "daily_root", "backtest_root", "results_root", "envs_root")}
    roots["repo_root"] = str(paths.repo)
    (paths.repo / "config/storage_paths.json").write_text(json.dumps(roots), encoding="utf-8")
    return Path(roots["results_root"]) / "_maintenance" / "startup_check.json"


def _startup_check_service(tmp_path, monkeypatch, *, quote_ready=True, network_ready=True):
    paths = make_repo(tmp_path)
    output = _startup_check_storage(paths, tmp_path, monkeypatch)
    shutil.copyfile(HERE / "v22_047_r1d_live_market_account_bridge.py", paths.r1d_script)
    protected = {
        paths.output / "service.stop": b"preserve service stop",
        paths.output / "watchdog.stop": b"preserve watchdog stop",
        paths.output / "autostart_state.json": b'{"service_invoked": false}',
        paths.output / "service_state.json": b'{"service_status": "STOPPED"}',
        paths.output / "v22_047_r1e_summary.json": b'{"service_status": "STOPPED"}',
        paths.r1d_output / "switch_state.json": b'{"mode": "OFF"}',
        paths.r1d_output / "emergency_stop.json": b'{"active": true}',
    }
    for path, payload in protected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    service = m.Service(paths.repo, 0.02, startup_check_only=True, startup_check_output=output)
    before = {str(path.relative_to(paths.repo)): path.read_bytes()
              for path in paths.repo.rglob("*") if path.is_file()}
    monkeypatch.setattr(m, "network_available", lambda: network_ready)
    monkeypatch.setattr(m, "tcp_ready", lambda *args: True)
    probes = []

    def probe(_paths, _r1d, *, output_dir):
        probes.append(output_dir)
        return quote_ready, "QUOTE_API_OK" if quote_ready else "QUOTE_DATA_NOT_READY"

    monkeypatch.setattr(m, "quote_probe", probe)
    def forbidden(*args, **kwargs):
        raise AssertionError("Startup check must not write service state or start workers")
    for name in ("initialize", "enforce_shadow_default", "set_switch", "start_engine",
                 "launch_python", "write_summary", "audit", "record_error", "watchdog_snapshot"):
        monkeypatch.setattr(m, name, forbidden)
    return service, before, probes


@pytest.mark.parametrize("quote_ready,network_ready,expected", [
    (True, True, "STARTUP_PREREQUISITES_READY"),
    (False, True, "STARTUP_CHECK_FAILED"), (False, False, "STARTUP_CHECK_FAILED"),
])
def test_startup_check_preserves_all_service_authorization_and_starts_nothing(
        tmp_path, monkeypatch, quote_ready, network_ready, expected):
    service, before, probes = _startup_check_service(
        tmp_path, monkeypatch, quote_ready=quote_ready, network_ready=network_ready)
    result = service.run()
    assert result == (0 if quote_ready else 2)
    payload = m.read_json(service.startup_check_output)
    assert payload["startup_check_status"] == expected
    assert "service_status" not in payload
    assert payload["service_started"] is False and payload["workers_started"] is False
    assert payload["history_requested"] is False and payload["account_queried"] is False
    assert not service.lock.path.exists()
    if network_ready:
        assert probes and set(probes) == {service.startup_check_output.parent}
    else:
        assert probes == []
    if not quote_ready:
        assert "STARTUP_PREREQUISITE_TIMEOUT" in payload["detail"]
        assert ("QUOTE_DATA_NOT_READY" if network_ready else "NETWORK_UNAVAILABLE") in payload["detail"]
    after = {str(path.relative_to(service.paths.repo)): path.read_bytes()
             for path in service.paths.repo.rglob("*") if path.is_file()}
    assert after == before


def test_startup_check_rejects_existing_service_lock_without_probing(tmp_path, monkeypatch):
    service, _, probes = _startup_check_service(tmp_path, monkeypatch)
    service.lock.path.parent.mkdir(parents=True, exist_ok=True)
    service.lock.path.write_text(str(os.getpid()), encoding="ascii")
    with pytest.raises(service.r1d.R1DError, match="ALREADY_RUNNING"):
        service.run()
    assert probes == [] and not service.startup_check_output.exists()
    assert service.lock.path.read_text(encoding="ascii") == str(os.getpid())


def test_startup_check_constructor_skips_formal_output_initialization(tmp_path):
    paths = make_repo(tmp_path)
    shutil.copyfile(HERE / "v22_047_r1d_live_market_account_bridge.py", paths.r1d_script)
    service = m.Service(paths.repo, startup_check_only=True)
    assert not paths.output.exists() and not paths.r1d_output.exists()
    assert service.startup_check_output == paths.output / "startup_check.json"


@pytest.mark.parametrize("target_kind", ("repository", "canonical_data", "service_authorization"))
def test_startup_check_rejects_protected_output_before_any_writes(tmp_path, monkeypatch, target_kind):
    paths = make_repo(tmp_path)
    _startup_check_storage(paths, tmp_path, monkeypatch)
    target = {"repository": paths.repo / "config/important.json",
              "canonical_data": tmp_path / "data_root/source.json",
              "service_authorization": paths.r1d_output / "switch_state.json"}[target_kind]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b'{"keep_original": true}')
    before = {str(path.relative_to(tmp_path)): path.read_bytes()
              for path in tmp_path.rglob("*") if path.is_file()}
    with pytest.raises(m.R1EError, match="OUTPUT_MUST_BE_UNDER_RESULTS_MAINTENANCE"):
        m.Service(paths.repo, startup_check_only=True, startup_check_output=target)
    after = {str(path.relative_to(tmp_path)): path.read_bytes()
             for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before
    assert not paths.runtime.exists()


@pytest.mark.parametrize("exit_code", (0, 2))
def test_startup_check_powershell_propagates_arguments_failure_and_no_state_changes(tmp_path, monkeypatch, exit_code):
    repo, _ = _runtime_repo(tmp_path, monkeypatch)
    monkeypatch.setenv("USTQ_PYTHON_EXE", sys.executable)
    main = repo / "scripts/v22/v22_047_r1e_windows_service_hardening.py"
    main.write_text("import json,sys\nfrom pathlib import Path\n"
                    "Path(sys.argv[sys.argv.index('--startup-check-output')+1]).write_text(json.dumps(sys.argv[1:]))\n"
                    f"raise SystemExit({exit_code})\n", encoding="utf-8")
    output = tmp_path / "synthetic dispatch 中文.json"
    result = _powershell(tmp_path, r'''
param($RepoRoot, $OutputPath)
$ErrorActionPreference = 'Stop'
& (Join-Path $RepoRoot 'scripts/v22/start_v22_047_r1e_service.ps1') -RepoRoot $RepoRoot -StartupCheckOnly -WaitSeconds 0.25 -StartupCheckOutput $OutputPath
''', repo, output)
    dispatch = json.loads(output.read_text(encoding="utf-8"))
    assert dispatch == ["service", "--repo-root", str(repo), "--wait-seconds", "0.25",
                        "--startup-check-only", "--startup-check-output", str(output)]
    assert not (repo / "outputs").exists()
    if exit_code:
        assert result.returncode != 0
        assert "startup prerequisite check failed" in result.stderr
        assert "STARTUP_PREREQUISITES_READY" not in result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert "startup_check_status=STARTUP_PREREQUISITES_READY" in result.stdout


def test_status_propagates_child_exit_code(tmp_path, monkeypatch):
    repo, _ = _runtime_repo(tmp_path, monkeypatch)
    monkeypatch.setenv("USTQ_PYTHON_EXE", sys.executable)
    main = repo / "scripts/v22/v22_047_r1e_windows_service_hardening.py"
    main.write_text("import sys\nassert sys.argv[1] == 'status'\nsys.exit(7)\n", encoding="utf-8")
    result = _powershell(tmp_path, r'''
param($RepoRoot)
function Get-ScheduledTask { }
& (Join-Path $RepoRoot 'scripts/v22/status_v22_047_r1e_service.ps1') -RepoRoot $RepoRoot
exit $LASTEXITCODE
''', repo)
    assert result.returncode == 7, result.stdout + result.stderr


@pytest.mark.parametrize("cancel_mode", ("signal", "stop_file"))
def test_normal_service_cancel_during_probe_never_starts_workers(tmp_path, monkeypatch, cancel_mode):
    paths = make_repo(tmp_path)
    shutil.copyfile(HERE / "v22_047_r1d_live_market_account_bridge.py", paths.r1d_script)
    service = m.Service(paths.repo, wait_seconds=1)
    monkeypatch.setattr(m, "network_available", lambda: True)
    monkeypatch.setattr(m, "tcp_ready", lambda *args: True)
    monkeypatch.setattr(m, "power_state", lambda: {"POWER_SAFE_FOR_BACKGROUND_TRADING": False})
    started = []
    monkeypatch.setattr(m, "start_engine", lambda *args: started.append("engine") or (0, False))
    monkeypatch.setattr(m, "launch_python", lambda *args: started.append("worker") or 0)
    def probe(*args, **kwargs):
        if cancel_mode == "signal":
            service.running = False
        else:
            (paths.output / "service.stop").touch()
        return True, "SYNTHETIC_READY_AFTER_CANCEL"
    monkeypatch.setattr(m, "quote_probe", probe)
    assert service.run() == 0
    assert started == []
    assert m.read_json(paths.output / "service_state.json")["service_status"] == "STOPPED"
    assert not service.lock.path.exists()


_CONTROLLED_SERVICE = r'''
import importlib.util, json, os, sys, time
from pathlib import Path
entrypoint = Path(__file__).resolve()
repo = entrypoint.parents[2]
if __name__ == '__main__':
    sys.modules['moomoo'] = None
def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
r1d = load(repo/'scripts/v22/r1d_source.py', 'controlled_r1d')
SingleInstance = r1d.SingleInstance
if __name__ != '__main__':
    # The real Service imports the R1D entrypoint for this lock implementation.
    # Importing a substitute must never start a worker.
    def __getattr__(name):
        return getattr(r1d, name)
else:
    assert Path(sys.argv[sys.argv.index('--repo-root') + 1]).resolve() == repo
    role = sys.argv[1] if 'r1e_' in entrypoint.name else (
        'engine' if 'r1d_' in entrypoint.name else entrypoint.name.split('_')[2])
    manifest = json.loads((repo/'controlled_workers.json').read_text())
    if role == 'service':
        service = load(repo/'scripts/v22/r1e_source.py', 'controlled_r1e')
        original_launch = service.launch_python
        def launch(paths, arguments, pid_path):
            assert paths.repo == repo and Path(arguments[0]).resolve().is_relative_to(repo)
            assert pid_path.resolve().is_relative_to(repo)
            name = pid_path.stem.replace('_launcher', '')
            assert name in manifest
            executable = Path(arguments[0])
            if executable.name == 'r1e_source.py':
                executable = entrypoint
            assert executable.read_text(encoding='utf-8') == entrypoint.read_text(encoding='utf-8')
            # Real launch_python, Service and SingleInstance; only temporary
            # canonical entrypoints execute these bounded synthetic workers.
            pid = original_launch(paths, [str(executable), *arguments[1:]], pid_path)
            service.atomic_json(repo/'events'/f'launch.{name}.{pid}.json', {
                'requested_script': arguments[0], 'executed_script': str(executable), 'pid': pid})
            return pid
        service.launch_python = launch
        service.network_available = lambda: True
        service.tcp_ready = lambda *args, **kwargs: True
        service.quote_probe = lambda *args, **kwargs: (True, 'SYNTHETIC_QUOTE_READY')
        service.power_state = lambda: {'POWER_SAFE_FOR_BACKGROUND_TRADING': False, 'power_policy_modified': False}
        original_state = service.Service.state
        def state(instance, status, detail=''):
            fault = repo/'service_fail_after_start.flag'
            if status == 'RUNNING' and fault.exists():
                fault.unlink()
                raise RuntimeError('SYNTHETIC_SERVICE_MANAGER_FAILURE')
            result = original_state(instance, status, detail)
            if status == 'RUNNING':
                instance.synthetic_running_count = getattr(instance, 'synthetic_running_count', 0) + 1
                service.atomic_json(repo/'events'/f'manager.{os.getpid()}.json', {
                    'pid': os.getpid(), 'running_count': instance.synthetic_running_count})
            return result
        service.Service.state = state
        raise SystemExit(service.main(['service', '--repo-root', str(repo), '--wait-seconds', '1']))
    stop = repo/manifest[role]
    stop.parent.mkdir(parents=True, exist_ok=True)
    lock = r1d.SingleInstance(stop.parent/'runtime'/f'{role}.lock')
    lock.acquire()
    stop.unlink(missing_ok=True)
    pid = os.getpid()
    r1d.atomic_json(repo/'events'/f'start.{role}.{pid}.json', {'role': role, 'pid': pid})
    try:
        deadline = time.monotonic() + 60
        while not stop.exists() and time.monotonic() < deadline:
            crash = repo/'crash_role.txt'
            if crash.exists() and crash.read_text() == role:
                crash.unlink()
                os._exit(23)  # Deliberately retain a stale lock for restart coverage.
            if role == 'engine':
                r1d.atomic_json(stop.parent/'engine_heartbeat.json', {
                    'timestamp_utc': r1d.utc_iso(), 'pid': pid, 'status': 'ALIVE'})
            time.sleep(.03)
    finally:
        lock.release()
        r1d.atomic_json(repo/'events'/f'exit.{role}.{pid}.json', {'role': role, 'pid': pid})
'''


def _controlled_service_repo(tmp_path):
    paths = make_repo(tmp_path)
    scripts = paths.repo / "scripts/v22"
    for role, name in (("r1d", "v22_047_r1d_live_market_account_bridge.py"),
                       ("r1e", "v22_047_r1e_windows_service_hardening.py")):
        shutil.copyfile(HERE / name, scripts / f"{role}_source.py")
        (scripts / name).write_text(_CONTROLLED_SERVICE, encoding="utf-8")
    shutil.copyfile(HERE / "stop_v22_047_r1e_service.ps1", scripts / "stop_v22_047_r1e_service.ps1")
    workers = {
        "engine": str((paths.r1d_output / "engine.stop").relative_to(paths.repo)),
        "watchdog": str((paths.output / "watchdog.stop").relative_to(paths.repo)),
    }
    for role, script, output in (
        ("r1f", "fractional_protected_sleeve", "V22.047_R1F_V8_REFERENCE_ROTATION_FRACTIONAL_RTH_PROTECTED_SLEEVE_SHADOW"),
        ("r1g", "shadow_fractional_assumption_and_execution_arming", "V22.047_R1G_SHADOW_FRACTIONAL_ASSUMPTION_AND_EXECUTION_ARMING"),
        ("r1h", "paper_execution_order_lifecycle_and_reconciliation", "V22.047_R1H_PAPER_EXECUTION_ORDER_LIFECYCLE_AND_RECONCILIATION"),
        ("r1i", "paper_soak_replay_fault_injection_and_live_readiness_gate", "V22.047_R1I_PAPER_SOAK_REPLAY_FAULT_INJECTION_AND_LIVE_READINESS_GATE"),
    ):
        (scripts / f"v22_047_{role}_{script}.py").write_text(_CONTROLLED_SERVICE, encoding="utf-8")
        workers[role] = str(Path("outputs/v22") / output / f"{role}.stop")
    (paths.repo / "controlled_workers.json").write_text(json.dumps(workers), encoding="utf-8")
    bootstrap = scripts / "v22_047_r1e_windows_service_hardening.py"
    (paths.repo / "events").mkdir()
    return paths, workers, bootstrap


def _wait_until(condition, *, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(.05)
    assert condition(), "Controlled lifecycle condition did not complete within its deadline"


@pytest.mark.parametrize("pid_file", ("engine_launcher.pid", "r1h.pid"))
def test_stop_rejects_unrelated_live_pid_without_killing_or_removing_evidence(tmp_path, pid_file):
    paths = make_repo(tmp_path)
    paths.runtime.mkdir(parents=True)
    paths.r1d_output.mkdir(parents=True)
    shutil.copyfile(HERE / "stop_v22_047_r1e_service.ps1", paths.repo / "scripts/v22/stop_v22_047_r1e_service.ps1")
    with subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(60)"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as sentinel:
        pid_path = paths.runtime / pid_file
        pid_path.write_text(str(sentinel.pid), encoding="ascii")
        try:
            result = _powershell(tmp_path, r'''
param($RepoRoot)
& (Join-Path $RepoRoot 'scripts/v22/stop_v22_047_r1e_service.ps1') -RepoRoot $RepoRoot
exit $LASTEXITCODE
''', paths.repo)
            assert result.returncode != 0, result.stdout + result.stderr
            assert "IDENTITY_NOT_CONFIRMED" in result.stdout + result.stderr
            assert "stop_status=PASS" not in result.stdout
            assert sentinel.poll() is None
            assert pid_path.read_text(encoding="ascii") == str(sentinel.pid)
        finally:
            if sentinel.poll() is None:
                sentinel.terminate()
            sentinel.wait(timeout=5)


def test_stop_is_idempotent_before_first_service_start(tmp_path):
    paths = make_repo(tmp_path)
    shutil.copyfile(HERE / "stop_v22_047_r1e_service.ps1", paths.repo / "scripts/v22/stop_v22_047_r1e_service.ps1")
    for _ in range(2):
        result = _powershell(tmp_path, r'''
param($RepoRoot)
& (Join-Path $RepoRoot 'scripts/v22/stop_v22_047_r1e_service.ps1') -RepoRoot $RepoRoot
exit $LASTEXITCODE
''', paths.repo)
        assert result.returncode == 0, result.stdout + result.stderr
    assert (paths.r1d_output / "engine.stop").exists()


def test_stop_forces_only_a_verified_owned_worker(tmp_path, record_property):
    paths = make_repo(tmp_path)
    paths.runtime.mkdir(parents=True)
    r1d = m.load_module(HERE / "v22_047_r1d_live_market_account_bridge.py", "forced_worker_parent_r1d")
    shutil.copyfile(HERE / "stop_v22_047_r1e_service.ps1", paths.repo / "scripts/v22/stop_v22_047_r1e_service.ps1")
    script = paths.repo / "scripts/v22/v22_047_r1h_paper_execution_order_lifecycle_and_reconciliation.py"
    script.write_text("import os,time\nfrom pathlib import Path\n"
        f"Path({str(paths.repo / 'actual_worker.pid')!r}).write_text(str(os.getpid()))\n"
        f"cleanup = Path({str(paths.repo / 'test_cleanup.stop')!r})\n"
        "deadline = time.monotonic() + 60\n"
        "while not cleanup.exists() and time.monotonic() < deadline: time.sleep(.03)\n", encoding="utf-8")
    # Preserve the exact production launch_python PID file, including the
    # Windows venv launcher when it forwards to a separate Python worker.
    launcher_pid = m.launch_python(paths, [str(script), "--service", "--repo-root", str(paths.repo)], paths.runtime / "r1h.pid")
    actual_pid = None
    try:
        _wait_until(lambda: (paths.repo / "actual_worker.pid").exists())
        actual_pid = int((paths.repo / "actual_worker.pid").read_text())
        assert int((paths.runtime / "r1h.pid").read_text()) == launcher_pid
        record_property("forced_stop_launcher_pid", launcher_pid)
        record_property("forced_stop_actual_worker_pid", actual_pid)
        result = _powershell(tmp_path, r'''
param($RepoRoot)
& (Join-Path $RepoRoot 'scripts/v22/stop_v22_047_r1e_service.ps1') -RepoRoot $RepoRoot
exit $LASTEXITCODE
''', paths.repo)
        assert result.returncode == 0, result.stdout + result.stderr
        assert not r1d.SingleInstance.alive(actual_pid), f"launcher={launcher_pid} actual_worker={actual_pid} still alive"
        _wait_until(lambda: not r1d.SingleInstance.alive(launcher_pid), timeout=5)
        assert not (paths.runtime / "r1h.pid").exists()
    finally:
        (paths.repo / "test_cleanup.stop").touch()
        _wait_until(lambda: not r1d.SingleInstance.alive(launcher_pid) and
                   (actual_pid is None or not r1d.SingleInstance.alive(actual_pid)), timeout=5)


def test_normal_service_real_process_start_crash_restart_duplicate_stop_and_restart(tmp_path, record_property):
    paths, workers, bootstrap = _controlled_service_repo(tmp_path)
    r1d = m.load_module(paths.r1d_script, "controlled_parent_r1d")
    processes = []
    try:
        for round_number in (1, 2):
            started_before = set((paths.repo / "events").glob("start.*.json"))
            process = subprocess.Popen([sys.executable, "-B", str(bootstrap), "service", "--repo-root", str(paths.repo)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            processes.append(process)
            _wait_until(lambda: len(set((paths.repo / "events").glob("start.*.json")) - started_before) >= len(workers))
            _wait_until(lambda: m.read_json(paths.output / "service_state.json", {}).get("service_status") == "RUNNING")
            state_before = (paths.output / "service_state.json").read_bytes()
            duplicate = subprocess.run([sys.executable, "-B", str(bootstrap), "service", "--repo-root", str(paths.repo)],
                capture_output=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            assert duplicate.returncode == 2 and b"ALREADY_RUNNING" in duplicate.stderr
            assert (paths.output / "service_state.json").read_bytes() == state_before
            if round_number == 1:
                watchdogs_before = set((paths.repo / "events").glob("start.watchdog.*.json"))
                (paths.repo / "crash_role.txt").write_text("watchdog", encoding="ascii")
                _wait_until(lambda: len(set((paths.repo / "events").glob("start.watchdog.*.json")) - watchdogs_before) == 1)
            stopped = _powershell(tmp_path, r'''
param($RepoRoot)
& (Join-Path $RepoRoot 'scripts/v22/stop_v22_047_r1e_service.ps1') -RepoRoot $RepoRoot
''', paths.repo)
            assert stopped.returncode == 0, stopped.stdout + stopped.stderr
            assert process.wait(timeout=15) == 0
            _wait_until(lambda: all(not r1d.SingleInstance.alive(m.read_json(record)["pid"])
                                   for record in (paths.repo / "events").glob("start.*.json")), timeout=3)
            assert not (paths.runtime / "service.lock").exists()
            assert m.read_json(paths.output / "service_state.json")["service_status"] == "STOPPED"
        launches = [m.read_json(path) for path in (paths.repo / "events").glob("launch.*.json")]
        assert len(launches) >= 2 * len(workers) + 1
        record_property("controlled_launcher_pids", json.dumps(sorted({item["pid"] for item in launches})))
        record_property("controlled_actual_worker_pids", json.dumps(sorted({m.read_json(path)["pid"]
            for path in (paths.repo / "events").glob("start.*.json")})))
        _wait_until(lambda: all(not r1d.SingleInstance.alive(item["pid"]) for item in launches), timeout=5)
        assert all(Path(item["executed_script"]).is_relative_to(paths.repo) and
                   Path(item["executed_script"]).read_text(encoding="utf-8") == _CONTROLLED_SERVICE for item in launches)
        assert all(Path(item["requested_script"]).is_relative_to(paths.repo) for item in launches)
        assert m.read_json(paths.r1d_output / "switch_state.json")["mode"] == "SHADOW"
    finally:
        # This exact temporary repo owns every flag/PID below. Even assertion
        # failures ask all controlled workers to exit; no machine-wide kills.
        for relative in workers.values():
            target = paths.repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch()
        paths.output.mkdir(parents=True, exist_ok=True)
        (paths.output / "service.stop").touch()
        for process in processes:
            if process.poll() is None:
                process.wait(timeout=15)
        _wait_until(lambda: all(not r1d.SingleInstance.alive(m.read_json(record)["pid"])
                               for record in (paths.repo / "events").glob("start.*.json")), timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows replacement contention contract")
@pytest.mark.parametrize("persistent", (False, True))
def test_atomic_json_bounds_windows_replace_denial_and_preserves_target(tmp_path, monkeypatch, persistent):
    target = tmp_path / "state.json"
    original = b'{"original": true}\n'
    target.write_bytes(original)
    replace = m.os.replace
    denied = PermissionError(13, "SYNTHETIC_WINDOWS_REPLACE_DENIAL", str(target))
    denied.winerror = 5
    calls, sleeps = [], []
    def replace_with_contention(source, destination):
        calls.append((source, destination))
        assert target.read_bytes() == original
        if persistent or len(calls) == 1:
            raise denied
        return replace(source, destination)
    monkeypatch.setattr(m.os, "replace", replace_with_contention)
    monkeypatch.setattr(m.time, "sleep", sleeps.append)
    if persistent:
        with pytest.raises(PermissionError) as caught:
            m.atomic_json(target, {"replacement": True})
        assert caught.value is denied
        assert len(calls) == 6 and sum(sleeps) == pytest.approx(.775)
        assert target.read_bytes() == original
    else:
        m.atomic_json(target, {"replacement": True})
        assert len(calls) == 2 and sleeps == [.025]
        assert m.read_json(target) == {"replacement": True}
    assert len({str(source) for source, _ in calls}) == 1
    assert all(destination == target for _, destination in calls)
    assert list(tmp_path.iterdir()) == [target]


def test_service_manager_exception_fails_closed_and_restart_reuses_live_workers(tmp_path, record_property):
    paths, workers, bootstrap = _controlled_service_repo(tmp_path)
    r1d = m.load_module(paths.r1d_script, "manager_failure_parent_r1d")
    processes = []
    command = [sys.executable, "-B", str(bootstrap), "service", "--repo-root", str(paths.repo)]
    try:
        failed = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        processes.append(failed)
        _wait_until(lambda: len(list((paths.repo / "events").glob("start.*.json"))) == len(workers))
        _wait_until(lambda: m.read_json(paths.output / "service_state.json", {}).get("service_status") == "RUNNING")
        original_records = set((paths.repo / "events").glob("start.*.json"))
        original_launches = set((paths.repo / "events").glob("launch.*.json"))
        actual_pids = {m.read_json(path)["pid"] for path in original_records}
        launcher_pids = {m.read_json(path)["pid"] for path in original_launches}
        manager_pid = m.read_json(paths.output / "service_state.json")["pid"]
        assert len(original_launches) == len(workers)
        # Trigger only after actual Service and every synthetic worker is ready.
        (paths.repo / "service_fail_after_start.flag").touch()
        assert failed.wait(timeout=15) == 2
        failed_state = m.read_json(paths.output / "service_state.json")
        assert failed_state["service_status"] == "FAILED"
        assert "SYNTHETIC_SERVICE_MANAGER_FAILURE" in failed_state["detail"]
        assert m.read_json(paths.r1d_output / "switch_state.json")["mode"] == "OFF"
        assert m.read_json(paths.r1d_output / "emergency_stop.json")["active"] is True
        assert not (paths.runtime / "service.lock").exists()
        assert not r1d.SingleInstance.alive(manager_pid)
        assert all(r1d.SingleInstance.alive(pid) for pid in actual_pids | launcher_pids)

        restarted = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        processes.append(restarted)
        def restarted_through_management_cycle():
            snapshot = m.read_json(paths.output / "service_state.json", {})
            if restarted.poll() is not None or (snapshot.get("service_status") == "FAILED" and snapshot.get("pid") != manager_pid):
                pytest.fail(f"Restarted manager failed: rc={restarted.poll()}, state={snapshot}, "
                    f"errors={(paths.output / 'error_ledger.csv').read_text(encoding='utf-8')}")
            event = m.read_json(paths.repo / "events" / f"manager.{snapshot.get('pid')}.json", {})
            # Initial RUNNING plus two actual loop writes crosses the service's
            # existing timed management cycle; no arbitrary test sleep.
            return (snapshot.get("service_status") == "RUNNING" and snapshot.get("pid") != manager_pid
                    and event.get("running_count", 0) >= 3)
        _wait_until(restarted_through_management_cycle)
        assert restarted.poll() is None
        assert (paths.runtime / "service.lock").exists(), (
            restarted.poll(), m.read_json(paths.output / "service_state.json"),
            (paths.output / "error_ledger.csv").read_text(encoding="utf-8"))
        lock_pid = int((paths.runtime / "service.lock").read_text())
        assert lock_pid == m.read_json(paths.output / "service_state.json")["pid"]
        assert r1d.SingleInstance.alive(lock_pid)
        assert set((paths.repo / "events").glob("start.*.json")) == original_records
        assert set((paths.repo / "events").glob("launch.*.json")) == original_launches
        assert all(r1d.SingleInstance.alive(pid) for pid in actual_pids | launcher_pids)
        assert m.read_json(paths.r1d_output / "switch_state.json")["mode"] == "SHADOW"
        stopped = _powershell(tmp_path, r'''
param($RepoRoot)
& (Join-Path $RepoRoot 'scripts/v22/stop_v22_047_r1e_service.ps1') -RepoRoot $RepoRoot
exit $LASTEXITCODE
''', paths.repo)
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        assert restarted.wait(timeout=15) == 0
        _wait_until(lambda: all(not r1d.SingleInstance.alive(pid) for pid in actual_pids | launcher_pids), timeout=5)
        assert not (paths.runtime / "service.lock").exists()
        assert m.read_json(paths.output / "service_state.json")["service_status"] == "STOPPED"
        record_property("reused_worker_launchers", json.dumps(sorted(launcher_pids)))
        record_property("reused_actual_workers", json.dumps(sorted(actual_pids)))
        record_property("failed_manager_actual_pid", manager_pid)
    finally:
        for relative in workers.values():
            target = paths.repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch()
        paths.output.mkdir(parents=True, exist_ok=True)
        (paths.output / "service.stop").touch()
        for process in processes:
            if process.poll() is None:
                process.wait(timeout=15)
        records = list((paths.repo / "events").glob("start.*.json")) + list((paths.repo / "events").glob("launch.*.json"))
        _wait_until(lambda: all(not r1d.SingleInstance.alive(m.read_json(path)["pid"]) for path in records), timeout=5)
