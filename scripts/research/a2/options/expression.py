"""Fixed opportunity-level expression adapter, not a portfolio backtest engine."""
from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
from math import floor, log, sqrt

import numpy as np
import pandas as pd

from fast3.src.fast3.options.moomoo_option_shadow_r1 import choose_atm_contract, choose_expiry
from scripts.v22.r9a_trade_ledger import TradeLedgerEvent, validate_ledger
from .contracts import (Contract, Fees, Invalid, LifecycleEvent, Mark, Opportunity, Quote,
                        TEMPLATE, calendar, clock, finite, in_session, pre2026, require,
                        ts, validate_opportunity, validate_quote)


def select_contract(o: Opportunity, contracts: tuple[Contract, ...]) -> Contract | None:
    """This function cannot see future quotes, path labels or lifecycle events."""
    validate_opportunity(o)
    decision = ts(o.decision_at)
    day = str(decision.tz_convert("America/New_York").date())
    buffered = clock(day, 7)
    seen = set()
    legal = []
    for c in contracts:
        if ts(c.available_at) > decision:
            continue
        require(c.contract_id not in seen, "DUPLICATE_CONTRACT")
        seen.add(c.contract_id)
        pre2026(c.available_at)
        expiry = pd.Timestamp(c.expiry)
        dte = (expiry.date() - pd.Timestamp(day).date()).days
        if c.underlying_uid != o.underlying_uid or c.right != "CALL" or not finite(c.strike, positive=True):
            continue
        if (c.multiplier != 100 or type(c.multiplier) is not int or c.currency != "USD"
                or c.deliverable != "100_UNDERLYING_SHARES" or c.adjustment_status != "STANDARD"
                or c.exercise_style != "AMERICAN" or c.settlement_type != "PHYSICAL" or not c.source or not c.version):
            continue
        if not 30 <= dte <= 60 or not in_session(c.last_trade_at, economic=False):
            continue
        last_day = ts(c.last_trade_at).tz_convert("America/New_York").date()
        if last_day > expiry.date():
            continue
        buffer_close = calendar().schedule.loc[str(buffered.tz_convert('America/New_York').date()), "close"]
        if ts(c.last_trade_at) < buffer_close:
            continue
        legal.append((c, dte))
    expiry = choose_expiry([{"expiry": c.expiry, "dte": dte} for c, dte in legal], 45)
    if expiry is None:
        return None
    picked = choose_atm_contract([{"expiry": c.expiry, "call_put": c.right, "strike": c.strike,
                                  "option_code": c.contract_id} for c, _ in legal], expiry["expiry"], "CALL", o.spot)
    return next(c for c, _ in legal if c.contract_id == picked["option_code"])


def quote_at(quotes: tuple[Quote, ...], o: Opportunity, instrument: str, at: pd.Timestamp,
             *, option: bool, decision: bool = False, quantity: float = 0, side: str = "BUY") -> tuple[Quote | None, str]:
    candidates = sorted((q for q in quotes if q.instrument_id == instrument),
                        key=lambda q: (ts(q.event_at), ts(q.available_at)))
    reason = "NO_DECISION_QUOTE" if decision else "NO_EXECUTION_QUOTE"
    valid = []
    seen = set()
    for q in candidates:
        event, available = ts(q.event_at), ts(q.available_at)
        if decision:
            if not (available <= at and at - event <= timedelta(seconds=2)):
                continue
        elif not (at + timedelta(seconds=1) <= event <= available <= at + timedelta(seconds=61)):
            continue
        key = (q.instrument_id, ts(q.event_at), ts(q.available_at))
        require(key not in seen, "DUPLICATE_QUOTE")
        seen.add(key)
        try:
            validate_quote(q, o.underlying_uid, instrument, option=option, grade=o.evidence_grade)
            if side == "BUY":
                require(q.bid > 0 and q.ask_size >= quantity and q.ask_size > 0, "ENTRY_SIZE_OR_BID")
            else:
                require(q.bid > 0 and q.bid_size >= quantity and q.bid_size > 0, "EXIT_SIZE_OR_BID")
        except Invalid as exc:
            reason = str(exc)
            continue
        valid.append(q)
    return ((valid[-1] if decision else valid[0]), "OK") if valid else (None, reason)


