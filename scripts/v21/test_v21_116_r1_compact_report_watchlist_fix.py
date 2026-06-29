from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_116_r1_compact_report_watchlist_fix.py"
OUT = ROOT / "outputs/v21/V21.116_R1_COMPACT_REPORT_WATCHLIST_FIX"


def test_v21_116_r1_compact_report_watchlist_fix() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads((OUT / "V21.116_R1_compact_report_watchlist_fix_summary.json").read_text(encoding="utf-8"))
    assert summary["inconsistency_count"] == 0
    assert (OUT / "V21.116_R1_compact_readable_top50_report_FIXED.txt").is_file()
    check = pd.read_csv(OUT / "watchlist_consistency_check.csv")
    assert check["consistent"].astype(str).str.upper().eq("TRUE").all()
    wdc = check[(check["as_of_date"].eq("2026-06-16")) & (check["ticker"].eq("WDC"))].iloc[0]
    assert int(wdc["d_rank"]) == 2
    assert str(wdc["reported_top20"]).upper() == "TRUE"
    assert str(wdc["reported_top50"]).upper() == "TRUE"
