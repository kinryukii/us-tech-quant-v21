#!/usr/bin/env python3
"""R10A: frozen six-method A1_CONTROL next-open random-window diagnostic."""
from __future__ import annotations

import argparse, hashlib, json, math, shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(r"D:\us-tech-quant-results\R10A_A1_ENTRY_EXIT_RANDOM_BACKTEST_R1")
RANKS = Path(r"D:\us-tech-quant-data\derived_cache\abcde_current_rule_proxy_rankings_r8\historical_proxy_rankings.parquet")
PRICES = Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq")
SEED, COST, BOOTSTRAPS = 2026071801, 0.0005, 2000
METHODS = {
    "METHOD_1_TOP1_EXIT3": (1, 1, 3, None),
    "METHOD_2_TOP3_EXIT5": (3, 3, 5, None),
    "METHOD_3_TOP5_EXIT10_BASELINE": (5, 5, 10, None),
    "METHOD_4_TOP5_EXIT5_FAST": (5, 5, 5, None),
    "METHOD_5_TOP5_EXIT15_SLOW": (5, 5, 15, None),
    "METHOD_6_TOP5_FIXED10": (5, 5, None, 10),
}
HORIZONS = (20, 60, 120, 252, 504)
TOL = 1e-9


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def norm(x: object) -> str:
    s = str(x).strip().upper().replace("-", ".")
    return s[3:] if s.startswith("US.") else s


def exposure_metrics(cash_value: float, position_value: float) -> tuple[float, float, float]:
    """Post-open-trades / close-mark exposure; terminal liquidation is excluded."""
    nav = cash_value + position_value
    if nav <= 0: raise RuntimeError("non-positive NAV during exposure accounting")
    cash_share, invested = cash_value / nav, position_value / nav
    if min(cash_value, position_value, cash_share, invested) < -TOL or abs(cash_share + invested - 1.0) > TOL:
        raise RuntimeError("exposure accounting identity failure")
    return cash_share, invested, nav


def compute_max_drawdown_from_nav(nav_values) -> float:
    values = np.asarray(nav_values, dtype=float)
    if not len(values) or not np.isfinite(values).all() or np.any(values <= 0): raise ValueError("invalid NAV path")
    return float(np.min(values / np.maximum.accumulate(values) - 1.0))


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not RANKS.exists() or not PRICES.exists(): raise FileNotFoundError("frozen local ranking or QFQ price source absent")
    r = pq.read_table(RANKS, columns=["signal_date", "strategy", "rank", "ticker"], filters=[("strategy", "=", "A1")]).to_pandas()
    r["signal_date"] = pd.to_datetime(r.signal_date).dt.normalize(); r["ticker"] = r.ticker.map(norm)
    r["rank"] = pd.to_numeric(r["rank"], errors="coerce")
    r = r.dropna().query("rank <= 15").sort_values(["signal_date", "rank", "ticker"]).drop_duplicates(["signal_date", "ticker"])
    wanted = set(r.ticker) | {"QQQ"}; fs = sorted(PRICES.glob("year=*/prices.parquet"))
    if not fs: raise FileNotFoundError("no QFQ price partitions")
    xs = []
    for f in fs:
        x = pq.read_table(f, columns=["ticker", "trade_date", "open", "close"]).to_pandas(); x["ticker"] = x.ticker.map(norm)
        xs.append(x[x.ticker.isin(wanted)])
    p = pd.concat(xs, ignore_index=True); p["date"] = pd.to_datetime(p.trade_date).dt.normalize()
    p["open"] = pd.to_numeric(p.open, errors="coerce"); p["close"] = pd.to_numeric(p.close, errors="coerce")
    p = p.dropna(subset=["date", "ticker", "open", "close"]).query("open > 0 and close > 0").drop_duplicates(["date", "ticker"], keep="last")
    return r, p


def manifest(days: pd.DatetimeIndex, signals: dict[pd.Timestamp, tuple], op: np.ndarray, qi: int) -> pd.DataFrame:
    rows = []; rng = np.random.default_rng(SEED)
    for h in HORIZONS:
        eligible = [i for i in range(1, len(days) - h + 1) if days[i - 1] in signals and np.isfinite(op[i, qi]) and np.isfinite(op[i + h - 1, qi])]
        pick = eligible if len(eligible) <= 100 else sorted(rng.choice(eligible, 100, replace=False))
        for j, i in enumerate(pick): rows.append({"window_id": f"A1_{h}_{j:03d}", "horizon_trading_days": h, "start_date": days[i].date().isoformat(), "end_date": days[i+h-1].date().isoformat(), "start_index": i, "end_index": i+h-1, "master_seed": SEED})
    return pd.DataFrame(rows)


