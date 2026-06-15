#!/usr/bin/env python
"""Tests for V20.199B-R3 shadow dynamic weight candidate selection."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_199b_r3_shadow_dynamic_weight_candidate_and_guardrail_selection.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_199b_r3_shadow_dynamic_weight_candidate_and_guardrail_selection.ps1"
OUT_DIR = ROOT / "outputs" / "v20" / "backtest"
OUTPUTS = [
    OUT_DIR / "V20_199B_R3_INPUT_AUDIT.csv",
    OUT_DIR / "V20_199B_R3_SHADOW_WEIGHT_CANDIDATE_SELECTION.csv",
    OUT_DIR / "V20_199B_R3_WEIGHT_SCENARIO_DECISION_AUDIT.csv",
    OUT_DIR / "V20_199B_R3_TOPN_USAGE_GUARDRAIL.csv",
    OUT_DIR / "V20_199B_R3_BENCHMARK_ROBUSTNESS_GUARDRAIL.csv",
    OUT_DIR / "V20_199B_R3_DYNAMIC_WEIGHT_SHADOW_POLICY.csv",
    OUT_DIR / "V20_199B_R3_OFFICIAL_ACTIVATION_BLOCKER_AUDIT.csv",
    OUT_DIR / "V20_199B_R3_RESEARCH_ONLY_INTEGRATION_PLAN.csv",
    OUT_DIR / "V20_199B_R3_NO_LOOKAHEAD_AND_NO_MUTATION_GUARD.csv",
    OUT_DIR / "V20_199B_R3_READ_CENTER_REPORT.md",
    OUT_DIR / "V20_199B_R3_NEXT_STAGE_GATE.csv",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_common(row: dict[str, str]) -> None:
    assert row["research_only"] == "TRUE"
    assert row["no_lookahead_guard_pass"] == "TRUE"
    assert row["official_ranking_mutated"] == "FALSE"
    assert row["official_ranking_score_mutation_count"] == "0"
    assert row["official_rank_mutation_count"] == "0"
    assert row["official_recommendation_created"] == "FALSE"
    assert row["trade_action_created"] == "FALSE"
    assert row["broker_execution_supported"] == "FALSE"
    assert row["real_book_action_created"] == "FALSE"
    assert row["no_fabricated_scores"] == "TRUE"
    assert row["no_fabricated_returns"] == "TRUE"
    assert row["no_fabricated_benchmark_rows"] == "TRUE"
    assert row["current_snapshot_join_count"] == "0"
    assert row["current_fundamental_field_used_count"] == "0"
    assert row["future_price_used_for_factor_count"] == "0"


def test_r3_shadow_policy_selection() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    for expected in [
        "R1_GATE_PASSED=TRUE",
        "R2_GATE_PASSED=TRUE",
        "DYNAMIC_WEIGHT_STATUS=SHADOW_ONLY",
        "OFFICIAL_WEIGHT_ACTIVATION_ALLOWED=FALSE",
        "OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE",
        "TRADE_RECOMMENDATION_ALLOWED=FALSE",
        "NO_LOOKAHEAD_GUARD_PASS=TRUE",
        "RESEARCH_ONLY=TRUE",
    ]:
        assert expected in stdout, expected
    assert any(status in stdout for status in ["PASS_SHADOW_POLICY_READY", "PARTIAL_PASS_SHADOW_POLICY_MIXED_SIGNAL"])
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    input_audit = read_csv(OUTPUTS[0])
    selection = read_csv(OUTPUTS[1])
    decision = read_csv(OUTPUTS[2])
    topn = read_csv(OUTPUTS[3])
    bench = read_csv(OUTPUTS[4])
    policy = read_csv(OUTPUTS[5])[0]
    blockers = read_csv(OUTPUTS[6])
    plan = read_csv(OUTPUTS[7])
    guard = read_csv(OUTPUTS[8])
    gate = read_csv(OUTPUTS[10])[0]

    assert len([row for row in input_audit if row["required_input"] == "TRUE"]) == 14
    assert all(row["input_status"] == "PASS" for row in input_audit if row["required_input"] == "TRUE")
    assert {row["scenario"] for row in decision} == {
        "PIT_LITE_INITIAL_POLICY",
        "SCENARIO_A_TECH_HEAVY",
        "SCENARIO_B_BALANCED_PRICE",
        "SCENARIO_C_RISK_CONTROL",
    }
    assert len(selection) == 4
    assert sum(1 for row in selection if row["selected_shadow_candidate"] == "TRUE") <= 1
    assert {row["usage_status"] for row in topn} == {
        "NOT_READY_FOR_AUTOMATED_SELECTION",
        "MANUAL_REVIEW_ONLY",
        "SHADOW_CANDIDATE_POOL",
        "RESEARCH_UNIVERSE_POOL",
    }
    assert len(bench) == 4
    assert all(row["guardrail_action"] == "SHADOW_ONLY_NO_OFFICIAL_ACTIVATION" for row in bench)
    assert policy["dynamic_weight_status"] == "SHADOW_ONLY"
    assert policy["official_weight_activation_allowed"] == "FALSE"
    assert policy["allowed_usage"] == "RESEARCH_ONLY_SHADOW_COMPARISON"
    assert policy["allowed_topn_scope"] == "TOP20_TOP40_ONLY"
    assert policy["disallowed_topn_scope"] == "TOP5_AUTOMATION"
    assert policy["minimum_future_validation_required"] == "TRUE"
    assert len(blockers) >= 7
    assert all(row["blocks_official_activation"] == "TRUE" for row in blockers)
    assert len(plan) >= 5
    assert all(row["guard_passed"] == "TRUE" for row in guard)
    assert gate["r1_gate_passed"] == "TRUE"
    assert gate["r2_gate_passed"] == "TRUE"
    assert gate["topn_guardrails_created"] == "TRUE"
    assert gate["benchmark_guardrails_created"] == "TRUE"
    assert gate["official_activation_blockers_recorded"] == "TRUE"
    assert gate["official_weight_activation_allowed"] == "FALSE"
    assert gate["final_status"] in {"PASS_SHADOW_POLICY_READY", "PARTIAL_PASS_SHADOW_POLICY_MIXED_SIGNAL"}
    assert_common(gate)

    report = OUTPUTS[9].read_text(encoding="utf-8")
    assert "SHADOW_ONLY" in report
    assert "official_weight_activation_allowed: FALSE" in report
    assert "Official Activation Blockers" in report


def test_wrapper_parseable() -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert any(status in result.stdout for status in ["PASS_SHADOW_POLICY_READY", "PARTIAL_PASS_SHADOW_POLICY_MIXED_SIGNAL"])
    assert "DYNAMIC_WEIGHT_STATUS=SHADOW_ONLY" in result.stdout
    assert "OFFICIAL_WEIGHT_ACTIVATION_ALLOWED=FALSE" in result.stdout


if __name__ == "__main__":
    test_r3_shadow_policy_selection()
    test_wrapper_parseable()
    print("PASS test_v20_199b_r3_shadow_dynamic_weight_candidate_and_guardrail_selection")
