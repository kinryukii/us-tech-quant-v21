"""Synthetic causal equivalence and independently reconstructed account tests."""
from pathlib import Path
import importlib.util
import sys
import numpy as np
import pandas as pd
import pytest

from fast_account import MarketArrays, OperationalEvidence, TargetDecision, run_many

REFERENCE=Path(__file__).resolve().parents[1]/"a2_buy_sell_cash_multimodel_20260928"/"engine_v2.py"
_spec=importlib.util.spec_from_file_location("pto_reference_engine_v2",REFERENCE)
ref=importlib.util.module_from_spec(_spec);sys.modules[_spec.name]=ref;_spec.loader.exec_module(ref)


def fixture(names=("Z","A","B"),days=5,signals=2):
    dates=pd.bdate_range("2025-06-02",periods=days)
    shape=(days,len(names))
    return MarketArrays(dates,np.asarray(names),np.full(shape,100.0),np.full(shape,100.0),
                        adv=np.full(shape,1e9),signal_mask=np.arange(days)<signals)


def compare(market,targets,*,extra_explicit=None,initial_units=None,initial_cash=1000.,**options):
    targets=np.asarray(targets,dtype=float)
    s,n=targets.shape[1:]
    ids=[f"path_{i}" for i in range(s)]
    options.setdefault("capacity_fraction",.01)
    initial=np.zeros((s,n)) if initial_units is None else np.broadcast_to(np.asarray(initial_units,dtype=float),(s,n)).copy()
    def policy(di,ctx):
        mask=ctx.decision_mask.copy()
        if extra_explicit is not None:mask&=extra_explicit[di]
        return TargetDecision(targets[di],mask,raw_evidence_id="synthetic_predictions")
    batch=run_many(market,ids,policy,initial_units=initial,initial_cash=initial_cash,**options)
    pxrows=[]
    for di,date in enumerate(market.dates):
        for ci,ticker in enumerate(market.tickers):
            if market.row_present[di,ci]:
                pxrows.append(dict(ticker=str(ticker),trade_date=date,open=market.open[di,ci],close=market.close[di,ci],price_quality_warning=market.quality[di,ci]))
    for ci,ticker in enumerate(market.tickers):
        if np.isfinite(market.initial_marks[ci]):
            day=pd.Timestamp(market.initial_mark_dates[ci]) if not np.isnat(market.initial_mark_dates[ci]) else market.dates[0]-pd.Timedelta(days=1)
            pxrows.append(dict(ticker=str(ticker),trade_date=day,open=market.initial_marks[ci],close=market.initial_marks[ci],price_quality_warning=False))
    prices=pd.DataFrame(pxrows)
    frows=[dict(ticker=str(t),signal_date=d,new_buy_eligible=market.new_buy_eligible[di,ci],avg_dollar_volume_20d=market.adv[di,ci])
           for di,d in enumerate(market.dates) if market.signal_mask[di] for ci,t in enumerate(market.tickers) if market.input_present[di,ci]]
    features=pd.DataFrame(frows,columns=["ticker","signal_date","new_buy_eligible","avg_dollar_volume_20d"])
    operations={d:{t:ref.OperationalExit(a.reason,a.known_at,a.source_id) for t,a in events.items()} for d,events in market.operational_exits.items()}
    for r,path in enumerate(ids):
        def original_policy(day,ctx):
            di=market.dates.get_loc(ctx.signal_date)
            decisions={str(t):float(targets[di,r,np.where(market.tickers==t)[0][0]]) for t in day.ticker
                       if extra_explicit is None or extra_explicit[di,r,np.where(market.tickers==t)[0][0]]}
            return ref.HoldingAwareDecision(decisions,raw_model_outputs={})
        cash=float(np.broadcast_to(initial_cash,(s,))[r])
        reference=ref.run_replay(prices,market.dates,features,original_policy,candidate=path,initial_cash=cash,
                                 initial_positions={str(t):float(initial[r,ci]) for ci,t in enumerate(market.tickers) if initial[r,ci]>0},
                                 signal_start=market.dates[market.signal_mask].min(),signal_end=market.dates[market.signal_mask].max(),
                                 operational_exits_by_signal=operations,signal_asof=dict(zip(market.dates,market.signal_asof)),
                                 known_restrictions=market.known_restrictions_evidence,**options)
        daily=batch.daily[batch.daily.path_id.eq(path)].reset_index(drop=True)
        numeric=["cash","nav","certified_nav","pretrade_nav","open_posttrade_nav","known_position_value","stale_count","unknown_count","actual_name_count",
                 "cash_weight","gross_exposure","net_return","indicative_return","transaction_cost_amount","buy_notional","sell_notional","turnover","buy_cash_scale","blocked_order_count"]
        numeric += ["open_stale_count","open_unknown_count"]
        np.testing.assert_allclose(daily[numeric].to_numpy(float),reference.daily[numeric].to_numpy(float),atol=2e-7,rtol=2e-12,equal_nan=True)
        assert daily.valuation_status.tolist()==reference.daily.valuation_status.tolist()
        for actual,expected,keys,cols in [
            (batch.positions[batch.positions.path_id.eq(path)],reference.positions,["date","ticker"],["index_units","market_value","mark","weight"]),
            (batch.fills[batch.fills.path_id.eq(path)],reference.trades,["execution_date","ticker","side"],["notional","index_units","transaction_cost","index_units_before","index_units_after"])
        ]:
            actual=actual.sort_values(keys).reset_index(drop=True);expected=expected.sort_values(keys).reset_index(drop=True)
            assert len(actual)==len(expected)
            if len(actual):
                assert list(actual[keys].itertuples(index=False,name=None))==list(expected[keys].itertuples(index=False,name=None))
                np.testing.assert_allclose(actual[cols].to_numpy(float),expected[cols].to_numpy(float),atol=2e-7,rtol=2e-12,equal_nan=True)
        orders=batch.orders[batch.orders.path_id.eq(path)]
        if len(orders):
            merged=orders.merge(reference.target_decisions,on="order_id",suffixes=("_fast","_ref"),validate="one_to_one")
            assert len(merged)==len(orders)
            np.testing.assert_allclose(merged.target_weight_fast,merged.target_weight_ref,atol=1e-12,equal_nan=True)
            assert merged.decision_semantic_fast.tolist()==merged.decision_semantic_ref.tolist()
        # Reconstruct units and cash using fills alone, independently of engine
        # internal audit columns. Then independently value each daily account.
        reconstructed=initial[r].copy();funds=cash
        for drow in daily.itertuples():
            trades=batch.fills[batch.fills.path_id.eq(path)&batch.fills.execution_date.eq(drow.date)]
            for trade in trades.itertuples():
                ci=np.where(market.tickers==trade.ticker)[0][0]
                sign=1 if trade.side=="BUY" else -1
                reconstructed[ci]+=sign*trade.index_units
                funds-=sign*trade.notional+trade.transaction_cost
                assert trade.execution_date==market.dates[market.dates.get_loc(trade.signal_date)+1]
                assert trade.transaction_cost==pytest.approx(trade.notional*options.get("cost_bps",10.)/10000)
            assert funds==pytest.approx(drow.cash,abs=2e-7)
            observed=batch.positions[batch.positions.path_id.eq(path)&batch.positions.date.eq(drow.date)]
            actual_units=np.zeros(n)
            for pos in observed.itertuples():actual_units[np.where(market.tickers==pos.ticker)[0][0]]=pos.index_units
            np.testing.assert_allclose(reconstructed,actual_units,atol=1e-9)
            if np.isfinite(drow.nav):assert drow.nav==pytest.approx(funds+observed.market_value.sum(),abs=2e-7)
    return batch


