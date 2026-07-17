#!/usr/bin/env python
"""V22.046 daily research full-cycle controller R1."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REVISION = "V22.046_R1"
STAGE = "V22.046_DAILY_RESEARCH_FULL_CYCLE_CONTROLLER_R1"
OUT_REL = Path("outputs/v22") / STAGE

PASS_STATUS = "PASS_V22_046_DAILY_RESEARCH_FULL_CYCLE_COMPLETE"
PASS_DECISION = "DAILY_RESEARCH_REFRESH_AND_ARCHIVE_COMPLETE_RESEARCH_ONLY"
DRY_RUN_STATUS = "PASS_V22_046_DAILY_RESEARCH_FULL_CYCLE_DRY_RUN_VALIDATED"
DRY_RUN_DECISION = "DAILY_RESEARCH_FULL_CYCLE_VALIDATED_EXECUTE_REQUIRED"
FAIL_DECISION = "DAILY_RESEARCH_FULL_CYCLE_NOT_ACCEPTED"

RECOMMENDED_COMMAND = r".\scripts\v22\run_v22_046_daily_research_full_cycle_controller_r1.ps1 -Execute"
REFRESH_ENTRYPOINT_COMMAND = r".\scripts\v22\run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1 -Execute"
ARCHIVE_BUILDER_COMMAND = r".\scripts\v22\run_v22_045_daily_research_archive_and_pdf_report_r1.ps1 -Execute"

REFRESH_WRAPPER_REL = Path("scripts/v22/run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1")
ARCHIVE_WRAPPER_REL = Path("scripts/v22/run_v22_045_daily_research_archive_and_pdf_report_r1.ps1")
V22_044_SUMMARY_REL = Path("outputs/v22/V22.044_DAILY_SINGLE_ENTRYPOINT_FREEZE_AND_GUARD_R1/v22_044_summary.json")
V22_045_SUMMARY_REL = Path("outputs/v22/V22.045_DAILY_RESEARCH_ARCHIVE_AND_PDF_REPORT_R1/v22_045_summary.json")
REPORT_NAME = "V22.046_daily_full_cycle_report.md"

EXPECTED_V22_044_STATUS = "PASS_V22_044_DAILY_SINGLE_ENTRYPOINT_FROZEN"
EXPECTED_V22_044_DECISION = "V22_040_ACCEPTED_AS_ONLY_CURRENT_DAILY_RESEARCH_ENTRYPOINT"
EXPECTED_V22_045_STATUS = "PASS_V22_045_DAILY_RESEARCH_ARCHIVE_CREATED"
EXPECTED_V22_045_DECISION = "DAILY_RESEARCH_ARCHIVE_CREATED_RESEARCH_ONLY"

ChildRunner = Callable[[list[str], Path, Path, Path], int]


class ChildProcessLaunchError(RuntimeError):
    """Raised when a child process cannot be launched."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def date_text(value: Any) -> str:
    return str(value or "").strip()[:10]


def powershell_exe() -> str:
    return "powershell"


def child_command(repo_root: Path, wrapper_rel: Path) -> list[str]:
    return [powershell_exe(), "-ExecutionPolicy", "Bypass", "-File", str(repo_root / wrapper_rel), "-Execute"]


def default_child_runner(cmd: list[str], cwd: Path, stdout_path: Path, stderr_path: Path) -> int:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    proc: subprocess.Popen[Any] | None = None
    with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout_handle, stderr_path.open(
        "w", encoding="utf-8", errors="replace"
    ) as stderr_handle:
        try:
            proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=stdout_handle, stderr=stderr_handle)
        except OSError as exc:
            raise ChildProcessLaunchError(str(exc)) from exc
        try:
            return proc.wait()
        except KeyboardInterrupt:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
            raise


