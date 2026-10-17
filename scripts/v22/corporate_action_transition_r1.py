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


# Opt-in entitlement lifecycle. Existing transition APIs above remain unchanged.
# Source terms and a complete immutable event catalogue belong to the caller.
from dataclasses import InitVar
import re

RAW_OLD_SHARE_COORDINATE = "RAW_OLD_SECURITY_SHARES"
USD_PER_RAW_OLD_SHARE = "USD_PER_RAW_OLD_SHARE"
CASH_ENTITLEMENT_FAMILIES = ("CASH_DIVIDEND", "CASH_DISTRIBUTION")
BLOCKED_ENTITLEMENT_FAMILIES = ("SPINOFF", "MULTI_SECURITY_SPINOFF", "COMPLEX_CA")


def _entitlement_day(value: Any) -> pd.Timestamp:
    day = pd.Timestamp(value)
    if pd.isna(day) or day.tzinfo is not None or day != day.normalize():
        raise ValueError("ENTITLEMENT_REQUIRES_NAIVE_SESSION_DATE")
    return day


def _entitlement_available(value: Any) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError("ENTITLEMENT_REQUIRES_EXPLICIT_AVAILABLE_TIME")
    return stamp.tz_convert("UTC")


def _cash_source_identity(event) -> None:
    if any(not isinstance(v, str) or not v.strip() for v in (
        event.event_id, event.old_security_id, event.ticker, event.source_reference)):
        raise ValueError("ENTITLEMENT_EVENT_SECURITY_SOURCE_ID_REQUIRED")
    if (event.old_security_id.upper().startswith("FROZEN_VENDOR:") or
            any(token in event.old_security_id.upper() for token in
                ("UNKNOWN", "NOT_EXTRACTED", "NOT_REQUIRED", "UNCONFIRMED"))):
        raise ValueError("ENTITLEMENT_PLACEHOLDER_SECURITY_ID_FORBIDDEN")
    if event.source_type not in AUTHORIZED_SOURCE_TYPES:
        raise ValueError("ENTITLEMENT_SOURCE_NOT_AUTHORIZED")
    if not isinstance(event.source_fingerprint, str) or not re.fullmatch(
            r"[0-9a-fA-F]{64}", event.source_fingerprint):
        raise ValueError("ENTITLEMENT_SOURCE_SHA256_REQUIRED")
    if event.currency != "USD":
        raise ValueError("ENTITLEMENT_CURRENCY_NOT_USD")
    if event.amount_unit != USD_PER_RAW_OLD_SHARE:
        raise ValueError("ENTITLEMENT_CASH_UNIT_UNCONFIRMED")
    if event.quantity_coordinate != RAW_OLD_SHARE_COORDINATE:
        raise ValueError("ENTITLEMENT_QUANTITY_COORDINATE_UNCONFIRMED")


@dataclass(frozen=True)
class SourceBackedEntitlementEvent:
    """Explicit source terms; cash is per RAW old-security share, never factor_b.

    Standard ex-before-payment cash distributions are supported. Due-bill and
    multi-security distributions remain explicit blocked families. record_date
    records source identity; ownership is the snapshot before ex-session trades.
    """
    event_id: str
    action_type: str
    old_security_id: str
    ticker: str
    ex_date: str
    record_date: str
    pay_date: str
    available_at: str
    cash_per_old_share: float | None
    currency: str
    amount_unit: str
    quantity_coordinate: str
    source_type: str
    source_reference: str
    source_fingerprint: str

    def __post_init__(self) -> None:
        _validate_cash_entitlement_terms(self)

    @property
    def event_fingerprint(self) -> str:
        return hashlib.sha256(canonical_bytes(asdict(self))).hexdigest()


CAD_PER_RAW_OLD_SHARE = "CAD_PER_RAW_OLD_SHARE"
CAD_PER_USD = "CAD_PER_USD"


@dataclass(frozen=True)
class SourceBackedForeignCashEvent(SourceBackedEntitlementEvent):
    """Declared gross CAD common dividend; USD conversion is a frozen scenario."""
    def __post_init__(self):
        if (self.action_type != "CASH_DIVIDEND" or self.currency != "CAD"
                or self.amount_unit != CAD_PER_RAW_OLD_SHARE
                or self.quantity_coordinate != RAW_OLD_SHARE_COORDINATE
                or self.source_type not in AUTHORIZED_SOURCE_TYPES
                or not re.fullmatch(r"[0-9a-fA-F]{64}", str(self.source_fingerprint))
                or type(self.cash_per_old_share) not in (int, float)
                or not math.isfinite(self.cash_per_old_share) or self.cash_per_old_share < 0):
            raise ValueError("SOURCE_QUALIFIED_GROSS_CAD_COMMON_DIVIDEND_REQUIRED")
        if any(not isinstance(v, str) or not v.strip() for v in
               (self.event_id, self.old_security_id, self.ticker, self.source_reference)):
            raise ValueError("FOREIGN_CASH_SOURCE_AND_DATED_SECURITY_REQUIRED")
        if any(x in self.old_security_id.upper() for x in ("FROZEN_VENDOR:", "UNKNOWN", "PLACEHOLDER", "UNCONFIRMED")):
            raise ValueError("FOREIGN_CASH_PLACEHOLDER_SECURITY_FORBIDDEN")
        ex, record, pay = map(_entitlement_day, (self.ex_date, self.record_date, self.pay_date))
        available = _entitlement_available(self.available_at)
        if (not pd.Timestamp("2023-01-01") <= ex < pd.Timestamp("2026-01-01")
                or record < ex or pay < ex or available >= pd.Timestamp("2026-01-01", tz="UTC")):
            raise ValueError("FOREIGN_CASH_PRE2026_SOURCE_EX_AND_KNOWN_SCHEDULE_REQUIRED")


@dataclass(frozen=True)
class SourceBackedFXMark:
    currency: str
    rate_unit: str
    observation_date: str
    available_at: str
    currency_per_usd: float
    source_reference: str
    source_fingerprint: str

    def __post_init__(self):
        # Release date is sourced. End-of-day is a conservative availability
        # bound; neither the scheduled 16:15 nor actual intraday time is certified.
        observation = _entitlement_day(self.observation_date)
        available = _entitlement_available(self.available_at)
        local = available.tz_convert("America/New_York")
        if (self.currency != "CAD" or self.rate_unit != CAD_PER_USD
                or not pd.Timestamp("2023-01-01") <= observation < pd.Timestamp("2026-01-01")
                or available >= pd.Timestamp("2026-01-01", tz="UTC")
                or observation.date() > local.date()
                or (local.hour, local.minute, local.second, local.microsecond) != (23, 59, 59, 0)
                or type(self.currency_per_usd) not in (float, int)
                or not math.isfinite(self.currency_per_usd) or self.currency_per_usd <= 0
                or not isinstance(self.source_reference, str) or not self.source_reference.strip()
                or not re.fullmatch(r"[0-9a-fA-F]{64}", str(self.source_fingerprint))):
            raise ValueError("PRE2026_FED_H10_CAD_PER_USD_PUBLICATION_BOUND_MARK_REQUIRED")


def select_foreign_fx_mark(marks, *, as_of):
    """Select publication-first, then latest observation; no native backdating."""
    clock = _entitlement_available(as_of)
    if clock >= pd.Timestamp("2026-01-01", tz="UTC"):
        raise ValueError("FOREIGN_FX_MARK_PRE2026_ONLY")
    candidates = []
    source_versions = {}
    for mark in marks:
        if not isinstance(mark, SourceBackedFXMark):
            raise ValueError("SOURCE_BACKED_FX_MARK_TYPE_REQUIRED")
        if _entitlement_available(mark.available_at) <= clock:
            key = (_entitlement_available(mark.available_at), _entitlement_day(mark.observation_date))
            version = (mark.currency_per_usd, mark.source_reference, mark.source_fingerprint)
            if key in source_versions and source_versions[key] != version:
                raise ValueError("AMBIGUOUS_PUBLISHED_FX_OBSERVATION_OR_SOURCE_VERSION")
            source_versions[key] = version
            candidates.append(mark)
    return max(candidates, key=lambda m: (_entitlement_available(m.available_at),
        _entitlement_day(m.observation_date))) if candidates else None


