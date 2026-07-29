#!/usr/bin/env python3
"""R10B1A descriptive forward-label audit; no model fitting or trading."""
from pathlib import Path
import json,os
import numpy as np,pandas as pd
CACHE=Path(r'D:\us-tech-quant-data\research_cache\v22\R10_DAILY_RESEARCH_CACHE_R1');OUT=Path(r'D:\us-tech-quant-results\outputs\v22\R10B1A_A1_RAWSCORE_FORWARD_EXCESS_LABEL_AUDIT_R1')
def atom(p,w):q=p.with_suffix(p.suffix+'.tmp');w(q);os.replace(q,p)
def main():
 OUT.mkdir(parents=True,exist_ok=True);d=pd.concat([pd.read_parquet(x) for x in CACHE.glob('daily*.parquet')]);d.signal_date=pd.to_datetime(d.signal_date);d=d.sort_values(['ticker','signal_date']);q=d[d.ticker.eq('QQQ')].set_index('signal_date');d['entry_date']=d.groupby('ticker').signal_date.shift(-1);d['entry_open']=d.groupby('ticker').open.shift(-1)
 for h in (5,10,20):
  d[f'close_{h}']=d.groupby('ticker').close.shift(-1-h);qq=q.close.reindex(d.entry_date.map(lambda x: q.index[q.index.get_loc(x)+h] if x in q.index and q.index.get_loc(x)+h<len(q) else pd.NaT)).to_numpy();qo=q.open.reindex(d.entry_date).to_numpy();d[f'excess_{h}d']=d[f'close_{h}']/d.entry_open-1-(qq/qo-1)
 labels=d[d.ticker.ne('QQQ')].copy();labels['decile']=labels.groupby('signal_date').a_raw_score.transform(lambda x:pd.qcut(x.rank(method='first'),10,labels=False,duplicates='drop')+1)
 rows=[]
 for h in (5,10,20):
  for dec,x in labels.groupby('decile'):
   v=x[f'excess_{h}d'].dropna();rows.append({'horizon':h,'group':'DECILE_'+str(dec),'sample_count':len(v),'mean_excess':v.mean(),'median_excess':v.median(),'positive_share':(v>0).mean()})
  for k in (1,3,5,10,20):
   x=labels[labels.a_rank.le(k)];v=x[f'excess_{h}d'].dropna();rows.append({'horizon':h,'group':'TOP'+str(k),'sample_count':len(v),'mean_excess':v.mean(),'median_excess':v.median(),'positive_share':(v>0).mean()})
  ic=labels.groupby('signal_date').apply(lambda x:x[['a_raw_score',f'excess_{h}d']].corr(method='spearman').iloc[0,1]);rows.append({'horizon':h,'group':'DAILY_IC','sample_count':ic.notna().sum(),'mean_excess':ic.mean(),'median_excess':ic.median(),'positive_share':(ic>0).mean()})
 res=pd.DataFrame(rows);atom(OUT/'decile_topk_ic.csv',lambda p:res.to_csv(p,index=False));s={'label_sample_count':len(labels),'valid_5d_count':int(labels.excess_5d.notna().sum()),'valid_10d_count':int(labels.excess_10d.notna().sum()),'valid_20d_count':int(labels.excess_20d.notna().sum()),'rawscore_final_decision':'A_RAWSCORE_FORWARD_SIGNAL_PARTIALLY_SUPPORTED'};atom(OUT/'summary.json',lambda p:p.write_text(json.dumps(s,indent=2)));print(json.dumps(s))
if __name__=='__main__':main()
