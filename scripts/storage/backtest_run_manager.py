"""R2A isolated backtest run-directory manager (no market-data copying)."""
from __future__ import annotations
import json
import secrets
from pathlib import Path
from storage_r2a import BACKTEST_ROOT, assert_safety_flags, storage_guard_result, utc_now

def create_backtest_run(strategy_id: str, git_commit: str, research_start_date: str, research_end_date: str, universe: list[str]) -> Path:
    if not strategy_id or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-" for ch in strategy_id):
        raise ValueError("invalid strategy_id")
    run_id = f"{utc_now().replace(':','').replace('+00:00','Z').replace('-','')}_{secrets.token_hex(4)}"
    root = BACKTEST_ROOT / strategy_id / run_id
    for name in ("logs", "charts", "report", "derived"):
        (root / name).mkdir(parents=True, exist_ok=False)
    payload = {"strategy_id":strategy_id,"strategy_version":"UNSPECIFIED","git_commit":git_commit,"run_id":run_id,"run_start":utc_now(),"run_end":"","research_start_date":research_start_date,"research_end_date":research_end_date,"execution_assumption":"RESEARCH_ONLY","cost_assumption":"UNSPECIFIED","universe":universe,"ticker":universe,"data_files":[],"snapshot_id":"","input_data_copied":False,"duplicate_market_data_count":0,"broker_action_allowed":False,"official_adoption_allowed":False,"research_only":True}
    assert_safety_flags(payload)
    (root / "run_config.json").write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
    (root / "input_manifest.json").write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
    return root

def validate_backtest_run(root: Path) -> dict:
    config = json.loads((root / "run_config.json").read_text(encoding="utf-8"))
    assert_safety_flags(config)
    return {"run_directory":str(root),"run_id":config["run_id"],"input_data_copied":config["input_data_copied"],"duplicate_market_data_count":config["duplicate_market_data_count"],"guard":storage_guard_result(root / "summary.json","backtest",config["run_id"]),"result":"PASS"}
