#!/usr/bin/env python
"""V20.16-R4 legacy downstream stale-lineage closeout.

Documentation/status-only stage. It records that V20.8-V20.16 production
downstream remains stale, V20.8/V20.9 staging contracts are repaired, and the
legacy replay is intentionally closed out for now.
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
STAGE = "V20.16-R4_LEGACY_DOWNSTREAM_STALE_LINEAGE_CLOSEOUT"
EXPECTED_STATUS = "PARTIAL_PASS_V20_16_R4_LEGACY_DOWNSTREAM_STALE_LINEAGE_DOCUMENTED_NO_LONGER_BLOCKING_DAILY_RESEARCH"
PASS_NO_STALE = "PASS_V20_16_R4_NO_STALE_LINEAGE_FOUND"
BLOCKED_INPUT = "BLOCKED_V20_16_R4_REQUIRED_INPUT_MISSING_OR_INVALID"
BLOCKED_PRODUCTION = "BLOCKED_V20_16_R4_PRODUCTION_OUTPUT_MUTATION_DETECTED"
BLOCKED_PROTECTED = "BLOCKED_V20_16_R4_PROTECTED_OUTPUT_MUTATION_DETECTED"
BLOCKED_PERMISSION = "BLOCKED_V20_16_R4_OFFICIAL_PERMISSION_VIOLATION"

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "current_v20_7v_as_of_date",
    "current_v20_7v_eligible_row_count", "certified_v20_7x_as_of_date",
    "certified_v20_7x_eligible_row_count",
    "production_downstream_v20_8_to_v20_16_as_of_date",
    "production_downstream_v20_8_to_v20_16_eligible_row_count",
    "lineage_mismatch_confirmed", "mismatch_root_cause",
    "v20_8_staging_contract_repaired", "v20_9_staging_contract_repaired",
    "next_unrepaired_legacy_stage", "next_unrepaired_legacy_stage_reason",
    "full_legacy_replay_available", "full_legacy_replay_recommended_now",
    "daily_research_bootstrap_blocked_by_this_issue",
    "v20_7v_r1_research_only_bootstrap_allowed", "v20_7v_r2_fast_smoke_pass",
    "v20_current_research_use_allowed", "v20_8_to_v20_16_current_use_allowed",
    "v20_8_to_v20_16_current_use_restriction", "recommended_next_focus",
    "production_v20_8_to_v20_16_outputs_mutated",
    "certified_v20_7x_outputs_mutated", "protected_outputs_mutated",
    "protected_output_mutation_count", "official_activation_allowed",
    "official_recommendation_allowed", "official_ranking_mutation_allowed",
    "official_weight_mutation_allowed", "broker_execution_allowed",
    "trade_action_allowed", "research_only", "created_at_utc",
]

STATUS_FIELDS = [
    "stage_name", "as_of_date", "eligible_row_count", "production_status",
    "staging_contract_status", "current_use_allowed", "restriction", "notes",
]

PROTECTED_RE = re.compile(
    r"(authoritative.*official.*rank|official.*weight|official.*recommend|"
    r"broker|trade[_ .-]*action|real[_ .-]*book)", re.IGNORECASE
)
PRODUCTION_RE = re.compile(r"^V20_(?:8|9|10|11|12|13|14|15|16)(?:_|\\.)", re.IGNORECASE)
V7X_RE = re.compile(r"^V20_7X_", re.IGNORECASE)


def clean(value: object) -> str:
    return str(value or "").strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists() or path.stat().st_size == 0:
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


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
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_r4_artifact(path: Path) -> bool:
    return path.name.startswith("V20_16_R4_") or "V20.16-R4" in path.name


def non_staging(path: Path) -> bool:
    return "staging" not in {part.lower() for part in path.parts}


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


def production_matcher(path: Path) -> bool:
    return non_staging(path) and not is_r4_artifact(path) and bool(PRODUCTION_RE.match(path.name))


def v7x_matcher(path: Path) -> bool:
    return non_staging(path) and bool(V7X_RE.match(path.name))


def protected_matcher(path: Path) -> bool:
    return non_staging(path) and not is_r4_artifact(path) and bool(PROTECTED_RE.search(path.name))


def unique_date(rows: list[dict[str, str]]) -> str:
    fields = ("effective_observation_date", "latest_price_date", "expected_market_date", "as_of_date", "effective_price_date")
    dates = sorted({clean(row.get(field))[:10] for row in rows for field in fields if clean(row.get(field))})
    return dates[-1] if dates else ""


def current_v20_7v(root: Path, v7x_r2: dict[str, str]) -> tuple[str, str]:
    date = clean(v7x_r2.get("current_v20_7v_as_of_date"))
    count = clean(v7x_r2.get("current_v20_7v_eligible_row_count"))
    if date and count:
        return date, count
    v7v = read_first(root / "outputs/v20/consolidation/V20_7V_VALIDATION_SUMMARY.csv")
    return clean(v7v.get("expected_market_date") or v7v.get("as_of_date")), clean(v7v.get("eligible_row_count"))


def validate_inputs(rows: dict[str, dict[str, str]]) -> bool:
    r3b = rows["r3b"]
    return (
        bool(rows["r1"]) and bool(rows["r2"]) and bool(rows["v7x_r2"])
        and bool(rows["v8_r1"]) and bool(rows["v9_r1"]) and bool(r3b)
        and clean(r3b.get("final_status")) == "BLOCKED_V20_16_R3B_ABSOLUTE_PRODUCTION_PATH_BINDING"
        and clean(r3b.get("earliest_failed_stage")) == "V20.10"
    )


def build_stage_rows(summary: dict[str, object]) -> list[dict[str, object]]:
    stale_date = clean(summary["production_downstream_v20_8_to_v20_16_as_of_date"])
    stale_count = clean(summary["production_downstream_v20_8_to_v20_16_eligible_row_count"])
    rows: list[dict[str, object]] = [
        {
            "stage_name": "V20.7V",
            "as_of_date": summary["current_v20_7v_as_of_date"],
            "eligible_row_count": summary["current_v20_7v_eligible_row_count"],
            "production_status": "CURRENT",
            "staging_contract_status": "NOT_APPLICABLE",
            "current_use_allowed": "TRUE",
            "restriction": "RESEARCH_ONLY_CURRENT_LINEAGE",
            "notes": "Current active market lineage source.",
        },
        {
            "stage_name": "V20.7X",
            "as_of_date": summary["certified_v20_7x_as_of_date"],
            "eligible_row_count": summary["certified_v20_7x_eligible_row_count"],
            "production_status": "CERTIFIED_CURRENT",
            "staging_contract_status": "CERTIFIED_INPUT",
            "current_use_allowed": "TRUE",
            "restriction": "RESEARCH_ONLY_CERTIFIED_INPUT",
            "notes": "Certified V20.7X matches current V20.7V.",
        },
    ]
    for stage in ("V20.8", "V20.9", "V20.10", "V20.11", "V20.12", "V20.13", "V20.14", "V20.15", "V20.16"):
        repaired = stage == "V20.8" and summary["v20_8_staging_contract_repaired"] == "TRUE" or stage == "V20.9" and summary["v20_9_staging_contract_repaired"] == "TRUE"
        next_legacy = stage == summary["next_unrepaired_legacy_stage"]
        rows.append({
            "stage_name": stage,
            "as_of_date": stale_date,
            "eligible_row_count": stale_count,
            "production_status": "STALE_LEGACY_LINEAGE",
            "staging_contract_status": "REPAIRED" if repaired else "NEXT_UNREPAIRED_LEGACY_BINDING" if next_legacy else "UNREPAIRED_LEGACY_OR_NOT_REPLAYED",
            "current_use_allowed": "FALSE",
            "restriction": "LEGACY_STALE_LINEAGE_DO_NOT_USE_AS_CURRENT",
            "notes": "Production downstream remains 2026-06-15 / 314 and is not current-lineage output.",
        })
    return rows


def render_report(summary: dict[str, object], stage_rows: list[dict[str, object]]) -> str:
    table = "\n".join(
        f"| {row['stage_name']} | {row['as_of_date']} | {row['eligible_row_count']} | {row['production_status']} | {row['staging_contract_status']} | {row['current_use_allowed']} | {row['restriction']} |"
        for row in stage_rows
    )
    return f"""# V20.16-R4 Legacy Downstream Stale Lineage Closeout

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- lineage_mismatch_confirmed: {summary['lineage_mismatch_confirmed']}
- mismatch_root_cause: {summary['mismatch_root_cause']}
- next_unrepaired_legacy_stage: {summary['next_unrepaired_legacy_stage']}
- full_legacy_replay_available: {summary['full_legacy_replay_available']}
- full_legacy_replay_recommended_now: {summary['full_legacy_replay_recommended_now']}
- daily_research_bootstrap_blocked_by_this_issue: {summary['daily_research_bootstrap_blocked_by_this_issue']}
- recommended_next_focus: {summary['recommended_next_focus']}

