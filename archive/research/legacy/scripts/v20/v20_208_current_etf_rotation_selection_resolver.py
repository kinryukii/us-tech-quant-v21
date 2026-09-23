#!/usr/bin/env python
"""V20.208 current ETF rotation selection resolver.

Scans existing V20 CSV outputs for explicit ETF rotation selections, resolves
the most recent non-conflicting selected_etf, and emits a single current
selection artifact for downstream research-only observation specs.
"""

from __future__ import annotations

import csv
import math
import re
from datetime import date, datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
OUT_DIR = OUTPUTS / "random_weight_backtest"
CONSOLIDATION = OUTPUTS / "consolidation"
READ_CENTER = OUTPUTS / "read_center"

OUT_SCAN = OUT_DIR / "V20_208_ETF_SELECTION_SOURCE_SCAN.csv"
OUT_CANDIDATES = OUT_DIR / "V20_208_ETF_SELECTION_CANDIDATES.csv"
OUT_CONFLICT = OUT_DIR / "V20_208_ETF_SELECTION_CONFLICT_AUDIT.csv"
OUT_FRESHNESS = OUT_DIR / "V20_208_ETF_SELECTION_FRESHNESS_AUDIT.csv"
OUT_SELECTION = CONSOLIDATION / "V20_208_CURRENT_ETF_ROTATION_SELECTION.csv"
OUT_GATE = OUT_DIR / "V20_208_CURRENT_ETF_SELECTION_RESOLUTION_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_208_CURRENT_ETF_ROTATION_SELECTION_RESOLVER_REPORT.md"

MAX_SCAN_BYTES = 8 * 1024 * 1024
VALID_ETFS = {"SPY", "QQQ", "SOXX"}
DATE_FIELDS = ["as_of_date", "decision_date", "run_date", "created_at", "date"]
INDICATORS = ["ETF", "ROTATION", "BENCHMARK", "CURRENT", "SELECTION"]

SCAN_FIELDS = [
    "source_artifact", "exists_non_empty", "row_count", "column_count",
    "has_selected_etf", "has_etf_rotation_signal", "has_date_field",
    "detected_date_field", "min_detected_date", "max_detected_date",
    "scan_status", "warning_reason",
]
CANDIDATE_FIELDS = [
    "candidate_id", "source_artifact", "selected_etf", "etf_rotation_signal",
    "selection_date", "detected_date_field", "source_row_index", "source_priority",
    "freshness_status", "candidate_status", "reason",
]
CONFLICT_FIELDS = [
    "conflict_group", "selection_date", "candidate_count", "selected_etf_values",
    "source_artifacts", "conflict_status", "resolution_action", "reason",
]
FRESHNESS_FIELDS = [
    "selected_candidate_id", "selected_etf", "selection_date", "current_run_date",
    "age_calendar_days", "age_trading_days_if_available", "freshness_status",
    "warning_reason",
]
SELECTION_FIELDS = [
    "current_selected_etf", "etf_rotation_signal", "selection_date",
    "selected_etf_source", "selected_candidate_id", "resolution_status",
    "freshness_status", "conflict_status",
    "current_observation_condition_for_v20_207",
    "observation_allowed_if_rule_v20_206_applied", "non_spy_edge_disabled",
    "reason", "created_at",
]
GATE_FIELDS = [
    "final_status", "current_selected_etf", "selection_date", "resolution_status",
    "freshness_status", "conflict_status",
    "current_observation_allowed_under_v20_206_rule", "non_spy_edge_disabled",
    "source_scan_count", "valid_candidate_count", "conflict_count", "research_only",
    "official_weight_mutated", "official_recommendation_created",
    "real_book_signal_created", "broker_execution_supported", "trade_action_created",
    "shadow_weight_change_recommended", "next_stage_allowed", "reason",
    "next_recommended_action",
]

PASS_SPY = "PASS_V20_208_CURRENT_ETF_SELECTION_RESOLVED_SPY"
PASS_NON_SPY = "PASS_V20_208_CURRENT_ETF_SELECTION_RESOLVED_NON_SPY"
PARTIAL_UNKNOWN = "PARTIAL_PASS_V20_208_CURRENT_ETF_SELECTION_UNKNOWN"
BLOCKED_CONFLICT = "BLOCKED_V20_208_CONFLICTING_CURRENT_ETF_SELECTIONS"
BLOCKED_EXECUTION = "BLOCKED_V20_208_RESOLVER_EXECUTION_FAILED"


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def read_rows(path: Path, limit: int | None = None) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists() or path.stat().st_size == 0:
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = []
        for idx, row in enumerate(reader):
            if limit is not None and idx >= limit:
                break
            rows.append({k: clean(v) for k, v in row.items()})
    return fields, rows


