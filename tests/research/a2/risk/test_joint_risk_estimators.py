"""Synthetic behavior checks for caller-bound JOINT risk estimates."""
import json
import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.risk.joint_risk_estimators import (
    RiskEstimatorBlocked, fit_risk_estimator, risk_matrix, specs,
    validate_covariance,
)


def inputs():
    rng = np.random.default_rng(21)
    dates = pd.date_range("2024-01-01", periods=140)
    market = pd.Series(rng.normal(0, .01, len(dates)), index=dates)
    market.attrs["source_id"] = "synthetic_market"
    returns = pd.DataFrame(
        market.to_numpy()[:, None]*np.linspace(.6, 1.8, 8)
        +rng.normal(0, .009, (len(dates), 8)),
        index=dates, columns=[f"S{i}" for i in range(8)],
    )
    exposure = pd.DataFrame({"f1": np.linspace(.5, 2, 8), "f2": [0, 1]*4}, index=returns.columns)
    exposure.attrs.update(pit_qualified=True, source_id="synthetic_exposure",
                          available_at="2024-05-20")
    params = {"fit_cutoff": "2024-06-01", "return_horizon_sessions": 5,
              "return_unit": "synthetic_5_session_shareholder_return", "source_id": "synthetic_returns"}
    return returns, market, exposure, params


@pytest.mark.parametrize("method", [
    "DIAG", "SCOV", "LW", "OAS", "CONSTANT_CORR", "PCA", "FA",
    "SINGLE_INDEX", "EWMA", "HISTVOL", "GARCH", "GJR_GARCH",
    "GRAPHICAL_LASSO", "ROBUST_COV", "COV_ENSEMBLE",
])
def test_estimators_fit_all_caller_rows_and_produce_psd_in_return_units(method):
    returns, market, _, params = inputs()
    bundle = fit_risk_estimator(method, returns, market_returns=market, params=params)
    assert bundle.status == "FITTED", bundle.failure_reason
    assert bundle.assets == tuple(returns.columns)
    assert bundle.estimated_assets == bundle.assets
    assert len(bundle.fitted_dates) == len(returns)
    assert bundle.fitted_state["return_observation_rows"] == len(returns)
    assert bundle.fitted_state["return_horizon_sessions"] == 5
    assert bundle.budget["total_state_estimations"] >= 2
    assert not bundle.coverage.strategy_eligibility_upgraded.any()
    matrix = risk_matrix(bundle, returns.columns)
    assert np.isfinite(matrix).all()
    assert np.allclose(matrix, matrix.T)
    assert np.linalg.eigvalsh(matrix).min() >= 0
    # Return-unit scale, not a unit correlation mislabeled as covariance.
    assert 1e-6 < np.median(np.diag(matrix)) < .01
    if method == "EWMA":
        assert bundle.fitted_state["positive_weight_rows"] == len(returns)
    if method in {"GARCH", "GJR_GARCH"}:
        assert len(bundle.fitted_state["pure_definition_sha256"]) == 64


@pytest.mark.parametrize("method", ["INDUSTRY", "FUNDAMENTAL"])
def test_factor_covariance_respects_exposure_units_and_records_partial_coverage(method):
    returns, _, exposure, params = inputs()
    first = fit_risk_estimator(method, returns, exposure_frame=exposure, params=params)
    changed_units = exposure.copy()
    changed_units["f1"] *= 100
    second = fit_risk_estimator(method, returns, exposure_frame=changed_units, params=params)
    assert first.status == second.status == "FITTED"
    np.testing.assert_allclose(first.covariance, second.covariance, rtol=1e-10, atol=1e-12)
    assert first.budget["estimator_state_estimations"] == 3
    assert first.budget["total_state_estimations"] == 4
    assert first.fitted_state["physical_crosssectional_solutions"] == len(returns)
    assert first.fitted_state["exposure_source_id"] == "synthetic_exposure"
    partial = exposure.drop(index="S7")
    fitted = fit_risk_estimator(method, returns, exposure_frame=partial, params=params)
    assert fitted.status == "FITTED"
    assert "S7" not in fitted.estimated_assets
    assert not fitted.coverage.loc[fitted.coverage.asset.eq("S7"), "dependency_available_for_estimation"].iloc[0]
    matrix, metadata = risk_matrix(fitted, ["S0", "S7"], return_metadata=True)
    assert metadata["unknown_assets"] == ["S7"]
    assert matrix[0, 1] == matrix[1, 0] == 0
    assert metadata["strategy_eligibility_upgraded"] is False


