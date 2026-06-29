#!/usr/bin/env python
"""Research-only D maturity refresh and ABCD comparison-readiness staging."""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import pandas as pd


STAGE_ID = "V21.063"
SOURCE_VARIANT = "D_WEIGHT_OPTIMIZED_R1"
OUT_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/"
    "v21_063_maturity_refresh_and_abcd_comparison_readiness"
)
PRICE_REL = Path(
    "inputs/v21/historical_ohlcv_cache/"
    "V21_037_R1_HISTORICAL_OHLCV_CACHE.csv"
)
LEDGER_NAME = "V21_063_D_MATURITY_REFRESH_LEDGER.csv"
SUMMARY_NAME = "V21_063_D_MATURITY_REFRESH_SUMMARY.csv"
READINESS_NAME = "V21_063_ABCD_COMPARISON_READINESS.csv"
AUDIT_NAME = "V21_063_D_MATURITY_REFRESH_AUDIT.json"
VALIDATION_NAME = "V21_063_D_MATURITY_REFRESH_VALIDATION.json"

NO_MATURITY_STATUS = (
    "PARTIAL_PASS_V21_063_D_REFRESHED_NO_MATURED_ROWS_COMPARISON_NOT_READY"
)
NO_MATURITY_DECISION = (
    "D_MATURITY_REFRESH_COMPLETE_WAIT_FOR_FORWARD_RETURN_MATURITY"
)
PARTIAL_STATUS = (
    "PARTIAL_PASS_V21_063_D_REFRESHED_PARTIAL_MATURITY_COMPARISON_PARTIAL_READY"
)
PARTIAL_DECISION = (
    "D_MATURITY_REFRESH_COMPLETE_PARTIAL_ABCD_COMPARISON_READINESS_REVIEW_ONLY"
)
READY_STATUS = (
    "PARTIAL_PASS_V21_063_D_REFRESHED_ABCD_COMPARISON_READY_REVIEW_ONLY"
)
READY_DECISION = (
    "D_AND_ABCD_MATCHED_MATURED_COMPARISON_READY_NO_POLICY_SELECTION"
)

LEDGER_FIELDS = [
    "observation_id", "source_stage", "source_variant", "as_of_date",
    "ticker", "rank", "rank_bucket", "forward_window",
    "target_maturity_date", "latest_available_price_date",
    "previous_maturity_status", "refreshed_maturity_status",
    "realized_forward_return", "price_date_warning",
    "price_missing_reason", "research_only",
]
COMPARATORS = {
    "A1": "A1_BASELINE_REPLAY_CURRENT",
    "B": "B_MOMENTUM_STATIC_R1",
    "C": "C_MOMENTUM_DYNAMIC_R1",
}


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


def discover_v21_062_d(
    root: Path,
) -> tuple[Path, Path, dict[str, str]]:
    base = root / "outputs/v21/experiments/momentum_dynamic"
    candidates = sorted(
        base.rglob("V21_062_D_DAILY_MATURITY_MONITORING_SUMMARY.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    rejected = []
    for summary_path in candidates:
        rows = read_csv(summary_path)
        ledger = summary_path.parent / (
            "V21_062_D_DAILY_MATURITY_MONITORING_LEDGER.csv"
        )
        if (
            len(rows) == 1
            and rows[0].get("source_variant") == SOURCE_VARIANT
            and truth(rows[0].get("research_only"))
            and not truth(rows[0].get("official_mutation"))
            and ledger.is_file()
        ):
            return summary_path, ledger, rows[0]
        rejected.append(relative(root, summary_path))
    raise RuntimeError(
        "No valid V21.062 D monitoring summary/ledger pair found. "
        f"Rejected: {rejected}"
    )


def discover_abcd_maturity(
    root: Path,
) -> tuple[Path | None, list[dict[str, str]], str]:
    base = root / "outputs/v21/experiments/momentum_dynamic"
    patterns = (
        "V21_*_REFRESHED_MATURED_OBSERVATION_RESULTS.csv",
        "V21_*_MATURED_OBSERVATION_RESULTS.csv",
    )
    candidates = []
    for pattern in patterns:
        candidates.extend(base.rglob(pattern))
    candidates = sorted(
        set(candidates), key=lambda path: path.stat().st_mtime, reverse=True
    )
    for path in candidates:
        rows = read_csv(path)
        variants = {clean(row.get("variant_id")) for row in rows}
        if (
            rows
            and set(COMPARATORS.values()).issubset(variants)
            and all(truth(row.get("research_only")) for row in rows)
        ):
            return path, rows, "AVAILABLE_VALID_RESEARCH_ONLY"
    return None, [], "NOT_AVAILABLE"


def protected_paths(
    root: Path, v62_dir: Path, abcd_path: Path | None
) -> list[Path]:
    paths = list(v62_dir.glob("V21_062_D_*"))
    if abcd_path:
        paths.append(abcd_path)
    base = root / "outputs/v21/experiments/momentum_dynamic"
    for pattern in (
        "V21_059_R1_A1_*", "V21_059_R1_B_*", "V21_059_R1_C_*",
        "V21_060_R1_ABCD_*", "V21_061_R1_*", "V21_062_R1_*",
    ):
        paths.extend(base.glob(pattern))
    paths.extend(
        [
            root / "outputs/v21/experiments/version_control/"
            "V21_056_R2_A0_CANONICAL_CONTROL_VIEW.csv",
            root / "outputs/v21/experiments/version_control/"
            "V21_056_R1_A0_LEDGER_SNAPSHOT.csv",
        ]
    )
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
    evaluation_date: str,
) -> tuple[str, float] | None:
    series = prices.get(ticker)
    if not series:
        return None
    dates, values = series
    index = bisect.bisect_left(dates, target)
    if index >= len(dates) or dates[index] > evaluation_date:
        return None
    return dates[index], values[index]


def refresh_d(
    source_rows: list[dict[str, str]],
    prices: dict[str, tuple[list[str], list[float]]],
    evaluation_date: str,
) -> list[dict[str, object]]:
    output = []
    for source in source_rows:
        ticker = clean(source.get("ticker")).upper()
        as_of = clean(source.get("as_of_date"))
        target = clean(source.get("target_maturity_date"))
        realized = ""
        reason = ""
        warning = truth(source.get("price_date_warning"))
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
                missing = []
                if not start:
                    missing.append("START_PRICE_MISSING")
                if not end:
                    missing.append("END_PRICE_MISSING")
                reason = "|".join(missing)
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
            "latest_available_price_date": evaluation_date,
            "previous_maturity_status": clean(source.get("maturity_status")),
            "refreshed_maturity_status": status,
            "realized_forward_return": realized,
            "price_date_warning": "TRUE" if warning else "FALSE",
            "price_missing_reason": reason,
            "research_only": "TRUE",
        })
    return output


