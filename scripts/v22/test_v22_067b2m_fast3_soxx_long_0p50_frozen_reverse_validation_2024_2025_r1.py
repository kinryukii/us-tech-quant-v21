import importlib.util
from pathlib import Path
import pandas as pd
p=Path(__file__).with_name("v22_067b2m_fast3_soxx_long_0p50_frozen_reverse_validation_2024_2025_r1.py");s=importlib.util.spec_from_file_location("m",p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def test_1_bundle(): _,f,t,c=m.load_frozen_bundle();assert f and t>0 and c["horizon"]==90
def test_2_threshold(): assert m.load_frozen_bundle()[2]>0
def test_3_race(): assert m.classify_long_race(pd.DataFrame([{"high":100.5,"low":99.9}]),100)=="TARGET_FIRST"
def test_4_dual(): assert m.classify_long_race(pd.DataFrame([{"high":100.5,"low":99.75}]),100)=="BOTH_SAME_MINUTE"
def test_5_dedup(): x=pd.DataFrame({"model_probability":[.9,.8,.7],"overlap_group_id":["a","a","b"],"trading_date_et":["x","x","y"],"session":["P","P","Q"]});z,n=m.select_and_deduplicate(x,.75);assert n==2 and len(z)==1
def test_6_concentration(): assert m.calculate_month_concentration(pd.Series([45,41]))["corrected_gate_pass"]
def test_7_scope(): t=p.read_text();assert "SHORT_MODEL_CREATED=False" in t and "fit(" not in t and m.DIRECTION=="LONG"
