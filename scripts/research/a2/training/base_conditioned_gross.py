"""Conditional gross on a base policy's unnormalised tradable target.

Pure array adapter: no source reading, account engine or fitting on import.
The caller owns OOF/PIT qualification and authority. Original R7 remains frozen;
its RAW20-only recipe cannot represent these weighted, cash-containing sleeves.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.research.a2.training import stateful_decision as owner
from scripts.research.a2.training import stateful_decision_models as models
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision

GRID = owner.G
FRICTION = owner.S
FEATURES = tuple("mean_" + c for c in owner.inputs.FEATURES) + (
    "raw_score_mean", "raw_score_std", "raw_score_width", "diagonal_vol_proxy",
    "base_tradable_gross", "gross_previous_proxy", "friction")
TRAINING_CUTOFF = pd.Timestamp("2024-10-07")


def _weights(weights):
    w = np.asarray(weights, float)
    if w.ndim != 1 or not np.isfinite(w).all() or (w < 0).any() or w.sum() > 1 + 1e-10:
        raise ValueError("FINITE_LONG_ONLY_BASE_WEIGHTS_REQUIRED")
    return w


def aggregate_reference(weights, feature_matrix, raw_scores):
    """Weighted feature means describe stock mix; mass/vol retain original weights.

    A missing contributing feature stays missing, rather than renormalising over
    observed names. The frozen owner adds explicit missing flags at model input.
    None denotes a genuinely empty stock sleeve, which has no training label.
    """
    w = _weights(weights)
    a = float(w.sum())
    if a == 0:
        return None
    x, score = np.asarray(feature_matrix, float), np.asarray(raw_scores, float)
    if x.shape != (len(w), len(owner.inputs.FEATURES)) or score.shape != w.shape:
        raise ValueError("BASE_REFERENCE_FEATURE_SHAPE")
    selected = w > 0
    x, score, q = x[selected], score[selected], w[selected]
    if np.isinf(x).any() or np.isinf(score).any():
        raise ValueError("INFINITE_BASE_FEATURE")
    relative = q / a
    mean = relative @ x
    score_mean = float(relative @ score)
    vol = x[:, owner.inputs.FEATURES.index("realized_vol_20d")]
    if (vol[np.isfinite(vol)] < 0).any():
        raise ValueError("NEGATIVE_BASE_VOLATILITY")
    result = dict(zip(("mean_" + c for c in owner.inputs.FEATURES), mean))
    result.update(raw_score_mean=score_mean,
                  raw_score_std=float(np.sqrt(relative @ ((score - score_mean) ** 2))),
                  raw_score_width=float(np.max(score) - np.min(score)),
                  diagonal_vol_proxy=float(np.sqrt(np.sum((q * vol) ** 2))),
                  base_tradable_gross=a, friction=FRICTION)
    return result


def gross_utilities(base_return, base_gross, previous):
    """Local five-day sleeve proxy; excludes turnover and account cash constraints."""
    r, a, p = np.broadcast_arrays(np.asarray(base_return, float),
                                  np.asarray(base_gross, float), np.asarray(previous, float))
    if (not np.isfinite(r).all() or not np.isfinite(a).all()
            or (a <= 0).any() or (a > 1 + 1e-10).any()
            or (r < -a).any() or not np.isin(p, GRID).all()):
        raise ValueError("QUALIFIED_NONEMPTY_BASE_GROSS_COORDINATE_REQUIRED")
    return (r[..., None] * GRID - FRICTION * a[..., None] * np.abs(GRID - p[..., None])
            - FRICTION * GRID * (a + r)[..., None] - 5 * (GRID * r[..., None]) ** 2)


def gross_targets(base_return, base_gross, previous):
    utility = gross_utilities(base_return, base_gross, previous)
    p = np.broadcast_arrays(np.asarray(base_return), np.asarray(base_gross),
                            np.asarray(previous))[2]
    result = []
    for row, prior in zip(utility.reshape(-1, len(GRID)), p.reshape(-1)):
        choices = np.flatnonzero(row == row.max())
        result.append(min(choices, key=lambda j: (abs(GRID[j] - prior), GRID[j])))
    return np.asarray(result, int).reshape(p.shape)


def training_rows(weights, feature_matrix, raw_scores, returns, *,
                  signal_date, label_mature_dates, cutoff):
    """Five exogenous previous requests from a caller-qualified causal base target.

    Base decisions/weights must already be chronological OOF. These checks do not
    certify that lineage. No outcome-dependent constituent removal is permitted.
    """
    day, cut = pd.Timestamp(signal_date), pd.Timestamp(cutoff)
    if pd.isna(day) or pd.isna(cut) or cut > TRAINING_CUTOFF or day >= cut:
        raise ValueError("PAST_BASE_SIGNAL_REQUIRED")
    w = _weights(weights)
    reference = aggregate_reference(w, feature_matrix, raw_scores)
    columns = ["signal_date", "label_mature_date", "basket_y", "target", *FEATURES]
    if reference is None:
        return pd.DataFrame(columns=columns)
    y = np.asarray(returns, float)
    mature = pd.DatetimeIndex(label_mature_dates)
    if y.shape != w.shape or len(mature) != len(w):
        raise ValueError("BASE_LABEL_SHAPE")
    selected = w > 0
    y, mature = y[selected], mature[selected]
    if (not np.isfinite(y).all() or (y < -1).any() or mature.hasnans
            or not (mature > day).all() or not (mature < cut).all()):
        raise ValueError("ALL_BASE_LABELS_MATURE_BEFORE_CUTOFF_REQUIRED")
    r = float(w[selected] @ y)
    target = gross_targets(r, reference["base_tradable_gross"], GRID)
    return pd.DataFrame([dict(reference, signal_date=day, label_mature_date=mature.max(),
                              basket_y=r, gross_previous_proxy=float(p), target=int(t))
                         for p, t in zip(GRID, target)], columns=columns)


def fit_model(learner, frame, *, cutoff, dependencies=(), on_fit_started=None):
    """Reuse original estimators; caller must admit this distinct research tuple."""
    cut = pd.Timestamp(cutoff)
    dates, mature = pd.DatetimeIndex(frame.signal_date), pd.DatetimeIndex(frame.label_mature_date)
    if (pd.isna(cut) or cut > TRAINING_CUTOFF or frame.empty or dates.hasnans or mature.hasnans
            or not (dates < cut).all() or not (mature < cut).all()
            or not (mature > dates).all()
            or not frame.base_tradable_gross.gt(0).all()
            or not frame.base_tradable_gross.le(1 + 1e-10).all()
            or not frame.gross_previous_proxy.isin(GRID).all()
            or not frame.friction.eq(FRICTION).all()):
        raise ValueError("QUALIFIED_PAST_GROSS_TRAINING_REQUIRED")
    x, names = owner.encode_features(frame, FEATURES)
    weights = owner.date_weights(frame.signal_date)
    return models.fit("gross", learner, x, frame.target.to_numpy(float), weights,
                      features=names, dependencies=dependencies, on_fit_started=on_fit_started)


def predict_gross(model, reference, previous):
    if previous not in GRID:
        raise ValueError("PREVIOUS_REQUESTED_GRID_REQUIRED")
    frame = pd.DataFrame([dict(reference, gross_previous_proxy=float(previous))])
    x, names = owner.encode_features(frame, FEATURES)
    if tuple(model.features) != names:
        raise ValueError("CONDITIONAL_GROSS_MODEL_FEATURE_SCHEMA")
    result = models.predict(model, x)
    gross = np.asarray(result["gross"], float)
    if gross.shape != (1,) or not np.isin(gross, GRID).all():
        raise ValueError("NATIVE_GROSS_GRID_OUTPUT_REQUIRED")
    return float(gross[0])


class BaseConditionedGrossOverlay:
    """Scale live base targets with independent previous-request state per path.

    input_provider(di, context, row) returns (canonical32, raw_scores), or None
    when the complete signal input is unavailable. It must not read future data.
    The caller owns base policy state and any test-inference authorization.
    """
    def __init__(self, path_ids, base_policy, models_by_path, input_provider):
        self.path_ids = tuple(path_ids)
        if not self.path_ids or len(set(self.path_ids)) != len(self.path_ids) or set(models_by_path) != set(self.path_ids):
            raise ValueError("EXACT_UNIQUE_GROSS_PATHS_REQUIRED")
        self.base_policy, self.models, self.input_provider = base_policy, dict(models_by_path), input_provider
        self.previous = dict.fromkeys(self.path_ids, 1.)
        self.last_date = None
        self.audit = []

    def __call__(self, di, context):
        date = pd.Timestamp(context.signal_date)
        if (pd.isna(date) or tuple(context.path_ids) != self.path_ids
                or (self.last_date is not None and date <= self.last_date)):
            raise ValueError("CAUSAL_ACCOUNT_PATH_ORDER_REQUIRED")
        original = self.base_policy(di, context)
        weights = np.asarray(original.weights, float).copy()
        mask = (np.asarray(context.decision_mask, bool).copy() if original.explicit_mask is None
                else np.asarray(original.explicit_mask, bool).copy())
        if weights.shape != np.asarray(context.current_units).shape or mask.shape != weights.shape:
            raise ValueError("BASE_TARGET_SHAPE")
        next_previous, audit = self.previous.copy(), []
        for row, path in enumerate(self.path_ids):
            _weights(weights[row])
            frozen = (np.asarray(context.reserved_mask[row], bool)
                      | ~np.asarray(context.decision_mask[row], bool)
                      | (np.asarray(context.sell_restricted[row], bool)
                         & (np.asarray(context.current_units[row]) > 1e-10)))
            mask[row] &= ~frozen
            weights[row, ~mask[row]] = 0.
            a = float(weights[row].sum())
            prior = self.previous[path]
            if a == 0:
                status = "BASE_CASH_TARGET_NO_GROSS_LABEL_OR_REQUEST_UPDATE"
            else:
                inputs = self.input_provider(di, context, row)
                if inputs is None:
                    weights[row] = 0.
                    mask[row] = False
                    status = "MISSING_INPUT_PRESERVE_UNITS_AND_PREVIOUS_REQUEST"
                else:
                    reference = aggregate_reference(weights[row], *inputs)
                    requested = predict_gross(self.models[path], reference, prior)
                    weights[row] *= requested
                    next_previous[path] = requested
                    status = "SCALE_BASE_TRADABLE_TARGET"
            audit.append(dict(path_id=path, signal_date=date, base_tradable_gross=a,
                              previous_requested_gross=prior,
                              requested_gross=next_previous[path], status=status))
        self.previous, self.last_date = next_previous, date
        self.audit.extend(audit)
        return TargetDecision(weights, explicit_mask=mask,
                              raw_evidence_id="BASE_CONDITIONED_GROSS_LOCAL_H5")
