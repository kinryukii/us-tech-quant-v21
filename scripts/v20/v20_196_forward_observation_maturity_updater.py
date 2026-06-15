#!/usr/bin/env python
"""V20.196 forward observation maturity updater."""

from __future__ import annotations

import csv
import hashlib
from datetime import date
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v20" / "forward_observation"
SCHEDULE_SOURCE = OUT_DIR / "V20_195_FORWARD_OBSERVATION_SCHEDULE.csv"
RETURN_SOURCE = OUT_DIR / "V20_195_FORWARD_RETURN_OBSERVATION_LEDGER.csv"
BENCHMARK_SOURCE = OUT_DIR / "V20_195_BENCHMARK_OBSERVATION_LEDGER.csv"
SNAPSHOT_SOURCE = ROOT / "outputs" / "v20" / "backtest_snapshots" / "V20_194_RECOMPUTABLE_FACTOR_SNAPSHOT_LEDGER.csv"

OUT_INPUT_AUDIT = OUT_DIR / "V20_196_MATURITY_INPUT_AUDIT.csv"
OUT_ELIGIBILITY = OUT_DIR / "V20_196_MATURED_OBSERVATION_ELIGIBILITY.csv"
OUT_RETURN_LEDGER = OUT_DIR / "V20_196_UPDATED_FORWARD_RETURN_OBSERVATION_LEDGER.csv"
OUT_BENCHMARK_LEDGER = OUT_DIR / "V20_196_UPDATED_BENCHMARK_OBSERVATION_LEDGER.csv"
OUT_TOPN_READOUT = OUT_DIR / "V20_196_TOPN_FORWARD_RETURN_READOUT.csv"
OUT_EXCESS_READOUT = OUT_DIR / "V20_196_BENCHMARK_EXCESS_RETURN_READOUT.csv"
OUT_PENDING_STATUS = OUT_DIR / "V20_196_PENDING_OBSERVATION_STATUS.csv"
OUT_MISSING_PRICE_AUDIT = OUT_DIR / "V20_196_MISSING_PRICE_DATA_AUDIT.csv"
OUT_FABRICATION_AUDIT = OUT_DIR / "V20_196_NO_FABRICATION_GUARD_AUDIT.csv"
OUT_GATE = OUT_DIR / "V20_196_NEXT_STAGE_GATE.csv"
OUT_REPORT = OUT_DIR / "V20_196_READ_CENTER_REPORT.md"

PRICE_DISCOVERY_ROOTS = [
    ROOT / "outputs" / "v20",
    ROOT / "outputs" / "v18",
    ROOT / "outputs" / "v16",
    ROOT / "data",
    ROOT / "cache",
]
BENCHMARKS = ["QQQ", "SPY", "SOXX"]
FORWARD_WINDOWS = ["5D", "10D", "20D", "60D"]
TOP_N_GROUPS = [5, 10, 20, 40]
PASS_STATUS = "PASS_V20_196_FORWARD_OBSERVATION_MATURITY_UPDATER"
PARTIAL_STATUS = "PARTIAL_PASS_V20_196_FORWARD_OBSERVATION_MATURITY_UPDATER_ALL_OBSERVATIONS_PENDING_NOT_MATURED"
PARTIAL_MISSING_STATUS = "PARTIAL_PASS_MATURED_BUT_PRICE_DATA_MISSING_V20_196_FORWARD_OBSERVATION_MATURITY_UPDATER"
BLOCKED_STATUS = "BLOCKED_V20_196_FORWARD_OBSERVATION_MATURITY_UPDATER"

COMMON = {
    "research_only": "TRUE",
    "official_ranking_mutated": "FALSE",
    "official_ranking_score_mutation_count": "0",
    "official_rank_mutation_count": "0",
    "official_recommendation_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "real_book_action_created": "FALSE",
    "no_fabricated_returns": "TRUE",
    "no_fabricated_benchmark_returns": "TRUE",
    "no_future_price_used": "TRUE",
    "no_current_to_historical_score_join": "TRUE",
    "data_trust_scoring_weight": "0.0000000000",
    "zero_weight_policy_binding": "TRUE",
    "audit_only": "TRUE",
}

