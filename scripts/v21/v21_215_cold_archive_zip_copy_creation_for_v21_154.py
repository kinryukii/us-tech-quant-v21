#!/usr/bin/env python
"""V21.215 cold archive zip copy creation for V21.154 only.

Creates a verified zip *copy* for the V21.154 audit-critical stage. It never
deletes, moves, rewrites source files, refreshes prices, mutates canonical
files, connects to OpenD, changes adoption outputs, or performs broker actions.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path(r"D:\us-tech-quant")
STAGE = "V21.215_COLD_ARCHIVE_ZIP_COPY_CREATION_FOR_V21_154"
OUT_REL = Path("outputs/v21/V21.215_COLD_ARCHIVE_ZIP_COPY_CREATION_FOR_V21_154")
ZIP_REL = Path("archive/v21_cold_archive_stage_copies/V21.215_COLD_ARCHIVE_ZIP_COPY_CREATION_FOR_V21_154")
PLAN_REL = Path("outputs/v21/V21.214_LARGE_OUTPUTS_COLD_ARCHIVE_CANDIDATE_PLAN/large_outputs_cold_archive_candidate_plan.csv")
APPROVED_STAGE = "V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT"
ZIP_NAME = f"{APPROVED_STAGE}__V21.215_COLD_ARCHIVE_COPY.zip"
PROTECTED_REQUIRED = [
    ".venv",
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
    "outputs/v21/V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY",
    "outputs/v21/V21.214_LARGE_OUTPUTS_COLD_ARCHIVE_CANDIDATE_PLAN",
    f"outputs/v21/{APPROVED_STAGE}",
]
HARD_EXCLUDED = {
    "V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020",
    "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
}
for number in range(202, 215):
    HARD_EXCLUDED.add(f"V21.{number}")

RESULT_FIELDS = [
    "stage_dir", "source_path", "zip_file_path", "status", "overwrite_reason",
    "source_file_count_before", "source_size_bytes_before", "source_manifest_sha256_before",
    "zip_exists", "zip_size_bytes", "zip_test_passed", "zip_member_count",
    "zip_uncompressed_size_bytes", "zip_manifest_sha256", "source_still_exists_after",
    "source_file_count_after", "source_size_bytes_after", "source_manifest_sha256_after",
    "source_unchanged_after", "compression_ratio_actual",
    "estimated_space_savings_if_expanded_original_removed_later", "deletion_allowed_now",
    "error_message",
]
INTEGRITY_FIELDS = [
    "stage_dir", "source_file_count_before", "source_size_bytes_before",
    "source_manifest_sha256_before", "zip_file_path", "zip_exists", "zip_size_bytes",
    "zip_test_passed", "zip_member_count", "zip_uncompressed_size_bytes",
    "zip_manifest_sha256", "source_still_exists_after", "source_file_count_after",
    "source_size_bytes_after", "source_manifest_sha256_after", "source_unchanged_after",
    "compression_ratio_actual", "estimated_space_savings_if_expanded_original_removed_later",
    "deletion_allowed_now",
]
SOURCE_MANIFEST_FIELDS = ["relative_file_path", "file_size_bytes", "modified_time", "sha256", "file_extension", "manifest_status"]
POSTCHECK_FIELDS = ["stage_dir", "source_path", "source_still_exists_after", "source_file_count_after", "source_size_bytes_after", "source_manifest_sha256_after", "source_unchanged_after"]
ZIP_MANIFEST_FIELDS = ["stage_dir", "zip_file_path", "zip_member_path", "member_size_bytes", "member_crc", "manifest_status"]
PRESENCE_FIELDS = ["protected_key", "expected_path", "exact_exists", "alias_discovery_attempted", "alias_candidate_count", "resolved_exists", "resolved_protected_path", "resolution_method", "warning_reason"]


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
        return sorted([p for p in path.rglob("*") if p.is_file()], key=lambda p: p.relative_to(path).as_posix())
    except OSError:
        return []


def file_mtime(path: Path) -> str:
    try:
        return str(path.stat().st_mtime)
    except OSError:
        return ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_manifest(source: Path) -> tuple[str, int, int, list[dict[str, Any]]]:
    digest = hashlib.sha256()
    rows: list[dict[str, Any]] = []
    total = 0
    for file in iter_files(source):
        stat = file.stat()
        file_hash = sha256_file(file)
        rel_path = file.relative_to(source).as_posix()
        total += stat.st_size
        digest.update(f"{rel_path}\t{stat.st_size}\t{file_hash}\n".encode("utf-8"))
        rows.append({
            "relative_file_path": rel_path,
            "file_size_bytes": stat.st_size,
            "modified_time": file_mtime(file),
            "sha256": file_hash,
            "file_extension": file.suffix.lower(),
            "manifest_status": "SOURCE_FILE_OK",
        })
    return digest.hexdigest(), len(rows), total, rows


def zip_manifest(zip_path: Path, stage_name: str) -> tuple[str, bool, int, int, list[dict[str, Any]], str]:
    rows: list[dict[str, Any]] = []
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
                member_hash = hashlib.sha256(data).hexdigest()
                member = info.filename.replace("\\", "/")
                rel_member = member[len(stage_name) + 1:] if member.startswith(stage_name + "/") else member
                total += info.file_size
                digest.update(f"{rel_member}\t{info.file_size}\t{member_hash}\n".encode("utf-8"))
                rows.append({
                    "stage_dir": stage_name,
                    "zip_file_path": str(zip_path),
                    "zip_member_path": member,
                    "member_size_bytes": info.file_size,
                    "member_crc": info.CRC,
                    "manifest_status": "ZIP_MEMBER_OK",
                })
        return digest.hexdigest(), True, len(rows), total, rows, "ZIP_TEST_PASSED"
    except Exception as exc:
        return "", False, 0, 0, rows, f"ZIP_EXCEPTION:{type(exc).__name__}:{exc}"


def create_zip(source: Path, zip_path: Path, stage_name: str) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file in iter_files(source):
            zf.write(file, f"{stage_name}/{file.relative_to(source).as_posix()}")


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


def select_candidate(root: Path) -> tuple[dict[str, str] | None, str]:
    rows = read_csv(root / PLAN_REL)
    for row in rows:
        stage = row.get("stage_dir", "")
        if stage != APPROVED_STAGE:
            continue
        if row.get("cold_archive_candidate_tier") != "TIER_A_COLD_ARCHIVE_RETAIN_EVIDENCE":
            return None, "V21_154_NOT_TIER_A"
        if row.get("future_action_plan") != "ZIP_COPY_ONLY_NEXT_STAGE":
            return None, "V21_154_ACTION_NOT_ZIP_COPY"
        if str_bool(row.get("compression_allowed_in_this_run")):
            return None, "V21_214_COMPRESSION_ALLOWED_UNEXPECTED_TRUE"
        if str_bool(row.get("deletion_allowed_in_this_run")):
            return None, "V21_214_DELETION_ALLOWED_UNEXPECTED_TRUE"
        return row, ""
    return None, "V21_154_PLAN_ROW_MISSING"


def hard_exclusion_reason(stage: str) -> str:
    if stage == APPROVED_STAGE:
        return ""
    if stage in HARD_EXCLUDED:
        return "HARDCODED_EXCLUSION"
    if any(stage.startswith(prefix) for prefix in HARD_EXCLUDED if prefix.startswith("V21.")):
        return "CLEANUP_OR_CURRENT_CHAIN_EXCLUSION"
    return "NOT_APPROVED_V21_154"


def zip_path(root: Path) -> Path:
    return root / ZIP_REL / ZIP_NAME


def process(root: Path, simulate_zip_failure: bool = False, simulate_source_mutation: bool = False) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    source = root / "outputs/v21" / APPROVED_STAGE
    zpath = zip_path(root)
    before_hash, before_count, before_size, source_rows = source_manifest(source)
    zhash, ztest, zcount, zsize, zip_rows, _zstatus = zip_manifest(zpath, APPROVED_STAGE)
    valid_existing = zpath.exists() and ztest and zhash == before_hash and zcount == before_count and zsize == before_size
    status = "SKIP_EXISTING_VALID_ZIP" if valid_existing else "CREATED_ZIP_COPY"
    overwrite_reason = ""
    error = ""
    if not valid_existing:
        if zpath.exists():
            overwrite_reason = "FAILED_PRIOR_INTEGRITY_CHECK"
        try:
            if simulate_zip_failure:
                raise RuntimeError("simulated zip failure")
            create_zip(source, zpath, APPROVED_STAGE)
        except Exception as exc:
            status = "ZIP_CREATION_FAILED"
            error = f"{type(exc).__name__}: {exc}"
        if simulate_source_mutation:
            (source / "__v21_215_mutation_probe.tmp").write_text("mutation", encoding="utf-8")
        zhash, ztest, zcount, zsize, zip_rows, zstatus = zip_manifest(zpath, APPROVED_STAGE)
        if status != "ZIP_CREATION_FAILED" and not (ztest and zhash == before_hash and zcount == before_count and zsize == before_size):
            status = "ZIP_INTEGRITY_FAILED"
            error = zstatus
    after_hash, after_count, after_size, _after_rows = source_manifest(source) if source.exists() else ("", 0, 0, [])
    unchanged = before_hash == after_hash and before_count == after_count and before_size == after_size
    zip_size = zpath.stat().st_size if zpath.exists() else 0
    ratio = (zip_size / before_size) if before_size else 0
    savings = max(0, before_size - zip_size)
    result = {
        "stage_dir": APPROVED_STAGE,
        "source_path": rel(source, root),
        "zip_file_path": rel(zpath, root),
        "status": status,
        "overwrite_reason": overwrite_reason,
        "source_file_count_before": before_count,
        "source_size_bytes_before": before_size,
        "source_manifest_sha256_before": before_hash,
        "zip_exists": zpath.exists(),
        "zip_size_bytes": zip_size,
        "zip_test_passed": ztest,
        "zip_member_count": zcount,
        "zip_uncompressed_size_bytes": zsize,
        "zip_manifest_sha256": zhash,
        "source_still_exists_after": source.exists(),
        "source_file_count_after": after_count,
        "source_size_bytes_after": after_size,
        "source_manifest_sha256_after": after_hash,
        "source_unchanged_after": unchanged,
        "compression_ratio_actual": ratio,
        "estimated_space_savings_if_expanded_original_removed_later": savings,
        "deletion_allowed_now": False,
        "error_message": error,
    }
    postcheck = {
        "stage_dir": APPROVED_STAGE,
        "source_path": rel(source, root),
        "source_still_exists_after": source.exists(),
        "source_file_count_after": after_count,
        "source_size_bytes_after": after_size,
        "source_manifest_sha256_after": after_hash,
        "source_unchanged_after": unchanged,
    }
    integrity = {field: result.get(field, "") for field in INTEGRITY_FIELDS}
    return result, integrity, postcheck, source_rows, zip_rows


def policy_flags(zip_created: bool) -> dict[str, Any]:
    return {
        "research_only": True,
        "cold_archive_copy_creation_allowed": True,
        "mutation_allowed_limited_to_new_zip_and_v21_215_artifacts": True,
        "source_mutation_allowed": False,
        "deletion_performed": False,
        "original_directory_removed": False,
        "compression_performed": zip_created,
        "archive_movement_performed": False,
        "price_refresh_performed": False,
        "canonical_mutation_performed": False,
        "moomoo_broker_connection_performed": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "protected_outputs_modified": False,
    }


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"zip_integrity_passed={summary.get('zip_integrity_passed')}",
        f"source_unchanged_after={summary.get('source_unchanged_after')}",
        f"zip_size_bytes={summary.get('zip_size_bytes')}",
        f"deletion_allowed_now={summary.get('deletion_allowed_now')}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_outputs(output: Path, result: dict[str, Any], integrity: dict[str, Any], postcheck: dict[str, Any], source_rows: list[dict[str, Any]], zip_rows: list[dict[str, Any]], presence: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    write_csv(output / "cold_archive_zip_copy_result.csv", [result], RESULT_FIELDS)
    write_csv(output / "cold_archive_zip_integrity_check.csv", [integrity], INTEGRITY_FIELDS)
    write_csv(output / "source_directory_pre_manifest.csv", source_rows, SOURCE_MANIFEST_FIELDS)
    write_csv(output / "source_directory_postcheck.csv", [postcheck], POSTCHECK_FIELDS)
    write_csv(output / "zip_file_manifest.csv", zip_rows, ZIP_MANIFEST_FIELDS)
    write_csv(output / "protected_path_presence_check.csv", presence, PRESENCE_FIELDS)
    (output / "v21_154_audit_evidence_retention_note.txt").write_text("V21.154 is audit-critical evidence. V21.215 creates a zip copy only; the expanded original remains retained and deletion_allowed_now=false.\n", encoding="utf-8")
    write_json(output / "v21_215_summary.json", summary)
    write_report(output / "V21.215_cold_archive_zip_copy_creation_report.txt", summary)


def run(repo_root: Path = DEFAULT_ROOT, out_dir: Path | None = None, simulate_exception: bool = False, simulate_zip_failure: bool = False, simulate_source_mutation: bool = False) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    zip_created = False
    try:
        if simulate_exception:
            raise RuntimeError("simulated V21.215 failure")
        presence = protected_presence(root)
        missing = [row for row in presence if not str_bool(row["resolved_exists"])]
        candidate, candidate_error = select_candidate(root)
        if missing:
            summary = {"stage": STAGE, "approved_candidate_count": 0, "zip_created_count": 0, "zip_skipped_existing_valid_count": 0, "zip_failed_count": 0, "source_size_bytes": 0, "zip_size_bytes": 0, "compression_ratio_actual": 0, "estimated_space_savings_if_expanded_original_removed_later": 0, "source_unchanged_after": False, "zip_integrity_passed": False, "deletion_allowed_now": False, "protected_path_missing_count": len(missing), "final_status": "FAIL_V21_215_PROTECTED_PATH_MISSING", "final_decision": "COLD_ARCHIVE_ZIP_COPY_FAILED_PROTECTED_PATH_MISSING", **policy_flags(False)}
            write_outputs(output, {}, {}, {}, [], [], presence, summary)
            return summary
        if not candidate:
            summary = {"stage": STAGE, "approved_candidate_count": 0, "zip_created_count": 0, "zip_skipped_existing_valid_count": 0, "zip_failed_count": 1, "source_size_bytes": 0, "zip_size_bytes": 0, "compression_ratio_actual": 0, "estimated_space_savings_if_expanded_original_removed_later": 0, "source_unchanged_after": True, "zip_integrity_passed": False, "deletion_allowed_now": False, "protected_path_missing_count": 0, "final_status": "WARN_V21_215_COLD_ARCHIVE_ZIP_COPY_FAILED_SOURCE_RETAINED", "final_decision": "COLD_ARCHIVE_ZIP_COPY_FAILED_ORIGINAL_RETAINED", **policy_flags(False)}
            result = {"stage_dir": APPROVED_STAGE, "status": "CANDIDATE_NOT_APPROVED", "error_message": candidate_error, "deletion_allowed_now": False}
            write_outputs(output, result, {}, {}, [], [], presence, summary)
            return summary
        result, integrity, postcheck, source_rows, zip_rows = process(root, simulate_zip_failure, simulate_source_mutation)
        zip_valid = str_bool(result["zip_test_passed"]) and result["zip_manifest_sha256"] == result["source_manifest_sha256_before"]
        source_unchanged = str_bool(result["source_unchanged_after"])
        zip_created = result["status"] == "CREATED_ZIP_COPY"
        skipped = result["status"] == "SKIP_EXISTING_VALID_ZIP"
        failed = not zip_valid or result["status"] in {"ZIP_CREATION_FAILED", "ZIP_INTEGRITY_FAILED"}
        if not source_unchanged:
            final_status = "FAIL_V21_215_SOURCE_MUTATION_DETECTED"
            final_decision = "COLD_ARCHIVE_ZIP_COPY_FAILED_SOURCE_MUTATION"
        elif zip_valid:
            final_status = "PASS_V21_215_COLD_ARCHIVE_ZIP_COPY_READY"
            final_decision = "COLD_ARCHIVE_ZIP_COPY_READY_ORIGINAL_RETAINED"
        else:
            final_status = "WARN_V21_215_COLD_ARCHIVE_ZIP_COPY_FAILED_SOURCE_RETAINED"
            final_decision = "COLD_ARCHIVE_ZIP_COPY_FAILED_ORIGINAL_RETAINED"
        summary = {
            "stage": STAGE,
            "approved_candidate_count": 1,
            "zip_created_count": 1 if zip_created else 0,
            "zip_skipped_existing_valid_count": 1 if skipped else 0,
            "zip_failed_count": 1 if failed else 0,
            "source_size_bytes": result["source_size_bytes_before"],
            "zip_size_bytes": result["zip_size_bytes"],
            "compression_ratio_actual": result["compression_ratio_actual"],
            "estimated_space_savings_if_expanded_original_removed_later": result["estimated_space_savings_if_expanded_original_removed_later"],
            "source_unchanged_after": source_unchanged,
            "zip_integrity_passed": zip_valid,
            "deletion_allowed_now": False,
            "protected_path_missing_count": 0,
            "final_status": final_status,
            "final_decision": final_decision,
            **policy_flags(zip_created),
        }
        write_outputs(output, result, integrity, postcheck, source_rows, zip_rows, presence, summary)
    except Exception as exc:
        summary = {"stage": STAGE, "final_status": "FAIL_V21_215_COLD_ARCHIVE_ZIP_EXCEPTION", "final_decision": "COLD_ARCHIVE_ZIP_COPY_FAILED", "error_type": type(exc).__name__, "error_message": str(exc), **policy_flags(zip_created)}
        write_json(output / "v21_215_summary.json", summary)
        (output / "V21.215_cold_archive_zip_copy_creation_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\nerror={summary['error_type']}: {summary['error_message']}\n", encoding="utf-8")
    for key in ["final_status", "final_decision", "zip_created_count", "zip_skipped_existing_valid_count", "zip_failed_count", "source_unchanged_after", "zip_integrity_passed", "deletion_allowed_now"]:
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
