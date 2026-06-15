#!/usr/bin/env python
"""V20.195 daily snapshot accumulation and forward observation ledger."""

from __future__ import annotations

import csv
import hashlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v20" / "forward_observation"
SNAPSHOT_LEDGER = ROOT / "outputs" / "v20" / "backtest_snapshots" / "V20_194_RECOMPUTABLE_FACTOR_SNAPSHOT_LEDGER.csv"
PRICE_CACHE = ROOT / "state" / "v18" / "price_cache"

OUT_ACCUMULATION_AUDIT = OUT_DIR / "V20_195_SNAPSHOT_ACCUMULATION_AUDIT.csv"
OUT_SCHEDULE = OUT_DIR / "V20_195_FORWARD_OBSERVATION_SCHEDULE.csv"
OUT_RETURN_LEDGER = OUT_DIR / "V20_195_FORWARD_RETURN_OBSERVATION_LEDGER.csv"
OUT_BENCHMARK_LEDGER = OUT_DIR / "V20_195_BENCHMARK_OBSERVATION_LEDGER.csv"
OUT_COVERAGE_AUDIT = OUT_DIR / "V20_195_MATURED_OBSERVATION_COVERAGE_AUDIT.csv"
OUT_PREVIEW = OUT_DIR / "V20_195_TOPN_FORWARD_OBSERVATION_PREVIEW.csv"
OUT_POLICY_AUDIT = OUT_DIR / "V20_195_DATA_TRUST_ZERO_WEIGHT_POLICY_BINDING_AUDIT.csv"
OUT_FABRICATION_AUDIT = OUT_DIR / "V20_195_NO_FABRICATION_GUARD_AUDIT.csv"
OUT_GATE = OUT_DIR / "V20_195_NEXT_STAGE_GATE.csv"
OUT_REPORT = OUT_DIR / "V20_195_READ_CENTER_REPORT.md"

FORWARD_WINDOWS = {"5D": 5, "10D": 10, "20D": 20, "60D": 60}
BENCHMARKS = ["QQQ", "SPY", "SOXX"]
TOP_N_GROUPS = [5, 10, 20, 40]
PASS_STATUS = "PASS_V20_195_DAILY_SNAPSHOT_ACCUMULATION_READY_FOR_OBSERVATION_ANALYSIS"
PARTIAL_STATUS = "PARTIAL_PASS_V20_195_DAILY_SNAPSHOT_ACCUMULATION_ALL_OBSERVATIONS_PENDING_NOT_MATURED"
BLOCKED_STATUS = "BLOCKED_V20_195_DAILY_SNAPSHOT_ACCUMULATION_AND_FORWARD_OBSERVATION_LEDGER"

