from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_112_r1_latest_data_abcd_rerun_20260624.py"
OUT = ROOT / "outputs/v21/V21.112_R1_LATEST_DATA_ABCD_RERUN_20260624_PRICE_REFRESH"
OLD_V112 = ROOT / "outputs/v21/V21.112_LATEST_DATA_ABCD_RERUN"


def run_script() -> dict:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    summary = OUT / "latest_abcd_summary.json"
    assert summary.is_file()
    return json.loads(summary.read_text(encoding="utf-8"))


def test_output_folder_isolated_and_v21_112_not_overwritten() -> None:
    summary = run_script()
    assert OUT.is_dir()
    assert OLD_V112.is_dir()
    assert OUT.resolve() != OLD_V112.resolve()
    assert summary["output_dir"] == "outputs/v21/V21.112_R1_LATEST_DATA_ABCD_RERUN_20260624_PRICE_REFRESH"
    assert summary["v21_112_overwritten"] is False


def test_stale_price_panel_blocks_pass() -> None:
    summary = run_script()
    if summary["latest_price_date"] < "2026-06-24":
        assert summary["FINAL_STATUS"] == "BLOCKED_V21_112_R1_STALE_PRICE_PANEL"
        assert summary["DECISION"] == "DO_NOT_ARCHIVE_AS_TRUE_LATEST_DATA"
        assert not summary["FINAL_STATUS"].startswith("PASS_")


def test_pass_requires_latest_price_date_at_or_after_20260624() -> None:
    summary = run_script()
    if summary["FINAL_STATUS"].startswith("PASS_"):
        assert summary["latest_price_date"] >= "2026-06-24"
    else:
        assert summary["latest_price_date"] < "2026-06-24"


def test_safety_flags_remain_false_or_true_as_required() -> None:
    summary = run_script()
    assert summary["protected_outputs_modified"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["research_only"] is True


def test_report_exists_and_contains_required_sections() -> None:
    run_script()
    report = OUT / "latest_abcd_report.txt"
    assert report.is_file()
    text = report.read_text(encoding="utf-8")
    assert "FINAL_STATUS=" in text
    assert "LATEST_PRICE_DATE=" in text
    assert "ABCD Top20 Tickers" in text
    for strategy in [
        "A1_BASELINE_CONTROL",
        "B_STATIC_MOMENTUM_BLEND",
        "C_DYNAMIC_MOMENTUM_BLEND",
        "D_WEIGHT_OPTIMIZED_R1",
    ]:
        assert strategy in text
