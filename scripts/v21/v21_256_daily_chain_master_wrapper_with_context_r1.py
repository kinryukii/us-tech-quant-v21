#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

STAGE = "V21.256_DAILY_CHAIN_MASTER_WRAPPER_WITH_CONTEXT_R1"
OUT_REL = Path("outputs/v21") / STAGE
V241_REL = Path("outputs/v21/V21.241_DAILY_CHAIN_RETENTION_GUARD_INTEGRATION")
V253_REL = Path("outputs/v21/V21.253_DAILY_RESEARCH_CHAIN_CONTEXT_BLOCK_INTEGRATION_R1")
V254_REL = Path("outputs/v21/V21.254_DAILY_CHAIN_WRAPPER_CONTEXT_BLOCK_APPEND_R1")
GATES = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "factor_promotion_allowed": False,
    "weight_update_allowed": False,
    "ranking_mutation_allowed": False,
    "trade_plan_mutation_allowed": False,
    "child_output_mutation_allowed": False,
    "automatic_ticker_replacement_allowed": False,
    "automatic_position_increase_allowed": False,
    "automatic_trade_trigger_allowed": False,
    "protected_outputs_modified": False,
    "market_data_fetch_allowed": False,
}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def root(repo: Path, rel: Path) -> Path:
    return rel if rel.is_absolute() else repo / rel


def accepted_daily_wrapper(repo: Path) -> Path | None:
    preferred = repo / "scripts/v21/run_v21_241_daily_chain_retention_guard_integration.ps1"
    fallback = repo / "scripts/v21/run_v21_241_daily_chain_with_retention_guard.ps1"
    if preferred.exists():
        return preferred
    if fallback.exists():
        return fallback
    return None


def wrapper_paths(repo: Path) -> dict[str, Path | None]:
    return {
        "DAILY_CHAIN_RETENTION_GUARD": accepted_daily_wrapper(repo),
        "V21_253_CONTEXT_BLOCK": repo / "scripts/v21/run_v21_253_daily_research_chain_context_block_integration_r1.ps1",
        "V21_254_CONTEXT_APPEND": repo / "scripts/v21/run_v21_254_daily_chain_wrapper_context_block_append_r1.ps1",
    }


def default_runner(cmd: list[str], cwd: Path, log_path: Path) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text((proc.stdout or "") + ("\nSTDERR:\n" + proc.stderr if proc.stderr else ""), encoding="utf-8")
    return proc.returncode, (proc.stderr or proc.stdout or "").strip()


def child_commands(repo: Path, out: Path) -> dict[str, list[str]]:
    daily = accepted_daily_wrapper(repo)
    return {
        "DAILY_CHAIN_RETENTION_GUARD": ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(daily), "-AuditOnly", "-RetentionGuardMode", "discover_only"] if daily else [],
        "V21_253_CONTEXT_BLOCK": ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(repo / "scripts/v21/run_v21_253_daily_research_chain_context_block_integration_r1.ps1")],
        "V21_254_CONTEXT_APPEND": ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(repo / "scripts/v21/run_v21_254_daily_chain_wrapper_context_block_append_r1.ps1")],
    }


def load_child_summaries(repo: Path) -> dict[str, dict[str, Any]]:
    return {
        "DAILY_CHAIN_RETENTION_GUARD": read_json(root(repo, V241_REL) / "v21_241_summary.json"),
        "V21_253_CONTEXT_BLOCK": read_json(root(repo, V253_REL) / "v21_253_summary.json"),
        "V21_254_CONTEXT_APPEND": read_json(root(repo, V254_REL) / "v21_254_summary.json"),
    }


