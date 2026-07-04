#!/usr/bin/env python
"""V21.210 post-cleanup size and integrity reconciliation.

Audit-only reconciliation after V21.209. This stage does not delete, move,
compress, rewrite, refresh prices, mutate canonical files, or perform broker or
adoption actions.
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
STAGE = "V21.210_POST_CLEANUP_SIZE_AND_INTEGRITY_RECONCILIATION"
OUT_REL = Path("outputs/v21/V21.210_POST_CLEANUP_SIZE_AND_INTEGRITY_RECONCILIATION")
V209_OUT_REL = Path("outputs/v21/V21.209_DELETE_ORIGINALS_AFTER_ZIP_VERIFICATION")
V209_PASS = "PASS_V21_209_ORIGINALS_DELETED_AFTER_ZIP_VERIFICATION"
DELETED_ORIGINALS = [
    "outputs/v21/V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST",
    "outputs/v21/V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST",
    "outputs/v21/V21.148_E_R1_A1_PIT_LITE_REPLAY_DIAGNOSTIC_ONLY",
]
PROTECTED_REQUIRED = [
    ".venv",
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
    "outputs/v21/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION",
    "outputs/v21/V21.208_ORIGINAL_REMOVAL_DRY_RUN_APPROVAL_GATE",
    "outputs/v21/V21.209_DELETE_ORIGINALS_AFTER_ZIP_VERIFICATION",
]
SIZE_FIELDS = ["path", "size_bytes", "file_count", "directory_count"]
ORIGINAL_FIELDS = ["stage_dir", "expected_absent", "exists_after_cleanup", "presence_status"]
ZIP_FIELDS = [
    "stage_dir",
    "zip_file_path",
    "zip_exists",
    "zip_test_passed",
    "zip_member_count",
    "zip_uncompressed_size_bytes",
    "zip_manifest_sha256",
    "expected_manifest_sha256",
    "expected_uncompressed_size_bytes",
    "integrity_recheck_passed",
    "blocker_reason",
]
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
CHAIN_FIELDS = ["check_name", "expected_value", "observed_value", "check_passed", "reconciliation_note"]


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


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def iter_files(path: Path) -> list[Path]:
    try:
        return sorted([p for p in path.rglob("*") if p.is_file()], key=lambda p: p.as_posix())
    except OSError:
        return []


def tree_metrics(path: Path) -> tuple[int, int, int]:
    total = 0
    files = 0
    dirs = 0
    if not path.exists():
        return 0, 0, 0
    try:
        for child in path.rglob("*"):
            if child.is_file():
                files += 1
                total += child.stat().st_size
            elif child.is_dir():
                dirs += 1
    except OSError:
        pass
    return total, files, dirs


def repo_size_summary(root: Path) -> list[dict[str, Any]]:
    total, files, dirs = tree_metrics(root)
    rows = [{"path": ".", "size_bytes": total, "file_count": files, "directory_count": dirs}]
    for item in [".venv", "outputs", "outputs/v21", "archive", "scripts", "scripts/v21", "data"]:
        size, count, dcount = tree_metrics(root / item)
        rows.append({"path": item, "size_bytes": size, "file_count": count, "directory_count": dcount})
    return rows


def zip_manifest(zip_path: Path, stage_name: str) -> tuple[str, bool, int, int, str]:
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
                rel_member = member[len(stage_name) + 1:] if member.startswith(stage_name + "/") else member
                data_hash = hashlib.sha256(zf.read(info.filename)).hexdigest()
                digest.update(f"{rel_member}\t{info.file_size}\t{data_hash}\n".encode("utf-8"))
                count += 1
                total += info.file_size
        return digest.hexdigest(), True, count, total, "ZIP_TEST_PASSED"
    except Exception as exc:
        return "", False, 0, 0, f"ZIP_EXCEPTION:{type(exc).__name__}:{exc}"


def deleted_original_presence(root: Path) -> list[dict[str, Any]]:
    rows = []
    for item in DELETED_ORIGINALS:
        exists = (root / item).exists()
        rows.append({
            "stage_dir": item,
            "expected_absent": True,
            "exists_after_cleanup": exists,
            "presence_status": "UNEXPECTED_STILL_PRESENT" if exists else "ABSENT_AS_EXPECTED",
        })
    return rows


def zip_recheck(root: Path, deletion_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows = []
    by_stage = {row.get("stage_dir", ""): row for row in deletion_rows}
    for item in DELETED_ORIGINALS:
        prior = by_stage.get(item, {})
        zip_path = Path(prior.get("zip_file_path", ""))
        if not zip_path:
            zip_path = root / "archive/v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION" / f"{Path(item).name}__V21.207_COMPRESS_ONLY_COPY.zip"
        elif not zip_path.is_absolute():
            zip_path = root / zip_path
        zhash, zpass, zcount, zsize, zstatus = zip_manifest(zip_path, Path(item).name)
        expected_hash = prior.get("pre_delete_source_manifest_sha256", "")
        expected_size = prior.get("pre_delete_source_size_bytes", "")
        integrity = bool(zip_path.exists() and zpass and zhash == expected_hash and str(zsize) == str(expected_size))
        blockers = []
        if not zip_path.exists():
            blockers.append("ZIP_MISSING")
        if not zpass:
            blockers.append(zstatus)
        if expected_hash and zhash != expected_hash:
            blockers.append("ZIP_MANIFEST_HASH_MISMATCH")
        if expected_size and str(zsize) != str(expected_size):
            blockers.append("ZIP_UNCOMPRESSED_SIZE_MISMATCH")
        rows.append({
            "stage_dir": item,
            "zip_file_path": str(zip_path),
            "zip_exists": zip_path.exists(),
            "zip_test_passed": zpass,
            "zip_member_count": zcount,
            "zip_uncompressed_size_bytes": zsize,
            "zip_manifest_sha256": zhash,
            "expected_manifest_sha256": expected_hash,
            "expected_uncompressed_size_bytes": expected_size,
            "integrity_recheck_passed": integrity,
            "blocker_reason": "|".join(blockers),
        })
    return rows


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
    rows = []
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
            stage_id = Path(item).name.split("_", 1)[0]
            candidates = protected_alias_candidates(root, stage_id)
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


def chain_reconciliation(v209_summary: dict[str, Any], original_rows: list[dict[str, Any]], zip_rows: list[dict[str, Any]], protected_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"check_name": "v21_209_final_status", "expected_value": V209_PASS, "observed_value": v209_summary.get("final_status", ""), "check_passed": v209_summary.get("final_status") == V209_PASS, "reconciliation_note": ""},
        {"check_name": "deleted_originals_absent", "expected_value": "3", "observed_value": sum(1 for row in original_rows if not str_bool(row["exists_after_cleanup"])), "check_passed": all(not str_bool(row["exists_after_cleanup"]) for row in original_rows), "reconciliation_note": ""},
        {"check_name": "zip_archives_integrity", "expected_value": "3", "observed_value": sum(1 for row in zip_rows if str_bool(row["integrity_recheck_passed"])), "check_passed": all(str_bool(row["integrity_recheck_passed"]) for row in zip_rows), "reconciliation_note": ""},
        {"check_name": "protected_paths_present", "expected_value": str(len(protected_rows)), "observed_value": sum(1 for row in protected_rows if str_bool(row["resolved_exists"])), "check_passed": all(str_bool(row["resolved_exists"]) for row in protected_rows), "reconciliation_note": ""},
        {"check_name": "v21_209_deleted_size_bytes", "expected_value": "positive", "observed_value": v209_summary.get("deleted_size_bytes", 0), "check_passed": int(v209_summary.get("deleted_size_bytes", 0) or 0) > 0, "reconciliation_note": "Observed current-state absence by directory presence; exact pre/post repo total delta is not reconstructable without a pre-cleanup snapshot."},
    ]


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


def write_report(path: Path, summary: dict[str, Any], chain_rows: list[dict[str, Any]]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"reconciliation_status={summary['reconciliation_status']}",
        f"repo_total_size_bytes_after={summary['repo_total_size_bytes_after']}",
        f"deleted_original_missing_count={summary['deleted_original_missing_count']}",
        f"deleted_original_still_present_count={summary['deleted_original_still_present_count']}",
        f"zip_archive_present_count={summary['zip_archive_present_count']}",
        f"zip_integrity_pass_count={summary['zip_integrity_pass_count']}",
        f"protected_path_missing_count={summary['protected_path_missing_count']}",
        f"v21_209_deleted_size_bytes={summary['v21_209_deleted_size_bytes']}",
        "research_only=true",
        "audit_only=true",
        "mutation_allowed=false",
        "deletion_performed=false",
        "",
        "cleanup_chain_reconciliation:",
    ]
    lines.extend([f"- {row['check_name']} passed={row['check_passed']} observed={row['observed_value']}" for row in chain_rows])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(
    repo_root: Path = DEFAULT_ROOT,
    v209_summary_path: Path | None = None,
    v209_result_path: Path | None = None,
    out_dir: Path | None = None,
    simulate_exception: bool = False,
) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if simulate_exception:
            raise RuntimeError("simulated V21.210 failure")
        v209_summary = read_json(v209_summary_path or (root / V209_OUT_REL / "v21_209_summary.json"))
        v209_results = read_csv(v209_result_path or (root / V209_OUT_REL / "deletion_execution_result.csv"))
        size_rows = repo_size_summary(root)
        original_rows = deleted_original_presence(root)
        zip_rows = zip_recheck(root, v209_results)
        protected_rows = protected_presence(root)
        chain_rows = chain_reconciliation(v209_summary, original_rows, zip_rows, protected_rows)
        repo_total = size_rows[0]
        original_present = [row for row in original_rows if str_bool(row["exists_after_cleanup"])]
        zip_bad = [row for row in zip_rows if not str_bool(row["integrity_recheck_passed"])]
        zip_missing = [row for row in zip_rows if not str_bool(row["zip_exists"])]
        protected_missing = [row for row in protected_rows if not str_bool(row["resolved_exists"])]
        v209_pass = v209_summary.get("final_status") == V209_PASS
        if protected_missing or zip_bad or zip_missing:
            final_status = "FAIL_V21_210_PROTECTED_PATH_OR_ZIP_MISSING"
            final_decision = "POST_CLEANUP_RECONCILIATION_FAILED_PROTECTED_OR_ZIP_MISSING"
            reconciliation_status = "FAILED_PROTECTED_OR_ZIP_MISSING"
        elif original_present or not v209_pass:
            final_status = "WARN_V21_210_RECONCILIATION_MISMATCH"
            final_decision = "POST_CLEANUP_RECONCILIATION_WARN_MISMATCH"
            reconciliation_status = "WARN_RECONCILIATION_MISMATCH"
        else:
            final_status = "PASS_V21_210_POST_CLEANUP_RECONCILIATION_READY"
            final_decision = "POST_CLEANUP_RECONCILIATION_READY"
            reconciliation_status = "RECONCILED"
        summary = {
            "stage": STAGE,
            "repo_total_size_bytes_after": int(repo_total["size_bytes"]),
            "repo_total_file_count_after": int(repo_total["file_count"]),
            "repo_total_directory_count_after": int(repo_total["directory_count"]),
            "deleted_original_missing_count": sum(1 for row in original_rows if not str_bool(row["exists_after_cleanup"])),
            "deleted_original_still_present_count": len(original_present),
            "zip_archive_present_count": sum(1 for row in zip_rows if str_bool(row["zip_exists"])),
            "zip_integrity_pass_count": sum(1 for row in zip_rows if str_bool(row["integrity_recheck_passed"])),
            "protected_path_missing_count": len(protected_missing),
            "v21_209_deleted_size_bytes": int(v209_summary.get("deleted_size_bytes", 0) or 0),
            "reconciliation_status": reconciliation_status,
            "final_status": final_status,
            "final_decision": final_decision,
            **policy_flags(),
        }
        write_csv(output / "post_cleanup_repo_size_summary.csv", size_rows, SIZE_FIELDS)
        write_csv(output / "deleted_original_presence_check.csv", original_rows, ORIGINAL_FIELDS)
        write_csv(output / "zip_archive_integrity_recheck.csv", zip_rows, ZIP_FIELDS)
        write_csv(output / "protected_path_presence_check.csv", protected_rows, PRESENCE_FIELDS)
        write_csv(output / "cleanup_chain_reconciliation.csv", chain_rows, CHAIN_FIELDS)
        write_json(output / "v21_210_summary.json", summary)
        write_report(output / "V21.210_post_cleanup_reconciliation_report.txt", summary, chain_rows)
    except Exception as exc:
        summary = {
            "stage": STAGE,
            "final_status": "FAIL_V21_210_RECONCILIATION_EXCEPTION",
            "final_decision": "POST_CLEANUP_RECONCILIATION_FAILED",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            **policy_flags(),
        }
        write_json(output / "v21_210_summary.json", summary)
        (output / "V21.210_post_cleanup_reconciliation_report.txt").write_text(
            "\n".join([STAGE, f"final_status={summary['final_status']}", f"final_decision={summary['final_decision']}", f"error={summary['error_type']}: {summary['error_message']}"]) + "\n",
            encoding="utf-8",
        )
    for key in ["final_status", "final_decision", "reconciliation_status", "repo_total_size_bytes_after", "deleted_original_missing_count", "zip_integrity_pass_count", "protected_path_missing_count", "deletion_performed", "broker_action_allowed"]:
        if key in summary:
            print(f"{key}={summary[key]}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", default=str(DEFAULT_ROOT))
    parser.add_argument("--v209-summary", default="")
    parser.add_argument("--v209-result", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(
        Path(args.repo_root),
        v209_summary_path=Path(args.v209_summary) if args.v209_summary else None,
        v209_result_path=Path(args.v209_result) if args.v209_result else None,
    )
    return 0 if str(summary["final_status"]).startswith(("PASS", "WARN")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
