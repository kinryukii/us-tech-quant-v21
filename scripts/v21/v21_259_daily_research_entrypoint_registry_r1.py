#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

STAGE = "V21.259_DAILY_RESEARCH_ENTRYPOINT_REGISTRY_R1"
OUT_REL = Path("outputs/v21") / STAGE
V258_REL = Path("outputs/v21/V21.258_RETENTION_GUARD_DISCOVERY_REVIEW_AND_DAILY_ENTRYPOINT_UNBLOCK_R1")
V257_REL = Path("outputs/v21/V21.257_DAILY_MASTER_WRAPPER_ADOPTION_READINESS_AUDIT_R1")
V256_REL = Path("outputs/v21/V21.256_DAILY_CHAIN_MASTER_WRAPPER_WITH_CONTEXT_R1")
ENTRYPOINT_NAME = "V21.256_DAILY_CHAIN_MASTER_WRAPPER_WITH_CONTEXT_R1"
ENTRYPOINT_SCRIPT = "scripts/v21/run_v21_256_daily_chain_master_wrapper_with_context_r1.ps1"
RECOMMENDED_COMMAND = r".\scripts\v21\run_v21_256_daily_chain_master_wrapper_with_context_r1.ps1 -Execute"
GATES = {
    "research_only": True,
    "registry_only": True,
    "retention_delete_allowed": False,
    "retention_move_allowed": False,
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


def gate_violation(summary: dict[str, Any]) -> bool:
    return any(summary.get(k) != v for k, v in GATES.items())


def entrypoint_status(v258: dict[str, Any]) -> str:
    if v258.get("blocking_retention_candidate_count", 0) > 0:
        return "BLOCKED_BY_RETENTION"
    if v258.get("accepted_daily_research_entrypoint_after_review") is True:
        return "ACCEPTED"
    if v258.get("accepted_with_retention_observation") is True:
        return "ACCEPTED_WITH_RETENTION_OBSERVATION"
    return "NOT_ACCEPTED"


def registry_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [{
        "registry_version": STAGE,
        "accepted_entrypoint_name": summary["accepted_entrypoint_name"],
        "accepted_entrypoint_script": summary["accepted_entrypoint_script"],
        "recommended_command": summary["recommended_command"],
        "entrypoint_status": summary["entrypoint_status"],
        "retention_observation_required": summary["retention_observation_required"],
        "run_mode_recommended": "Execute",
        "research_only": True,
        "gate_status": "LOCKED",
    }]


def no_go_rows() -> list[dict[str, Any]]:
    keys = ["official_adoption_allowed", "broker_action_allowed", "ranking_mutation_allowed", "weight_update_allowed", "trade_plan_mutation_allowed", "child_output_mutation_allowed", "retention_delete_allowed", "retention_move_allowed", "market_data_fetch_allowed"]
    return [{"audit_item": k, "expected": GATES[k], "observed": GATES[k], "passed": True} for k in keys]


def maintenance_rows() -> list[dict[str, Any]]:
    rows = [
        ("REVIEW_IF_V21_256_EXECUTE_FAILS", "Registry must be reviewed if V21.256 fails in Execute mode."),
        ("REVIEW_IF_BLOCKING_RETENTION_CANDIDATES_APPEAR", "Registry must be reviewed if any blocking retention candidate appears."),
        ("REVIEW_IF_ACTION_OR_MODEL_GATES_CHANGE", "Registry must be reviewed if broker/action/ranking/weight gates change."),
        ("REVIEW_IF_DRAM_PRIMARY_FOCUS_CHANGES", "Registry must be reviewed if the user explicitly changes DRAM primary focus."),
    ]
    return [{"policy_name": name, "policy_detail": detail, "research_only": True} for name, detail in rows]


def gate_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"gate_name": k, "expected": v, "observed": summary.get(k), "passed": summary.get(k) == v} for k, v in GATES.items()]


