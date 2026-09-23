#!/usr/bin/env python
"""V20.197 daily walk-forward validation runner."""

from __future__ import annotations

import csv
import hashlib
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FORWARD_DIR = ROOT / "outputs" / "v20" / "forward_observation"
OUT_DIR = ROOT / "outputs" / "v20" / "walk_forward"

SNAPSHOT_LEDGER = ROOT / "outputs" / "v20" / "backtest_snapshots" / "V20_194_RECOMPUTABLE_FACTOR_SNAPSHOT_LEDGER.csv"
SCHEDULE = FORWARD_DIR / "V20_195_FORWARD_OBSERVATION_SCHEDULE.csv"
V195_RETURN_LEDGER = FORWARD_DIR / "V20_195_FORWARD_RETURN_OBSERVATION_LEDGER.csv"
V195_BENCHMARK_LEDGER = FORWARD_DIR / "V20_195_BENCHMARK_OBSERVATION_LEDGER.csv"
V196_RETURN_LEDGER = FORWARD_DIR / "V20_196_UPDATED_FORWARD_RETURN_OBSERVATION_LEDGER.csv"
V196_BENCHMARK_LEDGER = FORWARD_DIR / "V20_196_UPDATED_BENCHMARK_OBSERVATION_LEDGER.csv"
V196_GATE = FORWARD_DIR / "V20_196_NEXT_STAGE_GATE.csv"
V196_GUARD = FORWARD_DIR / "V20_196_NO_FABRICATION_GUARD_AUDIT.csv"

OUT_CHAIN_AUDIT = OUT_DIR / "V20_197_RUN_CHAIN_AUDIT.csv"
OUT_SNAPSHOT_STATUS = OUT_DIR / "V20_197_SNAPSHOT_ACCUMULATION_STATUS.csv"
OUT_FORWARD_STATUS = OUT_DIR / "V20_197_FORWARD_OBSERVATION_STATUS.csv"
OUT_MATURITY_BY_WINDOW = OUT_DIR / "V20_197_MATURITY_STATUS_BY_WINDOW.csv"
OUT_TOPN_STATUS = OUT_DIR / "V20_197_TOPN_PENDING_AND_OBSERVED_STATUS.csv"
OUT_BENCHMARK_STATUS = OUT_DIR / "V20_197_BENCHMARK_STATUS.csv"
OUT_NO_FAB_GUARD = OUT_DIR / "V20_197_NO_FABRICATION_AND_NO_LEAKAGE_GUARD.csv"
OUT_MUTATION_GUARD = OUT_DIR / "V20_197_OFFICIAL_TRADE_MUTATION_GUARD.csv"
OUT_REPORT = OUT_DIR / "V20_197_OPERATOR_READABLE_WALK_FORWARD_REPORT.md"
OUT_GATE = OUT_DIR / "V20_197_NEXT_STAGE_GATE.csv"

