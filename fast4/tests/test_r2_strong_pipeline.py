from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import optuna
import pandas as pd


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fast4.r2_evaluation import choose_abstention, crossfit_ridge_stack  # noqa: E402
from fast4.r2_pipeline import R1_FEATURE_MANIFEST, R1_MATRIX, _apply_quantile_order  # noqa: E402
from fast4.strong_models import StrongSpec, default_parameters, fit_spec, specifications  # noqa: E402


def test_r2_environment_feature_identity_and_ranking_group_integrity() -> None:
    assert Path(sys.executable).resolve() == Path(r"D:\us-tech-quant\.venv\Scripts\python.exe").resolve()
    import catboost
    import lightgbm
    import xgboost
    assert (lightgbm.__version__, xgboost.__version__, catboost.__version__, optuna.__version__) == ("4.7.0", "3.4.0", "1.2.10", "4.9.0")
    manifest = json.loads(R1_FEATURE_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["feature_manifest_sha256"] == "729ef554070cde1d9a6b4501e68ee4e641d2bf92a163ff29cecc3e7b165ea7a5"
    frame = pd.read_parquet(R1_MATRIX, columns=["candidate_id", "decision_timestamp_utc", "trading_date"])
    assert frame.candidate_id.is_unique
    assert frame.groupby("decision_timestamp_utc").size().max() == 1
    assert frame.groupby("trading_date").size().max() == 1


def test_lightgbm_xgboost_catboost_quantile_and_serialization(tmp_path: Path) -> None:
    rng = np.random.default_rng(44202)
    frame = pd.DataFrame({"x1": rng.normal(size=80), "x2": rng.normal(size=80),
                          "head": np.where(np.arange(80) % 2, "UP", "DOWN")})
    frame["primary_target"] = .001 * frame.x1 - .0005 * frame.x2
    tested = []
    for family, objective in (("LightGBM", "huber"), ("XGBoost", "reg:pseudohubererror"), ("CatBoost", "Huber:delta=0.005")):
        spec = StrongSpec(f"test_{family}", family, objective, "pooled", "regression", "primary_target")
        fitted, count = fit_spec(spec, frame, frame.index.to_numpy(), ["x1", "x2"], default_parameters(spec), 44202, 1)
        prediction = fitted.predict_score(frame)
        assert count == 1 and np.isfinite(prediction).all()
        path = tmp_path / f"{family}.joblib"
        joblib.dump(fitted, path)
        assert np.allclose(prediction, joblib.load(path).predict_score(frame), atol=1e-12, rtol=0)
        tested.append(family)
    assert tested == ["LightGBM", "XGBoost", "CatBoost"]
    available = {spec.name for spec in specifications()}
    assert all(f"{short}_q{q:02d}_pooled" in available for short in ("lgb", "xgb", "cat") for q in (5, 10, 25, 50))


def test_optuna_seed_quantile_order_meta_crossfit_and_abstention_isolation() -> None:
    def sampled(seed: int) -> list[float]:
        study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
        study.optimize(lambda trial: -(trial.suggest_float("x", -1, 1) - .25) ** 2, n_trials=5)
        return [trial.params["x"] for trial in study.trials]
    assert sampled(44203) == sampled(44203)
    inner = pd.DataFrame({f"lgb_q{q:02d}_pooled": [value] for q, value in zip((5, 10, 25, 50), (.3, .1, .4, .2))})
    outer = inner.copy()
    audit = _apply_quantile_order(inner, outer, set(inner.columns))
    assert audit["crossing_rows_before_deterministic_ordering"] == 2
    assert audit["crossing_rows_after_deterministic_ordering"] == 0
    index = pd.RangeIndex(90)
    base = pd.DataFrame({"a": np.linspace(-1, 1, 90), "b": np.sin(np.arange(90))}, index=index)
    target = pd.Series(np.linspace(-.01, .01, 90), index=index)
    labels = pd.Series(np.repeat(["INNER_1", "INNER_2", "INNER_3"], 30), index=index)
    crossfit, outer_prediction, contract, _ = crossfit_ridge_stack(base, base.iloc[:10], target, labels)
    assert crossfit.iloc[:30].isna().all() and crossfit.iloc[30:].notna().all()
    assert np.isfinite(outer_prediction).all() and contract["crossfit_row_count"] == 60
    frame = pd.DataFrame({"primary_target": target, "candidate_id": index.astype(str),
                          "decision_timestamp_utc": pd.date_range("2020-01-01", periods=90, freq="D", tz="UTC")})
    selected, policy = choose_abstention(frame, base.a, labels, base.a.iloc[:10].to_numpy(), [.3, .2, .1])
    assert selected.dtype == bool and policy["candidate_coverages"] == [.3, .2, .1]
    assert "outer" not in json.dumps(policy).lower()
