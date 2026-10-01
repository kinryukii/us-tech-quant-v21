"""Opt-in numerical work elimination; never installed by importing this file.

The capped-turnover proximal map is row independent. Rows whose direct prox
already respects their budget are returned unchanged by the reference map.
Only constrained rows need the same fixed 36 shifted bisection evaluations.
No tolerance, iteration, objective, step, seed, or model contract is changed.
"""
from __future__ import annotations

import numpy as np
from optimization import SPEC, _soft, _prox_budget as _reference_prox


def prox_budget_subset(y, center, threshold, budget, upper):
    """Reference turnover prox with bisection restricted to constrained rows."""
    # Fancy row indexing changes Fortran/strided arrays to C layout. NumPy
    # then chooses a different floating row-sum reduction path. Preserve those
    # inputs with the original calculation instead of accepting roundoff.
    cap = np.asarray(upper)
    if (not y.flags.c_contiguous or not center.flags.c_contiguous or
            (cap.ndim == 2 and not cap.flags.c_contiguous)):
        return _reference_prox(y, center, threshold, budget, upper)
    zero = np.zeros(len(y))
    direct = np.clip(center + _soft(y - center - zero[:, None], threshold[:, None]),
                     0.0, upper)
    need = direct.sum(axis=1) > budget
    if not need.any():
        return direct
    sub_y, sub_center = y[need], center[need]
    sub_threshold, sub_budget = threshold[need], budget[need]
    sub_upper = np.broadcast_to(upper, y.shape)[need]
    low = np.zeros(len(sub_y))
    high = np.maximum((sub_y - sub_center).max(axis=1) + sub_center.max(axis=1)
                      + sub_threshold, 0.0)
    def shifted(lam):
        return np.clip(sub_center + _soft(sub_y - sub_center - lam[:, None],
                                         sub_threshold[:, None]), 0.0, sub_upper)
    for _ in range(SPEC["projection_bisections"]):
        mid = (low + high) * 0.5
        too_much = shifted(mid).sum(axis=1) > sub_budget
        low = np.where(too_much, mid, low)
        high = np.where(~too_much, mid, high)
    direct[need] = shifted(high)
    return direct
