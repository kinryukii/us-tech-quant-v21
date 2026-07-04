#!/usr/bin/env python
"""Tests for V20.16-R4 legacy downstream stale-lineage closeout."""

from __future__ import annotations

import csv
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v20/v20_16_r4_legacy_downstream_stale_lineage_closeout.py"
spec = importlib.util.spec_from_file_location("v20_16_r4", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def fixture(root: Path) -> tuple[Path, Path]:
    d = root / "outputs/v20/diagnostics"
    c = root / "outputs/v20/consolidation"
    write_rows(c / "V20_7V_R1_RESEARCH_ONLY_BOOTSTRAP_PRECHECK_REPAIR_SUMMARY.csv", [{
        "final_status": "PASS_V20_7V_R1_RESEARCH_ONLY_BOOTSTRAP_ALLOWED_OFFICIAL_GUARDRAILS_PRESERVED",
        "research_only_bootstrap_allowed": "TRUE",
    }])
    write_rows(c / "V20_7V_R2_DAILY_BOOTSTRAP_FAST_SMOKE_VALIDATOR_SUMMARY.csv", [{
        "final_status": "PASS_V20_7V_R2_DAILY_BOOTSTRAP_FAST_SMOKE_VALIDATED",
        "fallback_contract_pass": "TRUE",
    }])
    write_rows(c / "V20_7V_VALIDATION_SUMMARY.csv", [{"expected_market_date": "2026-06-16", "eligible_row_count": "190"}])
    write_rows(d / "V20_16_R1_ELIGIBLE_ROW_COUNT_MISMATCH_FORENSIC_SUMMARY.csv", [{
        "mismatch_confirmed": "TRUE",
        "suspected_root_cause": "DATE_OR_AS_OF_MISMATCH",
        "expected_eligible_row_count": "190",
        "actual_eligible_row_count": "314",
    }])
    write_rows(d / "V20_16_R2_CURRENT_LINEAGE_DOWNSTREAM_REFRESH_DRY_RUN_SUMMARY.csv", [{
        "stale_downstream_lineage_detected": "TRUE",
        "current_v20_7v_as_of_date": "2026-06-16",
        "stale_downstream_as_of_date": "2026-06-15",
        "expected_eligible_row_count": "190",
        "stale_actual_eligible_row_count": "314",
        "reconciliation_pass": "TRUE",
    }])
    write_rows(d / "V20_7X_R2_CURRENT_LINEAGE_CERTIFICATION_REFRESH_COMMIT_SUMMARY.csv", [{
        "current_v20_7v_as_of_date": "2026-06-16",
        "current_v20_7v_eligible_row_count": "190",
        "certified_v20_7x_as_of_date_after": "2026-06-16",
        "certified_v20_7x_eligible_row_count_after": "190",
    }])
    write_rows(d / "V20_8_R1_RELATIVE_PATH_AND_STAGING_CONTRACT_REPAIR_SUMMARY.csv", [{
        "final_status": "PASS_V20_8_R1_RELATIVE_PATH_AND_STAGING_CONTRACT_REPAIRED",
    }])
    write_rows(d / "V20_9_R1_RELATIVE_PATH_AND_STAGING_CONTRACT_REPAIR_SUMMARY.csv", [{
        "final_status": "PASS_V20_9_R1_RELATIVE_PATH_AND_STAGING_CONTRACT_REPAIRED",
    }])
    write_rows(d / "V20_16_R3B_SAFE_STAGED_RERUN_WRAPPER_SUMMARY.csv", [{
        "final_status": "BLOCKED_V20_16_R3B_ABSOLUTE_PRODUCTION_PATH_BINDING",
        "decision": "BLOCK_STAGED_RERUN_ABSOLUTE_PRODUCTION_PATH_BINDING",
        "certified_v20_7x_as_of_date": "2026-06-16",
        "certified_v20_7x_eligible_row_count": "190",
        "production_downstream_as_of_date_before": "2026-06-15",
        "production_downstream_eligible_row_count_before": "314",
        "earliest_failed_stage": "V20.10",
        "earliest_failure_reason": "ABSOLUTE_PRODUCTION_PATH_BINDING_DETECTED_IN_DOWNSTREAM_SCRIPT_OR_WRAPPER",
    }])
    prod = c / "V20_16_GATE_DECISION.csv"
    protected = c / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
    write_rows(c / "V20_8_NORMALIZED_RESEARCH_DATASET.csv", [{"ticker": "OLD", "effective_observation_date": "2026-06-15"}])
    write_rows(prod, [{"eligible_row_count": "314", "as_of_date": "2026-06-15"}])
    write_rows(c / "V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv", [{"ticker": "A", "effective_observation_date": "2026-06-16"}])
    write_rows(protected, [{"ticker": "A", "rank": "1"}])
    return prod, protected


def test_stale_downstream_lineage_and_repaired_status_detected() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, rows = module.run_closeout(root)
        assert summary["lineage_mismatch_confirmed"] == "TRUE"
        assert summary["v20_8_staging_contract_repaired"] == "TRUE"
        assert summary["v20_9_staging_contract_repaired"] == "TRUE"
        assert summary["next_unrepaired_legacy_stage"] == "V20.10"
        assert any(r["stage_name"] == "V20.10" and r["staging_contract_status"] == "NEXT_UNREPAIRED_LEGACY_BINDING" for r in rows)


def test_current_use_restricted_and_daily_bootstrap_not_blocked() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, rows = module.run_closeout(root)
        assert summary["v20_8_to_v20_16_current_use_allowed"] == "FALSE"
        assert summary["v20_8_to_v20_16_current_use_restriction"] == "LEGACY_STALE_LINEAGE_DO_NOT_USE_AS_CURRENT"
        assert summary["daily_research_bootstrap_blocked_by_this_issue"] == "FALSE"
        assert all(r["current_use_allowed"] == "FALSE" for r in rows if str(r["stage_name"]).startswith("V20.1") or r["stage_name"] in {"V20.8", "V20.9"})


def test_full_legacy_replay_not_recommended_and_v21_focus() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, _ = module.run_closeout(root)
        assert summary["full_legacy_replay_available"] == "FALSE"
        assert summary["full_legacy_replay_recommended_now"] == "FALSE"
        assert summary["recommended_next_focus"] == "V21_FORWARD_RETURN_MATURITY_CHECK_2026_06_24"


def test_production_and_protected_mutation_detection() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); prod, _ = fixture(root)
        summary, _ = module.run_closeout(root, production_mutation_hook=lambda: prod.write_text("x\n1\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_PRODUCTION
        assert summary["production_v20_8_to_v20_16_outputs_mutated"] == "TRUE"
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); _, protected = fixture(root)
        summary, _ = module.run_closeout(root, protected_mutation_hook=lambda: protected.write_text("ticker,rank\nA,2\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_PROTECTED
        assert summary["protected_outputs_mutated"] == "TRUE"


def test_permissions_fields_summary_fields_and_repeat_safe() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        first, _ = module.run_closeout(root)
        second, _ = module.run_closeout(root)
        assert first["final_status"] == second["final_status"]
        assert set(module.SUMMARY_FIELDS).issubset(second)
        for field in (
            "official_activation_allowed", "official_recommendation_allowed",
            "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
            "broker_execution_allowed", "trade_action_allowed",
        ):
            assert second[field] == "FALSE"


if __name__ == "__main__":
    test_stale_downstream_lineage_and_repaired_status_detected()
    test_current_use_restricted_and_daily_bootstrap_not_blocked()
    test_full_legacy_replay_not_recommended_and_v21_focus()
    test_production_and_protected_mutation_detection()
    test_permissions_fields_summary_fields_and_repeat_safe()
    print("PASS test_v20_16_r4_legacy_downstream_stale_lineage_closeout")
