#!/usr/bin/env python
"""R1F protected fractional sleeve around the single R1B V8 plug-in.

No broker mutation API is imported or called.  All output is SHADOW intent and
all quantities use Decimal strings.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, InvalidOperation, getcontext
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

getcontext().prec = 28
REVISION = "V22.047_R1F_R2A"
STAGE = "V22.047_R1F_V8_REFERENCE_ROTATION_FRACTIONAL_RTH_PROTECTED_SLEEVE_SHADOW"
OUTPUT_FOLDER = STAGE
STRATEGY_PREFIX = "V22_047_R1F_"
ACTIVE_SYMBOLS = ("US.QQQ", "US.TQQQ", "US.SQQQ", "US.IQQQ")
FUTURE_SYMBOL = "US.IQQ"
RTH_START = dt_time(9, 45)
RTH_END = dt_time(15, 50)
LEDGER_FIELDS = ("timestamp_utc", "event", "symbol", "quantity", "cash_usd", "reference", "remark", "detail")


class R1FError(RuntimeError): pass


def now_utc() -> datetime: return datetime.now(timezone.utc)
def utc_iso() -> str: return now_utc().isoformat()


def D(value: Any, default: str = "0") -> Decimal:
    try: return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError): return Decimal(default)


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True, default=str); handle.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def read_json(path: Path, default: Any = None) -> Any:
    try: return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError, OSError): return default


def append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists(): return []
    result=[]
    for line in path.read_text(encoding="utf-8-sig",errors="replace").splitlines():
        try:
            row=json.loads(line)
            if isinstance(row,dict): result.append(row)
        except json.JSONDecodeError: pass
    return result


def load_module(path: Path, name: str) -> Any:
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None: raise R1FError(f"MODULE_LOAD_FAILED:{path}")
    module=importlib.util.module_from_spec(spec); sys.modules[name]=module; spec.loader.exec_module(module); return module


class Paths:
    def __init__(self, repo: Path):
        self.repo=repo.resolve(); self.output=self.repo/"outputs"/"v22"/OUTPUT_FOLDER
        self.r1d_output=self.repo/"outputs"/"v22"/"V22.047_R1D_LIVE_MARKET_ACCOUNT_BRIDGE_AND_LOCAL_DASHBOARD_SHADOW_ONLY"
        self.config=self.repo/"config"/"v22_047_r1f_fractional_protected_sleeve.json"
        self.plugin=self.repo/"scripts"/"v22"/"v22_047_r1b_strategy_plugin_template.py"
        self.r1b=self.repo/"scripts"/"v22"/"v22_047_r1b_auto_trading_control_component.py"
        self.r1d=self.repo/"scripts"/"v22"/"v22_047_r1d_live_market_account_bridge.py"
        self.output.mkdir(parents=True,exist_ok=True)


def rth_order_window(now: datetime | None = None) -> tuple[bool,str]:
    current=(now or now_utc()).astimezone(ZoneInfo("America/New_York"))
    if current.weekday()>=5: return False,"WEEKEND_BLOCKED"
    t=current.time().replace(tzinfo=None)
    if t < RTH_START: return False,"BEFORE_0945_ET_BLOCKED"
    if t > RTH_END: return False,"AFTER_1550_ET_BLOCKED"
    return True,"RTH_ORDER_WINDOW_OPEN"


def load_config(paths: Paths) -> dict[str,Any]:
    cfg=read_json(paths.config,{}) or {}
    if cfg.get("margin_allowed") or cfg.get("short_selling_allowed") or cfg.get("options_allowed"): raise R1FError("CASH_LONG_ONLY_REQUIRED")
    if not cfg.get("allow_fractional"): raise R1FError("FRACTIONAL_INTENTS_MUST_BE_ENABLED")
    if tuple(cfg.get("execution_whitelist",[])) != ACTIVE_SYMBOLS: raise R1FError("EXECUTION_WHITELIST_MUST_BE_QQQ_TQQQ_SQQQ_IQQQ")
    return cfg


def asset_type(symbol: str, item: Mapping[str,Any] | None=None) -> str:
    if symbol in ACTIVE_SYMBOLS or symbol==FUTURE_SYMBOL: return "NASDAQ_ETF"
    detail=" ".join(str((item or {}).get(k, "")) for k in ("position_type","strategy_type","stock_name")).upper()
    return "OPTION" if "OPTION" in detail or "期权" in detail else "NON_WHITELIST_ASSET"


def protected_baseline(paths: Paths, account: Mapping[str,Any]) -> dict[str,Any]:
    path=paths.output/"protected_position_baseline.json"; existing=read_json(path,{}) or {}
    if existing.get("r2a_classification_complete"):
        ledger=paths.output/"manual_activity_ledger.jsonl"
        if not any(x.get("event")=="MANUAL_ACTIVITY_SCHEMA_R2A" for x in read_jsonl(ledger)):
            created=utc_iso(); append_jsonl(ledger,{"event_id":hashlib.sha256(f"SCHEMA_R2A|{created}".encode()).hexdigest()[:24],"timestamp_et":datetime.now(ZoneInfo("America/New_York")).isoformat(),"event":"MANUAL_ACTIVITY_SCHEMA_R2A","symbol":"","asset_type":"","side":"","quantity":"0","price":"0","order_id_hash":"","deal_id_hash":"","manual_or_strategy":"SCHEMA","previous_quantity":"0","new_quantity":"0","cash_change":"0","override_until":"","reconciliation_status":"READY"})
        return existing
    protected={}; managed={}; created=utc_iso()
    for item in account.get("positions_detail",[]):
        if not isinstance(item,Mapping) or D(item.get("qty"))==0: continue
        symbol=str(item.get("code","")).upper(); qty=D(item.get("qty"))
        if symbol in ACTIVE_SYMBOLS and qty>0:
            managed[symbol]={"quantity":decimal_text(qty),"classification":"NASDAQ_ETF_MANAGED_SLEEVE","source":"R2A_INITIAL_ACCOUNT_SYNC","updated_at_utc":created}
        else:
            protected[symbol]={"classification":"OUT_OF_SCOPE_PROTECTED_POSITION","asset_type":asset_type(symbol,item),"protected_position_floor":decimal_text(qty),"strategy_control_allowed":False,"strategy_sell_allowed":False,"included_in_strategy_nav":False,"included_in_strategy_cash_pool":False,"baseline_at_utc":created}
            append_jsonl(paths.output/"out_of_scope_position_ledger.jsonl",{"event_id":hashlib.sha256(f"INIT|{symbol}|{qty}|{created}".encode()).hexdigest()[:20],"timestamp_et":datetime.now(ZoneInfo("America/New_York")).isoformat(),"event":"OUT_OF_SCOPE_PROTECTED_POSITION_CREATED","symbol":symbol,"asset_type":asset_type(symbol,item),"quantity":decimal_text(qty)})
    payload={"schema_version":2,"created_at_utc":created,"positions":protected,"r2a_classification_complete":True}
    atomic_json(path,payload); atomic_json(paths.output/"nasdaq_etf_managed_sleeve.json",{"schema_version":1,"updated_at_utc":created,"positions":managed})
    if not (paths.output/"strategy_inventory_ledger.jsonl").exists(): append_jsonl(paths.output/"strategy_inventory_ledger.jsonl",{"timestamp_utc":created,"event":"INVENTORY_GENESIS","strategy_owned_qty":{s:"0" for s in ACTIVE_SYMBOLS},"remark_prefix":STRATEGY_PREFIX})
    if not (paths.output/"manual_activity_ledger.jsonl").exists(): append_jsonl(paths.output/"manual_activity_ledger.jsonl",{"event_id":hashlib.sha256(f"BASELINE|{created}".encode()).hexdigest()[:24],"timestamp_et":datetime.now(ZoneInfo("America/New_York")).isoformat(),"event":"MANUAL_ACTIVITY_BASELINE","symbol":"","asset_type":"","side":"","quantity":"0","price":"0","order_id_hash":"","deal_id_hash":"","manual_or_strategy":"BASELINE","previous_quantity":"0","new_quantity":"0","cash_change":"0","override_until":"","reconciliation_status":"READY","detail":"Existing orders/deals recorded as pre-enable baseline"})
    if not (paths.output/"activity_cursor.json").exists():
        atomic_json(paths.output/"activity_cursor.json",{"seen_order_references":[x.get("order_reference") for x in account.get("today_orders",[]) if x.get("order_reference")],"seen_deal_references":[x.get("deal_reference") for x in account.get("today_deals",[]) if x.get("deal_reference")]})
    if not (paths.output/"manual_override_state.json").exists(): atomic_json(paths.output/"manual_override_state.json",{"schema_version":1,"symbols":{},"system_state":"READY"})
    return payload


def strategy_owned_quantities(paths: Paths) -> dict[str,Decimal]:
    qty={s:Decimal("0") for s in ACTIVE_SYMBOLS}
    for row in read_jsonl(paths.output/"strategy_inventory_ledger.jsonl"):
        if row.get("event") != "STRATEGY_FILL" or not str(row.get("remark","")).startswith(STRATEGY_PREFIX): continue
        symbol=str(row.get("symbol","")).upper()
        if symbol in qty: qty[symbol]+=D(row.get("signed_quantity"))
    return qty


def broker_quantities(account: Mapping[str,Any]) -> dict[str,Decimal]:
    result={}
    for item in account.get("positions_detail",[]):
        if isinstance(item,Mapping): result[str(item.get("code","")).upper()]=D(item.get("qty"))
    return result


def managed_quantities(paths: Paths) -> dict[str,Decimal]:
    state=read_json(paths.output/"nasdaq_etf_managed_sleeve.json",{}) or {}
    return {s:D(v.get("quantity")) for s,v in state.get("positions",{}).items() if s in ACTIVE_SYMBOLS and isinstance(v,Mapping)}


def next_decision_time(current: datetime) -> datetime:
    candidate=current.astimezone(ZoneInfo("America/New_York"))
    candidate=datetime.combine(candidate.date(),RTH_START,tzinfo=ZoneInfo("America/New_York"))
    if current.astimezone(ZoneInfo("America/New_York"))>=candidate: candidate+=timedelta(days=1)
    while candidate.weekday()>=5: candidate+=timedelta(days=1)
    return candidate


def _manual_event(kind:str,row:Mapping[str,Any],symbol:str,previous:Decimal,new:Decimal,current:datetime,override_until:str,event_name:str)->dict[str,Any]:
    side=str(row.get("trd_side","")).upper(); qty=D(row.get("qty")); price=D(row.get("price")); cash=(-qty*price if side=="BUY" else qty*price if side=="SELL" else Decimal("0"))
    order_hash=str(row.get("order_reference","") or ""); deal_hash=str(row.get("deal_reference","") or "")
    seed=f"{kind}|{symbol}|{order_hash}|{deal_hash}|{side}|{qty}|{price}"
    return {"event_id":hashlib.sha256(seed.encode()).hexdigest()[:24],"timestamp_et":current.isoformat(),"event":event_name,"symbol":symbol,"asset_type":asset_type(symbol,row),"side":side,"quantity":decimal_text(qty),"price":decimal_text(price),"order_id_hash":order_hash,"deal_id_hash":deal_hash,"manual_or_strategy":"MANUAL","previous_quantity":decimal_text(previous),"new_quantity":decimal_text(new),"cash_change":decimal_text(cash),"override_until":override_until,"reconciliation_status":"RECONCILING","source_kind":kind}


def process_manual_activity(paths: Paths, account: Mapping[str,Any], baseline: dict[str,Any], current:datetime|None=None) -> dict[str,Any]:
    current=(current or now_utc()).astimezone(ZoneInfo("America/New_York"))
    cursor=read_json(paths.output/"activity_cursor.json",{}) or {}; seen_orders=set(cursor.get("seen_order_references",[])); seen_deals=set(cursor.get("seen_deal_references",[]))
    override=read_json(paths.output/"manual_override_state.json",{"schema_version":1,"symbols":{},"system_state":"READY"}) or {"schema_version":1,"symbols":{},"system_state":"READY"}
    managed_state=read_json(paths.output/"nasdaq_etf_managed_sleeve.json",{"schema_version":1,"positions":{}}) or {"schema_version":1,"positions":{}}
    broker=broker_quantities(account); before=managed_quantities(paths); new_manual=[]; touched=set(); unknown_sources=[]
    manual_open_symbols={str(x.get("code","")).upper() for x in account.get("open_orders",[]) if not str(x.get("remark","") or "").startswith(STRATEGY_PREFIX)}
    for row in account.get("open_orders",[]):
        remark=str(row.get("remark","") or ""); symbol=str(row.get("code","")).upper()
        if remark.startswith("V22_") and not remark.startswith(STRATEGY_PREFIX): unknown_sources.append(str(row.get("order_reference","") or symbol))
        if symbol in ACTIVE_SYMBOLS and not remark.startswith(STRATEGY_PREFIX):
            override.setdefault("symbols",{}).setdefault(symbol,{"state":"MANUAL_OVERRIDE_PENDING","side":str(row.get("trd_side","")).upper(),"override_until":next_decision_time(current).isoformat(),"updated_at_et":current.isoformat(),"automatic_resume_allowed":True})
    for kind,rows,ref_key in (("ORDER",account.get("today_orders",[]),"order_reference"),("DEAL",account.get("today_deals",[]),"deal_reference")):
        for row in rows:
            ref=row.get(ref_key); remark=str(row.get("remark","") or ""); symbol=str(row.get("code","")).upper()
            seen=seen_orders if kind=="ORDER" else seen_deals
            if not ref or ref in seen: continue
            seen.add(ref)
            if kind=="DEAL" and remark.startswith(STRATEGY_PREFIX):
                side=str(row.get("trd_side","")).upper(); signed=D(row.get("qty"))*(Decimal("-1") if side=="SELL" else Decimal("1"))
                append_jsonl(paths.output/"strategy_inventory_ledger.jsonl",{"timestamp_utc":utc_iso(),"event":"STRATEGY_FILL","symbol":symbol,"signed_quantity":decimal_text(signed),"reference":ref,"remark":remark,"price":row.get("price")})
                touched.add(symbol)
            elif not remark.startswith(STRATEGY_PREFIX):
                if remark.startswith("V22_"): unknown_sources.append(ref)
                previous=before.get(symbol,Decimal("0")); new=broker.get(symbol,Decimal("0")); until=next_decision_time(current).isoformat() if symbol in ACTIVE_SYMBOLS else ""
                event_name=("MANUAL_OVERRIDE_SELL" if str(row.get("trd_side","")).upper()=="SELL" else "MANUAL_OVERRIDE_BUY") if symbol in ACTIVE_SYMBOLS else "OUT_OF_SCOPE_PROTECTED_POSITION_CREATED"
                event=_manual_event(kind,row,symbol,previous,new,current,until,event_name); append_jsonl(paths.output/"manual_activity_ledger.jsonl",event); new_manual.append(event); touched.add(symbol)
                if symbol in ACTIVE_SYMBOLS:
                    override["symbols"][symbol]={"state":"MANUAL_OVERRIDE_PENDING" if kind=="ORDER" and symbol in manual_open_symbols else "MANUAL_OVERRIDE_COOLDOWN","side":str(row.get("trd_side","")).upper(),"override_until":until,"updated_at_et":current.isoformat(),"automatic_resume_allowed":True}
                else:
                    qty=broker.get(symbol,Decimal("0")); baseline["positions"][symbol]={"classification":"OUT_OF_SCOPE_PROTECTED_POSITION","asset_type":asset_type(symbol,row),"protected_position_floor":decimal_text(qty),"strategy_control_allowed":False,"strategy_sell_allowed":False,"included_in_strategy_nav":False,"included_in_strategy_cash_pool":False,"updated_at_utc":utc_iso()}
                    append_jsonl(paths.output/"out_of_scope_position_ledger.jsonl",event)
    cursor={"seen_order_references":sorted(seen_orders),"seen_deal_references":sorted(seen_deals),"updated_at_utc":utc_iso()}; atomic_json(paths.output/"activity_cursor.json",cursor)
    for symbol,item in list(override.get("symbols",{}).items()):
        if item.get("state")=="MANUAL_OVERRIDE_PENDING" and symbol not in manual_open_symbols and symbol not in touched:
            item["state"]="MANUAL_OVERRIDE_COOLDOWN"; item["updated_at_et"]=current.isoformat(); touched.add(symbol)
        elif item.get("state")=="MANUAL_OVERRIDE_COOLDOWN" and item.get("override_until") and current>=datetime.fromisoformat(item["override_until"]): item["state"]="READY"; item["updated_at_et"]=current.isoformat()
    for symbol in touched & set(ACTIVE_SYMBOLS): managed_state["positions"][symbol]={"quantity":decimal_text(max(Decimal("0"),broker.get(symbol,Decimal("0")))),"classification":"NASDAQ_ETF_MANAGED_SLEEVE","source":"ACCOUNT_ACTIVITY_RESYNC","updated_at_utc":utc_iso()}
    unresolved=bool(unknown_sources or any(q<0 for q in broker.values()))
    states={x.get("state") for x in override.get("symbols",{}).values()}
    override["system_state"]="DEGRADED" if unresolved else ("MANUAL_OVERRIDE_PENDING" if "MANUAL_OVERRIDE_PENDING" in states else "RECONCILING" if "RECONCILING" in states else "MANUAL_OVERRIDE_COOLDOWN" if "MANUAL_OVERRIDE_COOLDOWN" in states else "READY")
    override["updated_at_et"]=current.isoformat(); override["unknown_order_sources"]=unknown_sources
    atomic_json(paths.output/"manual_override_state.json",override); atomic_json(paths.output/"nasdaq_etf_managed_sleeve.json",managed_state); atomic_json(paths.output/"protected_position_baseline.json",baseline)
    return {"manual_order_detected":bool(new_manual or manual_open_symbols),"manual_open_order":bool(manual_open_symbols),"new_manual_events":new_manual,"override_state":override,"blocked_symbols":sorted(s for s,x in override.get("symbols",{}).items() if x.get("state")!="READY"),"unresolved":unresolved}


def resume_automation_now(paths: Paths, symbol: str, current: datetime | None = None) -> dict[str,Any]:
    symbol=symbol.upper()
    if symbol not in ACTIVE_SYMBOLS: raise R1FError("RESUME_SYMBOL_NOT_IN_EXECUTION_WHITELIST")
    state=read_json(paths.output/"manual_override_state.json",{"schema_version":1,"symbols":{},"system_state":"READY"}) or {"schema_version":1,"symbols":{},"system_state":"READY"}
    item=state.setdefault("symbols",{}).setdefault(symbol,{})
    item.update({"state":"READY","override_until":"","explicit_resume":True,"updated_at_et":(current or now_utc()).astimezone(ZoneInfo("America/New_York")).isoformat()})
    active=[x for x in state["symbols"].values() if x.get("state")!="READY"]
    state["system_state"]="READY" if not active else state.get("system_state","RECONCILING")
    atomic_json(paths.output/"manual_override_state.json",state)
    append_jsonl(paths.output/"manual_activity_ledger.jsonl",{"event_id":hashlib.sha256(f"RESUME|{symbol}|{utc_iso()}".encode()).hexdigest()[:24],"timestamp_et":item["updated_at_et"],"event":"RESUME_AUTOMATION_NOW","symbol":symbol,"manual_or_strategy":"MANUAL","reconciliation_status":"READY"})
    return state


def protected_quantities(baseline: Mapping[str,Any]) -> dict[str,Decimal]:
    return {s:D(v.get("protected_position_floor")) for s,v in baseline.get("positions",{}).items() if isinstance(v,Mapping)}


def reconcile_inventory(account: Mapping[str,Any], managed: Mapping[str,Decimal], protected: Mapping[str,Decimal]) -> dict[str,Any]:
    broker=broker_quantities(account); symbols=set(broker)|set(managed)|set(protected); mismatches=[]
    rows={}
    for symbol in sorted(symbols):
        expected=managed.get(symbol,Decimal("0"))+protected.get(symbol,Decimal("0")); actual=broker.get(symbol,Decimal("0"))
        ok=actual==expected
        rows[symbol]={"broker_total_qty":decimal_text(actual),"nasdaq_etf_managed_qty":decimal_text(managed.get(symbol,Decimal("0"))),"out_of_scope_protected_qty":decimal_text(protected.get(symbol,Decimal("0"))),"expected_total_qty":decimal_text(expected),"reconciled":ok}
        if not ok: mismatches.append(symbol)
    return {"state":"READY" if not mismatches else "DEGRADED","rows":rows,"mismatches":mismatches,"new_entry_allowed":not mismatches,"sell_allowed":not mismatches,"broker_action_allowed":False}


def open_order_reserves(account: Mapping[str,Any]) -> tuple[Decimal,Decimal]:
    manual=Decimal("0"); strategy=Decimal("0")
    for row in account.get("open_orders",[]):
        if str(row.get("trd_side","")).upper() != "BUY": continue
        remaining=max(Decimal("0"),D(row.get("qty"))-D(row.get("dealt_qty"))); reserve=remaining*D(row.get("price"))
        if str(row.get("remark","") or "").startswith(STRATEGY_PREFIX): strategy+=reserve
        else: manual+=reserve
    return manual,strategy


def strategy_cash_pool(account: Mapping[str,Any], minimum_buffer: Decimal) -> dict[str,Any]:
    available=D(account.get("available_cash_usd")); manual,strategy=open_order_reserves(account)
    pool=max(Decimal("0"),available-manual-strategy-minimum_buffer)
    return {"available_usd_cash":available,"manual_open_order_cash_reserve":manual,"strategy_open_order_cash_reserve":strategy,"minimum_cash_buffer":minimum_buffer,"strategy_cash_pool":pool}


def strategy_sleeve_nav(cash_balance: Decimal, owned: Mapping[str,Decimal], prices: Mapping[str,Decimal]) -> Decimal:
    return cash_balance + sum(owned.get(s,Decimal("0"))*prices.get(s,Decimal("0")) for s in ACTIVE_SYMBOLS)


def floor_increment(quantity: Decimal, increment: Decimal) -> Decimal:
    if increment <= 0: raise R1FError("MINIMUM_QUANTITY_INCREMENT_INVALID")
    return (quantity/increment).to_integral_value(rounding=ROUND_DOWN)*increment


def capability_pass(capability: Mapping[str,Any]) -> bool:
    return bool(capability.get("enabled") and capability.get("tradeable") and capability.get("fractional_tradeable") and D(capability.get("minimum_quantity_increment"))>0 and D(capability.get("minimum_notional"))>=0 and "LIMIT" in capability.get("supported_order_types",[]))


def probe_capabilities(paths: Paths) -> dict[str,Any]:
    r1d=load_module(paths.r1d,"v22_047_r1d_for_r1f_capability"); cfg=load_config(paths); profile=r1d.load_connection_profile(paths.repo/"config"/"moomoo_opend_connection.json")
    appdata=paths.output/"runtime"/"moomoo_appdata"; appdata.mkdir(parents=True,exist_ok=True); os.environ["appdata"]=str(appdata)
    try: import moomoo as sdk  # type: ignore
    except Exception as exc:
        return {s:{"enabled":bool(cfg["symbols"][s]["enabled"]),"tradeable":False,"fractional_tradeable":False,"probe_error":f"MOOMOO_IMPORT:{exc}"} for s in (*ACTIVE_SYMBOLS,FUTURE_SYMBOL)}
    quote=None; trade=None; result={}
    try:
        quote=sdk.OpenQuoteContext(host=profile["host"],port=int(profile["port"])); snapshots=r1d.api_rows(quote.get_market_snapshot(list((*ACTIVE_SYMBOLS,FUTURE_SYMBOL))),"CAPABILITY_SNAPSHOT"); by={str(x.get("code","")).upper():x for x in snapshots}
        trade=sdk.OpenSecTradeContext(filter_trdmarket=sdk.TrdMarket.US,host=profile["host"],port=int(profile["port"])); accounts=r1d.api_rows(trade.get_acc_list(),"CAPABILITY_ACCOUNT"); real=[x for x in accounts if str(x.get("trd_env","")).upper()=="REAL"]; selected=(real or accounts)[0]; env=sdk.TrdEnv.REAL if str(selected.get("trd_env","")).upper()=="REAL" else sdk.TrdEnv.SIMULATE; acc=int(selected.get("acc_id") or 0)
        for symbol in (*ACTIVE_SYMBOLS,FUTURE_SYMBOL):
            raw=by.get(symbol,{}); price=D(raw.get("ask_price") or raw.get("last_price")); query_ok=False; query_error=""
            try:
                r1d.api_rows(trade.acctradinginfo_query(order_type=sdk.OrderType.NORMAL,code=symbol,price=float(price),trd_env=env,acc_id=acc,session=sdk.Session.RTH),f"CAPABILITY_{symbol}"); query_ok=True
            except Exception as exc: query_error=f"{type(exc).__name__}:{exc}"
            fractional=raw.get("fractional_tradeable",raw.get("is_support_fractional",raw.get("fractional_enabled")))
            increment=raw.get("minimum_quantity_increment",raw.get("min_qty_increment")); minimum=raw.get("minimum_notional",raw.get("min_notional"))
            enabled=bool(cfg["symbols"][symbol]["enabled"])
            result[symbol]={"symbol":symbol,"enabled":enabled,"tradeable":bool(query_ok and str(raw.get("sec_status","NORMAL")).upper() in {"NORMAL","N/A",""}),"fractional_tradeable":fractional is True,"minimum_quantity_increment":increment,"minimum_notional":minimum,"supported_order_types":["LIMIT"] if query_ok else [],"lot_size":raw.get("lot_size"),"probe_source":"MOOMOO_ACCOUNT_TRADING_INFO_AND_SNAPSHOT","probe_error":query_error or ("FRACTIONAL_CAPABILITY_NOT_EXPOSED_BY_OPENAPI" if fractional is not True else ""),"capability_pass":False}
            result[symbol]["capability_pass"]=capability_pass(result[symbol])
    except Exception as exc:
        result={s:{"symbol":s,"enabled":bool(cfg["symbols"][s]["enabled"]),"tradeable":False,"fractional_tradeable":False,"minimum_quantity_increment":None,"minimum_notional":None,"supported_order_types":[],"probe_error":f"{type(exc).__name__}:{exc}","capability_pass":False} for s in (*ACTIVE_SYMBOLS,FUTURE_SYMBOL)}
    finally:
        for ctx in (quote,trade):
            if ctx is not None:
                try: ctx.close()
                except Exception: pass
    payload={"schema_version":1,"timestamp_utc":utc_iso(),"symbols":result,"iqq_status":"ENABLED" if result.get(FUTURE_SYMBOL,{}).get("capability_pass") else "IQQ_WAITING_FOR_MOOMOO_AVAILABILITY","broker_api_called":False,"trade_api_called":False}; atomic_json(paths.output/"fractional_capability.json",payload); return result


def build_fractional_intents(target_weights: Mapping[str,Any], cash_pool: Decimal, owned: Mapping[str,Decimal], protected: Mapping[str,Decimal], prices: Mapping[str,Decimal], quotes: Mapping[str,Mapping[str,Any]], capabilities: Mapping[str,Mapping[str,Any]], now: datetime, *, blocked: bool, reason_code: str, utilization_pct: Decimal=Decimal("99.5"), broker_sellable: Mapping[str,Decimal] | None=None, blocked_symbols: Sequence[str]=()) -> list[dict[str,Any]]:
    window,window_reason=rth_order_window(now)
    if blocked or not window: return []
    unknown=set(target_weights)-set(ACTIVE_SYMBOLS)
    if unknown: raise R1FError(f"TARGET_SYMBOL_NOT_IN_EXECUTION_WHITELIST:{','.join(sorted(unknown))}")
    if D(target_weights.get("US.TQQQ"))>0 and D(target_weights.get("US.SQQQ"))>0: raise R1FError("TQQQ_SQQQ_SIMULTANEOUS_TARGET_FORBIDDEN")
    sleeve=strategy_sleeve_nav(cash_pool,owned,prices); investable=sleeve*utilization_pct/Decimal("100"); intents=[]; cash=cash_pool
    for side in ("SELL","BUY"):
        for symbol in ACTIVE_SYMBOLS:
            if symbol in blocked_symbols: continue
            cap=capabilities.get(symbol,{})
            if not capability_pass(cap): continue
            price=D(quotes.get(symbol,{}).get("bid" if side=="SELL" else "ask"))
            if price<=0: continue
            target_value=investable*D(target_weights.get(symbol))/Decimal("100"); target_qty=target_value/price
            before=owned.get(symbol,Decimal("0")); delta=target_qty-before
            if side=="SELL" and delta>=0: continue
            if side=="BUY" and delta<=0: continue
            increment=D(cap.get("minimum_quantity_increment")); qty=floor_increment(abs(delta),increment)
            if side=="SELL": qty=min(qty,before,(broker_sellable or {}).get(symbol,before))
            notional=qty*price
            if qty<=0 or notional<D(cap.get("minimum_notional")): continue
            if side=="BUY" and notional>cash: qty=floor_increment(cash/price,increment); notional=qty*price
            if qty<=0: continue
            after=before+qty if side=="BUY" else before-qty
            if side=="SELL" and after<0: raise R1FError("STRATEGY_SELL_EXCEEDS_STRATEGY_OWNED")
            cash_after=cash-notional if side=="BUY" else cash+notional
            fingerprint=f"{symbol}|{side}|{decimal_text(qty)}|{decimal_text(price)}|{reason_code}|{now.date().isoformat()}"
            intent_id=hashlib.sha256(fingerprint.encode()).hexdigest()[:20].upper()
            intents.append({"intent_id":intent_id,"remark":f"{STRATEGY_PREFIX}{intent_id}","symbol":symbol,"side":side,"decimal_quantity":decimal_text(qty),"notional_usd":decimal_text(notional),"order_type":"LIMIT","limit_price":decimal_text(price),"session":"RTH","strategy_owned_inventory_before":decimal_text(before),"nasdaq_etf_managed_inventory_before":decimal_text(before),"protected_manual_inventory":decimal_text(protected.get(symbol,Decimal("0"))),"strategy_owned_inventory_after_expected":decimal_text(after),"nasdaq_etf_managed_inventory_after_expected":decimal_text(after),"cash_before":decimal_text(cash),"cash_after_expected":decimal_text(cash_after),"reason_code":reason_code,"rth_gate":window_reason,"fractional_capability_status":cap.get("fractional_capability_status"),"broker_fractional_api_confirmed":cap.get("broker_fractional_api_confirmed"),"execution_assumption_only":cap.get("execution_assumption_only",False),"broker_action_allowed":False,"trade_api_called":False})
            cash=cash_after
    return intents


def run_cycle(repo: Path, *, probe: bool=False, now: datetime|None=None) -> dict[str,Any]:
    paths=Paths(repo); cfg=load_config(paths); market=read_json(paths.r1d_output/"market_snapshot.json",{}) or {}; account=read_json(paths.r1d_output/"account_snapshot.json",{}) or {}
    if not account.get("account_snapshot_ready") or not market.get("snapshot_ready"): raise R1FError("R1D_MARKET_OR_ACCOUNT_SNAPSHOT_NOT_READY")
    if not (paths.output/"manual_activity_ledger.jsonl").exists():
        created=utc_iso(); append_jsonl(paths.output/"manual_activity_ledger.jsonl",{"event_id":hashlib.sha256(f"BASELINE|{created}".encode()).hexdigest()[:24],"timestamp_et":datetime.now(ZoneInfo("America/New_York")).isoformat(),"event":"MANUAL_ACTIVITY_BASELINE","symbol":"","asset_type":"","side":"","quantity":"0","price":"0","order_id_hash":"","deal_id_hash":"","manual_or_strategy":"BASELINE","previous_quantity":"0","new_quantity":"0","cash_change":"0","override_until":"","reconciliation_status":"READY","detail":"No post-enable manual activity recorded"})
    current=(now or now_utc()).astimezone(ZoneInfo("America/New_York"))
    baseline=protected_baseline(paths,account); manual=process_manual_activity(paths,account,baseline,current); managed=managed_quantities(paths); protected=protected_quantities(baseline); reconciliation=reconcile_inventory(account,managed,protected)
    cash=strategy_cash_pool(account,D(cfg["minimum_cash_buffer_usd"])); append_jsonl(paths.output/"strategy_cash_ledger.jsonl",{"timestamp_utc":utc_iso(),"event":"CASH_POOL_SNAPSHOT",**{k:decimal_text(v) for k,v in cash.items()}})
    capabilities=probe_capabilities(paths) if probe or not (paths.output/"fractional_capability.json").exists() else (read_json(paths.output/"fractional_capability.json",{}) or {}).get("symbols",{})
    plugin=load_module(paths.plugin,"v22_047_r1b_strategy_for_r1f"); state=read_json(paths.output/"v8_strategy_state.json",plugin.default_v8_state()) or plugin.default_v8_state()
    in_window,_=rth_order_window(current); decision_due=bool(in_window and current.time().replace(tzinfo=None)>=RTH_START and state.get("last_decision_date")!=current.date().isoformat())
    prices={s:D(market.get("quotes",{}).get(s,{}).get("latest_price")) for s in ACTIVE_SYMBOLS}; context={"r1f_enabled":True,"market":market,"account":account,"r1f_state":state,"current_et_date":current.date().isoformat(),"decision_due":decision_due,"prices":{s:float(v) for s,v in prices.items()},"strategy_owned_qty":{s:decimal_text(v) for s,v in managed.items()},"strategy_parameters":{}}
    decision=plugin.generate_decision(context); metadata=decision["metadata"]; atomic_json(paths.output/"v8_strategy_state.json",metadata["updated_state"]); atomic_json(paths.output/"strategy_decision.json",decision)
    r1b=load_module(paths.r1b,"v22_047_r1b_control_for_r1f"); parsed=r1b.parse_strategy_decision(decision); benchmark=r1b.BenchmarkMetrics(status="R1F_STRATEGY_SLEEVE",observation_count=0,strategy_return=None,qqq_return=None,excess_return=None,underperformance_threshold=0.0,block_new_entries=False,reason_code="R1F_SEPARATE_SLEEVE_BENCHMARK")
    r1b_cfg=r1b.load_config(paths.repo/"config"/"v22_047_r1b_auto_trading_control.json"); auth=r1b.build_authorization("SHADOW",parsed,account,benchmark,r1b_cfg,execute_requested=False,live_confirmation="")
    blocked=bool(manual["unresolved"] or reconciliation["state"]!="READY"); blocked_symbols=manual["blocked_symbols"]
    sellable={str(x.get("code","")).upper():D(x.get("can_sell_qty")) for x in account.get("positions_detail",[]) if isinstance(x,Mapping)}
    quotes=market.get("quotes",{}); intents=build_fractional_intents(metadata["target_weights"],cash["strategy_cash_pool"],managed,protected,prices,quotes,capabilities,current,blocked=blocked,blocked_symbols=blocked_symbols,reason_code=decision["reason_code"],utilization_pct=D(cfg["execution_cash_utilization_pct"]),broker_sellable=sellable)
    sleeve=strategy_sleeve_nav(cash["strategy_cash_pool"],managed,prices); perf_path=paths.output/"sleeve_performance_state.json"; perf=read_json(perf_path,{}) or {}; qqq=prices["US.QQQ"]
    if not perf: perf={"start_sleeve_nav":decimal_text(sleeve),"start_qqq_price":decimal_text(qqq),"started_at_utc":utc_iso()}
    start_nav=D(perf.get("start_sleeve_nav")); start_qqq=D(perf.get("start_qqq_price")); strategy_return=sleeve/start_nav-1 if start_nav>0 else Decimal("0"); qqq_return=qqq/start_qqq-1 if start_qqq>0 else Decimal("0"); perf.update({"strategy_sleeve_nav":decimal_text(sleeve),"strategy_net_return":decimal_text(strategy_return),"qqq_buy_hold_return":decimal_text(qqq_return),"excess_return_vs_qqq":decimal_text(strategy_return-qqq_return),"manual_holdings_excluded":True,"updated_at_utc":utc_iso()}); atomic_json(perf_path,perf)
    intent_payload={"schema_version":1,"timestamp_utc":utc_iso(),"order_intent_created":bool(intents),"intents":intents,"effective_execution_mode":"SHADOW_ONLY","broker_action_allowed":False,"trade_api_called":False}; atomic_json(paths.output/"shadow_order_intent.json",intent_payload)
    override_state=manual["override_state"]; override_active=bool(blocked_symbols)
    control={"r1b_control_component_called":True,"r1b_authorization":r1b.asdict(auth) if hasattr(r1b,"asdict") else auth.__dict__,"r1f_blocked":blocked,"manual_order_detected":manual["manual_order_detected"],"manual_override_active":override_active,"manual_override_blocked_symbols":blocked_symbols,"manual_override_state":override_state.get("system_state"),"inventory_reconciliation":reconciliation,"effective_execution_mode":"SHADOW_ONLY","broker_action_allowed":False,"trade_api_called":False}; atomic_json(paths.output/"control_decision.json",control)
    override_until={s:x.get("override_until","") for s,x in override_state.get("symbols",{}).items() if x.get("state")!="READY"}
    summary={"schema_version":2,"revision":REVISION,"stage":STAGE,"timestamp_utc":utc_iso(),"final_status":"R1F_PASS_V8_STRATEGY_FRACTIONAL_PROTECTED_SLEEVE_SHADOW_READY","strategy_enabled":True,"strategy_configured":True,"strategy_name":"V8_REFERENCE_TREND_ROTATION","execution_mode":"SHADOW","active_state":metadata["active_state_name"],"available_cash":decimal_text(cash["available_usd_cash"]),"strategy_cash_pool":decimal_text(cash["strategy_cash_pool"]),"strategy_sleeve_nav":decimal_text(sleeve),"nasdaq_etf_managed_sleeve":{s:decimal_text(managed.get(s,Decimal("0"))) for s in ACTIVE_SYMBOLS},"out_of_scope_protected_positions":{s:decimal_text(v) for s,v in protected.items()},"manual_override_active":override_active,"manual_override_until":override_until,"manual_override_state":override_state.get("system_state"),"manual_order_detected":manual["manual_order_detected"],"fractional_capability_ready_symbols":[s for s,v in capabilities.items() if capability_pass(v)],"iqq_status":"IQQ_WAITING_FOR_MOOMOO_AVAILABILITY","inventory_state":reconciliation["state"],"order_intent_created":bool(intents),"effective_execution_mode":"SHADOW_ONLY","broker_action_allowed":False,"trade_api_called":False}; atomic_json(paths.output/"v22_047_r1f_summary.json",summary); atomic_json(paths.output/"account_reconciliation.json",reconciliation); return summary


def run_service(repo: Path, interval: float=30.0) -> int:
    paths=Paths(repo); r1d=load_module(paths.r1d,"v22_047_r1d_lock_for_r1f"); lock=r1d.SingleInstance(paths.output/"runtime"/"r1f.lock"); lock.acquire(); stop=paths.output/"r1f.stop"
    try:
        if stop.exists(): stop.unlink()
        while not stop.exists():
            try: run_cycle(repo)
            except Exception as exc:
                atomic_json(paths.output/"service_error_state.json",{"active":True,"timestamp_utc":utc_iso(),"error":f"{type(exc).__name__}:{exc}","broker_action_allowed":False,"trade_api_called":False})
            deadline=time.monotonic()+max(5.0,interval)
            while not stop.exists() and time.monotonic()<deadline: time.sleep(min(.5,deadline-time.monotonic()))
        return 0
    finally: lock.release()


def main(argv: list[str]|None=None)->int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--repo-root",default=r"D:\us-tech-quant"); p.add_argument("--probe-capabilities",action="store_true"); p.add_argument("--service",action="store_true"); p.add_argument("--interval",type=float,default=30.0); p.add_argument("--resume-symbol"); args=p.parse_args(argv)
    try:
        if args.resume_symbol:
            print(json.dumps(resume_automation_now(Paths(Path(args.repo_root)),args.resume_symbol),ensure_ascii=True,indent=2)); return 0
        if args.service: return run_service(Path(args.repo_root),args.interval)
        summary=run_cycle(Path(args.repo_root),probe=args.probe_capabilities); print(json.dumps(summary,ensure_ascii=True,indent=2)); return 0
    except Exception as exc:
        print(f"final_status=FAIL_{REVISION}",file=sys.stderr); print(f"error={type(exc).__name__}:{exc}",file=sys.stderr); return 2


if __name__=="__main__": raise SystemExit(main())
