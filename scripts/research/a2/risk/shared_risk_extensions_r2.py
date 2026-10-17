"""Pure RB/RH/RT/RR additions to the existing shared covariance primitives.

Inputs are caller-isolated matured returns, never readers or provider substitutes.
``learn(kind, name, inputs, compute)`` owns reservations, identities and reuse;
all fitted calculations and deterministic transforms pass through that callback.
Source receipts and horizon/endpoint/identity qualification remain caller-owned.
"""
from __future__ import annotations

from collections.abc import Callable
import copy
import warnings

import numpy as np
import pandas as pd

from .joint_risk_estimators import (
    COMMON, RiskEstimatorBlocked, _estimate, specs, validate_covariance,
)

METHODS = frozenset({"RB", "RH", "RT", "RR"})
POOL_STRENGTH = 60
MIN_OBSERVATIONS = 30


def _block(reason):
    raise RiskEstimatorBlocked("BLOCKED_INPUT:" + reason)


def _date_index(value, name):
    index = value.index
    if (not isinstance(index, pd.DatetimeIndex) or index.hasnans
            or index.has_duplicates or not index.is_monotonic_increasing):
        _block(name + "_DATES_MUST_BE_UNIQUE_INCREASING")


def _with_attrs(value, source, *, extra=None):
    """Keep source identities on every derived pandas state used in fit keys."""
    attributes = copy.deepcopy(source.attrs)
    if attributes.get("source_id") and not attributes.get("source_identity"):
        attributes["source_identity"] = attributes["source_id"]
    attributes.update(copy.deepcopy(extra or {}))
    value.attrs = attributes
    return value


def _series(value, name, cutoff, *, index=None):
    if not isinstance(value, pd.Series):
        _block(name + "_SERIES_REQUIRED")
    _date_index(value, name)
    if value.index.tz != cutoff.tzinfo:
        _block(name + "_TIMEZONE_DIFFERS_FROM_CUTOFF")
    # Slice before numerical access: later rows are not estimation content.
    result = value.loc[value.index < cutoff].copy()
    if index is not None:
        result = result.reindex(index)
    if result.empty or not np.isfinite(result.to_numpy(float)).all():
        _block(name + "_FINITE_PAST_OBSERVATIONS_REQUIRED")
    return _with_attrs(result.astype(float), value, extra={"cutoff": cutoff.isoformat()})


class _Calculations:
    def __init__(self, learn):
        if not callable(learn):
            raise TypeError("LEARN_CALLBACK_REQUIRED")
        self.learn = learn
        self.transforms = []

    def fit(self, kind, name, inputs, compute):
        return self.learn(kind, name, tuple(inputs), compute)

    def transform(self, name, inputs, compute, **detail):
        self.transforms.append({"name": name, **detail})
        return self.fit("deterministic_transform", name, inputs, compute)


def _prepare(stocks, cutoff, calc):
    if not isinstance(stocks, pd.DataFrame) or stocks.empty:
        _block("NONEMPTY_STOCK_RETURN_DATAFRAME_REQUIRED")
    _date_index(stocks, "STOCK")
    if (stocks.index.tz != cutoff.tzinfo or np.any(stocks.index >= cutoff)
            or np.any(stocks.index >= pd.Timestamp("2026-01-01", tz=stocks.index.tz))):
        _block("STOCK_OBSERVATIONS_MUST_BE_PRE_CUTOFF_AND_PRE_2026")
    names = tuple(map(str, stocks.columns))
    if not names or len(set(names)) != len(names) or any(not name.strip() for name in names):
        _block("STOCK_ASSETS_MUST_BE_UNIQUE_NONEMPTY")
    frame = stocks.copy()
    frame.columns = names
    raw = frame.to_numpy(float)
    if np.isinf(raw).any():
        _block("INFINITE_STOCK_RETURN")
    counts = np.isfinite(raw).sum(axis=0)
    qualified = counts >= MIN_OBSERVATIONS
    coverage = pd.DataFrame({"asset": names, "observations": counts,
                             "history_qualified_for_estimation": qualified,
                             "strategy_eligibility_upgraded": False})
    blocked = {name: "FEWER_THAN_30_MATURED_OBSERVATIONS"
               for name, valid in zip(names, qualified) if not valid}
    if not qualified.any():
        _block("NO_ASSET_HAS_30_MATURED_OBSERVATIONS")
    frame = frame.loc[:, qualified]
    mean = calc.fit("scaler", "stock_observed_mean", [frame],
                    lambda: frame.mean(axis=0))
    centered = calc.transform("stock_center_and_missing_zero", [frame, mean],
                             lambda: frame.subtract(mean, axis=1).fillna(0.))
    return frame, centered, mean, coverage, blocked


