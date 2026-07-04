#!/usr/bin/env python
"""V20.16-R3 guarded current-lineage downstream refresh commit.

Commits only through an explicitly safe rerun callback/path after the certified
V20.7X input matches current V20.7V. Never substitutes dry-run rows for factor
outputs and never bypasses V20.7W/V20.7X certification.
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
STAGE = "V20.16-R3_CURRENT_LINEAGE_DOWNSTREAM_REFRESH_COMMIT"
PASS_STATUS = "PASS_V20_16_R3_CURRENT_LINEAGE_DOWNSTREAM_REFRESH_COMMITTED"
PARTIAL_STATUS = "PARTIAL_PASS_V20_16_R3_COMMIT_READY_BUT_REQUIRES_OPERATOR_REVIEW"
BLOCKED_INPUT = "BLOCKED_V20_16_R3_R1_OR_R2_INPUT_MISSING_OR_INVALID"
BLOCKED_PRECHECK = "BLOCKED_V20_16_R3_RECONCILIATION_PRECHECK_FAILED"
BLOCKED_PATH = "BLOCKED_V20_16_R3_SAFE_RERUN_PATH_UNAVAILABLE"
BLOCKED_COUNT = "BLOCKED_V20_16_R3_COMMITTED_COUNT_MISMATCH"
BLOCKED_PROTECTED = "BLOCKED_V20_16_R3_PROTECTED_OUTPUT_MUTATION_DETECTED"
BLOCKED_PERMISSION = "BLOCKED_V20_16_R3_OFFICIAL_PERMISSION_VIOLATION"

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "source_v20_16_r1_status",
    "source_v20_16_r2_status", "source_v20_16_r2_reconciliation_pass",
    "current_v20_7v_as_of_date", "stale_downstream_as_of_date_before_commit",
    "downstream_as_of_date_after_commit", "expected_eligible_row_count",
    "stale_actual_eligible_row_count_before_commit", "committed_eligible_row_count",
    "expected_vs_committed_delta", "commit_pass",
    "production_v20_8_to_v20_16_outputs_mutated", "production_mutation_scope",
    "protected_outputs_mutated", "protected_output_mutation_count",
    "official_activation_allowed", "official_recommendation_allowed",
    "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
    "broker_execution_allowed", "trade_action_allowed", "research_only",
    "created_at_utc",
]

COMPARISON_FIELDS = [
    "stage_name", "source_path", "as_of_date_before", "as_of_date_after",
    "row_count_before", "row_count_after", "eligible_row_count_before",
    "eligible_row_count_after", "hash_changed", "validation_status", "notes",
]

PROTECTED_RE = re.compile(
    r"(authoritative.*official.*rank|official.*weight|official.*recommend|"
    r"broker|trade[_ .-]*action|real[_ .-]*book)", re.IGNORECASE
)
PRODUCTION_RE = re.compile(r"^V20_(?:8|9|10|11|12|13|14|15|16)(?:_|\\.)", re.IGNORECASE)

WRAPPERS = [
    "run_v20_8_normalized_research_dataset_construction.ps1",
    "run_v20_9_factor_research_dataset_preparation.ps1",
    "run_v20_10_factor_source_attachment_or_availability_audit.ps1",
    "run_v20_11_factor_source_attachment_plan_or_first_attachable_factor_layer.ps1",
    "run_v20_12_factor_input_layer_review_or_factor_evidence_gate.ps1",
    "run_v20_13_first_limited_factor_evidence_layer.ps1",
    "run_v20_14_factor_evidence_review_or_factor_score_gate.ps1",
    "run_v20_15_first_limited_factor_score_layer.ps1",
    "run_v20_16_factor_score_review_or_backtest_readiness_gate.ps1",
]


def clean(value: object) -> str:
    return str(value or "").strip()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists() or path.stat().st_size == 0:
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def read_first(path: Path) -> dict[str, str]:
    rows, _ = read_csv(path)
    return rows[0] if rows else {}


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def integer(value: object) -> int | None:
    try:
        return int(clean(value))
    except ValueError:
        return None


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def snapshot(root: Path, matcher: Callable[[Path], bool]) -> dict[str, str]:
    base = root / "outputs/v20"
    if not base.exists():
        return {}
    return {
        path.resolve().relative_to(root.resolve()).as_posix(): file_hash(path)
        for path in base.rglob("*") if path.is_file() and matcher(path)
    }


def production_snapshot(root: Path) -> dict[str, str]:
    return snapshot(root, lambda path: bool(PRODUCTION_RE.match(path.name)))


def protected_snapshot(root: Path) -> dict[str, str]:
    return snapshot(
        root,
        lambda path: "V20_16_R3_CURRENT_LINEAGE" not in path.name and bool(PROTECTED_RE.search(path.name)),
    )


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def unique_date(rows: list[dict[str, str]], fields: tuple[str, ...]) -> str:
    dates = sorted({
        clean(row.get(field))[:10] for row in rows for field in fields
        if clean(row.get(field))
    })
    return dates[-1] if dates else ""


def safe_rerun_available(root: Path, current_date: str, expected: int) -> tuple[bool, str]:
    consolidation = root / "outputs/v20/consolidation"
    binding_rows, _ = read_csv(consolidation / "V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv")
    gate = read_first(consolidation / "V20_7X_GATE_DECISION.csv")
    binding_date = unique_date(binding_rows, ("effective_observation_date", "effective_price_date"))
    accepted = [row for row in binding_rows if clean(row.get("allowed_for_v20_8_input")).upper() == "TRUE"]
    wrappers_exist = all((root / "scripts/v20" / name).exists() for name in WRAPPERS)
    safe = (
        wrappers_exist
        and clean(gate.get("status")) == "PASS_V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING_READY"
        and binding_date == current_date
        and len(accepted) == expected
    )
    reason = (
        "SAFE_CERTIFIED_WRAPPER_CHAIN_AVAILABLE"
        if safe else
        f"V20_7X_NOT_ALIGNED_WITH_CURRENT_V20_7V binding_date={binding_date} "
        f"binding_rows={len(accepted)} expected={expected} wrappers_exist={wrappers_exist}"
    )
    return safe, reason


def validate_committed(root: Path, expected_date: str, expected_count: int) -> tuple[bool, str, int, str]:
    c = root / "outputs/v20/consolidation"
    v8_rows, v8_fields = read_csv(c / "V20_8_NORMALIZED_RESEARCH_DATASET.csv")
    gate = read_first(c / "V20_16_GATE_DECISION.csv")
    after_date = unique_date(v8_rows, ("effective_observation_date", "effective_price_date"))
    committed = integer(gate.get("eligible_row_count"))
    ids = [clean(row.get("normalized_row_id")) for row in v8_rows]
    required_gate = {
        "eligible_row_count", "consumed_v20_7v_status",
        "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION",
        "OFFICIAL_RECOMMENDATION_ROWS_CREATED",
    }
    permission_safe = (
        clean(gate.get("READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION")).upper() == "FALSE"
        and clean(gate.get("OFFICIAL_RECOMMENDATION_ROWS_CREATED")) in {"", "0"}
    )
    valid = (
        after_date == expected_date
        and committed == expected_count
        and len(v8_rows) == expected_count
        and len(ids) == len(set(ids))
        and all(ids)
        and required_gate.issubset(gate)
        and permission_safe
    )
    return valid, after_date, committed if committed is not None else 0, "TRUE" if permission_safe else "FALSE"


def stage_state(root: Path, name: str, path: Path) -> dict[str, object]:
    rows, _ = read_csv(path)
    date_value = unique_date(rows, (
        "effective_observation_date", "observation_date", "as_of_date",
        "effective_price_date",
    ))
    eligible = len(rows)
    if name == "V20.16":
        gate = rows[0] if rows else {}
        eligible = integer(gate.get("eligible_row_count")) or 0
    return {
        "stage_name": name,
        "source_path": path.resolve().relative_to(root.resolve()).as_posix(),
        "as_of_date": date_value,
        "row_count": len(rows),
        "eligible_row_count": eligible,
        "hash": file_hash(path) if path.exists() else "",
    }


def run_commit(
    root: Path,
    safe_runner: Callable[[Path], None] | None = None,
    mutation_hook: Callable[[], None] | None = None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    d = root / "outputs/v20/diagnostics"
    c = root / "outputs/v20/consolidation"
    r1 = read_first(d / "V20_16_R1_ELIGIBLE_ROW_COUNT_MISMATCH_FORENSIC_SUMMARY.csv")
    r2 = read_first(d / "V20_16_R2_CURRENT_LINEAGE_DOWNSTREAM_REFRESH_DRY_RUN_SUMMARY.csv")
    expected = integer(r2.get("expected_eligible_row_count"))
    dry_count = integer(r2.get("dry_run_reconciled_eligible_row_count"))
    stale_count = integer(r2.get("stale_actual_eligible_row_count"))
    current_date = clean(r2.get("current_v20_7v_as_of_date"))
    stale_date = clean(r2.get("stale_downstream_as_of_date"))

    inputs_valid = (
        clean(r1.get("final_status")) == "PASS_V20_16_R1_MISMATCH_ROOT_CAUSE_IDENTIFIED_REPAIR_PLAN_READY"
        and clean(r1.get("suspected_root_cause")) == "DATE_OR_AS_OF_MISMATCH"
        and clean(r2.get("final_status")) == "PASS_V20_16_R2_CURRENT_LINEAGE_DRY_RUN_RECONCILED"
    )
    precheck = (
        inputs_valid
        and clean(r2.get("reconciliation_pass")).upper() == "TRUE"
        and expected is not None and dry_count == expected
        and clean(r2.get("decision")) == "RECOMMEND_V20_16_R3_CURRENT_LINEAGE_DOWNSTREAM_REFRESH_COMMIT"
        and bool(current_date and stale_date and current_date > stale_date)
    )

    production_paths = [
        c / "V20_8_NORMALIZED_RESEARCH_DATASET.csv",
        c / "V20_9_FACTOR_RESEARCH_BASE_DATASET.csv",
        c / "V20_11_FIRST_ATTACHABLE_FACTOR_INPUT_LAYER.csv",
        c / "V20_13_LIMITED_FACTOR_EVIDENCE_LAYER.csv",
        c / "V20_15_LIMITED_FACTOR_SCORE_LAYER.csv",
        c / "V20_16_GATE_DECISION.csv",
    ]
    names = ["V20.8", "V20.9", "V20.11", "V20.13", "V20.15", "V20.16"]
    before_states = {name: stage_state(root, name, path) for name, path in zip(names, production_paths)}
    before_production = production_snapshot(root)
    before_protected = protected_snapshot(root)
    safe_path, safe_reason = safe_rerun_available(root, current_date, expected or 0)
    executed = False
    runner_error = ""

    if precheck and (safe_path or safe_runner is not None):
        try:
            if safe_runner is not None:
                safe_runner(root)
            else:
                # Deliberately unavailable to the Python stage without an injected
                # transaction-capable operator. The wrapper chain is not run ad hoc.
                raise RuntimeError("transaction-capable wrapper orchestration is not configured")
            executed = True
        except Exception as exc:  # preserve diagnostic status, never conceal partial failure
            runner_error = str(exc)

    if mutation_hook:
        mutation_hook()

    after_production = production_snapshot(root)
    after_protected = protected_snapshot(root)
    production_changes = changed(before_production, after_production)
    protected_changes = changed(before_protected, after_protected)
    comparison = []
    after_states = {name: stage_state(root, name, path) for name, path in zip(names, production_paths)}
    for name in names:
        before = before_states[name]
        after = after_states[name]
        comparison.append({
            "stage_name": name,
            "source_path": before["source_path"],
            "as_of_date_before": before["as_of_date"],
            "as_of_date_after": after["as_of_date"],
            "row_count_before": before["row_count"],
            "row_count_after": after["row_count"],
            "eligible_row_count_before": before["eligible_row_count"],
            "eligible_row_count_after": after["eligible_row_count"],
            "hash_changed": "TRUE" if before["hash"] != after["hash"] else "FALSE",
            "validation_status": "MUTATED" if before["hash"] != after["hash"] else "UNCHANGED",
            "notes": safe_reason,
        })

    committed_valid, after_date, committed_count, permission_safe = validate_committed(
        root, current_date, expected or 0
    ) if executed else (False, stale_date, stale_count or 0, "TRUE")

    if protected_changes:
        final_status = BLOCKED_PROTECTED
        decision = "BLOCK_COMMIT_PROTECTED_OUTPUT_MUTATION_DETECTED"
    elif permission_safe != "TRUE":
        final_status = BLOCKED_PERMISSION
        decision = "BLOCK_COMMIT_OFFICIAL_PERMISSION_VIOLATION"
    elif not inputs_valid:
        final_status = BLOCKED_INPUT
        decision = "BLOCK_COMMIT_R1_OR_R2_INPUT_MISSING_OR_INVALID"
    elif not precheck:
        final_status = BLOCKED_PRECHECK
        decision = "BLOCK_COMMIT_RECONCILIATION_PRECHECK_FAILED"
    elif not safe_path and safe_runner is None:
        final_status = BLOCKED_PATH
        decision = "BLOCK_COMMIT_SAFE_CERTIFIED_RERUN_PATH_UNAVAILABLE"
    elif runner_error:
        final_status = BLOCKED_PATH
        decision = "BLOCK_COMMIT_SAFE_RERUN_EXECUTION_FAILED"
    elif not committed_valid:
        final_status = BLOCKED_COUNT
        decision = "BLOCK_COMMIT_POST_COMMIT_COUNT_OR_LINEAGE_VALIDATION_FAILED"
    else:
        final_status = PASS_STATUS
        decision = "CURRENT_LINEAGE_DOWNSTREAM_RESEARCH_ONLY_REFRESH_COMMITTED"

    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "source_v20_16_r1_status": clean(r1.get("final_status")) or "NOT_AVAILABLE",
        "source_v20_16_r2_status": clean(r2.get("final_status")) or "NOT_AVAILABLE",
        "source_v20_16_r2_reconciliation_pass": clean(r2.get("reconciliation_pass")) or "FALSE",
        "current_v20_7v_as_of_date": current_date,
        "stale_downstream_as_of_date_before_commit": stale_date,
        "downstream_as_of_date_after_commit": after_date,
        "expected_eligible_row_count": "" if expected is None else expected,
        "stale_actual_eligible_row_count_before_commit": "" if stale_count is None else stale_count,
        "committed_eligible_row_count": committed_count,
        "expected_vs_committed_delta": "" if expected is None else expected - committed_count,
        "commit_pass": "TRUE" if final_status == PASS_STATUS else "FALSE",
        "production_v20_8_to_v20_16_outputs_mutated": "TRUE" if production_changes else "FALSE",
        "production_mutation_scope": "|".join(production_changes) if production_changes else "NONE",
        "protected_outputs_mutated": "TRUE" if protected_changes else "FALSE",
        "protected_output_mutation_count": len(protected_changes),
        "official_activation_allowed": "FALSE",
        "official_recommendation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "research_only": "TRUE",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    return summary, comparison


def render_report(summary: dict[str, object], comparison: list[dict[str, object]]) -> str:
    rows = "\n".join(
        f"| {row['stage_name']} | {row['as_of_date_before']} | {row['as_of_date_after']} | "
        f"{row['row_count_before']} | {row['row_count_after']} | {row['hash_changed']} |"
        for row in comparison
    )
    return f"""# V20.16-R3 Current Lineage Downstream Refresh Commit

