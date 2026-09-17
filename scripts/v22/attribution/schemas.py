"""Typed schemas and explicit field roles for realized attribution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


COMPONENT_TYPES = {"SECURITY", "CASH", "COST", "OTHER_EXPLICIT_RESIDUAL"}
FIELD_ROLES = {
    "REQUIRED": (
        "strategy_id", "date", "security_id", "component_type", "model_id",
        "universe_id", "vintage_id",
    ),
    "CONDITIONAL_ECONOMIC_REQUIRED": (
        "net_contribution or portfolio_contribution; otherwise explicit derived-contribution authorization",
    ),
    "OPTIONAL": (
        "ticker", "sector", "industry", "rank", "portfolio_weight", "previous_weight",
        "security_return", "portfolio_contribution", "transaction_cost", "turnover_contribution",
        "gross_contribution", "net_contribution", "cost_contribution", "nav_before", "nav_after",
        "fold", "regime", "contribution_source",
    ),
    "DERIVED": (
        "year", "quarter", "month", "rank_bucket", "winner_loser_class",
        "identity_error", "incremental_contribution", "difference_taxonomy",
    ),
}


@dataclass(frozen=True)
class AttributionRow:
    strategy_id: str
    date: str
    security_id: str
    component_type: str
    model_id: str
    universe_id: str
    vintage_id: str
    ticker: str | None = None
    sector: str | None = None
    industry: str | None = None
    rank: float | None = None
    portfolio_weight: float | None = None
    previous_weight: float | None = None
    security_return: float | None = None
    portfolio_contribution: float | None = None
    transaction_cost: float | None = None
    turnover_contribution: float | None = None
    gross_contribution: float | None = None
    net_contribution: float | None = None
    cost_contribution: float | None = None
    nav_before: float | None = None
    nav_after: float | None = None
    fold: str | None = None
    regime: str | None = None
    contribution_source: str | None = None


@dataclass(frozen=True)
class AttributionConfig:
    identity_tolerance: float = 1e-12
    incremental_weight_tolerance: float = 1e-12
    allow_weight_return_derived_contribution: bool = False
    transaction_cost_is_positive_charge: bool = True
    winner_loser_threshold: float = 0.0
    concentration_status: str = "INFORMATIONAL_ONLY"
    require_same_incremental_dates: bool = True
    require_same_incremental_universe: bool = True
    rank_buckets: tuple[tuple[str, int, int], ...] = (
        ("RANK_1_5", 1, 5),
        ("RANK_6_10", 6, 10),
        ("RANK_11_20", 11, 20),
    )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AttributionConfig":
        known = set(cls.__dataclass_fields__)
        unknown = set(payload) - known
        if unknown:
            raise ValueError(f"unknown attribution config fields: {sorted(unknown)}")
        values = dict(payload)
        if "rank_buckets" in values:
            values["rank_buckets"] = tuple(
                (str(item["label"]), int(item["min_rank"]), int(item["max_rank"]))
                for item in values["rank_buckets"]
            )
        result = cls(**values)
        result.validate()
        return result

    def validate(self) -> None:
        if self.identity_tolerance < 0 or self.incremental_weight_tolerance < 0:
            raise ValueError("identity and weight tolerances must be nonnegative")
        if self.winner_loser_threshold < 0:
            raise ValueError("winner_loser_threshold must be nonnegative")
        occupied: set[int] = set()
        for label, minimum, maximum in self.rank_buckets:
            if not label or minimum < 1 or maximum < minimum:
                raise ValueError(f"invalid rank bucket: {(label, minimum, maximum)}")
            ranks = set(range(minimum, maximum + 1))
            if occupied & ranks:
                raise ValueError("rank buckets overlap")
            occupied |= ranks

    def rank_bucket(self, rank: float | None, component_type: str = "SECURITY") -> str:
        if component_type != "SECURITY":
            return f"{component_type}_COMPONENT"
        if rank is None:
            return "UNRANKED"
        integer = int(rank)
        if float(integer) != float(rank):
            return "UNRANKED"
        for label, minimum, maximum in self.rank_buckets:
            if minimum <= integer <= maximum:
                return label
        return "OUTSIDE_CONFIGURED_RANKS"


def schema_contract() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "schema": "AttributionRow",
        "field_roles": FIELD_ROLES,
        "component_types": sorted(COMPONENT_TYPES),
        "unknown_metadata_policy": "PRESERVE_AS_UNKNOWN_NEVER_INFER",
        "economic_field_policy": "AUTHORITATIVE_REALIZED_CONTRIBUTION_FIRST",
    }