def parse_date(value: object) -> str:
    text = clean(value)
    if not text:
        return ""
    match = re.search(r"(20\d{2})[-_/]?(\d{2})[-_/]?(\d{2})", text)
    if not match:
        return ""
    yyyy, mm, dd = match.groups()
    try:
        return date(int(yyyy), int(mm), int(dd)).isoformat()
    except ValueError:
        return ""


def priority(path: Path) -> int:
    p = rel(path).upper()
    name = path.name.upper()
    if p.startswith("outputs/v20/consolidation/") and "CURRENT" in name and "ETF" in name and "SELECTION" in name:
        return 1
    if p.startswith("outputs/v20/consolidation/") and "ETF" in name and "ROTATION" in name:
        return 2
    if p.startswith("outputs/v20/random_weight_backtest/") and "ETF" in name and "BENCHMARK" in name:
        return 3
    if p.startswith("outputs/v20/random_weight_backtest/") and "SELECTED_ETF" in name:
        return 4
    return 5


def allows_metadata_date_candidate(path: Path) -> bool:
    name = path.name.upper()
    p = rel(path).upper()
    return "CURRENT" in name and ("ETF" in name or "ROTATION" in name or p.startswith("OUTPUTS/V20/CONSOLIDATION/"))


def aggregate_selected_etf_source(path: Path, fields: list[str]) -> bool:
    name = path.name.upper()
    lower_fields = {field.lower() for field in fields}
    aggregate_markers = ["EFFECTIVENESS", "CONTRIBUTION", "BIAS", "DIAGNOSTICS", "AUDIT", "GATE", "REGISTRY"]
    if any(marker in name for marker in aggregate_markers) and "etf_rotation_signal" not in lower_fields:
        return True
    if name.startswith(("V20_205_", "V20_206_", "V20_207_")) and "etf_rotation_signal" not in lower_fields:
        return True
    return False


def candidate_file(path: Path, fields: list[str]) -> bool:
    upper_name = path.name.upper()
    field_set = {field.lower() for field in fields}
    return (
        any(indicator in upper_name for indicator in INDICATORS)
        or "selected_etf" in field_set
        or "etf_rotation_signal" in field_set
    )


def detected_date_field(fields: list[str]) -> str:
    lower = {field.lower(): field for field in fields}
    for preferred in DATE_FIELDS:
        if preferred in lower:
            return lower[preferred]
    return ""


def freshness(selection_date: str, run_date: date) -> tuple[str, str, str]:
    if not selection_date:
        return "UNKNOWN_DATE_WARN", "", "No reliable selection date available."
    try:
        selected = date.fromisoformat(selection_date)
    except ValueError:
        return "UNKNOWN_DATE_WARN", "", "Selection date could not be parsed."
    age = (run_date - selected).days
    if age <= 3:
        return "FRESH", str(age), ""
    return "STALE_WARN", str(age), "Selection date is older than 3 calendar days but is the most recent available."