def run_window(method: str, w: pd.Series, days, signals, oi, ci, tickers, qi, return_daily_path: bool = False, strategy_config: dict | None = None, signal_context: dict | None = None, return_trade_events: bool = False, return_diagnostics: bool = False) -> tuple[dict, list[dict]]:
    """The sole daily portfolio loop; config=None preserves frozen behaviour."""
    if strategy_config is not None:
        return _run_window_configured(w, days, signals, oi, ci, tickers, qi, strategy_config, signal_context or {}, return_daily_path, return_trade_events, return_diagnostics)
    slots, entry_n, exit_rank, fixed = METHODS[method]; st, en = int(w.start_index), int(w.end_index)
    cash = [1.0 / slots] * slots; pos = [None] * slots; trades = []; costs = turnover = 0.; cash_samples=[]; exposure_samples=[]; navs = []; peak = 1.; dd = 0.; path = {"dates":[],"nav":[],"daily_returns":[],"cash":[],"position_market_value":[],"invested_exposure":[],"is_terminal_liquidation":[]} if return_daily_path else None
    qshares = (1 - COST) / oi[st, qi]
    for d in range(st, en):  # final day is reserved for the required open forced exit
        ranks, top = signals.get(days[d-1], ({}, []))
        # sell first; a fixed-10 position bought at b sells at b+11 open.
        for j, x in enumerate(pos):
            if x is None: continue
            ticker, shares, bought, basis = x; rank = ranks.get(ticker, 10**6)
            must = (fixed is not None and d - bought > fixed) or (exit_rank is not None and rank > exit_rank)
            if must and np.isfinite(oi[d, tickers[ticker]]):
                gross = shares * oi[d, tickers[ticker]]; fee = gross * COST; cash[j] += gross - fee; costs += fee; turnover += gross
                trades.append({"ticker":ticker,"side":"SELL","day":d,"pnl":gross-fee-basis,"holding_days":d-bought,"forced":False})
                pos[j] = None
        candidates = [t for t in top[:entry_n] if t not in {x[0] for x in pos if x is not None} and t in tickers and np.isfinite(oi[d, tickers[t]])]
        for j in range(slots):
            if pos[j] is None and candidates and cash[j] > 0:
                t = candidates.pop(0); allocation = cash[j]; fee = allocation * COST; sh = (allocation-fee) / oi[d, tickers[t]]
                pos[j] = (t, sh, d, allocation); cash[j] = 0.; costs += fee; turnover += allocation
                trades.append({"ticker":t,"side":"BUY","day":d,"pnl":0.,"holding_days":0,"forced":False})
        position_value = sum(x[1] * ci[d, tickers[x[0]]] for x in pos if x is not None)
        cash_share, invested, nav = exposure_metrics(sum(cash), position_value)
        cash_samples.append(cash_share); exposure_samples.append(invested); peak = max(peak, nav); dd = min(dd, nav / peak - 1); navs.append(nav)
        if path is not None:
            prior = path["nav"][-1] if path["nav"] else 1.0
            path["dates"].append(days[d]); path["nav"].append(float(nav)); path["daily_returns"].append(float(nav/prior-1)); path["cash"].append(float(sum(cash))); path["position_market_value"].append(float(position_value)); path["invested_exposure"].append(float(invested)); path["is_terminal_liquidation"].append(False)
    # All open positions are liquidated at the final usable session's real open.
    for j, x in enumerate(pos):
        if x is not None:
            ticker, shares, bought, basis = x; series = oi[st:en+1, tickers[ticker]]; valid = np.flatnonzero(np.isfinite(series))
            if not len(valid): raise RuntimeError(f"no legal forced-exit open for {ticker} in {w.window_id}")
            exit_d = st + int(valid[-1]); gross = shares * oi[exit_d, tickers[ticker]]; fee = gross * COST; cash[j] += gross-fee; costs += fee; turnover += gross
            trades.append({"ticker":ticker,"side":"SELL","day":exit_d,"pnl":gross-fee-basis,"holding_days":exit_d-bought,"forced":True}); pos[j] = None
    nav = sum(cash); peak = max(peak, nav); dd = min(dd, nav / peak - 1)
    if path is not None:
        prior = path["nav"][-1] if path["nav"] else 1.0
        path["dates"].append(days[en]); path["nav"].append(float(nav)); path["daily_returns"].append(float(nav/prior-1)); path["cash"].append(float(nav)); path["position_market_value"].append(0.0); path["invested_exposure"].append(0.0); path["is_terminal_liquidation"].append(True)
    qnav = qshares * oi[en, qi] * (1-COST); qdd = float(np.min(np.array([qshares * ci[d, qi] for d in range(st, en)]) / np.maximum.accumulate([qshares * ci[d, qi] for d in range(st, en)]) - 1)) if en > st else 0.
    sells = [t for t in trades if t["side"] == "SELL"]
    ticker_pnl = {}
    for t in sells: ticker_pnl[t["ticker"]] = ticker_pnl.get(t["ticker"], 0.) + t["pnl"]
    if not cash_samples or len(cash_samples) != len(exposure_samples): raise RuntimeError("missing exposure observations")
    result={"strategy_method_return":nav-1,"qqq_return":qnav-1,"excess_return":nav-qnav,"strategy_max_drawdown":dd,"qqq_max_drawdown":qdd,"trade_count":len(trades),"turnover":turnover,"transaction_cost":costs,"average_cash_share":float(np.mean(cash_samples)),"median_cash_share":float(np.median(cash_samples)),"average_invested_exposure":float(np.mean(exposure_samples)),"median_invested_exposure":float(np.median(exposure_samples)),"exposure_identity_max_abs_error":float(np.max(np.abs(np.array(cash_samples)+np.array(exposure_samples)-1))),"terminal_liquidation_excluded":True,"forced_exit_count":sum(t["forced"] for t in trades),"median_holding_days":float(np.median([t["holding_days"] for t in sells])) if sells else np.nan,"worst_trade_return":min((t["pnl"] for t in sells), default=np.nan),"max_ticker_pnl":max(ticker_pnl.values(), default=0.)}
    if path is not None:
        if abs(compute_max_drawdown_from_nav(path["nav"])-dd)>1e-12: raise RuntimeError("daily path drawdown mismatch")
        result["daily_path"]=path
    return result, trades


