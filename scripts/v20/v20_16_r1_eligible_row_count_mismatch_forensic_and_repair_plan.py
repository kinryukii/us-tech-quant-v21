#!/usr/bin/env python
"""V20.16-R1 eligible-row-count mismatch forensic and repair plan.

Audit-only. Produces comparison evidence and a repair plan without changing
V20.16 or any official/protected artifact.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V20.16-R1_ELIGIBLE_ROW_COUNT_MISMATCH_FORENSIC_AND_REPAIR_PLAN"
PASS_IDENTIFIED = "PASS_V20_16_R1_MISMATCH_ROOT_CAUSE_IDENTIFIED_REPAIR_PLAN_READY"
PARTIAL_PROBABLE = "PARTIAL_PASS_V20_16_R1_MISMATCH_CONFIRMED_ROOT_CAUSE_PROBABLE"
PARTIAL_MANUAL = "PARTIAL_PASS_V20_16_R1_MISMATCH_CONFIRMED_MANUAL_REVIEW_REQUIRED"
PASS_NO_MISMATCH = "PASS_V20_16_R1_NO_MISMATCH_FOUND"
BLOCKED_INPUT = "BLOCKED_V20_16_R1_INPUT_MISSING_OR_INVALID"
BLOCKED_MUTATION = "BLOCKED_V20_16_R1_PROTECTED_OUTPUT_MUTATION_DETECTED"

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "detected_regression_name",
    "expected_eligible_row_count", "actual_eligible_row_count", "row_count_delta",
    "mismatch_confirmed", "suspected_root_cause", "root_cause_confidence",
    "source_expected_path", "source_actual_path", "comparison_artifact_path",
    "safe_repair_available", "production_output_mutation_allowed",
    "official_activation_allowed", "official_recommendation_allowed",
    "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
    "broker_execution_allowed", "trade_action_allowed", "research_only",
    "created_at_utc",
]

COMPARISON_FIELDS = [
    "stage_name", "file_path", "row_count", "eligible_row_count",
    "distinct_ticker_count", "distinct_as_of_date_count", "duplicate_key_count",
    "missing_required_field_count", "price_missing_count", "notes",
]

PROTECTED_RE = re.compile(
    r"(authoritative.*official.*rank|official.*weight|official.*recommend|"
    r"broker|trade[_ .-]*action|real[_ .-]*book)", re.IGNORECASE
)


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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def protected_snapshot(root: Path) -> dict[str, str]:
    base = root / "outputs/v20"
    if not base.exists():
        return {}
    return {
        path.resolve().relative_to(root.resolve()).as_posix(): sha256(path)
        for path in base.rglob("*")
        if path.is_file()
        and "V20_16_R1_ELIGIBLE_ROW_COUNT_MISMATCH_FORENSIC" not in path.name
        and PROTECTED_RE.search(path.name)
    }


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def int_value(value: object) -> int | None:
    try:
        return int(clean(value))
    except ValueError:
        return None


def date_field(fields: list[str]) -> str:
    return next((field for field in (
        "observation_date", "effective_observation_date", "as_of_date",
        "signal_date", "price_date", "latest_price_date",
    ) if field in fields), "")


def ticker_field(fields: list[str]) -> str:
    return next((field for field in ("ticker", "symbol") if field in fields), "")


def duplicate_key_count(rows: list[dict[str, str]], fields: list[str]) -> int:
    candidates = [
        "factor_score_row_id", "factor_evidence_row_id", "normalized_row_id",
        "sample_id", "observation_id",
    ]
    key_field = next((field for field in candidates if field in fields), "")
    if key_field:
        values = [clean(row.get(key_field)) for row in rows]
        return len(values) - len(set(values))
    ticker = ticker_field(fields)
    day = date_field(fields)
    if ticker:
        values = [(clean(row.get(ticker)).upper(), clean(row.get(day))) for row in rows]
        return len(values) - len(set(values))
    return 0


def comparison_row(stage: str, root: Path, path: Path, eligible: int | None = None) -> dict[str, object]:
    rows, fields = read_csv(path)
    ticker = ticker_field(fields)
    day = date_field(fields)
    required = [field for field in (ticker, day) if field]
    missing_required = sum(
        1 for row in rows for field in required if not clean(row.get(field))
    )
    price_fields = [field for field in ("latest_close", "effective_close", "close") if field in fields]
    price_missing = sum(
        1 for row in rows if price_fields and not any(clean(row.get(field)) for field in price_fields)
    )
    run_ids = sorted({clean(row.get("run_id")) for row in rows if clean(row.get("run_id"))})
    dates = sorted({clean(row.get(day))[:10] for row in rows if day and clean(row.get(day))})
    notes = []
    if run_ids:
        notes.append("run_id=" + "|".join(run_ids[:3]))
    if dates:
        notes.append("dates=" + "|".join(dates[:5]))
    return {
        "stage_name": stage,
        "file_path": path.resolve().relative_to(root.resolve()).as_posix(),
        "row_count": len(rows),
        "eligible_row_count": "" if eligible is None else eligible,
        "distinct_ticker_count": len({clean(row.get(ticker)).upper() for row in rows}) if ticker else "",
        "distinct_as_of_date_count": len({clean(row.get(day))[:10] for row in rows}) if day else "",
        "duplicate_key_count": duplicate_key_count(rows, fields),
        "missing_required_field_count": missing_required,
        "price_missing_count": price_missing,
        "notes": ";".join(notes),
    }


def classify(
    expected: int,
    actual: int,
    comparison: list[dict[str, object]],
) -> tuple[str, str, bool]:
    if expected == actual:
        return "NO_MISMATCH", "HIGH", False
    by_stage = {str(row["stage_name"]): row for row in comparison}
    v7 = by_stage.get("V20.7V_CURRENT_STAGING", {})
    v8 = by_stage.get("V20.8_NORMALIZED_DATASET", {})
    v15 = by_stage.get("V20.15_SCORE_LAYER", {})
    v16 = by_stage.get("V20.16_GATE", {})
    v7_dates = clean(v7.get("notes"))
    v8_dates = clean(v8.get("notes"))
    downstream_consistent = (
        int(v8.get("row_count") or -1) == actual
        and int(v16.get("eligible_row_count") or -1) == actual
        and int(v15.get("row_count") or -1) > 0
        and int(v15.get("row_count") or 0) % actual == 0
    )
    if downstream_consistent and v7_dates and v8_dates and v7_dates != v8_dates:
        return "DATE_OR_AS_OF_MISMATCH", "HIGH", True
    missing = sum(int(row.get("missing_required_field_count") or 0) for row in comparison)
    price_missing = sum(int(row.get("price_missing_count") or 0) for row in comparison)
    if actual < expected and (missing or price_missing):
        return "MISSING_PRICE_OR_REQUIRED_FIELD_FILTER", "HIGH", True
    duplicates = sum(int(row.get("duplicate_key_count") or 0) for row in comparison)
    if duplicates:
        return "DUPLICATE_ROW_COLLAPSE_OR_EXPANSION", "MEDIUM", True
    if downstream_consistent:
        return "TEST_FIXTURE_OUT_OF_SYNC", "MEDIUM", True
    return "UNKNOWN_REQUIRES_MANUAL_REVIEW", "LOW", False


def run_forensic(root: Path, mutation_hook: Callable[[], None] | None = None) -> tuple[dict[str, object], list[dict[str, object]]]:
    consolidation = root / "outputs/v20/consolidation"
    expected_path = consolidation / "V20_7V_ACTIVE_MARKET_SOURCE_STAGING.csv"
    actual_path = consolidation / "V20_16_GATE_DECISION.csv"
    v8_path = consolidation / "V20_8_NORMALIZED_RESEARCH_DATASET.csv"
    v9_path = consolidation / "V20_9_FACTOR_RESEARCH_BASE_DATASET.csv"
    v15_path = consolidation / "V20_15_LIMITED_FACTOR_SCORE_LAYER.csv"
    before = protected_snapshot(root)
    expected_rows, _ = read_csv(expected_path)
    gate = read_first(actual_path)
    expected = len(expected_rows) if expected_path.exists() else None
    actual = int_value(gate.get("eligible_row_count"))
    valid = expected is not None and actual is not None and bool(gate)

    comparison = []
    if expected_path.exists():
        comparison.append(comparison_row("V20.7V_CURRENT_STAGING", root, expected_path, expected))
    if v8_path.exists():
        comparison.append(comparison_row("V20.8_NORMALIZED_DATASET", root, v8_path, len(read_csv(v8_path)[0])))
    if v9_path.exists():
        comparison.append(comparison_row("V20.9_FACTOR_RESEARCH_BASE", root, v9_path, len(read_csv(v9_path)[0])))
    if v15_path.exists():
        comparison.append(comparison_row("V20.15_SCORE_LAYER", root, v15_path, actual))
    if actual_path.exists():
        comparison.append({
            **comparison_row("V20.16_GATE", root, actual_path, actual),
            "row_count": 1,
            "notes": (
                f"consumed_v20_7v_status={clean(gate.get('consumed_v20_7v_status'))};"
                f"expected_score_rows={clean(gate.get('expected_score_rows_from_current_v20_7v_eligible_rows'))}"
            ),
        })

    if valid:
        cause, confidence, safe_repair = classify(expected, actual, comparison)
        mismatch = expected != actual
    else:
        cause, confidence, safe_repair, mismatch = "UNKNOWN_REQUIRES_MANUAL_REVIEW", "LOW", False, False

    if mutation_hook:
        mutation_hook()
    mutated = changed(before, protected_snapshot(root))
    if mutated:
        final_status = BLOCKED_MUTATION
        decision = "BLOCK_FORENSIC_STAGE_PROTECTED_OUTPUT_MUTATION_DETECTED"
    elif not valid:
        final_status = BLOCKED_INPUT
        decision = "BLOCK_FORENSIC_STAGE_REQUIRED_INPUT_MISSING_OR_INVALID"
    elif not mismatch:
        final_status = PASS_NO_MISMATCH
        decision = "NO_ELIGIBLE_ROW_COUNT_MISMATCH_CURRENTLY_PRESENT"
    elif cause in {"DATE_OR_AS_OF_MISMATCH", "MISSING_PRICE_OR_REQUIRED_FIELD_FILTER", "DUPLICATE_ROW_COLLAPSE_OR_EXPANSION"} and confidence == "HIGH":
        final_status = PASS_IDENTIFIED
        decision = "NON_MUTATING_REPAIR_PLAN_READY_RERUN_DOWNSTREAM_CHAIN_FROM_CURRENT_V20_7V"
    elif cause != "UNKNOWN_REQUIRES_MANUAL_REVIEW":
        final_status = PARTIAL_PROBABLE
        decision = "MISMATCH_CONFIRMED_ROOT_CAUSE_PROBABLE_REPAIR_REQUIRES_EXPLICIT_STAGE"
    else:
        final_status = PARTIAL_MANUAL
        decision = "MISMATCH_CONFIRMED_MANUAL_REVIEW_REQUIRED"

    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "detected_regression_name": "V20_16_ELIGIBLE_ROW_COUNT_MISMATCH",
        "expected_eligible_row_count": "" if expected is None else expected,
        "actual_eligible_row_count": "" if actual is None else actual,
        "row_count_delta": "" if not valid else actual - expected,
        "mismatch_confirmed": "TRUE" if valid and mismatch else "FALSE",
        "suspected_root_cause": cause,
        "root_cause_confidence": confidence,
        "source_expected_path": expected_path.resolve().relative_to(root.resolve()).as_posix(),
        "source_actual_path": actual_path.resolve().relative_to(root.resolve()).as_posix(),
        "comparison_artifact_path": "outputs/v20/diagnostics/V20_16_R1_ELIGIBLE_ROW_COUNT_COMPARISON_BY_STAGE.csv",
        "safe_repair_available": "TRUE" if safe_repair else "FALSE",
        "production_output_mutation_allowed": "FALSE",
        "official_activation_allowed": "FALSE",
        "official_recommendation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "research_only": "TRUE",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "_mutated_protected_count": len(mutated),
    }
    return summary, comparison


def report(summary: dict[str, object], comparison: list[dict[str, object]]) -> str:
    rows = "\n".join(
        f"| {row['stage_name']} | {row['row_count']} | {row['eligible_row_count']} | "
        f"{row['distinct_ticker_count']} | {row['distinct_as_of_date_count']} |"
        for row in comparison
    )
    scope = (
        "This mismatch affects regression confidence and the stale legacy V20.8-V20.16 chain. "
        "It does not revoke the separately validated V20.7V-R1/R2 research-only fallback."
    )
    return f"""# V20.16-R1 Eligible Row Count Mismatch Forensic and Repair Plan

