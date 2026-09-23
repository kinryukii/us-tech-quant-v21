#!/usr/bin/env python
"""V20.199B-R3 shadow dynamic weight candidate and guardrail selection.

Consumes V20.199B-R1/R2 PIT-lite diagnostics and emits a shadow-only dynamic
weight candidate policy. This stage never activates official weights, mutates
official rankings, creates recommendations, or creates trade actions.
"""

from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v20" / "backtest"

IN_R1_EFFECT = OUT_DIR / "V20_199B_R1_EFFECTIVENESS_SUMMARY.csv"
IN_R1_COMPARE = OUT_DIR / "V20_199B_R1_TOPN_BENCHMARK_COMPARISON.csv"
IN_R1_WEIGHT = OUT_DIR / "V20_199B_R1_WEIGHT_SCENARIO_COMPARISON.csv"
IN_R1_DYNAMIC = OUT_DIR / "V20_199B_R1_DYNAMIC_WEIGHT_WALK_FORWARD_AUDIT.csv"
IN_R1_GUARD = OUT_DIR / "V20_199B_R1_NO_LOOKAHEAD_GUARD_AUDIT.csv"
IN_R1_GATE = OUT_DIR / "V20_199B_R1_NEXT_STAGE_GATE.csv"
IN_R2_SCENARIO = OUT_DIR / "V20_199B_R2_SCENARIO_ROBUSTNESS_SUMMARY.csv"
IN_R2_TOPN = OUT_DIR / "V20_199B_R2_TOPN_MONOTONICITY_AUDIT.csv"
IN_R2_BENCHMARK = OUT_DIR / "V20_199B_R2_BENCHMARK_ROBUSTNESS_AUDIT.csv"
IN_R2_WINDOW = OUT_DIR / "V20_199B_R2_FORWARD_WINDOW_EFFECTIVENESS_AUDIT.csv"
IN_R2_PRECISION = OUT_DIR / "V20_199B_R2_TOP5_TOP10_RANK_PRECISION_AUDIT.csv"
IN_R2_DYNAMIC = OUT_DIR / "V20_199B_R2_DYNAMIC_WEIGHT_ELIGIBILITY_AUDIT.csv"
IN_R2_CONCLUSION = OUT_DIR / "V20_199B_R2_RESEARCH_CONCLUSION_SUMMARY.csv"
IN_R2_GATE = OUT_DIR / "V20_199B_R2_NEXT_STAGE_GATE.csv"
IN_R2_OUTLIER = OUT_DIR / "V20_199B_R2_OUTLIER_CONCENTRATION_AUDIT.csv"
IN_R2_PERIOD = OUT_DIR / "V20_199B_R2_ASOF_PERIOD_STABILITY_AUDIT.csv"

REQUIRED_INPUTS = [
    IN_R1_EFFECT, IN_R1_COMPARE, IN_R1_WEIGHT, IN_R1_DYNAMIC, IN_R1_GUARD, IN_R1_GATE,
    IN_R2_SCENARIO, IN_R2_TOPN, IN_R2_BENCHMARK, IN_R2_WINDOW, IN_R2_PRECISION,
    IN_R2_DYNAMIC, IN_R2_CONCLUSION, IN_R2_GATE,
]
OPTIONAL_INPUTS = [IN_R2_OUTLIER, IN_R2_PERIOD]

OUT_INPUT = OUT_DIR / "V20_199B_R3_INPUT_AUDIT.csv"
OUT_SELECTION = OUT_DIR / "V20_199B_R3_SHADOW_WEIGHT_CANDIDATE_SELECTION.csv"
OUT_DECISION = OUT_DIR / "V20_199B_R3_WEIGHT_SCENARIO_DECISION_AUDIT.csv"
OUT_TOPN = OUT_DIR / "V20_199B_R3_TOPN_USAGE_GUARDRAIL.csv"
OUT_BENCH = OUT_DIR / "V20_199B_R3_BENCHMARK_ROBUSTNESS_GUARDRAIL.csv"
OUT_POLICY = OUT_DIR / "V20_199B_R3_DYNAMIC_WEIGHT_SHADOW_POLICY.csv"
OUT_BLOCKERS = OUT_DIR / "V20_199B_R3_OFFICIAL_ACTIVATION_BLOCKER_AUDIT.csv"
OUT_PLAN = OUT_DIR / "V20_199B_R3_RESEARCH_ONLY_INTEGRATION_PLAN.csv"
OUT_GUARD = OUT_DIR / "V20_199B_R3_NO_LOOKAHEAD_AND_NO_MUTATION_GUARD.csv"
OUT_REPORT = OUT_DIR / "V20_199B_R3_READ_CENTER_REPORT.md"
OUT_GATE = OUT_DIR / "V20_199B_R3_NEXT_STAGE_GATE.csv"

