#!/usr/bin/env python
"""Read-only strict survival gate for existing V22.065A one-dimensional groups."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import numpy as np
import pandas as pd

SRC=Path(r"D:\us-tech-quant-results\v22\V22.065A_FAST3_PREMARKET_0925_EDGE_ATTRIBUTION_R1")
OUT=Path(r"D:\us-tech-quant-results\v22\V22.065B_FAST3_PREMARKET_SUBGROUP_SURVIVAL_GATE_R1")
PB=Path(r"D:\us-tech-quant-results\v22\V22.062PB_FAST3_CORPORATE_ACTION_SAFE_PRICE_NORMALIZATION_R1")
PR=Path(r"D:\us-tech-quant-results\v22\V22.062PR_FAST3_PREMARKET_INDEPENDENT_FORWARD_REPLICATION_R1")
PER=['2023-2024_VALIDATION','2025-2026_YTD_CONFIRMATION']
FILES=['v22_065a_summary.json','v22_065a_year_summary.csv','v22_065a_direction_summary.csv','v22_065a_instrument_summary.csv','v22_065a_signal_time_summary.csv','v22_065a_consensus_summary.csv','v22_065a_strength_bucket_summary.csv','v22_065a_volatility_bucket_summary.csv','v22_065a_gap_regime_summary.csv','v22_065a_cost_sensitivity.csv','v22_065a_trade_diagnostics.csv']
DIM={'direction':'direction','instrument':'selected_instrument','signal_time':'signal_time_bucket','consensus':'consensus','strength':'strength_bucket','volatility':'volatility_bucket','gap_regime':'gap_regime'}
class GateError(RuntimeError): pass
def h(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def metrics(x, ret):
    a=pd.to_numeric(x[ret],errors='coerce').dropna()
    if a.empty:return {k:np.nan for k in ['trade_count','positive_rate','mean_return','median_return','profit_factor','cumulative_return','max_drawdown']}
    win=a[a>0].sum(); loss=-a[a<0].sum(); curve=(1+a).cumprod()
    return {'trade_count':len(a),'positive_rate':(a>0).mean(),'mean_return':a.mean(),'median_return':a.median(),'profit_factor':win/loss if loss else np.inf,'cumulative_return':curve.iloc[-1]-1,'max_drawdown':(curve/curve.cummax()-1).min()}
def two_x(x):
    long=x.exit_price*(1-.001)/(x.entry_price*(1+.001))-1; short=x.entry_price*(1-.001)/(x.exit_price*(1+.001))-1
    return np.where(x.direction.eq('LONG'),long,short)*x.position_weight
def gate_row(dim,val,t):
    z=t[t[DIM[dim]].astype(str)==str(val)].copy(); z['two']=two_x(z)
    m={p:metrics(z[z.study_period.eq(p)],'account_return') for p in PER}; c={p:metrics(z[z.study_period.eq(p)],'two') for p in PER}
    pos=z[z.account_return>0].account_return.sum(); top=z.nlargest(5,'account_return').account_return
    years=z.groupby('calendar_year').account_return.apply(lambda a:(1+a).prod()-1); complete=len(years)>=3
    py=(years>0).sum(); ny=(years<0).sum(); dom=(years[years>0].max()/years[years>0].sum()) if (years>0).any() else np.nan
    fail=[]
    for p in PER:
        q=m[p]; r=c[p]
        for name,ok in [('TRADE_COUNT',q['trade_count'] >= (20 if p==PER[0] else 40)),('MEAN_RETURN',q['mean_return']>0),('MEDIAN_RETURN',q['median_return']>=0),('BASELINE_PF',q['profit_factor']>=1.2),('CUMULATIVE_RETURN',q['cumulative_return']>0),('MAX_DRAWDOWN',q['max_drawdown']>=-.05),('COST_2X_MEAN_RETURN',r['mean_return']>0),('COST_2X_PF',r['profit_factor']>=1.05),('COST_2X_CUMULATIVE_RETURN',r['cumulative_return']>0)]:
            if not pd.notna(ok) or not ok: fail.append(f'{p}:{name}' if pd.notna(q.get('mean_return',np.nan)) else 'MISSING_REQUIRED_METRIC')
    for name,ok in [('TOP1_CONCENTRATION',(top.iloc[:1].sum()/pos if pos else np.nan)<=.25),('TOP5_CONCENTRATION',(top.sum()/pos if pos else np.nan)<=.60)]:
        if not pd.notna(ok) or not ok: fail.append(name)
    if complete:
        if not py>ny: fail.append('YEAR_POSITIVE_NEGATIVE_BALANCE')
        if not pd.notna(dom) or dom>.60: fail.append('DOMINANT_YEAR_PROFIT_SHARE')
    row={'subgroup_dimension':dim,'subgroup_value':val,'top1_positive_profit_share':top.iloc[:1].sum()/pos if pos else np.nan,'top5_positive_profit_share':top.sum()/pos if pos else np.nan,'positive_year_count':py,'negative_year_count':ny,'dominant_year_profit_share':dom,'failed_gate_names':'|'.join(sorted(set(fail))),'strict_gate_pass':not fail}
    for p,label in zip(PER,['validation','confirmation']):
        for k,v in m[p].items(): row[f'{label}_{k}']=v
        row[f'{label}_2x_cost_profit_factor']=c[p]['profit_factor']; row[f'{label}_2x_cost_mean_return']=c[p]['mean_return']; row[f'{label}_2x_cost_cumulative_return']=c[p]['cumulative_return']
    return row, years, c
def run(src=SRC,out=OUT):
    for f in FILES:
        if not (src/f).exists(): raise GateError(f'missing V22.065A input {f}')
    frozen=[PB/'v22_062pb_corrected_trades.csv',PR/'v22_062pr_freeze_manifest.json']+[src/f for f in FILES]
    before={str(p):h(p) for p in frozen}
    t=pd.read_csv(src/'v22_065a_trade_diagnostics.csv'); required=['study_period','account_return','entry_price','exit_price','position_weight','direction','calendar_year']+list(DIM.values())
    if set(required)-set(t): raise GateError('trade diagnostics missing required existing fields')
    rows=[]; ys=[]; costs=[]
    for dim,col in DIM.items():
        for val in sorted(t[col].dropna().astype(str).unique()):
            r,y,c=gate_row(dim,val,t); rows.append(r)
            for year,ret in y.items():ys.append({'subgroup_dimension':dim,'subgroup_value':val,'calendar_year':year,'account_cumulative_return':ret})
            for p in PER:costs.append({'subgroup_dimension':dim,'subgroup_value':val,'report_period':p,'cost_multiple':2,**metrics(t[(t[col].astype(str)==val)&(t.study_period==p)].assign(two=two_x(t[(t[col].astype(str)==val)&(t.study_period==p)])),'two')})
    g=pd.DataFrame(rows); survivors=g[g.strict_gate_pass].copy()
    survivors['_p2']=survivors[['validation_2x_cost_profit_factor','confirmation_2x_cost_profit_factor']].min(axis=1); survivors['_pb']=survivors[['validation_profit_factor','confirmation_profit_factor']].min(axis=1); survivors['_n']=survivors.validation_trade_count+survivors.confirmation_trade_count; survivors['_dd']=survivors[['validation_max_drawdown','confirmation_max_drawdown']].abs().max(axis=1)
    survivors=survivors.sort_values(['_p2','_pb','_n','_dd','subgroup_dimension','subgroup_value'],ascending=[False,False,False,True,True,True]).head(3).drop(columns=['_p2','_pb','_n','_dd'])
    fail=g.failed_gate_names.str.split('|').explode(); fc=fail[fail.ne('')].value_counts().rename_axis('failed_gate_name').reset_index(name='count')
    missing=int(fail.eq('MISSING_REQUIRED_METRIC').sum()); sample_ok=int(((g.validation_trade_count>=20)&(g.confirmation_trade_count>=40)).sum())
    if len(survivors)==0: decision='NO_SUBGROUP_SURVIVES_STRICT_GATE'; nxt='STOP_PREMARKET_0925_HISTORICAL_OPTIMIZATION; V22.062PR_FROZEN_OBSERVATION_ONLY; NO_V22.065C'
    elif len(survivors)==1: decision='ONE_SUBGROUP_SURVIVES_FOR_PROSPECTIVE_TEST'; nxt='PROSPECTIVE_SHADOW_OBSERVATION_ONLY_NO_PAPER_OR_BROKER_ACTION'
    else: decision='MULTIPLE_SUBGROUPS_SURVIVE_FOR_PROSPECTIVE_TEST'; nxt='PROSPECTIVE_SHADOW_OBSERVATION_ONLY_NO_PAPER_OR_BROKER_ACTION'
    out.mkdir(parents=True,exist_ok=True); g.to_csv(out/'v22_065b_subgroup_gate.csv',index=False,encoding='utf-8-sig'); survivors.to_csv(out/'v22_065b_surviving_subgroups.csv',index=False,encoding='utf-8-sig'); fc.to_csv(out/'v22_065b_failed_gate_counts.csv',index=False,encoding='utf-8-sig'); pd.DataFrame(ys).to_csv(out/'v22_065b_year_stability.csv',index=False,encoding='utf-8-sig'); pd.DataFrame(costs).to_csv(out/'v22_065b_cost_survival.csv',index=False,encoding='utf-8-sig')
    changed=sum(h(Path(p))!=v for p,v in before.items()); summary={'version':'V22.065B_FAST3_PREMARKET_SUBGROUP_SURVIVAL_GATE_R1','final_status':'PASS','final_decision':decision,'source_subgroup_count':len(g),'eligible_sample_subgroup_count':sample_ok,'strict_gate_pass_count':len(survivors),'surviving_subgroups':survivors[['subgroup_dimension','subgroup_value']].to_dict('records'),'most_common_failed_gate':fc.iloc[0,0] if len(fc) else None,'validation_cost_2x_survivor_count':int((g.validation_2x_cost_profit_factor>=1.05).sum()),'confirmation_cost_2x_survivor_count':int((g.confirmation_2x_cost_profit_factor>=1.05).sum()),'cross_period_cost_2x_survivor_count':int(((g.validation_2x_cost_profit_factor>=1.05)&(g.confirmation_2x_cost_profit_factor>=1.05)).sum()),'missing_required_metric_count':missing,'cross_dimension_candidate_count':0,'frozen_file_modification_count':changed,'paper_trading_allowed':False,'broker_action_allowed':False,'official_adoption_allowed':False,'next_stage_recommendation':nxt}
    (out/'v22_065b_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    for k,v in [('FINAL_STATUS','PASS'),('FINAL_DECISION',decision),('SOURCE_SUBGROUP_COUNT',len(g)),('ELIGIBLE_SAMPLE_SUBGROUP_COUNT',sample_ok),('STRICT_GATE_PASS_COUNT',len(survivors)),('SURVIVING_SUBGROUPS',summary['surviving_subgroups']),('MOST_COMMON_FAILED_GATE',summary['most_common_failed_gate']),('VALIDATION_COST_2X_SURVIVOR_COUNT',summary['validation_cost_2x_survivor_count']),('CONFIRMATION_COST_2X_SURVIVOR_COUNT',summary['confirmation_cost_2x_survivor_count']),('CROSS_PERIOD_COST_2X_SURVIVOR_COUNT',summary['cross_period_cost_2x_survivor_count']),('MISSING_REQUIRED_METRIC_COUNT',missing),('CROSS_DIMENSION_CANDIDATE_COUNT',0),('FROZEN_FILE_MODIFICATION_COUNT',changed),('PAPER_TRADING_ALLOWED',False),('BROKER_ACTION_ALLOWED',False),('OFFICIAL_ADOPTION_ALLOWED',False),('NEXT_STAGE_RECOMMENDATION',nxt)]:print(f'{k}={v}')
    return summary
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--source',default=str(SRC));p.add_argument('--result-dir',default=str(OUT));a=p.parse_args()
 if not a.execute: print('FINAL_STATUS=BLOCKED_EXECUTE_FLAG_REQUIRED');raise SystemExit(2)
 try:run(Path(a.source),Path(a.result_dir))
 except Exception as e:print('FINAL_STATUS=FAIL');print(f'ERROR={e}');raise SystemExit(1)
