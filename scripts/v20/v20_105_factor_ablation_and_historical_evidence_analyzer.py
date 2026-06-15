#!/usr/bin/env python
"""V20.105 factor ablation and historical evidence analyzer.

Consumes V20.104 random as-of evidence, V20.98B-R5 active research-only base
weights, and V20.98C ETF regime context. This stage summarizes historical
factor-family evidence and records limited factor-level ablation coverage when
PIT-safe factor-level inputs are unavailable. It does not create dynamic factor
weights or execute V20.107.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

V104_BATCH = CONSOLIDATION / "V20_104_RANDOM_ASOF_BACKTEST_BATCH_RUNS.csv"
V104_INPUT = CONSOLIDATION / "V20_104_RANDOM_ASOF_SNAPSHOT_INPUT_AUDIT.csv"
V104_OUTCOME = CONSOLIDATION / "V20_104_RANDOM_ASOF_FORWARD_OUTCOME_MATRIX.csv"
V104_BENCH = CONSOLIDATION / "V20_104_RANDOM_ASOF_BENCHMARK_COMPARISON.csv"
V104_PIT = CONSOLIDATION / "V20_104_RANDOM_ASOF_PIT_SAFETY_AUDIT.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
V98C_AUDIT = CONSOLIDATION / "V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDIT.csv"
V98C_MATRIX = CONSOLIDATION / "V20_98C_ETF_PAIR_RELATIVE_STRENGTH_MATRIX.csv"
V98C_SCAFFOLD = CONSOLIDATION / "V20_98C_ETF_REGIME_FACTOR_MULTIPLIER_SCAFFOLD.csv"
V48_FACTORS = CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv"
V50_FACTORS = CONSOLIDATION / "V20_50_FACTOR_RESEARCH_CONTEXT_PACKET.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_FAMILY = CONSOLIDATION / "V20_105_FACTOR_FAMILY_HISTORICAL_EVIDENCE.csv"
OUT_ABLATION = CONSOLIDATION / "V20_105_FACTOR_ABLATION_EVIDENCE_MATRIX.csv"
OUT_WINDOW = CONSOLIDATION / "V20_105_FORWARD_WINDOW_FACTOR_PERFORMANCE.csv"
OUT_QUALITY = CONSOLIDATION / "V20_105_FACTOR_EVIDENCE_QUALITY_AUDIT.csv"
OUT_READY = CONSOLIDATION / "V20_105_SHADOW_REWEIGHTING_READINESS.csv"
REPORT = READ_CENTER / "V20_105_FACTOR_ABLATION_AND_HISTORICAL_EVIDENCE_REPORT.md"

PASS_STATUS = "PASS_V20_105_FACTOR_ABLATION_AND_HISTORICAL_EVIDENCE_ANALYZER"
PARTIAL_GRANULARITY = "PARTIAL_PASS_V20_105_FACTOR_ABLATION_AND_HISTORICAL_EVIDENCE_ANALYZER_WITH_LIMITED_FACTOR_GRANULARITY"
PARTIAL_COVERAGE = "PARTIAL_PASS_V20_105_FACTOR_ABLATION_AND_HISTORICAL_EVIDENCE_ANALYZER_WITH_LIMITED_HISTORICAL_COVERAGE"
FACTOR_FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
FORWARD_WINDOWS = ["5D", "10D", "20D", "60D", "120D"]
MIN_OBS = 30

FAMILY_FIELDS = [
    "factor_family", "active_research_base_weight", "forward_window",
    "observation_count", "usable_observation_count", "missing_observation_count",
    "mean_forward_return", "median_forward_return", "hit_rate",
    "mean_alpha_vs_spy", "mean_alpha_vs_qqq", "relative_outperformance_rate",
    "max_drawdown_proxy", "adverse_outcome_rate", "evidence_quality",
    "evidence_status", "dynamic_reweighting_eligible",
    "dynamic_reweighting_blocker_reason", "research_only",
    "official_promotion_allowed", "official_recommendation_created",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]

ABLATION_FIELDS = [
    "ablation_id", "factor_family", "ablation_method", "forward_window",
    "baseline_score_source", "ablated_score_source", "baseline_mean_alpha",
    "ablated_mean_alpha", "estimated_factor_contribution",
    "contribution_direction", "observation_count", "evidence_quality",
    "ablation_status", "missing_reason", "research_only",
    "official_promotion_allowed", "official_recommendation_created",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]

WINDOW_FIELDS = [
    "forward_window", "observation_count", "usable_observation_count",
    "mean_forward_return", "median_forward_return", "mean_alpha_vs_spy",
    "mean_alpha_vs_qqq", "hit_rate", "relative_outperformance_rate",
    "evidence_quality", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
    "dynamic_factor_weight_created", "v20_107_execution_status",
]

QUALITY_FIELDS = [
    "quality_check_id", "source_artifact", "artifact_exists", "artifact_non_empty",
    "row_count", "quality_status", "quality_reason", "v20_104_partial_pass_recognized",
    "missing_historical_coverage_classified", "factor_level_granularity_available",
    "source_rank_or_score_used_as_weight", "pit_safety_passed", "research_only",
    "official_promotion_allowed", "official_recommendation_created", "is_official_weight",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
    "dynamic_factor_weight_created", "v20_107_execution_status",
]

READINESS_FIELDS = [
    "readiness_check_id", "active_research_base_weights_available",
    "usable_etf_regime_evidence_available", "random_asof_backtest_available",
    "factor_ablation_evidence_available", "minimum_observation_threshold_met",
    "pit_safety_passed", "evidence_quality", "v20_107_precondition_status",
    "v20_107_execution_status", "dynamic_factor_weight_created", "research_only",
    "official_promotion_allowed", "official_recommendation_created", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def safety(include_extra: bool = False) -> dict[str, str]:
    row = {
        "research_only": "TRUE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
    }
    if include_extra:
        row["is_official_weight"] = "FALSE"
        row["dynamic_factor_weight_created"] = "FALSE"
        row["v20_107_execution_status"] = "NOT_RUN"
    return row


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], str]:
    if not path.exists():
        return [], "MISSING"
    if path.stat().st_size == 0:
        return [], "EMPTY"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [{key: clean(value) for key, value in row.items()} for row in reader]
        return rows, "OK" if reader.fieldnames else "MALFORMED"


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def num(value: object) -> float | None:
    try:
        x = float(clean(value))
    except ValueError:
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return x


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.10f}"


def mean_or_blank(values: list[float]) -> str:
    return fmt(mean(values)) if values else ""


def median_or_blank(values: list[float]) -> str:
    return fmt(median(values)) if values else ""


def r5_weights() -> dict[str, str]:
    rows, status = read_csv(R5_REGISTRY)
    if status != "OK":
        return {}
    return {row["factor_family"]: row["active_research_base_weight"] for row in rows}


def benchmark_alpha_by_key(rows: list[dict[str, str]], benchmark: str) -> dict[tuple[str, str, str], float]:
    result = {}
    for row in rows:
        if row.get("benchmark_ticker") != benchmark:
            continue
        alpha = num(row.get("alpha_vs_benchmark"))
        if alpha is not None:
            result[(row["as_of_date"], row["ticker"], row["forward_window"])] = alpha
    return result


def source_status_row(path: Path, check_id: str, partial: bool, pit_passed: bool, factor_level_available: bool) -> dict[str, str]:
    rows, status = read_csv(path)
    exists = path.exists()
    non_empty = exists and path.stat().st_size > 0
    return {
        "quality_check_id": check_id,
        "source_artifact": rel(path),
        "artifact_exists": tf(exists),
        "artifact_non_empty": tf(non_empty),
        "row_count": str(len(rows) if status == "OK" else 0),
        "quality_status": "PASS" if status == "OK" and non_empty else "WARN_MISSING_OR_EMPTY",
        "quality_reason": "SOURCE_AVAILABLE_FOR_V20_105_ANALYSIS" if status == "OK" and non_empty else status,
        "v20_104_partial_pass_recognized": tf(partial),
        "missing_historical_coverage_classified": "TRUE",
        "factor_level_granularity_available": tf(factor_level_available),
        "source_rank_or_score_used_as_weight": "FALSE",
        "pit_safety_passed": tf(pit_passed),
        **safety(include_extra=True),
    }


def main() -> int:
    batch_rows, batch_status = read_csv(V104_BATCH)
    input_rows, _ = read_csv(V104_INPUT)
    outcome_rows, outcome_status = read_csv(V104_OUTCOME)
    bench_rows, bench_status = read_csv(V104_BENCH)
    pit_rows, pit_status = read_csv(V104_PIT)
    weights = r5_weights()
    spy_alpha = benchmark_alpha_by_key(bench_rows, "SPY")
    qqq_alpha = benchmark_alpha_by_key(bench_rows, "QQQ")

    v104_partial = any(row.get("factor_context_available") == "FALSE" for row in batch_rows)
    pit_passed = bool(pit_rows) and all(row.get("future_factor_data_used") == "FALSE" for row in pit_rows)
    missing_classified = any(row.get("outcome_available") == "FALSE" and row.get("missing_reason") for row in outcome_rows)
    factor_level_available = any(row.get("factor_context_available") == "TRUE" for row in batch_rows)

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in outcome_rows:
        grouped[row.get("forward_window", "")].append(row)

    family_rows: list[dict[str, str]] = []
    ablation_rows: list[dict[str, str]] = []
    window_rows: list[dict[str, str]] = []
    for window in FORWARD_WINDOWS:
        rows = grouped.get(window, [])
        usable = [row for row in rows if row.get("outcome_available") == "TRUE"]
        returns = [num(row.get("forward_return")) for row in usable]
        returns = [value for value in returns if value is not None]
        keys = [(row["as_of_date"], row["ticker"], row["forward_window"]) for row in usable]
        spy_vals = [spy_alpha[key] for key in keys if key in spy_alpha]
        qqq_vals = [qqq_alpha[key] for key in keys if key in qqq_alpha]
        rel_wins = [value for value in spy_vals + qqq_vals if value > 0]
        obs = len(rows)
        usable_count = len(usable)
        missing_count = obs - usable_count
        evidence_quality = "HIGH" if usable_count >= MIN_OBS and missing_count == 0 else ("PARTIAL" if usable_count >= MIN_OBS else "LOW")
        status = "USABLE_EVIDENCE" if usable_count >= MIN_OBS else "INSUFFICIENT_EVIDENCE"
        eligible = usable_count >= MIN_OBS and pit_passed
        adverse = [value for value in returns if value < 0]
        max_drawdown_proxy = min(returns) if returns else None
        for family in FACTOR_FAMILIES:
            family_rows.append({
                "factor_family": family,
                "active_research_base_weight": weights.get(family, ""),
                "forward_window": window,
                "observation_count": str(obs),
                "usable_observation_count": str(usable_count),
                "missing_observation_count": str(missing_count),
                "mean_forward_return": mean_or_blank(returns),
                "median_forward_return": median_or_blank(returns),
                "hit_rate": fmt(sum(1 for value in returns if value > 0) / len(returns)) if returns else "",
                "mean_alpha_vs_spy": mean_or_blank(spy_vals),
                "mean_alpha_vs_qqq": mean_or_blank(qqq_vals),
                "relative_outperformance_rate": fmt(len(rel_wins) / (len(spy_vals) + len(qqq_vals))) if (spy_vals or qqq_vals) else "",
                "max_drawdown_proxy": fmt(max_drawdown_proxy),
                "adverse_outcome_rate": fmt(len(adverse) / len(returns)) if returns else "",
                "evidence_quality": evidence_quality,
                "evidence_status": status,
                "dynamic_reweighting_eligible": tf(eligible),
                "dynamic_reweighting_blocker_reason": "" if eligible else "MINIMUM_OBSERVATION_THRESHOLD_OR_PIT_SAFETY_NOT_MET",
                **safety(),
            })
            baseline = mean(spy_vals + qqq_vals) if (spy_vals or qqq_vals) else None
            ablation_rows.append({
                "ablation_id": f"V20_105_ABL_{family}_{window}",
                "factor_family": family,
                "ablation_method": "FACTOR_FAMILY_LEVEL_PROXY_NO_FACTOR_LEVEL_RECOMPUTE",
                "forward_window": window,
                "baseline_score_source": "V20_104_RANDOM_ASOF_FORWARD_OUTCOME_AND_BENCHMARK_ALPHA",
                "ablated_score_source": "NOT_COMPUTED_FACTOR_LEVEL_DATA_UNAVAILABLE",
                "baseline_mean_alpha": fmt(baseline),
                "ablated_mean_alpha": "",
                "estimated_factor_contribution": "",
                "contribution_direction": "NOT_ESTIMATED",
                "observation_count": str(usable_count),
                "evidence_quality": evidence_quality,
                "ablation_status": "LIMITED_FACTOR_GRANULARITY",
                "missing_reason": "PIT_SAFE_FACTOR_LEVEL_NUMERIC_CONTRIBUTIONS_UNAVAILABLE",
                **safety(),
            })
        window_rows.append({
            "forward_window": window,
            "observation_count": str(obs),
            "usable_observation_count": str(usable_count),
            "mean_forward_return": mean_or_blank(returns),
            "median_forward_return": median_or_blank(returns),
            "mean_alpha_vs_spy": mean_or_blank(spy_vals),
            "mean_alpha_vs_qqq": mean_or_blank(qqq_vals),
            "hit_rate": fmt(sum(1 for value in returns if value > 0) / len(returns)) if returns else "",
            "relative_outperformance_rate": fmt(len(rel_wins) / (len(spy_vals) + len(qqq_vals))) if (spy_vals or qqq_vals) else "",
            "evidence_quality": evidence_quality,
            **safety(include_extra=True),
        })

    quality_rows = [
        source_status_row(path, f"V20_105_QUALITY_{i:03d}", v104_partial, pit_passed, factor_level_available)
        for i, path in enumerate(
            [V104_BATCH, V104_INPUT, V104_OUTCOME, V104_BENCH, V104_PIT, R5_REGISTRY, V98C_AUDIT, V98C_MATRIX, V98C_SCAFFOLD, V48_FACTORS, V50_FACTORS, V49_RESEARCH, V49_OFFICIAL],
            start=1,
        )
    ]
    if missing_classified:
        quality_rows.append({
            "quality_check_id": "V20_105_QUALITY_MISSING_COVERAGE_CLASSIFICATION",
            "source_artifact": rel(V104_OUTCOME),
            "artifact_exists": "TRUE",
            "artifact_non_empty": "TRUE",
            "row_count": str(len(outcome_rows)),
            "quality_status": "PASS",
            "quality_reason": "MISSING_HISTORICAL_COVERAGE_CLASSIFIED_NOT_FABRICATED",
            "v20_104_partial_pass_recognized": tf(v104_partial),
            "missing_historical_coverage_classified": "TRUE",
            "factor_level_granularity_available": tf(factor_level_available),
            "source_rank_or_score_used_as_weight": "FALSE",
            "pit_safety_passed": tf(pit_passed),
            **safety(include_extra=True),
        })

    min_threshold_met = all(
        int(row["usable_observation_count"]) >= MIN_OBS for row in family_rows
    ) if family_rows else False
    active_weights_available = set(weights) == set(FACTOR_FAMILIES)
    usable_etf = bool(read_csv(V98C_AUDIT)[0]) and bool(read_csv(V98C_MATRIX)[0])
    random_available = batch_status == "OK" and outcome_status == "OK" and bench_status == "OK"
    ablation_available = bool(ablation_rows)
    all_high = all(row["evidence_quality"] in {"HIGH", "PARTIAL"} for row in family_rows) if family_rows else False
    readiness_quality = "PARTIAL_LIMITED_FACTOR_GRANULARITY" if not factor_level_available else ("HIGH" if all_high else "LIMITED")
    readiness_rows = [{
        "readiness_check_id": "V20_105_READINESS_001",
        "active_research_base_weights_available": tf(active_weights_available),
        "usable_etf_regime_evidence_available": tf(usable_etf),
        "random_asof_backtest_available": tf(random_available),
        "factor_ablation_evidence_available": tf(ablation_available),
        "minimum_observation_threshold_met": tf(min_threshold_met),
        "pit_safety_passed": tf(pit_passed),
        "evidence_quality": readiness_quality,
        "v20_107_precondition_status": "HISTORICAL_FACTOR_FAMILY_EVIDENCE_AVAILABLE_LIMITED_FACTOR_GRANULARITY",
        "v20_107_execution_status": "NOT_RUN",
        "dynamic_factor_weight_created": "FALSE",
        **safety(),
    }]

    status = PARTIAL_GRANULARITY if not factor_level_available else (PASS_STATUS if min_threshold_met else PARTIAL_COVERAGE)

    write_csv(OUT_FAMILY, FAMILY_FIELDS, family_rows)
    write_csv(OUT_ABLATION, ABLATION_FIELDS, ablation_rows)
    write_csv(OUT_WINDOW, WINDOW_FIELDS, window_rows)
    write_csv(OUT_QUALITY, QUALITY_FIELDS, quality_rows)
    write_csv(OUT_READY, READINESS_FIELDS, readiness_rows)

    lines = [
        "# V20.105 Factor Ablation And Historical Evidence Analyzer",
        "",
        "## Current Result",
        f"- wrapper_status: {status}",
        f"- factor_family_rows: {len(family_rows)}",
        f"- ablation_rows: {len(ablation_rows)}",
        f"- forward_window_rows: {len(window_rows)}",
        f"- v20_104_partial_pass_recognized: {tf(v104_partial)}",
        "- ablation_status: LIMITED_FACTOR_GRANULARITY",
        "- dynamic_factor_weight_created: FALSE",
        "- v20_107_execution_status: NOT_RUN",
        "",
        "## Safety Boundary",
        "- research_only: TRUE",
        "- official_promotion_allowed: FALSE",
        "- official_recommendation_created: FALSE",
        "- is_official_weight: FALSE",
        "- weight_mutated: FALSE",
        "- trade_action_created: FALSE",
        "- broker_execution_supported: FALSE",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(status)
    print(f"FACTOR_FAMILY_ROWS={len(family_rows)}")
    print(f"ABLATION_ROWS={len(ablation_rows)}")
    print(f"FORWARD_WINDOW_ROWS={len(window_rows)}")
    print(f"V20_104_PARTIAL_PASS_RECOGNIZED={tf(v104_partial)}")
    print(f"FACTOR_LEVEL_GRANULARITY_AVAILABLE={tf(factor_level_available)}")
    print("DYNAMIC_FACTOR_WEIGHT_CREATED=FALSE")
    print("V20_107_EXECUTION_STATUS=NOT_RUN")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print(f"OUTPUT_FACTOR_FAMILY={rel(OUT_FAMILY)}")
    print(f"OUTPUT_ABLATION={rel(OUT_ABLATION)}")
    print(f"OUTPUT_FORWARD_WINDOW={rel(OUT_WINDOW)}")
    print(f"OUTPUT_QUALITY={rel(OUT_QUALITY)}")
    print(f"OUTPUT_READINESS={rel(OUT_READY)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
