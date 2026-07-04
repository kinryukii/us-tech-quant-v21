#!/usr/bin/env python
"""V21.225 system review, deprecation, and cleanup audit.

Audit-only governance step. This script scans repository files and writes only
V21.225 report artifacts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


STAGE = "V21.225_SYSTEM_REVIEW_DEPRECATION_AND_CLEANUP_AUDIT"
OUT_REL = Path("outputs/v21") / STAGE
V224_REL = Path("outputs/v21/V21.224_PRE_MIGRATION_RESULT_ARCHIVE_AND_MANIFEST_FREEZE")
PASS_STATUS = "PASS_V21_225_SYSTEM_CLEANUP_AUDIT_READY"
WARN_REVIEW_STATUS = "WARN_V21_225_SYSTEM_CLEANUP_AUDIT_READY_WITH_REVIEW_ITEMS"
WARN_NO_V224_STATUS = "WARN_V21_225_SYSTEM_CLEANUP_AUDIT_READY_WITHOUT_V21_224_CROSSCHECK"
FAIL_STATUS = "FAIL_V21_225_SYSTEM_CLEANUP_AUDIT_FAILED"
FINAL_DECISION = "SYSTEM_CLEANUP_DEPRECATION_PLAN_READY_REVIEW_REQUIRED_BEFORE_ANY_DELETE"
FAIL_DECISION = "SYSTEM_CLEANUP_DEPRECATION_AUDIT_FAILED"
DEFAULT_LARGE_THRESHOLD = 5_242_880
DEFAULT_MAX_SCAN = 2_000_000

SKIP_DIRS = {".git", ".venv", ".venv_moomoo_py312", "__pycache__", ".pytest_cache"}
FUTURE_ACTIVE_SCOPE = [
    "MOOMOO_ONLY_DATA_CHAIN",
    "LOCAL_CACHE_IO_ROUTER",
    "DRAM_DAILY_INTRADAY_CHAIN",
    "DRAM_RISK_EVENT_AND_NO_TRADE_GATE",
    "MINIMAL_ABCDE_COMPACT_RESEARCH",
    "MANIFEST_POINTER_AUDIT",
]

PROTECTED_PATTERNS = [
    r"V21\.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    r"V21\.199_R4",
    r"V21\.201",
    r"V21\.223_LOCAL_CACHE_ARCHITECTURE_AND_IO_ROUTER",
    r"V21\.224_PRE_MIGRATION_RESULT_ARCHIVE_AND_MANIFEST_FREEZE",
    r"FULL_SYSTEM_LATEST_RERUN",
    r"DAILY_MOOMOO_RESEARCH_CHAIN",
]
ACTIVE_CORE_PATTERNS = [
    r"DAILY_MOOMOO_RESEARCH_CHAIN",
    r"MOOMOO.*CANONICAL",
    r"V21\.199",
    r"DRAM.*(DAILY|INTRADAY|PLAN|TRIGGER|OUTCOME|DASHBOARD|NO_TRADE)",
    r"V21\.178",
    r"V21\.180",
    r"V21\.182",
    r"V21\.183",
    r"V21\.184",
    r"V21\.185",
    r"V21\.186",
    r"ABCDE",
]
ACTIVE_SUPPORT_PATTERNS = [
    r"CACHE_IO",
    r"LOCAL_CACHE",
    r"MANIFEST",
    r"POINTER",
    r"AUDIT",
    r"ORCHESTRAT",
    r"RUN_DAILY",
    r"RUNBOOK",
]
PAUSED_PATTERNS = [
    r"E_R1",
    r"D_R2C",
    r"D_R3",
    r"\bD_ORIGINAL\b",
    r"SOFT.?CAP",
    r"OVERHEAT",
    r"SWITCH",
    r"AI_BOTTLENECK",
    r"ETF_ROTATION|TACTICAL_ETF|LEVERAGED_ETF",
    r"\bB_CLEAN\b|\bB\b",
    r"\bC_CHALLENGER\b|\bC\b",
    r"RANDOM.*BACKTEST",
]
ARCHIVE_ONLY_PATTERNS = [r"V20", r"OLD", r"HISTORICAL", r"ARCHIVE"]
DIAGNOSTIC_PATTERNS = [r"FORENSIC", r"DIAGNOSIS", r"HEALTHCHECK", r"TRACE", r"DEBUG", r"SMOKE"]
DELETE_REVIEW_PATTERNS = [r"__PYCACHE__", r"\.PYC$", r"\.PYTEST_CACHE", r"TMP|TEMP|SCRATCH", r"DUPLICATE"]
QUARANTINE_PATTERNS = [r"FAILED", r"CORRUPT", r"CONFLICT", r"PARTIAL"]
YFINANCE_PATTERNS = [r"YFINANCE", r"YAHOO"]
EXTERNAL_FALLBACK_PATTERNS = [r"EXTERNAL_FALLBACK", r"PUBLIC_SOURCE", r"YAHOO", r"YFINANCE"]
DRAM_OUTCOME_PATTERNS = [
    "DRAM_OUTCOME",
    "OUTCOME_LEDGER",
    "FORWARD_OUTCOME",
    "INTRADAY_OUTCOME",
    "DRAM_INTRADAY_OUTCOME",
    "V21.183",
    "V21.184",
    "dram_intraday_forward_outcome",
    "dram_intraday_outcome_dashboard",
    "outcome_dashboard",
    "trigger_event_ledger",
    "no_trade_gate",
]

SYSTEM_FIELDS = [
    "path",
    "relative_path",
    "path_type",
    "size_bytes",
    "mtime_utc",
    "extension",
    "inferred_module",
    "inferred_version",
    "inferred_artifact_type",
    "primary_status",
    "secondary_status",
    "reason",
    "recommended_action",
    "safe_to_delete_now",
    "requires_user_review",
    "should_archive",
    "should_cache",
    "should_keep_in_repo",
    "yfinance_related",
    "moomoo_related",
    "dram_related",
    "abcde_related",
    "v20_related",
    "v21_related",
    "protected_by_v21_224",
    "notes",
]
MODULE_FIELDS = [
    "module_name",
    "latest_version",
    "primary_status",
    "latest_final_status",
    "latest_final_decision",
    "reason",
    "recommended_action",
    "user_review_required",
    "active_chain_dependency",
    "storage_bytes",
    "file_count",
    "protected_by_v21_224",
    "continue_value_score",
    "fit_with_dram_only_focus",
    "maintenance_cost",
    "risk_level",
]
PAUSED_FIELDS = [
    "project_name",
    "latest_version",
    "latest_decision",
    "reason_paused",
    "evidence_strength",
    "risk_level",
    "storage_cost",
    "maintenance_cost",
    "fit_with_dram_only_focus",
    "continue_value_score",
    "recommendation",
    "user_review_required",
    "representative_paths",
]
DELETE_FIELDS = [
    "path",
    "size_bytes",
    "reason",
    "confidence",
    "blocked_by_protection",
    "blocked_by_user_review",
    "safe_to_delete_after_verification",
    "recommended_verification_before_delete",
]
LARGE_FIELDS = [
    "path",
    "size_bytes",
    "size_mb",
    "primary_status",
    "recommended_action",
    "should_cache",
    "should_archive",
    "should_delete_after_verification",
    "protected_by_v21_224",
]
YF_FIELDS = [
    "path",
    "artifact_type",
    "size_bytes",
    "yfinance_import_or_output_detected",
    "yahoo_string_detected",
    "primary_status",
    "recommended_action",
    "allowed_in_future_active_chain",
]
MOOMOO_FIELDS = [
    "module_or_file",
    "moomoo_related",
    "yfinance_related",
    "external_fallback_related",
    "needs_moomoo_only_rebuild",
    "allowed_in_future_canonical_chain",
    "notes",
]
PRESSURE_FIELDS = ["category", "file_count", "total_bytes", "total_mb", "largest_file", "recommended_action"]
V224_FIELDS = ["source_path", "protected_by_v21_224", "archive_path", "sha256", "classification", "found_in_current_repo", "notes"]
DRAM_CROSS_FIELDS = ["path", "matched_pattern", "size_bytes", "mtime_utc", "crosscheck_status", "notes"]


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/")


def norm(text: str) -> str:
    return text.upper().replace("-", "_").replace(" ", "_")


def mtime_utc(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def sha256_file(path: Path, limit: int | None = None) -> str:
    digest = hashlib.sha256()
    read_bytes = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if limit is not None and read_bytes + len(chunk) > limit:
                chunk = chunk[: max(0, limit - read_bytes)]
            if not chunk:
                break
            digest.update(chunk)
            read_bytes += len(chunk)
            if limit is not None and read_bytes >= limit:
                break
    return digest.hexdigest()


def safe_content_sample(path: Path, max_bytes: int) -> str:
    if path.suffix.lower() not in {".py", ".ps1", ".json", ".csv", ".txt", ".md", ".yaml", ".yml", ".toml"}:
        return ""
    try:
        with path.open("rb") as handle:
            data = handle.read(max_bytes)
        return data.decode("utf-8", errors="ignore")
    except OSError:
        return ""


def regex_any(patterns: list[str], text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def infer_module(path: Path, repo_root: Path) -> str:
    parts = path.resolve().relative_to(repo_root.resolve()).parts
    if "outputs" in parts:
        i = parts.index("outputs")
        if len(parts) > i + 2:
            return parts[i + 2]
    if "scripts" in parts and len(parts) >= 3:
        return path.stem
    if len(parts) >= 2:
        return parts[0]
    return path.stem


def infer_version(module: str) -> str:
    match = re.search(r"(V\d+(?:\.\d+)?(?:_[A-Z0-9]+)?)", module, flags=re.IGNORECASE)
    return match.group(1).upper() if match else ""


def infer_artifact_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".py":
        return "python_code"
    if ext == ".ps1":
        return "powershell_wrapper"
    if ext in {".json", ".csv"}:
        return "manifest_or_data"
    if ext in {".txt", ".md"}:
        return "report_or_doc"
    if ext in {".zip", ".parquet", ".pkl", ".feather"}:
        return "large_binary_or_panel"
    return "file"


def load_v224_context(repo_root: Path, v224_output_dir: Path | None) -> tuple[dict[str, dict[str, str]], str]:
    base = (v224_output_dir or (repo_root / V224_REL)).resolve()
    pointer = read_json(base / "archive_pointer_manifest.json")
    rows = read_csv(base / "archive_manifest.csv")
    if not rows and pointer.get("archive_manifest"):
        rows = read_csv(Path(str(pointer["archive_manifest"])))
    protected: dict[str, dict[str, str]] = {}
    for row in rows:
        source = row.get("source_path", "")
        if source:
            protected[str(Path(source).resolve()).lower()] = row
    return protected, ("FOUND" if protected else "MISSING")


def iter_repo_files(repo_root: Path, include_v20: bool) -> list[Path]:
    files: list[Path] = []
    for path in repo_root.rglob("*"):
        try:
            rel_parts = path.resolve().relative_to(repo_root.resolve()).parts
        except ValueError:
            rel_parts = path.parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if not include_v20 and "v20" in [part.lower() for part in path.parts]:
            continue
        if path.is_file():
            files.append(path)
    return sorted(files, key=lambda p: rel(p, repo_root).lower())


def classify_file(path: Path, repo_root: Path, content: str, protected: bool) -> tuple[str, str, str]:
    rpath = rel(path, repo_root)
    text = norm(f"{rpath} {content[:4000]}")
    if protected or regex_any(PROTECTED_PATTERNS, rpath):
        return "PROTECTED_EVIDENCE", "V21.224 protected or known protected output", "KEEP_PROTECTED_EVIDENCE_REVIEW_ONLY"
    if regex_any(YFINANCE_PATTERNS, text):
        return "DEPRECATED", "Yahoo/yfinance chain is not allowed in future active system", "DEPRECATE_AND_REBUILD_MOOMOO_ONLY_IF_NEEDED"
    if regex_any(DELETE_REVIEW_PATTERNS, text):
        return "DELETE_CANDIDATE_REVIEW_ONLY", "Scratch/cache/duplicate artifact candidate", "REVIEW_BEFORE_ANY_DELETE"
    if regex_any(QUARANTINE_PATTERNS, text):
        return "QUARANTINE_CANDIDATE", "Failed/partial/conflict artifact needs quarantine review", "REVIEW_FOR_QUARANTINE"
    if regex_any(PAUSED_PATTERNS, text):
        return "PAUSED_REVIEW_REQUIRED", "Paused project or experiment outside future DRAM-only focus", "PRESERVE_FOR_USER_REVIEW"
    if regex_any(ACTIVE_CORE_PATTERNS, text):
        return "ACTIVE_CORE", "Fits future active Moomoo/DRAM/ABCDE scope", "KEEP_IN_REPO_OR_CACHE_POINTER"
    if regex_any(ACTIVE_SUPPORT_PATTERNS, text):
        return "ACTIVE_SUPPORT", "Supports manifests, cache IO, orchestration, or audit", "KEEP_AS_SUPPORT"
    if regex_any(DIAGNOSTIC_PATTERNS, text):
        return "DIAGNOSTIC_ONLY", "Diagnostic or forensic artifact", "ARCHIVE_OR_RETAIN_COMPACT_REPORT"
    if regex_any(ARCHIVE_ONLY_PATTERNS, text):
        return "ARCHIVE_ONLY", "Historical or old-system artifact", "ARCHIVE_ONLY_REVIEW"
    return "UNKNOWN_REVIEW_REQUIRED", "No deterministic cleanup classification matched", "USER_REVIEW_REQUIRED"


def recommended_flags(status: str, size: int, yfinance_related: bool, moomoo_related: bool) -> dict[str, bool]:
    return {
        "safe_to_delete_now": False,
        "requires_user_review": status in {"PAUSED_REVIEW_REQUIRED", "DELETE_CANDIDATE_REVIEW_ONLY", "QUARANTINE_CANDIDATE", "UNKNOWN_REVIEW_REQUIRED"},
        "should_archive": status in {"PROTECTED_EVIDENCE", "ARCHIVE_ONLY", "DIAGNOSTIC_ONLY", "PAUSED_REVIEW_REQUIRED"},
        "should_cache": size >= DEFAULT_LARGE_THRESHOLD or (moomoo_related and status in {"ACTIVE_CORE", "ACTIVE_SUPPORT"}),
        "should_keep_in_repo": status in {"ACTIVE_CORE", "ACTIVE_SUPPORT"} and size < DEFAULT_LARGE_THRESHOLD and not yfinance_related,
    }


def build_inventory(repo_root: Path, files: list[Path], protected_rows: dict[str, dict[str, str]], max_scan: int, large_threshold: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in files:
        stat = path.stat()
        rpath = rel(path, repo_root)
        content = safe_content_sample(path, max_scan)
        protected = str(path.resolve()).lower() in protected_rows
        status, reason, action = classify_file(path, repo_root, content, protected)
        text = norm(f"{rpath} {content[:4000]}")
        yfin = regex_any(YFINANCE_PATTERNS, text)
        moomoo = "MOOMOO" in text
        dram = "DRAM" in text
        abcde = "ABCDE" in text or "A1" in text
        flags = recommended_flags(status, stat.st_size, yfin, moomoo)
        if stat.st_size >= large_threshold and status not in {"ACTIVE_CORE", "ACTIVE_SUPPORT"}:
            flags["should_archive"] = True
        rows.append(
            {
                "path": str(path),
                "relative_path": rpath,
                "path_type": "file",
                "size_bytes": stat.st_size,
                "mtime_utc": mtime_utc(path),
                "extension": path.suffix.lower(),
                "inferred_module": infer_module(path, repo_root),
                "inferred_version": infer_version(infer_module(path, repo_root)),
                "inferred_artifact_type": infer_artifact_type(path),
                "primary_status": status,
                "secondary_status": "YFINANCE_RELATED" if yfin else "",
                "reason": reason,
                "recommended_action": action,
                "yfinance_related": yfin,
                "moomoo_related": moomoo,
                "dram_related": dram,
                "abcde_related": abcde,
                "v20_related": "V20" in text or "/V20/" in rpath.upper(),
                "v21_related": "V21" in text or "/V21/" in rpath.upper(),
                "protected_by_v21_224": protected,
                "notes": "audit_only_no_mutation",
                **flags,
            }
        )
    return rows


def latest_metadata_for_module(rows: list[dict[str, Any]], repo_root: Path) -> dict[str, dict[str, str]]:
    metadata: dict[str, dict[str, str]] = {}
    for row in rows:
        if row["extension"] != ".json":
            continue
        name = Path(row["path"]).name.lower()
        if "summary" not in name and "pointer_manifest" not in name:
            continue
        payload = read_json(Path(row["path"]))
        if payload:
            metadata.setdefault(row["inferred_module"], {})
            for key in ["final_status", "final_decision"]:
                if key in payload and key not in metadata[row["inferred_module"]]:
                    metadata[row["inferred_module"]][key] = str(payload[key])
    return metadata


def module_registry(rows: list[dict[str, Any]], repo_root: Path) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["inferred_module"]].append(row)
    metadata = latest_metadata_for_module(rows, repo_root)
    registry = []
    rank = [
        "PROTECTED_EVIDENCE",
        "ACTIVE_CORE",
        "ACTIVE_SUPPORT",
        "PAUSED_REVIEW_REQUIRED",
        "ARCHIVE_ONLY",
        "DIAGNOSTIC_ONLY",
        "DEPRECATED",
        "DELETE_CANDIDATE_REVIEW_ONLY",
        "QUARANTINE_CANDIDATE",
        "UNKNOWN_REVIEW_REQUIRED",
    ]
    for module, items in sorted(grouped.items()):
        status = min((item["primary_status"] for item in items), key=lambda s: rank.index(s) if s in rank else 99)
        storage = sum(int(item["size_bytes"]) for item in items)
        protected = any(bool(item["protected_by_v21_224"]) for item in items)
        active = status in {"ACTIVE_CORE", "PROTECTED_EVIDENCE", "ACTIVE_SUPPORT"}
        review = any(bool(item["requires_user_review"]) for item in items)
        registry.append(
            {
                "module_name": module,
                "latest_version": infer_version(module),
                "primary_status": status,
                "latest_final_status": metadata.get(module, {}).get("final_status", ""),
                "latest_final_decision": metadata.get(module, {}).get("final_decision", ""),
                "reason": items[0]["reason"],
                "recommended_action": items[0]["recommended_action"],
                "user_review_required": review,
                "active_chain_dependency": active,
                "storage_bytes": storage,
                "file_count": len(items),
                "protected_by_v21_224": protected,
                "continue_value_score": 90 if active else 45 if status == "PAUSED_REVIEW_REQUIRED" else 20,
                "fit_with_dram_only_focus": "HIGH" if active else "REVIEW" if status == "PAUSED_REVIEW_REQUIRED" else "LOW",
                "maintenance_cost": "HIGH" if storage > 50_000_000 else "MEDIUM" if storage > 5_000_000 else "LOW",
                "risk_level": "HIGH" if status in {"QUARANTINE_CANDIDATE", "DEPRECATED"} else "MEDIUM" if review else "LOW",
            }
        )
    return registry


def filter_rows(rows: list[dict[str, Any]], status: str) -> list[dict[str, Any]]:
    return [row for row in rows if row["primary_status"] == status]


def paused_rows(registry: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reps: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        if row["primary_status"] == "PAUSED_REVIEW_REQUIRED" and len(reps[row["inferred_module"]]) < 3:
            reps[row["inferred_module"]].append(row["relative_path"])
    out = []
    for module in sorted(reps):
        reg = next(r for r in registry if r["module_name"] == module)
        out.append(
            {
                "project_name": module,
                "latest_version": reg["latest_version"],
                "latest_decision": reg["latest_final_decision"],
                "reason_paused": "Outside current Moomoo-only DRAM/ABCDE compact focus",
                "evidence_strength": "MEDIUM",
                "risk_level": reg["risk_level"],
                "storage_cost": reg["storage_bytes"],
                "maintenance_cost": reg["maintenance_cost"],
                "fit_with_dram_only_focus": reg["fit_with_dram_only_focus"],
                "continue_value_score": reg["continue_value_score"],
                "recommendation": "PRESERVE_FOR_USER_REVIEW_NOT_SAFE_DELETE",
                "user_review_required": True,
                "representative_paths": "|".join(reps[module]),
            }
        )
    return out


def delete_candidate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        if row["primary_status"] == "DELETE_CANDIDATE_REVIEW_ONLY":
            out.append(
                {
                    "path": row["path"],
                    "size_bytes": row["size_bytes"],
                    "reason": row["reason"],
                    "confidence": "MEDIUM",
                    "blocked_by_protection": row["protected_by_v21_224"],
                    "blocked_by_user_review": True,
                    "safe_to_delete_after_verification": False,
                    "recommended_verification_before_delete": "Confirm no active dependency and confirm archive copy before any future delete approval",
                }
            )
    return out


def large_rows(rows: list[dict[str, Any]], threshold: int) -> list[dict[str, Any]]:
    return [
        {
            "path": row["path"],
            "size_bytes": row["size_bytes"],
            "size_mb": round(int(row["size_bytes"]) / (1024 * 1024), 3),
            "primary_status": row["primary_status"],
            "recommended_action": row["recommended_action"],
            "should_cache": row["should_cache"],
            "should_archive": row["should_archive"],
            "should_delete_after_verification": False,
            "protected_by_v21_224": row["protected_by_v21_224"],
        }
        for row in rows
        if int(row["size_bytes"]) >= threshold
    ]


def yfinance_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        if row["yfinance_related"]:
            path_text = norm(row["relative_path"])
            out.append(
                {
                    "path": row["path"],
                    "artifact_type": row["inferred_artifact_type"],
                    "size_bytes": row["size_bytes"],
                    "yfinance_import_or_output_detected": "YFINANCE" in path_text,
                    "yahoo_string_detected": "YAHOO" in path_text,
                    "primary_status": "DEPRECATED",
                    "recommended_action": "DEPRECATED_FOR_FUTURE_ACTIVE_CHAIN",
                    "allowed_in_future_active_chain": False,
                }
            )
    return out


def moomoo_readiness_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        ext_fallback = regex_any(EXTERNAL_FALLBACK_PATTERNS, norm(row["relative_path"]))
        relevant = row["moomoo_related"] or row["yfinance_related"] or ext_fallback or row["primary_status"] in {"ACTIVE_CORE", "DEPRECATED"}
        if relevant:
            allowed = bool(row["moomoo_related"]) and not bool(row["yfinance_related"]) and not ext_fallback
            out.append(
                {
                    "module_or_file": row["relative_path"],
                    "moomoo_related": row["moomoo_related"],
                    "yfinance_related": row["yfinance_related"],
                    "external_fallback_related": ext_fallback,
                    "needs_moomoo_only_rebuild": bool(row["yfinance_related"]) or ext_fallback,
                    "allowed_in_future_canonical_chain": allowed,
                    "notes": "audit_only_no_data_fetch",
                }
            )
    return out


def pressure_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["primary_status"]].append(row)
    out = []
    for category, items in sorted(grouped.items()):
        largest = max(items, key=lambda r: int(r["size_bytes"]))
        total = sum(int(r["size_bytes"]) for r in items)
        out.append(
            {
                "category": category,
                "file_count": len(items),
                "total_bytes": total,
                "total_mb": round(total / (1024 * 1024), 3),
                "largest_file": largest["path"],
                "recommended_action": largest["recommended_action"],
            }
        )
    return out


def v224_crosscheck_rows(protected_rows: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    out = []
    for source_key, row in sorted(protected_rows.items()):
        source = Path(row.get("source_path", source_key))
        out.append(
            {
                "source_path": row.get("source_path", str(source)),
                "protected_by_v21_224": True,
                "archive_path": row.get("archive_path", ""),
                "sha256": row.get("sha256", ""),
                "classification": row.get("classification", ""),
                "found_in_current_repo": source.exists(),
                "notes": "matched_v21_224_archive_manifest",
            }
        )
    return out


def dram_outcome_crosscheck(repo_root: Path) -> tuple[list[dict[str, Any]], str]:
    out21 = repo_root / "outputs" / "v21"
    matches = []
    exact = False
    if out21.exists():
        for path in sorted(out21.rglob("*"), key=lambda p: rel(p, repo_root).lower()):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            text = rel(path, repo_root)
            for pattern in DRAM_OUTCOME_PATTERNS:
                if pattern.lower() in text.lower():
                    if pattern == "DRAM_OUTCOME":
                        exact = True
                    size = path.stat().st_size if path.is_file() else 0
                    matches.append(
                        {
                            "path": str(path),
                            "matched_pattern": pattern,
                            "size_bytes": size,
                            "mtime_utc": mtime_utc(path),
                            "crosscheck_status": "",
                            "notes": "broader_dram_outcome_pattern_match",
                        }
                    )
                    break
    if exact:
        status = "INCONCLUSIVE_REVIEW_REQUIRED"
    elif matches:
        status = "PATTERN_MISS_ONLY"
    else:
        status = "TRUE_MISSING"
    if not matches:
        matches.append({"path": "", "matched_pattern": "", "size_bytes": 0, "mtime_utc": "", "crosscheck_status": status, "notes": "no broader outcome-like artifact found"})
    for row in matches:
        row["crosscheck_status"] = status
    return matches, status


def cleanup_policy() -> dict[str, Any]:
    return {
        "audit_only": True,
        "delete_allowed": False,
        "move_allowed": False,
        "mutation_allowed": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
        "yfinance_allowed": False,
        "data_fetch_allowed": False,
        "moomoo_import_allowed": False,
        "future_active_core_scope": FUTURE_ACTIVE_SCOPE,
    }


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"scanned_file_count={summary['scanned_file_count']}",
        f"scanned_total_bytes={summary['scanned_total_bytes']}",
        f"active_core_module_count={summary['active_core_module_count']}",
        f"protected_evidence_module_count={summary['protected_evidence_module_count']}",
        f"paused_review_project_count={summary['paused_review_project_count']}",
        f"deprecated_module_count={summary['deprecated_module_count']}",
        f"delete_candidate_review_only_count={summary['delete_candidate_review_only_count']}",
        f"large_file_count={summary['large_file_count']}",
        f"yfinance_artifact_count={summary['yfinance_artifact_count']}",
        f"dram_outcome_crosscheck_status={summary['dram_outcome_crosscheck_status']}",
        f"v21_224_archive_crosscheck_status={summary['v21_224_archive_crosscheck_status']}",
        f"warning_count={summary['warning_count']}",
        f"error_count={summary['error_count']}",
        "audit_only=True",
        "delete_allowed=False",
        "move_allowed=False",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(
    repo_root: Path | None = None,
    output_dir: Path | None = None,
    v21_224_output_dir: Path | None = None,
    include_v20: bool = False,
    large_threshold_bytes: int = DEFAULT_LARGE_THRESHOLD,
    max_content_scan_bytes: int = DEFAULT_MAX_SCAN,
) -> dict[str, Any]:
    root = (repo_root or default_repo_root()).resolve()
    output = (output_dir or (root / OUT_REL)).resolve()
    errors: list[str] = []
    try:
        output.mkdir(parents=True, exist_ok=True)
        protected_rows, v224_status = load_v224_context(root, v21_224_output_dir)
        files = iter_repo_files(root, include_v20=include_v20)
        inventory = build_inventory(root, files, protected_rows, max_content_scan_bytes, large_threshold_bytes)
        registry = module_registry(inventory, root)
        paused = paused_rows(registry, inventory)
        delete_candidates = delete_candidate_rows(inventory)
        large = large_rows(inventory, large_threshold_bytes)
        yfin = yfinance_rows(inventory)
        moomoo = moomoo_readiness_rows(inventory)
        pressure = pressure_rows(inventory)
        cross = v224_crosscheck_rows(protected_rows)
        dram_cross, dram_status = dram_outcome_crosscheck(root)

        unknown_count = sum(1 for row in registry if row["primary_status"] == "UNKNOWN_REVIEW_REQUIRED")
        warning_count = (1 if unknown_count else 0) + (1 if v224_status == "MISSING" else 0) + (1 if dram_status != "PATTERN_MISS_ONLY" else 0)
        if v224_status == "MISSING":
            final_status = WARN_NO_V224_STATUS
        elif unknown_count:
            final_status = WARN_REVIEW_STATUS
        else:
            final_status = PASS_STATUS

        write_csv(output / "system_file_inventory.csv", inventory, SYSTEM_FIELDS)
        write_csv(output / "module_status_registry.csv", registry, MODULE_FIELDS)
        write_csv(output / "active_core_modules.csv", [r for r in registry if r["primary_status"] == "ACTIVE_CORE"], MODULE_FIELDS)
        write_csv(output / "active_support_modules.csv", [r for r in registry if r["primary_status"] == "ACTIVE_SUPPORT"], MODULE_FIELDS)
        write_csv(output / "protected_evidence_modules.csv", [r for r in registry if r["primary_status"] == "PROTECTED_EVIDENCE"], MODULE_FIELDS)
        write_csv(output / "paused_project_review_list.csv", paused, PAUSED_FIELDS)
        write_csv(output / "archive_only_modules.csv", [r for r in registry if r["primary_status"] == "ARCHIVE_ONLY"], MODULE_FIELDS)
        write_csv(output / "deprecated_modules.csv", [r for r in registry if r["primary_status"] == "DEPRECATED"], MODULE_FIELDS)
        write_csv(output / "diagnostic_only_modules.csv", [r for r in registry if r["primary_status"] == "DIAGNOSTIC_ONLY"], MODULE_FIELDS)
        write_csv(output / "delete_candidates_review_only.csv", delete_candidates, DELETE_FIELDS)
        write_csv(output / "quarantine_candidates.csv", [r for r in inventory if r["primary_status"] == "QUARANTINE_CANDIDATE"], SYSTEM_FIELDS)
        write_csv(output / "large_file_inventory.csv", large, LARGE_FIELDS)
        write_csv(output / "yfinance_artifact_inventory.csv", yfin, YF_FIELDS)
        write_csv(output / "moomoo_only_readiness_audit.csv", moomoo, MOOMOO_FIELDS)
        write_csv(output / "repo_memory_pressure_report.csv", pressure, PRESSURE_FIELDS)
        write_csv(output / "v21_224_protected_archive_crosscheck.csv", cross, V224_FIELDS)
        write_csv(output / "dram_outcome_pattern_crosscheck.csv", dram_cross, DRAM_CROSS_FIELDS)
        write_json(output / "cleanup_policy.json", cleanup_policy())

        scanned_total = sum(int(row["size_bytes"]) for row in inventory)
        summary = {
            "final_status": final_status,
            "final_decision": FINAL_DECISION,
            "repo_root": str(root),
            "output_dir": str(output),
            "scanned_file_count": len(inventory),
            "scanned_total_bytes": scanned_total,
            "active_core_module_count": sum(1 for r in registry if r["primary_status"] == "ACTIVE_CORE"),
            "active_support_module_count": sum(1 for r in registry if r["primary_status"] == "ACTIVE_SUPPORT"),
            "protected_evidence_module_count": sum(1 for r in registry if r["primary_status"] == "PROTECTED_EVIDENCE"),
            "paused_review_project_count": len(paused),
            "archive_only_module_count": sum(1 for r in registry if r["primary_status"] == "ARCHIVE_ONLY"),
            "deprecated_module_count": sum(1 for r in registry if r["primary_status"] == "DEPRECATED"),
            "diagnostic_only_module_count": sum(1 for r in registry if r["primary_status"] == "DIAGNOSTIC_ONLY"),
            "delete_candidate_review_only_count": len(delete_candidates),
            "quarantine_candidate_count": sum(1 for r in inventory if r["primary_status"] == "QUARANTINE_CANDIDATE"),
            "large_file_count": len(large),
            "yfinance_artifact_count": len(yfin),
            "v21_224_archive_crosscheck_status": v224_status,
            "dram_outcome_crosscheck_status": dram_status,
            "warning_count": warning_count,
            "error_count": 0,
            "audit_only": True,
            "delete_allowed": False,
            "move_allowed": False,
            "yfinance_used": False,
            "data_fetch_used": False,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "research_only": True,
        }
        write_json(output / "v21_225_summary.json", summary)
        write_report(output / "V21.225_system_cleanup_audit_report.txt", summary)
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        summary = {
            "final_status": FAIL_STATUS,
            "final_decision": FAIL_DECISION,
            "repo_root": str(root),
            "output_dir": str(output),
            "scanned_file_count": 0,
            "scanned_total_bytes": 0,
            "active_core_module_count": 0,
            "active_support_module_count": 0,
            "protected_evidence_module_count": 0,
            "paused_review_project_count": 0,
            "archive_only_module_count": 0,
            "deprecated_module_count": 0,
            "diagnostic_only_module_count": 0,
            "delete_candidate_review_only_count": 0,
            "quarantine_candidate_count": 0,
            "large_file_count": 0,
            "yfinance_artifact_count": 0,
            "v21_224_archive_crosscheck_status": "NOT_RUN",
            "dram_outcome_crosscheck_status": "NOT_RUN",
            "warning_count": 0,
            "error_count": len(errors),
            "errors": errors,
            "audit_only": True,
            "delete_allowed": False,
            "move_allowed": False,
            "yfinance_used": False,
            "data_fetch_used": False,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "research_only": True,
        }
        try:
            output.mkdir(parents=True, exist_ok=True)
            write_json(output / "v21_225_summary.json", summary)
        except Exception:
            pass

    for key in [
        "final_status",
        "final_decision",
        "scanned_file_count",
        "scanned_total_bytes",
        "active_core_module_count",
        "protected_evidence_module_count",
        "paused_review_project_count",
        "deprecated_module_count",
        "delete_candidate_review_only_count",
        "large_file_count",
        "yfinance_artifact_count",
        "dram_outcome_crosscheck_status",
        "v21_224_archive_crosscheck_status",
        "warning_count",
        "error_count",
    ]:
        print(f"{key}={summary[key]}")
    print(f"summary_path={output / 'v21_225_summary.json'}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--v21-224-output-dir", default=None)
    parser.add_argument("--include-v20", action="store_true")
    parser.add_argument("--large-threshold-bytes", type=int, default=DEFAULT_LARGE_THRESHOLD)
    parser.add_argument("--max-content-scan-bytes", type=int, default=DEFAULT_MAX_SCAN)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(
        repo_root=Path(args.repo_root) if args.repo_root else None,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        v21_224_output_dir=Path(args.v21_224_output_dir) if args.v21_224_output_dir else None,
        include_v20=args.include_v20,
        large_threshold_bytes=args.large_threshold_bytes,
        max_content_scan_bytes=args.max_content_scan_bytes,
    )
    return 1 if summary["final_status"] == FAIL_STATUS else 0


if __name__ == "__main__":
    sys.exit(main())
