import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


RUNNER = Path(__file__).parents[2] / "scripts/run/fast3_r36_frozen_prospective_tail_risk_guard_validation.py"
spec = importlib.util.spec_from_file_location("r36_tail", RUNNER)
r36 = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(r36)


def test_r36_frozen_prospective_guard_contract() -> None:
    assert not r36.is_legal_r36_timestamp("2026-08-12T00:00:00Z", "2026-08-12T00:00:00Z")
    assert r36.is_legal_r36_timestamp("2026-08-12T00:00:00.000001Z", "2026-08-12T00:00:00Z")

    source = pd.DataFrame({"direction": ["UP"] * 5 + ["DOWN"] * 5, "expected_payoff_raw": list(range(5)) * 2})
    assert r36.outcome_blind_cutpoints(source) == {"UP": [0.8, 1.6, 2.4, 3.2], "DOWN": [0.8, 1.6, 2.4, 3.2]}
    assert list(source.columns) == ["direction", "expected_payoff_raw"]

    p, t5, t6 = np.array([0.25]), np.array([np.log1p(0.2)]), np.array([np.log1p(0.4)])
    assert np.isclose(r36.score(p, t5, t6)[0], 0.25 * 0.4 - 0.75 * 0.2)
    assert r36.FORMULA == "p*gain_magnitude-(1-p)*loss_magnitude"

    cuts = [1.0, 2.0, 3.0, 4.0]
    assert [r36.bucket_for(x, cuts) for x in [0, 1, 1.1, 2, 3, 4, 5]] == ["Q1", "Q1", "Q2", "Q2", "Q3", "Q4", "Q5"]
    assert r36.bucket_for(-999, cuts) == "Q1" and r36.bucket_for(999, cuts) == "Q5"
    assert r36.SEVERE_LOSS_THRESHOLD == -0.05

    small = pd.DataFrame({"direction": ["UP", "DOWN"], "frozen_direction_quantile_bucket": ["Q1", "Q5"], "trading_date": ["a", "b"]})
    assert r36.sample_gate(small)[0] is False
    enough = pd.DataFrame({
        "direction": ["UP"] * 1000 + ["DOWN"] * 1000,
        "frozen_direction_quantile_bucket": ["Q1"] * 250 + ["Q5"] * 250 + ["Q3"] * 1500,
        "trading_date": [str(i % 10) for i in range(2000)],
    })
    assert r36.sample_gate(enough)[0] is True

    assert r36.primary_signs(
        {"P05": -0.2, "WORST_5PCT_MEAN": -0.3, "SEVERE_LOSS_5PCT_RATE": 0.2},
        {"P05": -0.1, "WORST_5PCT_MEAN": -0.2, "SEVERE_LOSS_5PCT_RATE": 0.1},
    ) == (True, True, True)

    assert r36.PROTECTED_FLAGS["R36_GUARD_ENFORCEMENT_ENABLED"] is False
    assert r36.PROTECTED_FLAGS["R36_CAN_BLOCK_TRADE"] is False
    assert r36.PROTECTED_FLAGS["FAST3_R34R_PROSPECTIVE_CHANGED"] is False
    assert r36.PROTECTED_FLAGS["FAST3_BASE_MODEL_CHANGED"] is False
    assert r36.PROTECTED_FLAGS["MODEL_FIT_COUNT"] == 0
    assert r36.PROTECTED_FLAGS["MODEL_PREDICT_CALL_COUNT"] == 0
    assert r36.PROTECTED_FLAGS["BROKER_ACTION_ALLOWED"] is False

    option_source = (Path(__file__).parents[2] / "scripts/audit/run_fast3_moomoo_option_data_acquisition_r1.py").read_text(encoding="utf-8")
    assert 'path.open("a", encoding="utf-8")' in option_source
    assert "OPTION_SURFACE_RETROACTIVE_BACKFILL_COUNT" not in option_source
    assert r36.option_quality_status()["OPTION_SURFACE_RETROACTIVE_BACKFILL_COUNT"] == 0
