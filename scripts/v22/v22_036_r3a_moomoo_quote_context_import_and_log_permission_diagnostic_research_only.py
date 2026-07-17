#!/usr/bin/env python
"""V22.036_R3A Moomoo import/log permission diagnostic.

Research-only environment diagnostic for the V22.036_R3 provider import failure.
It does not open quote or trade contexts, fetch market data, refresh option
chains/quotes, calculate IV/Greeks, or generate candidates.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

import pandas as pd


MODULE_ID = "V22.036_R3A"
MODULE_NAME = "MOOMOO_QUOTE_CONTEXT_IMPORT_AND_LOG_PERMISSION_DIAGNOSTIC_RESEARCH_ONLY"
STAGE = "V22.036_R3A_MOOMOO_QUOTE_CONTEXT_IMPORT_AND_LOG_PERMISSION_DIAGNOSTIC_RESEARCH_ONLY"
OUT_REL = Path("outputs") / "v22" / STAGE
V22_036_R3_DIR = Path("outputs") / "v22" / "V22.036_R3_OPTION_READ_ONLY_UNDERLYING_QUOTE_SNAPSHOT_REFRESH_AND_INJECTION_RESEARCH_ONLY"
V22_036_R2_DIR = Path("outputs") / "v22" / "V22.036_R2_OPTION_UNDERLYING_SPOT_FRESHNESS_ROOT_CAUSE_AND_SAME_SNAPSHOT_RECOVERY_AUDIT_RESEARCH_ONLY"
V22_036_R1_DIR = Path("outputs") / "v22" / "V22.036_R1_OPTION_UNDERLYING_SPOT_SOURCE_RESOLUTION_AND_INJECTION_AUDIT_RESEARCH_ONLY"
V22_035_R1_DIR = Path("outputs") / "v22" / "V22.035_R1_OPTION_SYNTHETIC_IV_GREEKS_CALCULABILITY_AUDIT_RESEARCH_ONLY"

PASS_READY = "PASS_V22_036_R3A_MOOMOO_IMPORT_READY_WITH_SAFE_LOG_DIR"
WARN_RETRY_FAILED = "WARN_V22_036_R3A_SAFE_LOG_DIR_READY_IMPORT_RETRY_FAILED"
WARN_PERMISSION = "WARN_V22_036_R3A_MANUAL_PERMISSION_REPAIR_REQUIRED"
WARN_PACKAGE = "WARN_V22_036_R3A_MOOMOO_PACKAGE_INSTALL_OR_REPAIR_REQUIRED"
FAIL_INPUT = "FAIL_V22_036_R3A_INPUT_NOT_FOUND"
READY_DECISION = "MOOMOO_QUOTE_CONTEXT_IMPORT_READY_RERUN_V22_036_R3_RESEARCH_ONLY"
BLOCKED_DECISION = "MOOMOO_LOG_PERMISSION_REPAIR_REQUIRED_BEFORE_V22_036_R3_RETRY"


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def discover_r3_inputs(repo_root: Path) -> list[Path]:
    root = repo_root / V22_036_R3_DIR
    if not root.exists():
        return []
    return sorted([p for p in root.glob("*") if p.suffix.lower() in {".csv", ".json", ".txt"}])


def infer_failure_type(status: str, error: str) -> str:
    text = f"{status} {error}".lower()
    if "permission" in text and ("opend" in text or "log" in text):
        return "OPEND_LOG_PATH_PERMISSION_ERROR"
    if "permission" in text and "moomoo" in text:
        return "MOOMOO_PACKAGE_IMPORT_PERMISSION_ERROR"
    if "no module named" in text or "not installed" in text:
        return "MOOMOO_PACKAGE_NOT_INSTALLED"
    if "connection" in text or "opend" in text:
        return "OPEND_CONNECTION_FAILURE"
    if "schema" in text:
        return "PROVIDER_SCHEMA_FAILURE"
    if status:
        return "UNKNOWN_PROVIDER_FAILURE"
    return "INPUT_NOT_FOUND"


def extract_log_path(text: str) -> str:
    patterns = [r"([A-Za-z]:\\[^'\"\n\r]+?\.log)", r"(/[^\s'\"\n\r]+?\.log)"]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""


def extract_prior_failure(repo_root: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for path in discover_r3_inputs(repo_root):
        final_status = quote_status = attempted = succeeded = error = ""
        try:
            if path.suffix.lower() == ".json":
                payload = read_json(path)
                final_status = payload.get("final_status", "")
                quote_status = payload.get("quote_refresh_status", "")
                attempted = payload.get("provider_call_attempted", "")
                succeeded = payload.get("provider_call_succeeded", "")
            elif path.suffix.lower() == ".csv":
                frame = pd.read_csv(path, dtype=str, keep_default_na=False)
                if len(frame):
                    row = frame.iloc[0]
                    quote_status = row.get("quote_refresh_status", "")
                    attempted = row.get("provider_call_attempted", "")
                    succeeded = row.get("provider_call_succeeded", "")
                    error = row.get("quote_refresh_error", "")
            else:
                error = path.read_text(encoding="utf-8", errors="ignore")
                final_match = re.search(r"final_status=([A-Z0-9_]+)", error)
                final_status = final_match.group(1) if final_match else ""
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
        combined = " ".join(str(x) for x in [final_status, quote_status, error])
        rows.append(
            {
                "source_file": str(path),
                "final_status": final_status,
                "quote_refresh_status": quote_status,
                "provider_call_attempted": attempted,
                "provider_call_succeeded": succeeded,
                "extracted_error_text": error,
                "extracted_log_path": extract_log_path(combined),
                "inferred_failure_type": infer_failure_type(quote_status, combined),
                "failure_extraction_status": "EXTRACTED" if combined.strip() else "NO_FAILURE_TEXT_FOUND",
            }
        )
    if not rows:
        rows.append({"source_file": "", "final_status": "", "quote_refresh_status": "", "provider_call_attempted": "", "provider_call_succeeded": "", "extracted_error_text": "", "extracted_log_path": "", "inferred_failure_type": "INPUT_NOT_FOUND", "failure_extraction_status": "INPUT_NOT_FOUND"})
    return pd.DataFrame(rows)


def try_import_package(name: str, import_func: Callable[[str], Any] = __import__) -> tuple[bool, str, str, str]:
    try:
        module = import_func(name)
        return True, getattr(module, "__version__", ""), "", ""
    except Exception as exc:  # noqa: BLE001
        return False, "", type(exc).__name__, str(exc)


def audit_python_environment(import_func: Callable[[str], Any] = __import__) -> pd.DataFrame:
    moomoo_ok, moomoo_ver, moomoo_type, moomoo_msg = try_import_package("moomoo", import_func)
    futu_ok, futu_ver, futu_type, futu_msg = try_import_package("futu", import_func)
    if moomoo_ok:
        status = "MOOMOO_IMPORT_OK"
    elif moomoo_type in {"ModuleNotFoundError", "ImportError"} and "No module named" in moomoo_msg:
        status = "MOOMOO_NOT_INSTALLED"
    elif moomoo_type == "PermissionError" or "permission" in moomoo_msg.lower():
        status = "MOOMOO_IMPORT_PERMISSION_ERROR"
    elif moomoo_type:
        status = "MOOMOO_IMPORT_FAILED_OTHER"
    else:
        status = "UNKNOWN_ENVIRONMENT_STATUS"
    return pd.DataFrame([{"python_executable": sys.executable, "python_version": sys.version, "cwd": str(Path.cwd()), "platform": platform.platform(), "current_user": getpass.getuser(), "moomoo_import_attempted": True, "moomoo_import_succeeded": moomoo_ok, "moomoo_version": moomoo_ver, "moomoo_import_error_type": moomoo_type, "moomoo_import_error_message": moomoo_msg, "futu_import_attempted": True, "futu_import_succeeded": futu_ok, "futu_version": futu_ver, "futu_import_error_type": futu_type, "futu_import_error_message": futu_msg, "environment_status": status}])


def probe_path(path: Path, source: str) -> dict[str, Any]:
    create_attempted = write_attempted = False
    create_ok = write_ok = delete_ok = False
    error = ""
    exists = path.exists()
    is_dir = path.is_dir()
    target = path
    try:
        if exists and not is_dir:
            return {"candidate_path": str(path), "path_source": source, "exists": exists, "is_dir": is_dir, "create_dir_attempted": False, "create_dir_succeeded": False, "write_probe_attempted": False, "write_probe_succeeded": False, "delete_probe_succeeded": False, "permission_status": "NOT_A_DIRECTORY", "error_message": ""}
        if not exists:
            create_attempted = True
            target.mkdir(parents=True, exist_ok=True)
            create_ok = True
        probe = target / "v22_036_r3a_probe.tmp"
        write_attempted = True
        probe.write_text("probe\n", encoding="utf-8")
        write_ok = True
        probe.unlink()
        delete_ok = True
    except PermissionError as exc:
        error = str(exc)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    if write_ok and (exists or create_ok):
        status = "WRITABLE" if exists else "PATH_MISSING_CREATED_WRITABLE"
    elif create_attempted and not create_ok:
        status = "PATH_MISSING_CREATE_FAILED"
    elif error:
        status = "NOT_WRITABLE_PERMISSION_DENIED" if "permission" in error.lower() or "denied" in error.lower() else "UNKNOWN_PERMISSION_STATUS"
    else:
        status = "UNKNOWN_PERMISSION_STATUS"
    return {"candidate_path": str(path), "path_source": source, "exists": exists, "is_dir": path.is_dir(), "create_dir_attempted": create_attempted, "create_dir_succeeded": create_ok, "write_probe_attempted": write_attempted, "write_probe_succeeded": write_ok, "delete_probe_succeeded": delete_ok, "permission_status": status, "error_message": error}


def candidate_log_paths(repo_root: Path, output_dir: Path, prior: pd.DataFrame) -> list[tuple[Path, str]]:
    paths: list[tuple[Path, str]] = [(Path.cwd(), "cwd"), (repo_root, "repo_root"), (output_dir, "output_dir"), (Path.home(), "home"), (Path(tempfile.gettempdir()), "tempfile")]
    for env_name in ["FutuOpenD_LogDir", "FUTU_OPEND_LOG_DIR", "MOOMOO_LOG_DIR", "FUTU_LOG_DIR", "TEMP", "TMP"]:
        value = os.environ.get(env_name)
        if value:
            paths.append((Path(value), f"env:{env_name}"))
    for value in prior.get("extracted_log_path", pd.Series(dtype=str)).dropna().tolist():
        if value:
            paths.append((Path(value).parent, "prior_error_log_path"))
    unique: dict[str, tuple[Path, str]] = {}
    for path, source in paths:
        unique[str(path)] = (path, source)
    return list(unique.values())


def audit_log_paths(repo_root: Path, output_dir: Path, prior: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([probe_path(path, source) for path, source in candidate_log_paths(repo_root, output_dir, prior)])


def build_fallback(output_dir: Path) -> pd.DataFrame:
    fallback = output_dir / "provider_logs"
    row = probe_path(fallback, "safe_fallback")
    ready = row["permission_status"] in {"WRITABLE", "PATH_MISSING_CREATED_WRITABLE"}
    prefix = f'$env:FUTU_OPEND_LOG_DIR = "{fallback}"; $env:MOOMOO_LOG_DIR = "{fallback}";'
    status = "SAFE_FALLBACK_LOG_DIR_READY" if ready else ("SAFE_FALLBACK_LOG_DIR_CREATE_FAILED" if row["permission_status"] == "PATH_MISSING_CREATE_FAILED" else "SAFE_FALLBACK_LOG_DIR_NOT_WRITABLE")
    return pd.DataFrame([{"fallback_log_dir": str(fallback), "fallback_dir_created": row["create_dir_succeeded"], "fallback_dir_writable": ready, "fallback_probe_deleted": row["delete_probe_succeeded"], "recommended_environment_variable_name": "FUTU_OPEND_LOG_DIR;MOOMOO_LOG_DIR", "recommended_environment_variable_value": str(fallback), "recommended_powershell_prefix": prefix, "fallback_status": status}])


def retry_import_with_fallback(execute: bool, fallback_dir: str, import_func: Callable[[str], Any] = __import__) -> pd.DataFrame:
    if not execute:
        return pd.DataFrame([{"execute_mode": False, "fallback_env_set": False, "fallback_log_dir": fallback_dir, "import_retry_attempted": False, "import_retry_succeeded": False, "moomoo_version_after_retry": "", "import_retry_error_type": "", "import_retry_error_message": "", "retry_status": "IMPORT_RETRY_NOT_EXECUTED_DRY_RUN"}])
    os.environ["FUTU_OPEND_LOG_DIR"] = fallback_dir
    os.environ["MOOMOO_LOG_DIR"] = fallback_dir
    ok, version, err_type, err_msg = try_import_package("moomoo", import_func)
    return pd.DataFrame([{"execute_mode": True, "fallback_env_set": True, "fallback_log_dir": fallback_dir, "import_retry_attempted": True, "import_retry_succeeded": ok, "moomoo_version_after_retry": version, "import_retry_error_type": err_type, "import_retry_error_message": err_msg, "retry_status": "IMPORT_RETRY_SUCCEEDED_WITH_FALLBACK_LOG_DIR" if ok else "IMPORT_RETRY_FAILED_WITH_FALLBACK_LOG_DIR"}])


def build_repair_policy(prior_type: str, env_status: str, fallback_ready: bool, retry_ok: bool, input_found: bool) -> pd.DataFrame:
    if not input_found:
        label = "FAIL_INPUT_NOT_FOUND"
    elif fallback_ready and retry_ok:
        label = "RERUN_V22_036_R3_WITH_SAFE_LOG_DIR_ENV"
    elif env_status == "MOOMOO_NOT_INSTALLED":
        label = "INSTALL_OR_REPAIR_MOOMOO_PACKAGE_REQUIRED"
    elif prior_type in {"OPEND_LOG_PATH_PERMISSION_ERROR", "MOOMOO_PACKAGE_IMPORT_PERMISSION_ERROR"} or env_status == "MOOMOO_IMPORT_PERMISSION_ERROR":
        label = "MANUAL_FIX_MOOMOO_LOG_PERMISSION_REQUIRED"
    else:
        label = "PROVIDER_FAILURE_UNKNOWN_MANUAL_REVIEW_REQUIRED"
    return pd.DataFrame([{"prior_failure_type": prior_type, "moomoo_import_initial_status": env_status, "fallback_log_dir_ready": fallback_ready, "import_retry_succeeded": retry_ok, "v22_036_r3_rerun_recommended": label == "RERUN_V22_036_R3_WITH_SAFE_LOG_DIR_ENV", "manual_permission_repair_required": label == "MANUAL_FIX_MOOMOO_LOG_PERMISSION_REQUIRED", "provider_quote_context_test_allowed_next_step": label == "RERUN_V22_036_R3_WITH_SAFE_LOG_DIR_ENV", "option_chain_refresh_allowed": False, "option_quote_refresh_allowed": False, "iv_greeks_calculation_allowed": False, "full_option_candidate_generation_allowed": False, "broker_action_allowed": False, "official_adoption_allowed": False, "trade_order_allowed": False, "final_policy_label": label}])


def write_summary_and_report(output_dir: Path, summary: dict[str, Any]) -> None:
    (output_dir / "v22_036_r3a_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    keys = ["final_status", "final_decision", "prior_quote_refresh_status", "prior_failure_type", "python_executable", "moomoo_import_succeeded_initial", "moomoo_import_error_type_initial", "fallback_log_dir", "fallback_log_dir_ready", "import_retry_attempted", "import_retry_succeeded", "v22_036_r3_rerun_recommended", "provider_quote_context_test_allowed_next_step", "option_chain_refresh_allowed", "option_quote_refresh_allowed", "iv_greeks_calculation_allowed", "full_option_candidate_generation_allowed", "broker_action_allowed", "official_adoption_allowed", "trade_order_allowed"]
    lines = ["V22.036_R3A Moomoo Quote Context Import And Log Permission Diagnostic Research Only"] + [f"{k}={summary[k]}" for k in keys]
    (output_dir / "V22.036_R3A_moomoo_quote_context_import_and_log_permission_diagnostic_research_only_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(repo_root: Path, output_dir: Path | None = None, execute: bool = False, import_func: Callable[[str], Any] = __import__) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    default = (repo_root / OUT_REL).resolve()
    output_dir = (output_dir or default).resolve()
    if output_dir != default and default not in output_dir.parents:
        raise ValueError(f"OutputDir must be under {default}")
    output_dir.mkdir(parents=True, exist_ok=True)
    inputs = discover_r3_inputs(repo_root)
    prior = extract_prior_failure(repo_root)
    env = audit_python_environment(import_func)
    paths = audit_log_paths(repo_root, output_dir, prior)
    fallback = build_fallback(output_dir)
    retry = retry_import_with_fallback(execute, fallback.iloc[0]["fallback_log_dir"], import_func)
    prior_types = [x for x in prior["inferred_failure_type"].tolist() if x != "INPUT_NOT_FOUND"]
    prior_type = prior_types[0] if prior_types else "INPUT_NOT_FOUND"
    policy = build_repair_policy(prior_type, env.iloc[0]["environment_status"], bool(fallback.iloc[0]["fallback_dir_writable"]), bool(retry.iloc[0]["import_retry_succeeded"]), bool(inputs))
    label = policy.iloc[0]["final_policy_label"]
    if not inputs:
        final_status, final_decision = FAIL_INPUT, BLOCKED_DECISION
    elif label == "RERUN_V22_036_R3_WITH_SAFE_LOG_DIR_ENV":
        final_status, final_decision = PASS_READY, READY_DECISION
    elif label == "INSTALL_OR_REPAIR_MOOMOO_PACKAGE_REQUIRED":
        final_status, final_decision = WARN_PACKAGE, BLOCKED_DECISION
    elif label == "MANUAL_FIX_MOOMOO_LOG_PERMISSION_REQUIRED":
        final_status, final_decision = WARN_PERMISSION, BLOCKED_DECISION
    else:
        final_status, final_decision = WARN_RETRY_FAILED, BLOCKED_DECISION
    summary = {"module_id": MODULE_ID, "module_name": MODULE_NAME, "final_status": final_status, "final_decision": final_decision, "input_v22_036_r3_dir": str(repo_root / V22_036_R3_DIR), "discovered_input_file_count": len(inputs), "prior_final_status": next((x for x in prior["final_status"].tolist() if x), ""), "prior_quote_refresh_status": next((x for x in prior["quote_refresh_status"].tolist() if x), ""), "prior_failure_type": prior_type, "python_executable": env.iloc[0]["python_executable"], "moomoo_import_succeeded_initial": bool(env.iloc[0]["moomoo_import_succeeded"]), "moomoo_import_error_type_initial": env.iloc[0]["moomoo_import_error_type"], "moomoo_import_error_message_initial": env.iloc[0]["moomoo_import_error_message"], "fallback_log_dir": fallback.iloc[0]["fallback_log_dir"], "fallback_log_dir_ready": bool(fallback.iloc[0]["fallback_dir_writable"]), "import_retry_attempted": bool(retry.iloc[0]["import_retry_attempted"]), "import_retry_succeeded": bool(retry.iloc[0]["import_retry_succeeded"]), "import_retry_error_type": retry.iloc[0]["import_retry_error_type"], "import_retry_error_message": retry.iloc[0]["import_retry_error_message"], "v22_036_r3_rerun_recommended": bool(policy.iloc[0]["v22_036_r3_rerun_recommended"]), "recommended_powershell_prefix": fallback.iloc[0]["recommended_powershell_prefix"], "provider_quote_context_test_allowed_next_step": bool(policy.iloc[0]["provider_quote_context_test_allowed_next_step"]), "option_chain_refresh_allowed": False, "option_quote_refresh_allowed": False, "iv_greeks_calculation_allowed": False, "full_option_candidate_generation_allowed": False, "broker_action_allowed": False, "official_adoption_allowed": False, "trade_order_allowed": False}
    prior.to_csv(output_dir / "moomoo_prior_failure_extraction_audit.csv", index=False, lineterminator="\n")
    env.to_csv(output_dir / "moomoo_python_environment_and_package_audit.csv", index=False, lineterminator="\n")
    paths.to_csv(output_dir / "moomoo_log_path_permission_audit.csv", index=False, lineterminator="\n")
    fallback.to_csv(output_dir / "moomoo_safe_log_dir_fallback_audit.csv", index=False, lineterminator="\n")
    retry.to_csv(output_dir / "moomoo_import_retry_with_fallback_audit.csv", index=False, lineterminator="\n")
    policy.to_csv(output_dir / "moomoo_log_permission_repair_recommendation_policy.csv", index=False, lineterminator="\n")
    write_summary_and_report(output_dir, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    summary = run(args.repo_root, args.output_dir, args.execute)
    print(f"final_status={summary['final_status']}")
    print(f"final_decision={summary['final_decision']}")
    print(f"summary_path={(args.output_dir or (args.repo_root / OUT_REL)) / 'v22_036_r3a_summary.json'}")
    print("full_option_candidate_generation_allowed=False")
    print("broker_action_allowed=False")
    print("official_adoption_allowed=False")
    print("trade_order_allowed=False")
    return 1 if summary["final_status"] == FAIL_INPUT else 0


if __name__ == "__main__":
    raise SystemExit(main())
