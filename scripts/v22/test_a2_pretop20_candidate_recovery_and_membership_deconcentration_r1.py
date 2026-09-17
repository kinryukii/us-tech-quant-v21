from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SOURCE = Path(__file__).with_name("a2_pretop20_candidate_recovery_and_membership_deconcentration_r1.py")
SPEC = importlib.util.spec_from_file_location("a2_pretop20_membership_tested", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_fixed_contract_constants_and_delta_hhi() -> None:
    assert MODULE.TOP_N == 20
    assert MODULE.LAMBDA_TOTAL == 0.25
    assert MODULE.FF12_SHARE == MODULE.FF48_SHARE == 0.50
    assert np.isclose(MODULE.marginal_delta_hhi(0.10, 0.05), 0.15**2 - 0.10**2)


def test_sequential_lambda_zero_replays_score_order() -> None:
    frame = pd.DataFrame({
        "ticker": [f"T{number:02d}" for number in range(30)],
        "a2_prediction": np.arange(30, dtype=float),
        "a2_rank": np.arange(30, 0, -1),
        "ff12": [f"S{number % 3}" for number in range(30)],
        "ff48": [f"I{number % 7}" for number in range(30)],
    })
    expected = set(frame.nlargest(20, "a2_prediction").ticker)
    actual = MODULE.select_membership(frame, 0.0)
    assert set(actual) == expected
    assert len(actual) == len(set(actual)) == 20


def test_dynamic_selector_is_deterministic_and_uses_broad_pool() -> None:
    frame = pd.DataFrame({
        "ticker": [f"T{number:02d}" for number in range(35)],
        "a2_prediction": np.linspace(1.0, 0.0, 35),
        "a2_rank": np.arange(1, 36),
        "ff12": ["S0"] * 18 + ["S1"] * 9 + ["S2"] * 8,
        "ff48": ["I0"] * 12 + ["I1"] * 6 + ["I2"] * 9 + ["I3"] * 8,
    })
    first = MODULE.select_membership(frame, 0.25)
    second = MODULE.select_membership(frame.sample(frac=1.0, random_state=7), 0.25)
    assert first == second
    assert len(frame) > 20 and len(first) == 20


def test_frozen_candidate_source_and_exact_top20_replay() -> None:
    pool, top, facts = MODULE.load_candidate_pool()
    assert len(pool) == 312_707
    assert facts["decision_date_count"] == 750
    assert facts["min_candidates"] > 20
    assert facts["top20_mismatch_date_count"] == 0
    assert len(top) == 15_000


def test_no_2026_and_completed_artifact_budget_if_present() -> None:
    if not MODULE.OUT.exists():
        return
    files = [path for path in MODULE.OUT.iterdir() if path.is_file()]
    assert len(files) <= 7
    contract_path = MODULE.OUT / "membership_overlay_contract.json"
    if contract_path.is_file():
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        assert contract["lambda_total"] == 0.25
        assert contract["economic_outcome_read_count_at_freeze"] == 0
        assert contract["2026_outcome_used"] is False
