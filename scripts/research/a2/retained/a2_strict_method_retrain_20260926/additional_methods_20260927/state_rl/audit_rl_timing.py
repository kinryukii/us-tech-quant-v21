"""Preflight all RL signal/reward/accounting clocks before any successful RL fit."""
from pathlib import Path
import json
import pandas as pd

HERE=Path(__file__).resolve().parent
POOL=Path(r'D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\A\score_rank_ledger.parquet')
PRICE=Path(r'D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\pre2026_original_price_coordinate.parquet')
pool=pd.read_parquet(POOL,columns=['signal_date','ticker'])
qqq=pd.read_parquet(PRICE,columns=['ticker','trade_date'])
calendar=pd.DatetimeIndex(qqq.loc[qqq.ticker.eq('QQQ'),'trade_date'].unique()).sort_values()
rows=[]
for year in (2023,2024,2025):
    dates=pd.DatetimeIndex(pool.loc[pool.signal_date.dt.year.eq(year),'signal_date'].unique()).sort_values()
    last_signal=calendar[calendar.year==year][-3]
    dates=dates[dates<=last_signal]
    pos=calendar.get_indexer(dates)
    assert (pos>=0).all() and len(dates)>0
    execution=calendar[pos+1]; valuation=calendar[pos+2]
    assert (execution.year==year).all() and (valuation.year==year).all()
    assert (valuation<pd.Timestamp('2026-01-01')).all()
    rows.append({'episode_year':year,'role':'TRAIN' if year==2023 else ('VALIDATION_SELECT' if year==2024 else 'FINAL_UNTOUCHED_EVAL'),
                 'signal_first':str(dates.min().date()),'signal_last':str(dates.max().date()),'signal_days':len(dates),
                 'first_execution_open':str(execution.min().date()),'last_execution_open':str(execution.max().date()),
                 'first_subsequent_valuation_open':str(valuation.min().date()),'last_subsequent_valuation_open':str(valuation.max().date()),
                 'max_consumed_price_date':str(valuation.max().date()),'cross_year_steps':0})
report={'status':'PASS_PRETRAIN_TIMING_BOUND','cutoff_exclusive':'2026-01-01','original_price_coordinate_last_date':str(calendar.max().date()),
        'episode_boundaries':rows,'state_columns':'Original signal-date 32 stock features plus previous target membership; no target or outcome columns loaded',
        'reward_source':'Original reconstruct_path daily net returns, positions, transactions and costs',
        'model_selection':'2024 validation only; 2025 untouched final evaluation; 2026 absent',
        'full_pre2026_refit':'Three independent 2023/2024/2025 episodes reset cash and holdings at year boundaries; no episode crosses a year',
        'future_price_filtering':'None. Candidate action pool is original eligible score_rank_ledger; original accounting handles missing execution/valuation prices.'}
(HERE/'RL_TIME_LEAKAGE_PREFLIGHT.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
