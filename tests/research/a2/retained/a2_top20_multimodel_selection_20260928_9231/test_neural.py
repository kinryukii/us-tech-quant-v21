"""Causality, execution, and actual optimizer-update proofs on synthetic data."""
import numpy as np
import pandas as pd
import pytest
import torch

import neural as n


def test_projection_obeys_reserved_capacity_and_stable_ties():
    logits=torch.zeros(30)
    weights=n.project(logits,max_names=3,max_exposure=.09)
    assert torch.nonzero(weights).flatten().tolist()==[0,1,2]
    assert float(weights.sum())==pytest.approx(.09)
    assert float(weights.max())<=.1
    assert n.project(logits,max_names=0).sum()==0
    assert n.project(logits,max_exposure=0).sum()==0
    upper=torch.tensor([.01,.04])
    assert torch.all(n.project(logits[:2],upper=upper)<=upper)


def test_capacity_caps_real_buys_and_cash_and_rejects_bad_adv():
    units=torch.zeros(3,dtype=torch.float64)
    cash=torch.tensor(1.,dtype=torch.float64)
    opening=torch.ones(3,dtype=torch.float64)*100
    fill=torch.ones(3,dtype=torch.bool)
    weights=torch.tensor([.1,.1,.1],dtype=torch.float64)
    locked=torch.zeros(3,dtype=torch.bool)
    adv=torch.tensor([1_000_000.,float('nan'),-1.],dtype=torch.float64)
    new,remaining,fees,nav,blocked,stats=n.execute_targets(units,cash,opening,fill,weights,locked,fill,adv)
    assert new.tolist()==pytest.approx([.0001,0.,0.])
    assert float(remaining)==pytest.approx(.98999)
    assert float(fees)==pytest.approx(.00001)
    assert float(nav)==1 and blocked==0
    assert stats['cap_limited_orders']==3
    assert stats['filled_buy_notional']==pytest.approx(.01)
    assert float(remaining+(new*opening).sum()+fees)==pytest.approx(1.)


def test_failed_sells_preserve_units_and_actual_twenty_name_cap():
    units=torch.tensor([.04]*20+[0.],dtype=torch.float64)
    fill=torch.tensor([False]*20+[True])
    weights=torch.tensor([0.]*20+[.1],dtype=torch.float64)
    new,cash,fees,nav,blocked,stats=n.execute_targets(units,torch.tensor(.2),torch.ones(21),
        fill,weights,torch.zeros(21,dtype=torch.bool),torch.ones(21,dtype=torch.bool),torch.ones(21)*1e9)
    assert torch.equal(new,units)
    assert blocked==1 and float(fees)==0.
    assert int((new>0).sum())==20


def test_locked_position_never_sold_and_ineligible_position_never_increased():
    units=torch.tensor([.1,.05],dtype=torch.float64)
    new,cash,fees,_,_,_=n.execute_targets(units,torch.tensor(.85),torch.ones(2),
        torch.ones(2,dtype=torch.bool),torch.tensor([0.,.1]),torch.tensor([True,False]),
        torch.tensor([False,False]),torch.ones(2)*1e9)
    assert torch.equal(new,units)
    assert float(fees)==0


def panel_fixture(dates,ends,values=None):
    values=range(len(dates)) if values is None else values
    rows=[]
    for date,end,value in zip(dates,ends,values):
        row={f:float(value) for f in n.FEATURES}
        row.update(ticker='A',signal_date=pd.Timestamp(date),label_end_date=pd.Timestamp(end),
            new_buy_eligible=True,avg_dollar_volume_20d=1e6,realized_vol_20d=.02)
        rows.append(row)
    return pd.DataFrame(rows)


def test_normalizer_purges_cross_year_labels_and_ignores_future_mutations():
    panel=panel_fixture(['2024-12-20','2024-12-23','2024-12-31','2025-01-02'],
        ['2024-12-24','2024-12-26','2025-01-03','2025-01-06'],[1,3,1e12,1e12])
    mean,scale,evidence=n.fit_normalization(panel,'2024-12-31')
    panel.loc[2:,n.FEATURES]=-1e12
    changed_mean,changed_scale,_=n.fit_normalization(panel,'2024-12-31')
    np.testing.assert_array_equal(mean,changed_mean)
    np.testing.assert_array_equal(scale,changed_scale)
    assert mean[0]==2 and evidence['rows']==2
    assert evidence['label_end_max']=='2024-12-26'
    with pytest.raises(ValueError,match='TRAIN_STAGE_BOUNDARY'):
        n.fit_normalization(panel,'2026-01-01')


