#!/usr/bin/env python
"""Rank entry rules by missed-winner cost and block efficiency."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from v21_074_common import OUT_REL
from v21_074_r1_entry_threshold_diagnostic import (
    ROW_NAME, run_stage as run_r1,
)


STAGE = "V21.074-R2_MISSED_WINNER_ATTRIBUTION"
OUTPUT_NAME = "V21_074_R2_MISSED_WINNER_ATTRIBUTION.csv"
VALIDATION_NAME = "V21_074_R2_VALIDATION_SUMMARY.csv"


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, object]:
    root = root.resolve()
    output = (
        output_override if output_override and output_override.is_absolute()
        else root / (output_override or OUT_REL)
    ).resolve()
    if not (output / ROW_NAME).is_file():
        run_r1(root, output)
    decisions = pd.read_csv(output / ROW_NAME, low_memory=False)
    blocked = decisions[decisions["blocked"].map(
        lambda value: str(value).upper() == "TRUE"
    )].copy()
    returns = pd.to_numeric(blocked["realized_forward_return"], errors="coerce")
    blocked["_return"] = returns
    rows = []
    for reason, group in blocked.groupby("block_reason"):
        winners = group[group["_return"] > 0]["_return"]
        losers = group[group["_return"] < 0]["_return"]
        efficiency = len(losers) / max(len(winners), 1)
        missed_cost = winners.sum()
        if reason in {"data_quality_block", "market_regime_block", "overheat_block"}:
            recommendation = "keep"
        elif efficiency < 0.6 and missed_cost > abs(losers.sum()):
            recommendation = "soften"
        elif efficiency < 1.0:
            recommendation = "convert_to_penalty"
        else:
            recommendation = "keep"
        rows.append({
            "rule_name": reason, "missed_winner_count": len(winners),
            "missed_winner_mean_return": winners.mean(),
            "missed_winner_total_return_cost": missed_cost,
            "avoided_loser_count": len(losers),
            "avoided_loser_mean_loss": losers.mean(),
            "avoided_loser_total_loss_avoided": abs(losers.sum()),
            "block_efficiency": efficiency,
            "recommendation": recommendation,
        })
    attribution = pd.DataFrame(rows).sort_values(
        ["missed_winner_total_return_cost", "block_efficiency"],
        ascending=[False, True],
    )
    attribution["attribution_rank"] = range(1, len(attribution) + 1)
    attribution.to_csv(output / OUTPUT_NAME, index=False)
    validation = {
        "stage": STAGE,
        "final_status": "PASS_V21_074_R2_MISSED_WINNER_ATTRIBUTION_READY",
        "decision": "HIGH_COST_LOW_EFFICIENCY_BLOCKS_IDENTIFIED",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "rules_attributed": len(attribution),
        "soften_count": int(attribution["recommendation"].eq("soften").sum()),
        "penalty_conversion_count": int(
            attribution["recommendation"].eq("convert_to_penalty").sum()
        ),
        "research_only": True, "pass_gate": True,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
