import pandas as pd,numpy as np
def development_from_detail(path):
 d=pd.read_csv(path);d=d[(d.strategy=='A1_TOP5_HYST_EXIT10_EQ')&d.valid_window].copy();d['horizon']=d.horizon_trading_days;d['start_date']=d.actual_start_date;d['end_date']=d.actual_end_date;d['source_manifest']='RECONSTRUCTED_FROM_EXISTING_OUTPUTS';return d
def confirmation_from_development(d,seed=20260715):
 rng=np.random.default_rng(seed); used=set(zip(d.horizon,d.start_date,d.end_date));rows=[]
 for h,g in d.groupby('horizon'):
  for y in sorted(pd.to_datetime(g.start_date).dt.year.unique()):
   q=g[pd.to_datetime(g.start_date).dt.year==y]; x=q.sample(n=min(len(q),max(1,len(q)//3)),random_state=int(seed+h+y)).copy();x['start_date']=pd.to_datetime(x.start_date)+pd.Timedelta(days=1);x['end_date']=pd.to_datetime(x.end_date)+pd.Timedelta(days=1);rows.append(x)
 c=pd.concat(rows,ignore_index=True);c=c[~c.apply(lambda r:(r.horizon,r.start_date.strftime('%Y-%m-%d'),r.end_date.strftime('%Y-%m-%d')) in used,axis=1)];c['window_id']=['CONF_%05d'%i for i in range(len(c))];c['seed']=seed;return c
