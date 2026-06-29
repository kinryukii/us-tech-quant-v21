#!/usr/bin/env python
"""Research-only D maturity continuation and price-refresh checkpoint."""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd


STAGE_ID = "V21.064"
SOURCE_VARIANT = "D_WEIGHT_OPTIMIZED_R1"
OUT_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/"
    "v21_064_daily_maturity_continuation_or_price_refresh_check"
)
SUMMARY_NAME = "V21_064_D_MATURITY_CONTINUATION_CHECK_SUMMARY.csv"
DETAIL_NAME = "V21_064_D_MATURITY_CONTINUATION_CHECK_DETAIL.csv"
AUDIT_NAME = "V21_064_D_PRICE_REFRESH_CHECK_AUDIT.json"
VALIDATION_NAME = "V21_064_D_PRICE_REFRESH_CHECK_VALIDATION.json"

NATURAL_WAIT = "NATURAL_WAIT_FOR_MATURITY"
REFRESH_CHECK = "PRICE_REFRESH_CHECK_RECOMMENDED"
PRICE_GAP = "PRICE_GAP_AFTER_MATURITY_DATE"
COMPUTE_READY = "PARTIAL_MATURITY_NOW_AVAILABLE"
APPROVED_STATES = {NATURAL_WAIT, REFRESH_CHECK, PRICE_GAP, COMPUTE_READY}

STATUS_DECISIONS = {
    NATURAL_WAIT: (
        "PARTIAL_PASS_V21_064_D_NATURAL_WAIT_FOR_MATURITY",
        "CONTINUE_D_DAILY_MATURITY_MONITORING_WAIT_FOR_TARGET_DATES",
        "V21_065_D_DAILY_MATURITY_WAIT_CONTINUATION",
    ),
    REFRESH_CHECK: (
        "PARTIAL_PASS_V21_064_D_PRICE_REFRESH_CHECK_RECOMMENDED",
        "REFRESH_PRICE_DATA_BEFORE_NEXT_D_MATURITY_RECHECK",
        "V21_065_PRICE_REFRESH_THEN_D_MATURITY_RECHECK",
    ),
    PRICE_GAP: (
        "PARTIAL_PASS_V21_064_D_PRICE_GAP_AFTER_MATURITY_DATE_REVIEW_NEEDED",
        "PRICE_GAP_REVIEW_REQUIRED_BEFORE_D_MATURITY_COMPUTE",
        "V21_065_D_PRICE_GAP_REPAIR_OR_MISSING_PRICE_AUDIT",
    ),
    COMPUTE_READY: (
        "PARTIAL_PASS_V21_064_D_MATURITY_COMPUTE_READY_REVIEW_ONLY",
        "D_MATURITY_COMPUTE_READY_NO_ABCD_POLICY_SELECTION",
        "V21_065_D_MATURITY_COMPUTE_BRIDGE_REVIEW_ONLY",
    ),
}

DETAIL_FIELDS = [
    "observation_id", "source_stage", "source_variant", "as_of_date",
    "ticker", "rank", "rank_bucket", "forward_window",
    "target_maturity_date", "latest_available_price_date",
    "current_maturity_status", "target_date_reached",
    "should_be_maturable_now", "price_available_for_maturity",
    "continuation_state", "price_date_warning", "research_only",
]


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def truth(value: object) -> bool:
    return clean(value).upper() == "TRUE"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def read_csv(path: Path) -> list[dict[str, str]]:
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


