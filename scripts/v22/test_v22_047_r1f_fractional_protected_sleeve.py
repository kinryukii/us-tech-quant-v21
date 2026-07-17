from __future__ import annotations
import ast
import importlib.util
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

HERE=Path(__file__).resolve().parent


def load(path:Path,name:str):
    spec=importlib.util.spec_from_file_location(name,path); assert spec and spec.loader
    module=importlib.util.module_from_spec(spec); sys.modules[name]=module; spec.loader.exec_module(module); return module


m=load(HERE/"v22_047_r1f_fractional_protected_sleeve.py","r1f_test")
plugin=load(HERE/"v22_047_r1b_strategy_plugin_template.py","r1f_plugin_test")


def cap(enabled=True):
    return {s:{"enabled":enabled,"tradeable":True,"fractional_tradeable":True,"minimum_quantity_increment":"0.0001","minimum_notional":"1","supported_order_types":["LIMIT"]} for s in m.ACTIVE_SYMBOLS}


def quotes(price="10"):
    return {s:{"bid":price,"ask":price} for s in m.ACTIVE_SYMBOLS}


def rth(hour=10,minute=0):
    return datetime(2026,7,13,hour,minute,tzinfo=ZoneInfo("America/New_York"))


def empty_owned(): return {s:Decimal("0") for s in m.ACTIVE_SYMBOLS}


def test_fractional_quantity_does_not_truncate():
    intents=m.build_fractional_intents({"US.QQQ":100},Decimal("100"),empty_owned(),{}, {s:Decimal("10") for s in m.ACTIVE_SYMBOLS},quotes(),cap(),rth(),blocked=False,reason_code="TEST")
    assert intents and Decimal(intents[0]["decimal_quantity"]) == Decimal("9.95")
    assert "." in intents[0]["decimal_quantity"]


def test_all_available_cash_sizing_and_utilization():
    pool=m.strategy_cash_pool({"available_cash_usd":101,"open_orders":[]},Decimal("1"))
    intents=m.build_fractional_intents({"US.QQQ":100},pool["strategy_cash_pool"],empty_owned(),{}, {s:Decimal("20") for s in m.ACTIVE_SYMBOLS},quotes("20"),cap(),rth(),blocked=False,reason_code="TEST")
    assert pool["strategy_cash_pool"] == Decimal("100")
    assert Decimal(intents[0]["notional_usd"]) == Decimal("99.5")


def test_minimum_cash_buffer_and_open_order_reserves():
    account={"available_cash_usd":"100","open_orders":[{"trd_side":"BUY","qty":"2","dealt_qty":"0.5","price":"10","remark":"manual"},{"trd_side":"BUY","qty":"1","dealt_qty":"0","price":"5","remark":"V22_047_R1F_X"}]}
    pool=m.strategy_cash_pool(account,Decimal("1"))
    assert pool["manual_open_order_cash_reserve"]==Decimal("15")
    assert pool["strategy_open_order_cash_reserve"]==Decimal("5")
    assert pool["strategy_cash_pool"]==Decimal("79")


@pytest.mark.parametrize("symbol",["US.QQQ","US.TQQQ","US.SQQQ","US.IQQQ"])
def test_existing_nasdaq_etf_enters_managed_sleeve(tmp_path,symbol):
    paths=m.Paths(tmp_path); account={"positions_detail":[{"code":symbol,"qty":"2.5"}],"today_orders":[],"today_deals":[]}
    baseline=m.protected_baseline(paths,account)
    assert symbol not in baseline["positions"]
    assert m.managed_quantities(paths)[symbol]==Decimal("2.5")


def test_existing_unrelated_holding_is_out_of_scope_protected(tmp_path):
    paths=m.Paths(tmp_path); account={"positions_detail":[{"code":"US.AAPL","qty":"2.5"}],"today_orders":[],"today_deals":[]}
    baseline=m.protected_baseline(paths,account); row=baseline["positions"]["US.AAPL"]
    assert row["classification"]=="OUT_OF_SCOPE_PROTECTED_POSITION"
    assert row["strategy_control_allowed"] is False and row["strategy_sell_allowed"] is False
    assert row["included_in_strategy_nav"] is False and row["included_in_strategy_cash_pool"] is False


