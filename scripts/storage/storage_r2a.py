"""R2A storage contract helpers; intentionally offline and broker-free."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ALLOWED_ROOTS = tuple(Path(p) for p in (
    r"D:\us-tech-quant", r"D:\us-tech-quant-data", r"D:\us-tech-quant-backtests",
    r"D:\us-tech-quant-daily", r"D:\us-tech-quant-cache", r"D:\us-tech-quant-archive",
    r"D:\us-tech-quant-quarantine"))
REPO_ROOT = ALLOWED_ROOTS[0]
DATA_ROOT = ALLOWED_ROOTS[1]
BACKTEST_ROOT = ALLOWED_ROOTS[2]
DAILY_ROOT = ALLOWED_ROOTS[3]
CACHE_ROOT = ALLOWED_ROOTS[4]
MAX_REPO_FILE_BYTES = 20 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def assert_allowed(path: Path) -> None:
    if not any(is_under(path, root) for root in ALLOWED_ROOTS):
        raise ValueError(f"FAIL_STORAGE_CONTRACT_VIOLATION: path outside allowed roots: {path}")


def assert_write_path(path: Path, purpose: str) -> None:
    assert_allowed(path)
    resolved = path.resolve()
    if is_under(resolved, REPO_ROOT):
        rel = resolved.relative_to(REPO_ROOT.resolve())
        if rel.parts and rel.parts[0].lower() in {"outputs", "exports"}:
            raise ValueError("FAIL_STORAGE_CONTRACT_VIOLATION: repo outputs/exports are prohibited")
        if path.suffix.lower() in {".csv", ".parquet", ".zip"}:
            raise ValueError("FAIL_STORAGE_CONTRACT_VIOLATION: large data format prohibited in repo")
    if purpose == "market_data" and not is_under(resolved, DATA_ROOT / "stocks"):
        raise ValueError("FAIL_STORAGE_CONTRACT_VIOLATION: market data must be under data_root/stocks")
    if purpose == "daily" and not is_under(resolved, DAILY_ROOT):
        raise ValueError("FAIL_STORAGE_CONTRACT_VIOLATION: daily output must be under daily_root")
    if purpose == "backtest" and not is_under(resolved, BACKTEST_ROOT):
        raise ValueError("FAIL_STORAGE_CONTRACT_VIOLATION: backtest output must be under backtest_root")
    if purpose == "derived" and not (is_under(resolved, CACHE_ROOT / "derived") or is_under(resolved, BACKTEST_ROOT)):
        raise ValueError("FAIL_STORAGE_CONTRACT_VIOLATION: derived output must be cache/derived or a backtest run")


def assert_safety_flags(payload: dict) -> None:
    if payload.get("broker_action_allowed", False) is not False or payload.get("official_adoption_allowed", False) is not False or payload.get("research_only", True) is not True:
        raise ValueError("FAIL_STORAGE_CONTRACT_VIOLATION: research safety flags changed")


def write_json_atomic(path: Path, payload: dict) -> None:
    assert_write_path(path, "state" if is_under(path, REPO_ROOT / "state") else "backtest")
    assert_safety_flags(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def storage_guard_result(path: Path, purpose: str, run_id: str = "") -> dict:
    try:
        if purpose == "backtest" and not run_id:
            raise ValueError("FAIL_STORAGE_CONTRACT_VIOLATION: backtest run_id is required")
        assert_write_path(path, purpose)
        if is_under(path, REPO_ROOT) and path.exists() and path.stat().st_size > MAX_REPO_FILE_BYTES:
            raise ValueError("FAIL_STORAGE_CONTRACT_VIOLATION: repo file exceeds 20 MB")
        return {"path": str(path), "purpose": purpose, "run_id": run_id, "result": "PASS"}
    except Exception as exc:
        return {"path": str(path), "purpose": purpose, "run_id": run_id, "result": "FAIL", "reason": str(exc)}


def load_ticker_daily(ticker: str, adjustment: str, start_date: str | None = None, end_date: str | None = None):
    import pandas as pd
    name = "daily_qfq.parquet" if adjustment.lower() == "qfq" else "daily_raw.parquet"
    path = DATA_ROOT / "stocks" / ticker.upper() / name
    assert_allowed(path)
    frame = pd.read_parquet(path)
    if start_date: frame = frame[frame["date"] >= start_date]
    if end_date: frame = frame[frame["date"] <= end_date]
    return frame.sort_values("date").reset_index(drop=True)


def load_ticker_intraday(ticker: str, timeframe: str, start_time: str | None = None, end_time: str | None = None):
    import pandas as pd
    folder = DATA_ROOT / "stocks" / ticker.upper() / "intraday" / timeframe
    assert_allowed(folder)
    files = sorted(folder.glob("*.parquet"))
    frame = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True) if files else pd.DataFrame()
    if not frame.empty and start_time: frame = frame[frame["datetime"] >= start_time]
    if not frame.empty and end_time: frame = frame[frame["datetime"] <= end_time]
    return frame.sort_values("datetime").reset_index(drop=True) if not frame.empty else frame


def scan_universe_daily(tickers: Iterable[str], adjustment: str, start_date: str | None = None, end_date: str | None = None):
    import pandas as pd
    frames = [load_ticker_daily(ticker, adjustment, start_date, end_date) for ticker in tickers]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
