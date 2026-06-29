#!/usr/bin/env python
"""V21.049-R1 repaired-context maturity evaluator scaffold.

Research-only evaluation of the V21.048-R1 repaired context ledger. This stage
does not create returns, adopt a shadow policy, or mutate official artifacts.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.049-R1_REPAIRED_CONTEXT_MATURITY_EVALUATOR_SCAFFOLD"
PASS_STATUS = "PASS_V21_049_R1_REPAIRED_CONTEXT_MATURITY_EVALUATED"
PENDING_STATUS = "PARTIAL_PASS_V21_049_R1_REPAIRED_CONTEXT_EVALUATOR_READY_PENDING_MATURITY"
INSUFFICIENT_STATUS = "PARTIAL_PASS_V21_049_R1_MATURED_DATA_INSUFFICIENT_FOR_ALPHA_INTERPRETATION"
INVALID_STATUS = "BLOCKED_V21_049_R1_INPUT_MISSING_OR_INVALID"
DUPLICATE_STATUS = "BLOCKED_V21_049_R1_DUPLICATE_OBSERVATION_IDS"
COLUMNS_STATUS = "BLOCKED_V21_049_R1_REQUIRED_COLUMNS_MISSING"

MIN_MATURED_TOTAL = 100
MIN_MATURED_PER_CONTEXT = 20
MAX_PRICE_MISSING_RATIO = 0.05

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "source_repaired_ledger_path",
    "source_row_count", "distinct_repaired_observation_id_count",
    "duplicate_repaired_observation_id_count", "distinct_ticker_count",
    "repaired_context_count", "forward_return_window_count",
    "matured_row_count", "pending_row_count", "price_missing_count",
    "realized_return_available", "context_selectivity_gate_pass_from_v21_048",
    "alpha_interpretation_allowed", "shadow_review_allowed",
    "shadow_adoption_allowed", "official_use_allowed",
    "broker_execution_allowed", "trade_action_allowed", "research_only",
    "next_maturity_check_date", "created_at_utc",
]

BY_CONTEXT_FIELDS = [
    "repaired_context_label", "row_count", "matured_row_count",
    "pending_row_count", "price_missing_count", "mean_realized_forward_return",
    "median_realized_forward_return", "hit_rate", "positive_count",
    "negative_count", "zero_count", "distinct_ticker_count",
    "distinct_as_of_date_count", "distinct_lane_count", "distinct_window_count",
]

BY_WINDOW_FIELDS = [
    "forward_return_window", "row_count", "matured_row_count",
    "pending_row_count", "price_missing_count", "mean_realized_forward_return",
    "median_realized_forward_return", "hit_rate", "distinct_context_count",
    "distinct_ticker_count",
]

ID_FIELDS = ("repaired_observation_id", "observation_id")
CONTEXT_FIELDS = ("repaired_context_label", "context_label", "context_key")
WINDOW_FIELDS = ("forward_return_window", "forward_window")
MATURITY_DATE_FIELDS = ("scheduled_maturity_date", "maturity_date", "expected_maturity_date")
RETURN_FIELDS = ("realized_forward_return", "forward_return", "realized_return")


def clean(value: object) -> str:
    return str(value or "").strip()


def norm(value: object) -> str:
    return clean(value).upper()


def yes(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def fnum(value: object) -> float | None:
    try:
        result = float(clean(value))
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def parse_date(value: object) -> date | None:
    try:
        return date.fromisoformat(clean(value)[:10])
    except ValueError:
        return None


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


def first_field(fields: list[str], candidates: tuple[str, ...]) -> str:
    return next((field for field in candidates if field in fields), "")


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def discover_source(root: Path) -> Path | None:
    preferred = root / "outputs/v21/context/V21_048_R1_REPAIRED_CONTEXT_OBSERVATION_LEDGER.csv"
    if preferred.exists():
        return preferred
    candidates = [
        path for path in (root / "outputs/v21").rglob("*.csv")
        if "REPAIRED_CONTEXT_OBSERVATION_LEDGER" in path.name.upper()
        and "V21_049" not in path.name.upper()
    ]
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def schedule_map(root: Path) -> dict[tuple[str, str], str]:
    candidates = [
        root / "outputs/v21/ledger/V21_044_R8_R1_TECHNICAL_ONLY_OBSERVATION_LEDGER_REFRESHED_WITH_REPAIR.csv",
        root / "outputs/v21/ledger/V21_044_R8_TECHNICAL_ONLY_OBSERVATION_LEDGER_REFRESHED.csv",
        root / "outputs/v21/ledger/V21_044_R7_TECHNICAL_ONLY_OBSERVATION_LEDGER.csv",
    ]
    result: dict[tuple[str, str], str] = {}
    for path in candidates:
        rows, _ = read_csv(path)
        for row in rows:
            as_of = clean(row.get("observation_as_of_date") or row.get("as_of_date"))[:10]
            window = norm(row.get("forward_window") or row.get("forward_return_window"))
            maturity = clean(row.get("scheduled_maturity_date") or row.get("maturity_date"))[:10]
            if as_of and window and maturity:
                result.setdefault((as_of, window), maturity)
        if result:
            break
    return result


def fallback_maturity_date(as_of: date, window: str) -> str:
    """Conservative weekday-only fallback when no local schedule is available."""
    digits = "".join(character for character in norm(window) if character.isdigit())
    if not digits:
        return ""
    sessions = int(digits)
    current = as_of
    counted = 0
    while counted < sessions:
        current += timedelta(days=1)
        if current.weekday() < 5:
            counted += 1
    return current.isoformat()


def exact_deduplicate(
    rows: list[dict[str, str]], id_field: str
) -> tuple[list[dict[str, str]], int, int]:
    by_id: dict[str, dict[str, str]] = {}
    exact_duplicate_count = 0
    conflicting_duplicate_count = 0
    for row in rows:
        observation_id = clean(row.get(id_field))
        if observation_id not in by_id:
            by_id[observation_id] = row
        elif by_id[observation_id] == row:
            exact_duplicate_count += 1
        else:
            conflicting_duplicate_count += 1
    return list(by_id.values()), exact_duplicate_count, conflicting_duplicate_count


def status_is_matured(value: object) -> bool:
    status = norm(value)
    return status.startswith("MATURED") and "NOT_MATURED" not in status


def status_is_price_missing(value: object) -> bool:
    status = norm(value)
    return "PRICE_MISSING" in status or "MISSING_PRICE" in status


def row_value(row: dict[str, str], fields: tuple[str, ...]) -> str:
    return next((clean(row.get(field)) for field in fields if clean(row.get(field))), "")


def classify_rows(
    rows: list[dict[str, str]],
    fields: list[str],
    schedules: dict[tuple[str, str], str],
    today: date,
) -> tuple[list[dict[str, object]], str]:
    context_field = first_field(fields, CONTEXT_FIELDS)
    window_field = first_field(fields, WINDOW_FIELDS)
    maturity_field = first_field(fields, MATURITY_DATE_FIELDS)
    classified: list[dict[str, object]] = []
    maturity_dates: list[str] = []
    for source in rows:
        row = dict(source)
        as_of_text = clean(row.get("as_of_date"))[:10]
        window = norm(row.get(window_field))
        maturity_text = clean(row.get(maturity_field))[:10] if maturity_field else ""
        if not maturity_text:
            maturity_text = schedules.get((as_of_text, window), "")
        if not maturity_text and parse_date(as_of_text):
            maturity_text = fallback_maturity_date(parse_date(as_of_text), window)
        maturity = parse_date(maturity_text)
        realized = fnum(row_value(row, RETURN_FIELDS))
        explicit_matured = status_is_matured(row.get("maturity_status") or row.get("observation_status"))
        explicit_missing = (
            norm(row.get("price_missing")) == "TRUE"
            or status_is_price_missing(row.get("maturity_status"))
            or status_is_price_missing(row.get("observation_status"))
        )
        due = bool(maturity and maturity <= today)
        matured = realized is not None or (
            explicit_matured
            and not explicit_missing
            and norm(row.get("forward_price_available")) != "FALSE"
        )
        price_missing = not matured and (explicit_missing or (due and norm(row.get("forward_price_available")) == "FALSE"))
        pending = not matured and not price_missing
        if pending and maturity and maturity > today:
            maturity_dates.append(maturity.isoformat())
        row["_context"] = clean(row.get(context_field))
        row["_window"] = clean(row.get(window_field))
        row["_maturity_date"] = maturity_text
        row["_realized"] = realized
        row["_matured"] = matured
        row["_pending"] = pending
        row["_price_missing"] = price_missing
        classified.append(row)
    return classified, min(maturity_dates, default="")


def metrics(items: list[dict[str, object]]) -> dict[str, object]:
    returns = [float(row["_realized"]) for row in items if row["_matured"] and row["_realized"] is not None]
    positives = sum(value > 0 for value in returns)
    negatives = sum(value < 0 for value in returns)
    zeros = sum(value == 0 for value in returns)
    return {
        "row_count": len(items),
        "matured_row_count": len(returns),
        "pending_row_count": sum(bool(row["_pending"]) for row in items),
        "price_missing_count": sum(bool(row["_price_missing"]) for row in items),
        "mean_realized_forward_return": f"{statistics.mean(returns):.10f}" if returns else "",
        "median_realized_forward_return": f"{statistics.median(returns):.10f}" if returns else "",
        "hit_rate": f"{positives / len(returns):.10f}" if returns else "",
        "positive_count": positives,
        "negative_count": negatives,
        "zero_count": zeros,
    }


def aggregate_context(classified: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in classified:
        groups[str(row["_context"])].append(row)
    output = []
    for context, items in sorted(groups.items()):
        output.append({
            "repaired_context_label": context,
            **metrics(items),
            "distinct_ticker_count": len({clean(row.get("ticker")) for row in items}),
            "distinct_as_of_date_count": len({clean(row.get("as_of_date"))[:10] for row in items}),
            "distinct_lane_count": len({clean(row.get("lane_id")) for row in items}),
            "distinct_window_count": len({str(row["_window"]) for row in items}),
        })
    return output


def aggregate_window(classified: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in classified:
        groups[str(row["_window"])].append(row)
    output = []
    for window, items in sorted(groups.items()):
        values = metrics(items)
        output.append({
            "forward_return_window": window,
            **{key: values[key] for key in (
                "row_count", "matured_row_count", "pending_row_count",
                "price_missing_count", "mean_realized_forward_return",
                "median_realized_forward_return", "hit_rate",
            )},
            "distinct_context_count": len({str(row["_context"]) for row in items}),
            "distinct_ticker_count": len({clean(row.get("ticker")) for row in items}),
        })
    return output


def evaluate(
    rows: list[dict[str, str]],
    fields: list[str],
    source_path: str,
    selectivity_pass: bool,
    schedules: dict[tuple[str, str], str] | None = None,
    today: date | None = None,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    schedules = schedules or {}
    today = today or date.today()
    id_field = first_field(fields, ID_FIELDS)
    context_field = first_field(fields, CONTEXT_FIELDS)
    window_field = first_field(fields, WINDOW_FIELDS)
    required = {"as_of_date", "ticker", "lane_id"}
    inputs_valid = bool(rows and id_field)
    required_valid = required.issubset(fields) and bool(context_field and window_field)
    deduped: list[dict[str, str]] = rows
    exact_duplicates = 0
    conflicting_duplicates = 0
    if inputs_valid:
        deduped, exact_duplicates, conflicting_duplicates = exact_deduplicate(rows, id_field)

    derivable_maturity = bool(
        first_field(fields, MATURITY_DATE_FIELDS)
        or schedules
        or all(parse_date(row.get("as_of_date")) for row in rows)
    )
    if required_valid and not derivable_maturity:
        required_valid = False

    classified: list[dict[str, object]] = []
    next_date = ""
    if inputs_valid and required_valid and not conflicting_duplicates:
        classified, next_date = classify_rows(deduped, fields, schedules, today)
    matured_count = sum(bool(row["_matured"]) for row in classified)
    pending_count = sum(bool(row["_pending"]) for row in classified)
    missing_count = sum(bool(row["_price_missing"]) for row in classified)
    by_context = aggregate_context(classified) if matured_count > 0 else []
    by_window = aggregate_window(classified) if matured_count > 0 else []
    missing_ratio = missing_count / len(classified) if classified else 0.0
    context_samples_sufficient = bool(by_context) and all(
        int(row["matured_row_count"]) >= MIN_MATURED_PER_CONTEXT for row in by_context
    )
    alpha_allowed = (
        selectivity_pass
        and matured_count >= MIN_MATURED_TOTAL
        and missing_ratio <= MAX_PRICE_MISSING_RATIO
        and context_samples_sufficient
    )

    if not inputs_valid:
        final_status = INVALID_STATUS
        decision = "BLOCK_REPAIRED_CONTEXT_MATURITY_EVALUATOR_INPUT_MISSING_OR_INVALID"
    elif not required_valid:
        final_status = COLUMNS_STATUS
        decision = "BLOCK_REPAIRED_CONTEXT_MATURITY_EVALUATOR_REQUIRED_COLUMNS_MISSING"
    elif conflicting_duplicates:
        final_status = DUPLICATE_STATUS
        decision = "BLOCK_REPAIRED_CONTEXT_MATURITY_EVALUATOR_CONFLICTING_DUPLICATE_IDS"
    elif matured_count == 0:
        final_status = PENDING_STATUS
        decision = "WAIT_FOR_FORWARD_RETURN_MATURITY"
    elif alpha_allowed:
        final_status = PASS_STATUS
        decision = "REPAIRED_CONTEXT_MATURITY_EVALUATED_RESEARCH_ONLY_ALPHA_REVIEW_AVAILABLE"
    else:
        final_status = INSUFFICIENT_STATUS
        decision = "MATURED_DATA_AVAILABLE_BUT_INSUFFICIENT_FOR_ALPHA_INTERPRETATION"

    duplicate_count = exact_duplicates + conflicting_duplicates
    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "source_repaired_ledger_path": source_path,
        "source_row_count": len(rows),
        "distinct_repaired_observation_id_count": len({
            clean(row.get(id_field)) for row in deduped if id_field and clean(row.get(id_field))
        }),
        "duplicate_repaired_observation_id_count": duplicate_count,
        "distinct_ticker_count": len({clean(row.get("ticker")) for row in deduped if clean(row.get("ticker"))}),
        "repaired_context_count": len({clean(row.get(context_field)) for row in deduped if context_field}),
        "forward_return_window_count": len({clean(row.get(window_field)) for row in deduped if window_field}),
        "matured_row_count": matured_count,
        "pending_row_count": pending_count,
        "price_missing_count": missing_count,
        "realized_return_available": yes(matured_count > 0),
        "context_selectivity_gate_pass_from_v21_048": yes(selectivity_pass),
        "alpha_interpretation_allowed": yes(alpha_allowed),
        "shadow_review_allowed": yes(matured_count > 0 and selectivity_pass),
        "shadow_adoption_allowed": "FALSE",
        "official_use_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "research_only": "TRUE",
        "next_maturity_check_date": next_date,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    return summary, by_context, by_window


def render_report(summary: dict[str, object], by_context: list[dict[str, object]]) -> str:
    sample_warning = (
        "No realized forward returns are available; no alpha statistics were fabricated."
        if int(summary["matured_row_count"]) == 0
        else "Realized returns were summarized, but adoption remains prohibited."
    )
    return f"""# V21.049-R1 Repaired Context Maturity Evaluator Scaffold

