#!/usr/bin/env python
"""Tests for V20.16-R1 eligible-row-count forensic stage."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v20/v20_16_r1_eligible_row_count_mismatch_forensic_and_repair_plan.py"
spec = importlib.util.spec_from_file_location("v20_16_r1", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def fixture(root: Path, expected: int = 2, actual: int = 3, date_mismatch: bool = True) -> Path:
    c = root / "outputs/v20/consolidation"
    current_date = "2026-06-16"
    old_date = "2026-06-15" if date_mismatch else current_date
    write_rows(c / "V20_7V_ACTIVE_MARKET_SOURCE_STAGING.csv", [
        {"ticker": f"T{i}", "observation_date": current_date, "latest_close": "1", "run_id": "CURRENT"}
        for i in range(expected)
    ])
    write_rows(c / "V20_8_NORMALIZED_RESEARCH_DATASET.csv", [
        {"ticker": f"X{i}", "effective_observation_date": old_date, "effective_close": "1", "normalized_row_id": f"N{i}", "run_id": "OLD"}
        for i in range(actual)
    ])
    write_rows(c / "V20_9_FACTOR_RESEARCH_BASE_DATASET.csv", [
        {"ticker": f"X{i}", "effective_observation_date": old_date, "effective_close": "1", "normalized_row_id": f"N{i}", "run_id": "OLD"}
        for i in range(actual)
    ])
    write_rows(c / "V20_15_LIMITED_FACTOR_SCORE_LAYER.csv", [
        {"ticker": f"X{i}", "effective_observation_date": old_date, "effective_close": "1", "factor_score_row_id": f"S{i}-{family}", "run_id": "OLD"}
        for i in range(actual) for family in range(5)
    ])
    write_rows(c / "V20_16_GATE_DECISION.csv", [{
        "eligible_row_count": str(actual),
        "consumed_v20_7v_status": "PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY",
        "expected_score_rows_from_current_v20_7v_eligible_rows": str(actual * 5),
    }])
    protected = c / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
    write_rows(protected, [{"ticker": "AAA", "rank": "1"}])
    return protected


def test_mismatch_and_date_cause() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root)
        summary, comparison = module.run_forensic(root)
        assert summary["mismatch_confirmed"] == "TRUE"
        assert summary["expected_eligible_row_count"] == 2
        assert summary["actual_eligible_row_count"] == 3
        assert summary["row_count_delta"] == 1
        assert summary["suspected_root_cause"] == "DATE_OR_AS_OF_MISMATCH"
        assert summary["final_status"] == module.PASS_IDENTIFIED
        assert comparison


def test_no_mismatch() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root, expected=3, actual=3, date_mismatch=False)
        summary, _ = module.run_forensic(root)
        assert summary["final_status"] == module.PASS_NO_MISMATCH
        assert summary["mismatch_confirmed"] == "FALSE"


def test_probable_fixture_and_row_loss_classification() -> None:
    comparison = [
        {"stage_name": "V20.7V_CURRENT_STAGING", "row_count": 5, "notes": "", "missing_required_field_count": 0, "price_missing_count": 0, "duplicate_key_count": 0},
        {"stage_name": "V20.8_NORMALIZED_DATASET", "row_count": 3, "notes": "", "missing_required_field_count": 1, "price_missing_count": 0, "duplicate_key_count": 0},
        {"stage_name": "V20.15_SCORE_LAYER", "row_count": 15, "notes": "", "missing_required_field_count": 0, "price_missing_count": 0, "duplicate_key_count": 0},
        {"stage_name": "V20.16_GATE", "row_count": 1, "eligible_row_count": 3, "notes": "", "missing_required_field_count": 0, "price_missing_count": 0, "duplicate_key_count": 0},
    ]
    assert module.classify(5, 3, comparison)[0] == "MISSING_PRICE_OR_REQUIRED_FIELD_FILTER"
    for row in comparison:
        row["missing_required_field_count"] = 0
    assert module.classify(5, 4, comparison)[0] == "UNKNOWN_REQUIRES_MANUAL_REVIEW"


def test_mutation_blocks_and_production_unchanged() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        protected = fixture(root)
        gate = root / "outputs/v20/consolidation/V20_16_GATE_DECISION.csv"
        gate_before = hashlib.sha256(gate.read_bytes()).hexdigest()

        def mutate() -> None:
            protected.write_text("ticker,rank\nAAA,2\n", encoding="utf-8")

        summary, _ = module.run_forensic(root, mutation_hook=mutate)
        assert summary["final_status"] == module.BLOCKED_MUTATION
        assert hashlib.sha256(gate.read_bytes()).hexdigest() == gate_before


def test_fields_and_guardrails() -> None:
    assert set(module.SUMMARY_FIELDS) >= {
        "stage", "final_status", "decision", "detected_regression_name",
        "expected_eligible_row_count", "actual_eligible_row_count", "row_count_delta",
        "mismatch_confirmed", "suspected_root_cause", "root_cause_confidence",
        "source_expected_path", "source_actual_path", "comparison_artifact_path",
        "safe_repair_available", "production_output_mutation_allowed",
        "official_activation_allowed", "official_recommendation_allowed",
        "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
        "broker_execution_allowed", "trade_action_allowed", "research_only", "created_at_utc",
    }
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root)
        summary, _ = module.run_forensic(root)
        for field in (
            "production_output_mutation_allowed", "official_activation_allowed",
            "official_recommendation_allowed", "official_ranking_mutation_allowed",
            "official_weight_mutation_allowed", "broker_execution_allowed",
            "trade_action_allowed",
        ):
            assert summary[field] == "FALSE"


if __name__ == "__main__":
    test_mismatch_and_date_cause()
    test_no_mismatch()
    test_probable_fixture_and_row_loss_classification()
    test_mutation_blocks_and_production_unchanged()
    test_fields_and_guardrails()
    print("PASS test_v20_16_r1_eligible_row_count_mismatch_forensic_and_repair_plan")
