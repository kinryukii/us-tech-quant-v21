from __future__ import annotations

import json
import importlib.util
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21"
SCRIPT = ROOT / "scripts/v21/v21_095_r6_import_pit_timestamped_macro_and_earnings_snapshots.py"


def load_module():
    spec = importlib.util.spec_from_file_location("v21_095_r6", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_chain() -> None:
    names = [
        "v21_095_r6_manual_import_manifest.csv",
        "v21_095_r6_raw_snapshot_hash_manifest.csv",
        "v21_095_r6_macro_events_normalized.csv",
        "v21_095_r6_ticker_earnings_events_normalized.csv",
        "v21_095_r6_certified_event_snapshot_ledger.csv",
        "v21_095_r6_rejected_or_quarantined_import_rows.csv",
        "v21_095_r6_event_coverage_by_ticker.csv",
        "v21_095_r6_event_coverage_by_event_type.csv",
        "v21_095_r6_pit_certification_audit.csv",
        "v21_095_r6_import_pit_timestamped_event_snapshots_report.md",
        "v21_095_r6_import_pit_timestamped_event_snapshots_summary.json",
    ]
    assert all((OUT / name).is_file() for name in names)
    summary = json.loads((OUT / names[-1]).read_text(encoding="utf-8"))
    assert summary["FINAL_STATUS"] == "PASS"
    assert summary["PIT_LEAKAGE_WARNINGS"] == 0
    assert summary["PROTECTED_OUTPUTS_MODIFIED"] is False
    assert summary["OFFICIAL_OUTPUTS_MODIFIED"] is False
    assert summary["RESEARCH_ONLY"] is True
    assert summary["OFFICIAL_ADOPTION_ALLOWED"] is False
    assert summary["D_BASELINE_PRESERVED"] is True

    ledger = pd.read_csv(OUT / names[4])
    assert ledger["event_id"].is_unique
    certified = ledger["pit_certified"].astype(str).str.upper().eq("TRUE")
    assert pd.to_datetime(
        ledger.loc[certified, "known_as_of_timestamp"], utc=True, errors="coerce"
    ).notna().all()
    assert ledger.loc[certified, "raw_payload_hash"].astype(str).str.len().eq(64).all()

    manifest = pd.read_csv(OUT / names[0])
    snapshots = pd.read_csv(OUT / names[1])
    if len(snapshots):
        assert snapshots["hash_match"].astype(str).str.upper().eq("TRUE").all()
    if len(manifest) == 0:
        assert summary["DECISION"] == "NO_MANUAL_EVENT_IMPORT_FILES_FOUND"


def test_isolated_import_logic() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        for directory in module.IMPORT_SPECS.values():
            (root / directory).mkdir(parents=True, exist_ok=True)
        macro = pd.DataFrame([{
            "event_type": "macro_cpi", "event_name": "CPI release",
            "event_date": "2026-07-14", "event_time": "08:30:00",
            "event_timezone": "America/New_York", "source_name": "BLS",
            "source_url_or_provider": "official-test",
            "retrieval_timestamp_utc": "2026-06-22T08:00:00Z",
            "provider_available_date": "", "notes": "schedule only",
        }])
        earnings = pd.DataFrame([{
            "ticker": "WDC", "event_type": "ticker_earnings",
            "event_name": "WDC earnings", "event_date": "2026-07-20",
            "event_time": "16:05:00", "event_timezone": "America/New_York",
            "earnings_session": "AFTER_MARKET", "source_name": "provider-test",
            "source_url_or_provider": "local-test",
            "retrieval_timestamp_utc": "2026-06-22T08:00:00Z",
            "provider_available_date": "2026-06-20T08:00:00Z",
            "notes": "schedule only",
        }])
        macro.to_csv(root / module.IMPORT_SPECS["macro"] / "macro.csv", index=False)
        earnings.to_csv(root / module.IMPORT_SPECS["earnings"] / "earnings.csv", index=False)
        manifest = module.scan_imports(root)
        assert len(manifest) == 2
        assert manifest["safe_to_import"].map(module.truth).all()
        run_ts = pd.Timestamp("2026-06-22T09:00:00Z")
        snapshots = module.snapshot_files(root, manifest, "2026-06-22", run_ts)
        assert snapshots["hash_match"].map(module.truth).all()
        normalized = module.normalize_rows(
            root, snapshots, {"WDC"}, run_ts,
            pd.Timestamp("2024-01-01T00:00:00Z"),
            pd.Timestamp("2025-12-31T00:00:00Z"),
        )
        assert len(normalized) == 2
        assert normalized["pit_certified"].map(module.truth).all()
        assert normalized["forward_observation_usable"].map(module.truth).all()
        assert not normalized["historical_backtest_usable"].map(module.truth).any()
        wdc = normalized[normalized["affected_ticker"].eq("WDC")].iloc[0]
        assert wdc["known_as_of_timestamp"].startswith("2026-06-20")
        assert bool(wdc["candidate_universe_member"])


if __name__ == "__main__":
    test_chain()
    test_isolated_import_logic()
    print("V21.095-R6 manual event snapshot import tests passed.")
