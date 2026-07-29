from __future__ import annotations

import argparse, json, math, os, re
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

VERSION = 'V22.063R1_FAST3_RTH_VWAP_MEAN_REVERSION_BASELINE_R1'
SIGNAL_SYMBOLS = ('QQQ','SOXX')
EXECUTION_SYMBOLS = ('TQQQ','SOXL','SQQQ','SOXS')
ALL_SYMBOLS = SIGNAL_SYMBOLS + EXECUTION_SYMBOLS
EXIT_VARIANTS = ('FIXED_15M','FIXED_30M','DUAL_VWAP_TOUCH_OR_30M')
RTH_START_ET, RTH_END_ET, RTH_LENGTH = 570, 959, 390
SIGNAL_START, SIGNAL_END = 60, 270
DEVIATION_THRESHOLD = 1.50
REALIZED_VOL_WINDOW, REALIZED_VOL_MIN_RETURNS = 30, 20
ENTRY_COST = EXIT_COST = 0.0005
FIXED_ACCOUNT_WEIGHT = 0.20
JUMP_THRESHOLD, FACTOR_TOLERANCE = 0.20, 0.03
ALLOWED_SPLIT_FACTORS = (2.,3.,4.,5.,6.,8.,10.,15.,20.,25.,30.,40.,50.,100.)
PERIODS = ('2018-2022_DEVELOPMENT','2023-2024_VALIDATION','2025-2026_YTD_CONFIRMATION')
MIN_FULL_HISTORY_TRADES, MIN_VALIDATION_TRADES, MIN_CONFIRMATION_TRADES = 100, 30, 30
MAX_TOP1_SHARE, MAX_TOP5_SHARE, MAX_YEAR_SHARE = 0.50, 0.80, 0.60

class StudyError(RuntimeError): pass

def study_period(year:int)->str:
    if 2018 <= year <= 2022: return PERIODS[0]
    if 2023 <= year <= 2024: return PERIODS[1]
    if 2025 <= year <= 2026: return PERIODS[2]
    return 'OUTSIDE_STUDY'

def validate_v22_061(s:Mapping[str,Any])->None:
    expected = {
        'final_status':'PASS','final_decision':'NO_ORB_BASELINE_CANDIDATE_QUALIFIED',
        'previous_pullback_reentry_architecture_used':False,'parameter_sweep_executed':False,
        'canonical_files_modified':False,'raw_files_modified':False,
        'new_market_data_cache_created':False,'broker_action_allowed':False,
        'paper_trading_allowed':False,'official_adoption_allowed':False,
    }
    bad=[f'{k}={s.get(k)!r}' for k,v in expected.items() if s.get(k)!=v]
    if bad: raise StudyError('V22.061 lineage invalid: '+'; '.join(bad))
    if s.get('supported_exit_variants_for_replication') != []: raise StudyError('V22.061 supported exit unexpectedly')
    if int(s.get('canonical_partition_count_indexed',-1)) != 582: raise StudyError('V22.061 partition count invalid')

def validate_v22_062pr(s:Mapping[str,Any])->None:
    expected = {
        'final_status':'PASS','v22_062pb_validated':True,'research_cutoff_date':'2026-07-24',
        'forward_holdout_only':True,'rule_change_requires_reset':True,
        'sole_exit_variant':'PREMARKET_0925','historical_pre_cutoff_outcomes_used_for_qualification':False,
        'parameter_sweep_executed':False,'threshold_optimization_executed':False,
        'strategy_rule_change_executed':False,'canonical_files_modified':False,
        'raw_files_modified':False,'new_market_data_cache_created':False,
        'broker_action_allowed':False,'paper_trading_allowed':False,'official_adoption_allowed':False,
    }
    bad=[f'{k}={s.get(k)!r}' for k,v in expected.items() if s.get(k)!=v]
    if bad: raise StudyError('V22.062PR lineage invalid: '+'; '.join(bad))
    allowed={
      'FORWARD_REPLICATION_IN_PROGRESS_INSUFFICIENT_INTERIM_SAMPLE',
      'FORWARD_REPLICATION_INTERIM_ONLY_NOT_FINAL_DECISION_READY',
      'PREMARKET_0925_FORWARD_REPLICATION_PASSED_RESEARCH_CANDIDATE_ONLY',
      'PREMARKET_0925_FORWARD_REPLICATION_FAILED'}
    if s.get('final_decision') not in allowed: raise StudyError('V22.062PR decision invalid')