def _lw(frame, calc, name):
    def compute():
        state = {"centered": frame.to_numpy(float),
                 "marginal_variance": np.ones(frame.shape[1])}
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            matrix, detail, _ = _estimate("LW", state, frame.index,
                                          tuple(frame.columns), None, None, specs("LW"))
        return {"covariance": matrix, "shrinkage": detail["shrinkage"],
                "warnings": [str(item.message) for item in captured]}
    return calc.fit("covariance", name, [frame], compute)


def _qqq_decomposition(frame, centered, qqq, cutoff, calc, *, need_variance=True):
    factor = _series(qqq, "QQQ_5D_RETURN", cutoff, index=frame.index)
    factor_matrix = pd.DataFrame(
        np.broadcast_to(factor.to_numpy()[:, None], frame.shape),
        index=frame.index, columns=frame.columns,
    ).where(frame.notna())
    factor_matrix = _with_attrs(factor_matrix, factor)
    factor_means = calc.fit("scaler", "qqq_per_asset_observed_mean", [factor_matrix],
                           lambda: _with_attrs(factor_matrix.mean(axis=0), factor_matrix))
    factors = calc.transform("qqq_center_per_asset_observed", [factor_matrix, factor_means],
                             lambda: _with_attrs(factor_matrix.subtract(factor_means, axis=1).fillna(0.), factor_matrix))
    def ols():
        numerator = (factors * centered).sum(axis=0)
        denominator = (factors * factors).sum(axis=0)
        if (denominator <= COMMON["variance_floor"]).any():
            _block("QQQ_FACTOR_HAS_NO_IDENTIFIABLE_VARIANCE")
        return _with_attrs(numerator / denominator, factors)
    beta = calc.fit("covariance", "qqq_centered_ols_beta", [factors, centered], ols)
    residual = calc.transform("qqq_ols_residual", [centered, factors, beta],
                              lambda: _with_attrs(centered - factors.multiply(beta, axis=1), factors))
    factor_variance = calc.fit("covariance", "qqq_5d_sample_variance", [factor],
                              lambda: float(factor.var(ddof=1))) if need_variance else None
    return factor, beta, residual, factor_variance


def _rb(frame, centered, qqq, cutoff, calc):
    factor, beta, residual, variance = _qqq_decomposition(frame, centered, qqq, cutoff, calc)
    residual_fit = _lw(residual, calc, "qqq_residual_lw")
    residual_cov = residual_fit["covariance"]
    beta_array = beta.to_numpy(float)
    absolute = calc.transform("qqq_absolute_reconstruction", [beta, residual_cov, variance],
                              lambda: variance*np.outer(beta_array, beta_array)+residual_cov)
    relative = calc.transform("qqq_relative_reconstruction", [beta, residual_cov, variance],
                              lambda: variance*np.outer(beta_array-1., beta_array-1.)+residual_cov)
    return {"covariance": absolute, "shrinkage_intensity": residual_fit["shrinkage"],
            "qqq_relative_state": {"beta": beta_array, "qqq_variance": variance,
                                   "residual_covariance": residual_cov,
                                   "relative_covariance": relative,
                                   "factor_observations": len(factor), "source_binding": copy.deepcopy(factor.attrs),
                                   "cutoff": cutoff.isoformat()},
            "estimation_notes": ["OLS uses each asset's observed rows; missing residuals are zero after observed centering.",
                                 "Absolute covariance reconstructs beta QQQ risk plus residual LW; no cross-sectional factor fallback."]}


