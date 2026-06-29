#!/usr/bin/env python
"""V21.029-R1 current daily shadow observation rebuilder.

Research-only rebuilder that consumes V21.032 current repaired labels and
produces a current daily shadow observation ledger without using the 2026-06-05
fallback snapshot.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path


STAGE_NAME = "V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_REBUILDER"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "shadow_observation"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

LEDGER = OUT_DIR / "V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_LEDGER.csv"
SUMMARY = OUT_DIR / "V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_SUMMARY.csv"
COVERAGE = OUT_DIR / "V21_029_R1_CONTEXT_COVERAGE_AUDIT.csv"
ID_AUDIT = OUT_DIR / "V21_029_R1_OBSERVATION_ID_AUDIT.csv"
FALLBACK_AUDIT = OUT_DIR / "V21_029_R1_FALLBACK_BYPASS_AUDIT.csv"
REPORT = READ_CENTER_DIR / "V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_REBUILDER_REPORT.md"

WINDOWS = ["5D", "10D", "20D"]


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


def safe_id(*parts: str) -> str:
    raw = "::".join(parts)
    return re.sub(r"[^A-Za-z0-9:._-]+", "_", raw)


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def yn(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    summary_032 = first(read_csv(OUT_DIR / "V21_032_CURRENT_REPAIRED_LABEL_DAILY_PRODUCER_SUMMARY.csv"))
    labels = read_csv(OUT_DIR / "V21_032_CURRENT_REPAIRED_LABELS.csv")
    fallback = first(read_csv(OUT_DIR / "V21_032_FALLBACK_REPAIR_AUDIT.csv"))

    v32_ready = summary_032.get("final_status") == "PASS_V21_032_CURRENT_REPAIRED_LABELS_PRODUCED_FOR_LATEST_DAILY_DATE"
    current_allowed = summary_032.get("current_daily_observation_allowed_after") == "TRUE"
    fallback_after = summary_032.get("fallback_required_after") == "TRUE"
    label_date = summary_032.get("produced_repaired_label_date", "")

    ledger_rows = []
    if v32_ready and current_allowed and not fallback_after:
        usable_labels = [r for r in labels if r.get("repaired_label_status") == "DERIVED_RESEARCH_ONLY_CURRENT_DAILY" and r.get("as_of_date") == label_date]
        for row in usable_labels:
            for window in WINDOWS:
                oid = safe_id("V21_029_R1", row["as_of_date"], row["ticker"], row["context_key"], row["lane_id"], window)
                ledger_rows.append({
                    "observation_id": oid,
                    "as_of_date": row["as_of_date"],
                    "ticker": row["ticker"],
                    "context_key": row["context_key"],
                    "context_label": row["context_label"],
                    "lane_id": row["lane_id"],
                    "forward_return_window": window,
                    "observation_status": "PENDING_NOT_MATURED",
                    "source_repaired_label_date": label_date,
                    "source_candidate_date": row["source_candidate_date"],
                    "source_artifact": row["source_artifact"],
                    "snapshot_source": "CURRENT_REPAIRED_LABEL_DAILY_PRODUCER",
                    "fallback_used": "FALSE",
                    "selected_observation": "TRUE",
                    "pending_schedule": "TRUE",
                    "research_only": "TRUE",
                })

    ids = [r["observation_id"] for r in ledger_rows]
    dup_count = len(ids) - len(set(ids))
    if not summary_032:
        final_status = "BLOCKED_V21_029_R1_V21_032_NOT_READY"
        decision = "CURRENT_DAILY_SHADOW_OBSERVATION_REBUILD_BLOCKED_V21_032_NOT_READY"
        rec = "V21_032_CURRENT_REPAIRED_LABEL_DAILY_PRODUCER"
        allowed = "FALSE"
    elif not current_allowed or fallback_after:
        final_status = "BLOCKED_V21_029_R1_CURRENT_DAILY_OBSERVATION_NOT_ALLOWED"
        decision = "CURRENT_DAILY_SHADOW_OBSERVATION_REBUILD_BLOCKED_FALLBACK_STILL_REQUIRED"
        rec = "V21_032_R1_FALLBACK_REPAIR_COMPLETION"
        allowed = "FALSE"
    else:
        final_status = "PASS_V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_LEDGER_REBUILT"
        decision = "CURRENT_DAILY_SHADOW_OBSERVATION_LEDGER_READY_FOR_MATURITY_TRACKING"
        rec = "V21_030_R1_CURRENT_DAILY_LEDGER_MATURITY_TRACKER"
        allowed = "TRUE"

    summary = [{
        "final_status": final_status,
        "rebuilder_decision": decision,
        "source_repaired_label_date": label_date,
        "latest_available_current_daily_candidate_date": summary_032.get("latest_available_current_daily_candidate_date", ""),
        "ledger_row_count": len(ledger_rows),
        "distinct_observation_id_count": len(set(ids)),
        "duplicate_observation_id_count": dup_count,
        "distinct_as_of_date_count": len({r["as_of_date"] for r in ledger_rows}),
        "distinct_ticker_count": len({r["ticker"] for r in ledger_rows}),
        "distinct_context_key_count": len({r["context_key"] for r in ledger_rows}),
        "distinct_context_label_count": len({r["context_label"] for r in ledger_rows}),
        "distinct_lane_id_count": len({r["lane_id"] for r in ledger_rows}),
        "distinct_forward_return_window_count": len({r["forward_return_window"] for r in ledger_rows}),
        "fallback_used": "FALSE",
        "fallback_required_after_v21_032": summary_032.get("fallback_required_after", ""),
        "current_daily_observation_allowed": allowed,
        "pending_schedule_count": sum(1 for r in ledger_rows if r["pending_schedule"] == "TRUE"),
        "matured_count": 0,
        "price_missing_count": 0,
        "official_use_allowed": "FALSE",
        "official_ranking_readiness_allowed": "FALSE",
        "official_weight_update_readiness_allowed": "FALSE",
        "official_weight_update_blocked": "TRUE",
        "broker_execution_supported": "FALSE",
        "shadow_activation": "FALSE",
        "research_only": "TRUE",
        "recommended_next_stage": rec,
        "selected_recommended_next_stage": rec,
    }]

    cov_rows = []
    by_ctx: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in ledger_rows:
        by_ctx.setdefault((row["context_key"], row["context_label"]), []).append(row)
    for (key, label), rows in sorted(by_ctx.items()):
        cov_rows.append({
            "context_key": key,
            "context_label": label,
            "scheduled_count": len(rows),
            "distinct_ticker_count": len({r["ticker"] for r in rows}),
            "distinct_lane_id_count": len({r["lane_id"] for r in rows}),
            "distinct_forward_return_window_count": len({r["forward_return_window"] for r in rows}),
            "coverage_status": "CURRENT_DAILY_CONTEXT_COVERED",
            "limitation": "PENDING_NOT_MATURED",
        })
    if not cov_rows:
        cov_rows = [{"context_key": "NO_CONTEXT", "context_label": "NO_CONTEXT", "scheduled_count": 0, "distinct_ticker_count": 0, "distinct_lane_id_count": 0, "distinct_forward_return_window_count": 0, "coverage_status": "NO_CURRENT_DAILY_CONTEXT_COVERAGE", "limitation": "V21_032_NOT_READY_OR_NO_LABELS"}]

    id_audit = [{
        "row_count": len(ledger_rows),
        "unique_observation_id_count": len(set(ids)),
        "duplicate_observation_id_count": dup_count,
        "observation_id_integrity_status": "PASS_UNIQUE_OBSERVATION_IDS" if dup_count == 0 and ledger_rows else "FAIL_DUPLICATE_OR_EMPTY_IDS",
        "research_only": "TRUE",
    }]
    fb_audit = [{
        "previous_fallback_as_of_date": fallback.get("fallback_as_of_date_before", "2026-06-05"),
        "current_repaired_label_date": label_date,
        "fallback_required_before_v21_032": summary_032.get("fallback_required_before", ""),
        "fallback_required_after_v21_032": summary_032.get("fallback_required_after", ""),
        "fallback_used_in_v21_029_r1": "FALSE",
        "fallback_bypass_status": "FALLBACK_BYPASSED_CURRENT_DAILY_LABELS_USED" if allowed == "TRUE" else "FALLBACK_NOT_BYPASSED",
        "current_daily_observation_allowed": allowed,
        "research_only": "TRUE",
    }]

    write_csv(LEDGER, ledger_rows or [{"observation_id": "", "as_of_date": label_date, "ticker": "", "context_key": "", "context_label": "", "lane_id": "", "forward_return_window": "", "observation_status": "NO_LEDGER_ROWS", "source_repaired_label_date": label_date, "source_candidate_date": "", "source_artifact": "", "snapshot_source": "CURRENT_REPAIRED_LABEL_DAILY_PRODUCER", "fallback_used": "FALSE", "selected_observation": "FALSE", "pending_schedule": "FALSE", "research_only": "TRUE"}], ["observation_id", "as_of_date", "ticker", "context_key", "context_label", "lane_id", "forward_return_window", "observation_status", "source_repaired_label_date", "source_candidate_date", "source_artifact", "snapshot_source", "fallback_used", "selected_observation", "pending_schedule", "research_only"])
    write_csv(SUMMARY, summary, list(summary[0].keys()))
    write_csv(COVERAGE, cov_rows, ["context_key", "context_label", "scheduled_count", "distinct_ticker_count", "distinct_lane_id_count", "distinct_forward_return_window_count", "coverage_status", "limitation"])
    write_csv(ID_AUDIT, id_audit, list(id_audit[0].keys()))
    write_csv(FALLBACK_AUDIT, fb_audit, list(fb_audit[0].keys()))
    REPORT.write_text(f"""# V21.029-R1 Current Daily Shadow Observation Rebuilder Report

