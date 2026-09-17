from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path
import pytest


MODULE_PATH = Path(__file__).with_name("v21_231_moomoo_only_historical_refetch_and_canonical_rebuild.py")
spec = importlib.util.spec_from_file_location("v21_231", MODULE_PATH)
v231 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v231)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def make_guard(root: Path, ok: bool = True) -> None:
    policy = {
        "default_data_source_policy": "MOOMOO_ONLY" if ok else "MIXED",
        "research_only": True,
        "yfinance_allowed_by_default": False,
        "yahoo_allowed_by_default": False,
        "external_fallback_allowed_for_canonical": False,
        "external_fallback_allowed_for_dram": False,
        "external_fallback_allowed_for_abcde": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
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
        raise RuntimeError("bad")
def assert_moomoo_only_policy(context, allow_diagnostic_external=False):
    if load_data_source_policy().get("default_data_source_policy") != "MOOMOO_ONLY":
        raise RuntimeError("not moomoo only")
    assert_yfinance_disabled(context)
def policy_flags_for_summary():
    return load_data_source_policy()
""".lstrip(),
    )


def make_inputs(root: Path, ready: bool = True, include_dram_intraday: bool = True) -> tuple[Path, Path]:
    v230 = root / "outputs/v21/V21.230_MOOMOO_ONLY_HISTORICAL_REFETCH_DRY_RUN"
    v230r1 = root / "outputs/v21/V21.230_R1_MOOMOO_OPEND_READINESS_AND_PERMISSION_PROBE"
    write(v230 / "v21_230_summary.json", json.dumps({"ticker_universe_count": 3, "planned_total_fetch_items": 8}))
    write(v230 / "dry_run_policy_gate.json", json.dumps({"dry_run_only": True, "actual_historical_fetch_allowed_now": False}))
    plan_rows = [
        "ticker,market,moomoo_symbol,asset_type,active_scope,frequency,adjustment,planned_start_date,planned_end_date",
        "DRAM,US,US.DRAM,EQUITY,DRAM ABCDE,1d,raw,2026-07-01,2026-07-03",
        "DRAM,US,US.DRAM,EQUITY,DRAM ABCDE,1d,qfq,2026-07-01,2026-07-03",
        "NVDA,US,US.NVDA,EQUITY,ABCDE,1d,raw,2026-07-01,2026-07-03",
        "NVDA,US,US.NVDA,EQUITY,ABCDE,1d,qfq,2026-07-01,2026-07-03",
        "MU,US,US.MU,EQUITY,ABCDE,1d,raw,2026-07-01,2026-07-03",
        "MU,US,US.MU,EQUITY,ABCDE,1d,qfq,2026-07-01,2026-07-03",
    ]
    if include_dram_intraday:
        plan_rows += [
            "DRAM,US,US.DRAM,EQUITY,DRAM,1m,raw,2026-07-01,2026-07-03",
            "DRAM,US,US.DRAM,EQUITY,DRAM,5m,raw,2026-07-01,2026-07-03",
        ]
    write(v230 / "moomoo_refetch_dry_run_plan.csv", "\n".join(plan_rows) + "\n")
    write(v230 / "ticker_universe_resolution.csv", "ticker,resolved_symbol,market\nDRAM,US.DRAM,US\nNVDA,US.NVDA,US\nMU,US.MU,US\n")
    for name in ["moomoo_frequency_plan.csv","moomoo_adjustment_plan.csv","moomoo_cache_target_plan.csv","moomoo_canonical_target_plan.csv","dram_intraday_refetch_plan.csv","abcde_daily_refetch_plan.csv","failed_or_missing_ticker_plan.csv","v21_231_execution_prerequisites.csv"]:
        write(v230 / name, "name,value\nx,y\n")
    write(v230r1 / "v21_230_r1_summary.json", json.dumps({"final_status": "PASS_V21_230_R1_MOOMOO_OPEND_READY_FOR_V21_231" if ready else "WARN", "v21_231_ready": ready}))
    write(v230r1 / "opend_probe_policy_gate.json", json.dumps({"probe_only": True}))
    for name in ["opend_connection_probe.csv","moomoo_import_probe.csv","moomoo_api_capability_probe.csv","ticker_symbol_probe.csv","permission_probe.csv","v21_231_go_no_go_gate.csv"]:
        write(v230r1 / name, "name,value\nx,y\n")
    return v230, v230r1


def make_repo(tmp_path: Path, ready: bool = True, guard_ok: bool = True) -> Path:
    root = tmp_path / "repo"
    make_guard(root, guard_ok)
    make_inputs(root, ready)
    return root


def run_ok(root: Path, out: Path, cache: Path, **kwargs):
    return v231.run(root, out, cache_root=cache, snapshot_id=kwargs.pop("snapshot_id", "moomoo_only_test"), no_network=True, sleep_seconds=0, **kwargs)


@pytest.fixture(autouse=True)
def isolated_active_universe(monkeypatch):
    """Unit tests exercise their explicit three-ticker fixture.

    Full-universe behaviour is covered by the dedicated coverage-guard suite;
    these tests must not silently read the workstation's durable manifest.
    """
    monkeypatch.setattr(v231, "active_abcde_universe", lambda: {"DRAM", "NVDA", "MU"})


def test_fails_if_v21_230_inputs_missing(tmp_path):
    root = tmp_path / "repo"; make_guard(root)
    summary = v231.run(root, tmp_path / "out", cache_root=tmp_path / "cache", no_network=True)
    assert summary["final_status"] == v231.FAIL_INPUT


def test_fails_if_v21_230_r1_readiness_missing_or_not_ready(tmp_path):
    root = make_repo(tmp_path, ready=False)
    summary = v231.run(root, tmp_path / "out", cache_root=tmp_path / "cache", no_network=True)
    assert summary["final_status"] == v231.FAIL_INPUT


def test_imports_and_uses_policy_guard(tmp_path):
    root = make_repo(tmp_path)
    summary = run_ok(root, tmp_path / "out", tmp_path / "cache")
    assert summary["policy_guard_found"] is True
    assert summary["policy_guard_passed"] is True


def test_never_imports_yfinance():
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "import yfinance" not in text
    assert "from yfinance" not in text


def test_does_not_import_moomoo_or_futu_at_module_import_time():
    assert "moomoo" not in sys.modules
    assert "futu" not in sys.modules
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "import moomoo" not in text
    assert "from moomoo" not in text
    assert "import futu" not in text
    assert "from futu" not in text


def test_writes_source_policy_gate(tmp_path):
    root = make_repo(tmp_path); out = tmp_path / "out"
    run_ok(root, out, tmp_path / "cache")
    gate = json.loads((out / "source_policy_gate.json").read_text())
    assert gate["yfinance_allowed"] is False
    assert gate["broker_action_allowed"] is False


def test_creates_new_immutable_snapshot_path_under_cache_root(tmp_path):
    root = make_repo(tmp_path); cache = tmp_path / "cache"
    summary = run_ok(root, tmp_path / "out", cache)
    assert str(cache) in summary["canonical_snapshot_dir"]
    assert (cache / "canonical/moomoo_ohlcv/snapshot_id=moomoo_only_test").exists()


def test_refuses_overwrite_existing_snapshot_unless_resume(tmp_path):
    root = make_repo(tmp_path); cache = tmp_path / "cache"
    run_ok(root, tmp_path / "out1", cache)
    summary = run_ok(root, tmp_path / "out2", cache)
    assert summary["final_status"] == v231.FAIL_SNAPSHOT
    resumed = v231.run(root, tmp_path / "out3", cache_root=cache, resume_snapshot_id="moomoo_only_test", no_network=True, sleep_seconds=0)
    assert not resumed["final_status"].startswith("FAIL_")


def test_mocked_fetch_produces_daily_raw_and_qfq_cache_files(tmp_path):
    root = make_repo(tmp_path); cache = tmp_path / "cache"; out = tmp_path / "out"
    run_ok(root, out, cache)
    assert read_csv(out / "daily_raw_fetch_manifest.csv")
    assert read_csv(out / "daily_qfq_fetch_manifest.csv")


def test_mocked_dram_intraday_fetch(tmp_path):
    root = make_repo(tmp_path); out = tmp_path / "out"
    summary = run_ok(root, out, tmp_path / "cache")
    assert summary["dram_intraday_success_count"] >= 2


def test_builds_canonical_raw_and_qfq_outputs(tmp_path):
    root = make_repo(tmp_path); cache = tmp_path / "cache"
    summary = run_ok(root, tmp_path / "out", cache)
    assert summary["canonical_raw_row_count"] > 0
    assert summary["canonical_qfq_row_count"] > 0


def test_historical_target_date_truncates_canonical_and_blocks_future_sentinel(tmp_path, monkeypatch):
    root = make_repo(tmp_path); cache = tmp_path / "cache"; out = tmp_path / "out"
    original = v231.mock_fetch
    def future_bars(item, snapshot):
        rows = original(item, snapshot)
        if item["frequency"] == "1d":
            rows = [r for r in rows if r["date"] != "2026-08-12"]
            rows.extend([{**rows[-1], "date": "2026-08-12", "close": 10.5}, {**rows[-1], "date": "2026-08-13", "open": 999999, "high": 999999, "low": 999999, "close": 999999, "volume": 999999999}])
        return rows
    monkeypatch.setattr(v231, "mock_fetch", future_bars)
    summary = v231.run(root, out, cache_root=cache, snapshot_id="historical", no_network=True, sleep_seconds=0, end_date="2026-08-12")
    pointer = json.loads((out / "canonical_snapshot_pointer.json").read_text())
    raw, qfq = read_csv(Path(pointer["canonical_raw_path"])), read_csv(Path(pointer["canonical_qfq_path"]))
    assert max(r["date"] for r in raw) == "2026-08-12"
    assert max(r["date"] for r in qfq) == "2026-08-12"
    assert all(float(r["close"]) != 999999 for r in raw + qfq)
    assert summary["canonical_complete_universe_date"] == "2026-08-12"


def test_latest_date_canonical_behavior_is_unchanged(tmp_path):
    root = make_repo(tmp_path); summary = run_ok(root, tmp_path / "out", tmp_path / "cache")
    assert summary["canonical_complete_universe_date"] == "2026-07-03"


def test_writes_canonical_snapshot_pointer(tmp_path):
    root = make_repo(tmp_path); out = tmp_path / "out"
    run_ok(root, out, tmp_path / "cache")
    assert (out / "canonical_snapshot_pointer.json").exists()


def test_writes_fetch_execution_master(tmp_path):
    root = make_repo(tmp_path); out = tmp_path / "out"
    run_ok(root, out, tmp_path / "cache")
    assert read_csv(out / "fetch_execution_master.csv")


def test_failed_retry_ledger_forbids_fallbacks(tmp_path, monkeypatch):
    root = make_repo(tmp_path); out = tmp_path / "out"
    original = v231.mock_fetch
    monkeypatch.setattr(v231, "mock_fetch", lambda item, snapshot: [] if item["ticker"] == "MU" else original(item, snapshot))
    v231.run(root, out, cache_root=tmp_path / "cache", snapshot_id="moomoo_only_test", no_network=True, sleep_seconds=0, min_daily_success_ratio=0.5)
    rows = read_csv(out / "failed_ticker_retry_ledger.csv")
    assert rows and all(r["yahoo_fallback_allowed"] == "False" and r["external_fallback_allowed"] == "False" for r in rows)


def test_quality_audit_catches_bad_rows(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    original = v231.mock_fetch
    def bad(item, snapshot):
        rows = original(item, snapshot)
        rows[0]["high"] = 1
        return rows
    monkeypatch.setattr(v231, "mock_fetch", bad)
    summary = v231.run(root, tmp_path / "out", cache_root=tmp_path / "cache", snapshot_id="moomoo_only_test", no_network=True, sleep_seconds=0)
    assert summary["final_status"] == v231.FAIL_QUALITY


def test_partial_daily_universe_is_not_promotable_even_above_legacy_ratio(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    original = v231.mock_fetch
    monkeypatch.setattr(v231, "mock_fetch", lambda item, snapshot: [] if item["ticker"] == "MU" else original(item, snapshot))
    summary = v231.run(root, tmp_path / "out", cache_root=tmp_path / "cache", snapshot_id="moomoo_only_test", no_network=True, sleep_seconds=0, min_daily_success_ratio=0.5)
    assert summary["final_status"] == v231.FAIL_DAILY


def test_returns_fail_when_dram_intraday_fails_required(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    original = v231.mock_fetch
    monkeypatch.setattr(v231, "mock_fetch", lambda item, snapshot: [] if item["ticker"] == "DRAM" and item["frequency"] != "1d" else original(item, snapshot))
    summary = v231.run(root, tmp_path / "out", cache_root=tmp_path / "cache", snapshot_id="moomoo_only_test", no_network=True, sleep_seconds=0)
    assert summary["final_status"] == v231.FAIL_DRAM


def test_returns_fail_when_daily_coverage_below_threshold(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    original = v231.mock_fetch
    monkeypatch.setattr(v231, "mock_fetch", lambda item, snapshot: [] if item["frequency"] == "1d" else original(item, snapshot))
    summary = v231.run(root, tmp_path / "out", cache_root=tmp_path / "cache", snapshot_id="moomoo_only_test", no_network=True, sleep_seconds=0)
    assert summary["final_status"] == v231.FAIL_DAILY


def test_verifies_hashes_for_written_files(tmp_path):
    root = make_repo(tmp_path)
    summary = run_ok(root, tmp_path / "out", tmp_path / "cache")
    assert summary["hash_verified_file_count"] > 0


def test_does_not_write_large_fetched_data_into_repo_outputs(tmp_path):
    root = make_repo(tmp_path); out = tmp_path / "out"
    run_ok(root, out, tmp_path / "cache")
    assert not any(p.name.startswith("canonical_moomoo_ohlcv") for p in out.rglob("*"))


def test_no_trade_unlock_or_broker_actions(tmp_path):
    root = make_repo(tmp_path)
    summary = run_ok(root, tmp_path / "out", tmp_path / "cache")
    text = MODULE_PATH.read_text(encoding="utf-8").lower()
    assert "unlock_trade(" not in text
    assert "place_order(" not in text
    assert summary["broker_action_allowed"] is False
    assert summary["trade_unlock_used"] is False


def test_supports_max_fetch_items(tmp_path):
    root = make_repo(tmp_path)
    summary = run_ok(root, tmp_path / "out", tmp_path / "cache", max_fetch_items=2)
    # The limiter must never truncate the durable daily ABCDE universe; it
    # only applies to optional non-daily DRAM legs.
    assert summary["attempted_fetch_items"] >= 2


def test_supports_no_network(tmp_path):
    root = make_repo(tmp_path)
    summary = run_ok(root, tmp_path / "out", tmp_path / "cache")
    assert summary["data_fetch_used"] is True
    assert summary["yfinance_used"] is False


def test_policy_violation_fails(tmp_path):
    root = make_repo(tmp_path, guard_ok=False)
    summary = v231.run(root, tmp_path / "out", cache_root=tmp_path / "cache", no_network=True)
    assert summary["final_status"] == v231.FAIL_SOURCE


def _make_incremental_parent(cache: Path, snapshot: str = "parent") -> None:
    fields = "ticker,moomoo_symbol,market,date,open,high,low,close,volume,turnover,adjustment,source,source_policy,snapshot_id,fetched_at_utc\n"
    for adjustment, folder in (("raw", "daily_raw"), ("qfq", "daily_qfq")):
        for ticker in ("DRAM", "NVDA", "MU"):
            write(
                cache / f"raw/moomoo/{folder}/snapshot_id={snapshot}/{ticker}.csv",
                fields + f"{ticker},US.{ticker},US,2026-08-19,10,11,9,10.5,1000,10500,{adjustment},MOOMOO_OPEND,MOOMOO_ONLY,{snapshot},2026-08-20T00:00:00Z\n",
            )


def test_incremental_only_requests_exact_date_and_preserves_parent_history(tmp_path, monkeypatch):
    root = make_repo(tmp_path); cache = tmp_path / "cache"; out = tmp_path / "out"
    _make_incremental_parent(cache)
    requested = []
    monkeypatch.setattr(v231, "active_abcde_universe", lambda: {"DRAM", "NVDA", "MU"})

    def exact_fetch(item, snapshot):
        requested.append((item["ticker"], item["adjustment"], item["planned_start_date"], item["planned_end_date"]))
        return [{
            "ticker": item["ticker"], "moomoo_symbol": item["moomoo_symbol"], "market": "US", "date": "2026-08-20",
            "open": 12, "high": 13, "low": 11, "close": 12.5, "volume": 1200, "turnover": 15000,
            "adjustment": item["adjustment"], "source": "MOOMOO_OPEND", "source_policy": "MOOMOO_ONLY",
            "snapshot_id": snapshot, "fetched_at_utc": "2026-08-21T00:00:00Z",
        }]

    monkeypatch.setattr(v231, "mock_fetch", exact_fetch)
    summary = v231.run(root, out, cache_root=cache, snapshot_id="child", start_date="2026-08-20", end_date="2026-08-20",
                       no_network=True, sleep_seconds=0, incremental_only=True, parent_snapshot_id="parent")
    assert not summary["final_status"].startswith("FAIL_")
    assert summary["network_fetch_scope"] == "EXACT_DATE_ONLY"
    assert summary["historical_deep_refetch_run"] is False
    assert len(requested) == 6 and all(start == end == "2026-08-20" for _, _, start, end in requested)
    assert summary["dram_intraday_attempted_count"] == 0
    raw = read_csv(Path(json.loads((out / "canonical_snapshot_pointer.json").read_text())["canonical_raw_path"]))
    assert {(row["ticker"], row["date"]) for row in raw} == {(ticker, day) for ticker in ("DRAM", "NVDA", "MU") for day in ("2026-08-19", "2026-08-20")}


def test_incremental_only_fails_closed_on_incomplete_target_date(tmp_path, monkeypatch):
    root = make_repo(tmp_path); cache = tmp_path / "cache"; out = tmp_path / "out"
    _make_incremental_parent(cache)
    monkeypatch.setattr(v231, "active_abcde_universe", lambda: {"DRAM", "NVDA", "MU"})
    original = v231.mock_fetch
    monkeypatch.setattr(v231, "mock_fetch", lambda item, snapshot: [] if item["ticker"] == "MU" else [{**original(item, snapshot)[0], "date": "2026-08-20"}])
    summary = v231.run(root, out, cache_root=cache, snapshot_id="child", start_date="2026-08-20", end_date="2026-08-20",
                       no_network=True, sleep_seconds=0, incremental_only=True, parent_snapshot_id="parent")
    assert summary["final_status"] == v231.FAIL_DAILY
    assert summary["stale_ticker_count"] > 0


def test_incremental_only_requires_one_explicit_target_date(tmp_path):
    root = make_repo(tmp_path)
    summary = v231.run(root, tmp_path / "out", cache_root=tmp_path / "cache", snapshot_id="child", end_date="2026-08-20",
                       no_network=True, sleep_seconds=0, incremental_only=True, parent_snapshot_id="parent")
    assert summary["final_status"] == v231.FAIL_INPUT
    assert summary["historical_deep_refetch_run"] is False
