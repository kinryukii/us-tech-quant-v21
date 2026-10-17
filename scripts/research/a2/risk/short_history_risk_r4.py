"""Pure R4 short-history estimators; no readers, persistence or account authority.

Original R3 min30 remains unchanged. Caller metadata fixes support before numeric
access. Generalized-Bayes likelihood discounts overlapping H5 by 1/5; this is
not an empirical independent effective sample size or calibrated PIT posterior.
"""
from __future__ import annotations

from dataclasses import asdict
import copy
import numpy as np
import pandas as pd

from .joint_risk_estimators import validate_covariance, _estimate, specs
from .shared_risk_budget_r2 import StateBudget, StateCache, content_hash
from .shared_risk_engine_r2 import (
    META, CUTOFF, RiskState, _calendar, _panel, _time,
)

METHODS = ("SHR_HP", "SHR_EB", "SHR_CC", "SHR_FACTOR", "SHR_DYNAMIC", "SHR_ROBUST")
RECIPE = dict(
    schema="B_R4_SHORT_HISTORY_RECIPE_V1", methods=list(METHODS), horizon=5,
    cadence="quarterly", parent_origin_sessions=252, minimum_nominal_n=10,
    minimum_structural_n=2, likelihood_weight=.2, donor_minimum_nominal_n=60,
    minimum_donors=5, minimum_group_donors_every_origin=5,
    beta_prior_market=1., beta_prior_industry=0., beta_prior_intercept=0.,
    hp_prior_strength=8., hp_ig_shape=3., eb_prior_strength=8.,
    factor_ridge_strength=1., variance_floor=1e-12, cc_identity_shrinkage=.5,
    cc_rho_bounds=[0., .95], cc_minimum_pair_nominal_n=30,
    psd_policy="existing declared roundoff-only validate_covariance ridge",
    covariance_condition_limit=1e12, scientific_retry=0,
    missing_industry="market-only; metadata decides; no future backfill",
    missing_returns="preserved NaN outside qualified support; required nonfinite blocks whole node",
    factor_policy="existing QQQ H5 proxy + qualified-donor FF48 mean (stock minus QQQ)",
    uncertainty="conditional independent asset NIG; beta/intercept and sigma posterior uncertainty",
    posterior_limitations="discounted generalized Bayes; donor hyperpriors and factor covariance plug-in; serial dependence beyond overlap uncalibrated",
    structural_n="floor(nominal N/5), overlap-limited proxy/upper bound; not independent ESS",
    dynamic_status="BLOCKED_DEPENDENCY:NO_EXISTING_KALMAN_DEPENDENCY_OR_PRODUCER",
    robust_status="BLOCKED_INPUT:EXISTING_MINCOVDET_MIN30_AND_ROWS_GREATER_THAN_ASSETS_INCOMPATIBLE_WITH_SHORT_FULLPOOL",
    maximum_learned_states_per_refresh=13,
    donor_specific_variance="observed donor residual SSE/N; no iid unbiasedness claim",
    formulae=dict(
        hp_precision="Lambda_n=diag(8,8*diag(Fcov_subset))+.2*Z.T@Z",
        hp_mean="b_n=inv(Lambda_n)@(Lambda_0@[0,1,0]+.2*Z.T@y)",
        hp_shape="a_n=3+.1*N",
        hp_scale="d_n=2*s_prior^2+.5*(.2*SSE+(b_n-b0).T@Lambda0@(b_n-b0))",
        hp_covariance="B@Fcov@B.T+diag(E[sigma2]*(1+V00+trace(Fcov_subset@Vslopes)))",
        eb="eta=(N/5)/(N/5+8); beta=eta*OLS+(1-eta)*b0; variance=eta*SSE/N+(1-eta)*prior",
        factor="zero-mean ridge precision diag(1,diag(Fcov_subset)); specific=max(SSE/N,1e-12)",
        cc="HP marginal sigmas; rho=clip(equal mean metadata qualified donor pair correlations,0,.95); C=diag(sigmas)@[(1-.5rho)I+.5rho11.T]@diag(sigmas)",
    ),
)


def specification():
    return copy.deepcopy(RECIPE)


def _unknown(value):
    return (not isinstance(value, str) or not value.strip()
            or value.strip().upper() in {"UNKNOWN", "UNBOUND", "NONE", "NULL", "?"})


