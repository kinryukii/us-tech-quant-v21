"""Task-scoped cash/fee projection of the single retained execution owner.

The frozen engine and corporate-action owner remain unchanged.  This adapter
adds a fee function, settlement receivables and minimum ordinary trade amounts
through source-pinned AST edits; it does not implement another order engine.
All-in bps include spread/slippage/fees once, plus an optional fixed stress fee.
"""
from __future__ import annotations

import ast
import copy
from dataclasses import asdict, dataclass
import hashlib
import types
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.research.a2.evaluation import continuous_research_account as ca_owner
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2 import fast_account as engine

ENGINE_SHA = "200462d48816918a5b9fe72f2239a81d01f69a32d57922e8e47cf1ee4c06ee1b"
HOOK_AST_SHA = "bd86562d64959554d503853798eab6942e63189b1eb723cf6a49478ea825bb16"
TOL = engine.TOL


@dataclass(frozen=True)
class FeeConfig:
    one_way_all_in_bps: float = 10.0
    fixed_per_fill_usd: float = 0.0
    minimum_trade_usd: float = 5.0
    settlement_enabled: bool = True

    def __post_init__(self):
        if (self.one_way_all_in_bps not in (5., 10., 25.)
                or self.fixed_per_fill_usd not in (0., .5)
                or isinstance(self.minimum_trade_usd, bool)
                or not np.isfinite(self.minimum_trade_usd)
                or self.minimum_trade_usd < 0
                or type(self.settlement_enabled) is not bool):
            raise ValueError("Invalid task fee/settlement configuration")


def fee_for_notional(notional, config: FeeConfig):
    """Pure one-way all-in proxy, charged exactly once per positive actual fill."""
    value = np.asarray(notional, dtype=float)
    if not np.isfinite(value).all() or (value < 0).any():
        raise ValueError("Fee notional must be finite and nonnegative")
    return value * (config.one_way_all_in_bps / 10000.) + np.where(value > TOL, config.fixed_per_fill_usd, 0.)


def quote_transition_cost(current_weights, target_weights, nav, config: FeeConfig, *, full_exit_mask=None):
    """Signal-known estimate using the same fee function as actual execution."""
    current, target = np.asarray(current_weights, float), np.asarray(target_weights, float)
    if current.shape != target.shape or current.ndim not in (1, 2):
        raise ValueError("Transition weights must have matching vectors/matrices")
    wealth = np.asarray(nav, float)
    if not np.isfinite(wealth).all() or (wealth <= 0).any():
        raise ValueError("Positive signal NAV required")
    if not np.isfinite(current).all() or not np.isfinite(target).all() or (current < 0).any() or (target < 0).any():
        raise ValueError("Finite nonnegative weights required")
    change = (target - current) * (wealth[..., None] if current.ndim == 2 else wealth)
    intent = np.abs(change)
    full_exit = ((current > TOL) & (target <= TOL)) if full_exit_mask is None else np.asarray(full_exit_mask, bool)
    if full_exit.shape != current.shape:
        raise ValueError("Full exit mask must match transition weights")
    ordinary_or_exit = (intent + TOL >= config.minimum_trade_usd) | (full_exit & (change < 0))
    profitable_sale = (change >= 0) | (intent > fee_for_notional(intent, config) + TOL)
    intent = np.where(ordinary_or_exit & profitable_sale, intent, 0.)
    return dict(notional=intent, fees=fee_for_notional(intent, config),
                total_fee=np.sum(fee_for_notional(intent, config), axis=-1),
                role="SIGNAL_FULL_INTENT_ESTIMATE_NOT_ACTUAL_FILL", spread_slippage_added_separately=False)


def validate_calendar(calendar):
    dates = pd.DatetimeIndex(calendar)
    if (dates.tz is not None or len(dates) == 0 or dates.hasnans
            or not dates.is_monotonic_increasing or dates.has_duplicates
            or not dates.equals(dates.normalize()) or (dates.dayofweek >= 5).any()):
        raise ValueError("Explicit ordered US equity session calendar required")
    return dates


def settlement_date(trade_date, calendar, *, trading_calendar=None):
    """Use supplied sessions only; never fabricate a date beyond their coverage."""
    dates = validate_calendar(calendar)
    trade = pd.Timestamp(trade_date)
    legal_trades = dates if trading_calendar is None else validate_calendar(trading_calendar)
    if trade not in legal_trades:
        raise ValueError("Trade date absent from supplied trading calendar")
    lag = 1 if trade >= pd.Timestamp("2024-05-28") else 2
    index = int(dates.searchsorted(trade, side="right")) + lag - 1
    return dates[index] if index < len(dates) else None


