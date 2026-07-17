#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

STAGE = "V21.253_DAILY_RESEARCH_CHAIN_CONTEXT_BLOCK_INTEGRATION_R1"
OUT_REL = Path("outputs/v21") / STAGE
V252_REL = Path("outputs/v21/V21.252_DRAM_ONLY_STRATEGY_GOVERNANCE_COMPATIBILITY_AND_BOUNDARY_R1")
V251_REL = Path("outputs/v21/V21.251_STRATEGY_WEIGHT_GOVERNANCE_FROM_V21_255_AND_CURRENT_REGIME_R1")
V250_REL = Path("outputs/v21/V21.250_TECHNICAL_DIAGNOSTIC_FREEZE_AND_MANUAL_CHECKLIST_ARCHIVE_R1")
CHAIN_HINTS = ("V21.201", "V21.232", "V21.234", "V21.241")
GATES = {
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "factor_promotion_allowed": False,
    "weight_update_allowed": False,
    "ranking_mutation_allowed": False,
    "trade_plan_mutation_allowed": False,
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


def write_json(path: Path, data: Any) -> None:
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
    return any(h in path.name for h in CHAIN_HINTS) or "DAILY" in name or "RETENTION" in name or ("DRAM" in name and "GOVERNANCE" not in name and "BOUNDARY" not in name)


def discover_latest_chain_summary(repo: Path) -> tuple[Path | None, dict[str, Any], list[dict[str, Any]]]:
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
        usable = bool(data)
        audit.append({"candidate_summary_path": str(p), "candidate_stage": p.parent.name, "readable": usable, "selected": False, "final_status": data.get("final_status", ""), "final_decision": data.get("final_decision", "")})
        if usable and chosen_path is None:
            chosen_path, chosen_summary = p, data
    if chosen_path:
        for row in audit:
            row["selected"] = row["candidate_summary_path"] == str(chosen_path)
    return chosen_path, chosen_summary, audit


def context_rows(s252: dict[str, Any], s251: dict[str, Any], s250: dict[str, Any], chain_path: Path | None, chain: dict[str, Any]) -> list[dict[str, Any]]:
    latest_status = chain.get("final_status", "")
    latest_decision = chain.get("final_decision", "")
    return [
        {"section": "DRAM_PRIMARY_FOCUS_STATUS", "context_key": "dram_primary_focus_active", "context_value": s252.get("dram_primary_focus_active", True), "source": "V21.252", "allowed_use": "DAILY_REPORT_CONTEXT", "blocked_use": "TICKER_REPLACEMENT"},
        {"section": "LATEST_DRAM_CHAIN_STATUS", "context_key": "latest_dram_final_status", "context_value": latest_status, "source": str(chain_path or ""), "allowed_use": "DAILY_STATUS_CONTEXT", "blocked_use": "TRADE_PLAN_MUTATION"},
        {"section": "LATEST_DRAM_CHAIN_STATUS", "context_key": "latest_dram_final_decision", "context_value": latest_decision, "source": str(chain_path or ""), "allowed_use": "DAILY_STATUS_CONTEXT", "blocked_use": "BROKER_ACTION"},
        {"section": "STRATEGY_GOVERNANCE_CONTEXT", "context_key": "current_regime_shadow_primary", "context_value": s251.get("current_regime_shadow_primary", ""), "source": "V21.251", "allowed_use": "RESEARCH_CONTEXT_ONLY", "blocked_use": "OFFICIAL_ADOPTION"},
        {"section": "STRATEGY_GOVERNANCE_CONTEXT", "context_key": "long_history_fallback", "context_value": s251.get("long_history_fallback", ""), "source": "V21.251", "allowed_use": "RISK_REVIEW_ONLY", "blocked_use": "WEIGHT_UPDATE"},
        {"section": "STRATEGY_GOVERNANCE_CONTEXT", "context_key": "high_return_watch_only", "context_value": s251.get("high_return_watch_only", ""), "source": "V21.251", "allowed_use": "WATCH_ONLY", "blocked_use": "POSITION_CHANGE"},
        {"section": "TECHNICAL_FREEZE_STATUS", "context_key": "technical_checklist_observation_only", "context_value": s250.get("technical_manual_checklist_allowed", True), "source": "V21.250", "allowed_use": "MANUAL_OBSERVATION_ONLY", "blocked_use": "AUTOMATIC_TRADE_TRIGGER"},
        {"section": "TECHNICAL_FREEZE_STATUS", "context_key": "technical_model_entry_allowed", "context_value": False, "source": "V21.250", "allowed_use": "NO_MODEL_ENTRY", "blocked_use": "MODEL_INTEGRATION"},
        {"section": "RETENTION_AND_CACHE_GUARD_STATUS", "context_key": "retention_guard_status_found", "context_value": bool(chain_path and ("RETENTION" in chain_path.parent.name.upper() or "V21.241" in chain_path.parent.name)), "source": str(chain_path or ""), "allowed_use": "GUARD_STATUS_CONTEXT", "blocked_use": "CACHE_MUTATION"},
        {"section": "RETENTION_AND_CACHE_GUARD_STATUS", "context_key": "latest_plan_currentness", "context_value": chain.get("latest_dram_plan_currentness", chain.get("plan_currentness", "")), "source": str(chain_path or ""), "allowed_use": "CURRENTNESS_CONTEXT", "blocked_use": "MARKET_DATA_FETCH"},
        {"section": "BROKER_AND_ACTION_GATE_STATUS", "context_key": "broker_action_allowed", "context_value": False, "source": "V21.252", "allowed_use": "GATE_STATUS", "blocked_use": "BROKER_ACTION"},
        {"section": "BROKER_AND_ACTION_GATE_STATUS", "context_key": "no_automatic_ticker_replacement", "context_value": True, "source": "V21.252", "allowed_use": "GATE_STATUS", "blocked_use": "TICKER_REPLACEMENT"},
        {"section": "BROKER_AND_ACTION_GATE_STATUS", "context_key": "no_automatic_position_increase", "context_value": True, "source": "V21.252", "allowed_use": "GATE_STATUS", "blocked_use": "POSITION_INCREASE"},
        {"section": "BROKER_AND_ACTION_GATE_STATUS", "context_key": "no_automatic_trade_trigger", "context_value": True, "source": "V21.252", "allowed_use": "GATE_STATUS", "blocked_use": "TRADE_TRIGGER"},
        {"section": "BROKER_AND_ACTION_GATE_STATUS", "context_key": "no_ranking_mutation", "context_value": True, "source": "V21.252", "allowed_use": "GATE_STATUS", "blocked_use": "RANKING_MUTATION"},
        {"section": "BROKER_AND_ACTION_GATE_STATUS", "context_key": "no_weight_update", "context_value": True, "source": "V21.252", "allowed_use": "GATE_STATUS", "blocked_use": "WEIGHT_UPDATE"},
    ]


def recommendations() -> list[dict[str, Any]]:
    return [
        {"recommendation": "APPEND_CONTEXT_BLOCK_AFTER_DAILY_RESULT_SUMMARY", "detail": "Append this block after the daily result summary.", "allowed": True, "mutation_allowed": False},
        {"recommendation": "DO_NOT_MUTATE_RANKING_OUTPUTS", "detail": "Ranking outputs must remain unchanged.", "allowed": False, "mutation_allowed": False},
        {"recommendation": "DO_NOT_MUTATE_DRAM_TRADE_PLAN", "detail": "DRAM trade plans must remain unchanged.", "allowed": False, "mutation_allowed": False},
        {"recommendation": "DO_NOT_ALTER_BROKER_ACTION_GATES", "detail": "Broker/action gates stay locked.", "allowed": False, "mutation_allowed": False},
        {"recommendation": "DO_NOT_FETCH_MARKET_DATA", "detail": "No provider or market data fetch is allowed.", "allowed": False, "mutation_allowed": False},
    ]


def gate_audit(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [{"gate_name": "research_only", "expected": True, "observed": True, "passed": True}]
    for key, expected in GATES.items():
        rows.append({"gate_name": key, "expected": expected, "observed": summary.get(key), "passed": summary.get(key) == expected})
    return rows


def report_text(rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    by_section: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_section.setdefault(row["section"], []).append(row)
    lines = ["V21.253 Daily Research Context Block", f"final_status={summary['final_status']}", ""]
    for section, items in by_section.items():
        lines.append(f"[{section}]")
        for item in items:
            lines.append(f"- {item['context_key']}: {item['context_value']} ({item['allowed_use']}; blocked={item['blocked_use']})")
        lines.append("")
    lines.append("No official adoption, broker action, ranking mutation, weight update, trade plan mutation, automatic ticker replacement, automatic position increase, automatic trade trigger, protected output mutation, or market data fetch is allowed.")
    return "\n".join(lines) + "\n"


def fail_summary(status: str, decision: str, missing: int) -> dict[str, Any]:
    return {
        "final_status": status,
        "final_decision": decision,
        "context_section_count": 0,
        "latest_dram_summary_found": False,
        "latest_dram_final_status": "",
        "latest_dram_final_decision": "",
        "dram_primary_focus_active": False,
        "strategy_governance_research_context_only": False,
        "strategy_governance_risk_review_only": False,
        "technical_checklist_observation_only": False,
        "technical_freeze_enforced": False,
        "current_regime_shadow_primary": "",
        "long_history_fallback": "",
        "high_return_watch_only": "",
        "retention_guard_status_found": False,
        "missing_input_count": missing,
        "warning_count": 0,
        "error_count": 1,
        **GATES,
    }


def has_gate_violation(summary: dict[str, Any]) -> bool:
    return any(summary.get(k) is True for k in GATES if k != "protected_outputs_modified") or summary.get("protected_outputs_modified") is True


def run(repo: Path, output_dir: Path | None = None, v252_root: Path = V252_REL, v251_root: Path = V251_REL, v250_root: Path = V250_REL) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    s252 = read_json(root(repo, v252_root) / "v21_252_summary.json")
    s251 = read_json(root(repo, v251_root) / "v21_251_summary.json")
    s250 = read_json(root(repo, v250_root) / "v21_250_summary.json")
    missing = [name for name, data in [("V21.252 summary", s252), ("V21.251 summary", s251), ("V21.250 summary", s250)] if not data]
    # V21.250--V21.252 are archival research-context producers.  Their
    # absence must never manufacture a technical signal, but it also must not
    # make an otherwise read-only daily chain unusable.  Continue with an
    # explicitly conservative context: all action gates remain false and the
    # missing provenance is carried in the summary/report.

    chain_path, chain, discovery = discover_latest_chain_summary(repo)
    rows = context_rows(s252, s251, s250, chain_path, chain)
    sections = sorted({r["section"] for r in rows})
    technical_freeze_enforced = (
        s250.get("model_entry_allowed", False) is False
        and s250.get("technical_timing_overlay_allowed", False) is False
        and s250.get("technical_context_filter_allowed", False) is False
        and s250.get("technical_manual_checklist_allowed", True) is True
    )
    retention_found = bool(chain_path and ("RETENTION" in chain_path.parent.name.upper() or "V21.241" in chain_path.parent.name))
    summary = {
        "final_status": "PASS_V21_253_DAILY_CONTEXT_BLOCK_READY_WITH_LEGACY_CONTEXT_UNAVAILABLE" if missing else ("PASS_V21_253_DAILY_CONTEXT_BLOCK_READY_RESEARCH_ONLY" if chain_path else "WARN_V21_253_DAILY_CONTEXT_BLOCK_READY_WITH_MISSING_DRAM_SUMMARY"),
        "final_decision": "DAILY_RESEARCH_CONTEXT_BLOCK_CONSERVATIVE_LEGACY_CONTEXT_UNAVAILABLE" if missing else ("DAILY_RESEARCH_CONTEXT_BLOCK_READY_RESEARCH_ONLY" if chain_path else "DAILY_CONTEXT_BLOCK_READY_WITH_MISSING_DRAM_CONTEXT"),
        "context_section_count": len(sections),
        "latest_dram_summary_found": bool(chain_path),
        "latest_dram_final_status": chain.get("final_status", ""),
        "latest_dram_final_decision": chain.get("final_decision", ""),
        "dram_primary_focus_active": s252.get("dram_primary_focus_active", True) is True,
        "strategy_governance_research_context_only": s252.get("strategy_governance_research_context_only", True) is True,
        "strategy_governance_risk_review_only": s252.get("strategy_governance_risk_review_only", True) is True,
        "technical_checklist_observation_only": s250.get("technical_manual_checklist_allowed", True) is True,
        "technical_freeze_enforced": technical_freeze_enforced,
        "current_regime_shadow_primary": s251.get("current_regime_shadow_primary", ""),
        "long_history_fallback": s251.get("long_history_fallback", ""),
        "high_return_watch_only": s251.get("high_return_watch_only", ""),
        "retention_guard_status_found": retention_found,
        "missing_input_count": len(missing),
        "missing_context_inputs": missing,
        "legacy_context_available": not missing,
        "warning_count": len(missing) if missing else (0 if chain_path else 1),
        "error_count": 0,
        **GATES,
    }
    if not summary["dram_primary_focus_active"] or not technical_freeze_enforced or has_gate_violation(summary):
        summary["final_status"] = "FAIL_V21_253_DAILY_CONTEXT_BLOCK_GATE_VIOLATION"
        summary["final_decision"] = "DAILY_CONTEXT_BLOCK_BLOCKED_GATE_VIOLATION"
        summary["error_count"] = 1
    write_outputs(out, rows, recommendations(), gate_audit(summary), discovery, summary)
    return summary


def write_outputs(out: Path, rows: list[dict[str, Any]], recs: list[dict[str, Any]], gates: list[dict[str, Any]], discovery: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "daily_research_context_block.csv", rows, ["section", "context_key", "context_value", "source", "allowed_use", "blocked_use"])
    write_json(out / "daily_research_context_block.json", {"summary": summary, "context": rows})
    (out / "daily_research_context_block_for_report.txt").write_text(report_text(rows, summary), encoding="utf-8")
    write_csv(out / "daily_chain_context_integration_recommendation.csv", recs, ["recommendation", "detail", "allowed", "mutation_allowed"])
    write_csv(out / "gate_status_context_audit.csv", gates, ["gate_name", "expected", "observed", "passed"])
    write_csv(out / "latest_dram_chain_discovery_audit.csv", discovery, ["candidate_summary_path", "candidate_stage", "readable", "selected", "final_status", "final_decision"])
    write_json(out / "v21_253_summary.json", summary)
    (out / "V21.253_daily_research_chain_context_block_report.txt").write_text(report_text(rows, summary), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--v21-252-root", type=Path, default=V252_REL)
    p.add_argument("--v21-251-root", type=Path, default=V251_REL)
    p.add_argument("--v21-250-root", type=Path, default=V250_REL)
    a = p.parse_args(argv)
    s = run(a.repo_root.resolve(), a.output_dir, a.v21_252_root, a.v21_251_root, a.v21_250_root)
    for k in [
        "final_status", "final_decision", "context_section_count", "latest_dram_summary_found", "latest_dram_final_status",
        "latest_dram_final_decision", "dram_primary_focus_active", "strategy_governance_research_context_only",
        "strategy_governance_risk_review_only", "technical_checklist_observation_only", "technical_freeze_enforced",
        "current_regime_shadow_primary", "long_history_fallback", "high_return_watch_only", "retention_guard_status_found",
        "broker_action_allowed", "official_adoption_allowed", "weight_update_allowed", "ranking_mutation_allowed",
        "trade_plan_mutation_allowed", "automatic_ticker_replacement_allowed", "automatic_position_increase_allowed",
        "automatic_trade_trigger_allowed", "market_data_fetch_allowed", "missing_input_count", "warning_count", "error_count",
    ]:
        print(f"{k}={s.get(k)}")
    return 1 if str(s.get("final_status", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