## Result

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- commit_pass: {summary['commit_pass']}
- current_v20_7v_as_of_date: {summary['current_v20_7v_as_of_date']}
- downstream_as_of_date_after_commit: {summary['downstream_as_of_date_after_commit']}
- committed_eligible_row_count: {summary['committed_eligible_row_count']}

## Mutation Audit

| Stage | Date Before | Date After | Rows Before | Rows After | Hash Changed |
|---|---|---|---:|---:|---|
{rows}

- production_mutation_scope: {summary['production_mutation_scope']}
- protected_outputs_mutated: {summary['protected_outputs_mutated']}
- protected_output_mutation_count: {summary['protected_output_mutation_count']}

The commit is blocked unless the certified V20.7X input matches current V20.7V.
No dry-run rows are used as factor outputs. Official activation,
recommendations, ranking/weight mutation, broker execution, and trade actions
remain prohibited.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    summary, comparison = run_commit(root)
    diagnostics = root / "outputs/v20/diagnostics"
    write_csv(diagnostics / "V20_16_R3_CURRENT_LINEAGE_DOWNSTREAM_REFRESH_COMMIT_SUMMARY.csv", [summary], SUMMARY_FIELDS)
    write_csv(diagnostics / "V20_16_R3_CURRENT_LINEAGE_COMMIT_COMPARISON_BY_STAGE.csv", comparison, COMPARISON_FIELDS)
    report_path = root / "outputs/v20/read_center/V20_16_R3_CURRENT_LINEAGE_DOWNSTREAM_REFRESH_COMMIT_REPORT.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(summary, comparison), encoding="utf-8")
    for field in (
        "final_status", "decision", "current_v20_7v_as_of_date",
        "stale_downstream_as_of_date_before_commit",
        "downstream_as_of_date_after_commit", "expected_eligible_row_count",
        "stale_actual_eligible_row_count_before_commit", "committed_eligible_row_count",
        "expected_vs_committed_delta", "commit_pass",
        "production_v20_8_to_v20_16_outputs_mutated",
        "protected_outputs_mutated", "protected_output_mutation_count",
    ):
        print(f"{field.upper()}={summary[field]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