@dataclass(frozen=True)
class CashPolicyContext:
    common: object
    settled_cash: np.ndarray
    unsettled_cash: np.ndarray
    fee_config: FeeConfig

    def __getattr__(self, name):
        return getattr(self.common, name)


class _CashRules:
    def __init__(self, config, calendar, path_ids, corporate_action_hook):
        self.config, self.calendar, self.path_ids = config, calendar, tuple(path_ids)
        self.corporate_action_hook = corporate_action_hook
        size = len(path_ids)
        self.unsettled = np.zeros(size)
        self.receivable = np.zeros(size)
        self.corporate_receivable = np.zeros(size)
        self.added_unsettled = np.zeros(size)
        self.expected_fees = np.zeros(size)
        self.settlement_release = np.zeros(size)
        self.pending = []
        self.settlement_ledger = []
        self.daily_extension = []

    def opening(self, di, date, units, cash):
        self.added_unsettled[:] = 0.
        self.expected_fees[:] = 0.
        self.settlement_release[:] = 0.
        waiting = []
        for item in self.pending:
            due, amount, ledger_rows = item
            if due is not None and due <= pd.Timestamp(date):
                cash = cash + amount
                self.unsettled -= amount
                self.settlement_release += amount
                for ledger_row in ledger_rows:
                    ledger_row["status"] = "SETTLED"
                    ledger_row["actual_settlement_session"] = pd.Timestamp(date)
            else:
                waiting.append(item)
        self.pending = waiting
        self.unsettled[np.abs(self.unsettled) < TOL] = 0.
        if self.corporate_action_hook is not None:
            units, cash, receivable = self.corporate_action_hook(di, date, units, cash)
            value = np.asarray(receivable, float)
            if value.shape != self.unsettled.shape or not np.isfinite(value).all() or (value < -TOL).any():
                raise ValueError("Corporate-action owner returned invalid receivables")
            self.corporate_receivable[:] = value
        self.receivable[:] = self.corporate_receivable + self.unsettled
        return units, cash, self.receivable

    def filter_sales(self, amount, full_exit):
        # Explicit full exits may clear small tails; ordinary reductions retain
        # the minimum. Every sale must still yield positive net cash proceeds.
        value = np.where((amount + TOL >= self.config.minimum_trade_usd) | full_exit, amount, 0.)
        return np.where(value > fee_for_notional(value, self.config) + TOL, value, 0.)

    def actual_fees(self, amount):
        fees = fee_for_notional(amount, self.config)
        self.expected_fees += fees.sum(axis=1)
        return fees

    def receive_sales(self, di, cash, amount, fees):
        proceeds = np.sum(amount - fees, axis=1)
        if not self.config.settlement_enabled:
            return cash + proceeds
        due = settlement_date(self.calendar_execution_dates[di], self.calendar, trading_calendar=self.calendar_execution_dates)
        if (proceeds > TOL).any():
            ledger_rows = []
            self.pending.append((due, proceeds.copy(), ledger_rows))
            self.unsettled += proceeds
            self.added_unsettled += proceeds
            self.receivable[:] = self.corporate_receivable + self.unsettled
            for row in np.flatnonzero(proceeds > TOL):
                ledger_row = dict(path_id=self.path_ids[row],
                    execution_date=self.calendar_execution_dates[di], settlement_date=due,
                    net_sale_proceeds=proceeds[row], actual_settlement_session=None,
                    status="PENDING" if due is not None else "CALENDAR_COVERAGE_UNKNOWN")
                ledger_rows.append(ledger_row)
                self.settlement_ledger.append(ledger_row)
        return cash

    def fund_buys(self, requested, cash):
        amount = np.asarray(requested, float).copy()
        active = (amount > TOL) & (amount + TOL >= self.config.minimum_trade_usd)
        amount[~active] = 0.
        ratio = np.ones(len(cash))
        rate = self.config.one_way_all_in_bps / 10000.
        # Only sizing is added. Existing engine owns capacity, name ordering,
        # restrictions, actual quantities and fill construction.
        for _ in range(amount.shape[1] + 1):
            count = active.sum(axis=1)
            principal = amount.sum(axis=1)
            free = np.maximum(cash - count * self.config.fixed_per_fill_usd, 0.)
            ratio = np.minimum(1., np.divide(free, principal * (1. + rate), out=np.ones(len(cash)), where=principal > 0))
            candidate = amount * ratio[:, None]
            next_active = active & (candidate > TOL) & (candidate + TOL >= self.config.minimum_trade_usd)
            if np.array_equal(next_active, active):
                return candidate, ratio
            active = next_active
            amount[~active] = 0.
        raise AssertionError("Fee-aware cash sizing did not converge")


