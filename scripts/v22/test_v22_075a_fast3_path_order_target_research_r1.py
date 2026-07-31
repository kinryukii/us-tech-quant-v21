import importlib.util,sys
from pathlib import Path
import numpy as np,pandas as pd
P=Path(__file__).with_name('v22_075a_fast3_path_order_target_research_r1.py');sp=importlib.util.spec_from_file_location('m075',P);M=importlib.util.module_from_spec(sp);sys.modules['m075']=M;sp.loader.exec_module(M)
def events(n=72):
 d=np.resize(pd.date_range('2023-01-02',periods=n//6,freq='B').strftime('%Y-%m-%d'),n);return pd.DataFrame({'date':d,'symbol':np.resize(M.SYMS,n),'TP_BEFORE_SL':np.resize([0,1],n),'prediction':np.linspace(.01,.99,n),'path_outcome':np.resize(['TP_FIRST','SL_FIRST','NEITHER','SAME_MINUTE_BOTH'],n),'strategy_gross_return':np.resize([.03,-.006,.002,-.006],n),'fold_id':np.resize([1,2,3,4,5],n)})
def bar(h,l,c=100): return pd.DataFrame({'open':[100.],'high':[h],'low':[l],'close':[c]})
def test_confirmation_zero_read(): assert 'confirmation_months' not in P.read_text(encoding='utf-8') and 'confirmation_row_read_count' in P.read_text(encoding='utf-8')
def test_exact_22_feature_contract(): assert len(M.FEATURES)==22 and M.CONTRACT.name=='feature_contract.json'
def test_path_classes():
 tp=pd.DataFrame({'open':[100.,100.],'high':[103.,102.],'low':[99.5,99.4],'close':[100.,100.]});sl=pd.DataFrame({'open':[100.,100.],'high':[102.,103.],'low':[99.4,99.5],'close':[100.,100.]})
 assert M.path_outcome(tp)[0]=='TP_FIRST' and M.path_outcome(sl)[0]=='SL_FIRST' and M.path_outcome(bar(102,99.5))[0]=='NEITHER'
def test_same_minute_both_is_stop(): assert M.path_outcome(bar(103,99.4))[0]=='SAME_MINUTE_BOTH' and M.path_outcome(bar(103,99.4))[1]==-.006
def test_plus3_target_mismatch():
 x=pd.DataFrame({'PLUS_3PCT_HIT_BY_CLOSE':[1,1,0],'path_outcome':['TP_FIRST','SL_FIRST','NEITHER']});assert int(x[x.PLUS_3PCT_HIT_BY_CLOSE==1].path_outcome.isin(['SL_FIRST','SAME_MINUTE_BOTH']).sum())==1
def test_top1_one_symbol_tiebreak():
 x=events();x.loc[x.date==x.date.iloc[0],'prediction']=.5;t,_=M.top1(x,x.date.nunique());assert t.date.nunique()==len(t) and t.iloc[0].symbol=='QQQ'
def test_expanding_full_dates(): assert len(M.folds(events().date))==5 and all(max(f['train_dates'])<min(f['test_dates']) for f in M.folds(events().date))
def test_two_fixed_models_no_search(): assert list(M.MODEL_SPECS)==['LOGISTIC_REGRESSION','CONSTRAINED_RANDOM_FOREST'] and M.MODEL_SPECS['CONSTRAINED_RANDOM_FOREST']['n_estimators']==300 and 'GridSearch' not in P.read_text()
def test_lift_and_returns():
 x=events();c=M.classify(x,[{'pr_auc_lift':1.2}],len(x));_,t=M.top1(x,x.date.nunique());assert c['pr_auc_lift'] is not None and t['daily_top1_mean_net_return'] is not None
def test_thresholds_and_negative_result_contract():
 c={'research_coverage_ratio':.8,'valid_fold_count':5,'pr_auc_lift':1.2,'top_decile_tp_before_sl_lift':1.5,'positive_fold_lift_ratio':.6,'median_fold_pr_auc_lift':1.01};t={'daily_top1_trade_count':1000,'daily_top1_date_coverage_ratio':.8,'daily_top1_mean_net_return':.001,'daily_top1_median_net_return':0,'daily_top1_positive_month_ratio':.55,'daily_top1_positive_fold_ratio':.6,'daily_top1_tp_first_rate':.2,'daily_top1_sl_first_rate':.1,'daily_top1_top5_date_profit_concentration':.59,'daily_top1_single_symbol_max_selection_ratio':.59};assert M.passes(c,t);c['pr_auc_lift']=1.19;assert not M.passes(c,t);assert 'FAST3_PREMARKET_RESEARCH_STOPPED_NO_PATH_ORDER_EDGE' in P.read_text()
def test_safety_and_summary_fields(): assert all(k in P.read_text() for k in ('final_frozen_model_output_count','broker_connection_count','order_output_count','outcome_distribution.csv'))