def test_manual_new_buy_is_protected_and_logged(tmp_path):
    paths=m.Paths(tmp_path); base={"positions":{}}; m.atomic_json(paths.output/"activity_cursor.json",{"seen_order_references":[],"seen_deal_references":[]})
    account={"positions_detail":[{"code":"US.AAPL","qty":"3"}],"today_orders":[],"today_deals":[{"deal_reference":"D1","order_reference":"O1","code":"US.AAPL","remark":""}],"open_orders":[]}
    result=m.process_manual_activity(paths,account,base)
    assert result["manual_order_detected"] is True
    saved=m.read_json(paths.output/"protected_position_baseline.json")
    assert saved["positions"]["US.AAPL"]["protected_position_floor"]=="3"


def test_manual_same_symbol_purchase_creates_temporary_override(tmp_path):
    paths=m.Paths(tmp_path); m.atomic_json(paths.output/"activity_cursor.json",{"seen_order_references":[],"seen_deal_references":[]})
    row={"order_reference":"O1","code":"US.QQQ","remark":"","trd_side":"BUY","qty":"1","price":"10"}
    result=m.process_manual_activity(paths,{"positions_detail":[],"today_orders":[row],"today_deals":[],"open_orders":[row]},{"positions":{}},rth())
    assert result["override_state"]["symbols"]["US.QQQ"]["state"]=="MANUAL_OVERRIDE_PENDING"
    assert "US.QQQ" in result["blocked_symbols"]


def test_strategy_cannot_sell_protected_and_only_sells_owned():
    owned=empty_owned(); owned["US.QQQ"]=Decimal("1.25")
    protected={"US.QQQ":Decimal("10")}
    intents=m.build_fractional_intents({"US.QQQ":0},Decimal("0"),owned,protected,{s:Decimal("10") for s in m.ACTIVE_SYMBOLS},quotes(),cap(),rth(),blocked=False,reason_code="EXIT")
    assert len(intents)==1 and intents[0]["side"]=="SELL"
    assert Decimal(intents[0]["decimal_quantity"])==Decimal("1.25")
    assert Decimal(intents[0]["strategy_owned_inventory_after_expected"])==0
    assert Decimal(intents[0]["protected_manual_inventory"])==10


def test_strategy_sell_is_capped_by_broker_sellable():
    owned=empty_owned(); owned["US.QQQ"]=Decimal("2")
    intents=m.build_fractional_intents({"US.QQQ":0},Decimal("0"),owned,{"US.QQQ":Decimal("5")},{s:Decimal("10") for s in m.ACTIVE_SYMBOLS},quotes(),cap(),rth(),blocked=False,reason_code="EXIT",broker_sellable={"US.QQQ":Decimal("0.75")})
    assert Decimal(intents[0]["decimal_quantity"])==Decimal("0.75")


def test_only_strategy_remark_deal_creates_strategy_inventory(tmp_path):
    paths=m.Paths(tmp_path); m.atomic_json(paths.output/"activity_cursor.json",{"seen_order_references":[],"seen_deal_references":[]})
    account={"positions_detail":[],"today_orders":[],"open_orders":[],"today_deals":[{"deal_reference":"D1","order_reference":"O1","code":"US.QQQ","qty":"0.25","price":"10","trd_side":"BUY","remark":"V22_047_R1F_INTENT1"}]}
    m.process_manual_activity(paths,account,{"positions":{}})
    assert m.strategy_owned_quantities(paths)["US.QQQ"]==Decimal("0.25")
    assert not any(x.get("event")=="MANUAL_DEAL_DETECTED" for x in m.read_jsonl(paths.output/"manual_activity_ledger.jsonl"))


def test_strategy_sleeve_nav_excludes_manual_holdings():
    owned=empty_owned(); owned["US.QQQ"]=Decimal("2")
    nav=m.strategy_sleeve_nav(Decimal("50"),owned,{"US.QQQ":Decimal("10"),"US.TQQQ":Decimal("1"),"US.SQQQ":Decimal("1")})
    assert nav==Decimal("70")


@pytest.mark.parametrize("hour,minute,allowed",[(9,44,False),(9,45,True),(15,50,True),(15,51,False),(8,0,False),(16,0,False)])
def test_rth_only_order_gate(hour,minute,allowed):
    assert m.rth_order_window(rth(hour,minute))[0] is allowed


def test_premarket_and_after_hours_generate_no_intent():
    args=({"US.QQQ":100},Decimal("100"),empty_owned(),{}, {s:Decimal("10") for s in m.ACTIVE_SYMBOLS},quotes(),cap())
    assert m.build_fractional_intents(*args,rth(9,0),blocked=False,reason_code="X")==[]
    assert m.build_fractional_intents(*args,rth(16,0),blocked=False,reason_code="X")==[]


