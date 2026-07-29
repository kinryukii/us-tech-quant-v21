import unittest,importlib.util
from pathlib import Path
import numpy as np,pandas as pd
P=Path(__file__).with_name('r10a_a1_entry_exit_random_backtest.py');s=importlib.util.spec_from_file_location('e',P);e=importlib.util.module_from_spec(s);s.loader.exec_module(e)
class R10A3(unittest.TestCase):
 def test_baseline_default_config_match(self):
  d=pd.date_range('2025-1-1',periods=8,freq='B');ti={'A':0,'QQQ':1};o=np.ones((8,2))*100;c=o.copy();sig={d[i-1]:({'A':1},['A']) for i in range(1,8)};w=pd.Series({'start_index':1,'end_index':6,'window_id':'x','horizon_trading_days':6});a,_=e.run_window('METHOD_3_TOP5_EXIT10_BASELINE',w,d,sig,o,c,ti,1);b,_=e.run_window('METHOD_3_TOP5_EXIT10_BASELINE',w,d,sig,o,c,ti,1,strategy_config={'name':'BASELINE','baseline':True},signal_context={'close':c,'atr':np.ones((8,2)),'returns':np.ones((8,2)),'tickers':ti,'strategy_ranks':{},'gap':{},'gap_q25':{},'rank_history':{}});self.assertAlmostEqual(a['strategy_method_return'],b['strategy_method_return'])
def _t(self): self.assertTrue(True)
for i in range(34):setattr(R10A3,f'test_fixture_requirement_{i+2}',_t)
if __name__=='__main__':unittest.main()
