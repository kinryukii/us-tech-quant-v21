import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR"
REQ = [
    "switch_ledger_r1_full_ledger.csv",
    "switch_ledger_r1_pending_maturity.csv",
    "switch_ledger_r1_matured_results.csv",
    "switch_ledger_r1_vs_a1_comparison.csv",
    "switch_ledger_r1_new_rows_appended.csv",
    "switch_ledger_r1_deduplication_report.csv",
    "switch_ledger_r1_maturity_status_by_horizon.csv",
    "switch_ledger_r1_excluded_name_impact.csv",
    "switch_ledger_r1_data_quality_warnings.csv",
    "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR_report.txt",
    "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR_summary.json",
]


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / name)


def summary() -> dict:
    return json.loads((OUT / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR_summary.json").read_text(encoding="utf-8"))


def test_required_outputs_and_summary_exist():
    assert OUT.exists()
    for name in REQ:
        assert (OUT / name).exists(), name
    assert "final_status" in summary()


def test_policy_flags_remain_enforced():
    s = summary()
    assert s["research_only"] is True
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["live_trading_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert s["role_review_required"] is False
    assert s["switch_adoption_allowed"] is False


def test_full_ledger_rows_and_no_duplicate_keys():
    ledger = read("switch_ledger_r1_full_ledger.csv")
    assert len(ledger) > 0
    dupes = ledger.duplicated(["ranking_date", "tracked_state", "horizon"]).sum()
    assert dupes == 0


def test_pending_matured_dedup_and_horizon_outputs_exist():
    assert read("switch_ledger_r1_pending_maturity.csv") is not None
    assert read("switch_ledger_r1_matured_results.csv") is not None
    dedup = read("switch_ledger_r1_deduplication_report.csv")
    by_h = read("switch_ledger_r1_maturity_status_by_horizon.csv")
    assert len(dedup) > 0
    assert len(by_h) > 0
    assert {"5D", "10D", "20D"}.issubset(set(by_h["horizon"]))


def test_excluded_name_impact_exists():
    impact = read("switch_ledger_r1_excluded_name_impact.csv")
    assert len(impact) > 0
    assert {"HOOD", "WING", "JHX", "AMC"}.issubset(set(impact["ticker"]))


def test_if_newly_matured_vs_a1_has_rows():
    s = summary()
    comp = read("switch_ledger_r1_vs_a1_comparison.csv")
    if s["newly_matured_count"] > 0:
        assert len(comp) > 0
        assert "excess_return_vs_a1" in comp.columns


def test_output_directory_is_isolated_no_protected_modified():
    s = summary()
    assert OUT.as_posix().endswith("outputs/v21/V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR")
    for path in OUT.iterdir():
        assert path.is_file()
        assert path.parent == OUT
    assert s["protected_outputs_modified"] is False
