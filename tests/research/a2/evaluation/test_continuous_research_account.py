"""Synthetic focused checks for the thin immutable-engine adapter."""
import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.evaluation.continuous_research_account import run_continuous_account,account_prefix_identity
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays,TargetDecision
from scripts.v22.corporate_action_transition_r1 import CorporateActionTransition


def config(capital=3000):
    return dict(base_currency="USD",initial_nav=capital,initial_cash=capital,initial_holdings=[],
        fractional_shares=True,integer_share_rounding=False,cash_interest=0,transaction_cost_bps=0,
        financing=False,borrowed_cash=False,long_only=True,max_positions=20,max_weight=1.,
        max_invested=1.,capacity_fraction=.01)


def market(dates,prices):
    values=np.asarray(prices,float)[:,None]
    return MarketArrays(pd.to_datetime(dates),["S"],values.copy(),values.copy(),
                        adv=np.full(values.shape,1e9),signal_mask=np.ones(len(dates),bool))


def buy_then_hold(observed=None):
    def policy(j,ctx):
        if observed is not None:
            observed.append((j,ctx.holding_age.copy(),ctx.entry_date.copy(),ctx.entry_price.copy(),ctx.current_units.copy()))
        if j==0:
            return TargetDecision(np.array([[.8]]),ctx.decision_mask)
        return TargetDecision(np.zeros((1,1)),np.zeros((1,1),bool))
    return policy


def event(cash=0):
    return CorporateActionTransition("2024-01-04","FORWARD_SPLIT","old","new","S","S",2.,
        cash,"TIER2_LOCAL_CANONICAL","synthetic://split","a"*64)


def test_fractional_cash_age_and_entry_persist_across_year_boundary():
    data=market(["2023-12-29","2024-01-02","2024-01-03","2024-01-04"],[777]*4)
    observed=[]
    replay=run_continuous_account(data,["path"],buy_then_hold(observed),config())
    assert replay.final_cash[0]==pytest.approx(600)
    assert replay.final_state["fractional_shares"][0,0]==pytest.approx(2400/777)
    assert replay.final_state["fractional_shares"][0,0] != int(replay.final_state["fractional_shares"][0,0])
    assert replay.positions.holding_age.tolist()==[0,1,2]
    assert replay.positions.entry_date.eq(pd.Timestamp("2024-01-02")).all()
    assert replay.positions.entry_price.eq(777).all()
    assert [int(o[1][0,0]) for o in observed]==[-1,0,1,2]
    assert replay.fills.iloc[0].execution_date==pd.Timestamp("2024-01-02")
    assert replay.fills.iloc[0].price*replay.fills.iloc[0].fractional_shares==pytest.approx(2400)
    assert replay.daily.transaction_cost_amount.eq(0).all()
    assert replay.metadata["annual_reset"] is False
    larger=run_continuous_account(data,["path"],buy_then_hold(),config(6000))
    assert larger.final_state["fractional_shares"][0,0]==pytest.approx(2*2400/777)


def test_source_backed_split_uses_common_transition_and_raw_fill_identity():
    data=market(["2024-01-02","2024-01-03","2024-01-04","2024-01-05"],[777,777,388.5,388.5])
    split=event()
    replay=run_continuous_account(data,["path"],buy_then_hold(),config(),corporate_actions=[split],
        corporate_action_known_at={split.event_fingerprint:"2024-01-03 16:00:00+00:00"})
    assert replay.daily.nav.eq(3000).all()
    assert replay.final_state["fractional_shares"][0,0]==pytest.approx(2*2400/777)
    assert replay.final_units[0,0]==pytest.approx(2400/777)
    assert replay.positions.fractional_shares.tolist()==pytest.approx([2400/777,2*2400/777,2*2400/777])
    assert replay.positions.market_value.tolist()==pytest.approx([2400]*3)
    assert (replay.positions.mark*replay.positions.fractional_shares).tolist()==pytest.approx([2400]*3)
    assert len(replay.metadata["corporate_action_receipts"])==1
    assert replay.accounting_exceptions.empty

    assert replay.positions.entry_price.tolist()==pytest.approx([777,388.5,388.5])
    assert replay.positions.entry_execution_open.eq(777).all()
    def with_exit(j,ctx):
        if j==2:
            return TargetDecision(np.zeros((1,1)),ctx.decision_mask)
        return buy_then_hold()(j,ctx)
    exited=run_continuous_account(data,["path"],with_exit,config(),corporate_actions=[split],
        corporate_action_known_at={split.event_fingerprint:"2024-01-03 16:00:00+00:00"})
    sold=exited.fills.loc[exited.fills.side.eq("SELL")].iloc[0]
    assert sold.price==388.5
    assert sold.fractional_shares==pytest.approx(2*2400/777)
    assert sold.price*sold.fractional_shares==pytest.approx(sold.notional)
    assert exited.final_cash[0]==pytest.approx(3000)
    assert exited.final_state["holding_age"][0,0]==-1


def test_unavailable_or_cash_component_event_fails_closed_only_for_affected_holding():
    data=market(["2024-01-02","2024-01-03","2024-01-04","2024-01-05"],[777,777,388.5,388.5])
    split=event(cash=1)
    replay=run_continuous_account(data,["path"],buy_then_hold(),config(),corporate_actions=[split],
        corporate_action_known_at={split.event_fingerprint:"2024-01-03 16:00:00+00:00"})
    assert len(replay.accounting_exceptions)==1
    assert replay.accounting_exceptions.iloc[0].nav_valid==False
    assert replay.daily.loc[replay.daily.date.ge("2024-01-04"),"certified_nav"].isna().all()
    assert replay.final_state["fractional_shares"][0,0]==pytest.approx(2400/777)
    assert len(replay.fills)==1
    assert replay.daily.loc[replay.daily.date.ge("2024-01-04"),"accounting_qualified"].eq(False).all()
    assert replay.final_state["accounting_qualified"].tolist()==[False]


