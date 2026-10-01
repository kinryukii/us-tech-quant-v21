"""Audit pre2026 dynamic-pool and original price coverage without training."""
from pathlib import Path
import hashlib, json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
HERE.mkdir(parents=True,exist_ok=True)
ORIG=Path(r'D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1')
PRICE=Path(r'D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\pre2026_original_price_coordinate.parquet')
POOL=ORIG/'A'/'score_rank_ledger.parquet'
ENGINE=Path(r'D:\us-tech-quant\scripts\v22\fast_a2_r0f_corporate_action_and_nav_forensic_audit.py')
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()

p=pd.read_parquet(PRICE,columns=['ticker','trade_date','open'])
qqq=p.loc[p.ticker.eq('QQQ'),'trade_date'].sort_values().drop_duplicates().reset_index(drop=True)
next_map=dict(zip(qqq.iloc[:-1],qqq.iloc[1:]))
next2_map=dict(zip(qqq.iloc[:-2],qqq.iloc[2:]))
pool=pd.read_parquet(POOL,columns=['signal_date','ticker','lookback_121_eligible','all_features_available'])
assert pool.lookback_121_eligible.all() and pool.all_features_available.all()
assert not pool.duplicated(['signal_date','ticker']).any()
pool['exec_date']=pool.signal_date.map(next_map)
pool['val_date']=pool.signal_date.map(next2_map)
price_index=pd.MultiIndex.from_frame(p[['ticker','trade_date']])
exec_index=pd.MultiIndex.from_frame(pool[['ticker','exec_date']])
val_index=pd.MultiIndex.from_frame(pool[['ticker','val_date']])
pool['execution_open_present']=exec_index.isin(price_index)
pool['next_mark_open_present']=val_index.isin(price_index)
year=pool.signal_date.dt.year
summary=[]
for y,g in pool.groupby(year):
    summary.append({'year':int(y),'candidate_rows':len(g),'signal_days':g.signal_date.nunique(),
                    'signal_with_two_qqq_next_opens':int(g.loc[g.val_date.notna(),'signal_date'].nunique()),
                    'candidate_rows_with_two_next_qqq_opens':int(g.val_date.notna().sum()),
                    'execution_open_present':int(g.execution_open_present.sum()),'next_mark_open_present':int(g.next_mark_open_present.sum()),
                    'both_opens_present':int((g.execution_open_present&g.next_mark_open_present).sum())})
report={'input_paths':{str(x):sha(x) for x in [POOL,PRICE,ENGINE]},'calendar_first':str(qqq.min().date()),'calendar_last':str(qqq.max().date()),
        'qqq_sessions':len(qqq),'pool_candidate_rows':len(pool),'pool_signal_days':pool.signal_date.nunique(),
        'pool_all_original_121_and_32_feature_eligible':True,'yearly_price_coverage':summary,
        'price_gap_policy':'Original reconstruct_path skips missing buys, blocks missing sells, and marks held positions from prior close. No candidate may be removed from policy action pool based on future price presence.'}
(HERE/'ENVIRONMENT_AUDIT.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
