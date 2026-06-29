#!/usr/bin/env python
"""V21.104 full random long-horizon hold-only A1/B/C/D backtest."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STAGE = "V21.104_ABCD_RANDOM_252D_HOLD_BACKTEST_FULL_RUN"
OUTPUT_ROOT_REL = Path("outputs/v21/v21_104_abcd_random_252d_hold_full_run")
CONFIG_NAME = "v21_104_abcd_random_252d_hold_config.json"
SAMPLE_NAME = "v21_104_abcd_random_sample_dates.csv"
ROWS_NAME = "v21_104_abcd_252d_hold_row_results.csv"
SUMMARY_NAME = "v21_104_abcd_252d_hold_summary.csv"
PAIRWISE_NAME = "v21_104_abcd_252d_hold_pairwise_comparison.csv"
BENCHMARK_NAME = "v21_104_abcd_252d_hold_benchmark_comparison.csv"
LEAKAGE_NAME = "v21_104_abcd_252d_hold_leakage_audit.csv"
WARNING_NAME = "v21_104_abcd_252d_hold_data_quality_warnings.csv"
WORST_NAME = "v21_104_abcd_252d_hold_worst_samples.csv"
README_NAME = "v21_104_abcd_252d_hold_decision_readme.md"

PASS = "PASS_V21_104_D_LONG_HORIZON_EDGE_CONFIRMED_RESEARCH_ONLY"
PARTIAL_TAIL = "PARTIAL_PASS_V21_104_D_EDGE_EXISTS_BUT_LEFT_TAIL_WARN"
PARTIAL_NO_EDGE = "PARTIAL_PASS_V21_104_NO_CLEAR_D_EDGE_KEEP_MONITORING"
FAIL_UNDERPERFORM = "FAIL_V21_104_D_UNDERPERFORMS_A1_OR_QQQ"
FAIL_BLOCKER = "FAIL_V21_104_LEAKAGE_OR_DATA_QUALITY_BLOCKER"

PAIRWISE = (
    ("D", "A1"), ("D", "B"), ("D", "C"), ("D", "QQQ"),
    ("D", "SPY"), ("D", "SOXX"), ("B", "A1"), ("C", "A1"), ("C", "B"),
)

SUMMARY_FIELDS = [
    "variant", "portfolio_size", "horizon", "sample_count", "mean_return",
    "median_return", "p5_return", "p25_return", "p75_return", "p95_return",
    "worst_sample_return", "best_sample_return", "mean_excess_vs_A1",
    "median_excess_vs_A1", "p5_excess_vs_A1", "mean_excess_vs_QQQ",
    "median_excess_vs_QQQ", "p5_excess_vs_QQQ", "mean_excess_vs_SPY",
    "median_excess_vs_SPY", "mean_excess_vs_SOXX", "median_excess_vs_SOXX",
    "win_rate_vs_A1", "win_rate_vs_B", "win_rate_vs_C", "win_rate_vs_D",
    "win_rate_vs_QQQ", "win_rate_vs_SPY", "win_rate_vs_SOXX",
    "missing_price_count", "leakage_warning_count",
    "survivorship_bias_warning_count", "pit_factor_approximation_warning_count",
]

PAIRWISE_FIELDS = [
    "portfolio_size", "horizon", "left", "right", "paired_sample_count",
    "left_mean_return", "right_mean_return", "mean_return_delta",
    "median_return_delta", "p5_return_delta", "left_win_count",
    "right_win_count", "tie_count", "left_win_rate", "right_win_rate",
    "directional_result", "research_only",
]

BENCHMARK_FIELDS = [
    "variant", "portfolio_size", "horizon", "benchmark", "sample_count",
    "mean_variant_return", "mean_benchmark_return", "mean_excess_return",
    "median_excess_return", "p5_excess_return", "win_rate_vs_benchmark",
    "research_only",
]


def load_v103(root: Path):
    path = root / "scripts/v21/v21_103_abcd_random_long_horizon_backtest_spec.py"
    spec = importlib.util.spec_from_file_location("v21_103_shared_for_v104", path)
    if not spec or not spec.loader:
        raise RuntimeError("V21.103 shared implementation cannot be loaded.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def output_path(root: Path, override: Path | None, run_id: str | None) -> Path:
    if override:
        return (override if override.is_absolute() else root / override).resolve()
    identifier = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return (root / OUTPUT_ROOT_REL / identifier).resolve()


def numeric_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    numeric = [
        "portfolio_return", "benchmark_QQQ_return", "benchmark_SPY_return",
        "benchmark_semiconductor_return", "excess_vs_A1", "excess_vs_B",
        "excess_vs_C", "excess_vs_D", "excess_vs_QQQ", "excess_vs_SPY",
        "excess_vs_semiconductor_benchmark", "missing_price_count",
    ]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def summaries(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    frame = numeric_frame(rows)
    output = []
    for keys, group in frame.groupby(["variant", "portfolio_size", "horizon"], sort=True):
        values = group["portfolio_return"].dropna()
        output.append({
            "variant": keys[0], "portfolio_size": keys[1], "horizon": keys[2],
            "sample_count": len(values), "mean_return": values.mean(),
            "median_return": values.median(), "p5_return": values.quantile(.05),
            "p25_return": values.quantile(.25), "p75_return": values.quantile(.75),
            "p95_return": values.quantile(.95), "worst_sample_return": values.min(),
            "best_sample_return": values.max(),
            "mean_excess_vs_A1": group["excess_vs_A1"].mean(),
            "median_excess_vs_A1": group["excess_vs_A1"].median(),
            "p5_excess_vs_A1": group["excess_vs_A1"].quantile(.05),
            "mean_excess_vs_QQQ": group["excess_vs_QQQ"].mean(),
            "median_excess_vs_QQQ": group["excess_vs_QQQ"].median(),
            "p5_excess_vs_QQQ": group["excess_vs_QQQ"].quantile(.05),
            "mean_excess_vs_SPY": group["excess_vs_SPY"].mean(),
            "median_excess_vs_SPY": group["excess_vs_SPY"].median(),
            "mean_excess_vs_SOXX": group["excess_vs_semiconductor_benchmark"].mean(),
            "median_excess_vs_SOXX": group["excess_vs_semiconductor_benchmark"].median(),
            "win_rate_vs_A1": group["excess_vs_A1"].gt(0).mean(),
            "win_rate_vs_B": group["excess_vs_B"].gt(0).mean(),
            "win_rate_vs_C": group["excess_vs_C"].gt(0).mean(),
            "win_rate_vs_D": group["excess_vs_D"].gt(0).mean(),
            "win_rate_vs_QQQ": group["excess_vs_QQQ"].gt(0).mean(),
            "win_rate_vs_SPY": group["excess_vs_SPY"].gt(0).mean(),
            "win_rate_vs_SOXX": group["excess_vs_semiconductor_benchmark"].gt(0).mean(),
            "missing_price_count": int(group["missing_price_count"].sum()),
            "leakage_warning_count": int((group["point_in_time_valid"] != "TRUE").sum()),
            "survivorship_bias_warning_count": int((group["survivorship_bias_warning"] == "TRUE").sum()),
            "pit_factor_approximation_warning_count": len(group),
        })
    return output


def comparison_series(frame: pd.DataFrame, name: str) -> pd.Series:
    if name in {"A1", "B", "C", "D"}:
        return frame[name]
    return frame[f"benchmark_{name}_return"]


def pairwise_comparisons(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    frame = numeric_frame(rows)
    pivot = frame.pivot_table(
        index=["sample_id", "portfolio_size", "horizon"],
        columns="variant", values="portfolio_return", aggfunc="first",
    ).reset_index()
    benchmark = frame[frame["variant"].eq("A1")][[
        "sample_id", "portfolio_size", "horizon", "benchmark_QQQ_return",
        "benchmark_SPY_return", "benchmark_semiconductor_return",
    ]].rename(columns={"benchmark_semiconductor_return": "benchmark_SOXX_return"})
    pivot = pivot.merge(benchmark, on=["sample_id", "portfolio_size", "horizon"], how="left")
    output = []
    for (size, horizon), group in pivot.groupby(["portfolio_size", "horizon"], sort=True):
        for left, right in PAIRWISE:
            left_values = comparison_series(group, left)
            right_values = comparison_series(group, right)
            valid = left_values.notna() & right_values.notna()
            delta = left_values[valid] - right_values[valid]
            wins, losses = int(delta.gt(0).sum()), int(delta.lt(0).sum())
            ties = int(delta.eq(0).sum())
            count = len(delta)
            output.append({
                "portfolio_size": size, "horizon": horizon, "left": left,
                "right": right, "paired_sample_count": count,
                "left_mean_return": left_values[valid].mean(),
                "right_mean_return": right_values[valid].mean(),
                "mean_return_delta": delta.mean(), "median_return_delta": delta.median(),
                "p5_return_delta": delta.quantile(.05), "left_win_count": wins,
                "right_win_count": losses, "tie_count": ties,
                "left_win_rate": wins / count if count else np.nan,
                "right_win_rate": losses / count if count else np.nan,
                "directional_result": "LEFT_BETTER" if wins > losses else "RIGHT_BETTER" if losses > wins else "TIED",
                "research_only": "TRUE",
            })
    return output


def benchmark_comparisons(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    frame = numeric_frame(rows)
    output = []
    mapping = {
        "QQQ": ("benchmark_QQQ_return", "excess_vs_QQQ"),
        "SPY": ("benchmark_SPY_return", "excess_vs_SPY"),
        "SOXX": ("benchmark_semiconductor_return", "excess_vs_semiconductor_benchmark"),
    }
    for keys, group in frame.groupby(["variant", "portfolio_size", "horizon"], sort=True):
        for benchmark, (return_column, excess_column) in mapping.items():
            excess = group[excess_column].dropna()
            output.append({
                "variant": keys[0], "portfolio_size": keys[1], "horizon": keys[2],
                "benchmark": benchmark, "sample_count": len(excess),
                "mean_variant_return": group.loc[excess.index, "portfolio_return"].mean(),
                "mean_benchmark_return": group.loc[excess.index, return_column].mean(),
                "mean_excess_return": excess.mean(),
                "median_excess_return": excess.median(),
                "p5_excess_return": excess.quantile(.05),
                "win_rate_vs_benchmark": excess.gt(0).mean(),
                "research_only": "TRUE",
            })
    return output


def worst_samples(rows: list[dict[str, object]], count: int = 20) -> list[dict[str, object]]:
    frame = numeric_frame(rows)
    columns = [
        "sample_id", "seed", "draw_index", "start_date", "variant",
        "portfolio_size", "horizon", "portfolio_return", "excess_vs_A1",
        "excess_vs_QQQ", "excess_vs_SPY", "excess_vs_semiconductor_benchmark",
        "max_drawdown", "missing_price_count", "point_in_time_valid",
        "survivorship_bias_warning", "research_only",
    ]
    output = []
    for keys, group in frame.groupby(["variant", "portfolio_size", "horizon"], sort=True):
        output.extend(group.nsmallest(count, "portfolio_return")[columns].to_dict("records"))
    return output


def decision(summary: pd.DataFrame, leakage_failures: int, core_ok: bool) -> tuple[str, str, dict[str, Any]]:
    primary = summary[
        (summary["variant"] == "D")
        & (pd.to_numeric(summary["portfolio_size"]) == 20)
        & (pd.to_numeric(summary["horizon"]) == 252)
    ]
    a1 = summary[
        (summary["variant"] == "A1")
        & (pd.to_numeric(summary["portfolio_size"]) == 20)
        & (pd.to_numeric(summary["horizon"]) == 252)
    ]
    if leakage_failures or not core_ok or primary.empty or a1.empty:
        return FAIL_BLOCKER, "STOP_REPAIR_LEAKAGE_OR_CORE_DATA", {}
    d, baseline = primary.iloc[0], a1.iloc[0]
    p5_gap_vs_a1 = float(d["p5_excess_vs_QQQ"]) - float(baseline["p5_excess_vs_QQQ"])
    promising = (
        float(d["win_rate_vs_A1"]) > .55
        and float(d["win_rate_vs_QQQ"]) > .55
        and float(d["median_excess_vs_QQQ"]) > 0
        and p5_gap_vs_a1 >= -.05
    )
    higher_mean = float(d["mean_excess_vs_A1"]) > 0 or float(d["mean_excess_vs_QQQ"]) > 0
    worse_median = float(d["median_excess_vs_A1"]) <= 0 or float(d["median_excess_vs_QQQ"]) <= 0
    left_tail = p5_gap_vs_a1 < -.05
    facts = {
        "d_top20_252d_win_rate_vs_A1": float(d["win_rate_vs_A1"]),
        "d_top20_252d_win_rate_vs_QQQ": float(d["win_rate_vs_QQQ"]),
        "d_top20_252d_median_excess_vs_QQQ": float(d["median_excess_vs_QQQ"]),
        "d_top20_252d_p5_excess_vs_QQQ": float(d["p5_excess_vs_QQQ"]),
        "a1_top20_252d_p5_excess_vs_QQQ": float(baseline["p5_excess_vs_QQQ"]),
        "d_p5_gap_vs_A1": p5_gap_vs_a1,
        "left_tail_warning": left_tail,
    }
    if promising:
        return PASS, "D_LONG_HORIZON_EDGE_CONFIRMED_RESEARCH_ONLY_NO_ADOPTION", facts
    if higher_mean and (worse_median or left_tail):
        return PARTIAL_TAIL, "D_MEAN_EDGE_WITH_MEDIAN_OR_LEFT_TAIL_WARNING", facts
    if float(d["mean_excess_vs_A1"]) < 0 and float(d["mean_excess_vs_QQQ"]) < 0:
        return FAIL_UNDERPERFORM, "D_UNDERPERFORMS_A1_AND_QQQ", facts
    return PARTIAL_NO_EDGE, "D_DOES_NOT_CLEAR_PRIMARY_LONG_HORIZON_EDGE_THRESHOLDS", facts


def render_readme(
    output: Path, run_id: str, status: str, decision_text: str,
    samples: list[dict[str, object]], summary: pd.DataFrame,
    pairwise: pd.DataFrame, leakage_failures: int, facts: dict[str, Any],
) -> None:
    def pair(left: str, right: str) -> str:
        row = pairwise[
            (pairwise["portfolio_size"] == 20) & (pairwise["horizon"] == 252)
            & (pairwise["left"] == left) & (pairwise["right"] == right)
        ]
        return "NOT_AVAILABLE" if row.empty else (
            f"{'YES' if float(row.iloc[0]['left_win_rate']) > .5 else 'NO'} "
            f"(win_rate={float(row.iloc[0]['left_win_rate']):.4f})"
        )
    text = f"""# V21.104 A1/B/C/D Random 252D Hold Full Run

