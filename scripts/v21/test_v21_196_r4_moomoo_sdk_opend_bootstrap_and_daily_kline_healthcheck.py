import importlib.util
import json
import subprocess
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_196_r4_moomoo_sdk_opend_bootstrap_and_daily_kline_healthcheck.py"
RUNNER = ROOT / "scripts/v21/run_v21_196_r4_moomoo_sdk_opend_bootstrap_and_daily_kline_healthcheck.ps1"


def load_module():
    spec = importlib.util.spec_from_file_location("v21_196_r4a", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_package_name_is_moomoo_api_and_import_module_is_moomoo():
    module = load_module()
    assert module.PACKAGE_INSTALL_NAME == "moomoo-api"
    assert module.IMPORT_MODULE_NAME == "moomoo"
    text = SCRIPT.read_text(encoding="utf-8")
    assert "from moomoo import *" in text


def test_python_314_rejected_for_dedicated_moomoo_env_by_default():
    module = load_module()
    assert module.version_eligible("3.14.4") is False
    assert module.version_eligible("3.14.4", force=True) is True


def test_python_311_312_discovery_works():
    module = load_module()

    def fake_runner(args, timeout):
        label = " ".join(args[:2])
        if args[0] == "py" and args[1] == "-3.12":
            payload = {"executable": "C:/Python312/python.exe", "version": "3.12.9"}
            return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")
        if args[0] == "py" and args[1] == "-3.11":
            payload = {"executable": "C:/Python311/python.exe", "version": "3.11.11"}
            return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")
        return subprocess.CompletedProcess(args, 1, "", f"{label} unavailable")

    rows = module.discover_python_interpreters(fake_runner)
    selected = module.select_python_for_moomoo(rows)
    assert any(row["python_version"] == "3.11.11" and row["eligible_for_moomoo_sdk"] for row in rows)
    assert selected["python_version"] == "3.12.9"


def test_env_creation_requires_explicit_flag(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    calls = []

    def fake_runner(args, timeout):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    selected = {"python_executable": "C:/Python312/python.exe", "python_version": "3.12.9"}
    audit = module.create_dedicated_env(selected, False, fake_runner)
    assert audit["env_exists_before"] is False
    assert audit["env_created"] is False
    assert "CREATE_MOOMOO_ENV" in audit["guard_note"]
    assert not calls


def test_install_command_uses_moomoo_api_not_moomoo(tmp_path):
    module = load_module()
    calls = []
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")

    def fake_runner(args, timeout):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "ok", "")

    audit = module.install_moomoo_api(python, True, fake_runner)
    assert audit["install_attempted"] is True
    assert audit["install_succeeded"] is True
    assert calls[0][-1] == "moomoo-api"
    assert "moomoo-api" in audit["install_command"]
    assert "moomoo" not in calls[0][-1].replace("moomoo-api", "")


def test_no_trade_context_usage():
    text = SCRIPT.read_text(encoding="utf-8")
    banned = [
        "OpenSecTradeContext",
        "OpenFutureTradeContext",
        "unlock_trade",
        "place_order",
        "modify_order",
        "cancel_order",
    ]
    for item in banned:
        assert item not in text
    assert "OpenQuoteContext" in text


def test_opend_unavailable_classifies_as_wait_opend_start():
    module = load_module()
    status, decision = module.decide_status(
        py_available=True,
        env_ready=True,
        create_requested=True,
        install_attempted=True,
        install_succeeded=True,
        import_succeeded=True,
        tcp_probe_success=False,
        healthcheck_attempted=False,
        opend_success=False,
        hc_success=False,
    )
    assert status == "PARTIAL_PASS_V21_196_R4A_WAIT_OPEND_START"
    assert decision == "START_MOOMOO_OPEND_AND_RERUN_R4A"


def test_tcp_probe_failure_skips_long_healthcheck(monkeypatch, tmp_path):
    module = load_module()
    monkeypatch.setattr(module, "OUT", tmp_path / "out")
    monkeypatch.setattr(module, "main_python_audit", lambda: {
        "main_project_python": "python",
        "main_project_python_version": "3.14.4",
        "main_project_python_rejected_for_moomoo_sdk": True,
    })
    monkeypatch.setattr(module, "discover_python_interpreters", lambda: [{"eligible_for_moomoo_sdk": True, "python_version": "3.12.9"}])
    monkeypatch.setattr(module, "select_python_for_moomoo", lambda rows: rows[0])
    dedicated_python = tmp_path / "python.exe"
    dedicated_python.write_text("", encoding="utf-8")
    monkeypatch.setattr(module, "create_dedicated_env", lambda selected, create_requested: {
        "create_env_requested": False,
        "env_created": False,
        "dedicated_env_path": ".venv_moomoo_py312",
        "dedicated_python_executable": str(dedicated_python),
        "dedicated_python_version": "3.12.9",
    })
    monkeypatch.setattr(module, "install_moomoo_api", lambda dedicated, env_ready: {
        "install_attempted": False,
        "install_succeeded": False,
    })
    monkeypatch.setattr(module, "verify_moomoo_import", lambda dedicated, env_ready: {
        "moomoo_api_package_installed": True,
        "moomoo_import_succeeded": True,
    })
    monkeypatch.setattr(module, "tcp_probe", lambda host, port, timeout_seconds=3.0: {
        "tcp_probe_attempted": True,
        "tcp_probe_success": False,
        "tcp_probe_host": host,
        "tcp_probe_port": port,
        "tcp_probe_timeout_seconds": timeout_seconds,
        "tcp_probe_error": "connection refused",
    })

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("long healthcheck should be skipped after TCP probe failure")

    monkeypatch.setattr(module, "run_healthcheck_in_dedicated_env", should_not_run)
    summary = module.run()
    assert summary["final_status"] == "PARTIAL_PASS_V21_196_R4A_WAIT_OPEND_START"
    assert summary["tcp_probe_attempted"] is True
    assert summary["tcp_probe_success"] is False
    assert summary["healthcheck_attempted"] is False


def test_tcp_probe_success_forces_healthcheck_attempted(tmp_path):
    module = load_module()
    dedicated = tmp_path / "python.exe"
    dedicated.write_text("", encoding="utf-8")
    main = {
        "main_project_python": "python",
        "main_project_python_version": "3.14.4",
        "main_project_python_rejected_for_moomoo_sdk": True,
    }
    env = {
        "create_env_requested": False,
        "env_created": False,
        "dedicated_env_path": ".venv_moomoo_py312",
        "dedicated_python_executable": str(dedicated),
        "dedicated_python_version": "3.12.9",
    }
    install = {"install_attempted": False, "install_succeeded": False}
    imp = {"moomoo_api_package_installed": True, "moomoo_import_succeeded": True}
    conn = {
        "moomoo_opend_host": "127.0.0.1",
        "moomoo_opend_port": 11111,
        "moomoo_opend_connection_attempted": True,
        "moomoo_opend_connection_success": False,
        "tcp_probe": {"tcp_probe_attempted": True, "tcp_probe_success": True, "tcp_probe_error": ""},
        "healthcheck_subprocess": {"healthcheck_attempted": True, "healthcheck_timeout": False, "healthcheck_timeout_seconds": 20},
    }
    summary = module.build_summary(main, [{"eligible_for_moomoo_sdk": True}], env, install, imp, conn, pd.DataFrame(), [], tmp_path / "instructions.txt")
    assert summary["tcp_probe_success"] is True
    assert summary["healthcheck_attempted"] is True


def test_tcp_success_without_healthcheck_attempt_is_inconsistent_failure(tmp_path):
    module = load_module()
    dedicated = tmp_path / "python.exe"
    dedicated.write_text("", encoding="utf-8")
    main = {
        "main_project_python": "python",
        "main_project_python_version": "3.14.4",
        "main_project_python_rejected_for_moomoo_sdk": True,
    }
    env = {
        "create_env_requested": False,
        "env_created": False,
        "dedicated_env_path": ".venv_moomoo_py312",
        "dedicated_python_executable": str(dedicated),
        "dedicated_python_version": "3.12.9",
    }
    install = {"install_attempted": False, "install_succeeded": False}
    imp = {"moomoo_api_package_installed": True, "moomoo_import_succeeded": True}
    conn = {
        "moomoo_opend_host": "127.0.0.1",
        "moomoo_opend_port": 11111,
        "moomoo_opend_connection_attempted": False,
        "moomoo_opend_connection_success": False,
        "tcp_probe": {"tcp_probe_attempted": True, "tcp_probe_success": True, "tcp_probe_error": ""},
        "healthcheck_subprocess": {"healthcheck_timeout": False, "healthcheck_timeout_seconds": 20},
    }
    summary = module.build_summary(main, [{"eligible_for_moomoo_sdk": True}], env, install, imp, conn, pd.DataFrame(), [], tmp_path / "instructions.txt")
    assert summary["final_status"] == "FAIL_V21_196_R4C_INCONSISTENT_TCP_HEALTHCHECK_STATE"
    assert summary["final_decision"] == "REPAIR_R4_HEALTHCHECK_BRANCHING"


def test_timeout_expired_is_caught_and_classified_safely(tmp_path):
    module = load_module()
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")

    def fake_runner(args, timeout):
        raise subprocess.TimeoutExpired(args, timeout, output="partial out", stderr="partial err")

    conn, raw, rows, diag = module.run_healthcheck_in_dedicated_env(
        python,
        True,
        "127.0.0.1",
        11111,
        timeout_seconds=7,
        command_runner=fake_runner,
    )
    assert conn["moomoo_opend_connection_success"] is False
    assert conn["moomoo_opend_connection_attempted"] is True
    assert raw.empty
    assert rows == []
    assert diag["healthcheck_timeout"] is True
    assert diag["healthcheck_timeout_seconds"] == 7


def test_timeout_summary_fields_written_and_sdk_fields_preserved(tmp_path):
    module = load_module()
    dedicated = tmp_path / "python.exe"
    dedicated.write_text("", encoding="utf-8")
    main = {
        "main_project_python": "python",
        "main_project_python_version": "3.14.4",
        "main_project_python_rejected_for_moomoo_sdk": True,
    }
    env = {
        "create_env_requested": False,
        "env_created": False,
        "dedicated_env_path": ".venv_moomoo_py312",
        "dedicated_python_executable": str(dedicated),
        "dedicated_python_version": "3.12.9",
    }
    install = {"install_attempted": False, "install_succeeded": False}
    imp = {"moomoo_api_package_installed": True, "moomoo_import_succeeded": True}
    conn = {
        "moomoo_opend_host": "127.0.0.1",
        "moomoo_opend_port": 11111,
        "moomoo_opend_connection_attempted": True,
        "moomoo_opend_connection_success": False,
        "tcp_probe": {"tcp_probe_attempted": True, "tcp_probe_success": True, "tcp_probe_error": ""},
        "healthcheck_subprocess": {
            "returncode": None,
            "stdout_tail": "partial out",
            "stderr_tail": "partial err",
            "healthcheck_attempted": True,
            "healthcheck_timeout": True,
            "healthcheck_timeout_seconds": 7,
        },
    }
    summary = module.build_summary(main, [{"eligible_for_moomoo_sdk": True}], env, install, imp, conn, pd.DataFrame(), [], tmp_path / "instructions.txt")
    assert summary["final_status"] == "PARTIAL_PASS_V21_196_R4B_OPEND_HEALTHCHECK_TIMEOUT"
    assert summary["final_decision"] == "CHECK_OPEND_RUNNING_PORT_FIREWALL_AND_RERUN"
    assert summary["dedicated_env_path"] == ".venv_moomoo_py312"
    assert summary["dedicated_python_version"] == "3.12.9"
    assert summary["moomoo_api_package_installed"] is True
    assert summary["moomoo_import_succeeded"] is True
    assert summary["healthcheck_timeout"] is True
    assert summary["healthcheck_timeout_seconds"] == 7
    assert summary["healthcheck_subprocess_stdout_tail"] == "partial out"
    assert summary["healthcheck_subprocess_stderr_tail"] == "partial err"
    assert summary["r3_ready_to_rerun"] is False


def test_tcp_success_quote_context_failure_classifies(tmp_path):
    module = load_module()
    dedicated = tmp_path / "python.exe"
    dedicated.write_text("", encoding="utf-8")
    main = {"main_project_python": "python", "main_project_python_version": "3.14.4", "main_project_python_rejected_for_moomoo_sdk": True}
    env = {"create_env_requested": False, "env_created": False, "dedicated_env_path": ".venv_moomoo_py312", "dedicated_python_executable": str(dedicated), "dedicated_python_version": "3.12.9"}
    install = {"install_attempted": False, "install_succeeded": False}
    imp = {"moomoo_api_package_installed": True, "moomoo_import_succeeded": True}
    conn = {
        "moomoo_opend_host": "127.0.0.1",
        "moomoo_opend_port": 11111,
        "moomoo_opend_connection_attempted": True,
        "moomoo_opend_connection_success": False,
        "tcp_probe": {"tcp_probe_attempted": True, "tcp_probe_success": True, "tcp_probe_error": ""},
        "healthcheck_subprocess": {"healthcheck_attempted": True, "healthcheck_timeout": False, "healthcheck_timeout_seconds": 20},
    }
    summary = module.build_summary(main, [{"eligible_for_moomoo_sdk": True}], env, install, imp, conn, pd.DataFrame(), [], tmp_path / "instructions.txt")
    assert summary["final_status"] == "PARTIAL_PASS_V21_196_R4C_OPEND_TCP_OK_QUOTE_CONTEXT_FAILED"
    assert summary["final_decision"] == "CHECK_OPEND_LOGIN_API_PERMISSION_AND_RERUN"


def test_tcp_success_connected_no_kline_rows_classifies(tmp_path):
    module = load_module()
    dedicated = tmp_path / "python.exe"
    dedicated.write_text("", encoding="utf-8")
    main = {"main_project_python": "python", "main_project_python_version": "3.14.4", "main_project_python_rejected_for_moomoo_sdk": True}
    env = {"create_env_requested": False, "env_created": False, "dedicated_env_path": ".venv_moomoo_py312", "dedicated_python_executable": str(dedicated), "dedicated_python_version": "3.12.9"}
    install = {"install_attempted": False, "install_succeeded": False}
    imp = {"moomoo_api_package_installed": True, "moomoo_import_succeeded": True}
    conn = {
        "moomoo_opend_host": "127.0.0.1",
        "moomoo_opend_port": 11111,
        "moomoo_opend_connection_attempted": True,
        "moomoo_opend_connection_success": True,
        "tcp_probe": {"tcp_probe_attempted": True, "tcp_probe_success": True, "tcp_probe_error": ""},
        "healthcheck_subprocess": {"healthcheck_attempted": True, "healthcheck_timeout": False, "healthcheck_timeout_seconds": 20},
    }
    summary = module.build_summary(main, [{"eligible_for_moomoo_sdk": True}], env, install, imp, conn, pd.DataFrame(), [], tmp_path / "instructions.txt")
    assert summary["final_status"] == "PARTIAL_PASS_V21_196_R4C_OPEND_CONNECTED_KLINE_NO_DATA"
    assert summary["final_decision"] == "CHECK_MOOMOO_MARKET_DATA_PERMISSION_OR_DATE_RANGE"


def test_healthcheck_rows_normalize_correctly():
    module = load_module()
    raw = pd.DataFrame([
        {"date": "2026-06-29", "valid_completed_daily_bar": True},
        {"date": "2026-06-30", "valid_completed_daily_bar": True},
    ])
    assert module.target_date_coverage(raw) == {"2026-06-29": True, "2026-06-30": True}
    rows = [{"moomoo_code": code, "status": "SUCCESS"} for code in module.HEALTHCHECK_CODES]
    success, success_count, failed_count = module.healthcheck_success(rows)
    assert success is True
    assert success_count == 4
    assert failed_count == 0


def test_healthcheck_payload_parser_ignores_sdk_log_lines_after_json():
    module = load_module()
    payload = {"connection": {"moomoo_opend_connection_success": True}, "raw_rows": [], "summary_rows": []}
    stdout = "sdk banner\n" + json.dumps(payload) + "\n2026-07-01 log disconnect line\n"
    parsed = module.parse_healthcheck_payload(stdout)
    assert parsed["connection"]["moomoo_opend_connection_success"] is True


def test_r3_ready_to_rerun_only_after_sdk_opend_and_healthcheck_success(tmp_path):
    module = load_module()
    main = {
        "main_project_python": "python",
        "main_project_python_version": "3.14.4",
        "main_project_python_rejected_for_moomoo_sdk": True,
    }
    discovery = [{"eligible_for_moomoo_sdk": True}]
    env = {
        "create_env_requested": True,
        "env_created": True,
        "dedicated_env_path": ".venv_moomoo_py312",
        "dedicated_python_executable": str(tmp_path / "python.exe"),
        "dedicated_python_version": "3.12.9",
    }
    Path(env["dedicated_python_executable"]).write_text("", encoding="utf-8")
    install = {"install_attempted": True, "install_succeeded": True}
    imp = {"moomoo_api_package_installed": True, "moomoo_import_succeeded": True}
    conn = {
        "moomoo_opend_host": "127.0.0.1",
        "moomoo_opend_port": 11111,
        "moomoo_opend_connection_attempted": True,
        "moomoo_opend_connection_success": True,
        "tcp_probe": {"tcp_probe_attempted": True, "tcp_probe_success": True, "tcp_probe_error": ""},
        "healthcheck_subprocess": {"healthcheck_attempted": True, "healthcheck_timeout": False, "healthcheck_timeout_seconds": 20},
    }
    raw = pd.DataFrame([
        {"date": date, "valid_completed_daily_bar": True}
        for date in module.TARGET_DATES
        for _code in module.HEALTHCHECK_CODES
    ])
    rows = [{"moomoo_code": code, "status": "SUCCESS"} for code in module.HEALTHCHECK_CODES]
    summary = module.build_summary(main, discovery, env, install, imp, conn, raw, rows, tmp_path / "instructions.txt")
    assert summary["r3_ready_to_rerun"] is True
    conn["moomoo_opend_connection_success"] = False
    summary = module.build_summary(main, discovery, env, install, imp, conn, raw, rows, tmp_path / "instructions.txt")
    assert summary["r3_ready_to_rerun"] is False


def test_safety_flags_remain_false(tmp_path):
    module = load_module()
    main = {
        "main_project_python": "python",
        "main_project_python_version": "3.14.4",
        "main_project_python_rejected_for_moomoo_sdk": True,
    }
    env = {
        "create_env_requested": False,
        "env_created": False,
        "dedicated_env_path": ".venv_moomoo_py311",
        "dedicated_python_executable": str(tmp_path / "missing.exe"),
        "dedicated_python_version": "",
    }
    install = {"install_attempted": False, "install_succeeded": False}
    imp = {"moomoo_api_package_installed": False, "moomoo_import_succeeded": False}
    conn = {
        "moomoo_opend_host": "127.0.0.1",
        "moomoo_opend_port": 11111,
        "moomoo_opend_connection_attempted": False,
        "moomoo_opend_connection_success": False,
    }
    summary = module.build_summary(main, [], env, install, imp, conn, pd.DataFrame(), [], tmp_path / "instructions.txt")
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["protected_outputs_modified"] is False
    assert summary["research_only"] is True
    assert SCRIPT.is_file()
    assert RUNNER.is_file()
