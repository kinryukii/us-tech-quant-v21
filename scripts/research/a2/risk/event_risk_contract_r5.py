"""R5 event identity and explicit PSD prior completion; no readers or fitters.

These contracts are new scientific descendants. Native R3/R4 clocks, minimum
history rules, estimator code and frozen state identities remain untouched.
"""
from __future__ import annotations
from dataclasses import dataclass
from types import FunctionType
from pathlib import Path
import hashlib
import numpy as np
import pandas as pd
from .shared_risk_budget_r2 import content_hash
from .shared_risk_engine_r2 import _time, CUTOFF
from .joint_risk_estimators import validate_covariance

FAMILIES = ("LW", "OAS", "EWMA", "CONSTANT_CORRELATION", "PCA_FACTOR",
            "QQQ_RESIDUAL", "FF48_HIERARCHICAL", "DOWNSIDE_SEMIVARIANCE",
            "TAIL_CVAR", "REGIME_COVARIANCE", "UNCERTAINTY_JACKKNIFE",
            "DISAGREEMENT_ENSEMBLE", "SHR_HP", "SHR_EB", "SHR_CC", "SHR_FACTOR")


def structural_identity(*, assets, uids, epochs, security_coordinate,
                        source_support_identity):
    """Only prespecified structural metadata is accepted; no outcome input."""
    assets = tuple(assets)
    if not assets or assets != tuple(sorted(set(assets))):
        raise ValueError("EXACT_ORDERED_FULL_POOL_REQUIRED")
    if set(uids) != set(assets) or set(epochs) != set(assets):
        raise ValueError("COMPLETE_CURRENT_UID_EPOCH_REQUIRED")
    for mapping in (uids, epochs):
        if any(not isinstance(v, str) or not v.strip() or v.strip().upper() in
               {"UNKNOWN", "NONE", "NULL", "UNBOUND", "?"} for v in mapping.values()):
            raise ValueError("UNKNOWN_UID_EPOCH_FORBIDDEN")
    if len(set(uids.values())) != len(assets):
        raise ValueError("NONUNIQUE_CURRENT_UID")
    if not isinstance(security_coordinate, str) or not security_coordinate:
        raise ValueError("SECURITY_COORDINATE_REQUIRED")
    if not isinstance(source_support_identity, dict) or not source_support_identity:
        raise ValueError("FROZEN_SOURCE_SUPPORT_IDENTITY_REQUIRED")
    forbidden = {"nav", "returns", "sharpe", "performance", "winner", "risk_values"}
    def check(value):
        if isinstance(value, dict):
            if any(str(k).lower() in forbidden for k in value):
                raise ValueError("OUTCOME_TRIGGER_FORBIDDEN")
            for item in value.values(): check(item)
        elif isinstance(value, (tuple, list)):
            for item in value: check(item)
    check(source_support_identity)
    return content_hash(dict(assets=assets, uids=dict(uids), epochs=dict(epochs),
                             security_coordinate=security_coordinate,
                             source_support_identity=source_support_identity))


@dataclass(frozen=True)
class EventWitness:
    decision_asof: str
    current_structural_identity: str
    state_structural_identity: str
    source_still_valid: bool
    maturity_still_valid: bool

    def validate(self, fit_asof):
        decision, fit = _time(self.decision_asof), _time(fit_asof)
        if not fit <= decision < CUTOFF:
            raise ValueError("PRE2026_NONFUTURE_EVENT_USE_REQUIRED")
        if (len(self.current_structural_identity) != 64 or
                self.current_structural_identity != self.state_structural_identity):
            raise ValueError("STRUCTURAL_CHANGE_REQUIRES_NEW_STATE")
        if self.source_still_valid is not True or self.maturity_still_valid is not True:
            raise ValueError("SOURCE_OR_MATURITY_SUPPORT_INVALID")
        return "EXACT_EVENT_STATE_REUSE"


