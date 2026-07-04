#!/usr/bin/env python
"""V21.213 alternate virtualenv retirement dry-run gate from registry.

Audit-only gate for .venv_moomoo_py312. It uses V21.212 artifact_registry.csv as
the source of truth and never deletes, moves, compresses, rewrites, refreshes
prices, mutates canonical files, or performs broker/adoption actions.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path(r"D:\us-tech-quant")
STAGE = "V21.213_ALTERNATE_VENV_RETIREMENT_DRY_RUN_GATE_FROM_REGISTRY"
OUT_REL = Path("outputs/v21/V21.213_ALTERNATE_VENV_RETIREMENT_DRY_RUN_GATE_FROM_REGISTRY")
REGISTRY_REL = Path("outputs/v21/V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY/artifact_registry.csv")
ALT_ENV = ".venv_moomoo_py312"
CURRENT_ENV = ".venv"
APPROVAL_PHRASE = "APPROVE_V21_214_DELETE_ALTERNATE_VENV_MOOMOO_PY312"
REFERENCE_TOKENS = [".venv_moomoo_py312", "venv_moomoo", "moomoo_py312"]
PROTECTED_REQUIRED = [
    ".venv",
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
    "outputs/v21/V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY",
]
PLAN_FIELDS = [
    "path", "exists", "recursive_size_bytes", "file_count", "directory_count", "pyvenv_cfg_exists",
    "pyvenv_cfg_python_version", "scripts_python_exists", "scripts_python_path", "site_packages_exists",
    "site_packages_size_bytes", "latest_modified_time", "earliest_modified_time", "referenced_by_scripts_count",
    "referenced_by_ps1_count", "referenced_by_config_count", "current_project_env_flag",
    "registry_artifact_role", "registry_retention_class", "registry_future_action_allowed",
    "retirement_candidate_flag", "eligible_for_future_deletion", "deletion_allowed_in_this_run",
    "manual_approval_required", "required_manual_approval_phrase", "blocker_reasons", "rationale",
]
MANIFEST_FIELDS = ["relative_file_path", "file_size_bytes", "modified_time", "file_extension"]
REGISTRY_FIELDS = ["artifact_path", "artifact_role", "retention_class", "future_action_allowed", "registry_confirms_alternate_env_review", "blocker_reason"]
CURRENT_FIELDS = ["check_name", "expected", "observed", "check_passed", "rationale"]
PRESENCE_FIELDS = ["protected_key", "expected_path", "exact_exists", "alias_discovery_attempted", "alias_candidate_count", "resolved_exists", "resolved_protected_path", "resolution_method", "warning_reason"]
BLOCKER_FIELDS = ["path", "blocker_type", "blocker_detail"]
CHECKLIST_FIELDS = ["check_item", "required_value", "observed_value", "check_passed"]
REFERENCE_CLASS_FIELDS = [
    "reference_file",
    "line_number",
    "matched_text",
    "surrounding_context_short",
    "reference_category",
    "blocking_reference_flag",
    "classification_reason",
]
BLOCKING_REFERENCE_CLASSES = {"ACTIVE_RUNTIME_REFERENCE", "CONFIGURED_EXECUTION_REFERENCE", "UNKNOWN_REFERENCE"}


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


def iter_dirs(path: Path) -> list[Path]:
    try:
        return sorted([p for p in path.rglob("*") if p.is_dir()], key=lambda p: p.as_posix())
    except OSError:
        return []


def metrics(path: Path) -> tuple[int, int, int, str, str]:
    files = iter_files(path) if path.exists() else []
    dirs = iter_dirs(path) if path.exists() else []
    total = 0
    mtimes = []
    for file in files:
        try:
            stat = file.stat()
            total += stat.st_size
            mtimes.append(stat.st_mtime)
        except OSError:
            continue
    try:
        mtimes.append(path.stat().st_mtime)
    except OSError:
        pass
    if not mtimes:
        return 0, 0, 0, "", ""
    latest = datetime.fromtimestamp(max(mtimes), timezone.utc).replace(microsecond=0).isoformat()
    earliest = datetime.fromtimestamp(min(mtimes), timezone.utc).replace(microsecond=0).isoformat()
    return total, len(files), len(dirs), latest, earliest


def pyvenv_version(path: Path) -> str:
    cfg = path / "pyvenv.cfg"
    if not cfg.exists():
        return ""
    try:
        for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.lower().startswith("version"):
                return line.split("=", 1)[1].strip()
    except OSError:
        return ""
    return ""


def site_packages_size(path: Path) -> tuple[bool, int]:
    found = False
    total = 0
    for candidate in path.rglob("site-packages") if path.exists() else []:
        found = True
        size, _files, _dirs, _latest, _earliest = metrics(candidate)
        total += size
    return found, total


def manifest(path: Path, root: Path) -> list[dict[str, Any]]:
    rows = []
    for file in iter_files(path) if path.exists() else []:
        try:
            stat = file.stat()
        except OSError:
            continue
        rows.append({
            "relative_file_path": rel(file, root),
            "file_size_bytes": stat.st_size,
            "modified_time": datetime.fromtimestamp(stat.st_mtime, timezone.utc).replace(microsecond=0).isoformat(),
            "file_extension": file.suffix.lower(),
        })
    return rows


def registry_row(rows: list[dict[str, str]]) -> dict[str, str]:
    for row in rows:
        if row.get("artifact_path") == ALT_ENV:
            return row
    return {}


def registry_check(row: dict[str, str]) -> tuple[bool, str]:
    if not row:
        return False, "REGISTRY_ROW_MISSING"
    if row.get("artifact_role") != "ALTERNATE_ENVIRONMENT_REVIEW":
        return False, "REGISTRY_ROLE_NOT_ALTERNATE_ENVIRONMENT_REVIEW"
    if row.get("retention_class") != "REVIEW_ALTERNATE_ENV_RETIREMENT":
        return False, "REGISTRY_RETENTION_CLASS_MISMATCH"
    return True, ""


def skip_reference_path(path: Path, root: Path) -> bool:
    r = rel(path, root).lower()
    if r.startswith(".venv/") or r.startswith(".venv_moomoo_py312/"):
        return True
    if r.startswith("archive/") and path.suffix.lower() == ".zip":
        return True
    if r.startswith("outputs/") and path.suffix.lower() in {".csv", ".parquet", ".zip", ".bin", ".pkl"}:
        return True
    return False


def text_file_candidate(path: Path) -> bool:
    if path.suffix.lower() in {".py", ".ps1", ".txt", ".md", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".bat", ".cmd"}:
        return True
    return path.name.lower() in {"dockerfile", "makefile"}


def line_comment_or_doc(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("<!--") or stripped.startswith("*") or stripped.startswith('"""') or stripped.startswith("'''")


