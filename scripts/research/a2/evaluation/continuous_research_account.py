"""Persistent research traces using the immutable common account engine.

Year/fold boundaries never reset accounts. Locked continuation replays one
frozen full prefix and checks its ledger identity before accepting test rows.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
import hashlib
import numpy as np
import pandas as pd
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays, TargetDecision, run_many
from scripts.v22.corporate_action_transition_r1 import CorporateActionTransitionAdapter, apply_transition_to_positions

TOL = 1e-10

@dataclass(frozen=True)
class PersistentPolicyContext:
    common: object
    holding_age: np.ndarray
    entry_date: np.ndarray
    entry_price: np.ndarray
    entry_execution_open: np.ndarray
    current_units: np.ndarray

    def __getattr__(self, name):
        return getattr(self.common, name)

def account_prefix_identity(replay, end, path_ids=None):
    end = pd.Timestamp(end)
    digest = hashlib.sha256()
    counts = {}
    wanted=None if path_ids is None else tuple(str(p) for p in path_ids)
    if wanted is not None and (not wanted or not set(wanted).issubset(replay.metadata['path_ids'])):
        raise ValueError('prefix path identity mismatch')
    for name, clock, keys in [
        ("daily", "date", ["date", "path_id"]),
        ("positions", "date", ["date", "path_id", "ticker"]),
        ("fills", "execution_date", ["execution_date", "path_id", "ticker", "side"]),
    ]:
        frame = getattr(replay, name)
        if wanted is not None:
            frame = frame.loc[frame.path_id.isin(wanted)]
        frame = frame.loc[pd.to_datetime(frame[clock]).le(end)].sort_values(keys,kind="stable").copy()
        semantic_columns = {
            "daily": ["path_id","date","cash","nav","certified_nav","gross_exposure","transaction_cost_amount","buy_notional","sell_notional","turnover","accounting_qualified"],
            "positions": ["path_id","date","ticker","index_units","mark","market_value","weight","holding_age","entry_date","entry_price","entry_execution_open","quantity_coordinate_factor","stale","unknown","accounting_qualified"],
            "fills": ["path_id","signal_date","execution_date","order_id","ticker","side","action","price","notional","index_units","index_units_before","index_units_after","transaction_cost","quantity_coordinate_factor"],
        }
        frame = frame.reindex(columns=semantic_columns[name])
        for col in frame.select_dtypes(include=["float"]).columns:
            frame[col] = frame[col].round(10)
        digest.update(name.encode())
        digest.update(frame.to_csv(index=False,float_format="%.10f",na_rep="NA").encode())
        counts[name] = len(frame)
    return {"end_session": str(end.date()), "sha256": digest.hexdigest(),
            "row_counts": counts, "comparison_precision_decimals": 10}

def run_continuous_account(
    market: MarketArrays, path_ids, policy, account_config: dict, *,
    corporate_actions=(), corporate_action_known_at=None, unsupported_events=(),
    previous_prefix=None, locked_evaluation_receipt=None, ledger_callback=None,
):
    """One fractional account per path across every supplied session.

    policy(local_session_index, PersistentPolicyContext) returns TargetDecision.
    Same-ticker, zero-cash source-backed share transforms reuse the common
    corporate-action transition function. Other events fail closed per ticker.
    Event availability and source coverage receipts are bound by the caller.
    """
    if (account_config.get("base_currency") != "USD"
        or account_config.get("fractional_shares") is not True
        or account_config.get("integer_share_rounding",False) is not False
        or account_config.get("cash_interest") != 0
        or account_config.get("transaction_cost_bps") != 0
        or account_config.get("financing") is not False
        or account_config.get("borrowed_cash",False) is not False
        or account_config.get("long_only") is not True):
        raise ValueError("R1 requires fractional USD, zero cost/interest, unfinanced long-only")
    capital = account_config["initial_nav"]
    if not np.isfinite(capital) or capital <= 0 or account_config.get("initial_cash",capital) != capital or account_config.get("initial_holdings",[]) != []:
        raise ValueError("new common account must start empty with task-config capital")
    if market.dates[0] < pd.Timestamp("2023-01-01"):
        raise ValueError("common initial state begins at the first legal 2023 execution point")
    if market.dates[-1] >= pd.Timestamp("2026-01-01"):
        if not locked_evaluation_receipt or locked_evaluation_receipt.get("status") != "FINALIST_FROZEN" or len(str(locked_evaluation_receipt.get("sha256",""))) != 64 or previous_prefix is None:
            raise ValueError("locked 2026 replay requires finalist freeze and pre-2026 prefix receipt")
        if market.dates[-1] >= pd.Timestamp("2027-01-01"):
            raise ValueError("test replay is restricted to 2026")
    ids = tuple(str(p) for p in path_ids)
    n, s = len(market.tickers), len(ids)
    ti = {str(t): i for i,t in enumerate(market.tickers)}
    di = {d: i for i,d in enumerate(market.dates)}
    factors = np.ones((len(market.dates),n))
    event_receipts = []
    known_at = corporate_action_known_at or {}
    exceptions = list(unsupported_events)
    corporate_actions = tuple(corporate_actions)
    CorporateActionTransitionAdapter(corporate_actions)  # Same source duplicate-event guard.
    for event in sorted(corporate_actions,key=lambda e:(e.effective_date,e.old_security_id)):
        day = pd.Timestamp(event.effective_date)
        if day > market.dates[-1] or event.old_ticker not in ti or day < market.dates[0]:
            continue
        open_at = (day+pd.Timedelta(hours=9,minutes=30)).tz_localize("America/New_York").tz_convert("UTC")
        available = pd.Timestamp(known_at.get(event.event_fingerprint,pd.NaT))
        supported = (event.old_ticker == event.new_ticker and event.cash_component_per_old_share == 0
                     and event.quantity_multiplier > 0 and event.repair_authorized
                     and bool(event.source_reference) and bool(event.source_fingerprint)
                     and not pd.isna(available) and available.tzinfo is not None and available <= open_at)
        if not supported:
            exceptions.append({"ticker":event.old_ticker,"effective_date":str(day.date()),
                               "reason":"UNSUPPORTED_OR_UNAVAILABLE_CORPORATE_ACTION",
                               "source_reference":event.source_reference,
                               "source_fingerprint":event.source_fingerprint})
            continue
        converted,cash,record = apply_transition_to_positions(event,{event.old_ticker:1.},0.,day)
        if cash != 0 or set(converted) != {event.old_ticker}:
            raise ValueError("share-only coordinate transform cannot alter cash or ticker")
        multiplier = converted[event.old_ticker]
        factors[market.dates >= day,ti[event.old_ticker]] *= multiplier
        event_receipts.append({**record,"known_at":str(available),"research_coordinate_multiplier":multiplier})
    quality = market.quality.copy()
    exception_by_ticker = {}
    for event in exceptions:
        if str(event["ticker"]) not in ti:
            continue
        day = pd.Timestamp(event["effective_date"])
        if day > market.dates[-1]:
            continue
        c = ti[str(event["ticker"])]
        quality[market.dates == day,c] = True
        exception_by_ticker.setdefault(c,[]).append(event)
    common_market = replace(market,open=market.open*factors,close=market.close*factors,
                            quality=quality,initial_marks=market.initial_marks.copy())
    entry_index = np.full((s,n),-1,dtype=int)
    entry_date = np.full((s,n),np.datetime64("NaT","ns"),dtype="datetime64[ns]")
    entry_price = np.full((s,n),np.nan)
    entry_factor = np.ones((s,n))
    current_units = np.zeros((s,n))
    enriched = {}
    accounting_exceptions = []
    reported_exceptions = set()
    invalid_paths = np.zeros(s,dtype=bool)
    path_index = {p:i for i,p in enumerate(ids)}
    def callback(name,frame):
        out = frame.copy()
        if name == "fills":
            ii = np.asarray([di[pd.Timestamp(d)] for d in out.execution_date],int)
            cc = np.asarray([ti[str(t)] for t in out.ticker],int)
            scale = factors[ii,cc]
            for col in ["price","index_units","index_units_before","index_units_after"]:
                out["engine_"+col] = out[col]
            out["price"] = market.open[ii,cc]
            for col in ["index_units","index_units_before","index_units_after"]:
                out[col] *= scale
            out["fractional_shares"] = out.index_units
            out["quantity_coordinate_factor"] = scale
            if not np.allclose(out.price*out.index_units,out.notional,rtol=1e-12,atol=1e-8):
                raise AssertionError("raw Open/quantity/notional translation mismatch")
            for row,j,c in zip(out.itertuples(),ii,cc):
                r = path_index[str(row.path_id)]
                current_units[r,c] = row.engine_index_units_after
                if row.side == "BUY" and row.engine_index_units_before <= TOL:
                    entry_index[r,c] = j; entry_date[r,c] = market.dates[j].to_datetime64(); entry_price[r,c] = row.price;entry_factor[r,c] = factors[j,c]
                if row.side == "SELL" and row.engine_index_units_after <= TOL:
                    entry_index[r,c] = -1;entry_date[r,c] = np.datetime64("NaT","ns");entry_price[r,c] = np.nan
        elif name == "positions":
            ii = np.asarray([di[pd.Timestamp(d)] for d in out.date],int)
            cc = np.asarray([ti[str(t)] for t in out.ticker],int)
            rr = np.asarray([path_index[str(p)] for p in out.path_id],int)
            out["engine_index_units"] = out.index_units;out["engine_mark"] = out.mark
            out["index_units"] *= factors[ii,cc];out["mark"] /= factors[ii,cc]
            out["fractional_shares"] = out.index_units;out["quantity_coordinate_factor"] = factors[ii,cc]
            out["holding_age"] = ii-entry_index[rr,cc]
            out["entry_date"] = entry_date[rr,cc]
            out["entry_execution_open"] = entry_price[rr,cc]
            out["entry_price"] = entry_price[rr,cc]*entry_factor[rr,cc]/factors[ii,cc]
            out["accounting_qualified"] = ~invalid_paths[rr]
        elif name == "orders":
            jj = np.asarray([di[pd.Timestamp(d)] for d in out.signal_date],int)
            cc = np.asarray([ti[str(t)] for t in out.ticker],int)
            for col in ["current_units","hold_units"]:
                out["engine_"+col] = out[col];out[col] *= factors[jj,cc]
        elif name == "execution_results":
            scale=[factors[di[pd.Timestamp(date)],ti[str(ticker)]] if not pd.isna(date) else 1.
                   for date,ticker in zip(out.execution_date,out.ticker)]
            out["engine_index_units"] = out.index_units;out["index_units"] *= np.asarray(scale)
        elif name == "daily":
            for row in out.itertuples():
                r = path_index[str(row.path_id)]
                for c,events in exception_by_ticker.items():
                    for event in events:
                        key = (r,c,str(event["effective_date"]))
                        if pd.Timestamp(event["effective_date"]) == row.date and current_units[r,c] > TOL and key not in reported_exceptions:
                            accounting_exceptions.append({"path_id":ids[r],**event,
                                "first_affected_session":str(row.date.date()),"nav_valid":False})
                            reported_exceptions.add(key)
                            invalid_paths[r] = True
            rr = np.asarray([path_index[str(p)] for p in out.path_id],int)
            out["engine_certified_nav"] = out.certified_nav
            out["accounting_qualified"] = ~invalid_paths[rr]
            out.loc[invalid_paths[rr],"certified_nav"] = np.nan
            out.loc[invalid_paths[rr],"net_return"] = np.nan
        if name in {"daily","fills","positions","orders","execution_results"}:
            enriched.setdefault(name,[]).append(out)
        if ledger_callback is not None:
            ledger_callback(name,out)
    def wrapped(j,context):
        age=np.where(entry_index >= 0,j-entry_index,-1)
        result=policy(j,PersistentPolicyContext(context,age.copy(),entry_date.copy(),
                      entry_price*entry_factor/factors[j][None,:],entry_price.copy(),context.current_units*factors[j][None,:]))
        if not isinstance(result,TargetDecision):
            raise ValueError("policy must return the existing TargetDecision")
        return result
    replay=run_many(common_market,ids,wrapped,initial_cash=capital,cost_bps=account_config["transaction_cost_bps"],
                    max_weight=account_config["max_weight"],max_positions=account_config["max_positions"],
                    max_invested=account_config["max_invested"],capacity_fraction=account_config.get("capacity_fraction"),
                    ledger_callback=callback)
    for name,chunks in enriched.items():
        setattr(replay,name,pd.concat(chunks,ignore_index=True))
    replay.accounting_exceptions=pd.DataFrame(accounting_exceptions)
    replay.final_state={"cash":replay.final_cash.copy(),"engine_units":replay.final_units.copy(),
                        "fractional_shares":replay.final_units*factors[-1][None,:],
                        "holding_age":np.where(entry_index>=0,len(market.dates)-1-entry_index,-1),
                        "entry_date":entry_date.copy(),"entry_price":entry_price*entry_factor/factors[-1][None,:],
                        "entry_execution_open":entry_price.copy(),
                        "last_session":str(market.dates[-1].date()),"accounting_qualified":~invalid_paths.copy()}
    if previous_prefix is not None and account_prefix_identity(replay,previous_prefix["end_session"]) != previous_prefix:
        raise AssertionError("locked continuation changed frozen pre-2026 account prefix")
    replay.prefix_identity=account_prefix_identity(replay,min(market.dates[-1],pd.Timestamp("2025-12-31")))
    replay.metadata.update(unit="fractional raw-share research coordinate; engine coordinates retained explicitly",
        account_config=dict(account_config),continuous_account=True,annual_reset=False,
        corporate_action_transition_source="scripts/v22/corporate_action_transition_r1.py",
        corporate_action_receipts=event_receipts,corporate_action_exceptions=exceptions,
        raw_open_fill_translation=True,live_official_auction_certification=False,
        pending_continuation_mode="frozen full-prefix replay and identity comparison",
        holding_age_semantics="sessions since first actual Open fill of current holding spell",
        entry_price_semantics="first fill translated to current share basis; entry_execution_open retains original raw receipt",
        accounting_exception_count=len(accounting_exceptions),
        unsupported_event_semantics="only effective session quote blocked; affected pre-existing held account stays unqualified; later first buys unaffected")
    return replay