## Finding

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- expected_eligible_row_count: {summary['expected_eligible_row_count']}
- actual_eligible_row_count: {summary['actual_eligible_row_count']}
- row_count_delta: {summary['row_count_delta']}
- mismatch_confirmed: {summary['mismatch_confirmed']}
- suspected_root_cause: {summary['suspected_root_cause']}
- root_cause_confidence: {summary['root_cause_confidence']}

## Comparison

| Stage | Rows | Eligible | Tickers | Dates |
|---|---:|---:|---:|---:|
{rows}

## Repair Plan

Do not edit V20.16 outputs or relax the regression assertion. In a later
explicit execution stage, rerun the V20.8 through V20.16 research chain from
the current V20.7V lineage, then verify row counts, dates, run IDs, exclusions,
and five-family score cardinality before replacing any baseline.

## Operational Scope

{scope}

All official activation, recommendation, ranking/weight mutation, broker, and
trade permissions remain FALSE. Production output mutation is not allowed.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    summary, comparison = run_forensic(root)
    diagnostics = root / "outputs/v20/diagnostics"
    write_csv(diagnostics / "V20_16_R1_ELIGIBLE_ROW_COUNT_MISMATCH_FORENSIC_SUMMARY.csv", [summary], SUMMARY_FIELDS)
    write_csv(diagnostics / "V20_16_R1_ELIGIBLE_ROW_COUNT_COMPARISON_BY_STAGE.csv", comparison, COMPARISON_FIELDS)
    report_path = root / "outputs/v20/read_center/V20_16_R1_ELIGIBLE_ROW_COUNT_MISMATCH_FORENSIC_AND_REPAIR_PLAN_REPORT.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report(summary, comparison), encoding="utf-8")
    for field in (
        "final_status", "decision", "expected_eligible_row_count",
        "actual_eligible_row_count", "row_count_delta", "mismatch_confirmed",
        "suspected_root_cause", "root_cause_confidence", "safe_repair_available",
    ):
        print(f"{field.upper()}={summary[field]}")
    print(f"PROTECTED_OUTPUT_MUTATION_COUNT={summary['_mutated_protected_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
