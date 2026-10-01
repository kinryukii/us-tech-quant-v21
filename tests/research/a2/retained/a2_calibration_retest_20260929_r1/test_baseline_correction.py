"""No training: legal-history checks, bit preservation, frozen nonlinear fusion."""
import sys
sys.dont_write_bytecode = True
import ast
from dataclasses import dataclass
from pathlib import Path
import types

import numpy as np
import pandas as pd
import pytest

import baseline_correction as bc


def frame():
    return pd.DataFrame({"signal_date": pd.to_datetime(["2024-01-02", "2024-01-02", "2024-01-03"]),
        "ticker": ["A", "B", "A"], "label_end_date": pd.to_datetime(["2024-01-04", "2024-01-04", "2024-01-05"]),
        "y_next_open": [.01, .03, -.02]})


def receipt():
    return {"oof_first": "2024-01-01", "oof_last_exclusive": "2025-01-01",
            "base_fit_cutoff_exclusive": "2024-01-01", "rows": 3}


def test_equal_date_full_population_and_old_rows_retained():
    first = frame()
    assert bc.equal_date_mean(first) == pytest.approx(0., abs=1e-16)
    assert first.y_next_open.mean() != bc.equal_date_mean(first)
    next_year = pd.DataFrame({"signal_date": pd.to_datetime(["2025-01-02"]), "ticker": ["C"],
        "label_end_date": pd.to_datetime(["2025-01-06"]), "y_next_open": [.06]})
    full = pd.concat([first, next_year], ignore_index=True)
    assert len(full) == len(first) + len(next_year)
    assert full.iloc[:len(first)].reset_index(drop=True).equals(first)
    assert bc.equal_date_mean(full) == pytest.approx(.02)
    assert bc.historical_sample(full).equals(bc.historical_sample(full))


@pytest.mark.parametrize("defect", ["duplicate", "label_boundary", "future_signal", "overlap", "nan_target"])
def test_illegal_oof_is_rejected(defect):
    f = frame()
    if defect == "duplicate":
        f.loc[1, ["signal_date", "ticker"]] = f.loc[0, ["signal_date", "ticker"]]
    elif defect == "label_boundary":
        f.loc[0, "label_end_date"] = pd.Timestamp("2025-01-01")
    elif defect == "future_signal":
        f.loc[0, "signal_date"] = pd.Timestamp("2026-01-02")
    elif defect == "overlap":
        f.loc[0, "signal_date"] = pd.Timestamp("2023-12-29")
    else:
        f.loc[0, "y_next_open"] = np.nan
    with pytest.raises(ValueError):
        bc.validate_oof(f, receipt())


def test_member_shift_preserves_nan_payload_probability_uncertainty_and_rank():
    payload = np.array([0x7FF8000000000042], dtype=np.uint64).view(np.float64)[0]
    f = pd.DataFrame({"signal_date": pd.to_datetime(["2025-01-02"] * 3), "ticker": ["A", "B", "C"],
        "ridge__mu": np.array([.001, -.002, .0003]), "linear_q__mu": np.array([payload, payload, payload]),
        "logistic__calibrated_p": np.array([.6, .2, .4]), "ridge__uncertainty": np.array([.03, .03, .03])})
    original = f.copy(deep=True)
    delta = .00031727937244615676
    shifted = bc.shift_member_mu(f, delta)
    np.testing.assert_array_equal(shifted.ridge__mu.to_numpy(), f.ridge__mu.to_numpy() + delta)
    for name in ["linear_q__mu", "logistic__calibrated_p", "ridge__uncertainty"]:
        np.testing.assert_array_equal(shifted[name].to_numpy().view(np.uint64), f[name].to_numpy().view(np.uint64))
    np.testing.assert_array_equal(np.argsort(-shifted.ridge__mu.to_numpy(), kind="stable"),
                                  np.argsort(-f.ridge__mu.to_numpy(), kind="stable"))
    assert f.equals(original)


def test_2026_requires_new_freeze_before_any_runtime_or_prediction_read(monkeypatch, tmp_path):
    monkeypatch.setattr(bc, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="NEW_BATCH_FREEZE_REQUIRED"):
        bc.make_predictions(2026)


def test_frozen_nonlinear_fusion_is_not_assumed_translation_equivariant():
    # Extract the exact existing Fusion class without importing torch/training code.
    source = bc.OLD / "calibration_fusion.py"
    node = next(n for n in ast.parse(source.read_text(encoding="utf-8")).body
                if isinstance(n, ast.ClassDef) and n.name == "Fusion")
    stub = types.ModuleType("calibration_fusion")
    stub.__dict__.update(np=np, dataclass=dataclass)
    prior = sys.modules.get("calibration_fusion")
    sys.modules["calibration_fusion"] = stub
    try:
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), stub.__dict__)
        import joblib
        frozen = joblib.load(bc.OLD / "models/fusion_final/all_points__hgb_stack.joblib")
    finally:
        if prior is None:
            del sys.modules["calibration_fusion"]
        else:
            sys.modules["calibration_fusion"] = prior
    # The old weights remain fixed. Crossing frozen tree bins changes the response.
    v = np.linspace(-.008, .008, 257)
    mu = np.column_stack([v + i * .0001 for i in range(13)])
    context = np.zeros((len(mu), 5))
    delta = .00031727937244615676
    before = frozen.predict(mu, context)
    after = frozen.predict(mu + delta, context)
    assert np.isfinite(before).all() and np.isfinite(after).all()
    assert not np.allclose(after - before, delta, rtol=0., atol=1e-12)
    assert np.ptp(after - before) > 1e-12
    # The fixed equal rule, unlike the frozen nonlinear stack, is equivariant.
    equal = stub.Fusion("equal", list(range(13)))
    np.testing.assert_allclose(equal.predict(mu + delta, context) - equal.predict(mu, context),
                               delta, rtol=0., atol=1e-16)
