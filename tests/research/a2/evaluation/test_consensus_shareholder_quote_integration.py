"""Independent generated regression for combined shareholder/quote/cash owners.

Only synthetic 2025 bars/events and temporary authority metadata are used.
"""
from dataclasses import replace
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.evaluation import consensus_shareholder_account as bridge
from scripts.research.a2.evaluation.consensus_cash_account import FeeConfig, fee_for_notional
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision
from scripts.v22 import corporate_action_transition_r1 as ca
from test_consensus_shareholder_account import binding, entitlement, source_binding, market


def test_quote_only_split_day_execution_preserves_raw_shares_actual_fees_and_settlement(tmp_path):
    m=market(split=True)
    # Split-day raw price55 gives an execution index price110; legacy decision
    # mark remains100 on the quality-blocked row. Only usable_a admits execution.
    opens=m.open.copy();closes=m.close.copy();opens[2:]=55.;closes[2:]=55.
    quality=m.quality.copy();quality[2]=True
    m=replace(m,open=opens,close=closes,quality=quality)
    e=entitlement();events=(e,);ids={'old':'S','new':'S'}
    split=ca.CorporateActionTransition('2025-06-04','FORWARD_SPLIT','old','new','S','S',2.,0.,
        'TIER2_LOCAL_CANONICAL','synthetic://split-quote-integration','d'*64)
    owner_bytes=Path(bridge.owner.__file__).read_bytes();ca_bytes=Path(ca.__file__).read_bytes()
    observed=[];proofs=[]
    def policy(di,ctx):
        observed.append(dict(date=ctx.signal_date,units=ctx.current_units.copy(),
            cash=ctx.settled_cash.copy(),unsettled=ctx.unsettled_cash.copy(),receivable=ctx.receivable_value_usd.copy()))
        target=np.asarray([[.1 if di==0 else .05 if di<3 else 0.]])
        return TargetDecision(target,ctx.decision_mask.copy(),'SYNTHETIC_QUOTE_SPLIT_FIXED_FEE')
    def ledger(name,frame):
        if name=='execution_coordinate_proof':proofs.append(frame.copy())
    config=FeeConfig(25.,.5,5.,True)
    replay=bridge.run_shareholder_cash_account(m,['x'],policy,task_authority=binding(tmp_path,events),
        settlement_calendar=m.dates,fee_config=config,corporate_actions=(split,),
        corporate_action_known_at={split.event_fingerprint:'2025-06-03T12:00:00Z'},entitlement_events=events,
        entitlement_security_tickers=ids,entitlement_source_binding=source_binding(events,ids),
        usable_a=np.ones_like(quality,bool),ledger_callback=ledger)
    fills=replay.fills
    split_fill=fills.loc[fills.execution_date.eq(m.dates[2])].iloc[0]
    assert split_fill.side=='SELL' and split_fill.price==55.
    assert split_fill.quantity_coordinate_factor==2.
    assert split_fill.index_units_before==pytest.approx(6.)
    assert split_fill.index_units==pytest.approx(split_fill.notional/55.)
    assert split_fill.engine_index_units==pytest.approx(split_fill.index_units/2.)
    np.testing.assert_allclose(fills.transaction_cost,fee_for_notional(fills.notional,config),rtol=0,atol=1e-10)
    np.testing.assert_allclose(fills.fixed_stress_fee,.5,rtol=0,atol=0)
    np.testing.assert_allclose(fills.all_in_proxy_fee,fills.notional*.0025,rtol=0,atol=1e-10)
    np.testing.assert_allclose(fills.transaction_cost,fills.fixed_stress_fee+fills.all_in_proxy_fee,rtol=0,atol=1e-10)
    assert replay.daily.transaction_cost_amount.sum()==pytest.approx(fills.transaction_cost.sum())
    claim=e.cash_per_old_share*split_fill.index_units_after
    assert observed[3]['receivable'][0]==pytest.approx(claim)
    assert observed[2]['unsettled'][0]==pytest.approx(split_fill.notional-split_fill.transaction_cost)
    assert split_fill.settlement_date==m.dates[3]
    assert replay.daily.loc[replay.daily.date.eq(m.dates[3]),'settlement_release'].iloc[0]==pytest.approx(split_fill.notional-split_fill.transaction_cost)
    proof=pd.concat(proofs,ignore_index=True)
    assert proof.identity_error.max()<1e-8
    assert proof.actual_fee_verified_by_cash_owner.sum()==pytest.approx(fills.transaction_cost.sum())
    sales=fills.loc[fills.side.eq('SELL')]
    assert proof.net_sale_cash_withheld_by_cash_owner.sum()==pytest.approx((sales.notional-sales.transaction_cost).sum())
    assert replay.audit['actual_cash_flow_identity_error_max']<1e-8
    expected_cash=3000.-fills.loc[fills.side.eq('BUY'),'notional'].sum()+sales.notional.sum()-fills.transaction_cost.sum()+claim
    assert replay.final_cash[0]==pytest.approx(expected_cash)
    assert replay.final_unsettled_cash[0]==0. and replay.final_state['fractional_shares'][0,0]==0.
    assert replay.metadata['quote_vintage_status']=='UNKNOWN' and replay.metadata['certified_NAV'] is False
    assert Path(bridge.owner.__file__).read_bytes()==owner_bytes and Path(ca.__file__).read_bytes()==ca_bytes

