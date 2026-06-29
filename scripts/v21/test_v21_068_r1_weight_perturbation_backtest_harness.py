#!/usr/bin/env python
"""Contract tests for V21.068-R1 weight perturbation harness."""

from __future__ import annotations

import hashlib
import importlib.util
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_068_r1_weight_perturbation_backtest_harness.py"
SPEC = importlib.util.spec_from_file_location("v21_068_r1", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def truth(value: object) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES"}


def test_repository_run() -> None:
    r3_path, _, ledger, source = MODULE.discover_r3(ROOT)
    protected = MODULE.protected_files(ROOT, ROOT / MODULE.OUT_REL, [r3_path, ledger, source])
    before = {path: digest(path) for path in protected}
    result = MODULE.run_stage(ROOT)
    assert not str(result["final_status"]).startswith("BLOCKED_"), result
    output = ROOT / MODULE.OUT_REL
    required = [
        MODULE.UNIVERSE_NAME, MODULE.GRID_NAME, MODULE.RANKINGS_NAME,
        MODULE.METRICS_NAME, MODULE.PAIRWISE_NAME,
        MODULE.RECOMMENDATION_NAME, MODULE.VALIDATION_NAME,
    ]
    assert all((output / name).is_file() for name in required)
    universe = pd.read_csv(output / MODULE.UNIVERSE_NAME, low_memory=False)
    grid = pd.read_csv(output / MODULE.GRID_NAME)
    rankings = pd.read_csv(output / MODULE.RANKINGS_NAME, low_memory=False)
    recommendations = pd.read_csv(output / MODULE.RECOMMENDATION_NAME)
    validation = pd.read_csv(output / MODULE.VALIDATION_NAME).iloc[0]
    assert set(MODULE.UNIVERSE_COLUMNS).issubset(universe.columns)
    assert set(MODULE.GRID_COLUMNS).issubset(grid.columns)
    assert set(MODULE.RANKING_COLUMNS).issubset(rankings.columns)
    assert truth(validation["source_ranking_hash_verified"])
    assert truth(validation["research_only"])
    assert truth(validation["current_d_preserved"])
    assert not truth(validation["ranking_mutation"])
    assert not truth(validation["official_mutation"])
    assert not truth(validation["protected_outputs_modified"])
    assert not truth(validation["forward_ledger_mutation"])
    assert len(universe) == int(validation["ranking_rows"])
    assert grid["perturbation_id"].eq("P00_CURRENT_D").any()
    assert not grid["diagnostic_qqq_ma50_used_in_score"].map(truth).any()
    assert not grid["diagnostic_liquidity_used_in_score"].map(truth).any()
    assert not recommendations["official_adoption_allowed"].map(truth).any()
    assert not recommendations["adoption_allowed"].map(truth).any()
    assert truth(validation["pass_gate"])
    assert str(validation["final_status"]).startswith(("PASS_", "PARTIAL_PASS_"))
    assert before == {path: digest(path) for path in protected}


def test_source_hash_mismatch_blocked() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        r3_path, _, _, _ = MODULE.discover_r3(ROOT)
        fake = pd.read_csv(r3_path)
        fake.loc[0, "source_ranking_hash"] = "0" * 64
        fake_path = Path(temporary) / "r3.csv"
        fake.to_csv(fake_path, index=False)
        result = MODULE.run_stage(ROOT, fake_path, Path(temporary) / "output")
        assert result["final_status"] == "BLOCKED_V21_068_R1_SOURCE_HASH_MISMATCH"


def test_missing_r3_blocked() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        result = MODULE.run_stage(
            ROOT, Path(temporary) / "missing.csv", Path(temporary) / "output"
        )
        assert result["final_status"] == "BLOCKED_V21_068_R1_MISSING_R3_OR_SOURCE_RANKING"


def test_future_evaluation_blocked() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        future = Path(temporary) / "future.csv"
        pd.DataFrame([{
            "batch_id": "X", "sampled_as_of_date": "2999-01-01",
            "momentum_weight": 0.4, "top_n_bucket": "TOP20",
            "forward_window": "5D", "ticker": "X", "rank": 1, "score": 1,
            "base_score": 1, "momentum_score": 1,
            "net_position_return": 0.1, "benchmark_spy_return": 0,
            "benchmark_qqq_return": 0, "benchmark_smh_return": 0,
            "point_in_time_valid": True, "research_only": True,
        }]).to_csv(future, index=False)
        result = MODULE.run_stage(
            ROOT, output_override=Path(temporary) / "output",
            evaluation_override=future,
        )
        assert result["final_status"] == "BLOCKED_V21_068_R1_SCORE_RECONSTRUCTION_OR_EVALUATION_RISK"


if __name__ == "__main__":
    test_repository_run()
    test_source_hash_mismatch_blocked()
    test_missing_r3_blocked()
    test_future_evaluation_blocked()
    print("PASS test_v21_068_r1_weight_perturbation_backtest_harness")
