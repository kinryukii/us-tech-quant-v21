"""Independent A2 accounts sharing immutable market arrays.

callback(day_dataframe, context) returns {'targets': float[K,N],
'decided': bool[K,N], 'raw': optional per-strategy metadata}. day_dataframe is
reindexed to market.tickers. A false decided bit preserves held units; explicit
zero requests an exit. Missing/uncertified quotes never release signal-time
reserved cash or slots, and a failed next-open sale cannot create a buy slot.

The original holding-aware engine is loaded read-only for its evidence classes
and the conformance tests. No old source, model, prediction or account is edited.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys
import types
from collections.abc import Mapping

import numpy as np
import pandas as pd

REFERENCE_PATH = Path(__file__).resolve().parent.parent / "a2_buy_sell_cash_multimodel_20260928/engine_v2.py"
_reference = types.ModuleType("a2_pto_readonly_reference_engine_v2")
_reference.__file__ = str(REFERENCE_PATH)
sys.modules[_reference.__name__] = _reference
exec(compile(REFERENCE_PATH.read_text(encoding="utf-8"), str(REFERENCE_PATH), "exec"), _reference.__dict__)
HoldingAwareDecision = _reference.HoldingAwareDecision
HoldingAwareContext = _reference.HoldingAwareContext
OperationalExit = _reference.OperationalExit
TOL = _reference.TOL
WEIGHT_TOL = _reference.WEIGHT_TOL
FORWARD_FIELDS = {"y_next_open", "label_end_date", "label_available", "label_price_warning",
                  "next_open", "following_open", "target", "target_end_date", "target_context_available"}


def _positive(values):
    return np.isfinite(values) & (values > 0)


def _json(value):
    def clean(item):
        if isinstance(item, Mapping):
            return {str(k): clean(v) for k, v in item.items()}
        if isinstance(item, (list, tuple, np.ndarray)):
            return [clean(v) for v in item]
        if isinstance(item, np.generic):
            return clean(item.item())
        if isinstance(item, float) and not np.isfinite(item):
            return None
        if isinstance(item, (str, float, int, bool)) or item is None:
            return item
        return str(item)
    return json.dumps(clean(value), ensure_ascii=False, allow_nan=False, sort_keys=True)


class BatchMarket:
    """Prepare quotes/features once; no strategy state or future-price filtering.

    Keyword contracts match the original engine: signal_start/end,
    known_restrictions, operational_exits_by_signal, signal_asof, adv_column.
    extra_tickers supports an initially held security without an input row.
    """
    def __init__(self, prices, calendar, features, *, signal_start=None, signal_end=None,
                 known_restrictions=None, operational_exits_by_signal=None,
                 signal_asof=None, adv_column="avg_dollar_volume_20d", extra_tickers=()):
        self.calendar = _reference.dates(calendar, "calendar")
        if (not len(self.calendar) or self.calendar.has_duplicates
                or not self.calendar.is_monotonic_increasing):
            raise ValueError("calendar must be nonempty, unique and increasing")
        for frame, required, name in [(prices, {"ticker", "trade_date", "open", "close"}, "prices"),
                                      (features, {"ticker", "signal_date"}, "features")]:
            if not required.issubset(frame):
                raise ValueError(f"{name} missing {required - set(frame)}")
            if not frame.ticker.map(lambda x: isinstance(x, str) and bool(x.strip())).all():
                raise ValueError(f"invalid {name} ticker")
        px, fs = prices.copy(), features.copy()
        px["trade_date"] = _reference.dates(px.trade_date, "trade_date")
        fs["signal_date"] = _reference.dates(fs.signal_date, "signal_date")
        if px.duplicated(["trade_date", "ticker"]).any() or fs.duplicated(["signal_date", "ticker"]).any():
            raise ValueError("duplicate price or feature key")
        if not fs.signal_date.isin(self.calendar).all():
            raise ValueError("slice feature signal dates to supplied calendar")
        self.signal_start = pd.Timestamp(signal_start) if signal_start is not None else fs.signal_date.min()
        self.signal_end = pd.Timestamp(signal_end) if signal_end is not None else fs.signal_date.max()
        if pd.isna(self.signal_start) or pd.isna(self.signal_end):
            raise ValueError("empty features require explicit signal_start and signal_end")
        if (self.signal_start > self.signal_end or fs.signal_date.lt(self.signal_start).any()
                or fs.signal_date.gt(self.signal_end).any()):
            raise ValueError("inconsistent signal window")
        op_names = {t for actions in (operational_exits_by_signal or {}).values() for t in actions}
        self.tickers = np.asarray(sorted(set(px.ticker) | set(fs.ticker) | set(extra_tickers) | op_names), dtype=str)
        self.ticker_index = {t: i for i, t in enumerate(self.tickers)}
        self.N, self.T = len(self.tickers), len(self.calendar)
        self.adv_column = adv_column
        self.asofs = {pd.Timestamp(k): pd.Timestamp(v) for k, v in (signal_asof or {}).items()}
        self.ops = {pd.Timestamp(k): v for k, v in (operational_exits_by_signal or {}).items()}
        self.restrictions = {}
        if known_restrictions is not None and len(known_restrictions):
            kr = known_restrictions.copy()
            if not {"signal_date", "ticker", "known_at", "source_id", "reason"}.issubset(kr):
                raise ValueError("known restrictions require dated source evidence")
            kr["signal_date"] = _reference.dates(kr.signal_date, "restriction signal_date")
            self.restrictions = {d: g.to_dict("records") for d, g in kr.groupby("signal_date", sort=False)}
        warning = px.price_quality_warning.fillna(True).astype(bool) if "price_quality_warning" in px else pd.Series(False, index=px.index)
        px["price_quality_warning"] = warning
        for c in ["open", "close"]:
            px[c] = pd.to_numeric(px[c], errors="coerce")
        shape = (self.T, self.N)
        self.opens, self.closes = np.full(shape, np.nan), np.full(shape, np.nan)
        self.open_reason = np.full(shape, "MISSING_PRICE_ROW", dtype="U32")
        self.close_reason = np.full(shape, "MISSING_PRICE_ROW", dtype="U32")
        days = {d: i for i, d in enumerate(self.calendar)}
        oncal = px.loc[px.trade_date.isin(self.calendar)]
        r = oncal.trade_date.map(days).to_numpy(int)
        c = oncal.ticker.map(self.ticker_index).to_numpy(int)
        for field, arr, reason in [("open", self.opens, self.open_reason), ("close", self.closes, self.close_reason)]:
            values = oncal[field].to_numpy(float)
            valid = _positive(values) & ~oncal.price_quality_warning.to_numpy(bool)
            arr[r[valid], c[valid]] = values[valid]
            reasons = np.where(oncal.price_quality_warning, "PRICE_QUALITY_UNCERTIFIED",
                               np.where(_positive(values), "AVAILABLE", "MISSING_OR_INVALID_" + field.upper()))
            reason[r, c] = reasons
        self.initial_marks = np.full(self.N, np.nan)
        self.initial_mark_dates = np.full(self.N, np.datetime64("NaT"), dtype="datetime64[ns]")
        history = px.loc[px.trade_date.lt(self.calendar[0]) & ~px.price_quality_warning & _positive(px.close.to_numpy(float))]
        history = history.sort_values("trade_date").drop_duplicates("ticker", keep="last")
        hcols = history.ticker.map(self.ticker_index).to_numpy(int)
        self.initial_marks[hcols] = history.close.to_numpy(float)
        self.initial_mark_dates[hcols] = history.trade_date.to_numpy("datetime64[ns]")
        fs = fs.drop(columns=list(FORWARD_FIELDS & set(fs)))
        source_days = {d: g.copy() for d, g in fs.groupby("signal_date", sort=False)}
        self.frames, self.present, self.eligible, self.held_only = [], np.zeros(shape, bool), np.zeros(shape, bool), np.zeros(shape, bool)
        self.adv = np.full(shape, np.nan)
        empty = fs.iloc[:0]
        for i, date in enumerate(self.calendar):
            original = source_days.get(date, empty)
            cols = original.ticker.map(self.ticker_index).to_numpy(int)
            self.present[i, cols] = True
            self.eligible[i, cols] = original.new_buy_eligible.fillna(False).to_numpy(bool) if "new_buy_eligible" in original else True
            self.held_only[i, cols] = original.context_only_if_held.fillna(False).to_numpy(bool) if "context_only_if_held" in original else False
            if adv_column in original:
                self.adv[i, cols] = pd.to_numeric(original[adv_column], errors="coerce").to_numpy(float)
            frame = original.set_index("ticker").reindex(self.tickers).reset_index()
            frame["ticker"] = self.tickers
            frame["signal_date"] = date
            self.frames.append(frame)
        with REFERENCE_PATH.open("rb") as stream:
            self.reference_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()


@dataclass
class BatchReplayResult:
    daily: pd.DataFrame
    trades: pd.DataFrame
    positions: pd.DataFrame
    target_decisions: pd.DataFrame
    execution_results: pd.DataFrame
    raw_model_outputs: pd.DataFrame
    signal_contexts: pd.DataFrame
    diagnostics: pd.DataFrame
    operational_actions: pd.DataFrame
    metadata: dict


class _Recorder:
    TABLES = ["daily", "trades", "positions", "target_decisions", "execution_results",
              "raw_model_outputs", "signal_contexts", "diagnostics", "operational_actions"]
    def __init__(self, output_dir):
        self.output = Path(output_dir) if output_dir is not None else None
        self.buffers = {k: [] for k in self.TABLES}
        self.captured = {k: [] for k in self.TABLES}
        self.parts = {k: 0 for k in self.TABLES}
        self.counts = {k: 0 for k in self.TABLES}
        if self.output is not None:
            if self.output.exists() and any(self.output.iterdir()):
                raise ValueError("preserve existing batch outputs; output_dir must be new or empty")
            self.output.mkdir(parents=True, exist_ok=True)
            (self.output / "decision_coverage").mkdir()

    def add(self, table, frame):
        if frame is None or frame.empty:
            return
        self.counts[table] += len(frame)
        if self.output is None or table == "daily":
            self.captured[table].append(frame)
        if self.output is not None:
            self.buffers[table].append(frame)

    def flush(self):
        if self.output is None:
            return
        for table, parts in self.buffers.items():
            if not parts:
                continue
            directory = self.output / table
            directory.mkdir(exist_ok=True)
            frame = pd.concat(parts, ignore_index=True)
            frame.to_parquet(directory / f"part_{self.parts[table]:04d}.parquet", index=False, compression="zstd")
            self.parts[table] += 1
            parts.clear()

    def result(self, metadata):
        self.flush()
        frames = {k: pd.concat(v, ignore_index=True) if v else pd.DataFrame() for k, v in self.captured.items()}
        metadata.update(table_rows=self.counts, table_parts=self.parts)
        return BatchReplayResult(**frames, metadata=metadata)


def _single_policies(policies, ids, day, ctx, reserve_reasons, ops):
    """Optional compatibility adapter; normal large runs use a batch callback."""
    K, N = ctx["current_units"].shape
    targets, decided, raw_extra = np.zeros((K, N)), np.zeros((K, N), bool), []
    for k, candidate in enumerate(ids):
        held = ctx["current_units"][k] > TOL
        reserved = ctx["reserved_mask"][k]
        weights = {t: float(ctx["current_weights"][k, j]) for j, t in enumerate(ctx["tickers"]) if held[j]}
        units = {t: float(ctx["current_units"][k, j]) for j, t in enumerate(ctx["tickers"]) if held[j]}
        rn = {t: tuple(reserve_reasons[k][j]) for j, t in enumerate(ctx["tickers"]) if reserved[j]}
        single = HoldingAwareContext(ctx["signal_date"], ctx["signal_asof"], weights, units,
            float(ctx["cash_weight"][k]), float(ctx["cash"][k]), float(ctx["nav"][k]),
            tuple(ctx["tickers"][reserved]), {t: units[t] for t in rn}, {t: weights[t] for t in rn},
            float(ctx["reserved_weight"][k]), int(ctx["reserved_slots"][k]), rn,
            int(ctx["available_slots"][k]), float(ctx["available_weight"][k]),
            ctx["max_positions"], ctx["max_weight"], ctx["max_invested"],
            tuple(ctx["tickers"][ctx["buy_restricted_mask"][k]]), tuple(ctx["tickers"][ctx["sell_restricted_mask"][k]]),
            tuple(ctx["tickers"][ctx["decision_mask"][k]]), ops.copy())
        policy = policies[candidate] if isinstance(policies, Mapping) else policies[k]
        result = policy(day.loc[ctx["decision_mask"][k]].copy(), single) if _positive(ctx["nav"])[k] else HoldingAwareDecision()
        if not isinstance(result, HoldingAwareDecision):
            raise ValueError("individual policies must return HoldingAwareDecision")
        if result.operational_exits:
            raise ValueError("declare common dated operational exits in BatchMarket before the callback")
        for ticker, weight in result.model_decisions.items():
            j = ctx["ticker_index"].get(ticker)
            if j is None or not ctx["decision_mask"][k, j]:
                raise ValueError(f"model decision has no decision-day input row: {ticker}")
            targets[k, j], decided[k, j] = float(weight), True
        raw_extra.append(result.raw_model_outputs)
    return {"targets": targets, "decided": decided, "raw": raw_extra}


def run_batch(market, policies, strategy_ids, *, initial_cash=1_000_000., cost_bps=10.,
              capacity_fraction=.01, max_positions=20, max_weight=.10, max_invested=.95,
              output_dir=None, initial_positions=None, capacity_on_sells=False, max_batch_size=384):
    """Advance each account's actual units/cash under a shared market clock.

    For output_dir, tables are parquet directories with cross-strategy rows.
    decision_coverage/YYYYMMDD.npz stores the complete raw targets and packed
    decided/decision-mask bits, including every explicit unheld zero. Sparse
    order tables retain all held names, positive requested targets and exits.
    No terminal liquidation. Returned daily always contains every account/day;
    other returned tables are populated when output_dir is None (test mode).
    """
    if not isinstance(market, BatchMarket):
        raise TypeError("market must be BatchMarket")
    ids = np.asarray(list(strategy_ids), dtype=str)
    K, N = len(ids), market.N
    if not K or len(set(ids)) != K or K > max_batch_size:
        raise ValueError("strategy_ids must be unique, nonempty and within fixed batch limit")
    if not 0 <= cost_bps < 10000 or not 0 < max_weight <= 1 or not 0 < max_invested <= 1 or max_positions < 1 or int(max_positions) != max_positions:
        raise ValueError("invalid portfolio constraints or one-way cost")
    if capacity_fraction is not None and not 0 < capacity_fraction <= 1:
        raise ValueError("invalid capacity_fraction")
    cash = np.broadcast_to(np.asarray(initial_cash, dtype=float), (K,)).copy()
    if not np.isfinite(cash).all() or (cash < 0).any():
        raise ValueError("invalid initial cash")
    units = np.zeros((K, N))
    if initial_positions is not None:
        if isinstance(initial_positions, Mapping):
            for t, q in initial_positions.items():
                if t not in market.ticker_index:
                    raise ValueError("include initially held unknown names using extra_tickers")
                units[:, market.ticker_index[t]] = float(q)
        else:
            units[:] = np.asarray(initial_positions, dtype=float)
    if not np.isfinite(units).all() or (units < 0).any() or ((units > 0).sum(axis=1) > max_positions).any() or ((cash == 0) & (units.sum(axis=1) == 0)).any():
        raise ValueError("invalid initial account")
    initial_units = units.copy()
    initial_cash_array = cash.copy()
    rate = cost_bps / 10000.
    marks, mark_dates = market.initial_marks.copy(), market.initial_mark_dates.copy()
    mark_source = np.where(_positive(marks), "close", "unknown").astype("U7")
    last_adv, last_adv_date = np.full(N, np.nan), np.full(N, np.datetime64("NaT"), dtype="datetime64[ns]")
    pending = None
    previous_nav, previous_certified = np.full(K, np.nan), np.full(K, np.nan)
    rec = _Recorder(output_dir)
    all_rows = np.arange(K)

    def rows(mask, signal_date, execution_date=None, **values):
        rr, cc = np.nonzero(mask)
        if not len(rr):
            return pd.DataFrame()
        decision = np.asarray([f"{s}|{pd.Timestamp(signal_date).date()}" for s in ids])
        data = {"strategy_id": ids[rr], "candidate": ids[rr], "decision_id": decision[rr],
                "order_id": np.asarray([f"{decision[r]}|{market.tickers[c]}" for r, c in zip(rr, cc)]),
                "signal_date": signal_date, "ticker": market.tickers[cc]}
        if execution_date is not None:
            data["execution_date"] = execution_date
        for key, value in values.items():
            if isinstance(value, np.ndarray):
                if value.ndim == 2:
                    data[key] = np.broadcast_to(value, (K, N))[rr, cc]
                elif value.ndim == 1:
                    data[key] = value[rr]
                else:
                    data[key] = value.item()
            else:
                data[key] = value
        return pd.DataFrame(data)

    def outcome(mask, signal, date, status, reason, semantic, kind, side="NONE", notional=0., quantity=0., cost=0., names_at_event=None):
        rec.add("execution_results", rows(mask, signal, date, status=status, reason=reason,
            execution_semantic="EXECUTION_REJECTED" if status == "REJECTED" else status,
            decision_semantic=semantic, order_type=kind, side=side, notional=notional,
            index_units=quantity, transaction_cost=cost,
            actual_names_at_event=(units > TOL).sum(axis=1) if names_at_event is None else names_at_event))

    def reject(mask, signal, date, reason, semantic, kind, side, names_at_event=None):
        outcome(mask, signal, date, "REJECTED", reason, semantic, kind, side, names_at_event=names_at_event)
        rec.add("diagnostics", rows(mask, signal, date, code="execution_rejected", phase="EXECUTION", rejection_reason=reason))

    for i, date in enumerate(market.calendar):
        open_ok, close_ok = _positive(market.opens[i]), _positive(market.closes[i])
        adv_ok = _positive(market.adv[i])
        last_adv[adv_ok], last_adv_date[adv_ok] = market.adv[i, adv_ok], date.to_datetime64()
        before_held = units > TOL
        open_stale = (before_held & ~open_ok[None, :] & _positive(marks)[None, :]).sum(axis=1)
        open_unknown = (before_held & ~open_ok[None, :] & ~_positive(marks)[None, :]).sum(axis=1)
        marks[open_ok], mark_dates[open_ok], mark_source[open_ok] = market.opens[i, open_ok], date.to_datetime64(), "open"
        opening = marks.copy()
        open_values = np.where(before_held, units * np.nan_to_num(opening)[None, :], 0.)
        pre_nav = cash + open_values.sum(axis=1)
        pre_nav[open_unknown > 0] = np.nan
        cash_before = cash.copy()
        fees, buys_total, sells_total, blocked = np.zeros(K), np.zeros(K), np.zeros(K), np.zeros(K, int)
        buy_scale = np.ones(K)
        executed_signal = pending["date"] if pending is not None else pd.NaT
        if pending is not None:
            p, signal = pending, pending["date"]
            healthy = _positive(pre_nav)
            orders, hold, semantic, kind = p["orders"], p["hold"], p["semantic"], p["kind"]
            outcome(orders & hold, signal, date, "PRESERVED_UNITS", np.where(healthy[:, None], "MODEL_NO_DECISION_OR_SIGNAL_RESERVATION", "UNKNOWN_NAV_NO_CAPITAL_CREATED"), semantic, kind)
            rejected_unknown = orders & ~hold & ~healthy[:, None]
            reject(rejected_unknown, signal, date, "UNKNOWN_NAV", semantic, kind, "NONE")
            blocked += rejected_unknown.sum(axis=1)
            active_orders = orders & ~hold & healthy[:, None]
            wanted = p["targets"] * np.nan_to_num(pre_nav)[:, None]
            current = units * np.nan_to_num(opening)[None, :]
            sell_requested = np.where(active_orders, np.maximum(current - wanted, 0.), 0.)
            sell_has = sell_requested > TOL
            sell_restrict = sell_has & p["sell_restricted"]
            sell_missing = sell_has & ~p["sell_restricted"] & ~open_ok[None, :]
            blocked += (sell_restrict | sell_missing).sum(axis=1)
            sell = np.where(sell_has & ~p["sell_restricted"] & open_ok[None, :], sell_requested, 0.)
            sell_adv = np.where(_positive(p["adv"]), p["adv"], p["last_adv"])
            if capacity_fraction is not None and capacity_on_sells:
                sell = np.minimum(sell, np.where(_positive(sell_adv), sell_adv * capacity_fraction, np.inf)[None, :])
            sell_before = units.copy()
            sell_quantity = np.divide(sell, market.opens[i][None, :], out=np.zeros_like(sell), where=open_ok[None, :])
            sell_quantity = np.minimum(sell_quantity, units)
            sell = sell_quantity * np.where(open_ok, market.opens[i], 0.)[None, :]
            sell_cost = sell * rate
            units -= sell_quantity
            units[units <= TOL] = 0.
            cash += (sell - sell_cost).sum(axis=1)
            sells_total, fees = sell.sum(axis=1), sell_cost.sum(axis=1)
            sold = sell > TOL
            # Original sells execute in ticker order. Preserve the event's
            # observed live-name count while updating cash/units in arrays.
            sale_exits = sold & (sell_before > TOL) & (units <= TOL)
            sell_event_names = before_held.sum(axis=1)[:, None] - np.cumsum(sale_exits, axis=1)
            reject(sell_restrict, signal, date, "SIGNAL_KNOWN_SELL_RESTRICTION", semantic, kind, "SELL", sell_event_names)
            reject(sell_missing, signal, date, market.open_reason[i][None, :], semantic, kind, "SELL", sell_event_names)
            sell_action = np.where(units <= TOL, "EXIT", "REDUCE")
            rec.add("trades", rows(sold, signal, date, side="SELL", action=sell_action,
                decision_semantic=semantic, price=market.opens[i][None, :], notional=sell,
                index_units=sell_quantity, shares=sell_quantity, index_units_before=sell_before,
                index_units_after=units, transaction_cost=sell_cost, cost_bps=cost_bps,
                pretrade_nav=pre_nav, buy_fraction_nav=0.,
                sell_fraction_original_units=np.divide(sell_quantity, sell_before, out=np.zeros_like(units), where=sell_before > 0),
                capacity_proxy=capacity_fraction is not None,
                capacity_enforced=(capacity_fraction is not None and capacity_on_sells) & _positive(np.where(_positive(p["last_adv"]), p["last_adv"], p["adv"]))[None, :],
                capacity_adv=np.where(_positive(p["last_adv"]), p["last_adv"], p["adv"])[None, :],
                capacity_adv_source_date=np.where(_positive(p["last_adv"]), p["last_adv_date"], np.where(_positive(p["adv"]), signal.to_datetime64(), np.datetime64("NaT")))[None, :],
                capacity_adv_stale=(_positive(p["last_adv"]) & (p["last_adv_date"] < signal.to_datetime64()))[None, :]))
            outcome(sold, signal, date, "FILLED", "ACTUAL_FILL", semantic, kind, "SELL", sell, sell_quantity, sell_cost, sell_event_names)
            outcome(sold & (sell < sell_requested - TOL), signal, date, "PARTIALLY_FILLED", "SELL_CAPACITY_LIMIT", semantic, kind, "SELL", names_at_event=sell_event_names)
            current = units * np.nan_to_num(opening)[None, :]
            buy_requested = np.where(active_orders, np.maximum(wanted - current, 0.), 0.)
            buy_has = buy_requested > TOL
            buy_ineligible = buy_has & ~p["buy_allowed"]
            buy_missing = buy_has & p["buy_allowed"] & ~open_ok[None, :]
            reject(buy_ineligible, signal, date, "SIGNAL_BUY_INELIGIBLE", semantic, kind, "BUY")
            reject(buy_missing, signal, date, market.open_reason[i][None, :], semantic, kind, "BUY")
            blocked += (buy_ineligible | buy_missing).sum(axis=1)
            request_ok = buy_has & p["buy_allowed"] & open_ok[None, :]
            capped_buy = buy_requested.copy()
            if capacity_fraction is not None:
                capped_buy = np.minimum(capped_buy, np.where(_positive(p["adv"]), p["adv"] * capacity_fraction, 0.)[None, :])
            names_now = units > TOL
            priority = np.argsort(-p["targets"], axis=1, kind="stable")
            priority_new_cap = np.take_along_axis(request_ok & ~names_now & (capped_buy > TOL), priority, axis=1)
            prior_reservations = np.cumsum(priority_new_cap, axis=1) - priority_new_cap
            remaining_slots = max_positions - names_now.sum(axis=1)
            live_sorted = prior_reservations >= remaining_slots[:, None]
            live = np.zeros((K, N), bool)
            np.put_along_axis(live, priority, live_sorted, axis=1)
            live &= request_ok & ~names_now
            missing_adv = request_ok & ~live & (capped_buy <= TOL)
            reject(live, signal, date, "LIVE_POSITION_LIMIT", semantic, kind, "BUY")
            reject(missing_adv, signal, date, "MISSING_SIGNAL_ADV", semantic, kind, "BUY")
            blocked += (live | missing_adv).sum(axis=1)
            requests = np.where(request_ok & ~live & ~missing_adv, capped_buy, 0.)
            required_cash = requests.sum(axis=1) * (1 + rate)
            np.divide(np.maximum(cash, 0.), required_cash, out=buy_scale, where=required_cash > 0)
            buy_scale = np.minimum(buy_scale, 1.)
            buy = requests * buy_scale[:, None]
            no_cash = (requests > TOL) & (buy <= TOL)
            reject(no_cash, signal, date, "INSUFFICIENT_CASH", semantic, kind, "BUY")
            blocked += no_cash.sum(axis=1)
            buy[no_cash] = 0.
            buy_before = units.copy()
            buy_quantity = np.divide(buy, market.opens[i][None, :], out=np.zeros_like(buy), where=open_ok[None, :])
            units += buy_quantity
            units[units <= TOL] = 0.
            buy_cost = buy * rate
            cash -= (buy + buy_cost).sum(axis=1)
            buys_total = buy.sum(axis=1)
            fees += buy_cost.sum(axis=1)
            bought = buy > TOL
            new_bought = bought & (buy_before <= TOL) & (units > TOL)
            new_bought_sorted = np.take_along_axis(new_bought, priority, axis=1)
            buy_event_names = np.zeros((K, N), int)
            np.put_along_axis(buy_event_names, priority,
                              names_now.sum(axis=1)[:, None] + np.cumsum(new_bought_sorted, axis=1), axis=1)
            rec.add("trades", rows(bought, signal, date, side="BUY", action=np.where(buy_before <= TOL, "BUY", "INCREASE"),
                decision_semantic=semantic, price=market.opens[i][None, :], notional=buy,
                index_units=buy_quantity, shares=buy_quantity, index_units_before=buy_before,
                index_units_after=units, transaction_cost=buy_cost, cost_bps=cost_bps,
                pretrade_nav=pre_nav, buy_fraction_nav=np.divide(buy, pre_nav[:, None], out=np.zeros_like(buy), where=_positive(pre_nav)[:, None]),
                sell_fraction_original_units=0., capacity_proxy=capacity_fraction is not None,
                capacity_enforced=capacity_fraction is not None, capacity_adv=p["adv"][None, :],
                capacity_adv_source_date=np.where(_positive(p["adv"]), signal.to_datetime64(), np.datetime64("NaT"))[None, :],
                capacity_adv_stale=False))
            outcome(bought, signal, date, "FILLED", "ACTUAL_FILL", semantic, kind, "BUY", buy, buy_quantity, buy_cost, buy_event_names)
            acted = hold | sell_has | buy_has
            outcome(orders & ~acted & healthy[:, None], signal, date, "NO_ACTION", "TARGET_ALREADY_MET_OR_NO_POSITION", semantic, kind)
            pending = None
        if (cash < -np.maximum(TOL, initial_cash_array * 1e-12)).any() or ((units > TOL).sum(axis=1) > max_positions).any():
            raise AssertionError("cash/actual-position invariant violated")
        cash = np.maximum(cash, 0.)
        open_after = cash + (units * np.nan_to_num(opening)[None, :]).sum(axis=1)
        open_after[open_unknown > 0] = np.nan
        marks[close_ok], mark_dates[close_ok], mark_source[close_ok] = market.closes[i, close_ok], date.to_datetime64(), "close"
        held = units > TOL
        unknown_mask = held & ~_positive(marks)[None, :]
        stale_mask = held & ~close_ok[None, :] & _positive(marks)[None, :]
        unknown_count, stale_count = unknown_mask.sum(axis=1), stale_mask.sum(axis=1)
        position_value = units * np.nan_to_num(marks)[None, :]
        known_value = position_value.sum(axis=1)
        nav = cash + known_value
        nav[unknown_count > 0] = np.nan
        certified = np.where((unknown_count == 0) & (stale_count == 0), nav, np.nan)
        weights = np.divide(position_value, nav[:, None], out=np.full_like(units, np.nan), where=_positive(nav)[:, None])
        weights[~held & _positive(nav)[:, None]] = 0.
        cash_weight = np.divide(cash, nav, out=np.full(K, np.nan), where=_positive(nav))
        pos = rows(held, date, date, date=date, index_units=units, shares=units,
                   mark=marks[None, :], mark_date=mark_dates[None, :], mark_source=mark_source[None, :],
                   market_value=np.where(unknown_mask, np.nan, position_value), weight=weights,
                   stale=stale_mask, unknown=unknown_mask, current_close_reason=market.close_reason[i][None, :])
        if not pos.empty:
            pos["decision_id"] = ids[np.nonzero(held)[0]] + "|MARK|" + str(date.date())
            pos["order_id"] = None
        rec.add("positions", pos)
        daily = pd.DataFrame(dict(strategy_id=ids, candidate=ids, date=date, execution_date=date,
            decision_id=[f"{s}|{executed_signal.date()}" if pd.notna(executed_signal) else None for s in ids],
            order_id=None, signal_date=executed_signal, cash=cash.copy(), nav=nav.copy(), certified_nav=certified,
            valuation_status=np.where(unknown_count > 0, "unknown", np.where(stale_count > 0, "stale", "certified")),
            pretrade_nav=pre_nav, open_pretrade_nav=pre_nav, open_posttrade_nav=open_after,
            open_stale_count=open_stale, open_unknown_count=open_unknown, known_position_value=known_value,
            stale_count=stale_count, unknown_count=unknown_count, actual_name_count=held.sum(axis=1),
            cash_weight=cash_weight, gross_exposure=np.divide(known_value, nav, out=np.full(K, np.nan), where=_positive(nav)),
            net_return=np.divide(certified, previous_certified, out=np.full(K, np.nan), where=_positive(certified) & _positive(previous_certified)) - 1,
            indicative_return=np.divide(nav, previous_nav, out=np.full(K, np.nan), where=_positive(nav) & _positive(previous_nav)) - 1,
            transaction_cost_amount=fees, buy_notional=buys_total, sell_notional=sells_total,
            traded_notional=buys_total + sells_total,
            turnover=np.divide(.5 * (buys_total + sells_total), pre_nav, out=np.full(K, np.nan), where=_positive(pre_nav)),
            buy_cash_scale=buy_scale, blocked_order_count=blocked,
            nav_identity_error=np.where(_positive(nav), nav - cash - known_value, np.nan),
            cash_flow_identity_error=cash - cash_before - (sells_total - buys_total - fees),
            cost_identity_error=fees - (buys_total + sells_total) * rate,
            open_self_finance_error=open_after - pre_nav + fees))
        rec.add("daily", daily)
        if market.signal_start <= date <= market.signal_end:
            asof = market.asofs.get(date, date)
            if pd.isna(asof) or asof.date() != date.date():
                raise ValueError("signal_asof must lie in signal session date")
            ops = _reference.checked_exits(market.ops.get(date, {}), asof)
            ops_mask = np.asarray([t in ops for t in market.tickers])
            present = np.broadcast_to(market.present[i], (K, N)).copy()
            # Context-only names are observable exclusively in accounts that own
            # them; this preserves the published holding-context data contract.
            present &= ~market.held_only[i][None, :] | held
            buy_restrict = np.broadcast_to(~close_ok, (K, N)).copy()
            sell_restrict = np.broadcast_to(~close_ok, (K, N)).copy()
            reserve_reasons = [[[] for _ in range(N)] for _ in range(K)] if not callable(policies) else None
            reserved = held & (~present | ~close_ok[None, :])
            for restriction in market.restrictions.get(date, []):
                if pd.isna(restriction["reason"]) or pd.isna(restriction["source_id"]):
                    raise ValueError("known restriction has missing source evidence")
                _reference.checked_exits({restriction["ticker"]: OperationalExit(str(restriction["reason"]), restriction["known_at"], str(restriction["source_id"]))}, asof)
                j = market.ticker_index.get(restriction["ticker"])
                if j is None:
                    continue
                if bool(restriction.get("buy_restricted", False)):
                    buy_restrict[:, j] = True
                if bool(restriction.get("sell_restricted", False)):
                    sell_restrict[:, j] = True
                    reserved[:, j] |= held[:, j]
            reserved &= ~ops_mask[None, :] | sell_restrict
            reserved |= held & ~_positive(nav)[:, None]
            if reserve_reasons is not None:
                for k, j in zip(*np.nonzero(reserved)):
                    if not _positive(nav)[k]:
                        reserve_reasons[k][j] = ["UNKNOWN_ACCOUNT_NAV"]
                    else:
                        if not close_ok[j]:
                            reserve_reasons[k][j].append("SIGNAL_CLOSE_UNAVAILABLE:" + market.close_reason[i, j])
                        if not present[k, j]:
                            reserve_reasons[k][j].append("MODEL_INPUT_ROW_ABSENT")
                        if sell_restrict[k, j] and close_ok[j]:
                            reserve_reasons[k][j].append("KNOWN_RESTRICTION")
            reserve_weight = np.where(_positive(nav), np.where(reserved, weights, 0.).sum(axis=1), np.nan)
            reserve_slots = reserved.sum(axis=1)
            decision_mask = present & ~reserved & ~ops_mask[None, :] & ~(buy_restrict & ~held) & _positive(nav)[:, None]
            buy_allowed = present & market.eligible[i][None, :] & ~buy_restrict
            ctx = dict(strategy_ids=ids.copy(), tickers=market.tickers.copy(), ticker_index=market.ticker_index.copy(),
                signal_date=date, signal_asof=asof, current_weights=weights.copy(), current_units=units.copy(),
                cash=cash.copy(), cash_weight=cash_weight.copy(), nav=nav.copy(), reserved_mask=reserved.copy(),
                reserved_weight=reserve_weight, reserved_slots=reserve_slots,
                available_slots=np.maximum(0, max_positions - reserve_slots),
                available_weight=np.where(_positive(nav), np.maximum(0., max_invested - reserve_weight), 0.),
                decision_mask=decision_mask.copy(), buy_allowed_mask=buy_allowed.copy(),
                buy_restricted_mask=buy_restrict.copy(), sell_restricted_mask=sell_restrict.copy(),
                max_positions=max_positions, max_weight=max_weight, max_invested=max_invested)
            day = market.frames[i].copy(deep=True)
            day.attrs.update(signal_date=date, valuation_clock="signal_close")
            result = policies(day, ctx) if callable(policies) else _single_policies(policies, ids, day, ctx, reserve_reasons, ops)
            if not isinstance(result, Mapping) or "targets" not in result or "decided" not in result:
                raise ValueError("batch callback requires targets and decided arrays")
            raw, decided = np.asarray(result["targets"], dtype=float), np.asarray(result["decided"], dtype=bool)
            if raw.shape != (K, N) or decided.shape != (K, N):
                raise ValueError("callback arrays must have shape K,N")
            if (decided & ~decision_mask).any():
                raise ValueError("model decision has no decision-day input row")
            if (decided & (~np.isfinite(raw) | (raw < 0) | (raw > max_weight + WEIGHT_TOL))).any():
                raise ValueError("invalid explicit model weight")
            raw = np.where(decided, raw, 0.)
            final_reserved = reserved | (held & ~decided & ~ops_mask[None, :])
            final_reserved &= ~ops_mask[None, :] | sell_restrict
            final_weight = np.where(_positive(nav), np.where(final_reserved, weights, 0.).sum(axis=1), np.nan)
            available_weight = np.where(_positive(nav), np.maximum(0., max_invested - final_weight), 0.)
            available_slots = np.maximum(0, max_positions - final_reserved.sum(axis=1))
            adapted = np.where(decided & ~final_reserved & ~ops_mask[None, :], np.minimum(raw, max_weight), 0.)
            restricted_increase = ~buy_allowed & (adapted > weights)
            adapted[restricted_increase] = np.maximum(0., weights[restricted_increase])
            positive = adapted > 0
            priority = np.argsort(-np.where(positive, 2. * held + adapted, -1.), axis=1, kind="stable")
            positive_sorted = np.take_along_axis(positive, priority, axis=1)
            rank_sorted = np.cumsum(positive_sorted, axis=1)
            excess_sorted = positive_sorted & (rank_sorted > available_slots[:, None])
            excess = np.zeros((K, N), bool)
            np.put_along_axis(excess, priority, excess_sorted, axis=1)
            adapted[excess] = 0.
            total = adapted.sum(axis=1)
            scale = np.ones(K)
            np.divide(available_weight, total, out=scale, where=(total > available_weight) & (total > 0))
            adapted *= scale[:, None]
            orders = held | (decided & (raw > 0)) | ops_mask[None, :]
            hold_orders = final_reserved & ~ops_mask[None, :]
            kind = np.where(ops_mask[None, :], "EXIT", np.where(hold_orders, "HOLD_UNITS", "TARGET_WEIGHT"))
            semantic = np.where(ops_mask[None, :], "OPERATIONAL_EXIT_REQUIRED",
                np.where(decided & (raw == 0) & held, "MODEL_ACTIVE_EXIT",
                np.where(decided & (raw == 0), "MODEL_ZERO_ALLOCATION", np.where(decided, "MODEL_TARGET_WEIGHT", "MODEL_NO_DECISION"))))
            next_date = market.calendar[i + 1] if i + 1 < market.T else pd.NaT
            final_targets = np.where(hold_orders, weights, adapted)
            raw_path = "in_memory"
            expert_path = None
            if rec.output is not None:
                raw_path = "decision_coverage/" + date.strftime("%Y%m%d") + ".npz"
                np.savez_compressed(rec.output / raw_path, targets=raw, decided=np.packbits(decided, axis=1, bitorder="little"),
                    decision_mask=np.packbits(decision_mask, axis=1, bitorder="little"),
                    reserved_mask=np.packbits(reserved, axis=1, bitorder="little"),
                    final_reserved_mask=np.packbits(final_reserved, axis=1, bitorder="little"),
                    buy_allowed_mask=np.packbits(buy_allowed, axis=1, bitorder="little"),
                    ticker_count=np.asarray(N), strategy_count=np.asarray(K))
                if "expert_targets" in result:
                    experts = np.asarray(result["expert_targets"], dtype=float)
                    expert_rows = np.asarray(result["expert_strategy_indices"], dtype=int)
                    expert_names = np.asarray(result["expert_names"], dtype=str)
                    if (experts.shape != (len(expert_rows), len(expert_names), N)
                            or (expert_rows < 0).any() or (expert_rows >= K).any()
                            or not np.isfinite(experts).all()):
                        raise ValueError("invalid target-fusion expert contribution arrays")
                    expert_path = "decision_coverage/" + date.strftime("%Y%m%d") + "_experts.npz"
                    np.savez_compressed(rec.output / expert_path, targets=experts,
                                        rowindices=expert_rows, expert_names=expert_names)
            extra = result.get("raw")
            if extra is None:
                raw_extra = [None] * K
            elif isinstance(extra, list) and len(extra) == K:
                raw_extra = extra
            else:
                raw_extra = [extra] * K
            raw_frame = pd.DataFrame(dict(strategy_id=ids, candidate=ids, signal_date=date,
                decision_id=[f"{s}|{date.date()}" for s in ids], order_id=None,
                policy_called=_positive(nav), raw_matrix_path=raw_path, raw_matrix_strategy_row=all_rows,
                expert_matrix_path=expert_path,
                decided_count=decided.sum(axis=1), explicit_unheld_zero_count=(decided & ~held & (raw == 0)).sum(axis=1),
                raw_model_outputs_json=[_json(x) for x in raw_extra]))
            if rec.output is None:
                raw_frame["model_decisions_json"] = [_json({t: float(raw[k, j]) for j, t in enumerate(market.tickers) if decided[k, j]}) for k in range(K)]
            rec.add("raw_model_outputs", raw_frame)
            reasons = np.full((K, N), "", dtype="U160")
            reasons[restricted_increase] = "SIGNAL_NEW_CAPITAL_INELIGIBLE"
            reasons[excess] = np.where(reasons[excess] == "", "", reasons[excess] + "|") + "SIGNAL_RESERVED_SLOT_BUDGET"
            scaled = (scale < 1)[:, None] & (adapted > 0)
            reasons[scaled] = np.where(reasons[scaled] == "", "", reasons[scaled] + "|") + "SIGNAL_RESERVED_CAPITAL_BUDGET"
            rec.add("target_decisions", rows(orders, date, next_date,
                decision_semantic=semantic, order_type=kind, explicit_model_decision=decided,
                model_input_row_present=present, decision_input_row_present=decision_mask,
                raw_model_weight=np.where(decided, raw, np.nan), target_weight=final_targets,
                adapted_target_weight=final_targets, current_weight=weights, current_units=units,
                hold_units=np.where(hold_orders, units, 0.), signal_reserved=final_reserved,
                adaptation_reasons=reasons, cash_weight=cash_weight, signal_close_nav=nav,
                status="no_next_session" if pd.isna(next_date) else "submitted", signal_day_adv=market.adv[i][None, :],
                reserved_weight=final_weight, active_target_sum=adapted.sum(axis=1),
                total_signal_committed_weight=final_weight + adapted.sum(axis=1), raw_matrix_path=raw_path))
            rec.add("signal_contexts", pd.DataFrame(dict(strategy_id=ids, candidate=ids, signal_date=date,
                decision_id=[f"{s}|{date.date()}" for s in ids], order_id=None, signal_asof=asof,
                nav=nav.copy(), cash=cash.copy(), cash_weight=cash_weight, input_count=present.sum(axis=1),
                decision_input_count=decision_mask.sum(axis=1), reserved_slots=reserve_slots, reserved_weight=reserve_weight,
                available_slots=ctx["available_slots"], available_weight=ctx["available_weight"],
                final_reserved_slots=final_reserved.sum(axis=1), final_reserved_weight=final_weight,
                final_available_slots=available_slots, final_available_weight=available_weight,
                active_target_count=(adapted > 0).sum(axis=1), active_target_weight=adapted.sum(axis=1),
                policy_called=_positive(nav), raw_matrix_path=raw_path)))
            for ticker, action in ops.items():
                j = market.ticker_index[ticker]
                mask = np.zeros((K, N), bool)
                mask[:, j] = True
                rec.add("operational_actions", rows(mask, date, semantic="OPERATIONAL_EXIT_REQUIRED", reason=action.reason,
                    known_at=pd.Timestamp(action.known_at), source_id=action.source_id, had_position=held,
                    signal_sell_restricted=sell_restrict, reserved_until_execution=final_reserved))
            if pd.notna(next_date):
                pending = dict(date=date, orders=orders, hold=hold_orders, semantic=semantic, kind=kind,
                    targets=adapted, buy_allowed=buy_allowed.copy(), sell_restricted=sell_restrict.copy(),
                    adv=market.adv[i].copy(), last_adv=last_adv.copy(), last_adv_date=last_adv_date.copy())
        previous_nav, previous_certified = nav.copy(), certified.copy()
        if (i + 1) % 20 == 0:
            rec.flush()
    metadata = dict(version="NUMPY_BATCH_HOLDING_AWARE_V1", reference_sha256=market.reference_sha256,
        strategy_ids=ids.tolist(), tickers=market.tickers.tolist(), independent_accounts=K,
        initial_cash=initial_cash_array.tolist(), initial_units=initial_units.tolist(),
        max_positions=max_positions, max_target_weight=max_weight, max_target_invested=max_invested,
        cost_bps_one_way=cost_bps, capacity_fraction=capacity_fraction, capacity_on_sells=capacity_on_sells,
        signal_start=str(market.signal_start.date()), signal_end=str(market.signal_end.date()),
        valuation_first=str(market.calendar[0].date()), valuation_last=str(market.calendar[-1].date()),
        decision_clock="signal close; immutable signal ADV and eligibility; execute next session open",
        missing_decision_policy="held units/capital/slots preserved; explicit zero is model exit",
        quantity_unit="affine price-index units, not physical shareholder shares",
        sparse_order_scope="all held names, positive explicitly requested names and operational exits; all other explicit zeros stored in complete raw decision matrix",
        target_fusion_expert_scope="decision_coverage/YYYYMMDD_experts.npz: targets(Kfusion,E,N), rowindices into strategy_ids, expert_names; every expert uses that fusion strategy's actual account state",
        decision_bit_order="little", terminal_liquidation=False, shareholder_total_return_certified=False,
        max_cash_identity_error=float(rec.result({}).daily.cash_flow_identity_error.abs().max()))
    result = rec.result(metadata)
    if rec.output is not None:
        (rec.output / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return result
