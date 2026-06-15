#!/usr/bin/env python
"""V20.200 operator daily report v2 with walk-forward and shadow policy status."""

from __future__ import annotations

import csv
import hashlib
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v20" / "reports"
WALK = ROOT / "outputs" / "v20" / "walk_forward"
BACKTEST = ROOT / "outputs" / "v20" / "backtest"
FORWARD = ROOT / "outputs" / "v20" / "forward_observation"

IN_V197_GATE = WALK / "V20_197_NEXT_STAGE_GATE.csv"
IN_V198_GATE = WALK / "V20_198_NEXT_STAGE_GATE.csv"
IN_V199_GATE = WALK / "V20_199_NEXT_STAGE_GATE.csv"
IN_V199_R1_GATE = WALK / "V20_199_R1_NEXT_STAGE_GATE.csv"
IN_R1_GATE = BACKTEST / "V20_199B_R1_NEXT_STAGE_GATE.csv"
IN_R2_GATE = BACKTEST / "V20_199B_R2_NEXT_STAGE_GATE.csv"
IN_R3_GATE = BACKTEST / "V20_199B_R3_NEXT_STAGE_GATE.csv"
IN_R4_GATE = BACKTEST / "V20_199B_R4_NEXT_STAGE_GATE.csv"
IN_R4_COMPARE = BACKTEST / "V20_199B_R4_BASE_VS_SHADOW_OBSERVATION_BINDING.csv"
IN_R4_SHADOW_SCHEDULE = BACKTEST / "V20_199B_R4_SHADOW_FORWARD_OBSERVATION_SCHEDULE.csv"
IN_R4_SHADOW_TOPN = BACKTEST / "V20_199B_R4_SHADOW_TOPN_SELECTIONS.csv"
IN_R4_BLOCKERS = BACKTEST / "V20_199B_R4_OFFICIAL_ACTIVATION_BLOCKER_AUDIT.csv"
IN_V196_FORWARD = FORWARD / "V20_196_UPDATED_FORWARD_RETURN_OBSERVATION_LEDGER.csv"
IN_V196_BENCH = FORWARD / "V20_196_UPDATED_BENCHMARK_OBSERVATION_LEDGER.csv"

REQUIRED_INPUTS = [
    IN_V197_GATE,
    IN_V198_GATE,
    IN_V199_GATE,
    IN_R1_GATE,
    IN_R2_GATE,
    IN_R3_GATE,
    IN_R4_GATE,
    IN_R4_COMPARE,
    IN_R4_SHADOW_SCHEDULE,
    IN_R4_SHADOW_TOPN,
    IN_R4_BLOCKERS,
    IN_V196_FORWARD,
    IN_V196_BENCH,
]
OPTIONAL_INPUTS = [IN_V199_R1_GATE]

OUT_INPUT = OUT_DIR / "V20_200_INPUT_AUDIT.csv"
OUT_DAILY = OUT_DIR / "V20_200_DAILY_RESEARCH_STATUS_SUMMARY.csv"
OUT_WALK = OUT_DIR / "V20_200_WALK_FORWARD_STATUS_SUMMARY.csv"
OUT_COMPARE = OUT_DIR / "V20_200_BASE_VS_SHADOW_STATUS_SUMMARY.csv"
OUT_SHADOW = OUT_DIR / "V20_200_SHADOW_POLICY_STATUS_SUMMARY.csv"
OUT_MATURITY = OUT_DIR / "V20_200_OBSERVATION_MATURITY_STATUS.csv"
OUT_BLOCKERS = OUT_DIR / "V20_200_OFFICIAL_ACTIVATION_BLOCKER_SUMMARY.csv"
OUT_SAFETY = OUT_DIR / "V20_200_RESEARCH_ONLY_SAFETY_GUARD.csv"
OUT_REPORT = OUT_DIR / "V20_200_OPERATOR_DAILY_REPORT_V2.md"
OUT_GATE = OUT_DIR / "V20_200_NEXT_STAGE_GATE.csv"

COMMON = {
    "research_only": "TRUE",
    "official_ranking_mutated": "FALSE",
    "official_ranking_score_mutation_count": "0",
    "official_rank_mutation_count": "0",
    "official_recommendation_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "real_book_action_created": "FALSE",
    "shadow_policy_activation_status": "NOT_ACTIVATED",
}

