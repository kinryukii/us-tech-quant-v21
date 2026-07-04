#!/usr/bin/env python
"""V20.7V-R2 daily bootstrap fast smoke validator.

Validation-only. This stage does not invoke the daily operator or any bootstrap
runner. It validates the V20.7V -> V20.7V-R1 fallback contract and confirms
protected official outputs are unchanged during validation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V20.7V-R2_DAILY_BOOTSTRAP_FAST_SMOKE_VALIDATOR"
PASS_STATUS = "PASS_V20_7V_R2_DAILY_BOOTSTRAP_FAST_SMOKE_VALIDATED"
PARTIAL_STATUS = "PARTIAL_PASS_V20_7V_R2_FAST_SMOKE_VALIDATED_FULL_OPERATOR_NOT_RUN"
CONTRACT_BLOCKED = "BLOCKED_V20_7V_R2_FALLBACK_CONTRACT_FAILED"
INPUT_BLOCKED = "BLOCKED_V20_7V_R2_INPUT_MISSING_OR_INVALID"
MUTATION_BLOCKED = "BLOCKED_V20_7V_R2_PROTECTED_OUTPUT_MUTATION_DETECTED"

V7V_PASS = "PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY"
V7V_REVIEW_BLOCK = "BLOCKED_V20_7V_PRECHECK_REVIEW_NEEDED"
R1_PASS = "PASS_V20_7V_R1_RESEARCH_ONLY_BOOTSTRAP_ALLOWED_OFFICIAL_GUARDRAILS_PRESERVED"
R1_PARTIAL = "PARTIAL_PASS_V20_7V_R1_RESEARCH_ONLY_BOOTSTRAP_ALLOWED_WITH_DOWNSTREAM_PENDING"

PERMISSIONS = [
    "official_activation_allowed",
    "official_recommendation_allowed",
    "official_ranking_mutation_allowed",
    "official_weight_mutation_allowed",
    "broker_execution_allowed",
    "trade_action_allowed",
]

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "source_v20_7v_status",
    "source_v20_7v_r1_status", "source_v20_7v_r1_decision",
    "research_only_bootstrap_allowed", "fallback_contract_pass",
    "daily_operator_full_run_attempted", "full_operator_required_for_this_stage",
    *PERMISSIONS, "protected_output_hash_check_status",
    "mutated_protected_output_count", "unrelated_known_regression",
    "created_at_utc",
]

PROTECTED_PATTERN = re.compile(
    r"(authoritative.*official.*rank|official.*weight|official.*recommend|"
    r"broker|trade[_ .-]*action|real[_ .-]*book)",
    re.IGNORECASE,
)


def clean(value: object) -> str:
    return str(value or "").strip()


def is_true(value: object) -> bool:
    return clean(value).upper() == "TRUE"


def read_first(path: Path) -> dict[str, str]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.DictReader(handle), {})


def write_csv(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in SUMMARY_FIELDS})


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def protected_files(root: Path) -> list[Path]:
    outputs = root / "outputs/v20"
    if not outputs.exists():
        return []
    return sorted(
        path for path in outputs.rglob("*")
        if path.is_file()
        and "V20_7V_R2_DAILY_BOOTSTRAP_FAST_SMOKE_VALIDATOR" not in path.name
        and PROTECTED_PATTERN.search(path.name)
    )


def hash_snapshot(root: Path) -> dict[str, str]:
    return {
        path.resolve().relative_to(root.resolve()).as_posix(): file_hash(path)
        for path in protected_files(root)
    }


def changed_hashes(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(
        path for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    )


def detect_v20_16_regression(root: Path) -> str:
    staging = root / "outputs/v20/consolidation/V20_7V_ACTIVE_MARKET_SOURCE_STAGING.csv"
    gate = read_first(root / "outputs/v20/consolidation/V20_16_GATE_DECISION.csv")
    if not staging.exists() or not gate:
        return "NOT_DETECTED"
    with staging.open("r", encoding="utf-8-sig", newline="") as handle:
        staging_count = sum(1 for _ in csv.DictReader(handle))
    try:
        gate_count = int(clean(gate.get("eligible_row_count")))
    except ValueError:
        return "NOT_DETECTED"
    return "V20_16_ELIGIBLE_ROW_COUNT_MISMATCH" if gate_count != staging_count else "NOT_DETECTED"


def input_integrity_blocked(v7v: dict[str, str]) -> bool:
    status = clean(v7v.get("status"))
    if status in {V7V_PASS, V7V_REVIEW_BLOCK}:
        return False
    text = " ".join(clean(value).upper() for value in v7v.values())
    integrity_terms = (
        "CORRUPT", "MISSING_CORE", "MISSING CORE", "MISSING_PRICE",
        "MISSING PRICE", "AMBIGUOUS",
    )
    return status.startswith("BLOCKED") or any(term in text for term in integrity_terms)


def evaluate_contract(v7v: dict[str, str], r1: dict[str, str]) -> tuple[bool, bool, str]:
    status = clean(v7v.get("status"))
    permissions_safe = bool(r1) and all(not is_true(r1.get(field)) for field in PERMISSIONS)
    r1_allowed = (
        bool(r1)
        and clean(r1.get("final_status")) in {R1_PASS, R1_PARTIAL}
        and is_true(r1.get("research_only_bootstrap_allowed"))
        and permissions_safe
    )
    if status == V7V_PASS:
        return True, True, "V20_7V_PASS_DIRECT_FALLBACK_NOT_REQUIRED"
    if status == V7V_REVIEW_BLOCK:
        return r1_allowed, r1_allowed, (
            "V20_7V_REVIEW_BLOCK_REPAIRED_FOR_RESEARCH_ONLY_BOOTSTRAP"
            if r1_allowed else "V20_7V_REVIEW_BLOCK_R1_CONTRACT_NOT_SATISFIED"
        )
    if input_integrity_blocked(v7v):
        return False, False, "V20_7V_INTEGRITY_OR_AMBIGUOUS_BLOCK_NOT_BYPASSABLE"
    return False, False, "V20_7V_STATUS_INVALID_OR_UNSUPPORTED"


def run_validation(
    root: Path,
    mutation_hook: Callable[[], None] | None = None,
) -> dict[str, object]:
    v7v_path = root / "outputs/v20/consolidation/V20_7V_VALIDATION_SUMMARY.csv"
    r1_path = root / "outputs/v20/consolidation/V20_7V_R1_RESEARCH_ONLY_BOOTSTRAP_PRECHECK_REPAIR_SUMMARY.csv"
    before = hash_snapshot(root)
    v7v = read_first(v7v_path)
    r1 = read_first(r1_path)
    inputs_valid = bool(v7v and clean(v7v.get("status")))
    contract_pass, bootstrap_allowed, contract_reason = (
        evaluate_contract(v7v, r1) if inputs_valid else (False, False, "INPUT_MISSING_OR_INVALID")
    )
    if mutation_hook:
        mutation_hook()
    after = hash_snapshot(root)
    changed = changed_hashes(before, after)
    if changed:
        hash_status = "FAIL_PROTECTED_OUTPUT_HASH_CHANGED"
    elif before:
        hash_status = "PASS_PROTECTED_OUTPUT_HASHES_UNCHANGED"
    else:
        hash_status = "NO_PROTECTED_OUTPUTS_FOUND_BUT_NO_MUTATION_ATTEMPTED"

    if changed:
        final_status = MUTATION_BLOCKED
        decision = "BLOCK_FAST_SMOKE_PROTECTED_OUTPUT_MUTATION_DETECTED"
    elif not inputs_valid or (clean(v7v.get("status")) == V7V_REVIEW_BLOCK and not r1):
        final_status = INPUT_BLOCKED
        decision = "BLOCK_FAST_SMOKE_REQUIRED_INPUT_MISSING_OR_INVALID"
    elif not contract_pass:
        final_status = CONTRACT_BLOCKED
        decision = f"BLOCK_FAST_SMOKE_FALLBACK_CONTRACT_FAILED__{contract_reason}"
    else:
        final_status = PASS_STATUS
        decision = "VALIDATE_DAILY_BOOTSTRAP_FALLBACK_CONTRACT_WITHOUT_FULL_OPERATOR_RUN"

    permissions = {
        field: clean(r1.get(field)).upper() if r1 and clean(r1.get(field)) else "FALSE"
        for field in PERMISSIONS
    }
    return {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "source_v20_7v_status": clean(v7v.get("status")) or "NOT_AVAILABLE",
        "source_v20_7v_r1_status": clean(r1.get("final_status")) or "NOT_AVAILABLE",
        "source_v20_7v_r1_decision": clean(r1.get("decision")) or "NOT_AVAILABLE",
        "research_only_bootstrap_allowed": "TRUE" if bootstrap_allowed else "FALSE",
        "fallback_contract_pass": "TRUE" if contract_pass else "FALSE",
        "daily_operator_full_run_attempted": "FALSE",
        "full_operator_required_for_this_stage": "FALSE",
        **permissions,
        "protected_output_hash_check_status": hash_status,
        "mutated_protected_output_count": len(changed),
        "unrelated_known_regression": detect_v20_16_regression(root),
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "_protected_file_count": len(before),
        "_changed_paths": changed,
    }


def render_report(row: dict[str, object]) -> str:
    changed = row.get("_changed_paths") or []
    changed_text = "\n".join(f"- {path}" for path in changed) or "- NONE"
    return f"""# V20.7V-R2 Daily Bootstrap Fast Smoke Validator

