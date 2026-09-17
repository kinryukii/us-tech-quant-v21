from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SOURCE = Path(r"D:\us-tech-quant\scripts\v22\a2_concentration_triggered_gross_scaler_r1.py")
SPEC = importlib.util.spec_from_file_location("a2_gross_scaler_tested", SOURCE)
assert SPEC is not None and SPEC.loader is not None
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)
CASH = MOD.import_file("a2_gross_scaler_test_cash", MOD.CASH_SOURCE)


def test_structural_gross_formula_is_exact_and_bounded() -> None:
    g12, g48, unclipped, gross = MOD.gross_rule(.25, .16, .20, .144)
    assert abs(g12 - math.sqrt(.20 / .25)) <= 1e-15
    assert abs(g48 - math.sqrt(.144 / .16)) <= 1e-15
    assert unclipped == min(1.0, g12, g48)
    assert gross == max(.80, unclipped)
    assert MOD.gross_rule(.25, .16, .01, .01)[3] == .80
    assert MOD.gross_rule(.20, .14, .21, .15) == (1.0, 1.0, 1.0, 1.0)


def test_uniform_scaling_preserves_equity_normalized_hhi() -> None:
    weights = np.array([.05] * 20)
    labels = ["A"] * 8 + ["B"] * 7 + ["C"] * 5
    assert abs(CASH.normalized_hhi(weights, labels) - CASH.normalized_hhi(.83 * weights, labels)) <= 1e-15


def test_contract_is_frozen_before_economics_and_dual_reference_unchanged() -> None:
    contract = json.loads((MOD.OUT / "gross_scaler_contract.json").read_text(encoding="utf-8"))
    assert contract["gross_floor"] == .80
    assert contract["rule_is_outcome_independent"] is True
    assert contract["no_parameter_search"] is True
    assert contract["economic_outcome_read_count_at_freeze"] == 0
    dual = json.loads(MOD.DUAL_CONTRACT.read_text(encoding="utf-8"))
    assert dual["overlay_contract_hash"] == MOD.EXPECTED_DUAL_CONTRACT_HASH
    assert contract["authoritative_hashes"]["dual_contract_hash"] == dual["overlay_contract_hash"]


def test_completed_arm_and_mechanical_identities() -> None:
    result = json.loads((MOD.OUT / "classification.json").read_text(encoding="utf-8"))
    mechanics = result["mechanics"]
    assert result["raw_reconciliation"] == "PASS_EXACT_1E-12"
    assert result["s1_reconciliation"] == "PASS_EXACT_1E-12"
    assert result["dual_reference_status"] == "PASS_FROZEN_CONTRACT_AND_TARGET_MAP_EXACT_REPLAY"
    assert result["2026_outcome_used"] is False and result["2026_leakage_count"] == 0
    assert mechanics["max_primary_gross_mismatch"] <= 1e-12
    assert mechanics["max_cash_identity_error"] <= 1e-12
    for key in (
        "max_raw_scaled_ff12_normalized_hhi_error", "max_raw_scaled_ff48_normalized_hhi_error",
        "max_s1_scaled_ff12_normalized_hhi_error", "max_s1_scaled_ff48_normalized_hhi_error",
    ):
        assert mechanics[key] <= 1e-12
    arms = pd.read_csv(MOD.OUT / "arm_summary.csv")
    assert set(arms.arm) == {
        "RAW_A2", "S1_SOFT_025", "RAW_CONCENTRATION_GROSS_SCALED",
        "S1_CONCENTRATION_GROSS_SCALED", "DUAL_SECTOR_CASH_REFERENCE",
    }
    assert arms.turnover.notna().all() and arms.cost.notna().all()


def test_paired_seed_and_artifact_hashes_are_deterministic() -> None:
    values = np.cos(np.arange(751, dtype=float)) / 1000.0
    assert CASH.paired_inference(values) == CASH.paired_inference(values)
    manifest = json.loads((MOD.OUT / "hash_manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifact_count_including_manifest"] <= 7
    assert len(list(MOD.OUT.iterdir())) <= 7
    for row in manifest["artifacts"]:
        assert CASH.sha256_file(MOD.OUT / row["name"]) == row["sha256"]