FINAL_STATUS: `{status}`  
DECISION: `{decision_text}`  
run_id: `{run_id}`  
official_adoption_allowed: `false`  
broker_action_allowed: `false`

## Run scope

- Attempted configured samples: 30 seeds x 100 dates = 3000
- Actual sample_count: {len(samples)}
- Horizons tested: 126, 189, 252 trading days
- Primary horizon: 252 trading days
- Variants tested: A1, B, C, D
- Portfolio sizes: Top20, Top50
- Mode: RANDOM_252D_HOLD only
- Benchmarks: QQQ, SPY, SOXX

## D Top20 252D decisions

- D beat A1: {pair('D', 'A1')}
- D beat B: {pair('D', 'B')}
- D beat C: {pair('D', 'C')}
- D beat QQQ: {pair('D', 'QQQ')}
- D beat SOXX: {pair('D', 'SOXX')}
- D has left-tail weakness: {'YES' if facts.get('left_tail_warning') else 'NO'}
- Critical leakage failures exist: {'YES' if leakage_failures else 'NO'}
- Survivorship bias warning exists: YES
- PIT factor approximation warning exists: YES

## Primary acceptance facts

```json
{json.dumps(facts, indent=2)}
```

## PIT and data boundaries

- Historical rankings were recomputed from canonical OHLCV using input dates no later than each as-of date.
- Current rankings, forward labels, event-risk coefficients, broker data, and trading actions were not used.
- Forward returns start after each as-of date.
- Missing prices are recorded and remaining available positions are deterministically reweighted.
- `SURVIVORSHIP_BIAS_WARN` and `PIT_FACTOR_APPROXIMATION_WARN` remain active.

