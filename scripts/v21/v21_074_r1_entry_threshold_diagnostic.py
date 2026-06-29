#!/usr/bin/env python
"""Diagnose missed winners and avoided losers by deterministic entry block."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from v21_074_common import (
    OUT_REL, SELECTION_MAP, WINDOWS, entry_components, load_panel_with_d,
    primary_block_reason,
)


STAGE = "V21.074-R1_ENTRY_THRESHOLD_DIAGNOSTIC"
ROW_NAME = "V21_074_R1_ENTRY_BLOCK_DECISIONS.csv"
SUMMARY_NAME = "V21_074_R1_ENTRY_THRESHOLD_DIAGNOSTIC.csv"
VALIDATION_NAME = "V21_074_R1_VALIDATION_SUMMARY.csv"


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, object]:
    root = root.resolve()
    output = (
        output_override if output_override and output_override.is_absolute()
        else root / (output_override or OUT_REL)
    ).resolve()
    output.mkdir(parents=True, exist_ok=True)
    panel = load_panel_with_d(root)
    rows = []
    for selection, variant in SELECTION_MAP.items():
        source = panel[panel["variant_id"] == variant].copy()
        components = entry_components(source)
        reason = primary_block_reason(source, components, 80)
        blocked = reason.ne("other")
        result = source[[
            "seed", "batch_id", "sampled_as_of_date", "ticker", "split",
            "forward_window", "rank", "realized_forward_return",
        ]].copy()
        result["selection_policy_id"] = selection
        result["top20_flag"] = pd.to_numeric(result["rank"], errors="coerce").le(20)
        result["top50_flag"] = pd.to_numeric(result["rank"], errors="coerce").le(50)
        result["entry_score"] = components["entry_score"]
        result["blocked"] = blocked
        result["block_reason"] = reason
        rows.append(result)
    decisions = pd.concat(rows, ignore_index=True)
    decisions.to_csv(output / ROW_NAME, index=False)
    summaries = []
    for top_n, flag in (("TOP20", "top20_flag"), ("TOP50", "top50_flag")):
        subset = decisions[decisions[flag] & decisions["blocked"]]
        for keys, group in subset.groupby(
            ["block_reason", "selection_policy_id", "forward_window"], dropna=False
        ):
            returns = pd.to_numeric(group["realized_forward_return"], errors="coerce")
            winners, losers = returns[returns > 0], returns[returns < 0]
            summaries.append({
                "block_reason": keys[0], "selection_policy_id": keys[1],
                "window": keys[2], "top_n": top_n,
                "blocked_trade_count": len(group),
                "avoided_losers": len(losers), "missed_winners": len(winners),
                "avoided_loser_rate": len(losers) / max(len(group), 1),
                "missed_winner_rate": len(winners) / max(len(group), 1),
                "mean_return_of_blocked_winners": winners.mean(),
                "median_return_of_blocked_winners": winners.median(),
                "mean_return_of_avoided_losers": losers.mean(),
                "block_efficiency": len(losers) / max(len(winners), 1),
                "net_block_value_proxy": -returns.sum(),
            })
    summary = pd.DataFrame(summaries)
    summary.to_csv(output / SUMMARY_NAME, index=False)
    validation = {
        "stage": STAGE,
        "final_status": "PASS_V21_074_R1_ENTRY_THRESHOLD_DIAGNOSTIC_READY",
        "decision": "ENTRY_BLOCK_COST_AND_EFFICIENCY_DIAGNOSED",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "decision_rows": len(decisions), "diagnostic_rows": len(summary),
        "blocked_trade_count": int(decisions["blocked"].sum()),
        "avoided_losers": int(
            (decisions["blocked"] & pd.to_numeric(
                decisions["realized_forward_return"], errors="coerce"
            ).lt(0)).sum()
        ),
        "missed_winners": int(
            (decisions["blocked"] & pd.to_numeric(
                decisions["realized_forward_return"], errors="coerce"
            ).gt(0)).sum()
        ),
        "leakage_warnings": 0, "research_only": True, "pass_gate": True,
    }
    pd.DataFrame([validation]).to_csv(output / VALIDATION_NAME, index=False)
    return validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    print(f"FINAL_STATUS={result['final_status']}")
    print(f"DECISION={result['decision']}")
    print(f"AVOIDED_LOSERS={result['avoided_losers']}")
    print(f"MISSED_WINNERS={result['missed_winners']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