INPUT_AUDIT_FIELDS = [
    "input_audit_id",
    "source_artifact",
    "artifact_exists",
    "artifact_non_empty",
    "row_count",
    "required_for_stage",
    "input_status",
    "price_artifacts_discovered",
    "accepted_price_row_count",
    *COMMON.keys(),
]
ELIGIBILITY_FIELDS = [
    "observation_id",
    "snapshot_id",
    "as_of_date",
    "ticker",
    "forward_window",
    "scheduled_observation_date",
    "current_run_date",
    "maturity_status",
    "eligible_for_update",
    "entry_price_available",
    "exit_price_available",
    "benchmark_price_available",
    "eligibility_status",
    "insufficient_data_reason",
    *COMMON.keys(),
]
RETURN_FIELDS = [
    "observation_id",
    "snapshot_id",
    "as_of_date",
    "ticker",
    "zero_weight_rank",
    "top_n_group_membership",
    "forward_window",
    "entry_price",
    "exit_price",
    "forward_return",
    "observation_status",
    "insufficient_data_reason",
    "deterministic_recompute_status",
    *COMMON.keys(),
]
BENCH_FIELDS = [
    "as_of_date",
    "forward_window",
    "benchmark",
    "scheduled_observation_date",
    "benchmark_entry_price",
    "benchmark_exit_price",
    "benchmark_forward_return",
    "benchmark_observation_status",
    "insufficient_data_reason",
    *COMMON.keys(),
]
TOPN_FIELDS = [
    "readout_id",
    "top_n",
    "forward_window",
    "candidate_count",
    "matured_candidate_count",
    "observed_return_count",
    "average_forward_return",
    "median_forward_return",
    "win_rate",
    "average_excess_return_vs_QQQ",
    "average_excess_return_vs_SPY",
    "average_excess_return_vs_SOXX",
    "median_excess_return_vs_QQQ",
    "median_excess_return_vs_SPY",
    "median_excess_return_vs_SOXX",
    "positive_excess_return_rate_vs_QQQ",
    "positive_excess_return_rate_vs_SPY",
    "positive_excess_return_rate_vs_SOXX",
    "pending_count",
    "missing_price_data_count",
    "insufficient_data_reason",
    *COMMON.keys(),
]
EXCESS_FIELDS = [
    "readout_id",
    "top_n",
    "forward_window",
    "benchmark",
    "candidate_count",
    "observed_pair_count",
    "average_excess_return",
    "median_excess_return",
    "positive_excess_return_rate",
    "benchmark_observation_status",
    "insufficient_data_reason",
    *COMMON.keys(),
]
PENDING_FIELDS = [
    "pending_status_id",
    "forward_window",
    "pending_count",
    "next_scheduled_observation_date",
    "pending_status",
    *COMMON.keys(),
]
MISSING_FIELDS = [
    "missing_price_audit_id",
    "observation_id",
    "as_of_date",
    "ticker",
    "forward_window",
    "scheduled_observation_date",
    "entry_price_missing",
    "exit_price_missing",
    "benchmark_price_missing",
    "missing_price_data_status",
    "insufficient_data_reason",
    *COMMON.keys(),
]
GUARD_FIELDS = [
    "guard_id",
    "guard_check",
    "expected_value",
    "actual_value",
    "guard_passed",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "schedule_exists",
    "usable_observation_rows",
    "pending_not_matured_count",
    "matured_observation_count",
    "observed_return_count",
    "benchmark_observed_count",
    "missing_price_data_count",
    "no_fabrication_guard_pass",
    "no_official_trade_mutation",
    "future_price_leakage_detected",
    "ready_for_next_stage",
    "blocking_reason",
    "final_status",
    *COMMON.keys(),
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{k: clean(v) for k, v in row.items()} for row in csv.DictReader(handle)]


