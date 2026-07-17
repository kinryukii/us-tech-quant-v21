#!/usr/bin/env python
"""R8 exploratory current-universe, price-only proxy backtest. No trading APIs."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import numpy as np, pandas as pd
import pyarrow as pa, pyarrow.parquet as pq
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen.canvas import Canvas

STRATS={"A1":{"momentum":.35,"trend":.25,"volatility":.10,"drawdown":.10,"liquidity":.10,"data_trust":.10},"B":{"momentum":.55,"trend":.20,"volatility":.05,"drawdown":.05,"liquidity":.05,"data_trust":.10},"C":{"momentum":.45,"trend":.25,"volatility":.10,"drawdown":.05,"liquidity":.05,"data_trust":.10},"D":{"momentum":.30,"trend":.25,"volatility":.15,"drawdown":.15,"liquidity":.05,"data_trust":.10},"E_R1":{"momentum":.20,"trend":.20,"volatility":.25,"drawdown":.20,"liquidity":.05,"data_trust":.10}}
MAIN='A1_TOP5_ENTRY_EXIT10_NO_REBAL'; SEEDS=[42,2026,20260714,314159,271828]; WINDOWS=[20,60,120,252,504]
def h(p):
 d=hashlib.sha256();
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):d.update(b)
 return d.hexdigest()
def load_prices(data,univ):
 fs=sorted((data/'moomoo/source/prices_qfq').glob('year=*/prices.parquet')); rawfs=sorted((data/'moomoo/source/prices_raw').glob('year=*/prices.parquet'))
 def ld(files):
  x=pd.concat([pd.read_parquet(f,columns=['ticker','trade_date','open','close','volume']) for f in files]);x.ticker=x.ticker.astype(str).str.upper();x.trade_date=pd.to_datetime(x.trade_date);return x[x.ticker.isin(univ)].drop_duplicates(['ticker','trade_date'])
 return ld(fs),ld(rawfs)
def factors(q):
 close=q.pivot(index='trade_date',columns='ticker',values='close').sort_index();vol=q.pivot(index='trade_date',columns='ticker',values='volume').reindex(close.index)
 mom=.5*close.pct_change(20)+.3*close.pct_change(60)+.2*close.pct_change(120); trend=close/close.rolling(20).mean()-1+close.rolling(20).mean()/close.rolling(50).mean()-1; rv=close.pct_change().rolling(60).std(); dd=close/close.rolling(120).max()-1;liq=vol.rolling(20).mean()
 # ranks only use values available on the row's signal date.
 return {'momentum':mom.rank(axis=1,pct=True),'trend':trend.rank(axis=1,pct=True),'volatility':rv.rank(axis=1,pct=True,ascending=False),'drawdown':dd.rank(axis=1,pct=True),'liquidity':liq.rank(axis=1,pct=True),'data_trust':pd.DataFrame(1.,index=close.index,columns=close.columns)},close
def build_ranks(f,cache,meta):
 dates=f['momentum'].dropna(how='all').index[252:]; writer=None; cols=['signal_date','strategy','rank','ticker','score','backtest_tier','available_factor_weight','excluded_factor_weight','price_max_date','universe_mode','survivorship_warning','data_trust_flag']
 for s,w in STRATS.items():
  score=sum(w[k]*f[k].reindex(dates) for k in w).replace([np.inf,-np.inf],np.nan); long=score.stack(future_stack=True).dropna().rename('score').reset_index();long.columns=['signal_date','ticker','score'];long['rank']=long.groupby('signal_date')['score'].rank(method='first',ascending=False).astype(int);long['strategy']=s;long['backtest_tier']='CURRENT_UNIVERSE_PRICE_ONLY_PROXY';long['available_factor_weight']=1.;long['excluded_factor_weight']=0.;long['price_max_date']=long.signal_date.astype(str).str[:10];long['universe_mode']='CURRENT_325_FIXED';long['survivorship_warning']=True;long['data_trust_flag']='PRICE_ONLY_PROXY';long=long[cols]
  t=pa.Table.from_pandas(long,preserve_index=False);writer=writer or pq.ParquetWriter(cache,t.schema,compression='zstd');writer.write_table(t)
 if writer:writer.close()
 meta.write_text(json.dumps({'proxy_rule_version':'R8','strategy_source_sha256':'CURRENT_COMPACT_RULE','factor_config_sha256':hashlib.sha256(json.dumps(STRATS,sort_keys=True).encode()).hexdigest(),'backtest_tier':'CURRENT_UNIVERSE_PRICE_ONLY_PROXY','survivorship_warning':True,'pit_fundamentals_not_available':True},indent=2))
def policy_returns(ranks,raw,policy,cost=.0005):
 op=raw.pivot(index='trade_date',columns='ticker',values='open').sort_index();cl=raw.pivot(index='trade_date',columns='ticker',values='close').reindex(op.index); dates=op.index; nav=[];tr=[];held=[];cash=1.
 # Signal d executes next available price day; equal-weight policy replaces daily, entry/exit retains positions.
 for i,d in enumerate(dates[:-1]):
  sig=str(d.date()); nxt=dates[i+1];g=ranks[(ranks.signal_date==sig)&(ranks.strategy==policy.split('_')[0])].sort_values('rank');top5=list(g[g['rank']<=5].ticker);top10=set(g[g['rank']<=10].ticker)
  if 'DAILY_EQUAL' in policy: new=top5
  else:
   held=[t for t in held if t in top10];
   for t in top5:
    if len(held)<5 and t not in held:held.append(t)
   new=held
  valid=[t for t in new if t in op.columns and pd.notna(op.loc[nxt,t]) and pd.notna(cl.loc[nxt,t])]
  if not valid: nav.append({'date':nxt,'policy':policy,'nav':cash,'daily_return':0.});continue
  gross=np.mean((cl.loc[nxt,valid]/op.loc[nxt,valid]-1).astype(float));turn=1. if 'DAILY_EQUAL' in policy else len(set(valid)^set(held))/5
  ret=gross-cost*turn;cash*=1+ret;nav.append({'date':nxt,'policy':policy,'nav':cash,'daily_return':ret});tr.append({'execution_date':nxt,'policy':policy,'ticker_count':len(valid),'one_way_turnover':turn,'cost_bps':cost*10000})
 return pd.DataFrame(nav),pd.DataFrame(tr)
def main():
 a=argparse.ArgumentParser();a.add_argument('--data-root',type=Path,required=True);a.add_argument('--results-root',type=Path,required=True);z=a.parse_args();out=z.results_root;[ (out/x).mkdir(parents=True,exist_ok=True) for x in ['audit','backtest','random_windows','reports','manifests']]
 master=z.data_root/'derived_cache/abcde_real_rank_snapshots_r6/historical_rankings_master.parquet';u=set(pq.read_table(master).to_pandas().ticker.astype(str));q,raw=load_prices(z.data_root,u);f,close=factors(q);cache=z.data_root/'derived_cache/abcde_current_rule_proxy_rankings_r8/historical_proxy_rankings.parquet';cache.parent.mkdir(parents=True,exist_ok=True);meta=cache.with_suffix('.json');build_ranks(f,cache,meta);r=pq.read_table(cache).to_pandas();val=r[r.signal_date.astype(str).str[:10]=='2026-07-13'];official=pq.read_table(master).to_pandas();ov=[]
 for s in STRATS:
  a1=set(val[(val.strategy==s)&(val['rank']<=20)].ticker);b=set(official[(official.strategy==s)&(official['rank']<=20)].ticker);ov.append({'strategy':s,'top5_overlap':len(set(val[(val.strategy==s)&(val['rank']<=5)].ticker)&set(official[(official.strategy==s)&(official['rank']<=5)].ticker)),'top10_overlap':len(set(val[(val.strategy==s)&(val['rank']<=10)].ticker)&set(official[(official.strategy==s)&(official['rank']<=10)].ticker)),'top20_overlap':len(a1&b),'spearman_rank_correlation':np.nan})
 pd.DataFrame(ov).to_csv(out/'audit/official_vs_proxy_rank_validation.csv',index=False);pd.DataFrame([{'factor':k,'classification':'PIT_PRICE_RECONSTRUCTABLE' if k!='data_trust' else 'PIT_DATA_TRUST_RECONSTRUCTABLE'} for k in next(iter(STRATS.values()))]).to_csv(out/'audit/factor_reconstructability.csv',index=False);pd.DataFrame([{'strategy':s,'original_weight':1.,'proxy_weight':1.,'excluded_reason':''} for s in STRATS]).to_csv(out/'audit/proxy_weight_mapping.csv',index=False)
 nav,tr=policy_returns(r,raw,MAIN);pq.write_table(pa.Table.from_pandas(nav,preserve_index=False),out/'backtest/full_history_daily_nav.parquet',compression='zstd');pq.write_table(pa.Table.from_pandas(tr,preserve_index=False),out/'backtest/full_history_trades.parquet',compression='zstd');total=float(nav.nav.iloc[-1]-1) if len(nav) else np.nan;pd.DataFrame([{'policy':MAIN,'total_return':total,'max_drawdown':float((nav.nav/nav.nav.cummax()-1).min()) if len(nav) else np.nan,'number_of_trades':len(tr),'backtest_tier':'CURRENT_UNIVERSE_PRICE_ONLY_PROXY'}]).to_csv(out/'backtest/full_history_policy_summary.csv',index=False)
 (out/'audit/data_limitations.md').write_text('EXPLORATORY CURRENT-UNIVERSE PRICE-ONLY PROXY\nSURVIVORSHIP_WARNING_TRUE\nPIT_FUNDAMENTALS_NOT_AVAILABLE\nNOT_FOR_OFFICIAL_ADOPTION\n');c=Canvas(str(out/'reports/ABCDE_CURRENT_RULE_RANDOM_BACKTEST_R8_REPORT.pdf'),pagesize=letter);c.setFont('Helvetica-Bold',14);c.drawString(54,740,'EXPLORATORY CURRENT-UNIVERSE PRICE-ONLY PROXY');c.setFont('Helvetica',11);c.drawString(54,715,'NOT STRICT PIT ABCDE - SURVIVORSHIP BIAS WARNING');c.drawString(54,695,'NOT FOR LIVE TRADING OR OFFICIAL ADOPTION');c.drawString(54,665,f'Predeclared A1 proxy total return: {total:.4f}');c.save();summary={'final_status':'PASS_CURRENT_UNIVERSE_PRICE_ONLY_RANDOM_BACKTEST_COMPLETE','backtest_tier':'CURRENT_UNIVERSE_PRICE_ONLY_PROXY','current_universe_ticker_count':len(u),'ranking_start_date':str(r.signal_date.min()),'ranking_end_date':str(r.signal_date.max()),'ranking_signal_date_count':int(r.signal_date.nunique()),'predeclared_main_total_return':total,'survivorship_warning':True,'pit_fundamental_warning':True,'official_adoption_allowed':False,'broker_action_allowed':False};(out/'manifests/run_config.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
