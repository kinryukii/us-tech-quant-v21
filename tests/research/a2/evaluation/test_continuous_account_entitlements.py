"""Source-only accounting/slippage checks; no real market or economic inputs."""
from dataclasses import asdict
from pathlib import Path
import importlib.util
import sys
import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from scripts.research.a2.evaluation.continuous_research_account import (
    run_continuous_account, account_prefix_identity, _engine_with_entitlement_hook,
)
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays, TargetDecision
from scripts.v22.corporate_action_transition_r1 import (
    SourceBackedEntitlementEvent, SourceBackedTerminalEvent, SourceBackedTerminalSettlement, CorporateActionTransition,
    RAW_OLD_SHARE_COORDINATE, USD_PER_RAW_OLD_SHARE,
)


def account():
    return dict(base_currency="USD", initial_nav=3000, initial_cash=3000, initial_holdings=[],
        fractional_shares=True, integer_share_rounding=False, cash_interest=0, transaction_cost_bps=0,
        financing=False, borrowed_cash=False, long_only=True, max_positions=20, max_weight=1.,
        max_invested=1., capacity_fraction=None)


def inputs(prices=(100,100,90,90,90), dates=None, tickers=("S",)):
    dates = dates or ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"]
    values=np.asarray(prices,float)
    if values.ndim==1: values=values[:,None]
    return MarketArrays(pd.to_datetime(dates),tickers,values.copy(),values.copy(),adv=np.full(values.shape,1e9))


def event(**changes):
    fields=dict(event_id="div", action_type="CASH_DIVIDEND", old_security_id="secS", ticker="S",
        ex_date="2024-01-04", record_date="2024-01-04", pay_date="2024-01-06",
        available_at="2024-01-03 12:00:00+00:00", cash_per_old_share=10., currency="USD",
        amount_unit=USD_PER_RAW_OLD_SHARE, quantity_coordinate=RAW_OLD_SHARE_COORDINATE,
        source_type="TIER2_LOCAL_CANONICAL", source_reference="synthetic://declared_dividend", source_fingerprint="c"*64)
    fields.update(changes)
    return SourceBackedEntitlementEvent(**fields)


def entitlement_args(events, mapping=None):
    mapping=mapping or {"secS":"S"}
    return dict(entitlement_enabled=True, entitlement_events=events, entitlement_security_tickers=mapping,
        entitlement_source_binding=dict(status="SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND",
            source_fingerprint="d"*64, event_fingerprints=[e.event_fingerprint for e in events],
            security_tickers=mapping, quantity_coordinate=RAW_OLD_SHARE_COORDINATE))


def friction(bps=10):
    return dict(kind="FIXED_ADVERSE_OPEN_SLIPPAGE", scenario_id=f"synthetic_{bps}bps",
        one_way_bps=bps, fee_bps=0, benchmark="NEXT_RAW_OPEN", authority="HYPOTHETICAL_RESEARCH_SCENARIO")


def hold(j,ctx):
    return TargetDecision(np.ones_like(ctx.current_weights),ctx.decision_mask) if j==0 else TargetDecision(np.zeros_like(ctx.current_weights),np.zeros_like(ctx.decision_mask))


def rebalance(j,ctx):
    return TargetDecision(np.ones_like(ctx.current_weights),ctx.decision_mask)


def test_receivable_is_nav_not_buy_cash_and_pay_funds_actual_execution():
    observed=[]
    def policy(j,ctx):
        observed.append((j,ctx.cash.copy(),ctx.nav.copy(),ctx.receivable_value_usd.copy()))
        return rebalance(j,ctx)
    replay=run_continuous_account(inputs(),["p"],policy,account(),**entitlement_args([event()]))
    assert replay.daily.nav.tolist()==pytest.approx([3000]*5)
    assert replay.daily.receivable_value_usd.tolist()==pytest.approx([0,0,300,300,0])
    assert replay.daily.entitlement_cash_flow_usd.tolist()==pytest.approx([0,0,0,0,300])
    assert replay.daily.buy_cash_scale.iloc[2:4].tolist()==pytest.approx([0,0])
    assert replay.daily.buy_notional.iloc[4]==pytest.approx(300)
    assert replay.final_state["fractional_shares"][0,0]==pytest.approx(3000/90)
    assert replay.final_state["cash"][0]==pytest.approx(0)
    assert replay.final_state["cash_receivables"]==()
    assert observed[2][1][0]==0 and observed[2][2][0]==3000 and observed[2][3][0]==300
    assert replay.daily.actual_cash_flow_identity_error.abs().max()<1e-8
    assert replay.audit["nav_identity_error_max"]<1e-8


def test_ex_pretrade_snapshot_survives_sale_and_ex_buyer_has_no_claim():
    def policy(j,ctx):
        weights=np.zeros_like(ctx.current_weights)
        if j==0: weights[0,0]=1
        if j==1: weights[1,0]=1
        return TargetDecision(weights,ctx.decision_mask)
    replay=run_continuous_account(inputs(),["seller","ex_buyer"],policy,account(),**entitlement_args([event()]))
    seller=replay.daily.loc[replay.daily.path_id.eq("seller")]
    buyer=replay.daily.loc[replay.daily.path_id.eq("ex_buyer")]
    assert seller.cash.tolist()==pytest.approx([3000,0,2700,2700,3000])
    assert seller.receivable_value_usd.tolist()==pytest.approx([0,0,300,300,0])
    assert buyer.receivable_value_usd.eq(0).all()
    assert buyer.entitlement_cash_flow_usd.eq(0).all()
    snapshots=replay.entitlements.loc[replay.entitlements.phase.eq("EX_PRETRADE_RAW_SHARE_SNAPSHOT")]
    assert snapshots.path_id.tolist()==["seller"]
    assert snapshots.entitled_raw_shares.iloc[0]==30
    assert replay.daily.accounting_qualified.all()


def test_ex_snapshot_uses_old_raw_shares_before_same_session_split():
    data=inputs(prices=(100,100,45,45,45))
    split=CorporateActionTransition("2024-01-04","FORWARD_SPLIT","old","new","S","S",2.,0.,
        "TIER2_LOCAL_CANONICAL","synthetic://split","a"*64)
    replay=run_continuous_account(data,["p"],hold,account(),corporate_actions=[split],
        corporate_action_known_at={split.event_fingerprint:"2024-01-03 12:00:00+00:00"},**entitlement_args([event()]))
    assert replay.daily.nav.tolist()==pytest.approx([3000]*5)
    assert replay.final_state["fractional_shares"][0,0]==60
    assert replay.final_state["cash"][0]==300
    snap=replay.entitlements.loc[replay.entitlements.phase.eq("EX_PRETRADE_RAW_SHARE_SNAPSHOT")]
    assert snap.entitled_raw_shares.tolist()==[30]
    assert replay.positions.entry_price.iloc[-1]==50


def test_late_source_blocks_only_pre_ex_holder_and_never_late_pays():
    late=event(available_at="2024-01-04 15:00:00+00:00")
    def policy(j,ctx):
        weights=np.zeros_like(ctx.current_weights)
        if j==0: weights[0,0]=1
        if j==2: weights[1,0]=1
        return TargetDecision(weights,ctx.decision_mask)
    replay=run_continuous_account(inputs(),["held","later"],policy,account(),**entitlement_args([late]))
    assert replay.final_state["accounting_qualified"].tolist()==[False,True]
    assert replay.daily.entitlement_cash_flow_usd.eq(0).all()
    assert replay.daily.receivable_value_usd.eq(0).all()
    assert replay.daily.loc[replay.daily.path_id.eq("later"),"certified_nav"].notna().all()
    assert replay.accounting_exceptions.path_id.tolist()==["held"]


