#!/usr/bin/env python
"""V22.036_R3B exact Moomoo/Futu import permission path diagnostic.

Research-only. Static package discovery/source scans avoid importing moomoo or
futu. Optional --execute subprocess experiments import packages only; they do
not open quote/trade contexts, connect to OpenD, or fetch data.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd


MODULE_ID = "V22.036_R3B"
MODULE_NAME = "MOOMOO_FUTU_EXACT_PERMISSION_PATH_AND_IMPORT_TIME_LOG_CONFIG_AUDIT_RESEARCH_ONLY"
STAGE = "V22.036_R3B_MOOMOO_FUTU_EXACT_PERMISSION_PATH_AND_IMPORT_TIME_LOG_CONFIG_AUDIT_RESEARCH_ONLY"
OUT_REL = Path("outputs") / "v22" / STAGE
V22_036_R3A_DIR = Path("outputs") / "v22" / "V22.036_R3A_MOOMOO_QUOTE_CONTEXT_IMPORT_AND_LOG_PERMISSION_DIAGNOSTIC_RESEARCH_ONLY"
V22_036_R3_DIR = Path("outputs") / "v22" / "V22.036_R3_OPTION_READ_ONLY_UNDERLYING_QUOTE_SNAPSHOT_REFRESH_AND_INJECTION_RESEARCH_ONLY"

PASS_READY = "PASS_V22_036_R3B_IMPORT_PERMISSION_REPAIR_READY_RERUN_R3"
WARN_MANUAL = "WARN_V22_036_R3B_MANUAL_PERMISSION_REPAIR_REQUIRED"
WARN_REINSTALL = "WARN_V22_036_R3B_PACKAGE_REINSTALL_OR_REPAIR_REQUIRED"
WARN_FALLBACK = "WARN_V22_036_R3B_FALLBACK_TO_MANUAL_SPOT_GATE_RESEARCH_ONLY"
FAIL_INPUT = "FAIL_V22_036_R3B_INPUT_NOT_FOUND"
READY_DECISION = "MOOMOO_FUTU_IMPORT_PERMISSION_REPAIRED_READY_TO_RERUN_V22_036_R3_RESEARCH_ONLY"
MANUAL_DECISION = "MOOMOO_FUTU_IMPORT_PERMISSION_MANUAL_REPAIR_REQUIRED_RESEARCH_ONLY"
FALLBACK_DECISION = "MOOMOO_FUTU_IMPORT_UNREPAIRED_FALLBACK_TO_MANUAL_SPOT_GATE_RESEARCH_ONLY"

PATTERNS = ["log", "logger", "logging", "OpenD", "FutuOpenD", "LogDir", "log_dir", "logPath", "log_path", "FUTU_OPEND_LOG_DIR", "MOOMOO_LOG_DIR", "FUTU_LOG_DIR", "FutuOpenD_LogDir", "set_logger", "SysConfig", "RET_OK", "OpenQuoteContext", "OpenSecTradeContext"]
ENV_VARS = ["FUTU_OPEND_LOG_DIR", "MOOMOO_LOG_DIR", "FUTU_LOG_DIR", "FutuOpenD_LogDir", "FutuLogDir", "FutuLogPath", "LOG_DIR", "PYTHONLOGGING", "TMP", "TEMP", "USERPROFILE", "HOME"]


def extract_windows_paths(text: str) -> list[str]:
    return sorted(set(re.findall(r"[A-Za-z]:\\[^'\"\n\r<>|]+", text or "")))


def permission_paths(text: str) -> list[str]:
    paths = extract_windows_paths(text)
    if "permission" in (text or "").lower() or "winerror 5" in (text or "").lower() or "denied" in (text or "").lower():
        return paths
    return []


def path_like_logs(paths: list[str]) -> list[str]:
    return [p for p in paths if "log" in p.lower() or p.lower().endswith(".log")]


def read_r3a_errors(repo_root: Path) -> pd.DataFrame:
    root = repo_root / V22_036_R3A_DIR
    rows: list[dict[str, Any]] = []
    if not root.exists():
        return pd.DataFrame([{"source_file": "", "error_source": "", "error_type": "", "error_message": "", "traceback_text_present": False, "extracted_windows_paths": "", "extracted_permission_denied_paths": "", "extracted_log_like_paths": "", "fallback_env_vars_observed": "", "exact_permission_path_found": False, "extraction_status": "NO_PERMISSION_ERROR_TEXT_FOUND"}])
    for path in sorted([p for p in root.glob("*") if p.suffix.lower() in {".csv", ".json", ".txt"}]):
        try:
            texts: list[tuple[str, str, str]] = []
            if path.suffix.lower() == ".csv":
                frame = pd.read_csv(path, dtype=str, keep_default_na=False)
                for _, row in frame.iterrows():
                    for col in frame.columns:
                        if "error" in col.lower() or "trace" in col.lower() or "prefix" in col.lower():
                            texts.append((col, row.get(col, ""), row.get(col.replace("message", "type"), "")))
            elif path.suffix.lower() == ".json":
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("prior_failure_type"):
                    texts.append(("prior_failure_type", str(payload.get("prior_failure_type", "")), ""))
                for k, v in payload.items():
                    if "error" in k.lower() or "prefix" in k.lower() or "failure" in k.lower():
                        texts.append((k, str(v), str(payload.get(k.replace("message", "type"), ""))))
            else:
                texts.append(("report", path.read_text(encoding="utf-8", errors="ignore"), ""))
            for source, msg, err_type in texts:
                paths = extract_windows_paths(msg)
                ppaths = permission_paths(msg)
                logs = path_like_logs(paths)
                envs = ";".join([v for v in ENV_VARS if v in msg])
                if ppaths:
                    status = "EXACT_PERMISSION_PATH_FOUND"
                elif "permission" in msg.lower():
                    status = "ERROR_TEXT_FOUND_BUT_PATH_NOT_EXPLICIT"
                elif "traceback" in msg.lower():
                    status = "TRACEBACK_FOUND_BUT_PATH_NOT_EXPLICIT"
                else:
                    status = "NO_PERMISSION_ERROR_TEXT_FOUND"
                inferred = msg if msg in {"OPEND_LOG_PATH_PERMISSION_ERROR", "MOOMOO_PACKAGE_IMPORT_PERMISSION_ERROR", "MOOMOO_PACKAGE_NOT_INSTALLED"} else ""
                rows.append({"source_file": str(path), "error_source": source, "error_type": err_type, "error_message": msg[:1000], "traceback_text_present": "traceback" in msg.lower(), "extracted_windows_paths": ";".join(paths), "extracted_permission_denied_paths": ";".join(ppaths), "extracted_log_like_paths": ";".join(logs), "fallback_env_vars_observed": envs, "exact_permission_path_found": bool(ppaths), "inferred_failure_type": inferred, "extraction_status": status})
        except Exception as exc:  # noqa: BLE001
            rows.append({"source_file": str(path), "error_source": "", "error_type": type(exc).__name__, "error_message": str(exc), "traceback_text_present": False, "extracted_windows_paths": "", "extracted_permission_denied_paths": "", "extracted_log_like_paths": "", "fallback_env_vars_observed": "", "exact_permission_path_found": False, "inferred_failure_type": "", "extraction_status": "INPUT_FILE_READ_FAILED"})
    return pd.DataFrame(rows)


def static_package_discovery(package: str) -> dict[str, Any]:
    try:
        spec = importlib.util.find_spec(package)
        spec_found = spec is not None
        origin = str(spec.origin) if spec and spec.origin else ""
        package_dir = str(Path(origin).parent) if origin and origin != "built-in" else ""
        try:
            version = importlib.metadata.version(package)
            meta = True
        except importlib.metadata.PackageNotFoundError:
            version = ""
            meta = False
        files = list(Path(package_dir).rglob("*.py")) if package_dir and Path(package_dir).exists() else []
        candidates = 0
        for file in files[:1000]:
            text = file.read_text(encoding="utf-8", errors="ignore")
            if any(p.lower() in text.lower() for p in PATTERNS):
                candidates += 1
        if spec_found and package_dir:
            status = "PACKAGE_STATICALLY_DISCOVERED"
        elif spec_found:
            status = "PACKAGE_METADATA_ONLY"
        else:
            status = "PACKAGE_SPEC_NOT_FOUND"
        return {"package_name": package, "spec_found": spec_found, "spec_origin": origin, "package_dir": package_dir, "dist_metadata_found": meta, "dist_version": version, "file_count_scanned": len(files[:1000]), "log_config_candidate_file_count": candidates, "discovery_status": status}
    except Exception:  # noqa: BLE001
        return {"package_name": package, "spec_found": False, "spec_origin": "", "package_dir": "", "dist_metadata_found": False, "dist_version": "", "file_count_scanned": 0, "log_config_candidate_file_count": 0, "discovery_status": "STATIC_DISCOVERY_FAILED"}


def source_scan(discovery: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, pkg in discovery.iterrows():
        package_dir = Path(pkg.get("package_dir", ""))
        if not package_dir.exists():
            continue
        for file in sorted(package_dir.rglob("*.py"))[:1000]:
            text = file.read_text(encoding="utf-8", errors="ignore")
            matched = sorted({p for p in PATTERNS if p.lower() in text.lower()})
            if not matched:
                continue
            env_refs = [v for v in ENV_VARS if v in text]
            default_paths = sorted(set(extract_windows_paths(text) + re.findall(r"(/[^\s'\"\)]+log[^\s'\"\)]*)", text, flags=re.I)))
            file_handler = "FileHandler" in text or ".log" in text
            import_time = file_handler and ("import logging" in text or "logging." in text)
            if import_time:
                risk = "HIGH_IMPORT_TIME_FILE_WRITE_LIKELY"
            elif env_refs or file_handler:
                risk = "MEDIUM_LOG_CONFIG_RELEVANT"
            else:
                risk = "LOW_STRING_MATCH_ONLY"
            rows.append({"package_name": pkg["package_name"], "source_file": str(file), "matched_pattern_count": len(matched), "matched_patterns": ";".join(matched), "candidate_config_names": ";".join(env_refs), "candidate_default_paths": ";".join(default_paths), "has_import_time_logger_init": import_time, "has_env_var_reference": bool(env_refs), "has_cwd_reference": "cwd" in text or "getcwd" in text, "has_home_reference": "home" in text.lower() or "USERPROFILE" in text, "has_temp_reference": "temp" in text.lower() or "TMP" in text, "has_file_handler_reference": file_handler, "risk_level": risk, "scan_status": "SCANNED"})
    return pd.DataFrame(rows)


def probe_candidate(path: Path, kind: str, reason: str) -> dict[str, Any]:
    try:
        if kind == "file":
            parent = path.parent
            parent_exists = parent.exists()
            if not parent_exists:
                return {"candidate_path": str(path), "path_kind": kind, "source_reason": reason, "exists": path.exists(), "parent_exists": False, "parent_writable": False, "path_writable_if_dir": False, "file_create_probe_succeeded": False, "delete_probe_succeeded": False, "permission_status": "PATH_MISSING_PARENT_MISSING", "error_message": ""}
            probe = path if not path.exists() else parent / "v22_r3b_probe.tmp"
            probe.write_text("probe\n", encoding="utf-8")
            probe.unlink()
            return {"candidate_path": str(path), "path_kind": kind, "source_reason": reason, "exists": path.exists(), "parent_exists": True, "parent_writable": True, "path_writable_if_dir": False, "file_create_probe_succeeded": True, "delete_probe_succeeded": True, "permission_status": "PARENT_WRITABLE_FILE_CAN_BE_CREATED", "error_message": ""}
        path.mkdir(parents=True, exist_ok=True)
        probe = path / "v22_r3b_probe.tmp"
        probe.write_text("probe\n", encoding="utf-8")
        probe.unlink()
        return {"candidate_path": str(path), "path_kind": kind, "source_reason": reason, "exists": path.exists(), "parent_exists": path.parent.exists(), "parent_writable": True, "path_writable_if_dir": True, "file_create_probe_succeeded": True, "delete_probe_succeeded": True, "permission_status": "WRITABLE", "error_message": ""}
    except Exception as exc:  # noqa: BLE001
        return {"candidate_path": str(path), "path_kind": kind, "source_reason": reason, "exists": path.exists(), "parent_exists": path.parent.exists(), "parent_writable": False, "path_writable_if_dir": False, "file_create_probe_succeeded": False, "delete_probe_succeeded": False, "permission_status": "PARENT_NOT_WRITABLE" if path.parent.exists() else "PATH_INVALID", "error_message": f"{type(exc).__name__}: {exc}"}


def reconstruct_paths(output_dir: Path, errors: pd.DataFrame, scan: pd.DataFrame) -> pd.DataFrame:
    items: list[tuple[Path, str, str]] = [(output_dir, "directory", "output_dir"), (Path.cwd(), "directory", "cwd"), (Path.home(), "directory", "home"), (Path(tempfile.gettempdir()), "directory", "temp")]
    for col in ["extracted_permission_denied_paths", "extracted_log_like_paths"]:
        for value in errors.get(col, pd.Series(dtype=str)).dropna():
            for part in str(value).split(";"):
                if part:
                    items.append((Path(part), "file" if Path(part).suffix else "directory", col))
    for value in scan.get("candidate_default_paths", pd.Series(dtype=str)).dropna():
        for part in str(value).split(";"):
            if part:
                items.append((Path(part), "file" if Path(part).suffix else "directory", "source_scan_default_path"))
    seen = set()
    rows = []
    for path, kind, reason in items:
        key = (str(path), kind)
        if key in seen:
            continue
        seen.add(key)
        rows.append(probe_candidate(path, kind, reason))
    return pd.DataFrame(rows)


def env_support(scan: pd.DataFrame, fallback_dir: str) -> pd.DataFrame:
    rows = []
    for var in ENV_VARS:
        refs = scan[scan.get("candidate_config_names", pd.Series(dtype=str)).fillna("").str.contains(re.escape(var), regex=True)] if not scan.empty else pd.DataFrame()
        supported = not refs.empty
        generic = var in {"TMP", "TEMP", "USERPROFILE", "HOME", "PYTHONLOGGING"}
        status = "SUPPORTED_BY_PACKAGE_SOURCE" if supported else ("GENERIC_OS_ENV_ONLY" if generic else "NOT_REFERENCED_BY_PACKAGE_SOURCE")
        rows.append({"env_var_name": var, "currently_set": var in os.environ, "current_value": os.environ.get(var, ""), "referenced_in_package_source": supported, "source_files_referencing": ";".join(refs["source_file"].head(10).tolist()) if supported else "", "likely_controls_log_path": supported or var in {"TMP", "TEMP"}, "recommended_to_set": supported or var in {"TMP", "TEMP"}, "recommended_value": fallback_dir if supported or var in {"TMP", "TEMP"} else "", "support_status": status})
    return pd.DataFrame(rows)


def run_import_experiment(package: str, name: str, cwd: Path, env_overrides: dict[str, str], execute: bool) -> dict[str, Any]:
    if not execute:
        return {"experiment_name": name, "package_name": package, "cwd": str(cwd), "env_overrides": json.dumps(env_overrides, sort_keys=True), "return_code": "", "stdout_tail": "", "stderr_tail": "", "import_succeeded": False, "extracted_permission_paths": "", "extracted_error_type": "", "experiment_status": "EXPERIMENT_NOT_EXECUTED_DRY_RUN"}
    env = os.environ.copy()
    env.update(env_overrides)
    proc = subprocess.run([sys.executable, "-c", f"import {package}; print('IMPORT_OK')"], cwd=str(cwd), env=env, text=True, capture_output=True, timeout=30)
    out = (proc.stdout or "")[-1000:]
    err = (proc.stderr or "")[-1000:]
    text = out + "\n" + err
    ok = proc.returncode == 0 and "IMPORT_OK" in out
    if ok:
        status = "IMPORT_SUCCEEDED"
        err_type = ""
    elif "No module named" in text:
        status = "IMPORT_FAILED_PACKAGE_NOT_FOUND"
        err_type = "ModuleNotFoundError"
    elif "PermissionError" in text or "WinError 5" in text or "permission" in text.lower():
        status = "IMPORT_FAILED_PERMISSION_ERROR"
        err_type = "PermissionError"
    else:
        status = "IMPORT_FAILED_OTHER"
        err_type = ""
    return {"experiment_name": name, "package_name": package, "cwd": str(cwd), "env_overrides": json.dumps(env_overrides, sort_keys=True), "return_code": proc.returncode, "stdout_tail": out, "stderr_tail": err, "import_succeeded": ok, "extracted_permission_paths": ";".join(permission_paths(text)), "extracted_error_type": err_type, "experiment_status": status}


def import_experiment_matrix(output_dir: Path, fallback_dir: Path, env_audit: pd.DataFrame, execute: bool) -> pd.DataFrame:
    env_vars = {row["env_var_name"]: str(fallback_dir) for _, row in env_audit.iterrows() if bool(row["recommended_to_set"])}
    variants = [
        ("baseline_env", Path.cwd(), {}),
        ("cwd_output_dir", output_dir, {}),
        ("cwd_fallback_provider_logs", fallback_dir, {}),
        ("env_supported_log_vars", Path.cwd(), {k: v for k, v in env_vars.items() if k not in {"TMP", "TEMP"}}),
        ("env_temp_vars", Path.cwd(), {"TMP": str(fallback_dir), "TEMP": str(fallback_dir)}),
        ("combined_cwd_env_temp", fallback_dir, env_vars),
    ]
    rows = []
    for package in ["moomoo", "futu"]:
        for name, cwd, env in variants:
            cwd.mkdir(parents=True, exist_ok=True)
            rows.append(run_import_experiment(package, name, cwd, env, execute))
    return pd.DataFrame(rows)


def repair_wrapper(matrix: pd.DataFrame, fallback_dir: Path) -> pd.DataFrame:
    successes = matrix[matrix["import_succeeded"] == True] if not matrix.empty else pd.DataFrame()
    selected = None
    order = ["env_supported_log_vars", "cwd_output_dir", "cwd_fallback_provider_logs", "env_temp_vars", "combined_cwd_env_temp", "baseline_env"]
    for name in order:
        match = successes[successes["experiment_name"] == name]
        if not match.empty:
            selected = match.iloc[0]
            break
    if selected is not None:
        strategy = selected["experiment_name"]
        prefix = ""
        cwd = ""
        env = selected["env_overrides"]
        if "env" in strategy or "combined" in strategy:
            env_dict = json.loads(env)
            prefix = " ".join([f'$env:{k} = "{v}";' for k, v in env_dict.items()])
        if "cwd" in strategy or "combined" in strategy:
            cwd = selected["cwd"]
        status = "REPAIR_READY_RERUN_V22_036_R3"
        rerun = True
        manual = ""
    else:
        perm = matrix[matrix["experiment_status"] == "IMPORT_FAILED_PERMISSION_ERROR"] if not matrix.empty else pd.DataFrame()
        status = "MANUAL_PERMISSION_REPAIR_REQUIRED" if not perm.empty else "PACKAGE_INSTALL_OR_REPAIR_REQUIRED"
        strategy = "manual_permission_repair" if not perm.empty else "package_reinstall_or_repair"
        prefix = ""
        cwd = ""
        env = ""
        rerun = False
        all_paths = [p for p in ";".join(perm.get("extracted_permission_paths", pd.Series(dtype=str)).tolist()).split(";") if p]
        manual = next((p for p in all_paths if "moomoo" in p.lower() or "opend" in p.lower() or p.lower().endswith(".log")), next(iter(all_paths), ""))
    return pd.DataFrame([{"repair_strategy": strategy, "successful_experiment_name": selected["experiment_name"] if selected is not None else "", "recommended_powershell_prefix": prefix, "recommended_working_directory": cwd, "recommended_env_vars": env, "manual_permission_target_path": manual, "manual_repair_instructions": "Grant write permission or redirect provider import-time log path." if manual else "", "v22_036_r3_rerun_recommended": rerun, "repair_status": status}])


def next_step_policy(errors: pd.DataFrame, discovery: pd.DataFrame, scan: pd.DataFrame, env_audit: pd.DataFrame, matrix: pd.DataFrame, repair: pd.DataFrame, input_found: bool) -> pd.DataFrame:
    exact = bool(errors.get("exact_permission_path_found", pd.Series(dtype=bool)).any()) if not errors.empty else False
    static = bool(discovery.get("spec_found", pd.Series(dtype=bool)).any()) if not discovery.empty else False
    scan_done = not scan.empty
    env_found = bool(env_audit.get("referenced_in_package_source", pd.Series(dtype=bool)).any()) if not env_audit.empty else False
    exp_ok = bool(matrix.get("import_succeeded", pd.Series(dtype=bool)).any()) if not matrix.empty else False
    repair_row = repair.iloc[0]
    if not input_found:
        label = "FAIL_INPUT_NOT_FOUND"
    elif exp_ok:
        label = "RERUN_V22_036_R3_WITH_REPAIRED_IMPORT_CONTEXT"
    elif repair_row["repair_status"] == "PACKAGE_INSTALL_OR_REPAIR_REQUIRED":
        label = "PACKAGE_REINSTALL_OR_REPAIR_REQUIRED"
    elif repair_row["repair_status"] == "MANUAL_PERMISSION_REPAIR_REQUIRED":
        label = "MANUAL_PERMISSION_REPAIR_REQUIRED_BEFORE_R3"
    else:
        label = "FALLBACK_TO_MANUAL_UNDERLYING_SPOT_GATE_RESEARCH_ONLY"
    return pd.DataFrame([{"exact_permission_path_found": exact, "package_static_discovered": static, "package_source_scan_completed": scan_done, "supported_log_env_var_found": env_found, "import_experiment_succeeded": exp_ok, "selected_repair_strategy": repair_row["repair_strategy"], "v22_036_r3_rerun_recommended": label == "RERUN_V22_036_R3_WITH_REPAIRED_IMPORT_CONTEXT", "manual_permission_repair_required": label == "MANUAL_PERMISSION_REPAIR_REQUIRED_BEFORE_R3", "package_reinstall_required": label == "PACKAGE_REINSTALL_OR_REPAIR_REQUIRED", "fallback_to_manual_spot_gate_allowed_next_step": label in {"FALLBACK_TO_MANUAL_UNDERLYING_SPOT_GATE_RESEARCH_ONLY", "MANUAL_PERMISSION_REPAIR_REQUIRED_BEFORE_R3", "PACKAGE_REINSTALL_OR_REPAIR_REQUIRED"}, "read_only_underlying_quote_refresh_allowed_next_step": label == "RERUN_V22_036_R3_WITH_REPAIRED_IMPORT_CONTEXT", "option_chain_refresh_allowed": False, "option_quote_refresh_allowed": False, "iv_greeks_calculation_allowed": False, "full_option_candidate_generation_allowed": False, "broker_action_allowed": False, "official_adoption_allowed": False, "trade_order_allowed": False, "final_policy_label": label}])


def write_summary_report(output_dir: Path, summary: dict[str, Any]) -> None:
    (output_dir / "v22_036_r3b_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    keys = ["final_status", "final_decision", "prior_failure_type", "exact_permission_path_found", "moomoo_static_spec_found", "futu_static_spec_found", "package_source_scan_completed", "supported_log_env_var_found", "import_experiment_attempted", "import_experiment_succeeded", "successful_experiment_name", "selected_repair_strategy", "v22_036_r3_rerun_recommended", "manual_permission_repair_required", "package_reinstall_required", "fallback_to_manual_spot_gate_allowed_next_step", "read_only_underlying_quote_refresh_allowed_next_step", "option_chain_refresh_allowed", "option_quote_refresh_allowed", "iv_greeks_calculation_allowed", "full_option_candidate_generation_allowed", "broker_action_allowed", "official_adoption_allowed", "trade_order_allowed"]
    (output_dir / "V22.036_R3B_moomoo_futu_exact_permission_path_and_import_time_log_config_audit_research_only_report.txt").write_text("\n".join(["V22.036_R3B Moomoo/Futu Exact Permission Path And Import-Time Log Config Audit"] + [f"{k}={summary[k]}" for k in keys]) + "\n", encoding="utf-8")


def run(repo_root: Path, output_dir: Path | None = None, execute: bool = False) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    default = (repo_root / OUT_REL).resolve()
    output_dir = (output_dir or default).resolve()
    if output_dir != default and default not in output_dir.parents:
        raise ValueError(f"OutputDir must be under {default}")
    output_dir.mkdir(parents=True, exist_ok=True)
    input_found = (repo_root / V22_036_R3A_DIR).exists()
    errors = read_r3a_errors(repo_root)
    discovery = pd.DataFrame([static_package_discovery("moomoo"), static_package_discovery("futu")])
    scan = source_scan(discovery)
    fallback_dir = output_dir / "provider_logs"
    fallback_dir.mkdir(parents=True, exist_ok=True)
    recon = reconstruct_paths(output_dir, errors, scan)
    env_audit = env_support(scan, str(fallback_dir))
    matrix = import_experiment_matrix(output_dir, fallback_dir, env_audit, execute)
    repair = repair_wrapper(matrix, fallback_dir)
    policy = next_step_policy(errors, discovery, scan, env_audit, matrix, repair, input_found)
    label = policy.iloc[0]["final_policy_label"]
    if not input_found:
        final_status, final_decision = FAIL_INPUT, FALLBACK_DECISION
    elif label == "RERUN_V22_036_R3_WITH_REPAIRED_IMPORT_CONTEXT":
        final_status, final_decision = PASS_READY, READY_DECISION
    elif label == "PACKAGE_REINSTALL_OR_REPAIR_REQUIRED":
        final_status, final_decision = WARN_REINSTALL, MANUAL_DECISION
    elif label == "MANUAL_PERMISSION_REPAIR_REQUIRED_BEFORE_R3":
        final_status, final_decision = WARN_MANUAL, MANUAL_DECISION
    else:
        final_status, final_decision = WARN_FALLBACK, FALLBACK_DECISION
    moomoo = discovery[discovery["package_name"] == "moomoo"].iloc[0]
    futu = discovery[discovery["package_name"] == "futu"].iloc[0]
    successful = matrix[matrix["import_succeeded"] == True]
    summary = {"module_id": MODULE_ID, "module_name": MODULE_NAME, "final_status": final_status, "final_decision": final_decision, "input_v22_036_r3a_dir": str(repo_root / V22_036_R3A_DIR), "input_v22_036_r3_dir": str(repo_root / V22_036_R3_DIR), "discovered_input_file_count": len(list((repo_root / V22_036_R3A_DIR).glob("*"))) if input_found else 0, "prior_final_status": "", "prior_failure_type": next((x for x in ["OPEND_LOG_PATH_PERMISSION_ERROR", "MOOMOO_PACKAGE_IMPORT_PERMISSION_ERROR", "MOOMOO_PACKAGE_NOT_INSTALLED"] if x in errors["inferred_failure_type"].to_string() if "inferred_failure_type" in errors.columns), "UNKNOWN_PROVIDER_FAILURE") if "inferred_failure_type" in errors.columns else "UNKNOWN_PROVIDER_FAILURE", "initial_permission_error_type": next((x for x in errors.get("error_type", pd.Series(dtype=str)).tolist() if x), "",), "initial_permission_error_message": next((x for x in errors.get("error_message", pd.Series(dtype=str)).tolist() if x), "",), "exact_permission_path_found": bool(errors.get("exact_permission_path_found", pd.Series(dtype=bool)).any()), "extracted_permission_paths": ";".join([x for x in errors.get("extracted_permission_denied_paths", pd.Series(dtype=str)).tolist() if x]), "moomoo_static_spec_found": bool(moomoo["spec_found"]), "moomoo_package_dir": moomoo["package_dir"], "futu_static_spec_found": bool(futu["spec_found"]), "futu_package_dir": futu["package_dir"], "package_source_scan_completed": not scan.empty, "supported_log_env_var_found": bool(env_audit["referenced_in_package_source"].any()), "supported_log_env_vars": ";".join(env_audit[env_audit["referenced_in_package_source"] == True]["env_var_name"].tolist()), "fallback_log_dir": str(fallback_dir), "import_experiment_attempted": execute, "import_experiment_succeeded": bool(policy.iloc[0]["import_experiment_succeeded"]), "successful_experiment_name": successful.iloc[0]["experiment_name"] if not successful.empty else "", "selected_repair_strategy": repair.iloc[0]["repair_strategy"], "recommended_powershell_prefix": repair.iloc[0]["recommended_powershell_prefix"], "recommended_working_directory": repair.iloc[0]["recommended_working_directory"], "manual_permission_target_path": repair.iloc[0]["manual_permission_target_path"], "v22_036_r3_rerun_recommended": bool(policy.iloc[0]["v22_036_r3_rerun_recommended"]), "manual_permission_repair_required": bool(policy.iloc[0]["manual_permission_repair_required"]), "package_reinstall_required": bool(policy.iloc[0]["package_reinstall_required"]), "fallback_to_manual_spot_gate_allowed_next_step": bool(policy.iloc[0]["fallback_to_manual_spot_gate_allowed_next_step"]), "read_only_underlying_quote_refresh_allowed_next_step": bool(policy.iloc[0]["read_only_underlying_quote_refresh_allowed_next_step"]), "option_chain_refresh_allowed": False, "option_quote_refresh_allowed": False, "iv_greeks_calculation_allowed": False, "full_option_candidate_generation_allowed": False, "broker_action_allowed": False, "official_adoption_allowed": False, "trade_order_allowed": False}
    errors.to_csv(output_dir / "moomoo_r3a_error_traceback_extraction_audit.csv", index=False, lineterminator="\n")
    discovery.to_csv(output_dir / "moomoo_futu_static_package_discovery_audit.csv", index=False, lineterminator="\n")
    scan.to_csv(output_dir / "moomoo_futu_static_log_config_source_scan_audit.csv", index=False, lineterminator="\n")
    recon.to_csv(output_dir / "moomoo_futu_permission_path_candidate_reconstruction_audit.csv", index=False, lineterminator="\n")
    env_audit.to_csv(output_dir / "moomoo_futu_env_var_support_audit.csv", index=False, lineterminator="\n")
    matrix.to_csv(output_dir / "moomoo_futu_process_local_import_experiment_matrix.csv", index=False, lineterminator="\n")
    repair.to_csv(output_dir / "moomoo_futu_safe_repair_wrapper_proposal.csv", index=False, lineterminator="\n")
    policy.to_csv(output_dir / "moomoo_futu_import_permission_next_step_policy.csv", index=False, lineterminator="\n")
    write_summary_report(output_dir, summary)
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
    print(f"summary_path={(args.output_dir or (args.repo_root / OUT_REL)) / 'v22_036_r3b_summary.json'}")
    print("full_option_candidate_generation_allowed=False")
    print("broker_action_allowed=False")
    print("official_adoption_allowed=False")
    print("trade_order_allowed=False")
    return 1 if summary["final_status"] == FAIL_INPUT else 0


if __name__ == "__main__":
    raise SystemExit(main())