def test_random_accounts_match_reference_through_reservations_and_failed_prices():
    rng=np.random.default_rng(20250928)
    market=fixture(("Z","B","A","D","C"),days=8,signals=6)
    market.open[:]*=np.exp(rng.normal(0,.08,market.open.shape));market.close[:]*=np.exp(rng.normal(0,.08,market.close.shape))
    market.input_present[2,0]=False;market.quality[3,1]=True;market.open[4,2]=np.nan;market.close[5,3]=np.nan
    market.adv[:,4]=3000.;market.new_buy_eligible[4:,0]=False
    targets=rng.uniform(0,.1,(8,3,5));targets[targets<.035]=0
    explicit=np.ones_like(targets,dtype=bool);explicit[1,0,1]=False
    compare(market,targets,extra_explicit=explicit,initial_units=np.array([[2,0,0,0,0],[0,2,0,0,0],[0,0,0,0,0]]),max_positions=2)


def test_unknown_nav_is_separate_account_and_keeps_original_units():
    market=fixture(("UNKNOWN","B"),days=4,signals=2)
    market.open[:,0]=np.nan;market.close[:,0]=np.nan;market.input_present[:,0]=False
    targets=np.zeros((4,2,2));targets[:,:,1]=.1
    batch=compare(market,targets,initial_units=[[10,0],[0,0]])
    assert batch.daily[batch.daily.path_id.eq("path_0")].nav.isna().all()
    assert batch.final_units[0,0]==10
    assert batch.final_units[1,1]>0
    assert not batch.contexts[batch.contexts.path_id.eq("path_0")].policy_called.any()


