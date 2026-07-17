from pathlib import Path
import pandas as pd, numpy as np, pyarrow.parquet as pq
def load_inputs(data=Path(r'D:\us-tech-quant-data')):
 r=pq.read_table(data/'derived_cache/abcde_current_rule_proxy_rankings_r8/historical_proxy_rankings.parquet').to_pandas();r=r[r.strategy=='A1'];r.signal_date=pd.to_datetime(r.signal_date);raw=pd.concat([pd.read_parquet(f,columns=['ticker','trade_date','open','close']) for f in (data/'moomoo/source/prices_raw').glob('year=*/prices.parquet')]);raw.ticker=raw.ticker.astype(str);raw.trade_date=pd.to_datetime(raw.trade_date);o=raw.pivot(index='trade_date',columns='ticker',values='open').sort_index();c=raw.pivot(index='trade_date',columns='ticker',values='close').reindex(o.index);return r,o,c
def sim(r,o,c,a,b,cost=.0005):
 ds=sorted(r.signal_date.unique());ds=ds[a:b];cash=np.ones(5)*.2;hold=[None]*5;nav=[];tr=[]
 for sd in ds:
  ix=o.index.searchsorted(sd,side='right')
  if ix>=len(o.index):break
  d=o.index[ix];g=r[r.signal_date==sd].sort_values('rank');rank=dict(zip(g.ticker,g['rank']));top=list(g[g['rank']<=5].ticker)
  for j,t in enumerate(hold):
   if t and (t not in rank or rank[t]>10) and pd.notna(o.loc[d,t]):cash[j]+=cash[j]*(o.loc[d,t]/c.loc[o.index[ix-1],t]-1)*(1-cost);hold[j]=None;tr.append((d,'SELL',t))
  used={x for x in hold if x}
  for j,t in enumerate(hold):
   if t is None:
    x=next((x for x in top if x not in used and pd.notna(o.loc[d,x])),None)
    if x:cash[j]*=(c.loc[d,x]/o.loc[d,x])*(1-cost);hold[j]=x;used.add(x);tr.append((d,'BUY',x))
   elif pd.notna(c.loc[d,t]):cash[j]*=c.loc[d,t]/c.loc[o.index[ix-1],t]
  nav.append((d,cash.sum(),len(used)))
 n=pd.DataFrame(nav,columns=['date','nav','position_count']);n['ret']=n.nav.pct_change().fillna(n.nav-1);return n,pd.DataFrame(tr,columns=['date','side','ticker'])
def qqq(o,c,start,end,cost=.0005):
 x=o.index[(o.index>=start)&(o.index<=end)];v=c.loc[x,'QQQ']/o.loc[x[0],'QQQ']*(1-cost);d=pd.DataFrame({'date':x,'nav':v});d['ret']=d.nav.pct_change().fillna(d.nav-1);return d