def comparator_status(row: dict[str, str]) -> str:
    return clean(row.get("maturity_status")).upper()


def rank_bucket(row: dict[str, str]) -> str:
    existing = clean(row.get("rank_bucket"))
    if existing:
        return existing
    try:
        rank = int(float(clean(row.get("rank"))))
    except ValueError:
        return ""
    if rank <= 20:
        return "TOP20"
    if rank <= 50:
        return "TOP50"
    return ""


def readiness_rows(
    d_rows: list[dict[str, object]],
    abcd_rows: list[dict[str, str]],
    source_path: str,
) -> list[dict[str, object]]:
    d_matured = [
        row for row in d_rows
        if row["refreshed_maturity_status"] == "MATURED"
        and clean(row["realized_forward_return"])
    ]
    output = []
    for label, variant in COMPARATORS.items():
        comparator = [
            row for row in abcd_rows
            if clean(row.get("variant_id")) == variant
            and comparator_status(row) in {
                "MATURED", "MATURED_PRICE_AVAILABLE"
            }
            and clean(row.get("realized_forward_return"))
        ]
        d_counts = Counter(
            (
                clean(row["as_of_date"]),
                clean(row["forward_window"]),
                clean(row["rank_bucket"]),
            )
            for row in d_matured
        )
        comparator_counts = Counter(
            (
                clean(row.get("as_of_date")),
                clean(row.get("forward_window")),
                rank_bucket(row),
            )
            for row in comparator
        )
        matched = sum(
            min(count, comparator_counts[key])
            for key, count in d_counts.items()
        )
        output.append({
            "comparator": label,
            "comparator_variant": variant,
            "comparison_key": "AS_OF_DATE|FORWARD_WINDOW|RANK_BUCKET",
            "d_matured_rows": len(d_matured),
            "comparator_matured_rows": len(comparator),
            "matched_matured_rows": matched,
            "comparison_ready": matched > 0,
            "comparison_ready_level": "PARTIAL" if matched > 0 else "NONE",
            "comparator_source_path": source_path,
            "preferred_policy_selected": False,
            "research_only": True,
        })
    return output


