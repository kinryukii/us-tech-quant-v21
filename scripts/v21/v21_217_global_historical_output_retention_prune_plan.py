#!/usr/bin/env python
"""V21.217 global historical output retention prune plan.

Audit-only aggressive storage plan after V21.216. This stage never deletes,
compresses, moves, refreshes prices, mutates canonical files, connects to
OpenD, changes adoption outputs, or performs broker actions.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path(r"D:\us-tech-quant")
STAGE = "V21.217_GLOBAL_HISTORICAL_OUTPUT_RETENTION_PRUNE_PLAN"
OUT_REL = Path("outputs/v21/V21.217_GLOBAL_HISTORICAL_OUTPUT_RETENTION_PRUNE_PLAN")
REGISTRY_REL = Path("outputs/v21/V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY/artifact_registry.csv")
TARGET_REPO_SIZE_BYTES = 1_000_000_000
WARNING_THRESHOLD_BYTES = 1_200_000_000
APPROVAL_PHRASE = "APPROVE_V21_218_GLOBAL_HISTORICAL_OUTPUT_PRUNE"
ALREADY_ARCHIVED = {
    "V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020",
    "V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT",
    "V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST",
    "V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST",
    "V21.148_E_R1_A1_PIT_LITE_REPLAY_DIAGNOSTIC_ONLY",
}
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
    "outputs/v21/V21.215_COLD_ARCHIVE_ZIP_COPY_CREATION_FOR_V21_154",
    "outputs/v21/V21.215_AGGRESSIVE_COMPACT_OUTPUT_POLICY_AND_STORAGE_BUDGET_ENFORCER",
    "outputs/v21/V21.216_AGGRESSIVE_COMPACT_AND_DELETE_EXPANDED_OUTPUTS_AFTER_APPROVAL",
]
SENSITIVE_TOKENS = ["canonical", "price_history", "ohlcv", "kline", "moomoo", "dram", "abcde", "trade_plan", "ledger", "ranking", "latest", "current_chain", "protected"]
SUMMARY_KEEP_TOKENS = ["summary", "report", "manifest", "integrity", "top20", "top50", "metrics"]
LARGE_INTERMEDIATE_BYTES = 5 * 1024 * 1024
COMPACT_KEEP_ESTIMATE_BYTES = 2 * 1024 * 1024

SNAPSHOT_FIELDS = ["path", "size_bytes", "file_count", "directory_count"]
STAGE_FIELDS = [
    "stage_dir", "source_path", "recursive_size_bytes", "file_count", "directory_count",
    "latest_modified_time", "registry_role", "retention_class", "has_summary_json",
    "has_report_txt", "has_manifest", "protected_flag", "current_chain_flag",
    "cleanup_chain_flag", "canonical_or_price_flag", "broker_or_moomoo_flag",
    "dram_or_abcde_flag", "large_csv_size_bytes", "large_parquet_size_bytes",
    "large_json_size_bytes", "compact_keep_size_bytes_estimate", "zip_size_bytes_estimate",
    "projected_savings_bytes", "proposed_action", "approval_required",
    "deletion_allowed_in_this_run", "compression_allowed_in_this_run", "rationale",
    "blocker_reasons",
]
KEEP_FIELDS = ["stage_dir", "source_path", "size_bytes", "keep_reason"]
ARCHIVED_FIELDS = ["stage_dir", "expanded_original_exists", "zip_archive_expected", "already_archived_or_deleted", "rationale"]
PROJECTION_FIELDS = ["repo_total_size_bytes_now", "target_repo_size_bytes", "warning_threshold_bytes", "projected_total_savings_bytes", "projected_repo_size_after_global_prune", "target_1gb_reachable_flag", "target_1_2gb_warning_reachable_flag"]
PRESENCE_FIELDS = ["protected_key", "expected_path", "exact_exists", "alias_discovery_attempted", "alias_candidate_count", "resolved_exists", "resolved_protected_path", "resolution_method", "warning_reason"]
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


def metrics(path: Path) -> tuple[int, int, int, str]:
    files = iter_files(path) if path.exists() else []
    dirs = iter_dirs(path) if path.exists() else []
    size = 0
    mtimes = []
    for file in files:
        try:
            stat = file.stat()
            size += stat.st_size
            mtimes.append(stat.st_mtime)
        except OSError:
            pass
    if path.exists():
        try:
            mtimes.append(path.stat().st_mtime)
        except OSError:
            pass
    latest = datetime.fromtimestamp(max(mtimes), timezone.utc).replace(microsecond=0).isoformat() if mtimes else ""
    return size, len(files), len(dirs), latest


def registry_by_stage(root: Path) -> dict[str, dict[str, str]]:
    rows = read_csv(root / REGISTRY_REL)
    mapping: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.get("artifact_type") == "stage_directory":
            name = row.get("stage_name") or Path(row.get("artifact_path", "")).name
            mapping[name] = row
    return mapping


def v21_201_alias_is_current_chain(path: Path) -> bool:
    tokens = {"dram", "moomoo", "plan", "r4", "daily"}
    if any(token in path.name.lower() for token in tokens):
        return True
    return any(any(token in file.name.lower() for token in tokens) for file in iter_files(path)[:50])


def protected_presence(root: Path) -> list[dict[str, Any]]:
    rows = []
    out21 = root / "outputs/v21"
    for item in PROTECTED_REQUIRED:
        expected = root / item
        exact = expected.exists()
        attempted = False
        candidates: list[Path] = []
        resolved = expected if exact else None
        method = "EXACT_PATH" if exact else "UNRESOLVED"
        warning = "" if exact else "EXPECTED_PATH_MISSING"
        if not exact and item.startswith("outputs/v21/V21.") and out21.exists():
            attempted = True
            sid = Path(item).name.split("_", 1)[0]
            candidates = [p for p in out21.iterdir() if p.is_dir() and p.name.startswith(sid) and (sid != "V21.201" or v21_201_alias_is_current_chain(p))]
            if candidates:
                resolved = max(candidates, key=lambda p: p.stat().st_mtime)
                method = "ALIAS_DISCOVERY_NEWEST_MODIFIED"
                warning = ""
        rows.append({"protected_key": Path(item).name, "expected_path": item, "exact_exists": exact, "alias_discovery_attempted": attempted, "alias_candidate_count": len(candidates), "resolved_exists": bool(resolved and resolved.exists()), "resolved_protected_path": rel(resolved, root) if resolved else "", "resolution_method": method, "warning_reason": warning})
    return rows


def protected_set(presence: list[dict[str, Any]]) -> set[str]:
    return {row["resolved_protected_path"] for row in presence if row.get("resolved_protected_path")}


def cleanup_chain(stage: str) -> bool:
    return any(stage.startswith(f"V21.{n}") for n in range(207, 218))


def current_chain(stage: str, reg: dict[str, str]) -> bool:
    if str_bool(reg.get("current_chain_required")):
        return True
    return stage.startswith("V21.197") or stage.startswith("V21.199") or stage.startswith("V21.201")


def file_class_sizes(files: list[Path]) -> tuple[int, int, int]:
    large_csv = large_parquet = large_json = 0
    for file in files:
        try:
            size = file.stat().st_size
        except OSError:
            continue
        suffix = file.suffix.lower()
        name = file.name.lower()
        if suffix == ".csv" and size >= LARGE_INTERMEDIATE_BYTES and not any(token in name for token in SUMMARY_KEEP_TOKENS):
            large_csv += size
        elif suffix == ".parquet" and size >= LARGE_INTERMEDIATE_BYTES:
            large_parquet += size
        elif suffix == ".json" and size >= LARGE_INTERMEDIATE_BYTES and "summary" not in name and "manifest" not in name:
            large_json += size
    return large_csv, large_parquet, large_json


def stage_flags(stage: Path, root: Path, reg: dict[str, str], protected_rels: set[str]) -> dict[str, bool]:
    text = f"{stage.name} {rel(stage, root)}".lower()
    return {
        "protected_flag": rel(stage, root) in protected_rels or str_bool(reg.get("protected_flag")),
        "current_chain_flag": current_chain(stage.name, reg),
        "cleanup_chain_flag": cleanup_chain(stage.name),
        "canonical_or_price_flag": any(token in text for token in ["canonical", "price_history", "ohlcv"]),
        "broker_or_moomoo_flag": any(token in text for token in ["broker", "moomoo", "kline"]),
        "dram_or_abcde_flag": any(token in text for token in ["dram", "abcde", "trade_plan", "ledger", "ranking", "latest", "current_chain", "protected"]),
    }


def classify_stage(stage: Path, root: Path, reg: dict[str, str], protected_rels: set[str]) -> dict[str, Any]:
    size, file_count, dir_count, latest = metrics(stage)
    files = iter_files(stage)
    names = [f.name.lower() for f in files]
    has_summary = any(name.endswith("_summary.json") or name == "summary.json" or "summary" in name and name.endswith(".json") for name in names)
    has_report = any(name.endswith(".txt") and ("report" in name or "decision" in name) for name in names)
    has_manifest = any("manifest" in name for name in names)
    large_csv, large_parquet, large_json = file_class_sizes(files)
    flags = stage_flags(stage, root, reg, protected_rels)
    compact_est = min(size, COMPACT_KEEP_ESTIMATE_BYTES)
    zip_est = int(size * 0.20)
    action = "MANUAL_REVIEW_REQUIRED"
    rationale = "Manual review required by default."
    blockers = ""
    if stage.name in ALREADY_ARCHIVED:
        action = "ALREADY_ARCHIVED_OR_DELETED"
        compact_est = 0
        zip_est = 0
        rationale = "Expanded original is already deleted or represented by verified zip archive."
    elif flags["cleanup_chain_flag"]:
        action = "KEEP_EXPANDED_RECENT_CLEANUP_CHAIN"
        rationale = "V21.207+ cleanup/proof chain is hard kept."
        blockers = "RECENT_CLEANUP_EVIDENCE"
    elif flags["protected_flag"] or flags["current_chain_flag"]:
        action = "KEEP_EXPANDED_PROTECTED_CURRENT_CHAIN"
        rationale = "Protected/current-chain expanded output is hard kept."
        blockers = "PROTECTED_OR_CURRENT_CHAIN"
    elif flags["canonical_or_price_flag"] or flags["broker_or_moomoo_flag"] or flags["dram_or_abcde_flag"]:
        action = "MANUAL_REVIEW_REQUIRED"
        rationale = "Sensitive current-chain/canonical/broker-like keyword requires manual review."
        blockers = "SENSITIVE_KEYWORD"
    elif large_csv + large_parquet + large_json > 0 and (has_summary or has_report or has_manifest):
        action = "DELETE_LARGE_INTERMEDIATE_FILES_AFTER_COMPACT_KEEP"
        rationale = "Stage has compact evidence plus large intermediate files."
    elif size >= 25 * 1024 * 1024 and (has_summary or has_report or has_manifest):
        action = "ZIP_THEN_DELETE_EXPANDED_STAGE"
        rationale = "Large historical stage has compact summary/report/manifest evidence."
    elif reg.get("artifact_role") == "UNKNOWN_REVIEW_REQUIRED" and (has_summary or has_report or has_manifest):
        action = "KEEP_COMPACT_SUMMARY_ONLY"
        rationale = "Aggressive mode allows unknown historical stage to compact-only retention when compact evidence exists."
    elif size < 25 * 1024 * 1024:
        action = "KEEP_COMPACT_SUMMARY_ONLY"
        rationale = "Small historical stage; compact summary retention is enough."
    projected = 0
    if action == "ZIP_THEN_DELETE_EXPANDED_STAGE":
        projected = max(0, size - max(zip_est, compact_est))
    elif action == "DELETE_LARGE_INTERMEDIATE_FILES_AFTER_COMPACT_KEEP":
        projected = max(0, large_csv + large_parquet + large_json)
    row = {
        "stage_dir": stage.name,
        "source_path": rel(stage, root),
        "recursive_size_bytes": size,
        "file_count": file_count,
        "directory_count": dir_count,
        "latest_modified_time": latest,
        "registry_role": reg.get("artifact_role", "UNKNOWN_REVIEW_REQUIRED"),
        "retention_class": reg.get("retention_class", "UNKNOWN_MANUAL_REVIEW"),
        "has_summary_json": has_summary,
        "has_report_txt": has_report,
        "has_manifest": has_manifest,
        **flags,
        "large_csv_size_bytes": large_csv,
        "large_parquet_size_bytes": large_parquet,
        "large_json_size_bytes": large_json,
        "compact_keep_size_bytes_estimate": compact_est,
        "zip_size_bytes_estimate": zip_est,
        "projected_savings_bytes": projected,
        "proposed_action": action,
        "approval_required": True,
        "deletion_allowed_in_this_run": False,
        "compression_allowed_in_this_run": False,
        "rationale": rationale,
        "blocker_reasons": blockers,
    }
    return row


def build_plan(root: Path, protected_rels: set[str]) -> list[dict[str, Any]]:
    regmap = registry_by_stage(root)
    out21 = root / "outputs/v21"
    if not out21.exists():
        return []
    rows = []
    for stage in sorted([p for p in out21.iterdir() if p.is_dir()], key=lambda p: p.name):
        rows.append(classify_stage(stage, root, regmap.get(stage.name, {}), protected_rels))
    for archived in sorted(ALREADY_ARCHIVED):
        if not (out21 / archived).exists():
            rows.append({
                "stage_dir": archived, "source_path": f"outputs/v21/{archived}", "recursive_size_bytes": 0,
                "file_count": 0, "directory_count": 0, "latest_modified_time": "", "registry_role": "",
                "retention_class": "", "has_summary_json": False, "has_report_txt": False,
                "has_manifest": False, "protected_flag": False, "current_chain_flag": False,
                "cleanup_chain_flag": False, "canonical_or_price_flag": False, "broker_or_moomoo_flag": False,
                "dram_or_abcde_flag": False, "large_csv_size_bytes": 0, "large_parquet_size_bytes": 0,
                "large_json_size_bytes": 0, "compact_keep_size_bytes_estimate": 0, "zip_size_bytes_estimate": 0,
                "projected_savings_bytes": 0, "proposed_action": "ALREADY_ARCHIVED_OR_DELETED",
                "approval_required": True, "deletion_allowed_in_this_run": False, "compression_allowed_in_this_run": False,
                "rationale": "Expanded original already absent or archived.", "blocker_reasons": "",
            })
    return rows


def snapshot_rows(root: Path) -> list[dict[str, Any]]:
    rows = []
    for p in [root, root / "outputs", root / "outputs/v21", root / "archive", root / "state"]:
        size, fc, dc, _latest = metrics(p)
        rows.append({"path": rel(p, root), "size_bytes": size, "file_count": fc, "directory_count": dc})
    return rows


def policy_flags() -> dict[str, Any]:
    return {
        "research_only": True, "audit_only": True, "dry_run": True, "aggressive_storage_cleanup": True,
        "deletion_performed": False, "compression_performed": False, "archive_movement_performed": False,
        "price_refresh_performed": False, "canonical_mutation_performed": False,
        "moomoo_broker_connection_performed": False, "broker_action_allowed": False,
        "official_adoption_allowed": False, "protected_outputs_modified": False,
    }


def summarize(root: Path, rows: list[dict[str, Any]], missing_count: int) -> dict[str, Any]:
    repo_size = metrics(root)[0]
    out21_size = metrics(root / "outputs/v21")[0]
    savings = sum(int(row["projected_savings_bytes"]) for row in rows)
    projected = max(0, repo_size - savings)
    by_action = defaultdict(int)
    for row in rows:
        by_action[row["proposed_action"]] += 1
    if missing_count:
        status = "FAIL_V21_217_PROTECTED_PATH_MISSING"
        decision = "GLOBAL_HISTORICAL_OUTPUT_PRUNE_FAILED_PROTECTED_PATH_MISSING"
    elif projected > TARGET_REPO_SIZE_BYTES:
        status = "WARN_V21_217_1GB_TARGET_NOT_REACHABLE"
        decision = "GLOBAL_HISTORICAL_OUTPUT_PRUNE_PLAN_READY_BUT_1GB_NOT_REACHABLE"
    else:
        status = "PASS_V21_217_GLOBAL_PRUNE_PLAN_READY"
        decision = "GLOBAL_HISTORICAL_OUTPUT_PRUNE_PLAN_READY_APPROVAL_REQUIRED"
    return {
        "stage": STAGE,
        "repo_total_size_bytes_now": repo_size,
        "outputs_v21_size_bytes_now": out21_size,
        "target_repo_size_bytes": TARGET_REPO_SIZE_BYTES,
        "total_stage_dirs_scanned": len([r for r in rows if int(r["recursive_size_bytes"]) > 0]),
        "protected_keep_count": by_action["KEEP_EXPANDED_PROTECTED_CURRENT_CHAIN"],
        "compact_summary_only_candidate_count": by_action["KEEP_COMPACT_SUMMARY_ONLY"],
        "zip_then_delete_candidate_count": by_action["ZIP_THEN_DELETE_EXPANDED_STAGE"],
        "delete_large_intermediate_file_candidate_count": by_action["DELETE_LARGE_INTERMEDIATE_FILES_AFTER_COMPACT_KEEP"],
        "projected_total_savings_bytes": savings,
        "projected_repo_size_after_global_prune": projected,
        "target_1gb_reachable_flag": projected <= TARGET_REPO_SIZE_BYTES,
        "target_1_2gb_warning_reachable_flag": projected <= WARNING_THRESHOLD_BYTES,
        "destructive_cleanup_requires_approval": True,
        "required_manual_approval_phrase": APPROVAL_PHRASE,
        "protected_path_missing_count": missing_count,
        "final_status": status,
        "final_decision": decision,
        **policy_flags(),
    }


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"repo_total_size_bytes_now={summary['repo_total_size_bytes_now']}",
        f"projected_total_savings_bytes={summary['projected_total_savings_bytes']}",
        f"projected_repo_size_after_global_prune={summary['projected_repo_size_after_global_prune']}",
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
            raise RuntimeError("simulated V21.217 failure")
        presence = protected_presence(root)
        missing = [r for r in presence if not str_bool(r["resolved_exists"])]
        rows = build_plan(root, protected_set(presence))
        summary = summarize(root, rows, len(missing))
        write_csv(output / "repo_post_v21_216_size_snapshot.csv", snapshot_rows(root), SNAPSHOT_FIELDS)
        write_csv(output / "global_historical_stage_prune_plan.csv", rows, STAGE_FIELDS)
        write_csv(output / "keep_current_chain_manifest.csv", [r for r in rows if r["proposed_action"] == "KEEP_EXPANDED_PROTECTED_CURRENT_CHAIN"], STAGE_FIELDS)
        write_csv(output / "keep_protected_manifest.csv", [r for r in rows if str_bool(r["protected_flag"])], STAGE_FIELDS)
        write_csv(output / "keep_compact_summary_manifest.csv", [r for r in rows if r["proposed_action"] == "KEEP_COMPACT_SUMMARY_ONLY"], STAGE_FIELDS)
        write_csv(output / "zip_then_delete_stage_plan.csv", [r for r in rows if r["proposed_action"] == "ZIP_THEN_DELETE_EXPANDED_STAGE"], STAGE_FIELDS)
        write_csv(output / "delete_large_intermediate_file_plan.csv", [r for r in rows if r["proposed_action"] == "DELETE_LARGE_INTERMEDIATE_FILES_AFTER_COMPACT_KEEP"], STAGE_FIELDS)
        write_csv(output / "already_archived_stage_check.csv", [{"stage_dir": r["stage_dir"], "expanded_original_exists": int(r["recursive_size_bytes"]) > 0, "zip_archive_expected": r["stage_dir"] in ALREADY_ARCHIVED, "already_archived_or_deleted": r["proposed_action"] == "ALREADY_ARCHIVED_OR_DELETED", "rationale": r["rationale"]} for r in rows if r["stage_dir"] in ALREADY_ARCHIVED], ARCHIVED_FIELDS)
        write_csv(output / "projected_repo_size_after_global_prune.csv", [{"repo_total_size_bytes_now": summary["repo_total_size_bytes_now"], "target_repo_size_bytes": TARGET_REPO_SIZE_BYTES, "warning_threshold_bytes": WARNING_THRESHOLD_BYTES, "projected_total_savings_bytes": summary["projected_total_savings_bytes"], "projected_repo_size_after_global_prune": summary["projected_repo_size_after_global_prune"], "target_1gb_reachable_flag": summary["target_1gb_reachable_flag"], "target_1_2gb_warning_reachable_flag": summary["target_1_2gb_warning_reachable_flag"]}], PROJECTION_FIELDS)
        write_csv(output / "protected_path_presence_check.csv", presence, PRESENCE_FIELDS)
        write_csv(output / "manual_approval_checklist.csv", [{"required_manual_approval_phrase": APPROVAL_PHRASE, "destructive_cleanup_requires_approval": True, "deletion_allowed_in_this_run": False, "compression_allowed_in_this_run": False, "rationale": "V21.217 is plan-only; V21.218 requires exact approval."}], APPROVAL_FIELDS)
        write_json(output / "v21_217_summary.json", summary)
        write_report(output / "V21.217_global_historical_output_retention_prune_plan_report.txt", summary)
    except Exception as exc:
        summary = {"stage": STAGE, "final_status": "FAIL_V21_217_GLOBAL_PRUNE_PLAN_EXCEPTION", "final_decision": "GLOBAL_HISTORICAL_OUTPUT_PRUNE_PLAN_FAILED", "error_type": type(exc).__name__, "error_message": str(exc), **policy_flags()}
        write_json(output / "v21_217_summary.json", summary)
        (output / "V21.217_global_historical_output_retention_prune_plan_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\nerror={summary['error_type']}: {summary['error_message']}\n", encoding="utf-8")
    for key in ["final_status", "final_decision", "repo_total_size_bytes_now", "projected_repo_size_after_global_prune", "projected_total_savings_bytes"]:
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
