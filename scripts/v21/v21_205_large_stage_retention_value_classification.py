#!/usr/bin/env python
"""V21.205 large outputs/v21 stage retention value classification.

Audit-only. Produces manual-review recommendations only; never deletes, moves,
compresses, refreshes prices, mutates canonical files, or performs broker action.
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
STAGE = "V21.205_LARGE_STAGE_RETENTION_VALUE_CLASSIFICATION"
OUT_REL = Path("outputs/v21/V21.205_LARGE_STAGE_RETENTION_VALUE_CLASSIFICATION")
DEFAULT_LARGE_THRESHOLD_BYTES = 25 * 1024 * 1024
PROTECTED_EXPECTED = [
    "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
    "V21.202_REPO_SAFE_CLEANUP_AUDIT_AND_CACHE_PURGE",
    "V21.203_REPO_SIZE_ATTRIBUTION_AND_SAFE_PURGE_CANDIDATE_AUDIT",
]
CURRENT_CHAIN_TOKENS = ["latest", "moomoo", "dram", "abcde", "canonical", "price_history", "kline", "ranking", "ledger", "trade_plan", "trade-plan"]
FIELDS = [
    "stage_dir", "stage_name", "recursive_size_bytes", "file_count", "directory_count",
    "latest_modified_time", "earliest_modified_time", "age_days", "largest_file_path",
    "largest_file_size_bytes", "csv_size_bytes", "json_size_bytes", "txt_size_bytes",
    "parquet_size_bytes", "log_size_bytes", "tmp_size_bytes", "cache_size_bytes",
    "contains_summary_json", "contains_report_txt", "contains_final_status",
    "contains_invalid_trial", "contains_replay", "contains_forward", "contains_ledger",
    "contains_ranking", "contains_trade_plan", "contains_canonical", "contains_price_history",
    "contains_moomoo", "contains_dram", "contains_abcde", "protected_stage_flag",
    "current_chain_flag", "retention_value_class", "future_action_recommendation",
    "manual_review_required", "rationale",
]
LARGEST_FILE_FIELDS = ["stage_name", "file_path", "size_bytes", "extension", "modified_time"]
TYPE_FIELDS = ["stage_name", "file_type", "size_bytes", "file_count"]
ACTION_FIELDS = ["stage_name", "retention_value_class", "future_action_recommendation", "manual_review_required", "estimated_size_bytes", "rationale"]
PROTECTED_FIELDS = ["protected_key", "expected_stage_dir", "exact_exists", "alias_discovery_attempted", "alias_candidate_count", "resolved_exists", "resolved_stage_dir", "resolution_method", "warning_reason", "alias_candidates"]


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/")


def stage_dirs(root: Path) -> list[Path]:
    out21 = root / "outputs/v21"
    if not out21.exists():
        return []
    return sorted([p for p in out21.iterdir() if p.is_dir() and p.name.startswith("V21.")], key=lambda p: p.name)


def v21_201_alias_is_current_chain(path: Path) -> bool:
    tokens = {"dram", "moomoo", "plan", "r4", "daily"}
    if any(token in path.name.lower() for token in tokens):
        return True
    try:
        return any(any(token in child.name.lower() for token in tokens) for child in path.rglob("*"))
    except OSError:
        return False


def alias_candidates(root: Path, stage_id: str) -> list[Path]:
    candidates = []
    for path in stage_dirs(root):
        if not path.name.startswith(stage_id):
            continue
        if stage_id == "V21.201" and not v21_201_alias_is_current_chain(path):
            continue
        candidates.append(path)
    return candidates


def newest(paths: list[Path]) -> Path:
    return max(paths, key=lambda p: p.stat().st_mtime if p.exists() else 0.0)


def protected_resolution(root: Path) -> list[dict[str, Any]]:
    rows = []
    out21 = root / "outputs/v21"
    for expected in PROTECTED_EXPECTED:
        exact = out21 / expected
        exact_exists = exact.exists()
        attempted = False
        candidates: list[Path] = []
        resolved = exact if exact_exists else None
        method = "EXACT_PATH" if exact_exists else "UNRESOLVED"
        warning = "" if exact_exists else "EXPECTED_STAGE_MISSING"
        if not exact_exists:
            attempted = True
            stage_id = expected.split("_", 1)[0]
            candidates = alias_candidates(root, stage_id)
            if candidates:
                resolved = newest(candidates)
                method = "ALIAS_DISCOVERY_NEWEST_MODIFIED"
                warning = ""
        rows.append({
            "protected_key": expected,
            "expected_stage_dir": rel(exact, root),
            "exact_exists": exact_exists,
            "alias_discovery_attempted": attempted,
            "alias_candidate_count": len(candidates),
            "resolved_exists": bool(resolved and resolved.exists()),
            "resolved_stage_dir": rel(resolved, root) if resolved else "",
            "resolution_method": method,
            "warning_reason": warning,
            "alias_candidates": "|".join(rel(candidate, root) for candidate in candidates),
        })
    return rows


def protected_stage_names(root: Path, resolution: list[dict[str, Any]]) -> set[str]:
    names = set(PROTECTED_EXPECTED)
    for row in resolution:
        if row["resolved_exists"] and row["resolved_stage_dir"]:
            names.add(Path(str(row["resolved_stage_dir"])).name)
    return names


def iter_files(stage: Path) -> list[Path]:
    try:
        return [p for p in stage.rglob("*") if p.is_file()]
    except OSError:
        return []


def file_type(path: Path) -> str:
    lower = path.as_posix().lower()
    suffix = path.suffix.lower()
    if "__pycache__" in lower or ".pytest_cache" in lower:
        return "cache"
    if suffix in {".tmp", ".temp"}:
        return "tmp"
    if suffix in {".csv"}:
        return "csv"
    if suffix in {".json"}:
        return "json"
    if suffix in {".txt", ".md"}:
        return "txt"
    if suffix in {".parquet"}:
        return "parquet"
    if suffix in {".log"}:
        return "log"
    return suffix.lstrip(".") or "no_extension"


def stage_basic_size(stage: Path) -> int:
    total = 0
    for file in iter_files(stage):
        try:
            total += file.stat().st_size
        except OSError:
            continue
    return total


def selected_large_stages(root: Path, threshold: int = DEFAULT_LARGE_THRESHOLD_BYTES) -> list[Path]:
    stages = stage_dirs(root)
    sized = sorted([(stage, stage_basic_size(stage)) for stage in stages], key=lambda x: x[1], reverse=True)
    selected = {stage for stage, size in sized[:20]}
    selected.update(stage for stage, size in sized if size >= threshold)
    return [stage for stage, _size in sized if stage in selected]


def classify_stage(stage: Path, root: Path, protected_names: set[str], now: datetime | None = None) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    now = now or datetime.now(timezone.utc)
    files = iter_files(stage)
    dirs = [p for p in stage.rglob("*") if p.is_dir()] if stage.exists() else []
    type_sizes: dict[str, int] = defaultdict(int)
    type_counts: dict[str, int] = defaultdict(int)
    largest_file = None
    largest_size = 0
    mtimes: list[float] = []
    text_blobs: list[str] = [stage.name.lower()]
    total = 0
    contains_final_status = False
    for file in files:
        try:
            stat = file.stat()
        except OSError:
            continue
        size = stat.st_size
        total += size
        mtimes.append(stat.st_mtime)
        ftype = file_type(file)
        type_sizes[ftype] += size
        type_counts[ftype] += 1
        text_blobs.append(file.name.lower())
        if size > largest_size:
            largest_size = size
            largest_file = file
        if file.suffix.lower() in {".json", ".txt", ".csv", ".md"} and size <= 1024 * 1024:
            try:
                contains_final_status = contains_final_status or ("final_status" in file.read_text(encoding="utf-8", errors="ignore").lower())
            except OSError:
                pass
    latest_ts = max(mtimes) if mtimes else (stage.stat().st_mtime if stage.exists() else 0.0)
    earliest_ts = min(mtimes) if mtimes else latest_ts
    latest_dt = datetime.fromtimestamp(latest_ts, timezone.utc) if latest_ts else now
    age_days = max(0.0, (now - latest_dt).total_seconds() / 86400)
    joined = " ".join(text_blobs)
    flags = {
        "contains_summary_json": any(name.endswith("summary.json") for name in text_blobs),
        "contains_report_txt": any(name.endswith(".txt") and "report" in name for name in text_blobs),
        "contains_final_status": contains_final_status,
        "contains_invalid_trial": "invalid_trial" in joined or "invalid trial" in joined,
        "contains_replay": "replay" in joined,
        "contains_forward": "forward" in joined,
        "contains_ledger": "ledger" in joined,
        "contains_ranking": "ranking" in joined,
        "contains_trade_plan": "trade_plan" in joined or "trade-plan" in joined,
        "contains_canonical": "canonical" in joined,
        "contains_price_history": "price_history" in joined,
        "contains_moomoo": "moomoo" in joined,
        "contains_dram": "dram" in joined,
        "contains_abcde": "abcde" in joined,
    }
    protected = stage.name in protected_names
    current_chain = any(token in joined for token in CURRENT_CHAIN_TOKENS)
    retention, action, manual, rationale = classify_retention(stage.name, total, type_sizes, flags, protected, current_chain)
    row = {
        "stage_dir": rel(stage, root),
        "stage_name": stage.name,
        "recursive_size_bytes": total,
        "file_count": len(files),
        "directory_count": len(dirs),
        "latest_modified_time": datetime.fromtimestamp(latest_ts, timezone.utc).replace(microsecond=0).isoformat() if latest_ts else "",
        "earliest_modified_time": datetime.fromtimestamp(earliest_ts, timezone.utc).replace(microsecond=0).isoformat() if earliest_ts else "",
        "age_days": round(age_days, 3),
        "largest_file_path": rel(largest_file, root) if largest_file else "",
        "largest_file_size_bytes": largest_size,
        "csv_size_bytes": type_sizes["csv"],
        "json_size_bytes": type_sizes["json"],
        "txt_size_bytes": type_sizes["txt"],
        "parquet_size_bytes": type_sizes["parquet"],
        "log_size_bytes": type_sizes["log"],
        "tmp_size_bytes": type_sizes["tmp"],
        "cache_size_bytes": type_sizes["cache"],
        **flags,
        "protected_stage_flag": protected,
        "current_chain_flag": current_chain,
        "retention_value_class": retention,
        "future_action_recommendation": action,
        "manual_review_required": manual,
        "rationale": rationale,
    }
    largest_rows = []
    for file in sorted(files, key=lambda p: p.stat().st_size if p.exists() else 0, reverse=True)[:10]:
        try:
            stat = file.stat()
        except OSError:
            continue
        largest_rows.append({
            "stage_name": stage.name,
            "file_path": rel(file, root),
            "size_bytes": stat.st_size,
            "extension": file.suffix.lower() or "",
            "modified_time": datetime.fromtimestamp(stat.st_mtime, timezone.utc).replace(microsecond=0).isoformat(),
        })
    type_rows = [
        {"stage_name": stage.name, "file_type": key, "size_bytes": type_sizes[key], "file_count": type_counts[key]}
        for key in sorted(type_sizes)
    ]
    return row, largest_rows, type_rows


def classify_retention(stage_name: str, total: int, type_sizes: dict[str, int], flags: dict[str, bool], protected: bool, current_chain: bool) -> tuple[str, str, bool, str]:
    lower = stage_name.lower()
    if protected:
        return "MUST_KEEP_PROTECTED_STAGE", "KEEP_AS_IS_PROTECTED", True, "Protected current-system stage resolved by stage identity."
    if "v21.154" in lower and flags["contains_invalid_trial"] and flags["contains_replay"]:
        return "KEEP_AUDIT_CRITICAL_HISTORY", "KEEP_AS_IS", True, "Invalid-trial replay audit history explains strategy rejection/repair decisions."
    if current_chain:
        return "MUST_KEEP_CURRENT_CHAIN", "KEEP_AS_IS", True, "Contains current-chain keywords or artifacts; no retention reduction recommended."
    if flags["contains_canonical"] or flags["contains_price_history"] or flags["contains_moomoo"] or flags["contains_dram"] or flags["contains_abcde"] or flags["contains_trade_plan"] or flags["contains_ranking"] or flags["contains_ledger"]:
        return "KEEP_REPRODUCIBILITY_SUPPORT", "REVIEW_BEFORE_ANY_ACTION", True, "Contains strategy/data lineage artifacts that may support reproducibility."
    if type_sizes.get("tmp", 0) + type_sizes.get("cache", 0) >= max(1, int(total * 0.5)):
        return "MANUAL_REVIEW_LOW_VALUE_CANDIDATE", "CONSIDER_MOVE_TO_ARCHIVE_AFTER_MANUAL_APPROVAL", True, "Large stage appears temp/cache-heavy; manual review required before any action."
    if flags["contains_summary_json"] and flags["contains_report_txt"] and (type_sizes.get("csv", 0) or type_sizes.get("json", 0) or type_sizes.get("txt", 0)):
        return "COMPRESS_ONLY_CANDIDATE", "CONSIDER_ZIP_ARCHIVE_COPY_ONLY", True, "Completed historical stage has report metadata and large intermediate files."
    if type_sizes.get("csv", 0) >= max(1, int(total * 0.5)):
        return "COMPRESS_ONLY_CANDIDATE", "CONSIDER_COMPRESS_INTERMEDIATE_CSV_ONLY", True, "Large footprint is dominated by intermediate CSV outputs."
    if total < 5 * 1024 * 1024:
        return "UNKNOWN_REVIEW_REQUIRED", "NO_ACTION_LOW_SAVINGS", True, "Included by top-20 selection but savings are low."
    return "UNKNOWN_REVIEW_REQUIRED", "REVIEW_BEFORE_ANY_ACTION", True, "Insufficient evidence for automated retention classification."


def classify_large_stages(root: Path, resolution: list[dict[str, Any]], threshold: int = DEFAULT_LARGE_THRESHOLD_BYTES, now: datetime | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    protected = protected_stage_names(root, resolution)
    rows = []
    largest = []
    breakdown = []
    for stage in selected_large_stages(root, threshold=threshold):
        row, largest_rows, type_rows = classify_stage(stage, root, protected, now=now)
        rows.append(row)
        largest.extend(largest_rows)
        breakdown.extend(type_rows)
    rows.sort(key=lambda r: int(r["recursive_size_bytes"]), reverse=True)
    largest.sort(key=lambda r: int(r["size_bytes"]), reverse=True)
    return rows, largest, breakdown


def protected_stage_names(root: Path, resolution: list[dict[str, Any]]) -> set[str]:
    names = set(PROTECTED_EXPECTED)
    for row in resolution:
        if row["resolved_exists"] and row["resolved_stage_dir"]:
            names.add(Path(str(row["resolved_stage_dir"])).name)
    return names


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def write_report(path: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"large_stage_count={summary['large_stage_count']}",
        f"total_large_stage_size_bytes={summary['total_large_stage_size_bytes']}",
        f"largest_stage_dir={summary['largest_stage_dir']}",
        f"largest_stage_size_bytes={summary['largest_stage_size_bytes']}",
        f"compress_only_candidate_count={summary['compress_only_candidate_count']}",
        f"manual_review_low_value_candidate_count={summary['manual_review_low_value_candidate_count']}",
        "research_only=true",
        "audit_only=true",
        "mutation_allowed=false",
        "deletion_performed=false",
        "archive_movement_performed=false",
        "compression_performed=false",
        "broker_action_allowed=false",
        "official_adoption_allowed=false",
        "protected_outputs_modified=false",
        "",
        "large_stage_classification_preview:",
    ]
    lines.extend([f"- {row['stage_name']} size_bytes={row['recursive_size_bytes']} class={row['retention_value_class']} action={row['future_action_recommendation']}" for row in rows[:25]])
    lines.append("")
    lines.append("next_recommended_action=Manual review only; implement any archive/compression in a separate explicitly approved stage.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summary_counts(rows: list[dict[str, Any]], resolution: list[dict[str, Any]], root: Path) -> dict[str, Any]:
    largest = rows[0] if rows else {"stage_name": "", "recursive_size_bytes": 0}
    counts = defaultdict(int)
    sizes = defaultdict(int)
    for row in rows:
        cls = row["retention_value_class"]
        counts[cls] += 1
        sizes[cls] += int(row["recursive_size_bytes"])
    all_stages = stage_dirs(root)
    return {
        "total_stage_dirs_seen": len(all_stages),
        "large_stage_count": len(rows),
        "total_large_stage_size_bytes": sum(int(row["recursive_size_bytes"]) for row in rows),
        "largest_stage_dir": largest["stage_name"],
        "largest_stage_size_bytes": int(largest["recursive_size_bytes"]),
        "compress_only_candidate_count": counts["COMPRESS_ONLY_CANDIDATE"],
        "compress_only_candidate_size_bytes": sizes["COMPRESS_ONLY_CANDIDATE"],
        "manual_review_low_value_candidate_count": counts["MANUAL_REVIEW_LOW_VALUE_CANDIDATE"],
        "manual_review_low_value_candidate_size_bytes": sizes["MANUAL_REVIEW_LOW_VALUE_CANDIDATE"],
        "must_keep_current_chain_count": counts["MUST_KEEP_CURRENT_CHAIN"],
        "must_keep_protected_stage_count": counts["MUST_KEEP_PROTECTED_STAGE"],
        "keep_audit_critical_history_count": counts["KEEP_AUDIT_CRITICAL_HISTORY"],
        "keep_reproducibility_support_count": counts["KEEP_REPRODUCIBILITY_SUPPORT"],
        "unknown_review_required_count": counts["UNKNOWN_REVIEW_REQUIRED"],
        "protected_resolution_missing_count": sum(1 for row in resolution if not row["resolved_exists"]),
    }


def run(repo_root: Path = DEFAULT_ROOT, out_dir: Path | None = None, threshold_bytes: int = DEFAULT_LARGE_THRESHOLD_BYTES, simulate_exception: bool = False, now: datetime | None = None) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if simulate_exception:
            raise RuntimeError("simulated retention classification failure")
        if not (root / "outputs/v21").exists():
            raise RuntimeError("outputs/v21 not found")
        resolution = protected_resolution(root)
        rows, largest_rows, type_rows = classify_large_stages(root, resolution, threshold=threshold_bytes, now=now)
        counts = summary_counts(rows, resolution, root)
        missing = counts["protected_resolution_missing_count"]
        final_status = "WARN_V21_205_PROTECTED_STAGE_RESOLUTION_INCOMPLETE" if missing else "PASS_V21_205_LARGE_STAGE_RETENTION_CLASSIFICATION_READY"
        final_decision = "LARGE_STAGE_RETENTION_CLASSIFICATION_WARN_PROTECTED_RESOLUTION" if missing else "LARGE_STAGE_RETENTION_CLASSIFICATION_READY_MANUAL_REVIEW_ONLY"
        summary = {
            "stage": STAGE,
            **counts,
            "final_status": final_status,
            "final_decision": final_decision,
            "research_only": True,
            "audit_only": True,
            "mutation_allowed": False,
            "deletion_performed": False,
            "archive_movement_performed": False,
            "compression_performed": False,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "protected_outputs_modified": False,
        }
        action_rows = [{
            "stage_name": row["stage_name"],
            "retention_value_class": row["retention_value_class"],
            "future_action_recommendation": row["future_action_recommendation"],
            "manual_review_required": row["manual_review_required"],
            "estimated_size_bytes": row["recursive_size_bytes"],
            "rationale": row["rationale"],
        } for row in rows]
        write_csv(output / "large_stage_retention_classification.csv", rows, FIELDS)
        write_csv(output / "large_stage_largest_files.csv", largest_rows, LARGEST_FILE_FIELDS)
        write_csv(output / "large_stage_file_type_breakdown.csv", type_rows, TYPE_FIELDS)
        write_csv(output / "large_stage_recommended_manual_actions.csv", action_rows, ACTION_FIELDS)
        write_csv(output / "protected_stage_resolution_check.csv", resolution, PROTECTED_FIELDS)
        write_json(output / "v21_205_summary.json", summary)
        write_report(output / "V21.205_large_stage_retention_value_report.txt", summary, rows)
    except Exception as exc:
        summary = {
            "stage": STAGE,
            "final_status": "FAIL_V21_205_RETENTION_CLASSIFICATION_EXCEPTION",
            "final_decision": "LARGE_STAGE_RETENTION_CLASSIFICATION_FAILED",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "research_only": True,
            "audit_only": True,
            "mutation_allowed": False,
            "deletion_performed": False,
            "archive_movement_performed": False,
            "compression_performed": False,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "protected_outputs_modified": False,
        }
        write_json(output / "v21_205_summary.json", summary)
        (output / "V21.205_large_stage_retention_value_report.txt").write_text(
            "\n".join([STAGE, f"final_status={summary['final_status']}", f"final_decision={summary['final_decision']}", f"error={summary['error_type']}: {summary['error_message']}"]) + "\n",
            encoding="utf-8",
        )
    for key in ["final_status", "final_decision", "large_stage_count", "compress_only_candidate_count", "manual_review_low_value_candidate_count", "deletion_performed", "broker_action_allowed"]:
        if key in summary:
            print(f"{key}={summary[key]}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", default=str(DEFAULT_ROOT))
    parser.add_argument("--large-threshold-mb", type=float, default=25.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(Path(args.repo_root), threshold_bytes=int(args.large_threshold_mb * 1024 * 1024))
    return 0 if str(summary["final_status"]).startswith(("PASS", "WARN")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
