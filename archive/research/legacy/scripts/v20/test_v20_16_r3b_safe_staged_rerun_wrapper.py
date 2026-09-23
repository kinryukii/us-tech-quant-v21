#!/usr/bin/env python
"""Tests for V20.16-R3B safe staged rerun wrapper."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v20/v20_16_r3b_safe_staged_rerun_wrapper.py"
spec = importlib.util.spec_from_file_location("v20_16_r3b", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def script_source(stage: str, output_name: str, fail: bool = False, mismatch: bool = False) -> str:
    if fail:
        return "raise SystemExit(3)\n"
    return f"""
from pathlib import Path
import csv

BASE = Path("outputs/v20/consolidation")

def read_csv(path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as h:
        return list(csv.DictReader(h))

def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=fields, lineterminator="\\n")
        w.writeheader(); w.writerows(rows)

def main():
    source = read_csv(BASE / "V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv")
    rows = [r for r in source if r.get("allowed_for_v20_8_input") == "TRUE"] or source
    out = BASE / "{output_name}"
    if "{stage}" == "V20.15":
        score = []
        for r in rows:
            score.append({{
                "ticker": r.get("ticker", ""),
                "effective_observation_date": r.get("effective_observation_date", ""),
                "factor_score_value": "0.5",
                "research_only_flag": "TRUE",
                "official_use_allowed": "FALSE",
            }})
        write_csv(out, score, ["ticker","effective_observation_date","factor_score_value","research_only_flag","official_use_allowed"])
    elif "{stage}" == "V20.16":
        count = 1 if {str(mismatch)} else len(rows)
        write_csv(out, [{{"eligible_row_count": str(count), "as_of_date": rows[0].get("effective_observation_date", "") if rows else ""}}], ["eligible_row_count","as_of_date"])
    else:
        write_csv(out, rows, list(rows[0]) if rows else ["ticker","effective_observation_date"])
    return 0