def _metadata(inputs, cutoff, sessions):
    if (not inputs.assets or len(set(inputs.assets)) != len(inputs.assets)
            or set(inputs.asset_uids) != set(inputs.assets)
            or any(_unknown(v) for v in inputs.asset_uids.values())
            or len(set(inputs.asset_uids.values())) != len(inputs.assets)
            or _unknown(inputs.identity_epoch)):
        raise ValueError("EXACT_CURRENT_UID_EPOCH_REQUIRED")
    if inputs.source_receipt.identity_epoch != inputs.identity_epoch:
        raise ValueError("SOURCE_IDENTITY_EPOCH_MISMATCH")
    frame = inputs.observations.loc[:, list(META)].copy()
    for field in ("origin_at", "entry_at", "endpoint_at", "matured_at", "available_at"):
        frame[field] = frame[field].map(_time)
    mask = frame.asset.isin(inputs.assets) & frame.horizon.eq(5)
    for field in ("origin_at", "entry_at", "endpoint_at", "matured_at", "available_at"):
        mask &= frame[field].lt(cutoff) & frame[field].lt(CUTOFF)
    legal = frame.loc[mask]
    if legal.duplicated(["asset", "origin_at"]).any():
        raise ValueError("DUPLICATE_ORIGIN_ASSET")
    positions = {v.normalize(): i for i, v in enumerate(sessions)}
    for row in legal.itertuples():
        oi, ei, xi = (positions.get(t.normalize(), -1)
                      for t in (row.origin_at, row.entry_at, row.endpoint_at))
        if (row.uid != inputs.asset_uids[row.asset]
                or row.identity_epoch != inputs.identity_epoch
                or row.source_identity != inputs.source_receipt.source_identity):
            raise ValueError("SECURITY_UID_EPOCH_OR_SOURCE_SWAP")
        if (oi < 0 or ei != oi + 1 or xi != ei + 5
                or not row.origin_at < row.entry_at < row.endpoint_at <= row.matured_at <= row.available_at):
            raise ValueError("H5_ENDPOINT_MATURITY_MISMATCH")
    return legal


def _groups(inputs, cutoff):
    result = {a: None for a in inputs.assets}
    if inputs.industry_mapping is None or inputs.industry_receipt is None:
        return result
    inputs.industry_receipt.validate(cutoff, role="industry", primary=inputs.source_receipt)
    frame = inputs.industry_mapping
    fields = ("asset", "group", "available_at", "effective_at", "identity_epoch", "source_identity")
    if not set(fields).issubset(frame):
        raise ValueError("INDUSTRY_METADATA_SCHEMA")
    legal = frame.loc[:, list(fields)].copy()
    for field in ("available_at", "effective_at"):
        legal[field] = legal[field].map(_time)
    legal = legal.loc[legal.asset.isin(inputs.assets) & legal.available_at.le(cutoff) & legal.effective_at.le(cutoff)]
    if legal.duplicated("asset").any():
        raise ValueError("AMBIGUOUS_ASOF_INDUSTRY")
    for row in legal.itertuples():
        if (row.identity_epoch != inputs.identity_epoch
                or row.source_identity != inputs.industry_receipt.source_identity):
            raise ValueError("INDUSTRY_SOURCE_EPOCH_SWAP")
        if pd.notna(row.group) and float(row.group).is_integer() and 1 <= float(row.group) <= 48:
            result[row.asset] = int(row.group)
    return result