def _industry(frame, groups, cutoff):
    if not isinstance(groups, pd.Series) or groups.index.has_duplicates:
        _block("PIT_FF48_INDUSTRY_SERIES_REQUIRED")
    if groups.attrs.get("pit_qualified") is not True:
        _block("PIT_FF48_INDUSTRY_QUALIFICATION_REQUIRED")
    for field in ("available_at", "effective_at"):
        value = groups.attrs.get(field)
        if field == "available_at" and value is None:
            _block("PIT_FF48_AVAILABLE_AT_REQUIRED")
        if value is not None:
            date = pd.Timestamp(value)
            if pd.isna(date) or date.tzinfo != cutoff.tzinfo or date > cutoff:
                _block("PIT_FF48_" + field.upper() + "_AFTER_CUTOFF")
    normalized = groups.copy()
    normalized.index = normalized.index.map(str)
    if normalized.index.has_duplicates:
        _block("DUPLICATE_NORMALIZED_FF48_ASSET")
    selected = pd.to_numeric(normalized.reindex(frame.columns), errors="coerce")
    valid = selected.notna() & selected.between(1, 48) & selected.eq(np.floor(selected))
    blocked = {asset: "PIT_FF48_INDUSTRY_UNKNOWN" for asset in frame.columns if not valid[asset]}
    if not valid.any():
        _block("NO_ASSET_HAS_PIT_FF48_INDUSTRY")
    return _with_attrs(selected.loc[valid].astype(int), groups), blocked


def _rh(frame, centered, qqq, groups, cutoff, calc):
    industry, blocked = _industry(frame, groups, cutoff)
    assets = industry.index
    frame, centered = frame.loc[:, assets], centered.loc[:, assets]
    factor, beta, residual, _ = _qqq_decomposition(frame, centered, qqq, cutoff, calc, need_variance=False)
    labels = tuple(sorted(industry.unique()))
    observed_residual = residual.where(frame.notna())
    group_factors = calc.fit(
        "scaler", "ff48_observed_group_mean_returns", [observed_residual, industry],
        lambda: _with_attrs(pd.DataFrame({f"FF48_{label}": observed_residual.loc[:, industry.eq(label)].mean(axis=1)
                              for label in labels}, index=frame.index).fillna(0.), residual,
                              extra={"industry_source_binding": copy.deepcopy(industry.attrs)}),
    )
    factors = _with_attrs(pd.concat([factor.rename("QQQ"), group_factors], axis=1), group_factors)
    factor_mean = calc.fit("scaler", "qqq_ff48_factor_mean", [factors], lambda: _with_attrs(factors.mean(axis=0), factors))
    factor_centered = calc.transform("qqq_ff48_factor_center", [factors, factor_mean],
                                     lambda: _with_attrs(factors.subtract(factor_mean, axis=1), factors))
    factor_fit = _lw(factor_centered, calc, "qqq_ff48_factor_lw")
    group_projection = _with_attrs(pd.DataFrame({asset: group_factors[f"FF48_{industry[asset]}"]
                                     for asset in assets}, index=frame.index), group_factors)
    specific_returns = calc.transform("ff48_specific_residual", [residual, group_projection],
                                      lambda: _with_attrs((residual-group_projection).where(frame.notna()), group_factors))
    specific = calc.fit("covariance", "ff48_specific_sample_variance", [specific_returns],
                        lambda: _with_attrs(specific_returns.var(axis=0, ddof=1).clip(lower=COMMON["variance_floor"]), specific_returns))
    median = calc.fit("covariance", "ff48_asof_group_specific_median", [specific, industry],
                      lambda: _with_attrs(specific.groupby(industry).median(), specific))
    counts = frame.notna().sum(axis=0)
    weight = counts / (counts + POOL_STRENGTH)
    pooled = calc.transform("ff48_specific_partial_pool", [specific, median, industry, counts],
                            lambda: weight*specific+(1.-weight)*industry.map(median))
    loadings = np.zeros((len(assets), len(labels)+1))
    loadings[:, 0] = beta.to_numpy(float)
    for position, asset in enumerate(assets):
        loadings[position, labels.index(industry[asset])+1] = 1.
    covariance = calc.transform("qqq_ff48_absolute_reconstruction", [beta, industry, pooled, factor_fit["covariance"]],
                                lambda: loadings@factor_fit["covariance"]@loadings.T+np.diag(pooled))
    return {"covariance": covariance, "estimated_assets": tuple(assets), "blocked_assets": blocked,
            "shrinkage_intensity": factor_fit["shrinkage"],
            "qqq_relative_state": {"beta": beta.to_numpy(float), "factor_names": tuple(factors.columns),
                                   "factor_covariance": factor_fit["covariance"],
                                   "specific_variance": specific.to_numpy(float),
                                   "pooled_specific_variance": pooled.to_numpy(float),
                                   "industry_group_median": {str(group): float(value) for group, value in median.items()},
                                   "specific_pool_weight": weight.to_numpy(float),
                                   "source_binding": copy.deepcopy(factors.attrs), "cutoff": cutoff.isoformat()},
            "estimation_notes": ["PIT FF48 membership is bound as of cutoff; current membership cannot backfill past state.",
                                 "Observed group mean residual factors and QQQ receive joint LW; specific variance pools n/(n+60) toward the as-of group median."]}


