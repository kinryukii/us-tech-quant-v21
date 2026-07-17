#!/usr/bin/env python
"""V22.041 R1A Moomoo read-only quote and log permission repair.

Research-only diagnostic and smoke test for ETF option quote access. This
module redirects provider log-related environment variables to a writable
repo-local directory before importing moomoo or opening a read-only quote
context. It never opens trade context, unlocks trading, or places orders.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import os
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


MODULE_ID = "V22.041_R1A"
MODULE_NAME = "ETF_OPTION_MOOMOO_READONLY_QUOTE_AND_LOG_PERMISSION_REPAIR"
STAGE = "V22.041_R1A_ETF_OPTION_MOOMOO_READONLY_QUOTE_AND_LOG_PERMISSION_REPAIR"
OUT_REL = Path("outputs") / "v22" / STAGE

V22_041_DIR = Path("outputs") / "v22" / "V22.041_OPTION_INTRADAY_ETF_ONLY_RESEARCH_LAYER_R1"
V22_036_R3B_DIR = Path("outputs") / "v22" / "V22.036_R3B_MOOMOO_FUTU_EXACT_PERMISSION_PATH_AND_IMPORT_TIME_LOG_CONFIG_AUDIT_RESEARCH_ONLY"

PASS_STATUS = "PASS_V22_041_R1A_MOOMOO_READONLY_OPTION_QUOTE_LOG_PERMISSION_REPAIRED"
WARN_STATUS = "WARN_V22_041_R1A_MOOMOO_READONLY_OPTION_QUOTE_NOT_VERIFIED"
FAIL_STATUS = "FAIL_V22_041_R1A_SAFE_LOG_DIR_NOT_WRITABLE"
READY_DECISION = "MOOMOO_READONLY_OPTION_QUOTE_READY_FOR_V22_041_RERUN_RESEARCH_ONLY"
BLOCKED_DECISION = "MOOMOO_READONLY_OPTION_QUOTE_NOT_READY_FOR_V22_041_RERUN_RESEARCH_ONLY"

SAFE_ENV_VARS = [
    "FUTU_OPEND_LOG_DIR",
    "MOOMOO_LOG_DIR",
    "FUTU_LOG_DIR",
    "FutuOpenD_LogDir",
]
APP_ENV_VARS = ["TMP", "TEMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA"]
SUMMARY_FIELDS = [
    "final_status",
    "final_decision",
    "execution_mode",
    "moomoo_import_available",
    "moomoo_quote_context_attempted",
    "moomoo_quote_context_connected",
    "moomoo_quote_context_disconnected_cleanly",
    "original_log_access_denied_detected",
    "safe_log_dir_selected",
    "safe_log_dir_path",
    "safe_log_dir_writable",
    "quote_access_status",
    "fallback_rows_used",
    "real_readonly_quote_verified",
    "trade_context_used",
    "unlock_trade_called",
    "place_order_called",
    "broker_action_allowed",
    "official_adoption_allowed",
    "research_only",
]
LOG_DIAGNOSTIC_FIELDS = [
    "source_file",
    "access_denied_detected",
    "extracted_log_path",
    "diagnostic_status",
    "error_text",
]
SMOKE_FIELDS = [
    "smoke_step",
    "attempted",
    "succeeded",
    "status",
    "error_type",
    "error_message",
    "row_count",
]


def utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def is_access_denied_text(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in ["access is denied", "permission denied", "permissionerror", "winerror 5", "errno 13"])


def extract_log_paths(text: str) -> list[str]:
    patterns = [
        r"([A-Za-z]:\\[^'\"\n\r<>|]+)",
        r"(/[^\s'\"\n\r<>|]+)",
    ]
    paths: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, text or ""):
            cleaned = match.rstrip(" .;,)]}")
            if cleaned and "log" in cleaned.lower() and cleaned not in paths:
                paths.append(cleaned)
    return paths


def discover_prior_diagnostics(repo_root: Path) -> list[Path]:
    candidates: list[Path] = []
    for rel in [V22_041_DIR, V22_036_R3B_DIR]:
        root = repo_root / rel
        if root.exists():
            candidates.extend(sorted(p for p in root.glob("*") if p.suffix.lower() in {".json", ".txt", ".csv", ".log"}))
    return candidates


def diagnose_prior_log_access(repo_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in discover_prior_diagnostics(repo_root):
        text = read_text_safe(path)
        detected = is_access_denied_text(text)
        log_paths = extract_log_paths(text)
        if detected or log_paths:
            rows.append(
                {
                    "source_file": str(path),
                    "access_denied_detected": detected,
                    "extracted_log_path": ";".join(log_paths),
                    "diagnostic_status": "ACCESS_DENIED_LOG_PATH_DETECTED" if detected else "LOG_PATH_DETECTED_NO_ACCESS_DENIED_TEXT",
                    "error_text": text[:1200],
                }
            )
    if not rows:
        rows.append({"source_file": "", "access_denied_detected": False, "extracted_log_path": "", "diagnostic_status": "NO_PRIOR_ACCESS_DENIED_LOG_PATH_FOUND", "error_text": ""})
    return rows


def validate_writable_dir(path: Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / "v22_041_r1a_write_probe.tmp"
        probe.write_text("probe\n", encoding="utf-8")
        probe.unlink()
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def select_safe_log_dir(repo_root: Path, output_dir: Path) -> Path:
    return (output_dir / "provider_logs").resolve()


def configure_safe_moomoo_environment(safe_log_dir: Path) -> dict[str, str]:
    safe_log_dir.mkdir(parents=True, exist_ok=True)
    safe_root = safe_log_dir.parent / "provider_env"
    userprofile = safe_root / "userprofile"
    appdata = safe_root / "AppData" / "Roaming"
    localappdata = safe_root / "AppData" / "Local"
    for path in [userprofile, appdata, localappdata, safe_log_dir]:
        path.mkdir(parents=True, exist_ok=True)
    updates = {
        "FUTU_OPEND_LOG_DIR": str(safe_log_dir),
        "MOOMOO_LOG_DIR": str(safe_log_dir),
        "FUTU_LOG_DIR": str(safe_log_dir),
        "FutuOpenD_LogDir": str(safe_log_dir),
        "TMP": str(safe_log_dir),
        "TEMP": str(safe_log_dir),
        "USERPROFILE": str(userprofile),
        "APPDATA": str(appdata),
        "LOCALAPPDATA": str(localappdata),
    }
    os.environ.update(updates)
    return updates


def import_moomoo(import_func: Callable[[str], Any] | None = None) -> tuple[Any | None, bool, str, str]:
    try:
        module = import_func("moomoo") if import_func else importlib.import_module("moomoo")
        return module, True, "", ""
    except Exception as exc:  # noqa: BLE001
        return None, False, type(exc).__name__, str(exc)


def opend_port_reachable(host: str, port: int, timeout_seconds: float = 1.5) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def result_rows_count(data: Any) -> int:
    if hasattr(data, "to_dict"):
        try:
            return len(data.to_dict("records"))
        except Exception:
            return 0
    if isinstance(data, list):
        return len(data)
    return 0


def result_succeeded(result: Any) -> tuple[bool, Any]:
    if isinstance(result, tuple) and len(result) >= 2:
        code = result[0]
        data = result[1]
        return str(code).upper() in {"0", "RET_OK", "OK"} or code == 0, data
    return result is not None, result


def smoke_test_quote_context(moomoo: Any, host: str, port: int) -> tuple[list[dict[str, Any]], dict[str, bool | str]]:
    rows: list[dict[str, Any]] = []
    state = {"attempted": True, "connected": False, "closed": False, "verified": False, "status": "QUOTE_CONTEXT_NOT_VERIFIED"}
    ctx = None
    try:
        quote_cls = getattr(moomoo, "OpenQuoteContext")
        ctx = quote_cls(host=host, port=port)
        state["connected"] = True
        rows.append({"smoke_step": "open_quote_context", "attempted": True, "succeeded": True, "status": "QUOTE_CONTEXT_OPENED", "error_type": "", "error_message": "", "row_count": 0})
    except Exception as exc:  # noqa: BLE001
        status = "QUOTE_CONTEXT_ACCESS_DENIED" if is_access_denied_text(str(exc)) else "QUOTE_CONTEXT_OPEN_FAILED"
        rows.append({"smoke_step": "open_quote_context", "attempted": True, "succeeded": False, "status": status, "error_type": type(exc).__name__, "error_message": str(exc), "row_count": 0})
        state["status"] = status
        return rows, state

    try:
        method = getattr(ctx, "get_option_chain", None)
        if method is None:
            rows.append({"smoke_step": "get_option_chain", "attempted": False, "succeeded": False, "status": "GET_OPTION_CHAIN_NOT_AVAILABLE", "error_type": "", "error_message": "", "row_count": 0})
            state["status"] = "READ_ONLY_QUOTE_CONTEXT_OPENED_OPTION_CHAIN_METHOD_MISSING"
        else:
            result = method(code="US.QQQ")
            ok, data = result_succeeded(result)
            count = result_rows_count(data)
            verified = ok and count > 0
            rows.append({"smoke_step": "get_option_chain", "attempted": True, "succeeded": verified, "status": "OPTION_CHAIN_READ_ONLY_QUOTE_VERIFIED" if verified else "OPTION_CHAIN_RETURNED_NO_ROWS_OR_NOT_OK", "error_type": "", "error_message": "", "row_count": count})
            state["verified"] = verified
            state["status"] = "READ_ONLY_OPTION_QUOTE_VERIFIED" if verified else "READ_ONLY_QUOTE_CONTEXT_OPENED_BUT_OPTION_QUOTE_NOT_VERIFIED"
    except Exception as exc:  # noqa: BLE001
        status = "OPTION_CHAIN_ACCESS_DENIED" if is_access_denied_text(str(exc)) else "OPTION_CHAIN_READ_ONLY_QUOTE_FAILED"
        rows.append({"smoke_step": "get_option_chain", "attempted": True, "succeeded": False, "status": status, "error_type": type(exc).__name__, "error_message": str(exc), "row_count": 0})
        state["status"] = status
    finally:
        close = getattr(ctx, "close", None)
        if close is not None:
            try:
                close()
                state["closed"] = True
                rows.append({"smoke_step": "close_quote_context", "attempted": True, "succeeded": True, "status": "QUOTE_CONTEXT_CLOSED", "error_type": "", "error_message": "", "row_count": 0})
            except Exception as exc:  # noqa: BLE001
                rows.append({"smoke_step": "close_quote_context", "attempted": True, "succeeded": False, "status": "QUOTE_CONTEXT_CLOSE_FAILED", "error_type": type(exc).__name__, "error_message": str(exc), "row_count": 0})
    return rows, state


def build_summary(
    execution_mode: str,
    import_ok: bool,
    quote_state: dict[str, bool | str],
    prior_rows: list[dict[str, Any]],
    safe_log_dir: Path,
    safe_writable: bool,
) -> dict[str, Any]:
    original_denied = any(bool(row["access_denied_detected"]) for row in prior_rows)
    quote_attempted = bool(quote_state.get("attempted", False))
    connected = bool(quote_state.get("connected", False))
    verified = bool(quote_state.get("verified", False))
    quote_status = str(quote_state.get("status", "QUOTE_CONTEXT_NOT_ATTEMPTED"))
    if not safe_writable:
        final_status, final_decision = FAIL_STATUS, BLOCKED_DECISION
    elif verified:
        final_status, final_decision = PASS_STATUS, READY_DECISION
    else:
        final_status, final_decision = WARN_STATUS, BLOCKED_DECISION
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "generated_at_utc": utc_now_text(),
        "final_status": final_status,
        "final_decision": final_decision,
        "execution_mode": execution_mode,
        "python_executable": sys.executable,
        "moomoo_import_available": import_ok,
        "moomoo_quote_context_attempted": quote_attempted,
        "moomoo_quote_context_connected": connected,
        "moomoo_quote_context_disconnected_cleanly": bool(quote_state.get("closed", False)),
        "original_log_access_denied_detected": original_denied,
        "safe_log_dir_selected": True,
        "safe_log_dir_path": str(safe_log_dir),
        "safe_log_dir_writable": safe_writable,
        "quote_access_status": quote_status,
        "fallback_rows_used": not verified,
        "real_readonly_quote_verified": verified,
        "trade_context_used": False,
        "unlock_trade_called": False,
        "place_order_called": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
    }


def report_text(summary: dict[str, Any]) -> str:
    return "\n".join(["V22.041 R1A Moomoo Read-Only Quote And Log Permission Repair", *[f"{key}={summary.get(key)}" for key in SUMMARY_FIELDS]]) + "\n"


def run(repo_root: Path, execute: bool = False, host: str = "127.0.0.1", port: int = 18441, import_func: Callable[[str], Any] | None = None) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = repo_root / OUT_REL
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_log_dir = select_safe_log_dir(repo_root, output_dir)
    safe_writable, safe_error = validate_writable_dir(safe_log_dir)
    env_updates = configure_safe_moomoo_environment(safe_log_dir) if safe_writable else {}

    prior_rows = diagnose_prior_log_access(repo_root)
    if safe_error:
        prior_rows.append({"source_file": str(safe_log_dir), "access_denied_detected": is_access_denied_text(safe_error), "extracted_log_path": str(safe_log_dir), "diagnostic_status": "SAFE_LOG_DIR_NOT_WRITABLE", "error_text": safe_error})

    smoke_rows: list[dict[str, Any]] = []
    quote_state: dict[str, bool | str] = {"attempted": False, "connected": False, "closed": False, "verified": False, "status": "EXECUTE_NOT_REQUESTED"}
    moomoo_module = None
    import_ok = False
    if execute and safe_writable:
        moomoo_module, import_ok, err_type, err_msg = import_moomoo(import_func)
        smoke_rows.append({"smoke_step": "import_moomoo", "attempted": True, "succeeded": import_ok, "status": "MOOMOO_IMPORT_OK" if import_ok else "MOOMOO_IMPORT_FAILED", "error_type": err_type, "error_message": err_msg, "row_count": 0})
        if not import_ok:
            quote_state["status"] = "MOOMOO_IMPORT_UNAVAILABLE"
            if is_access_denied_text(err_msg):
                prior_rows.append({"source_file": "moomoo_import", "access_denied_detected": True, "extracted_log_path": ";".join(extract_log_paths(err_msg)), "diagnostic_status": "IMPORT_ACCESS_DENIED_DETECTED", "error_text": err_msg})
        else:
            reachable, reach_error = (True, "") if import_func is not None else opend_port_reachable(host, port)
            smoke_rows.append({"smoke_step": "opend_port_preflight", "attempted": True, "succeeded": reachable, "status": "OPEND_PORT_REACHABLE" if reachable else "OPEND_PORT_UNREACHABLE", "error_type": "" if reachable else reach_error.split(":", 1)[0], "error_message": "" if reachable else reach_error, "row_count": 0})
            if not reachable:
                quote_state["status"] = "OPEND_PORT_UNREACHABLE"
                summary = build_summary("EXECUTE_READ_ONLY", import_ok, quote_state, prior_rows, safe_log_dir, safe_writable)
                summary["safe_environment_variables_set"] = ";".join(env_updates.keys())
                summary["safe_environment_variable_count"] = len(env_updates)
                write_csv(output_dir / "moomoo_log_permission_diagnostic.csv", LOG_DIAGNOSTIC_FIELDS, prior_rows)
                write_csv(output_dir / "moomoo_readonly_quote_smoke_test.csv", SMOKE_FIELDS, smoke_rows)
                write_json(output_dir / "v22_041_r1a_summary.json", summary)
                (output_dir / "V22.041_R1A_moomoo_readonly_quote_and_log_permission_repair_report.txt").write_text(report_text(summary), encoding="utf-8")
                return summary
            quote_rows, quote_state = smoke_test_quote_context(moomoo_module, host, port)
            smoke_rows.extend(quote_rows)
            for row in quote_rows:
                if is_access_denied_text(str(row.get("error_message", ""))):
                    prior_rows.append({"source_file": f"smoke:{row['smoke_step']}", "access_denied_detected": True, "extracted_log_path": ";".join(extract_log_paths(str(row.get("error_message", "")))), "diagnostic_status": "SMOKE_ACCESS_DENIED_DETECTED", "error_text": row.get("error_message", "")})
    else:
        smoke_rows.append({"smoke_step": "execute_gate", "attempted": False, "succeeded": False, "status": "EXECUTE_NOT_REQUESTED" if not execute else "SAFE_LOG_DIR_NOT_WRITABLE", "error_type": "", "error_message": safe_error, "row_count": 0})

    summary = build_summary("EXECUTE_READ_ONLY" if execute else "PLAN", import_ok, quote_state, prior_rows, safe_log_dir, safe_writable)
    summary["safe_environment_variables_set"] = ";".join(env_updates.keys())
    summary["safe_environment_variable_count"] = len(env_updates)

    write_csv(output_dir / "moomoo_log_permission_diagnostic.csv", LOG_DIAGNOSTIC_FIELDS, prior_rows)
    write_csv(output_dir / "moomoo_readonly_quote_smoke_test.csv", SMOKE_FIELDS, smoke_rows)
    write_json(output_dir / "v22_041_r1a_summary.json", summary)
    (output_dir / "V22.041_R1A_moomoo_readonly_quote_and_log_permission_repair_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18441)
    args = parser.parse_args(argv)
    summary = run(args.repo_root, execute=args.execute, host=args.host, port=args.port)
    for key in SUMMARY_FIELDS:
        print(f"{key}={summary.get(key)}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_041_r1a_summary.json'}")
    return 1 if summary["final_status"] == FAIL_STATUS else 0


if __name__ == "__main__":
    raise SystemExit(main())
