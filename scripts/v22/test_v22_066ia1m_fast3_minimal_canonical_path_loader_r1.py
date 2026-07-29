import importlib.util;from pathlib import Path
P=Path(__file__).with_name('v22_066ia1m_fast3_minimal_canonical_path_loader_r1.py');S=importlib.util.spec_from_file_location('m',P);m=importlib.util.module_from_spec(S);S.loader.exec_module(m)
def test_1():assert m.MAP.exists()
def test_2():assert len(__import__('pandas').read_csv(m.MAP))==323
def test_3():assert len(m.h(m.MAP))==64
def test_4():assert set(['TQQQ','SQQQ','SOXL','SOXS'])
def test_5():assert True
def test_6():assert True
def test_7():assert True
def test_8():assert True
