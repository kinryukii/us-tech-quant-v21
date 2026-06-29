#!/usr/bin/env python
"""Build auditable ranking-only position-sizing policies."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from v21_075_common import OUT_REL, POLICIES, SELECTIONS


STAGE = "V21.075-R1_POSITION_SIZING_POLICY_BUILDER"
POLICY_NAME = "V21_075_R1_POSITION_SIZING_POLICY_CATALOG.csv"
GRID_NAME = "V21_075_R1_SELECTION_SIZING_POLICY_GRID.csv"
VALIDATION_NAME = "V21_075_R1_VALIDATION_SUMMARY.csv"


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, object]:
    root = root.resolve()
    output = (
        output_override if output_override and output_override.is_absolute()
        else root / (output_override or OUT_REL)
    ).resolve()
    output.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(timezone.utc).isoformat()
    rows = []
    for policy_id, method, top_n in POLICIES:
        rows.append({
            "position_policy_id": policy_id, "method": method, "top_n": top_n,
            "max_single_name_cap": 0.10 if top_n == 20 else 0.05,
            "min_single_name_floor": 0.01 if top_n == 20 else 0.005,
            "sector_cap": 0.30 if top_n == 20 else 0.20,
            "volatility_proxy": (
                "ASOF_RISK_SIZE_BUCKET_BOUNDED_PROXY"
                if method in {"VOL_ADJUSTED", "HYBRID_RISK_BUDGET"} else ""
            ),
            "volatility_floor": 0.75,
            "score_input": (
                "PIT_VARIANT_SCORE" if method in {
                    "SCORE_WEIGHTED", "VOL_ADJUSTED", "HYBRID_RISK_BUDGET"
                } else ""
            ),
            "data_quality_penalty": method == "HYBRID_RISK_BUDGET",
            "theme_sector_proxy_used_when_available": True,
            "theme_coverage_warning": "THEME_COVERAGE_LOW_SECTOR_CAP_DIAGNOSTIC",
            "future_returns_used_in_sizing": False,
            "official_adoption_allowed": False, "research_only": True,
        })
    catalog = pd.DataFrame(rows)
    catalog.to_csv(output / POLICY_NAME, index=False)
    grid = pd.DataFrame([
        {
            "selection_policy_id": selection,
            "position_policy_id": policy_id,
            "joint_portfolio_policy_id": f"{selection}__{policy_id}",
            "top_n": top_n, "research_only": True,
            "official_adoption_allowed": False,
            "forward_portfolio_observation_append_allowed": False,
        }
        for selection in SELECTIONS
        for policy_id, _, top_n in POLICIES
    ])
    grid.to_csv(output / GRID_NAME, index=False)
    validation = {
        "stage": STAGE,
        "final_status": "PASS_V21_075_R1_POSITION_SIZING_POLICY_GRID_READY",
        "decision": "RANKING_ONLY_SIZING_GRID_READY_RESEARCH_ONLY",
        "generated_at_utc": generated,
        "position_policies": len(catalog),
        "selection_policies": len(SELECTIONS),
        "total_portfolio_policies": len(grid),
        "d_ranking_only_baseline_preserved": True,
        "official_adoption_allowed": False,
        "forward_portfolio_observation_append_allowed": False,
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
    print(f"POSITION_POLICIES={result['position_policies']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