def _run_window_configured(w, days, signals, oi, ci, tickers, qi, cfg, ctx, return_daily_path, return_trade_events, return_diagnostics):
    """Research-only configuration branch of run_window, not a separate engine."""
    st,en=int(w.start_index),int(w.end_index); slots=5; cash=1.; pos=[]; qsh=0.; trades=[]; rejects=[]; turnover=costs=0.; navs=[]; cashs=[]; inv=[]; qalloc=[]; peak=1.;dd=0.
    def emit(kind,day,ticker,sh,price,reason=None,extra=None):
        nonlocal cash,turnover,costs,qsh
        gross=sh*price; fee=gross*COST; buy=kind.endswith("BUY")
        if buy: cash-=gross+fee; costs+=fee; turnover+=gross
        else: cash+=gross-fee; costs+=fee; turnover+=gross
        e={"window_id":w.window_id,"strategy_name":cfg["name"],"signal_date":str(days[day-1].date()),"execution_date":str(days[day].date()),"ticker":ticker,"event_type":kind,"exit_reason":reason,"quantity_or_weight":sh,"execution_price":price,"gross_value":gross,"transaction_cost":fee,"cash_after":cash}
        if extra:e.update(extra)
        trades.append(e)
    for d in range(st,en):
        sd=days[d-1]; ranks,top=signals.get(sd,({},[])); regime=classify_market_regime(ctx,d-1,qi) if cfg.get("regime") else "STRONG"; maxstocks={"STRONG":5,"NEUTRAL":3,"RISK_OFF":1}[regime]
        # 1 exits; reason calculation only consumes signal-day data.
        survivors=[]
        for x in pos:
            reason=resolve_exit_reason(x,ranks,ctx,d-1,tickers)
            if reason and np.isfinite(oi[d,tickers[x["ticker"]]]): emit("STOCK_SELL",d,x["ticker"],x["shares"],oi[d,tickers[x["ticker"]]],reason,{"slot_id":x["slot_id"]})
            else: survivors.append(x)
        pos=survivors
        # 2 regime trim: missing rank sorts worst.
        if len(pos)>maxstocks:
            pos.sort(key=lambda x:ranks.get(x["ticker"],10**9),reverse=True)
            for x in pos[maxstocks:]: emit("STOCK_SELL",d,x["ticker"],x["shares"],oi[d,tickers[x["ticker"]]],"REGIME_TRIM",{"slot_id":x["slot_id"]})
            pos=pos[:maxstocks]
        # 3 qqq sell before new buys.
        if regime!="NEUTRAL" and qsh:
            emit("QQQ_SELL",d,"QQQ",qsh,oi[d,qi],"REGIME_CHANGE");qsh=0.
        # 4/5 stocks: fixed $0.20 initial allocation, never rebalance.
        held={x["ticker"] for x in pos}
        for t in evaluate_entry(sd,top,ranks,signals,ctx,d-1,pos,cfg,rejects):
            if len(pos)>=maxstocks or t in held or t not in tickers or not np.isfinite(oi[d,tickers[t]]) or cash<.2*(1+COST): continue
            px=oi[d,tickers[t]]; sh=.2/px; atr=ctx.get("atr",np.empty((0,0)))[d-1,tickers[t]] if len(ctx.get("atr",[])) else np.nan
            x={"ticker":t,"shares":sh,"slot_id":next(i for i in range(5) if i not in {z["slot_id"] for z in pos}),"entry_signal_date":sd,"entry_date":days[d],"entry_open_price":px,"entry_atr20":atr,"peak_close":ci[d-1,tickers[t]],"soft_exit_consecutive_count":0,"entry_source":entry_source(t,sd,signals)}
            emit("STOCK_BUY",d,t,sh,px,None,{"slot_id":x["slot_id"],"entry_source":x["entry_source"],"a_rank":ranks.get(t) });pos.append(x);held.add(t)
        # 6 Neutral QQQ target is exactly 40% of initial capital, no cash sweep.
        target=.4 if regime=="NEUTRAL" else 0.; qval=qsh*oi[d,qi]
        if qval+1e-12<target and cash>(target-qval)*(1+COST):
            sh=(target-qval)/oi[d,qi];emit("QQQ_BUY",d,"QQQ",sh,oi[d,qi],"NEUTRAL_TARGET");qsh+=sh
        for x in pos:x["peak_close"]=max(x["peak_close"],ci[d,tickers[x["ticker"]]])
        pval=sum(x["shares"] * ci[d, tickers[x["ticker"]]] for x in pos); qv=qsh*ci[d,qi];nav=cash+pval+qv;peak=max(peak,nav);dd=min(dd,nav/peak-1);navs.append(nav);cashs.append(cash/nav);inv.append(pval/nav);qalloc.append(qv/nav)
    # Uniform final open liquidation.
    for x in pos: emit("WINDOW_END_FORCED_EXIT",en,x["ticker"],x["shares"],oi[en,tickers[x["ticker"]]],"WINDOW_END_FORCED_EXIT",{"slot_id":x["slot_id"]})
    if qsh: emit("WINDOW_END_FORCED_EXIT",en,"QQQ",qsh,oi[en,qi],"WINDOW_END_FORCED_EXIT");qsh=0.
    nav=cash; qshares=(1-COST)/oi[st,qi];qnav=qshares*oi[en,qi]*(1-COST); sells=[x for x in trades if x["event_type"] in ("STOCK_SELL","WINDOW_END_FORCED_EXIT")]
    z={"strategy_method_return":nav-1,"qqq_return":qnav-1,"excess_return":nav-qnav,"strategy_max_drawdown":dd,"qqq_max_drawdown":0.,"trade_count":len(trades),"turnover":turnover,"transaction_cost":costs,"average_cash_share":float(np.mean(cashs)) if cashs else 1.,"median_cash_share":float(np.median(cashs)) if cashs else 1.,"average_invested_exposure":float(np.mean(inv)) if inv else 0.,"median_invested_exposure":float(np.median(inv)) if inv else 0.,"average_qqq_allocation":float(np.mean(qalloc)) if qalloc else 0.,"forced_exit_count":sum(x["event_type"]=="WINDOW_END_FORCED_EXIT" for x in trades),"median_holding_days":np.nan,"worst_trade_return":np.nan,"max_ticker_pnl":0.,"rejected_entries":rejects}
    if return_daily_path:z["daily_path"]={"nav":navs}
    return z,trades

