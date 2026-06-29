#!/usr/bin/env python
"""Approved price refresh/alignment followed by research-only D maturity recheck."""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import os
import subprocess
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd


STAGE_ID = "V21.065"
SOURCE_VARIANT = "D_WEIGHT_OPTIMIZED_R1"
OUT_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/"
    "v21_065_price_refresh_then_d_maturity_recheck"
)
SUMMARY_NAME = "V21_065_PRICE_REFRESH_RECHECK_SUMMARY.csv"
DETAIL_NAME = "V21_065_PRICE_REFRESH_RECHECK_DETAIL.csv"
AUDIT_NAME = "V21_065_PRICE_REFRESH_AUDIT.json"
VALIDATION_NAME = "V21_065_PRICE_REFRESH_VALIDATION.json"

V21_CACHE_REL = Path(
    "inputs/v21/historical_ohlcv_cache/"
    "V21_037_R1_HISTORICAL_OHLCV_CACHE.csv"
)
APPROVED_REFRESH_REL = Path(
    "scripts/v20/v20_199d_approved_historical_price_refresh.py"
)
REFRESH_RESULT_REL = Path(
    "outputs/v20/price_history/V20_199D_HISTORICAL_PRICE_REFRESH_RESULT.csv"
)
REFRESH_TICKER_REL = Path(
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
)
REFRESH_BENCHMARK_REL = Path(
    "outputs/v20/price_history/V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"
)
REFRESH_FAILURE_REL = Path(
    "outputs/v20/price_history/V20_199D_PRICE_REFRESH_FAILURES.csv"
)

