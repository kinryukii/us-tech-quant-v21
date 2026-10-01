"""Frozen engine gap ownership: synthetic inputs only, no strategy changes."""
import pandas as pd
import pytest
from scripts.common.storage_paths import resolve
from scripts.research.a2.evaluation import demo_performance as producer


def run_case(model, gap, mode):
    engine, _ = producer._authority(resolve())
    dates = pd.bdate_range('2026-01-05',periods=3)
    engine.EFFECTIVE_START=dates[0]
    old=[f'A{i:02}' for i in range(20)];new=[f'B{i:02}' for i in range(20)]
    first=new if mode=='entry' else old
    second=old if mode=='entry' else new if mode=='exit' else old
    targets={dates[0]:dict.fromkeys(first,.05),dates[1]:dict.fromkeys(second,.05)}
    rows=[]
    for date in dates:
        for ticker in old+new:
            opening=100*(1+gap) if date==dates[2] and ticker in old else 100.
            rows.append(dict(trade_date=date,ticker=ticker,open=opening,close=opening))
    prices=pd.DataFrame(rows)
    result=engine.reconstruct_open_ended(model,targets,prices,dates,dates[-1])
    return result,dates,old


@pytest.mark.parametrize('model',['A2_HGB','A2_RX'])
@pytest.mark.parametrize('gap',[.1,-.1])
@pytest.mark.parametrize('mode',['hold','entry','exit'])
def test_gap_belongs_to_previous_holders_and_costs_are_separate(model,gap,mode):
    result,dates,old=run_case(model,gap,mode)
    daily=result.daily.set_index('date');book=result.positions.loc[result.positions.date.eq(dates[-1])]
    old_book=book.loc[book.ticker.isin(old)]
    assert not result.missing_price_events
    if mode=='entry':
        assert old_book.shares_before.eq(0).all()
        assert old_book.market_pnl.eq(0).all()
        buys=result.trades.loc[result.trades.date.eq(dates[-1]) & result.trades.side.eq('BUY')]
        assert buys.execution_price.eq(100*(1+gap)).all()
        expected_market_pnl=0.
    else:
        expected_market_pnl=float(old_book.shares_before.sum()*100*gap)
        assert old_book.market_pnl.sum()==pytest.approx(expected_market_pnl)
        assert expected_market_pnl/daily.loc[dates[1],'nav']==pytest.approx(gap)
    if mode=='exit':
        assert old_book.shares_after.eq(0).all()
        sells=result.trades.loc[result.trades.date.eq(dates[-1]) & result.trades.side.eq('SELL')]
        assert sells.execution_price.eq(100*(1+gap)).all()
    today=result.trades.loc[result.trades.date.eq(dates[-1])]
    expected_cost=.0005*today.notional.sum()
    assert daily.loc[dates[-1],'transaction_cost']==pytest.approx(expected_cost)
    assert daily.loc[dates[-1],'nav']==pytest.approx(daily.loc[dates[1],'nav']+expected_market_pnl-expected_cost)
    if mode=='hold':assert daily.loc[dates[-1],'daily_return']==pytest.approx(gap)
    if mode=='entry':assert daily.loc[dates[-1],'daily_return']<0


@pytest.mark.parametrize('model',['A2_HGB','A2_RX'])
def test_close_gap_decomposition_is_not_added_twice(model):
    engine,_=producer._authority(resolve());dates=pd.bdate_range('2026-01-05',periods=3)
    engine.EFFECTIVE_START=dates[0];names=[f'A{i:02}' for i in range(20)]
    target={day:dict.fromkeys(names,.05) for day in dates[:2]}
    prices=pd.DataFrame([dict(trade_date=day,ticker=ticker,open=110. if day==dates[-1] else 100.,
        close=105. if day==dates[1] else 110. if day==dates[-1] else 100.) for day in dates for ticker in names])
    result=engine.reconstruct_open_ended(model,target,prices,dates,dates[-1])
    book=result.positions.loc[result.positions.date.eq(dates[-1])]
    shares=book.shares_before.sum()
    intraday=shares*(105.-100.);overnight=shares*(110.-105.)
    assert book.market_pnl.sum()==pytest.approx(intraday+overnight)
    assert book.market_pnl.sum()==pytest.approx(shares*10.)
    assert result.daily.iloc[-1].daily_return==pytest.approx(.1)
    assert 110./105.-1==pytest.approx(5./105.)
    # First purchase at the 110 open has no prior position, even with a 105 close.
    engine.EFFECTIVE_START=dates[1]
    fresh=engine.reconstruct_open_ended(model,{dates[1]:dict.fromkeys(names,.05)},prices,dates,dates[-1])
    assert fresh.positions.shares_before.eq(0).all() and fresh.positions.market_pnl.eq(0).all()
    assert fresh.trades.execution_price.eq(110.).all()
