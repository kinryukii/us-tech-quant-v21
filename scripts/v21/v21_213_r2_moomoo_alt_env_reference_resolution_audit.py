#!/usr/bin/env python
"""V21.213 R2 Moomoo alternate-env reference resolution audit.

Research-only, audit-only. Resolves whether .venv_moomoo_py312 references are
active Moomoo runtime dependencies, frozen V21.196 artifacts, or migration
candidates. It never connects to OpenD or performs broker actions.
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
STAGE = "V21.213_R2_MOOMOO_ALT_ENV_REFERENCE_RESOLUTION_AUDIT"
OUT_REL = Path("outputs/v21/V21.213_R2_MOOMOO_ALT_ENV_REFERENCE_RESOLUTION_AUDIT")
R1_REF_REL = Path("outputs/v21/V21.213_ALTERNATE_VENV_RETIREMENT_DRY_RUN_GATE_FROM_REGISTRY/alternate_venv_reference_classification.csv")
REGISTRY_REL = Path("outputs/v21/V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY/artifact_registry.csv")
PROTECTED_REQUIRED = [
    ".venv",
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
    "outputs/v21/V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY",
    "outputs/v21/V21.213_ALTERNATE_VENV_RETIREMENT_DRY_RUN_GATE_FROM_REGISTRY",
]
BLOCKING_AFTER_RESOLUTION = {"ACTIVE_MOOMOO_RUNTIME_KEEP_ALT_ENV", "UNKNOWN_KEEP_BLOCKING"}
RESOLUTION_FIELDS = [
    "reference_file", "line_number", "reference_category_from_r1", "matched_text",
    "surrounding_context_short", "v21_stage_context", "moomoo_related_flag",
    "wrapper_or_runtime_flag", "historical_output_flag", "current_daily_chain_reference_flag",
    "migration_to_current_venv_feasible_flag", "resolution_class",
    "blocks_deletion_after_resolution", "recommended_action", "rationale",
]
V196_FIELDS = [
    "artifact_path", "artifact_type", "exists", "referenced_by_current_root_daily_chain",
    "superseded_by_v21_199_r4_or_v21_201", "frozen_historical_environment_repair_artifact",
    "current_alt_env_dependency_flag", "rationale",
]
ENV_FIELDS = [
    "current_venv_python_executable", "current_venv_python_exists", "current_venv_moomoo_import_ok",
    "current_venv_moomoo_version", "alt_venv_python_exists", "alt_venv_invoked_by_this_stage",
]
MIGRATION_FIELDS = ["reference_file", "line_number", "migration_candidate_flag", "recommended_action", "rationale"]
PRESENCE_FIELDS = [
    "protected_key", "expected_path", "exact_exists", "alias_discovery_attempted",
    "alias_candidate_count", "resolved_exists", "resolved_protected_path",
    "resolution_method", "warning_reason",
]
GATE_FIELDS = ["gate_name", "gate_value", "recommendation", "rationale"]


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


def current_daily_chain_text(root: Path) -> str:
    texts = []
    for file in [root / "scripts/run_daily_moomoo_research_chain.ps1", root / "scripts/v21/run_daily_moomoo_research_chain.ps1"]:
        if file.exists():
            texts.append(file.read_text(encoding="utf-8", errors="ignore").lower())
    return "\n".join(texts)


def current_env_check(root: Path, simulate_moomoo_import_ok: bool | None = None) -> dict[str, Any]:
    current_py = root / ".venv/Scripts/python.exe"
    alt_py = root / ".venv_moomoo_py312/Scripts/python.exe"
    version = ""
    ok = False
    if simulate_moomoo_import_ok is not None:
        ok = simulate_moomoo_import_ok
        version = "SIMULATED" if ok else ""
    elif current_py.exists():
        code = "import json\ntry:\n import moomoo\n print(json.dumps({'ok': True, 'version': getattr(moomoo, '__version__', '')}))\nexcept Exception as e:\n print(json.dumps({'ok': False, 'version': '', 'error': type(e).__name__ + ': ' + str(e)}))\n"
        try:
            proc = subprocess.run([str(current_py), "-c", code], capture_output=True, text=True, timeout=20, check=False)
            payload = json.loads((proc.stdout or "{}").strip().splitlines()[-1])
            ok = bool(payload.get("ok"))
            version = str(payload.get("version", ""))
        except Exception:
            ok = False
    return {
        "current_venv_python_executable": str(current_py),
        "current_venv_python_exists": current_py.exists(),
        "current_venv_moomoo_import_ok": ok,
        "current_venv_moomoo_version": version,
        "alt_venv_python_exists": alt_py.exists(),
        "alt_venv_invoked_by_this_stage": False,
    }


def stage_context(path: str) -> str:
    parts = Path(path.replace("\\", "/")).parts
    for part in parts:
        if part.startswith("V21."):
            return part
    return ""


def classify_reference(row: dict[str, str], root: Path, daily_text: str, current_moomoo_ok: bool) -> dict[str, Any]:
    file = row.get("reference_file", "")
    context = row.get("surrounding_context_short", "")
    lower_file = file.lower()
    lower_context = context.lower()
    category = row.get("reference_category", "")
    vstage = stage_context(file)
    historical_output = lower_file.startswith("outputs/v21/v21.196")
    v196_script = lower_file.startswith("scripts/v21/v21_196") or lower_file.startswith("scripts/v21/run_v21_196") or lower_file.startswith("scripts/v21/test_v21_196")
    current_chain_ref = "v21_196" in daily_text or "run_v21_196" in daily_text
    wrapper_runtime = lower_file.endswith(".ps1") or "scripts\\python.exe" in lower_context or "scripts/python.exe" in lower_context or "subprocess" in lower_context
    moomoo_related = "moomoo" in lower_file or "moomoo" in lower_context
    if "opend" in lower_context and ("subprocess" in lower_context or "python.exe" in lower_context) and not v196_script and not historical_output:
        resolution = "ACTIVE_MOOMOO_RUNTIME_KEEP_ALT_ENV"
        action = "KEEP_ALT_ENV_UNTIL_ACTIVE_RUNTIME_MIGRATED"
        rationale = "Reference appears to actively run Moomoo/OpenD-related code with alternate environment."
    elif historical_output:
        resolution = "HISTORICAL_FROZEN_ARTIFACT_REFERENCE"
        action = "KEEP_ARTIFACT_AS_HISTORY_DO_NOT_BLOCK_ALT_ENV_RETIREMENT"
        rationale = "Reference is in frozen V21.196 output artifact, not an active runtime launcher."
    elif v196_script and not current_chain_ref:
        resolution = "MIGRATE_TO_CURRENT_VENV_CANDIDATE"
        action = "MANUAL_REVIEW_MIGRATE_OR_FREEZE_V21_196_SCRIPT"
        rationale = "V21.196 script references alternate env but current daily chain uses V21.199_R4/V21.201."
    elif category in {"SELF_AUDIT_REFERENCE", "TEST_REFERENCE", "REPORT_OR_REGISTRY_REFERENCE"}:
        resolution = "SELF_AUDIT_OR_REGISTRY_FALSE_BLOCKER"
        action = "NO_RUNTIME_ACTION_REQUIRED"
        rationale = "Reference is audit, test, report, or registry metadata."
    elif category == "CONFIGURED_EXECUTION_REFERENCE" and "v21.196" in lower_file:
        resolution = "CONFIGURED_BUT_OBSOLETE_RUNTIME_REFERENCE"
        action = "MANUAL_REVIEW_MARK_V21_196_CONFIG_OBSOLETE"
        rationale = "Configured V21.196 reference appears superseded by current Moomoo stages."
    elif current_moomoo_ok and moomoo_related and (v196_script or "v21.196" in lower_file):
        resolution = "MIGRATE_TO_CURRENT_VENV_CANDIDATE"
        action = "MANUAL_REVIEW_MIGRATE_TO_CURRENT_VENV"
        rationale = "Current .venv can import moomoo; reference can likely migrate after review."
    else:
        resolution = "UNKNOWN_KEEP_BLOCKING"
        action = "INVESTIGATE_BEFORE_RETIREMENT"
        rationale = "Reference remains unclear after R2 classification."
    return {
        "reference_file": file,
        "line_number": row.get("line_number", ""),
        "reference_category_from_r1": category,
        "matched_text": row.get("matched_text", ""),
        "surrounding_context_short": context,
        "v21_stage_context": vstage,
        "moomoo_related_flag": moomoo_related,
        "wrapper_or_runtime_flag": wrapper_runtime,
        "historical_output_flag": historical_output,
        "current_daily_chain_reference_flag": current_chain_ref,
        "migration_to_current_venv_feasible_flag": bool(current_moomoo_ok and resolution in {"MIGRATE_TO_CURRENT_VENV_CANDIDATE", "CONFIGURED_BUT_OBSOLETE_RUNTIME_REFERENCE"}),
        "resolution_class": resolution,
        "blocks_deletion_after_resolution": resolution in BLOCKING_AFTER_RESOLUTION,
        "recommended_action": action,
        "rationale": rationale,
    }


def v21_196_dependency_audit(root: Path, daily_text: str) -> list[dict[str, Any]]:
    paths: list[Path] = []
    for base in [root / "scripts/v21", root / "outputs/v21"]:
        if base.exists():
            paths.extend([p for p in base.iterdir() if p.name.lower().startswith(("v21_196", "run_v21_196", "test_v21_196", "v21.196"))])
    rows = []
    for path in sorted(set(paths), key=lambda p: rel(p, root)):
        rows.append({
            "artifact_path": rel(path, root),
            "artifact_type": "directory" if path.is_dir() else "file",
            "exists": path.exists(),
            "referenced_by_current_root_daily_chain": "v21_196" in daily_text or "run_v21_196" in daily_text,
            "superseded_by_v21_199_r4_or_v21_201": True,
            "frozen_historical_environment_repair_artifact": rel(path, root).lower().startswith("outputs/v21/v21.196"),
            "current_alt_env_dependency_flag": False,
            "rationale": "Current daily chain uses V21.199_R4 and V21.201, not V21.196.",
        })
    return rows


def policy_flags() -> dict[str, bool]:
    return {
        "research_only": True,
        "audit_only": True,
        "dry_run": True,
        "mutation_allowed": False,
        "deletion_performed": False,
        "compression_performed": False,
        "archive_movement_performed": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "protected_outputs_modified": False,
        "canonical_mutation_performed": False,
        "price_refresh_performed": False,
        "moomoo_broker_connection_performed": False,
    }


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"input_blocking_reference_count={summary['input_blocking_reference_count']}",
        f"resolved_nonblocking_count={summary['resolved_nonblocking_count']}",
        f"remaining_blocking_count={summary['remaining_blocking_count']}",
        f"current_venv_moomoo_import_ok={summary['current_venv_moomoo_import_ok']}",
        f"alt_venv_retirement_recommended_after_manual_review={summary['alt_venv_retirement_recommended_after_manual_review']}",
        "deletion_allowed_in_this_run=false",
        "moomoo_broker_connection_performed=false",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(
    repo_root: Path = DEFAULT_ROOT,
    r1_reference_csv: Path | None = None,
    registry_csv: Path | None = None,
    out_dir: Path | None = None,
    simulate_exception: bool = False,
    simulate_moomoo_import_ok: bool | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if simulate_exception:
            raise RuntimeError("simulated V21.213 R2 failure")
        r1_rows = read_csv(r1_reference_csv or (root / R1_REF_REL))
        blocking_input = [row for row in r1_rows if str_bool(row.get("blocking_reference_flag"))]
        presence = protected_presence(root)
        missing = [row for row in presence if not str_bool(row["resolved_exists"])]
        env = current_env_check(root, simulate_moomoo_import_ok=simulate_moomoo_import_ok)
        daily_text = current_daily_chain_text(root)
        resolved = [classify_reference(row, root, daily_text, bool(env["current_venv_moomoo_import_ok"])) for row in blocking_input]
        remaining = [row for row in resolved if str_bool(row["blocks_deletion_after_resolution"])]
        v196_rows = v21_196_dependency_audit(root, daily_text)
        migration_rows = [{
            "reference_file": row["reference_file"],
            "line_number": row["line_number"],
            "migration_candidate_flag": row["resolution_class"] == "MIGRATE_TO_CURRENT_VENV_CANDIDATE",
            "recommended_action": row["recommended_action"],
            "rationale": row["rationale"],
        } for row in resolved]
        gate_rows = [{
            "gate_name": "alt_venv_retirement_after_manual_review",
            "gate_value": not remaining and bool(env["current_venv_moomoo_import_ok"]) and not missing,
            "recommendation": "RETIREMENT_REVIEW_READY" if not remaining and bool(env["current_venv_moomoo_import_ok"]) and not missing else "DO_NOT_RETIRE_YET",
            "rationale": "Requires zero remaining blockers and current .venv moomoo import success.",
        }]
        if missing:
            final_status = "FAIL_V21_213_R2_PROTECTED_PATH_MISSING"
            final_decision = "ALT_ENV_REFERENCE_RESOLUTION_FAILED_PROTECTED_PATH_MISSING"
        elif remaining:
            final_status = "WARN_V21_213_R2_ALT_ENV_REFERENCES_REMAIN_BLOCKING"
            final_decision = "ALT_ENV_REFERENCES_STILL_BLOCK_RETIREMENT"
        elif not env["current_venv_moomoo_import_ok"]:
            final_status = "WARN_V21_213_R2_CURRENT_VENV_MOOMOO_IMPORT_FAILED"
            final_decision = "ALT_ENV_REFERENCES_RESOLVED_BUT_CURRENT_VENV_MOOMOO_FAILED"
        else:
            final_status = "PASS_V21_213_R2_ALT_ENV_REFERENCES_RESOLVED_NONBLOCKING"
            final_decision = "ALT_ENV_REFERENCES_RESOLVED_RETIREMENT_REVIEW_READY"
        summary = {
            "stage": STAGE,
            "input_blocking_reference_count": len(blocking_input),
            "resolved_nonblocking_count": len(resolved) - len(remaining),
            "remaining_blocking_count": len(remaining),
            "active_moomoo_runtime_keep_alt_env_count": sum(1 for row in resolved if row["resolution_class"] == "ACTIVE_MOOMOO_RUNTIME_KEEP_ALT_ENV"),
            "unknown_keep_blocking_count": sum(1 for row in resolved if row["resolution_class"] == "UNKNOWN_KEEP_BLOCKING"),
            "migrate_to_current_venv_candidate_count": sum(1 for row in resolved if row["resolution_class"] == "MIGRATE_TO_CURRENT_VENV_CANDIDATE"),
            "configured_obsolete_reference_count": sum(1 for row in resolved if row["resolution_class"] == "CONFIGURED_BUT_OBSOLETE_RUNTIME_REFERENCE"),
            "historical_frozen_artifact_reference_count": sum(1 for row in resolved if row["resolution_class"] == "HISTORICAL_FROZEN_ARTIFACT_REFERENCE"),
            "current_venv_moomoo_import_ok": bool(env["current_venv_moomoo_import_ok"]),
            "current_venv_moomoo_version": env["current_venv_moomoo_version"],
            "v21_196_current_chain_required_flag": "v21_196" in daily_text or "run_v21_196" in daily_text,
            "v21_196_superseded_by_v21_199_r4_or_v21_201_flag": True,
            "alt_venv_retirement_recommended_after_manual_review": not remaining and bool(env["current_venv_moomoo_import_ok"]) and not missing,
            "deletion_allowed_in_this_run": False,
            "final_status": final_status,
            "final_decision": final_decision,
            **policy_flags(),
        }
        write_csv(output / "blocking_reference_resolution_audit.csv", resolved, RESOLUTION_FIELDS)
        write_csv(output / "v21_196_dependency_audit.csv", v196_rows, V196_FIELDS)
        write_csv(output / "current_moomoo_execution_env_check.csv", [env], ENV_FIELDS)
        write_csv(output / "migration_candidate_check.csv", migration_rows, MIGRATION_FIELDS)
        write_csv(output / "protected_path_presence_check.csv", presence, PRESENCE_FIELDS)
        write_csv(output / "deletion_gate_recommendation.csv", gate_rows, GATE_FIELDS)
        write_json(output / "v21_213_r2_summary.json", summary)
        write_report(output / "V21.213_R2_moomoo_alt_env_reference_resolution_report.txt", summary)
    except Exception as exc:
        summary = {
            "stage": STAGE,
            "final_status": "FAIL_V21_213_R2_REFERENCE_RESOLUTION_EXCEPTION",
            "final_decision": "ALT_ENV_REFERENCE_RESOLUTION_FAILED",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            **policy_flags(),
        }
        write_json(output / "v21_213_r2_summary.json", summary)
        (output / "V21.213_R2_moomoo_alt_env_reference_resolution_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\nerror={summary['error_type']}: {summary['error_message']}\n", encoding="utf-8")
    for key in ["final_status", "final_decision", "input_blocking_reference_count", "resolved_nonblocking_count", "remaining_blocking_count", "current_venv_moomoo_import_ok", "deletion_performed", "broker_action_allowed"]:
        if key in summary:
            print(f"{key}={summary[key]}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", default=str(DEFAULT_ROOT))
    parser.add_argument("--r1-reference-csv", default="")
    parser.add_argument("--registry-csv", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(
        Path(args.repo_root),
        r1_reference_csv=Path(args.r1_reference_csv) if args.r1_reference_csv else None,
        registry_csv=Path(args.registry_csv) if args.registry_csv else None,
    )
    return 0 if str(summary["final_status"]).startswith(("PASS", "WARN")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