def test_crossyear_outstanding_claim_and_prefix_replay_identity():
    data=inputs(prices=(100,100,90,90), dates=["2024-12-27","2024-12-30","2024-12-31","2025-01-02"])
    dividend=event(ex_date="2024-12-31",record_date="2024-12-31",pay_date="2025-01-01",available_at="2024-12-30 12:00:00+00:00")
    first=run_continuous_account(inputs(prices=(100,100,90),dates=data.dates[:3].tolist()),["p"],hold,account(),**entitlement_args([dividend]))
    assert first.final_state["receivable_value_usd"].tolist()==[300]
    assert first.final_state["cash_receivables"][0]["pay_date"]=="2025-01-01"
    later=run_continuous_account(data,["p"],hold,account(),previous_prefix=first.prefix_identity,**entitlement_args([dividend]))
    assert account_prefix_identity(later,first.prefix_identity["end_session"])==first.prefix_identity
    assert later.final_state["cash"][0]==300
    assert later.final_state["receivable_value_usd"].tolist()==[0]
    assert later.positions.holding_age.tolist()==[0,1,2]


def test_required_source_binder_rejects_implicit_or_mismatched_authority():
    dividend=event()
    with pytest.raises(ValueError,match="SOURCE_COVERAGE_BINDING_REQUIRED"):
        run_continuous_account(inputs(),["p"],hold,account(),entitlement_enabled=True,entitlement_events=[dividend])
    args=entitlement_args([dividend]);args['entitlement_source_binding']['event_fingerprints']=[]
    with pytest.raises(ValueError,match="CATALOGUE_MISMATCH"):
        run_continuous_account(inputs(),["p"],hold,account(),**args)
    with pytest.raises(ValueError,match="EXPLICIT_OPT_IN"):
        run_continuous_account(inputs(),["p"],hold,account(),entitlement_events=[dividend])
    historical=event(ex_date="2023-12-28",record_date="2023-12-28",pay_date="2024-01-05",available_at="2023-12-27 12:00:00+00:00")
    replay=run_continuous_account(inputs(),["p"],hold,account(),**entitlement_args([historical]))
    assert replay.accounting_exceptions.empty and replay.entitlements.empty
    assert replay.daily.accounting_qualified.all()


@pytest.mark.parametrize('bps',[0,5,10,20])
def test_slippage_actual_fill_cash_scaling_and_no_double_charge(bps):
    data=inputs(prices=(100,100,100,100,100))
    def policy(j,ctx):
        return TargetDecision(np.ones_like(ctx.current_weights) if j==0 else np.zeros_like(ctx.current_weights),ctx.decision_mask)
    replay=run_continuous_account(data,["p"],policy,account(),execution_friction=friction(bps))
    rate=bps/10000
    buy,sell=replay.fills.iloc[0],replay.fills.iloc[1]
    assert buy.price==100 and buy.raw_Open==100 and sell.price==100
    assert buy.actual_fill_price==pytest.approx(100*(1+rate))
    assert sell.actual_fill_price==pytest.approx(100*(1-rate))
    assert buy.actual_fill_notional==pytest.approx(3000)
    assert replay.daily.buy_cash_scale.iloc[1]==pytest.approx(1/(1+rate))
    assert buy.index_units==pytest.approx(30/(1+rate))
    expected=3000*(1-rate)/(1+rate)
    assert replay.final_cash[0]==pytest.approx(expected)
    assert replay.fills.transaction_fee.eq(0).all()
    assert np.allclose(replay.fills.transaction_cost,replay.fills.slippage_amount)
    assert np.allclose(replay.fills.actual_fill_price*replay.fills.index_units,replay.fills.actual_fill_notional)
    assert replay.daily.actual_cash_flow_identity_error.abs().max()<1e-8


def test_paid_entitlement_and_slippage_share_the_real_cash_budget():
    replay=run_continuous_account(inputs(),["p"],rebalance,account(),execution_friction=friction(10),**entitlement_args([event()]))
    assert replay.daily.buy_cash_scale.iloc[2:4].tolist()==pytest.approx([0,0])
    paid=replay.daily.entitlement_cash_flow_usd.iloc[4]
    assert paid==pytest.approx(300/(1+.001))
    assert replay.daily.actual_buy_notional.iloc[4]==pytest.approx(paid)
    assert replay.final_cash[0]==pytest.approx(0,abs=1e-8)
    assert replay.daily.accounting_qualified.all()


@pytest.mark.parametrize('change',[{'one_way_bps':25},{'one_way_bps':True},{'fee_bps':1},{'authority':'ACTUAL_QUOTE'}])
def test_friction_requires_frozen_hypothetical_scenario(change):
    contract=friction();contract.update(change)
    with pytest.raises(ValueError,match="INVALID_FROZEN"):
        run_continuous_account(inputs(),["p"],hold,account(),execution_friction=contract)


def test_old_wrapper_default_is_exact_and_explicit_zero_preserves_economics():
    source=Path('D:/us-tech-quant-results/JOINT_TOP20_PORTFOLIO_POLICY_PRE2026_TEST2026_R1/V24/receipts/source_audit/continuous_research_account_99038f036431c91b1070fe52d5bdbbd057c617356a8b839c295c6c4bf0742d00.py')
    if not source.exists(): pytest.skip('preserved source audit is task-local')
    spec=importlib.util.spec_from_file_location('_old_continuous_synthetic_reference',source)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
    try:
        spec.loader.exec_module(module)
        data=inputs(prices=(100,101,99,100,101))
        old=module.run_continuous_account(data,["p"],hold,account())
        new=run_continuous_account(data,["p"],hold,account())
        for table in ('daily','positions','fills','orders','execution_results','contexts','operational_actions'):
            assert_frame_equal(getattr(old,table),getattr(new,table),check_exact=True)
        assert old.metadata==new.metadata and old.audit==new.audit
        assert old.prefix_identity==new.prefix_identity
        zero=run_continuous_account(data,["p"],hold,account(),execution_friction=friction(0))
        for table in ('daily','positions','fills','orders','execution_results','contexts','operational_actions'):
            expected=getattr(new,table);assert_frame_equal(expected,getattr(zero,table)[expected.columns],check_exact=True)
        assert new.prefix_identity==zero.prefix_identity
        opted=run_continuous_account(data,["p"],hold,account(),**entitlement_args([]))
        for table in ('daily','positions','fills','orders','execution_results','contexts','operational_actions'):
            expected=getattr(new,table);assert_frame_equal(expected,getattr(opted,table)[expected.columns],check_exact=True)
        for key,value in new.audit.items(): assert opted.audit[key]==value
    finally:
        sys.modules.pop(spec.name,None)


def test_unsupported_event_isolated_by_actual_pretrade_holder():
    data=inputs(prices=np.column_stack([np.full(5,100.),np.full(5,50.)]),tickers=("S","B"))
    def policy(j,ctx):
        weights=np.zeros_like(ctx.current_weights)
        if j==0: weights[0,0]=1.;weights[1,1]=1.
        return TargetDecision(weights,ctx.decision_mask)
    unknown=[dict(ticker="S",effective_date="2024-01-04",reason="MISSING_SOURCE_TERMS")]
    replay=run_continuous_account(data,["heldS","otherB"],policy,account(),unsupported_events=unknown,
        **entitlement_args([]))
    assert replay.final_state['accounting_qualified'].tolist()==[False,True]
    assert replay.accounting_exceptions.path_id.tolist()==['heldS']
    assert replay.daily.loc[replay.daily.path_id.eq('otherB'),'accounting_qualified'].all()


