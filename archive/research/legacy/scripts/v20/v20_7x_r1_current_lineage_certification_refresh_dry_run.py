#!/usr/bin/env python
"""V20.7X-R1 current-lineage certification refresh dry run.

Creates a conservative lineage-binding candidate from current V20.7V without
claiming V20.7W/V20.7X certification or mutating production artifacts.
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
STAGE = "V20.7X-R1_CURRENT_LINEAGE_CERTIFICATION_REFRESH_DRY_RUN"
PASS_STATUS = "PASS_V20_7X_R1_CURRENT_LINEAGE_CERTIFICATION_DRY_RUN_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V20_7X_R1_CERTIFICATION_STALENESS_CONFIRMED_REVIEW_REQUIRED"
BLOCKED_R3 = "BLOCKED_V20_7X_R1_R3_INPUT_MISSING_OR_INVALID"
BLOCKED_V7V = "BLOCKED_V20_7X_R1_CURRENT_V20_7V_SOURCE_MISSING"
BLOCKED_V7X = "BLOCKED_V20_7X_R1_CERTIFIED_V20_7X_SOURCE_MISSING"
BLOCKED_DRY = "BLOCKED_V20_7X_R1_CERTIFICATION_DRY_RUN_FAILED"
BLOCKED_PRODUCTION = "BLOCKED_V20_7X_R1_PRODUCTION_OUTPUT_MUTATION_DETECTED"
BLOCKED_PROTECTED = "BLOCKED_V20_7X_R1_PROTECTED_OUTPUT_MUTATION_DETECTED"

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "source_v20_16_r3_status",
    "source_v20_16_r3_decision", "current_v20_7v_path",
    "current_v20_7v_as_of_date", "current_v20_7v_eligible_row_count",
    "certified_v20_7x_path", "certified_v20_7x_as_of_date_before",
    "certified_v20_7x_eligible_row_count_before", "certification_staleness_detected",
    "dry_run_certified_as_of_date", "dry_run_certified_eligible_row_count",
    "expected_current_eligible_row_count", "expected_vs_dry_run_delta",
    "certification_dry_run_pass", "certified_v20_7x_production_outputs_mutated",
    "downstream_v20_8_to_v20_16_outputs_mutated", "protected_outputs_mutated",
    "protected_output_mutation_count", "official_activation_allowed",
    "official_recommendation_allowed", "official_ranking_mutation_allowed",
    "official_weight_mutation_allowed", "broker_execution_allowed",
    "trade_action_allowed", "research_only", "created_at_utc",
]

COMPARISON_FIELDS = [
    "source_role", "source_path", "as_of_date", "row_count",
    "eligible_row_count", "distinct_ticker_count", "required_column_count",
    "missing_required_field_count", "duplicate_key_count",
    "price_missing_count", "certification_claimed", "notes",
]

DRY_FIELDS = [
    "dry_run_input_artifact_id", "dry_run_lineage_binding_id",
    "source_artifact_id", "source_system", "source_hash", "run_id",
    "sample_id", "ticker", "effective_observation_date",
    "effective_price_date", "effective_close", "active_runtime_flag",
    "historical_reference_flag", "candidate_allowed_for_v20_8_input",
    "allowed_for_official_use", "certification_claimed",
    "certification_metadata_generated", "factor_values_generated",
    "research_only", "dry_run_status",
]

V7X_REQUIRED = [
    "source_artifact_id", "source_system", "source_hash", "run_id",
    "sample_id", "ticker", "effective_observation_date",
    "effective_price_date", "effective_close", "active_runtime_flag",
    "historical_reference_flag",
]
V7V_REQUIRED = [
    "source_artifact_id", "source_system", "source_hash", "run_id",
    "sample_id", "ticker", "observation_date", "latest_price_date",
    "latest_close", "active_runtime_flag", "historical_reference_flag",
]

PROTECTED_RE = re.compile(
    r"(authoritative.*official.*rank|official.*weight|official.*recommend|"
    r"broker|trade[_ .-]*action|real[_ .-]*book)", re.IGNORECASE
)
V7X_PRODUCTION_RE = re.compile(r"^V20_7X_", re.IGNORECASE)
DOWNSTREAM_RE = re.compile(r"^V20_(?:8|9|10|11|12|13|14|15|16)(?:_|\\.)", re.IGNORECASE)


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


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def unique_date(rows: list[dict[str, str]], fields: tuple[str, ...]) -> str:
    dates = sorted({
        clean(row.get(field))[:10] for row in rows for field in fields
        if clean(row.get(field))
    })
    return dates[-1] if dates else ""


def missing_count(rows: list[dict[str, str]], required: list[str]) -> int:
    return sum(1 for row in rows for field in required if not clean(row.get(field)))


def duplicate_count(rows: list[dict[str, str]], fields: tuple[str, ...]) -> int:
    keys = [tuple(clean(row.get(field)).upper() for field in fields) for row in rows]
    return len(keys) - len(set(keys))


def short_hash(text: str, length: int = 24) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length].upper()


def project(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    output = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        ticker = clean(row.get("ticker")).upper()
        as_of = clean(row.get("observation_date") or row.get("signal_date"))[:10]
        price_date = clean(row.get("latest_price_date") or row.get("price_date"))[:10]
        close = clean(row.get("latest_close") or row.get("close"))
        required = all(clean(row.get(field)) for field in (
            "source_artifact_id", "source_system", "source_hash", "run_id", "sample_id",
        ))
        key = (ticker, as_of)
        if not (ticker and as_of and price_date and close and required) or key in seen:
            continue
        seen.add(key)
        basis = "|".join([
            ticker, as_of, price_date, clean(row.get("source_artifact_id")),
            clean(row.get("source_hash")), clean(row.get("run_id")),
            clean(row.get("sample_id")),
        ])
        output.append({
            "dry_run_input_artifact_id": "V20_7X_R1_INPUT_" + short_hash(basis + "|INPUT"),
            "dry_run_lineage_binding_id": "V20_7X_R1_BIND_" + short_hash(basis + "|BIND"),
            "source_artifact_id": clean(row.get("source_artifact_id")),
            "source_system": clean(row.get("source_system")),
            "source_hash": clean(row.get("source_hash")),
            "run_id": clean(row.get("run_id")),
            "sample_id": clean(row.get("sample_id")),
            "ticker": ticker,
            "effective_observation_date": as_of,
            "effective_price_date": price_date,
            "effective_close": close,
            "active_runtime_flag": clean(row.get("active_runtime_flag")),
            "historical_reference_flag": clean(row.get("historical_reference_flag")),
            "candidate_allowed_for_v20_8_input": "TRUE",
            "allowed_for_official_use": "FALSE",
            "certification_claimed": "FALSE",
            "certification_metadata_generated": "FALSE",
            "factor_values_generated": "FALSE",
            "research_only": "TRUE",
            "dry_run_status": "CERTIFICATION_CANDIDATE_ONLY_REQUIRES_V20_7X_R2_COMMIT",
        })
    return output


def comparison(
    role: str, root: Path, path: Path, rows: list[dict[str, str]],
    required: list[str], date_fields: tuple[str, ...], eligible_field: str = "",
) -> dict[str, object]:
    eligible = (
        sum(clean(row.get(eligible_field)).upper() == "TRUE" for row in rows)
        if eligible_field else len(rows)
    )
    price_field = "effective_close" if "effective_close" in required else "latest_close"
    return {
        "source_role": role,
        "source_path": path.resolve().relative_to(root.resolve()).as_posix(),
        "as_of_date": unique_date(rows, date_fields),
        "row_count": len(rows),
        "eligible_row_count": eligible,
        "distinct_ticker_count": len({clean(row.get("ticker")).upper() for row in rows}),
        "required_column_count": len(required),
        "missing_required_field_count": missing_count(rows, required),
        "duplicate_key_count": duplicate_count(rows, ("ticker", date_fields[0])) if rows else 0,
        "price_missing_count": sum(not clean(row.get(price_field)) for row in rows),
        "certification_claimed": "TRUE" if role == "CERTIFIED_V20_7X_BEFORE" else "FALSE",
        "notes": "read-only source comparison",
    }


def run_dry_run(
    root: Path,
    projection_hook: Callable[[list[dict[str, object]]], list[dict[str, object]]] | None = None,
    v7x_mutation_hook: Callable[[], None] | None = None,
    protected_mutation_hook: Callable[[], None] | None = None,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    d = root / "outputs/v20/diagnostics"
    c = root / "outputs/v20/consolidation"
    r3 = read_first(d / "V20_16_R3_CURRENT_LINEAGE_DOWNSTREAM_REFRESH_COMMIT_SUMMARY.csv")
    current_path = c / "V20_7V_ACTIVE_MARKET_SOURCE_STAGING.csv"
    certified_path = c / "V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv"
    current_rows, current_fields = read_csv(current_path)
    certified_rows, certified_fields = read_csv(certified_path)
    r3_valid = (
        clean(r3.get("final_status")) == "BLOCKED_V20_16_R3_SAFE_RERUN_PATH_UNAVAILABLE"
        and clean(r3.get("decision")) == "BLOCK_COMMIT_SAFE_CERTIFIED_RERUN_PATH_UNAVAILABLE"
    )
    current_valid = bool(current_rows and set(V7V_REQUIRED).issubset(current_fields))
    certified_valid = bool(certified_rows and set(V7X_REQUIRED).issubset(certified_fields))

    before_v7x = snapshot(root, lambda path: bool(V7X_PRODUCTION_RE.match(path.name)))
    before_downstream = snapshot(root, lambda path: bool(DOWNSTREAM_RE.match(path.name)))
    before_protected = snapshot(
        root,
        lambda path: "V20_7X_R1_CURRENT_LINEAGE" not in path.name and bool(PROTECTED_RE.search(path.name)),
    )

    current_date = unique_date(current_rows, ("observation_date", "signal_date", "latest_price_date"))
    certified_date = unique_date(certified_rows, ("effective_observation_date", "effective_price_date"))
    current_count = len(current_rows)
    certified_count = sum(
        clean(row.get("allowed_for_v20_8_input")).upper() == "TRUE" for row in certified_rows
    )
    stale = bool(current_date and certified_date and current_date > certified_date)
    projected = project(current_rows) if current_valid else []
    if projection_hook:
        projected = projection_hook(projected)
    dry_date = unique_date(
        [{key: str(value) for key, value in row.items()} for row in projected],
        ("effective_observation_date", "effective_price_date"),
    )
    dry_count = len(projected)
    dry_pass = bool(
        r3_valid and current_valid and certified_valid
        and dry_date == current_date and dry_count == current_count
        and len({row["dry_run_lineage_binding_id"] for row in projected}) == dry_count
        and all(row["certification_claimed"] == "FALSE" for row in projected)
    )

    comparison_rows = []
    if current_rows:
        comparison_rows.append(comparison(
            "CURRENT_V20_7V", root, current_path, current_rows, V7V_REQUIRED,
            ("observation_date", "signal_date", "latest_price_date"),
        ))
    if certified_rows:
        comparison_rows.append(comparison(
            "CERTIFIED_V20_7X_BEFORE", root, certified_path, certified_rows, V7X_REQUIRED,
            ("effective_observation_date", "effective_price_date"),
            "allowed_for_v20_8_input",
        ))
    comparison_rows.append({
        "source_role": "V20_7X_R1_DRY_RUN_CANDIDATE",
        "source_path": "outputs/v20/diagnostics/V20_7X_R1_DRY_RUN_CERTIFIED_ELIGIBLE_ROWS.csv",
        "as_of_date": dry_date,
        "row_count": dry_count,
        "eligible_row_count": dry_count,
        "distinct_ticker_count": len({str(row["ticker"]) for row in projected}),
        "required_column_count": len(V7X_REQUIRED),
        "missing_required_field_count": sum(
            1 for row in projected for field in V7X_REQUIRED if not clean(row.get(field))
        ),
        "duplicate_key_count": dry_count - len({str(row["dry_run_lineage_binding_id"]) for row in projected}),
        "price_missing_count": sum(not clean(row.get("effective_close")) for row in projected),
        "certification_claimed": "FALSE",
        "notes": "candidate only; no V20.7W/V20.7X certification metadata fabricated",
    })

    if v7x_mutation_hook:
        v7x_mutation_hook()
    if protected_mutation_hook:
        protected_mutation_hook()
    v7x_changes = changed(before_v7x, snapshot(root, lambda path: bool(V7X_PRODUCTION_RE.match(path.name))))
    downstream_changes = changed(before_downstream, snapshot(root, lambda path: bool(DOWNSTREAM_RE.match(path.name))))
    protected_changes = changed(
        before_protected,
        snapshot(
            root,
            lambda path: "V20_7X_R1_CURRENT_LINEAGE" not in path.name and bool(PROTECTED_RE.search(path.name)),
        ),
    )

    if protected_changes:
        final_status = BLOCKED_PROTECTED
        decision = "BLOCK_DRY_RUN_PROTECTED_OUTPUT_MUTATION_DETECTED"
    elif v7x_changes or downstream_changes:
        final_status = BLOCKED_PRODUCTION
        decision = "BLOCK_DRY_RUN_PRODUCTION_OUTPUT_MUTATION_DETECTED"
    elif not r3_valid:
        final_status = BLOCKED_R3
        decision = "BLOCK_DRY_RUN_V20_16_R3_INPUT_MISSING_OR_INVALID"
    elif not current_valid:
        final_status = BLOCKED_V7V
        decision = "BLOCK_DRY_RUN_CURRENT_V20_7V_SOURCE_MISSING_OR_INVALID"
    elif not certified_valid:
        final_status = BLOCKED_V7X
        decision = "BLOCK_DRY_RUN_CERTIFIED_V20_7X_SOURCE_MISSING_OR_INVALID"
    elif dry_pass and stale:
        final_status = PASS_STATUS
        decision = "RECOMMEND_V20_7X_R2_CURRENT_LINEAGE_CERTIFICATION_REFRESH_COMMIT"
    elif dry_pass:
        final_status = PARTIAL_STATUS
        decision = "CERTIFICATION_CANDIDATE_VALID_STALENESS_REVIEW_REQUIRED"
    else:
        final_status = BLOCKED_DRY
        decision = "BLOCK_V20_7X_R2_CERTIFICATION_DRY_RUN_FAILED"

    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "source_v20_16_r3_status": clean(r3.get("final_status")) or "NOT_AVAILABLE",
        "source_v20_16_r3_decision": clean(r3.get("decision")) or "NOT_AVAILABLE",
        "current_v20_7v_path": current_path.resolve().relative_to(root.resolve()).as_posix(),
        "current_v20_7v_as_of_date": current_date,
        "current_v20_7v_eligible_row_count": current_count,
        "certified_v20_7x_path": certified_path.resolve().relative_to(root.resolve()).as_posix(),
        "certified_v20_7x_as_of_date_before": certified_date,
        "certified_v20_7x_eligible_row_count_before": certified_count,
        "certification_staleness_detected": "TRUE" if stale else "FALSE",
        "dry_run_certified_as_of_date": dry_date,
        "dry_run_certified_eligible_row_count": dry_count,
        "expected_current_eligible_row_count": current_count,
        "expected_vs_dry_run_delta": current_count - dry_count,
        "certification_dry_run_pass": "TRUE" if dry_pass else "FALSE",
        "certified_v20_7x_production_outputs_mutated": "TRUE" if v7x_changes else "FALSE",
        "downstream_v20_8_to_v20_16_outputs_mutated": "TRUE" if downstream_changes else "FALSE",
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
    return summary, comparison_rows, projected


def report(summary: dict[str, object], rows: list[dict[str, object]]) -> str:
    table = "\n".join(
        f"| {row['source_role']} | {row['as_of_date']} | {row['row_count']} | "
        f"{row['eligible_row_count']} | {row['duplicate_key_count']} |"
        for row in rows
    )
    recommendation = (
        "V20.7X-R2 commit is recommended."
        if summary["certification_dry_run_pass"] == "TRUE"
        and summary["certification_staleness_detected"] == "TRUE"
        else "V20.7X-R2 commit is not recommended."
    )
    return f"""# V20.7X-R1 Current Lineage Certification Refresh Dry Run