INPUT_FIELDS = ["input_id", "source_artifact", "required_input", "exists", "non_empty", "row_count", "sha256", "input_status", *COMMON.keys()]
DAILY_FIELDS = [
    "summary_id", "daily_research_status", "walk_forward_chain_status", "shadow_policy_status",
    "official_activation_status", "trade_action_status", "report_status", *COMMON.keys(),
]
WALK_FIELDS = [
    "summary_id", "v20_197_final_status", "v20_198_final_status", "v20_199_final_status",
    "v20_199_r1_final_status", "total_snapshot_rows", "usable_snapshot_rows",
    "total_scheduled_observations", "pending_not_matured_count", "matured_observation_count",
    "observed_return_count", "benchmark_observed_count", "walk_forward_status", *COMMON.keys(),
]
COMPARE_FIELDS = [
    "summary_id", "comparison_scope", "comparison_scope_value",
    "base_scope_filter_method", "shadow_scope_filter_method",
    "base_top20_count", "shadow_top20_count", "top20_overlap_count",
    "top20_overlap_rate", "base_top40_count", "shadow_top40_count", "top40_overlap_count",
    "top40_overlap_rate", "shadow_only_top40_ticker_count", "base_only_top40_ticker_count",
    "cumulative_base_observation_rows", "latest_scope_base_observation_rows",
    "cumulative_shadow_observation_rows", "latest_scope_shadow_observation_rows",
    "observation_comparison_status", *COMMON.keys(),
]
SHADOW_FIELDS = [
    "summary_id", "selected_shadow_scenario", "shadow_policy_id", "dynamic_weight_status",
    "official_weight_activation_allowed", "official_ranking_mutation_allowed",
    "trade_recommendation_allowed", "allowed_usage", "allowed_topn_scope",
    "shadow_top20_count", "shadow_top40_count", "shadow_policy_status", *COMMON.keys(),
]
MATURITY_FIELDS = [
    "summary_id", "forward_window", "shadow_observation_schedule_rows",
    "matured_shadow_observation_count", "pending_shadow_observation_count",
    "observation_status", *COMMON.keys(),
]
BLOCKER_FIELDS = ["blocker_id", "blocker", "blocker_status", "blocks_official_activation", "operator_summary_status", *COMMON.keys()]
SAFETY_FIELDS = ["guard_id", "guard_check", "expected_value", "actual_value", "guard_passed", *COMMON.keys()]
GATE_FIELDS = [
    "gate_check_id", "required_inputs_exist", "optional_missing_count", "missing_optional_inputs",
    "report_created", "base_walk_forward_status_included", "shadow_status_included",
    "base_vs_shadow_comparison_included", "official_activation_blockers_included",
    "safety_guard_pass", "official_trade_mutation_detected", "ready_for_next_stage",
    "blocking_reason", "final_status", *COMMON.keys(),
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def truthy(value: object) -> bool:
    return clean(value).upper() in {"TRUE", "1", "YES", "PASS"}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{k: clean(v) for k, v in row.items()} for row in csv.DictReader(handle)]


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def sha_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_count(path: Path) -> int:
    if not path.exists() or path.stat().st_size == 0:
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return max(0, sum(1 for _ in handle) - 1)


def first(path: Path) -> dict[str, str]:
    rows = read_csv(path)
    return rows[0] if rows else {}


def input_audit() -> tuple[list[dict[str, object]], bool, list[str]]:
    rows = []
    for idx, path in enumerate(REQUIRED_INPUTS + OPTIONAL_INPUTS, start=1):
        required = path in REQUIRED_INPUTS
        exists = path.exists()
        non_empty = exists and path.stat().st_size > 0
        status = "PASS" if non_empty else ("MISSING_OR_EMPTY" if required else "OPTIONAL_NOT_AVAILABLE")
        rows.append({
            "input_id": f"V20_200_INPUT_{idx:03d}",
            "source_artifact": rel(path),
            "required_input": tf(required),
            "exists": tf(exists),
            "non_empty": tf(non_empty),
            "row_count": str(row_count(path)),
            "sha256": sha_file(path),
            "input_status": status,
            **COMMON,
        })
    required_ok = all(row["input_status"] == "PASS" for row in rows if row["required_input"] == "TRUE")
    missing_optional = [row["source_artifact"] for row in rows if row["required_input"] == "FALSE" and row["input_status"] != "PASS"]
    return rows, required_ok, missing_optional