def classify_reference(file: Path, root: Path, line: str) -> tuple[str, bool, str]:
    r = rel(file, root).replace("\\", "/")
    lower_path = r.lower()
    lower_line = line.lower()
    invokes_python = "scripts\\python.exe" in lower_line or "scripts/python.exe" in lower_line or "python.exe" in lower_line
    if lower_path.startswith("scripts/v21/test_v21_211") or lower_path.startswith("scripts/v21/test_v21_212") or lower_path.startswith("scripts/v21/test_v21_213"):
        return "TEST_REFERENCE", False, "Reference is inside V21.211/V21.212/V21.213 tests."
    if lower_path.startswith("scripts/v21/v21_211") or lower_path.startswith("scripts/v21/v21_212") or lower_path.startswith("scripts/v21/v21_213"):
        if invokes_python and ("subprocess" in lower_line or "start-process" in lower_line or "&" in lower_line):
            return "ACTIVE_RUNTIME_REFERENCE", True, "Self-audit script appears to invoke alternate environment executable."
        return "SELF_AUDIT_REFERENCE", False, "Reference is inside V21.211/V21.212/V21.213 audit code."
    if lower_path.startswith("outputs/v21/v21.211") or lower_path.startswith("outputs/v21/v21.212") or lower_path.startswith("outputs/v21/v21.213"):
        return "REPORT_OR_REGISTRY_REFERENCE", False, "Reference is inside V21.211/V21.212/V21.213 generated audit artifacts."
    if line_comment_or_doc(line):
        return "COMMENT_OR_DOC_REFERENCE", False, "Reference appears in a comment or documentation line."
    if file.suffix.lower() == ".ps1" and invokes_python:
        return "CONFIGURED_EXECUTION_REFERENCE", True, "PowerShell file invokes alternate environment python."
    if file.suffix.lower() in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"} and invokes_python:
        return "CONFIGURED_EXECUTION_REFERENCE", True, "Configuration file selects alternate environment python."
    if file.suffix.lower() in {".bat", ".cmd"} and invokes_python:
        return "CONFIGURED_EXECUTION_REFERENCE", True, "Launch script selects alternate environment python."
    if file.suffix.lower() == ".py" and invokes_python and "subprocess" in lower_line:
        return "ACTIVE_RUNTIME_REFERENCE", True, "Python script invokes alternate environment python via subprocess."
    if "log" in lower_path or lower_path.endswith(".log"):
        return "HISTORICAL_LOG_REFERENCE", False, "Reference is in a historical log-like file."
    if file.suffix.lower() in {".md", ".txt"}:
        return "COMMENT_OR_DOC_REFERENCE", False, "Reference is in documentation text."
    return "UNKNOWN_REFERENCE", True, "Reference meaning is unclear."


