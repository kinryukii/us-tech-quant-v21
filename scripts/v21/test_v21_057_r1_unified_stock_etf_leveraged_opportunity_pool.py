#!/usr/bin/env python
"""Contract tests for V21.057-R1 unified opportunity pool."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_057_r1_unified_stock_etf_leveraged_opportunity_pool.py"
WRAPPER = ROOT / "scripts/v21/run_v21_057_r1_unified_stock_etf_leveraged_opportunity_pool.ps1"
spec = importlib.util.spec_from_file_location("v21_057_r1", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)
ALLOWED = {module.PASS_STATUS, module.PARTIAL_STATUS, module.BLOCKED_AUDIT, module.BLOCKED_POOL, module.FAIL_STATUS}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def fixture(root: Path) -> list[Path]:
    seed_src = ROOT / module.SEED_REL
    seed_dst = root / module.SEED_REL
    seed_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(seed_src, seed_dst)
    write_csv(root / module.STOCK_REL, [
        {"rank": "1", "ticker": "MU", "composite_candidate_score": "9", "latest_price_date": "2026-06-18", "latest_close": "100"},
        {"rank": "2", "ticker": "QQQ", "composite_candidate_score": "8", "latest_price_date": "2026-06-18", "latest_close": "500"},
        {"rank": "3", "ticker": "SNDK", "composite_candidate_score": "7", "latest_price_date": "2026-06-18", "latest_close": "50"},
    ])
    a0 = root / module.A0_REL
    snap = root / module.R1_SNAPSHOT_REL
    write_csv(a0, [{"observation_id": "O1", "ticker": "MU"}])
    write_csv(snap, [{"observation_id": "O1", "ticker": "MU"}])
    write_csv(root / "outputs/v21/factors/V21_037_R1_HISTORICAL_OHLCV_TICKER_DEPTH_AFTER_INGESTION.csv", [
        {"ticker": ticker, "row_count": "10", "max_date": "2026-06-18", "volume_ma20_ready": "TRUE"}
        for ticker in ("SPY", "VOO", "IVV", "QQQ", "QQQM", "SMH", "SOXX", "SOXQ", "XSD", "DRAM", "QLD", "TQQQ", "QID", "SQQQ", "SSO", "UPRO", "SDS", "SPXU", "USD", "SOXL", "SSG", "SOXS")
    ])
    protected = [a0, snap]
    for relpath in ("outputs/v21/official/OFFICIAL_RANKING.csv", "outputs/v21/official/OFFICIAL_WEIGHTS.csv", "outputs/v21/real_book/REAL_BOOK.csv", "outputs/v21/broker/BROKER.csv"):
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("id,value\n1,same\n", encoding="utf-8")
        protected.append(path)
    return protected


def assert_contract(root: Path, summary: dict[str, object], before: dict[str, str]) -> None:
    out = root / module.OUT_REL
    required = (module.POOL_NAME, module.ELIGIBLE_NAME, module.SEED_AUDIT_NAME, module.FORCED_NAME, module.DUPLICATE_NAME, module.DATA_NAME, module.LINEAGE_NAME, module.SUMMARY_NAME)
    assert all((out / name).is_file() for name in required)
    assert (root / module.SEED_REL).is_file()
    rows = list(csv.DictReader((out / module.POOL_NAME).open("r", encoding="utf-8")))
    forced = list(csv.DictReader((out / module.FORCED_NAME).open("r", encoding="utf-8")))
    assert set(module.FORCED).issubset({row["ticker"] for row in forced})
    assert any(row["instrument_type"] == "STOCK" for row in rows)
    assert set(row["ticker"] for row in rows).issuperset(set(row["ticker"] for row in csv.DictReader((root / module.SEED_REL).open("r", encoding="utf-8"))))
    assert all(row["instrument_type"] and row["eligible_for_unified_pool"] for row in rows)
    assert all(row["exclusion_reason"] for row in rows if row["eligible_for_unified_pool"] == "FALSE")
    for row in rows:
        if row["instrument_type"] == "LEVERAGED_LONG_ETF":
            assert row["tactical_only"] == row["daily_reset_risk_flag"] == row["leverage_decay_risk_flag"] == "TRUE"
            assert row["default_risk_size_bucket"] != "FULL_SIZE_ALLOWED"
        if row["instrument_type"] == "INVERSE_ETF":
            assert row["hedge_only"] == "TRUE"
            assert row["default_trade_permission"] == "HEDGE_ONLY_RESEARCH"
    assert before == {path: sha(root / path) for path in before}
    assert summary["research_only"] is True
    assert summary["official_mutation_detected"] is False
    assert summary["real_book_mutation_detected"] is False
    assert summary["broker_mutation_detected"] is False
    assert summary["FINAL_STATUS"] in ALLOWED
    assert {path.parent.resolve() for path in out.glob("V21_057_R1*") if path.is_file()} == {out.resolve()}


def test_fixture_pool() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        protected = fixture(root)
        before = {path.relative_to(root).as_posix(): sha(path) for path in protected}
        summary = module.run_stage(root)
        assert summary["FINAL_STATUS"] == module.PASS_STATUS
        assert summary["duplicate_ticker_count"] == 1
        assert_contract(root, summary, before)


def test_repository_wrapper() -> None:
    protected = [path for path in (ROOT / module.A0_REL, ROOT / module.R1_SNAPSHOT_REL) if path.is_file()]
    for base in (ROOT / "outputs", ROOT / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            text = path.as_posix().lower()
            if ("official" in text and ("rank" in text or "weight" in text)) or "real_book" in text or "realbook" in text or "broker" in text:
                protected.append(path)
    before = {path.relative_to(ROOT).as_posix(): sha(path) for path in protected}
    completed = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)], cwd=ROOT, text=True, capture_output=True)
    summary_path = ROOT / module.OUT_REL / module.SUMMARY_NAME
    assert summary_path.is_file(), completed.stdout + completed.stderr
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary["FINAL_STATUS"] in {module.FAIL_STATUS, module.BLOCKED_AUDIT, module.BLOCKED_POOL}:
        assert completed.returncode != 0
    else:
        assert completed.returncode == 0, completed.stdout + completed.stderr
    assert_contract(ROOT, summary, before)


if __name__ == "__main__":
    test_fixture_pool()
    test_repository_wrapper()
    print("PASS test_v21_057_r1_unified_stock_etf_leveraged_opportunity_pool")
