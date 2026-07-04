#!/usr/bin/env python
"""V21.214 large outputs/v21 cold archive candidate plan.

Research-only, audit-only. This stage proposes future zip-copy cold archive
candidates for large historical outputs/v21 stage directories. It never
compresses, deletes, moves, refreshes prices, mutates canonical files, connects
to OpenD, changes adoption outputs, or performs broker actions.
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
STAGE = "V21.214_LARGE_OUTPUTS_COLD_ARCHIVE_CANDIDATE_PLAN"
OUT_REL = Path("outputs/v21/V21.214_LARGE_OUTPUTS_COLD_ARCHIVE_CANDIDATE_PLAN")
REGISTRY_REL = Path("outputs/v21/V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY/artifact_registry.csv")
STAGE_ROLE_REL = Path("outputs/v21/V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY/stage_role_summary.csv")
RISK_BUDGET_REL = Path("outputs/v21/V21.211_SECOND_PASS_CLEANUP_TARGET_DISCOVERY_AND_RISK_BUDGET/cleanup_target_risk_budget.csv")
MIN_SIZE_BYTES = 25 * 1024 * 1024
DELETED_ARCHIVED_ORIGINALS = {
    "V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST",
    "V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST",
    "V21.148_E_R1_A1_PIT_LITE_REPLAY_DIAGNOSTIC_ONLY",
}
PROTECTED_REQUIRED = [
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
    "outputs/v21/V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY",
]
SENSITIVE_TOKENS = [
    "canonical", "price_history", "ohlcv", "kline", "moomoo", "dram", "abcde",
    "trade_plan", "ledger", "ranking", "latest", "current_chain", "protected",
]
ROLE_INCLUDE = {
    "AUDIT_CRITICAL_HISTORY",
    "REPRODUCIBILITY_SUPPORT",
    "BACKTEST_RESULT",
    "DIAGNOSTIC_ONLY",
    "UNKNOWN_REVIEW_REQUIRED",
}
RETENTION_INCLUDE = {
    "RETAIN_AUDIT_CRITICAL",
    "RETAIN_REPRODUCIBILITY",
    "REVIEW_COLD_ARCHIVE",
    "UNKNOWN_MANUAL_REVIEW",
}
PLAN_FIELDS = [
    "stage_dir", "source_path", "recursive_size_bytes", "file_count", "directory_count",
    "largest_file_path", "largest_file_size_bytes", "csv_size_bytes", "json_size_bytes",
    "txt_size_bytes", "parquet_size_bytes", "other_size_bytes", "registry_artifact_role",
    "registry_retention_class", "current_chain_required", "audit_required",
    "reproducibility_required", "protected_flag", "sensitive_keyword_count",
    "cold_archive_candidate_tier", "future_action_plan", "estimated_zip_size_bytes",
    "estimated_savings_if_expanded_original_removed_later", "manual_review_required",
    "compression_allowed_in_this_run", "deletion_allowed_in_this_run",
    "deletion_allowed_after_zip", "rationale", "blocker_reasons",
]
EXCLUSION_FIELDS = ["stage_dir", "source_path", "excluded", "exclusion_reasons", "sensitive_keyword_count", "protected_flag", "current_chain_required", "already_archived_flag"]
MANIFEST_FIELDS = ["stage_dir", "relative_file_path", "file_size_bytes", "file_extension", "modified_time", "manifest_preview_status"]
SAVINGS_FIELDS = ["stage_dir", "recursive_size_bytes", "estimated_zip_size_bytes", "estimated_savings_if_expanded_original_removed_later", "cold_archive_candidate_tier", "future_action_plan"]
PRESENCE_FIELDS = ["protected_key", "expected_path", "exact_exists", "alias_discovery_attempted", "alias_candidate_count", "resolved_exists", "resolved_protected_path", "resolution_method", "warning_reason"]
REGISTRY_CHECK_FIELDS = ["input_path", "exists", "row_count", "used_for_classification", "rationale"]


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
        return sorted([p for p in path.rglob("*") if p.is_file()], key=lambda p: p.as_posix())
    except OSError:
        return []


def iter_dirs(path: Path) -> list[Path]:
    try:
        return sorted([p for p in path.rglob("*") if p.is_dir()], key=lambda p: p.as_posix())
    except OSError:
        return []


def file_time(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat()
    except OSError:
        return ""


def metrics(path: Path, root: Path) -> dict[str, Any]:
    files = iter_files(path)
    dirs = iter_dirs(path)
    by_ext = defaultdict(int)
    total = 0
    largest_file = ""
    largest_size = 0
    for file in files:
        try:
            size = file.stat().st_size
        except OSError:
            continue
        total += size
        ext = file.suffix.lower()
        by_ext[ext] += size
        if size > largest_size:
            largest_size = size
            largest_file = rel(file, root)
    csv_size = by_ext[".csv"]
    json_size = by_ext[".json"]
    txt_size = by_ext[".txt"] + by_ext[".md"] + by_ext[".log"]
    parquet_size = by_ext[".parquet"]
    other_size = max(0, total - csv_size - json_size - txt_size - parquet_size)
    return {
        "recursive_size_bytes": total,
        "file_count": len(files),
        "directory_count": len(dirs),
        "largest_file_path": largest_file,
        "largest_file_size_bytes": largest_size,
        "csv_size_bytes": csv_size,
        "json_size_bytes": json_size,
        "txt_size_bytes": txt_size,
        "parquet_size_bytes": parquet_size,
        "other_size_bytes": other_size,
        "files": files,
    }


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


def v21_201_alias_is_current_chain(path: Path) -> bool:
    tokens = {"dram", "moomoo", "plan", "r4", "daily"}
    if any(token in path.name.lower() for token in tokens):
        return True
    for file in iter_files(path)[:50]:
        if any(token in file.name.lower() for token in tokens):
            return True
    return False


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


def registry_by_stage(root: Path) -> dict[str, dict[str, str]]:
    rows = read_csv(root / REGISTRY_REL)
    mapping: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.get("artifact_type") != "stage_directory":
            continue
        stage_name = row.get("stage_name") or Path(row.get("artifact_path", "")).name
        if stage_name:
            mapping[stage_name] = row
    return mapping


def sensitive_keyword_count(path: Path, root: Path, files: list[Path]) -> int:
    text_hits = 0
    all_names = [path.name.lower()] + [rel(file, root).lower() for file in files[:500]]
    for token in SENSITIVE_TOKENS:
        if any(token in name for name in all_names):
            text_hits += 1
    return text_hits


def is_cleanup_stage(stage: str) -> bool:
    for num in range(202, 215):
        if stage.startswith(f"V21.{num}"):
            return True
    return False


def estimate_zip_size(row: dict[str, Any]) -> int:
    # Conservative dry-run estimate: text/csv/json compress well; unknown data less so.
    return int(
        int(row["csv_size_bytes"]) * 0.22
        + int(row["json_size_bytes"]) * 0.25
        + int(row["txt_size_bytes"]) * 0.30
        + int(row["parquet_size_bytes"]) * 0.90
        + int(row["other_size_bytes"]) * 0.55
    )


def classify_stage(stage_path: Path, root: Path, reg: dict[str, str], m: dict[str, Any], protected_rels: set[str]) -> tuple[str, str, str, str]:
    stage = stage_path.name
    role = reg.get("artifact_role", "UNKNOWN_REVIEW_REQUIRED")
    retention = reg.get("retention_class", "UNKNOWN_MANUAL_REVIEW")
    current = str_bool(reg.get("current_chain_required"))
    protected = str_bool(reg.get("protected_flag")) or rel(stage_path, root) in protected_rels
    sensitive = sensitive_keyword_count(stage_path, root, m["files"])
    blockers: list[str] = []
    if stage in DELETED_ARCHIVED_ORIGINALS:
        blockers.append("ALREADY_ARCHIVED_OR_ORIGINAL_DELETED")
        return "NOT_CANDIDATE", "ALREADY_ARCHIVED", "Previously archived/deleted original is not included.", "|".join(blockers)
    if stage.startswith("V21.140"):
        blockers.append("SENSITIVE_HISTORICAL_PRICE_PANEL")
        return "NOT_CANDIDATE", "EXCLUDE_SENSITIVE_PRICE_OR_BROKER_DATA", "V21.140 contains historical price panel semantics.", "|".join(blockers)
    if protected:
        blockers.append("PROTECTED_STAGE")
        return "NOT_CANDIDATE", "KEEP_AS_IS_PROTECTED", "Protected/current-chain stage is excluded.", "|".join(blockers)
    if current:
        blockers.append("CURRENT_CHAIN_REQUIRED")
        return "NOT_CANDIDATE", "KEEP_AS_IS_CURRENT_CHAIN", "Current-chain required artifact is excluded.", "|".join(blockers)
    if is_cleanup_stage(stage):
        blockers.append("CLEANUP_REPAIR_CHAIN_OUTPUT")
        return "NOT_CANDIDATE", "KEEP_AS_IS_PROTECTED", "Cleanup/repair chain outputs V21.202+ are excluded.", "|".join(blockers)
    if m["recursive_size_bytes"] < MIN_SIZE_BYTES:
        blockers.append("BELOW_25MB_THRESHOLD")
        return "NOT_CANDIDATE", "MANUAL_RECLASSIFICATION_REQUIRED_BEFORE_ZIP", "Below large-output threshold.", "|".join(blockers)
    manual = str_bool(reg.get("manual_approval_required"))
    explicit_non_current = role in {"DIAGNOSTIC_ONLY", "BACKTEST_RESULT", "AUDIT_CRITICAL_HISTORY", "REPRODUCIBILITY_SUPPORT"} and manual
    if sensitive and not explicit_non_current:
        blockers.append("SENSITIVE_KEYWORD_WITHOUT_NONCURRENT_REGISTRY_CONFIRMATION")
        return "NOT_CANDIDATE", "EXCLUDE_SENSITIVE_PRICE_OR_BROKER_DATA", "Sensitive keyword requires explicit non-current historical diagnostic registry classification.", "|".join(blockers)
    if stage.startswith("V21.154"):
        return "TIER_A_COLD_ARCHIVE_RETAIN_EVIDENCE", "ZIP_COPY_ONLY_NEXT_STAGE", "Audit-critical invalid-trial replay evidence may be zip-copied only, never deleted in this plan.", ""
    if role in {"AUDIT_CRITICAL_HISTORY", "REPRODUCIBILITY_SUPPORT"} or retention in {"RETAIN_AUDIT_CRITICAL", "RETAIN_REPRODUCIBILITY"}:
        return "TIER_A_COLD_ARCHIVE_RETAIN_EVIDENCE", "ZIP_COPY_ONLY_NEXT_STAGE", "Large audit/reproducibility evidence eligible for future zip-copy with strict approval.", ""
    if role in {"BACKTEST_RESULT", "DIAGNOSTIC_ONLY"}:
        return "TIER_B_COLD_ARCHIVE_REVIEW", "ZIP_COPY_ONLY_NEXT_STAGE", "Large diagnostic/backtest output likely archivable after manual review.", ""
    if role == "UNKNOWN_REVIEW_REQUIRED" or retention in {"REVIEW_COLD_ARCHIVE", "UNKNOWN_MANUAL_REVIEW"}:
        return "TIER_C_UNKNOWN_REVIEW_LARGE", "MANUAL_RECLASSIFICATION_REQUIRED_BEFORE_ZIP", "Large unknown item requires manual classification before zip.", ""
    blockers.append("ROLE_RETENTION_NOT_INCLUDED")
    return "NOT_CANDIDATE", "MANUAL_RECLASSIFICATION_REQUIRED_BEFORE_ZIP", "Role/retention class is outside cold archive inclusion policy.", "|".join(blockers)


def plan_rows(root: Path, protected_rels: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    regmap = registry_by_stage(root)
    out21 = root / "outputs/v21"
    rows: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []
    if not out21.exists():
        return rows, exclusions, manifest
    for stage_path in sorted([p for p in out21.iterdir() if p.is_dir()], key=lambda p: p.name):
        m = metrics(stage_path, root)
        reg = regmap.get(stage_path.name, {})
        tier, action, rationale, blockers = classify_stage(stage_path, root, reg, m, protected_rels)
        sensitive = sensitive_keyword_count(stage_path, root, m["files"])
        row = {
            "stage_dir": stage_path.name,
            "source_path": rel(stage_path, root),
            "recursive_size_bytes": m["recursive_size_bytes"],
            "file_count": m["file_count"],
            "directory_count": m["directory_count"],
            "largest_file_path": m["largest_file_path"],
            "largest_file_size_bytes": m["largest_file_size_bytes"],
            "csv_size_bytes": m["csv_size_bytes"],
            "json_size_bytes": m["json_size_bytes"],
            "txt_size_bytes": m["txt_size_bytes"],
            "parquet_size_bytes": m["parquet_size_bytes"],
            "other_size_bytes": m["other_size_bytes"],
            "registry_artifact_role": reg.get("artifact_role", "UNKNOWN_REVIEW_REQUIRED"),
            "registry_retention_class": reg.get("retention_class", "UNKNOWN_MANUAL_REVIEW"),
            "current_chain_required": str_bool(reg.get("current_chain_required")),
            "audit_required": str_bool(reg.get("audit_required")),
            "reproducibility_required": str_bool(reg.get("reproducibility_required")),
            "protected_flag": str_bool(reg.get("protected_flag")) or rel(stage_path, root) in protected_rels,
            "sensitive_keyword_count": sensitive,
            "cold_archive_candidate_tier": tier,
            "future_action_plan": action,
            "manual_review_required": True,
            "compression_allowed_in_this_run": False,
            "deletion_allowed_in_this_run": False,
            "deletion_allowed_after_zip": False,
            "rationale": rationale,
            "blocker_reasons": blockers,
        }
        zip_size = estimate_zip_size(row)
        row["estimated_zip_size_bytes"] = zip_size
        row["estimated_savings_if_expanded_original_removed_later"] = max(0, int(row["recursive_size_bytes"]) - zip_size)
        if tier != "NOT_CANDIDATE":
            rows.append(row)
            for file in m["files"][:200]:
                try:
                    size = file.stat().st_size
                except OSError:
                    size = 0
                manifest.append({
                    "stage_dir": stage_path.name,
                    "relative_file_path": rel(file, stage_path),
                    "file_size_bytes": size,
                    "file_extension": file.suffix.lower(),
                    "modified_time": file_time(file),
                    "manifest_preview_status": "PREVIEW_ONLY_NO_HASH_NO_COPY",
                })
        exclusions.append({
            "stage_dir": stage_path.name,
            "source_path": rel(stage_path, root),
            "excluded": tier == "NOT_CANDIDATE",
            "exclusion_reasons": blockers,
            "sensitive_keyword_count": sensitive,
            "protected_flag": row["protected_flag"],
            "current_chain_required": row["current_chain_required"],
            "already_archived_flag": stage_path.name in DELETED_ARCHIVED_ORIGINALS,
        })
    rows.sort(key=lambda r: int(r["recursive_size_bytes"]), reverse=True)
    return rows, exclusions, manifest


def registry_checks(root: Path) -> list[dict[str, Any]]:
    checks = []
    for relpath, used, rationale in [
        (REGISTRY_REL, True, "Primary artifact role/retention source."),
        (STAGE_ROLE_REL, False, "Optional supporting summary."),
        (RISK_BUDGET_REL, False, "Optional prior risk budget context."),
    ]:
        path = root / relpath
        checks.append({
            "input_path": relpath.as_posix(),
            "exists": path.exists(),
            "row_count": len(read_csv(path)),
            "used_for_classification": used and path.exists(),
            "rationale": rationale,
        })
    return checks


def policy_flags() -> dict[str, Any]:
    return {
        "research_only": True,
        "audit_only": True,
        "dry_run": True,
        "mutation_allowed": False,
        "compression_performed": False,
        "deletion_performed": False,
        "archive_movement_performed": False,
        "price_refresh_performed": False,
        "canonical_mutation_performed": False,
        "moomoo_broker_connection_performed": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "protected_outputs_modified": False,
    }


def summarize(rows: list[dict[str, Any]], scanned: int, protected_missing: int) -> dict[str, Any]:
    by_tier = defaultdict(list)
    for row in rows:
        by_tier[row["cold_archive_candidate_tier"]].append(row)
    largest = rows[0] if rows else {}
    total_size = sum(int(r["recursive_size_bytes"]) for r in rows)
    total_zip = sum(int(r["estimated_zip_size_bytes"]) for r in rows)
    if protected_missing:
        final_status = "FAIL_V21_214_PROTECTED_PATH_MISSING"
        final_decision = "LARGE_OUTPUTS_COLD_ARCHIVE_FAILED_PROTECTED_PATH_MISSING"
    elif not rows:
        final_status = "WARN_V21_214_NO_COLD_ARCHIVE_CANDIDATES"
        final_decision = "LARGE_OUTPUTS_COLD_ARCHIVE_NO_CANDIDATES"
    else:
        final_status = "PASS_V21_214_COLD_ARCHIVE_CANDIDATE_PLAN_READY"
        final_decision = "LARGE_OUTPUTS_COLD_ARCHIVE_CANDIDATES_READY_MANUAL_REVIEW"
    summary = {
        "stage": STAGE,
        "total_stage_dirs_scanned": scanned,
        "candidate_count": len(rows),
        "tier_a_count": len(by_tier["TIER_A_COLD_ARCHIVE_RETAIN_EVIDENCE"]),
        "tier_a_size_bytes": sum(int(r["recursive_size_bytes"]) for r in by_tier["TIER_A_COLD_ARCHIVE_RETAIN_EVIDENCE"]),
        "tier_b_count": len(by_tier["TIER_B_COLD_ARCHIVE_REVIEW"]),
        "tier_b_size_bytes": sum(int(r["recursive_size_bytes"]) for r in by_tier["TIER_B_COLD_ARCHIVE_REVIEW"]),
        "tier_c_count": len(by_tier["TIER_C_UNKNOWN_REVIEW_LARGE"]),
        "tier_c_size_bytes": sum(int(r["recursive_size_bytes"]) for r in by_tier["TIER_C_UNKNOWN_REVIEW_LARGE"]),
        "total_candidate_size_bytes": total_size,
        "estimated_total_zip_size_bytes": total_zip,
        "estimated_savings_if_expanded_originals_removed_later": max(0, total_size - total_zip),
        "largest_candidate_stage": largest.get("stage_dir", ""),
        "largest_candidate_size_bytes": int(largest.get("recursive_size_bytes", 0) or 0),
        "protected_path_missing_count": protected_missing,
        "compression_allowed_in_this_run": False,
        "deletion_allowed_in_this_run": False,
        "final_status": final_status,
        "final_decision": final_decision,
        **policy_flags(),
    }
    return summary


def write_report(path: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"candidate_count={summary['candidate_count']}",
        f"total_candidate_size_bytes={summary['total_candidate_size_bytes']}",
        f"estimated_total_zip_size_bytes={summary['estimated_total_zip_size_bytes']}",
        f"estimated_savings_if_expanded_originals_removed_later={summary['estimated_savings_if_expanded_originals_removed_later']}",
        "compression_allowed_in_this_run=false",
        "deletion_allowed_in_this_run=false",
        "",
        "Top candidates:",
    ]
    for row in rows[:20]:
        lines.append(f"{row['stage_dir']},{row['cold_archive_candidate_tier']},{row['recursive_size_bytes']},{row['future_action_plan']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(repo_root: Path = DEFAULT_ROOT, out_dir: Path | None = None, simulate_exception: bool = False) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if simulate_exception:
            raise RuntimeError("simulated V21.214 failure")
        presence = protected_presence(root)
        missing = [row for row in presence if not str_bool(row["resolved_exists"])]
        protected_rels = {row["resolved_protected_path"] for row in presence if row.get("resolved_protected_path")}
        rows, exclusions, manifest = plan_rows(root, protected_rels)
        out21 = root / "outputs/v21"
        scanned = len([p for p in out21.iterdir() if p.is_dir()]) if out21.exists() else 0
        summary = summarize(rows, scanned, len(missing))
        write_csv(output / "large_outputs_cold_archive_candidate_plan.csv", rows, PLAN_FIELDS)
        write_csv(output / "large_outputs_cold_archive_exclusion_check.csv", exclusions, EXCLUSION_FIELDS)
        write_csv(output / "large_outputs_candidate_file_manifest_preview.csv", manifest, MANIFEST_FIELDS)
        write_csv(output / "projected_savings_by_candidate.csv", rows, SAVINGS_FIELDS)
        write_csv(output / "protected_path_presence_check.csv", presence, PRESENCE_FIELDS)
        write_csv(output / "registry_input_check.csv", registry_checks(root), REGISTRY_CHECK_FIELDS)
        write_json(output / "v21_214_summary.json", summary)
        write_report(output / "V21.214_large_outputs_cold_archive_candidate_plan_report.txt", summary, rows)
    except Exception as exc:
        summary = {
            "stage": STAGE,
            "final_status": "FAIL_V21_214_COLD_ARCHIVE_PLAN_EXCEPTION",
            "final_decision": "LARGE_OUTPUTS_COLD_ARCHIVE_PLAN_FAILED",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            **policy_flags(),
        }
        write_json(output / "v21_214_summary.json", summary)
        (output / "V21.214_large_outputs_cold_archive_candidate_plan_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\nerror={summary['error_type']}: {summary['error_message']}\n", encoding="utf-8")
    for key in ["final_status", "final_decision", "candidate_count", "total_candidate_size_bytes", "compression_allowed_in_this_run", "deletion_allowed_in_this_run"]:
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