def reference_classification(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for file in iter_files(root):
        if skip_reference_path(file, root) or not text_file_candidate(file):
            continue
        try:
            lines = file.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            lower = line.lower()
            matches = [token for token in REFERENCE_TOKENS if token.lower() in lower]
            if not matches:
                continue
            category, blocking, reason = classify_reference(file, root, line)
            rows.append({
                "reference_file": rel(file, root),
                "line_number": line_number,
                "matched_text": "|".join(matches),
                "surrounding_context_short": line.strip()[:240],
                "reference_category": category,
                "blocking_reference_flag": blocking,
                "classification_reason": reason,
            })
    return rows


def reference_counts(rows: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    seen: dict[str, set[str]] = {"scripts": set(), "ps1": set(), "config": set()}
    for row in rows:
        file = str(row["reference_file"])
        suffix = Path(file).suffix.lower()
        if suffix == ".py":
            seen["scripts"].add(file)
        elif suffix == ".ps1":
            seen["ps1"].add(file)
        else:
            seen["config"].add(file)
    for key, values in seen.items():
        counts[key] = len(values)
    return counts


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


def current_env_checks(root: Path) -> list[dict[str, Any]]:
    current = root / CURRENT_ENV
    python = current / "Scripts/python.exe"
    current_exec = Path(sys.executable).resolve()
    alt = (root / ALT_ENV).resolve()
    return [
        {"check_name": "current_env_exists", "expected": True, "observed": current.exists(), "check_passed": current.exists(), "rationale": ".venv must exist before alternate env retirement."},
        {"check_name": "current_env_python_exists", "expected": True, "observed": python.exists(), "check_passed": python.exists(), "rationale": ".venv/Scripts/python.exe must exist."},
        {"check_name": "alternate_not_current_executable", "expected": True, "observed": not str(current_exec).lower().startswith(str(alt).lower()), "check_passed": not str(current_exec).lower().startswith(str(alt).lower()), "rationale": "Running interpreter must not be inside alternate env."},
    ]


def policy_flags() -> dict[str, bool]:
    return {
        "research_only": True,
        "dry_run": True,
        "audit_only": True,
        "mutation_allowed": False,
        "deletion_performed": False,
        "compression_performed": False,
        "archive_movement_performed": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "protected_outputs_modified": False,
        "canonical_mutation_performed": False,
        "price_refresh_performed": False,
    }


def write_report(path: Path, summary: dict[str, Any], plan: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"alternate_venv_exists={summary['alternate_venv_exists']}",
        f"alternate_venv_size_bytes={summary['alternate_venv_size_bytes']}",
        f"alternate_venv_reference_count={summary['alternate_venv_reference_count']}",
        f"blocking_reference_count={summary.get('blocking_reference_count', 0)}",
        f"nonblocking_reference_count={summary.get('nonblocking_reference_count', 0)}",
        f"eligible_for_future_deletion_count={summary['eligible_for_future_deletion_count']}",
        "deletion_allowed_in_this_run=false",
        f"required_manual_approval_phrase={APPROVAL_PHRASE}",
        f"blocker_reasons={plan.get('blocker_reasons', '')}",
        "research_only=true",
        "dry_run=true",
        "audit_only=true",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(repo_root: Path = DEFAULT_ROOT, registry_csv: Path | None = None, out_dir: Path | None = None, simulate_exception: bool = False) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if simulate_exception:
            raise RuntimeError("simulated V21.213 failure")
        registry_rows = read_csv(registry_csv or (root / REGISTRY_REL))
        registry = registry_row(registry_rows)
        registry_ok, registry_blocker = registry_check(registry)
        alt = root / ALT_ENV
        exists = alt.exists()
        size, files, dirs, latest, earliest = metrics(alt)
        site_exists, site_size = site_packages_size(alt)
        reference_rows = reference_classification(root)
        refs = reference_counts(reference_rows)
        blocking_reference_rows = [row for row in reference_rows if str_bool(row["blocking_reference_flag"])]
        category_counts = Counter(str(row["reference_category"]) for row in reference_rows)
        current_checks = current_env_checks(root)
        presence = protected_presence(root)
        missing_protected = [row for row in presence if not str_bool(row["resolved_exists"])]
        current_ok = all(str_bool(row["check_passed"]) for row in current_checks)
        blockers = []
        if registry_blocker:
            blockers.append(registry_blocker)
        if not exists:
            blockers.append("ALTERNATE_VENV_NOT_FOUND")
        if blocking_reference_rows:
            blockers.append("ALTERNATE_VENV_BLOCKING_REFERENCES_FOUND")
        if not current_ok:
            blockers.append("CURRENT_ENV_SAFETY_CHECK_FAILED")
        if missing_protected:
            blockers.append("PROTECTED_PATH_MISSING")
        eligible = bool(exists and registry_ok and not blocking_reference_rows and current_ok and not missing_protected)
        plan = {
            "path": ALT_ENV,
            "exists": exists,
            "recursive_size_bytes": size,
            "file_count": files,
            "directory_count": dirs,
            "pyvenv_cfg_exists": (alt / "pyvenv.cfg").exists(),
            "pyvenv_cfg_python_version": pyvenv_version(alt),
            "scripts_python_exists": (alt / "Scripts/python.exe").exists(),
            "scripts_python_path": str(alt / "Scripts/python.exe"),
            "site_packages_exists": site_exists,
            "site_packages_size_bytes": site_size,
            "latest_modified_time": latest,
            "earliest_modified_time": earliest,
            "referenced_by_scripts_count": refs["scripts"],
            "referenced_by_ps1_count": refs["ps1"],
            "referenced_by_config_count": refs["config"],
            "current_project_env_flag": False,
            "registry_artifact_role": registry.get("artifact_role", ""),
            "registry_retention_class": registry.get("retention_class", ""),
            "registry_future_action_allowed": registry.get("future_action_allowed", ""),
            "retirement_candidate_flag": registry_ok,
            "eligible_for_future_deletion": eligible,
            "deletion_allowed_in_this_run": False,
            "manual_approval_required": True,
            "required_manual_approval_phrase": APPROVAL_PHRASE,
            "blocker_reasons": "|".join(blockers),
            "rationale": "Dry-run only. Future deletion requires exact manual approval and a separate stage.",
        }
        blocker_rows = [{"path": ALT_ENV, "blocker_type": blocker, "blocker_detail": blocker} for blocker in blockers]
        checklist = [
            {"check_item": "manual_approval_phrase", "required_value": APPROVAL_PHRASE, "observed_value": APPROVAL_PHRASE, "check_passed": True},
            {"check_item": "deletion_allowed_in_this_run", "required_value": "false", "observed_value": False, "check_passed": True},
            {"check_item": "registry_confirms_alternate_env_review", "required_value": "true", "observed_value": registry_ok, "check_passed": registry_ok},
        ]
        registry_ref = [{
            "artifact_path": registry.get("artifact_path", ALT_ENV),
            "artifact_role": registry.get("artifact_role", ""),
            "retention_class": registry.get("retention_class", ""),
            "future_action_allowed": registry.get("future_action_allowed", ""),
            "registry_confirms_alternate_env_review": registry_ok,
            "blocker_reason": registry_blocker,
        }]
        if missing_protected or not current_ok:
            final_status = "FAIL_V21_213_CURRENT_ENV_OR_PROTECTED_PATH_MISSING"
            final_decision = "ALTERNATE_VENV_RETIREMENT_FAILED_CURRENT_ENV_OR_PROTECTED_PATH"
        elif not registry_ok:
            final_status = "FAIL_V21_213_REGISTRY_DOES_NOT_CONFIRM_ALTERNATE_ENV"
            final_decision = "ALTERNATE_VENV_RETIREMENT_FAILED_REGISTRY_MISMATCH"
        elif not exists:
            final_status = "WARN_V21_213_ALTERNATE_VENV_NOT_FOUND"
            final_decision = "ALTERNATE_VENV_RETIREMENT_WARN_NOT_FOUND"
        elif blocking_reference_rows:
            final_status = "WARN_V21_213_ALTERNATE_VENV_HAS_BLOCKING_REFERENCES"
            final_decision = "ALTERNATE_VENV_RETIREMENT_WARN_BLOCKING_REFERENCES_FOUND"
        else:
            final_status = "PASS_V21_213_ALTERNATE_VENV_RETIREMENT_DRY_RUN_READY"
            final_decision = "ALTERNATE_VENV_RETIREMENT_DRY_RUN_READY_MANUAL_APPROVAL_REQUIRED"
        summary = {
            "stage": STAGE,
            "alternate_venv_exists": exists,
            "alternate_venv_size_bytes": size,
            "current_env_present": (root / CURRENT_ENV).exists(),
            "current_env_python_present": (root / CURRENT_ENV / "Scripts/python.exe").exists(),
            "alternate_venv_reference_count": len(reference_rows),
            "total_reference_count": len(reference_rows),
            "blocking_reference_count": len(blocking_reference_rows),
            "nonblocking_reference_count": len(reference_rows) - len(blocking_reference_rows),
            "active_runtime_reference_count": category_counts["ACTIVE_RUNTIME_REFERENCE"],
            "configured_execution_reference_count": category_counts["CONFIGURED_EXECUTION_REFERENCE"],
            "self_audit_reference_count": category_counts["SELF_AUDIT_REFERENCE"],
            "test_reference_count": category_counts["TEST_REFERENCE"],
            "report_or_registry_reference_count": category_counts["REPORT_OR_REGISTRY_REFERENCE"],
            "comment_or_doc_reference_count": category_counts["COMMENT_OR_DOC_REFERENCE"],
            "historical_log_reference_count": category_counts["HISTORICAL_LOG_REFERENCE"],
            "unknown_reference_count": category_counts["UNKNOWN_REFERENCE"],
            "registry_confirms_alternate_env_review": registry_ok,
            "eligible_for_future_deletion_count": 1 if eligible else 0,
            "deletion_allowed_in_this_run": False,
            "required_manual_approval_phrase": APPROVAL_PHRASE,
            "protected_path_missing_count": len(missing_protected),
            "final_status": final_status,
            "final_decision": final_decision,
            **policy_flags(),
        }
        write_csv(output / "alternate_venv_retirement_dry_run_plan.csv", [plan], PLAN_FIELDS)
        write_csv(output / "alternate_venv_file_manifest.csv", manifest(alt, root), MANIFEST_FIELDS)
        write_csv(output / "alternate_venv_reference_classification.csv", reference_rows, REFERENCE_CLASS_FIELDS)
        write_csv(output / "registry_reference_check.csv", registry_ref, REGISTRY_FIELDS)
        write_csv(output / "current_env_safety_check.csv", current_checks, CURRENT_FIELDS)
        write_csv(output / "protected_path_presence_check.csv", presence, PRESENCE_FIELDS)
        write_csv(output / "deletion_blocker_check.csv", blocker_rows, BLOCKER_FIELDS)
        write_csv(output / "manual_approval_checklist.csv", checklist, CHECKLIST_FIELDS)
        write_json(output / "v21_213_summary.json", summary)
        write_report(output / "V21.213_alternate_venv_retirement_dry_run_report.txt", summary, plan)
    except Exception as exc:
        summary = {"stage": STAGE, "final_status": "FAIL_V21_213_DRY_RUN_EXCEPTION", "final_decision": "ALTERNATE_VENV_RETIREMENT_FAILED", "error_type": type(exc).__name__, "error_message": str(exc), **policy_flags()}
        write_json(output / "v21_213_summary.json", summary)
        (output / "V21.213_alternate_venv_retirement_dry_run_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\nerror={summary['error_type']}: {summary['error_message']}\n", encoding="utf-8")
    for key in ["final_status", "final_decision", "alternate_venv_exists", "alternate_venv_reference_count", "eligible_for_future_deletion_count", "deletion_performed", "broker_action_allowed"]:
        if key in summary:
            print(f"{key}={summary[key]}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", default=str(DEFAULT_ROOT))
    parser.add_argument("--registry-csv", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(Path(args.repo_root), registry_csv=Path(args.registry_csv) if args.registry_csv else None)
    return 0 if str(summary["final_status"]).startswith(("PASS", "WARN")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
