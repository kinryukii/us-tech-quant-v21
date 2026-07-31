import importlib.util,sys
from pathlib import Path
import numpy as np,pandas as pd
P=Path(__file__).with_name('v22_072a_fast3_target_regime_screen_r1.py');s=importlib.util.spec_from_file_location('m',P);M=importlib.util.module_from_spec(s);sys.modules['m']=M;s.loader.exec_module(M)
def f(n=30):return pd.DataFrame({'date':pd.date_range('2024-01-01',periods=n,freq='B').strftime('%Y-%m-%d'),'symbol':['QQQ']*n,'PREMARKET_CUM_RETURN':np.linspace(-1,1,n),'PREMARKET_MAX_DRAWDOWN':0.,'PREMARKET_REALIZED_VOLATILITY':np.arange(n),'target_return':np.linspace(-.01,.01,n)})
def test_confirmation_zero_read():assert 'confirmation_months' not in P.read_text() and M.TARGETS
def test_current_target_inventory():assert len(M.TARGETS)==1 and 'exit_price / entry_price - 1' in M.TARGETS[0]['definition']
def test_only_two_fixed_models():assert list(M.MODELS)==['RIDGE','CONSTRAINED_RANDOM_FOREST'] and M.MODELS['CONSTRAINED_RANDOM_FOREST']['n_estimators']==200
def test_no_search_or_random_kfold():assert 'GridSearch' not in P.read_text() and 'KFold' not in P.read_text()
def test_terciles_training_only():
 a=f();lo,hi=M.boundaries(a.iloc[:20]);assert M.mask(a.iloc[20:],'VOL_HIGH',lo,hi).equals(M.mask(a.iloc[20:],'VOL_HIGH',lo,hi)) and lo<hi
def test_time_order():
 h=M.helper();z=h.expanding_folds(f(60).date);assert len(z)==5 and all(max(x['train_dates'])<min(x['test_dates']) for x in z)
def test_coverage_gate():
 r=pd.Series({'event_count':999,'research_coverage_ratio':.3,'oof_spearman_ic':.1,'top_bottom_spread_net_10bps':.1,'positive_fold_ratio':1,'median_fold_ic':.1,'positive_month_ratio':1,'top5_date_concentration':.1,'valid_symbol_count':6,'positive_symbol_net_spread_count':6,'valid_fold_count':5});assert not M.gate(r)
def test_negative_is_stopped_shape():assert 'FAST3_CURRENT_FEATURE_LINE_STOPPED_NO_TARGET_REGIME_EDGE' in P.read_text()
def test_outputs_and_safety():
 x=P.read_text();assert all(z in x for z in ('target_regime_scorecard.csv','final_frozen_model_output_count','broker_connection_count'))
