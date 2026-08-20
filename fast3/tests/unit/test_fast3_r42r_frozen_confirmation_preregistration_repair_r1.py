from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).parents[2] / "scripts/run/fast3_r42r_frozen_confirmation_preregistration_repair_r1.py"
SPEC = importlib.util.spec_from_file_location("r42r", SCRIPT)
R = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(R)


def test_boundary_assignment_is_lower_inclusive_and_deterministic():
    scores = pd.Series([0.1, 0.2, 0.20001, 0.3, 0.30001, 0.4, 0.40001, 0.5, 0.50001])
    result = R.assign_by_boundaries(scores, [0.2, 0.3, 0.4, 0.5])
    assert result.tolist() == ["Q1", "Q1", "Q2", "Q2", "Q3", "Q3", "Q4", "Q4", "Q5"]


def test_actual_r41_identity_and_boundaries_reproduce_exactly():
    identity, payload = R.reconstruction()
    assert len(identity) == 1197
    assert payload["R41_DISCOVERY_INPUT_COUNT"] == 1197
    assert payload["R41_DISCOVERY_MATCHED_SCORE_COUNT"] == 1197
    assert payload["R41_DISCOVERY_DUPLICATE_COUNT"] == 0
    assert payload["R41_DISCOVERY_MISSING_SCORE_COUNT"] == 0
    for head in ("UP", "DOWN"):
        direction = payload["BOUNDARY_CONTRACT"]["DIRECTIONS"][head]
        assert direction["QUINTILE_ASSIGNMENT_MATCH_RATE"] == 1.0
        assert direction["CROSS_BOUNDARY_TIE_COUNT"] == 0


def test_contract_freezes_primary_horizons_eligibility_blinding_and_ledger_schema():
    _, reconstruction = R.reconstruction()
    contract = R.preregistration("fixed", reconstruction, R.verify_r28_production_identity(), R.payoff_contract())
    assert contract["PRIMARY_DIRECTION"] == "DOWN" and contract["SECONDARY_DIRECTION"] == "UP"
    assert contract["FROZEN_HORIZONS_MINUTES"] == [5, 10, 15, 30, 60]
    assert contract["CONFIRMATION_ACTIVATION_TS"] == "fixed"
    assert contract["ECONOMIC_RESULT_BLINDED_UNTIL_GATE"] is True
    assert contract["SAMPLE_SIZE_GATES"]["DOWN_FIRST_CONFIRMATION_GATE"] == 50
    assert contract["SAMPLE_SIZE_GATES"]["DOWN_SECOND_MILESTONE"] == 100
    assert contract["APPEND_ONLY_CONFIRMATION_LEDGER"] is True
    assert contract["CONFIRMATION_LEDGER_SCHEMA"] == list(R.LEDGER_SCHEMA)
    assert contract["NO_CONFIRMATION_OUTCOME_READ"] is True


def test_source_contains_no_model_or_economic_execution_calls():
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in (".fit(", ".predict(", ".predict_proba(", "GridSearchCV", "RandomizedSearchCV"):
        assert forbidden not in source
    assert '"MODEL_FIT_COUNT": 0' in source
    assert '"MODEL_PREDICT_CALL_COUNT": 0' in source
    assert '"R28_REFIT_COUNT": 0' in source
    assert '"R28_THRESHOLD_CHANGE_COUNT": 0' in source
