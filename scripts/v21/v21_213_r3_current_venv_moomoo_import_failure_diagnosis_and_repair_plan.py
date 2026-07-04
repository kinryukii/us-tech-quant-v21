#!/usr/bin/env python
"""V21.213 R3 current .venv Moomoo import failure diagnosis.

Research-only repair-plan stage. It performs harmless Python/pip/import checks
only. It does not install packages, connect to OpenD, delete environments, or
perform broker/adoption actions.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path(r"D:\us-tech-quant")
STAGE = "V21.213_R3_CURRENT_VENV_MOOMOO_IMPORT_FAILURE_DIAGNOSIS_AND_REPAIR_PLAN"
OUT_REL = Path("outputs/v21/V21.213_R3_CURRENT_VENV_MOOMOO_IMPORT_FAILURE_DIAGNOSIS_AND_REPAIR_PLAN")
PROTECTED_REQUIRED = [
    ".venv",
    ".venv_moomoo_py312",
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
    "outputs/v21/V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY",
    "outputs/v21/V21.213_R2_MOOMOO_ALT_ENV_REFERENCE_RESOLUTION_AUDIT",
]
PY_CHECK_FIELDS = [
    "venv_path", "venv_exists", "python_executable", "python_exists", "sys_executable",
    "python_version", "sys_path_short_summary", "site_packages_paths", "pip_available",
    "pip_version_output",
]
IMPORT_FIELDS = ["env_name", "python_executable", "import_ok", "version", "exception_type", "exception_message", "traceback_tail"]
PIP_FIELDS = ["pip_show_found", "pip_show_output", "pip_freeze_filtered"]
ALT_FIELDS = IMPORT_FIELDS + ["alt_venv_exists", "alt_venv_python_exists"]
REPAIR_FIELDS = ["diagnosed_root_cause", "recommended_repair_action", "manual_approval_required", "rationale"]
PRESENCE_FIELDS = ["protected_key", "expected_path", "exact_exists", "alias_discovery_attempted", "alias_candidate_count", "resolved_exists", "resolved_protected_path", "resolution_method", "warning_reason"]
GATE_FIELDS = ["alt_venv_retirement_allowed_now", "alt_venv_retirement_blocker", "rationale"]


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/")


def str_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


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


def run_cmd(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as exc:
        return 999, "", f"{type(exc).__name__}: {exc}"


def python_check(root: Path, env_name: str) -> dict[str, Any]:
    env = root / env_name
    py = env / "Scripts/python.exe"
    row = {
        "venv_path": env_name,
        "venv_exists": env.exists(),
        "python_executable": str(py),
        "python_exists": py.exists(),
        "sys_executable": "",
        "python_version": "",
        "sys_path_short_summary": "",
        "site_packages_paths": "",
        "pip_available": False,
        "pip_version_output": "",
    }
    if not py.exists():
        return row
    code = (
        "import json,sys,site\n"
        "paths=[p for p in sys.path if 'site-packages' in p.lower()]\n"
        "print(json.dumps({'sys_executable': sys.executable, 'python_version': sys.version.split()[0], "
        "'sys_path_short_summary': sys.path[:5], 'site_packages_paths': paths}))"
    )
    rc, out, err = run_cmd([str(py), "-c", code])
    if rc == 0 and out:
        try:
            payload = json.loads(out.splitlines()[-1])
            row.update({
                "sys_executable": payload.get("sys_executable", ""),
                "python_version": payload.get("python_version", ""),
                "sys_path_short_summary": "|".join(payload.get("sys_path_short_summary", [])),
                "site_packages_paths": "|".join(payload.get("site_packages_paths", [])),
            })
        except json.JSONDecodeError:
            row["python_version"] = err
    rc, out, err = run_cmd([str(py), "-m", "pip", "--version"])
    row["pip_available"] = rc == 0
    row["pip_version_output"] = out if out else err
    return row


def import_trace(root: Path, env_name: str) -> dict[str, Any]:
    py = root / env_name / "Scripts/python.exe"
    row = {"env_name": env_name, "python_executable": str(py), "import_ok": False, "version": "", "exception_type": "", "exception_message": "", "traceback_tail": ""}
    if not py.exists():
        row["exception_type"] = "PythonMissing"
        row["exception_message"] = "python executable missing"
        return row
    code = (
        "import json,traceback\n"
        "try:\n"
        " import moomoo\n"
        " print(json.dumps({'ok': True, 'version': getattr(moomoo, '__version__', '')}))\n"
        "except Exception as e:\n"
        " print(json.dumps({'ok': False, 'version': '', 'exception_type': type(e).__name__, 'exception_message': str(e), 'traceback_tail': traceback.format_exc().splitlines()[-8:]}))\n"
    )
    rc, out, err = run_cmd([str(py), "-c", code])
    try:
        payload = json.loads((out or "{}").splitlines()[-1])
        row.update({
            "import_ok": bool(payload.get("ok")),
            "version": payload.get("version", ""),
            "exception_type": payload.get("exception_type", ""),
            "exception_message": payload.get("exception_message", ""),
            "traceback_tail": " | ".join(payload.get("traceback_tail", [])),
        })
    except Exception:
        row["exception_type"] = "ImportTraceFailed"
        row["exception_message"] = err or out
    return row


def pip_moomoo_check(root: Path) -> dict[str, Any]:
    py = root / ".venv/Scripts/python.exe"
    row = {"pip_show_found": False, "pip_show_output": "", "pip_freeze_filtered": ""}
    if not py.exists():
        return row
    rc, out, err = run_cmd([str(py), "-m", "pip", "show", "moomoo"])
    row["pip_show_found"] = rc == 0 and bool(out)
    row["pip_show_output"] = out if out else err
    rc, out, err = run_cmd([str(py), "-m", "pip", "freeze"])
    packages = []
    for line in (out or "").splitlines():
        lower = line.lower()
        if any(token in lower for token in ["moomoo", "futu", "protobuf", "pandas", "requests", "websocket-client"]):
            packages.append(line)
    row["pip_freeze_filtered"] = "|".join(packages)
    return row


def diagnose(current_import: dict[str, Any], alt_import: dict[str, Any], pip_row: dict[str, Any], py_row: dict[str, Any]) -> tuple[str, str, str]:
    if current_import["import_ok"]:
        return "IMPORT_OK", "UPDATE_WRAPPER_TO_USE_CURRENT_VENV_ONLY_AFTER_IMPORT_REPAIR", "Current .venv imports moomoo successfully."
    if not py_row["python_exists"] or not py_row["venv_exists"]:
        return "CURRENT_VENV_CORRUPT_OR_INCOMPLETE", "REBUILD_CURRENT_VENV_AFTER_MANUAL_APPROVAL", "Current .venv or python executable is missing."
    if py_row["sys_executable"] and ".venv" not in str(py_row["sys_executable"]).lower():
        return "WRONG_CURRENT_PYTHON_EXECUTABLE", "MANUAL_REVIEW_REQUIRED", "sys.executable does not appear to be current .venv."
    if not pip_row["pip_show_found"]:
        if alt_import["import_ok"]:
            return "ALT_ENV_HAS_MOOMOO_CURRENT_VENV_MISSING", "INSTALL_MOOMOO_IN_CURRENT_VENV_AFTER_MANUAL_APPROVAL", "Alternate env imports moomoo but current .venv lacks package metadata."
        return "MOOMOO_PACKAGE_NOT_INSTALLED_IN_CURRENT_VENV", "INSTALL_MOOMOO_IN_CURRENT_VENV_AFTER_MANUAL_APPROVAL", "pip show moomoo did not find package in current .venv."
    if current_import["exception_type"] in {"ModuleNotFoundError", "ImportError"}:
        if alt_import["import_ok"]:
            return "ALT_ENV_HAS_MOOMOO_CURRENT_VENV_MISSING", "REINSTALL_MOOMOO_IN_CURRENT_VENV_AFTER_MANUAL_APPROVAL", "Current import fails while alternate import works."
        return "MOOMOO_IMPORT_DEPENDENCY_ERROR", "REINSTALL_MOOMOO_IN_CURRENT_VENV_AFTER_MANUAL_APPROVAL", "Package metadata exists but import failed."
    if not alt_import["import_ok"]:
        return "BOTH_ENVS_IMPORT_FAIL", "MANUAL_REVIEW_REQUIRED", "Both current and alternate env imports failed."
    return "UNKNOWN_IMPORT_FAILURE", "MANUAL_REVIEW_REQUIRED", "Import failed for an unclassified reason."


def policy_flags() -> dict[str, bool]:
    return {
        "research_only": True,
        "audit_only": True,
        "dry_run": True,
        "mutation_allowed": False,
        "package_install_performed": False,
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


def write_report(path: Path, summary: dict[str, Any], rationale: str) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"current_venv_moomoo_import_ok={summary['current_venv_moomoo_import_ok']}",
        f"alt_venv_moomoo_import_ok={summary['alt_venv_moomoo_import_ok']}",
        f"diagnosed_root_cause={summary['diagnosed_root_cause']}",
        f"recommended_repair_action={summary['recommended_repair_action']}",
        "alt_venv_retirement_allowed_now=false",
        "package_install_performed=false",
        "moomoo_broker_connection_performed=false",
        f"rationale={rationale}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(repo_root: Path = DEFAULT_ROOT, out_dir: Path | None = None, simulate_exception: bool = False) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if simulate_exception:
            raise RuntimeError("simulated V21.213 R3 failure")
        presence = protected_presence(root)
        missing = [row for row in presence if not str_bool(row["resolved_exists"])]
        current_py = python_check(root, ".venv")
        current_import = import_trace(root, ".venv")
        pip_row = pip_moomoo_check(root)
        alt_import = import_trace(root, ".venv_moomoo_py312")
        alt_row = {**alt_import, "alt_venv_exists": (root / ".venv_moomoo_py312").exists(), "alt_venv_python_exists": (root / ".venv_moomoo_py312/Scripts/python.exe").exists()}
        cause, action, rationale = diagnose(current_import, alt_import, pip_row, current_py)
        gate = {
            "alt_venv_retirement_allowed_now": False if not current_import["import_ok"] else False,
            "alt_venv_retirement_blocker": "" if current_import["import_ok"] else "CURRENT_VENV_MOOMOO_IMPORT_NOT_OK",
            "rationale": "Alternate env retirement remains blocked unless current .venv Moomoo import is OK and a later deletion gate approves it.",
        }
        if not current_py["venv_exists"] or not alt_row["alt_venv_exists"]:
            final_status = "FAIL_V21_213_R3_CURRENT_OR_ALT_ENV_MISSING"
            final_decision = "CURRENT_OR_ALT_ENV_MISSING_KEEP_ALT_ENV"
        elif missing:
            final_status = "FAIL_V21_213_R3_PROTECTED_PATH_MISSING"
            final_decision = "CURRENT_VENV_MOOMOO_DIAGNOSIS_FAILED_PROTECTED_PATH_MISSING"
        elif current_import["import_ok"]:
            final_status = "PASS_V21_213_R3_CURRENT_VENV_MOOMOO_IMPORT_OK"
            final_decision = "CURRENT_VENV_MOOMOO_IMPORT_OK_ALT_ENV_RETIREMENT_REVIEW_CAN_CONTINUE"
        else:
            final_status = "WARN_V21_213_R3_CURRENT_VENV_MOOMOO_IMPORT_REPAIR_NEEDED"
            final_decision = "CURRENT_VENV_MOOMOO_IMPORT_REPAIR_PLAN_READY_KEEP_ALT_ENV"
        summary = {
            "stage": STAGE,
            "current_venv_exists": current_py["venv_exists"],
            "current_venv_python_exists": current_py["python_exists"],
            "current_venv_python_version": current_py["python_version"],
            "current_venv_moomoo_import_ok": current_import["import_ok"],
            "current_venv_moomoo_version": current_import["version"],
            "current_venv_moomoo_pip_show_found": pip_row["pip_show_found"],
            "alt_venv_exists": alt_row["alt_venv_exists"],
            "alt_venv_python_exists": alt_row["alt_venv_python_exists"],
            "alt_venv_moomoo_import_ok": alt_import["import_ok"],
            "alt_venv_moomoo_version": alt_import["version"],
            "diagnosed_root_cause": cause,
            "recommended_repair_action": action,
            "alt_venv_retirement_allowed_now": False,
            "protected_path_missing_count": len(missing),
            "final_status": final_status,
            "final_decision": final_decision,
            **policy_flags(),
        }
        write_csv(output / "current_venv_python_check.csv", [current_py], PY_CHECK_FIELDS)
        write_csv(output / "current_venv_moomoo_import_trace.csv", [current_import], IMPORT_FIELDS)
        write_csv(output / "current_venv_pip_moomoo_check.csv", [pip_row], PIP_FIELDS)
        write_csv(output / "alternate_venv_moomoo_comparison_check.csv", [alt_row], ALT_FIELDS)
        write_csv(output / "moomoo_repair_plan.csv", [{"diagnosed_root_cause": cause, "recommended_repair_action": action, "manual_approval_required": True, "rationale": rationale}], REPAIR_FIELDS)
        write_csv(output / "protected_path_presence_check.csv", presence, PRESENCE_FIELDS)
        write_csv(output / "alt_venv_retirement_gate_status.csv", [gate], GATE_FIELDS)
        write_json(output / "v21_213_r3_summary.json", summary)
        write_report(output / "V21.213_R3_current_venv_moomoo_import_failure_diagnosis_report.txt", summary, rationale)
    except Exception as exc:
        summary = {
            "stage": STAGE,
            "final_status": "FAIL_V21_213_R3_DIAGNOSIS_EXCEPTION",
            "final_decision": "CURRENT_VENV_MOOMOO_DIAGNOSIS_FAILED",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            **policy_flags(),
        }
        write_json(output / "v21_213_r3_summary.json", summary)
        (output / "V21.213_R3_current_venv_moomoo_import_failure_diagnosis_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\nerror={summary['error_type']}: {summary['error_message']}\n", encoding="utf-8")
    for key in ["final_status", "final_decision", "current_venv_moomoo_import_ok", "alt_venv_moomoo_import_ok", "diagnosed_root_cause", "recommended_repair_action", "package_install_performed", "broker_action_allowed"]:
        if key in summary:
            print(f"{key}={summary[key]}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", default=str(DEFAULT_ROOT))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(Path(args.repo_root))
    return 0 if str(summary["final_status"]).startswith(("PASS", "WARN")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