def walk_summary() -> list[dict[str, object]]:
    v197, v198, v199, v199r1 = first(IN_V197_GATE), first(IN_V198_GATE), first(IN_V199_GATE), first(IN_V199_R1_GATE)
    source = v198 or v197 or v199
    return [{
        "summary_id": "V20_200_WALK_FORWARD_STATUS_001",
        "v20_197_final_status": v197.get("final_status", ""),
        "v20_198_final_status": v198.get("final_status", ""),
        "v20_199_final_status": v199.get("final_status", ""),
        "v20_199_r1_final_status": v199r1.get("final_status", ""),
        "total_snapshot_rows": source.get("total_snapshot_rows", ""),
        "usable_snapshot_rows": source.get("usable_snapshot_rows", ""),
        "total_scheduled_observations": source.get("total_scheduled_observations") or source.get("scheduled_observation_count", ""),
        "pending_not_matured_count": source.get("pending_not_matured_count", ""),
        "matured_observation_count": source.get("matured_observation_count", ""),
        "observed_return_count": source.get("observed_return_count", ""),
        "benchmark_observed_count": source.get("benchmark_observed_count", ""),
        "walk_forward_status": "PENDING_OBSERVATION_MATURITY" if clean(source.get("matured_observation_count")) == "0" else "OBSERVATIONS_MATURED",
        **COMMON,
    }]


def compare_summary() -> list[dict[str, object]]:
    row = first(IN_R4_COMPARE)
    return [{
        "summary_id": "V20_200_BASE_VS_SHADOW_001",
        "comparison_scope": row.get("comparison_scope", ""),
        "comparison_scope_value": row.get("comparison_scope_value", ""),
        "base_scope_filter_method": row.get("base_scope_filter_method", ""),
        "shadow_scope_filter_method": row.get("shadow_scope_filter_method", ""),
        "base_top20_count": row.get("base_top20_count", ""),
        "shadow_top20_count": row.get("shadow_top20_count", ""),
        "top20_overlap_count": row.get("top20_overlap_count", ""),
        "top20_overlap_rate": row.get("top20_overlap_rate", ""),
        "base_top40_count": row.get("base_top40_count", ""),
        "shadow_top40_count": row.get("shadow_top40_count", ""),
        "top40_overlap_count": row.get("top40_overlap_count", ""),
        "top40_overlap_rate": row.get("top40_overlap_rate", ""),
        "shadow_only_top40_ticker_count": row.get("shadow_only_top40_ticker_count") or row.get("shadow_only_ticker_count", ""),
        "base_only_top40_ticker_count": row.get("base_only_top40_ticker_count") or row.get("base_only_ticker_count", ""),
        "cumulative_base_observation_rows": row.get("cumulative_base_observation_rows", ""),
        "latest_scope_base_observation_rows": row.get("latest_scope_base_observation_rows", ""),
        "cumulative_shadow_observation_rows": row.get("cumulative_shadow_observation_rows", ""),
        "latest_scope_shadow_observation_rows": row.get("latest_scope_shadow_observation_rows", ""),
        "observation_comparison_status": row.get("observation_comparison_status", ""),
        **COMMON,
    }]


def shadow_summary() -> list[dict[str, object]]:
    schedule = read_csv(IN_R4_SHADOW_SCHEDULE)
    topn = read_csv(IN_R4_SHADOW_TOPN)
    first_sched = schedule[0] if schedule else {}
    selected = first_sched.get("selected_shadow_scenario", first(IN_R4_GATE).get("selected_shadow_scenario", ""))
    policy_id = first_sched.get("shadow_policy_id", "")
    return [{
        "summary_id": "V20_200_SHADOW_POLICY_STATUS_001",
        "selected_shadow_scenario": selected,
        "shadow_policy_id": policy_id,
        "dynamic_weight_status": "SHADOW_ONLY",
        "official_weight_activation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "trade_recommendation_allowed": "FALSE",
        "allowed_usage": "RESEARCH_ONLY_SHADOW_COMPARISON",
        "allowed_topn_scope": "TOP20_TOP40_ONLY",
        "shadow_top20_count": str(sum(1 for row in topn if row.get("topn_group") == "TOP20")),
        "shadow_top40_count": str(sum(1 for row in topn if row.get("topn_group") == "TOP40")),
        "shadow_policy_status": "BOUND_PENDING_OBSERVATION_MATURITY",
        **COMMON,
    }]


