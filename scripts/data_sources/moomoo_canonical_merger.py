"""Quality-gated Moomoo staging to canonical OHLCV merger."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESEARCH_CANONICAL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
DEFAULT_TRADE_PLAN_CANONICAL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV_RAW_TRADE_PLAN.csv"
OHLCV = ["open", "high", "low", "close", "volume"]


def normalize_for_canonical(frame: pd.DataFrame, adjusted_close_from_close: bool = True) -> pd.DataFrame:
    out = frame.copy()
    if "internal_symbol" in out and "symbol" not in out:
        out["symbol"] = out["internal_symbol"]
    out["symbol"] = out["symbol"].astype(str).str.upper().str.strip()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in OHLCV:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    if "adjusted_close" not in out:
        out["adjusted_close"] = out["close"] if adjusted_close_from_close else pd.NA
    out["source_provider"] = "MOOMOO"
    out["source_artifact"] = "data/moomoo/staging"
    out["refresh_timestamp"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    out["price_row_status"] = out.get("price_row_status", "MOOMOO_PROVIDER_OBSERVED_OHLCV")
    fields = ["symbol", "date", "open", "high", "low", "close", "adjusted_close", "volume", "source_provider", "source_artifact", "refresh_timestamp", "price_row_status"]
    for field in fields:
        if field not in out:
            out[field] = ""
    return out[fields].dropna(subset=["symbol", "date"])


def broad_date_coverage(frame: pd.DataFrame, eligible_symbols: Iterable[str], min_ratio: float = 0.95) -> pd.DataFrame:
    eligible = {str(s).upper().strip() for s in eligible_symbols if str(s).strip()}
    rows = []
    if frame.empty:
        return pd.DataFrame(columns=["date", "distinct_symbol_count", "eligible_symbol_count", "coverage_ratio", "broad_price_date_eligible"])
    for date, group in frame.groupby("date", sort=True):
        symbols = set(group["symbol"].astype(str).str.upper())
        ratio = len(symbols & eligible) / len(eligible) if eligible else 0.0
        rows.append({
            "date": date,
            "distinct_symbol_count": len(symbols),
            "eligible_symbol_count": len(eligible),
            "coverage_ratio": ratio,
            "broad_price_date_eligible": ratio >= min_ratio,
        })
    return pd.DataFrame(rows)


def latest_broad_honest_date(frame: pd.DataFrame, eligible_symbols: Iterable[str], min_ratio: float = 0.95) -> tuple[str, pd.DataFrame]:
    coverage = broad_date_coverage(frame, eligible_symbols, min_ratio=min_ratio)
    dates = coverage.loc[coverage["broad_price_date_eligible"].astype(bool), "date"].astype(str).tolist() if not coverage.empty else []
    return (max(dates) if dates else "", coverage)


def quality_gate(
    staging: pd.DataFrame,
    eligible_symbols: Iterable[str],
    min_coverage_ratio: float = 0.95,
    priority_symbol: str = "DRAM",
) -> tuple[bool, dict[str, Any], pd.DataFrame]:
    frame = normalize_for_canonical(staging)
    raw_max_date = str(frame["date"].max()) if not frame.empty else ""
    broad_latest, coverage = latest_broad_honest_date(frame, eligible_symbols, min_ratio=min_coverage_ratio)
    duplicate_count = int(frame.duplicated(["symbol", "date"]).sum()) if not frame.empty else 0
    sane = pd.Series(dtype=bool)
    if not frame.empty:
        sane = (
            (frame["high"] >= frame[["open", "close"]].max(axis=1))
            & (frame["low"] <= frame[["open", "close"]].min(axis=1))
            & (frame["volume"] >= 0)
        )
    sanity_failures = int((~sane).sum()) if len(sane) else 0
    required_ok = pd.Series(dtype=bool)
    if not frame.empty:
        required_ok = frame[OHLCV].notna().all(axis=1) & (frame["volume"] >= 0)
    required_failures = int((~required_ok).sum()) if len(required_ok) else 0
    dram = frame[frame["symbol"].eq(priority_symbol.upper())]
    dram_latest = str(dram["date"].max()) if not dram.empty else ""
    symbol_latest = frame.groupby("symbol")["date"].max().reset_index(name="latest_date") if not frame.empty else pd.DataFrame(columns=["symbol", "latest_date"])
    stale_count = int((symbol_latest["latest_date"].astype(str) < broad_latest).sum()) if broad_latest and not symbol_latest.empty else 0
    pass_gate = (
        bool(broad_latest)
        and duplicate_count == 0
        and required_failures == 0
        and stale_count == 0
        and dram_latest == broad_latest
        and broad_latest == raw_max_date
    )
    summary = {
        "gate_passed": pass_gate,
        "raw_max_date": raw_max_date,
        "latest_moomoo_broad_honest_date": broad_latest,
        "duplicate_symbol_date_rows": duplicate_count,
        "ohlc_sanity_failure_rows": sanity_failures,
        "ohlcv_required_field_failure_rows": required_failures,
        "date_completeness_stale_symbol_count": stale_count,
        "dram_latest_date": dram_latest,
        "dram_present_and_current": dram_latest == broad_latest and bool(broad_latest),
        "raw_max_date_later_than_broad_honest_latest_date": raw_max_date > broad_latest if raw_max_date and broad_latest else False,
        "minimum_broad_coverage_ratio": min_coverage_ratio,
    }
    return pass_gate, summary, coverage


def merge_canonical(
    research_staging: pd.DataFrame,
    trade_plan_staging: pd.DataFrame,
    eligible_symbols: Iterable[str],
    research_canonical_path: Path = DEFAULT_RESEARCH_CANONICAL,
    trade_plan_canonical_path: Path = DEFAULT_TRADE_PLAN_CANONICAL,
    backup_dir: Path | None = None,
    min_coverage_ratio: float = 0.95,
    apply: bool = True,
) -> dict[str, Any]:
    backup_dir = backup_dir or ROOT / "data/moomoo/audit/canonical_backups"
    passed, gate_summary, coverage = quality_gate(research_staging, eligible_symbols, min_coverage_ratio=min_coverage_ratio)
    result = {
        **gate_summary,
        "canonical_updated": False,
        "research_canonical_path": str(research_canonical_path),
        "trade_plan_canonical_path": str(trade_plan_canonical_path),
        "research_backup_path": "",
        "trade_plan_backup_path": "",
        "final_status": "FAIL_MOOMOO_CANONICAL_GATE_FAILED",
    }
    if not passed or not apply:
        return result
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir.mkdir(parents=True, exist_ok=True)
    if research_canonical_path.exists():
        research_backup = backup_dir / f"{research_canonical_path.stem}_before_moomoo_{timestamp}.csv"
        shutil.copy2(research_canonical_path, research_backup)
        result["research_backup_path"] = str(research_backup)
        base = pd.read_csv(research_canonical_path, low_memory=False)
    else:
        base = pd.DataFrame()
    candidate = pd.concat([base, normalize_for_canonical(research_staging)], ignore_index=True)
    candidate["symbol"] = candidate["symbol"].astype(str).str.upper().str.strip()
    candidate["date"] = pd.to_datetime(candidate["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    candidate = candidate.drop_duplicates(["symbol", "date"], keep="last").sort_values(["symbol", "date"])
    candidate.to_csv(research_canonical_path, index=False)
    if trade_plan_canonical_path.exists():
        trade_backup = backup_dir / f"{trade_plan_canonical_path.stem}_before_moomoo_{timestamp}.csv"
        shutil.copy2(trade_plan_canonical_path, trade_backup)
        result["trade_plan_backup_path"] = str(trade_backup)
        trade_base = pd.read_csv(trade_plan_canonical_path, low_memory=False)
    else:
        trade_base = pd.DataFrame()
    trade_candidate = pd.concat([trade_base, normalize_for_canonical(trade_plan_staging, adjusted_close_from_close=False)], ignore_index=True)
    trade_candidate["symbol"] = trade_candidate["symbol"].astype(str).str.upper().str.strip()
    trade_candidate["date"] = pd.to_datetime(trade_candidate["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    trade_candidate = trade_candidate.drop_duplicates(["symbol", "date"], keep="last").sort_values(["symbol", "date"])
    trade_candidate.to_csv(trade_plan_canonical_path, index=False)
    result["canonical_updated"] = True
    result["canonical_latest_date_after"] = str(candidate["date"].max()) if not candidate.empty else ""
    result["final_status"] = "PASS_MOOMOO_CANONICAL_UPDATED"
    return result
