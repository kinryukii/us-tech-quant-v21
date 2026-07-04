#!/usr/bin/env python
"""V21.206 compress-only dry-run plan.

Research-only and dry-run only. This stage writes manifests and proposed plans;
it never creates zip files, deletes, moves, compresses, refreshes prices, mutates
canonical files, or performs broker/adoption actions.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path(r"D:\us-tech-quant")
STAGE = "V21.206_COMPRESS_ONLY_DRY_RUN_PLAN"
OUT_REL = Path("outputs/v21/V21.206_COMPRESS_ONLY_DRY_RUN_PLAN")
V205_REL = Path("outputs/v21/V21.205_LARGE_STAGE_RETENTION_VALUE_CLASSIFICATION/large_stage_retention_classification.csv")
HARD_EXCLUDE_STAGE_NAMES = {
    "V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT",
    "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
    "V21.202_REPO_SAFE_CLEANUP_AUDIT_AND_CACHE_PURGE",
    "V21.203_REPO_SIZE_ATTRIBUTION_AND_SAFE_PURGE_CANDIDATE_AUDIT",
    "V21.204_OUTPUTS_V21_ARCHIVE_CANDIDATE_AUDIT",
    "V21.205_LARGE_STAGE_RETENTION_VALUE_CLASSIFICATION",
}
SENSITIVE_TOKENS = ["canonical", "price_history", "ohlcv", "kline", "moomoo", "dram", "abcde", "trade_plan", "ledger", "ranking", "latest", "current_chain", "protected"]
PLAN_FIELDS = [
    "stage_dir", "source_path", "proposed_archive_zip_path", "source_recursive_size_bytes",
    "source_file_count", "source_directory_count", "largest_file_path", "largest_file_size_bytes",
    "csv_size_bytes", "json_size_bytes", "txt_size_bytes", "parquet_size_bytes", "other_size_bytes",
    "estimated_compression_ratio", "estimated_zip_size_bytes", "estimated_space_savings_bytes",
    "original_directory_retention_policy", "manual_approval_required", "compression_allowed_in_this_run",
    "deletion_allowed_after_compression", "exclusion_reason",
]
FILE_FIELDS = ["stage_dir", "relative_file_path", "file_size_bytes", "modified_time", "sha256", "file_extension", "manifest_status"]
INTEGRITY_FIELDS = ["stage_dir", "source_path", "source_recursive_size_bytes", "source_file_count", "source_directory_count", "manifest_file_count", "manifest_total_size_bytes", "manifest_status"]
EXCLUSION_FIELDS = ["stage_name", "stage_dir", "excluded", "exclusion_reason"]


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


def is_manual_compression_action(action: str) -> bool:
    return "COMPRESS" in action.upper() or "ZIP_ARCHIVE" in action.upper()


def contains_sensitive_text(value: str) -> bool:
    text = value.lower().replace("\\", "/")
    return any(token in text for token in SENSITIVE_TOKENS)


def exclusion_reason(row: dict[str, str], root: Path) -> str:
    stage_name = row.get("stage_name", "")
    stage_dir = row.get("stage_dir", f"outputs/v21/{stage_name}")
    path = root / stage_dir
    if row.get("retention_value_class") != "COMPRESS_ONLY_CANDIDATE":
        return "NOT_COMPRESS_ONLY_CANDIDATE"
    if not is_manual_compression_action(row.get("future_action_recommendation", "")):
        return "ACTION_NOT_COMPRESSION_RELATED"
    if str_bool(row.get("protected_stage_flag")):
        return "PROTECTED_STAGE_FLAG"
    if str_bool(row.get("current_chain_flag")):
        return "CURRENT_CHAIN_FLAG"
    if stage_name in HARD_EXCLUDE_STAGE_NAMES:
        return "HARDCODED_PROTECTED_EXCLUSION"
    if contains_sensitive_text(stage_dir):
        return "SENSITIVE_STAGE_PATH_KEYWORD"
    for file in iter_files(path):
        if contains_sensitive_text(rel(file, root)):
            return "SENSITIVE_FILE_KEYWORD"
    if not path.exists() or not path.is_dir():
        return "SOURCE_STAGE_DIR_MISSING"
    return ""


def candidate_rows(rows: list[dict[str, str]], root: Path) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    eligible = []
    exclusions = []
    for row in rows:
        reason = exclusion_reason(row, root)
        if reason:
            exclusions.append({"stage_name": row.get("stage_name", ""), "stage_dir": row.get("stage_dir", ""), "excluded": True, "exclusion_reason": reason})
        else:
            eligible.append(row)
            exclusions.append({"stage_name": row.get("stage_name", ""), "stage_dir": row.get("stage_dir", ""), "excluded": False, "exclusion_reason": ""})
    return eligible, exclusions


def iter_files(path: Path) -> list[Path]:
    try:
        return [p for p in path.rglob("*") if p.is_file()]
    except OSError:
        return []


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_type_size(files: list[Path]) -> dict[str, int]:
    sizes = {"csv": 0, "json": 0, "txt": 0, "parquet": 0, "other": 0}
    for file in files:
        try:
            size = file.stat().st_size
        except OSError:
            continue
        suffix = file.suffix.lower()
        if suffix == ".csv":
            sizes["csv"] += size
        elif suffix == ".json":
            sizes["json"] += size
        elif suffix in {".txt", ".md"}:
            sizes["txt"] += size
        elif suffix == ".parquet":
            sizes["parquet"] += size
        else:
            sizes["other"] += size
    return sizes


def estimate_ratio(sizes: dict[str, int], total: int) -> float:
    if total <= 0:
        return 1.0
    weighted = (
        sizes["csv"] * 0.25
        + sizes["json"] * 0.35
        + sizes["txt"] * 0.35
        + sizes["parquet"] * 0.9
        + sizes["other"] * 0.75
    )
    return round(max(0.2, min(0.95, weighted / total)), 4)


def build_candidate_plan(row: dict[str, str], root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    stage_name = row["stage_name"]
    stage_dir = row.get("stage_dir", f"outputs/v21/{stage_name}")
    source = root / stage_dir
    files = iter_files(source)
    dirs = [p for p in source.rglob("*") if p.is_dir()] if source.exists() else []
    total = sum(p.stat().st_size for p in files if p.exists())
    largest = max(files, key=lambda p: p.stat().st_size if p.exists() else 0, default=None)
    largest_size = largest.stat().st_size if largest and largest.exists() else 0
    sizes = file_type_size(files)
    ratio = estimate_ratio(sizes, total)
    zip_size = int(total * ratio)
    manifest_rows = []
    for file in files:
        try:
            stat = file.stat()
            manifest_rows.append({
                "stage_dir": stage_dir,
                "relative_file_path": rel(file, source),
                "file_size_bytes": stat.st_size,
                "modified_time": datetime.fromtimestamp(stat.st_mtime, timezone.utc).replace(microsecond=0).isoformat(),
                "sha256": sha256_file(file),
                "file_extension": file.suffix.lower(),
                "manifest_status": "HASHED_DRY_RUN_ONLY",
            })
        except OSError as exc:
            manifest_rows.append({
                "stage_dir": stage_dir,
                "relative_file_path": rel(file, source),
                "file_size_bytes": 0,
                "modified_time": "",
                "sha256": "",
                "file_extension": file.suffix.lower(),
                "manifest_status": f"HASH_FAILED_{type(exc).__name__}",
            })
    plan = {
        "stage_dir": stage_dir,
        "source_path": str(source),
        "proposed_archive_zip_path": str(root / "archive/outputs_v21_compress_only" / f"{stage_name}.zip"),
        "source_recursive_size_bytes": total,
        "source_file_count": len(files),
        "source_directory_count": len(dirs),
        "largest_file_path": rel(largest, root) if largest else "",
        "largest_file_size_bytes": largest_size,
        "csv_size_bytes": sizes["csv"],
        "json_size_bytes": sizes["json"],
        "txt_size_bytes": sizes["txt"],
        "parquet_size_bytes": sizes["parquet"],
        "other_size_bytes": sizes["other"],
        "estimated_compression_ratio": ratio,
        "estimated_zip_size_bytes": zip_size,
        "estimated_space_savings_bytes": max(0, total - zip_size),
        "original_directory_retention_policy": "KEEP_ORIGINAL_UNTIL_SEPARATE_MANUAL_APPROVAL",
        "manual_approval_required": True,
        "compression_allowed_in_this_run": False,
        "deletion_allowed_after_compression": False,
        "exclusion_reason": "",
    }
    integrity = {
        "stage_dir": stage_dir,
        "source_path": str(source),
        "source_recursive_size_bytes": total,
        "source_file_count": len(files),
        "source_directory_count": len(dirs),
        "manifest_file_count": len(manifest_rows),
        "manifest_total_size_bytes": sum(int(r["file_size_bytes"]) for r in manifest_rows),
        "manifest_status": "PASS_MANIFEST_HASHED_DRY_RUN_ONLY",
    }
    return plan, manifest_rows, integrity


def fail_if_protected_included(plan_rows: list[dict[str, Any]]) -> bool:
    for row in plan_rows:
        stage = Path(str(row["stage_dir"])).name
        if stage in HARD_EXCLUDE_STAGE_NAMES or contains_sensitive_text(str(row["stage_dir"])):
            return True
    return False


def write_report(path: Path, summary: dict[str, Any], plan_rows: list[dict[str, Any]]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"candidate_count_from_v21_205={summary['candidate_count_from_v21_205']}",
        f"candidate_count_after_exclusions={summary['candidate_count_after_exclusions']}",
        f"planned_compression_count={summary['planned_compression_count']}",
        f"total_source_size_bytes={summary['total_source_size_bytes']}",
        f"estimated_total_zip_size_bytes={summary['estimated_total_zip_size_bytes']}",
        f"estimated_total_space_savings_bytes={summary['estimated_total_space_savings_bytes']}",
        "research_only=true",
        "dry_run=true",
        "audit_only=true",
        "mutation_allowed=false",
        "compression_performed=false",
        "deletion_performed=false",
        "archive_movement_performed=false",
        "",
        "planned_candidates:",
    ]
    lines.extend([f"- {row['stage_dir']} source_bytes={row['source_recursive_size_bytes']} estimated_zip={row['estimated_zip_size_bytes']} savings={row['estimated_space_savings_bytes']}" for row in plan_rows])
    lines.append("")
    lines.append("next_recommended_action=Manual review only. A separate approved stage is required before any zip/archive/compression action.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(repo_root: Path = DEFAULT_ROOT, source_csv: Path | None = None, out_dir: Path | None = None, simulate_exception: bool = False, force_include_protected: bool = False) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if simulate_exception:
            raise RuntimeError("simulated compress dry-run failure")
        source = source_csv or (root / V205_REL)
        rows = read_csv(source)
        from_v205 = [row for row in rows if row.get("retention_value_class") == "COMPRESS_ONLY_CANDIDATE"]
        eligible, exclusions = candidate_rows(rows, root)
        if force_include_protected and rows:
            eligible.append(rows[0])
        plan_rows: list[dict[str, Any]] = []
        manifest_rows: list[dict[str, Any]] = []
        integrity_rows: list[dict[str, Any]] = []
        for row in eligible:
            plan, manifest, integrity = build_candidate_plan(row, root)
            plan_rows.append(plan)
            manifest_rows.extend(manifest)
            integrity_rows.append(integrity)
        protected_included = fail_if_protected_included(plan_rows)
        if protected_included:
            final_status = "FAIL_V21_206_PROTECTED_OR_CURRENT_CHAIN_CANDIDATE_INCLUDED"
            final_decision = "COMPRESS_ONLY_DRY_RUN_BLOCKED_PROTECTED_CANDIDATE"
        elif not plan_rows:
            final_status = "WARN_V21_206_NO_ELIGIBLE_COMPRESS_ONLY_CANDIDATES"
            final_decision = "COMPRESS_ONLY_DRY_RUN_NO_ELIGIBLE_CANDIDATES"
        else:
            final_status = "PASS_V21_206_COMPRESS_ONLY_DRY_RUN_PLAN_READY"
            final_decision = "COMPRESS_ONLY_DRY_RUN_READY_MANUAL_APPROVAL_REQUIRED"
        summary = {
            "stage": STAGE,
            "candidate_count_from_v21_205": len(from_v205),
            "candidate_count_after_exclusions": len(eligible),
            "planned_compression_count": len(plan_rows),
            "total_source_size_bytes": sum(int(r["source_recursive_size_bytes"]) for r in plan_rows),
            "estimated_total_zip_size_bytes": sum(int(r["estimated_zip_size_bytes"]) for r in plan_rows),
            "estimated_total_space_savings_bytes": sum(int(r["estimated_space_savings_bytes"]) for r in plan_rows),
            "total_manifest_file_count": len(manifest_rows),
            "final_status": final_status,
            "final_decision": final_decision,
            "research_only": True,
            "dry_run": True,
            "audit_only": True,
            "mutation_allowed": False,
            "compression_performed": False,
            "deletion_performed": False,
            "archive_movement_performed": False,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "protected_outputs_modified": False,
        }
        write_csv(output / "compress_only_dry_run_plan.csv", plan_rows, PLAN_FIELDS)
        write_csv(output / "compress_only_file_manifest.csv", manifest_rows, FILE_FIELDS)
        write_csv(output / "compress_only_candidate_integrity_manifest.csv", integrity_rows, INTEGRITY_FIELDS)
        write_csv(output / "compression_exclusion_check.csv", exclusions, EXCLUSION_FIELDS)
        write_json(output / "v21_206_summary.json", summary)
        write_report(output / "V21.206_compress_only_dry_run_plan_report.txt", summary, plan_rows)
    except Exception as exc:
        summary = {
            "stage": STAGE,
            "final_status": "FAIL_V21_206_COMPRESS_DRY_RUN_EXCEPTION",
            "final_decision": "COMPRESS_ONLY_DRY_RUN_FAILED",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "research_only": True,
            "dry_run": True,
            "audit_only": True,
            "mutation_allowed": False,
            "compression_performed": False,
            "deletion_performed": False,
            "archive_movement_performed": False,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "protected_outputs_modified": False,
        }
        write_json(output / "v21_206_summary.json", summary)
        (output / "V21.206_compress_only_dry_run_plan_report.txt").write_text(
            "\n".join([STAGE, f"final_status={summary['final_status']}", f"final_decision={summary['final_decision']}", f"error={summary['error_type']}: {summary['error_message']}"]) + "\n",
            encoding="utf-8",
        )
    for key in ["final_status", "final_decision", "candidate_count_from_v21_205", "candidate_count_after_exclusions", "planned_compression_count", "compression_performed", "deletion_performed", "broker_action_allowed"]:
        if key in summary:
            print(f"{key}={summary[key]}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", default=str(DEFAULT_ROOT))
    parser.add_argument("--source-csv", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source = Path(args.source_csv) if args.source_csv else None
    summary = run(Path(args.repo_root), source_csv=source)
    return 0 if str(summary["final_status"]).startswith(("PASS", "WARN")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
