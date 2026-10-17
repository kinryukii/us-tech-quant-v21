"""Frozen P2 receipts and thin Q/action/G integration; no fits or account replay.

All numerical allocation, exposure and action operations reuse their current
owners. This module supplies missing source/clock/identity contracts around
those APIs. Synthetic and explicitly activated frozen-history mechanism use are
distinct. Neither path grants historical quote authority or PIT promotion.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from typing import Any, Mapping

import numpy as np
import pandas as pd

from scripts.research.a2.portfolio.joint_allocation_methods import (
    AllocationUnavailable, TradingControlPolicy, allocate_q, exposure,
)
from scripts.research.a2.inference.joint_stateful_policy import RuleStatefulPolicy
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision
from scripts.research.a2.risk.shared_risk_engine_r2 import SourceReceipt, RiskState, SCHEDULE
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash

P2_MEMBERS = ("ridge", "hgb", "xgb_rank", "logistic", "cat_uncertainty")
Q_METHODS = {"Q0": "mean_variance", "Q1": "gmv", "Q2": "mean_cvar", "Q3": "cost_aware"}
G_METHODS = {"G0": "fixed", "G1": "volatility_targeting", "G2": "dynamic"}
EPS = 1e-10
PRE2026 = pd.Timestamp("2026-01-01")


class AdapterBlocked(AllocationUnavailable):
    """The caller must preserve holdings; no silent source or role substitute."""


def _stamp(value, label):
    try:
        stamp = pd.Timestamp(value)
    except (ValueError, TypeError) as error:
        raise AdapterBlocked("INVALID_CLOCK:" + label) from error
    if pd.isna(stamp):
        raise AdapterBlocked("INVALID_CLOCK:" + label)
    return stamp.tz_convert("UTC") if stamp.tzinfo is not None else stamp


def _pre2026(stamp):
    boundary = PRE2026.tz_localize("UTC") if stamp.tzinfo is not None else PRE2026
    return stamp < boundary


def _same_clock_domain(reference, *values):
    if any((reference.tzinfo is None) != (value.tzinfo is None) for value in values):
        raise AdapterBlocked("MIXED_NAIVE_AWARE_CLOCKS")


def _field(obj, name):
    try:
        return obj[name] if isinstance(obj, Mapping) else getattr(obj, name)
    except (KeyError, AttributeError) as error:
        raise AdapterBlocked("MISSING_CONTRACT_FIELD:" + name) from error


@dataclass(frozen=True)
class FrozenSourceBinding:
    source_identity: str
    source_version: str
    source_sha256: str
    return_coordinate: str
    horizon_sessions: int
    identity_epoch: str

    def validate(self):
        if any(not isinstance(v, str) or not v.strip() for v in (
            self.source_identity, self.source_version, self.return_coordinate, self.identity_epoch
        )):
            raise AdapterBlocked("INVALID_SOURCE_BINDING")
        if (len(self.source_sha256) != 64 or
                any(c not in "0123456789abcdef" for c in self.source_sha256) or
                self.horizon_sessions != 5):
            raise AdapterBlocked("INVALID_SOURCE_SHA_OR_FIVE_SESSION_UNIT")

    @classmethod
    def from_receipt(cls, receipt):
        result = cls(**{key: _field(receipt, key) for key in cls.__dataclass_fields__})
        result.validate()
        return result


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def legal_calendar_sha256(sessions):
    return content_hash(tuple(_stamp(v, "legal_session").isoformat() for v in sessions))


def risk_state_sha256(state):
    """Bind the whole existing typed state; no covariance or learned state is made."""
    return content_hash({key: _field(state, key) for key in RiskState.__dataclass_fields__})


@dataclass(frozen=True)
class FrozenMechanismActivation:
    scientific_contract_identity: str
    scientific_contract_sha256: str
    research_id: str
    run_id: str
    family_freeze_sha256: str
    legal_calendar_sha256: str
    status: str = "FROZEN_FAMILY_ACTIVATED"
    allowed_risk_methods: tuple[str, ...] = tuple(SCHEDULE)
    allowed_q_roles: tuple[str, ...] = tuple(Q_METHODS)
    allowed_action_roles: tuple[str, ...] = ("A0", "A1", "A2")
    allowed_gross_roles: tuple[str, ...] = tuple(G_METHODS)
    strict_PIT_promotion_eligible: bool = False
    certified_NAV: bool = False
    quote_qualified: bool = False
    historical_authority_status: str = "UNKNOWN"
    allow_weak_prior_rms: bool = False
    allowed_cost_bps: tuple[int, ...] = (5, 10, 20)

    def digest(self):
        return content_hash(self)

    def validate(self, expected_sha256, decision_asof):
        if self.digest() != expected_sha256 or not _sha(expected_sha256):
            raise AdapterBlocked("FROZEN_MECHANISM_ACTIVATION_MUTATION")
        if (self.status != "FROZEN_FAMILY_ACTIVATED" or
                any(not isinstance(v, str) or not v.strip() for v in
                    (self.scientific_contract_identity, self.research_id, self.run_id)) or
                not all(_sha(v) for v in (self.scientific_contract_sha256, self.family_freeze_sha256,
                                        self.legal_calendar_sha256)) or
                self.strict_PIT_promotion_eligible is not False or self.certified_NAV is not False or
                self.quote_qualified is not False or self.historical_authority_status != "UNKNOWN" or
                type(self.allow_weak_prior_rms) is not bool):
            raise AdapterBlocked("EXPLICIT_UNCERTIFIED_MECHANISM_FAMILY_REQUIRED")
        if (decision_asof.tzinfo is None or not _pre2026(decision_asof) or
                not set(self.allowed_risk_methods).issubset(SCHEDULE) or
                not set(self.allowed_q_roles).issubset(Q_METHODS) or
                not set(self.allowed_action_roles).issubset({"A0", "A1", "A2"}) or
                not set(self.allowed_gross_roles).issubset(G_METHODS) or
                not self.allowed_cost_bps or any(type(v) is not int or v not in (5, 10, 20) for v in self.allowed_cost_bps)):
            raise AdapterBlocked("FROZEN_PRE2026_MECHANISM_SCOPE_REQUIRED")


def _mechanism_source(receipt, binding, cutoff, activation, expected_activation_sha256, asof):
    if not isinstance(activation, FrozenMechanismActivation):
        raise AdapterBlocked("TYPED_FROZEN_MECHANISM_ACTIVATION_REQUIRED")
    activation.validate(expected_activation_sha256, asof)
    try:
        source = receipt if isinstance(receipt, SourceReceipt) else SourceReceipt(**{
            key: _field(receipt, key) for key in SourceReceipt.__dataclass_fields__})
        source.validate(cutoff)
    except (ValueError, TypeError) as error:
        raise AdapterBlocked("MECHANISM_SOURCE_VALIDATION:"+str(error)) from error
    physical_binding = FrozenSourceBinding.from_receipt(
        asdict(source) | dict(horizon_sessions=binding.horizon_sessions)
        if isinstance(receipt, SourceReceipt) else receipt)
    if (source.synthetic is not False or source.mechanism is not True or
            source.scientific_contract_identity != activation.scientific_contract_identity or
            source.scientific_contract_sha256 != activation.scientific_contract_sha256 or
            physical_binding != binding):
        raise AdapterBlocked("MECHANISM_SOURCE_OR_SCIENTIFIC_CONTRACT_MISMATCH")
    return source


@dataclass(frozen=True)
class RiskStateUseReceipt:
    risk_state_id: str
    risk_state_sha256: str
    source: FrozenSourceBinding
    assets: tuple[str, ...]
    identity_epoch: str
    method: str
    fit_as_of: str
    fit_cutoff: str
    next_refresh_as_of: str
    legal_sessions: tuple[str, ...]
    frozen_sha256: str = ""

    def digest(self):
        value = asdict(self); value.pop("frozen_sha256")
        return content_hash(value)

    def seal(self):
        return replace(self, frozen_sha256=self.digest())

    def validate(self, state, binding, activation, expected_sha256, decision_asof):
        if (not expected_sha256 or self.frozen_sha256 != expected_sha256 or
                self.digest() != expected_sha256):
            raise AdapterBlocked("FROZEN_RISK_STATE_USE_RECEIPT_MUTATION")
        if (self.risk_state_id != _field(state, "risk_state_id") or
                self.risk_state_sha256 != risk_state_sha256(state) or self.source != binding or
                self.assets != tuple(_field(state, "assets")) or self.identity_epoch != binding.identity_epoch or
                self.method != _field(state, "method") or self.method not in activation.allowed_risk_methods):
            raise AdapterBlocked("RISK_STATE_USE_SOURCE_IDENTITY_OR_METHOD_MISMATCH")
        sessions = pd.DatetimeIndex([_stamp(v, "legal_session") for v in self.legal_sessions])
        if (sessions.empty or sessions.tz is None or sessions.has_duplicates or
                sessions.normalize().has_duplicates or not sessions.is_monotonic_increasing or
                legal_calendar_sha256(self.legal_sessions) != activation.legal_calendar_sha256):
            raise AdapterBlocked("FROZEN_LEGAL_SESSION_CALENDAR_REQUIRED")
        fit, cutoff, refresh = (_stamp(self.fit_as_of, "fit_asof"), _stamp(self.fit_cutoff, "fit_cutoff"),
                                _stamp(self.next_refresh_as_of, "next_refresh_asof"))
        _same_clock_domain(decision_asof, fit, cutoff, refresh)
        if fit != _stamp(_field(state, "as_of"), "state_asof") or cutoff != _stamp(_field(state, "cutoff"), "state_cutoff"):
            raise AdapterBlocked("RISK_STATE_USE_CLOCK_MISMATCH")
        i = sessions.normalize().get_indexer([fit.normalize()])[0]
        if i <= 0 or cutoff != sessions[i-1] or decision_asof.normalize() not in sessions.normalize():
            raise AdapterBlocked("FIT_OR_APPLICATION_NOT_ON_FROZEN_LEGAL_CALENDAR")
        period = {"annual": "Y", "quarterly": "Q", "monthly": "M"}[SCHEDULE[self.method]]
        periods = sessions.tz_localize(None).to_period(period)
        if np.flatnonzero(periods == periods[i])[0] != i:
            raise AdapterBlocked("RISK_FIT_NOT_AT_REGISTERED_REFRESH_SESSION")
        later = np.flatnonzero((np.arange(len(sessions)) > i) & (periods != periods[i]))
        expected_refresh = sessions[int(later[0])] if len(later) else PRE2026.tz_localize("UTC")
        j = sessions.normalize().get_indexer([decision_asof.normalize()])[0]
        if (refresh != expected_refresh or periods[j] != periods[i] or
                not cutoff < fit <= decision_asof < refresh):
            raise AdapterBlocked("RISK_STATE_CARRY_EXPIRED_OR_FUTURE")


@dataclass(frozen=True)
class FrozenForecastSupport:
    assets: tuple[str, ...]
    required_assets: tuple[str, ...]
    signal_asof: str
    basis: str = "ACTUAL_PIT_BUY_ELIGIBLE_UNION_HELD"
    frozen_sha256: str = ""

    def digest(self):
        value=asdict(self); value.pop("frozen_sha256")
        return content_hash(value)

    def seal(self): return replace(self,frozen_sha256=self.digest())

    def required_mask(self, assets, asof, expected_sha256, ctx=None):
        if (self.frozen_sha256!=expected_sha256 or self.digest()!=expected_sha256 or
                self.assets!=tuple(assets) or self.basis!="ACTUAL_PIT_BUY_ELIGIBLE_UNION_HELD" or
                _stamp(self.signal_asof,"forecast_support_asof")!=asof or
                self.required_assets!=tuple(a for a in assets if a in self.required_assets)):
            raise AdapterBlocked("EXACT_FROZEN_FORECAST_SUPPORT_REQUIRED")
        mask=np.isin(assets,self.required_assets)
        if ctx is not None:
            actual=(ctx.current_units[0]>EPS) | (ctx.current_weights[0]>EPS) | (ctx.decision_mask[0]&ctx.buy_allowed[0])
            if not np.array_equal(mask,actual):
                raise AdapterBlocked("FORECAST_SUPPORT_CANNOT_SHRINK_ACTUAL_PIT_ELIGIBLE_OR_HELD")
        return mask


def _required_forecasts(mu, sigma, n, required):
    # Preserve NaN for inactive forecasts; convert only actual required values.
    raw_mu,raw_sigma=np.asarray(mu,dtype=object),np.asarray(sigma,dtype=object)
    if raw_mu.shape!=(n,) or raw_sigma.shape!=(n,):
        raise AdapterBlocked("FORECAST_ASSET_COORDINATES_OR_UNCERTAINTY_INVALID")
    mean,uncertainty=np.full(n,np.nan),np.full(n,np.nan)
    try:
        mean[required]=np.asarray(raw_mu[required],float)
        uncertainty[required]=np.asarray(raw_sigma[required],float)
    except (ValueError,TypeError) as error:
        raise AdapterBlocked("REQUIRED_FORECAST_NUMERIC_VALUE_REQUIRED") from error
    if not np.isfinite(mean[required]).all() or not np.isfinite(uncertainty[required]).all() or np.any(uncertainty[required]<0):
        raise AdapterBlocked("ACTUAL_REQUIRED_FORECAST_OR_UNCERTAINTY_MISSING")
    return mean,uncertainty


@dataclass(frozen=True)
class FrozenCalibratedOOFReceipt:
    """Canonical member-major arrays, one common chronological OOF support.

    Prior RMS is supplied by an already frozen bridge_calibration state: the
    per-asset RMS error of the equal-member calibrated genuine OOF mean by
    default. Explicit mechanism activation may instead declare a frozen bridge
    in-training residual RMS as weak coverage; it grants no calibrated uncertainty
    certification and never calls that residual genuine OOF.
    Generating that statistic is an upstream learned operation. Apply checks
    provenance clocks but never estimates RMS or reads prior numeric targets.
    Prior arrays are optional audit payload with a separately frozen hash.
    """
    receipt_id: str
    source: FrozenSourceBinding
    assets: tuple[str, ...]
    members: tuple[str, ...]
    cutoff: str
    available_at: str
    current_fit_cutoffs: tuple[str, ...]
    current_calibration_cutoffs: tuple[str, ...]
    calibrated_mu: tuple[tuple[float, ...], ...]
    origins: tuple[str, ...]
    label_maturities: tuple[str, ...]
    target_available_at: tuple[str, ...]
    predicted_at: tuple[tuple[str, ...], ...]
    fit_cutoffs: tuple[tuple[str, ...], ...]
    calibration_cutoffs: tuple[tuple[str, ...], ...]
    prior_calibrated_mu: tuple[tuple[tuple[float, ...], ...], ...]
    prior_targets: tuple[tuple[float, ...], ...]
    status: str = "PASS_SYNTHETIC"
    synthetic: bool = True
    genuine_chronological_oof: bool = True
    frozen: bool = True
    frozen_sha256: str = ""
    frozen_prior_oof_rms: tuple[float, ...] = ()
    prior_oof_payload_sha256: str = ""
    prior_rms_coverage: str = "GENUINE_CHRONOLOGICAL_OOF_RMS"
    mechanism_source_receipt: object = None

    def digest(self):
        # Apply binds an upstream prior-payload SHA without traversing targets.
        excluded = {"frozen_sha256", "prior_calibrated_mu", "prior_targets"}
        value = {key: getattr(self, key) for key in self.__dataclass_fields__ if key not in excluded}
        value["source"] = asdict(self.source)
        if self.mechanism_source_receipt is not None:
            value["mechanism_source_receipt"] = content_hash(self.mechanism_source_receipt)
        return content_hash(value)

    def seal(self):
        """Synthetic upstream binding helper; never estimates or qualifies RMS.

        Production must supply the existing frozen bridge receipt. Calling this
        helper creates no learned state, source authority or activation.
        """
        payload = dict(prior_calibrated_mu=self.prior_calibrated_mu, prior_targets=self.prior_targets)
        prior_sha = content_hash(payload)
        sealed = replace(self, prior_oof_payload_sha256=prior_sha)
        return replace(sealed, frozen_sha256=sealed.digest())


@dataclass(frozen=True)
class P2Disagreement:
    assets: tuple[str, ...]
    calibrated_mean: np.ndarray
    prior_oof_rms: np.ndarray
    member_variance: np.ndarray
    sigma: np.ndarray
    receipt_sha256: str
    physical_fit_count: int = 0
    rms_generation_budget_kind: str = "bridge_calibration"
    rms_generation_executed: bool = False
    weak_coverage: bool = False
    prior_rms_coverage: str = "GENUINE_CHRONOLOGICAL_OOF_RMS"
    calibrated_uncertainty_certified: bool = False
    strict_PIT_promotion_eligible: bool = False


def p2_receipt_contract():
    return dict(schema="FROZEN_CALIBRATED_OOF_P2_R2",
                fields=list(FrozenCalibratedOOFReceipt.__dataclass_fields__),
                activation="Explicit frozen-history family activation; no PIT promotion",
                weak_coverage="BRIDGE_IN_TRAINING_RESIDUAL_FROZEN_RMS requires explicit activation.allow_weak_prior_rms; never genuine OOF or certified calibrated uncertainty",
                required_prior_statistic="nonempty frozen_prior_oof_rms aligned exactly to assets",
                rms_source="default genuine chronological OOF equal-member-mean date-equal RMS; weak bridge in-training residual reuse must be explicit",
                rms_generation_physical_kind="bridge_calibration",
                apply="sqrt(frozen_prior_oof_rms**2 + population_var(current calibrated five-member mu))",
                apply_prior_target_numeric_access=False, apply_physical_fit_count=0,
                prior_arrays="audit-only; frozen upstream prior_oof_payload_sha256 is bound in apply identity")


def compute_p2_disagreement(receipt: FrozenCalibratedOOFReceipt, *, assets, as_of,
                            prior_cutoff, expected_source: FrozenSourceBinding,
                            expected_receipt_sha256: str, execution_mode="synthetic",
                            mechanism_activation=None, expected_activation_sha256=None,
                            forecast_support=None, expected_forecast_support_sha256=None) -> P2Disagreement:
    """Apply a frozen bridge RMS; no target-based statistic is estimated here."""
    expected_source.validate()
    if not isinstance(receipt, FrozenCalibratedOOFReceipt):
        raise AdapterBlocked("TYPED_FROZEN_CALIBRATED_OOF_RECEIPT_REQUIRED")
    if receipt.source != expected_source:
        raise AdapterBlocked("OOF_SOURCE_OR_VERSION_MUTATION")
    if receipt.members != P2_MEMBERS:
        raise AdapterBlocked("MISSING_OR_REORDERED_REQUIRED_P2_MEMBER")
    if tuple(assets) != receipt.assets or len(set(receipt.assets)) != len(receipt.assets):
        raise AdapterBlocked("OOF_ASSET_IDENTITY_OR_COMMON_SUPPORT_MISMATCH")
    weak = receipt.prior_rms_coverage == "BRIDGE_IN_TRAINING_RESIDUAL_FROZEN_RMS"
    if (not receipt.frozen or receipt.prior_rms_coverage not in
            {"GENUINE_CHRONOLOGICAL_OOF_RMS", "BRIDGE_IN_TRAINING_RESIDUAL_FROZEN_RMS"} or
            (not weak and not receipt.genuine_chronological_oof) or (weak and receipt.genuine_chronological_oof)):
        raise AdapterBlocked("GENUINE_OOF_OR_EXPLICIT_WEAK_FROZEN_RMS_COVERAGE_REQUIRED")
    if execution_mode == "synthetic":
        if not receipt.synthetic:
            raise AdapterBlocked("SCIENTIFIC_ACTIVATION_PENDING_REAL_OOF_DISABLED")
        if receipt.status != "PASS_SYNTHETIC" or weak:
            raise AdapterBlocked("OOF_SOURCE_QUALIFICATION_REQUIRED")
    elif execution_mode == "frozen_history_mechanism":
        if receipt.synthetic is not False or receipt.status != "PASS_FROZEN_HISTORY_MECHANISM":
            raise AdapterBlocked("MECHANISM_PRIOR_RMS_RECEIPT_REQUIRED")
        _mechanism_source(receipt.mechanism_source_receipt, receipt.source, _stamp(receipt.cutoff, "cutoff"),
            mechanism_activation, expected_activation_sha256, _stamp(as_of, "asof"))
        if weak and mechanism_activation.allow_weak_prior_rms is not True:
            raise AdapterBlocked("EXPLICIT_WEAK_BRIDGE_RESIDUAL_ACTIVATION_REQUIRED")
    else:
        raise AdapterBlocked("EXPLICIT_EXECUTION_MODE_REQUIRED")
    try:
        digest = receipt.digest()
    except (ValueError, TypeError) as error:
        raise AdapterBlocked("NONFINITE_OR_MUTATED_OOF_PAYLOAD") from error
    if not expected_receipt_sha256 or receipt.frozen_sha256 != expected_receipt_sha256 or digest != expected_receipt_sha256:
        raise AdapterBlocked("FROZEN_OOF_RECEIPT_MUTATION")
    asof, cutoff, prior = (_stamp(as_of, "as_of"), _stamp(receipt.cutoff, "cutoff"),
                            _stamp(prior_cutoff, "prior_cutoff"))
    available = _stamp(receipt.available_at, "available_at")
    _same_clock_domain(asof, cutoff, prior, available)
    if not cutoff <= prior < asof or not _pre2026(cutoff) or not cutoff <= available <= asof:
        raise AdapterBlocked("OOF_FUTURE_CUTOFF_OR_2026_GUARD")
    n, m = len(receipt.assets), len(receipt.origins)
    required=(forecast_support.required_mask(receipt.assets,asof,expected_forecast_support_sha256)
              if isinstance(forecast_support,FrozenForecastSupport) else np.ones(n,bool))
    if forecast_support is not None and not isinstance(forecast_support,FrozenForecastSupport):
        raise AdapterBlocked("TYPED_FROZEN_FORECAST_SUPPORT_REQUIRED")
    try:
        raw_current = np.asarray(receipt.calibrated_mu,dtype=object)
        raw_rms = np.asarray(receipt.frozen_prior_oof_rms,dtype=object)
        current = np.full((5,n),np.nan); rms=np.full(n,np.nan)
        if raw_current.shape!=(5,n) or raw_rms.shape!=(n,):
            raise AdapterBlocked("OOF_CURRENT_OR_FROZEN_RMS_SHAPE")
        current[:,required]=np.asarray(raw_current[:,required],float)
        rms[required]=np.asarray(raw_rms[required],float)
    except (ValueError, TypeError) as error:
        raise AdapterBlocked("OOF_CURRENT_OR_FROZEN_RMS_SHAPE") from error
    if (m == 0 or not np.isfinite(current[:,required]).all() or
            not np.isfinite(rms[required]).all() or np.any(rms[required] < 0)):
        raise AdapterBlocked("FROZEN_PRIOR_OOF_RMS_REQUIRED_OR_COMMON_SUPPORT_FAILURE")
    if (len(receipt.prior_oof_payload_sha256) != 64 or
            any(c not in "0123456789abcdef" for c in receipt.prior_oof_payload_sha256)):
        raise AdapterBlocked("FROZEN_UPSTREAM_PRIOR_OOF_PAYLOAD_SHA_REQUIRED")
    # Structural topology only; prior numeric arrays are never transformed or inspected.
    if (len(receipt.prior_calibrated_mu) != 5 or
            any(len(member) != m or any(len(row) != n for row in member)
                for member in receipt.prior_calibrated_mu) or
            len(receipt.prior_targets) != m or any(len(row) != n for row in receipt.prior_targets)):
        raise AdapterBlocked("OOF_COMMON_SUPPORT_SHAPE")
    origins = [_stamp(v, "origin") for v in receipt.origins]
    if origins != sorted(set(origins)):
        raise AdapterBlocked("OOF_ORIGINS_MUST_BE_UNIQUE_CHRONOLOGICAL")
    if len(receipt.label_maturities) != m or len(receipt.target_available_at) != m:
        raise AdapterBlocked("OOF_LABEL_CLOCK_SHAPE")
    for j, origin in enumerate(origins):
        maturity = _stamp(receipt.label_maturities[j], "maturity")
        target_at = _stamp(receipt.target_available_at[j], "target_available_at")
        _same_clock_domain(cutoff, origin, maturity, target_at)
        if not origin < maturity <= target_at <= cutoff or not _pre2026(target_at):
            raise AdapterBlocked("OOF_IMMATURE_OR_FUTURE_TARGET")
    for clock in (receipt.current_fit_cutoffs, receipt.current_calibration_cutoffs):
        parsed = [_stamp(v, "current_learned_cutoff") for v in clock]
        _same_clock_domain(cutoff, *parsed)
        if len(clock) != 5 or any(v > cutoff for v in parsed):
            raise AdapterBlocked("FUTURE_CURRENT_LEARNED_CUTOFF")
    for clocks in (receipt.predicted_at, receipt.fit_cutoffs, receipt.calibration_cutoffs):
        if len(clocks) != 5 or any(len(row) != m for row in clocks):
            raise AdapterBlocked("MEMBER_OOF_CLOCK_SHAPE")
    for member in range(5):
        for j, origin in enumerate(origins):
            fit = _stamp(receipt.fit_cutoffs[member][j], "fit_cutoff")
            calibration = _stamp(receipt.calibration_cutoffs[member][j], "calibration_cutoff")
            predicted = _stamp(receipt.predicted_at[member][j], "predicted_at")
            maturity = _stamp(receipt.label_maturities[j], "maturity")
            _same_clock_domain(origin, fit, calibration, predicted)
            if weak:
                if max(fit, calibration, predicted) > cutoff or predicted < origin:
                    raise AdapterBlocked("WEAK_BRIDGE_RESIDUAL_FUTURE_TRAINING_OR_PREDICTION")
            else:
                if not (fit < origin and calibration < origin):
                    raise AdapterBlocked("OOF_IN_SAMPLE_OR_FUTURE_TRAINING")
                if not origin <= predicted < maturity:
                    raise AdapterBlocked("OOF_PREDICTION_NOT_BEFORE_LABEL_MATURITY")
    variance,mean,sigma=np.full(n,np.nan),np.full(n,np.nan),np.full(n,np.nan)
    variance[required]=np.var(current[:,required],axis=0,ddof=0)
    mean[required]=current[:,required].mean(axis=0)
    sigma[required]=np.sqrt(rms[required]**2+variance[required])
    return P2Disagreement(receipt.assets, mean, rms, variance, sigma, digest, weak_coverage=weak, prior_rms_coverage=receipt.prior_rms_coverage)


@dataclass(frozen=True)
class MatureScenarioReceipt:
    """No fallback: a real CVaR source needs independently qualified lineage."""
    assets: tuple[str, ...]
    source: FrozenSourceBinding
    cutoff: str
    available_at: str
    origins: tuple[str, ...]
    label_maturities: tuple[str, ...]
    target_available_at: tuple[str, ...]
    scenarios: tuple[tuple[float, ...], ...]
    status: str
    synthetic: bool
    frozen_sha256: str = ""
    horizon_sessions: int = 5
    mechanism_source_receipt: object = None
    entry_at: tuple[str, ...] = ()
    endpoint_at: tuple[str, ...] = ()

    def digest(self):
        value = asdict(self)
        value.pop("frozen_sha256")
        return content_hash(value)

    def seal(self):
        return replace(self, frozen_sha256=self.digest())


def _scenarios(receipt, assets, source, as_of, cutoff, expected_sha256, *,
               execution_mode="synthetic", activation=None, activation_sha256=None, legal_sessions=()):
    if not isinstance(receipt, MatureScenarioReceipt):
        raise AdapterBlocked("BLOCKED_MATURE_QUALIFIED_SCENARIO_SOURCE")
    if execution_mode == "synthetic":
        if not receipt.synthetic:
            raise AdapterBlocked("SCIENTIFIC_ACTIVATION_PENDING_REAL_SCENARIOS_DISABLED")
        if receipt.status != "PASS_SYNTHETIC":
            raise AdapterBlocked("BLOCKED_MATURE_QUALIFIED_SCENARIO_SOURCE")
    else:
        if receipt.synthetic is not False or receipt.status != "PASS_FROZEN_HISTORY_MECHANISM":
            raise AdapterBlocked("BLOCKED_MATURE_MECHANISM_SCENARIO_SOURCE")
        _mechanism_source(receipt.mechanism_source_receipt, source, _stamp(receipt.cutoff, "scenario_cutoff"),
                          activation, activation_sha256, as_of)
    try:
        digest = receipt.digest()
    except (ValueError, TypeError) as error:
        raise AdapterBlocked("INVALID_SCENARIO_PAYLOAD") from error
    if not expected_sha256 or receipt.frozen_sha256 != expected_sha256 or digest != expected_sha256:
        raise AdapterBlocked("FROZEN_SCENARIO_RECEIPT_MUTATION")
    if receipt.source != source or receipt.assets != tuple(assets):
        raise AdapterBlocked("SCENARIO_SOURCE_OR_ASSET_IDENTITY_MISMATCH")
    if receipt.horizon_sessions != 5:
        raise AdapterBlocked("SCENARIO_FIVE_SESSION_HORIZON_REQUIRED")
    rc = _stamp(receipt.cutoff, "scenario_cutoff")
    available = _stamp(receipt.available_at, "scenario_available")
    _same_clock_domain(as_of, rc, cutoff, available)
    if rc > cutoff or not _pre2026(rc) or not rc <= available <= as_of:
        raise AdapterBlocked("FUTURE_SCENARIO_CUTOFF")
    data = np.asarray(receipt.scenarios, float)
    if data.ndim != 2 or data.shape[1] != len(assets) or len(data) == 0 or not np.isfinite(data).all():
        raise AdapterBlocked("INVALID_MATURE_SCENARIO_SHAPE")
    if not len(data) == len(receipt.origins) == len(receipt.label_maturities) == len(receipt.target_available_at):
        raise AdapterBlocked("SCENARIO_CLOCK_SHAPE")
    origins = [_stamp(v, "scenario_origin") for v in receipt.origins]
    if origins != sorted(set(origins)):
        raise AdapterBlocked("SCENARIO_COMMON_SUPPORT_NOT_CHRONOLOGICAL")
    for origin, maturity, available in zip(origins, receipt.label_maturities, receipt.target_available_at):
        m, a = _stamp(maturity, "scenario_maturity"), _stamp(available, "scenario_target_available")
        _same_clock_domain(rc, origin, m, a)
        if not origin < m <= a <= rc:
            raise AdapterBlocked("IMMATURE_SCENARIO_SOURCE")
    if execution_mode == "frozen_history_mechanism":
        if len(receipt.entry_at) != len(origins) or len(receipt.endpoint_at) != len(origins):
            raise AdapterBlocked("MECHANISM_TRUE_H5_ENDPOINT_RECEIPT_REQUIRED")
        sessions = pd.DatetimeIndex([_stamp(v, "legal_session") for v in legal_sessions]).normalize()
        for origin, entry, endpoint, maturity in zip(origins, receipt.entry_at, receipt.endpoint_at, receipt.label_maturities):
            e, x, m = _stamp(entry, "entry"), _stamp(endpoint, "endpoint"), _stamp(maturity, "maturity")
            _same_clock_domain(rc, origin, e, x, m)
            oi, ei, xi = sessions.get_indexer([origin.normalize(), e.normalize(), x.normalize()])
            if oi < 0 or ei != oi+1 or xi != ei+5 or not origin < e < x <= m:
                raise AdapterBlocked("MECHANISM_SCENARIO_H5_ENDPOINT_OR_MATURITY_MISMATCH")
    return data


@dataclass(frozen=True)
class PortfolioTarget:
    assets: tuple[str, ...]
    weights: np.ndarray
    explicit_mask: np.ndarray
    effective_weights: np.ndarray
    gross: float


@dataclass(frozen=True)
class AdapterResult:
    target: PortfolioTarget
    q: np.ndarray
    requested_gross: float
    q_role: str
    action_role: str
    gross_role: str
    allocation_status: str
    equivalence: str
    risk_state_id: str
    synthetic: bool
    execution_friction_bps: float
    fees_bps: float = 0.
    physical_fit_count: int = 0
    account_replay_count: int = 0
    global_optimum_claim: bool = False
    execution_mode: str = "synthetic"
    scientific_contract_sha256: str = ""
    strict_PIT_promotion_eligible: bool = False
    certified_NAV: bool = False
    quote_qualified: bool = False
    account_execution_friction_bps: float = 10.


class SharedJointAdapter:
    """One explicitly scoped call over existing Q/action/G; no account or fit."""
    def __init__(self, *, q_role="Q0", action_role="A0", gross_role="G0"):
        if q_role not in Q_METHODS or action_role not in {"A0", "A1", "A2"} or gross_role not in G_METHODS:
            raise AdapterBlocked("UNREGISTERED_Q_ACTION_G_ROLE")
        self.q_role, self.action_role, self.gross_role = q_role, action_role, gross_role

    def evaluate(self, risk_state: Any, mu, uncertainty, ctx, *, expected_source: FrozenSourceBinding,
                 prior_cutoff, synthetic_context=None, scenarios=None, expected_scenario_sha256=None,
                 execution_mode="synthetic", mechanism_activation=None, expected_activation_sha256=None,
                 state_use_receipt=None, expected_state_use_sha256=None, cost_bps=10,
                 forecast_support=None, expected_forecast_support_sha256=None) -> AdapterResult:
        if type(cost_bps) is not int or cost_bps not in (5, 10, 20):
            raise AdapterBlocked("FROZEN_5_10_20_BPS_COST_SCENARIO_REQUIRED")
        if execution_mode not in {"synthetic", "frozen_history_mechanism"}:
            raise AdapterBlocked("EXPLICIT_EXECUTION_MODE_REQUIRED")
        if execution_mode == "synthetic" and synthetic_context is not True:
            raise AdapterBlocked("SYNTHETIC_CONTEXT_REQUIRED_NO_ACCOUNT_ACTIVATION")
        if execution_mode == "frozen_history_mechanism" and synthetic_context is True:
            raise AdapterBlocked("MECHANISM_CANNOT_USE_SYNTHETIC_CONTEXT")
        source = FrozenSourceBinding.from_receipt(_field(risk_state, "source_receipt"))
        if source != expected_source:
            raise AdapterBlocked("RISK_SOURCE_OR_VERSION_MUTATION")
        status = _field(risk_state, "status")
        receipt = _field(risk_state, "source_receipt")
        if execution_mode == "synthetic":
            if status == "QUALIFIED" and not bool(_field(receipt, "synthetic")):
                raise AdapterBlocked("SCIENTIFIC_ACTIVATION_PENDING_REAL_RISK_DISABLED")
            if status != "PASS_SYNTHETIC":
                raise AdapterBlocked("RISK_STATE_NOT_QUALIFIED")
            if _field(receipt, "status") != "QUALIFIED_SYNTHETIC" or _field(receipt, "synthetic") is not True:
                raise AdapterBlocked("RISK_RECEIPT_STATUS_MISMATCH")
        elif status != "PASS_FROZEN_HISTORY_MECHANISM":
            raise AdapterBlocked("RISK_STATE_NOT_QUALIFIED_FOR_MECHANISM")
        assets = tuple(str(v) for v in _field(risk_state, "assets"))
        if tuple(ctx.tickers) != assets or len(set(assets)) != len(assets):
            raise AdapterBlocked("RISK_ASSET_IDENTITY_MISMATCH")
        if any(_field(risk_state, key) != getattr(source, key) for key in ("source_identity", "return_coordinate", "identity_epoch")):
            raise AdapterBlocked("RISK_SOURCE_UNIT_OR_IDENTITY_MISMATCH")
        horizon = _field(risk_state, "horizon")
        if horizon != 5:
            raise AdapterBlocked("RISK_ADAPTER_REQUIRES_FIVE_SESSION_COVARIANCE")
        asof = _stamp(_field(risk_state, "as_of"), "risk_as_of")
        cutoff = _stamp(_field(receipt, "cutoff"), "risk_cutoff")
        prior = _stamp(prior_cutoff, "prior_cutoff")
        _same_clock_domain(asof, cutoff, prior, _stamp(ctx.signal_asof, "context_asof"))
        if _stamp(_field(risk_state, "cutoff"), "risk_state_cutoff") != cutoff:
            raise AdapterBlocked("RISK_CUTOFF_RECEIPT_MISMATCH")
        decision_asof = _stamp(ctx.signal_asof, "context_asof")
        if not cutoff <= prior < decision_asof or not cutoff < asof <= decision_asof or not _pre2026(cutoff):
            raise AdapterBlocked("RISK_FUTURE_CUTOFF_OR_2026_GUARD")
        if execution_mode == "synthetic":
            if asof != decision_asof:
                raise AdapterBlocked("SYNTHETIC_RISK_ASOF_CONTEXT_MISMATCH")
        else:
            _mechanism_source(receipt, source, cutoff, mechanism_activation, expected_activation_sha256, decision_asof)
            if cost_bps not in mechanism_activation.allowed_cost_bps:
                raise AdapterBlocked("COST_NOT_IN_FROZEN_MECHANISM_FAMILY")
            if (self.q_role not in mechanism_activation.allowed_q_roles or
                    self.action_role not in mechanism_activation.allowed_action_roles or
                    self.gross_role not in mechanism_activation.allowed_gross_roles):
                raise AdapterBlocked("Q_ACTION_G_NOT_IN_FROZEN_MECHANISM_FAMILY")
            if not isinstance(state_use_receipt, RiskStateUseReceipt):
                raise AdapterBlocked("TYPED_FROZEN_RISK_STATE_USE_RECEIPT_REQUIRED")
            state_use_receipt.validate(risk_state, source, mechanism_activation, expected_state_use_sha256, decision_asof)
        covariance = np.asarray(_field(risk_state, "covariance"), float)
        n = len(assets)
        if (covariance.shape != (n, n) or not np.isfinite(covariance).all() or
                not np.allclose(covariance, covariance.T, rtol=0, atol=1e-12) or
                np.any(np.diag(covariance) <= 0) or np.linalg.eigvalsh(covariance).min() < -1e-12):
            raise AdapterBlocked("RISK_COVARIANCE_NOT_FINITE_PSD")
        required=(forecast_support.required_mask(assets,decision_asof,expected_forecast_support_sha256,ctx)
                  if isinstance(forecast_support,FrozenForecastSupport) else np.ones(n,bool))
        if forecast_support is not None and not isinstance(forecast_support,FrozenForecastSupport):
            raise AdapterBlocked("TYPED_FROZEN_FORECAST_SUPPORT_REQUIRED")
        mean,sigma=_required_forecasts(mu,uncertainty,n,required)
        if (len(ctx.path_ids) != 1 or ctx.current_weights.shape != (1, n) or
                ctx.max_positions != 20 or ctx.max_weight != .1 or ctx.max_invested != 1.):
            raise AdapterBlocked("FIXED_SYNTHETIC_FEASIBILITY_CONSTRAINTS_REQUIRED")
        current = np.asarray(ctx.current_weights[0], float)
        if not np.isfinite(current).all() or np.any(current < 0) or current.sum() > 1+EPS:
            raise AdapterBlocked("INVALID_SYNTHETIC_HOLDING_WEIGHTS")
        scenario_data = _scenarios(scenarios, assets, source, decision_asof, cutoff, expected_scenario_sha256,
            execution_mode=execution_mode, activation=mechanism_activation, activation_sha256=expected_activation_sha256,
            legal_sessions=state_use_receipt.legal_sessions if state_use_receipt else ()) if self.q_role == "Q2" else None
        captures = []
        friction = float(cost_bps) if self.q_role == "Q3" else 0.
        ranks = np.argsort(np.argsort(np.asarray(assets), kind="stable"), kind="stable")
        blocked = np.isin(assets, tuple(_field(risk_state, "blocked_assets")))
        common = replace(ctx, decision_mask=ctx.decision_mask & ~blocked[None, :],
                         buy_allowed=ctx.buy_allowed & ~blocked[None, :])

        def base(day, gated):
            held = gated.current_units[0] > EPS
            modeled = gated.decision_mask[0]
            locked = gated.reserved_mask[0].copy() | (held & ~modeled & ~gated.operational_mask[0])
            reserved = np.where(locked, current, 0.)
            allowed = modeled & ~locked & (gated.buy_allowed[0] | held)
            solved = allocate_q(Q_METHODS[self.q_role], mean, sigma, covariance, current,
                                locked, allowed, gated.buy_allowed[0], 20-int(locked.sum()), ranks,
                                scenarios=scenario_data, execution_friction_bps=friction)
            composition, gross = exposure(solved.q, covariance, reserved, G_METHODS[self.gross_role],
                                           mu=mean, uncertainty=sigma)
            captures.append((solved, composition, gross))
            target = gross*composition-reserved
            return TargetDecision(target[None, :], (modeled & ~locked)[None, :])

        if self.action_role == "A0":
            decision = TradingControlPolicy(base, "partial_rebalance")(0, common)
        elif self.action_role == "A1":
            decision = TradingControlPolicy(base, "no_trade_band")(0, common)
        else:
            decision = RuleStatefulPolicy(base, mean[None, None, :], sigma[None, None, :],
                                          no_trade_band=.0025, minimum_trade_usd=0., hysteresis=.5)(0, common)
        weights, explicit = decision.weights[0], decision.explicit_mask[0]
        effective = np.where(explicit, weights, current)
        if (not np.isfinite(effective).all() or np.any(effective < -EPS) or effective.sum() > 1+EPS or
                np.count_nonzero(effective > EPS) > 20 or
                np.any(effective[explicit] > .1+EPS) or
                np.any(effective[~ctx.buy_allowed[0]] > current[~ctx.buy_allowed[0]]+EPS)):
            raise AdapterBlocked("ACTION_TARGET_FEASIBILITY_OR_OUTPOOL_INCREASE")
        solved, composition, gross = captures[0]
        return AdapterResult(PortfolioTarget(assets, weights.copy(), explicit.copy(), effective,
                                             float(effective.sum())), composition.copy(), gross,
                             self.q_role, self.action_role, self.gross_role, solved.status,
                             solved.equivalence, str(_field(risk_state, "risk_state_id")), execution_mode == "synthetic", friction,
                             execution_mode=execution_mode, scientific_contract_sha256=(
                                 mechanism_activation.scientific_contract_sha256 if mechanism_activation else ""),
                             account_execution_friction_bps=float(cost_bps))