def run_children(repo: Path, out: Path, runner: Callable[[list[str], Path, Path], tuple[int, str]] | None) -> list[dict[str, Any]]:
    runner = runner or default_runner
    commands = child_commands(repo, out)
    ledger: list[dict[str, Any]] = []
    for stage, cmd in commands.items():
        log_path = out / "logs" / f"{stage}.log"
        if not cmd:
            ledger.append({"stage_name": stage, "attempted": True, "succeeded": False, "final_status": "", "final_decision": "", "output_root": "", "error_message": "wrapper_missing"})
            continue
        code, msg = runner(cmd, repo, log_path)
        summaries = load_child_summaries(repo)
        summary = summaries.get(stage, {})
        succeeded = code == 0 and not str(summary.get("final_status", "")).startswith("FAIL")
        ledger.append({"stage_name": stage, "attempted": True, "succeeded": succeeded, "final_status": summary.get("final_status", ""), "final_decision": summary.get("final_decision", ""), "output_root": str(root(repo, stage_rel(stage))), "error_message": "" if succeeded else msg})
    return ledger


def stage_rel(stage: str) -> Path:
    if stage == "DAILY_CHAIN_RETENTION_GUARD":
        return V241_REL
    if stage == "V21_253_CONTEXT_BLOCK":
        return V253_REL
    return V254_REL


def audit_ledger(repo: Path) -> list[dict[str, Any]]:
    summaries = load_child_summaries(repo)
    rows = []
    for stage, summary in summaries.items():
        rows.append({"stage_name": stage, "attempted": False, "succeeded": bool(summary) and not str(summary.get("final_status", "")).startswith("FAIL"), "final_status": summary.get("final_status", ""), "final_decision": summary.get("final_decision", ""), "output_root": str(root(repo, stage_rel(stage))), "error_message": "" if summary else "latest_output_missing"})
    return rows


def no_mutation_audit() -> list[dict[str, Any]]:
    rows = [
        ("canonical_snapshots_not_mutated_by_v21_256", "protected_outputs_modified"),
        ("official_rankings_not_mutated_by_v21_256", "ranking_mutation_allowed"),
        ("factor_weights_not_mutated_by_v21_256", "weight_update_allowed"),
        ("broker_files_not_mutated_by_v21_256", "broker_action_allowed"),
        ("dram_trade_plans_not_mutated_by_v21_256", "trade_plan_mutation_allowed"),
        ("child_outputs_not_mutated_by_v21_256_itself", "child_output_mutation_allowed"),
    ]
    return [{"audit_item": item, "observed_allowed": GATES[field], "expected_allowed": False, "passed": GATES[field] is False, "field": field} for item, field in rows]


def gate_audit(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"gate_name": k, "expected": v, "observed": summary.get(k), "passed": summary.get(k) == v} for k, v in GATES.items()]


def context_summary_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    keys = [
        "latest_daily_chain_final_status", "latest_daily_chain_final_decision", "latest_context_block_final_status",
        "latest_context_append_final_status", "dram_primary_focus_active", "technical_freeze_enforced",
        "strategy_governance_research_context_only", "retention_guard_status_found", "combined_report_created",
    ]
    return [{"context_key": k, "context_value": summary.get(k)} for k in keys]


def master_summary_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"summary_key": k, "summary_value": v} for k, v in summary.items()]


def has_warn(ledger: list[dict[str, Any]]) -> bool:
    return any(str(r.get("final_status", "")).startswith("WARN") for r in ledger)


def has_fail(ledger: list[dict[str, Any]]) -> bool:
    return any(r.get("attempted") and not r.get("succeeded") for r in ledger)


def gate_violation(summary: dict[str, Any]) -> bool:
    return any(summary.get(k) != v for k, v in GATES.items())


