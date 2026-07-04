#!/usr/bin/env python
"""V21.213 R5 install/reinstall moomoo-api in current .venv after approval.

This stage has a hard manual approval gate. When approved, mutation is limited
to current .venv package installation state plus V21.213_R5 artifacts.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path(r"D:\us-tech-quant")
STAGE = "V21.213_R5_INSTALL_MOOMOO_IN_CURRENT_VENV_AFTER_APPROVAL"
OUT_REL = Path("outputs/v21/V21.213_R5_INSTALL_MOOMOO_IN_CURRENT_VENV_AFTER_APPROVAL")
R4_DIST_REL = Path("outputs/v21/V21.213_R4_CURRENT_VENV_MOOMOO_PACKAGE_IDENTITY_AND_REPAIR_DRY_RUN/current_venv_distribution_metadata_check.csv")
APPROVAL_PHRASE = "APPROVE_V21_213_R5_INSTALL_MOOMOO_IN_CURRENT_VENV"
PROTECTED_REQUIRED = [
    ".venv",
    ".venv_moomoo_py312",
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
    "outputs/v21/V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY",
    "outputs/v21/V21.213_R4_CURRENT_VENV_MOOMOO_PACKAGE_IDENTITY_AND_REPAIR_DRY_RUN",
]
APPROVAL_FIELDS = ["required_approval_phrase", "approval_received", "approval_valid", "install_allowed"]
STATE_FIELDS = ["phase", "python_executable", "python_exists", "python_version", "pip_version", "pip_show_moomoo_api", "pip_show_moomoo", "pip_freeze_filtered", "moomoo_import_ok", "moomoo_version", "exception_type", "exception_message"]
INSTALL_FIELDS = ["command", "start_time", "end_time", "return_code", "stdout_tail", "stderr_tail", "install_attempted", "install_success"]
GATE_FIELDS = ["alt_venv_retirement_allowed_now", "alt_venv_retirement_blocker", "rationale"]
PRESENCE_FIELDS = ["protected_key", "expected_path", "exact_exists", "alias_discovery_attempted", "alias_candidate_count", "resolved_exists", "resolved_protected_path", "resolution_method", "warning_reason"]


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/")


def str_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def iter_files(path: Path) -> list[Path]:
    try:
        return sorted([p for p in path.rglob("*") if p.is_file()], key=lambda p: p.as_posix())
    except OSError:
        return []


def protected_alias_candidates(root: Path, stage_id: str) -> list[Path]:
    out21 = root / "outputs/v21"
    if not out21.exists():
        return []
    candidates = []
    for child in out21.iterdir():
        if not child.is_dir() or not child.name.startswith(stage_id):
            continue
        if stage_id == "V21.201" and not v21_201_alias_is_current_chain(child):
            continue
        candidates.append(child)
    return sorted(candidates, key=lambda p: rel(p, root))


def v21_201_alias_is_current_chain(path: Path) -> bool:
    tokens = {"dram", "moomoo", "plan", "r4", "daily"}
    if any(token in path.name.lower() for token in tokens):
        return True
    for file in iter_files(path)[:50]:
        if any(token in file.name.lower() for token in tokens):
            return True
    return False


def protected_presence(root: Path) -> list[dict[str, Any]]:
    rows = []
    for item in PROTECTED_REQUIRED:
        expected = root / item
        exact = expected.exists()
        attempted = False
        candidates: list[Path] = []
        resolved = expected if exact else None
        method = "EXACT_PATH" if exact else "UNRESOLVED"
        warning = "" if exact else "EXPECTED_PATH_MISSING"
        if not exact and item.startswith("outputs/v21/V21."):
            attempted = True
            candidates = protected_alias_candidates(root, Path(item).name.split("_", 1)[0])
            if candidates:
                resolved = max(candidates, key=lambda p: p.stat().st_mtime)
                method = "ALIAS_DISCOVERY_NEWEST_MODIFIED"
                warning = ""
        rows.append({
            "protected_key": Path(item).name,
            "expected_path": item,
            "exact_exists": exact,
            "alias_discovery_attempted": attempted,
            "alias_candidate_count": len(candidates),
            "resolved_exists": bool(resolved and resolved.exists()),
            "resolved_protected_path": rel(resolved, root) if resolved else "",
            "resolution_method": method,
            "warning_reason": warning,
        })
    return rows


def run_cmd(args: list[str], timeout: int = 180) -> tuple[int, str, str]:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def tail(text: str, max_chars: int = 4000) -> str:
    return (text or "")[-max_chars:]


def approval_ok(approval_phrase: str | None) -> bool:
    return (approval_phrase or os.environ.get("V21_213_R5_APPROVAL_PHRASE", "")) == APPROVAL_PHRASE


def python_version(py: Path) -> str:
    if not py.exists():
        return ""
    rc, out, err = run_cmd([str(py), "-c", "import sys; print(sys.version.split()[0])"], timeout=30)
    return out if rc == 0 else ""


def pip_show(py: Path, package: str) -> str:
    if not py.exists():
        return ""
    _rc, out, err = run_cmd([str(py), "-m", "pip", "show", package], timeout=60)
    return out or err


def pip_freeze_filtered(py: Path) -> str:
    if not py.exists():
        return ""
    _rc, out, _err = run_cmd([str(py), "-m", "pip", "freeze"], timeout=90)
    rows = []
    for line in out.splitlines():
        if any(token in line.lower() for token in ["moomoo", "futu", "protobuf", "pandas", "requests", "websocket-client"]):
            rows.append(line)
    return "|".join(rows)


def import_moomoo(py: Path) -> tuple[bool, str, str, str]:
    if not py.exists():
        return False, "", "PythonMissing", "python executable missing"
    code = (
        "import json,traceback\n"
        "try:\n"
        " import moomoo\n"
        " print(json.dumps({'ok': True, 'version': getattr(moomoo, '__version__', 'NO_VERSION_ATTR')}))\n"
        "except Exception as e:\n"
        " print(json.dumps({'ok': False, 'version': '', 'exception_type': type(e).__name__, 'exception_message': str(e), 'traceback_tail': traceback.format_exc().splitlines()[-8:]}))\n"
    )
    _rc, out, err = run_cmd([str(py), "-c", code], timeout=60)
    try:
        payload = json.loads((out or "{}").splitlines()[-1])
        return bool(payload.get("ok")), str(payload.get("version", "")), str(payload.get("exception_type", "")), str(payload.get("exception_message", ""))
    except Exception:
        return False, "", "ImportCheckFailed", err or out


def package_state(root: Path, phase: str) -> dict[str, Any]:
    py = root / ".venv/Scripts/python.exe"
    ok, version, exc_type, exc_msg = import_moomoo(py)
    return {
        "phase": phase,
        "python_executable": str(py),
        "python_exists": py.exists(),
        "python_version": python_version(py),
        "pip_version": run_cmd([str(py), "-m", "pip", "--version"], timeout=30)[1] if py.exists() else "",
        "pip_show_moomoo_api": pip_show(py, "moomoo-api"),
        "pip_show_moomoo": pip_show(py, "moomoo"),
        "pip_freeze_filtered": pip_freeze_filtered(py),
        "moomoo_import_ok": ok,
        "moomoo_version": version,
        "exception_type": exc_type,
        "exception_message": exc_msg,
    }


def selected_version(root: Path) -> tuple[str, str]:
    rows = read_csv(root / R4_DIST_REL)
    for name in ["moomoo-api", "moomoo_api"]:
        for row in rows:
            if row.get("distribution_name") == name and str_bool(row.get("found")) and row.get("version"):
                return "moomoo-api", row["version"]
    return "moomoo-api", ""


def install_command(root: Path, package: str, version: str) -> list[str]:
    py = root / ".venv/Scripts/python.exe"
    spec = f"{package}=={version}" if version else package
    return [str(py), "-m", "pip", "install", "--upgrade", "--force-reinstall", spec]


def policy_flags(approved: bool, install_performed: bool, reinstall_performed: bool) -> dict[str, Any]:
    return {
        "research_only": True,
        "explicit_manual_approval_required": True,
        "explicit_manual_approval_received": approved,
        "mutation_allowed_limited_to_current_venv_package_state": approved,
        "package_install_performed": install_performed,
        "package_reinstall_performed": reinstall_performed,
        "package_uninstall_performed": False,
        "deletion_performed": False,
        "compression_performed": False,
        "archive_movement_performed": False,
        "price_refresh_performed": False,
        "canonical_mutation_performed": False,
        "moomoo_broker_connection_performed": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "protected_outputs_modified": False,
    }


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"explicit_manual_approval_received={summary['explicit_manual_approval_received']}",
        f"install_attempted={summary['install_attempted']}",
        f"install_success={summary['install_success']}",
        f"post_install_moomoo_import_ok={summary['post_install_moomoo_import_ok']}",
        f"alt_venv_retirement_allowed_now={summary['alt_venv_retirement_allowed_now']}",
        "moomoo_broker_connection_performed=false",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def empty_install_log(command: str = "") -> list[dict[str, Any]]:
    return [{"command": command, "start_time": "", "end_time": "", "return_code": "", "stdout_tail": "", "stderr_tail": "", "install_attempted": False, "install_success": False}]


def run(
    repo_root: Path = DEFAULT_ROOT,
    approval_phrase: str | None = None,
    out_dir: Path | None = None,
    simulate_exception: bool = False,
    simulate_install: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    approved = approval_ok(approval_phrase)
    install_performed = False
    reinstall_performed = False
    try:
        if simulate_exception:
            raise RuntimeError("simulated V21.213 R5 failure")
        package, version = selected_version(root)
        command = install_command(root, package, version)
        command_text = " ".join(command)
        approval_row = {"required_approval_phrase": APPROVAL_PHRASE, "approval_received": bool(approval_phrase), "approval_valid": approved, "install_allowed": approved}
        presence = protected_presence(root)
        missing = [row for row in presence if not str_bool(row["resolved_exists"])]
        pre_state = package_state(root, "pre_install")
        install_log = empty_install_log(command_text)
        if not approved:
            summary = {
                "stage": STAGE,
                "explicit_manual_approval_required": True,
                "explicit_manual_approval_received": False,
                "current_venv_python_exists": pre_state["python_exists"],
                "current_venv_python_version": pre_state["python_version"],
                "selected_candidate_package": package,
                "selected_candidate_version": version,
                "install_command": command_text,
                "install_attempted": False,
                "install_success": False,
                "install_return_code": "",
                "pre_install_moomoo_import_ok": pre_state["moomoo_import_ok"],
                "post_install_moomoo_import_ok": False,
                "post_install_moomoo_version": "",
                "alt_venv_retirement_allowed_now": False,
                "alt_venv_retirement_blocker": "MANUAL_APPROVAL_MISSING",
                "protected_path_missing_count": len(missing),
                "final_status": "FAIL_V21_213_R5_MANUAL_APPROVAL_MISSING",
                "final_decision": "MOOMOO_INSTALL_BLOCKED_MANUAL_APPROVAL_MISSING",
                **policy_flags(False, False, False),
            }
            write_outputs(output, approval_row, pre_state, install_log, pre_state, presence, summary)
            return summary
        if missing:
            summary = {
                "stage": STAGE,
                "explicit_manual_approval_required": True,
                "explicit_manual_approval_received": True,
                "current_venv_python_exists": pre_state["python_exists"],
                "current_venv_python_version": pre_state["python_version"],
                "selected_candidate_package": package,
                "selected_candidate_version": version,
                "install_command": command_text,
                "install_attempted": False,
                "install_success": False,
                "install_return_code": "",
                "pre_install_moomoo_import_ok": pre_state["moomoo_import_ok"],
                "post_install_moomoo_import_ok": False,
                "post_install_moomoo_version": "",
                "alt_venv_retirement_allowed_now": False,
                "alt_venv_retirement_blocker": "PROTECTED_PATH_MISSING",
                "protected_path_missing_count": len(missing),
                "final_status": "FAIL_V21_213_R5_PROTECTED_PATH_MISSING",
                "final_decision": "MOOMOO_INSTALL_FAILED_PROTECTED_PATH_MISSING",
                **policy_flags(True, False, False),
            }
            write_outputs(output, approval_row, pre_state, install_log, pre_state, presence, summary)
            return summary
        start = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        if simulate_install is not None:
            rc = int(simulate_install.get("return_code", 0))
            stdout = str(simulate_install.get("stdout", ""))
            stderr = str(simulate_install.get("stderr", ""))
        else:
            rc, stdout, stderr = run_cmd(command, timeout=300)
        end = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        install_performed = True
        reinstall_performed = True
        install_success = rc == 0
        install_log = [{
            "command": command_text,
            "start_time": start,
            "end_time": end,
            "return_code": rc,
            "stdout_tail": tail(stdout),
            "stderr_tail": tail(stderr),
            "install_attempted": True,
            "install_success": install_success,
        }]
        post_state = package_state(root, "post_install")
        if simulate_install and "post_import_ok" in simulate_install:
            post_state["moomoo_import_ok"] = bool(simulate_install["post_import_ok"])
            post_state["moomoo_version"] = str(simulate_install.get("post_version", ""))
        if not install_success:
            final_status = "FAIL_V21_213_R5_INSTALL_COMMAND_FAILED"
            final_decision = "MOOMOO_INSTALL_COMMAND_FAILED_KEEP_ALT_ENV"
        elif post_state["moomoo_import_ok"]:
            final_status = "PASS_V21_213_R5_CURRENT_VENV_MOOMOO_IMPORT_REPAIRED"
            final_decision = "CURRENT_VENV_MOOMOO_IMPORT_REPAIRED_ALT_ENV_RETIREMENT_CAN_CONTINUE"
        else:
            final_status = "WARN_V21_213_R5_INSTALL_COMPLETED_IMPORT_STILL_FAILS"
            final_decision = "CURRENT_VENV_MOOMOO_INSTALL_DONE_IMPORT_STILL_FAILS_KEEP_ALT_ENV"
        alt_allowed = bool(post_state["moomoo_import_ok"])
        summary = {
            "stage": STAGE,
            "explicit_manual_approval_required": True,
            "explicit_manual_approval_received": True,
            "current_venv_python_exists": pre_state["python_exists"],
            "current_venv_python_version": pre_state["python_version"],
            "selected_candidate_package": package,
            "selected_candidate_version": version,
            "install_command": command_text,
            "install_attempted": True,
            "install_success": install_success,
            "install_return_code": rc,
            "pre_install_moomoo_import_ok": pre_state["moomoo_import_ok"],
            "post_install_moomoo_import_ok": post_state["moomoo_import_ok"],
            "post_install_moomoo_version": post_state["moomoo_version"],
            "alt_venv_retirement_allowed_now": alt_allowed,
            "alt_venv_retirement_blocker": "" if alt_allowed else "CURRENT_VENV_MOOMOO_IMPORT_NOT_OK_AFTER_REPAIR",
            "protected_path_missing_count": 0,
            "final_status": final_status,
            "final_decision": final_decision,
            **policy_flags(True, install_performed, reinstall_performed),
        }
        write_outputs(output, approval_row, pre_state, install_log, post_state, presence, summary)
    except Exception as exc:
        summary = {
            "stage": STAGE,
            "final_status": "FAIL_V21_213_R5_INSTALL_EXCEPTION",
            "final_decision": "MOOMOO_INSTALL_FAILED_KEEP_ALT_ENV",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            **policy_flags(approved, install_performed, reinstall_performed),
        }
        write_json(output / "v21_213_r5_summary.json", summary)
        (output / "V21.213_R5_install_moomoo_in_current_venv_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\nerror={summary['error_type']}: {summary['error_message']}\n", encoding="utf-8")
    for key in ["final_status", "final_decision", "install_attempted", "install_success", "post_install_moomoo_import_ok", "package_install_performed", "broker_action_allowed"]:
        if key in summary:
            print(f"{key}={summary[key]}")
    return summary


def write_outputs(output: Path, approval_row: dict[str, Any], pre_state: dict[str, Any], install_log: list[dict[str, Any]], post_state: dict[str, Any], presence: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    gate = {
        "alt_venv_retirement_allowed_now": summary.get("alt_venv_retirement_allowed_now", False),
        "alt_venv_retirement_blocker": summary.get("alt_venv_retirement_blocker", ""),
        "rationale": "Alt env retirement can continue only after current .venv import moomoo succeeds.",
    }
    write_csv(output / "manual_approval_check.csv", [approval_row], APPROVAL_FIELDS)
    write_csv(output / "pre_install_current_venv_package_state.csv", [pre_state], STATE_FIELDS)
    write_csv(output / "install_execution_log.csv", install_log, INSTALL_FIELDS)
    write_csv(output / "post_install_import_check.csv", [post_state], STATE_FIELDS)
    write_csv(output / "post_install_current_venv_package_state.csv", [post_state], STATE_FIELDS)
    write_csv(output / "alt_venv_retirement_gate_status.csv", [gate], GATE_FIELDS)
    write_csv(output / "protected_path_presence_check.csv", presence, PRESENCE_FIELDS)
    write_json(output / "v21_213_r5_summary.json", summary)
    write_report(output / "V21.213_R5_install_moomoo_in_current_venv_report.txt", summary)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", default=str(DEFAULT_ROOT))
    parser.add_argument("--approval-phrase", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(Path(args.repo_root), approval_phrase=args.approval_phrase)
    return 0 if str(summary["final_status"]).startswith(("PASS", "WARN")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
