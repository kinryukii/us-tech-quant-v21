import importlib.util,sys
from pathlib import Path
import numpy as np
import pandas as pd
P=Path(__file__).with_name('r10a2_a1_temporal_effectiveness.py');s=importlib.util.spec_from_file_location('m',P);m=importlib.util.module_from_spec(s);sys.modules['m']=m;s.loader.exec_module(m)
def test_paired_is_window_aligned():
 a=pd.DataFrame({'window_id':['a','b'],'strategy_method_return':[.1,.2],'strategy_max_drawdown':[-.1,-.2],'turnover':[1.,2.],'average_invested_exposure':[.8,.9]});b=a.copy();b.strategy_method_return=[.0,.1];z=m.paired(a,b,1);assert z['paired_window_count']==2 and z['median_delta']>.09
def test_stats_small_sample_descriptive_only():
 x=pd.DataFrame({'strategy_method_return':[.1],'qqq_return':[.0],'excess_return':[.1],'strategy_max_drawdown':[-.1],'trade_count':[1],'median_holding_days':[2],'turnover':[1.],'horizon_trading_days':[20],'transaction_cost':[.1],'average_invested_exposure':[1.],'average_cash_share':[0.]});assert m.stats(x,1)['inference_allowed']==False