## Result

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- current_v20_7v_as_of_date: {summary['current_v20_7v_as_of_date']}
- certified_v20_7x_as_of_date_before: {summary['certified_v20_7x_as_of_date_before']}
- dry_run_certified_as_of_date: {summary['dry_run_certified_as_of_date']}
- certification_dry_run_pass: {summary['certification_dry_run_pass']}

| Source | Date | Rows | Eligible | Duplicates |
|---|---|---:|---:|---:|
{table}

{recommendation}

The dry-run artifact is a certification candidate only. It preserves current
lineage and price fields but does not claim certification and does not
fabricate V20.7W/V20.7X metadata, factor values, or official permissions.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    summary, comparison_rows, projected = run_dry_run(root)
    diagnostics = root / "outputs/v20/diagnostics"
    write_csv(diagnostics / "V20_7X_R1_CURRENT_LINEAGE_CERTIFICATION_REFRESH_DRY_RUN_SUMMARY.csv", [summary], SUMMARY_FIELDS)
    write_csv(diagnostics / "V20_7X_R1_CERTIFICATION_INPUT_COMPARISON.csv", comparison_rows, COMPARISON_FIELDS)
    write_csv(diagnostics / "V20_7X_R1_DRY_RUN_CERTIFIED_ELIGIBLE_ROWS.csv", projected, DRY_FIELDS)
    report_path = root / "outputs/v20/read_center/V20_7X_R1_CURRENT_LINEAGE_CERTIFICATION_REFRESH_DRY_RUN_REPORT.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report(summary, comparison_rows), encoding="utf-8")
    for field in (
        "final_status", "decision", "current_v20_7v_as_of_date",
        "current_v20_7v_eligible_row_count", "certified_v20_7x_as_of_date_before",
        "certified_v20_7x_eligible_row_count_before", "certification_staleness_detected",
        "dry_run_certified_as_of_date", "dry_run_certified_eligible_row_count",
        "certification_dry_run_pass", "certified_v20_7x_production_outputs_mutated",
        "downstream_v20_8_to_v20_16_outputs_mutated", "protected_outputs_mutated",
    ):
        print(f"{field.upper()}={summary[field]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
