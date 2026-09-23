#!/usr/bin/env python
"""V20.96 multi-run observation accumulation orchestrator.

Research-only accumulation layer. It reads V20.95 blocker decomposition,
discovers daily observation run outputs, counts only valid research-only
observation runs, and reports progress toward multi-run sufficiency without
creating promotion, recommendation, weight, or trade actions.
"""

from __future__ import annotations

import csv
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "outputs" / "v20" / "evidence"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
REPAIR = ROOT / "outputs" / "v20" / "repair"

PASS_STATUS = "PASS_V20_96_MULTI_RUN_OBSERVATIONS_ACCUMULATED_RESEARCH_ONLY"
WARN_STATUS = "WARN_V20_96_INSUFFICIENT_VALID_OBSERVATION_RUNS"
BLOCKED_STATUS = "BLOCKED_V20_96_MISSING_V20_95_PREFLIGHT"

V20_95_DETAIL = EVIDENCE / "V20_CURRENT_PROMOTION_BLOCKER_DECOMPOSITION_DETAIL.csv"
V20_95_SUMMARY = EVIDENCE / "V20_CURRENT_PROMOTION_BLOCKER_DECOMPOSITION_SUMMARY.md"

DETAIL = EVIDENCE / "V20_96_MULTI_RUN_OBSERVATION_ACCUMULATION_DETAIL.csv"
SUMMARY = EVIDENCE / "V20_96_MULTI_RUN_OBSERVATION_ACCUMULATION_SUMMARY.md"
DETAIL_ALIAS = EVIDENCE / "V20_CURRENT_MULTI_RUN_OBSERVATION_ACCUMULATION_DETAIL.csv"
SUMMARY_ALIAS = EVIDENCE / "V20_CURRENT_MULTI_RUN_OBSERVATION_ACCUMULATION_SUMMARY.md"
ACCUMULATION = EVIDENCE / "V20_96_MULTI_RUN_OBSERVATION_ACCUMULATION.csv"
ACCUMULATION_ALIAS = EVIDENCE / "V20_CURRENT_MULTI_RUN_OBSERVATION_ACCUMULATION.csv"
DAILY_RESEARCH_OBSERVATION_LEDGER = EVIDENCE / "V20_DAILY_RESEARCH_OBSERVATION_LEDGER.csv"
DAILY_RESEARCH_OBSERVATION_LEDGER_ALIAS = EVIDENCE / "V20_CURRENT_DAILY_RESEARCH_OBSERVATION_LEDGER.csv"

CURRENT_DAILY_CONCLUSION = READ_CENTER / "V20_CURRENT_DAILY_CONCLUSION.md"
CURRENT_CHAIN_LANE_STATUS = REPAIR / "V20_CURRENT_CHAIN_LANE_STATUS.csv"
CURRENT_DAILY_RESEARCH_LANE_STATUS = REPAIR / "V20_CURRENT_DAILY_RESEARCH_LANE_STATUS.csv"
V20_49_PROMOTION_GATE = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

V20_55_WARN_RESEARCH_ONLY = "WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED"
DAILY_CONCLUSION_RESEARCH_ONLY = "RESEARCH_ONLY_DAILY_CONCLUSION_READY_OFFICIAL_PROMOTION_BLOCKED"

DEFAULT_REQUIRED_RUN_COUNT = 5

