#!/usr/bin/env python
"""V21.212 artifact role registry and retention policy.

Research-only, audit-only registry for outputs/v21 and key protected artifacts.
No deletion, movement, compression, price refresh, canonical mutation, adoption
change, or broker action is performed.
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
STAGE = "V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY"
OUT_REL = Path("outputs/v21/V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY")
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
    "archive/v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION",
]
DELETED_ZIP_STAGES = {
    "V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST",
    "V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST",
    "V21.148_E_R1_A1_PIT_LITE_REPLAY_DIAGNOSTIC_ONLY",
}
SENSITIVE_TOKENS = ["canonical", "price_history", "ohlcv", "kline", "moomoo", "dram", "abcde", "trade_plan", "ledger", "ranking", "latest", "current_chain", "protected"]
REGISTRY_FIELDS = [
    "artifact_id", "artifact_path", "artifact_type", "stage_id", "stage_name", "file_name", "file_extension",
    "recursive_size_bytes", "file_size_bytes", "file_count", "directory_count", "latest_modified_time",
    "earliest_modified_time", "artifact_role", "retention_class", "future_action_allowed",
    "current_chain_required", "audit_required", "reproducibility_required", "protected_flag",
    "canonical_flag", "broker_data_flag", "price_history_flag", "kline_flag", "moomoo_flag",
    "dram_flag", "abcde_flag", "trade_plan_flag", "ledger_flag", "ranking_flag", "cleanup_chain_flag",
    "zip_backup_flag", "source_deleted_but_zip_retained_flag", "safe_to_delete_now", "safe_to_compress_now",
    "manual_approval_required", "retention_rationale", "classification_confidence", "warning_flags",
]
POLICY_FIELDS = ["artifact_role", "retention_class", "future_action_allowed", "manual_approval_required", "policy_rationale"]
EDGE_FIELDS = ["consumer_stage", "producer_stage", "consumer_artifact", "producer_artifact", "dependency_type", "detection_method", "confidence", "rationale"]
SUMMARY_FIELDS = ["stage_id", "stage_name", "artifact_role", "retention_class", "recursive_size_bytes", "file_count", "protected_flag", "current_chain_required"]
PRESENCE_FIELDS = ["protected_key", "expected_path", "exact_exists", "alias_discovery_attempted", "alias_candidate_count", "resolved_exists", "resolved_protected_path", "resolution_method", "warning_reason"]
WARN_FIELDS = ["artifact_path", "warning_type", "warning_detail"]


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


def iter_files(path: Path, deep: bool = True) -> list[Path]:
    try:
        if deep:
            return sorted([p for p in path.rglob("*") if p.is_file()], key=lambda p: p.as_posix())
        return sorted([p for p in path.iterdir() if p.is_file()], key=lambda p: p.as_posix())
    except OSError:
        return []


def iter_dirs(path: Path) -> list[Path]:
    try:
        return sorted([p for p in path.rglob("*") if p.is_dir()], key=lambda p: p.as_posix())
    except OSError:
        return []


def metrics(path: Path, deep: bool = True) -> tuple[int, int, int, str, str]:
    files = iter_files(path, deep=deep) if path.exists() else []
    dirs = iter_dirs(path) if path.exists() and deep else []
    size = 0
    mtimes = []
    for file in files:
        try:
            stat = file.stat()
            size += stat.st_size
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
    return size, len(files), len(dirs), latest, earliest


def stage_id(name: str) -> str:
    match = re.match(r"^(V\d+\.\d+)", name)
    return match.group(1) if match else ""


def protected_alias_candidates(root: Path, sid: str) -> list[Path]:
    out21 = root / "outputs/v21"
    if not out21.exists():
        return []
    candidates = []
    for child in out21.iterdir():
        if not child.is_dir() or not child.name.startswith(sid):
            continue
        if sid == "V21.201" and not v21_201_alias_is_current_chain(child):
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


def newest(paths: list[Path]) -> Path:
    return max(paths, key=lambda p: p.stat().st_mtime)


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
                resolved = newest(candidates)
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


def protected_paths_set(presence: list[dict[str, Any]]) -> set[str]:
    return {row["resolved_protected_path"] for row in presence if row.get("resolved_protected_path")}


def classify(path_rel: str, name: str, is_dir: bool, protected_paths: set[str]) -> tuple[str, str, str, str, bool, bool, bool, float, str]:
    text = f"{path_rel} {name}".lower()
    protected = path_rel in protected_paths or any(path_rel.startswith(p + "/") for p in protected_paths)
    cleanup = any(f"v21.{n}" in text for n in ["202", "203", "204", "205", "206", "207", "208", "209", "210", "211", "212"])
    if path_rel == ".venv":
        return "CURRENT_ENVIRONMENT", "RETAIN_PROTECTED_CURRENT_CHAIN", "NO_ACTION_PROTECTED", "Current project virtual environment.", True, False, False, 1.0, ""
    if path_rel == ".venv_moomoo_py312":
        return "ALTERNATE_ENVIRONMENT_REVIEW", "REVIEW_ALTERNATE_ENV_RETIREMENT", "REVIEW_BEFORE_ACTION", "Alternate virtualenv requires manual retirement review.", False, False, False, 0.9, ""
    if path_rel.endswith("V20_199D_CANONICAL_HISTORICAL_OHLCV.csv") or "canonical_historical_ohlcv" in text:
        return "CANONICAL_PRICE_SOURCE", "RETAIN_CANONICAL_SOURCE", "NO_ACTION_PROTECTED", "Canonical price history source.", True, True, True, 1.0, ""
    if path_rel == "state":
        return "STATE_CACHE_OR_RUNTIME_STATE", "REVIEW_STATE_CACHE", "REVIEW_BEFORE_ACTION", "Runtime state summary; manual review required.", False, False, False, 0.9, ""
    if "archive/v21_compressed_stage_copies" in text or path_rel.endswith(".zip"):
        return "ZIP_ARCHIVE_BACKUP", "RETAIN_ZIP_BACKUP", "KEEP_AS_IS", "Zip backup retained after verified original deletion.", False, True, False, 1.0, ""
    if "v21.154" in text:
        return "AUDIT_CRITICAL_HISTORY", "RETAIN_AUDIT_CRITICAL", "KEEP_AS_IS", "Invalid trial repair/replay history is audit critical.", False, True, True, 1.0, ""
    if cleanup:
        return "CLEANUP_AUDIT_ARTIFACT", "RETAIN_CLEANUP_EVIDENCE", "KEEP_AS_IS", "Cleanup chain evidence should be retained.", False, True, True, 0.98, ""
    if "v21.199" in text or "moomoo" in text or "kline" in text:
        return "BROKER_DATA_SOURCE", "RETAIN_PROTECTED_CURRENT_CHAIN", "NO_ACTION_PROTECTED", "Broker/Moomoo/kline data stage.", True, False, True, 0.95, ""
    if "v21.201" in text or "dram" in text:
        return "DRAM_PLAN_OUTPUT", "RETAIN_PROTECTED_CURRENT_CHAIN", "NO_ACTION_PROTECTED", "DRAM current-chain planning output.", True, False, True, 0.95, ""
    if "v21.197" in text or "abcde" in text:
        return "ABCDE_RERUN_OUTPUT", "RETAIN_PROTECTED_CURRENT_CHAIN", "NO_ACTION_PROTECTED", "ABCDE current-chain rerun output.", True, False, True, 0.95, ""
    if "v21.140" in text or "price_history" in text:
        return "REPRODUCIBILITY_SUPPORT", "RETAIN_REPRODUCIBILITY", "REVIEW_BEFORE_ACTION", "Historical panel/price semantics are sensitive.", False, False, True, 0.9, ""
    if "ledger" in text:
        return "FORWARD_TRACKING_LEDGER", "RETAIN_AUDIT_CRITICAL", "NO_ACTION_PROTECTED", "Ledger artifact.", True, True, True, 0.9, ""
    if "ranking" in text:
        return "STRATEGY_RANKING_OUTPUT", "RETAIN_REPRODUCIBILITY", "REVIEW_BEFORE_ACTION", "Strategy ranking output.", False, True, True, 0.85, ""
    if "backtest" in text:
        return "BACKTEST_RESULT", "REVIEW_COLD_ARCHIVE", "ZIP_COPY_ONLY_AFTER_APPROVAL", "Historical backtest result can be reviewed for cold archive.", False, False, True, 0.85, ""
    if "__pycache__" in text or ".pytest_cache" in text or "pytest_tmp" in text:
        return "LOW_VALUE_CACHE", "SAFE_DELETE_CACHE", "DELETE_CACHE_AFTER_DRY_RUN", "Low-value cache/temp artifact.", False, False, False, 0.95, ""
    if protected:
        return "CURRENT_CHAIN_OUTPUT", "RETAIN_PROTECTED_CURRENT_CHAIN", "NO_ACTION_PROTECTED", "Resolved protected path.", True, False, True, 0.9, ""
    return "UNKNOWN_REVIEW_REQUIRED", "UNKNOWN_MANUAL_REVIEW", "REVIEW_BEFORE_ACTION", "No explicit role rule matched.", False, False, False, 0.4, "UNKNOWN_REVIEW_REQUIRED"


def flags_for(path_rel: str) -> dict[str, bool]:
    text = path_rel.lower()
    return {
        "canonical_flag": "canonical" in text,
        "broker_data_flag": "broker" in text or "moomoo" in text,
        "price_history_flag": "price_history" in text,
        "kline_flag": "kline" in text,
        "moomoo_flag": "moomoo" in text,
        "dram_flag": "dram" in text,
        "abcde_flag": "abcde" in text,
        "trade_plan_flag": "trade_plan" in text or "trade-plan" in text,
        "ledger_flag": "ledger" in text,
        "ranking_flag": "ranking" in text,
        "cleanup_chain_flag": any(f"v21.{n}" in text for n in ["202", "203", "204", "205", "206", "207", "208", "209", "210", "211", "212"]),
        "zip_backup_flag": path_rel.lower().endswith(".zip") or "archive/v21_compressed_stage_copies" in text,
    }


def registry_row(root: Path, path: Path, artifact_type: str, protected_paths: set[str], deep: bool = True) -> dict[str, Any]:
    path_rel = rel(path, root)
    size, files, dirs, latest, earliest = metrics(path, deep=deep)
    is_file = path.is_file()
    stage_name = ""
    sid = ""
    parts = Path(path_rel).parts
    if len(parts) >= 3 and parts[0] == "outputs" and parts[1] == "v21":
        stage_name = parts[2]
        sid = stage_id(stage_name)
    role, retention, action, rationale, current_req, audit_req, repro_req, confidence, warning = classify(path_rel, path.name, path.is_dir(), protected_paths)
    f = flags_for(path_rel)
    protected = current_req or path_rel in protected_paths or any(path_rel.startswith(p + "/") for p in protected_paths)
    source_deleted = f["zip_backup_flag"] and any(stage in path_rel for stage in DELETED_ZIP_STAGES)
    safe_delete = role == "LOW_VALUE_CACHE" and not protected
    return {
        "artifact_id": path_rel.replace("/", "__"),
        "artifact_path": path_rel,
        "artifact_type": artifact_type,
        "stage_id": sid,
        "stage_name": stage_name,
        "file_name": path.name if is_file else "",
        "file_extension": path.suffix.lower() if is_file else "",
        "recursive_size_bytes": 0 if is_file else size,
        "file_size_bytes": path.stat().st_size if is_file and path.exists() else 0,
        "file_count": files,
        "directory_count": dirs,
        "latest_modified_time": latest,
        "earliest_modified_time": earliest,
        "artifact_role": role,
        "retention_class": retention,
        "future_action_allowed": action,
        "current_chain_required": current_req,
        "audit_required": audit_req,
        "reproducibility_required": repro_req,
        "protected_flag": protected,
        **f,
        "source_deleted_but_zip_retained_flag": source_deleted,
        "safe_to_delete_now": False if role != "LOW_VALUE_CACHE" else safe_delete,
        "safe_to_compress_now": False,
        "manual_approval_required": True,
        "retention_rationale": rationale,
        "classification_confidence": confidence,
        "warning_flags": warning,
    }


def scan_registry(root: Path, protected_paths: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    out21 = root / "outputs/v21"
    if out21.exists():
        for stage in sorted([p for p in out21.iterdir() if p.is_dir()], key=lambda p: p.name):
            rows.append(registry_row(root, stage, "stage_directory", protected_paths))
            for file in iter_files(stage):
                if file.name.lower() in {"summary.json", "v21_212_summary.json"} or file.suffix.lower() in {".csv", ".json", ".txt"} and any(k in file.name.lower() for k in ["summary", "report", "ranking", "ledger", "plan", "manifest"]):
                    rows.append(registry_row(root, file, "important_file", protected_paths, deep=False))
    canonical = root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
    if canonical.exists():
        rows.append(registry_row(root, canonical, "important_file", protected_paths, deep=False))
    archive = root / "archive/v21_compressed_stage_copies"
    if archive.exists():
        rows.append(registry_row(root, archive, "archive_directory", protected_paths))
        for zfile in archive.rglob("*.zip"):
            rows.append(registry_row(root, zfile, "zip_archive", protected_paths, deep=False))
    for item in ["state", ".venv", ".venv_moomoo_py312"]:
        path = root / item
        if path.exists():
            rows.append(registry_row(root, path, "summary_directory", protected_paths, deep=False if item.startswith(".venv") else True))
    return rows


def dependency_edges(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stages = {row["stage_name"]: row for row in rows if row["artifact_type"] == "stage_directory" and row["stage_name"]}
    edges = []
    known_pairs = [("V21.197", "V21.199"), ("V21.201", "V21.199"), ("V21.208", "V21.207"), ("V21.209", "V21.208"), ("V21.210", "V21.209"), ("V21.211", "V21.210"), ("V21.212", "V21.211")]
    for consumer_id, producer_id in known_pairs:
        consumers = [name for name in stages if name.startswith(consumer_id)]
        producers = [name for name in stages if name.startswith(producer_id)]
        for consumer in consumers:
            for producer in producers:
                edges.append({
                    "consumer_stage": consumer,
                    "producer_stage": producer,
                    "consumer_artifact": stages[consumer]["artifact_path"],
                    "producer_artifact": stages[producer]["artifact_path"],
                    "dependency_type": "KNOWN_CHAIN_ORDER",
                    "detection_method": "stage_id_rule",
                    "confidence": 0.9,
                    "rationale": f"{consumer_id} is known to consume or validate outputs after {producer_id}.",
                })
    refs = ["V21.197", "V21.199", "V21.201", "V21.207", "V21.208", "V21.209", "V21.210", "V21.211"]
    for row in rows:
        if row["artifact_type"] != "important_file":
            continue
        text = row["artifact_path"]
        for ref in refs:
            if ref.replace(".", "_") in text or ref in text:
                continue
    return edges


def policy_rules() -> list[dict[str, Any]]:
    return [
        {"artifact_role": "CURRENT_ENVIRONMENT", "retention_class": "RETAIN_PROTECTED_CURRENT_CHAIN", "future_action_allowed": "NO_ACTION_PROTECTED", "manual_approval_required": True, "policy_rationale": "Current execution environment."},
        {"artifact_role": "CANONICAL_PRICE_SOURCE", "retention_class": "RETAIN_CANONICAL_SOURCE", "future_action_allowed": "NO_ACTION_PROTECTED", "manual_approval_required": True, "policy_rationale": "Canonical price source cannot be cleanup target."},
        {"artifact_role": "AUDIT_CRITICAL_HISTORY", "retention_class": "RETAIN_AUDIT_CRITICAL", "future_action_allowed": "KEEP_AS_IS", "manual_approval_required": True, "policy_rationale": "Decision-history evidence."},
        {"artifact_role": "CLEANUP_AUDIT_ARTIFACT", "retention_class": "RETAIN_CLEANUP_EVIDENCE", "future_action_allowed": "KEEP_AS_IS", "manual_approval_required": True, "policy_rationale": "Cleanup evidence chain."},
        {"artifact_role": "ZIP_ARCHIVE_BACKUP", "retention_class": "RETAIN_ZIP_BACKUP", "future_action_allowed": "KEEP_AS_IS", "manual_approval_required": True, "policy_rationale": "Verified backup retained after source deletion."},
        {"artifact_role": "LOW_VALUE_CACHE", "retention_class": "SAFE_DELETE_CACHE", "future_action_allowed": "DELETE_CACHE_AFTER_DRY_RUN", "manual_approval_required": True, "policy_rationale": "Only cache can be considered by future dry-run."},
        {"artifact_role": "UNKNOWN_REVIEW_REQUIRED", "retention_class": "UNKNOWN_MANUAL_REVIEW", "future_action_allowed": "REVIEW_BEFORE_ACTION", "manual_approval_required": True, "policy_rationale": "No automated action."},
    ]


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"total_registry_rows={summary['total_registry_rows']}",
        f"protected_artifact_count={summary['protected_artifact_count']}",
        f"unknown_review_required_count={summary['unknown_review_required_count']}",
        f"safe_to_delete_now_count={summary['safe_to_delete_now_count']}",
        "research_only=true",
        "audit_only=true",
        "mutation_allowed=false",
        "deletion_performed=false",
        "next_recommended_action=Use artifact_registry.csv as the classification source for future cleanup stages.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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


def run(repo_root: Path = DEFAULT_ROOT, out_dir: Path | None = None, simulate_exception: bool = False) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if simulate_exception:
            raise RuntimeError("simulated V21.212 failure")
        presence = protected_presence(root)
        protected_missing = [row for row in presence if not str_bool(row["resolved_exists"])]
        alias_used = [row for row in presence if str_bool(row["alias_discovery_attempted"]) and str_bool(row["resolved_exists"])]
        registry = scan_registry(root, protected_paths_set(presence))
        edges = dependency_edges(registry)
        warnings = [{"artifact_path": row["artifact_path"], "warning_type": row["warning_flags"], "warning_detail": "Manual review required"} for row in registry if row["warning_flags"]]
        by_role: dict[str, int] = defaultdict(int)
        by_retention: dict[str, int] = defaultdict(int)
        for row in registry:
            size = int(row["recursive_size_bytes"] or row["file_size_bytes"] or 0)
            by_role[row["artifact_role"]] += size
            by_retention[row["retention_class"]] += size
        unknown_count = sum(1 for row in registry if row["artifact_role"] == "UNKNOWN_REVIEW_REQUIRED")
        if protected_missing:
            final_status = "FAIL_V21_212_PROTECTED_PATH_MISSING"
            final_decision = "ARTIFACT_REGISTRY_FAILED_PROTECTED_PATH_MISSING"
        elif alias_used:
            final_status = "WARN_V21_212_PROTECTED_ALIAS_USED"
            final_decision = "ARTIFACT_REGISTRY_READY_WITH_PROTECTED_ALIAS_RESOLUTION"
        elif unknown_count:
            final_status = "WARN_V21_212_REGISTRY_HAS_UNKNOWN_REVIEW_ITEMS"
            final_decision = "ARTIFACT_REGISTRY_READY_WITH_UNKNOWN_REVIEW_ITEMS"
        else:
            final_status = "PASS_V21_212_ARTIFACT_REGISTRY_READY"
            final_decision = "ARTIFACT_REGISTRY_READY_RETENTION_POLICY_ACTIVE"
        summary = {
            "stage": STAGE,
            "total_registry_rows": len(registry),
            "total_scanned_size_bytes": sum(int(row["recursive_size_bytes"] or row["file_size_bytes"] or 0) for row in registry),
            "current_chain_required_count": sum(1 for row in registry if str_bool(row["current_chain_required"])),
            "protected_artifact_count": sum(1 for row in registry if str_bool(row["protected_flag"])),
            "canonical_artifact_count": sum(1 for row in registry if str_bool(row["canonical_flag"])),
            "audit_critical_count": sum(1 for row in registry if row["retention_class"] == "RETAIN_AUDIT_CRITICAL"),
            "reproducibility_support_count": sum(1 for row in registry if str_bool(row["reproducibility_required"])),
            "cleanup_audit_artifact_count": sum(1 for row in registry if row["artifact_role"] == "CLEANUP_AUDIT_ARTIFACT"),
            "zip_backup_count": sum(1 for row in registry if row["artifact_role"] == "ZIP_ARCHIVE_BACKUP"),
            "unknown_review_required_count": unknown_count,
            "cold_archive_review_count": sum(1 for row in registry if row["retention_class"] == "REVIEW_COLD_ARCHIVE"),
            "safe_delete_cache_count": sum(1 for row in registry if row["retention_class"] == "SAFE_DELETE_CACHE"),
            "safe_delete_after_zip_approval_count": sum(1 for row in registry if row["future_action_allowed"] == "DELETE_ORIGINAL_AFTER_VERIFIED_ZIP_AND_APPROVAL"),
            "safe_to_delete_now_count": sum(1 for row in registry if str_bool(row["safe_to_delete_now"])),
            "safe_to_compress_now_count": sum(1 for row in registry if str_bool(row["safe_to_compress_now"])),
            "total_size_by_role": dict(by_role),
            "total_size_by_retention_class": dict(by_retention),
            "protected_path_missing_count": len(protected_missing),
            "dependency_edge_count": len(edges),
            "final_status": final_status,
            "final_decision": final_decision,
            **policy_flags(),
        }
        write_csv(output / "artifact_registry.csv", registry, REGISTRY_FIELDS)
        write_csv(output / "artifact_retention_policy_rules.csv", policy_rules(), POLICY_FIELDS)
        write_csv(output / "artifact_dependency_edges.csv", edges, EDGE_FIELDS)
        write_csv(output / "stage_role_summary.csv", [row for row in registry if row["artifact_type"] == "stage_directory"], SUMMARY_FIELDS)
        write_csv(output / "current_chain_artifact_manifest.csv", [row for row in registry if str_bool(row["current_chain_required"])], REGISTRY_FIELDS)
        write_csv(output / "audit_critical_artifact_manifest.csv", [row for row in registry if row["retention_class"] == "RETAIN_AUDIT_CRITICAL"], REGISTRY_FIELDS)
        write_csv(output / "reproducibility_artifact_manifest.csv", [row for row in registry if str_bool(row["reproducibility_required"])], REGISTRY_FIELDS)
        write_csv(output / "cold_archive_candidate_manifest.csv", [row for row in registry if row["retention_class"] == "REVIEW_COLD_ARCHIVE"], REGISTRY_FIELDS)
        write_csv(output / "deletion_candidate_manifest.csv", [row for row in registry if row["retention_class"] in {"SAFE_DELETE_CACHE", "SAFE_DELETE_AFTER_ZIP_AND_APPROVAL"}], REGISTRY_FIELDS)
        write_csv(output / "protected_path_presence_check.csv", presence, PRESENCE_FIELDS)
        write_csv(output / "registry_validation_warnings.csv", warnings, WARN_FIELDS)
        write_json(output / "v21_212_summary.json", summary)
        write_report(output / "V21.212_artifact_role_registry_report.txt", summary)
    except Exception as exc:
        summary = {"stage": STAGE, "final_status": "FAIL_V21_212_ARTIFACT_REGISTRY_EXCEPTION", "final_decision": "ARTIFACT_REGISTRY_FAILED", "error_type": type(exc).__name__, "error_message": str(exc), **policy_flags()}
        write_json(output / "v21_212_summary.json", summary)
        (output / "V21.212_artifact_role_registry_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\nerror={summary['error_type']}: {summary['error_message']}\n", encoding="utf-8")
    for key in ["final_status", "final_decision", "total_registry_rows", "protected_path_missing_count", "dependency_edge_count", "safe_to_delete_now_count", "deletion_performed", "broker_action_allowed"]:
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
