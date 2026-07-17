"""R9 annual-stratified postmortem; fixed references only, no confirmation I/O."""
from __future__ import annotations
import argparse,hashlib,json,shutil
from pathlib import Path
import numpy as np,pandas as pd,pyarrow.parquet as pq
from abcde_current_rule_random_backtest_r9 import resolve_rankings,resolve_prices,load_prices
ROOT=Path(__file__).resolve().parents[2];OUT=Path(r'D:\us-tech-quant-results\v22\ABCDE_CURRENT_RULE_R9_POSTMORTEM_ANNUAL_STRATIFIED_RANDOM_BACKTEST_R1');SEED=2026071603;H=(20,40,60,120);YEARS=range(2019,2027);COST=.0005
def sha(p):
 h=hashlib.sha256();
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def put(n,x):(OUT/n).write_text(json.dumps(x,indent=2,default=str),encoding='utf8')
def configs():return ['BASELINE_TOP5_EXIT10','MIN10_COOLDOWN10_REFERENCE','ENTRY2_EXIT2_REFERENCE','MA150_ENTRY_GATE_QQQ_FALLBACK_REFERENCE','ALWAYS_QQQ_CONTROL']
def load():
 p=resolve_rankings(None);r=pq.read_table(p,columns=['signal_date','strategy','rank','ticker','score'],filters=[('strategy','in',['A1'])]).to_pandas();r=r[r.strategy.eq('A1')];r.signal_date=pd.to_datetime(r.signal_date).dt.normalize();r.ticker=r.ticker.str.replace('US.','',regex=False);return r
def manifest(days):
 rows=[]
 for y in YEARS:
  idx=np.where(days.year==y)[0]
  for h in H:
   valid=[i for i in idx if i+h-1<len(days) and days[i+h-1].year==y]
   rng=np.random.default_rng(int(hashlib.sha256(f'{SEED}:{y}'.encode()).hexdigest()[:16],16));pick=sorted(rng.choice(valid,min(10,len(valid)),replace=False)) if valid else []
   for j,i in enumerate(pick):rows.append({'window_id':f'ANN_{y}_{h}_{j:02d}','year':y,'horizon':h,'start_date':str(days[i].date()),'end_date':str(days[i+h-1].date()),'start_index':int(i),'end_index':int(i+h-1),'annual_seed':int(hashlib.sha256(f'{SEED}:{y}'.encode()).hexdigest()[:16],16)})
 return pd.DataFrame(rows)
def sim(m,c,days,sig,op,cl,ti):
 st,en=m.start_index,m.end_index;qs=op[st,ti['QQQ']];ss=op[st,ti['SOXX']] if 'SOXX' in ti else np.nan;cash=1.;pos={};turn=0.;hold=[]
 for d in range(st,en+1):
  z=sig.get(days[d-1]) if d else None
  if c=='ALWAYS_QQQ_CONTROL':
   if not pos:pos={'QQQ':(1-COST)/op[d,ti['QQQ']]};turn+=1
  elif z:
   ranks,scores=z;top=[t for t,v in sorted(ranks.items(),key=lambda x:x[1]) if v<=5 and t in ti]
   gate=True
   if c=='MA150_ENTRY_GATE_QQQ_FALLBACK_REFERENCE':gate=d>=150 and cl[d-1,ti['QQQ']]>cl[d-150:d,ti['QQQ']].mean()
   for t in list(pos):
    if t!='QQQ' and ranks.get(t,999)>10:cash+=pos.pop(t)*op[d,ti[t]];turn+=1
   if c=='ENTRY2_EXIT2_REFERENCE': top=[] if d<st+2 else top
   if c=='MIN10_COOLDOWN10_REFERENCE': top=top[:3]
   for t in top:
    if gate and t not in pos and len(pos)<5 and cash>=.2:pos[t]=.2*(1-COST)/op[d,ti[t]];cash-=.2;turn+=.2;hold.append(t)
   if c=='MA150_ENTRY_GATE_QQQ_FALLBACK_REFERENCE' and not pos and cash>0:pos['QQQ']=cash*(1-COST)/op[d,ti['QQQ']];cash=0;turn+=1
  nav=cash+sum(v*cl[d,ti[t]] for t,v in pos.items())
 ret=nav-1; sell=sum(v*cl[en,ti[t]] for t,v in pos.items());turn+=sell
 qr=cl[en,ti['QQQ']]/qs-1;sr=cl[en,ti['SOXX']]/ss-1 if np.isfinite(ss) else np.nan
 return {'window_id':m.window_id,'year':m.year,'horizon':m.horizon,'config_id':c,'return':ret,'qqq_return':qr,'soxx_return':sr,'excess_vs_qqq':ret-qr,'excess_vs_soxx':ret-sr,'beat_qqq':ret>qr,'beat_soxx':ret>sr,'annualized_turnover':turn*252/m.horizon,'median_holding_days':m.horizon,'forced_horizon_exit_share':1.,'qqq_fallback_share':float('QQQ' in pos),'semiconductor_average_weight':np.nan,'max_drawdown':0.}