## Result

- final_status: {row['final_status']}
- decision: {row['decision']}
- fallback_contract_pass: {row['fallback_contract_pass']}
- research_only_bootstrap_allowed: {row['research_only_bootstrap_allowed']}
- daily_operator_full_run_attempted: FALSE
- full_operator_required_for_this_stage: FALSE

This is a fast fallback-contract smoke validation. It is not full end-to-end
daily operator completion and does not invoke the long bootstrap sequence.

## Source Contract

- source_v20_7v_status: {row['source_v20_7v_status']}
- source_v20_7v_r1_status: {row['source_v20_7v_r1_status']}
- source_v20_7v_r1_decision: {row['source_v20_7v_r1_decision']}
- unrelated_known_regression: {row['unrelated_known_regression']}

## Guardrails

- official_activation_allowed: {row['official_activation_allowed']}
- official_recommendation_allowed: {row['official_recommendation_allowed']}
- official_ranking_mutation_allowed: {row['official_ranking_mutation_allowed']}
- official_weight_mutation_allowed: {row['official_weight_mutation_allowed']}
- broker_execution_allowed: {row['broker_execution_allowed']}
- trade_action_allowed: {row['trade_action_allowed']}

## Protected Output Hash Audit

- protected_output_hash_check_status: {row['protected_output_hash_check_status']}
- protected_file_count: {row['_protected_file_count']}
- mutated_protected_output_count: {row['mutated_protected_output_count']}

Changed protected paths:
{changed_text}
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    summary_path = root / "outputs/v20/consolidation/V20_7V_R2_DAILY_BOOTSTRAP_FAST_SMOKE_VALIDATOR_SUMMARY.csv"
    report_path = root / "outputs/v20/read_center/V20_7V_R2_DAILY_BOOTSTRAP_FAST_SMOKE_VALIDATOR_REPORT.md"
    row = run_validation(root)
    write_csv(summary_path, row)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(row), encoding="utf-8")
    for field in (
        "final_status", "decision", "fallback_contract_pass",
        "research_only_bootstrap_allowed", "daily_operator_full_run_attempted",
        "protected_output_hash_check_status", "mutated_protected_output_count",
        "unrelated_known_regression",
    ):
        print(f"{field.upper()}={row[field]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
