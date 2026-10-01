"""NumPy batched implementation of the common holding-aware v2 account rules.

An account is one row, and all state (units, cash, pending orders) is per row.
Policy receives SIGNAL-CLOSE information only. Orders execute at the next
session's OPEN, sells before buys, and missing decisions preserve exact units.
Sparse orders include every held name, positive target and operational exit;
unheld explicit-zero decisions are losslessly reconstructed from the saved
common input keys plus sparse targets (they create no account action).
All prices/units are research price-index coordinates, not shareholder shares.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
import numpy as np
import pandas as pd

TOL = 1e-10


@dataclass
class OperationalEvidence:
    reason: str
    known_at: Any
    source_id: str


@dataclass
class MarketArrays:
    dates: Any
    tickers: Any
    open: np.ndarray
    close: np.ndarray
    quality: np.ndarray | None = None
    adv: np.ndarray | None = None
    input_present: np.ndarray | None = None
    new_buy_eligible: np.ndarray | None = None
    signal_mask: np.ndarray | None = None
    signal_asof: Any = None
    operational_exits: dict[Any, dict[str, OperationalEvidence]] = field(default_factory=dict)
    buy_restricted: np.ndarray | None = None
    sell_restricted: np.ndarray | None = None
    initial_marks: np.ndarray | None = None
    known_restrictions_evidence: Any = None
    row_present: np.ndarray | None = None
    initial_mark_dates: Any = None

    def __post_init__(self):
        self.dates = pd.DatetimeIndex(pd.to_datetime(self.dates))
        self.tickers = np.asarray(self.tickers,dtype=str)
        if self.dates.empty or self.dates.tz is not None or self.dates.hasnans or self.dates.has_duplicates or not self.dates.is_monotonic_increasing or not self.dates.equals(self.dates.normalize()):
            raise ValueError("dates must be unique increasing naive session labels")
        if len(set(self.tickers)) != len(self.tickers) or any(not x.strip() for x in self.tickers):
            raise ValueError("invalid ticker universe")
        shape = (len(self.dates),len(self.tickers))
        self.open = np.asarray(self.open,dtype=np.float64)
        self.close = np.asarray(self.close,dtype=np.float64)
        if self.open.shape != shape or self.close.shape != shape:
            raise ValueError("market price shape must be [date,ticker]")
        supplied_restrictions={name:getattr(self,name) is not None for name in ["buy_restricted","sell_restricted"]}
        for name,default,dtype in [("quality",False,bool),("adv",np.nan,float),("input_present",True,bool),("row_present",True,bool),
                                   ("new_buy_eligible",True,bool),("buy_restricted",False,bool),("sell_restricted",False,bool)]:
            value = getattr(self,name)
            value = np.full(shape,default,dtype=dtype) if value is None else np.asarray(value,dtype=dtype)
            if value.shape != shape:
                raise ValueError(f"invalid market {name} shape")
            setattr(self,name,value)
        self.signal_mask = np.ones(len(self.dates),dtype=bool) if self.signal_mask is None else np.asarray(self.signal_mask,dtype=bool)
        if self.signal_mask.shape != (len(self.dates),):
            raise ValueError("signal_mask shape")
        if self.signal_asof is None:
            self.signal_asof = list(self.dates)
        elif isinstance(self.signal_asof,dict):
            self.signal_asof = [pd.Timestamp(self.signal_asof.get(d,d)) for d in self.dates]
        else:
            self.signal_asof = [pd.Timestamp(d) for d in self.signal_asof]
        if len(self.signal_asof)!=len(self.dates) or any(pd.isna(a) or a.date()!=d.date() for a,d in zip(self.signal_asof,self.dates)):
            raise ValueError("signal_asof must match session date")
        self.initial_marks = np.full(len(self.tickers),np.nan) if self.initial_marks is None else np.asarray(self.initial_marks,dtype=np.float64)
        if self.initial_marks.shape != (len(self.tickers),):
            raise ValueError("initial_marks shape")
        self.operational_exits = {pd.Timestamp(d):actions for d,actions in self.operational_exits.items()}
        if (self.buy_restricted.any() or self.sell_restricted.any()) and self.known_restrictions_evidence is None:
            raise ValueError("known restrictions require separately saved dated source evidence")
        if self.known_restrictions_evidence is not None:
            evidence=pd.DataFrame(self.known_restrictions_evidence).copy()
            required={"signal_date","ticker","known_at","source_id","reason"}
            if not required.issubset(evidence.columns):
                raise ValueError("known restrictions require signal_date/ticker/known_at/source_id/reason")
            proven={name:np.zeros(shape,dtype=bool) for name in supplied_restrictions}
            date_lookup={d:i for i,d in enumerate(self.dates)}
            ticker_lookup={str(t):i for i,t in enumerate(self.tickers)}
            for row in evidence.to_dict("records"):
                day=pd.Timestamp(row["signal_date"])
                if day not in date_lookup or str(row["ticker"]) not in ticker_lookup:
                    raise ValueError("restriction evidence outside market date/ticker keys")
                di,ti=date_lookup[day],ticker_lookup[str(row["ticker"])]
                known=pd.Timestamp(row["known_at"]);asof=pd.Timestamp(self.signal_asof[di])
                if pd.isna(known) or known.tzinfo!=asof.tzinfo or known>asof or any(pd.isna(row[c]) or not str(row[c]).strip() for c in ["source_id","reason"]):
                    raise ValueError("restriction evidence future/unsourced")
                for name in proven:
                    value=row.get(name,False)
                    if pd.isna(value):raise ValueError("restriction boolean missing")
                    proven[name][di,ti]|=bool(value)
            for name in proven:
                if supplied_restrictions[name] and not np.array_equal(getattr(self,name),proven[name]):
                    raise ValueError("restriction mask is not exactly supported by dated evidence")
                setattr(self,name,proven[name])
        self.initial_mark_dates=np.full(len(self.tickers),np.datetime64("NaT"),dtype="datetime64[ns]") if self.initial_mark_dates is None else np.asarray(self.initial_mark_dates,dtype="datetime64[ns]")
        if self.initial_mark_dates.shape!=(len(self.tickers),) or np.any(self.initial_mark_dates>=self.dates[0].to_datetime64()):
            raise ValueError("initial trusted marks must precede first session")


@dataclass(frozen=True)
class AccountContext:
    signal_index: int
    signal_date: pd.Timestamp
    signal_asof: pd.Timestamp
    path_ids: tuple[str,...]
    tickers: np.ndarray
    current_units: np.ndarray
    current_weights: np.ndarray
    cash: np.ndarray
    cash_weight: np.ndarray
    nav: np.ndarray
    reserved_mask: np.ndarray
    reserved_weight: np.ndarray
    reserved_slots: np.ndarray
    available_budget: np.ndarray
    available_slots: np.ndarray
    buy_allowed: np.ndarray
    sell_restricted: np.ndarray
    input_present: np.ndarray
    decision_mask: np.ndarray
    operational_mask: np.ndarray
    max_positions: int
    max_weight: float
    max_invested: float

    @property
    def available_weight(self):
        return self.available_budget


@dataclass
class TargetDecision:
    weights: np.ndarray
    explicit_mask: np.ndarray | None = None
    raw_evidence_id: Any = None


@dataclass
class BatchReplay:
    daily: pd.DataFrame
    positions: pd.DataFrame
    orders: pd.DataFrame
    fills: pd.DataFrame
    execution_results: pd.DataFrame
    contexts: pd.DataFrame
    operational_actions: pd.DataFrame
    metadata: dict
    audit: dict
    final_units: np.ndarray
    final_cash: np.ndarray

    @property
    def trades(self):
        return self.fills

    @property
    def target_decisions(self):
        return self.orders


def _positive(x):
    return np.isfinite(x) & (x>0)


def _take_frame(chunks,columns):
    if not chunks:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame({key:np.concatenate([chunk[key] for chunk in chunks]) for key in columns})


def run_many(market: MarketArrays, path_ids, policy: Callable,
             *, initial_cash=1_000_000.0, initial_units=None, cost_bps=10.0,
             max_weight=0.10,max_positions=20,max_invested=0.95,
             capacity_fraction=0.01,capacity_on_sells=False,collect_ledgers=True,
             ledger_callback=None):
    """Replay S independent accounts with one vectorized policy call per signal.

    ``policy(signal_index, context) -> TargetDecision``. Targets use full ticker
    coordinates [S,N]. False explicit_mask means NO MODEL DECISION, hence held
    units are preserved. The mask may not include unavailable decision inputs.
    ``ledger_callback(name, dataframe)`` streams chunks instead of collecting
    them, so caller can use ParquetWriter without retaining years of ledgers.
    Initial units can be [N] (broadcast) or [S,N]; zero cash cannot fund buys.
    """
    ids = tuple(str(p) for p in path_ids)
    if not ids or len(set(ids))!=len(ids):
        raise ValueError("unique nonempty path_ids required")
    if not np.isfinite(cost_bps) or not 0<=cost_bps<10000 or not 0<max_weight<=1 or not 0<max_invested<=1 or max_positions<1:
        raise ValueError("invalid common account limits")
    if capacity_fraction is not None and not 0<capacity_fraction<=1:
        raise ValueError("invalid capacity fraction")
    s,n = len(ids),len(market.tickers)
    cash = np.broadcast_to(np.asarray(initial_cash,dtype=np.float64),(s,)).copy()
    units = np.zeros((s,n)) if initial_units is None else np.broadcast_to(np.asarray(initial_units,dtype=np.float64),(s,n)).copy()
    if not np.isfinite(cash).all() or (cash<0).any() or not np.isfinite(units).all() or (units<0).any() or (np.count_nonzero(units>TOL,axis=1)>max_positions).any():
        raise ValueError("invalid independent initial accounts")
    if ((cash==0)&~(units>TOL).any(axis=1)).any():
        raise ValueError("empty initial account")
    rate=cost_bps/10000.0
    marks=np.broadcast_to(market.initial_marks,(s,n)).copy()
    mark_day=np.full((s,n),-1,dtype=np.int32)
    mark_source=np.where(_positive(marks),"close","unknown").astype("U7")
    ticker_rank=np.argsort(np.argsort(market.tickers,kind="stable"),kind="stable")
    ticker_keys=np.broadcast_to(ticker_rank,(s,n))
    last_adv=np.full(n,np.nan)
    id_array=np.asarray(ids,dtype=object)
    ticker_array=np.asarray(market.tickers,dtype=object)
    chunks={name:[] for name in ["daily","positions","orders","fills","execution_results","contexts","operational_actions"]}
    previous_nav=np.full(s,np.nan);previous_certified=np.full(s,np.nan)
    audit=dict(cash_identity_error_max=0.0,cost_identity_error_max=0.0,self_finance_error_max=0.0,
               nav_identity_error_max=0.0,max_actual_names=0,minimum_cash=float(cash.min()),
               next_open_violations=0,capacity_violations=0)
    pending=None
    ticker_lookup={str(t):j for j,t in enumerate(market.tickers)}
    decision_label_cache={}

    def emit(name,data):
        if not data or len(next(iter(data.values())))==0:
            return
        if ledger_callback is not None:
            ledger_callback(name,pd.DataFrame(data))
        if collect_ledgers:
            chunks[name].append(data)

    def linked(ri,ci,signal_index,execution_index):
        if signal_index not in decision_label_cache:
            day_label=str(market.dates[signal_index].date())
            decision_label_cache[signal_index]=np.asarray([f"{p}|{day_label}" for p in ids],dtype=object)
        decision=decision_label_cache[signal_index][ri]
        return dict(path_id=id_array[ri],signal_date=np.repeat(market.dates[signal_index].to_datetime64(),len(ri)),
                    execution_date=np.repeat(market.dates[execution_index].to_datetime64() if execution_index is not None else np.datetime64("NaT","ns"),len(ri)),
                    decision_id=decision,order_id=np.asarray([f"{d}|{market.tickers[c]}" for d,c in zip(decision,ci)],dtype=object),
                    ticker=ticker_array[ci])

    def outcomes(mask,signal_i,exec_i,status,reason,side="NONE",notional=None,quantity=None,cost=None):
        ri,ci=np.nonzero(mask)
        if len(ri)==0:
            return
        def value(v,default):
            return np.full(len(ri),default) if v is None else v[ri,ci]
        data=linked(ri,ci,signal_i,exec_i)
        data.update(status=np.full(len(ri),status,dtype=object),reason=np.full(len(ri),reason,dtype=object),
                    side=np.full(len(ri),side,dtype=object),notional=value(notional,0.0),index_units=value(quantity,0.0),
                    transaction_cost=value(cost,0.0),decision_semantic=pending["semantics"][ri,ci],order_type=pending["kinds"][ri,ci],
                    execution_semantic=np.full(len(ri),"EXECUTION_REJECTED" if status=="REJECTED" else status,dtype=object))
        emit("execution_results",data)

    for di,date in enumerate(market.dates):
        # Updating same-day ADV here cannot leak: execution uses prior pending's
        # frozen ADV snapshot, just as engine_v2 does.
        known_adv=market.input_present[di]&_positive(market.adv[di])
        last_adv[known_adv]=market.adv[di,known_adv]
        valid_open=_positive(market.open[di])&~market.quality[di]&market.row_present[di]
        valid_close=_positive(market.close[di])&~market.quality[di]&market.row_present[di]
        held=units>TOL
        marks=np.where(held&valid_open[None,:],market.open[di][None,:],marks)
        mark_day=np.where(held&valid_open[None,:],di,mark_day)
        mark_source=np.where(held&valid_open[None,:],"open",mark_source)
        opening=np.where(valid_open[None,:],market.open[di][None,:],marks)
        unknown_open=held&~_positive(opening)
        open_stale_count=(held&~valid_open[None,:]&_positive(opening)).sum(axis=1)
        pre_nav=cash+np.sum(np.where(held,units*np.where(_positive(opening),opening,0.0),0.0),axis=1)
        pre_nav[unknown_open.any(axis=1)]=np.nan
        cash_before=cash.copy()
        fees=np.zeros(s);buys=np.zeros(s);sells=np.zeros(s);blocked=np.zeros(s,dtype=np.int32)
        buy_scale=np.ones(s)
        executed_signal=np.full(s,np.datetime64("NaT"),dtype="datetime64[ns]")
        if pending is not None:
            pi=pending["signal_index"]
            executed_signal[:]=market.dates[pi].to_datetime64()
            active_nav=_positive(pre_nav)
            order_mask=pending["order_mask"]
            keep=pending["keep"]&order_mask
            outcomes(keep,pi,di,"PRESERVED_UNITS","MODEL_NO_DECISION_OR_SIGNAL_RESERVATION")
            unknown_reject=order_mask&~keep&~active_nav[:,None]
            outcomes(unknown_reject,pi,di,"REJECTED","UNKNOWN_NAV")
            blocked+=unknown_reject.sum(axis=1)
            active=order_mask&~keep&active_nav[:,None]
            wanted=pending["weights"]*np.nan_to_num(pre_nav,nan=0.0)[:,None]
            current_value=np.where(held,units*np.where(_positive(opening),opening,0.0),0.0)
            requested_sell=np.maximum(current_value-wanted,0.0)
            sell_mask=active&(requested_sell>TOL)
            restricted_sell=sell_mask&pending["sell_restricted"]
            outcomes(restricted_sell,pi,di,"REJECTED","SIGNAL_KNOWN_SELL_RESTRICTION","SELL")
            blocked+=restricted_sell.sum(axis=1)
            missing_sell=sell_mask&~pending["sell_restricted"]&~valid_open[None,:]
            for reason,condition in [("MISSING_PRICE_ROW",~market.row_present[di]),("PRICE_QUALITY_UNCERTIFIED",market.row_present[di]&market.quality[di]),("MISSING_OR_INVALID_OPEN",market.row_present[di]&~market.quality[di])]:
                mask=missing_sell&condition[None,:]
                outcomes(mask,pi,di,"REJECTED",reason,"SELL")
            blocked+=missing_sell.sum(axis=1)
            fill_sell=sell_mask&~pending["sell_restricted"]&valid_open[None,:]
            sell_amount=np.where(fill_sell,requested_sell,0.0)
            if capacity_fraction is not None and capacity_on_sells:
                adv=np.where(_positive(pending["adv"]),pending["adv"],pending["last_adv"])
                cap=np.where(_positive(adv),adv*capacity_fraction,np.inf)
                sell_amount=np.minimum(sell_amount,cap[None,:])
            sell_quantity=np.minimum(units,np.divide(sell_amount,market.open[di][None,:],out=np.zeros_like(units),where=valid_open[None,:]))
            sell_amount=sell_quantity*np.where(valid_open[None,:],market.open[di][None,:],0.0)
            sell_cost=sell_amount*rate
            before=units.copy()
            units-=sell_quantity
            units[units<=TOL]=0.0
            cash+=np.sum(sell_amount-sell_cost,axis=1)
            sells+=sell_amount.sum(axis=1);fees+=sell_cost.sum(axis=1)
            sold=sell_amount>TOL
            ri,ci=np.nonzero(sold)
            if len(ri):
                data=linked(ri,ci,pi,di)
                data.update(side=np.full(len(ri),"SELL",dtype=object),action=np.where(units[ri,ci]<=TOL,"EXIT","REDUCE"),
                            price=market.open[di,ci],notional=sell_amount[ri,ci],index_units=sell_quantity[ri,ci],
                            index_units_before=before[ri,ci],index_units_after=units[ri,ci],transaction_cost=sell_cost[ri,ci],
                            cost_bps=np.full(len(ri),cost_bps),pretrade_nav=pre_nav[ri],signal_day_adv=pending["adv"][ci],
                            decision_semantic=pending["semantics"][ri,ci],requested_notional=requested_sell[ri,ci],
                            partial_fill=sell_amount[ri,ci]<requested_sell[ri,ci]-TOL,capacity_limited=sell_amount[ri,ci]<requested_sell[ri,ci]-TOL,cash_limited=np.zeros(len(ri),dtype=bool))
                emit("fills",data)
                outcomes(sold,pi,di,"FILLED","ACTUAL_FILL","SELL",sell_amount,sell_quantity,sell_cost)
            partial=sold&(sell_amount<requested_sell-TOL)
            outcomes(partial,pi,di,"PARTIALLY_FILLED","SELL_CAPACITY_LIMIT","SELL")
            held=units>TOL
            current_value=np.where(held,units*np.where(_positive(opening),opening,0.0),0.0)
            requested_buy=np.maximum(wanted-current_value,0.0)
            buy_mask=active&(requested_buy>TOL)
            ineligible=buy_mask&~pending["buy_allowed"]
            outcomes(ineligible,pi,di,"REJECTED","SIGNAL_BUY_INELIGIBLE","BUY")
            blocked+=ineligible.sum(axis=1)
            missing_buy=buy_mask&pending["buy_allowed"]&~valid_open[None,:]
            for reason,condition in [("MISSING_PRICE_ROW",~market.row_present[di]),("PRICE_QUALITY_UNCERTIFIED",market.row_present[di]&market.quality[di]),("MISSING_OR_INVALID_OPEN",market.row_present[di]&~market.quality[di])]:
                mask=missing_buy&condition[None,:]
                outcomes(mask,pi,di,"REJECTED",reason,"BUY")
            blocked+=missing_buy.sum(axis=1)
            candidate_buy=buy_mask&pending["buy_allowed"]&valid_open[None,:]
            amount=np.where(candidate_buy,requested_buy,0.0)
            if capacity_fraction is not None:
                adv_cap=np.where(_positive(pending["adv"]),pending["adv"]*capacity_fraction,0.0)
                amount=np.minimum(amount,adv_cap[None,:])
            # Same stable descending target-weight then ticker order as common
            # engine. Reserving accepted new names precedes cash scaling.
            order=np.lexsort((ticker_keys,-pending["weights"]),axis=1)
            sorted_amount=np.take_along_axis(amount,order,axis=1)
            sorted_candidate=np.take_along_axis(candidate_buy,order,axis=1)
            sorted_new=~np.take_along_axis(held,order,axis=1)
            remaining=max_positions-held.sum(axis=1)
            # Missing ADV names do not consume a name, unless a full account
            # rejects them first. Equivalent to the original sequential loop.
            accepted_new=(sorted_amount>TOL)&sorted_new
            before_new=np.cumsum(accepted_new,axis=1)-accepted_new
            name_failure=sorted_candidate&sorted_new&(before_new>=remaining[:,None])
            failure=np.zeros_like(name_failure)
            np.put_along_axis(failure,order,name_failure,axis=1)
            outcomes(failure,pi,di,"REJECTED","LIVE_POSITION_LIMIT","BUY")
            blocked+=failure.sum(axis=1)
            amount[failure]=0.0
            capacity_limited=candidate_buy&~failure&(amount<requested_buy-TOL)
            no_adv=candidate_buy&~failure&(amount<=TOL)
            outcomes(no_adv,pi,di,"REJECTED","MISSING_SIGNAL_ADV","BUY")
            blocked+=no_adv.sum(axis=1)
            required=amount.sum(axis=1)*(1+rate)
            buy_scale=np.minimum(1.0,np.divide(np.maximum(cash,0.0),required,out=np.ones(s),where=required>0))
            amount*=buy_scale[:,None]
            insufficient=candidate_buy&~failure&~no_adv&(amount<=TOL)
            outcomes(insufficient,pi,di,"REJECTED","INSUFFICIENT_CASH","BUY")
            blocked+=insufficient.sum(axis=1)
            amount[amount<=TOL]=0.0
            quantity=np.divide(amount,market.open[di][None,:],out=np.zeros_like(units),where=valid_open[None,:])
            cost=amount*rate
            before=units.copy()
            units+=quantity
            cash-=np.sum(amount+cost,axis=1)
            buys+=amount.sum(axis=1);fees+=cost.sum(axis=1)
            purchased=amount>TOL
            marks=np.where(purchased,market.open[di][None,:],marks)
            mark_day=np.where(purchased,di,mark_day)
            mark_source=np.where(purchased,"open",mark_source)
            ri,ci=np.nonzero(purchased)
            if len(ri):
                data=linked(ri,ci,pi,di)
                data.update(side=np.full(len(ri),"BUY",dtype=object),action=np.where(before[ri,ci]<=TOL,"BUY","INCREASE"),
                            price=market.open[di,ci],notional=amount[ri,ci],index_units=quantity[ri,ci],
                            index_units_before=before[ri,ci],index_units_after=units[ri,ci],transaction_cost=cost[ri,ci],
                            cost_bps=np.full(len(ri),cost_bps),pretrade_nav=pre_nav[ri],signal_day_adv=pending["adv"][ci],
                            decision_semantic=pending["semantics"][ri,ci],requested_notional=requested_buy[ri,ci],
                            partial_fill=amount[ri,ci]<requested_buy[ri,ci]-TOL,capacity_limited=capacity_limited[ri,ci],cash_limited=buy_scale[ri]<1.0)
                emit("fills",data)
                outcomes(purchased,pi,di,"FILLED","ACTUAL_FILL","BUY",amount,quantity,cost)
                if capacity_fraction is not None:
                    audit["capacity_violations"]+=int(np.count_nonzero(amount[ri,ci]>capacity_fraction*pending["adv"][ci]+1e-7))
            # Explicit zero unheld names are absent from sparse order_mask.
            no_action=active&~sell_mask&~buy_mask
            outcomes(no_action,pi,di,"NO_ACTION","TARGET_ALREADY_MET_OR_NO_POSITION")
            audit["next_open_violations"]+=int(di!=pi+1)
            pending=None
        if (cash < -max(TOL,float(np.max(np.broadcast_to(initial_cash,(s,))))*1e-12)).any() or (np.count_nonzero(units>TOL,axis=1)>max_positions).any():
            raise AssertionError("common cash/actual name invariant")
        cash=np.maximum(cash,0.0)
        held=units>TOL
        open_after=cash+np.sum(np.where(held,units*np.where(_positive(opening),opening,0.0),0.0),axis=1)
        open_after[unknown_open.any(axis=1)]=np.nan
        marks=np.where(held&valid_close[None,:],market.close[di][None,:],marks)
        mark_day=np.where(held&valid_close[None,:],di,mark_day)
        mark_source=np.where(held&valid_close[None,:],"close",mark_source)
        unknown=held&~_positive(marks)
        stale=held&~valid_close[None,:]&~unknown
        values=np.where(held,units*np.where(_positive(marks),marks,0.0),0.0)
        nav=cash+values.sum(axis=1)
        nav[unknown.any(axis=1)]=np.nan
        certified=nav.copy();certified[(unknown|stale).any(axis=1)]=np.nan
        weights=np.divide(values,nav[:,None],out=np.zeros_like(units),where=_positive(nav)[:,None])
        weights[unknown.any(axis=1)]=np.nan
        cash_weight=np.divide(cash,nav,out=np.full(s,np.nan),where=_positive(nav))
        nav_error=np.where(_positive(nav),nav-cash-values.sum(axis=1),np.nan)
        cash_error=cash-cash_before-(sells-buys-fees)
        cost_error=fees-(sells+buys)*rate
        self_error=np.where(np.isfinite(open_after)&np.isfinite(pre_nav),open_after-pre_nav+fees,np.nan)
        for key,array in [("nav_identity_error_max",nav_error),("cash_identity_error_max",cash_error),
                          ("cost_identity_error_max",cost_error),("self_finance_error_max",self_error)]:
            finite=array[np.isfinite(array)]
            if len(finite):audit[key]=max(audit[key],float(np.max(np.abs(finite))))
        audit["max_actual_names"]=max(audit["max_actual_names"],int(held.sum(axis=1).max()))
        audit["minimum_cash"]=min(audit["minimum_cash"],float(cash.min()))
        data=dict(path_id=id_array.copy(),date=np.repeat(date.to_datetime64(),s),execution_date=np.repeat(date.to_datetime64(),s),signal_date=executed_signal,
                  cash=cash.copy(),nav=nav,certified_nav=certified,valuation_status=np.where(unknown.any(axis=1),"unknown",np.where(stale.any(axis=1),"stale","certified")),
                  pretrade_nav=pre_nav,open_posttrade_nav=open_after,known_position_value=values.sum(axis=1),
                  stale_count=stale.sum(axis=1),unknown_count=unknown.sum(axis=1),actual_name_count=held.sum(axis=1),
                  open_stale_count=open_stale_count,open_unknown_count=unknown_open.sum(axis=1),
                  cash_weight=cash_weight,gross_exposure=np.divide(values.sum(axis=1),nav,out=np.full(s,np.nan),where=_positive(nav)),
                  net_return=np.divide(certified,previous_certified,out=np.full(s,np.nan),where=_positive(previous_certified)&_positive(certified))-1,
                  indicative_return=np.divide(nav,previous_nav,out=np.full(s,np.nan),where=_positive(previous_nav)&_positive(nav))-1,
                  transaction_cost_amount=fees,buy_notional=buys,sell_notional=sells,traded_notional=buys+sells,
                  turnover=np.divide(0.5*(buys+sells),pre_nav,out=np.full(s,np.nan),where=_positive(pre_nav)),
                  buy_cash_scale=buy_scale,blocked_order_count=blocked,nav_identity_error=nav_error,
                  cash_flow_identity_error=cash_error,cost_identity_error=cost_error,open_self_finance_error=self_error)
        emit("daily",data)
        ri,ci=np.nonzero(held)
        if len(ri):
            data=dict(path_id=id_array[ri],date=np.repeat(date.to_datetime64(),len(ri)),ticker=ticker_array[ci],index_units=units[ri,ci].copy(),
                      mark=marks[ri,ci],mark_date=np.asarray([market.dates[j].to_datetime64() if j>=0 else market.initial_mark_dates[c] for j,c in zip(mark_day[ri,ci],ci)]),mark_source=mark_source[ri,ci],
                      market_value=np.where(unknown[ri,ci],np.nan,values[ri,ci]),weight=weights[ri,ci],stale=stale[ri,ci],unknown=unknown[ri,ci])
            emit("positions",data)
        if market.signal_mask[di]:
            input_mask=np.broadcast_to(market.input_present[di],(s,n))
            signal_sell=market.sell_restricted[di]|~valid_close
            signal_buy=market.buy_restricted[di]|~valid_close
            op_shared=np.zeros(n,dtype=bool)
            actions=market.operational_exits.get(date,{})
            for ticker,evidence in actions.items():
                if ticker not in ticker_lookup or not str(evidence.reason).strip() or not str(evidence.source_id).strip():
                    raise ValueError("operational evidence requires known ticker, source and reason")
                known=pd.Timestamp(evidence.known_at);asof=pd.Timestamp(market.signal_asof[di])
                if pd.isna(known) or known.tzinfo!=asof.tzinfo or known>asof:
                    raise ValueError("operational exit future/unsourced")
                op_shared[ticker_lookup[ticker]]=True
            op_mask=np.broadcast_to(op_shared,(s,n))
            reserved=held&(~input_mask|signal_sell[None,:])
            reserved&=~(op_mask&~signal_sell[None,:])
            reserved[~_positive(nav)]=held[~_positive(nav)]
            reserved_weight=np.sum(np.where(reserved,weights,0.0),axis=1)
            reserved_slots=reserved.sum(axis=1)
            budget=np.where(_positive(nav),np.maximum(0,max_invested-reserved_weight),0)
            slots=np.maximum(0,max_positions-reserved_slots)
            decision_mask=input_mask&~reserved&~op_mask&~(signal_buy[None,:]&~held)
            buy_allowed=np.broadcast_to(market.input_present[di]&market.new_buy_eligible[di]&~signal_buy,(s,n)).copy()
            ctx=AccountContext(di,date,pd.Timestamp(market.signal_asof[di]),ids,market.tickers.copy(),units.copy(),weights.copy(),cash.copy(),cash_weight.copy(),nav.copy(),
                               reserved.copy(),reserved_weight.copy(),reserved_slots.copy(),budget.copy(),slots.copy(),buy_allowed.copy(),
                               np.broadcast_to(signal_sell,(s,n)).copy(),input_mask.copy(),decision_mask.copy(),op_mask.copy(),max_positions,max_weight,max_invested)
            if _positive(nav).any():
                result=policy(di,ctx)
                if not isinstance(result,TargetDecision):raise ValueError("policy must return TargetDecision")
                raw=np.asarray(result.weights,dtype=np.float64)
                explicit=decision_mask.copy() if result.explicit_mask is None else np.asarray(result.explicit_mask,dtype=bool)
                if raw.shape!=(s,n) or explicit.shape!=(s,n) or (explicit&~decision_mask&_positive(nav)[:,None]).any():
                    raise ValueError("target/explicit mask incompatible with current decision inputs")
                explicit=explicit&_positive(nav)[:,None]
                if not np.isfinite(raw[explicit]).all() or ((raw[explicit]<0)|(raw[explicit]>max_weight+1e-7)).any():
                    raise ValueError("invalid explicit target weights")
                raw=np.where(explicit,raw,0.0)
                evidence_id=result.raw_evidence_id
            else:
                raw=np.zeros((s,n));explicit=np.zeros((s,n),dtype=bool);evidence_id=None
            final_reserved=reserved|(held&~explicit&~op_mask)
            final_reserved&=~(op_mask&~signal_sell[None,:])
            final_reserved_weight=np.sum(np.where(final_reserved,weights,0.0),axis=1)
            final_budget=np.where(_positive(nav),np.maximum(0,max_invested-final_reserved_weight),0.0)
            final_slots=np.maximum(0,max_positions-final_reserved.sum(axis=1))
            adapted=np.where(explicit&~final_reserved&~op_mask,np.minimum(raw,max_weight),0.0)
            # Signal new-capital ineligibility is independent of overnight move.
            ineligible_adaptation=~buy_allowed&(adapted>np.nan_to_num(weights,nan=0.0))
            adapted=np.where(ineligible_adaptation,np.maximum(np.nan_to_num(weights,nan=0.0),0.0),adapted)
            # Common engine prioritizes existing positive targets only if policy
            # exceeds slot budget. Proper optimizers do not trigger this repair.
            ordering=np.lexsort((ticker_keys,-adapted,~held,adapted<=0),axis=1)
            rank=np.argsort(ordering,axis=1,kind="stable")
            slot_adaptation=(adapted>0)&(rank>=final_slots[:,None])
            adapted=np.where(rank<final_slots[:,None],adapted,0.0)
            total=adapted.sum(axis=1)
            scale=np.minimum(1.0,np.divide(final_budget,total,out=np.ones(s),where=total>0))
            adapted*=scale[:,None]
            adapted=np.where(op_mask,0.0,adapted)
            # Raw positive requests repaired to zero must still be saved.
            # Only unheld explicit-zero/no-decision rows may be compressed.
            order_mask=held|(raw>0)|(adapted>0)|op_mask
            keep=final_reserved&~op_mask
            semantics=np.where(op_mask,"OPERATIONAL_EXIT_REQUIRED",np.where(explicit&held&(raw==0),"MODEL_ACTIVE_EXIT",np.where(explicit&(raw==0),"MODEL_ZERO_ALLOCATION",np.where(explicit,"MODEL_TARGET_WEIGHT","MODEL_NO_DECISION"))))
            kind=np.where(op_mask,"EXIT",np.where(final_reserved,"HOLD_UNITS","TARGET_WEIGHT"))
            ri,ci=np.nonzero(order_mask)
            if len(ri):
                data=linked(ri,ci,di,di+1 if di+1<len(market.dates) else None)
                if evidence_id is None:ev=np.full(len(ri),"",dtype=object)
                elif isinstance(evidence_id,str):ev=np.full(len(ri),evidence_id,dtype=object)
                else:ev=np.asarray(evidence_id,dtype=object)[ri]
                data.update(decision_semantic=semantics[ri,ci],order_type=kind[ri,ci],explicit_model_decision=explicit[ri,ci],
                            raw_model_weight=np.where(explicit[ri,ci],raw[ri,ci],np.nan),target_weight=np.where(op_mask[ri,ci],0.0,np.where(final_reserved[ri,ci],weights[ri,ci],adapted[ri,ci])),
                            current_weight=weights[ri,ci],current_units=units[ri,ci].copy(),hold_units=np.where(final_reserved[ri,ci],units[ri,ci],0.0),
                            signal_reserved=final_reserved[ri,ci],signal_close_nav=nav[ri],signal_day_adv=market.adv[di,ci],
                            reserved_weight=final_reserved_weight[ri],active_target_sum=adapted.sum(axis=1)[ri],
                            status=np.full(len(ri),"submitted" if di+1<len(market.dates) else "no_next_session",dtype=object),raw_evidence_id=ev)
                reasons=[]
                for r,c in zip(ri,ci):
                    reasons.append("|".join((["SIGNAL_NEW_CAPITAL_INELIGIBLE"] if ineligible_adaptation[r,c] else [])+(["SIGNAL_RESERVED_SLOT_BUDGET"] if slot_adaptation[r,c] else [])+(["SIGNAL_RESERVED_CAPITAL_BUDGET"] if adapted[r,c]>0 and scale[r]<1.0 else [])))
                data.update(adapted_target_weight=data["target_weight"],adaptation_reasons=np.asarray(reasons,dtype=object),model_input_row_present=input_mask[ri,ci],decision_input_row_present=decision_mask[ri,ci])
                emit("orders",data)
            if di not in decision_label_cache:
                day_label=str(date.date())
                decision_label_cache[di]=np.asarray([f"{p}|{day_label}" for p in ids],dtype=object)
            decision_ids=decision_label_cache[di]
            emit("contexts",dict(path_id=id_array.copy(),decision_id=decision_ids,signal_date=np.repeat(date.to_datetime64(),s),nav=nav.copy(),cash=cash.copy(),
                                 cash_weight=cash_weight.copy(),reserved_slots=reserved_slots,reserved_weight=reserved_weight,
                                 available_slots=slots,available_budget=budget,final_reserved_slots=final_reserved.sum(axis=1),
                                 final_reserved_weight=final_reserved_weight,final_available_slots=final_slots,final_available_budget=final_budget,
                                 active_target_count=(adapted>0).sum(axis=1),active_target_weight=adapted.sum(axis=1),
                                 explicit_input_count=explicit.sum(axis=1),policy_called=_positive(nav),
                                 decision_mask_bits=np.asarray([x.tobytes() for x in np.packbits(decision_mask,axis=1,bitorder="little")],dtype=object),
                                 explicit_mask_bits=np.asarray([x.tobytes() for x in np.packbits(explicit,axis=1,bitorder="little")],dtype=object)))
            for ticker,evidence in actions.items():
                ci0=ticker_lookup[ticker];rr=np.arange(s);cc=np.full(s,ci0)
                data=linked(rr,cc,di,di+1 if di+1<len(market.dates) else None)
                data.update(reason=np.full(s,evidence.reason,dtype=object),known_at=np.full(s,str(evidence.known_at),dtype=object),
                            source_id=np.full(s,evidence.source_id,dtype=object),had_position=held[:,ci0],signal_sell_restricted=np.repeat(signal_sell[ci0],s))
                emit("operational_actions",data)
            if di+1<len(market.dates):
                pending=dict(signal_index=di,weights=adapted,keep=keep,order_mask=order_mask,buy_allowed=buy_allowed,
                             sell_restricted=np.broadcast_to(signal_sell,(s,n)).copy(),adv=market.adv[di].copy(),last_adv=last_adv.copy(),semantics=semantics,kinds=kind)
        previous_nav,previous_certified=nav,certified

    metadata=dict(version="BATCH_HOLDING_AWARE_EXECUTION_V2",reference="a2_buy_sell_cash_multimodel_20260928/engine_v2.py",
                  unit="price-index units",shareholder_total_return_certified=False,path_ids=list(ids),cost_bps_one_way=cost_bps,
                  capacity_fraction=capacity_fraction,capacity_on_sells=capacity_on_sells,max_positions=max_positions,max_target_weight=max_weight,
                  max_target_invested=max_invested,terminal_liquidation=False,decision_clock="signal close",execution_clock="next session open",
                  target_sizing="next-open marked NAV",missing_decision_policy="preserve exact units and reserve capital/slots",
                  zero_target_storage="unheld explicit zeros reconstructed from context explicit_mask_bits and sparse orders; raw positive repaired-to-zero orders retained",
                  ticker_order=list(market.tickers),mask_bitorder="little",
                  independent_accounts=True)
    if any(audit[k]>1e-5 for k in ["cash_identity_error_max","cost_identity_error_max","self_finance_error_max","nav_identity_error_max"]) or audit["capacity_violations"] or audit["next_open_violations"]:
        raise AssertionError(f"independent vectorized account audit failed: {audit}")
    columns={
        "daily":["path_id","date","execution_date","signal_date","cash","nav","certified_nav","valuation_status","pretrade_nav","open_posttrade_nav","known_position_value","stale_count","unknown_count","actual_name_count","open_stale_count","open_unknown_count","cash_weight","gross_exposure","net_return","indicative_return","transaction_cost_amount","buy_notional","sell_notional","traded_notional","turnover","buy_cash_scale","blocked_order_count","nav_identity_error","cash_flow_identity_error","cost_identity_error","open_self_finance_error"],
        "positions":["path_id","date","ticker","index_units","mark","mark_date","mark_source","market_value","weight","stale","unknown"],
        "orders":["path_id","signal_date","execution_date","decision_id","order_id","ticker","decision_semantic","order_type","explicit_model_decision","raw_model_weight","target_weight","current_weight","current_units","hold_units","signal_reserved","signal_close_nav","signal_day_adv","reserved_weight","active_target_sum","status","raw_evidence_id","adapted_target_weight","adaptation_reasons","model_input_row_present","decision_input_row_present"],
        "fills":["path_id","signal_date","execution_date","decision_id","order_id","ticker","side","action","price","notional","index_units","index_units_before","index_units_after","transaction_cost","cost_bps","pretrade_nav","signal_day_adv","decision_semantic","requested_notional","partial_fill","capacity_limited","cash_limited"],
        "execution_results":["path_id","signal_date","execution_date","decision_id","order_id","ticker","status","reason","side","notional","index_units","transaction_cost","decision_semantic","order_type","execution_semantic"],
        "contexts":["path_id","decision_id","signal_date","nav","cash","cash_weight","reserved_slots","reserved_weight","available_slots","available_budget","final_reserved_slots","final_reserved_weight","final_available_slots","final_available_budget","active_target_count","active_target_weight","explicit_input_count","policy_called","decision_mask_bits","explicit_mask_bits"],
        "operational_actions":["path_id","signal_date","execution_date","decision_id","order_id","ticker","reason","known_at","source_id","had_position","signal_sell_restricted"]}
    frames={name:_take_frame(chunks[name],cols) for name,cols in columns.items()}
    return BatchReplay(**frames,metadata=metadata,audit=audit,final_units=units,final_cash=cash)
