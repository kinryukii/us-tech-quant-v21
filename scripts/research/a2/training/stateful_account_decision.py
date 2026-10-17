"""R9 pre-target state and single-intervention consumers of the unique account.

No data readers, fits, source discovery, account mathematics or execution loop.
The existing continuous-account function/code and its lifecycle return value own
all fills, cash, receivables, split coordinates and terminal transitions.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, is_dataclass
import hashlib
import json
from pathlib import Path
from types import FunctionType

import numpy as np
import pandas as pd

from scripts.research.a2.evaluation import continuous_research_account as account_owner
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision
from scripts.research.a2.training.stateful_inputs import FEATURES
from scripts.research.a2.training.stateful_decision import _valid_sid
from scripts.v22.corporate_action_transition_r1 import RAW_OLD_SHARE_COORDINATE

CORE_SOURCE_SHA = "b9bd90d88b0c678698092341483c3129931e007dfe892b25a61fd26eaf0c4d35"
RAW_FIELDS = ("raw_rank", "raw_score", "raw_rank_change_1session", "raw_score_change_1session",
              "raw_rank_change_5sessions", "raw_score_change_5sessions")
ACTION_MAP = {"NO_ACTUAL_FILL": "NO_ACTUAL_FILL", "BUY": "BUY", "INCREASE": "ADD",
              "EXIT": "SELL", "REDUCE": "REDUCE"}
GROSS_GRID = (0., .25, .5, .75, 1.)


class BlockedState(ValueError):
    """Missing, future, inconsistent or unqualified required reference state."""


class PrefixMismatch(ValueError):
    """An intervention cannot claim a different reference prefix."""


def _fail(reason):
    raise BlockedState("BLOCKED_STATE:" + reason)


def _time(value, name, *, asof=None):
    try:
        stamp = pd.Timestamp(value)
    except (ValueError, TypeError):
        _fail(name)
    if pd.isna(stamp) or stamp >= pd.Timestamp("2026-01-01", tz=stamp.tz):
        _fail(name + "_MISSING_OR_LOCKED")
    if asof is not None:
        if stamp.tzinfo != asof.tzinfo or stamp > asof:
            _fail(name + "_FUTURE_OR_CLOCK")
    return stamp


def _number(value, name, *, nonnegative=False):
    if isinstance(value, (bool, np.bool_)):
        _fail(name + "_BOOLEAN")
    try:
        number = float(value)
    except (TypeError, ValueError):
        _fail(name + "_UNKNOWN")
    if not np.isfinite(number) or (nonnegative and number < 0):
        _fail(name + "_NONFINITE_OR_NEGATIVE")
    return number


def _sha(value, name):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        _fail(name + "_SHA_REQUIRED")
    return value


def _exact(value):
    """Canonical float bits, not rounded account_prefix_identity CSV."""
    if is_dataclass(value):
        return _exact(asdict(value))
    if isinstance(value, dict):
        return {str(k): _exact(v) for k, v in sorted(value.items())}
    if isinstance(value, (tuple, list, np.ndarray)):
        return [_exact(v) for v in value]
    if isinstance(value, (float, np.floating)):
        if not np.isfinite(value):
            _fail("EXACT_NONFINITE")
        return {"float64_hex": float(value).hex()}
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        if pd.isna(value):
            _fail("EXACT_UNKNOWN_TIME")
        return pd.Timestamp(value).isoformat()
    if value is None or isinstance(value, str):
        return value
    _fail("EXACT_UNSUPPORTED_TYPE")


def _digest(value):
    encoded = json.dumps(_exact(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def exact_prefix_identity(snapshot):
    """Identity of the supplemental actual account/source prefix, path normalized."""
    return {"sha256": _digest(snapshot["prefix_payload"]),
            "precision": "EXACT_FLOAT64_HEX_NO_ROUND",
            "reference_path_id": snapshot["reference_path_id"],
            "signal_asof": snapshot["signal_asof"]}


def verify_reference_prefix(snapshot, expected):
    if not isinstance(expected, dict) or expected != exact_prefix_identity(snapshot):
        raise PrefixMismatch("REFERENCE_PREFIX_EXACT_IDENTITY_MISMATCH")
    return True


class ReferenceStateExporter:
    """Observe actual ledger/lifecycle output; project state before TargetDecision.

    signal_inputs_provider(j, ctx) returns signal-only bound inputs:
      available_at; signal_close/quote_qualified/quote_available_at/quote_source_sha
      quantity_factors/quantity_available_at; raw_buy_pool/terminal_closed/terminal_available_at
      feature_available_at/raw_available_at/pit32; six RAW_FIELDS arrays
      signal_transition_cost_usd[path].
    Every stock-array has universe width; pit32 is [universe, 32].
    Unknown required entries fail closed. Source authority is owned by the caller.
    """
    def __init__(self, security_tickers, source_account_identity, signal_inputs_provider,
                 *, reference_path_by_path):
        self.security_tickers = dict(security_tickers)
        if (not self.security_tickers or len(set(self.security_tickers.values())) != len(self.security_tickers)
                or any(not isinstance(k, str) or not _valid_sid(k)
                       or k.strip() == str(v).strip()
                       or k.strip().upper().startswith("A2_TICKER_")
                       for k, v in self.security_tickers.items())):
            _fail("SID_TICKER_BINDING")
        self.sid_by_ticker = {ticker: sid for sid, ticker in self.security_tickers.items()}
        self.source_account_identity = deepcopy(source_account_identity)
        for key in ("reference_run_id", "source_account_id", "reference_policy_sha256",
                    "q_contract_sha256", "friction_contract_sha256", "security_binding_sha256"):
            if key not in self.source_account_identity:
                _fail("SOURCE_IDENTITY_" + key)
        for key, value in self.source_account_identity.items():
            if key.endswith("sha256"):
                _sha(value, key)
        if any(not isinstance(self.source_account_identity[k], str) or not self.source_account_identity[k]
               for k in ("reference_run_id", "source_account_id")):
            _fail("SOURCE_ACCOUNT_ID_REQUIRED")
        self.provider = signal_inputs_provider
        self.reference_path_by_path = dict(reference_path_by_path)
        self.paths = None
        self.lifecycle = {}
        self.fills = {}
        self.daily = {}
        self.snapshots = {}
        self.observation_receipt = None

    def attach_paths(self, paths):
        ids = tuple(map(str, paths))
        if (not ids or len(set(ids)) != len(ids) or set(ids) != set(self.reference_path_by_path)
                or any(not isinstance(v, str) or not v for v in self.reference_path_by_path.values())):
            _fail("REFERENCE_PATH_NORMALIZATION_BINDING")
        if self.paths is not None:
            _fail("EXPORTER_ALREADY_ATTACHED_USE_DISTINCT_RUN_OBSERVER")
        self.paths = ids
        self.fills = {p: [] for p in ids}

    def observe_lifecycle(self, date, row_index, applied):
        if self.paths is None or not 0 <= row_index < len(self.paths):
            _fail("LIFECYCLE_PATH_SEQUENCE")
        # No transition is recomputed. Only the original owner's returned state.
        self.lifecycle[self.paths[row_index]] = {
            "session": pd.Timestamp(date), "state": deepcopy(applied.state),
            "positions": deepcopy(applied.positions), "cash": float(applied.cash),
            "receivable_value_usd": float(applied.receivable_value_usd),
            "accounting_qualified": applied.accounting_qualified is True}

    def ledger_callback(self, name, frame):
        if self.paths is None:
            _fail("LEDGER_BEFORE_PATH_ATTACHMENT")
        if name not in ("fills", "daily"):
            return
        for row in frame.to_dict("records"):
            path = str(row["path_id"])
            if path not in self.fills:
                _fail("UNBOUND_LEDGER_PATH")
            if name == "fills":
                # Generated branch order/decision IDs and physical path are not
                # economic prefix fields. Raw actual execution values are retained.
                fields = ("signal_date", "execution_date", "ticker", "side", "action", "price",
                          "notional", "index_units", "index_units_before", "index_units_after",
                          "transaction_cost", "quantity_coordinate_factor", "actual_fill_price",
                          "actual_fill_notional", "raw_Open", "fractional_shares")
                receipt = {k: row[k] for k in fields if k in row}
                if receipt["action"] not in ACTION_MAP:
                    _fail("UNKNOWN_ACTUAL_FILL_ACTION")
                self.fills[path].append(receipt)
            else:
                self.daily[path] = deepcopy(row)

    def capture(self, j, ctx):
        if self.paths != tuple(ctx.path_ids):
            _fail("CONTEXT_PATHS_MISMATCH")
        asof = _time(ctx.signal_asof, "SIGNAL_ASOF")
        date = _time(ctx.signal_date, "SIGNAL_DATE")
        if asof.date() != date.date() or int(ctx.signal_index) != j:
            _fail("CONTEXT_SIGNAL_CLOCK")
        data = deepcopy(self.provider(j, ctx))
        _time(data.get("available_at"), "SIGNAL_INPUT", asof=asof)
        n = len(ctx.tickers)
        vectors = ("signal_close", "quote_qualified", "quote_available_at", "quote_source_sha",
                   "quantity_factors", "quantity_available_at", "raw_buy_pool", "terminal_closed", "terminal_available_at",
                   "feature_available_at", "raw_available_at") + RAW_FIELDS
        for key in vectors:
            if key not in data or np.asarray(data[key]).shape != (n,):
                _fail("SIGNAL_VECTOR_" + key)
        if np.asarray(data.get("pit32")).shape != (n, 32):
            _fail("PIT32_SHAPE")
        costs = data.get("signal_transition_cost_usd")
        if not isinstance(costs, dict):
            _fail("SIGNAL_TRANSITION_COST_UNKNOWN")
        output = []
        for p, path in enumerate(self.paths):
            life, day = self.lifecycle.get(path), self.daily.get(path)
            if life is None or day is None or pd.Timestamp(life["session"]) != date or pd.Timestamp(day["date"]) != date:
                _fail("ACTUAL_COMPLETED_LIFECYCLE_DAILY_REQUIRED")
            if (life["accounting_qualified"] is not True
                    or day.get("accounting_qualified") is not True
                    or not np.isfinite(day.get("certified_nav", np.nan))):
                _fail("ACCOUNT_UNQUALIFIED")
            if ctx.receivable_value_usd is None:
                _fail("RECEIVABLE_UNKNOWN_NOT_ZERO")
            cash = _number(ctx.cash[p], "CASH", nonnegative=True)
            receivable = _number(ctx.receivable_value_usd[p], "RECEIVABLE", nonnegative=True)
            nav = _number(ctx.nav[p], "NAV", nonnegative=True)
            if nav <= 0 or cash != float(day["cash"]) or nav != float(day["nav"]) or receivable != life["receivable_value_usd"]:
                _fail("CONTEXT_LEDGER_CASH_NAV_RECEIVABLE_MISMATCH")
            held = np.asarray(ctx.current_units[p]) > 1e-10
            weights = np.asarray(ctx.current_weights[p], float)
            units = np.asarray(ctx.current_units[p], float)
            if not np.isfinite(weights).all() or not np.isfinite(units).all() or (units < 0).any():
                _fail("CONTEXT_WEIGHTS_QUANTITY")
            stocks, securities = [], []
            for t, ticker in enumerate(map(str, ctx.tickers)):
                sid = self.sid_by_ticker.get(ticker)
                if not sid:
                    _fail("CONTEXT_SID_MISSING")
                _time(data["quantity_available_at"][t], "QUANTITY_COORDINATE", asof=asof)
                _time(data["terminal_available_at"][t], "TERMINAL_STATE", asof=asof)
                factor = _number(data["quantity_factors"][t], "QUANTITY_FACTOR", nonnegative=True)
                if factor <= 0:
                    _fail("QUANTITY_FACTOR_ZERO")
                common_units = float(ctx.common.current_units[p, t])
                if held[t] and not np.isclose(units[t], common_units * factor, rtol=1e-12, atol=1e-10):
                    _fail("RAW_SHARE_COORDINATE_MISMATCH")
                securities.append({"sid": sid, "ticker": ticker, "quantity_factor": factor,
                                   "raw_fractional_shares": float(units[t]),
                                   "engine_units": common_units, "actual_weight": float(weights[t]),
                                   "terminal_closed": bool(data["terminal_closed"][t]),
                                   "quantity_available_at": pd.Timestamp(data["quantity_available_at"][t]).isoformat(),
                                   "terminal_available_at": pd.Timestamp(data["terminal_available_at"][t]).isoformat()})
                for bit in ("raw_buy_pool", "terminal_closed"):
                    if not isinstance(data[bit][t], (bool, np.bool_)):
                        _fail("SIGNAL_LITERAL_BOOLEAN_" + bit)
                if not (held[t] or data["raw_buy_pool"][t]):
                    continue
                if data["terminal_closed"][t] and not held[t]:
                    stocks.append({"sid": sid, "ticker": ticker, "is_held": False,
                        "buy_eligible": False, "sell_eligible": False, "decision_eligible": False,
                        "raw_buy_pool": bool(data["raw_buy_pool"][t]), "terminal_closed": True,
                        "holding_age_sessions": -1, "raw_fractional_shares": 0., "actual_weight": 0.,
                        "first_fill_reference_price": None, "entry_execution_open": None,
                        "first_fill_state": "TERMINAL_NOT_APPLICABLE", "mark_vs_first_fill": None,
                        "prior_actual_action": "NO_ACTUAL_FILL", "sessions_since_prior_fill": None,
                        "pit32": None, **{key: None for key in RAW_FIELDS}})
                    continue
                _time(data["quote_available_at"][t], "QUOTE", asof=asof)
                _time(data["feature_available_at"][t], "FEATURE", asof=asof)
                _time(data["raw_available_at"][t], "RAW", asof=asof)
                _sha(data["quote_source_sha"][t], "QUOTE_SOURCE")
                if data["quote_qualified"][t] is not True and not (
                        isinstance(data["quote_qualified"][t], np.bool_) and bool(data["quote_qualified"][t])):
                    _fail("QUOTE_UNQUALIFIED")
                mark = _number(data["signal_close"][t], "SIGNAL_MARK", nonnegative=True)
                if mark <= 0:
                    _fail("SIGNAL_MARK_ZERO")
                pit = [_number(v, "PIT32_UNKNOWN") for v in data["pit32"][t]]
                raw = {key: _number(data[key][t], key) for key in RAW_FIELDS}
                age = int(ctx.holding_age[p, t])
                first, original = None, None
                if held[t]:
                    first = _number(ctx.entry_price[p, t], "HELD_FIRST_FILL_REFERENCE_PRICE", nonnegative=True)
                    original = _number(ctx.entry_execution_open[p, t], "HELD_FIRST_FILL_OPEN", nonnegative=True)
                    if first <= 0 or original <= 0 or age < 0 or pd.isna(ctx.entry_date[p, t]):
                        _fail("HELD_FIRST_FILL_UNKNOWN")
                elif age != -1:
                    _fail("UNHELD_AGE_NOT_STRUCTURAL_MINUS_ONE")
                history = self.fills[path]
                recent = next((f for f in reversed(history) if f["ticker"] == ticker), None)
                if held[t] and recent is None:
                    _fail("HELD_PRIOR_ACTUAL_FILL_UNKNOWN")
                prior = "NO_ACTUAL_FILL" if recent is None else ACTION_MAP[recent["action"]]
                fill_at = None if recent is None else pd.Timestamp(recent["execution_date"])
                if fill_at is not None and fill_at > date:
                    _fail("FUTURE_ACTUAL_FILL")
                # j is the actual session coordinate, so fill age remains session based.
                since = None if recent is None else sum(
                    1 for d in self._seen_sessions(path) if fill_at < d <= date)
                eligible = bool(ctx.decision_mask[p, t])
                closed = bool(data["terminal_closed"][t])
                if held[t] and not np.isclose(units[t] * mark / nav, weights[t], rtol=1e-12, atol=1e-10):
                    _fail("SOURCE_MARK_CONTEXT_WEIGHT_MISMATCH")
                stocks.append({"sid": sid, "ticker": ticker,
                    "quote_source_sha256": data["quote_source_sha"][t],
                    "quote_available_at": pd.Timestamp(data["quote_available_at"][t]).isoformat(),
                    "raw_available_at": pd.Timestamp(data["raw_available_at"][t]).isoformat(),
                    "feature_available_at": pd.Timestamp(data["feature_available_at"][t]).isoformat(),
                    "is_held": bool(held[t]),
                    "buy_eligible": bool(ctx.buy_allowed[p, t]) and eligible and not closed,
                    "sell_eligible": bool(held[t]) and eligible and not bool(ctx.sell_restricted[p, t]) and not closed,
                    "decision_eligible": eligible and not closed,
                    "raw_buy_pool": bool(data["raw_buy_pool"][t]), "terminal_closed": closed,
                    "holding_age_sessions": age, "raw_fractional_shares": float(units[t]),
                    "actual_weight": float(weights[t]), "first_fill_reference_price": first,
                    "entry_execution_open": original, "first_fill_state": "KNOWN" if held[t] else "NOT_APPLICABLE",
                    "mark_vs_first_fill": mark / first if held[t] else None,
                    "prior_actual_action": prior, "sessions_since_prior_fill": since,
                    "pit32": pit, **raw})
            assets = sum(float(units[t]) * float(data["signal_close"][t])
                         for t in range(n) if held[t])
            if not np.isclose(cash + receivable + assets, nav, rtol=1e-12, atol=1e-8):
                _fail("SOURCE_MARK_CASH_RECEIVABLE_NAV_IDENTITY")
            account = {"cash_usd": cash, "spendable_cash_usd": cash,
                "spendable_cash_weight": cash / nav, "receivable_value_usd": receivable,
                "receivable_nav_weight": receivable / nav, "nav_usd": nav, "nav_over_initial_3000": nav / 3000.,
                "gross": float(weights.sum()), "actual_name_count": int(held.sum()),
                "available_slots": int(ctx.available_slots[p]), "available_budget": _number(ctx.available_budget[p], "BUDGET", nonnegative=True),
                "reserved_weight": _number(ctx.reserved_weight[p], "RESERVED_WEIGHT", nonnegative=True),
                "prior_completed_session_turnover": _number(day["turnover"], "TURNOVER", nonnegative=True),
                "signal_transition_cost_usd": _number(costs.get(path), "TRANSITION_COST", nonnegative=True)}
            prefix = {"reference_path_id": self.reference_path_by_path[path], "signal_index": j,
                "signal_date": date.isoformat(), "signal_asof": asof.isoformat(),
                "source_account_identity": deepcopy(self.source_account_identity),
                "quantity_coordinate": RAW_OLD_SHARE_COORDINATE, "securities": securities,
                "decision_state_stocks": deepcopy(stocks),
                "account": account, "corporate_action_state": deepcopy(life["state"]),
                "actual_fill_prefix": deepcopy(self.fills[path]),
                "prior_completed_daily_prefix": deepcopy(self._daily_history[path])}
            snapshot = {"signal_index": j, "signal_date": date.isoformat(), "signal_asof": asof.isoformat(),
                "path_id": path, "reference_path_id": self.reference_path_by_path[path],
                "source_account_identity": deepcopy(self.source_account_identity),
                "quantity_coordinate": RAW_OLD_SHARE_COORDINATE,
                "stocks": stocks, "account": account, "prefix_payload": prefix}
            snapshot["prefix_identity"] = exact_prefix_identity(snapshot)
            key = (j, path)
            if key in self.snapshots and self.snapshots[key]["prefix_identity"] != snapshot["prefix_identity"]:
                _fail("REPEATED_SNAPSHOT_STATE_CHANGED")
            self.snapshots[key] = deepcopy(snapshot)
            output.append(snapshot)
        return output

    def _seen_sessions(self, path):
        return [pd.Timestamp(row["date"]) for row in self._daily_history[path]]

    @property
    def _daily_history(self):
        return self.__dict__.setdefault("_history", {p: [] for p in self.paths or ()})

    def observed_ledger_callback(self, name, frame):
        self.ledger_callback(name, frame)
        if name == "daily":
            for row in frame.to_dict("records"):
                # Preserve all past completed economic state; strip physical path/IDs.
                fields = ("date", "cash", "nav", "certified_nav", "gross_exposure", "turnover",
                          "transaction_cost_amount", "buy_notional", "sell_notional",
                          "accounting_qualified", "receivable_value_usd", "actual_cash_flow_identity_error")
                self._daily_history[str(row["path_id"])].append({k: row[k] for k in fields if k in row})


def run_observed_continuous_account(market, path_ids, policy, account_config, *,
                                    exporter, ledger_callback=None, **kwargs):
    """Call the original owner's code with one private, read-only observer anchor.

    The original module/global callable is never monkeypatched. The observer
    returns the identical EntitlementApplication object and performs no CA math.
    """
    original = account_owner.run_continuous_account
    physical_sha = hashlib.sha256(Path(account_owner.__file__).read_bytes()).hexdigest()
    if physical_sha != CORE_SOURCE_SHA:
        _fail("PROTECTED_ACCOUNT_SOURCE_CHANGED")
    if kwargs.get("entitlement_enabled") is not True:
        _fail("BOUND_ENTITLEMENT_LIFECYCLE_REQUIRED_NOT_IMPLICIT_ZERO")
    cash_securities = kwargs.get("entitlement_security_tickers")
    if not isinstance(cash_securities, dict) or any(
            exporter.security_tickers.get(sid) != ticker
            for sid, ticker in cash_securities.items()):
        _fail("OBSERVER_SECURITY_BINDING_MISMATCH")
    # Cash catalogue scope may be a legal subset; the original owner still
    # verifies its exact catalogue/binding. No SID or authority is invented.
    if market.dates[-1] >= pd.Timestamp("2026-01-01"):
        _fail("R9_ENGINE_PRE2026_ONLY")
    exporter.attach_paths(path_ids)
    lifecycle = original.__globals__["apply_entitlement_lifecycle"]
    sequence = {"date": None, "index": 0}
    def observed(*args, **call_kwargs):
        result = lifecycle(*args, **call_kwargs)
        date = pd.Timestamp(call_kwargs["execution_date"])
        if sequence["date"] != date:
            sequence.update(date=date, index=0)
        index = sequence["index"]
        exporter.observe_lifecycle(date, index, result)
        sequence["index"] += 1
        return result
    namespace = dict(original.__globals__)
    namespace["apply_entitlement_lifecycle"] = observed
    function = FunctionType(original.__code__, namespace, original.__name__, original.__defaults__, original.__closure__)
    function.__kwdefaults__ = dict(original.__kwdefaults__ or {})
    def ledger(name, frame):
        exporter.observed_ledger_callback(name, frame)
        if ledger_callback is not None:
            ledger_callback(name, frame)
    exporter.observation_receipt = {"original_source_sha256": physical_sha,
        "same_original_code_object": function.__code__ is original.__code__,
        "private_globals_copy": function.__globals__ is not original.__globals__,
        "observer_anchor": "apply_entitlement_lifecycle_RETURN_ONLY",
        "global_original_lifecycle_unchanged": original.__globals__["apply_entitlement_lifecycle"] is lifecycle,
        "lifecycle_return_identity_unchanged": True, "new_engine": False}
    return function(market, path_ids, policy, account_config, ledger_callback=ledger, **kwargs)


def _decision(reference, ctx):
    if not isinstance(reference, TargetDecision):
        _fail("REFERENCE_TargetDecision_REQUIRED")
    weights = np.asarray(reference.weights, float).copy()
    explicit = ctx.decision_mask.copy() if reference.explicit_mask is None else np.asarray(reference.explicit_mask).copy()
    if weights.shape != ctx.current_weights.shape or explicit.shape != weights.shape:
        _fail("REFERENCE_TARGET_SHAPE")
    return weights, explicit.astype(bool)


def _planner_binding(intervention, snapshot):
    intent = intervention.get("planner_intent")
    if not isinstance(intent, dict):
        _fail("FROZEN_PLANNER_INTENT_REQUIRED")
    source = snapshot["source_account_identity"]
    for key in ("q_contract_sha256", "friction_contract_sha256"):
        if intent.get(key) != source[key]:
            _fail("PLANNER_" + key + "_MISMATCH")
    if intent.get("prefix_sha256") != snapshot["prefix_identity"]["sha256"]:
        _fail("PLANNER_PREFIX_MISMATCH")
    _time(intent.get("available_at"), "PLANNER_INTENT", asof=pd.Timestamp(snapshot["signal_asof"]))
    return intent


def single_action_override(reference, ctx, snapshot, intervention):
    """One TargetDecision edit; no funds transfer, fills, prices or later policies."""
    weights, explicit = _decision(reference, ctx)
    path = intervention["path_id"]
    if path != snapshot["path_id"]:
        _fail("INTERVENTION_PATH")
    p = tuple(ctx.path_ids).index(path)
    action = intervention.get("action")
    if action not in ("BUY", "SKIP", "HOLD", "SELL", "REPLACE", "GROSS", "REFERENCE_GROSS"):
        _fail("UNKNOWN_ACTION")
    intent = _planner_binding(intervention, snapshot)
    if action == "REFERENCE_GROSS":
        return TargetDecision(weights, explicit, reference.raw_evidence_id)
    index = {str(t): i for i, t in enumerate(ctx.tickers)}
    lookup = {row["sid"]: row for row in snapshot["stocks"]}
    def stock(key, held, eligibility):
        sid = intervention.get(key)
        row = lookup.get(sid)
        if row is None or row["is_held"] != held or (eligibility is not None and not row[eligibility]) or row["terminal_closed"]:
            _fail("ACTION_SECURITY_NOT_SIGNAL_LEGAL_" + key)
        if not held and not row["raw_buy_pool"]:
            _fail("ENTRANT_NOT_FROZEN_RAW_POOL")
        return index[row["ticker"]]
    if action in ("BUY", "SKIP", "REPLACE"):
        entrant = stock("entrant_sid", False, "buy_eligible")
    if action in ("HOLD", "SELL", "REPLACE"):
        incumbent = stock("incumbent_sid", True, "sell_eligible" if action != "HOLD" else None)
    if action == "BUY" or action == "REPLACE":
        weight = _number(intent.get("target_weight"), "PLANNER_TARGET_WEIGHT", nonnegative=True)
        if weight <= 0 or weight > ctx.max_weight:
            _fail("PLANNER_TARGET_WEIGHT_CONSTRAINT")
        weights[p, entrant], explicit[p, entrant] = weight, True
    if action == "SKIP":
        weights[p, entrant], explicit[p, entrant] = 0., False
    if action == "HOLD":
        weights[p, incumbent], explicit[p, incumbent] = 0., False
    if action == "SELL" or action == "REPLACE":
        weights[p, incumbent], explicit[p, incumbent] = 0., True
    if action == "GROSS":
        gross = _number(intervention.get("gross"), "GROSS_GRID")
        if gross not in GROSS_GRID or intent.get("gross") != gross:
            _fail("GROSS_FIXED_GRID_BINDING")
        target = np.asarray(intent.get("weights"), float)
        mask = np.asarray(intent.get("explicit_mask"))
        if target.shape != (len(ctx.tickers),) or mask.shape != target.shape or mask.dtype != np.dtype(bool):
            _fail("GROSS_PLANNER_VECTOR")
        if not np.isfinite(target[mask]).all() or (target[mask] < 0).any() or (target[mask] > ctx.max_weight).any():
            _fail("GROSS_PLANNER_VECTOR_CONSTRAINT")
        if (mask & ~ctx.decision_mask[p]).any():
            _fail("GROSS_PLANNER_ILLEGAL_MASK")
        closed = {index[row["ticker"]] for row in snapshot["stocks"] if row["terminal_closed"]}
        if any(mask[t] or target[t] > 0 for t in closed):
            _fail("GROSS_TERMINAL_REBUY")
        weights[p], explicit[p] = target, mask
    return TargetDecision(weights, explicit, reference.raw_evidence_id)


class SingleActionOverride:
    """Policy consumer which validates one exact prefix then restores reference."""
    def __init__(self, reference_policy, exporter, intervention, expected_prefix):
        self.reference_policy = reference_policy
        self.exporter = exporter
        self.intervention = deepcopy(intervention)
        self.expected_prefix = deepcopy(expected_prefix)
        self.applied_count = 0

    def __call__(self, j, ctx):
        snapshots = self.exporter.capture(j, ctx)
        reference = self.reference_policy(j, ctx)
        if j != self.intervention["signal_index"]:
            return reference
        if self.applied_count:
            _fail("SINGLE_INTERVENTION_ALREADY_USED")
        snapshot = next((s for s in snapshots if s["path_id"] == self.intervention["path_id"]), None)
        if snapshot is None:
            _fail("INTERVENTION_PATH_NOT_BOUND")
        verify_reference_prefix(snapshot, self.expected_prefix)
        result = single_action_override(reference, ctx, snapshot, self.intervention)
        self.applied_count += 1
        return result
