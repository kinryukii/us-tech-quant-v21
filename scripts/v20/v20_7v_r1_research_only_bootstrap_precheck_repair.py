#!/usr/bin/env python
"""V20.7V-R1 research-only bootstrap precheck repair.

This stage never changes V20.7V, ranking, weight, recommendation, or trading
artifacts. It only records whether a separate research-only bootstrap lane is
safe to use.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V20.7V-R1_RESEARCH_ONLY_BOOTSTRAP_PRECHECK_REPAIR"
PASS_STATUS = "PASS_V20_7V_R1_RESEARCH_ONLY_BOOTSTRAP_ALLOWED_OFFICIAL_GUARDRAILS_PRESERVED"
PARTIAL_STATUS = "PARTIAL_PASS_V20_7V_R1_RESEARCH_ONLY_BOOTSTRAP_ALLOWED_WITH_DOWNSTREAM_PENDING"
BLOCKED_STATUS = "BLOCKED_V20_7V_R1_REPAIR_NOT_SAFE"
INVALID_STATUS = "BLOCKED_V20_7V_R1_INPUT_MISSING_OR_INVALID"
SOURCE_PASS = "PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY"
SOURCE_REVIEW_BLOCK = "BLOCKED_V20_7V_PRECHECK_REVIEW_NEEDED"

PERMISSION_FIELDS = (
    "official_activation_allowed",
    "official_recommendation_allowed",
    "official_ranking_mutation_allowed",
    "official_weight_mutation_allowed",
    "broker_execution_allowed",
    "trade_action_allowed",
)

SUMMARY_FIELDS = [
    "stage",
    "final_status",
    "decision",
    "source_v20_7v_status",
    "research_only_bootstrap_allowed",
    *PERMISSION_FIELDS,
    "downstream_v20_200_status_if_available",
    "blocker_classification",
    "repair_scope",
    "created_at_utc",
]


def clean(value: object) -> str:
    return str(value or "").strip()


def is_true(value: object) -> bool:
    return clean(value).upper() == "TRUE"


def read_first(path: Path) -> dict[str, str]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.DictReader(handle), {})


def write_csv(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in SUMMARY_FIELDS})


def downstream_state(root: Path) -> tuple[str, bool, bool]:
    gate = read_first(root / "outputs/v20/reports/V20_200_NEXT_STAGE_GATE.csv")
    status = clean(gate.get("final_status"))
    guard_fields = (
        "research_only",
        "official_ranking_mutated",
        "official_recommendation_created",
        "trade_action_created",
        "broker_execution_supported",
        "real_book_action_created",
    )
    guard_safe = (
        status in {"PASS_REPORT_READY", "PARTIAL_PASS_REPORT_READY_WITH_MISSING_OPTIONAL_INPUTS"}
        and clean(gate.get("research_only")).upper() == "TRUE"
        and all(clean(gate.get(field)).upper() == "FALSE" for field in guard_fields[1:])
    )
    wrappers = [
        root / f"scripts/v20/run_v20_{number}_{name}.ps1"
        for number, name in (
            ("194", "recomputable_factor_snapshot_producer_contract"),
            ("195", "daily_snapshot_accumulation_and_forward_observation_ledger"),
            ("196", "forward_observation_maturity_updater"),
            ("197", "daily_walk_forward_validation_runner"),
            ("198", "daily_walk_forward_chain_integration"),
            ("199", "daily_research_runner_walk_forward_binding"),
            ("200", "operator_daily_report_v2_with_walk_forward_and_shadow_policy_status"),
        )
    ]
    return status, guard_safe, all(path.exists() for path in wrappers)


def integrity_safe(source: dict[str, str]) -> tuple[bool, str]:
    if not source:
        return False, "INPUT_MISSING_OR_INVALID"
    required = {"status", "eligible_row_count", "missing_core_field_summary"}
    if not required.issubset(source):
        return False, "INPUT_MISSING_OR_INVALID"
    try:
        eligible = int(clean(source.get("eligible_row_count")) or "0")
        stale = int(clean(source.get("stale_ticker_count")) or "0")
        missing_price = int(clean(source.get("missing_latest_price_count")) or "0")
    except ValueError:
        return False, "INPUT_MISSING_OR_INVALID"
    missing_core = clean(source.get("missing_core_field_summary")).upper()
    if eligible <= 0:
        return False, "MISSING_CORE_DATA"
    if missing_core not in {"", "NONE"}:
        return False, "MISSING_CORE_DATA"
    if stale > 0 or missing_price > 0:
        return False, "MISSING_OR_STALE_STAGED_PRICE_DATA"
    if is_true(source.get("BROKER_API_USED")) or is_true(source.get("ORDER_EXECUTION_USED")):
        return False, "TRADING_PATH_DETECTED"
    return True, "OFFICIAL_ACTIVE_MARKET_GUARDRAIL_ONLY"


def evaluate_repair(
    source: dict[str, str],
    downstream_status: str,
    downstream_guard_safe: bool,
    downstream_runnable: bool,
    permissions: dict[str, str] | None = None,
) -> dict[str, str]:
    permission_values = {field: "FALSE" for field in PERMISSION_FIELDS}
    permission_values.update(permissions or {})
    source_status = clean(source.get("status"))
    safe, classification = integrity_safe(source)
    permissions_safe = all(not is_true(permission_values[field]) for field in PERMISSION_FIELDS)
    downstream_available = downstream_guard_safe or downstream_runnable

    allowed = False
    if source_status == SOURCE_PASS:
        allowed = safe and permissions_safe and downstream_available
    elif source_status == SOURCE_REVIEW_BLOCK:
        allowed = safe and permissions_safe and downstream_available
    elif classification != "INPUT_MISSING_OR_INVALID":
        classification = "AMBIGUOUS_OFFICIAL_USE_READINESS"

    if not source or classification == "INPUT_MISSING_OR_INVALID":
        final_status = INVALID_STATUS
        decision = "BLOCK_RESEARCH_ONLY_BOOTSTRAP_INPUT_INVALID"
    elif not allowed:
        final_status = BLOCKED_STATUS
        decision = "BLOCK_RESEARCH_ONLY_BOOTSTRAP_REPAIR_NOT_SAFE"
    elif downstream_guard_safe:
        final_status = PASS_STATUS
        decision = "ALLOW_RESEARCH_ONLY_BOOTSTRAP_OFFICIAL_GUARDRAILS_PRESERVED"
    else:
        final_status = PARTIAL_STATUS
        decision = "ALLOW_RESEARCH_ONLY_BOOTSTRAP_DOWNSTREAM_RESEARCH_STAGES_PENDING"

    return {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "source_v20_7v_status": source_status,
        "research_only_bootstrap_allowed": "TRUE" if allowed else "FALSE",
        **{field: clean(permission_values[field]).upper() for field in PERMISSION_FIELDS},
        "downstream_v20_200_status_if_available": downstream_status or "NOT_AVAILABLE",
        "blocker_classification": classification,
        "repair_scope": "RESEARCH_ONLY_BOOTSTRAP_PRECHECK_ONLY_NO_SOURCE_OR_OFFICIAL_ARTIFACT_MUTATION",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def render_report(row: dict[str, str]) -> str:
    return f"""# V20.7V-R1 Research-Only Bootstrap Precheck Repair

