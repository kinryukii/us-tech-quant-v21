import importlib.util
from pathlib import Path
p=Path(__file__).with_name("v22_067a4m3_fast3_frozen_signal_leveraged_gross_return_r1.py");s=importlib.util.spec_from_file_location("m",p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def test_1_contract(): c=__import__("json").loads(m.K.read_text());assert (c["target_threshold"],c["adverse_threshold"],c["prediction_horizon_minutes"])==(.0025,.0015,90)
def test_2_counts(): assert sum(a+b for _,_,a,b in m.S)==1944
def test_3_mapping(): assert "SOXL" in p.read_text() and "SOXS" in p.read_text()
def test_4_entry_next_bar(): assert "timestamp_utc>pd.Timestamp(ts)" in p.read_text()
def test_5_exit_next_bar(): assert "ex=N(lev,base)" in p.read_text()
def test_6_hash(): assert m.H(m.K)==m.H(m.K)
