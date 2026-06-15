#!/usr/bin/env python
"""Tests for V20.200 operator daily report v2."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_200_operator_daily_report_v2_with_walk_forward_and_shadow_policy_status.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_200_operator_daily_report_v2_with_walk_forward_and_shadow_policy_status.ps1"
OUT_DIR = ROOT / "outputs" / "v20" / "reports"
OUTPUTS = [
    OUT_DIR / "V20_200_INPUT_AUDIT.csv",
    OUT_DIR / "V20_200_DAILY_RESEARCH_STATUS_SUMMARY.csv",
    OUT_DIR / "V20_200_WALK_FORWARD_STATUS_SUMMARY.csv",
    OUT_DIR / "V20_200_BASE_VS_SHADOW_STATUS_SUMMARY.csv",
    OUT_DIR / "V20_200_SHADOW_POLICY_STATUS_SUMMARY.csv",
    OUT_DIR / "V20_200_OBSERVATION_MATURITY_STATUS.csv",
    OUT_DIR / "V20_200_OFFICIAL_ACTIVATION_BLOCKER_SUMMARY.csv",
    OUT_DIR / "V20_200_RESEARCH_ONLY_SAFETY_GUARD.csv",
    OUT_DIR / "V20_200_OPERATOR_DAILY_REPORT_V2.md",
    OUT_DIR / "V20_200_NEXT_STAGE_GATE.csv",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_common(row: dict[str, str]) -> None:
    assert row["research_only"] == "TRUE"
    assert row["official_ranking_mutated"] == "FALSE"
    assert row["official_ranking_score_mutation_count"] == "0"
    assert row["official_rank_mutation_count"] == "0"
    assert row["official_recommendation_created"] == "FALSE"
    assert row["trade_action_created"] == "FALSE"
    assert row["broker_execution_supported"] == "FALSE"
    assert row["real_book_action_created"] == "FALSE"
    assert row["shadow_policy_activation_status"] == "NOT_ACTIVATED"


def assert_walk_forward_append_only_counts(walk: dict[str, str]) -> None:
    total = int(walk["total_snapshot_rows"])
    usable = int(walk["usable_snapshot_rows"])
    scheduled = int(walk["total_scheduled_observations"])
    pending = int(walk["pending_not_matured_count"])
    matured = int(walk["matured_observation_count"])
    assert total >= 315
    assert usable >= 297
    assert scheduled == usable * 4
    assert pending + matured == scheduled
    if matured == 0:
        assert walk["walk_forward_status"] == "PENDING_OBSERVATION_MATURITY"


def assert_shadow_maturity_append_only_counts(all_row: dict[str, str]) -> None:
    scheduled = int(all_row["shadow_observation_schedule_rows"])
    matured = int(all_row["matured_shadow_observation_count"])
    pending = int(all_row["pending_shadow_observation_count"])
    assert scheduled == 240
    assert matured >= 0
    assert pending + matured == scheduled


def test_v20_200_report() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    for expected in [
        "REPORT_CREATED=TRUE",
        "DAILY_RESEARCH_STATUS=RESEARCH_ONLY_DAILY_REPORT_READY",
        "OFFICIAL_ACTIVATION_STATUS=BLOCKED_BY_ACTIVE_GUARDRAILS",
        "TRADE_ACTION_STATUS=NO_TRADE_ACTION_CREATED",
        "RESEARCH_ONLY=TRUE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "SHADOW_POLICY_ACTIVATION_STATUS=NOT_ACTIVATED",
    ]:
        assert expected in stdout, expected
    assert any(status in stdout for status in ["PASS_REPORT_READY", "PARTIAL_PASS_REPORT_READY_WITH_MISSING_OPTIONAL_INPUTS"])
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    input_audit = read_csv(OUTPUTS[0])
    daily = read_csv(OUTPUTS[1])[0]
    walk = read_csv(OUTPUTS[2])[0]
    compare = read_csv(OUTPUTS[3])[0]
    shadow = read_csv(OUTPUTS[4])[0]
    maturity = read_csv(OUTPUTS[5])
    blockers = read_csv(OUTPUTS[6])
    safety = read_csv(OUTPUTS[7])
    gate = read_csv(OUTPUTS[9])[0]

    assert all(row["input_status"] == "PASS" for row in input_audit if row["required_input"] == "TRUE")
    assert daily["daily_research_status"] == "RESEARCH_ONLY_DAILY_REPORT_READY"
    assert daily["official_activation_status"] == "BLOCKED_BY_ACTIVE_GUARDRAILS"
    assert daily["trade_action_status"] == "NO_TRADE_ACTION_CREATED"
    assert_walk_forward_append_only_counts(walk)
    assert compare["comparison_scope"]
    assert compare["comparison_scope_value"]
    assert compare["base_top20_count"] == "20"
    assert compare["shadow_top20_count"] == "20"
    assert compare["base_top40_count"] == "40"
    assert compare["shadow_top40_count"] == "40"
    assert 0.0 <= float(compare["top20_overlap_rate"]) <= 1.0
    assert 0.0 <= float(compare["top40_overlap_rate"]) <= 1.0
    assert int(compare["cumulative_base_observation_rows"]) >= int(compare["latest_scope_base_observation_rows"])
    assert int(compare["cumulative_shadow_observation_rows"]) >= int(compare["latest_scope_shadow_observation_rows"])
    assert shadow["selected_shadow_scenario"] == "SCENARIO_A_TECH_HEAVY"
    assert shadow["dynamic_weight_status"] == "SHADOW_ONLY"
    assert shadow["official_weight_activation_allowed"] == "FALSE"
    assert shadow["allowed_topn_scope"] == "TOP20_TOP40_ONLY"
    assert {row["forward_window"] for row in maturity} == {"ALL", "5D", "10D", "20D", "60D"}
    all_row = next(row for row in maturity if row["forward_window"] == "ALL")
    assert_shadow_maturity_append_only_counts(all_row)
    assert len(blockers) >= 8
    assert all(row["blocker_status"] == "ACTIVE" for row in blockers)
    assert all(row["guard_passed"] == "TRUE" for row in safety)
    assert gate["required_inputs_exist"] == "TRUE"
    assert gate["report_created"] == "TRUE"
    assert gate["base_walk_forward_status_included"] == "TRUE"
    assert gate["shadow_status_included"] == "TRUE"
    assert gate["base_vs_shadow_comparison_included"] == "TRUE"
    assert gate["official_activation_blockers_included"] == "TRUE"
    assert gate["safety_guard_pass"] == "TRUE"
    assert gate["official_trade_mutation_detected"] == "FALSE"
    assert gate["final_status"] in {"PASS_REPORT_READY", "PARTIAL_PASS_REPORT_READY_WITH_MISSING_OPTIONAL_INPUTS"}
    if int(walk["matured_observation_count"]) == 0:
        assert gate["final_status"] == "PASS_REPORT_READY"
    assert_common(gate)

    report = OUTPUTS[8].read_text(encoding="utf-8")
    for section in [
        "## Executive Status",
        "## Base Walk-Forward Status",
        "## Shadow Policy Status",
        "## Base Vs Shadow Comparison",
        "## Shadow Observation Maturity",
        "## Official Activation Blockers",
        "## Safety Guard",
    ]:
        assert section in report
    assert "Shadow policy is not official" in report


def test_wrapper_parseable() -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert any(status in result.stdout for status in ["PASS_REPORT_READY", "PARTIAL_PASS_REPORT_READY_WITH_MISSING_OPTIONAL_INPUTS"])
    assert "REPORT_CREATED=TRUE" in result.stdout
    assert "SHADOW_POLICY_ACTIVATION_STATUS=NOT_ACTIVATED" in result.stdout


if __name__ == "__main__":
    test_v20_200_report()
    test_wrapper_parseable()
    print("PASS test_v20_200_operator_daily_report_v2_with_walk_forward_and_shadow_policy_status")
