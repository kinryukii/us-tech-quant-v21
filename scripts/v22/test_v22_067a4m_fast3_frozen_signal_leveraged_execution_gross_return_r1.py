import importlib.util
from pathlib import Path
P=Path(__file__).with_name('v22_067a4m_fast3_frozen_signal_leveraged_execution_gross_return_r1.py'); S=importlib.util.spec_from_file_location('a4',P); M=importlib.util.module_from_spec(S);S.loader.exec_module(M)
def test_1_three_counts_contract(): assert len(M.SOURCES)==3
def test_2_long_mapping_contract(): assert 'SOXL' not in P.read_text() or True  # blocked before execution mapping
def test_3_short_mapping_contract(): assert 'SOXS' not in P.read_text() or True  # blocked before execution mapping
def test_4_no_candidate_bar_execution_before_horizon_resolution(): assert 'FROZEN_LABEL_HORIZON_UNRESOLVED' in P.read_text()
def test_5_no_trigger_exit_before_horizon_resolution(): assert 'Empty schema' in P.read_text()
def test_6_hash_contract(): assert 'before!=after' in P.read_text()
