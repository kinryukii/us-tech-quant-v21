from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_116_daily_top50_full_data_ledger_20260616_to_latest.py"
OUT = ROOT / "outputs/v21/V21.116_DAILY_TOP50_FULL_DATA_LEDGER_20260616_TO_LATEST"
SUMMARY = OUT / "V21.116_daily_top50_full_data_ledger_summary.json"
TARGET_DATES = {"2026-06-16", "2026-06-17", "2026-06-18", "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25"}


def test_v21_116_daily_top50_full_data_ledger_outputs() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert OUT.is_dir()
    assert SUMMARY.is_file()
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))

    for name in [
        "daily_A1_top50_full_ledger.csv",
        "daily_B_top50_full_ledger.csv",
        "daily_C_top50_full_ledger.csv",
        "daily_D_top50_full_ledger.csv",
        "daily_ABCD_top50_full_ledger.csv",
        "daily_weight_grid_top50_full_ledger.csv",
        "daily_watchlist_top50_ledger.csv",
    ]:
        assert (OUT / name).is_file(), name

    assert TARGET_DATES.issubset(set(summary["processed_dates"]))
    assert not {"2026-06-19", "2026-06-20", "2026-06-21"} & set(summary["processed_dates"])
    if "2026-06-26" in summary["processed_dates"]:
        assert summary["included_2026_06_26"] is True
        assert summary["latest_completed_daily_price_date"] >= "2026-06-26"
    else:
        assert summary["included_2026_06_26"] is False

    for name in [
        "daily_A1_top50_full_ledger.csv",
        "daily_B_top50_full_ledger.csv",
        "daily_C_top50_full_ledger.csv",
        "daily_D_top50_full_ledger.csv",
    ]:
        frame = pd.read_csv(OUT / name)
        counts = frame.groupby("as_of_date")["ticker"].count().to_dict()
        for date in summary["processed_dates"]:
            assert counts.get(date) == 50, f"{name} {date}"

    assert summary["any_prior_ranking_reuse_detected"] is False
    assert summary["protected_outputs_modified"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["research_only"] is True
