"""Synthetic account isolation and full-candidate selection integration."""
import numpy as np
import pandas as pd
import pytest
from fast_account import MarketArrays,run_many
from portfolio_policy import PortfolioPolicy
from shared import RISKS


class RiskCache(dict):
    @property
    def files(self):return list(self.keys())


def sources(names,days=3):
    n=len(names)
    # Fixed joint scenarios; not fitted or selected against any result.
    rng=np.random.default_rng(20250928)
    z=rng.normal(size=(32,n))
    risk=RiskCache(corr_diagonal=np.eye(n),scenario_diagonal=z,
                   corr_ledoit_wolf=np.eye(n),scenario_ledoit_wolf=z,
                   scales=np.full((days,len(RISKS),n),.015))
    values=np.linspace(.009,.03,n)
    forecast=dict(stream_ids=np.array(["ridge__identity"]),mu=np.tile(values,(days,1,1)))
    return forecast,risk


def roster(ids,optimizer):
    return pd.DataFrame([dict(path_id=path,group="ridge",fusion="identity",risk="diagonal",optimizer=optimizer) for path in ids])


def test_unknown_nav_account_does_not_change_normal_account_or_receive_explicit_decisions():
    names=np.array(["A_UNKNOWN"]+[f"T{i:02}" for i in range(24)])
    dates=pd.bdate_range("2025-06-02",periods=3)
    prices=np.full((3,len(names)),100.);prices[:,0]=np.nan
    present=np.ones_like(prices,dtype=bool);present[:,0]=False
    market=MarketArrays(dates,names,prices,prices.copy(),adv=np.full_like(prices,1e8),input_present=present,signal_mask=[True,True,False])
    forecast,risk=sources(names)
    diagnostics=[];actor=PortfolioPolicy(roster(["normal","unknown"],"mean_variance"),forecast,risk,diagnostic_callback=diagnostics.append)
    calls=[]
    def policy(di,ctx):
        decision=actor(di,ctx)
        calls.append((decision.weights.copy(),decision.explicit_mask.copy()))
        return decision
    initial=np.zeros((2,len(names)));initial[0,1]=10.;initial[1,0]=10.
    mixed=run_many(market,["normal","unknown"],policy,initial_units=initial,initial_cash=9000.)
    single_actor=PortfolioPolicy(roster(["normal"],"mean_variance"),forecast,risk)
    single_calls=[]
    def single_policy(di,ctx):
        decision=single_actor(di,ctx)
        single_calls.append((decision.weights.copy(),decision.explicit_mask.copy()))
        return decision
    single=run_many(market,["normal"],single_policy,initial_units=initial[0],initial_cash=9000.)
    assert len(calls)==len(single_calls)
    for (w,explicit),(solo_w,solo_explicit) in zip(calls,single_calls):
        np.testing.assert_array_equal(w[0],solo_w[0])
        np.testing.assert_array_equal(explicit[0],solo_explicit[0])
        assert np.all(w[1]==0) and not explicit[1].any()
    for name in ["daily","positions","orders","fills","execution_results","contexts"]:
        frame=getattr(mixed,name)
        together=frame[frame.path_id.eq("normal")].reset_index(drop=True)
        alone=getattr(single,name).copy()
        # Adding an unknown mark introduces datetime64[ns] into NumPy's mixed
        # timestamp array, while all-known session labels can be datetime64[us].
        # Normalize this representational unit only; all account values and
        # strings still require exact equality and identical other dtypes.
        if "mark_date" in together:
            together["mark_date"]=together.mark_date.astype("datetime64[ns]")
            alone["mark_date"]=alone.mark_date.astype("datetime64[ns]")
        pd.testing.assert_frame_equal(together,alone,check_exact=True)
    assert np.isnan(mixed.daily[mixed.daily.path_id.eq("unknown")].nav).all()
    assert mixed.final_units[1,0]==10.
    assert all(frame.path_id.eq("normal").all() for frame in diagnostics)
    # Every known forecast remains explicit, even when outside selected TOP20.
    assert calls[0][1][0,1] and calls[0][0][0,1]==0
    assert mixed.orders[mixed.orders.ticker.eq("T00")].decision_semantic.iloc[0]=="MODEL_ACTIVE_EXIT"


@pytest.mark.parametrize("optimizer",["positive_equal","mean_variance","robust_mv","cvar","target_equal","target_median"])
def test_less_than_twenty_total_candidates_has_valid_dynamic_shapes_and_cash(optimizer):
    names=np.array(["A","B","C"]);dates=pd.bdate_range("2025-06-02",periods=3)
    prices=np.full((3,3),100.)
    market=MarketArrays(dates,names,prices,prices.copy(),adv=np.full((3,3),1e8),signal_mask=[True,True,False])
    forecast,risk=sources(names);diagnostics=[]
    actor=PortfolioPolicy(roster(["small_pool"],optimizer),forecast,risk,diagnostic_callback=diagnostics.append)
    decisions=[]
    def policy(di,ctx):
        decision=actor(di,ctx);decisions.append(decision)
        return decision
    result=run_many(market,["small_pool"],policy)
    assert all(decision.weights.shape==(1,3) and decision.explicit_mask.shape==(1,3) for decision in decisions)
    assert all(np.isfinite(decision.weights).all() and np.all(decision.weights>=0) and np.all(decision.weights<=.1+1e-10) for decision in decisions)
    assert result.daily.actual_name_count.le(3).all() and result.daily.cash.ge(0).all()
    assert result.daily.gross_exposure.le(.301).all()
    assert diagnostics and all(len(values)==3 for frame in diagnostics for values in frame.selected_tickers)
    if optimizer=="positive_equal":
        assert all(frame.gradient_evaluations.eq(0).all() and frame.exact_fixed_point.eq(False).all() for frame in diagnostics)


def test_full_candidate_top20_selects_highest_names_and_does_not_start_from_old_twenty():
    names=np.array([f"T{i:02}" for i in range(25)])
    dates=pd.bdate_range("2025-06-02",periods=2);prices=np.full((2,25),100.)
    market=MarketArrays(dates,names,prices,prices.copy(),adv=np.full((2,25),1e8),signal_mask=[True,False])
    forecast,risk=sources(names,days=2)
    actor=PortfolioPolicy(roster(["full_pool"],"positive_equal"),forecast,risk)
    result=run_many(market,["full_pool"],actor)
    bought=set(result.fills.loc[result.fills.side.eq("BUY"),"ticker"])
    assert bought==set(names[-20:])
    assert "T24" in bought and "T00" not in bought
