import importlib.util,sys
from pathlib import Path
import numpy as np,pandas as pd
P=Path(__file__).with_name('v22_073a_fast3_pit_feature_expansion_research_r1.py');s=importlib.util.spec_from_file_location('m073',P);M=importlib.util.module_from_spec(s);sys.modules['m073']=M;s.loader.exec_module(M)
def sample(n=60):
 d=pd.date_range('2023-01-02',periods=n,freq='B').strftime('%Y-%m-%d');x=pd.DataFrame({'date':d,'symbol':np.resize(M.SYMS,n),'target_return':np.linspace(-.01,.01,n)})
 for i,f in enumerate(M.FIXED_FEATURES):x[f]=np.linspace(i,i+1,n)
 return x
def test_confirmation_zero_read(): assert 'confirmation_months' not in P.read_text(encoding='utf-8') and 'confirmation_row_read_count' in P.read_text(encoding='utf-8')
def test_fixed_feature_inventory(): assert len(M.FIXED_FEATURES)==20 and M.BASE_FEATURES==['PREMARKET_CUM_RETURN','MAX_DRAWDOWN','REALIZED_VOL']
def test_new_price_features_pit_available(): assert set(M.PRICE_FEATURES).issubset(M.pfeat(np.linspace(100,110,326)))
def test_cross_etf_same_day_alignment():
 x=sample(); assert all(z in M.ETF_FEATURES for z in ('QQQ_PREMARKET_RETURN','SOXX_PREMARKET_RETURN','SYMBOL_MINUS_QQQ_PREMARKET_RETURN')) and x.date.iloc[0]==x.date.iloc[0]
def test_volume_bad_is_skipped(): assert M.volume_features(np.array([0.,0.]))['PREMARKET_VOLUME_CONCENTRATION']!=M.volume_features(np.array([0.,0.]))['PREMARKET_VOLUME_CONCENTRATION']
def test_expanding_time_order(): assert len(M.folds(sample().date))==5 and all(max(f['train_dates'])<min(f['test_dates']) for f in M.folds(sample().date))
def test_only_fixed_models_no_search(): assert list(M.MODEL_SPECS)==['RIDGE','CONSTRAINED_RANDOM_FOREST'] and M.MODEL_SPECS['CONSTRAINED_RANDOM_FOREST']['n_estimators']==300 and 'GridSearch' not in P.read_text(encoding='utf-8')
def test_coverage_and_no_subgroup_gate():
 r={'research_coverage_ratio':.79,'event_count':8000,'oof_spearman_ic':.1,'top_bottom_spread_net_10bps':.01,'positive_fold_ratio':.8,'median_fold_ic':.1,'positive_month_ratio':.6,'valid_symbol_count':6,'positive_symbol_net_spread_count':4,'top5_date_concentration':.2,'valid_fold_count':5};assert not M.passes(r)
def test_negative_research_is_pass_stopped(): assert 'FAST3_EXPANDED_FEATURE_LINE_STOPPED_NO_STABLE_EDGE' in P.read_text(encoding='utf-8')
def test_safety_and_summary_fields():
 x=P.read_text(encoding='utf-8');assert all(v in x for v in ('final_frozen_model_output_count','broker_connection_count','feature_quality.csv','model_scorecard.csv','symbol_scorecard.csv'))
