from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(r"D:\us-tech-quant\scripts\v22\a2_risk_os_r1.py")
spec = importlib.util.spec_from_file_location("a2_risk_os_r1_tested", SCRIPT)
assert spec and spec.loader
R = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = R
spec.loader.exec_module(R)


def _json(name: str):
    return json.loads((R.OUTPUT / name).read_text(encoding="utf-8"))


def test_frozen_a2_and_r6_identity_unchanged():
    identity = R.frozen_identity()
    assert identity["r6_oof_sha256"] == R.R6_OOF_SHA256
    assert identity["r6_deploy_sha256"] == R.R6_DEPLOY_SHA256
    assert identity["r6_2026_model_fit_rows"] == 0


def test_contract_preregistered_and_contains_no_search():
    contract = _json("risk_os_r1_contract.json")
    assert contract["training_cutoff_exclusive"] == "2026-01-01"
    assert contract["learned_model_count"] == 0
    assert contract["feature_selection_count"] == 0
    assert contract["parameter_search_count"] == 0
    assert contract["threshold_search_count"] == 0


def test_pit_timestamps_and_no_2026_training():
    weights = pd.read_parquet(R.OUTPUT / "risk_os_r1_weight_attribution.parquet")
    audit = _json("risk_os_r1_audit.json")
    assert weights.information_date.lt(weights.signal_date).all()
    assert weights.signal_date.lt(pd.Timestamp("2026-01-01")).all()
    assert audit["2026_TRAINING_ROW_COUNT"] == 0
    assert audit["LOOKAHEAD_VIOLATION_COUNT"] == 0


def test_r6_mapping_is_exact_frozen_sparse_rule():
    weights = pd.read_parquet(R.OUTPUT / "risk_os_r1_weight_attribution.parquet")
    expected = np.where(weights.risk_percentile.ge(.90), .50, 1.0)
    assert np.array_equal(expected, weights.r6_multiplier.to_numpy())


def test_weight_attribution_and_hard_cap():
    weights = pd.read_parquet(R.OUTPUT / "risk_os_r1_weight_attribution.parquet")
    assert weights.final_weight.between(0, .06).all()
    normal = weights.hard_limit_component.notna()
    expected = np.minimum(.06, weights.uncertainty_adjusted_weight * weights.hard_limit_component)
    bypass = weights.final_weight.eq(weights.base_a2_weight) & ~np.isclose(weights.final_weight, expected)
    assert np.allclose(weights.loc[normal & ~bypass, "final_weight"], expected.loc[normal & ~bypass])


def test_missing_geometry_fails_closed_to_existing_a2_weight():
    geometry = pd.read_parquet(R.OUTPUT / "risk_os_r1_portfolio_geometry.parquet")
    weights = pd.read_parquet(R.OUTPUT / "risk_os_r1_weight_attribution.parquet")
    bad_dates = set(geometry.loc[geometry.NO_NEW_RISK, "signal_date"])
    assert bad_dates
    affected = weights.loc[weights.signal_date.isin(bad_dates)]
    assert np.allclose(affected.final_weight, affected.base_a2_weight)


def test_matched_exposure_is_exact():
    audit = _json("risk_os_r1_audit.json")
    assert audit["matched_exposure_absolute_difference"] < 1e-12


def test_stress_scenarios_are_deterministic():
    geometry = pd.read_parquet(R.OUTPUT / "risk_os_r1_portfolio_geometry.parquet")
    first = R.stress_scenarios(geometry)
    second = R.stress_scenarios(geometry)
    pd.testing.assert_frame_equal(first, second, check_exact=True)
    assert {"SPX_2PCT", "NASDAQ_10PCT", "VIX_PLUS_100PCT", "CORRELATION_FLOOR_70", "COMBINED_SPX4_SOXX8_VIX50_CORR70"}.issubset(set(first.scenario))


def test_classification_stops_before_new_prospective_read():
    summary = _json("risk_os_r1_summary.json")
    audit = _json("risk_os_r1_audit.json")
    assert summary["A2_RISK_OS_R1_CLASSIFICATION"] == "E_INSUFFICIENT_AUTHORITATIVE_GEOMETRY_COVERAGE"
    assert summary["prospective_authorized"] is False
    assert audit["2026_RISK_OS_OUTCOME_READ_COUNT"] == 0


def test_external_storage_and_no_large_repo_artifact():
    assert str(R.OUTPUT).startswith(r"D:\us-tech-quant-results")
    assert SCRIPT.stat().st_size < 10 * 1024 * 1024
    assert not (R.REPO / ".venv").exists()


def test_contract_freeze_is_idempotent():
    witness = R.freeze_contract(R.OUTPUT)
    assert witness["contract_sha256"] == R.sha256_file(R.OUTPUT / "risk_os_r1_contract.json")


def test_full_replay_is_reproducible():
    weights = pd.read_parquet(R.OUTPUT / "risk_os_r1_weight_attribution.parquet")
    positions = pd.read_parquet(R.R3.POSITION_LEDGER_PATH, columns=["date", "ticker", "raw_return"])
    positions["date"] = pd.to_datetime(positions.date)
    targets = R.target_maps(weights, "final_weight")
    first = R.simulate(targets, positions, R.BASE_COST)
    second = R.simulate(targets, positions, R.BASE_COST)
    pd.testing.assert_frame_equal(first, second, check_exact=True)