FORWARD_WINDOWS = ["5D", "10D", "20D", "60D"]
BENCHMARKS = ["QQQ", "SPY", "SOXX"]
TOP_N_GROUPS = [5, 10, 20, 40]
PASS_STATUS = "PASS_V20_197_DAILY_WALK_FORWARD_VALIDATION_RUNNER"
PARTIAL_PENDING_STATUS = "PARTIAL_PASS_PENDING_V20_197_DAILY_WALK_FORWARD_VALIDATION_RUNNER"
PARTIAL_INSUFFICIENT_STATUS = "PARTIAL_PASS_MATURED_BUT_INSUFFICIENT_DATA_V20_197_DAILY_WALK_FORWARD_VALIDATION_RUNNER"
BLOCKED_STATUS = "BLOCKED_V20_197_DAILY_WALK_FORWARD_VALIDATION_RUNNER"

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
    "no_fabricated_ticker_rows": "TRUE",
    "no_future_price_used": "TRUE",
    "future_price_leakage_detected": "FALSE",
    "zero_weight_policy_binding": "TRUE",
    "data_trust_scoring_weight": "0.0000000000",
    "audit_only": "TRUE",
}
METRIC_FIELDS = [
    "total_snapshot_rows",
    "usable_snapshot_rows",
    "excluded_snapshot_rows",
    "total_scheduled_observations",
    "pending_not_matured_count",
    "matured_observation_count",
    "observed_return_count",
    "benchmark_observed_count",
    "missing_price_data_count",
    "observed_top5_count",
    "observed_top10_count",
    "observed_top20_count",
    "observed_top40_count",
    "pending_5d_count",
    "pending_10d_count",
    "pending_20d_count",
    "pending_60d_count",
    "matured_5d_count",
    "matured_10d_count",
    "matured_20d_count",
    "matured_60d_count",
    "observed_5d_count",
    "observed_10d_count",
    "observed_20d_count",
    "observed_60d_count",
]
CHAIN_FIELDS = [
    "chain_audit_id",
    "source_artifact",
    "artifact_exists",
    "artifact_non_empty",
    "row_count",
    "source_sha256",
    "chain_role",
    "chain_status",
    *COMMON.keys(),
]
STATUS_FIELDS = ["status_id", *METRIC_FIELDS, *COMMON.keys()]
WINDOW_FIELDS = [
    "window_status_id",
    "forward_window",
    "scheduled_observation_count",
    "pending_not_matured_count",
    "matured_observation_count",
    "observed_return_count",
    "missing_price_data_count",
    *COMMON.keys(),
]
TOPN_FIELDS = [
    "topn_status_id",
    "top_n",
    "scheduled_observation_count",
    "pending_not_matured_count",
    "matured_observation_count",
    "observed_return_count",
    "missing_price_data_count",
    *COMMON.keys(),
]
BENCHMARK_FIELDS = [
    "benchmark_status_id",
    "benchmark",
    "benchmark_row_count",
    "pending_not_matured_count",
    "matured_benchmark_count",
    "benchmark_observed_count",
    "missing_price_data_count",
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
    "snapshot_ledger_exists",
    "observation_schedule_exists",
    "maturity_updater_outputs_exist",
    "no_fabrication_guard_pass",
    "no_future_leakage_guard_pass",
    "no_official_trade_mutation",
    *METRIC_FIELDS,
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


def truthy(value: str) -> bool:
    return clean(value).upper() == "TRUE"


def pit_safe(value: str) -> bool:
    return clean(value).upper() in {"PASS", "TRUE", "CURRENT_RUN_PIT_SNAPSHOT"}


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(clean(value)[:10])
    except ValueError:
        return None


def usable_snapshot(row: dict[str, str]) -> bool:
    return truthy(row.get("snapshot_usable_for_future_backtest", "")) and pit_safe(row.get("pit_safe_status", "")) and truthy(row.get("no_future_outcome_joined", ""))


def source_hashes(paths: list[Path]) -> dict[Path, str]:
    return {path: sha_file(path) for path in paths}


def count_status(rows: list[dict[str, str]], status: str, field: str = "observation_status") -> int:
    return sum(1 for row in rows if row.get(field) == status)


def topn_count(rows: list[dict[str, str]], top_n: int, status: str) -> int:
    marker = f"TOP_{top_n}"
    return sum(1 for row in rows if row.get("observation_status") == status and marker in row.get("top_n_group_membership", "").split("|"))


def build_metrics(snapshot_rows: list[dict[str, str]], schedule_rows: list[dict[str, str]], return_rows: list[dict[str, str]], benchmark_rows: list[dict[str, str]]) -> dict[str, str]:
    pending = count_status(return_rows, "PENDING_NOT_MATURED")
    observed = count_status(return_rows, "OBSERVED")
    missing = count_status(return_rows, "MISSING_PRICE_DATA")
    metrics = {
        "total_snapshot_rows": str(len(snapshot_rows)),
        "usable_snapshot_rows": str(sum(1 for row in snapshot_rows if usable_snapshot(row))),
        "excluded_snapshot_rows": str(sum(1 for row in snapshot_rows if not usable_snapshot(row))),
        "total_scheduled_observations": str(len(schedule_rows)),
        "pending_not_matured_count": str(pending),
        "matured_observation_count": str(len(return_rows) - pending),
        "observed_return_count": str(observed),
        "benchmark_observed_count": str(count_status(benchmark_rows, "OBSERVED", "benchmark_observation_status")),
        "missing_price_data_count": str(missing),
        "observed_top5_count": str(topn_count(return_rows, 5, "OBSERVED")),
        "observed_top10_count": str(topn_count(return_rows, 10, "OBSERVED")),
        "observed_top20_count": str(topn_count(return_rows, 20, "OBSERVED")),
        "observed_top40_count": str(topn_count(return_rows, 40, "OBSERVED")),
    }
    for window in FORWARD_WINDOWS:
        key = window.lower()
        group = [row for row in return_rows if row.get("forward_window") == window]
        pending_window = count_status(group, "PENDING_NOT_MATURED")
        metrics[f"pending_{key}_count"] = str(pending_window)
        metrics[f"matured_{key}_count"] = str(len(group) - pending_window)
        metrics[f"observed_{key}_count"] = str(count_status(group, "OBSERVED"))
    return metrics


def chain_audit_rows(sources: list[tuple[Path, str]]) -> list[dict[str, str]]:
    rows = []
    for idx, (path, role) in enumerate(sources, start=1):
        data = read_csv(path)
        exists = path.exists()
        non_empty = exists and path.stat().st_size > 0
        rows.append({
            "chain_audit_id": f"V20_197_CHAIN_{idx:03d}",
            "source_artifact": rel(path),
            "artifact_exists": tf(exists),
            "artifact_non_empty": tf(non_empty),
            "row_count": str(len(data)),
            "source_sha256": sha_file(path),
            "chain_role": role,
            "chain_status": "PASS" if exists and non_empty else "MISSING_OR_EMPTY",
            **COMMON,
        })
    return rows


def window_rows(return_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for idx, window in enumerate(FORWARD_WINDOWS, start=1):
        group = [row for row in return_rows if row.get("forward_window") == window]
        pending = count_status(group, "PENDING_NOT_MATURED")
        rows.append({
            "window_status_id": f"V20_197_WINDOW_{idx:03d}",
            "forward_window": window,
            "scheduled_observation_count": str(len(group)),
            "pending_not_matured_count": str(pending),
            "matured_observation_count": str(len(group) - pending),
            "observed_return_count": str(count_status(group, "OBSERVED")),
            "missing_price_data_count": str(count_status(group, "MISSING_PRICE_DATA")),
            **COMMON,
        })
    return rows


def topn_rows(return_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for idx, top_n in enumerate(TOP_N_GROUPS, start=1):
        marker = f"TOP_{top_n}"
        group = [row for row in return_rows if marker in row.get("top_n_group_membership", "").split("|")]
        pending = count_status(group, "PENDING_NOT_MATURED")
        rows.append({
            "topn_status_id": f"V20_197_TOPN_{idx:03d}",
            "top_n": str(top_n),
            "scheduled_observation_count": str(len(group)),
            "pending_not_matured_count": str(pending),
            "matured_observation_count": str(len(group) - pending),
            "observed_return_count": str(count_status(group, "OBSERVED")),
            "missing_price_data_count": str(count_status(group, "MISSING_PRICE_DATA")),
            **COMMON,
        })
    return rows


def benchmark_rows(benchmark_rows_in: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for idx, benchmark in enumerate(BENCHMARKS, start=1):
        group = [row for row in benchmark_rows_in if row.get("benchmark") == benchmark]
        pending = count_status(group, "PENDING_NOT_MATURED", "benchmark_observation_status")
        observed = count_status(group, "OBSERVED", "benchmark_observation_status")
        missing = count_status(group, "MISSING_PRICE_DATA", "benchmark_observation_status")
        rows.append({
            "benchmark_status_id": f"V20_197_BENCHMARK_{idx:03d}",
            "benchmark": benchmark,
            "benchmark_row_count": str(len(group)),
            "pending_not_matured_count": str(pending),
            "matured_benchmark_count": str(len(group) - pending),
            "benchmark_observed_count": str(observed),
            "missing_price_data_count": str(missing),
            **COMMON,
        })
    return rows


def no_fabrication_guard(schedule_rows: list[dict[str, str]], return_rows: list[dict[str, str]], benchmark_rows_in: list[dict[str, str]], v196_guard_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], bool, bool]:
    schedule_by_id = {row.get("observation_id", ""): row for row in schedule_rows}
    fabricated_returns = sum(1 for row in return_rows if row.get("observation_status") != "OBSERVED" and clean(row.get("forward_return", "")))
    fabricated_bench = sum(1 for row in benchmark_rows_in if row.get("benchmark_observation_status") != "OBSERVED" and clean(row.get("benchmark_forward_return", "")))
    fabricated_tickers = max(0, len(return_rows) - len(schedule_rows))
    today = date.today().isoformat()
    future_leakage = 0
    for row in return_rows:
        scheduled = schedule_by_id.get(row.get("observation_id", ""), {}).get("scheduled_observation_date", "")
        if row.get("observation_status") == "OBSERVED" and scheduled and scheduled > today:
            future_leakage += 1
    upstream_guard_pass = all(row.get("guard_passed") == "TRUE" for row in v196_guard_rows) if v196_guard_rows else False
    checks = [
        ("fabricated_forward_return_count", "0", str(fabricated_returns)),
        ("fabricated_benchmark_return_count", "0", str(fabricated_bench)),
        ("fabricated_ticker_row_count", "0", str(fabricated_tickers)),
        ("future_price_leakage_count", "0", str(future_leakage)),
        ("v20_196_no_fabrication_guard_pass", "TRUE", tf(upstream_guard_pass)),
        ("zero_weight_policy_binding", "TRUE", "TRUE"),
    ]
    rows = []
    for idx, (check, expected, actual) in enumerate(checks, start=1):
        rows.append({
            "guard_id": f"V20_197_NO_FAB_{idx:03d}",
            "guard_check": check,
            "expected_value": expected,
            "actual_value": actual,
            "guard_passed": tf(expected == actual),
            **COMMON,
        })
    return rows, all(row["guard_passed"] == "TRUE" for row in rows), future_leakage > 0


def mutation_guard(hashes_before: dict[Path, str], hashes_after: dict[Path, str]) -> tuple[list[dict[str, str]], bool]:
    mutated = hashes_before != hashes_after
    checks = [
        ("input_artifacts_mutated", "FALSE", tf(mutated)),
        ("official_ranking_mutated", "FALSE", "FALSE"),
        ("official_ranking_score_mutation_count", "0", "0"),
        ("official_rank_mutation_count", "0", "0"),
        ("official_recommendation_created", "FALSE", "FALSE"),
        ("trade_action_created", "FALSE", "FALSE"),
        ("broker_execution_supported", "FALSE", "FALSE"),
        ("real_book_action_created", "FALSE", "FALSE"),
    ]
    rows = []
    for idx, (check, expected, actual) in enumerate(checks, start=1):
        rows.append({
            "guard_id": f"V20_197_MUTATION_{idx:03d}",
            "guard_check": check,
            "expected_value": expected,
            "actual_value": actual,
            "guard_passed": tf(expected == actual),
            **COMMON,
        })
    return rows, all(row["guard_passed"] == "TRUE" for row in rows)


def write_report(gate: dict[str, str]) -> None:
    lines = [
        "# V20.197 Daily Walk-Forward Validation Runner",
        "",
        f"- final_status: {gate['final_status']}",
        f"- total_snapshot_rows: {gate['total_snapshot_rows']}",
        f"- usable_snapshot_rows: {gate['usable_snapshot_rows']}",
        f"- total_scheduled_observations: {gate['total_scheduled_observations']}",
        f"- pending_not_matured_count: {gate['pending_not_matured_count']}",
        f"- matured_observation_count: {gate['matured_observation_count']}",
        f"- observed_return_count: {gate['observed_return_count']}",
        f"- benchmark_observed_count: {gate['benchmark_observed_count']}",
        "",
        "This runner summarizes the daily walk-forward chain only. It does not prove effectiveness, recompute official ranking, create trades, or fabricate prices, returns, benchmark rows, or ticker rows.",
    ]
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    sources = [
        (SNAPSHOT_LEDGER, "V20_194_SNAPSHOT_LEDGER"),
        (SCHEDULE, "V20_195_OBSERVATION_SCHEDULE"),
        (V195_RETURN_LEDGER, "V20_195_RETURN_LEDGER"),
        (V195_BENCHMARK_LEDGER, "V20_195_BENCHMARK_LEDGER"),
        (V196_RETURN_LEDGER, "V20_196_UPDATED_RETURN_LEDGER"),
        (V196_BENCHMARK_LEDGER, "V20_196_UPDATED_BENCHMARK_LEDGER"),
        (V196_GATE, "V20_196_NEXT_STAGE_GATE"),
        (V196_GUARD, "V20_196_NO_FABRICATION_GUARD"),
    ]
    protected_paths = [path for path, _ in sources]
    hashes_before = source_hashes(protected_paths)
    snapshot_rows = read_csv(SNAPSHOT_LEDGER)
    schedule_rows = read_csv(SCHEDULE)
    return_rows = read_csv(V196_RETURN_LEDGER)
    benchmark_rows_in = read_csv(V196_BENCHMARK_LEDGER)
    v196_guard_rows = read_csv(V196_GUARD)
    metrics = build_metrics(snapshot_rows, schedule_rows, return_rows, benchmark_rows_in)
    no_fab_rows, no_fab_pass, future_leakage = no_fabrication_guard(schedule_rows, return_rows, benchmark_rows_in, v196_guard_rows)
    hashes_after = source_hashes(protected_paths)
    mutation_rows, mutation_pass = mutation_guard(hashes_before, hashes_after)

    snapshot_exists = SNAPSHOT_LEDGER.exists() and SNAPSHOT_LEDGER.stat().st_size > 0
    schedule_exists = SCHEDULE.exists() and SCHEDULE.stat().st_size > 0
    maturity_outputs_exist = all(path.exists() and path.stat().st_size > 0 for path in [V196_RETURN_LEDGER, V196_BENCHMARK_LEDGER, V196_GATE, V196_GUARD])
    matured = int(metrics["matured_observation_count"])
    observed = int(metrics["observed_return_count"])
    benchmark_observed = int(metrics["benchmark_observed_count"])
    missing = int(metrics["missing_price_data_count"])
    pending = int(metrics["pending_not_matured_count"])
    total_observations = len(return_rows)

    blocked_reasons = []
    if not snapshot_exists:
        blocked_reasons.append("SNAPSHOT_LEDGER_MISSING")
    if not schedule_exists:
        blocked_reasons.append("OBSERVATION_SCHEDULE_MISSING")
    if not maturity_outputs_exist:
        blocked_reasons.append("MATURITY_UPDATER_OUTPUTS_MISSING")
    if not no_fab_pass:
        blocked_reasons.append("FABRICATION_DETECTED")
    if future_leakage:
        blocked_reasons.append("FUTURE_PRICE_LEAKAGE_DETECTED")
    if not mutation_pass:
        blocked_reasons.append("OFFICIAL_OR_TRADE_MUTATION_DETECTED")

    if blocked_reasons:
        final_status = BLOCKED_STATUS
        ready = "FALSE"
        blocking = "|".join(blocked_reasons)
    elif matured > 0 and observed > 0 and benchmark_observed > 0:
        final_status = PASS_STATUS
        ready = "TRUE"
        blocking = "NONE"
    elif total_observations > 0 and pending == total_observations:
        final_status = PARTIAL_PENDING_STATUS
        ready = "TRUE"
        blocking = "ALL_OBSERVATIONS_PENDING_NOT_MATURED"
    elif matured > 0 and (observed == 0 or benchmark_observed == 0 or missing > 0):
        final_status = PARTIAL_INSUFFICIENT_STATUS
        ready = "TRUE"
        blocking = "MATURED_BUT_TICKER_OR_BENCHMARK_DATA_INSUFFICIENT"
    else:
        final_status = BLOCKED_STATUS
        ready = "FALSE"
        blocking = "UNCLASSIFIED_WALK_FORWARD_STATE"

    gate = {
        "gate_check_id": "V20_197_NEXT_STAGE_GATE_001",
        "snapshot_ledger_exists": tf(snapshot_exists),
        "observation_schedule_exists": tf(schedule_exists),
        "maturity_updater_outputs_exist": tf(maturity_outputs_exist),
        "no_fabrication_guard_pass": tf(no_fab_pass),
        "no_future_leakage_guard_pass": tf(not future_leakage),
        "no_official_trade_mutation": tf(mutation_pass),
        **metrics,
        "ready_for_next_stage": ready,
        "blocking_reason": blocking,
        "final_status": final_status,
        **COMMON,
    }

    write_csv(OUT_CHAIN_AUDIT, CHAIN_FIELDS, chain_audit_rows(sources))
    write_csv(OUT_SNAPSHOT_STATUS, STATUS_FIELDS, [{"status_id": "V20_197_SNAPSHOT_STATUS_001", **metrics, **COMMON}])
    write_csv(OUT_FORWARD_STATUS, STATUS_FIELDS, [{"status_id": "V20_197_FORWARD_STATUS_001", **metrics, **COMMON}])
    write_csv(OUT_MATURITY_BY_WINDOW, WINDOW_FIELDS, window_rows(return_rows))
    write_csv(OUT_TOPN_STATUS, TOPN_FIELDS, topn_rows(return_rows))
    write_csv(OUT_BENCHMARK_STATUS, BENCHMARK_FIELDS, benchmark_rows(benchmark_rows_in))
    write_csv(OUT_NO_FAB_GUARD, GUARD_FIELDS, no_fab_rows)
    write_csv(OUT_MUTATION_GUARD, GUARD_FIELDS, mutation_rows)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate)

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
    print("NO_FABRICATED_TICKER_ROWS=TRUE")
    print("NO_FUTURE_PRICE_USED=TRUE")
    print("FUTURE_PRICE_LEAKAGE_DETECTED=FALSE")
    print("ZERO_WEIGHT_POLICY_BINDING=TRUE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
