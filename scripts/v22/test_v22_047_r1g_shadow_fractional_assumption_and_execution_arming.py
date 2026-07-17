from __future__ import annotations

import ast
import importlib.util
import json
import shutil
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]


def load(path:Path,name:str):
    spec=importlib.util.spec_from_file_location(name,path); assert spec and spec.loader
    module=importlib.util.module_from_spec(spec); sys.modules[name]=module; spec.loader.exec_module(module); return module


g=load(HERE/"v22_047_r1g_shadow_fractional_assumption_and_execution_arming.py","r1g_test")
f=load(HERE/"v22_047_r1f_fractional_protected_sleeve.py","r1f_for_r1g_test")
plugin=load(HERE/"v22_047_r1b_strategy_plugin_template.py","plugin_for_r1g_test")


def write(path:Path,payload):
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(payload),encoding="utf-8")


@pytest.fixture
def r1g_repo(tmp_path):
    scripts=tmp_path/"scripts"/"v22"; config=tmp_path/"config"; scripts.mkdir(parents=True); config.mkdir()
    for name in ("v22_047_r1g_shadow_fractional_assumption_and_execution_arming.py","v22_047_r1f_fractional_protected_sleeve.py","v22_047_r1b_strategy_plugin_template.py"):
        shutil.copy2(HERE/name,scripts/name)
    shutil.copy2(REPO/"config"/"v22_047_r1g_shadow_fractional_assumption.json",config/"v22_047_r1g_shadow_fractional_assumption.json")
    paths=g.Paths(tmp_path)
    quotes={s:{"latest_price":"10","bid":"10","ask":"10","data_fresh":True} for s in g.ACTIVE_SYMBOLS}
    write(paths.r1d_output/"market_snapshot.json",{"snapshot_ready":True,"quotes":quotes})
    write(paths.r1d_output/"account_snapshot.json",{"account_snapshot_ready":True,"available_cash_usd":"100","open_orders":[],"positions_detail":[]})
    weights={"US.QQQ":100,"US.TQQQ":0,"US.SQQQ":0,"US.IQQQ":0}
    write(paths.r1f_output/"strategy_decision.json",{"action":"HOLD","symbol":None,"target_notional_usd":0,"confidence":1,"reason_code":"CORE","metadata":{"strategy_configured":True,"strategy_name":"V8_REFERENCE_TREND_ROTATION","active_state_name":"CORE_QQQ","target_weights":weights}})
    write(paths.r1f_output/"control_decision.json",{"r1f_blocked":False,"manual_override_blocked_symbols":[]})
    write(paths.r1f_output/"protected_position_baseline.json",{"schema_version":2,"positions":{},"r2a_classification_complete":True})
    write(paths.r1f_output/"nasdaq_etf_managed_sleeve.json",{"positions":{}})
    write(paths.r1f_output/"fractional_capability.json",{"symbols":{s:{"tradeable":True,"fractional_tradeable":False} for s in g.ACTIVE_SYMBOLS}})
    return tmp_path,paths


def rth(hour=10,minute=0):return datetime(2026,7,13,hour,minute,tzinfo=ZoneInfo("America/New_York"))


def test_user_confirmed_rth_app_permits_shadow_intent(r1g_repo):
    repo,paths=r1g_repo; result=g.run_cycle(repo,now=rth()); plan=g.read_json(paths.output/"shadow_fractional_order_intents.json")
    assert result["order_intent_created"] is True and plan["intents"]


def test_user_confirmed_rth_app_does_not_permit_real_api(r1g_repo):
    repo,paths=r1g_repo; result=g.run_cycle(repo,now=rth()); assumption=g.read_json(paths.output/"fractional_assumption.json")
    assert assumption["broker_fractional_api_confirmed"] is False and assumption["real_api_permission"] is False
    assert result["broker_action_allowed"] is False and result["real_trade_api_called"] is False


def test_decimal_quantity_uses_point_zero_zero_one_increment_without_integer_truncation(r1g_repo):
    repo,paths=r1g_repo; g.run_cycle(repo,now=rth()); intent=g.read_json(paths.output/"shadow_fractional_order_intents.json")["intents"][0]
    qty=Decimal(intent["decimal_quantity"])
    assert qty%Decimal("0.001")==0 and qty!=qty.to_integral_value()
    assert intent["quantity_type"]=="Decimal" and intent["integer_truncation_forbidden"] is True


def test_shadow_intent_marked_assumption_only(r1g_repo):
    repo,paths=r1g_repo; g.run_cycle(repo,now=rth()); intent=g.read_json(paths.output/"shadow_fractional_order_intents.json")["intents"][0]
    assert intent["fractional_capability_status"]=="USER_CONFIRMED_RTH_APP"
    assert intent["broker_fractional_api_confirmed"] is False and intent["execution_assumption_only"] is True
    assert intent["plan_status"]=="SHADOW PLAN ONLY" and intent["broker_delivery_status"]=="NOT SENT TO BROKER"


def test_v8_enabled_does_not_arm_execution(r1g_repo):
    repo,paths=r1g_repo; result=g.run_cycle(repo,now=rth()); auth=g.read_json(paths.output/"execution_authorization_state.json")
    assert result["strategy_enabled"] is True and auth["execution_authorization"]=="DISARMED"


