from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fast5 import option_pilot_r1 as pilot  # noqa: E402


def test_frozen_contracts_and_target_blind_covered_cohort() -> None:
    cfg = pilot.config()
    assert pilot.sha(pilot.D1 / "FAST5_DATA_R1_OPTION_FEATURE_CONTRACT.json") == cfg["option_feature_contract_sha256"]
    assert pilot.sha(pilot.TARGET_CONTRACT) == cfg["target_sha256"]
    cohort = pilot.covered_metadata()
    assert len(cohort) == 402
    assert {"candidate_id", "decision_timestamp_utc", "underlying", "direction"}.issubset(cohort)
    assert not any("target" in column or column.startswith("y_") for column in cohort)


def test_option_features_are_contract_limited_and_past_only() -> None:
    cohort = pilot.covered_metadata()
    values = pilot.option_features(cohort)
    assert len(values) == len(cohort)
    assert values.columns[0] == "candidate_id"
    assert len(values.columns) - 1 == 12
    assert not any(token in column.lower() for column in values.columns for token in ("open_interest", "iv", "delta", "gamma", "theta", "vega"))
    assert values.candidate_id.equals(cohort.candidate_id)
