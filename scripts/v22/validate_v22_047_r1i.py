#!/usr/bin/env python
from __future__ import annotations
import importlib.util, json, sys
from pathlib import Path

def load(path, name):
    spec=importlib.util.spec_from_file_location(name,path); assert spec and spec.loader
    module=importlib.util.module_from_spec(spec); sys.modules[name]=module; spec.loader.exec_module(module); return module

def main(argv=None):
    repo=Path(argv[0] if argv else r"D:\us-tech-quant").resolve(); path=repo/"scripts"/"v22"/"v22_047_r1i_paper_soak_replay_fault_injection_and_live_readiness_gate.py"; m=load(path,"r1i_validator"); summary=m.write_summary(repo); paths=m.Paths(repo); gate=m.read_json(paths.live_gate,{}) or {}; replay=m._csv_rows(paths.replay_results); faults=m._csv_rows(paths.fault_results)
    checks={"final_status":summary.get("final_status")==m.FINAL_STATUS,"replay_25_deterministic":len(replay)==25 and all(x["result"]=="PASS" for x in replay),"faults_test_only":len(faults)==11 and all(x["production_enabled"]=="False" for x in faults),"live_false":gate.get("live_ready") is False and gate.get("live_available") is False,"protected_zero":gate.get("protected_asset_action_count")==0,"real_api_zero":gate.get("real_trade_api_call_count")==0,"safe_defaults":summary.get("default_execution_mode")=="SHADOW" and summary.get("paper_armed") is False}
    report={"schema_version":1,"final_status":m.FINAL_STATUS if all(checks.values()) else "R1I_VALIDATION_FAILED","checks":checks,"live_ready":False,"broker_action_allowed":False,"real_trade_api_called":False}; (paths.output/"validation_report.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8"); print(f"final_status={report['final_status']}"); return 0 if all(checks.values()) else 1

if __name__=="__main__": raise SystemExit(main(sys.argv[1:]))
