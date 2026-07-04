#!/usr/bin/env python
"""V21.199 R2 Moomoo full-universe fetch and completed-date gate."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.data_sources.moomoo_canonical_merger import (
    DEFAULT_RESEARCH_CANONICAL,
    DEFAULT_TRADE_PLAN_CANONICAL,
    broad_date_coverage,
    merge_canonical,
    normalize_for_canonical,
    quality_gate,
)
from scripts.data_sources.moomoo_client import MoomooQuoteClient
from scripts.data_sources.moomoo_daily_ohlcv_fetcher import fetch_many_daily, write_fetch_outputs
from scripts.data_sources.moomoo_market_state_gate import market_state_gate
from scripts.data_sources.moomoo_quota_auditor import audit_quota
from scripts.data_sources.moomoo_symbol_mapper import map_symbols


STAGE = "V21.199_R2_MOOMOO_FULL_UNIVERSE_FETCH_AND_COMPLETED_DATE_GATE"
OUT = ROOT / "outputs/v21/V21.199_R2_MOOMOO_FULL_UNIVERSE_FETCH_AND_COMPLETED_DATE_GATE"
MIN_COVERAGE_RATIO = 0.95
PRIORITY_SYMBOLS = ["DRAM", "QQQ", "AAPL"]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def latest_date(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        frame = pd.read_csv(path, usecols=["date"], low_memory=False)
    except Exception:
        return ""
    return str(pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d").max()) if not frame.empty else ""


def canonical_symbols(path: Path = DEFAULT_RESEARCH_CANONICAL) -> list[str]:
    if not path.exists():
        return ["AAPL", "QQQ"]
    frame = pd.read_csv(path, usecols=lambda c: str(c).lower() in {"symbol", "ticker"}, low_memory=False)
    col = "symbol" if "symbol" in frame.columns else "ticker"
    return sorted(frame[col].dropna().astype(str).str.upper().str.strip().unique())


def build_fetch_universe(eligible_symbols: Iterable[str], priority_symbols: Iterable[str] = PRIORITY_SYMBOLS, explicit_symbol_cap: int | None = None) -> list[str]:
    """Return eligible universe union priority symbols.

    Production calls must leave explicit_symbol_cap unset. Tests may pass a cap
    directly; the environment cap is intentionally opt-in and named as test-only.
    """
    priority_set = {str(s).upper().strip() for s in priority_symbols}
    ordered: list[str] = []
    seen: set[str] = set()
    base_symbols = list(eligible_symbols)
    if explicit_symbol_cap is not None:
        base_symbols = base_symbols[: max(0, int(explicit_symbol_cap))]
    for symbol in base_symbols + list(priority_symbols):
        sym = str(symbol).upper().strip()
        if sym and sym not in seen:
            seen.add(sym)
            ordered.append(sym)
    return ordered


def optional_test_symbol_cap() -> int | None:
    raw = os.environ.get("V21_199_R2_TEST_SYMBOL_CAP", "").strip()
    if not raw:
        return None
    return max(0, int(raw))


def regular_session_open(market: pd.DataFrame) -> bool:
    if market.empty or "decision" not in market:
        return False
    return market["decision"].astype(str).str.upper().str.contains("BLOCK_REGULAR_SESSION_OPEN").any()


def current_us_exchange_date() -> str:
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def completed_research_frame(
    staging: pd.DataFrame,
    market_open: bool,
    current_exchange_date: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    exchange_date = str(current_exchange_date or current_us_exchange_date())
    if staging.empty:
        empty = pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "adjusted_close", "volume"])
        return empty, {
            "latest_raw_max_date": "",
            "latest_completed_candidate_date": "",
            "open_session_excluded_dates": [],
            "regular_session_open": bool(market_open),
            "current_exchange_date": exchange_date,
        }
    frame = normalize_for_canonical(staging)
    raw_max = str(frame["date"].max()) if not frame.empty else ""
    excluded_dates: list[str] = []
    completed = frame.copy()
    if market_open and raw_max == exchange_date:
        excluded_dates = [raw_max]
        completed = completed[completed["date"].astype(str) < raw_max].copy()
    latest_completed = str(completed["date"].max()) if not completed.empty else ""
    return completed, {
        "latest_raw_max_date": raw_max,
        "latest_completed_candidate_date": latest_completed,
        "open_session_excluded_dates": excluded_dates,
        "regular_session_open": bool(market_open),
        "current_exchange_date": exchange_date,
    }


def priority_symbol_audit(mapping: pd.DataFrame, research: pd.DataFrame, completed: pd.DataFrame, priority_symbols: Iterable[str] = PRIORITY_SYMBOLS) -> pd.DataFrame:
    rows = []
    for sym in priority_symbols:
        symbol = str(sym).upper()
        mapped = mapping[mapping["internal_symbol"].astype(str).str.upper().eq(symbol)]
        staging = research[research.get("internal_symbol", pd.Series(dtype=str)).astype(str).str.upper().eq(symbol)] if not research.empty else pd.DataFrame()
        completed_rows = completed[completed["symbol"].astype(str).str.upper().eq(symbol)] if not completed.empty and "symbol" in completed else pd.DataFrame()
        rows.append({
            "priority_symbol": symbol,
            "requested": True,
            "mapped": (not mapped.empty and str(mapped.iloc[0].get("mapping_status", "")).upper() == "PASS"),
            "moomoo_code": "" if mapped.empty else str(mapped.iloc[0].get("moomoo_code", "")),
            "fetched": not staging.empty,
            "row_count": int(len(staging)),
            "latest_raw_date": str(staging["date"].max()) if not staging.empty else "",
            "latest_completed_date": str(completed_rows["date"].max()) if not completed_rows.empty else "",
            "fetch_status": "PASS" if not staging.empty else "FAIL_MISSING_STAGING_ROWS",
        })
    return pd.DataFrame(rows)


def fetch_universe_audit(
    eligible_symbols: list[str],
    mapping: pd.DataFrame,
    fetch_symbols: list[str],
    research: pd.DataFrame,
    completed: pd.DataFrame,
    priority: pd.DataFrame,
) -> dict[str, Any]:
    latest_completed = str(completed["date"].max()) if not completed.empty else ""
    latest_group = completed[completed["date"].astype(str).eq(latest_completed)] if latest_completed else pd.DataFrame()
    dram_row = priority[priority["priority_symbol"].eq("DRAM")].iloc[0].to_dict() if not priority.empty and "DRAM" in set(priority["priority_symbol"]) else {}
    return {
        "eligible_symbol_count": len(set(eligible_symbols)),
        "mapped_symbol_count": int(mapping["mapping_status"].astype(str).str.upper().eq("PASS").sum()) if not mapping.empty else 0,
        "fetch_symbol_count": len(fetch_symbols),
        "fetch_symbol_count_minus_eligible": len(fetch_symbols) - len(set(eligible_symbols)),
        "priority_symbols": "|".join(PRIORITY_SYMBOLS),
        "priority_symbol_fetch_status": "|".join(priority["fetch_status"].astype(str).tolist()) if not priority.empty else "",
        "staging_distinct_symbol_count": int(research["internal_symbol"].nunique()) if not research.empty and "internal_symbol" in research else 0,
        "staging_distinct_symbol_count_by_latest_date": int(latest_group["symbol"].nunique()) if not latest_group.empty and "symbol" in latest_group else 0,
        "dram_requested": True,
        "dram_mapped": bool(dram_row.get("mapped", False)),
        "dram_fetched": bool(dram_row.get("fetched", False)),
        "dram_row_count": int(dram_row.get("row_count", 0) or 0),
        "dram_latest_raw_date": str(dram_row.get("latest_raw_date", "")),
        "dram_latest_completed_date": str(dram_row.get("latest_completed_date", "")),
    }


def final_status_from_gates(summary: dict[str, Any], trade_rows: int, gate_pass: bool, merge: dict[str, Any]) -> str:
    if summary["staging_distinct_symbol_count"] < max(1, int(summary["mapped_symbol_count"] * 0.80)):
        return "FAIL_V21_199_R2_FETCH_UNIVERSE_TRUNCATED"
    if not summary["dram_fetched"]:
        return "FAIL_V21_199_R2_DRAM_PRIORITY_FETCH_MISSING"
    if trade_rows == 0:
        return "FAIL_V21_199_R2_TRADE_PLAN_RAW_PANEL_EMPTY"
    if not summary.get("latest_completed_candidate_date"):
        return "FAIL_V21_199_R2_NO_COMPLETED_BROAD_DATE_AVAILABLE"
    if not summary.get("latest_moomoo_broad_honest_date"):
        return "FAIL_V21_199_R2_BROAD_DATE_COVERAGE_INSUFFICIENT"
    if not gate_pass:
        return "FAIL_V21_199_R2_DATA_QUALITY_GATE_FAILED"
    if merge.get("canonical_updated"):
        return "PASS_V21_199_R2_MOOMOO_CANONICAL_UPDATED"
    return "FAIL_V21_199_R2_DATA_QUALITY_GATE_FAILED"


def write_report(summary: dict[str, Any], out_dir: Path = OUT) -> None:
    keys = [
        "final_status", "final_decision", "eligible_symbol_count", "mapped_symbol_count", "fetch_symbol_count",
        "staging_distinct_symbol_count", "latest_raw_max_date", "latest_completed_candidate_date",
        "latest_moomoo_broad_honest_date", "best_broad_candidate_date", "best_broad_candidate_coverage_ratio",
        "dram_requested", "dram_mapped", "dram_fetched", "dram_row_count", "dram_latest_raw_date",
        "dram_latest_completed_date", "trade_plan_candidate_rows", "canonical_latest_date_before",
        "canonical_latest_date_after", "canonical_mutated", "research_only", "official_adoption_allowed",
        "broker_action_allowed", "trade_api_called",
    ]
    lines = [STAGE] + [f"{key}={summary.get(key, '')}" for key in keys]
    (out_dir / "V21.199_R2_moomoo_full_universe_fetch_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_empty_required_outputs(out_dir: Path) -> None:
    pd.DataFrame(columns=[
        "eligible_symbol_count", "mapped_symbol_count", "fetch_symbol_count", "fetch_symbol_count_minus_eligible",
        "priority_symbols", "priority_symbol_fetch_status", "staging_distinct_symbol_count",
        "staging_distinct_symbol_count_by_latest_date", "dram_requested", "dram_mapped", "dram_fetched",
        "dram_row_count", "dram_latest_raw_date", "dram_latest_completed_date",
    ]).to_csv(out_dir / "moomoo_full_universe_fetch_audit.csv", index=False)
    pd.DataFrame(columns=["priority_symbol", "requested", "mapped", "moomoo_code", "fetched", "row_count", "latest_raw_date", "latest_completed_date", "fetch_status"]).to_csv(out_dir / "moomoo_priority_symbol_audit.csv", index=False)
    pd.DataFrame(columns=["latest_raw_max_date", "latest_completed_candidate_date", "open_session_excluded_dates", "regular_session_open", "best_broad_candidate_date", "best_broad_candidate_coverage_ratio", "latest_moomoo_broad_honest_date"]).to_csv(out_dir / "moomoo_completed_date_gate_audit.csv", index=False)
    pd.DataFrame(columns=["date", "distinct_symbol_count", "eligible_symbol_count", "coverage_ratio", "broad_price_date_eligible"]).to_csv(out_dir / "moomoo_broad_date_coverage_r2.csv", index=False)
    pd.DataFrame().to_csv(out_dir / "moomoo_daily_ohlcv_staging_r2.csv", index=False)
    pd.DataFrame().to_csv(out_dir / "moomoo_daily_ohlcv_research_canonical_candidate_r2.csv", index=False)
    pd.DataFrame().to_csv(out_dir / "moomoo_daily_ohlcv_trade_plan_candidate_r2.csv", index=False)
    pd.DataFrame().to_csv(out_dir / "moomoo_data_quality_audit_r2.csv", index=False)


def run(
    client: MoomooQuoteClient | None = None,
    out_dir: Path = OUT,
    apply_merge: bool = True,
    eligible_symbols: list[str] | None = None,
    research_fetcher: Callable[..., tuple[pd.DataFrame, pd.DataFrame]] = fetch_many_daily,
    trade_fetcher: Callable[..., tuple[pd.DataFrame, pd.DataFrame]] = fetch_many_daily,
    research_canonical_path: Path = DEFAULT_RESEARCH_CANONICAL,
    trade_plan_canonical_path: Path = DEFAULT_TRADE_PLAN_CANONICAL,
    explicit_symbol_cap: int | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    before = latest_date(research_canonical_path)
    owns_client = client is None
    client = client or MoomooQuoteClient()
    health = client.health_check()
    if not health.get("minimal_quote_function_ok"):
        summary = {
            "stage": STAGE,
            "final_status": "FAIL_V21_199_R2_MOOMOO_OPEND_UNAVAILABLE",
            "final_decision": "STOP_BEFORE_STRATEGY_RERUN",
            "eligible_symbol_count": 0,
            "mapped_symbol_count": 0,
            "fetch_symbol_count": 0,
            "fetch_symbol_count_minus_eligible": 0,
            "priority_symbols": "|".join(PRIORITY_SYMBOLS),
            "priority_symbol_fetch_status": "",
            "staging_distinct_symbol_count": 0,
            "staging_distinct_symbol_count_by_latest_date": 0,
            "latest_raw_max_date": "",
            "latest_completed_candidate_date": "",
            "latest_moomoo_broad_honest_date": "",
            "best_broad_candidate_date": "",
            "best_broad_candidate_coverage_ratio": 0.0,
            "dram_requested": True,
            "dram_mapped": False,
            "dram_fetched": False,
            "dram_row_count": 0,
            "dram_latest_raw_date": "",
            "dram_latest_completed_date": "",
            "trade_plan_candidate_rows": 0,
            "canonical_latest_date_before": before,
            "canonical_latest_date_after": before,
            "canonical_mutated": False,
            "research_only": True,
            "official_adoption_allowed": False,
            "broker_action_allowed": False,
            "trade_api_called": False,
        }
        write_empty_required_outputs(out_dir)
        write_json(out_dir / "v21_199_r2_summary.json", summary)
        write_report(summary, out_dir)
        if owns_client:
            client.close()
        print(f"final_status={summary['final_status']}")
        return summary

    market = market_state_gate(client)
    market.to_csv(out_dir / "moomoo_market_state_audit_r2.csv", index=False)
    eligible = sorted({str(s).upper().strip() for s in (eligible_symbols or canonical_symbols(research_canonical_path)) if str(s).strip()})
    cap = explicit_symbol_cap if explicit_symbol_cap is not None else optional_test_symbol_cap()
    fetch_symbols = build_fetch_universe(eligible, PRIORITY_SYMBOLS, explicit_symbol_cap=cap)
    mapping = map_symbols(fetch_symbols, include_priority=False)
    mapping.to_csv(out_dir / "moomoo_symbol_mapping_audit_r2.csv", index=False)
    research, research_audit = research_fetcher(client, mapping, adjustment_mode="QFQ")
    trade, trade_audit = trade_fetcher(client, mapping, adjustment_mode="RAW")
    write_fetch_outputs(research, research_audit, "v21_199_r2_research_qfq")
    write_fetch_outputs(trade, trade_audit, "v21_199_r2_trade_plan_raw")
    research.to_csv(out_dir / "moomoo_daily_ohlcv_staging_r2.csv", index=False)
    research_candidate = normalize_for_canonical(research)
    trade_candidate = normalize_for_canonical(trade, adjusted_close_from_close=False) if not trade.empty else pd.DataFrame(columns=research_candidate.columns)
    trade_candidate.to_csv(out_dir / "moomoo_daily_ohlcv_trade_plan_candidate_r2.csv", index=False)
    market_open = regular_session_open(market)
    completed, completed_gate = completed_research_frame(research, market_open)
    completed.to_csv(out_dir / "moomoo_daily_ohlcv_research_canonical_candidate_r2.csv", index=False)
    completed_trade, _trade_gate = completed_research_frame(trade, market_open)
    priority = priority_symbol_audit(mapping, research, completed)
    priority.to_csv(out_dir / "moomoo_priority_symbol_audit.csv", index=False)
    full_audit = fetch_universe_audit(eligible, mapping, fetch_symbols, research, completed, priority)
    full_audit_df = pd.DataFrame([{**full_audit, **completed_gate}])
    full_audit_df.to_csv(out_dir / "moomoo_full_universe_fetch_audit.csv", index=False)

    gate_pass, gate_summary, coverage = quality_gate(completed, eligible, min_coverage_ratio=MIN_COVERAGE_RATIO)
    if coverage.empty:
        coverage = broad_date_coverage(completed, eligible, min_ratio=MIN_COVERAGE_RATIO)
    coverage.to_csv(out_dir / "moomoo_broad_date_coverage_r2.csv", index=False)
    best_row = coverage.sort_values(["coverage_ratio", "date"], ascending=[False, False]).head(1).to_dict("records")
    best = best_row[0] if best_row else {}
    completed_gate_rows = [{
        **completed_gate,
        "best_broad_candidate_date": str(best.get("date", "")),
        "best_broad_candidate_coverage_ratio": float(best.get("coverage_ratio", 0.0) or 0.0),
        "latest_moomoo_broad_honest_date": gate_summary.get("latest_moomoo_broad_honest_date", ""),
    }]
    pd.DataFrame(completed_gate_rows).to_csv(out_dir / "moomoo_completed_date_gate_audit.csv", index=False)
    data_quality = {
        **gate_summary,
        **full_audit,
        "trade_plan_candidate_rows": int(len(trade_candidate)),
        "completed_trade_plan_candidate_rows": int(len(completed_trade)),
        "best_broad_candidate_date": str(best.get("date", "")),
        "best_broad_candidate_coverage_ratio": float(best.get("coverage_ratio", 0.0) or 0.0),
    }
    pd.DataFrame([data_quality]).to_csv(out_dir / "moomoo_data_quality_audit_r2.csv", index=False)
    can_attempt_merge = bool(gate_pass and len(trade_candidate) > 0 and full_audit["dram_fetched"] and full_audit["staging_distinct_symbol_count"] >= max(1, int(full_audit["mapped_symbol_count"] * 0.80)))
    merge = merge_canonical(
        completed,
        completed_trade,
        eligible,
        research_canonical_path=research_canonical_path,
        trade_plan_canonical_path=trade_plan_canonical_path,
        backup_dir=out_dir / "canonical_backups",
        min_coverage_ratio=MIN_COVERAGE_RATIO,
        apply=apply_merge and can_attempt_merge,
    )
    after = latest_date(research_canonical_path)
    quota = audit_quota(client)
    merged_summary = {
        "stage": STAGE,
        **completed_gate,
        **gate_summary,
        **full_audit,
        **merge,
        "best_broad_candidate_date": str(best.get("date", "")),
        "best_broad_candidate_coverage_ratio": float(best.get("coverage_ratio", 0.0) or 0.0),
        "trade_plan_candidate_rows": int(len(trade_candidate)),
        "canonical_latest_date_before": before,
        "canonical_latest_date_after": after,
        "canonical_mutated": bool(merge.get("canonical_updated", False)),
        "quota_status": quota.get("quota_status", ""),
        "quota": quota,
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "trade_api_called": False,
    }
    final_status = final_status_from_gates(merged_summary, int(len(trade_candidate)), gate_pass, merge)
    merged_summary["final_status"] = final_status
    merged_summary["final_decision"] = "CANONICAL_UPDATED_RUN_ABCDE_NEXT" if final_status.startswith("PASS") else "STOP_BEFORE_STRATEGY_RERUN"
    write_json(out_dir / "moomoo_quota_audit_r2.json", quota)
    write_json(out_dir / "v21_199_r2_summary.json", merged_summary)
    write_report(merged_summary, out_dir)
    if owns_client:
        client.close()
    for key in ["final_status", "final_decision", "eligible_symbol_count", "mapped_symbol_count", "fetch_symbol_count", "staging_distinct_symbol_count", "latest_raw_max_date", "latest_completed_candidate_date", "latest_moomoo_broad_honest_date", "dram_fetched", "trade_plan_candidate_rows", "canonical_mutated"]:
        print(f"{key}={merged_summary.get(key, '')}")
    return merged_summary


if __name__ == "__main__":
    run()
