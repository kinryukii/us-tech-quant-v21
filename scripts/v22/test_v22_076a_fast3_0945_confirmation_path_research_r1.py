import importlib.util,sys
from pathlib import Path
import numpy as np,pandas as pd
P=Path(__file__).with_name('v22_076a_fast3_0945_confirmation_path_research_r1.py');sp=importlib.util.spec_from_file_location('m076',P);M=importlib.util.module_from_spec(sp);sys.modules['m076']=M;sp.loader.exec_module(M)
def bars(h,l,c=100): return pd.DataFrame({'open':[100.],'high':[h],'low':[l],'close':[c]})
def events(n=72):
 d=np.resize(pd.date_range('2023-01-02',periods=n//6,freq='B').strftime('%Y-%m-%d'),n);return pd.DataFrame({'date':d,'symbol':np.resize(M.SYMS,n),'TP_BEFORE_SL_FROM_0945':np.resize([0,1],n),'prediction':np.linspace(.01,.99,n),'path_outcome':np.resize(['TP_FIRST','SL_FIRST','NEITHER','SAME_MINUTE_BOTH'],n),'strategy_gross_return':np.resize([.03,-.006,.002,-.006],n),'fold_id':np.resize([1,2,3,4,5],n)})
def test_confirmation_sealed_and_fixed_contract(): assert 'confirmation_months' not in P.read_text(encoding='utf-8') and len(M.PREMARKET_FEATURES)==22 and len(M.CONFIRMATION_FEATURES)==15
def test_cutoff_and_no_post_entry_features(): assert "<=pd.Timestamp('09:45').time()" in P.read_text(encoding='utf-8') and 'post_entry_feature_row_read_count' in P.read_text(encoding='utf-8')
def test_volume_exclusion_is_exactly_two(): assert M.VOLUME_CONFIRMATION_FEATURES==['OPEN_TO_0945_VOLUME','OPEN_TO_0945_LAST_5M_VOLUME_SHARE'] and [x for x in M.CONFIRMATION_FEATURES if x not in M.VOLUME_CONFIRMATION_FEATURES].__len__()==13
def test_confirmation_features_math():
 x=pd.DataFrame({'open':[100]*16,'high':np.arange(101,117),'low':np.arange(99,83,-1),'close':np.arange(100,116),'volume':[1]*16});z=M.cfeat(x,True);assert set(M.CONFIRMATION_FEATURES[:11])<=set(z) and np.isclose(z['OPEN_TO_0945_RETURN'],.15)
def test_path_classes_and_stop_priority():
 assert M.path_outcome(bars(103,99.5))[0]=='TP_FIRST' and M.path_outcome(bars(102,99.4))[0]=='SL_FIRST' and M.path_outcome(bars(102,99.5))[0]=='NEITHER' and M.path_outcome(bars(103,99.4))==('SAME_MINUTE_BOTH',-.006)
def test_daily_top1_tiebreak_one_symbol():
 x=events();x.loc[x.date==x.date.iloc[0],'prediction']=.5;t,_=M.top1(x,x.date.nunique());assert len(t)==t.date.nunique() and t.iloc[0].symbol=='QQQ'
def test_complete_date_expanding_folds(): assert len(M.folds(events().date))==5 and all(max(x['train_dates'])<min(x['test_dates']) for x in M.folds(events().date))
def test_two_fixed_models_no_search(): assert list(M.MODEL_SPECS)==['LOGISTIC_REGRESSION','CONSTRAINED_RANDOM_FOREST'] and M.MODEL_SPECS['CONSTRAINED_RANDOM_FOREST']['n_estimators']==300 and 'GridSearch' not in P.read_text()
def test_same_fold_incremental_calculation():
 b={'pr_auc_lift':1.,'daily_top1_mean_net_return':0.,'daily_top1_sl_first_rate':.5,'daily_top1_max_drawdown':-.2};c={'pr_auc_lift':1.1,'daily_top1_mean_net_return':.01,'daily_top1_sl_first_rate':.4,'daily_top1_max_drawdown':-.1};assert all(v>0 for v in M.improvement(b,c).values())
def test_negative_result_is_pass_and_stopped_contract(): assert "'final_status':'PASS'" in P.read_text() and 'FAST3_0945_RESEARCH_STOPPED_NO_EXECUTABLE_EDGE' in P.read_text()
def test_safety_and_summary_outputs(): assert all(x in P.read_text() for x in ('final_frozen_model_output_count','broker_connection_count','order_output_count','classification_scorecard.csv','outcome_distribution.csv'))
