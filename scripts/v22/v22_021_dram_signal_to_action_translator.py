#!/usr/bin/env python
"""V22.021 DRAM signal-to-action translator.

Read-only translator from V22.020 DRAM research signals into conservative
research-only action states. This module does not fetch data, connect to
brokers, execute chains, mutate historical outputs, place orders, or allow
trades.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any


MODULE_ID = "V22.021"
MODULE_NAME = "DRAM_SIGNAL_TO_ACTION_TRANSLATOR"
STAGE = "V22.021_DRAM_SIGNAL_TO_ACTION_TRANSLATOR"
OUT_REL = Path("outputs") / "v22" / STAGE
PANEL_DATE_UTC = date(2026, 7, 6).isoformat()

V22_020_DIR = Path("outputs") / "v22" / "V22.020_DRAM_DAILY_DECISION_PANEL_R2"
DRAM_PANEL_INPUT = V22_020_DIR / "v22_dram_daily_decision_panel.csv"
DRAM_SIGNAL_INPUT = V22_020_DIR / "v22_dram_signal_to_action_panel.csv"
DRAM_FORWARD_INPUT = V22_020_DIR / "v22_dram_forward_maturity_panel.csv"
DRAM_SUMMARY_INPUT = V22_020_DIR / "v22_dram_daily_decision_panel_summary.json"
DRAM_RISK_STATE_INPUT = V22_020_DIR / "v22_dram_risk_state.json"

OPTIONAL_INPUTS = [
    Path("outputs") / "v22" / "V22.015_FORWARD_ONLY_FACTOR_CONFIRMATION_DASHBOARD" / "v22_forward_only_factor_confirmation_dashboard.csv",
    Path("outputs") / "v22" / "V22.014_MULTIPLE_TESTING_FALSE_DISCOVERY_AUDIT" / "v22_multiple_testing_false_discovery_audit.csv",
    Path("outputs") / "v22" / "V22.013_FACTOR_REDUNDANCY_CLUSTER_AUDIT" / "v22_factor_redundancy_cluster_audit.csv",
    Path("outputs") / "v22" / "V22.011_FACTOR_COVERAGE_AND_MISSINGNESS_AUDIT" / "v22_factor_coverage_audit.csv",
    Path("outputs") / "v21" / "V21.186_DRAM_NO_TRADE_GATE",
    Path("outputs") / "v21" / "V21.184_DRAM_INTRADAY_OUTCOME_DASHBOARD_AND_DECISION_SUMMARY",
    Path("outputs") / "v21" / "V21.185_DRAM_INTRADAY_TRIGGER_EVENT_ARCHIVE_AND_DAILY_APPEND",
]

PASS_STATUS = "PASS_V22_021_DRAM_SIGNAL_TO_ACTION_TRANSLATOR_READY"
WARN_STATUS = "WARN_V22_021_DRAM_SIGNAL_TRANSLATOR_READY_WITH_OPTIONAL_SOURCE_LIMITATIONS"
FAIL_STATUS = "FAIL_V22_021_DRAM_SIGNAL_TRANSLATOR_MISSING_REQUIRED_INPUTS"
READY_DECISION = "DRAM_SIGNAL_TO_ACTION_TRANSLATOR_READY_RESEARCH_ONLY"
FAIL_DECISION = "DRAM_SIGNAL_TO_ACTION_TRANSLATOR_BLOCKED_MISSING_REQUIRED_INPUTS"

NEXT_RECOMMENDED_MODULES = [
    "V22.022_DRAM_MANUAL_TRADE_JOURNAL_SCHEMA",
    "V22.030_ETF_OPTION_UNIVERSE_REGISTRY",
    "V22.031_ETF_OPTION_CONTRACT_SPEC_REGISTRY",
    "V22.050_DAILY_RESEARCH_CHAIN_WITH_ETF_OPTIONS_EXTENSION",
]

NO_ACTION_GATES = {
    "broker_action_allowed": False,
    "official_adoption_allowed": False,
    "trade_allowed": False,
    "market_data_fetch_allowed": False,
    "moomoo_connection_allowed": False,
    "option_chain_fetch_allowed": False,
    "daily_chain_execution_allowed": False,
    "historical_outputs_mutation_allowed": False,
    "cache_mutation_allowed": False,
    "factor_promotion_allowed": False,
    "factor_weight_change_allowed": False,
}

FORBIDDEN_STATES = {
    "BUY_NOW",
    "SELL_NOW",
    "TRADE_ALLOWED",
    "BROKER_ACTION_ALLOWED",
    "AUTO_TRADE",
    "EXECUTE_ORDER",
    "ORDER_READY",
    "ENTRY_APPROVED",
    "EXIT_APPROVED",
}

TRANSLATOR_FIELDNAMES = [
    "panel_date_utc",
    "primary_symbol",
    "signal_name",
    "signal_group",
    "source_status",
    "source_quality",
    "input_signal_status",
    "translated_action_state",
    "action_permission_level",
    "action_blocked",
    "primary_blocker",
    "secondary_blockers",
    "paper_review_allowed",
    "manual_review_required",
    "broker_action_allowed",
    "official_adoption_allowed",
    "trade_allowed",
    "research_only",
    "next_required_validation",
    "reason",
]

POLICY_FIELDNAMES = [
    "policy_name",
    "policy_group",
    "trigger_condition",
    "translated_action_state",
    "action_permission_level",
    "broker_action_allowed",
    "official_adoption_allowed",
    "trade_allowed",
    "reason",
]

BLOCKER_FIELDNAMES = [
    "blocker_name",
    "blocker_type",
    "blocker_severity",
    "triggered",
    "source_signal",
    "source_path",
    "recommended_next_step",
    "broker_action_allowed",
    "trade_allowed",
    "reason",
]

READINESS_FIELDNAMES = [
    "readiness_group",
    "signal_count",
    "observe_only_count",
    "wait_forward_maturity_count",
    "review_local_plan_count",
    "paper_review_only_count",
    "blocked_count",
    "manual_review_required_count",
    "broker_action_allowed_count",
    "official_adoption_allowed_count",
    "trade_allowed_count",
    "group_recommendation",
]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="", errors="ignore") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def validate_output_dir(repo_root: Path, output_dir: Path) -> None:
    expected = (repo_root / OUT_REL).resolve()
    if output_dir.resolve() != expected:
        raise ValueError(f"V22.021 output directory must be {expected}, got {output_dir.resolve()}")


def required_flags(repo_root: Path) -> dict[str, bool]:
    return {
        "dram_panel_input_exists": (repo_root / DRAM_PANEL_INPUT).exists(),
        "dram_signal_input_exists": (repo_root / DRAM_SIGNAL_INPUT).exists(),
        "dram_forward_input_exists": (repo_root / DRAM_FORWARD_INPUT).exists(),
        "dram_summary_input_exists": (repo_root / DRAM_SUMMARY_INPUT).exists(),
        "dram_risk_state_input_exists": (repo_root / DRAM_RISK_STATE_INPUT).exists(),
    }


def optional_missing_count(repo_root: Path) -> int:
    return sum(1 for rel_path in OPTIONAL_INPUTS if not (repo_root / rel_path).exists())


def bool_from_text(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def policy_rows() -> list[dict[str, Any]]:
    specs = [
        ("FORWARD_PENDING_MATURITY_POLICY", "FORWARD_MATURITY", "forward status is FORWARD_PENDING_MATURITY", "WAIT_FORWARD_MATURITY", "RESEARCH_ONLY"),
        ("MISSING_LOCAL_PLAN_POLICY", "SOURCE", "local DRAM plan source missing", "BLOCKED_BY_NO_LOCAL_PLAN_SOURCE", "BLOCKED"),
        ("STALE_SOURCE_POLICY", "SOURCE", "plan currentness is stale blocking", "BLOCKED_BY_STALE_SOURCE", "BLOCKED"),
        ("NO_TRADE_GATE_POLICY", "RISK", "no-trade gate explicitly blocks", "BLOCKED_BY_NO_TRADE_GATE", "BLOCKED"),
        ("RISK_GATE_POLICY", "RISK", "permission gate is unsafe or risk-gate label present", "BLOCKED_BY_RISK_GATE", "BLOCKED"),
        ("OPTION_EXTENSION_PLACEHOLDER_POLICY", "OPTIONS", "option extension placeholder signal", "BLOCKED_BY_PLACEHOLDER_OPTION_EXTENSION", "BLOCKED"),
        ("PAPER_REVIEW_POLICY", "REVIEW", "local plan exists but needs review", "REVIEW_LOCAL_PLAN_ONLY", "PAPER_REVIEW_ONLY"),
        ("MANUAL_REVIEW_POLICY", "REVIEW", "manual review required by source signal", "PAPER_REVIEW_ONLY", "PAPER_REVIEW_ONLY"),
    ]
    return [
        {
            "policy_name": name,
            "policy_group": group,
            "trigger_condition": condition,
            "translated_action_state": state,
            "action_permission_level": permission,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "trade_allowed": False,
            "reason": "Policy translates DRAM signals to conservative research-only states.",
        }
        for name, group, condition, state, permission in specs
    ]


def risk_gate_violation(risk_state: dict[str, Any]) -> bool:
    for key in ["broker_action_allowed", "official_adoption_allowed", "trade_allowed", "market_data_fetch_allowed", "moomoo_connection_allowed", "option_chain_fetch_allowed", "daily_chain_execution_allowed"]:
        if risk_state.get(key) is not False:
            return True
    return False


def translate_signal(signal: dict[str, str], panel: dict[str, str], risk_state: dict[str, Any]) -> dict[str, Any]:
    group = signal.get("signal_group", "")
    status = signal.get("signal_status", "")
    final_label = panel.get("final_research_action_label", "")
    plan_currentness = panel.get("plan_currentness_status", "")
    source_status = panel.get("source_status", "")
    forward_status = panel.get("forward_confirmation_status_from_v22_015", "")
    no_trade_status = panel.get("no_trade_gate_status", "")
    state = "OBSERVE_ONLY"
    permission = "RESEARCH_ONLY"
    blocker = ""
    secondary: list[str] = []
    manual_review = "REVIEW" in status or "REVIEW" in final_label or "REVIEW" in plan_currentness
    paper_review = manual_review

    if risk_gate_violation(risk_state) or final_label == "DRAM_BLOCKED_BY_RISK_GATE":
        state, permission, blocker = "BLOCKED_BY_RISK_GATE", "BLOCKED", "RISK_GATE"
    elif group == "OPTION_EXTENSION_PLACEHOLDER" or "OPTION" in group:
        state, permission, blocker = "BLOCKED_BY_PLACEHOLDER_OPTION_EXTENSION", "BLOCKED", "OPTION_EXTENSION_PLACEHOLDER"
    elif "BLOCK" in no_trade_status or final_label == "DRAM_BLOCKED_BY_NO_TRADE_GATE":
        state, permission, blocker = "BLOCKED_BY_NO_TRADE_GATE", "BLOCKED", "NO_TRADE_GATE"
    elif source_status == "LOCAL_DRAM_SOURCE_MISSING" or final_label == "DRAM_BLOCKED_BY_NO_LOCAL_PLAN_SOURCE":
        state, permission, blocker = "BLOCKED_BY_NO_LOCAL_PLAN_SOURCE", "BLOCKED", "SOURCE_MISSING"
    elif final_label == "DRAM_BLOCKED_BY_STALE_SOURCE" or plan_currentness == "STALE_BLOCKING":
        state, permission, blocker = "BLOCKED_BY_STALE_SOURCE", "BLOCKED", "SOURCE_STALE"
    elif forward_status == "FORWARD_PENDING_MATURITY" or status == "FORWARD_PENDING_MATURITY":
        state, permission, blocker = "WAIT_FORWARD_MATURITY", "RESEARCH_ONLY", "FORWARD_MATURITY"
    elif group == "DAILY_PLAN" and ("REVIEW" in final_label or "REVIEW" in status):
        state, permission, blocker = "REVIEW_LOCAL_PLAN_ONLY", "PAPER_REVIEW_ONLY", "MANUAL_REVIEW_REQUIRED"
    elif manual_review:
        state, permission, blocker = "PAPER_REVIEW_ONLY", "PAPER_REVIEW_ONLY", "MANUAL_REVIEW_REQUIRED"

    if panel.get("primary_blocker") and panel.get("primary_blocker") != blocker:
        secondary.append(panel.get("primary_blocker", ""))
    if panel.get("secondary_blockers"):
        secondary.append(panel.get("secondary_blockers", ""))
    if state in FORBIDDEN_STATES:
        state = "REVIEW_REQUIRED"
        permission = "BLOCKED"
        blocker = "MANUAL_REVIEW_REQUIRED"
    return {
        "panel_date_utc": panel.get("panel_date_utc", PANEL_DATE_UTC),
        "primary_symbol": panel.get("primary_symbol", "DRAM"),
        "signal_name": signal.get("signal_name", ""),
        "signal_group": group,
        "source_status": source_status,
        "source_quality": signal.get("source_quality", ""),
        "input_signal_status": status,
        "translated_action_state": state,
        "action_permission_level": permission,
        "action_blocked": permission == "BLOCKED",
        "primary_blocker": blocker,
        "secondary_blockers": ";".join(value for value in secondary if value),
        "paper_review_allowed": permission in {"PAPER_REVIEW_ONLY", "RESEARCH_ONLY"},
        "manual_review_required": manual_review or permission == "BLOCKED",
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "trade_allowed": False,
        "research_only": True,
        "next_required_validation": "Complete DRAM forward maturity and manual review before any future policy discussion.",
        "reason": "Translated from V22.020 signal to research-only state; no trade or broker permission is granted.",
    }


def blocker_rows(panel: dict[str, str], risk_state: dict[str, Any], optional_missing: int) -> list[dict[str, Any]]:
    final_label = panel.get("final_research_action_label", "")
    rows = [
        ("Forward maturity pending", "FORWARD_MATURITY", "MAJOR", panel.get("forward_confirmation_status_from_v22_015") == "FORWARD_PENDING_MATURITY", "FORWARD_CONFIRMATION", "Accumulate 5D/10D/20D forward observations."),
        ("Local source missing", "SOURCE_MISSING", "BLOCKING", panel.get("source_status") == "LOCAL_DRAM_SOURCE_MISSING", "DAILY_PLAN", "Restore or review local DRAM plan source."),
        ("Source stale blocking", "SOURCE_STALE", "BLOCKING", panel.get("plan_currentness_status") == "STALE_BLOCKING", "DAILY_PLAN", "Refresh local plan through approved manual research workflow."),
        ("No trade gate block", "NO_TRADE_GATE", "BLOCKING", "BLOCK" in panel.get("no_trade_gate_status", ""), "NO_TRADE_GATE", "Resolve no-trade gate before paper review."),
        ("Risk gate block", "RISK_GATE", "BLOCKING", risk_gate_violation(risk_state) or final_label == "DRAM_BLOCKED_BY_RISK_GATE", "PERSONAL_RISK_RULE", "Keep all risk gates closed; investigate any unsafe permission."),
        ("Option extension placeholder", "OPTION_EXTENSION_PLACEHOLDER", "MAJOR", panel.get("option_extension_status") == "NOT_YET_INGESTED", "OPTION_EXTENSION_PLACEHOLDER", "Wait for V22.030/V22.031 option registries."),
        ("Manual review required", "MANUAL_REVIEW_REQUIRED", "MAJOR", "REVIEW" in final_label or optional_missing > 0, "DAILY_PLAN", "Manual research review required before paper planning."),
    ]
    return [
        {
            "blocker_name": name,
            "blocker_type": blocker_type,
            "blocker_severity": severity,
            "triggered": triggered,
            "source_signal": source_signal,
            "source_path": "",
            "recommended_next_step": next_step,
            "broker_action_allowed": False,
            "trade_allowed": False,
            "reason": "Blocker audit is informational and cannot grant trade permission.",
        }
        for name, blocker_type, severity, triggered, source_signal, next_step in rows
    ]


def readiness_rows(translated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in sorted({row["signal_group"] for row in translated}):
        members = [row for row in translated if row["signal_group"] == group]
        rows.append(readiness_row(group, members))
    rows.append(readiness_row("ALL_SIGNALS", translated))
    return rows


def readiness_row(group: str, members: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "readiness_group": group,
        "signal_count": len(members),
        "observe_only_count": sum(1 for row in members if row["translated_action_state"] == "OBSERVE_ONLY"),
        "wait_forward_maturity_count": sum(1 for row in members if row["translated_action_state"] == "WAIT_FORWARD_MATURITY"),
        "review_local_plan_count": sum(1 for row in members if row["translated_action_state"] == "REVIEW_LOCAL_PLAN_ONLY"),
        "paper_review_only_count": sum(1 for row in members if row["translated_action_state"] == "PAPER_REVIEW_ONLY"),
        "blocked_count": sum(1 for row in members if row["action_permission_level"] == "BLOCKED"),
        "manual_review_required_count": sum(1 for row in members if row["manual_review_required"] is True),
        "broker_action_allowed_count": 0,
        "official_adoption_allowed_count": 0,
        "trade_allowed_count": 0,
        "group_recommendation": "Research-only; do not translate to broker or trade action.",
    }


def final_state(translated: list[dict[str, Any]], panel: dict[str, str]) -> tuple[str, str]:
    severe = [row for row in translated if row["action_permission_level"] == "BLOCKED" and row["primary_blocker"] not in {"OPTION_EXTENSION_PLACEHOLDER"}]
    if severe:
        return severe[0]["translated_action_state"], "BLOCKED"
    if panel.get("forward_confirmation_status_from_v22_015") == "FORWARD_PENDING_MATURITY":
        return "WAIT_FORWARD_MATURITY", "RESEARCH_ONLY"
    if any(row["translated_action_state"] == "REVIEW_LOCAL_PLAN_ONLY" for row in translated):
        return "REVIEW_LOCAL_PLAN_ONLY", "PAPER_REVIEW_ONLY"
    return "OBSERVE_ONLY", "RESEARCH_ONLY"


def summary_payload(
    repo_root: Path,
    translated: list[dict[str, Any]],
    policies: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    panel: dict[str, str],
    optional_missing: int,
) -> dict[str, Any]:
    flags = required_flags(repo_root)
    if not all(flags.values()):
        final_status = FAIL_STATUS
        final_decision = FAIL_DECISION
    elif optional_missing:
        final_status = WARN_STATUS
        final_decision = READY_DECISION
    else:
        final_status = PASS_STATUS
        final_decision = READY_DECISION
    final_action, final_permission = final_state(translated, panel) if translated else ("REVIEW_REQUIRED", "BLOCKED")
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "final_status": final_status,
        "final_decision": final_decision,
        **flags,
        "translated_signal_count": len(translated),
        "policy_count": len(policies),
        "blocker_count": len(blockers),
        "triggered_blocker_count": sum(1 for row in blockers if row["triggered"] is True),
        "observe_only_count": sum(1 for row in translated if row["translated_action_state"] == "OBSERVE_ONLY"),
        "wait_forward_maturity_count": sum(1 for row in translated if row["translated_action_state"] == "WAIT_FORWARD_MATURITY"),
        "review_local_plan_count": sum(1 for row in translated if row["translated_action_state"] == "REVIEW_LOCAL_PLAN_ONLY"),
        "paper_review_only_count": sum(1 for row in translated if row["translated_action_state"] == "PAPER_REVIEW_ONLY"),
        "blocked_count": sum(1 for row in translated if row["action_permission_level"] == "BLOCKED"),
        "manual_review_required_count": sum(1 for row in translated if row["manual_review_required"] is True),
        "final_translated_action_state": final_action,
        "final_action_permission_level": final_permission,
        "protected_outputs_modified": False,
        "research_only": True,
        "next_recommended_modules": NEXT_RECOMMENDED_MODULES,
        **NO_ACTION_GATES,
    }


def risk_gate_payload() -> dict[str, Any]:
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "allowed_side_effects": ["create_outputs_v22_021_only"],
        "forbidden_side_effects": [
            "execute_daily_chain",
            "connect_moomoo",
            "fetch_market_data",
            "fetch_option_chain",
            "mutate_v21_outputs",
            "mutate_cache",
            "create_trade_order",
            "modify_broker_state",
            "promote_factor",
            "promote_strategy",
            "change_factor_weight",
        ],
        **NO_ACTION_GATES,
    }


def report_text(summary: dict[str, Any]) -> str:
    lines = [
        "V22.021 DRAM Signal-To-Action Translator",
        f"module_id={summary['module_id']}",
        f"module_name={summary['module_name']}",
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"translated_signal_count={summary['translated_signal_count']}",
        f"final_translated_action_state={summary['final_translated_action_state']}",
        f"final_action_permission_level={summary['final_action_permission_level']}",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
        "trade_allowed=False",
        "market_data_fetch_allowed=False",
        "moomoo_connection_allowed=False",
        "option_chain_fetch_allowed=False",
        "daily_chain_execution_allowed=False",
        "protected_outputs_modified=False",
    ]
    return "\n".join(lines) + "\n"


def run(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = repo_root / OUT_REL
    validate_output_dir(repo_root, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    panels = read_csv_rows(repo_root / DRAM_PANEL_INPUT)
    signals = read_csv_rows(repo_root / DRAM_SIGNAL_INPUT)
    _forward = read_csv_rows(repo_root / DRAM_FORWARD_INPUT)
    _summary = read_json(repo_root / DRAM_SUMMARY_INPUT)
    risk_state = read_json(repo_root / DRAM_RISK_STATE_INPUT)
    panel = panels[0] if panels else {}
    translated: list[dict[str, Any]] = []
    if all(required_flags(repo_root).values()):
        translated = [translate_signal(signal, panel, risk_state) for signal in signals]
    policies = policy_rows()
    optional_missing = optional_missing_count(repo_root)
    blockers = blocker_rows(panel, risk_state, optional_missing) if panel else []
    readiness = readiness_rows(translated)
    summary = summary_payload(repo_root, translated, policies, blockers, panel, optional_missing)

    write_csv(output_dir / "v22_dram_signal_to_action_translator.csv", TRANSLATOR_FIELDNAMES, translated)
    write_csv(output_dir / "v22_dram_action_policy_table.csv", POLICY_FIELDNAMES, policies)
    write_csv(output_dir / "v22_dram_action_blocker_audit.csv", BLOCKER_FIELDNAMES, blockers)
    write_csv(output_dir / "v22_dram_action_readiness_summary.csv", READINESS_FIELDNAMES, readiness)
    write_json(output_dir / "v22_dram_signal_to_action_summary.json", summary)
    write_json(output_dir / "v22_dram_signal_to_action_risk_gate.json", risk_gate_payload())
    (output_dir / "V22.021_dram_signal_to_action_translator_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    args = parser.parse_args(argv)
    payload = run(args.repo_root)
    print(f"final_status={payload['final_status']}")
    print(f"final_decision={payload['final_decision']}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_dram_signal_to_action_summary.json'}")
    print("broker_action_allowed=False")
    print("official_adoption_allowed=False")
    print("trade_allowed=False")
    return 1 if payload["final_status"] == FAIL_STATUS else 0


if __name__ == "__main__":
    raise SystemExit(main())