## Stage Status

| stage | as_of_date | rows | production_status | staging_contract_status | current_use_allowed | restriction |
| --- | --- | --- | --- | --- | --- | --- |
{table}

V20.8-V20.16 production outputs are retained as legacy stale-lineage artifacts
and must not be interpreted as the current/latest chain. Full legacy replay is
not available and is not recommended now. V20.7V research-only bootstrap remains
allowed, with official/trading permissions held FALSE.
"""


def run_closeout(
    root: Path,
    production_mutation_hook: Callable[[], None] | None = None,
    protected_mutation_hook: Callable[[], None] | None = None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    root = root.resolve()
    diagnostics = root / "outputs/v20/diagnostics"
    consolidation = root / "outputs/v20/consolidation"
    rows = {
        "v7v_r1": read_first(consolidation / "V20_7V_R1_RESEARCH_ONLY_BOOTSTRAP_PRECHECK_REPAIR_SUMMARY.csv"),
        "v7v_r2": read_first(consolidation / "V20_7V_R2_DAILY_BOOTSTRAP_FAST_SMOKE_VALIDATOR_SUMMARY.csv"),
        "r1": read_first(diagnostics / "V20_16_R1_ELIGIBLE_ROW_COUNT_MISMATCH_FORENSIC_SUMMARY.csv"),
        "r2": read_first(diagnostics / "V20_16_R2_CURRENT_LINEAGE_DOWNSTREAM_REFRESH_DRY_RUN_SUMMARY.csv"),
        "v7x_r2": read_first(diagnostics / "V20_7X_R2_CURRENT_LINEAGE_CERTIFICATION_REFRESH_COMMIT_SUMMARY.csv"),
        "v8_r1": read_first(diagnostics / "V20_8_R1_RELATIVE_PATH_AND_STAGING_CONTRACT_REPAIR_SUMMARY.csv"),
        "v9_r1": read_first(diagnostics / "V20_9_R1_RELATIVE_PATH_AND_STAGING_CONTRACT_REPAIR_SUMMARY.csv"),
        "r3b": read_first(diagnostics / "V20_16_R3B_SAFE_STAGED_RERUN_WRAPPER_SUMMARY.csv"),
    }

    before_production = snapshot(root, production_matcher)
    before_v7x = snapshot(root, v7x_matcher)
    before_protected = snapshot(root, protected_matcher)

    current_date, current_count = current_v20_7v(root, rows["v7x_r2"])
    certified_date = clean(rows["v7x_r2"].get("certified_v20_7x_as_of_date_after") or rows["r3b"].get("certified_v20_7x_as_of_date"))
    certified_count = clean(rows["v7x_r2"].get("certified_v20_7x_eligible_row_count_after") or rows["r3b"].get("certified_v20_7x_eligible_row_count"))
    downstream_date = clean(rows["r3b"].get("production_downstream_as_of_date_before") or rows["r2"].get("stale_downstream_as_of_date"))
    downstream_count = clean(rows["r3b"].get("production_downstream_eligible_row_count_before") or rows["r2"].get("stale_actual_eligible_row_count"))
    mismatch = bool(current_date and downstream_date and (current_date != downstream_date or current_count != downstream_count))
    v8_repaired = clean(rows["v8_r1"].get("final_status")) == "PASS_V20_8_R1_RELATIVE_PATH_AND_STAGING_CONTRACT_REPAIRED"
    v9_repaired = clean(rows["v9_r1"].get("final_status")) == "PASS_V20_9_R1_RELATIVE_PATH_AND_STAGING_CONTRACT_REPAIRED"
    r1_allowed = clean(rows["v7v_r1"].get("research_only_bootstrap_allowed")).upper() == "TRUE"
    r2_pass = clean(rows["v7v_r2"].get("final_status")).startswith("PASS_V20_7V_R2") and clean(rows["v7v_r2"].get("fallback_contract_pass")).upper() == "TRUE"

    inputs_valid = validate_inputs(rows)
    final_status = EXPECTED_STATUS if mismatch and inputs_valid else PASS_NO_STALE if not mismatch and inputs_valid else BLOCKED_INPUT
    decision = "DOCUMENT_LEGACY_STALE_LINEAGE_CLOSEOUT_NO_LONGER_BLOCKS_DAILY_RESEARCH" if final_status == EXPECTED_STATUS else "BLOCK_CLOSEOUT_REQUIRED_INPUT_MISSING_OR_INVALID" if final_status == BLOCKED_INPUT else "NO_STALE_LINEAGE_FOUND"
    summary: dict[str, object] = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "current_v20_7v_as_of_date": current_date,
        "current_v20_7v_eligible_row_count": current_count,
        "certified_v20_7x_as_of_date": certified_date,
        "certified_v20_7x_eligible_row_count": certified_count,
        "production_downstream_v20_8_to_v20_16_as_of_date": downstream_date,
        "production_downstream_v20_8_to_v20_16_eligible_row_count": downstream_count,
        "lineage_mismatch_confirmed": tf(mismatch),
        "mismatch_root_cause": clean(rows["r1"].get("suspected_root_cause")) or "DATE_OR_AS_OF_MISMATCH",
        "v20_8_staging_contract_repaired": tf(v8_repaired),
        "v20_9_staging_contract_repaired": tf(v9_repaired),
        "next_unrepaired_legacy_stage": clean(rows["r3b"].get("earliest_failed_stage")),
        "next_unrepaired_legacy_stage_reason": clean(rows["r3b"].get("earliest_failure_reason")),
        "full_legacy_replay_available": "FALSE",
        "full_legacy_replay_recommended_now": "FALSE",
        "daily_research_bootstrap_blocked_by_this_issue": "FALSE",
        "v20_7v_r1_research_only_bootstrap_allowed": tf(r1_allowed),
        "v20_7v_r2_fast_smoke_pass": tf(r2_pass),
        "v20_current_research_use_allowed": "TRUE",
        "v20_8_to_v20_16_current_use_allowed": "FALSE",
        "v20_8_to_v20_16_current_use_restriction": "LEGACY_STALE_LINEAGE_DO_NOT_USE_AS_CURRENT",
        "recommended_next_focus": "V21_FORWARD_RETURN_MATURITY_CHECK_2026_06_24",
        "production_v20_8_to_v20_16_outputs_mutated": "FALSE",
        "certified_v20_7x_outputs_mutated": "FALSE",
        "protected_outputs_mutated": "FALSE",
        "protected_output_mutation_count": "0",
        "official_activation_allowed": "FALSE",
        "official_recommendation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "research_only": "TRUE",
        "created_at_utc": utc_now(),
    }
    stage_rows = build_stage_rows(summary)

    if production_mutation_hook:
        production_mutation_hook()
    if protected_mutation_hook:
        protected_mutation_hook()

    write_csv(diagnostics / "V20_16_R4_LEGACY_DOWNSTREAM_STALE_LINEAGE_CLOSEOUT_SUMMARY.csv", [summary], SUMMARY_FIELDS)
    write_csv(diagnostics / "V20_16_R4_LEGACY_DOWNSTREAM_STATUS_BY_STAGE.csv", stage_rows, STATUS_FIELDS)
    report_path = root / "outputs/v20/read_center/V20_16_R4_LEGACY_DOWNSTREAM_STALE_LINEAGE_CLOSEOUT_REPORT.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(summary, stage_rows), encoding="utf-8")

    production_changes = changed(before_production, snapshot(root, production_matcher))
    v7x_changes = changed(before_v7x, snapshot(root, v7x_matcher))
    protected_changes = changed(before_protected, snapshot(root, protected_matcher))
    summary["production_v20_8_to_v20_16_outputs_mutated"] = tf(bool(production_changes))
    summary["certified_v20_7x_outputs_mutated"] = tf(bool(v7x_changes))
    summary["protected_outputs_mutated"] = tf(bool(protected_changes))
    summary["protected_output_mutation_count"] = str(len(protected_changes))
    if protected_changes:
        summary["final_status"] = BLOCKED_PROTECTED
        summary["decision"] = "BLOCK_PROTECTED_OUTPUT_MUTATION_DETECTED"
    elif production_changes or v7x_changes:
        summary["final_status"] = BLOCKED_PRODUCTION
        summary["decision"] = "BLOCK_PRODUCTION_OUTPUT_MUTATION_DETECTED"
    if any(summary[field] != "FALSE" for field in ("official_activation_allowed", "official_recommendation_allowed", "official_ranking_mutation_allowed", "official_weight_mutation_allowed", "broker_execution_allowed", "trade_action_allowed")):
        summary["final_status"] = BLOCKED_PERMISSION
        summary["decision"] = "BLOCK_OFFICIAL_PERMISSION_VIOLATION"

    write_csv(diagnostics / "V20_16_R4_LEGACY_DOWNSTREAM_STALE_LINEAGE_CLOSEOUT_SUMMARY.csv", [summary], SUMMARY_FIELDS)
    report_path.write_text(render_report(summary, stage_rows), encoding="utf-8")
    return summary, stage_rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    summary, _ = run_closeout(args.root)
    for field in SUMMARY_FIELDS:
        print(f"{field.upper()}={summary.get(field, '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