def symbol_month_from_path(path:Path)->tuple[str,str,str]:
    symbol=year=month=None
    for part in path.parts:
        m=re.fullmatch(r'symbol=(.+)',part,re.I)
        if m: symbol=m.group(1).upper().replace('US.','')
        m=re.fullmatch(r'year=(\d{4})',part,re.I)
        if m: year=m.group(1)
        m=re.fullmatch(r'month=(\d{1,2})',part,re.I)
        if m: month=f'{int(m.group(1)):02d}'
    if not all((symbol,year,month)): raise StudyError(f'Cannot parse partition path: {path}')
    return symbol,year,month

def index_canonical(root:Path)->dict[tuple[str,str,str],Path]:
    out={}
    for p in sorted(root.rglob('*.parquet')):
        key=symbol_month_from_path(p)
        if key[0] not in ALL_SYMBOLS: continue
        if key in out: raise StudyError(f'Duplicate partition {key}')
        out[key]=p
    counts={s:sum(k[0]==s for k in out) for s in ALL_SYMBOLS}
    if len(out)!=582 or len(set(counts.values()))!=1 or any(v==0 for v in counts.values()):
        raise StudyError(f'Canonical partition inventory invalid: total={len(out)}, counts={counts}')
    return out

def find_column(df:pd.DataFrame, aliases:Iterable[str])->str:
    mapping={str(c).strip().lower():str(c) for c in df.columns}
    for a in aliases:
        if a.lower() in mapping: return mapping[a.lower()]
    raise StudyError(f'Missing column from aliases {tuple(aliases)}')

def load_symbol_rth(symbol:str, canonical:Mapping[tuple[str,str,str],Path])->tuple[pd.DataFrame,list[str]]:
    frames=[]; paths=[]
    for (current,_,_),p in sorted(canonical.items()):
        if current!=symbol: continue
        raw=pd.read_parquet(p); paths.append(str(p))
        if raw.empty: continue
        ts=pd.to_datetime(raw[find_column(raw,('timestamp_utc',))],errors='raise',utc=True)
        et=ts.dt.tz_convert('America/New_York'); minute=et.dt.hour*60+et.dt.minute
        mask=(minute>=RTH_START_ET)&(minute<=RTH_END_ET)
        frames.append(pd.DataFrame({
            'timestamp_utc':ts.loc[mask],
            'trade_date':et.loc[mask].dt.strftime('%Y-%m-%d'),
            'session_minute':(minute.loc[mask]-RTH_START_ET).astype(int),
            'open':pd.to_numeric(raw.loc[mask,find_column(raw,('open',))],errors='coerce'),
            'high':pd.to_numeric(raw.loc[mask,find_column(raw,('high',))],errors='coerce'),
            'low':pd.to_numeric(raw.loc[mask,find_column(raw,('low',))],errors='coerce'),
            'close':pd.to_numeric(raw.loc[mask,find_column(raw,('close',))],errors='coerce'),
            'volume':pd.to_numeric(raw.loc[mask,find_column(raw,('volume',))],errors='coerce').fillna(0.0),
        }).dropna(subset=['timestamp_utc','open','high','low','close']))
    if not frames: return pd.DataFrame(),paths
    df=(pd.concat(frames,ignore_index=True).sort_values('timestamp_utc',kind='mergesort')
        .drop_duplicates('timestamp_utc',keep='last').reset_index(drop=True))
    if df.duplicated(['trade_date','session_minute']).any(): raise StudyError(f'Duplicate RTH minute for {symbol}')
    if ((df.low>df.high)|(df.close<df.low)|(df.close>df.high)).any(): raise StudyError(f'Invalid OHLC for {symbol}')
    return df,paths

def candidate_factors()->np.ndarray:
    vals=set(ALLOWED_SPLIT_FACTORS); vals.update(1/x for x in ALLOWED_SPLIT_FACTORS)
    return np.array(sorted(vals),dtype=float)

def snap_split_factor(raw_ratio:float)->tuple[float,float]|None:
    if not np.isfinite(raw_ratio) or raw_ratio<=0: return None
    factors=candidate_factors(); errors=np.abs(factors/raw_ratio-1.0); i=int(np.argmin(errors))
    return (float(factors[i]),float(errors[i])) if errors[i]<=FACTOR_TOLERANCE else None