def discover() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    scan_rows: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    candidate_seq = 1
    run_date = datetime.now(timezone.utc).date()
    for path in sorted(OUTPUTS.rglob("*.csv")):
        if path.name.startswith("V20_208_"):
            continue
        rel_path = rel(path)
        exists = path.exists() and path.stat().st_size > 0
        if not exists:
            scan_rows.append({
                "source_artifact": rel_path, "exists_non_empty": "FALSE", "row_count": "0",
                "column_count": "0", "has_selected_etf": "FALSE",
                "has_etf_rotation_signal": "FALSE", "has_date_field": "FALSE",
                "detected_date_field": "", "scan_status": "MISSING_OR_EMPTY",
                "warning_reason": "File missing or empty.",
            })
            continue
        if path.stat().st_size > MAX_SCAN_BYTES:
            scan_rows.append({
                "source_artifact": rel_path, "exists_non_empty": "TRUE", "row_count": "",
                "column_count": "", "has_selected_etf": "FALSE",
                "has_etf_rotation_signal": "FALSE", "has_date_field": "FALSE",
                "detected_date_field": "", "scan_status": "SKIPPED_TOO_LARGE",
                "warning_reason": f"File larger than scan cap {MAX_SCAN_BYTES} bytes.",
            })
            continue
        fields, rows = read_rows(path)
        if not candidate_file(path, fields):
            continue
        lower_fields = {field.lower() for field in fields}
        date_field = detected_date_field(fields)
        dates = [parse_date(row.get(date_field)) for row in rows if date_field]
        dates = [d for d in dates if d]
        has_selected = "selected_etf" in lower_fields
        has_signal = "etf_rotation_signal" in lower_fields
        scan_rows.append({
            "source_artifact": rel_path,
            "exists_non_empty": "TRUE",
            "row_count": str(len(rows)),
            "column_count": str(len(fields)),
            "has_selected_etf": "TRUE" if has_selected else "FALSE",
            "has_etf_rotation_signal": "TRUE" if has_signal else "FALSE",
            "has_date_field": "TRUE" if bool(date_field) else "FALSE",
            "detected_date_field": date_field,
            "min_detected_date": min(dates) if dates else "",
            "max_detected_date": max(dates) if dates else "",
            "scan_status": "SCANNED",
            "warning_reason": "" if has_selected else "No selected_etf column; source scan only.",
        })
        if not has_selected:
            continue
        aggregate_source = aggregate_selected_etf_source(path, fields)
        for idx, row in enumerate(rows, start=1):
            selected_etf = clean(row.get("selected_etf")).upper()
            if selected_etf not in VALID_ETFS:
                continue
            selection_date = parse_date(row.get(date_field)) if date_field else ""
            date_source = date_field
            if not selection_date:
                if aggregate_source or not allows_metadata_date_candidate(path):
                    candidates.append({
                        "candidate_id": f"V20_208_CANDIDATE_{candidate_seq:04d}",
                        "source_artifact": rel_path,
                        "selected_etf": selected_etf,
                        "etf_rotation_signal": clean(row.get("etf_rotation_signal")),
                        "selection_date": "",
                        "detected_date_field": "",
                        "source_row_index": str(idx),
                        "source_priority": str(priority(path)),
                        "freshness_status": "UNKNOWN_DATE_WARN",
                        "candidate_status": "INVALID",
                        "reason": "selected_etf appears in an aggregate or undated diagnostic source, not an explicit current/dated ETF rotation selection.",
                    })
                    candidate_seq += 1
                    continue
                selection_date = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).date().isoformat()
                date_source = "file_modified_date"
            fresh_status, _age, warning = freshness(selection_date, run_date)
            metadata_note = " Date derived from file modified timestamp." if date_source == "file_modified_date" else ""
            candidates.append({
                "candidate_id": f"V20_208_CANDIDATE_{candidate_seq:04d}",
                "source_artifact": rel_path,
                "selected_etf": selected_etf,
                "etf_rotation_signal": clean(row.get("etf_rotation_signal")),
                "selection_date": selection_date,
                "detected_date_field": date_source,
                "source_row_index": str(idx),
                "source_priority": str(priority(path)),
                "freshness_status": fresh_status if date_source != "file_modified_date" else f"{fresh_status}_METADATA_DERIVED",
                "candidate_status": "VALID",
                "reason": ("Explicit selected_etf candidate." + metadata_note + (" " + warning if warning else "")).strip(),
            })
            candidate_seq += 1
    return scan_rows, candidates