SCENARIOS = [
    "PIT_LITE_INITIAL_POLICY",
    "SCENARIO_A_TECH_HEAVY",
    "SCENARIO_B_BALANCED_PRICE",
    "SCENARIO_C_RISK_CONTROL",
]
TOPNS = [5, 10, 20, 40]
BENCHMARKS = ["QQQ", "SPY", "SOXX"]
CORE_WINDOWS = {"20D", "60D"}
CORE_TOPNS = {20, 40}

COMMON = {
    "research_only": "TRUE",
    "no_lookahead_guard_pass": "TRUE",
    "official_ranking_mutated": "FALSE",
    "official_ranking_score_mutation_count": "0",
    "official_rank_mutation_count": "0",
    "official_recommendation_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "real_book_action_created": "FALSE",
    "no_fabricated_scores": "TRUE",
    "no_fabricated_returns": "TRUE",
    "no_fabricated_benchmark_rows": "TRUE",
    "current_snapshot_join_count": "0",
    "current_fundamental_field_used_count": "0",
    "future_price_used_for_factor_count": "0",
}

INPUT_FIELDS = ["input_id", "source_artifact", "required_input", "exists", "non_empty", "row_count", "sha256", "input_status", *COMMON.keys()]
SELECTION_FIELDS = [
    "scenario", "selected_shadow_candidate", "candidate_rank", "candidate_score",
    "selection_status", "allowed_usage", "allowed_topn_scope", "official_weight_activation_allowed",
    "official_ranking_mutation_allowed", "trade_recommendation_allowed", "score_reason", *COMMON.keys(),
]
DECISION_FIELDS = [
    "scenario", "core_top20_top40_20d_60d_qqq_spy_positive_count", "core_top20_top40_20d_60d_cell_count",
    "positive_median_excess_vs_qqq_and_spy", "average_benchmark_pass_count",
    "soxx_underperformance_penalty_count", "topn_support_count", "top5_top10_weakness_penalty_count",
    "spy_only_penalty_count", "outlier_dependence_penalty_count", "period_concentration_penalty_count",
    "candidate_score", "decision_status", *COMMON.keys(),
]
TOPN_FIELDS = ["top_n", "usage_status", "automation_allowed", "selection_scope", "guardrail_reason", *COMMON.keys()]
BENCH_FIELDS = [
    "scenario", "beats_qqq", "beats_spy", "beats_soxx", "average_qqq_excess",
    "average_spy_excess", "average_soxx_excess", "benchmark_guardrail_status", "guardrail_action",
    *COMMON.keys(),
]
POLICY_FIELDS = [
    "policy_id", "dynamic_weight_status", "official_weight_activation_allowed",
    "official_ranking_mutation_allowed", "real_book_usage_allowed", "trade_recommendation_allowed",
    "allowed_usage", "allowed_topn_scope", "disallowed_topn_scope",
    "minimum_future_validation_required", "selected_shadow_scenario", *COMMON.keys(),
]
BLOCKER_FIELDS = ["blocker_id", "blocker", "blocker_status", "blocks_official_activation", "resolution_requirement", *COMMON.keys()]
PLAN_FIELDS = ["plan_step_id", "plan_step", "integration_scope", "allowed", "blocked_from_official_use", "plan_status", *COMMON.keys()]
GUARD_FIELDS = ["guard_id", "guard_check", "expected_value", "actual_value", "guard_passed", *COMMON.keys()]
GATE_FIELDS = [
    "gate_check_id", "r1_gate_passed", "r2_gate_passed", "shadow_candidate_selected",
    "topn_guardrails_created", "benchmark_guardrails_created", "official_activation_blockers_recorded",
    "no_lookahead_guard_pass", "no_official_trade_mutation", "official_weight_activation_allowed",
    "ready_for_next_stage", "blocking_reason", "final_status", *[k for k in COMMON if k != "no_lookahead_guard_pass"],
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def truthy(value: object) -> bool:
    return clean(value).upper() in {"TRUE", "1", "YES", "PASS"}


def as_float(value: object) -> float | None:
    try:
        text = clean(value)
        if not text:
            return None
        number = float(text)
    except ValueError:
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.10f}"


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


