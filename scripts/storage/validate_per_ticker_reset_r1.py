"""Fast structural validation used by the destructive minimal reset R1.

This deliberately performs no historical-equivalence or network work.  It
opens each raw/QFQ parquet, validates the required OHLCV contract, and emits a
small JSON decision record for the reset orchestrator.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


REQUIRED = {"date", "open", "high", "low", "close", "volume"}


def validate_file(path: Path) -> tuple[bool, str, int]:
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        return False, f"PARQUET_OPEN_FAILED:{type(exc).__name__}", 0
    if frame.empty:
        return False, "EMPTY", 0
    missing = REQUIRED.difference(frame.columns)
    if missing:
        return False, "MISSING_COLUMNS:" + ",".join(sorted(missing)), len(frame)
    dates = pd.to_datetime(frame["date"], errors="coerce")
    if dates.isna().any():
        return False, "UNPARSEABLE_DATE", len(frame)
    numeric = frame[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    if (numeric["high"].notna() & numeric["low"].notna() & (numeric["high"] < numeric["low"])).any():
        return False, "HIGH_BELOW_LOW", len(frame)
    if (numeric["volume"].notna() & (numeric["volume"] < 0)).any():
        return False, "NEGATIVE_VOLUME", len(frame)
    return True, "PASS", len(frame)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stocks-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results: list[dict[str, object]] = []
    for ticker_dir in sorted((p for p in args.stocks_root.iterdir() if p.is_dir()), key=lambda p: p.name):
        ticker = ticker_dir.name
        metadata_path = ticker_dir / "metadata.json"
        metadata_ok = False
        try:
            metadata_ok = isinstance(json.loads(metadata_path.read_text(encoding="utf-8")), dict)
        except Exception:
            pass
        raw_ok, raw_reason, raw_rows = validate_file(ticker_dir / "daily_raw.parquet")
        qfq_ok, qfq_reason, qfq_rows = validate_file(ticker_dir / "daily_qfq.parquet")
        results.append({
            "ticker": ticker,
            "valid": raw_ok and qfq_ok and metadata_ok,
            "raw_ok": raw_ok, "raw_reason": raw_reason, "raw_rows": raw_rows,
            "qfq_ok": qfq_ok, "qfq_reason": qfq_reason, "qfq_rows": qfq_rows,
            "metadata_ok": metadata_ok,
        })
    valid = sum(bool(row["valid"]) for row in results)
    total = len(results)
    payload = {
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "ticker_count": total,
        "valid_ticker_count": valid,
        "valid_ticker_ratio": valid / total if total else 0.0,
        "preserve_stocks": bool(total and valid / total >= 0.98),
        "invalid_tickers": [row for row in results if not row["valid"]],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, args.output)
    print(json.dumps({key: value for key, value in payload.items() if key != "invalid_tickers"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
