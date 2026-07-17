#!/usr/bin/env python
"""V21.196 R4A Moomoo API package and dedicated Python env repair."""

from __future__ import annotations

import csv
import json
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.196_R4A_MOOMOO_API_PACKAGE_NAME_AND_PY311_ENV_REPAIR"
OUT = ROOT / "outputs/v21/V21.196_R4A_MOOMOO_API_PACKAGE_NAME_AND_PY311_ENV_REPAIR"
CREATE_ENV = "V21_196_R4A_CREATE_MOOMOO_ENV"
FORCE_MAIN_ENV = "V21_196_R4A_FORCE_MAIN_PYTHON_FOR_MOOMOO"
HOST_ENV = "MOOMOO_OPEND_HOST"
PORT_ENV = "MOOMOO_OPEND_PORT"
HEALTHCHECK_TIMEOUT_ENV = "V21_196_R4B_HEALTHCHECK_TIMEOUT_SECONDS"
PACKAGE_INSTALL_NAME = "moomoo-api"
IMPORT_MODULE_NAME = "moomoo"
TARGET_DATES = ["2026-06-29", "2026-06-30"]
HEALTHCHECK_CODES = ["US.QQQ", "US.AAPL", "US.MU", "US.AMAT"]
RAW_FIELDS = [
    "symbol",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source_provider",
    "moomoo_code",
    "autype",
    "valid_completed_daily_bar",
    "validation_error",
]
SUMMARY_FIELDS = [
    "moomoo_code",
    "symbol",
    "autype",
    "returned_row_count",
    "valid_row_count",
    "target_dates_covered",
    "status",
    "error",
]
DISCOVERY_FIELDS = [
    "candidate",
    "command",
    "available",
    "python_executable",
    "python_version",
    "major",
    "minor",
    "eligible_for_moomoo_sdk",
    "error",
]


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(list(rows))


def subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    runtime_home = OUT / "moomoo_sdk_runtime_home"
    runtime_home.mkdir(parents=True, exist_ok=True)
    env["APPDATA"] = str(runtime_home)
    env["appdata"] = str(runtime_home)
    env["HOME"] = str(runtime_home)
    return env


def run_command(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False, timeout=timeout, env=subprocess_env())


def env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().upper() == "TRUE"


def parse_port(value: str | None) -> int:
    raw = value or "18441"
    try:
        port = int(raw)
    except ValueError as exc:
        raise ValueError(f"{PORT_ENV} must be an integer, got {raw!r}") from exc
    if port <= 0 or port > 65535:
        raise ValueError(f"{PORT_ENV} must be between 1 and 65535, got {port}")
    return port


def parse_healthcheck_timeout(value: str | None) -> int:
    raw = value or "20"
    try:
        timeout = int(raw)
    except ValueError:
        return 20
    return max(1, min(timeout, 300))


def version_tuple(version: str) -> tuple[int, int]:
    parts = str(version).split(".")
    try:
        return int(parts[0]), int(parts[1])
    except Exception:
        return 0, 0


def version_eligible(version: str, force: bool = False) -> bool:
    major, minor = version_tuple(version)
    if force:
        return major == 3 and minor >= 11
    return major == 3 and minor in {11, 12}


def main_python_audit() -> dict[str, Any]:
    version = platform.python_version()
    rejected = version_tuple(version) >= (3, 14) and not env_truthy(FORCE_MAIN_ENV)
    return {
        "main_project_python": sys.executable,
        "main_project_python_version": version,
        "main_project_python_rejected_for_moomoo_sdk": rejected,
        "force_main_project_python": env_truthy(FORCE_MAIN_ENV),
    }


def python_query_code() -> str:
    return (
        "import json,platform,sys;"
        "print(json.dumps({'executable':sys.executable,'version':platform.python_version()}))"
    )


def discover_python_interpreters(
    command_runner: Callable[[list[str], int], subprocess.CompletedProcess[str]] = run_command,
) -> list[dict[str, Any]]:
    candidates = [
        ("py -3.12", ["py", "-3.12", "-c", python_query_code()]),
        ("py -3.11", ["py", "-3.11", "-c", python_query_code()]),
        ("python3.12", ["python3.12", "-c", python_query_code()]),
        ("python3.11", ["python3.11", "-c", python_query_code()]),
        ("python", ["python", "-c", python_query_code()]),
    ]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for label, command in candidates:
        row = {
            "candidate": label,
            "command": " ".join(command),
            "available": False,
            "python_executable": "",
            "python_version": "",
            "major": "",
            "minor": "",
            "eligible_for_moomoo_sdk": False,
            "error": "",
        }
        try:
            proc = command_runner(command, 30)
            if proc.returncode != 0:
                row["error"] = (proc.stderr or proc.stdout or f"returncode={proc.returncode}")[-1000:]
            else:
                data = json.loads((proc.stdout or "").strip().splitlines()[-1])
                executable = str(data.get("executable", ""))
                version = str(data.get("version", ""))
                major, minor = version_tuple(version)
                row.update({
                    "available": True,
                    "python_executable": executable,
                    "python_version": version,
                    "major": major,
                    "minor": minor,
                    "eligible_for_moomoo_sdk": version_eligible(version),
                })
        except Exception as exc:
            row["error"] = str(exc)
        key = f"{row['python_executable']}|{row['python_version']}"
        if row["available"] and key in seen:
            continue
        if row["available"]:
            seen.add(key)
        rows.append(row)
    return rows


