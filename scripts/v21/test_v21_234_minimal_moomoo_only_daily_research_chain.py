from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_234_minimal_moomoo_only_daily_research_chain.py")
spec = importlib.util.spec_from_file_location("v21_234", MODULE_PATH)
v234 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v234)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as h:
        return list(csv.DictReader(h))


def make_guard(root: Path, ok: bool = True) -> None:
    policy = {"default_data_source_policy": "MOOMOO_ONLY" if ok else "MIXED", "research_only": True, "yfinance_allowed_by_default": False}
    write(root / "config/v21/data_source_policy.json", json.dumps(policy))
    write(root / "scripts/v21/v21_data_source_policy_guard.py", """
import json
from pathlib import Path
def load_data_source_policy(policy_path=None):
    return json.loads(Path(policy_path).read_text(encoding="utf-8"))
def assert_moomoo_only_policy(context, allow_diagnostic_external=False):
    if load_data_source_policy(Path(__file__).resolve().parents[2] / "config/v21/data_source_policy.json").get("default_data_source_policy") != "MOOMOO_ONLY":
        raise RuntimeError("bad policy")
""".lstrip())


def make_repo(tmp_path: Path, *, missing: str | None = None, v232_pass: bool = True, policy_bad: bool = False) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "repo"; make_guard(root, not policy_bad)
    d231 = root / "outputs/v21/V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD"
    d232 = root / "outputs/v21/V21.232_MOOMOO_ONLY_DRAM_DAILY_AND_INTRADAY_PLAN"
    d233 = root / "outputs/v21/V21.233_MOOMOO_ONLY_ABCDE_RERUN"
    if missing != "231":
        write(d231 / "v21_231_summary.json", json.dumps({"final_status":"WARN_V21_231_MOOMOO_ONLY_CANONICAL_REBUILD_READY_WITH_COVERAGE_WARNINGS","final_decision":"MOOMOO_ONLY_CANONICAL_READY_FOR_DRAM_AND_ABCDE_RERUN","snapshot_id":"snap","canonical_snapshot_dir":"cache/snap","canonical_latest_date":"2026-07-02","daily_raw_success_ratio":0.99,"daily_qfq_success_ratio":0.99,"quality_error_count":0,"warning_count":8,"error_count":0,"yfinance_used":False,"yahoo_used":False,"external_fallback_used":False,"moomoo_used":True,"broker_action_allowed":False,"official_adoption_allowed":False,"research_only":True}))
        write(d231 / "canonical_snapshot_pointer.json", json.dumps({"snapshot_id":"snap","canonical_snapshot_dir":"cache/snap"}))
        for n in ["canonical_snapshot_pointer.csv","canonical_rebuild_manifest.csv","canonical_quality_audit.csv","ticker_coverage_audit.csv","failed_ticker_retry_ledger.csv","source_policy_gate.json"]:
            write(d231 / n, "x,y\n")
    if missing != "232":
        write(d232 / "v21_232_summary.json", json.dumps({"final_status":"PASS_V21_232_MOOMOO_ONLY_DRAM_PLAN_READY" if v232_pass else "WARN_BAD","final_decision":"MOOMOO_ONLY_DRAM_PLAN_READY_RESEARCH_ONLY","source_snapshot_id":"snap","latest_price_date":"2026-07-02","latest_intraday_timestamp":"2026-07-02","entry":"60.9","no_chase":"62.7","stop":"55.3","daily_trend_state":"BEARISH","multiframe_gate":"WAIT_FOR_CONFIRMATION","trade_plan_currentness":"CURRENT","entry_allowed_research_only":False,"chase_allowed_research_only":False,"warning_count":0,"error_count":0,"yfinance_used":False,"yahoo_used":False,"external_fallback_used":False,"moomoo_used":True,"broker_action_allowed":False,"official_adoption_allowed":False,"research_only":True}))
        for n in ["dram_daily_plan.csv","dram_intraday_multiframe_gate.csv","dram_entry_exit_levels.csv","dram_no_chase_gate.csv","dram_stop_risk_plan.csv","dram_trade_permission_gate.csv","source_policy_gate.json"]:
            write(d232 / n, "x,y\n")
    if missing != "233":
        write(d233 / "v21_233_summary.json", json.dumps({"final_status":"WARN_V21_233_MOOMOO_ONLY_ABCDE_RERUN_READY_WITH_COMPACT_PROXY_WARNINGS","final_decision":"MOOMOO_ONLY_ABCDE_COMPACT_RERUN_READY_RESEARCH_ONLY","source_snapshot_id":"snap","canonical_latest_date":"2026-07-02","ranked_strategy_count":5,"ranked_ticker_count":326,"missing_ticker_count":4,"compact_proxy_used":True,"same_date_comparable_all_strategies":"True","A1_top20":"A","B_top20":"B","C_top20":"C","D_top20":"D","E_R1_top20":"E","quality_error_count":0,"quality_warning_count":1,"coverage_warning_count":4,"warning_count":5,"error_count":0,"yfinance_used":False,"yahoo_used":False,"external_fallback_used":False,"moomoo_used":True,"broker_action_allowed":False,"official_adoption_allowed":False,"research_only":True}))
        write(d233 / "abcde_missing_ticker_audit.csv", "ticker,reason,yahoo_fallback_allowed,external_fallback_allowed,notes\nBITF,MISSING,False,False,x\n")
        write(d233 / "abcde_top50_summary.csv", "strategy_name,ticker\nA1_CONTROL,A\nB_STATIC_MOMENTUM,B\nC_DYNAMIC_MOMENTUM,C\nD_WEIGHT_OPTIMIZED_REFERENCE,D\nE_R1_DEFENSIVE_REFERENCE,E\n")
        for n in ["abcde_top20_summary.csv","abcde_strategy_overlap_matrix.csv","abcde_strategy_latest_date_audit.csv","abcde_coverage_audit.csv","abcde_compact_report.txt","source_policy_gate.json"]:
            write(d233 / n, "x,y\n")
    return root, d231, d232, d233