def test_twenty_first_name_rejected_after_unexpected_failed_sale():
    market=fixture(tuple(f"T{i:02}" for i in range(21)),days=3,signals=1)
    market.open[1,0]=np.nan
    targets=np.full((3,1,21),100/11000);targets[0,0,0]=0;targets[0,0,-1]=.05
    batch=compare(market,targets,initial_cash=9000.,initial_units=[1]*20+[0])
    assert "LIVE_POSITION_LIMIT" in batch.execution_results.reason.tolist()
    assert batch.final_units[0,-1]==0


def test_capacity_partial_sell_missing_adv_and_stale_valuation_match():
    market=fixture(days=4,signals=2);market.adv[:,0]=1000.;market.adv[1,0]=np.nan;market.adv[:,1]=1000.;market.adv[:,2]=np.nan
    market.close[2,0]=np.nan
    targets=np.zeros((4,1,3));targets[0,0]=[.05,.1,.1]
    batch=compare(market,targets,initial_units=[2,0,0],capacity_on_sells=True)
    assert batch.fills.partial_fill.any()
    assert "PARTIALLY_FILLED" in batch.execution_results.status.tolist()
    assert "MISSING_SIGNAL_ADV" in batch.execution_results.reason.tolist()


def test_cash_cost_scaling_and_final_target_without_implicit_liquidation():
    market=fixture(("Z","A"),days=3,signals=3)
    targets=np.full((3,2,2),.6);targets[:,1]=0
    batch=compare(market,targets,max_weight=1.,max_invested=1.,max_positions=2,capacity_fraction=None)
    assert batch.fills.cash_limited.any()
    assert batch.orders[batch.orders.signal_date.eq(market.dates[-1])].status.eq("no_next_session").all()
    assert batch.final_units[0].sum()>0 and batch.final_units[1].sum()==0


def test_exact_ticker_ties_and_tiny_weight_differences():
    market=fixture(("Z","A"),days=3,signals=1)
    targets=np.full((3,2,2),.05);targets[0,0,0]+=1e-15
    batch=compare(market,targets,max_positions=1)
    assert batch.final_units[0,0]>0 and batch.final_units[0,1]==0
    assert batch.final_units[1,1]>0 and batch.final_units[1,0]==0
    # Positive requests repaired to zero are still auditable.
    assert len(batch.orders)==4


