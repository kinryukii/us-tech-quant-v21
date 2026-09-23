#!/usr/bin/env python
"""Tests for V20.7V-R2 daily bootstrap fast smoke validator."""

from __future__ import annotations

import csv
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v20/v20_7v_r2_daily_bootstrap_fast_smoke_validator.py"
spec = importlib.util.spec_from_file_location("v20_7v_r2", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def write_row(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row), lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)


def build_fixture(root: Path, include_r1: bool = True) -> Path:
    consolidation = root / "outputs/v20/consolidation"
    write_row(consolidation / "V20_7V_VALIDATION_SUMMARY.csv", {
        "status": module.V7V_REVIEW_BLOCK,
        "eligible_row_count": "2",
        "missing_core_field_summary": "NONE",
        "stale_ticker_count": "0",
        "missing_latest_price_count": "0",
    })
    if include_r1:
        write_row(consolidation / "V20_7V_R1_RESEARCH_ONLY_BOOTSTRAP_PRECHECK_REPAIR_SUMMARY.csv", {
            "final_status": module.R1_PASS,
            "decision": "ALLOW_RESEARCH_ONLY_BOOTSTRAP_OFFICIAL_GUARDRAILS_PRESERVED",
            "research_only_bootstrap_allowed": "TRUE",
            **{field: "FALSE" for field in module.PERMISSIONS},
        })
    write_row(consolidation / "V20_7V_ACTIVE_MARKET_SOURCE_STAGING.csv", {"ticker": "AAA"})
    write_row(consolidation / "V20_16_GATE_DECISION.csv", {"eligible_row_count": "2"})
    protected = consolidation / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
    write_row(protected, {"ticker": "AAA", "rank": "1"})
    return protected


def test_pass_and_unrelated_regression() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        build_fixture(root)
        row = module.run_validation(root)
        assert row["final_status"] == module.PASS_STATUS
        assert row["fallback_contract_pass"] == "TRUE"
        assert row["research_only_bootstrap_allowed"] == "TRUE"
        assert row["daily_operator_full_run_attempted"] == "FALSE"
        assert row["protected_output_hash_check_status"] == "PASS_PROTECTED_OUTPUT_HASHES_UNCHANGED"
        assert row["mutated_protected_output_count"] == 0
        assert row["unrelated_known_regression"] == "V20_16_ELIGIBLE_ROW_COUNT_MISMATCH"


def test_missing_r1_blocks() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        build_fixture(root, include_r1=False)
        row = module.run_validation(root)
        assert row["final_status"] == module.INPUT_BLOCKED
        assert row["fallback_contract_pass"] == "FALSE"


def test_permission_true_blocks() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        build_fixture(root)
        r1 = root / "outputs/v20/consolidation/V20_7V_R1_RESEARCH_ONLY_BOOTSTRAP_PRECHECK_REPAIR_SUMMARY.csv"
        write_row(r1, {
            "final_status": module.R1_PASS,
            "decision": "INVALID_PERMISSION_FIXTURE",
            "research_only_bootstrap_allowed": "TRUE",
            **{field: "TRUE" if field == "broker_execution_allowed" else "FALSE" for field in module.PERMISSIONS},
        })
        row = module.run_validation(root)
        assert row["final_status"] == module.CONTRACT_BLOCKED
        assert row["fallback_contract_pass"] == "FALSE"


def test_hash_change_blocks() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        protected = build_fixture(root)

        def mutate() -> None:
            protected.write_text("ticker,rank\nAAA,2\n", encoding="utf-8")

        row = module.run_validation(root, mutation_hook=mutate)
        assert row["final_status"] == module.MUTATION_BLOCKED
        assert row["mutated_protected_output_count"] == 1


def test_contract_has_no_operator_invocation_and_fields_complete() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "subprocess" not in text
    assert "run_v20_daily_research_observation_operator.ps1" not in text
    assert set(module.SUMMARY_FIELDS) >= {
        "stage", "final_status", "decision", "source_v20_7v_status",
        "source_v20_7v_r1_status", "source_v20_7v_r1_decision",
        "research_only_bootstrap_allowed", "fallback_contract_pass",
        "daily_operator_full_run_attempted", "full_operator_required_for_this_stage",
        *module.PERMISSIONS, "protected_output_hash_check_status",
        "mutated_protected_output_count", "unrelated_known_regression", "created_at_utc",
    }


if __name__ == "__main__":
    test_pass_and_unrelated_regression()
    test_missing_r1_blocks()
    test_permission_true_blocks()
    test_hash_change_blocks()
    test_contract_has_no_operator_invocation_and_fields_complete()
    print("PASS test_v20_7v_r2_daily_bootstrap_fast_smoke_validator")