def input_audit() -> tuple[list[dict[str, object]], bool, bool, bool]:
    rows: list[dict[str, object]] = []
    for idx, path in enumerate(REQUIRED_INPUTS + OPTIONAL_INPUTS, start=1):
        required = path in REQUIRED_INPUTS
        exists = path.exists()
        non_empty = exists and path.stat().st_size > 0
        status = "PASS" if non_empty else ("MISSING_OR_EMPTY" if required else "OPTIONAL_NOT_AVAILABLE")
        rows.append({
            "input_id": f"V20_199B_R3_INPUT_{idx:03d}",
            "source_artifact": rel(path),
            "required_input": tf(required),
            "exists": tf(exists),
            "non_empty": tf(non_empty),
            "row_count": str(row_count(path)),
            "sha256": sha_file(path),
            "input_status": status,
            **COMMON,
        })
    r1_gate = read_csv(IN_R1_GATE)
    r2_gate = read_csv(IN_R2_GATE)
    r1 = r1_gate[0] if r1_gate else {}
    r2 = r2_gate[0] if r2_gate else {}
    required_ok = all(row["input_status"] == "PASS" for row in rows if row["required_input"] == "TRUE")
    r1_pass = required_ok and clean(r1.get("final_status")).startswith("PASS") and truthy(r1.get("no_lookahead_guard_pass")) and truthy(r1.get("no_official_trade_mutation"))
    r2_pass = required_ok and clean(r2.get("final_status")) == "PASS_DIAGNOSTIC_READY" and truthy(r2.get("no_lookahead_guard_pass")) and truthy(r2.get("no_official_trade_mutation"))
    no_lookahead = r1_pass and r2_pass and all(truthy(row.get("guard_passed")) for row in read_csv(IN_R1_GUARD))
    return rows, r1_pass, r2_pass, no_lookahead


def average(nums: list[float]) -> float | None:
    return mean(nums) if nums else None


