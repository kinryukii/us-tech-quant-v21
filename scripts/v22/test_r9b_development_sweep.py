import tempfile
from pathlib import Path
import pandas as pd
from r9b_development_sweep import catalog,manifest,gates
def main():
 c=catalog();assert len(c)<=32 and c.parameter_hash.nunique()==len(c) and c.is_baseline.sum()==1
 m=manifest(pd.date_range('2020-01-01',periods=600,freq='B'),2);assert set(m.split)=={'DEVELOPMENT'} and m.window_id.nunique()==len(m)
 p=pd.DataFrame([{'candidate_id':'BASE_CURRENT_RULE','median_excess_vs_qqq':.1,'beat_qqq_share':.6,'worst_return':-.1,'lower_decile_return':-.05,'worst_max_drawdown':-.1,'valid_window_share':1,'median_annualized_turnover':1},{'candidate_id':'X','median_excess_vs_qqq':.1,'beat_qqq_share':.6,'worst_return':-.1,'lower_decile_return':-.05,'worst_max_drawdown':-.1,'valid_window_share':1,'median_annualized_turnover':1}]);h=pd.concat([p.assign(horizon=x) for x in [20,60,120,252,504]]);g,_=gates(p,h,p.iloc[0]);assert g.candidate_pass.all();print('R9B_UNIT_TESTS=3')
if __name__=='__main__':main()
