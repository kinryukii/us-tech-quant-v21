import importlib.util
from pathlib import Path

import pandas as pd
import pytest


SOURCE = Path(__file__).parents[2] / "scripts" / "run" / "fast3_r28_phase3_frozen_validation.py"
SPEC = importlib.util.spec_from_file_location("r28_phase3", SOURCE)
P3 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P3)


def ledger():
    stamp = pd.Timestamp("2026-08-09T14:30:00Z")
    return pd.DataFrame({"candidate_id": ["QQQ|UP|" + str(stamp), "QQQ|DOWN|" + str(stamp)],
                         "underlying_symbol": ["QQQ", "QQQ"], "direction": ["UP", "DOWN"],
                         "decision_timestamp_utc": [stamp, stamp]})


def test_outcome_key_is_directionless_but_candidate_identity_is_not():
    keys = P3.outcome_key(ledger())
    assert keys.nunique() == 1
    assert ledger().candidate_id.nunique() == 2


def test_join_maps_one_label_to_both_independent_heads_without_row_loss():
    x, audit = P3.join_outcomes(ledger(), pd.DataFrame({"outcome_key": [P3.outcome_key(ledger()).iloc[0]], "first_touch_label": ["UP"]}))
    assert len(x) == 2 and audit["unmatched_row_count"] == 0 and audit["duplicate_candidate_count"] == 0
    assert x.first_touch_label.tolist() == ["UP", "UP"]


def test_duplicate_label_key_is_rejected_before_many_to_many_merge():
    key = P3.outcome_key(ledger()).iloc[0]
    with pytest.raises(ValueError, match="LABEL_OUTCOME_KEY_DUPLICATE"):
        P3.join_outcomes(ledger(), pd.DataFrame({"outcome_key": [key, key], "first_touch_label": ["UP", "UP"]}))


def test_unmatched_rows_are_diagnosed_and_rejected_without_silent_drop():
    with pytest.raises(ValueError, match="OUTCOME_JOIN_CONSERVATION_FAILURE"):
        P3.join_outcomes(ledger(), pd.DataFrame({"outcome_key": ["SOXX|2026-08-09 14:30:00+00:00"], "first_touch_label": ["UP"]}))
