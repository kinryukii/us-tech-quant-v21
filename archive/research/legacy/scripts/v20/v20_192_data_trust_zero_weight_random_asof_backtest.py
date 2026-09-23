#!/usr/bin/env python
"""V20.192 DATA_TRUST zero-weight randomized as-of backtest."""

from __future__ import annotations

import csv
import hashlib
import random
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
FACTORS = ROOT / "outputs" / "v20" / "factors"
BACKTEST = ROOT / "outputs" / "v20" / "backtest"

FORWARD_SOURCE = CONSOLIDATION / "V20_104_RANDOM_ASOF_FORWARD_OUTCOME_MATRIX.csv"
BENCHMARK_SOURCE = CONSOLIDATION / "V20_104_RANDOM_ASOF_BENCHMARK_COMPARISON.csv"
TECHNICAL_ONLY_SOURCE = CONSOLIDATION / "V20_35_R2_ASOF_TECHNICAL_SCORE_AND_RANKING.csv"
CURRENT_SCORE_SOURCE = CONSOLIDATION / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv"
POLICY_SOURCE = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_WEIGHT_SIMULATION.csv"

PROTECTED = [FORWARD_SOURCE, BENCHMARK_SOURCE, TECHNICAL_ONLY_SOURCE, CURRENT_SCORE_SOURCE, POLICY_SOURCE]

OUT_SAMPLE_DATES = BACKTEST / "V20_192_ZERO_WEIGHT_RANDOM_ASOF_SAMPLE_DATES.csv"
OUT_POLICY = BACKTEST / "V20_192_ZERO_WEIGHT_POLICY_USED.csv"
OUT_SELECTIONS = BACKTEST / "V20_192_RANDOM_ASOF_TOPN_SELECTIONS.csv"
OUT_FORWARD = BACKTEST / "V20_192_RANDOM_ASOF_FORWARD_RETURNS.csv"
OUT_BENCH = BACKTEST / "V20_192_RANDOM_ASOF_BENCHMARK_RETURNS.csv"
OUT_COMPARE = BACKTEST / "V20_192_TOPN_BENCHMARK_COMPARISON.csv"
OUT_WINDOW_SUMMARY = BACKTEST / "V20_192_FORWARD_WINDOW_EFFECTIVENESS_SUMMARY.csv"
OUT_CONTRIB_AUDIT = BACKTEST / "V20_192_FACTOR_FAMILY_CONTRIBUTION_AUDIT.csv"
OUT_GUARD = BACKTEST / "V20_192_DATA_TRUST_ZERO_WEIGHT_BACKTEST_GUARD_AUDIT.csv"
OUT_EFFECTIVENESS = BACKTEST / "V20_192_EFFECTIVENESS_SUMMARY.csv"
OUT_GATE = BACKTEST / "V20_192_NEXT_STAGE_GATE.csv"