def test_sell_then_buy_same_open_uses_net_slippage_proceeds_once():
    data=inputs(prices=np.column_stack([np.full(5,100.),np.full(5,50.)]),tickers=("S","B"))
    def policy(j,ctx):
        weights=np.zeros_like(ctx.current_weights)
        if j==0: weights[0,0]=1.
        elif j==1: weights[0,1]=1.
        return TargetDecision(weights,ctx.decision_mask)
    replay=run_continuous_account(data,['p'],policy,account(),execution_friction=friction(10))
    switch=replay.fills.loc[replay.fills.execution_date.eq(pd.Timestamp('2024-01-04'))]
    assert switch.side.tolist()==['SELL','BUY']
    assert switch.actual_fill_notional.iloc[1]==pytest.approx(switch.actual_fill_notional.iloc[0])
    assert replay.daily.buy_cash_scale.iloc[2]==pytest.approx((1-.001)/(1+.001))
    assert replay.daily.actual_cash_flow_identity_error.abs().max()<1e-8


def test_engine_source_guard_and_entitlement_catalogue_duplicates_fail_closed(monkeypatch):
    import scripts.research.a2.evaluation.continuous_research_account as wrapper
    monkeypatch.setattr(wrapper,'ENTITLEMENT_ENGINE_SHA256','0'*64)
    with pytest.raises(ValueError,match='IMMUTABLE_ENGINE_SOURCE_CHANGED'):
        _engine_with_entitlement_hook(lambda *a: None)
    duplicate=event()
    with pytest.raises(ValueError,match='CATALOGUE_MISMATCH'):
        run_continuous_account(inputs(),['p'],hold,account(),**entitlement_args([duplicate,duplicate]))


def test_pending_claim_pay_terms_are_part_of_the_semantic_prefix_identity():
    data=inputs(prices=(100,100,90),dates=['2024-01-02','2024-01-03','2024-01-04'])
    first=run_continuous_account(data,['p'],hold,account(),**entitlement_args([event(pay_date='2024-01-05')]))
    later_terms=run_continuous_account(data,['p'],hold,account(),**entitlement_args([event(pay_date='2024-01-08')]))
    assert first.daily.nav.tolist()==later_terms.daily.nav.tolist()
    assert first.prefix_identity['sha256']!=later_terms.prefix_identity['sha256']


def test_twenty_name_full_investment_entitlement_hook_receives_engine_clamped_cash(monkeypatch):
    import scripts.research.a2.evaluation.continuous_research_account as wrapper
    dates=pd.bdate_range('2024-02-01',periods=22)
    tickers=tuple(f'S{i:02d}' for i in range(20))
    matrix=(np.linspace(11.37,271.29,20)[None,:]
            * (1.+.011*np.sin(np.arange(22)[:,None]+np.arange(20)[None,:])))
    data=MarketArrays(dates,tickers,matrix.copy(),matrix.copy(),adv=np.full(matrix.shape,1e9))
    def policy(j,ctx):
        values=.02+.003*((np.arange(20)+j)%7)
        values=values/values.sum()
        return TargetDecision(values[None,:],ctx.decision_mask)
    seen=[]
    original=wrapper.apply_entitlement_lifecycle
    def spy(events,positions,cash,**kwargs):
        seen.append(cash)
        assert cash>=0
        return original(events,positions,cash,**kwargs)
    monkeypatch.setattr(wrapper,'apply_entitlement_lifecycle',spy)
    native=run_continuous_account(data,['p'],policy,account(),execution_friction=friction(10))
    opted=run_continuous_account(data,['p'],policy,account(),execution_friction=friction(10),**entitlement_args([]))
    assert len(seen)==22 and min(seen)>=0
    assert (native.daily.buy_cash_scale<1).any()
    assert native.audit['max_actual_names']==20
    for table in ('daily','positions','fills','orders','execution_results','contexts','operational_actions'):
        expected=getattr(native,table)
        assert_frame_equal(expected,getattr(opted,table)[expected.columns],check_exact=True)
    assert native.audit==opted.audit



def terminal(**changes):
    fields=dict(event_id="terminal",old_security_id="secS",ticker="S",
        effective_at="2024-01-04T14:30:00Z",available_at="2024-01-03T12:00:00Z",
        cash_per_old_share=5.,currency="USD",amount_unit=USD_PER_RAW_OLD_SHARE,
        quantity_coordinate=RAW_OLD_SHARE_COORDINATE,
        quantity_source_reference="synthetic://post-split-raw-coordinate",quantity_source_fingerprint="b"*64,
        source_type="TIER2_LOCAL_CANONICAL",source_reference="synthetic://closing",source_fingerprint="c"*64)
    fields.update(changes)
    return SourceBackedTerminalEvent(**fields)


def terminal_payment(**changes):
    fields=dict(event_id="terminal",old_security_id="secS",pay_date="2024-01-08",
        available_at="2024-01-05T12:00:00Z",cash_per_old_share=5.,currency="USD",
        amount_unit=USD_PER_RAW_OLD_SHARE,quantity_coordinate=RAW_OLD_SHARE_COORDINATE,
        source_type="TIER2_LOCAL_CANONICAL",source_reference="synthetic://payment",source_fingerprint="f"*64)
    fields.update(changes)
    return SourceBackedTerminalSettlement(**fields)


def test_terminal_removes_old_shares_and_mark_without_sale_or_rebuy():
    data=inputs(prices=(100,100,999,777,555))
    raw=data.open.copy();rows=data.row_present.copy()
    replay=run_continuous_account(data,['p'],rebalance,account(),execution_friction=friction(10),**entitlement_args([terminal()]))
    qty=30/1.001
    assert replay.fills.side.tolist()==['BUY']
    assert replay.final_state['fractional_shares'][0,0]==0 and replay.final_state['holding_age'][0,0]==-1
    assert replay.positions.date.max()==pd.Timestamp('2024-01-03')
    assert replay.daily.receivable_value_usd.tolist()==pytest.approx([0,0,5*qty,5*qty,5*qty])
    assert replay.daily.cash.tolist()==pytest.approx([3000,0,0,0,0],abs=1e-8)
    assert replay.daily.transaction_cost_amount.iloc[2:].eq(0).all()
    assert replay.daily.accounting_qualified.tolist()==[True,True,False,False,False]
    assert replay.daily.certified_nav.iloc[2:].isna().all() and replay.daily.net_return.iloc[2:].isna().all()
    assert replay.metadata['terminal_settlement_qualified_by_path']=={'p':False}
    assert replay.daily.actual_cash_flow_identity_error.abs().max()<1e-8
    assert np.array_equal(data.open,raw) and np.array_equal(data.row_present,rows)
    assert replay.final_state['cash_receivables'][0]['entitled_raw_shares']==pytest.approx(qty)
    assert replay.entitlements.ex_date.isna().all() and replay.entitlements.record_date.isna().all()


def test_terminal_prior_signal_buy_has_no_shares_or_cash_right():
    def late(j,ctx):
        return TargetDecision(np.ones_like(ctx.current_weights),ctx.decision_mask) if j==1 else TargetDecision(
            np.zeros_like(ctx.current_weights),np.zeros_like(ctx.decision_mask))
    replay=run_continuous_account(inputs(),['p'],late,account(),**entitlement_args([terminal()]))
    assert replay.fills.empty and replay.final_cash.tolist()==[3000]
    assert replay.daily.receivable_value_usd.eq(0).all() and replay.daily.accounting_qualified.all()
    assert replay.entitlements.empty and replay.execution_results.reason.eq('MISSING_PRICE_ROW').any()


def test_terminal_raw_runtime_quantity_after_reverse_split_not_divided_twice():
    data=inputs(prices=(10,10,100,999,777))
    split=CorporateActionTransition('2024-01-04','REVERSE_SPLIT','old','new','S','S',.1,0.,
        'TIER2_LOCAL_CANONICAL','synthetic://reverse-split','a'*64)
    e=terminal(effective_at='2024-01-05T14:30:00Z')
    replay=run_continuous_account(data,['p'],hold,account(),corporate_actions=[split],
        corporate_action_known_at={split.event_fingerprint:'2024-01-03T12:00:00Z'},**entitlement_args([e]))
    snapshot=replay.entitlements.loc[replay.entitlements.phase.eq('TERMINAL_PRE_EFFECTIVE_RAW_SHARE_SNAPSHOT')].iloc[0]
    assert snapshot.entitled_raw_shares==30 and snapshot.pre_effective_engine_units==300
    assert snapshot.pre_effective_quantity_factor==.1
    assert replay.final_state['receivable_value_usd'].tolist()==[150]
    assert replay.final_state['fractional_shares'][0,0]==0


