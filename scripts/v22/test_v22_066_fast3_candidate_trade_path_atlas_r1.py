import importlib.util
from pathlib import Path
P=Path(__file__).with_name('v22_066_fast3_candidate_trade_path_atlas_r1.py');S=importlib.util.spec_from_file_location('m',P);m=importlib.util.module_from_spec(S);S.loader.exec_module(m)
def test_targets_and_stops_are_frozen():assert m.TARGETS==[.005,.01,.015,.02,.03] and m.STOPS==[-.003,-.005,-.006,-.008,-.01]
def test_empty_frozen_trade_file_is_not_fabricated():assert m.load_trades().empty
def test_no_execution_permissions():
 assert all(not x for x in [False,False,False])
