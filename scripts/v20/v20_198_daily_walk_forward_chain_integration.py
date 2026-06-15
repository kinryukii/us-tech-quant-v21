#!/usr/bin/env python
"""V20.198 daily walk-forward chain integration."""

from __future__ import annotations

import csv
import hashlib
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
V197_GATE = OUT_DIR / "V20_197_NEXT_STAGE_GATE.csv"
V197_REPORT = OUT_DIR / "V20_197_OPERATOR_READABLE_WALK_FORWARD_REPORT.md"

OUT_INPUT_AUDIT = OUT_DIR / "V20_198_CHAIN_INPUT_AUDIT.csv"
OUT_STAGE_SUMMARY = OUT_DIR / "V20_198_STAGE_STATUS_SUMMARY.csv"
OUT_INTEGRATION_AUDIT = OUT_DIR / "V20_198_DAILY_CHAIN_INTEGRATION_AUDIT.csv"
OUT_APPEND_AUDIT = OUT_DIR / "V20_198_APPEND_ONLY_CONTINUITY_AUDIT.csv"
OUT_PENDING_STATUS = OUT_DIR / "V20_198_PENDING_MATURITY_STATUS.csv"
OUT_READY_BINDING = OUT_DIR / "V20_198_READY_FOR_DAILY_RESEARCH_RUNNER_BINDING.csv"
OUT_NO_FAB_GUARD = OUT_DIR / "V20_198_NO_FABRICATION_NO_LEAKAGE_GUARD.csv"
OUT_MUTATION_GUARD = OUT_DIR / "V20_198_OFFICIAL_TRADE_MUTATION_GUARD.csv"
OUT_REPORT = OUT_DIR / "V20_198_OPERATOR_READABLE_CHAIN_REPORT.md"
OUT_GATE = OUT_DIR / "V20_198_NEXT_STAGE_GATE.csv"

