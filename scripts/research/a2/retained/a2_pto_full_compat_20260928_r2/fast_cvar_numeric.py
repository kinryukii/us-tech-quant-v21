"""Allocation-only alternative to the frozen smooth CVaR calculation.

This module does not install a replacement.  It retains the original einsum,
elementwise operation order, row reductions, and fixed eta bisection budget.
Scratch arrays are local to a call, so separate accounts and threads cannot
share mutable numerical state.  Numeric equivalence must be proved before a
caller chooses to use ``smooth_cvar_buffered``.
"""
from __future__ import annotations

import numpy as np

from optimization import SPEC


def _sigmoid_into(value: np.ndarray, destination: np.ndarray) -> None:
    """Evaluate 1 / (1 + exp(-clip(value))) in the original operation order."""
    np.clip(value, -45.0, 45.0, out=destination)
    np.negative(destination, out=destination)
    np.exp(destination, out=destination)
    np.add(1.0, destination, out=destination)
    np.divide(1.0, destination, out=destination)


def smooth_cvar_buffered(weights, returns, reserved_joint_loss=None):
    """Same float64 objective as ``optimization._smooth_cvar``, local buffers.

    The initial loss and final gradient expressions deliberately use the exact
    original einsum calls and allocation behavior.  ``empty_like`` also retains
    the loss array's memory order for all row reductions and the final einsum.
    Only redundant allocation inside the fixed eta loop is removed.
    """
    epsilon, tail = SPEC["cvar_softplus_epsilon"], 1.0 - SPEC["cvar_alpha"]
    loss = -np.einsum("shn,sn->sh", returns, weights, optimize=True)
    if reserved_joint_loss is not None:
        loss = loss + reserved_joint_loss
    low = loss.min(axis=1) - 25.0 * epsilon
    high = loss.max(axis=1) + 25.0 * epsilon
    eta = np.empty_like(low)
    normalized_loss = np.empty_like(loss)
    probability = np.empty_like(loss)
    mass = np.empty_like(low)
    above_tail = np.empty(low.shape, dtype=bool)
    for _ in range(SPEC["eta_bisections"]):
        np.add(low, high, out=eta)
        np.multiply(eta, 0.5, out=eta)
        np.subtract(loss, eta[:, None], out=normalized_loss)
        np.divide(normalized_loss, epsilon, out=normalized_loss)
        _sigmoid_into(normalized_loss, probability)
        np.mean(probability, axis=1, out=mass)
        np.greater(mass, tail, out=above_tail)
        np.copyto(low, eta, where=above_tail)
        np.logical_not(above_tail, out=above_tail)
        np.copyto(high, eta, where=above_tail)
    np.add(low, high, out=eta)
    np.multiply(eta, 0.5, out=eta)
    np.subtract(loss, eta[:, None], out=normalized_loss)
    np.divide(normalized_loss, epsilon, out=normalized_loss)
    np.logaddexp(0.0, normalized_loss, out=probability)
    np.mean(probability, axis=1, out=mass)
    np.multiply(epsilon, mass, out=mass)
    np.divide(mass, tail, out=mass)
    cvar = eta + mass
    _sigmoid_into(normalized_loss, probability)
    gradient = -np.einsum("shn,sh->sn", returns, probability, optimize=True) / (returns.shape[1] * tail)
    return cvar, gradient, eta
