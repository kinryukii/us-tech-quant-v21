#!/usr/bin/env python
from __future__ import annotations

import ast
import json
import sys
from datetime import datetime,timezone
from pathlib import Path

STAGE="V22.047_R1G_SHADOW_FRACTIONAL_ASSUMPTION_AND_EXECUTION_ARMING"


def read(path:Path):
    try:return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:return {}


def main(argv=None):
    repo=Path(argv[0] if argv else r"D:\us-tech-quant").resolve(); out=repo/"outputs"/"v22"/STAGE
    summary=read(out/"r1g_summary.json"); assumption=read(out/"fractional_assumption.json"); auth=read(out/"execution_authorization_state.json"); target=read(out/"target_portfolio_snapshot.json"); plan=read(out/"shadow_fractional_order_intents.json"); cash=read(out/"shadow_cash_projection.json")
    calls=set(); forbidden={"place_order","modify_order","cancel_order","unlock_trade","place_market"}
    for path in (repo/"scripts"/"v22"/"v22_047_r1g_shadow_fractional_assumption_and_execution_arming.py",repo/"scripts"/"v22"/"v22_047_r1f_fractional_protected_sleeve.py"):
        tree=ast.parse(path.read_text(encoding="utf-8")); calls|={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
    checks={
        "final_status":summary.get("final_status")=="R1G_PASS_SHADOW_FRACTIONAL_PLANNING_AND_EXECUTION_ARMING_READY",
        "strategy_enabled_configured":summary.get("strategy_enabled") is True and summary.get("strategy_configured") is True,
        "shadow_only":summary.get("execution_mode")=="SHADOW" and summary.get("effective_execution_mode")=="SHADOW_ONLY",
        "user_assumption_not_broker_confirmation":assumption.get("fractional_capability_status")=="USER_CONFIRMED_RTH_APP" and assumption.get("broker_fractional_api_confirmed") is False and assumption.get("execution_assumption_only") is True,
        "execution_disarmed":auth.get("execution_authorization")=="DISARMED",
        "iqqq_zero_weight":target.get("target_weights",{}).get("US.IQQQ")==0,
        "shadow_plan_not_sent":plan.get("shadow_plan_only") is True and plan.get("not_sent_to_broker") is True,
        "decimal_limit_rth":all(x.get("quantity_type")=="Decimal" and x.get("order_type")=="LIMIT" and x.get("session")=="RTH" for x in plan.get("intents",[])),
        "cash_projection_complete":all(k in cash for k in ("cash_before","cash_reserved","cash_used","cash_after_expected","total_target_notional","uninvested_cash")),
        "no_broker_mutation_calls":not forbidden.intersection(calls),
        "broker_blocked":summary.get("broker_action_allowed") is False and summary.get("real_trade_api_called") is False,
    }
    final="R1G_PASS_SHADOW_FRACTIONAL_PLANNING_AND_EXECUTION_ARMING_READY" if all(checks.values()) else "R1G_VALIDATION_FAILED"
    report={"schema_version":1,"timestamp_utc":datetime.now(timezone.utc).isoformat(),"final_status":final,"checks":checks,"broker_action_allowed":False,"real_trade_api_called":False}
    (out/"validation_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=[f"# {STAGE} Validation Report","",f"Final status: **{final}**","","| Check | Result |","|---|---|"]+[f"| {k} | {'PASS' if v else 'FAIL'} |" for k,v in checks.items()]+["","SHADOW PLAN ONLY — NOT SENT TO BROKER."]
    (out/"validation_report.md").write_text("\n".join(lines)+"\n",encoding="utf-8"); print(f"final_status={final}"); return 0 if all(checks.values()) else 1


if __name__=="__main__":raise SystemExit(main(sys.argv[1:]))
