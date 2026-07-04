from __future__ import annotations

import pandas as pd

from scripts.v21 import v21_199_r4a_symbol_exclusion_and_unknown_ticker_cleanup as r4a
from scripts.v21 import v21_199_r4_rate_limited_history_kline_fetch_and_resume as r4


def write_canonical(path):
    pd.DataFrame([
        {"symbol": "AAPL", "date": "2026-06-30"},
        {"symbol": "SATS", "date": "2026-06-30"},
        {"symbol": "DRAM", "date": "2026-06-30"},
    ]).to_csv(path, index=False)


def test_sats_excluded_from_active_fetch_universe(tmp_path):
    reg = tmp_path / "registry.csv"
    r4a.upsert_sats_registry(reg)
    symbols = r4.build_active_fetch_symbols(["AAPL", "SATS", "DRAM"], registry_path=reg)
    assert "SATS" not in symbols
    assert "AAPL" in symbols


def test_sats_remains_recorded_in_exclusion_audit(tmp_path):
    canonical = tmp_path / "canonical.csv"
    write_canonical(canonical)
    summary = r4a.run(tmp_path / "out", tmp_path / "registry.csv", canonical)
    audit = pd.read_csv(tmp_path / "out/unknown_ticker_audit.csv")
    assert summary["excluded_symbols"] == "SATS"
    assert "SATS" in set(audit["internal_symbol"])


def test_r4_no_longer_requests_us_sats(tmp_path):
    reg = tmp_path / "registry.csv"
    r4a.upsert_sats_registry(reg)
    mapping = r4.map_symbols(r4.build_active_fetch_symbols(["SATS", "AAPL"], registry_path=reg), include_priority=False)
    assert "US.SATS" not in set(mapping["moomoo_code"])


def test_active_universe_count_decreases_by_one(tmp_path):
    canonical = tmp_path / "canonical.csv"
    write_canonical(canonical)
    summary = r4a.run(tmp_path / "out", tmp_path / "registry.csv", canonical)
    assert summary["active_universe_count_before"] - summary["active_universe_count_after"] == 1


def test_historical_outputs_are_not_deleted(tmp_path):
    historical = tmp_path / "outputs/v21/old.csv"
    historical.parent.mkdir(parents=True)
    historical.write_text("x\n", encoding="utf-8")
    canonical = tmp_path / "canonical.csv"
    write_canonical(canonical)
    summary = r4a.run(tmp_path / "out", tmp_path / "registry.csv", canonical)
    assert historical.exists()
    assert summary["historical_outputs_deleted"] is False


def test_broker_action_allowed_false(tmp_path):
    canonical = tmp_path / "canonical.csv"
    write_canonical(canonical)
    assert r4a.run(tmp_path / "out", tmp_path / "registry.csv", canonical)["broker_action_allowed"] is False


def test_trade_api_called_false(tmp_path):
    canonical = tmp_path / "canonical.csv"
    write_canonical(canonical)
    assert r4a.run(tmp_path / "out", tmp_path / "registry.csv", canonical)["trade_api_called"] is False
