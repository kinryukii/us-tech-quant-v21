#!/usr/bin/env python
"""Tests for V20.16-R3 current-lineage downstream refresh commit."""

from __future__ import annotations

import csv
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v20/v20_16_r3_current_lineage_downstream_refresh_commit.py"
spec = importlib.util.spec_from_file_location("v20_16_r3", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def fixture(root: Path, r2_pass: bool = True, aligned_7x: bool = False) -> Path:
    d = root / "outputs/v20/diagnostics"
    c = root / "outputs/v20/consolidation"
    write_rows(d / "V20_16_R1_ELIGIBLE_ROW_COUNT_MISMATCH_FORENSIC_SUMMARY.csv", [{
        "final_status": "PASS_V20_16_R1_MISMATCH_ROOT_CAUSE_IDENTIFIED_REPAIR_PLAN_READY",
        "suspected_root_cause": "DATE_OR_AS_OF_MISMATCH",
    }])
    write_rows(d / "V20_16_R2_CURRENT_LINEAGE_DOWNSTREAM_REFRESH_DRY_RUN_SUMMARY.csv", [{
        "final_status": "PASS_V20_16_R2_CURRENT_LINEAGE_DRY_RUN_RECONCILED",
        "reconciliation_pass": "TRUE" if r2_pass else "FALSE",
        "decision": "RECOMMEND_V20_16_R3_CURRENT_LINEAGE_DOWNSTREAM_REFRESH_COMMIT",
        "current_v20_7v_as_of_date": "2026-06-16",
        "stale_downstream_as_of_date": "2026-06-15",
        "expected_eligible_row_count": "2",
        "stale_actual_eligible_row_count": "3",
        "dry_run_reconciled_eligible_row_count": "2" if r2_pass else "1",
    }])
    binding_date = "2026-06-16" if aligned_7x else "2026-06-15"
    binding_count = 2 if aligned_7x else 3
    write_rows(c / "V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv", [
        {"ticker": f"T{i}", "effective_observation_date": binding_date, "allowed_for_v20_8_input": "TRUE"}
        for i in range(binding_count)
    ])
    write_rows(c / "V20_7X_GATE_DECISION.csv", [{"status": "PASS_V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING_READY"}])
    for wrapper in module.WRAPPERS:
        path = root / "scripts/v20" / wrapper
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# fixture\n", encoding="utf-8")
    stale = [
        {"ticker": f"X{i}", "effective_observation_date": "2026-06-15", "normalized_row_id": f"N{i}"}
        for i in range(3)
    ]
    write_rows(c / "V20_8_NORMALIZED_RESEARCH_DATASET.csv", stale)
    write_rows(c / "V20_9_FACTOR_RESEARCH_BASE_DATASET.csv", stale)
    write_rows(c / "V20_11_FIRST_ATTACHABLE_FACTOR_INPUT_LAYER.csv", stale)
    write_rows(c / "V20_13_LIMITED_FACTOR_EVIDENCE_LAYER.csv", stale)
    write_rows(c / "V20_15_LIMITED_FACTOR_SCORE_LAYER.csv", stale)
    write_rows(c / "V20_16_GATE_DECISION.csv", [{
        "eligible_row_count": "3",
        "consumed_v20_7v_status": "PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY",
        "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
        "OFFICIAL_RECOMMENDATION_ROWS_CREATED": "0",
    }])
    protected = c / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
    write_rows(protected, [{"ticker": "AAA", "rank": "1"}])
    return protected


def safe_runner(root: Path) -> None:
    c = root / "outputs/v20/consolidation"
    current = [
        {"ticker": f"T{i}", "effective_observation_date": "2026-06-16", "normalized_row_id": f"CURRENT_{i}"}
        for i in range(2)
    ]
    for name in (
        "V20_8_NORMALIZED_RESEARCH_DATASET.csv",
        "V20_9_FACTOR_RESEARCH_BASE_DATASET.csv",
        "V20_11_FIRST_ATTACHABLE_FACTOR_INPUT_LAYER.csv",
        "V20_13_LIMITED_FACTOR_EVIDENCE_LAYER.csv",
        "V20_15_LIMITED_FACTOR_SCORE_LAYER.csv",
    ):
        write_rows(c / name, current)
    write_rows(c / "V20_16_GATE_DECISION.csv", [{
        "eligible_row_count": "2",
        "consumed_v20_7v_status": "PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY",
        "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
        "OFFICIAL_RECOMMENDATION_ROWS_CREATED": "0",
    }])


def test_precheck_blocks() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root, r2_pass=False)
        summary, _ = module.run_commit(root)
        assert summary["final_status"] == module.BLOCKED_PRECHECK
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root)
        (root / "outputs/v20/diagnostics/V20_16_R1_ELIGIBLE_ROW_COUNT_MISMATCH_FORENSIC_SUMMARY.csv").unlink()
        summary, _ = module.run_commit(root)
        assert summary["final_status"] == module.BLOCKED_INPUT


def test_safe_path_unavailable_blocks() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root, aligned_7x=False)
        summary, _ = module.run_commit(root)
        assert summary["final_status"] == module.BLOCKED_PATH
        assert summary["production_v20_8_to_v20_16_outputs_mutated"] == "FALSE"


def test_successful_commit_and_repeat_safe() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root, aligned_7x=True)
        summary, _ = module.run_commit(root, safe_runner=safe_runner)
        assert summary["final_status"] == module.PASS_STATUS
        assert summary["committed_eligible_row_count"] == 2
        assert summary["downstream_as_of_date_after_commit"] == "2026-06-16"
        assert summary["expected_vs_committed_delta"] == 0
        assert summary["commit_pass"] == "TRUE"
        assert summary["protected_outputs_mutated"] == "FALSE"
        second, _ = module.run_commit(root, safe_runner=safe_runner)
        assert second["final_status"] == module.PASS_STATUS


def test_protected_mutation_and_guardrails() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        protected = fixture(root, aligned_7x=True)

        def mutate() -> None:
            protected.write_text("ticker,rank\nAAA,2\n", encoding="utf-8")

        summary, _ = module.run_commit(root, safe_runner=safe_runner, mutation_hook=mutate)
        assert summary["final_status"] == module.BLOCKED_PROTECTED
        assert summary["protected_output_mutation_count"] == 1
    assert set(module.SUMMARY_FIELDS) >= {
        "stage", "final_status", "decision", "source_v20_16_r1_status",
        "source_v20_16_r2_status", "source_v20_16_r2_reconciliation_pass",
        "current_v20_7v_as_of_date", "stale_downstream_as_of_date_before_commit",
        "downstream_as_of_date_after_commit", "expected_eligible_row_count",
        "stale_actual_eligible_row_count_before_commit", "committed_eligible_row_count",
        "expected_vs_committed_delta", "commit_pass",
        "production_v20_8_to_v20_16_outputs_mutated", "production_mutation_scope",
        "protected_outputs_mutated", "protected_output_mutation_count",
        "official_activation_allowed", "official_recommendation_allowed",
        "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
        "broker_execution_allowed", "trade_action_allowed", "research_only", "created_at_utc",
    }


if __name__ == "__main__":
    test_precheck_blocks()
    test_safe_path_unavailable_blocks()
    test_successful_commit_and_repeat_safe()
    test_protected_mutation_and_guardrails()
    print("PASS test_v20_16_r3_current_lineage_downstream_refresh_commit")
