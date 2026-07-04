from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.v21 import v21_201_dram_moomoo_r4_date_alignment_and_plan_refresh as v201


ROOT = Path(__file__).resolve().parents[2]


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def dram_rows(latest="2026-06-30", include=True):
    if not include:
        return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"])
    dates = pd.date_range("2026-05-01", latest, freq="B")
    return pd.DataFrame([
        {"symbol": "DRAM", "date": d.strftime("%Y-%m-%d"), "open": 10 + i * 0.1, "high": 10.5 + i * 0.1, "low": 9.8 + i * 0.1, "close": 10.2 + i * 0.1, "volume": 1000 + i}
        for i, d in enumerate(dates)
    ])


def run_tmp(tmp_path, raw_latest="2026-06-30", raw_present=True, r4_date="2026-06-30"):
    r4 = tmp_path / "r4.json"
    abcde = tmp_path / "abcde.json"
    raw = tmp_path / "raw.csv"
    staging = tmp_path / "staging.csv"
    write_json(r4, {"latest_moomoo_broad_honest_date": r4_date})
    write_json(abcde, {"target_rerun_date": "2026-06-30"})
    dram_rows(raw_latest, raw_present).to_csv(raw, index=False)
    pd.DataFrame().to_csv(staging, index=False)
    return v201.run(tmp_path / "out", r4, raw, staging, abcde)


def test_dram_raw_present_latest_equals_r4_pass(tmp_path):
    summary = run_tmp(tmp_path)
    assert summary["final_status"] == "PASS_V21_201_DRAM_MOOMOO_R4_PLAN_READY"
    assert summary["latest_price_date"] == "2026-06-30"
    assert summary["latest_plan_date"] == "2026-06-30"


def test_dram_raw_missing_fails(tmp_path):
    summary = run_tmp(tmp_path, raw_present=False)
    assert summary["final_status"] == "FAIL_V21_201_DRAM_MOOMOO_RAW_STALE_OR_MISSING"


def test_dram_raw_stale_by_one_day_fails(tmp_path):
    summary = run_tmp(tmp_path, raw_latest="2026-06-29")
    assert summary["final_status"] == "FAIL_V21_201_DRAM_MOOMOO_RAW_STALE_OR_MISSING"


def test_r4_date_differs_from_v201_plan_root_alignment_fails():
    assert not v201.dates_aligned("2026-06-30", "2026-06-30", "2026-06-29")


def test_v201_preserves_research_only(tmp_path):
    assert run_tmp(tmp_path)["research_only"] is True


def test_v201_preserves_broker_action_false(tmp_path):
    assert run_tmp(tmp_path)["broker_action_allowed"] is False


def test_v201_does_not_call_trade_apis(tmp_path):
    assert run_tmp(tmp_path)["trade_api_called"] is False


def test_v201_does_not_mutate_protected_outputs(tmp_path):
    assert run_tmp(tmp_path)["protected_outputs_modified"] is False


def test_root_chain_passes_only_when_r4_abcde_dram_dates_match():
    assert v201.dates_aligned("2026-06-30", "2026-06-30", "2026-06-30")
    script = (ROOT / "scripts/run_daily_moomoo_research_chain.ps1").read_text(encoding="utf-8")
    assert "run_v21_201_dram_moomoo_r4_date_alignment_and_plan_refresh.ps1" in script
    assert "FAIL_DAILY_MOOMOO_RESEARCH_CHAIN_DRAM_DATE_MISMATCH" in script