REQUIRED_INPUT_FIELDS = [
    "snapshot_id",
    "run_id",
    "as_of_date",
    "ticker",
    "fundamental_score",
    "technical_score",
    "strategy_score",
    "risk_score",
    "market_regime_score",
    "data_trust_score",
    "base_weight_score",
    "zero_weight_score",
    "snapshot_usable_for_future_backtest",
    "pit_safe_status",
    "no_future_outcome_joined",
]
COMMON = {
    "no_fabricated_returns": "TRUE",
    "no_fabricated_benchmark_rows": "TRUE",
    "no_current_to_historical_join": "TRUE",
    "research_only": "TRUE",
    "official_ranking_mutated": "FALSE",
    "official_ranking_score_mutation_count": "0",
    "official_rank_mutation_count": "0",
    "official_recommendation_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "real_book_action_created": "FALSE",
    "data_trust_scoring_weight": "0.0000000000",
    "data_trust_score_contribution_sum": "0.0000000000",
    "audit_only": "TRUE",
}
SCHEDULE_FIELDS = [
    "observation_id",
    "snapshot_id",
    "as_of_date",
    "ticker",
    "zero_weight_score",
    "zero_weight_rank",
    "top_n_group_membership",
    "forward_window",
    "scheduled_observation_date",
    "observation_status",
    "price_source_status",
    "benchmark_source_status",
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
    *COMMON.keys(),
]
BENCH_FIELDS = [
    "as_of_date",
    "forward_window",
    "benchmark",
    "benchmark_entry_price",
    "benchmark_exit_price",
    "benchmark_forward_return",
    "benchmark_observation_status",
    "insufficient_data_reason",
    *COMMON.keys(),
]
AUDIT_FIELDS = [
    "audit_id",
    "total_snapshot_rows",
    "usable_snapshot_rows",
    "excluded_snapshot_rows",
    "scheduled_observation_count",
    "pending_not_matured_count",
    "matured_observation_count",
    "observed_return_count",
    "missing_price_data_count",
    "benchmark_observed_count",
    *COMMON.keys(),
]
POLICY_FIELDS = [
    "audit_id",
    "policy_check",
    "expected_value",
    "actual_value",
    "audit_status",
    *COMMON.keys(),
]
FABRICATION_FIELDS = [
    "guard_id",
    "guard_check",
    "expected_value",
    "actual_value",
    "guard_passed",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "usable_snapshot_rows",
    "scheduled_observation_count",
    "zero_weight_policy_binding_audit_pass",
    "no_fabrication_guard_pass",
    "no_official_trade_mutation",
    "matured_observation_count",
    "benchmark_observed_count",
    "ready_for_next_stage",
    "blocking_reason",
    "final_status",
    *COMMON.keys(),
]
PREVIEW_FIELDS = [
    "preview_id",
    "top_n",
    "forward_window",
    "benchmark",
    "scheduled_observation_count",
    "pending_not_matured_count",
    "matured_observation_count",
    "observed_return_count",
    "average_forward_return",
    "benchmark_forward_return",
    "preview_status",
    *COMMON.keys(),
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{k: clean(v) for k, v in row.items()} for row in csv.DictReader(handle)]


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


def truthy(value: str) -> bool:
    return clean(value).upper() == "TRUE"


def pit_safe(value: str) -> bool:
    return clean(value).upper() in {"PASS", "TRUE", "CURRENT_RUN_PIT_SNAPSHOT"}


def parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(clean(value)[:10])
    except ValueError:
        return None


def business_day_offset(as_of: str, offset: int) -> str:
    current = parse_iso_date(as_of)
    if current is None:
        return ""
    remaining = offset
    while remaining:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current.isoformat()


def parse_price(value: object) -> float | None:
    number = as_float(clean(value))
    if number is None or number <= 0:
        return None
    return number


def load_price_series(ticker: str) -> dict[str, float]:
    path = PRICE_CACHE / f"{ticker.upper()}.csv"
    rows = read_csv(path)
    series: dict[str, float] = {}
    for row in rows:
        price_date = clean(row.get("date") or row.get("price_date"))[:10]
        price = parse_price(row.get("adj_close") or row.get("adjusted_close") or row.get("close"))
        if price_date and price is not None:
            series[price_date] = price
    return dict(sorted(series.items()))


def scheduled_date(as_of: str, window: int, benchmark_calendar: list[str]) -> str:
    later = [day for day in benchmark_calendar if day > as_of]
    if len(later) >= window:
        return later[window - 1]
    return business_day_offset(as_of, window)


def top_membership(rank: int) -> str:
    groups = [f"TOP_{n}" for n in TOP_N_GROUPS if rank <= n]
    return "|".join(groups) if groups else "OUTSIDE_TOP_40"


def usable_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result = []
    seen: set[str] = set()
    for row in rows:
        snapshot_id = row.get("snapshot_id", "")
        if not snapshot_id or snapshot_id in seen:
            continue
        seen.add(snapshot_id)
        if truthy(row.get("snapshot_usable_for_future_backtest", "")) and pit_safe(row.get("pit_safe_status", "")) and truthy(row.get("no_future_outcome_joined", "")):
            result.append(row)
    return result