def normalize_scale_series(df:pd.DataFrame)->tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame]:
    if df.empty: return df.copy(),pd.DataFrame(),pd.DataFrame()
    out=df.sort_values('timestamp_utc',kind='mergesort').reset_index(drop=True).copy()
    multiplier=1.0; multipliers=[]; recognized=[]; unresolved=[]; prev_close=None; prev_ts=None
    for _,r in out.iterrows():
        ts=pd.Timestamp(r.timestamp_utc); current=float(r.open)
        if prev_close is not None and prev_close>0 and current>0:
            change=current/prev_close-1.0
            if abs(change)>=JUMP_THRESHOLD:
                ratio=prev_close/current; snapped=snap_split_factor(ratio)
                rec={'timestamp_utc':ts,'previous_timestamp_utc':prev_ts,'raw_change':change,'raw_ratio':ratio}
                if snapped is None: unresolved.append(rec)
                else:
                    factor,error=snapped; multiplier*=factor
                    recognized.append({**rec,'recognized_factor':factor,'relative_error':error})
        multipliers.append(multiplier); prev_close=float(r.close); prev_ts=ts
    out['scale_multiplier']=multipliers
    for c in ('open','high','low','close'): out[f'normalized_{c}']=out[c]*out.scale_multiplier
    return out,pd.DataFrame(recognized),pd.DataFrame(unresolved)

def get_day(df:pd.DataFrame, date:str)->pd.DataFrame:
    return df.loc[df.trade_date==date].sort_values('session_minute',kind='mergesort').reset_index(drop=True)

def session_grid(day:pd.DataFrame)->pd.DataFrame:
    grid=pd.DataFrame(index=pd.RangeIndex(RTH_LENGTH)); grid.index.name='session_minute'
    cols=['timestamp_utc','normalized_open','normalized_high','normalized_low','normalized_close','volume']
    if day.empty:
        for c in cols: grid[c]=np.nan
        grid['observed']=False; grid['session_complete']=False
        return grid
    indexed=(day.sort_values('session_minute').drop_duplicates('session_minute',keep='last').set_index('session_minute'))
    grid=grid.join(indexed[cols],how='left')
    grid['observed']=grid.normalized_close.notna(); grid['session_complete']=bool(grid.observed.sum()==RTH_LENGTH)
    grid['positive_volume']=grid.volume.fillna(0)>0
    typical=(grid.normalized_high+grid.normalized_low+grid.normalized_close)/3
    vol=grid.volume.fillna(0).clip(lower=0); cumvol=vol.cumsum(); cumval=(typical.fillna(0)*vol).cumsum()
    grid['vwap']=cumval.divide(cumvol.where(cumvol>0)).fillna(grid.normalized_close.expanding().mean())
    grid['ret_1m']=grid.normalized_close.pct_change(fill_method=None)
    grid['ret_5m']=grid.normalized_close/grid.normalized_close.shift(5)-1
    grid['realized_vol_30m']=grid.ret_1m.rolling(REALIZED_VOL_WINDOW,min_periods=REALIZED_VOL_MIN_RETURNS).std(ddof=1)*math.sqrt(REALIZED_VOL_WINDOW)
    grid['vwap_deviation']=grid.normalized_close/grid.vwap-1
    grid['normalized_vwap_deviation']=grid.vwap_deviation/grid.realized_vol_30m.replace(0,np.nan)
    grid['prior_high']=grid.normalized_high.shift(1); grid['prior_low']=grid.normalized_low.shift(1)
    grid['tradability_proxy_pass']=grid.observed&grid.positive_volume&grid.normalized_close.shift(5).notna()&grid.normalized_vwap_deviation.notna()
    return grid

def event_in_window(events:pd.DataFrame,start:pd.Timestamp,end:pd.Timestamp)->bool:
    if events.empty: return False
    ts=pd.to_datetime(events.timestamp_utc,utc=True)
    return bool(((ts>=start)&(ts<=end)).any())

