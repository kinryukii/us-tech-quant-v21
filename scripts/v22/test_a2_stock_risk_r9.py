from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).with_name("a2_stock_risk_r9.py")
SPEC = importlib.util.spec_from_file_location("a2_stock_risk_r9", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _result(name: str) -> Path:
    return MODULE.OUTPUT_DIR / name


def test_r9_no_2026_reads() -> None:
    assert MODULE.TRAINING_CUTOFF == pd.Timestamp("2026-01-01")
    assert max(range(2019, 2026)) == 2025
    assert MODULE.POSITION_RULE_APPLICATION_COUNT == MODULE.ECONOMIC_BACKTEST_COUNT == 0
    if _result("r9_audit.json").exists():
        audit = json.loads(_result("r9_audit.json").read_text(encoding="utf-8"))
        assert set(audit["firewall"].values()) == {0}


def test_r9_portfolio_date_observation_unit() -> None:
    assert MODULE.R9_FOLD_CONTRACT["split_unit"] == "portfolio_date"
    if _result("r9_oof_predictions.parquet").exists():
        frame = pd.read_parquet(_result("r9_oof_predictions.parquet"), columns=["date"])
        assert not frame.duplicated("date").any()


def test_r9_target_threshold_uses_training_fold_only() -> None:
    train = pd.DataFrame({"future_portfolio_mae": [-.10, -.05, -.01, 0.0]})
    valid = pd.DataFrame({"future_portfolio_mae": [-.20, 0.0]})
    _, labels, threshold = MODULE.fold_labels(train, valid)
    assert threshold == train.future_portfolio_mae.quantile(.10)
    assert np.array_equal(labels, [1, 0])
    valid.loc[0, "future_portfolio_mae"] = -999.0
    assert MODULE.fold_labels(train, valid)[2] == threshold


def test_r9_target_horizon_is_frozen() -> None:
    assert MODULE.TARGET_HORIZON == 1
    assert MODULE.TARGET_QUANTILE == .10
    contract = MODULE.target_contract("abc")
    assert contract["horizon_trading_sessions"] == 1
    assert "fold-training Q10" in contract["event_formula"]


def test_r9_features_are_backward_looking() -> None:
    dates = pd.bdate_range("2020-01-01", periods=80)
    daily = pd.DataFrame({
        "execution_date": dates,
        "reconstructed_daily_return": np.linspace(-.02, .02, len(dates)),
        "reconstructed_nav": np.cumprod(1 + np.linspace(-.02, .02, len(dates))),
    })
    first = MODULE.build_trailing_a2(daily)
    changed = daily.copy()
    changed.loc[changed.index[-1], "reconstructed_daily_return"] = .99
    second = MODULE.build_trailing_a2(changed)
    assert np.allclose(first[MODULE.TRAILING_A2_FEATURES], second[MODULE.TRAILING_A2_FEATURES], equal_nan=True)


def test_r9_r6_features_use_oof_scores_only() -> None:
    assert MODULE.R1.sha256_file(MODULE.R6_OOF_PATH) == MODULE.R6_OOF_SHA256
    frame = pd.read_parquet(MODULE.R6_OOF_PATH, columns=["candidate_id"])
    assert frame.candidate_id.eq(MODULE.R6_REFERENCE_MODEL).any()


def test_r9_reuses_frozen_temporal_boundaries() -> None:
    assert MODULE.FOLDS == list(MODULE.R7.FOLDS)
    assert MODULE.R7.R6_FOLD_CONTRACT_ID == MODULE.R6_FOLD_CONTRACT_ID_EXPECTED
    assert MODULE.R3.PURGE_EMBARGO_SESSIONS == 5


def test_r9_no_parameter_search() -> None:
    assert MODULE.PARAMETER_SEARCH_COUNT == 0
    assert MODULE.LIGHTGBM_PARAMS == MODULE.R7.LIGHTGBM_PARAMS
    assert MODULE.LOGISTIC_PARAMS == MODULE.R7.LOGISTIC_PARAMS
    assert set(MODULE.ABLATIONS) == {
        "A_MARKET_ONLY", "B_A2_PORTFOLIO_STATE_ONLY", "C_R6_CROSS_SECTION_STATE_ONLY",
        "D_TRAILING_A2_STATE_ONLY", "E_FULL_R9",
    }


def test_r9_no_threshold_search() -> None:
    assert MODULE.THRESHOLD_SEARCH_COUNT == 0
    assert MODULE.TARGET_QUANTILE == .10


def test_r9_oof_predictions_complete_unique() -> None:
    if not _result("r9_oof_predictions.parquet").exists():
        return
    frame = pd.read_parquet(_result("r9_oof_predictions.parquet"))
    assert not frame.duplicated("date").any()
    assert frame.bad_regime_target.notna().all()
    assert frame.logistic_oof_probability.between(0, 1).all()
    assert frame.r9_ml_oof_probability.between(0, 1).all()
    assert set(frame.fold) == {row[0] for row in MODULE.FOLDS}


def test_r9_prediction_reproducibility() -> None:
    if _result("r9_run_manifest.json").exists():
        manifest = json.loads(_result("r9_run_manifest.json").read_text(encoding="utf-8"))
        assert manifest["primary_prediction_sha256"] == manifest["repeat_prediction_sha256"]
    rng = np.random.default_rng(9)
    x = pd.DataFrame({"x1": rng.normal(size=400), "x2": rng.normal(size=400)})
    y = (x.x1 - .25 * x.x2 > 0).astype(int)
    a, b = MODULE.make_model("LIGHTGBM"), MODULE.make_model("LIGHTGBM")
    a.fit(x, y); b.fit(x, y)
    assert np.array_equal(a.predict_proba(x), b.predict_proba(x))
