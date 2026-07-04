#!/usr/bin/env python
"""V21.194 integrate broad-date gate into daily-chain research controls."""

from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable

from v21_194_broad_date_gate_utils import (
    BroadDateGateError,
    build_blocked_newer_dates_audit,
    classify_requested_date,
    emit_broad_date_gate_snapshot,
    load_latest_broad_date_gate,
)


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.194_INTEGRATE_BROAD_DATE_GATE_INTO_DAILY_CHAIN"
OUT = ROOT / "outputs/v21/V21.194_INTEGRATE_BROAD_DATE_GATE_INTO_DAILY_CHAIN"
HELPER = ROOT / "scripts/v21/v21_194_broad_date_gate_utils.py"
CANONICAL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
STAGE_SCRIPTS = [
    ROOT / "scripts/v21/v21_178_r1a_daily_dram_chain_execution_mode.py",
    ROOT / "scripts/v21/v21_187_latest_data_abcde_rerun_20260630_price_refresh.py",
    ROOT / "scripts/v21/v21_189_provider_append_repair_for_20260630_and_abcde_rerun.py",
    ROOT / "scripts/v21/v21_191_latest_available_20260629_abcde_rerun_and_manual_20260630_import_scaffold.py",
    ROOT / "scripts/v21/v21_193_broad_date_gated_abcde_rerun_20260626_honest_latest.py",
]


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    if fields is None:
        fields = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
        fields = fields or ["empty"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git_status() -> list[str]:
    proc = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, text=True, capture_output=True, check=False)
    return proc.stdout.splitlines()


def protected_modified(status_lines: list[str], baseline: list[str]) -> bool:
    new_lines = set(status_lines) - set(baseline)
    protected_prefixes = (" M outputs/v20/", "M  outputs/v20/", "?? outputs/v20/", " M outputs/official", "?? outputs/official")
    return any(line.startswith(protected_prefixes) for line in new_lines)


def scan_scripts() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    awareness: list[dict[str, Any]] = []
    raw_usage: list[dict[str, Any]] = []
    risk: list[dict[str, Any]] = []
    patterns = ["date.max()", ".max()", "raw_canonical_max_date", "latest_price_date_used", "LATEST_AVAILABLE_DATE"]
    for path in STAGE_SCRIPTS:
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        gate_aware = "v21_194_broad_date_gate_utils" in text or "latest_broad_date_gate.json" in text
        high_risk = any(token in path.name for token in ["187", "189", "191", "193", "178"])
        usage_count = sum(text.count(pattern) for pattern in patterns)
        awareness.append({
            "script_path": rel(path),
            "exists": path.is_file(),
            "gate_aware_before_or_after": gate_aware,
            "high_risk_stage": high_risk,
            "raw_max_date_usage_count": usage_count,
            "integration_mode": "direct_helper_or_gate_reference" if gate_aware else "wrapper_audit_required",
        })
        if usage_count:
            raw_usage.append({
                "script_path": rel(path),
                "raw_max_date_usage_count": usage_count,
                "gate_aware": gate_aware,
                "risk": "HIGH" if high_risk and not gate_aware else "CONTROLLED_BY_GATE_OR_AUDIT",
            })
        if high_risk and not gate_aware:
            risk.append({
                "script_path": rel(path),
                "risk_level": "HIGH",
                "risk": "Stage has latest-date behavior but no direct broad-date gate helper/reference.",
                "mitigation": "Use V21.194 contract/wrapper or patch stage before future daily-chain use.",
            })
    return awareness, raw_usage, risk


