"""Meaningful temporal isolation and covariance/diagnostic interface checks."""
import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

SPEC = importlib.util.spec_from_file_location("new_risk_aux", Path(__file__).with_name("risk_aux.py"))
risk = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(risk)


def test_validation_prices_ignore_future_values():
    dates = pd.bdate_range("2023-10-01", "2025-06-01")
    p = pd.DataFrame({"trade_date": np.repeat(dates, 5), "ticker": np.tile(list("ABCDE"), len(dates)),
                      "close": np.exp(np.arange(len(dates) * 5) * .0001)})
    before = risk.returns_before(p, "2025-01-01")
    p.loc[p.trade_date.ge("2025-01-01"), "close"] = np.nan
    pd.testing.assert_frame_equal(before, risk.returns_before(p, "2025-01-01"))
    assert len(before) == 252 and before.index.max() < pd.Timestamp("2025-01-01")


def test_sampling_is_order_independent_and_stage_isolated():
    frame = pd.DataFrame({"signal_date": pd.to_datetime(["2024-01-02", "2024-01-02", "2024-12-30", "2025-01-02"]),
                          "ticker": ["A", "B", "C", "D"], "outcome": [1., 2., 3., 4.]})
    first = risk.sample_by_key(frame, "2025-01-01", limit=2)
    frame["outcome"] *= -999
    second = risk.sample_by_key(frame.iloc[::-1], "2025-01-01", limit=2)
    assert first.ticker.tolist() == second.ticker.tolist()
    assert "D" not in first.ticker.tolist()


@pytest.mark.parametrize("stage", list(risk.STAGES))
def test_frozen_covariance_and_unknown_fallback(stage):
    model = risk.FrozenRisk(stage)
    names = list(model.lookup)[:12] + ["__UNKNOWN_SECURITY__"]
    for factor in [False, True]:
        cov = model.covariance_for(names, factor=factor)
        assert cov.shape == (13, 13) and np.isfinite(cov).all()
        np.testing.assert_allclose(cov, cov.T, atol=1e-14)
        assert np.linalg.eigvalsh(cov).min() > 0
        np.testing.assert_allclose(cov[-1, :-1], 0)
        assert cov[-1, -1] == risk.UNKNOWN_DAILY_VOL ** 2
        assert model.covariance_for([], factor=factor).shape == (0, 0)
    receipt = model.receipt
    assert receipt["risk"]["return_last"] < risk.STAGES[stage]
    assert receipt["diagnostics"]["sample_last"] < risk.STAGES[stage]
    assert receipt["risk"]["return_rows"] == 252


@pytest.mark.parametrize("stage", list(risk.STAGES))
def test_diagnostic_predict_is_frozen_and_does_not_trade(stage):
    model = risk.FrozenDiagnostics(stage)
    columns = model.bundle["features"]
    frame = pd.read_parquet(risk.FEATURE_SOURCE, columns=["signal_date", *columns]).head(8)
    hashes_before = {p.name: risk.sha(p) for p in (risk.OUT / stage).glob("*.*")}
    result = model.predict(frame)
    assert list(result.columns) == ["cluster", "anomaly_score", "is_anomaly"]
    assert len(result) == len(frame) and result.cluster.between(0, 4).all()
    assert np.isfinite(result.anomaly_score).all()
    assert hashes_before == {p.name: risk.sha(p) for p in (risk.OUT / stage).glob("*.*")}
    bad = frame.copy()
    bad.loc[bad.index[0], columns[0]] = np.nan
    with pytest.raises(ValueError, match="NONFINITE"):
        model.predict(bad)


def test_stage_objects_are_distinct_and_invalid_stage_rejected():
    validation = risk.FrozenRisk("validation")
    final = risk.FrozenRisk("final")
    # 2025 has only 250 sessions in the source, so its 252-return window
    # legitimately overlaps the final two 2024 days. Each cutoff remains strict.
    assert validation.receipt["risk"]["return_last"] < final.receipt["risk"]["return_last"]
    assert validation.receipt["risk"]["return_first"] < final.receipt["risk"]["return_first"]
    assert validation.receipt["artifacts_sha256"]["frozen_covariance.npz"] != final.receipt["artifacts_sha256"]["frozen_covariance.npz"]
    with pytest.raises(ValueError, match="UNKNOWN_STAGE"):
        risk.FrozenRisk("test2026")