def entry_source(t,day,signals):
    prev=signals.get(day-pd.offsets.BDay(1),({},[]))[0];now=signals.get(day,({},[]))[0];return "BOTH_CONFIRMATIONS" if prev.get(t,99)<=5 and prev.get(t,99)<=10 and now.get(t,99)<prev.get(t,99) else ("CONTINUOUS_TOP5" if prev.get(t,99)<=5 else "IMPROVING_FROM_TOP10")
def classify_market_regime(ctx,idx,qi):
    c=ctx.get("close");
    if c is None or idx<199:return "RISK_OFF"
    q=c[:idx+1,qi];ma20=np.nanmean(q[-20:]);ma50=np.nanmean(q[-50:]);ma200=np.nanmean(q[-200:]);return "STRONG" if q[-1]>ma50 and ma20>ma50 else ("NEUTRAL" if q[-1]>ma200 else "RISK_OFF")
def resolve_exit_reason(x,ranks,ctx,idx,ti):
    t=x["ticker"]; rank=ranks.get(t);close=ctx.get("close")[idx,ti[t]];atr=ctx.get("atr")[idx,ti[t]]
    if rank is None:return "MISSING_RANK_EXIT"
    if np.isfinite(x["entry_atr20"]) and close<=x["entry_open_price"]-2.5*x["entry_atr20"]:return "INITIAL_ATR_STOP"
    if x["peak_close"]>=x["entry_open_price"]*1.05 and np.isfinite(atr) and close<=x["peak_close"]-3*atr:return "TRAILING_ATR_EXIT"
    if rank>15:return "HARD_RANK_EXIT"
    prev=ctx.get("rank_history",{}).get((idx-1,t));return "SOFT_RANK_EXIT" if rank>10 and prev is not None and prev>10 else None
