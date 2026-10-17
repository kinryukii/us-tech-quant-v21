"""Synthetic-only mathematical contracts for additive RB/RH/RT/RR."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.covariance import LedoitWolf

from scripts.research.a2.risk.joint_risk_estimators import RiskEstimatorBlocked
from scripts.research.a2.risk.shared_risk_budget_r2 import StateBudget, StateCache
from scripts.research.a2.risk.shared_risk_extensions_r2 import compute_extension


def fixture_data():
    rng = np.random.default_rng(20260928)
    daily_index = pd.bdate_range("2019-01-02", periods=900, tz="UTC")
    daily = pd.Series(rng.normal(0., .012, len(daily_index)), index=daily_index, name="QQQ")
    origins = daily_index[-257:-5]
    factor = pd.Series(rng.normal(0., .03, len(origins)), index=origins, name="QQQ_5D")
    betas = np.array([.6, 1., 1.4, .8, 1.3, .2])
    frame = pd.DataFrame(factor.to_numpy()[:, None]*betas + rng.normal(0., .015, (252, 6)),
                         index=origins, columns=list("ABCDEF"))
    cutoff = daily_index[-1]+pd.offsets.BDay(1)
    groups = pd.Series([1, 1, 2, 2, 3, 3], index=frame.columns, name="FF48")
    groups.attrs.update(pit_qualified=True, available_at=cutoff, effective_at=origins[0])
    return frame, factor, daily, groups, cutoff


def cache_for(frame, cutoff, **updates):
    budget = StateBudget(limit=100)
    context = dict(source_identity={"synthetic": "fixture-v1"}, cutoff=cutoff.isoformat(),
                   assets=tuple(frame.columns), return_coordinate="STOCK_5D_DECIMAL",
                   horizon=5, identity_epoch={"synthetic_uid": "epoch1"})
    context.update(updates)
    return StateCache(budget, **context)


def run(method, *, frame=None, factor=None, daily=None, groups=None, cutoff=None, cache=None):
    default_frame, default_factor, default_daily, default_groups, default_cutoff = fixture_data()
    frame = default_frame if frame is None else frame
    cutoff = default_cutoff if cutoff is None else cutoff
    cache = cache_for(frame, cutoff) if cache is None else cache
    result = compute_extension(method, frame,
                               qqq_returns=default_factor if factor is None else factor,
                               qqq_daily=default_daily if daily is None else daily,
                               industry_groups=default_groups if groups is None else groups,
                               cutoff=cutoff, learn=cache.learn)
    return result, cache


def assert_psd(matrix):
    assert np.isfinite(matrix).all()
    np.testing.assert_allclose(matrix, matrix.T, atol=1e-13)
    assert np.linalg.eigvalsh(matrix).min() >= -1e-11


def test_rb_is_ols_plus_residual_lw_and_true_qqq_relative_reconstruction():
    frame, qqq, _, _, _ = fixture_data()
    result, cache = run("RB")
    x = frame.to_numpy()-frame.mean().to_numpy()
    f = qqq.to_numpy()-qqq.mean()
    beta = f@x/(f@f)
    residual = x-f[:, None]*beta
    residual_cov = LedoitWolf(assume_centered=True).fit(residual).covariance_
    expected = qqq.var(ddof=1)*np.outer(beta, beta)+residual_cov
    np.testing.assert_allclose(result["covariance"], expected, atol=2e-12)
    np.testing.assert_allclose(result["qqq_relative_state"]["relative_covariance"],
                               qqq.var(ddof=1)*np.outer(beta-1., beta-1.)+residual_cov, atol=1e-12)
    assert cache.budget.counts["scaler"] == 2
    assert cache.budget.counts["covariance"] == 3
    assert_psd(result["covariance"])


def test_rb_qqq_future_append_and_exact_reuse():
    frame, qqq, _, _, cutoff = fixture_data()
    cache = cache_for(frame, cutoff)
    first, _ = run("RB", cache=cache)
    snapshot = cache.budget.snapshot()
    appended = pd.concat([qqq, pd.Series([999.], index=pd.DatetimeIndex([cutoff]))]).rename(qqq.name)
    second, _ = run("RB", factor=appended, cache=cache)
    np.testing.assert_array_equal(first["covariance"], second["covariance"])
    assert cache.budget.snapshot() == snapshot


def test_rb_no_qqq_never_substitutes_cross_sectional_mean():
    frame, _, _, _, cutoff = fixture_data()
    with pytest.raises(RiskEstimatorBlocked, match="QQQ_5D_RETURN_SERIES_REQUIRED"):
        compute_extension("RB", frame, cutoff=cutoff, learn=cache_for(frame, cutoff).learn)


@pytest.mark.parametrize("observations", [0, 29])
def test_rh_short_history_keeps_blocked_asset_out_of_covariance(observations):
    frame, _, _, groups, _ = fixture_data()
    frame.loc[frame.index[observations:], "A"] = np.nan
    result, _ = run("RH", frame=frame, groups=groups)
    assert result["blocked_assets"]["A"] == "FEWER_THAN_30_MATURED_OBSERVATIONS"
    assert "A" not in result["estimated_assets"]
    assert result["covariance"].shape == (5, 5)
    assert_psd(result["covariance"])


def test_rh_fixed_weight_and_asof_group_median_with_at_least_30_observations():
    frame, _, _, _, _ = fixture_data()
    frame.loc[frame.index[30:], "A"] = np.nan
    result, cache = run("RH", frame=frame)
    state = result["qqq_relative_state"]
    assert state["specific_pool_weight"][0] == 30/90
    assert state["specific_pool_weight"][1] == 252/312
    raw = state["specific_variance"]
    expected_a = (30/90)*raw[0]+(60/90)*np.median(raw[:2])
    assert state["pooled_specific_variance"][0] == pytest.approx(expected_a)
    assert cache.budget.counts["scaler"] == 4
    assert cache.budget.counts["covariance"] == 4
    assert_psd(result["covariance"])


@pytest.mark.parametrize("field", ["available_at", "effective_at"])
def test_rh_refuses_future_industry_mapping(field):
    _, _, _, groups, cutoff = fixture_data()
    groups.attrs[field] = cutoff+pd.offsets.BDay(1)
    with pytest.raises(RiskEstimatorBlocked, match=field.upper()+"_AFTER_CUTOFF"):
        run("RH", groups=groups)


def test_rh_missing_industry_is_unknown_and_unqualified_mapping_blocks():
    _, _, _, groups, _ = fixture_data()
    groups.loc["A"] = np.nan
    result, _ = run("RH", groups=groups)
    assert result["blocked_assets"]["A"] == "PIT_FF48_INDUSTRY_UNKNOWN"
    assert "A" not in result["estimated_assets"]
    groups.attrs["pit_qualified"] = False
    with pytest.raises(RiskEstimatorBlocked, match="QUALIFICATION_REQUIRED"):
        run("RH", groups=groups)


def test_rt_raw_downside_moment_and_caller_only_scenario_values():
    frame, _, _, _, _ = fixture_data()
    frame.loc[frame.index[0], "A"] = np.nan
    result, cache = run("RT", frame=frame)
    scenarios = frame.dropna().to_numpy()
    minus = np.minimum(scenarios, 0.)
    expected = minus.T@minus/len(minus)
    np.testing.assert_allclose(result["downside_state"]["downside_second_moment"], expected)
    np.testing.assert_array_equal(result["downside_state"]["scenario_returns"], scenarios)
    assert result["downside_state"]["scenario_count"] == 251
    assert result["downside_state"]["source_evidence_level"] == "CALLER_INPUT_ONLY_UNQUALIFIED"
    assert result["downside_state"]["source_receipt_required_from_caller"]
    assert cache.budget.counts["scaler"] == 1
    assert cache.budget.counts["covariance"] == 2
    assert_psd(result["covariance"])


def test_rr_threshold_is_exact_prior252_median_and_future_append_has_no_effect():
    frame, _, daily, _, cutoff = fixture_data()
    result, cache = run("RR")
    prior_vol = daily.rolling(20).std(ddof=1)*np.sqrt(252.)
    expected_threshold = prior_vol.dropna().iloc[-252:].median()
    assert result["regime_state"]["threshold"] == pytest.approx(expected_threshold)
    assert pd.Timestamp(result["regime_state"]["threshold_last"]) < cutoff
    before = cache.budget.snapshot()
    future = pd.concat([daily, pd.Series([999., -999.], index=pd.bdate_range(cutoff, periods=2))]).rename(daily.name)
    second, _ = run("RR", daily=future, cache=cache)
    np.testing.assert_array_equal(result["covariance"], second["covariance"])
    assert cache.budget.snapshot() == before
    assert cache.budget.counts["regime_threshold"] == 1
    assert cache.budget.counts["covariance"] == 3
    assert "not each historical origin's own" in " ".join(result["estimation_notes"])


def test_rr_empty_regime_boundary_uses_weight_zero_and_no_conditional_fit():
    frame, _, daily, _, cutoff = fixture_data()
    daily.loc[:] = 0.
    result, cache = run("RR", daily=daily)
    state = result["regime_state"]
    assert state["threshold"] == 0.
    assert state["active_regime"] == 0  # Equality belongs to the low regime.
    assert state["regimes"]["1"]["observations"] == 0
    assert state["regimes"]["1"]["pool_weight"] == 0.
    assert state["regimes"]["1"]["status"] == "EMPTY_GLOBAL_ONLY"
    assert cache.budget.counts["covariance"] == 2
    assert all(event["name"] != "regime_1_conditional_lw" for event in cache.budget.events)
    np.testing.assert_array_equal(state["regimes"]["1"]["covariance"],
                                  LedoitWolf(assume_centered=True).fit(frame-frame.mean()).covariance_)


def test_rr_one_observation_sparse_regime_is_explicitly_pooled_and_psd():
    frame, _, daily, _, _ = fixture_data()
    daily.loc[:] = 0.
    daily.iloc[-7] = .25
    result, _ = run("RR", daily=daily)
    state = result["regime_state"]
    sparse = state["regimes"]["1"]
    assert sparse["observations"] == 1
    assert sparse["pool_weight"] == 1/61
    assert sparse["status"] == "SPARSE_CONDITIONAL_POOLED"
    expected = (60/61)*LedoitWolf(assume_centered=True).fit(frame-frame.mean()).covariance_
    np.testing.assert_allclose(sparse["covariance"], expected, atol=1e-12)
    assert_psd(result["covariance"])


def test_rr_new_prior_daily_vol_can_switch_regime_without_changing_threshold():
    _, _, daily, _, _ = fixture_data()
    daily.loc[:] = 0.
    low, _ = run("RR", daily=daily)
    daily.iloc[-1] = .2
    high, _ = run("RR", daily=daily)
    assert low["regime_state"]["threshold"] == high["regime_state"]["threshold"] == 0.
    assert low["regime_state"]["active_regime"] == 0
    assert high["regime_state"]["active_regime"] == 1


def test_source_identity_mutation_consumes_fresh_states_and_repeated_result_is_deterministic():
    frame, _, _, _, cutoff = fixture_data()
    cache = cache_for(frame, cutoff)
    first, _ = run("RB", cache=cache)
    learned = cache.budget.learned_total
    changed = cache.bind(source_identity={"synthetic": "fixture-v2"})
    second, _ = run("RB", cache=changed)
    assert cache.budget.learned_total == 2*learned
    np.testing.assert_array_equal(first["covariance"], second["covariance"])


@pytest.mark.parametrize("method", ["RB", "RH", "RT", "RR"])
def test_cross_method_transform_cache_never_reuses_a_different_covariance(method):
    frame, _, _, _, cutoff = fixture_data()
    cache = cache_for(frame, cutoff)
    run("RT", cache=cache)
    reused, _ = run(method, cache=cache)
    isolated, _ = run(method)
    np.testing.assert_array_equal(reused["covariance"], isolated["covariance"])


def test_pre2026_cutoff_and_current_session_are_fail_closed():
    frame, _, _, _, cutoff = fixture_data()
    with pytest.raises(RiskEstimatorBlocked, match="PRE_CUTOFF"):
        run("RB", frame=frame, cutoff=frame.index[-1])
    with pytest.raises(RiskEstimatorBlocked, match="CUTOFF_MUST_BE_PRE_2026"):
        compute_extension("RT", frame, cutoff="2026-01-01", learn=lambda *args: args[-1]())


def test_no_history_and_insufficient_prior_regime_history_fail_explicitly():
    frame, _, daily, _, _ = fixture_data()
    frame.loc[:] = np.nan
    with pytest.raises(RiskEstimatorBlocked, match="NO_ASSET_HAS_30"):
        run("RT", frame=frame)
    with pytest.raises(RiskEstimatorBlocked, match="252_PRIOR_VALID"):
        run("RR", daily=daily.iloc[-260:])



@pytest.mark.parametrize("method", ["RB", "RH", "RR"])
@pytest.mark.parametrize("field", ["source_version", "source_sha256"])
def test_qqq_source_mutation_with_identical_values_refits_all_dependent_states(method, field):
    frame, factor, daily, groups, cutoff = fixture_data()
    qqq_source = dict(source_id="SYNTHETIC_QQQ", source_version="v1", source_sha256="1"*64,
                      available_at=cutoff, cutoff=cutoff.isoformat())
    factor.attrs.update(qqq_source)
    daily.attrs.update(qqq_source)
    cache = cache_for(frame, cutoff)
    before = compute_extension(method, frame, qqq_returns=factor, qqq_daily=daily,
                               industry_groups=groups, cutoff=cutoff, learn=cache.learn)
    first_events = list(cache.budget.events)
    independent = {"stock_observed_mean", "stock_global_lw"}
    expected_new = {event["name"] for event in first_events
                    if event["kind"] != "deterministic_transform" and event["name"] not in independent}
    factor.attrs[field] = "v2" if field == "source_version" else "2"*64
    daily.attrs[field] = factor.attrs[field]
    after = compute_extension(method, frame, qqq_returns=factor, qqq_daily=daily,
                              industry_groups=groups, cutoff=cutoff, learn=cache.learn)
    new_events = cache.budget.events[len(first_events):]
    learned_names = [event["name"] for event in new_events if event["kind"] != "deterministic_transform"]
    assert set(learned_names) == expected_new
    assert len(learned_names) == len(expected_new)
    np.testing.assert_array_equal(before["covariance"], after["covariance"])
    state = after["regime_state"] if method == "RR" else after["qqq_relative_state"]
    assert state["source_binding"][field] == factor.attrs[field]
    assert state["source_binding"]["source_identity"] == "SYNTHETIC_QQQ"
    assert state["source_binding"]["available_at"] == cutoff
    assert state["cutoff"] == cutoff.isoformat()


def test_industry_source_mutation_refits_hierarchical_specific_and_factor_states():
    frame, factor, _, groups, cutoff = fixture_data()
    factor.attrs.update(source_id="SYNTHETIC_QQQ", source_version="v1", source_sha256="1"*64)
    groups.attrs.update(source_id="SYNTHETIC_FF48", source_version="v1", source_sha256="3"*64)
    cache = cache_for(frame, cutoff)
    before = compute_extension("RH", frame, qqq_returns=factor, industry_groups=groups,
                               cutoff=cutoff, learn=cache.learn)
    first_count = len(cache.budget.events)
    groups.attrs["source_version"] = "v2"
    after = compute_extension("RH", frame, qqq_returns=factor, industry_groups=groups,
                              cutoff=cutoff, learn=cache.learn)
    learned = {event["name"] for event in cache.budget.events[first_count:]
               if event["kind"] != "deterministic_transform"}
    assert learned == {"ff48_observed_group_mean_returns", "qqq_ff48_factor_mean",
                       "qqq_ff48_factor_lw", "ff48_specific_sample_variance",
                       "ff48_asof_group_specific_median"}
    np.testing.assert_array_equal(before["covariance"], after["covariance"])
    assert after["qqq_relative_state"]["source_binding"]["industry_source_binding"]["source_version"] == "v2"



def test_rh_complete_state_serializes_with_string_ff48_group_keys():
    from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
    result, _ = run("RH")
    groups = result["qqq_relative_state"]["industry_group_median"]
    assert set(groups) == {"1", "2", "3"}
    assert all(isinstance(value, float) for value in groups.values())
    assert len(content_hash(result)) == 64
