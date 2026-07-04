from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_233_moomoo_only_abcde_rerun.py")
spec = importlib.util.spec_from_file_location("v21_233", MODULE_PATH)
v233 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v233)


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


def canonical(tickers: list[str], n: int = 80) -> str:
    lines = ["ticker,moomoo_symbol,market,date,open,high,low,close,volume,turnover,adjustment,source,source_policy,snapshot_id,fetched_at_utc"]
    for ti, t in enumerate(tickers):
        for i in range(n):
            c = 10 + ti + i * (0.05 + ti * 0.005)
            lines.append(f"{t},US.{t},US,2026-06-{(i%28)+1:02d},{c:.2f},{c+0.5:.2f},{c-0.5:.2f},{c+0.2:.2f},{1000+ti*100},10000,qfq,MOOMOO_OPEND,MOOMOO_ONLY,snap,t")
    return "\n".join(lines) + "\n"


def make_repo(tmp_path: Path, source_policy: str = "MOOMOO_ONLY", with_qfq: bool = True) -> tuple[Path, Path, Path]:
    root = tmp_path / "repo"; cache = tmp_path / "cache"; out231 = root / "outputs/v21/V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD"
    make_guard(root)
    snapdir = cache / "canonical/moomoo_ohlcv/snapshot_id=snap"
    qfq = snapdir / "canonical_moomoo_ohlcv_daily_qfq.csv"
    if with_qfq:
        write(qfq, canonical(["DRAM","NVDA","MU","AAPL","AMD"]))
    pointer = {"snapshot_id":"snap","cache_root":str(cache),"canonical_snapshot_dir":str(snapdir),"canonical_qfq_path":str(qfq),"source_policy":source_policy,"source":"MOOMOO_OPEND","yfinance_used":False,"yahoo_used":False,"external_fallback_used":False}
    write(out231 / "canonical_snapshot_pointer.json", json.dumps(pointer))
    write(out231 / "canonical_snapshot_pointer.csv", "key,value\nsnapshot_id,snap\n")
    write(out231 / "v21_231_summary.json", json.dumps({"canonical_latest_date":"2026-06-28"}))
    write(out231 / "canonical_rebuild_manifest.csv", "canonical_artifact,path,source_policy\nqfq,x,MOOMOO_ONLY\n")
    write(out231 / "canonical_quality_audit.csv", "check_name,passed\nx,True\n")
    write(out231 / "ticker_coverage_audit.csv", "ticker,moomoo_symbol,coverage_status\nDRAM,US.DRAM,OK\nNVDA,US.NVDA,OK\nBITF,US.BITF,MISSING_OR_FAILED\n")
    write(out231 / "failed_ticker_retry_ledger.csv", "ticker,moomoo_symbol\nBITF,US.BITF\n")
    write(out231 / "source_policy_gate.json", json.dumps({"yfinance_allowed":False}))
    return root, cache, out231


def test_fails_if_v21_231_inputs_missing(tmp_path):
    root = tmp_path / "repo"; make_guard(root)
    s = v233.run(root, tmp_path / "out")
    assert s["final_status"] == v233.FAIL_MISSING


def test_imports_and_uses_policy_guard(tmp_path):
    root, cache, out231 = make_repo(tmp_path)
    s = v233.run(root, tmp_path / "out", out231, cache_root=cache)
    assert s["ranked_strategy_count"] == 5


def test_never_imports_yfinance_or_moomoo_futu():
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "import yfinance" not in text and "from yfinance" not in text
    assert "import moomoo" not in text and "from moomoo" not in text
    assert "import futu" not in text and "from futu" not in text


def test_reads_pointer_snapshot_id(tmp_path):
    root, cache, out231 = make_repo(tmp_path)
    s = v233.run(root, tmp_path / "out", out231, cache_root=cache)
    assert s["source_snapshot_id"] == "snap"


def test_fails_if_source_policy_not_moomoo(tmp_path):
    root, cache, out231 = make_repo(tmp_path, source_policy="MIXED")
    s = v233.run(root, tmp_path / "out", out231, cache_root=cache)
    assert s["final_status"] == v233.FAIL_POLICY


def test_loads_mock_canonical_and_produces_all_strategies(tmp_path):
    root, cache, out231 = make_repo(tmp_path)
    out = tmp_path / "out"; v233.run(root, out, out231, cache_root=cache)
    strategies = {r["strategy_name"] for r in read_csv(out / "abcde_strategy_ranking_master.csv")}
    assert strategies == set(v233.STRATEGIES)


def test_creates_required_outputs(tmp_path):
    root, cache, out231 = make_repo(tmp_path)
    out = tmp_path / "out"; v233.run(root, out, out231, cache_root=cache)
    for name in ["abcde_strategy_ranking_master.csv","abcde_top20_summary.csv","abcde_top50_summary.csv","abcde_strategy_overlap_matrix.csv","abcde_coverage_audit.csv"]:
        assert (out / name).exists()


def test_missing_tickers_forbid_fallback(tmp_path):
    root, cache, out231 = make_repo(tmp_path)
    out = tmp_path / "out"; v233.run(root, out, out231, cache_root=cache)
    rows = read_csv(out / "abcde_missing_ticker_audit.csv")
    assert any(r["ticker"] == "BITF" for r in rows)
    assert all(r["yahoo_fallback_allowed"] == "False" and r["external_fallback_allowed"] == "False" for r in rows)


def test_marks_compact_proxy_used(tmp_path):
    root, cache, out231 = make_repo(tmp_path)
    out = tmp_path / "out"; s = v233.run(root, out, out231, cache_root=cache)
    assert s["compact_proxy_used"] is True
    assert all(r["compact_proxy_used"] == "True" for r in read_csv(out / "abcde_strategy_ranking_master.csv"))


def test_source_policy_gate_flags(tmp_path):
    root, cache, out231 = make_repo(tmp_path)
    out = tmp_path / "out"; v233.run(root, out, out231, cache_root=cache)
    gate = json.loads((out / "source_policy_gate.json").read_text())
    assert gate["broker_action_allowed"] is False
    assert gate["official_adoption_allowed"] is False
    assert gate["active_trading_focus"] == "DRAM"


def test_warn_when_proxy_warnings_but_rankings_exist(tmp_path):
    root, cache, out231 = make_repo(tmp_path)
    s = v233.run(root, tmp_path / "out", out231, cache_root=cache)
    assert s["final_status"] == v233.WARN_STATUS


def test_fail_when_qfq_missing(tmp_path):
    root, cache, out231 = make_repo(tmp_path, with_qfq=False)
    s = v233.run(root, tmp_path / "out", out231, cache_root=cache)
    assert s["final_status"] == v233.FAIL_MISSING


def test_does_not_mutate_cache_snapshot(tmp_path):
    root, cache, out231 = make_repo(tmp_path)
    qfq = cache / "canonical/moomoo_ohlcv/snapshot_id=snap/canonical_moomoo_ohlcv_daily_qfq.csv"
    before = v233.sha256(qfq)
    v233.run(root, tmp_path / "out", out231, cache_root=cache)
    assert v233.sha256(qfq) == before


def test_no_large_canonical_data_in_repo_outputs(tmp_path):
    root, cache, out231 = make_repo(tmp_path)
    out = tmp_path / "out"; v233.run(root, out, out231, cache_root=cache)
    assert all(p.stat().st_size < 250_000 for p in out.rglob("*") if p.is_file())
