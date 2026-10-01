"""Fixed target-only weights for the bounded Raw A2 sizing pilot."""
from __future__ import annotations

from math import isfinite
from typing import Mapping


def allocate(base: Mapping[str, float], amounts: Mapping[str, float | None]) -> tuple[dict[str, float], str]:
    """Normalize an admissible amount across exactly the frozen candidates.

    Missing keys mean complete-filing non-listing (observable zero); explicit
    None means UNKNOWN and triggers a whole-day fallback to the baseline.
    """
    names = tuple(base)
    if not names or any(not isfinite(x) or x < 0 for x in base.values()):
        raise ValueError("invalid baseline")
    gross = sum(base.values())
    if not isfinite(gross) or gross > 1 + 1e-10:
        raise ValueError("invalid gross exposure")
    if gross == 0:
        return {name: 0.0 for name in names}, "ZERO_EXPOSURE"
    if set(amounts) - set(names):
        raise ValueError("amount outside frozen candidates")
    if any(value is None for value in amounts.values()):
        return dict(base), "UNKNOWN_INPUT"
    observed = {name: float(amounts.get(name, 0.0)) for name in names}
    if any(not isfinite(value) or value < 0 for value in observed.values()):
        return dict(base), "UNKNOWN_OR_INVALID_AMOUNT"
    total = sum(observed.values())
    if total <= 0:
        return dict(base), "ZERO_OBSERVED_AMOUNT"
    return {name: gross * observed[name] / total for name in names}, "WEIGHTED"


def portfolio_share(
    base: Mapping[str, float],
    managers: tuple[str, ...],
    values: Mapping[tuple[str, str], float | None],
    full_equity_totals: Mapping[str, float | None],
) -> tuple[dict[str, float], str]:
    """Use one fixed institution set and full eligible-equity denominators."""
    if len(set(managers)) != len(managers) or not managers:
        raise ValueError("invalid manager set")
    if any(manager not in full_equity_totals or full_equity_totals[manager] is None
           or not isfinite(float(full_equity_totals[manager]))
           or float(full_equity_totals[manager]) <= 0 for manager in managers):
        return dict(base), "UNKNOWN_FULL_DENOMINATOR"
    scores: dict[str, float | None] = {}
    for name in base:
        if any(values.get((manager, name), 0.0) is None for manager in managers):
            scores[name] = None
        else:
            scores[name] = sum(float(values.get((manager, name), 0.0)) /
                               float(full_equity_totals[manager]) for manager in managers) / len(managers)
    return allocate(base, scores)
