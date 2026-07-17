#!/usr/bin/env python
from __future__ import annotations
import ast,json,sys
from datetime import datetime,timezone
from pathlib import Path

STAGE="V22.047_R1F_V8_REFERENCE_ROTATION_FRACTIONAL_RTH_PROTECTED_SLEEVE_SHADOW"

def read(path):
    try:return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:return {}

def main(argv=None):
    repo=Path(argv[0] if argv else r"D:\us-tech-quant").resolve(); out=repo/"outputs"/"v22"/STAGE
    summary=read(out/"v22_047_r1f_summary.json"); cap=read(out/"fractional_capability.json"); baseline=read(out/"protected_position_baseline.json"); recon=read(out/"account_reconciliation.json"); state=read(out/"v8_strategy_state.json"); intent=read(out/"shadow_order_intent.json"); tests=read(out/"target_test_result.json"); config=read(repo/"config"/"v22_047_r1f_fractional_protected_sleeve.json"); managed=read(out/"nasdaq_etf_managed_sleeve.json"); override=read(out/"manual_override_state.json")
    required_state={"active_state","state_entry_day","bull_confirm_count","bull_exit_count","bear_confirm_count","last_sqqq_exit_day","tqqq_entry_reference","sqqq_entry_reference","sqqq_highest_price","last_decision_date","last_rebalance_date"}
    forbidden={"place_order","modify_order","cancel_order","unlock_trade","place_market"}; calls=set()
    for path in (repo/"scripts"/"v22"/"v22_047_r1f_fractional_protected_sleeve.py",repo/"scripts"/"v22"/"v22_047_r1b_strategy_plugin_template.py"):
        tree=ast.parse(path.read_text(encoding="utf-8")); calls|={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
    checks={
        "target_tests_passed":tests.get("passed") is True,
        "v8_state_persisted":required_state.issubset(state),
        "r2a_position_classification":baseline.get("r2a_classification_complete") is True and all(x.get("classification")=="OUT_OF_SCOPE_PROTECTED_POSITION" and x.get("strategy_sell_allowed") is False for x in baseline.get("positions",{}).values()),
        "nasdaq_managed_sleeve_present":isinstance(managed.get("positions"),dict),
        "inventory_reconciled":recon.get("state")=="READY",
        "iqq_disabled_waiting":summary.get("iqq_status")=="IQQ_WAITING_FOR_MOOMOO_AVAILABILITY" and cap.get("symbols",{}).get("US.IQQ",{}).get("enabled") is False,
        "iqqq_execution_whitelisted_zero_default":config.get("execution_whitelist")==["US.QQQ","US.TQQQ","US.SQQQ","US.IQQQ"] and config.get("symbols",{}).get("US.IQQQ",{}).get("default_v8_weight_pct")==0,
        "manual_override_state_machine":override.get("system_state") in {"READY","MANUAL_OVERRIDE_PENDING","MANUAL_OVERRIDE_COOLDOWN","RECONCILING","DEGRADED"},
        "shadow_only":summary.get("effective_execution_mode")=="SHADOW_ONLY",
        "broker_action_blocked":summary.get("broker_action_allowed") is False,
        "trade_api_not_called":summary.get("trade_api_called") is False,
        "no_broker_mutation_calls":not forbidden.intersection(calls),
        "orders_limit_rth_decimal":all(x.get("order_type")=="LIMIT" and x.get("session")=="RTH" and isinstance(x.get("decimal_quantity"),str) for x in intent.get("intents",[])),
        "manual_ledgers_present":all((out/name).exists() for name in ("strategy_inventory_ledger.jsonl","manual_activity_ledger.jsonl","out_of_scope_position_ledger.jsonl","strategy_cash_ledger.jsonl","nasdaq_etf_managed_sleeve.json","manual_override_state.json")),
    }
    final="R1F_PASS_V8_STRATEGY_FRACTIONAL_PROTECTED_SLEEVE_SHADOW_READY" if all(checks.values()) else "R1F_VALIDATION_FAILED"
    report={"schema_version":2,"revision":"V22.047_R1F_R2A","timestamp_utc":datetime.now(timezone.utc).isoformat(),"final_status":final,"checks":checks,"fractional_capability_note":"Actual OpenAPI probe is fail-closed when explicit fractional increment/minimum notional fields are absent.","broker_action_allowed":False,"trade_api_called":False}
    (out/"validation_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=[f"# {STAGE} R2A Validation Report","",f"Final status: **{final}**","","| Check | Result |","|---|---|"]+[f"| {k} | {'PASS' if v else 'FAIL'} |" for k,v in checks.items()]+["","## Capability probe","",f"- Ready symbols: `{summary.get('fractional_capability_ready_symbols',[])}`","- IQQ: `IQQ_WAITING_FOR_MOOMOO_AVAILABILITY`","- IQQQ is execution-whitelisted with default V8 weight 0.","- Missing explicit fractional capability fields remain fail-closed.","","## Execution","","- execution_mode=`SHADOW`","- effective_execution_mode=`SHADOW_ONLY`","- broker_action_allowed=`False`","- trade_api_called=`False`"]
    (out/"validation_report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(f"final_status={final}");return 0 if final.startswith("R1F_PASS") else 1

if __name__=="__main__":raise SystemExit(main(sys.argv[1:]))
