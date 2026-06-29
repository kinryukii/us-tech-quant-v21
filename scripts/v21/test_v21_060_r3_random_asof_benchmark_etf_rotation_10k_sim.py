#!/usr/bin/env python
"""Contract tests for V21.060-R3 benchmark/rotation simulation."""
from __future__ import annotations
import csv, hashlib, importlib.util, json, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_060_r3_random_asof_benchmark_etf_rotation_10k_sim.py"
WRAPPER = ROOT / "scripts/v21/run_v21_060_r3_random_asof_benchmark_etf_rotation_10k_sim.ps1"
spec = importlib.util.spec_from_file_location("v21_060_r3", SCRIPT)
module = importlib.util.module_from_spec(spec); assert spec.loader; spec.loader.exec_module(module)
REQUIRED = (module.RESULTS_NAME,module.PORTFOLIO_NAME,module.SEED_NAME,module.OVERALL_NAME,module.PAIR_NAME,module.EXAMPLE_NAME,module.SELECTION_NAME,module.FORCED_NAME,module.LINEAGE_NAME,module.SUMMARY_NAME)
ALLOWED = {module.PASS_STATUS,module.PARTIAL_STATUS,module.FAIL_A0,module.FAIL_HARDCODED,module.FAIL_PRICE,module.FAIL_TQQQ,module.FAIL_MUTATION}
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def test_repository_wrapper():
    r2 = module.load_module(ROOT,"r2_test","v21_060_r2_multi_seed_random_asof_abcd_robustness_backtest.py")
    protected=r2.protected_files(ROOT); before={p.relative_to(ROOT).as_posix():sha(p) for p in protected}
    run=subprocess.run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-File",str(WRAPPER)],cwd=ROOT,text=True,capture_output=True)
    out=ROOT/module.OUT_REL; summary=json.loads((out/module.SUMMARY_NAME).read_text())
    assert summary["FINAL_STATUS"] in ALLOWED
    assert run.returncode==(1 if summary["FINAL_STATUS"].startswith("FAIL_") else 0),run.stdout+run.stderr
    assert all((out/x).is_file() for x in REQUIRED)
    strategies=set()
    with (out/module.RESULTS_NAME).open("r",encoding="utf-8") as h:
        for row in csv.DictReader(h):
            strategies.add(row["strategy_id"]); assert row["research_only"]=="TRUE"; assert row["price_data_status"]=="PASS"
    assert set(module.STRATEGIES)<=strategies
    with (out/module.PORTFOLIO_NAME).open("r",encoding="utf-8") as h:
        first=next(csv.DictReader(h)); assert float(first["initial_capital_usd"])==10000; assert first["research_only"]=="TRUE"
    assert (out/module.PAIR_NAME).stat().st_size>0 and (out/module.SELECTION_NAME).stat().st_size>0
    forced=list(csv.DictReader((out/module.FORCED_NAME).open("r",encoding="utf-8")))
    assert set(module.FORCED)=={x["ticker"] for x in forced}
    for ticker in ("DRAM","SPCX"):
        row=next(x for x in forced if x["ticker"]==ticker)
        if row["local_price_missing_flag"]=="TRUE": assert row["included_in_any_seed"]=="FALSE"
    assert next(x for x in forced if x["ticker"]=="TQQQ")["tqqq_ipo_watch_violation_flag"]=="FALSE"
    assert summary["a0_replayed"] is False and summary["a0_modified"] is False
    assert summary["hardcoded_inclusion_violation_count"]==summary["local_price_missing_included_violation_count"]==summary["tqqq_ipo_watch_violation_count"]==0
    assert summary["production_adoption_allowed"] is False and summary["official_use_allowed"] is False
    assert before=={p:sha(ROOT/p) for p in before}
    assert {p.parent.resolve() for p in out.glob("V21_060_R3*") if p.is_file()}=={out.resolve()}
    assert not list(out.glob("*OFFICIAL_RECOMMENDATION*")) and not list(out.glob("*BROKER_ACTION*"))
if __name__=="__main__":
    test_repository_wrapper(); print("PASS test_v21_060_r3_random_asof_benchmark_etf_rotation_10k_sim")
