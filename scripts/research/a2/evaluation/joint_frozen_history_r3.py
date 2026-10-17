"""New frozen-history mechanism identity over the unchanged common account.

No readers, fitting, price repair or account implementation. Caller registration
and a published immutable freeze precede real use. Strict PIT and certified NAV
remain false. Current raw-Close snapshot valuation is a new research assumption;
it never changes the engine's indicative marks, policy context or quality mask.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from scripts.research.a2.evaluation import continuous_research_account as common
from scripts.research.a2.evaluation import joint_method_accounts as parameter_source
from scripts.research.a2.evaluation.joint_method_accounts import PARAMETERS
from scripts.research.a2.inference.joint_portfolio_policy import JointResearchPolicy
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2 import fast_account
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
from scripts.v22 import corporate_action_transition_r1 as actions

VALUATION = "CURRENT_FROZEN_RAW_CLOSE_WITH_EXPLICIT_UNCERTIFIED_QUALITY"
CONTROLS = ("CONTROL_RAW_A2_POLICY", "JOINT_SIMPLE_EQUAL")
EVENT_KEYS = frozenset(("corporate_actions", "corporate_action_known_at", "unsupported_events",
    "entitlement_enabled", "entitlement_events", "entitlement_security_tickers", "entitlement_source_binding"))
ACCOUNT = dict(base_currency="USD", initial_nav=3000, initial_cash=3000, initial_holdings=[],
    fractional_shares=True, integer_share_rounding=False, cash_interest=0, transaction_cost_bps=0,
    financing=False, borrowed_cash=False, long_only=True, max_positions=20, max_weight=.1,
    max_invested=1., capacity_fraction=.01)


class FrozenHistoryAccountBlocked(ValueError):
    pass


def source_pins():
    """Source metadata only; no old runner, receipt, model or ledger is loaded."""
    modules = (common, fast_account, actions, parameter_source)
    from scripts.research.a2.inference import joint_portfolio_policy
    modules += (joint_portfolio_policy,)
    paths = [Path(module.__file__).resolve() for module in modules] + [Path(__file__).resolve()]
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def input_digests(market, raw_scores, event_inputs, uncertified_quality_only):
    """Bind already caller-authorized in-memory inputs; this does not load them."""
    return dict(market=content_hash(market), raw_scores=content_hash(np.asarray(raw_scores)),
                events=content_hash(dict(event_inputs)),
                uncertified_quality_only=content_hash(np.asarray(uncertified_quality_only, bool)))


@dataclass(frozen=True)
class FrozenHistoryAccountFreeze:
    research_id: str
    parent_research_id: str
    run_id: str
    registration_receipt_sha256: str
    input_sha256: Mapping[str, str]
    source_sha256: Mapping[str, str]
    identity_assumption: str
    status: str = "FROZEN_FOR_MECHANISM_ACCOUNT"
    research_kind: str = "FROZEN_HISTORY_MECHANISM"
    valuation: str = VALUATION
    raw_price_coordinate: str = "RAW_UNADJUSTED_OPEN_CLOSE"
    quantity_coordinate: str = "RAW_OLD_SECURITY_SHARES"
    source_authority: str = "UNKNOWN"
    historical_availability: str = "UNKNOWN"
    historical_revision: str = "UNKNOWN"
    identity_coordinate_consistent: bool = True
    strict_PIT_promotion_eligible: bool = False
    certified_NAV: bool = False
    quote_qualified: bool = False
    initial_cash_usd: float = 3000.
    one_way_friction_bps: float = 10.
    fee_bps: float = 0.
    cash_interest: float = 0.
    synthetic: bool = False

    def digest(self):
        return content_hash(self)

    @property
    def path_ids(self):
        return tuple(f"{self.research_id}::{role}@10bps" for role in CONTROLS)


@dataclass(frozen=True)
class FrozenHistoryMechanismResult:
    replay: object
    qualification_by_path: Mapping[str, object]
    freeze_sha256: str
    physical_account_replays: int = 2
    physical_fit_count: int = 0


def _freeze_guard(freeze, expected_sha256, market, raw_scores, events, quality_only):
    if not isinstance(freeze, FrozenHistoryAccountFreeze) or freeze.digest() != expected_sha256:
        raise FrozenHistoryAccountBlocked("REGISTERED_IMMUTABLE_MECHANISM_FREEZE_REQUIRED")
    if (not freeze.research_id.strip() or freeze.research_id == freeze.parent_research_id or
            not freeze.parent_research_id.strip() or not freeze.run_id.strip() or
            len(freeze.registration_receipt_sha256) != 64 or
            any(c not in "0123456789abcdef" for c in freeze.registration_receipt_sha256)):
        raise FrozenHistoryAccountBlocked("NEW_REGISTERED_RESEARCH_IDENTITY_REQUIRED")
    expected = dict(status="FROZEN_FOR_MECHANISM_ACCOUNT", research_kind="FROZEN_HISTORY_MECHANISM",
        valuation=VALUATION, raw_price_coordinate="RAW_UNADJUSTED_OPEN_CLOSE",
        quantity_coordinate="RAW_OLD_SECURITY_SHARES", source_authority="UNKNOWN",
        historical_availability="UNKNOWN", historical_revision="UNKNOWN",
        strict_PIT_promotion_eligible=False, certified_NAV=False, quote_qualified=False,
        initial_cash_usd=3000., one_way_friction_bps=10., fee_bps=0., cash_interest=0.)
    if any(getattr(freeze, key) != value for key, value in expected.items()):
        raise FrozenHistoryAccountBlocked("MECHANISM_VALUATION_OR_FIXED_ACCOUNT_CONTRACT_CHANGED")
    if freeze.identity_coordinate_consistent is not True or not freeze.identity_assumption.strip():
        raise FrozenHistoryAccountBlocked("NUMERIC_SECURITY_COORDINATE_CONTRADICTION")
    if freeze.source_sha256 != source_pins():
        raise FrozenHistoryAccountBlocked("CURRENT_SHARED_SOURCE_IDENTITY_CHANGED")
    if freeze.input_sha256 != input_digests(market, raw_scores, events, quality_only):
        raise FrozenHistoryAccountBlocked("FROZEN_SHARED_INPUT_IDENTITY_CHANGED")
    if not set(events).issubset(EVENT_KEYS):
        raise FrozenHistoryAccountBlocked("ONLY_SHARED_CA_ENTITLEMENT_TERMINAL_INPUTS_ALLOWED")
    dates = pd.DatetimeIndex(market.dates)
    if (dates.empty or dates.hasnans or dates.has_duplicates or not dates.is_monotonic_increasing or
            dates.tz is not None or dates[0] < pd.Timestamp("2023-01-01") or
            dates[-1] >= pd.Timestamp("2026-01-01")):
        raise FrozenHistoryAccountBlocked("PHYSICALLY_PRE2026_CONTINUOUS_CALENDAR_REQUIRED")
    scores = np.asarray(raw_scores, float)
    shape = (len(dates), len(market.tickers))
    if scores.shape != shape or quality_only.shape != shape or market.open.shape != shape or market.close.shape != shape:
        raise FrozenHistoryAccountBlocked("EXACT_DATE_SECURITY_COORDINATES_REQUIRED")
    if np.any(quality_only & ~market.quality):
        raise FrozenHistoryAccountBlocked("UNCERTIFIED_MASK_MUST_NOT_INVENT_QUALITY_FLAGS")
    if (np.isinf(market.open).any() or np.isinf(market.close).any() or
            np.any(np.isfinite(market.open) & (market.open <= 0)) or
            np.any(np.isfinite(market.close) & (market.close <= 0))):
        raise FrozenHistoryAccountBlocked("INVALID_RAW_PRICE_COORDINATE")
    # NaN rows stay present in the frozen universe. Eligibility and missing
    # next-Open decisions belong to the shared engine; only actual dependencies
    # enter mechanism qualification below, never the whole supplied universe.
    return scores


def _audit_pass(audit):
    errors = ("cash_identity_error_max", "cost_identity_error_max", "self_finance_error_max",
              "nav_identity_error_max", "actual_cash_flow_identity_error_max")
    return (all(key in audit and np.isfinite(audit[key]) and abs(audit[key]) <= 1e-5 for key in errors) and
            audit.get("next_open_violations") == 0 and audit.get("capacity_violations") == 0 and
            audit.get("max_actual_names", 21) <= 20 and audit.get("minimum_cash", -1) >= -1e-8)


def _qualify(replay, market, quality_only, freeze, selection_gaps):
    """One current-day raw snapshot; no prior mark substitution or price repair."""
    daily, positions = replay.daily.copy(), replay.positions.copy()
    di, ti = pd.Index(market.dates), pd.Index(market.tickers)
    if daily.duplicated(["path_id", "date"]).any() or positions.duplicated(["path_id", "date", "ticker"]).any():
        raise FrozenHistoryAccountBlocked("DUPLICATE_SHARED_ACCOUNT_ROWS")
    value, endpoints, quality = {}, {}, {}
    for row in positions.itertuples():
        d, c = di.get_indexer([row.date])[0], ti.get_indexer([row.ticker])[0]
        if d < 0 or c < 0:
            raise FrozenHistoryAccountBlocked("POSITION_DATE_OR_SECURITY_COORDINATE_SWAP")
        shares = float(row.fractional_shares)
        if not np.isfinite(shares) or shares < 0:
            raise FrozenHistoryAccountBlocked("INVALID_RAW_SHARE_QUANTITY")
        key = (row.path_id, row.date)
        valid = bool(market.row_present[d, c] and np.isfinite(market.close[d, c]) and market.close[d, c] > 0 and
                     np.isfinite(market.open[d, c]) and market.open[d, c] > 0)
        pure_quality = bool(not market.quality[d, c] or quality_only[d, c])
        endpoints[key] = endpoints.get(key, True) and valid
        quality[key] = quality.get(key, True) and pure_quality
        if valid:
            value[key] = value.get(key, 0.) + shares*float(market.close[d, c])
        else:
            value[key] = np.nan
    audit_pass = _audit_pass(replay.audit)
    execution_gaps = {path: [] for path in freeze.path_ids}
    for row in replay.execution_results.itertuples():
        if row.status != "REJECTED": continue
        material = row.reason in {"MISSING_PRICE_ROW", "MISSING_OR_INVALID_OPEN", "MISSING_SIGNAL_ADV", "UNKNOWN_NAV"}
        if row.reason == "PRICE_QUALITY_UNCERTIFIED":
            d, c = di.get_indexer([row.execution_date])[0], ti.get_indexer([row.ticker])[0]
            if d < 0 or c < 0:
                raise FrozenHistoryAccountBlocked("EXECUTION_DATE_OR_SECURITY_COORDINATE_SWAP")
            material = not (quality_only[d, c] and market.row_present[d, c] and
                            np.isfinite(market.open[d, c]) and market.open[d, c] > 0)
        if material:
            execution_gaps[row.path_id].append(dict(date=str(row.execution_date), ticker=row.ticker, reason=row.reason))
    for row in replay.fills.itertuples():
        d, c = di.get_indexer([row.execution_date])[0], ti.get_indexer([row.ticker])[0]
        if (d < 0 or c < 0 or not market.row_present[d, c] or not np.isfinite(market.open[d, c]) or
                market.open[d, c] <= 0 or not np.isclose(row.raw_Open, market.open[d, c], rtol=1e-12, atol=1e-8)):
            raise FrozenHistoryAccountBlocked("ACTUAL_FILL_RAW_OPEN_COORDINATE_MISMATCH")
    qualified, raw_values, finite_values, quality_values = [], [], [], []
    for row in daily.itertuples():
        key = (row.path_id, row.date)
        rights = float(getattr(row, "receivable_value_usd", 0.))
        cash = float(row.cash)
        raw = cash+value.get(key, 0.)+rights
        finite = endpoints.get(key, True) and np.isfinite([cash, rights, raw]).all() and cash >= -1e-8 and rights >= 0
        source_only = quality.get(key, True)
        economic = bool(row.accounting_qualified)
        complete = not selection_gaps[row.path_id] and not execution_gaps[row.path_id]
        qualified.append(bool(finite and source_only and economic and audit_pass and complete))
        raw_values.append(raw if finite else np.nan)
        finite_values.append(bool(finite)); quality_values.append(bool(source_only))
    daily["engine_original_nav"] = daily.nav
    daily["research_raw_snapshot_value"] = raw_values
    daily["raw_endpoints_finite"] = finite_values
    daily["quality_source_only_or_clear"] = quality_values
    daily["mechanism_accounting_consistent"] = qualified
    daily["mechanism_account_value"] = daily.research_raw_snapshot_value.where(daily.mechanism_accounting_consistent)
    # The raw engine trace remains available; strict certification never survives this new wrapper.
    daily["certified_nav"] = np.nan
    qualification = {}
    for path, frame in daily.groupby("path_id", sort=False):
        exception_count = (int(replay.accounting_exceptions.path_id.eq(path).sum())
                           if not replay.accounting_exceptions.empty else 0)
        valid = bool(frame.mechanism_accounting_consistent.all() and exception_count == 0)
        qualification[path] = dict(mechanism_accounting_consistent=valid,
            raw_endpoints_finite=bool(frame.raw_endpoints_finite.all()),
            quality_source_only_or_clear=bool(frame.quality_source_only_or_clear.all()),
            unresolved_economic_exception_count=exception_count, execution_audit_pass=audit_pass,
            selection_input_complete=not selection_gaps[path], actual_execution_inputs_complete=not execution_gaps[path],
            selection_input_gaps=selection_gaps[path], actual_execution_input_gaps=execution_gaps[path],
            strict_PIT_promotion_eligible=False, certified_NAV=False, quote_qualified=False,
            status="MECHANISM_ACCOUNT_CONSISTENT_UNCERTIFIED" if valid else "BLOCKED_MECHANISM_ACCOUNT_QUALIFICATION")
    replay.daily = daily
    for name in ("daily", "positions", "orders", "fills", "execution_results", "contexts", "operational_actions", "entitlements"):
        frame = getattr(replay, name, None)
        if frame is None: continue
        frame["research_id"] = freeze.research_id
        frame["mechanism_run_id"] = freeze.run_id
        frame["strict_PIT_promotion_eligible"] = False
        frame["certified_NAV"] = False
        frame["quote_qualified"] = False
        frame["valuation_contract"] = VALUATION
    replay.metadata.update(research_id=freeze.research_id, parent_research_id=freeze.parent_research_id,
        mechanism_run_id=freeze.run_id, research_kind=freeze.research_kind, valuation_contract=VALUATION,
        strict_PIT_promotion_eligible=False, certified_NAV=False, quote_qualified=False,
        source_authority="UNKNOWN", historical_availability="UNKNOWN", historical_revision="UNKNOWN",
        source_identity_assumption=freeze.identity_assumption, quality_flags_preserved=True,
        synthetic=freeze.synthetic, mechanism_freeze_sha256=freeze.digest(),
        original_engine_prefix_identity=dict(replay.prefix_identity),
        original_engine_prefix_scope="original common trace; excludes new snapshot valuation columns",
        original_engine_nav_and_stale_preserved=True,
        policy_context_valuation="UNCHANGED_COMMON_ENGINE_INDICATIVE_MARKS; not the new snapshot value",
        snapshot_valuation="current frozen raw Close * current raw fractional shares + cash + source-backed receivables",
        snapshot_previous_mark_substitution=False, controls=list(CONTROLS), mechanism_account_qualification=qualification)
    return qualification


def run_frozen_history_controls(market, raw_scores, *, event_inputs, uncertified_quality_only,
                                freeze: FrozenHistoryAccountFreeze, expected_freeze_sha256: str):
    """Execute exactly two newly identified controls using one shared input set.

    No registered freeze is created here. expected_freeze_sha256 pins the caller's
    registered and published mechanism specification. Synthetic component success
    cannot establish real source authority or activate a scientific identity.
    """
    events = dict(event_inputs)
    quality_only = np.asarray(uncertified_quality_only, bool)
    scores = _freeze_guard(freeze, expected_freeze_sha256, market, raw_scores, events, quality_only)
    before = input_digests(market, raw_scores, events, quality_only)
    path_ids = freeze.path_ids
    mu = np.repeat(scores[:, None, :], 2, axis=1)
    uncertainty = np.where(np.isfinite(mu), 0., np.nan)
    policy = JointResearchPolicy(path_ids, mu, uncertainty, {},
        roles={path_ids[0]: dict(kind="raw"), path_ids[1]: dict(kind="simple")}, parameters=PARAMETERS)
    friction = dict(kind="FIXED_ADVERSE_OPEN_SLIPPAGE", one_way_bps=10, fee_bps=0,
        benchmark="NEXT_RAW_OPEN", authority="HYPOTHETICAL_RESEARCH_SCENARIO",
        scenario_id=freeze.research_id+"::10bps")
    selection_gaps = {path: [] for path in path_ids}
    def checked_policy(day, ctx):
        needed = np.asarray(ctx.decision_mask, bool) & (np.asarray(ctx.buy_allowed, bool) | (ctx.current_units > 1e-10))
        missing = needed & ~np.isfinite(mu[day])
        for r, c in zip(*np.nonzero(missing)):
            selection_gaps[path_ids[r]].append(dict(date=str(ctx.signal_date), ticker=str(ctx.tickers[c]),
                reason="MISSING_ACTUAL_ELIGIBLE_FROZEN_SCORE"))
        return policy(day, ctx)
    replay = common.run_continuous_account(market, path_ids, checked_policy, dict(ACCOUNT),
        execution_friction=friction, **events)
    if before != input_digests(market, raw_scores, events, quality_only):
        raise FrozenHistoryAccountBlocked("SHARED_FROZEN_INPUT_MUTATION")
    qualification = _qualify(replay, market, quality_only, freeze, selection_gaps)
    return FrozenHistoryMechanismResult(replay, qualification, expected_freeze_sha256)
