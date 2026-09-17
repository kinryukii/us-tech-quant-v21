"""Generate a versioned XNYS regular-session calendar without writing the catalog.

The installed exchange_calendars package supplies all sessions, holidays and
early closes. The existing provider calendar is preserved. Register the emitted
catalog_record only after any concurrent catalog build has finished.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from scripts.storage.storage_r2a import DataStore, resolve_storage_paths


SOURCE_URL = "https://github.com/gerrymanoim/exchange_calendars"
NYSE_REFERENCE_URL = "https://www.nyse.com/trade/hours-calendars"


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            value.update(chunk)
    return value.hexdigest()


def build_sessions(start, end):
    import exchange_calendars

    start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
    if start_day.isoformat() != start or end_day.isoformat() != end or start_day > end_day:
        raise ValueError("start/end must be ordered YYYY-MM-DD dates")
    calendar = exchange_calendars.get_calendar("XNYS", start=start, end=end)
    schedule = calendar.schedule
    version = importlib.metadata.version("exchange_calendars")
    frame = pd.DataFrame({
        "trade_date": schedule.index.strftime("%Y-%m-%d"),
        "exchange": "XNYS", "timezone": str(calendar.tz),
        "market_open_utc": schedule["open"].to_numpy(),
        "market_close_utc": schedule["close"].to_numpy(),
        "is_early_close": schedule.index.isin(calendar.early_closes),
        "is_session": True, "source": "EXCHANGE_CALENDARS_XNYS", "source_package_version": version,
    })
    frame["market_open_utc"] = pd.to_datetime(frame.market_open_utc, utc=True)
    frame["market_close_utc"] = pd.to_datetime(frame.market_close_utc, utc=True)
    if frame.empty or frame.trade_date.duplicated().any() or not frame.trade_date.is_monotonic_increasing:
        raise ValueError("invalid or empty calendar sessions")
    if frame.trade_date.min() < start or frame.trade_date.max() > end:
        raise ValueError("calendar escaped requested date bounds")
    if not frame.market_open_utc.lt(frame.market_close_utc).all():
        raise ValueError("calendar open must precede close")
    local_days = frame.market_open_utc.dt.tz_convert(str(calendar.tz)).dt.strftime("%Y-%m-%d")
    if not local_days.eq(frame.trade_date).all():
        raise ValueError("XNYS session date does not match local opening date")
    rule_module = importlib.import_module(type(calendar).__module__)
    provenance = {"package": "exchange_calendars", "package_version": version,
                  "source_url": SOURCE_URL, "official_reference_url": NYSE_REFERENCE_URL,
                  "calendar_class": type(calendar).__module__ + "." + type(calendar).__name__,
                  "rule_module_sha256": digest(rule_module.__file__),
                  "source_role": "GENERATED_EXCHANGE_SCHEDULE_NOT_PROVIDER_PRICE_DATA"}
    return frame, provenance


def generate(store, start, end):
    frame, provenance = build_sessions(start, end)
    directory = store._check_data_path(store.paths.data_root / "reference/trading_calendar/XNYS/versions", must_exist=False)
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=directory, prefix="xnys_sessions.", suffix=".parquet", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        sha = digest(temporary)
        path = directory / f"xnys_sessions_{sha[:20]}.parquet"
        if path.exists():
            if digest(path) != sha:
                raise ValueError("calendar content-address collision")
        else:
            os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    manifest_path = path.with_suffix(".manifest.json")
    lineage = {"date_column": "trade_date", "calendar": "XNYS", "timezone": "America/New_York",
               "requested_start": start, "requested_end": end, "manifest_path": str(manifest_path), **provenance}
    record = {"dataset": "trading_calendar", "ticker": "", "adjustment": "", "path": str(path),
              "row_count": len(frame), "min_date": frame.trade_date.min(), "max_date": frame.trade_date.max(),
              "source": "EXCHANGE_CALENDARS_XNYS", "lineage": lineage}
    manifest = {"schema_version": 1, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "requested_start": start, "requested_end": end, "calendar": "XNYS",
                "session_count": len(frame), "early_close_count": int(frame.is_early_close.sum()),
                "first_session": frame.trade_date.min(), "last_session": frame.trade_date.max(),
                "path": str(path), "sha256": sha, "manifest_path": str(manifest_path),
                "source": provenance, "catalog_record": record, "catalog_written": False,
                "provider_calendar_modified": False,
                "limitations": ["XNYS regular cash-equity sessions; not pre/post-market or every US venue.",
                                "Generated from the installed calendar package; not a fetched broker calendar.",
                                "Complete for the requested range under this recorded package version.",
                                "Eventual unscheduled closures or rule corrections require a new recorded version."]}
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous["sha256"] != sha or previous["catalog_record"] != record:
            raise ValueError("existing calendar manifest contract conflict")
        return previous
    with manifest_path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2019-01-01")
    parser.add_argument("--end", required=True)
    parser.add_argument("--data-root", type=Path)
    args = parser.parse_args(argv)
    store = DataStore(resolve_storage_paths(data_root=args.data_root))
    manifest = generate(store, args.start, args.end)
    print(json.dumps(manifest, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
