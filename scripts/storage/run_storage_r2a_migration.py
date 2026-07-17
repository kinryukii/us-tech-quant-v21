"""Offline R2A per-ticker conversion. Copies/converts only; never alters legacy files."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

from storage_r2a import BACKTEST_ROOT, CACHE_ROOT, DATA_ROOT, REPO_ROOT, sha256, storage_guard_result, utc_now

RAW_ROOT = CACHE_ROOT / "raw/moomoo/daily_raw"
QFQ_ROOT = CACHE_ROOT / "raw/moomoo/daily_qfq"
REQUIRED = ["ticker", "date", "open", "high", "low", "close", "volume"]


def read_source_index(root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = defaultdict(list)
    for path in root.glob("snapshot_id=*/*.csv"):
        index[path.stem.upper()].append(path)
    return index


def validate(frame: pd.DataFrame, ticker: str) -> tuple[bool, str]:
    if frame.empty or any(c not in frame.columns for c in REQUIRED): return False, "EMPTY_OR_SCHEMA"
    if set(frame["ticker"].astype(str).str.upper()) != {ticker}: return False, "TICKER_MISMATCH"
    if frame["date"].isna().any() or frame.duplicated(["ticker", "date"]).any(): return False, "DATE_INVALID_OR_DUPLICATE"
    numeric = frame[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or (numeric["close"] <= 0).any(): return False, "OHLCV_NULL_OR_NONPOSITIVE"
    if not ((numeric["high"] >= numeric[["open", "low", "close"]].max(axis=1)) & (numeric["low"] <= numeric[["open", "high", "close"]].min(axis=1))).all(): return False, "OHLC_INVALID"
    return True, ""


def convert_one(ticker: str, paths: list[Path], adjustment: str, report: list[dict], manifest: list[dict]) -> None:
    target_dir = DATA_ROOT / "stocks" / ticker
    target = target_dir / ("daily_qfq.parquet" if adjustment == "qfq" else "daily_raw.parquet")
    if target.exists():
        raise RuntimeError(f"refusing to overwrite existing R2A target: {target}")
    frames = []
    source_rows = 0
    for source in sorted(paths, key=lambda p: p.parent.name):
        frame = pd.read_csv(source, low_memory=False)
        source_rows += len(frame)
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        frames.append(frame)
        manifest.append({"operation":"COPY_CONVERT","source_path":str(source),"target_path":str(target),"source_sha256":sha256(source),"source_size_bytes":source.stat().st_size,"reason":"R2A_PER_TICKER_PERMANENT_MARKET_DATA","status":"SOURCE_RETAINED"})
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.drop_duplicates(["ticker", "date"], keep="last").sort_values("date").reset_index(drop=True)
    ok, reason = validate(merged, ticker)
    if not ok: raise RuntimeError(f"{ticker} {adjustment}: {reason}")
    target_dir.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".parquet.tmp")
    merged.to_parquet(tmp, index=False, engine="pyarrow", compression="zstd")
    check = pd.read_parquet(tmp)
    ok, reason = validate(check, ticker)
    if not ok or len(check) != len(merged): raise RuntimeError(f"{ticker} write validation: {reason}")
    tmp.replace(target)
    report.append({"ticker":ticker,"adjustment":adjustment,"source_file_count":len(paths),"source_row_count":source_rows,"output_row_count":len(check),"first_date":str(check.date.min()),"last_date":str(check.date.max()),"output_path":str(target),"sha256":sha256(target),"size_bytes":target.stat().st_size,"status":"PASS"})


def write_parquet(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False, engine="pyarrow", compression="zstd")


def main() -> int:
    run_id = f"STORAGE_R2A_{utc_now().replace(':','').replace('+00:00','Z').replace('-','')}"
    out = BACKTEST_ROOT / "_system_migrations" / run_id
    state = REPO_ROOT / "state/storage_migration_r2a"
    for p in [DATA_ROOT / "stocks", BACKTEST_ROOT, CACHE_ROOT / "derived", out, state]: p.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    report: list[dict] = []
    raw, qfq = read_source_index(RAW_ROOT), read_source_index(QFQ_ROOT)
    tickers = sorted(set(raw) & set(qfq))
    failures = []
    for index, ticker in enumerate(tickers, 1):
        try:
            convert_one(ticker, raw[ticker], "raw", report, manifest)
            convert_one(ticker, qfq[ticker], "qfq", report, manifest)
            metadata = DATA_ROOT / "stocks" / ticker / "metadata.json"
            metadata.write_text(json.dumps({"ticker":ticker,"source":"MOOMOO_OPEND","migration_run_id":run_id,"raw_path":"daily_raw.parquet","qfq_path":"daily_qfq.parquet","updated_utc":utc_now()}, indent=2)+"\n", encoding="utf-8")
        except Exception as exc:
            failures.append({"ticker":ticker,"error":str(exc)})
        if index % 100 == 0: print(f"converted={index}/{len(tickers)} failures={len(failures)}", flush=True)
    write_parquet(manifest, out / "migration_manifest.parquet")
    write_parquet(report, out / "ticker_conversion_report.parquet")
    validation = pd.DataFrame(report).assign(validation_status="PASS") if report else pd.DataFrame()
    validation.to_parquet(out / "ticker_validation_report.parquet", index=False, engine="pyarrow", compression="zstd")
    guard = {"repo_large_csv_blocked":storage_guard_result(REPO_ROOT / "outputs/v99/big.csv","derived"),"repo_outputs_blocked":storage_guard_result(REPO_ROOT / "outputs/v99/small.json","state"),"backtest_run_id_required":storage_guard_result(BACKTEST_ROOT / "x/summary.json","backtest"),"safety_flags":"broker_action_allowed=False; official_adoption_allowed=False; research_only=True"}
    (out / "storage_guard_test_results.json").write_text(json.dumps(guard,indent=2)+"\n",encoding="utf-8")
    summary = {"status":"PASS_STORAGE_R2A_PER_TICKER_AND_ISOLATED_RUNS_READY" if not failures else "FAIL_STORAGE_R2A_CONVERSION_INCOMPLETE","run_id":run_id,"tickers_common":len(tickers),"converted_files":len(report),"failures":failures,"network_called":False,"broker_called":False,"broker_action_allowed":False,"official_adoption_allowed":False,"research_only":True,"legacy_files_modified":False,"legacy_files_moved":False,"created_utc":utc_now()}
    for name, payload in [("summary.json",summary),("projected_repo_size.json",{"legacy_repo_cleanup_requires_R2B":True}),("projected_data_size.json",{"per_ticker_files":len(report)}),("projected_quarantine_size.json",{"bytes":0,"reason":"R2A_NO_MOVE_OR_DELETE"})]: (out / name).write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
    write_parquet([
        {"legacy_path":"outputs/v21/V21.246_TECHNICAL_AND_FORWARD_PANEL_BUILD_FROM_MOOMOO_CACHE_R1","classification":"REPRODUCIBLE_DERIVED_DATA","referenced_by":"v22 ABCDE and V21.247-V21.250","r2a_target":"cache/derived or isolated backtest derived","switch_required":True},
        {"legacy_path":"cache/canonical/moomoo_ohlcv","classification":"CANONICAL_RESEARCH_DATA","referenced_by":"V22.040/V21.231","r2a_target":"data/stocks/<ticker>","switch_required":True},
        {"legacy_path":"outputs/v22","classification":"DAILY_RUN_ARTIFACT","referenced_by":"V22.044/V22.047","r2a_target":"daily/<research_date>","switch_required":True},
    ], out / "path_dependency_report.parquet")
    write_parquet([{**row, "rollback_action":"NONE_R2A_COPY_ONLY", "rollback_source_path":row["source_path"], "rollback_target_path":row["target_path"]} for row in manifest], out / "rollback_manifest.parquet")
    state.joinpath("latest_migration_pointer.json").write_text(json.dumps({"run_id":run_id,"summary_path":str(out / 'summary.json'),"status":summary["status"]},indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary))
    return 0 if not failures else 2

if __name__ == "__main__": raise SystemExit(main())
