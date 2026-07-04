#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

STAGE = "V21.254_DAILY_CHAIN_WRAPPER_CONTEXT_BLOCK_APPEND_R1"
OUT_REL = Path("outputs/v21") / STAGE
V253_REL = Path("outputs/v21/V21.253_DAILY_RESEARCH_CHAIN_CONTEXT_BLOCK_INTEGRATION_R1")
CHAIN_HINTS = ("V21.234", "V21.241")
GATES = {
    "append_only": True,
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


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


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


def version_key(path: Path) -> tuple[int, str]:
    m = re.search(r"V21\.(\d+)", path.name)
    return (int(m.group(1)) if m else -1, path.name)


def is_daily_chain_dir(path: Path) -> bool:
    name = path.name.upper()
    if "V21.253" in name or "V21.254" in name:
        return False
    return any(h in path.name for h in CHAIN_HINTS) or "RETENTION" in name or ("DAILY" in name and "CONTEXT" not in name)


def discover_latest_daily_chain(repo: Path) -> tuple[Path | None, dict[str, Any], list[dict[str, Any]]]:
    base = repo / "outputs" / "v21"
    candidates: list[Path] = []
    if base.exists():
        for d in base.iterdir():
            if d.is_dir() and is_daily_chain_dir(d):
                candidates.extend(d.glob("*summary*.json"))
    candidates.sort(key=lambda p: version_key(p.parent), reverse=True)
    audit: list[dict[str, Any]] = []
    chosen_path: Path | None = None
    chosen_summary: dict[str, Any] = {}
    for p in candidates:
        data = read_json(p)
        readable = bool(data)
        audit.append({"candidate_summary_path": str(p), "candidate_stage": p.parent.name, "readable": readable, "selected": False, "final_status": data.get("final_status", ""), "final_decision": data.get("final_decision", "")})
        if readable and chosen_path is None:
            chosen_path, chosen_summary = p, data
    if chosen_path:
        for row in audit:
            row["selected"] = row["candidate_summary_path"] == str(chosen_path)
    return chosen_path, chosen_summary, audit


def section_count_from_context(summary: dict[str, Any], text: str) -> int:
    if summary.get("context_section_count"):
        return int(summary.get("context_section_count", 0))
    return len(set(re.findall(r"^\[([A-Z0-9_]+)\]", text, flags=re.MULTILINE)))


def combined_report(chain_path: Path | None, chain: dict[str, Any], context_text: str, summary: dict[str, Any]) -> str:
    return (
        "V21.254 Daily Chain Combined Context Report\n"
        f"final_status={summary['final_status']}\n"
        f"final_decision={summary['final_decision']}\n\n"
        "[Latest Daily Chain / Retention Guard Summary]\n"
        f"source={chain_path or ''}\n"
        f"latest_daily_chain_final_status={chain.get('final_status', '')}\n"
        f"latest_daily_chain_final_decision={chain.get('final_decision', '')}\n\n"
        "[Appended V21.253 Daily Research Context Block]\n"
        f"{context_text.strip()}\n\n"
        "[Append-Only Gate]\n"
        "This artifact is append-only and research-only. It does not mutate child outputs, rankings, weights, trade plans, broker/action gates, canonical outputs, cache artifacts, or live execution files.\n"
    )


def append_audit() -> list[dict[str, Any]]:
    rows = [
        ("child_outputs_not_mutated", False, "child_output_mutation_allowed"),
        ("rankings_not_mutated", False, "ranking_mutation_allowed"),
        ("weights_not_mutated", False, "weight_update_allowed"),
        ("trade_plans_not_mutated", False, "trade_plan_mutation_allowed"),
        ("broker_action_gates_not_changed", False, "broker_action_allowed"),
        ("no_provider_data_fetch", False, "market_data_fetch_allowed"),
    ]
    return [{"audit_item": item, "mutation_or_action_allowed": GATES[field], "expected_allowed": expected, "passed": GATES[field] == expected, "field": field} for item, expected, field in rows]


def recommendations() -> list[dict[str, Any]]:
    return [
        {"recommendation": "CALL_AFTER_V21_241_RETENTION_GUARD", "detail": "V21.254 may run after retention guard outputs exist.", "allowed": True, "mutation_allowed": False},
        {"recommendation": "APPEND_ONLY_CONTEXT_ARTIFACT", "detail": "Create a separate combined report; do not replace daily chain outputs.", "allowed": True, "mutation_allowed": False},
        {"recommendation": "DO_NOT_USE_AS_DATA_REFRESH_STEP", "detail": "V21.254 must not fetch data or refresh cache.", "allowed": False, "mutation_allowed": False},
        {"recommendation": "DO_NOT_USE_AS_RANKING_STEP", "detail": "V21.254 must not alter rankings or weights.", "allowed": False, "mutation_allowed": False},
    ]


def gate_audit(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"gate_name": k, "expected": v, "observed": summary.get(k), "passed": summary.get(k) == v} for k, v in GATES.items()]


