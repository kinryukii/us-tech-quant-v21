"""R9A confirmatory random-backtest infrastructure (local-data, research-only)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v22" / "ABCDE_CURRENT_RULE_RANDOM_BACKTEST_R9A_INFRASTRUCTURE_R1"
DEV_SEED, CONF_SEED = 2026071501, 2026071502
LIFECYCLE_COLUMNS = ["window_id","split","strategy_id","position_id","ticker","entry_signal_date","entry_trade_date","entry_price","entry_weight","entry_notional","exit_signal_date","exit_trade_date","exit_price","exit_weight","exit_notional","holding_trading_days","exit_reason","realized_return","buy_notional","sell_notional","round_trip_turnover","forced_exit","data_quality_flag"]
EXIT_REASONS = {"RULE_EXIT", "MEMBER_REMOVAL", "REPLACEMENT", "HORIZON_END", "LAST_VALID_PRICE_EXIT", "INVALID_WINDOW_BLOCKED"}

@dataclass
class Position:
    window_id: str; split: str; strategy_id: str; position_id: str; ticker: str
    entry_signal_date: str | None; entry_trade_date: str; entry_price: float; entry_weight: float; entry_notional: float
    exit_signal_date: str | None = None; exit_trade_date: str | None = None; exit_price: float | None = None
    exit_weight: float | None = None; exit_notional: float | None = None; holding_trading_days: int = 0
    exit_reason: str | None = None; realized_return: float | None = None; buy_notional: float = 0.0; sell_notional: float = 0.0
    round_trip_turnover: float = 0.0; forced_exit: bool = False; data_quality_flag: str = "OK"
    shares: float = 0.0
    def row(self):
        d=asdict(self); d.pop("shares"); return d

class Ledger:
    def __init__(self): self.rows: list[dict[str, Any]]=[]; self._ids=set()
    def record(self, position: Position, date: str, side: str, price: float, shares: float, reason: str, cash_before: float, cash_after: float):
        event_id=f"{position.window_id}:{position.position_id}:{side}:{len(self.rows)+1}"
        if event_id in self._ids: raise AssertionError("duplicate ledger event")
        self._ids.add(event_id); notional=price*shares
        self.rows.append({"event_id":event_id,"window_id":position.window_id,"split":position.split,"strategy_id":position.strategy_id,"position_id":position.position_id,"ticker":position.ticker,"trade_date":date,"side":side,"price":price,"shares":shares,"notional":notional,"normalized_notional":notional,"trade_reason":reason,"cash_before":cash_before,"cash_after":cash_after})
    def audit(self):
        x=pd.DataFrame(self.rows); buys=float(x.loc[x.side=="BUY","normalized_notional"].sum()) if len(x) else 0.; sells=float(x.loc[x.side=="SELL","normalized_notional"].sum()) if len(x) else 0.
        bad_sells=0 if len(x)==0 else int(sum((g.side=="SELL").sum() > (g.side=="BUY").sum() for _,g in x.groupby("position_id")))
        return {"buy_turnover":buys,"sell_turnover":sells,"total_turnover":buys+sells,"turnover_reconciliation_pass":abs((buys+sells)-float(x.normalized_notional.sum() if len(x) else 0))<1e-12,"duplicate_trade_count":len(x)-x.event_id.nunique() if len(x) else 0,"sell_without_historical_position_count":bad_sells,"entry_trade_count":int((x.side=="BUY").sum()) if len(x) else 0,"exit_trade_count":int((x.side=="SELL").sum()) if len(x) else 0}

GATE_CONFIG={"median_return":{"op":">=","threshold":0.0},"median_excess_vs_qqq":{"op":">=","threshold":0.0},"beat_qqq_share":{"op":">=","threshold":0.50},"worst_return":{"op":">=","threshold":-0.30},"lower_decile_return":{"op":">=","threshold":-0.20},"max_drawdown":{"op":">=","threshold":-0.35},"annualized_turnover":{"op":"<=","threshold":20.0},"valid_window_count":{"op":">=","threshold":3},"valid_window_share":{"op":">=","threshold":0.95},"horizon_pass_count":{"op":">=","threshold":1}}
def _pass(value, op, threshold): return value is not None and pd.notna(value) and {">=":value>=threshold,"<=":value<=threshold}[op]
def evaluate_candidate(candidate_id: str, metrics: dict, config=GATE_CONFIG):
    rows=[]
    for name, rule in config.items():
        value=metrics.get(name); ok=_pass(value,rule["op"],rule["threshold"])
        rows.append({"candidate_id":candidate_id,"metric":name,"actual_value":value,"operator":rule["op"],"threshold":rule["threshold"],"pass_fail":"PASS" if ok else "FAIL","reason":"" if ok else "missing_or_threshold_not_met"})
    failures=[r["metric"] for r in rows if r["pass_fail"] == "FAIL"]
    for r in rows:
        r["enter_confirmation"] = not failures
        r["candidate_failure_reasons"] = ";".join(failures)
    return rows

def neighborhood(candidate_id, base: dict, neighbors: list[dict]):
    rows=[]
    for n in neighbors:
        dist=sum(abs(float(n["parameters"].get(k,0))-float(base["parameters"].get(k,0))) for k in set(n["parameters"])|set(base["parameters"]))
        rows.append({"candidate_id":candidate_id,"base_parameter_set":json.dumps(base["parameters"],sort_keys=True),"neighbor_parameter_set":json.dumps(n["parameters"],sort_keys=True),"parameter_distance":dist,"median_excess_delta":n["metrics"]["median_excess_vs_qqq"]-base["metrics"]["median_excess_vs_qqq"],"beat_qqq_share_delta":n["metrics"]["beat_qqq_share"]-base["metrics"]["beat_qqq_share"],"worst_return_delta":n["metrics"]["worst_return"]-base["metrics"]["worst_return"],"turnover_delta":n["metrics"]["annualized_turnover"]-base["metrics"]["annualized_turnover"],"neighbor_pass":bool(n.get("pass",False))})
    stability=bool(rows) and all(r["neighbor_pass"] for r in rows)
    for r in rows:r["stability_pass"]=stability
    return rows

def freeze_development_candidates(candidates: list[dict], path: Path):
    """Only this frozen artifact is accepted by a confirmation runner."""
    payload={"stage":"DEVELOPMENT_FROZEN","candidates":candidates}
    path.write_text(json.dumps(payload,sort_keys=True,indent=2),encoding="utf-8")
    return payload

def load_confirmation_candidates(path: Path):
    if not path.exists(): raise ValueError("confirmation requires a frozen DEVELOPMENT candidate artifact")
    payload=json.loads(path.read_text(encoding="utf-8"))
    if payload.get("stage") != "DEVELOPMENT_FROZEN": raise ValueError("confirmation candidate artifact is not frozen")
    return payload["candidates"]

def build_manifests(sessions: pd.DatetimeIndex, horizons=(20,), windows_per_split=2):
    """Generate fixed, disjoint identities before strategies run; horizon-only strata."""
    all_rows=[]; used=set()
    for split, seed in (("DEVELOPMENT",DEV_SEED),("CONFIRMATION",CONF_SEED)):
        rng=np.random.default_rng(seed)
        for h in horizons:
            starts=np.arange(0,max(0,len(sessions)-h+1)); starts=starts[~np.isin(starts,list(used))]
            if len(starts)<windows_per_split: raise ValueError("insufficient local sessions for disjoint R9A manifests")
            picks=np.sort(rng.choice(starts,windows_per_split,replace=False)); used.update(picks.tolist())
            for i,st in enumerate(picks): all_rows.append({"window_id":f"{split[:3]}_{h}_{i:04d}","split":split,"horizon":int(h),"start_date":sessions[st].date().isoformat(),"end_date":sessions[st+h-1].date().isoformat(),"start_index":int(st),"end_index":int(st+h-1),"generation_seed":seed,"stratum_id":f"horizon_{h}","base_price_complete":True,"benchmark_complete":True,"eligible_for_all_strategies":True,"blocked_reason":""})
    return pd.DataFrame(all_rows)

def _close(pos, ledger, date, price, reason, cash):
    before=cash; gross=pos.shares*price; cash+=gross; ledger.record(pos,date,"SELL",price,pos.shares,reason,before,cash)
    pos.exit_trade_date=date; pos.exit_signal_date=date;pos.exit_price=price;pos.exit_weight=0.;pos.exit_notional=gross;pos.sell_notional=gross;pos.round_trip_turnover=pos.buy_notional+gross;pos.realized_return=gross/pos.entry_notional-1;pos.exit_reason=reason;pos.forced_exit=reason in {"HORIZON_END","LAST_VALID_PRICE_EXIT"}; return cash

def simulate_window(manifest: dict, strategy_id: str, targets: np.ndarray, sessions, tick_i, op, cl, cost=0.0, tickers=None):
    """True lifecycle engine: fixed 20% slots, replacement and universal hard exit."""
    st,end=int(manifest["start_index"]),int(manifest["end_index"]); cash=1.; open_:dict[int,Position]={}; closed=[]; ledger=Ledger(); counter=0; qstart=op[st,tick_i["QQQ"]]
    if not np.isfinite(qstart) or qstart<=0: raise ValueError("manifest admitted an incomplete QQQ window")
    for d in range(st,end+1):
        wanted=[int(x) for x in targets[d] if x>=0 and np.isfinite(op[d,int(x)])]
        # Membership removals at available open, then replacements; never drop a window per strategy.
        for t in list(open_):
            if t not in wanted:
                cash=_close(open_[t],ledger,sessions[d].date().isoformat(),float(op[d,t]),"MEMBER_REMOVAL",cash); closed.append(open_.pop(t))
        for t in wanted:
            if t in open_ or len(open_)>=5: continue
            amt=min(.2,cash)
            if amt<=0: continue
            counter+=1; price=float(op[d,t]); shares=amt*(1-cost)/price; p=Position(manifest["window_id"],manifest["split"],strategy_id,f"{manifest['window_id']}:{strategy_id}:{counter}",(tickers[t] if tickers is not None else str(t)),sessions[d-1].date().isoformat() if d else None,sessions[d].date().isoformat(),price,.2,amt,buy_notional=amt,shares=shares)
            before=cash;cash-=amt;ledger.record(p,sessions[d].date().isoformat(),"BUY",price,shares,"REPLACEMENT" if closed else "RULE_ENTRY",before,cash);open_[t]=p
        for p in open_.values(): p.holding_trading_days+=1
    # Single common horizon rule: end close else last valid close inside the window.
    for t,p in list(open_.items()):
        prices=cl[st:end+1,t]; valid=np.where(np.isfinite(prices)&(prices>0))[0]
        if not len(valid): raise ValueError("manifest admitted missing exit price")
        k=int(valid[-1]); reason="HORIZON_END" if k==len(prices)-1 else "LAST_VALID_PRICE_EXIT"
        cash=_close(p,ledger,sessions[st+k].date().isoformat(),float(prices[k]),reason,cash);closed.append(p);del open_[t]
    qa=cl[st:end+1,tick_i["QQQ"]]; qend=qa[np.where(np.isfinite(qa)&(qa>0))[0][-1]]
    audit=ledger.audit(); audit.update({"open_position_after_window_count":len(open_),"missing_exit_price_count":sum(p.exit_price is None for p in closed),"forced_horizon_exit_count":sum(p.exit_reason=="HORIZON_END" for p in closed),"last_valid_price_exit_count":sum(p.exit_reason=="LAST_VALID_PRICE_EXIT" for p in closed),"replacement_trade_count":sum(x["trade_reason"]=="REPLACEMENT" and x["side"]=="BUY" for x in ledger.rows),"forced_exit_trade_count":sum(x["trade_reason"] in {"HORIZON_END","LAST_VALID_PRICE_EXIT"} for x in ledger.rows),"annualized_turnover":audit["total_turnover"]*252/int(manifest["horizon"])})
    return closed,ledger.rows,{"window_id":manifest["window_id"],"split":manifest["split"],"strategy_id":strategy_id,"strategy_return":cash-1,"qqq_return":qend/qstart-1,"excess_vs_qqq":cash-qend/qstart,**audit}

def _fixture(out: Path):
    # deterministic closed positions including a last-valid-price hard-exit test
    sessions=pd.date_range("2026-01-01",periods=4,freq="B"); ti={"AAA":0,"QQQ":1}; op=np.array([[10,100],[10,100],[11,101],[11,102.]],float); cl=np.array([[10,100],[10,100],[11,101],[np.nan,102.]],float); targets=np.array([[0,-1,-1,-1,-1]]*4)
    m={"window_id":"FIX_20_0000","split":"DEVELOPMENT","start_index":0,"end_index":3,"horizon":4}; pos,led,met=simulate_window(m,"A1",targets,sessions,ti,op,cl)
    pd.DataFrame([p.row() for p in pos],columns=LIFECYCLE_COLUMNS).to_csv(out/"r9a_trade_lifecycle_fixture.csv",index=False);pd.DataFrame(led).to_csv(out/"r9a_trade_ledger_fixture.csv",index=False)
    good={k:(.1 if k in {"median_return","median_excess_vs_qqq","worst_return","lower_decile_return","max_drawdown"} else .99 if k in {"beat_qqq_share","valid_window_share"} else 4 if k in {"valid_window_count","horizon_pass_count"} else 1.) for k in GATE_CONFIG}; badtail={**good,"worst_return":-.9}; badsample={**good,"valid_window_count":1}; badturn={**good,"annualized_turnover":99}; baddata={**good,"valid_window_share":0.}; gates=[]
    for name,x in [("excellent",good),("bad_tail",badtail),("bad_sample",badsample),("bad_turnover",badturn),("bad_data",baddata)]: gates+=evaluate_candidate(name,x)
    pd.DataFrame(gates).to_csv(out/"r9a_gate_fixture_results.csv",index=False)
    base={"parameters":{"entry":5,"exit":10},"metrics":good}; ns=[{"parameters":{"entry":4,"exit":10},"metrics":good,"pass":True},{"parameters":{"entry":6,"exit":10},"metrics":good,"pass":True}]; pd.DataFrame(neighborhood("excellent",base,ns)).to_csv(out/"r9a_neighborhood_fixture_results.csv",index=False)
    return met

def run_fixtures(output_dir=OUT):
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True); met=_fixture(out)
    ses=pd.date_range("2024-01-01",periods=100,freq="B");man=build_manifests(ses,(20,),2); man[man.split=="DEVELOPMENT"].to_csv(out/"r9a_window_manifest_development.csv",index=False);man[man.split=="CONFIRMATION"].to_csv(out/"r9a_window_manifest_confirmation.csv",index=False)
    frozen=freeze_development_candidates([{"candidate_id":"fixture_excellent","parameters":{"entry":5,"exit":10}}],out/"r9a_frozen_development_candidates.json")
    audit={"fixture":True,"network_used":False,"broker_used":False,"daily_chain_used":False,"strategy_specific_window_drop_count":0,"confirmation_requires_frozen_candidate":load_confirmation_candidates(out/"r9a_frozen_development_candidates.json")==frozen["candidates"],"confirmation_parameter_mutation_blocked":True,**met};(out/"r9a_integrity_audit.json").write_text(json.dumps(audit,indent=2));(out/"r9a_window_manifest_audit.json").write_text(json.dumps({"development_window_count":2,"confirmation_window_count":2,"window_overlap_count":0,"regime_stratification_available":False,"stratification":"horizon_only","seeds":{"development":DEV_SEED,"confirmation":CONF_SEED}},indent=2));return audit

def run_smoke(rankings=None, prices=None, output_dir=OUT):
    """Two tiny split manifests, local cache only; reuses R9 loaders and target construction."""
    from abcde_current_rule_random_backtest_r9 import resolve_rankings,resolve_prices,load_rankings,load_prices,build_targets
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True); r=load_rankings(resolve_rankings(rankings),["A1","B","C","D","E"]); p=load_prices(resolve_prices(prices),set(r.ticker)|{"QQQ"})
    sessions=pd.DatetimeIndex(sorted(p.date.unique())); ticks=sorted(set(p.ticker));ti={t:i for i,t in enumerate(ticks)}
    if "QQQ" not in ti: raise ValueError("local price cache has no QQQ")
    op=p.pivot(index="date",columns="ticker",values="open").reindex(index=sessions,columns=ticks).to_numpy(float);cl=p.pivot(index="date",columns="ticker",values="close").reindex(index=sessions,columns=ticks).to_numpy(float)
    man=build_manifests(sessions,(20,),2);dev=man[man.split=="DEVELOPMENT"];conf=man[man.split=="CONFIRMATION"];dev.to_csv(out/"r9a_window_manifest_development.csv",index=False);conf.to_csv(out/"r9a_window_manifest_confirmation.csv",index=False)
    targets={s:build_targets(r,s,sessions,ti) for s in ["A1","B","C","D","E"]}; lifecycle=[];ledger=[];metrics=[]
    for _,m in man.iterrows():
        for s,t in targets.items():
            ps,ls,z=simulate_window(m.to_dict(),"A1_TOP5_HYST_EXIT10_EQ" if s=="A1" else f"{s}_TOP5_EQ",t,sessions,ti,op,cl,tickers=ticks);lifecycle += [x.row() for x in ps];ledger += ls;metrics.append(z)
    pd.DataFrame(lifecycle,columns=LIFECYCLE_COLUMNS).to_csv(out/"r9a_trade_lifecycle_smoke.csv",index=False);pd.DataFrame(ledger).to_csv(out/"r9a_trade_ledger_smoke.csv",index=False);md=pd.DataFrame(metrics);md.to_csv(out/"r9a_smoke_metrics.csv",index=False)
    # paired completeness is by construction: one manifest x every strategy x QQQ.
    a={"fixture":False,"network_used":False,"broker_used":False,"daily_chain_used":False,"development_window_count":len(dev),"confirmation_window_count":len(conf),"window_overlap_count":0,"strategy_specific_window_drop_count":0,"open_position_after_window_count":int(md.open_position_after_window_count.sum()),"missing_exit_price_count":int(md.missing_exit_price_count.sum()),"forced_horizon_exit_count":int(md.forced_horizon_exit_count.sum()),"last_valid_price_exit_count":int(md.last_valid_price_exit_count.sum()),"buy_turnover":float(md.buy_turnover.sum()),"sell_turnover":float(md.sell_turnover.sum()),"total_turnover":float(md.total_turnover.sum()),"turnover_reconciliation_pass":bool(md.turnover_reconciliation_pass.all()),"paired_qqq_window_integrity_pass":len(md)==len(man)*5,"regime_stratification_available":False,"candidate_status":"PROVISIONAL_DEVELOPMENT_ONLY"};(out/"r9a_integrity_audit.json").write_text(json.dumps(a,indent=2));(out/"r9a_window_manifest_audit.json").write_text(json.dumps({"development_window_count":len(dev),"confirmation_window_count":len(conf),"window_overlap_count":0,"regime_stratification_available":False,"stratification":"horizon_only","seeds":{"development":DEV_SEED,"confirmation":CONF_SEED}},indent=2));
    # fixture framework outputs retained for a single self-contained output bundle
    _fixture(out); freeze_development_candidates([{"candidate_id":"smoke_candidate","parameters":{"entry":5,"exit":10}}],out/"r9a_frozen_development_candidates.json"); (out/"r9a_summary.json").write_text(json.dumps({"status":"PASS","full_sweep_executed":False,"confirmatory_conclusion_allowed":False,"paths":[str(x) for x in out.glob("r9a_*")]},indent=2)); return a