def evaluate_entry(day,top,ranks,signals,ctx,idx,pos,cfg,rejects):
    if cfg.get("baseline"):return top[:5]
    prev=signals.get(day-pd.offsets.BDay(1),({},[]))[0];out=[]
    for t in top[:5]:
        a=ranks.get(t,99);p=prev.get(t,99);ok=p<=5 or (p<=10 and a<p)
        rs=ctx.get("strategy_ranks",{}).get(day,{});count=sum(rs.get(k,{}).get(t,99)<=10 for k in ("A","B","C","D","E"));de=rs.get("D",{}).get(t,99)<=20 or rs.get("E",{}).get(t,99)<=20
        if not(ok and count>=3 and de):rejects.append({"ticker":t,"reason":"ENTRY_CORE"});continue
        if cfg.get("gap") and not calculate_cutoff_gap_gate(ctx,day):rejects.append({"ticker":t,"reason":"CUTOFF_GAP"});continue
        if cfg.get("cluster") and not calculate_correlation_gate(ctx,idx,t,pos):rejects.append({"ticker":t,"reason":"HIGH_CORRELATION"});continue
        out.append(t)
    return out
def calculate_cutoff_gap_gate(ctx,day):
    q=ctx.get("gap_q25",{}).get(day);g=ctx.get("gap",{}).get(day);return not(np.isfinite(q) and np.isfinite(g) and g<=q)
def calculate_correlation_gate(ctx,idx,t,pos):
    if len(pos)<2:return True
    c=ctx.get("returns");ti=ctx.get("tickers",{});hits=0
    for x in pos:
        a,b=c[max(0,idx-60):idx,ti[t]],c[max(0,idx-60):idx,ti[x["ticker"]]];m=np.isfinite(a)&np.isfinite(b)
        if m.sum()>=40 and np.corrcoef(a[m],b[m])[0,1]>=.75:hits+=1
    return hits<2


