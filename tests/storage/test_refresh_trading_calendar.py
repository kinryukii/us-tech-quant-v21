"""Calendar generation respects exchange holidays and never writes the catalog."""
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.storage.refresh_trading_calendar import build_sessions, generate, digest
from scripts.storage.storage_r2a import DataStore, StoragePaths


def test_september_2026_sessions_exclude_labor_day_and_carry_utc_hours():
    frame, provenance = build_sessions("2026-09-01", "2026-09-11")
    assert frame.trade_date.tolist() == ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
                                      "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"]
    assert frame.market_open_utc.iloc[-1] == pd.Timestamp("2026-09-11T13:30:00Z")
    assert frame.market_close_utc.iloc[-1] == pd.Timestamp("2026-09-11T20:00:00Z")
    assert not frame.is_early_close.any()
    assert provenance["package"] == "exchange_calendars" and provenance["package_version"]


def test_early_close_and_daylight_saving_are_not_replaced_by_fixed_utc_hours():
    frame, _ = build_sessions("2025-11-03", "2025-11-28")
    early = frame.loc[frame.trade_date.eq("2025-11-28")].iloc[0]
    assert bool(early.is_early_close)
    assert early.market_close_utc == pd.Timestamp("2025-11-28T18:00:00Z")
    assert early.market_open_utc == pd.Timestamp("2025-11-28T14:30:00Z")
    assert "2025-11-27" not in set(frame.trade_date)


def test_generation_is_idempotent_and_preserves_provider_calendar_and_catalog(tmp_path):
    names = ["repo_root", "data_root", "cache_root", "daily_root", "backtest_root", "results_root", "envs_root"]
    store = DataStore(StoragePaths(**{name: tmp_path / name for name in names}))
    provider = store.paths.data_root / "moomoo/source/trading_calendar/us_trading_calendar.parquet"
    provider.parent.mkdir(parents=True)
    provider.write_bytes(b"preserved-original-provider-calendar")
    store.catalog_path.parent.mkdir(parents=True)
    store.catalog_path.write_bytes(b"must-not-open-or-update-catalog")
    first = generate(store, "2026-09-01", "2026-09-11")
    again = generate(store, "2026-09-01", "2026-09-11")
    assert again == first
    assert first["catalog_written"] is False and first["provider_calendar_modified"] is False
    assert first["catalog_record"]["dataset"] == "trading_calendar"
    assert digest(first["path"]) == first["sha256"]
    assert provider.read_bytes() == b"preserved-original-provider-calendar"
    assert store.catalog_path.read_bytes() == b"must-not-open-or-update-catalog"
    assert json.loads(Path(first["manifest_path"]).read_text(encoding="utf-8"))["last_session"] == "2026-09-11"
    assert len(pd.read_parquet(first["path"])) == 8


def test_invalid_or_reversed_dates_fail_before_materialization():
    with pytest.raises(ValueError):
        build_sessions("2026-09-12", "2026-09-11")
    with pytest.raises(ValueError):
        build_sessions("2026-9-1", "2026-09-11")