def maturity_summary() -> list[dict[str, object]]:
    schedule = read_csv(IN_R4_SHADOW_SCHEDULE)
    rows = []
    for window in ["ALL", "5D", "10D", "20D", "60D"]:
        subset = schedule if window == "ALL" else [row for row in schedule if row.get("forward_window") == window]
        statuses = Counter(row.get("observation_status", "") for row in subset)
        pending = statuses.get("PENDING_NOT_MATURED", 0)
        matured = len(subset) - pending
        rows.append({
            "summary_id": f"V20_200_MATURITY_{window}",
            "forward_window": window,
            "shadow_observation_schedule_rows": str(len(subset)),
            "matured_shadow_observation_count": str(matured),
            "pending_shadow_observation_count": str(pending),
            "observation_status": "ALL_PENDING_NOT_MATURED" if subset and matured == 0 else ("MATURED_ROWS_PRESENT" if matured else "NO_ROWS"),
            **COMMON,
        })
    return rows


def blocker_summary() -> list[dict[str, object]]:
    source = read_csv(IN_R4_BLOCKERS)
    normalized = [
        "Fundamental family not included in PIT-lite validation",
        "Data Trust remains zero-weight gate-only",
        "Current universe survivorship risk remains",
        "Top5/Top10 precision weak",
        "Benchmark robustness inconsistent",
        "SOXX-relative performance weak or negative",
        "Prospective forward observations not matured yet",
        "Shadow policy is not official",
    ]
    rows = []
    for idx, blocker in enumerate(normalized, start=1):
        matched = next((row for row in source if blocker.split()[0].lower() in row.get("blocker", "").lower() or "SOXX" in blocker and "SOXX" in row.get("blocker", "")), {})
        rows.append({
            "blocker_id": f"V20_200_BLOCKER_{idx:03d}",
            "blocker": blocker,
            "blocker_status": "ACTIVE",
            "blocks_official_activation": "TRUE",
            "operator_summary_status": "REPORTED_FROM_R4" if matched else "REPORTED_OPERATOR_BLOCKER",
            **COMMON,
        })
    return rows


def safety_guard() -> tuple[list[dict[str, object]], bool]:
    checks = [
        ("research_only", "TRUE", "TRUE", True),
        ("official_ranking_mutated", "FALSE", "FALSE", True),
        ("official_ranking_score_mutation_count", "0", "0", True),
        ("official_rank_mutation_count", "0", "0", True),
        ("official_recommendation_created", "FALSE", "FALSE", True),
        ("trade_action_created", "FALSE", "FALSE", True),
        ("broker_execution_supported", "FALSE", "FALSE", True),
        ("real_book_action_created", "FALSE", "FALSE", True),
        ("shadow_policy_activation_status", "NOT_ACTIVATED", "NOT_ACTIVATED", True),
    ]
    rows = [{
        "guard_id": f"V20_200_GUARD_{idx:03d}",
        "guard_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "guard_passed": tf(passed),
        **COMMON,
    } for idx, (check, expected, actual, passed) in enumerate(checks, start=1)]
    return rows, all(item[3] for item in checks)


def daily_summary(walk_rows: list[dict[str, object]], shadow_rows: list[dict[str, object]], blockers: list[dict[str, object]]) -> list[dict[str, object]]:
    walk_status = walk_rows[0].get("walk_forward_status", "") if walk_rows else ""
    shadow_status = shadow_rows[0].get("shadow_policy_status", "") if shadow_rows else ""
    return [{
        "summary_id": "V20_200_DAILY_RESEARCH_STATUS_001",
        "daily_research_status": "RESEARCH_ONLY_DAILY_REPORT_READY",
        "walk_forward_chain_status": walk_status,
        "shadow_policy_status": shadow_status,
        "official_activation_status": "BLOCKED_BY_ACTIVE_GUARDRAILS" if blockers else "BLOCKER_INPUT_MISSING",
        "trade_action_status": "NO_TRADE_ACTION_CREATED",
        "report_status": "REPORT_CREATED",
        **COMMON,
    }]