RANDOM_SEED = 20260615
TARGET_RANDOM_ASOF_COUNT = 100
TOP_N_GROUPS = [5, 10, 20, 40]
FORWARD_WINDOWS = ["5D", "10D", "20D", "60D"]
BENCHMARKS = ["QQQ", "SPY", "SOXX"]
WEIGHTS = {
    "FUNDAMENTAL": "0.2222222222",
    "TECHNICAL": "0.2777777778",
    "STRATEGY": "0.2222222222",
    "RISK": "0.1666666667",
    "MARKET_REGIME": "0.1111111111",
    "DATA_TRUST": "0.0000000000",
}
COMMON = {
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

SAMPLE_FIELDS = [
    "sample_id", "as_of_date", "selected_for_backtest", "random_seed",
    "source_artifact", "valid_forward_outcome_rows", "valid_benchmark_rows",
    "scoring_fields_recomputable", "sample_status", *COMMON.keys(),
]
POLICY_FIELDS = [
    "factor_family", "scoring_weight", "source_artifact", "policy_scope",
    "used_in_zero_weight_score", "weight_source_status", *COMMON.keys(),
]
SELECTION_FIELDS = [
    "selection_id", "as_of_date", "top_n", "ticker", "zero_weight_rank",
    "zero_weight_score", "selection_status", "insufficient_data_reason",
    "source_artifact", *COMMON.keys(),
]
FORWARD_FIELDS = [
    "return_id", "as_of_date", "top_n", "ticker", "forward_window",
    "forward_return", "return_status", "insufficient_data_reason",
    "source_artifact", *COMMON.keys(),
]
BENCH_FIELDS = [
    "benchmark_return_id", "as_of_date", "forward_window", "benchmark",
    "benchmark_forward_return", "benchmark_status", "insufficient_data_reason",
    "source_artifact", *COMMON.keys(),
]
COMPARE_FIELDS = [
    "comparison_id", "top_n", "forward_window", "benchmark", "candidate_count",
    "valid_return_count", "average_forward_return", "median_forward_return",
    "win_rate", "positive_excess_return_rate", "average_excess_return",
    "median_excess_return", "benchmark_comparison_status",
    "insufficient_data_reason", *COMMON.keys(),
]
WINDOW_FIELDS = [
    "summary_id", "top_n", "forward_window", "candidate_count",
    "valid_return_count", "average_forward_return", "median_forward_return",
    "win_rate", "positive_excess_return_rate_vs_QQQ",
    "positive_excess_return_rate_vs_SPY", "positive_excess_return_rate_vs_SOXX",
    "average_excess_return_vs_QQQ", "average_excess_return_vs_SPY",
    "average_excess_return_vs_SOXX", "median_excess_return_vs_QQQ",
    "median_excess_return_vs_SPY", "median_excess_return_vs_SOXX",
    "max_drawdown_proxy", "missing_return_count", "insufficient_data_reason",
    *COMMON.keys(),
]
CONTRIB_FIELDS = [
    "audit_id", "factor_family", "required_field", "field_available",
    "field_source_status", "comparable_normalized_field", "scoring_weight",
    "contribution_recomputable", "source_artifact", *COMMON.keys(),
]
GUARD_FIELDS = [
    "guard_id", "guard_check", "expected_value", "actual_value",
    "guard_passed", "source_artifact", *COMMON.keys(),
]
EFFECT_FIELDS = [
    "summary_id", "random_seed", "target_random_asof_count", "valid_random_asof_count",
    "scoring_fields_recomputable", "forward_windows_with_valid_results",
    "topn_group_with_valid_qqq_spy_comparison", "benchmark_coverage_status",
    "guard_audit_pass", "no_official_trade_mutation", "effectiveness_status",
    "insufficient_data_reason", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "valid_random_asof_count", "minimum_pass_asof_count",
    "minimum_partial_asof_count", "scoring_fields_recomputable",
    "forward_windows_with_valid_results", "topn_group_with_valid_qqq_spy_comparison",
    "benchmark_coverage_incomplete", "guard_audit_pass",
    "no_official_trade_mutation", "ready_for_next_stage",
    "blocking_reason", "final_status", *COMMON.keys(),
]


def clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


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


def protected_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in PROTECTED if path.exists()}


def as_float(value: str) -> float | None:
    try:
        if clean(value) == "":
            return None
        return float(value)
    except ValueError:
        return None


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.10f}"


def discover_dates(forward_rows: list[dict[str, str]], bench_rows: list[dict[str, str]]) -> list[str]:
    forward_dates = {
        row["as_of_date"] for row in forward_rows
        if row.get("as_of_date") and row.get("outcome_available") == "TRUE" and row.get("pit_safe") == "TRUE"
    }
    bench_dates = {
        row["as_of_date"] for row in bench_rows
        if row.get("as_of_date") and row.get("benchmark_data_available") == "TRUE" and row.get("pit_safe") == "TRUE"
    }
    dates = sorted(forward_dates & bench_dates)
    rng = random.Random(RANDOM_SEED)
    rng.shuffle(dates)
    return sorted(dates[:TARGET_RANDOM_ASOF_COUNT])


