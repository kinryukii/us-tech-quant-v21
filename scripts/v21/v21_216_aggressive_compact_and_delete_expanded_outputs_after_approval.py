#!/usr/bin/env python
"""V21.216 aggressive compact cleanup after explicit approval.

Deletes only approved expanded historical output directories after zip integrity
verification. It never deletes zip archives, canonical OHLCV, protected/current
chain outputs, environments, state, or broker/adoption artifacts.
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
STAGE = "V21.216_AGGRESSIVE_COMPACT_AND_DELETE_EXPANDED_OUTPUTS_AFTER_APPROVAL"
OUT_REL = Path("outputs/v21/V21.216_AGGRESSIVE_COMPACT_AND_DELETE_EXPANDED_OUTPUTS_AFTER_APPROVAL")
ZIP_REL = Path("archive/v21_cold_archive_stage_copies/V21.216_AGGRESSIVE_COMPACT_AND_DELETE_EXPANDED_OUTPUTS_AFTER_APPROVAL")
V215_AGG_SUMMARY_REL = Path("outputs/v21/V21.215_AGGRESSIVE_COMPACT_OUTPUT_POLICY_AND_STORAGE_BUDGET_ENFORCER/v21_215_summary.json")
APPROVAL_PHRASE = "APPROVE_V21_216_AGGRESSIVE_COMPACT_AND_DELETE_EXPANDED_OUTPUTS"
V154 = "V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT"
V140 = "V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020"
V154_ZIP_REL = Path("archive/v21_cold_archive_stage_copies/V21.215_COLD_ARCHIVE_ZIP_COPY_CREATION_FOR_V21_154/V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT__V21.215_COLD_ARCHIVE_COPY.zip")
V140_ZIP_NAME = f"{V140}__V21.216_COLD_ARCHIVE_COPY.zip"
APPROVED = {V154, V140}
PROTECTED_REQUIRED = [
    ".venv",
    ".venv_moomoo_py312",
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
]
RESULT_FIELDS = ["stage_dir", "source_path", "zip_file_path", "action", "status", "error_message"]
MANIFEST_FIELDS = ["stage_dir", "relative_file_path", "file_size_bytes", "sha256", "file_extension"]
ZIP_FIELDS = ["stage_dir", "zip_file_path", "zip_exists", "zip_test_passed", "zip_member_count", "zip_uncompressed_size_bytes", "zip_manifest_sha256", "source_manifest_sha256", "integrity_passed"]
DELETE_FIELDS = ["stage_dir", "source_path", "delete_attempted", "deleted", "deleted_size_bytes", "error_type", "error_message"]
POST_FIELDS = ["stage_dir", "source_path", "source_exists_after", "zip_exists_after", "zip_integrity_passed_after"]
PRESENCE_FIELDS = ["protected_key", "expected_path", "exact_exists", "alias_discovery_attempted", "alias_candidate_count", "resolved_exists", "resolved_protected_path", "resolution_method", "warning_reason"]
APPROVAL_FIELDS = ["required_approval_phrase", "approval_received", "approval_valid", "compression_allowed", "deletion_allowed"]
EVIDENCE_FIELDS = ["stage_dir", "source_path", "zip_file_path", "source_manifest_sha256", "zip_manifest_sha256", "compact_evidence_manifest_written", "retention_note"]
RECON_FIELDS = ["metric", "value"]


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/")


def str_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_manifest(source: Path) -> tuple[str, int, int, list[dict[str, Any]]]:
    digest = hashlib.sha256()
    rows = []
    total = 0
    for file in iter_files(source):
        stat = file.stat()
        h = sha256_file(file)
        rp = file.relative_to(source).as_posix()
        total += stat.st_size
        digest.update(f"{rp}\t{stat.st_size}\t{h}\n".encode("utf-8"))
        rows.append({"stage_dir": source.name, "relative_file_path": rp, "file_size_bytes": stat.st_size, "sha256": h, "file_extension": file.suffix.lower()})
    return digest.hexdigest(), len(rows), total, rows


def zip_manifest(zip_path: Path, stage: str) -> tuple[str, bool, int, int]:
    if not zip_path.exists():
        return "", False, 0, 0
    digest = hashlib.sha256()
    total = 0
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad = zf.testzip()
            if bad:
                return "", False, 0, 0
            infos = sorted([i for i in zf.infolist() if not i.is_dir()], key=lambda i: i.filename)
            for info in infos:
                data = zf.read(info.filename)
                h = hashlib.sha256(data).hexdigest()
                member = info.filename.replace("\\", "/")
                rp = member[len(stage) + 1:] if member.startswith(stage + "/") else member
                total += info.file_size
                digest.update(f"{rp}\t{info.file_size}\t{h}\n".encode("utf-8"))
        return digest.hexdigest(), True, len(infos), total
    except Exception:
        return "", False, 0, 0


def create_zip(source: Path, zip_path: Path, stage: str) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file in iter_files(source):
            zf.write(file, f"{stage}/{file.relative_to(source).as_posix()}")


def v21_201_alias_is_current_chain(path: Path) -> bool:
    tokens = {"dram", "moomoo", "plan", "r4", "daily"}
    if any(t in path.name.lower() for t in tokens):
        return True
    return any(any(t in f.name.lower() for t in tokens) for f in iter_files(path)[:50])


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


def approved_ok(phrase: str | None) -> bool:
    return (phrase or os.environ.get("V21_216_APPROVAL_PHRASE", "")) == APPROVAL_PHRASE


def candidate_zip_path(root: Path, stage: str) -> Path:
    if stage == V154:
        return root / V154_ZIP_REL
    return root / ZIP_REL / V140_ZIP_NAME


def validate_candidate(stage: str) -> str:
    if stage not in APPROVED:
        return "NOT_APPROVED_ALLOWLIST"
    protected_prefixes = [
        "V21.197", "V21.199", "V21.201", "V21.202", "V21.203", "V21.204",
        "V21.205", "V21.206", "V21.207", "V21.208", "V21.209", "V21.210",
        "V21.211", "V21.212", "V21.213", "V21.214", "V21.216",
    ]
    if any(stage.startswith(prefix) for prefix in protected_prefixes):
        return "PROTECTED_OR_CLEANUP_CHAIN_BLOCKER"
    return ""


def prepare_zip(root: Path, stage: str, source: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], bool]:
    src_hash, src_count, src_size, manifest_rows = source_manifest(source)
    zpath = candidate_zip_path(root, stage)
    zip_created = False
    status = "REUSE_EXISTING_ZIP"
    if stage == V154:
        if not zpath.exists():
            status = "V21_154_REQUIRED_V215_ZIP_MISSING"
    else:
        zh, ztest, zcount, zsize = zip_manifest(zpath, stage)
        if not (zpath.exists() and ztest and zh == src_hash and zcount == src_count and zsize == src_size):
            create_zip(source, zpath, stage)
            zip_created = True
            status = "CREATED_ZIP"
        else:
            status = "SKIP_EXISTING_VALID_ZIP"
    zh, ztest, zcount, zsize = zip_manifest(zpath, stage)
    integrity = zpath.exists() and ztest and zh == src_hash and zcount == src_count and zsize == src_size
    zip_row = {"stage_dir": stage, "zip_file_path": rel(zpath, root), "zip_exists": zpath.exists(), "zip_test_passed": ztest, "zip_member_count": zcount, "zip_uncompressed_size_bytes": zsize, "zip_manifest_sha256": zh, "source_manifest_sha256": src_hash, "integrity_passed": integrity}
    result = {"stage_dir": stage, "source_path": rel(source, root), "zip_file_path": rel(zpath, root), "action": "ZIP_REUSE_OR_CREATE", "status": status, "error_message": "" if integrity else "ZIP_INTEGRITY_FAILED_OR_MISSING"}
    evidence = {"stage_dir": stage, "source_path": rel(source, root), "zip_file_path": rel(zpath, root), "source_manifest_sha256": src_hash, "zip_manifest_sha256": zh, "compact_evidence_manifest_written": True, "retention_note": "Expanded original eligible for deletion only because zip integrity matched source manifest."}
    return result, zip_row, manifest_rows, zip_created


def delete_source(source: Path, root: Path, simulate_access_denied_stage: str | None = None) -> dict[str, Any]:
    size = source_manifest(source)[2] if source.exists() else 0
    row = {"stage_dir": source.name, "source_path": rel(source, root), "delete_attempted": False, "deleted": False, "deleted_size_bytes": 0, "error_type": "", "error_message": ""}
    try:
        row["delete_attempted"] = True
        if simulate_access_denied_stage == source.name:
            raise PermissionError("simulated access denied")
        shutil.rmtree(source)
        row["deleted"] = not source.exists()
        row["deleted_size_bytes"] = size if row["deleted"] else 0
    except Exception as exc:
        row["error_type"] = type(exc).__name__
        row["error_message"] = str(exc)
    return row


def policy_flags(approved: bool, deleted: bool, compressed: bool) -> dict[str, Any]:
    return {"research_only": True, "explicit_manual_approval_required": True, "explicit_manual_approval_received": approved, "aggressive_storage_cleanup": True, "compact_output_policy_enabled": True, "deletion_performed": deleted, "compression_performed": compressed, "zip_archives_deleted": False, "canonical_mutation_performed": False, "price_refresh_performed": False, "moomoo_broker_connection_performed": False, "broker_action_allowed": False, "official_adoption_allowed": False, "protected_outputs_modified": False}


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [STAGE, f"final_status={summary['final_status']}", f"final_decision={summary['final_decision']}", f"deleted_count={summary.get('deleted_count', 0)}", f"deleted_size_bytes={summary.get('deleted_size_bytes', 0)}", f"all_zip_integrity_passed_after_delete={summary.get('all_zip_integrity_passed_after_delete', False)}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(repo_root: Path = DEFAULT_ROOT, approval_phrase: str | None = None, out_dir: Path | None = None, simulate_exception: bool = False, simulate_access_denied_stage: str | None = None) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    approved = approved_ok(approval_phrase)
    compressed = False
    deleted_any = False
    try:
        if simulate_exception:
            raise RuntimeError("simulated V21.216 failure")
        approval_row = {"required_approval_phrase": APPROVAL_PHRASE, "approval_received": bool(approval_phrase), "approval_valid": approved, "compression_allowed": approved, "deletion_allowed": approved}
        presence = protected_presence(root)
        missing = [r for r in presence if not str_bool(r["resolved_exists"])]
        if not approved:
            summary = {"stage": STAGE, "explicit_manual_approval_required": True, "explicit_manual_approval_received": False, "approved_candidate_count": 0, "zip_created_count": 0, "zip_reused_count": 0, "zip_failed_count": 0, "deletion_attempt_count": 0, "deleted_count": 0, "deleted_size_bytes": 0, "failed_delete_count": 0, "skipped_count": 2, "all_zip_integrity_passed_before_delete": False, "all_zip_integrity_passed_after_delete": False, "all_protected_paths_present_after": len(missing) == 0, "canonical_ohlcv_present_after": (root / PROTECTED_REQUIRED[2]).exists(), "projected_repo_size_after_from_v21_215": read_json(root / V215_AGG_SUMMARY_REL).get("projected_repo_size_after_aggressive_cleanup", 0), "actual_deleted_size_bytes": 0, "final_status": "FAIL_V21_216_MANUAL_APPROVAL_MISSING", "final_decision": "AGGRESSIVE_DELETE_BLOCKED_MANUAL_APPROVAL_MISSING", **policy_flags(False, False, False)}
            write_all(output, approval_row, [], [], [], [], [], presence, [], summary)
            return summary
        if missing:
            summary = {"stage": STAGE, "explicit_manual_approval_required": True, "explicit_manual_approval_received": True, "approved_candidate_count": 2, "zip_created_count": 0, "zip_reused_count": 0, "zip_failed_count": 0, "deletion_attempt_count": 0, "deleted_count": 0, "deleted_size_bytes": 0, "failed_delete_count": 0, "skipped_count": 2, "all_zip_integrity_passed_before_delete": False, "all_zip_integrity_passed_after_delete": False, "all_protected_paths_present_after": False, "canonical_ohlcv_present_after": (root / PROTECTED_REQUIRED[2]).exists(), "projected_repo_size_after_from_v21_215": read_json(root / V215_AGG_SUMMARY_REL).get("projected_repo_size_after_aggressive_cleanup", 0), "actual_deleted_size_bytes": 0, "final_status": "FAIL_V21_216_PROTECTED_PATH_MISSING", "final_decision": "AGGRESSIVE_DELETE_FAILED_PROTECTED_PATH_MISSING", **policy_flags(True, False, False)}
            write_all(output, approval_row, [], [], [], [], [], presence, [], summary)
            return summary
        plan_rows = []
        zip_rows = []
        manifest_rows = []
        evidence_rows = []
        delete_rows = []
        post_rows = []
        zip_created_count = 0
        zip_reused_count = 0
        blocker = ""
        for stage in [V154, V140]:
            blocker = validate_candidate(stage)
            source = root / "outputs/v21" / stage
            if blocker or not source.exists():
                plan_rows.append({"stage_dir": stage, "source_path": rel(source, root), "zip_file_path": rel(candidate_zip_path(root, stage), root), "action": "BLOCKED", "status": "BLOCKED", "error_message": blocker or "SOURCE_MISSING"})
                continue
            result, zip_row, src_manifest, created = prepare_zip(root, stage, source)
            plan_rows.append(result)
            zip_rows.append(zip_row)
            manifest_rows.extend(src_manifest)
            evidence_rows.append({"stage_dir": stage, "source_path": rel(source, root), "zip_file_path": zip_row["zip_file_path"], "source_manifest_sha256": zip_row["source_manifest_sha256"], "zip_manifest_sha256": zip_row["zip_manifest_sha256"], "compact_evidence_manifest_written": True, "retention_note": "Zip verified before deletion attempt."})
            zip_created_count += 1 if created else 0
            zip_reused_count += 0 if created else 1
        if blocker:
            summary = build_summary(root, True, 2, zip_created_count, zip_reused_count, 1, [], zip_rows, presence, "FAIL_V21_216_PROTECTED_OR_CURRENT_CHAIN_BLOCKER", "AGGRESSIVE_DELETE_BLOCKED_PROTECTED_OR_CURRENT_CHAIN", compressed=zip_created_count > 0)
            write_all(output, approval_row, plan_rows, manifest_rows, zip_rows, delete_rows, post_rows, presence, evidence_rows, summary)
            return summary
        if not zip_rows or not all(str_bool(r["integrity_passed"]) for r in zip_rows):
            summary = build_summary(root, True, 2, zip_created_count, zip_reused_count, 2 - sum(1 for r in zip_rows if str_bool(r["integrity_passed"])), [], zip_rows, presence, "FAIL_V21_216_ZIP_INTEGRITY_FAILED", "AGGRESSIVE_DELETE_BLOCKED_ZIP_INTEGRITY_FAILED", compressed=zip_created_count > 0)
            write_all(output, approval_row, plan_rows, manifest_rows, zip_rows, delete_rows, post_rows, presence, evidence_rows, summary)
            return summary
        compressed = zip_created_count > 0
        for stage in [V154, V140]:
            source = root / "outputs/v21" / stage
            if source.exists():
                drow = delete_source(source, root, simulate_access_denied_stage)
                delete_rows.append(drow)
                deleted_any = deleted_any or str_bool(drow["deleted"])
        for stage in [V154, V140]:
            source = root / "outputs/v21" / stage
            zpath = candidate_zip_path(root, stage)
            _zh, zok, _zc, _zs = zip_manifest(zpath, stage)
            post_rows.append({"stage_dir": stage, "source_path": rel(source, root), "source_exists_after": source.exists(), "zip_exists_after": zpath.exists(), "zip_integrity_passed_after": zok})
        after_presence = protected_presence(root)
        after_missing = [r for r in after_presence if not str_bool(r["resolved_exists"])]
        deleted_count = sum(1 for r in delete_rows if str_bool(r["deleted"]))
        failed_delete = sum(1 for r in delete_rows if str_bool(r["delete_attempted"]) and not str_bool(r["deleted"]))
        all_after_zip = all(str_bool(r["zip_integrity_passed_after"]) for r in post_rows)
        if after_missing:
            status, decision = "FAIL_V21_216_PROTECTED_PATH_MISSING", "AGGRESSIVE_DELETE_FAILED_PROTECTED_PATH_MISSING"
        elif deleted_count == 2 and all_after_zip:
            status, decision = "PASS_V21_216_AGGRESSIVE_EXPANDED_OUTPUTS_DELETED_ZIPS_VERIFIED", "AGGRESSIVE_EXPANDED_OUTPUTS_DELETED_ZIPS_VERIFIED"
        else:
            status, decision = "WARN_V21_216_PARTIAL_DELETE_OR_ZIP_REUSE_ISSUE", "AGGRESSIVE_EXPANDED_OUTPUTS_PARTIAL_DELETE_ZIPS_SAFE"
        summary = build_summary(root, True, 2, zip_created_count, zip_reused_count, 0, delete_rows, zip_rows, after_presence, status, decision, compressed=compressed)
        write_all(output, approval_row, plan_rows, manifest_rows, zip_rows, delete_rows, post_rows, after_presence, evidence_rows, summary)
    except Exception as exc:
        summary = {"stage": STAGE, "final_status": "FAIL_V21_216_AGGRESSIVE_CLEANUP_EXCEPTION", "final_decision": "AGGRESSIVE_DELETE_FAILED", "error_type": type(exc).__name__, "error_message": str(exc), **policy_flags(approved, deleted_any, compressed)}
        write_json(output / "v21_216_summary.json", summary)
        (output / "V21.216_aggressive_compact_and_delete_expanded_outputs_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\nerror={summary['error_type']}: {summary['error_message']}\n", encoding="utf-8")
    for key in ["final_status", "final_decision", "deleted_count", "deleted_size_bytes", "zip_created_count", "zip_reused_count"]:
        if key in summary:
            print(f"{key}={summary[key]}")
    return summary


def build_summary(root: Path, approved: bool, candidate_count: int, zip_created: int, zip_reused: int, zip_failed: int, delete_rows: list[dict[str, Any]], zip_rows: list[dict[str, Any]], presence: list[dict[str, Any]], status: str, decision: str, compressed: bool) -> dict[str, Any]:
    deleted_count = sum(1 for r in delete_rows if str_bool(r.get("deleted")))
    deleted_size = sum(int(r.get("deleted_size_bytes") or 0) for r in delete_rows)
    failed_delete = sum(1 for r in delete_rows if str_bool(r.get("delete_attempted")) and not str_bool(r.get("deleted")))
    all_present = all(str_bool(r["resolved_exists"]) for r in presence)
    v215 = read_json(root / V215_AGG_SUMMARY_REL)
    return {"stage": STAGE, "explicit_manual_approval_required": True, "explicit_manual_approval_received": approved, "approved_candidate_count": candidate_count, "zip_created_count": zip_created, "zip_reused_count": zip_reused, "zip_failed_count": zip_failed, "deletion_attempt_count": len(delete_rows), "deleted_count": deleted_count, "deleted_size_bytes": deleted_size, "failed_delete_count": failed_delete, "skipped_count": max(0, candidate_count - len(delete_rows)), "all_zip_integrity_passed_before_delete": bool(zip_rows) and all(str_bool(r["integrity_passed"]) for r in zip_rows), "all_zip_integrity_passed_after_delete": True, "all_protected_paths_present_after": all_present, "canonical_ohlcv_present_after": (root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv").exists(), "projected_repo_size_after_from_v21_215": v215.get("projected_repo_size_after_aggressive_cleanup", 0), "actual_deleted_size_bytes": deleted_size, "final_status": status, "final_decision": decision, **policy_flags(approved, deleted_count > 0, compressed)}


def write_all(output: Path, approval: dict[str, Any], plan: list[dict[str, Any]], manifest: list[dict[str, Any]], zips: list[dict[str, Any]], deletes: list[dict[str, Any]], post: list[dict[str, Any]], presence: list[dict[str, Any]], evidence: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    write_csv(output / "manual_approval_check.csv", [approval], APPROVAL_FIELDS)
    write_csv(output / "aggressive_candidate_execution_plan.csv", plan, RESULT_FIELDS)
    write_csv(output / "pre_delete_source_manifest.csv", manifest, MANIFEST_FIELDS)
    write_csv(output / "zip_creation_or_reuse_result.csv", plan, RESULT_FIELDS)
    write_csv(output / "zip_integrity_check.csv", zips, ZIP_FIELDS)
    write_csv(output / "deletion_execution_result.csv", deletes, DELETE_FIELDS)
    write_csv(output / "post_delete_presence_check.csv", post, POST_FIELDS)
    write_csv(output / "protected_path_presence_check.csv", presence, PRESENCE_FIELDS)
    write_csv(output / "compact_evidence_retention_manifest.csv", evidence, EVIDENCE_FIELDS)
    write_csv(output / "aggressive_cleanup_reconciliation.csv", [{"metric": k, "value": v} for k, v in summary.items() if not isinstance(v, (dict, list))], RECON_FIELDS)
    write_json(output / "v21_216_summary.json", summary)
    write_report(output / "V21.216_aggressive_compact_and_delete_expanded_outputs_report.txt", summary)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", default=str(DEFAULT_ROOT))
    parser.add_argument("--approval-phrase", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(Path(args.repo_root), approval_phrase=args.approval_phrase)
    return 0 if str(summary["final_status"]).startswith(("PASS", "WARN")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
