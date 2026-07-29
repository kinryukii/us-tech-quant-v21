from __future__ import annotations
import numpy as np
import pandas as pd
import pytest
import v22_063r1_fast3_rth_vwap_mean_reversion_r1 as mod

def valid_061():
    return {'final_status':'PASS','final_decision':'NO_ORB_BASELINE_CANDIDATE_QUALIFIED','previous_pullback_reentry_architecture_used':False,'supported_exit_variants_for_replication':[],'canonical_partition_count_indexed':582,'parameter_sweep_executed':False,'canonical_files_modified':False,'raw_files_modified':False,'new_market_data_cache_created':False,'broker_action_allowed':False,'paper_trading_allowed':False,'official_adoption_allowed':False}

def valid_pr():
    return {'final_status':'PASS','final_decision':'FORWARD_REPLICATION_IN_PROGRESS_INSUFFICIENT_INTERIM_SAMPLE','v22_062pb_validated':True,'research_cutoff_date':'2026-07-24','forward_holdout_only':True,'rule_change_requires_reset':True,'sole_exit_variant':'PREMARKET_0925','historical_pre_cutoff_outcomes_used_for_qualification':False,'parameter_sweep_executed':False,'threshold_optimization_executed':False,'strategy_rule_change_executed':False,'canonical_files_modified':False,'raw_files_modified':False,'new_market_data_cache_created':False,'broker_action_allowed':False,'paper_trading_allowed':False,'official_adoption_allowed':False}

def synthetic(date='2026-01-05',base=100.0):
    et=pd.date_range(f'{date} 09:30',periods=390,freq='min',tz='America/New_York'); close=base+np.arange(390)*0.001
    return pd.DataFrame({'timestamp_utc':et.tz_convert('UTC'),'trade_date':date,'session_minute':np.arange(390),'open':close,'high':close+.05,'low':close-.05,'close':close,'volume':1000.0})

def grid(base=100.0):
    n,_,_=mod.normalize_scale_series(synthetic(base=base)); return mod.session_grid(n)

def forced_long():
    q,s=grid(100),grid(200)
    for g,b in ((q,100),(s,200)):
        g.loc[60:66,'normalized_close']=np.linspace(b-4,b-3,7); g.loc[60:66,'normalized_open']=g.loc[60:66,'normalized_close']; g.loc[60:66,'normalized_high']=g.loc[60:66,'normalized_close']+.1; g.loc[60:66,'normalized_low']=g.loc[60:66,'normalized_close']-.1
        g.loc[60:66,'ret_5m']=.01; g.loc[60:66,'normalized_vwap_deviation']=-2.; g.loc[60:66,'prior_high']=g.loc[60:66,'normalized_close']-.1; g.loc[60:66,'tradability_proxy_pass']=True; g['session_complete']=True
    return q,s

def test_validate_lineages(): mod.validate_v22_061(valid_061()); mod.validate_v22_062pr(valid_pr())
def test_validate_rejects():
    s=valid_pr(); s['rule_change_requires_reset']=False
    with pytest.raises(mod.StudyError): mod.validate_v22_062pr(s)
def test_study_periods(): assert mod.study_period(2020)==mod.PERIODS[0] and mod.study_period(2024)==mod.PERIODS[1] and mod.study_period(2026)==mod.PERIODS[2]
def test_path_parse(): assert mod.symbol_month_from_path(mod.Path('x')/'symbol=US.QQQ'/'year=2025'/'month=7'/'a.parquet')==('QQQ','2025','07')
def test_split_snap(): assert mod.snap_split_factor(10)[0]==pytest.approx(10) and mod.snap_split_factor(1.35) is None
def test_normalize_split():
    f=synthetic().head(10); f.loc[5:,['open','high','low','close']]/=10
    n,r,u=mod.normalize_scale_series(f); assert len(r)==1 and u.empty and n.loc[5,'normalized_open']==pytest.approx(n.loc[4,'normalized_close'],rel=.03)
def test_grid_complete(): assert bool(grid().session_complete.iloc[0])
def test_grid_incomplete():
    f=synthetic().iloc[:-1]; n,_,_=mod.normalize_scale_series(f); assert not bool(mod.session_grid(n).session_complete.iloc[0])
def test_candidate_long():
    q,s=forced_long(); c,reasons=mod.build_candidate('2026-01-05',q,s,{'QQQ':pd.DataFrame(),'SOXX':pd.DataFrame()},{'QQQ':pd.DataFrame(),'SOXX':pd.DataFrame()}); assert not reasons and c and c['direction']=='LONG'
def test_candidate_event_block():
    q,s=forced_long(); e=pd.DataFrame({'timestamp_utc':[pd.Timestamp('2026-01-05 16:00:00+00:00')]}); c,reasons=mod.build_candidate('2026-01-05',q,s,{'QQQ':e,'SOXX':pd.DataFrame()},{'QQQ':pd.DataFrame(),'SOXX':pd.DataFrame()}); assert c is None and reasons
def test_fixed_exits():
    q,s=grid(),grid(200); assert mod.exit_minute('FIXED_15M',100,'LONG',q,s)==115 and mod.exit_minute('FIXED_30M',100,'LONG',q,s)==130
def test_vwap_touch_exit():
    q,s=grid(),grid(200)
    q.loc[100:104,'normalized_close']=q.loc[100:104,'vwap']-.1
    s.loc[100:104,'normalized_close']=s.loc[100:104,'vwap']-.1
    q.loc[105,'normalized_close']=q.loc[105,'vwap']+.1
    s.loc[105,'normalized_close']=s.loc[105,'vwap']+.1
    assert mod.exit_minute('DUAL_VWAP_TOUCH_OR_30M',100,'LONG',q,s)==105
def test_return_from_grid(): assert mod.return_from_grid(grid(),100,115)[1]['holding_minutes']==15
def test_net_return(): assert mod.net_return(100,101)==pytest.approx(101*(1-mod.EXIT_COST)/(100*(1+mod.ENTRY_COST))-1)
def test_profit_factor(): assert mod.profit_factor(pd.Series([.02,.01,-.01]))==pytest.approx(3)
def test_positive_share(): assert mod.positive_profit_share(pd.Series([.8,.1,.1,-.1]),1)==pytest.approx(.8)
def test_cumulative(): assert mod.cumulative_return(pd.Series([.1,-.1]))==pytest.approx(-.01)
def test_drawdown(): assert mod.maximum_drawdown(pd.Series([.1,-.2,.1]))==pytest.approx(-.2)
def test_choose_insufficient():
    q=pd.DataFrame({'exit_variant':list(mod.EXIT_VARIANTS),'sample_pass':[False]*3,'research_candidate_for_independent_replication':[False]*3}); assert mod.choose_decision(q)[0]=='RTH_VWAP_MEAN_REVERSION_INCONCLUSIVE_INSUFFICIENT_SAMPLE'
def test_choose_supported():
    q=pd.DataFrame({'exit_variant':list(mod.EXIT_VARIANTS),'sample_pass':[True]*3,'research_candidate_for_independent_replication':[False,True,False]}); assert mod.choose_decision(q)[1]==['FIXED_30M']
def test_defaults():
    a=mod.parse_args(['--execute']); assert 'V22.061_FAST3' in a.v22_061_summary and 'V22.062PR_FAST3' in a.v22_062pr_summary and 'moomoo_24h_1m' in a.canonical_root
def test_constants(): assert mod.SIGNAL_START==60 and mod.SIGNAL_END==270 and mod.DEVIATION_THRESHOLD==1.5 and mod.FIXED_ACCOUNT_WEIGHT==.2
