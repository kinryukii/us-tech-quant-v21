#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

STAGE = "V21.248_R1_ACTIVE_EVENT_DEPENDENCY_REPLACEMENT_PLAN"
OUT_REL = Path("outputs/v21") / STAGE
V248_REL = Path("outputs/v21/V21.248_EVENT_AUTO_UPDATE_RETIREMENT_AND_MOOMOO_ONLY_REPLACEMENT_AUDIT")
REFERENCE_RE = re.compile(r"(event|external|earnings|calendar|news|refresh|fallback|provider|yahoo|yfin)", re.I)


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def as_bool(v: Any) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes"}


def classify_dependency(rel: str, lines: list[tuple[int, str]]) -> tuple[str, str, str]:
    lowered = rel.lower()
    if "v21_241_daily_chain_retention_guard_integration" in lowered:
        return (
            "stale_reference",
            "DISABLE_SAFE_AFTER_CHAIN_TEST",
            "retention guard integration text mentions daily-chain external/fetch policy but does not call old event updater",
        )
    if "v21_248_event_auto_update_retirement" in lowered:
        return (
            "soft_dependency",
            "REPLACE_WITH_MOOMOO_LOCAL_CACHE",
            "audit module inventories event references; not an execution dependency for current Moomoo-only chain",
        )
    import_like = [text for _line, text in lines if re.search(r"^\s*(import|from)\s+", text)]
    if import_like:
        return ("hard_dependency", "KEEP_REQUIRED", "active import-like dependency requires manual review")
    return ("unknown", "UNKNOWN_BLOCKER", "dependency could not be classified safely")


def affected_area(line: str) -> str:
    low = line.lower()
    if any(x in low for x in ["earnings", "calendar", "news", "event"]):
        return "event/fundamental data"
    if any(x in low for x in ["rank", "factor", "feature"]):
        return "ranking features"
    if any(x in low for x in ["daily", "chain", "orchestrat"]):
        return "daily chain orchestration"
    if any(x in low for x in ["price", "ohlcv", "cache"]):
        return "price data"
    return "audit/report generation"


def find_reference_lines(path: Path) -> list[tuple[int, str]]:
    if not path.exists() or not path.is_file():
        return []
    try:
        out = []
        for idx, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if REFERENCE_RE.search(line):
                out.append((idx, line.strip()[:500]))
        return out[:50]
    except Exception:
        return []