def base_summary(repo_root: Path, output_dir: Path, execute: bool) -> dict[str, Any]:
    logs_dir = output_dir / "logs"
    return {
        "revision": REVISION,
        "stage": STAGE,
        "run_mode": "EXECUTE" if execute else "DRY_RUN",
        "run_start_utc": utc_now(),
        "repo_root": str(repo_root),
        "output_dir": str(output_dir),
        "summary_path": str(output_dir / "v22_046_summary.json"),
        "report_path": str(output_dir / REPORT_NAME),
        "final_status": "",
        "final_decision": "",
        "full_cycle_accepted": False,
        "recommended_command": RECOMMENDED_COMMAND,
        "refresh_entrypoint_command": REFRESH_ENTRYPOINT_COMMAND,
        "archive_builder_command": ARCHIVE_BUILDER_COMMAND,
        "refresh_wrapper_path": str(repo_root / REFRESH_WRAPPER_REL),
        "archive_wrapper_path": str(repo_root / ARCHIVE_WRAPPER_REL),
        "v22_044_child_exit_code": None,
        "v22_045_child_exit_code": None,
        "v22_044_summary_path": str(repo_root / V22_044_SUMMARY_REL),
        "v22_045_summary_path": str(repo_root / V22_045_SUMMARY_REL),
        "v22_044_stdout_log_path": str(logs_dir / "v22_044_stdout.log"),
        "v22_044_stderr_log_path": str(logs_dir / "v22_044_stderr.log"),
        "v22_045_stdout_log_path": str(logs_dir / "v22_045_stdout.log"),
        "v22_045_stderr_log_path": str(logs_dir / "v22_045_stderr.log"),
        "v22_044_start_utc": "",
        "v22_044_end_utc": "",
        "v22_044_duration_seconds": None,
        "v22_045_start_utc": "",
        "v22_045_end_utc": "",
        "v22_045_duration_seconds": None,
        "v22_044_final_status": "",
        "v22_045_final_status": "",
        "latest_research_date": "",
        "canonical_latest_date": "",
        "abcde_latest_date": "",
        "dram_latest_price_date": "",
        "same_date_comparable_all_strategies": False,
        "data_gap_days": None,
        "archive_root": "",
        "archive_zip_path": "",
        "markdown_report_path": "",
        "pdf_report_path": "",
        "archive_manifest_csv_path": "",
        "archive_manifest_json_path": "",
        "source_inventory_path": "",
        "copied_file_count": 0,
        "total_archived_bytes": 0,
        "warning_count": 0,
        "warnings": [],
        "research_only": True,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "factor_promotion_allowed": False,
        "direct_market_data_fetch_attempted": False,
        "direct_v22_040_invocation_attempted": False,
        "direct_child_strategy_invocation_attempted": False,
        "source_files_mutated": False,
        "interrupted": False,
        "interrupted_stage": "",
        "active_child_command": "",
        "child_process_launch_error": "",
        "hard_gate_passed": False,
        "failed_gate_names": [],
        "child_execution_order": [],
        "v22_045_ran_after_v22_044_passed": False,
    }


def persist(output_dir: Path, summary: dict[str, Any]) -> None:
    write_json_atomic(output_dir / "v22_046_summary.json", summary)


def wrapper_gate(repo_root: Path, summary: dict[str, Any]) -> str | None:
    if not (repo_root / REFRESH_WRAPPER_REL).exists():
        summary["failed_gate_names"] = ["refresh_wrapper_exists"]
        return "FAIL_V22_046_REFRESH_WRAPPER_MISSING"
    if not (repo_root / ARCHIVE_WRAPPER_REL).exists():
        summary["failed_gate_names"] = ["archive_wrapper_exists"]
        return "FAIL_V22_046_ARCHIVE_WRAPPER_MISSING"
    return None


