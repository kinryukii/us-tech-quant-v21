"""One common input representation for all independent frozen accounts."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from shared import *
from fast_account import MarketArrays,OperationalEvidence

# NYSE published calendar; these are common signal clocks, not strategy choices.
EARLY_CLOSE_DATES={pd.Timestamp(d) for d in ['2025-07-03','2025-11-28','2025-12-24',
    '2026-11-27','2026-12-24']}
KNOWN_INPUT_CONFLICTS={(pd.Timestamp('2026-02-26'),'GLW')}
KNOWN_PRICE_CONFLICTS={(pd.Timestamp(d),'GLW') for d in ['2026-02-26','2026-02-27']}

def signal_asof(date):
    date=pd.Timestamp(date)
    return (date+pd.Timedelta(hours=13 if date in EARLY_CLOSE_DATES else 16)).tz_localize('America/New_York').tz_convert('UTC')

def usable_context_mask(panel):
    finite=np.isfinite(panel[FEATURES].to_numpy(float)).all(axis=1)
    conflict=np.asarray([(pd.Timestamp(d),str(t)) in KNOWN_INPUT_CONFLICTS
        for d,t in zip(panel.signal_date,panel.ticker)],bool)
    return finite&~conflict

@dataclass
class PreparedMarket:
    market:MarketArrays
    features:np.ndarray
    panel:pd.DataFrame
    date_index:dict
    ticker_index:dict

def prepare_market(year):
    if year not in [2025,2026]:raise ValueError('FIXED_EVALUATION_YEARS')
    if year==2026 and not (ROOT/'FROZEN_BEFORE_2026.json').exists():raise RuntimeError('FREEZE_ENTIRE_BATCH_BEFORE_2026')
    inputs=read_json(ROOT/'input_paths.json')
    if year==2025:
        panel=pd.read_parquet(inputs['pre_panel']);panel=panel.loc[panel.signal_date.dt.year.eq(year)&panel.signal_date.le('2025-12-29')].copy()
        prices=pd.read_parquet(inputs['pre_prices']);prices=prices.loc[prices.trade_date.dt.year.eq(year)].copy()
        calendar=pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq('QQQ'),'trade_date'].unique()))
        operations={}
    else:
        panel=pd.read_parquet(inputs['test_panel']);panel=panel.loc[panel.signal_date.le('2026-09-22')].copy()
        prices=pd.read_parquet(inputs['test_prices'])
        cal=pd.read_parquet(inputs['calendar']);calendar=pd.DatetimeIndex(cal.loc[cal.is_test,'trade_date'])
        evidence=pd.read_csv(inputs['ops'],parse_dates=['effective_date','known_at'])
        operations={}
        for date in calendar:
            asof=signal_asof(date)
            rows=evidence.loc[evidence.effective_date.le(date)&evidence.known_at.le(asof)]
            operations[date]={str(r.ticker):OperationalEvidence(str(r.reason),r.known_at,str(r.source_id)) for r in rows.itertuples()}
    assert panel.signal_date.dt.year.eq(year).all() and not panel.duplicated(['signal_date','ticker']).any()
    ticker_set=set(panel.ticker.astype(str))|{t for actions in operations.values() for t in actions}
    tickers=np.asarray(sorted(ticker_set),str);di={d:i for i,d in enumerate(calendar)};ti={t:i for i,t in enumerate(tickers)}
    shape=(len(calendar),len(tickers));op=np.full(shape,np.nan);close=op.copy();quality=np.zeros(shape,bool);rows=np.zeros(shape,bool)
    selected=prices.loc[prices.ticker.isin(ticker_set)&prices.trade_date.isin(calendar)]
    if selected.duplicated(['trade_date','ticker']).any():raise RuntimeError('DUPLICATE_PRICE_ROWS')
    ri=selected.trade_date.map(di).to_numpy(int);ci=selected.ticker.map(ti).to_numpy(int)
    op[ri,ci]=selected.open.to_numpy(float);close[ri,ci]=selected.close.to_numpy(float);rows[ri,ci]=True
    if 'price_quality_warning' in selected:quality[ri,ci]=selected.price_quality_warning.fillna(True).to_numpy(bool)
    for date,ticker in KNOWN_PRICE_CONFLICTS:
        if date in di and ticker in ti:quality[di[date],ti[ticker]]=True
    features=np.full((*shape,len(FEATURES)),np.nan);present=np.zeros(shape,bool);eligible=np.zeros(shape,bool);adv=np.full(shape,np.nan)
    keep=panel.signal_date.isin(calendar);panel=panel.loc[keep].sort_values(['signal_date','ticker']).reset_index(drop=True)
    ri=panel.signal_date.map(di).to_numpy(int);ci=panel.ticker.map(ti).to_numpy(int)
    x=panel[FEATURES].to_numpy(float);finite=usable_context_mask(panel)
    panel['runtime_input_usable']=finite
    features[ri,ci]=np.where(finite[:,None],x,np.nan);present[ri,ci]=finite;eligible[ri,ci]=panel.new_buy_eligible.to_numpy(bool)&finite
    adv[ri,ci]=panel.avg_dollar_volume_20d.to_numpy(float)
    signal_dates=set(panel.signal_date)
    signal_mask=np.array([d in signal_dates for d in calendar],bool)
    clocks=[signal_asof(d) for d in calendar]
    market=MarketArrays(calendar,tickers,op,close,quality=quality,adv=adv,input_present=present,
        new_buy_eligible=eligible,signal_mask=signal_mask,signal_asof=clocks,operational_exits=operations,row_present=rows)
    return PreparedMarket(market,features,panel,di,ti)