## Decision

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- source_repaired_ledger_path: {summary['source_repaired_ledger_path']}
- matured_row_count: {summary['matured_row_count']}
- pending_row_count: {summary['pending_row_count']}
- price_missing_count: {summary['price_missing_count']}
- next_maturity_check_date: {summary['next_maturity_check_date']}

{sample_warning}

## Interpretation Boundary

- context_selectivity_gate_pass_from_v21_048: {summary['context_selectivity_gate_pass_from_v21_048']}
- alpha_interpretation_allowed: {summary['alpha_interpretation_allowed']}
- shadow_review_allowed: {summary['shadow_review_allowed']}
- shadow_adoption_allowed: FALSE
- official_use_allowed: FALSE
- broker_execution_allowed: FALSE
- trade_action_allowed: FALSE

This is a research-only maturity evaluator scaffold, not an adoption stage.
It never authorizes official use, shadow adoption, broker execution, or trade
actions.

## Context Evaluation Rows

- context_summary_row_count: {len(by_context)}
- minimum_matured_rows_total: {MIN_MATURED_TOTAL}
- minimum_matured_rows_per_context: {MIN_MATURED_PER_CONTEXT}
- maximum_price_missing_ratio: {MAX_PRICE_MISSING_RATIO:.2f}
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    source = args.source or discover_source(root)
    rows, fields = read_csv(source) if source else ([], [])
    selectivity = read_first(root / "outputs/v21/context/V21_048_R1_CONTEXT_SELECTIVITY_AUDIT_SUMMARY.csv")
    selectivity_pass = norm(selectivity.get("context_selectivity_gate_pass")) == "TRUE"
    source_path = rel(root, source) if source else "NOT_AVAILABLE"
    summary, by_context, by_window = evaluate(
        rows, fields, source_path, selectivity_pass, schedule_map(root)
    )

    context_dir = root / "outputs/v21/context"
    read_center = root / "outputs/v21/read_center"
    write_csv(
        context_dir / "V21_049_R1_REPAIRED_CONTEXT_MATURITY_EVALUATION_SUMMARY.csv",
        [summary], SUMMARY_FIELDS,
    )
    write_csv(
        context_dir / "V21_049_R1_REPAIRED_CONTEXT_MATURITY_BY_CONTEXT.csv",
        by_context, BY_CONTEXT_FIELDS,
    )
    write_csv(
        context_dir / "V21_049_R1_REPAIRED_CONTEXT_MATURITY_BY_WINDOW.csv",
        by_window, BY_WINDOW_FIELDS,
    )
    report_path = read_center / "V21_049_R1_REPAIRED_CONTEXT_MATURITY_EVALUATOR_SCAFFOLD_REPORT.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(summary, by_context), encoding="utf-8")
    for field in (
        "final_status", "decision", "source_repaired_ledger_path",
        "matured_row_count", "pending_row_count", "price_missing_count",
        "alpha_interpretation_allowed", "shadow_review_allowed",
        "next_maturity_check_date",
    ):
        print(f"{field.upper()}={summary[field]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