def fail_summary(status: str, decision: str, missing: int) -> dict[str, Any]:
    return {
        "final_status": status,
        "final_decision": decision,
        "latest_daily_chain_summary_found": False,
        "latest_daily_chain_final_status": "",
        "latest_daily_chain_final_decision": "",
        "v21_253_context_block_found": False,
        "context_section_count": 0,
        "combined_report_created": False,
        "missing_input_count": missing,
        "warning_count": 0,
        "error_count": 1,
        **GATES,
    }


def has_gate_violation(summary: dict[str, Any]) -> bool:
    return any(summary.get(k) != v for k, v in GATES.items())


def run(repo: Path, output_dir: Path | None = None, v253_root: Path = V253_REL) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    r253 = root(repo, v253_root)
    s253 = read_json(r253 / "v21_253_summary.json")
    context_text = read_text(r253 / "daily_research_context_block_for_report.txt")
    missing = []
    if not s253:
        missing.append("V21.253 summary")
    if not context_text:
        missing.append("V21.253 report block")
    if missing:
        summary = fail_summary("FAIL_V21_254_DAILY_CHAIN_CONTEXT_APPEND_INPUT_MISSING", "DAILY_CHAIN_CONTEXT_APPEND_BLOCKED_INPUT_MISSING", len(missing))
        write_outputs(out, "", [], [], [], [], [], summary)
        return summary

    chain_path, chain, discovery = discover_latest_daily_chain(repo)
    section_count = section_count_from_context(s253, context_text)
    status = "PASS_V21_254_DAILY_CHAIN_CONTEXT_APPEND_READY" if chain_path else "WARN_V21_254_DAILY_CHAIN_CONTEXT_APPEND_READY_WITH_MISSING_DAILY_CHAIN"
    summary = {
        "final_status": status,
        "final_decision": "DAILY_CHAIN_CONTEXT_APPEND_READY_RESEARCH_ONLY" if chain_path else "DAILY_CHAIN_CONTEXT_APPEND_READY_WITH_MISSING_DAILY_CHAIN",
        "latest_daily_chain_summary_found": bool(chain_path),
        "latest_daily_chain_final_status": chain.get("final_status", ""),
        "latest_daily_chain_final_decision": chain.get("final_decision", ""),
        "v21_253_context_block_found": True,
        "context_section_count": section_count,
        "combined_report_created": True,
        "missing_input_count": 0,
        "warning_count": 0 if chain_path else 1,
        "error_count": 0,
        **GATES,
    }
    if has_gate_violation(summary):
        summary["final_status"] = "FAIL_V21_254_DAILY_CHAIN_CONTEXT_APPEND_GATE_VIOLATION"
        summary["final_decision"] = "DAILY_CHAIN_CONTEXT_APPEND_BLOCKED_GATE_VIOLATION"
        summary["error_count"] = 1
    report = combined_report(chain_path, chain, context_text, summary)
    write_outputs(out, report, summary_rows(summary), append_audit(), recommendations(), gate_audit(summary), discovery, summary)
    return summary


def summary_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"summary_key": k, "summary_value": v} for k, v in summary.items()]


def write_outputs(out: Path, report: str, summary_rows_: list[dict[str, Any]], append_rows: list[dict[str, Any]], recs: list[dict[str, Any]], gates: list[dict[str, Any]], discovery: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "daily_chain_combined_context_report.txt").write_text(report, encoding="utf-8")
    write_csv(out / "daily_chain_combined_context_summary.csv", summary_rows_, ["summary_key", "summary_value"])
    write_csv(out / "daily_chain_context_append_audit.csv", append_rows, ["audit_item", "mutation_or_action_allowed", "expected_allowed", "passed", "field"])
    write_csv(out / "daily_chain_wrapper_integration_recommendation.csv", recs, ["recommendation", "detail", "allowed", "mutation_allowed"])
    write_csv(out / "gate_status_append_audit.csv", gates, ["gate_name", "expected", "observed", "passed"])
    write_csv(out / "latest_daily_chain_discovery_audit.csv", discovery, ["candidate_summary_path", "candidate_stage", "readable", "selected", "final_status", "final_decision"])
    write_json(out / "v21_254_summary.json", summary)
    (out / "V21.254_daily_chain_wrapper_context_block_append_report.txt").write_text(report, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--v21-253-root", type=Path, default=V253_REL)
    a = p.parse_args(argv)
    s = run(a.repo_root.resolve(), a.output_dir, a.v21_253_root)
    for k in [
        "final_status", "final_decision", "latest_daily_chain_summary_found", "latest_daily_chain_final_status",
        "latest_daily_chain_final_decision", "v21_253_context_block_found", "context_section_count", "combined_report_created",
        "append_only", "research_only", "official_adoption_allowed", "broker_action_allowed", "weight_update_allowed",
        "ranking_mutation_allowed", "trade_plan_mutation_allowed", "child_output_mutation_allowed",
        "automatic_ticker_replacement_allowed", "automatic_position_increase_allowed", "automatic_trade_trigger_allowed",
        "market_data_fetch_allowed", "missing_input_count", "warning_count", "error_count",
    ]:
        print(f"{k}={s.get(k)}")
    return 1 if str(s.get("final_status", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