def foreign_claim_value_usd(claims, mark, *, as_of):
    if not claims:
        return 0.
    if mark is None or select_foreign_fx_mark((mark,), as_of=as_of) is None:
        raise ValueError("FOREIGN_CLAIM_WITHOUT_PUBLISHED_LEGAL_FX_NAV_MARK")
    value = sum(claim.amount_foreign for claim in claims) / mark.currency_per_usd
    if not math.isfinite(value):
        raise ValueError("FOREIGN_CLAIM_USD_NAV_OVERFLOW")
    return float(value)


@dataclass(frozen=True)
class ForeignCashReceivable:
    event_id: str
    old_security_id: str
    ex_date: str
    pay_date: str
    entitled_raw_shares: float
    currency: str
    amount_foreign: float
    source_fingerprint: str


STOCK_DISTRIBUTION_RESEARCH_MODE = "BENEFICIAL_FRACTIONAL_ECONOMIC_INTEREST_RESEARCH_ASSUMPTION"


@dataclass(frozen=True)
class SourceBackedStockDistributionEvent:
    """Nonterminal parent plus child right; issuer cash-in-lieu is not simulated.

    The caller binds official security, quantity, delivery and listing facts.
    This closed research capability supports delivery no later than ex session.
    Raw price adjustment factors are never a child share quantity coordinate.
    """
    event_id: str
    action_type: str
    old_security_id: str
    ticker: str
    ex_date: str
    record_date: str
    available_at: str
    child_security_id: str
    child_ticker: str
    child_ratio_numerator: int
    child_ratio_denominator: int
    child_quantity_unit: str
    delivery_date: str
    regular_trading_date: str
    quantity_coordinate: str
    source_type: str
    source_reference: str
    source_fingerprint: str
    original_cash_in_lieu_terms: str
    research_mode: str = STOCK_DISTRIBUTION_RESEARCH_MODE
    parent_share_multiplier: float = 1.0

    def __post_init__(self):
        values = (self.event_id, self.old_security_id, self.ticker,
            self.child_security_id, self.child_ticker, self.source_reference,
            self.original_cash_in_lieu_terms)
        if any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError("STOCK_DISTRIBUTION_SOURCE_SECURITY_AND_CIL_TERMS_REQUIRED")
        if any(any(x in sid.upper() for x in ("FROZEN_VENDOR:", "UNKNOWN", "PLACEHOLDER", "UNCONFIRMED"))
               for sid in (self.old_security_id, self.child_security_id)):
            raise ValueError("STOCK_DISTRIBUTION_PLACEHOLDER_SECURITY_FORBIDDEN")
        if (self.old_security_id == self.child_security_id or self.ticker == self.child_ticker
                or self.action_type != "MULTI_SECURITY_STOCK_DISTRIBUTION"
                or self.source_type not in AUTHORIZED_SOURCE_TYPES
                or not re.fullmatch(r"[0-9a-fA-F]{64}", str(self.source_fingerprint))
                or self.quantity_coordinate != RAW_OLD_SHARE_COORDINATE
                or self.child_quantity_unit not in ("COMMON_SHARE", "AMERICAN_DEPOSITARY_SHARE")
                or self.research_mode != STOCK_DISTRIBUTION_RESEARCH_MODE
                or type(self.parent_share_multiplier) not in (float, int)
                or self.parent_share_multiplier != 1.):
            raise ValueError("STOCK_DISTRIBUTION_EXPLICIT_RAW_SHARE_RESEARCH_TERMS_REQUIRED")
        if any(type(x) is not int or x <= 0 for x in
               (self.child_ratio_numerator, self.child_ratio_denominator)):
            raise ValueError("STOCK_DISTRIBUTION_OFFICIAL_POSITIVE_RATIONAL_RATIO_REQUIRED")
        ex, record, delivery, regular = map(_entitlement_day,
            (self.ex_date, self.record_date, self.delivery_date, self.regular_trading_date))
        _entitlement_available(self.available_at)
        if (not pd.Timestamp("2023-01-01") <= ex < pd.Timestamp("2026-01-01")
                or record > ex or delivery > ex or regular > ex):
            raise ValueError("STOCK_DISTRIBUTION_CLOSED_PRE2026_DELIVERY_BY_EX_SCOPE_REQUIRED")

    @property
    def event_fingerprint(self):
        return hashlib.sha256(canonical_bytes(asdict(self))).hexdigest()


@dataclass(frozen=True)
class StockClaim:
    event_id: str
    old_security_id: str
    child_security_id: str
    ex_date: str
    delivery_date: str
    entitled_raw_parent_shares: float
    child_units: float
    child_quantity_unit: str
    source_fingerprint: str


CLOSED_RECORD_RESEARCH_POLICY = "CLOSED_RECORD_NEXT_SESSION_RESEARCH"
CLOSED_RECORD_RESEARCH_ROLE = "EXACT_FROZEN_EVENT_NEXT_SESSION_AFTER_OFFICIAL_CLOSED_RECORD_RESEARCH_ONLY"