def test_restriction_and_operational_evidence_are_causal_and_equivalent():
    market=fixture(days=4,signals=2)
    asofs=[(d+pd.Timedelta(hours=16)).tz_localize("America/New_York").tz_convert("UTC") for d in market.dates]
    evidence=pd.DataFrame([dict(signal_date=market.dates[0],ticker="Z",known_at=asofs[0]-pd.Timedelta(minutes=1),source_id="pause:1",reason="known restriction",sell_restricted=True)])
    market=MarketArrays(market.dates,market.tickers,market.open,market.close,adv=market.adv,signal_mask=market.signal_mask,signal_asof=asofs,
                        known_restrictions_evidence=evidence,
                        operational_exits={market.dates[0]:{"Z":OperationalEvidence("mandate",asofs[0]-pd.Timedelta(minutes=2),"mandate:1")}})
    targets=np.zeros((4,1,3));targets[:,:,1]=.1
    batch=compare(market,targets,initial_units=[1,0,0],max_positions=1)
    assert "SIGNAL_KNOWN_SELL_RESTRICTION" in batch.execution_results.reason.tolist()
    evidence.loc[0,"known_at"]=asofs[0]+pd.Timedelta(seconds=1)
    with pytest.raises(ValueError,match="future/unsourced"):
        MarketArrays(market.dates,market.tickers,market.open,market.close,signal_asof=asofs,known_restrictions_evidence=evidence)


def test_missing_price_row_and_signal_quality_have_distinct_rejection_reasons():
    market=fixture(days=3,signals=1);market.row_present[1,0]=False;market.quality[1,1]=True
    targets=np.full((3,1,3),.05)
    batch=compare(market,targets)
    assert {"MISSING_PRICE_ROW","PRICE_QUALITY_UNCERTIFIED"}.issubset(set(batch.execution_results.reason))


def test_sparse_explicit_masks_reconstruct_zeros_and_streaming_is_identical():
    market=fixture(days=3,signals=1)
    target=np.array([[.05,0,0],[0,0,0]])
    def policy(di,ctx):return TargetDecision(target,ctx.decision_mask)
    result=run_many(market,["A","B"],policy)
    assert len(result.orders)==1
    for row in result.contexts.itertuples():
        explicit=np.unpackbits(np.frombuffer(row.explicit_mask_bits,dtype=np.uint8),bitorder="little")[:len(market.tickers)].astype(bool)
        reconstructed=np.zeros(len(market.tickers));reconstructed[~explicit]=np.nan
        for order in result.orders[result.orders.decision_id.eq(row.decision_id)].itertuples():
            reconstructed[np.where(market.tickers==order.ticker)[0][0]]=order.raw_model_weight
        np.testing.assert_allclose(reconstructed,target[0 if row.path_id=="A" else 1])
    chunks={}
    def sink(name,frame):chunks.setdefault(name,[]).append(frame)
    streamed=run_many(market,["A","B"],policy,collect_ledgers=False,ledger_callback=sink)
    assert streamed.daily.empty
    pd.testing.assert_frame_equal(pd.concat(chunks["daily"],ignore_index=True),result.daily)


def test_next_open_never_changes_previous_signal_targets():
    market=fixture(days=3,signals=1)
    def policy(di,ctx):return TargetDecision(np.full_like(ctx.current_weights,.05),ctx.decision_mask)
    good=run_many(market,["A"],policy)
    market.open[1]*=4
    bad=run_many(market,["A"],policy)
    pd.testing.assert_frame_equal(good.orders,bad.orders)
    assert good.fills.index_units.sum()==pytest.approx(4*bad.fills.index_units.sum())


def test_trusted_initial_mark_survives_flagged_current_prices_without_inflating_capital():
    market=fixture(days=3,signals=1)
    market.initial_marks[0]=100.;market.initial_mark_dates[0]=market.dates[0].to_datetime64()-np.timedelta64(1,"D")
    market.quality[0,0]=True;market.open[0,0]=1e9;market.close[0,0]=1e9
    targets=np.zeros((3,1,3));targets[:,:,1]=.1
    batch=compare(market,targets,initial_units=[10,0,0])
    first=batch.daily.iloc[0]
    assert first.nav==2000 and pd.isna(first.certified_nav)
    assert batch.final_units[0,0]==10


