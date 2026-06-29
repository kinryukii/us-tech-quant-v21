#!/usr/bin/env python
"""Research-only D maturity wait-continuation scheduling gate."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd


STAGE_ID = "V21.066"
SOURCE_VARIANT = "D_WEIGHT_OPTIMIZED_R1"
OUT_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/"
    "v21_066_maturity_wait_continuation_after_price_refresh"
)
SUMMARY_NAME = "V21_066_D_WAIT_CONTINUATION_SUMMARY.csv"
DETAIL_NAME = "V21_066_D_WAIT_CONTINUATION_DETAIL.csv"
AUDIT_NAME = "V21_066_D_WAIT_CONTINUATION_AUDIT.json"
VALIDATION_NAME = "V21_066_D_WAIT_CONTINUATION_VALIDATION.json"

WAIT = "WAIT_CONTINUATION_CONFIRMED"
RECHECK = "RECHECK_ON_OR_AFTER_NEXT_TARGET_DATE"
NO_REFRESH = "PRICE_REFRESH_NOT_NEEDED_YET"
UNEXPECTED = "UNEXPECTED_MATURITY_READY_REVIEW"
INCONSISTENT = "INPUT_CONTRACT_INCONSISTENT"
STATES = {WAIT, RECHECK, NO_REFRESH, UNEXPECTED, INCONSISTENT}
STATUS_MAP = {
    WAIT: (
        "PARTIAL_PASS_V21_066_D_WAIT_CONTINUATION_CONFIRMED",
        "CONTINUE_WAITING_FOR_D_TARGET_MATURITY_DATE",
        "V21_067_D_TARGET_DATE_RECHECK_GATE",
    ),
    RECHECK: (
        "PARTIAL_PASS_V21_066_D_RECHECK_SCHEDULED_ON_OR_AFTER_TARGET_DATE",
        "RECHECK_D_MATURITY_ON_OR_AFTER_NEXT_TARGET_DATE",
        "V21_067_D_TARGET_DATE_RECHECK_GATE",
    ),
    NO_REFRESH: (
        "PARTIAL_PASS_V21_066_D_PRICE_REFRESH_NOT_NEEDED_YET",
        "SUPPRESS_REPEATED_PRICE_REFRESH_WAIT_FOR_TARGET_MATURITY",
        "V21_067_D_TARGET_DATE_RECHECK_GATE",
    ),
    UNEXPECTED: (
        "PARTIAL_PASS_V21_066_D_UNEXPECTED_MATURITY_READY_REVIEW",
        "REVIEW_D_MATURITY_COMPUTE_READINESS_BEFORE_NEXT_STAGE",
        "V21_067_D_MATURITY_COMPUTE_READINESS_REVIEW",
    ),
    INCONSISTENT: (
        "BLOCKED_V21_066_INPUT_CONTRACT_INCONSISTENT",
        "INPUT_CONTRACT_REVIEW_REQUIRED_BEFORE_D_WAIT_CONTINUATION",
        "V21_067_D_WAIT_CONTINUATION_INPUT_REPAIR",
    ),
}
DETAIL_FIELDS = [
    "observation_id", "source_stage", "source_variant", "as_of_date",
    "ticker", "rank", "rank_bucket", "forward_window",
    "target_maturity_date", "latest_available_price_date",
    "current_maturity_status", "target_date_reached",
    "days_until_target_maturity", "trading_sessions_until_target_maturity",
    "price_date_warning", "wait_continuation_state",
    "maturity_compute_allowed", "abcd_comparison_allowed", "research_only",
]


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def truth(value: object) -> bool:
    return clean(value).upper() == "TRUE"


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def discover_v21_065(root: Path) -> tuple[Path, Path, dict[str, str]]:
    base = root / "outputs/v21/experiments/momentum_dynamic"
    candidates = sorted(
        base.rglob("V21_065_PRICE_REFRESH_RECHECK_SUMMARY.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for summary_path in candidates:
        rows = read_csv(summary_path)
        detail = summary_path.parent / "V21_065_PRICE_REFRESH_RECHECK_DETAIL.csv"
        if (
            len(rows) == 1
            and rows[0].get("source_variant") == SOURCE_VARIANT
            and rows[0].get("post_refresh_maturity_state")
            == "PRICE_REFRESH_COMPLETED_STILL_PENDING"
            and truth(rows[0].get("research_only"))
            and not truth(rows[0].get("official_mutation"))
            and detail.is_file()
        ):
            return summary_path, detail, rows[0]
    raise RuntimeError("No valid V21.065 D wait-continuation source found.")


def discover_latest_d_price_date(
    root: Path, tickers: set[str]
) -> tuple[str, list[str]]:
    candidates = []
    for base in (
        root / "inputs/v21/historical_ohlcv_cache",
        root / "outputs/v20/price_history",
    ):
        if base.exists():
            candidates.extend(base.glob("*OHLCV*.csv"))
    latest = ""
    used = []
    for path in sorted(set(candidates)):
        try:
            columns = set(pd.read_csv(path, nrows=0).columns)
            ticker_col = "ticker" if "ticker" in columns else "symbol"
            date_col = "as_of_date" if "as_of_date" in columns else "date"
            if ticker_col not in columns or date_col not in columns:
                continue
            frame = pd.read_csv(path, usecols=[ticker_col, date_col], low_memory=False)
        except (OSError, ValueError):
            continue
        frame[ticker_col] = frame[ticker_col].astype(str).str.upper().str.strip()
        dates = frame.loc[
            frame[ticker_col].isin(tickers), date_col
        ].astype(str).str.slice(0, 10)
        if not dates.empty:
            latest = max(latest, clean(dates.max()))
            used.append(relative(root, path))
    return latest, used


def protected_paths(root: Path, v65_dir: Path) -> list[Path]:
    paths = list(v65_dir.glob("V21_065_*"))
    base = root / "outputs/v21/experiments/momentum_dynamic"
    for pattern in (
        "V21_059_R1_A1_*", "V21_059_R1_B_*", "V21_059_R1_C_*",
        "V21_060_R1_ABCD_*", "V21_061_R1_*", "V21_062_R1_*",
        "d_weight_optimized/V21_060_R5_*",
        "d_weight_optimized/v21_062_daily_monitoring/V21_062_D_*",
        "d_weight_optimized/v21_063_maturity_refresh_and_abcd_comparison_readiness/V21_063_*",
        "d_weight_optimized/v21_064_daily_maturity_continuation_or_price_refresh_check/V21_064_*",
    ):
        paths.extend(base.glob(pattern))
    paths.extend([
        root / "outputs/v21/experiments/version_control/"
        "V21_056_R2_A0_CANONICAL_CONTROL_VIEW.csv",
        root / "outputs/v21/experiments/version_control/"
        "V21_056_R1_A0_LEDGER_SNAPSHOT.csv",
    ])
    output_dir = (root / OUT_REL).resolve()
    for scan_root in (root / "outputs", root / "data"):
        if not scan_root.exists():
            continue
        for path in scan_root.rglob("*"):
            if not path.is_file() or output_dir in path.resolve().parents:
                continue
            text = path.as_posix().lower()
            if (
                ("official" in text and any(
                    token in text
                    for token in ("rank", "weight", "recommend", "allocation")
                ))
                or "real_book" in text or "realbook" in text or "broker" in text
            ):
                paths.append(path)
    return sorted({path.resolve() for path in paths if path.is_file()})


def run_stage(root: Path) -> dict[str, object]:
    root = root.resolve()
    output_dir = root / OUT_REL
    output_dir.mkdir(parents=True, exist_ok=True)
    source_summary_path, source_detail_path, source_summary = discover_v21_065(root)
    source_rows = read_csv(source_detail_path)
    protected = protected_paths(root, source_summary_path.parent)
    before = {relative(root, path): sha256(path) for path in protected}

    errors = []
    ids = [clean(row.get("observation_id")) for row in source_rows]
    duplicate_count = len(ids) - len(set(ids))
    expected = int(source_summary.get("total_rows", 200))
    counts = Counter(clean(row.get("post_refresh_maturity_status")) for row in source_rows)
    warnings = sum(truth(row.get("price_date_warning_after")) for row in source_rows)
    if len(source_rows) != expected:
        errors.append("SOURCE_ROW_COUNT_MISMATCH")
    if duplicate_count or any(not observation_id for observation_id in ids):
        errors.append("SOURCE_OBSERVATION_ID_FAILURE")
    if (
        counts["PENDING"] != int(source_summary.get("post_refresh_pending_count", 0))
        or counts["MATURED"] != int(source_summary.get("post_refresh_matured_count", 0))
        or counts["PRICE_MISSING"] != int(
            source_summary.get("post_refresh_price_missing_count", 0)
        )
    ):
        errors.append("SOURCE_MATURITY_ACCOUNTING_MISMATCH")
    if counts["MATURED"] or counts["PRICE_MISSING"]:
        errors.append("SOURCE_NOT_FULLY_PENDING")
    if warnings != int(source_summary.get("post_refresh_price_warning_count", 0)):
        errors.append("SOURCE_WARNING_COUNT_MISMATCH")
    if not truth(source_summary.get("warning_reconciled")):
        errors.append("SOURCE_WARNINGS_NOT_RECONCILED")
    if truth(source_summary.get("price_gap_detected_after")):
        errors.append("SOURCE_PRICE_GAP_TRUE")
    if truth(source_summary.get("maturity_compute_ready")):
        errors.append("SOURCE_MATURITY_COMPUTE_READY_TRUE")
    if truth(source_summary.get("official_mutation")):
        errors.append("SOURCE_OFFICIAL_MUTATION_TRUE")
    if not truth(source_summary.get("research_only")):
        errors.append("SOURCE_RESEARCH_ONLY_FALSE")

    tickers = {clean(row.get("ticker")).upper() for row in source_rows}
    discovered_latest, price_sources = discover_latest_d_price_date(root, tickers)
    source_latest = clean(source_summary.get("post_refresh_latest_usable_price_date"))
    latest = max(discovered_latest, source_latest)
    targets = sorted(
        clean(row.get("target_maturity_date"))
        for row in source_rows if clean(row.get("target_maturity_date"))
    )
    reached_count = sum(target <= latest for target in targets)
    future_targets = [target for target in targets if target > latest]
    next_target = min(future_targets) if future_targets else ""
    earliest_target = min(targets) if targets else ""
    latest_target = max(targets) if targets else ""
    days_until_next = (
        (date.fromisoformat(next_target) - date.fromisoformat(latest)).days
        if next_target and latest else ""
    )
    provider_recent = source_summary.get("provider_refresh_status") in {
        "EXECUTED", "SKIPPED_VALIDATED_LATEST"
    }
    internally_consistent = not errors

    if not internally_consistent:
        state = INCONSISTENT
    elif reached_count > 0 and not truth(source_summary.get("maturity_compute_ready")):
        state = UNEXPECTED
    elif next_target and latest < next_target:
        state = RECHECK
    elif provider_recent and earliest_target and latest < earliest_target:
        state = NO_REFRESH
    else:
        state = WAIT

    before_target = bool(next_target and latest < next_target)
    repeated_refresh_suppressed = bool(provider_recent and before_target)
    maturity_compute_allowed = bool(state == UNEXPECTED)
    abcd_allowed = bool(counts["MATURED"] > 0 and maturity_compute_allowed)
    final_status, decision, next_stage = STATUS_MAP[state]
    details = []
    for row in source_rows:
        target = clean(row.get("target_maturity_date"))
        target_reached = bool(target and target <= latest)
        days_until = (
            max(0, (date.fromisoformat(target) - date.fromisoformat(latest)).days)
            if target and latest else ""
        )
        details.append({
            "observation_id": clean(row.get("observation_id")),
            "source_stage": clean(row.get("source_stage")),
            "source_variant": clean(row.get("source_variant")),
            "as_of_date": clean(row.get("as_of_date")),
            "ticker": clean(row.get("ticker")).upper(),
            "rank": clean(row.get("rank")),
            "rank_bucket": clean(row.get("rank_bucket")),
            "forward_window": clean(row.get("forward_window")),
            "target_maturity_date": target,
            "latest_available_price_date": latest,
            "current_maturity_status": clean(row.get("post_refresh_maturity_status")),
            "target_date_reached": target_reached,
            "days_until_target_maturity": days_until,
            "trading_sessions_until_target_maturity": "",
            "price_date_warning": truth(row.get("price_date_warning_after")),
            "wait_continuation_state": state,
            "maturity_compute_allowed": maturity_compute_allowed,
            "abcd_comparison_allowed": abcd_allowed,
            "research_only": True,
        })

    summary = {
        "final_status": final_status,
        "decision": decision,
        "source_stage": "V21.065",
        "source_variant": SOURCE_VARIANT,
        "total_rows": len(details),
        "unique_observation_ids": len(set(ids)),
        "duplicate_observation_count": duplicate_count,
        "pending_count": counts["PENDING"],
        "matured_count": counts["MATURED"],
        "price_missing_count": counts["PRICE_MISSING"],
        "price_date_warning_count": warnings,
        "latest_available_price_date": latest,
        "earliest_target_maturity_date": earliest_target,
        "next_target_maturity_date": next_target,
        "latest_target_maturity_date": latest_target,
        "target_dates_reached_count": reached_count,
        "target_dates_not_reached_count": len(targets) - reached_count,
        "days_until_next_target_maturity": days_until_next,
        "trading_sessions_until_next_target_maturity": "",
        "wait_continuation_state": state,
        "price_refresh_needed_now": False,
        "repeated_price_refresh_suppressed": repeated_refresh_suppressed,
        "maturity_compute_allowed": maturity_compute_allowed,
        "abcd_comparison_allowed": abcd_allowed,
        "preferred_policy_selected": False,
        "recommendation_allowed": False,
        "trade_action_created": False,
        "broker_execution_supported": False,
        "official_mutation": False,
        "research_only": True,
        "protected_outputs_modified": False,
        "recommended_next_stage": next_stage,
    }
    write_csv(output_dir / DETAIL_NAME, details, DETAIL_FIELDS)
    write_csv(output_dir / SUMMARY_NAME, [summary], list(summary.keys()))

    after = {path: sha256(root / path) for path in before}
    changed = sorted(path for path in before if before[path] != after[path])
    validation = {
        "stage_id": STAGE_ID,
        "source_summary_path": relative(root, source_summary_path),
        "source_detail_path": relative(root, source_detail_path),
        "observation_ids_preserved": [row["observation_id"] for row in details] == ids,
        "observation_ids_unique": duplicate_count == 0,
        "maturity_accounting_valid": sum(counts.values()) == len(details),
        "maturity_compute_false_before_next_target": (
            not before_target or not maturity_compute_allowed
        ),
        "abcd_comparison_false_with_zero_matured": (
            counts["MATURED"] > 0 or not abcd_allowed
        ),
        "repeated_refresh_suppressed_before_target": (
            not provider_recent or not before_target or repeated_refresh_suppressed
        ),
        "wait_continuation_state_valid": state in STATES,
        "v21_062_outputs_modified": any("V21_062_D_" in path for path in changed),
        "v21_063_outputs_modified": any("V21_063_" in path for path in changed),
        "v21_064_outputs_modified": any("V21_064_" in path for path in changed),
        "v21_065_outputs_modified": any("V21_065_" in path for path in changed),
        "a0_a1_b_c_d_source_outputs_modified": bool(changed),
        "protected_outputs_modified": changed,
        "preferred_policy_selected": False,
        "recommendation_allowed": False,
        "trade_action_created": False,
        "broker_execution_supported": False,
        "official_mutation": False,
        "research_only": True,
        "contract_errors": errors,
    }
    audit = {
        "stage_id": STAGE_ID,
        "run_contract": "READ_ONLY_WAIT_CONTINUATION_AND_RECHECK_SCHEDULING",
        "price_sources_checked": price_sources,
        "source_latest_usable_price_date": source_latest,
        "rediscovered_latest_d_price_date": discovered_latest,
        "selected_latest_available_price_date": latest,
        "trading_calendar_status": "APPROVED_TRADING_CALENDAR_NOT_AVAILABLE",
        "trading_session_distance_reason": (
            "NULL_NOT_APPROXIMATED_WITH_WEEKDAYS_WITHOUT_APPROVED_CALENDAR"
        ),
        "state_priority": [
            INCONSISTENT, UNEXPECTED, RECHECK, NO_REFRESH, WAIT
        ],
        "protected_before_sha256": before,
        "protected_after_sha256": after,
        "protected_outputs_modified": changed,
        "guardrails": {
            "alpha_evaluated": False,
            "abcd_performance_compared": False,
            "preferred_policy_selected": False,
            "weights_optimized": False,
            "trade_actions_created": False,
            "broker_execution_triggered": False,
            "future_returns_fabricated": False,
        },
        "research_only": True,
    }
    write_json(output_dir / AUDIT_NAME, audit)
    write_json(output_dir / VALIDATION_NAME, validation)

    final_after = {path: sha256(root / path) for path in before}
    final_changed = sorted(
        path for path in before if before[path] != final_after[path]
    )
    if final_changed:
        summary["final_status"] = "BLOCKED_V21_066_PROTECTED_OUTPUT_MUTATION"
        summary["decision"] = "RESTORE_PROTECTED_OUTPUTS_BEFORE_CONTINUING"
        summary["official_mutation"] = True
        summary["protected_outputs_modified"] = True
        validation["protected_outputs_modified"] = final_changed
        validation["a0_a1_b_c_d_source_outputs_modified"] = True
        write_csv(output_dir / SUMMARY_NAME, [summary], list(summary.keys()))
        write_json(output_dir / VALIDATION_NAME, validation)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    summary = run_stage(parser.parse_args().root)
    print(f"FINAL_STATUS={summary['final_status']}")
    print(f"DECISION={summary['decision']}")
    print(f"TOTAL_ROWS={summary['total_rows']}")
    print(
        "PENDING/MATURED/PRICE_MISSING="
        f"{summary['pending_count']}/{summary['matured_count']}/"
        f"{summary['price_missing_count']}"
    )
    print(f"LATEST_AVAILABLE_PRICE_DATE={summary['latest_available_price_date']}")
    print(f"NEXT_TARGET_MATURITY_DATE={summary['next_target_maturity_date']}")
    print(f"DAYS_UNTIL_NEXT_TARGET_MATURITY={summary['days_until_next_target_maturity']}")
    print(
        "TRADING_SESSIONS_UNTIL_NEXT_TARGET_MATURITY="
        f"{summary['trading_sessions_until_next_target_maturity'] or 'NULL'}"
    )
    print(f"WAIT_CONTINUATION_STATE={summary['wait_continuation_state']}")
    print(f"PRICE_REFRESH_NEEDED_NOW={str(summary['price_refresh_needed_now']).upper()}")
    print(
        "REPEATED_PRICE_REFRESH_SUPPRESSED="
        f"{str(summary['repeated_price_refresh_suppressed']).upper()}"
    )
    print(f"MATURITY_COMPUTE_ALLOWED={str(summary['maturity_compute_allowed']).upper()}")
    print(f"ABCD_COMPARISON_ALLOWED={str(summary['abcd_comparison_allowed']).upper()}")
    print(f"OFFICIAL_MUTATION={str(summary['official_mutation']).upper()}")
    print(f"RESEARCH_ONLY={str(summary['research_only']).upper()}")
    print(f"NEXT_RECOMMENDED_STAGE={summary['recommended_next_stage']}")
    return 1 if summary["final_status"].startswith("BLOCKED_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