def _project_engine(rules, usable_a=None):
    source = Path(engine.__file__).read_bytes()
    if hashlib.sha256(source).hexdigest() != ENGINE_SHA:
        raise ValueError("Frozen common engine source changed")
    owner_tree = ast.parse(Path(ca_owner.__file__).read_text(encoding="utf-8-sig"))
    owner_hook = next(n for n in owner_tree.body if isinstance(n, ast.FunctionDef) and n.name == "_engine_with_entitlement_hook")
    if hashlib.sha256(ast.dump(owner_hook).encode()).hexdigest() != HOOK_AST_SHA:
        raise ValueError("Corporate-action projection owner changed")
    captured = []
    def capture_compile(tree, *args, **kwargs):
        captured.append(copy.deepcopy(tree))
        return compile(tree, *args, **kwargs)
    # Clone function globals, never monkeypatch the shared module. Execute the
    # existing corporate-action owner's projection and retain its actual AST.
    projector = types.FunctionType(ca_owner._engine_with_entitlement_hook.__code__,
        {**ca_owner._engine_with_entitlement_hook.__globals__, "compile": capture_compile})
    projected, lineage = projector(rules.opening, operational_exit_hook=getattr(rules.corporate_action_hook, "_stock_distribution_operational_mask", None))
    if len(captured) != 1 or not isinstance(captured[0], ast.Module):
        raise ValueError("Expected exactly one owner-projected function")
    tree = captured[0]
    function = tree.body[0]
    if hashlib.sha256(ast.dump(function).encode()).hexdigest() != lineage["projected_function_ast_sha256"]:
        raise ValueError("Captured owner projection identity changed")
    quote_lineage = None
    if usable_a is not None:
        from scripts.research.a2.evaluation import frozen_history_research_quote_domain as quote_owner
        if hashlib.sha256(Path(quote_owner.__file__).read_bytes()).hexdigest() != "eda136406c8de2c9053441943e751c6b16d5a56307ae118b904ac8fb773b55f4":
            raise ValueError("Frozen execution quote projection owner changed")
        function, quote_lineage = quote_owner.project_pending_execution_ast(function, ENGINE_SHA)
        tree.body[0] = function
    execution_mask = "valid_open" if usable_a is None else "execution_valid_open"
    edits = []
    def replace(old, new):
        old_nodes = ast.parse(old).body
        new_nodes = ast.parse(new).body
        matches = []
        for parent in ast.walk(function):
            for field, value in ast.iter_fields(parent):
                if not isinstance(value, list):
                    continue
                for index in range(len(value) - len(old_nodes) + 1):
                    if all(isinstance(value[index+j], ast.AST) and ast.dump(value[index+j]) == ast.dump(old_nodes[j]) for j in range(len(old_nodes))):
                        matches.append((value, index))
        if len(matches) != 1:
            raise ValueError("Cash projection AST anchor changed: " + old)
        sequence, index = matches[0]
        sequence[index:index+len(old_nodes)] = new_nodes
        edits.append(old)
    replace("sell_quantity = np.minimum(units, np.divide(sell_amount, market.open[di][None, :], out=np.zeros_like(units), where=" + execution_mask + "[None, :]))",
            "full_exit = np.isin(pending[\"semantics\"], (\"MODEL_ACTIVE_EXIT\", \"OPERATIONAL_EXIT_REQUIRED\"))\nminimum_sell = (sell_amount > TOL) & (((sell_amount + TOL < _cash_rules.config.minimum_trade_usd) & ~full_exit) | (sell_amount <= fee_for_notional(sell_amount, _cash_rules.config) + TOL))\noutcomes(minimum_sell, pi, di, \"REJECTED\", \"MINIMUM_TRADE_OR_FEE_EXCEEDS_PROCEEDS\", \"SELL\")\nblocked += minimum_sell.sum(axis=1)\nsell_amount = _cash_rules.filter_sales(sell_amount, full_exit)\nsell_quantity = np.minimum(units, np.divide(sell_amount, market.open[di][None, :], out=np.zeros_like(units), where=" + execution_mask + "[None, :]))")
    replace("sell_cost = sell_amount * rate", "sell_cost = _cash_rules.actual_fees(sell_amount)")
    replace("cash += np.sum(sell_amount - sell_cost, axis=1)", "cash = _cash_rules.receive_sales(di, cash, sell_amount, sell_cost)")
    replace("required = amount.sum(axis=1) * (1 + rate)\nbuy_scale = np.minimum(1.0, np.divide(np.maximum(cash, 0.0), required, out=np.ones(s), where=required > 0))\namount *= buy_scale[:, None]",
            "amount, buy_scale = _cash_rules.fund_buys(amount, cash)")
    replace('order = np.lexsort((ticker_keys, -pending["weights"]), axis=1)',
            'minimum_buy = candidate_buy & (amount > TOL) & (amount + TOL < _cash_rules.config.minimum_trade_usd)\noutcomes(minimum_buy, pi, di, "REJECTED", "BELOW_MINIMUM_TRADE", "BUY")\nblocked += minimum_buy.sum(axis=1)\namount = np.where(amount + TOL >= _cash_rules.config.minimum_trade_usd, amount, 0.)\norder = np.lexsort((ticker_keys, -pending["weights"]), axis=1)')
    replace("no_adv = candidate_buy & ~failure & (amount <= TOL)",
            "no_adv = candidate_buy & ~failure & ~minimum_buy & (amount <= TOL)")
    replace("insufficient = candidate_buy & ~failure & ~no_adv & (amount <= TOL)",
            "insufficient = candidate_buy & ~failure & ~no_adv & ~minimum_buy & (amount <= TOL)")
    replace("cost = amount * rate", "cost = _cash_rules.actual_fees(amount)")
    replace("cash_error = cash - cash_before - (sells - buys - fees)", "cash_error = cash - cash_before - (sells - buys - fees) + _cash_rules.added_unsettled")
    replace("cost_error = fees - (sells + buys) * rate", "cost_error = fees - _cash_rules.expected_fees")
    tree = ast.fix_missing_locations(tree)
    namespace = {**projected.__globals__, "_cash_rules": rules, "fee_for_notional": fee_for_notional}
    if usable_a is not None:
        def coordinate_only_proof(units_before, cash_before, units_after, cash_after,
                execution_open, row_present, execution_valid_open, buy_quantity,
                sell_quantity, buy_notional, sell_notional, buy_cost, sell_cost, fees, rate):
            # Normalize only for legacy execution-coordinate identities.
            # Cash owner's audits independently own actual fee/settlement.
            if (not np.allclose(buy_cost, fee_for_notional(buy_notional, rules.config), rtol=0, atol=1e-8)
                    or not np.allclose(sell_cost, fee_for_notional(sell_notional, rules.config), rtol=0, atol=1e-8)
                    or not np.allclose(fees, np.sum(buy_cost + sell_cost, axis=1), rtol=0, atol=1e-8)):
                raise AssertionError("ACTUAL_QUOTE_FILL_FEES_DO_NOT_MATCH_CASH_OWNER")
            proof = quote_owner.execution_coordinate_proof(units_before, cash_before,
                units_after, cash_after + fees + rules.added_unsettled,
                execution_open, row_present, execution_valid_open, buy_quantity,
                sell_quantity, buy_notional, sell_notional, np.zeros_like(buy_cost),
                np.zeros_like(sell_cost), np.zeros_like(fees), 0.)
            proof["actual_fee_verified_by_cash_owner"] = np.asarray(fees).copy()
            proof["net_sale_cash_withheld_by_cash_owner"] = rules.added_unsettled.copy()
            return proof
        namespace[quote_owner.USABLE_GLOBAL] = usable_a
        namespace[quote_owner.PROOF_GLOBAL] = coordinate_only_proof
    exec(compile(tree, engine.__file__, "exec"), namespace)
    lineage.update(adapter_ast_sha256=hashlib.sha256(ast.dump(function).encode()).hexdigest(),
                   cash_fee_ast_anchor_count=len(edits), cash_fee_ast_anchors=edits,
                   original_engine_unchanged=True, owner_hook_ast_sha256=HOOK_AST_SHA,
                    quote_execution_projection=quote_lineage,
                    quote_proof_scope="NORMALIZED_EXECUTION_COORDINATE_QUANTITY_NOTIONAL; ACTUAL_FEES_AND_SETTLEMENT_VERIFIED_BY_CASH_OWNER" if usable_a is not None else None)
    return namespace["run_many"], lineage