def test_terminal_payment_funds_other_stock_only_at_authorized_open():
    data=inputs(prices=np.column_stack([np.full(5,100.),np.full(5,50.)]),tickers=('S','B'))
    def policy(j,ctx):
        weights=np.zeros_like(ctx.current_weights);weights[0,0 if j==0 else 1]=1.
        return TargetDecision(weights,ctx.decision_mask)
    replay=run_continuous_account(data,['p'],policy,account(),execution_friction=friction(10),
        **entitlement_args([terminal(settlement=terminal_payment())]))
    assert replay.fills.ticker.tolist()==['S','B'] and replay.fills.side.tolist()==['BUY','BUY']
    assert replay.fills.execution_date.iloc[1]==pd.Timestamp('2024-01-08')
    paid=replay.daily.entitlement_cash_flow_usd.iloc[-1]
    assert paid==pytest.approx(150/1.001) and replay.daily.actual_buy_notional.iloc[-1]==pytest.approx(paid)
    assert replay.final_cash[0]==pytest.approx(0,abs=1e-8)
    assert replay.daily.accounting_qualified.all() and replay.daily.certified_nav.notna().all()
    assert replay.final_state['cash_receivables']==() and replay.audit['nav_identity_error_max']<1e-8
    assert replay.daily.actual_cash_flow_identity_error.abs().max()<1e-8


def test_terminal_future_settlement_hidden_from_policy_and_early_ledger():
    def capture(e):
        seen=[]
        def policy(j,ctx):
            seen.append((ctx.cash.copy(),ctx.nav.copy(),ctx.receivable_value_usd.copy(),ctx.accounting_qualified.copy()))
            return hold(j,ctx)
        run_continuous_account(inputs(),['p'],policy,account(),**entitlement_args([e]))
        return seen
    absent=capture(terminal());future=capture(terminal(settlement=terminal_payment()))
    for left,right in zip(absent[:3],future[:3]):
        for a,b in zip(left,right):np.testing.assert_array_equal(a,b)
    replay=run_continuous_account(inputs(),['p'],hold,account(),**entitlement_args([terminal(settlement=terminal_payment())]))
    assert replay.entitlements.loc[replay.entitlements.session.eq('2024-01-04'),'pay_date'].isna().all()


def test_future_terminal_keeps_earlier_dividend_prefix_and_chunk_identity():
    div=event(ex_date='2024-01-03',record_date='2024-01-03',pay_date='2024-01-03')
    e=terminal(settlement=terminal_payment())
    short=inputs(prices=(100,100),dates=['2024-01-02','2024-01-03'])
    old=run_continuous_account(short,['p'],hold,account(),**entitlement_args([div]))
    future=run_continuous_account(short,['p'],hold,account(),**entitlement_args([div,e]))
    assert old.prefix_identity==future.prefix_identity
    later=run_continuous_account(inputs(),['p'],hold,account(),previous_prefix=future.prefix_identity,**entitlement_args([div,e]))
    assert account_prefix_identity(later,future.prefix_identity['end_session'])==future.prefix_identity


def test_terminal_crossyear_pending_right_and_unknown_payment_remain_continuous():
    data=inputs(prices=(100,100,999,999),dates=['2024-12-27','2024-12-30','2024-12-31','2025-01-02'])
    e=terminal(effective_at='2024-12-31T14:30:00Z',available_at='2024-12-30T12:00:00Z')
    first=run_continuous_account(inputs(prices=(100,100,999),dates=data.dates[:3].tolist()),['p'],hold,account(),**entitlement_args([e]))
    later=run_continuous_account(data,['p'],hold,account(),previous_prefix=first.prefix_identity,**entitlement_args([e]))
    assert first.final_state['receivable_value_usd'].tolist()==later.final_state['receivable_value_usd'].tolist()==[150]
    assert later.final_state['fractional_shares'][0,0]==0 and later.final_state['cash'][0]==0
    assert account_prefix_identity(later,'2024-12-31')==first.prefix_identity


def test_terminal_missing_session_and_ambiguous_same_session_split_rejected():
    with pytest.raises(ValueError,match='EFFECTIVE_SESSION_MISSING'):
        run_continuous_account(inputs(),['p'],hold,account(),**entitlement_args([
            terminal(effective_at='2024-01-06T14:30:00Z')]))
    split=CorporateActionTransition('2024-01-04','REVERSE_SPLIT','old','new','S','S',.1,0.,
        'TIER2_LOCAL_CANONICAL','synthetic://reverse-split','a'*64)
    with pytest.raises(ValueError,match='SAME_SESSION_SHARE_TRANSFORM_PRIORITY'):
        run_continuous_account(inputs(),['p'],hold,account(),corporate_actions=[split],
            corporate_action_known_at={split.event_fingerprint:'2024-01-03T12:00:00Z'},**entitlement_args([terminal()]))


@pytest.mark.parametrize("settlement_known", [False, True],
    ids=["unknown-source", "known-synthetic-source"])