OBSERVATION_INPUT_CANDIDATES = [
    DAILY_RESEARCH_OBSERVATION_LEDGER,
    DAILY_RESEARCH_OBSERVATION_LEDGER_ALIAS,
    CONSOLIDATION / "V20_55_DAILY_ONE_CLICK_RUN_SUMMARY.csv",
    EVIDENCE / "V20_97_DAILY_RUNNER_OBSERVATION_BRIDGE_REPAIR_DETAIL.csv",
    EVIDENCE / "V20_CURRENT_DAILY_RUNNER_OBSERVATION_BRIDGE_REPAIR_DETAIL.csv",
    EVIDENCE / "V20_97_DAILY_RUNNER_OBSERVATION_BRIDGE.csv",
    EVIDENCE / "V20_CURRENT_DAILY_RUNNER_OBSERVATION_BRIDGE.csv",
    CONSOLIDATION / "V20_55_DAILY_ONE_CLICK_RUNNER_OUTPUT.csv",
    EVIDENCE / "V20_CURRENT_DAILY_ONE_CLICK_RUNNER_OUTPUT.csv",
    CONSOLIDATION / "V20_57_SHADOW_FEEDBACK_COMPUTATION_OUTPUT.csv",
    EVIDENCE / "V20_CURRENT_SHADOW_FEEDBACK_COMPUTATION_OUTPUT.csv",
    CONSOLIDATION / "V20_58_STABILITY_MULTI_RUN_GATE.csv",
    EVIDENCE / "V20_CURRENT_STABILITY_MULTI_RUN_GATE.csv",
    CONSOLIDATION / "V20_59_OBSERVATION_INTAKE.csv",
    EVIDENCE / "V20_CURRENT_OBSERVATION_INTAKE.csv",
    CONSOLIDATION / "V20_61_DAILY_OBSERVATION_BRIDGE.csv",
    EVIDENCE / "V20_CURRENT_DAILY_OBSERVATION_BRIDGE.csv",
    CONSOLIDATION / "V20_63_DAILY_RUNNER_HEALTH_TABLE.csv",
    EVIDENCE / "V20_CURRENT_DAILY_RUNNER_HEALTH_TABLE.csv",
    CONSOLIDATION / "V20_63_OBSERVATION_INTEGRATION_TABLE.csv",
    EVIDENCE / "V20_CURRENT_OBSERVATION_INTEGRATION_TABLE.csv",
    CONSOLIDATION / "V20_64_ROLLING_EVIDENCE_LEDGER.csv",
    EVIDENCE / "V20_CURRENT_ROLLING_EVIDENCE_LEDGER.csv",
    CONSOLIDATION / "V20_65_PROPOSAL_PROMOTION_READINESS_GATE.csv",
    EVIDENCE / "V20_CURRENT_PROPOSAL_PROMOTION_READINESS_GATE.csv",
]

ROLLING_LEDGER_CANDIDATES = [
    CONSOLIDATION / "V20_64_ROLLING_EVIDENCE_LEDGER.csv",
    EVIDENCE / "V20_CURRENT_ROLLING_EVIDENCE_LEDGER.csv",
]