def test_locked_full_prefix_continuation_keeps_pre2026_account_and_requires_freeze():
    pre=market(["2025-12-30","2025-12-31"],[777,777])
    first=run_continuous_account(pre,["path"],buy_then_hold(),config())
    full=market(["2025-12-30","2025-12-31","2026-01-02","2026-01-05"],[777]*4)
    with pytest.raises(ValueError,match="finalist freeze"):
        run_continuous_account(full,["path"],buy_then_hold(),config(),previous_prefix=first.prefix_identity)
    later=run_continuous_account(full,["path"],buy_then_hold(),config(),
        previous_prefix=first.prefix_identity,locked_evaluation_receipt={"status":"FINALIST_FROZEN","sha256":"f"*64})
    assert later.prefix_identity==first.prefix_identity
    assert later.positions.holding_age.tolist()==[0,1,2]
    assert later.final_cash[0]==pytest.approx(first.final_cash[0])
    bad=dict(first.prefix_identity,sha256="0"*64)
    with pytest.raises(AssertionError,match="changed frozen"):
        run_continuous_account(full,["path"],buy_then_hold(),config(),previous_prefix=bad,
            locked_evaluation_receipt={"status":"FINALIST_FROZEN","sha256":"f"*64})


def test_all_cash_prefix_can_legally_add_first_position_in_locked_period():
    pre=market(["2025-12-30","2025-12-31"],[777]*2)
    def cash_then_buy(j,ctx):
        if j==2:
            return TargetDecision(np.array([[.8]]),ctx.decision_mask)
        return TargetDecision(np.zeros((1,1)),ctx.decision_mask)
    first=run_continuous_account(pre,["path"],cash_then_buy,config())
    assert first.fills.empty and first.positions.empty
    full=market(["2025-12-30","2025-12-31","2026-01-02","2026-01-05"],[777]*4)
    later=run_continuous_account(full,["path"],cash_then_buy,config(),
        previous_prefix=first.prefix_identity,locked_evaluation_receipt={"status":"FINALIST_FROZEN","sha256":"f"*64})
    assert later.prefix_identity==first.prefix_identity
    assert later.fills.iloc[0].execution_date==pd.Timestamp("2026-01-05")


def test_finalist_only_prefix_is_reused_from_the_full_candidate_batch():
    pre=market(["2025-12-30","2025-12-31"],[777]*2)
    def batch_policy(j,ctx):
        if j==0:
            return TargetDecision(np.array([[.8],[.4]]),ctx.decision_mask)
        return TargetDecision(np.zeros((2,1)),np.zeros((2,1),bool))
    first=run_continuous_account(pre,["x","y"],batch_policy,config())
    chosen=account_prefix_identity(first,"2025-12-31",["y"])
    full=market(["2025-12-30","2025-12-31","2026-01-02"],[777]*3)
    def finalist_policy(j,ctx):
        if j==0:
            return TargetDecision(np.array([[.4]]),ctx.decision_mask)
        return TargetDecision(np.zeros((1,1)),np.zeros((1,1),bool))
    later=run_continuous_account(full,["y"],finalist_policy,config(),previous_prefix=chosen,
        locked_evaluation_receipt={"status":"FINALIST_FROZEN","sha256":"f"*64})
    assert later.prefix_identity==chosen
    assert later.final_cash[0]==pytest.approx(1800)
    with pytest.raises(ValueError,match="path identity"):
        account_prefix_identity(first,"2025-12-31",["missing"])


def test_historical_cash_event_does_not_block_a_later_first_buy_or_other_ticker():
    data=market(["2024-01-02","2024-01-03","2024-01-04","2024-01-05","2024-01-08"],[777,777,388.5,388.5,388.5])
    cash_event=event(cash=1)
    known={cash_event.event_fingerprint:"2024-01-03 16:00:00+00:00"}
    def late_buy(j,ctx):
        if j==3:
            return TargetDecision(np.array([[.8]]),ctx.decision_mask)
        return TargetDecision(np.zeros((1,1)),ctx.decision_mask)
    later=run_continuous_account(data,["later"],late_buy,config(),corporate_actions=[cash_event],
        corporate_action_known_at=known)
    assert later.accounting_exceptions.empty
    assert later.daily.accounting_qualified.all()
    assert later.daily.certified_nav.notna().all()
    assert later.fills.iloc[0].execution_date==pd.Timestamp("2024-01-08")
    assert later.final_state["fractional_shares"][0,0]==pytest.approx(2400/388.5)
    two=MarketArrays(data.dates,["S","B"],np.column_stack([data.open[:,0],np.full(5,100.)]),
        np.column_stack([data.close[:,0],np.full(5,100.)]),adv=np.full((5,2),1e9))
    def with_other_buy(j,ctx):
        if j==0:
            return TargetDecision(np.array([[.4,0]]),ctx.decision_mask)
        if j==2:
            return TargetDecision(np.array([[0,.2]]),ctx.decision_mask)
        return TargetDecision(np.zeros((1,2)),np.zeros((1,2),bool))
    held=run_continuous_account(two,["held"],with_other_buy,config(),corporate_actions=[cash_event],
        corporate_action_known_at=known)
    assert len(held.accounting_exceptions)==1
    assert (held.fills.ticker.eq("B") & held.fills.side.eq("BUY")).any()
    assert held.daily.loc[held.daily.date.ge("2024-01-04"),"accounting_qualified"].eq(False).all()
    assert held.daily.loc[held.daily.date.ge("2024-01-04"),"certified_nav"].isna().all()