def build_candidate(date:str, q:pd.DataFrame, s:pd.DataFrame, recognized:Mapping[str,pd.DataFrame], unresolved:Mapping[str,pd.DataFrame])->tuple[dict[str,Any]|None,list[str]]:
    reasons=[]
    if not bool(q.session_complete.iloc[0]): reasons.append('QQQ_INCOMPLETE_RTH')
    if not bool(s.session_complete.iloc[0]): reasons.append('SOXX_INCOMPLETE_RTH')
    if reasons: return None,reasons
    start=pd.Timestamp(f'{date} 09:30',tz='America/New_York').tz_convert('UTC')
    end=pd.Timestamp(f'{date} 14:00',tz='America/New_York').tz_convert('UTC')
    for sym in SIGNAL_SYMBOLS:
        if event_in_window(recognized[sym],start,end): reasons.append(f'{sym}_RECOGNIZED_SCALE_EVENT_DURING_SIGNAL')
        if event_in_window(unresolved[sym],start,end): reasons.append(f'{sym}_UNRESOLVED_SCALE_EVENT_DURING_SIGNAL')
    if reasons: return None,reasons
    sl=pd.RangeIndex(SIGNAL_START,SIGNAL_END+1); qx=q.loc[sl]; sx=s.loc[sl]
    ql=(qx.tradability_proxy_pass&(qx.normalized_vwap_deviation<=-DEVIATION_THRESHOLD)&(qx.ret_5m>0)&(qx.normalized_close>qx.prior_high)).fillna(False)
    slong=(sx.tradability_proxy_pass&(sx.normalized_vwap_deviation<=-DEVIATION_THRESHOLD)&(sx.ret_5m>0)&(sx.normalized_close>sx.prior_high)).fillna(False)
    qs=(qx.tradability_proxy_pass&(qx.normalized_vwap_deviation>=DEVIATION_THRESHOLD)&(qx.ret_5m<0)&(qx.normalized_close<qx.prior_low)).fillna(False)
    sshort=(sx.tradability_proxy_pass&(sx.normalized_vwap_deviation>=DEVIATION_THRESHOLD)&(sx.ret_5m<0)&(sx.normalized_close<sx.prior_low)).fillna(False)
    long_state=ql&slong; short_state=qs&sshort
    triggers=pd.DataFrame({'LONG':long_state&~long_state.shift(1,fill_value=False),'SHORT':short_state&~short_state.shift(1,fill_value=False)},index=sl)
    loc=np.argwhere(triggers.to_numpy(dtype=bool))
    if len(loc)==0: return None,[]
    ri,di=loc[0]; minute=int(triggers.index[int(ri)]); direction=str(triggers.columns[int(di)])
    qr=q.loc[minute]; sr=s.loc[minute]; qdev=float(qr.normalized_vwap_deviation); sdev=float(sr.normalized_vwap_deviation)
    execution=('SOXL' if sdev<qdev else 'TQQQ') if direction=='LONG' else ('SOXS' if sdev>qdev else 'SQQQ')
    return {
      'trade_date':date,'calendar_year':int(date[:4]),'study_period':study_period(int(date[:4])),
      'direction':direction,'execution_symbol':execution,'signal_session_minute':minute,
      'signal_timestamp_utc':qr.timestamp_utc,'qqq_normalized_vwap_deviation':qdev,
      'soxx_normalized_vwap_deviation':sdev,'qqq_vwap_deviation':float(qr.vwap_deviation),
      'soxx_vwap_deviation':float(sr.vwap_deviation),'qqq_ret_5m':float(qr.ret_5m),
      'soxx_ret_5m':float(sr.ret_5m),'relative_overextension':sdev-qdev},[]

def exit_minute(variant:str, entry:int, direction:str, q:pd.DataFrame, s:pd.DataFrame)->int:
    if variant=='FIXED_15M': return entry+15
    if variant=='FIXED_30M': return entry+30
    if variant!='DUAL_VWAP_TOUCH_OR_30M': raise StudyError(f'Unknown exit {variant}')
    for m in range(entry,entry+31):
        qr=q.loc[m]; sr=s.loc[m]
        if pd.isna(qr.normalized_close) or pd.isna(sr.normalized_close): continue
        touched=(qr.normalized_close>=qr.vwap and sr.normalized_close>=sr.vwap) if direction=='LONG' else (qr.normalized_close<=qr.vwap and sr.normalized_close<=sr.vwap)
        if touched: return m
    return entry+30

def net_return(entry:float,exit_:float)->float:
    return exit_*(1-EXIT_COST)/(entry*(1+ENTRY_COST))-1

def return_from_grid(grid:pd.DataFrame,entry:int,exit_:int)->tuple[float,dict[str,Any]]|None:
    if entry>=RTH_LENGTH or exit_>=RTH_LENGTH or exit_<=entry: return None
    er=grid.loc[entry]; xr=grid.loc[exit_]
    if pd.isna(er.normalized_open) or pd.isna(xr.normalized_close) or pd.isna(er.timestamp_utc) or pd.isna(xr.timestamp_utc): return None
    value=net_return(float(er.normalized_open),float(xr.normalized_close))
    return value,{'entry_timestamp_utc':er.timestamp_utc,'exit_timestamp_utc':xr.timestamp_utc,'entry_price_normalized':float(er.normalized_open),'exit_price_normalized':float(xr.normalized_close),'holding_minutes':exit_-entry}

