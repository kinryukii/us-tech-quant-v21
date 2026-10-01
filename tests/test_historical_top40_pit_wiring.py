"""Independent inference-boundary checks for dated identity snapshots."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("historical_runner_pit_under_test",
    ROOT / "scripts/research/a2/inference/historical_top40.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def example(tmp_path, *, day="2026-09-22"):
    model_path = tmp_path / "model.bin"
    model_path.write_bytes(b"synthetic deterministic model")
    models = {"artifacts": {"2026": {"path": str(model_path), "sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
                                      "labelmax": "2025-12-01"}}}
    schedule = pd.DataFrame([{"snapshot_id": "current", "universe_id": "membership", "quarter": "2026Q2",
        "effective_date": "2026-09-10", "snapshot_effective_date": "2026-09-22", "institution_count": 25,
        "universe_member_count": 3, "mapped_count": 2}])
    members = pd.DataFrame([{"snapshot_id": "current", "security_id": code, "ticker": ticker}
                            for code, ticker in [("a", "AAA"), ("b", "BBB"), ("unknown", None)]])
    ledger = pd.DataFrame([{"target_date": day, "snapshot_id": "current"}])
    features = pd.DataFrame([{"trade_date": day, "ticker": ticker, "feature": 2.0} for ticker in ["BBB", "AAA"]])
    class Model:
        def predict(self, values):
            return np.ones(len(values))
    return features, schedule, members, ledger, models, ["feature"], lambda _: Model()


def test_future_identity_rejected_despite_already_effective_membership(tmp_path):
    with pytest.raises(ValueError, match="FUTURE_UNIVERSE_IDENTITY_SNAPSHOT"):
        runner.ranked_predictions(*example(tmp_path, day="2026-09-21"))


def test_current_snapshot_partial_pool_has_explicit_coverage_and_stable_ties(tmp_path):
    ranks, coverage = runner.ranked_predictions(*example(tmp_path))
    assert ranks.ticker.tolist() == ["AAA", "BBB"]
    assert ranks["rank"].tolist() == [1, 2]
    assert coverage.iloc[0].status == "PARTIAL"
    assert coverage.iloc[0].eligible_count == 2
    assert coverage.iloc[0].universe_member_count == 3
    assert coverage.iloc[0].excluded_count == 1
    assert ranks.universe_effective_date.eq("2026-09-10").all()