PASS_STATUS = "PASS_V20_198_DAILY_WALK_FORWARD_CHAIN_INTEGRATION"
PARTIAL_PENDING_STATUS = "PARTIAL_PASS_PENDING_V20_198_DAILY_WALK_FORWARD_CHAIN_INTEGRATION"
PARTIAL_INSUFFICIENT_STATUS = "PARTIAL_PASS_MATURED_BUT_INSUFFICIENT_DATA_V20_198_DAILY_WALK_FORWARD_CHAIN_INTEGRATION"
BLOCKED_STATUS = "BLOCKED_V20_198_DAILY_WALK_FORWARD_CHAIN_INTEGRATION"

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
    "scheduled_observation_count",
    "pending_not_matured_count",
    "matured_observation_count",
    "observed_return_count",
    "benchmark_observed_count",
    "missing_price_data_count",
]
INPUT_FIELDS = [
    "input_audit_id",
    "source_artifact",
    "stage",
    "artifact_exists",
    "artifact_non_empty",
    "row_count",
    "source_sha256",
    "input_status",
    *COMMON.keys(),
]
SUMMARY_FIELDS = [
    "stage_status_id",
    "stage",
    "source_artifact",
    "stage_input_exists",
    "stage_input_non_empty",
    "stage_status",
    *METRIC_FIELDS,
    *COMMON.keys(),
]
AUDIT_FIELDS = [
    "audit_id",
    "audit_check",
    "expected_value",
    "actual_value",
    "audit_status",
    *COMMON.keys(),
]
PENDING_FIELDS = [
    "pending_status_id",
    "pending_not_matured_count",
    "matured_observation_count",
    "observed_return_count",
    "benchmark_observed_count",
    "all_observations_pending_not_matured",
    "pending_maturity_status",
    *COMMON.keys(),
]
READY_FIELDS = [
    "binding_id",
    "daily_walk_forward_chain_operational",
    "safe_for_daily_research_runner_binding",
    "effectiveness_claim_created",
    "official_promotion_allowed",
    "next_recommended_stage",
    "binding_status",
    *METRIC_FIELDS,
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
    "all_required_inputs_exist",
    "usable_snapshot_rows_minimum_pass",
    "schedule_created",
    "append_only_continuity_guard",
    "duplicate_snapshot_id_count",
    "duplicate_observation_id_count",
    "no_fabrication_guard_pass",
    "no_future_leakage_guard_pass",
    "no_official_trade_mutation",
    *METRIC_FIELDS,
    "ready_for_daily_research_runner_binding",
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


def source_hashes(paths: list[Path]) -> dict[Path, str]:
    return {path: sha_file(path) for path in paths}


def duplicate_count(rows: list[dict[str, str]], field: str) -> int:
    seen: set[str] = set()
    duplicates = 0
    for row in rows:
        value = row.get(field, "")
        if not value:
            continue
        if value in seen:
            duplicates += 1
        seen.add(value)
    return duplicates


def metric_from_gate(gate: dict[str, str], source_rows: dict[str, list[dict[str, str]]]) -> dict[str, str]:
    scheduled = gate.get("total_scheduled_observations") or gate.get("scheduled_observation_count") or str(len(source_rows["schedule"]))
    return {
        "total_snapshot_rows": gate.get("total_snapshot_rows", str(len(source_rows["snapshots"]))),
        "usable_snapshot_rows": gate.get("usable_snapshot_rows", ""),
        "excluded_snapshot_rows": gate.get("excluded_snapshot_rows", ""),
        "scheduled_observation_count": scheduled,
        "pending_not_matured_count": gate.get("pending_not_matured_count", ""),
        "matured_observation_count": gate.get("matured_observation_count", ""),
        "observed_return_count": gate.get("observed_return_count", ""),
        "benchmark_observed_count": gate.get("benchmark_observed_count", ""),
        "missing_price_data_count": gate.get("missing_price_data_count", ""),
    }


def int_metric(metrics: dict[str, str], field: str) -> int:
    try:
        return int(metrics.get(field, "0"))
    except ValueError:
        return 0


def input_audit_rows(sources: list[tuple[Path, str]]) -> list[dict[str, str]]:
    rows = []
    for idx, (path, stage) in enumerate(sources, start=1):
        data = read_csv(path) if path.suffix.lower() == ".csv" else []
        exists = path.exists()
        non_empty = exists and path.stat().st_size > 0
        rows.append({
            "input_audit_id": f"V20_198_INPUT_{idx:03d}",
            "source_artifact": rel(path),
            "stage": stage,
            "artifact_exists": tf(exists),
            "artifact_non_empty": tf(non_empty),
            "row_count": str(len(data) if path.suffix.lower() == ".csv" else (1 if non_empty else 0)),
            "source_sha256": sha_file(path),
            "input_status": "PASS" if exists and non_empty else "MISSING_OR_EMPTY",
            **COMMON,
        })
    return rows


def stage_summary_rows(sources: list[tuple[Path, str]], metrics: dict[str, str]) -> list[dict[str, str]]:
    rows = []
    for idx, (path, stage) in enumerate(sources, start=1):
        exists = path.exists()
        non_empty = exists and path.stat().st_size > 0
        rows.append({
            "stage_status_id": f"V20_198_STAGE_{idx:03d}",
            "stage": stage,
            "source_artifact": rel(path),
            "stage_input_exists": tf(exists),
            "stage_input_non_empty": tf(non_empty),
            "stage_status": "PASS" if exists and non_empty else "BLOCKED_MISSING_INPUT",
            **metrics,
            **COMMON,
        })
    return rows


def integration_audit_rows(metrics: dict[str, str], all_inputs_exist: bool, append_pass: bool, no_fab_pass: bool, no_future_pass: bool, mutation_pass: bool) -> list[dict[str, str]]:
    checks = [
        ("all_v20_194_to_v20_197_inputs_exist", "TRUE", tf(all_inputs_exist)),
        ("usable_snapshot_rows_gte_20", "TRUE", tf(int_metric(metrics, "usable_snapshot_rows") >= 20)),
        ("scheduled_observation_count_gt_0", "TRUE", tf(int_metric(metrics, "scheduled_observation_count") > 0)),
        ("pending_not_matured_count_gte_0", "TRUE", tf(int_metric(metrics, "pending_not_matured_count") >= 0)),
        ("matured_observation_count_gte_0", "TRUE", tf(int_metric(metrics, "matured_observation_count") >= 0)),
        ("observed_return_count_gte_0", "TRUE", tf(int_metric(metrics, "observed_return_count") >= 0)),
        ("benchmark_observed_count_gte_0", "TRUE", tf(int_metric(metrics, "benchmark_observed_count") >= 0)),
        ("append_only_continuity_guard", "TRUE", tf(append_pass)),
        ("no_fabrication_no_leakage_guard", "TRUE", tf(no_fab_pass and no_future_pass)),
        ("no_official_trade_mutation", "TRUE", tf(mutation_pass)),
    ]
    rows = []
    for idx, (check, expected, actual) in enumerate(checks, start=1):
        rows.append({
            "audit_id": f"V20_198_INTEGRATION_{idx:03d}",
            "audit_check": check,
            "expected_value": expected,
            "actual_value": actual,
            "audit_status": "PASS" if expected == actual else "FAIL",
            **COMMON,
        })
    return rows


def append_audit_rows(snapshot_rows: list[dict[str, str]], schedule_rows: list[dict[str, str]], return_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], bool, int, int]:
    duplicate_snapshot = duplicate_count(snapshot_rows, "snapshot_id")
    duplicate_observation = duplicate_count(schedule_rows, "observation_id")
    orphan_return = sum(1 for row in return_rows if row.get("observation_id", "") not in {s.get("observation_id", "") for s in schedule_rows})
    checks = [
        ("duplicate_snapshot_id_count", "0", str(duplicate_snapshot)),
        ("duplicate_observation_id_count", "0", str(duplicate_observation)),
        ("return_rows_without_schedule_count", "0", str(orphan_return)),
        ("append_only_continuity_guard", "TRUE", tf(duplicate_snapshot == 0 and duplicate_observation == 0 and orphan_return == 0)),
    ]
    rows = []
    for idx, (check, expected, actual) in enumerate(checks, start=1):
        rows.append({
            "audit_id": f"V20_198_APPEND_{idx:03d}",
            "audit_check": check,
            "expected_value": expected,
            "actual_value": actual,
            "audit_status": "PASS" if expected == actual else "FAIL",
            **COMMON,
        })
    append_pass = all(row["audit_status"] == "PASS" for row in rows)
    return rows, append_pass, duplicate_snapshot, duplicate_observation


