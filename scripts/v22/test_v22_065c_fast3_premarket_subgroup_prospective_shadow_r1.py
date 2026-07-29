import sys;from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent));import v22_065c_fast3_premarket_subgroup_prospective_shadow_r1 as m
def test_cutoff_and_thresholds():assert m.CUT=='2026-07-24'
def test_no_cross_candidate():assert 'SOXL_AND_UP_GAP_STRONG' not in m.__dict__