def decision_delta(q: Quote | None, decision: str) -> float | None:
    if q is None or q.delta is None or not finite(q.delta) or q.delta > 1:
        return None
    if (not q.delta_at or not q.delta_source or q.delta_unit != "PER_UNDERLYING_SHARE"
            or q.delta_style != "AMERICAN" or q.delta_kind != "PROVIDER_HISTORICAL"):
        return None
    try:
        if not ts(q.delta_at) <= ts(decision) or abs(ts(q.event_at) - ts(q.delta_at)) > timedelta(seconds=2):
            return None
    except (Invalid, ValueError):
        return None
    if q.evidence_grade == "REAL_HISTORICAL_QUOTES" and q.delta_source == "SYNTHETIC":
        return None
    return float(q.delta)


def payoff_at_expiry(spot: float, strike: float, premium: float, multiplier: int = 100) -> float:
    """Terminal arithmetic only; not a fill or automatic exercise instruction."""
    require(all(finite(v) for v in (spot, strike, premium)) and type(multiplier) is int and multiplier == 100,
            "INVALID_PAYOFF_UNITS")
    return (max(spot - strike, 0) - premium) * multiplier


def settle_cash_order(cash: float, quantity: float, quote_price: float, *,
                      option: bool, fees: Fees, side: str) -> dict:
    """Original order arithmetic only; no quote, identity or execution authority.

    Callers establish their own observation/assumption scope. Keep operation
    ordering identical to replay_arm so its float-USD results do not change.
    """
    require(side in {"BUY", "SELL"}, "INVALID_CASH_ORDER_SIDE")
    fee = fees.order(quantity, option)
    slip = fees.option_slippage if option else fees.stock_slippage
    multiplier = 100 if option else 1
    if side == "BUY":
        fill_price = quote_price + slip
        debit = quantity * multiplier * fill_price + fee
        cash_after = cash - debit
        reason = "FILL_OVER_BUDGET" if debit > cash else "OK"
    else:
        fill_price = quote_price - slip
        proceeds = quantity * multiplier * fill_price - fee
        cash_after = cash + proceeds
        reason = "EXIT_FINANCING_REQUIRED" if quote_price < slip or cash_after < 0 else "OK"
    return {"cash_after": cash_after, "fill_price": fill_price, "fee": fee,
            "slippage": quantity * multiplier * slip, "reason": reason}