def aggregate(g: pd.DataFrame, label: str, seed_offset: int) -> dict:
    x = g.copy(); ex = x.excess_return.to_numpy(); rng = np.random.default_rng(SEED + seed_offset)
    boot = np.array([np.median(rng.choice(ex, len(ex), replace=True)) for _ in range(BOOTSTRAPS)]) if len(ex) else np.array([np.nan])
    q = lambda c,p: float(x[c].quantile(p)) if len(x) else np.nan
    posh = int(sum(x.groupby("horizon_trading_days").excess_return.median() > 0)); years = x.groupby("start_year").excess_return.median()
    improve = np.maximum(x.excess_return, 0); maxw = float(improve.max()/improve.sum()) if improve.sum() > 0 else 1.
    tick = x.max_ticker_pnl.clip(lower=0); maxt = float(tick.max()/tick.sum()) if tick.sum() > 0 else 1.
    worst_gap = float(x.strategy_max_drawdown.min() - x.qqq_max_drawdown.min())
    return {"scope":label,"valid_window_count":len(x),"median_return":q("strategy_method_return",.5),"mean_return":float(x.strategy_method_return.mean()),"p05_return":q("strategy_method_return",.05),"p25_return":q("strategy_method_return",.25),"positive_return_share":float((x.strategy_method_return>0).mean()),"median_qqq_return":q("qqq_return",.5),"median_excess_vs_qqq":q("excess_return",.5),"mean_excess_vs_qqq":float(x.excess_return.mean()),"beat_qqq_window_share":float((x.excess_return>0).mean()),"median_max_drawdown":q("strategy_max_drawdown",.5),"worst_max_drawdown":float(x.strategy_max_drawdown.min()),"qqq_median_max_drawdown":q("qqq_max_drawdown",.5),"downside_deviation":float(np.sqrt(np.mean(np.minimum(x.strategy_method_return,0)**2))),"worst_window_return":float(x.strategy_method_return.min()),"worst_trade_return":float(x.worst_trade_return.min()),"loss_window_share":float((x.strategy_method_return<0).mean()),"total_trade_count":int(x.trade_count.sum()),"median_trade_count_per_window":q("trade_count",.5),"median_holding_days":q("median_holding_days",.5),"turnover":float(x.turnover.sum()),"annualized_turnover":float(np.median(x.turnover*252/x.horizon_trading_days)),"transaction_cost":float(x.transaction_cost.sum()),"average_cash_share":float(x.average_cash_share.mean()),"median_cash_share":q("median_cash_share",.5),"average_invested_exposure":float(x.average_invested_exposure.mean()),"median_invested_exposure":q("median_invested_exposure",.5),"forced_exit_count":int(x.forced_exit_count.sum()),"positive_horizon_count":posh,"positive_year_count":int((years>0).sum()),"max_single_ticker_improvement_contribution":maxt,"max_single_window_improvement_contribution":maxw,"bootstrap_ci_low":float(np.quantile(boot,.025)),"bootstrap_ci_high":float(np.quantile(boot,.975)),"worst_drawdown_gap_vs_qqq":worst_gap}


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--output-dir",type=Path,default=OUT); ap.add_argument("--reuse-frozen-manifest",action="store_true"); a=ap.parse_args(); out=a.output_dir
    if out.exists() and any(out.iterdir()) and not a.reuse_frozen_manifest: raise RuntimeError("R10A output directory already populated; refusing a second manifest")
    if a.reuse_frozen_manifest and not (out/"r10a_window_manifest.csv").exists(): raise RuntimeError("no frozen R10A manifest to reuse")
    core = [RANKS, ROOT/"scripts/v22/abcde_current_rule_random_backtest_r9.py"]; before={str(p):sha(p) for p in core}
    manifest_hash_before=sha(out/"r10a_window_manifest.csv") if a.reuse_frozen_manifest else None
    old_d=pd.read_csv(out/"r10a_paired_window_results.csv") if a.reuse_frozen_manifest else None
    old_summary=pd.read_csv(out/"r10a_method_summary.csv") if a.reuse_frozen_manifest else None
    r,p=load(); days=pd.DatetimeIndex(sorted(p.date.unique())); names=sorted(p.ticker.unique()); ti={t:i for i,t in enumerate(names)}
    op=p.pivot(index="date",columns="ticker",values="open").reindex(index=days,columns=names).to_numpy(float); cl=p.pivot(index="date",columns="ticker",values="close").reindex(index=days,columns=names).to_numpy(float); cm=pd.DataFrame(cl).ffill().to_numpy(float)
    signals={pd.Timestamp(d):(dict(zip(g.ticker,g["rank"].astype(int))),g.sort_values("rank").ticker.tolist()) for d,g in r.groupby("signal_date")}
    if a.reuse_frozen_manifest: m=pd.read_csv(out/"r10a_window_manifest.csv")
    else:
        m=manifest(days,signals,op,ti["QQQ"]); out.mkdir(parents=True); m.to_csv(out/"r10a_window_manifest.csv",index=False)
    rows=[]
    for method in METHODS:
        for _,w in m.iterrows():
            z,_=run_window(method,w,days,signals,op,cm,ti,ti["QQQ"]); rows.append({"method":method,"window_id":w.window_id,"horizon_trading_days":int(w.horizon_trading_days),"start_date":w.start_date,"end_date":w.end_date,"start_year":pd.Timestamp(w.start_date).year,**z})
    d=pd.DataFrame(rows)
    identity_ok=bool((d.average_cash_share.between(-TOL,1+TOL)&d.median_cash_share.between(-TOL,1+TOL)&d.average_invested_exposure.between(-TOL,1+TOL)&d.median_invested_exposure.between(-TOL,1+TOL)&(d.exposure_identity_max_abs_error<=TOL)&d.terminal_liquidation_excluded).all() and np.allclose(d.average_cash_share+d.average_invested_exposure,1.,rtol=0,atol=TOL))
    non_exposure_columns=["method","window_id","horizon_trading_days","start_date","end_date","start_year","strategy_method_return","qqq_return","excess_return","strategy_max_drawdown","qqq_max_drawdown","trade_count","turnover","transaction_cost","forced_exit_count","median_holding_days","worst_trade_return","max_ticker_pnl"]
    non_exposure_match=True
    if old_d is not None:
        a0=old_d[non_exposure_columns].sort_values(["method","window_id"]).reset_index(drop=True); a1=d[non_exposure_columns].sort_values(["method","window_id"]).reset_index(drop=True)
        for c in non_exposure_columns:
            if pd.api.types.is_numeric_dtype(a0[c]): non_exposure_match &= bool(np.allclose(a0[c],a1[c],rtol=0,atol=1e-12,equal_nan=True))
            else: non_exposure_match &= bool(a0[c].equals(a1[c]))
    if not identity_ok: raise RuntimeError("FAIL_EXPOSURE_ACCOUNTING_IDENTITY")
    if not non_exposure_match: raise RuntimeError("FAIL_REPAIR_CHANGED_TRADING_RESULTS")
    ss=[]
    for i,(method,g) in enumerate(d.groupby("method",sort=True)):
        allrow=aggregate(g,"OVERALL",i); hmed=g.groupby("horizon_trading_days").excess_return.median(); qualifies=allrow["median_excess_vs_qqq"]>0 and allrow["beat_qqq_window_share"]>=.55 and allrow["positive_horizon_count"]>=4 and not (hmed.get(252,-1)<0 and hmed.get(504,-1)<0) and allrow["bootstrap_ci_low"]>=0 and allrow["worst_drawdown_gap_vs_qqq"]>=-.05 and allrow["max_single_ticker_improvement_contribution"]<=.2 and allrow["max_single_window_improvement_contribution"]<=.2
        ss.append({"method":method,"qualified":qualifies,**allrow})
        for h,x in g.groupby("horizon_trading_days"): ss.append({"method":method,"qualified":qualifies,**aggregate(x,f"HORIZON_{h}",i+int(h))})
        for y,x in g.groupby("start_year"): ss.append({"method":method,"qualified":qualifies,**aggregate(x,f"YEAR_{y}",i+int(y))})
    summary=pd.DataFrame(ss); summary["metric_schema_version"]="R10A_METRIC_SCHEMA_2"; summary["cash_share_definition"]="TIME_WEIGHTED_DAILY_CASH_OVER_NAV"; summary["invested_exposure_definition"]="TIME_WEIGHTED_DAILY_POSITION_VALUE_OVER_NAV"; summary["exposure_valuation_timing"]="POST_OPEN_TRADES_CLOSE_MARK"; summary["terminal_forced_liquidation_included_in_exposure_metrics"]=False
    overall=summary[summary.scope.eq("OVERALL")].copy(); qualified=overall[overall.qualified].copy(); pool=qualified if len(qualified) else overall
    pool=pool.sort_values(["median_excess_vs_qqq","beat_qqq_window_share","positive_horizon_count","positive_year_count","worst_max_drawdown","annualized_turnover"],ascending=[False,False,False,False,False,True]); best=pool.iloc[0]
    after={str(p):sha(p) for p in core}; manifest_hash_unchanged=manifest_hash_before is None or sha(out/"r10a_window_manifest.csv")==manifest_hash_before; size=sum(x.stat().st_size for x in out.iterdir() if x.is_file()); files=sorted(set(x.name for x in out.iterdir() if x.is_file()) | {"r10a_summary.json"})
    code_growth=sum((ROOT/"scripts/v22"/n).stat().st_size for n in ("r10a_a1_entry_exit_random_backtest.py","test_r10a_a1_entry_exit_random_backtest.py"))
    old_overall=old_summary[old_summary.scope.eq("OVERALL")] if old_summary is not None else pd.DataFrame()
    result={"final_status":"PASS" if len(METHODS)==6 and len(m)==500 and len(files)<=4 and size<=12000000 and before==after and manifest_hash_unchanged and identity_ok and non_exposure_match else "FAIL","final_decision":"R10A_METRIC_INTEGRITY_REPAIRED","metric_schema_version":"R10A_METRIC_SCHEMA_2","cash_share_definition":"TIME_WEIGHTED_DAILY_CASH_OVER_NAV","invested_exposure_definition":"TIME_WEIGHTED_DAILY_POSITION_VALUE_OVER_NAV","exposure_valuation_timing":"POST_OPEN_TRADES_CLOSE_MARK","terminal_forced_liquidation_included_in_exposure_metrics":False,"strategy":"A1_CONTROL","master_seed":SEED,"expected_method_count":6,"actual_method_count":len(METHODS),"total_random_window_count":len(m),"window_manifest_hash_unchanged":manifest_hash_unchanged,"non_exposure_metrics_exact_match":non_exposure_match,"exposure_accounting_identity_pass":identity_ok,"window_id_identical_across_methods":all(d.groupby("method").window_id.apply(lambda x:set(x)==set(m.window_id))),"qqq_window_exact_match":bool(d.merge(m[["window_id","start_date","end_date"]],on="window_id",suffixes=("_result","_manifest")).apply(lambda x:x.start_date_result==x.start_date_manifest and x.end_date_result==x.end_date_manifest,axis=1).all()),"best_method":best.method,"best_diagnostic_method":best.method,"best_median_return":float(best.median_return),"qqq_median_return":float(best.median_qqq_return),"best_median_excess_vs_qqq":float(best.median_excess_vs_qqq),"best_beat_qqq_share":float(best.beat_qqq_window_share),"best_median_max_drawdown":float(best.median_max_drawdown),"qqq_median_max_drawdown":float(best.qqq_median_max_drawdown),"best_annualized_turnover":float(best.annualized_turnover),"qualified_method_count":int(len(qualified)),"official_adoption_allowed":False,"broker_action_allowed":False,"core_frozen_file_modified":before!=after,"files_created":files,"files_modified":["r10a_method_summary.csv","r10a_paired_window_results.csv","r10a_summary.json"],"repository_net_growth_bytes":code_growth,"results_output_size_bytes":size,"bootstrap_repetitions":BOOTSTRAPS,"old_overall_median_cash_share":float(old_overall.median_cash_share.median()) if len(old_overall) else None,"new_overall_median_cash_share":float(overall.median_cash_share.median()),"old_overall_average_invested_exposure":float(old_overall.average_invested_exposure.mean()) if len(old_overall) else None,"new_overall_average_invested_exposure":float(overall.average_invested_exposure.mean()),"trade_audit":{"forced_exit_count":int(d.forced_exit_count.sum()),"method_specific_window_drop_count":0,"no_rebalance":True,"execution":"T signal -> T+1 open"}}
    if not manifest_hash_unchanged: raise RuntimeError("FAIL_WINDOW_MANIFEST_CHANGED")
    for name, frame in (("r10a_paired_window_results.csv",d),("r10a_method_summary.csv",summary)):
        tmp=out/(name+".tmp"); frame.to_csv(tmp,index=False); tmp.replace(out/name)
    for _ in range(3):
        result["results_output_size_bytes"]=sum(x.stat().st_size for x in out.iterdir() if x.is_file())
        tmp=out/"r10a_summary.json.tmp"; tmp.write_text(json.dumps(result,indent=2),encoding="utf8"); tmp.replace(out/"r10a_summary.json")
    for k in ["final_status","final_decision","metric_schema_version","total_random_window_count","actual_method_count","window_manifest_hash_unchanged","non_exposure_metrics_exact_match","exposure_accounting_identity_pass","terminal_forced_liquidation_included_in_exposure_metrics","old_overall_median_cash_share","new_overall_median_cash_share","old_overall_average_invested_exposure","new_overall_average_invested_exposure","core_frozen_file_modified","files_modified","repository_net_growth_bytes","results_output_size_bytes"]: print(f"{k.upper()}={result[k]}")
    return 0 if result["final_status"]=="PASS" else 2

if __name__=="__main__": raise SystemExit(main())