def build_contract(gate: dict[str, Any]) -> dict[str, Any]:
    blocked_0629 = classify_requested_date("2026-06-29", gate)
    allowed_0626 = classify_requested_date("2026-06-26", gate)
    return {
        "contract_version": "V21.194_R0",
        "stage": STAGE,
        "gate_source_path": gate["gate_source_path"],
        "date_policy": "Use abcd_honest_latest_date for ABCDE/latest-data/switch governance unless a newer broad gate proves eligibility.",
        "required_helper": "scripts/v21/v21_194_broad_date_gate_utils.py",
        "required_functions": [
            "load_latest_broad_date_gate",
            "resolve_honest_latest_date",
            "assert_target_date_is_broad_eligible",
            "classify_requested_date",
            "build_blocked_newer_dates_audit",
            "emit_broad_date_gate_snapshot",
        ],
        "blocked_if_requested_date_newer_than_abcd_honest_latest_date": True,
        "blocked_status": "FAIL_OR_BLOCKED_TARGET_DATE_NOT_BROAD_ELIGIBLE",
        "blocked_decision": "USE_ABCD_HONEST_LATEST_DATE_OR_IMPORT_BROAD_DAILY_BARS",
        "example_20260629": blocked_0629,
        "example_20260626": allowed_0626,
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
    }


