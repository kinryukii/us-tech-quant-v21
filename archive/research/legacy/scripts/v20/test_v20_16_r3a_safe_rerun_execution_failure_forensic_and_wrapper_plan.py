#!/usr/bin/env python
"""Tests for V20.16-R3A safe-rerun failure forensic."""

from __future__ import annotations

import csv
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v20/v20_16_r3a_safe_rerun_execution_failure_forensic_and_wrapper_plan.py"
spec = importlib.util.spec_from_file_location("v20_16_r3a", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def fixture(root: Path, v7x_pass: bool = True) -> tuple[Path, Path]:
    d, c, s = root / "outputs/v20/diagnostics", root / "outputs/v20/consolidation", root / "scripts/v20"
    write_rows(d / "V20_7X_R2_CURRENT_LINEAGE_CERTIFICATION_REFRESH_COMMIT_SUMMARY.csv", [{
        "final_status": "PASS_V20_7X_R2_CURRENT_LINEAGE_CERTIFICATION_REFRESH_COMMITTED" if v7x_pass else "BLOCKED",
        "certification_commit_pass": "TRUE" if v7x_pass else "FALSE",
        "current_v20_7v_as_of_date": "2026-06-16",
        "certified_v20_7x_as_of_date_after": "2026-06-16",
        "certified_v20_7x_eligible_row_count_after": "2",
    }])
    write_rows(d / "V20_16_R3_CURRENT_LINEAGE_DOWNSTREAM_REFRESH_COMMIT_SUMMARY.csv", [{
        "final_status": "BLOCKED_V20_16_R3_SAFE_RERUN_PATH_UNAVAILABLE",
        "decision": "BLOCK_COMMIT_SAFE_RERUN_EXECUTION_FAILED",
        "expected_eligible_row_count": "2",
    }])
    for stage, script_name, wrapper_name, input_rel, output_rel in module.STAGES:
        script = s / script_name
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(
            "from pathlib import Path\nROOT=Path(__file__).resolve().parents[2]\n"
            "CONSOLIDATION=ROOT/'outputs'/'v20'/'consolidation'\n"
            "OUT_X=CONSOLIDATION/'x.csv'\ndef main():\n write_csv(OUT_X, [], [])\n",
            encoding="utf-8",
        )
        (s / wrapper_name).write_text(f"python scripts/v20/{script_name}\n", encoding="utf-8")
        input_path = root / input_rel
        if not input_path.exists():
            write_rows(input_path, [{"ticker": "T", "effective_observation_date": "2026-06-15"}])
        write_rows(root / output_rel, [{"ticker": "T", "effective_observation_date": "2026-06-15"}])
    write_rows(c / "V20_16_GATE_DECISION.csv", [{"eligible_row_count": "3"}])
    protected = c / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
    write_rows(protected, [{"ticker": "A", "rank": "1"}])
    return c / "V20_8_NORMALIZED_RESEARCH_DATASET.csv", protected


def test_failure_and_contract_classification() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, deps, contracts = module.run_forensic(root)
        assert summary["execution_failure_confirmed"] == "TRUE"
        assert summary["suspected_failure_stage"] == "V20.8"
        assert summary["suspected_failure_reason"] == "INPUT_OVERRIDE_UNSUPPORTED"
        assert summary["safe_wrapper_available"] == "FALSE"
        assert summary["recommended_next_stage"] == "V20.16-R3B_SAFE_STAGED_RERUN_WRAPPER"
        assert set(module.DEPENDENCY_FIELDS).issubset(deps[0])
        assert set(module.CONTRACT_FIELDS).issubset(contracts[0])


def test_missing_wrapper_and_direct_write() -> None:
    contract = {"input_override": True, "output_override": True, "dry_run": False, "direct_write": True, "requires_v7x": False, "reads_current_v7x": False}
    assert module.classify_contract(True, False, contract, False, False)[0] == "WRAPPER_MISSING"
    assert module.classify_contract(True, True, contract, False, False)[0] == "SCRIPT_WRITES_PRODUCTION_DIRECTLY"
    contract["direct_write"] = False
    contract["input_override"] = False
    assert module.classify_contract(True, True, contract, False, False)[0] == "INPUT_OVERRIDE_UNSUPPORTED"


def test_stale_binding_classification() -> None:
    contract = {"input_override": True, "output_override": True, "dry_run": False, "direct_write": False, "requires_v7x": True, "reads_current_v7x": False}
    assert module.classify_contract(True, True, contract, True, False)[0] == "CERTIFIED_V20_7X_NOT_READ_BY_DOWNSTREAM"
    contract["reads_current_v7x"] = True
    assert module.classify_contract(True, True, contract, True, False)[0] == "SCRIPT_STILL_POINTS_TO_STALE_INPUT"


def test_invalid_input_and_mutations() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, v7x_pass=False)
        summary, _, _ = module.run_forensic(root)
        assert summary["final_status"] == module.BLOCKED_INPUT
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); production, _ = fixture(root)
        summary, _, _ = module.run_forensic(root, production_mutation_hook=lambda: production.write_text("x\n1\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_PRODUCTION
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); _, protected = fixture(root)
        summary, _, _ = module.run_forensic(root, protected_mutation_hook=lambda: protected.write_text("ticker,rank\nA,2\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_PROTECTED


def test_guardrails_and_repeat_safe() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        first, _, _ = module.run_forensic(root)
        second, _, _ = module.run_forensic(root)
        assert first["final_status"] == second["final_status"]
        for field in ("official_activation_allowed", "official_recommendation_allowed", "official_ranking_mutation_allowed", "official_weight_mutation_allowed", "broker_execution_allowed", "trade_action_allowed"):
            assert first[field] == "FALSE"


if __name__ == "__main__":
    test_failure_and_contract_classification(); test_missing_wrapper_and_direct_write()
    test_stale_binding_classification(); test_invalid_input_and_mutations()
    test_guardrails_and_repeat_safe()
    print("PASS test_v20_16_r3a_safe_rerun_execution_failure_forensic_and_wrapper_plan")
