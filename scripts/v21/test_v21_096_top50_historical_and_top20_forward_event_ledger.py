from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_096_top50_historical_and_top20_forward_event_ledger.py"
OUT = ROOT / "outputs/v21"


def load_module():
    spec = importlib.util.spec_from_file_location("v21_096", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_classification_and_policy() -> None:
    module = load_module()
    assert module.classify_filing("8-K", "2.02,9.01")[0] == "ticker_earnings_occurrence"
    assert module.classify_filing("8-K", "3.02")[0] == "company_financing"
    assert module.classify_filing("10-Q", "")[0] == "filing_financial_report"
    assert module.classify_filing("424B5", "")[0] == "company_financing_or_shelf_offering"
    assert module.classify_filing("DEF 14A", "")[0] == "shareholder_meeting_proxy"


def test_outputs() -> None:
    required = [
        "v21_096_r1_current_d_top50_event_universe.csv",
        "v21_096_r1_current_d_top20_forward_watchlist.csv",
        "v21_096_r2_ticker_cik_mapping.csv",
        "v21_096_r2_ticker_cik_mapping_validation.json",
        "v21_096_r2_ticker_cik_mapping_report.md",
        "v21_096_r3_top50_sec_raw_fetch_manifest.csv",
        "v21_096_r3_top50_sec_event_filings_raw.csv",
        "v21_096_r3_top50_sec_event_filings_classified.csv",
        "v21_096_r3_top50_sec_fetch_validation.json",
        "v21_096_r3_top50_sec_event_report.md",
        "v21_096_r4_top20_forward_manual_template_manifest.csv",
        "v21_096_r4_top20_forward_manual_event_validation.csv",
        "v21_096_r4_top20_forward_events_normalized.csv",
        "v21_096_r4_top20_forward_events_quarantined.csv",
        "v21_096_r5_official_macro_and_market_event_ledger.csv",
        "v21_096_r5_official_macro_source_audit.csv",
        "v21_096_r5_macro_event_report.md",
        "v21_096_r6_certified_event_master_ledger.csv",
        "v21_096_r6_event_coverage_by_top50_ticker.csv",
        "v21_096_r6_event_coverage_by_top20_ticker.csv",
        "v21_096_r6_event_coverage_by_event_type.csv",
        "v21_096_r6_event_pit_certification_audit.csv",
        "v21_096_r6_event_usage_policy.csv",
        "v21_096_r6_rejected_or_quarantined_events.csv",
        "v21_096_r7_top50_historical_top20_forward_event_ledger_report.md",
        "v21_096_r7_top50_historical_top20_forward_event_ledger_summary.json",
    ]
    assert all((OUT / name).is_file() for name in required)
    summary = json.loads((OUT / required[-1]).read_text(encoding="utf-8"))
    assert summary["D_TOP50_TICKERS_FOUND"] == 50
    assert summary["D_TOP20_TICKERS_FOUND"] == 20
    assert summary["HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED"] is False
    assert summary["PIT_LEAKAGE_WARNINGS"] == 0
    assert summary["PROTECTED_OUTPUTS_MODIFIED"] is False
    assert summary["OFFICIAL_OUTPUTS_MODIFIED"] is False
    assert summary["RESEARCH_ONLY"] is True
    assert summary["OFFICIAL_ADOPTION_ALLOWED"] is False
    assert summary["D_BASELINE_PRESERVED"] is True
    usage = pd.read_csv(OUT / required[22])
    sec_usage = usage[usage["event_type"].astype(str).str.contains(
        "filing|occurrence|agreement|management|ownership|financing|material|mna|reg_fd",
        case=False, regex=True,
    )]
    if len(sec_usage):
        assert not sec_usage["allowed_for_historical_random_retest"].astype(str).str.upper().eq("TRUE").any()


if __name__ == "__main__":
    test_classification_and_policy()
    test_outputs()
    print("V21.096 event ledger tests passed.")