def simulate(candidate:Mapping[str,Any],grids:Mapping[str,pd.DataFrame],recognized:Mapping[str,pd.DataFrame],unresolved:Mapping[str,pd.DataFrame])->tuple[list[dict[str,Any]],list[str]]:
    entry=int(candidate['signal_session_minute'])+1; direction=str(candidate['direction']); selected=str(candidate['execution_symbol'])
    pair=('TQQQ','SOXL') if direction=='LONG' else ('SQQQ','SOXS')
    rows=[]; reasons=[]
    for variant in EXIT_VARIANTS:
        xm=exit_minute(variant,entry,direction,grids['QQQ'],grids['SOXX'])
        ets=grids[selected].loc[entry,'timestamp_utc']; xts=grids[selected].loc[xm,'timestamp_utc']
        if pd.isna(ets) or pd.isna(xts): reasons.append(f'{variant}_EXACT_EXECUTION_BAR_MISSING'); continue
        local_reasons=[]
        for sym in ALL_SYMBOLS:
            if event_in_window(recognized[sym],pd.Timestamp(ets),pd.Timestamp(xts)): local_reasons.append(f'{variant}_{sym}_RECOGNIZED_SCALE_EVENT')
            if event_in_window(unresolved[sym],pd.Timestamp(ets),pd.Timestamp(xts)): local_reasons.append(f'{variant}_{sym}_UNRESOLVED_SCALE_EVENT')
        if local_reasons: reasons.extend(local_reasons); continue
        chosen=return_from_grid(grids[selected],entry,xm)
        if chosen is None: reasons.append(f'{variant}_RETURN_NOT_RECONSTRUCTABLE'); continue
        value,details=chosen; pair_values=[]
        for sym in pair:
            r=return_from_grid(grids[sym],entry,xm)
            if r is not None: pair_values.append(float(r[0]))
        pair_mean=float(np.mean(pair_values)) if len(pair_values)==2 else math.nan
        rows.append({**dict(candidate),'exit_variant':variant,'entry_session_minute':entry,'exit_session_minute':xm,**details,
                     'instrument_net_return':value,'position_weight':FIXED_ACCOUNT_WEIGHT,'account_trade_return':value*FIXED_ACCOUNT_WEIGHT,
                     'direction_pair_baseline_count':len(pair_values),'direction_pair_mean_return':pair_mean,
                     'selection_excess_return':value-pair_mean if np.isfinite(pair_mean) else math.nan})
    return rows,sorted(set(reasons))

def profit_factor(v:pd.Series)->float:
    x=pd.to_numeric(v,errors='coerce').dropna(); gains=float(x[x>0].sum()); losses=float(-x[x<0].sum())
    return math.inf if losses==0 and gains>0 else (math.nan if losses==0 else gains/losses)

def positive_profit_share(v:pd.Series,n:int)->float:
    x=pd.to_numeric(v,errors='coerce').dropna(); x=x[x>0].sort_values(ascending=False); total=float(x.sum())
    return math.nan if total<=0 else float(x.head(n).sum()/total)

def cumulative_return(v:pd.Series)->float:
    x=pd.to_numeric(v,errors='coerce').fillna(0); return math.nan if x.empty else float(np.prod(1+x.to_numpy(dtype=float))-1)

def maximum_drawdown(v:pd.Series)->float:
    x=pd.to_numeric(v,errors='coerce').fillna(0)
    if x.empty: return math.nan
    nav=(1+x).cumprod(); return float((nav/nav.cummax()-1).min())

def daily_returns(trades:pd.DataFrame)->pd.DataFrame:
    rows=[]
    for (variant,period,date),g in trades.groupby(['exit_variant','study_period','trade_date'],sort=True):
        rows.append({'exit_variant':variant,'study_period':period,'trade_date':date,'calendar_year':int(str(date)[:4]),'daily_return':float(np.prod(1+g.account_trade_return.to_numpy(dtype=float))-1)})
    return pd.DataFrame(rows)

def summarize_periods(trades:pd.DataFrame,daily:pd.DataFrame)->pd.DataFrame:
    rows=[]
    for variant in EXIT_VARIANTS:
        for period in PERIODS:
            g=trades[(trades.exit_variant==variant)&(trades.study_period==period)]
            d=daily[(daily.exit_variant==variant)&(daily.study_period==period)]
            if g.empty: continue
            excess=g.selection_excess_return.dropna(); account=g.account_trade_return
            rows.append({'exit_variant':variant,'study_period':period,'trade_count':len(g),'long_trade_count':int((g.direction=='LONG').sum()),'short_trade_count':int((g.direction=='SHORT').sum()),
              'mean_instrument_return':float(g.instrument_net_return.mean()),'median_instrument_return':float(g.instrument_net_return.median()),'positive_rate':float((g.instrument_net_return>0).mean()),
              'profit_factor':profit_factor(account),'cumulative_return':cumulative_return(d.daily_return),'max_drawdown':maximum_drawdown(d.daily_return),
              'top1_positive_profit_share':positive_profit_share(account,1),'top5_positive_profit_share':positive_profit_share(account,5),
              'selection_excess_count':len(excess),'mean_selection_excess_return':float(excess.mean()) if len(excess) else math.nan,
              'mean_signal_session_minute':float(g.signal_session_minute.mean()),'mean_holding_minutes':float(g.holding_minutes.mean())})
    return pd.DataFrame(rows)

