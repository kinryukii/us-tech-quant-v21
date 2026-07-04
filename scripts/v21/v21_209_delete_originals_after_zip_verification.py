#!/usr/bin/env python
"""V21.209 delete originals after zip verification.

Deletes only the three explicitly approved, zip-verified V21 output stage
directories after the exact manual approval phrase is supplied. Zip archive
copies are retained and reverified before and after deletion.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path(r"D:\us-tech-quant")
STAGE = "V21.209_DELETE_ORIGINALS_AFTER_ZIP_VERIFICATION"
OUT_REL = Path("outputs/v21/V21.209_DELETE_ORIGINALS_AFTER_ZIP_VERIFICATION")
V208_PLAN_REL = Path("outputs/v21/V21.208_ORIGINAL_REMOVAL_DRY_RUN_APPROVAL_GATE/original_removal_dry_run_approval_plan.csv")
V207_INTEGRITY_REL = Path("outputs/v21/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION/zip_copy_integrity_check.csv")
APPROVAL_PHRASE = "APPROVE_V21_209_DELETE_ORIGINALS_AFTER_ZIP_VERIFICATION"
APPROVED_STAGE_DIRS = {
    "outputs/v21/V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST",
    "outputs/v21/V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST",
    "outputs/v21/V21.148_E_R1_A1_PIT_LITE_REPLAY_DIAGNOSTIC_ONLY",
}
HARD_EXCLUDE_STAGE_DIRS = {
    "outputs/v21/V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020",
    "outputs/v21/V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT",
    "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
    "outputs/v21/V21.202_REPO_SAFE_CLEANUP_AUDIT_AND_CACHE_PURGE",
    "outputs/v21/V21.203_REPO_SIZE_ATTRIBUTION_AND_SAFE_PURGE_CANDIDATE_AUDIT",
    "outputs/v21/V21.204_OUTPUTS_V21_ARCHIVE_CANDIDATE_AUDIT",
    "outputs/v21/V21.205_LARGE_STAGE_RETENTION_VALUE_CLASSIFICATION",
    "outputs/v21/V21.206_COMPRESS_ONLY_DRY_RUN_PLAN",
    "outputs/v21/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION",
    "outputs/v21/V21.208_ORIGINAL_REMOVAL_DRY_RUN_APPROVAL_GATE",
}
SENSITIVE_TOKENS = [
    "canonical",
    "price_history",
    "ohlcv",
    "kline",
    "moomoo",
    "dram",
    "abcde",
    "trade_plan",
    "ledger",
    "ranking",
    "latest",
    "current_chain",
    "protected",
]
PROTECTED_REQUIRED = [
    ".venv",
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
    "outputs/v21/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION",
    "outputs/v21/V21.208_ORIGINAL_REMOVAL_DRY_RUN_APPROVAL_GATE",
    "archive/v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION",
]

RESULT_FIELDS = [
    "stage_dir",
    "source_path",
    "zip_file_path",
    "pre_delete_source_exists",
    "pre_delete_zip_exists",
    "pre_delete_zip_test_passed",
    "pre_delete_source_file_count",
    "pre_delete_source_size_bytes",
    "pre_delete_source_manifest_sha256",
    "pre_delete_zip_member_count",
    "pre_delete_zip_uncompressed_size_bytes",
    "pre_delete_zip_manifest_sha256",
    "deletion_attempted",
    "deletion_status",
    "deleted_size_bytes",
    "delete_error_type",
    "delete_error_message",
    "post_delete_source_exists",
    "post_delete_zip_exists",
    "post_delete_zip_test_passed",
    "post_delete_zip_manifest_sha256",
    "zip_archives_deleted",
]
ZIP_FIELDS = [
    "stage_dir",
    "zip_file_path",
    "source_manifest_sha256",
    "source_file_count",
    "source_size_bytes",
    "zip_exists",
    "zip_test_passed",
    "zip_member_count",
    "zip_uncompressed_size_bytes",
    "zip_manifest_sha256",
    "integrity_passed",
    "integrity_phase",
    "blocker_reasons",
]
MANIFEST_FIELDS = ["stage_dir", "relative_file_path", "file_size_bytes", "modified_time", "sha256"]
POST_FIELDS = ["stage_dir", "source_path", "source_exists_after", "zip_file_path", "zip_exists_after", "zip_test_passed_after"]
PRESENCE_FIELDS = [
    "protected_key",
    "expected_path",
    "exact_exists",
    "alias_discovery_attempted",
    "alias_candidate_count",
    "resolved_exists",
    "resolved_protected_path",
    "resolution_method",
    "warning_reason",
]
BLOCKER_FIELDS = ["stage_dir", "blocker_type", "blocker_detail"]


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/")


def norm_rel(path: str | Path, root: Path | None = None) -> str:
    p = Path(path)
    if root and p.is_absolute():
        return rel(p, root)
    return str(path).replace("\\", "/").strip("/")


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


def stage_name(stage_dir: str) -> str:
    return Path(stage_dir).name


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
    digest = hashlib.sha256()
    rows: list[dict[str, Any]] = []
    total = 0
    if not source.exists() or not source.is_dir():
        return "", 0, 0, rows
    for file in iter_files(source):
        size = file.stat().st_size
        file_hash = sha256_file(file)
        rel_path = file.relative_to(source).as_posix()
        total += size
        digest.update(f"{rel_path}\t{size}\t{file_hash}\n".encode("utf-8"))
        rows.append({
            "relative_file_path": rel_path,
            "file_size_bytes": size,
            "modified_time": file.stat().st_mtime,
            "sha256": file_hash,
        })
    return digest.hexdigest(), len(rows), total, rows


def zip_manifest(zip_path: Path, name: str) -> tuple[str, bool, int, int, str]:
    digest = hashlib.sha256()
    count = 0
    total = 0
    if not zip_path.exists():
        return "", False, 0, 0, "ZIP_MISSING"
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad = zf.testzip()
            if bad:
                return "", False, 0, 0, f"ZIP_TEST_FAILED:{bad}"
            infos = sorted([info for info in zf.infolist() if not info.is_dir()], key=lambda info: info.filename)
            for info in infos:
                member = info.filename.replace("\\", "/")
                rel_member = member[len(name) + 1:] if member.startswith(name + "/") else member
                data_hash = hashlib.sha256(zf.read(info.filename)).hexdigest()
                digest.update(f"{rel_member}\t{info.file_size}\t{data_hash}\n".encode("utf-8"))
                count += 1
                total += info.file_size
        return digest.hexdigest(), True, count, total, "ZIP_TEST_PASSED"
    except Exception as exc:
        return "", False, 0, 0, f"ZIP_EXCEPTION:{type(exc).__name__}:{exc}"


def sensitive_hits(path: Path, root: Path) -> list[str]:
    targets = [rel(path, root)]
    targets.extend(rel(file, root) for file in iter_files(path))
    hits = []
    for target in targets:
        text = target.lower().replace("\\", "/")
        for token in SENSITIVE_TOKENS:
            if token in text:
                hits.append(f"{token}:{target}")
    return hits


def protected_alias_candidates(root: Path, stage_id: str) -> list[Path]:
    out21 = root / "outputs/v21"
    if not out21.exists():
        return []
    candidates = []
    for child in out21.iterdir():
        if not child.is_dir() or not child.name.startswith(stage_id):
            continue
        if stage_id == "V21.201" and not v21_201_alias_is_current_chain(child):
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


def newest_path(paths: list[Path]) -> Path:
    return max(paths, key=lambda p: p.stat().st_mtime)


def protected_presence(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in PROTECTED_REQUIRED:
        expected = root / item
        exact_exists = expected.exists()
        alias_attempted = False
        candidates: list[Path] = []
        resolved = expected if exact_exists else None
        method = "EXACT_PATH" if exact_exists else "UNRESOLVED"
        warning = "" if exact_exists else "EXPECTED_PATH_MISSING"
        if not exact_exists and item.startswith("outputs/v21/V21."):
            alias_attempted = True
            sid = Path(item).name.split("_", 1)[0]
            candidates = protected_alias_candidates(root, sid)
            if candidates:
                resolved = newest_path(candidates)
                method = "ALIAS_DISCOVERY_NEWEST_MODIFIED"
                warning = ""
        rows.append({
            "protected_key": Path(item).name,
            "expected_path": item,
            "exact_exists": exact_exists,
            "alias_discovery_attempted": alias_attempted,
            "alias_candidate_count": len(candidates),
            "resolved_exists": bool(resolved and resolved.exists()),
            "resolved_protected_path": rel(resolved, root) if resolved else "",
            "resolution_method": method,
            "warning_reason": warning,
        })
    return rows


def approval_received(approval_phrase: str | None) -> bool:
    provided = approval_phrase or os.environ.get("V21_209_APPROVAL_PHRASE", "")
    return provided == APPROVAL_PHRASE


def v207_by_stage(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row.get("stage_dir", ""): row for row in rows}


def candidate_blockers(row: dict[str, str], v207: dict[str, str], root: Path) -> list[str]:
    sdir = norm_rel(row.get("stage_dir", ""), root)
    source = root / sdir
    blockers: list[str] = []
    if sdir not in APPROVED_STAGE_DIRS:
        blockers.append("NOT_APPROVED_ELIGIBLE_ORIGINAL")
    if sdir in HARD_EXCLUDE_STAGE_DIRS:
        blockers.append("HARDCODED_SAFETY_EXCLUSION")
    if any(token in sdir.lower() for token in SENSITIVE_TOKENS):
        blockers.append("SENSITIVE_STAGE_PATH_KEYWORD")
    if not str_bool(row.get("eligible_for_future_deletion")):
        blockers.append("V21_208_NOT_ELIGIBLE")
    if not str_bool(row.get("integrity_recheck_passed")):
        blockers.append("V21_208_INTEGRITY_RECHECK_NOT_PASSED")
    if not str_bool(row.get("zip_exists")) or not str_bool(row.get("zip_test_passed")):
        blockers.append("V21_208_ZIP_NOT_VALID")
    if not str_bool(row.get("source_exists")):
        blockers.append("V21_208_SOURCE_NOT_PRESENT")
    if not v207:
        blockers.append("V21_207_INTEGRITY_ROW_MISSING")
    if source.exists() and sensitive_hits(source, root):
        blockers.append("SENSITIVE_FILE_KEYWORD")
    return blockers


def predelete_check(row: dict[str, str], root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    sdir = norm_rel(row["stage_dir"], root)
    name = stage_name(sdir)
    source = root / sdir
    zip_path = Path(row.get("zip_file_path", ""))
    if not zip_path.is_absolute():
        zip_path = root / zip_path
    source_hash, source_count, source_size, manifest_rows = source_manifest(source)
    zip_hash, zip_ok, zip_count, zip_uncompressed, zip_status = zip_manifest(zip_path, name)
    blockers = []
    if not source.exists():
        blockers.append("SOURCE_MISSING")
    if not zip_path.exists():
        blockers.append("ZIP_MISSING")
    if not zip_ok:
        blockers.append(zip_status)
    if source_hash != zip_hash or source_count != zip_count or source_size != zip_uncompressed:
        blockers.append("SOURCE_ZIP_MANIFEST_MISMATCH")
    for manifest in manifest_rows:
        manifest["stage_dir"] = sdir
    check = {
        "stage_dir": sdir,
        "zip_file_path": str(zip_path),
        "source_manifest_sha256": source_hash,
        "source_file_count": source_count,
        "source_size_bytes": source_size,
        "zip_exists": zip_path.exists(),
        "zip_test_passed": zip_ok,
        "zip_member_count": zip_count,
        "zip_uncompressed_size_bytes": zip_uncompressed,
        "zip_manifest_sha256": zip_hash,
        "integrity_passed": not blockers,
        "integrity_phase": "PRE_DELETE",
        "blocker_reasons": "|".join(blockers),
    }
    return check, manifest_rows, blockers


def delete_source(source: Path) -> tuple[bool, str, str]:
    try:
        shutil.rmtree(source)
        return True, "", ""
    except Exception as exc:
        return False, type(exc).__name__, str(exc)


def policy_flags(approved: bool, deletion_performed: bool) -> dict[str, Any]:
    return {
        "research_only": True,
        "explicit_manual_approval_required": True,
        "explicit_manual_approval_received": approved,
        "deletion_performed": deletion_performed,
        "deletion_scope_limited_to_zip_verified_originals": True,
        "zip_archives_deleted": False,
        "compression_performed": False,
        "archive_movement_performed": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "protected_outputs_modified": False,
        "canonical_mutation_performed": False,
        "price_refresh_performed": False,
    }


def write_report(path: Path, summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"approved_candidate_count={summary.get('approved_candidate_count', 0)}",
        f"deletion_attempt_count={summary.get('deletion_attempt_count', 0)}",
        f"deleted_count={summary.get('deleted_count', 0)}",
        f"deleted_size_bytes={summary.get('deleted_size_bytes', 0)}",
        f"failed_delete_count={summary.get('failed_delete_count', 0)}",
        f"skipped_count={summary.get('skipped_count', 0)}",
        f"all_zip_integrity_passed_after={summary.get('all_zip_integrity_passed_after', False)}",
        f"all_protected_paths_present_after={summary.get('all_protected_paths_present_after', False)}",
        f"explicit_manual_approval_received={summary.get('explicit_manual_approval_received', False)}",
        "zip_archives_deleted=false",
        "broker_action_allowed=false",
        "official_adoption_allowed=false",
        "",
        "deletion_results:",
    ]
    lines.extend([f"- {row['stage_dir']} status={row['deletion_status']} zip_exists_after={row['post_delete_zip_exists']}" for row in results])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_empty_artifacts(output: Path) -> None:
    write_csv(output / "deletion_execution_result.csv", [], RESULT_FIELDS)
    write_csv(output / "pre_delete_zip_integrity_recheck.csv", [], ZIP_FIELDS)
    write_csv(output / "pre_delete_source_manifest.csv", [], MANIFEST_FIELDS)
    write_csv(output / "post_delete_presence_check.csv", [], POST_FIELDS)
    write_csv(output / "protected_path_presence_check.csv", [], PRESENCE_FIELDS)
    write_csv(output / "deletion_blocker_check.csv", [], BLOCKER_FIELDS)


def run(
    repo_root: Path = DEFAULT_ROOT,
    approval_phrase: str | None = None,
    v208_plan: Path | None = None,
    v207_integrity: Path | None = None,
    out_dir: Path | None = None,
    simulate_exception: bool = False,
    simulate_delete_failure_stage: str | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    approved = approval_received(approval_phrase)
    try:
        if simulate_exception:
            raise RuntimeError("simulated V21.209 failure")
        if not approved:
            write_empty_artifacts(output)
            summary = {
                "stage": STAGE,
                "approved_candidate_count": 0,
                "deletion_attempt_count": 0,
                "deleted_count": 0,
                "deleted_size_bytes": 0,
                "failed_delete_count": 0,
                "skipped_count": 0,
                "zip_integrity_pass_count": 0,
                "protected_path_missing_count": 0,
                "all_zip_integrity_passed_after": False,
                "all_protected_paths_present_after": False,
                "final_status": "FAIL_V21_209_MANUAL_APPROVAL_MISSING",
                "final_decision": "DELETE_ORIGINALS_BLOCKED_MANUAL_APPROVAL_MISSING",
                **policy_flags(False, False),
            }
            write_json(output / "v21_209_summary.json", summary)
            write_report(output / "V21.209_delete_originals_after_zip_verification_report.txt", summary, [])
            return summary
        plan_rows = read_csv(v208_plan or (root / V208_PLAN_REL))
        v207_rows = v207_by_stage(read_csv(v207_integrity or (root / V207_INTEGRITY_REL)))
        presence_before = protected_presence(root)
        protected_missing_before = [row for row in presence_before if not str_bool(row["resolved_exists"])]
        selected: list[dict[str, str]] = []
        blocker_rows: list[dict[str, Any]] = []
        for row in plan_rows:
            sdir = norm_rel(row.get("stage_dir", ""), root)
            blockers = candidate_blockers(row, v207_rows.get(sdir, {}), root)
            if blockers:
                if blockers == ["NOT_APPROVED_ELIGIBLE_ORIGINAL"]:
                    continue
                for blocker in blockers:
                    blocker_rows.append({"stage_dir": sdir, "blocker_type": blocker, "blocker_detail": blocker})
                continue
            selected.append(row)
        for row in protected_missing_before:
            blocker_rows.append({"stage_dir": row["expected_path"], "blocker_type": "PROTECTED_PATH_MISSING_BEFORE", "blocker_detail": row["warning_reason"]})
        prechecks: list[dict[str, Any]] = []
        manifest_rows: list[dict[str, Any]] = []
        precheck_blocked = False
        for row in selected:
            check, manifests, blockers = predelete_check(row, root)
            prechecks.append(check)
            manifest_rows.extend(manifests)
            for blocker in blockers:
                blocker_rows.append({"stage_dir": check["stage_dir"], "blocker_type": blocker.split(":", 1)[0], "blocker_detail": blocker})
            precheck_blocked = precheck_blocked or bool(blockers)
        protected_or_current_blocker = any(
            row["blocker_type"] in {"NOT_APPROVED_ELIGIBLE_ORIGINAL", "HARDCODED_SAFETY_EXCLUSION", "SENSITIVE_STAGE_PATH_KEYWORD", "SENSITIVE_FILE_KEYWORD"}
            for row in blocker_rows
        )
        if protected_missing_before:
            final_status = "FAIL_V21_209_PROTECTED_PATH_MISSING_AFTER"
            final_decision = "DELETE_ORIGINALS_FAILED_PROTECTED_PATH_MISSING"
        elif protected_or_current_blocker:
            final_status = "FAIL_V21_209_PROTECTED_OR_CURRENT_CHAIN_BLOCKER"
            final_decision = "DELETE_ORIGINALS_BLOCKED_PROTECTED_OR_CURRENT_CHAIN"
        elif precheck_blocked:
            final_status = "FAIL_V21_209_ZIP_INTEGRITY_FAILED"
            final_decision = "DELETE_ORIGINALS_BLOCKED_ZIP_INTEGRITY_FAILED"
        else:
            final_status = ""
            final_decision = ""
        results: list[dict[str, Any]] = []
        if not final_status:
            checks_by_stage = {row["stage_dir"]: row for row in prechecks}
            for row in selected:
                sdir = norm_rel(row["stage_dir"], root)
                source = root / sdir
                zip_path = Path(row["zip_file_path"])
                if not zip_path.is_absolute():
                    zip_path = root / zip_path
                check = checks_by_stage[sdir]
                delete_ok = False
                err_type = ""
                err_msg = ""
                status = "DELETED_ORIGINAL"
                if simulate_delete_failure_stage == stage_name(sdir):
                    delete_ok, err_type, err_msg = False, "PermissionError", "simulated access denied"
                else:
                    delete_ok, err_type, err_msg = delete_source(source)
                if not delete_ok:
                    status = "DELETE_FAILED_OR_RETAINED"
                post_hash, post_zip_ok, _post_count, _post_size, _post_status = zip_manifest(zip_path, stage_name(sdir))
                results.append({
                    "stage_dir": sdir,
                    "source_path": str(source),
                    "zip_file_path": str(zip_path),
                    "pre_delete_source_exists": True,
                    "pre_delete_zip_exists": check["zip_exists"],
                    "pre_delete_zip_test_passed": check["zip_test_passed"],
                    "pre_delete_source_file_count": check["source_file_count"],
                    "pre_delete_source_size_bytes": check["source_size_bytes"],
                    "pre_delete_source_manifest_sha256": check["source_manifest_sha256"],
                    "pre_delete_zip_member_count": check["zip_member_count"],
                    "pre_delete_zip_uncompressed_size_bytes": check["zip_uncompressed_size_bytes"],
                    "pre_delete_zip_manifest_sha256": check["zip_manifest_sha256"],
                    "deletion_attempted": True,
                    "deletion_status": status,
                    "deleted_size_bytes": int(check["source_size_bytes"]) if delete_ok else 0,
                    "delete_error_type": err_type,
                    "delete_error_message": err_msg,
                    "post_delete_source_exists": source.exists(),
                    "post_delete_zip_exists": zip_path.exists(),
                    "post_delete_zip_test_passed": post_zip_ok,
                    "post_delete_zip_manifest_sha256": post_hash,
                    "zip_archives_deleted": False,
                })
                if not delete_ok:
                    blocker_rows.append({"stage_dir": sdir, "blocker_type": err_type or "DELETE_FAILED", "blocker_detail": err_msg})
        post_rows = [{
            "stage_dir": row["stage_dir"],
            "source_path": row["source_path"],
            "source_exists_after": row["post_delete_source_exists"],
            "zip_file_path": row["zip_file_path"],
            "zip_exists_after": row["post_delete_zip_exists"],
            "zip_test_passed_after": row["post_delete_zip_test_passed"],
        } for row in results]
        presence_after = protected_presence(root)
        protected_missing_after = [row for row in presence_after if not str_bool(row["resolved_exists"])]
        for row in protected_missing_after:
            if not any(b["stage_dir"] == row["expected_path"] and b["blocker_type"].startswith("PROTECTED_PATH_MISSING") for b in blocker_rows):
                blocker_rows.append({"stage_dir": row["expected_path"], "blocker_type": "PROTECTED_PATH_MISSING_AFTER", "blocker_detail": row["warning_reason"]})
        all_zip_after = bool(results) and all(str_bool(row["post_delete_zip_exists"]) and str_bool(row["post_delete_zip_test_passed"]) for row in results)
        failed_deletes = [row for row in results if row["deletion_status"] != "DELETED_ORIGINAL"]
        deleted_count = sum(1 for row in results if row["deletion_status"] == "DELETED_ORIGINAL" and not str_bool(row["post_delete_source_exists"]))
        if not final_status:
            if protected_missing_after:
                final_status = "FAIL_V21_209_PROTECTED_PATH_MISSING_AFTER"
                final_decision = "DELETE_ORIGINALS_FAILED_PROTECTED_PATH_MISSING"
            elif not all_zip_after:
                final_status = "FAIL_V21_209_ZIP_INTEGRITY_FAILED"
                final_decision = "DELETE_ORIGINALS_BLOCKED_ZIP_INTEGRITY_FAILED"
            elif failed_deletes or deleted_count != len(APPROVED_STAGE_DIRS):
                final_status = "WARN_V21_209_PARTIAL_DELETE_WITH_ORIGINALS_RETAINED_OR_SKIPPED"
                final_decision = "DELETE_ORIGINALS_PARTIAL_OR_SKIPPED_ZIPS_SAFE"
            else:
                final_status = "PASS_V21_209_ORIGINALS_DELETED_AFTER_ZIP_VERIFICATION"
                final_decision = "DELETE_ORIGINALS_COMPLETED_ZIPS_VERIFIED"
        deletion_performed = deleted_count > 0
        summary = {
            "stage": STAGE,
            "approved_candidate_count": len(selected),
            "deletion_attempt_count": len(results),
            "deleted_count": deleted_count,
            "deleted_size_bytes": sum(int(row["deleted_size_bytes"]) for row in results),
            "failed_delete_count": len(failed_deletes),
            "skipped_count": max(0, len(selected) - len(results)) + len(failed_deletes),
            "zip_integrity_pass_count": sum(1 for row in results if str_bool(row["post_delete_zip_test_passed"])),
            "protected_path_missing_count": len(protected_missing_after) or len(protected_missing_before),
            "all_zip_integrity_passed_after": all_zip_after,
            "all_protected_paths_present_after": not protected_missing_after,
            "final_status": final_status,
            "final_decision": final_decision,
            **policy_flags(True, deletion_performed),
        }
        write_csv(output / "deletion_execution_result.csv", results, RESULT_FIELDS)
        write_csv(output / "pre_delete_zip_integrity_recheck.csv", prechecks, ZIP_FIELDS)
        write_csv(output / "pre_delete_source_manifest.csv", manifest_rows, MANIFEST_FIELDS)
        write_csv(output / "post_delete_presence_check.csv", post_rows, POST_FIELDS)
        write_csv(output / "protected_path_presence_check.csv", presence_after, PRESENCE_FIELDS)
        write_csv(output / "deletion_blocker_check.csv", blocker_rows, BLOCKER_FIELDS)
        write_json(output / "v21_209_summary.json", summary)
        write_report(output / "V21.209_delete_originals_after_zip_verification_report.txt", summary, results)
    except Exception as exc:
        summary = {
            "stage": STAGE,
            "final_status": "FAIL_V21_209_DELETE_EXCEPTION",
            "final_decision": "DELETE_ORIGINALS_FAILED",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            **policy_flags(approved, False),
        }
        write_empty_artifacts(output)
        write_json(output / "v21_209_summary.json", summary)
        (output / "V21.209_delete_originals_after_zip_verification_report.txt").write_text(
            "\n".join([STAGE, f"final_status={summary['final_status']}", f"final_decision={summary['final_decision']}", f"error={summary['error_type']}: {summary['error_message']}"]) + "\n",
            encoding="utf-8",
        )
    for key in ["final_status", "final_decision", "approved_candidate_count", "deletion_attempt_count", "deleted_count", "deleted_size_bytes", "failed_delete_count", "deletion_performed", "broker_action_allowed"]:
        if key in summary:
            print(f"{key}={summary[key]}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", default=str(DEFAULT_ROOT))
    parser.add_argument("--approval-phrase", default="")
    parser.add_argument("--v208-plan", default="")
    parser.add_argument("--v207-integrity", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(
        Path(args.repo_root),
        approval_phrase=args.approval_phrase,
        v208_plan=Path(args.v208_plan) if args.v208_plan else None,
        v207_integrity=Path(args.v207_integrity) if args.v207_integrity else None,
    )
    return 0 if str(summary["final_status"]).startswith(("PASS", "WARN")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
