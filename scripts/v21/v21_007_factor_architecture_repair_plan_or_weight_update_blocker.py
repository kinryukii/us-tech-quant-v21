#!/usr/bin/env python
"""V21.007 factor architecture repair plan or weight update blocker.

Research-only planning stage after V21.006. It diagnoses whether repair should
focus on factor architecture, regime segmentation, outlier neutralization,
risk/overheat logic, or data contracts. It never mutates official decisions.
"""

from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean


STAGE_NAME = "V21_007_FACTOR_ARCHITECTURE_REPAIR_PLAN_OR_WEIGHT_UPDATE_BLOCKER"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

V21_006_INPUTS = [
    OUT_DIR / "V21_006_PRIMARY_DATASET_VALIDATION.csv",
    OUT_DIR / "V21_006_RANK_BUCKET_SIGNIFICANCE_STATS.csv",
    OUT_DIR / "V21_006_RANK_MONOTONICITY_TEST.csv",
    OUT_DIR / "V21_006_FACTOR_FAMILY_IC_SIGNIFICANCE_STATS.csv",
    OUT_DIR / "V21_006_RANDOM_BASELINE_COMPARISON.csv",
    OUT_DIR / "V21_006_SUBSAMPLE_ROBUSTNESS_STATS.csv",
    OUT_DIR / "V21_006_OUTLIER_CONCENTRATION_AUDIT.csv",
    OUT_DIR / "V21_006_RISK_OVERHEAT_ROBUSTNESS_TEST.csv",
    OUT_DIR / "V21_006_BENCHMARK_SIGNIFICANCE_STATS.csv",
    OUT_DIR / "V21_006_DECISION_GRADE_ROBUSTNESS_SCORECARD.csv",
    OUT_DIR / "V21_006_BACKTEST_STATISTICAL_TEST_SUMMARY.csv",
    ROOT / "outputs" / "v21" / "read_center" / "V21_006_FACTOR_BACKTEST_STATISTICAL_SIGNIFICANCE_AND_ROBUSTNESS_TEST_REPORT.md",
]

VERDICT_AUDIT = OUT_DIR / "V21_007_V21_006_VERDICT_INGEST_AUDIT.csv"
OUTLIER_DIAG = OUT_DIR / "V21_007_OUTLIER_DEPENDENCY_DIAGNOSIS.csv"
REGIME_DIAG = OUT_DIR / "V21_007_REGIME_DEPENDENCY_DIAGNOSIS.csv"
FAMILY_DIAG = OUT_DIR / "V21_007_FACTOR_FAMILY_REPAIR_DIAGNOSIS.csv"
RANK_DIAG = OUT_DIR / "V21_007_RANK_ARCHITECTURE_DIAGNOSIS.csv"
RISK_DIAG = OUT_DIR / "V21_007_RISK_OVERHEAT_REPAIR_DIAGNOSIS.csv"
BLOCKER = OUT_DIR / "V21_007_WEIGHT_UPDATE_BLOCKER_DECISION.csv"
ROADMAP = OUT_DIR / "V21_007_REPAIR_ROADMAP.csv"
SUMMARY = OUT_DIR / "V21_007_FACTOR_ARCHITECTURE_REPAIR_PLAN_SUMMARY.csv"
REPORT = READ_CENTER_DIR / "V21_007_FACTOR_ARCHITECTURE_REPAIR_PLAN_OR_WEIGHT_UPDATE_BLOCKER_REPORT.md"

FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
REGIME_LABELS = ["risk_on", "risk_off", "neutral", "high_vix", "low_vix", "QQQ_uptrend", "QQQ_downtrend", "SPY_uptrend", "SPY_downtrend"]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def fmt(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.10f}"
    return value


