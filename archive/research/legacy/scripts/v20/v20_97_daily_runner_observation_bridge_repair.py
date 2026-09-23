#!/usr/bin/env python
"""V20.97 daily runner observation bridge repair.

Research-only bridge repair layer. It normalizes available daily runner and
daily operation artifacts into observation rows that V20.96 can discover.
"""

from __future__ import annotations

import csv
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "outputs" / "v20" / "evidence"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
REPAIR = ROOT / "outputs" / "v20" / "repair"

PASS_STATUS = "PASS_V20_97_DAILY_RUNNER_OBSERVATION_BRIDGE_REPAIRED"
WARN_STATUS = "WARN_V20_97_NO_VALID_DAILY_RUNNER_OBSERVATIONS_FOUND"
BLOCKED_STATUS = "BLOCKED_V20_97_MISSING_REQUIRED_V20_96_CONTEXT"

V20_96_CONTEXT = EVIDENCE / "V20_CURRENT_MULTI_RUN_OBSERVATION_ACCUMULATION_DETAIL.csv"

DETAIL = EVIDENCE / "V20_97_DAILY_RUNNER_OBSERVATION_BRIDGE_REPAIR_DETAIL.csv"
SUMMARY = EVIDENCE / "V20_97_DAILY_RUNNER_OBSERVATION_BRIDGE_REPAIR_SUMMARY.md"
DETAIL_ALIAS = EVIDENCE / "V20_CURRENT_DAILY_RUNNER_OBSERVATION_BRIDGE_REPAIR_DETAIL.csv"
SUMMARY_ALIAS = EVIDENCE / "V20_CURRENT_DAILY_RUNNER_OBSERVATION_BRIDGE_REPAIR_SUMMARY.md"
BRIDGE = EVIDENCE / "V20_97_DAILY_RUNNER_OBSERVATION_BRIDGE.csv"
BRIDGE_ALIAS = EVIDENCE / "V20_CURRENT_DAILY_RUNNER_OBSERVATION_BRIDGE.csv"

CURRENT_DAILY_CONCLUSION = READ_CENTER / "V20_CURRENT_DAILY_CONCLUSION.md"
CURRENT_CHAIN_LANE_STATUS = REPAIR / "V20_CURRENT_CHAIN_LANE_STATUS.csv"
CURRENT_DAILY_RESEARCH_LANE_STATUS = REPAIR / "V20_CURRENT_DAILY_RESEARCH_LANE_STATUS.csv"
V20_49_PROMOTION_GATE = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

V20_55_PASS = "PASS_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER"
V20_55_WARN_RESEARCH_ONLY = "WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED"
DAILY_CONCLUSION_RESEARCH_ONLY = "RESEARCH_ONLY_DAILY_CONCLUSION_READY_OFFICIAL_PROMOTION_BLOCKED"

KNOWN_SOURCES = [
    READ_CENTER / "V20_CURRENT_DAILY_OPERATION_EXPORT_BRIEF.md",
    READ_CENTER / "V20_CURRENT_DAILY_OPERATION_READABLE_REPORT.md",
    READ_CENTER / "V20_CURRENT_DAILY_ONE_CLICK_RESEARCH_RUNNER_REPORT.md",
    READ_CENTER / "V20_CURRENT_DAILY_OPERATION_RESEARCH_PACKET_DRY_RUN.md",
    READ_CENTER / "V20_CURRENT_DAILY_OPERATION_REVIEW_ACCEPTANCE_AND_EXPORT_GATE.md",
    EVIDENCE / "V20_CURRENT_DAILY_RUNNER_HEALTH_AND_OBSERVATION_INTEGRATION.csv",
    EVIDENCE / "V20_CURRENT_DAILY_OBSERVATION_STATUS_BRIDGE.csv",
    EVIDENCE / "V20_CURRENT_OBSERVATION_INTAKE.csv",
    CONSOLIDATION / "V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER_OUTPUT.csv",
    READ_CENTER / "V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER_REPORT.md",
    CONSOLIDATION / "V20_59_OBSERVATION_INTAKE.csv",
    CONSOLIDATION / "V20_61_DAILY_OBSERVATION_BRIDGE.csv",
    CONSOLIDATION / "V20_63_DAILY_RUNNER_HEALTH_TABLE.csv",
    CONSOLIDATION / "V20_63_OBSERVATION_INTEGRATION_TABLE.csv",
]

