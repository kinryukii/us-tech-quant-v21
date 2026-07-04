#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import subprocess
from pathlib import Path
from typing import Any, Callable

STAGE = "V21.261_DAILY_CHAIN_RETENTION_ENFORCEMENT_WIRING_R1"
OUT_REL = Path("outputs/v21") / STAGE
DAILY_WRAPPER_REL = Path("scripts/v21/run_v21_256_daily_chain_master_wrapper_with_context_r1.ps1")
RETENTION_WRAPPER_REL = Path("scripts/v21/run_v21_260_retention_enforced_output_guard_r1.ps1")
V256_SUMMARY_REL = Path("outputs/v21/V21.256_DAILY_CHAIN_MASTER_WRAPPER_WITH_CONTEXT_R1/v21_256_summary.json")
V260_SUMMARY_REL = Path("outputs/v21/V21.260_RETENTION_ENFORCED_OUTPUT_GUARD_R1/v21_260_summary.json")
GATES = {
    "research_only": True,
    "broker_action_allowed": False,
    "official_adoption_allowed": False,
    "factor_promotion_allowed": False,
    "market_data_fetch_allowed": False,
}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def default_runner(cmd: list[str], cwd: Path, log_path: Path) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text((proc.stdout or "") + ("\nSTDERR:\n" + proc.stderr if proc.stderr else ""), encoding="utf-8")
    return proc.returncode, (proc.stderr or proc.stdout or "").strip()


def wrapper_manifest(repo: Path) -> list[dict[str, Any]]:
    daily = repo / DAILY_WRAPPER_REL
    retention = repo / RETENTION_WRAPPER_REL
    return [
        {"component": "accepted_daily_entrypoint", "path": str(daily), "exists": daily.exists(), "intended_mode": "Execute", "command": f"powershell -ExecutionPolicy Bypass -File {daily} -Execute"},
        {"component": "retention_execute_guard", "path": str(retention), "exists": retention.exists(), "intended_mode": "Execute", "command": f"powershell -ExecutionPolicy Bypass -File {retention} -Execute -LargeFileThresholdMB 5 -IncludeV20 -IncludeShared"},
        {"component": "retention_verify_guard", "path": str(retention), "exists": retention.exists(), "intended_mode": "DryRunVerify", "command": f"powershell -ExecutionPolicy Bypass -File {retention} -DryRun -LargeFileThresholdMB 5 -IncludeV20 -IncludeShared -FailOnViolation"},
    ]


def step_commands(repo: Path) -> list[tuple[str, list[str]]]:
    daily = repo / DAILY_WRAPPER_REL
    retention = repo / RETENTION_WRAPPER_REL
    return [
        ("daily_chain_execute", ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(daily), "-Execute"]),
        ("retention_enforce_execute", ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(retention), "-Execute", "-LargeFileThresholdMB", "5", "-IncludeV20", "-IncludeShared"]),
        ("retention_enforce_verify", ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(retention), "-DryRun", "-LargeFileThresholdMB", "5", "-IncludeV20", "-IncludeShared", "-FailOnViolation"]),
    ]


def is_pass(status: str) -> bool:
    return str(status).startswith("PASS")


def is_warn(status: str) -> bool:
    return str(status).startswith("WARN")


def is_fail(status: str) -> bool:
    return str(status).startswith("FAIL")


def execute_steps(repo: Path, out: Path, runner: Callable[[list[str], Path, Path], tuple[int, str]] | None) -> list[dict[str, Any]]:
    runner = runner or default_runner
    rows: list[dict[str, Any]] = []
    for idx, (name, cmd) in enumerate(step_commands(repo), 1):
        log_path = out / "logs" / f"{idx:02d}_{name}.log"
        code, msg = runner(cmd, repo, log_path)
        daily_summary = read_json(repo / V256_SUMMARY_REL)
        retention_summary = read_json(repo / V260_SUMMARY_REL)
        if name == "daily_chain_execute":
            status = daily_summary.get("final_status", "")
            decision = daily_summary.get("final_decision", "")
            output_root = str((repo / V256_SUMMARY_REL).parent)
        else:
            status = retention_summary.get("final_status", "")
            decision = retention_summary.get("final_decision", "")
            output_root = str((repo / V260_SUMMARY_REL).parent)
        rows.append({
            "step_order": idx,
            "step_name": name,
            "attempted": True,
            "exit_code": code,
            "succeeded": code == 0 and not is_fail(status),
            "final_status": status,
            "final_decision": decision,
            "output_root": output_root,
            "log_path": str(log_path),
            "error_message": "" if code == 0 and not is_fail(status) else msg,
        })
        if code != 0 or is_fail(status):
            break
    return rows


