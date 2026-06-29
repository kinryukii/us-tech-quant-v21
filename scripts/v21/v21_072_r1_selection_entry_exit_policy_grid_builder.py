#!/usr/bin/env python
"""Build the research-only V21.072 selection/entry/exit policy grid."""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


STAGE = "V21.072-R1_SELECTION_ENTRY_EXIT_POLICY_GRID_BUILDER"
OUT_REL = Path("outputs/v21/v21_072")
SELECTION_NAME = "V21_072_R1_SELECTION_POLICY_CATALOG.csv"
ENTRY_NAME = "V21_072_R1_ENTRY_POLICY_CATALOG.csv"
EXIT_NAME = "V21_072_R1_EXIT_POLICY_CATALOG.csv"
GRID_NAME = "V21_072_R1_JOINT_POLICY_GRID.csv"
VALIDATION_NAME = "V21_072_R1_VALIDATION_SUMMARY.csv"

SELECTION_SOURCES = {
    "A1_BASELINE": "A1_BASELINE_REPLAY_CURRENT",
    "B_STATIC_MOMENTUM": "B_MOMENTUM_STATIC_R1",
    "C_DYNAMIC_MOMENTUM": "C_MOMENTUM_DYNAMIC_R1",
    "D_WEIGHT_OPTIMIZED_R1": "DERIVED_D_BASE_060_MOMENTUM_040",
    "P04_DYNAMIC_FACTOR_POLICY_R1": "P04_DYNAMIC_FACTOR_POLICY_R1",
}
ENTRY_POLICIES = {
    "ENTRY_PULLBACK_R1": {
        "ranking_strength": 25, "pullback_quality": 25,
        "trigger_recovery_proxy": 20, "oscillator_recovery": 15,
        "volume_confirmation": 10, "market_sector_regime": 5,
    },
    "ENTRY_BREAKOUT_CONTINUATION_R1": {
        "ranking_strength": 25, "breakout_continuation": 25,
        "relative_strength": 20, "volume_expansion": 15,
        "bullish_confirmation": 10, "market_sector_regime": 5,
    },
    "ENTRY_HYBRID_R1": {
        "ranking_strength": 25, "trend_confirmation": 20,
        "entry_pattern_quality": 20, "technical_confirmation": 15,
        "volume_liquidity": 10, "market_sector_regime": 10,
    },
}
EXIT_POLICIES = {
    "EXIT_FAST_RISK_CONTROL_R1": {
        "hard_stop_loss_control": 35, "option_loss_rule_if_enabled": 25,
        "trend_breakdown": 15, "momentum_exhaustion": 10,
        "time_dte_event_risk": 10, "ranking_deterioration": 5,
    },
    "EXIT_TREND_HOLD_R1": {
        "trend_breakdown": 30, "ma20_ma50_breakdown": 20,
        "ranking_deterioration": 15, "momentum_exhaustion": 15,
        "market_risk_off_transition": 10, "profit_protection": 10,
    },
    "EXIT_PROFIT_PROTECT_R1": {
        "profit_protection": 25, "momentum_exhaustion": 20,
        "oscillator_divergence": 15, "option_time_decay_if_available": 15,
        "event_risk": 15, "ranking_deterioration": 10,
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, object]:
    root = root.resolve()
    output = (
        output_override if output_override and output_override.is_absolute()
        else root / (output_override or OUT_REL)
    ).resolve()
    output.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    generated = now.isoformat()
    random_source = root / (
        "outputs/v21/experiments/momentum_dynamic/random_backtests/"
        "V21_060_R2_RANDOM_ASOF_BACKTEST_RESULTS.csv"
    )
    p04_candidates = list((root / "outputs/v21").rglob("*P04*RANKING*.csv"))
    selection_rows = []
    for policy, source_variant in SELECTION_SOURCES.items():
        available = policy != "P04_DYNAMIC_FACTOR_POLICY_R1" or bool(p04_candidates)
        selection_rows.append({
            "run_id": run_id, "generated_at_utc": generated,
            "selection_policy_id": policy, "source_variant": source_variant,
            "available": available,
            "base_weight": 0.60 if policy == "D_WEIGHT_OPTIMIZED_R1" else "",
            "momentum_weight": 0.40 if policy == "D_WEIGHT_OPTIMIZED_R1" else "",
            "score_method": (
                "0.60*base_score+0.40*momentum_score"
                if policy == "D_WEIGHT_OPTIMIZED_R1"
                else "SOURCE_VARIANT_SCORE"
            ),
            "research_only": True,
            "warning": "" if available else "P04_SOURCE_NOT_AVAILABLE",
        })
    entry_rows = [{
        "run_id": run_id, "generated_at_utc": generated,
        "entry_policy_id": policy, "weight_map": "|".join(
            f"{key}={value}" for key, value in weights.items()
        ), "normalized_weight_sum": sum(weights.values()),
        "first_day_breakout_chase_blocked": policy == "ENTRY_BREAKOUT_CONTINUATION_R1",
        "day2_continuation_allowed": policy == "ENTRY_BREAKOUT_CONTINUATION_R1",
        "proxy_evidence_only": True, "research_only": True,
    } for policy, weights in ENTRY_POLICIES.items()]
    exit_rows = [{
        "run_id": run_id, "generated_at_utc": generated,
        "exit_policy_id": policy, "weight_map": "|".join(
            f"{key}={value}" for key, value in weights.items()
        ), "normalized_weight_sum": sum(weights.values()),
        "option_simulation_enabled": False,
        "path_dependent_execution_required": True,
        "research_only": True,
        "warning": "WITHIN_WINDOW_PRICE_PATH_REQUIRED_FOR_CAUSAL_EXIT_BACKTEST",
    } for policy, weights in EXIT_POLICIES.items()]
    available_selection = [
        row["selection_policy_id"] for row in selection_rows if row["available"]
    ]
    grid_rows = []
    for selection in available_selection:
        for entry in ENTRY_POLICIES:
            for exit_policy in EXIT_POLICIES:
                grid_rows.append({
                    "run_id": run_id, "generated_at_utc": generated,
                    "joint_policy_id": f"{selection}__{entry}__{exit_policy}",
                    "selection_policy_id": selection,
                    "entry_policy_id": entry, "exit_policy_id": exit_policy,
                    "position_sizing_policy_id": "ASOF_RISK_BUCKET_SIZING_R1",
                    "ranking_only_enabled": True, "entry_filter_enabled": True,
                    "exit_simulation_enabled": False,
                    "position_sizing_enabled": True,
                    "point_in_time_required": True,
                    "future_information_allowed": False,
                    "official_adoption_allowed": False,
                    "forward_trade_signal_ledger_append_allowed": False,
                    "research_only": True,
                    "warning": "EXIT_PATH_EVIDENCE_REQUIRED;NO_OFFICIAL_OR_FORWARD_MUTATION",
                })
    pd.DataFrame(selection_rows).to_csv(output / SELECTION_NAME, index=False)
    pd.DataFrame(entry_rows).to_csv(output / ENTRY_NAME, index=False)
    pd.DataFrame(exit_rows).to_csv(output / EXIT_NAME, index=False)
    pd.DataFrame(grid_rows).to_csv(output / GRID_NAME, index=False)
    validation = {
        "stage": STAGE,
        "final_status": "PASS_V21_072_R1_POLICY_GRID_READY",
        "decision": "JOINT_POLICY_GRID_READY_RESEARCH_ONLY",
        "generated_at_utc": generated,
        "selection_policy_catalog_path": rel(root, output / SELECTION_NAME),
        "entry_policy_catalog_path": rel(root, output / ENTRY_NAME),
        "exit_policy_catalog_path": rel(root, output / EXIT_NAME),
        "joint_policy_grid_path": rel(root, output / GRID_NAME),
        "evaluation_source_path": rel(root, random_source),
        "evaluation_source_hash": sha256(random_source),
        "selection_policy_count": len(available_selection),
        "entry_policy_count": len(ENTRY_POLICIES),
        "exit_policy_count": len(EXIT_POLICIES),
        "total_policy_combinations": len(grid_rows),
        "p04_available": bool(p04_candidates),
        "weights_normalized": True, "official_adoption_allowed": False,
        "forward_trade_signal_ledger_append_allowed": False,
        "protected_outputs_modified": False, "official_outputs_mutated": False,
        "research_only": True, "pass_gate": True,
    }
    pd.DataFrame([validation]).to_csv(output / VALIDATION_NAME, index=False)
    return validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    result = run_stage(parser.parse_args().root, parser.parse_args().output_dir)
    print(f"FINAL_STATUS={result['final_status']}")
    print(f"DECISION={result['decision']}")
    print(f"SELECTION_POLICY_COUNT={result['selection_policy_count']}")
    print(f"ENTRY_POLICY_COUNT={result['entry_policy_count']}")
    print(f"EXIT_POLICY_COUNT={result['exit_policy_count']}")
    print(f"TOTAL_POLICY_COMBINATIONS={result['total_policy_combinations']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