def test_terminal_after_split_crossyear_acceptance_and_path_isolation(settlement_known):
    """Exercise a pending exit, terminal right and independent account together."""
    from scripts.research.a2.training.stateful_replay import qualification_checks

    dates=["2024-12-26", "2024-12-27", "2024-12-30", "2024-12-31",
           "2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"]
    prices=(10,10,100,999,888,777,666,555)
    data=inputs(prices=prices,dates=dates)
    raw=data.open.copy();rows=data.row_present.copy()
    split=CorporateActionTransition("2024-12-30","REVERSE_SPLIT","old","new","S","S",.1,0.,
        "TIER2_LOCAL_CANONICAL","synthetic://overnight-split","a"*64)
    payment=(terminal_payment(pay_date="2025-01-06",available_at="2025-01-03T12:00:00Z")
             if settlement_known else None)
    closing=terminal(effective_at="2024-12-31T14:30:00Z",available_at="2024-12-30T12:00:00Z",
                     settlement=payment)
    kwargs=dict(corporate_actions=[split],
        corporate_action_known_at={split.event_fingerprint:"2024-12-27T12:00:00Z"},
        execution_friction=friction(10),**entitlement_args([closing]))

    def policy(j,ctx):
        weights=np.zeros_like(ctx.current_weights)
        # The exit submitted before closing must not become a market SELL.
        # Later positive wishes exercise the permanent old-security buy block.
        weights[0,0]=0. if j==2 else 1.
        return TargetDecision(weights,ctx.decision_mask)

    first=run_continuous_account(inputs(prices=prices[:4],dates=dates[:4]),
        ["held","unheld"],policy,account(),**kwargs)
    replay=run_continuous_account(data,["held","unheld"],policy,account(),
        previous_prefix=first.prefix_identity,**kwargs)
    empty=run_continuous_account(data,["unheld"],
        lambda j,ctx:TargetDecision(np.zeros_like(ctx.current_weights),ctx.decision_mask),account(),**kwargs)

    assert account_prefix_identity(replay,"2024-12-31")==first.prefix_identity
    assert np.equal(first.final_state["fractional_shares"],0).all()
    assert replay.fills.path_id.tolist()==["held"] and replay.fills.side.tolist()==["BUY"]
    entry=replay.fills.iloc[0]
    expected_raw=entry.index_units*.1
    expected_right=expected_raw*5.
    records=replay.entitlements.loc[replay.entitlements.path_id.eq("held")]
    snapshot=records.loc[records.phase.eq("TERMINAL_PRE_EFFECTIVE_RAW_SHARE_SNAPSHOT")].iloc[0]
    extinct=records.loc[records.phase.eq("SECURITY_EXTINGUISHED")]
    claim=records.loc[records.phase.eq("MERGER_RECEIVABLE_RECOGNIZED")]
    assert snapshot.entitled_raw_shares==pytest.approx(expected_raw)
    assert snapshot.pre_effective_engine_units==pytest.approx(entry.engine_index_units_after)
    assert snapshot.pre_effective_quantity_factor==.1
    assert len(extinct)==len(claim)==1 and extinct.remaining_raw_shares.eq(0).all()
    assert extinct.spendable_cash_delta.eq(0).all() and claim.spendable_cash_delta.eq(0).all()
    assert claim.amount_usd.iloc[0]==pytest.approx(expected_right)
    assert records.currency.eq("USD").all() and records.amount_unit.eq(USD_PER_RAW_OLD_SHARE).all()
    assert records.quantity_coordinate.eq(RAW_OLD_SHARE_COORDINATE).all()
    assert records.receivable_id.nunique()==1
    assert records.loc[records.session.eq("2024-12-31"),"pay_date"].isna().all()
    before_close=replay.positions.loc[replay.positions.path_id.eq("held")
        & replay.positions.date.eq(pd.Timestamp("2024-12-30"))].iloc[0]
    assert before_close.fractional_shares==pytest.approx(expected_raw)
    assert first.final_state["receivable_value_usd"].tolist()==pytest.approx([expected_right,0])
    assert first.final_state["cash_receivables"][0]["pay_date"] is None
    assert replay.positions.date.max()==pd.Timestamp("2024-12-30")
    exit_intent=replay.orders.loc[replay.orders.path_id.eq("held")
        & replay.orders.signal_date.eq(pd.Timestamp("2024-12-30"))]
    assert exit_intent.decision_semantic.tolist()==["MODEL_ACTIVE_EXIT"]
    assert replay.execution_results.terminal_cancellation_reason.eq(
        "SOURCE_BACKED_OLD_SECURITY_EXTINGUISHED").any()
    assert np.equal(replay.final_state["fractional_shares"],0).all()
    assert replay.final_state["holding_age"].tolist()==[[-1],[-1]]
    assert np.array_equal(data.open,raw) and np.array_equal(data.row_present,rows)

    daily=replay.daily.loc[replay.daily.path_id.eq("held")]
    closed=daily.date.ge(pd.Timestamp("2024-12-31"))
    assert daily.loc[closed,"nav"].tolist()==pytest.approx([expected_right]*5)
    assert daily.loc[closed & daily.date.lt(pd.Timestamp("2025-01-06")),"receivable_value_usd"].tolist()==pytest.approx([expected_right]*3)
    assert daily.loc[closed & daily.date.lt(pd.Timestamp("2025-01-06")),"cash"].eq(0).all()
    paid=records.loc[records.phase.eq("CASH_PAID")]
    assert replay.daily.actual_cash_flow_identity_error.abs().max()<1e-8
    assert replay.daily.cash_flow_identity_error.abs().max()<1e-8
    assert replay.audit["nav_identity_error_max"]<1e-8
    values=replay.positions.groupby(["path_id","date"]).market_value.sum()
    marked=pd.MultiIndex.from_frame(replay.daily[["path_id","date"]]).map(values).fillna(0).to_numpy()
    np.testing.assert_allclose(replay.daily.nav,replay.daily.cash+marked+replay.daily.receivable_value_usd,atol=1e-8,rtol=0)
    assert replay.metadata["terminal_settlement_qualified_by_path"]=={"held":settlement_known,"unheld":True}
    if settlement_known:
        assert len(paid)==1 and paid.session.iloc[0]=="2025-01-06"
        assert paid.spendable_cash_delta.iloc[0]==pytest.approx(expected_right)
        assert daily.entitlement_cash_flow_usd.tolist()==pytest.approx([0,0,0,0,0,0,expected_right,0])
        assert replay.final_state["cash"][0]==pytest.approx(expected_right)
        assert replay.final_state["receivable_value_usd"][0]==0 and replay.final_state["cash_receivables"]==()
        assert daily.accounting_qualified.all() and daily.certified_nav.notna().all()
    else:
        assert paid.empty and daily.entitlement_cash_flow_usd.eq(0).all()
        assert replay.final_state["cash"][0]==0
        assert replay.final_state["receivable_value_usd"][0]==pytest.approx(expected_right)
        assert replay.final_state["cash_receivables"][0]["pay_date"] is None
        assert not daily.loc[closed,"accounting_qualified"].any()
        assert daily.loc[closed,"certified_nav"].isna().all() and daily.loc[closed,"net_return"].isna().all()
        checks=qualification_checks(replay,"held")
        assert checks["terminal_settlement_qualified"] is False and checks["eligible_for_selection"] is False
        assert checks["status"]=="NOT_TESTABLE_REQUIRED_BASELINE"
        assert replay.accounting_exceptions.path_id.unique().tolist()==["held"]
    assert_frame_equal(replay.daily.loc[replay.daily.path_id.eq("unheld")].reset_index(drop=True),
                       empty.daily.reset_index(drop=True),check_exact=True)
    assert replay.entitlements.path_id.unique().tolist()==["held"]
    checks=qualification_checks(replay,"unheld")
    assert checks["accounting_qualified"] and checks["entitlement_identity_correct"] and checks["terminal_settlement_qualified"]


# Same-ticker identity changes use the existing share-transition source only.
def alias_transition(**changes):
    fields = dict(effective_date="2024-01-05", action_type="REVERSE_SPLIT",
        old_security_id="secS", new_security_id="secNew", old_ticker="S", new_ticker="S",
        quantity_multiplier=.5, cash_component_per_old_share=0.,
        source_type="TIER2_LOCAL_CANONICAL", source_reference="synthetic://dated-identity-split",
        source_fingerprint="a"*64)
    fields.update(changes)
    return CorporateActionTransition(**fields)


def alias_args(events, transition=None):
    transition = transition or alias_transition()
    return dict(**entitlement_args(events, {"secS":"S", "secNew":"S"}),
        corporate_actions=[transition],
        corporate_action_known_at={transition.event_fingerprint:"2024-01-04T12:00:00Z"})


def test_dated_alias_old_claim_pays_after_change_new_dividend_uses_new_raw_quantity(monkeypatch):
    from scripts.research.a2.evaluation import continuous_research_account as owner
    days = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09", "2024-01-10"]
    old = event(pay_date="2024-01-09")
    new = event(event_id="new-div", old_security_id="secNew", ex_date="2024-01-08",
        record_date="2024-01-08", pay_date="2024-01-10", cash_per_old_share=2.,
        available_at="2024-01-04T12:00:00Z")
    captured=[]
    original=owner.apply_entitlement_lifecycle
    def observe(events, positions, cash, **kwargs):
        captured.append((dict(positions), dict(kwargs['security_tickers'])))
        return original(events, positions, cash, **kwargs)
    monkeypatch.setattr(owner, 'apply_entitlement_lifecycle', observe)
    replay=run_continuous_account(inputs((100,100,90,180,178,178,178), days), ['p'], hold,
        account(), **alias_args([old,new]))
    assert replay.daily.nav.tolist()==pytest.approx([3000]*7)
    assert replay.daily.receivable_value_usd.tolist()==pytest.approx([0,0,300,300,330,30,0])
    assert replay.daily.entitlement_cash_flow_usd.tolist()==pytest.approx([0,0,0,0,0,300,30])
    assert replay.final_state['fractional_shares'][0,0]==15
    assert replay.final_cash[0]==330
    assert captured[2][0]=={'secS':30.,'secNew':0.}
    assert captured[3][0]=={'secS':0.,'secNew':15.}
    assert all(mapping=={'secS':'S','secNew':'S'} for _,mapping in captured)
    snapshots=replay.entitlements.loc[replay.entitlements.phase.eq('EX_PRETRADE_RAW_SHARE_SNAPSHOT')]
    assert snapshots.entitled_raw_shares.tolist()==[30.,15.]
    assert replay.daily.accounting_qualified.all()
    assert replay.audit['nav_identity_error_max']<1e-8


