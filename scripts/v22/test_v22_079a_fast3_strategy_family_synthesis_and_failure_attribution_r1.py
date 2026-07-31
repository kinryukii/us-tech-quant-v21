import importlib.util
from pathlib import Path
P=Path(__file__).with_name('v22_079a_fast3_strategy_family_synthesis_and_failure_attribution_r1.py');s=importlib.util.spec_from_file_location('x',P);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def test_sealed():assert m.NA.startswith('NOT_AVAILABLE') and m.FAMILIES['EVENT_24H'][-1]=='V22.078A'
def test_families():assert set(m.FAMILIES)=={'PREMARKET_FORWARD','COMPACT_MODEL','EVENT_24H'}