This result is research-only and cannot authorize official adoption.
"""
    (output / README_NAME).write_text(text, encoding="utf-8")


def run_stage(root: Path, output: Path, run_id: str) -> dict[str, object]:
    root, output = root.resolve(), output.resolve()
    v103 = load_v103(root)
    v103.ensure_immutable_output(output)
    protected = v103.protected_files(root, output)
    before = {path: v103.sha256(path) for path in protected}
    warnings = [
        {
            "warning_code": "SURVIVORSHIP_BIAS_WARN", "severity": "MEDIUM",
            "scope": "ALL_SAMPLES",
            "details": "True historical PIT universe membership is unavailable; current canonical ticker coverage is used.",
            "research_only": "TRUE",
        },
        {
            "warning_code": "PIT_FACTOR_APPROXIMATION_WARN", "severity": "MEDIUM",
            "scope": "A1_B_C_D_HISTORICAL_RANKINGS",
            "details": "Historical full-factor A1 inputs are unavailable; documented price/volume PIT-lite factors are used.",
            "research_only": "TRUE",
        },
    ]
    try:
        data = v103.load_market_data(root)
        if data.semiconductor_benchmark != "SOXX":
            raise RuntimeError("SOXX benchmark is required for V21.104.")
        features = v103.rolling_features(data)
        eligible = v103.eligible_start_dates(
            data.calendar, features["base"].dropna(how="all").index, v103.PRIMARY_HORIZON,
        )
        samples = v103.sample_dates(
            eligible, v103.DEFAULT_SEEDS, v103.DEFAULT_DATES_PER_SEED,
        )
        config = {
            "stage": STAGE, "run_id": run_id,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "seed_count": len(v103.DEFAULT_SEEDS),
            "random_start_dates_per_seed": v103.DEFAULT_DATES_PER_SEED,
            "configured_sample_count": len(v103.DEFAULT_SEEDS) * v103.DEFAULT_DATES_PER_SEED,
            "actual_sample_count": len(samples), "eligible_start_date_count": len(eligible),
            "horizons": list(v103.HORIZONS), "primary_horizon": v103.PRIMARY_HORIZON,
            "mode": "RANDOM_252D_HOLD", "portfolio_sizes": list(v103.PORTFOLIO_SIZES),
            "variants": list(v103.VARIANTS), "benchmarks": ["QQQ", "SPY", "SOXX"],
            "variant_weights": {
                "A1": {"base": 1.0, "momentum": 0.0},
                "B": {"base": .80, "momentum": .20},
                "C": {"dynamic_momentum": {"risk_off": .10, "neutral": .15, "risk_on": .20}},
                "D": {"base": .60, "momentum": .40},
            },
            "missing_price_policy": "REWEIGHT_REMAINING_AVAILABLE_POSITIONS_AT_EACH_VALUATION_POINT",
            "survivorship_bias_warning": True,
            "pit_factor_approximation_warning": True,
            "event_risk_integrated": False, "official_adoption_allowed": False,
            "broker_action_allowed": False, "research_only": True,
        }
        v103.write_json(output / CONFIG_NAME, config)
        v103.write_csv(
            output / SAMPLE_NAME, samples,
            ["sample_id", "seed", "draw_index", "start_date", "eligible_start_date_count",
             "sampling_with_replacement", "minimum_forward_sessions", "research_only"],
        )
        rank_cache: dict[str, dict[str, pd.DataFrame]] = {}
        rows: list[dict[str, object]] = []
        for sample in samples:
            day = str(sample["start_date"])
            if day not in rank_cache:
                rank_cache[day] = v103.rank_variants(features, day)
            for size in v103.PORTFOLIO_SIZES:
                for horizon in v103.HORIZONS:
                    rows.extend(v103.hold_result(data, rank_cache[day], sample, size, horizon))
        audits = v103.leakage_audit(rows)
        leakage_failures = sum(not v103.truth(row["point_in_time_valid"]) for row in audits)
        summary_rows = summaries(rows)
        pair_rows = pairwise_comparisons(rows)
        benchmark_rows = benchmark_comparisons(rows)
        worst_rows = worst_samples(rows)
        v103.write_csv(output / ROWS_NAME, rows, v103.ROW_FIELDS)
        v103.write_csv(output / SUMMARY_NAME, summary_rows, SUMMARY_FIELDS)
        v103.write_csv(output / PAIRWISE_NAME, pair_rows, PAIRWISE_FIELDS)
        v103.write_csv(output / BENCHMARK_NAME, benchmark_rows, BENCHMARK_FIELDS)
        v103.write_csv(
            output / LEAKAGE_NAME, audits,
            ["sample_id", "mode", "variant", "portfolio_size", "horizon",
             "transaction_cost_bps", "start_date", "ranking_max_input_date",
             "forward_return_starts_after_as_of", "current_ranking_used",
             "future_label_used", "future_membership_used", "point_in_time_valid",
             "leakage_violation_reason", "research_only"],
        )
        if len(samples) < 3000:
            warnings.append({
                "warning_code": "REDUCED_SAMPLE_COUNT_WARN", "severity": "MEDIUM",
                "scope": "STAGE",
                "details": f"Configured 3000 samples; produced {len(samples)} because of available eligible dates.",
                "research_only": "TRUE",
            })
        if any(int(row["missing_price_count"]) for row in rows):
            warnings.append({
                "warning_code": "MISSING_FORWARD_PRICE_REWEIGHT_APPLIED",
                "severity": "LOW", "scope": "ROW_RESULTS",
                "details": "Missing valuation prices were recorded; remaining positions were reweighted.",
                "research_only": "TRUE",
            })
        v103.write_csv(
            output / WARNING_NAME, warnings,
            ["warning_code", "severity", "scope", "details", "research_only"],
        )
        worst_fields = list(worst_rows[0]) if worst_rows else [
            "sample_id", "variant", "portfolio_size", "horizon", "portfolio_return",
        ]
        v103.write_csv(output / WORST_NAME, worst_rows, worst_fields)
        summary_frame = pd.DataFrame(summary_rows)
        pair_frame = pd.DataFrame(pair_rows)
        status, decision_text, facts = decision(
            summary_frame, leakage_failures, core_ok=True,
        )
        render_readme(
            output, run_id, status, decision_text, samples, summary_frame,
            pair_frame, leakage_failures, facts,
        )
    except Exception as exc:
        samples, rows, leakage_failures = [], [], 0
        status, decision_text = FAIL_BLOCKER, "STOP_REPAIR_EXECUTION_OR_DATA_BLOCKER"
        v103.write_json(output / CONFIG_NAME, {
            "stage": STAGE, "run_id": run_id, "execution_error": str(exc),
            "official_adoption_allowed": False, "broker_action_allowed": False,
            "research_only": True,
        })
        for name, fields in (
            (SAMPLE_NAME, ["sample_id", "seed", "draw_index", "start_date"]),
            (ROWS_NAME, v103.ROW_FIELDS), (SUMMARY_NAME, SUMMARY_FIELDS),
            (PAIRWISE_NAME, PAIRWISE_FIELDS), (BENCHMARK_NAME, BENCHMARK_FIELDS),
            (LEAKAGE_NAME, ["sample_id", "point_in_time_valid", "leakage_violation_reason"]),
            (WORST_NAME, ["sample_id", "variant", "portfolio_return"]),
        ):
            v103.write_csv(output / name, [], fields)
        warnings.append({
            "warning_code": "EXECUTION_BLOCKER", "severity": "HIGH",
            "scope": "STAGE", "details": str(exc), "research_only": "TRUE",
        })
        v103.write_csv(
            output / WARNING_NAME, warnings,
            ["warning_code", "severity", "scope", "details", "research_only"],
        )
        (output / README_NAME).write_text(
            f"# V21.104 Hold Full Run\n\nFINAL_STATUS: `{status}`  \n"
            f"DECISION: `{decision_text}`  \nrun_id: `{run_id}`  \n"
            "official_adoption_allowed: `false`  \nbroker_action_allowed: `false`\n\n"
            f"Blocking error: {exc}\n",
            encoding="utf-8",
        )
    after = {path: v103.sha256(path) for path in protected}
    changed = [path for path in protected if before[path] != after[path]]
    if changed:
        status, decision_text = FAIL_BLOCKER, "STOP_PROTECTED_OUTPUT_MUTATION_DETECTED"
        with (output / README_NAME).open("a", encoding="utf-8") as handle:
            handle.write("\nProtected output mutation detected; final status forced to FAIL.\n")
    result = {
        "FINAL_STATUS": status, "DECISION": decision_text, "RUN_ID": run_id,
        "SAMPLE_COUNT": len(samples), "ROW_COUNT": len(rows),
        "LEAKAGE_FAILURE_COUNT": leakage_failures,
        "PROTECTED_OUTPUTS_MODIFIED": bool(changed),
        "OUTPUT_DIR": output.as_posix(), "OFFICIAL_ADOPTION_ALLOWED": False,
        "BROKER_ACTION_ALLOWED": False,
    }
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output = output_path(args.root.resolve(), args.output_dir, run_id)
    result = run_stage(args.root, output, run_id)
    return 1 if str(result["FINAL_STATUS"]).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
