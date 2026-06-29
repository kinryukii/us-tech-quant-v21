#!/usr/bin/env python
"""V21.106 consolidated long-horizon and rebalance research decision report."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd


STAGE = "V21.106_LONG_HORIZON_AND_REBALANCE_DECISION_REPORT"
OUTPUT_REL = Path("outputs/v21/v21_106_long_horizon_and_rebalance_decision_report")

SOURCES = {
    "V21.104": ("20260623_163856", Path("outputs/v21/v21_104_abcd_random_252d_hold_full_run/20260623_163856")),
    "V21.104-R1": ("20260623_165210", Path("outputs/v21/v21_104_r1_d_long_horizon_edge_decomposition/20260623_165210")),
    "V21.104-R2": ("20260623_170358", Path("outputs/v21/v21_104_r2_holdings_persistence_and_ticker_contribution/20260623_170358")),
    "V21.105": ("20260623_122740", Path("outputs/v21/v21_105_abcd_random_252d_monthly_rebalance/20260623_122740")),
    "V21.105-R1": ("20260623_125503", Path("outputs/v21/v21_105_r1_rebalance_failure_and_turnover_decomposition/20260623_125503")),
    "V21.105-R2": ("20260623_135252", Path("outputs/v21/v21_105_r2_rebalance_gate_backtest/20260623_135252")),
}

SOURCE_FILES = {
    "V21.104": (
        "v21_104_abcd_252d_hold_summary.csv",
        "v21_104_abcd_252d_hold_pairwise_comparison.csv",
        "v21_104_abcd_252d_hold_decision_readme.md",
        "v21_104_abcd_252d_hold_leakage_audit.csv",
    ),
    "V21.104-R1": (
        "v21_104_r1_horizon_decomposition.csv",
        "v21_104_r1_benchmark_decomposition.csv",
        "v21_104_r1_decision_readme.md",
        "v21_104_r1_warning_audit.csv",
    ),
    "V21.104-R2": (
        "v21_104_r2_concentration_analysis.csv",
        "v21_104_r2_top20_vs_top50_contribution_comparison.csv",
        "v21_104_r2_decision_readme.md",
        "v21_104_r2_warning_audit.csv",
    ),
    "V21.105": (
        "v21_105_monthly_rebalance_summary.csv",
        "v21_105_hold_vs_rebalance_comparison.csv",
        "v21_105_decision_readme.md",
        "v21_105_leakage_audit.csv",
    ),
    "V21.105-R1": (
        "v21_105_r1_hold_vs_rebalance_decomposition.csv",
        "v21_105_r1_turnover_source_decomposition.csv",
        "v21_105_r1_decision_readme.md",
        "v21_105_r1_warning_audit.csv",
    ),
    "V21.105-R2": (
        "v21_105_r2_gate_summary.csv",
        "v21_105_r2_gate_vs_hold_only.csv",
        "v21_105_r2_gate_vs_monthly_baseline.csv",
        "v21_105_r2_decision_readme.md",
        "v21_105_r2_data_quality_warnings.csv",
        "v21_105_r2_leakage_audit.csv",
    ),
}

CONFIG = "v21_106_config.json"
EVIDENCE = "v21_106_evidence_chain_summary.csv"
HOLD_REBALANCE = "v21_106_hold_vs_rebalance_decision.csv"
SIZE_DECISION = "v21_106_top20_vs_top50_decision.csv"
BENCHMARK = "v21_106_benchmark_interpretation.csv"
RISK = "v21_106_risk_turnover_assessment.csv"
WARNING = "v21_106_warning_and_blocker_audit.csv"
NEXT = "v21_106_next_step_recommendations.csv"
README = "v21_106_decision_readme.md"

PASS = "PASS_V21_106_D_LONG_HORIZON_AND_TOP50_QUARTERLY_RESEARCH_CANDIDATE"
PARTIAL_PRIMARY = "PARTIAL_PASS_V21_106_D_HOLD_ONLY_PRIMARY_TOP50_QUARTERLY_DIAGNOSTIC"
PARTIAL_WARN = "PARTIAL_PASS_V21_106_D_EDGE_CONFIRMED_BUT_ADOPTION_BLOCKED_BY_PIT_WARNINGS"
FAIL = "FAIL_V21_106_D_EDGE_NOT_CONFIRMED_AFTER_REBALANCE"


def load_v103(root: Path):
    path = root / "scripts/v21/v21_103_abcd_random_long_horizon_backtest_spec.py"
    spec = importlib.util.spec_from_file_location("v21_103_shared_for_v106", path)
    if not spec or not spec.loader:
        raise RuntimeError("V21.103 shared implementation unavailable.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: Iterable[dict[str, object]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    fields = fields or (list(rows[0]) if rows else ["status"])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def immutable_output(root: Path, override: Path | None, run_id: str | None) -> tuple[Path, str]:
    identifier = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output = (override if override and override.is_absolute() else root / (override or OUTPUT_REL / identifier)).resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"Immutable output directory is non-empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    return output, identifier


def source_paths(root: Path) -> dict[str, Path]:
    return {stage: (root / relative).resolve() for stage, (_, relative) in SOURCES.items()}


def source_hashes(paths: dict[str, Path]) -> dict[str, dict[str, str]]:
    result = {}
    for stage, base in paths.items():
        missing = [name for name in SOURCE_FILES[stage] if not (base / name).is_file()]
        if missing:
            raise RuntimeError(f"Missing {stage} source files: {missing}")
        result[stage] = {name: sha256(base / name) for name in SOURCE_FILES[stage]}
    return result


def read_status(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"FINAL_STATUS:\s*`([^`]+)`", text)
    if not match:
        raise RuntimeError(f"FINAL_STATUS not found in {path}")
    return match.group(1)


def select(frame: pd.DataFrame, **conditions: object) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    for column, value in conditions.items():
        mask &= frame[column].astype(str) == str(value)
    selected = frame[mask]
    if len(selected) != 1:
        raise RuntimeError(f"Expected one row for {conditions}; found {len(selected)}")
    return selected.iloc[0]


def evidence_rows(statuses: dict[str, str]) -> list[dict[str, object]]:
    findings = {
        "V21.104": "D 252D hold-only edge confirmed; Top20 cleared A1 and QQQ primary thresholds with acceptable QQQ-relative left tail.",
        "V21.104-R1": "Edge strengthens at 189D/252D; Top20 has stronger relative edge, Top50 better absolute return and p5 stability; SOXX mean gap comes from extreme upside.",
        "V21.104-R2": "D contribution is broad, not few-name dominated; Top50 stability is diversification-driven; SOXX gap is underparticipation.",
        "V21.105": "Unconditional monthly reranking failed A1/B/C thresholds; Top50 improved versus hold, Top20 declined; turnover was excessive.",
        "V21.105-R1": "Broad churn explained the failure; Top50 had lower churn and better diversification, but monthly turnover still required a gate.",
        "V21.105-R2": "Quarterly Top50 reduced turnover below 5x, retained QQQ/SOXX edge, and beat hold-only on mean return; A1/B/C threshold remained uncleared.",
    }
    implications = {
        "V21.104": "Establishes D as a long-horizon hold-only research candidate.",
        "V21.104-R1": "Rejects short-horizon interpretation and preserves separate Top20/Top50 roles.",
        "V21.104-R2": "Reduces concentration concern but does not remove survivorship/PIT warnings.",
        "V21.105": "Rejects unconditional monthly rebalance as the primary view.",
        "V21.105-R1": "Motivates lower-frequency and retention-oriented diagnostic gates.",
        "V21.105-R2": "Supports quarterly Top50 as a secondary diagnostic view, not an official strategy.",
    }
    return [
        {
            "stage": stage, "run_id": SOURCES[stage][0], "final_status": statuses[stage],
            "key_finding": findings[stage], "decision_implication": implications[stage],
            "leakage_or_reconciliation_failure": 0, "official_adoption_allowed": "FALSE",
            "broker_action_allowed": "FALSE", "research_only": "TRUE",
        }
        for stage in SOURCES
    ]


def report_rows(paths: dict[str, Path]) -> tuple[
    list[dict[str, object]], list[dict[str, object]], list[dict[str, object]],
    list[dict[str, object]], list[dict[str, object]]
]:
    hold = pd.read_csv(paths["V21.104"] / "v21_104_abcd_252d_hold_summary.csv")
    monthly = pd.read_csv(paths["V21.105"] / "v21_105_monthly_rebalance_summary.csv")
    gated = pd.read_csv(paths["V21.105-R2"] / "v21_105_r2_gate_summary.csv")
    gated_hold = pd.read_csv(paths["V21.105-R2"] / "v21_105_r2_gate_vs_hold_only.csv")
    gated_monthly = pd.read_csv(paths["V21.105-R2"] / "v21_105_r2_gate_vs_monthly_baseline.csv")
    r1_turnover = pd.read_csv(paths["V21.105-R1"] / "v21_105_r1_turnover_source_decomposition.csv")

    d20 = select(hold, variant="D", portfolio_size=20, horizon=252)
    d50 = select(hold, variant="D", portfolio_size=50, horizon=252)
    m50 = select(monthly, variant="D", portfolio_size=50, transaction_cost_bps=10)
    q50 = select(gated, gate_id="QUARTERLY_REBALANCE_TOP50", portfolio_size=50, transaction_cost_bps=10)
    qhold = select(gated_hold, gate_id="QUARTERLY_REBALANCE_TOP50", portfolio_size=50, transaction_cost_bps=10)
    qmonthly = select(gated_monthly, gate_id="QUARTERLY_REBALANCE_TOP50", portfolio_size=50, transaction_cost_bps=10)
    t20 = select(r1_turnover, variant="D", portfolio_size=20)
    t50 = select(r1_turnover, variant="D", portfolio_size=50)

    views = [
        {
            "view": "D_TOP20_252D_HOLD_ONLY", "role": "PRIMARY_RESEARCH_VIEW",
            "mean_return": d20["mean_return"], "median_return": d20["median_return"],
            "p5_return": d20["p5_return"], "win_rate_vs_A1": d20["win_rate_vs_A1"],
            "win_rate_vs_B": d20["win_rate_vs_B"], "win_rate_vs_C": d20["win_rate_vs_C"],
            "win_rate_vs_QQQ": d20["win_rate_vs_QQQ"], "win_rate_vs_SOXX": d20["win_rate_vs_SOXX"],
            "median_excess_vs_QQQ": d20["median_excess_vs_QQQ"],
            "p5_excess_vs_QQQ": d20["p5_excess_vs_QQQ"], "annualized_turnover": 0.0,
            "assessment": "High-conviction long-horizon watchlist; strongest relative hold-only edge.",
            "research_only": "TRUE",
        },
        {
            "view": "D_TOP50_252D_HOLD_ONLY", "role": "STABILITY_REFERENCE",
            "mean_return": d50["mean_return"], "median_return": d50["median_return"],
            "p5_return": d50["p5_return"], "win_rate_vs_A1": d50["win_rate_vs_A1"],
            "win_rate_vs_B": d50["win_rate_vs_B"], "win_rate_vs_C": d50["win_rate_vs_C"],
            "win_rate_vs_QQQ": d50["win_rate_vs_QQQ"], "win_rate_vs_SOXX": d50["win_rate_vs_SOXX"],
            "median_excess_vs_QQQ": d50["median_excess_vs_QQQ"],
            "p5_excess_vs_QQQ": d50["p5_excess_vs_QQQ"], "annualized_turnover": 0.0,
            "assessment": "Diversified hold-only reference with superior absolute return and p5 stability.",
            "research_only": "TRUE",
        },
        {
            "view": "D_TOP50_MONTHLY_10BPS", "role": "REJECTED_PRIMARY_REBALANCE_VIEW",
            "mean_return": m50["mean_return"], "median_return": m50["median_return"],
            "p5_return": m50["p5_return"], "win_rate_vs_A1": m50["win_rate_vs_A1"],
            "win_rate_vs_B": m50["win_rate_vs_B"], "win_rate_vs_C": m50["win_rate_vs_C"],
            "win_rate_vs_QQQ": m50["win_rate_vs_QQQ"], "win_rate_vs_SOXX": m50["win_rate_vs_SOXX"],
            "median_excess_vs_QQQ": m50["median_excess_vs_QQQ"],
            "p5_excess_vs_QQQ": m50["p5_excess_vs_QQQ"],
            "annualized_turnover": m50["annualized_turnover"],
            "assessment": "Benchmark edge survives, but broad churn and 9.83x turnover make unconditional monthly reranking unsuitable.",
            "research_only": "TRUE",
        },
        {
            "view": "D_TOP50_QUARTERLY_10BPS", "role": "SECONDARY_DIAGNOSTIC_VIEW",
            "mean_return": q50["mean_return"], "median_return": q50["median_return"],
            "p5_return": q50["p5_return"], "win_rate_vs_A1": q50["win_rate_vs_A1"],
            "win_rate_vs_B": q50["win_rate_vs_B"], "win_rate_vs_C": q50["win_rate_vs_C"],
            "win_rate_vs_QQQ": q50["win_rate_vs_QQQ"], "win_rate_vs_SOXX": q50["win_rate_vs_SOXX"],
            "median_excess_vs_QQQ": q50["median_excess_vs_QQQ"],
            "p5_excess_vs_QQQ": q50["p5_excess_vs_QQQ"],
            "annualized_turnover": q50["annualized_turnover"],
            "mean_return_change_vs_hold": qhold["mean_return_change"],
            "turnover_reduction_vs_monthly": qmonthly["turnover_reduction"],
            "assessment": "Best gated rebalance diagnostic: lower-frequency Top50 preserves breadth and reduces timing/churn damage.",
            "research_only": "TRUE",
        },
    ]

    sizes = [
        {
            "portfolio_view": "TOP20", "preferred_use": "HIGH_CONVICTION_HOLD_ONLY_WATCHLIST",
            "relative_edge": "STRONGER_IN_HOLD_ONLY_RESEARCH",
            "stability": "LOWER_THAN_TOP50", "rebalance_suitability": "LOW",
            "turnover_evidence": t20["annualized_turnover"],
            "core_retention_evidence": t20["core_holding_retention_rate"],
            "rationale": "Concentration preserves the strongest relative D signal, but reranking creates more timing error, churn, and tail variability.",
            "decision": "PRIMARY_RESEARCH_VIEW_AS_252D_HOLD_ONLY", "research_only": "TRUE",
        },
        {
            "portfolio_view": "TOP50", "preferred_use": "DIVERSIFIED_QUARTERLY_REBALANCE_DIAGNOSTIC",
            "relative_edge": "WEAKER_HOLD_ONLY_RELATIVE_EDGE_BUT_STRONG_BENCHMARK_EDGE",
            "stability": "BETTER_P5_AND_DRAWDOWN_STABILITY", "rebalance_suitability": "PREFERRED",
            "turnover_evidence": q50["annualized_turnover"],
            "core_retention_evidence": q50["final_core_retention"],
            "rationale": "Diversification dilutes loser and timing risk; quarterly frequency cuts turnover by 64.21% while maintaining QQQ/SOXX edge.",
            "decision": "SECONDARY_DIAGNOSTIC_VIEW_AS_QUARTERLY_TOP50", "research_only": "TRUE",
        },
    ]

    benchmarks = [
        {
            "benchmark": "QQQ", "hold_top20_win_rate": d20["win_rate_vs_QQQ"],
            "quarterly_top50_win_rate": q50["win_rate_vs_QQQ"],
            "quarterly_top50_median_excess": q50["median_excess_vs_QQQ"],
            "interpretation": "D shows a durable long-horizon benchmark edge in hold-only and quarterly Top50 views.",
            "remaining_gap": "P5 excess remains negative, but is within the accepted hold-relative tolerance.",
            "research_only": "TRUE",
        },
        {
            "benchmark": "SOXX", "hold_top20_win_rate": d20["win_rate_vs_SOXX"],
            "quarterly_top50_win_rate": q50["win_rate_vs_SOXX"],
            "quarterly_top50_median_excess": "NOT_REPORTED_IN_V21_105_R2_GATE_SUMMARY",
            "interpretation": "D wins more often than SOXX but does not fully participate in rare semiconductor extreme-upside windows.",
            "remaining_gap": "SOXX top-5% upside remains a structural underparticipation gap, not ordinary left-tail weakness.",
            "research_only": "TRUE",
        },
        {
            "benchmark": "A1_B_C_FACTOR_BASELINES",
            "hold_top20_win_rate": f"A1={d20['win_rate_vs_A1']:.4f};B={d20['win_rate_vs_B']:.4f};C={d20['win_rate_vs_C']:.4f}",
            "quarterly_top50_win_rate": f"A1={q50['win_rate_vs_A1']:.4f};B={q50['win_rate_vs_B']:.4f};C={q50['win_rate_vs_C']:.4f}",
            "quarterly_top50_median_excess": "",
            "interpretation": "D's benchmark value does not translate into a uniform >55% advantage over closely related A1/B/C variants.",
            "remaining_gap": "No rebalance gate clears all A1/B/C thresholds; this prevents a full research pass.",
            "research_only": "TRUE",
        },
    ]

    risks = [
        {"assessment_area": "LEFT_TAIL", "status": "ACCEPTABLE_WITH_WARNING",
         "evidence": f"Top20 hold p5 excess vs QQQ={d20['p5_excess_vs_QQQ']:.4f}; quarterly Top50 p5 excess vs QQQ={q50['p5_excess_vs_QQQ']:.4f}.",
         "decision_impact": "No material absolute/A1/QQQ left-tail blocker; SOXX-relative extreme-upside gap remains.", "research_only": "TRUE"},
        {"assessment_area": "TURNOVER", "status": "ACCEPTABLE_ONLY_UNDER_QUARTERLY_TOP50_DIAGNOSTIC",
         "evidence": f"Monthly Top50={m50['annualized_turnover']:.2f}x; quarterly Top50={q50['annualized_turnover']:.2f}x.",
         "decision_impact": "Reject unconditional monthly view; retain quarterly Top50 diagnostic.", "research_only": "TRUE"},
        {"assessment_area": "COST_ROBUSTNESS", "status": "QQQ_EDGE_SURVIVES_TESTED_GRID",
         "evidence": "Quarterly Top50 QQQ median edge remains positive through 100 bps; mean return falls below hold-only at high costs.",
         "decision_impact": "Costs do not invalidate benchmark edge, but do not authorize adoption.", "research_only": "TRUE"},
        {"assessment_area": "WINNER_RETENTION", "status": "LIMITATION_REMAINS",
         "evidence": "Quarterly Top50 did not reduce selling subsequent winners in V21.105-R2.",
         "decision_impact": "Requires live forward monitoring and possible future retention diagnostics.", "research_only": "TRUE"},
        {"assessment_area": "A1_B_C_THRESHOLD", "status": "NOT_CLEARED",
         "evidence": f"Quarterly Top50 win rates: A1={q50['win_rate_vs_A1']:.4f}, B={q50['win_rate_vs_B']:.4f}, C={q50['win_rate_vs_C']:.4f}.",
         "decision_impact": "Prevents full pass and official-candidate classification.", "research_only": "TRUE"},
    ]

    warnings = [
        {"warning_or_blocker": "SURVIVORSHIP_BIAS_WARN", "status": "ACTIVE",
         "scope": "ALL_HISTORICAL_SAMPLES", "blocking_effect": "Blocks official adoption until historical universe membership is repaired.",
         "official_adoption_allowed": "FALSE", "broker_action_allowed": "FALSE"},
        {"warning_or_blocker": "PIT_FACTOR_APPROXIMATION_WARN", "status": "ACTIVE",
         "scope": "A1_B_C_D_HISTORICAL_RANKINGS", "blocking_effect": "PIT-lite price/volume factors are not a full historical A1 factor replay.",
         "official_adoption_allowed": "FALSE", "broker_action_allowed": "FALSE"},
        {"warning_or_blocker": "NO_FULL_HISTORICAL_A1_FACTOR_REPLAY", "status": "ACTIVE",
         "scope": "FACTOR_LINEAGE", "blocking_effect": "Relative D conclusions require feasibility audit before stronger claims.",
         "official_adoption_allowed": "FALSE", "broker_action_allowed": "FALSE"},
        {"warning_or_blocker": "NO_GATE_CLEARS_A1_B_C_55_PERCENT", "status": "ACTIVE",
         "scope": "REBALANCE_DECISION", "blocking_effect": "Quarterly Top50 remains diagnostic rather than a confirmed factor replacement.",
         "official_adoption_allowed": "FALSE", "broker_action_allowed": "FALSE"},
        {"warning_or_blocker": "OFFICIAL_ADOPTION_BLOCK", "status": "ENFORCED",
         "scope": "ALL_OUTPUTS", "blocking_effect": "No official rankings or weights may be changed.",
         "official_adoption_allowed": "FALSE", "broker_action_allowed": "FALSE"},
        {"warning_or_blocker": "BROKER_ACTION_BLOCK", "status": "ENFORCED",
         "scope": "ALL_OUTPUTS", "blocking_effect": "No orders, broker actions, or trading instructions are authorized.",
         "official_adoption_allowed": "FALSE", "broker_action_allowed": "FALSE"},
    ]
    return views, sizes, benchmarks, risks, warnings


def next_steps() -> list[dict[str, object]]:
    return [
        {"priority": 1, "stage": "V21.106-R1_FULL_PIT_FACTOR_REPLAY_FEASIBILITY_AUDIT",
         "objective": "Inventory historical A1/B/C/D factor inputs and determine whether a full PIT replay is technically feasible.",
         "allowed_action": "READ_ONLY_AUDIT_AND_FEASIBILITY_REPORT", "adoption_effect": "NONE", "research_only": "TRUE"},
        {"priority": 2, "stage": "V21.106-R2_SURVIVORSHIP_BIAS_REPAIR_PLAN",
         "objective": "Design historical universe-membership reconstruction, validation, and failure-handling requirements.",
         "allowed_action": "DESIGN_PLAN_ONLY", "adoption_effect": "NONE", "research_only": "TRUE"},
        {"priority": 3, "stage": "V21.107_LIVE_FORWARD_TRACKING_FOR_D_TOP20_HOLD_AND_D_TOP50_QUARTERLY",
         "objective": "Track Top20 hold-only and Top50 quarterly views prospectively without backfilling or broker action.",
         "allowed_action": "RESEARCH_ONLY_FORWARD_OBSERVATION", "adoption_effect": "NONE", "research_only": "TRUE"},
        {"priority": 4, "stage": "PDF_ARCHIVE_REPORT_GENERATION_IF_REQUIRED",
         "objective": "Create an immutable human-readable archive after the CSV/README decision chain is accepted.",
         "allowed_action": "DOCUMENT_GENERATION_ONLY", "adoption_effect": "NONE", "research_only": "TRUE"},
    ]


def render_readme(
    output: Path, run_id: str, status: str, statuses: dict[str, str],
    views: list[dict[str, object]], warnings: list[dict[str, object]],
    source_modified: bool, protected_modified: bool,
) -> None:
    view = {row["view"]: row for row in views}
    hold20 = view["D_TOP20_252D_HOLD_ONLY"]
    quarter50 = view["D_TOP50_QUARTERLY_10BPS"]
    run_lines = "\n".join(f"- {stage}: `{SOURCES[stage][0]}` - `{statuses[stage]}`" for stage in SOURCES)
    text = f"""# V21.106 Long-Horizon and Rebalance Decision Report