def _rt(frame, centered, calc):
    fit = _lw(centered, calc, "stock_global_lw")
    scenarios = frame.dropna(axis=0, how="any")
    if len(scenarios) < MIN_OBSERVATIONS:
        _block("DOWNSIDE_REQUIRES_30_COMPLETE_MATURED_SCENARIOS")
    negative = calc.transform("downside_negative_return_scenarios", [scenarios],
                              lambda: scenarios.clip(upper=0.))
    moment = calc.fit("covariance", "downside_uncentered_second_moment", [negative],
                      lambda: negative.to_numpy().T@negative.to_numpy()/len(negative))
    covariance = calc.transform("lw_downside_equal_blend", [fit["covariance"], moment],
                                lambda: .5*fit["covariance"]+.5*moment)
    return {"covariance": covariance, "shrinkage_intensity": fit["shrinkage"],
            "downside_state": {"scenario_returns": scenarios.to_numpy(float),
                               "scenario_origins": tuple(scenarios.index.map(pd.Timestamp.isoformat)),
                               "scenario_assets": tuple(scenarios.columns),
                               "scenario_count": len(scenarios), "downside_second_moment": moment,
                               "source_receipt_required_from_caller": True,
                               "source_evidence_level": "CALLER_INPUT_ONLY_UNQUALIFIED"},
            "estimation_notes": ["Downside second moment uses uncentered min(actual return,0), not centered shocks.",
                                 "Scenario values are caller inputs; this module produces no real/source-qualified CVaR receipt."]}


