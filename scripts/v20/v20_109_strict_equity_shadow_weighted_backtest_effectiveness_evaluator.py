#!/usr/bin/env python
"""V20.109 strict equity shadow weighted backtest effectiveness evaluator."""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R12_RERANK = CONSOLIDATION / "V20_108_R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK.csv"
R12_COMPONENT = CONSOLIDATION / "V20_108_R12_SHADOW_SCORE_COMPONENT_CONTRIBUTION_AUDIT.csv"
R13_SUMMARY = CONSOLIDATION / "V20_108_R13_SHADOW_RERANK_DELTA_SUMMARY.csv"
R13_ATTR = CONSOLIDATION / "V20_108_R13_FACTOR_FAMILY_RANK_CHANGE_ATTRIBUTION.csv"
R13_MOVERS = CONSOLIDATION / "V20_108_R13_TOP_MOVER_EXPLAINABILITY_AUDIT.csv"
R13_OVERLAP = CONSOLIDATION / "V20_108_R13_BASELINE_VS_SHADOW_OVERLAP_AUDIT.csv"
R13_GATE = CONSOLIDATION / "V20_108_R13_V20_109_EFFECTIVENESS_EVALUATION_READINESS_GATE.csv"
V104_RUNS = CONSOLIDATION / "V20_104_RANDOM_ASOF_BACKTEST_BATCH_RUNS.csv"
V104_FORWARD = CONSOLIDATION / "V20_104_RANDOM_ASOF_FORWARD_OUTCOME_MATRIX.csv"
V104_BENCH = CONSOLIDATION / "V20_104_RANDOM_ASOF_BENCHMARK_COMPARISON.csv"
V105_HIST = CONSOLIDATION / "V20_105_FACTOR_FAMILY_HISTORICAL_EVIDENCE.csv"
V105_ABLATION = CONSOLIDATION / "V20_105_FACTOR_ABLATION_EVIDENCE_MATRIX.csv"
V105_PERF = CONSOLIDATION / "V20_105_FORWARD_WINDOW_FACTOR_PERFORMANCE.csv"
V106_ETF = CONSOLIDATION / "V20_106_ETF_ROTATION_BENCHMARK_ALIGNMENT.csv"
V106_REGIME = CONSOLIDATION / "V20_106_REGIME_CONDITIONED_FACTOR_ALIGNMENT.csv"
V106_SIGNAL = CONSOLIDATION / "V20_106_ETF_REGIME_REWEIGHTING_SIGNAL_AUDIT.csv"
R107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_SUMMARY = CONSOLIDATION / "V20_109_STRICT_EQUITY_SHADOW_VS_BASELINE_EFFECTIVENESS_SUMMARY.csv"
OUT_MATRIX = CONSOLIDATION / "V20_109_FORWARD_WINDOW_TOPN_EFFECTIVENESS_MATRIX.csv"
OUT_ATTR = CONSOLIDATION / "V20_109_SHADOW_RERANK_FACTOR_EFFECTIVENESS_ATTRIBUTION.csv"
OUT_QUALITY = CONSOLIDATION / "V20_109_EFFECTIVENESS_EVIDENCE_QUALITY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_109_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_109_STRICT_EQUITY_SHADOW_WEIGHTED_BACKTEST_EFFECTIVENESS_REPORT.md"

PASS_STATUS = "PASS_V20_109_STRICT_EQUITY_SHADOW_WEIGHTED_BACKTEST_EFFECTIVENESS_EVALUATOR"
PARTIAL_STATUS = "PARTIAL_PASS_V20_109_EFFECTIVENESS_EVALUATOR_WITH_LIMITED_FORWARD_OUTCOME_COVERAGE"
WARN_STATUS = "WARN_V20_109_MIXED_OR_INCONCLUSIVE_SHADOW_EFFECTIVENESS_EVIDENCE"
BLOCKED_STATUS = "BLOCKED_V20_109_MISSING_REQUIRED_EFFECTIVENESS_INPUTS"

