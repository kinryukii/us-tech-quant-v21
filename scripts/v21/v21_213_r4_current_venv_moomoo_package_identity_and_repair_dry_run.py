#!/usr/bin/env python
"""V21.213 R4 current .venv Moomoo package identity dry-run repair plan.

Research-only. Inspects package metadata/import behavior and writes candidate
manual repair commands. It never installs, uninstalls, connects to OpenD, or
performs broker/adoption actions.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path(r"D:\us-tech-quant")
STAGE = "V21.213_R4_CURRENT_VENV_MOOMOO_PACKAGE_IDENTITY_AND_REPAIR_DRY_RUN"
OUT_REL = Path("outputs/v21/V21.213_R4_CURRENT_VENV_MOOMOO_PACKAGE_IDENTITY_AND_REPAIR_DRY_RUN")
APPROVAL_PHRASE = "APPROVE_V21_213_R5_INSTALL_MOOMOO_IN_CURRENT_VENV"
DIST_NAMES = ["moomoo", "moomoo-api", "moomoo_api", "futu", "futu-api", "futu_api"]
PROTECTED_REQUIRED = [
    ".venv",
    ".venv_moomoo_py312",
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
    "outputs/v21/V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY",
    "outputs/v21/V21.213_R2_MOOMOO_ALT_ENV_REFERENCE_RESOLUTION_AUDIT",
    "outputs/v21/V21.213_R3_CURRENT_VENV_MOOMOO_IMPORT_FAILURE_DIAGNOSIS_AND_REPAIR_PLAN",
]
DIST_FIELDS = ["distribution_name", "found", "version", "package_location", "top_level", "requires_python", "direct_url"]
IMPORT_FIELDS = ["import_name", "import_ok", "version_attr", "exception_type", "exception_message", "traceback_tail"]
USAGE_FIELDS = ["file", "line_number", "import_style", "runtime_relevant_flag", "current_chain_relevant_flag", "rationale"]
PLAN_FIELDS = ["command", "selected_candidate_package", "package_install_allowed_in_this_run", "package_uninstall_allowed_in_this_run", "required_manual_approval_phrase", "rationale"]
GATE_FIELDS = ["alt_venv_retirement_allowed_now", "blocker", "rationale"]
PRESENCE_FIELDS = ["protected_key", "expected_path", "exact_exists", "alias_discovery_attempted", "alias_candidate_count", "resolved_exists", "resolved_protected_path", "resolution_method", "warning_reason"]


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


def run_cmd(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as exc:
        return 999, "", f"{type(exc).__name__}: {exc}"


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


def distribution_metadata(root: Path) -> tuple[list[dict[str, Any]], str]:
    py = root / ".venv/Scripts/python.exe"
    code = (
        "import json, importlib.metadata as md\n"
        f"names={DIST_NAMES!r}\n"
        "rows=[]\n"
        "for name in names:\n"
        " try:\n"
        "  dist=md.distribution(name); meta=dist.metadata\n"
        "  top=''; direct=''\n"
        "  try: top=dist.read_text('top_level.txt') or ''\n"
        "  except Exception: top=''\n"
        "  try: direct=dist.read_text('direct_url.json') or ''\n"
        "  except Exception: direct=''\n"
        "  rows.append({'distribution_name': name,'found': True,'version': dist.version,'package_location': str(dist.locate_file('')),'top_level': top.strip().replace('\\n','|'),'requires_python': meta.get('Requires-Python',''),'direct_url': direct.strip()})\n"
        " except Exception:\n"
        "  rows.append({'distribution_name': name,'found': False,'version': '', 'package_location': '', 'top_level': '', 'requires_python': '', 'direct_url': ''})\n"
        "print(json.dumps({'rows': rows}))\n"
    )
    if not py.exists():
        return ([{"distribution_name": name, "found": False, "version": "", "package_location": "", "top_level": "", "requires_python": "", "direct_url": ""} for name in DIST_NAMES], "")
    rc, out, err = run_cmd([str(py), "-c", code])
    try:
        payload = json.loads(out.splitlines()[-1])
        return payload["rows"], python_version(root)
    except Exception:
        return ([{"distribution_name": name, "found": False, "version": "", "package_location": "", "top_level": "", "requires_python": "", "direct_url": err} for name in DIST_NAMES], python_version(root))


def python_version(root: Path) -> str:
    py = root / ".venv/Scripts/python.exe"
    if not py.exists():
        return ""
    rc, out, err = run_cmd([str(py), "-c", "import sys; print(sys.version.split()[0])"])
    return out.strip() if rc == 0 else ""


def import_checks(root: Path) -> list[dict[str, Any]]:
    py = root / ".venv/Scripts/python.exe"
    rows = []
    for name in ["moomoo", "moomoo_api", "futu"]:
        row = {"import_name": name, "import_ok": False, "version_attr": "", "exception_type": "", "exception_message": "", "traceback_tail": ""}
        if not py.exists():
            row["exception_type"] = "PythonMissing"
            row["exception_message"] = "python missing"
            rows.append(row)
            continue
        code = (
            "import json,traceback\n"
            f"name={name!r}\n"
            "try:\n"
            " m=__import__(name)\n"
            " print(json.dumps({'ok': True, 'version': getattr(m,'__version__','')}))\n"
            "except Exception as e:\n"
            " print(json.dumps({'ok': False, 'exception_type': type(e).__name__, 'exception_message': str(e), 'traceback_tail': traceback.format_exc().splitlines()[-8:]}))\n"
        )
        _rc, out, err = run_cmd([str(py), "-c", code])
        try:
            payload = json.loads((out or "{}").splitlines()[-1])
            row.update({
                "import_ok": bool(payload.get("ok")),
                "version_attr": payload.get("version", ""),
                "exception_type": payload.get("exception_type", ""),
                "exception_message": payload.get("exception_message", ""),
                "traceback_tail": " | ".join(payload.get("traceback_tail", [])),
            })
        except Exception:
            row["exception_type"] = "ImportCheckFailed"
            row["exception_message"] = err or out
        rows.append(row)
    return rows


def skip_usage_file(path: Path, root: Path) -> bool:
    r = rel(path, root).lower()
    return r.startswith(".venv/") or r.startswith(".venv_moomoo_py312/") or r.startswith("archive/") or (r.startswith("outputs/") and path.suffix.lower() in {".csv", ".parquet", ".zip", ".bin"})


def project_usage(root: Path) -> list[dict[str, Any]]:
    patterns = [
        ("import moomoo_api", "import_moomoo_api"),
        ("from moomoo_api import", "from_moomoo_api"),
        ("import moomoo", "import_moomoo"),
        ("from moomoo import", "from_moomoo"),
        ("import futu", "import_futu"),
        ("from futu import", "from_futu"),
    ]
    rows = []
    for file in iter_files(root):
        if skip_usage_file(file, root) or file.suffix.lower() not in {".py", ".ps1", ".txt", ".md", ".json", ".yaml", ".yml", ".toml"}:
            continue
        try:
            lines = file.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines, start=1):
            lower = line.lower()
            for text, style in patterns:
                if text in lower:
                    r = rel(file, root)
                    rows.append({
                        "file": r,
                        "line_number": idx,
                        "import_style": style,
                        "runtime_relevant_flag": r.startswith("scripts/") and not Path(r).name.startswith("test_"),
                        "current_chain_relevant_flag": any(token in r.lower() for token in ["v21_197", "v21_199", "v21_201", "run_daily"]),
                        "rationale": line.strip()[:240],
                    })
    return rows


def classify_repair(dists: list[dict[str, Any]], imports: list[dict[str, Any]], usage: list[dict[str, Any]], py_ver: str) -> tuple[str, str, str]:
    found = {row["distribution_name"]: row for row in dists if str_bool(row["found"])}
    imp = {row["import_name"]: row for row in imports}
    if str_bool(imp["moomoo"]["import_ok"]):
        return "IMPORT_OK", "MANUAL_REVIEW_REQUIRED", ""
    if not found:
        return "DIST_NOT_INSTALLED", "INSTALL_CORRECT_MOOMOO_DIST_AFTER_MANUAL_APPROVAL", ""
    if ("moomoo-api" in found or "moomoo_api" in found) and not str_bool(imp["moomoo"]["import_ok"]):
        if str_bool(imp["moomoo_api"]["import_ok"]):
            return "DIST_INSTALLED_BUT_TOP_LEVEL_IMPORT_MISMATCH", "ADD_IMPORT_COMPATIBILITY_SHIM_AFTER_MANUAL_APPROVAL", "moomoo_api import works but project expects moomoo."
        return "CURRENT_VENV_PACKAGE_STATE_INCONSISTENT", "REINSTALL_EXISTING_MOOMOO_API_DIST_AFTER_MANUAL_APPROVAL", "moomoo-api/moomoo_api distribution exists but moomoo import fails."
    if any(row["import_style"] in {"import_moomoo", "from_moomoo"} for row in usage) and ("moomoo" not in found):
        return "PROJECT_IMPORT_STYLE_MISMATCH", "INSTALL_CORRECT_MOOMOO_DIST_AFTER_MANUAL_APPROVAL", "Project imports moomoo but distribution metadata does not contain moomoo."
    if py_ver.startswith("3.14"):
        return "PYTHON_VERSION_COMPATIBILITY_SUSPECT", "PIN_COMPATIBLE_PACKAGE_VERSION_AFTER_MANUAL_APPROVAL", "Current Python is 3.14; package compatibility may be incomplete."
    return "UNKNOWN_REPAIR_NEEDED", "MANUAL_REVIEW_REQUIRED", ""


def selected_package(diagnosis: str, dists: list[dict[str, Any]], usage: list[dict[str, Any]]) -> str:
    found = {row["distribution_name"] for row in dists if str_bool(row["found"])}
    if diagnosis in {"DIST_INSTALLED_BUT_TOP_LEVEL_IMPORT_MISMATCH", "CURRENT_VENV_PACKAGE_STATE_INCONSISTENT"}:
        return "moomoo-api" if "moomoo-api" in found else ("moomoo_api" if "moomoo_api" in found else "")
    if diagnosis in {"DIST_NOT_INSTALLED", "PROJECT_IMPORT_STYLE_MISMATCH"} and any(row["import_style"] in {"import_moomoo", "from_moomoo"} for row in usage):
        return "moomoo"
    if diagnosis == "PYTHON_VERSION_COMPATIBILITY_SUSPECT":
        return "moomoo-api" if "moomoo-api" in found else ""
    return ""


def command_plan(root: Path, package: str) -> list[dict[str, Any]]:
    py = r".\.venv\Scripts\python.exe"
    commands = [
        f"{py} -m pip show moomoo",
        f"{py} -m pip show moomoo-api",
        f"{py} -m pip show moomoo_api",
    ]
    if package:
        commands.append(f"{py} -m pip install {package}")
    return [{
        "command": cmd,
        "selected_candidate_package": package,
        "package_install_allowed_in_this_run": False,
        "package_uninstall_allowed_in_this_run": False,
        "required_manual_approval_phrase": APPROVAL_PHRASE,
        "rationale": "Dry-run command plan only; command was not executed.",
    } for cmd in commands]


def policy_flags() -> dict[str, bool]:
    return {
        "research_only": True,
        "audit_only": True,
        "dry_run": True,
        "mutation_allowed": False,
        "package_install_performed": False,
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
        f"diagnosed_repair_class={summary['diagnosed_repair_class']}",
        f"recommended_repair_action={summary['recommended_repair_action']}",
        f"selected_candidate_package={summary['selected_candidate_package']}",
        "package_install_allowed_in_this_run=false",
        "moomoo_broker_connection_performed=false",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(repo_root: Path = DEFAULT_ROOT, out_dir: Path | None = None, simulate_exception: bool = False) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if simulate_exception:
            raise RuntimeError("simulated V21.213 R4 failure")
        presence = protected_presence(root)
        missing = [row for row in presence if not str_bool(row["resolved_exists"])]
        dists, py_ver = distribution_metadata(root)
        imports = import_checks(root)
        usage = project_usage(root)
        diagnosis, action, rationale = classify_repair(dists, imports, usage, py_ver)
        package = selected_package(diagnosis, dists, usage)
        imp = {row["import_name"]: row for row in imports}
        found = {row["distribution_name"]: row for row in dists if str_bool(row["found"])}
        gate = {"alt_venv_retirement_allowed_now": False, "blocker": "" if str_bool(imp["moomoo"]["import_ok"]) else "CURRENT_VENV_MOOMOO_IMPORT_NOT_OK", "rationale": "Retirement remains blocked unless current moomoo import passes and later gate approves."}
        if missing:
            final_status = "FAIL_V21_213_R4_PROTECTED_PATH_MISSING"
            final_decision = "CURRENT_VENV_MOOMOO_REPAIR_DRY_RUN_FAILED_PROTECTED_PATH_MISSING"
        elif str_bool(imp["moomoo"]["import_ok"]):
            final_status = "PASS_V21_213_R4_CURRENT_VENV_MOOMOO_IMPORT_ALREADY_OK"
            final_decision = "CURRENT_VENV_MOOMOO_IMPORT_OK_ALT_ENV_RETIREMENT_CAN_CONTINUE"
        else:
            final_status = "WARN_V21_213_R4_MOOMOO_REPAIR_DRY_RUN_READY"
            final_decision = "CURRENT_VENV_MOOMOO_REPAIR_DRY_RUN_READY_MANUAL_APPROVAL_REQUIRED"
        summary = {
            "stage": STAGE,
            "current_venv_python_version": py_ver,
            "current_venv_moomoo_import_ok": str_bool(imp["moomoo"]["import_ok"]),
            "current_venv_moomoo_api_import_ok": str_bool(imp["moomoo_api"]["import_ok"]),
            "current_venv_futu_import_ok": str_bool(imp["futu"]["import_ok"]),
            "moomoo_dist_found": "moomoo" in found,
            "moomoo_api_dist_found": "moomoo-api" in found or "moomoo_api" in found,
            "futu_dist_found": "futu" in found or "futu-api" in found or "futu_api" in found,
            "project_import_moomoo_count": sum(1 for row in usage if row["import_style"] in {"import_moomoo", "from_moomoo"}),
            "project_import_moomoo_api_count": sum(1 for row in usage if row["import_style"] in {"import_moomoo_api", "from_moomoo_api"}),
            "project_import_futu_count": sum(1 for row in usage if row["import_style"] in {"import_futu", "from_futu"}),
            "diagnosed_repair_class": diagnosis,
            "recommended_repair_action": action,
            "selected_candidate_package": package,
            "package_install_allowed_in_this_run": False,
            "required_manual_approval_phrase": APPROVAL_PHRASE,
            "alt_venv_retirement_allowed_now": False,
            "protected_path_missing_count": len(missing),
            "final_status": final_status,
            "final_decision": final_decision,
            **policy_flags(),
        }
        write_csv(output / "current_venv_distribution_metadata_check.csv", dists, DIST_FIELDS)
        write_csv(output / "current_venv_top_level_import_check.csv", imports, IMPORT_FIELDS)
        write_csv(output / "project_moomoo_import_usage_audit.csv", usage, USAGE_FIELDS)
        write_csv(output / "moomoo_repair_command_dry_run_plan.csv", command_plan(root, package), PLAN_FIELDS)
        write_csv(output / "alt_venv_retirement_gate_status.csv", [gate], GATE_FIELDS)
        write_csv(output / "protected_path_presence_check.csv", presence, PRESENCE_FIELDS)
        write_csv(output / "manual_approval_checklist.csv", [{"required_manual_approval_phrase": APPROVAL_PHRASE, "package_install_allowed_in_this_run": False, "package_uninstall_allowed_in_this_run": False, "rationale": "Manual approval required for any future install."}], ["required_manual_approval_phrase", "package_install_allowed_in_this_run", "package_uninstall_allowed_in_this_run", "rationale"])
        write_json(output / "v21_213_r4_summary.json", summary)
        write_report(output / "V21.213_R4_current_venv_moomoo_package_identity_and_repair_report.txt", summary)
    except Exception as exc:
        summary = {"stage": STAGE, "final_status": "FAIL_V21_213_R4_REPAIR_DRY_RUN_EXCEPTION", "final_decision": "CURRENT_VENV_MOOMOO_REPAIR_DRY_RUN_FAILED", "error_type": type(exc).__name__, "error_message": str(exc), **policy_flags()}
        write_json(output / "v21_213_r4_summary.json", summary)
        (output / "V21.213_R4_current_venv_moomoo_package_identity_and_repair_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\nerror={summary['error_type']}: {summary['error_message']}\n", encoding="utf-8")
    for key in ["final_status", "final_decision", "diagnosed_repair_class", "recommended_repair_action", "selected_candidate_package", "package_install_performed", "broker_action_allowed"]:
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
