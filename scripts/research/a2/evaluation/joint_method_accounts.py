"""V24 fixed one-layer method accounts on the immutable continuous engine.

Only orchestration is added: no execution, price, selector or registry clone.
All scientific choices are frozen before the first economic account replay.
"""
from __future__ import annotations
import argparse
from dataclasses import replace
import hashlib
import json
import time
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from scripts.research.a2.data.joint_input_binding import load_training_inputs, guard_parquet
from scripts.research.a2.evaluation.joint_method_coverage import JointMethodCoverage, mature_training_mask
from scripts.research.a2.evaluation.joint_method_stages import prepare_market, task_writer, RISK_ROWS
from scripts.research.a2.evaluation.joint_execution_resume import digest
from scripts.research.a2.evaluation.continuous_research_account import run_continuous_account
from scripts.research.a2.inference.joint_portfolio_policy import JointResearchPolicy
from scripts.research.a2.inference.joint_stateful_policy import RuleStatefulPolicy, SequentialPolicy
from scripts.research.a2.portfolio import joint_allocation_methods as allocation
from scripts.research.a2.risk.joint_risk_estimators import risk_matrix

YEARS = (2023,2024,2025)
ANCHOR = "PTO_ANCHOR_EQUAL_5D_LW_ROBUST_MV"
CONTROLS = ("CONTROL_RAW_A2_POLICY","JOINT_SIMPLE_EQUAL")
PARAMETERS = dict(
    optimizer=dict(risk_penalty=4.,uncertainty_penalty=.5,max_q=.1,max_positions=20,
                   iterations=128,tolerance=2e-6,turnover_cost=0),
    action=dict(partial_rebalance=.5,full_action_ablation=1.),
    gross=dict(fixed=1.,volatility_target_annual=.10))
ALLOCATION_ROWS = dict(zip(range(68,90), allocation.ALLOCATION_METHODS[:22]))
NATIVE_ROWS = {
 1:"OWN_Ridge",2:"elastic",3:"huber",4:"logistic",5:"OWN_HGB",6:"xgb",7:"lgb",8:"cat",
 9:"rf",10:"extra",11:"ebm",12:"mlp",13:"resnet",14:"fttransformer",15:"tcn",
 16:"lstm",17:"gru",18:"xgb_rank",19:"lgb_rank",20:"linear_q",21:"hgb_q",22:"xgb_q",
 23:"lgb_q",24:"cat_q",25:"mlp_q",26:"ngboost",27:"gaussian_mlp",28:"cat_uncertainty",
 29:"svc",45:"kmeans_ridge",46:"gmm_ridge",47:"iforest_ridge",48:"pca_ridge",49:"fa_ridge"}
META_ROWS = dict(zip(range(32,45), (
 "equal","median","fixed_weighted","nnls","simplex","ridge_stack","elastic_stack",
 "hgb_stack","mlp_stack","linear_gate","mlp_gate","ridge_then_hgb","hgb_then_ridge")))
ALIASES = {61:50,76:None,78:77,80:81,83:76,86:75,87:85,90:75,
           96:76,99:76,100:76,101:76,102:76,104:103,106:76}

