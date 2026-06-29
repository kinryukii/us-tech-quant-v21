#!/usr/bin/env python
"""Research-only daily maturity monitoring for D_WEIGHT_OPTIMIZED_R1."""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import pandas as pd


STAGE_ID = "V21.062-INCLUDE-D"
SOURCE_VARIANT = "D_WEIGHT_OPTIMIZED_R1"
OUT_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/"
    "d_weight_optimized/v21_062_daily_monitoring"
)
LEDGER_NAME = "V21_062_D_DAILY_MATURITY_MONITORING_LEDGER.csv"
SUMMARY_NAME = "V21_062_D_DAILY_MATURITY_MONITORING_SUMMARY.csv"
AUDIT_NAME = "V21_062_D_DAILY_MATURITY_MONITORING_AUDIT.json"
VALIDATION_NAME = "V21_062_D_DAILY_MATURITY_MONITORING_VALIDATION.json"
PRICE_REL = Path(
    "inputs/v21/historical_ohlcv_cache/"
    "V21_037_R1_HISTORICAL_OHLCV_CACHE.csv"
)

PENDING_STATUS = "PARTIAL_PASS_V21_062_D_INCLUDED_PENDING_MATURITY"
MATURED_STATUS = "PARTIAL_PASS_V21_062_D_INCLUDED_WITH_MATURED_RESULTS"
PENDING_DECISION = (
    "D_DAILY_MATURITY_MONITORING_READY_WAIT_FOR_FORWARD_RETURN_MATURITY"
)
MATURED_DECISION = (
    "D_DAILY_MATURITY_MONITORING_READY_WITH_MATURED_RESULTS_REVIEW_ONLY"
)