def test_unknown_and_insufficient_history_names_use_explicit_prior_median_independently():
    returns, _, _, params = inputs()
    returns["THIN"] = np.nan
    returns.loc[returns.index[:5], "THIN"] = np.linspace(.01, .02, 5)
    fitted = fit_risk_estimator("LW", returns, params=params)
    matrix, metadata = risk_matrix(fitted, ["S1", "THIN", "NEW", "S0"], return_metadata=True)
    assert metadata["unknown_assets"] == ["THIN", "NEW"]
    assert matrix[1, 1] == matrix[2, 2] == fitted.fallback_variance
    assert not matrix[1, [0, 2, 3]].any()
    assert not matrix[2, [0, 1, 3]].any()
    positions = [fitted.estimated_assets.index("S1"), fitted.estimated_assets.index("S0")]
    # Mapping must not repeatedly regularize or refit the known submatrix.
    np.testing.assert_array_equal(matrix[np.ix_([0, 3], [0, 3])],
                                  fitted.covariance[np.ix_(positions, positions)])
    assert not fitted.coverage.strategy_eligibility_upgraded.any()


def test_factor_dependencies_block_without_inventing_exposures_or_broker_eligibility():
    returns, _, exposure, params = inputs()
    for method in ("INDUSTRY", "FUNDAMENTAL"):
        bundle = fit_risk_estimator(method, returns, params=params)
        assert bundle.status == "BLOCKED_INPUT"
        assert bundle.covariance is None
        with pytest.raises(RiskEstimatorBlocked, match="BLOCKED_INPUT"):
            risk_matrix(bundle, returns.columns)
        unqualified = exposure.copy()
        unqualified.attrs["pit_qualified"] = False
        assert fit_risk_estimator(method, returns, exposure_frame=unqualified, params=params).status == "BLOCKED_INPUT"
        future = exposure.copy()
        future.attrs["available_at"] = "2024-06-02"
        assert fit_risk_estimator(method, returns, exposure_frame=future, params=params).status == "BLOCKED_INPUT"


def test_genuine_nonlinear_shrinkage_missing_backend_is_not_lw_fallback():
    returns, _, _, params = inputs()
    bundle = fit_risk_estimator("NONLINEAR_SHRINKAGE", returns, params=params)
    assert bundle.status == "BLOCKED_DEPENDENCY"
    assert "GENUINE_NONLINEAR" in bundle.failure_reason
    assert bundle.covariance is None
    assert bundle.budget["estimator_state_estimations"] == 0


def test_caller_cutoff_rejects_future_rows_and_append_does_not_change_isolated_fit():
    returns, _, _, params = inputs()
    earlier = fit_risk_estimator("LW", returns, params=params)
    future = pd.DataFrame(9., index=pd.date_range("2024-06-02", periods=3), columns=returns.columns)
    appended = pd.concat([returns, future])
    with pytest.raises(ValueError, match="STRICTLY_BEFORE_CALLER_CUTOFF"):
        fit_risk_estimator("LW", appended, params=params)
    # The caller owns content-level isolation and label maturity; the estimator
    # never loads a mixed file and never silently trims its input.
    isolated = appended.loc[appended.index < pd.Timestamp(params["fit_cutoff"])]
    repeated = fit_risk_estimator("LW", isolated, params=params)
    np.testing.assert_array_equal(earlier.covariance, repeated.covariance)
    assert earlier.fitted_state["fit_identity_sha256"] == repeated.fitted_state["fit_identity_sha256"]


def test_frozen_specs_serialization_identity_and_no_parameter_search():
    returns, _, _, params = inputs()
    configurations = specs()
    assert len(configurations) == 18
    json.dumps(configurations)
    for config in configurations.values():
        assert config["configs"] == config["seeds"] == 1
        assert config["window"] == "ALL_CALLER_PROVIDED_MATURED_PAST_ROWS"
    with pytest.raises(ValueError, match="DIFFERS_FROM_FROZEN"):
        fit_risk_estimator("LW", returns, params={**params, "min_observations": 29})
    # Dict insertion order alone is not a new identity.
    other_order = dict(reversed(list(params.items())))
    a = fit_risk_estimator("LW", returns, params=params)
    b = fit_risk_estimator("LW", returns, params=other_order)
    assert a.fitted_state["fit_identity_sha256"] == b.fitted_state["fit_identity_sha256"]
    changed_unit = fit_risk_estimator("LW", returns, params={**params, "return_unit": "different_target_unit"})
    assert a.fitted_state["fit_identity_sha256"] != changed_unit.fitted_state["fit_identity_sha256"]


def test_min_cov_det_dimension_requirement_blocks_without_asset_or_row_sampling():
    rng = np.random.default_rng(7)
    returns = pd.DataFrame(rng.normal(0, .02, (60, 64)),
                           index=pd.date_range("2024-01-01", periods=60))
    bundle = fit_risk_estimator("ROBUST_COV", returns)
    assert bundle.status == "BLOCKED_INPUT"
    assert "MORE_OBSERVATION_ROWS_THAN_ASSETS" in bundle.failure_reason
    assert len(bundle.assets) == 64 and len(bundle.fitted_dates) == 60


def test_psd_validation_rejects_indefinite_and_nonfinite_matrices():
    with pytest.raises(ValueError, match="NOT_PSD"):
        validate_covariance([[1., 2.], [2., 1.]])
    with pytest.raises(ValueError, match="NONFINITE"):
        validate_covariance([[1., np.nan], [np.nan, 1.]])
