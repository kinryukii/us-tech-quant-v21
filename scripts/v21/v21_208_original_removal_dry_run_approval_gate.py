#!/usr/bin/env python
"""V21.208 original-removal dry-run approval gate.

This stage does not delete, move, compress, rewrite, or mutate source outputs.
It verifies whether the three V21.207 zip-backed original directories are
eligible for a future, separately approved deletion stage.
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
STAGE = "V21.208_ORIGINAL_REMOVAL_DRY_RUN_APPROVAL_GATE"
OUT_REL = Path("outputs/v21/V21.208_ORIGINAL_REMOVAL_DRY_RUN_APPROVAL_GATE")
V207_OUT_REL = Path("outputs/v21/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION")
APPROVAL_PHRASE = "APPROVE_V21_209_DELETE_ORIGINALS_AFTER_ZIP_VERIFICATION"
ELIGIBLE_STAGE_NAMES = {
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
    "V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION",
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
    "archive/v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION",
]
PLAN_FIELDS = [
    "stage_dir",
    "source_path",
    "zip_file_path",
    "source_exists",
    "zip_exists",
    "zip_test_passed",
    "source_file_count",
    "zip_member_count",
    "source_size_bytes",
    "zip_size_bytes",
    "source_manifest_sha256",
    "zip_manifest_sha256",
    "integrity_recheck_passed",
    "sensitive_keyword_blocker_count",
    "protected_path_overlap_flag",
    "current_chain_overlap_flag",
    "eligible_for_future_deletion",
    "deletion_allowed_in_this_run",
    "manual_approval_required",
    "required_manual_approval_phrase",
    "estimated_space_savings_if_deleted_later",
    "blocker_reasons",
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
BLOCKER_FIELDS = ["stage_dir", "blocker_type", "blocker_detail"]
CHECKLIST_FIELDS = ["stage_dir", "check_item", "required_value", "observed_value", "check_passed"]


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


def source_manifest(source: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    count = 0
    total = 0
    if not source.exists() or not source.is_dir():
        return "", 0, 0
    for file in iter_files(source):
        size = file.stat().st_size
        file_hash = sha256_file(file)
        rel_path = file.relative_to(source).as_posix()
        digest.update(f"{rel_path}\t{size}\t{file_hash}\n".encode("utf-8"))
        count += 1
        total += size
    return digest.hexdigest(), count, total


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


def sensitive_keyword_hits(source: Path, root: Path) -> list[str]:
    hits: list[str] = []
    targets = [rel(source, root)]
    targets.extend(rel(file, root) for file in iter_files(source))
    for target in targets:
        text = target.lower().replace("\\", "/")
        for token in SENSITIVE_TOKENS:
            if token in text:
                hits.append(f"{token}:{target}")
    return hits


def protected_overlap(name: str, source: Path, root: Path) -> bool:
    if name in HARD_EXCLUDE_STAGE_NAMES:
        return True
    r = rel(source, root).lower()
    return any(r == item.lower() or r.startswith(item.lower() + "/") for item in PROTECTED_REQUIRED)


def current_chain_overlap(source: Path, root: Path) -> bool:
    text = rel(source, root).lower()
    return any(token in text for token in ["current_chain", "latest", "moomoo", "dram", "abcde", "canonical", "kline", "ranking", "ledger", "trade_plan"])


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
    name = path.name.lower()
    if any(token in name for token in tokens):
        return True
    for file in iter_files(path)[:50]:
        text = file.name.lower()
        if any(token in text for token in tokens):
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


def merge_v207_rows(result_rows: list[dict[str, str]], integrity_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    integrity_by_stage = {row.get("stage_dir", ""): row for row in integrity_rows}
    merged = []
    for row in result_rows:
        item = dict(row)
        item.update({k: v for k, v in integrity_by_stage.get(row.get("stage_dir", ""), {}).items() if v != ""})
        merged.append(item)
    return merged


def candidate_precheck(row: dict[str, str]) -> str:
    name = stage_name(row.get("stage_dir", ""))
    if name in HARD_EXCLUDE_STAGE_NAMES:
        return "HARDCODED_SAFETY_EXCLUSION"
    if name not in ELIGIBLE_STAGE_NAMES:
        return "NOT_IN_ELIGIBLE_STAGE_ALLOWLIST"
    if not str_bool(row.get("zip_test_passed")):
        return "V21_207_ZIP_TEST_NOT_PASSED"
    if not str_bool(row.get("source_unchanged_after")):
        return "V21_207_SOURCE_UNCHANGED_FALSE"
    if str_bool(row.get("deletion_allowed_now")):
        return "V21_207_DELETION_ALLOWED_UNEXPECTED_TRUE"
    if not str_bool(row.get("source_still_exists_after")):
        return "V21_207_SOURCE_STILL_EXISTS_FALSE"
    return ""


def evaluate_candidate(row: dict[str, str], root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    sdir = row["stage_dir"]
    name = stage_name(sdir)
    source = root / sdir
    zip_path = Path(row.get("zip_file_path", ""))
    if not zip_path.is_absolute():
        zip_path = root / zip_path
    source_hash, source_count, source_size = source_manifest(source)
    zip_hash, zip_ok, zip_count, zip_uncompressed, zip_status = zip_manifest(zip_path, name)
    zip_size = zip_path.stat().st_size if zip_path.exists() else 0
    hits = sensitive_keyword_hits(source, root) if source.exists() else []
    protected_flag = protected_overlap(name, source, root)
    current_flag = current_chain_overlap(source, root)
    blockers: list[str] = []
    if not source.exists():
        blockers.append("SOURCE_MISSING")
    if not zip_path.exists():
        blockers.append("ZIP_MISSING")
    if not zip_ok:
        blockers.append(zip_status)
    if source_hash != zip_hash or source_count != zip_count or source_size != zip_uncompressed:
        blockers.append("SOURCE_ZIP_MANIFEST_MISMATCH")
    if hits:
        blockers.append("SENSITIVE_KEYWORD_BLOCKER")
    if protected_flag:
        blockers.append("PROTECTED_PATH_OVERLAP")
    if current_flag:
        blockers.append("CURRENT_CHAIN_OVERLAP")
    integrity_ok = bool(source.exists() and zip_path.exists() and zip_ok and source_hash == zip_hash and source_count == zip_count and source_size == zip_uncompressed)
    eligible = bool(integrity_ok and not hits and not protected_flag and not current_flag)
    plan = {
        "stage_dir": sdir,
        "source_path": str(source),
        "zip_file_path": str(zip_path),
        "source_exists": source.exists(),
        "zip_exists": zip_path.exists(),
        "zip_test_passed": zip_ok,
        "source_file_count": source_count,
        "zip_member_count": zip_count,
        "source_size_bytes": source_size,
        "zip_size_bytes": zip_size,
        "source_manifest_sha256": source_hash,
        "zip_manifest_sha256": zip_hash,
        "integrity_recheck_passed": integrity_ok,
        "sensitive_keyword_blocker_count": len(hits),
        "protected_path_overlap_flag": protected_flag,
        "current_chain_overlap_flag": current_flag,
        "eligible_for_future_deletion": eligible,
        "deletion_allowed_in_this_run": False,
        "manual_approval_required": True,
        "required_manual_approval_phrase": APPROVAL_PHRASE,
        "estimated_space_savings_if_deleted_later": max(0, source_size - zip_size) if eligible else 0,
        "blocker_reasons": "|".join(blockers),
    }
    blocker_rows = [{"stage_dir": sdir, "blocker_type": reason.split(":", 1)[0], "blocker_detail": reason} for reason in blockers]
    checklist = [
        {"stage_dir": sdir, "check_item": "zip_test_passed", "required_value": "true", "observed_value": zip_ok, "check_passed": zip_ok},
        {"stage_dir": sdir, "check_item": "source_zip_manifest_match", "required_value": "true", "observed_value": integrity_ok, "check_passed": integrity_ok},
        {"stage_dir": sdir, "check_item": "deletion_allowed_in_this_run", "required_value": "false", "observed_value": False, "check_passed": True},
        {"stage_dir": sdir, "check_item": "manual_approval_phrase", "required_value": APPROVAL_PHRASE, "observed_value": APPROVAL_PHRASE, "check_passed": True},
    ]
    return plan, blocker_rows, checklist


def write_report(path: Path, summary: dict[str, Any], plan_rows: list[dict[str, Any]]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"candidates_from_v21_207={summary['candidates_from_v21_207']}",
        f"candidates_after_hard_exclusions={summary['candidates_after_hard_exclusions']}",
        f"integrity_recheck_pass_count={summary['integrity_recheck_pass_count']}",
        f"eligible_for_future_deletion_count={summary['eligible_for_future_deletion_count']}",
        f"blocked_candidate_count={summary['blocked_candidate_count']}",
        f"estimated_total_space_savings_if_deleted_later={summary['estimated_total_space_savings_if_deleted_later']}",
        "deletion_allowed_in_this_run=false",
        f"required_manual_approval_phrase={APPROVAL_PHRASE}",
        "research_only=true",
        "dry_run=true",
        "audit_only=true",
        "mutation_allowed=false",
        "deletion_performed=false",
        "",
        "candidate_plan:",
    ]
    lines.extend([f"- {row['stage_dir']} eligible={row['eligible_for_future_deletion']} blockers={row['blocker_reasons']}" for row in plan_rows])
    lines.append("")
    lines.append("next_recommended_action=Manual review only. A separate V21.209 stage would require the exact approval phrase before any original removal.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def policy_flags() -> dict[str, bool]:
    return {
        "research_only": True,
        "dry_run": True,
        "audit_only": True,
        "mutation_allowed": False,
        "deletion_performed": False,
        "compression_performed": False,
        "archive_movement_performed": False,
        "original_directories_removed": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "protected_outputs_modified": False,
        "canonical_mutation_performed": False,
        "price_refresh_performed": False,
    }


def run(
    repo_root: Path = DEFAULT_ROOT,
    result_csv: Path | None = None,
    integrity_csv: Path | None = None,
    out_dir: Path | None = None,
    simulate_exception: bool = False,
) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if simulate_exception:
            raise RuntimeError("simulated V21.208 failure")
        result_rows = read_csv(result_csv or (root / V207_OUT_REL / "zip_copy_creation_result.csv"))
        integrity_rows = read_csv(integrity_csv or (root / V207_OUT_REL / "zip_copy_integrity_check.csv"))
        merged = merge_v207_rows(result_rows, integrity_rows)
        presence_rows = protected_presence(root)
        protected_missing = [row for row in presence_rows if not str_bool(row["resolved_exists"])]
        selected: list[dict[str, str]] = []
        precheck_blockers: list[dict[str, Any]] = []
        for row in merged:
            reason = candidate_precheck(row)
            if reason:
                if stage_name(row.get("stage_dir", "")) in HARD_EXCLUDE_STAGE_NAMES or "PROTECTED" in reason:
                    precheck_blockers.append({"stage_dir": row.get("stage_dir", ""), "blocker_type": reason, "blocker_detail": reason})
                continue
            selected.append(row)
        plan_rows: list[dict[str, Any]] = []
        blocker_rows: list[dict[str, Any]] = list(precheck_blockers)
        checklist_rows: list[dict[str, Any]] = []
        for row in selected:
            plan, blockers, checklist = evaluate_candidate(row, root)
            plan_rows.append(plan)
            blocker_rows.extend(blockers)
            checklist_rows.extend(checklist)
        for row in protected_missing:
            blocker_rows.append({"stage_dir": row["expected_path"], "blocker_type": "PROTECTED_PATH_MISSING", "blocker_detail": row["warning_reason"]})
        protected_or_current = any(
            row.get("protected_path_overlap_flag") or row.get("current_chain_overlap_flag") or row.get("sensitive_keyword_blocker_count", 0)
            for row in plan_rows
        ) or bool(protected_missing or precheck_blockers)
        integrity_fail = any(not str_bool(row["integrity_recheck_passed"]) for row in plan_rows)
        eligible_count = sum(1 for row in plan_rows if str_bool(row["eligible_for_future_deletion"]))
        if protected_or_current:
            final_status = "FAIL_V21_208_PROTECTED_OR_CURRENT_CHAIN_BLOCKER"
            final_decision = "ORIGINAL_REMOVAL_DRY_RUN_BLOCKED_PROTECTED_OR_CURRENT_CHAIN"
        elif integrity_fail:
            final_status = "FAIL_V21_208_INTEGRITY_RECHECK_FAILED"
            final_decision = "ORIGINAL_REMOVAL_DRY_RUN_BLOCKED_INTEGRITY_FAILURE"
        elif eligible_count == 0:
            final_status = "WARN_V21_208_NO_ELIGIBLE_ORIGINALS_FOR_FUTURE_DELETION"
            final_decision = "ORIGINAL_REMOVAL_DRY_RUN_NO_ELIGIBLE_ORIGINALS"
        else:
            final_status = "PASS_V21_208_ORIGINAL_REMOVAL_DRY_RUN_READY"
            final_decision = "ORIGINAL_REMOVAL_DRY_RUN_READY_MANUAL_APPROVAL_REQUIRED"
        summary = {
            "stage": STAGE,
            "candidates_from_v21_207": len(merged),
            "candidates_after_hard_exclusions": len(selected),
            "integrity_recheck_pass_count": sum(1 for row in plan_rows if str_bool(row["integrity_recheck_passed"])),
            "eligible_for_future_deletion_count": eligible_count,
            "blocked_candidate_count": sum(1 for row in plan_rows if not str_bool(row["eligible_for_future_deletion"])) + len(protected_missing) + len(precheck_blockers),
            "estimated_total_space_savings_if_deleted_later": sum(int(row["estimated_space_savings_if_deleted_later"]) for row in plan_rows),
            "deletion_allowed_in_this_run": False,
            "required_manual_approval_phrase": APPROVAL_PHRASE,
            "final_status": final_status,
            "final_decision": final_decision,
            **policy_flags(),
        }
        write_csv(output / "original_removal_dry_run_approval_plan.csv", plan_rows, PLAN_FIELDS)
        write_csv(output / "zip_vs_source_integrity_recheck.csv", plan_rows, PLAN_FIELDS)
        write_csv(output / "source_deletion_blocker_check.csv", blocker_rows, BLOCKER_FIELDS)
        write_csv(output / "protected_path_presence_check.csv", presence_rows, PRESENCE_FIELDS)
        write_csv(output / "manual_approval_checklist.csv", checklist_rows, CHECKLIST_FIELDS)
        write_json(output / "v21_208_summary.json", summary)
        write_report(output / "V21.208_original_removal_dry_run_approval_gate_report.txt", summary, plan_rows)
    except Exception as exc:
        summary = {
            "stage": STAGE,
            "final_status": "FAIL_V21_208_DRY_RUN_EXCEPTION",
            "final_decision": "ORIGINAL_REMOVAL_DRY_RUN_FAILED",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            **policy_flags(),
        }
        write_json(output / "v21_208_summary.json", summary)
        (output / "V21.208_original_removal_dry_run_approval_gate_report.txt").write_text(
            "\n".join([STAGE, f"final_status={summary['final_status']}", f"final_decision={summary['final_decision']}", f"error={summary['error_type']}: {summary['error_message']}"]) + "\n",
            encoding="utf-8",
        )
    for key in ["final_status", "final_decision", "candidates_from_v21_207", "candidates_after_hard_exclusions", "eligible_for_future_deletion_count", "deletion_performed", "broker_action_allowed"]:
        if key in summary:
            print(f"{key}={summary[key]}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", default=str(DEFAULT_ROOT))
    parser.add_argument("--result-csv", default="")
    parser.add_argument("--integrity-csv", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = Path(args.result_csv) if args.result_csv else None
    integrity = Path(args.integrity_csv) if args.integrity_csv else None
    summary = run(Path(args.repo_root), result_csv=result, integrity_csv=integrity)
    return 0 if str(summary["final_status"]).startswith(("PASS", "WARN")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