def test_market_filters_prices_and_mature_labels_at_phase_boundary(tmp_path,monkeypatch):
    calendar=pd.bdate_range('2024-12-20','2025-01-06')
    rows=[dict(ticker=t,trade_date=d,open=100.,close=100.) for t in ['A','QQQ'] for d in calendar]
    price_path=tmp_path/'prices.parquet'
    pd.DataFrame(rows).to_parquet(price_path,index=False)
    monkeypatch.setattr(n,'PRICE',price_path)
    panel=panel_fixture(calendar[:-2],calendar[2:])
    market=n.Market(panel,'2024-12-20','2024-12-31',np.zeros(32),np.ones(32))
    assert market.price_date_max=='2024-12-31'
    assert max(d['reward_end_date'] for d in market.days)=='2024-12-31'
    assert max(d['date'] for d in market.days)=='2024-12-27'
    assert all(len(d['ids'])==1 for d in market.days)
    with pytest.raises(ValueError,match='TRAIN_PRICE_BOUNDARY'):
        n.Market(panel,'2024-12-20','2026-01-01',np.zeros(32),np.ones(32))


def synthetic_market(days=3):
    market=object.__new__(n.Market)
    market.tickers=['A'];market.days=[]
    calendar=pd.bdate_range('2024-01-02',periods=days+2)
    for index in range(days):
        market.days.append(dict(date=str(calendar[index].date()),execution_date=str(calendar[index+1].date()),
            reward_end_date=str(calendar[index+2].date()),ids=torch.tensor([0]),x=torch.zeros((1,32)),
            eligible=torch.tensor([True]),close=torch.tensor([100.],dtype=torch.float64),
            signal_price_usable=torch.tensor([True]),opening=torch.tensor([100.],dtype=torch.float64),
            ending=torch.tensor([100.],dtype=torch.float64),fill=torch.tensor([True]),
            signal_adv_dollars=torch.tensor([1_000_000.],dtype=torch.float64),
            vol=torch.tensor([.02],dtype=torch.float64)))
    return market


def test_actual_capacity_limited_holdings_and_cash_feed_next_observation():
    observations=[]
    class RecordingPolicy(torch.nn.Module):
        def forward(self,x):
            observations.append(x.detach().clone())
            return torch.zeros(len(x))
    info,records=synthetic_market(2).episode(RecordingPolicy())
    assert observations[0][0,-3].item()==0
    assert observations[1][0,-3].item()==pytest.approx(.01/.99999)
    assert observations[1][0,-2].item()==pytest.approx(.98999/.99999)
    assert observations[1][0,-1].item()==1
    assert info['updates']==0 and info['adv_limited_buy_orders']==2
    assert records[0]['filled_buy_notional']==pytest.approx(.01)


@pytest.mark.parametrize('method,days,expected_updates',[('direct',3,3),('rl',65,3)])
def test_real_optimizer_steps_occur_and_zero_mode_does_not_update(method,days,expected_updates):
    torch.manual_seed(12)
    model=n.JointPolicy()
    before={k:v.detach().clone() for k,v in model.state_dict().items()}
    market=synthetic_market(days)
    with torch.no_grad():
        zero_info,_=market.episode(model)
    assert zero_info['updates']==0
    assert all(torch.equal(v,before[k]) for k,v in model.state_dict().items())
    optimizer=torch.optim.Adam(model.parameters(),lr=.0005,weight_decay=.001)
    info,records=market.episode(model,optimizer,method,noise_seed=12)
    assert info['updates']==expected_updates
    assert any(not torch.equal(v,before[k]) for k,v in model.state_dict().items())
    assert max(r['actual_names'] for r in records)<=20
    assert all(r['actual_cash_fraction']>=0 for r in records)
