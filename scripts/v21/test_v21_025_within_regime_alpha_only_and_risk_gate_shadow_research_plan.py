#!/usr/bin/env python
"""Tests for V21.025 shadow research plan."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_025_within_regime_alpha_only_and_risk_gate_shadow_research_plan.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_025_within_regime_alpha_only_and_risk_gate_shadow_research_plan.ps1"
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_025_WITHIN_REGIME_ALPHA_ONLY_AND_RISK_GATE_SHADOW_RESEARCH_PLAN_REPORT.md"

REQUIRED_OUTPUTS = [
    OUT_DIR / "V21_025_V21_027_DECISION_INGEST_AUDIT.csv",
    OUT_DIR / "V21_025_RESEARCH_CONTEXT_CANDIDATE_SELECTION.csv",
    OUT_DIR / "V21_025_SHADOW_RESEARCH_PLAN_DESIGN.csv",
    OUT_DIR / "V21_025_PLAN_GUARDRAILS.csv",
    OUT_DIR / "V21_025_SHADOW_OBSERVATION_LEDGER_SPEC.csv",
    OUT_DIR / "V21_025_SELECTION_POLICY_PROTOTYPE.csv",
    OUT_DIR / "V21_025_RISK_GATE_POLICY_PROTOTYPE.csv",
    OUT_DIR / "V21_025_REQUIRED_MONITORING_METRICS.csv",
    OUT_DIR / "V21_025_PROMOTION_BLOCKER_AND_EXIT_CRITERIA.csv",
    OUT_DIR / "V21_025_DRY_RUN_ARTIFACT_PLAN.csv",
    OUT_DIR / "V21_025_SHADOW_RESEARCH_PLAN_DECISION.csv",
    OUT_DIR / "V21_025_WITHIN_REGIME_ALPHA_ONLY_AND_RISK_GATE_SHADOW_RESEARCH_PLAN_SUMMARY.csv",
    REPORT,
]

INPUTS = [
    OUT_DIR / "V21_027_V21_026_DECISION_INGEST_AUDIT.csv",
    OUT_DIR / "V21_027_REPAIRED_LABEL_COVERAGE_AUDIT.csv",
    OUT_DIR / "V21_027_CONTEXT_RETEST_UNIVERSE.csv",
    OUT_DIR / "V21_027_REPAIRED_CONTEXT_RANK_BUCKET_PERFORMANCE.csv",
    OUT_DIR / "V21_027_STABLE_VS_UNSTABLE_REGIME_TEST.csv",
    OUT_DIR / "V21_027_TREND_COMBINATION_CONTEXT_TEST.csv",
    OUT_DIR / "V21_027_RISK_GATE_BY_REPAIRED_CONTEXT.csv",
    OUT_DIR / "V21_027_STATISTICAL_RANDOM_BASELINE_RETEST.csv",
    OUT_DIR / "V21_027_REMAINING_SOURCE_GAP_IMPACT_AUDIT.csv",
    OUT_DIR / "V21_027_CONTEXT_RETEST_DECISION.csv",
    OUT_DIR / "V21_027_MARKET_REGIME_CONTEXT_RETEST_WITH_REPAIRED_LABELS_SUMMARY.csv",
    ROOT / "outputs" / "v21" / "read_center" / "V21_027_MARKET_REGIME_CONTEXT_RETEST_WITH_REPAIRED_LABELS_REPORT.md",
]

ALLOWED_DECISIONS = {
    "SHADOW_RESEARCH_PLAN_READY_NOT_ACTIVATED",
    "SHADOW_RESEARCH_PLAN_PARTIAL_SOURCE_GAPS_REMAIN",
    "SHADOW_RESEARCH_PLAN_BLOCKED_BY_CONTEXT_INSTABILITY",
    "SHADOW_RESEARCH_PLAN_BLOCKED_BY_RISK_GATE_FALSE_BLOCK",
    "SHADOW_RESEARCH_PLAN_INCONCLUSIVE_REQUIRED_FIELDS_MISSING",
}
ALLOWED_NEXT = {
    "V21.029_WITHIN_REGIME_SHADOW_OBSERVATION_LEDGER_PRODUCER",
    "V21.028_MARKET_REGIME_DATA_PRODUCER_IMPLEMENTATION",
    "V21.017_OVERHEAT_ENTRY_TIMING_AND_FALSE_BLOCK_REPAIR",
    "V21.015_NONLINEAR_FACTOR_INTERACTION_RESEARCH_PROTOTYPE",
    "V21.019_MORE_MATURED_OBSERVATION_ACCUMULATION_PLAN",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def snapshot(paths: list[Path]) -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in paths if path.exists()}


def run_stage() -> subprocess.CompletedProcess[str]:
    before = snapshot(INPUTS)
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = snapshot(INPUTS)
    changed = [path for path, mtime in before.items() if after.get(path) != mtime]
    assert not changed, f"input files modified: {changed}"
    return result


def test_v21_025_contract() -> None:
    result = run_stage()
    assert "STAGE_NAME=V21_025_WITHIN_REGIME_ALPHA_ONLY_AND_RISK_GATE_SHADOW_RESEARCH_PLAN" in result.stdout
    for path in REQUIRED_OUTPUTS:
        assert path.exists(), f"missing output {path}"
        assert path.stat().st_size > 0, f"empty output {path}"
    summary = read_csv(OUT_DIR / "V21_025_WITHIN_REGIME_ALPHA_ONLY_AND_RISK_GATE_SHADOW_RESEARCH_PLAN_SUMMARY.csv")[0]
    assert summary["research_only"] == "TRUE"
    assert summary["v21_027_context_retest_decision"] == "REPAIRED_LABEL_CONTEXT_SIGNAL_CONFIRMED_RESEARCH_ONLY"
    assert summary["v21_027_recommended_next_stage"] == "V21.025_WITHIN_REGIME_ALPHA_ONLY_AND_RISK_GATE_SHADOW_RESEARCH_PLAN"
    for key in ["official_use_allowed", "official_ranking_readiness_allowed", "official_weight_update_readiness_allowed", "broker_execution_supported", "shadow_activation"]:
        assert summary[key] == "FALSE"
    assert summary["official_weight_update_blocked"] == "TRUE"
    for key in ["data_trust_ranking_weight", "data_trust_alpha_contribution", "risk_additive_alpha_contribution", "market_regime_additive_alpha_contribution", "official_ranking_mutation_count", "official_factor_weight_mutation_count", "official_recommendation_count", "trade_action_count"]:
        assert summary[key] == "0"
    assert summary["shadow_research_plan_decision"] in ALLOWED_DECISIONS
    assert summary["recommended_next_stage"] in ALLOWED_NEXT
    assert summary["prototype_output_scope"] == "V21_025_RESEARCH_ONLY"
    for term in ["PRODUCTION", "REAL_BOOK", "OFFICIAL_ACTIVATION", "OFFICIAL_RANKING_READINESS", "OFFICIAL_WEIGHT_UPDATE_READINESS"]:
        assert term not in summary["final_status"]
        assert term not in summary["shadow_research_plan_decision"]

    ingest = read_csv(OUT_DIR / "V21_025_V21_027_DECISION_INGEST_AUDIT.csv")
    assert any(row["audit_item"] == "v21_027_decision_ingested" and row["audit_passed"] == "TRUE" for row in ingest)
    assert any(row["audit_item"] == "recommended_next_stage_v21_025" and row["audit_passed"] == "TRUE" for row in ingest)

    guards = read_csv(OUT_DIR / "V21_025_PLAN_GUARDRAILS.csv")
    assert any(row["guardrail"] == "no_official_ranking_mutation" for row in guards)
    assert any(row["guardrail"] == "no_shadow_activation" for row in guards)
    assert all(row["official_use_allowed"] == "FALSE" for row in guards)
    assert all(row["shadow_activation"] == "FALSE" for row in guards)

    ledger_fields = {row["field_name"] for row in read_csv(OUT_DIR / "V21_025_SHADOW_OBSERVATION_LEDGER_SPEC.csv")}
    for field in ["observation_id", "context_label", "lane_id", "within_regime_alpha_only_rank", "risk_gate_action", "trade_action_created"]:
        assert field in ledger_fields

    selection = read_csv(OUT_DIR / "V21_025_SELECTION_POLICY_PROTOTYPE.csv")
    assert all(row["creates_recommendation"] == "FALSE" for row in selection)
    assert all(row["creates_trade_action"] == "FALSE" for row in selection)
    assert all(row["observation_only"] == "TRUE" for row in selection)

    risk_policy = read_csv(OUT_DIR / "V21_025_RISK_GATE_POLICY_PROTOTYPE.csv")
    assert all(row["global_hard_gate_allowed"] == "FALSE" for row in risk_policy)

    blockers = read_csv(OUT_DIR / "V21_025_PROMOTION_BLOCKER_AND_EXIT_CRITERIA.csv")
    assert any(row["criteria"] == "VIX labels missing" for row in blockers)
    assert any(row["criteria"] == "macro/event labels missing" for row in blockers)

    decision = read_csv(OUT_DIR / "V21_025_SHADOW_RESEARCH_PLAN_DECISION.csv")
    selected = [row for row in decision if row["selected_recommended_next_stage"] == "TRUE"]
    assert len(decision) == 1
    assert len(selected) == 1
    assert selected[0]["shadow_research_plan_decision"] in ALLOWED_DECISIONS
    assert selected[0]["recommended_next_stage"] in ALLOWED_NEXT
    assert selected[0]["shadow_activation"] == "FALSE"

    for output in REQUIRED_OUTPUTS:
        if output.suffix == ".csv":
            assert output.name.startswith("V21_025_")
    report_text = REPORT.read_text(encoding="utf-8").lower()
    for expected in ["research-only", "final shadow research plan decision", "plan guardrails", "no broker execution", "no shadow activation", "what this stage still blocks", "recommended next stage"]:
        assert expected in report_text


def test_wrapper_parseable() -> None:
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)], cwd=ROOT, text=True, capture_output=True, check=True)
    for expected in [
        "STAGE_NAME=V21_025_WITHIN_REGIME_ALPHA_ONLY_AND_RISK_GATE_SHADOW_RESEARCH_PLAN",
        "official_use_allowed=FALSE",
        "official_ranking_readiness_allowed=FALSE",
        "official_weight_update_readiness_allowed=FALSE",
        "official_weight_update_blocked=TRUE",
        "broker_execution_supported=FALSE",
        "data_trust_ranking_weight=0",
        "data_trust_alpha_contribution=0",
        "risk_additive_alpha_contribution=0",
        "market_regime_additive_alpha_contribution=0",
        "official_ranking_mutation_count=0",
        "official_factor_weight_mutation_count=0",
        "official_recommendation_count=0",
        "trade_action_count=0",
        "shadow_activation=FALSE",
        "research_only=TRUE",
    ]:
        assert expected in result.stdout


if __name__ == "__main__":
    test_v21_025_contract()
    test_wrapper_parseable()
    print("V21.025 shadow research plan tests passed")
