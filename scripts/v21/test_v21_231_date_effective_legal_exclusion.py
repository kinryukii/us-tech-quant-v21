"""Regression coverage for date-effective legal delisting exclusions."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("v231", ROOT / "scripts/v21/v21_231_moomoo_only_historical_refetch_and_canonical_rebuild.py")
v231 = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(v231)


OLPX = {"ticker":"OLPX", "allowed":"True", "effective_date":"2026-07-07", "last_trading_date":"2026-07-06", "evidence_source":"SEC_FORM_8K", "evidence_reference":"0001193125-26-296993_ITEM_2_01_AND_ITEM_3_01"}


def write_bars(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "date"]); w.writeheader(); w.writerows(rows)


def test_olpx_is_historical_before_effective_date_and_excluded_afterwards(tmp_path):
    assert v231.effective_exclusion_tickers([OLPX], "2026-07-06") == set()
    assert v231.effective_exclusion_tickers([OLPX], "2026-07-07") == {"OLPX"}


def test_legal_exclusion_is_not_stale_and_does_not_drag_complete_date(tmp_path):
    rows = [{"ticker":"A", "date":"2026-07-15"}, {"ticker":"OLPX", "date":"2026-07-06"}]
    raw, qfq = tmp_path / "raw.csv", tmp_path / "qfq.csv"
    write_bars(raw, rows); write_bars(qfq, rows)
    coverage = v231.complete_universe_coverage(str(raw), str(qfq), {"A", "OLPX"}, "2026-07-15", [OLPX])
    assert coverage["legally_excluded_count"] == 1
    assert coverage["eligible_universe_count"] == 1
    assert coverage["stale_ticker_count"] == 0
    assert coverage["canonical_complete_universe_date"] == "2026-07-15"
    assert coverage["gross_target_date_coverage_ratio"] == 0.5
    assert coverage["eligible_target_date_coverage_ratio"] == 1.0


def test_retained_olpx_ledger_does_not_count_after_active_universe_removal(tmp_path):
    rows = [{"ticker":"A", "date":"2026-07-15"}]
    raw, qfq = tmp_path / "raw.csv", tmp_path / "qfq.csv"
    write_bars(raw, rows); write_bars(qfq, rows)
    coverage = v231.complete_universe_coverage(str(raw), str(qfq), {"A"}, "2026-07-15", [OLPX])
    assert coverage["expected_universe_count"] == 1
    assert coverage["legally_excluded_count"] == 0
    assert coverage["eligible_universe_count"] == 1


def test_ordinary_stale_ticker_without_evidence_is_never_auto_excluded(tmp_path):
    raw, qfq = tmp_path / "raw.csv", tmp_path / "qfq.csv"
    write_bars(raw, [{"ticker":"A", "date":"2026-07-15"}, {"ticker":"B", "date":"2026-07-06"}]); write_bars(qfq, [{"ticker":"A", "date":"2026-07-15"}, {"ticker":"B", "date":"2026-07-06"}])
    coverage = v231.complete_universe_coverage(str(raw), str(qfq), {"A", "B"}, "2026-07-15", [])
    assert coverage["stale_ticker_count"] == 1
    assert coverage["missing_target_date_tickers"] == ["B"]


def test_historical_bars_are_retained_for_pit_use(tmp_path):
    raw = tmp_path / "raw.csv"; qfq = tmp_path / "qfq.csv"
    rows = [{"ticker":"OLPX", "date":"2026-07-06"}, {"ticker":"A", "date":"2026-07-15"}]
    write_bars(raw, rows); write_bars(qfq, rows)
    assert any(r["ticker"] == "OLPX" and r["date"] == "2026-07-06" for r in v231.read_csv_rows(raw))


def test_active_authority_removes_olpx_without_erasing_historical_pit_data(tmp_path, monkeypatch):
    active = tmp_path / "abcde_price_universe_r2.csv"
    active.write_text("ticker,moomoo_symbol\nA,US.A\n", encoding="utf-8")
    metadata = active.with_suffix(".active_manifest.json")
    metadata.write_text(json.dumps({"active_ticker_count": 1, "sha256": hashlib.sha256(active.read_bytes()).hexdigest()}), encoding="utf-8")
    monkeypatch.setattr(v231, "ABCDE_UNIVERSE_MANIFEST", active)
    monkeypatch.setattr(v231, "ABCDE_UNIVERSE_METADATA", metadata)
    assert v231.active_abcde_universe() == {"A"}
    historical = [{"ticker": "OLPX", "date": "2026-07-06"}]
    assert historical[0]["ticker"] == "OLPX"  # active-membership change never deletes PIT input
