from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21"


def test_chain() -> None:
    names = [
        "v21_094_r1_event_source_candidate_inventory.csv",
        "v21_094_r1_event_source_candidate_inventory_summary.json",
        "v21_094_r1_event_source_candidate_inventory_report.md",
        "v21_094_r2_verified_ticker_earnings_events.csv",
        "v21_094_r2_rejected_ticker_earnings_events.csv",
        "v21_094_r2_ticker_earnings_coverage_summary.csv",
        "v21_094_r2_ticker_earnings_ingestion_validation.json",
        "v21_094_r2_ticker_earnings_ingestion_report.md",
        "v21_094_r3_verified_macro_events.csv",
        "v21_094_r3_rejected_macro_events.csv",
        "v21_094_r3_macro_event_coverage_summary.csv",
        "v21_094_r3_macro_ingestion_validation.json",
        "v21_094_r3_macro_ingestion_report.md",
        "v21_094_r4_sector_key_event_mapping.csv",
        "v21_094_r4_sector_propagated_events.csv",
        "v21_094_r4_sector_event_mapping_validation.json",
        "v21_094_r4_sector_event_mapping_report.md",
        "v21_094_r5_certified_event_master_ledger.csv",
        "v21_094_r5_rejected_event_quarantine.csv",
        "v21_094_r5_event_coverage_by_ticker.csv",
        "v21_094_r5_event_coverage_by_event_type.csv",
        "v21_094_r5_event_pit_certification_audit.csv",
        "v21_094_r5_certified_event_source_summary.json",
        "v21_094_r5_certified_event_source_report.md",
    ]
    assert all((OUT / name).is_file() for name in names)
    summary = json.loads((OUT / names[-2]).read_text(encoding="utf-8"))
    assert summary["FINAL_STATUS"] == "PASS"
    assert summary["PIT_LEAKAGE_WARNINGS"] == 0
    assert summary["PROTECTED_OUTPUTS_MODIFIED"] is False
    assert summary["OFFICIAL_OUTPUTS_MODIFIED"] is False
    assert summary["RESEARCH_ONLY"] is True
    assert summary["OFFICIAL_ADOPTION_ALLOWED"] is False
    assert summary["D_BASELINE_PRESERVED"] is True

    inventory = pd.read_csv(OUT / names[0])
    assert set(["source_path", "pit_certification_possible", "safe_to_ingest"]).issubset(inventory.columns)
    ledger = pd.read_csv(OUT / names[17])
    assert ledger["event_id"].is_unique
    assert ledger["pit_certified"].astype(str).str.upper().eq("TRUE").all()
    assert pd.to_datetime(ledger["known_as_of_timestamp"], utc=True, errors="coerce").notna().all()

    mapping = pd.read_csv(OUT / names[13])
    assert {"MU", "WDC", "STX", "SNDK", "AMKR"}.issubset(set(mapping["ticker"]))
    assert {"SOXX", "SMH", "QQQ", "TQQQ"}.issubset(set(mapping["ticker"]))


if __name__ == "__main__":
    test_chain()
    print("V21.094 verified ticker event source ingestion tests passed.")
