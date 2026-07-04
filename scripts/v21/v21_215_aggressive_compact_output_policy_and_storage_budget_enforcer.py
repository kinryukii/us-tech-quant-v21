#!/usr/bin/env python
"""V21.215 aggressive compact-output policy and storage budget enforcer.

This stage enables compact-output policy helpers and writes aggressive storage
budget plans. It does not delete, compress, move, refresh prices, mutate
canonical files, connect to OpenD, change adoption outputs, or perform broker
actions. Destructive cleanup is deferred to a later explicitly approved stage.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path(r"D:\us-tech-quant")
STAGE = "V21.215_AGGRESSIVE_COMPACT_OUTPUT_POLICY_AND_STORAGE_BUDGET_ENFORCER"
OUT_REL = Path("outputs/v21/V21.215_AGGRESSIVE_COMPACT_OUTPUT_POLICY_AND_STORAGE_BUDGET_ENFORCER")
REGISTRY_REL = Path("outputs/v21/V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY/artifact_registry.csv")
TARGET_REPO_SIZE_BYTES = 1_000_000_000
HARD_WARNING_THRESHOLD_BYTES = 1_200_000_000
CURRENT_CHAIN_OUTPUTS_BUDGET_BYTES = 350_000_000
ARCHIVE_BUDGET_BYTES = 250_000_000
STATE_BUDGET_BYTES = 50_000_000
CACHE_BUDGET_BYTES = 20_000_000
REQUIRED_APPROVAL_PHRASE = "APPROVE_V21_216_AGGRESSIVE_COMPACT_AND_DELETE_EXPANDED_OUTPUTS"
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
    "outputs/v21/V21.211_SECOND_PASS_CLEANUP_TARGET_DISCOVERY_AND_RISK_BUDGET",
    "outputs/v21/V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY",
]
HARD_KEEP_STAGE_PREFIXES = {"V21.197", "V21.199", "V21.201", "V21.207", "V21.208", "V21.209", "V21.210", "V21.211", "V21.212"}
SENSITIVE_TOKENS = ["canonical", "price_history", "ohlcv", "kline", "moomoo", "dram", "abcde", "trade_plan", "ledger", "ranking", "latest", "current_chain", "protected"]
LARGE_THRESHOLD_BYTES = 25 * 1024 * 1024
COMPACT_RETAIN_ESTIMATE_BYTES = 2 * 1024 * 1024

PRESENCE_FIELDS = ["protected_key", "expected_path", "exact_exists", "alias_discovery_attempted", "alias_candidate_count", "resolved_exists", "resolved_protected_path", "resolution_method", "warning_reason"]
POLICY_FIELDS = ["policy_key", "policy_value", "policy_scope", "rationale"]
PATCH_FIELDS = ["script_path", "detected_writer_type", "artifact_name_pattern", "likely_large_output_flag", "current_chain_sensitive_flag", "proposed_patch_type", "patch_allowed", "manual_review_required", "rationale"]
CANDIDATE_FIELDS = ["source_path", "current_size_bytes", "retained_compact_size_bytes_estimate", "estimated_zip_size_bytes", "estimated_delete_savings_bytes", "proposed_action", "confidence", "blocker_reasons"]
KEEP_FIELDS = ["artifact_path", "keep_class", "size_bytes", "rationale"]
RECLASS_FIELDS = ["artifact_path", "current_role", "current_retention_class", "proposed_role", "proposed_retention_class", "rationale"]
SIZE_FIELDS = ["repo_total_size_bytes_before", "target_repo_size_bytes", "projected_repo_size_after_aggressive_cleanup", "projected_total_savings_bytes", "hard_warning_threshold_bytes"]
APPROVAL_FIELDS = ["required_manual_approval_phrase", "destructive_cleanup_requires_approval", "deletion_allowed_in_this_run", "compression_allowed_in_this_run", "rationale"]


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


def path_size(path: Path) -> tuple[int, int, int]:
    files = iter_files(path) if path.exists() else []
    size = 0
    for file in files:
        try:
            size += file.stat().st_size
        except OSError:
            pass
    return size, len(files), len(iter_dirs(path)) if path.exists() else 0


def repo_size(root: Path) -> tuple[int, int, int]:
    return path_size(root)


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


def registry_by_stage(root: Path) -> dict[str, dict[str, str]]:
    mapping = {}
    for row in read_csv(root / REGISTRY_REL):
        if row.get("artifact_type") == "stage_directory":
            name = row.get("stage_name") or Path(row.get("artifact_path", "")).name
            if name:
                mapping[name] = row
    return mapping


def policy_rows() -> list[dict[str, Any]]:
    values = {
        "V21_OUTPUT_MODE": "compact",
        "V21_KEEP_FULL_ARTIFACTS": "false",
        "V21_WRITE_INTERMEDIATE_PANELS": "false",
        "V21_WRITE_FULL_TRIAL_LEDGER": "false",
        "V21_WRITE_FULL_REPLAY_PANEL": "false",
        "V21_WRITE_PER_SEED_FULL_DETAILS": "false",
        "V21_SAVE_ONLY_SUMMARY_TOPN_AND_METRICS": "true",
    }
    return [{"policy_key": k, "policy_value": v, "policy_scope": "future_v21_runs", "rationale": "Default to compact artifacts; full outputs require explicit override."} for k, v in values.items()]


def budget_rows() -> list[dict[str, Any]]:
    budgets = {
        "target_repo_size_bytes": TARGET_REPO_SIZE_BYTES,
        "hard_warning_threshold_bytes": HARD_WARNING_THRESHOLD_BYTES,
        "current_chain_outputs_budget_bytes": CURRENT_CHAIN_OUTPUTS_BUDGET_BYTES,
        "archive_budget_bytes": ARCHIVE_BUDGET_BYTES,
        "state_budget_bytes": STATE_BUDGET_BYTES,
        "cache_budget_bytes": CACHE_BUDGET_BYTES,
    }
    return [{"policy_key": k, "policy_value": v, "policy_scope": "repo_storage_budget", "rationale": "Aggressive storage budget target."} for k, v in budgets.items()]


def script_patch_plan(root: Path) -> list[dict[str, Any]]:
    rows = []
    scripts = root / "scripts/v21"
    if not scripts.exists():
        return rows
    writer_patterns = {
        "df.to_csv": r"\.to_csv\(",
        "to_parquet": r"\.to_parquet\(",
        "json_large_dump": r"json\.dump|json\.dumps",
        "csv_writer": r"csv\.DictWriter|csv\.writer",
    }
    for file in sorted(scripts.glob("*.py")):
        if file.name == "v21_storage_policy.py":
            continue
        text = file.read_text(encoding="utf-8", errors="ignore")
        lower = file.name.lower()
        current_sensitive = any(token in lower for token in ["197", "199", "201", "moomoo", "dram", "abcde", "daily"])
        for writer_type, pattern in writer_patterns.items():
            if re.search(pattern, text):
                likely_large = any(token in lower for token in ["backtest", "replay", "diagnostic", "trial", "random", "ledger", "panel"])
                patch_allowed = likely_large and not current_sensitive
                rows.append({
                    "script_path": rel(file, root),
                    "detected_writer_type": writer_type,
                    "artifact_name_pattern": "*.csv/*.json/*.parquet",
                    "likely_large_output_flag": likely_large,
                    "current_chain_sensitive_flag": current_sensitive,
                    "proposed_patch_type": "ADD_COMPACT_MODE_GUARD_OR_USE_V21_STORAGE_POLICY",
                    "patch_allowed": patch_allowed,
                    "manual_review_required": True,
                    "rationale": "Future patch candidate; this stage only installs shared helper and reports writer behavior.",
                })
    return rows


def sensitive_count(path: Path, files: list[Path], root: Path) -> int:
    names = [path.name.lower()] + [rel(file, root).lower() for file in files[:500]]
    return sum(1 for token in SENSITIVE_TOKENS if any(token in item for item in names))


def stage_action(stage: Path, root: Path, reg: dict[str, str], protected_rels: set[str]) -> tuple[str, str, str]:
    name = stage.name
    low = name.lower()
    if any(name.startswith(prefix) for prefix in HARD_KEEP_STAGE_PREFIXES):
        return "KEEP_PROTECTED_CURRENT_CHAIN", "HIGH", "Hard keep protected current/cleanup proof chain."
    if rel(stage, root) in protected_rels or str_bool(reg.get("protected_flag")):
        return "KEEP_PROTECTED_CURRENT_CHAIN", "HIGH", "Protected by registry or protected manifest."
    if str_bool(reg.get("current_chain_required")):
        return "KEEP_CURRENT_DRAM_ABCDE", "HIGH", "Current-chain required registry row."
    files = iter_files(stage)
    size, _fc, _dc = path_size(stage)
    if size < LARGE_THRESHOLD_BYTES and "__pycache__" not in low and "pytest_tmp" not in low:
        return "KEEP_COMPACT_SUMMARY_ONLY", "MEDIUM", "Small enough to keep as compact summary/history."
    if name.startswith("V21.154"):
        return "ZIP_THEN_DELETE_EXPANDED_ORIGINAL", "HIGH", "User changed objective to prioritize repo size; V21.154 has zip evidence and can be proposed for future approved expanded-original deletion."
    if name.startswith("V21.140") or sensitive_count(stage, files, root):
        manual = str_bool(reg.get("manual_approval_required"))
        role = reg.get("artifact_role", "")
        if role in {"DIAGNOSTIC_ONLY", "BACKTEST_RESULT", "AUDIT_CRITICAL_HISTORY", "REPRODUCIBILITY_SUPPORT"} and manual:
            return "ZIP_THEN_DELETE_EXPANDED_ORIGINAL", "MEDIUM", "Sensitive token but registry indicates non-current historical output requiring manual review."
        return "KEEP_CANONICAL_OR_PRICE_SOURCE", "HIGH", "Sensitive price/broker/current-chain keyword blocks aggressive deletion candidate status."
    role = reg.get("artifact_role", "UNKNOWN_REVIEW_REQUIRED")
    if any(token in low for token in ["backtest", "replay", "diagnostic", "trial", "random"]):
        return "DELETE_EXPANDED_ORIGINAL_AFTER_COMPACT_SUMMARY_EXISTS", "MEDIUM", "Large historical backtest/replay/diagnostic output should be compacted under aggressive policy."
    if role in {"BACKTEST_RESULT", "DIAGNOSTIC_ONLY", "UNKNOWN_REVIEW_REQUIRED", "REPRODUCIBILITY_SUPPORT", "AUDIT_CRITICAL_HISTORY"}:
        return "ZIP_THEN_DELETE_EXPANDED_ORIGINAL", "MEDIUM", "Large non-current historical output can be zip-backed then expanded original removed after approval."
    return "MANUAL_REVIEW_REQUIRED", "LOW", "No safe automatic aggressive classification."


def cleanup_candidates(root: Path, protected_rels: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    regmap = registry_by_stage(root)
    out21 = root / "outputs/v21"
    candidates: list[dict[str, Any]] = []
    protected_keep: list[dict[str, Any]] = []
    compact_keep: list[dict[str, Any]] = []
    delete_plan: list[dict[str, Any]] = []
    reclass: list[dict[str, Any]] = []
    if not out21.exists():
        return candidates, protected_keep, compact_keep, delete_plan, reclass
    for stage in sorted([p for p in out21.iterdir() if p.is_dir()], key=lambda p: p.name):
        size, _fc, _dc = path_size(stage)
        reg = regmap.get(stage.name, {})
        action, confidence, rationale = stage_action(stage, root, reg, protected_rels)
        retained = min(COMPACT_RETAIN_ESTIMATE_BYTES, size)
        zip_estimate = int(size * 0.12) if action == "ZIP_THEN_DELETE_EXPANDED_ORIGINAL" else 0
        delete_savings = max(0, size - max(retained, zip_estimate))
        row = {
            "source_path": rel(stage, root),
            "current_size_bytes": size,
            "retained_compact_size_bytes_estimate": retained,
            "estimated_zip_size_bytes": zip_estimate,
            "estimated_delete_savings_bytes": delete_savings if action in {"ZIP_THEN_DELETE_EXPANDED_ORIGINAL", "DELETE_EXPANDED_ORIGINAL_AFTER_COMPACT_SUMMARY_EXISTS", "DELETE_LOW_VALUE_CACHE"} else 0,
            "proposed_action": action,
            "confidence": confidence,
            "blocker_reasons": "" if action in {"ZIP_THEN_DELETE_EXPANDED_ORIGINAL", "DELETE_EXPANDED_ORIGINAL_AFTER_COMPACT_SUMMARY_EXISTS", "DELETE_LOW_VALUE_CACHE"} else rationale,
        }
        candidates.append(row)
        if action.startswith("KEEP_PROTECTED") or action.startswith("KEEP_CANONICAL") or action.startswith("KEEP_CURRENT"):
            protected_keep.append({"artifact_path": row["source_path"], "keep_class": action, "size_bytes": size, "rationale": rationale})
        elif action == "KEEP_COMPACT_SUMMARY_ONLY":
            compact_keep.append({"artifact_path": row["source_path"], "keep_class": action, "size_bytes": retained, "rationale": rationale})
        elif action in {"ZIP_THEN_DELETE_EXPANDED_ORIGINAL", "DELETE_EXPANDED_ORIGINAL_AFTER_COMPACT_SUMMARY_EXISTS", "DELETE_LOW_VALUE_CACHE"}:
            delete_plan.append(row)
        if reg.get("artifact_role") == "UNKNOWN_REVIEW_REQUIRED":
            reclass.append({"artifact_path": row["source_path"], "current_role": reg.get("artifact_role", "UNKNOWN_REVIEW_REQUIRED"), "current_retention_class": reg.get("retention_class", "UNKNOWN_MANUAL_REVIEW"), "proposed_role": "HISTORICAL_EXPANDED_OUTPUT_REVIEW", "proposed_retention_class": "AGGRESSIVE_COMPACT_REVIEW", "rationale": "Unknown registry item requires reclassification before destructive V21.216 action."})
    return candidates, protected_keep, compact_keep, delete_plan, reclass


def projected_rows(repo_before: int, delete_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    savings = sum(int(row["estimated_delete_savings_bytes"]) for row in delete_plan)
    projected = max(0, repo_before - savings)
    return [{
        "repo_total_size_bytes_before": repo_before,
        "target_repo_size_bytes": TARGET_REPO_SIZE_BYTES,
        "projected_repo_size_after_aggressive_cleanup": projected,
        "projected_total_savings_bytes": savings,
        "hard_warning_threshold_bytes": HARD_WARNING_THRESHOLD_BYTES,
    }]


def policy_flags() -> dict[str, Any]:
    return {
        "research_only": True,
        "audit_only": False,
        "compact_output_policy_enabled": True,
        "mutation_allowed_limited_to_storage_policy_helpers_and_guarded_script_patches": True,
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


def summarize(repo_before: int, presence_missing: int, delete_plan: list[dict[str, Any]], protected_keep: list[dict[str, Any]], compact_keep: list[dict[str, Any]], patch_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_action = defaultdict(list)
    for row in delete_plan:
        by_action[row["proposed_action"]].append(row)
    savings = sum(int(row["estimated_delete_savings_bytes"]) for row in delete_plan)
    projected = max(0, repo_before - savings)
    if presence_missing:
        status = "FAIL_V21_215_PROTECTED_PATH_MISSING"
        decision = "AGGRESSIVE_STORAGE_POLICY_FAILED_PROTECTED_PATH_MISSING"
    elif projected > TARGET_REPO_SIZE_BYTES:
        status = "WARN_V21_215_TARGET_1GB_NOT_REACHABLE_WITH_SAFE_CANDIDATES"
        decision = "AGGRESSIVE_STORAGE_POLICY_READY_BUT_1GB_TARGET_NOT_REACHABLE"
    else:
        status = "PASS_V21_215_AGGRESSIVE_STORAGE_POLICY_READY"
        decision = "AGGRESSIVE_COMPACT_OUTPUT_POLICY_READY_DESTRUCTIVE_APPROVAL_REQUIRED"
    return {
        "stage": STAGE,
        "repo_total_size_bytes_before": repo_before,
        "target_repo_size_bytes": TARGET_REPO_SIZE_BYTES,
        "projected_repo_size_after_aggressive_cleanup": projected,
        "projected_total_savings_bytes": savings,
        "protected_keep_size_bytes": sum(int(row["size_bytes"]) for row in protected_keep),
        "current_chain_keep_size_bytes": sum(int(row["size_bytes"]) for row in protected_keep if "CURRENT" in row["keep_class"]),
        "compact_summary_keep_size_bytes": sum(int(row["size_bytes"]) for row in compact_keep),
        "zip_then_delete_candidate_count": len(by_action["ZIP_THEN_DELETE_EXPANDED_ORIGINAL"]),
        "zip_then_delete_candidate_size_bytes": sum(int(row["current_size_bytes"]) for row in by_action["ZIP_THEN_DELETE_EXPANDED_ORIGINAL"]),
        "delete_after_compact_summary_candidate_count": len(by_action["DELETE_EXPANDED_ORIGINAL_AFTER_COMPACT_SUMMARY_EXISTS"]),
        "delete_after_compact_summary_candidate_size_bytes": sum(int(row["current_size_bytes"]) for row in by_action["DELETE_EXPANDED_ORIGINAL_AFTER_COMPACT_SUMMARY_EXISTS"]),
        "low_value_cache_delete_candidate_count": len(by_action["DELETE_LOW_VALUE_CACHE"]),
        "low_value_cache_delete_candidate_size_bytes": sum(int(row["current_size_bytes"]) for row in by_action["DELETE_LOW_VALUE_CACHE"]),
        "script_patch_plan_count": len(patch_rows),
        "script_patch_applied_count": 1,
        "destructive_cleanup_requires_approval": True,
        "required_manual_approval_phrase": REQUIRED_APPROVAL_PHRASE,
        "deletion_allowed_in_this_run": False,
        "compression_allowed_in_this_run": False,
        "protected_path_missing_count": presence_missing,
        "final_status": status,
        "final_decision": decision,
        **policy_flags(),
    }


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"repo_total_size_bytes_before={summary['repo_total_size_bytes_before']}",
        f"target_repo_size_bytes={summary['target_repo_size_bytes']}",
        f"projected_repo_size_after_aggressive_cleanup={summary['projected_repo_size_after_aggressive_cleanup']}",
        f"projected_total_savings_bytes={summary['projected_total_savings_bytes']}",
        f"required_manual_approval_phrase={summary['required_manual_approval_phrase']}",
        "deletion_allowed_in_this_run=false",
        "compression_allowed_in_this_run=false",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(repo_root: Path = DEFAULT_ROOT, out_dir: Path | None = None, simulate_exception: bool = False) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if simulate_exception:
            raise RuntimeError("simulated V21.215 aggressive policy failure")
        presence = protected_presence(root)
        missing = [row for row in presence if not str_bool(row["resolved_exists"])]
        protected_rels = {row["resolved_protected_path"] for row in presence if row.get("resolved_protected_path")}
        repo_before, _files, _dirs = repo_size(root)
        candidates, protected_keep, compact_keep, delete_plan, reclass = cleanup_candidates(root, protected_rels)
        patches = script_patch_plan(root)
        summary = summarize(repo_before, len(missing), delete_plan, protected_keep, compact_keep, patches)
        write_csv(output / "storage_budget_policy.csv", budget_rows(), POLICY_FIELDS)
        write_csv(output / "compact_output_policy_rules.csv", policy_rows(), POLICY_FIELDS)
        write_csv(output / "script_output_behavior_patch_plan.csv", patches, PATCH_FIELDS)
        write_csv(output / "large_artifact_rewrite_or_suppress_plan.csv", delete_plan, CANDIDATE_FIELDS)
        write_csv(output / "aggressive_cleanup_candidate_plan.csv", candidates, CANDIDATE_FIELDS)
        write_csv(output / "protected_artifact_keep_manifest.csv", protected_keep, KEEP_FIELDS)
        write_csv(output / "compact_artifact_keep_manifest.csv", compact_keep, KEEP_FIELDS)
        write_csv(output / "historical_expanded_output_delete_plan.csv", delete_plan, CANDIDATE_FIELDS)
        write_csv(output / "registry_unknown_reclassification_plan.csv", reclass, RECLASS_FIELDS)
        write_csv(output / "projected_repo_size_after_aggressive_cleanup.csv", projected_rows(repo_before, delete_plan), SIZE_FIELDS)
        write_csv(output / "protected_path_presence_check.csv", presence, PRESENCE_FIELDS)
        write_csv(output / "manual_approval_checklist.csv", [{"required_manual_approval_phrase": REQUIRED_APPROVAL_PHRASE, "destructive_cleanup_requires_approval": True, "deletion_allowed_in_this_run": False, "compression_allowed_in_this_run": False, "rationale": "V21.215 only plans; V21.216 must receive exact approval before destructive cleanup."}], APPROVAL_FIELDS)
        write_json(output / "v21_215_summary.json", summary)
        write_report(output / "V21.215_aggressive_compact_output_policy_report.txt", summary)
    except Exception as exc:
        summary = {"stage": STAGE, "final_status": "FAIL_V21_215_STORAGE_POLICY_EXCEPTION", "final_decision": "AGGRESSIVE_STORAGE_POLICY_FAILED", "error_type": type(exc).__name__, "error_message": str(exc), **policy_flags()}
        write_json(output / "v21_215_summary.json", summary)
        (output / "V21.215_aggressive_compact_output_policy_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\nerror={summary['error_type']}: {summary['error_message']}\n", encoding="utf-8")
    for key in ["final_status", "final_decision", "repo_total_size_bytes_before", "projected_repo_size_after_aggressive_cleanup", "projected_total_savings_bytes", "deletion_allowed_in_this_run", "compression_allowed_in_this_run"]:
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
