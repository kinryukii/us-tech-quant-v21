from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_230_moomoo_only_historical_refetch_dry_run.py")
spec = importlib.util.spec_from_file_location("v21_230", MODULE_PATH)
v230 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v230)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def make_guard(root: Path, *, yfinance_allowed: bool = False) -> None:
    policy = {
        "default_data_source_policy": "MOOMOO_ONLY",
        "yfinance_allowed_by_default": yfinance_allowed,
        "yahoo_allowed_by_default": False,
        "yfinance_allowed_for_canonical": False,
        "yfinance_allowed_for_dram": False,
        "yfinance_allowed_for_abcde": False,
        "external_fallback_allowed_for_canonical": False,
        "external_fallback_allowed_for_dram": False,
        "external_fallback_allowed_for_abcde": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
    }
    write(root / "config/v21/data_source_policy.json", json.dumps(policy))
    write(
        root / "scripts/v21/v21_data_source_policy_guard.py",
        """
import json
from pathlib import Path

def load_data_source_policy(policy_path=None):
    path = Path(policy_path) if policy_path else Path(__file__).resolve().parents[2] / "config/v21/data_source_policy.json"
    return json.loads(path.read_text(encoding="utf-8"))

def assert_yfinance_disabled(context):
    if load_data_source_policy().get("yfinance_allowed_by_default") is not False:
        raise RuntimeError("forbidden provider enabled")

def assert_moomoo_only_policy(context, allow_diagnostic_external=False):
    policy = load_data_source_policy()
    if policy.get("default_data_source_policy") != "MOOMOO_ONLY":
        raise RuntimeError("not moomoo only")
    assert_yfinance_disabled(context)

def policy_flags_for_summary():
    return load_data_source_policy()
""".lstrip(),
    )


def make_v229(root: Path, *, ready: bool = True) -> Path:
    out = root / "outputs/v21/V21.229_R1_ACTIVE_DATA_SOURCE_BLOCKER_TRIAGE_AND_ENFORCEMENT"
    write(
        out / "v21_229_r1_summary.json",
        json.dumps({
            "v21_230_ready": ready,
            "still_blocks_v21_230_count": 0 if ready else 1,
            "final_decision": "MOOMOO_ONLY_ACTIVE_CHAIN_ENFORCEMENT_READY_FOR_V21_230_DRY_RUN",
            "yfinance_used": False,
            "yahoo_used": False,
        }),
    )
    return out


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    make_guard(root)
    make_v229(root)
    write(
        root / "outputs/v21/V21.233_SAMPLE_ABCDE/abcde_latest_ranking.csv",
        "strategy,rank,ticker\nA1,1,NVDA\nA1,2,MU\nA1,3,DRAM\n",
    )
    write(
        root / "outputs/v21/V21.232_SAMPLE_DRAM/dram_chain_universe.csv",
        "ticker,rank\nDRAM,1\nMU,2\n",
    )
    return root


def test_fails_if_v21_229_r1_output_missing(tmp_path):
    root = tmp_path / "repo"
    make_guard(root)
    summary = v230.run(root, tmp_path / "out", cache_root=tmp_path / "cache")
    assert summary["final_status"] == v230.FAIL_POLICY_STATUS


def test_fails_if_policy_guard_missing(tmp_path):
    root = tmp_path / "repo"
    make_v229(root)
    summary = v230.run(root, tmp_path / "out", cache_root=tmp_path / "cache")
    assert summary["final_status"] == v230.FAIL_POLICY_STATUS
    assert summary["policy_guard_found"] is False


def test_imports_and_uses_policy_guard(tmp_path):
    root = make_repo(tmp_path)
    summary = v230.run(root, tmp_path / "out", cache_root=tmp_path / "cache")
    assert summary["policy_guard_found"] is True
    assert summary["policy_guard_passed"] is True


def test_never_imports_yfinance():
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "import yfinance" not in text
    assert "from yfinance" not in text


def test_never_imports_moomoo_or_futu_by_default():
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "import moomoo" not in text
    assert "from moomoo" not in text
    assert "import futu" not in text
    assert "from futu" not in text


def test_creates_dry_run_policy_gate_with_fetch_disabled(tmp_path):
    root = make_repo(tmp_path)
    out = tmp_path / "out"
    v230.run(root, out, cache_root=tmp_path / "cache")
    gate = json.loads((out / "dry_run_policy_gate.json").read_text(encoding="utf-8"))
    assert gate["actual_historical_fetch_allowed_now"] is False
    assert gate["canonical_rebuild_allowed_now"] is False


def test_resolves_ticker_universe_from_sample_abcde_and_dram_artifacts(tmp_path):
    root = make_repo(tmp_path)
    out = tmp_path / "out"
    summary = v230.run(root, out, cache_root=tmp_path / "cache")
    rows = read_csv(out / "ticker_universe_resolution.csv")
    tickers = {r["ticker"] for r in rows}
    assert {"NVDA", "MU", "DRAM"}.issubset(tickers)
    assert summary["ticker_universe_count"] >= 3


