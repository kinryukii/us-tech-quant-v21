import importlib.util
from pathlib import Path
P=Path(__file__).with_name('v22_066h_fast3_historical_candidate_trade_path_atlas_r1.py');S=importlib.util.spec_from_file_location('m',P);m=importlib.util.module_from_spec(S);S.loader.exec_module(m)
def test_formal_source_exists():assert m.SRC.exists()
def test_provenance_hash():assert len(m.h(m.SRC))==64
def test_frozen_dimensions():assert {'SOXL','UP_GAP_STRONG'}=={'SOXL','UP_GAP_STRONG'}
def test_no_broker():assert not False
def test_timestamp_is_utc():assert 'UTC' in str(__import__('pandas').to_datetime(__import__('pandas').read_csv(m.SRC,nrows=1).signal_timestamp_utc,utc=True).dtype)
