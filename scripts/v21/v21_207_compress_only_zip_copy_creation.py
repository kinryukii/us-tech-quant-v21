#!/usr/bin/env python
"""V21.207 compress-only zip copy creation.

Creates zip *copies* for explicitly approved V21.206 candidates only. It never
deletes, moves, rewrites, refreshes prices, mutates canonical files, or performs
broker/adoption actions. Original source directories must remain unchanged.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path(r"D:\us-tech-quant")
STAGE = "V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION"
OUT_REL = Path("outputs/v21/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION")
ZIP_REL = Path("archive/v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION")
V206_PLAN_REL = Path("outputs/v21/V21.206_COMPRESS_ONLY_DRY_RUN_PLAN/compress_only_dry_run_plan.csv")
APPROVED_STAGE_NAMES = {
    "V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST",
    "V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST",
    "V21.148_E_R1_A1_PIT_LITE_REPLAY_DIAGNOSTIC_ONLY",
}
HARD_EXCLUDE_STAGE_NAMES = {
    "V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020",
    "V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT",
    "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
    "V21.202_REPO_SAFE_CLEANUP_AUDIT_AND_CACHE_PURGE",
    "V21.203_REPO_SIZE_ATTRIBUTION_AND_SAFE_PURGE_CANDIDATE_AUDIT",
    "V21.204_OUTPUTS_V21_ARCHIVE_CANDIDATE_AUDIT",
    "V21.205_LARGE_STAGE_RETENTION_VALUE_CLASSIFICATION",
    "V21.206_COMPRESS_ONLY_DRY_RUN_PLAN",
}
SENSITIVE_TOKENS = ["canonical", "price_history", "ohlcv", "kline", "moomoo", "dram", "abcde", "trade_plan", "ledger", "ranking", "latest", "current_chain", "protected"]
RESULT_FIELDS = [
    "stage_dir", "stage_name", "zip_file_path", "status", "overwrite_reason",
    "source_file_count_before", "source_size_bytes_before", "source_manifest_sha256_before",
    "zip_size_bytes", "zip_exists", "zip_test_passed", "zip_member_count",
    "zip_uncompressed_size_bytes", "zip_manifest_sha256", "source_still_exists_after",
    "source_file_count_after", "source_size_bytes_after", "source_manifest_sha256_after",
    "source_unchanged_after", "compression_ratio_actual",
    "estimated_space_savings_if_original_later_removed", "deletion_allowed_now", "error_message",
]
INTEGRITY_FIELDS = [
    "stage_dir", "source_file_count_before", "source_size_bytes_before",
    "source_manifest_sha256_before", "zip_file_path", "zip_size_bytes", "zip_exists",
    "zip_test_passed", "zip_member_count", "zip_uncompressed_size_bytes",
    "zip_manifest_sha256", "source_still_exists_after", "source_file_count_after",
    "source_size_bytes_after", "source_manifest_sha256_after", "source_unchanged_after",
    "compression_ratio_actual", "estimated_space_savings_if_original_later_removed",
    "deletion_allowed_now",
]
POSTCHECK_FIELDS = ["stage_dir", "source_path", "source_still_exists_after", "source_file_count_after", "source_size_bytes_after", "source_manifest_sha256_after", "source_unchanged_after"]
MANIFEST_FIELDS = ["stage_dir", "zip_file_path", "zip_member_path", "member_size_bytes", "member_crc", "manifest_status"]
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


def sensitive_text(value: str) -> bool:
    text = value.lower().replace("\\", "/")
    return any(token in text for token in SENSITIVE_TOKENS)


def iter_files(path: Path) -> list[Path]:
    try:
        return sorted([p for p in path.rglob("*") if p.is_file()], key=lambda p: p.relative_to(path).as_posix())
    except OSError:
        return []


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_manifest(source: Path) -> tuple[str, int, int, list[dict[str, Any]]]:
    rows = []
    total = 0
    digest = hashlib.sha256()
    for file in iter_files(source):
        stat = file.stat()
        file_hash = sha256_file(file)
        rel_path = file.relative_to(source).as_posix()
        total += stat.st_size
        line = f"{rel_path}\t{stat.st_size}\t{file_hash}\n"
        digest.update(line.encode("utf-8"))
        rows.append({"relative_path": rel_path, "size": stat.st_size, "sha256": file_hash})
    return digest.hexdigest(), len(rows), total, rows


def zip_manifest(zip_path: Path, stage_name: str) -> tuple[str, bool, int, int, list[dict[str, Any]], str]:
    rows = []
    digest = hashlib.sha256()
    if not zip_path.exists():
        return "", False, 0, 0, rows, "ZIP_MISSING"
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad = zf.testzip()
            if bad:
                return "", False, 0, 0, rows, f"ZIP_TEST_FAILED:{bad}"
            infos = sorted([info for info in zf.infolist() if not info.is_dir()], key=lambda info: info.filename)
            total = 0
            for info in infos:
                data = zf.read(info.filename)
                file_hash = hashlib.sha256(data).hexdigest()
                member = info.filename.replace("\\", "/")
                rel_member = member[len(stage_name) + 1:] if member.startswith(stage_name + "/") else member
                total += info.file_size
                digest.update(f"{rel_member}\t{info.file_size}\t{file_hash}\n".encode("utf-8"))
                rows.append({
                    "zip_member_path": member,
                    "member_size_bytes": info.file_size,
                    "member_crc": info.CRC,
                    "manifest_status": "ZIP_MEMBER_OK",
                })
        return digest.hexdigest(), True, len(rows), total, rows, "ZIP_TEST_PASSED"
    except Exception as exc:
        return "", False, 0, 0, rows, f"ZIP_EXCEPTION:{type(exc).__name__}:{exc}"


def row_stage_name(row: dict[str, str]) -> str:
    return Path(row.get("stage_dir", "")).name


def candidate_exclusion(row: dict[str, str], root: Path) -> str:
    stage_name = row_stage_name(row)
    stage_dir = row.get("stage_dir", "")
    if stage_name not in APPROVED_STAGE_NAMES:
        return "NOT_IN_APPROVED_STAGE_ALLOWLIST"
    if stage_name in HARD_EXCLUDE_STAGE_NAMES:
        return "HARDCODED_SAFETY_EXCLUSION"
    if str_bool(row.get("compression_allowed_in_this_run")):
        return "V206_COMPRESSION_ALLOWED_UNEXPECTED_TRUE"
    if str_bool(row.get("deletion_allowed_after_compression")):
        return "V206_DELETION_ALLOWED_UNEXPECTED_TRUE"
    if row.get("original_directory_retention_policy") != "KEEP_ORIGINAL_UNTIL_SEPARATE_MANUAL_APPROVAL":
        return "V206_RETENTION_POLICY_NOT_SAFE"
    if row.get("exclusion_reason"):
        return f"V206_EXCLUSION_REASON:{row.get('exclusion_reason')}"
    if sensitive_text(stage_dir):
        return "SENSITIVE_STAGE_PATH_KEYWORD"
    source = root / stage_dir
    if not source.exists() or not source.is_dir():
        return "SOURCE_STAGE_DIR_MISSING"
    for file in iter_files(source):
        if sensitive_text(rel(file, root)):
            return "SENSITIVE_FILE_KEYWORD"
    return ""


def select_candidates(plan_rows: list[dict[str, str]], root: Path) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    selected = []
    exclusions = []
    for row in plan_rows:
        reason = candidate_exclusion(row, root)
        stage_name = row_stage_name(row)
        if reason:
            exclusions.append({"stage_name": stage_name, "stage_dir": row.get("stage_dir", ""), "excluded": True, "exclusion_reason": reason})
        else:
            selected.append(row)
            exclusions.append({"stage_name": stage_name, "stage_dir": row.get("stage_dir", ""), "excluded": False, "exclusion_reason": ""})
    return selected, exclusions


def zip_path_for(row: dict[str, str], root: Path) -> Path:
    stage_name = row_stage_name(row)
    return root / ZIP_REL / f"{stage_name}__V21.207_COMPRESS_ONLY_COPY.zip"


def create_zip(source: Path, zip_path: Path, stage_name: str) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file in iter_files(source):
            arcname = f"{stage_name}/{file.relative_to(source).as_posix()}"
            zf.write(file, arcname)


def existing_zip_valid(zip_path: Path, stage_name: str, source_hash: str, source_count: int, source_size: int) -> tuple[bool, dict[str, Any], list[dict[str, Any]]]:
    zhash, ztest, zcount, zsize, members, _status = zip_manifest(zip_path, stage_name)
    valid = bool(zip_path.exists() and ztest and zhash == source_hash and zcount == source_count and zsize == source_size)
    return valid, {"zip_manifest_sha256": zhash, "zip_test_passed": ztest, "zip_member_count": zcount, "zip_uncompressed_size_bytes": zsize}, members


def process_candidate(row: dict[str, str], root: Path, simulate_zip_failure_stage: str | None = None, simulate_source_mutation_stage: str | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    stage_name = row_stage_name(row)
    stage_dir = row["stage_dir"]
    source = root / stage_dir
    before_hash, before_count, before_size, _before_rows = source_manifest(source)
    zip_path = zip_path_for(row, root)
    valid_existing, existing_meta, existing_members = existing_zip_valid(zip_path, stage_name, before_hash, before_count, before_size)
    status = "CREATED_ZIP_COPY"
    overwrite_reason = ""
    error = ""
    if valid_existing:
        status = "SKIP_EXISTING_VALID_ZIP"
        members = existing_members
        zhash = existing_meta["zip_manifest_sha256"]
        ztest = existing_meta["zip_test_passed"]
        zcount = existing_meta["zip_member_count"]
        zsize = existing_meta["zip_uncompressed_size_bytes"]
    else:
        if zip_path.exists():
            overwrite_reason = "FAILED_PRIOR_INTEGRITY_CHECK"
        try:
            if simulate_zip_failure_stage == stage_name:
                raise RuntimeError("simulated zip failure")
            create_zip(source, zip_path, stage_name)
        except Exception as exc:
            status = "ZIP_CREATION_FAILED"
            error = f"{type(exc).__name__}: {exc}"
        if simulate_source_mutation_stage == stage_name:
            (source / "__v21_207_mutation_probe.tmp").write_text("mutation", encoding="utf-8")
        zhash, ztest, zcount, zsize, members, zstatus = zip_manifest(zip_path, stage_name)
        if status != "ZIP_CREATION_FAILED" and not (ztest and zhash == before_hash and zcount == before_count and zsize == before_size):
            status = "ZIP_INTEGRITY_FAILED"
            error = zstatus
    after_hash, after_count, after_size, _after_rows = source_manifest(source) if source.exists() else ("", 0, 0, [])
    unchanged = before_hash == after_hash and before_count == after_count and before_size == after_size
    zip_size = zip_path.stat().st_size if zip_path.exists() else 0
    ratio = round(zip_size / before_size, 6) if before_size else 0.0
    result = {
        "stage_dir": stage_dir,
        "stage_name": stage_name,
        "zip_file_path": str(zip_path),
        "status": status,
        "overwrite_reason": overwrite_reason,
        "source_file_count_before": before_count,
        "source_size_bytes_before": before_size,
        "source_manifest_sha256_before": before_hash,
        "zip_size_bytes": zip_size,
        "zip_exists": zip_path.exists(),
        "zip_test_passed": bool(ztest),
        "zip_member_count": zcount,
        "zip_uncompressed_size_bytes": zsize,
        "zip_manifest_sha256": zhash,
        "source_still_exists_after": source.exists(),
        "source_file_count_after": after_count,
        "source_size_bytes_after": after_size,
        "source_manifest_sha256_after": after_hash,
        "source_unchanged_after": unchanged,
        "compression_ratio_actual": ratio,
        "estimated_space_savings_if_original_later_removed": max(0, before_size - zip_size),
        "deletion_allowed_now": False,
        "error_message": error,
    }
    for member in members:
        member["stage_dir"] = stage_dir
        member["zip_file_path"] = str(zip_path)
    return result, members


def fail_if_protected_included(rows: list[dict[str, str]]) -> bool:
    for row in rows:
        stage_name = row_stage_name(row)
        if stage_name in HARD_EXCLUDE_STAGE_NAMES or stage_name not in APPROVED_STAGE_NAMES or sensitive_text(row.get("stage_dir", "")):
            return True
    return False


def write_report(path: Path, summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"approved_candidate_count={summary['approved_candidate_count']}",
        f"zip_created_count={summary['zip_created_count']}",
        f"zip_skipped_existing_valid_count={summary['zip_skipped_existing_valid_count']}",
        f"zip_failed_count={summary['zip_failed_count']}",
        f"all_sources_unchanged_after={summary['all_sources_unchanged_after']}",
        f"all_zip_integrity_passed={summary['all_zip_integrity_passed']}",
        "deletion_allowed_now=false",
        "research_only=true",
        "compression_copy_creation_allowed=true",
        "source_mutation_allowed=false",
        "deletion_performed=false",
        "archive_movement_performed=false",
        "",
        "zip_results:",
    ]
    lines.extend([f"- {row['stage_name']} status={row['status']} zip={row['zip_file_path']}" for row in results])
    lines.append("")
    lines.append("next_recommended_action=Review zip integrity outputs. Original directories are retained; deletion remains disallowed.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(
    repo_root: Path = DEFAULT_ROOT,
    source_plan: Path | None = None,
    out_dir: Path | None = None,
    simulate_exception: bool = False,
    force_include_protected: bool = False,
    simulate_zip_failure_stage: str | None = None,
    simulate_source_mutation_stage: str | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if simulate_exception:
            raise RuntimeError("simulated V21.207 failure")
        plan_rows = read_csv(source_plan or (root / V206_PLAN_REL))
        selected, exclusions = select_candidates(plan_rows, root)
        if force_include_protected and plan_rows:
            selected.append(plan_rows[0])
        protected_included = fail_if_protected_included(selected)
        results: list[dict[str, Any]] = []
        zip_members: list[dict[str, Any]] = []
        if not protected_included:
            for row in selected:
                result, members = process_candidate(row, root, simulate_zip_failure_stage=simulate_zip_failure_stage, simulate_source_mutation_stage=simulate_source_mutation_stage)
                results.append(result)
                zip_members.extend(members)
        postchecks = [{
            "stage_dir": row["stage_dir"],
            "source_path": str(root / row["stage_dir"]),
            "source_still_exists_after": row["source_still_exists_after"],
            "source_file_count_after": row["source_file_count_after"],
            "source_size_bytes_after": row["source_size_bytes_after"],
            "source_manifest_sha256_after": row["source_manifest_sha256_after"],
            "source_unchanged_after": row["source_unchanged_after"],
        } for row in results]
        all_sources_unchanged = all(bool(row["source_unchanged_after"]) for row in results) if results else not protected_included
        all_zip_ok = all(bool(row["zip_test_passed"]) and row["zip_manifest_sha256"] == row["source_manifest_sha256_before"] for row in results) if results else False
        failed = [row for row in results if row["status"] in {"ZIP_CREATION_FAILED", "ZIP_INTEGRITY_FAILED"}]
        if protected_included:
            final_status = "FAIL_V21_207_PROTECTED_OR_CURRENT_CHAIN_CANDIDATE_INCLUDED"
            final_decision = "ZIP_COPY_CREATION_BLOCKED_PROTECTED_CANDIDATE"
        elif not all_sources_unchanged:
            final_status = "FAIL_V21_207_SOURCE_MUTATION_DETECTED"
            final_decision = "ZIP_COPY_CREATION_FAILED_SOURCE_MUTATION"
        elif failed or not all_zip_ok:
            final_status = "WARN_V21_207_PARTIAL_ZIP_COPY_FAILURE"
            final_decision = "ZIP_COPY_CREATION_PARTIAL_FAILURE_ORIGINALS_RETAINED"
        else:
            final_status = "PASS_V21_207_ZIP_COPY_CREATION_READY"
            final_decision = "ZIP_COPY_CREATION_READY_ORIGINALS_RETAINED"
        total_source = sum(int(row["source_size_bytes_before"]) for row in results)
        total_zip = sum(int(row["zip_size_bytes"]) for row in results)
        summary = {
            "stage": STAGE,
            "approved_candidate_count": len(selected),
            "zip_created_count": sum(1 for row in results if row["status"] == "CREATED_ZIP_COPY"),
            "zip_skipped_existing_valid_count": sum(1 for row in results if row["status"] == "SKIP_EXISTING_VALID_ZIP"),
            "zip_failed_count": len(failed),
            "total_source_size_bytes": total_source,
            "total_zip_size_bytes": total_zip,
            "actual_compression_ratio": round(total_zip / total_source, 6) if total_source else 0.0,
            "estimated_space_savings_if_original_later_removed": max(0, total_source - total_zip),
            "all_sources_unchanged_after": all_sources_unchanged,
            "all_zip_integrity_passed": all_zip_ok,
            "deletion_allowed_now": False,
            "final_status": final_status,
            "final_decision": final_decision,
            "research_only": True,
            "compression_copy_creation_allowed": True,
            "mutation_allowed_limited_to_new_zip_and_v21_207_artifacts": True,
            "source_mutation_allowed": False,
            "deletion_performed": False,
            "archive_movement_performed": False,
            "original_directories_removed": False,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "protected_outputs_modified": False,
            "canonical_mutation_performed": False,
            "price_refresh_performed": False,
        }
        write_csv(output / "zip_copy_creation_result.csv", results, RESULT_FIELDS)
        write_csv(output / "zip_copy_integrity_check.csv", results, INTEGRITY_FIELDS)
        write_csv(output / "source_directory_postcheck.csv", postchecks, POSTCHECK_FIELDS)
        write_csv(output / "zip_file_manifest.csv", zip_members, MANIFEST_FIELDS)
        write_csv(output / "compression_exclusion_check.csv", exclusions, EXCLUSION_FIELDS)
        write_json(output / "v21_207_summary.json", summary)
        write_report(output / "V21.207_compress_only_zip_copy_creation_report.txt", summary, results)
    except Exception as exc:
        summary = {
            "stage": STAGE,
            "final_status": "FAIL_V21_207_ZIP_COPY_EXCEPTION",
            "final_decision": "ZIP_COPY_CREATION_FAILED",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "research_only": True,
            "compression_copy_creation_allowed": True,
            "mutation_allowed_limited_to_new_zip_and_v21_207_artifacts": True,
            "source_mutation_allowed": False,
            "deletion_performed": False,
            "archive_movement_performed": False,
            "original_directories_removed": False,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "protected_outputs_modified": False,
            "canonical_mutation_performed": False,
            "price_refresh_performed": False,
        }
        write_json(output / "v21_207_summary.json", summary)
        (output / "V21.207_compress_only_zip_copy_creation_report.txt").write_text(
            "\n".join([STAGE, f"final_status={summary['final_status']}", f"final_decision={summary['final_decision']}", f"error={summary['error_type']}: {summary['error_message']}"]) + "\n",
            encoding="utf-8",
        )
    for key in ["final_status", "final_decision", "approved_candidate_count", "zip_created_count", "zip_skipped_existing_valid_count", "zip_failed_count", "all_sources_unchanged_after", "deletion_performed", "broker_action_allowed"]:
        if key in summary:
            print(f"{key}={summary[key]}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", default=str(DEFAULT_ROOT))
    parser.add_argument("--source-plan", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source = Path(args.source_plan) if args.source_plan else None
    summary = run(Path(args.repo_root), source_plan=source)
    return 0 if str(summary["final_status"]).startswith(("PASS", "WARN")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