def build_plan(repo: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    inventory = read_rows(repo / V248_REL / "event_auto_update_module_inventory.csv")
    active = [r for r in inventory if as_bool(r.get("active_chain_dependency"))]
    detail: list[dict[str, Any]] = []
    call_graph: list[dict[str, Any]] = []
    plan: list[dict[str, Any]] = []
    equivalent: list[dict[str, Any]] = []
    chain_test: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []

    for row in active:
        rel = row.get("relative_path") or row.get("path", "")
        src = repo / rel.replace("/", "\\")
        lines = find_reference_lines(src)
        dep_type, proposed, note = classify_dependency(rel, lines)
        line_preview = lines[0][1] if lines else ""
        called_component = "event_auto_update_or_external_reference"
        if "v21_241" in rel:
            called_component = "retention_guard_external_policy_reference"
        elif "v21_248" in rel:
            called_component = "event_retirement_inventory_scanner"
        area = affected_area(line_preview or rel)
        detail.append({
            "file_path": str(src),
            "relative_path": rel,
            "caller_script": rel,
            "reference_line": line_preview,
            "called_event_external_component": called_component,
            "dependency_type": dep_type,
            "proposed_resolution": proposed,
            "affects_price_data": area == "price data",
            "affects_event_fundamental_data": area == "event/fundamental data",
            "affects_ranking_features": area == "ranking features",
            "affects_daily_chain_orchestration": area == "daily chain orchestration",
            "affects_audit_report_generation": area == "audit/report generation",
            "notes": note,
        })
        for line_no, text in lines[:10]:
            call_graph.append({
                "caller_script": rel,
                "line_number": line_no,
                "reference_line": text,
                "called_component": called_component,
                "dependency_type": dep_type,
                "notes": note,
            })
        plan.append({
            "dependency": rel,
            "current_classification": dep_type,
            "proposed_action": proposed,
            "replacement_source": "Moomoo-only local cache / current V21.231-V21.234 manifests" if proposed != "KEEP_REQUIRED" else "manual review required",
            "disable_allowed_now": False,
            "delete_allowed": False,
            "quarantine_allowed": False,
            "chain_test_required": True,
            "notes": note,
        })
        equivalent.append({
            "dependency": rel,
            "moomoo_only_equivalent_available": proposed in {"REPLACE_WITH_MOOMOO_LOCAL_CACHE", "DISABLE_SAFE_AFTER_CHAIN_TEST"},
            "equivalent_source": "local cache, V21.231 canonical pointer, V21.232 DRAM plan, V21.233 ABCDE rerun, V21.234 chain summary",
            "external_provider_needed": False,
            "notes": note,
        })
        chain_test.append({
            "dependency": rel,
            "test_step": "run V21.234 minimal daily chain and V21.241 retention guard wrapper with dependency disabled in a branch",
            "expected_result": "no source-policy, DRAM, ABCDE, or retention guard regression",
            "disable_ready_after_chain_test": proposed in {"REPLACE_WITH_MOOMOO_LOCAL_CACHE", "DISABLE_SAFE_AFTER_CHAIN_TEST"},
            "notes": "plan only; no disable performed",
        })
        quarantine.append({
            "dependency": rel,
            "quarantine_allowed_now": False,
            "delete_allowed_now": False,
            "required_before_quarantine": "successful disable chain test plus preserved hash manifests",
            "notes": "R1 is a plan only",
        })

    hard = sum(1 for r in detail if r["dependency_type"] == "hard_dependency")
    soft = sum(1 for r in detail if r["dependency_type"] == "soft_dependency")
    stale = sum(1 for r in detail if r["dependency_type"] == "stale_reference")
    unknown = sum(1 for r in detail if r["dependency_type"] == "unknown")
    replace_ready = sum(1 for r in plan if r["proposed_action"] in {"REPLACE_WITH_MOOMOO_LOCAL_CACHE", "DISABLE_SAFE_AFTER_CHAIN_TEST"})
    keep = sum(1 for r in plan if r["proposed_action"] == "KEEP_REQUIRED")
    disable_ready = bool(active) and unknown == 0 and hard == 0 and replace_ready == len(active)
    if unknown:
        status = "BLOCKED_UNKNOWN_DEPENDENCY"
        decision = "ACTIVE_EVENT_DEPENDENCY_REPLACEMENT_BLOCKED_UNKNOWN_REVIEW_REQUIRED"
    elif hard:
        status = "KEEP_REQUIRED_CONFIRMED"
        decision = "ACTIVE_EVENT_DEPENDENCIES_KEEP_REQUIRED_RESEARCH_ONLY"
    elif disable_ready:
        status = "DISABLE_READY_AFTER_CHAIN_TEST"
        decision = "ACTIVE_EVENT_DEPENDENCIES_REPLACEMENT_PLAN_READY_CHAIN_TEST_REQUIRED"
    else:
        status = "REPLACE_WITH_MOOMOO_READY"
        decision = "ACTIVE_EVENT_DEPENDENCIES_MOOMOO_LOCAL_REPLACEMENT_READY_RESEARCH_ONLY"

    summary = {
        "final_status": status,
        "final_decision": decision,
        "active_dependency_count": len(active),
        "hard_dependency_count": hard,
        "soft_dependency_count": soft,
        "stale_reference_count": stale,
        "replace_with_moomoo_ready_count": replace_ready,
        "keep_required_count": keep,
        "unknown_blocker_count": unknown,
        "disable_ready_after_chain_test": disable_ready,
        "delete_allowed": False,
        "quarantine_allowed": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "protected_outputs_modified": False,
        "input_files_mutated": False,
        "warning_count": 1 if status != "DISABLE_READY_AFTER_CHAIN_TEST" else 0,
        "error_count": 0,
    }
    return detail, call_graph, plan, {
        "summary": summary,
        "equivalent": equivalent,
        "chain_test": chain_test,
        "quarantine": quarantine,
    }


def run(repo: Path, output_dir: Path | None = None) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    required = repo / V248_REL / "event_auto_update_module_inventory.csv"
    if not required.exists():
        summary = {
            "final_status": "FAIL_V21_248_R1_REQUIRED_INPUT_MISSING",
            "final_decision": "ACTIVE_EVENT_DEPENDENCY_REPLACEMENT_BLOCKED_MISSING_V21_248",
            "active_dependency_count": 0,
            "hard_dependency_count": 0,
            "soft_dependency_count": 0,
            "stale_reference_count": 0,
            "replace_with_moomoo_ready_count": 0,
            "keep_required_count": 0,
            "unknown_blocker_count": 0,
            "disable_ready_after_chain_test": False,
            "delete_allowed": False,
            "quarantine_allowed": False,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "protected_outputs_modified": False,
            "input_files_mutated": False,
            "warning_count": 0,
            "error_count": 1,
        }
        write_json(out / "v21_248_r1_summary.json", summary)
        return summary

    detail, call_graph, plan, payload = build_plan(repo)
    detail_fields = [
        "file_path", "relative_path", "caller_script", "reference_line", "called_event_external_component",
        "dependency_type", "proposed_resolution", "affects_price_data", "affects_event_fundamental_data",
        "affects_ranking_features", "affects_daily_chain_orchestration", "affects_audit_report_generation", "notes",
    ]
    write_csv(out / "active_event_dependency_detail.csv", detail, detail_fields)
    write_csv(out / "active_event_dependency_call_graph.csv", call_graph, ["caller_script", "line_number", "reference_line", "called_component", "dependency_type", "notes"])
    write_csv(out / "active_event_dependency_replacement_plan.csv", plan, ["dependency", "current_classification", "proposed_action", "replacement_source", "disable_allowed_now", "delete_allowed", "quarantine_allowed", "chain_test_required", "notes"])
    write_csv(out / "moomoo_only_equivalent_source_audit.csv", payload["equivalent"], ["dependency", "moomoo_only_equivalent_available", "equivalent_source", "external_provider_needed", "notes"])
    write_csv(out / "disable_chain_test_plan.csv", payload["chain_test"], ["dependency", "test_step", "expected_result", "disable_ready_after_chain_test", "notes"])
    write_csv(out / "quarantine_delete_safety_plan.csv", payload["quarantine"], ["dependency", "quarantine_allowed_now", "delete_allowed_now", "required_before_quarantine", "notes"])
    summary = payload["summary"]
    write_json(out / "v21_248_r1_summary.json", summary)
    report = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"active_dependency_count={summary['active_dependency_count']}",
        f"hard_dependency_count={summary['hard_dependency_count']}",
        f"soft_dependency_count={summary['soft_dependency_count']}",
        f"stale_reference_count={summary['stale_reference_count']}",
        "delete_allowed=False",
        "quarantine_allowed=False",
        "official_adoption_allowed=False",
        "broker_action_allowed=False",
    ]
    (out / "V21.248_R1_active_event_dependency_replacement_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    args = p.parse_args(argv)
    summary = run(args.repo_root.resolve(), args.output_dir)
    print(str((args.output_dir or args.repo_root / OUT_REL) / "v21_248_r1_summary.json"))
    return 1 if summary.get("error_count", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