def run_cash_account(market, path_ids, policy, *, fee_config=None, settlement_calendar=None,
                     initial_cash=3000., initial_units=None, max_weight=.10,
                     max_positions=20, max_invested=.95, capacity_fraction=.01,
                     corporate_action_hook=None, usable_a=None, collect_ledgers=True, ledger_callback=None):
    """Runner API; policy returns the existing fast_account.TargetDecision.

    Optional corporate_action_hook is the existing qualified owner's callable,
    returning (units, settled_cash, nonspendable corporate receivable). This
    adapter never infers or reconstructs company events. Supplied calendar is
    authoritative session metadata; unknown terminal settlement stays withheld.
    """
    config = fee_config or FeeConfig()
    if not isinstance(config, FeeConfig):
        raise TypeError("fee_config must be FeeConfig")
    path_ids = tuple(str(p) for p in path_ids)
    dates = validate_calendar(market.dates if settlement_calendar is None else settlement_calendar)
    trade_dates = validate_calendar(market.dates)
    if trade_dates[0] < dates[0] or trade_dates[-1] > dates[-1]:
        raise ValueError("Settlement calendar must cover the whole trading date range")
    rules = _CashRules(config, dates, path_ids, corporate_action_hook)
    rules.calendar_execution_dates = pd.DatetimeIndex(market.dates)
    if usable_a is not None:
        usable_a = np.asarray(usable_a)
        if usable_a.dtype.kind != "b" or usable_a.shape != market.open.shape:
            raise ValueError("Exact source-qualified execution A bool mask required")
        usable_a = usable_a.copy()
    projected, lineage = _project_engine(rules, usable_a)
    def account_policy(di, context):
        return policy(di, CashPolicyContext(context, context.cash.copy(), rules.unsettled.copy(), config))
    def decorate_fills(frame):
        frame = frame.copy()
        frame["fixed_stress_fee"] = np.where(frame.notional > TOL, config.fixed_per_fill_usd, 0.)
        frame["all_in_proxy_fee"] = frame.notional * config.one_way_all_in_bps / 10000.
        frame["settlement_date"] = [settlement_date(d, dates, trading_calendar=market.dates) if side == "SELL" and config.settlement_enabled else pd.NaT for d, side in zip(frame.execution_date, frame.side)]
        return frame
    def emit(name, frame):
        if name == "fills":
            frame = decorate_fills(frame)
        if name == "daily":
            frame = frame.copy()
            frame["settled_cash"] = frame.cash
            frame["unsettled_cash"] = rules.unsettled.copy()
            frame["corporate_receivable"] = rules.corporate_receivable.copy()
            frame["settlement_release"] = rules.settlement_release.copy()
            frame["total_cash_assets"] = frame.cash + rules.unsettled + rules.corporate_receivable
            rules.daily_extension.append(frame[["path_id", "date", "settled_cash", "unsettled_cash", "corporate_receivable", "total_cash_assets", "settlement_release"]])
        if ledger_callback is not None:
            ledger_callback(name, frame)
    result = projected(market, path_ids, account_policy, initial_cash=initial_cash,
        initial_units=initial_units, cost_bps=config.one_way_all_in_bps, max_weight=max_weight,
        max_positions=max_positions, max_invested=max_invested, capacity_fraction=capacity_fraction,
        collect_ledgers=collect_ledgers, ledger_callback=emit)
    if not result.daily.empty:
        result.daily = result.daily.merge(pd.concat(rules.daily_extension, ignore_index=True), on=["path_id", "date"], validate="one_to_one")
    if not result.fills.empty:
        result.fills = decorate_fills(result.fills)
    result.settlement_ledger = pd.DataFrame(rules.settlement_ledger)
    result.final_unsettled_cash = rules.unsettled.copy()
    result.metadata.update(consensus_cash_adapter=True, fee_config=asdict(config),
        fee_semantics="ONE_WAY_ALL_IN_PROXY_PLUS_FIXED_STRESS_PER_ACTUAL_FILL; NO_SEPARATE_SPREAD_SLIP_DEBIT",
        settlement_semantics="US_EQUITY_T2_BEFORE_2024_05_28_ELSE_T1; DISTINCT_SUPPLIED_SETTLEMENT_AND_TRADING_CALENDARS",
        available_cash_semantics="SETTLED_ONLY; PENDING_NET_SALE_PROCEEDS_REMAIN_NAV_ASSETS",
        source_lineage=lineage, production_qualified=False)
    return result