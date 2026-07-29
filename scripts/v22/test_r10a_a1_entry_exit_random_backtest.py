import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

P = Path(__file__).with_name("r10a_a1_entry_exit_random_backtest.py")
S = importlib.util.spec_from_file_location("r10a", P); M = importlib.util.module_from_spec(S); S.loader.exec_module(M)


def fixture(method):
    days = pd.date_range("2025-01-01", periods=16, freq="B"); ti={"AAA":0,"BBB":1,"CCC":2,"DDD":3,"EEE":4,"FFF":5,"QQQ":6}
    op=np.full((16,7),100.); cl=np.full((16,7),101.); cl[:,6]=102.
    sig={days[d-1]:({t:i+1 for i,t in enumerate(["AAA","BBB","CCC","DDD","EEE","FFF"])},["AAA","BBB","CCC","DDD","EEE","FFF"]) for d in range(1,16)}
    w=pd.Series({"start_index":1,"end_index":14,"window_id":"X","horizon_trading_days":14})
    return M.run_window(method,w,days,sig,op,cl,ti,ti["QQQ"])


def test_six_methods_and_next_open_execution():
    assert len(M.METHODS)==6
    for method in M.METHODS:
        z,tr=fixture(method)
        assert z["forced_exit_count"] <= M.METHODS[method][0]
        assert all(t["day"] >= 1 for t in tr)
        assert z["transaction_cost"] > 0


def test_fixed10_and_forced_exit():
    z,tr=fixture("METHOD_6_TOP5_FIXED10")
    assert z["forced_exit_count"] == 5
    assert any(not t["forced"] and t["holding_days"] == 11 for t in tr if t["side"]=="SELL")
    assert len({t["ticker"] for t in tr if t["side"]=="BUY"}) <= 5


def test_no_rebalance_and_slot_limit():
    z,tr=fixture("METHOD_3_TOP5_EXIT10_BASELINE")
    assert z["trade_count"] == 10
    assert z["turnover"] > 1
    assert z["average_invested_exposure"] > 0


def test_optional_daily_path_is_aggregate_compatible():
    z0,_=fixture("METHOD_6_TOP5_FIXED10")
    days=pd.date_range("2025-01-01",periods=16,freq="B");ti={"AAA":0,"BBB":1,"CCC":2,"DDD":3,"EEE":4,"FFF":5,"QQQ":6};op=np.full((16,7),100.);cl=np.full((16,7),101.);cl[:,6]=102.;sig={days[d-1]:({t:i+1 for i,t in enumerate(["AAA","BBB","CCC","DDD","EEE","FFF"])},["AAA","BBB","CCC","DDD","EEE","FFF"]) for d in range(1,16)};w=pd.Series({"start_index":1,"end_index":14,"window_id":"X","horizon_trading_days":14})
    z1,t1=M.run_window("METHOD_6_TOP5_FIXED10",w,days,sig,op,cl,ti,ti["QQQ"],return_daily_path=True)
    assert "daily_path" not in z0 and abs(z0["strategy_method_return"]-z1["strategy_method_return"])<1e-12
    p=z1["daily_path"];assert len(p["dates"])==len(p["nav"])==len(p["daily_returns"])==len(p["cash"])
    assert all(p["dates"][i]<p["dates"][i+1] for i in range(len(p["dates"])-1)) and p["is_terminal_liquidation"][-1]
    assert abs(M.compute_max_drawdown_from_nav(p["nav"])-z1["strategy_max_drawdown"])<1e-12


def test_exposure_accounting_definitions():
    assert M.exposure_metrics(0., 1.)[:2] == (0., 1.)
    assert M.exposure_metrics(.5, .5)[:2] == (.5, .5)
    assert M.exposure_metrics(1., 0.)[:2] == (1., 0.)
    z, _ = fixture("METHOD_3_TOP5_EXIT10_BASELINE")
    assert 0 <= z["average_cash_share"] <= 1
    assert 0 <= z["median_cash_share"] <= 1
    assert abs(z["average_cash_share"] + z["average_invested_exposure"] - 1) < 1e-9
    assert z["terminal_liquidation_excluded"]