def replay_arm(o: Opportunity, instrument: str, quantity: float, quotes: tuple[Quote, ...],
               *, option: bool, fees: Fees, arm: str, events: tuple[LifecycleEvent, ...] = (),
               evaluated_at: str = "2025-12-31T23:00:00Z") -> tuple[dict, list[dict]]:
    multiplier = 100 if option else 1
    decision = ts(o.decision_at)
    exit_at = clock(str(decision.tz_convert("America/New_York").date()), 5)
    row = {"decision_id": o.decision_id, "underlying_uid": o.underlying_uid,
           "decision_at": o.decision_at, "arm": arm, "instrument_id": instrument,
           "initial_cash": o.capital, "cash": o.capital, "quantity": 0., "action": "CASH",
           "status": "NOT_OPENED", "reason": "ZERO_QUANTITY", "net_wealth": o.capital,
           "net_pnl": 0., "entry_fee": 0., "exit_fee": 0., "extra_slippage": 0.,
           "entry_at": None, "exit_at": None, "label_end": None, "label_available_at": None,
           "planned_entry": str(decision + timedelta(seconds=1)), "planned_exit": str(exit_at),
           "evidence_grade": o.evidence_grade, "quantity_unit": "CONTRACTS" if option else "SHARES",
           "usage": "ANALYTICAL_ONLY", "fee_basis": "ASSUMED_CURRENT_SCENARIO_NOT_ACCOUNT",
           "price_basis": "ASK_BUY_BID_SELL", "unresolved": False}
    if quantity <= 0:
        return row, []
    try:
        q, reason = quote_at(quotes, o, instrument, decision, option=option, quantity=quantity)
    except Invalid as exc:
        q, reason = None, str(exc)
    if q is None:
        row["reason"] = reason
        return row, []
    if ts(q.available_at) > ts(evaluated_at):
        row["reason"] = "ENTRY_NOT_YET_AVAILABLE"
        return row, []
    entry_cash = settle_cash_order(o.capital, quantity, q.ask, option=option, fees=fees, side="BUY")
    fee = entry_cash["fee"]
    slip = fees.option_slippage if option else fees.stock_slippage
    if entry_cash["reason"] != "OK":
        row["reason"] = entry_cash["reason"]
        return row, []
    cash = entry_cash["cash_after"]
    row.update(action="LONG_CALL" if option else "STOCK", status="OPEN", reason="ENTRY_FILLED",
               cash=cash, quantity=quantity, net_wealth=None, net_pnl=None, entry_fee=fee,
               entry_at=q.available_at, extra_slippage=quantity * multiplier * slip,
               entry_price=q.ask, entry_delta_raw=q.delta, entry_delta_qualified=decision_delta(q, q.available_at),
               source=q.source, source_version=q.version)
    ledger = []

    def append(side, fill, price, cash_before, cash_after, before, after, order_fee):
        event = TradeLedgerEvent(TEMPLATE, f"{o.decision_id}:{arm}:{side}", f"{o.decision_id}:{arm}",
                                 fill.available_at, o.underlying_uid, side, quantity * multiplier,
                                 price, quantity * multiplier * price, quantity * multiplier * price / o.capital,
                                 "FIXED_R1", None, None, cash_before, cash_after, before, after)
        record = event.to_dict()
        record.update(arm=arm, decision_id=o.decision_id, instrument_id=instrument, fee=order_fee,
                      contracts=quantity if option else None, multiplier=multiplier,
                      evidence_grade=o.evidence_grade, price_source=fill.source, price_version=fill.version,
                      event_at=fill.event_at, available_at=fill.available_at, ingested_at=fill.ingested_at)
        expected = cash_before + (-1 if side == "BUY" else 1) * record["notional"] - order_fee
        require(abs(expected - cash_after) < 1e-8 and cash_after >= 0, "CASH_CONSERVATION")
        ledger.append(record)

    append("BUY", q, entry_cash["fill_price"], o.capital, cash, 0, quantity * multiplier, fee)
    lifecycle = []
    for event in events:
        if event.contract_id != instrument:
            continue
        try:
            event_at = ts(event.event_at)
            if ts(q.available_at) <= event_at <= exit_at + timedelta(seconds=61):
                pre2026(event_at)
                lifecycle.append(event)
        except (Invalid, ValueError):
            # An already funded position cannot disappear because event timing
            # is unresolvable. Future out-of-window synthetic events are ignored.
            lifecycle.append(event)
    try:
        out, reason = quote_at(quotes, o, instrument, exit_at, option=option, quantity=quantity, side="SELL")
    except Invalid as exc:
        out, reason = None, str(exc)
    if lifecycle or out is None or ts(out.available_at) > ts(evaluated_at):
        row.update(action="HOLD", status="UNRESOLVED", unresolved=True,
                   reason="LIFECYCLE_UNRESOLVED" if lifecycle else ("LABEL_NOT_MATURE" if out else reason),
                   lifecycle_status="SETTLEMENT_UNIDENTIFIED" if option else "POSITION_OPEN")
        return row, ledger
    exit_cash = settle_cash_order(cash, quantity, out.bid, option=option, fees=fees, side="SELL")
    exit_fee = exit_cash["fee"]
    if exit_cash["reason"] != "OK":
        row.update(action="HOLD", status="UNRESOLVED", unresolved=True, reason=exit_cash["reason"])
        return row, ledger
    final_cash = exit_cash["cash_after"]
    append("SELL", out, exit_cash["fill_price"], cash, final_cash, quantity * multiplier, 0, exit_fee)
    row.update(action="CASH", status="CLOSED", reason="FIXED_EXIT", cash=final_cash, quantity=0.,
               net_wealth=final_cash, net_pnl=final_cash-o.capital, exit_fee=exit_fee,
               extra_slippage=2 * quantity * multiplier * slip, exit_at=out.available_at,
               label_end=out.event_at, label_available_at=out.available_at, exit_price=out.bid)
    return row, ledger