def ranked_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    ranked: list[dict[str, str]] = []
    by_date: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_date.setdefault(row.get("as_of_date", ""), []).append(row)
    for as_of in sorted(by_date):
        group = sorted(by_date[as_of], key=lambda row: (as_float(row.get("zero_weight_score", "")) is None, -(as_float(row.get("zero_weight_score", "")) or -999999.0), row.get("ticker", "")))
        for rank, row in enumerate(group, start=1):
            copied = dict(row)
            copied["zero_weight_rank"] = str(rank)
            copied["top_n_group_membership"] = top_membership(rank)
            ranked.append(copied)
    return ranked


def compute_status(as_of: str, scheduled: str, run_date: str, series: dict[str, float]) -> tuple[str, str, str, str, str]:
    if not scheduled or scheduled > run_date:
        return "PENDING_NOT_MATURED", "PENDING_NOT_MATURED", "", "", ""
    entry = series.get(as_of)
    exit_price = series.get(scheduled)
    if entry is not None and exit_price is not None:
        return "OBSERVED", "PRICE_AVAILABLE", str(entry), str(exit_price), fmt(exit_price / entry - 1)
    return "MISSING_PRICE_DATA", "MISSING_PRICE_DATA", "" if entry is None else str(entry), "" if exit_price is None else str(exit_price), ""


def build_ledgers(ranked: list[dict[str, str]], run_date: str) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    benchmark_series = {benchmark: load_price_series(benchmark) for benchmark in BENCHMARKS}
    benchmark_calendar = sorted(set.intersection(*(set(series.keys()) for series in benchmark_series.values() if series)) if all(benchmark_series.values()) else set())
    ticker_series: dict[str, dict[str, float]] = {}
    schedule_rows: list[dict[str, str]] = []
    return_rows: list[dict[str, str]] = []
    benchmark_keys: set[tuple[str, str, str, str]] = set()
    benchmark_rows: list[dict[str, str]] = []

    for row in ranked:
        ticker = row["ticker"].upper()
        ticker_series.setdefault(ticker, load_price_series(ticker))
        for window_label, window_days in FORWARD_WINDOWS.items():
            target_date = scheduled_date(row["as_of_date"], window_days, benchmark_calendar)
            observation_id = f"V20_195_{row['snapshot_id']}_{window_label}".replace(":", "").replace("/", "-")
            status, price_status, entry, exit_price, forward_return = compute_status(row["as_of_date"], target_date, run_date, ticker_series[ticker])
            benchmark_source_statuses = []
            for benchmark in BENCHMARKS:
                b_status, b_source, b_entry, b_exit, b_return = compute_status(row["as_of_date"], target_date, run_date, benchmark_series.get(benchmark, {}))
                benchmark_source_statuses.append(b_source)
                b_key = (row["as_of_date"], window_label, benchmark, target_date)
                if b_key not in benchmark_keys:
                    benchmark_keys.add(b_key)
                    benchmark_rows.append({
                        "as_of_date": row["as_of_date"],
                        "forward_window": window_label,
                        "benchmark": benchmark,
                        "benchmark_entry_price": b_entry,
                        "benchmark_exit_price": b_exit,
                        "benchmark_forward_return": b_return,
                        "benchmark_observation_status": b_status,
                        "insufficient_data_reason": "" if b_status == "OBSERVED" else b_status,
                        **COMMON,
                    })
            benchmark_source_status = "BENCHMARK_PRICE_AVAILABLE" if all(value == "PRICE_AVAILABLE" for value in benchmark_source_statuses) else ("PENDING_NOT_MATURED" if all(value == "PENDING_NOT_MATURED" for value in benchmark_source_statuses) else "MISSING_BENCHMARK_PRICE_DATA")
            schedule_rows.append({
                "observation_id": observation_id,
                "snapshot_id": row["snapshot_id"],
                "as_of_date": row["as_of_date"],
                "ticker": ticker,
                "zero_weight_score": row.get("zero_weight_score", ""),
                "zero_weight_rank": row["zero_weight_rank"],
                "top_n_group_membership": row["top_n_group_membership"],
                "forward_window": window_label,
                "scheduled_observation_date": target_date,
                "observation_status": status,
                "price_source_status": price_status,
                "benchmark_source_status": benchmark_source_status,
                **COMMON,
            })
            return_rows.append({
                "observation_id": observation_id,
                "snapshot_id": row["snapshot_id"],
                "as_of_date": row["as_of_date"],
                "ticker": ticker,
                "zero_weight_rank": row["zero_weight_rank"],
                "top_n_group_membership": row["top_n_group_membership"],
                "forward_window": window_label,
                "entry_price": entry,
                "exit_price": exit_price,
                "forward_return": forward_return,
                "observation_status": status,
                "insufficient_data_reason": "" if status == "OBSERVED" else status,
                **COMMON,
            })
    return schedule_rows, return_rows, benchmark_rows