def test_unproven_restriction_mask_and_missing_sources_are_rejected():
    market=fixture(days=3,signals=1)
    masks=np.zeros_like(market.open,dtype=bool);masks[0,0]=True
    with pytest.raises(ValueError,match="dated source evidence"):
        MarketArrays(market.dates,market.tickers,market.open,market.close,sell_restricted=masks)
    rows=pd.DataFrame([dict(signal_date=market.dates[0],ticker="Z",known_at=market.dates[0],source_id="x",reason="pause",sell_restricted=True)])
    with pytest.raises(ValueError,match="not exactly supported"):
        MarketArrays(market.dates,market.tickers,market.open,market.close,sell_restricted=np.zeros_like(masks),known_restrictions_evidence=rows)
    rows.loc[0,"source_id"]=""
    with pytest.raises(ValueError,match="future/unsourced"):
        MarketArrays(market.dates,market.tickers,market.open,market.close,known_restrictions_evidence=rows)


def benchmark_128():
    """Fixed synthetic throughput receipt; no production data or outcomes."""
    import time
    from optimization import optimize
    rng=np.random.default_rng(20250928)
    s,n,h=128,20,32
    mu=rng.normal(.004,.003,(s,n));scale=np.full((s,n),.015)
    cov=np.tile(np.eye(n)*.000225,(s,1,1));current=np.full((s,n),.02)
    scenarios=rng.normal(size=(s,h,n))
    receipt={"synthetic_only":True,"accounts":s,"selected_names":n,"scenarios":h,"optimization":{}}
    for kind in ["positive_equal","mean_variance","robust_mv","cvar"]:
        start=time.perf_counter()
        result=optimize(kind,mu,cov,current,np.full(s,.95),np.full(s,20),uncertainty=scale,scenarios=scenarios)
        receipt["optimization"][kind]=dict(seconds=time.perf_counter()-start,maximum_iterations=int(result.iterations.max()),
                                           residual_max=float(result.residual.max()),statuses={str(k):int(v) for k,v in zip(*np.unique(result.status,return_counts=True))})
    market=fixture(tuple(f"T{i:03}" for i in range(40)),days=30,signals=29)
    targets=np.zeros((s,40));targets[:,:20]=.0475
    def policy(di,ctx):return TargetDecision(targets,ctx.decision_mask)
    start=time.perf_counter();result=run_many(market,[f"bench_{i}" for i in range(s)],policy,collect_ledgers=False)
    receipt["account_30_sessions_without_retaining_ledgers"]=dict(seconds=time.perf_counter()-start,audit=result.audit)
    start=time.perf_counter();result=run_many(market,[f"bench_{i}" for i in range(s)],policy)
    receipt["account_30_sessions_with_ledgers"]=dict(seconds=time.perf_counter()-start,daily_rows=len(result.daily),
                                                   position_rows=len(result.positions),order_rows=len(result.orders),fill_rows=len(result.fills),audit=result.audit)
    return receipt