def summarize_years(trades:pd.DataFrame)->pd.DataFrame:
    return trades.groupby(['exit_variant','calendar_year'],as_index=False).agg(trade_count=('trade_date','size'),account_return_sum=('account_trade_return','sum'))

def qualification(period:pd.DataFrame,year:pd.DataFrame)->pd.DataFrame:
    rows=[]
    for variant in EXIT_VARIANTS:
        vr=period[period.exit_variant==variant]; full=int(vr.trade_count.sum())
        val=vr[vr.study_period==PERIODS[1]]; conf=vr[vr.study_period==PERIODS[2]]
        val=val.iloc[0] if len(val) else None; conf=conf.iloc[0] if len(conf) else None
        vc=int(val.trade_count) if val is not None else 0; cc=int(conf.trade_count) if conf is not None else 0
        sample=full>=MIN_FULL_HISTORY_TRADES and vc>=MIN_VALIDATION_TRADES and cc>=MIN_CONFIRMATION_TRADES
        mean=bool(sample and val.mean_instrument_return>0 and conf.mean_instrument_return>0)
        median=bool(sample and val.median_instrument_return>0 and conf.median_instrument_return>0)
        pf=bool(sample and val.profit_factor>1 and conf.profit_factor>1)
        cum=bool(sample and val.cumulative_return>0 and conf.cumulative_return>0)
        sel=bool(sample and val.mean_selection_excess_return>=0 and conf.mean_selection_excess_return>=0)
        conc=bool(sample and val.top1_positive_profit_share<=MAX_TOP1_SHARE and conf.top1_positive_profit_share<=MAX_TOP1_SHARE and val.top5_positive_profit_share<=MAX_TOP5_SHARE and conf.top5_positive_profit_share<=MAX_TOP5_SHARE)
        yr=year[year.exit_variant==variant]; pos=yr[yr.account_return_sum>0].account_return_sum
        share=float(pos.max()/pos.sum()) if len(pos) and float(pos.sum())>0 else math.nan; ypass=bool(np.isfinite(share) and share<=MAX_YEAR_SHARE)
        candidate=sample and mean and median and pf and cum and sel and conc and ypass
        rows.append({'exit_variant':variant,'full_history_trade_count':full,'validation_trade_count':vc,'confirmation_trade_count':cc,'sample_pass':sample,
          'mean_positive_both_periods':mean,'median_positive_both_periods':median,'profit_factor_pass_both_periods':pf,
          'cumulative_return_positive_both_periods':cum,'selection_excess_nonnegative_both_periods':sel,'trade_concentration_pass':conc,
          'single_positive_year_profit_share':share,'year_concentration_pass':ypass,'research_candidate_for_independent_replication':candidate})
    return pd.DataFrame(rows)

def choose_decision(q:pd.DataFrame)->tuple[str,list[str]]:
    supported=q.loc[q.research_candidate_for_independent_replication,'exit_variant'].astype(str).tolist()
    if supported: return 'RTH_VWAP_MEAN_REVERSION_CANDIDATE_REQUIRES_INDEPENDENT_REPLICATION',supported
    if not bool(q.sample_pass.any()): return 'RTH_VWAP_MEAN_REVERSION_INCONCLUSIVE_INSUFFICIENT_SAMPLE',[]
    return 'NO_RTH_VWAP_MEAN_REVERSION_CANDIDATE_QUALIFIED',[]

def json_default(v:Any)->Any:
    if isinstance(v,(np.integer,np.floating)):
        if isinstance(v,np.floating) and not np.isfinite(v): return None
        return v.item()
    if isinstance(v,(pd.Timestamp,Path)): return str(v)
    raise TypeError(type(v))

def atomic_json(path:Path,payload:Mapping[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    try:
        tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2,default=json_default)+'\n',encoding='utf-8'); os.replace(tmp,path)
    finally: tmp.unlink(missing_ok=True)

