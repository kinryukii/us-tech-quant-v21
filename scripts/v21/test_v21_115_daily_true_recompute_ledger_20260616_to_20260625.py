from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_115_daily_true_recompute_ledger_20260616_to_20260625.py"
OUT = ROOT / "outputs/v21/V21.115_DAILY_TRUE_RECOMPUTE_LEDGER_20260616_TO_20260625"
SUMMARY = OUT / "V21.115_daily_true_recompute_ledger_summary.json"
TARGET_DATES = ["2026-06-16", "2026-06-17", "2026-06-18", "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25"]


def test_v21_115_daily_true_recompute_ledger_outputs() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert OUT.is_dir()
    assert SUMMARY.is_file()
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))

    for name in [
        "daily_status_ledger.csv",
        "daily_d_top20_ledger.csv",
        "daily_d_top50_ledger.csv",
        "daily_weight_grid_top20_ledger.csv",
        "daily_dram_mu_sndk_wdc_watchlist.csv",
    ]:
        assert (OUT / name).is_file(), name

    status = pd.read_csv(OUT / "daily_status_ledger.csv")
    assert set(status["as_of_date"].astype(str)) == set(TARGET_DATES)
    assert not {"2026-06-19", "2026-06-20", "2026-06-21"} & set(status["as_of_date"].astype(str))
    for _, row in status.iterrows():
        as_of = str(row["as_of_date"])
        assert str(row["price_data_max_date_used"]) <= as_of
        for field in ["A1_ranking_latest_date", "B_ranking_latest_date", "C_ranking_latest_date", "D_ranking_latest_date"]:
            assert str(row[field]) <= as_of
        assert row["read_v21_112_ranking_as_input"] in [False, "False", "FALSE", 0]
        assert row["read_v21_113_ranking_as_input"] in [False, "False", "FALSE", 0]

    if summary["FINAL_STATUS"].startswith(("PASS", "PARTIAL_PASS")):
        assert int(status["stale_factor_input_count"].sum()) == 0

    assert summary["protected_outputs_modified"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["research_only"] is True
    assert summary["any_prior_ranking_reuse_detected"] is False

    report = (OUT / "V21.115_daily_true_recompute_ledger_report.md").read_text(encoding="utf-8")
    assert "From 2026-06-16 onward, which prior daily/latest runs were only price-refresh or stale-cache, and what are the corrected daily ABCD rankings?" in report
