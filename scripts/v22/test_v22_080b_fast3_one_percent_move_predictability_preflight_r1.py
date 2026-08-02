import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
P=Path(__file__).with_name('v22_080b_fast3_one_percent_move_predictability_preflight_r1.py'); spec=importlib.util.spec_from_file_location('m',P); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
def test_tree_first_ge():
 t,s=m.build_tree(np.array([1.,2.,4.,3.]),True); assert m.first_cross(t,s,1,3,3.5,True)==2
def test_tree_first_le():
 t,s=m.build_tree(np.array([4.,3.,1.,2.]),False); assert m.first_cross(t,s,0,3,1.5,False)==2
def test_tree_no_cross():
 t,s=m.build_tree(np.array([1.,2.]),True); assert m.first_cross(t,s,0,1,3.,True)==-1
def test_approved_paths_excludes_confirmation_months(tmp_path):
 for y,mn in ((2025,1),(2025,2)):
  p=tmp_path/f'symbol=QQQ/year={y}/month={mn:02d}'; p.mkdir(parents=True); (p/'data.parquet').touch()
 assert len(m.approved_paths('QQQ',tmp_path))==1
def test_contract_has_confirmation_isolation(): assert m.CONF_START>m.VAL_END and 'CONFIRMATION_ISOLATION_VIOLATION' in P.read_text()
def test_random_asof_windows_are_deterministic_and_contiguous():
 x=pd.DataFrame({'decision_timestamp_et':pd.date_range('2024-01-01',periods=150,freq='D',tz='America/New_York'),'target_first':1})
 y=pd.DataFrame({'net_return_10bps':np.zeros(150),'net_return_20bps':np.zeros(150)})
 a=m.random_asof_robustness(x,y,seed=7,iterations=2,window_days=20); b=m.random_asof_robustness(x,y,seed=7,iterations=2,window_days=20)
 assert a.equals(b) and (a.selected_trade_count==20).all()
def test_safety_source(): assert 'order_generation_allowed":False' in P.read_text() and 'broker_action_allowed":False' in P.read_text()