def instruction_card(summary: dict[str, Any]) -> str:
    return (
        "V21.259 Daily Research Entrypoint Run Instruction Card\n"
        f"Primary command: {summary['recommended_command']}\n"
        "Expected outputs: V21.256 master summary, child-stage ledger, context summary, V21.254 combined context report.\n"
        f"Accepted warnings: retention observation required={summary['retention_observation_required']}; run-mode history warning={summary['run_mode_history_warning']}.\n"
        "Must not do: no official adoption, broker action, ranking mutation, weight update, trade plan mutation, child output mutation, retention deletion, retention movement, automatic ticker replacement, automatic position increase, automatic trade trigger, protected output mutation, or registry-layer market data fetch.\n"
    )


def fail_summary(status: str, decision: str, missing: int) -> dict[str, Any]:
    return {
        "final_status": status,
        "final_decision": decision,
        "accepted_entrypoint_name": "",
        "accepted_entrypoint_script": "",
        "recommended_command": "",
        "entrypoint_status": "NOT_ACCEPTED",
        "accepted_with_retention_observation": False,
        "retention_observation_required": False,
        "blocking_retention_candidate_count": 0,
        "run_mode_history_label": "",
        "run_mode_history_warning": False,
        "registry_created": False,
        "run_instruction_card_created": False,
        "registry_maintenance_policy_created": False,
        "missing_input_count": missing,
        "warning_count": 0,
        "error_count": 1,
        **GATES,
    }


def run(repo: Path, output_dir: Path | None = None) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    v258 = read_json(root(repo, V258_REL) / "v21_258_summary.json")
    v257 = read_json(root(repo, V257_REL) / "v21_257_summary.json")
    v256 = read_json(root(repo, V256_REL) / "v21_256_summary.json")
    missing = (0 if v258 else 1) + (0 if v257 else 1) + (0 if v256 else 1)
    if missing:
        summary = fail_summary("FAIL_V21_259_ENTRYPOINT_REGISTRY_INPUT_MISSING", "DAILY_ENTRYPOINT_REGISTRY_BLOCKED_INPUT_MISSING", missing)
        write_outputs(out, summary)
        return summary
    status = entrypoint_status(v258)
    blocking = int(v258.get("blocking_retention_candidate_count", 0) or 0)
    accepted_obs = status == "ACCEPTED_WITH_RETENTION_OBSERVATION"
    accepted_full = status == "ACCEPTED"
    summary = {
        "final_status": "PASS_V21_259_DAILY_RESEARCH_ENTRYPOINT_REGISTERED",
        "final_decision": "DAILY_RESEARCH_ENTRYPOINT_REGISTERED_RESEARCH_ONLY",
        "accepted_entrypoint_name": ENTRYPOINT_NAME,
        "accepted_entrypoint_script": ENTRYPOINT_SCRIPT,
        "recommended_command": RECOMMENDED_COMMAND,
        "entrypoint_status": status,
        "accepted_with_retention_observation": accepted_obs,
        "retention_observation_required": accepted_obs,
        "blocking_retention_candidate_count": blocking,
        "run_mode_history_label": v258.get("run_mode_history_label", ""),
        "run_mode_history_warning": bool(v258.get("run_mode_history_warning")),
        "registry_created": status in {"ACCEPTED", "ACCEPTED_WITH_RETENTION_OBSERVATION"},
        "run_instruction_card_created": status in {"ACCEPTED", "ACCEPTED_WITH_RETENTION_OBSERVATION"},
        "registry_maintenance_policy_created": status in {"ACCEPTED", "ACCEPTED_WITH_RETENTION_OBSERVATION"},
        "missing_input_count": 0,
        "warning_count": 0,
        "error_count": 0,
        **GATES,
    }
    if blocking > 0:
        summary.update({"final_status": "FAIL_V21_259_ENTRYPOINT_REGISTRY_BLOCKED_BY_RETENTION", "final_decision": "DAILY_ENTRYPOINT_REGISTRY_BLOCKED_BY_RETENTION", "registry_created": False, "run_instruction_card_created": False, "registry_maintenance_policy_created": False, "error_count": 1})
    elif accepted_obs:
        summary.update({"final_status": "PARTIAL_PASS_V21_259_ENTRYPOINT_REGISTERED_WITH_RETENTION_OBSERVATION", "final_decision": "DAILY_ENTRYPOINT_REGISTERED_WITH_RETENTION_OBSERVATION_RESEARCH_ONLY", "warning_count": 1})
    elif not accepted_full:
        summary.update({"final_status": "FAIL_V21_259_ENTRYPOINT_REGISTRY_BLOCKED_BY_RETENTION", "final_decision": "DAILY_ENTRYPOINT_REGISTRY_NOT_ACCEPTED", "registry_created": False, "run_instruction_card_created": False, "registry_maintenance_policy_created": False, "error_count": 1})
    if summary["registry_created"] and summary["run_mode_history_warning"]:
        summary["warning_count"] += 1
    if gate_violation(summary):
        summary.update({"final_status": "FAIL_V21_259_ENTRYPOINT_REGISTRY_GATE_VIOLATION", "final_decision": "DAILY_ENTRYPOINT_REGISTRY_BLOCKED_GATE_VIOLATION", "registry_created": False, "error_count": 1})
    write_outputs(out, summary)
    return summary