def run_stage(root: Path) -> dict[str, object]:
    root = root.resolve()
    output_dir = root / OUT_REL
    output_dir.mkdir(parents=True, exist_ok=True)
    v62_summary_path, v62_ledger_path, v62_summary = discover_v21_062_d(root)
    source_rows = read_csv(v62_ledger_path)
    abcd_path, abcd_rows, abcd_discovery = discover_abcd_maturity(root)
    protected = protected_paths(root, v62_summary_path.parent, abcd_path)
    before = {relative(root, path): sha256(path) for path in protected}

    errors = []
    source_ids = [clean(row.get("observation_id")) for row in source_rows]
    duplicate_count = len(source_ids) - len(set(source_ids))
    if not source_rows:
        errors.append("V21_062_D_LEDGER_EMPTY")
    if any(not observation_id for observation_id in source_ids):
        errors.append("EMPTY_OBSERVATION_ID")
    if duplicate_count:
        errors.append("DUPLICATE_OBSERVATION_IDS")
    if any(clean(row.get("source_variant")) != SOURCE_VARIANT for row in source_rows):
        errors.append("SOURCE_VARIANT_MISMATCH")
    if any(not truth(row.get("research_only")) for row in source_rows):
        errors.append("SOURCE_RESEARCH_ONLY_FALSE")
    expected_rows = int(v62_summary.get("total_rows", len(source_rows)))
    if len(source_rows) != expected_rows:
        errors.append("SOURCE_ROW_COUNT_MISMATCH")

    prices, evaluation_date = load_prices(root / PRICE_REL)
    refreshed = refresh_d(source_rows, prices, evaluation_date)
    counts = Counter(row["refreshed_maturity_status"] for row in refreshed)
    warning_count = sum(
        row["price_date_warning"] == "TRUE" for row in refreshed
    )
    source_warning_count = int(v62_summary.get("price_date_warning_count", 0))
    warning_delta = warning_count - source_warning_count
    non_null_returns = sum(
        bool(clean(row["realized_forward_return"])) for row in refreshed
    )
    invalid_return_rows = sum(
        bool(clean(row["realized_forward_return"]))
        != (row["refreshed_maturity_status"] == "MATURED")
        for row in refreshed
    )
    zero_filled_missing = sum(
        row["refreshed_maturity_status"] != "MATURED"
        and clean(row["realized_forward_return"]) in {"0", "0.0"}
        for row in refreshed
    )
    if sum(counts.values()) != len(refreshed):
        errors.append("MATURITY_ACCOUNTING_MISMATCH")
    if invalid_return_rows:
        errors.append("REALIZED_RETURN_STATUS_CONTRACT_FAILURE")
    if zero_filled_missing:
        errors.append("MISSING_RETURN_ZERO_FILL_DETECTED")

    readiness = readiness_rows(
        refreshed,
        abcd_rows,
        relative(root, abcd_path) if abcd_path else "",
    )
    matched = {
        row["comparator"]: int(row["matched_matured_rows"])
        for row in readiness
    }
    all_ready = all(matched[label] > 0 for label in COMPARATORS)
    any_ready = any(matched[label] > 0 for label in COMPARATORS)
    if counts["MATURED"] == 0:
        ready_level = "NONE"
        comparison_ready = False
        final_status = NO_MATURITY_STATUS
        decision = NO_MATURITY_DECISION
        next_stage = "V21_064_D_DAILY_MATURITY_CONTINUATION_OR_PRICE_REFRESH_CHECK"
    elif all_ready:
        ready_level = "READY"
        comparison_ready = True
        final_status = READY_STATUS
        decision = READY_DECISION
        next_stage = "V21_064_D_ABCD_MATCHED_MATURED_RESULT_EVALUATOR"
    else:
        ready_level = "PARTIAL"
        comparison_ready = any_ready
        final_status = PARTIAL_STATUS
        decision = PARTIAL_DECISION
        next_stage = "V21_064_D_PARTIAL_MATURED_ABCD_COMPARISON_REVIEW"
    if errors:
        final_status = "BLOCKED_V21_063_D_INPUT_OR_REFRESH_CONTRACT_FAILURE"
        decision = "BLOCKED_VALIDATE_V21_062_D_AND_PRICE_INPUTS"

    summary = {
        "final_status": final_status,
        "decision": decision,
        "source_stage": clean(v62_summary.get("source_stage")),
        "source_variant": SOURCE_VARIANT,
        "total_rows": len(refreshed),
        "unique_observation_ids": len(set(source_ids)),
        "duplicate_observation_count": duplicate_count,
        "previous_pending_count": sum(
            clean(row.get("maturity_status")) == "PENDING"
            for row in source_rows
        ),
        "refreshed_pending_count": counts["PENDING"],
        "refreshed_matured_count": counts["MATURED"],
        "refreshed_price_missing_count": counts["PRICE_MISSING"],
        "price_date_warning_count": warning_count,
        "realized_forward_return_non_null_count": non_null_returns,
        "distinct_ticker_count": len({row["ticker"] for row in refreshed}),
        "distinct_as_of_date_count": len(
            {row["as_of_date"] for row in refreshed}
        ),
        "forward_window_count": len(
            {row["forward_window"] for row in refreshed}
        ),
        "abcd_comparison_ready": comparison_ready,
        "abcd_comparison_ready_level": ready_level,
        "matched_matured_rows_vs_A1": matched["A1"],
        "matched_matured_rows_vs_B": matched["B"],
        "matched_matured_rows_vs_C": matched["C"],
        "preferred_policy_selected": False,
        "recommendation_allowed": False,
        "trade_action_created": False,
        "broker_execution_supported": False,
        "official_mutation": False,
        "research_only": True,
        "next_recommended_stage": next_stage,
    }
    write_csv(output_dir / LEDGER_NAME, refreshed, LEDGER_FIELDS)
    write_csv(output_dir / READINESS_NAME, readiness, list(readiness[0].keys()))
    write_csv(output_dir / SUMMARY_NAME, [summary], list(summary.keys()))

    after = {path: sha256(root / path) for path in before}
    changed = sorted(path for path in before if before[path] != after[path])
    validation = {
        "stage_id": STAGE_ID,
        "source_v21_062_summary_path": relative(root, v62_summary_path),
        "source_v21_062_ledger_path": relative(root, v62_ledger_path),
        "abcd_maturity_source_path": (
            relative(root, abcd_path) if abcd_path else ""
        ),
        "abcd_source_discovery_status": abcd_discovery,
        "source_observation_ids_preserved": (
            [row["observation_id"] for row in refreshed] == source_ids
        ),
        "observation_ids_unique": duplicate_count == 0,
        "maturity_accounting_valid": sum(counts.values()) == len(refreshed),
        "realized_return_only_for_matured": invalid_return_rows == 0,
        "missing_return_zero_fill_count": zero_filled_missing,
        "source_price_date_warning_count": source_warning_count,
        "refreshed_price_date_warning_count": warning_count,
        "price_date_warning_reconciliation_delta": warning_delta,
        "price_date_warning_reconciled": warning_delta >= 0,
        "comparison_false_when_d_zero_matured": (
            counts["MATURED"] > 0 or not comparison_ready
        ),
        "v21_062_outputs_modified": any("V21_062_D_" in path for path in changed),
        "a0_a1_b_c_d_source_files_modified": bool(changed),
        "protected_outputs_modified": changed,
        "official_mutation": False,
        "preferred_policy_selected": False,
        "recommendation_allowed": False,
        "trade_action_created": False,
        "broker_execution_supported": False,
        "research_only": True,
        "contract_errors": errors,
    }
    audit = {
        "stage_id": STAGE_ID,
        "run_contract": (
            "READ_ONLY_D_MATURITY_REFRESH_AND_MATCHED_COUNT_READINESS_ONLY"
        ),
        "latest_available_price_date": evaluation_date,
        "source_v21_062_sha256": {
            relative(root, v62_summary_path): before[relative(root, v62_summary_path)],
            relative(root, v62_ledger_path): before[relative(root, v62_ledger_path)],
        },
        "abcd_source_discovery_status": abcd_discovery,
        "protected_before_sha256": before,
        "protected_after_sha256": after,
        "protected_outputs_modified": changed,
        "price_date_warning_reconciliation": {
            "source": source_warning_count,
            "refreshed": warning_count,
            "delta_due_to_newly_due_missing_prices": warning_delta,
        },
        "comparison_method": (
            "ONE_TO_ONE_CAPACITY_BY_AS_OF_DATE_FORWARD_WINDOW_RANK_BUCKET"
        ),
        "guardrails": {
            "official_use": False,
            "preferred_policy_selected": False,
            "recommendation_allowed": False,
            "trade_action_created": False,
            "broker_execution_supported": False,
            "source_outputs_modified": False,
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
        summary["final_status"] = "BLOCKED_V21_063_PROTECTED_OUTPUT_MUTATION"
        summary["decision"] = "BLOCKED_RESTORE_PROTECTED_OUTPUTS"
        summary["official_mutation"] = True
        validation["protected_outputs_modified"] = final_changed
        validation["a0_a1_b_c_d_source_files_modified"] = True
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
        "REFRESHED_PENDING/MATURED/PRICE_MISSING="
        f"{summary['refreshed_pending_count']}/"
        f"{summary['refreshed_matured_count']}/"
        f"{summary['refreshed_price_missing_count']}"
    )
    print(f"PRICE_DATE_WARNINGS={summary['price_date_warning_count']}")
    print(
        f"ABCD_COMPARISON_READY_LEVEL={summary['abcd_comparison_ready_level']}"
    )
    print(
        "MATCHED_MATURED_ROWS_VS_A1/B/C="
        f"{summary['matched_matured_rows_vs_A1']}/"
        f"{summary['matched_matured_rows_vs_B']}/"
        f"{summary['matched_matured_rows_vs_C']}"
    )
    print(f"OFFICIAL_MUTATION={str(summary['official_mutation']).upper()}")
    print(f"RESEARCH_ONLY={str(summary['research_only']).upper()}")
    print(f"NEXT_RECOMMENDED_STAGE={summary['next_recommended_stage']}")
    return 1 if summary["final_status"].startswith("BLOCKED_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
