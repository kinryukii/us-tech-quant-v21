import importlib.util
from pathlib import Path
import pandas as pd

P=Path(__file__).with_name('abcde_conditional_execution_backtest_r7.py')
S=importlib.util.spec_from_file_location('r7',P); M=importlib.util.module_from_spec(S); S.loader.exec_module(M)
def test_one_real_date_waits_for_second_date():
 rows=[]
 for s in M.STRATEGIES:
  for r in range(1,11): rows.append({'signal_date':'2026-07-13','strategy':s,'ticker':f'T{r}','rank':r})
 info,audit,_=M.integrity(pd.DataFrame(rows))
 assert info['ranking_integrity_pass'] is True
 assert info['common_signal_date_count']==1
 assert audit.row_count.tolist()==[10]*5
def test_duplicate_rank_blocks_integrity():
 rows=[]
 for s in M.STRATEGIES:
  for r in range(1,11): rows.append({'signal_date':'2026-07-13','strategy':s,'ticker':f'{s}{r}','rank':1 if r==2 else r})
 info,_,_=M.integrity(pd.DataFrame(rows))
 assert info['ranking_integrity_pass'] is False
