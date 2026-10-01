"""Temporal, capacity, and holding-state behavior of the fresh neural arm."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest
import torch

sys.path.insert(0,str(Path(__file__).resolve().parent))
import neural


def tensor(x):return torch.tensor(x,dtype=torch.float64)


def synthetic_panel(dates):
    rows=[]
    for i,date in enumerate(dates[:-2]):
        row={f:0. for f in neural.FEATURES}
        row.update(signal_date=date,label_end_date=dates[i+2],ticker='A',
                   new_buy_eligible=True,avg_dollar_volume_20d=1_000_000.,realized_vol_20d=.01)
        rows.append(row)
    return pd.DataFrame(rows)


def prices(dates):
    return pd.DataFrame([dict(ticker=t,trade_date=d,open=100.,close=100.)
                         for d in dates for t in ('A','QQQ')])


def test_stage_normalizer_excludes_future_signal_and_future_label():
    dates=pd.bdate_range('2024-12-23',periods=12)
    panel=synthetic_panel(dates)
    panel.loc[panel.label_end_date.gt('2024-12-31'),neural.FEATURES[0]]=1e12
    mean,scale,evidence=neural.fit_normalization(panel,'2024-12-31')
    assert mean[0]==0
    assert np.isfinite(scale).all() and (scale>0).all()
    assert evidence['signal_max']<'2025-01-01'
    assert evidence['label_end_max']<'2025-01-01'
    with pytest.raises(ValueError,match='BOUNDARY_2026'):
        neural.fit_normalization(panel,'2026-01-01')


def test_market_filters_prices_and_mature_reward_at_stage_cutoff(monkeypatch):
    dates=pd.bdate_range('2024-12-23',periods=12)
    panel=synthetic_panel(dates)
    calls=[]
    def read(path,columns,filters):
        calls.append(filters)
        return prices(dates)
    monkeypatch.setattr(neural.pd,'read_parquet',read)
    market=neural.Market(panel,'2024-01-01','2024-12-31',np.zeros(32),np.ones(32))
    assert calls==[[('trade_date','<=',pd.Timestamp('2024-12-31'))]]
    assert market.price_date_max=='2024-12-31'
    assert max(d['reward_end_date'] for d in market.days)=='2024-12-31'
    assert all(d['date']<d['execution_date']<d['reward_end_date']<'2025-01-01' for d in market.days)
    with pytest.raises(ValueError,match='BOUNDARY_2026'):
        neural.Market(panel,'2023-01-01','2026-01-01',np.zeros(32),np.ones(32))
    assert len(calls)==1


def test_adv_capacity_and_cash_cost_are_realized_before_next_state():
    units,cash,fees,_,_,info=neural.execute_targets(
        tensor([0.]),tensor(1.),tensor([100.]),torch.tensor([True]),
        tensor([.1]),torch.tensor([False]),torch.tensor([True]),tensor([1_000_000.]))
    assert units[0].item()==pytest.approx(.0001)
    assert cash.item()==pytest.approx(.98999)
    assert fees.item()==pytest.approx(.00001)
    assert info['cap_limited_orders']==1
    units,cash,fees,nav,_,_=neural.execute_targets(
        units.detach(),cash.detach(),tensor([100.]),torch.tensor([True]),
        tensor([.1]),torch.tensor([False]),torch.tensor([True]),tensor([1_000_000.]))
    assert units[0].item()==pytest.approx(.0002)
    assert nav.item()==pytest.approx(.99999)
    assert cash.item()==pytest.approx(.97998)


def test_episode_observation_uses_partial_filled_weight_and_cash(monkeypatch):
    dates=pd.bdate_range('2024-12-02',periods=4)
    monkeypatch.setattr(neural.pd,'read_parquet',lambda *args,**kwargs:prices(dates))
    market=neural.Market(synthetic_panel(dates),'2024-01-01','2024-12-31',np.zeros(32),np.ones(32))
    class Capture(torch.nn.Module):
        def __init__(self):super().__init__();self.observations=[]
        def forward(self,x):self.observations.append(x.clone());return torch.full((len(x),),10.)
    model=Capture()
    info,records=market.episode(model)
    second=model.observations[1][0,-3:]
    assert second[0].item()==pytest.approx(.01/.99999)
    assert second[1].item()==pytest.approx(.98999/.99999)
    assert second[2].item()==1.
    assert info['adv_limited_buy_orders']==2
    assert records[-1]['actual_cash_fraction']<records[0]['actual_cash_fraction']


def test_missing_decision_holding_stays_exactly_locked():
    units=tensor([.003,0.])
    new_units,_,_,_,_,_=neural.execute_targets(
        units,tensor(.7),tensor([100.,100.]),torch.tensor([True,True]),
        tensor([0.,.1]),torch.tensor([True,False]),torch.tensor([True,True]),tensor([1e12,1e12]))
    assert torch.equal(new_units[:1],units[:1])


def test_failed_sales_reserve_actual_twenty_name_capacity():
    units=tensor([.0004]*20+[0.])
    new_units,_,_,_,blocked,_=neural.execute_targets(
        units,tensor(.2),tensor([100.]*21),torch.tensor([False]*20+[True]),
        tensor([0.]*20+[.1]),torch.tensor([False]*21),torch.tensor([True]*21),tensor([1e12]*21))
    assert blocked==1
    assert torch.equal(new_units,units)
    assert int((new_units>0).sum())==20


def test_sell_is_not_adv_limited_and_restricted_holding_cannot_buy():
    new_units,_,_,_,_,info=neural.execute_targets(
        tensor([.002,.0001]),tensor(.79),tensor([100.,100.]),torch.tensor([True,True]),
        tensor([.1,.1]),torch.tensor([False,False]),torch.tensor([True,False]),tensor([0.,1e12]))
    assert new_units[0].item()==pytest.approx(.001)
    assert new_units[1].item()==pytest.approx(.0001)
    assert info['filled_buy_notional']==0.


def test_projection_reserves_slots_exposure_and_holding_upper_bound():
    w=neural.project(torch.linspace(-1,2,30),upper=torch.full((30,),.025),max_names=3,max_exposure=.07)
    assert int((w>0).sum())<=3
    assert w.sum().item()<=.070001
    assert w.max().item()<=.025001
    assert neural.project(torch.ones(5),max_names=0,max_exposure=0).sum()==0


@pytest.mark.parametrize('method',['direct','rl'])
def test_optimizer_actually_updates_fresh_parameters(method,monkeypatch):
    dates=pd.bdate_range('2024-01-02',periods=36)
    monkeypatch.setattr(neural.pd,'read_parquet',lambda *args,**kwargs:prices(dates))
    market=neural.Market(synthetic_panel(dates),'2024-01-01','2024-12-31',np.zeros(32),np.ones(32))
    torch.manual_seed(neural.SEEDS[0]);model=neural.JointPolicy()
    initial=[p.detach().clone() for p in model.parameters()]
    optimizer=torch.optim.Adam(model.parameters(),lr=.0005,weight_decay=.001)
    info,_=market.episode(model,optimizer,method,neural.SEEDS[0])
    assert info['updates']==(34 if method=='direct' else 2)
    assert any(not torch.equal(old,new) for old,new in zip(initial,model.parameters()))
