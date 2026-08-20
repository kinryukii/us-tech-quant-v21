"""Minimal source-backed corporate-action position transition adapter."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable

import pandas as pd


SUPPORTED_ACTION_FAMILIES = (
    "FORWARD_SPLIT", "REVERSE_SPLIT", "SECURITY_REORGANIZATION_SHARE_CONVERSION",
    "TICKER_CHANGE_NO_ECONOMIC_CHANGE", "SECURITY_ID_CHANGE_NO_ECONOMIC_CHANGE",
    "MERGER_STOCK_CONVERSION", "MERGER_CASH_CONVERSION", "MERGER_MIXED_CONVERSION",
    "ADR_RATIO_CHANGE", "SPINOFF", "OTHER_SHARE_COUNT_TRANSFORM",
)
AUTHORIZED_SOURCE_TYPES = ("TIER1_ISSUER_REGULATOR_EXCHANGE", "TIER2_LOCAL_CANONICAL", "TIER3_VENDOR_METADATA")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode()


@dataclass(frozen=True)
class CorporateActionTransition:
    effective_date: str
    action_type: str
    old_security_id: str
    new_security_id: str
    old_ticker: str
    new_ticker: str
    quantity_multiplier: float
    cash_component_per_old_share: float
    source_type: str
    source_reference: str
    source_fingerprint: str
    ratio_orientation: str = "NEW_QUANTITY_PER_OLD_QUANTITY"
    repair_authorized: bool = True

    def __post_init__(self) -> None:
        if self.action_type not in SUPPORTED_ACTION_FAMILIES:
            raise ValueError(f"UNSUPPORTED_ACTION_FAMILY:{self.action_type}")
        if self.ratio_orientation != "NEW_QUANTITY_PER_OLD_QUANTITY":
            raise ValueError("WRONG_RATIO_ORIENTATION")
        if not math.isfinite(self.quantity_multiplier) or self.quantity_multiplier < 0:
            raise ValueError("INVALID_QUANTITY_MULTIPLIER")
        if not math.isfinite(self.cash_component_per_old_share):
            raise ValueError("INVALID_CASH_COMPONENT")
        if self.repair_authorized and self.source_type not in AUTHORIZED_SOURCE_TYPES:
            raise ValueError("HEURISTIC_OR_UNKNOWN_SOURCE_CANNOT_AUTHORIZE_REPAIR")
        if not self.old_security_id or not self.new_security_id:
            raise ValueError("SECURITY_IDENTIFIERS_REQUIRED_FOR_APPLIED_TRANSITION")
        pd.Timestamp(self.effective_date)

    @property
    def event_fingerprint(self) -> str:
        return hashlib.sha256(canonical_bytes(asdict(self))).hexdigest()


def apply_transition_to_positions(
    transition: CorporateActionTransition, positions: dict[str, float], cash: float,
    execution_date: pd.Timestamp,
) -> tuple[dict[str, float], float, dict[str, Any] | None]:
    """Apply one transition before the effective session mark.

    The function is ticker-agnostic.  Security identity and source evidence are
    mandatory even when old/new tickers happen to be equal.
    """
    if pd.Timestamp(execution_date) != pd.Timestamp(transition.effective_date):
        return dict(positions), float(cash), None
    if not transition.repair_authorized:
        raise RuntimeError("UNAUTHORIZED_TRANSITION_APPLICATION")
    updated = dict(positions)
    old_quantity = float(updated.pop(transition.old_ticker, 0.0))
    if old_quantity <= 0:
        return updated, float(cash), None
    if transition.new_ticker in updated:
        raise RuntimeError("OLD_NEW_POSITION_DOUBLE_COUNT_RISK")
    new_quantity = old_quantity * transition.quantity_multiplier
    cash_delta = old_quantity * transition.cash_component_per_old_share
    if new_quantity > 0:
        updated[transition.new_ticker] = new_quantity
    new_cash = float(cash) + cash_delta
    record = {
        "effective_date": pd.Timestamp(transition.effective_date),
        "action_type": transition.action_type,
        "old_security_id": transition.old_security_id,
        "new_security_id": transition.new_security_id,
        "old_ticker": transition.old_ticker,
        "new_ticker": transition.new_ticker,
        "old_quantity": old_quantity,
        "quantity_multiplier": transition.quantity_multiplier,
        "new_quantity": new_quantity,
        "cash_component_per_old_share": transition.cash_component_per_old_share,
        "cash_delta": cash_delta,
        "source_type": transition.source_type,
        "source_reference": transition.source_reference,
        "source_fingerprint": transition.source_fingerprint,
        "event_fingerprint": transition.event_fingerprint,
        "timing_rule": "BEFORE_EFFECTIVE_SESSION_MARK_AND_BEFORE_TRADES",
    }
    return updated, new_cash, record


class CorporateActionTransitionAdapter:
    def __init__(self, transitions: Iterable[CorporateActionTransition]):
        ordered = sorted(transitions, key=lambda item: (item.effective_date, item.old_security_id, item.new_security_id))
        keys = [(item.effective_date, item.old_security_id) for item in ordered]
        if len(keys) != len(set(keys)):
            raise ValueError("DUPLICATE_EFFECTIVE_OLD_SECURITY_TRANSITION")
        self._by_date: dict[pd.Timestamp, list[CorporateActionTransition]] = {}
        for transition in ordered:
            self._by_date.setdefault(pd.Timestamp(transition.effective_date), []).append(transition)
        self.records: list[dict[str, Any]] = []

    def apply(
        self, *, execution_date: pd.Timestamp, shares: dict[str, float], cash: float,
        context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, float], float, list[dict[str, Any]]]:
        updated = dict(shares)
        updated_cash = float(cash)
        rows: list[dict[str, Any]] = []
        for transition in self._by_date.get(pd.Timestamp(execution_date), []):
            updated, updated_cash, row = apply_transition_to_positions(
                transition, updated, updated_cash, pd.Timestamp(execution_date)
            )
            if row is not None:
                row = {**(context or {}), **row}
                rows.append(row)
                self.records.append(row)
        return updated, updated_cash, rows
