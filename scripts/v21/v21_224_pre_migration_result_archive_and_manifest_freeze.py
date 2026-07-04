#!/usr/bin/env python
"""V21.224 pre-migration result archive and manifest freeze.

Copy-only governance step. No source output is deleted, moved, renamed, or
mutated.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


STAGE = "V21.224_PRE_MIGRATION_RESULT_ARCHIVE_AND_MANIFEST_FREEZE"
OUT_REL = Path("outputs/v21") / STAGE
DEFAULT_ARCHIVE_ROOT = Path(r"D:\us-tech-quant-archive")
PASS_STATUS = "PASS_V21_224_PRE_MIGRATION_ARCHIVE_READY"
WARN_STATUS = "WARN_V21_224_PRE_MIGRATION_ARCHIVE_READY_WITH_MISSING_EXPECTED_RUNS"
FAIL_STATUS = "FAIL_V21_224_ARCHIVE_COPY_OR_HASH_VERIFICATION_FAILED"
FINAL_DECISION = "PRE_MIGRATION_RESULTS_FROZEN_READY_FOR_SYSTEM_CLEANUP_AND_EXTERNAL_MIGRATION"
FAIL_DECISION = "PRE_MIGRATION_RESULT_FREEZE_FAILED_COPY_OR_HASH_VERIFICATION"
LARGE_ARTIFACT_BYTES = 5 * 1024 * 1024

CRITICAL_PATTERNS = [
    "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "V21.199_R4",
    "V21.201",
    "V21.223_LOCAL_CACHE_ARCHITECTURE_AND_IO_ROUTER",
    "FULL_SYSTEM_LATEST_RERUN_20260630_152719",
    "DAILY_MOOMOO_RESEARCH_CHAIN",
    "DAILY_DRAM",
    "DRAM_INTRADAY",
    "DRAM_NO_TRADE",
    "DRAM_OUTCOME",
    "ABCDE",
    "MOOMOO_CANONICAL",
    "CACHE_IO",
]

PROTECTED_TOKENS = [
    "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "V21.199_R4",
    "V21.201",
    "V21.223_LOCAL_CACHE_ARCHITECTURE_AND_IO_ROUTER",
    "FULL_SYSTEM_LATEST_RERUN",
    "DAILY_MOOMOO_RESEARCH_CHAIN",
]
ARCHIVE_TOKENS = ["ABCDE", "DRAM_INTRADAY", "DRAM_NO_TRADE", "DRAM_OUTCOME", "DAILY_DRAM"]
CACHE_TOKENS = ["MOOMOO_CANONICAL", "CACHE_IO", "CACHE", "CANONICAL"]
DIAGNOSTIC_TOKENS = ["AUDIT", "FORENSIC", "DIAGNOSIS", "HEALTHCHECK", "PLAN", "DRY_RUN"]
REPO_KEEP_TOKENS = ["REGISTRY", "README", "RUNBOOK", "SUMMARY"]
DELETE_REVIEW_TOKENS = ["DELETE", "PRUNE", "PURGE", "CLEANUP"]

MIGRATION_FIELDS = [
    "source_path",
    "relative_path",
    "artifact_name",
    "artifact_type",
    "size_bytes",
    "mtime_utc",
    "extension",
    "inferred_run_id",
    "classification",
    "is_large_artifact",
    "is_protected_evidence",
    "migration_action",
    "archive_target_path",
    "sha256",
    "notes",
]
RUN_INDEX_FIELDS = [
    "run_id",
    "source_output_dir",
    "archive_output_dir",
    "detected_version",
    "final_status",
    "final_decision",
    "latest_price_date",
    "latest_plan_date",
    "canonical_latest_date",
    "strategy_latest_date",
    "research_only",
    "broker_action_allowed",
    "official_adoption_allowed",
    "data_source_policy",
    "yfinance_used",
    "external_fallback_used",
    "protected_reason",
    "copied_file_count",
    "copied_total_bytes",
    "sha256_manifest_path",
    "pointer_manifest_path",
]
ARCHIVE_FIELDS = [
    "source_path",
    "archive_path",
    "relative_archive_path",
    "size_bytes",
    "sha256",
    "copied",
    "verified",
    "classification",
    "run_id",
]
SHA_FIELDS = ["path_role", "source_path", "archive_path", "sha256", "size_bytes"]


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def freeze_id_from_now(now: datetime | None = None) -> str:
    return f"freeze_{(now or utc_now()).strftime('%Y%m%d_%H%M%S')}"


def norm(text: str) -> str:
    return text.upper().replace("-", "_").replace(" ", "_")


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def iter_files(path: Path) -> list[Path]:
    try:
        return sorted([p for p in path.rglob("*") if p.is_file()], key=lambda p: p.as_posix().lower())
    except OSError:
        return []


def metadata_for_run(run_dir: Path) -> dict[str, Any]:
    candidates = sorted(
        [p for p in run_dir.rglob("*.json") if "summary" in p.name.lower() or "pointer_manifest" in p.name.lower()],
        key=lambda p: (0 if "summary" in p.name.lower() else 1, len(p.parts), p.name.lower()),
    )
    merged: dict[str, Any] = {}
    for path in candidates[:20]:
        payload = read_json(path)
        for key, value in payload.items():
            if key not in merged and isinstance(value, (str, int, float, bool)) or value is None:
                merged[key] = value
        if "final_status" in merged and "final_decision" in merged:
            break
    return merged


def run_search_text(run_dir: Path, metadata: dict[str, Any]) -> str:
    metadata_text = " ".join(f"{k}={v}" for k, v in metadata.items())
    return norm(f"{run_dir.name} {metadata_text}")


def classify_run(run_dir: Path, metadata: dict[str, Any]) -> tuple[str, str]:
    text = run_search_text(run_dir, metadata)
    matched = [token for token in PROTECTED_TOKENS if norm(token) in text]
    if matched:
        return "PROTECTED_EVIDENCE", "|".join(matched)
    matched = [token for token in ARCHIVE_TOKENS if norm(token) in text]
    if matched:
        return "ARCHIVE_CANDIDATE", "|".join(matched)
    matched = [token for token in CACHE_TOKENS if norm(token) in text]
    if matched:
        return "CACHE_CANDIDATE", "|".join(matched)
    matched = [token for token in DELETE_REVIEW_TOKENS if norm(token) in text]
    if matched:
        return "DELETE_CANDIDATE_REVIEW_ONLY", "|".join(matched)
    matched = [token for token in DIAGNOSTIC_TOKENS if norm(token) in text]
    if matched:
        return "DIAGNOSTIC_ONLY", "|".join(matched)
    matched = [token for token in REPO_KEEP_TOKENS if norm(token) in text]
    if matched:
        return "REPO_LIGHTWEIGHT_KEEP", "|".join(matched)
    return "UNKNOWN_REVIEW_REQUIRED", ""


def infer_run_id(run_dir: Path) -> str:
    return run_dir.name


def detected_version(run_id: str) -> str:
    parts = run_id.split("_", 1)
    return parts[0] if parts and parts[0].upper().startswith("V") else ""


def candidate_run_dirs(repo_root: Path) -> list[Path]:
    outputs = repo_root / "outputs"
    candidates: set[Path] = set()
    for rel_root in [Path("outputs/v21"), Path("outputs/v20")]:
        root = repo_root / rel_root
        if root.exists():
            candidates.update(p for p in root.iterdir() if p.is_dir())
    if outputs.exists():
        for path in outputs.iterdir():
            if path.is_dir() and path.name.lower() not in {"v20", "v21", "shared", "_analysis"}:
                candidates.add(path)
        for path in outputs.rglob("*"):
            if path.is_dir():
                text = norm(path.name)
                if any(norm(pattern) in text for pattern in CRITICAL_PATTERNS):
                    candidates.add(path)
    return sorted(candidates, key=lambda p: rel(p, repo_root).lower())


def discover_runs(repo_root: Path) -> list[dict[str, Any]]:
    rows = []
    for run_dir in candidate_run_dirs(repo_root):
        metadata = metadata_for_run(run_dir)
        classification, reason = classify_run(run_dir, metadata)
        rows.append(
            {
                "run_dir": run_dir,
                "run_id": infer_run_id(run_dir),
                "metadata": metadata,
                "classification": classification,
                "protected_reason": reason,
            }
        )
    return rows


def missing_critical_patterns(discovered: list[dict[str, Any]]) -> list[str]:
    texts = [run_search_text(row["run_dir"], row["metadata"]) for row in discovered]
    missing = []
    for pattern in CRITICAL_PATTERNS:
        wanted = norm(pattern)
        if not any(wanted in text for text in texts):
            missing.append(pattern)
    return missing


def metadata_value(metadata: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if key in metadata and metadata[key] is not None:
            return str(metadata[key])
    return ""


def copy_and_verify(source: Path, target: Path, source_hash: str, dry_run: bool) -> tuple[str, bool, bool, str]:
    if target.exists():
        target_hash = sha256_file(target)
        if target_hash != source_hash:
            raise RuntimeError(f"archive target hash mismatch: {target}")
        return "already_present_verified", False, True, "target already existed with same sha256"
    if dry_run:
        return "dry_run_not_copied", False, False, "dry-run"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    copied_hash = sha256_file(target)
    if copied_hash != source_hash:
        raise RuntimeError(f"copied archive hash mismatch: {target}")
    if target.stat().st_size != source.stat().st_size:
        raise RuntimeError(f"copied archive size mismatch: {target}")
    return "copied_verified", True, True, ""


def archive_selected_runs(
    repo_root: Path,
    archive_freeze_dir: Path,
    discovered: list[dict[str, Any]],
    dry_run: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int, int]:
    inventory_rows: list[dict[str, Any]] = []
    archive_rows: list[dict[str, Any]] = []
    sha_rows: list[dict[str, Any]] = []
    run_index_rows: list[dict[str, Any]] = []
    total_files = 0
    total_bytes = 0
    snapshot_root = archive_freeze_dir / "outputs_snapshot"

    for run in discovered:
        run_dir = run["run_dir"]
        run_id = run["run_id"]
        classification = run["classification"]
        metadata = run["metadata"]
        selected = classification in {"PROTECTED_EVIDENCE", "ARCHIVE_CANDIDATE"}
        files = iter_files(run_dir)
        copied_count = 0
        copied_bytes = 0
        archive_output_dir = snapshot_root / run_dir.resolve().relative_to(repo_root.resolve()) if selected else Path("")

        for source in files:
            size = source.stat().st_size
            source_hash = sha256_file(source)
            rel_source = source.resolve().relative_to(repo_root.resolve())
            archive_path = snapshot_root / rel_source if selected else Path("")
            migration_action = "COPY_TO_EXTERNAL_ARCHIVE" if selected else "REVIEW_ONLY_NO_COPY"
            copied = False
            verified = False
            note = ""
            if selected:
                status, copied, verified, note = copy_and_verify(source, archive_path, source_hash, dry_run)
                migration_action = status
                if verified:
                    copied_count += 1
                    copied_bytes += size
                    total_files += 1
                    total_bytes += size
                archive_rows.append(
                    {
                        "source_path": str(source),
                        "archive_path": str(archive_path),
                        "relative_archive_path": rel(archive_path, archive_freeze_dir),
                        "size_bytes": size,
                        "sha256": source_hash,
                        "copied": copied,
                        "verified": verified,
                        "classification": classification,
                        "run_id": run_id,
                    }
                )
                sha_rows.append(
                    {
                        "path_role": "archived_output",
                        "source_path": str(source),
                        "archive_path": str(archive_path),
                        "sha256": source_hash,
                        "size_bytes": size,
                    }
                )
            inventory_rows.append(
                {
                    "source_path": str(source),
                    "relative_path": rel(source, repo_root),
                    "artifact_name": source.name,
                    "artifact_type": "file",
                    "size_bytes": size,
                    "mtime_utc": mtime_utc(source),
                    "extension": source.suffix.lower(),
                    "inferred_run_id": run_id,
                    "classification": classification,
                    "is_large_artifact": size >= LARGE_ARTIFACT_BYTES,
                    "is_protected_evidence": classification == "PROTECTED_EVIDENCE",
                    "migration_action": migration_action,
                    "archive_target_path": str(archive_path) if selected else "",
                    "sha256": source_hash,
                    "notes": note or run["protected_reason"],
                }
            )

        if selected:
            run_index_rows.append(
                {
                    "run_id": run_id,
                    "source_output_dir": str(run_dir),
                    "archive_output_dir": str(archive_output_dir),
                    "detected_version": detected_version(run_id),
                    "final_status": metadata_value(metadata, "final_status", "status"),
                    "final_decision": metadata_value(metadata, "final_decision", "decision"),
                    "latest_price_date": metadata_value(metadata, "latest_price_date", "price_latest_date"),
                    "latest_plan_date": metadata_value(metadata, "latest_plan_date", "plan_latest_date"),
                    "canonical_latest_date": metadata_value(metadata, "canonical_latest_date", "canonical_max_date"),
                    "strategy_latest_date": metadata_value(metadata, "strategy_latest_date", "strategy_max_date"),
                    "research_only": True,
                    "broker_action_allowed": False,
                    "official_adoption_allowed": False,
                    "data_source_policy": metadata_value(metadata, "data_source_policy") or "ARCHIVE_ONLY_NO_DATA_FETCH",
                    "yfinance_used": False,
                    "external_fallback_used": False,
                    "protected_reason": run["protected_reason"],
                    "copied_file_count": copied_count,
                    "copied_total_bytes": copied_bytes,
                    "sha256_manifest_path": str(archive_freeze_dir / "manifest" / "sha256_manifest.csv"),
                    "pointer_manifest_path": str(archive_freeze_dir / "manifest" / "archive_pointer_manifest.json"),
                }
            )

    return inventory_rows, run_index_rows, archive_rows, sha_rows, total_files, total_bytes


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"archive_freeze_dir={summary['archive_freeze_dir']}",
        f"protected_result_count={summary['protected_result_count']}",
        f"archived_file_count={summary['archived_file_count']}",
        f"archived_total_bytes={summary['archived_total_bytes']}",
        f"missing_critical_patterns={';'.join(summary['missing_critical_patterns'])}",
        f"warning_count={summary['warning_count']}",
        f"error_count={summary['error_count']}",
        "copy_only=True",
        "delete_allowed=False",
        "move_allowed=False",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
        "yfinance_used=False",
        "external_data_fetch_used=False",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def policy_flags() -> dict[str, bool]:
    return {
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "copy_only": True,
        "delete_allowed": False,
        "move_allowed": False,
        "yfinance_used": False,
        "external_data_fetch_used": False,
    }


def run(
    repo_root: Path | None = None,
    archive_root: Path | None = None,
    output_dir: Path | None = None,
    freeze_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = (repo_root or default_repo_root()).resolve()
    archive_base = (archive_root or Path(os.environ.get("US_TECH_QUANT_ARCHIVE_ROOT", str(DEFAULT_ARCHIVE_ROOT)))).resolve()
    output = (output_dir or (root / OUT_REL)).resolve()
    freeze = freeze_id or freeze_id_from_now()
    archive_freeze_dir = archive_base / "v21" / f"{STAGE}_{freeze}"
    output.mkdir(parents=True, exist_ok=True)
    (archive_freeze_dir / "manifest").mkdir(parents=True, exist_ok=True)
    (archive_freeze_dir / "outputs_snapshot").mkdir(parents=True, exist_ok=True)
    (archive_freeze_dir / "reports").mkdir(parents=True, exist_ok=True)
    created_at = utc_now().isoformat()
    errors: list[str] = []

    try:
        discovered = discover_runs(root)
        missing = missing_critical_patterns(discovered)
        inventory, run_index, archive_manifest, sha_manifest, archived_count, archived_bytes = archive_selected_runs(
            root, archive_freeze_dir, discovered, dry_run
        )
        warning_count = len(missing)
        final_status = WARN_STATUS if missing else PASS_STATUS
        final_decision = FINAL_DECISION
    except Exception as exc:
        discovered = []
        missing = []
        inventory = []
        run_index = []
        archive_manifest = []
        sha_manifest = []
        archived_count = 0
        archived_bytes = 0
        warning_count = 0
        errors.append(f"{type(exc).__name__}: {exc}")
        final_status = FAIL_STATUS
        final_decision = FAIL_DECISION

    error_count = len(errors)
    protected_count = len(run_index)
    summary = {
        "version": STAGE,
        "run_id": freeze,
        "final_status": final_status,
        "final_decision": final_decision,
        "created_at_utc": created_at,
        "repo_root": str(root),
        "archive_root": str(archive_base),
        "archive_freeze_dir": str(archive_freeze_dir),
        "protected_result_count": protected_count,
        "archived_file_count": archived_count,
        "archived_total_bytes": archived_bytes,
        "missing_critical_patterns": missing,
        "warning_count": warning_count,
        "error_count": error_count,
        "errors": errors,
        "dry_run": dry_run,
        **policy_flags(),
    }

    pointer = {
        "version": STAGE,
        "run_id": freeze,
        "final_status": final_status,
        "final_decision": final_decision,
        "created_at_utc": created_at,
        "repo_root": str(root),
        "archive_root": str(archive_base),
        "archive_freeze_dir": str(archive_freeze_dir),
        "protected_result_count": protected_count,
        "archived_file_count": archived_count,
        "archived_total_bytes": archived_bytes,
        "sha256_manifest": str(archive_freeze_dir / "manifest" / "sha256_manifest.csv"),
        "archive_manifest": str(archive_freeze_dir / "manifest" / "archive_manifest.csv"),
        "protected_result_run_index": str(archive_freeze_dir / "manifest" / "protected_result_run_index.csv"),
        "policy_flags": policy_flags(),
    }

    for base in [output, archive_freeze_dir / "manifest"]:
        write_csv(base / "migration_inventory.csv", inventory, MIGRATION_FIELDS)
        write_csv(base / "protected_result_run_index.csv", run_index, RUN_INDEX_FIELDS)
        write_csv(base / "archive_manifest.csv", archive_manifest, ARCHIVE_FIELDS)
        write_csv(base / "sha256_manifest.csv", sha_manifest, SHA_FIELDS)
        write_json(base / "archive_pointer_manifest.json", pointer)
    write_json(output / "v21_224_summary.json", summary)
    write_json(archive_freeze_dir / "v21_224_archive_freeze_summary.json", summary)
    write_report(output / "V21.224_pre_migration_archive_report.txt", summary)
    write_report(archive_freeze_dir / "reports" / "V21.224_pre_migration_archive_report.txt", summary)

    for key in [
        "final_status",
        "final_decision",
        "archive_freeze_dir",
        "protected_result_count",
        "archived_file_count",
        "archived_total_bytes",
        "warning_count",
        "error_count",
    ]:
        print(f"{key}={summary[key]}")
    print(f"summary_path={output / 'v21_224_summary.json'}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--archive-root", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--freeze-id", default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(
        repo_root=Path(args.repo_root) if args.repo_root else None,
        archive_root=Path(args.archive_root) if args.archive_root else None,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        freeze_id=args.freeze_id,
        dry_run=args.dry_run,
    )
    return 1 if summary["final_status"] == FAIL_STATUS else 0


if __name__ == "__main__":
    sys.exit(main())