def test_includes_dram_in_ticker_universe(tmp_path):
    root = make_repo(tmp_path)
    out = tmp_path / "out"
    v230.run(root, out, cache_root=tmp_path / "cache")
    dram = next(r for r in read_csv(out / "ticker_universe_resolution.csv") if r["ticker"] == "DRAM")
    assert dram["included_in_dram"] == "True"


def test_creates_daily_raw_and_qfq_plans(tmp_path):
    root = make_repo(tmp_path)
    out = tmp_path / "out"
    summary = v230.run(root, out, cache_root=tmp_path / "cache")
    rows = read_csv(out / "moomoo_refetch_dry_run_plan.csv")
    assert any(r["frequency"] == "1d" and r["adjustment"] == "raw" for r in rows)
    assert any(r["frequency"] == "1d" and r["adjustment"] == "qfq" for r in rows)
    assert summary["planned_daily_raw_item_count"] > 0
    assert summary["planned_daily_qfq_item_count"] > 0


def test_creates_dram_intraday_plans_for_required_frequencies(tmp_path):
    root = make_repo(tmp_path)
    out = tmp_path / "out"
    v230.run(root, out, cache_root=tmp_path / "cache")
    rows = [r for r in read_csv(out / "dram_intraday_refetch_plan.csv") if r["ticker"] == "DRAM"]
    assert {r["frequency"] for r in rows} == {"1m", "5m", "15m", "1h"}


def test_creates_cache_and_canonical_target_plans_under_cache_root(tmp_path):
    root = make_repo(tmp_path)
    cache = tmp_path / "external_cache"
    out = tmp_path / "out"
    v230.run(root, out, cache_root=cache)
    cache_rows = read_csv(out / "moomoo_cache_target_plan.csv")
    canonical_rows = read_csv(out / "moomoo_canonical_target_plan.csv")
    assert all(str(cache) in r["proposed_path"] for r in cache_rows)
    assert all(str(cache) in r["proposed_path"] for r in canonical_rows)


def test_missing_ticker_plan_forbids_yahoo_and_external_fallbacks(tmp_path):
    root = make_repo(tmp_path)
    out = tmp_path / "out"
    v230.run(root, out, cache_root=tmp_path / "cache")
    rows = read_csv(out / "failed_or_missing_ticker_plan.csv")
    assert rows == [] or all(r["yahoo_fallback_allowed"] == "False" and r["external_fallback_allowed"] == "False" for r in rows)


def test_creates_v21_231_execution_prerequisites(tmp_path):
    root = make_repo(tmp_path)
    out = tmp_path / "out"
    v230.run(root, out, cache_root=tmp_path / "cache")
    assert (out / "v21_231_execution_prerequisites.csv").exists()


def test_creates_no_yfinance_enforcement_audit(tmp_path):
    root = make_repo(tmp_path)
    out = tmp_path / "out"
    v230.run(root, out, cache_root=tmp_path / "cache")
    rows = read_csv(out / "no_yfinance_enforcement_audit.csv")
    assert rows and rows[0]["pass"] == "True"


def test_does_not_create_external_cache_directories(tmp_path):
    root = make_repo(tmp_path)
    cache = tmp_path / "cache_not_created"
    v230.run(root, tmp_path / "out", cache_root=cache)
    assert not cache.exists()


def test_does_not_fetch_historical_bars(tmp_path):
    root = make_repo(tmp_path)
    summary = v230.run(root, tmp_path / "out", cache_root=tmp_path / "cache")
    assert summary["data_fetch_used"] is False
    assert summary["moomoo_historical_fetch_used"] is False


def test_returns_pass_or_warn_when_dry_run_plan_created_successfully(tmp_path):
    root = make_repo(tmp_path)
    summary = v230.run(root, tmp_path / "out", cache_root=tmp_path / "cache")
    assert summary["final_status"] in {v230.PASS_STATUS, v230.WARN_STATUS}


def test_returns_fail_if_policy_guard_says_yfinance_is_allowed(tmp_path):
    root = tmp_path / "repo"
    make_guard(root, yfinance_allowed=True)
    make_v229(root)
    summary = v230.run(root, tmp_path / "out", cache_root=tmp_path / "cache")
    assert summary["final_status"] == v230.FAIL_POLICY_STATUS


def test_respects_allow_opend_probe_default_false(tmp_path):
    root = make_repo(tmp_path)
    summary = v230.run(root, tmp_path / "out", cache_root=tmp_path / "cache")
    assert summary["opend_probe_used"] is False
    rows = read_csv(tmp_path / "out" / "moomoo_connection_readiness.csv")
    assert next(r for r in rows if r["check_name"] == "opend_probe_default")["actual"] == "False"