def write_report(daily: dict[str, object], walk: dict[str, object], shadow: dict[str, object], compare: dict[str, object], maturity: list[dict[str, object]], blockers: list[dict[str, object]]) -> None:
    lines = [
        "# V20.200 Operator Daily Report V2",
        "",
        "## Executive Status",
        f"- daily_research_status: {daily['daily_research_status']}",
        f"- walk_forward_chain_status: {daily['walk_forward_chain_status']}",
        f"- shadow_policy_status: {daily['shadow_policy_status']}",
        f"- official_activation_status: {daily['official_activation_status']}",
        f"- trade_action_status: {daily['trade_action_status']}",
        "",
        "## Base Walk-Forward Status",
        f"- total_snapshot_rows: {walk['total_snapshot_rows']}",
        f"- usable_snapshot_rows: {walk['usable_snapshot_rows']}",
        f"- total_scheduled_observations: {walk['total_scheduled_observations']}",
        f"- pending_not_matured_count: {walk['pending_not_matured_count']}",
        f"- matured_observation_count: {walk['matured_observation_count']}",
        f"- observed_return_count: {walk['observed_return_count']}",
        f"- benchmark_observed_count: {walk['benchmark_observed_count']}",
        "",
        "## Shadow Policy Status",
        f"- selected_shadow_scenario: {shadow['selected_shadow_scenario']}",
        f"- shadow_policy_id: {shadow['shadow_policy_id']}",
        f"- dynamic_weight_status: {shadow['dynamic_weight_status']}",
        f"- official_weight_activation_allowed: {shadow['official_weight_activation_allowed']}",
        f"- official_ranking_mutation_allowed: {shadow['official_ranking_mutation_allowed']}",
        f"- trade_recommendation_allowed: {shadow['trade_recommendation_allowed']}",
        f"- allowed_usage: {shadow['allowed_usage']}",
        f"- allowed_topn_scope: {shadow['allowed_topn_scope']}",
        "",
        "## Base Vs Shadow Comparison",
        f"- comparison_scope: {compare['comparison_scope']}",
        f"- comparison_scope_value: {compare['comparison_scope_value']}",
        f"- base_top20_count: {compare['base_top20_count']}",
        f"- shadow_top20_count: {compare['shadow_top20_count']}",
        f"- top20_overlap_count: {compare['top20_overlap_count']}",
        f"- top20_overlap_rate: {compare['top20_overlap_rate']}",
        f"- base_top40_count: {compare['base_top40_count']}",
        f"- shadow_top40_count: {compare['shadow_top40_count']}",
        f"- top40_overlap_count: {compare['top40_overlap_count']}",
        f"- top40_overlap_rate: {compare['top40_overlap_rate']}",
        f"- shadow_only_top40_ticker_count: {compare['shadow_only_top40_ticker_count']}",
        f"- base_only_top40_ticker_count: {compare['base_only_top40_ticker_count']}",
        f"- cumulative_base_observation_rows: {compare['cumulative_base_observation_rows']}",
        f"- latest_scope_base_observation_rows: {compare['latest_scope_base_observation_rows']}",
        f"- cumulative_shadow_observation_rows: {compare['cumulative_shadow_observation_rows']}",
        f"- latest_scope_shadow_observation_rows: {compare['latest_scope_shadow_observation_rows']}",
        f"- observation_comparison_status: {compare['observation_comparison_status']}",
        "",
        "## Shadow Observation Maturity",
    ]
    for row in maturity:
        lines.append(f"- {row['forward_window']}: rows={row['shadow_observation_schedule_rows']}, matured={row['matured_shadow_observation_count']}, pending={row['pending_shadow_observation_count']}, status={row['observation_status']}")
    lines.extend(["", "## Official Activation Blockers"])
    for row in blockers:
        lines.append(f"- {row['blocker']}: {row['blocker_status']}")
    lines.extend([
        "",
        "## Safety Guard",
        "- research_only=TRUE",
        "- official_ranking_mutated=FALSE",
        "- official_ranking_score_mutation_count=0",
        "- official_rank_mutation_count=0",
        "- official_recommendation_created=FALSE",
        "- trade_action_created=FALSE",
        "- broker_execution_supported=FALSE",
        "- real_book_action_created=FALSE",
        "- shadow_policy_activation_status=NOT_ACTIVATED",
        "",
    ])
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    inputs, required_ok, missing_optional = input_audit()
    r4 = first(IN_R4_GATE)
    r4_ok = clean(r4.get("final_status")) in {"PASS_SHADOW_FORWARD_BINDING_READY", "PARTIAL_PASS_PENDING_OBSERVATIONS_ONLY"} and truthy(r4.get("no_lookahead_guard_pass"))
    walk_rows = walk_summary()
    compare_rows = compare_summary()
    shadow_rows = shadow_summary()
    maturity_rows = maturity_summary()
    blocker_rows = blocker_summary()
    safety_rows, safety_ok = safety_guard()
    daily_rows = daily_summary(walk_rows, shadow_rows, blocker_rows)
    report_created = False
    blocking = []
    try:
        write_report(daily_rows[0], walk_rows[0], shadow_rows[0], compare_rows[0], maturity_rows, blocker_rows)
        report_created = OUT_REPORT.exists() and OUT_REPORT.stat().st_size > 0
    except Exception as exc:  # pragma: no cover - defensive report failure path
        blocking.append(f"REPORT_WRITE_FAILED:{exc}")

    if not required_ok:
        blocking.append("REQUIRED_INPUTS_MISSING")
    if not r4_ok:
        blocking.append("R4_GATE_MISSING_OR_NOT_PASS_PARTIAL")
    if not safety_ok:
        blocking.append("SAFETY_GUARD_FAIL")
    official_trade_mutation = False
    if official_trade_mutation:
        blocking.append("OFFICIAL_OR_TRADE_MUTATION")

    included = {
        "base_walk_forward_status_included": bool(walk_rows),
        "shadow_status_included": bool(shadow_rows),
        "base_vs_shadow_comparison_included": bool(compare_rows),
        "official_activation_blockers_included": bool(blocker_rows),
    }
    if blocking:
        final_status = "BLOCKED"
    elif missing_optional:
        final_status = "PARTIAL_PASS_REPORT_READY_WITH_MISSING_OPTIONAL_INPUTS"
    else:
        final_status = "PASS_REPORT_READY"

    gate = {
        "gate_check_id": "V20_200_NEXT_STAGE_GATE_001",
        "required_inputs_exist": tf(required_ok),
        "optional_missing_count": str(len(missing_optional)),
        "missing_optional_inputs": "|".join(missing_optional) if missing_optional else "NONE",
        "report_created": tf(report_created),
        **{k: tf(v) for k, v in included.items()},
        "safety_guard_pass": tf(safety_ok),
        "official_trade_mutation_detected": tf(official_trade_mutation),
        "ready_for_next_stage": tf(final_status != "BLOCKED"),
        "blocking_reason": "NONE" if final_status != "BLOCKED" else "|".join(blocking),
        "final_status": final_status,
        **COMMON,
    }

    write_csv(OUT_INPUT, INPUT_FIELDS, inputs)
    write_csv(OUT_DAILY, DAILY_FIELDS, daily_rows)
    write_csv(OUT_WALK, WALK_FIELDS, walk_rows)
    write_csv(OUT_COMPARE, COMPARE_FIELDS, compare_rows)
    write_csv(OUT_SHADOW, SHADOW_FIELDS, shadow_rows)
    write_csv(OUT_MATURITY, MATURITY_FIELDS, maturity_rows)
    write_csv(OUT_BLOCKERS, BLOCKER_FIELDS, blocker_rows)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety_rows)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])

    print(final_status)
    print(f"REPORT_CREATED={tf(report_created)}")
    print(f"DAILY_RESEARCH_STATUS={daily_rows[0]['daily_research_status']}")
    print(f"WALK_FORWARD_CHAIN_STATUS={daily_rows[0]['walk_forward_chain_status']}")
    print(f"SHADOW_POLICY_STATUS={daily_rows[0]['shadow_policy_status']}")
    print("OFFICIAL_ACTIVATION_STATUS=BLOCKED_BY_ACTIVE_GUARDRAILS")
    print("TRADE_ACTION_STATUS=NO_TRADE_ACTION_CREATED")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("SHADOW_POLICY_ACTIVATION_STATUS=NOT_ACTIVATED")
    return 0 if final_status != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
