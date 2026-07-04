#!/usr/bin/env python
"""V21.199 Moomoo broad daily bar import and quality-gated canonical merge."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.data_sources.moomoo_canonical_merger import (
    DEFAULT_RESEARCH_CANONICAL,
    DEFAULT_TRADE_PLAN_CANONICAL,
    merge_canonical,
    normalize_for_canonical,
    quality_gate,
)
from scripts.data_sources.moomoo_client import MoomooQuoteClient
from scripts.data_sources.moomoo_daily_ohlcv_fetcher import fetch_many_daily, write_fetch_outputs
from scripts.data_sources.moomoo_market_state_gate import import_allowed, market_state_gate
from scripts.data_sources.moomoo_quota_auditor import audit_quota
from scripts.data_sources.moomoo_symbol_mapper import map_symbols


STAGE = "V21.199_MOOMOO_BROAD_DAILY_BAR_IMPORT_AND_CANONICAL_MERGE"
OUT = ROOT / "outputs/v21/V21.199_MOOMOO_BROAD_DAILY_BAR_IMPORT_AND_CANONICAL_MERGE"
MIN_COVERAGE_RATIO = 0.95


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def canonical_symbols(path: Path = DEFAULT_RESEARCH_CANONICAL) -> list[str]:
    if not path.exists():
        return ["AAPL", "QQQ", "DRAM"]
    frame = pd.read_csv(path, usecols=lambda c: str(c).lower() in {"symbol", "ticker"}, low_memory=False)
    col = "symbol" if "symbol" in frame.columns else "ticker"
    symbols = sorted(frame[col].dropna().astype(str).str.upper().str.strip().unique())
    return symbols + ([] if "DRAM" in symbols else ["DRAM"])


def latest_date(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        frame = pd.read_csv(path, usecols=["date"], low_memory=False)
    except Exception:
        return ""
    return str(pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d").max()) if not frame.empty else ""


def write_report(summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"latest_moomoo_broad_honest_date={summary.get('latest_moomoo_broad_honest_date', '')}",
        f"canonical_latest_date_before={summary.get('canonical_latest_date_before', '')}",
        f"canonical_latest_date_after={summary.get('canonical_latest_date_after', '')}",
        f"dram_latest_date={summary.get('dram_latest_date', '')}",
        f"quota_status={summary.get('quota_status', '')}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "trade_api_called=false",
    ]
    (OUT / "V21.199_moomoo_broad_daily_import_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(client: MoomooQuoteClient | None = None, out_dir: Path = OUT, apply_merge: bool = True) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    before = latest_date(DEFAULT_RESEARCH_CANONICAL)
    owns_client = client is None
    client = client or MoomooQuoteClient()
    health = client.health_check()
    if not health.get("minimal_quote_function_ok"):
        summary = {
            "stage": STAGE,
            "final_status": "FAIL_V21_199_MOOMOO_OPEND_UNAVAILABLE",
            "final_decision": "STOP_BEFORE_CANONICAL_OR_STRATEGY_RERUN",
            "canonical_latest_date_before": before,
            "canonical_latest_date_after": before,
            "latest_moomoo_broad_honest_date": "",
            "dram_latest_date": "",
            "research_only": True,
            "official_adoption_allowed": False,
            "broker_action_allowed": False,
            "trade_api_called": False,
        }
        write_json(out_dir / "moomoo_canonical_merge_summary.json", summary)
        write_json(out_dir / "v21_199_summary.json", summary)
        write_report(summary)
        if owns_client:
            client.close()
        print(f"final_status={summary['final_status']}")
        return summary
    market = market_state_gate(client)
    market.to_csv(out_dir / "moomoo_market_state_audit.csv", index=False)
    universe = canonical_symbols()
    mapping = map_symbols(universe, include_priority=True)
    mapping.to_csv(out_dir / "moomoo_symbol_mapping_audit.csv", index=False)
    research, research_audit = fetch_many_daily(client, mapping, adjustment_mode="QFQ")
    trade, trade_audit = fetch_many_daily(client, mapping, adjustment_mode="RAW")
    write_fetch_outputs(research, research_audit, "v21_199_research_qfq")
    write_fetch_outputs(trade, trade_audit, "v21_199_trade_plan_raw")
    research.to_csv(out_dir / "moomoo_daily_ohlcv_staging.csv", index=False)
    normalize_for_canonical(research).to_csv(out_dir / "moomoo_daily_ohlcv_research_canonical_candidate.csv", index=False)
    normalize_for_canonical(trade, adjusted_close_from_close=False).to_csv(out_dir / "moomoo_daily_ohlcv_trade_plan_candidate.csv", index=False)
    gate_pass, gate_summary, coverage = quality_gate(research, universe, min_coverage_ratio=MIN_COVERAGE_RATIO)
    coverage.to_csv(out_dir / "moomoo_broad_date_coverage.csv", index=False)
    data_quality = pd.DataFrame([gate_summary])
    data_quality.to_csv(out_dir / "moomoo_data_quality_audit.csv", index=False)
    quota = audit_quota(client)
    if not import_allowed(market):
        gate_pass = False
        gate_summary["market_state_gate"] = "BLOCK"
    merge = merge_canonical(
        research,
        trade,
        universe,
        backup_dir=out_dir / "canonical_backups",
        min_coverage_ratio=MIN_COVERAGE_RATIO,
        apply=apply_merge and gate_pass,
    )
    after = latest_date(DEFAULT_RESEARCH_CANONICAL)
    if not gate_summary.get("latest_moomoo_broad_honest_date"):
        final_status = "FAIL_V21_199_BROAD_DATE_COVERAGE_INSUFFICIENT"
    elif not gate_summary.get("dram_present_and_current"):
        final_status = "FAIL_V21_199_DRAM_NOT_CURRENT"
    elif not gate_pass:
        final_status = "FAIL_V21_199_DATA_QUALITY_GATE_FAILED"
    elif merge.get("canonical_updated"):
        final_status = "PASS_V21_199_MOOMOO_CANONICAL_UPDATED"
    else:
        final_status = "FAIL_V21_199_DATA_QUALITY_GATE_FAILED"
    summary = {
        "stage": STAGE,
        **gate_summary,
        **merge,
        "final_status": final_status,
        "final_decision": "CANONICAL_UPDATED_RUN_ABCDE_NEXT" if final_status.startswith("PASS") else "STOP_BEFORE_STRATEGY_RERUN",
        "canonical_latest_date_before": before,
        "canonical_latest_date_after": after,
        "quota_status": quota.get("quota_status", ""),
        "quota": quota,
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "trade_api_called": False,
    }
    write_json(out_dir / "moomoo_quota_audit.json", quota)
    write_json(out_dir / "moomoo_canonical_merge_summary.json", summary)
    write_json(out_dir / "v21_199_summary.json", summary)
    write_report(summary)
    if owns_client:
        client.close()
    for key in ["final_status", "final_decision", "latest_moomoo_broad_honest_date", "canonical_latest_date_before", "canonical_latest_date_after", "dram_latest_date"]:
        print(f"{key}={summary.get(key, '')}")
    return summary


if __name__ == "__main__":
    run()
