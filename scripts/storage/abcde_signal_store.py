"""Canonical compact ABCDE rank history and per-ticker QFQ forward-return reader."""
from __future__ import annotations
from pathlib import Path
import pandas as pd
from storage_r2a import sha256
SIGNAL=Path(r'D:\us-tech-quant-backtests\_strategy_signal_history\ABCDE_R1\abcde_rank_history.parquet')
DATA=Path(r'D:\us-tech-quant-data\stocks')
def validate_rank_uniqueness(frame):
 if frame.duplicated(['research_date','strategy_id','ticker']).any(): raise ValueError('duplicate canonical ABCDE rank key')
 if not set(frame.strategy_id).issubset({'A1_CONTROL','B_STATIC_MOMENTUM','C_DYNAMIC_MOMENTUM','D_WEIGHT_OPTIMIZED_REFERENCE','E_R1_DEFENSIVE_REFERENCE'}): raise ValueError('unknown strategy version')
 return frame
def validate_compact_rank_schema(f):
 required={'research_date','strategy_id','ticker','rank','score','eligible'}
 missing=required-set(f.columns)
 if missing: raise ValueError(f'FAIL_ABCDE_COMPACT_INPUT_MISSING: schema {sorted(missing)}')
 return validate_rank_uniqueness(f)
def load_compact_rank_history(path=SIGNAL,start_date=None,end_date=None,strategy_id=None):
 f=pd.read_parquet(path); validate_compact_rank_schema(f)
 if start_date: f=f[f.research_date>=start_date]
 if end_date: f=f[f.research_date<=end_date]
 if strategy_id: f=f[f.strategy_id==strategy_id]
 return f
def load_historical_rankings(start_date=None,end_date=None,strategy_id=None):
 f=pd.read_parquet(SIGNAL)
 if start_date: f=f[f.research_date>=start_date]
 if end_date: f=f[f.research_date<=end_date]
 if strategy_id: f=f[f.strategy_id==strategy_id]
 return validate_rank_uniqueness(f).sort_values(['research_date','strategy_id','rank'])
def get_available_research_dates(): return sorted(load_historical_rankings().research_date.unique())
def forward_returns(tickers,dates,horizons=(1,3,5,10,20)):
 rows=[]
 for ticker in sorted(set(tickers)):
  p=DATA/ticker/'daily_qfq.parquet'
  if not p.exists(): continue
  f=pd.read_parquet(p).sort_values('date').reset_index(drop=True); f['date']=f.date.astype(str)
  idx={d:i for i,d in enumerate(f.date)}
  for d in dates:
   i=idx.get(str(d))
   if i is None: continue
   for h in horizons:
    j=i+h; value=None if j>=len(f) else float(f.close.iloc[j]/f.close.iloc[i]-1)
    rows.append({'research_date':str(d),'ticker':ticker,'horizon_days':h,'forward_return':value,'matured':value is not None,'price_source':str(p)})
 return pd.DataFrame(rows)
def load_ticker_qfq(ticker, stock_data_root=DATA):
 p=Path(stock_data_root)/ticker/'daily_qfq.parquet'
 if not p.exists(): raise FileNotFoundError(f'FAIL_ABCDE_COMPACT_INPUT_MISSING: {p}')
 f=pd.read_parquet(p).copy(); f['date']=f.date.astype(str)
 if f.date.duplicated().any(): raise ValueError(f'duplicate qfq date: {ticker}')
 return f.sort_values('date').reset_index(drop=True),p
def compute_forward_returns_from_qfq(ticker,research_dates,horizons=(1,3,5,10,20),stock_data_root=DATA):
 f,p=load_ticker_qfq(ticker,stock_data_root); idx={d:i for i,d in enumerate(f.date)}; rows=[]
 for d in research_dates:
  i=idx.get(str(d)); row={'ticker':ticker,'research_date':str(d),'price_date':str(d) if i is not None else None,'close':float(f.close.iloc[i]) if i is not None else float('nan'),'maturity_status':'OK' if i is not None else 'MISSING_RESEARCH_DATE_PRICE','source_file':str(p),'source_sha256':sha256(p)}
  for h in horizons: row[f'forward_{h}d']=float(f.close.iloc[i+h]/f.close.iloc[i]-1) if i is not None and i+h<len(f) else float('nan')
  rows.append(row)
 return pd.DataFrame(rows)
def join_rankings_with_forward_returns(rankings,horizons=(1,3,5,10,20),stock_data_root=DATA):
 parts=[compute_forward_returns_from_qfq(t, rankings[rankings.ticker==t].research_date.unique(),horizons,stock_data_root) for t in sorted(rankings.ticker.unique())]
 f=pd.concat(parts,ignore_index=True); return rankings.merge(f,on=['ticker','research_date'],how='left',validate='many_to_one')