def qualify_metadata(inputs, *, as_of, support_metadata):
    """Zero-value support check. qualified keys must come from source flags/UID.

    support_metadata: exact asset/origin_at/qualified(bool) source-key projection,
    including false unsupported slots. No return_value is read by this function.
    """
    as_of, cutoff, sessions = _calendar(inputs, as_of, "RH")
    inputs.source_receipt.validate(cutoff)
    legal = _metadata(inputs, cutoff, sessions)
    origins = pd.DatetimeIndex(legal.origin_at.unique()).sort_values()[-252:]
    if len(origins) != 252:
        raise ValueError("INSUFFICIENT_252_METADATA_ORIGINS")
    if not isinstance(support_metadata, pd.DataFrame) or not {"asset", "origin_at", "qualified"}.issubset(support_metadata):
        raise ValueError("SOURCE_QUALIFIED_KEY_PROJECTION_REQUIRED")
    support = support_metadata.loc[:, ["asset", "origin_at", "qualified"]].copy()
    support["origin_at"] = support.origin_at.map(_time)
    support = support.loc[support.origin_at.isin(origins)]
    if not support.asset.isin(inputs.assets).all():
        raise ValueError("SOURCE_SUPPORT_KEY_OUTSIDE_REQUESTED_ASSETS")
    if support.duplicated(["asset", "origin_at"]).any():
        raise ValueError("DUPLICATE_SOURCE_SUPPORT_KEY")
    if not support.qualified.map(lambda v: isinstance(v, (bool, np.bool_))).all():
        raise ValueError("EXPLICIT_BOOLEAN_SOURCE_SUPPORT_REQUIRED")
    available_keys = set(zip(legal.asset, legal.origin_at))
    true_keys = set(zip(support.loc[support.qualified].asset, support.loc[support.qualified].origin_at))
    if not set(zip(support.asset, support.origin_at)).issubset(available_keys):
        raise ValueError("QUALIFIED_KEY_WITHOUT_LEGAL_UID_MATURITY_METADATA")
    matrix = (support.pivot(index="origin_at", columns="asset", values="qualified")
              .reindex(index=origins, columns=inputs.assets).fillna(False).astype(bool))
    counts = matrix.sum().astype(int)
    short = {a: int(n) for a, n in counts.items() if n < 10 or n // 5 < 2}
    if short:
        raise ValueError("SHORT_HISTORY_BELOW_FIXED_MINIMUM:" + str(short))
    donors = tuple(a for a in inputs.assets if counts[a] >= 60)
    if len(donors) < 5:
        raise ValueError("FEWER_THAN_5_METADATA_DONORS")
    groups = _groups(inputs, cutoff)
    active = []
    for group in sorted({g for g in groups.values() if g is not None}):
        members = [a for a in donors if groups[a] == group]
        if len(members) >= 5 and matrix.loc[:, members].sum(axis=1).ge(5).all():
            active.append(group)
    # Market source and exact endpoint slots are metadata requirements too.
    if inputs.qqq_receipt is None or inputs.qqq_observations is None:
        raise ValueError("QQQ_H5_PROXY_SOURCE_REQUIRED")
    inputs.qqq_receipt.validate(cutoff, role="benchmark", primary=inputs.source_receipt)
    q = inputs.qqq_observations.loc[:, list(META)].copy()
    for field in ("origin_at", "entry_at", "endpoint_at", "matured_at", "available_at"):
        q[field] = q[field].map(_time)
    mask = q.asset.eq("QQQ") & q.horizon.eq(5) & q.origin_at.isin(origins)
    for field in ("origin_at", "entry_at", "endpoint_at", "matured_at", "available_at"):
        mask &= q[field].lt(cutoff)
    q = q.loc[mask]
    positions = {v.normalize(): i for i, v in enumerate(sessions)}
    for row in q.itertuples():
        oi, ei, xi = (positions.get(t.normalize(), -1)
                      for t in (row.origin_at, row.entry_at, row.endpoint_at))
        if (oi < 0 or ei != oi + 1 or xi != ei + 5
                or not row.origin_at < row.entry_at < row.endpoint_at <= row.matured_at <= row.available_at):
            raise ValueError("QQQ_H5_ENDPOINT_MATURITY_MISMATCH")
    cc_pairs = [[a, b] for i, a in enumerate(donors) for b in donors[i+1:]
                if int((matrix[a] & matrix[b]).sum()) >= 30]
    if (q.duplicated("origin_at").any() or set(q.origin_at) != set(origins)
            or not q.uid.eq("QQQ").all()
            or not q.identity_epoch.eq(inputs.qqq_receipt.identity_epoch).all()
            or not q.source_identity.eq(inputs.qqq_receipt.source_identity).all()):
        raise ValueError("QQQ_H5_METADATA_SUPPORT_INCOMPLETE")
    proof = dict(schema="B_R4_SHORT_HISTORY_METADATA_SUPPORT_V1", as_of=as_of.isoformat(),
                 cutoff=cutoff.isoformat(), assets=list(inputs.assets), uids=dict(inputs.asset_uids),
                 identity_epoch=inputs.identity_epoch, source=inputs.source_receipt.cache_identity(),
                 market_source=inputs.qqq_receipt.cache_identity(), origins=[v.isoformat() for v in origins],
                 nominal_n=counts.to_dict(), structural_n={a: int(counts[a] // 5) for a in inputs.assets},
                 donors=list(donors), industry_groups=groups, active_groups=active, cc_pairs=cc_pairs,
                 method_block_reasons={m: ([] if m != "SHR_CC" or cc_pairs else ["CC_NO_METADATA_QUALIFIED_DONOR_PAIRS"])
                                       for m in METHODS[:4]},
                 industry_source=None if not active else inputs.industry_receipt.cache_identity(),
                 qualified_keys=[[a, v.isoformat()] for v in origins for a in inputs.assets if matrix.loc[v, a]],
                 source_support_sha256=content_hash(matrix), recipe_sha256=content_hash(RECIPE),
                 strict_PIT_promotion_eligible=False, quote_qualified=False, certified_nav_qualified=False)
    proof["metadata_proof_sha256"] = content_hash(proof)
    return proof


def _context(inputs, cutoff):
    return dict(source_identity=inputs.source_receipt.cache_identity(), cutoff=cutoff.isoformat(),
                assets=inputs.assets, return_coordinate=inputs.source_receipt.return_coordinate,
                horizon=5, identity_epoch=dict(epoch=inputs.identity_epoch, uids=dict(inputs.asset_uids)),
                synthetic=inputs.source_receipt.synthetic, mechanism=inputs.source_receipt.mechanism)


def make_cache(inputs, *, as_of, budget=None):
    _, cutoff, _ = _calendar(inputs, as_of, "RH")
    return StateCache(budget if budget is not None else StateBudget(limit=650), **_context(inputs, cutoff))


def _closure(cache, keys):
    by_key = {v["key"]: v for v in cache.budget.events}
    used, pending = set(keys), list(keys)
    while pending:
        for child in by_key.get(pending.pop(), {}).get("dependencies", ()):
            if child not in used:
                used.add(child)
                pending.append(child)
    return tuple(sorted(used))


def _state(method, inputs, as_of, cutoff, *, status, notes, covariance=None, coverage=None,
           uncertainty=None, dependency_ids=()):
    binding = dict(method=method, as_of=str(as_of), cutoff=str(cutoff), assets=inputs.assets,
                   uids=dict(inputs.asset_uids), epoch=inputs.identity_epoch,
                   source=inputs.source_receipt.cache_identity(), recipe=RECIPE,
                   covariance_sha256=None if covariance is None else content_hash(covariance), notes=notes)
    if covariance is not None:
        covariance = np.array(covariance, copy=True)
        covariance.flags.writeable = False
        sigma = np.sqrt(np.diag(covariance))
        sigma.flags.writeable = False
    else:
        sigma = None
    return RiskState(content_hash(binding), as_of, cutoff, tuple(inputs.assets),
                     inputs.source_receipt.source_identity, inputs.source_receipt.return_coordinate,
                     5, covariance, sigma, coverage or {},
                     {a: v["structural_effective_n_proxy"] for a, v in (coverage or {}).items()},
                     inputs.identity_epoch, None if covariance is None else float(np.linalg.cond(covariance)),
                     None, uncertainty, None, None, None, None,
                     () if covariance is not None else tuple(inputs.assets), asdict(inputs.source_receipt),
                     status, method, dependency_ids, notes)


def fit_risk(method, inputs, *, as_of, support_metadata, cache=None, expected_qualification=None):
    """Pure analytic risk fit; durable StateCache reservation required for mechanism.

    Share one cache over all methods in a refresh. No reader/authority is created;
    recipe and qualification must be frozen by the outer run before real use.
    """
    if method not in METHODS:
        raise ValueError("UNKNOWN_SHORT_HISTORY_METHOD")
    cutoff, usage = None, 0
    try:
        as_of, cutoff, sessions = _calendar(inputs, as_of, "RH")
        if method in {"SHR_DYNAMIC", "SHR_ROBUST"}:
            return _state(method, inputs, as_of, cutoff, status="BLOCKED", notes={
                "block_reason": RECIPE["dynamic_status" if method == "SHR_DYNAMIC" else "robust_status"]})
        proof = qualify_metadata(inputs, as_of=as_of, support_metadata=support_metadata)
        if proof["method_block_reasons"][method]:
            raise ValueError(proof["method_block_reasons"][method][0])
        if expected_qualification is not None and proof != expected_qualification:
            raise ValueError("FROZEN_METADATA_QUALIFICATION_CHANGED")
        if cache is None:
            cache = make_cache(inputs, as_of=as_of)
        cache = cache.bind(**_context(inputs, cutoff))
        usage = len(cache.usage_log)
        origins = pd.DatetimeIndex(proof["origins"])
        selected = inputs.observations.loc[inputs.observations.origin_at.map(_time).isin(origins)]
        frame = _panel(selected, inputs.assets, inputs.asset_uids, inputs.identity_epoch,
                       inputs.source_receipt, sessions, cutoff, 5).reindex(index=origins, columns=inputs.assets)
        keys = {(a, pd.Timestamp(o)) for a, o in proof["qualified_keys"]}
        support = pd.DataFrame([[ (a, o) in keys for a in inputs.assets] for o in origins],
                               index=origins, columns=inputs.assets)
        raw = frame.to_numpy(float)
        if not np.isfinite(raw[support.to_numpy()]).all():
            raise ValueError("NONFINITE_REQUIRED_SOURCE_SUPPORT_NO_ASSET_REMOVAL")
        # Unsupported source cells remain absent. No return or price fill.
        frame = frame.where(support)
        q_selected = inputs.qqq_observations.loc[inputs.qqq_observations.origin_at.map(_time).isin(origins)]
        q = _panel(q_selected, ("QQQ",), {"QQQ": "QQQ"}, inputs.qqq_receipt.identity_epoch,
                   inputs.qqq_receipt, sessions, cutoff, 5).reindex(origins)["QQQ"]
        if not np.isfinite(q.to_numpy(float)).all():
            raise ValueError("NONFINITE_REQUIRED_QQQ_FACTOR")
        groups, donors = proof["industry_groups"], tuple(proof["donors"])
        parameters = dict(recipe_sha256=content_hash(RECIPE), proof_sha256=proof["metadata_proof_sha256"])
        def learn(kind, name, values, compute):
            return cache.learn(kind, "SHR_R4:" + name, values, compute, parameters=parameters)
        factors = pd.DataFrame({"QQQ": q}, index=origins)
        if proof["active_groups"]:
            def group_returns():
                return pd.DataFrame({"FF48_" + str(g): frame.loc[:, [a for a in donors if groups[a] == g]]
                                     .subtract(q, axis=0).mean(axis=1) for g in proof["active_groups"]}, index=origins)
            factors = pd.concat([factors, learn("scaler", "qualified_ff48_group_returns", (frame, q, proof), group_returns)], axis=1)
        factor_mean = learn("scaler", "factor_mean", (factors,), lambda: factors.mean())
        f = learn("deterministic_transform", "factor_center", (factors, factor_mean), lambda: factors - factor_mean)
        def factor_covariance():
            values = f.to_numpy(float)
            if not np.isfinite(values).all() or np.any(np.var(values, axis=0, ddof=1) <= 1e-12):
                raise ValueError("FACTOR_VARIANCE_NOT_IDENTIFIABLE")
            matrix, _, count = _estimate("LW", {"centered": values, "marginal_variance": np.ones(values.shape[1])},
                                        f.index, tuple(f.columns), None, None, specs("LW"))
            if count != 1:
                raise ValueError("UNACCOUNTED_FACTOR_COVARIANCE_SUBFIT")
            return matrix
        fcov = learn("covariance", "factor_lw_covariance", (f,), factor_covariance)
        def design(asset):
            positions = [0]
            if groups[asset] in proof["active_groups"]:
                positions.append(1 + proof["active_groups"].index(groups[asset]))
            mask = support[asset].to_numpy(bool)
            z = np.column_stack([np.ones(mask.sum()), f.to_numpy(float)[mask][:, positions]])
            return z, frame[asset].to_numpy(float)[mask], positions
        def regress(names, *, ridge=0., prior=False):
            result = {}
            for asset in names:
                z, y, positions = design(asset)
                diagonal = np.r_[1., np.diag(fcov)[positions]]
                penalty = np.diag(ridge * diagonal)
                beta0 = np.r_[0., 1., np.zeros(len(positions)-1)] if prior else np.zeros(z.shape[1])
                inverse = np.linalg.inv(.2*z.T@z + penalty)
                beta = inverse @ (.2*z.T@y + penalty@beta0)
                result[asset] = dict(beta=beta, inverse=inverse, positions=positions, nominal_n=len(y))
            return result
        donor_beta = learn("covariance", "donor_ols_coefficients", (frame, f, proof), lambda: regress(donors))
        def specific(names, beta):
            return {a: max(float(np.mean((design(a)[1] - design(a)[0]@beta[a]["beta"])**2)), 1e-12) for a in names}
        donor_variance = learn("covariance", "donor_specific_variance", (frame, f, donor_beta), lambda: specific(donors, donor_beta))
        def prior_variances():
            global_prior = float(np.median(list(donor_variance.values())))
            return {a: float(np.median([donor_variance[d] for d in donors if groups[d] == groups[a]]))
                    if groups[a] in proof["active_groups"] else global_prior for a in inputs.assets}
        priors = learn("covariance", "group_global_variance_prior", (donor_variance, proof), prior_variances)
        uncertainty = None
        if method in {"SHR_HP", "SHR_CC"}:
            coefficients = learn("covariance", "hp_nig_coefficients", (frame, f, fcov, proof),
                                 lambda: regress(inputs.assets, ridge=8., prior=True))
            def inverse_gamma():
                result = {}
                for asset in inputs.assets:
                    z, y, positions = design(asset)
                    beta = coefficients[asset]["beta"]
                    beta0 = np.r_[0., 1., np.zeros(len(positions)-1)]
                    precision = np.diag(8.*np.r_[1., np.diag(fcov)[positions]])
                    an = 3. + .1*len(y)
                    dn = 2.*priors[asset] + .5*(.2*np.sum((y-z@beta)**2) + (beta-beta0)@precision@(beta-beta0))
                    if not np.isfinite(dn) or dn <= 0:
                        raise ValueError("NIG_SCALE_NONFINITE_OR_NONPOSITIVE")
                    expected, varvar = dn/(an-1), dn*dn/((an-1)**2*(an-2))
                    if not np.isfinite([expected, varvar]).all():
                        raise ValueError("NIG_POSTERIOR_UNCERTAINTY_NONFINITE")
                    result[asset] = dict(shape=an, scale=dn, expected_variance=expected,
                                         variance_of_variance=varvar)
                return result
            variance = learn("covariance", "hp_nig_specific_posterior", (frame, f, coefficients, priors), inverse_gamma)
            def hp_covariance():
                b = np.zeros((len(inputs.assets), len(f.columns)))
                residual, detail = [], {}
                for i, asset in enumerate(inputs.assets):
                    item, var = coefficients[asset], variance[asset]
                    positions = item["positions"]
                    b[i, positions] = item["beta"][1:]
                    posterior = item["inverse"]
                    uncertainty_term = posterior[0, 0] + np.trace(fcov[np.ix_(positions, positions)] @ posterior[1:, 1:])
                    residual.append(var["expected_variance"]*(1.+uncertainty_term))
                    detail[asset] = dict(beta_covariance=var["expected_variance"]*posterior,
                                         predictive_parameter_variance=var["expected_variance"]*uncertainty_term,
                                         sigma2_posterior=var)
                return dict(covariance=b@fcov@b.T+np.diag(residual), detail=detail)
            hp = learn("deterministic_transform", "hp_posterior_predictive_covariance", (coefficients, variance, fcov), hp_covariance)
            covariance, uncertainty = hp["covariance"], hp["detail"]
            if method == "SHR_CC":
                pairs = proof["cc_pairs"]
                if not pairs:
                    raise ValueError("CC_NO_METADATA_QUALIFIED_DONOR_PAIRS")
                def correlation():
                    values = []
                    for a, b in pairs:
                        mask = (support[a] & support[b]).to_numpy(bool)
                        value = float(np.corrcoef(frame[a].to_numpy()[mask], frame[b].to_numpy()[mask])[0, 1])
                        if not np.isfinite(value):
                            raise ValueError("CC_DONOR_CORRELATION_NONFINITE")
                        values.append(value)
                    return float(np.clip(np.mean(values), 0., .95))
                rho = learn("covariance", "cc_donor_constant_correlation", (frame, pairs), correlation)
                def cc_covariance():
                    sigma = np.sqrt(np.diag(covariance))
                    correlation = np.full(covariance.shape, .5*rho)
                    np.fill_diagonal(correlation, 1.)
                    return correlation*np.outer(sigma, sigma)
                covariance = learn("deterministic_transform", "cc_hp_marginal_covariance", (covariance, rho), cc_covariance)
        else:
            if method == "SHR_EB":
                ols = learn("covariance", "eb_ols_coefficients", (frame, f, proof), lambda: regress(inputs.assets))
                def shrink_beta():
                    result = copy.deepcopy(ols)
                    for asset, item in result.items():
                        eta = (item["nominal_n"]/5.)/(item["nominal_n"]/5.+8.)
                        beta0 = np.r_[0., 1., np.zeros(len(item["positions"])-1)]
                        item["beta"] = eta*item["beta"]+(1.-eta)*beta0
                    return result
                coefficients = learn("deterministic_transform", "eb_scalar_beta_pool", (ols,), shrink_beta)
            else:
                coefficients = learn("covariance", "factor_zero_prior_ridge_coefficients", (frame, f, fcov, proof),
                                     lambda: regress(inputs.assets, ridge=1.))
            variance = learn("covariance", method.lower()+"_specific_variance", (frame, f, coefficients),
                             lambda: specific(inputs.assets, coefficients))
            def plug_in():
                b = np.zeros((len(inputs.assets), len(f.columns)))
                v = []
                for i, asset in enumerate(inputs.assets):
                    item = coefficients[asset]
                    b[i, item["positions"]] = item["beta"][1:]
                    specific_variance = variance[asset]
                    if method == "SHR_EB":
                        eta = (item["nominal_n"]/5.)/(item["nominal_n"]/5.+8.)
                        specific_variance = eta*specific_variance+(1.-eta)*priors[asset]
                    v.append(specific_variance)
                return b@fcov@b.T+np.diag(v)
            covariance = learn("deterministic_transform", method.lower()+"_plug_in_covariance", (coefficients, variance, priors, fcov), plug_in)
        covariance, psd = learn("deterministic_transform", method.lower()+"_psd", (covariance,), lambda: validate_covariance(covariance))
        condition = float(np.linalg.cond(covariance))
        if not np.isfinite(condition) or condition > 1e12:
            raise ValueError("ILL_CONDITIONED_SHORT_HISTORY_COVARIANCE")
        coverage = {a: dict(nominal_n=proof["nominal_n"][a], structural_effective_n_proxy=proof["structural_n"][a],
                           power_likelihood_n=proof["nominal_n"][a]/5., uid=inputs.asset_uids[a],
                           identity_epoch=inputs.identity_epoch, source_qualified=True,
                           industry_mode="FF48" if groups[a] in proof["active_groups"] else "MARKET_ONLY",
                           original_r3_min30_qualified=proof["nominal_n"][a]>=30) for a in inputs.assets}
        notes = dict(metadata_proof=proof, recipe=specification(), numeric_check=psd,
                     covariance_sha256=content_hash(covariance), posterior_limitations=RECIPE["posterior_limitations"],
                     coefficient_systems_in_method=len(inputs.assets), donor_coefficient_systems=len(donors),
                     vector_learned_states_are_not_independent_asset_models=True,
                     strict_PIT_promotion_eligible=False, quote_qualified=False, certified_nav_qualified=False)
        status = "PASS_SYNTHETIC" if inputs.source_receipt.synthetic else "CONDITIONAL_FROZEN_HISTORY_MECHANISM"
        return _state(method, inputs, as_of, cutoff, status=status, notes=notes, covariance=covariance,
                      coverage=coverage, uncertainty=uncertainty, dependency_ids=_closure(cache, cache.usage_log[usage:]))
    except (ValueError, TypeError, KeyError, np.linalg.LinAlgError) as error:
        return _state(method, inputs, as_of, cutoff, status="BLOCKED", notes={"block_reason":str(error)},
                      dependency_ids=() if cache is None else _closure(cache, cache.usage_log[usage:]))
