"""Low-memory, resumable comparison of legacy forward-return CSV data.

The reader is deliberately chunked: it reads only ticker/date/one forward column
from the legacy CSV and never copies either the panel or market-data inputs.
Intermediate SQLite state is kept inside ``--output-dir`` so a stopped scan can
be resumed without counting completed chunks twice.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from collections import OrderedDict, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ALLOWED_HORIZONS = {1, 5, 10, 20}
SCHEMA_VERSION = "LEGACY_FORWARD_OVERLAP_R2_CANONICAL_DUPLICATES"
DATE_CANDIDATES = ("research_date", "price_date", "asof_date", "date")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding="utf-8")
    os.replace(temporary, path)


def _append_journal(path: Path, event: dict[str, Any]) -> None:
    event["at"] = _utc_now()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, default=str) + "\n")


def _outside_repo(path: Path) -> bool:
    repo = Path(r"D:\us-tech-quant").resolve()
    try:
        path.resolve().relative_to(repo)
    except ValueError:
        return True
    return False


def detect_schema(legacy_panel_path: Path, horizon: int) -> dict[str, str]:
    """Return an unambiguous mapping; fail rather than guessing a date column."""
    columns = list(pd.read_csv(legacy_panel_path, nrows=0).columns)
    ticker_matches = [column for column in columns if column.lower() == "ticker"]
    date_matches = [column for column in columns if column.lower() in DATE_CANDIDATES]
    forward_candidates = (f"forward_return_{horizon}d", f"forward_{horizon}d")
    forward_matches = [column for column in columns if column.lower() in forward_candidates]
    if len(ticker_matches) != 1 or len(date_matches) != 1 or len(forward_matches) != 1:
        raise ValueError(
            "FAIL_LEGACY_FORWARD_SCHEMA_AMBIGUOUS: expected exactly one ticker, "
            "one recognized date, and one requested forward column"
        )
    return {"ticker": ticker_matches[0], "date": date_matches[0], "forward": forward_matches[0]}


class TickerQfqCache:
    """A bounded LRU cache; no attempt is made to retain every ticker in memory."""

    def __init__(self, stock_data_root: Path, capacity: int = 32) -> None:
        self.stock_data_root = stock_data_root
        self.capacity = capacity
        self._items: OrderedDict[str, tuple[pd.DataFrame | None, str, str]] = OrderedDict()

    def get(self, ticker: str) -> tuple[pd.DataFrame | None, str, str]:
        ticker = str(ticker)
        if ticker in self._items:
            self._items.move_to_end(ticker)
            return self._items[ticker]
        path = self.stock_data_root / ticker / "daily_qfq.parquet"
        if not path.exists():
            item = (None, "MISSING_TICKER_DATA", str(path))
        else:
            try:
                frame = pd.read_parquet(path)
                if not {"date", "close"}.issubset(frame.columns):
                    item = (None, "COMPARISON_ERROR", str(path))
                else:
                    frame = frame[["date", "close"]].copy()
                    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
                    if frame["date"].isna().any() or frame["date"].duplicated().any():
                        item = (None, "DUPLICATE_QFQ_DATE", str(path))
                    else:
                        frame = frame.sort_values("date", kind="stable").reset_index(drop=True)
                        frame["close"] = pd.to_numeric(frame["close"], errors="coerce").astype("float64")
                        item = (frame, "OK", str(path))
            except Exception:
                item = (None, "COMPARISON_ERROR", str(path))
        self._items[ticker] = item
        if len(self._items) > self.capacity:
            self._items.popitem(last=False)
        return item


def _file_identity(path: Path, horizon: int, chunk_size: int) -> dict[str, Any]:
    details = path.stat()
    return {
        "schema_version": SCHEMA_VERSION,
        "legacy_panel_path": str(path.resolve()),
        "legacy_panel_size": details.st_size,
        "legacy_panel_last_write_time": details.st_mtime_ns,
        "horizon": horizon,
        "chunk_size": chunk_size,
    }


def _validate_resume(checkpoint: dict[str, Any], expected: dict[str, Any]) -> None:
    changed = [name for name, value in expected.items() if checkpoint.get(name) != value]
    if changed:
        raise ValueError(f"FAIL_LEGACY_FORWARD_RESUME_MISMATCH: {', '.join(changed)}")


def _open_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=90)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=90000")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS legacy_keys ("
        "ticker TEXT NOT NULL, research_date TEXT NOT NULL, value REAL NOT NULL, "
        "duplicate_count INTEGER NOT NULL DEFAULT 1, conflict INTEGER NOT NULL DEFAULT 0, "
        "PRIMARY KEY(ticker, research_date))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS invalid_rows ("
        "ticker TEXT, research_date TEXT, reason TEXT NOT NULL)"
    )
    connection.commit()
    return connection


def _invalid_reason(value: Any) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return "EMPTY_STRING"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "PARSE_FAILURE"
    if numeric == float("inf"):
        return "POSITIVE_INFINITY"
    if numeric == float("-inf"):
        return "NEGATIVE_INFINITY"
    return "NONFINITE_OTHER"


def _ingest_chunk(connection: sqlite3.Connection, frame: pd.DataFrame, mapping: dict[str, str]) -> tuple[int, int, int]:
    work = frame[[mapping["ticker"], mapping["date"], mapping["forward"]]].copy()
    work.columns = ["ticker", "research_date", "legacy_value"]
    work["ticker"] = work["ticker"].astype(str).str.strip()
    work["research_date"] = pd.to_datetime(work["research_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    raw_values = work["legacy_value"].copy()
    source_nonnull = int(raw_values.notna().sum())
    work["legacy_value"] = pd.to_numeric(raw_values, errors="coerce")
    valid_mask = work["legacy_value"].notna() & np.isfinite(work["legacy_value"])
    invalid = work[~valid_mask]
    for row, raw_value in zip(invalid.itertuples(index=False), raw_values.loc[invalid.index]):
        connection.execute(
            "INSERT INTO invalid_rows(ticker,research_date,reason) VALUES(?,?,?)",
            (str(row.ticker), row.research_date if isinstance(row.research_date, str) else None, _invalid_reason(raw_value)),
        )
    nonnull = work[valid_mask].copy()
    invalid_count = int(len(invalid))
    for row in nonnull.itertuples(index=False):
        if not row.ticker or not isinstance(row.research_date, str):
            invalid_count += 1
            continue
        previous = connection.execute(
            "SELECT value, duplicate_count, conflict FROM legacy_keys WHERE ticker=? AND research_date=?",
            (row.ticker, row.research_date),
        ).fetchone()
        if previous is None:
            connection.execute(
                "INSERT INTO legacy_keys(ticker,research_date,value) VALUES(?,?,?)",
                (row.ticker, row.research_date, float(row.legacy_value)),
            )
        else:
            same = bool(np.isclose(float(previous[0]), float(row.legacy_value), rtol=1e-13, atol=1e-15))
            connection.execute(
                "UPDATE legacy_keys SET duplicate_count=?, conflict=? WHERE ticker=? AND research_date=?",
                (int(previous[1]) + 1, int(previous[2]) or int(not same), row.ticker, row.research_date),
            )
    connection.commit()
    return len(work), source_nonnull, invalid_count


def _empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype="object") for column in columns})


def run_compare(arguments: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-panel-path", type=Path, required=True)
    parser.add_argument("--stock-data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--horizon", type=int, required=True, choices=sorted(ALLOWED_HORIZONS))
    parser.add_argument("--chunk-size", type=int, default=200000)
    parser.add_argument("--checkpoint-path", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-difference-rows", type=int, default=100000)
    parser.add_argument("--absolute-tolerance", type=float, default=1e-12)
    parser.add_argument("--relative-tolerance", type=float, default=1e-10)
    args = parser.parse_args(arguments)
    if args.chunk_size <= 0 or args.max_difference_rows < 0:
        raise ValueError("chunk-size must be positive and max-difference-rows non-negative")
    if not args.legacy_panel_path.exists():
        raise FileNotFoundError(args.legacy_panel_path)
    if not _outside_repo(args.output_dir):
        raise ValueError("FAIL_STORAGE_CONTRACT_VIOLATION: output-dir must be outside repo")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = (args.checkpoint_path or output_dir / "checkpoint.json").resolve()
    journal_path = output_dir / "execution_journal.jsonl"
    log_path = output_dir / "execution_log.txt"
    database_path = output_dir / "legacy_keys.sqlite"
    identity = _file_identity(args.legacy_panel_path, args.horizon, args.chunk_size)
    checkpoint: dict[str, Any] = dict(identity)
    start_chunk = 0
    if args.resume:
        if not checkpoint_path.exists():
            raise ValueError("FAIL_LEGACY_FORWARD_RESUME_MISSING_CHECKPOINT")
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        _validate_resume(checkpoint, identity)
        if checkpoint.get("completed"):
            return json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
        start_chunk = int(checkpoint.get("next_chunk_index", 0))
    elif checkpoint_path.exists() or database_path.exists():
        raise ValueError("existing checkpoint/state found; pass --resume or choose a new output-dir")

    mapping = detect_schema(args.legacy_panel_path, args.horizon)
    _atomic_json(output_dir / "schema_mapping.json", mapping)
    started = time.monotonic()
    connection = _open_database(database_path)
    _append_journal(journal_path, {"event": "scan_started", "resume": args.resume, "start_chunk": start_chunk})
    log_path.write_text("legacy forward overlap scan started\n", encoding="utf-8")
    raw_rows = int(checkpoint.get("legacy_rows_scanned", 0))
    nonnull_rows = int(checkpoint.get("legacy_nonnull_row_count", 0))
    invalid_rows = int(checkpoint.get("invalid_legacy_value_count", 0))
    try:
        reader = pd.read_csv(
            args.legacy_panel_path, usecols=list(mapping.values()), chunksize=args.chunk_size,
            dtype={mapping["forward"]: "string"}, keep_default_na=False,
        )
        for chunk_index, chunk in enumerate(reader):
            if chunk_index < start_chunk:
                continue
            rows, nonnull, invalid = _ingest_chunk(connection, chunk, mapping)
            raw_rows += rows
            nonnull_rows += nonnull
            invalid_rows += invalid
            checkpoint.update(identity)
            checkpoint.update({
                "next_chunk_index": chunk_index + 1,
                "legacy_rows_scanned": raw_rows,
                "legacy_nonnull_row_count": nonnull_rows,
                "invalid_legacy_value_count": invalid_rows,
                "completed": False,
                "updated_at": _utc_now(),
            })
            _atomic_json(checkpoint_path, checkpoint)
            _append_journal(journal_path, {"event": "chunk_completed", "chunk_index": chunk_index, "rows": rows})
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"chunk {chunk_index} completed rows={rows}\n")

        cache = TickerQfqCache(args.stock_data_root)
        classifications: defaultdict[str, int] = defaultdict(int)
        ticker_counts: defaultdict[str, defaultdict[str, int]] = defaultdict(lambda: defaultdict(int))
        differences: list[dict[str, Any]] = []
        absolute_differences: list[float] = []
        comparable_count = 0
        unique_key_count = int(connection.execute("SELECT COUNT(*) FROM legacy_keys").fetchone()[0])
        invalid_reason_counts = dict(connection.execute("SELECT reason,COUNT(*) FROM invalid_rows GROUP BY reason"))
        invalid_unique_key_count = int(connection.execute(
            "SELECT COUNT(DISTINCT COALESCE(ticker,'') || '|' || COALESCE(research_date,'')) FROM invalid_rows"
        ).fetchone()[0])
        classifications["INVALID_LEGACY_VALUE"] += invalid_rows
        identical_duplicate_key_count = 0
        identical_duplicate_extra_row_count = 0
        conflicting_duplicate_key_count = 0
        duplicate_samples: list[dict[str, Any]] = []
        for ticker, research_date, legacy_value, duplicate_count, conflict in connection.execute(
            "SELECT ticker,research_date,value,duplicate_count,conflict FROM legacy_keys ORDER BY ticker,research_date"
        ):
            ticker = str(ticker)
            if conflict:
                classification = "DUPLICATE_LEGACY_KEY_CONFLICT"
                conflicting_duplicate_key_count += 1
                detail = {"ticker": ticker, "research_date": research_date, "classification": classification,
                          "duplicate_count": duplicate_count, "legacy_value": legacy_value}
            else:
                duplicate_class = "NONE"
                if duplicate_count > 1:
                    duplicate_class = "DUPLICATE_LEGACY_KEY_IDENTICAL"
                    identical_duplicate_key_count += 1
                    identical_duplicate_extra_row_count += int(duplicate_count) - 1
                    if len(duplicate_samples) < 1000:
                        duplicate_samples.append({"ticker": ticker, "research_date": research_date,
                                                  "duplicate_class": duplicate_class,
                                                  "duplicate_count": int(duplicate_count),
                                                  "canonical_legacy_value": float(legacy_value)})
                frame, status, source_path = cache.get(ticker)
                if status != "OK":
                    classification = status
                    detail = {"ticker": ticker, "research_date": research_date, "classification": classification,
                              "legacy_value": legacy_value, "source_path": source_path}
                else:
                    matched = frame.index[frame["date"] == research_date]
                    if len(matched) == 0:
                        classification = "MISSING_EXACT_DATE"
                        detail = {"ticker": ticker, "research_date": research_date, "classification": classification,
                                  "legacy_value": legacy_value, "source_path": source_path}
                    else:
                        position = int(matched[0])
                        if position + args.horizon >= len(frame):
                            classification = "IMMATURE_COMPACT_FORWARD"
                            detail = {"ticker": ticker, "research_date": research_date, "classification": classification,
                                      "legacy_value": legacy_value, "source_path": source_path}
                        else:
                            close = float(frame.loc[position, "close"])
                            future_close = float(frame.loc[position + args.horizon, "close"])
                            compact_value = np.float64(future_close / close - 1.0)
                            if not np.isfinite(compact_value):
                                classification = "IMMATURE_COMPACT_FORWARD"
                                detail = {"ticker": ticker, "research_date": research_date, "classification": classification,
                                          "duplicate_class": duplicate_class, "duplicate_count": int(duplicate_count),
                                          "legacy_value": legacy_value, "source_path": source_path}
                            else:
                                classification = "COMPARABLE"
                                comparable_count += 1
                                abs_diff = abs(float(legacy_value) - float(compact_value))
                                rel_diff = abs_diff / max(abs(float(legacy_value)), abs(float(compact_value)), 1e-300)
                                within = bool(abs_diff <= args.absolute_tolerance + args.relative_tolerance * max(abs(float(legacy_value)), abs(float(compact_value))))
                                absolute_differences.append(abs_diff)
                                detail = {"ticker": ticker, "research_date": research_date, "classification": classification,
                                          "legacy_value": float(legacy_value), "compact_value": float(compact_value),
                                          "absolute_difference": abs_diff, "relative_difference": rel_diff,
                                          "within_tolerance": within, "source_path": source_path}
                                if not within:
                                    detail["classification"] = "FINITE_MISMATCH"
                                    classification = "FINITE_MISMATCH"
            classifications[classification] += 1
            ticker_counts[ticker][classification] += 1
            if classification in {"FINITE_MISMATCH", "NAN_MISMATCH", "DUPLICATE_LEGACY_KEY_CONFLICT", "DUPLICATE_QFQ_DATE", "COMPARISON_ERROR"} or not detail.get("within_tolerance", True):
                if len(differences) < args.max_difference_rows:
                    differences.append(detail)
        connection.close()

        finite_mismatch = int(classifications["FINITE_MISMATCH"])
        excluded = sum(value for name, value in classifications.items() if name not in {"COMPARABLE", "FINITE_MISMATCH", "INVALID_LEGACY_VALUE"})
        values = np.asarray(absolute_differences, dtype="float64")
        summary = {
            **identity,
            "scan_started": True, "scan_completed": True, "resume_supported": True, "horizon": args.horizon,
            "legacy_rows_scanned": raw_rows, "legacy_nonnull_row_count": nonnull_rows,
            "unique_legacy_key_count": unique_key_count,
            "identical_duplicate_key_count": identical_duplicate_key_count,
            "identical_duplicate_extra_row_count": identical_duplicate_extra_row_count,
            "conflicting_duplicate_key_count": conflicting_duplicate_key_count,
            "canonical_unique_key_count": unique_key_count - conflicting_duplicate_key_count,
            "comparable_key_count": comparable_count,
            "comparable_row_count": comparable_count, "excluded_row_count": excluded,
            "excluded_unique_key_count": excluded,
            "invalid_legacy_row_count": invalid_rows,
            "invalid_legacy_unique_key_count": invalid_unique_key_count,
            "invalid_legacy_reason_counts": invalid_reason_counts,
            "missing_ticker_count": int(classifications["MISSING_TICKER_DATA"]),
            "missing_exact_date_count": int(classifications["MISSING_EXACT_DATE"]),
            "immature_compact_forward_count": int(classifications["IMMATURE_COMPACT_FORWARD"]),
            "finite_mismatch_count": finite_mismatch, "nan_mismatch_count": 0,
            "max_abs_diff": float(values.max()) if len(values) else 0.0,
            "max_rel_diff": max((float(row.get("relative_difference", 0.0)) for row in differences if "relative_difference" in row), default=0.0),
            "mean_abs_diff": float(values.mean()) if len(values) else 0.0,
            "p95_abs_diff": float(np.quantile(values, .95)) if len(values) else 0.0,
            "p99_abs_diff": float(np.quantile(values, .99)) if len(values) else 0.0,
            "strict_equivalence_pass": bool(comparable_count > 0 and finite_mismatch == 0),
            "elapsed_seconds": time.monotonic() - started,
        }
        parquet_summary = dict(summary)
        parquet_summary["invalid_legacy_reason_counts"] = json.dumps(invalid_reason_counts, sort_keys=True)
        pd.DataFrame([parquet_summary]).to_parquet(output_dir / f"horizon_{args.horizon}_equivalence.parquet", index=False)
        pd.DataFrame([{"classification": key, "row_count": value} for key, value in sorted(classifications.items())]).to_parquet(
            output_dir / f"horizon_{args.horizon}_exclusion_summary.parquet", index=False)
        pd.DataFrame(differences).to_parquet(output_dir / f"horizon_{args.horizon}_difference_rows.parquet", index=False)
        pd.DataFrame(duplicate_samples).to_parquet(output_dir / f"horizon_{args.horizon}_duplicate_summary.parquet", index=False)
        pd.DataFrame([{"ticker": ticker, **counts} for ticker, counts in sorted(ticker_counts.items())]).to_parquet(
            output_dir / f"horizon_{args.horizon}_ticker_summary.parquet", index=False)
        _atomic_json(output_dir / "serialization_precision_analysis.json", {
            "status": "STRICT_RESULTS_ONLY", "automatic_tolerance_relaxation": False,
            "absolute_tolerance": args.absolute_tolerance, "relative_tolerance": args.relative_tolerance,
        })
        checkpoint.update(summary)
        checkpoint.update({"next_chunk_index": checkpoint.get("next_chunk_index", 0), "completed": True, "updated_at": _utc_now()})
        _atomic_json(checkpoint_path, checkpoint)
        _atomic_json(output_dir / "summary.json", summary)
        _append_journal(journal_path, {"event": "scan_completed", "comparable": comparable_count, "mismatches": finite_mismatch})
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write("scan completed\n")
        return summary
    finally:
        try:
            connection.close()
        except Exception:
            pass


def main(arguments: list[str] | None = None) -> int:
    run_compare(arguments)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
