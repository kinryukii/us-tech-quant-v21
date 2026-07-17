#!/usr/bin/env python
"""V22.001 canonical V21 daily entrypoint freeze.

This module records the accepted V21 daily research chain entrypoint for V22
consolidation research. It does not execute the daily chain, fetch data,
connect to broker APIs, or mutate existing V21 outputs.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any


MODULE_ID = "V22.001"
MODULE_NAME = "V21_CANONICAL_DAILY_ENTRYPOINT_FREEZE"
STAGE = "V22.001_V21_CANONICAL_DAILY_ENTRYPOINT_FREEZE"
OUT_REL = Path("outputs") / "v22" / STAGE
FREEZE_DATE = date(2026, 7, 5).isoformat()

PASS_STATUS = "PASS_V22_001_V21_CANONICAL_DAILY_ENTRYPOINT_FROZEN"
WARN_STATUS = "WARN_V22_001_ENTRYPOINT_FREEZE_DONE_WITH_MISSING_REFERENCES"
FINAL_DECISION = "V21_CANONICAL_DAILY_ENTRYPOINT_FROZEN_FOR_V22_CONSOLIDATION_RESEARCH_ONLY"

ACCEPTED_ENTRYPOINT_NAME = "V21.256_DAILY_CHAIN_MASTER_WRAPPER_WITH_CONTEXT_R1"
ACCEPTED_ENTRYPOINT_SCRIPT = "scripts/v21/run_v21_256_daily_chain_master_wrapper_with_context_r1.ps1"
RECOMMENDED_COMMAND = r".\scripts\v21\run_v21_256_daily_chain_master_wrapper_with_context_r1.ps1 -Execute"
V22_000_SCOPE_FILE = "outputs/v22/V22.000_V22_CHARTER_SCOPE_AND_RISK_POLICY_FREEZE/v22_charter_scope_freeze.json"

NEXT_RECOMMENDED_MODULES = [
    "V22.002_V21_ACTIVE_DEPRECATED_OUTPUT_MANIFEST",
    "V22.010_FACTOR_EVIDENCE_LEVEL_REGISTRY",
    "V22.020_DRAM_DAILY_DECISION_PANEL_R2",
    "V22.030_ETF_OPTION_UNIVERSE_REGISTRY",
]

NO_ACTION_GATES = {
    "research_only": True,
    "broker_action_allowed": False,
    "official_adoption_allowed": False,
    "trade_allowed": False,
    "market_data_fetch_allowed": False,
    "moomoo_connection_allowed": False,
    "option_chain_fetch_allowed": False,
    "daily_chain_execution_allowed_in_v22_001": False,
    "historical_outputs_mutation_allowed": False,
    "cache_mutation_allowed": False,
}

OPTIONAL_REFERENCES = [
    (
        "V21.234_MINIMAL_MOOMOO_ONLY_DAILY_RESEARCH_CHAIN",
        "scripts/v21/run_v21_234_minimal_moomoo_only_daily_research_chain.ps1",
        "script",
    ),
    (
        "V21.241_DAILY_CHAIN_WITH_RETENTION_GUARD",
        "scripts/v21/run_v21_241_daily_chain_with_retention_guard.ps1",
        "script",
    ),
    (
        "V21.259_DAILY_RESEARCH_ENTRYPOINT_REGISTRY_R1",
        "outputs/v21/V21.259_DAILY_RESEARCH_ENTRYPOINT_REGISTRY_R1",
        "output_directory",
    ),
    (
        "V21.264_KNOWN_FAILURE_GROUPS_REPAIRED",
        "outputs/v21/V21.264_KNOWN_FAILURE_GROUPS_REPAIRED",
        "output_directory",
    ),
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


def validate_output_dir(repo_root: Path, output_dir: Path) -> None:
    expected = (repo_root / OUT_REL).resolve()
    observed = output_dir.resolve()
    if observed != expected:
        raise ValueError(f"V22.001 output directory must be {expected}, got {observed}")


def dependency_status(required: bool, exists: bool) -> str:
    if exists:
        return "PRESENT"
    if required:
        return "MISSING_REQUIRED_REFERENCE"
    return "MISSING_OPTIONAL_REFERENCE"


def canonical_payload(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    entrypoint_exists = (repo_root / ACCEPTED_ENTRYPOINT_SCRIPT).exists()
    v22_000_scope_file_exists = (repo_root / V22_000_SCOPE_FILE).exists()
    final_status = PASS_STATUS if entrypoint_exists and v22_000_scope_file_exists else WARN_STATUS

    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "stage": STAGE,
        "freeze_date": FREEZE_DATE,
        "final_status": final_status,
        "final_decision": FINAL_DECISION,
        "accepted_entrypoint_name": ACCEPTED_ENTRYPOINT_NAME,
        "accepted_entrypoint_script": ACCEPTED_ENTRYPOINT_SCRIPT,
        "recommended_command": RECOMMENDED_COMMAND,
        "entrypoint_exists": entrypoint_exists,
        "entrypoint_status": "ACCEPTED_IF_PRESENT",
        "v22_000_scope_file_expected": V22_000_SCOPE_FILE,
        "v22_000_scope_file_exists": v22_000_scope_file_exists,
        "protected_outputs_modified": False,
        "next_recommended_modules": NEXT_RECOMMENDED_MODULES,
        "output_dir": str(output_dir),
        **NO_ACTION_GATES,
    }


def entrypoint_manifest_rows(repo_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "entrypoint_name": ACCEPTED_ENTRYPOINT_NAME,
            "entrypoint_script": ACCEPTED_ENTRYPOINT_SCRIPT,
            "recommended_command": RECOMMENDED_COMMAND,
            "role": "CANONICAL_V21_DAILY_RESEARCH_ENTRYPOINT",
            "status": "ACCEPTED_IF_PRESENT",
            "execute_allowed_in_this_module": False,
            "research_only": True,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "trade_allowed": False,
            "reason": "Canonical V21 daily research entrypoint frozen for V22 consolidation audit only; execution is forbidden in V22.001.",
        }
    ]

    for name, rel_path, dependency_type in OPTIONAL_REFERENCES:
        if dependency_type != "script" or not (repo_root / rel_path).exists():
            continue
        rows.append(
            {
                "entrypoint_name": name,
                "entrypoint_script": rel_path,
                "recommended_command": "",
                "role": "SUPPORTING_OR_HISTORICAL",
                "status": "NOT_CANONICAL_FOR_V22",
                "execute_allowed_in_this_module": False,
                "research_only": True,
                "broker_action_allowed": False,
                "official_adoption_allowed": False,
                "trade_allowed": False,
                "reason": "Observed historical/supporting wrapper; not canonical for V22.001 and not executed.",
            }
        )
    return rows


def dependency_audit_rows(repo_root: Path) -> list[dict[str, Any]]:
    dependencies = [
        (
            ACCEPTED_ENTRYPOINT_NAME,
            ACCEPTED_ENTRYPOINT_SCRIPT,
            "script",
            True,
            "Canonical V21 wrapper expected by the V22.001 freeze.",
        ),
        (
            "V22.000_CHARTER_SCOPE_JSON",
            V22_000_SCOPE_FILE,
            "json",
            True,
            "V22 scope and risk policy freeze expected before V22.001.",
        ),
    ]
    dependencies.extend(
        (name, rel_path, dependency_type, False, "Optional historical/supporting reference audited when present.")
        for name, rel_path, dependency_type in OPTIONAL_REFERENCES
    )

    rows: list[dict[str, Any]] = []
    for name, rel_path, dependency_type, required, note in dependencies:
        exists = (repo_root / rel_path).exists()
        rows.append(
            {
                "dependency_name": name,
                "dependency_path": rel_path,
                "dependency_type": dependency_type,
                "required_for_freeze": required,
                "exists": exists,
                "status": dependency_status(required, exists),
                "note": note,
            }
        )
    return rows


def risk_gate_payload() -> dict[str, Any]:
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "allowed_side_effects": ["create_outputs_v22_001_only"],
        "forbidden_side_effects": [
            "execute_daily_chain",
            "connect_moomoo",
            "fetch_market_data",
            "fetch_option_chain",
            "mutate_v21_outputs",
            "mutate_cache",
            "create_trade_order",
            "modify_broker_state",
        ],
        **{key: value for key, value in NO_ACTION_GATES.items() if key != "research_only"},
    }


def report_text(payload: dict[str, Any]) -> str:
    lines = [
        "V22.001 V21 Canonical Daily Entrypoint Freeze",
        f"module_id={payload['module_id']}",
        f"module_name={payload['module_name']}",
        f"final_status={payload['final_status']}",
        f"final_decision={payload['final_decision']}",
        f"accepted_entrypoint_name={payload['accepted_entrypoint_name']}",
        f"accepted_entrypoint_script={payload['accepted_entrypoint_script']}",
        f"recommended_command={payload['recommended_command']}",
        f"entrypoint_exists={payload['entrypoint_exists']}",
        f"v22_000_scope_file_expected={payload['v22_000_scope_file_expected']}",
        f"v22_000_scope_file_exists={payload['v22_000_scope_file_exists']}",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
        "trade_allowed=False",
        "market_data_fetch_allowed=False",
        "moomoo_connection_allowed=False",
        "option_chain_fetch_allowed=False",
        "daily_chain_execution_allowed_in_v22_001=False",
        "historical_outputs_mutation_allowed=False",
        "cache_mutation_allowed=False",
        "protected_outputs_modified=False",
        "next_recommended_modules=" + ";".join(payload["next_recommended_modules"]),
    ]
    if not payload["entrypoint_exists"]:
        lines.append("warning=canonical entrypoint missing; freeze recorded without execution or recovery.")
    if not payload["v22_000_scope_file_exists"]:
        lines.append("warning=V22.000 scope JSON missing; freeze recorded without execution or recovery.")
    return "\n".join(lines) + "\n"


def run(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = repo_root / OUT_REL
    validate_output_dir(repo_root, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = canonical_payload(repo_root, output_dir)
    write_json(output_dir / "v21_canonical_daily_entrypoint.json", payload)
    write_csv(
        output_dir / "v21_daily_chain_entrypoint_manifest.csv",
        [
            "entrypoint_name",
            "entrypoint_script",
            "recommended_command",
            "role",
            "status",
            "execute_allowed_in_this_module",
            "research_only",
            "broker_action_allowed",
            "official_adoption_allowed",
            "trade_allowed",
            "reason",
        ],
        entrypoint_manifest_rows(repo_root),
    )
    write_csv(
        output_dir / "v21_entrypoint_dependency_presence_audit.csv",
        [
            "dependency_name",
            "dependency_path",
            "dependency_type",
            "required_for_freeze",
            "exists",
            "status",
            "note",
        ],
        dependency_audit_rows(repo_root),
    )
    write_json(output_dir / "v21_entrypoint_freeze_risk_gate.json", risk_gate_payload())
    (output_dir / "V22.001_v21_canonical_daily_entrypoint_freeze_report.txt").write_text(report_text(payload), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    args = parser.parse_args(argv)
    payload = run(args.repo_root)
    print(f"final_status={payload['final_status']}")
    print(f"final_decision={payload['final_decision']}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v21_canonical_daily_entrypoint.json'}")
    print("daily_chain_execution_allowed_in_v22_001=False")
    print("broker_action_allowed=False")
    print("official_adoption_allowed=False")
    print("trade_allowed=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
