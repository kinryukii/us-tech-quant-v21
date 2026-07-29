import importlib.util;from pathlib import Path
P=Path(__file__).with_name('v22_066ia0_fast3_frozen_ledger_mapping_audit_r1.py');S=importlib.util.spec_from_file_location('m',P);m=importlib.util.module_from_spec(S);S.loader.exec_module(m)
def test_01():assert m.PROV.exists()
def test_02():assert len(m.h(m.PROV))==64
def test_03():assert m.norm('US.QQQ')=='QQQ'
def test_04():assert m.MAP['TQQQ'][0]=='QQQ'
def test_05():assert m.MAP['SQQQ'][1]=='SHORT'
def test_06():assert m.MAP['SOXL'][0]=='SOXX'
def test_07():assert m.MAP['SOXS'][1]=='SHORT'
def test_08():assert m.dnorm('BUY')=='LONG'
def test_09():assert m.dnorm('SELL')=='SHORT'
def test_10():assert not m.MAP.get('BAD')
def test_11():assert len(m.REQ)==10
def test_12():assert 'gap_regime' in m.REQ
def test_13():assert m.norm('TQQQ')=='TQQQ'
def test_14():assert m.dnorm('-1')=='SHORT'
def test_15():assert True
