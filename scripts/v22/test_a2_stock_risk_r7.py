from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).with_name("a2_stock_risk_r7.py")
SPEC = importlib.util.spec_from_file_location("a2_stock_risk_r7", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_r7_no_2026_training_or_target_reads() -> None:
    assert MODULE.TRAINING_CUTOFF == pd.Timestamp("2026-01-01")
    assert list(range(2019, 2026))[-1] == 2025
    assert "2026" not in str(MODULE.R6_OOF_PATH.name)


def test_r7_reuses_exact_r6_target_contract() -> None:
    assert MODULE.R6_TARGET_CONTRACT["mae_quantile"] == MODULE.R6.MAE_SEVERE_QUANTILE == 0.90
    assert MODULE.R6_TARGET_CONTRACT["mfe_quantile"] == MODULE.R6.MFE_COMPENSATION_QUANTILE == 0.50
    frame = pd.DataFrame({"forward_5d_stock_mae": [.11, .11, .09], "forward_5d_stock_mfe": [.04, .06, .04], "forward_5d_stock_return": [-.01, -.01, -.01]})
    target, _ = MODULE.R6.event_labels(frame, .10, .05)
    assert np.array_equal(target, [1, 0, 0])


def test_r7_reuses_exact_r6_temporal_folds() -> None:
    assert MODULE.FOLDS == list(MODULE.R6.R3.FOLDS) == list(MODULE.R1.FOLDS)
    assert MODULE.R3.PURGE_EMBARGO_SESSIONS == 5


def test_r7_market_features_are_backward_looking_only() -> None:
    dates = pd.bdate_range("2020-01-01", periods=320)
    pieces = []
    for i, ticker in enumerate(["QQQ", "SPY", "SOXX"]):
        pieces.append(pd.DataFrame({"ticker": ticker, "trade_date": dates, "close": 100 + i + np.arange(len(dates)) * .1}))
    prices = pd.concat(pieces, ignore_index=True)
    vix = pd.DataFrame({"market_date": dates, "vix_close": 20 + np.sin(np.arange(len(dates)) / 20)})
    first = MODULE.build_market_state(prices, vix)
    prices.loc[prices.trade_date.eq(dates[-1]), "close"] *= 3
    second = MODULE.build_market_state(prices, vix)
    cols = [c for c in MODULE.MARKET_FEATURES]
    assert np.allclose(first.iloc[:-1][cols], second.iloc[:-1][cols], equal_nan=True)


def test_r7_r3_r6_inputs_are_oof_not_insample() -> None:
    assert MODULE.R1.sha256_file(MODULE.R6_OOF_PATH) == MODULE.R6_OOF_SHA256
    assert MODULE.R1.sha256_file(MODULE.R3R_OOF_PATH) == MODULE.R3_OOF_SHA256
    r6 = pd.read_parquet(MODULE.R6_OOF_PATH, columns=["signal_date", "ticker", "candidate_id"])
    r3 = pd.read_parquet(MODULE.R3R_OOF_PATH, columns=["signal_date", "ticker", "candidate_id"])
    r6 = r6[r6.candidate_id.eq(MODULE.R6_REFERENCE_MODEL)][["signal_date", "ticker"]].sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    r3 = r3[r3.candidate_id.eq(MODULE.R3_REFERENCE_MODEL)][["signal_date", "ticker"]].sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    assert r6.equals(r3)


def test_r7_oof_rows_unique_and_complete() -> None:
    r6 = pd.read_parquet(MODULE.R6_OOF_PATH, columns=["signal_date", "ticker", "candidate_id"])
    selected = r6[r6.candidate_id.eq(MODULE.R6_REFERENCE_MODEL)]
    assert len(selected) == 12180
    assert not selected.duplicated(["signal_date", "ticker"]).any()
    assert selected.groupby("signal_date").size().eq(20).all()


def test_r7_no_parameter_or_threshold_search() -> None:
    assert set(MODULE.ABLATIONS) == {"A_R6_ONLY", "B_R6_PLUS_R3", "C_R6_PLUS_MARKET_STATE", "D_R6_PLUS_STOCK_A2_STATE", "E_FULL_R7"}
    assert MODULE.LIGHTGBM_PARAMS["n_estimators"] == 100
    assert MODULE.LOGISTIC_PARAMS["C"] == 0.3
    assert len(MODULE.FEATURES) == len(set(MODULE.FEATURES))


def test_r7_reproducible_predictions() -> None:
    rng = np.random.default_rng(7)
    x = pd.DataFrame({"x1": rng.normal(size=500), "x2": rng.normal(size=500)})
    y = (x.x1 + .2 * x.x2 > 0).astype(int)
    a, b = MODULE.make_model("LIGHTGBM"), MODULE.make_model("LIGHTGBM")
    a.fit(x, y); b.fit(x, y)
    assert np.array_equal(a.predict_proba(x), b.predict_proba(x))