def run_study(v22_061_summary_path:Path,v22_062pr_summary_path:Path,canonical_root:Path,result_dir:Path)->dict[str,Any]:
    for p in (v22_061_summary_path,v22_062pr_summary_path,canonical_root):
        if not p.exists(): raise StudyError(f'Missing input: {p}')
    s061=json.loads(v22_061_summary_path.read_text(encoding='utf-8-sig')); spr=json.loads(v22_062pr_summary_path.read_text(encoding='utf-8-sig'))
    validate_v22_061(s061); validate_v22_062pr(spr)
    canonical=index_canonical(canonical_root); normalized={}; recognized={}; unresolved={}; paths=set()
    for sym in ALL_SYMBOLS:
        raw,used=load_symbol_rth(sym,canonical); paths.update(used); normalized[sym],recognized[sym],unresolved[sym]=normalize_scale_series(raw)
    dates=sorted(set.intersection(*[set(normalized[s].trade_date.unique()) for s in ALL_SYMBOLS]))
    session_rows=[]; candidate_rows=[]; trade_rows=[]
    for date in dates:
        grids={s:session_grid(get_day(normalized[s],date)) for s in ALL_SYMBOLS}
        complete=all(bool(grids[s].session_complete.iloc[0]) for s in ALL_SYMBOLS)
        if not complete:
            session_rows.append({'trade_date':date,'session_complete':False,'signal_generated':False,'trade_record_count':0,'session_quarantined':False,'quarantine_reasons':''}); continue
        candidate,reasons=build_candidate(date,grids['QQQ'],grids['SOXX'],recognized,unresolved); rows=[]
        if candidate is not None and not reasons:
            rows,extra=simulate(candidate,grids,recognized,unresolved); reasons.extend(extra)
        quarantined=bool(reasons)
        session_rows.append({'trade_date':date,'session_complete':True,'signal_generated':candidate is not None,'trade_record_count':len(rows) if not quarantined else 0,'session_quarantined':quarantined,'quarantine_reasons':'|'.join(sorted(set(reasons)))})
        if candidate is not None: candidate_rows.append(candidate)
        if not quarantined: trade_rows.extend(rows)
    sessions=pd.DataFrame(session_rows); candidates=pd.DataFrame(candidate_rows); trades=pd.DataFrame(trade_rows)
    if candidates.empty: raise StudyError('No candidate generated')
    if trades.empty: raise StudyError('No executable trades generated')
    daily=daily_returns(trades); period=summarize_periods(trades,daily); year=summarize_years(trades); q=qualification(period,year); decision,supported=choose_decision(q)
    result_dir.mkdir(parents=True,exist_ok=True)
    outputs={name:result_dir/f'v22_063r1_{name}.csv' for name in ('sessions','candidates','trades','daily','period','year','qualification')}
    sessions.to_csv(outputs['sessions'],index=False,encoding='utf-8-sig'); candidates.to_csv(outputs['candidates'],index=False,encoding='utf-8-sig'); trades.to_csv(outputs['trades'],index=False,encoding='utf-8-sig')
    daily.to_csv(outputs['daily'],index=False,encoding='utf-8-sig'); period.to_csv(outputs['period'],index=False,encoding='utf-8-sig'); year.to_csv(outputs['year'],index=False,encoding='utf-8-sig'); q.to_csv(outputs['qualification'],index=False,encoding='utf-8-sig')
    rec=pd.concat([df.assign(symbol=s) for s,df in recognized.items() if not df.empty],ignore_index=True) if any(not x.empty for x in recognized.values()) else pd.DataFrame()
    unr=pd.concat([df.assign(symbol=s) for s,df in unresolved.items() if not df.empty],ignore_index=True) if any(not x.empty for x in unresolved.values()) else pd.DataFrame()
    rec_path=result_dir/'v22_063r1_recognized_scale_events.csv'; unr_path=result_dir/'v22_063r1_unresolved_scale_events.csv'; rec.to_csv(rec_path,index=False,encoding='utf-8-sig'); unr.to_csv(unr_path,index=False,encoding='utf-8-sig')
    summary_path=result_dir/'v22_063r1_summary.json'
    summary={'version':VERSION,'final_status':'PASS','final_decision':decision,'v22_061_validated':True,'v22_062pr_validated':True,'premarket_forward_chain_modified':False,
      'session_name':'RTH','session_start_et':'09:30','session_end_et':'15:59','signal_start_et':'10:30','signal_end_et':'14:00','maximum_entries_per_session':1,
      'entry_timing':'EXACT_NEXT_MINUTE_OPEN','deviation_threshold':DEVIATION_THRESHOLD,'exit_variants':list(EXIT_VARIANTS),'entry_cost_bps':5.0,'exit_cost_bps':5.0,'fixed_account_weight':FIXED_ACCOUNT_WEIGHT,
      'corporate_action_safe_normalization_used':True,'signal_candidate_count':len(candidates),'long_candidate_count':int((candidates.direction=='LONG').sum()),'short_candidate_count':int((candidates.direction=='SHORT').sum()),
      'trade_record_count':len(trades),'trade_count_by_exit_variant':{v:int((trades.exit_variant==v).sum()) for v in EXIT_VARIANTS},'supported_exit_variants_for_replication':supported,
      'canonical_partition_count_indexed':len(canonical),'canonical_partition_count_read':len(paths),'parameter_sweep_executed':False,'deviation_threshold_sweep_executed':False,
      'signal_window_sweep_executed':False,'exit_threshold_optimization_executed':False,'rsi_entry_gate_used':False,'macd_entry_gate_used':False,'kdj_entry_gate_used':False,
      'vix_entry_gate_used':False,'vix_risk_scaling_used':False,'canonical_files_modified':False,'raw_files_modified':False,'new_market_data_cache_created':False,
      'history_download_executed':False,'open_d_called':False,'broker_action_allowed':False,'paper_trading_allowed':False,'official_adoption_allowed':False,
      'outputs':{**{k:str(v) for k,v in outputs.items()},'recognized_events':str(rec_path),'unresolved_events':str(unr_path),'summary':str(summary_path)}}
    atomic_json(summary_path,summary)
    print('=============================================='); print(' V22.063R1 RTH VWAP mean-reversion baseline'); print('==============================================')
    print('\n========== Validation / Confirmation performance ==========')
    print(period[period.study_period.isin(PERIODS[1:])].to_string(index=False))
    print('\n========== Qualification =========='); print(q.to_string(index=False))
    print('\nFINAL_STATUS=PASS'); print(f'FINAL_DECISION={decision}'); print('V22_061_VALIDATED=True'); print('V22_062PR_VALIDATED=True'); print('PREMARKET_FORWARD_CHAIN_MODIFIED=False')
    print(f'SIGNAL_CANDIDATE_COUNT={len(candidates)}'); print(f'LONG_CANDIDATE_COUNT={int((candidates.direction=="LONG").sum())}'); print(f'SHORT_CANDIDATE_COUNT={int((candidates.direction=="SHORT").sum())}')
    for v in EXIT_VARIANTS: print(f'TRADE_COUNT_{v}={int((trades.exit_variant==v).sum())}')
    print(f'SUPPORTED_EXIT_VARIANTS_FOR_REPLICATION={supported}'); print(f'CANONICAL_PARTITION_COUNT_READ={len(paths)}'); print('PARAMETER_SWEEP_EXECUTED=False'); print('DEVIATION_THRESHOLD_SWEEP_EXECUTED=False')
    print('SIGNAL_WINDOW_SWEEP_EXECUTED=False'); print('EXIT_THRESHOLD_OPTIMIZATION_EXECUTED=False'); print('CANONICAL_FILES_MODIFIED=False'); print('RAW_FILES_MODIFIED=False'); print('NEW_MARKET_DATA_CACHE_CREATED=False')
    print('BROKER_ACTION_ALLOWED=False'); print('PAPER_TRADING_ALLOWED=False'); print('OFFICIAL_ADOPTION_ALLOWED=False'); print(f'SUMMARY_PATH={summary_path}'); print(f'RESULT_DIRECTORY={result_dir}')
    return summary