## Decision

- final_status: {row['final_status']}
- decision: {row['decision']}
- source_v20_7v_status: {row['source_v20_7v_status']}
- blocker_classification: {row['blocker_classification']}
- research_only_bootstrap_allowed: {row['research_only_bootstrap_allowed']}
- downstream_v20_200_status_if_available: {row['downstream_v20_200_status_if_available']}

## Guardrails

- official_activation_allowed: {row['official_activation_allowed']}
- official_recommendation_allowed: {row['official_recommendation_allowed']}
- official_ranking_mutation_allowed: {row['official_ranking_mutation_allowed']}
- official_weight_mutation_allowed: {row['official_weight_mutation_allowed']}
- broker_execution_allowed: {row['broker_execution_allowed']}
- trade_action_allowed: {row['trade_action_allowed']}

This repair is an audit-only research-lane decision. It does not modify the
V20.7V source summary or create an official recommendation, ranking/weight
mutation, broker execution path, or real-book trade action.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    source_path = root / "outputs/v20/consolidation/V20_7V_VALIDATION_SUMMARY.csv"
    summary_path = root / "outputs/v20/consolidation/V20_7V_R1_RESEARCH_ONLY_BOOTSTRAP_PRECHECK_REPAIR_SUMMARY.csv"
    report_path = root / "outputs/v20/read_center/V20_7V_R1_RESEARCH_ONLY_BOOTSTRAP_PRECHECK_REPAIR_REPORT.md"

    source = read_first(source_path)
    downstream_status, downstream_guard_safe, downstream_runnable = downstream_state(root)
    row = evaluate_repair(source, downstream_status, downstream_guard_safe, downstream_runnable)
    write_csv(summary_path, row)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(row), encoding="utf-8")
    for key in ("final_status", "decision", "research_only_bootstrap_allowed"):
        print(f"{key.upper()}={row[key]}")
    print("OFFICIAL_ACTIVATION_ALLOWED=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
