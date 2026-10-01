"""Fixed JOINT risk/account adapter; one existing engine, no model search."""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf
from threadpoolctl import threadpool_limits
from scripts.research.a2.evaluation.joint_execution_resume import JointExecution,digest
from scripts.research.a2.evaluation.continuous_research_account import run_continuous_account
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays
from scripts.research.a2.inference.joint_portfolio_policy import JointResearchPolicy
from scripts.v22.corporate_action_transition_r1 import CorporateActionTransition

ROLES=["CONTROL_RAW_A2_POLICY","JOINT_SIMPLE_EQUAL","PTO_RIDGE_DIAG","PTO_HGB_DIAG",
       "PTO_EQUAL_ENSEMBLE_LW","PTO_EQUAL_ENSEMBLE_LW_VOL","ABL_ACTION","ABL_WEIGHT"]

def run(root):
    task=JointExecution(root)
    inputs=task.read("receipts/R1_TRAINING_INPUTS.json")
    task.input_sha=inputs["panel_sha256"]
    frame=pd.read_parquet(inputs["panel"],columns=["signal_date","ticker","execution_date","label_end_date",
          "y_next_open","model_sample_eligible","features_available","avg_dollar_volume_20d"])
    frame.signal_date=pd.to_datetime(frame.signal_date);frame.label_end_date=pd.to_datetime(frame.label_end_date)
    calendar=pd.read_parquet(inputs["calendar_file"])
    date_col=next(c for c in calendar.columns if c in ["trade_date","signal_date","date"])
    dates=pd.DatetimeIndex(pd.to_datetime(calendar[date_col])).sort_values()
    dates=dates[(dates>=pd.Timestamp("2023-01-01"))&(dates<pd.Timestamp("2026-01-01"))]
    tickers=np.asarray(sorted(frame.ticker.unique()),dtype=str)
    ti={t:i for i,t in enumerate(tickers)};di={d:i for i,d in enumerate(dates)}
    shape=(len(dates),len(tickers))
    covariances={}
    for year in [2023,2024,2025]:
        cutoff=pd.Timestamp(year,1,1)
        history=frame.loc[frame.model_sample_eligible & frame.signal_date.lt(cutoff) & frame.label_end_date.lt(cutoff)].copy()
        table=history.pivot(index="signal_date",columns="ticker",values="y_next_open").sort_index()
        count=table.notna().sum()
        selected=table.columns[count>=30]
        table=table[selected]
        values=table.to_numpy(float);means=np.nanmean(values,axis=0)
        var=np.nanvar(values,axis=0,ddof=1)
        fallback=float(np.nanmedian(var[np.isfinite(var)&(var>0)]))
        if not np.isfinite(fallback) or fallback<=0:raise RuntimeError("No legal prior risk variance")
        known=np.asarray([ti[t] for t in selected],int)
        centered=np.where(np.isfinite(values),values-means,0)
        for kind in ["DIAG","LW"]:
            def creator(kind=kind):
                covariance=np.eye(len(tickers))*fallback
                if kind=="DIAG":covariance[known,known]=np.maximum(var,1e-8)
                else:
                    local=LedoitWolf().fit(centered).covariance_
                    covariance[np.ix_(known,known)]=local
                covariance=(covariance+covariance.T)/2
                covariance[np.diag_indices(len(tickers))]=np.maximum(np.diag(covariance),1e-8)
                return {"covariance":covariance,"tickers":tickers.tolist(),"known_names":selected.tolist(),
                        "fallback_variance":fallback,"cutoff":str(cutoff.date())}
            bundle=task.fit_state("risk_"+kind,year,{"kind":kind,"minimum_prior_observations":30,
                "unknown":"median frozen variance, independent correlation, not eligibility"},history,creator)
            covariances[(year,kind)]=bundle["covariance"]
    pool=np.zeros(shape,bool);present=np.zeros(shape,bool)
    rows=frame.loc[frame.signal_date.isin(dates)]
    ri=np.asarray([di[d] for d in rows.signal_date],int);ci=np.asarray([ti[t] for t in rows.ticker],int)
    pool[ri,ci]=True;present[ri,ci]=rows.features_available.to_numpy(bool)
    prices=pd.read_parquet(inputs["price_file"])
    prices.trade_date=pd.to_datetime(prices.trade_date)
    prices=prices.loc[prices.ticker.isin(tickers)].copy()
    prices=prices.sort_values(["ticker","trade_date"])
    prices["dollar_volume"]=prices.close*prices.volume
    prices["adv"]=prices.groupby("ticker").dollar_volume.transform(lambda x:x.rolling(20,min_periods=20).mean())
    prices=prices.loc[prices.trade_date.isin(dates)].copy()
    op=np.full(shape,np.nan);close=np.full(shape,np.nan);row_present=np.zeros(shape,bool)
    pri=np.asarray([di[d] for d in prices.trade_date],int);pci=np.asarray([ti[t] for t in prices.ticker],int)
    op[pri,pci]=prices.open.to_numpy(float);close[pri,pci]=prices.close.to_numpy(float);row_present[pri,pci]=True
    # Existing capacity engine uses signal-known ADV, including pre-2023 warmup.
    adv=np.full(shape,np.nan)
    adv[np.asarray([di[d] for d in prices.trade_date],int),np.asarray([ti[t] for t in prices.ticker],int)]=prices.adv.to_numpy(float)
    oof=pd.read_parquet(task.out("OOF_PREDICTIONS.parquet"))
    oof.signal_date=pd.to_datetime(oof.signal_date)
    mu=np.full((len(dates),len(ROLES),len(tickers)),np.nan)
    unc=np.full_like(mu,np.nan)
    oi=np.asarray([di[d] for d in oof.signal_date],int);oc=np.asarray([ti[t] for t in oof.ticker],int)
    mapping={"PTO_RIDGE_DIAG":("Ridge_mu","Ridge_uncertainty"),"PTO_HGB_DIAG":("HGB_mu","HGB_uncertainty")}
    for role in ROLES[2:]:
        mi,ui=mapping.get(role,("ensemble_mu","ensemble_disagreement"))
        j=ROLES.index(role);mu[oi,j,oc]=oof[mi].to_numpy(float);unc[oi,j,oc]=oof[ui].to_numpy(float)
    # Physical pre-2026 Raw OOF; project score/key columns only, no original targets/performance.
    raw_path=Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\A2\oof_predictions.parquet")
    raw=pd.read_parquet(raw_path,columns=["signal_date","ticker","a2_prediction"])
    raw.signal_date=pd.to_datetime(raw.signal_date)
    assert raw.signal_date.lt("2026-01-01").all()
    raw=raw.loc[raw.signal_date.isin(dates)&raw.ticker.isin(tickers)]
    rri=np.asarray([di[d] for d in raw.signal_date],int);rci=np.asarray([ti[t] for t in raw.ticker],int)
    for j in [0,1]:
        mu[rri,j,rci]=raw.a2_prediction.to_numpy(float);unc[rri,j,rci]=0
    market=MarketArrays(dates,tickers,op,close,row_present=row_present,adv=adv,
        input_present=present,new_buy_eligible=pool,signal_mask=np.ones(len(dates),bool),
        signal_asof=[(d+pd.Timedelta(hours=16)).tz_localize("America/New_York") for d in dates])
    # Reuse frozen vendor effective-event accounting semantics, explicit R1 assumption.
    event_path=Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\audit\corporate_action_event_audit.parquet")
    events=pd.read_parquet(event_path,columns=["ticker","code","event_date","source_event_date",
                 "factor_a","factor_b","share_event","manual_wolf","raw_jump","audit_kind"])
    events.event_date=pd.to_datetime(events.event_date)
    if events.event_date.ge("2026-01-01").any():raise RuntimeError("Mixed event input")
    actions=[];known_at={};unsupported=[]
    event_hash="782e592f17fff8ac9fa9b535cc6b590b59e94e3d725feaedfb7b4f50f39c471c"
    for row in events.itertuples():
        day=pd.Timestamp(row.event_date)
        if day not in di or row.ticker not in ti:continue
        if bool(row.share_event) and np.isfinite(row.factor_a) and row.factor_a>0 and row.factor_b==0 and not bool(row.manual_wolf):
            reference=str(event_path)+"#"+str(row.code)+"@"+str(day.date())
            action=CorporateActionTransition(str(day.date()),"OTHER_SHARE_COUNT_TRANSFORM",
                "R1_VENDOR_CODE:"+str(row.code),"R1_VENDOR_CODE:"+str(row.code),str(row.ticker),str(row.ticker),
                1/float(row.factor_a),0,"TIER2_LOCAL_CANONICAL",reference,event_hash)
            actions.append(action)
            known_at[action.event_fingerprint]=(day+pd.Timedelta(hours=9,minutes=30)).tz_localize("America/New_York").tz_convert("UTC")
        elif (bool(row.manual_wolf) or (np.isfinite(row.factor_b) and row.factor_b!=0)
              or (np.isfinite(row.raw_jump) and abs(row.raw_jump)>=.8)):
            unsupported.append({"ticker":str(row.ticker),"effective_date":str(day.date()),
              "reason":"SOURCE_CASH_OR_REORGANIZATION_EVENT_NOT_HANDLED_BY_IMMUTABLE_COMMON_ENGINE",
              "source_reference":str(event_path),"source_fingerprint":event_hash})
    # Deduplicate immutable audit rows without changing event semantics.
    actions=list({(a.effective_date,a.old_ticker):a for a in actions}.values())
    unsupported=list({(e["ticker"],e["effective_date"],e["reason"]):e for e in unsupported}.values())
    task.write("receipts/RESEARCH_ACCOUNTING_BINDING.json",{
        "status":"R1_EXISTING_COMMON_VENDOR_EFFECTIVE_ACCOUNTING_SEMANTICS",
        "raw_price_receipt":"receipts/R1_TRAINING_INPUTS.json","event_source":str(event_path),"event_source_sha256":event_hash,
        "share_actions":len(actions),"unsupported_specific_events":len(unsupported),
        "availability_assumption":"Human-accepted existing common accounting vendor effective event applied at that session Open; not publication/acquisition certification.",
        "ratio":"NEW_QUANTITY_PER_OLD=1/factor_a only source-backed share_event with factor_b0",
        "no_ratio_heuristics":True,"live_official_auction_certification":False})
    diagnostics=[]
    def save_diagnostics(block):
        diagnostics.append(block)
        if len(diagnostics)%100==0:print(json.dumps({"status":"ACCOUNT_SIGNAL_PROGRESS","sessions":len(diagnostics)}),flush=True)
    policy=JointResearchPolicy(ROLES,mu,unc,covariances,on_diagnostics=save_diagnostics,parameters=task.parameters)
    task.write("receipts/ACCOUNT_EXECUTION_FREEZE.json",{
        "status":"FIXED_BEFORE_ACCOUNT_ECONOMIC_READ","role_ids":ROLES,
        "policy_source_sha256":digest(Path(__file__).resolve().parents[1]/"inference/joint_portfolio_policy.py"),
        "account_source_sha256":digest(Path(__file__).resolve().parent/"continuous_research_account.py"),
        "adapter_source_sha256":digest(__file__),"account_config_sha256":digest(task.out("ACCOUNT_CONFIG.json")),
        "execution_parameters_sha256":digest(task.out("EXECUTION_PARAMETERS.json")),
        "finalist_rule_sha256":digest(task.out("FINALIST_RULE.json")),
        "2026_locked":True,"qualification":"PARTIAL DIAGNOSTIC ONLY; no finalist admission from subset results"})
    print(json.dumps({"status":"CONTINUOUS_ACCOUNT_STARTED","paths":len(ROLES),"sessions":len(dates),"full_ticker_coordinates":len(tickers)}),flush=True)
    with threadpool_limits(limits=2):
        replay=run_continuous_account(market,ROLES,policy,task.read("ACCOUNT_CONFIG.json"),
                         corporate_actions=actions,corporate_action_known_at=known_at,unsupported_events=unsupported)
    # Outputs are genuine traces. Full-scope qualification stays false on every ledger.
    daily=replay.daily.copy();daily["full_pool_qualified"]=False
    daily["evaluation_scope"]="R1_PARTIAL_INPUT_DIAGNOSTIC"
    daily.to_parquet(task.out("RESEARCH_LEDGER.parquet"),index=False)
    daily.to_parquet(task.out("DEPLOYMENT_LEDGER.parquet"),index=False)
    for name,dest in [("orders","TARGET_PORTFOLIOS.parquet"),("execution_results","EXECUTABLE_PORTFOLIOS.parquet"),
                      ("fills","POLICY_ACTIONS.parquet"),("positions","ledgers/POSITIONS.parquet"),("contexts","ledgers/CONTEXTS.parquet")]:
        table=getattr(replay,name).copy();table["full_pool_qualified"]=False
        table.to_parquet(task.out(dest),index=False)
    cost=replay.fills[["path_id","signal_date","execution_date","ticker","notional","transaction_cost"]].copy()
    cost["cash_interest"]=0;cost.to_parquet(task.out("COST_LEDGER.parquet"),index=False)
    pd.concat(diagnostics,ignore_index=True).to_parquet(task.out("ledgers/POLICY_DIAGNOSTICS.parquet"),index=False)
    if not replay.accounting_exceptions.empty:
        replay.accounting_exceptions.to_csv(task.out("reports/ACCOUNTING_EXCEPTIONS.csv"),index=False)
    yearly=[]
    for path,g in daily.groupby("path_id",sort=False):
        for year,h in g.groupby(g.date.dt.year):
            nav=h.nav.to_numpy(float);previous=task.read("ACCOUNT_CONFIG.json")["initial_nav"] if year==2023 else float(g.loc[g.date.lt(h.date.min())].nav.iloc[-1])
            ret=h.net_return.to_numpy(float);finite=ret[np.isfinite(ret)]
            yearly.append({"path_id":path,"year":int(year),"initial_nav":previous,"final_nav":float(nav[-1]),
                "return":float(nav[-1]/previous-1),"max_drawdown":float(np.nanmin(nav/np.maximum.accumulate(np.r_[previous,nav])[1:]-1)),
                "sharpe":float(np.sqrt(252)*finite.mean()/finite.std()) if len(finite)>1 and finite.std()>0 else 0,
                "mean_gross":float(h.gross_exposure.mean()),"mean_cash":float(h.cash_weight.mean()),
                "all_cash_days":int((h.gross_exposure<=1e-10).sum()),"zero_trade_days":int((h.traded_notional<=1e-10).sum()),
                "turnover":float(h.turnover.sum()),"valuation_uncertified_days":int((~np.isfinite(h.certified_nav.to_numpy(float))).sum()),
                "full_pool_qualified":False,"finalist_eligible":False,"scope":"PARTIAL_DIAGNOSTIC_NOT_PRIMARY_RESULT"})
    pd.DataFrame(yearly).to_csv(task.out("YEARLY_RESULTS.csv"),index=False)
    holding=replay.positions.groupby("path_id").agg(holding_age_mean=("holding_age","mean"),
            holding_age_max=("holding_age","max"),position_rows=("ticker","size")).reset_index()
    holding.to_csv(task.out("HOLDING_DIAGNOSTICS.csv"),index=False)
    gross=daily.groupby("path_id").agg(mean_gross=("gross_exposure","mean"),mean_cash=("cash_weight","mean"),
            all_cash_days=("gross_exposure",lambda x:int((x<=1e-10).sum())),zero_trade_days=("traded_notional",lambda x:int((x<=1e-10).sum())),
            total_turnover=("turnover","sum")).reset_index()
    gross.to_csv(task.out("GROSS_DIAGNOSTICS.csv"),index=False)
    attribution=[]
    for role in ROLES:
        end=daily.loc[daily.path_id.eq(role)].iloc[-1]
        attribution.append({"path_id":role,"final_nav":float(end.nav),"mean_gross":float(gross.loc[gross.path_id.eq(role),"mean_gross"].iloc[0]),
          "mechanism":{"PTO_EQUAL_ENSEMBLE_LW_VOL":"Gross/Cash","ABL_WEIGHT":"relative weighting","ABL_ACTION":"rebalance action"}.get(role,"opportunity+risk/control"),
          "full_pool_qualified":False,"claim":"No causal/selection-alpha claim from partial unqualified accounting"})
    pd.DataFrame(attribution).to_csv(task.out("ATTRIBUTION_RESULTS.csv"),index=False)
    task.write("EXECUTION_AUDIT.json",{"status":"COMMON_ENGINE_IDENTITIES_VERIFIED_PARTIAL_INPUT_ACCOUNTING_UNQUALIFIED",
         "numeric_audit":replay.audit,"metadata":replay.metadata,"paths":len(ROLES),"sessions":len(dates),
         "accounting_exceptions":replay.accounting_exceptions.to_dict("records"),"full_pool_qualified":False,
         "broker_orders":0,"actual_year_resets":0,"2026_evaluations":0,"prefix_identity":replay.prefix_identity,
         "deployment_ledger_meaning":"Same exact R1 executable research trace, not live deployment or certification"})
    task.write("reports/ABLATION_STATUS.json",{"ABL_SELECTION":{"status":"BLOCKED_TARGET_BRIDGE_OOF_MATURITY","missing":"Pre2023 Raw historical OOF calibration bridge from MEAN_ER multihorizon relative target to one-day absolute target","raw_refit_prohibited":True},
       "ABL_ACTION":"REAL_DIAGNOSTIC_REPLAY_COMPLETE","ABL_WEIGHT":"REAL_DIAGNOSTIC_REPLAY_COMPLETE",
       "ABL_GROSS":{"status":"DIRECT_REUSE","path":"PTO_EQUAL_ENSEMBLE_LW"},
       "cost_pair":"NOT_IDENTIFIABLE_UNDER_ZERO_PRIMARY_COST"})
    task.write("FINALIST.json",{"status":"FINALIST_NONE","candidate_id":None,"rule":"FINALIST_RULE.json",
       "reason":"Every challenger fails required full-pool raw input qualification; no partial economic result used to admit a finalist",
       "test2026_locked":True,"selection_complete_as_unqualified":True,"final_fit_performed":False,
       "freeze_authority":"Pre-result eligibility requires complete legal full-chain account"})
    task.write("MODEL_CHANGE_GATE.json",{"status":"NO_CHANGE_REVIEW","production_activation":False,
       "accepted_challenger":None,"required_full_chain_qualified":False,"test2026_permitted":False,
       "reason":"Required full-pool raw objects absent/unavailable within legal read scope; partial diagnostics do not authorize model replacement."})
    task.status["status"]="REAL_PARTIAL_OOF_AND_CONTINUOUS_DIAGNOSTIC_ACCOUNT_COMPLETE_PRIMARY_BLOCKED"
    task.write("work/FIT_STATUS.json",task.status)
    task.write("receipts/REAL_ACCOUNT_RECEIPT.json",{"status":task.status["status"],"paths":len(ROLES),"sessions":len(dates),
       "source":"existing immutable run_many via continuous adapter","prefix":replay.prefix_identity,
       "actual_order_rows":len(replay.orders),"actual_fill_rows":len(replay.fills),"actual_daily_rows":len(daily),
       "missing_fullscope_prices":1631,"primary_qualification":False,"2026_read":0,"no_year_reset":True})
    status=task.read("RUN_MANIFEST.json")
    status["status"]="BLOCKED_REQUIRED_FULLPOOL_RAW_INPUTS_REAL_PARTIAL_RESULTS"
    status["counts"]["new_fits"]=task.status["fit_attempts"]
    status["counts"]["new_account_paths"]=len(ROLES)
    status["milestones"]["pre2026_full_chain_oof"]="REAL_OPPORTUNITY_CALIBRATION_OOF_COMPLETE_LEGAL_PARTIAL_FULL_KEYS_RETAINED"
    status["milestones"]["account_replay"]="REAL_CONTINUOUS_2023_2025_DIAGNOSTIC_COMPLETE_FULLSCOPE_UNQUALIFIED"
    status["milestones"]["finalist"]="FINALIST_NONE_INPUT_QUALIFICATION_FAILURE"
    status["blocking_gaps"]=[{"id":"RAW_FULLPOOL_PHYSICAL_OR_LEGAL_READ_ABSENCE","missing_tickers":1631,
        "mixed_single_rowgroup":631,"raw_object_absent":1000,"exact_source_receipt":"receipts/INPUT_BINDING_RESUME.json",
        "affects":"All four main challengers full-scope economic qualification; partial training and diagnostics completed"}]
    task.write("RUN_MANIFEST.json",status)
    records=[{"model_id":r["identity"]["kind"]+"_"+r["identity"]["cutoff_exclusive"][:4],"status":r["status"],
         "fit_count":r["learned_states"],"cutoff":r["identity"]["cutoff_exclusive"],"artifact":r["artifact"],
         "sha256":r.get("sha256",""),"rows":r["rows"]} for r in task.status["records"]]
    pd.DataFrame(records).to_csv(task.out("MODEL_REGISTRY.csv"),index=False)
    print(json.dumps({"status":status["status"],"fit_states":task.status["fit_attempts"],"paths":len(ROLES),
          "fills":len(replay.fills),"finalist":"NONE","2026_read":0}),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--task-root",required=True);args=p.parse_args();run(args.task_root)
