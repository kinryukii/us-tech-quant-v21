#!/usr/bin/env python
"""Tests for V20.7X-R2 certification refresh commit."""

from __future__ import annotations

import csv
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v20/v20_7x_r2_current_lineage_certification_refresh_commit.py"
spec = importlib.util.spec_from_file_location("v20_7x_r2", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def fixture(root: Path, dry_pass: bool = True) -> tuple[Path, Path]:
    d, c = root / "outputs/v20/diagnostics", root / "outputs/v20/consolidation"
    write_rows(d / "V20_7X_R1_CURRENT_LINEAGE_CERTIFICATION_REFRESH_DRY_RUN_SUMMARY.csv", [{
        "final_status": "PASS_V20_7X_R1_CURRENT_LINEAGE_CERTIFICATION_DRY_RUN_READY",
        "decision": "RECOMMEND_V20_7X_R2_CURRENT_LINEAGE_CERTIFICATION_REFRESH_COMMIT",
        "certification_dry_run_pass": "TRUE" if dry_pass else "FALSE",
        "dry_run_certified_as_of_date": "2026-06-16",
        "dry_run_certified_eligible_row_count": "2" if dry_pass else "1",
    }])
    write_rows(c / "V20_7V_ACTIVE_MARKET_SOURCE_STAGING.csv", [{
        "source_artifact_id": "CURRENT", "source_system": "SOURCE", "source_hash": "HASH",
        "run_id": "RUN", "sample_id": f"S{i}", "ticker": f"T{i}",
        "observation_date": "2026-06-16", "latest_price_date": "2026-06-16",
        "latest_close": "10", "active_runtime_flag": "TRUE",
        "historical_reference_flag": "FALSE", "created_at_utc": "2026-06-17T00:00:00+00:00",
    } for i in range(2)])
    write_rows(c / "V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv", [{
        **{field: "" for field in module.BINDING_FIELDS},
        "input_artifact_id": "OLD", "lineage_binding_id": f"OLD{i}", "source_artifact_id": "OLD",
        "source_system": "SOURCE", "source_hash": "OLD", "run_id": "OLD", "sample_id": f"O{i}",
        "ticker": f"X{i}", "effective_observation_date": "2026-06-15",
        "effective_price_date": "2026-06-15", "effective_close": "9",
        "active_runtime_flag": "TRUE", "historical_reference_flag": "FALSE",
        "allowed_for_v20_8_input": "TRUE", "allowed_for_official_use": "FALSE",
    } for i in range(3)])
    downstream = c / "V20_8_NORMALIZED_RESEARCH_DATASET.csv"
    write_rows(downstream, [{"ticker": "X", "effective_observation_date": "2026-06-15"}])
    protected = c / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
    write_rows(protected, [{"ticker": "AAA", "rank": "1"}])
    return downstream, protected


def test_prechecks() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, dry_pass=False)
        summary, _ = module.run_commit(root)
        assert summary["final_status"] == module.BLOCKED_PRECHECK
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        (root / "outputs/v20/diagnostics/V20_7X_R1_CURRENT_LINEAGE_CERTIFICATION_REFRESH_DRY_RUN_SUMMARY.csv").unlink()
        summary, _ = module.run_commit(root)
        assert summary["final_status"] == module.BLOCKED_R1


def test_date_and_count_precheck() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        p = root / "outputs/v20/diagnostics/V20_7X_R1_CURRENT_LINEAGE_CERTIFICATION_REFRESH_DRY_RUN_SUMMARY.csv"
        write_rows(p, [{
            "final_status": "PASS_V20_7X_R1_CURRENT_LINEAGE_CERTIFICATION_DRY_RUN_READY",
            "decision": "RECOMMEND_V20_7X_R2_CURRENT_LINEAGE_CERTIFICATION_REFRESH_COMMIT",
            "certification_dry_run_pass": "TRUE", "dry_run_certified_as_of_date": "2026-06-15",
            "dry_run_certified_eligible_row_count": "2",
        }])
        summary, _ = module.run_commit(root)
        assert summary["final_status"] == module.BLOCKED_PRECHECK


def test_success_and_repeat_safe() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        first, _ = module.run_commit(root)
        assert first["final_status"] == module.PASS_STATUS
        assert first["certified_v20_7x_as_of_date_after"] == "2026-06-16"
        assert first["certified_v20_7x_eligible_row_count_after"] == 2
        assert first["expected_vs_committed_delta"] == 0
        assert first["downstream_v20_8_to_v20_16_outputs_mutated"] == "FALSE"
        second, _ = module.run_commit(root)
        assert second["final_status"] == module.PASS_STATUS
        assert second["certified_v20_7x_eligible_row_count_after"] == 2


def test_mutation_detection() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); downstream, _ = fixture(root)
        summary, _ = module.run_commit(root, downstream_mutation_hook=lambda: downstream.write_text("x\n1\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_DOWNSTREAM
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); _, protected = fixture(root)
        summary, _ = module.run_commit(root, protected_mutation_hook=lambda: protected.write_text("ticker,rank\nAAA,2\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_PROTECTED


def test_fields_and_permissions() -> None:
    assert set(module.SUMMARY_FIELDS) >= {
        "stage", "final_status", "decision", "source_v20_7x_r1_status",
        "source_v20_7x_r1_decision", "source_v20_7x_r1_certification_dry_run_pass",
        "current_v20_7v_path", "current_v20_7v_as_of_date",
        "current_v20_7v_eligible_row_count", "certified_v20_7x_path",
        "certified_v20_7x_as_of_date_before", "certified_v20_7x_eligible_row_count_before",
        "certification_staleness_detected", "dry_run_certified_as_of_date",
        "dry_run_certified_eligible_row_count", "certified_v20_7x_as_of_date_after",
        "certified_v20_7x_eligible_row_count_after", "expected_vs_committed_delta",
        "certification_commit_pass", "certified_v20_7x_production_outputs_mutated",
        "certified_v20_7x_mutation_scope", "downstream_v20_8_to_v20_16_outputs_mutated",
        "protected_outputs_mutated", "protected_output_mutation_count",
        "official_activation_allowed", "official_recommendation_allowed",
        "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
        "broker_execution_allowed", "trade_action_allowed", "research_only", "created_at_utc",
    }
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, _ = module.run_commit(root)
        for field in ("official_activation_allowed", "official_recommendation_allowed", "official_ranking_mutation_allowed", "official_weight_mutation_allowed", "broker_execution_allowed", "trade_action_allowed"):
            assert summary[field] == "FALSE"


if __name__ == "__main__":
    test_prechecks(); test_date_and_count_precheck(); test_success_and_repeat_safe()
    test_mutation_detection(); test_fields_and_permissions()
    print("PASS test_v20_7x_r2_current_lineage_certification_refresh_commit")
