"""Focused frozen-rule and completed-artifact tests for the 2026 R5 holdout."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).with_name("a2_risk_control_r5_2026_holdout.py")
SPEC = importlib.util.spec_from_file_location("a2_risk_control_r5_2026_holdout", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_frozen_contract_and_deploy_hashes() -> None:
    assert MODULE.sha256_file(MODULE.R5_CONTRACT) == MODULE.R5_CONTRACT_SHA256
    assert MODULE.sha256_file(MODULE.R6_DEPLOY) == MODULE.R6_DEPLOY_SHA256


def test_frozen_rule_has_no_new_degree_of_freedom() -> None:
    r5 = MODULE.load_module("r5_holdout_test_rule", MODULE.REPO / "scripts/v22/a2_risk_control_r5.py")
    assert (r5.RISK_THRESHOLD, r5.HIGH_RISK_MULTIPLIER, r5.NORMAL_MULTIPLIER, r5.MAX_WEIGHT, r5.BASE_COST) == (.90, .50, 1.0, .06, .001)
    weights, _ = r5.waterfill(np.array([.025] * 11 + [.05] * 9))
    assert abs(weights.sum() - 1) <= 2e-15 and weights.max() <= .06 + 1e-14


def test_completed_holdout_identity_if_present() -> None:
    if not (MODULE.OUTPUT / "r5_2026_final_summary.json").is_file():
        return
    summary = json.loads((MODULE.OUTPUT / "r5_2026_final_summary.json").read_text(encoding="utf-8"))
    assert summary["TEST_LABEL"] == MODULE.TEST_LABEL
    assert summary["2026_TRAINING_ROWS"] == 0
    assert summary["2026_PARAMETER_SEARCH_COUNT"] == 0
    assert summary["2026_THRESHOLD_SEARCH_COUNT"] == 0
    assert summary["2026_MODEL_SELECTION_COUNT"] == 0
    gross = pd.read_csv(MODULE.OUTPUT / "r5_2026_daily_gross_identity.csv")
    assert gross.gross_match_error.max() <= 2e-15
    assert (gross.r5_gross <= gross.raw_a2_gross + 2e-15).all()
    assert gross.r5_max_weight.max() <= .06 + 1e-14
