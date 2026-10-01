"""Fixed, non-learned distribution readout for the q10/q50/q90 models.

The inverse CDF is constant in [0,.1] and [.9,1], linear between the
three predicted knots. This makes the tail assumption explicit: each tail
has a 10% point mass at the corresponding endpoint. It is a conditional
distribution approximation, not a conditional-mean estimator.
"""
from __future__ import annotations

import numpy as np


PROBABILITIES = np.array([0.1, 0.5, 0.9], dtype=float)


def monotone_knots(raw_q10_q50_q90: np.ndarray) -> np.ndarray:
    raw = np.asarray(raw_q10_q50_q90, dtype=float)
    if raw.ndim != 2 or raw.shape[1] != 3 or not np.isfinite(raw).all():
        raise ValueError("Expected finite N x 3 quantile predictions")
    return np.sort(raw, axis=1)


def inverse_cdf(knots: np.ndarray, probabilities: np.ndarray) -> np.ndarray:
    """Return rowwise Q(p), including declared constant tails."""
    q = monotone_knots(knots)
    p = np.asarray(probabilities, dtype=float)
    if p.ndim == 0:
        p = np.full(len(q), float(p))
    if p.shape != (len(q),) or not ((p >= 0) & (p <= 1)).all():
        raise ValueError("One probability in [0,1] per row required")
    return np.where(p <= .1, q[:, 0],
                    np.where(p < .5, q[:, 0] + (p - .1) / .4 * (q[:, 1] - q[:, 0]),
                             np.where(p < .9, q[:, 1] + (p - .5) / .4 * (q[:, 2] - q[:, 1]), q[:, 2])))


def cdf(knots: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Return rowwise F(x) for the fixed piecewise-quantile distribution."""
    q = monotone_knots(knots)
    x = np.asarray(values, dtype=float)
    if x.ndim == 0:
        x = np.full(len(q), float(x))
    if x.shape != (len(q),) or not np.isfinite(x).all():
        raise ValueError("One finite value per row required")
    lo, mid, hi = q.T
    first = np.where(mid > lo, .1 + .4 * (x - lo) / np.maximum(mid - lo, np.finfo(float).tiny), .5)
    second = np.where(hi > mid, .5 + .4 * (x - mid) / np.maximum(hi - mid, np.finfo(float).tiny), .9)
    return np.where(x < lo, 0., np.where(x < mid, first,
                    np.where(x < hi, second, 1.)))
