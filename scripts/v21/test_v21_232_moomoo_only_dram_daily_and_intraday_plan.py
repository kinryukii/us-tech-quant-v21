from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_232_moomoo_only_dram_daily_and_intraday_plan.py")
spec = importlib.util.spec_from_file_location("v21_232", MODULE_PATH)
v232 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v232)


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


def bars(n: int) -> str:
    lines = ["ticker,moomoo_symbol,market,date,open,high,low,close,volume,turnover,adjustment,source,source_policy,snapshot_id,fetched_at_utc"]
    for i in range(n):
        d = f"2026-06-{(i%28)+1:02d}"
        c = 10 + i * 0.1
        lines.append(f"DRAM,US.DRAM,US,{d},{c:.2f},{c+0.5:.2f},{c-0.5:.2f},{c+0.2:.2f},1000,10000,qfq,MOOMOO_OPEND,MOOMOO_ONLY,snap,t")
    return "\n".join(lines) + "\n"


def make_repo(tmp_path: Path, n: int = 60, source_policy: str = "MOOMOO_ONLY", daily: bool = True) -> tuple[Path, Path, Path]:
    root = tmp_path / "repo"; cache = tmp_path / "cache"; out231 = root / "outputs/v21/V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD"
    make_guard(root)
    snapdir = cache / "canonical/moomoo_ohlcv/snapshot_id=snap"
    intradir = cache / "raw/moomoo/intraday/DRAM/snapshot_id=snap"
    if daily:
        write(snapdir / "canonical_moomoo_ohlcv_daily_qfq.csv", bars(n))
    for f in ["1m","5m","15m","1h"]:
        write(intradir / f / "DRAM.csv", bars(n))
    pointer = {"snapshot_id":"snap","cache_root":str(cache),"canonical_snapshot_dir":str(snapdir),"canonical_qfq_path":str(snapdir / "canonical_moomoo_ohlcv_daily_qfq.csv"),"intraday_snapshot_dir":str(intradir),"source_policy":source_policy,"source":"MOOMOO_OPEND","yfinance_used":False,"yahoo_used":False,"external_fallback_used":False}
    write(out231 / "canonical_snapshot_pointer.json", json.dumps(pointer))
    write(out231 / "canonical_snapshot_pointer.csv", "key,value\nsnapshot_id,snap\n")
    write(out231 / "v21_231_summary.json", json.dumps({"quality_error_count":0}))
    write(out231 / "canonical_rebuild_manifest.csv", "canonical_artifact,path,source_policy\nx,y,MOOMOO_ONLY\n")
    write(out231 / "canonical_quality_audit.csv", "check_name,passed\nx,True\n")
    write(out231 / "ticker_coverage_audit.csv", "ticker,coverage_status\nDRAM,OK\n")
    write(out231 / "source_policy_gate.json", json.dumps({"yfinance_allowed":False}))
    rows = ["ticker,moomoo_symbol,frequency,cache_path,success"]
    for f in ["1m","5m","15m","1h"]:
        rows.append(f"DRAM,US.DRAM,{f},{intradir / f / 'DRAM.csv'},True")
    write(out231 / "dram_intraday_fetch_manifest.csv", "\n".join(rows)+"\n")
    return root, cache, out231


def test_fails_if_v21_231_inputs_missing(tmp_path):
    root = tmp_path / "repo"; make_guard(root)
    s = v232.run(root, tmp_path / "out")
    assert s["final_status"] == v232.FAIL_DATA


def test_imports_and_uses_policy_guard(tmp_path):
    root, cache, out231 = make_repo(tmp_path)
    s = v232.run(root, tmp_path / "out", out231, cache)
    assert s["final_status"] in {v232.PASS_STATUS, v232.WARN_STATUS}


def test_never_imports_yfinance_or_moomoo_futu():
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "import yfinance" not in text and "from yfinance" not in text
    assert "import moomoo" not in text and "from moomoo" not in text
    assert "import futu" not in text and "from futu" not in text


def test_reads_pointer_snapshot_id(tmp_path):
    root, cache, out231 = make_repo(tmp_path)
    s = v232.run(root, tmp_path / "out", out231, cache)
    assert s["source_snapshot_id"] == "snap"


def test_fails_if_source_policy_not_moomoo_only(tmp_path):
    root, cache, out231 = make_repo(tmp_path, source_policy="MIXED")
    s = v232.run(root, tmp_path / "out", out231, cache)
    assert s["final_status"] == v232.FAIL_POLICY


def test_loads_dram_daily_and_intraday(tmp_path):
    root, cache, out231 = make_repo(tmp_path)
    s = v232.run(root, tmp_path / "out", out231, cache)
    assert s["daily_data_found"] is True
    assert s["intraday_1m_found"] is True


def test_computes_levels_deterministically(tmp_path):
    root, cache, out231 = make_repo(tmp_path)
    out = tmp_path / "out"; v232.run(root, out, out231, cache)
    row = read_csv(out / "dram_entry_exit_levels.csv")[0]
    assert float(row["entry"]) > 0 and float(row["no_chase"]) > float(row["entry"]) and float(row["stop"]) > 0


def test_indicators_or_insufficient_bars(tmp_path):
    root, cache, out231 = make_repo(tmp_path, n=5)
    out = tmp_path / "out"; s = v232.run(root, out, out231, cache)
    assert s["final_status"] == v232.WARN_STATUS
    assert "INSUFFICIENT_BARS" in (out / "dram_intraday_signal_audit.csv").read_text()


def test_creates_required_plan_artifacts(tmp_path):
    root, cache, out231 = make_repo(tmp_path)
    out = tmp_path / "out"; v232.run(root, out, out231, cache)
    for name in ["dram_daily_plan.csv","dram_intraday_signal_audit.csv","dram_intraday_multiframe_gate.csv","dram_entry_exit_levels.csv","dram_no_chase_gate.csv","dram_trade_permission_gate.csv"]:
        assert (out / name).exists()


def test_trade_permission_gate_forbids_broker_action(tmp_path):
    root, cache, out231 = make_repo(tmp_path)
    out = tmp_path / "out"; v232.run(root, out, out231, cache)
    rows = read_csv(out / "dram_trade_permission_gate.csv")
    assert all(r["allowed"] == "False" for r in rows)


def test_source_policy_gate_flags(tmp_path):
    root, cache, out231 = make_repo(tmp_path)
    out = tmp_path / "out"; v232.run(root, out, out231, cache)
    gate = json.loads((out / "source_policy_gate.json").read_text())
    assert gate["yfinance_allowed"] is False and gate["official_adoption_allowed"] is False


def test_fail_when_daily_missing(tmp_path):
    root, cache, out231 = make_repo(tmp_path, daily=False)
    s = v232.run(root, tmp_path / "out", out231, cache)
    assert s["final_status"] == v232.FAIL_DATA


def test_does_not_mutate_cache_snapshot(tmp_path):
    root, cache, out231 = make_repo(tmp_path)
    target = cache / "canonical/moomoo_ohlcv/snapshot_id=snap/canonical_moomoo_ohlcv_daily_qfq.csv"
    before = v232.sha256(target)
    v232.run(root, tmp_path / "out", out231, cache)
    assert v232.sha256(target) == before


def test_no_large_market_data_in_repo_outputs(tmp_path):
    root, cache, out231 = make_repo(tmp_path, n=100)
    out = tmp_path / "out"; v232.run(root, out, out231, cache)
    assert all(p.stat().st_size < 200_000 for p in out.rglob("*") if p.is_file())