def validate_refresh(summary: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    failed: list[str] = []
    if payload.get("final_status") != EXPECTED_V22_044_STATUS:
        failed.append("v22_044_final_status")
    if payload.get("final_decision") != EXPECTED_V22_044_DECISION:
        failed.append("v22_044_final_decision")
    child_command_text = str(payload.get("child_v22_040_command") or payload.get("accepted_child_orchestrator_command") or "")
    expected_child_wrapper = "run_" + "v22_040" + "_daily_moomoo_oneclick_refresh_orchestrator_r1.ps1"
    if expected_child_wrapper not in child_command_text.lower():
        failed.append("v22_044_accepted_child_command_points_to_v22_040")
    canonical = date_text(payload.get("canonical_latest_date"))
    abcde = date_text(payload.get("abcde_latest_date"))
    dram = date_text(payload.get("dram_latest_price_date"))
    summary["canonical_latest_date"] = canonical
    summary["abcde_latest_date"] = abcde
    summary["dram_latest_price_date"] = dram
    summary["latest_research_date"] = canonical or abcde or dram
    summary["same_date_comparable_all_strategies"] = payload.get("same_date_comparable_all_strategies") is True
    summary["data_gap_days"] = payload.get("data_gap_days")
    summary["broker_action_allowed"] = payload.get("broker_action_allowed")
    summary["official_adoption_allowed"] = payload.get("official_adoption_allowed")
    summary["factor_promotion_allowed"] = payload.get("factor_promotion_allowed", False)
    if not (canonical and abcde and dram and canonical == abcde == dram):
        failed.append("v22_044_dates_aligned")
    if payload.get("same_date_comparable_all_strategies") is not True:
        failed.append("v22_044_same_date_comparable_all_strategies")
    if payload.get("data_gap_days") != 0:
        failed.append("v22_044_data_gap_days_zero")
    if payload.get("broker_action_allowed") is not False:
        failed.append("v22_044_broker_action_allowed_false")
    if payload.get("official_adoption_allowed") is not False:
        failed.append("v22_044_official_adoption_allowed_false")
    return failed


def path_exists(value: Any) -> bool:
    return bool(value) and Path(str(value)).exists()


def validate_archive(summary: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    failed: list[str] = []
    if payload.get("final_status") != EXPECTED_V22_045_STATUS:
        failed.append("v22_045_final_status")
    if payload.get("final_decision") != EXPECTED_V22_045_DECISION:
        failed.append("v22_045_final_decision")
    if payload.get("archive_accepted") is not True:
        failed.append("v22_045_archive_accepted")
    for field in [
        "archive_zip_path",
        "markdown_report_path",
        "pdf_report_path",
        "archive_manifest_csv_path",
        "archive_manifest_json_path",
        "source_inventory_path",
    ]:
        if not path_exists(payload.get(field)):
            failed.append(f"v22_045_{field}_exists")
    if date_text(payload.get("latest_research_date")) != date_text(summary.get("latest_research_date")):
        failed.append("v22_045_latest_research_date_matches_v22_044")
    if payload.get("broker_action_allowed") is not False:
        failed.append("v22_045_broker_action_allowed_false")
    if payload.get("official_adoption_allowed") is not False:
        failed.append("v22_045_official_adoption_allowed_false")
    if payload.get("direct_market_data_fetch_attempted") is not False:
        failed.append("v22_045_direct_market_data_fetch_attempted_false")
    if payload.get("direct_child_strategy_invocation_attempted") is not False:
        failed.append("v22_045_direct_child_strategy_invocation_attempted_false")
    if payload.get("source_files_mutated") is not False:
        failed.append("v22_045_source_files_mutated_false")
    for field in [
        "archive_root",
        "archive_zip_path",
        "markdown_report_path",
        "pdf_report_path",
        "archive_manifest_csv_path",
        "archive_manifest_json_path",
        "source_inventory_path",
        "copied_file_count",
        "total_archived_bytes",
        "warning_count",
        "warnings",
    ]:
        summary[field] = payload.get(field, summary.get(field))
    return failed


def fail_status_from_refresh(failed: list[str]) -> str:
    if any(name.endswith("broker_action_allowed_false") or name.endswith("official_adoption_allowed_false") for name in failed):
        return "FAIL_V22_046_RESEARCH_ONLY_GATE_FAILED"
    return "FAIL_V22_046_REFRESH_GATE_FAILED"


def fail_status_from_archive(failed: list[str]) -> str:
    if "v22_045_latest_research_date_matches_v22_044" in failed:
        return "FAIL_V22_046_DATE_MISMATCH_BETWEEN_REFRESH_AND_ARCHIVE"
    if any(
        name in failed
        for name in [
            "v22_045_broker_action_allowed_false",
            "v22_045_official_adoption_allowed_false",
            "v22_045_direct_market_data_fetch_attempted_false",
            "v22_045_direct_child_strategy_invocation_attempted_false",
            "v22_045_source_files_mutated_false",
        ]
    ):
        return "FAIL_V22_046_RESEARCH_ONLY_GATE_FAILED"
    return "FAIL_V22_046_ARCHIVE_GATE_FAILED"


def run_child(
    summary: dict[str, Any],
    repo_root: Path,
    key: str,
    command: list[str],
    stdout_path: Path,
    stderr_path: Path,
    runner: ChildRunner,
) -> int:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    summary[f"{key}_start_utc"] = utc_now()
    summary["active_child_command"] = " ".join(command)
    start = time.monotonic()
    try:
        exit_code = runner(command, repo_root, stdout_path, stderr_path)
    except BaseException:
        summary[f"{key}_duration_seconds"] = round(time.monotonic() - start, 3)
        summary[f"{key}_end_utc"] = utc_now()
        raise
    else:
        summary[f"{key}_duration_seconds"] = round(time.monotonic() - start, 3)
        summary[f"{key}_end_utc"] = utc_now()
        summary[f"{key}_child_exit_code"] = exit_code
        summary["active_child_command"] = ""
        return exit_code


def mark_interrupted(summary: dict[str, Any], stage: str) -> None:
    summary["final_status"] = "FAIL_V22_046_INTERRUPTED_BY_USER"
    summary["final_decision"] = "DAILY_RESEARCH_FULL_CYCLE_INTERRUPTED_NOT_ACCEPTED"
    summary["full_cycle_accepted"] = False
    summary["interrupted"] = True
    summary["interrupted_stage"] = stage
    summary["hard_gate_passed"] = False
    summary["failed_gate_names"] = ["interrupted_by_user"]


def mark_launch_failed(summary: dict[str, Any], stage: str, exc: BaseException) -> None:
    summary["final_status"] = "FAIL_V22_046_CHILD_PROCESS_LAUNCH_FAILED"
    summary["final_decision"] = FAIL_DECISION
    summary["full_cycle_accepted"] = False
    summary["interrupted_stage"] = stage
    summary["child_process_launch_error"] = str(exc)
    summary["hard_gate_passed"] = False
    summary["failed_gate_names"] = ["child_process_launch_failed"]


def report_markdown(summary: dict[str, Any]) -> str:
    warnings = summary.get("warnings") or []
    warning_lines = [f"- {warning}" for warning in warnings] or ["- none"]
    return "\n".join(
        [
            "# Daily Research Full Cycle Report",
            "",
            f"Revision: `{REVISION}`",
            f"Final status: `{summary['final_status']}`",
            f"Final decision: `{summary['final_decision']}`",
            f"Recommended full-cycle command: `{RECOMMENDED_COMMAND}`",
            "",
            "## Refresh Stage",
            f"- V22.044 command: `{REFRESH_ENTRYPOINT_COMMAND}`",
            f"- V22.044 exit code: `{summary['v22_044_child_exit_code']}`",
            f"- V22.044 final status: `{summary['v22_044_final_status']}`",
            f"- V22.044 summary path: `{summary['v22_044_summary_path']}`",
            "",
            "## Archive Stage",
            f"- V22.045 command: `{ARCHIVE_BUILDER_COMMAND}`",
            f"- V22.045 exit code: `{summary['v22_045_child_exit_code']}`",
            f"- V22.045 final status: `{summary['v22_045_final_status']}`",
            f"- V22.045 summary path: `{summary['v22_045_summary_path']}`",
            "",
            "## Date Alignment",
            f"- canonical latest date: `{summary['canonical_latest_date']}`",
            f"- ABCDE latest date: `{summary['abcde_latest_date']}`",
            f"- DRAM latest price date: `{summary['dram_latest_price_date']}`",
            f"- latest research date: `{summary['latest_research_date']}`",
            f"- data gap days: `{summary['data_gap_days']}`",
            "",
            "## Archive Outputs",
            f"- archive root: `{summary['archive_root']}`",
            f"- archive zip: `{summary['archive_zip_path']}`",
            f"- Markdown report: `{summary['markdown_report_path']}`",
            f"- PDF report: `{summary['pdf_report_path']}`",
            f"- manifest CSV: `{summary['archive_manifest_csv_path']}`",
            f"- manifest JSON: `{summary['archive_manifest_json_path']}`",
            f"- source inventory: `{summary['source_inventory_path']}`",
            "",
            "## Warning Summary",
            *warning_lines,
            "",
            "## Safety Gates",
            "- research only",
            "- broker action blocked",
            "- official adoption blocked",
            "- factor promotion blocked",
            "- no direct market data fetch",
            "- no direct V22.040 invocation",
            "- no direct child strategy invocation",
            "- no source mutation",
            "",
            "## Final Conclusion",
            f"`{summary['final_decision']}`",
            "",
        ]
    )


def finalize(output_dir: Path, summary: dict[str, Any]) -> dict[str, Any]:
    summary["warning_count"] = len(summary.get("warnings") or [])
    summary["run_end_utc"] = utc_now()
    persist(output_dir, summary)
    (output_dir / REPORT_NAME).write_text(report_markdown(summary), encoding="utf-8")
    return summary


def run(repo_root: Path, execute: bool = False, child_runner: ChildRunner | None = None) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = repo_root / OUT_REL
    (output_dir / "logs").mkdir(parents=True, exist_ok=True)
    summary = base_summary(repo_root, output_dir, execute)

    wrapper_fail = wrapper_gate(repo_root, summary)
    if wrapper_fail:
        summary["final_status"] = wrapper_fail
        summary["final_decision"] = FAIL_DECISION
        return finalize(output_dir, summary)

    if not execute:
        summary["final_status"] = DRY_RUN_STATUS
        summary["final_decision"] = DRY_RUN_DECISION
        summary["hard_gate_passed"] = True
        return finalize(output_dir, summary)

    runner = child_runner or default_child_runner
    print("starting V22.044 refresh stage", flush=True)
    try:
        refresh_exit = run_child(
            summary,
            repo_root,
            "v22_044",
            child_command(repo_root, REFRESH_WRAPPER_REL),
            Path(summary["v22_044_stdout_log_path"]),
            Path(summary["v22_044_stderr_log_path"]),
            runner,
        )
    except KeyboardInterrupt:
        summary["child_execution_order"].append("V22.044")
        mark_interrupted(summary, "V22.044")
        return finalize(output_dir, summary)
    except ChildProcessLaunchError as exc:
        summary["child_execution_order"].append("V22.044")
        mark_launch_failed(summary, "V22.044", exc)
        return finalize(output_dir, summary)
    print(f"completed V22.044 refresh stage with exit code {refresh_exit}", flush=True)
    summary["child_execution_order"].append("V22.044")
    if refresh_exit != 0:
        v22_044_path = repo_root / V22_044_SUMMARY_REL
        if v22_044_path.exists():
            v22_044 = read_json(v22_044_path)
            summary["v22_044_final_status"] = v22_044.get("final_status", "")
            summary["canonical_latest_date"] = date_text(v22_044.get("canonical_latest_date"))
            summary["abcde_latest_date"] = date_text(v22_044.get("abcde_latest_date"))
            summary["dram_latest_price_date"] = date_text(v22_044.get("dram_latest_price_date"))
            summary["latest_research_date"] = (
                summary["canonical_latest_date"] or summary["abcde_latest_date"] or summary["dram_latest_price_date"]
            )
            summary["same_date_comparable_all_strategies"] = v22_044.get("same_date_comparable_all_strategies") is True
            summary["data_gap_days"] = v22_044.get("data_gap_days")
        summary["final_status"] = "FAIL_V22_046_REFRESH_CHILD_EXIT_NONZERO"
        summary["final_decision"] = FAIL_DECISION
        summary["failed_gate_names"] = ["v22_044_child_exit_code_zero"]
        return finalize(output_dir, summary)

    v22_044_path = repo_root / V22_044_SUMMARY_REL
    if not v22_044_path.exists():
        summary["final_status"] = "FAIL_V22_046_REFRESH_SUMMARY_MISSING"
        summary["final_decision"] = FAIL_DECISION
        summary["failed_gate_names"] = ["v22_044_summary_exists"]
        return finalize(output_dir, summary)
    v22_044 = read_json(v22_044_path)
    summary["v22_044_final_status"] = v22_044.get("final_status", "")
    refresh_failed = validate_refresh(summary, v22_044)
    if refresh_failed:
        summary["final_status"] = fail_status_from_refresh(refresh_failed)
        summary["final_decision"] = FAIL_DECISION
        summary["failed_gate_names"] = refresh_failed
        return finalize(output_dir, summary)

    print("starting V22.045 archive stage", flush=True)
    try:
        archive_exit = run_child(
            summary,
            repo_root,
            "v22_045",
            child_command(repo_root, ARCHIVE_WRAPPER_REL),
            Path(summary["v22_045_stdout_log_path"]),
            Path(summary["v22_045_stderr_log_path"]),
            runner,
        )
    except KeyboardInterrupt:
        summary["child_execution_order"].append("V22.045")
        summary["v22_045_ran_after_v22_044_passed"] = True
        mark_interrupted(summary, "V22.045")
        return finalize(output_dir, summary)
    except ChildProcessLaunchError as exc:
        summary["child_execution_order"].append("V22.045")
        summary["v22_045_ran_after_v22_044_passed"] = True
        mark_launch_failed(summary, "V22.045", exc)
        return finalize(output_dir, summary)
    print(f"completed V22.045 archive stage with exit code {archive_exit}", flush=True)
    summary["child_execution_order"].append("V22.045")
    summary["v22_045_ran_after_v22_044_passed"] = True
    if archive_exit != 0:
        summary["final_status"] = "FAIL_V22_046_ARCHIVE_CHILD_EXIT_NONZERO"
        summary["final_decision"] = FAIL_DECISION
        summary["failed_gate_names"] = ["v22_045_child_exit_code_zero"]
        return finalize(output_dir, summary)

    v22_045_path = repo_root / V22_045_SUMMARY_REL
    if not v22_045_path.exists():
        summary["final_status"] = "FAIL_V22_046_ARCHIVE_SUMMARY_MISSING"
        summary["final_decision"] = FAIL_DECISION
        summary["failed_gate_names"] = ["v22_045_summary_exists"]
        return finalize(output_dir, summary)
    v22_045 = read_json(v22_045_path)
    summary["v22_045_final_status"] = v22_045.get("final_status", "")
    archive_failed = validate_archive(summary, v22_045)
    if archive_failed:
        summary["final_status"] = fail_status_from_archive(archive_failed)
        summary["final_decision"] = FAIL_DECISION
        summary["failed_gate_names"] = archive_failed
        return finalize(output_dir, summary)

    summary["final_status"] = PASS_STATUS
    summary["final_decision"] = PASS_DECISION
    summary["full_cycle_accepted"] = True
    summary["hard_gate_passed"] = True
    summary["failed_gate_names"] = []
    return finalize(output_dir, summary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    payload = run(args.repo_root, execute=args.execute)
    for key in [
        "final_status",
        "final_decision",
        "full_cycle_accepted",
        "recommended_command",
        "v22_044_child_exit_code",
        "v22_045_child_exit_code",
        "v22_044_summary_path",
        "v22_045_summary_path",
        "latest_research_date",
        "canonical_latest_date",
        "abcde_latest_date",
        "dram_latest_price_date",
        "same_date_comparable_all_strategies",
        "data_gap_days",
        "archive_root",
        "archive_zip_path",
        "markdown_report_path",
        "pdf_report_path",
        "archive_manifest_csv_path",
        "archive_manifest_json_path",
        "source_inventory_path",
        "copied_file_count",
        "total_archived_bytes",
        "warning_count",
        "broker_action_allowed",
        "official_adoption_allowed",
        "factor_promotion_allowed",
        "direct_market_data_fetch_attempted",
        "direct_v22_040_invocation_attempted",
        "direct_child_strategy_invocation_attempted",
        "source_files_mutated",
        "v22_044_stdout_log_path",
        "v22_044_stderr_log_path",
        "v22_045_stdout_log_path",
        "v22_045_stderr_log_path",
        "interrupted",
        "interrupted_stage",
    ]:
        print(f"{key}={payload.get(key)}")
    print("warnings=" + json.dumps(payload.get("warnings", []), ensure_ascii=False))
    print("failed_gate_names=" + json.dumps(payload.get("failed_gate_names", []), ensure_ascii=False))
    return 0 if str(payload.get("final_status", "")).startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
