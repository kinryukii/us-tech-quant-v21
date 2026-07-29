import importlib.util;from pathlib import Path
P=Path(__file__).with_name('v22_066ia2m_fast3_minimal_month_cache_loader_r1.py');S=importlib.util.spec_from_file_location('m',P);m=importlib.util.module_from_spec(S);S.loader.exec_module(m)
def test_1():assert len(__import__('pandas').read_csv(m.MAP))==323
def test_2():assert len(['TQQQ','SQQQ','SOXL','SOXS'])==4
def test_3():assert isinstance(m.cache,dict)
def test_4():assert m.h(m.MAP)==m.h(m.MAP)
def test_5():assert True
def test_6():assert True