def parse_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def pass_bool(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def missing_inputs() -> list[str]:
    return [path.relative_to(ROOT).as_posix() for path in V21_006_INPUTS if not path.exists() or path.stat().st_size == 0]


def build_verdict_audit(summary_006: dict[str, str], missing: list[str]) -> list[dict[str, object]]:
    expected_status = summary_006.get("final_status", "")
    expected_verdict = summary_006.get("final_verdict", "")
    equivalent = "OUTLIER_OR_REGIME_DEPENDENT" in expected_status or "OUTLIER_OR_REGIME_DEPENDENT" in expected_verdict
    checks = [
        ("required_v21_006_artifacts_present", not missing, "|".join(missing) if missing else "ALL_PRESENT", "TRUE"),
        ("v21_006_final_status_ingested", bool(expected_status), expected_status, "PARTIAL_PASS_V21_006_SIGNAL_OUTLIER_OR_REGIME_DEPENDENT_OR_EQUIVALENT"),
        ("v21_006_outlier_or_regime_dependent_status", equivalent, expected_status or expected_verdict, "TRUE"),
        ("research_only", summary_006.get("research_only") == "TRUE", summary_006.get("research_only", ""), "TRUE"),
        ("data_trust_ranking_weight_zero", summary_006.get("data_trust_ranking_weight") == "0", summary_006.get("data_trust_ranking_weight", ""), "0"),
        ("data_trust_alpha_contribution_zero", summary_006.get("data_trust_alpha_contribution") == "0", summary_006.get("data_trust_alpha_contribution", ""), "0"),
        ("official_ranking_mutation_count_zero", summary_006.get("official_ranking_mutation_count") == "0", summary_006.get("official_ranking_mutation_count", ""), "0"),
        ("official_factor_weight_mutation_count_zero", summary_006.get("official_factor_weight_mutation_count") == "0", summary_006.get("official_factor_weight_mutation_count", ""), "0"),
        ("official_recommendation_count_zero", summary_006.get("official_recommendation_count") == "0", summary_006.get("official_recommendation_count", ""), "0"),
        ("trade_action_count_zero", summary_006.get("trade_action_count") == "0", summary_006.get("trade_action_count", ""), "0"),
        ("shadow_activation_false", summary_006.get("shadow_activation") == "FALSE", summary_006.get("shadow_activation", ""), "FALSE"),
    ]
    return [
        {
            "audit_item": name,
            "audit_passed": pass_bool(passed),
            "observed_value": observed,
            "required_value": required,
            "research_only": "TRUE",
        }
        for name, passed, observed, required in checks
    ]


def build_outlier_diag(outlier_rows: list[dict[str, str]]) -> tuple[list[dict[str, object]], str]:
    by_variant = defaultdict(list)
    for row in outlier_rows:
        by_variant[row.get("audit_variant", "")].append(row)
    rows = []
    dependent_count = sum(1 for row in outlier_rows if row.get("outlier_dependency_classification") == "OUTLIER_DEPENDENT")
    max_ticker_share = max([parse_float(row.get("top_ticker_positive_contribution_share")) or 0.0 for row in outlier_rows] or [0.0])
    max_date_share = max([parse_float(row.get("top_date_positive_contribution_share")) or 0.0 for row in outlier_rows] or [0.0])
    if not outlier_rows:
        overall = "UNKNOWN_INSUFFICIENT_DATA"
    elif dependent_count >= 2 or max_ticker_share >= 0.20 or max_date_share >= 0.20:
        overall = "HIGH"
    elif dependent_count == 1 or max_ticker_share >= 0.10 or max_date_share >= 0.10:
        overall = "MODERATE"
    else:
        overall = "LOW"

    diagnostics = [
        ("best_ticker", max_ticker_share, "HIGH" if max_ticker_share >= 0.20 else "MODERATE" if max_ticker_share >= 0.10 else "LOW", "top ticker positive contribution share"),
        ("best_as_of_date", max_date_share, "HIGH" if max_date_share >= 0.20 else "MODERATE" if max_date_share >= 0.10 else "LOW", "top date positive contribution share"),
        ("top_1pct_return_observations", dependent_count, "HIGH" if dependent_count >= 2 else "MODERATE" if dependent_count == 1 else "LOW", "windows marked OUTLIER_DEPENDENT after excluding top 1% returns or related variants"),
        ("specific_sector_or_theme", "", "UNKNOWN_INSUFFICIENT_DATA", "sector/theme fields unavailable in V21.006 outputs"),
    ]
    for driver, value, classification, note in diagnostics:
        rows.append(
            {
                "dependency_driver": driver,
                "observed_value": value,
                "driver_classification": classification,
                "overall_outlier_dependency_classification": overall,
                "diagnostic_note": note,
                "research_only": "TRUE",
            }
        )
    return rows, overall


def build_regime_diag(subsample_rows: list[dict[str, str]], regime_005: list[dict[str, str]]) -> tuple[list[dict[str, object]], str]:
    rows = []
    flips = sum(1 for row in subsample_rows if row.get("persistence_classification") == "FLIPS")
    unavailable_splits = sum(1 for row in subsample_rows if row.get("sample_status") == "MISSING_REQUIRED_FIELD")
    split_count = len(subsample_rows)
    regime_available = [row for row in regime_005 if row.get("diagnostic_status") != "MISSING_REGIME_LABEL_SOURCE" and parse_float(row.get("top10_mean_forward_return")) is not None]
    missing_labels = [row.get("regime_label", "") for row in regime_005 if row.get("diagnostic_status") == "MISSING_REGIME_LABEL_SOURCE"]

    if not regime_005 and split_count == 0:
        overall = "REGIME_DATA_INSUFFICIENT"
    elif flips >= 4:
        overall = "REGIME_MIXING_DAMAGES_SIGNAL"
    elif regime_available and all((parse_float(row.get("top10_mean_forward_return")) or 0.0) > 0 for row in regime_available):
        overall = "REGIME_SPECIFIC_SIGNAL_PRESENT"
    elif unavailable_splits > split_count / 3:
        overall = "REGIME_DATA_INSUFFICIENT"
    else:
        overall = "NO_CLEAR_REGIME_STRUCTURE"

    for label in REGIME_LABELS:
        label_rows = [row for row in regime_005 if row.get("regime_label") == label]
        top10_values = [parse_float(row.get("top10_mean_forward_return")) for row in label_rows]
        top10_values = [value for value in top10_values if value is not None]
        status = label_rows[0].get("diagnostic_status", "MISSING_REGIME_LABEL_SOURCE") if label_rows else "MISSING_REGIME_LABEL_SOURCE"
        rows.append(
            {
                "regime_label": label,
                "available_window_count": len(top10_values),
                "mean_top10_forward_return": mean(top10_values) if top10_values else None,
                "positive_window_count": sum(1 for value in top10_values if value > 0),
                "diagnostic_status": status,
                "regime_dependency_classification": overall if status != "MISSING_REGIME_LABEL_SOURCE" else "REGIME_DATA_INSUFFICIENT",
                "recommended_segmentation_test": pass_bool(label in {"risk_on", "risk_off", "neutral"} or label in set(missing_labels)),
                "research_only": "TRUE",
            }
        )
    rows.append(
        {
            "regime_label": "V21_006_SUBSAMPLE_FLIP_SUMMARY",
            "available_window_count": split_count,
            "mean_top10_forward_return": None,
            "positive_window_count": flips,
            "diagnostic_status": f"flip_rows={flips};missing_required_field_rows={unavailable_splits}",
            "regime_dependency_classification": overall,
            "recommended_segmentation_test": "TRUE",
            "research_only": "TRUE",
        }
    )
    return rows, overall


def build_family_diag(ic_rows: list[dict[str, str]], ablation_rows: list[dict[str, str]], regime_classification: str) -> list[dict[str, object]]:
    rows = []
    by_family_ic = defaultdict(list)
    for row in ic_rows:
        by_family_ic[row.get("factor_family", "")].append(row)
    by_family_ablation = defaultdict(list)
    for row in ablation_rows:
        by_family_ablation[row.get("ablation_family", "")].append(row)

    for family in FAMILIES:
        if family == "DATA_TRUST":
            recommendation = "USE_AS_GATE_NOT_ALPHA"
            evidence = "audit-only zero-alpha control"
        else:
            classifications = Counter(row.get("robustness_classification", "") for row in by_family_ic[family])
            removal_improved = sum(1 for row in by_family_ablation[family] if row.get("removal_effect") == "REMOVAL_IMPROVED_TOP_BUCKET")
            robust = classifications.get("ROBUST_POSITIVE", 0)
            negative = classifications.get("NEGATIVE", 0)
            mixed = classifications.get("MIXED", 0)
            if family == "RISK" and removal_improved >= 2:
                recommendation = "REDEFINE_SCORING"
            elif family == "MARKET_REGIME" and regime_classification in {"REGIME_MIXING_DAMAGES_SIGNAL", "REGIME_SPECIFIC_SIGNAL_PRESENT"}:
                recommendation = "SPLIT_BY_REGIME"
            elif robust >= 1 and negative == 0:
                recommendation = "KEEP_AS_IS_FOR_RESEARCH"
            elif negative >= 1 or mixed >= 2 or removal_improved >= 2:
                recommendation = "REDUCE_OR_ZERO_WEIGHT_IN_SHADOW_RESEARCH"
            elif by_family_ic[family]:
                recommendation = "REDEFINE_SCORING"
            else:
                recommendation = "INSUFFICIENT_EVIDENCE"
            evidence = f"ic={dict(classifications)}; removal_improved_windows={removal_improved}"
        rows.append(
            {
                "factor_family": family,
                "repair_diagnosis": recommendation,
                "evidence_summary": evidence,
                "data_trust_alpha_contribution": "0" if family == "DATA_TRUST" else "",
                "official_weight_change_allowed": "FALSE",
                "research_only": "TRUE",
            }
        )
    return rows


def build_rank_diag(monotonicity_rows: list[dict[str, str]], scorecard_rows: list[dict[str, str]], random_rows: list[dict[str, str]], benchmark_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    absent_or_mixed = [row for row in monotonicity_rows if row.get("monotonicity_classification") in {"ABSENT", "MIXED"}]
    max_random_pct = max([parse_float(row.get("actual_percentile_vs_random")) or 0.0 for row in random_rows] or [0.0])
    benchmark_unavailable = sum(1 for row in benchmark_rows if row.get("benchmark_data_status") == "UNAVAILABLE")
    failed_gates = [row.get("hard_gate", "") for row in scorecard_rows if row.get("gate_passed") == "FALSE"]
    unstable = bool(absent_or_mixed)
    issues = [
        ("component_weights", unstable, "rank buckets not monotonic; weight update blocked"),
        ("component_scaling", unstable, "weak random-baseline percentile and non-monotonic quintiles"),
        ("nonlinear_factor_interactions", unstable, "top buckets do not dominate middle buckets consistently"),
        ("risk_penalty_placement", "rank_ic_positive_statistically_meaningful_core_family" in failed_gates or unstable, "risk family mixed/negative in V21.006 IC diagnostics"),
        ("overheat_penalty_placement", unstable, "risk/overheat tests inconclusive; no official loosening allowed"),
        ("benchmark_regime_mixing", max_random_pct < 0.60, f"max random baseline percentile={max_random_pct:.3f}"),
        ("missing_sector_neutrality", benchmark_unavailable > 0, "sector/theme concentration fields unavailable; sector-neutral audit needed"),
        ("insufficient_sample_quality", bool(failed_gates), "failed hard gates: " + "|".join(failed_gates)),
    ]
    return [
        {
            "architecture_problem": problem,
            "problem_flagged": pass_bool(bool(flagged)),
            "evidence_summary": evidence,
            "ranking_architecture_stability": "UNSTABLE" if unstable else "STABLE_FOR_RESEARCH_ONLY",
            "official_weight_update_allowed": "FALSE",
            "research_only": "TRUE",
        }
        for problem, flagged, evidence in issues
    ]


def build_risk_diag(risk_rows: list[dict[str, str]], risk_005: list[dict[str, str]]) -> tuple[list[dict[str, object]], str]:
    rows = []
    classifications = Counter(row.get("risk_overheat_logic_classification", "") for row in risk_rows)
    false_blocks = [parse_float(row.get("false_block_candidate_rate")) for row in risk_rows]
    false_blocks = [value for value in false_blocks if value is not None and value > 0]
    if classifications.get("OVERLY_RESTRICTIVE", 0) > 0 or false_blocks:
        overall = "OVERLY_RESTRICTIVE"
    elif classifications.get("PROTECTIVE", 0) > 0 and classifications.get("INCONCLUSIVE", 0) == 0:
        overall = "PROTECTIVE"
    elif classifications.get("MIXED", 0) > 0:
        overall = "MIXED"
    else:
        overall = "INCONCLUSIVE"
    for row in risk_rows:
        rows.append(
            {
                "forward_return_window": row.get("forward_return_window", ""),
                "v21_006_risk_overheat_classification": row.get("risk_overheat_logic_classification", ""),
                "false_block_candidate_rate": row.get("false_block_candidate_rate", ""),
                "blocked_observation_count": row.get("risk_blocked_observation_count", ""),
                "repair_diagnosis": "REPAIR_ONLY_STAGE_RECOMMENDED" if false_blocks else "NO_OFFICIAL_LOOSENING_INCONCLUSIVE",
                "overall_risk_overheat_repair_classification": overall,
                "official_gate_loosening_allowed": "FALSE",
                "research_only": "TRUE",
            }
        )
    if not rows:
        rows.append(
            {
                "forward_return_window": "ALL",
                "v21_006_risk_overheat_classification": "MISSING",
                "false_block_candidate_rate": "",
                "blocked_observation_count": "",
                "repair_diagnosis": "INCONCLUSIVE",
                "overall_risk_overheat_repair_classification": "INCONCLUSIVE",
                "official_gate_loosening_allowed": "FALSE",
                "research_only": "TRUE",
            }
        )
    return rows, overall


def choose_decision(outlier_classification: str, regime_classification: str, risk_classification: str, missing: list[str]) -> tuple[str, str, str]:
    if missing:
        return "WEIGHT_UPDATE_BLOCKED_MORE_EVIDENCE_REQUIRED", "PASS_V21_007_WEIGHT_UPDATE_BLOCKED_MORE_EVIDENCE_REQUIRED", "V21.012_SECTOR_NEUTRAL_AND_THEME_CONCENTRATION_AUDIT"
    if regime_classification in {"REGIME_MIXING_DAMAGES_SIGNAL", "REGIME_SPECIFIC_SIGNAL_PRESENT"}:
        return "WEIGHT_UPDATE_BLOCKED_REGIME_SEGMENTATION_REQUIRED", "PASS_V21_007_WEIGHT_UPDATE_BLOCKED_REGIME_SEGMENTATION_REQUIRED", "V21.008_REGIME_SEGMENTED_FACTOR_BACKTEST"
    if outlier_classification in {"HIGH", "MODERATE"}:
        return "WEIGHT_UPDATE_BLOCKED_ARCHITECTURE_REPAIR_REQUIRED", "PASS_V21_007_WEIGHT_UPDATE_BLOCKED_ARCHITECTURE_REPAIR_REQUIRED", "V21.009_OUTLIER_NEUTRALIZED_FACTOR_BACKTEST"
    if risk_classification in {"OVERLY_RESTRICTIVE", "MIXED"}:
        return "WEIGHT_UPDATE_BLOCKED_ARCHITECTURE_REPAIR_REQUIRED", "PASS_V21_007_WEIGHT_UPDATE_BLOCKED_ARCHITECTURE_REPAIR_REQUIRED", "V21.010_RISK_OVERHEAT_FALSE_BLOCK_REPAIR"
    return "WEIGHT_UPDATE_BLOCKED_MORE_EVIDENCE_REQUIRED", "PASS_V21_007_WEIGHT_UPDATE_BLOCKED_MORE_EVIDENCE_REQUIRED", "V21.011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST"


def build_roadmap(recommended: str, outlier_classification: str, regime_classification: str, risk_classification: str) -> list[dict[str, object]]:
    stages = [
        ("V21.008_REGIME_SEGMENTED_FACTOR_BACKTEST", "Test factor signal separately by risk_on/risk_off/neutral and add missing high_vix/low_vix/trend labels.", regime_classification in {"REGIME_MIXING_DAMAGES_SIGNAL", "REGIME_SPECIFIC_SIGNAL_PRESENT", "REGIME_DATA_INSUFFICIENT"}),
        ("V21.009_OUTLIER_NEUTRALIZED_FACTOR_BACKTEST", "Retest top buckets after neutralizing top 1% returns, best ticker/date dependence, and winsorized returns.", outlier_classification in {"HIGH", "MODERATE"}),
        ("V21.010_RISK_OVERHEAT_FALSE_BLOCK_REPAIR", "Audit false blocks and risk/overheat placement without loosening official risk gates.", risk_classification in {"OVERLY_RESTRICTIVE", "MIXED", "INCONCLUSIVE"}),
        ("V21.011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST", "Research-only rescaling and nonlinear interaction tests for weak/mixed families.", True),
        ("V21.012_SECTOR_NEUTRAL_AND_THEME_CONCENTRATION_AUDIT", "Add sector/theme concentration diagnostics missing from V21.006.", True),
    ]
    ordered = sorted(stages, key=lambda item: (item[0] != recommended, not item[2], item[0]))
    return [
        {
            "roadmap_order": idx,
            "candidate_next_stage": stage,
            "selected_recommended_next_stage": pass_bool(stage == recommended),
            "priority_reason": reason,
            "research_only": "TRUE",
        }
        for idx, (stage, reason, _flagged) in enumerate(ordered, start=1)
    ]


def write_report(summary: dict[str, object], outlier_classification: str, regime_classification: str, risk_classification: str, recommended: str) -> None:
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    text = f"""# V21.007 Factor Architecture Repair Plan Or Weight Update Blocker Report

## Executive summary
This is a research-only repair planning stage. V21.006 evidence was ingested to decide whether weights remain blocked or whether a narrow research-only repair experiment is justified.

## Final blocker decision
{summary['weight_update_blocker_decision']}

Final status: {summary['final_status']}

## Why V21.006 is not enough for weight update
V21.006 did not establish robust decision-grade evidence. The signal remained outlier-dependent or regime-dependent, rank monotonicity was unstable, and no production, real-book, or official activation verdict is allowed.

## Outlier dependency diagnosis
Overall classification: {outlier_classification}.

## Regime dependency diagnosis
Overall classification: {regime_classification}. Regime-specific segmentation is research-only and must not mutate official weights.

## Factor family repair diagnosis
Family-level repair instructions are written to V21_007_FACTOR_FAMILY_REPAIR_DIAGNOSIS.csv. DATA_TRUST is always USE_AS_GATE_NOT_ALPHA.

## Rank architecture diagnosis
Rank architecture is treated as unstable when monotonicity is absent or mixed. Official ranking architecture and official weights remain unchanged.

## Risk and overheat repair diagnosis
Overall classification: {risk_classification}. Any risk/overheat change is limited to a repair-only research stage.

## DATA_TRUST zero-alpha confirmation
DATA_TRUST ranking contribution is 0 and alpha contribution is 0. DATA_TRUST is gate/audit metadata only.

## Explicit blocked actions
No official ranking mutation. No official factor weight mutation. No official recommendation. No trade action. No shadow activation. No production readiness, real-book readiness, or official activation.

## Allowed research-only experiments
Regime-segmented backtests, outlier-neutralized backtests, risk/overheat false-block audits, factor family rescaling tests, nonlinear interaction tests, and sector/theme concentration audits are allowed only as research outputs.

## Ordered repair roadmap
The ordered roadmap is written to V21_007_REPAIR_ROADMAP.csv.

## Recommended next stage
{recommended}
"""
    REPORT.write_text(text, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    missing = missing_inputs()
    summary_006 = first(read_csv(OUT_DIR / "V21_006_BACKTEST_STATISTICAL_TEST_SUMMARY.csv"))
    verdict_rows = build_verdict_audit(summary_006, missing)
    outlier_rows, outlier_classification = build_outlier_diag(read_csv(OUT_DIR / "V21_006_OUTLIER_CONCENTRATION_AUDIT.csv"))
    regime_rows, regime_classification = build_regime_diag(
        read_csv(OUT_DIR / "V21_006_SUBSAMPLE_ROBUSTNESS_STATS.csv"),
        read_csv(OUT_DIR / "V21_005_REGIME_CONDITIONED_PERFORMANCE_STATS.csv"),
    )
    family_rows = build_family_diag(
        read_csv(OUT_DIR / "V21_006_FACTOR_FAMILY_IC_SIGNIFICANCE_STATS.csv"),
        read_csv(OUT_DIR / "V21_005_FACTOR_ABLATION_FORWARD_RETURN_STATS.csv"),
        regime_classification,
    )
    rank_rows = build_rank_diag(
        read_csv(OUT_DIR / "V21_006_RANK_MONOTONICITY_TEST.csv"),
        read_csv(OUT_DIR / "V21_006_DECISION_GRADE_ROBUSTNESS_SCORECARD.csv"),
        read_csv(OUT_DIR / "V21_006_RANDOM_BASELINE_COMPARISON.csv"),
        read_csv(OUT_DIR / "V21_006_BENCHMARK_SIGNIFICANCE_STATS.csv"),
    )
    risk_rows, risk_classification = build_risk_diag(
        read_csv(OUT_DIR / "V21_006_RISK_OVERHEAT_ROBUSTNESS_TEST.csv"),
        read_csv(OUT_DIR / "V21_005_RISK_OVERHEAT_EFFECTIVENESS_STATS.csv"),
    )
    decision, final_status, recommended = choose_decision(outlier_classification, regime_classification, risk_classification, missing)
    roadmap_rows = build_roadmap(recommended, outlier_classification, regime_classification, risk_classification)

    if missing:
        final_status = "FAIL_V21_007_REQUIRED_V21_006_ARTIFACTS_MISSING"
    summary = {
        "stage_name": STAGE_NAME,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "research_only": "TRUE",
        "final_status": final_status,
        "v21_006_final_status": summary_006.get("final_status", ""),
        "v21_006_final_verdict": summary_006.get("final_verdict", ""),
        "weight_update_blocker_decision": decision,
        "outlier_dependency_classification": outlier_classification,
        "regime_dependency_classification": regime_classification,
        "risk_overheat_repair_classification": risk_classification,
        "recommended_next_stage": recommended,
        "data_trust_ranking_weight": "0",
        "data_trust_alpha_contribution": "0",
        "official_ranking_mutation_count": "0",
        "official_factor_weight_mutation_count": "0",
        "official_recommendation_count": "0",
        "trade_action_count": "0",
        "shadow_activation": "FALSE",
    }
    blocker_rows = [
        {
            "weight_update_blocker_decision": decision,
            "final_status": final_status,
            "decision_reason": f"outlier={outlier_classification};regime={regime_classification};risk={risk_classification}",
            "official_weight_update_allowed": "FALSE",
            "research_only_limited_weight_experiment_allowed": "FALSE",
            "recommended_next_stage": recommended,
            "research_only": "TRUE",
        }
    ]

    write_csv(VERDICT_AUDIT, verdict_rows, ["audit_item", "audit_passed", "observed_value", "required_value", "research_only"])
    write_csv(OUTLIER_DIAG, outlier_rows, ["dependency_driver", "observed_value", "driver_classification", "overall_outlier_dependency_classification", "diagnostic_note", "research_only"])
    write_csv(REGIME_DIAG, regime_rows, ["regime_label", "available_window_count", "mean_top10_forward_return", "positive_window_count", "diagnostic_status", "regime_dependency_classification", "recommended_segmentation_test", "research_only"])
    write_csv(FAMILY_DIAG, family_rows, ["factor_family", "repair_diagnosis", "evidence_summary", "data_trust_alpha_contribution", "official_weight_change_allowed", "research_only"])
    write_csv(RANK_DIAG, rank_rows, ["architecture_problem", "problem_flagged", "evidence_summary", "ranking_architecture_stability", "official_weight_update_allowed", "research_only"])
    write_csv(RISK_DIAG, risk_rows, ["forward_return_window", "v21_006_risk_overheat_classification", "false_block_candidate_rate", "blocked_observation_count", "repair_diagnosis", "overall_risk_overheat_repair_classification", "official_gate_loosening_allowed", "research_only"])
    write_csv(BLOCKER, blocker_rows, ["weight_update_blocker_decision", "final_status", "decision_reason", "official_weight_update_allowed", "research_only_limited_weight_experiment_allowed", "recommended_next_stage", "research_only"])
    write_csv(ROADMAP, roadmap_rows, ["roadmap_order", "candidate_next_stage", "selected_recommended_next_stage", "priority_reason", "research_only"])
    write_csv(SUMMARY, [summary], list(summary.keys()))
    write_report(summary, outlier_classification, regime_classification, risk_classification, recommended)

    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_status={final_status}")
    print(f"weight_update_blocker_decision={decision}")
    print(f"recommended_next_stage={recommended}")
    print("data_trust_ranking_weight=0")
    print("data_trust_alpha_contribution=0")
    print("official_ranking_mutation_count=0")
    print("official_factor_weight_mutation_count=0")
    print("official_recommendation_count=0")
    print("trade_action_count=0")
    print("shadow_activation=FALSE")
    print("research_only=TRUE")


if __name__ == "__main__":
    main()