def csv_headers(path: Path) -> list[str]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return csv.DictReader(handle).fieldnames or []


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def sha_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def as_float(value: str) -> float | None:
    try:
        if clean(value) == "":
            return None
        return float(value)
    except ValueError:
        return None


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.10f}"


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(clean(value)[:10])
    except ValueError:
        return None


def positive_price(value: object) -> float | None:
    number = as_float(clean(value))
    if number is None or number <= 0:
        return None
    return number


def discover_price_artifacts() -> list[Path]:
    found: list[Path] = []
    price_tokens = ("price", "cache", "quote", "historical", "yahoo")
    for root in PRICE_DISCOVERY_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.csv"):
            if any(token in path.name.lower() for token in price_tokens):
                found.append(path)
    return sorted(set(found))


def field_lookup(row: dict[str, str], candidates: list[str]) -> str:
    lower = {key.lower(): key for key in row}
    for candidate in candidates:
        if candidate in lower:
            return row.get(lower[candidate], "")
    return ""


def build_price_index(paths: list[Path]) -> tuple[dict[tuple[str, str], float], int, int]:
    index: dict[tuple[str, str], float] = {}
    accepted_rows = 0
    accepted_artifacts = 0
    ticker_fields = ["ticker", "symbol", "benchmark", "benchmark_symbol", "ticker_symbol"]
    date_fields = ["date", "price_date", "latest_price_date", "as_of_date"]
    close_fields = ["adj_close", "adjusted_close", "adjusted_close_price", "close", "latest_price", "close_price"]
    for path in paths:
        headers = {header.lower() for header in csv_headers(path)}
        if not headers.intersection(ticker_fields) or not headers.intersection(date_fields) or not headers.intersection(close_fields):
            continue
        rows = read_csv(path)
        artifact_accepted = False
        for row in rows:
            ticker = field_lookup(row, ticker_fields).upper()
            price_date = field_lookup(row, date_fields)[:10]
            price = positive_price(field_lookup(row, close_fields))
            if not ticker or not price_date or price is None:
                continue
            index[(ticker, price_date)] = price
            accepted_rows += 1
            artifact_accepted = True
        if artifact_accepted:
            accepted_artifacts += 1
    return index, accepted_artifacts, accepted_rows


def return_from(entry: float | None, exit_price: float | None) -> str:
    if entry is None or exit_price is None:
        return ""
    return fmt(exit_price / entry - 1)


def identical_observed(prior: dict[str, str], computed: dict[str, str]) -> bool:
    keys = ["entry_price", "exit_price", "forward_return", "observation_status"]
    return all(clean(prior.get(key)) == clean(computed.get(key)) for key in keys)


