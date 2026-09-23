#!/usr/bin/env python
"""Tests for V20.108-R9 risk candidate score coverage expander."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_108_r9_risk_candidate_score_coverage_expander.py"
OUT_SOURCE = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R9_RISK_CANDIDATE_SCORE_SOURCE.csv"
OUT_AUDIT = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R9_RISK_SOURCE_COLUMN_AUDIT.csv"
OUT_COMPONENT = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R9_RISK_SCORE_COMPONENT_AUDIT.csv"
OUT_VALIDATION = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R9_RISK_MATERIALIZATION_VALIDATION.csv"
OUT_COVERAGE = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R9_FACTOR_FAMILY_COVERAGE_AFTER_RISK.csv"
OUT_GATE = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R9_NEXT_STAGE_GATE.csv"
OUT_REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_108_R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER_REPORT.md"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    assert rows, f"{field} check has no rows"
    bad = [row for row in rows if row.get(field) not in {"FALSE", ""}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def assert_safety(rows: list[dict[str, str]]) -> None:
    for field in [
        "official_promotion_allowed",
        "official_recommendation_created",
        "is_official_weight",
        "weight_mutated",
        "trade_action_created",
        "broker_execution_supported",
    ]:
        if field in rows[0]:
            assert_false(rows, field)


def test_risk_expander() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert any(
        status in stdout
        for status in [
            "PASS_V20_108_R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER",
            "PARTIAL_PASS_V20_108_R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER_WITH_PARTIAL_COVERAGE",
            "BLOCKED_V20_108_R9_NO_SAFE_RISK_CANDIDATE_SOURCE_FOUND",
        ]
    )
    for expected in [
        "CANDIDATE_COUNT=315",
        "SOURCE_RANK_OR_SCORE_USED=FALSE",
        "BASELINE_RANK_USED=FALSE",
        "FABRICATED_VALUES_CREATED=FALSE",
        "PROXY_VALUES_ACTIVATED=FALSE",
        "ENTRY_EXIT_PRICES_CREATED=FALSE",
        "BUY_SELL_RECOMMENDATIONS_CREATED=FALSE",
        "SHADOW_RERANK_OUTPUT_CREATED=FALSE",
        "OFFICIAL_RANKING_CREATED=FALSE",
        "AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE",
        "WEIGHT_MUTATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
    ]:
        assert expected in stdout

    for path in [OUT_SOURCE, OUT_AUDIT, OUT_COMPONENT, OUT_VALIDATION, OUT_COVERAGE, OUT_GATE, OUT_REPORT]:
        assert path.exists(), f"missing output {path}"

    source_rows = read_csv(OUT_SOURCE)
    audit_rows = read_csv(OUT_AUDIT)
    component_rows = read_csv(OUT_COMPONENT)
    validation_rows = read_csv(OUT_VALIDATION)
    coverage_rows = read_csv(OUT_COVERAGE)
    gate_rows = read_csv(OUT_GATE)

    assert len(source_rows) == 315
    assert len(component_rows) == 315 * 11
    assert all(row.get("risk_contribution") for row in source_rows)
    assert all(row.get("risk_raw_columns_used") for row in source_rows if row.get("risk_contribution"))
    assert all("source_rank_or_score" not in row.get("risk_raw_columns_used", "") for row in source_rows)
    assert all("baseline_rank" not in row.get("risk_raw_columns_used", "") for row in source_rows)
    assert all("technical_timing_score" not in row.get("risk_raw_columns_used", "") for row in source_rows)
    assert any("technical_timing_score" in row.get("rejected_columns", "") for row in audit_rows)
    assert any("overheat_status" in row.get("accepted_columns", "") for row in audit_rows)

    validation = validation_rows[0]
    assert validation["candidate_count"] == "315"
    assert int(validation["materialized_risk_candidate_count"]) == 315
    assert int(validation["carried_forward_existing_risk_candidate_count"]) == 11
    assert int(validation["newly_materialized_risk_candidate_count"]) == 304
    assert validation["source_rank_or_score_used"] == "FALSE"
    assert validation["baseline_rank_used"] == "FALSE"
    assert validation["entry_exit_prices_created"] == "FALSE"
    assert validation["buy_sell_recommendations_created"] == "FALSE"
    assert validation["shadow_rerank_output_created"] == "FALSE"
    assert validation["official_ranking_created"] == "FALSE"
    assert validation["authoritative_ranking_overwritten"] == "FALSE"

    risk_coverage = [row for row in coverage_rows if row["factor_family"] == "RISK"][0]
    assert risk_coverage["materialized_candidate_count"] == "315"
    assert risk_coverage["contribution_coverage_status"] == "COMPLETE"

    gate = gate_rows[0]
    assert gate["risk_materialized"] == "TRUE"
    assert gate["next_stage_allowed"] == "FALSE"
    assert gate["usable_for_shadow_rerank_count"] == "0"
    assert int(gate["complete_six_family_contribution_candidate_count"]) < 315

    for rows in [source_rows, component_rows, validation_rows, coverage_rows, gate_rows]:
        if "fabricated_values_created" in rows[0]:
            assert_false(rows, "fabricated_values_created")
        if "proxy_values_activated" in rows[0]:
            assert_false(rows, "proxy_values_activated")
        assert_safety(rows)

    assert all(row["source_rank_or_score_used_as_risk"] == "FALSE" for row in audit_rows)
    assert all(row["baseline_rank_used_as_risk"] == "FALSE" for row in audit_rows)


if __name__ == "__main__":
    test_risk_expander()
    print("PASS_V20_108_R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER_TESTS")
