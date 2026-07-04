#!/usr/bin/env python
"""V21.198 isolated research-only Moomoo data backbone health check."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.data_sources.moomoo_client import MoomooQuoteClient
from scripts.data_sources.moomoo_market_state_gate import market_state_gate
from scripts.data_sources.moomoo_quota_auditor import audit_quota
from scripts.data_sources.moomoo_symbol_mapper import map_symbols


STAGE = "V21.198_MOOMOO_DATA_BACKBONE_AND_HEALTH_CHECK"
OUT = ROOT / "outputs/v21/V21.198_MOOMOO_DATA_BACKBONE_AND_HEALTH_CHECK"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def write_report(summary: dict[str, Any], out_dir: Path = OUT) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"opend_reachable={summary['opend_reachable']}",
        f"minimal_quote_function_ok={summary['minimal_quote_function_ok']}",
        f"quota_status={summary.get('quota_status', '')}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "trade_api_called=false",
    ]
    (out_dir / "V21.198_moomoo_data_backbone_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(client: MoomooQuoteClient | None = None, out_dir: Path = OUT) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    mapping = map_symbols(["DRAM", "QQQ", "AAPL"], include_priority=True)
    mapping.to_csv(out_dir / "moomoo_symbol_mapping_audit.csv", index=False)
    owns_client = client is None
    client = client or MoomooQuoteClient()
    health = client.health_check()
    market = pd.DataFrame()
    quota = {"quota_status": "FAIL", "error": "HEALTH_CHECK_FAILED"}
    if health.get("minimal_quote_function_ok"):
        market = market_state_gate(client, ["US.DRAM", "US.QQQ", "US.AAPL"])
        quota = audit_quota(client)
    else:
        market = pd.DataFrame([{"moomoo_code": "US.DRAM|US.QQQ|US.AAPL", "market_state": "", "decision": "BLOCK", "timestamp": "", "reason": health.get("error", "")}])
    market.to_csv(out_dir / "moomoo_market_state_audit.csv", index=False)
    write_json(out_dir / "moomoo_quota_audit.json", quota)
    final_pass = bool(health.get("minimal_quote_function_ok"))
    summary = {
        "stage": STAGE,
        "final_status": "PASS" if final_pass else "FAIL_V21_198_MOOMOO_OPEND_UNAVAILABLE",
        "final_decision": "MOOMOO_DATA_BACKBONE_READY_RESEARCH_ONLY" if final_pass else "STOP_MOOMOO_OPEND_UNAVAILABLE",
        "opend_reachable": bool(health.get("opend_reachable")),
        "minimal_quote_function_ok": bool(health.get("minimal_quote_function_ok")),
        "quota_status": quota.get("quota_status", ""),
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "trade_api_called": False,
    }
    write_json(out_dir / "moomoo_health_check.json", {**health, **summary})
    write_json(out_dir / "v21_198_summary.json", summary)
    write_report(summary, out_dir)
    if owns_client:
        client.close()
    for key in ["final_status", "final_decision", "opend_reachable", "minimal_quote_function_ok", "broker_action_allowed"]:
        print(f"{key}={summary[key]}")
    return summary


if __name__ == "__main__":
    run()