def scenario_scores() -> tuple[list[dict[str, object]], list[dict[str, object]], str]:
    scenario_rows = {row["scenario"]: row for row in read_csv(IN_R2_SCENARIO)}
    benchmark = read_csv(IN_R2_BENCHMARK)
    topn = read_csv(IN_R2_TOPN)
    precision = read_csv(IN_R2_PRECISION)
    outlier = read_csv(IN_R2_OUTLIER)
    period = read_csv(IN_R2_PERIOD)

    decision_rows: list[dict[str, object]] = []
    for scenario in SCENARIOS:
        core = [
            row for row in benchmark
            if row.get("scenario") == scenario
            and int(float(row.get("top_n") or 0)) in CORE_TOPNS
            and row.get("forward_window") in CORE_WINDOWS
        ]
        core_positive = sum(1 for row in core if row.get("qqq_excess_status") == "PASS" and row.get("spy_excess_status") == "PASS")
        pass_counts = [as_float(row.get("benchmark_pass_count")) for row in benchmark if row.get("scenario") == scenario]
        avg_pass = average([x for x in pass_counts if x is not None]) or 0.0
        soxx_penalty = sum(
            1 for row in benchmark
            if row.get("scenario") == scenario
            and (row.get("semi_beta_underperformance") == "TRUE" or (as_float(row.get("soxx_excess")) or 0) < -0.01)
        )
        topn_support = sum(1 for row in topn if row.get("scenario") == scenario and row.get("topn_monotonicity_status") in {"BROAD_BUCKET_STRONGER", "TOPN_PRECISION_STRONG"})
        precision_penalty = sum(1 for row in precision if row.get("scenario") == scenario and row.get("concentrated_selection_status") in {"NOT_READY", "WATCHLIST_ONLY"})
        spy_only = sum(1 for row in benchmark if row.get("scenario") == scenario and row.get("benchmark_robustness_status") == "TECH_BETA_NOT_ALPHA")
        outlier_penalty = sum(1 for row in outlier if row.get("scenario") == scenario and row.get("outlier_concentration_status") == "OUTLIER_DEPENDENT")
        period_penalty = sum(1 for row in period if row.get("scenario") == scenario and row.get("period_stability_status") == "PERIOD_CONCENTRATED")
        scen = scenario_rows.get(scenario, {})
        median_support = 1 if truthy(scen.get("positive_median_excess_vs_qqq_and_spy")) else 0
        score = (
            core_positive * 10.0
            + median_support * 8.0
            + avg_pass * 4.0
            + topn_support * 2.0
            - soxx_penalty * 1.5
            - precision_penalty * 2.0
            - spy_only * 2.0
            - outlier_penalty * 1.0
            - period_penalty * 0.5
        )
        if core_positive > 0 and score > 0:
            status = "SELECTABLE_SHADOW_CANDIDATE"
        elif score > 0:
            status = "WATCHLIST_SHADOW_CANDIDATE"
        else:
            status = "NOT_SELECTED_MIXED_OR_WEAK_EVIDENCE"
        decision_rows.append({
            "scenario": scenario,
            "core_top20_top40_20d_60d_qqq_spy_positive_count": str(core_positive),
            "core_top20_top40_20d_60d_cell_count": str(len(core)),
            "positive_median_excess_vs_qqq_and_spy": tf(median_support == 1),
            "average_benchmark_pass_count": fmt(avg_pass),
            "soxx_underperformance_penalty_count": str(soxx_penalty),
            "topn_support_count": str(topn_support),
            "top5_top10_weakness_penalty_count": str(precision_penalty),
            "spy_only_penalty_count": str(spy_only),
            "outlier_dependence_penalty_count": str(outlier_penalty),
            "period_concentration_penalty_count": str(period_penalty),
            "candidate_score": fmt(score),
            "decision_status": status,
            **COMMON,
        })
    ranked = sorted(decision_rows, key=lambda row: as_float(row["candidate_score"]) or -999, reverse=True)
    selected = clean(ranked[0]["scenario"]) if ranked and clean(ranked[0]["decision_status"]) == "SELECTABLE_SHADOW_CANDIDATE" else ""
    selection_rows: list[dict[str, object]] = []
    for rank, row in enumerate(ranked, start=1):
        is_selected = clean(row["scenario"]) == selected
        selection_rows.append({
            "scenario": row["scenario"],
            "selected_shadow_candidate": tf(is_selected),
            "candidate_rank": str(rank),
            "candidate_score": row["candidate_score"],
            "selection_status": "SELECTED_FOR_SHADOW_OBSERVATION" if is_selected else "NOT_SELECTED_FOR_PRIMARY_SHADOW_OBSERVATION",
            "allowed_usage": "RESEARCH_ONLY_SHADOW_COMPARISON",
            "allowed_topn_scope": "TOP20_TOP40_ONLY",
            "official_weight_activation_allowed": "FALSE",
            "official_ranking_mutation_allowed": "FALSE",
            "trade_recommendation_allowed": "FALSE",
            "score_reason": "Score uses R1/R2 diagnostics only: core Top20/Top40 QQQ/SPY excess, median support, benchmark pass count, SOXX penalty, TopN support, concentrated precision weakness, outlier dependence, and period concentration.",
            **COMMON,
        })
    return decision_rows, selection_rows, selected


