#!/usr/bin/env python
"""V20.106 ETF rotation benchmark alignment analyzer.

Combines usable V20.98C ETF regime evidence, V20.104 random as-of benchmark
comparison evidence, and V20.105 factor-family historical evidence. The stage
only emits research evidence and V20.107 precondition audit rows; no ETF
multipliers, dynamic factor weights, official recommendations, or trade actions
are created.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
V98C_AUDIT = CONSOLIDATION / "V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDIT.csv"
V98C_MATRIX = CONSOLIDATION / "V20_98C_ETF_PAIR_RELATIVE_STRENGTH_MATRIX.csv"
V98C_SCAFFOLD = CONSOLIDATION / "V20_98C_ETF_REGIME_FACTOR_MULTIPLIER_SCAFFOLD.csv"
R2_ETF_CACHE = CONSOLIDATION / "V20_98C_R2_CONTROLLED_ETF_PRICE_REFRESH_CACHE.csv"
V104_BENCH = CONSOLIDATION / "V20_104_RANDOM_ASOF_BENCHMARK_COMPARISON.csv"
V104_OUTCOME = CONSOLIDATION / "V20_104_RANDOM_ASOF_FORWARD_OUTCOME_MATRIX.csv"
V104_PIT = CONSOLIDATION / "V20_104_RANDOM_ASOF_PIT_SAFETY_AUDIT.csv"
V105_FAMILY = CONSOLIDATION / "V20_105_FACTOR_FAMILY_HISTORICAL_EVIDENCE.csv"
V105_ABLATION = CONSOLIDATION / "V20_105_FACTOR_ABLATION_EVIDENCE_MATRIX.csv"
V105_WINDOW = CONSOLIDATION / "V20_105_FORWARD_WINDOW_FACTOR_PERFORMANCE.csv"
V105_QUALITY = CONSOLIDATION / "V20_105_FACTOR_EVIDENCE_QUALITY_AUDIT.csv"
V105_READY = CONSOLIDATION / "V20_105_SHADOW_REWEIGHTING_READINESS.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_ALIGNMENT = CONSOLIDATION / "V20_106_ETF_ROTATION_BENCHMARK_ALIGNMENT.csv"
OUT_FACTOR_ALIGNMENT = CONSOLIDATION / "V20_106_REGIME_CONDITIONED_FACTOR_ALIGNMENT.csv"
OUT_SIGNAL_AUDIT = CONSOLIDATION / "V20_106_ETF_REGIME_REWEIGHTING_SIGNAL_AUDIT.csv"
OUT_PRECONDITION = CONSOLIDATION / "V20_106_SHADOW_REWEIGHTING_PRECONDITION_AUDIT.csv"
REPORT = READ_CENTER / "V20_106_ETF_ROTATION_BENCHMARK_ALIGNMENT_REPORT.md"

PASS_STATUS = "PASS_V20_106_ETF_ROTATION_BENCHMARK_ALIGNMENT_ANALYZER"
PARTIAL_GRANULARITY = "PARTIAL_PASS_V20_106_ETF_ROTATION_BENCHMARK_ALIGNMENT_ANALYZER_WITH_LIMITED_FACTOR_GRANULARITY"
PARTIAL_COVERAGE = "PARTIAL_PASS_V20_106_ETF_ROTATION_BENCHMARK_ALIGNMENT_ANALYZER_WITH_LIMITED_HISTORICAL_COVERAGE"
FORWARD_WINDOWS = ["5D", "10D", "20D", "60D", "120D"]
FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
PAIR_BENCHMARK_MAP = {
    "QQQ_SPY": "QQQ",
    "XLK_SPY": "SPY",
    "SOXX_QQQ": "QQQ",
    "SMH_QQQ": "QQQ",
    "SOXX_SPY": "SPY",
    "SMH_SPY": "SPY",
    "TQQQ_SQQQ": "QQQ",
    "SOXL_SOXS": "QQQ",
    "RSP_SPY": "SPY",
    "XLU_SPY": "SPY",
    "XLP_SPY": "SPY",
    "TLT_SPY": "SPY",
    "GLD_SPY": "SPY",
}

ALIGNMENT_FIELDS = [
    "regime_signal_id", "etf_pair", "regime_classification", "left_ticker",
    "right_ticker", "relative_strength_status", "benchmark_alignment_status",
    "aligned_benchmark_ticker", "forward_window", "benchmark_observation_count",
    "mean_benchmark_forward_return", "mean_alpha_vs_benchmark",
    "relative_outperformance_rate", "evidence_quality", "alignment_status",
    "missing_reason", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]

FACTOR_ALIGNMENT_FIELDS = [
    "factor_family", "active_research_base_weight", "regime_classification",
    "forward_window", "factor_observation_count", "factor_mean_alpha",
    "factor_hit_rate", "factor_adverse_outcome_rate", "etf_regime_support_status",
    "suggested_shadow_multiplier_direction", "suggested_shadow_multiplier_reason",
    "multiplier_activation_allowed", "dynamic_weight_created", "evidence_quality",
    "evidence_status", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]

SIGNAL_AUDIT_FIELDS = [
    "signal_audit_id", "regime_classification", "factor_family", "forward_window",
    "alignment_rows_available", "factor_family_evidence_available",
    "limited_factor_granularity_recognized", "multiplier_activation_allowed",
    "dynamic_factor_weight_created", "v20_107_execution_status",
    "audit_status", "audit_reason", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]

PRECONDITION_FIELDS = [
    "readiness_check_id", "active_research_base_weights_available",
    "usable_etf_regime_evidence_available", "random_asof_backtest_available",
    "factor_family_evidence_available", "etf_benchmark_alignment_available",
    "factor_granularity_status", "minimum_observation_threshold_met",
    "pit_safety_passed", "evidence_quality", "v20_107_precondition_status",
    "v20_107_execution_status", "dynamic_factor_weight_created", "research_only",
    "official_promotion_allowed", "official_recommendation_created",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def safety(extra: bool = False) -> dict[str, str]:
    row = {
        "research_only": "TRUE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
    }
    if extra:
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


def weights() -> dict[str, str]:
    rows, status = read_csv(R5_REGISTRY)
    return {row["factor_family"]: row["active_research_base_weight"] for row in rows} if status == "OK" else {}


def benchmark_groups(rows: list[dict[str, str]]) -> dict[tuple[str, str], list[dict[str, str]]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row.get("benchmark_data_available") == "TRUE":
            grouped[(row.get("benchmark_ticker", ""), row.get("forward_window", ""))].append(row)
    return grouped


def main() -> int:
    regime_rows, _ = read_csv(V98C_AUDIT)
    bench_rows, bench_status = read_csv(V104_BENCH)
    outcome_rows, outcome_status = read_csv(V104_OUTCOME)
    pit_rows, _ = read_csv(V104_PIT)
    family_rows, family_status = read_csv(V105_FAMILY)
    ablation_rows, _ = read_csv(V105_ABLATION)
    readiness_rows, _ = read_csv(V105_READY)
    weight_map = weights()

    grouped_bench = benchmark_groups(bench_rows)
    alignment_rows: list[dict[str, str]] = []
    for regime in regime_rows:
        pair = regime["etf_pair"]
        aligned = PAIR_BENCHMARK_MAP.get(pair, "SPY")
        for window in FORWARD_WINDOWS:
            group = grouped_bench.get((aligned, window), [])
            bench_returns = [num(row.get("benchmark_forward_return")) for row in group]
            alphas = [num(row.get("alpha_vs_benchmark")) for row in group]
            bench_returns = [value for value in bench_returns if value is not None]
            alphas = [value for value in alphas if value is not None]
            obs = len(group)
            evidence_quality = "PARTIAL" if obs >= 30 else "LOW"
            available = obs > 0
            alignment_rows.append({
                "regime_signal_id": regime["regime_signal_id"],
                "etf_pair": pair,
                "regime_classification": regime["regime_classification"],
                "left_ticker": regime["left_ticker"],
                "right_ticker": regime["right_ticker"],
                "relative_strength_status": regime["relative_strength_status"],
                "benchmark_alignment_status": "BENCHMARK_ALIGNMENT_AVAILABLE" if available else "MISSING_BENCHMARK_ALIGNMENT",
                "aligned_benchmark_ticker": aligned,
                "forward_window": window,
                "benchmark_observation_count": str(obs),
                "mean_benchmark_forward_return": fmt(mean(bench_returns)) if bench_returns else "",
                "mean_alpha_vs_benchmark": fmt(mean(alphas)) if alphas else "",
                "relative_outperformance_rate": fmt(sum(1 for value in alphas if value > 0) / len(alphas)) if alphas else "",
                "evidence_quality": evidence_quality,
                "alignment_status": "USABLE_ALIGNMENT_EVIDENCE" if available else "INSUFFICIENT_ALIGNMENT_EVIDENCE",
                "missing_reason": "" if available else "NO_BENCHMARK_COMPARISON_ROWS_FOR_PAIR_WINDOW",
                **safety(),
            })

    family_by_key = {(row["factor_family"], row["forward_window"]): row for row in family_rows}
    regimes = sorted({row["regime_classification"] for row in regime_rows})
    factor_alignment: list[dict[str, str]] = []
    for regime in regimes:
        for family in FAMILIES:
            for window in FORWARD_WINDOWS:
                row = family_by_key.get((family, window), {})
                obs = clean(row.get("usable_observation_count"))
                mean_alpha = clean(row.get("mean_alpha_vs_spy")) or clean(row.get("mean_alpha_vs_qqq"))
                hit_rate = clean(row.get("hit_rate"))
                adverse = clean(row.get("adverse_outcome_rate"))
                quality = clean(row.get("evidence_quality")) or "LOW"
                status = clean(row.get("evidence_status")) or "INSUFFICIENT_EVIDENCE"
                usable = status == "USABLE_EVIDENCE"
                direction = "REVIEW_UP_OR_DOWN_AT_V20_107_ONLY" if usable else "NO_MULTIPLIER_REVIEW"
                factor_alignment.append({
                    "factor_family": family,
                    "active_research_base_weight": weight_map.get(family, ""),
                    "regime_classification": regime,
                    "forward_window": window,
                    "factor_observation_count": obs,
                    "factor_mean_alpha": mean_alpha,
                    "factor_hit_rate": hit_rate,
                    "factor_adverse_outcome_rate": adverse,
                    "etf_regime_support_status": "USABLE_ETF_REGIME_CONTEXT" if regime_rows else "MISSING_ETF_REGIME_CONTEXT",
                    "suggested_shadow_multiplier_direction": direction,
                    "suggested_shadow_multiplier_reason": "FACTOR_FAMILY_EVIDENCE_AVAILABLE_BUT_MULTIPLIER_NOT_ACTIVATED"
                    if usable else "INSUFFICIENT_FACTOR_FAMILY_EVIDENCE",
                    "multiplier_activation_allowed": "FALSE",
                    "dynamic_weight_created": "FALSE",
                    "evidence_quality": quality,
                    "evidence_status": status,
                    **safety(),
                })

    limited_granularity = any(row.get("ablation_status") == "LIMITED_FACTOR_GRANULARITY" for row in ablation_rows)
    alignment_available = bool(alignment_rows) and all(row["alignment_status"] == "USABLE_ALIGNMENT_EVIDENCE" for row in alignment_rows)
    family_available = family_status == "OK" and bool(family_rows)
    active_weights = set(weight_map) == set(FAMILIES)
    usable_etf = bool(regime_rows) and all(row.get("data_available") == "TRUE" for row in regime_rows)
    random_available = bench_status == "OK" and outcome_status == "OK"
    pit_passed = bool(pit_rows) and all(row.get("future_factor_data_used") == "FALSE" for row in pit_rows)
    threshold_met = all(int(row.get("usable_observation_count") or "0") >= 30 for row in family_rows) if family_rows else False
    precondition = "PARTIAL_READY_WITH_LIMITED_GRANULARITY" if limited_granularity else (
        "READY_FOR_FACTOR_FAMILY_SHADOW_REWEIGHTING" if alignment_available and threshold_met else "PARTIAL_READY_WITH_LIMITED_HISTORICAL_COVERAGE"
    )
    precondition_rows = [{
        "readiness_check_id": "V20_106_PRECONDITION_001",
        "active_research_base_weights_available": tf(active_weights),
        "usable_etf_regime_evidence_available": tf(usable_etf),
        "random_asof_backtest_available": tf(random_available),
        "factor_family_evidence_available": tf(family_available),
        "etf_benchmark_alignment_available": tf(alignment_available),
        "factor_granularity_status": "LIMITED_FACTOR_GRANULARITY" if limited_granularity else "FACTOR_FAMILY_GRANULARITY",
        "minimum_observation_threshold_met": tf(threshold_met),
        "pit_safety_passed": tf(pit_passed),
        "evidence_quality": "PARTIAL_LIMITED_FACTOR_GRANULARITY" if limited_granularity else ("USABLE" if alignment_available else "LIMITED"),
        "v20_107_precondition_status": precondition,
        "v20_107_execution_status": "NOT_RUN",
        "dynamic_factor_weight_created": "FALSE",
        **safety(),
    }]

    signal_rows: list[dict[str, str]] = []
    for idx, row in enumerate(factor_alignment, start=1):
        signal_rows.append({
            "signal_audit_id": f"V20_106_SIGNAL_{idx:04d}",
            "regime_classification": row["regime_classification"],
            "factor_family": row["factor_family"],
            "forward_window": row["forward_window"],
            "alignment_rows_available": tf(alignment_available),
            "factor_family_evidence_available": tf(row["evidence_status"] == "USABLE_EVIDENCE"),
            "limited_factor_granularity_recognized": tf(limited_granularity),
            "multiplier_activation_allowed": "FALSE",
            "dynamic_factor_weight_created": "FALSE",
            "v20_107_execution_status": "NOT_RUN",
            "audit_status": "PASS_RESEARCH_ONLY_SIGNAL_AUDIT",
            "audit_reason": "ALIGNMENT_CONTEXT_AVAILABLE_MULTIPLIERS_AND_DYNAMIC_WEIGHTS_NOT_CREATED",
            **safety(extra=True),
        })

    status = PARTIAL_GRANULARITY if limited_granularity else (PASS_STATUS if alignment_available else PARTIAL_COVERAGE)
    write_csv(OUT_ALIGNMENT, ALIGNMENT_FIELDS, alignment_rows)
    write_csv(OUT_FACTOR_ALIGNMENT, FACTOR_ALIGNMENT_FIELDS, factor_alignment)
    write_csv(OUT_SIGNAL_AUDIT, SIGNAL_AUDIT_FIELDS, signal_rows)
    write_csv(OUT_PRECONDITION, PRECONDITION_FIELDS, precondition_rows)

    lines = [
        "# V20.106 ETF Rotation Benchmark Alignment Analyzer",
        "",
        "## Current Result",
        f"- wrapper_status: {status}",
        f"- etf_alignment_rows: {len(alignment_rows)}",
        f"- regime_conditioned_factor_rows: {len(factor_alignment)}",
        f"- signal_audit_rows: {len(signal_rows)}",
        f"- v20_107_precondition_status: {precondition}",
        "- limited_factor_granularity_recognized: " + tf(limited_granularity),
        "- multiplier_activation_allowed: FALSE",
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
    print(f"ETF_ALIGNMENT_ROWS={len(alignment_rows)}")
    print(f"REGIME_CONDITIONED_FACTOR_ROWS={len(factor_alignment)}")
    print(f"SIGNAL_AUDIT_ROWS={len(signal_rows)}")
    print(f"LIMITED_FACTOR_GRANULARITY_RECOGNIZED={tf(limited_granularity)}")
    print(f"V20_107_PRECONDITION_STATUS={precondition}")
    print("MULTIPLIER_ACTIVATION_ALLOWED=FALSE")
    print("DYNAMIC_FACTOR_WEIGHT_CREATED=FALSE")
    print("V20_107_EXECUTION_STATUS=NOT_RUN")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print(f"OUTPUT_ALIGNMENT={rel(OUT_ALIGNMENT)}")
    print(f"OUTPUT_FACTOR_ALIGNMENT={rel(OUT_FACTOR_ALIGNMENT)}")
    print(f"OUTPUT_SIGNAL_AUDIT={rel(OUT_SIGNAL_AUDIT)}")
    print(f"OUTPUT_PRECONDITION={rel(OUT_PRECONDITION)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