def _rr(frame, centered, qqq_daily, cutoff, calc):
    daily = _series(qqq_daily, "QQQ_DAILY_RETURN", cutoff)
    realized = calc.fit("scaler", "qqq_20_session_annual_realized_vol", [daily],
                        lambda: _with_attrs(daily.rolling(20, min_periods=20).std(ddof=1)*np.sqrt(252.), daily))
    history = _with_attrs(realized.dropna().iloc[-252:], realized)
    if len(history) != 252:
        _block("REGIME_THRESHOLD_REQUIRES_252_PRIOR_VALID_20_SESSION_VOLS")
    threshold = calc.fit("regime_threshold", "qqq_prior252_vol_median", [history],
                         lambda: float(history.median()))
    # A return labelled at an origin uses volatility observed strictly before it.
    def origin_volatility():
        positions = realized.index.searchsorted(frame.index, side="left")-1
        if (positions < 0).any():
            _block("REGIME_ORIGIN_HAS_NO_STRICTLY_PRIOR_QQQ_VOL")
        values = realized.iloc[positions].to_numpy(float)
        if not np.isfinite(values).all():
            _block("REGIME_ORIGIN_REQUIRES_20_STRICTLY_PRIOR_QQQ_SESSIONS")
        return _with_attrs(pd.Series(values, index=frame.index, name="prior_origin_volatility"), realized)
    origin_vol = calc.transform("qqq_strict_prior_origin_volatility", [realized, frame], origin_volatility)
    labels = calc.transform("qqq_frozen_threshold_regime_labels", [origin_vol, threshold],
                            lambda: _with_attrs(origin_vol.gt(threshold).astype(int), origin_vol))
    global_fit = _lw(centered, calc, "stock_global_lw")
    states = {}
    matrices = []
    for label in (0, 1):
        selected = _with_attrs(frame.loc[labels.eq(label)], labels)
        count = len(selected)
        weight = count/(count+POOL_STRENGTH)
        conditional = None
        if count:
            mean = calc.fit("scaler", f"regime_{label}_observed_mean", [selected],
                            lambda selected=selected: _with_attrs(selected.mean(axis=0), selected))
            conditional_centered = calc.transform(
                f"regime_{label}_center_and_missing_zero", [selected, mean],
                lambda selected=selected, mean=mean: _with_attrs(selected.subtract(mean, axis=1).fillna(0.), selected),
            )
            conditional = _lw(conditional_centered, calc, f"regime_{label}_conditional_lw")
        conditional_cov = conditional["covariance"] if conditional else global_fit["covariance"]
        pooled = calc.transform(
            f"regime_{label}_partial_pool", [conditional_cov, global_fit["covariance"], weight],
            lambda conditional_cov=conditional_cov, weight=weight: (
                weight*conditional_cov+(1.-weight)*global_fit["covariance"]),
        )
        matrices.append(pooled)
        states[str(label)] = {"observations": count, "pool_weight": weight,
                              "status": "EMPTY_GLOBAL_ONLY" if not count else (
                                  "SPARSE_CONDITIONAL_POOLED" if count < MIN_OBSERVATIONS else "CONDITIONAL_POOLED"),
                              "conditional_shrinkage": conditional["shrinkage"] if conditional else None,
                              "warnings": conditional["warnings"] if conditional else [],
                              "covariance": pooled}
    current_vol = float(realized.iloc[-1])
    active = int(current_vol > threshold)
    return {"covariance": matrices[active], "shrinkage_intensity": global_fit["shrinkage"],
            "regime_state": {"threshold": threshold, "threshold_first": history.index[0].isoformat(),
                             "threshold_last": history.index[-1].isoformat(), "threshold_observations": 252,
                             "realized_vol_window_sessions": 20, "realized_vol_annualization": 252,
                             "current_volatility": current_vol, "active_regime": active,
                             "regimes": states, "origin_regimes": labels.to_numpy(int),
                             "source_binding": copy.deepcopy(realized.attrs), "cutoff": cutoff.isoformat()},
            "estimation_notes": ["One cutoff-frozen threshold classifies prior origins using strictly-prior volatility.",
                                 "These labels are not each historical origin's own then-known PIT threshold history.",
                                 "Empty regimes pool with n=0 and weight=0; nonempty sparse regimes keep the fixed n/(n+60) rule."]}


def compute_extension(method, stocks, *, qqq_returns=None, qqq_daily=None,
                      industry_groups=None, cutoff, learn: Callable):
    """Return covariance on explicitly estimated assets; blocked assets stay blocked.

    The callback must reserve before ``compute`` and never refund failed attempts.
    Repeated states may reuse only exact source/cutoff/asset/input identities. This
    pure module does not certify maturity, FF48 lineage, or source authenticity.
    """
    name = str(method).upper().strip()
    if name not in METHODS:
        raise ValueError(f"UNKNOWN_RISK_EXTENSION:{method}")
    cutoff = pd.Timestamp(cutoff)
    if pd.isna(cutoff) or cutoff >= pd.Timestamp("2026-01-01", tz=cutoff.tzinfo):
        _block("LEARNED_STATE_CUTOFF_MUST_BE_PRE_2026")
    calc = _Calculations(learn)
    frame, centered, mean, coverage, blocked = _prepare(stocks, cutoff, calc)
    if name == "RB":
        result = _rb(frame, centered, qqq_returns, cutoff, calc)
    elif name == "RH":
        result = _rh(frame, centered, qqq_returns, industry_groups, cutoff, calc)
    elif name == "RT":
        result = _rt(frame, centered, calc)
    else:
        result = _rr(frame, centered, qqq_daily, cutoff, calc)
    covariance, psd = calc.transform("covariance_psd_check", [result["covariance"]],
                                     lambda: validate_covariance(result["covariance"]))
    result["covariance"] = covariance
    result.setdefault("estimated_assets", tuple(frame.columns))
    result["blocked_assets"] = {**blocked, **result.get("blocked_assets", {})}
    result.update(method=name, cutoff=cutoff.isoformat(), coverage=coverage,
                  effective_sample_size={asset: int(frame[asset].notna().sum())
                                         for asset in result["estimated_assets"]},
                  deterministic_transforms=calc.transforms, psd=psd,
                  stock_observed_mean=mean.to_dict())
    for field in ("qqq_relative_state", "downside_state", "regime_state"):
        result.setdefault(field, None)
    return result




