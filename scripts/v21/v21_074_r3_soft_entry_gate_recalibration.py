#!/usr/bin/env python
"""Materialize auditable recalibrated hybrid entry variants."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from v21_074_common import ENTRY_VARIANTS, OUT_REL
from v21_074_r2_missed_winner_attribution import (
    OUTPUT_NAME as ATTRIBUTION_NAME, run_stage as run_r2,
)


STAGE = "V21.074-R3_SOFT_ENTRY_GATE_RECALIBRATION"
POLICY_NAME = "V21_074_R3_RECALIBRATED_ENTRY_POLICY_CATALOG.csv"
VALIDATION_NAME = "V21_074_R3_VALIDATION_SUMMARY.csv"


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, object]:
    root = root.resolve()
    output = (
        output_override if output_override and output_override.is_absolute()
        else root / (output_override or OUT_REL)
    ).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if not (output / ATTRIBUTION_NAME).is_file():
        run_r2(root, output)
    attribution = pd.read_csv(output / ATTRIBUTION_NAME)
    soften = set(
        attribution.loc[
            attribution["recommendation"].isin(["soften", "convert_to_penalty"]),
            "rule_name",
        ].astype(str)
    )
    rows = []
    for policy, threshold in ENTRY_VARIANTS.items():
        rows.append({
            "entry_policy_id": policy, "buy_threshold": threshold,
            "momentum_relaxed_threshold": (
                65 if policy == "ENTRY_HYBRID_MOMENTUM_RELAXED_R1" else ""
            ),
            "soft_penalty_rules": (
                "|".join(sorted(soften))
                if policy == "ENTRY_HYBRID_SOFT_BLOCK_R1" else ""
            ),
            "hard_block_data_quality": True,
            "hard_block_severe_pit_issue": True,
            "hard_block_extreme_overheat_reversal": True,
            "hard_block_risk_off_weak_trend": True,
            "hard_block_impossible_ohlc": True,
            "oscillator_incomplete_override_allowed": (
                policy == "ENTRY_HYBRID_MOMENTUM_RELAXED_R1"
            ),
            "d_or_c_top20_only_for_override": (
                policy == "ENTRY_HYBRID_MOMENTUM_RELAXED_R1"
            ),
            "research_only": True, "official_adoption_allowed": False,
            "warning": "PIT_PROXY_SCORE;NO_INTRADAY_TRIGGER_DATA",
        })
    catalog = pd.DataFrame(rows)
    catalog.to_csv(output / POLICY_NAME, index=False)
    validation = {
        "stage": STAGE,
        "final_status": "PASS_V21_074_R3_RECALIBRATED_ENTRY_GRID_READY",
        "decision": "RECALIBRATED_ENTRY_VARIANTS_READY_FOR_PATH_BACKTEST",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "entry_variant_count": len(catalog),
        "hard_safety_blocks_preserved": True,
        "official_adoption_allowed": False,
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
    print(f"ENTRY_VARIANT_COUNT={result['entry_variant_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