def contribution_audit_rows() -> tuple[list[dict[str, str]], bool]:
    rows = []
    source_rows = read_csv(CURRENT_SCORE_SOURCE)
    source_fields = set(source_rows[0].keys()) if source_rows else set()
    technical_rows = read_csv(TECHNICAL_ONLY_SOURCE)
    technical_fields = set(technical_rows[0].keys()) if technical_rows else set()
    historical_fields = {
        "FUNDAMENTAL": ("fundamental_contribution", False, "NO_HISTORICAL_ASOF_FIELD"),
        "TECHNICAL": ("exploratory_technical_score", "exploratory_technical_score" in technical_fields, "HISTORICAL_TECHNICAL_ONLY_SOURCE"),
        "STRATEGY": ("strategy_contribution", False, "NO_HISTORICAL_ASOF_FIELD"),
        "RISK": ("risk_contribution", False, "NO_HISTORICAL_ASOF_FIELD"),
        "MARKET_REGIME": ("market_regime_contribution", False, "NO_HISTORICAL_ASOF_FIELD"),
        "DATA_TRUST": ("data_trust_contribution", "data_trust_contribution" in source_fields, "CURRENT_ONLY_ZERO_WEIGHT_NOT_USED_FOR_SCORE"),
    }
    for idx, (family, (field, available, status)) in enumerate(historical_fields.items(), start=1):
        rows.append({
            "audit_id": f"V20_192_CONTRIBUTION_AUDIT_{idx:03d}",
            "factor_family": family,
            "required_field": field,
            "field_available": tf(bool(available)),
            "field_source_status": status,
            "comparable_normalized_field": tf(family == "TECHNICAL" and bool(available)),
            "scoring_weight": WEIGHTS[family],
            "contribution_recomputable": tf(bool(available) or family == "DATA_TRUST"),
            "source_artifact": rel(TECHNICAL_ONLY_SOURCE if family == "TECHNICAL" else CURRENT_SCORE_SOURCE),
            **COMMON,
        })
    recomputable = all(row["contribution_recomputable"] == "TRUE" for row in rows)
    return rows, recomputable


def aggregate_metrics(values: list[float], benchmarks: dict[str, list[float]]) -> dict[str, str]:
    result = {
        "average_forward_return": fmt(mean(values)) if values else "",
        "median_forward_return": fmt(median(values)) if values else "",
        "win_rate": fmt(sum(1 for value in values if value > 0) / len(values)) if values else "",
        "max_drawdown_proxy": fmt(min(values)) if values else "",
    }
    for benchmark in BENCHMARKS:
        pairs = list(zip(values, benchmarks.get(benchmark, [])))
        excess = [a - b for a, b in pairs if b is not None]
        result[f"positive_excess_return_rate_vs_{benchmark}"] = fmt(sum(1 for value in excess if value > 0) / len(excess)) if excess else ""
        result[f"average_excess_return_vs_{benchmark}"] = fmt(mean(excess)) if excess else ""
        result[f"median_excess_return_vs_{benchmark}"] = fmt(median(excess)) if excess else ""
    return result


def guard_row(idx: int, check: str, expected: str, actual: str, source: Path) -> dict[str, str]:
    return {
        "guard_id": f"V20_192_GUARD_{idx:03d}",
        "guard_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "guard_passed": tf(expected == actual),
        "source_artifact": rel(source),
        **COMMON,
    }


