#!/usr/bin/env python
"""V21.211 second-pass cleanup target discovery and risk budget.

Research-only, audit-only. This stage explains remaining disk usage and proposes
manual-review cleanup targets. It never deletes, moves, compresses, rewrites,
refreshes prices, mutates canonical files, or performs broker/adoption actions.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path(r"D:\us-tech-quant")
STAGE = "V21.211_SECOND_PASS_CLEANUP_TARGET_DISCOVERY_AND_RISK_BUDGET"
OUT_REL = Path("outputs/v21/V21.211_SECOND_PASS_CLEANUP_TARGET_DISCOVERY_AND_RISK_BUDGET")
CURRENT_ENV = ".venv"
ALT_ENV = ".venv_moomoo_py312"
PROTECTED_REQUIRED = [
    ".venv",
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
    "outputs/v21/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION",
    "outputs/v21/V21.208_ORIGINAL_REMOVAL_DRY_RUN_APPROVAL_GATE",
    "outputs/v21/V21.209_DELETE_ORIGINALS_AFTER_ZIP_VERIFICATION",
    "outputs/v21/V21.210_POST_CLEANUP_SIZE_AND_INTEGRITY_RECONCILIATION",
    "archive/v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION",
]
SENSITIVE_TOKENS = [
    "canonical",
    "price_history",
    "ohlcv",
    "kline",
    "moomoo",
    "dram",
    "abcde",
    "trade_plan",
    "ledger",
    "ranking",
    "latest",
    "current_chain",
    "protected",
]
CURRENT_CHAIN_STAGE_PREFIXES = (
    "V21.197",
    "V21.199",
    "V21.201",
    "V21.207",
    "V21.208",
    "V21.209",
    "V21.210",
    "V21.211",
)
TOP_FIELDS = ["path", "size_bytes", "file_count", "directory_count", "latest_modified_time"]
LARGEST_FILE_FIELDS = ["path", "size_bytes", "extension", "latest_modified_time"]
TARGET_FIELDS = [
    "target_path",
    "target_type",
    "recursive_size_bytes",
    "file_count",
    "directory_count",
    "latest_modified_time",
    "risk_class",
    "estimated_savings_if_actioned_later",
    "recommended_next_stage",
    "deletion_candidate_now",
    "compression_candidate_now",
    "manual_review_required",
    "blocker_reasons",
    "rationale",
]
VENV_FIELDS = [
    "path",
    "recursive_size_bytes",
    "file_count",
    "directory_count",
    "python_version",
    "scripts_python_exe_present",
    "site_packages_size_bytes",
    "latest_modified_time",
    "current_project_env_flag",
    "retirement_candidate_flag",
    "risk_class",
    "blocker_reasons",
]
STATE_FIELDS = [
    "path",
    "recursive_size_bytes",
    "file_count",
    "directory_count",
    "latest_modified_time",
    "largest_file_path",
    "largest_file_size_bytes",
    "extension_breakdown",
    "cache_temp_log_checkpoint_like_count",
    "persistent_ledger_state_like_count",
    "risk_class",
    "deletion_candidate_now",
    "rationale",
]
ARCHIVE_FIELDS = [
    "path",
    "recursive_size_bytes",
    "file_count",
    "directory_count",
    "latest_modified_time",
    "zip_archive_count",
    "v21_207_zip_copies_present",
    "contains_active_state_like_file",
    "risk_class",
    "deletion_candidate_now",
    "rationale",
]
HISTORICAL_FIELDS = [
    "stage_dir",
    "stage_name",
    "recursive_size_bytes",
    "file_count",
    "directory_count",
    "latest_modified_time",
    "risk_class",
    "cold_archive_review_candidate_flag",
    "blocker_reasons",
    "rationale",
]
PRESENCE_FIELDS = [
    "protected_key",
    "expected_path",
    "exact_exists",
    "alias_discovery_attempted",
    "alias_candidate_count",
    "resolved_exists",
    "resolved_protected_path",
    "resolution_method",
    "warning_reason",
]


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


def iter_dirs(path: Path) -> list[Path]:
    try:
        return sorted([p for p in path.rglob("*") if p.is_dir()], key=lambda p: p.as_posix())
    except OSError:
        return []


def latest_mtime(paths: list[Path]) -> str:
    mtimes = []
    for path in paths:
        try:
            mtimes.append(path.stat().st_mtime)
        except OSError:
            continue
    if not mtimes:
        return ""
    return datetime.fromtimestamp(max(mtimes), timezone.utc).replace(microsecond=0).isoformat()


def tree_metrics(path: Path) -> tuple[int, int, int, str]:
    total = 0
    files = 0
    dirs = 0
    all_paths: list[Path] = []
    if not path.exists():
        return 0, 0, 0, ""
    for file in iter_files(path):
        try:
            total += file.stat().st_size
            files += 1
            all_paths.append(file)
        except OSError:
            continue
    for directory in iter_dirs(path):
        dirs += 1
        all_paths.append(directory)
    all_paths.append(path)
    return total, files, dirs, latest_mtime(all_paths)


def top_level_size(root: Path) -> list[dict[str, Any]]:
    rows = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        size, files, dirs, latest = tree_metrics(child)
        rows.append({"path": rel(child, root), "size_bytes": size, "file_count": files, "directory_count": dirs, "latest_modified_time": latest})
    rows.sort(key=lambda row: int(row["size_bytes"]), reverse=True)
    total, files, dirs, latest = tree_metrics(root)
    return [{"path": ".", "size_bytes": total, "file_count": files, "directory_count": dirs, "latest_modified_time": latest}] + rows


def largest_directories(root: Path, limit: int = 100) -> list[dict[str, Any]]:
    candidates = [root] + iter_dirs(root)
    rows = []
    for path in candidates:
        size, files, dirs, latest = tree_metrics(path)
        rows.append({"path": rel(path, root), "size_bytes": size, "file_count": files, "directory_count": dirs, "latest_modified_time": latest})
    rows.sort(key=lambda row: int(row["size_bytes"]), reverse=True)
    return rows[:limit]


def largest_files(root: Path, limit: int = 100) -> list[dict[str, Any]]:
    rows = []
    for file in iter_files(root):
        try:
            stat = file.stat()
        except OSError:
            continue
        rows.append({
            "path": rel(file, root),
            "size_bytes": stat.st_size,
            "extension": file.suffix.lower(),
            "latest_modified_time": datetime.fromtimestamp(stat.st_mtime, timezone.utc).replace(microsecond=0).isoformat(),
        })
    rows.sort(key=lambda row: int(row["size_bytes"]), reverse=True)
    return rows[:limit]


def pyvenv_dirs(root: Path) -> list[Path]:
    candidates = {root / CURRENT_ENV, root / ALT_ENV}
    for cfg in root.rglob("pyvenv.cfg"):
        candidates.add(cfg.parent)
    return sorted([path for path in candidates if path.exists() and path.is_dir()], key=lambda p: rel(p, root).lower())


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


def site_packages_size(path: Path) -> int:
    total = 0
    for candidate in path.rglob("site-packages"):
        size, _files, _dirs, _latest = tree_metrics(candidate)
        total += size
    return total


def virtualenv_audit(root: Path) -> list[dict[str, Any]]:
    rows = []
    for env in pyvenv_dirs(root):
        size, files, dirs, latest = tree_metrics(env)
        r = rel(env, root)
        current = r == CURRENT_ENV
        retirement = r == ALT_ENV and not current
        blockers = []
        if current:
            blockers.append("CURRENT_PROJECT_ENV")
        if r.lower().find("moomoo") >= 0:
            blockers.append("BROKER_OR_MOOMOO_NAMED_ENV_REVIEW_REQUIRED")
        rows.append({
            "path": r,
            "recursive_size_bytes": size,
            "file_count": files,
            "directory_count": dirs,
            "python_version": pyvenv_version(env),
            "scripts_python_exe_present": (env / "Scripts/python.exe").exists(),
            "site_packages_size_bytes": site_packages_size(env),
            "latest_modified_time": latest,
            "current_project_env_flag": current,
            "retirement_candidate_flag": retirement,
            "risk_class": "MUST_KEEP_CURRENT_ENV" if current else "POSSIBLE_UNUSED_VIRTUALENV_REVIEW",
            "blocker_reasons": "|".join(blockers),
        })
    return rows


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


def newest_path(paths: list[Path]) -> Path:
    return max(paths, key=lambda p: p.stat().st_mtime)


def protected_presence(root: Path) -> list[dict[str, Any]]:
    rows = []
    for item in PROTECTED_REQUIRED:
        expected = root / item
        exact_exists = expected.exists()
        alias_attempted = False
        candidates: list[Path] = []
        resolved = expected if exact_exists else None
        method = "EXACT_PATH" if exact_exists else "UNRESOLVED"
        warning = "" if exact_exists else "EXPECTED_PATH_MISSING"
        if not exact_exists and item.startswith("outputs/v21/V21."):
            alias_attempted = True
            stage_id = Path(item).name.split("_", 1)[0]
            candidates = protected_alias_candidates(root, stage_id)
            if candidates:
                resolved = newest_path(candidates)
                method = "ALIAS_DISCOVERY_NEWEST_MODIFIED"
                warning = ""
        rows.append({
            "protected_key": Path(item).name,
            "expected_path": item,
            "exact_exists": exact_exists,
            "alias_discovery_attempted": alias_attempted,
            "alias_candidate_count": len(candidates),
            "resolved_exists": bool(resolved and resolved.exists()),
            "resolved_protected_path": rel(resolved, root) if resolved else "",
            "resolution_method": method,
            "warning_reason": warning,
        })
    return rows


def stage_dirs(root: Path) -> list[Path]:
    out21 = root / "outputs/v21"
    if not out21.exists():
        return []
    return sorted([p for p in out21.iterdir() if p.is_dir() and p.name.startswith("V21.")], key=lambda p: p.name)


def protected_resolved_stage_names(presence: list[dict[str, Any]]) -> set[str]:
    names = set()
    for row in presence:
        resolved = str(row.get("resolved_protected_path", ""))
        if resolved.startswith("outputs/v21/"):
            names.add(Path(resolved).name)
    return names


def sensitive_path(path: Path, root: Path) -> bool:
    text = rel(path, root).lower()
    return any(token in text for token in SENSITIVE_TOKENS)


def classify_stage(stage: Path, root: Path, protected_names: set[str]) -> tuple[str, str, str, bool]:
    name = stage.name
    lower = name.lower()
    joined = " ".join([lower] + [file.name.lower() for file in iter_files(stage)[:500]])
    if "v21.154" in lower:
        return "KEEP_AUDIT_CRITICAL_HISTORY", "V21.154 invalid-trial replay history remains audit-critical.", "KEEP_AS_IS", False
    if name in protected_names or name.startswith(CURRENT_CHAIN_STAGE_PREFIXES):
        return "MUST_KEEP_CURRENT_CHAIN_OUTPUT", "Protected/current chain stage.", "KEEP_AS_IS", False
    if sensitive_path(stage, root) or any(token in joined for token in SENSITIVE_TOKENS):
        return "MUST_KEEP_CURRENT_CHAIN_OUTPUT", "Contains protected current-chain or data-lineage keywords.", "KEEP_AS_IS", False
    return "COLD_ARCHIVE_COMPRESSION_REVIEW", "Large historical output can be manually reviewed for future cold archive compression.", "PLAN_FUTURE_COLD_ARCHIVE_REVIEW", True


def large_historical_outputs(root: Path, presence: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    protected_names = protected_resolved_stage_names(presence)
    rows = []
    for stage in stage_dirs(root):
        size, files, dirs, latest = tree_metrics(stage)
        risk, rationale, _next, cold = classify_stage(stage, root, protected_names)
        blockers = []
        if risk.startswith("MUST_KEEP"):
            blockers.append("PROTECTED_OR_CURRENT_CHAIN")
        if "audit-critical" in rationale.lower():
            blockers.append("AUDIT_CRITICAL_HISTORY")
        rows.append({
            "stage_dir": rel(stage, root),
            "stage_name": stage.name,
            "recursive_size_bytes": size,
            "file_count": files,
            "directory_count": dirs,
            "latest_modified_time": latest,
            "risk_class": risk,
            "cold_archive_review_candidate_flag": cold,
            "blocker_reasons": "|".join(blockers),
            "rationale": rationale,
        })
    rows.sort(key=lambda row: int(row["recursive_size_bytes"]), reverse=True)
    return rows[:limit]


def state_audit(root: Path) -> list[dict[str, Any]]:
    state = root / "state"
    size, files, dirs, latest = tree_metrics(state)
    file_rows = iter_files(state) if state.exists() else []
    largest = max(file_rows, key=lambda p: p.stat().st_size, default=None) if file_rows else None
    ext_counts = Counter((file.suffix.lower() or "<none>") for file in file_rows)
    cache_like = sum(1 for file in file_rows if any(token in file.name.lower() for token in ["cache", "tmp", "temp", "log", "checkpoint", "ckpt"]))
    persistent_like = sum(1 for file in file_rows if any(token in file.name.lower() for token in ["ledger", "state", "position", "portfolio", "history", "manifest"]))
    return [{
        "path": "state",
        "recursive_size_bytes": size,
        "file_count": files,
        "directory_count": dirs,
        "latest_modified_time": latest,
        "largest_file_path": rel(largest, root) if largest else "",
        "largest_file_size_bytes": largest.stat().st_size if largest else 0,
        "extension_breakdown": "|".join(f"{key}:{value}" for key, value in sorted(ext_counts.items())),
        "cache_temp_log_checkpoint_like_count": cache_like,
        "persistent_ledger_state_like_count": persistent_like,
        "risk_class": "STATE_CACHE_REVIEW",
        "deletion_candidate_now": False,
        "rationale": "State directory is audit-only review; persistent state/ledger files must be inspected manually.",
    }]


def archive_audit(root: Path) -> list[dict[str, Any]]:
    archive = root / "archive"
    size, files, dirs, latest = tree_metrics(archive)
    file_rows = iter_files(archive) if archive.exists() else []
    zip_count = sum(1 for file in file_rows if file.suffix.lower() == ".zip")
    active_like = any(any(token in rel(file, root).lower() for token in ["state", "ledger", "current_chain", "latest"]) for file in file_rows)
    v207 = archive / "v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION"
    return [{
        "path": "archive",
        "recursive_size_bytes": size,
        "file_count": files,
        "directory_count": dirs,
        "latest_modified_time": latest,
        "zip_archive_count": zip_count,
        "v21_207_zip_copies_present": v207.exists() and len(list(v207.glob("*.zip"))) >= 3,
        "contains_active_state_like_file": active_like,
        "risk_class": "ARCHIVE_BACKUP_KEEP",
        "deletion_candidate_now": False,
        "rationale": "Archive contains backup zip copies; keep unless a separate archive-retention policy is approved.",
    }]


def cleanup_targets(root: Path, venv_rows: list[dict[str, Any]], state_rows: list[dict[str, Any]], archive_rows: list[dict[str, Any]], historical_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in venv_rows:
        size = int(row["recursive_size_bytes"])
        rows.append(target_row(row["path"], "virtualenv", size, row["file_count"], row["directory_count"], row["latest_modified_time"], row["risk_class"], size if row["risk_class"] == "POSSIBLE_UNUSED_VIRTUALENV_REVIEW" else 0, "V21.212_VIRTUALENV_RETIREMENT_MANUAL_REVIEW_PLAN" if row["risk_class"] == "POSSIBLE_UNUSED_VIRTUALENV_REVIEW" else "NO_ACTION", row["blocker_reasons"], "Virtualenv-like directory classification."))
    for row in state_rows:
        rows.append(target_row(row["path"], "state_directory", row["recursive_size_bytes"], row["file_count"], row["directory_count"], row["latest_modified_time"], "STATE_CACHE_REVIEW", int(row["recursive_size_bytes"]), "V21.212_STATE_DIRECTORY_MANUAL_REVIEW_PLAN", "PERSISTENT_STATE_REVIEW_REQUIRED", row["rationale"]))
    for row in archive_rows:
        rows.append(target_row(row["path"], "archive_directory", row["recursive_size_bytes"], row["file_count"], row["directory_count"], row["latest_modified_time"], "ARCHIVE_BACKUP_KEEP", 0, "NO_ACTION_WITHOUT_RETENTION_POLICY", "BACKUP_ARCHIVE_KEEP", row["rationale"]))
    for row in historical_rows:
        risk = row["risk_class"]
        savings = int(row["recursive_size_bytes"]) if risk == "COLD_ARCHIVE_COMPRESSION_REVIEW" else 0
        rows.append(target_row(row["stage_dir"], "outputs_v21_stage", row["recursive_size_bytes"], row["file_count"], row["directory_count"], row["latest_modified_time"], risk, savings, "V21.212_COLD_ARCHIVE_COMPRESSION_REVIEW_PLAN" if savings else "NO_ACTION", row["blocker_reasons"], row["rationale"]))
    rows.sort(key=lambda row: int(row["recursive_size_bytes"]), reverse=True)
    return rows


def target_row(path: str, target_type: str, size: Any, files: Any, dirs: Any, latest: str, risk: str, savings: int, next_stage: str, blockers: str, rationale: str) -> dict[str, Any]:
    return {
        "target_path": path,
        "target_type": target_type,
        "recursive_size_bytes": int(size or 0),
        "file_count": int(files or 0),
        "directory_count": int(dirs or 0),
        "latest_modified_time": latest,
        "risk_class": risk,
        "estimated_savings_if_actioned_later": int(savings),
        "recommended_next_stage": next_stage,
        "deletion_candidate_now": False,
        "compression_candidate_now": False,
        "manual_review_required": True,
        "blocker_reasons": blockers,
        "rationale": rationale,
    }


def policy_flags() -> dict[str, bool]:
    return {
        "research_only": True,
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


def write_report(path: Path, summary: dict[str, Any], targets: list[dict[str, Any]]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"repo_total_size_bytes={summary['repo_total_size_bytes']}",
        f"outputs_size_bytes={summary['outputs_size_bytes']}",
        f"archive_size_bytes={summary['archive_size_bytes']}",
        f"state_size_bytes={summary['state_size_bytes']}",
        f"venv_size_bytes={summary['venv_size_bytes']}",
        f"alternate_venv_candidate_count={summary['alternate_venv_candidate_count']}",
        f"cold_archive_review_candidate_count={summary['cold_archive_review_candidate_count']}",
        f"immediate_deletion_candidate_count={summary['immediate_deletion_candidate_count']}",
        "research_only=true",
        "audit_only=true",
        "mutation_allowed=false",
        "deletion_performed=false",
        "",
        "top_manual_review_targets:",
    ]
    lines.extend([f"- {row['target_path']} size_bytes={row['recursive_size_bytes']} risk={row['risk_class']} next={row['recommended_next_stage']}" for row in targets[:25]])
    lines.append("")
    lines.append("next_recommended_action=Manual review only; no immediate deletion or compression candidates were authorized by this stage.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(repo_root: Path = DEFAULT_ROOT, out_dir: Path | None = None, simulate_exception: bool = False) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if simulate_exception:
            raise RuntimeError("simulated V21.211 discovery failure")
        top_rows = top_level_size(root)
        dir_rows = largest_directories(root)
        file_rows = largest_files(root)
        presence = protected_presence(root)
        venv_rows = virtualenv_audit(root)
        state_rows = state_audit(root)
        archive_rows = archive_audit(root)
        historical_rows = large_historical_outputs(root, presence)
        target_rows = cleanup_targets(root, venv_rows, state_rows, archive_rows, historical_rows)
        missing = [row for row in presence if not str_bool(row["resolved_exists"])]
        totals = {row["path"]: row for row in top_rows}
        alt_venvs = [row for row in venv_rows if row["retirement_candidate_flag"]]
        cold = [row for row in historical_rows if row["cold_archive_review_candidate_flag"]]
        immediate = [row for row in target_rows if str_bool(row["deletion_candidate_now"])]
        if missing:
            final_status = "WARN_V21_211_PROTECTED_PATH_MISSING"
            final_decision = "SECOND_PASS_CLEANUP_WARN_PROTECTED_PATH_MISSING"
        else:
            final_status = "PASS_V21_211_SECOND_PASS_TARGET_DISCOVERY_READY"
            final_decision = "SECOND_PASS_CLEANUP_TARGETS_READY_MANUAL_REVIEW_ONLY"
        repo_total = top_rows[0]
        summary = {
            "stage": STAGE,
            "repo_total_size_bytes": int(repo_total["size_bytes"]),
            "repo_total_file_count": int(repo_total["file_count"]),
            "repo_total_directory_count": int(repo_total["directory_count"]),
            "outputs_size_bytes": int(totals.get("outputs", {}).get("size_bytes", 0)),
            "archive_size_bytes": int(totals.get("archive", {}).get("size_bytes", 0)),
            "state_size_bytes": int(totals.get("state", {}).get("size_bytes", 0)),
            "venv_size_bytes": int(totals.get(".venv", {}).get("size_bytes", 0)),
            "alternate_venv_candidate_count": len(alt_venvs),
            "alternate_venv_size_bytes": sum(int(row["recursive_size_bytes"]) for row in alt_venvs),
            "state_cache_review_size_bytes": int(state_rows[0]["recursive_size_bytes"]) if state_rows else 0,
            "cold_archive_review_candidate_count": len(cold),
            "cold_archive_review_candidate_size_bytes": sum(int(row["recursive_size_bytes"]) for row in cold),
            "immediate_deletion_candidate_count": len(immediate),
            "immediate_deletion_candidate_size_bytes": sum(int(row["recursive_size_bytes"]) for row in immediate),
            "final_status": final_status,
            "final_decision": final_decision,
            **policy_flags(),
        }
        write_csv(output / "repo_second_pass_top_level_size.csv", top_rows, TOP_FIELDS)
        write_csv(output / "repo_second_pass_largest_directories.csv", dir_rows, TOP_FIELDS)
        write_csv(output / "repo_second_pass_largest_files.csv", file_rows, LARGEST_FILE_FIELDS)
        write_csv(output / "cleanup_target_risk_budget.csv", target_rows, TARGET_FIELDS)
        write_csv(output / "virtualenv_retirement_candidate_audit.csv", venv_rows, VENV_FIELDS)
        write_csv(output / "state_directory_cleanup_candidate_audit.csv", state_rows, STATE_FIELDS)
        write_csv(output / "archive_directory_retention_audit.csv", archive_rows, ARCHIVE_FIELDS)
        write_csv(output / "large_historical_output_cold_archive_candidate_audit.csv", historical_rows, HISTORICAL_FIELDS)
        write_csv(output / "protected_path_presence_check.csv", presence, PRESENCE_FIELDS)
        write_json(output / "v21_211_summary.json", summary)
        write_report(output / "V21.211_second_pass_cleanup_target_discovery_report.txt", summary, target_rows)
    except Exception as exc:
        summary = {
            "stage": STAGE,
            "final_status": "FAIL_V21_211_SECOND_PASS_DISCOVERY_EXCEPTION",
            "final_decision": "SECOND_PASS_CLEANUP_DISCOVERY_FAILED",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            **policy_flags(),
        }
        write_json(output / "v21_211_summary.json", summary)
        (output / "V21.211_second_pass_cleanup_target_discovery_report.txt").write_text(
            "\n".join([STAGE, f"final_status={summary['final_status']}", f"final_decision={summary['final_decision']}", f"error={summary['error_type']}: {summary['error_message']}"]) + "\n",
            encoding="utf-8",
        )
    for key in ["final_status", "final_decision", "repo_total_size_bytes", "alternate_venv_candidate_count", "cold_archive_review_candidate_count", "immediate_deletion_candidate_count", "deletion_performed", "broker_action_allowed"]:
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