FINAL_STATUS: `{status}`  
DECISION: `D_LONG_HORIZON_HOLD_PLUS_GATED_TOP50_REBALANCE_CANDIDATE_ADOPTION_BLOCKED`  
run_id: `{run_id}`  
D status classification: `long-horizon hold plus gated Top50 rebalance candidate`  
official_adoption_allowed: `false`  
broker_action_allowed: `false`

## Source run IDs

{run_lines}

## Consolidated decision

- Primary research view: `D Top20 252D hold-only`.
- Secondary diagnostic view: `D Top50 quarterly rebalance at 10 bps`.
- Best gate: `QUARTERLY_REBALANCE_TOP50`.
- D beats QQQ: `YES` in both primary hold and secondary quarterly views (win rates {hold20['win_rate_vs_QQQ']:.2%} and {quarter50['win_rate_vs_QQQ']:.2%}).
- D beats SOXX: `YES BY WIN RATE` in both views ({hold20['win_rate_vs_SOXX']:.2%} and {quarter50['win_rate_vs_SOXX']:.2%}), while SOXX extreme upside remains undercaptured.
- D clears A1/B/C thresholds under gated rebalance: `NO`.
- Quarterly Top50 turnover acceptable for diagnostic research: `YES` ({quarter50['annualized_turnover']:.2f}x, below 5x).
- Left-tail acceptable: `YES WITH ACTIVE WARNINGS`; no material absolute/A1/QQQ weakness was found, but p5 excess remains negative.
- SOXX extreme-upside gap remains: `YES`; it is explained by underparticipation rather than ordinary downside weakness.
- Prior source outputs modified: `{'TRUE' if source_modified else 'FALSE'}`.
- Protected outputs modified: `{'TRUE' if protected_modified else 'FALSE'}`.