DETAIL_FIELDS = [
    "record_type",
    "source_file",
    "source_status",
    "run_id",
    "run_timestamp",
    "observation_timestamp",
    "v20_55_status",
    "daily_conclusion_mode",
    "current_daily_research_lane_status",
    "forward_outcome_validation_lane_status",
    "observation_class",
    "research_observation_valid",
    "official_promotion_eligible",
    "promotion_blocker_present",
    "promotion_blocked_reason",
    "v20_27_forward_pending",
    "daily_runner_status",
    "row_status",
    "rejection_reason",
    "discovered_run_count",
    "valid_observation_run_count",
    "invalid_observation_run_count",
    "duplicate_run_count",
    "required_run_count",
    "remaining_run_count",
    "multi_run_sufficiency_met",
    "earliest_valid_observation_date",
    "latest_valid_observation_date",
    "valid_run_ids",
    "rejected_run_ids",
    "rejection_reasons",
    "rolling_ledger_source_file",
    "rolling_ledger_status",
    "rolling_ledger_row_count",
    "usable_rolling_ledger_row_count",
    "rolling_ledger_sufficiency_met",
    "research_only",
    "promotion_allowed",
    "official_recommendation_created",
    "official_weight_mutated",
    "weight_mutated",
    "trade_action_created",
    "source_artifact_path",
    "provenance_status",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    if not path.exists():
        return [], [], "MISSING_FILE"
    if path.stat().st_size == 0:
        return [], [], "EMPTY_FILE"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            rows = [{key: clean(value) for key, value in row.items()} for row in reader]
    except csv.Error:
        return [], [], "MALFORMED_CSV"
    return rows, fields, "OK" if fields else "MALFORMED_CSV"


def safety() -> dict[str, str]:
    return {
        "research_only": "TRUE",
        "promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutated": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
    }


def first_value(row: dict[str, str], fields: list[str]) -> str:
    for field in fields:
        value = clean(row.get(field))
        if value:
            return value
    return ""


def extract_markdown_value(text: str, names: list[str]) -> str:
    import re

    for name in names:
        patterns = [
            rf"(?im)^\s*[-*]?\s*{re.escape(name)}\s*[:=]\s*`?([^`\n]+)`?\s*$",
            rf"(?im)\b{re.escape(name)}\s*[:=]\s*`?([A-Za-z0-9_.:\-TZ]+)`?",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return clean(match.group(1))
    return ""


def read_first_csv_row(path: Path) -> dict[str, str]:
    rows, _fields, status = read_csv(path)
    return rows[0] if status == "OK" and rows else {}


def current_lane_context() -> dict[str, str]:
    conclusion_text = CURRENT_DAILY_CONCLUSION.read_text(encoding="utf-8", errors="ignore") if CURRENT_DAILY_CONCLUSION.exists() else ""
    chain_rows, _fields, chain_status = read_csv(CURRENT_CHAIN_LANE_STATUS)
    daily_row = read_first_csv_row(CURRENT_DAILY_RESEARCH_LANE_STATUS)
    promotion_gate = read_first_csv_row(V20_49_PROMOTION_GATE)
    chain_by_name = {clean(row.get("lane_name")): row for row in chain_rows} if chain_status == "OK" else {}
    research_lane = daily_row or chain_by_name.get("CURRENT_DAILY_RESEARCH_LANE", {})
    forward_lane = chain_by_name.get("FORWARD_OUTCOME_VALIDATION_LANE", {})
    pending_forward = first_value(forward_lane, ["pending_forward_target_dates"]) or first_value(research_lane, ["pending_forward_target_dates"])
    reasons: list[str] = []
    forward_blocker = first_value(forward_lane, ["blocker_reason"])
    if clean(pending_forward).upper() == "TRUE" or first_value(forward_lane, ["first_failed_stage"]) == "V20.27":
        reasons.append(forward_blocker or "V20.27 pending forward target dates")
    missing_lineage = clean(promotion_gate.get("missing_promotion_lineage_sources"))
    if missing_lineage:
        reasons.append(f"missing promotion lineage sources: {missing_lineage}")
    blockers = clean(promotion_gate.get("official_promotion_blockers"))
    if blockers:
        reasons.append(blockers)
    return {
        "daily_conclusion_mode": extract_markdown_value(conclusion_text, ["daily_conclusion_mode"]) if conclusion_text else "",
        "current_daily_research_lane_status": first_value(research_lane, ["lane_status"]),
        "forward_outcome_validation_lane_status": first_value(forward_lane, ["lane_status"]),
        "v20_27_forward_pending": tf(clean(pending_forward).upper() == "TRUE" or first_value(forward_lane, ["first_failed_stage"]) == "V20.27"),
        "promotion_blocked_reason": "|".join(dict.fromkeys(reasons)) if reasons else "NONE",
        "conclusion_exists": tf(CURRENT_DAILY_CONCLUSION.exists() and CURRENT_DAILY_CONCLUSION.stat().st_size > 0),
    }


def parse_date_key(value: str) -> str:
    text = clean(value)
    if not text:
        return ""
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else text


def status_acceptable(value: str) -> bool:
    text = clean(value).upper()
    return text.startswith("PASS") or text.startswith("WARN") or text in {"OK", "ACCEPTABLE_WARN"}


def classify_observation(row: dict[str, str], run_id: str, timestamp: str, runner_status: str, source_path: Path) -> dict[str, str]:
    ctx = current_lane_context() if source_path.resolve().is_relative_to(ROOT.resolve()) else {}
    daily_lane = first_value(row, ["current_daily_research_lane_status"]) or ctx.get("current_daily_research_lane_status", "")
    forward_lane = first_value(row, ["forward_outcome_validation_lane_status"]) or ctx.get("forward_outcome_validation_lane_status", "")
    conclusion_mode = first_value(row, ["daily_conclusion_mode"]) or ctx.get("daily_conclusion_mode", "")
    forward_pending = clean(first_value(row, ["v20_27_forward_pending"]) or ctx.get("v20_27_forward_pending")).upper() == "TRUE" or forward_lane == "PENDING_FORWARD_TARGET_DATES"
    promotion_reason = first_value(row, ["promotion_blocked_reason"]) or ctx.get("promotion_blocked_reason", "NONE")
    existing_class = clean(row.get("observation_class"))
    text = clean(runner_status).upper()
    if existing_class:
        observation_class = existing_class
    elif text.startswith("BLOCKED") or text.startswith("FAIL") or text.startswith("ERROR"):
        observation_class = "BLOCKED_DAILY_RESEARCH"
    elif V20_55_WARN_RESEARCH_ONLY in text and conclusion_mode in {"", DAILY_CONCLUSION_RESEARCH_ONLY}:
        observation_class = "RESEARCH_ONLY_READY_PROMOTION_BLOCKED"
    elif text.startswith("PASS"):
        observation_class = "FULL_PASS_OFFICIAL_ELIGIBLE"
    elif forward_pending:
        observation_class = "PENDING_FORWARD_OUTCOME_VALIDATION"
    else:
        observation_class = "INVALID_OR_STALE"
    daily_lane_ok = daily_lane in {"", "PASS", "WARN"}
    conclusion_exists = clean(ctx.get("conclusion_exists", "TRUE")).upper() == "TRUE"
    research_valid = observation_class in {"FULL_PASS_OFFICIAL_ELIGIBLE", "RESEARCH_ONLY_READY_PROMOTION_BLOCKED"} and bool(run_id and timestamp) and daily_lane_ok and conclusion_exists
    official_eligible = observation_class == "FULL_PASS_OFFICIAL_ELIGIBLE" and research_valid and not forward_pending and promotion_reason == "NONE"
    if observation_class == "FULL_PASS_OFFICIAL_ELIGIBLE" and not official_eligible and (forward_pending or promotion_reason != "NONE"):
        observation_class = "RESEARCH_ONLY_READY_PROMOTION_BLOCKED"
    return {
        "observation_class": observation_class,
        "research_observation_valid": tf(research_valid),
        "official_promotion_eligible": tf(official_eligible),
        "promotion_blocker_present": tf(not official_eligible and (forward_pending or promotion_reason != "NONE" or observation_class == "RESEARCH_ONLY_READY_PROMOTION_BLOCKED")),
        "promotion_blocked_reason": promotion_reason if not official_eligible else "NONE",
        "v20_27_forward_pending": tf(forward_pending),
        "daily_conclusion_mode": conclusion_mode or "NA",
        "current_daily_research_lane_status": daily_lane or "NA",
        "forward_outcome_validation_lane_status": forward_lane or "NA",
        "provenance_status": "OK" if conclusion_exists else "MISSING_DAILY_CONCLUSION_ARTIFACT",
    }


def flag_is(row: dict[str, str], field: str, expected: str) -> bool:
    return clean(row.get(field)).upper() == expected


def research_only_true(row: dict[str, str]) -> bool:
    explicit = clean(row.get("research_only")).upper()
    if explicit:
        return explicit == "TRUE"
    return clean(row.get("research_only_daily_conclusion_ready")).upper() == "TRUE"


def safe_false(row: dict[str, str], field: str, inverse_fields: list[str] | None = None) -> bool:
    explicit = clean(row.get(field)).upper()
    if explicit:
        return explicit == "FALSE"
    for inverse in inverse_fields or []:
        if clean(row.get(inverse)).upper() == "TRUE":
            return True
    return False


def validate_observation_row(row: dict[str, str], seen_run_ids: set[str]) -> tuple[str, str, str, str]:
    run_id = first_value(row, ["run_id", "stage_run_id", "source_run_id", "observation_run_id", "daily_run_id"])
    timestamp = first_value(row, ["observation_timestamp", "run_timestamp", "source_timestamp_utc", "created_at_utc", "created_at", "as_of_date", "observation_date", "date", "run_date"])
    runner_status = first_value(row, ["v20_55_status", "daily_runner_status", "runner_status", "run_status", "health_status", "overall_status", "status", "observation_status"])
    reasons: list[str] = []
    if not run_id:
        reasons.append("MISSING_RUN_ID")
    if not timestamp:
        reasons.append("MISSING_RUN_TIMESTAMP")
    if not runner_status or not status_acceptable(runner_status):
        reasons.append("RUNNER_STATUS_NOT_PASS_OR_ACCEPTABLE_WARN")
    if not research_only_true(row):
        reasons.append("RESEARCH_ONLY_NOT_TRUE")
    if not safe_false(row, "official_recommendation_created", ["no_official_recommendation"]):
        reasons.append("OFFICIAL_RECOMMENDATION_CREATED_NOT_FALSE")
    if not safe_false(row, "official_weight_mutated", ["no_official_weight_mutation", "no_official_ranking_mutation"]):
        reasons.append("OFFICIAL_WEIGHT_MUTATED_NOT_FALSE")
    if not safe_false(row, "trade_action_created", ["no_trade_action", "no_trading_signal", "no_broker_action", "no_order_execution"]):
        reasons.append("TRADE_ACTION_CREATED_NOT_FALSE")
    if clean(row.get("weight_mutated")) and not safe_false(row, "weight_mutated", ["no_official_weight_mutation", "no_official_ranking_mutation"]):
        reasons.append("WEIGHT_MUTATED_NOT_FALSE")
    if clean(row.get("eligible_for_official_promotion")).upper() == "TRUE" or clean(row.get("official_promotion_eligible")).upper() == "TRUE":
        reasons.append("OFFICIAL_PROMOTION_ELIGIBLE_NOT_ALLOWED_IN_RESEARCH_ACCUMULATION")
    if run_id and run_id in seen_run_ids:
        reasons.append("DUPLICATE_RUN_ID")
    if reasons:
        return "REJECTED", run_id or "MISSING_RUN_ID", timestamp, "|".join(reasons)
    seen_run_ids.add(run_id)
    return "VALID", run_id, timestamp, "NA"


def v20_95_context(detail_path: Path = V20_95_DETAIL, summary_path: Path = V20_95_SUMMARY) -> tuple[bool, int, str]:
    rows, _, status = read_csv(detail_path)
    if status != "OK" or not rows:
        return False, DEFAULT_REQUIRED_RUN_COUNT, status
    if not summary_path.exists() or summary_path.stat().st_size == 0:
        return False, DEFAULT_REQUIRED_RUN_COUNT, "MISSING_SUMMARY"
    by_category = {clean(row.get("blocker_category")): row for row in rows}
    multi = by_category.get("multi_run_history_sufficiency", {})
    v20_94_inherited = "PASS_EVIDENCE_CHAIN_CLOSED_WITH_OPTIONAL_WARN" in summary_path.read_text(encoding="utf-8")
    promotion_blocked = "PASS_EVIDENCE_CHAIN_CLOSED_PROMOTION_STILL_BLOCKED" in summary_path.read_text(encoding="utf-8")
    safe = all(clean(row.get("promotion_allowed")) == "FALSE" for row in rows)
    gap_exists = clean(multi.get("sufficiency_met")) != "TRUE"
    required = int(clean(multi.get("required_run_count") or DEFAULT_REQUIRED_RUN_COUNT) or DEFAULT_REQUIRED_RUN_COUNT)
    return bool(v20_94_inherited and promotion_blocked and safe and gap_exists), required, "OK"


def discover_observations(candidate_paths: list[Path] = OBSERVATION_INPUT_CANDIDATES) -> tuple[list[dict[str, str]], list[str]]:
    detail_rows: list[dict[str, str]] = []
    missing_sources: list[str] = []
    seen: set[str] = set()
    any_source = False
    for path in candidate_paths:
        rows, _fields, status = read_csv(path)
        if status != "OK":
            missing_sources.append(rel(path))
            continue
        any_source = True
        for item in rows:
            row_status, run_id, timestamp, reason = validate_observation_row(item, seen)
            runner_status = first_value(item, ["v20_55_status", "daily_runner_status", "runner_status", "run_status", "health_status", "overall_status", "status", "observation_status"])
            classification = classify_observation(item, run_id if run_id != "MISSING_RUN_ID" else "", timestamp, runner_status, path)
            if row_status == "VALID" and classification["research_observation_valid"] != "TRUE":
                row_status = "REJECTED"
                reason = classification["provenance_status"] if classification["provenance_status"] != "OK" else "OBSERVATION_CLASS_NOT_RESEARCH_VALID"
            detail_rows.append(
                {
                    "record_type": "OBSERVATION_RUN",
                    "source_file": rel(path),
                    "source_status": "OK",
                    "run_id": run_id,
                    "run_timestamp": timestamp,
                    "observation_timestamp": timestamp,
                    "v20_55_status": runner_status,
                    "daily_conclusion_mode": classification["daily_conclusion_mode"],
                    "current_daily_research_lane_status": classification["current_daily_research_lane_status"],
                    "forward_outcome_validation_lane_status": classification["forward_outcome_validation_lane_status"],
                    "observation_class": classification["observation_class"],
                    "research_observation_valid": tf(row_status == "VALID"),
                    "official_promotion_eligible": classification["official_promotion_eligible"],
                    "promotion_blocker_present": classification["promotion_blocker_present"],
                    "promotion_blocked_reason": classification["promotion_blocked_reason"],
                    "v20_27_forward_pending": classification["v20_27_forward_pending"],
                    "daily_runner_status": runner_status,
                    "row_status": row_status,
                    "rejection_reason": reason,
                    "source_artifact_path": rel(path),
                    "provenance_status": classification["provenance_status"],
                }
            )
    if not any_source:
        detail_rows.append(
            {
                "record_type": "OBSERVATION_SOURCE_AUDIT",
                "source_file": "NA",
                "source_status": "MISSING_OPTIONAL_INPUTS",
                "run_id": "NA",
                "run_timestamp": "NA",
                "daily_runner_status": "NA",
                "row_status": "WARN",
                "rejection_reason": "NO_OPTIONAL_OBSERVATION_INPUT_FILES_FOUND",
            }
        )
    return detail_rows, missing_sources


def rolling_ledger_metrics(candidate_paths: list[Path] = ROLLING_LEDGER_CANDIDATES) -> dict[str, str]:
    for path in candidate_paths:
        rows, _fields, status = read_csv(path)
        if status != "OK":
            continue
        usable_keys: set[tuple[str, str]] = set()
        for item in rows:
            run_id = first_value(item, ["run_id", "stage_run_id", "source_run_id", "observation_run_id", "daily_run_id"])
            date_key = parse_date_key(first_value(item, ["run_timestamp", "created_at_utc", "as_of_date", "observation_date", "date", "run_date"]))
            if run_id or date_key:
                usable_keys.add((run_id, date_key))
        return {
            "rolling_ledger_source_file": rel(path),
            "rolling_ledger_status": "OK",
            "rolling_ledger_row_count": str(len(rows)),
            "usable_rolling_ledger_row_count": str(len(usable_keys)),
            "rolling_ledger_sufficiency_met": tf(bool(usable_keys)),
        }
    return {
        "rolling_ledger_source_file": "NA",
        "rolling_ledger_status": "MISSING_OPTIONAL_INPUT",
        "rolling_ledger_row_count": "0",
        "usable_rolling_ledger_row_count": "0",
        "rolling_ledger_sufficiency_met": "FALSE",
    }


def summarize_observations(rows: list[dict[str, str]], required_run_count: int, ledger: dict[str, str]) -> dict[str, str]:
    observation_rows = [row for row in rows if row["record_type"] == "OBSERVATION_RUN"]
    valid = [row for row in observation_rows if row["row_status"] == "VALID"]
    rejected = [row for row in observation_rows if row["row_status"] == "REJECTED"]
    official_eligible = [row for row in valid if row.get("official_promotion_eligible") == "TRUE"]
    duplicate_count = sum("DUPLICATE_RUN_ID" in row["rejection_reason"] for row in rejected)
    valid_dates = sorted(parse_date_key(row["run_timestamp"]) for row in valid if parse_date_key(row["run_timestamp"]))
    remaining = max(0, required_run_count - len(valid))
    return {
        "discovered_run_count": str(len(observation_rows)),
        "valid_observation_run_count": str(len(valid)),
        "research_observation_count": str(len(valid)),
        "official_promotion_eligible_count": str(len(official_eligible)),
        "invalid_observation_run_count": str(len(rejected)),
        "duplicate_run_count": str(duplicate_count),
        "required_run_count": str(required_run_count),
        "remaining_run_count": str(remaining),
        "multi_run_sufficiency_met": tf(len(valid) >= required_run_count),
        "earliest_valid_observation_date": valid_dates[0] if valid_dates else "NA",
        "latest_valid_observation_date": valid_dates[-1] if valid_dates else "NA",
        "valid_run_ids": "|".join(row["run_id"] for row in valid) if valid else "NONE",
        "rejected_run_ids": "|".join(row["run_id"] for row in rejected) if rejected else "NONE",
        "rejection_reasons": "|".join(dict.fromkeys(row["rejection_reason"] for row in rejected if row["rejection_reason"] != "NA")) if rejected else "NONE",
        **ledger,
    }


def apply_summary_to_rows(rows: list[dict[str, str]], summary: dict[str, str]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for item in rows:
        row = {field: item.get(field, "") for field in DETAIL_FIELDS}
        row.update(summary)
        row.update(safety())
        output.append(row)
    if not output:
        row = {field: "" for field in DETAIL_FIELDS}
        row.update(
            {
                "record_type": "OBSERVATION_SOURCE_AUDIT",
                "source_file": "NA",
                "source_status": "MISSING_OPTIONAL_INPUTS",
                "run_id": "NA",
                "run_timestamp": "NA",
                "daily_runner_status": "NA",
                "row_status": "WARN",
                "rejection_reason": "NO_OPTIONAL_OBSERVATION_INPUT_FILES_FOUND",
            }
        )
        row.update(summary)
        row.update(safety())
        output.append(row)
    return output


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DETAIL_FIELDS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, status: str, summary: dict[str, str]) -> None:
    lines = [
        "# V20.96 Multi-Run Observation Accumulation Orchestrator",
        "",
        "## Inherited V20.95 Status",
        f"- final_status: {status}",
        "- v20_95_prefight_readable: TRUE",
        "",
        "## Observation Run Counts",
        f"- discovered_run_count: {summary['discovered_run_count']}",
        f"- valid_observation_run_count: {summary['valid_observation_run_count']}",
        f"- research_observation_count: {summary.get('research_observation_count', summary['valid_observation_run_count'])}",
        f"- official_promotion_eligible_count: {summary.get('official_promotion_eligible_count', '0')}",
        f"- invalid_observation_run_count: {summary['invalid_observation_run_count']}",
        f"- duplicate_run_count: {summary['duplicate_run_count']}",
        f"- required_run_count: {summary['required_run_count']}",
        f"- remaining_run_count: {summary['remaining_run_count']}",
        f"- multi_run_sufficiency_met: {summary['multi_run_sufficiency_met']}",
        f"- earliest_valid_observation_date: {summary['earliest_valid_observation_date']}",
        f"- latest_valid_observation_date: {summary['latest_valid_observation_date']}",
        "",
        "## Rejected Run Reasons",
        f"- rejected_run_ids: {summary['rejected_run_ids']}",
        f"- rejection_reasons: {summary['rejection_reasons']}",
        "",
        "## Rolling Ledger Status",
        f"- rolling_ledger_source_file: {summary['rolling_ledger_source_file']}",
        f"- rolling_ledger_status: {summary['rolling_ledger_status']}",
        f"- rolling_ledger_row_count: {summary['rolling_ledger_row_count']}",
        f"- usable_rolling_ledger_row_count: {summary['usable_rolling_ledger_row_count']}",
        f"- rolling_ledger_sufficiency_met: {summary['rolling_ledger_sufficiency_met']}",
        "",
        "## Safety Confirmation",
        "- research_only: TRUE",
        "- promotion_allowed: FALSE",
        "- official_recommendation_created: FALSE",
        "- official_weight_mutated: FALSE",
        "- weight_mutated: FALSE",
        "- trade_action_created: FALSE",
        "",
        "## Recommended Next Stages",
        "- Continue daily observation collection until required_run_count is met.",
        "- Refresh V20.64 rolling evidence ledger after additional valid runs.",
        "- Rerun V20.95 after V20.96 reports sufficiency.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def run_orchestrator(
    v20_95_detail: Path = V20_95_DETAIL,
    v20_95_summary: Path = V20_95_SUMMARY,
    observation_paths: list[Path] = OBSERVATION_INPUT_CANDIDATES,
    ledger_paths: list[Path] = ROLLING_LEDGER_CANDIDATES,
) -> tuple[list[dict[str, str]], str, dict[str, str]]:
    v20_95_ok, required_run_count, v20_95_status = v20_95_context(v20_95_detail, v20_95_summary)
    if not v20_95_ok:
        ledger = rolling_ledger_metrics(ledger_paths)
        summary = summarize_observations([], required_run_count, ledger)
        rows = apply_summary_to_rows(
            [
                {
                    "record_type": "V20_95_PREFLIGHT_AUDIT",
                    "source_file": rel(v20_95_detail),
                    "source_status": v20_95_status,
                    "run_id": "NA",
                    "run_timestamp": "NA",
                    "daily_runner_status": "NA",
                    "row_status": "BLOCKED",
                    "rejection_reason": "V20_95_PREFLIGHT_MISSING_OR_MULTI_RUN_GAP_NOT_CONFIRMED",
                }
            ],
            summary,
        )
        return rows, BLOCKED_STATUS, summary
    observation_rows, _missing = discover_observations(observation_paths)
    ledger = rolling_ledger_metrics(ledger_paths)
    summary = summarize_observations(observation_rows, required_run_count, ledger)
    rows = apply_summary_to_rows(observation_rows, summary)
    status = PASS_STATUS if summary["multi_run_sufficiency_met"] == "TRUE" else WARN_STATUS
    return rows, status, summary


def main() -> int:
    rows, status, summary = run_orchestrator()
    write_csv(DETAIL, rows)
    write_summary(SUMMARY, status, summary)
    shutil.copyfile(DETAIL, DETAIL_ALIAS)
    shutil.copyfile(SUMMARY, SUMMARY_ALIAS)
    shutil.copyfile(DETAIL, ACCUMULATION)
    shutil.copyfile(DETAIL, ACCUMULATION_ALIAS)
    print(status)
    for key in [
        "discovered_run_count",
        "valid_observation_run_count",
        "research_observation_count",
        "official_promotion_eligible_count",
        "invalid_observation_run_count",
        "duplicate_run_count",
        "required_run_count",
        "remaining_run_count",
        "multi_run_sufficiency_met",
        "rolling_ledger_status",
        "rejection_reasons",
    ]:
        print(f"{key.upper()}={summary[key]}")
    print("RESEARCH_ONLY=TRUE")
    print("PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("OFFICIAL_WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    return 1 if status == BLOCKED_STATUS else 0


if __name__ == "__main__":
    raise SystemExit(main())