def parse_args(argv:list[str]|None=None)->argparse.Namespace:
    p=argparse.ArgumentParser()
    p.add_argument('--v22-061-summary',default=r'D:\us-tech-quant-results\v22\V22.061_FAST3_SYNCHRONIZED_OPENING_RANGE_BREAKOUT_BASELINE_R1\v22_061_summary.json')
    p.add_argument('--v22-062pr-summary',default=r'D:\us-tech-quant-results\v22\V22.062PR_FAST3_PREMARKET_INDEPENDENT_FORWARD_REPLICATION_R1\v22_062pr_summary.json')
    p.add_argument('--canonical-root',default=r'D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical')
    p.add_argument('--result-dir',default=r'D:\us-tech-quant-results\v22\V22.063R1_FAST3_RTH_VWAP_MEAN_REVERSION_BASELINE_R1')
    p.add_argument('--execute',action='store_true'); return p.parse_args(argv)

def main(argv:list[str]|None=None)->int:
    a=parse_args(argv)
    if not a.execute: print('FINAL_STATUS=BLOCKED_EXECUTE_FLAG_REQUIRED'); return 2
    try:
        run_study(Path(a.v22_061_summary),Path(a.v22_062pr_summary),Path(a.canonical_root),Path(a.result_dir)); return 0
    except Exception as exc:
        print('FINAL_STATUS=FAIL'); print(f'ERROR_TYPE={type(exc).__name__}'); print(f'ERROR={exc}'); return 1

if __name__=='__main__': raise SystemExit(main())