raise SystemExit(main())
"""


def fixture(root: Path, *, r3a: bool = True, v7x: bool = True, absolute: bool = False, fail_stage: str = "", mismatch: bool = False) -> None:
    d = root / "outputs/v20/diagnostics"
    c = root / "outputs/v20/consolidation"
    s = root / "scripts/v20"
    if r3a:
        write_rows(d / "V20_16_R3A_SAFE_RERUN_EXECUTION_FAILURE_FORENSIC_SUMMARY.csv", [{
            "final_status": "PARTIAL_PASS_V20_16_R3A_FAILURE_CONFIRMED_MULTIPLE_UNSAFE_CONTRACTS",
            "decision": "MULTIPLE_UNSAFE_STAGE_CONTRACTS_REQUIRE_STAGED_WRAPPER",
            "recommended_next_stage": "V20.16-R3B_SAFE_STAGED_RERUN_WRAPPER",
        }])
    write_rows(d / "V20_7X_R2_CURRENT_LINEAGE_CERTIFICATION_REFRESH_COMMIT_SUMMARY.csv", [{
        "final_status": "PASS_V20_7X_R2_CURRENT_LINEAGE_CERTIFICATION_REFRESH_COMMITTED",
        "certification_commit_pass": "TRUE",
        "certified_v20_7x_as_of_date_after": "2026-06-16",
        "certified_v20_7x_eligible_row_count_after": "2",
    }])
    if v7x:
        write_rows(c / "V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv", [
            {"ticker": "AAA", "effective_observation_date": "2026-06-16", "allowed_for_v20_8_input": "TRUE"},
            {"ticker": "BBB", "effective_observation_date": "2026-06-16", "allowed_for_v20_8_input": "TRUE"},
        ])
    write_rows(c / "V20_8_NORMALIZED_RESEARCH_DATASET.csv", [
        {"ticker": "OLD1", "effective_observation_date": "2026-06-15"},
        {"ticker": "OLD2", "effective_observation_date": "2026-06-15"},
        {"ticker": "OLD3", "effective_observation_date": "2026-06-15"},
    ])
    write_rows(c / "V20_16_GATE_DECISION.csv", [{"eligible_row_count": "3", "as_of_date": "2026-06-15"}])
    write_rows(c / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv", [{"ticker": "AAA", "rank": "1"}])
    for stage, script_name, wrapper_name, _, output_rel in module.STAGES:
        script = s / script_name
        wrapper = s / wrapper_name
        output_name = Path(output_rel).name
        if absolute:
            text = 'from pathlib import Path\nROOT = Path(__file__).resolve().parents[2]\nCONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"\nOUT_X = CONSOLIDATION / "x.csv"\n'
        else:
            text = script_source(stage, output_name, fail=(stage == fail_stage), mismatch=mismatch)
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(text, encoding="utf-8")
        wrapper.write_text(f"python scripts/v20/{script_name}\n", encoding="utf-8")


def test_blocks_when_r3a_missing_or_invalid() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root, r3a=False)
        summary, _, _ = module.run_wrapper(root)
        assert summary["final_status"] == module.BLOCKED_R3A


def test_blocks_when_certified_v20_7x_missing() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root, v7x=False)
        summary, _, _ = module.run_wrapper(root)
        assert summary["final_status"] == module.BLOCKED_V7X


def test_absolute_production_path_binding_detected() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root, absolute=True)
        summary, results, _ = module.run_wrapper(root)
        assert summary["final_status"] == module.BLOCKED_ABSOLUTE
        assert summary["absolute_path_binding_detected"] == "TRUE"
        assert any(r["status"] == "BLOCKED_ABSOLUTE_PRODUCTION_PATH_BINDING" for r in results)


def test_relative_path_staging_creates_workspace_and_outputs_only_under_staging() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root)
        production_before = sha(root / "outputs/v20/consolidation/V20_8_NORMALIZED_RESEARCH_DATASET.csv")
        summary, _, manifest = module.run_wrapper(root)
        assert summary["staging_workspace_created"] == "TRUE"
        assert summary["relative_path_staging_supported"] == "TRUE"
        assert summary["staged_rerun_attempted"] == "TRUE"
        assert manifest
        assert all(str(row["relative_path"]).startswith("outputs/v20/") for row in manifest)
        assert sha(root / "outputs/v20/consolidation/V20_8_NORMALIZED_RESEARCH_DATASET.csv") == production_before


def test_production_certified_and_protected_outputs_not_mutated() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root)
        prod = root / "outputs/v20/consolidation/V20_8_NORMALIZED_RESEARCH_DATASET.csv"
        v7x = root / "outputs/v20/consolidation/V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv"
        official = root / "outputs/v20/consolidation/V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
        before = (sha(prod), sha(v7x), sha(official))
        summary, _, _ = module.run_wrapper(root)
        assert before == (sha(prod), sha(v7x), sha(official))
        assert summary["production_v20_8_to_v20_16_outputs_mutated"] == "FALSE"
        assert summary["certified_v20_7x_outputs_mutated"] == "FALSE"
        assert summary["protected_outputs_mutated"] == "FALSE"


def test_successful_staged_rerun_reconciles_expected_count() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root)
        summary, _, _ = module.run_wrapper(root)
        assert summary["final_status"] == module.PASS_STATUS
        assert summary["staged_eligible_row_count"] == "2"
        assert summary["expected_eligible_row_count"] == "2"
        assert summary["expected_vs_staged_delta"] == "0"
        assert summary["staged_reconciliation_pass"] == "TRUE"


def test_staged_count_mismatch_blocks_reconciliation() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root, mismatch=True)
        summary, _, _ = module.run_wrapper(root)
        assert summary["final_status"] == module.BLOCKED_RECON
        assert summary["expected_vs_staged_delta"] == "-1"


def test_stage_failure_is_captured() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root, fail_stage="V20.9")
        summary, results, _ = module.run_wrapper(root)
        assert summary["final_status"] == module.PARTIAL_STAGE_FAILED
        assert summary["earliest_failed_stage"] == "V20.9"
        assert summary["earliest_failure_reason"]
        assert any(r["stage_name"] == "V20.9" and r["status"] == "FAILED" for r in results)


def test_permissions_are_false_and_summary_fields_present() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root)
        summary, _, _ = module.run_wrapper(root)
        for field in (
            "official_activation_allowed", "official_recommendation_allowed",
            "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
            "broker_execution_allowed", "trade_action_allowed",
        ):
            assert summary[field] == "FALSE"
        assert set(module.SUMMARY_FIELDS).issubset(summary)


def test_repeat_safe() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture(root)
        first, _, _ = module.run_wrapper(root)
        second, _, _ = module.run_wrapper(root)
        assert first["final_status"] == second["final_status"]
        assert second["production_v20_8_to_v20_16_outputs_mutated"] == "FALSE"


if __name__ == "__main__":
    test_blocks_when_r3a_missing_or_invalid()
    test_blocks_when_certified_v20_7x_missing()
    test_absolute_production_path_binding_detected()
    test_relative_path_staging_creates_workspace_and_outputs_only_under_staging()
    test_production_certified_and_protected_outputs_not_mutated()
    test_successful_staged_rerun_reconciles_expected_count()
    test_staged_count_mismatch_blocks_reconciliation()
    test_stage_failure_is_captured()
    test_permissions_are_false_and_summary_fields_present()
    test_repeat_safe()
    print("PASS test_v20_16_r3b_safe_staged_rerun_wrapper")