def label_cache_compatibility_receipt():
    """Audit-only reverse snapshot and bitwise proof for the label cache patch."""
    import hashlib,json
    from datetime import datetime,timezone
    root=Path(__file__).resolve().parent
    common=root/"fast_account.py"
    after_bytes=common.read_bytes();after=after_bytes.decode("utf-8")
    pairs=[
        ("    decision_label_cache={}\n", ""),
        ("        if signal_index not in decision_label_cache:\n            day_label=str(market.dates[signal_index].date())\n            decision_label_cache[signal_index]=np.asarray([f\"{p}|{day_label}\" for p in ids],dtype=object)\n        decision=decision_label_cache[signal_index][ri]\n",
         "        decision=np.asarray([f\"{ids[r]}|{market.dates[signal_index].date()}\" for r in ri],dtype=object)\n"),
        ("            if di not in decision_label_cache:\n                day_label=str(date.date())\n                decision_label_cache[di]=np.asarray([f\"{p}|{day_label}\" for p in ids],dtype=object)\n            decision_ids=decision_label_cache[di]\n",
         "            decision_ids=np.asarray([f\"{p}|{date.date()}\" for p in ids],dtype=object)\n")]
    before=after
    for new,old in pairs:
        assert before.count(new)==1,"LABEL_PATCH_NOT_UNIQUE"
        before=before.replace(new,old,1)
    before_bytes=before.encode("utf-8")
    expected="e655f3c6c8ef4456c54094c235c4e925629f76914603b46ff633e7e2f0114e64"
    assert hashlib.sha256(before_bytes).hexdigest()==expected,"BEFORE_SOURCE_NOT_BOUND_VERSION"
    auditdir=root/"audits";auditdir.mkdir(exist_ok=True)
    snapshot=auditdir/"engine_before_label_cache_e655.py";snapshot.write_bytes(before_bytes)
    module_name="pto_engine_before_label_cache"
    spec=importlib.util.spec_from_file_location(module_name,snapshot)
    original=importlib.util.module_from_spec(spec);sys.modules[module_name]=original;spec.loader.exec_module(original)
    rng=np.random.default_rng(20250928)
    market=fixture(("Z","B","A","D","C"),days=8,signals=6)
    market.open[:]*=np.exp(rng.normal(0,.08,market.open.shape));market.close[:]*=np.exp(rng.normal(0,.08,market.close.shape))
    market.input_present[2,0]=False;market.quality[3,1]=True;market.open[4,2]=np.nan;market.close[5,3]=np.nan
    market.adv[:,4]=3000.;market.new_buy_eligible[4:,0]=False
    targets=rng.uniform(0,.1,(8,3,5));targets[targets<.035]=0
    initial=np.array([[2,0,0,0,0],[0,2,0,0,0],[0,0,0,0,0]],dtype=float)
    ids=["compat_0","compat_1","compat_2"]
    def old_policy(di,ctx):return original.TargetDecision(targets[di],ctx.decision_mask,"same_synthetic_evidence")
    def new_policy(di,ctx):return TargetDecision(targets[di],ctx.decision_mask,"same_synthetic_evidence")
    older=original.run_many(market,ids,old_policy,initial_units=initial,initial_cash=1000.,max_positions=2)
    newer=run_many(market,ids,new_policy,initial_units=initial,initial_cash=1000.,max_positions=2)
    tables={}
    for name in ["daily","positions","orders","fills","execution_results","contexts","operational_actions"]:
        a,b=getattr(older,name),getattr(newer,name)
        pd.testing.assert_frame_equal(a,b,check_exact=True)
        for column in a.select_dtypes(include=[np.floating]).columns:
            np.testing.assert_array_equal(a[column].to_numpy().view(np.uint64),b[column].to_numpy().view(np.uint64))
        tables[name]=dict(rows=len(a),all_columns_and_values_exactly_equal=True,numeric_float64_bits_equal=True)
    np.testing.assert_array_equal(older.final_cash,newer.final_cash)
    np.testing.assert_array_equal(older.final_units,newer.final_units)
    assert older.audit==newer.audit and older.metadata==newer.metadata
    assert common.read_bytes()==after_bytes,"COMMON_SOURCE_CHANGED_DURING_COMPATIBILITY_CHECK"
    receipt=dict(status="PASS",scope="decision_id label cache only; no numerical or account rule change",
                 checked_at_utc=datetime.now(timezone.utc).isoformat(),synthetic_only=True,production_or_2026_outcomes_read=False,
                 before_sha256=expected,after_sha256=hashlib.sha256(after_bytes).hexdigest(),
                 before_source_snapshot=str(snapshot.resolve()),after_source_path=str(common.resolve()),
                 reconstructed_before_matches_original_rl_fit_binding=True,
                 exact_tables=tables,final_cash_and_units_bitwise_equal=True,audit_and_metadata_exactly_equal=True,
                 common_source_was_not_modified_by_this_audit=True,
                 cases="three independent synthetic accounts; missing features, missing next-open, quality warning, omitted/zero/positive orders, capacity and terminal valuation",
                 train_binding_note="Original pre-fit hashes stay unchanged; record this separate compatibility supplement, never claim raw sources_unchanged",
                 reproduce="python -B a2_pto_full_compat_20260928_r2/test_fast_account.py --label-compatibility")
    target=auditdir/"ACCOUNT_LABEL_CACHE_COMPATIBILITY.json"
    target.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding="utf-8")
    return dict(receipt_path=str(target.resolve()),**receipt)


if __name__=="__main__":
    import json
    print(json.dumps(label_cache_compatibility_receipt() if "--label-compatibility" in sys.argv else benchmark_128(),ensure_ascii=False,indent=2),flush=True)
