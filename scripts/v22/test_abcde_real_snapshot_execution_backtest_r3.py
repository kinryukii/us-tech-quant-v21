import importlib.util
from pathlib import Path
import pandas as pd
import subprocess,sys,json
import pyarrow.parquet as pq
P=Path(__file__).with_name('abcde_real_snapshot_execution_backtest_r3.py');s=importlib.util.spec_from_file_location('r3',P);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def test_explicit_date_rank_is_accepted(tmp_path):
 p=tmp_path/'ranking.csv';pd.DataFrame({'signal_date':['2026-01-02'],'strategy':['A1'],'ticker':['AMD'],'rank':[1],'score':[2.]}).to_csv(p,index=False);d,e=m.read_candidate(p);assert e is None and len(d)==1
def test_filename_date_is_not_evidence(tmp_path):
 p=tmp_path/'2026-01-02_ranking.csv';pd.DataFrame({'ticker':['AMD'],'rank':[1],'strategy':['A1']}).to_csv(p,index=False);d,e=m.read_candidate(p);assert d is None and 'MISSING_EXPLICIT_DATE' in e
def test_e_r1_is_preserved_not_silently_e(): assert m.canonical_strategy('E_R1')=='E_R1' and m.canonical_strategy('E')=='E'
def test_v21_strategy_names_are_normalized():
 from abcde_daily_rank_snapshot_collector_r3 import norm_strategy
 assert [norm_strategy(x) for x in ['A1_CONTROL','B_STATIC_MOMENTUM','C_DYNAMIC_MOMENTUM','D_WEIGHT_OPTIMIZED_REFERENCE','E_R1_DEFENSIVE_REFERENCE']]==['A1','B','C','D','E_R1']
def test_collector_is_idempotent(tmp_path):
 d=tmp_path/'daily';d.mkdir();(d/'summary.json').write_text(json.dumps({'final_status':'SUCCESS'}));rows=[{'research_date':'2026-07-15','strategy':s,'ticker':f'{s}{i}','rank':i,'score':float(11-i)} for s in ['A1','B','C','D','E_R1'] for i in range(1,11)];pd.DataFrame(rows).to_csv(d/'abcde_rankings.csv',index=False)
 c=Path(__file__).with_name('abcde_daily_rank_snapshot_collector_r3.py');data=tmp_path/'data'
 for _ in range(2): subprocess.run([sys.executable,str(c),'--daily-run-dir',str(d),'--data-root',str(data)],check=True,capture_output=True,text=True)
 z=pq.read_table(data/'derived_cache'/'abcde_real_rank_snapshots_r3'/'historical_rankings_master.parquet').to_pandas();assert len(z)==50