def test_shadow_creates_plan_without_api_call(r1g_repo):
    repo,paths=r1g_repo; g.run_cycle(repo,now=rth()); plan=g.read_json(paths.output/"shadow_fractional_order_intents.json")
    assert plan["order_intent_created"] is True and plan["broker_action_allowed"] is False and plan["real_trade_api_called"] is False


def test_paper_requires_explicit_double_confirmation(r1g_repo):
    _,paths=r1g_repo
    with pytest.raises(g.R1GError,match="DOUBLE_CONFIRMATION"):
        g.request_paper_arm(paths,first_confirmation=True,second_confirmation="NO",current=rth())


def test_paper_uses_simulate_environment_only(r1g_repo):
    _,paths=r1g_repo; state=g.request_paper_arm(paths,first_confirmation=True,second_confirmation="CONFIRM_PAPER_SIMULATE_ONLY",current=rth())
    assert state["execution_authorization"]=="PAPER_ARMED" and state["paper_environment"]=="TrdEnv.SIMULATE"
    assert state["real_environment_allowed"] is False and state["expires_at_utc"]


def test_live_remains_unavailable(r1g_repo):
    _,paths=r1g_repo; result=g.request_live_arm(paths)
    assert result["ok"] is False and result["error"]=="LIVE_NOT_AVAILABLE" and result["broker_action_allowed"] is False


def test_out_of_scope_and_option_assets_remain_untouched(r1g_repo):
    repo,paths=r1g_repo
    account=g.read_json(paths.r1d_output/"account_snapshot.json"); account["positions_detail"]=[{"code":"US.AAPL","qty":"2"},{"code":"US.AAPL260117C00100000","qty":"1","position_type":"OPTION"}]; write(paths.r1d_output/"account_snapshot.json",account)
    baseline={"schema_version":2,"r2a_classification_complete":True,"positions":{"US.AAPL":{"protected_position_floor":"2","classification":"OUT_OF_SCOPE_PROTECTED_POSITION","strategy_sell_allowed":False},"US.AAPL260117C00100000":{"protected_position_floor":"1","classification":"OUT_OF_SCOPE_PROTECTED_POSITION","strategy_sell_allowed":False}}}; write(paths.r1f_output/"protected_position_baseline.json",baseline)
    g.run_cycle(repo,now=rth()); plan=g.read_json(paths.output/"shadow_fractional_order_intents.json")
    assert all(x["symbol"] in g.ACTIVE_SYMBOLS for x in plan["intents"])


def test_manual_override_still_takes_precedence(r1g_repo):
    repo,paths=r1g_repo; write(paths.r1f_output/"control_decision.json",{"r1f_blocked":False,"manual_override_blocked_symbols":["US.QQQ"]})
    result=g.run_cycle(repo,now=rth()); assert result["order_intent_created"] is False


def test_iqqq_accepted_but_v8_weight_remains_zero(r1g_repo):
    repo,paths=r1g_repo; g.run_cycle(repo,now=rth()); target=g.read_json(paths.output/"target_portfolio_snapshot.json")
    assert "US.IQQQ" in g.ACTIVE_SYMBOLS and target["target_weights"]["US.IQQQ"]==0 and target["iqqq_default_weight_zero"] is True
    assert all(weights["US.IQQQ"]==0 for weights in plugin.STATE_WEIGHTS.values())


@pytest.mark.parametrize("hour,minute",[(9,44),(15,51),(8,0),(16,0)])
def test_rth_gate_blocks_premarket_and_after_hours(r1g_repo,hour,minute):
    repo,paths=r1g_repo; result=g.run_cycle(repo,now=rth(hour,minute)); assert result["order_intent_created"] is False


def test_shadow_cash_projection_fields(r1g_repo):
    repo,paths=r1g_repo; g.run_cycle(repo,now=rth()); projection=g.read_json(paths.output/"shadow_cash_projection.json")
    for key in ("cash_before","cash_reserved","cash_used","cash_after_expected","total_target_notional","uninvested_cash"):assert key in projection


def test_no_broker_mutation_api_calls():
    forbidden={"place_order","modify_order","cancel_order","unlock_trade","place_market"}; called=set()
    for path in (HERE/"v22_047_r1g_shadow_fractional_assumption_and_execution_arming.py",HERE/"v22_047_r1f_fractional_protected_sleeve.py"):
        tree=ast.parse(path.read_text(encoding="utf-8")); called|={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
    assert not forbidden.intersection(called)


def test_dashboard_exposes_r1g_planning_and_arming_controls():
    text=(HERE/"v22_047_r1e_windows_service_hardening.py").read_text(encoding="utf-8")
    for label in ("FRACTIONAL CAPABILITY STATUS","USER CONFIRMED RTH APP SUPPORT","BROKER API CONFIRMED = FALSE","SHADOW ASSUMPTION ACTIVE","CURRENT V8 STATE","TARGET PORTFOLIO","PLANNED FRACTIONAL ORDERS","EXPECTED CASH AFTER","EXECUTION AUTHORIZATION","PAPER ARM","LIVE NOT AVAILABLE","SHADOW PLAN ONLY","NOT SENT TO BROKER"):
        assert label in text
    assert "/api/r1g/paper-arm" in text and "/api/r1g/live-arm" in text
    assert "CONFIRM_PAPER_SIMULATE_ONLY" in text