def select_python_for_moomoo(discovery_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    eligible = [row for row in discovery_rows if row.get("available") and row.get("eligible_for_moomoo_sdk")]
    for minor in [12, 11]:
        for row in eligible:
            if int(row.get("minor") or 0) == minor:
                return row
    return eligible[0] if eligible else None


def dedicated_env_path_for_version(version: str) -> Path:
    major, minor = version_tuple(version)
    if major == 3 and minor == 12:
        return ROOT / ".venv_moomoo_py312"
    return ROOT / ".venv_moomoo_py311"


def dedicated_python_for_env(env_path: Path) -> Path:
    return env_path / "Scripts/python.exe" if os.name == "nt" else env_path / "bin/python"


def existing_dedicated_env() -> tuple[Path | None, Path | None, str]:
    for env_path in [ROOT / ".venv_moomoo_py312", ROOT / ".venv_moomoo_py311"]:
        python_path = dedicated_python_for_env(env_path)
        if python_path.is_file():
            return env_path, python_path, query_python_version(python_path)
    return None, None, ""


def query_python_version(python_executable: Path | str) -> str:
    proc = run_command([str(python_executable), "-c", "import platform; print(platform.python_version())"], 30)
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def create_dedicated_env(
    selected_python: dict[str, Any] | None,
    create_requested: bool,
    command_runner: Callable[[list[str], int], subprocess.CompletedProcess[str]] = run_command,
) -> dict[str, Any]:
    existing_env, existing_python, existing_version = existing_dedicated_env()
    selected_version = str(selected_python.get("python_version", "")) if selected_python else ""
    env_path = existing_env or (dedicated_env_path_for_version(selected_version) if selected_python else ROOT / ".venv_moomoo_py311")
    dedicated_python = existing_python or dedicated_python_for_env(env_path)
    exists_before = dedicated_python.is_file()
    audit = {
        "create_env_requested": create_requested,
        "env_exists_before": exists_before,
        "env_created": False,
        "dedicated_env_path": rel(env_path),
        "dedicated_python_executable": str(dedicated_python),
        "dedicated_python_version": existing_version if existing_version else (query_python_version(dedicated_python) if exists_before else ""),
        "create_command": "",
        "create_returncode": None,
        "create_stdout_tail": "",
        "create_stderr_tail": "",
        "pip_upgrade_attempted": False,
        "pip_upgrade_succeeded": False,
        "pip_upgrade_stdout_tail": "",
        "pip_upgrade_stderr_tail": "",
        "guard_note": "",
    }
    if exists_before:
        return audit
    if not create_requested:
        audit["guard_note"] = f"Dedicated env missing. Set {CREATE_ENV}=TRUE to create it."
        return audit
    if not selected_python:
        audit["guard_note"] = "No Python 3.11/3.12 interpreter available for dedicated env creation."
        return audit
    command = [str(selected_python["python_executable"]), "-m", "venv", str(env_path)]
    audit["create_command"] = " ".join(command)
    proc = command_runner(command, 300)
    audit["create_returncode"] = proc.returncode
    audit["create_stdout_tail"] = (proc.stdout or "")[-4000:]
    audit["create_stderr_tail"] = (proc.stderr or "")[-4000:]
    audit["env_created"] = proc.returncode == 0 and dedicated_python.is_file()
    audit["dedicated_python_version"] = query_python_version(dedicated_python) if dedicated_python.is_file() else ""
    if dedicated_python.is_file():
        pip_proc = command_runner([str(dedicated_python), "-m", "pip", "install", "--upgrade", "pip"], 300)
        audit["pip_upgrade_attempted"] = True
        audit["pip_upgrade_succeeded"] = pip_proc.returncode == 0
        audit["pip_upgrade_stdout_tail"] = (pip_proc.stdout or "")[-4000:]
        audit["pip_upgrade_stderr_tail"] = (pip_proc.stderr or "")[-4000:]
    return audit


def install_moomoo_api(
    dedicated_python: Path,
    env_ready: bool,
    command_runner: Callable[[list[str], int], subprocess.CompletedProcess[str]] = run_command,
) -> dict[str, Any]:
    audit = {
        "package_install_name": PACKAGE_INSTALL_NAME,
        "import_module_name": IMPORT_MODULE_NAME,
        "install_attempted": False,
        "install_succeeded": False,
        "install_command": [str(dedicated_python), "-m", "pip", "install", PACKAGE_INSTALL_NAME],
        "returncode": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "guard_note": "",
    }
    if not env_ready:
        audit["guard_note"] = "Install skipped because dedicated Moomoo env is not ready."
        return audit
    audit["install_attempted"] = True
    proc = command_runner([str(dedicated_python), "-m", "pip", "install", PACKAGE_INSTALL_NAME], 600)
    audit["returncode"] = proc.returncode
    audit["stdout_tail"] = (proc.stdout or "")[-4000:]
    audit["stderr_tail"] = (proc.stderr or "")[-4000:]
    audit["install_succeeded"] = proc.returncode == 0
    return audit


def verify_moomoo_import(
    dedicated_python: Path,
    env_ready: bool,
    command_runner: Callable[[list[str], int], subprocess.CompletedProcess[str]] = run_command,
) -> dict[str, Any]:
    audit = {
        "package_install_name": PACKAGE_INSTALL_NAME,
        "import_module_name": IMPORT_MODULE_NAME,
        "moomoo_api_package_installed": False,
        "moomoo_import_succeeded": False,
        "star_import_verified": False,
        "returncode": None,
        "stdout_tail": "",
        "stderr_tail": "",
    }
    if not env_ready:
        return audit
    code = (
        "from moomoo import *\n"
        "import importlib.util\n"
        "print('MOOMOO_STAR_IMPORT_OK')\n"
        "print(importlib.util.find_spec('moomoo').origin)\n"
    )
    proc = command_runner([str(dedicated_python), "-c", code], 60)
    audit["returncode"] = proc.returncode
    audit["stdout_tail"] = (proc.stdout or "")[-4000:]
    audit["stderr_tail"] = (proc.stderr or "")[-4000:]
    audit["moomoo_import_succeeded"] = proc.returncode == 0
    audit["star_import_verified"] = proc.returncode == 0 and "MOOMOO_STAR_IMPORT_OK" in (proc.stdout or "")
    audit["moomoo_api_package_installed"] = audit["moomoo_import_succeeded"]
    return audit


def tcp_probe(host: str, port: int, timeout_seconds: float = 3.0) -> dict[str, Any]:
    audit = {
        "tcp_probe_attempted": True,
        "tcp_probe_success": False,
        "tcp_probe_host": host,
        "tcp_probe_port": port,
        "tcp_probe_timeout_seconds": timeout_seconds,
        "tcp_probe_error": "",
    }
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            audit["tcp_probe_success"] = True
    except Exception as exc:
        audit["tcp_probe_error"] = str(exc)
    return audit


def healthcheck_subprocess_code() -> str:
    return r'''
import json
import sys
import pandas as pd
from moomoo import *

host = sys.argv[1]
port = int(sys.argv[2])
target_dates = ["2026-06-29", "2026-06-30"]
codes = ["US.QQQ", "US.AAPL", "US.MU", "US.AMAT"]

raw_rows = []
summary_rows = []
connection = {
    "moomoo_opend_host": host,
    "moomoo_opend_port": port,
    "moomoo_opend_connection_attempted": True,
    "moomoo_opend_connection_success": False,
    "quote_context_only": True,
    "error": "",
}

def symbol_from_code(code):
    return code[3:] if code.upper().startswith("US.") else code

def validate(row):
    errors = []
    if row.get("date") not in target_dates:
        errors.append("DATE_NOT_TARGET_COMPLETED_DAILY_BAR")
    for col in ["open", "high", "low", "close", "volume"]:
        if pd.isna(row.get(col)):
            errors.append(f"{col.upper()}_NOT_NUMERIC")
    for col in ["open", "high", "low", "close"]:
        if not pd.isna(row.get(col)) and float(row[col]) <= 0:
            errors.append(f"{col.upper()}_NON_POSITIVE")
    if not pd.isna(row.get("volume")) and float(row["volume"]) < 0:
        errors.append("VOLUME_NEGATIVE")
    if not any(pd.isna(row.get(col)) for col in ["open", "high", "low", "close"]):
        if float(row["high"]) < float(row["low"]):
            errors.append("HIGH_BELOW_LOW")
        if float(row["high"]) < float(row["open"]) or float(row["high"]) < float(row["close"]):
            errors.append("HIGH_BELOW_OPEN_OR_CLOSE")
        if float(row["low"]) > float(row["open"]) or float(row["low"]) > float(row["close"]):
            errors.append("LOW_ABOVE_OPEN_OR_CLOSE")
    return errors

def autypes():
    result = []
    for name in ["QFQ", "NONE"]:
        if hasattr(AuType, name):
            result.append((name, getattr(AuType, name)))
    return result or [("NONE", None)]

ctx = None
try:
    ctx = OpenQuoteContext(host=host, port=port)
    connection["moomoo_opend_connection_success"] = True
    for code in codes:
        for autype_name, autype in autypes():
            error = ""
            try:
                ret, data, *_ = ctx.request_history_kline(
                    code=code,
                    start=target_dates[0],
                    end=target_dates[1],
                    ktype=KLType.K_DAY,
                    autype=autype,
                )
                if ret != RET_OK:
                    frame = pd.DataFrame()
                    error = str(data)
                else:
                    frame = pd.DataFrame(data)
            except Exception as exc:
                frame = pd.DataFrame()
                error = str(exc)
            normalized = []
            if not frame.empty:
                rename = {}
                for col in frame.columns:
                    low = str(col).strip().lower()
                    if low in {"time_key", "date", "time"}:
                        rename[col] = "date"
                    elif low in {"open", "high", "low", "close", "volume"}:
                        rename[col] = low
                frame = frame.rename(columns=rename)
                for col in ["date", "open", "high", "low", "close", "volume"]:
                    if col not in frame:
                        frame[col] = pd.NA
                frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
                for col in ["open", "high", "low", "close", "volume"]:
                    frame[col] = pd.to_numeric(frame[col], errors="coerce")
                for _, item in frame.iterrows():
                    row = {
                        "symbol": symbol_from_code(code),
                        "date": item.get("date"),
                        "open": item.get("open"),
                        "high": item.get("high"),
                        "low": item.get("low"),
                        "close": item.get("close"),
                        "volume": item.get("volume"),
                        "source_provider": "MOOMOO_OPEND_QUOTE_API",
                        "moomoo_code": code,
                        "autype": autype_name,
                    }
                    errors = validate(row)
                    row["valid_completed_daily_bar"] = not errors
                    row["validation_error"] = "|".join(errors)
                    raw_rows.append(row)
                    normalized.append(row)
            valid_dates = sorted({str(row["date"]) for row in normalized if row.get("valid_completed_daily_bar")})
            summary_rows.append({
                "moomoo_code": code,
                "symbol": symbol_from_code(code),
                "autype": autype_name,
                "returned_row_count": len(normalized),
                "valid_row_count": len([row for row in normalized if row.get("valid_completed_daily_bar")]),
                "target_dates_covered": "|".join(valid_dates),
                "status": "SUCCESS" if all(date in valid_dates for date in target_dates) else "FAILED",
                "error": error,
            })
except Exception as exc:
    connection["error"] = str(exc)
finally:
    if ctx is not None:
        try:
            ctx.close()
        except Exception:
            pass

print(json.dumps({"connection": connection, "raw_rows": raw_rows, "summary_rows": summary_rows}, default=str, allow_nan=False))
'''


def run_healthcheck_in_dedicated_env(
    dedicated_python: Path,
    import_succeeded: bool,
    host: str,
    port: int,
    timeout_seconds: int | None = None,
    command_runner: Callable[[list[str], int], subprocess.CompletedProcess[str]] = run_command,
) -> tuple[dict[str, Any], pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    connection = {
        "moomoo_opend_host": host,
        "moomoo_opend_port": port,
        "moomoo_opend_connection_attempted": False,
        "moomoo_opend_connection_success": False,
        "quote_context_only": True,
        "error": "",
    }
    timeout_seconds = timeout_seconds or parse_healthcheck_timeout(os.environ.get(HEALTHCHECK_TIMEOUT_ENV))
    diagnostic = {
        "returncode": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "parse_error": "",
        "healthcheck_attempted": False,
        "healthcheck_timeout": False,
        "healthcheck_timeout_seconds": timeout_seconds,
    }
    if not import_succeeded:
        return connection, pd.DataFrame(columns=RAW_FIELDS), [], diagnostic
    diagnostic["healthcheck_attempted"] = True
    try:
        proc = command_runner([str(dedicated_python), "-c", healthcheck_subprocess_code(), host, str(port)], timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        connection["moomoo_opend_connection_attempted"] = True
        connection["moomoo_opend_connection_success"] = False
        connection["error"] = f"HEALTHCHECK_TIMEOUT_AFTER_{timeout_seconds}_SECONDS"
        diagnostic["healthcheck_timeout"] = True
        diagnostic["healthcheck_timeout_seconds"] = getattr(exc, "timeout", timeout_seconds) or timeout_seconds
        diagnostic["stdout_tail"] = ((exc.stdout or "") if isinstance(exc.stdout, str) else "").encode("utf-8", "ignore").decode("utf-8")[-4000:]
        diagnostic["stderr_tail"] = ((exc.stderr or "") if isinstance(exc.stderr, str) else "").encode("utf-8", "ignore").decode("utf-8")[-4000:]
        return connection, pd.DataFrame(columns=RAW_FIELDS), [], diagnostic
    diagnostic["returncode"] = proc.returncode
    diagnostic["stdout_tail"] = (proc.stdout or "")[-4000:]
    diagnostic["stderr_tail"] = (proc.stderr or "")[-4000:]
    try:
        payload = parse_healthcheck_payload(proc.stdout or "")
        connection = payload.get("connection", connection)
        raw = pd.DataFrame(payload.get("raw_rows", []), columns=RAW_FIELDS)
        summary_rows = payload.get("summary_rows", [])
        return connection, raw, summary_rows, diagnostic
    except Exception as exc:
        connection["moomoo_opend_connection_attempted"] = True
        connection["error"] = (proc.stderr or str(exc))[-2000:]
        diagnostic["parse_error"] = str(exc)
        return connection, pd.DataFrame(columns=RAW_FIELDS), [], diagnostic


def parse_healthcheck_payload(stdout: str) -> dict[str, Any]:
    for line in reversed((stdout or "").splitlines()):
        candidate = line.strip()
        if not candidate.startswith("{") or '"connection"' not in candidate:
            continue
        return json.loads(candidate)
    raise ValueError("healthcheck JSON payload not found in stdout")


def target_date_coverage(raw_rows: pd.DataFrame) -> dict[str, bool]:
    if raw_rows.empty:
        return {date: False for date in TARGET_DATES}
    valid = raw_rows[raw_rows["valid_completed_daily_bar"].eq(True)]
    return {date: bool(valid["date"].eq(date).any()) for date in TARGET_DATES}


def healthcheck_success(summary_rows: list[dict[str, Any]]) -> tuple[bool, int, int]:
    success_codes = {
        row["moomoo_code"]
        for row in summary_rows
        if row.get("status") == "SUCCESS" and row.get("moomoo_code") in HEALTHCHECK_CODES
    }
    return len(success_codes) == len(HEALTHCHECK_CODES), len(success_codes), len(set(HEALTHCHECK_CODES) - success_codes)


def decide_status(
    py_available: bool,
    env_ready: bool,
    create_requested: bool,
    install_attempted: bool,
    install_succeeded: bool,
    import_succeeded: bool,
    tcp_probe_success: bool,
    healthcheck_attempted: bool,
    opend_success: bool,
    hc_success: bool,
    healthcheck_timeout: bool = False,
) -> tuple[str, str]:
    if not py_available:
        return (
            "PARTIAL_PASS_V21_196_R4A_NEED_PY311_OR_PY312",
            "INSTALL_PYTHON_311_OR_312_THEN_RERUN",
        )
    if not env_ready and not create_requested:
        return (
            "PARTIAL_PASS_V21_196_R4A_CREATE_ENV_REQUIRED",
            "SET_CREATE_ENV_FLAG_TO_BUILD_DEDICATED_MOOMOO_ENV",
        )
    if install_attempted and not install_succeeded:
        return (
            "FAIL_V21_196_R4A_MOOMOO_API_INSTALL_FAILED",
            "FIX_DEDICATED_MOOMOO_PYTHON_ENV_OR_USE_RAW_EXPORT",
        )
    if env_ready and not import_succeeded:
        return (
            "FAIL_V21_196_R4A_MOOMOO_API_INSTALL_FAILED",
            "FIX_DEDICATED_MOOMOO_PYTHON_ENV_OR_USE_RAW_EXPORT",
        )
    if import_succeeded and not tcp_probe_success:
        return (
            "PARTIAL_PASS_V21_196_R4A_WAIT_OPEND_START",
            "START_MOOMOO_OPEND_AND_RERUN_R4A",
        )
    if import_succeeded and tcp_probe_success and not healthcheck_attempted:
        return (
            "FAIL_V21_196_R4C_INCONSISTENT_TCP_HEALTHCHECK_STATE",
            "REPAIR_R4_HEALTHCHECK_BRANCHING",
        )
    if healthcheck_timeout:
        return (
            "PARTIAL_PASS_V21_196_R4B_OPEND_HEALTHCHECK_TIMEOUT",
            "CHECK_OPEND_RUNNING_PORT_FIREWALL_AND_RERUN",
        )
    if import_succeeded and tcp_probe_success and healthcheck_attempted and not opend_success:
        return (
            "PARTIAL_PASS_V21_196_R4C_OPEND_TCP_OK_QUOTE_CONTEXT_FAILED",
            "CHECK_OPEND_LOGIN_API_PERMISSION_AND_RERUN",
        )
    if import_succeeded and opend_success and hc_success:
        return (
            "PASS_V21_196_R4A_MOOMOO_SDK_ENV_AND_OPEND_READY",
            "RERUN_V21_196_R3_USING_MOOMOO_ENV",
        )
    if import_succeeded and tcp_probe_success and opend_success and not hc_success:
        return (
            "PARTIAL_PASS_V21_196_R4C_OPEND_CONNECTED_KLINE_NO_DATA",
            "CHECK_MOOMOO_MARKET_DATA_PERMISSION_OR_DATE_RANGE",
        )
    if import_succeeded and not opend_success:
        return (
            "PARTIAL_PASS_V21_196_R4A_WAIT_OPEND_START",
            "START_MOOMOO_OPEND_AND_RERUN_R4A",
        )
    return (
        "PARTIAL_PASS_V21_196_R4A_WAIT_OPEND_START",
        "START_MOOMOO_OPEND_AND_RERUN_R4A",
    )


def write_user_action_instructions(path: Path, summary: dict[str, Any]) -> None:
    status = summary["final_status"]
    lines = [STAGE, "", f"final_status={status}", ""]
    if status == "PARTIAL_PASS_V21_196_R4A_NEED_PY311_OR_PY312":
        lines.extend([
            "Install Python 3.11 or Python 3.12, then rerun R4A.",
            "The main project Python is rejected for the Moomoo SDK because it is Python 3.14 or newer.",
            f"After installing Python 3.11/3.12, set {CREATE_ENV}=TRUE to create the dedicated Moomoo env.",
        ])
    elif status == "PARTIAL_PASS_V21_196_R4A_CREATE_ENV_REQUIRED":
        lines.extend([
            f"Dedicated Moomoo env is missing. Set {CREATE_ENV}=TRUE and rerun R4A.",
            "R4A will create .venv_moomoo_py312 when Python 3.12 is available, otherwise .venv_moomoo_py311.",
            f"It will install package {PACKAGE_INSTALL_NAME} and verify import with: from moomoo import *",
        ])
    elif status == "PARTIAL_PASS_V21_196_R4A_WAIT_OPEND_START":
        lines.extend([
            "Start Moomoo OpenD.",
            "Log in if OpenD requires authentication for quote access.",
            f"Confirm it is listening on {summary['moomoo_opend_host']}:{summary['moomoo_opend_port']}.",
            f"If using a different port, set {PORT_ENV}.",
            "Ensure firewall allows local connection.",
            "Rerun R4A/R4B after OpenD is running.",
        ])
    elif status == "PARTIAL_PASS_V21_196_R4B_OPEND_HEALTHCHECK_TIMEOUT":
        lines.extend([
            "The TCP probe reached OpenD, but the quote healthcheck subprocess timed out.",
            "Start or restart Moomoo OpenD.",
            f"Confirm it is listening on {summary['moomoo_opend_host']}:{summary['moomoo_opend_port']}.",
            f"If using a different port, set {PORT_ENV}.",
            "Ensure firewall allows local connection.",
            "Log in to OpenD if required.",
            "Rerun R4A/R4B.",
        ])
    elif status == "PARTIAL_PASS_V21_196_R4C_OPEND_TCP_OK_QUOTE_CONTEXT_FAILED":
        lines.extend([
            "OpenD TCP connectivity is available, but OpenQuoteContext failed.",
            "Confirm OpenD is logged in and API quote access is enabled.",
            f"Confirm host {summary['moomoo_opend_host']} and port {summary['moomoo_opend_port']}.",
            "Check OpenD permissions, API settings, and firewall, then rerun R4A/R4B.",
        ])
    elif status == "PARTIAL_PASS_V21_196_R4C_OPEND_CONNECTED_KLINE_NO_DATA":
        lines.extend([
            "OpenD quote context connected, but no valid target-date daily K-line rows were returned.",
            "Check Moomoo market data permissions and the requested date range.",
            "Rerun R4A/R4B after permissions or OpenD state are fixed.",
        ])
    elif status == "FAIL_V21_196_R4C_INCONSISTENT_TCP_HEALTHCHECK_STATE":
        lines.extend([
            "Internal R4 state is inconsistent: TCP probe succeeded but healthcheck was not attempted.",
            "Repair R4 healthcheck branching before using this result.",
        ])
    elif status == "FAIL_V21_196_R4A_MOOMOO_API_INSTALL_FAILED":
        lines.extend([
            f"Fix the dedicated Moomoo Python environment or install {PACKAGE_INSTALL_NAME} manually.",
            f"Dedicated env path: {summary['dedicated_env_path']}",
            f"Dedicated Python: {summary['dedicated_python_executable']}",
        ])
    else:
        lines.append("R4A is ready. Rerun V21.196_R3 using the dedicated Moomoo env if needed.")
    lines.extend([
        "",
        "Safety contract:",
        "quote_context_only=true",
        "trade_context_used=false",
        "broker_action_allowed=false",
        "official_adoption_allowed=false",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_summary(
    main_audit: dict[str, Any],
    discovery_rows: list[dict[str, Any]],
    env_audit: dict[str, Any],
    install_audit: dict[str, Any],
    import_audit: dict[str, Any],
    connection_audit: dict[str, Any],
    raw_rows: pd.DataFrame,
    summary_rows: list[dict[str, Any]],
    instructions_path: Path,
) -> dict[str, Any]:
    hc_success, success_count, failed_count = healthcheck_success(summary_rows)
    health_diag = connection_audit.get("healthcheck_subprocess", {})
    tcp_diag = connection_audit.get("tcp_probe", {})
    healthcheck_timeout = bool(health_diag.get("healthcheck_timeout", False))
    tcp_probe_success = bool(tcp_diag.get("tcp_probe_success", False))
    healthcheck_attempted = bool(health_diag.get("healthcheck_attempted", False))
    env_ready = Path(env_audit["dedicated_python_executable"]).is_file()
    py_available = any(bool(row.get("eligible_for_moomoo_sdk")) for row in discovery_rows) or version_eligible(str(env_audit.get("dedicated_python_version", "")))
    status, decision = decide_status(
        py_available=py_available,
        env_ready=env_ready,
        create_requested=bool(env_audit["create_env_requested"]),
        install_attempted=bool(install_audit["install_attempted"]),
        install_succeeded=bool(install_audit["install_succeeded"]),
        import_succeeded=bool(import_audit["moomoo_import_succeeded"]),
        tcp_probe_success=tcp_probe_success,
        healthcheck_attempted=healthcheck_attempted,
        opend_success=bool(connection_audit["moomoo_opend_connection_success"]),
        hc_success=hc_success,
        healthcheck_timeout=healthcheck_timeout,
    )
    r3_ready = bool(import_audit["moomoo_import_succeeded"] and connection_audit["moomoo_opend_connection_success"] and hc_success)
    return {
        "stage": STAGE,
        "final_status": status,
        "final_decision": decision,
        "main_project_python": main_audit["main_project_python"],
        "main_project_python_version": main_audit["main_project_python_version"],
        "main_project_python_rejected_for_moomoo_sdk": bool(main_audit["main_project_python_rejected_for_moomoo_sdk"]),
        "package_install_name": PACKAGE_INSTALL_NAME,
        "import_module_name": IMPORT_MODULE_NAME,
        "create_env_requested": bool(env_audit["create_env_requested"]),
        "env_created": bool(env_audit["env_created"]),
        "dedicated_env_path": env_audit["dedicated_env_path"],
        "dedicated_python_executable": env_audit["dedicated_python_executable"],
        "dedicated_python_version": env_audit["dedicated_python_version"],
        "py311_or_py312_available": py_available,
        "install_attempted": bool(install_audit["install_attempted"]),
        "install_succeeded": bool(install_audit["install_succeeded"]),
        "moomoo_api_package_installed": bool(import_audit["moomoo_api_package_installed"]),
        "moomoo_import_succeeded": bool(import_audit["moomoo_import_succeeded"]),
        "moomoo_opend_host": connection_audit["moomoo_opend_host"],
        "moomoo_opend_port": connection_audit["moomoo_opend_port"],
        "moomoo_opend_connection_attempted": bool(connection_audit["moomoo_opend_connection_attempted"]),
        "moomoo_opend_connection_success": bool(connection_audit["moomoo_opend_connection_success"]),
        "tcp_probe_attempted": bool(tcp_diag.get("tcp_probe_attempted", False)),
        "tcp_probe_success": bool(tcp_diag.get("tcp_probe_success", False)),
        "tcp_probe_error": str(tcp_diag.get("tcp_probe_error", "")),
        "quote_context_only": True,
        "trade_context_used": False,
        "healthcheck_attempted": healthcheck_attempted,
        "healthcheck_timeout": healthcheck_timeout,
        "healthcheck_timeout_seconds": health_diag.get("healthcheck_timeout_seconds", 0),
        "healthcheck_subprocess_returncode": health_diag.get("returncode"),
        "healthcheck_subprocess_stdout_tail": str(health_diag.get("stdout_tail", "")),
        "healthcheck_subprocess_stderr_tail": str(health_diag.get("stderr_tail", "")),
        "healthcheck_success_count": success_count,
        "healthcheck_failed_count": failed_count,
        "healthcheck_returned_row_count": int(len(raw_rows)),
        "healthcheck_target_dates_covered": target_date_coverage(raw_rows),
        "r3_ready_to_rerun": r3_ready,
        "user_action_required": not r3_ready,
        "user_action_instructions_path": rel(instructions_path),
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": False,
    }


def write_report(summary: dict[str, Any], path: Path) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"main_project_python={summary['main_project_python']}",
        f"main_project_python_version={summary['main_project_python_version']}",
        f"package_install_name={summary['package_install_name']}",
        f"import_module_name={summary['import_module_name']}",
        f"dedicated_env_path={summary['dedicated_env_path']}",
        f"dedicated_python_version={summary['dedicated_python_version']}",
        f"install_succeeded={summary['install_succeeded']}",
        f"moomoo_import_succeeded={summary['moomoo_import_succeeded']}",
        f"moomoo_opend_connection_success={summary['moomoo_opend_connection_success']}",
        f"tcp_probe_success={summary['tcp_probe_success']}",
        f"healthcheck_timeout={summary['healthcheck_timeout']}",
        f"r3_ready_to_rerun={summary['r3_ready_to_rerun']}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "protected_outputs_modified=false",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    host = os.environ.get(HOST_ENV, "127.0.0.1")
    port = parse_port(os.environ.get(PORT_ENV))
    healthcheck_timeout = parse_healthcheck_timeout(os.environ.get(HEALTHCHECK_TIMEOUT_ENV))
    instructions_path = OUT / "moomoo_user_action_instructions.txt"

    main_audit = main_python_audit()
    discovery_rows = discover_python_interpreters()
    selected = select_python_for_moomoo(discovery_rows)
    create_requested = env_truthy(CREATE_ENV)
    env_audit = create_dedicated_env(selected, create_requested)
    dedicated_python = Path(env_audit["dedicated_python_executable"])
    env_ready = dedicated_python.is_file()
    import_audit = verify_moomoo_import(dedicated_python, env_ready)
    if env_ready and not import_audit["moomoo_import_succeeded"]:
        install_audit = install_moomoo_api(dedicated_python, env_ready)
        import_audit = verify_moomoo_import(dedicated_python, env_ready)
    else:
        install_audit = {
            "package_install_name": PACKAGE_INSTALL_NAME,
            "import_module_name": IMPORT_MODULE_NAME,
            "install_attempted": False,
            "install_succeeded": False,
            "install_command": [str(dedicated_python), "-m", "pip", "install", PACKAGE_INSTALL_NAME],
            "returncode": None,
            "stdout_tail": "",
            "stderr_tail": "",
            "guard_note": "Install skipped because the dedicated env already imports moomoo.",
        }
    tcp_diag = {
        "tcp_probe_attempted": False,
        "tcp_probe_success": False,
        "tcp_probe_host": host,
        "tcp_probe_port": port,
        "tcp_probe_timeout_seconds": 3.0,
        "tcp_probe_error": "",
    }
    if import_audit["moomoo_import_succeeded"]:
        tcp_diag = tcp_probe(host, port, 3.0)
    if import_audit["moomoo_import_succeeded"] and tcp_diag["tcp_probe_success"]:
        connection_audit, raw_rows, health_summary, health_diag = run_healthcheck_in_dedicated_env(
            dedicated_python,
            bool(import_audit["moomoo_import_succeeded"]),
            host,
            port,
            healthcheck_timeout,
        )
    else:
        connection_audit = {
            "moomoo_opend_host": host,
            "moomoo_opend_port": port,
            "moomoo_opend_connection_attempted": False,
            "moomoo_opend_connection_success": False,
            "quote_context_only": True,
            "error": tcp_diag["tcp_probe_error"] if import_audit["moomoo_import_succeeded"] else "",
        }
        raw_rows = pd.DataFrame(columns=RAW_FIELDS)
        health_summary = []
        health_diag = {
            "returncode": None,
            "stdout_tail": "",
            "stderr_tail": "",
            "parse_error": "",
            "healthcheck_attempted": False,
            "healthcheck_timeout": False,
            "healthcheck_timeout_seconds": healthcheck_timeout,
        }
    connection_audit["tcp_probe"] = tcp_diag
    connection_audit["healthcheck_subprocess"] = health_diag

    summary = build_summary(
        main_audit,
        discovery_rows,
        env_audit,
        install_audit,
        import_audit,
        connection_audit,
        raw_rows,
        health_summary,
        instructions_path,
    )
    write_user_action_instructions(instructions_path, summary)

    write_csv(OUT / "python_interpreter_discovery.csv", discovery_rows, DISCOVERY_FIELDS)
    write_json(OUT / "moomoo_dedicated_env_audit.json", env_audit)
    write_json(OUT / "moomoo_api_install_audit.json", install_audit)
    write_json(OUT / "moomoo_import_audit.json", import_audit)
    write_json(OUT / "moomoo_opend_connection_audit.json", connection_audit)
    raw_rows.to_csv(OUT / "moomoo_daily_kline_healthcheck_raw.csv", index=False)
    write_csv(OUT / "moomoo_daily_kline_healthcheck_summary.csv", health_summary, SUMMARY_FIELDS)
    write_json(OUT / "moomoo_r3_readiness_flag.json", {
        "r3_ready_to_rerun": summary["r3_ready_to_rerun"],
        "dedicated_python_executable": summary["dedicated_python_executable"],
        "final_status": summary["final_status"],
        "final_decision": summary["final_decision"],
        "r3_runner": "scripts/v21/run_v21_196_r3_moomoo_daily_bar_fetcher_and_approved_csv_builder.ps1",
    })
    write_json(OUT / "v21_196_r4a_summary.json", summary)
    write_report(summary, OUT / "V21.196_R4A_moomoo_api_package_and_env_repair_report.txt")

    for key in [
        "final_status",
        "final_decision",
        "main_project_python",
        "main_project_python_version",
        "main_project_python_rejected_for_moomoo_sdk",
        "package_install_name",
        "import_module_name",
        "create_env_requested",
        "env_created",
        "dedicated_env_path",
        "dedicated_python_version",
        "install_attempted",
        "install_succeeded",
        "moomoo_api_package_installed",
        "moomoo_import_succeeded",
        "moomoo_opend_connection_success",
        "tcp_probe_attempted",
        "tcp_probe_success",
        "tcp_probe_error",
        "quote_context_only",
        "trade_context_used",
        "healthcheck_attempted",
        "healthcheck_timeout",
        "healthcheck_timeout_seconds",
        "healthcheck_success_count",
        "healthcheck_failed_count",
        "healthcheck_returned_row_count",
        "r3_ready_to_rerun",
        "user_action_required",
        "user_action_instructions_path",
        "official_adoption_allowed",
        "broker_action_allowed",
        "protected_outputs_modified",
    ]:
        print(f"{key}={summary[key]}")
    return summary


if __name__ == "__main__":
    run()
