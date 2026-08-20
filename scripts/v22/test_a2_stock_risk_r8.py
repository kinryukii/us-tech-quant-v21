from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).with_name("a2_stock_risk_r8.py")
SPEC = importlib.util.spec_from_file_location("a2_stock_risk_r8", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _sample() -> pd.DataFrame:
    return pd.DataFrame({"forward_5d_stock_mae": [.11, .04, .09, .02], "forward_5d_stock_mfe": [.04, .11, .09, .02], "forward_5d_stock_return": [-.03, .03, 0, 0]})


def test_r8_uses_exact_r6_bad_target() -> None:
    assert MODULE.BAD_TARGET_CONTRACT == MODULE.R7.R6_TARGET_CONTRACT
    y = MODULE.target_labels(_sample(), "BAD", .10, .05, .10, .05)
    assert np.array_equal(y, [1, 0, 0, 0])


def test_r8_good_target_is_symmetric_and_frozen() -> None:
    assert MODULE.GOOD_TARGET_CONTRACT["mfe_quantile"] == .90
    assert MODULE.GOOD_TARGET_CONTRACT["mae_compensation_quantile"] == .50
    y = MODULE.target_labels(_sample(), "GOOD", .10, .05, .10, .05)
    assert np.array_equal(y, [0, 1, 0, 0])


def test_r8_uses_exact_r6_temporal_folds() -> None:
    assert MODULE.FOLDS == MODULE.R7.FOLDS == MODULE.R3.FOLDS
    assert MODULE.R3.PURGE_EMBARGO_SESSIONS == 5


def test_r8_no_2026_target_or_return_reads() -> None:
    assert MODULE.TRAINING_CUTOFF == pd.Timestamp("2026-01-01")
    r7 = pd.read_parquet(MODULE.R7_OOF_PATH, columns=["signal_date"])
    assert pd.to_datetime(r7.signal_date).lt(MODULE.TRAINING_CUTOFF).all()


def test_r8_features_are_pit_safe() -> None:
    assert MODULE.MARKET_DIAGNOSTIC_FEATURES == MODULE.R7.FEATURES
    assert set(MODULE.PRIMARY_FEATURES) == set(MODULE.R7.A2_FEATURES + MODULE.R7.STOCK_FEATURES + MODULE.R7.RISK_FEATURES)
    assert not set(MODULE.R7.MARKET_FEATURES) & set(MODULE.PRIMARY_FEATURES)


def test_r8_oof_predictions_are_complete() -> None:
    r7 = pd.read_parquet(MODULE.R7_OOF_PATH, columns=["signal_date", "ticker"])
    assert len(r7) == 12180 and not r7.duplicated(["signal_date", "ticker"]).any()
    assert r7.groupby("signal_date").size().eq(20).all()


def test_r8_bad_good_models_use_fixed_params() -> None:
    assert MODULE.R7.LIGHTGBM_PARAMS["n_estimators"] == 100
    assert MODULE.R7.LOGISTIC_PARAMS["C"] == .3
    assert MODULE.BAD_MODEL_PARAMS_HASH == MODULE.GOOD_MODEL_PARAMS_HASH


def test_r8_no_threshold_search() -> None:
    assert MODULE.QUADRANT_CUT == .20
    assert MODULE.GOOD_TARGET_CONTRACT["mfe_quantile"] == .90
    assert MODULE.GOOD_TARGET_CONTRACT["mae_compensation_quantile"] == .50


def test_r8_dual_score_formula_is_fixed() -> None:
    bad, good = np.array([.8, .2]), np.array([.1, .4])
    assert np.allclose(bad - good, [.7, -.2])
    assert np.allclose(bad / (good + MODULE.DUAL_SCORE_EPSILON), bad / (good + 1e-6))


def test_r8_reproducibility() -> None:
    rng = np.random.default_rng(8); x = pd.DataFrame({"x1": rng.normal(size=400), "x2": rng.normal(size=400)}); y = (x.x1 > 0).astype(int)
    a, b = MODULE.R7.make_model("LIGHTGBM"), MODULE.R7.make_model("LIGHTGBM"); a.fit(x, y); b.fit(x, y)
    assert np.array_equal(a.predict_proba(x), b.predict_proba(x))