def resolve(candidates: list[dict[str, object]]) -> tuple[dict[str, object] | None, list[dict[str, object]], str, str]:
    valid = [row for row in candidates if row.get("candidate_status") == "VALID"]
    if not valid:
        return None, [{
            "conflict_group": "NO_VALID_CANDIDATE",
            "selection_date": "",
            "candidate_count": "0",
            "selected_etf_values": "",
            "source_artifacts": "",
            "conflict_status": "NO_CONFLICT",
            "resolution_action": "EMIT_UNKNOWN",
            "reason": "No explicit selected_etf candidate found.",
        }], "NO_CONFLICT", ""
    latest = max(clean(row["selection_date"]) for row in valid)
    latest_rows = [row for row in valid if row["selection_date"] == latest]
    values = sorted({clean(row["selected_etf"]) for row in latest_rows})
    if len(values) > 1:
        conflict = {
            "conflict_group": "LATEST_SELECTION_DATE",
            "selection_date": latest,
            "candidate_count": str(len(latest_rows)),
            "selected_etf_values": ";".join(values),
            "source_artifacts": ";".join(sorted({clean(row["source_artifact"]) for row in latest_rows})),
            "conflict_status": "CONFLICT",
            "resolution_action": "BLOCK_RESOLUTION",
            "reason": "Multiple latest fresh/current candidates disagree on selected_etf.",
        }
        return None, [conflict], "CONFLICT", latest
    chosen = sorted(latest_rows, key=lambda row: (int(row["source_priority"]), clean(row["source_artifact"]), int(row["source_row_index"])))[0]
    audit = {
        "conflict_group": "LATEST_SELECTION_DATE",
        "selection_date": latest,
        "candidate_count": str(len(latest_rows)),
        "selected_etf_values": values[0],
        "source_artifacts": ";".join(sorted({clean(row["source_artifact"]) for row in latest_rows})),
        "conflict_status": "NO_CONFLICT",
        "resolution_action": "SELECT_HIGHEST_PRIORITY_SOURCE",
        "reason": "Latest candidates agree on selected_etf; highest-priority source selected.",
    }
    return chosen, [audit], "NO_CONFLICT", latest


def freshness_row(chosen: dict[str, object] | None) -> dict[str, object]:
    run_date = datetime.now(timezone.utc).date()
    if not chosen:
        return {
            "selected_candidate_id": "",
            "selected_etf": "UNKNOWN",
            "selection_date": "",
            "current_run_date": run_date.isoformat(),
            "age_calendar_days": "",
            "age_trading_days_if_available": "",
            "freshness_status": "UNKNOWN_DATE_WARN",
            "warning_reason": "No selected candidate.",
        }
    status, age, warning = freshness(clean(chosen.get("selection_date")), run_date)
    if clean(chosen.get("detected_date_field")) == "file_modified_date":
        status = f"{status}_METADATA_DERIVED"
        warning = (warning + " " if warning else "") + "Selection date is metadata-derived."
    return {
        "selected_candidate_id": chosen.get("candidate_id", ""),
        "selected_etf": chosen.get("selected_etf", ""),
        "selection_date": chosen.get("selection_date", ""),
        "current_run_date": run_date.isoformat(),
        "age_calendar_days": age,
        "age_trading_days_if_available": "",
        "freshness_status": status,
        "warning_reason": warning,
    }


def selection_row(chosen: dict[str, object] | None, conflict_status: str, fresh: dict[str, object]) -> dict[str, object]:
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if conflict_status == "CONFLICT":
        return {
            "current_selected_etf": "CONFLICT",
            "etf_rotation_signal": "",
            "selection_date": fresh.get("selection_date", ""),
            "selected_etf_source": "",
            "selected_candidate_id": "",
            "resolution_status": "CONFLICT",
            "freshness_status": fresh.get("freshness_status", ""),
            "conflict_status": "CONFLICT",
            "current_observation_condition_for_v20_207": "CONFLICT",
            "observation_allowed_if_rule_v20_206_applied": "FALSE",
            "non_spy_edge_disabled": "TRUE",
            "reason": "Conflicting latest selected_etf candidates.",
            "created_at": created,
        }
    if not chosen:
        return {
            "current_selected_etf": "UNKNOWN",
            "etf_rotation_signal": "",
            "selection_date": "",
            "selected_etf_source": "",
            "selected_candidate_id": "",
            "resolution_status": "UNKNOWN",
            "freshness_status": fresh.get("freshness_status", ""),
            "conflict_status": "NO_CONFLICT",
            "current_observation_condition_for_v20_207": "UNKNOWN",
            "observation_allowed_if_rule_v20_206_applied": "FALSE",
            "non_spy_edge_disabled": "TRUE",
            "reason": "No valid current ETF rotation selection candidate found.",
            "created_at": created,
        }
    selected = clean(chosen["selected_etf"])
    is_spy = selected == "SPY"
    return {
        "current_selected_etf": selected,
        "etf_rotation_signal": chosen.get("etf_rotation_signal", ""),
        "selection_date": chosen.get("selection_date", ""),
        "selected_etf_source": chosen.get("source_artifact", ""),
        "selected_candidate_id": chosen.get("candidate_id", ""),
        "resolution_status": "RESOLVED",
        "freshness_status": fresh.get("freshness_status", ""),
        "conflict_status": "NO_CONFLICT",
        "current_observation_condition_for_v20_207": "SELECTED_ETF_EQ_SPY" if is_spy else "SELECTED_ETF_NOT_SPY",
        "observation_allowed_if_rule_v20_206_applied": "TRUE" if is_spy else "FALSE",
        "non_spy_edge_disabled": "FALSE" if is_spy else "TRUE",
        "reason": "Resolved from latest explicit selected_etf candidate.",
        "created_at": created,
    }


