"""Explicit, symmetric round-trip costs for research-only ETF execution."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoundTripCost:
    round_trip_bps: int

    @property
    def total_cost(self) -> float:
        return self.round_trip_bps / 10_000.0

    @property
    def entry_cost(self) -> float:
        return self.total_cost / 2.0

    @property
    def exit_cost(self) -> float:
        return self.total_cost / 2.0

    def net_return(self, gross_return: float) -> float:
        return gross_return - self.total_cost
