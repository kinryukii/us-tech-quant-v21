#!/usr/bin/env python
"""Tests for V20.7V-R1 research-only bootstrap precheck repair."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v20/v20_7v_r1_research_only_bootstrap_precheck_repair.py"
OPERATOR = ROOT / "scripts/v20/run_v20_current_chain_bootstrap_repair.ps1"
V200 = ROOT / "outputs/v20/reports/V20_200_NEXT_STAGE_GATE.csv"

spec = importlib.util.spec_from_file_location("v20_7v_r1", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def source_row(status: str) -> dict[str, str]:
    return {
        "status": status,
        "eligible_row_count": "190",
        "missing_core_field_summary": "NONE",
        "stale_ticker_count": "0",
        "missing_latest_price_count": "0",
        "BROKER_API_USED": "FALSE",
        "ORDER_EXECUTION_USED": "FALSE",
    }


def test_evaluation() -> None:
    normal = module.evaluate_repair(source_row(module.SOURCE_PASS), "PASS_REPORT_READY", True, True)
    assert normal["final_status"] == module.PASS_STATUS
    assert normal["research_only_bootstrap_allowed"] == "TRUE"

    blocked = module.evaluate_repair(source_row(module.SOURCE_REVIEW_BLOCK), "PASS_REPORT_READY", True, True)
    assert blocked["final_status"] == module.PASS_STATUS
    assert blocked["research_only_bootstrap_allowed"] == "TRUE"
    assert all(blocked[field] == "FALSE" for field in module.PERMISSION_FIELDS)

    for field in module.PERMISSION_FIELDS:
        refused = module.evaluate_repair(
            source_row(module.SOURCE_REVIEW_BLOCK), "PASS_REPORT_READY", True, True, {field: "TRUE"}
        )
        assert refused["research_only_bootstrap_allowed"] == "FALSE", field
        assert refused["final_status"] == module.BLOCKED_STATUS, field

    corrupted = source_row(module.SOURCE_REVIEW_BLOCK)
    corrupted["missing_latest_price_count"] = "1"
    assert module.evaluate_repair(corrupted, "PASS_REPORT_READY", True, True)[
        "research_only_bootstrap_allowed"
    ] == "FALSE"


def test_stage_and_no_source_overwrite() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = root / "outputs/v20/consolidation/V20_7V_VALIDATION_SUMMARY.csv"
        source.parent.mkdir(parents=True)
        with source.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(source_row(module.SOURCE_REVIEW_BLOCK)))
            writer.writeheader()
            writer.writerow(source_row(module.SOURCE_REVIEW_BLOCK))
        before = hashlib.sha256(source.read_bytes()).hexdigest()

        for number, name in (
            ("194", "recomputable_factor_snapshot_producer_contract"),
            ("195", "daily_snapshot_accumulation_and_forward_observation_ledger"),
            ("196", "forward_observation_maturity_updater"),
            ("197", "daily_walk_forward_validation_runner"),
            ("198", "daily_walk_forward_chain_integration"),
            ("199", "daily_research_runner_walk_forward_binding"),
            ("200", "operator_daily_report_v2_with_walk_forward_and_shadow_policy_status"),
        ):
            path = root / f"scripts/v20/run_v20_{number}_{name}.ps1"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# research-only fixture\n", encoding="utf-8")

        result = subprocess.run(
            ["python", str(SCRIPT), "--root", str(root)], cwd=ROOT, text=True, capture_output=True, check=True
        )
        assert "RESEARCH_ONLY_BOOTSTRAP_ALLOWED=TRUE" in result.stdout
        assert hashlib.sha256(source.read_bytes()).hexdigest() == before
        summary = module.read_first(
            root / "outputs/v20/consolidation/V20_7V_R1_RESEARCH_ONLY_BOOTSTRAP_PRECHECK_REPAIR_SUMMARY.csv"
        )
        assert summary["final_status"] == module.PARTIAL_STATUS


def test_operator_fallback_and_v200_safety() -> None:
    text = OPERATOR.read_text(encoding="utf-8-sig")
    assert "run_v20_7v_r1_research_only_bootstrap_precheck_repair.ps1" in text
    assert "research_only_bootstrap_allowed" in text
    assert "OFFICIAL ACTIVATION REMAINS BLOCKED" in text
    assert "V20.7W official active-market certification is not being bypassed" in text
    assert "RESEARCH_ONLY_DAILY_BOOTSTRAP" in text
    gate = module.read_first(V200)
    assert gate["final_status"] == "PASS_REPORT_READY"
    assert gate["research_only"] == "TRUE"
    for field in (
        "official_ranking_mutated",
        "official_recommendation_created",
        "trade_action_created",
        "broker_execution_supported",
        "real_book_action_created",
    ):
        assert gate[field] == "FALSE", field


if __name__ == "__main__":
    test_evaluation()
    test_stage_and_no_source_overwrite()
    test_operator_fallback_and_v200_safety()
    print("PASS test_v20_7v_r1_research_only_bootstrap_precheck_repair")
