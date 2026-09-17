from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fast4.contracts import HORIZONS, R43A_CONTRACT, RESULTS, load_targets, sha256, verify_contracts  # noqa: E402
from fast4.features import _window_features, quality_audit  # noqa: E402


def test_target_identity_storage_and_secondary_labels() -> None:
    verified = verify_contracts()
    assert sha256(R43A_CONTRACT) == "a5d43651433c6dde50eef791facd02047db2be073a0097acaf31cd1af25d2d6a"
    assert verified["target_contract"]["HORIZONS"] == list(HORIZONS)
    assert verified["target_contract"]["COST_CONTRACT"]["ECONOMIC_COST_BPS"] == 20
    target = load_targets()
    assert len(target) == 1197 and target.candidate_id.is_unique
    assert np.allclose(target.primary_target, target[[f"y_{h}m" for h in HORIZONS]].mean(axis=1))
    assert target.positive_horizon_majority.isin([0, 1]).all()
    assert target.severe_loss.equals(target.primary_target.le(-.01).astype(int))
    assert RESULTS == Path(r"D:\us-tech-quant-results")


def test_deterministic_pit_feature_and_quality_audit() -> None:
    timestamp = pd.date_range("2024-01-02T14:30:00Z", periods=21, freq="min")
    close = np.linspace(100, 102, 21)
    bars = pd.DataFrame({"close": close, "high": close + .1, "low": close - .1, "volume": np.arange(21) + 100}, index=timestamp)
    one = _window_features(bars, 20, 1.0)
    two = _window_features(bars.copy(), 20, 1.0)
    assert one == two
    frame = pd.DataFrame({"candidate_id": ["a", "b", "c"], "decision_timestamp_utc": timestamp[:3], "direction": ["UP"] * 3,
                          "validation_slice": ["x"] * 3, "f1": [1., 2., 3.], "f1_duplicate": [1., 2., 3.], "constant": [1., 1., 1.]})
    clean, audit, families = quality_audit(frame, pd.Series([.1, -.1, .2]))
    assert audit["duplicate_columns"] == {"f1_duplicate": "f1"}
    assert "constant" in audit["constant_columns"] and list(families) == ["f1"]
