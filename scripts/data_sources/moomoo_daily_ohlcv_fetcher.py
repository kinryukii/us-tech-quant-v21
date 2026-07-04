"""Fetch and normalize Moomoo daily historical K-line bars."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from scripts.data_sources.moomoo_client import MoomooQuoteClient


ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data/moomoo/raw"
STAGING_DIR = ROOT / "data/moomoo/staging"
AUDIT_DIR = ROOT / "data/moomoo/audit"
SCHEMA = [
    "source", "internal_symbol", "moomoo_code", "date", "time_key", "open", "high", "low", "close",
    "volume", "turnover", "last_close", "adjustment_mode", "fetch_timestamp_utc",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def autype_for_mode(module: Any, adjustment_mode: str) -> Any:
    mode = adjustment_mode.upper()
    if mode in {"QFQ", "RESEARCH"}:
        return getattr(module, "AuType", None).QFQ if hasattr(getattr(module, "AuType", None), "QFQ") else "qfq"
    if mode in {"RAW", "NONE", "TRADE_PLAN"}:
        return getattr(module, "AuType", None).NONE if hasattr(getattr(module, "AuType", None), "NONE") else "none"
    raise ValueError(f"Unsupported adjustment_mode={adjustment_mode}")


def ktype_daily(module: Any) -> Any:
    kltype = getattr(module, "KLType", None)
    return getattr(kltype, "K_DAY", "K_DAY") if kltype is not None else "K_DAY"


def _to_frame(payload: Any) -> pd.DataFrame:
    if isinstance(payload, pd.DataFrame):
        return payload.copy()
    if isinstance(payload, (list, tuple)):
        return pd.DataFrame(payload)
    return pd.DataFrame()


def normalize_kline_frame(frame: pd.DataFrame, internal_symbol: str, moomoo_code: str, adjustment_mode: str, fetched_at: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=SCHEMA)
    rename = {c: str(c).strip().lower() for c in frame.columns}
    out = frame.rename(columns=rename).copy()
    if "code" in out and "moomoo_code" not in out:
        out["moomoo_code"] = out["code"]
    if "time_key" not in out and "date" in out:
        out["time_key"] = out["date"]
    if "date" not in out:
        out["date"] = pd.to_datetime(out.get("time_key", ""), errors="coerce").dt.strftime("%Y-%m-%d")
    else:
        out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out["source"] = "MOOMOO"
    out["internal_symbol"] = str(internal_symbol).upper()
    out["moomoo_code"] = moomoo_code
    out["adjustment_mode"] = adjustment_mode.upper()
    out["fetch_timestamp_utc"] = fetched_at
    for col in ["open", "high", "low", "close", "volume", "turnover", "last_close"]:
        if col not in out:
            out[col] = pd.NA
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out[SCHEMA].dropna(subset=["date"]).sort_values(["internal_symbol", "date"]).reset_index(drop=True)


def fetch_history_daily(
    client: MoomooQuoteClient,
    internal_symbol: str,
    moomoo_code: str,
    start: str | None = None,
    end: str | None = None,
    adjustment_mode: str = "QFQ",
) -> pd.DataFrame:
    fetched_at = utc_now()
    rows: list[pd.DataFrame] = []
    page_req_key = None
    while True:
        kwargs = {
            "code": moomoo_code,
            "ktype": ktype_daily(client.module),
            "autype": autype_for_mode(client.module, adjustment_mode),
        }
        if start:
            kwargs["start"] = start
        if end:
            kwargs["end"] = end
        if page_req_key is not None:
            kwargs["page_req_key"] = page_req_key
        payload = client.checked_call("request_history_kline", **kwargs)
        next_key = None
        data = payload
        if isinstance(payload, tuple):
            data = payload[0]
            if len(payload) > 1:
                next_key = payload[1]
        frame = _to_frame(data)
        rows.append(frame)
        if not next_key:
            break
        page_req_key = next_key
    raw = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    return normalize_kline_frame(raw, internal_symbol, moomoo_code, adjustment_mode, fetched_at)


def fetch_many_daily(
    client: MoomooQuoteClient,
    mapping_audit: pd.DataFrame,
    start: str | None = None,
    end: str | None = None,
    adjustment_mode: str = "QFQ",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames = []
    audit_rows = []
    ok = mapping_audit[mapping_audit["mapping_status"].astype(str).str.upper().eq("PASS")]
    for _, row in ok.iterrows():
        sym = str(row["internal_symbol"])
        code = str(row["moomoo_code"])
        try:
            frame = fetch_history_daily(client, sym, code, start=start, end=end, adjustment_mode=adjustment_mode)
            frames.append(frame)
            status = "PASS" if not frame.empty else "WARN_EMPTY"
            err = ""
        except Exception as exc:
            status = "FAIL"
            err = str(exc)
        audit_rows.append({"internal_symbol": sym, "moomoo_code": code, "adjustment_mode": adjustment_mode.upper(), "fetch_status": status, "fetch_error": err})
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SCHEMA)
    return data, pd.DataFrame(audit_rows)


def write_fetch_outputs(frame: pd.DataFrame, audit: pd.DataFrame, label: str) -> dict[str, str]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"{label}.csv"
    staging_path = STAGING_DIR / f"{label}_normalized.csv"
    audit_path = AUDIT_DIR / f"{label}_audit.csv"
    frame.to_csv(raw_path, index=False)
    frame.to_csv(staging_path, index=False)
    audit.to_csv(audit_path, index=False)
    return {"raw_path": str(raw_path), "staging_path": str(staging_path), "audit_path": str(audit_path)}