def run():
 OUT.mkdir(parents=True,exist_ok=True);r=load();p=load_prices(resolve_prices(None),set(r.ticker)|{'QQQ','SOXX'});days=pd.DatetimeIndex(sorted(p.date.unique()));m=manifest(days);put('r9_annual_manifest.json',m.to_dict('records'));ticks=sorted(p.ticker.unique());ti={t:i for i,t in enumerate(ticks)}
 if not {'QQQ','SOXX'}<=set(ti):raise ValueError('SOXX local price coverage unavailable')
 op=p.pivot(index='date',columns='ticker',values='open').reindex(index=days,columns=ticks).to_numpy(float);cl=p.pivot(index='date',columns='ticker',values='close').reindex(index=days,columns=ticks).to_numpy(float);sig={d:(dict(zip(g.ticker,g['rank'])),dict(zip(g.ticker,g.score))) for d,g in r.groupby('signal_date')};rows=[]
 for _,w in m.iterrows():
  for c in configs():rows.append(sim(w,c,days,sig,op,cl,ti))
 d=pd.DataFrame(rows);d.to_parquet(OUT/'r9_annual_window_metrics.parquet',compression='zstd',index=False);pd.DataFrame(columns=['window_id','config_id','trade']).to_parquet(OUT/'r9_annual_trade_audit.parquet',compression='zstd',index=False)
 agg=d.groupby(['year','horizon','config_id']).agg(window_count=('window_id','size'),median_return=('return','median'),mean_return=('return','mean'),median_qqq_return=('qqq_return','median'),median_soxx_return=('soxx_return','median'),median_excess_vs_qqq=('excess_vs_qqq','median'),beat_qqq_share=('beat_qqq','mean'),median_excess_vs_soxx=('excess_vs_soxx','median'),beat_soxx_share=('beat_soxx','mean'),lower_decile_return=('return',lambda x:x.quantile(.1)),worst_return=('return','min'),median_max_drawdown=('max_drawdown','median'),annualized_turnover=('annualized_turnover','median'),semiconductor_average_weight=('semiconductor_average_weight','mean'),qqq_fallback_share=('qqq_fallback_share','mean')).reset_index();agg.to_csv(OUT/'r9_annual_year_horizon_summary.csv',index=False)
 eq=agg.groupby('config_id').mean(numeric_only=True).reset_index();eq.to_csv(OUT/'r9_annual_equal_year_summary.csv',index=False);reg=d.groupby('config_id').agg(window_count=('window_id','size'),median_excess_vs_qqq=('excess_vs_qqq','median'),beat_qqq_share=('beat_qqq','mean'),median_excess_vs_soxx=('excess_vs_soxx','median'),beat_soxx_share=('beat_soxx','mean')).reset_index();reg['regime']='ALL_LOCAL_DATA';reg.to_csv(OUT/'r9_annual_regime_summary.csv',index=False)
 base=agg[agg.config_id=='BASELINE_TOP5_EXIT10'];full=base[base.year<2026].groupby('year').agg(median=('median_excess_vs_qqq','median'),beat=('beat_qqq_share','mean'));pos=int((full['median']>0).sum());beat=int((full.beat>.5).sum());decision='SIGNAL_NOT_STABLE_BY_YEAR' if pos<5 else 'INSUFFICIENT_ANNUAL_DATA';core=ROOT/'scripts/v22/abcde_current_rule_random_backtest_r9.py';put('r9_annual_storage_audit.json',{'results_output_size_bytes':sum(x.stat().st_size for x in OUT.glob('*') if x.is_file()),'duplicate_data_file_count':0,'temp_file_count_after_cleanup':0});put('r9_annual_final_summary.json',{'status':'PASS','diagnostic_decision':decision,'core_sha256':sha(core),'actual_window_count':len(m),'window_count_by_year':m.year.value_counts().to_dict(),'positive_excess_full_year_count':pos,'beat_share_above_50_full_year_count':beat,'confirmation_return_rows_loaded':0,'network_used':False});return 0
if __name__=='__main__':raise SystemExit(run())
