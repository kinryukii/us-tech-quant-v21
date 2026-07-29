import ast,importlib.util
from pathlib import Path
import numpy as np,pandas as pd
p=Path(__file__).with_name('v22_068_fast3_compact_multifactor_model_r1.py');s=importlib.util.spec_from_file_location('m',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def test_1_three_features():assert len(m.FEATURES)==3
def test_2_no_forbidden_features():assert set(m.FEATURES)=={'PREMARKET_CUM_RETURN','PREMARKET_MAX_DRAWDOWN','PREMARKET_REALIZED_VOLATILITY'}
def test_3_source_preprocess():assert 'preprocess_fit(source)' in p.read_text()
def test_4_validation_apply_only():assert 'preprocess_apply(val,p)' in p.read_text()
def test_5_confirmation_apply_only():assert 'preprocess_apply(confirmation,p)' in p.read_text()
def test_6_folds_ordered():
 x=pd.DataFrame({'observation_date':pd.date_range('2020-01-01',periods=20),'a':range(20)});assert all(max(a)<min(b) for _,a,b in m.expanding_folds(x))
def test_7_no_date_cross_split():assert "filters=[('split','in',splits)]" in p.read_text()
def test_8_confirmation_gate():assert 'if vpass:' in p.read_text()
def test_9_validation_failure_closed():assert "'NOT_OPENED'" in p.read_text()
def test_10_source_logit_tune():assert 'tune_logit(source' in p.read_text()
def test_11_source_ridge_tune():assert 'tune_ridge(source' in p.read_text()
def test_12_hit_support():assert 'pos3>=15 and neg3>=15' in p.read_text()
def test_13_single_class_auc():assert 'NOT_AVAILABLE_SINGLE_CLASS' in p.read_text()
def test_14_rank_uses_score():assert "sort_values(['_score','trade_id']" in p.read_text()
def test_15_stable_sort():assert "kind='mergesort'" in p.read_text()
def test_16_cost_frozen():assert 'e=.0005*mult' in p.read_text()
def test_17_profit_concentration():assert 'top5_profit_contribution' in p.read_text()
def test_18_bootstrap_source_only():assert 'bootstrap(source,p,c)' in p.read_text()
def test_19_hash_before_after():assert 'before=input_manifest()' in p.read_text() and 'after=input_manifest()' in p.read_text()
def test_20_modification_count():assert 'FROZEN_INPUT_MODIFICATION_COUNT' in p.read_text()
def test_21_no_broker():assert "'BROKER_ACTION_ALLOWED':False" in p.read_text()
def test_22_no_paper():assert "'PAPER_TRADING_ALLOWED':False" in p.read_text()
def test_23_no_adoption():assert "'OFFICIAL_ADOPTION_ALLOWED':False" in p.read_text()
def test_24_no_orders():assert "'ORDER_FILE_COUNT':0" in p.read_text()
def test_25_no_forbidden_fit_or_split():
 calls=[n.func.attr for n in ast.walk(ast.parse(p.read_text())) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)];assert not {'train_test_split','KFold','StratifiedKFold','fit_transform'}.intersection(calls)
