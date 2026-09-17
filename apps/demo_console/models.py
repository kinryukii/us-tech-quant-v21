"""Immutable display contracts. No scoring, allocation or execution behavior."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class HoldingRow:
    rank: int | None
    ticker: str
    score: float | None = None
    rank_change: int | None = None
    held_before: bool | None = None
    raw_action: str | None = None
    rx_action: str | None = None
    final_action: str | None = None
    weight: float | None = None


@dataclass(frozen=True)
class PipelineStage:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class Provenance:
    decision_date: str | None = None
    information_as_of: str | None = None
    execution_date: str | None = None
    universe_identity: str | None = None
    strategy_identity: str | None = None
    artifact_sources: tuple[str, ...] = ()
    producer_identity: str | None = None
    replay_identity: str | None = None
    artifact_hashes: tuple[tuple[str, str], ...] = ()
    raw_status: str | None = None
    config_identity: str | None = None
    alpha_implementation: str | None = None


@dataclass(frozen=True)
class ModelVintage:
    year: int
    name: str
    train_max_date: str
    train_target_end_max: str
    prediction_min_date: str
    prediction_max_date: str
    training_row_count: int
    prediction_count: int
    fingerprint: str
    serialized_status: str


@dataclass(frozen=True)
class LearningProfile:
    """Compact metadata from the already verified freeze; never a fitted model."""
    feature_columns: tuple[str, ...] = ()
    parameters: tuple[tuple[str, str], ...] = ()
    target: str | None = None
    vintages: tuple[ModelVintage, ...] = ()
    source_fingerprint: str | None = None


@dataclass(frozen=True)
class DecisionOverview:
    decision_date: str | None = None
    available_dates: tuple[str, ...] = ()
    ranking: tuple[HoldingRow, ...] = ()
    holdings: tuple[HoldingRow, ...] = ()
    previous_holdings: tuple[str, ...] | None = None
    retained: tuple[str, ...] | None = None
    entered: tuple[str, ...] | None = None
    exited: tuple[str, ...] | None = None
    raw_proposed_changes: int | None = None
    rx_accepted_changes: int | None = None
    rx_prevented_changes: int | None = None
    turnover: float | None = None
    eligible_universe_count: int | None = None
    pipeline: tuple[PipelineStage, ...] = ()
    provenance: Provenance = field(default_factory=Provenance)
    limitations: tuple[str, ...] = ()
    error: str | None = None
    debug_error: str | None = None
    previous_decision_date: str | None = None
    learning: LearningProfile = field(default_factory=LearningProfile)


@dataclass(frozen=True)
class PerformancePoint:
    """Post-trade observations; cost, cash and value use initial-NAV units."""
    execution_date: str
    nav: float
    net_return: float
    gross_return: float
    transaction_cost: float
    turnover: float
    cash: float
    position_value: float
    holding_count: int
    stale_mark_count: int
    skipped_buy_count: int
    blocked_rebalance_count: int
    buy_cash_scale: float
    reference_nav: float | None = None
    reference_net_return: float | None = None
    reference_gross_return: float | None = None
    reference_transaction_cost: float | None = None


@dataclass(frozen=True)
class PerformanceHistory:
    """Cutoff-limited points plus the complete verified archive's execution calendar."""
    points: tuple[PerformancePoint, ...] = ()
    available_dates: tuple[str, ...] = ()
    archive_start: str | None = None
    archive_end: str | None = None
    requested_end_date: str | None = None
    effective_end_date: str | None = None
    initial_nav: float = 1.0
    model_identity: str = "A2_HGB"
    reference_identity: str | None = None
    reference_available: bool = False
    source_refs: tuple[tuple[str, str], ...] = ()
    reference_error: str | None = None
    reference_debug_error: str | None = None
    error: str | None = None
    debug_error: str | None = None
    limitations: tuple[str, ...] = ()
