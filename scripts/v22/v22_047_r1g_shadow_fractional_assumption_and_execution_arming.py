#!/usr/bin/env python
"""R1G shadow-only fractional assumption and execution arming boundary.

This layer consumes the existing R1F/V8 decision.  It never imports or calls
broker mutation APIs and it never promotes an app-level user assumption to a
broker API confirmation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

REVISION="V22.047_R1G"
STAGE="V22.047_R1G_SHADOW_FRACTIONAL_ASSUMPTION_AND_EXECUTION_ARMING"
CAPABILITY_STATES={"UNKNOWN","USER_CONFIRMED_RTH_APP","CONFIRMED_PAPER_API","CONFIRMED_REAL_API","UNSUPPORTED"}
AUTHORIZATION_STATES={"DISARMED","PAPER_ARMED","LIVE_ARM_PENDING","LIVE_ARMED"}
ASSUMPTION_STATUS="USER_CONFIRMED_RTH_APP"
ACTIVE_SYMBOLS=("US.QQQ","US.TQQQ","US.SQQQ","US.IQQQ")
ET=ZoneInfo("America/New_York")


class R1GError(RuntimeError): pass


def load_module(path:Path,name:str)->Any:
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None: raise R1GError(f"MODULE_LOAD_FAILED:{path}")
    module=importlib.util.module_from_spec(spec); sys.modules[name]=module; spec.loader.exec_module(module); return module


def read_json(path:Path,default:Any=None)->Any:
    try:return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError,json.JSONDecodeError):return default


def utc_iso(current:datetime|None=None)->str:return (current or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


class Paths:
    def __init__(self,repo:Path):
        self.repo=repo.resolve(); self.output=self.repo/"outputs"/"v22"/STAGE; self.output.mkdir(parents=True,exist_ok=True)
        self.config=self.repo/"config"/"v22_047_r1g_shadow_fractional_assumption.json"
        self.r1f_script=self.repo/"scripts"/"v22"/"v22_047_r1f_fractional_protected_sleeve.py"
        self.r1f_output=self.repo/"outputs"/"v22"/"V22.047_R1F_V8_REFERENCE_ROTATION_FRACTIONAL_RTH_PROTECTED_SLEEVE_SHADOW"
        self.r1d_output=self.repo/"outputs"/"v22"/"V22.047_R1D_LIVE_MARKET_ACCOUNT_BRIDGE_AND_LOCAL_DASHBOARD_SHADOW_ONLY"


def config_hash(paths:Paths)->str:return hashlib.sha256(paths.config.read_bytes()).hexdigest()


def load_config(paths:Paths)->dict[str,Any]:
    cfg=read_json(paths.config,{}) or {}
    if cfg.get("fractional_capability_status") not in CAPABILITY_STATES: raise R1GError("INVALID_CAPABILITY_STATUS")
    if tuple(cfg.get("assumption_symbols",[]))!=ACTIVE_SYMBOLS: raise R1GError("R1G_SYMBOL_SCOPE_INVALID")
    if cfg.get("execution_mode")!="SHADOW" or cfg.get("live_available") is not False: raise R1GError("SHADOW_ONLY_CONFIG_REQUIRED")
    if cfg.get("broker_fractional_api_confirmed") is not False or cfg.get("execution_assumption_only") is not True: raise R1GError("ASSUMPTION_MUST_NOT_CLAIM_BROKER_CONFIRMATION")
    return cfg


def assumption_payload(paths:Paths,cfg:Mapping[str,Any],current:datetime)->dict[str,Any]:
    payload={"schema_version":1,"revision":REVISION,"timestamp_utc":utc_iso(current),"fractional_capability_status":ASSUMPTION_STATUS,"symbols":list(ACTIVE_SYMBOLS),"scope":["SHADOW_DECIMAL_ORDER_INTENT","LOCAL_SIMULATED_FILL","DASHBOARD_DISPLAY"],"default_quantity_increment":str(cfg["default_quantity_increment"]),"session":"RTH","allowed_window_et":cfg["allowed_window_et"],"user_confirmed_rth_app_support":True,"broker_fractional_api_confirmed":False,"execution_assumption_only":True,"real_api_permission":False,"broker_action_allowed":False,"real_trade_api_called":False}
    r1f=load_module(paths.r1f_script,"v22_047_r1f_for_r1g_assumption"); r1f.atomic_json(paths.output/"fractional_assumption.json",payload); return payload


def authorization_state(paths:Paths,cfg:Mapping[str,Any],current:datetime)->dict[str,Any]:
    r1f=load_module(paths.r1f_script,"v22_047_r1f_for_r1g_auth_read")
    path=paths.output/"execution_authorization_state.json"; state=read_json(path,{}) or {}
    if not state:
        state={"schema_version":1,"execution_authorization":"DISARMED","created_at_utc":utc_iso(current),"expires_at_utc":None,"paper_environment":"TrdEnv.SIMULATE","live_available":False,"strategy_enabled_does_not_arm_execution":True}
    expiry=state.get("expires_at_utc")
    if state.get("execution_authorization")=="PAPER_ARMED" and expiry and current.astimezone(timezone.utc)>=datetime.fromisoformat(expiry):
        state.update({"execution_authorization":"DISARMED","expired_at_utc":utc_iso(current),"expires_at_utc":None})
    if state.get("execution_authorization") not in AUTHORIZATION_STATES or state.get("execution_authorization") in {"LIVE_ARM_PENDING","LIVE_ARMED"}:
        state.update({"execution_authorization":"DISARMED","forced_disarm_reason":"LIVE_NOT_AVAILABLE","expires_at_utc":None})
    state.update({"updated_at_utc":utc_iso(current),"broker_action_allowed":False,"real_trade_api_called":False})
    r1f.atomic_json(path,state); return state


def request_paper_arm(paths:Paths,*,first_confirmation:bool,second_confirmation:str,current:datetime|None=None)->dict[str,Any]:
    current=(current or datetime.now(timezone.utc)).astimezone(timezone.utc); cfg=load_config(paths)
    if first_confirmation is not True or second_confirmation!="CONFIRM_PAPER_SIMULATE_ONLY": raise R1GError("PAPER_EXPLICIT_DOUBLE_CONFIRMATION_REQUIRED")
    plugin=paths.repo/"scripts"/"v22"/"v22_047_r1b_strategy_plugin_template.py"; expires=current+timedelta(minutes=int(cfg["paper_arm_ttl_minutes"]))
    state={"schema_version":1,"execution_authorization":"PAPER_ARMED","armed_at_utc":utc_iso(current),"expires_at_utc":utc_iso(expires),"paper_environment":"TrdEnv.SIMULATE","real_environment_allowed":False,"configuration_hash":config_hash(paths),"strategy_version":hashlib.sha256(plugin.read_bytes()).hexdigest(),"double_confirmation_recorded":True,"broker_action_allowed":False,"real_trade_api_called":False}
    r1f=load_module(paths.r1f_script,"v22_047_r1f_for_r1g_paper_arm"); r1f.atomic_json(paths.output/"execution_authorization_state.json",state); return state


def request_live_arm(paths:Paths)->dict[str,Any]:
    state=authorization_state(paths,load_config(paths),datetime.now(timezone.utc))
    return {"ok":False,"error":"LIVE_NOT_AVAILABLE","execution_authorization":state["execution_authorization"],"required_fractional_capability_status":"CONFIRMED_REAL_API","broker_action_allowed":False,"real_trade_api_called":False}


def shadow_capabilities(paths:Paths,cfg:Mapping[str,Any])->dict[str,dict[str,Any]]:
    broker=(read_json(paths.r1f_output/"fractional_capability.json",{}) or {}).get("symbols",{})
    result={}
    for symbol in ACTIVE_SYMBOLS:
        raw=broker.get(symbol,{}) if isinstance(broker,Mapping) else {}
        result[symbol]={"enabled":True,"tradeable":raw.get("tradeable") is not False,"fractional_tradeable":True,"minimum_quantity_increment":str(cfg["default_quantity_increment"]),"minimum_notional":"0","supported_order_types":["LIMIT"],"fractional_capability_status":ASSUMPTION_STATUS,"broker_fractional_api_confirmed":False,"execution_assumption_only":True,"shadow_only":True}
    return result


def cash_projection(r1f:Any,cash:Mapping[str,Decimal],intents:list[dict[str,Any]],target_weights:Mapping[str,Any],prices:Mapping[str,Decimal],managed:Mapping[str,Decimal],utilization:Decimal)->tuple[dict[str,Any],dict[str,Any]]:
    sleeve=r1f.strategy_sleeve_nav(cash["strategy_cash_pool"],managed,prices); investable=sleeve*utilization/Decimal("100")
    targets={s:{"weight_pct":r1f.decimal_text(r1f.D(target_weights.get(s))),"target_notional_usd":r1f.decimal_text(investable*r1f.D(target_weights.get(s))/Decimal("100"))} for s in ACTIVE_SYMBOLS}
    used=sum((r1f.D(x["notional_usd"]) for x in intents if x["side"]=="BUY"),Decimal("0")); proceeds=sum((r1f.D(x["notional_usd"]) for x in intents if x["side"]=="SELL"),Decimal("0")); after=cash["strategy_cash_pool"]+proceeds-used
    projection={"cash_before":r1f.decimal_text(cash["available_usd_cash"]),"cash_reserved":r1f.decimal_text(cash["manual_open_order_cash_reserve"]+cash["strategy_open_order_cash_reserve"]+cash["minimum_cash_buffer"]),"strategy_cash_pool_before":r1f.decimal_text(cash["strategy_cash_pool"]),"cash_used":r1f.decimal_text(used),"cash_from_planned_sales":r1f.decimal_text(proceeds),"cash_after_expected":r1f.decimal_text(after),"total_target_notional":r1f.decimal_text(sum((r1f.D(x["target_notional_usd"]) for x in targets.values()),Decimal("0"))),"uninvested_cash":r1f.decimal_text(after),"broker_action_allowed":False,"real_trade_api_called":False}
    return targets,projection


def run_cycle(repo:Path,*,now:datetime|None=None)->dict[str,Any]:
    paths=Paths(repo); cfg=load_config(paths); current=(now or datetime.now(timezone.utc)).astimezone(ET); r1f=load_module(paths.r1f_script,"v22_047_r1f_for_r1g_cycle")
    assumption=assumption_payload(paths,cfg,current); auth=authorization_state(paths,cfg,current)
    market=read_json(paths.r1d_output/"market_snapshot.json",{}) or {}; account=read_json(paths.r1d_output/"account_snapshot.json",{}) or {}; decision=read_json(paths.r1f_output/"strategy_decision.json",{}) or {}; control=read_json(paths.r1f_output/"control_decision.json",{}) or {}
    if not market.get("snapshot_ready") or not account.get("account_snapshot_ready") or not decision.get("metadata",{}).get("strategy_configured"): raise R1GError("R1F_OR_R1D_INPUT_NOT_READY")
    baseline=read_json(paths.r1f_output/"protected_position_baseline.json",{}) or {}; managed=r1f.managed_quantities(r1f.Paths(repo)); protected=r1f.protected_quantities(baseline); reconciliation=r1f.reconcile_inventory(account,managed,protected)
    cash=r1f.strategy_cash_pool(account,r1f.D(cfg["minimum_cash_buffer_usd"])); prices={s:r1f.D(market.get("quotes",{}).get(s,{}).get("latest_price")) for s in ACTIVE_SYMBOLS}; target_weights=decision.get("metadata",{}).get("target_weights",{})
    blocked=bool(control.get("r1f_blocked") or reconciliation.get("state")!="READY"); blocked_symbols=control.get("manual_override_blocked_symbols",[]); sellable={str(x.get("code","")).upper():r1f.D(x.get("can_sell_qty")) for x in account.get("positions_detail",[]) if isinstance(x,Mapping)}
    intents=r1f.build_fractional_intents(target_weights,cash["strategy_cash_pool"],managed,protected,prices,market.get("quotes",{}),shadow_capabilities(paths,cfg),current,blocked=blocked,blocked_symbols=blocked_symbols,reason_code=decision.get("reason_code","R1G_SHADOW_PLAN"),utilization_pct=r1f.D(cfg["cash_utilization_pct"]),broker_sellable=sellable)
    for intent in intents: intent.update({"quantity_type":"Decimal","integer_truncation_forbidden":True,"fractional_capability_status":ASSUMPTION_STATUS,"broker_fractional_api_confirmed":False,"execution_assumption_only":True,"plan_status":"SHADOW PLAN ONLY","broker_delivery_status":"NOT SENT TO BROKER","execution_authorization":auth["execution_authorization"]})
    targets,projection=cash_projection(r1f,cash,intents,target_weights,prices,managed,r1f.D(cfg["cash_utilization_pct"])); target={"schema_version":1,"timestamp_utc":utc_iso(current),"current_v8_state":decision.get("metadata",{}).get("active_state_name"),"target_weights":target_weights,"target_portfolio":targets,"iqqq_default_weight_zero":r1f.D(target_weights.get("US.IQQQ"))==0}
    plan={"schema_version":1,"timestamp_utc":utc_iso(current),"order_intent_created":bool(intents),"intents":intents,"fractional_capability_status":ASSUMPTION_STATUS,"shadow_plan_only":True,"not_sent_to_broker":True,"execution_authorization":auth["execution_authorization"],"broker_action_allowed":False,"real_trade_api_called":False}
    summary={"schema_version":1,"revision":REVISION,"timestamp_utc":utc_iso(current),"final_status":"R1G_PASS_SHADOW_FRACTIONAL_PLANNING_AND_EXECUTION_ARMING_READY","strategy_enabled":True,"strategy_configured":True,"strategy_name":"V8_REFERENCE_TREND_ROTATION","strategy_runtime_mode":"ENABLED","execution_mode":"SHADOW","effective_execution_mode":"SHADOW_ONLY","fractional_capability_status":ASSUMPTION_STATUS,"broker_fractional_api_confirmed":False,"execution_assumption_only":True,"execution_authorization":auth["execution_authorization"],"current_v8_state":target["current_v8_state"],"order_intent_created":bool(intents),"planned_order_count":len(intents),"expected_cash_after":projection["cash_after_expected"],"broker_action_allowed":False,"real_trade_api_called":False}
    for name,payload in (("target_portfolio_snapshot.json",target),("shadow_cash_projection.json",projection),("shadow_fractional_order_intents.json",plan),("r1g_summary.json",summary)): r1f.atomic_json(paths.output/name,payload)
    report=[f"# {STAGE} Validation Report","",f"Final status: **{summary['final_status']}**","",f"- fractional_capability_status=`{ASSUMPTION_STATUS}`","- broker_fractional_api_confirmed=`False`","- execution_assumption_only=`True`",f"- execution_authorization=`{auth['execution_authorization']}`",f"- order_intent_created=`{bool(intents)}`","- broker_action_allowed=`False`","- real_trade_api_called=`False`","","SHADOW PLAN ONLY — NOT SENT TO BROKER."]
    (paths.output/"validation_report.md").write_text("\n".join(report)+"\n",encoding="utf-8"); return summary


def run_service(repo:Path,interval:float)->int:
    paths=Paths(repo); stop=paths.output/"r1g.stop"
    if stop.exists():stop.unlink()
    while not stop.exists():
        try:run_cycle(repo)
        except Exception as exc:
            r1f=load_module(paths.r1f_script,"v22_047_r1f_for_r1g_error"); r1f.atomic_json(paths.output/"error_state.json",{"active":True,"timestamp_utc":utc_iso(),"error":f"{type(exc).__name__}:{exc}","broker_action_allowed":False,"real_trade_api_called":False})
        deadline=time.monotonic()+max(5,interval)
        while not stop.exists() and time.monotonic()<deadline:time.sleep(min(.5,deadline-time.monotonic()))
    return 0


def main(argv:list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--repo-root",default=r"D:\us-tech-quant"); parser.add_argument("--service",action="store_true"); parser.add_argument("--interval",type=float,default=30); args=parser.parse_args(argv)
    try:
        if args.service:return run_service(Path(args.repo_root),args.interval)
        print(json.dumps(run_cycle(Path(args.repo_root)),ensure_ascii=True,indent=2)); return 0
    except Exception as exc:print(f"final_status=FAIL_{REVISION}\nerror={type(exc).__name__}:{exc}",file=sys.stderr); return 2


if __name__=="__main__":raise SystemExit(main())
