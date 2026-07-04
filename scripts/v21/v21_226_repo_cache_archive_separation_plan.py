#!/usr/bin/env python
"""V21.226 repo/cache/archive separation plan.

Plan-only governance step. Reads V21.224/V21.225 artifacts and writes V21.226
planning artifacts only.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


STAGE = "V21.226_REPO_CACHE_ARCHIVE_SEPARATION_PLAN"
OUT_REL = Path("outputs/v21") / STAGE
V225_REL = Path("outputs/v21/V21.225_SYSTEM_REVIEW_DEPRECATION_AND_CLEANUP_AUDIT")
V224_REL = Path("outputs/v21/V21.224_PRE_MIGRATION_RESULT_ARCHIVE_AND_MANIFEST_FREEZE")
DEFAULT_CACHE_ROOT = Path(r"D:\us-tech-quant-cache")
DEFAULT_ARCHIVE_ROOT = Path(r"D:\us-tech-quant-archive")
DEFAULT_QUARANTINE_ROOT = Path(r"D:\us-tech-quant-quarantine")
PASS_STATUS = "PASS_V21_226_REPO_CACHE_ARCHIVE_SEPARATION_PLAN_READY"
WARN_STATUS = "WARN_V21_226_REPO_CACHE_ARCHIVE_SEPARATION_PLAN_READY_WITH_USER_REVIEW_ITEMS"
FAIL_STATUS = "FAIL_V21_226_MISSING_V21_225_AUDIT_INPUTS"
FINAL_DECISION = "REPO_CACHE_ARCHIVE_SEPARATION_PLAN_READY_FOR_DRY_RUN_ONLY"
LARGE_THRESHOLD = 5_242_880

REQUIRED_V225 = [
    "system_file_inventory.csv",
    "module_status_registry.csv",
    "large_file_inventory.csv",
    "yfinance_artifact_inventory.csv",
    "moomoo_only_readiness_audit.csv",
    "paused_project_review_list.csv",
    "delete_candidates_review_only.csv",
    "v21_224_protected_archive_crosscheck.csv",
    "dram_outcome_pattern_crosscheck.csv",
    "cleanup_policy.json",
]

MASTER_FIELDS = [
    "source_path",
    "relative_path",
    "size_bytes",
    "current_status",
    "target_action",
    "target_root",
    "target_relative_path",
    "proposed_target_path",
    "artifact_type",
    "inferred_module",
    "active_dependency",
    "protected_by_v21_224",
    "protected_by_v21_225",
    "yfinance_related",
    "moomoo_related",
    "dram_related",
    "abcde_related",
    "v20_related",
    "v21_related",
    "requires_user_review",
    "delete_after_verification_only",
    "immediate_delete_allowed",
    "immediate_move_allowed",
    "immediate_copy_allowed",
    "pointer_required",
    "sha256_required",
    "reason",
    "notes",
]
REPO_KEEP_FIELDS = ["source_path", "reason", "lightweight_policy", "max_expected_size_bytes", "pointer_required", "active_dependency"]
CACHE_FIELDS = ["source_path", "proposed_cache_path", "cache_category", "data_source_policy", "active_runtime_needed", "sha256_required", "pointer_required", "reason"]
ARCHIVE_FIELDS = ["source_path", "proposed_archive_path", "archive_category", "protected_evidence", "user_review_required", "sha256_required", "pointer_required", "reason"]
QUARANTINE_FIELDS = ["source_path", "proposed_quarantine_path", "reason", "conflict_type", "user_review_required", "verification_required"]
DELETE_FIELDS = ["source_path", "size_bytes", "reason", "required_pre_delete_checks", "protected_blocker", "user_review_blocker", "archive_or_cache_copy_required", "immediate_delete_allowed"]
USER_REVIEW_FIELDS = ["source_path", "project_name", "reason", "latest_status", "continue_value_score", "fit_with_dram_only_focus", "recommended_review_action"]
PROTECTED_FIELDS = ["source_path", "reason", "protected_by", "no_action_until"]
POINTER_FIELDS = ["source_path", "future_repo_pointer_path", "target_external_path", "pointer_type", "required_fields", "reason"]
ORDER_FIELDS = ["step_number", "phase_name", "action", "allowed_to_execute_now", "prerequisite", "expected_next_script", "notes"]
STORAGE_FIELDS = ["category", "file_count", "total_bytes", "total_mb", "proposed_action", "expected_repo_bytes_reduced_after_future_execution", "notes"]
CACHE_LAYOUT_FIELDS = ["cache_category", "proposed_path", "source_policy", "allowed_data_source", "yfinance_allowed", "active_runtime_needed", "retention_policy"]
ARCHIVE_LAYOUT_FIELDS = ["archive_category", "proposed_path", "immutable", "protected_evidence", "retention_policy", "pointer_required"]
CROSS_FIELDS = ["artifact", "source", "found", "status", "notes"]


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


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


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")


def as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def rel_from_source(row: dict[str, str]) -> str:
    return row.get("relative_path") or Path(row.get("source_path") or row.get("path") or "").name


def norm(text: str) -> str:
    return text.upper().replace("\\", "/")


def safe_name(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", path).strip("_")


def is_repo_keep(row: dict[str, str]) -> bool:
    rel = norm(rel_from_source(row))
    ext = row.get("extension", "").lower()
    artifact = row.get("inferred_artifact_type", "")
    if rel.startswith(("SCRIPTS/", "DOCS/")):
        return True
    if rel.endswith((".PY", ".PS1", ".MD", ".TOML", ".YAML", ".YML", ".INI", ".CFG")):
        return True
    if "TEST_" in rel or rel.endswith("_TEST.PY"):
        return True
    if rel.endswith("SUMMARY.JSON") or rel.endswith("REPORT.TXT") or "POINTER_MANIFEST" in rel:
        return int(row.get("size_bytes") or 0) < LARGE_THRESHOLD
    return artifact in {"python_code", "powershell_wrapper", "report_or_doc"} and int(row.get("size_bytes") or 0) < LARGE_THRESHOLD


def cache_category(row: dict[str, str]) -> str:
    rel = norm(rel_from_source(row))
    if "RAW" in rel:
        return "raw/moomoo"
    if "CANONICAL" in rel:
        return "canonical/ohlcv"
    if "INTRADAY" in rel:
        return "intraday"
    if "FEATURE" in rel:
        return "features"
    if "REGISTRY" in rel:
        return "registry"
    return "runtime"


def archive_category(row: dict[str, str]) -> str:
    status = row.get("primary_status", row.get("current_status", ""))
    rel = norm(rel_from_source(row))
    if as_bool(row.get("protected_by_v21_224")) or status == "PROTECTED_EVIDENCE":
        return "protected_evidence"
    if "V20" in rel:
        return "historical_v20"
    if "BACKTEST" in rel or "MATRIX" in rel:
        return "backtests"
    if "REPORT" in rel:
        return "reports"
    if status == "PAUSED_REVIEW_REQUIRED":
        return "paused_projects"
    return "historical_outputs"


def target_for(row: dict[str, str], action: str, cache_root: Path, archive_root: Path, quarantine_root: Path) -> tuple[str, str, str]:
    rel = rel_from_source(row)
    if action == "MOVE_TO_CACHE_PLAN":
        target_rel = f"v21/{cache_category(row)}/{rel}".replace("//", "/")
        return str(cache_root), target_rel, str(cache_root / Path(target_rel))
    if action == "MOVE_TO_ARCHIVE_PLAN":
        target_rel = f"v21/{archive_category(row)}/{rel}".replace("//", "/")
        return str(archive_root), target_rel, str(archive_root / Path(target_rel))
    if action == "QUARANTINE_PLAN":
        target_rel = f"v21/{safe_name(row.get('primary_status','conflict'))}/{rel}".replace("//", "/")
        return str(quarantine_root), target_rel, str(quarantine_root / Path(target_rel))
    return "", "", ""


def choose_action(row: dict[str, str]) -> tuple[str, str]:
    status = row.get("primary_status", "")
    rel = norm(rel_from_source(row))
    size = int(row.get("size_bytes") or 0)
    protected = as_bool(row.get("protected_by_v21_224")) or status == "PROTECTED_EVIDENCE"
    yfin = as_bool(row.get("yfinance_related")) or "YFINANCE" in rel or "YAHOO" in rel
    moomoo = as_bool(row.get("moomoo_related")) or "MOOMOO" in rel
    active = status in {"ACTIVE_CORE", "ACTIVE_SUPPORT"}
    if protected:
        if is_repo_keep(row):
            return "PROTECTED_NO_ACTION", "Protected evidence is lightweight or governance output; no action until pointer verification"
        return "MOVE_TO_ARCHIVE_PLAN", "Protected research evidence belongs in immutable archive plan"
    if status == "PAUSED_REVIEW_REQUIRED":
        return "USER_REVIEW_REQUIRED", "Paused project must be reviewed by user and is not safe delete"
    if status == "QUARANTINE_CANDIDATE":
        return "QUARANTINE_PLAN", "Uncertain or failed/conflicted artifact requires quarantine review"
    if yfin:
        if "CACHE" in rel or "TMP" in rel:
            return "DELETE_AFTER_VERIFICATION_PLAN", "Deprecated yfinance/Yahoo cache only; delete after verification only"
        return "QUARANTINE_PLAN", "Deprecated external-source artifact cannot enter active chain"
    if status == "DELETE_CANDIDATE_REVIEW_ONLY":
        return "DELETE_AFTER_VERIFICATION_PLAN", "Scratch/cache/duplicate candidate; delete after verification only"
    if active and (moomoo or as_bool(row.get("dram_related")) or as_bool(row.get("abcde_related"))) and size >= LARGE_THRESHOLD:
        return "MOVE_TO_CACHE_PLAN", "Large active runtime artifact should be externalized to cache"
    if active and moomoo and any(token in rel for token in ["RAW", "CANONICAL", "FEATURE", "INTRADAY", "CACHE"]):
        return "MOVE_TO_CACHE_PLAN", "Active Moomoo data/cache artifact belongs in cache plan"
    if is_repo_keep(row):
        return "KEEP_IN_REPO", "Repo should keep code, wrappers, docs, compact summaries, reports, and pointers"
    if status in {"ARCHIVE_ONLY", "DIAGNOSTIC_ONLY", "DEPRECATED"}:
        return "MOVE_TO_ARCHIVE_PLAN", "Historical/diagnostic/deprecated artifact should be archived for evidence"
    if status == "UNKNOWN_REVIEW_REQUIRED":
        return "UNKNOWN_REVIEW_REQUIRED", "No deterministic target; user review required"
    return "KEEP_IN_REPO", "Small active/support artifact remains in repo"


def build_master(rows: list[dict[str, str]], cache_root: Path, archive_root: Path, quarantine_root: Path) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        action, reason = choose_action(row)
        target_root, target_rel, target_path = target_for(row, action, cache_root, archive_root, quarantine_root)
        external = action in {"MOVE_TO_CACHE_PLAN", "MOVE_TO_ARCHIVE_PLAN", "QUARANTINE_PLAN"}
        delete_plan = action == "DELETE_AFTER_VERIFICATION_PLAN"
        out.append(
            {
                "source_path": row.get("path") or row.get("source_path"),
                "relative_path": rel_from_source(row),
                "size_bytes": row.get("size_bytes", "0"),
                "current_status": row.get("primary_status", ""),
                "target_action": action,
                "target_root": target_root,
                "target_relative_path": target_rel,
                "proposed_target_path": target_path,
                "artifact_type": row.get("inferred_artifact_type", ""),
                "inferred_module": row.get("inferred_module", ""),
                "active_dependency": row.get("primary_status") in {"ACTIVE_CORE", "ACTIVE_SUPPORT", "PROTECTED_EVIDENCE"},
                "protected_by_v21_224": as_bool(row.get("protected_by_v21_224")),
                "protected_by_v21_225": row.get("primary_status") == "PROTECTED_EVIDENCE",
                "yfinance_related": as_bool(row.get("yfinance_related")),
                "moomoo_related": as_bool(row.get("moomoo_related")),
                "dram_related": as_bool(row.get("dram_related")),
                "abcde_related": as_bool(row.get("abcde_related")),
                "v20_related": as_bool(row.get("v20_related")),
                "v21_related": as_bool(row.get("v21_related")),
                "requires_user_review": action in {"USER_REVIEW_REQUIRED", "QUARANTINE_PLAN", "UNKNOWN_REVIEW_REQUIRED"},
                "delete_after_verification_only": delete_plan,
                "immediate_delete_allowed": False,
                "immediate_move_allowed": False,
                "immediate_copy_allowed": False,
                "pointer_required": external,
                "sha256_required": external or delete_plan,
                "reason": reason,
                "notes": "plan_only_no_mutation",
            }
        )
    return out


def repo_keep_plan(master: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"source_path": r["source_path"], "reason": r["reason"], "lightweight_policy": "summary_report_pointer_or_code_only", "max_expected_size_bytes": LARGE_THRESHOLD, "pointer_required": r["pointer_required"], "active_dependency": r["active_dependency"]} for r in master if r["target_action"] == "KEEP_IN_REPO"]


def cache_plan(master: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"source_path": r["source_path"], "proposed_cache_path": r["proposed_target_path"], "cache_category": r["target_relative_path"].split("/")[1] if r["target_relative_path"] else "", "data_source_policy": "MOOMOO_ONLY_NO_YFINANCE", "active_runtime_needed": r["active_dependency"], "sha256_required": True, "pointer_required": True, "reason": r["reason"]} for r in master if r["target_action"] == "MOVE_TO_CACHE_PLAN"]


def archive_plan(master: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"source_path": r["source_path"], "proposed_archive_path": r["proposed_target_path"], "archive_category": r["target_relative_path"].split("/")[1] if r["target_relative_path"] else "", "protected_evidence": r["protected_by_v21_224"] or r["protected_by_v21_225"], "user_review_required": r["requires_user_review"], "sha256_required": True, "pointer_required": True, "reason": r["reason"]} for r in master if r["target_action"] == "MOVE_TO_ARCHIVE_PLAN"]


def quarantine_plan(master: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"source_path": r["source_path"], "proposed_quarantine_path": r["proposed_target_path"], "reason": r["reason"], "conflict_type": r["current_status"], "user_review_required": True, "verification_required": True} for r in master if r["target_action"] == "QUARANTINE_PLAN"]


def delete_plan(master: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"source_path": r["source_path"], "size_bytes": r["size_bytes"], "reason": r["reason"], "required_pre_delete_checks": "confirm no active dependency; confirm not protected; confirm archive/cache copy if needed; explicit user approval", "protected_blocker": r["protected_by_v21_224"] or r["protected_by_v21_225"], "user_review_blocker": r["requires_user_review"], "archive_or_cache_copy_required": True, "immediate_delete_allowed": False} for r in master if r["target_action"] == "DELETE_AFTER_VERIFICATION_PLAN"]


def user_review_plan(master: list[dict[str, Any]], module_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_module = {r.get("module_name", ""): r for r in module_rows}
    rows = []
    for r in master:
        if r["target_action"] in {"USER_REVIEW_REQUIRED", "UNKNOWN_REVIEW_REQUIRED"}:
            mod = by_module.get(r["inferred_module"], {})
            rows.append({"source_path": r["source_path"], "project_name": r["inferred_module"], "reason": r["reason"], "latest_status": mod.get("latest_final_status", r["current_status"]), "continue_value_score": mod.get("continue_value_score", ""), "fit_with_dram_only_focus": mod.get("fit_with_dram_only_focus", ""), "recommended_review_action": "USER_DECISION_REQUIRED_BEFORE_ANY_MIGRATION_OR_DELETE"})
    return rows


def protected_plan(master: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"source_path": r["source_path"], "reason": r["reason"], "protected_by": "V21.224" if r["protected_by_v21_224"] else "V21.225", "no_action_until": "external_pointer_verification_and_user_approval"} for r in master if r["target_action"] == "PROTECTED_NO_ACTION"]


def pointer_plan(master: list[dict[str, Any]], repo_root: Path) -> list[dict[str, Any]]:
    rows = []
    for r in master:
        if r["pointer_required"]:
            future = repo_root / "outputs" / "_pointers" / (safe_name(r["relative_path"]) + ".pointer.json")
            rows.append({"source_path": r["source_path"], "future_repo_pointer_path": str(future), "target_external_path": r["proposed_target_path"], "pointer_type": "cache_pointer" if r["target_action"] == "MOVE_TO_CACHE_PLAN" else "archive_pointer" if r["target_action"] == "MOVE_TO_ARCHIVE_PLAN" else "quarantine_pointer", "required_fields": "source_path|target_path|sha256|size_bytes|created_at_utc|policy_flags", "reason": r["reason"]})
    return rows


def directory_layout(cache_root: Path, archive_root: Path, quarantine_root: Path) -> dict[str, Any]:
    return {
        "repo": {"root": r"D:\us-tech-quant", "keeps": ["scripts", "tests", "config", "docs", "compact reports", "pointer manifests", "root orchestration wrappers"]},
        "cache": {"root": str(cache_root), "env_override": "US_TECH_QUANT_CACHE_ROOT", "tree": ["data/raw/moomoo", "data/canonical/ohlcv", "features", "intraday", "tmp", "registry"]},
        "archive": {"root": str(archive_root), "env_override": "US_TECH_QUANT_ARCHIVE_ROOT", "tree": ["v21/protected_evidence", "v21/historical_outputs", "v21/backtests", "v21/reports", "v20"]},
        "quarantine": {"root": str(quarantine_root), "env_override": "US_TECH_QUANT_QUARANTINE_ROOT", "tree": ["v21/conflicted", "v21/external_source", "v21/failed_partial", "review_required"]},
    }


def migration_order() -> list[dict[str, Any]]:
    steps = [
        ("V21.226 plan-only", "create separation plan", "V21.227 migration dry-run"),
        ("V21.227 migration dry-run", "simulate target paths and verification", "V21.228 copy-only externalization"),
        ("V21.228 copy-only externalization", "copy selected files to cache/archive", "V21.229 Moomoo-only data source policy gate"),
        ("V21.229 Moomoo-only data source policy gate", "block non-Moomoo canonical data", "V21.230 Moomoo-only historical refetch dry-run"),
        ("V21.230 Moomoo-only historical refetch dry-run", "plan Moomoo refetch", "V21.231 Moomoo-only canonical rebuild"),
        ("V21.231 Moomoo-only canonical rebuild", "rebuild canonical data", "V21.232 Moomoo-only DRAM rerun"),
        ("V21.232 Moomoo-only DRAM rerun", "rerun DRAM chain", "V21.233 Moomoo-only ABCDE rerun"),
        ("V21.233 Moomoo-only ABCDE rerun", "rerun compact ranking", "V21.234 minimal daily research chain"),
        ("V21.234 minimal daily research chain", "assemble minimal active chain", "V21.235 clean delete after verification"),
        ("V21.235 clean delete after verification", "delete only after verification and approval", "V21.236 paused project review package"),
        ("V21.236 paused project review package", "package paused project review", ""),
    ]
    return [{"step_number": i, "phase_name": p, "action": a, "allowed_to_execute_now": i == 1, "prerequisite": "V21.224/V21.225 complete" if i == 1 else f"step_{i-1}_complete", "expected_next_script": n, "notes": "plan_only" if i == 1 else "future_governed_step"} for i, (p, a, n) in enumerate(steps, 1)]


def storage_projection(master: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in master:
        grouped.setdefault(r["target_action"], []).append(r)
    rows = []
    reducible_actions = {"MOVE_TO_CACHE_PLAN", "MOVE_TO_ARCHIVE_PLAN", "QUARANTINE_PLAN", "DELETE_AFTER_VERIFICATION_PLAN"}
    for action, items in sorted(grouped.items()):
        total = sum(int(r["size_bytes"] or 0) for r in items)
        rows.append({"category": action, "file_count": len(items), "total_bytes": total, "total_mb": round(total / (1024 * 1024), 3), "proposed_action": action, "expected_repo_bytes_reduced_after_future_execution": total if action in reducible_actions else 0, "notes": "projection_only_no_current_mutation"})
    return rows


def cache_layout_plan(cache_root: Path) -> list[dict[str, Any]]:
    return [
        {"cache_category": "raw_moomoo", "proposed_path": str(cache_root / "data/raw/moomoo"), "source_policy": "broker_data_api_or_approved_export_only", "allowed_data_source": "Moomoo", "yfinance_allowed": False, "active_runtime_needed": True, "retention_policy": "active_with_registry"},
        {"cache_category": "canonical_ohlcv", "proposed_path": str(cache_root / "data/canonical/ohlcv"), "source_policy": "Moomoo-only canonical rebuild", "allowed_data_source": "Moomoo", "yfinance_allowed": False, "active_runtime_needed": True, "retention_policy": "protected_active"},
        {"cache_category": "features", "proposed_path": str(cache_root / "features"), "source_policy": "derived from Moomoo canonical", "allowed_data_source": "Moomoo-derived", "yfinance_allowed": False, "active_runtime_needed": True, "retention_policy": "refreshable"},
        {"cache_category": "intraday", "proposed_path": str(cache_root / "intraday"), "source_policy": "Moomoo intraday only", "allowed_data_source": "Moomoo", "yfinance_allowed": False, "active_runtime_needed": True, "retention_policy": "rolling"},
        {"cache_category": "tmp", "proposed_path": str(cache_root / "tmp"), "source_policy": "runtime temporary", "allowed_data_source": "Moomoo-derived", "yfinance_allowed": False, "active_runtime_needed": False, "retention_policy": "delete_after_verification"},
    ]


def archive_layout_plan(archive_root: Path) -> list[dict[str, Any]]:
    return [
        {"archive_category": "protected_evidence", "proposed_path": str(archive_root / "v21/protected_evidence"), "immutable": True, "protected_evidence": True, "retention_policy": "indefinite", "pointer_required": True},
        {"archive_category": "historical_outputs", "proposed_path": str(archive_root / "v21/historical_outputs"), "immutable": True, "protected_evidence": False, "retention_policy": "long_term", "pointer_required": True},
        {"archive_category": "backtests", "proposed_path": str(archive_root / "v21/backtests"), "immutable": True, "protected_evidence": False, "retention_policy": "long_term", "pointer_required": True},
        {"archive_category": "reports", "proposed_path": str(archive_root / "v21/reports"), "immutable": True, "protected_evidence": False, "retention_policy": "long_term", "pointer_required": True},
        {"archive_category": "v20", "proposed_path": str(archive_root / "v20"), "immutable": True, "protected_evidence": False, "retention_policy": "historical", "pointer_required": True},
    ]


def policy_json(threshold: int) -> dict[str, Any]:
    return {
        "repo_large_artifacts_disallowed": True,
        "repo_outputs_should_keep_only_summary_report_pointer": True,
        "large_artifact_threshold_bytes": threshold,
        "cache_for_active_data": True,
        "archive_for_historical_results": True,
        "quarantine_for_uncertain_or_conflicted_artifacts": True,
        "immediate_delete_allowed": False,
        "immediate_move_allowed": False,
        "immediate_copy_allowed": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
    }


def dependency_crosscheck(v225: Path, v224: Path) -> list[dict[str, Any]]:
    rows = []
    for name in REQUIRED_V225:
        rows.append({"artifact": name, "source": "V21.225", "found": (v225 / name).exists(), "status": "FOUND" if (v225 / name).exists() else "MISSING", "notes": "required V21.225 planning input"})
    for name in ["archive_pointer_manifest.json", "v21_224_summary.json"]:
        rows.append({"artifact": name, "source": "V21.224", "found": (v224 / name).exists(), "status": "FOUND" if (v224 / name).exists() else "MISSING", "notes": "optional V21.224 context"})
    dram = read_csv(v225 / "dram_outcome_pattern_crosscheck.csv")
    status = dram[0].get("crosscheck_status", "") if dram else ""
    rows.append({"artifact": "DRAM_OUTCOME_WARNING", "source": "V21.225", "found": bool(status), "status": status or "MISSING", "notes": "PATTERN_MISS_ONLY is treated as resolved warning note"})
    return rows


def run(repo_root: Path | None = None, output_dir: Path | None = None, v21_225_output_dir: Path | None = None, v21_224_output_dir: Path | None = None, cache_root: Path = DEFAULT_CACHE_ROOT, archive_root: Path = DEFAULT_ARCHIVE_ROOT, quarantine_root: Path = DEFAULT_QUARANTINE_ROOT, large_threshold_bytes: int = LARGE_THRESHOLD) -> dict[str, Any]:
    root = (repo_root or default_repo_root()).resolve()
    out = (output_dir or root / OUT_REL).resolve()
    v225 = (v21_225_output_dir or root / V225_REL).resolve()
    v224 = (v21_224_output_dir or root / V224_REL).resolve()
    missing = [name for name in REQUIRED_V225 if not (v225 / name).exists()]
    try:
        out.mkdir(parents=True, exist_ok=True)
        if missing:
            summary = {"final_status": FAIL_STATUS, "final_decision": "V21_225_AUDIT_INPUTS_REQUIRED_BEFORE_SEPARATION_PLAN", "repo_root": str(root), "output_dir": str(out), "cache_root_planned": str(cache_root), "archive_root_planned": str(archive_root), "quarantine_root_planned": str(quarantine_root), "input_v21_225_found": False, "input_v21_224_found": (v224 / "archive_pointer_manifest.json").exists(), "total_planned_items": 0, "keep_in_repo_count": 0, "cache_migration_plan_count": 0, "archive_migration_plan_count": 0, "quarantine_plan_count": 0, "delete_after_verification_plan_count": 0, "user_review_required_count": 0, "protected_no_action_count": 0, "pointer_manifest_plan_count": 0, "projected_future_repo_bytes_reducible": 0, "immediate_delete_allowed": False, "immediate_move_allowed": False, "immediate_copy_allowed": False, "yfinance_used": False, "data_fetch_used": False, "moomoo_import_used": False, "broker_action_allowed": False, "official_adoption_allowed": False, "research_only": True, "warning_count": 0, "error_count": 1, "missing_inputs": missing}
            write_json(out / "v21_226_summary.json", summary)
            return summary
        inv = read_csv(v225 / "system_file_inventory.csv")
        modules = read_csv(v225 / "module_status_registry.csv")
        master = build_master(inv, cache_root, archive_root, quarantine_root)
        repo_rows = repo_keep_plan(master)
        cache_rows = cache_plan(master)
        archive_rows = archive_plan(master)
        quarantine_rows = quarantine_plan(master)
        delete_rows = delete_plan(master)
        review_rows = user_review_plan(master, modules)
        protected_rows = protected_plan(master)
        pointer_rows = pointer_plan(master, root)
        storage_rows = storage_projection(master)
        cross_rows = dependency_crosscheck(v225, v224)
        projected = sum(int(r["expected_repo_bytes_reduced_after_future_execution"]) for r in storage_rows)
        warning_count = 1 if review_rows else 0
        summary = {
            "final_status": WARN_STATUS if review_rows else PASS_STATUS,
            "final_decision": FINAL_DECISION,
            "repo_root": str(root),
            "output_dir": str(out),
            "cache_root_planned": str(cache_root),
            "archive_root_planned": str(archive_root),
            "quarantine_root_planned": str(quarantine_root),
            "input_v21_225_found": True,
            "input_v21_224_found": (v224 / "archive_pointer_manifest.json").exists(),
            "total_planned_items": len(master),
            "keep_in_repo_count": len(repo_rows),
            "cache_migration_plan_count": len(cache_rows),
            "archive_migration_plan_count": len(archive_rows),
            "quarantine_plan_count": len(quarantine_rows),
            "delete_after_verification_plan_count": len(delete_rows),
            "user_review_required_count": len(review_rows),
            "protected_no_action_count": len(protected_rows),
            "pointer_manifest_plan_count": len(pointer_rows),
            "projected_future_repo_bytes_reducible": projected,
            "immediate_delete_allowed": False,
            "immediate_move_allowed": False,
            "immediate_copy_allowed": False,
            "yfinance_used": False,
            "data_fetch_used": False,
            "moomoo_import_used": False,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "research_only": True,
            "warning_count": warning_count,
            "error_count": 0,
        }
        write_csv(out / "separation_plan_master.csv", master, MASTER_FIELDS)
        write_csv(out / "repo_keep_plan.csv", repo_rows, REPO_KEEP_FIELDS)
        write_csv(out / "cache_migration_plan.csv", cache_rows, CACHE_FIELDS)
        write_csv(out / "archive_migration_plan.csv", archive_rows, ARCHIVE_FIELDS)
        write_csv(out / "quarantine_plan.csv", quarantine_rows, QUARANTINE_FIELDS)
        write_csv(out / "delete_after_verification_plan.csv", delete_rows, DELETE_FIELDS)
        write_csv(out / "user_review_required_plan.csv", review_rows, USER_REVIEW_FIELDS)
        write_csv(out / "protected_no_action_plan.csv", protected_rows, PROTECTED_FIELDS)
        write_csv(out / "pointer_manifest_plan.csv", pointer_rows, POINTER_FIELDS)
        write_json(out / "directory_layout_plan.json", directory_layout(cache_root, archive_root, quarantine_root))
        write_csv(out / "migration_order_plan.csv", migration_order(), ORDER_FIELDS)
        write_csv(out / "storage_impact_projection.csv", storage_rows, STORAGE_FIELDS)
        write_csv(out / "moomoo_only_cache_layout_plan.csv", cache_layout_plan(cache_root), CACHE_LAYOUT_FIELDS)
        write_csv(out / "archive_layout_plan.csv", archive_layout_plan(archive_root), ARCHIVE_LAYOUT_FIELDS)
        write_json(out / "repo_lightweight_output_policy.json", policy_json(large_threshold_bytes))
        write_csv(out / "v21_224_225_dependency_crosscheck.csv", cross_rows, CROSS_FIELDS)
        write_json(out / "v21_226_summary.json", summary)
        report = "\n".join([STAGE, *[f"{k}={summary[k]}" for k in ["final_status", "final_decision", "total_planned_items", "keep_in_repo_count", "cache_migration_plan_count", "archive_migration_plan_count", "quarantine_plan_count", "delete_after_verification_plan_count", "user_review_required_count", "protected_no_action_count", "projected_future_repo_bytes_reducible", "warning_count", "error_count"]], "plan_only=True", "immediate_delete_allowed=False", "immediate_move_allowed=False", "immediate_copy_allowed=False"]) + "\n"
        (out / "V21.226_repo_cache_archive_separation_plan_report.txt").write_text(report, encoding="utf-8")
    except Exception as exc:
        summary = {"final_status": FAIL_STATUS, "final_decision": "V21_226_PLAN_GENERATION_FAILED", "repo_root": str(root), "output_dir": str(out), "cache_root_planned": str(cache_root), "archive_root_planned": str(archive_root), "quarantine_root_planned": str(quarantine_root), "input_v21_225_found": not bool(missing), "input_v21_224_found": (v224 / "archive_pointer_manifest.json").exists(), "total_planned_items": 0, "keep_in_repo_count": 0, "cache_migration_plan_count": 0, "archive_migration_plan_count": 0, "quarantine_plan_count": 0, "delete_after_verification_plan_count": 0, "user_review_required_count": 0, "protected_no_action_count": 0, "pointer_manifest_plan_count": 0, "projected_future_repo_bytes_reducible": 0, "immediate_delete_allowed": False, "immediate_move_allowed": False, "immediate_copy_allowed": False, "yfinance_used": False, "data_fetch_used": False, "moomoo_import_used": False, "broker_action_allowed": False, "official_adoption_allowed": False, "research_only": True, "warning_count": 0, "error_count": 1, "error_message": f"{type(exc).__name__}: {exc}"}
        try:
            write_json(out / "v21_226_summary.json", summary)
        except Exception:
            pass
    for key in ["final_status", "final_decision", "total_planned_items", "keep_in_repo_count", "cache_migration_plan_count", "archive_migration_plan_count", "quarantine_plan_count", "delete_after_verification_plan_count", "user_review_required_count", "protected_no_action_count", "projected_future_repo_bytes_reducible", "warning_count", "error_count"]:
        print(f"{key}={summary[key]}")
    print(f"summary_path={out / 'v21_226_summary.json'}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=STAGE)
    p.add_argument("--repo-root")
    p.add_argument("--output-dir")
    p.add_argument("--v21-225-output-dir")
    p.add_argument("--v21-224-output-dir")
    p.add_argument("--cache-root", default=str(DEFAULT_CACHE_ROOT))
    p.add_argument("--archive-root", default=str(DEFAULT_ARCHIVE_ROOT))
    p.add_argument("--quarantine-root", default=str(DEFAULT_QUARANTINE_ROOT))
    p.add_argument("--large-threshold-bytes", type=int, default=LARGE_THRESHOLD)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(
        repo_root=Path(args.repo_root) if args.repo_root else None,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        v21_225_output_dir=Path(args.v21_225_output_dir) if args.v21_225_output_dir else None,
        v21_224_output_dir=Path(args.v21_224_output_dir) if args.v21_224_output_dir else None,
        cache_root=Path(args.cache_root),
        archive_root=Path(args.archive_root),
        quarantine_root=Path(args.quarantine_root),
        large_threshold_bytes=args.large_threshold_bytes,
    )
    return 1 if summary["final_status"] == FAIL_STATUS else 0


if __name__ == "__main__":
    sys.exit(main())