def gate_row(selection: dict[str, object], scan_count: int, valid_count: int, conflict_count: int) -> dict[str, object]:
    selected = clean(selection.get("current_selected_etf"))
    resolution = clean(selection.get("resolution_status"))
    if resolution == "CONFLICT":
        final_status = BLOCKED_CONFLICT
        next_allowed = "FALSE"
        reason = "Latest valid selected_etf candidates conflict."
    elif selected == "UNKNOWN":
        final_status = PARTIAL_UNKNOWN
        next_allowed = "TRUE"
        reason = "No valid current selected_etf candidate could be uniquely inferred."
    elif selected == "SPY":
        final_status = PASS_SPY
        next_allowed = "TRUE"
        reason = "Current ETF rotation selection resolved to SPY."
    else:
        final_status = PASS_NON_SPY
        next_allowed = "TRUE"
        reason = f"Current ETF rotation selection resolved to non-SPY ETF {selected}."
    return {
        "final_status": final_status,
        "current_selected_etf": selected,
        "selection_date": selection.get("selection_date", ""),
        "resolution_status": resolution,
        "freshness_status": selection.get("freshness_status", ""),
        "conflict_status": selection.get("conflict_status", ""),
        "current_observation_allowed_under_v20_206_rule": selection.get("observation_allowed_if_rule_v20_206_applied", "FALSE"),
        "non_spy_edge_disabled": selection.get("non_spy_edge_disabled", "TRUE"),
        "source_scan_count": str(scan_count),
        "valid_candidate_count": str(valid_count),
        "conflict_count": str(conflict_count),
        "research_only": "TRUE",
        "official_weight_mutated": "FALSE",
        "official_recommendation_created": "FALSE",
        "real_book_signal_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "trade_action_created": "FALSE",
        "shadow_weight_change_recommended": "FALSE",
        "next_stage_allowed": next_allowed,
        "reason": reason,
        "next_recommended_action": "Feed V20_208_CURRENT_ETF_ROTATION_SELECTION.csv into the next research-only daily report observation integration stage.",
    }


