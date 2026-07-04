#!/usr/bin/env python
"""V21.199 R4A active Moomoo symbol exclusion registry."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.v21.v21_199_r4_rate_limited_history_kline_fetch_and_resume import (
    DEFAULT_RESEARCH_CANONICAL,
    PRIORITY_SYMBOLS,
    build_active_fetch_symbols,
    canonical_symbols,
)


STAGE = "V21.199_R4A_SYMBOL_EXCLUSION_AND_UNKNOWN_TICKER_CLEANUP"
OUT = ROOT / "outputs/v21/V21.199_R4A_SYMBOL_EXCLUSION_AND_UNKNOWN_TICKER_CLEANUP"
EXCLUSION_REGISTRY = ROOT / "configs/v21/moomoo_symbol_exclusion_registry.csv"
EXCLUDED_SYMBOL = "SATS"
EXCLUSION_REASON = "UNKNOWN_TICKER_ON_MOOMOO"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def load_registry(path: Path = EXCLUSION_REGISTRY) -> pd.DataFrame:
    cols = ["internal_symbol", "moomoo_code", "exclusion_reason", "active_exclusion", "preserve_historical_manifests", "notes"]
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=cols)
    return pd.read_csv(path).reindex(columns=cols)


def upsert_sats_registry(path: Path = EXCLUSION_REGISTRY) -> pd.DataFrame:
    path.parent.mkdir(parents=True, exist_ok=True)
    reg = load_registry(path)
    reg = reg[reg["internal_symbol"].astype(str).str.upper().ne(EXCLUDED_SYMBOL)].copy() if not reg.empty else reg
    row = {
        "internal_symbol": EXCLUDED_SYMBOL,
        "moomoo_code": f"US.{EXCLUDED_SYMBOL}",
        "exclusion_reason": EXCLUSION_REASON,
        "active_exclusion": True,
        "preserve_historical_manifests": True,
        "notes": "Moomoo request_history_kline returned unknown ticker for QFQ and RAW; future fetches skip this active symbol.",
    }
    reg = pd.concat([reg, pd.DataFrame([row])], ignore_index=True)
    reg.to_csv(path, index=False)
    return reg


def run(out_dir: Path = OUT, registry_path: Path = EXCLUSION_REGISTRY, canonical_path: Path = DEFAULT_RESEARCH_CANONICAL) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    universe = canonical_symbols(canonical_path)
    before = len(set(universe))
    registry = upsert_sats_registry(registry_path)
    registry.to_csv(out_dir / "symbol_exclusion_registry.csv", index=False)
    unknown = registry[registry["exclusion_reason"].astype(str).eq(EXCLUSION_REASON)].copy()
    unknown.to_csv(out_dir / "unknown_ticker_audit.csv", index=False)
    active_exclusions = set(registry.loc[registry["active_exclusion"].astype(str).str.lower().isin(["true", "1", "yes"]), "internal_symbol"].astype(str).str.upper())
    active_eligible = [s for s in universe if str(s).upper().strip() not in active_exclusions]
    after = len(set(active_eligible))
    after_symbols = build_active_fetch_symbols(universe, registry_path=registry_path)
    sats_requested = EXCLUDED_SYMBOL in set(after_symbols) or f"US.{EXCLUDED_SYMBOL}" in set(after_symbols)
    before_after = pd.DataFrame([{
        "active_universe_count_before": before,
        "active_universe_count_after": after,
        "excluded_symbol_count": before - after if before >= after else 0,
        "sats_requested_after_patch": sats_requested,
        "historical_outputs_deleted": False,
    }])
    before_after.to_csv(out_dir / "active_universe_before_after_audit.csv", index=False)
    summary = {
        "stage": STAGE,
        "final_status": "PASS_V21_199_R4A_SYMBOL_EXCLUSION_REGISTERED",
        "final_decision": "SATS_EXCLUDED_FROM_ACTIVE_MOOMOO_FETCH_UNIVERSE",
        "excluded_symbol_count": 1,
        "excluded_symbols": EXCLUDED_SYMBOL,
        "exclusion_reason": EXCLUSION_REASON,
        "active_universe_count_before": before,
        "active_universe_count_after": after,
        "sats_requested_after_patch": bool(sats_requested),
        "historical_outputs_deleted": False,
        "broker_action_allowed": False,
        "trade_api_called": False,
        "research_only": True,
        "official_adoption_allowed": False,
    }
    write_json(out_dir / "v21_199_r4a_summary.json", summary)
    report = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"excluded_symbol_count={summary['excluded_symbol_count']}",
        f"excluded_symbols={summary['excluded_symbols']}",
        f"exclusion_reason={summary['exclusion_reason']}",
        f"active_universe_count_before={summary['active_universe_count_before']}",
        f"active_universe_count_after={summary['active_universe_count_after']}",
        f"sats_requested_after_patch={summary['sats_requested_after_patch']}",
        "historical_outputs_deleted=false",
        "broker_action_allowed=false",
        "trade_api_called=false",
    ]
    (out_dir / "V21.199_R4A_symbol_exclusion_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    for key in ["final_status", "final_decision", "excluded_symbols", "sats_requested_after_patch", "broker_action_allowed", "trade_api_called"]:
        print(f"{key}={summary[key]}")
    return summary


if __name__ == "__main__":
    run()
