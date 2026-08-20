from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest


MODULE_PATH = Path(r"D:\us-tech-quant\fast3\src\fast3\options\option_risk_overlay_r1.py")
spec = importlib.util.spec_from_file_location("option_risk_overlay_r1", MODULE_PATH)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)


def test_pit_rejects_future_quotes_and_same_day_final_oi() -> None:
    decision = datetime(2026, 8, 11, 14, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="future"):
        m.assert_pit_quote(decision + timedelta(seconds=1), decision)
    with pytest.raises(ValueError, match="same-day"):
        m.assert_previous_completed_day_oi(date(2026, 8, 11), decision)
    m.assert_previous_completed_day_oi(date(2026, 8, 10), decision)


def test_constant_maturity_and_expanding_percentile_are_deterministic_and_historical_only() -> None:
    points = [m.ConstantMaturityPoint(20, .20), m.ConstantMaturityPoint(40, .30)]
    assert m.constant_maturity_iv(points, 30) == pytest.approx((2.2 / 30) ** .5)
    now = datetime(2026, 8, 11, tzinfo=timezone.utc)
    history = [(now - timedelta(days=index + 1), float(index)) for index in range(60)] + [(now, 999.0)]
    assert m.expanding_percentile(history, now, 30.0) == pytest.approx(31 / 60)


def test_overlay_cannot_reverse_direction_or_amplify_and_missing_is_no_override() -> None:
    unavailable = m.overlay_action("UP", None)
    assert unavailable["position_multiplier"] == 1.0
    assert unavailable["effective_direction"] == "UP"
    for direction in ("UP", "DOWN"):
        for action, multiplier in {"NORMAL": 1.0, "REDUCED": .5, "VETO": 0.0}.items():
            result = m.overlay_action(direction, action)
            assert result["position_multiplier"] == multiplier
            assert result["effective_direction"] == direction
            m.validate_overlay_result(result)
    with pytest.raises(ValueError):
        m.validate_overlay_result({"fast3_direction": "UP", "effective_direction": "DOWN", "position_multiplier": 1.0})


def test_contract_has_no_model_fit_or_fast3_mutation_surface() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    runner = Path(r"D:\us-tech-quant\fast3\scripts\audit\run_fast3_option_risk_overlay_r1.py").read_text(encoding="utf-8")
    assert ".fit(" not in source
    assert "HistGradientBoosting" not in source
    assert "RISK_ACTION_MULTIPLIERS" in source
    assert ".fit(" not in runner
    assert "R42R.write" not in runner and "R43A.write" not in runner
    assert '"R28_PROSPECTIVE_LINE_ISOLATION": True' in runner