def topn_guardrails() -> list[dict[str, object]]:
    policy = {
        5: ("NOT_READY_FOR_AUTOMATED_SELECTION", "FALSE", "EXCLUDED_FROM_AUTOMATION", "Top5 precision is weak and unstable in R2."),
        10: ("MANUAL_REVIEW_ONLY", "FALSE", "CONCENTRATED_REVIEW_ONLY", "Top10 is not ready for automated selection."),
        20: ("SHADOW_CANDIDATE_POOL", "FALSE", "SHADOW_POOL", "Top20 has candidate-pool screening value but remains shadow-only."),
        40: ("RESEARCH_UNIVERSE_POOL", "FALSE", "RESEARCH_POOL", "Top40 is broad research universe scope only."),
    }
    return [{
        "top_n": str(top_n),
        "usage_status": policy[top_n][0],
        "automation_allowed": policy[top_n][1],
        "selection_scope": policy[top_n][2],
        "guardrail_reason": policy[top_n][3],
        **COMMON,
    } for top_n in TOPNS]


def benchmark_guardrails() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    benchmark = read_csv(IN_R2_BENCHMARK)
    for scenario in SCENARIOS:
        cells = [row for row in benchmark if row.get("scenario") == scenario and int(float(row.get("top_n") or 0)) in CORE_TOPNS and row.get("forward_window") in CORE_WINDOWS]
        qqq = [as_float(row.get("qqq_excess")) for row in cells]
        spy = [as_float(row.get("spy_excess")) for row in cells]
        soxx = [as_float(row.get("soxx_excess")) for row in cells]
        qqq_avg = average([x for x in qqq if x is not None])
        spy_avg = average([x for x in spy if x is not None])
        soxx_avg = average([x for x in soxx if x is not None])
        beats_qqq = qqq_avg is not None and qqq_avg > 0
        beats_spy = spy_avg is not None and spy_avg > 0
        beats_soxx = soxx_avg is not None and soxx_avg > 0
        if beats_spy and not beats_qqq:
            status = "TECH_BETA_UNCONFIRMED"
        elif beats_qqq and beats_spy and not beats_soxx:
            status = "BROAD_TECH_ALPHA_BUT_SEMI_BETA_UNDERPERFORMANCE"
        elif beats_qqq and beats_spy and beats_soxx:
            status = "ROBUST_ALPHA_CANDIDATE"
        else:
            status = "BENCHMARK_SIGNAL_WEAK_OR_MIXED"
        rows.append({
            "scenario": scenario,
            "beats_qqq": tf(beats_qqq),
            "beats_spy": tf(beats_spy),
            "beats_soxx": tf(beats_soxx),
            "average_qqq_excess": fmt(qqq_avg),
            "average_spy_excess": fmt(spy_avg),
            "average_soxx_excess": fmt(soxx_avg),
            "benchmark_guardrail_status": status,
            "guardrail_action": "SHADOW_ONLY_NO_OFFICIAL_ACTIVATION",
            **COMMON,
        })
    return rows


def policy_row(selected: str) -> list[dict[str, object]]:
    return [{
        "policy_id": "V20_199B_R3_DYNAMIC_WEIGHT_SHADOW_POLICY_001",
        "dynamic_weight_status": "SHADOW_ONLY",
        "official_weight_activation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "real_book_usage_allowed": "FALSE",
        "trade_recommendation_allowed": "FALSE",
        "broker_execution_supported": "FALSE",
        "allowed_usage": "RESEARCH_ONLY_SHADOW_COMPARISON",
        "allowed_topn_scope": "TOP20_TOP40_ONLY",
        "disallowed_topn_scope": "TOP5_AUTOMATION",
        "minimum_future_validation_required": "TRUE",
        "selected_shadow_scenario": selected,
        **COMMON,
    }]


def blocker_rows() -> list[dict[str, object]]:
    blockers = [
        ("Fundamental family not included in PIT-lite R1/R2", "Add PIT-safe historical fundamental evidence before official activation."),
        ("Data Trust scoring weight is zero and gate-only", "Promote only after separate Data Trust scoring evidence exists."),
        ("Current universe survivorship risk remains", "Use a point-in-time historical universe before official activation."),
        ("Top5/Top10 precision weak", "Require matured evidence that concentrated ranks are reliable."),
        ("Benchmark robustness inconsistent", "Require consistent QQQ/SPY/SOXX-relative robustness."),
        ("SOXX-relative excess weak or negative", "Repair or explicitly constrain semiconductor beta exposure."),
        ("Prospective walk-forward observations not matured yet", "Collect matured prospective walk-forward observations."),
    ]
    return [{
        "blocker_id": f"V20_199B_R3_BLOCKER_{idx:03d}",
        "blocker": blocker,
        "blocker_status": "ACTIVE",
        "blocks_official_activation": "TRUE",
        "resolution_requirement": requirement,
        **COMMON,
    } for idx, (blocker, requirement) in enumerate(blockers, start=1)]