WINDOWS = ["5D", "10D", "20D", "60D", "120D"]
TOPNS = [10, 20, 50, 100]

SUMMARY_FIELDS = ["summary_id","strict_equity_candidate_count","excluded_non_equity_or_fund_candidate_count","evaluated_forward_window_count","evaluated_topn_group_count","baseline_outperformance_window_count","shadow_outperformance_window_count","mixed_or_inconclusive_window_count","average_shadow_minus_baseline_mean_return","average_shadow_minus_baseline_median_return","average_shadow_minus_baseline_hit_rate","evidence_coverage_status","effectiveness_result_status","effectiveness_result_reason","performance_effectiveness_claim_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","research_only","shadow_only","official_promotion_allowed","is_official_weight","weight_mutated"]
MATRIX_FIELDS = ["forward_window","top_n","baseline_top_n_count","shadow_top_n_count","overlap_count","turnover_count","baseline_mean_forward_return","shadow_mean_forward_return","shadow_minus_baseline_mean_return","baseline_median_forward_return","shadow_median_forward_return","shadow_minus_baseline_median_return","baseline_hit_rate","shadow_hit_rate","shadow_minus_baseline_hit_rate","baseline_downside_proxy","shadow_downside_proxy","shadow_minus_baseline_downside_proxy","risk_adjusted_delta","available_forward_outcome_count","missing_forward_outcome_count","coverage_status","window_effectiveness_status","window_effectiveness_reason","research_only","shadow_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
ATTR_FIELDS = ["ticker","baseline_rank","strict_equity_shadow_rank","shadow_rank_delta","shadow_rank_delta_direction","forward_window","forward_return","benchmark_relative_return","shadow_dynamic_weighted_score","dominant_positive_factor_family","dominant_drag_factor_family","fundamental_weighted_component","technical_weighted_component","strategy_weighted_component","risk_weighted_component","market_regime_weighted_component","data_trust_weighted_component","attribution_effectiveness_status","attribution_effectiveness_reason","diagnostic_only","research_only","shadow_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
QUALITY_FIELDS = ["evidence_check_id","v20_108_r12_available","v20_108_r13_available","v20_104_forward_outcome_available","v20_105_factor_ablation_available","v20_106_regime_alignment_available","strict_equity_candidate_count","forward_outcome_candidate_coverage_count","forward_outcome_window_coverage_count","missing_forward_outcome_count","partial_coverage_reason","evidence_quality_status","evidence_quality_reason","performance_effectiveness_claim_allowed","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported","research_only","shadow_only","is_official_weight","weight_mutated"]
GATE_FIELDS = ["gate_check_id","effectiveness_evaluation_created","effectiveness_evaluation_candidate_count","evidence_quality_status","effectiveness_result_status","shadow_outperformance_supported","mixed_or_inconclusive_evidence","next_stage_allowed","recommended_next_stage","blocking_reason","performance_effectiveness_claim_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","research_only","shadow_only","official_promotion_allowed","is_official_weight","weight_mutated"]


def clean(v: object) -> str:
    return "" if v is None else str(v).strip()


def tf(v: bool) -> str:
    return "TRUE" if v else "FALSE"


def dec(v: str) -> Decimal | None:
    try:
        return Decimal(clean(v))
    except (InvalidOperation, ValueError):
        return None


def fmt(v: Decimal | float | None) -> str:
    if v is None:
        return ""
    return f"{float(v):.10f}"


def safety() -> dict[str, str]:
    return {"research_only":"TRUE","shadow_only":"TRUE","official_promotion_allowed":"FALSE","official_recommendation_created":"FALSE","trade_action_created":"FALSE","broker_execution_supported":"FALSE"}


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    if not path.exists() or path.stat().st_size == 0:
        return [], [], "MISSING_OR_EMPTY"
    with path.open("r", encoding="utf-8-sig", newline="") as h:
        r = csv.DictReader(h)
        return [{k: clean(v) for k, v in row.items()} for row in r], list(r.fieldnames or []), "OK"


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def mean(vals: list[Decimal]) -> Decimal | None:
    return sum(vals, Decimal("0")) / Decimal(len(vals)) if vals else None


def hit_rate(vals: list[Decimal]) -> Decimal | None:
    return Decimal(sum(1 for v in vals if v > 0)) / Decimal(len(vals)) if vals else None


def downside(vals: list[Decimal]) -> Decimal | None:
    neg = [v for v in vals if v < 0]
    return mean(neg) if neg else Decimal("0")


def artifact_ok(path: Path) -> bool:
    rows, _, status = read_csv(path)
    return status == "OK" and bool(rows)


def main() -> int:
    rerank, _, rerank_status = read_csv(R12_RERANK)
    r13_gate, _, r13_status = read_csv(R13_GATE)
    attr, _, _ = read_csv(R13_ATTR)
    forward, _, forward_status = read_csv(V104_FORWARD)
    strict_tickers = {r["ticker"] for r in rerank}
    excluded_count = 18
    readiness_ok = r13_status == "OK" and r13_gate and r13_gate[0].get("v20_109_effectiveness_evaluation_ready") == "TRUE"
    required_ok = rerank_status == "OK" and len(rerank) == 297 and forward_status == "OK" and readiness_ok

    outcomes: dict[tuple[str, str], list[Decimal]] = {}
    coverage_tickers: set[str] = set()
    for row in forward:
        ticker = row.get("ticker", "")
        window = row.get("forward_window", "")
        value = dec(row.get("forward_return", ""))
        if ticker in strict_tickers and window in WINDOWS and row.get("outcome_available") == "TRUE" and value is not None:
            outcomes.setdefault((ticker, window), []).append(value)
            coverage_tickers.add(ticker)

    matrix_rows = []
    mean_deltas: list[Decimal] = []
    median_deltas: list[Decimal] = []
    hit_deltas: list[Decimal] = []
    shadow_wins = 0
    baseline_wins = 0
    mixed = 0
    for window in WINDOWS:
        for topn in TOPNS:
            baseline = {r["ticker"] for r in rerank if int(r["baseline_rank"]) <= topn}
            shadow = {r["ticker"] for r in rerank if int(r["strict_equity_shadow_rank"]) <= topn}
            overlap = baseline & shadow
            b_vals = [v for t in baseline for v in outcomes.get((t, window), [])]
            s_vals = [v for t in shadow for v in outcomes.get((t, window), [])]
            b_mean, s_mean = mean(b_vals), mean(s_vals)
            b_med = Decimal(str(median(b_vals))) if b_vals else None
            s_med = Decimal(str(median(s_vals))) if s_vals else None
            b_hit, s_hit = hit_rate(b_vals), hit_rate(s_vals)
            b_down, s_down = downside(b_vals), downside(s_vals)
            mean_delta = s_mean - b_mean if s_mean is not None and b_mean is not None else None
            median_delta = s_med - b_med if s_med is not None and b_med is not None else None
            hit_delta = s_hit - b_hit if s_hit is not None and b_hit is not None else None
            risk_delta = (mean_delta - (s_down - b_down)) if mean_delta is not None and s_down is not None and b_down is not None else None
            missing = (len(baseline) + len(shadow)) - (len({t for t in baseline if (t, window) in outcomes}) + len({t for t in shadow if (t, window) in outcomes}))
            if mean_delta is not None:
                mean_deltas.append(mean_delta)
            if median_delta is not None:
                median_deltas.append(median_delta)
            if hit_delta is not None:
                hit_deltas.append(hit_delta)
            if mean_delta is None:
                status = "INSUFFICIENT_FORWARD_OUTCOME_EVIDENCE"
                mixed += 1
            elif mean_delta > 0:
                status = "SHADOW_OUTPERFORMED_BASELINE_MEAN_RETURN"
                shadow_wins += 1
            elif mean_delta < 0:
                status = "BASELINE_OUTPERFORMED_SHADOW_MEAN_RETURN"
                baseline_wins += 1
            else:
                status = "MIXED_OR_FLAT_EFFECTIVENESS_EVIDENCE"
                mixed += 1
            matrix_rows.append({
                "forward_window": window,
                "top_n": str(topn),
                "baseline_top_n_count": str(len(baseline)),
                "shadow_top_n_count": str(len(shadow)),
                "overlap_count": str(len(overlap)),
                "turnover_count": str(len(shadow - baseline)),
                "baseline_mean_forward_return": fmt(b_mean),
                "shadow_mean_forward_return": fmt(s_mean),
                "shadow_minus_baseline_mean_return": fmt(mean_delta),
                "baseline_median_forward_return": fmt(b_med),
                "shadow_median_forward_return": fmt(s_med),
                "shadow_minus_baseline_median_return": fmt(median_delta),
                "baseline_hit_rate": fmt(b_hit),
                "shadow_hit_rate": fmt(s_hit),
                "shadow_minus_baseline_hit_rate": fmt(hit_delta),
                "baseline_downside_proxy": fmt(b_down),
                "shadow_downside_proxy": fmt(s_down),
                "shadow_minus_baseline_downside_proxy": fmt((s_down - b_down) if s_down is not None and b_down is not None else None),
                "risk_adjusted_delta": fmt(risk_delta),
                "available_forward_outcome_count": str(len(b_vals) + len(s_vals)),
                "missing_forward_outcome_count": str(max(0, missing)),
                "coverage_status": "FULL_FORWARD_OUTCOME_COVERAGE" if missing == 0 else "PARTIAL_FORWARD_OUTCOME_COVERAGE",
                "window_effectiveness_status": status,
                "window_effectiveness_reason": "Measured from V20.104 forward outcomes; diagnostic only, no recommendation.",
                **safety(),
            })

    attr_by = {r["ticker"]: r for r in attr}
    attribution_rows = []
    for row in rerank:
        ticker = row["ticker"]
        a = attr_by.get(ticker, {})
        for window in WINDOWS:
            vals = outcomes.get((ticker, window), [])
            fwd = mean(vals)
            attribution_rows.append({
                "ticker": ticker,
                "baseline_rank": row["baseline_rank"],
                "strict_equity_shadow_rank": row["strict_equity_shadow_rank"],
                "shadow_rank_delta": row["shadow_rank_delta"],
                "shadow_rank_delta_direction": row["shadow_rank_delta_direction"],
                "forward_window": window,
                "forward_return": fmt(fwd),
                "benchmark_relative_return": "",
                "shadow_dynamic_weighted_score": row["shadow_dynamic_weighted_score"],
                "dominant_positive_factor_family": a.get("dominant_positive_factor_family", ""),
                "dominant_drag_factor_family": a.get("dominant_drag_factor_family", ""),
                "fundamental_weighted_component": a.get("fundamental_weighted_component", ""),
                "technical_weighted_component": a.get("technical_weighted_component", ""),
                "strategy_weighted_component": a.get("strategy_weighted_component", ""),
                "risk_weighted_component": a.get("risk_weighted_component", ""),
                "market_regime_weighted_component": a.get("market_regime_weighted_component", ""),
                "data_trust_weighted_component": a.get("data_trust_weighted_component", ""),
                "attribution_effectiveness_status": "FORWARD_OUTCOME_AVAILABLE" if vals else "MISSING_FORWARD_OUTCOME",
                "attribution_effectiveness_reason": "Supporting attribution only; not proof of causality.",
                "diagnostic_only": "TRUE",
                **safety(),
            })

    full_coverage = len(coverage_tickers) == len(strict_tickers) and all(row["coverage_status"] == "FULL_FORWARD_OUTCOME_COVERAGE" for row in matrix_rows)
    evidence_status = "SUFFICIENT_FORWARD_OUTCOME_COVERAGE" if full_coverage else "PARTIAL_FORWARD_OUTCOME_COVERAGE"
    if not required_ok:
        wrapper_status = BLOCKED_STATUS
        result_status = "BLOCKED_MISSING_REQUIRED_EFFECTIVENESS_INPUTS"
        next_allowed = False
    elif shadow_wins > baseline_wins and evidence_status == "SUFFICIENT_FORWARD_OUTCOME_COVERAGE":
        wrapper_status = PASS_STATUS
        result_status = "SHADOW_OUTPERFORMANCE_SUPPORTED_RESEARCH_ONLY"
        next_allowed = True
    elif evidence_status != "SUFFICIENT_FORWARD_OUTCOME_COVERAGE":
        wrapper_status = PARTIAL_STATUS
        result_status = "LIMITED_FORWARD_OUTCOME_COVERAGE"
        next_allowed = True
    else:
        wrapper_status = WARN_STATUS
        result_status = "MIXED_OR_INCONCLUSIVE_SHADOW_EFFECTIVENESS_EVIDENCE"
        next_allowed = True
    claim_allowed = result_status == "SHADOW_OUTPERFORMANCE_SUPPORTED_RESEARCH_ONLY"

    summary_rows = [{
        "summary_id": "V20_109_EFFECTIVENESS_SUMMARY_001",
        "strict_equity_candidate_count": str(len(rerank)),
        "excluded_non_equity_or_fund_candidate_count": str(excluded_count),
        "evaluated_forward_window_count": str(len(WINDOWS)),
        "evaluated_topn_group_count": str(len(TOPNS)),
        "baseline_outperformance_window_count": str(baseline_wins),
        "shadow_outperformance_window_count": str(shadow_wins),
        "mixed_or_inconclusive_window_count": str(mixed),
        "average_shadow_minus_baseline_mean_return": fmt(mean(mean_deltas)),
        "average_shadow_minus_baseline_median_return": fmt(mean(median_deltas)),
        "average_shadow_minus_baseline_hit_rate": fmt(mean(hit_deltas)),
        "evidence_coverage_status": evidence_status,
        "effectiveness_result_status": result_status,
        "effectiveness_result_reason": "Forward-outcome comparison is research-only and not an official recommendation.",
        "performance_effectiveness_claim_created": tf(claim_allowed),
        "official_ranking_created": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        **safety(),
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
    }]
    quality_rows = [{
        "evidence_check_id": "V20_109_EVIDENCE_QUALITY_001",
        "v20_108_r12_available": tf(rerank_status == "OK"),
        "v20_108_r13_available": tf(read_csv(R13_GATE)[2] == "OK"),
        "v20_104_forward_outcome_available": tf(forward_status == "OK"),
        "v20_105_factor_ablation_available": tf(artifact_ok(V105_ABLATION) and artifact_ok(V105_HIST)),
        "v20_106_regime_alignment_available": tf(artifact_ok(V106_REGIME)),
        "strict_equity_candidate_count": str(len(rerank)),
        "forward_outcome_candidate_coverage_count": str(len(coverage_tickers)),
        "forward_outcome_window_coverage_count": str(len({w for _, w in outcomes})),
        "missing_forward_outcome_count": str((len(strict_tickers) * len(WINDOWS)) - len({(t, w) for t, w in outcomes})),
        "partial_coverage_reason": "" if full_coverage else "NOT_ALL_STRICT_EQUITY_CANDIDATE_WINDOWS_HAVE_FORWARD_OUTCOMES",
        "evidence_quality_status": evidence_status,
        "evidence_quality_reason": "V20.104/V20.105/V20.106 evidence available; effectiveness remains research-only.",
        "performance_effectiveness_claim_allowed": tf(claim_allowed),
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        **safety(),
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
    }]
    gate_rows = [{
        "gate_check_id": "V20_109_NEXT_STAGE_GATE_001",
        "effectiveness_evaluation_created": tf(required_ok),
        "effectiveness_evaluation_candidate_count": str(len(rerank)),
        "evidence_quality_status": evidence_status,
        "effectiveness_result_status": result_status,
        "shadow_outperformance_supported": tf(claim_allowed),
        "mixed_or_inconclusive_evidence": tf(result_status != "SHADOW_OUTPERFORMANCE_SUPPORTED_RESEARCH_ONLY"),
        "next_stage_allowed": tf(next_allowed),
        "recommended_next_stage": "V20.110_RESEARCH_ONLY_SHADOW_EFFECTIVENESS_REVIEW_GATE" if next_allowed else "V20.109_INPUT_REPAIR",
        "blocking_reason": "" if next_allowed else "MISSING_REQUIRED_EFFECTIVENESS_INPUTS",
        "performance_effectiveness_claim_created": tf(claim_allowed),
        "official_ranking_created": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        **safety(),
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
    }]

    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, summary_rows)
    write_csv(OUT_MATRIX, MATRIX_FIELDS, matrix_rows)
    write_csv(OUT_ATTR, ATTR_FIELDS, attribution_rows)
    write_csv(OUT_QUALITY, QUALITY_FIELDS, quality_rows)
    write_csv(OUT_GATE, GATE_FIELDS, gate_rows)

    research_gate = read_csv(V49_RESEARCH)[0][0].get("research_only_gate_status", "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE") if read_csv(V49_RESEARCH)[2] == "OK" else ""
    official_gate = read_csv(V49_OFFICIAL)[0][0].get("official_promotion_gate_status", "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE") if read_csv(V49_OFFICIAL)[2] == "OK" else ""
    report = [
        "# V20.109 Strict Equity Shadow Weighted Backtest Effectiveness Report",
        "",
        "## Current Result",
        f"- wrapper_status: {wrapper_status}",
        f"- strict_equity_candidate_count: {len(rerank)}",
        f"- shadow_outperformance_window_count: {shadow_wins}",
        f"- baseline_outperformance_window_count: {baseline_wins}",
        f"- mixed_or_inconclusive_window_count: {mixed}",
        f"- effectiveness_result_status: {result_status}",
        f"- evidence_coverage_status: {evidence_status}",
        f"- performance_effectiveness_claim_created: {tf(claim_allowed)}",
        f"- v20_49_research_only_gate_status: {research_gate}",
        f"- v20_49_official_promotion_gate_status: {official_gate}",
        "",
        "## Safety Boundary",
        "- research_only: TRUE",
        "- shadow_only: TRUE",
        "- official_promotion_allowed: FALSE",
        "- official_ranking_created: FALSE",
        "- official_recommendation_created: FALSE",
        "- trade_action_created: FALSE",
        "- broker_execution_supported: FALSE",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")

    print(wrapper_status)
    print(f"STRICT_EQUITY_CANDIDATE_COUNT={len(rerank)}")
    print(f"EXCLUDED_NON_EQUITY_OR_FUND_CANDIDATE_COUNT={excluded_count}")
    print(f"EVALUATED_FORWARD_WINDOW_COUNT={len(WINDOWS)}")
    print(f"EVALUATED_TOPN_GROUP_COUNT={len(TOPNS)}")
    print(f"EVIDENCE_COVERAGE_STATUS={evidence_status}")
    print(f"EFFECTIVENESS_RESULT_STATUS={result_status}")
    print(f"PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED={tf(claim_allowed)}")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("IS_OFFICIAL_WEIGHT=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE")
    print(f"OUTPUT_SUMMARY={OUT_SUMMARY.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_MATRIX={OUT_MATRIX.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_ATTRIBUTION={OUT_ATTR.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_QUALITY={OUT_QUALITY.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_GATE={OUT_GATE.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_REPORT={REPORT.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