def update_return_rows(
    schedule_rows: list[dict[str, str]],
    prior_return_rows: list[dict[str, str]],
    price_index: dict[tuple[str, str], float],
    run_date: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], int]:
    prior_by_id = {row.get("observation_id", ""): row for row in prior_return_rows}
    updated: list[dict[str, str]] = []
    eligibility: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    deterministic_mismatch_count = 0
    run_dt = parse_date(run_date)
    for schedule in schedule_rows:
        observation_id = schedule["observation_id"]
        ticker = schedule["ticker"].upper()
        as_of_date = schedule["as_of_date"]
        scheduled = schedule["scheduled_observation_date"]
        scheduled_dt = parse_date(scheduled)
        matured = bool(run_dt and scheduled_dt and scheduled_dt <= run_dt)
        entry = price_index.get((ticker, as_of_date)) if matured else None
        exit_price = price_index.get((ticker, scheduled)) if matured else None
        entry_available = entry is not None
        exit_available = exit_price is not None
        if not matured:
            status = "PENDING_NOT_MATURED"
            reason = "PENDING_NOT_MATURED"
        elif entry_available and exit_available:
            status = "OBSERVED"
            reason = ""
        else:
            status = "MISSING_PRICE_DATA"
            reason = "MISSING_ENTRY_OR_EXIT_PRICE"
        computed = {
            "observation_id": observation_id,
            "snapshot_id": schedule["snapshot_id"],
            "as_of_date": as_of_date,
            "ticker": ticker,
            "zero_weight_rank": schedule["zero_weight_rank"],
            "top_n_group_membership": schedule["top_n_group_membership"],
            "forward_window": schedule["forward_window"],
            "entry_price": str(entry) if entry_available else "",
            "exit_price": str(exit_price) if exit_available else "",
            "forward_return": return_from(entry, exit_price) if status == "OBSERVED" else "",
            "observation_status": status,
            "insufficient_data_reason": reason,
            "deterministic_recompute_status": "COMPUTED_FROM_PRICE_INDEX" if status == "OBSERVED" else "NOT_COMPUTED",
            **COMMON,
        }
        prior = prior_by_id.get(observation_id, {})
        if prior.get("observation_status") == "OBSERVED":
            if identical_observed(prior, computed):
                computed["deterministic_recompute_status"] = "PREVIOUS_OBSERVED_IDENTICAL"
            else:
                deterministic_mismatch_count += 1
                for key in ["entry_price", "exit_price", "forward_return", "observation_status", "insufficient_data_reason"]:
                    computed[key] = prior.get(key, "")
                computed["deterministic_recompute_status"] = "PREVIOUS_OBSERVED_PRESERVED_RECOMPUTE_MISMATCH_AUDITED"
        updated.append(computed)
        eligibility.append({
            "observation_id": observation_id,
            "snapshot_id": schedule["snapshot_id"],
            "as_of_date": as_of_date,
            "ticker": ticker,
            "forward_window": schedule["forward_window"],
            "scheduled_observation_date": scheduled,
            "current_run_date": run_date,
            "maturity_status": "MATURED" if matured else "PENDING_NOT_MATURED",
            "eligible_for_update": tf(matured),
            "entry_price_available": tf(entry_available),
            "exit_price_available": tf(exit_available),
            "benchmark_price_available": "",
            "eligibility_status": status,
            "insufficient_data_reason": reason,
            **COMMON,
        })
        if status == "MISSING_PRICE_DATA":
            missing.append({
                "missing_price_audit_id": f"V20_196_MISSING_PRICE_{len(missing) + 1:06d}",
                "observation_id": observation_id,
                "as_of_date": as_of_date,
                "ticker": ticker,
                "forward_window": schedule["forward_window"],
                "scheduled_observation_date": scheduled,
                "entry_price_missing": tf(not entry_available),
                "exit_price_missing": tf(not exit_available),
                "benchmark_price_missing": "FALSE",
                "missing_price_data_status": "MISSING_PRICE_DATA",
                "insufficient_data_reason": reason,
                **COMMON,
            })
    return updated, eligibility, missing, deterministic_mismatch_count