def test_iqq_disabled_until_capability_pass():
    config=json.loads((HERE.parents[1]/"config"/"v22_047_r1f_fractional_protected_sleeve.json").read_text(encoding="utf-8"))
    assert config["symbols"]["US.IQQ"]["enabled"] is False
    assert m.capability_pass({"enabled":False,"tradeable":True,"fractional_tradeable":True,"minimum_quantity_increment":".001","minimum_notional":"1","supported_order_types":["LIMIT"]}) is False


def test_iqqq_accepted_in_execution_whitelist():
    intents=m.build_fractional_intents({"US.IQQQ":100},Decimal("100"),empty_owned(),{}, {s:Decimal("10") for s in m.ACTIVE_SYMBOLS},quotes(),cap(),rth(),blocked=False,reason_code="X")
    assert len(intents)==1 and intents[0]["symbol"]=="US.IQQQ"


def test_iqqq_default_v8_weight_remains_zero():
    assert all(weights["US.IQQQ"]==0 for weights in plugin.STATE_WEIGHTS.values())


def test_no_market_order_intent():
    intents=m.build_fractional_intents({"US.QQQ":100},Decimal("100"),empty_owned(),{}, {s:Decimal("10") for s in m.ACTIVE_SYMBOLS},quotes(),cap(),rth(),blocked=False,reason_code="X")
    assert all(x["order_type"]=="LIMIT" and x["session"]=="RTH" for x in intents)