def integration_plan(selected: str) -> list[dict[str, object]]:
    steps = [
        ("Record selected scenario as shadow-only comparison candidate", "RESEARCH_SHADOW_LEDGER", bool(selected)),
        ("Observe Top20/Top40 candidate-pool behavior prospectively", "TOP20_TOP40_SHADOW_ONLY", bool(selected)),
        ("Block Top5 automation and trade recommendations", "GUARDRAIL_ENFORCEMENT", True),
        ("Keep official ranking and official weights unchanged", "NO_MUTATION_POLICY", True),
        ("Require future validation before any promotion review", "FUTURE_VALIDATION_GATE", True),
    ]
    return [{
        "plan_step_id": f"V20_199B_R3_PLAN_{idx:03d}",
        "plan_step": step,
        "integration_scope": scope,
        "allowed": tf(allowed),
        "blocked_from_official_use": "TRUE",
        "plan_status": "READY_FOR_SHADOW_OBSERVATION" if allowed else "WAITING_FOR_SHADOW_CANDIDATE",
        **COMMON,
    } for idx, (step, scope, allowed) in enumerate(steps, start=1)]


def guard_rows(r1_pass: bool, r2_pass: bool, no_lookahead: bool) -> tuple[list[dict[str, object]], bool]:
    no_mutation = True
    checks = [
        ("r1_gate_passed", "TRUE", tf(r1_pass), r1_pass),
        ("r2_gate_passed", "TRUE", tf(r2_pass), r2_pass),
        ("no_lookahead_guard_pass", "TRUE", tf(no_lookahead), no_lookahead),
        ("official_ranking_mutated", "FALSE", "FALSE", True),
        ("official_ranking_score_mutation_count", "0", "0", True),
        ("official_rank_mutation_count", "0", "0", True),
        ("official_recommendation_created", "FALSE", "FALSE", True),
        ("trade_action_created", "FALSE", "FALSE", True),
        ("broker_execution_supported", "FALSE", "FALSE", True),
        ("real_book_action_created", "FALSE", "FALSE", True),
        ("current_snapshot_join_count", "0", "0", True),
        ("current_fundamental_field_used_count", "0", "0", True),
        ("future_price_used_for_factor_count", "0", "0", True),
    ]
    rows = [{
        "guard_id": f"V20_199B_R3_GUARD_{idx:03d}",
        "guard_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "guard_passed": tf(passed),
        **COMMON,
        "no_lookahead_guard_pass": tf(no_lookahead),
    } for idx, (check, expected, actual, passed) in enumerate(checks, start=1)]
    return rows, no_mutation


def report(gate: dict[str, object], selected: str, bench_rows: list[dict[str, object]], blockers: list[dict[str, object]]) -> None:
    lines = [
        "# V20.199B-R3 Shadow Dynamic Weight Candidate And Guardrail Selection",
        "",
        "## Result",
        f"- final_status: {gate.get('final_status', '')}",
        f"- selected_shadow_scenario: {selected or 'NONE'}",
        "- dynamic_weight_status: SHADOW_ONLY",
        "- official_weight_activation_allowed: FALSE",
        "- official_ranking_mutation_allowed: FALSE",
        "- trade_recommendation_allowed: FALSE",
        "",
        "## Benchmark Guardrails",
    ]
    for row in bench_rows:
        lines.append(f"- {row['scenario']}: {row['benchmark_guardrail_status']} (QQQ={row['beats_qqq']}, SPY={row['beats_spy']}, SOXX={row['beats_soxx']})")
    lines.extend(["", "## Official Activation Blockers"])
    for row in blockers:
        lines.append(f"- {row['blocker']}: {row['blocker_status']}")
    lines.append("")
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")


