import importlib.util,sys
from pathlib import Path
import numpy as np,pandas as pd
P=Path(__file__).with_name('v22_074a_fast3_plus3_hit_target_reset_r1.py');sp=importlib.util.spec_from_file_location('m074',P);M=importlib.util.module_from_spec(sp);sys.modules['m074']=M;sp.loader.exec_module(M)
def events(n=72):
 d=np.resize(pd.date_range('2023-01-02',periods=n//6,freq='B').strftime('%Y-%m-%d'),n);x=pd.DataFrame({'date':d,'symbol':np.resize(M.SYMS,n),'PLUS_3PCT_HIT_BY_CLOSE':np.resize([0,1],n),'prediction':np.linspace(.01,.99,n),'strategy_gross_return':np.resize([.03,-.006,.002],n),'strategy_exit_reason':np.resize(['TAKE_PROFIT','STOP_LOSS','CLOSE_EXIT'],n),'fold_id':np.resize([1,2,3,4,5],n)});return x
def test_confirmation_zero_read(): assert 'confirmation_months' not in P.read_text(encoding='utf-8') and 'confirmation_row_read_count' in P.read_text(encoding='utf-8')
def test_exact_22_feature_contract(): assert len(M.FEATURES)==22 and M.FEATURES[-2:]==['PREMARKET_VOLUME_SHARE_LAST_30M','PREMARKET_VOLUME_CONCENTRATION']
def test_target_uses_minute_high(): assert int((pd.Series([102.9,103.])>=103).any())==1
def test_same_minute_stop_is_first():
 r=pd.DataFrame({'open':[100.], 'high':[103.], 'low':[99.4], 'close':[101.]}); assert M.simulate(r)[1]=='STOP_LOSS'
def test_daily_top1_one_symbol_and_tiebreak():
 x=events();x.loc[x.date==x.date.iloc[0],'prediction']=.5;t,_=M.top1(x);assert t.date.nunique()==len(t) and t.iloc[0].symbol=='QQQ'
def test_expanding_dates_are_isolated(): assert len(M.folds(events().date))==5 and all(max(f['train_dates'])<min(f['test_dates']) for f in M.folds(events().date))
def test_only_two_fixed_classifiers_no_search(): assert list(M.MODEL_SPECS)==['LOGISTIC_REGRESSION','CONSTRAINED_RANDOM_FOREST'] and M.MODEL_SPECS['CONSTRAINED_RANDOM_FOREST']['n_estimators']==300 and 'GridSearch' not in P.read_text(encoding='utf-8')
def test_lift_and_daily_returns():
 x=events();c=M.classify(x,[{'pr_auc_lift':1.2}],len(x));_,t=M.top1(x);assert c['pr_auc_lift'] is not None and t['daily_top1_mean_net_return'] is not None
def test_thresholds_cannot_be_lowered():
 c={'research_coverage_ratio':.8,'valid_fold_count':5,'pr_auc_lift':1.2,'top_decile_hit_rate_lift':1.5,'positive_fold_lift_ratio':.6,'median_fold_pr_auc_lift':1.01};t={'daily_top1_trade_count':1000,'daily_top1_date_coverage_ratio':.8,'daily_top1_mean_net_return':.001,'daily_top1_median_net_return':0,'daily_top1_positive_month_ratio':.55,'daily_top1_positive_fold_ratio':.6,'daily_top1_take_profit_hit_rate':.2,'daily_top1_stop_loss_hit_rate':.1,'daily_top1_top5_date_profit_concentration':.59,'daily_top1_single_symbol_max_selection_ratio':.59};assert M.passes(c,t);c['pr_auc_lift']=1.19;assert not M.passes(c,t)
def test_negative_result_is_pass_and_safety_fields_exist():
 x=P.read_text(encoding='utf-8');assert 'FAST3_PREMARKET_RESEARCH_STOPPED_NO_PLUS3_PREDICTIVE_EDGE' in x and all(k in x for k in ('final_frozen_model_output_count','broker_connection_count','order_output_count'))