def path_metrics(prices) -> dict:
    """Clock-independent arithmetic; callers must validate complete causal marks."""
    returns = [p/prices[0]-1 for p in prices]
    return dict(absolute_return=returns[-1], mfe=max(returns), mae=min(returns),
                realized_volatility=sqrt(sum(log(b/a)**2 for a, b in zip(prices, prices[1:]))),
                first_positive_session=next((i for i, r in enumerate(returns) if r > 0), None))


def date_interval(daily: dict) -> list | None:
    """Original R1 equal-date moving-block interval; no row independence claim."""
    dates = sorted(daily)
    if len(dates) < 40:
        return None
    axis = calendar().sessions_in_range(dates[0], dates[-1])
    values = np.array([daily.get(str(d.date()), np.nan) for d in axis])
    rng = np.random.default_rng(1729)
    starts = rng.integers(0, len(values)-19, size=(2000, (len(values)+19)//20))
    sample = values[(starts[..., None] + np.arange(20)).reshape(2000, -1)[:, :len(values)]]
    if np.any(np.isfinite(sample), axis=1).all():
        return [float(x) for x in np.quantile(np.nanmean(sample, axis=1), [.025, .975])]
    return None


def stock_path(o: Opportunity, marks: tuple[Mark, ...], horizon: int, evaluated_at: str) -> dict:
    require(horizon in {5, 20}, "INVALID_HORIZON")
    row = {"decision_id": o.decision_id, "underlying_uid": o.underlying_uid, "horizon": horizon,
           "role": "POSTHOC_PATH_LABEL", "clock": "09:45_MARK_NOT_EXECUTION", "evidence_grade": o.evidence_grade,
           "status": "MISSING", "reason": "MISSING_PATH"}
    day = str(ts(o.decision_at).tz_convert('America/New_York').date())
    try:
        required = [clock(day, i) for i in range(horizon + 1)]
        selected = [m for m in marks if m.underlying_uid == o.underlying_uid and ts(m.event_at) in required]
        require(len({ts(m.event_at) for m in selected}) == len(selected), "DUPLICATE_MARK")
        require({ts(m.event_at) for m in selected} == set(required), "MISSING_PATH")
        selected.sort(key=lambda m: ts(m.event_at))
        for m in selected:
            require(m.evidence_grade == o.evidence_grade and bool(m.source), "PATH_SOURCE")
            require(m.identity_status == "VERIFIED" and m.action_status == "UNCHANGED", "PATH_IDENTITY_OR_ACTION")
            require(finite(m.price, positive=True), "PATH_PRICE")
            require(pre2026(m.event_at) <= pre2026(m.available_at) <= ts(evaluated_at), "LABEL_NOT_MATURE")
        prices = [m.price for m in selected]
        row.update(status="COMPLETE", reason="OK", **path_metrics(prices),
                   label_end=selected[-1].event_at, label_available_at=max(selected, key=lambda m: ts(m.available_at)).available_at,
                   price_source=selected[0].source)
    except Invalid as exc:
        row["reason"] = str(exc)
    return row


def evaluate(opportunities: tuple[Opportunity, ...], contracts: tuple[Contract, ...], quotes: tuple[Quote, ...],
             marks: tuple[Mark, ...] = (), events: tuple[LifecycleEvent, ...] = (),
             *, fees: Fees = Fees(), evaluated_at: str = "2025-12-31T23:00:00Z") -> dict:
    """Pure replay. Real IO authority must be established before constructing inputs."""
    ids = [o.decision_id for o in opportunities]
    require(len({o.evidence_grade for o in opportunities}) <= 1, "MIXED_EVIDENCE_DOMAIN")
    require(len(ids) == len(set(ids)), "DUPLICATE_OPPORTUNITY")
    require(len({(ts(o.decision_at), o.underlying_uid) for o in opportunities}) == len(opportunities), "DUPLICATE_UID_DATE")
    panel, outcomes, ledger, labels = [], [], [], []
    for o in sorted(opportunities, key=lambda o: (o.decision_at, o.decision_id)):
        decision = {**asdict(o), "template_id": TEMPLATE, "contract_id": None, "eligible": False,
                    "action": "CASH", "reason": "UNKNOWN", "decision_delta": None, "valid_opportunity": False}
        try:
            validate_opportunity(o)
        except (Invalid, ValueError, TypeError) as exc:
            decision["reason"] = str(exc)
            panel.append(decision)
            continue
        decision["valid_opportunity"] = True
        # Stock labels have no dependency on an option-chain or quote success.
        labels.extend(stock_path(o, marks, h, evaluated_at) for h in (5, 20))
        try:
            c = select_contract(o, contracts)
            dq, reason = quote_at(quotes, o, c.contract_id, ts(o.decision_at), option=True, decision=True) if c else (None, "NO_ELIGIBLE_CONTRACT")
        except (Invalid, ValueError, TypeError) as exc:
            c, dq, reason = None, None, str(exc)
        try:
            sq, stock_reason = quote_at(quotes, o, o.underlying_uid, ts(o.decision_at), option=False, decision=True)
        except (Invalid, ValueError, TypeError) as exc:
            sq, stock_reason = None, str(exc)
        delta = decision_delta(dq, o.decision_at)
        minimum = dq.ask * 100 + fees.order(1, True) if dq else None
        eligible = c is not None and dq is not None and minimum <= o.capital
        decision.update(contract_id=c.contract_id if c else None, eligible=eligible,
                        action="LONG_CALL" if eligible else "CASH", reason="ELIGIBLE" if eligible else ("ONE_CALL_OVER_BUDGET" if minimum and minimum > o.capital else reason),
                        decision_delta=delta, minimum_one_contract_cash=minimum,
                        budget_source="FIXED_ANALYTICAL_CAPITAL_NOT_USER_BALANCE", quantity=1 if eligible else 0)
        stock_quantity = floor(o.capital / (sq.ask + fees.stock_per_share)) if sq else 0
        if sq and stock_quantity * sq.ask + fees.order(stock_quantity, False) > o.capital:
            stock_quantity = max(0, stock_quantity - 1)
        for arm, instrument, quantity, option in [
                ("LONG_CALL", c.contract_id if c else "", 1 if eligible else 0, True),
                ("STOCK", o.underlying_uid, stock_quantity, False),
                ("CASH", o.underlying_uid, 0, False),
                ("DECISION_DELTA_MATCHED_FUNDED_STOCK", o.underlying_uid,
                 100 * delta if eligible and delta is not None and sq and 100*delta*sq.ask + fees.order(100*delta, False) <= o.capital else 0, False)]:
            result, entries = replay_arm(o, instrument, quantity, quotes, option=option, fees=fees, arm=arm, events=events,
                                         evaluated_at=evaluated_at)
            if arm == "LONG_CALL" and not eligible:
                result["reason"] = decision["reason"]
            if arm == "LONG_CALL":
                entry_delta = result.get("entry_delta_qualified")
                result["decision_to_entry_delta_drift"] = entry_delta-delta if entry_delta is not None and delta is not None else None
                result["delta_drift_status"] = "AVAILABLE" if result["decision_to_entry_delta_drift"] is not None else "NOT_IDENTIFIABLE"
            if arm == "STOCK" and not sq:
                result["reason"] = stock_reason
            if arm == "DECISION_DELTA_MATCHED_FUNDED_STOCK":
                result["delta_identifiable"] = bool(eligible and delta is not None and quantity > 0)
                result["decision_delta"] = delta
            outcomes.append(result)
            ledger.extend(entries)
        panel.append(decision)
    require(validate_ledger([TradeLedgerEvent(**{k: row[k] for k in TradeLedgerEvent.__dataclass_fields__}) for row in ledger])["unique_event_ids"], "LEDGER_DUPLICATE")
    return {"opportunities": panel, "outcomes": outcomes, "ledger": ledger, "labels": labels}


def paired_summary(result: dict) -> dict:
    """Frozen date-weighted estimand, with unavailable data kept out of wealth.

    The real adapter may attach separate completeness and qualification evidence
    after validating the bound source. Neither implies the other, and missing
    evidence is never evidence of a cash strategy.
    These annotations affect reporting only, not contract selection or replay.
    """
    outcomes = result["outcomes"]
    by_key = {(r["decision_id"], r["arm"]): r for r in outcomes}

    def wealth_status(p: dict, row: dict | None) -> str:
        if not row:
            return "MISSING_ARM"
        if row.get("unresolved") or row.get("status") in {"OPEN", "UNRESOLVED"}:
            return "UNRESOLVED"
        if not finite(row.get("net_wealth")) or not finite(row.get("initial_cash"), positive=True):
            return "UNKNOWN_WEALTH"
        if row.get("status") == "CLOSED":
            return "KNOWN_WEALTH"
        if row.get("status") != "NOT_OPENED":
            return "UNKNOWN_ARM_STATUS"
        reason = row.get("reason")
        # These rejection reasons already require a valid decision/fill quote.
        if reason in {"ONE_CALL_OVER_BUDGET", "FILL_OVER_BUDGET"}:
            return "KNOWN_NO_TRADE"
        if row.get("arm") == "STOCK" and reason == "ZERO_QUANTITY":
            return "KNOWN_NO_TRADE"
        if (row.get("arm") == "LONG_CALL" and reason == "NO_ELIGIBLE_CONTRACT"
                and p.get("contract_universe_complete") is True
                and p.get("contract_universe_qualified") is True):
            return "KNOWN_NO_TRADE"
        if (reason in {"NO_EXECUTION_QUOTE", "ENTRY_SIZE_OR_BID"}
                and p.get("entry_window_complete_by_arm", {}).get(row["arm"]) is True
                and p.get("entry_window_qualified_by_arm", {}).get(row["arm"]) is True):
            return "KNOWN_NO_TRADE"
        return "DATA_NOT_IDENTIFIABLE"

    rows, intervals = [], []
    for population in ("RESOLVED_FILLED_ONLY", "ALL_VALID_OPPORTUNITIES", "DECISION_OPTION_ELIGIBLE"):
      members = [p for p in result["opportunities"] if p.get("valid_opportunity", True) and
                 (population != "DECISION_OPTION_ELIGIBLE" or p["eligible"])]
      member_dates = sorted({str(ts(p["decision_at"]).tz_convert('America/New_York').date()) for p in members})
      for arm in ("STOCK", "DECISION_DELTA_MATCHED_FUNDED_STOCK"):
        exclusions = {}
        for p in sorted(members, key=lambda p: p["decision_id"]):
            r, stock = by_key.get((p["decision_id"], "LONG_CALL")), by_key.get((p["decision_id"], arm))
            reason = None
            call_state, stock_state = wealth_status(p, r), wealth_status(p, stock)
            if "MISSING_ARM" in {call_state, stock_state}:
                reason = "MISSING_ARM"
            elif "UNRESOLVED" in {call_state, stock_state}:
                reason = "UNRESOLVED"
            elif arm != "STOCK" and not stock.get("delta_identifiable"):
                reason = "DELTA_NOT_IDENTIFIABLE"
            elif call_state not in {"KNOWN_WEALTH", "KNOWN_NO_TRADE"}:
                reason = call_state
            elif stock_state not in {"KNOWN_WEALTH", "KNOWN_NO_TRADE"}:
                reason = stock_state
            elif population == "RESOLVED_FILLED_ONLY" and (r["status"] != "CLOSED" or stock["status"] != "CLOSED"):
                reason = "NOT_BOTH_FILLED_AND_CLOSED"
            elif r["initial_cash"] != stock["initial_cash"]:
                reason = "CAPITAL_MISMATCH"
            if reason:
                exclusions[reason] = exclusions.get(reason, 0) + 1
                continue
            rows.append({"decision_id": r["decision_id"], "underlying_uid": r["underlying_uid"],
                         "date": str(ts(r["decision_at"]).tz_convert('America/New_York').date()),
                         "arm": arm, "population": population, "call_status": r["status"], "stock_status": stock["status"],
                         "call_wealth_status": call_state, "stock_wealth_status": stock_state,
                         "increment": (r["net_wealth"]-stock["net_wealth"])/r["initial_cash"],
                         "break_even_extra_call_cost_usd": r["net_wealth"]-stock["net_wealth"],
                         "evidence_grade": r["evidence_grade"]})
        subset = [r for r in rows if r["arm"] == arm and r["population"] == population]
        dates = sorted({r["date"] for r in subset})
        daily = {d: float(np.mean([r["increment"] for r in subset if r["date"] == d])) for d in dates}
        # Retain missing leading/trailing member dates too; the frozen minimum
        # remains 40 dates with observed pairs, never 40 merely planned dates.
        interval_daily = {d: daily.get(d, np.nan) for d in member_dates}
        interval = date_interval(interval_daily) if len(dates) >= 40 else None
        intervals.append({"arm": arm, "population": population, "opportunity_rows": len(members),
                          "paired_rows": len(subset), "unresolved_rows": exclusions.get("UNRESOLVED", 0),
                          "excluded_rows": sum(exclusions.values()), "exclusions": exclusions,
                          "decision_dates": len(dates), "population_decision_dates": len(member_dates),
                          "missing_decision_dates": len(set(member_dates) - set(dates)),
                          "underlying_uids": len({r["underlying_uid"] for r in subset}),
                          "mean_conditioning": "KNOWN_WEALTH_PAIRS_UNRESOLVED_NOT_IMPUTED",
                          "comparison_status": ("NOT_IDENTIFIABLE" if not subset else
                                                "CONDITIONAL_COMPUTABLE" if exclusions else "COMPUTABLE"),
                          "known_no_trade_pairs": sum(r["call_wealth_status"] == "KNOWN_NO_TRADE" or
                                                      r["stock_wealth_status"] == "KNOWN_NO_TRADE" for r in subset),
                          "mean_date_increment": float(np.mean(list(daily.values()))) if daily else None,
                          "exploratory_95_interval": interval, "interval_status": "AVAILABLE" if interval else "INSUFFICIENT_DATES"})
    primary = next(r for r in intervals if r["arm"] == "STOCK" and r["population"] == "ALL_VALID_OPPORTUNITIES")
    delta = next(r for r in intervals if r["arm"] == "DECISION_DELTA_MATCHED_FUNDED_STOCK"
                 and r["population"] == "ALL_VALID_OPPORTUNITIES")
    opportunities = result["opportunities"]
    nominal = result.get("nominal_opportunities", len(opportunities))
    require(type(nominal) is int and nominal >= len(opportunities), "INVALID_NOMINAL_POPULATION")
    grades = {p.get("evidence_grade") for p in opportunities} | {r.get("evidence_grade") for r in outcomes}
    grades.discard(None)
    real = grades == {"REAL_HISTORICAL_QUOTES"}
    complete = (nominal > 0 and result.get("acquisition_status") == "COMPLETE"
                and primary["paired_rows"] == nominal and len(opportunities) == nominal)
    main_status = ("NOT_IDENTIFIABLE" if not primary["paired_rows"] else
                   "DESCRIPTIVE_COMPLETE" if complete else "CONDITIONAL_COMPUTABLE")
    invalid_or_unacquired = nominal - primary["opportunity_rows"]
    data_missing = sum(n for reason, n in primary["exclusions"].items() if reason != "UNRESOLVED")
    call_outcomes = [r for r in outcomes if r["arm"] == "LONG_CALL"]
    no_trade = sum(wealth_status(p, by_key.get((p["decision_id"], "LONG_CALL"))) == "KNOWN_NO_TRADE"
                   for p in opportunities)
    return {"pairs": rows, "comparisons": intervals, "unresolved": sum(r["unresolved"] for r in outcomes),
            "nominal_opportunities": nominal, "evaluated_opportunities": len(opportunities),
            "invalid_or_unacquired_opportunities": invalid_or_unacquired,
            "data_unidentifiable_opportunities": invalid_or_unacquired + data_missing,
            "opened_calls": sum(bool(r.get("entry_at")) for r in call_outcomes),
            "closed_calls": sum(r["status"] == "CLOSED" for r in call_outcomes),
            "active_no_trade_calls": no_trade,
            "unresolved_call_positions": sum(r["unresolved"] for r in call_outcomes),
            "underlying_uids": len({r["underlying_uid"] for r in result["opportunities"]}),
            "eligible": sum(r["eligible"] for r in result["opportunities"]),
            "main_comparison_status": main_status,
            "full_population_status": "COMPLETE" if complete else "LIMITED",
            "delta_comparison_status": delta["comparison_status"],
            "evidence_grade": next(iter(grades)) if len(grades) == 1 else "MIXED_OR_UNKNOWN",
            "economic_verdict": "DESCRIPTIVE_COMPLETE" if real and complete else "NOT_IDENTIFIABLE",
            "production_acceptance": "NOT_ASSESSED", "effective_sample_size": "UNKNOWN",
            "selection_history": "INCOMPLETE", "nav": "NOT_RUN_NO_ACCOUNT_POLICY"}
