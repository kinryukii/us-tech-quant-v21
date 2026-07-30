import ast,importlib.util
from pathlib import Path
import pandas as pd,numpy as np
p=Path(__file__).with_name('v22_068d_fast3_compact_model_failure_diagnostic_r1.py');s=importlib.util.spec_from_file_location('d',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def test_1_confirmation_filter():assert "isin(['SOURCE','VALIDATION'])" in p.read_text()
def test_2_confirmation_count_zero():assert "'CONFIRMATION_ROW_READ_COUNT':0" in p.read_text()
def test_3_no_fit():assert '.fit(' not in p.read_text()
def test_4_no_score_mutation():assert "rename(columns={'prediction':'score'})" in p.read_text()
def test_5_no_reversal():assert "ascending=[ascending,True]" in p.read_text()
def test_6_no_hyperparameter():assert 'LogisticRegression' not in p.read_text()
def test_7_split_filter():assert set(m.only_open(pd.DataFrame({'split':['SOURCE','VALIDATION','CONFIRMATION']})).split)=={'SOURCE','VALIDATION'}
def test_8_small_group():assert 'INSUFFICIENT_FOR_AUC' in p.read_text()
def test_9_buckets_local():assert "z=g.dropna" in p.read_text()
def test_10_nonmonotonic_logic():assert 'np.argmax(q)' in p.read_text()
def test_11_psi():assert m.psi(pd.Series([1,2,3,4]),pd.Series([2,3,4,5]))>=0
def test_12_target_alignment():assert 'TARGET_ALIGNMENT' in p.read_text()
def test_13_stable_sort():assert "kind='mergesort'" in p.read_text()
def test_14_boundary_ties():assert 'cutoff_tie_count' in p.read_text()
def test_15_loo_summary_only():assert 'leave_one_out_min' in p.read_text()
def test_16_concentration():assert 'top5_profit_contribution' in p.read_text()
def test_17_hashes():assert 'before=manifest()' in p.read_text() and 'after=manifest()' in p.read_text()
def test_18_modcount():assert 'FROZEN_INPUT_MODIFICATION_COUNT' in p.read_text()
def test_19_no_broker():assert "'BROKER_ACTION_ALLOWED':False" in p.read_text()
def test_20_no_paper():assert "'PAPER_TRADING_ALLOWED':False" in p.read_text()
def test_21_no_adoption():assert "'OFFICIAL_ADOPTION_ALLOWED':False" in p.read_text()
def test_22_no_shadow():assert "'PROSPECTIVE_SHADOW_ALLOWED':False" in p.read_text()
def test_23_no_orders():assert "'ORDER_FILE_COUNT':0" in p.read_text()
def test_24_no_training_artifact():assert 'BINARY_MODEL_FILE_COUNT' in p.read_text()
def test_25_no_training_or_confirmation():
 t=p.read_text();assert 'train_test_split' not in t and 'CONFIRMATION' not in m.only_open(pd.DataFrame({'split':['CONFIRMATION']})).split.tolist()
