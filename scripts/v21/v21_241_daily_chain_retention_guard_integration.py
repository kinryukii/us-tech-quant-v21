#!/usr/bin/env python
"""V21.241 daily-chain retention guard integration."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


STAGE = "V21.241_DAILY_CHAIN_RETENTION_GUARD_INTEGRATION"
OUT_REL = Path("outputs/v21") / STAGE
PASS_READY = "PASS_V21_241_DAILY_CHAIN_RETENTION_GUARD_READY"
PASS_DISCOVERY = "PASS_V21_241_DAILY_CHAIN_RETENTION_GUARD_DISCOVERY_READY"
WARN_GUARD_FAILED = "WARN_V21_241_RETENTION_GUARD_FAILED_RESEARCH_ONLY_BLOCK"
WARN_GUARD_REVIEW = "WARN_V21_241_RETENTION_GUARD_WARNING_REVIEW_REQUIRED"
FAIL_CHILD = "FAIL_V21_241_DAILY_CHAIN_CHILD_FAILED"
FAIL_GUARD = "FAIL_V21_241_RETENTION_GUARD_BLOCKED_DAILY_CHAIN"
FAIL_MISSING = "FAIL_V21_241_RETENTION_GUARD_MISSING"
MODES = {"disabled", "post_run_audit", "post_run_maintenance", "discover_only"}
V240_STAGE = "V21.240_RETENTION_POLICY_AND_MAINTENANCE_GUARD"
V240_SUMMARY = Path("outputs/v21") / V240_STAGE / "v21_240_summary.json"


def default_repo_root() -> Path:
    return Path(r"D:\us-tech-quant")


def default_archive_root() -> Path:
    return Path(r"D:\us-tech-quant-archive")


def default_cache_root() -> Path:
    return Path(r"D:\us-tech-quant-cache")


def default_quarantine_root() -> Path:
    return Path(r"D:\us-tech-quant-quarantine")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")


def safe_read(path: Path, limit: int = 200_000) -> str:
    try:
        if not path.exists() or path.stat().st_size > limit:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def classify_candidate(path: Path) -> str:
    name = path.name.lower()
    text = safe_read(path).lower()
    if "v21_240" in name or "retention_guard" in name or "retention_policy" in name:
        return "RETENTION_GUARD_ONLY"
    if "test" in name:
        return "LEGACY_OR_STAGE_CHAIN"
    strong = ("daily" in name and "chain" in name and ("moomoo" in name or "research" in name or "root" in name))
    refs_current = any(token in text for token in ("v21.198", "v21.199", "v21.199_r4", "v21.197", "v21.201", "v21.234"))
    if strong and refs_current:
        return "CURRENT_DAILY_CHAIN_CONFIRMED"
    if "daily" in name or "chain" in name or "orchestrator" in name:
        return "POSSIBLE_DAILY_CHAIN"
    if any(token in name for token in ("v21_178", "v21_201", "v21_223")):
        return "LEGACY_OR_STAGE_CHAIN"
    return "UNKNOWN"


def discover_candidates(repo_root: Path) -> list[dict[str, Any]]:
    patterns = [
        "scripts/v21/run_*daily*.ps1",
        "scripts/v21/run_*chain*.ps1",
        "scripts/v21/*daily*chain*.py",
        "scripts/v21/*orchestrator*.py",
        "scripts/v21/run_v21_178*",
        "scripts/v21/run_v21_201*",
        "scripts/v21/run_v21_223*",
        "run_daily*.ps1",
        "run_*chain*.ps1",
    ]
    seen: set[Path] = set()
    rows: list[dict[str, Any]] = []
    for pattern in patterns:
        for p in repo_root.glob(pattern):
            if not p.is_file() or p in seen:
                continue
            seen.add(p)
            classification = classify_candidate(p)
            rows.append({
                "path": str(p),
                "relative_path": p.relative_to(repo_root).as_posix(),
                "classification": classification,
                "selected_for_patch": False,
                "notes": "no active wrapper patched by V21.241",
            })
    return sorted(rows, key=lambda r: (r["classification"], r["relative_path"]))


def guard_status_map() -> list[dict[str, str]]:
    mapping = {
        "PASS_V21_240_RETENTION_GUARD_OK": "PASS",
        "PASS_V21_240_RETENTION_GUARD_MAINTENANCE_APPLIED": "PASS",
        "WARN_V21_240_RETENTION_GUARD_WARN_BUDGET": "WARN",
        "WARN_V21_240_RETENTION_GUARD_REPO_LARGE_FILE_VIOLATION": "WARN",
        "FAIL_V21_240_RETENTION_GUARD_HARD_BUDGET_BREACH": "FAIL",
        "FAIL_V21_240_RETENTION_GUARD_ERROR": "FAIL",
    }
    return [{"v21_240_final_status": k, "guard_result": v} for k, v in mapping.items()]


def build_v240_command(args: argparse.Namespace, repo_root: Path, mode: str) -> list[str]:
    ps1 = Path(args.retention_guard_ps1) if args.retention_guard_ps1 else repo_root / "scripts/v21/run_v21_240_retention_policy_and_maintenance_guard.ps1"
    command = [
        "powershell", "-ExecutionPolicy", "Bypass", "-File", str(ps1),
        "-TopSize", str(args.top_size),
        "-RepoWarningMB", "800", "-RepoHardMB", "1000",
        "-TotalWarningMB", "2000", "-TotalHardMB", "2500",
        "-ArchiveWarningMB", "800", "-ArchiveHardMB", "1200",
        "-CacheWarningMB", "700", "-CacheHardMB", "1000",
        "-QuarantineWarningMB", "100", "-QuarantineHardMB", "300",
    ]
    if args.execute:
        command.append("-Execute")
    else:
        command.append("-DryRun")
    if mode == "post_run_audit":
        command.append("-AuditOnly")
    elif mode == "post_run_maintenance":
        command.extend([
            "-AllowArchiveCompress", "-AllowArchiveDuplicateDelete",
            "-AllowQuarantineVerifiedDelete", "-AllowCacheRetentionDelete",
            "-ArchiveCompressMinMB", "5", "-RepoLargeFileWarningMB", "10",
            "-RepoLargeFileHardMB", "50", "-CacheRetentionDays", "14",
            "-QuarantineRetentionDays", "7", "-RecentFileProtectionHours", "24",
        ])
    return command


def run_child(command: list[str], cwd: Path, runner: Callable[..., Any] | None = None) -> int:
    if runner is None:
        completed = subprocess.run(command, cwd=str(cwd), shell=False)
        return int(completed.returncode)
    result = runner(command, cwd=str(cwd), shell=False)
    return int(getattr(result, "returncode", result if isinstance(result, int) else 0))


def parse_v240_summary(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def map_guard_result(status: str) -> str:
    for row in guard_status_map():
        if row["v21_240_final_status"] == status:
            return row["guard_result"]
    return "FAIL" if status else "FAIL"


def hook_contract(repo_root: Path) -> dict[str, Any]:
    audit_command = "powershell -ExecutionPolicy Bypass -File scripts/v21/run_v21_240_retention_policy_and_maintenance_guard.ps1 -Execute -AuditOnly"
    maint_command = "powershell -ExecutionPolicy Bypass -File scripts/v21/run_v21_240_retention_policy_and_maintenance_guard.ps1 -Execute -AllowArchiveCompress -AllowArchiveDuplicateDelete -AllowQuarantineVerifiedDelete -AllowCacheRetentionDelete"
    return {
        "hook_name": "V21.241_DAILY_CHAIN_RETENTION_GUARD",
        "hook_version": "V21.241",
        "when_to_run": "after_daily_research_chain",
        "command_audit_mode": audit_command,
        "command_maintenance_mode": maint_command,
        "pass_statuses": ["PASS_V21_240_RETENTION_GUARD_OK", "PASS_V21_240_RETENTION_GUARD_MAINTENANCE_APPLIED"],
        "warn_statuses": ["WARN_V21_240_RETENTION_GUARD_WARN_BUDGET", "WARN_V21_240_RETENTION_GUARD_REPO_LARGE_FILE_VIOLATION"],
        "fail_statuses": ["FAIL_V21_240_RETENTION_GUARD_HARD_BUDGET_BREACH", "FAIL_V21_240_RETENTION_GUARD_ERROR"],
        "adoption_blocking_rules": "WARN or FAIL retention guard blocks official adoption review promotion",
        "broker_action_blocking_rules": "broker action remains blocked always",
        "budget_thresholds": {"repo_mb": [800, 1000], "archive_mb": [800, 1200], "cache_mb": [700, 1000], "quarantine_mb": [100, 300], "total_mb": [2000, 2500]},
        "required_v21_240_files": ["scripts/v21/v21_240_retention_policy_and_maintenance_guard.py", "scripts/v21/run_v21_240_retention_policy_and_maintenance_guard.ps1"],
        "output_summary_path": str(repo_root / OUT_REL / "v21_241_summary.json"),
    }


def run(args: argparse.Namespace, runner: Callable[..., Any] | None = None) -> dict[str, Any]:
    repo_root = args.repo_root.resolve()
    archive_root = args.archive_root.resolve()
    cache_root = args.cache_root.resolve()
    quarantine_root = args.quarantine_root.resolve()
    output_dir = args.output_dir or (repo_root / OUT_REL)
    output_dir.mkdir(parents=True, exist_ok=True)
    mode = args.retention_guard_mode
    candidates = discover_candidates(repo_root)
    skipped: list[dict[str, Any]] = []
    child_rows: list[dict[str, Any]] = []
    v240_script = Path(args.retention_guard_python) if args.retention_guard_python else repo_root / "scripts/v21/v21_240_retention_policy_and_maintenance_guard.py"
    v240_ps1 = Path(args.retention_guard_ps1) if args.retention_guard_ps1 else repo_root / "scripts/v21/run_v21_240_retention_policy_and_maintenance_guard.ps1"
    v240_found = v240_script.exists() and v240_ps1.exists()

    daily_attempted = False
    daily_exit: int | None = None
    if not args.skip_daily_chain and not args.discover_only and mode != "discover_only":
        if args.daily_chain_command:
            daily_attempted = True
            command = args.daily_chain_command if isinstance(args.daily_chain_command, list) else ["powershell", "-Command", args.daily_chain_command]
            daily_exit = run_child(command, repo_root, runner)
            child_rows.append({"child_name": "daily_chain_command", "command_line": " ".join(command), "attempted": True, "exit_code": daily_exit, "notes": "user supplied daily chain command"})
        elif args.daily_chain_wrapper:
            daily_attempted = True
            command = ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(args.daily_chain_wrapper)]
            daily_exit = run_child(command, repo_root, runner)
            child_rows.append({"child_name": "daily_chain_wrapper", "command_line": " ".join(command), "attempted": True, "exit_code": daily_exit, "notes": "user supplied daily chain wrapper"})

    guard_attempted = False
    guard_exit: int | None = None
    guard_status = ""
    guard_decision = ""
    guard_result = "NOT_RUN"
    v240_summary_path = repo_root / V240_SUMMARY
    if mode in {"post_run_audit", "post_run_maintenance"} and not args.discover_only:
        if not v240_found:
            skipped.append({"blocker_type": "V21_240_MISSING", "path": str(v240_ps1), "notes": "retention guard cannot be enforced"})
        elif mode == "post_run_maintenance" and not (args.execute and args.retention_guard_allow_maintenance):
            skipped.append({"blocker_type": "MAINTENANCE_NOT_ALLOWED", "path": str(v240_ps1), "notes": "post_run_maintenance requires --execute and --retention-guard-allow-maintenance"})
        else:
            guard_attempted = True
            command = build_v240_command(args, repo_root, mode)
            guard_exit = run_child(command, repo_root, runner)
            child_rows.append({"child_name": "retention_guard_v21_240", "command_line": " ".join(command), "attempted": True, "exit_code": guard_exit, "notes": mode})
            payload = parse_v240_summary(v240_summary_path)
            guard_status = str(payload.get("final_status", ""))
            guard_decision = str(payload.get("final_decision", ""))
            guard_result = map_guard_result(guard_status)
    elif mode in {"disabled", "discover_only"} or args.discover_only:
        guard_result = "NOT_RUN"

    daily_status = "SKIPPED" if args.skip_daily_chain else "NOT_ATTEMPTED" if not daily_attempted else "PASS" if daily_exit == 0 else "FAIL"
    guard_child_status = "NOT_ATTEMPTED" if not guard_attempted else "PASS" if guard_exit == 0 else "FAIL"
    final_status = PASS_DISCOVERY if (args.discover_only or mode == "discover_only") else PASS_READY
    final_decision = "DAILY_CHAIN_RETENTION_GUARD_READY_FOR_USE"
    if daily_attempted and daily_exit != 0:
        final_status = FAIL_CHILD
        final_decision = "DAILY_CHAIN_CHILD_FAILED_REVIEW_REQUIRED"
    elif mode in {"post_run_audit", "post_run_maintenance"} and not v240_found:
        final_status = FAIL_MISSING
        final_decision = "RETENTION_GUARD_MISSING_OR_FAILED_REVIEW_REQUIRED"
    elif guard_attempted and guard_result == "FAIL":
        if args.fail_on_retention_fail:
            final_status = FAIL_GUARD
            final_decision = "DAILY_CHAIN_RETENTION_GUARD_FAIL_BLOCK_RESEARCH_PROMOTION"
        else:
            final_status = WARN_GUARD_FAILED
            final_decision = "RETENTION_GUARD_MISSING_OR_FAILED_REVIEW_REQUIRED"
    elif guard_attempted and guard_result == "WARN" and args.warn_on_retention_warn:
        final_status = WARN_GUARD_REVIEW
        final_decision = "DAILY_CHAIN_RETENTION_GUARD_WARN_REVIEW_REQUIRED"
    elif args.discover_only or mode == "discover_only":
        final_decision = "DAILY_CHAIN_RETENTION_GUARD_DISCOVERY_READY_REVIEW_CANDIDATES"

    v240_payload = parse_v240_summary(v240_summary_path) if v240_summary_path.exists() else {}
    summary = {
        "final_status": final_status,
        "final_decision": final_decision,
        "repo_root": str(repo_root),
        "archive_root": str(archive_root),
        "cache_root": str(cache_root),
        "quarantine_root": str(quarantine_root),
        "execute_mode": args.execute,
        "audit_only": args.audit_only,
        "discover_only": args.discover_only or mode == "discover_only",
        "retention_guard_mode": mode,
        "daily_chain_command_provided": bool(args.daily_chain_command),
        "daily_chain_wrapper_provided": bool(args.daily_chain_wrapper),
        "skip_daily_chain": args.skip_daily_chain,
        "daily_chain_child_attempted": daily_attempted,
        "daily_chain_child_exit_code": daily_exit,
        "daily_chain_child_status": daily_status,
        "retention_guard_child_attempted": guard_attempted,
        "retention_guard_child_exit_code": guard_exit,
        "retention_guard_child_status": guard_child_status,
        "retention_guard_summary_path": str(v240_summary_path),
        "retention_guard_final_status": guard_status or v240_payload.get("final_status", ""),
        "retention_guard_final_decision": guard_decision or v240_payload.get("final_decision", ""),
        "guard_result": guard_result,
        "repo_budget_status": v240_payload.get("repo_budget_status", ""),
        "archive_budget_status": v240_payload.get("archive_budget_status", ""),
        "cache_budget_status": v240_payload.get("cache_budget_status", ""),
        "quarantine_budget_status": v240_payload.get("quarantine_budget_status", ""),
        "total_budget_status": v240_payload.get("total_budget_status", ""),
        "guard_violation_count": v240_payload.get("guard_violation_count", 0),
        "repo_large_file_warning_count": v240_payload.get("repo_large_file_warning_count", 0),
        "repo_large_file_hard_count": v240_payload.get("repo_large_file_hard_count", 0),
        "repo_unclassified_large_file_count": v240_payload.get("repo_unclassified_large_file_count", 0),
        "total_size_after_bytes": v240_payload.get("total_size_after_bytes", 0),
        "total_size_after_mb": round(float(v240_payload.get("total_size_after_bytes", 0)) / 1024 / 1024, 3),
        "daily_chain_research_outputs_allowed": bool(args.skip_daily_chain or daily_status == "PASS"),
        "retention_guard_blocks_official_adoption": guard_result in {"WARN", "FAIL"},
        "retention_guard_blocks_broker_action": True,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "market_data_fetch_performed": False,
        "yahoo_yfinance_used": False,
        "moomoo_futu_used": False,
        "repo_active_files_modified": False,
        "active_canonical_file_modified": False,
        "error_count": 1 if final_status.startswith("FAIL") else 0,
        "warning_count": 1 if final_status.startswith("WARN") else 0,
        "skipped_count": len(skipped),
    }

    write_csv(output_dir / "v21_241_discovered_daily_chain_candidates.csv", candidates, ["path", "relative_path", "classification", "selected_for_patch", "notes"])
    write_csv(output_dir / "v21_241_child_invocation_manifest.csv", child_rows, ["child_name", "command_line", "attempted", "exit_code", "notes"])
    write_csv(output_dir / "v21_241_retention_guard_status_mapping.csv", guard_status_map(), ["v21_240_final_status", "guard_result"])
    write_json(output_dir / "v21_241_daily_chain_hook_contract.json", hook_contract(repo_root))
    write_csv(output_dir / "v21_241_integration_readiness_report.csv", [{"check_name": "v21_240_found", "passed": v240_found, "severity": "ERROR" if not v240_found else "INFO", "notes": str(v240_ps1)}, {"check_name": "standalone_wrapper_created", "passed": True, "severity": "INFO", "notes": "run_v21_241_daily_chain_with_retention_guard.ps1"}], ["check_name", "passed", "severity", "notes"])
    write_csv(output_dir / "v21_241_skipped_blockers.csv", skipped, ["blocker_type", "path", "notes"])
    write_json(output_dir / "v21_241_summary.json", summary)
    report = "\n".join([STAGE, f"final_status={final_status}", f"final_decision={final_decision}", f"guard_result={guard_result}", "broker_action_allowed=False", "official_adoption_allowed=False"]) + "\n"
    (output_dir / "V21.241_daily_chain_retention_guard_integration_report.txt").write_text(report, encoding="utf-8")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", type=Path, default=default_repo_root())
    parser.add_argument("--archive-root", type=Path, default=default_archive_root())
    parser.add_argument("--cache-root", type=Path, default=default_cache_root())
    parser.add_argument("--quarantine-root", type=Path, default=default_quarantine_root())
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--execute", action="store_true", default=False)
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--audit-only", action="store_true", default=False)
    parser.add_argument("--discover-only", action="store_true", default=False)
    parser.add_argument("--skip-daily-chain", action="store_true", default=False)
    parser.add_argument("--daily-chain-command", default="")
    parser.add_argument("--daily-chain-wrapper", default="")
    parser.add_argument("--retention-guard-mode", choices=sorted(MODES), default="post_run_audit")
    parser.add_argument("--retention-guard-ps1", default="")
    parser.add_argument("--retention-guard-python", default="")
    parser.add_argument("--retention-guard-allow-maintenance", action="store_true", default=False)
    parser.add_argument("--fail-on-retention-fail", action="store_true", default=False)
    parser.add_argument("--warn-on-retention-warn", action="store_true", default=False)
    parser.add_argument("--top-size", type=int, default=300)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.dry_run:
        args.execute = False
    summary = run(args)
    print(str((args.output_dir or (args.repo_root / OUT_REL)) / "v21_241_summary.json"))
    return 1 if summary["final_status"].startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