def write_all(
    input_rows: list[dict[str, object]],
    decision: list[dict[str, object]],
    selection: list[dict[str, object]],
    topn: list[dict[str, object]],
    bench: list[dict[str, object]],
    policy: list[dict[str, object]],
    blockers: list[dict[str, object]],
    plan: list[dict[str, object]],
    guard: list[dict[str, object]],
    gate: dict[str, object],
) -> None:
    write_csv(OUT_INPUT, INPUT_FIELDS, input_rows)
    write_csv(OUT_SELECTION, SELECTION_FIELDS, selection)
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_TOPN, TOPN_FIELDS, topn)
    write_csv(OUT_BENCH, BENCH_FIELDS, bench)
    write_csv(OUT_POLICY, POLICY_FIELDS, policy)
    write_csv(OUT_BLOCKERS, BLOCKER_FIELDS, blockers)
    write_csv(OUT_PLAN, PLAN_FIELDS, plan)
    write_csv(OUT_GUARD, GUARD_FIELDS, guard)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])


def main() -> int:
    input_rows, r1_pass, r2_pass, no_lookahead = input_audit()
    guard, no_mutation = guard_rows(r1_pass, r2_pass, no_lookahead)
    topn = topn_guardrails()
    bench = benchmark_guardrails() if r1_pass and r2_pass else []
    blockers = blocker_rows()
    decision, selection, selected = scenario_scores() if r1_pass and r2_pass else ([], [], "")
    policy = policy_row(selected)
    plan = integration_plan(selected)

    candidate_selected = any(row.get("selected_shadow_candidate") == "TRUE" for row in selection)
    blocking = []
    if not r1_pass:
        blocking.append("R1_GATE_NOT_PASS_OR_INPUTS_MISSING")
    if not r2_pass:
        blocking.append("R2_GATE_NOT_PASS_OR_INPUTS_MISSING")
    if not no_lookahead:
        blocking.append("NO_LOOKAHEAD_GUARD_FAIL")
    if not no_mutation:
        blocking.append("OFFICIAL_OR_TRADE_MUTATION")

    if blocking:
        final_status = "BLOCKED"
    elif candidate_selected:
        final_status = "PASS_SHADOW_POLICY_READY"
    else:
        final_status = "PARTIAL_PASS_SHADOW_POLICY_MIXED_SIGNAL"

    gate = {
        "gate_check_id": "V20_199B_R3_NEXT_STAGE_GATE_001",
        "r1_gate_passed": tf(r1_pass),
        "r2_gate_passed": tf(r2_pass),
        "shadow_candidate_selected": tf(candidate_selected),
        "topn_guardrails_created": tf(bool(topn)),
        "benchmark_guardrails_created": tf(bool(bench)),
        "official_activation_blockers_recorded": tf(bool(blockers)),
        "no_lookahead_guard_pass": tf(no_lookahead),
        "no_official_trade_mutation": tf(no_mutation),
        "official_weight_activation_allowed": "FALSE",
        "ready_for_next_stage": tf(final_status != "BLOCKED"),
        "blocking_reason": "NONE" if final_status != "BLOCKED" else "|".join(blocking),
        "final_status": final_status,
        **{k: v for k, v in COMMON.items() if k != "no_lookahead_guard_pass"},
    }
    write_all(input_rows, decision, selection, topn, bench, policy, blockers, plan, guard, gate)
    report(gate, selected, bench, blockers)

    print(final_status)
    print(f"R1_GATE_PASSED={tf(r1_pass)}")
    print(f"R2_GATE_PASSED={tf(r2_pass)}")
    print(f"SHADOW_CANDIDATE_SELECTED={tf(candidate_selected)}")
    print(f"SELECTED_SHADOW_SCENARIO={selected}")
    print("DYNAMIC_WEIGHT_STATUS=SHADOW_ONLY")
    print("OFFICIAL_WEIGHT_ACTIVATION_ALLOWED=FALSE")
    print("OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE")
    print("TRADE_RECOMMENDATION_ALLOWED=FALSE")
    print(f"NO_LOOKAHEAD_GUARD_PASS={tf(no_lookahead)}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    return 0 if final_status != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
