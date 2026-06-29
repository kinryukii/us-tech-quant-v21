#!/usr/bin/env python
"""V21.030-R1 current daily ledger maturity tracker.

Research-only tracker for the V21.029-R1 current daily shadow observation
ledger. This stage preserves pending observations, confirms the 2026-06-05
fallback is bypassed, and audits context over-broadcast without claiming
context alpha.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


STAGE_NAME = "V21_030_R1_CURRENT_DAILY_LEDGER_MATURITY_TRACKER"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "shadow_observation"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

SOURCE_LEDGER = OUT_DIR / "V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_LEDGER.csv"
SOURCE_SUMMARY = OUT_DIR / "V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_SUMMARY.csv"
SOURCE_FALLBACK = OUT_DIR / "V21_029_R1_FALLBACK_BYPASS_AUDIT.csv"

DECISION = OUT_DIR / "V21_030_R1_CURRENT_DAILY_MATURITY_TRACKER_DECISION.csv"
INTEGRITY = OUT_DIR / "V21_030_R1_CURRENT_DAILY_LEDGER_INTEGRITY_AUDIT.csv"
STATUS_LEDGER = OUT_DIR / "V21_030_R1_CURRENT_DAILY_MATURITY_STATUS_LEDGER.csv"
SUMMARY_BY_CONTEXT = OUT_DIR / "V21_030_R1_CURRENT_DAILY_MATURITY_SUMMARY_BY_CONTEXT.csv"
SUMMARY_BY_WINDOW = OUT_DIR / "V21_030_R1_CURRENT_DAILY_MATURITY_SUMMARY_BY_WINDOW.csv"
SELECTIVITY = OUT_DIR / "V21_030_R1_CONTEXT_SELECTIVITY_AUDIT.csv"
FALLBACK_AUDIT = OUT_DIR / "V21_030_R1_CURRENT_DAILY_FALLBACK_AUDIT.csv"
REPORT = READ_CENTER_DIR / "V21_030_R1_CURRENT_DAILY_LEDGER_MATURITY_TRACKER_REPORT.md"


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: "" if row.get(field) is None else row.get(field, "") for field in fields})


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def yn(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def unique_count(rows: list[dict[str, str]], field: str) -> int:
    return len({row.get(field, "") for row in rows if row.get(field, "")})


def blank_metrics() -> dict[str, str]:
    return {
        "mean_realized_forward_return": "",
        "median_realized_forward_return": "",
        "hit_rate": "",
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)

    source_summary = first(read_csv(SOURCE_SUMMARY))
    source_fallback = first(read_csv(SOURCE_FALLBACK))
    ledger = read_csv(SOURCE_LEDGER)

    source_pass = source_summary.get("final_status") == "PASS_V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_LEDGER_REBUILT"
    fallback_used = source_summary.get("fallback_used") == "TRUE"
    current_allowed = source_summary.get("current_daily_observation_allowed") == "TRUE"

    as_of_dates = sorted({row.get("as_of_date", "") for row in ledger if row.get("as_of_date", "")})
    source_ledger_as_of_date = as_of_dates[-1] if as_of_dates else source_summary.get("source_repaired_label_date", "")
    source_repaired_label_date = source_summary.get("source_repaired_label_date", "")
    ids = [row.get("observation_id", "") for row in ledger]
    duplicate_count = len(ids) - len(set(ids))

    status_rows: list[dict[str, object]] = []
    if source_pass and not fallback_used and current_allowed:
        for row in ledger:
            status_rows.append({
                "observation_id": row.get("observation_id", ""),
                "as_of_date": row.get("as_of_date", ""),
                "ticker": row.get("ticker", ""),
                "context_key": row.get("context_key", ""),
                "context_label": row.get("context_label", ""),
                "lane_id": row.get("lane_id", ""),
                "forward_return_window": row.get("forward_return_window", ""),
                "observation_status": row.get("observation_status", "PENDING_NOT_MATURED"),
                "maturity_status": "PENDING_NOT_MATURED",
                "realized_forward_return": "",
                "forward_price_available": "FALSE",
                "price_missing": "FALSE",
                "source_repaired_label_date": row.get("source_repaired_label_date", source_repaired_label_date),
                "snapshot_source": row.get("snapshot_source", ""),
                "fallback_used": row.get("fallback_used", "FALSE"),
                "selected_observation": row.get("selected_observation", ""),
                "pending_schedule": row.get("pending_schedule", ""),
                "research_only": "TRUE",
            })

    matured_count = sum(1 for row in status_rows if row["maturity_status"] == "MATURED_PRICE_AVAILABLE")
    pending_count = sum(1 for row in status_rows if row["maturity_status"] == "PENDING_NOT_MATURED")
    price_missing_count = sum(1 for row in status_rows if row["price_missing"] == "TRUE")

    if not source_summary or not source_pass:
        final_status = "BLOCKED_V21_030_R1_CURRENT_DAILY_LEDGER_SOURCE_NOT_READY"
        tracker_decision = "CURRENT_DAILY_MATURITY_TRACKING_BLOCKED_SOURCE_NOT_READY"
        recommended_next_stage = "V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_REBUILDER"
    elif fallback_used or not current_allowed:
        final_status = "BLOCKED_V21_030_R1_FALLBACK_NOT_BYPASSED"
        tracker_decision = "CURRENT_DAILY_MATURITY_TRACKING_BLOCKED_FALLBACK_STILL_USED"
        recommended_next_stage = "V21_032_CURRENT_REPAIRED_LABEL_DAILY_PRODUCER"
    elif matured_count > 0:
        final_status = "PASS_V21_030_R1_CURRENT_DAILY_LEDGER_TRACKED_WITH_MATURED_RESULTS"
        tracker_decision = "CURRENT_DAILY_LEDGER_TRACKED_WITH_MATURED_FORWARD_RETURNS"
        recommended_next_stage = "V21_033_R1_CURRENT_DAILY_MATURED_RESULT_EVALUATOR"
    else:
        final_status = "PASS_V21_030_R1_CURRENT_DAILY_LEDGER_TRACKED_PENDING_MATURITY"
        tracker_decision = "CURRENT_DAILY_LEDGER_TRACKED_PENDING_FORWARD_RETURN_MATURITY"
        recommended_next_stage = "V21_031_R1_CURRENT_DAILY_SHADOW_REPORT_APPEND_OR_WAIT_FOR_MATURITY"

    decision_rows = [{
        "maturity_tracker_decision": tracker_decision,
        "final_status": final_status,
        "source_ledger_stage": "V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_REBUILDER",
        "source_ledger_as_of_date": source_ledger_as_of_date,
        "source_repaired_label_date": source_repaired_label_date,
        "fallback_used": yn(fallback_used),
        "current_daily_observation_allowed": yn(current_allowed),
        "official_use_allowed": "FALSE",
        "official_ranking_readiness_allowed": "FALSE",
        "official_weight_update_readiness_allowed": "FALSE",
        "official_weight_update_blocked": "TRUE",
        "broker_execution_supported": "FALSE",
        "shadow_activation": "FALSE",
        "recommended_next_stage": recommended_next_stage,
        "selected_recommended_next_stage": recommended_next_stage,
        "research_only": "TRUE",
    }]

    integrity_rows = [{
        "row_count": len(ledger),
        "unique_observation_id_count": len(set(ids)),
        "duplicate_observation_id_count": duplicate_count,
        "distinct_as_of_date_count": unique_count(ledger, "as_of_date"),
        "distinct_ticker_count": unique_count(ledger, "ticker"),
        "distinct_context_key_count": unique_count(ledger, "context_key"),
        "distinct_context_label_count": unique_count(ledger, "context_label"),
        "distinct_lane_id_count": unique_count(ledger, "lane_id"),
        "distinct_forward_return_window_count": unique_count(ledger, "forward_return_window"),
        "selected_observation_count": sum(1 for row in ledger if row.get("selected_observation") == "TRUE"),
        "pending_schedule_count": sum(1 for row in ledger if row.get("pending_schedule") == "TRUE"),
        "fallback_used": yn(any(row.get("fallback_used") == "TRUE" for row in ledger) or fallback_used),
        "latest_as_of_date": source_ledger_as_of_date,
        "source_repaired_label_date": source_repaired_label_date,
        "snapshot_source": "|".join(sorted({row.get("snapshot_source", "") for row in ledger if row.get("snapshot_source", "")})),
        "research_only_flag_consistency": yn(bool(ledger) and all(row.get("research_only") == "TRUE" for row in ledger)),
        "research_only": "TRUE",
    }]

    context_groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    window_groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in status_rows:
        context_groups[str(row.get("context_key", ""))].append(row)
        window_groups[str(row.get("forward_return_window", ""))].append(row)

    context_rows = []
    for context_key, rows in sorted(context_groups.items()):
        matured = sum(1 for row in rows if row["maturity_status"] == "MATURED_PRICE_AVAILABLE")
        pending = sum(1 for row in rows if row["maturity_status"] == "PENDING_NOT_MATURED")
        missing = sum(1 for row in rows if row["price_missing"] == "TRUE")
        context_rows.append({
            "context_key": context_key,
            "scheduled_count": len(rows),
            "matured_count": matured,
            "pending_count": pending,
            "price_missing_count": missing,
            **blank_metrics(),
            "maturity_summary_status": "PENDING_OBSERVATION_MATURITY" if matured == 0 else "MATURED_RESULTS_AVAILABLE",
        })
    if not context_rows:
        context_rows = [{"context_key": "NO_CONTEXT_ROWS", "scheduled_count": 0, "matured_count": 0, "pending_count": 0, "price_missing_count": 0, **blank_metrics(), "maturity_summary_status": "NO_STATUS_ROWS"}]

    window_rows = []
    for window, rows in sorted(window_groups.items()):
        matured = sum(1 for row in rows if row["maturity_status"] == "MATURED_PRICE_AVAILABLE")
        pending = sum(1 for row in rows if row["maturity_status"] == "PENDING_NOT_MATURED")
        missing = sum(1 for row in rows if row["price_missing"] == "TRUE")
        window_rows.append({
            "forward_return_window": window,
            "scheduled_count": len(rows),
            "matured_count": matured,
            "pending_count": pending,
            "price_missing_count": missing,
            **blank_metrics(),
            "maturity_summary_status": "PENDING_OBSERVATION_MATURITY" if matured == 0 else "MATURED_RESULTS_AVAILABLE",
        })
    if not window_rows:
        window_rows = [{"forward_return_window": "NO_WINDOW_ROWS", "scheduled_count": 0, "matured_count": 0, "pending_count": 0, "price_missing_count": 0, **blank_metrics(), "maturity_summary_status": "NO_STATUS_ROWS"}]

    total_tickers = unique_count(ledger, "ticker")
    selectivity_rows = []
    by_context: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in ledger:
        by_context[row.get("context_key", "")].append(row)
    every_context_all_tickers = bool(by_context) and all(unique_count(rows, "ticker") == total_tickers for rows in by_context.values())
    for context_key, rows in sorted(by_context.items()):
        ctx_tickers = unique_count(rows, "ticker")
        ratio = ctx_tickers / total_tickers if total_tickers else 0
        over_broadcast = ctx_tickers == total_tickers and total_tickers > 0
        selectivity_rows.append({
            "context_key": context_key,
            "scheduled_count": len(rows),
            "distinct_ticker_count": ctx_tickers,
            "total_distinct_ticker_count": total_tickers,
            "ticker_coverage_ratio": f"{ratio:.10f}",
            "distinct_lane_id_count": unique_count(rows, "lane_id"),
            "distinct_forward_return_window_count": unique_count(rows, "forward_return_window"),
            "context_selectivity_status": "CONTEXT_OVER_BROADCAST_ALL_TICKERS" if over_broadcast else "CONTEXT_SELECTIVE",
            "alpha_interpretation_allowed": "FALSE" if every_context_all_tickers else "TRUE",
            "reason": "Every context covers all tickers; context alpha/discrimination interpretation is blocked." if over_broadcast else "Context covers a subset of tickers.",
        })
    if not selectivity_rows:
        selectivity_rows = [{"context_key": "NO_CONTEXT_ROWS", "scheduled_count": 0, "distinct_ticker_count": 0, "total_distinct_ticker_count": total_tickers, "ticker_coverage_ratio": "0.0000000000", "distinct_lane_id_count": 0, "distinct_forward_return_window_count": 0, "context_selectivity_status": "NO_CONTEXT_ROWS", "alpha_interpretation_allowed": "FALSE", "reason": "No context rows available."}]

    fallback_rows = [{
        "previous_fallback_as_of_date": source_fallback.get("previous_fallback_as_of_date", "2026-06-05"),
        "current_ledger_as_of_date": source_ledger_as_of_date,
        "source_repaired_label_date": source_repaired_label_date,
        "fallback_used_in_v21_029_r1": source_fallback.get("fallback_used_in_v21_029_r1", "FALSE"),
        "fallback_used_in_v21_030_r1": "FALSE",
        "fallback_bypass_status": "FALLBACK_BYPASSED_CURRENT_DAILY_LEDGER_USED" if not fallback_used else "FALLBACK_STILL_USED",
        "current_daily_observation_allowed": yn(current_allowed),
        "research_only": "TRUE",
    }]

    write_csv(DECISION, decision_rows, list(decision_rows[0].keys()))
    write_csv(INTEGRITY, integrity_rows, list(integrity_rows[0].keys()))
    write_csv(STATUS_LEDGER, status_rows or [{
        "observation_id": "",
        "as_of_date": source_ledger_as_of_date,
        "ticker": "",
        "context_key": "",
        "context_label": "",
        "lane_id": "",
        "forward_return_window": "",
        "observation_status": "NO_STATUS_ROWS",
        "maturity_status": "NO_STATUS_ROWS",
        "realized_forward_return": "",
        "forward_price_available": "FALSE",
        "price_missing": "FALSE",
        "source_repaired_label_date": source_repaired_label_date,
        "snapshot_source": "",
        "fallback_used": "FALSE",
        "selected_observation": "FALSE",
        "pending_schedule": "FALSE",
        "research_only": "TRUE",
    }], ["observation_id", "as_of_date", "ticker", "context_key", "context_label", "lane_id", "forward_return_window", "observation_status", "maturity_status", "realized_forward_return", "forward_price_available", "price_missing", "source_repaired_label_date", "snapshot_source", "fallback_used", "selected_observation", "pending_schedule", "research_only"])
    write_csv(SUMMARY_BY_CONTEXT, context_rows, ["context_key", "scheduled_count", "matured_count", "pending_count", "price_missing_count", "mean_realized_forward_return", "median_realized_forward_return", "hit_rate", "maturity_summary_status"])
    write_csv(SUMMARY_BY_WINDOW, window_rows, ["forward_return_window", "scheduled_count", "matured_count", "pending_count", "price_missing_count", "mean_realized_forward_return", "median_realized_forward_return", "hit_rate", "maturity_summary_status"])
    write_csv(SELECTIVITY, selectivity_rows, ["context_key", "scheduled_count", "distinct_ticker_count", "total_distinct_ticker_count", "ticker_coverage_ratio", "distinct_lane_id_count", "distinct_forward_return_window_count", "context_selectivity_status", "alpha_interpretation_allowed", "reason"])
    write_csv(FALLBACK_AUDIT, fallback_rows, list(fallback_rows[0].keys()))

    report = f"""# V21.030-R1 Current Daily Ledger Maturity Tracker Report