def validate_closed_record_research_binding(binding, *, calendar=None, record_date=None,
        pay_date=None, ex_date=None, security_id=None, ticker=None, original_key=None):
    """Exact accounting coordinate; pinned closure is not dividend-ex authority."""
    expected=dict(schema="B_FROZEN_HISTORY_CLOSED_RECORD_NEXT_SESSION_RESEARCH_BINDING_V1",
        status="PINNED_ORIGINAL_FROZEN_EX_ON_NEXT_SESSION_AFTER_OFFICIAL_CLOSED_RECORD",
        policy_id=CLOSED_RECORD_RESEARCH_POLICY,ex_coordinate_role=CLOSED_RECORD_RESEARCH_ROLE,
        entitlement_reconstruction_role="PRIOR_LEGAL_SESSION_HOLDINGS_AT_NEXT_SESSION_PREOPEN_RESEARCH_ASSUMPTION_NOT_EXCHANGE_EX_AUTHORITY",
        scope_start="2023-01-01",scope_end_exclusive="2026-01-01",clock_role="POST_VERIFIED_ACCOUNTING_ONLY",
        accounting_clock_convention="ORDINARY_CASH_PAY_DATE_END_NEXT_ACCOUNT_SESSION",
        currency="USD",amount_unit=USD_PER_RAW_OLD_SHARE,quantity_coordinate=RAW_OLD_SHARE_COORDINATE,
        available_at=None,source_declared_ex_date=None,actual_exchange_ex_authority="UNKNOWN",
        clearing_delivery_day_authority="UNKNOWN",historical_availability_authority="UNKNOWN",
        special_or_due_bill=False,late_notice_indicator=False,noncash_or_split_absent=True,
        strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False)
    if not isinstance(binding,dict) or any(type(binding.get(k)) is not type(v) or binding.get(k)!=v for k,v in expected.items()):
        raise ValueError("CLOSED_RECORD_EXPLICIT_RESEARCH_BINDING_REQUIRED")
    cb=binding.get("calendar_binding",{})
    if not isinstance(cb,dict) or cb.get("status")!="SOURCE_BOUND_LEGAL_SESSION_CALENDAR":
        raise ValueError("CLOSED_RECORD_COMPLETE_FROZEN_CALENDAR_REQUIRED")
    strings=cb.get("session_dates")
    if (not isinstance(strings,list) or len(strings)!=752
            or any(not isinstance(d,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",d) for d in strings)
            or strings!=sorted(set(strings))
            or hashlib.sha256(canonical_bytes(strings)).hexdigest()!=cb.get("session_dates_sha256")):
        raise ValueError("CLOSED_RECORD_COMPLETE_FROZEN_CALENDAR_REQUIRED")
    sessions=tuple(_entitlement_day(d) for d in strings)
    if (any(not pd.Timestamp("2023-01-01")<=d<pd.Timestamp("2026-01-01") for d in sessions)
            or calendar is not None and tuple(_entitlement_day(d) for d in calendar)!=sessions):
        raise ValueError("CLOSED_RECORD_CALENDAR_CHANGED")
    for ref in (cb.get("calendar_source_ref"),binding.get("official_closure_source_ref"),
            binding.get("official_closure_original_HTTP_ref"),binding.get("source_cash_custody_ref")):
        if (not isinstance(ref,dict) or set(ref) not in ({"path","sha256"},{"path","sha256","bytes"})
                or not isinstance(ref.get("path"),str) or not re.match(r"^D:[/\\]",ref["path"])
                or not re.fullmatch(r"[0-9a-f]{64}",str(ref.get("sha256")))
                or "bytes" in ref and (type(ref["bytes"]) is not int or ref["bytes"]<=0)):
            raise ValueError("CLOSED_RECORD_EXACT_PINNED_SOURCE_REFS_REQUIRED")
    if cb.get("source_reference")!=cb["calendar_source_ref"]["path"] or cb.get("source_fingerprint")!=cb["calendar_source_ref"]["sha256"]:
        raise ValueError("CLOSED_RECORD_CALENDAR_PHYSICAL_PIN_CHANGED")
    for name,value in (("record_date",record_date),("pay_date",pay_date),("ex_date",ex_date),
            ("security_id",security_id),("ticker",ticker),("original_exact_key",original_key)):
        if value is not None and binding.get(name)!=(str(_entitlement_day(value).date()) if name.endswith("date") else value):
            raise ValueError("CLOSED_RECORD_LITERAL_SUBJECT_CHANGED:"+name)
    record,ex,pay=map(_entitlement_day,(binding["record_date"],binding["ex_date"],binding["pay_date"]))
    prior=[d for d in sessions if d<record];after=[d for d in sessions if d>record];spendable=[d for d in sessions if d>pay]
    if (record in sessions or not prior or not after or not spendable
            or after[0]!=ex or record>=ex or ex>pay or pay>=pd.Timestamp("2026-01-01")
            or binding.get("prior_entitlement_session")!=str(prior[-1].date())
            or binding.get("next_spendable_session")!=str(spendable[0].date())
            or sessions[sessions.index(ex)-1]!=prior[-1]):
        raise ValueError("CLOSED_RECORD_ADJACENT_SESSION_AND_PAY_CLOCK_REQUIRED")
    key=binding.get("original_exact_key",{})
    if (set(key)!={"ticker","effective_date","reason","source_reference","source_fingerprint"}
            or key.get("ticker")!=binding.get("ticker") or key.get("effective_date")!=str(ex.date())
            or key.get("reason")!="VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY"
            or not isinstance(key.get("source_reference"),str) or not key["source_reference"].strip()
            or not re.fullmatch(r"[0-9a-f]{64}",str(key.get("source_fingerprint")))
            or not isinstance(binding.get("security_id"),str) or not binding["security_id"].strip()
            or any(v in binding["security_id"].upper() for v in ("UNKNOWN","FROZEN_VENDOR:","PLACEHOLDER"))):
        raise ValueError("CLOSED_RECORD_ORIGINAL_EXACT_KEY_AND_SECURITY_REQUIRED")
    return ex


def _validate_cash_entitlement_terms(event, *, allow_unknown_publication=False):
    # Strict callers retain exactly the same checks and error codes.
    _cash_source_identity(event)
    ex, record, pay = map(_entitlement_day, (event.ex_date, event.record_date, event.pay_date))
    if not allow_unknown_publication or event.available_at is not None:
        _entitlement_available(event.available_at)
    if event.action_type not in CASH_ENTITLEMENT_FAMILIES + BLOCKED_ENTITLEMENT_FAMILIES:
        raise ValueError("ENTITLEMENT_ACTION_FAMILY_UNKNOWN")
    if event.action_type in CASH_ENTITLEMENT_FAMILIES:
        if allow_unknown_publication and isinstance(event,ResearchClosedRecordCashEvent):
            if event.action_type!="CASH_DIVIDEND" or event.available_at is not None:
                raise ValueError("CLOSED_RECORD_ORDINARY_RESEARCH_CASH_ONLY")
            validate_closed_record_research_binding(event.closed_record_research_binding,
                record_date=event.record_date,pay_date=event.pay_date,ex_date=event.ex_date,
                security_id=event.old_security_id,ticker=event.ticker)
        elif not ex <= record <= pay:
            raise ValueError("ENTITLEMENT_DUE_BILL_OR_DATE_ORDER_UNSUPPORTED")
        if (event.cash_per_old_share is None or isinstance(event.cash_per_old_share, bool)
                or not math.isfinite(event.cash_per_old_share) or event.cash_per_old_share < 0):
            raise ValueError("ENTITLEMENT_EXPLICIT_FINITE_CASH_AMOUNT_REQUIRED")


@dataclass(frozen=True)
class ResearchReconstructedCashEvent(SourceBackedEntitlementEvent):
    """Post-verified realized cash terms; never a publication-time assertion.

    Default is the exact six-policy 2026 descriptive admission. An explicit
    pre2026 research-account cash admission is a separate accounting-only scope.
    Ownership, receivable and payment use the unchanged entitlement lifecycle.
    """
    available_at: str | None
    reconstruction_ref: str = ""
    reconstruction_sha256: str = ""
    clock_role: str = "POST_VERIFIED_ACCOUNTING_ONLY"

    source_scope: InitVar[str] = "US_2026_SOURCE_ONLY"

    def __post_init__(self, source_scope="US_2026_SOURCE_ONLY"):
        bounds={"US_2026_SOURCE_ONLY":("2026-01-01","2027-01-01"),
            "B_FROZEN_PRE2026_ACCOUNTING_ONLY":("2023-01-01","2026-01-01")}
        if source_scope not in bounds:
            raise ValueError("RESEARCH_CASH_SOURCE_SCOPE_UNKNOWN")
        start,end=map(pd.Timestamp,bounds[source_scope])
        _validate_cash_entitlement_terms(self, allow_unknown_publication=True)
        if (self.action_type not in CASH_ENTITLEMENT_FAMILIES
                or not start <= _entitlement_day(self.ex_date) < end
                or self.clock_role != "POST_VERIFIED_ACCOUNTING_ONLY"
                or not isinstance(self.reconstruction_ref, str) or not self.reconstruction_ref.strip()
                or not re.fullmatch(r"[0-9a-fA-F]{64}", str(self.reconstruction_sha256))):
            raise ValueError("RESEARCH_CASH_SOURCE_TERMS_AND_RECONSTRUCTION_REQUIRED")


@dataclass(frozen=True)
class ResearchClosedRecordCashEvent(ResearchReconstructedCashEvent):
    """Separate research type preserves all strict and prior event fingerprints."""
    closed_record_research_binding: dict | None = None

    def __post_init__(self, source_scope="US_2026_SOURCE_ONLY"):
        if source_scope!="B_FROZEN_PRE2026_ACCOUNTING_ONLY":
            raise ValueError("CLOSED_RECORD_PRE2026_ACCOUNTING_SCOPE_REQUIRED")
        super().__post_init__(source_scope=source_scope)


@dataclass(frozen=True)
class SourceBackedTerminalSettlement:
    """Independent fixed payment-date authority, never an inferred deadline."""
    event_id: str
    old_security_id: str
    pay_date: str
    available_at: str
    cash_per_old_share: float
    amount_unit: str
    quantity_coordinate: str
    source_type: str
    source_reference: str
    source_fingerprint: str
    currency: str = "USD"
    authority: str = "SOURCE_CONFIRMED_PAYMENT_DATE"

    def __post_init__(self):
        day = _entitlement_day(self.pay_date)
        open_at = (day + pd.Timedelta(hours=9, minutes=30)).tz_localize("America/New_York").tz_convert("UTC")
        if _entitlement_available(self.available_at) > open_at:
            raise ValueError("TERMINAL_PAYMENT_AUTHORITY_NOT_AVAILABLE_BY_PAY_OPEN")
        if (self.currency != "USD" or self.authority != "SOURCE_CONFIRMED_PAYMENT_DATE"
                or not self.event_id or not self.old_security_id
                or self.amount_unit != USD_PER_RAW_OLD_SHARE
                or self.quantity_coordinate != RAW_OLD_SHARE_COORDINATE
                or not isinstance(self.cash_per_old_share, (int, float))
                or isinstance(self.cash_per_old_share, bool) or not math.isfinite(self.cash_per_old_share)
                or self.cash_per_old_share < 0
                or self.source_type not in AUTHORIZED_SOURCE_TYPES[:2]
                or not isinstance(self.source_reference, str) or not self.source_reference.strip()
                or not re.fullmatch(r"[0-9a-fA-F]{64}", str(self.source_fingerprint))):
            raise ValueError("TERMINAL_PAYMENT_AUTHORITY_REQUIRED")


@dataclass(frozen=True)
class SourceBackedTerminalEvent:
    """Old stock extinguishes into a fixed cash right; payment is separate."""
    event_id: str
    old_security_id: str
    ticker: str
    effective_at: str
    available_at: str
    cash_per_old_share: float
    currency: str
    amount_unit: str
    quantity_coordinate: str
    quantity_source_reference: str
    quantity_source_fingerprint: str
    source_type: str
    source_reference: str
    source_fingerprint: str
    settlement: SourceBackedTerminalSettlement | None = None
    action_type: str = "MERGER_CASH_CONVERSION"
    effective_clock_basis: str = "SOURCE_CONFIRMED_TIME"

    def __post_init__(self):
        _cash_source_identity(self)
        effective = _entitlement_available(self.effective_at)
        available = _entitlement_available(self.available_at)
        day = effective.tz_convert("America/New_York").tz_localize(None).normalize()
        open_at = (day + pd.Timedelta(hours=9, minutes=30)).tz_localize("America/New_York").tz_convert("UTC")
        if available > open_at:
            raise ValueError("TERMINAL_SOURCE_NOT_AVAILABLE_BY_EFFECTIVE_OPEN")
        if effective > open_at or self.effective_clock_basis not in (
                "SOURCE_CONFIRMED_TIME", "SOURCE_EFFECTIVE_BY_OPEN_UPPER_BOUND"):
            raise ValueError("TERMINAL_EFFECTIVE_TIME_NOT_SUPPORTED_AT_SESSION_OPEN")
        _validate_terminal_terms(self, day)

    @property
    def effective_date(self):
        return str(_entitlement_available(self.effective_at).tz_convert("America/New_York").date())

    @property
    def event_fingerprint(self):
        return hashlib.sha256(canonical_bytes(asdict(self))).hexdigest()


def _validate_terminal_terms(event, day):
    if (event.action_type != "MERGER_CASH_CONVERSION" or event.source_type not in AUTHORIZED_SOURCE_TYPES[:2]
            or not isinstance(event.cash_per_old_share, (int, float))
            or isinstance(event.cash_per_old_share, bool) or not math.isfinite(event.cash_per_old_share)
            or event.cash_per_old_share < 0 or not isinstance(event.quantity_source_reference, str)
            or not event.quantity_source_reference.strip()
            or not re.fullmatch(r"[0-9a-fA-F]{64}", str(event.quantity_source_fingerprint))):
        raise ValueError("TERMINAL_SOURCE_RAW_QUANTITY_AND_CONSIDERATION_REQUIRED")
    if event.settlement is not None:
        if not isinstance(event.settlement, SourceBackedTerminalSettlement):
            raise ValueError("TERMINAL_SETTLEMENT_TYPE_REQUIRED")
        if _entitlement_day(event.settlement.pay_date) < day:
            raise ValueError("TERMINAL_PAYMENT_BEFORE_EXTINGUISHMENT")
        if (event.settlement.event_id != event.event_id
                or event.settlement.old_security_id != event.old_security_id
                or event.settlement.cash_per_old_share != event.cash_per_old_share
                or event.settlement.currency != event.currency
                or event.settlement.amount_unit != event.amount_unit
                or event.settlement.quantity_coordinate != event.quantity_coordinate):
            raise ValueError("TERMINAL_PAYMENT_SECURITY_AMOUNT_COORDINATE_MISMATCH")


@dataclass(frozen=True)
class ResearchPostVerifiedTerminalEvent(SourceBackedTerminalEvent):
    """2026 realized terminal facts, without publication or payment assumptions.

    Security, date, amount and source terms belong to the sealed task catalogue.
    Only a before-open upper bound and unknown settlement are supported.
    """
    available_at: str | None
    reconstruction_ref: str = ""
    reconstruction_sha256: str = ""
    clock_role: str = "POST_VERIFIED_ACCOUNTING_ONLY"
    effective_clock_basis: str = "SOURCE_EFFECTIVE_BY_OPEN_UPPER_BOUND"

    def __post_init__(self):
        _cash_source_identity(self)
        effective = _entitlement_available(self.effective_at)
        day = effective.tz_convert("America/New_York").tz_localize(None).normalize()
        opening = (day + pd.Timedelta(hours=9, minutes=30)).tz_localize("America/New_York").tz_convert("UTC")
        if (not pd.Timestamp("2026-01-01") <= day < pd.Timestamp("2027-01-01")
                or effective != opening
                or self.effective_clock_basis != "SOURCE_EFFECTIVE_BY_OPEN_UPPER_BOUND"
                or self.available_at is not None or self.settlement is not None
                or self.clock_role != "POST_VERIFIED_ACCOUNTING_ONLY"
                or not isinstance(self.reconstruction_ref, str) or not self.reconstruction_ref.strip()
                or not re.fullmatch(r"[0-9a-fA-F]{64}", str(self.reconstruction_sha256))):
            raise ValueError("RESEARCH_TERMINAL_2026_UNKNOWN_PUBLICATION_AND_SETTLEMENT_REQUIRED")
        _validate_terminal_terms(self, day)


@dataclass(frozen=True)
class ResearchReconstructedTerminalEvent(SourceBackedTerminalEvent):
    """Frozen realized-event accounting; publication time is never invented.

    This separate child type leaves the strict event's fields/fingerprint intact.
    It can be consumed only with the explicit frozen research-account authority.
    """
    reconstruction_ref: str = ""
    reconstruction_sha256: str = ""
    clock_role: str = "RECONSTRUCTED_REALIZED_EVENT"

    def __post_init__(self):
        _cash_source_identity(self)
        effective = _entitlement_available(self.effective_at)
        day = effective.tz_convert("America/New_York").tz_localize(None).normalize()
        opening = (day + pd.Timedelta(hours=9, minutes=30)).tz_localize("America/New_York").tz_convert("UTC")
        if (day >= pd.Timestamp("2026-01-01") or effective > opening
                or self.effective_clock_basis not in (
                    "SOURCE_CONFIRMED_TIME", "SOURCE_EFFECTIVE_BY_OPEN_UPPER_BOUND")):
            raise ValueError("RESEARCH_TERMINAL_EFFECTIVE_TIME_OR_BOUNDARY")
        if self.available_at is not None:
            _entitlement_available(self.available_at)  # Actual publication/read clock only.
        if (self.clock_role != "RECONSTRUCTED_REALIZED_EVENT"
                or not isinstance(self.reconstruction_ref, str) or not self.reconstruction_ref.strip()
                or not re.fullmatch(r"[0-9a-fA-F]{64}", str(self.reconstruction_sha256))):
            raise ValueError("RESEARCH_TERMINAL_RECONSTRUCTION_BINDING_REQUIRED")
        _validate_terminal_terms(self, day)


def _validate_frozen_history_cash_admission(events, admission):
    """Exact pre2026 accounting-only binding; not publication or terminal authority."""
    historical=tuple(e for e in events if isinstance(e, ResearchReconstructedCashEvent)
        and _entitlement_day(e.ex_date)<pd.Timestamp("2026-01-01"))
    if not historical and admission is None:
        return None
    expected=dict(schema="B_FROZEN_HISTORY_POST_VERIFIED_CASH_ADMISSION_V1",
        scientific_identity="FROZEN_HISTORY_RESEARCH_ACCOUNT",
        task_id="V24_B_FAST_TRACK_PAIR_COMPLETION_R1",
        clock_role="POST_VERIFIED_ACCOUNTING_ONLY",
        accounting_clock_convention="ORDINARY_CASH_PAY_DATE_END_NEXT_ACCOUNT_SESSION",
        scope_start="2023-01-01",scope_end_exclusive="2026-01-01",
        strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False)
    if (not historical or not isinstance(admission,dict)
            or any(type(admission.get(k)) is not type(v) or admission.get(k)!=v for k,v in expected.items())):
        raise ValueError("FROZEN_HISTORY_CASH_ADMISSION_REQUIRED")
    contract=admission.get("source_contract_ref")
    if (not isinstance(contract,dict) or set(contract)!={"path","sha256"}
            or not isinstance(contract["path"],str) or not re.match(r"^D:[/\\]",contract["path"])
            or not re.fullmatch(r"[0-9a-f]{64}",str(contract["sha256"]))
            or not re.fullmatch(r"[0-9a-f]{64}",str(admission.get("source_binding_fingerprint")))):
        raise ValueError("FROZEN_HISTORY_CASH_SOURCE_CONTRACT_REQUIRED")
    entries=admission.get("events")
    if (not isinstance(entries,list) or any(not isinstance(x,dict) for x in entries)
            or len({x.get("event_fingerprint") for x in entries})!=len(entries)
            or sorted(x.get("event_fingerprint","") for x in entries)!=sorted(e.event_fingerprint for e in historical)):
        raise ValueError("FROZEN_HISTORY_CASH_EXACT_TYPED_BINDING_REQUIRED")
    for event in historical:
        event.__post_init__(source_scope="B_FROZEN_PRE2026_ACCOUNTING_ONLY")
        if event.action_type!="CASH_DIVIDEND" or event.ticker=="MKFG" or event.cash_per_old_share<=0:
            raise ValueError("FROZEN_HISTORY_CASH_ORDINARY_SCOPE_REQUIRED")
        fingerprint=event.event_fingerprint
        item=next(x for x in entries if x["event_fingerprint"]==fingerprint)
        ref=item.get("source_projection_ref")
        if (ref!={"path":event.reconstruction_ref,"sha256":event.reconstruction_sha256}
                or not re.match(r"^D:[/\\]",event.reconstruction_ref)
                or (event.available_at is not None and _entitlement_available(event.available_at)>=pd.Timestamp("2026-01-01",tz="UTC"))
                or event.source_fingerprint!=event.reconstruction_sha256
                or item.get("publication_available_at")!=event.available_at
                or item.get("historical_availability_qualified") is not False
                or item.get("clock_role")!="POST_VERIFIED_ACCOUNTING_ONLY"):
            raise ValueError("FROZEN_HISTORY_CASH_RECONSTRUCTION_BINDING_CHANGED")
    return dict(admission,events=[dict(x) for x in entries])


_FULL_SELECTOR_ACCOUNT_SCHEMA = "C_FULL_SELECTOR_FIXED_POLICY_ACCOUNT_AUTHORITY_V1"
_FULL_SELECTOR_ACCOUNT_TASK = "V24_C_FULL_SELECTOR_FIXED_POLICY_FAST_R1"


def _validate_full_selector_account_authority(events, authority):
    """New task binding of existing cash and terminal source authorities."""
    events = tuple(events)
    expected = dict(schema=_FULL_SELECTOR_ACCOUNT_SCHEMA,
        scientific_identity="FULL_SELECTOR_FIXED_POLICY_RESEARCH_ACCOUNT",
        task_id=_FULL_SELECTOR_ACCOUNT_TASK, clock_role="POST_VERIFIED_ACCOUNTING_ONLY",
        accounting_clock_convention="ORDINARY_CASH_PAY_DATE_END_NEXT_ACCOUNT_SESSION",
        scope_start="2023-01-01", scope_end_exclusive="2026-01-01",
        strict_PIT_promotion_eligible=False, production_qualified=False,
        quote_qualified=False, certified_NAV=False)
    extra = {"frozen_contract_ref", "event_fingerprints", "ordinary_cash_event_fingerprints",
             "frozen_history_cash_admission", "terminal_source_authority"}
    if (not isinstance(authority, dict) or set(authority) != set(expected) | extra
            or any(type(authority.get(k)) is not type(v) or authority.get(k) != v
                   for k, v in expected.items())):
        raise ValueError("FULL_SELECTOR_ACCOUNT_AUTHORITY_INVALID")
    contract = authority["frozen_contract_ref"]
    if (not isinstance(contract, dict) or set(contract) != {"path", "sha256"}
            or not isinstance(contract["path"], str)
            or not re.match(r"^D:[/\\]", contract["path"])
            or not re.fullmatch(r"[0-9a-f]{64}", str(contract["sha256"]))):
        raise ValueError("FULL_SELECTOR_ACCOUNT_CONTRACT_REF_REQUIRED")
    if (not events or any(not isinstance(e, (SourceBackedEntitlementEvent, SourceBackedTerminalEvent))
                          or isinstance(e, (ResearchPostVerifiedTerminalEvent, SourceBackedForeignCashEvent)) for e in events)
            or any(not pd.Timestamp("2023-01-01") <= _entitlement_effective_day(e)
                       < pd.Timestamp("2026-01-01") for e in events)):
        raise ValueError("FULL_SELECTOR_ACCOUNT_PRE2026_TYPED_SCOPE_REQUIRED")
    pins = authority["event_fingerprints"]
    if (not isinstance(pins, list)
            or any(not isinstance(p, str) or not re.fullmatch(r"[0-9a-f]{64}", p) for p in pins)
            or len(set(pins)) != len(pins)
            or sorted(pins) != sorted(e.event_fingerprint for e in events)):
        raise ValueError("FULL_SELECTOR_ACCOUNT_EXACT_CATALOGUE_REQUIRED")
    ordinary = authority["ordinary_cash_event_fingerprints"]
    by_fingerprint = {e.event_fingerprint: e for e in events}
    if (not isinstance(ordinary, list)
            or any(not isinstance(p, str) or not re.fullmatch(r"[0-9a-f]{64}", p) for p in ordinary)
            or len(set(ordinary)) != len(ordinary) or not set(ordinary).issubset(by_fingerprint)
            or any(isinstance(by_fingerprint[p], SourceBackedTerminalEvent)
                   or by_fingerprint[p].action_type != "CASH_DIVIDEND"
                   or by_fingerprint[p].ticker == "MKFG" for p in ordinary)
            or not {e.event_fingerprint for e in events if isinstance(e, ResearchReconstructedCashEvent)}
                   .issubset(ordinary)):
        raise ValueError("FULL_SELECTOR_ACCOUNT_EXACT_ORDINARY_CASH_SCOPE_REQUIRED")
    terminals = tuple(e for e in events if isinstance(e, SourceBackedTerminalEvent))
    if (len(terminals) != 1 or not isinstance(terminals[0], ResearchReconstructedTerminalEvent)
            or terminals[0].ticker != "MKFG" or terminals[0].cash_per_old_share != 5.
            or terminals[0].settlement is not None):
        raise ValueError("FULL_SELECTOR_ACCOUNT_ORIGINAL_MKFG_UNKNOWN_SETTLEMENT_REQUIRED")
    # These are source-fact provenance bindings; their original task identities
    # are retained rather than being presented as new-task execution authority.
    cash_admission = _validate_frozen_history_cash_admission(
        events, authority["frozen_history_cash_admission"])
    terminal_authority = _validate_research_account_authority(
        terminals, authority["terminal_source_authority"])
    if terminal_authority is None:
        raise ValueError("FULL_SELECTOR_ACCOUNT_ORIGINAL_TERMINAL_AUTHORITY_REQUIRED")
    for event in events:
        if isinstance(event, ResearchReconstructedCashEvent):
            event.__post_init__(source_scope="B_FROZEN_PRE2026_ACCOUNTING_ONLY")
        else:
            event.__post_init__()
    return dict(expected, frozen_contract_ref=dict(contract),
        event_fingerprints=list(pins), ordinary_cash_event_fingerprints=list(ordinary),
        frozen_history_cash_admission=cash_admission,
        terminal_source_authority=terminal_authority)


def _validate_research_account_authority(events, authority):
    if isinstance(authority, dict) and authority.get("schema") == _FULL_SELECTOR_ACCOUNT_SCHEMA:
        return _validate_full_selector_account_authority(events, authority)
    cash_admission=_validate_frozen_history_cash_admission(events,
        authority.get("frozen_history_cash_admission") if isinstance(authority,dict) else None)
    reconstructed = tuple(e for e in events if isinstance(e, ResearchReconstructedTerminalEvent))
    if cash_admission is not None:
        expected_b=dict(schema="B_FROZEN_HISTORY_CASH_ACCOUNT_AUTHORITY_V1",
            scientific_identity="FROZEN_HISTORY_RESEARCH_ACCOUNT",
            task_id="V24_B_FAST_TRACK_PAIR_COMPLETION_R1",clock_role="POST_VERIFIED_ACCOUNTING_ONLY",
            strict_PIT_promotion_eligible=False,production_qualified=False)
        if (set(authority)!=set(expected_b)|{"frozen_history_cash_admission"}
                or any(type(authority.get(k)) is not type(v) or authority.get(k)!=v for k,v in expected_b.items())
                or reconstructed or any(isinstance(e,ResearchPostVerifiedTerminalEvent) for e in events)):
            raise ValueError("B_FROZEN_HISTORY_CASH_STANDALONE_AUTHORITY_REQUIRED")
        return dict(expected_b,frozen_history_cash_admission=cash_admission)
    if authority is None:
        if reconstructed:
            raise ValueError("RESEARCH_ACCOUNT_AUTHORITY_REQUIRED")
        return None
    expected = {
        "scientific_identity": "FROZEN_HISTORY_RESEARCH_ACCOUNT",
        "task_id": "V24_A_FROZEN_HISTORY_RESEARCH_ACCOUNT_AND_POLICY_EVALUATION_R1",
        "clock_role": "RECONSTRUCTED_REALIZED_EVENT",
    }
    if (not isinstance(authority, dict)
            or any(authority.get(k) != v for k, v in expected.items())
            or authority.get("strict_PIT_promotion_eligible") is not False
            or authority.get("production_qualified") is not False
            or not re.fullmatch(r"[0-9a-fA-F]{64}", str(authority.get("frozen_contract_sha256")))
            or not isinstance(authority.get("event_fingerprints"), list)):
        raise ValueError("RESEARCH_ACCOUNT_AUTHORITY_INVALID")
    pins = authority["event_fingerprints"]
    for event in reconstructed:
        event.__post_init__()  # Revalidate deserialized research terms.
    if (any(not isinstance(pin, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", pin) for pin in pins)
            or len(set(pins)) != len(pins)
            or sorted(pins) != sorted(e.event_fingerprint for e in reconstructed)):
        raise ValueError("RESEARCH_ACCOUNT_AUTHORITY_EVENT_BINDING_CHANGED")
    return {**expected, "frozen_contract_sha256": authority["frozen_contract_sha256"],
            "event_fingerprints": list(pins), "strict_PIT_promotion_eligible": False,
            "production_qualified": False,
            **({"frozen_history_cash_admission":cash_admission} if cash_admission is not None else {})}


def _entitlement_effective_day(event):
    return _entitlement_day(event.effective_date if isinstance(event, SourceBackedTerminalEvent) else event.ex_date)


def _entitlement_pay_date(event):
    if isinstance(event, SourceBackedTerminalEvent):
        return event.settlement.pay_date if event.settlement is not None else None
    return None if isinstance(event, SourceBackedStockDistributionEvent) else event.pay_date


@dataclass(frozen=True)
class CashReceivable:
    event_id: str
    old_security_id: str
    ex_date: str
    pay_date: str | None
    entitled_raw_shares: float
    amount_usd: float
    source_fingerprint: str


@dataclass(frozen=True)
class EntitlementLifecycleState:
    catalogue_fingerprint: str = ""
    security_binding_fingerprint: str = ""
    ex_quantities: tuple[tuple[str, float], ...] = ()
    receivables: tuple[CashReceivable, ...] = ()
    paid_event_ids: tuple[str, ...] = ()
    blocked_events: tuple[tuple[str, str], ...] = ()
    last_session: str | None = None
    stock_claims: tuple[StockClaim, ...] = ()
    delivered_stock_event_ids: tuple[str, ...] = ()
    foreign_cash_receivables: tuple[ForeignCashReceivable, ...] = ()


@dataclass(frozen=True)
class EntitlementApplication:
    positions: dict[str, float]
    cash: float
    state: EntitlementLifecycleState
    records: tuple[dict[str, Any], ...]
    receivable_value_usd: float
    accounting_qualified: bool
    fx_conversion_fee_usd: float = 0.


def apply_entitlement_lifecycle(
    events: Iterable[SourceBackedEntitlementEvent | SourceBackedTerminalEvent], positions_by_security_id: dict[str, float],
    cash: float, *, execution_date: Any, session_open_at: Any,
    security_tickers: dict[str, str], quantity_coordinate: str,
    state: EntitlementLifecycleState | None = None, enabled: bool = False,
    research_account_authority: dict | None = None,
    descriptive_accounting_authority=None,
    stock_delivery_quote_qualified: dict[str, bool] | None = None,
    foreign_fx_mark: SourceBackedFXMark | None = None,
    foreign_conversion_friction_bps: float | None = None,
) -> EntitlementApplication:
    """Pure before-open accounting hook, independent of portfolio decisions.

    Caller passes RAW-share positions immediately before ex-session trades and
    retains returned state across years/chunks. Receivables enter NAV but are
    NOT spendable cash; only payment increases cash. Selling the security does
    not erase its claim. Unknown/late source for a held event permanently marks
    this prefix unqualified; late publication never books a past entitlement.
    Events must include every relevant ex session from the start of the prefix.
    Known source terms absent at ex cannot be reconstructed from later holdings.
    No market values, fitting, tax estimate, FX estimate or provider fetch occurs.
    """
    if enabled is not True:
        prior = state or EntitlementLifecycleState()
        if prior.foreign_cash_receivables:
            raise ValueError("FOREIGN_CLAIMS_REQUIRE_ENABLED_SOURCE_MARKED_LIFECYCLE")
        return EntitlementApplication(dict(positions_by_security_id), float(cash), prior, (),
            float(sum(r.amount_usd for r in prior.receivables)), not prior.blocked_events)
    if quantity_coordinate != RAW_OLD_SHARE_COORDINATE:
        raise ValueError("ENTITLEMENT_INPUT_NOT_RAW_SECURITY_SHARES")
    day, open_at = _entitlement_day(execution_date), _entitlement_available(session_open_at)
    if open_at.tz_convert("America/New_York").date() != day.date():
        raise ValueError("ENTITLEMENT_OPEN_SESSION_MISMATCH")
    expected_open = (day + pd.Timedelta(hours=9, minutes=30)).tz_localize("America/New_York").tz_convert("UTC")
    if open_at != expected_open:
        raise ValueError("ENTITLEMENT_REQUIRES_RESEARCH_SESSION_OPEN_0930_NY")
    if not math.isfinite(cash) or cash < 0:
        raise ValueError("ENTITLEMENT_INVALID_CASH")
    positions = {str(k): float(v) for k, v in positions_by_security_id.items()}
    if any(not k or not math.isfinite(v) or v < 0 for k, v in positions.items()):
        raise ValueError("ENTITLEMENT_INVALID_RAW_POSITION")
    if any(v > 0 and not str(security_tickers.get(k, "")).strip() for k, v in positions.items()):
        raise ValueError("ENTITLEMENT_POSITION_SECURITY_BINDING_REQUIRED")
    events = tuple(events)
    research_authority = _validate_research_account_authority(events, research_account_authority)

    def account_pay_date(event):
        pay = _entitlement_pay_date(event)
        if (research_authority is not None
                and research_authority.get("schema") == _FULL_SELECTOR_ACCOUNT_SCHEMA
                and not isinstance(event, SourceBackedTerminalEvent)
                and event.event_fingerprint in research_authority["ordinary_cash_event_fingerprints"]):
            # Issuer pay-date end: the first supplied account session strictly
            # after that date makes the existing claim spendable.
            return str((_entitlement_day(pay) + pd.Timedelta(days=1)).date())
        return pay

    post_verified = tuple(e for e in events if isinstance(e,
        (ResearchReconstructedCashEvent, ResearchPostVerifiedTerminalEvent)))
    descriptive_events=tuple(e for e in events if not (isinstance(e,ResearchReconstructedCashEvent)
        and _entitlement_day(e.ex_date)<pd.Timestamp("2026-01-01")))
    if any(isinstance(e,(ResearchReconstructedCashEvent,ResearchPostVerifiedTerminalEvent)) for e in descriptive_events):
        from scripts.research.a2.evaluation.frozen_test_authority import (
            require_descriptive_decision, validate_reconstructed_accounting_events)
        validate_reconstructed_accounting_events(descriptive_accounting_authority, descriptive_events)
        require_descriptive_decision(descriptive_accounting_authority, day)
    if any(not isinstance(e, (SourceBackedEntitlementEvent, SourceBackedTerminalEvent, SourceBackedStockDistributionEvent)) for e in events):
        raise ValueError("ENTITLEMENT_EVENT_TYPE_REQUIRED")
    ordered = tuple(sorted(events, key=lambda e: (_entitlement_effective_day(e), e.event_id)))
    if any(not isinstance(e, (SourceBackedEntitlementEvent, SourceBackedTerminalEvent, SourceBackedStockDistributionEvent)) for e in ordered):
        raise ValueError("ENTITLEMENT_EVENT_TYPE_REQUIRED")
    if len({e.event_id for e in ordered}) != len(ordered):
        raise ValueError("DUPLICATE_ENTITLEMENT_EVENT_ID")
    terminal_sids = [e.old_security_id for e in ordered if isinstance(e, SourceBackedTerminalEvent)]
    if len(set(terminal_sids)) != len(terminal_sids):
        raise ValueError("DUPLICATE_TERMINAL_SECURITY_IDENTITY")
    terminal_keys = {(e.old_security_id, _entitlement_effective_day(e)) for e in ordered
                     if isinstance(e, SourceBackedTerminalEvent)}
    if any(not isinstance(e, SourceBackedTerminalEvent)
           and (e.old_security_id, _entitlement_effective_day(e)) in terminal_keys for e in ordered):
        raise ValueError("TERMINAL_SIMULTANEOUS_ENTITLEMENT_PRIORITY_UNSUPPORTED")
    economic_keys = [(e.old_security_id, str(_entitlement_effective_day(e).date()), _entitlement_pay_date(e), e.action_type) for e in ordered]
    if len(set(economic_keys)) != len(economic_keys):
        raise ValueError("DUPLICATE_ENTITLEMENT_ECONOMIC_EVENT")
    catalogue = hashlib.sha256(canonical_bytes([asdict(e) for e in ordered])).hexdigest()
    binding = hashlib.sha256(canonical_bytes(security_tickers)).hexdigest()
    prior = state or EntitlementLifecycleState()
    if prior.catalogue_fingerprint and prior.catalogue_fingerprint != catalogue:
        raise ValueError("ENTITLEMENT_FROZEN_CATALOGUE_CHANGED")
    if prior.security_binding_fingerprint and prior.security_binding_fingerprint != binding:
        raise ValueError("ENTITLEMENT_FROZEN_SECURITY_BINDING_CHANGED")
    if prior.last_session is not None and day <= _entitlement_day(prior.last_session):
        raise ValueError("ENTITLEMENT_SESSION_ALREADY_APPLIED_OR_REVERSED")
    ex_quantities, claims = dict(prior.ex_quantities), {r.event_id: r for r in prior.receivables}
    paid, blocked = set(prior.paid_event_ids), dict(prior.blocked_events)
    stock_claims = {r.event_id: r for r in prior.stock_claims}
    delivered_stock = set(prior.delivered_stock_event_ids)
    foreign_claims = {r.event_id: r for r in prior.foreign_cash_receivables}
    fx_fee_total = 0.
    rows = []

    def record(event, phase, **values):
        reconstruction = (dict(clock_role=event.clock_role,
            publication_available_at=event.available_at,
            accounting_effective_at=event.effective_at,
            reconstruction_ref=event.reconstruction_ref,
            reconstruction_sha256=event.reconstruction_sha256)
            if isinstance(event, (ResearchReconstructedTerminalEvent, ResearchPostVerifiedTerminalEvent)) else {})
        if isinstance(event, ResearchReconstructedCashEvent):
            reconstruction = dict(clock_role=event.clock_role,
                publication_available_at=event.available_at,
                accounting_effective_at=str((_entitlement_day(event.ex_date)
                    + pd.Timedelta(hours=9, minutes=30)).tz_localize("America/New_York").tz_convert("UTC")),
                accounting_boundary_role="EX_SESSION_PRETRADE_NOT_PUBLICATION_TIME",
                reconstruction_ref=event.reconstruction_ref,
                reconstruction_sha256=event.reconstruction_sha256)
        if isinstance(event, ResearchPostVerifiedTerminalEvent):
            reconstruction["accounting_boundary_role"] = "SOURCE_BEFORE_OPEN_UPPER_BOUND_NOT_PUBLICATION_TIME"
        if (research_authority is not None
                and research_authority.get("schema") == _FULL_SELECTOR_ACCOUNT_SCHEMA
                and not isinstance(event, SourceBackedTerminalEvent)
                and event.event_fingerprint in research_authority["ordinary_cash_event_fingerprints"]):
            reconstruction.update(issuer_pay_date=event.pay_date,
                accounting_clock_convention="ORDINARY_CASH_PAY_DATE_END_NEXT_ACCOUNT_SESSION",
                spendable_not_before=account_pay_date(event))
        rows.append(dict(event_id=event.event_id, event_fingerprint=event.event_fingerprint,
                         old_security_id=event.old_security_id, ticker=event.ticker,
                         session=str(day.date()), phase=phase,
                         source_fingerprint=event.source_fingerprint, **reconstruction, **values))

    def block(event, reason):
        if event.event_id not in blocked:
            blocked[event.event_id] = reason
            record(event, "BLOCKED_ACCOUNTING_ENTITLEMENT", reason=reason)

    for event in ordered:
        terminal = isinstance(event, SourceBackedTerminalEvent)
        ex = _entitlement_effective_day(event)
        if day < ex:
            continue
        available = (True if (
            research_authority is not None and isinstance(event, ResearchReconstructedTerminalEvent)
            or post_verified and isinstance(event, (ResearchReconstructedCashEvent, ResearchPostVerifiedTerminalEvent)))
            else _entitlement_available(event.available_at) <= open_at)
        if day == ex:
            quantity = positions.get(event.old_security_id, 0.0)
            if quantity > 0 and security_tickers.get(event.old_security_id) != event.ticker:
                raise ValueError("ENTITLEMENT_SECURITY_TICKER_MISMATCH")
            ex_quantities[event.event_id] = quantity
            if quantity > 0:
                record(event, "TERMINAL_PRE_EFFECTIVE_RAW_SHARE_SNAPSHOT" if terminal else "EX_PRETRADE_RAW_SHARE_SNAPSHOT", entitled_raw_shares=quantity)
        elif event.event_id not in ex_quantities:
            # Never infer earlier ownership from present positions. Missing
            # ex evidence is a caller error for an exposed security, not a
            # permanent qualification flag for unrelated/unheld accounts.
            if positions.get(event.old_security_id, 0.0) > 0:
                raise ValueError("MISSING_EX_PRETRADE_POSITION_SNAPSHOT")
            continue
        quantity = ex_quantities[event.event_id]
        if terminal:
            if not available:
                raise ValueError("TERMINAL_SOURCE_NOT_AVAILABLE_BY_EFFECTIVE_OPEN")
            if day > ex and positions.get(event.old_security_id, 0.0) > 0:
                raise ValueError("TERMINAL_OLD_SECURITY_REAPPEARED")
            if event.old_security_id in positions:
                positions[event.old_security_id] = 0.0
            if day == ex and quantity > 0:
                record(event, "SECURITY_EXTINGUISHED", entitled_raw_shares=quantity,
                       remaining_raw_shares=0.0, effective_at=event.effective_at,
                       action_type=event.action_type, spendable_cash_delta=0.0)
        if quantity <= 0:
            continue  # Unheld unknown events never contaminate unrelated accounts.
        if isinstance(event, SourceBackedForeignCashEvent):
            if foreign_conversion_friction_bps != 25. or type(foreign_conversion_friction_bps) not in (int, float):
                raise ValueError("FROZEN_CAD_CONVERSION_FRICTION_25BP_REQUIRED")
            if event.event_id in blocked or event.event_id in paid:
                continue
            if not available:
                block(event, "SOURCE_NOT_AVAILABLE_BY_EX_OPEN")
                continue
            if event.event_id not in foreign_claims:
                if day != ex:
                    raise ValueError("MISSING_EX_FOREIGN_CASH_CLAIM_STATE")
                amount = quantity * event.cash_per_old_share
                if not math.isfinite(amount):
                    raise ValueError("FOREIGN_CASH_CLAIM_OVERFLOW")
                foreign_claims[event.event_id] = ForeignCashReceivable(event.event_id, event.old_security_id,
                    str(ex.date()), account_pay_date(event), quantity, event.currency, amount, event.source_fingerprint)
                record(event, "FOREIGN_CASH_RECEIVABLE_RECOGNIZED", currency=event.currency,
                    amount_foreign=amount, spendable_cash_delta=0., tax_withholding_mode="NOT_MODELED_GROSS_RESEARCH")
            if foreign_fx_mark is None or select_foreign_fx_mark((foreign_fx_mark,), as_of=open_at) is None:
                block(event, "FOREIGN_CLAIM_WITHOUT_PUBLISHED_LEGAL_FX_NAV_MARK")
                continue
            if day >= _entitlement_day(account_pay_date(event)):
                claim = foreign_claims.pop(event.event_id)
                gross_usd = foreign_claim_value_usd((claim,), foreign_fx_mark, as_of=open_at)
                fee = gross_usd * foreign_conversion_friction_bps / 10000.
                net = gross_usd - fee
                cash += net
                if not math.isfinite(cash):
                    raise ValueError("FOREIGN_PAYMENT_CASH_OVERFLOW")
                fx_fee_total += fee
                paid.add(event.event_id)
                record(event, "FOREIGN_CASH_PAID_AND_CONVERTED_RESEARCH", currency=claim.currency,
                    amount_foreign=claim.amount_foreign, paid_gross_usd=gross_usd,
                    fx_conversion_fee_usd=fee, amount_usd=net, spendable_cash_delta=net,
                    fx_observation_date=foreign_fx_mark.observation_date,
                    fx_available_at=foreign_fx_mark.available_at,
                    fx_rate_unit=foreign_fx_mark.rate_unit, fx_currency_per_usd=foreign_fx_mark.currency_per_usd,
                    fx_source_reference=foreign_fx_mark.source_reference,
                    fx_source_fingerprint=foreign_fx_mark.source_fingerprint,
                    actual_broker_fx_payment_fee_tax_certified=False)
            continue
        if isinstance(event, SourceBackedStockDistributionEvent):
            if event.event_id in blocked or event.event_id in delivered_stock:
                continue
            if not available:
                block(event, "SOURCE_NOT_AVAILABLE_BY_EX_OPEN")
                continue
            if security_tickers.get(event.child_security_id) != event.child_ticker:
                raise ValueError("STOCK_DISTRIBUTION_CHILD_SECURITY_TICKER_BINDING_REQUIRED")
            if event.event_id not in stock_claims:
                if day != ex:
                    raise ValueError("MISSING_EX_STOCK_CLAIM_STATE")
                child_units = quantity * event.child_ratio_numerator / event.child_ratio_denominator
                if not math.isfinite(child_units) or child_units <= 0:
                    raise ValueError("STOCK_DISTRIBUTION_INVALID_CHILD_UNITS")
                stock_claims[event.event_id] = StockClaim(event.event_id, event.old_security_id,
                    event.child_security_id, str(ex.date()), event.delivery_date, quantity,
                    child_units, event.child_quantity_unit, event.source_fingerprint)
                record(event, "NONSPENDABLE_STOCK_CLAIM_RECOGNIZED", child_units=child_units,
                    child_security_id=event.child_security_id, spendable_cash_delta=0.)
            claim = stock_claims[event.event_id]
            qualified = (stock_delivery_quote_qualified or {}).get(event.child_security_id)
            if (day < _entitlement_day(event.delivery_date)
                    or day < _entitlement_day(event.regular_trading_date) or qualified is not True):
                block(event, "STOCK_CLAIM_WITHOUT_QUALIFIED_DELIVERABLE_RAW_QUOTE_NAV_MARK")
                continue
            positions[event.child_security_id] = positions.get(event.child_security_id, 0.) + claim.child_units
            if not math.isfinite(positions[event.child_security_id]):
                raise ValueError("STOCK_DISTRIBUTION_CHILD_POSITION_OVERFLOW")
            stock_claims.pop(event.event_id)
            delivered_stock.add(event.event_id)
            record(event, "STOCK_DISTRIBUTION_DELIVERED", child_units=claim.child_units,
                child_security_id=event.child_security_id, child_ticker=event.child_ticker,
                parent_share_multiplier=1., spendable_cash_delta=0.,
                child_quantity_unit=event.child_quantity_unit,
                research_mode=event.research_mode, actual_broker_fractional_delivery_certified=False)
            continue
        if event.action_type in BLOCKED_ENTITLEMENT_FAMILIES:
            block(event, "UNSUPPORTED_NONCASH_OR_MULTI_SECURITY_ENTITLEMENT:" + event.action_type)
            continue
        if event.event_id in blocked:
            continue  # Late publication cannot retroactively create a claim.
        if not available:
            block(event, "SOURCE_NOT_AVAILABLE_BY_EX_OPEN")
            continue
        if event.event_id not in claims and event.event_id not in paid:
            if day != ex:
                raise ValueError("MISSING_EX_RECEIVABLE_STATE")
            amount = quantity * float(event.cash_per_old_share)
            if not math.isfinite(amount):
                raise ValueError("ENTITLEMENT_NONFINITE_RECEIVABLE")
            visible_pay = (account_pay_date(event) if not terminal or (event.settlement is not None
                and _entitlement_available(event.settlement.available_at) <= open_at) else None)
            claims[event.event_id] = CashReceivable(event.event_id, event.old_security_id,
                str(ex.date()), visible_pay, quantity, amount, event.source_fingerprint)
            record(event, "MERGER_RECEIVABLE_RECOGNIZED" if terminal else "RECEIVABLE_RECOGNIZED", amount_usd=amount, spendable_cash_delta=0.0,
                   late_recognition=day > ex, historical_certification_restored=False)
        if terminal and (event.settlement is None
                or _entitlement_available(event.settlement.available_at) > open_at):
            if day == ex:
                record(event, "SETTLEMENT_PENDING_AUTHORITY", spendable_cash_delta=0.0)
            # The already sourced USD cash right remains a legal NAV asset. A
            # missing settlement bundle is a separate whole-account acceptance
            # failure in the consumer; no future pay term reaches policy state.
            continue
        pay_date = account_pay_date(event)
        if terminal and event.event_id in claims and claims[event.event_id].pay_date is None:
            claim = claims[event.event_id]
            claims[event.event_id] = CashReceivable(claim.event_id, claim.old_security_id,
                claim.ex_date, pay_date, claim.entitled_raw_shares, claim.amount_usd, claim.source_fingerprint)
            record(event, "SETTLEMENT_AUTHORITY_AVAILABLE", settlement_source_reference=event.settlement.source_reference,
                   settlement_source_fingerprint=event.settlement.source_fingerprint, spendable_cash_delta=0.0)
        if event.event_id in claims and day >= _entitlement_day(pay_date):
            claim = claims.pop(event.event_id)
            cash += claim.amount_usd
            if not math.isfinite(cash):
                raise ValueError("ENTITLEMENT_CASH_OVERFLOW")
            paid.add(event.event_id)
            record(event, "CASH_PAID", amount_usd=claim.amount_usd,
                   spendable_cash_delta=claim.amount_usd, entitled_raw_shares=claim.entitled_raw_shares,
                   **({"settlement_source_reference":event.settlement.source_reference,
                       "settlement_source_fingerprint":event.settlement.source_fingerprint} if terminal else {}))
    result_state = EntitlementLifecycleState(catalogue, binding,
        tuple(sorted(ex_quantities.items())), tuple(claims[k] for k in sorted(claims)),
        tuple(sorted(paid)), tuple(sorted(blocked.items())), str(day.date()),
        tuple(stock_claims[k] for k in sorted(stock_claims)), tuple(sorted(delivered_stock)),
        tuple(foreign_claims[k] for k in sorted(foreign_claims)))
    receivable_value = float(sum(r.amount_usd for r in result_state.receivables))
    if result_state.foreign_cash_receivables:
        try:
            receivable_value += foreign_claim_value_usd(result_state.foreign_cash_receivables, foreign_fx_mark, as_of=open_at)
        except ValueError:
            if not any(e.event_id in blocked for e in ordered if isinstance(e, SourceBackedForeignCashEvent)):
                raise
    if not math.isfinite(receivable_value):
        raise ValueError("ENTITLEMENT_RECEIVABLE_TOTAL_OVERFLOW")
    return EntitlementApplication(positions, float(cash), result_state, tuple(rows),
                                  receivable_value, not blocked, fx_fee_total)