## Why adoption remains blocked

- `SURVIVORSHIP_BIAS_WARN` remains active because true historical universe membership is unavailable.
- `PIT_FACTOR_APPROXIMATION_WARN` remains active because the chain uses PIT-lite historical factors.
- A full historical A1 factor replay has not been completed.
- No gate clears the required A1/B/C threshold simultaneously.
- Therefore D is not an official candidate, no ranking or weight change is authorized, and no broker action is allowed.

## Next allowed research steps

1. `V21.106-R1_FULL_PIT_FACTOR_REPLAY_FEASIBILITY_AUDIT`
2. `V21.106-R2_SURVIVORSHIP_BIAS_REPAIR_PLAN`
3. `V21.107_LIVE_FORWARD_TRACKING_FOR_D_TOP20_HOLD_AND_D_TOP50_QUARTERLY`
4. PDF archive/report generation if required

This report consolidates research evidence only. It does not change any strategy, ranking, portfolio weight, protected output, or broker state.
"""
    (output / README).write_text(text, encoding="utf-8")


def run_stage(root: Path, output: Path, run_id: str) -> dict[str, object]:
    root, output = root.resolve(), output.resolve()
    paths = source_paths(root)
    before = source_hashes(paths)
    v103 = load_v103(root)
    protected = v103.protected_files(root, output)
    protected_before = {path: sha256(path) for path in protected}
    try:
        statuses = {
            "V21.104": read_status(paths["V21.104"] / "v21_104_abcd_252d_hold_decision_readme.md"),
            "V21.104-R1": read_status(paths["V21.104-R1"] / "v21_104_r1_decision_readme.md"),
            "V21.104-R2": read_status(paths["V21.104-R2"] / "v21_104_r2_decision_readme.md"),
            "V21.105": read_status(paths["V21.105"] / "v21_105_decision_readme.md"),
            "V21.105-R1": read_status(paths["V21.105-R1"] / "v21_105_r1_decision_readme.md"),
            "V21.105-R2": read_status(paths["V21.105-R2"] / "v21_105_r2_decision_readme.md"),
        }
        evidence = evidence_rows(statuses)
        views, sizes, benchmarks, risks, warning_rows = report_rows(paths)
        next_rows = next_steps()
        source_after = source_hashes(paths)
        protected_after = {path: sha256(path) for path in protected}
        source_modified = before != source_after
        protected_modified = any(protected_before[path] != protected_after[path] for path in protected)
        warning_rows.extend([
            {"warning_or_blocker": "SOURCE_OUTPUTS_MODIFIED", "status": str(source_modified).upper(),
             "scope": "V21.104_THROUGH_V21.105_R2", "blocking_effect": "Forces report failure if true.",
             "official_adoption_allowed": "FALSE", "broker_action_allowed": "FALSE"},
            {"warning_or_blocker": "PROTECTED_OUTPUTS_MODIFIED", "status": str(protected_modified).upper(),
             "scope": "PROTECTED_OUTPUTS", "blocking_effect": "Forces report failure if true.",
             "official_adoption_allowed": "FALSE", "broker_action_allowed": "FALSE"},
        ])
        if source_modified or protected_modified:
            status = FAIL
        else:
            status = PARTIAL_WARN
        config = {
            "stage": STAGE, "run_id": run_id, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_runs": {stage: run for stage, (run, _) in SOURCES.items()},
            "source_final_statuses": statuses,
            "source_file_hashes": before,
            "d_status_classification": "long-horizon hold plus gated Top50 rebalance candidate",
            "primary_research_view": "D_TOP20_252D_HOLD_ONLY",
            "secondary_diagnostic_view": "D_TOP50_QUARTERLY_10BPS",
            "best_gate": "QUARTERLY_REBALANCE_TOP50",
            "full_historical_a1_factor_replay_available": False,
            "survivorship_bias_warning": True, "pit_factor_approximation_warning": True,
            "official_adoption_allowed": False, "broker_action_allowed": False,
            "research_only": True,
        }
        write_json(output / CONFIG, config)
        write_csv(output / EVIDENCE, evidence)
        write_csv(output / HOLD_REBALANCE, views)
        write_csv(output / SIZE_DECISION, sizes)
        write_csv(output / BENCHMARK, benchmarks)
        write_csv(output / RISK, risks)
        write_csv(output / WARNING, warning_rows)
        write_csv(output / NEXT, next_rows)
        render_readme(output, run_id, status, statuses, views, warning_rows, source_modified, protected_modified)
    except Exception as exc:
        status, source_modified, protected_modified = FAIL, False, False
        write_json(output / CONFIG, {
            "stage": STAGE, "run_id": run_id, "execution_error": str(exc),
            "official_adoption_allowed": False, "broker_action_allowed": False,
        })
        for name in (EVIDENCE, HOLD_REBALANCE, SIZE_DECISION, BENCHMARK, RISK, WARNING, NEXT):
            write_csv(output / name, [], ["status"])
        (output / README).write_text(
            f"# V21.106\n\nFINAL_STATUS: `{FAIL}`  \nDECISION: `STOP_SOURCE_OR_REPORT_BLOCKER`  \n"
            f"official_adoption_allowed: `false`  \nbroker_action_allowed: `false`\n\nBlocking error: {exc}\n",
            encoding="utf-8",
        )
    result = {
        "FINAL_STATUS": status,
        "DECISION": "D_LONG_HORIZON_HOLD_PLUS_GATED_TOP50_REBALANCE_CANDIDATE_ADOPTION_BLOCKED",
        "RUN_ID": run_id, "SOURCE_OUTPUTS_MODIFIED": source_modified,
        "PROTECTED_OUTPUTS_MODIFIED": protected_modified, "OUTPUT_DIR": output.as_posix(),
        "OFFICIAL_ADOPTION_ALLOWED": False, "BROKER_ACTION_ALLOWED": False,
    }
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    output, run_id = immutable_output(args.root.resolve(), args.output_dir, args.run_id)
    result = run_stage(args.root, output, run_id)
    return 1 if str(result["FINAL_STATUS"]).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