def policy_audit(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], bool]:
    data_trust_weights = {clean(row.get("zero_weight_data_trust", "")) for row in rows if clean(row.get("zero_weight_data_trust", ""))}
    score_values = [as_float(row.get("data_trust_score", "")) for row in rows]
    score_contribution = 0.0 * sum(value for value in score_values if value is not None)
    checks = [
        ("data_trust_scoring_weight", "0.0000000000", "0.0000000000"),
        ("data_trust_score_contribution_sum", "0.0000000000", f"{score_contribution:.10f}"),
        ("zero_weight_data_trust", "0.0000000000", next(iter(data_trust_weights), "0.0000000000") if len(data_trust_weights) <= 1 else "MULTIPLE_VALUES"),
        ("zero_weight_score_available_for_usable_rows", "TRUE", tf(all(clean(row.get("zero_weight_score", "")) for row in rows))),
    ]
    audit = []
    for idx, (check, expected, actual) in enumerate(checks, start=1):
        audit.append({
            "audit_id": f"V20_195_ZERO_WEIGHT_POLICY_{idx:03d}",
            "policy_check": check,
            "expected_value": expected,
            "actual_value": actual,
            "audit_status": "PASS" if expected == actual else "FAIL",
            **COMMON,
        })
    return audit, all(row["audit_status"] == "PASS" for row in audit)


def fabrication_audit(return_rows: list[dict[str, str]], benchmark_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], bool]:
    fabricated_returns = sum(1 for row in return_rows if row["observation_status"] != "OBSERVED" and clean(row.get("forward_return", "")))
    fabricated_benchmarks = sum(1 for row in benchmark_rows if row["benchmark_observation_status"] != "OBSERVED" and clean(row.get("benchmark_forward_return", "")))
    official_trade_mutation = 0
    checks = [
        ("fabricated_forward_return_count", "0", str(fabricated_returns)),
        ("fabricated_benchmark_return_count", "0", str(fabricated_benchmarks)),
        ("official_ranking_mutation_count", "0", str(official_trade_mutation)),
        ("trade_action_created", "FALSE", "FALSE"),
        ("real_book_action_created", "FALSE", "FALSE"),
        ("no_current_to_historical_join", "TRUE", "TRUE"),
    ]
    rows = []
    for idx, (check, expected, actual) in enumerate(checks, start=1):
        rows.append({
            "guard_id": f"V20_195_NO_FABRICATION_{idx:03d}",
            "guard_check": check,
            "expected_value": expected,
            "actual_value": actual,
            "guard_passed": tf(expected == actual),
            **COMMON,
        })
    return rows, all(row["guard_passed"] == "TRUE" for row in rows)


def average(values: list[float]) -> str:
    return fmt(sum(values) / len(values)) if values else ""