def json_safe(value):
    if isinstance(value,dict):return {str(k):json_safe(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [json_safe(v) for v in value]
    if isinstance(value,np.ndarray):return json_safe(value.tolist())
    if isinstance(value,(float,np.floating)):return float(value) if np.isfinite(value) else None
    if isinstance(value,np.integer):return int(value)
    if isinstance(value,np.bool_):return bool(value)
    return value

def sha_json(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=str,allow_nan=False).encode()).hexdigest()

def catalogue():
    roles = {}
    def add(pid,**kwargs):
        roles[pid] = dict(forecast="EQUAL",risk="LW",allocation="robust_mean_variance",
                         gross="fixed",rho=.5,control=None)
        roles[pid].update(kwargs)
    for control in CONTROLS:
        roles[control] = dict(forecast="RAW_CONTROL",kind="raw" if control==CONTROLS[0] else "simple")
    add(ANCHOR)
    for row,kind in RISK_ROWS:
        if row!=61:
            add(f"M{row:03d}",risk=kind)
    for row,method in ALLOCATION_ROWS.items():
        if row not in ALIASES:
            add(f"M{row:03d}",allocation=method)
    for row,control in [(91,"l1_turnover"),(92,"l2_turnover")]:
        add(f"M{row:03d}",allocation=control)
    for row,control in [(93,"turnover_limit"),(94,"no_trade_band"),(95,"buy_hold_hysteresis"),(97,"minimum_trade")]:
        add(f"M{row:03d}",control=control)
    add("M103",gross="volatility_targeting")
    add("M105",gross="dynamic")
    for row,name in NATIVE_ROWS.items():
        add(f"M{row:03d}",forecast=name)
    for row,name in META_ROWS.items():
        add(f"M{row:03d}",forecast=("RESID_" if row>=43 else "META_")+name)
    for row,algorithm in [(30,"REINFORCE"),(31,"PPO")]:
        add(f"M{row:03d}",algorithm=algorithm)
        add(f"M{row:03d}_ZERO",algorithm=algorithm,zero=True)
    return roles

def resolve_alias(row):
    seen=set()
    while row in ALIASES:
        if row in seen:raise ValueError("Alias cycle")
        seen.add(row);row=ALIASES[row]
        if row is None:return ANCHOR
    return f"M{row:03d}"

def core_ids():
    return [p for p in catalogue() if p in CONTROLS or p==ANCHOR or
            (p.startswith("M") and (50<=int(p[1:4])<=106 or int(p[1:4]) in (1,5,30,31)))]

def evaluation_market(market):
    start=int(market.dates.searchsorted(pd.Timestamp("2023-01-01")))
    dates=market.dates[start:]
    if dates.empty or dates[-1]>=pd.Timestamp("2026-01-01"):
        raise ValueError("Evaluation is strictly pre2026")
    names=("open","close","quality","adv","input_present","new_buy_eligible",
           "signal_mask","buy_restricted","sell_restricted","row_present")
    kwargs={name:getattr(market,name)[start:].copy() for name in names}
    kwargs.update(dates=dates,signal_asof=market.signal_asof[start:],
                  operational_exits={d:e for d,e in market.operational_exits.items() if d>=dates[0]})
    if market.known_restrictions_evidence is not None:
        evidence=pd.DataFrame(market.known_restrictions_evidence)
        kwargs["known_restrictions_evidence"]=evidence.loc[pd.to_datetime(evidence.signal_date).ge(dates[0])]
    return replace(market,**kwargs),start

def scenario_inputs(frame, tickers,mean_states=None):
    """No fit/subsample. Past mature eligible labels only; coverage is as-of."""
    tables={};known={};receipts={}
    for year in YEARS:
        train=frame.loc[mature_training_mask(frame,pd.Timestamp(year,1,1))]
        table=train.pivot(index="signal_date",columns="ticker",values="y_open5").reindex(columns=tickers)
        available=(table.count()>=30).to_numpy()
        values=table.to_numpy(float)
        mean_dependency={"synthetic_only_estimate":True}
        if mean_states is None:
            means=table.mean().to_numpy(float)
        else:
            state,dependency=mean_states[year]
            if state.status!="FITTED" or not pd.DatetimeIndex(state.fitted_dates).equals(table.index):
                raise ValueError("Scenario imputer dates do not match frozen risk preprocessing")
            if tuple(table.columns[available])!=state.estimated_assets:
                raise ValueError("Scenario imputer domain differs from frozen risk preprocessing")
            means=np.zeros(len(tickers));means[available]=state.fitted_state["mean"]
            mean_dependency={"status":"EXACT_REUSE_COUNTED_RISK_MEAN_PREPROCESSOR",
                             "artifact_dependency":dependency,"new_fit_states":0,
                             "state_sha256":hashlib.sha256(np.asarray(state.fitted_state["mean"],float).tobytes()).hexdigest()}
        values=np.where(np.isfinite(values),values,np.where(available,means,0)[None,:])
        if not np.isfinite(values).all() or len(table)<30:raise ValueError("Insufficient mature scenarios")
        tables[year]=values;known[year]=available
        receipts[str(year)]=dict(rows=len(table),known_assets=int(available.sum()),mean_preprocessor=mean_dependency,
            label_max=str(train.label_mature_date.max()),signal_max=str(train.signal_date.max()),
            sha256=hashlib.sha256(values.tobytes()).hexdigest(),
            missing="observed prior column mean, no cross-sectional sampling",
            unestimated="zero computational padding; forbidden forecast/exposure; never used as empirical zero risk")
    for previous,current in zip(YEARS,YEARS[1:]):
        if np.any(known[previous]&~known[current]):raise ValueError("Scenario-known asset set must not contract")
    return tables,known,receipts

def with_effective_event_quality(market,replay_kwargs):
    """Mirror the common wrapper's already-bound effective-day quote block only."""
    quality=market.quality.copy()
    tickers=pd.Index(market.tickers)
    for event in replay_kwargs.get("unsupported_events",()):
        day=market.dates.get_indexer([pd.Timestamp(event["effective_date"])])[0]
        ticker=tickers.get_indexer([str(event["ticker"])])[0]
        if day>=0 and ticker>=0:quality[day,ticker]=True
    return replace(market,quality=quality)

def legal_new_buy_domain(market):
    legal=(market.new_buy_eligible&market.input_present&market.row_present&~market.quality
           &~market.buy_restricted&np.isfinite(market.close)&(market.close>0))
    for day,actions in market.operational_exits.items():
        index=market.dates.get_indexer([pd.Timestamp(day)])[0]
        if index>=0:
            for ticker,evidence in actions.items():
                available=pd.Timestamp(evidence.known_at);asof=pd.Timestamp(market.signal_asof[index])
                if available<=asof:
                    found=np.flatnonzero(market.tickers==ticker)
                    legal[index,found]=False
    return legal

def reference_portfolios(market,scores):
    result={}
    legal=legal_new_buy_domain(market)
    for day in range(len(market.dates)):
        valid=legal[day]&np.isfinite(scores[day])
        ids=np.flatnonzero(valid)
        selected=ids[np.lexsort((market.tickers[ids],-scores[day,ids]))][:20]
        reference=np.zeros(len(market.tickers))
        if len(selected):reference[selected]=1/len(selected)
        result[day]=reference
    return result

def artifact_from_status(task,kind,year):
    record=next((r for r in task.status["records"] if r["identity"]["kind"]==kind and
                 r["identity"]["cutoff_exclusive"]==f"{year}-01-01"),None)
    if not record or record["status"]!="FIT_COMPLETE":
        return None,dict(status="BLOCKED_NO_COMPLETED_ARTIFACT",kind=kind,year=year)
    path=Path(record["artifact"])
    if not path.exists() or digest(path)!=record["sha256"]:raise ValueError("Fitted artifact identity changed")
    return joblib.load(path),dict(status="VERIFIED",kind=kind,year=year,sha256=record["sha256"])

def risk_inputs(task,tickers):
    matrices={};reports={};dependencies={}
    for _,kind in RISK_ROWS:
        if kind=="HISTVOL":continue
        for year in YEARS:
            obj,report=artifact_from_status(task,"risk_"+kind,year)
            if obj is not None:
                report.update(bundle_status=obj.status)
                if obj.status=="FITTED":
                    matrix,metadata=risk_matrix(obj,tickers,return_metadata=True)
                    if metadata["return_horizon_sessions"]!=5:raise ValueError("Risk horizon mismatch")
                    matrices[(year,kind)]=matrix;report["risk_metadata"]=metadata
                else:report.update(status=obj.status,reason=obj.failure_reason)
            reports[(year,kind)]=report
            dependencies[f"{year}:{kind}"]=report
    return matrices,reports,dependencies

def forecast_inputs(task,market,inputs,start,name):
    if name in inputs["mu"]:
        return inputs["mu"][name][start:].copy(),inputs["sigma"][name][start:].copy(),True,{"cache_forecast":name}
    if name.startswith("OWN_"):
        key=name[4:]
        return inputs["mu"][key][start:].copy(),inputs["sigma"][key][start:].copy(),True,{"own_initial_forecast":key}
    prefix="B_META_" if name.startswith("META_") else "B_RESID_" if name.startswith("RESID_") else "B_NATIVE_"
    leaf=name[5:] if name.startswith("META_") else name[6:] if name.startswith("RESID_") else name
    shape=(len(market.dates),len(market.tickers));mu=np.full(shape,np.nan);sigma=mu.copy()
    di=pd.Index(market.dates);ti=pd.Index(market.tickers);dependencies={};complete=True
    for year in YEARS:
        relative=f"OOF/{prefix}{leaf}_{year}.parquet"
        file=task.out(relative);receipt=task.out(f"receipts/{prefix}{leaf}_{year}.json")
        if not file.exists() or not receipt.exists():
            complete=False;dependencies[str(year)]={"status":"MISSING_OR_FAILED_DEPENDENCY"}
            continue
        report=task.read(str(receipt.relative_to(task.root)))
        expected=report.get("sha256")
        if not expected or digest(file)!=expected:raise ValueError("OOF forecast identity changed:"+relative)
        parquet,_=guard_parquet(file,expected,["signal_date","source_fit_cutoff"])
        block=parquet.read(columns=["signal_date","ticker","source_fit_cutoff","mu","sigma"]).to_pandas()
        block.signal_date=pd.to_datetime(block.signal_date);block.source_fit_cutoff=pd.to_datetime(block.source_fit_cutoff)
        if block.duplicated(["signal_date","ticker"]).any() or not block.signal_date.dt.year.eq(year).all():
            raise ValueError("OOF coordinates invalid")
        if block.source_fit_cutoff.isna().any() or not block.source_fit_cutoff.eq(pd.Timestamp(year,1,1)).all():
            raise ValueError("OOF annual fit lineage absent or changed")
        if block.source_fit_cutoff.gt(block.signal_date).any():raise ValueError("OOF fit cutoff after signal")
        ri=di.get_indexer(block.signal_date);ci=ti.get_indexer(block.ticker);good=(ri>=0)&(ci>=0)
        mu[ri[good],ci[good]]=block.mu.to_numpy(float)[good]
        sigma[ri[good],ci[good]]=block.sigma.to_numpy(float)[good]
        dependencies[str(year)]=dict(status="VERIFIED",sha256=expected,receipt_sha256=digest(receipt))
    return mu,sigma,complete,dependencies

class AnnualSequential:
    def __init__(self,policies):
        self.policies=policies
    def __call__(self,day,ctx):
        policy=self.policies.get(ctx.signal_date.year)
        if policy is None:
            from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision
            return TargetDecision(np.zeros_like(ctx.current_weights),np.zeros_like(ctx.decision_mask), "BLOCKED_ANNUAL_RL")
        return policy(day,ctx)

class ScenarioCoverageGate:
    def __init__(self,base,known):
        self.base,self.known=base,known
    def __call__(self,day,ctx):
        supported=self.known[ctx.signal_date.year]
        if np.any((ctx.current_units[0]>1e-10)&~supported):
            raise AssertionError("Computationally padded unknown scenario has a held exposure")
        result=self.base(day,ctx)
        if np.any(result.weights[0,~supported]>1e-10):
            raise AssertionError("Unestimated scenario used as zero empirical risk")
        return result

class ScientificCoveragePolicy:
    """Qualify a complete forecast domain; missing forecasts retain engine semantics."""
    def __init__(self,base,mu,sigma,known=None):
        self.base,self.mu,self.sigma,self.known=base,mu,sigma,known
        self.records=[];self.missing_rows=0;self.missing_held_rows=0
    def __call__(self,day,ctx):
        held=ctx.current_units[0]>1e-10
        required=(np.asarray(ctx.decision_mask[0],bool)&(np.asarray(ctx.buy_allowed[0],bool)|held)
                  &~np.asarray(ctx.operational_mask[0],bool))
        if self.known is not None:required=required&self.known[ctx.signal_date.year]
        finite=np.isfinite(self.mu[day])&np.isfinite(self.sigma[day])&(self.sigma[day]>=0)
        missing=required&~finite
        self.missing_rows+=int(missing.sum());self.missing_held_rows+=int((missing&held).sum())
        self.records.append(dict(signal_date=ctx.signal_date,required_rows=int(required.sum()),
            missing_rows=int(missing.sum()),missing_held_rows=int((missing&held).sum())))
        return self.base(day,ctx)

def static_forecast_coverage(market,mu,sigma,known=None):
    required=legal_new_buy_domain(market)
    if known is not None:
        for year in YEARS:required[market.dates.year==year]&=known[year][None,:]
    finite=np.isfinite(mu)&np.isfinite(sigma)&(sigma>=0)
    missing=required&~finite
    return dict(required_new_rows=int(required.sum()),missing_new_rows=int(missing.sum()),
       complete=not missing.any(),
       by_year={str(y):dict(required=int(required[market.dates.year==y].sum()),
              missing=int(missing[market.dates.year==y].sum())) for y in YEARS})

def freeze_accounts(task):
    from scripts.research.a2.evaluation import continuous_research_account
    from scripts.research.a2.inference import joint_portfolio_policy,joint_stateful_policy
    from scripts.research.a2.risk import joint_risk_estimators
    from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2 import fast_account,optimization
    from scripts.v22 import corporate_action_transition_r1
    sources={str(Path(p).resolve()):digest(p) for p in [
      __file__,continuous_research_account.__file__,joint_portfolio_policy.__file__,
      joint_stateful_policy.__file__,allocation.__file__,joint_risk_estimators.__file__,fast_account.__file__,
      optimization.__file__,corporate_action_transition_r1.__file__]}
    freeze=dict(status="POLICY_FROZEN_BEFORE_ECONOMIC_REPLAYS",parameters=PARAMETERS,
       allocation_spec=allocation.SPEC,catalogue=catalogue(),aliases={f"M{k:03d}":resolve_alias(k) for k in ALIASES},
       blocked={"M098":"INTEGER_EXECUTION_SECONDARY_INCOMPATIBLE_WITH_FRACTIONAL_COMMON_ACCOUNT"},
       anchor="EQUAL B five-session Ridge/HGB; LW risk; robust mean variance; independent fixed G1; selected support (incumbents and entrants) partial rho0.5, excluded incumbent SELL; independent composition Gross vs action target exposure both reported; no Top20 opportunity prefilter",
       native_identity="C date-balanced <=40000 sampled Raw multi-horizon native fits; B bridges use all legal prior5dOOF; not B full-population native refit",
       meta_members=["ridge","hgb","xgb_rank","logistic","cat_uncertainty"],
       meta_fixed_weights=[.30,.25,.20,.15,.10],
       meta_estimation="first11 prior matured native bridge OOF; fixed source configs; chronological probe residual sigma; secondary residual own5d base + PIT32",
       source_sha256=sources,input_binding_sha256=task.input_sha,run_config_sha256=digest(task.out("RUN_CONFIG.json")),
       evaluation_years=list(YEARS),initial_state="one empty USD3000 account at2023 start, never year reset",
       scenario_definition="all prior matured eligible5d labels, count>=30 as-of fit cutoff; exact reuse already-counted LW annual mean preprocessing with same dates/domain, no new fit; unknownnames forecasts forbidden; zero padding computational only",
       reference="stateless legal-new-buy Raw score Top20 (known close/quality/row/restriction/operational gates), normalized equal q; not incumbent Raw account target",
       scientific_coverage_gate="all required current legal PIT32 new-buy forecast rows finite mu/sigma>=0; actual held decision rows likewise; missing/partial dependencies excluded from finalist; scenario declared earlier count>=30 filter allowed; annual lineage equals corresponding Jan1 notNaT",
       selection=task.parameters["comparison"],economic_result_tuning=False,test2026_reads=0)
    relative="receipts/ACCOUNT_POLICY_FREEZE.json"
    if task.out(relative).exists():
        if task.read(relative)!=freeze:raise ValueError("Account policy freeze changed after replay")
    else:task.write(relative,freeze)
    return freeze

def account_audits_passed(audit):
    errors=("cash_identity_error_max","cost_identity_error_max","self_finance_error_max","nav_identity_error_max")
    return (all(k in audit and np.isfinite(audit[k]) and audit[k]<=1e-5 for k in errors)
            and audit.get("capacity_violations") == 0 and audit.get("next_open_violations") == 0
            and audit.get("max_actual_names",21)<=20 and np.isfinite(audit.get("minimum_cash",np.nan))
            and audit.get("minimum_cash",-1)>=-1e-7)

def sequence_diagnostics(records,raw,tickers):
    q=np.asarray(raw.get("q",np.zeros(len(tickers))),float)
    positive=q>1e-10
    records.append(dict(path_id=raw["path_id"],signal_date=raw["signal_date"],
        status=raw["status"],full_candidate_count=len(raw["modeled_tickers"]),
        gross_target=raw.get("gross_target",np.nan),gross_requested=raw.get("gross_requested",np.nan),
        composition_tickers=tickers[positive].tolist(),relative_weights=q[positive].tolist(),
        failure_reason=raw.get("reason",""),global_optimum_claim=False))

def path_metrics(replay,pid,scope_complete,policy_records,capital=3000):
    daily=replay.daily.sort_values("date").copy()
    qualified=(scope_complete and daily.accounting_qualified.astype(bool).all()
               and np.isfinite(daily.certified_nav).all() and (daily.certified_nav>0).all()
               and account_audits_passed(replay.audit))
    nav=daily.certified_nav.to_numpy(float)
    valid=qualified
    returns=daily.net_return.dropna().to_numpy(float)
    metrics=dict(path_id=pid,scope_complete=bool(scope_complete),accounting_qualified=bool(daily.accounting_qualified.all()),
       required_audits_passed=account_audits_passed(replay.audit),eligible_for_selection=bool(qualified),
       final_certified_nav=float(nav[-1]) if qualified else None,
       engine_final_nav_diagnostic=float(daily.nav.iloc[-1]),uncertified_engine_nav_not_ranked=True,
       sessions=len(daily),all_cash_days=int((daily.gross_exposure<=1e-10).sum()),
       mean_gross=float(daily.gross_exposure.mean()),mean_cash=float(daily.cash.mean()),
       total_turnover=float(daily.turnover.sum()),corporate_action_exceptions=len(replay.accounting_exceptions),
       policy_fallbacks=int(sum(r.get("status")=="FALLBACK_PRESERVE_UNITS" for r in policy_records)),
       annual_returns={},sharpe=None,max_drawdown=None)
    if valid:
        pathnav=np.r_[capital,nav];ret=pathnav[1:]/pathnav[:-1]-1
        metrics["sharpe"]=float(np.sqrt(252)*ret.mean()/ret.std(ddof=1)) if ret.std(ddof=1)>0 else None
        metrics["max_drawdown"]=float(np.min(pathnav/np.maximum.accumulate(pathnav)-1))
        previous=capital
        for year,group in daily.groupby(daily.date.dt.year):
            endpoint=float(group.certified_nav.iloc[-1]);metrics["annual_returns"][str(year)]=endpoint/previous-1;previous=endpoint
        invested=daily.gross_exposure.gt(1e-10).to_numpy()
        metrics["conditional_invested_daily_return"]=float(np.mean(ret[invested])) if invested.any() else None
    return metrics

def verify_account_record(task,record):
    relative=record["receipt"];receipt=task.read(relative)
    if digest(task.out(relative))!=record["receipt_sha256"]:raise ValueError("Account receipt changed")
    if receipt["identity"]!=record["identity"] or receipt["metrics"]!=record["metrics"]:
        raise ValueError("Account identity or metrics changed")
    for item in receipt["artifacts"].values():
        path=Path(item["path"]).resolve()
        if not path.is_relative_to(task.root) or digest(path)!=item["sha256"]:
            raise ValueError("Account artifact changed or escapes task root")
    return receipt

def save_replay(task,pid,replay,diagnostics,record):
    destination=task.out("ledgers/"+pid);destination.mkdir(exist_ok=True)
    artifacts={}
    for name in ("daily","positions","orders","fills","execution_results","contexts","operational_actions","accounting_exceptions"):
        frame=getattr(replay,name)
        path=destination/(name+".parquet");frame.to_parquet(path,index=False)
        artifacts[name]=dict(path=str(path),sha256=digest(path),rows=len(frame))
    frame=pd.DataFrame(diagnostics)
    path=destination/"policy_diagnostics.parquet";frame.to_parquet(path,index=False)
    artifacts["policy_diagnostics"]=dict(path=str(path),sha256=digest(path),rows=len(frame))
    state=destination/"final_state.joblib";joblib.dump(replay.final_state,state,compress=3)
    artifacts["final_state"]=dict(path=str(state),sha256=digest(state))
    coverage_path=task.out("ledgers/"+pid+"_forecast_coverage.parquet")
    artifacts["forecast_coverage"]=dict(path=str(coverage_path),sha256=digest(coverage_path))
    shared=json_safe({k:replay.metadata[k] for k in ("corporate_action_receipts","corporate_action_exceptions")})
    shared_relative="receipts/ACCOUNT_EVENT_SHARED.json"
    if task.out(shared_relative).exists():
        if task.read(shared_relative)!=shared:raise ValueError("Shared account event metadata changed")
    else:task.write(shared_relative,shared)
    artifacts["shared_event_binding"]=dict(path=str(task.out(shared_relative)),sha256=digest(task.out(shared_relative)))
    metadata={k:v for k,v in replay.metadata.items() if k not in shared}
    metadata["corporate_action_binding_receipt"]=artifacts["shared_event_binding"]
    metrics=json_safe(path_metrics(replay,pid,record["scope_complete"],diagnostics))
    task.write("receipts/ACCOUNT_"+pid+".json",json_safe(dict(
        status="CONTINUOUS_REPLAY_COMPLETE",identity=record["identity"],artifacts=artifacts,
        metadata=metadata,audit=replay.audit,prefix_identity=replay.prefix_identity,
        metrics=metrics,forecast_coverage=record.get("forecast_coverage",{}),accounting_exceptions=replay.accounting_exceptions.to_dict("records"),
        test2026_reads=0)))
    record.update(status="CONTINUOUS_REPLAY_COMPLETE",metrics=metrics,
                  receipt="receipts/ACCOUNT_"+pid+".json",receipt_sha256=digest(task.out("receipts/ACCOUNT_"+pid+".json")))
    return metrics

def run_accounts(root,phase):
    task=JointMethodCoverage(root);freeze_accounts(task)
    inputs=prepare_market(root);market,start=evaluation_market(inputs["market"])
    market=with_effective_event_quality(market,inputs["replay_kwargs"])
    covariances,risk_reports,riskdeps=risk_inputs(task,market.tickers)
    frame=load_training_inputs(task.read("INPUT_BINDING.json"))
    mean_states={year:artifact_from_status(task,"risk_LW",year) for year in YEARS}
    if any(value[0] is None for value in mean_states.values()):raise ValueError("Missing frozen scenario mean preprocessor")
    scenarios,scenario_known,scenario_receipts=scenario_inputs(frame,market.tickers,mean_states)
    reference=reference_portfolios(market,inputs["mu"]["RAW_CONTROL"][start:])
    task.write("receipts/ACCOUNT_ASOF_SCENARIOS.json",dict(status="ALL_MATURE_ROWS_NO_SAMPLING",
       years=scenario_receipts,input_binding_sha256=task.input_sha,test2026_reads=0))
    roles=catalogue();wanted=core_ids() if phase=="core" else [p for p in roles if p not in core_ids()]
    results=[]
    for pid in wanted:
        spec=roles[pid];mu,sigma,complete,forecastdeps=forecast_inputs(task,market,inputs,start,spec["forecast"])
        deps=dict(forecast=forecastdeps,market_cache_sha256=digest(task.out("cache/market_and_inputs.joblib")),
                  input_binding_sha256=task.input_sha,policy_freeze_sha256=digest(task.out("receipts/ACCOUNT_POLICY_FREEZE.json")))
        is_sequence="algorithm" in spec
        if spec.get("kind") is None and not is_sequence:
            deps["risk"]={str(y):riskdeps[f"{y}:{spec['risk']}"] for y in YEARS}
            complete=complete and all((y,spec["risk"]) in covariances for y in YEARS)
        diagnostics=[]
        callback=lambda block:diagnostics.extend(block.to_dict("records"))
        local_mu=mu.copy();local_sigma=sigma.copy()
        if spec.get("allocation") in ("mean_cvar","mean_es","kelly","log_growth","mean_semivariance"):
            for year in YEARS:
                bad=~scenario_known[year];days=market.dates.year==year
                local_mu[np.ix_(days,bad)]=np.nan;local_sigma[np.ix_(days,bad)]=np.nan
            deps["scenarios"]=scenario_receipts
        if spec.get("allocation") in ("reference_regularization","tracking_error"):
            deps["reference"]="Frozen Raw signal scores; common market receipt binds source"
        if is_sequence:
            from scripts.research.a2.evaluation.joint_sequential_training import bind_runtime
            bind_runtime()
            policies={}
            deps["rl"]={}
            for year in YEARS:
                bundle,report=artifact_from_status(task,"sequential_"+spec["algorithm"],year)
                deps["rl"][str(year)]=report
                key="zero_bundle" if spec.get("zero") else "trained_bundle"
                if bundle is None or bundle.get("status")!="FIT_COMPLETE" or key not in bundle:
                    complete=False;continue
                policies[year]=SequentialPolicy(bundle[key],inputs["feature_cube"][start:],mu,sigma,sampled=False,
                        on_diagnostics=lambda raw:sequence_diagnostics(diagnostics,raw,market.tickers))
            policy=AnnualSequential(policies)
        elif spec.get("kind"):
            policy=JointResearchPolicy([pid],mu[:,None,:],sigma[:,None,:],covariances,
                roles={pid:{"kind":spec["kind"]}},parameters=PARAMETERS,on_diagnostics=callback)
        else:
            policy=allocation.JointAllocationPolicy([pid],local_mu[:,None,:],local_sigma[:,None,:],covariances,
                roles={pid:{"risk":spec["risk"],"rho":spec["rho"]}},parameters=PARAMETERS,
                method=spec["allocation"],gross_method=spec["gross"],scenarios_by_year=scenarios,
                reference_by_day=reference,on_diagnostics=callback)
            if spec.get("control")=="buy_hold_hysteresis":
                policy=RuleStatefulPolicy(policy,local_mu[:,None,:],local_sigma[:,None,:],
                                         no_trade_band=0,minimum_trade_usd=0,hysteresis=.5)
            elif spec.get("control"):
                policy=allocation.TradingControlPolicy(policy,spec["control"])
            if spec["allocation"] in ("mean_cvar","mean_es","kelly","log_growth","mean_semivariance"):
                policy=ScenarioCoverageGate(policy,scenario_known)
        known_domain=scenario_known if spec.get("allocation") in ("mean_cvar","mean_es","kelly","log_growth","mean_semivariance") else None
        forecast_coverage=static_forecast_coverage(market,local_mu,local_sigma,known_domain)
        complete=complete and forecast_coverage["complete"]
        deps["forecast_coverage"]=forecast_coverage
        coverage_policy=ScientificCoveragePolicy(policy,local_mu,local_sigma,known_domain)
        identity=dict(path_id=pid,spec=spec,dependencies=deps,
                      account=inputs["account"],first_session=str(market.dates[0].date()),
                      last_session=str(market.dates[-1].date()),scope_complete=bool(complete))
        records=task.status.setdefault("account_records",[])
        old=next((r for r in records if r["identity"]["path_id"]==pid),None)
        if old:
            if old["identity"]!=identity:raise ValueError("Account input identity changed; retained attempt cannot silently rerun:"+pid)
            if old["status"]=="CONTINUOUS_REPLAY_COMPLETE":
                verify_account_record(task,old)
                results.append(old["metrics"]);continue
            if old["status"]=="CONTINUOUS_REPLAY_STARTED":
                old.update(status="INTERRUPTED_FAILURE_RETAINED",reason="Prior writer interrupted; no silent replay or budget reset")
                task.checkpoint()
            results.append(dict(path_id=pid,status=old["status"]));continue
        if task.status["account_paths"]>=task.parameters["budget"]["max_account_paths"]:
            raise RuntimeError("Account path budget exhausted")
        # No usable scientific dependency => formal blocked attempt, not a cash-only fake fit.
        if not np.isfinite(mu).any() or (is_sequence and not policies) or (not is_sequence and spec.get("kind") is None
                                      and not any((y,spec["risk"]) in covariances for y in YEARS)):
            blocked=dict(identity=identity,status="BLOCKED_ALL_REQUIRED_DEPENDENCIES",scope_complete=False)
            records.append(blocked);task.checkpoint()
            results.append(dict(path_id=pid,status=blocked["status"]));continue
        record=dict(identity=identity,status="CONTINUOUS_REPLAY_STARTED",scope_complete=bool(complete))
        records.append(record);task.status["account_paths"]+=1;task.checkpoint()
        print(json.dumps({"status":"ACCOUNT_STARTED","path_id":pid,"scope_complete":bool(complete)}),flush=True)
        begun=time.monotonic()
        def bounded_policy(day,ctx):
            if time.monotonic()-begun>task.parameters["budget"]["max_one_method_wall_seconds"]:
                raise TimeoutError("Fixed wall budget reached; retained failure, no config expansion")
            return coverage_policy(day,ctx)
        try:
            with threadpool_limits(limits=2):
                replay=run_continuous_account(market,[pid],bounded_policy,inputs["account"],**inputs["replay_kwargs"])
            record["scope_complete"]=bool(record["scope_complete"] and coverage_policy.missing_rows==0)
            record["forecast_coverage"]=dict(static=forecast_coverage,
                 runtime_missing_rows=coverage_policy.missing_rows,
                 runtime_missing_held_rows=coverage_policy.missing_held_rows)
            pd.DataFrame(coverage_policy.records).to_parquet(task.out("ledgers/"+pid+"_forecast_coverage.parquet"),index=False)
            result=save_replay(task,pid,replay,diagnostics,record);results.append(result)
        except Exception as exc:
            record.update(status="CONTINUOUS_REPLAY_FAILED",error=repr(exc))
            task.write("receipts/ACCOUNT_"+pid+"_FAILED.json",json_safe(dict(identity=identity,error=repr(exc),
                       partial_diagnostics=diagnostics,test2026_reads=0)))
            results.append(dict(path_id=pid,status=record["status"],error=repr(exc)))
        record["seconds"]=time.monotonic()-begun
        task.status["status"]="REAL_CONTINUOUS_ACCOUNTS_IN_PROGRESS";task.checkpoint()
        print(json.dumps({"status":record["status"],"path_id":pid,"seconds":round(record["seconds"],2)}),flush=True)
    task.write("receipts/ACCOUNT_PHASE_"+phase.upper()+".json",dict(status="PHASE_ATTEMPTS_COMPLETE",
                paths=wanted,results=results,test2026_reads=0))
    return results

def select_finalist(metrics):
    by_id={r["path_id"]:r for r in metrics}
    qualified_controls=all(p in by_id and by_id[p]["eligible_for_selection"] for p in CONTROLS)
    candidates=[r for r in metrics if r["path_id"] not in CONTROLS and not r["path_id"].endswith("_ZERO")
                and r["eligible_for_selection"]]
    admitted=[]
    if qualified_controls:
        threshold=max(by_id[p]["final_certified_nav"] for p in CONTROLS)
        admitted=[r for r in candidates if r["final_certified_nav"]>threshold]
    admitted.sort(key=lambda r:(-r["final_certified_nav"],r["path_id"]))
    return (admitted[0]["path_id"] if admitted else None),qualified_controls

def finalize(root):
    task=JointMethodCoverage(root);freeze_accounts(task)
    records={r["identity"]["path_id"]:r for r in task.status.get("account_records",[])}
    terminal={"CONTINUOUS_REPLAY_COMPLETE","CONTINUOUS_REPLAY_FAILED","BLOCKED_ALL_REQUIRED_DEPENDENCIES","INTERRUPTED_FAILURE_RETAINED"}
    if any(r["status"] not in terminal for r in records.values()):
        raise RuntimeError("Nonterminal account attempt; finalize forbidden")
    for record in records.values():
        if record["status"]=="CONTINUOUS_REPLAY_COMPLETE":verify_account_record(task,record)
    rows=[]
    for row in range(1,107):
        pid=resolve_alias(row)
        if row==98:
            rows.append(dict(method_id=f"M{row:03d}",account_status="BLOCKED_INTEGER_EXECUTION_CONTRACT",
                             account_path_id=None,eligible_for_selection=False));continue
        rec=records.get(pid);metric=rec.get("metrics",{}) if rec else {}
        rows.append(dict(method_id=f"M{row:03d}",account_status=rec["status"] if rec else "UNATTEMPTED",
             account_path_id=pid,equivalent_reuse=row in ALIASES,eligible_for_selection=metric.get("eligible_for_selection",False)))
    coverage=pd.read_csv(task.out("METHOD_COVERAGE.csv"))
    additive=pd.DataFrame(rows)
    for column in additive:
        if column!="method_id":
            coverage[column]=coverage.method_id.map(additive.set_index("method_id")[column])
    coverage.to_csv(task.out("METHOD_COVERAGE.csv"),index=False)
    if any(r["account_status"]=="UNATTEMPTED" for r in rows):
        raise RuntimeError("Cannot select before all106 responsible account roles attempted or explicitly blocked")
    metrics=[r["metrics"] for r in records.values() if r.get("metrics")]
    finalist,qualified_controls=select_finalist(metrics)
    decision=dict(status="PRE2026_METHOD_COVERAGE_COMPLETE",finalist=finalist,
       finalist_status="FINALIST_SELECTED_NEEDS_LAST_PRE2026_ARTIFACT_FREEZE" if finalist else "FINALIST_NONE",
       selection=task.parameters["comparison"],control_accounts_qualified=qualified_controls,
       no_test2026_reads=True,test2026_pages_read=0,methods=106,coverage=rows,
       account_paths_attempted=task.status["account_paths"],actual_fit_units=task.status["fit_attempts"],
       actual_rl_optimizer_updates=task.status["rl_optimizer_updates"],metrics=metrics,
       account_policy_freeze_sha256=digest(task.out("receipts/ACCOUNT_POLICY_FREEZE.json")),
       no_pristine_holdout_claim=True,no_deployment=True)
    task.write("receipts/PRE2026_SELECTION.json",decision)
    task.status["status"]="V24_PRE2026_ALL106_ATTEMPTS_COMPLETE";task.checkpoint()
    return decision

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--task-root",required=True)
    parser.add_argument("command",choices=("freeze","core","native","finalize"))
    args=parser.parse_args()
    with task_writer(args.task_root):
        if args.command=="freeze":freeze_accounts(JointMethodCoverage(args.task_root))
        elif args.command=="finalize":finalize(args.task_root)
        else:run_accounts(args.task_root,args.command)

if __name__=="__main__":main()