def test_dated_alias_fresh_window_after_change_has_no_old_claim_or_duplicate_quantity():
    days=['2024-01-05','2024-01-08','2024-01-09','2024-01-10','2024-01-11']
    old=event(pay_date='2024-01-10')
    new=event(event_id='new-div',old_security_id='secNew',ex_date='2024-01-10',
        record_date='2024-01-10',pay_date='2024-01-11',cash_per_old_share=2.,available_at='2024-01-04T12:00:00Z')
    replay=run_continuous_account(inputs((180,180,180,178,178),days),['p'],hold,account(),**alias_args([old,new]))
    assert replay.daily.nav.tolist()==pytest.approx([3000]*5)
    assert replay.final_state['fractional_shares'][0,0]==pytest.approx(3000/180)
    assert replay.final_cash[0]==pytest.approx(2*3000/180)
    assert set(replay.entitlements.event_id)=={'new-div'}


@pytest.mark.parametrize('changes',[
    {'corporate_actions':[]},
    {'corporate_action_known_at':{}},
    {'late':True},
    {'transition_change':{'new_ticker':'OTHER'}},
    {'transition_change':{'cash_component_per_old_share':1.}},
    {'transition_change':{'repair_authorized':False}},
    {'transition_change':{'source_reference':''}},
])
def test_dated_alias_requires_source_backed_available_same_ticker_share_chain(changes):
    from scripts.research.a2.evaluation import continuous_research_account as owner
    args=alias_args([event()])
    if 'transition_change' in changes:
        args=alias_args([event()],alias_transition(**changes['transition_change']))
    elif changes.get('late'):
        args['corporate_action_known_at']={args['corporate_actions'][0].event_fingerprint:'2024-01-05T14:31:00Z'}
    else:
        args.update(changes)
    with pytest.raises(ValueError,match='ENTITLEMENT_'):
        owner._entitlement_binding(args['entitlement_events'],args['entitlement_security_tickers'],
            args['entitlement_source_binding'],corporate_actions=args['corporate_actions'],
            corporate_action_known_at=args['corporate_action_known_at'])


@pytest.mark.parametrize('wrong_event',[
    event(old_security_id='secNew'),
    event(ex_date='2024-01-08',record_date='2024-01-08',pay_date='2024-01-09'),
    event(ex_date='2024-01-05',record_date='2024-01-05',pay_date='2024-01-09'),
    terminal(effective_at='2024-01-05T14:30:00Z'),
])
def test_dated_alias_rejects_wrong_sid_date_and_ambiguous_same_day_ex_or_terminal(wrong_event):
    with pytest.raises(ValueError,match='DATED_SECURITY_IDENTITY|SAME_SESSION_ENTITLEMENT'):
        run_continuous_account(inputs(),['p'],hold,account(),**alias_args([wrong_event]))


def test_dated_alias_rejects_branching_or_reversed_chain():
    from scripts.research.a2.evaluation import continuous_research_account as owner
    first=alias_transition()
    second=alias_transition(effective_date='2024-01-08',new_security_id='secThird')
    args=entitlement_args([],{'secS':'S','secNew':'S','secThird':'S'})
    known={e.event_fingerprint:'2024-01-04T12:00:00Z' for e in [first,second]}
    with pytest.raises(ValueError,match='LINEAR_FORWARD_CHAIN'):
        owner._entitlement_binding([],args['entitlement_security_tickers'],args['entitlement_source_binding'],
            corporate_actions=[first,second],corporate_action_known_at=known)


def test_runner_preflight_passes_existing_transition_evidence_to_alias_owner(monkeypatch,tmp_path):
    from types import SimpleNamespace
    from scripts.research.a2.evaluation import aggregate_frozen_runner as runner
    window={'window_id':'SYNTHETIC'}
    admitted=SimpleNamespace(task_id='SYNTHETIC',window_id='SYNTHETIC',end=pd.Timestamp('2026-10-07'))
    args=alias_args([])
    kwargs={k:v for k,v in args.items() if not k.startswith('corporate_action')}
    kwargs.update(events=args['corporate_actions'],known_at=args['corporate_action_known_at'])
    groups={'stocks':{'market':inputs(),'account_source_kwargs':kwargs}}
    monkeypatch.setattr(runner.authority,'load_descriptive_authority',lambda x:x)
    monkeypatch.setattr(runner.authority,'validate_reconstructed_accounting_events',lambda *a,**kw:None)
    monkeypatch.setattr(runner,'_window_inputs',lambda *a:groups)
    monkeypatch.setattr(runner.execution,'own_path',lambda root,p:p)
    monkeypatch.setattr(runner,'write_json_atomic',lambda *a:None)
    report=runner.preflight(dict(task_id='SYNTHETIC',schedule={'windows':[window]},candidates=[],
        inference_manifest_ref={},run=tmp_path),authority_for_window=lambda w:admitted,
        account_sources_for_window=lambda *a:{})
    assert report['account_executions']==report['model_predict_calls']==0
    assert len(report['windows'])==1


@pytest.mark.parametrize('sid,day', [('secS','2024-01-08'),('secNew','2024-01-04')])
def test_dated_alias_rejects_share_action_with_retired_or_future_sid(sid,day):
    from scripts.research.a2.evaluation import continuous_research_account as owner
    args=alias_args([])
    action=alias_transition(effective_date=day,old_security_id=sid,new_security_id=sid)
    args['corporate_actions'].append(action)
    with pytest.raises(ValueError,match='SHARE_ACTION_DATED_SECURITY_IDENTITY'):
        owner._entitlement_binding([],args['entitlement_security_tickers'],args['entitlement_source_binding'],
            corporate_actions=args['corporate_actions'],corporate_action_known_at=args['corporate_action_known_at'])