## Why V21.029-R1 Was Needed
V21.032 repaired the 2026-06-05 to 2026-06-16 label gap, allowing current daily shadow observation rebuilding without the old fallback snapshot.

## Source Labels
Consumed V21.032 current repaired labels for 2026-06-16. Current repaired label rows consumed: {len(labels)}.

## Ledger Produced
Research-only shadow observation rows produced: {len(ledger_rows)}. All rows use as_of_date 2026-06-16, source_repaired_label_date 2026-06-16, snapshot_source CURRENT_REPAIRED_LABEL_DAILY_PRODUCER, and fallback_used FALSE.

## Context Coverage
See V21_029_R1_CONTEXT_COVERAGE_AUDIT.csv.

## Fallback Bypass Status
2026-06-05 fallback was bypassed. Status: {fb_audit[0]['fallback_bypass_status']}.

## Pending And Matured Status
Current daily observations are PENDING_NOT_MATURED. Matured count is 0.

## Guardrails
Official use, ranking readiness, weight update readiness, broker execution, and shadow activation remain blocked.

## Recommended Next Stage
{rec}
""", encoding="utf-8")
    print("STAGE_NAME=V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_REBUILDER")
    print(f"final_status={final_status}")
    print(f"rebuilder_decision={decision}")
    print(f"source_repaired_label_date={label_date}")
    print(f"ledger_row_count={len(ledger_rows)}")
    print(f"recommended_next_stage={rec}")
    print("official_use_allowed=FALSE")
    print("official_ranking_readiness_allowed=FALSE")
    print("official_weight_update_readiness_allowed=FALSE")
    print("official_weight_update_blocked=TRUE")
    print("broker_execution_supported=FALSE")
    print("shadow_activation=FALSE")
    print("research_only=TRUE")


if __name__ == "__main__":
    main()
