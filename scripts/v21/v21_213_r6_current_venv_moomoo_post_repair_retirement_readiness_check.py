#!/usr/bin/env python
"""V21.213 R6 post-repair readiness check for alternate Moomoo venv retirement.

Research-only, audit-only. This stage verifies the current .venv can import
moomoo after R5 and that the alternate .venv_moomoo_py312 has no remaining
active runtime blockers. It never installs, deletes, connects to OpenD, or
performs broker actions.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path(r"D:\us-tech-quant")
STAGE = "V21.213_R6_CURRENT_VENV_MOOMOO_POST_REPAIR_RETIREMENT_READINESS_CHECK"
OUT_REL = Path("outputs/v21/V21.213_R6_CURRENT_VENV_MOOMOO_POST_REPAIR_RETIREMENT_READINESS_CHECK")
R5_SUMMARY_REL = Path("outputs/v21/V21.213_R5_INSTALL_MOOMOO_IN_CURRENT_VENV_AFTER_APPROVAL/v21_213_r5_summary.json")
R2_SUMMARY_REL = Path("outputs/v21/V21.213_R2_MOOMOO_ALT_ENV_REFERENCE_RESOLUTION_AUDIT/v21_213_r2_summary.json")
R2_RESOLUTION_REL = Path("outputs/v21/V21.213_R2_MOOMOO_ALT_ENV_REFERENCE_RESOLUTION_AUDIT/blocking_reference_resolution_audit.csv")
APPROVAL_PHRASE = "APPROVE_V21_214_DELETE_ALTERNATE_VENV_MOOMOO_PY312"
PROTECTED_REQUIRED = [
    ".venv",
    ".venv_moomoo_py312",
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
    "outputs/v21/V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY",
    "outputs/v21/V21.213_R2_MOOMOO_ALT_ENV_REFERENCE_RESOLUTION_AUDIT",
    "outputs/v21/V21.213_R5_INSTALL_MOOMOO_IN_CURRENT_VENV_AFTER_APPROVAL",
]
PRESENCE_FIELDS = ["protected_key", "expected_path", "exact_exists", "alias_discovery_attempted", "alias_candidate_count", "resolved_exists", "resolved_protected_path", "resolution_method", "warning_reason"]
IMPORT_FIELDS = ["python_executable", "python_exists", "import_ok", "moomoo_version", "exception_type", "exception_message", "moomoo_broker_connection_performed"]
READINESS_FIELDS = ["alt_venv_path", "alt_venv_exists", "alt_venv_size_bytes", "active_runtime_blocker_count", "v21_196_current_chain_required_flag", "v21_196_superseded_by_v21_199_r4_or_v21_201_flag", "alt_venv_retirement_ready", "deletion_allowed_in_this_run", "blocker_reasons"]
PRIOR_FIELDS = ["stage", "artifact_path", "exists", "required_condition", "condition_passed", "observed_value", "rationale"]
APPROVAL_FIELDS = ["required_manual_approval_phrase", "deletion_allowed_in_this_run", "manual_approval_required", "rationale"]


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/")


def str_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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


def dir_size(path: Path) -> int:
    total = 0
    for file in iter_files(path):
        try:
            total += file.stat().st_size
        except OSError:
            pass
    return total


def v21_201_alias_is_current_chain(path: Path) -> bool:
    tokens = {"dram", "moomoo", "plan", "r4", "daily"}
    if any(token in path.name.lower() for token in tokens):
        return True
    for file in iter_files(path)[:50]:
        if any(token in file.name.lower() for token in tokens):
            return True
    return False


def protected_alias_candidates(root: Path, stage_id: str) -> list[Path]:
    out21 = root / "outputs/v21"
    if not out21.exists():
        return []
    candidates = []
    for child in out21.iterdir():
        if child.is_dir() and child.name.startswith(stage_id):
            if stage_id != "V21.201" or v21_201_alias_is_current_chain(child):
                candidates.append(child)
    return sorted(candidates, key=lambda p: rel(p, root))


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


def run_cmd(args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def current_moomoo_import_check(root: Path, simulate_import: dict[str, Any] | None = None) -> dict[str, Any]:
    py = root / ".venv/Scripts/python.exe"
    if simulate_import is not None:
        return {
            "python_executable": str(py),
            "python_exists": py.exists(),
            "import_ok": bool(simulate_import.get("import_ok")),
            "moomoo_version": str(simulate_import.get("moomoo_version", "")),
            "exception_type": str(simulate_import.get("exception_type", "")),
            "exception_message": str(simulate_import.get("exception_message", "")),
            "moomoo_broker_connection_performed": False,
        }
    if not py.exists():
        return {"python_executable": str(py), "python_exists": False, "import_ok": False, "moomoo_version": "", "exception_type": "PythonMissing", "exception_message": "current .venv python missing", "moomoo_broker_connection_performed": False}
    code = (
        "import json,traceback\n"
        "try:\n"
        " import moomoo\n"
        " print(json.dumps({'ok': True, 'version': getattr(moomoo, '__version__', 'NO_VERSION_ATTR')}))\n"
        "except Exception as e:\n"
        " print(json.dumps({'ok': False, 'version': '', 'exception_type': type(e).__name__, 'exception_message': str(e), 'traceback_tail': traceback.format_exc().splitlines()[-8:]}))\n"
    )
    rc, out, err = run_cmd([str(py), "-c", code], timeout=60)
    try:
        payload = json.loads((out or "{}").splitlines()[-1])
        return {"python_executable": str(py), "python_exists": True, "import_ok": bool(payload.get("ok")), "moomoo_version": str(payload.get("version", "")), "exception_type": str(payload.get("exception_type", "")), "exception_message": str(payload.get("exception_message", "")), "moomoo_broker_connection_performed": False}
    except Exception:
        return {"python_executable": str(py), "python_exists": True, "import_ok": False, "moomoo_version": "", "exception_type": "ImportCheckFailed", "exception_message": err or out or f"return_code={rc}", "moomoo_broker_connection_performed": False}


def r5_prior_checks(root: Path, r5: dict[str, Any]) -> list[dict[str, Any]]:
    path = root / R5_SUMMARY_REL
    return [
        {"stage": "V21.213_R5", "artifact_path": rel(path, root), "exists": path.exists(), "required_condition": "final_status=PASS_V21_213_R5_CURRENT_VENV_MOOMOO_IMPORT_REPAIRED", "condition_passed": r5.get("final_status") == "PASS_V21_213_R5_CURRENT_VENV_MOOMOO_IMPORT_REPAIRED", "observed_value": r5.get("final_status", ""), "rationale": "R6 only opens retirement readiness after R5 repaired current .venv import."},
        {"stage": "V21.213_R5", "artifact_path": rel(path, root), "exists": path.exists(), "required_condition": "post_install_moomoo_import_ok=true", "condition_passed": str_bool(r5.get("post_install_moomoo_import_ok")), "observed_value": r5.get("post_install_moomoo_import_ok", ""), "rationale": "Current .venv must import moomoo after repair."},
        {"stage": "V21.213_R5", "artifact_path": rel(path, root), "exists": path.exists(), "required_condition": "alt_venv_retirement_allowed_now=true", "condition_passed": str_bool(r5.get("alt_venv_retirement_allowed_now")), "observed_value": r5.get("alt_venv_retirement_allowed_now", ""), "rationale": "R5 gate must explicitly allow retirement review."},
    ]


def active_runtime_blocker_count(root: Path, r2: dict[str, Any]) -> int:
    rows = read_csv(root / R2_RESOLUTION_REL)
    if rows:
        return sum(1 for row in rows if str_bool(row.get("blocks_deletion_after_resolution")))
    return int(r2.get("remaining_blocking_count") or 0)


def policy_flags() -> dict[str, Any]:
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
        f"current_venv_moomoo_import_ok={summary['current_venv_moomoo_import_ok']}",
        f"r5_pass_confirmed={summary['r5_pass_confirmed']}",
        f"active_runtime_blocker_count={summary['active_runtime_blocker_count']}",
        f"alt_venv_retirement_ready={summary['alt_venv_retirement_ready']}",
        f"required_manual_approval_phrase={summary['required_manual_approval_phrase']}",
        "deletion_allowed_in_this_run=false",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_outputs(output: Path, import_row: dict[str, Any], readiness_row: dict[str, Any], prior_rows: list[dict[str, Any]], presence: list[dict[str, Any]], approval_row: dict[str, Any], summary: dict[str, Any]) -> None:
    write_csv(output / "current_venv_moomoo_import_recheck.csv", [import_row], IMPORT_FIELDS)
    write_csv(output / "alt_venv_retirement_readiness_check.csv", [readiness_row], READINESS_FIELDS)
    write_csv(output / "prior_stage_gate_check.csv", prior_rows, PRIOR_FIELDS)
    write_csv(output / "protected_path_presence_check.csv", presence, PRESENCE_FIELDS)
    write_csv(output / "manual_approval_checklist.csv", [approval_row], APPROVAL_FIELDS)
    write_json(output / "v21_213_r6_summary.json", summary)
    write_report(output / "V21.213_R6_current_venv_moomoo_post_repair_retirement_readiness_report.txt", summary)


def run(repo_root: Path = DEFAULT_ROOT, out_dir: Path | None = None, simulate_exception: bool = False, simulate_import: dict[str, Any] | None = None) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if simulate_exception:
            raise RuntimeError("simulated V21.213 R6 failure")
        r5 = read_json(root / R5_SUMMARY_REL)
        r2 = read_json(root / R2_SUMMARY_REL)
        presence = protected_presence(root)
        missing = [row for row in presence if not str_bool(row["resolved_exists"])]
        import_row = current_moomoo_import_check(root, simulate_import)
        prior_rows = r5_prior_checks(root, r5)
        r5_pass = all(str_bool(row["condition_passed"]) for row in prior_rows)
        blockers = active_runtime_blocker_count(root, r2)
        v196_required = str_bool(r2.get("v21_196_current_chain_required_flag"))
        v196_superseded = str_bool(r2.get("v21_196_superseded_by_v21_199_r4_or_v21_201_flag"))
        alt = root / ".venv_moomoo_py312"
        reasons = []
        if not r5_pass:
            reasons.append("R5_PASS_NOT_CONFIRMED")
        if not str_bool(import_row["import_ok"]):
            reasons.append("CURRENT_VENV_MOOMOO_IMPORT_NOT_OK")
        if blockers:
            reasons.append("ACTIVE_RUNTIME_BLOCKERS_REMAIN")
        if v196_required:
            reasons.append("V21_196_STILL_CURRENT_CHAIN_REQUIRED")
        if not v196_superseded:
            reasons.append("V21_196_SUPERSESSION_NOT_CONFIRMED")
        if not alt.exists():
            reasons.append("ALT_VENV_NOT_FOUND")
        ready = not reasons and not missing
        if missing:
            final_status = "FAIL_V21_213_R6_PROTECTED_PATH_MISSING"
            final_decision = "ALT_VENV_RETIREMENT_FAILED_PROTECTED_PATH_MISSING"
        elif ready:
            final_status = "PASS_V21_213_R6_ALT_VENV_RETIREMENT_READY"
            final_decision = "ALT_VENV_RETIREMENT_READY_MANUAL_APPROVAL_REQUIRED"
        else:
            final_status = "WARN_V21_213_R6_ALT_VENV_RETIREMENT_NOT_READY"
            final_decision = "ALT_VENV_RETIREMENT_NOT_READY_KEEP_ALT_ENV"
        readiness_row = {
            "alt_venv_path": rel(alt, root),
            "alt_venv_exists": alt.exists(),
            "alt_venv_size_bytes": dir_size(alt) if alt.exists() else 0,
            "active_runtime_blocker_count": blockers,
            "v21_196_current_chain_required_flag": v196_required,
            "v21_196_superseded_by_v21_199_r4_or_v21_201_flag": v196_superseded,
            "alt_venv_retirement_ready": ready,
            "deletion_allowed_in_this_run": False,
            "blocker_reasons": "|".join(reasons),
        }
        approval_row = {
            "required_manual_approval_phrase": APPROVAL_PHRASE,
            "deletion_allowed_in_this_run": False,
            "manual_approval_required": True,
            "rationale": "R6 is readiness only; deletion requires a future explicit approval stage.",
        }
        summary = {
            "stage": STAGE,
            "current_venv_moomoo_import_ok": str_bool(import_row["import_ok"]),
            "current_venv_moomoo_version": import_row["moomoo_version"],
            "r5_pass_confirmed": r5_pass,
            "alt_venv_exists": alt.exists(),
            "alt_venv_size_bytes": readiness_row["alt_venv_size_bytes"],
            "active_runtime_blocker_count": blockers,
            "v21_196_current_chain_required_flag": v196_required,
            "v21_196_superseded_by_v21_199_r4_or_v21_201_flag": v196_superseded,
            "alt_venv_retirement_ready": ready,
            "deletion_allowed_in_this_run": False,
            "required_manual_approval_phrase": APPROVAL_PHRASE,
            "protected_path_missing_count": len(missing),
            "final_status": final_status,
            "final_decision": final_decision,
            **policy_flags(),
        }
        write_outputs(output, import_row, readiness_row, prior_rows, presence, approval_row, summary)
    except Exception as exc:
        summary = {
            "stage": STAGE,
            "final_status": "FAIL_V21_213_R6_READINESS_EXCEPTION",
            "final_decision": "ALT_VENV_RETIREMENT_FAILED",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            **policy_flags(),
        }
        write_json(output / "v21_213_r6_summary.json", summary)
        (output / "V21.213_R6_current_venv_moomoo_post_repair_retirement_readiness_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\nerror={summary['error_type']}: {summary['error_message']}\n", encoding="utf-8")
    for key in ["final_status", "final_decision", "current_venv_moomoo_import_ok", "alt_venv_retirement_ready", "deletion_allowed_in_this_run", "moomoo_broker_connection_performed"]:
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
