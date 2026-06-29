#!/usr/bin/env python
"""Research-only wait gate after V21.044-R8-R1 repaired entry-price binding."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path


STAGE = "V21.044-R8A_WAIT_UNTIL_FIRST_MATURITY_DATE"
FINAL_STATUS = "PARTIAL_PASS_V21_044_R8A_WAITING_FOR_FIRST_MATURITY_DATE"
FINAL_DECISION = "WAIT_UNTIL_2026_06_24_BEFORE_R8_RERUN_OR_R9"
BLOCKED_STATUS = "BLOCKED_V21_044_R8A_SCOPE_BOUNDARY_FAILED"
BLOCKED_DECISION = "BLOCK_WAIT_GATE_REVIEW_R8_R1_OUTPUTS"

ROOT = Path(__file__).resolve().parents[2]
LEDGER_DIR = ROOT / "outputs" / "v21" / "ledger"
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"

R8_R1_DECISION = REVIEW / "V21_044_R8_R1_TECHNICAL_ONLY_DECISION_SUMMARY.csv"
R8_R1_LEDGER = LEDGER_DIR / "V21_044_R8_R1_TECHNICAL_ONLY_OBSERVATION_LEDGER_REFRESHED_WITH_REPAIR.csv"
R8_R1_MATURITY_AUDIT = LEDGER_DIR / "V21_044_R8_R1_TECHNICAL_ONLY_MATURITY_REFRESH_AUDIT.csv"

WAIT_SUMMARY = REVIEW / "V21_044_R8A_WAIT_UNTIL_FIRST_MATURITY_DATE_SUMMARY.csv"
GATE_STATUS = REVIEW / "V21_044_R8A_MATURITY_GATE_STATUS.csv"
SCOPE_AUDIT = REVIEW / "V21_044_R8A_SCOPE_BOUNDARY_AUDIT.csv"
DECISION_SUMMARY = REVIEW / "V21_044_R8A_DECISION_SUMMARY.csv"
REPORT = READ_CENTER / "V21_044_R8A_WAIT_UNTIL_FIRST_MATURITY_DATE_REPORT.md"
CURRENT_REPORT = READ_CENTER / "CURRENT_V21_044_R8A_WAIT_UNTIL_FIRST_MATURITY_DATE_REPORT.md"

GUARDRAILS = {
    "research_only": "TRUE",
    "wait_gate_only": "TRUE",
    "observation_only": "TRUE",
    "technical_only_observation": "TRUE",
    "full_weight_result_available": "FALSE",
    "full_weight_rebacktest_allowed_now": "FALSE",
    "official_adoption_allowed": "FALSE",
    "official_weight_mutation": "FALSE",
    "official_ranking_mutation": "FALSE",
    "official_recommendation_allowed": "FALSE",
    "real_book_action_allowed": "FALSE",
    "broker_execution_allowed": "FALSE",
    "trade_action_allowed": "FALSE",
    "shadow_gate_allowed": "FALSE",
    "shadow_adoption_allowed": "FALSE",
}

FALSE_GUARDRAILS = [
    "full_weight_result_available",
    "full_weight_rebacktest_allowed_now",
    "official_adoption_allowed",
    "official_weight_mutation",
    "official_ranking_mutation",
    "official_recommendation_allowed",
    "real_book_action_allowed",
    "broker_execution_allowed",
    "trade_action_allowed",
    "shadow_gate_allowed",
    "shadow_adoption_allowed",
]


def yn(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: "" if row.get(field) is None else row.get(field, "") for field in fields})


def norm(value: object) -> str:
    return str(value or "").strip()


def unique_dates(rows: list[dict[str, str]]) -> list[str]:
    return sorted({norm(row.get("scheduled_maturity_date")) for row in rows if norm(row.get("scheduled_maturity_date"))})


def count_rows_with_value(rows: list[dict[str, str]], field: str) -> int:
    return sum(1 for row in rows if norm(row.get(field)))


def main() -> int:
    REVIEW.mkdir(parents=True, exist_ok=True)
    READ_CENTER.mkdir(parents=True, exist_ok=True)

    decision_rows = read_rows(R8_R1_DECISION)
    ledger_rows = read_rows(R8_R1_LEDGER)
    maturity_audit = read_rows(R8_R1_MATURITY_AUDIT)
    r8_r1 = decision_rows[0] if decision_rows else {}

    inputs_found = all(path.exists() and path.stat().st_size > 0 for path in [R8_R1_DECISION, R8_R1_LEDGER, R8_R1_MATURITY_AUDIT])
    r8_r1_ready = (
        r8_r1.get("final_status") == "PASS_V21_044_R8_R1_ENTRY_PRICE_BINDING_REPAIRED_PENDING_MATURITY"
        and r8_r1.get("decision") == "ENTRY_PRICE_REPAIRED_WAIT_FOR_MATURITY_DATES"
    )
    row_count_matches = bool(ledger_rows) and len(ledger_rows) == int(r8_r1.get("refreshed_ledger_rows") or 0)
    entry_repaired = all(norm(row.get("entry_price")) and norm(row.get("entry_price_date")) == "2026-06-16" for row in ledger_rows)
    benchmark_repaired = all(norm(row.get("benchmark_entry_price")) and norm(row.get("benchmark_entry_date")) == "2026-06-16" for row in ledger_rows)
    matured_rows = sum(1 for row in ledger_rows if row.get("maturity_status") == "MATURED")
    pending_rows = sum(1 for row in ledger_rows if row.get("maturity_status") == "PENDING_NOT_MATURED")
    no_returns = count_rows_with_value(ledger_rows, "realized_forward_return") == 0 and count_rows_with_value(ledger_rows, "benchmark_forward_return") == 0
    no_audit_returns = all(row.get("realized_return_computed") == "FALSE" and row.get("benchmark_return_computed") == "FALSE" for row in maturity_audit)
    dates = unique_dates(ledger_rows)
    first_maturity_date = dates[0] if dates else "2026-06-24"
    observation_dates = sorted({norm(row.get("observation_as_of_date")) for row in ledger_rows if norm(row.get("observation_as_of_date"))})
    observation_date = observation_dates[-1] if observation_dates else r8_r1.get("observation_as_of_date", "2026-06-16")

    checks = [
        ("r8_r1_inputs_found", inputs_found, "Required R8-R1 decision, repaired ledger, and maturity audit must exist."),
        ("r8_r1_status_ready", r8_r1_ready, "R8-R1 must have repaired entry bindings and routed to this wait gate."),
        ("row_count_preserved", row_count_matches, "Wait gate must not append or remove observation rows."),
        ("entry_prices_fully_repaired", entry_repaired, "All ledger rows must have repaired ticker entry prices for 2026-06-16."),
        ("benchmark_entry_prices_fully_repaired", benchmark_repaired, "All ledger rows must have repaired benchmark entry prices for 2026-06-16."),
        ("no_matured_rows", matured_rows == 0 and pending_rows == len(ledger_rows), "All rows must remain pending before the first maturity date."),
        ("no_returns_computed", no_returns and no_audit_returns, "Wait gate must not compute realized or benchmark returns."),
        ("restricted_scope_guardrails", all(GUARDRAILS[field] == "FALSE" for field in FALSE_GUARDRAILS), "Full-weight, official, execution, real-book, and shadow permissions remain disabled."),
    ]
    scope_ok = all(passed for _, passed, _ in checks)
    scope_rows = [
        {
            "boundary_check": name,
            "required_value": "TRUE",
            "observed_value": yn(passed),
            "check_passed": yn(passed),
            "blocking": "TRUE",
            "notes": notes,
            **GUARDRAILS,
        }
        for name, passed, notes in checks
    ]
    write_rows(SCOPE_AUDIT, scope_rows)

    final_status = FINAL_STATUS if scope_ok else BLOCKED_STATUS
    decision = FINAL_DECISION if scope_ok else BLOCKED_DECISION
    r9_allowed_now = False
    r8_rerun_allowed_now = False
    r8_rerun_condition = f"local_price_cache_covers_first_maturity_date_{first_maturity_date.replace('-', '_')}"
    recommended_next_stage = "rerun V21.044-R8_TECHNICAL_ONLY_LEDGER_MATURITY_REFRESH after local price cache covers 2026-06-24"

    base_row = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "observation_as_of_date": observation_date,
        "input_ledger_rows": len(ledger_rows),
        "entry_price_repaired_rows": count_rows_with_value(ledger_rows, "entry_price"),
        "benchmark_entry_price_repaired_rows": count_rows_with_value(ledger_rows, "benchmark_entry_price"),
        "remaining_entry_price_missing": sum(1 for row in ledger_rows if not norm(row.get("entry_price")) or not norm(row.get("benchmark_entry_price"))),
        "matured_rows": matured_rows,
        "pending_rows": pending_rows,
        "first_maturity_date": first_maturity_date,
        "required_price_date_for_5D": "2026-06-24",
        "required_price_date_for_10D": "2026-07-01",
        "required_price_date_for_20D": "2026-07-16",
        "required_price_date_for_60D": "2026-09-11",
        "r9_allowed_now": yn(r9_allowed_now),
        "r8_rerun_allowed_now": yn(r8_rerun_allowed_now),
        "r8_rerun_condition": r8_rerun_condition,
        "returns_computed": "FALSE",
        "observations_appended": "FALSE",
        "full_weight_blocked": "TRUE",
        "recommended_next_stage": recommended_next_stage,
        **GUARDRAILS,
    }
    write_rows(WAIT_SUMMARY, [base_row])
    write_rows(DECISION_SUMMARY, [base_row])

    gate_rows = []
    for window, date in [("5D", "2026-06-24"), ("10D", "2026-07-01"), ("20D", "2026-07-16"), ("60D", "2026-09-11")]:
        window_rows = [row for row in ledger_rows if row.get("forward_window") == window]
        gate_rows.append({
            "maturity_window": window,
            "required_maturity_date": date,
            "row_count": len(window_rows),
            "matured_rows": sum(1 for row in window_rows if row.get("maturity_status") == "MATURED"),
            "pending_rows": sum(1 for row in window_rows if row.get("maturity_status") == "PENDING_NOT_MATURED"),
            "gate_status": "WAITING_FOR_FIRST_MATURITY_DATE" if window == "5D" else "WAITING_FOR_LATER_MATURITY_DATE",
            "r8_rerun_allowed_for_window_now": "FALSE",
            "r9_allowed_for_window_now": "FALSE",
            "returns_computed": "FALSE",
            **GUARDRAILS,
        })
    write_rows(GATE_STATUS, gate_rows)

    report = f"""# V21.044-R8A wait until first maturity date

