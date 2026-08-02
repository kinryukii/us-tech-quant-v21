import json

import pandas as pd
import pytest

from generation3_research import _prior_exposure, freeze_contract, sha256_json


def _prior_contract():
    body = {"validation_end": "2026-02-28T23:59:59.999999-05:00", "contract_sha256": "prior"}
    return body


def test_prior_exposure_reclassifies_generation2_roles():
    assert _prior_exposure(pd.Timestamp("2025-04-01"), pd.Series({"generation2_frozen_role": "DEVELOPMENT"})) == "PREVIOUSLY_EXPOSED_DEVELOPMENT"
    assert _prior_exposure(pd.Timestamp("2025-12-01"), pd.Series({"generation2_frozen_role": "VALIDATION"})) == "PREVIOUSLY_EXPOSED_VALIDATION"
    assert _prior_exposure(pd.Timestamp("2024-01-01"), pd.Series({"generation2_data_usage": "PREVIOUSLY_USED_RANDOMIZED_SELECTION"})) == "PREVIOUSLY_EXPOSED_RANDOMIZED_SELECTION"


def test_freeze_contract_is_deterministic_and_confirmation_unread():
    dates = pd.date_range("2020-01-01", "2026-07-31", freq="B", tz="America/New_York")
    first = freeze_contract(dates, _prior_contract())
    second = freeze_contract(dates, _prior_contract())
    assert first["contract_sha256"] == second["contract_sha256"]
    assert first["confirmation_read_count"] == 0
    assert str(first["validation_start"]).startswith("2026-04-01")
    assert str(first["validation_end"]).startswith("2026-05-31")
    assert str(first["confirmation_start"]).startswith("2026-07-01")
    assert first["broker_action_allowed"] is False


def test_freeze_marks_insufficient_confirmation_weekdays_fail_closed():
    dates = pd.date_range("2020-01-01", "2026-07-28", freq="B", tz="America/New_York")
    dates = dates[dates != pd.Timestamp("2026-07-03", tz="America/New_York")]
    contract = freeze_contract(dates, _prior_contract())
    assert contract["terminal_split_feasibility_status"] == "FAIL_INSUFFICIENT_INDEPENDENT_DATA"
    assert contract["confirmation_read_count"] == 0


def test_contract_hash_changes_with_contract_content():
    assert sha256_json({"x": 1}) != sha256_json({"x": 2})
