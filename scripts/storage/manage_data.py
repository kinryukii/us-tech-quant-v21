"""Inspect the file catalog and manage data requests without changing a strategy.

Run as ``python -m scripts.storage.manage_data``. Downloads remain explicit via
scripts.storage.refresh_market_data. A subscription is an acquisition request,
never an authoritative security identity or a strategy-universe membership.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from scripts.storage.storage_r2a import DataStore, resolve_storage_paths


SUBSCRIPTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS data_subscriptions(
 provider_code TEXT PRIMARY KEY,ticker TEXT NOT NULL,requested_start TEXT NOT NULL,
 target_date TEXT NOT NULL,identity_source TEXT NOT NULL,status TEXT NOT NULL);
"""
PLAN_FIELDS = ["ticker", "moomoo_symbol", "adjustment", "start", "end", "reason",
               "catalog_min_date", "catalog_max_date", "mapping_status", "identity_status"]


def iso_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("dates must use YYYY-MM-DD")
    return value


def read_catalog(store: DataStore) -> tuple[list[dict], list[dict]]:
    """Read metadata only, validating the shared schema before any query."""
    prices = store._catalog_rows("prices_daily")
    with sqlite3.connect(store.catalog_path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        subscriptions = [dict(row) for row in connection.execute(
            "SELECT * FROM data_subscriptions ORDER BY ticker, provider_code"
        )] if "data_subscriptions" in tables else []
    return prices, subscriptions


def acquisition_tickers(store: DataStore) -> list[str]:
    """Union explicitly catalogued price symbols and requested subscriptions.

    This is a data acquisition scope, never a strategy or historical identity.
    Provider-only additions remain discoverable on subsequent maintenance runs.
    """
    from scripts.storage.storage_r2a import DAILY_PRICE_CONTRACTS
    prices, subscriptions = read_catalog(store)
    symbols = {row['ticker'] for row in prices} | {row['ticker'] for row in subscriptions}
    for dataset in DAILY_PRICE_CONTRACTS:
        if dataset != 'prices_daily':
            symbols.update(row['ticker'] for row in store._catalog_rows(dataset))
    return sorted(store._ticker(ticker) for ticker in symbols)


def status(store: DataStore) -> dict:
    prices, subscriptions = read_catalog(store)
    with sqlite3.connect(store.catalog_path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        datasets = [dict(row) for row in connection.execute("""
            SELECT dataset, adjustment, COUNT(*) AS current_files, SUM(row_count) AS rows,
                   MIN(min_date) AS earliest_date, MIN(max_date) AS oldest_latest_date,
                   MAX(max_date) AS newest_latest_date
            FROM data_files WHERE is_current=1 GROUP BY dataset, adjustment ORDER BY dataset, adjustment
        """)]
    return {"catalog": str(store.catalog_path), "catalog_role": "REBUILDABLE_FILE_INDEX",
            "price_tickers": len({row["ticker"] for row in prices}), "datasets": datasets,
            "price_files_missing_on_disk": sum(not Path(row["path"]).exists() for row in prices),
            "subscriptions": subscriptions,
            "coverage_scope": "Catalog coverage plus price-file existence; internal session gaps are not verified."}


def register_subscription(store: DataStore, *, provider_code: str, ticker: str, start: str,
                          target: str, identity_source: str) -> dict:
    read_catalog(store)
    ticker = store._ticker(ticker)
    provider_code = provider_code.strip().upper()
    if not re.fullmatch(r"US\.[A-Z0-9][A-Z0-9._/-]{0,63}", provider_code) or ".." in provider_code:
        raise ValueError("an explicit valid US provider_code is required")
    start, target = iso_date(start), iso_date(target)
    if start > target:
        raise ValueError("start must not exceed target")
    identity_source = identity_source.strip()
    if not identity_source:
        raise ValueError("identity_source must be explicit; use unknown when evidence is unavailable")
    identity_status = "PENDING_IDENTITY" if identity_source.lower() in {
        "unknown", "pending", "none", "n/a", "unverified"
    } else "REQUESTED_IDENTITY_REVIEW"
    request = {"provider_code": provider_code, "ticker": ticker, "requested_start": start,
               "target_date": target, "identity_source": identity_source, "status": identity_status}
    with sqlite3.connect(store.catalog_path) as connection:
        connection.executescript(SUBSCRIPTION_SCHEMA)
        existing = connection.execute("SELECT ticker FROM data_subscriptions WHERE provider_code=?",
                                      (provider_code,)).fetchone()
        if existing and existing[0] != ticker:
            raise ValueError("provider_code already belongs to another subscription ticker")
        connection.execute("""
            INSERT INTO data_subscriptions VALUES (:provider_code,:ticker,:requested_start,:target_date,:identity_source,:status)
            ON CONFLICT(provider_code) DO UPDATE SET requested_start=excluded.requested_start,
                target_date=excluded.target_date, identity_source=excluded.identity_source, status=excluded.status
        """, request)
    return {"subscription": request, "strategy_universe_changed": False,
            "download_started": False, "identity_authority_changed": False}


def build_plan(store: DataStore, *, start: str, target: str, tickers: list[str] | None = None,
               adjustments: list[str] | None = None) -> list[dict]:
    start, target = iso_date(start), iso_date(target)
    if start > target:
        raise ValueError("start must not exceed target")
    prices, subscriptions = read_catalog(store)
    by_key = {(row["ticker"], row["adjustment"]): row for row in prices}
    requests = {}
    for row in subscriptions:
        requests.setdefault(row["ticker"], []).append(row)
    symbols = sorted({store._ticker(t) for t in tickers}) if tickers else sorted(
        {row["ticker"] for row in prices} | set(requests)
    )
    adjustments = [store._adjustment(a) for a in (adjustments or ["raw", "qfq"])]
    plan = []
    for ticker in symbols:
        matches = requests.get(ticker, [])
        provider_codes = {row["provider_code"] for row in matches}
        if len(provider_codes) == 1:
            provider = next(iter(provider_codes)); mapping = "EXPLICIT_SUBSCRIPTION"
        elif len(provider_codes) > 1:
            provider = ""; mapping = "BLOCKED_AMBIGUOUS_PROVIDER_MAPPING"
        elif re.fullmatch(r"[A-Z0-9]+", ticker):
            provider = "US." + ticker; mapping = "STANDARD_US_TRANSPORT_NOT_PIT_IDENTITY"
        else:
            provider = ""; mapping = "BLOCKED_PROVIDER_MAPPING_REQUIRED"
        identity_status = "|".join(sorted({row["status"] for row in matches})) or "PENDING_IDENTITY"
        for adjustment in adjustments:
            row = by_key.get((ticker, adjustment), {})
            first, last = row.get("min_date"), row.get("max_date")
            intervals = []
            path_missing = bool(row) and not store._check_data_path(Path(row["path"]), must_exist=False).exists()
            if path_missing:
                intervals.append((start, target, "MISSING_FILE"))
            elif not first or not last:
                intervals.append((start, target, "MISSING_DATA"))
            else:
                first, last = iso_date(str(first)[:10]), iso_date(str(last)[:10])
                if first > last:
                    raise ValueError(f"invalid coverage interval for {ticker}/{adjustment}")
                if start < first:
                    intervals.append((start, min(target, (date.fromisoformat(first)-timedelta(days=1)).isoformat()), "PREFIX_GAP"))
                if target > last:
                    intervals.append((max(start, (date.fromisoformat(last)+timedelta(days=1)).isoformat()), target, "TAIL_GAP"))
            for lower, upper, reason in intervals:
                if lower <= upper:
                    plan.append({"ticker": ticker, "moomoo_symbol": provider, "adjustment": adjustment,
                                 "start": lower, "end": upper, "reason": reason,
                                 "catalog_min_date": first or "", "catalog_max_date": last or "",
                                 "mapping_status": mapping, "identity_status": identity_status})
    return plan


def write_plan(store: DataStore, rows: list[dict], output: Path) -> None:
    output = store._check_data_path(output, must_exist=False)
    if output.suffix.lower() != ".csv":
        raise ValueError("plan --output must name a CSV file")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PLAN_FIELDS)
        writer.writeheader(); writer.writerows(rows)
    os.replace(temporary, output)


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--catalog", type=Path)
    for root in ["repo", "data", "cache", "results", "daily", "backtest"]:
        cli.add_argument(f"--{root}-root", type=Path)
    sub = cli.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="show metadata coverage and acquisition subscriptions")
    price = sub.add_parser("prices", help="read a bounded price interval as CSV on stdout")
    price.add_argument("--ticker", required=True)
    price.add_argument("--adjustment", choices=["raw", "qfq"], default="qfq")
    price.add_argument("--start", required=True); price.add_argument("--end", required=True)
    price.add_argument("--limit", type=int, default=20)
    plan = sub.add_parser("plan", help="write boundary coverage gaps without downloading")
    plan.add_argument("--start", required=True); plan.add_argument("--target", required=True)
    plan.add_argument("--output", type=Path, required=True)
    plan.add_argument("--tickers", nargs="+")
    plan.add_argument("--adjustments", nargs="+", choices=["raw", "qfq"], default=["raw", "qfq"])
    add = sub.add_parser("add-stock", help="record an explicit data request, not strategy membership")
    add.add_argument("--provider-code", required=True); add.add_argument("--ticker", required=True)
    add.add_argument("--start", required=True); add.add_argument("--target", required=True)
    add.add_argument("--identity-source", required=True)
    return cli


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        roots = {f"{key}_root": getattr(args, f"{key}_root") for key in (
            "repo", "data", "cache", "results", "daily", "backtest"
        )}
        store = DataStore(resolve_storage_paths(**roots), args.catalog)
        if args.command == "status":
            result = status(store)
        elif args.command == "prices":
            if args.limit < 1:
                raise ValueError("limit must be positive")
            frame = store.daily(args.ticker, args.adjustment, iso_date(args.start), iso_date(args.end))
            print(frame.head(args.limit).to_csv(index=False), end="")
            return 0
        elif args.command == "add-stock":
            result = register_subscription(store, provider_code=args.provider_code, ticker=args.ticker,
                                           start=args.start, target=args.target, identity_source=args.identity_source)
        else:
            rows = build_plan(store, start=args.start, target=args.target, tickers=args.tickers,
                              adjustments=args.adjustments)
            write_plan(store, rows, args.output)
            result = {"output": str(args.output.resolve()), "planned_intervals": len(rows),
                      "blocked_mapping_intervals": sum(row["mapping_status"].startswith("BLOCKED") for row in rows),
                      "download_started": False, "coverage_scope": "Boundary gaps only; internal sessions are not audited.",
                      "download_entrypoint": "python -m scripts.storage.refresh_market_data",
                      "download_note": "Use a reviewed, fully mapped universe CSV and explicit --start/--end/--work-root. "
                                       "Refresh uses global dates; interval rows are a plan, not automatic per-row execution. "
                                       "QFQ updates require sufficient overlapping history or a complete matching vintage."}
        print(json.dumps(result, ensure_ascii=True, default=str))
        return 0
    except (ValueError, KeyError, FileNotFoundError, sqlite3.DatabaseError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