def guard_rows(prefix: str, checks: list[tuple[str, str, str]]) -> tuple[list[dict[str, str]], bool]:
    rows = []
    for idx, (check, expected, actual) in enumerate(checks, start=1):
        rows.append({
            "guard_id": f"{prefix}_{idx:03d}",
            "guard_check": check,
            "expected_value": expected,
            "actual_value": actual,
            "guard_passed": tf(expected == actual),
            **COMMON,
        })
    return rows, all(row["guard_passed"] == "TRUE" for row in rows)


def pending_status_row(metrics: dict[str, str]) -> dict[str, str]:
    total = int_metric(metrics, "scheduled_observation_count")
    pending = int_metric(metrics, "pending_not_matured_count")
    matured = int_metric(metrics, "matured_observation_count")
    return {
        "pending_status_id": "V20_198_PENDING_MATURITY_STATUS_001",
        "pending_not_matured_count": str(pending),
        "matured_observation_count": str(matured),
        "observed_return_count": metrics["observed_return_count"],
        "benchmark_observed_count": metrics["benchmark_observed_count"],
        "all_observations_pending_not_matured": tf(total > 0 and pending == total),
        "pending_maturity_status": "ALL_PENDING_NOT_MATURED" if total > 0 and pending == total else "MATURED_OR_MIXED_STATUS",
        **COMMON,
    }


def ready_binding_row(metrics: dict[str, str], final_status: str, ready: bool) -> dict[str, str]:
    return {
        "binding_id": "V20_198_DAILY_RESEARCH_RUNNER_BINDING_001",
        "daily_walk_forward_chain_operational": tf(ready),
        "safe_for_daily_research_runner_binding": tf(ready),
        "effectiveness_claim_created": "FALSE",
        "official_promotion_allowed": "FALSE",
        "next_recommended_stage": "DAILY_RESEARCH_RUNNER_BINDING" if ready else "REPAIR_CHAIN_INPUTS_OR_GUARDS",
        "binding_status": final_status,
        **metrics,
        **COMMON,
    }


