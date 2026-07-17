from __future__ import annotations
import ast
import importlib.util
import json
import os
import sys
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