def event_calendar(inputs, as_of, method=None):
    """New R5 clock: decision Close and previous legal Close fit cutoff."""
    asof = _time(as_of)
    sessions = pd.DatetimeIndex([_time(v) for v in inputs.sessions])
    if (sessions.empty or sessions.has_duplicates or not sessions.is_monotonic_increasing
            or sessions.normalize().has_duplicates or asof >= CUTOFF):
        raise ValueError("LEGAL_PRE2026_EVENT_CALENDAR_REQUIRED")
    index = sessions.get_indexer([asof])[0]
    if index <= 0:
        raise ValueError("EXACT_CURRENT_CLOSE_AND_PRIOR_SESSION_REQUIRED")
    return asof, sessions[index-1], sessions


def bind_pinned_kernel(function, *, physical_path, expected_sha256, dependencies):
    """Isolated dependency injection over byte-identical existing kernel code.

    No mutation of original module globals and no source/body copying. Changed
    clock/qualification dependencies must be declared by the R5 freeze.
    """
    path = Path(physical_path)
    if Path(function.__code__.co_filename).resolve() != path.resolve():
        raise ValueError("KERNEL_FUNCTION_SOURCE_PATH_MISMATCH")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("PINNED_PARENT_KERNEL_CHANGED")
    if not isinstance(dependencies, dict) or not dependencies:
        raise ValueError("EXPLICIT_R5_KERNEL_DEPENDENCIES_REQUIRED")
    unknown = set(dependencies).difference(function.__globals__)
    if unknown:
        raise ValueError("UNKNOWN_PARENT_DEPENDENCY:" + repr(sorted(unknown)))
    namespace = dict(function.__globals__)
    namespace.update(dependencies)
    clone = FunctionType(function.__code__, namespace, function.__name__,
                         function.__defaults__, function.__closure__)
    clone.__kwdefaults__ = function.__kwdefaults__
    return clone


def conditional_prior_completion(prior_covariance, estimated_covariance,
                                 estimated_positions):
    """Explicit R5 hybrid: preserve the estimated block and prior conditional law.

    With prior H, fitted C and long block L, cross = sqrt(C) invsqrt(H_LL) H_LS.
    The short marginal remains H_SS. The Schur complement remains the original
    prior conditional covariance. This is model-based risk, never filled prices
    or fabricated observations. It is NOT the original classical estimator.
    """
    h = np.asarray(prior_covariance, float)
    c = np.asarray(estimated_covariance, float)
    pos = tuple(estimated_positions)
    if (h.ndim != 2 or h.shape[0] != h.shape[1] or not pos
            or len(set(pos)) != len(pos) or any(type(i) is not int or i < 0 or i >= len(h) for i in pos)
            or c.shape != (len(pos), len(pos))):
        raise ValueError("EXACT_PRIOR_AND_ESTIMATED_BLOCK_REQUIRED")
    for value in (h, c):
        if (not np.isfinite(value).all() or not np.allclose(value, value.T, atol=1e-12, rtol=0)
                or np.linalg.eigvalsh(value).min() <= 0):
            raise ValueError("FINITE_POSITIVE_DEFINITE_INPUT_REQUIRED")
    short = [i for i in range(len(h)) if i not in pos]
    result = h.copy()
    result[np.ix_(pos, pos)] = c
    if short:
        def root(matrix, inverse=False):
            vals, vecs = np.linalg.eigh(matrix)
            return (vecs * (1/np.sqrt(vals) if inverse else np.sqrt(vals))) @ vecs.T
        cross = root(c) @ root(h[np.ix_(pos, pos)], True) @ h[np.ix_(pos, short)]
        result[np.ix_(pos, short)] = cross
        result[np.ix_(short, pos)] = cross.T
    np.linalg.cholesky(result)  # Do not change either declared principal block.
    result, proof = validate_covariance(result, regularize=False)
    if not np.allclose(result[np.ix_(pos,pos)], c, atol=1e-12, rtol=1e-10):
        raise ValueError("PRIOR_COMPLETION_CHANGED_FITTED_BLOCK")
    return result, {**proof, "scientific_method": "R5_CLASSICAL_PLUS_HP_CONDITIONAL_COMPLETION",
                    "estimated_positions": list(pos), "prior_only_positions": short,
                    "observations_fabricated": False, "price_filling": False}