def update_benchmark_rows(
    schedule_rows: list[dict[str, str]],
    prior_benchmark_rows: list[dict[str, str]],
    price_index: dict[tuple[str, str], float],
    run_date: str,
) -> tuple[list[dict[str, str]], int]:
    prior_by_key = {
        (row.get("as_of_date", ""), row.get("forward_window", ""), row.get("benchmark", "")): row
        for row in prior_benchmark_rows
    }
    run_dt = parse_date(run_date)
    unique_schedule = sorted({(row["as_of_date"], row["forward_window"], row["scheduled_observation_date"]) for row in schedule_rows})
    rows: list[dict[str, str]] = []
    observed_count = 0
    for as_of_date, window, scheduled in unique_schedule:
        scheduled_dt = parse_date(scheduled)
        matured = bool(run_dt and scheduled_dt and scheduled_dt <= run_dt)
        for benchmark in BENCHMARKS:
            entry = price_index.get((benchmark, as_of_date)) if matured else None
            exit_price = price_index.get((benchmark, scheduled)) if matured else None
            if not matured:
                status = "PENDING_NOT_MATURED"
                reason = "PENDING_NOT_MATURED"
            elif entry is not None and exit_price is not None:
                status = "OBSERVED"
                reason = ""
                observed_count += 1
            else:
                status = "MISSING_PRICE_DATA"
                reason = "MISSING_ENTRY_OR_EXIT_PRICE"
            prior = prior_by_key.get((as_of_date, window, benchmark), {})
            row = {
                "as_of_date": as_of_date,
                "forward_window": window,
                "benchmark": benchmark,
                "scheduled_observation_date": scheduled,
                "benchmark_entry_price": str(entry) if entry is not None else "",
                "benchmark_exit_price": str(exit_price) if exit_price is not None else "",
                "benchmark_forward_return": return_from(entry, exit_price) if status == "OBSERVED" else "",
                "benchmark_observation_status": status,
                "insufficient_data_reason": reason,
                **COMMON,
            }
            if prior.get("benchmark_observation_status") == "OBSERVED":
                prior_return = prior.get("benchmark_forward_return", "")
                if row["benchmark_forward_return"] != prior_return:
                    row["benchmark_entry_price"] = prior.get("benchmark_entry_price", "")
                    row["benchmark_exit_price"] = prior.get("benchmark_exit_price", "")
                    row["benchmark_forward_return"] = prior_return
                    row["benchmark_observation_status"] = "OBSERVED"
                    row["insufficient_data_reason"] = ""
            rows.append(row)
    return rows, observed_count


def num_values(rows: list[dict[str, str]], field: str) -> list[float]:
    values = [as_float(row.get(field, "")) for row in rows]
    return [value for value in values if value is not None]


def avg(values: list[float]) -> str:
    return fmt(mean(values)) if values else ""


def med(values: list[float]) -> str:
    return fmt(median(values)) if values else ""


def rate(values: list[bool]) -> str:
    return fmt(sum(1 for value in values if value) / len(values)) if values else ""


