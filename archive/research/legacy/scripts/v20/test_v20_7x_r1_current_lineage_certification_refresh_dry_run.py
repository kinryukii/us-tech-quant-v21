#!/usr/bin/env python
"""Tests for V20.7X-R1 current-lineage certification refresh dry run."""

from __future__ import annotations

import csv
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v20/v20_7x_r1_current_lineage_certification_refresh_dry_run.py"
spec = importlib.util.spec_from_file_location("v20_7x_r1", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def fixture(root: Path, current: bool = True, certified: bool = True) -> tuple[Path, Path]:
    d = root / "outputs/v20/diagnostics"
    c = root / "outputs/v20/consolidation"
    write_rows(d / "V20_16_R3_CURRENT_LINEAGE_DOWNSTREAM_REFRESH_COMMIT_SUMMARY.csv", [{
        "final_status": "BLOCKED_V20_16_R3_SAFE_RERUN_PATH_UNAVAILABLE",
        "decision": "BLOCK_COMMIT_SAFE_CERTIFIED_RERUN_PATH_UNAVAILABLE",
    }])
    if current:
        write_rows(c / "V20_7V_ACTIVE_MARKET_SOURCE_STAGING.csv", [
            {
                "source_artifact_id": "CURRENT", "source_system": "SOURCE",
                "source_hash": "HASH", "run_id": "RUN", "sample_id": f"S{i}",
                "ticker": f"T{i}", "observation_date": "2026-06-16",
                "latest_price_date": "2026-06-16", "latest_close": "10",
                "active_runtime_flag": "TRUE", "historical_reference_flag": "FALSE",
            }
            for i in range(2)
        ])
    v7x = c / "V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv"
    if certified:
        write_rows(v7x, [
            {
                "input_artifact_id": "OLD", "lineage_binding_id": f"B{i}",
                "source_artifact_id": "OLD", "source_system": "SOURCE",
                "source_hash": "OLDHASH", "run_id": "OLDRUN", "sample_id": f"O{i}",
                "ticker": f"X{i}", "effective_observation_date": "2026-06-15",
                "effective_price_date": "2026-06-15", "effective_close": "9",
                "active_runtime_flag": "TRUE", "historical_reference_flag": "FALSE",
                "allowed_for_v20_8_input": "TRUE", "allowed_for_official_use": "FALSE",
            }
            for i in range(3)
        ])
    downstream = c / "V20_8_NORMALIZED_RESEARCH_DATASET.csv"
    write_rows(downstream, [{"ticker": "X", "effective_observation_date": "2026-06-15"}])
    protected = c / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
    write_rows(protected, [{"ticker": "AAA", "rank": "1"}])
    return v7x, protected


def test_staleness_and_dry_run() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root)
        summary, comparison, projected = module.run_dry_run(root)
        assert summary["source_v20_16_r3_status"] == "BLOCKED_V20_16_R3_SAFE_RERUN_PATH_UNAVAILABLE"
        assert summary["certification_staleness_detected"] == "TRUE"
        assert summary["dry_run_certified_eligible_row_count"] == 2
        assert summary["certification_dry_run_pass"] == "TRUE"
        assert summary["final_status"] == module.PASS_STATUS
        assert len(projected) == 2
        assert all(row["certification_claimed"] == "FALSE" for row in projected)
        assert comparison


def test_missing_sources_and_count_failure() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root, current=False)
        summary, _, _ = module.run_dry_run(root)
        assert summary["final_status"] == module.BLOCKED_V7V
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root, certified=False)
        summary, _, _ = module.run_dry_run(root)
        assert summary["final_status"] == module.BLOCKED_V7X
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root)
        summary, _, _ = module.run_dry_run(root, projection_hook=lambda rows: rows[:-1])
        assert summary["final_status"] == module.BLOCKED_DRY


def test_mutation_detection() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        v7x, _ = fixture(root)

        def mutate_v7x() -> None:
            v7x.write_text("ticker\nMUTATED\n", encoding="utf-8")

        summary, _, _ = module.run_dry_run(root, v7x_mutation_hook=mutate_v7x)
        assert summary["final_status"] == module.BLOCKED_PRODUCTION
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        _, protected = fixture(root)

        def mutate_protected() -> None:
            protected.write_text("ticker,rank\nAAA,2\n", encoding="utf-8")

        summary, _, _ = module.run_dry_run(root, protected_mutation_hook=mutate_protected)
        assert summary["final_status"] == module.BLOCKED_PROTECTED


def test_guardrails_fields_and_repeat_safe() -> None:
    assert set(module.SUMMARY_FIELDS) >= {
        "stage", "final_status", "decision", "source_v20_16_r3_status",
        "source_v20_16_r3_decision", "current_v20_7v_path",
        "current_v20_7v_as_of_date", "current_v20_7v_eligible_row_count",
        "certified_v20_7x_path", "certified_v20_7x_as_of_date_before",
        "certified_v20_7x_eligible_row_count_before", "certification_staleness_detected",
        "dry_run_certified_as_of_date", "dry_run_certified_eligible_row_count",
        "expected_current_eligible_row_count", "expected_vs_dry_run_delta",
        "certification_dry_run_pass", "certified_v20_7x_production_outputs_mutated",
        "downstream_v20_8_to_v20_16_outputs_mutated", "protected_outputs_mutated",
        "protected_output_mutation_count", "official_activation_allowed",
        "official_recommendation_allowed", "official_ranking_mutation_allowed",
        "official_weight_mutation_allowed", "broker_execution_allowed",
        "trade_action_allowed", "research_only", "created_at_utc",
    }
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root)
        first, _, first_rows = module.run_dry_run(root)
        second, _, second_rows = module.run_dry_run(root)
        assert first["final_status"] == second["final_status"] == module.PASS_STATUS
        assert first_rows == second_rows
        for field in (
            "official_activation_allowed", "official_recommendation_allowed",
            "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
            "broker_execution_allowed", "trade_action_allowed",
        ):
            assert first[field] == "FALSE"


if __name__ == "__main__":
    test_staleness_and_dry_run()
    test_missing_sources_and_count_failure()
    test_mutation_detection()
    test_guardrails_fields_and_repeat_safe()
    print("PASS test_v20_7x_r1_current_lineage_certification_refresh_dry_run")