# Full-selector authority transports existing source facts into a new research
# scope. Every input below is synthetic; no real source, result, or run is read.
def full_selector_catalogue():
    from scripts.v22 import corporate_action_transition_r1 as ca
    cash = ca.ResearchReconstructedCashEvent(event_id="synthetic_ordinary", action_type="CASH_DIVIDEND",
        old_security_id="secS", ticker="S", ex_date="2025-04-25", record_date="2025-04-25",
        pay_date="2025-04-25", available_at=None, cash_per_old_share=1., currency="USD",
        amount_unit=USD_PER_RAW_OLD_SHARE, quantity_coordinate=RAW_OLD_SHARE_COORDINATE,
        source_type="TIER2_LOCAL_CANONICAL", source_reference="synthetic://ordinary",
        source_fingerprint="e" * 64, reconstruction_ref="D:/synthetic/ordinary.json",
        reconstruction_sha256="e" * 64, source_scope="B_FROZEN_PRE2026_ACCOUNTING_ONLY")
    terminal = ca.ResearchReconstructedTerminalEvent(event_id="synthetic_MKFG", old_security_id="secMKFG",
        ticker="MKFG", effective_at="2025-04-25T13:30:00+00:00", available_at=None,
        cash_per_old_share=5., currency="USD", amount_unit=USD_PER_RAW_OLD_SHARE,
        quantity_coordinate=RAW_OLD_SHARE_COORDINATE, quantity_source_reference="synthetic://raw-share",
        quantity_source_fingerprint="a" * 64, source_type="TIER2_LOCAL_CANONICAL",
        source_reference="synthetic://terminal", source_fingerprint="b" * 64,
        effective_clock_basis="SOURCE_EFFECTIVE_BY_OPEN_UPPER_BOUND",
        reconstruction_ref="D:/synthetic/MKFG.json", reconstruction_sha256="f" * 64)
    admission = dict(schema="B_FROZEN_HISTORY_POST_VERIFIED_CASH_ADMISSION_V1",
        scientific_identity="FROZEN_HISTORY_RESEARCH_ACCOUNT", task_id="V24_B_FAST_TRACK_PAIR_COMPLETION_R1",
        clock_role="POST_VERIFIED_ACCOUNTING_ONLY",
        accounting_clock_convention="ORDINARY_CASH_PAY_DATE_END_NEXT_ACCOUNT_SESSION",
        scope_start="2023-01-01", scope_end_exclusive="2026-01-01",
        strict_PIT=False, production_qualified=False, quote_qualified=False, certified_NAV=False,
        source_contract_ref=dict(path="D:/synthetic/B_source.json", sha256="1" * 64),
        source_binding_fingerprint="2" * 64, events=[dict(event_fingerprint=cash.event_fingerprint,
            source_projection_ref=dict(path=cash.reconstruction_ref, sha256=cash.reconstruction_sha256),
            publication_available_at=None, historical_availability_qualified=False,
            clock_role="POST_VERIFIED_ACCOUNTING_ONLY")])
    terminal_authority = dict(scientific_identity="FROZEN_HISTORY_RESEARCH_ACCOUNT",
        task_id="V24_A_FROZEN_HISTORY_RESEARCH_ACCOUNT_AND_POLICY_EVALUATION_R1",
        clock_role="RECONSTRUCTED_REALIZED_EVENT", frozen_contract_sha256="3" * 64,
        event_fingerprints=[terminal.event_fingerprint], strict_PIT_promotion_eligible=False,
        production_qualified=False)
    authority = dict(schema="C_FULL_SELECTOR_FIXED_POLICY_ACCOUNT_AUTHORITY_V1",
        scientific_identity="FULL_SELECTOR_FIXED_POLICY_RESEARCH_ACCOUNT",
        task_id="V24_C_FULL_SELECTOR_FIXED_POLICY_FAST_R1", clock_role="POST_VERIFIED_ACCOUNTING_ONLY",
        accounting_clock_convention="ORDINARY_CASH_PAY_DATE_END_NEXT_ACCOUNT_SESSION",
        scope_start="2023-01-01", scope_end_exclusive="2026-01-01",
        strict_PIT_promotion_eligible=False, production_qualified=False,
        quote_qualified=False, certified_NAV=False,
        frozen_contract_ref=dict(path="D:/synthetic/C_contract.json", sha256="4" * 64),
        event_fingerprints=[cash.event_fingerprint, terminal.event_fingerprint],
        ordinary_cash_event_fingerprints=[cash.event_fingerprint],
        frozen_history_cash_admission=admission, terminal_source_authority=terminal_authority)
    return cash, terminal, authority


def test_full_selector_composite_preserves_original_sources_and_pending_terminal():
    from scripts.v22 import corporate_action_transition_r1 as ca
    cash, terminal, authority = full_selector_catalogue()
    result = ca._validate_research_account_authority((cash, terminal), authority)
    assert result == authority
    assert result["terminal_source_authority"]["task_id"].startswith("V24_A_")
    assert result["frozen_history_cash_admission"]["task_id"].startswith("V24_B_")
    kwargs = dict(events=(cash, terminal), security_tickers={"secS": "S", "secMKFG": "MKFG"},
        quantity_coordinate=RAW_OLD_SHARE_COORDINATE, enabled=True, research_account_authority=authority)
    ex = ca.apply_entitlement_lifecycle(positions_by_security_id={"secS": 2., "secMKFG": 3.},
        cash=10., execution_date="2025-04-25", session_open_at="2025-04-25T13:30:00+00:00", **kwargs)
    assert ex.positions == {"secS": 2., "secMKFG": 0.}
    assert ex.cash == 10. and ex.receivable_value_usd == 17.
    assert {r.event_id: r.pay_date for r in ex.state.receivables} == {
        cash.event_id: "2025-04-26", terminal.event_id: None}
    # Selling S after its ex snapshot cannot destroy the ordinary claim.
    later = ca.apply_entitlement_lifecycle(positions_by_security_id={"secS": 0., "secMKFG": 0.},
        cash=ex.cash, state=ex.state, execution_date="2025-04-28",
        session_open_at="2025-04-28T13:30:00+00:00", **kwargs)
    assert later.cash == 12. and later.receivable_value_usd == 15.
    assert [r.event_id for r in later.state.receivables] == [terminal.event_id]
    assert not any(r["phase"] == "CASH_PAID" and r["ticker"] == "MKFG" for r in later.records)
    paid = next(r for r in later.records if r["phase"] == "CASH_PAID")
    assert paid["issuer_pay_date"] == "2025-04-25"
    assert paid["spendable_not_before"] == "2025-04-26"


def test_full_selector_same_day_issuer_payment_waits_for_next_session():
    from scripts.v22 import corporate_action_transition_r1 as ca
    cash, terminal, authority = full_selector_catalogue()
    normal = event(event_id="strict_ordinary", old_security_id="secT", ticker="T", ex_date="2025-04-25", record_date="2025-04-25",
        pay_date="2025-04-25", available_at="2025-04-24T12:00:00+00:00", cash_per_old_share=1.)
    catalogue = (cash, terminal, normal)
    authority["event_fingerprints"].append(normal.event_fingerprint)
    authority["ordinary_cash_event_fingerprints"].append(normal.event_fingerprint)
    result = ca.apply_entitlement_lifecycle(catalogue, {"secS": 2., "secT": 3., "secMKFG": 0.}, 0.,
        execution_date="2025-04-25", session_open_at="2025-04-25T13:30:00+00:00",
        security_tickers={"secS": "S", "secT": "T", "secMKFG": "MKFG"}, quantity_coordinate=RAW_OLD_SHARE_COORDINATE,
        enabled=True, research_account_authority=authority)
    assert result.cash == 0. and result.receivable_value_usd == 5.
    assert all(r.pay_date == "2025-04-26" for r in result.state.receivables)
    assert not any(r["phase"] == "CASH_PAID" for r in result.records)


def test_full_selector_account_uses_one_engine_cost_and_dual_nav(monkeypatch):
    import types
    from scripts.research.a2.evaluation import continuous_research_account as owner
    cash, terminal, authority = full_selector_catalogue()
    def forbidden(*args, **kwargs):
        raise AssertionError("historical C authority must not enter the 2026 descriptive seal")
    monkeypatch.setitem(sys.modules, "scripts.research.a2.evaluation.frozen_test_authority",
                        types.SimpleNamespace(validate_reconstructed_accounting_events=forbidden))
    data = inputs(prices=[[100., 100.]] * 5,
        dates=["2025-04-23", "2025-04-24", "2025-04-25", "2025-04-28", "2025-04-29"],
        tickers=("S", "MKFG"))
    config = account(); config["max_weight"] = .05
    def policy(j, ctx):
        return TargetDecision(np.full_like(ctx.current_weights, .05 if j == 0 else 0.),
            ctx.decision_mask if j == 0 else np.zeros_like(ctx.decision_mask))
    replay = owner.run_continuous_account(data, ["Raw", "HGB"], policy, config,
        execution_friction=friction(10), research_account_authority=authority,
        **entitlement_args((cash, terminal), {"secS": "S", "secMKFG": "MKFG"}))
    assert replay.daily.actual_cash_flow_identity_error.abs().max() < 1e-8
    assert replay.audit["nav_identity_error_max"] < 1e-8
    assert replay.daily.transaction_cost_amount.sum() == pytest.approx(.6)
    assert replay.final_state["fractional_shares"][:, 1].tolist() == [0., 0.]
    assert replay.daily.loc[replay.daily.date.eq(pd.Timestamp("2025-04-25")), "entitlement_cash_flow_usd"].eq(0).all()
    assert replay.daily.loc[replay.daily.date.eq(pd.Timestamp("2025-04-28")), "entitlement_cash_flow_usd"].gt(0).all()
    assert (replay.daily.TOTAL_ECONOMIC_NAV - replay.daily.LIQUID_NAV).to_numpy() == pytest.approx(
        replay.daily.receivable_value_usd.to_numpy())
    assert replay.final_state["cash_receivables"]
    ordinary_rows = replay.entitlements.loc[replay.entitlements.ticker.eq("S")]
    assert ordinary_rows.issuer_pay_date.eq("2025-04-25").all()
    assert ordinary_rows.spendable_not_before.eq("2025-04-26").all()
    assert replay.metadata["research_account_scientific_identity"] == "FULL_SELECTOR_FIXED_POLICY_RESEARCH_ACCOUNT"
    assert replay.daily.research_accounting_qualified.all()
    assert replay.daily.loc[replay.daily.date.ge(pd.Timestamp("2025-04-25")), "certified_nav"].isna().all()