LEDGER_FIELDS = [
    "observation_id", "source_stage", "source_variant", "as_of_date",
    "ticker", "rank", "rank_bucket", "forward_window",
    "target_maturity_date", "latest_available_price_date",
    "maturity_status", "realized_forward_return", "price_date_warning",
    "research_only",
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
        for row in rows:
            writer.writerow(row)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def discover_r5(root: Path) -> tuple[Path, Path, dict[str, object]]:
    search_root = root / "outputs/v21/experiments/momentum_dynamic"
    candidates = sorted(
        search_root.rglob("V21_060_R5_SUMMARY.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    failures = []
    for summary_path in candidates:
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            ledger_path = (
                summary_path.parent
                / "V21_060_R5_D_FORWARD_OBSERVATION_LEDGER.csv"
            )
            valid = (
                summary.get("proposed_variant_id") == SOURCE_VARIANT
                and summary.get("research_only") is True
                and summary.get("official_mutation_detected") is False
                and summary.get("a0_modified") is False
                and summary.get("existing_b_c_outputs_modified") is False
                and ledger_path.is_file()
            )
            if valid:
                return summary_path, ledger_path, summary
            failures.append(relative(root, summary_path))
        except (OSError, ValueError, KeyError):
            failures.append(relative(root, summary_path))
    raise RuntimeError(
        "No valid V21.060-R5 D summary/ledger pair found. "
        f"Rejected candidates: {failures}"
    )


def protected_paths(root: Path, source_dir: Path) -> list[Path]:
    paths = [
        root / "outputs/v21/experiments/version_control/"
        "V21_056_R2_A0_CANONICAL_CONTROL_VIEW.csv",
        root / "outputs/v21/experiments/version_control/"
        "V21_056_R1_A0_LEDGER_SNAPSHOT.csv",
        root / "outputs/v21/experiments/momentum_dynamic/"
        "V21_060_R1_ABCD_FORWARD_OBSERVATION_LEDGER.csv",
    ]
    parent = root / "outputs/v21/experiments/momentum_dynamic"
    for pattern in (
        "V21_059_R1_A1_*",
        "V21_059_R1_B_*",
        "V21_059_R1_C_*",
        "V21_061_R1_*",
        "V21_062_R1_*",
    ):
        paths.extend(parent.glob(pattern))
    paths.extend(source_dir.glob("V21_060_R5_*"))
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or root / OUT_REL in path.parents:
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


def refresh_rows(
    source_rows: list[dict[str, str]],
    prices: dict[str, tuple[list[str], list[float]]],
    evaluation_date: str,
) -> list[dict[str, object]]:
    output = []
    for source in source_rows:
        ticker = clean(source.get("ticker")).upper()
        as_of = clean(source.get("as_of_date"))
        target = clean(source.get("scheduled_maturity_date"))
        warning = clean(source.get("price_data_status")) != (
            "START_PRICE_AVAILABLE_PENDING_MATURITY"
        )
        realized = ""
        if not target or target > evaluation_date:
            status = "PENDING"
        else:
            start = price_on_or_after(prices, ticker, as_of, evaluation_date)
            end = price_on_or_after(prices, ticker, target, evaluation_date)
            if start and end:
                status = "MATURED"
                realized = f"{end[1] / start[1] - 1:.10f}"
            else:
                status = "PRICE_MISSING"
                warning = True
        rank_value = clean(source.get("rank"))
        try:
            rank = int(float(rank_value))
        except ValueError:
            rank = ""
        rank_bucket = (
            "TOP20" if isinstance(rank, int) and rank <= 20
            else "TOP50" if isinstance(rank, int) and rank <= 50
            else ""
        )
        output.append({
            "observation_id": clean(source.get("observation_id")),
            "source_stage": clean(source.get("source_stage_id") or source.get("stage_id")),
            "source_variant": clean(source.get("variant_id")),
            "as_of_date": as_of,
            "ticker": ticker,
            "rank": rank,
            "rank_bucket": rank_bucket,
            "forward_window": clean(source.get("forward_window")),
            "target_maturity_date": target,
            "latest_available_price_date": evaluation_date,
            "maturity_status": status,
            "realized_forward_return": realized,
            "price_date_warning": "TRUE" if warning else "FALSE",
            "research_only": "TRUE",
        })
    return output


def run_stage(root: Path) -> dict[str, object]:
    root = root.resolve()
    output_dir = root / OUT_REL
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path, source_ledger, source_summary = discover_r5(root)
    source_rows = read_csv(source_ledger)

    contract_errors = []
    if not source_rows:
        contract_errors.append("SOURCE_LEDGER_EMPTY")
    if any(clean(row.get("variant_id")) != SOURCE_VARIANT for row in source_rows):
        contract_errors.append("SOURCE_VARIANT_MISMATCH")
    if any(not truth(row.get("research_only")) for row in source_rows):
        contract_errors.append("SOURCE_RESEARCH_ONLY_FALSE")
    expected = int(source_summary.get("d_forward_observation_row_count", 200))
    if len(source_rows) != expected:
        contract_errors.append(
            f"SOURCE_ROW_COUNT_MISMATCH_EXPECTED_{expected}_ACTUAL_{len(source_rows)}"
        )
    source_ids = [clean(row.get("observation_id")) for row in source_rows]
    duplicate_count = len(source_ids) - len(set(source_ids))
    if any(not observation_id for observation_id in source_ids):
        contract_errors.append("SOURCE_EMPTY_OBSERVATION_ID")
    if duplicate_count:
        contract_errors.append("SOURCE_DUPLICATE_OBSERVATION_IDS")
    source_pending = int(source_summary.get("d_pending_observation_count", 0))
    source_matured = int(source_summary.get("d_matured_observation_count", 0))
    if source_pending + source_matured != len(source_rows):
        contract_errors.append("SOURCE_PENDING_MATURED_ACCOUNTING_MISMATCH")
    source_status_counts = Counter(
        clean(row.get("maturity_status")) for row in source_rows
    )
    if source_status_counts["PENDING_NOT_MATURED"] != source_pending:
        contract_errors.append("SOURCE_PENDING_STATUS_COUNT_MISMATCH")
    if sum(
        count for status, count in source_status_counts.items()
        if status.startswith("MATURED")
    ) != source_matured:
        contract_errors.append("SOURCE_MATURED_STATUS_COUNT_MISMATCH")
    source_violation_fields = (
        "local_price_missing_ranked_violation_count",
        "local_price_missing_observation_violation_count",
        "leveraged_full_size_violation_count",
        "inverse_non_hedge_violation_count",
        "tqqq_ipo_watch_violation_count",
    )
    for field in source_violation_fields:
        if int(source_summary.get(field, 0)):
            contract_errors.append(f"SOURCE_{field.upper()}")

    protected = protected_paths(root, summary_path.parent)
    before = {relative(root, path): sha256(path) for path in protected}
    prices, evaluation_date = load_prices(root / PRICE_REL)
    refreshed = refresh_rows(source_rows, prices, evaluation_date)

    status_counts = Counter(row["maturity_status"] for row in refreshed)
    warning_count = sum(row["price_date_warning"] == "TRUE" for row in refreshed)
    source_warning_count = int(
        source_summary.get("d_price_missing_observation_count", 0)
    )
    if warning_count != source_warning_count:
        contract_errors.append(
            "PRICE_DATE_WARNING_COUNT_NOT_PRESERVED_"
            f"SOURCE_{source_warning_count}_REFRESHED_{warning_count}"
        )
    if sum(status_counts.values()) != len(refreshed):
        contract_errors.append("MATURITY_ACCOUNTING_MISMATCH")

    if contract_errors:
        final_status = "BLOCKED_V21_062_D_INPUT_CONTRACT_FAILURE"
        decision = "BLOCKED_VALIDATE_V21_060_R5_D_SOURCE_BEFORE_MONITORING"
    elif status_counts["MATURED"] > 0:
        final_status = MATURED_STATUS
        decision = MATURED_DECISION
    else:
        final_status = PENDING_STATUS
        decision = PENDING_DECISION

    rank_ticker_pairs = {
        (row["ticker"], row["rank"])
        for row in refreshed
        if row["rank_bucket"] == "TOP20"
    }
    top20_count = len(rank_ticker_pairs)
    top50_count = len({
        (row["ticker"], row["rank"])
        for row in refreshed if row["rank_bucket"] in {"TOP20", "TOP50"}
    })
    next_stage = (
        "V21_063_D_ABCD_MATURED_RESULT_COMPARISON_REVIEW"
        if status_counts["MATURED"] > 0
        else "V21_063_D_MATURITY_REFRESH_AND_ABCD_COMPARISON_READINESS"
    )
    summary = {
        "final_status": final_status,
        "decision": decision,
        "source_stage": clean(source_rows[0].get("source_stage_id") if source_rows else ""),
        "source_variant": SOURCE_VARIANT,
        "total_rows": len(refreshed),
        "unique_observation_ids": len(set(source_ids)),
        "duplicate_observation_count": duplicate_count,
        "pending_count": status_counts["PENDING"],
        "matured_count": status_counts["MATURED"],
        "price_missing_count": status_counts["PRICE_MISSING"],
        "price_date_warning_count": warning_count,
        "distinct_ticker_count": len({row["ticker"] for row in refreshed}),
        "distinct_as_of_date_count": len({row["as_of_date"] for row in refreshed}),
        "forward_window_count": len({row["forward_window"] for row in refreshed}),
        "top20_count": top20_count,
        "top50_count": top50_count,
        "official_mutation": False,
        "research_only": True,
        "recommendation_allowed": False,
        "trade_action_created": False,
        "broker_execution_supported": False,
        "official_use": False,
        "next_recommended_stage": next_stage,
    }

    write_csv(output_dir / LEDGER_NAME, refreshed, LEDGER_FIELDS)
    write_csv(output_dir / SUMMARY_NAME, [summary], list(summary.keys()))

    after = {path: sha256(root / path) for path in before}
    changed = sorted(path for path in before if before[path] != after[path])
    validation = {
        "stage_id": STAGE_ID,
        "source_summary_path": relative(root, summary_path),
        "source_ledger_path": relative(root, source_ledger),
        "source_summary_sha256": before[relative(root, summary_path)],
        "source_ledger_sha256": before[relative(root, source_ledger)],
        "source_variant_valid": not any(
            "SOURCE_VARIANT" in error for error in contract_errors
        ),
        "source_research_only_valid": not any(
            "RESEARCH_ONLY" in error for error in contract_errors
        ),
        "source_row_count_expected": expected,
        "source_row_count_actual": len(source_rows),
        "source_pending_count": source_pending,
        "source_matured_count": source_matured,
        "source_pending_matured_accounting_valid": (
            source_pending + source_matured == len(source_rows)
        ),
        "observation_ids_unique": duplicate_count == 0,
        "maturity_accounting_valid": sum(status_counts.values()) == len(refreshed),
        "price_date_warning_preserved": warning_count == source_warning_count,
        "missing_price_return_zero_count": sum(
            row["maturity_status"] == "PRICE_MISSING"
            and clean(row["realized_forward_return"]) in {"0", "0.0"}
            for row in refreshed
        ),
        "local_price_missing_ranking_violation_count": int(
            source_summary.get("local_price_missing_ranked_violation_count", 0)
        ),
        "local_price_missing_observation_violation_count": int(
            source_summary.get("local_price_missing_observation_violation_count", 0)
        ),
        "leveraged_inverse_risk_violation_count": (
            int(source_summary.get("leveraged_full_size_violation_count", 0))
            + int(source_summary.get("inverse_non_hedge_violation_count", 0))
        ),
        "tqqq_ipo_watch_violation_count": int(
            source_summary.get("tqqq_ipo_watch_violation_count", 0)
        ),
        "a0_replayed": False,
        "a0_modified": False,
        "a1_b_c_source_outputs_modified": bool(changed),
        "existing_abcd_ledger_modified": any(
            "V21_060_R1_ABCD_FORWARD_OBSERVATION_LEDGER.csv" in path
            for path in changed
        ),
        "protected_outputs_modified": changed,
        "contract_errors": contract_errors,
        "research_only": True,
        "official_use": False,
        "official_mutation": False,
        "official_ranking_mutation": False,
        "official_recommendation_mutation": False,
        "recommendation_allowed": False,
        "trade_action_created": False,
        "broker_execution_supported": False,
    }
    audit = {
        "stage_id": STAGE_ID,
        "run_contract": "READ_ONLY_SOURCE_REFRESH_TO_DEDICATED_D_MONITORING_OUTPUT",
        "source_discovery_method": (
            "RECURSIVE_LATEST_VALID_V21_060_R5_SUMMARY_AND_SIBLING_LEDGER"
        ),
        "protected_before_sha256": before,
        "protected_after_sha256": after,
        "protected_outputs_modified": changed,
        "source_pending_count": int(
            source_summary.get("d_pending_observation_count", 0)
        ),
        "source_matured_count": int(
            source_summary.get("d_matured_observation_count", 0)
        ),
        "source_price_date_warning_count": source_warning_count,
        "latest_available_price_date": evaluation_date,
        "refreshed_counts": dict(status_counts),
        "output_directory": relative(root, output_dir),
        "guardrails": {
            "official_use": False,
            "recommendation_allowed": False,
            "trade_action_created": False,
            "broker_execution_supported": False,
            "official_ranking_mutation": False,
            "official_recommendation_mutation": False,
            "a0_replayed": False,
            "a0_modified": False,
            "a1_b_c_source_outputs_modified": False,
            "existing_abcd_ledger_modified": False,
        },
        "research_only": True,
    }
    write_json(output_dir / AUDIT_NAME, audit)
    write_json(output_dir / VALIDATION_NAME, validation)

    # Recheck after all writes. Only the dedicated output directory may change.
    final_after = {path: sha256(root / path) for path in before}
    final_changed = sorted(
        path for path in before if before[path] != final_after[path]
    )
    if final_changed:
        validation["protected_outputs_modified"] = final_changed
        validation["a1_b_c_source_outputs_modified"] = True
        write_json(output_dir / VALIDATION_NAME, validation)
        summary["final_status"] = "BLOCKED_V21_062_PROTECTED_OUTPUT_MUTATION"
        summary["decision"] = "BLOCKED_RESTORE_PROTECTED_OUTPUTS"
        summary["official_mutation"] = True
        write_csv(output_dir / SUMMARY_NAME, [summary], list(summary.keys()))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    summary = run_stage(parser.parse_args().root)
    print(f"FINAL_STATUS={summary['final_status']}")
    print(f"DECISION={summary['decision']}")
    print(f"SOURCE_VARIANT={summary['source_variant']}")
    print(f"TOTAL_ROWS={summary['total_rows']}")
    print(
        "PENDING/MATURED/PRICE_MISSING="
        f"{summary['pending_count']}/{summary['matured_count']}/"
        f"{summary['price_missing_count']}"
    )
    print(f"PRICE_DATE_WARNINGS={summary['price_date_warning_count']}")
    print(f"RESEARCH_ONLY={str(summary['research_only']).upper()}")
    print(f"OFFICIAL_MUTATION={str(summary['official_mutation']).upper()}")
    print(f"NEXT_RECOMMENDED_STAGE={summary['next_recommended_stage']}")
    return 1 if summary["final_status"].startswith("BLOCKED_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