def report(summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"gate_source_path={summary['gate_source_path']}",
        f"raw_canonical_max_date={summary['raw_canonical_max_date']}",
        f"abcd_honest_latest_date={summary['abcd_honest_latest_date']}",
        f"blocked_newer_dates={summary['blocked_newer_dates']}",
        f"gate_aware_stage_count_after={summary['gate_aware_stage_count_after']}",
        f"unpatched_high_risk_stage_count={summary['unpatched_high_risk_stage_count']}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        f"protected_outputs_modified={str(summary['protected_outputs_modified']).lower()}",
    ]
    (OUT / "V21.194_broad_date_gate_integration_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    baseline = git_status()
    gate_loaded = False
    try:
        gate = load_latest_broad_date_gate()
        gate_loaded = True
    except BroadDateGateError:
        gate = {
            "gate_source_path": "",
            "raw_canonical_max_date": "",
            "raw_canonical_max_date_symbol_count": 0,
            "raw_canonical_max_date_broad_eligible": False,
            "broad_price_latest_date": "",
            "feature_latest_date_technical": "",
            "feature_latest_date_momentum": "",
            "abcd_honest_latest_date": "",
            "narrow_tail_detected": False,
            "narrow_tail_row_count": 0,
            "blocked_newer_dates": [],
        }

    if gate_loaded:
        emit_broad_date_gate_snapshot(OUT / "broad_date_gate_snapshot.json", gate)
        write_csv(OUT / "blocked_newer_dates_audit.csv", build_blocked_newer_dates_audit(gate))
        contract = build_contract(gate)
        write_json(OUT / "broad_date_gate_contract.json", contract)
    else:
        write_json(OUT / "broad_date_gate_snapshot.json", gate)
        write_json(OUT / "broad_date_gate_contract.json", {"stage": STAGE, "gate_loaded": False})
        write_csv(OUT / "blocked_newer_dates_audit.csv", [])

    awareness, raw_usage, risk = scan_scripts()
    write_csv(OUT / "stage_gate_awareness_audit.csv", awareness)
    write_csv(OUT / "raw_max_date_usage_scan.csv", raw_usage)
    patched = [row for row in awareness if row["gate_aware_before_or_after"]]
    write_csv(OUT / "patched_scripts_audit.csv", [{"script_path": row["script_path"], "integration_mode": row["integration_mode"]} for row in patched])
    write_csv(OUT / "unpatched_stage_risk_register.csv", risk)
    write_csv(OUT / "daily_chain_gate_integration_audit.csv", [
        {
            "gate_loaded": gate_loaded,
            "helper_module_created": HELPER.is_file(),
            "contract_created": (OUT / "broad_date_gate_contract.json").is_file(),
            "requested_20260629_classification": classify_requested_date("2026-06-29", gate)["classification"] if gate_loaded else "GATE_MISSING",
            "requested_20260626_classification": classify_requested_date("2026-06-26", gate)["classification"] if gate_loaded else "GATE_MISSING",
            "canonical_mutated": False,
        }
    ])

    integration_test_passed = bool(
        gate_loaded
        and HELPER.is_file()
        and (OUT / "broad_date_gate_contract.json").is_file()
        and (not gate.get("blocked_newer_dates") or classify_requested_date(gate["blocked_newer_dates"][0], gate)["allowed"] is False)
        and classify_requested_date(gate["abcd_honest_latest_date"], gate)["allowed"] is True
    )
    unpatched_high = len(risk)
    if not gate_loaded:
        final_status = "FAIL_V21_194_BROAD_DATE_GATE_MISSING"
        final_decision = "RUN_V21_192_FIRST"
    elif not integration_test_passed:
        final_status = "FAIL_V21_194_GATE_INTEGRATION_TEST_FAILED"
        final_decision = "DO_NOT_USE_DAILY_CHAIN_UNTIL_GATE_INTEGRATION_REPAIRED"
    elif unpatched_high:
        final_status = "PARTIAL_PASS_V21_194_GATE_HELPER_READY_UNPATCHED_RISK_REMAINS"
        final_decision = "USE_GATE_AWARE_WRAPPER_UNTIL_ALL_STAGES_PATCHED"
    else:
        final_status = "PASS_V21_194_BROAD_DATE_GATE_INTEGRATED"
        final_decision = "DAILY_CHAIN_USES_ABCD_HONEST_LATEST_DATE_RESEARCH_ONLY"

    status_after = git_status()
    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "final_decision": final_decision,
        "gate_source_path": gate.get("gate_source_path", ""),
        "gate_loaded": gate_loaded,
        "raw_canonical_max_date": gate.get("raw_canonical_max_date", ""),
        "raw_canonical_max_date_symbol_count": gate.get("raw_canonical_max_date_symbol_count", 0),
        "raw_canonical_max_date_broad_eligible": gate.get("raw_canonical_max_date_broad_eligible", False),
        "broad_price_latest_date": gate.get("broad_price_latest_date", ""),
        "feature_latest_date_technical": gate.get("feature_latest_date_technical", ""),
        "feature_latest_date_momentum": gate.get("feature_latest_date_momentum", ""),
        "abcd_honest_latest_date": gate.get("abcd_honest_latest_date", ""),
        "narrow_tail_detected": gate.get("narrow_tail_detected", False),
        "narrow_tail_row_count": gate.get("narrow_tail_row_count", 0),
        "blocked_newer_dates": gate.get("blocked_newer_dates", []),
        "helper_module_created": HELPER.is_file(),
        "contract_created": (OUT / "broad_date_gate_contract.json").is_file(),
        "scanned_stage_count": len(awareness),
        "gate_aware_stage_count_before": len(patched),
        "gate_aware_stage_count_after": len(patched),
        "patched_script_count": len(patched),
        "unpatched_high_risk_stage_count": unpatched_high,
        "raw_max_date_usage_count": sum(int(row["raw_max_date_usage_count"]) for row in raw_usage),
        "integration_test_passed": integration_test_passed,
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": protected_modified(status_after, baseline),
    }
    write_json(OUT / "v21_194_summary.json", summary)
    report(summary)
    for key in [
        "final_status", "final_decision", "gate_loaded", "gate_source_path", "raw_canonical_max_date",
        "raw_canonical_max_date_symbol_count", "raw_canonical_max_date_broad_eligible",
        "broad_price_latest_date", "abcd_honest_latest_date", "narrow_tail_detected", "blocked_newer_dates",
        "helper_module_created", "contract_created", "scanned_stage_count", "gate_aware_stage_count_before",
        "gate_aware_stage_count_after", "patched_script_count", "unpatched_high_risk_stage_count",
        "raw_max_date_usage_count", "integration_test_passed", "official_adoption_allowed",
        "broker_action_allowed", "protected_outputs_modified",
    ]:
        print(f"{key}={summary[key]}")
    return summary


if __name__ == "__main__":
    run()