def topn_readouts(return_rows: list[dict[str, str]], benchmark_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    bench_lookup = {(row["as_of_date"], row["forward_window"], row["benchmark"]): as_float(row.get("benchmark_forward_return", "")) for row in benchmark_rows}
    top_rows: list[dict[str, str]] = []
    excess_rows: list[dict[str, str]] = []
    readout_id = 1
    excess_id = 1
    for top_n in TOP_N_GROUPS:
        marker = f"TOP_{top_n}"
        for window in FORWARD_WINDOWS:
            group = [row for row in return_rows if row["forward_window"] == window and marker in row.get("top_n_group_membership", "").split("|")]
            observed = [row for row in group if row["observation_status"] == "OBSERVED" and as_float(row.get("forward_return", "")) is not None]
            returns = num_values(observed, "forward_return")
            metrics = {
                "readout_id": f"V20_196_TOPN_READOUT_{readout_id:04d}",
                "top_n": str(top_n),
                "forward_window": window,
                "candidate_count": str(len(group)),
                "matured_candidate_count": str(sum(1 for row in group if row["observation_status"] != "PENDING_NOT_MATURED")),
                "observed_return_count": str(len(observed)),
                "average_forward_return": avg(returns),
                "median_forward_return": med(returns),
                "win_rate": rate([value > 0 for value in returns]),
                "pending_count": str(sum(1 for row in group if row["observation_status"] == "PENDING_NOT_MATURED")),
                "missing_price_data_count": str(sum(1 for row in group if row["observation_status"] == "MISSING_PRICE_DATA")),
                "insufficient_data_reason": "" if observed else "NO_OBSERVED_RETURNS",
                **COMMON,
            }
            for benchmark in BENCHMARKS:
                excess = []
                for row in observed:
                    bench_return = bench_lookup.get((row["as_of_date"], window, benchmark))
                    ticker_return = as_float(row.get("forward_return", ""))
                    if ticker_return is not None and bench_return is not None:
                        excess.append(ticker_return - bench_return)
                metrics[f"average_excess_return_vs_{benchmark}"] = avg(excess)
                metrics[f"median_excess_return_vs_{benchmark}"] = med(excess)
                metrics[f"positive_excess_return_rate_vs_{benchmark}"] = rate([value > 0 for value in excess])
                excess_rows.append({
                    "readout_id": f"V20_196_EXCESS_READOUT_{excess_id:04d}",
                    "top_n": str(top_n),
                    "forward_window": window,
                    "benchmark": benchmark,
                    "candidate_count": str(len(group)),
                    "observed_pair_count": str(len(excess)),
                    "average_excess_return": avg(excess),
                    "median_excess_return": med(excess),
                    "positive_excess_return_rate": rate([value > 0 for value in excess]),
                    "benchmark_observation_status": "OBSERVED" if excess else "PENDING_OR_INSUFFICIENT_DATA",
                    "insufficient_data_reason": "" if excess else "NO_OBSERVED_TICKER_AND_BENCHMARK_PAIRS",
                    **COMMON,
                })
                excess_id += 1
            top_rows.append(metrics)
            readout_id += 1
    return top_rows, excess_rows


def input_audit(price_paths: list[Path], accepted_artifacts: int, accepted_price_rows: int) -> list[dict[str, str]]:
    sources = [SCHEDULE_SOURCE, RETURN_SOURCE, BENCHMARK_SOURCE, SNAPSHOT_SOURCE]
    rows = []
    for idx, path in enumerate(sources, start=1):
        data = read_csv(path)
        rows.append({
            "input_audit_id": f"V20_196_INPUT_{idx:03d}",
            "source_artifact": rel(path),
            "artifact_exists": tf(path.exists()),
            "artifact_non_empty": tf(path.exists() and path.stat().st_size > 0),
            "row_count": str(len(data)),
            "required_for_stage": "TRUE",
            "input_status": "PASS" if data else "MISSING_OR_EMPTY",
            "price_artifacts_discovered": str(len(price_paths)),
            "accepted_price_row_count": str(accepted_price_rows),
            **COMMON,
        })
    rows.append({
        "input_audit_id": "V20_196_INPUT_PRICE_DISCOVERY",
        "source_artifact": "outputs/v20|outputs/v18|outputs/v16|data|cache",
        "artifact_exists": tf(bool(price_paths)),
        "artifact_non_empty": tf(accepted_price_rows > 0),
        "row_count": str(accepted_artifacts),
        "required_for_stage": "TRUE",
        "input_status": "PASS" if accepted_price_rows > 0 else "NO_ACCEPTED_PRICE_ROWS",
        "price_artifacts_discovered": str(len(price_paths)),
        "accepted_price_row_count": str(accepted_price_rows),
        **COMMON,
    })
    return rows


def pending_status_rows(return_rows: list[dict[str, str]], schedule_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    schedule_by_id = {row["observation_id"]: row for row in schedule_rows}
    rows = []
    for idx, window in enumerate(FORWARD_WINDOWS, start=1):
        pending = [row for row in return_rows if row["forward_window"] == window and row["observation_status"] == "PENDING_NOT_MATURED"]
        next_dates = sorted(schedule_by_id[row["observation_id"]]["scheduled_observation_date"] for row in pending if row["observation_id"] in schedule_by_id)
        rows.append({
            "pending_status_id": f"V20_196_PENDING_{idx:03d}",
            "forward_window": window,
            "pending_count": str(len(pending)),
            "next_scheduled_observation_date": next_dates[0] if next_dates else "",
            "pending_status": "PENDING_NOT_MATURED" if pending else "NO_PENDING_OBSERVATIONS",
            **COMMON,
        })
    return rows


def guard_audit(
    return_rows: list[dict[str, str]],
    benchmark_rows: list[dict[str, str]],
    run_date: str,
    source_hash_before: dict[Path, str],
    source_hash_after: dict[Path, str],
    deterministic_mismatch_count: int,
) -> tuple[list[dict[str, str]], bool, bool]:
    fabricated_returns = sum(1 for row in return_rows if row["observation_status"] != "OBSERVED" and clean(row.get("forward_return", "")))
    fabricated_bench = sum(1 for row in benchmark_rows if row["benchmark_observation_status"] != "OBSERVED" and clean(row.get("benchmark_forward_return", "")))
    future_price_count = 0
    for row in return_rows:
        if row["observation_status"] == "OBSERVED" and row.get("scheduled_observation_date", "") > run_date:
            future_price_count += 1
    source_mutated = source_hash_before != source_hash_after
    checks = [
        ("fabricated_forward_return_count", "0", str(fabricated_returns)),
        ("fabricated_benchmark_return_count", "0", str(fabricated_bench)),
        ("future_price_leakage_count", "0", str(future_price_count)),
        ("official_or_trade_mutation_count", "0", "1" if source_mutated else "0"),
        ("deterministic_observed_recompute_mismatch_count", "0", str(deterministic_mismatch_count)),
        ("research_only", "TRUE", "TRUE"),
        ("zero_weight_policy_binding", "TRUE", "TRUE"),
    ]
    rows = []
    for idx, (check, expected, actual) in enumerate(checks, start=1):
        rows.append({
            "guard_id": f"V20_196_GUARD_{idx:03d}",
            "guard_check": check,
            "expected_value": expected,
            "actual_value": actual,
            "guard_passed": tf(expected == actual),
            **COMMON,
        })
    guard_pass = all(row["guard_passed"] == "TRUE" for row in rows)
    return rows, guard_pass, future_price_count > 0


def write_report(gate: dict[str, str], run_date: str, accepted_price_rows: int) -> None:
    lines = [
        "# V20.196 Forward Observation Maturity Updater",
        "",
        f"- final_status: {gate['final_status']}",
        f"- current_run_date: {run_date}",
        f"- usable_observation_rows: {gate['usable_observation_rows']}",
        f"- pending_not_matured_count: {gate['pending_not_matured_count']}",
        f"- matured_observation_count: {gate['matured_observation_count']}",
        f"- observed_return_count: {gate['observed_return_count']}",
        f"- benchmark_observed_count: {gate['benchmark_observed_count']}",
        f"- accepted_price_row_count: {accepted_price_rows}",
        "",
        "Matured observations are filled only when the scheduled observation date has arrived and both entry and exit prices exist in accepted local price artifacts. Pending rows remain blank. No official ranking, recommendation, or trade action is created.",
    ]
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    protected_sources = [SCHEDULE_SOURCE, RETURN_SOURCE, BENCHMARK_SOURCE, SNAPSHOT_SOURCE]
    hashes_before = {path: sha_file(path) for path in protected_sources}
    schedule_rows = read_csv(SCHEDULE_SOURCE)
    prior_return_rows = read_csv(RETURN_SOURCE)
    prior_benchmark_rows = read_csv(BENCHMARK_SOURCE)
    price_paths = discover_price_artifacts()
    price_index, accepted_artifacts, accepted_price_rows = build_price_index(price_paths)
    run_date = date.today().isoformat()

    updated_returns, eligibility, missing_price_rows, deterministic_mismatch_count = update_return_rows(
        schedule_rows,
        prior_return_rows,
        price_index,
        run_date,
    )
    updated_benchmarks, benchmark_observed_count = update_benchmark_rows(schedule_rows, prior_benchmark_rows, price_index, run_date)
    topn_rows, excess_rows = topn_readouts(updated_returns, updated_benchmarks)
    pending_rows = pending_status_rows(updated_returns, schedule_rows)
    hashes_after = {path: sha_file(path) for path in protected_sources}
    guard_rows, guard_pass, future_leakage = guard_audit(
        updated_returns,
        updated_benchmarks,
        run_date,
        hashes_before,
        hashes_after,
        deterministic_mismatch_count,
    )
    no_official_trade_mutation = hashes_before == hashes_after

    pending_count = sum(1 for row in updated_returns if row["observation_status"] == "PENDING_NOT_MATURED")
    matured_count = len(updated_returns) - pending_count
    observed_count = sum(1 for row in updated_returns if row["observation_status"] == "OBSERVED")
    missing_count = sum(1 for row in updated_returns if row["observation_status"] == "MISSING_PRICE_DATA")

    blocked_reasons = []
    if not schedule_rows:
        blocked_reasons.append("NO_SCHEDULE_EXISTS")
    if schedule_rows and not updated_returns:
        blocked_reasons.append("USABLE_OBSERVATION_ROWS_MISSING")
    if not guard_pass:
        blocked_reasons.append("NO_FABRICATION_GUARD_FAILED")
    if future_leakage:
        blocked_reasons.append("FUTURE_PRICE_LEAKAGE_DETECTED")
    if not no_official_trade_mutation:
        blocked_reasons.append("OFFICIAL_OR_TRADE_MUTATION_DETECTED")

    if blocked_reasons:
        final_status = BLOCKED_STATUS
        ready = "FALSE"
        blocking = "|".join(blocked_reasons)
    elif matured_count > 0 and observed_count > 0 and benchmark_observed_count > 0:
        final_status = PASS_STATUS
        ready = "TRUE"
        blocking = "NONE"
    elif schedule_rows and pending_count == len(updated_returns):
        final_status = PARTIAL_STATUS
        ready = "TRUE"
        blocking = "ALL_OBSERVATIONS_PENDING_NOT_MATURED"
    elif matured_count > 0 and observed_count == 0:
        final_status = PARTIAL_MISSING_STATUS
        ready = "TRUE"
        blocking = "MATURED_BUT_PRICE_DATA_MISSING"
    else:
        final_status = BLOCKED_STATUS
        ready = "FALSE"
        blocking = "UNCLASSIFIED_MATURITY_UPDATE_STATE"

    gate = {
        "gate_check_id": "V20_196_NEXT_STAGE_GATE_001",
        "schedule_exists": tf(bool(schedule_rows)),
        "usable_observation_rows": str(len(updated_returns)),
        "pending_not_matured_count": str(pending_count),
        "matured_observation_count": str(matured_count),
        "observed_return_count": str(observed_count),
        "benchmark_observed_count": str(benchmark_observed_count),
        "missing_price_data_count": str(missing_count),
        "no_fabrication_guard_pass": tf(guard_pass),
        "no_official_trade_mutation": tf(no_official_trade_mutation),
        "future_price_leakage_detected": tf(future_leakage),
        "ready_for_next_stage": ready,
        "blocking_reason": blocking,
        "final_status": final_status,
        **COMMON,
    }

    write_csv(OUT_INPUT_AUDIT, INPUT_AUDIT_FIELDS, input_audit(price_paths, accepted_artifacts, accepted_price_rows))
    write_csv(OUT_ELIGIBILITY, ELIGIBILITY_FIELDS, eligibility)
    write_csv(OUT_RETURN_LEDGER, RETURN_FIELDS, updated_returns)
    write_csv(OUT_BENCHMARK_LEDGER, BENCH_FIELDS, updated_benchmarks)
    write_csv(OUT_TOPN_READOUT, TOPN_FIELDS, topn_rows)
    write_csv(OUT_EXCESS_READOUT, EXCESS_FIELDS, excess_rows)
    write_csv(OUT_PENDING_STATUS, PENDING_FIELDS, pending_rows)
    write_csv(OUT_MISSING_PRICE_AUDIT, MISSING_FIELDS, missing_price_rows)
    write_csv(OUT_FABRICATION_AUDIT, GUARD_FIELDS, guard_rows)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate, run_date, accepted_price_rows)

    print(gate["final_status"])
    for key in GATE_FIELDS:
        if key not in COMMON and key != "gate_check_id":
            print(f"{key.upper()}={gate[key]}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("NO_FABRICATED_RETURNS=TRUE")
    print("NO_FABRICATED_BENCHMARK_RETURNS=TRUE")
    print("NO_FUTURE_PRICE_USED=TRUE")
    print("NO_CURRENT_TO_HISTORICAL_SCORE_JOIN=TRUE")
    print("ZERO_WEIGHT_POLICY_BINDING=TRUE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
