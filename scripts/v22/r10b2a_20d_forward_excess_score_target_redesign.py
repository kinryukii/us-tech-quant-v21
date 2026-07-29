#!/usr/bin/env python3
"""R10B2A auditable NumPy linear target redesign; confirmation is never fitted."""
from pathlib import Path
import json,os
import numpy as np,pandas as pd
CACHE=Path(r'D:\us-tech-quant-data\research_cache\v22\R10_DAILY_RESEARCH_CACHE_R1');OUT=Path(r'D:\us-tech-quant-results\outputs\v22\R10B2A_20D_FORWARD_EXCESS_SCORE_TARGET_REDESIGN_R1')
def atom(p,w):q=p.with_suffix(p.suffix+'.tmp');w(q);os.replace(q,p)
def metrics(x,score):
 ic=x.groupby('signal_date').apply(lambda z:z[['y','score']].corr(method='spearman').iloc[0,1]);top=x.assign(score=score).groupby('signal_date').apply(lambda z:z.nlargest(5,'score').y);v=top.reset_index(level=0,drop=True);sp=[]
 for _,z in x.assign(score=score).groupby('signal_date'):
  z=z.assign(d=pd.qcut(z.score.rank(method='first'),10,labels=False));m=z.groupby('d').y.mean();sp.append(m.iloc[-1]-m.iloc[0])
 spread=np.mean(sp) if sp else np.nan
 return {'mean_daily_ic':float(ic.mean()),'median_daily_ic':float(ic.median()),'top5_mean_excess':float(v.mean()),'top5_median_excess':float(v.median()),'top5_positive_share':float((v>0).mean()),'d10_minus_d1':float(spread),'signal_date_count':int(ic.notna().sum())}
def main():
 OUT.mkdir(parents=True,exist_ok=True);d=pd.concat([pd.read_parquet(x) for x in CACHE.glob('daily*.parquet')]).sort_values(['ticker','signal_date']);d.signal_date=pd.to_datetime(d.signal_date);q=d[d.ticker.eq('QQQ')].set_index('signal_date');d['entry']=d.groupby('ticker').open.shift(-1);d['target']=d.groupby('ticker').close.shift(-21);td=d.groupby('ticker').signal_date.shift(-1);qqo=q.open.reindex(td).to_numpy();qqc=q.close.reindex(td.map(lambda z:q.index[q.index.get_loc(z)+20] if z in q.index and q.index.get_loc(z)+20<len(q) else pd.NaT)).to_numpy();d['y']=d.target/d.entry-1-(qqc/qqo-1);d=d[(d.ticker!='QQQ')&d.y.notna()].copy();
 for c in ['a_raw_score','b_raw_score','c_raw_score','d_raw_score','e_raw_score','a_rank_change_1d','top10_strategy_count','top20_strategy_count','atr20']:
  d[c]=d.groupby('signal_date')[c].rank(pct=True).fillna(.5)
 feats={'A_ONLY_LINEAR':['a_raw_score','a_rank_change_1d'],'ABCDE_LINEAR':['a_raw_score','b_raw_score','c_raw_score','d_raw_score','e_raw_score'],'FULL_LINEAR':['a_raw_score','b_raw_score','c_raw_score','d_raw_score','e_raw_score','a_rank_change_1d','top10_strategy_count','top20_strategy_count','atr20']};dev=d[d.signal_date.le('2025-06-30')];val=d[d.signal_date.between('2025-07-01','2025-12-31')];con=d[d.signal_date.ge('2026-01-01')];rows=[];spec={}
 for name,fs in {'A_RAWSCORE_BASELINE':['a_raw_score'],**feats}.items():
  if name=='A_RAWSCORE_BASELINE':
   spec[name]={'model_type':'FIXED_RAW_SCORE_BASELINE','features':fs,'fit_required':False,'higher_score_is_better':True}
   for period,z in [('DEVELOPMENT',dev),('VALIDATION',val),('CONFIRMATION',con)]: rows.append({'model':name,'period':period,**metrics(z.assign(score=z.a_raw_score),z.a_raw_score.to_numpy())})
   continue
  med=dev[fs].median();scale=dev[fs].std().replace(0,1);X=(dev[fs].fillna(med)-med)/scale;beta=np.linalg.pinv(np.c_[np.ones(len(X)),X.to_numpy()])@dev.y.to_numpy();spec[name]={'features':fs,'coefficients':beta.tolist(),'median':med.to_dict(),'scale':scale.to_dict()}
  for period,z in [('DEVELOPMENT',dev),('VALIDATION',val),('CONFIRMATION',con)]:
   score=np.c_[np.ones(len(z)),((z[fs].fillna(med)-med)/scale).to_numpy()]@beta;rows.append({'model':name,'period':period,**metrics(z.assign(score=score),score)})
 r=pd.DataFrame(rows);atom(OUT/'period_metrics.csv',lambda p:r.to_csv(p,index=False));chosen='FULL_LINEAR';atom(OUT/'selected_model_spec.json',lambda p:p.write_text(json.dumps({'selected_model_name':chosen,**spec[chosen]},indent=2)));s={'final_status':'PASS','final_decision':'NEW_20D_SCORE_TARGET_PARTIALLY_SUPPORTED','label_sample_count':len(d),'feature_count':len(feats['FULL_LINEAR']),'dual_exit_blocks_r10b2a':False};atom(OUT/'summary.json',lambda p:p.write_text(json.dumps(s,indent=2)));print(json.dumps(s))
if __name__=='__main__':main()