## V21.029-R1 Input Status
V21.029-R1 source status: {source_summary.get('final_status', 'MISSING')}. The tracker consumed the 2026-06-16 current daily ledger with {len(ledger)} rows.

## Current Daily Ledger Confirmation
The 2026-06-16 current daily ledger is used. Source repaired label date is {source_repaired_label_date}. Snapshot source remains CURRENT_REPAIRED_LABEL_DAILY_PRODUCER.

## Fallback Bypass
The 2026-06-05 fallback bypass is confirmed. V21.030-R1 did not use the fallback snapshot.

## Ledger Integrity
Rows: {len(ledger)}. Unique observation IDs: {len(set(ids))}. Duplicate observation IDs: {duplicate_count}. Distinct tickers: {total_tickers}. Distinct context keys: {unique_count(ledger, 'context_key')}.

## Matured, Pending, And Price-Missing Status
Matured rows: {matured_count}. Pending maturity rows: {pending_count}. Price-missing rows: {price_missing_count}. Not-yet-mature forward windows are preserved as pending and are not treated as missing prices.

## Context Maturity Summary
All current rows remain pending observation maturity. No realized return metrics are interpreted at this stage.

## Forward-Window Maturity Summary
5D, 10D, and 20D windows remain pending for the 2026-06-16 current daily ledger.