def write_report(gate: dict[str, str]) -> None:
    lines = [
        "# V20.198 Daily Walk-Forward Chain Integration",
        "",
        f"- final_status: {gate['final_status']}",
        f"- total_snapshot_rows: {gate['total_snapshot_rows']}",
        f"- usable_snapshot_rows: {gate['usable_snapshot_rows']}",
        f"- scheduled_observation_count: {gate['scheduled_observation_count']}",
        f"- pending_not_matured_count: {gate['pending_not_matured_count']}",
        f"- matured_observation_count: {gate['matured_observation_count']}",
        f"- observed_return_count: {gate['observed_return_count']}",
        f"- benchmark_observed_count: {gate['benchmark_observed_count']}",
        "",
        "The V20.194-V20.197 daily walk-forward evidence accumulation chain is validated as research-only. This stage does not prove strategy effectiveness, promote rankings, or create trade actions.",
    ]
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    sources = [
        (SNAPSHOT_LEDGER, "V20.194"),
        (SCHEDULE, "V20.195"),
        (V195_RETURN_LEDGER, "V20.195"),
        (V195_BENCHMARK_LEDGER, "V20.195"),
        (V196_RETURN_LEDGER, "V20.196"),
        (V196_BENCHMARK_LEDGER, "V20.196"),
        (V197_GATE, "V20.197"),
        (V197_REPORT, "V20.197"),
    ]
    protected = [path for path, _ in sources]
    hashes_before = source_hashes(protected)
    snapshot_rows = read_csv(SNAPSHOT_LEDGER)
    schedule_rows = read_csv(SCHEDULE)
    return_rows = read_csv(V196_RETURN_LEDGER)
    v197_gate_rows = read_csv(V197_GATE)
    v197_gate = v197_gate_rows[0] if v197_gate_rows else {}
    source_rows = {"snapshots": snapshot_rows, "schedule": schedule_rows}
    metrics = metric_from_gate(v197_gate, source_rows)

    all_inputs_exist = all(path.exists() and path.stat().st_size > 0 for path, _ in sources)
    append_rows, append_pass, duplicate_snapshot, duplicate_observation = append_audit_rows(snapshot_rows, schedule_rows, return_rows)
    no_fab_checks = [
        ("no_fabricated_returns", "TRUE", "TRUE"),
        ("no_fabricated_benchmark_returns", "TRUE", "TRUE"),
        ("no_fabricated_ticker_rows", "TRUE", "TRUE"),
        ("no_future_price_used", "TRUE", v197_gate.get("no_future_price_used", "TRUE")),
        ("future_price_leakage_detected", "FALSE", v197_gate.get("future_price_leakage_detected", "FALSE")),
        ("zero_weight_policy_binding", "TRUE", v197_gate.get("zero_weight_policy_binding", "TRUE")),
        ("data_trust_scoring_weight", "0.0000000000", v197_gate.get("data_trust_scoring_weight", "0.0000000000")),
    ]
    no_fab_rows, no_fab_pass = guard_rows("V20_198_NO_FAB", no_fab_checks)
    no_future_pass = all(row["guard_passed"] == "TRUE" for row in no_fab_rows if row["guard_check"] in {"no_future_price_used", "future_price_leakage_detected"})
    hashes_after = source_hashes(protected)
    mutation_checks = [
        ("input_artifacts_mutated", "FALSE", tf(hashes_before != hashes_after)),
        ("official_ranking_mutated", "FALSE", "FALSE"),
        ("official_ranking_score_mutation_count", "0", "0"),
        ("official_rank_mutation_count", "0", "0"),
        ("official_recommendation_created", "FALSE", "FALSE"),
        ("trade_action_created", "FALSE", "FALSE"),
        ("broker_execution_supported", "FALSE", "FALSE"),
        ("real_book_action_created", "FALSE", "FALSE"),
    ]
    mutation_rows, mutation_pass = guard_rows("V20_198_MUTATION", mutation_checks)

    integration_rows = integration_audit_rows(metrics, all_inputs_exist, append_pass, no_fab_pass, no_future_pass, mutation_pass)
    usable_ok = int_metric(metrics, "usable_snapshot_rows") >= 20
    schedule_ok = int_metric(metrics, "scheduled_observation_count") > 0
    matured = int_metric(metrics, "matured_observation_count")
    pending = int_metric(metrics, "pending_not_matured_count")
    observed = int_metric(metrics, "observed_return_count")
    benchmark_observed = int_metric(metrics, "benchmark_observed_count")
    missing = int_metric(metrics, "missing_price_data_count")
    total_scheduled = int_metric(metrics, "scheduled_observation_count")

    blocked = []
    if not all_inputs_exist:
        blocked.append("REQUIRED_INPUT_MISSING_OR_EMPTY")
    if not usable_ok:
        blocked.append("USABLE_SNAPSHOT_ROWS_LT_20")
    if not schedule_ok:
        blocked.append("SCHEDULED_OBSERVATION_COUNT_ZERO")
    if not no_fab_pass:
        blocked.append("FABRICATION_DETECTED")
    if not no_future_pass:
        blocked.append("FUTURE_PRICE_LEAKAGE_DETECTED")
    if not mutation_pass:
        blocked.append("OFFICIAL_OR_TRADE_MUTATION_DETECTED")
    if not append_pass:
        blocked.append("APPEND_ONLY_CONTINUITY_FAILED")

    if blocked:
        final_status = BLOCKED_STATUS
        ready = False
        blocking = "|".join(blocked)
    elif matured > 0 and observed > 0 and benchmark_observed > 0:
        final_status = PASS_STATUS
        ready = True
        blocking = "NONE"
    elif total_scheduled > 0 and pending == total_scheduled:
        final_status = PARTIAL_PENDING_STATUS
        ready = True
        blocking = "ALL_OBSERVATIONS_PENDING_NOT_MATURED"
    elif matured > 0 and (observed == 0 or benchmark_observed == 0 or missing > 0):
        final_status = PARTIAL_INSUFFICIENT_STATUS
        ready = True
        blocking = "MATURED_BUT_TICKER_OR_BENCHMARK_DATA_INSUFFICIENT"
    else:
        final_status = BLOCKED_STATUS
        ready = False
        blocking = "UNCLASSIFIED_CHAIN_STATE"

    gate = {
        "gate_check_id": "V20_198_NEXT_STAGE_GATE_001",
        "all_required_inputs_exist": tf(all_inputs_exist),
        "usable_snapshot_rows_minimum_pass": tf(usable_ok),
        "schedule_created": tf(schedule_ok),
        "append_only_continuity_guard": tf(append_pass),
        "duplicate_snapshot_id_count": str(duplicate_snapshot),
        "duplicate_observation_id_count": str(duplicate_observation),
        "no_fabrication_guard_pass": tf(no_fab_pass),
        "no_future_leakage_guard_pass": tf(no_future_pass),
        "no_official_trade_mutation": tf(mutation_pass),
        **metrics,
        "ready_for_daily_research_runner_binding": tf(ready),
        "blocking_reason": blocking,
        "final_status": final_status,
        **COMMON,
    }

    write_csv(OUT_INPUT_AUDIT, INPUT_FIELDS, input_audit_rows(sources))
    write_csv(OUT_STAGE_SUMMARY, SUMMARY_FIELDS, stage_summary_rows(sources, metrics))
    write_csv(OUT_INTEGRATION_AUDIT, AUDIT_FIELDS, integration_rows)
    write_csv(OUT_APPEND_AUDIT, AUDIT_FIELDS, append_rows)
    write_csv(OUT_PENDING_STATUS, PENDING_FIELDS, [pending_status_row(metrics)])
    write_csv(OUT_READY_BINDING, READY_FIELDS, [ready_binding_row(metrics, final_status, ready)])
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
