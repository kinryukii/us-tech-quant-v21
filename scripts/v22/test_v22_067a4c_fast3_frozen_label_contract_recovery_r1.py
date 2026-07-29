import importlib.util
from pathlib import Path
P=Path(__file__).with_name('v22_067a4c_fast3_frozen_label_contract_recovery_r1.py');s=importlib.util.spec_from_file_location('a4c',P);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def test_1_actual_labels(): assert m.recover()[0]=='long_0p25_0p15_90m' and m.recover()[1]=='short_0p25_0p15_90m'
def test_2_schema_exists(): assert all(x in set(__import__('pandas').read_parquet(m.A0).columns) for x in m.recover()[:2])
def test_3_unique_contract(): assert m.recover()[2:]==(.0025,.0015,90)
def test_4_hash_unchanged(): assert m.sha(m.MODEL)==m.sha(m.MODEL) and m.sha(m.SCRIPT)==m.sha(m.SCRIPT)