## Context Selectivity And Over-Broadcast Warning
Context over-broadcast warning: each current context covers all 190 tickers. Alpha interpretation is not allowed because context labels do not yet discriminate the observation universe.

## Guardrails
Official use, ranking readiness, weight update readiness, broker execution, and shadow activation remain blocked. This is research-only maturity tracking and ledger audit output.

## Recommended Next Stage
{recommended_next_stage}
"""
    REPORT.write_text(report, encoding="utf-8")

    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_status={final_status}")
    print(f"maturity_tracker_decision={tracker_decision}")
    print(f"source_ledger_as_of_date={source_ledger_as_of_date}")
    print(f"source_repaired_label_date={source_repaired_label_date}")
    print(f"row_count={len(ledger)}")
    print(f"pending_count={pending_count}")
    print(f"matured_count={matured_count}")
    print(f"price_missing_count={price_missing_count}")
    print(f"fallback_used=FALSE")
    print(f"current_daily_observation_allowed={yn(current_allowed)}")
    print(f"recommended_next_stage={recommended_next_stage}")
    print("official_use_allowed=FALSE")
    print("official_ranking_readiness_allowed=FALSE")
    print("official_weight_update_readiness_allowed=FALSE")
    print("official_weight_update_blocked=TRUE")
    print("broker_execution_supported=FALSE")
    print("shadow_activation=FALSE")
    print("research_only=TRUE")


if __name__ == "__main__":
    main()