def discover_v21_063(
    root: Path,
) -> tuple[Path, Path, dict[str, str]]:
    base = root / "outputs/v21/experiments/momentum_dynamic"
    candidates = sorted(
        base.rglob("V21_063_D_MATURITY_REFRESH_SUMMARY.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    rejected = []
    for summary_path in candidates:
        summaries = read_csv(summary_path)
        ledger = summary_path.parent / "V21_063_D_MATURITY_REFRESH_LEDGER.csv"
        if (
            len(summaries) == 1
            and summaries[0].get("source_variant") == SOURCE_VARIANT
            and truth(summaries[0].get("research_only"))
            and not truth(summaries[0].get("official_mutation"))
            and ledger.is_file()
        ):
            return summary_path, ledger, summaries[0]
        rejected.append(relative(root, summary_path))
    raise RuntimeError(
        "No valid V21.063 D maturity refresh summary/ledger pair found. "
        f"Rejected: {rejected}"
    )


def discover_price_data(root: Path) -> Path:
    search_root = root / "inputs/v21"
    candidates = sorted(
        search_root.rglob("*HISTORICAL_OHLCV_CACHE.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    required = {"as_of_date", "ticker", "close", "adjusted_close"}
    for path in candidates:
        try:
            columns = set(pd.read_csv(path, nrows=0).columns)
        except (OSError, ValueError):
            continue
        if required.issubset(columns):
            return path
    raise RuntimeError("No valid repository V21 historical OHLCV cache found.")


def protected_paths(root: Path, v63_dir: Path) -> list[Path]:
    paths = list(v63_dir.glob("V21_063_*"))
    base = root / "outputs/v21/experiments/momentum_dynamic"
    for pattern in (
        "V21_059_R1_A1_*", "V21_059_R1_B_*", "V21_059_R1_C_*",
        "V21_060_R1_ABCD_*", "V21_061_R1_*", "V21_062_R1_*",
        "d_weight_optimized/V21_060_R5_*",
        "d_weight_optimized/v21_062_daily_monitoring/V21_062_D_*",
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
                or "real_book" in text
                or "realbook" in text
                or "broker" in text
            ):
                paths.append(path)
    return sorted({path.resolve() for path in paths if path.is_file()})


def load_prices(
    path: Path,
) -> tuple[dict[str, tuple[list[str], list[float]]], str]:
    frame = pd.read_csv(
        path,
        usecols=["as_of_date", "ticker", "close", "adjusted_close"],
        low_memory=False,
    )
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    frame["as_of_date"] = frame["as_of_date"].astype(str).str.slice(0, 10)
    frame["price"] = pd.to_numeric(
        frame["adjusted_close"], errors="coerce"
    ).fillna(pd.to_numeric(frame["close"], errors="coerce"))
    frame = frame[frame["price"].gt(0)].sort_values(["ticker", "as_of_date"])
    frame = frame.drop_duplicates(["ticker", "as_of_date"], keep="last")
    prices = {
        ticker: (
            group["as_of_date"].tolist(),
            group["price"].astype(float).tolist(),
        )
        for ticker, group in frame.groupby("ticker", sort=False)
    }
    return prices, clean(frame["as_of_date"].max())


def price_on_or_after(
    prices: dict[str, tuple[list[str], list[float]]],
    ticker: str,
    target: str,
    latest: str,
) -> tuple[str, float] | None:
    series = prices.get(ticker)
    if not series:
        return None
    dates, values = series
    index = bisect.bisect_left(dates, target)
    if index >= len(dates) or dates[index] > latest:
        return None
    return dates[index], values[index]


def classify_state(
    rows: list[dict[str, str]],
    prices: dict[str, tuple[list[str], list[float]]],
    latest_price_date: str,
) -> tuple[str, list[dict[str, object]]]:
    probes = []
    for row in rows:
        target = clean(row.get("target_maturity_date"))
        as_of = clean(row.get("as_of_date"))
        ticker = clean(row.get("ticker")).upper()
        reached = bool(target and target <= latest_price_date)
        start = (
            price_on_or_after(prices, ticker, as_of, latest_price_date)
            if reached else None
        )
        end = (
            price_on_or_after(prices, ticker, target, latest_price_date)
            if reached else None
        )
        available = bool(start and end)
        probes.append({
            "row": row,
            "target_reached": reached,
            "price_available": available,
        })

    reached = [probe for probe in probes if probe["target_reached"]]
    reached_missing = [
        probe for probe in reached if not probe["price_available"]
    ]
    reached_available = [
        probe for probe in reached if probe["price_available"]
    ]
    latest_observation_date = max(
        (clean(row.get("as_of_date")) for row in rows), default=""
    )
    all_pending = all(
        clean(row.get("refreshed_maturity_status")) == "PENDING"
        for row in rows
    )
    if reached_missing:
        state = PRICE_GAP
    elif reached_available:
        state = COMPUTE_READY
    elif (
        all_pending
        and latest_observation_date
        and latest_price_date < latest_observation_date
    ):
        state = REFRESH_CHECK
    else:
        state = NATURAL_WAIT

    details = []
    for probe in probes:
        row = probe["row"]
        details.append({
            "observation_id": clean(row.get("observation_id")),
            "source_stage": clean(row.get("source_stage")),
            "source_variant": clean(row.get("source_variant")),
            "as_of_date": clean(row.get("as_of_date")),
            "ticker": clean(row.get("ticker")).upper(),
            "rank": clean(row.get("rank")),
            "rank_bucket": clean(row.get("rank_bucket")),
            "forward_window": clean(row.get("forward_window")),
            "target_maturity_date": clean(row.get("target_maturity_date")),
            "latest_available_price_date": latest_price_date,
            "current_maturity_status": clean(
                row.get("refreshed_maturity_status")
            ),
            "target_date_reached": probe["target_reached"],
            "should_be_maturable_now": probe["target_reached"],
            "price_available_for_maturity": probe["price_available"],
            "continuation_state": state,
            "price_date_warning": truth(row.get("price_date_warning")),
            "research_only": True,
        })
    return state, details


def run_stage(root: Path) -> dict[str, object]:
    root = root.resolve()
    output_dir = root / OUT_REL
    output_dir.mkdir(parents=True, exist_ok=True)
    source_summary_path, source_ledger_path, source_summary = discover_v21_063(
        root
    )
    price_path = discover_price_data(root)
    source_rows = read_csv(source_ledger_path)
    protected = protected_paths(root, source_summary_path.parent)
    before = {relative(root, path): sha256(path) for path in protected}

    errors = []
    source_ids = [clean(row.get("observation_id")) for row in source_rows]
    duplicate_count = len(source_ids) - len(set(source_ids))
    expected = int(source_summary.get("total_rows", 200))
    source_counts = Counter(
        clean(row.get("refreshed_maturity_status")) for row in source_rows
    )
    if not source_rows:
        errors.append("SOURCE_LEDGER_EMPTY")
    if len(source_rows) != expected:
        errors.append("SOURCE_ROW_COUNT_MISMATCH")
    if any(not observation_id for observation_id in source_ids):
        errors.append("EMPTY_OBSERVATION_ID")
    if duplicate_count:
        errors.append("DUPLICATE_OBSERVATION_IDS")
    if sum(source_counts.values()) != len(source_rows):
        errors.append("SOURCE_MATURITY_ACCOUNTING_MISMATCH")
    if source_counts["MATURED"] != int(
        source_summary.get("refreshed_matured_count", 0)
    ):
        errors.append("SOURCE_MATURED_COUNT_MISMATCH")
    if source_counts["MATURED"] != 0:
        errors.append("SOURCE_EXPECTED_ZERO_MATURED_ROWS")
    if any(not truth(row.get("research_only")) for row in source_rows):
        errors.append("SOURCE_RESEARCH_ONLY_FALSE")
    if truth(source_summary.get("official_mutation")):
        errors.append("SOURCE_OFFICIAL_MUTATION_TRUE")

    prices, latest_price_date = load_prices(price_path)
    state, details = classify_state(source_rows, prices, latest_price_date)
    targets = sorted(
        clean(row.get("target_maturity_date"))
        for row in source_rows
        if clean(row.get("target_maturity_date"))
    )
    reached_count = sum(target <= latest_price_date for target in targets)
    not_reached_count = len(targets) - reached_count
    future_targets = [target for target in targets if target > latest_price_date]
    next_target = min(future_targets) if future_targets else ""
    days_until_next = (
        (date.fromisoformat(next_target) - date.fromisoformat(
            latest_price_date
        )).days
        if next_target and latest_price_date else ""
    )
    warning_count = sum(
        truth(row.get("price_date_warning")) for row in source_rows
    )
    source_warning_count = int(
        source_summary.get("price_date_warning_count", 0)
    )
    warning_delta = warning_count - source_warning_count
    if warning_delta:
        errors.append("PRICE_DATE_WARNING_COUNT_NOT_PRESERVED")
    if state not in APPROVED_STATES:
        errors.append("INVALID_CONTINUATION_STATE")

    final_status, decision, next_stage = STATUS_DECISIONS[state]
    if errors:
        final_status = "BLOCKED_V21_064_D_INPUT_OR_CHECK_CONTRACT_FAILURE"
        decision = "BLOCKED_VALIDATE_V21_063_D_AND_PRICE_INPUTS"
    summary = {
        "final_status": final_status,
        "decision": decision,
        "source_stage": "V21.063",
        "source_variant": SOURCE_VARIANT,
        "total_rows": len(source_rows),
        "unique_observation_ids": len(set(source_ids)),
        "duplicate_observation_count": duplicate_count,
        "pending_count": source_counts["PENDING"],
        "matured_count": source_counts["MATURED"],
        "price_missing_count": source_counts["PRICE_MISSING"],
        "price_date_warning_count": warning_count,
        "latest_available_price_date": latest_price_date,
        "earliest_target_maturity_date": min(targets) if targets else "",
        "latest_target_maturity_date": max(targets) if targets else "",
        "target_dates_reached_count": reached_count,
        "target_dates_not_reached_count": not_reached_count,
        "next_target_maturity_date": next_target,
        "days_until_next_maturity": days_until_next,
        "continuation_state": state,
        "price_refresh_recommended": state == REFRESH_CHECK,
        "price_gap_detected": state == PRICE_GAP,
        "maturity_compute_ready": state == COMPUTE_READY,
        "abcd_comparison_allowed": False,
        "preferred_policy_selected": False,
        "recommendation_allowed": False,
        "trade_action_created": False,
        "broker_execution_supported": False,
        "official_mutation": False,
        "research_only": True,
        "protected_outputs_modified": False,
        "next_recommended_stage": next_stage,
    }
    write_csv(output_dir / DETAIL_NAME, details, DETAIL_FIELDS)
    write_csv(output_dir / SUMMARY_NAME, [summary], list(summary.keys()))

    after = {path: sha256(root / path) for path in before}
    changed = sorted(path for path in before if before[path] != after[path])
    validation = {
        "stage_id": STAGE_ID,
        "source_summary_path": relative(root, source_summary_path),
        "source_ledger_path": relative(root, source_ledger_path),
        "price_data_path": relative(root, price_path),
        "source_row_count_expected": expected,
        "source_row_count_actual": len(source_rows),
        "observation_ids_unique": duplicate_count == 0,
        "maturity_accounting_valid": sum(source_counts.values()) == len(source_rows),
        "source_matured_count_consistent": source_counts["MATURED"] == int(
            source_summary.get("refreshed_matured_count", 0)
        ),
        "source_price_date_warning_count": source_warning_count,
        "checkpoint_price_date_warning_count": warning_count,
        "price_date_warning_reconciliation_delta": warning_delta,
        "price_date_warning_preserved": warning_delta == 0,
        "continuation_state_valid": state in APPROVED_STATES,
        "no_realized_return_computed": True,
        "missing_return_zero_fill_count": 0,
        "v21_062_outputs_modified": any("V21_062_D_" in path for path in changed),
        "v21_063_outputs_modified": any("V21_063_" in path for path in changed),
        "a0_a1_b_c_d_source_outputs_modified": bool(changed),
        "protected_outputs_modified": changed,
        "abcd_comparison_allowed": False,
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
        "run_contract": "READ_ONLY_CONTINUATION_OR_PRICE_REFRESH_CHECKPOINT",
        "source_discovery_method": (
            "LATEST_VALID_V21_063_SUMMARY_AND_SIBLING_LEDGER"
        ),
        "price_discovery_method": (
            "LATEST_VALID_V21_HISTORICAL_OHLCV_CACHE_BY_MODIFICATION_TIME"
        ),
        "price_data_path": relative(root, price_path),
        "latest_available_price_date": latest_price_date,
        "latest_d_observation_date": max(
            clean(row.get("as_of_date")) for row in source_rows
        ),
        "protected_before_sha256": before,
        "protected_after_sha256": after,
        "protected_outputs_modified": changed,
        "classification_precedence": [
            PRICE_GAP, COMPUTE_READY, REFRESH_CHECK, NATURAL_WAIT
        ],
        "guardrails": {
            "alpha_evaluated": False,
            "abcd_performance_compared": False,
            "preferred_policy_selected": False,
            "weights_optimized": False,
            "source_observations_modified": False,
            "official_use": False,
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
        summary["final_status"] = "BLOCKED_V21_064_PROTECTED_OUTPUT_MUTATION"
        summary["decision"] = "BLOCKED_RESTORE_PROTECTED_OUTPUTS"
        summary["official_mutation"] = True
        summary["protected_outputs_modified"] = True
        validation["protected_outputs_modified"] = final_changed
        validation["a0_a1_b_c_d_source_outputs_modified"] = True
        write_csv(output_dir / SUMMARY_NAME, [summary], list(summary.keys()))
        write_json(output_dir / VALIDATION_NAME, validation)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    summary = run_stage(parser.parse_args().root)
    print(f"FINAL_STATUS={summary['final_status']}")
    print(f"DECISION={summary['decision']}")
    print(f"TOTAL_ROWS={summary['total_rows']}")
    print(
        "PENDING/MATURED/PRICE_MISSING="
        f"{summary['pending_count']}/{summary['matured_count']}/"
        f"{summary['price_missing_count']}"
    )
    print(f"PRICE_DATE_WARNINGS={summary['price_date_warning_count']}")
    print(
        f"LATEST_AVAILABLE_PRICE_DATE={summary['latest_available_price_date']}"
    )
    print(
        f"EARLIEST_TARGET_MATURITY_DATE="
        f"{summary['earliest_target_maturity_date']}"
    )
    print(f"NEXT_TARGET_MATURITY_DATE={summary['next_target_maturity_date']}")
    print(f"CONTINUATION_STATE={summary['continuation_state']}")
    print(
        f"PRICE_REFRESH_RECOMMENDED="
        f"{str(summary['price_refresh_recommended']).upper()}"
    )
    print(f"PRICE_GAP_DETECTED={str(summary['price_gap_detected']).upper()}")
    print(
        f"MATURITY_COMPUTE_READY="
        f"{str(summary['maturity_compute_ready']).upper()}"
    )
    print(f"OFFICIAL_MUTATION={str(summary['official_mutation']).upper()}")
    print(f"RESEARCH_ONLY={str(summary['research_only']).upper()}")
    print(f"NEXT_RECOMMENDED_STAGE={summary['next_recommended_stage']}")
    return 1 if summary["final_status"].startswith("BLOCKED_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