def dryrun_steps(repo: Path) -> list[dict[str, Any]]:
    v260 = read_json(repo / V260_SUMMARY_REL)
    status = v260.get("final_status", "")
    return [{
        "step_order": 0,
        "step_name": "dryrun_existing_retention_status_check",
        "attempted": False,
        "exit_code": "",
        "succeeded": bool(v260) and not is_fail(status),
        "final_status": status,
        "final_decision": v260.get("final_decision", ""),
        "output_root": str((repo / V260_SUMMARY_REL).parent),
        "log_path": "",
        "error_message": "" if v260 else "V21.260 summary not found; wiring still validates wrappers only.",
    }]


def build_summary(repo: Path, out: Path, mode: str, wiring: list[dict[str, Any]], steps: list[dict[str, Any]]) -> dict[str, Any]:
    missing = [r for r in wiring if not r["exists"]]
    daily_summary = read_json(repo / V256_SUMMARY_REL)
    retention_summary = read_json(repo / V260_SUMMARY_REL)
    daily_status = daily_summary.get("final_status", "")
    retention_status = retention_summary.get("final_status", "")
    warning = any(is_warn(r.get("final_status", "")) for r in steps) or is_warn(retention_status)
    failed = bool(missing) or any((r.get("attempted") is True and (r.get("exit_code") not in (0, "0") or is_fail(r.get("final_status", "")))) for r in steps)
    if failed:
        status = "FAIL_V21_261_DAILY_CHAIN_OR_RETENTION_FAILED"
    elif warning:
        status = "WARN_V21_261_DAILY_CHAIN_DONE_RETENTION_WARN"
    else:
        status = "PASS_V21_261_DAILY_CHAIN_RETENTION_ENFORCED"
    return {
        "final_status": status,
        "final_decision": "DAILY_CHAIN_RETENTION_ENFORCEMENT_WIRED" if status.startswith("PASS") else "DAILY_CHAIN_RETENTION_ENFORCEMENT_REVIEW_REQUIRED",
        "run_mode": mode,
        "accepted_daily_wrapper_exists": (repo / DAILY_WRAPPER_REL).exists(),
        "retention_wrapper_exists": (repo / RETENTION_WRAPPER_REL).exists(),
        "daily_chain_final_status": daily_status,
        "daily_chain_final_decision": daily_summary.get("final_decision", ""),
        "retention_final_status": retention_status,
        "retention_final_decision": retention_summary.get("final_decision", ""),
        "retention_verify_clean": is_pass(retention_status),
        "child_step_count": len(steps),
        "child_step_attempted_count": sum(1 for r in steps if r.get("attempted") is True),
        "child_step_succeeded_count": sum(1 for r in steps if r.get("succeeded") is True),
        "output_root": str(out),
        "error_count": 1 if failed else 0,
        "warning_count": 1 if warning and not failed else 0,
        **GATES,
    }


def write_outputs(out: Path, wiring: list[dict[str, Any]], steps: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "daily_chain_retention_wiring_manifest.csv", wiring, ["component", "path", "exists", "intended_mode", "command"])
    write_csv(out / "post_run_retention_enforcement_manifest.csv", steps, ["step_order", "step_name", "attempted", "exit_code", "succeeded", "final_status", "final_decision", "output_root", "log_path", "error_message"])
    write_json(out / "v21_261_summary.json", summary)
    report = "\n".join([
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"run_mode={summary['run_mode']}",
        f"daily_chain_final_status={summary['daily_chain_final_status']}",
        f"retention_final_status={summary['retention_final_status']}",
        "research_only=True",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
        "factor_promotion_allowed=False",
    ]) + "\n"
    (out / "v21_261_daily_chain_retention_wiring_report.txt").write_text(report, encoding="utf-8")


def run(repo: Path, output_dir: Path | None = None, mode: str = "DryRun", runner: Callable[[list[str], Path, Path], tuple[int, str]] | None = None) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    wiring = wrapper_manifest(repo)
    if mode == "Execute" and all(r["exists"] for r in wiring):
        steps = execute_steps(repo, out, runner)
    else:
        steps = dryrun_steps(repo)
    summary = build_summary(repo, out, mode, wiring, steps)
    write_outputs(out, wiring, steps, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--mode", choices=["DryRun", "Execute"], default="DryRun")
    args = p.parse_args(argv)
    summary = run(args.repo_root.resolve(), args.output_dir, args.mode)
    for key in ["final_status", "final_decision", "run_mode", "accepted_daily_wrapper_exists", "retention_wrapper_exists", "daily_chain_final_status", "retention_final_status", "retention_verify_clean", "child_step_attempted_count", "child_step_succeeded_count", "research_only", "broker_action_allowed", "official_adoption_allowed", "factor_promotion_allowed", "market_data_fetch_allowed", "output_root", "warning_count", "error_count"]:
        print(f"{key}={summary.get(key)}")
    return 1 if str(summary.get("final_status", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