COMPLETED_PENDING = "PRICE_REFRESH_COMPLETED_STILL_PENDING"
UNAVAILABLE_PENDING = "PRICE_REFRESH_UNAVAILABLE_STILL_PENDING"
FAILED = "PRICE_REFRESH_FAILED_REVIEW_NEEDED"
PARTIAL_READY = "PRICE_REFRESH_COMPLETED_PARTIAL_MATURITY_READY"
PRICE_GAP = "PRICE_GAP_AFTER_REFRESH_REVIEW_NEEDED"
STATES = {
    COMPLETED_PENDING, UNAVAILABLE_PENDING, FAILED, PARTIAL_READY, PRICE_GAP
}
STATUS_MAP = {
    COMPLETED_PENDING: (
        "PARTIAL_PASS_V21_065_PRICE_REFRESH_COMPLETED_D_STILL_PENDING_MATURITY",
        "PRICE_REFRESH_COMPLETE_CONTINUE_D_MATURITY_WAIT",
        "V21_066_D_MATURITY_WAIT_CONTINUATION_AFTER_PRICE_REFRESH",
    ),
    UNAVAILABLE_PENDING: (
        "PARTIAL_PASS_V21_065_PRICE_REFRESH_UNAVAILABLE_D_STILL_PENDING_MATURITY",
        "PRICE_REFRESH_UNAVAILABLE_CONTINUE_D_MATURITY_WAIT_WITH_DATA_WARN",
        "V21_066_D_PRICE_SOURCE_AVAILABILITY_AUDIT_OR_WAIT",
    ),
    FAILED: (
        "BLOCKED_V21_065_PRICE_REFRESH_FAILED_REVIEW_NEEDED",
        "PRICE_REFRESH_FAILURE_REVIEW_REQUIRED_BEFORE_D_MATURITY_RECHECK",
        "V21_066_PRICE_REFRESH_FAILURE_REPAIR",
    ),
    PARTIAL_READY: (
        "PARTIAL_PASS_V21_065_PRICE_REFRESH_COMPLETED_D_PARTIAL_MATURITY_READY",
        "D_MATURITY_COMPUTE_BRIDGE_READY_REVIEW_ONLY",
        "V21_066_D_MATURITY_COMPUTE_BRIDGE_REVIEW_ONLY",
    ),
    PRICE_GAP: (
        "PARTIAL_PASS_V21_065_PRICE_GAP_AFTER_REFRESH_REVIEW_NEEDED",
        "PRICE_GAP_REVIEW_REQUIRED_BEFORE_D_MATURITY_COMPUTE",
        "V21_066_D_PRICE_GAP_REPAIR_OR_MISSING_PRICE_AUDIT",
    ),
}
DETAIL_FIELDS = [
    "observation_id", "source_stage", "source_variant", "as_of_date",
    "ticker", "rank", "rank_bucket", "forward_window",
    "target_maturity_date", "pre_refresh_latest_price_date",
    "post_refresh_latest_price_date", "pre_refresh_maturity_status",
    "post_refresh_maturity_status", "target_date_reached_after_refresh",
    "price_available_for_maturity", "realized_forward_return",
    "price_date_warning_before", "price_date_warning_after",
    "warning_reconciliation_reason", "research_only",
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


def discover_v21_064(root: Path) -> tuple[Path, Path, dict[str, str]]:
    base = root / "outputs/v21/experiments/momentum_dynamic"
    candidates = sorted(
        base.rglob("V21_064_D_MATURITY_CONTINUATION_CHECK_SUMMARY.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for summary_path in candidates:
        rows = read_csv(summary_path)
        detail = summary_path.parent / (
            "V21_064_D_MATURITY_CONTINUATION_CHECK_DETAIL.csv"
        )
        if (
            len(rows) == 1
            and rows[0].get("continuation_state")
            == "PRICE_REFRESH_CHECK_RECOMMENDED"
            and truth(rows[0].get("price_refresh_recommended"))
            and not truth(rows[0].get("official_mutation"))
            and truth(rows[0].get("research_only"))
            and detail.is_file()
        ):
            return summary_path, detail, rows[0]
    raise RuntimeError("No valid V21.064 price-refresh-check output found.")


def discover_v21_063(root: Path) -> tuple[Path, Path, dict[str, str]]:
    base = root / "outputs/v21/experiments/momentum_dynamic"
    candidates = sorted(
        base.rglob("V21_063_D_MATURITY_REFRESH_SUMMARY.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for summary_path in candidates:
        rows = read_csv(summary_path)
        ledger = summary_path.parent / "V21_063_D_MATURITY_REFRESH_LEDGER.csv"
        if (
            len(rows) == 1
            and rows[0].get("source_variant") == SOURCE_VARIANT
            and truth(rows[0].get("research_only"))
            and not truth(rows[0].get("official_mutation"))
            and ledger.is_file()
        ):
            return summary_path, ledger, rows[0]
    raise RuntimeError("No valid V21.063 D maturity refresh output found.")


def protected_paths(root: Path, v63_dir: Path, v64_dir: Path) -> list[Path]:
    paths = list(v63_dir.glob("V21_063_*")) + list(v64_dir.glob("V21_064_*"))
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
    refresh_dir = (root / REFRESH_RESULT_REL).parent.resolve()
    for scan_root in (root / "outputs", root / "data"):
        if not scan_root.exists():
            continue
        for path in scan_root.rglob("*"):
            if (
                not path.is_file()
                or output_dir in path.resolve().parents
                or refresh_dir in path.resolve().parents
            ):
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


def refresh_artifact_hashes(root: Path) -> dict[str, str]:
    directory = (root / REFRESH_RESULT_REL).parent
    return {
        relative(root, path): sha256(path)
        for path in directory.glob("V20_199D_*")
        if path.is_file()
    }


def completed_refresh_today(root: Path) -> bool:
    rows = read_csv(root / REFRESH_RESULT_REL)
    if len(rows) != 1:
        return False
    timestamp = clean(rows[0].get("refresh_timestamp"))
    return (
        rows[0].get("refresh_status") == "REFRESH_COMPLETED_WITH_ROWS"
        and timestamp[:10] == date.today().isoformat()
    )


def execute_approved_refresh(root: Path) -> tuple[str, dict[str, object]]:
    script = root / APPROVED_REFRESH_REL
    if not script.is_file():
        return "UNAVAILABLE", {"reason": "APPROVED_REFRESH_SCRIPT_NOT_FOUND"}
    if completed_refresh_today(root):
        return "SKIPPED_VALIDATED_LATEST", {
            "reason": "SAME_DAY_APPROVED_REFRESH_RESULT_ALREADY_COMPLETED"
        }
    environment = os.environ.copy()
    environment["V20_199D_ENABLE_YFINANCE_REFRESH"] = "TRUE"
    try:
        completed = subprocess.run(
            ["python", str(script)],
            cwd=root,
            env=environment,
            text=True,
            capture_output=True,
            timeout=900,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "FAILED", {"reason": type(exc).__name__, "error": clean(exc)}
    result_rows = read_csv(root / REFRESH_RESULT_REL)
    result = result_rows[0] if len(result_rows) == 1 else {}
    status = (
        "EXECUTED"
        if completed.returncode == 0
        and result.get("refresh_status") == "REFRESH_COMPLETED_WITH_ROWS"
        else "FAILED"
    )
    return status, {
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
        "refresh_result": result,
    }


def normalized_price_frame(path: Path, role: str) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame(columns=["ticker", "date", "price", "role", "source"])
    frame = pd.read_csv(path, low_memory=False)
    ticker_col = "ticker" if "ticker" in frame.columns else "symbol"
    date_col = "as_of_date" if "as_of_date" in frame.columns else "date"
    adjusted = (
        pd.to_numeric(frame["adjusted_close"], errors="coerce")
        if "adjusted_close" in frame.columns else pd.Series(index=frame.index, dtype=float)
    )
    close = pd.to_numeric(frame.get("close"), errors="coerce")
    out = pd.DataFrame({
        "ticker": frame[ticker_col].astype(str).str.upper().str.strip(),
        "date": frame[date_col].astype(str).str.slice(0, 10),
        "price": adjusted.fillna(close),
        "role": role,
        "source": path.as_posix(),
    })
    return out[out["price"].gt(0)]


def load_aligned_prices(
    root: Path, d_tickers: set[str]
) -> tuple[dict[str, tuple[list[str], list[float]]], dict[str, object]]:
    frames = [
        normalized_price_frame(root / V21_CACHE_REL, "MIXED"),
        normalized_price_frame(root / REFRESH_TICKER_REL, "CANDIDATE"),
        normalized_price_frame(root / REFRESH_BENCHMARK_REL, "BENCHMARK"),
    ]
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values(["ticker", "date", "source"])
    combined = combined.drop_duplicates(["ticker", "date"], keep="last")
    prices = {
        ticker: (group["date"].tolist(), group["price"].astype(float).tolist())
        for ticker, group in combined.groupby("ticker", sort=False)
    }
    candidate = combined[combined["ticker"].isin(d_tickers)]
    benchmarks = combined[combined["ticker"].isin({"QQQ", "SPY", "SOXX", "SMH"})]
    missing = sorted(d_tickers - set(candidate["ticker"]))
    ticker_latest = {
        ticker: dates[-1] for ticker, (dates, _) in prices.items()
        if ticker in d_tickers and dates
    }
    metadata = {
        "latest_candidate_price_date": clean(candidate["date"].max()),
        "latest_benchmark_price_date": clean(benchmarks["date"].max()),
        "latest_usable_d_maturity_price_date": clean(candidate["date"].max()),
        "missing_d_tickers": missing,
        "failed_tickers": sorted({
            clean(row.get("symbol")).upper()
            for row in read_csv(root / REFRESH_FAILURE_REL)
            if clean(row.get("symbol"))
        }),
        "d_ticker_latest_dates": ticker_latest,
    }
    return prices, metadata


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


def recheck_rows(
    source_rows: list[dict[str, str]],
    prices: dict[str, tuple[list[str], list[float]]],
    pre_latest: str,
    post_latest: str,
) -> list[dict[str, object]]:
    output = []
    for source in source_rows:
        ticker = clean(source.get("ticker")).upper()
        as_of = clean(source.get("as_of_date"))
        target = clean(source.get("target_maturity_date"))
        warning_before = truth(source.get("price_date_warning"))
        warning_after = warning_before
        reason = "PRESERVED_FROM_V21_063"
        realized = ""
        reached = bool(target and target <= post_latest)
        start = price_on_or_after(prices, ticker, as_of, post_latest) if reached else None
        end = price_on_or_after(prices, ticker, target, post_latest) if reached else None
        if not reached:
            status = "PENDING"
            available = False
        elif start and end:
            status = "MATURED"
            available = True
            realized = f"{end[1] / start[1] - 1:.10f}"
        else:
            status = "PRICE_MISSING"
            available = False
            warning_after = True
            reason = "TARGET_REACHED_REQUIRED_START_OR_END_PRICE_MISSING"
        output.append({
            "observation_id": clean(source.get("observation_id")),
            "source_stage": clean(source.get("source_stage")),
            "source_variant": clean(source.get("source_variant")),
            "as_of_date": as_of,
            "ticker": ticker,
            "rank": clean(source.get("rank")),
            "rank_bucket": clean(source.get("rank_bucket")),
            "forward_window": clean(source.get("forward_window")),
            "target_maturity_date": target,
            "pre_refresh_latest_price_date": pre_latest,
            "post_refresh_latest_price_date": post_latest,
            "pre_refresh_maturity_status": clean(source.get("refreshed_maturity_status")),
            "post_refresh_maturity_status": status,
            "target_date_reached_after_refresh": reached,
            "price_available_for_maturity": available,
            "realized_forward_return": realized,
            "price_date_warning_before": warning_before,
            "price_date_warning_after": warning_after,
            "warning_reconciliation_reason": reason,
            "research_only": True,
        })
    return output


def run_stage(root: Path) -> dict[str, object]:
    root = root.resolve()
    output_dir = root / OUT_REL
    output_dir.mkdir(parents=True, exist_ok=True)
    v64_summary_path, v64_detail_path, v64_summary = discover_v21_064(root)
    v63_summary_path, v63_ledger_path, v63_summary = discover_v21_063(root)
    source_rows = read_csv(v63_ledger_path)
    protected = protected_paths(root, v63_summary_path.parent, v64_summary_path.parent)
    before = {relative(root, path): sha256(path) for path in protected}
    refresh_before = refresh_artifact_hashes(root)

    errors = []
    expected = int(v64_summary.get("total_rows", 200))
    source_ids = [clean(row.get("observation_id")) for row in source_rows]
    duplicate_count = len(source_ids) - len(set(source_ids))
    pre_counts = Counter(clean(row.get("refreshed_maturity_status")) for row in source_rows)
    if v64_summary.get("continuation_state") != "PRICE_REFRESH_CHECK_RECOMMENDED":
        errors.append("V21_064_CONTINUATION_STATE_MISMATCH")
    if not truth(v64_summary.get("price_refresh_recommended")):
        errors.append("V21_064_PRICE_REFRESH_NOT_RECOMMENDED")
    if truth(v64_summary.get("price_gap_detected")):
        errors.append("V21_064_PRICE_GAP_ALREADY_DETECTED")
    if truth(v64_summary.get("maturity_compute_ready")):
        errors.append("V21_064_MATURITY_ALREADY_READY")
    if len(source_rows) != expected:
        errors.append("SOURCE_ROW_COUNT_MISMATCH")
    if duplicate_count or any(not observation_id for observation_id in source_ids):
        errors.append("SOURCE_OBSERVATION_ID_FAILURE")
    expected_pre = (
        int(v64_summary.get("pending_count", 0)),
        int(v64_summary.get("matured_count", 0)),
        int(v64_summary.get("price_missing_count", 0)),
    )
    actual_pre = (pre_counts["PENDING"], pre_counts["MATURED"], pre_counts["PRICE_MISSING"])
    if actual_pre != expected_pre:
        errors.append("PRE_REFRESH_MATURITY_ACCOUNTING_MISMATCH")
    if any(not truth(row.get("research_only")) for row in source_rows):
        errors.append("SOURCE_RESEARCH_ONLY_FALSE")
    if truth(v64_summary.get("official_mutation")):
        errors.append("SOURCE_OFFICIAL_MUTATION_TRUE")

    provider_status, provider_audit = execute_approved_refresh(root)
    refresh_after = refresh_artifact_hashes(root)
    d_tickers = {clean(row.get("ticker")).upper() for row in source_rows}
    prices, price_meta = load_aligned_prices(root, d_tickers)
    pre_latest = clean(v64_summary.get("latest_available_price_date"))
    post_latest = clean(price_meta["latest_usable_d_maturity_price_date"]) or pre_latest
    details = recheck_rows(source_rows, prices, pre_latest, post_latest)
    post_counts = Counter(row["post_refresh_maturity_status"] for row in details)
    pre_warning = int(v64_summary.get("price_date_warning_count", 0))
    post_warning = sum(bool(row["price_date_warning_after"]) for row in details)
    warning_reconciled = (
        post_warning == pre_warning
        or all(
            row["warning_reconciliation_reason"]
            for row in details
            if row["price_date_warning_before"] != row["price_date_warning_after"]
        )
    )
    targets = sorted(clean(row.get("target_maturity_date")) for row in source_rows)
    reached = sum(target <= post_latest for target in targets)
    future = [target for target in targets if target > post_latest]
    next_target = min(future) if future else ""
    invalid_returns = sum(
        bool(clean(row["realized_forward_return"]))
        != (row["post_refresh_maturity_status"] == "MATURED")
        for row in details
    )
    zero_filled = sum(
        row["post_refresh_maturity_status"] != "MATURED"
        and clean(row["realized_forward_return"]) in {"0", "0.0"}
        for row in details
    )
    if sum(post_counts.values()) != len(details):
        errors.append("POST_REFRESH_MATURITY_ACCOUNTING_MISMATCH")
    if invalid_returns or zero_filled:
        errors.append("REALIZED_RETURN_CONTRACT_FAILURE")
    if not warning_reconciled:
        errors.append("WARNING_RECONCILIATION_FAILURE")

    if provider_status == "FAILED":
        state = FAILED
    elif post_counts["PRICE_MISSING"] > 0:
        state = PRICE_GAP
    elif post_counts["MATURED"] > 0:
        state = PARTIAL_READY
    elif provider_status in {"EXECUTED", "SKIPPED_VALIDATED_LATEST"}:
        state = COMPLETED_PENDING
    else:
        state = UNAVAILABLE_PENDING
    final_status, decision, next_stage = STATUS_MAP[state]
    if errors:
        final_status = "BLOCKED_V21_065_INPUT_OR_RECHECK_CONTRACT_FAILURE"
        decision = "PRICE_REFRESH_AND_D_RECHECK_INPUT_CONTRACT_REVIEW_REQUIRED"

    summary = {
        "final_status": final_status,
        "decision": decision,
        "source_stage": "V21.064",
        "source_variant": SOURCE_VARIANT,
        "total_rows": len(details),
        "unique_observation_ids": len(set(source_ids)),
        "duplicate_observation_count": duplicate_count,
        "pre_refresh_pending_count": pre_counts["PENDING"],
        "pre_refresh_matured_count": pre_counts["MATURED"],
        "pre_refresh_price_missing_count": pre_counts["PRICE_MISSING"],
        "post_refresh_pending_count": post_counts["PENDING"],
        "post_refresh_matured_count": post_counts["MATURED"],
        "post_refresh_price_missing_count": post_counts["PRICE_MISSING"],
        "pre_refresh_price_warning_count": pre_warning,
        "post_refresh_price_warning_count": post_warning,
        "warning_reconciled": warning_reconciled,
        "provider_refresh_status": provider_status,
        "pre_refresh_latest_price_date": pre_latest,
        "post_refresh_latest_candidate_price_date": price_meta["latest_candidate_price_date"],
        "post_refresh_latest_benchmark_price_date": price_meta["latest_benchmark_price_date"],
        "post_refresh_latest_usable_price_date": post_latest,
        "earliest_target_maturity_date": min(targets) if targets else "",
        "next_target_maturity_date": next_target,
        "target_dates_reached_count_after_refresh": reached,
        "target_dates_not_reached_count_after_refresh": len(targets) - reached,
        "post_refresh_maturity_state": state,
        "price_refresh_recommended_after": provider_status in {"UNAVAILABLE", "FAILED"},
        "price_gap_detected_after": state == PRICE_GAP,
        "maturity_compute_ready": state == PARTIAL_READY,
        "abcd_comparison_allowed": False,
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
    refresh_changed = sorted(
        set(refresh_before) | set(refresh_after),
        key=str,
    )
    refresh_changed = [
        path for path in refresh_changed
        if refresh_before.get(path) != refresh_after.get(path)
    ]
    validation = {
        "stage_id": STAGE_ID,
        "source_v21_064_summary_path": relative(root, v64_summary_path),
        "source_v21_064_detail_path": relative(root, v64_detail_path),
        "source_v21_063_summary_path": relative(root, v63_summary_path),
        "source_v21_063_ledger_path": relative(root, v63_ledger_path),
        "observation_ids_preserved": [row["observation_id"] for row in details] == source_ids,
        "observation_ids_unique": duplicate_count == 0,
        "post_refresh_maturity_accounting_valid": sum(post_counts.values()) == len(details),
        "realized_return_only_for_matured": invalid_returns == 0,
        "missing_return_zero_fill_count": zero_filled,
        "warning_reconciled": warning_reconciled,
        "v21_062_outputs_modified": any("V21_062_D_" in path for path in changed),
        "v21_063_outputs_modified": any("V21_063_" in path for path in changed),
        "v21_064_outputs_modified": any("V21_064_" in path for path in changed),
        "a0_a1_b_c_d_source_outputs_modified": bool(changed),
        "protected_outputs_modified": changed,
        "approved_refresh_artifacts_modified": refresh_changed,
        "post_refresh_maturity_state_valid": state in STATES,
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
        "approved_refresh_mechanism": relative(root, root / APPROVED_REFRESH_REL),
        "provider_refresh_status": provider_status,
        "provider_refresh_execution": provider_audit,
        "approved_refresh_artifacts_before_sha256": refresh_before,
        "approved_refresh_artifacts_after_sha256": refresh_after,
        "approved_refresh_artifacts_modified": refresh_changed,
        "price_alignment_sources": [
            relative(root, root / V21_CACHE_REL),
            relative(root, root / REFRESH_TICKER_REL),
            relative(root, root / REFRESH_BENCHMARK_REL),
        ],
        "failed_tickers": price_meta["failed_tickers"],
        "missing_d_tickers": price_meta["missing_d_tickers"],
        "pre_refresh_warning_count": pre_warning,
        "post_refresh_warning_count": post_warning,
        "warning_reconciliation": (
            "UNCHANGED_PRESERVED"
            if post_warning == pre_warning
            else "ROW_LEVEL_REASONS_RECORDED"
        ),
        "protected_before_sha256": before,
        "protected_after_sha256": after,
        "protected_outputs_modified": changed,
        "guardrails": {
            "alpha_evaluated": False,
            "abcd_performance_compared": False,
            "preferred_policy_selected": False,
            "weights_optimized": False,
            "trade_actions_created": False,
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
        summary["final_status"] = "BLOCKED_V21_065_PROTECTED_OUTPUT_MUTATION"
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
    print(f"PROVIDER_REFRESH_STATUS={summary['provider_refresh_status']}")
    print(f"TOTAL_ROWS={summary['total_rows']}")
    print(
        "PRE_REFRESH_PENDING/MATURED/PRICE_MISSING="
        f"{summary['pre_refresh_pending_count']}/"
        f"{summary['pre_refresh_matured_count']}/"
        f"{summary['pre_refresh_price_missing_count']}"
    )
    print(
        "POST_REFRESH_PENDING/MATURED/PRICE_MISSING="
        f"{summary['post_refresh_pending_count']}/"
        f"{summary['post_refresh_matured_count']}/"
        f"{summary['post_refresh_price_missing_count']}"
    )
    print(f"PRE_REFRESH_LATEST_PRICE_DATE={summary['pre_refresh_latest_price_date']}")
    print(f"POST_REFRESH_LATEST_USABLE_PRICE_DATE={summary['post_refresh_latest_usable_price_date']}")
    print(f"EARLIEST_TARGET_MATURITY_DATE={summary['earliest_target_maturity_date']}")
    print(f"NEXT_TARGET_MATURITY_DATE={summary['next_target_maturity_date']}")
    print(f"POST_REFRESH_MATURITY_STATE={summary['post_refresh_maturity_state']}")
    print(f"PRICE_GAP_DETECTED_AFTER={str(summary['price_gap_detected_after']).upper()}")
    print(f"MATURITY_COMPUTE_READY={str(summary['maturity_compute_ready']).upper()}")
    print(f"OFFICIAL_MUTATION={str(summary['official_mutation']).upper()}")
    print(f"RESEARCH_ONLY={str(summary['research_only']).upper()}")
    print(f"NEXT_RECOMMENDED_STAGE={summary['recommended_next_stage']}")
    return 1 if summary["final_status"].startswith("BLOCKED_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
