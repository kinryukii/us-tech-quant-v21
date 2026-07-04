#!/usr/bin/env python
"""V21.204 outputs/v21 archive candidate audit.

Audit-only. This stage never deletes, moves, compresses, or mutates existing
project artifacts; it writes only its own audit outputs.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path(r"D:\us-tech-quant")
STAGE = "V21.204_OUTPUTS_V21_ARCHIVE_CANDIDATE_AUDIT"
OUT_REL = Path("outputs/v21/V21.204_OUTPUTS_V21_ARCHIVE_CANDIDATE_AUDIT")
PROTECTED_EXPECTED = [
    "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
    "V21.202_REPO_SAFE_CLEANUP_AUDIT_AND_CACHE_PURGE",
    "V21.203_REPO_SIZE_ATTRIBUTION_AND_SAFE_PURGE_CANDIDATE_AUDIT",
]
CURRENT_CHAIN_KEYWORDS = [
    "latest",
    "dram",
    "moomoo",
    "abcde",
    "canonical",
    "price_history",
    "kline",
    "ranking",
    "ledger",
    "trade_plan",
    "trade-plan",
]
SENSITIVE_FILE_TOKENS = ["trade_plan", "trade-plan", "canonical", "ledger", "ranking", "price_history", "ohlcv", "kline"]
CSV_FIELDS = [
    "stage_dir",
    "stage_name",
    "recursive_size_bytes",
    "file_count",
    "directory_count",
    "latest_modified_time",
    "earliest_modified_time",
    "age_days",
    "contains_summary_json",
    "contains_report_txt",
    "contains_csv",
    "contains_trade_plan_like_file",
    "contains_price_history_like_file",
    "contains_canonical_like_file",
    "contains_moomoo_like_file",
    "contains_dram_like_file",
    "contains_abcde_like_file",
    "protected_stage_flag",
    "current_chain_flag",
    "archive_candidate_flag",
    "archive_candidate_tier",
    "exclusion_reasons",
]
LARGEST_FIELDS = ["stage_dir", "stage_name", "recursive_size_bytes", "file_count", "directory_count", "latest_modified_time", "archive_candidate_tier"]
PROTECTED_FIELDS = ["protected_key", "expected_stage_dir", "exact_exists", "alias_discovery_attempted", "alias_candidate_count", "resolved_exists", "resolved_stage_dir", "resolution_method", "warning_reason", "alias_candidates"]
REASON_FIELDS = ["exclusion_reason", "count"]


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/")


def utc_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat()
    except OSError:
        return ""


def stage_dirs(root: Path) -> list[Path]:
    out21 = root / "outputs/v21"
    if not out21.exists():
        return []
    return sorted([path for path in out21.iterdir() if path.is_dir() and path.name.startswith("V21.")], key=lambda p: p.name)


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


def iter_stage_files(stage: Path) -> list[Path]:
    try:
        return [path for path in stage.rglob("*") if path.is_file()]
    except OSError:
        return []


def stage_metrics(stage: Path, root: Path, protected_names: set[str], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    files = iter_stage_files(stage)
    dirs = [path for path in stage.rglob("*") if path.is_dir()] if stage.exists() else []
    size = 0
    mtimes: list[float] = []
    names = [stage.name.lower()]
    for file in files:
        try:
            stat = file.stat()
            size += stat.st_size
            mtimes.append(stat.st_mtime)
            names.append(file.name.lower())
        except OSError:
            continue
    latest_ts = max(mtimes) if mtimes else (stage.stat().st_mtime if stage.exists() else 0.0)
    earliest_ts = min(mtimes) if mtimes else latest_ts
    latest_dt = datetime.fromtimestamp(latest_ts, timezone.utc) if latest_ts else now
    age_days = max(0.0, (now - latest_dt).total_seconds() / 86400)
    joined = " ".join(names)
    contains_summary = any(file.name.lower().endswith("summary.json") for file in files)
    contains_report = any(file.name.lower().endswith(".txt") and "report" in file.name.lower() for file in files)
    contains_csv = any(file.suffix.lower() == ".csv" for file in files)
    flags = {
        "contains_trade_plan_like_file": any("trade_plan" in name or "trade-plan" in name for name in names),
        "contains_price_history_like_file": any("price_history" in name for name in names),
        "contains_canonical_like_file": any("canonical" in name for name in names),
        "contains_moomoo_like_file": any("moomoo" in name for name in names),
        "contains_dram_like_file": any("dram" in name for name in names),
        "contains_abcde_like_file": any("abcde" in name for name in names),
    }
    protected = stage.name in protected_names
    sensitive_file = any(any(token in file.name.lower() for token in SENSITIVE_FILE_TOKENS) for file in files)
    current_chain = any(keyword in joined for keyword in CURRENT_CHAIN_KEYWORDS)
    cache_only = all(any(token in file.as_posix().lower() for token in ["pytest_tmp", "__pycache__", ".pytest_cache"]) for file in files) if files else False
    reasons = []
    if protected:
        reasons.append("PROTECTED_STAGE")
    if current_chain:
        reasons.append("CURRENT_CHAIN_KEYWORD")
    if sensitive_file:
        reasons.append("SENSITIVE_CURRENT_ARTIFACT_NAME")
    if cache_only:
        reasons.append("CACHE_ONLY")
    if size < 1024 * 1024:
        reasons.append("TINY_UNDER_1MB")
    if age_days < 7:
        reasons.append("RECENT_UNDER_7_DAYS")
    tier = "NOT_ARCHIVE_CANDIDATE"
    candidate = False
    if not protected and not current_chain and not sensitive_file and not cache_only:
        if size >= 10 * 1024 * 1024 and age_days >= 7 and contains_summary and contains_report:
            tier = "TIER_1_ARCHIVE_CANDIDATE"
            candidate = True
        elif (size >= 1024 * 1024 and age_days >= 7) or (age_days >= 7 and not (contains_summary and contains_report) and size >= 1024 * 1024):
            tier = "TIER_2_REVIEW_CANDIDATE"
            candidate = True
        else:
            reasons.append("BELOW_ARCHIVE_THRESHOLD")
    row = {
        "stage_dir": rel(stage, root),
        "stage_name": stage.name,
        "recursive_size_bytes": size,
        "file_count": len(files),
        "directory_count": len(dirs),
        "latest_modified_time": datetime.fromtimestamp(latest_ts, timezone.utc).replace(microsecond=0).isoformat() if latest_ts else "",
        "earliest_modified_time": datetime.fromtimestamp(earliest_ts, timezone.utc).replace(microsecond=0).isoformat() if earliest_ts else "",
        "age_days": round(age_days, 3),
        "contains_summary_json": contains_summary,
        "contains_report_txt": contains_report,
        "contains_csv": contains_csv,
        **flags,
        "protected_stage_flag": protected,
        "current_chain_flag": current_chain,
        "archive_candidate_flag": candidate,
        "archive_candidate_tier": tier,
        "exclusion_reasons": "|".join(sorted(set(reasons))),
    }
    return row


def audit_stages(root: Path, resolution: list[dict[str, Any]], now: datetime | None = None) -> list[dict[str, Any]]:
    protected_names = protected_stage_names(root, resolution)
    return sorted([stage_metrics(stage, root, protected_names, now=now) for stage in stage_dirs(root)], key=lambda row: int(row["recursive_size_bytes"]), reverse=True)


def reason_counts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for row in rows:
        reasons = str(row["exclusion_reasons"]).split("|") if row["exclusion_reasons"] else []
        for reason in reasons:
            counts[reason] += 1
    return [{"exclusion_reason": key, "count": value} for key, value in sorted(counts.items())]


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def write_report(path: Path, summary: dict[str, Any], rows: list[dict[str, Any]], resolution: list[dict[str, Any]]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"total_stage_dirs_scanned={summary['total_stage_dirs_scanned']}",
        f"total_outputs_v21_size_bytes={summary['total_outputs_v21_size_bytes']}",
        f"tier_1_archive_candidate_count={summary['tier_1_archive_candidate_count']}",
        f"tier_1_archive_candidate_size_bytes={summary['tier_1_archive_candidate_size_bytes']}",
        f"tier_2_review_candidate_count={summary['tier_2_review_candidate_count']}",
        f"tier_2_review_candidate_size_bytes={summary['tier_2_review_candidate_size_bytes']}",
        "research_only=true",
        "audit_only=true",
        "mutation_allowed=false",
        "archive_movement_performed=false",
        "deletion_performed=false",
        "compression_performed=false",
        "broker_action_allowed=false",
        "official_adoption_allowed=false",
        "protected_outputs_modified=false",
        "",
        "protected_stage_resolution:",
    ]
    lines.extend([f"- {row['protected_key']} resolved={row['resolved_exists']} path={row['resolved_stage_dir']} method={row['resolution_method']}" for row in resolution])
    lines.extend(["", "largest_stage_directories:"])
    lines.extend([f"- {row['stage_name']} size_bytes={row['recursive_size_bytes']} tier={row['archive_candidate_tier']}" for row in rows[:20]])
    lines.extend(["", "tier_1_candidates:"])
    lines.extend([f"- {row['stage_name']} size_bytes={row['recursive_size_bytes']}" for row in rows if row["archive_candidate_tier"] == "TIER_1_ARCHIVE_CANDIDATE"])
    lines.append("")
    lines.append("next_recommended_action=Manual review only; consider external archive/compression plan in a separate explicitly approved stage.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(repo_root: Path = DEFAULT_ROOT, out_dir: Path | None = None, simulate_exception: bool = False, now: datetime | None = None) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if simulate_exception:
            raise RuntimeError("simulated audit failure")
        if not (root / "outputs/v21").exists():
            raise RuntimeError("outputs/v21 not found")
        resolution = protected_resolution(root)
        rows = audit_stages(root, resolution, now=now)
        missing = [row for row in resolution if not row["resolved_exists"]]
        tier1 = [row for row in rows if row["archive_candidate_tier"] == "TIER_1_ARCHIVE_CANDIDATE"]
        tier2 = [row for row in rows if row["archive_candidate_tier"] == "TIER_2_REVIEW_CANDIDATE"]
        not_archive = [row for row in rows if row["archive_candidate_tier"] == "NOT_ARCHIVE_CANDIDATE"]
        largest = rows[0] if rows else {"stage_name": "", "recursive_size_bytes": 0}
        final_status = "WARN_V21_204_PROTECTED_STAGE_RESOLUTION_INCOMPLETE" if missing else "PASS_V21_204_ARCHIVE_CANDIDATE_AUDIT_READY"
        final_decision = "OUTPUTS_V21_ARCHIVE_AUDIT_WARN_PROTECTED_RESOLUTION" if missing else "OUTPUTS_V21_ARCHIVE_CANDIDATES_READY_FOR_MANUAL_REVIEW"
        summary = {
            "stage": STAGE,
            "final_status": final_status,
            "final_decision": final_decision,
            "total_stage_dirs_scanned": len(rows),
            "total_outputs_v21_size_bytes": sum(int(row["recursive_size_bytes"]) for row in rows),
            "protected_stage_count": sum(1 for row in rows if row["protected_stage_flag"]),
            "current_chain_stage_count": sum(1 for row in rows if row["current_chain_flag"]),
            "tier_1_archive_candidate_count": len(tier1),
            "tier_1_archive_candidate_size_bytes": sum(int(row["recursive_size_bytes"]) for row in tier1),
            "tier_2_review_candidate_count": len(tier2),
            "tier_2_review_candidate_size_bytes": sum(int(row["recursive_size_bytes"]) for row in tier2),
            "not_archive_candidate_count": len(not_archive),
            "largest_stage_dir": largest["stage_name"],
            "largest_stage_size_bytes": int(largest["recursive_size_bytes"]),
            "protected_resolution_missing_count": len(missing),
            "research_only": True,
            "audit_only": True,
            "mutation_allowed": False,
            "archive_movement_performed": False,
            "deletion_performed": False,
            "compression_performed": False,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "protected_outputs_modified": False,
        }
        write_csv(output / "outputs_v21_stage_archive_candidate_audit.csv", rows, CSV_FIELDS)
        write_csv(output / "outputs_v21_largest_stage_directories.csv", rows, LARGEST_FIELDS)
        write_csv(output / "protected_stage_resolution_check.csv", resolution, PROTECTED_FIELDS)
        write_csv(output / "archive_candidate_exclusion_reason_counts.csv", reason_counts(rows), REASON_FIELDS)
        write_json(output / "v21_204_summary.json", summary)
        write_report(output / "V21.204_outputs_v21_archive_candidate_report.txt", summary, rows, resolution)
    except Exception as exc:
        summary = {
            "stage": STAGE,
            "final_status": "FAIL_V21_204_ARCHIVE_CANDIDATE_AUDIT_EXCEPTION",
            "final_decision": "OUTPUTS_V21_ARCHIVE_AUDIT_FAILED",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "research_only": True,
            "audit_only": True,
            "mutation_allowed": False,
            "archive_movement_performed": False,
            "deletion_performed": False,
            "compression_performed": False,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "protected_outputs_modified": False,
        }
        write_json(output / "v21_204_summary.json", summary)
        (output / "V21.204_outputs_v21_archive_candidate_report.txt").write_text(
            "\n".join([STAGE, f"final_status={summary['final_status']}", f"final_decision={summary['final_decision']}", f"error={summary['error_type']}: {summary['error_message']}"]) + "\n",
            encoding="utf-8",
        )
    for key in ["final_status", "final_decision", "total_stage_dirs_scanned", "tier_1_archive_candidate_count", "tier_2_review_candidate_count", "deletion_performed", "broker_action_allowed"]:
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
