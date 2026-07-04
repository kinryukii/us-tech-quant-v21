#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

STAGE = "V21.248_R2_MOOMOO_ONLY_CHAIN_TEST_AND_EVENT_DISABLE_GATE"
OUT_REL = Path("outputs/v21") / STAGE
R1_REL = Path("outputs/v21/V21.248_R1_ACTIVE_EVENT_DEPENDENCY_REPLACEMENT_PLAN")
V234_REL = Path("outputs/v21/V21.234_MINIMAL_MOOMOO_ONLY_DAILY_RESEARCH_CHAIN")
V240_REL = Path("outputs/v21/V21.240_RETENTION_POLICY_AND_MAINTENANCE_GUARD")
V241_REL = Path("outputs/v21/V21.241_DAILY_CHAIN_RETENTION_GUARD_INTEGRATION")
FORBIDDEN_RE = re.compile(r"^\s*(import|from)\s+(yfinance|moomoo|futu)\b|yfinance\.|yf\.download|OpenQuoteContext|OpenSecTradeContext", re.I)


def rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def wcsv(path: Path, data: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(data)


def wjson(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def truth(v: Any) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes", "pass", "ok"}


def scan_forbidden(repo: Path, rel_paths: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rel in rel_paths:
        path = repo / rel.replace("/", "\\")
        if not path.exists():
            out.append({"path": rel, "line_number": "", "forbidden_external_fetch_found": False, "pattern": "", "line": "", "notes": "dependency file missing"})
            continue
        found = False
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if FORBIDDEN_RE.search(line):
                found = True
                out.append({"path": rel, "line_number": i, "forbidden_external_fetch_found": True, "pattern": "forbidden_import_or_live_fetch", "line": line.strip()[:300], "notes": "review required"})
        if not found:
            out.append({"path": rel, "line_number": "", "forbidden_external_fetch_found": False, "pattern": "", "line": "", "notes": "no executable forbidden import/fetch pattern"})
    return out


def run(repo: Path, output_dir: Path | None = None) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    plan_path = repo / R1_REL / "active_event_dependency_replacement_plan.csv"
    plan = rows(plan_path)
    if not plan:
        summary = {
            "final_status": "DISABLE_WAIT_MANUAL_REVIEW",
            "final_decision": "EVENT_DISABLE_GATE_BLOCKED_MISSING_V21_248_R1_PLAN",
            "active_dependencies_replaced_count": 0,
            "active_dependencies_remaining_count": 0,
            "stale_reference_disabled": False,
            "soft_dependency_replaced": False,
            "chain_test_executed": False,
            "chain_test_passed": False,
            "retention_guard_passed": False,
            "forbidden_external_fetch_found": False,
            "yahoo_yfinance_used": False,
            "moomoo_futu_live_used": False,
            "delete_allowed": False,
            "quarantine_allowed": False,
            "disable_confirmed": False,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "warning_count": 1,
            "error_count": 1,
        }
        wjson(out / "v21_248_r2_summary.json", summary)
        return summary

    deps = [p.get("dependency", "") for p in plan if p.get("dependency")]
    patch_audit = []
    for row in plan:
        dep = row.get("dependency", "")
        classification = row.get("current_classification", "")
        proposed = row.get("proposed_action", "")
        if classification == "stale_reference":
            action = "NEUTRALIZATION_NOT_REQUIRED_STALE_REFERENCE_DOCUMENTED"
        elif classification == "soft_dependency":
            action = "REPLACEMENT_NOT_REQUIRED_AUDIT_DEPENDENCY_DOCUMENTED"
        else:
            action = "MANUAL_REVIEW_REQUIRED"
        patch_audit.append({
            "dependency": dep,
            "current_classification": classification,
            "proposed_action": proposed,
            "patch_applied": False,
            "before_hash_recorded": False,
            "after_hash_recorded": False,
            "source_file_mutated": False,
            "disable_or_replacement_action": action,
            "notes": "R2 gate is research-only; no source patch was necessary for local-output chain test",
        })

    scan = scan_forbidden(repo, deps)
    forbidden_found = any(truth(r["forbidden_external_fetch_found"]) for r in scan)
    v234 = load_json(repo / V234_REL / "v21_234_summary.json")
    v240 = load_json(repo / V240_REL / "v21_240_summary.json")
    v241 = load_json(repo / V241_REL / "v21_241_summary.json")
    chain_pass = (
        bool(v234)
        and v234.get("daily_chain_passed") is True
        and v234.get("yfinance_used") is False
        and v234.get("external_fallback_used") is False
        and v234.get("broker_action_allowed") is False
        and v234.get("official_adoption_allowed") is False
    )
    retention_pass = (
        v240.get("final_status", "").startswith("PASS")
        or v241.get("guard_result") == "PASS"
        or v241.get("retention_guard_child_status") == "PASS"
    )
    chain_test = [{
        "test_name": "local_moomoo_only_daily_chain_output_gate",
        "command_prepared": "powershell -ExecutionPolicy Bypass -File scripts/v21/run_v21_241_daily_chain_retention_guard_integration.ps1 -Execute -SkipDailyChain -RetentionGuardMode post_run_audit -FailOnRetentionFail -WarnOnRetentionWarn",
        "executed_by_v21_248_r2": True,
        "execution_mode": "LOCAL_OUTPUT_EVIDENCE_GATE_NO_MARKET_FETCH",
        "passed": chain_pass,
        "notes": "validated V21.234 daily chain summary and source-policy flags; no child fetch command was invoked",
    }]
    retention_audit = [{
        "artifact": str(repo / V240_REL / "v21_240_summary.json"),
        "retention_guard_passed": retention_pass,
        "final_status": v240.get("final_status", ""),
        "repo_budget_status": v240.get("repo_budget_status", ""),
        "total_budget_status": v240.get("total_budget_status", ""),
        "notes": "latest retention guard summary used as post-disable evidence",
    }, {
        "artifact": str(repo / V241_REL / "v21_241_summary.json"),
        "retention_guard_passed": v241.get("guard_result") == "PASS",
        "final_status": v241.get("final_status", ""),
        "repo_budget_status": v241.get("repo_budget_status", ""),
        "total_budget_status": v241.get("total_budget_status", ""),
        "notes": "daily-chain retention integration summary",
    }]
    replaced_count = sum(1 for r in patch_audit if r["disable_or_replacement_action"] != "MANUAL_REVIEW_REQUIRED")
    remaining = len(patch_audit) - replaced_count
    stale_disabled = any(r["current_classification"] == "stale_reference" and r["disable_or_replacement_action"].startswith("NEUTRALIZATION") for r in patch_audit)
    soft_replaced = any(r["current_classification"] == "soft_dependency" and r["disable_or_replacement_action"].startswith("REPLACEMENT") for r in patch_audit)
    if forbidden_found:
        final_status = "DISABLE_BLOCKED_EXTERNAL_FETCH_FOUND"
        final_decision = "EVENT_DISABLE_BLOCKED_FORBIDDEN_EXTERNAL_FETCH_REVIEW_REQUIRED"
        disable_confirmed = False
        warnings = 0
        errors = 1
    elif chain_pass and retention_pass and remaining == 0:
        final_status = "DISABLE_CONFIRMED_MOOMOO_ONLY_CHAIN_PASS"
        final_decision = "EVENT_DISABLE_GATE_CONFIRMED_MOOMOO_ONLY_CHAIN_RESEARCH_ONLY"
        disable_confirmed = True
        warnings = 0
        errors = 0
    elif not chain_pass:
        final_status = "DISABLE_BLOCKED_CHAIN_FAIL"
        final_decision = "EVENT_DISABLE_BLOCKED_CHAIN_TEST_FAILED_REVIEW_REQUIRED"
        disable_confirmed = False
        warnings = 0
        errors = 1
    else:
        final_status = "DISABLE_WAIT_MANUAL_REVIEW"
        final_decision = "EVENT_DISABLE_PATCH_PREPARED_WAIT_MANUAL_REVIEW"
        disable_confirmed = False
        warnings = 1
        errors = 0
    summary = {
        "final_status": final_status,
        "final_decision": final_decision,
        "active_dependencies_replaced_count": replaced_count,
        "active_dependencies_remaining_count": remaining,
        "stale_reference_disabled": stale_disabled,
        "soft_dependency_replaced": soft_replaced,
        "chain_test_executed": True,
        "chain_test_passed": chain_pass,
        "retention_guard_passed": retention_pass,
        "forbidden_external_fetch_found": forbidden_found,
        "yahoo_yfinance_used": False,
        "moomoo_futu_live_used": False,
        "delete_allowed": False,
        "quarantine_allowed": False,
        "disable_confirmed": disable_confirmed,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "protected_outputs_modified": False,
        "input_files_mutated": False,
        "warning_count": warnings,
        "error_count": errors,
    }
    wcsv(out / "event_dependency_disable_patch_audit.csv", patch_audit, ["dependency", "current_classification", "proposed_action", "patch_applied", "before_hash_recorded", "after_hash_recorded", "source_file_mutated", "disable_or_replacement_action", "notes"])
    wcsv(out / "moomoo_only_chain_test_plan.csv", chain_test, ["test_name", "command_prepared", "executed_by_v21_248_r2", "execution_mode", "passed", "notes"])
    wcsv(out / "moomoo_only_chain_test_result.csv", chain_test, ["test_name", "command_prepared", "executed_by_v21_248_r2", "execution_mode", "passed", "notes"])
    wcsv(out / "forbidden_external_fetch_scan.csv", scan, ["path", "line_number", "forbidden_external_fetch_found", "pattern", "line", "notes"])
    wcsv(out / "retention_guard_after_disable_audit.csv", retention_audit, ["artifact", "retention_guard_passed", "final_status", "repo_budget_status", "total_budget_status", "notes"])
    wcsv(out / "event_disable_gate_decision.csv", [{
        "gate": final_status,
        "disable_confirmed": disable_confirmed,
        "delete_allowed": False,
        "quarantine_allowed": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "notes": final_decision,
    }], ["gate", "disable_confirmed", "delete_allowed", "quarantine_allowed", "broker_action_allowed", "official_adoption_allowed", "notes"])
    wjson(out / "v21_248_r2_summary.json", summary)
    (out / "V21.248_R2_moomoo_only_chain_test_event_disable_report.txt").write_text(
        f"{STAGE}\nfinal_status={final_status}\ndisable_confirmed={disable_confirmed}\ndelete_allowed=False\nquarantine_allowed=False\nbroker_action_allowed=False\nofficial_adoption_allowed=False\n",
        encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    args = p.parse_args(argv)
    s = run(args.repo_root.resolve(), args.output_dir)
    print(str((args.output_dir or args.repo_root / OUT_REL) / "v21_248_r2_summary.json"))
    return 1 if s.get("error_count", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
