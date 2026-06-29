#!/usr/bin/env python
"""Verify listing age and repair local-history-gap misclassification."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable


STAGE_ID = "V21.058-R4"
PASS_STATUS = "PASS_V21_058_R4_LISTING_AGE_POLICY_REPAIRED"
PARTIAL_STATUS = "PARTIAL_PASS_V21_058_R4_READY_WITH_LOCAL_PRICE_DATA_WARN"
FAIL_MISCLASSIFIED = "FAIL_V21_058_R4_LOCAL_HISTORY_GAP_MISCLASSIFIED_AS_IPO"
FAIL_HARDCODED = "FAIL_V21_058_R4_HARDCODED_INCLUSION_VIOLATION"
FAIL_MUTATION = "FAIL_V21_058_R4_FORBIDDEN_MUTATION_DETECTED"

OUT_REL = Path("outputs/v21/momentum")
R3_LEDGER_REL = OUT_REL / "V21_058_R3_NEWLY_LISTED_MOMENTUM_LEDGER.csv"
R3_BOARD_REL = OUT_REL / "V21_058_R3_NEWLY_LISTED_MOMENTUM_BOARD.csv"
R3_FORCED_REL = OUT_REL / "V21_058_R3_FORCED_DIAGNOSTIC_AUDIT.csv"
R3_SUMMARY_REL = OUT_REL / "V21_058_R3_SUMMARY.json"
R2_LEDGER_REL = OUT_REL / "V21_058_R2_REPAIRED_UNIFIED_MOMENTUM_LEDGER.csv"
REFERENCE_REL = Path("configs/v21/instrument_listing_reference.csv")
A0_REL = Path("outputs/v21/experiments/version_control/V21_056_R2_A0_CANONICAL_CONTROL_VIEW.csv")
R1_SNAPSHOT_REL = Path("outputs/v21/experiments/version_control/V21_056_R1_A0_LEDGER_SNAPSHOT.csv")

VERIFICATION_NAME = "V21_058_R4_LISTING_AGE_VERIFICATION_AUDIT.csv"
RECLASS_NAME = "V21_058_R4_SHORT_HISTORY_RECLASSIFICATION_AUDIT.csv"
TQQQ_NAME = "V21_058_R4_TQQQ_POLICY_REPAIR_AUDIT.csv"
DRAM_NAME = "V21_058_R4_DRAM_POLICY_AUDIT.csv"
SPCX_NAME = "V21_058_R4_SPCX_POLICY_AUDIT.csv"
LEDGER_NAME = "V21_058_R4_REPAIRED_NEWLY_LISTED_MOMENTUM_LEDGER.csv"
BOARD_NAME = "V21_058_R4_REPAIRED_NEWLY_LISTED_MOMENTUM_BOARD.csv"
TOP50_NAME = "V21_058_R4_REPAIRED_MOMENTUM_TOP50.csv"
LINEAGE_NAME = "V21_058_R4_LINEAGE_AUDIT.csv"
SUMMARY_NAME = "V21_058_R4_SUMMARY.json"

R4_FIELDS = [
    "listing_reference_value", "listing_date_source", "listing_date_confidence",
    "listing_age_status", "estimated_listing_age_sessions",
    "repaired_r4_policy_bucket", "ipo_watch_removed",
    "local_history_gap_flag", "r4_score_status", "r4_score_scope",
    "r4_classification_reason",
]


def clean(value: object) -> str:
    return str(value or "").strip()


def tf(value: object) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return "TRUE" if clean(value).upper() == "TRUE" else "FALSE"


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.is_file() or path.stat().st_size == 0:
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, rows: Iterable[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                field: "TRUE" if row.get(field) is True else "FALSE" if row.get(field) is False
                else "" if row.get(field) is None else row.get(field, "")
                for field in fields
            })


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def row_count(path: Path) -> int:
    return len(read_csv(path)[0])


def protected_hashes(root: Path) -> dict[str, dict[str, str]]:
    groups = {"a0": {}, "official": {}, "real_book": {}, "broker": {}}
    for path in (root / A0_REL, root / R1_SNAPSHOT_REL):
        if path.is_file():
            groups["a0"][rel(root, path)] = sha(path)
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or root / OUT_REL in path.parents:
                continue
            text = rel(root, path).lower().replace("-", "_").replace(" ", "_")
            if "broker" in text:
                groups["broker"][rel(root, path)] = sha(path)
            elif "real_book" in text or "realbook" in text:
                groups["real_book"][rel(root, path)] = sha(path)
            elif "official" in text and any(token in text for token in ("rank", "weight", "recommend", "allocation")):
                groups["official"][rel(root, path)] = sha(path)
    return groups


def changed(before: dict[str, str], after: dict[str, str]) -> bool:
    return any(before.get(key) != after.get(key) for key in set(before) | set(after))


def parse_date(value: object) -> date | None:
    try:
        return datetime.strptime(clean(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def weekday_sessions(start: date, end: date) -> int:
    if end <= start:
        return 0
    count = 0
    current = start
    while current < end:
        current += timedelta(days=1)
        if current.weekday() < 5:
            count += 1
    return count


def listing_status(reference: dict[str, str], as_of: date) -> tuple[str, int | None]:
    value = clean(reference.get("known_listing_or_inception_date"))
    if value == "UNKNOWN_ESTABLISHED":
        return "ESTABLISHED_DATE_UNKNOWN", None
    parsed = parse_date(value)
    if parsed:
        sessions = weekday_sessions(parsed, as_of)
        return ("RECENT_LISTING_REFERENCE" if sessions < 60 else "ESTABLISHED_LISTING_REFERENCE"), sessions
    return "LISTING_DATE_UNKNOWN", None


def classify(rows: int, status: str, age_sessions: int | None) -> tuple[str, str]:
    if rows <= 0:
        return "LOCAL_PRICE_NOT_FOUND", "No exact-symbol local price rows."
    established = status in {"ESTABLISHED_DATE_UNKNOWN", "ESTABLISHED_LISTING_REFERENCE"}
    if established:
        return "LOCAL_HISTORY_GAP_NOT_NEWLY_LISTED", "Listing reference is established; short local history is a coverage gap."
    if status == "RECENT_LISTING_REFERENCE" and age_sessions is not None:
        if rows >= 20 and age_sessions < 60:
            return "TRUE_NEWLY_LISTED_LIMITED_HISTORY", "Recent listing reference and at least 20 local price rows."
        if rows >= 5 and age_sessions < 20:
            return "TRUE_IPO_EARLY_WATCH", "Recent listing reference, fewer than 20 sessions old, and at least five rows."
        return "UNKNOWN_LISTING_AGE_LOCAL_HISTORY_SHORT", "Recent reference exists but row count/session-age combination does not meet a scoring bucket."
    return "UNKNOWN_LISTING_AGE_LOCAL_HISTORY_SHORT", "Local history is short and listing age is not verified."


def run_stage(root: Path) -> dict[str, object]:
    root = root.resolve()
    out = root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    before = protected_hashes(root)
    r3_rows, r3_fields = read_csv(root / R3_LEDGER_REL)
    references, _ = read_csv(root / REFERENCE_REL)
    reference_map = {clean(row.get("ticker")).upper(): row for row in references}
    max_dates = [parse_date(row.get("latest_price_date") or row.get("as_of_date")) for row in r3_rows]
    as_of = max((value for value in max_dates if value), default=date(2026, 6, 18))

    verification = []
    reclassification = []
    repaired = []
    for source in r3_rows:
        row = dict(source)
        ticker = clean(row.get("ticker")).upper()
        count = int(clean(row.get("listing_age_price_rows")) or "0")
        previous = clean(row.get("newly_listed_policy_bucket"))
        reference = reference_map.get(ticker, {})
        status, age_sessions = listing_status(reference, as_of)
        if count >= 60:
            bucket, reason = "FULL_HISTORY_SCORING", "At least 60 exact-symbol local price rows."
        else:
            bucket, reason = classify(count, status, age_sessions)
        ipo_removed = previous == "IPO_EARLY_MOMENTUM_WATCH" and bucket != "TRUE_IPO_EARLY_WATCH"
        is_gap = bucket == "LOCAL_HISTORY_GAP_NOT_NEWLY_LISTED"

        if bucket == "FULL_HISTORY_SCORING":
            score_status = clean(row.get("r3_score_status"))
            score_scope = clean(row.get("r3_score_scope"))
        elif bucket == "TRUE_NEWLY_LISTED_LIMITED_HISTORY":
            score_status = "TRUE_NEWLY_LISTED_LIMITED_SCORE_PRESERVED"
            score_scope = "COMPARABLE_LIMITED_HISTORY_WITH_RISK_CAP"
        elif bucket == "TRUE_IPO_EARLY_WATCH":
            score_status = "TRUE_IPO_WATCH_SCORE_PRESERVED"
            score_scope = "SEPARATE_IPO_WATCH_BOARD_ONLY"
        elif bucket == "LOCAL_HISTORY_GAP_NOT_NEWLY_LISTED":
            score_status = "LOCAL_HISTORY_GAP_DATA_WARN"
            score_scope = "UNSCORED_COVERAGE_REPAIR_REQUIRED"
            row["ipo_early_momentum_score"] = ""
            row["ipo_watch_score_available"] = "FALSE"
            row["ipo_watch_flag"] = "FALSE"
            row["final_momentum_score_for_r3"] = ""
            row["momentum_state"] = "DATA_INSUFFICIENT"
            row["score_computed"] = "FALSE"
            row["chase_permission"] = "HEDGE_ONLY" if clean(row.get("instrument_type")) == "INVERSE_ETF" else "WATCH_ONLY_DATA_WARN"
            row["risk_size_bucket"] = "WATCH_ONLY"
        else:
            score_status = "DATA_INSUFFICIENT"
            score_scope = "UNSCORED"
            row["full_history_score_available"] = "FALSE"
            row["limited_history_score_available"] = "FALSE"
            row["ipo_watch_score_available"] = "FALSE"
            row["final_momentum_score_for_r3"] = ""
            row["score_computed"] = "FALSE"
        row.update({
            "listing_reference_value": clean(reference.get("known_listing_or_inception_date")),
            "listing_date_source": clean(reference.get("listing_date_source")),
            "listing_date_confidence": clean(reference.get("listing_date_confidence")),
            "listing_age_status": status,
            "estimated_listing_age_sessions": "" if age_sessions is None else age_sessions,
            "repaired_r4_policy_bucket": bucket,
            "newly_listed_policy_bucket": bucket,
            "ipo_watch_removed": tf(ipo_removed),
            "local_history_gap_flag": tf(is_gap),
            "r4_score_status": score_status,
            "r4_score_scope": score_scope,
            "r4_classification_reason": reason,
            "research_only": "TRUE",
        })
        repaired.append(row)
        verification.append({
            "ticker": ticker, "instrument_type": row.get("instrument_type", ""),
            "known_listing_or_inception_date": reference.get("known_listing_or_inception_date", ""),
            "listing_date_source": reference.get("listing_date_source", ""),
            "listing_date_confidence": reference.get("listing_date_confidence", ""),
            "listing_age_status": status,
            "estimated_listing_age_sessions": "" if age_sessions is None else age_sessions,
            "local_price_row_count": count, "previous_r3_bucket": previous,
            "repaired_r4_bucket": bucket, "research_only": "TRUE",
            "notes": reason,
        })
        if count < 60:
            reclassification.append({
                "ticker": ticker, "instrument_type": row.get("instrument_type", ""),
                "previous_r3_bucket": previous, "repaired_r4_bucket": bucket,
                "local_price_row_count": count, "listing_age_status": status,
                "known_listing_or_inception_date": reference.get("known_listing_or_inception_date", ""),
                "ipo_watch_removed": tf(ipo_removed), "local_history_gap_flag": tf(is_gap),
                "score_status_after_repair": score_status, "classification_reason": reason,
                "research_only": "TRUE",
            })

    fields = list(dict.fromkeys([*r3_fields, *R4_FIELDS]))
    write_csv(out / VERIFICATION_NAME, verification, list(verification[0].keys()))
    write_csv(out / RECLASS_NAME, reclassification, list(reclassification[0].keys()))
    write_csv(out / LEDGER_NAME, repaired, fields)
    board = [row for row in repaired if row["repaired_r4_policy_bucket"] != "FULL_HISTORY_SCORING"]
    write_csv(out / BOARD_NAME, board, fields)
    top50 = sorted(
        (
            row for row in repaired
            if row["r4_score_scope"] in {"COMPARABLE_FULL_HISTORY", "COMPARABLE_LIMITED_HISTORY_WITH_RISK_CAP"}
            and tf(row.get("entered_by_forced_audit_only")) != "TRUE"
            and clean(row.get("final_momentum_score_for_r3"))
        ),
        key=lambda row: (-float(row["final_momentum_score_for_r3"]), clean(row.get("ticker"))),
    )[:50]
    for rank, row in enumerate(top50, 1):
        row["momentum_rank"] = rank
    write_csv(out / TOP50_NAME, top50, ["momentum_rank", *fields])
    top_set = {clean(row.get("ticker")).upper() for row in top50}
    by_ticker = {clean(row.get("ticker")).upper(): row for row in repaired}

    tqqq = by_ticker["TQQQ"]
    tqqq_audit = [{
        "ticker": "TQQQ", "previous_r3_bucket": clean(next(row for row in r3_rows if clean(row.get("ticker")).upper() == "TQQQ").get("newly_listed_policy_bucket")),
        "repaired_r4_bucket": tqqq["repaired_r4_policy_bucket"],
        "local_price_row_count": tqqq["listing_age_price_rows"],
        "known_listing_or_inception_date": tqqq["listing_reference_value"],
        "listing_age_status": tqqq["listing_age_status"],
        "ipo_watch_removed": tqqq["ipo_watch_removed"],
        "reason": tqqq["r4_classification_reason"], "research_only": "TRUE",
    }]
    write_csv(out / TQQQ_NAME, tqqq_audit, list(tqqq_audit[0].keys()))

    def special_audit(ticker: str) -> dict[str, object]:
        row = by_ticker[ticker]
        return {
            "ticker": ticker, "repaired_r4_bucket": row["repaired_r4_policy_bucket"],
            "local_price_row_count": row["listing_age_price_rows"],
            "price_available": row.get("price_available", "FALSE"),
            "listing_reference_value": row["listing_reference_value"],
            "listing_age_status": row["listing_age_status"],
            "score_status": row["r4_score_status"], "score_scope": row["r4_score_scope"],
            "in_r4_top50": tf(ticker in top_set), "classification_reason": row["r4_classification_reason"],
            "research_only": "TRUE",
        }
    dram_audit = [special_audit("DRAM")]
    spcx_audit = [special_audit("SPCX")]
    write_csv(out / DRAM_NAME, dram_audit, list(dram_audit[0].keys()))
    write_csv(out / SPCX_NAME, spcx_audit, list(spcx_audit[0].keys()))

    after = protected_hashes(root)
    a0_modified = changed(before["a0"], after["a0"])
    official_modified = changed(before["official"], after["official"])
    real_modified = changed(before["real_book"], after["real_book"])
    broker_modified = changed(before["broker"], after["broker"])
    lineage_sources = [
        ("r3_newly_listed_ledger", root / R3_LEDGER_REL),
        ("r3_newly_listed_board", root / R3_BOARD_REL),
        ("r3_forced_diagnostic", root / R3_FORCED_REL),
        ("listing_reference_config", root / REFERENCE_REL),
        ("r2_repaired_momentum_ledger", root / R2_LEDGER_REL),
        ("a0_canonical_control", root / A0_REL),
    ]
    lineage = [{
        "source_role": role, "source_path": rel(root, path), "exists": tf(path.is_file()),
        "row_count": row_count(path), "status": "READ_ONLY_UNMODIFIED",
        "a0_modified": tf(a0_modified), "official_mutation_detected": tf(official_modified),
        "research_only": "TRUE", "notes": "Listing references classify short histories only; they do not grant score eligibility.",
    } for role, path in lineage_sources]
    write_csv(out / LINEAGE_NAME, lineage, ["source_role", "source_path", "exists", "row_count", "status", "a0_modified", "official_mutation_detected", "research_only", "notes"])

    local_gap_misclassified = sum(
        row["listing_age_status"] in {"ESTABLISHED_DATE_UNKNOWN", "ESTABLISHED_LISTING_REFERENCE"}
        and int(clean(row.get("listing_age_price_rows")) or "0") < 60
        and row["repaired_r4_policy_bucket"] in {"TRUE_IPO_EARLY_WATCH", "TRUE_NEWLY_LISTED_LIMITED_HISTORY"}
        for row in repaired
    )
    forced_only = [row for row in repaired if tf(row.get("entered_by_forced_audit_only")) == "TRUE"]
    forced_only_scored = sum(clean(row.get("r4_score_scope")) not in {"", "UNSCORED"} for row in forced_only)
    forced_only_top50 = sum(clean(row.get("ticker")).upper() in top_set for row in forced_only)
    hardcoded = forced_only_scored + forced_only_top50
    limited_policy_violation = sum(
        row["repaired_r4_policy_bucket"] != "FULL_HISTORY_SCORING"
        and tf(row.get("full_history_score_available")) == "TRUE"
        for row in repaired
    )
    forbidden = a0_modified or official_modified or real_modified or broker_modified
    bucket_counts = Counter(row["repaired_r4_policy_bucket"] for row in repaired)
    r3_summary = json.loads((root / R3_SUMMARY_REL).read_text(encoding="utf-8"))
    if forbidden:
        final, decision = FAIL_MUTATION, "STOP_AND_RESTORE_FORBIDDEN_MUTATION"
    elif hardcoded:
        final, decision = FAIL_HARDCODED, "REPAIR_FORCED_INCLUSION_LOGIC"
    elif local_gap_misclassified or tqqq["repaired_r4_policy_bucket"] == "TRUE_IPO_EARLY_WATCH":
        final, decision = FAIL_MISCLASSIFIED, "REPAIR_LISTING_AGE_CLASSIFICATION_BEFORE_ABCD"
    elif by_ticker["DRAM"]["repaired_r4_policy_bucket"] == "LOCAL_PRICE_NOT_FOUND" or by_ticker["SPCX"]["repaired_r4_policy_bucket"] == "LOCAL_PRICE_NOT_FOUND":
        final, decision = PARTIAL_STATUS, "READY_FOR_ABCD_WITH_REMAINING_LOCAL_PRICE_DATA_WARN"
    else:
        final, decision = PASS_STATUS, "LISTING_AGE_POLICY_READY_FOR_V21_059_ABCD"
    summary = {
        "FINAL_STATUS": final, "DECISION": decision, "stage_id": STAGE_ID, "research_only": True,
        "r3_ipo_watch_count": r3_summary["r3_ipo_watch_count"],
        "r4_true_ipo_watch_count": bucket_counts["TRUE_IPO_EARLY_WATCH"],
        "r4_true_newly_listed_limited_history_count": bucket_counts["TRUE_NEWLY_LISTED_LIMITED_HISTORY"],
        "r4_local_history_gap_not_newly_listed_count": bucket_counts["LOCAL_HISTORY_GAP_NOT_NEWLY_LISTED"],
        "r4_local_price_not_found_count": bucket_counts["LOCAL_PRICE_NOT_FOUND"],
        "tqqq_previous_bucket": tqqq_audit[0]["previous_r3_bucket"],
        "tqqq_repaired_bucket": tqqq["repaired_r4_policy_bucket"],
        "tqqq_ipo_watch_removed": tqqq["ipo_watch_removed"] == "TRUE",
        "dram_repaired_bucket": by_ticker["DRAM"]["repaired_r4_policy_bucket"],
        "dram_score_status": by_ticker["DRAM"]["r4_score_status"],
        "spcx_repaired_bucket": by_ticker["SPCX"]["repaired_r4_policy_bucket"],
        "spcx_score_status": by_ticker["SPCX"]["r4_score_status"],
        "hardcoded_inclusion_violation_count": hardcoded,
        "forced_audit_only_scored_count": forced_only_scored,
        "forced_audit_only_top50_count": forced_only_top50,
        "limited_history_policy_violation_count": limited_policy_violation,
        "local_history_gap_misclassified_as_ipo_count": local_gap_misclassified,
        "a0_modified": a0_modified, "official_mutation_detected": official_modified,
        "real_book_mutation_detected": real_modified, "broker_mutation_detected": broker_modified,
        "next_recommended_stage": "V21.059_ABCD_EXPERIMENT_HARNESS" if final in {PASS_STATUS, PARTIAL_STATUS} else "REPAIR_V21_058_R4_LISTING_POLICY",
    }
    write_json(out / SUMMARY_NAME, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    summary = run_stage(args.root)
    print(json.dumps(summary, indent=2))
    return 1 if clean(summary["FINAL_STATUS"]).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