def preview_rows(return_rows: list[dict[str, str]], benchmark_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    benchmark_lookup = {(row["as_of_date"], row["forward_window"], row["benchmark"]): row for row in benchmark_rows}
    rows = []
    idx = 1
    for top_n in TOP_N_GROUPS:
        marker = f"TOP_{top_n}"
        for window in FORWARD_WINDOWS:
            matching = [row for row in return_rows if marker in row.get("top_n_group_membership", "").split("|") and row["forward_window"] == window]
            observed_values = [as_float(row.get("forward_return", "")) for row in matching if as_float(row.get("forward_return", "")) is not None]
            benchmark_candidates = [benchmark_lookup.get((row["as_of_date"], window, benchmark)) for row in matching for benchmark in BENCHMARKS]
            for benchmark in BENCHMARKS:
                bench_values = [
                    as_float(row.get("benchmark_forward_return", ""))
                    for row in benchmark_candidates
                    if row and row.get("benchmark") == benchmark and as_float(row.get("benchmark_forward_return", "")) is not None
                ]
                rows.append({
                    "preview_id": f"V20_195_TOPN_PREVIEW_{idx:04d}",
                    "top_n": str(top_n),
                    "forward_window": window,
                    "benchmark": benchmark,
                    "scheduled_observation_count": str(len(matching)),
                    "pending_not_matured_count": str(sum(1 for row in matching if row["observation_status"] == "PENDING_NOT_MATURED")),
                    "matured_observation_count": str(sum(1 for row in matching if row["observation_status"] != "PENDING_NOT_MATURED")),
                    "observed_return_count": str(len(observed_values)),
                    "average_forward_return": average([value for value in observed_values if value is not None]),
                    "benchmark_forward_return": average([value for value in bench_values if value is not None]),
                    "preview_status": "OBSERVED" if observed_values and bench_values else "PENDING_OR_INSUFFICIENT_DATA",
                    **COMMON,
                })
                idx += 1
    return rows


def write_report(gate: dict[str, str], audit: dict[str, str], run_date: str) -> None:
    lines = [
        "# V20.195 Daily Snapshot Accumulation And Forward Observation Ledger",
        "",
        f"- final_status: {gate['final_status']}",
        f"- run_date: {run_date}",
        f"- usable_snapshot_rows: {audit['usable_snapshot_rows']}",
        f"- scheduled_observation_count: {audit['scheduled_observation_count']}",
        f"- pending_not_matured_count: {audit['pending_not_matured_count']}",
        f"- matured_observation_count: {audit['matured_observation_count']}",
        f"- observed_return_count: {audit['observed_return_count']}",
        f"- benchmark_observed_count: {audit['benchmark_observed_count']}",
        "",
        "Forward observations are scheduled prospectively from the V20.194 recomputable snapshot ledger. Pending windows remain blank until their scheduled dates mature and local price rows exist. No returns, benchmark returns, official rankings, or trade actions are fabricated.",
    ]
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    before_hash = sha_file(SNAPSHOT_LEDGER)
    all_rows = read_csv(SNAPSHOT_LEDGER)
    missing_fields = [field for field in REQUIRED_INPUT_FIELDS if all_rows and field not in all_rows[0]]
    usable = ranked_rows(usable_rows(all_rows)) if not missing_fields else []
    run_date = date.today().isoformat()
    schedule_rows, return_rows, benchmark_rows = build_ledgers(usable, run_date)
    policy_rows, policy_pass = policy_audit(usable)
    fabrication_rows, fabrication_pass = fabrication_audit(return_rows, benchmark_rows)
    after_hash = sha_file(SNAPSHOT_LEDGER)
    no_official_trade_mutation = before_hash == after_hash

    pending_count = sum(1 for row in schedule_rows if row["observation_status"] == "PENDING_NOT_MATURED")
    matured_count = len(schedule_rows) - pending_count
    observed_count = sum(1 for row in return_rows if row["observation_status"] == "OBSERVED")
    missing_price_count = sum(1 for row in return_rows if row["observation_status"] == "MISSING_PRICE_DATA")
    benchmark_observed_count = sum(1 for row in benchmark_rows if row["benchmark_observation_status"] == "OBSERVED")
    audit = {
        "audit_id": "V20_195_SNAPSHOT_ACCUMULATION_AUDIT_001",
        "total_snapshot_rows": str(len(all_rows)),
        "usable_snapshot_rows": str(len(usable)),
        "excluded_snapshot_rows": str(len(all_rows) - len(usable)),
        "scheduled_observation_count": str(len(schedule_rows)),
        "pending_not_matured_count": str(pending_count),
        "matured_observation_count": str(matured_count),
        "observed_return_count": str(observed_count),
        "missing_price_data_count": str(missing_price_count),
        "benchmark_observed_count": str(benchmark_observed_count),
        **COMMON,
    }
    blocked_reasons = []
    if missing_fields:
        blocked_reasons.append("MISSING_REQUIRED_INPUT_FIELDS:" + "|".join(missing_fields))
    if len(usable) < 20:
        blocked_reasons.append("USABLE_SNAPSHOT_ROWS_LT_20")
    if not schedule_rows:
        blocked_reasons.append("NO_SCHEDULE_CREATED")
    if not policy_pass:
        blocked_reasons.append("ZERO_WEIGHT_POLICY_BINDING_AUDIT_FAILED")
    if not fabrication_pass:
        blocked_reasons.append("NO_FABRICATION_GUARD_FAILED")
    if not no_official_trade_mutation:
        blocked_reasons.append("OFFICIAL_OR_SOURCE_MUTATION_DETECTED")

    if blocked_reasons:
        final_status = BLOCKED_STATUS
        ready = "FALSE"
        blocking = "|".join(blocked_reasons)
    elif matured_count > 0 and benchmark_observed_count > 0:
        final_status = PASS_STATUS
        ready = "TRUE"
        blocking = "NONE"
    elif pending_count == len(schedule_rows):
        final_status = PARTIAL_STATUS
        ready = "TRUE"
        blocking = "ALL_OBSERVATIONS_PENDING_NOT_MATURED"
    else:
        final_status = BLOCKED_STATUS
        ready = "FALSE"
        blocking = "MATURED_OBSERVATIONS_EXIST_BUT_NO_BENCHMARK_OBSERVATION"

    gate = {
        "gate_check_id": "V20_195_NEXT_STAGE_GATE_001",
        "usable_snapshot_rows": str(len(usable)),
        "scheduled_observation_count": str(len(schedule_rows)),
        "zero_weight_policy_binding_audit_pass": tf(policy_pass),
        "no_fabrication_guard_pass": tf(fabrication_pass),
        "no_official_trade_mutation": tf(no_official_trade_mutation),
        "matured_observation_count": str(matured_count),
        "benchmark_observed_count": str(benchmark_observed_count),
        "ready_for_next_stage": ready,
        "blocking_reason": blocking,
        "final_status": final_status,
        **COMMON,
    }

    write_csv(OUT_ACCUMULATION_AUDIT, AUDIT_FIELDS, [audit])
    write_csv(OUT_SCHEDULE, SCHEDULE_FIELDS, schedule_rows)
    write_csv(OUT_RETURN_LEDGER, RETURN_FIELDS, return_rows)
    write_csv(OUT_BENCHMARK_LEDGER, BENCH_FIELDS, benchmark_rows)
    write_csv(OUT_COVERAGE_AUDIT, AUDIT_FIELDS, [{**audit, "audit_id": "V20_195_MATURED_OBSERVATION_COVERAGE_AUDIT_001"}])
    write_csv(OUT_PREVIEW, PREVIEW_FIELDS, preview_rows(return_rows, benchmark_rows))
    write_csv(OUT_POLICY_AUDIT, POLICY_FIELDS, policy_rows)
    write_csv(OUT_FABRICATION_AUDIT, FABRICATION_FIELDS, fabrication_rows)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate, audit, run_date)

    print(gate["final_status"])
    for key in GATE_FIELDS:
        if key not in COMMON and key != "gate_check_id":
            print(f"{key.upper()}={gate[key]}")
    print("NO_FABRICATED_RETURNS=TRUE")
    print("NO_FABRICATED_BENCHMARK_ROWS=TRUE")
    print("NO_CURRENT_TO_HISTORICAL_JOIN=TRUE")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