final_status: {final_status}

decision: {decision}

observation_as_of_date: {observation_date}

input ledger rows: {len(ledger_rows)}

entry price repaired rows: {base_row['entry_price_repaired_rows']}

benchmark entry price repaired rows: {base_row['benchmark_entry_price_repaired_rows']}

remaining entry price missing: {base_row['remaining_entry_price_missing']}

matured rows: {matured_rows}

pending rows: {pending_rows}

first maturity date: {first_maturity_date}

R9 allowed now: FALSE

R8 rerun condition: local price cache must cover {first_maturity_date}.

No returns were computed. No observations were appended. No trading or adoption output was created.

Technical-only observation must not be interpreted as full-weight result or full-weight evidence.

Full-weight remains blocked: TRUE. full_weight_result_available=FALSE and full_weight_rebacktest_allowed_now=FALSE.

Recommended next stage: {recommended_next_stage}

Guardrail statement: this stage is research-only and wait-gate-only. Official adoption, official ranking mutation, official weight mutation, official recommendation creation, real-book actions, broker execution, trade actions, shadow gate, and shadow adoption remain disabled.
"""
    REPORT.write_text(report, encoding="utf-8")
    shutil.copyfile(REPORT, CURRENT_REPORT)

    print(f"final_status={final_status}")
    print(f"decision={decision}")
    print(f"first_maturity_date={first_maturity_date}")
    print(f"r9_allowed_now={yn(r9_allowed_now)}")
    print(f"r8_rerun_condition={r8_rerun_condition}")
    print("full_weight_blocked=TRUE")
    print(f"recommended_next_stage={recommended_next_stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
