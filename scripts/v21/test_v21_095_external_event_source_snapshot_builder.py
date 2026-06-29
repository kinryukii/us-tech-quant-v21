from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21"


def test_chain() -> None:
    required = [
        "v21_095_r1_event_source_registry.csv",
        "v21_095_r1_event_schema_contract.json",
        "v21_095_r1_event_schema_report.md",
        "v21_095_r2_macro_event_snapshot_raw_manifest.csv",
        "v21_095_r2_macro_event_normalized.csv",
        "v21_095_r2_macro_event_ingestion_validation.json",
        "v21_095_r2_macro_event_ingestion_report.md",
        "v21_095_r3_ticker_earnings_raw_manifest.csv",
        "v21_095_r3_ticker_earnings_normalized.csv",
        "v21_095_r3_ticker_earnings_rejected.csv",
        "v21_095_r3_ticker_earnings_coverage_summary.csv",
        "v21_095_r3_ticker_earnings_ingestion_validation.json",
        "v21_095_r3_ticker_earnings_ingestion_report.md",
        "v21_095_r4_certified_event_snapshot_ledger.csv",
        "v21_095_r4_event_snapshot_pit_audit.csv",
        "v21_095_r4_event_snapshot_usage_policy.csv",
        "v21_095_r4_rejected_or_quarantined_events.csv",
        "v21_095_r4_pit_certification_validation.json",
        "v21_095_r4_pit_certification_report.md",
        "v21_095_r5_event_source_readiness_summary.json",
        "v21_095_r5_event_source_readiness_report.md",
    ]
    assert all((OUT / name).is_file() for name in required)
    summary = json.loads((OUT / required[-2]).read_text(encoding="utf-8"))
    assert summary["FINAL_STATUS"] == "PASS"
    assert summary["PIT_LEAKAGE_WARNINGS"] == 0
    assert summary["PROTECTED_OUTPUTS_MODIFIED"] is False
    assert summary["OFFICIAL_OUTPUTS_MODIFIED"] is False
    assert summary["RESEARCH_ONLY"] is True
    assert summary["OFFICIAL_ADOPTION_ALLOWED"] is False
    assert summary["D_BASELINE_PRESERVED"] is True

    registry = pd.read_csv(OUT / required[0])
    assert {"FED_FOMC_OFFICIAL", "BLS_CPI_OFFICIAL", "BLS_NFP_OFFICIAL",
            "BEA_PCE_OFFICIAL", "BEA_GDP_OFFICIAL",
            "EARNINGS_MANUAL_IMPORT"}.issubset(set(registry["source_id"]))
    ledger = pd.read_csv(OUT / required[13])
    assert ledger["event_id"].is_unique
    assert pd.to_datetime(ledger["known_as_of_timestamp"], utc=True, errors="coerce").notna().all()
    assert ledger["raw_payload_hash"].astype(str).str.len().eq(64).all()
    assert ledger["normalized_row_hash"].astype(str).str.len().eq(64).all()
    usage = pd.read_csv(OUT / required[15])
    assert set(usage["usage_mode"]) == {"FORWARD_OBSERVATION", "HISTORICAL_RANDOM_BACKTEST"}


if __name__ == "__main__":
    test_chain()
    print("V21.095 external event source snapshot builder tests passed.")