def write_report(gate: dict[str, object], scan_rows: list[dict[str, object]], candidates: list[dict[str, object]], conflict_rows: list[dict[str, object]], selection: dict[str, object]) -> None:
    READ_CENTER.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.208 Current ETF Rotation Selection Resolver Report",
        "",
        f"- Final status: {gate.get('final_status', '')}",
        "- V20.208 was needed because V20.207 refused to fabricate current selected_etf and emitted CURRENT_SELECTED_ETF=UNKNOWN.",
        f"- Source scan count: {len(scan_rows)}",
        f"- Valid selected_etf candidate count: {len([row for row in candidates if row.get('candidate_status') == 'VALID'])}",
        f"- Current selected_etf resolution: {selection.get('current_selected_etf', '')}",
        f"- Selection date: {selection.get('selection_date', '')}",
        f"- Selected source: {selection.get('selected_etf_source', '')}",
        f"- Freshness status: {selection.get('freshness_status', '')}",
        f"- Conflict status: {selection.get('conflict_status', '')}",
        f"- Conflict audit result: {conflict_rows[0].get('conflict_status', '') if conflict_rows else ''}",
        f"- V20.206 SPY condition currently satisfied: {'TRUE' if selection.get('current_selected_etf') == 'SPY' and selection.get('resolution_status') == 'RESOLVED' and selection.get('conflict_status') == 'NO_CONFLICT' else 'FALSE'}",
        f"- Current observation allowed under V20.206 rule: {selection.get('observation_allowed_if_rule_v20_206_applied', '')}",
        f"- Next recommended stage: {gate.get('next_recommended_action', '')}",
        "",
        "Safety statement:",
        "- official weights were not changed",
        "- no official recommendation was created",
        "- no real-book signal was created",
        "- no broker execution was created",
        "- no trade action was created",
        "- no shadow weight change was recommended",
        "- existing daily reports were not overwritten",
    ]
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def blocked_outputs(reason: str) -> int:
    selection = {
        "current_selected_etf": "UNKNOWN",
        "selection_date": "",
        "resolution_status": "UNKNOWN",
        "freshness_status": "UNKNOWN_DATE_WARN",
        "conflict_status": "NO_CONFLICT",
        "observation_allowed_if_rule_v20_206_applied": "FALSE",
        "non_spy_edge_disabled": "TRUE",
    }
    gate = {
        "final_status": BLOCKED_EXECUTION,
        "current_selected_etf": "UNKNOWN",
        "selection_date": "",
        "resolution_status": "UNKNOWN",
        "freshness_status": "UNKNOWN_DATE_WARN",
        "conflict_status": "NO_CONFLICT",
        "current_observation_allowed_under_v20_206_rule": "FALSE",
        "non_spy_edge_disabled": "TRUE",
        "source_scan_count": "0",
        "valid_candidate_count": "0",
        "conflict_count": "0",
        "research_only": "TRUE",
        "official_weight_mutated": "FALSE",
        "official_recommendation_created": "FALSE",
        "real_book_signal_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "trade_action_created": "FALSE",
        "shadow_weight_change_recommended": "FALSE",
        "next_stage_allowed": "FALSE",
        "reason": reason,
        "next_recommended_action": "Repair resolver execution before consuming current ETF selection.",
    }
    write_csv(OUT_SCAN, SCAN_FIELDS, [])
    write_csv(OUT_CANDIDATES, CANDIDATE_FIELDS, [])
    write_csv(OUT_CONFLICT, CONFLICT_FIELDS, [])
    write_csv(OUT_FRESHNESS, FRESHNESS_FIELDS, [])
    write_csv(OUT_SELECTION, SELECTION_FIELDS, [selection])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate, [], [], [], selection)
    print(f"FINAL_STATUS={BLOCKED_EXECUTION}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_WEIGHT_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_SIGNAL_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("SHADOW_WEIGHT_CHANGE_RECOMMENDED=FALSE")
    return 0


def main() -> int:
    try:
        scan_rows, candidates = discover()
        chosen, conflict_rows, conflict_status, _latest = resolve(candidates)
        conflict_count = sum(1 for row in conflict_rows if row.get("conflict_status") == "CONFLICT")
        fresh = freshness_row(chosen)
        selection = selection_row(chosen, conflict_status, fresh)
        if conflict_status == "CONFLICT":
            selection["selection_date"] = conflict_rows[0].get("selection_date", "")
            fresh["selection_date"] = conflict_rows[0].get("selection_date", "")
        gate = gate_row(selection, len(scan_rows), len([row for row in candidates if row.get("candidate_status") == "VALID"]), conflict_count)
        write_csv(OUT_SCAN, SCAN_FIELDS, scan_rows)
        write_csv(OUT_CANDIDATES, CANDIDATE_FIELDS, candidates)
        write_csv(OUT_CONFLICT, CONFLICT_FIELDS, conflict_rows)
        write_csv(OUT_FRESHNESS, FRESHNESS_FIELDS, [fresh])
        write_csv(OUT_SELECTION, SELECTION_FIELDS, [selection])
        write_csv(OUT_GATE, GATE_FIELDS, [gate])
        write_report(gate, scan_rows, candidates, conflict_rows, selection)
        print(f"FINAL_STATUS={gate['final_status']}")
        print(f"CURRENT_SELECTED_ETF={gate['current_selected_etf']}")
        print(f"RESOLUTION_STATUS={gate['resolution_status']}")
        print(f"CURRENT_OBSERVATION_ALLOWED_UNDER_V20_206_RULE={gate['current_observation_allowed_under_v20_206_rule']}")
        print("RESEARCH_ONLY=TRUE")
        print("OFFICIAL_WEIGHT_MUTATED=FALSE")
        print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
        print("REAL_BOOK_SIGNAL_CREATED=FALSE")
        print("BROKER_EXECUTION_SUPPORTED=FALSE")
        print("TRADE_ACTION_CREATED=FALSE")
        print("SHADOW_WEIGHT_CHANGE_RECOMMENDED=FALSE")
        return 0
    except Exception as exc:  # pragma: no cover - guarded final status path
        return blocked_outputs(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