def test_full_selector_authority_rejects_scope_catalogue_and_source_tampering():
    from copy import deepcopy
    from scripts.v22 import corporate_action_transition_r1 as ca
    cash, terminal, original = full_selector_catalogue()
    changes = [
        ("task_id", "V24_C15"), ("scope_end_exclusive", "2027-01-01"),
        ("certified_NAV", True), ("production_qualified", True),
        ("quote_qualified", True), ("strict_PIT_promotion_eligible", True),
        ("accounting_clock_convention", "PAY_DATE_OPEN"), ("unexpected", 1),
        ("ordinary_cash_event_fingerprints", []),
        ("ordinary_cash_event_fingerprints", [terminal.event_fingerprint]),
        ("event_fingerprints", [cash.event_fingerprint]),
        ("event_fingerprints", original["event_fingerprints"] * 2),
        ("frozen_contract_ref", dict(path="C:/arbitrary.json", sha256="4" * 64)),
    ]
    for field, value in changes:
        authority = deepcopy(original); authority[field] = value
        with pytest.raises(ValueError, match="FULL_SELECTOR"):
            ca._validate_research_account_authority((cash, terminal), authority)
    for source in ("frozen_history_cash_admission", "terminal_source_authority"):
        authority = deepcopy(original); authority[source]["task_id"] = "OTHER_TASK"
        with pytest.raises(ValueError):
            ca._validate_research_account_authority((cash, terminal), authority)
    authority = deepcopy(original)
    authority["frozen_history_cash_admission"]["events"][0]["publication_available_at"] = "invented"
    with pytest.raises(ValueError, match="RECONSTRUCTION_BINDING_CHANGED"):
        ca._validate_research_account_authority((cash, terminal), authority)


def test_full_selector_rejects_terminal_term_change_and_2026_catalogue():
    from dataclasses import replace
    from scripts.v22 import corporate_action_transition_r1 as ca
    cash, terminal, original = full_selector_catalogue()
    for changed in (replace(terminal, cash_per_old_share=6.),
            replace(terminal, ticker="OTHER"),
            event(event_id="future", ex_date="2026-01-02", record_date="2026-01-02",
                  pay_date="2026-01-05", available_at="2025-12-31T12:00:00+00:00")):
        catalogue = (cash, changed)
        authority = dict(original, event_fingerprints=[e.event_fingerprint for e in catalogue])
        authority["terminal_source_authority"] = dict(original["terminal_source_authority"],
            event_fingerprints=[changed.event_fingerprint])
        with pytest.raises(ValueError, match="FULL_SELECTOR"):
            ca._validate_research_account_authority(catalogue, authority)


def test_full_selector_account_rejects_2026_or_continuation_even_with_valid_source_authority():
    from scripts.research.a2.evaluation import continuous_research_account as owner
    cash, terminal, authority = full_selector_catalogue()
    kwargs = dict(research_account_authority=authority,
        **entitlement_args((cash, terminal), {"secS": "S", "secMKFG": "MKFG"}))
    for extra in (dict(previous_prefix={}), dict(locked_evaluation_receipt={})):
        with pytest.raises(ValueError, match="FRESH_PRE2026_SCOPE"):
            owner.run_continuous_account(inputs(tickers=("S", "MKFG"), prices=[[100., 100.]] * 5),
                ["Raw"], rebalance, account(), **kwargs, **extra)
    data = inputs(tickers=("S", "MKFG"), prices=[[100., 100.]] * 2,
        dates=["2025-12-31", "2026-01-02"])
    with pytest.raises(ValueError, match="FRESH_PRE2026_SCOPE"):
        owner.run_continuous_account(data, ["Raw"], rebalance, account(), **kwargs)


def test_full_selector_does_not_relax_legacy_A_B_authorities_or_missing_seal(monkeypatch):
    import types
    from scripts.v22 import corporate_action_transition_r1 as ca
    from scripts.research.a2.evaluation import continuous_research_account as owner
    cash, terminal, composite = full_selector_catalogue()
    a = composite["terminal_source_authority"]
    b = dict(schema="B_FROZEN_HISTORY_CASH_ACCOUNT_AUTHORITY_V1",
        scientific_identity="FROZEN_HISTORY_RESEARCH_ACCOUNT",
        task_id="V24_B_FAST_TRACK_PAIR_COMPLETION_R1", clock_role="POST_VERIFIED_ACCOUNTING_ONLY",
        strict_PIT_promotion_eligible=False, production_qualified=False,
        frozen_history_cash_admission=composite["frozen_history_cash_admission"])
    assert ca._validate_research_account_authority((terminal,), a) == a
    assert ca._validate_research_account_authority((cash,), b) == b
    with pytest.raises(ValueError, match="STANDALONE_AUTHORITY"):
        ca._validate_research_account_authority((cash, terminal), b)
    with pytest.raises(ValueError, match="CASH_ADMISSION"):
        ca._validate_research_account_authority((cash, terminal), a)
    def needs_seal(*args, **kwargs):
        raise ValueError("SYNTHETIC_LEGACY_DESCRIPTIVE_SEAL_STILL_REQUIRED")
    monkeypatch.setitem(sys.modules, "scripts.research.a2.evaluation.frozen_test_authority",
                        types.SimpleNamespace(validate_reconstructed_accounting_events=needs_seal))
    with pytest.raises(ValueError, match="SYNTHETIC_LEGACY_DESCRIPTIVE_SEAL_STILL_REQUIRED"):
        owner.run_continuous_account(inputs(), ["Raw"], rebalance, account(),
            research_account_authority=b, **entitlement_args((cash,)))


def test_full_selector_unclassified_special_cash_keeps_original_payment_precedence():
    from scripts.v22 import corporate_action_transition_r1 as ca
    cash, terminal, authority = full_selector_catalogue()
    special = event(event_id="strict_special", old_security_id="secT", ticker="T",
        action_type="CASH_DISTRIBUTION", ex_date="2025-04-25", record_date="2025-04-25",
        pay_date="2025-04-25", available_at="2025-04-24T12:00:00+00:00", cash_per_old_share=1.)
    catalogue = (cash, terminal, special)
    authority["event_fingerprints"].append(special.event_fingerprint)
    result = ca.apply_entitlement_lifecycle(catalogue, {"secS": 2., "secT": 3., "secMKFG": 0.}, 0.,
        execution_date="2025-04-25", session_open_at="2025-04-25T13:30:00+00:00",
        security_tickers={"secS": "S", "secT": "T", "secMKFG": "MKFG"}, quantity_coordinate=RAW_OLD_SHARE_COORDINATE,
        enabled=True, research_account_authority=authority)
    assert result.cash == 3. and result.receivable_value_usd == 2.
    assert [r.event_id for r in result.state.receivables] == [cash.event_id]
    paid = next(r for r in result.records if r["phase"] == "CASH_PAID")
    assert paid["event_id"] == special.event_id and "spendable_not_before" not in paid