def test_no_trade_api_call_in_r1f_source():
    tree=ast.parse((HERE/"v22_047_r1f_fractional_protected_sleeve.py").read_text(encoding="utf-8"))
    forbidden={"place_order","modify_order","cancel_order","unlock_trade","place_market"}
    called={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
    assert not forbidden.intersection(called)


def test_state_persistence_across_restart(tmp_path):
    path=tmp_path/"state.json"; state=plugin.default_v8_state(); state["active_state"]=1; state["bull_confirm_count"]=3
    m.atomic_json(path,state); loaded=m.read_json(path)
    assert loaded["active_state"]==1 and loaded["bull_confirm_count"]==3


def rising(count=240,start=100): return [start+i*.5+((i%3)*.01) for i in range(count)]
def falling(count=240,start=300): return [start-i*.7+((i%3)*.01) for i in range(count)]
def dates(count=240,start=1): return [f"2025-{((i//28)%12)+1:02d}-{(i%28)+1:02d}" for i in range(count)]


def evaluate(closes,state,date):
    ds=[f"{2024+(i//336):04d}-{((i//28)%12)+1:02d}-{(i%28)+1:02d}" for i in range(len(closes))]
    return plugin.evaluate_v8_reference(closes,ds,state,{"US.QQQ":closes[-1],"US.TQQQ":50,"US.SQQQ":30},empty_owned(),date,decision_due=True)


def test_v8_bull_confirmation_transition_matches_reference():
    state=plugin.default_v8_state(); closes=rising()
    for day in ("2026-07-13","2026-07-14","2026-07-15"):
        result=evaluate(closes,state,day); state=result["state"]
    assert state["active_state"]==plugin.LEVERAGED_BULL
    assert result["reason_code"]=="LOW_VOL_BULL_TREND_CONFIRMED"
    assert plugin.STATE_WEIGHTS[state["active_state"]]=={"US.QQQ":75,"US.TQQQ":25,"US.SQQQ":0,"US.IQQQ":0}


def test_v8_bear_confirmation_transition_matches_reference():
    state=plugin.default_v8_state(); closes=falling()
    for day in ("2026-07-13","2026-07-14"):
        result=evaluate(closes,state,day); state=result["state"]
    assert state["active_state"]==plugin.TACTICAL_DEFENSE
    assert result["reason_code"]=="TACTICAL_BEAR_DEFENSE_CONFIRMED"


def test_no_direct_tqqq_to_sqqq_transition():
    state=plugin.default_v8_state(); state["active_state"]=plugin.LEVERAGED_BULL; state["bull_exit_count"]=1
    result=evaluate(falling(),state,"2026-07-13")
    assert result["state"]["active_state"]==plugin.CORE_QQQ
    assert result["state"]["active_state"]!=plugin.TACTICAL_DEFENSE


def test_sqqq_max_three_day_exit():
    state=plugin.default_v8_state(); state.update({"active_state":-1,"trading_day_index":250,"state_entry_day":247})
    result=evaluate(falling(),state,"2026-07-13")
    assert result["state"]["active_state"]==plugin.CORE_QQQ
    assert result["reason_code"]=="TACTICAL_DEFENSE_EXIT_TO_QQQ"


def test_tqqq_disaster_stop_and_sqqq_trailing_stop():
    bull=plugin.default_v8_state(); bull.update({"active_state":1,"tqqq_entry_reference":100})
    result=plugin.evaluate_v8_reference(rising(),dates(),bull,{"US.TQQQ":89,"US.SQQQ":30},{"US.TQQQ":"1"},"2026-07-13",decision_due=False)
    assert result["reason_code"]=="TQQQ_DISASTER_STOP_TO_QQQ"
    defense=plugin.default_v8_state(); defense.update({"active_state":-1,"sqqq_entry_reference":100,"sqqq_highest_price":110})
    result=plugin.evaluate_v8_reference(falling(),dates(),defense,{"US.TQQQ":50,"US.SQQQ":106},{"US.SQQQ":"1"},"2026-07-13",decision_due=False)
    assert result["reason_code"]=="SQQQ_TRAILING_PROFIT_TO_QQQ"


def test_inventory_reconciliation_mismatch_degrades():
    account={"positions_detail":[{"code":"US.QQQ","qty":"5"}]}; owned={"US.QQQ":Decimal("1")}; protected={"US.QQQ":Decimal("3")}
    result=m.reconcile_inventory(account,owned,protected)
    assert result["state"]=="DEGRADED" and result["new_entry_allowed"] is False and result["sell_allowed"] is False


def test_dashboard_exposes_r2a_sleeve_and_override_controls():
    text=(HERE/"v22_047_r1e_windows_service_hardening.py").read_text(encoding="utf-8")
    for label in ("STRATEGY CASH POOL","STRATEGY SLEEVE NAV","NASDAQ ETF MANAGED SLEEVE","OUT OF SCOPE PROTECTED POSITIONS","MANUAL OVERRIDE ACTIVE","MANUAL OVERRIDE UNTIL","AVAILABLE CASH","RESUME AUTOMATION NOW","FRACTIONAL CAPABILITY","IQQ WAITING FOR MOOMOO AVAILABILITY","ACCOUNT TOTAL"):
        assert label in text
    assert "/api/r1f/resume-automation" in text


def manual_deal(symbol,side,qty,new_qty,asset_detail=None):
    row={"deal_reference":f"D-{symbol}-{side}","order_reference":f"O-{symbol}-{side}","code":symbol,"remark":"","trd_side":side,"qty":qty,"price":"10"}
    position={"code":symbol,"qty":new_qty}
    if asset_detail: position.update(asset_detail); row.update(asset_detail)
    return {"positions_detail":[position],"today_orders":[],"today_deals":[row],"open_orders":[]}


def test_non_nasdaq_stock_option_and_unrelated_etf_cannot_be_modified(tmp_path):
    paths=m.Paths(tmp_path)
    account={"positions_detail":[{"code":"US.AAPL","qty":"2"},{"code":"US.AAPL240119C00100000","qty":"1","position_type":"OPTION"},{"code":"US.SPY","qty":"3"}],"today_orders":[],"today_deals":[]}
    baseline=m.protected_baseline(paths,account)
    assert set(baseline["positions"])=={"US.AAPL","US.AAPL240119C00100000","US.SPY"}
    assert all(not row["strategy_sell_allowed"] for row in baseline["positions"].values())
    assert baseline["positions"]["US.AAPL240119C00100000"]["asset_type"]=="OPTION"


def test_manual_sell_takes_precedence_and_is_not_immediately_reversed(tmp_path):
    paths=m.Paths(tmp_path); base=m.protected_baseline(paths,{"positions_detail":[{"code":"US.QQQ","qty":"5"}],"today_orders":[],"today_deals":[]})
    result=m.process_manual_activity(paths,manual_deal("US.QQQ","SELL","1","4"),base,rth())
    assert m.managed_quantities(paths)["US.QQQ"]==Decimal("4")
    assert result["new_manual_events"][0]["event"]=="MANUAL_OVERRIDE_SELL"
    intents=m.build_fractional_intents({"US.QQQ":100},Decimal("100"),m.managed_quantities(paths),{}, {s:Decimal("10") for s in m.ACTIVE_SYMBOLS},quotes(),cap(),rth(),blocked=False,blocked_symbols=result["blocked_symbols"],reason_code="CORE")
    assert not any(x["symbol"]=="US.QQQ" for x in intents)


def test_manual_buy_nasdaq_etf_is_not_immediately_sold(tmp_path):
    paths=m.Paths(tmp_path); base=m.protected_baseline(paths,{"positions_detail":[],"today_orders":[],"today_deals":[]})
    result=m.process_manual_activity(paths,manual_deal("US.TQQQ","BUY","1.5","1.5"),base,rth())
    assert m.managed_quantities(paths)["US.TQQQ"]==Decimal("1.5")
    intents=m.build_fractional_intents({"US.TQQQ":0},Decimal("0"),m.managed_quantities(paths),{}, {s:Decimal("10") for s in m.ACTIVE_SYMBOLS},quotes(),cap(),rth(),blocked=False,blocked_symbols=result["blocked_symbols"],reason_code="CORE")
    assert intents==[]


def test_manual_buy_non_nasdaq_becomes_protected(tmp_path):
    paths=m.Paths(tmp_path); base=m.protected_baseline(paths,{"positions_detail":[],"today_orders":[],"today_deals":[]})
    result=m.process_manual_activity(paths,manual_deal("US.AAPL","BUY","2","2"),base,rth())
    saved=m.read_json(paths.output/"protected_position_baseline.json")
    assert saved["positions"]["US.AAPL"]["classification"]=="OUT_OF_SCOPE_PROTECTED_POSITION"
    assert result["new_manual_events"][0]["event"]=="OUT_OF_SCOPE_PROTECTED_POSITION_CREATED"


def test_cash_pool_changes_with_manual_purchase_and_sale():
    before=m.strategy_cash_pool({"available_cash_usd":"100","open_orders":[]},Decimal("1"))["strategy_cash_pool"]
    after_buy=m.strategy_cash_pool({"available_cash_usd":"80","open_orders":[]},Decimal("1"))["strategy_cash_pool"]
    after_sell=m.strategy_cash_pool({"available_cash_usd":"120","open_orders":[]},Decimal("1"))["strategy_cash_pool"]
    assert after_buy<before<after_sell


def test_manual_override_expires_at_next_decision(tmp_path):
    paths=m.Paths(tmp_path); base=m.protected_baseline(paths,{"positions_detail":[],"today_orders":[],"today_deals":[]})
    account=manual_deal("US.QQQ","BUY","1","1")
    m.process_manual_activity(paths,account,base,rth())
    later=datetime(2026,7,14,9,45,tzinfo=ZoneInfo("America/New_York"))
    result=m.process_manual_activity(paths,account,base,later)
    assert result["override_state"]["symbols"]["US.QQQ"]["state"]=="READY"


def test_explicit_resume_clears_cooldown(tmp_path):
    paths=m.Paths(tmp_path); m.atomic_json(paths.output/"manual_override_state.json",{"schema_version":1,"system_state":"MANUAL_OVERRIDE_COOLDOWN","symbols":{"US.SQQQ":{"state":"MANUAL_OVERRIDE_COOLDOWN","override_until":"2099-01-01T09:45:00-05:00"}}})
    state=m.resume_automation_now(paths,"US.SQQQ",rth())
    assert state["symbols"]["US.SQQQ"]["state"]=="READY" and state["system_state"]=="READY"


def test_normal_manual_activity_does_not_permanently_degrade(tmp_path):
    paths=m.Paths(tmp_path); base=m.protected_baseline(paths,{"positions_detail":[],"today_orders":[],"today_deals":[]})
    result=m.process_manual_activity(paths,manual_deal("US.QQQ","BUY","1","1"),base,rth())
    assert result["unresolved"] is False and result["override_state"]["system_state"]!="DEGRADED"


def test_unresolved_unknown_order_source_enters_degraded(tmp_path):
    paths=m.Paths(tmp_path); base=m.protected_baseline(paths,{"positions_detail":[],"today_orders":[],"today_deals":[]})
    row={"order_reference":"UNKNOWN","code":"US.QQQ","remark":"V22_UNKNOWN_SOURCE","trd_side":"BUY","qty":"1","price":"10"}
    result=m.process_manual_activity(paths,{"positions_detail":[],"today_orders":[row],"today_deals":[],"open_orders":[row]},base,rth())
    assert result["unresolved"] is True and result["override_state"]["system_state"]=="DEGRADED"
