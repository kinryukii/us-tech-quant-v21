"""Additive risk-state adapter over existing pure covariance primitives.

No readers, provider clients, account engine or experiment authority live here.
Synthetic execution and explicitly frozen-history mechanism sources are distinct.
Historical quote/PIT authority is never inferred from a current snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Mapping
import copy
import numpy as np
import pandas as pd

from .joint_risk_estimators import (RiskBundle, _prepare, _estimate, specs,
                                   validate_covariance, RiskEstimatorBlocked)
from .shared_risk_budget_r2 import StateBudget, StateCache, StateBudgetError, content_hash

COORDINATE = "shareholder_value_open_return"
BENCHMARK_PROXY_COORDINATE = "frozen_qfq_open_return_proxy"
METHODS = ("R0", "RD", "RM", "RB", "RH", "RT", "RR", "RU", "RE")
CUTOFF = pd.Timestamp("2026-01-01", tz="UTC")
META = ("asset", "origin_at", "entry_at", "endpoint_at", "matured_at",
        "available_at", "horizon", "uid", "identity_epoch", "source_identity")
SCHEDULE = {m: ("annual" if m == "R0" else "monthly" if m in {"RD", "RB", "RT"} else "quarterly")
            for m in METHODS}


def _time(value):
    t = pd.Timestamp(value)
    if pd.isna(t) or t.tzinfo is None:
        raise ValueError("EXPLICIT_TIMEZONE_REQUIRED")
    return t.tz_convert("UTC")


@dataclass(frozen=True)
class SourceReceipt:
    source_identity: str
    source_version: str
    source_sha256: str
    available_at: object
    synthetic: bool = True
    status: str = "QUALIFIED_SYNTHETIC"
    return_coordinate: str = COORDINATE
    identity_epoch: str = "SYNTHETIC_EPOCH"
    quote_qualified: bool = False
    historical_authority_status: str = "UNKNOWN"

    mechanism: bool = False
    strict_PIT_promotion_eligible: bool = False
    scientific_contract_identity: str = ""
    scientific_contract_sha256: str = ""
    actual_snapshot_timestamp: object = None
    observation_time_assumed: bool = False
    benchmark_proxy_allowed: bool = False

    def validate(self, cutoff, *, role="primary", primary=None):
        cutoff = _time(cutoff)
        if role not in {"primary", "benchmark", "industry"}:
            raise ValueError("EXPLICIT_SOURCE_ROLE_REQUIRED")
        if not self.source_identity or not self.source_version or not self.identity_epoch:
            raise ValueError("SOURCE_VERSION_IDENTITY_REQUIRED")
        if len(self.source_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.source_sha256):
            raise ValueError("PHYSICAL_SOURCE_SHA_REQUIRED")
        if _time(self.available_at) > cutoff:
            raise ValueError("SOURCE_AVAILABILITY_OR_COORDINATE")
        if type(self.synthetic) is not bool or type(self.mechanism) is not bool or self.synthetic == self.mechanism:
            raise ValueError("EXPLICIT_DISTINCT_SOURCE_EXECUTION_MODE_REQUIRED")
        if self.synthetic:
            if self.status != "QUALIFIED_SYNTHETIC":
                raise ValueError("SOURCE_AUTHORITY_UNQUALIFIED")
            if self.return_coordinate != COORDINATE:
                raise ValueError("SOURCE_AVAILABILITY_OR_COORDINATE")
        else:
            if self.status != "FROZEN_HISTORY_MECHANISM_SOURCE_BOUND":
                raise ValueError("FROZEN_HISTORY_MECHANISM_SOURCE_BINDING_REQUIRED")
            if (self.strict_PIT_promotion_eligible is not False or self.quote_qualified is not False
                    or self.historical_authority_status != "UNKNOWN"):
                raise ValueError("MECHANISM_CANNOT_GRANT_HISTORICAL_AUTHORITY")
            if not self.scientific_contract_identity or len(self.scientific_contract_sha256) != 64 or any(
                    c not in "0123456789abcdef" for c in self.scientific_contract_sha256):
                raise ValueError("FROZEN_SCIENTIFIC_CONTRACT_BINDING_REQUIRED")
            if self.observation_time_assumed is not True:
                raise ValueError("EXPLICIT_ASSUMED_OBSERVATION_TIME_REQUIRED")
            if self.actual_snapshot_timestamp is None:
                raise ValueError("ACTUAL_SNAPSHOT_TIMESTAMP_REQUIRED")
            if _time(self.actual_snapshot_timestamp) < _time(self.available_at):
                raise ValueError("SNAPSHOT_PRECEDES_ASSUMED_OBSERVATION_TIME")
            proxy = role == "benchmark" and self.return_coordinate == BENCHMARK_PROXY_COORDINATE
            if self.return_coordinate != COORDINATE and not (proxy and self.benchmark_proxy_allowed is True):
                raise ValueError("SOURCE_AVAILABILITY_OR_COORDINATE")
        if primary is not None:
            if (self.synthetic, self.mechanism) != (primary.synthetic, primary.mechanism):
                raise ValueError("DEPENDENT_SOURCE_EXECUTION_MODE_MISMATCH")
            if self.mechanism and (self.scientific_contract_identity, self.scientific_contract_sha256) != (
                    primary.scientific_contract_identity, primary.scientific_contract_sha256):
                raise ValueError("DEPENDENT_SCIENTIFIC_CONTRACT_MISMATCH")

    def cache_identity(self):
        identity = dict(id=self.source_identity, version=self.source_version, sha256=self.source_sha256)
        if self.mechanism:
            def clock(value):
                try:
                    return _time(value).isoformat()
                except (ValueError, TypeError):
                    return str(value)  # A rejected receipt must still produce a typed BLOCKED state.
            # Human identity is audit lineage; the frozen semantics SHA is physical dependency.
            identity["execution_semantics"] = dict(
                scientific_contract_sha256=self.scientific_contract_sha256,
                status=self.status, return_coordinate=self.return_coordinate,
                identity_epoch=self.identity_epoch, strict_PIT_promotion_eligible=False,
                historical_authority_status=self.historical_authority_status,
                quote_qualified=self.quote_qualified,
                observation_time_assumed=self.observation_time_assumed,
                assumed_observation_at=clock(self.available_at),
                actual_snapshot_timestamp=clock(self.actual_snapshot_timestamp),
                benchmark_proxy_allowed=self.benchmark_proxy_allowed)
        return identity


@dataclass(frozen=True)
class EndpointPair:
    asset: str
    origin_at: object
    entry_at: object
    endpoint_at: object
    entry_open: float
    endpoint_shareholder_value: float
    matured_at: object
    available_at: object
    horizon: int
    uid: str
    identity_epoch: str
    source_identity: str
    shareholder_coordinate_qualified: bool
    source_receipt_id: str


def observations_from_endpoints(pairs, sessions):
    """True h-session endpoints; shareholder value/CA qualification stays caller-owned.

    sessions are explicit legal-session Close timestamps, not an inferred calendar.
    Endpoint value includes source-backed rights/claims per entry share. No CA engine
    is copied, and no price adjustment or invented cash substitute is applied.
    """
    calendar = pd.DatetimeIndex([_time(v) for v in sessions])
    if calendar.empty or calendar.has_duplicates or calendar.normalize().has_duplicates or not calendar.is_monotonic_increasing:
        raise ValueError("LEGAL_CALENDAR_REQUIRED")
    positions = {t.normalize(): i for i, t in enumerate(calendar)}
    rows = []
    for pair in pairs:
        if isinstance(pair.horizon, bool) or pair.horizon not in (1, 3, 5, 10, 20):
            raise ValueError("EXPLICIT_SUPPORTED_HORIZON_REQUIRED")
        o, e, x, m, a = map(_time, (pair.origin_at, pair.entry_at, pair.endpoint_at,
                                   pair.matured_at, pair.available_at))
        if max(o, e, x, m, a) >= CUTOFF:
            raise ValueError("PRE2026_ENDPOINT_REQUIRED")
        if not pair.shareholder_coordinate_qualified or not pair.source_receipt_id:
            raise ValueError("SHAREHOLDER_ENDPOINT_AUTHORITY_REQUIRED")
        oi, ei, xi = (positions.get(t.normalize(), -1) for t in (o, e, x))
        if oi < 0 or ei != oi + 1 or xi != ei + pair.horizon or not o < e < x <= m <= a:
            raise ValueError("HORIZON_ENDPOINT_OR_MATURITY_MISMATCH")
        if not np.isfinite([pair.entry_open, pair.endpoint_shareholder_value]).all() or pair.entry_open <= 0:
            raise ValueError("FINITE_POSITIVE_ENTRY_REQUIRED")
        rows.append(dict(asset=pair.asset, origin_at=o, entry_at=e, endpoint_at=x,
                         matured_at=m, available_at=a, horizon=pair.horizon,
                         uid=pair.uid, identity_epoch=pair.identity_epoch,
                         source_identity=pair.source_identity,
                         source_receipt_id=pair.source_receipt_id,
                         return_value=pair.endpoint_shareholder_value / pair.entry_open - 1))
    return pd.DataFrame(rows)


@dataclass
class RiskInput:
    assets: tuple[str, ...]
    sessions: object
    observations: pd.DataFrame
    source_receipt: SourceReceipt
    asset_uids: Mapping[str, str]
    identity_epoch: str = "SYNTHETIC_EPOCH"
    qqq_observations: pd.DataFrame | None = None
    qqq_receipt: SourceReceipt | None = None
    industry_mapping: pd.DataFrame | None = None
    industry_receipt: SourceReceipt | None = None


@dataclass(frozen=True)
class RiskState:
    risk_state_id: str
    as_of: object
    cutoff: object
    assets: tuple[str, ...]
    source_identity: str
    return_coordinate: str
    horizon: int
    covariance: object
    marginal_sigma: object
    coverage: object
    effective_sample_size: object
    identity_epoch: str
    condition_number: object
    shrinkage_intensity: object
    estimation_uncertainty: object
    model_disagreement: object
    regime_state: object
    downside_state: object
    qqq_relative_state: object
    blocked_assets: tuple[str, ...]
    source_receipt: object
    status: str
    method: str
    fit_dependency_ids: tuple[str, ...] = ()
    notes: object = field(default_factory=dict)


def risk_state_contract():
    return dict(schema="SHARED_RISK_STATE_R2", fields=list(RiskState.__dataclass_fields__),
                coordinate=COORDINATE, output_horizon=5, incremental_directions=list(METHODS[1:]),
                reference="R0 annual existing LW; not a ninth new direction",
                learned_state_binding=["source identity/version/SHA", "cutoff", "assets/UID/epoch",
                                       "eligible values hash", "coordinate/horizon", "fixed params"],
                real_activation="Only explicit frozen-history mechanism receipts plus durable lifecycle reservations",
                strict_PIT_promotion_eligible=False,
                benchmark_proxy_coordinate=BENCHMARK_PROXY_COORDINATE,
                historical_observation_clock="Explicit assumption; current snapshot timestamp is separate provenance",
                source_receipt_fields=list(SourceReceipt.__dataclass_fields__),
                missing_returns="existing primitive observed-column mean / centered absent=0; never price fill",
                no_history="BLOCKED; no median unknown-asset risk qualification",
                RE="Equal covariance average; diag(var member sigma) separate disagreement state, no automatic covariance addition",
                RU="standard4-block jackknife SE=sqrt(3/4*sum((sigma_j-mean_sigma)^2)); replica std also retained",
                covariance_condition_limit=1e12, min_asset_observations=30,
                required_matured_origin_sessions=252,
                overlap="Overlapping h-session returns permitted; dependency retained. Effective independent sample <= floor(origin_count/h).",
                RM="mean_h((5/h)*C_h), fixed equal; time-scale approximation, not alpha target equivalence",
                schema_authority="Engineering interface only; no historical quote authority granted")


def _calendar(inputs, as_of, method):
    if method not in METHODS:
        raise ValueError("UNKNOWN_RISK_DIRECTION")
    as_of = _time(as_of)
    if as_of >= CUTOFF:
        raise ValueError("PRE2026_AS_OF_REQUIRED")
    sessions = pd.DatetimeIndex([_time(t) for t in inputs.sessions])
    if sessions.empty or sessions.has_duplicates or sessions.normalize().has_duplicates or not sessions.is_monotonic_increasing:
        raise ValueError("LEGAL_CALENDAR_REQUIRED")
    dates = sessions.normalize()
    matches = np.flatnonzero(dates == as_of.normalize())
    if len(matches) != 1 or matches[0] == 0:
        raise ValueError("PRIOR_LEGAL_SESSION_REQUIRED")
    i = int(matches[0])
    period = "Y" if SCHEDULE[method] == "annual" else "Q" if SCHEDULE[method] == "quarterly" else "M"
    naive_dates = dates.tz_localize(None)
    periods = naive_dates.to_period(period)
    if np.flatnonzero(periods == periods[i])[0] != i:
        raise ValueError("OFF_SCHEDULE_FIT_USE_FROZEN_PRIOR_STATE")
    cutoff = sessions[i - 1]
    if not cutoff < as_of:
        raise ValueError("PRIOR_SESSION_CUTOFF_REQUIRED")
    return as_of, cutoff, sessions


def _panel(frame, assets, uids, epoch, source, sessions, cutoff, horizon):
    """Inspect clocks first; numeric return values only in the eligible projection."""
    if not isinstance(frame, pd.DataFrame) or any(c not in frame for c in (*META, "return_value")):
        raise ValueError("RETURN_METADATA_SCHEMA_REQUIRED")
    if not assets or len(set(assets)) != len(assets):
        raise ValueError("UNIQUE_ASSETS_REQUIRED")
    clocks = {}
    for c in ("origin_at", "entry_at", "endpoint_at", "matured_at", "available_at"):
        clocks[c] = frame[c].map(_time)
    mask = frame.horizon.eq(horizon) & frame.asset.isin(assets)
    for series in clocks.values():
        mask &= series.lt(cutoff) & series.lt(CUTOFF)
    eligible = frame.loc[mask, list(META) + ["return_value"]].copy()
    for c, values in clocks.items():
        eligible[c] = values[mask]
    if eligible.empty:
        raise ValueError("NO_MATURED_HISTORY")
    if eligible.duplicated(["asset", "origin_at", "horizon"]).any():
        raise ValueError("DUPLICATE_ORIGIN_ASSET")
    if not eligible.source_identity.eq(source.source_identity).all():
        raise ValueError("SOURCE_VERSION_BINDING_MISMATCH")
    if not eligible.identity_epoch.eq(epoch).all():
        raise ValueError("IDENTITY_EPOCH_SWAP")
    if any(row.uid != uids.get(row.asset) for row in eligible.itertuples()):
        raise ValueError("SECURITY_UID_SWAP")
    positions = {t.normalize(): i for i, t in enumerate(sessions)}
    for row in eligible.itertuples():
        oi, ei, xi = (positions.get(t.normalize(), -1) for t in (row.origin_at, row.entry_at, row.endpoint_at))
        if oi < 0 or ei != oi + 1 or xi != ei + horizon:
            raise ValueError("HORIZON_ENDPOINT_MISMATCH")
        if not row.origin_at < row.entry_at < row.endpoint_at <= row.matured_at <= row.available_at:
            raise ValueError("RETURN_MATURITY_ORDER")
    values = pd.to_numeric(eligible.return_value, errors="raise")
    if np.isinf(values.to_numpy(float)).any():
        raise ValueError("INFINITE_RISK_RETURN")
    eligible["return_value"] = values
    return eligible.pivot(index="origin_at", columns="asset", values="return_value").reindex(columns=assets).sort_index()


def _industries(inputs, assets, cutoff):
    receipt = inputs.industry_receipt
    if receipt is None or inputs.industry_mapping is None:
        raise ValueError("PIT_INDUSTRY_SOURCE_REQUIRED")
    receipt.validate(cutoff, role="industry", primary=inputs.source_receipt)
    frame = inputs.industry_mapping
    required = {"asset", "group", "available_at", "effective_at", "identity_epoch", "source_identity"}
    if not required.issubset(frame.columns):
        raise ValueError("INDUSTRY_METADATA_SCHEMA")
    available, effective = frame.available_at.map(_time), frame.effective_at.map(_time)
    legal = frame.loc[available.le(cutoff) & effective.le(cutoff) & frame.asset.isin(assets)].copy()
    if legal.duplicated("asset").any() or set(legal.asset) != set(assets):
        raise ValueError("MISSING_OR_AMBIGUOUS_PIT_INDUSTRY")
    if not legal.identity_epoch.eq(inputs.identity_epoch).all() or not legal.source_identity.eq(receipt.source_identity).all():
        raise ValueError("INDUSTRY_IDENTITY_OR_SOURCE_SWAP")
    groups = legal.set_index("asset").group.reindex(assets)
    groups.attrs.update(pit_qualified=True, available_at=cutoff, effective_at=effective[legal.index].max(),
                        source_id=receipt.source_identity, source_version=receipt.source_version,
                        source_sha256=receipt.source_sha256, identity_epoch=receipt.identity_epoch,
                        source_execution_semantics=receipt.cache_identity(),
                        strict_PIT_promotion_eligible=False,
                        historical_authority_status=receipt.historical_authority_status,
                        observation_time_assumed=receipt.observation_time_assumed)
    return groups


class SharedRiskEngine:
    def __init__(self, *, budget=None):
        self.budget = budget if budget is not None else StateBudget()
        self.cache = None

    def _bound(self, inputs, cutoff, horizon=5):
        receipt = inputs.source_receipt
        context = dict(source_identity=receipt.cache_identity(), cutoff=cutoff.isoformat(),
                       assets=inputs.assets, return_coordinate=receipt.return_coordinate,
                       horizon=horizon, identity_epoch=dict(epoch=inputs.identity_epoch, uids=dict(inputs.asset_uids)),
                       synthetic=receipt.synthetic, mechanism=receipt.mechanism)
        if self.cache is None:
            self.cache = StateCache(self.budget, **context)
        return self.cache.bind(**context)

    @staticmethod
    def _primitive(cache, method, frame, *, kind="covariance", suffix=""):
        """Reuse prepared state and pure estimator; never duplicate old fitter."""
        params = dict(fit_cutoff=cache.context["cutoff"], return_unit=cache.context["return_coordinate"],
                      return_horizon_sessions=cache.context["horizon"],
                      source_id=content_hash(cache.context["source_identity"]),
                      information_set_id=content_hash(cache.context["identity_epoch"]))
        prepare_config = {**specs("LW"), **params}
        names, coverage, prepared = cache.learn(
            "scaler", "stock_preprocessing" + suffix, (frame,),
            lambda: _prepare(frame, prepare_config),
            parameters={**params, "min_observations": 30, "variance_floor": 1e-12})
        if prepared is None or tuple(names[i] for i in prepared["positions"]) != tuple(frame.columns):
            raise RiskEstimatorBlocked("NO_SUBSET_OR_FALLBACK_QUALIFICATION")
        config = {**specs(method), **params}
        covariance, details, count = cache.learn(
            kind, "primitive:" + method + suffix, (prepared, frame.index.tolist()),
            lambda: _estimate(method, prepared, frame.index, tuple(frame.columns), None, None, config),
            parameters=config)
        if count != 1:
            raise RiskEstimatorBlocked("UNACCOUNTED_PRIMITIVE_SUBFIT")
        covariance, psd = cache.learn(
            "deterministic_transform", "primitive_psd:" + method + suffix, (covariance,),
            lambda: validate_covariance(covariance))
        return RiskBundle(method, "FITTED", tuple(names),
                          tuple(v.isoformat() for v in frame.index),
                          estimated_assets=tuple(names), covariance=covariance,
                          coverage=coverage, fitted_state={**details, **psd},
                          budget={"preprocessing_estimates": 1, "estimator_state_estimations": 1})

    def _dependency_closure(self, keys):
        used = set(keys)
        by_key = {e["key"]: e for e in self.budget.events}
        pending = list(used)
        while pending:
            for child in by_key.get(pending.pop(), {}).get("dependencies", ()):
                if child not in used:
                    used.add(child)
                    pending.append(child)
        return tuple(sorted(used))

    def _blocked(self, method, inputs, as_of, cutoff, reason, blocked_assets=None, used_keys=()):
        receipt = asdict(inputs.source_receipt)
        receipt.update(cutoff=str(cutoff), horizon_sessions=5)
        binding = dict(method=method, as_of=str(as_of), cutoff=str(cutoff),
                       assets=inputs.assets, source=inputs.source_receipt.cache_identity(),
                       epoch=inputs.identity_epoch, blocked=reason)
        return RiskState(content_hash(binding), as_of, cutoff, tuple(inputs.assets),
                         inputs.source_receipt.source_identity, inputs.source_receipt.return_coordinate,
                         5, None, None, {}, {}, inputs.identity_epoch, None, None,
                         None, None, None, None, None, tuple(blocked_assets or inputs.assets),
                         receipt, "BLOCKED", method,
                         self._dependency_closure(used_keys),
                         dict(block_reason=reason, real_fit=int(inputs.source_receipt.mechanism and bool(used_keys)),
                              mechanism=inputs.source_receipt.mechanism,
                              strict_PIT_promotion_eligible=False))

    def fit(self, method, inputs, *, as_of):
        """Fit caller-owned observations; unbound source/clock branches stay BLOCKED."""
        cutoff = None
        cache = None
        usage_start = 0
        try:
            as_of, cutoff, sessions = _calendar(inputs, as_of, method)
            inputs.source_receipt.validate(cutoff)
            if inputs.source_receipt.identity_epoch != inputs.identity_epoch:
                raise ValueError("SOURCE_IDENTITY_EPOCH_MISMATCH")
            cache = self._bound(inputs, cutoff)
            usage_start = len(cache.usage_log)
            horizons = (3, 5, 10, 20) if method == "RM" else (5,)
            panels = {h: _panel(inputs.observations, inputs.assets, inputs.asset_uids,
                                inputs.identity_epoch, inputs.source_receipt, sessions, cutoff, h)
                      for h in horizons}
            common = panels[horizons[0]].index
            for h in horizons[1:]:
                common = common.intersection(panels[h].index)
            common = common.sort_values()[-252:]
            if len(common) < 252:
                raise ValueError("INSUFFICIENT_252_MATURED_ORIGINS")
            panels = {h: frame.reindex(common) for h, frame in panels.items()}
            bad = tuple(a for a in inputs.assets if any(frame[a].count() < 30 for frame in panels.values()))
            if bad:
                return self._blocked(method, inputs, as_of, cutoff, "SHORT_ASSET_HISTORY", bad)
            frame = panels[5]
            qqq, daily, groups = None, None, None
            if method in {"RB", "RH", "RR", "RE"}:
                if inputs.qqq_receipt is None or inputs.qqq_observations is None:
                    raise ValueError("INDEPENDENT_QQQ_SOURCE_REQUIRED_NO_CROSSSECTION_FALLBACK")
                inputs.qqq_receipt.validate(cutoff, role="benchmark", primary=inputs.source_receipt)
                qp = _panel(inputs.qqq_observations, ("QQQ",), {"QQQ": "QQQ"},
                            inputs.qqq_receipt.identity_epoch, inputs.qqq_receipt, sessions, cutoff, 5)
                qqq = qp["QQQ"].reindex(common)
                if qqq.isna().any():
                    raise ValueError("QQQ_COMMON_SUPPORT_MISSING")
                qqq.attrs.update(source_id=inputs.qqq_receipt.source_identity,
                                 source_identity=inputs.qqq_receipt.source_identity,
                                 identity_epoch=inputs.qqq_receipt.identity_epoch,
                                 available_at=_time(inputs.qqq_receipt.available_at).isoformat(),
                                 source_version=inputs.qqq_receipt.source_version,
                                 source_sha256=inputs.qqq_receipt.source_sha256, cutoff=cutoff.isoformat(),
                                 return_coordinate=inputs.qqq_receipt.return_coordinate,
                                 source_execution_semantics=inputs.qqq_receipt.cache_identity(),
                                 observation_time_assumed=inputs.qqq_receipt.observation_time_assumed,
                                 strict_PIT_promotion_eligible=False)
                if method == "RR":
                    dp = _panel(inputs.qqq_observations, ("QQQ",), {"QQQ": "QQQ"},
                                inputs.qqq_receipt.identity_epoch, inputs.qqq_receipt, sessions, cutoff, 1)
                    daily = dp["QQQ"]
                    # Date 1D returns by declared availability/assumed observation, never origin.
                    qmeta = inputs.qqq_observations
                    legal_daily = qmeta.loc[qmeta.horizon.eq(1), list(META)].copy()
                    for c in ("origin_at", "entry_at", "endpoint_at", "matured_at", "available_at"):
                        legal_daily = legal_daily[legal_daily[c].map(_time).lt(cutoff)]
                    clock = legal_daily.set_index("origin_at").available_at.map(_time)
                    daily.index = pd.DatetimeIndex(clock.reindex(daily.index))
                    if daily.index.has_duplicates or not daily.index.is_monotonic_increasing:
                        raise ValueError("QQQ_DAILY_AVAILABILITY_CLOCK_INVALID")
                    daily.attrs.update(qqq.attrs)
            if method == "RH":
                groups = _industries(inputs, inputs.assets, cutoff)
            state = {}
            def learn(kind, name, values, compute, parameters=None):
                kind = {"covariance_state": "covariance", "horizon_state": "horizon"}.get(kind, kind)
                return cache.learn(kind, name, values, compute, parameters=parameters)
            if method in {"R0", "RD"}:
                bundle = self._primitive(cache, "LW" if method == "R0" else "EWMA", frame)
                covariance = bundle.covariance
                state["shrinkage_intensity"] = bundle.fitted_state.get("shrinkage")
            elif method == "RM":
                parts = {}
                for h in horizons:
                    hc = cache.bind(horizon=h)
                    parts[h] = self._primitive(hc, "LW", panels[h]).covariance
                covariance = learn("deterministic_transform", "RM:C5_PROXY", tuple(parts.values()),
                                   lambda: sum((5/h)*parts[h] for h in horizons)/4,
                                   parameters={"horizons": horizons, "scales": [5/h for h in horizons]})
                state["horizon_state"] = dict(horizons=horizons, common_support=len(common),
                                             origins=tuple(t.isoformat() for t in common),
                                             scaling="mean_h((5/h)*C_h); risk time-scale approximation only")
            elif method in {"RB", "RH", "RT", "RR"}:
                from .shared_risk_extensions_r2 import compute_extension
                state = compute_extension(method, frame, qqq_returns=qqq, qqq_daily=daily,
                                          industry_groups=groups, cutoff=cutoff, learn=learn)
                if state.get("blocked_assets") or tuple(state.get("estimated_assets", inputs.assets)) != tuple(inputs.assets):
                    return self._blocked(method, inputs, as_of, cutoff, "EXTENSION_ASSET_BLOCKED",
                                         state.get("blocked_assets"), used_keys=cache.usage_log[usage_start:])
                covariance = state["covariance"]
            elif method == "RU":
                base = self._primitive(cache, "LW", frame).covariance
                samples = []
                for block, removed in enumerate(np.array_split(np.arange(len(frame)), 4)):
                    subset = frame.iloc[np.setdiff1d(np.arange(len(frame)), removed)]
                    cov = self._primitive(cache, "LW", subset, kind="jackknife_subfit",
                                          suffix=":DELETE_BLOCK_" + str(block)).covariance
                    samples.append(np.sqrt(np.maximum(np.diag(cov), 0)))
                sj = np.asarray(samples)
                replica_spread = sj.std(axis=0, ddof=0)
                uncertainty = np.sqrt(3/4 * ((sj-sj.mean(axis=0))**2).sum(axis=0))
                penalty = np.diag(uncertainty**2)
                covariance = learn("deterministic_transform", "RU:UNCERTAINTY_PENALTY", (base, sj),
                                   lambda: base+penalty)
                state["estimation_uncertainty"] = dict(sigma_jackknife=sj,
                                                      marginal_sigma_uncertainty=uncertainty,
                                                      replica_spread=replica_spread,
                                                      standard_error_formula="sqrt(3/4*sum((sigma_j-mean_sigma)^2))",
                                                      uncertainty_diagonal_penalty=penalty,
                                                      jackknife_physical_subfits=4)
            else:
                from .shared_risk_extensions_r2 import compute_extension
                members = {m: self._primitive(cache, m, frame).covariance for m in ("LW", "OAS", "PCA")}
                rb = compute_extension("RB", frame, qqq_returns=qqq, cutoff=cutoff, learn=learn)
                if rb.get("blocked_assets"):
                    raise ValueError("RE_REQUIRED_RB_MEMBER_BLOCKED")
                members["RB"] = rb["covariance"]
                if set(members) != {"LW", "OAS", "PCA", "RB"}:
                    raise ValueError("RE_REQUIRED_MEMBER_MISSING")
                sigmas = np.asarray([np.sqrt(np.maximum(np.diag(c), 0)) for c in members.values()])
                disagreement = np.diag(sigmas.var(axis=0, ddof=0))
                covariance = learn("deterministic_transform", "RE:EQUAL_COVARIANCE",
                                   tuple(members.values()), lambda: sum(members.values())/4)
                state["model_disagreement"] = dict(members=("LW", "OAS", "PCA5", "RB"),
                                                   marginal_sigmas=sigmas,
                                                   disagreement_diagonal=disagreement,
                                                   equal_weights=(.25,)*4)
                state["qqq_relative_state"] = rb.get("qqq_relative_state")
            covariance, numeric = validate_covariance(covariance, regularize=False)
            condition = float(np.linalg.cond(covariance))
            if not np.isfinite(condition) or condition > 1e12:
                raise ValueError("ILL_CONDITIONED_RISK_STATE")
            covariance = np.array(covariance, copy=True)
            covariance.flags.writeable = False
            sigma = np.sqrt(np.diag(covariance))
            sigma.flags.writeable = False
            counts = frame.count().to_dict()
            coverage = {a: dict(observed=int(counts[a]), origin_sessions=252,
                               uid=inputs.asset_uids[a], identity_epoch=inputs.identity_epoch,
                               source_qualified=True, missing_cells=int(frame[a].isna().sum()))
                        for a in inputs.assets}
            receipt = asdict(inputs.source_receipt)
            receipt.update(cutoff=cutoff, horizon_sessions=5)
            notes = dict(schedule=SCHEDULE[method], seed=20260928, numeric=numeric,
                         h_overlapping_returns=True, approximate_effective_independent_sample=True,
                         no_unknown_asset_fallback=True,
                         imputation="Existing primitive observed means / missing centered cells=0; not price fill",
                         real_fit=int(inputs.source_receipt.mechanism),
                         real_fit_counter_scope="Execution mode flag; physical states counted by lifecycle reservations",
                         mechanism_fit=int(inputs.source_receipt.mechanism),
                         synthetic_fit=int(inputs.source_receipt.synthetic),
                         strict_PIT_promotion_eligible=False,
                         historical_authority_status=inputs.source_receipt.historical_authority_status,
                         observation_time_assumed=inputs.source_receipt.observation_time_assumed,
                         benchmark_clock="next-session Open to h-session endpoint Open; never Close substituted",
                         estimation_notes=state.get("estimation_notes", []),
                         dependent_source_receipts={
                             "stock": asdict(inputs.source_receipt),
                             "QQQ": asdict(inputs.qqq_receipt) if method in {"RB", "RH", "RR", "RE"} else None,
                             "FF48": asdict(inputs.industry_receipt) if method == "RH" else None})
            if "horizon_state" in state:
                notes["horizon_state"] = state["horizon_state"]
            dependencies = self._dependency_closure(cache.usage_log[usage_start:])
            identity = content_hash(dict(method=method, source=receipt, cutoff=cutoff,
                                         assets=inputs.assets, epoch=inputs.identity_epoch,
                                         covariance=covariance, parameters=notes,
                                         all_state_fields=state, fit_dependency_ids=dependencies))
            effective = {a: min(int(counts[a]), len(common)//max(horizons)) for a in inputs.assets}
            if method == "RD":
                weights = .94**np.arange(len(common))
                ess = float(weights.sum()**2/(weights@weights))
                effective = {a: min(effective[a], ess) for a in inputs.assets}
            return RiskState(identity, as_of, cutoff, tuple(inputs.assets),
                             inputs.source_receipt.source_identity, COORDINATE, 5, covariance, sigma,
                             coverage, effective,
                             inputs.identity_epoch, condition, state.get("shrinkage_intensity"),
                             state.get("estimation_uncertainty"), state.get("model_disagreement"),
                             state.get("regime_state"), state.get("downside_state"),
                             state.get("qqq_relative_state"), (), receipt,
                             "PASS_SYNTHETIC" if inputs.source_receipt.synthetic else "PASS_FROZEN_HISTORY_MECHANISM", method,
                             dependencies, notes)
        except (ValueError, TypeError, KeyError, np.linalg.LinAlgError, StateBudgetError) as error:
            return self._blocked(method, inputs, as_of, cutoff, str(error),
                                 used_keys=cache.usage_log[usage_start:] if cache is not None else ())


__all__ = ["SourceReceipt", "EndpointPair", "RiskInput", "RiskState", "SharedRiskEngine",
           "observations_from_endpoints", "risk_state_contract", "COORDINATE", "BENCHMARK_PROXY_COORDINATE", "METHODS"]