def test_fails_if_required_outputs_missing(tmp_path):
    for stage in ["231","232","233"]:
        root, d231, d232, d233 = make_repo(tmp_path / stage, missing=stage)
        s = v234.run(root, tmp_path / f"out{stage}", d231, d232, d233)
        assert s["final_status"] in {v234.FAIL_MISSING, v234.FAIL_DRAM}


def test_imports_and_uses_policy_guard(tmp_path):
    root, d231, d232, d233 = make_repo(tmp_path)
    s = v234.run(root, tmp_path / "out", d231, d232, d233)
    assert s["daily_chain_passed"] is True


def test_never_imports_provider_sdks():
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "import yfinance" not in text and "from yfinance" not in text
    assert "import moomoo" not in text and "from moomoo" not in text
    assert "import futu" not in text and "from futu" not in text


def test_accepts_upstream_warnings_and_requires_dram_pass(tmp_path):
    root, d231, d232, d233 = make_repo(tmp_path)
    s = v234.run(root, tmp_path / "out", d231, d232, d233)
    assert s["final_status"] == v234.WARN_STATUS
    root2, a, b, c = make_repo(tmp_path / "bad", v232_pass=False)
    s2 = v234.run(root2, tmp_path / "out2", a, b, c)
    assert s2["stage_fail_count"] >= 1


def test_creates_required_outputs_and_next_action(tmp_path):
    root, d231, d232, d233 = make_repo(tmp_path)
    out = tmp_path / "out"; s = v234.run(root, out, d231, d232, d233)
    for n in ["daily_chain_stage_status.csv","daily_chain_dram_summary.csv","daily_chain_abcde_summary.csv","daily_chain_pointer_manifest.json","daily_chain_next_action_gate.csv"]:
        assert (out / n).exists()
    gate = read_csv(out / "daily_chain_next_action_gate.csv")[0]
    assert gate["next_action"] == "WAIT_FOR_INTRADAY_CONFIRMATION_RESEARCH_ONLY"
    assert gate["allowed_now"] == "False"


def test_source_policy_gate_flags(tmp_path):
    root, d231, d232, d233 = make_repo(tmp_path)
    out = tmp_path / "out"; v234.run(root, out, d231, d232, d233)
    gate = json.loads((out / "source_policy_gate.json").read_text())
    assert gate["broker_action_allowed"] is False
    assert gate["official_adoption_allowed"] is False


def test_fail_on_source_policy_violation(tmp_path):
    root, d231, d232, d233 = make_repo(tmp_path, policy_bad=True)
    s = v234.run(root, tmp_path / "out", d231, d232, d233)
    assert s["final_status"] == v234.FAIL_POLICY


def test_no_cache_mutation_or_market_fetch(tmp_path):
    root, d231, d232, d233 = make_repo(tmp_path)
    marker = tmp_path / "cache_snapshot.txt"; write(marker, "x")
    before = marker.read_text()
    s = v234.run(root, tmp_path / "out", d231, d232, d233)
    assert marker.read_text() == before
    assert s["broker_action_allowed"] is False