OUTPUT_FIELDS = [
    "observation_run_id",
    "source_stage",
    "source_file",
    "source_status",
    "source_status_raw",
    "source_status_normalized",
    "source_status_extraction_method",
    "source_status_accepted",
    "source_run_id",
    "source_timestamp_utc",
    "observation_date",
    "daily_runner_status",
    "observation_valid",
    "observation_rejection_reason",
    "duplicate_key",
    "research_only",
    "promotion_allowed",
    "nasdaq_hurdle_passed",
    "official_recommendation_created",
    "official_weight_mutated",
    "trade_action_created",
    "eligible_for_v20_96",
    "eligible_for_v20_96_research_only",
    "eligible_for_official_promotion",
    "run_id",
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
    "weight_mutated",
    "source_artifact_path",
    "provenance_status",
    "notes",
    "source_file_exists",
    "candidate_rank",
    "candidate_selected",
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


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def source_stage(path: Path) -> str:
    name = path.name.upper()
    match = re.search(r"V20_(\d+[A-Z]?)", name)
    return f"V20.{match.group(1)}" if match else "UNKNOWN_DAILY_RUNNER_SOURCE"


def file_mtime_utc(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def date_from_timestamp(value: str) -> str:
    text = clean(value)
    if not text:
        return ""
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else text


def normalize_status_token(value: str) -> str:
    text = clean(value).upper()
    if not text:
        return ""
    match = re.search(r"\b(PASS(?:_[A-Z0-9]+)*|WARN(?:_[A-Z0-9]+)*|BLOCKED(?:_[A-Z0-9]+)*|FAIL|ERROR|UNKNOWN)\b", text)
    return match.group(1) if match else text


def status_acceptable(value: str) -> bool:
    text = normalize_status_token(value)
    if not text:
        return False
    if text == "PASS" or text.startswith("PASS_"):
        return True
    if text.startswith("WARN_"):
        return True
    return False


def first_value(row: dict[str, str], fields: list[str]) -> str:
    for field in fields:
        value = clean(row.get(field))
        if value:
            return value
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


def classify_observation(
    status: str,
    research_only: str,
    official_rec: str,
    official_weight: str,
    trade: str,
    timestamp: str,
    run_id: str,
    path: Path,
    ctx: dict[str, str] | None = None,
) -> dict[str, str]:
    ctx = ctx or {}
    normalized = normalize_status_token(status)
    daily_lane = clean(ctx.get("current_daily_research_lane_status"))
    forward_lane = clean(ctx.get("forward_outcome_validation_lane_status"))
    conclusion_mode = clean(ctx.get("daily_conclusion_mode"))
    safe = clean(research_only).upper() == "TRUE" and clean(official_rec).upper() == "FALSE" and clean(official_weight).upper() == "FALSE" and clean(trade).upper() == "FALSE"
    has_identity = bool(clean(run_id) and clean(timestamp))
    conclusion_exists = clean(ctx.get("conclusion_exists", "TRUE")).upper() == "TRUE"
    daily_lane_ok = daily_lane in {"", "PASS", "WARN"}
    forward_pending = clean(ctx.get("v20_27_forward_pending")).upper() == "TRUE" or forward_lane == "PENDING_FORWARD_TARGET_DATES"
    promotion_reason = clean(ctx.get("promotion_blocked_reason")) or "NONE"
    if normalized.startswith("BLOCKED") or normalized.startswith("FAIL") or normalized.startswith("ERROR"):
        observation_class = "BLOCKED_DAILY_RESEARCH"
    elif forward_pending and normalized == "":
        observation_class = "PENDING_FORWARD_OUTCOME_VALIDATION"
    elif normalized.startswith("WARN") and (V20_55_WARN_RESEARCH_ONLY in normalized or not ctx) and conclusion_mode in {"", DAILY_CONCLUSION_RESEARCH_ONLY}:
        observation_class = "RESEARCH_ONLY_READY_PROMOTION_BLOCKED"
    elif normalized.startswith("PASS"):
        observation_class = "FULL_PASS_OFFICIAL_ELIGIBLE"
    elif forward_pending:
        observation_class = "PENDING_FORWARD_OUTCOME_VALIDATION"
    else:
        observation_class = "INVALID_OR_STALE"
    research_valid = observation_class in {"FULL_PASS_OFFICIAL_ELIGIBLE", "RESEARCH_ONLY_READY_PROMOTION_BLOCKED"} and safe and has_identity and conclusion_exists and daily_lane_ok
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
        "source_artifact_path": rel(path),
        "provenance_status": "OK" if conclusion_exists else "MISSING_DAILY_CONCLUSION_ARTIFACT",
    }


def extract_markdown_value(text: str, names: list[str]) -> str:
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


def extract_markdown_status(text: str) -> tuple[str, str]:
    labeled = extract_markdown_value(
        text,
        [
            "Final wrapper status",
            "final wrapper status",
            "Wrapper status",
            "wrapper status",
            "Final status",
            "final status",
            "status",
            "daily_runner_status",
            "runner_status",
            "run_status",
            "final_status",
        ],
    )
    if labeled:
        return labeled, "LABELED_MARKDOWN_STATUS"
    token = re.search(r"\b(PASS_V20_[A-Z0-9_]+|PASS_[A-Z0-9_]+|WARN_V20_[A-Z0-9_]+|WARN_[A-Z0-9_]+|BLOCKED_V20_[A-Z0-9_]+|BLOCKED_[A-Z0-9_]+)\b", text, re.IGNORECASE)
    if token:
        return token.group(1), "TOKEN_SCAN_MARKDOWN_STATUS"
    return "", "STATUS_NOT_FOUND"


def markdown_to_row(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    status, method = extract_markdown_status(text)
    return {
        "run_id": extract_markdown_value(text, ["run_id", "Run ID", "stage_run_id", "source_run_id", "V20_55_RUN_ID", "V20_47_RUN_ID"]),
        "ranking_timestamp_utc": extract_markdown_value(text, ["ranking_timestamp_utc", "created_at_utc", "run_timestamp", "Started", "as_of_date", "date"]),
        "daily_runner_status": status,
        "source_status_extraction_method": method,
        "research_only": extract_markdown_value(text, ["research_only"]),
        "promotion_allowed": extract_markdown_value(text, ["promotion_allowed"]),
        "nasdaq_hurdle_passed": extract_markdown_value(text, ["nasdaq_hurdle_passed"]),
        "official_recommendation_created": extract_markdown_value(text, ["official_recommendation_created"]),
        "official_weight_mutated": extract_markdown_value(text, ["official_weight_mutated"]),
        "trade_action_created": extract_markdown_value(text, ["trade_action_created"]),
    }


def derive_run_id(row: dict[str, str], path: Path, timestamp: str, notes: list[str]) -> str:
    explicit = first_value(row, ["observation_run_id", "run_id", "stage_run_id", "source_run_id", "daily_run_id"])
    if explicit:
        return explicit
    for value in row.values():
        text = clean(value)
        if re.match(r"V20_(?:55|47)_[A-Za-z0-9T_:-]+", text):
            notes.append("RUN_ID_FROM_V20_TOKEN_FIELD")
            return text
    ranking = first_value(row, ["ranking_timestamp_utc", "ranking_timestamp", "created_at_utc", "run_timestamp", "as_of_date", "date"])
    if ranking:
        notes.append("RUN_ID_DERIVED_FROM_TIMESTAMP_AND_SOURCE_STAGE")
        return f"{source_stage(path).replace('.', '_')}_{ranking}"
    notes.append("RUN_ID_FALLBACK_FILE_STEM_MTIME")
    return f"{path.stem}_{int(path.stat().st_mtime)}"


def normalize_source_row(path: Path, row: dict[str, str], source_status: str = "OK") -> dict[str, str]:
    notes: list[str] = []
    timestamp = first_value(row, ["source_timestamp_utc", "ranking_timestamp_utc", "created_at_utc", "created_at", "run_timestamp", "as_of_date", "date"])
    if not timestamp and path.exists():
        timestamp = file_mtime_utc(path)
        notes.append("TIMESTAMP_DERIVED_FROM_FILE_MTIME")
    observation_date = date_from_timestamp(timestamp)
    run_id = derive_run_id(row, path, timestamp, notes)
    daily_status = first_value(row, ["daily_runner_status", "runner_status", "run_status", "health_status", "status", "final_status", "observation_status"])
    extraction_method = first_value(row, ["source_status_extraction_method"]) or "STRUCTURED_STATUS_FIELD"
    normalized_status = normalize_status_token(daily_status)
    status_accepted = status_acceptable(daily_status)
    research_only = first_value(row, ["research_only"]) or "TRUE"
    promotion_allowed = first_value(row, ["promotion_allowed"]) or "FALSE"
    nasdaq = first_value(row, ["nasdaq_hurdle_passed"]) or "FALSE"
    official_rec = first_value(row, ["official_recommendation_created"]) or "FALSE"
    official_weight = first_value(row, ["official_weight_mutated"]) or "FALSE"
    trade = first_value(row, ["trade_action_created"]) or "FALSE"
    ctx = current_lane_context() if path.resolve().is_relative_to(ROOT.resolve()) else {}
    classification = classify_observation(daily_status, research_only, official_rec, official_weight, trade, timestamp, run_id, path, ctx)
    reasons: list[str] = []
    if not run_id:
        reasons.append("MISSING_OBSERVATION_RUN_ID")
    if not timestamp or not observation_date:
        reasons.append("MISSING_SOURCE_TIMESTAMP")
    if not daily_status or not status_accepted:
        reasons.append("SOURCE_STATUS_NOT_PASS_OR_ACCEPTABLE_WARN")
    if clean(research_only).upper() != "TRUE":
        reasons.append("RESEARCH_ONLY_NOT_TRUE")
    if clean(promotion_allowed).upper() != "FALSE":
        reasons.append("PROMOTION_ALLOWED_NOT_FALSE")
    if clean(official_rec).upper() != "FALSE":
        reasons.append("OFFICIAL_RECOMMENDATION_CREATED_NOT_FALSE")
    if clean(official_weight).upper() != "FALSE":
        reasons.append("OFFICIAL_WEIGHT_MUTATED_NOT_FALSE")
    if clean(trade).upper() != "FALSE":
        reasons.append("TRADE_ACTION_CREATED_NOT_FALSE")
    if classification["research_observation_valid"] != "TRUE" and not reasons:
        reasons.append(classification["provenance_status"] if classification["provenance_status"] != "OK" else "OBSERVATION_CLASS_NOT_RESEARCH_VALID")
    valid = not reasons and classification["research_observation_valid"] == "TRUE"
    duplicate_key = run_id if run_id else f"{rel(path)}|{observation_date or 'NO_DATE'}"
    return {
        "observation_run_id": run_id,
        "source_stage": source_stage(path),
        "source_file": rel(path),
        "source_status": source_status,
        "source_status_raw": daily_status,
        "source_status_normalized": normalized_status or "NA",
        "source_status_extraction_method": extraction_method,
        "source_status_accepted": tf(status_accepted),
        "source_run_id": first_value(row, ["source_run_id", "stage_run_id", "run_id"]) or run_id,
        "source_timestamp_utc": timestamp,
        "observation_date": observation_date,
        "daily_runner_status": normalized_status or daily_status,
        "observation_valid": tf(valid),
        "observation_rejection_reason": "NA" if valid else "|".join(reasons),
        "duplicate_key": duplicate_key,
        "research_only": "TRUE",
        "promotion_allowed": "FALSE",
        "nasdaq_hurdle_passed": "FALSE" if clean(nasdaq).upper() != "TRUE" else "TRUE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "eligible_for_v20_96": tf(valid),
        "eligible_for_v20_96_research_only": tf(valid),
        "eligible_for_official_promotion": classification["official_promotion_eligible"],
        "run_id": run_id,
        "observation_timestamp": timestamp,
        "v20_55_status": normalized_status or daily_status,
        "daily_conclusion_mode": classification["daily_conclusion_mode"],
        "current_daily_research_lane_status": classification["current_daily_research_lane_status"],
        "forward_outcome_validation_lane_status": classification["forward_outcome_validation_lane_status"],
        "observation_class": classification["observation_class"],
        "research_observation_valid": tf(valid),
        "official_promotion_eligible": classification["official_promotion_eligible"],
        "promotion_blocker_present": classification["promotion_blocker_present"],
        "promotion_blocked_reason": classification["promotion_blocked_reason"],
        "v20_27_forward_pending": classification["v20_27_forward_pending"],
        "weight_mutated": "FALSE",
        "source_artifact_path": rel(path),
        "provenance_status": classification["provenance_status"],
        "notes": "|".join(notes) if notes else "NA",
        "source_file_exists": "TRUE",
        "candidate_rank": "0",
        "candidate_selected": "FALSE",
    }


def normalize_file(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() in {".md", ".txt"}:
        return [normalize_source_row(path, markdown_to_row(path))]
    rows, _fields, status = read_csv(path)
    if status != "OK":
        return []
    return [normalize_source_row(path, row) for row in rows]


def excluded_discovery_path(path: Path) -> bool:
    name = path.name.upper()
    return (
        "MULTI_RUN_OBSERVATION_ACCUMULATION" in name
        or "DAILY_RUNNER_OBSERVATION_BRIDGE_REPAIR" in name
        or "DAILY_RESEARCH_OBSERVATION_OPERATOR" in name
        or "DAILY_RESEARCH_OBSERVATION_LEDGER" in name
        or name in {"V20_97_DAILY_RUNNER_OBSERVATION_BRIDGE.CSV", "V20_CURRENT_DAILY_RUNNER_OBSERVATION_BRIDGE.CSV"}
    )


def discover_sources(paths: list[Path] = KNOWN_SOURCES, expand_versioned: bool = True) -> tuple[list[Path], list[Path]]:
    found: list[Path] = []
    missing: list[Path] = []
    expanded = list(paths)
    if expand_versioned:
        expanded.extend(sorted(READ_CENTER.glob("*V20_55*DAILY_ONE_CLICK*REPORT*.md")))
        expanded.extend(sorted(READ_CENTER.glob("*DAILY_ONE_CLICK_RESEARCH_RUNNER*.md")))
        expanded.extend(sorted(READ_CENTER.glob("*DAILY_OPERATION*.md")))
        expanded.extend(sorted(EVIDENCE.glob("*V20_59*OBSERVATION*.csv")))
        expanded.extend(sorted(EVIDENCE.glob("*V20_61*OBSERVATION*BRIDGE*.csv")))
        expanded.extend(sorted(EVIDENCE.glob("*V20_63*DAILY_RUNNER_HEALTH*.csv")))
        expanded.extend(sorted(EVIDENCE.glob("*V20_64*ROLLING*LEDGER*.csv")))
        expanded.extend(sorted(EVIDENCE.glob("*V20_CURRENT*DAILY_RUNNER*.csv")))
        expanded.extend(sorted(READ_CENTER.glob("V20_55*DAILY*REPORT*.md")))
        expanded.extend(sorted(CONSOLIDATION.glob("V20_5[579]*OBSERVATION*.csv")))
        expanded.extend(sorted(CONSOLIDATION.glob("V20_6[13]*OBSERVATION*.csv")))
        expanded.extend(sorted(EVIDENCE.glob("V20_CURRENT*OBSERVATION*.csv")))
    seen: set[Path] = set()
    for path in expanded:
        if path in seen:
            continue
        seen.add(path)
        if excluded_discovery_path(path):
            continue
        if path.exists() and path.stat().st_size > 0:
            found.append(path)
        else:
            missing.append(path)
    return found, missing


def timestamp_rank(value: str) -> float:
    text = clean(value).replace("Z", "+00:00")
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return 0.0


def candidate_sort_key(row: dict[str, str]) -> tuple[int, int, float, str]:
    valid = row["observation_valid"] == "TRUE"
    status = clean(row.get("source_status_normalized")).upper()
    status_score = 0 if status.startswith("PASS") else (1 if status.startswith("WARN") else 2)
    timestamp = clean(row.get("source_timestamp_utc"))
    return (0 if valid else 1, status_score, -timestamp_rank(timestamp), clean(row.get("observation_run_id")))


def rank_candidates(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    sorted_rows = sorted(rows, key=candidate_sort_key)
    for index, row in enumerate(sorted_rows, start=1):
        row["candidate_rank"] = str(index)
        row["candidate_selected"] = "FALSE"
    return sorted_rows


def dedupe_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], int]:
    seen: set[str] = set()
    output: list[dict[str, str]] = []
    duplicates = 0
    for row in rank_candidates(rows):
        key = clean(row.get("observation_run_id")) or clean(row.get("duplicate_key"))
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        row["candidate_selected"] = "TRUE"
        output.append(row)
    return output, duplicates


def context_ok(path: Path = V20_96_CONTEXT) -> bool:
    rows, _fields, status = read_csv(path)
    return status == "OK" and bool(rows)


def build_bridge_rows(paths: list[Path] = KNOWN_SOURCES, require_context: bool = True, expand_versioned: bool = True) -> tuple[list[dict[str, str]], dict[str, object], str]:
    if require_context and not context_ok():
        return [], {"source_files_scanned": 0, "source_files_found": 0, "source_files_missing": 0, "duplicate_count": 0}, BLOCKED_STATUS
    found, missing = discover_sources(paths, expand_versioned=expand_versioned)
    normalized: list[dict[str, str]] = []
    for path in found:
        normalized.extend(normalize_file(path))
    deduped, duplicates = dedupe_rows(normalized)
    valid_count = sum(row["observation_valid"] == "TRUE" for row in deduped)
    invalid_count = sum(row["observation_valid"] != "TRUE" for row in deduped)
    eligible_count = sum(row["eligible_for_v20_96"] == "TRUE" for row in deduped)
    official_eligible_count = sum(row["official_promotion_eligible"] == "TRUE" for row in deduped)
    reasons = sorted({row["observation_rejection_reason"] for row in deduped if row["observation_rejection_reason"] != "NA"})
    raw_statuses = sorted({row["source_status_raw"] for row in deduped if row["source_status_raw"]})
    normalized_statuses = sorted({row["source_status_normalized"] for row in deduped if row["source_status_normalized"] and row["source_status_normalized"] != "NA"})
    pass_candidates = sum(clean(row.get("source_status_normalized")).upper().startswith("PASS") for row in deduped)
    warn_candidates = sum(clean(row.get("source_status_normalized")).upper().startswith("WARN") for row in deduped)
    blocked_na_candidates = len(deduped) - pass_candidates - warn_candidates
    metrics = {
        "source_files_scanned": len(found) + len(missing),
        "source_files_found": len(found),
        "source_files_missing": len(missing),
        "normalized_observation_row_count": len(normalized),
        "canonical_observation_row_count": len(deduped),
        "valid_observation_row_count": valid_count,
        "invalid_observation_row_count": invalid_count,
        "duplicate_count": duplicates,
        "eligible_for_v20_96_count": eligible_count,
        "valid_research_observation_rows": eligible_count,
        "eligible_for_v20_96_research_only": eligible_count,
        "eligible_for_official_promotion": official_eligible_count,
        "pass_candidate_count": pass_candidates,
        "warn_candidate_count": warn_candidates,
        "blocked_na_candidate_count": blocked_na_candidates,
        "selected_candidate_source_files": "|".join(row["source_file"] for row in deduped if row["candidate_selected"] == "TRUE" and row["eligible_for_v20_96"] == "TRUE") or "NONE",
        "fresh_daily_runner_rerun_required": valid_count == 0,
        "rejected_reasons": "|".join(reasons) if reasons else "NONE",
        "extracted_raw_statuses": "|".join(raw_statuses) if raw_statuses else "NONE",
        "normalized_statuses": "|".join(normalized_statuses) if normalized_statuses else "NONE",
        "missing_sources": [rel(path) for path in missing],
        "found_sources": [rel(path) for path in found],
    }
    return deduped, metrics, PASS_STATUS if valid_count > 0 else WARN_STATUS


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, status: str, metrics: dict[str, object]) -> None:
    lines = [
        "# V20.97 Daily Runner Observation Bridge Repair",
        "",
        "## Source Scan",
        f"- final_status: {status}",
        f"- source_files_scanned: {metrics.get('source_files_scanned', 0)}",
        f"- source_files_found: {metrics.get('source_files_found', 0)}",
        f"- source_files_missing_warn: {metrics.get('source_files_missing', 0)}",
        "",
        "## Normalized Observation Counts",
        f"- normalized_observation_row_count: {metrics.get('normalized_observation_row_count', 0)}",
        f"- canonical_observation_row_count: {metrics.get('canonical_observation_row_count', 0)}",
        f"- valid_observation_row_count: {metrics.get('valid_observation_row_count', 0)}",
        f"- invalid_observation_row_count: {metrics.get('invalid_observation_row_count', 0)}",
        f"- duplicate_count: {metrics.get('duplicate_count', 0)}",
        f"- eligible_for_v20_96_count: {metrics.get('eligible_for_v20_96_count', 0)}",
        f"- valid_research_observation_rows: {metrics.get('valid_research_observation_rows', 0)}",
        f"- eligible_for_v20_96_research_only: {metrics.get('eligible_for_v20_96_research_only', 0)}",
        f"- eligible_for_official_promotion: {metrics.get('eligible_for_official_promotion', 0)}",
        f"- pass_candidate_count: {metrics.get('pass_candidate_count', 0)}",
        f"- warn_candidate_count: {metrics.get('warn_candidate_count', 0)}",
        f"- blocked_na_candidate_count: {metrics.get('blocked_na_candidate_count', 0)}",
        f"- selected_candidate_source_files: {metrics.get('selected_candidate_source_files', 'NONE')}",
        "",
        "## Rejection Reasons",
        f"- rejected_reasons: {metrics.get('rejected_reasons', 'NONE')}",
        f"- promotion_blocked_reason: {current_lane_context().get('promotion_blocked_reason', 'NONE')}",
        f"- extracted_raw_statuses: {metrics.get('extracted_raw_statuses', 'NONE')}",
        f"- normalized_statuses: {metrics.get('normalized_statuses', 'NONE')}",
        f"- FRESH_DAILY_RUNNER_RERUN_REQUIRED: {tf(bool(metrics.get('fresh_daily_runner_rerun_required')))}",
        "",
        "## Safety Confirmation",
        "- research_only: TRUE",
        "- promotion_allowed: FALSE",
        "- official_recommendation_created: FALSE",
        "- official_weight_mutated: FALSE",
        "- trade_action_created: FALSE",
        "",
        "## Recommended Next Stage",
        "- rerun V20.96 after V20.97 if valid rows > 0",
        "- rerun V20.55 daily one-click research runner if valid rows remain 0",
        "- rerun V20.97 after V20.55",
        "- rerun V20.96 after V20.97",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    rows, metrics, status = build_bridge_rows()
    write_csv(DETAIL, rows)
    write_summary(SUMMARY, status, metrics)
    shutil.copyfile(DETAIL, DETAIL_ALIAS)
    shutil.copyfile(SUMMARY, SUMMARY_ALIAS)
    shutil.copyfile(DETAIL, BRIDGE)
    shutil.copyfile(DETAIL, BRIDGE_ALIAS)
    print(status)
    for key in [
        "source_files_scanned",
        "source_files_found",
        "source_files_missing",
        "normalized_observation_row_count",
        "canonical_observation_row_count",
        "valid_observation_row_count",
        "invalid_observation_row_count",
        "duplicate_count",
        "eligible_for_v20_96_count",
        "valid_research_observation_rows",
        "eligible_for_v20_96_research_only",
        "eligible_for_official_promotion",
        "pass_candidate_count",
        "warn_candidate_count",
        "blocked_na_candidate_count",
        "selected_candidate_source_files",
        "fresh_daily_runner_rerun_required",
        "rejected_reasons",
        "extracted_raw_statuses",
        "normalized_statuses",
    ]:
        print(f"{key.upper()}={metrics.get(key, 0)}")
    print("RESEARCH_ONLY=TRUE")
    print("PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("OFFICIAL_WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    return 1 if status == BLOCKED_STATUS else 0


if __name__ == "__main__":
    raise SystemExit(main())