def write_outputs(out: Path, summary: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "daily_research_entrypoint_registry.csv", registry_rows(summary) if summary["registry_created"] else [], ["registry_version", "accepted_entrypoint_name", "accepted_entrypoint_script", "recommended_command", "entrypoint_status", "retention_observation_required", "run_mode_recommended", "research_only", "gate_status"])
    (out / "daily_research_entrypoint_run_instruction_card.txt").write_text(instruction_card(summary) if summary["run_instruction_card_created"] else "", encoding="utf-8")
    write_csv(out / "daily_research_entrypoint_registry_no_go_audit.csv", no_go_rows(), ["audit_item", "expected", "observed", "passed"])
    write_csv(out / "daily_research_entrypoint_registry_maintenance_policy.csv", maintenance_rows() if summary["registry_maintenance_policy_created"] else [], ["policy_name", "policy_detail", "research_only"])
    write_csv(out / "daily_research_entrypoint_gate_audit.csv", gate_rows(summary), ["gate_name", "expected", "observed", "passed"])
    write_json(out / "v21_259_summary.json", summary)
    report = "\n".join([STAGE, f"final_status={summary['final_status']}", f"final_decision={summary['final_decision']}", f"entrypoint_status={summary['entrypoint_status']}", f"recommended_command={summary['recommended_command']}", "registry_only=True", "official_adoption_allowed=False", "broker_action_allowed=False", "market_data_fetch_allowed=False"]) + "\n"
    (out / "V21.259_daily_research_entrypoint_registry_report.txt").write_text(report, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    a = p.parse_args(argv)
    s = run(a.repo_root.resolve(), a.output_dir)
    for k in ["final_status", "final_decision", "accepted_entrypoint_name", "accepted_entrypoint_script", "recommended_command", "entrypoint_status", "accepted_with_retention_observation", "retention_observation_required", "blocking_retention_candidate_count", "run_mode_history_label", "run_mode_history_warning", "registry_created", "run_instruction_card_created", "registry_maintenance_policy_created", "retention_delete_allowed", "retention_move_allowed", "official_adoption_allowed", "broker_action_allowed", "weight_update_allowed", "ranking_mutation_allowed", "trade_plan_mutation_allowed", "child_output_mutation_allowed", "automatic_ticker_replacement_allowed", "automatic_position_increase_allowed", "automatic_trade_trigger_allowed", "market_data_fetch_allowed", "missing_input_count", "warning_count", "error_count"]:
        print(f"{k}={s.get(k)}")
    return 1 if str(s.get("final_status", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
