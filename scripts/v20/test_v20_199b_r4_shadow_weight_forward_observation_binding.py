#!/usr/bin/env python
"""Tests for V20.199B-R4 shadow forward observation binding."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_199b_r4_shadow_weight_forward_observation_binding.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_199b_r4_shadow_weight_forward_observation_binding.ps1"
OUT_DIR = ROOT / "outputs" / "v20" / "backtest"
OUTPUTS = [
    OUT_DIR / "V20_199B_R4_INPUT_AUDIT.csv",
    OUT_DIR / "V20_199B_R4_SHADOW_POLICY_BINDING_AUDIT.csv",
    OUT_DIR / "V20_199B_R4_SHADOW_RESCORING_POLICY.csv",
    OUT_DIR / "V20_199B_R4_CURRENT_SNAPSHOT_SHADOW_SCORE_AUDIT.csv",
    OUT_DIR / "V20_199B_R4_SHADOW_TOPN_SELECTIONS.csv",
    OUT_DIR / "V20_199B_R4_SHADOW_FORWARD_OBSERVATION_SCHEDULE.csv",
    OUT_DIR / "V20_199B_R4_BASE_VS_SHADOW_OBSERVATION_BINDING.csv",
    OUT_DIR / "V20_199B_R4_TOPN_USAGE_ENFORCEMENT_AUDIT.csv",
    OUT_DIR / "V20_199B_R4_OFFICIAL_ACTIVATION_BLOCKER_AUDIT.csv",
    OUT_DIR / "V20_199B_R4_NO_LOOKAHEAD_AND_NO_MUTATION_GUARD.csv",
    OUT_DIR / "V20_199B_R4_READ_CENTER_REPORT.md",
    OUT_DIR / "V20_199B_R4_NEXT_STAGE_GATE.csv",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_common(row: dict[str, str]) -> None:
    assert row["research_only"] == "TRUE"
    assert row["dynamic_weight_status"] == "SHADOW_ONLY"
    assert row["official_weight_activation_allowed"] == "FALSE"
    assert row["official_ranking_mutation_allowed"] == "FALSE"
    assert row["trade_recommendation_allowed"] == "FALSE"
    assert row["broker_execution_supported"] == "FALSE"
    assert row["real_book_action_created"] == "FALSE"
    assert row["official_ranking_mutated"] == "FALSE"
    assert row["official_ranking_score_mutation_count"] == "0"
    assert row["official_rank_mutation_count"] == "0"
    assert row["no_fabricated_scores"] == "TRUE"
    assert row["no_fabricated_returns"] == "TRUE"
    assert row["no_fabricated_benchmark_rows"] == "TRUE"
    assert row["current_snapshot_join_allowed_for_current_asof_only"] == "TRUE"
    assert row["historical_current_snapshot_join_count"] == "0"
    assert row["future_price_used_for_factor_count"] == "0"
    assert row["no_lookahead_guard_pass"] == "TRUE"


def test_r4_shadow_forward_binding() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    for expected in [
        "R3_GATE_PASSED=TRUE",
        "SELECTED_SHADOW_SCENARIO=SCENARIO_A_TECH_HEAVY",
        "DYNAMIC_WEIGHT_STATUS=SHADOW_ONLY",
        "OFFICIAL_WEIGHT_ACTIVATION_ALLOWED=FALSE",
        "OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE",
        "TRADE_RECOMMENDATION_ALLOWED=FALSE",
        "SHADOW_SCORE_AUDIT_CREATED=TRUE",
        "SHADOW_FORWARD_OBSERVATION_SCHEDULE_CREATED=TRUE",
        "NO_LOOKAHEAD_GUARD_PASS=TRUE",
    ]:
        assert expected in stdout, expected
    assert any(status in stdout for status in ["PASS_SHADOW_FORWARD_BINDING_READY", "PARTIAL_PASS_PENDING_OBSERVATIONS_ONLY"])
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    input_audit = read_csv(OUTPUTS[0])
    binding = read_csv(OUTPUTS[1])[0]
    policy = read_csv(OUTPUTS[2])
    scores = read_csv(OUTPUTS[3])
    topn = read_csv(OUTPUTS[4])
    schedule = read_csv(OUTPUTS[5])
    compare = read_csv(OUTPUTS[6])[0]
    enforcement = read_csv(OUTPUTS[7])
    blockers = read_csv(OUTPUTS[8])
    guard = read_csv(OUTPUTS[9])
    gate = read_csv(OUTPUTS[11])[0]

    assert all(row["input_status"] == "PASS" for row in input_audit if row["required_input"] == "TRUE")
    weights = {row["factor_family"]: row["scoring_weight"] for row in policy}
    assert weights["FUNDAMENTAL"] == "0.0000000000"
    assert weights["TECHNICAL"] == "0.5000000000"
    assert weights["STRATEGY"] == "0.2500000000"
    assert weights["RISK"] == "0.1500000000"
    assert weights["MARKET_REGIME"] == "0.1000000000"
    assert weights["DATA_TRUST"] == "0.0000000000"
    assert len(scores) > 0
    assert all(row["shadow_score"] for row in scores if row["score_status"] == "PASS")
    assert all(row["shadow_rank"] for row in scores if row["score_status"] == "PASS")
    assert sum(1 for row in topn if row["topn_group"] == "TOP20") == 20
    assert sum(1 for row in topn if row["topn_group"] == "TOP40") == 40
    assert {row["usage_status"] for row in topn} == {"SHADOW_CANDIDATE_POOL", "RESEARCH_UNIVERSE_POOL"}
    assert len(schedule) == 240
    assert {row["forward_window"] for row in schedule} == {"5D", "10D", "20D", "60D"}
    assert all(row["benchmark_scope"] == "QQQ|SPY|SOXX" for row in schedule)
    assert all(row["observation_status"] in {"PENDING_NOT_MATURED", "MATURED_OBSERVED", "MATURED_MISSING_PRICE"} or row["observation_status"] for row in schedule)
    assert compare["comparison_scope"]
    assert compare["comparison_scope_value"]
    assert int(compare["base_top20_count"]) == 20
    assert int(compare["shadow_top20_count"]) == 20
    assert int(compare["base_top40_count"]) == 40
    assert int(compare["shadow_top40_count"]) == 40
    assert 0.0 <= float(compare["top20_overlap_rate"]) <= 1.0
    assert 0.0 <= float(compare["top40_overlap_rate"]) <= 1.0
    assert int(compare["cumulative_base_observation_rows"]) >= int(compare["latest_scope_base_observation_rows"])
    assert int(compare["cumulative_shadow_observation_rows"]) >= int(compare["latest_scope_shadow_observation_rows"])
    expected_topn = {
        "5": "NOT_READY_FOR_AUTOMATED_SELECTION",
        "10": "MANUAL_REVIEW_ONLY",
        "20": "SHADOW_CANDIDATE_POOL",
        "40": "RESEARCH_UNIVERSE_POOL",
    }
    assert {row["top_n"]: row["required_usage_status"] for row in enforcement} == expected_topn
    assert all(row["enforcement_status"] == "PASS" for row in enforcement)
    assert all(row["r4_blocker_status"] == "RECONFIRMED_ACTIVE" for row in blockers)
    assert all(row["guard_passed"] == "TRUE" for row in guard)
    assert binding["binding_status"] == "BOUND_FOR_SHADOW_FORWARD_OBSERVATION"
    assert gate["r3_gate_passed"] == "TRUE"
    assert gate["v20_194_current_snapshot_exists"] == "TRUE"
    assert gate["shadow_score_audit_created"] == "TRUE"
    assert gate["shadow_top20_top40_selections_created"] == "TRUE"
    assert gate["shadow_forward_observation_schedule_created"] == "TRUE"
    assert gate["base_vs_shadow_binding_audit_created"] == "TRUE"
    assert gate["all_official_activation_blockers_active"] == "TRUE"
    assert gate["official_weight_activation_allowed"] == "FALSE"
    assert gate["final_status"] in {"PASS_SHADOW_FORWARD_BINDING_READY", "PARTIAL_PASS_PENDING_OBSERVATIONS_ONLY"}
    assert_common(gate)

    report = OUTPUTS[10].read_text(encoding="utf-8")
    assert "SHADOW_ONLY" in report
    assert "Shadow scores and shadow ranks are written only to V20_199B_R4 outputs" in report


def test_wrapper_parseable() -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert any(status in result.stdout for status in ["PASS_SHADOW_FORWARD_BINDING_READY", "PARTIAL_PASS_PENDING_OBSERVATIONS_ONLY"])
    assert "DYNAMIC_WEIGHT_STATUS=SHADOW_ONLY" in result.stdout
    assert "OFFICIAL_WEIGHT_ACTIVATION_ALLOWED=FALSE" in result.stdout


if __name__ == "__main__":
    test_r4_shadow_forward_binding()
    test_wrapper_parseable()
    print("PASS test_v20_199b_r4_shadow_weight_forward_observation_binding")
