"""Independent streaming reconstruction of saved common-account ledgers.

Reads one session of each Parquet ledger at a time. Reconstructs each path's
cash and units from fills, independently values them against optional shared
market inputs, and checks fees, next-open timing, capacity, orders and masks.
It does not use engine error columns as proof. Production audits are explicit;
2026 data may be loaded only after the complete batch freeze exists.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq


class AuditFailure(Exception):
    pass


def _sessions(path, date_column, columns=None, batch_size=65536):
    """Yield adjacent, sorted sessions without reading the entire ledger."""
    path=Path(path)
    if not path.exists():return
    pending=[];current=None
    parquet=pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=batch_size,columns=columns):
        frame=batch.to_pandas()
        for key,group in frame.groupby(date_column,sort=False,dropna=False):
            key=pd.Timestamp(key)
            if pd.isna(key):raise AuditFailure(f"undated {path.name} row")
            if current is not None and key!=current:
                if key<current:raise AuditFailure(f"unsorted {path.name}: {key} after {current}")
                yield current,pd.concat(pending,ignore_index=True)
                pending=[]
            current=key;pending.append(group)
    if pending:yield current,pd.concat(pending,ignore_index=True)


class _Cursor:
    def __init__(self,path,date_column):
        self.iterator=iter(_sessions(path,date_column))
        self.next=next(self.iterator,None)
    def take(self,date):
        if self.next is not None and self.next[0]<date:
            raise AuditFailure(f"unmatched earlier ledger session {self.next[0]}")
        if self.next is None or self.next[0]!=date:return pd.DataFrame()
        result=self.next[1];self.next=next(self.iterator,None);return result
    def exhausted(self):return self.next is None


def _json_clean(value):
    if isinstance(value,dict):return {str(k):_json_clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [_json_clean(v) for v in value]
    if isinstance(value,(np.integer,)):return int(value)
    if isinstance(value,(np.floating,float)):return float(value) if np.isfinite(value) else None
    if isinstance(value,(pd.Timestamp,np.datetime64,Path)):return str(value)
    return value


def verify_folder(folder,*,market=None,initial_cash=1_000_000.0,initial_units=None,
                  metadata=None,tolerance=1e-5,unit_tolerance=1e-7,max_examples=12):
    folder=Path(folder)
    if metadata is None:
        receipt=folder/"DONE.json"
        if not receipt.exists():raise AuditFailure("DONE.json or explicit metadata required")
        metadata=json.loads(receipt.read_text(encoding="utf-8"))["metadata"]
    path_ids=tuple(metadata["path_ids"])
    tickers=tuple(str(t) for t in (market.tickers if market is not None else metadata["ticker_order"]))
    if len(set(path_ids))!=len(path_ids) or len(set(tickers))!=len(tickers):raise AuditFailure("nonunique metadata keys")
    s,n=len(path_ids),len(tickers)
    path_index={p:i for i,p in enumerate(path_ids)};ticker_index={t:i for i,t in enumerate(tickers)}
    cash=np.broadcast_to(np.asarray(initial_cash,dtype=float),(s,)).copy()
    units=np.zeros((s,n)) if initial_units is None else np.broadcast_to(np.asarray(initial_units,dtype=float),(s,n)).copy()
    marks=np.full((s,n),np.nan)
    if market is not None:marks[:]=market.initial_marks
    count=0;examples=[];max_errors={};sessions=0;fills_checked=0;orders_checked=0
    cost_bps=float(metadata["cost_bps_one_way"]);rate=cost_bps/10000.
    capacity=metadata.get("capacity_fraction")
    limit=int(metadata["max_positions"]);max_weight=float(metadata["max_target_weight"])
    previous_date=None;pending_orders=pd.DataFrame()
    previous_nav=np.full(s,np.nan);previous_certified=np.full(s,np.nan)
    position_cursor=_Cursor(folder/"positions.parquet","date")
    fill_cursor=_Cursor(folder/"fills.parquet","execution_date")
    order_cursor=_Cursor(folder/"orders.parquet","signal_date")
    context_cursor=_Cursor(folder/"contexts.parquet","signal_date")
    execution_cursor=_Cursor(folder/"execution_results.parquet","execution_date")
    operational_cursor=_Cursor(folder/"operational_actions.parquet","signal_date")
    day_index={d:i for i,d in enumerate(market.dates)} if market is not None else {}

    def mismatch(code,mask,detail=None):
        nonlocal count
        mask=np.asarray(mask,dtype=bool).reshape(-1)
        indices=np.flatnonzero(mask);count+=len(indices)
        for index in indices[:max(0,max_examples-len(examples))]:
            extra={} if detail is None else detail(int(index))
            examples.append(dict(code=code,**_json_clean(extra)))

    def close(code,actual,expected,labels=None,absolute=tolerance):
        a,b=np.broadcast_arrays(np.asarray(actual,dtype=float),np.asarray(expected,dtype=float))
        valid=np.isfinite(a)&np.isfinite(b)
        error=np.where(valid,np.abs(a-b),0.)
        max_errors[code]=max(max_errors.get(code,0.),float(np.max(error)) if error.size else 0.)
        bad=(~valid&~(np.isnan(a)&np.isnan(b)))|(error>absolute)
        aa,bb=a.reshape(-1),b.reshape(-1)
        mismatch(code,bad,lambda i:dict(index=i,path_id=path_ids[i] if a.shape==(s,) else None,
                                        actual=aa[i],expected=bb[i],label=labels[i] if labels is not None else None))

    def indices(frame):
        r=frame.path_id.map(path_index);c=frame.ticker.map(ticker_index)
        if r.isna().any() or c.isna().any():raise AuditFailure("ledger key outside metadata")
        return r.to_numpy(int),c.to_numpy(int)

    for date,daily in _sessions(folder/"daily.parquet","date"):
        sessions+=1
        mapped=daily.path_id.map(path_index)
        if mapped.isna().any():raise AuditFailure("daily path outside metadata")
        ri=mapped.to_numpy(int)
        coverage=np.bincount(ri,minlength=s)
        mismatch("DAILY_PATH_COVERAGE",coverage!=1,lambda i:dict(path_id=path_ids[i],date=date,count=int(coverage[i])))
        if np.any(coverage!=1):raise AuditFailure("daily coverage prevents independent row alignment")
        daily=daily.assign(_row=ri).sort_values("_row").reset_index(drop=True)
        fills=fill_cursor.take(date);positions=position_cursor.take(date);executions=execution_cursor.take(date)
        known_open=None;pre_nav=None
        if market is not None:
            if date not in day_index:raise AuditFailure("daily session outside shared market")
            di=day_index[date]
            valid_open=np.isfinite(market.open[di])&(market.open[di]>0)&~market.quality[di]&market.row_present[di]
            held=units>1e-10
            marks=np.where(held&valid_open[None,:],market.open[di][None,:],marks)
            known_open=marks.copy()
            pre_nav=cash+np.sum(np.where(held,units*np.nan_to_num(marks,nan=0.),0.),axis=1)
            pre_nav[(held&~np.isfinite(marks)).any(axis=1)]=np.nan
            close("PRETRADE_NAV_FROM_SHARED_PRICES",daily.pretrade_nav,pre_nav)
        day_fees=np.zeros(s);day_buy=np.zeros(s);day_sell=np.zeros(s)
        if len(fills):
            r,c=indices(fills);fills_checked+=len(fills)
            side=fills.side.to_numpy(str);quantity=fills.index_units.to_numpy(float);amount=fills.notional.to_numpy(float);fee=fills.transaction_cost.to_numpy(float)
            buy=side=="BUY";sell=side=="SELL"
            mismatch("INVALID_FILL_SIDE",~(buy|sell))
            mismatch("INVALID_FILL_QUANTITY_OR_AMOUNT",~np.isfinite(quantity)|~np.isfinite(amount)|~np.isfinite(fee)|(quantity<=0)|(amount<=0)|(fee<0))
            close("NOTIONAL_EQUALS_UNITS_TIMES_PRICE",amount,quantity*fills.price.to_numpy(float),fills.order_id.tolist())
            close("FEE_EQUALS_ACTUAL_NOTIONAL_TIMES_COMMON_COST",fee,amount*rate,fills.order_id.tolist())
            close("FILL_COST_BPS",fills.cost_bps,np.full(len(fills),cost_bps),fills.order_id.tolist(),absolute=1e-12)
            mismatch("NEXT_OPEN_SIGNAL_CLOCK",pd.to_datetime(fills.signal_date).ne(previous_date).to_numpy(),lambda i:dict(order_id=fills.iloc[i].order_id,signal_date=fills.iloc[i].signal_date,execution_date=date,expected_signal_date=previous_date))
            if pending_orders.empty:
                mismatch("FILL_WITHOUT_PREVIOUS_ORDER",np.ones(len(fills),bool))
            else:
                if pending_orders.order_id.duplicated().any():raise AuditFailure("duplicate pending order_id")
                joined=fills.merge(pending_orders[["order_id","execution_date","signal_date","decision_semantic"]],on="order_id",how="left",suffixes=("","_order"),validate="many_to_one")
                mismatch("FILL_ORDER_LINK_MISSING",joined.signal_date_order.isna().to_numpy())
                mismatch("FILL_ORDER_EXECUTION_DATE",pd.to_datetime(joined.execution_date_order).ne(date).to_numpy())
                mismatch("FILL_ORDER_DECISION_SEMANTIC",joined.decision_semantic.ne(joined.decision_semantic_order).to_numpy())
            if capacity is not None:
                adv=fills.signal_day_adv.to_numpy(float)
                mismatch("BUY_SIGNAL_ADV_CAPACITY",buy&(~np.isfinite(adv)|(amount>float(capacity)*adv+tolerance)))
            if market is not None:
                mismatch("FILL_AT_UNUSABLE_OPEN",~valid_open[c])
                mismatch("FILL_UNKNOWN_ACCOUNT_NAV",~np.isfinite(pre_nav[r])|(pre_nav[r]<=0))
                close("FILL_EQUALS_SHARED_OPEN",fills.price,market.open[di,c],fills.order_id.tolist(),absolute=1e-10)
                if previous_date in day_index:
                    pi=day_index[previous_date]
                    valid_signal_close=np.isfinite(market.close[pi,c])&(market.close[pi,c]>0)&~market.quality[pi,c]&market.row_present[pi,c]
                    mismatch("BUY_OUTSIDE_SIGNAL_POOL_OR_INPUT",buy&~(market.input_present[pi,c]&market.new_buy_eligible[pi,c]&valid_signal_close&~market.buy_restricted[pi,c]))
                    mismatch("SELL_KNOWN_SIGNAL_RESTRICTION",sell&~(valid_signal_close&~market.sell_restricted[pi,c]))
                    close("SIGNAL_ADV_PROVENANCE",fills.signal_day_adv,market.adv[pi,c],fills.order_id.tolist())
            np.add.at(units,(r,c),np.where(buy,quantity,-quantity))
            np.add.at(cash,r,np.where(buy,-amount,amount)-fee)
            np.add.at(day_fees,r,fee);np.add.at(day_buy,r,np.where(buy,amount,0.));np.add.at(day_sell,r,np.where(sell,amount,0.))
            if market is not None:marks[r[buy],c[buy]]=fills.price.to_numpy(float)[buy]
        mismatch("NEGATIVE_RECONSTRUCTED_UNITS",units.reshape(-1)<-unit_tolerance)
        units[np.abs(units)<=1e-10]=0.
        mismatch("NEGATIVE_RECONSTRUCTED_CASH",cash<-tolerance)
        close("CASH_RECONSTRUCTED_FROM_FILLS",daily.cash,cash)
        close("DAILY_FEES_RECONSTRUCTED_FROM_FILLS",daily.transaction_cost_amount,day_fees)
        close("DAILY_BUYS_RECONSTRUCTED_FROM_FILLS",daily.buy_notional,day_buy)
        close("DAILY_SELLS_RECONSTRUCTED_FROM_FILLS",daily.sell_notional,day_sell)
        pretrade=pre_nav if market is not None else daily.pretrade_nav.to_numpy(float)
        close("HALF_TURNOVER",daily.turnover,np.divide(.5*(day_buy+day_sell),pretrade,out=np.full(s,np.nan),where=np.isfinite(pretrade)&(pretrade>0)),absolute=1e-9)
        if market is not None:
            held_now=units>1e-10
            post_open=cash+np.sum(np.where(held_now,units*np.nan_to_num(marks,nan=0.),0.),axis=1)
            post_open[(held_now&~np.isfinite(marks)).any(axis=1)]=np.nan
            close("POSTTRADE_NAV_FROM_SHARED_OPENS",daily.open_posttrade_nav,post_open)
            close("OPEN_SELF_FINANCE_INDEPENDENT",post_open,pre_nav-day_fees)
        observed=np.zeros((s,n));position_value=np.zeros(s);position_unknown=np.zeros(s,bool);stale_count=np.zeros(s,int)
        if len(positions):
            r,c=indices(positions)
            if positions.duplicated(["path_id","ticker"]).any():raise AuditFailure("duplicate daily position")
            observed[r,c]=positions.index_units.to_numpy(float)
            v=positions.market_value.to_numpy(float)
            np.add.at(position_value,r,np.nan_to_num(v,nan=0.))
            position_unknown[r[np.isnan(v)]]=True
            np.add.at(stale_count,r,positions.stale.to_numpy(int))
            close("POSITION_MARK_VALUE",v,positions.index_units.to_numpy(float)*positions.mark.to_numpy(float),positions.path_id.tolist())
        close("UNITS_RECONSTRUCTED_FROM_FILLS",observed,units,absolute=unit_tolerance)
        actual_names=np.count_nonzero(units>1e-10,axis=1)
        close("ACTUAL_NAME_COUNT",daily.actual_name_count,actual_names,absolute=0.)
        mismatch("TWENTY_POSITION_CONSTRAINT",actual_names>limit)
        nav=cash+position_value;nav[position_unknown]=np.nan
        certified=nav.copy();certified[position_unknown|(stale_count>0)]=np.nan
        close("NAV_RECONSTRUCTED_FROM_POSITIONS_AND_FILLS",daily.nav,nav)
        close("CERTIFIED_NAV_QUALIFICATION",daily.certified_nav,certified)
        close("NET_RETURN_FROM_RECONSTRUCTED_CERTIFIED_NAV",daily.net_return,np.divide(certified,previous_certified,out=np.full(s,np.nan),where=np.isfinite(previous_certified)&(previous_certified>0)&np.isfinite(certified)&(certified>0))-1.,absolute=1e-10)
        close("INDICATIVE_RETURN_FROM_RECONSTRUCTED_NAV",daily.indicative_return,np.divide(nav,previous_nav,out=np.full(s,np.nan),where=np.isfinite(previous_nav)&(previous_nav>0)&np.isfinite(nav)&(nav>0))-1.,absolute=1e-10)
        close("CASH_WEIGHT",daily.cash_weight,np.divide(cash,nav,out=np.full(s,np.nan),where=np.isfinite(nav)&(nav>0)),absolute=1e-9)
        if market is not None:
            held=units>1e-10
            valid_close=np.isfinite(market.close[di])&(market.close[di]>0)&~market.quality[di]&market.row_present[di]
            marks=np.where(held&valid_close[None,:],market.close[di][None,:],marks)
            prices_value=units*np.where(np.isfinite(marks),marks,0.)
            independent_nav=cash+prices_value.sum(axis=1)
            unknown=held&~np.isfinite(marks);stale=held&~valid_close[None,:]&~unknown
            independent_nav[unknown.any(axis=1)]=np.nan
            close("NAV_RECONSTRUCTED_FROM_SHARED_CLOSES",daily.nav,independent_nav)
            close("STALE_COUNT_FROM_SHARED_QUOTES",daily.stale_count,stale.sum(axis=1),absolute=0.)
            close("UNKNOWN_COUNT_FROM_SHARED_QUOTES",daily.unknown_count,unknown.sum(axis=1),absolute=0.)
            if len(positions):
                r,c=indices(positions)
                close("POSITION_MARK_EQUALS_SHARED_TRUSTED_MARK",positions.mark,marks[r,c],positions.path_id.tolist(),absolute=1e-9)
        if len(executions):
            accepted=executions[executions.status.eq("FILLED")]
            if accepted.order_id.duplicated().any():raise AuditFailure("duplicate FILLED execution order")
            if len(fills)!=len(accepted):mismatch("FILLED_EXECUTION_COUNT",[True],lambda i:dict(date=date,fills=len(fills),filled_executions=len(accepted)))
            if len(fills):
                joined=fills.merge(accepted[["order_id","notional","index_units","transaction_cost"]],on="order_id",how="left",suffixes=("","_execution"),validate="one_to_one")
                for name in ["notional","index_units","transaction_cost"]:close("FILLED_EXECUTION_"+name,joined[name],joined[name+"_execution"],joined.order_id.tolist())
        elif len(fills):mismatch("FILLS_WITHOUT_EXECUTION_LEDGER",[True])
        orders=order_cursor.take(date);contexts=context_cursor.take(date);operations=operational_cursor.take(date)
        if len(orders):
            r,c=indices(orders);orders_checked+=len(orders)
            if orders.order_id.duplicated().any():raise AuditFailure("duplicate order_id")
            raw=orders.raw_model_weight.to_numpy(float);explicit=orders.explicit_model_decision.to_numpy(bool)
            mismatch("RAW_MODEL_WEIGHT_CAP",explicit&(~np.isfinite(raw)|(raw<0)|(raw>max_weight+1e-7)))
            close("SIGNAL_CURRENT_UNITS",orders.current_units,units[r,c],orders.order_id.tolist(),absolute=unit_tolerance)
            close("SIGNAL_NAV",orders.signal_close_nav,nav[r],orders.order_id.tolist())
            if market is not None:
                next_date=market.dates[di+1] if di+1<len(market.dates) else pd.NaT
                expected=pd.Series(np.repeat(next_date,len(orders)))
                actual=pd.to_datetime(orders.execution_date).reset_index(drop=True)
                mismatch("ORDER_NEXT_SESSION_CLOCK",~((actual==expected)|(actual.isna()&expected.isna())).to_numpy())
            if len(contexts):
                masks={row.path_id:np.unpackbits(np.frombuffer(row.explicit_mask_bits,dtype=np.uint8),bitorder="little")[:n].astype(bool) for row in contexts.itertuples()}
                mismatch("SPARSE_ORDER_EXPLICIT_MASK",[str(p) not in masks or bool(masks[str(p)][ci])!=bool(ex) for p,ci,ex in zip(orders.path_id,c,explicit)])
        if len(contexts):
            for row in contexts.itertuples():
                bits=np.unpackbits(np.frombuffer(row.explicit_mask_bits,dtype=np.uint8),bitorder="little")[:n]
                mismatch("EXPLICIT_MASK_COUNT",[int(bits.sum())!=int(row.explicit_input_count)],lambda i:dict(path_id=row.path_id,date=date))
        if len(operations):
            for row in operations.itertuples():
                known=pd.Timestamp(row.known_at)
                bad=pd.isna(known) or not str(row.reason).strip() or not str(row.source_id).strip()
                if market is not None:bad=bad or known.tzinfo!=pd.Timestamp(market.signal_asof[di]).tzinfo or known>pd.Timestamp(market.signal_asof[di])
                mismatch("OPERATIONAL_EXIT_DATED_SOURCE",[bad],lambda i:dict(order_id=row.order_id,date=date))
        pending_orders=orders;previous_date=date
        previous_nav=nav;previous_certified=certified
    if not sessions:raise AuditFailure("empty or missing daily ledger")
    for cursor in [position_cursor,fill_cursor,order_cursor,context_cursor,execution_cursor,operational_cursor]:
        if not cursor.exhausted():raise AuditFailure("unmatched ledger records after final daily session")
    return _json_clean(dict(status="PASS" if count==0 else "FAIL",independent_reconstruction=True,
                            shared_price_verification=market is not None,paths=s,tickers=n,sessions=sessions,
                            fills_checked=fills_checked,orders_checked=orders_checked,mismatch_count=count,
                            maximum_absolute_errors=max_errors,first_mismatches=examples,
                            tolerance=tolerance,unit_tolerance=unit_tolerance,folder=str(folder.resolve())))


def self_test():
    """Synthetic only, including deliberate fee corruption detection."""
    from fast_account import MarketArrays,TargetDecision,run_many
    root=Path(__file__).resolve().parent
    folder=root/"audits"/"synthetic_ledger_verifier"
    folder.mkdir(parents=True,exist_ok=True)
    dates=pd.bdate_range("2025-06-02",periods=5)
    prices=np.full((5,3),100.)
    market=MarketArrays(dates,["A","B","C"],prices,prices.copy(),adv=np.full((5,3),1e8),signal_mask=np.array([1,1,1,1,0],bool))
    def policy(di,ctx):
        weights=np.zeros_like(ctx.current_units)
        weights[0,di%3]=.1;weights[1,(di+1)%3]=.05
        return TargetDecision(weights,ctx.decision_mask)
    replay=run_many(market,["synthetic_a","synthetic_b"],policy)
    for name in ["daily","positions","orders","fills","execution_results","contexts","operational_actions"]:
        getattr(replay,name).to_parquet(folder/f"{name}.parquet",index=False)
    (folder/"DONE.json").write_text(json.dumps({"metadata":replay.metadata}),encoding="utf-8")
    good=verify_folder(folder,market=market)
    assert good["status"]=="PASS",good
    fill_path=folder/"fills.parquet";original=fill_path.read_bytes()
    corrupt=replay.fills.copy();corrupt.loc[0,"transaction_cost"]+=1.
    try:
        corrupt.to_parquet(fill_path,index=False)
        bad=verify_folder(folder,market=market)
        assert bad["status"]=="FAIL" and bad["mismatch_count"]>0,bad
    finally:fill_path.write_bytes(original)
    result=dict(status="PASS",synthetic_only=True,valid_ledger=good,fee_corruption_detected=True,
                corruption_mismatch_count=bad["mismatch_count"],common_source_modified=False)
    (folder/"SELF_TEST_RECEIPT.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--folder",type=Path)
    parser.add_argument("--year",type=int,choices=[2025,2026])
    parser.add_argument("--output",type=Path)
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test:result=self_test()
    else:
        if args.folder is None:parser.error("--folder required")
        market=None
        if args.year is not None:
            root=Path(__file__).resolve().parent
            if args.year==2026 and not (root/"FROZEN_BEFORE_2026.json").exists():
                raise SystemExit("2026_AUDIT_REQUIRES_COMPLETED_BATCH_FREEZE")
            from market_runtime import prepare_market
            market=prepare_market(args.year).market
        try:result=verify_folder(args.folder,market=market)
        except AuditFailure as error:result=dict(status="FAIL",structural_failure=str(error),folder=str(args.folder.resolve()))
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    raise SystemExit(0 if result["status"]=="PASS" else 1)