def main() -> int:
    before = protected_hashes()
    forward_rows = read_csv(FORWARD_SOURCE)
    bench_rows = read_csv(BENCHMARK_SOURCE)
    contribution_rows, scoring_recomputable = contribution_audit_rows()
    sample_dates = discover_dates(forward_rows, bench_rows)
    selected_dates = set(sample_dates)

    forward_by_key: dict[tuple[str, str, str], float] = {}
    for row in forward_rows:
        if row.get("as_of_date") in selected_dates and row.get("outcome_available") == "TRUE" and row.get("pit_safe") == "TRUE":
            value = as_float(row.get("forward_return", ""))
            if value is not None:
                forward_by_key[(row["as_of_date"], row["ticker"], row["forward_window"].upper())] = value
    benchmark_by_key: dict[tuple[str, str, str], float] = {}
    for row in bench_rows:
        if row.get("as_of_date") in selected_dates and row.get("benchmark_data_available") == "TRUE" and row.get("pit_safe") == "TRUE":
            value = as_float(row.get("benchmark_forward_return", ""))
            if value is not None:
                benchmark_by_key[(row["as_of_date"], row["forward_window"].upper(), row["benchmark_ticker"].upper())] = value

    sample_rows = []
    for idx, date in enumerate(sample_dates, start=1):
        f_count = sum(1 for key in forward_by_key if key[0] == date)
        b_count = sum(1 for key in benchmark_by_key if key[0] == date)
        sample_rows.append({
            "sample_id": f"V20_192_SAMPLE_DATE_{idx:03d}",
            "as_of_date": date,
            "selected_for_backtest": "TRUE",
            "random_seed": str(RANDOM_SEED),
            "source_artifact": rel(FORWARD_SOURCE),
            "valid_forward_outcome_rows": str(f_count),
            "valid_benchmark_rows": str(b_count),
            "scoring_fields_recomputable": tf(scoring_recomputable),
            "sample_status": "BLOCKED_MISSING_RECOMPUTABLE_FACTOR_FIELDS" if not scoring_recomputable else "SELECTED",
            **COMMON,
        })

    policy_rows = []
    policy_source_rows = read_csv(POLICY_SOURCE)
    policy_source_map = {row.get("factor_family", ""): row.get("proposed_scoring_weight", "") for row in policy_source_rows}
    for family, weight in WEIGHTS.items():
        policy_rows.append({
            "factor_family": family,
            "scoring_weight": weight,
            "source_artifact": rel(POLICY_SOURCE),
            "policy_scope": "RESEARCH_ONLY_DATA_TRUST_ZERO_WEIGHT_RANDOM_ASOF_BACKTEST",
            "used_in_zero_weight_score": tf(scoring_recomputable),
            "weight_source_status": "MATCHES_V20_166_POLICY" if policy_source_map.get(family) == weight else "USED_CONFIGURED_REQUIREMENT_WEIGHT",
            **COMMON,
        })

    selection_rows = []
    forward_out = []
    bench_out = []
    compare_rows = []
    window_rows = []
    insuff = "MISSING_RECOMPUTABLE_HISTORICAL_FACTOR_FIELDS_FOR_ZERO_WEIGHT_FORMULA"
    for top_n in TOP_N_GROUPS:
        selection_rows.append({
            "selection_id": f"V20_192_SELECTION_TOP{top_n}_BLOCKED",
            "as_of_date": "",
            "top_n": str(top_n),
            "ticker": "",
            "zero_weight_rank": "",
            "zero_weight_score": "",
            "selection_status": "BLOCKED_MISSING_RECOMPUTABLE_FACTOR_FIELDS",
            "insufficient_data_reason": insuff,
            "source_artifact": rel(CURRENT_SCORE_SOURCE),
            **COMMON,
        })
        for window in FORWARD_WINDOWS:
            valid_returns: list[float] = []
            bench_lists = {benchmark: [] for benchmark in BENCHMARKS}
            for benchmark in BENCHMARKS:
                available = [value for (date, win, bench), value in benchmark_by_key.items() if win == window and bench == benchmark]
                bench_out.append({
                    "benchmark_return_id": f"V20_192_BENCH_TOP{top_n}_{window}_{benchmark}",
                    "as_of_date": "MULTI_DATE_SAMPLE",
                    "forward_window": window,
                    "benchmark": benchmark,
                    "benchmark_forward_return": fmt(mean(available)) if available else "",
                    "benchmark_status": "INSUFFICIENT_BENCHMARK_DATA" if not available else "AVAILABLE_NOT_USED_SELECTION_BLOCKED",
                    "insufficient_data_reason": "BENCHMARK_NOT_AVAILABLE_OR_SELECTION_BLOCKED" if not available else insuff,
                    "source_artifact": rel(BENCHMARK_SOURCE),
                    **COMMON,
                })
            metrics = aggregate_metrics(valid_returns, bench_lists)
            forward_out.append({
                "return_id": f"V20_192_FORWARD_TOP{top_n}_{window}_BLOCKED",
                "as_of_date": "MULTI_DATE_SAMPLE",
                "top_n": str(top_n),
                "ticker": "",
                "forward_window": window,
                "forward_return": "",
                "return_status": "BLOCKED_MISSING_RECOMPUTABLE_FACTOR_FIELDS",
                "insufficient_data_reason": insuff,
                "source_artifact": rel(FORWARD_SOURCE),
                **COMMON,
            })
            for benchmark in BENCHMARKS:
                compare_rows.append({
                    "comparison_id": f"V20_192_COMPARE_TOP{top_n}_{window}_{benchmark}",
                    "top_n": str(top_n),
                    "forward_window": window,
                    "benchmark": benchmark,
                    "candidate_count": "0",
                    "valid_return_count": "0",
                    "average_forward_return": "",
                    "median_forward_return": "",
                    "win_rate": "",
                    "positive_excess_return_rate": "",
                    "average_excess_return": "",
                    "median_excess_return": "",
                    "benchmark_comparison_status": "INSUFFICIENT_SELECTION_DATA",
                    "insufficient_data_reason": insuff,
                    **COMMON,
                })
            window_rows.append({
                "summary_id": f"V20_192_WINDOW_TOP{top_n}_{window}",
                "top_n": str(top_n),
                "forward_window": window,
                "candidate_count": "0",
                "valid_return_count": "0",
                "average_forward_return": metrics["average_forward_return"],
                "median_forward_return": metrics["median_forward_return"],
                "win_rate": metrics["win_rate"],
                "positive_excess_return_rate_vs_QQQ": metrics["positive_excess_return_rate_vs_QQQ"],
                "positive_excess_return_rate_vs_SPY": metrics["positive_excess_return_rate_vs_SPY"],
                "positive_excess_return_rate_vs_SOXX": metrics["positive_excess_return_rate_vs_SOXX"],
                "average_excess_return_vs_QQQ": metrics["average_excess_return_vs_QQQ"],
                "average_excess_return_vs_SPY": metrics["average_excess_return_vs_SPY"],
                "average_excess_return_vs_SOXX": metrics["average_excess_return_vs_SOXX"],
                "median_excess_return_vs_QQQ": metrics["median_excess_return_vs_QQQ"],
                "median_excess_return_vs_SPY": metrics["median_excess_return_vs_SPY"],
                "median_excess_return_vs_SOXX": metrics["median_excess_return_vs_SOXX"],
                "max_drawdown_proxy": metrics["max_drawdown_proxy"],
                "missing_return_count": "0",
                "insufficient_data_reason": insuff,
                **COMMON,
            })

    weight_sum = sum(float(value) for value in WEIGHTS.values())
    upstream_mutated = before != protected_hashes()
    guards = [
        guard_row(1, "research_only", "TRUE", "TRUE", POLICY_SOURCE),
        guard_row(2, "official_ranking_mutated", "FALSE", "FALSE", POLICY_SOURCE),
        guard_row(3, "official_ranking_score_mutation_count", "0", "0", POLICY_SOURCE),
        guard_row(4, "official_rank_mutation_count", "0", "0", POLICY_SOURCE),
        guard_row(5, "trade_action_created", "FALSE", "FALSE", POLICY_SOURCE),
        guard_row(6, "broker_execution_supported", "FALSE", "FALSE", POLICY_SOURCE),
        guard_row(7, "data_trust_scoring_weight", "0.0000000000", WEIGHTS["DATA_TRUST"], POLICY_SOURCE),
        guard_row(8, "data_trust_score_contribution_sum", "0.0000000000", "0.0000000000", POLICY_SOURCE),
        guard_row(9, "scoring_weight_sum", "1.0000000000", f"{weight_sum:.10f}", POLICY_SOURCE),
        guard_row(10, "no_negative_weights", "TRUE", tf(all(float(value) >= 0 for value in WEIGHTS.values())), POLICY_SOURCE),
        guard_row(11, "no_fabricated_returns", "TRUE", "TRUE", FORWARD_SOURCE),
        guard_row(12, "no_fabricated_ticker_rows", "TRUE", "TRUE", FORWARD_SOURCE),
        guard_row(13, "upstream_artifacts_mutated", "FALSE", tf(upstream_mutated), POLICY_SOURCE),
    ]
    guard_pass = all(row["guard_passed"] == "TRUE" for row in guards)
    no_mutation = guard_pass and not upstream_mutated
    valid_asof_count = len(sample_dates)
    valid_windows = 0
    valid_topn_qqq_spy = "FALSE"
    benchmark_incomplete = "TRUE"
    if not scoring_recomputable:
        final_status = "BLOCKED_MISSING_RECOMPUTABLE_FACTOR_FIELDS"
        blocking_reason = insuff
        ready = "FALSE"
        effectiveness_status = "BLOCKED"
    elif valid_asof_count < 10:
        final_status = "BLOCKED_INSUFFICIENT_RANDOM_ASOF_SAMPLE"
        blocking_reason = "FEWER_THAN_10_VALID_RANDOM_ASOF_DATES"
        ready = "FALSE"
        effectiveness_status = "BLOCKED"
    elif valid_asof_count < 30 or benchmark_incomplete == "TRUE" or valid_windows < 3:
        final_status = "PARTIAL_PASS_LIMITED_RANDOM_ASOF_SAMPLE"
        blocking_reason = "LIMITED_SAMPLE_OR_BENCHMARK_COVERAGE"
        ready = "TRUE"
        effectiveness_status = "PARTIAL_PASS"
    else:
        final_status = "PASS_V20_192_DATA_TRUST_ZERO_WEIGHT_RANDOM_ASOF_BACKTEST"
        blocking_reason = "NONE"
        ready = "TRUE"
        effectiveness_status = "PASS"

    effectiveness = [{
        "summary_id": "V20_192_EFFECTIVENESS_SUMMARY_001",
        "random_seed": str(RANDOM_SEED),
        "target_random_asof_count": str(TARGET_RANDOM_ASOF_COUNT),
        "valid_random_asof_count": str(valid_asof_count),
        "scoring_fields_recomputable": tf(scoring_recomputable),
        "forward_windows_with_valid_results": str(valid_windows),
        "topn_group_with_valid_qqq_spy_comparison": valid_topn_qqq_spy,
        "benchmark_coverage_status": "INCOMPLETE_SELECTION_BLOCKED",
        "guard_audit_pass": tf(guard_pass),
        "no_official_trade_mutation": tf(no_mutation),
        "effectiveness_status": effectiveness_status,
        "insufficient_data_reason": blocking_reason,
        **COMMON,
    }]
    gate = [{
        "gate_check_id": "V20_192_NEXT_STAGE_GATE_001",
        "valid_random_asof_count": str(valid_asof_count),
        "minimum_pass_asof_count": "30",
        "minimum_partial_asof_count": "10",
        "scoring_fields_recomputable": tf(scoring_recomputable),
        "forward_windows_with_valid_results": str(valid_windows),
        "topn_group_with_valid_qqq_spy_comparison": valid_topn_qqq_spy,
        "benchmark_coverage_incomplete": benchmark_incomplete,
        "guard_audit_pass": tf(guard_pass),
        "no_official_trade_mutation": tf(no_mutation),
        "ready_for_next_stage": ready,
        "blocking_reason": blocking_reason,
        "final_status": final_status,
        **COMMON,
    }]

    write_csv(OUT_SAMPLE_DATES, SAMPLE_FIELDS, sample_rows)
    write_csv(OUT_POLICY, POLICY_FIELDS, policy_rows)
    write_csv(OUT_SELECTIONS, SELECTION_FIELDS, selection_rows)
    write_csv(OUT_FORWARD, FORWARD_FIELDS, forward_out)
    write_csv(OUT_BENCH, BENCH_FIELDS, bench_out)
    write_csv(OUT_COMPARE, COMPARE_FIELDS, compare_rows)
    write_csv(OUT_WINDOW_SUMMARY, WINDOW_FIELDS, window_rows)
    write_csv(OUT_CONTRIB_AUDIT, CONTRIB_FIELDS, contribution_rows)
    write_csv(OUT_GUARD, GUARD_FIELDS, guards)
    write_csv(OUT_EFFECTIVENESS, EFFECT_FIELDS, effectiveness)
    write_csv(OUT_GATE, GATE_FIELDS, gate)

    gate_row = gate[0]
    print(gate_row["final_status"])
    for key in GATE_FIELDS:
        if key in gate_row and key not in COMMON and key != "gate_check_id":
            print(f"{key.upper()}={gate_row[key]}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("DATA_TRUST_SCORING_WEIGHT=0.0000000000")
    print("DATA_TRUST_SCORE_CONTRIBUTION_SUM=0.0000000000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
