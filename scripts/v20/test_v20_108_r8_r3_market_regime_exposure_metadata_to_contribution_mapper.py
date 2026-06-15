#!/usr/bin/env python
"""Tests for V20.108-R8-R3 market regime metadata mapper."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_108_r8_r3_market_regime_exposure_metadata_to_contribution_mapper.py"
OUT_SOURCE = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R8_R3_MARKET_REGIME_CONTRIBUTION_SOURCE.csv"
OUT_MAPPING = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R8_R3_EXPOSURE_TO_CONTRIBUTION_MAPPING_AUDIT.csv"
OUT_COMPONENT = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R8_R3_MARKET_REGIME_COMPONENT_AUDIT.csv"
OUT_VALIDATION = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R8_R3_MARKET_REGIME_MATERIALIZATION_VALIDATION.csv"
OUT_COVERAGE = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R8_R3_FACTOR_FAMILY_COVERAGE_AFTER_MARKET_REGIME_MAPPING.csv"
OUT_GATE = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R8_R3_NEXT_STAGE_GATE.csv"
OUT_REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_108_R8_R3_MARKET_REGIME_EXPOSURE_METADATA_TO_CONTRIBUTION_MAPPER_REPORT.md"
R8_SOURCE = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R8_MARKET_REGIME_CANDIDATE_EXPOSURE_SOURCE.csv"
R8_R2_CACHE = ROOT / "outputs" / "v20" / "consolidation" / "snapshots" / "V20_108_R8_R2_ENABLED_METADATA_CACHE.csv"


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
        assert_false(rows, field)


def test_mapper() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert any(
        status in stdout
        for status in [
            "PASS_V20_108_R8_R3_MARKET_REGIME_EXPOSURE_METADATA_TO_CONTRIBUTION_MAPPER",
            "PARTIAL_PASS_V20_108_R8_R3_MARKET_REGIME_EXPOSURE_METADATA_TO_CONTRIBUTION_MAPPER_WITH_PARTIAL_COVERAGE",
            "BLOCKED_V20_108_R8_R3_NO_SAFE_MARKET_REGIME_CONTRIBUTION_MAPPING_AVAILABLE",
        ]
    )
    for expected in [
        "CANDIDATE_COUNT=315",
        "SOURCE_RANK_OR_SCORE_USED=FALSE",
        "BASELINE_RANK_USED=FALSE",
        "FABRICATED_VALUES_CREATED=FALSE",
        "PROXY_VALUES_ACTIVATED=FALSE",
        "GLOBAL_REGIME_COPIED_WITHOUT_EXPOSURE_CONDITIONING=FALSE",
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

    for path in [OUT_SOURCE, OUT_MAPPING, OUT_COMPONENT, OUT_VALIDATION, OUT_COVERAGE, OUT_GATE, OUT_REPORT]:
        assert path.exists(), f"missing output {path}"

    source_rows = read_csv(OUT_SOURCE)
    mapping_rows = read_csv(OUT_MAPPING)
    component_rows = read_csv(OUT_COMPONENT)
    validation_rows = read_csv(OUT_VALIDATION)
    coverage_rows = read_csv(OUT_COVERAGE)
    gate_rows = read_csv(OUT_GATE)
    r8_rows = read_csv(R8_SOURCE)
    metadata_rows = read_csv(R8_R2_CACHE)

    assert len(source_rows) == 315
    assert len(mapping_rows) == 315
    assert len(component_rows) == 315 * 7
    assert {row["ticker"] for row in source_rows} == {row["ticker"] for row in metadata_rows}

    certified = {
        row["ticker"]
        for row in metadata_rows
        if row.get("exposure_metadata_certification_status") in {"EXPOSURE_METADATA_CERTIFIED", "EXPOSURE_CARRIED_FORWARD_FROM_R8"}
    }
    materialized = {row["ticker"] for row in source_rows if row.get("market_regime_contribution")}
    assert materialized <= certified

    r8_carried = {
        row["ticker"]: row["market_regime_contribution"]
        for row in r8_rows
        if row.get("market_regime_contribution")
    }
    carried_rows = [row for row in source_rows if row.get("carried_forward_from_r8") == "TRUE"]
    assert len(carried_rows) == 7
    for row in carried_rows:
        assert row["ticker"] in r8_carried
        assert row["market_regime_contribution"] == r8_carried[row["ticker"]]

    assert all(row.get("deterministic_mapping_used") == "TRUE" for row in mapping_rows if row.get("contribution_value"))
    assert all(row.get("source_exposure_fields_used") for row in mapping_rows if row.get("contribution_value"))
    assert all(row.get("global_regime_copied_without_exposure_conditioning") == "FALSE" for row in mapping_rows)
    assert all(row.get("source_rank_or_score_used") == "FALSE" for row in mapping_rows)
    assert all(row.get("baseline_rank_used") == "FALSE" for row in mapping_rows)

    for rows in [source_rows, mapping_rows, component_rows, validation_rows, coverage_rows, gate_rows]:
        assert_false(rows, "fabricated_values_created") if "fabricated_values_created" in rows[0] else None
        assert_false(rows, "proxy_values_activated") if "proxy_values_activated" in rows[0] else None
        assert_false(rows, "global_regime_copied_without_exposure_conditioning") if "global_regime_copied_without_exposure_conditioning" in rows[0] else None
        assert_safety(rows)

    validation = validation_rows[0]
    assert validation["shadow_rerank_output_created"] == "FALSE"
    assert validation["official_ranking_created"] == "FALSE"
    assert validation["authoritative_ranking_overwritten"] == "FALSE"
    assert validation["entry_exit_prices_created"] == "FALSE"
    assert validation["buy_sell_recommendations_created"] == "FALSE"

    gate = gate_rows[0]
    assert gate["next_stage_allowed"] == "FALSE"
    assert gate["usable_for_shadow_rerank_count"] == "0"
    assert int(gate["complete_six_family_contribution_candidate_count"]) < 315

    market_coverage = [row for row in coverage_rows if row["factor_family"] == "MARKET_REGIME"][0]
    assert int(market_coverage["materialized_candidate_count"]) == len(materialized)


if __name__ == "__main__":
    test_mapper()
    print("PASS_V20_108_R8_R3_MARKET_REGIME_EXPOSURE_METADATA_MAPPER_TESTS")