def build_summary(run_mode: str, ledger: list[dict[str, Any]], summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    daily = summaries.get("DAILY_CHAIN_RETENTION_GUARD", {})
    ctx = summaries.get("V21_253_CONTEXT_BLOCK", {})
    app = summaries.get("V21_254_CONTEXT_APPEND", {})
    missing = sum(1 for s in [daily, ctx, app] if not s)
    attempted = sum(1 for r in ledger if r.get("attempted"))
    succeeded = sum(1 for r in ledger if r.get("succeeded"))
    summary = {
        "final_status": "PASS_V21_256_DAILY_MASTER_WRAPPER_READY",
        "final_decision": "DAILY_MASTER_WRAPPER_WITH_CONTEXT_READY_RESEARCH_ONLY",
        "run_mode": run_mode,
        "child_stage_count": 3,
        "child_stage_attempted_count": attempted,
        "child_stage_succeeded_count": succeeded,
        "daily_chain_stage_succeeded": bool(daily) and not str(daily.get("final_status", "")).startswith("FAIL"),
        "context_block_stage_succeeded": bool(ctx) and not str(ctx.get("final_status", "")).startswith("FAIL"),
        "context_append_stage_succeeded": bool(app) and not str(app.get("final_status", "")).startswith("FAIL"),
        "latest_daily_chain_final_status": daily.get("final_status", ""),
        "latest_daily_chain_final_decision": daily.get("final_decision", ""),
        "latest_context_block_final_status": ctx.get("final_status", ""),
        "latest_context_append_final_status": app.get("final_status", ""),
        "dram_primary_focus_active": ctx.get("dram_primary_focus_active", app.get("dram_primary_focus_active", True)),
        "technical_freeze_enforced": ctx.get("technical_freeze_enforced", True),
        "strategy_governance_research_context_only": ctx.get("strategy_governance_research_context_only", True),
        "retention_guard_status_found": ctx.get("retention_guard_status_found", bool(daily)),
        "combined_report_created": app.get("combined_report_created", False),
        "missing_input_count": missing,
        "warning_count": 0,
        "error_count": 0,
        **GATES,
    }
    if run_mode == "Execute" and has_fail(ledger):
        summary["final_status"] = "FAIL_V21_256_DAILY_MASTER_WRAPPER_CHILD_FAILURE"
        summary["final_decision"] = "DAILY_MASTER_WRAPPER_BLOCKED_CHILD_FAILURE"
        summary["error_count"] = 1
    elif missing:
        summary["final_status"] = "WARN_V21_256_DAILY_MASTER_WRAPPER_AUDIT_ONLY_PARTIAL" if run_mode == "AuditOnly" else "FAIL_V21_256_DAILY_MASTER_WRAPPER_INPUT_MISSING"
        summary["final_decision"] = "DAILY_MASTER_WRAPPER_PARTIAL_MISSING_CHILD_OUTPUTS" if run_mode == "AuditOnly" else "DAILY_MASTER_WRAPPER_BLOCKED_INPUT_MISSING"
        summary["warning_count"] = missing if run_mode == "AuditOnly" else 0
        summary["error_count"] = 0 if run_mode == "AuditOnly" else 1
    elif has_warn(ledger) or any(str(s.get("final_status", "")).startswith("WARN") for s in summaries.values()):
        summary["final_status"] = "WARN_V21_256_DAILY_MASTER_WRAPPER_READY_WITH_CHILD_WARNINGS"
        summary["final_decision"] = "DAILY_MASTER_WRAPPER_READY_WITH_CHILD_WARNINGS"
        summary["warning_count"] = 1
    if not summary["combined_report_created"] and summary["final_status"].startswith("PASS"):
        summary["final_status"] = "WARN_V21_256_DAILY_MASTER_WRAPPER_AUDIT_ONLY_PARTIAL"
        summary["final_decision"] = "DAILY_MASTER_WRAPPER_PARTIAL_CONTEXT_APPEND_MISSING"
        summary["warning_count"] += 1
    if gate_violation(summary):
        summary["final_status"] = "FAIL_V21_256_DAILY_MASTER_WRAPPER_GATE_VIOLATION"
        summary["final_decision"] = "DAILY_MASTER_WRAPPER_BLOCKED_GATE_VIOLATION"
        summary["error_count"] = 1
    return summary


def wrapper_missing(repo: Path) -> bool:
    paths = wrapper_paths(repo)
    return any(p is None or not p.exists() for p in paths.values())


def run(repo: Path, output_dir: Path | None = None, run_mode: str = "AuditOnly", child_runner: Callable[[list[str], Path, Path], tuple[int, str]] | None = None) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    if run_mode == "Execute":
        if wrapper_missing(repo):
            ledger = [{"stage_name": k, "attempted": True, "succeeded": False, "final_status": "", "final_decision": "", "output_root": "", "error_message": "required_wrapper_missing"} for k, p in wrapper_paths(repo).items() if p is None or not p.exists()]
            summaries = load_child_summaries(repo)
            summary = build_summary(run_mode, ledger, summaries)
            summary["final_status"] = "FAIL_V21_256_DAILY_MASTER_WRAPPER_INPUT_MISSING"
            summary["final_decision"] = "DAILY_MASTER_WRAPPER_BLOCKED_REQUIRED_WRAPPER_MISSING"
            summary["error_count"] = 1
        else:
            ledger = run_children(repo, out, child_runner)
            summaries = load_child_summaries(repo)
            summary = build_summary(run_mode, ledger, summaries)
    else:
        ledger = audit_ledger(repo)
        summaries = load_child_summaries(repo)
        summary = build_summary("AuditOnly", ledger, summaries)
    write_outputs(out, summary, ledger)
    return summary


def report(summary: dict[str, Any], ledger: list[dict[str, Any]]) -> str:
    lines = ["V21.256 Daily Chain Master Wrapper With Context", f"final_status={summary['final_status']}", f"final_decision={summary['final_decision']}", f"run_mode={summary['run_mode']}", ""]
    lines.append("[Child Stage Ledger]")
    for r in ledger:
        lines.append(f"- {r['stage_name']}: attempted={r['attempted']} succeeded={r['succeeded']} final_status={r['final_status']}")
    lines.append("")
    lines.append("[No-Go Gates]")
    for k, v in GATES.items():
        lines.append(f"- {k}={summary.get(k)}")
    return "\n".join(lines) + "\n"


def write_outputs(out: Path, summary: dict[str, Any], ledger: list[dict[str, Any]]) -> None:
    write_csv(out / "daily_chain_master_summary.csv", master_summary_rows(summary), ["summary_key", "summary_value"])
    write_csv(out / "daily_chain_master_child_stage_ledger.csv", ledger, ["stage_name", "attempted", "succeeded", "final_status", "final_decision", "output_root", "error_message"])
    write_csv(out / "daily_chain_master_gate_audit.csv", gate_audit(summary), ["gate_name", "expected", "observed", "passed"])
    write_csv(out / "daily_chain_master_no_mutation_audit.csv", no_mutation_audit(), ["audit_item", "observed_allowed", "expected_allowed", "passed", "field"])
    write_csv(out / "daily_chain_master_context_summary.csv", context_summary_rows(summary), ["context_key", "context_value"])
    text = report(summary, ledger)
    (out / "daily_chain_master_report.txt").write_text(text, encoding="utf-8")
    write_json(out / "v21_256_summary.json", summary)
    (out / "V21.256_daily_chain_master_wrapper_with_context_report.txt").write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--run-mode", choices=["AuditOnly", "Execute"], default="AuditOnly")
    a = p.parse_args(argv)
    s = run(a.repo_root.resolve(), a.output_dir, a.run_mode)
    for k in [
        "final_status", "final_decision", "run_mode", "child_stage_count", "child_stage_attempted_count",
        "child_stage_succeeded_count", "daily_chain_stage_succeeded", "context_block_stage_succeeded",
        "context_append_stage_succeeded", "latest_daily_chain_final_status", "latest_daily_chain_final_decision",
        "latest_context_block_final_status", "latest_context_append_final_status", "dram_primary_focus_active",
        "technical_freeze_enforced", "strategy_governance_research_context_only", "retention_guard_status_found",
        "combined_report_created", "official_adoption_allowed", "broker_action_allowed", "weight_update_allowed",
        "ranking_mutation_allowed", "trade_plan_mutation_allowed", "child_output_mutation_allowed",
        "automatic_ticker_replacement_allowed", "automatic_position_increase_allowed", "automatic_trade_trigger_allowed",
        "market_data_fetch_allowed", "missing_input_count", "warning_count", "error_count",
    ]:
        print(f"{k}={s.get(k)}")
    return 1 if str(s.get("final_status", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
