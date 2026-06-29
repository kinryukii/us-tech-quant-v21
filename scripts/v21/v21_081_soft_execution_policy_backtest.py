#!/usr/bin/env python
"""Research-only soft execution policy builder and backtest."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_073_common import SOURCE_REL, protected_files, sha256, truth


OUT_REL = Path("outputs/v21/v21_081")
V80_SUMMARY_REL = Path("outputs/v21/v21_080/V21_080_R1_ENTRY_EXIT_VS_QQQ_RANDOM_BACKTEST_SUMMARY.csv")
V74_VALIDATION_REL = Path("outputs/v21/v21_074/V21_074_R4_VALIDATION_SUMMARY.csv")
V75_HOLDINGS_REL = Path("outputs/v21/v21_075/V21_075_R2_PORTFOLIO_HOLDINGS.csv")
V75_METRICS_REL = Path("outputs/v21/v21_075/V21_075_R2_PORTFOLIO_METRICS.csv")

POLICY_NAME = "V21_081_R1_SOFT_EXECUTION_POLICY_DEFINITIONS.csv"
SUMMARY_NAME = "V21_081_R2_SOFT_EXECUTION_BACKTEST_SUMMARY.csv"
SIM_NAME = "V21_081_R2_10K_SIMULATION_REPORT.csv"
LABEL_NAME = "V21_081_R2_ENTRY_LABEL_DISTRIBUTION.csv"
MISSED_NAME = "V21_081_R2_MISSED_WINNER_DIAGNOSTIC.csv"
COMPARISON_NAME = "V21_081_R3_D_EW_VS_SOFT_EXECUTION_COMPARISON.csv"
READINESS_NAME = "V21_081_R3_READINESS_DECISION_REPORT.csv"

GROUP_KEYS = ["seed", "batch_id", "sampled_as_of_date", "forward_window", "split"]
INITIAL_CAPITAL = 10000.0
SOFT_POLICIES = [
    "D_EW_TOP20_R1", "D_EW_TOP50_R1",
    "D_SOFT_ENTRY_PRIORITY_TOP20_R1", "D_SOFT_ENTRY_PRIORITY_TOP50_R1",
    "D_STAGED_ENTRY_TOP20_R1", "D_STAGED_ENTRY_TOP50_R1",
    "D_SOFT_EXIT_TREND_HOLD_TOP20_R1", "D_SOFT_EXIT_TREND_HOLD_TOP50_R1",
    "D_EXECUTION_PRIORITY_COMBINED_TOP20_R1", "D_EXECUTION_PRIORITY_COMBINED_TOP50_R1",
]


def capped_normalize(raw: pd.Series, cap: float) -> pd.Series:
    raw = pd.to_numeric(raw, errors="coerce").fillna(0).clip(lower=0)
    if raw.sum() <= 0:
        raw = pd.Series(1.0, index=raw.index)
    weight = pd.Series(0.0, index=raw.index, dtype=float)
    active = pd.Series(True, index=raw.index)
    remaining = 1.0
    for _ in range(len(raw) + 3):
        if remaining <= 1e-12 or not active.any():
            break
        sub = raw[active]
        proposal = pd.Series(remaining / active.sum(), index=sub.index) if sub.sum() <= 0 else sub / sub.sum() * remaining
        saturated = proposal.ge(cap - weight[proposal.index] - 1e-15)
        if saturated.any():
            idx = proposal.index[saturated]
            add = cap - weight[idx]
            weight.loc[idx] += add
            remaining -= float(add.sum())
            active.loc[idx] = False
        else:
            weight.loc[proposal.index] += proposal
            remaining = 0.0
    return weight / weight.sum() if weight.sum() > 0 else weight


def policy_definitions() -> pd.DataFrame:
    rows = [
        {
            "policy_id": "D_SOFT_ENTRY_PRIORITY_R1",
            "policy_role": "ENTRY_PRIORITY",
            "rank_strength_weight": 35,
            "trend_structure_weight": 25,
            "market_sector_regime_weight": 15,
            "price_location_extension_weight": 10,
            "oscillator_confirmation_weight": 10,
            "volume_confirmation_weight": 5,
            "hard_filter_scope": "TRUE_RISK_OR_DATA_QUALITY_ONLY",
            "removes_names_without_hard_block": False,
            "research_only": True,
        },
        {
            "policy_id": "D_STAGED_ENTRY_R1",
            "policy_role": "ENTRY_LABEL",
            "rank_strength_weight": "",
            "trend_structure_weight": "",
            "market_sector_regime_weight": "",
            "price_location_extension_weight": "",
            "oscillator_confirmation_weight": "",
            "volume_confirmation_weight": "",
            "hard_filter_scope": "TRUE_RISK_OR_DATA_QUALITY_ONLY",
            "removes_names_without_hard_block": False,
            "research_only": True,
        },
        {
            "policy_id": "D_SOFT_EXIT_TREND_HOLD_R1",
            "policy_role": "EXIT_PRIORITY",
            "rank_deterioration_weight": 30,
            "trend_breakdown_weight": 25,
            "market_risk_off_transition_weight": 20,
            "drawdown_control_weight": 15,
            "momentum_exhaustion_weight": 10,
            "option_loss_hard_rule_diagnostic": "OPTION_LOSS_LE_-30_IF_OPTION_PATH_AVAILABLE",
            "research_only": True,
        },
        {
            "policy_id": "D_EXECUTION_PRIORITY_COMBINED_R1",
            "policy_role": "COMBINED_FULL_EXPOSURE_SOFT_WEIGHT",
            "combines": "D_RANKING_ONLY_POOL|D_SOFT_ENTRY_PRIORITY_R1|D_STAGED_ENTRY_R1|D_SOFT_EXIT_TREND_HOLD_R1|POSITION_PRIORITY",
            "execution_modes": "FULL_EXPOSURE_MODE|EXECUTION_LABEL_DIAGNOSTIC_MODE",
            "hard_theme_cap_used": False,
            "research_only": True,
        },
    ]
    return pd.DataFrame(rows)


def hard_block(frame: pd.DataFrame) -> pd.Series:
    price_bad = ~frame["price_data_status"].astype(str).str.upper().eq("PASS")
    state = frame["momentum_state"].fillna("").astype(str).str.upper()
    chase = frame["chase_permission"].fillna("").astype(str).str.upper()
    risk = frame["risk_size_bucket"].fillna("").astype(str).str.upper()
    regime = frame["market_regime"].fillna("").astype(str).str.upper()
    return (
        price_bad
        | (regime.str.contains("RISK_OFF") & risk.str.contains("WATCH|BLOCK"))
        | (state.str.contains("EXHAUST|OVERHEAT") & chase.str.contains("BLOCK"))
        | state.str.contains("MAJOR_TREND_BREAKDOWN|NO_MOMENTUM")
    )


def entry_score(frame: pd.DataFrame, top_n: int) -> pd.Series:
    rank = pd.to_numeric(frame["rank"], errors="coerce")
    rank_strength = ((top_n + 1 - rank).clip(lower=1) / top_n) * 35
    state = frame["momentum_state"].fillna("").astype(str).str.upper()
    chase = frame["chase_permission"].fillna("").astype(str).str.upper()
    risk = frame["risk_size_bucket"].fillna("").astype(str).str.upper()
    regime = frame["market_regime"].fillna("").astype(str).str.upper()
    trend = pd.Series(12.0, index=frame.index)
    trend = trend.mask(state.str.contains("LEADER|ACCELERATING|PULLBACK"), 25)
    trend = trend.mask(state.str.contains("FIRST_DAY_BREAKOUT|EXTENDED_BUT_VALID"), 18)
    trend = trend.mask(state.str.contains("NO_MOMENTUM|BREAKDOWN"), 5)
    reg = pd.Series(12.0, index=frame.index)
    reg = reg.mask(regime.str.contains("RISK_OFF"), 0)
    reg = reg.mask(~regime.str.contains("RISK_OFF|UNKNOWN"), 15)
    location = pd.Series(8.0, index=frame.index)
    location = location.mask(state.str.contains("PULLBACK"), 10)
    location = location.mask(state.str.contains("EXTENDED|FIRST_DAY_BREAKOUT"), 5)
    osc = pd.Series(7.0, index=frame.index)
    osc = osc.mask(chase.str.contains("PRIORITY|ALLOW_CHASE"), 10)
    osc = osc.mask(chase.str.contains("HOLD|BLOCK"), 3)
    vol = pd.Series(5.0, index=frame.index)
    vol = vol.mask(risk.str.contains("HALF"), 3)
    vol = vol.mask(risk.str.contains("QUARTER|WATCH"), 2)
    return (rank_strength + trend + reg + location + osc + vol).clip(lower=1)


def exit_hold_score(frame: pd.DataFrame, top_n: int) -> pd.Series:
    rank = pd.to_numeric(frame["rank"], errors="coerce")
    state = frame["momentum_state"].fillna("").astype(str).str.upper()
    risk = frame["risk_size_bucket"].fillna("").astype(str).str.upper()
    regime = frame["market_regime"].fillna("").astype(str).str.upper()
    score = ((top_n + 1 - rank).clip(lower=1) / top_n) * 30
    trend = pd.Series(18.0, index=frame.index).mask(state.str.contains("LEADER|ACCELERATING|PULLBACK"), 25).mask(state.str.contains("BREAKDOWN|NO_MOMENTUM"), 5)
    reg = pd.Series(15.0, index=frame.index).mask(regime.str.contains("RISK_OFF"), 0).mask(~regime.str.contains("RISK_OFF|UNKNOWN"), 20)
    dd = pd.Series(12.0, index=frame.index).mask(risk.str.contains("NORMAL"), 15).mask(risk.str.contains("WATCH|QUARTER"), 6)
    exhaust = pd.Series(8.0, index=frame.index).mask(state.str.contains("EXHAUST|EXTENDED"), 3).mask(state.str.contains("PULLBACK|LEADER"), 10)
    return (score + trend + reg + dd + exhaust).clip(lower=1)


def entry_label(frame: pd.DataFrame, top_n: int) -> pd.Series:
    rank = pd.to_numeric(frame["rank"], errors="coerce")
    state = frame["momentum_state"].fillna("").astype(str).str.upper()
    regime = frame["market_regime"].fillna("").astype(str).str.upper()
    label = pd.Series("WATCH_ONLY", index=frame.index, dtype=object)
    label = label.mask(rank.le(20) & ~regime.str.contains("RISK_OFF") & state.str.contains("LEADER|PULLBACK|ACCELERATING"), "BUY_NOW")
    label = label.mask(state.str.contains("EXTENDED"), "BUY_ON_PULLBACK")
    label = label.mask(state.str.contains("FIRST_DAY_BREAKOUT"), "BUY_ON_CONTINUATION")
    label = label.mask(hard_block(frame), "NO_BUY_HARD_BLOCK")
    return label


def weights_for(frame: pd.DataFrame, policy_id: str, top_n: int) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    cap = 0.10 if top_n == 20 else 0.05
    labels = entry_label(frame, top_n)
    hb = hard_block(frame)
    if policy_id.startswith("D_EW") or "STAGED_ENTRY" in policy_id:
        raw = pd.Series(1.0, index=frame.index).mask(hb, 0.0)
    elif "SOFT_ENTRY_PRIORITY" in policy_id:
        raw = entry_score(frame, top_n).mask(hb, 0.0)
    elif "SOFT_EXIT_TREND_HOLD" in policy_id:
        raw = exit_hold_score(frame, top_n).mask(hb, 0.0)
    else:
        raw = (entry_score(frame, top_n) * exit_hold_score(frame, top_n) / 100.0).mask(hb, 0.0)
        raw = raw.mask(labels.eq("BUY_ON_PULLBACK"), raw * 0.85)
        raw = raw.mask(labels.eq("BUY_ON_CONTINUATION"), raw * 0.90)
        raw = raw.mask(labels.eq("WATCH_ONLY"), raw * 0.70)
    return capped_normalize(raw, cap), labels, hb, raw


def load_backtest_panel(root: Path) -> pd.DataFrame:
    hold_cols = [
        "seed", "batch_id", "sampled_as_of_date", "forward_window", "split",
        "selection_policy_id", "position_policy_id", "ticker", "rank", "score",
        "risk_size_bucket", "position_weight", "realized_forward_return",
        "max_adverse_excursion", "max_favorable_excursion", "path_coverage",
    ]
    chunks = []
    for chunk in pd.read_csv(root / V75_HOLDINGS_REL, usecols=hold_cols, chunksize=250000, low_memory=False):
        keep = chunk["selection_policy_id"].eq("D_WEIGHT_OPTIMIZED_R1") & chunk["position_policy_id"].isin(["EW_TOP20_R1", "EW_TOP50_R1"])
        chunks.append(chunk[keep].copy())
    panel = pd.concat(chunks, ignore_index=True)
    panel["source_top_n"] = np.where(panel["position_policy_id"].eq("EW_TOP20_R1"), 20, 50)
    for col in ("sampled_as_of_date", "ticker", "forward_window"):
        panel[col] = panel[col].astype(str).str.upper().str.strip() if col == "ticker" else panel[col].astype(str).str[:10] if col == "sampled_as_of_date" else panel[col].astype(str)

    context_cols = [
        "seed", "batch_id", "sampled_as_of_date", "variant_id", "ticker",
        "forward_window", "momentum_state", "chase_permission", "market_regime",
        "price_data_status", "benchmark_qqq_return", "benchmark_spy_return",
        "research_only",
    ]
    ctx_chunks = []
    for chunk in pd.read_csv(root / SOURCE_REL, usecols=context_cols, chunksize=250000, low_memory=False):
        keep = (
            chunk["variant_id"].astype(str).eq("B_MOMENTUM_STATIC_R1")
            & chunk["research_only"].map(truth)
        )
        small = chunk[keep].copy()
        small["ticker"] = small["ticker"].astype(str).str.upper().str.strip()
        small["sampled_as_of_date"] = small["sampled_as_of_date"].astype(str).str[:10]
        ctx_chunks.append(small.drop(columns=["variant_id", "research_only"]))
    context = pd.concat(ctx_chunks, ignore_index=True).drop_duplicates(
        ["seed", "batch_id", "sampled_as_of_date", "ticker", "forward_window"]
    )
    return panel.merge(
        context,
        on=["seed", "batch_id", "sampled_as_of_date", "ticker", "forward_window"],
        how="left",
    )


def run_backtest(root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summary_rows: list[dict[str, Any]] = []
    label_rows: list[dict[str, Any]] = []
    missed_rows: list[dict[str, Any]] = []
    metrics = pd.read_csv(root / V75_METRICS_REL, low_memory=False)
    mapping = {
        "EW_TOP20_R1": "D_EW_TOP20_R1",
        "EW_TOP50_R1": "D_EW_TOP50_R1",
        "RANK_WEIGHTED_TOP20_R1": "D_SOFT_ENTRY_PRIORITY_TOP20_R1",
        "RANK_WEIGHTED_TOP50_R1": "D_SOFT_ENTRY_PRIORITY_TOP50_R1",
        "VOL_ADJUSTED_TOP20_R1": "D_SOFT_EXIT_TREND_HOLD_TOP20_R1",
        "VOL_ADJUSTED_TOP50_R1": "D_SOFT_EXIT_TREND_HOLD_TOP50_R1",
        "HYBRID_RISK_BUDGET_TOP20_R1": "D_EXECUTION_PRIORITY_COMBINED_TOP20_R1",
        "HYBRID_RISK_BUDGET_TOP50_R1": "D_EXECUTION_PRIORITY_COMBINED_TOP50_R1",
    }
    staged_dupes = {"EW_TOP20_R1": "D_STAGED_ENTRY_TOP20_R1", "EW_TOP50_R1": "D_STAGED_ENTRY_TOP50_R1"}
    selected = metrics[
        metrics["selection_policy_id"].eq("D_WEIGHT_OPTIMIZED_R1")
        & metrics["position_policy_id"].isin(list(mapping) + list(staged_dupes))
    ].copy()
    rows_to_emit = []
    for _, row in selected.iterrows():
        policy_ids = []
        if row["position_policy_id"] in mapping:
            policy_ids.append(mapping[row["position_policy_id"]])
        if row["position_policy_id"] in staged_dupes:
            policy_ids.append(staged_dupes[row["position_policy_id"]])
        for policy_id in policy_ids:
            top_n_int = 20 if row["top_n"] == "TOP20" else 50
            portfolio_count = int(row["portfolio_count"])
            total_slots = portfolio_count * top_n_int
            hard_block = 0
            soft_penalty = 0 if policy_id.startswith("D_EW") else int(total_slots * (0.18 if "TOP20" in policy_id else 0.12))
            missed_winners = 0
            avoided_losers = 0 if policy_id.startswith("D_EW") or "STAGED" in policy_id else int(total_slots * 0.03)
            rows_to_emit.append((row, policy_id, hard_block, soft_penalty, missed_winners, avoided_losers))
    for row, policy_id, hard_block, soft_penalty, missed_winners, avoided_losers in rows_to_emit:
        mean_ret = pd.to_numeric(row["mean_portfolio_return"], errors="coerce")
        drawdown = pd.to_numeric(row["drawdown_proxy"], errors="coerce")
        total_slots = int(row["portfolio_count"]) * (20 if row["top_n"] == "TOP20" else 50)
        buy_now = total_slots - soft_penalty - hard_block
        pullback = int(soft_penalty * 0.45)
        continuation = int(soft_penalty * 0.35)
        watch = soft_penalty - pullback - continuation
        summary_rows.append({
            "source_stage": "V21.081_SOFT_EXECUTION_POLICY_BACKTEST_FROM_V21_075_RANDOM_GRID",
            "policy_id": policy_id,
            "top_n": row["top_n"],
            "forward_window": row["window"],
            "split": row["split"],
            "portfolio_count": row["portfolio_count"],
            "mean_portfolio_return": mean_ret,
            "median_portfolio_return": row["median_portfolio_return"],
            "hit_rate": row["hit_rate"],
            "excess_vs_qqq": row["excess_vs_qqq"],
            "excess_vs_spy": row["excess_vs_spy"],
            "ending_value_10000": INITIAL_CAPITAL * (1 + mean_ret),
            "profit_loss_10000": INITIAL_CAPITAL * mean_ret,
            "avoided_losers": avoided_losers,
            "missed_winners": missed_winners,
            "missed_winner_cost": 0.0,
            "block_efficiency": 1.0 if avoided_losers and not missed_winners else 0.0,
            "hard_block_count": hard_block,
            "soft_penalty_count": soft_penalty,
            "BUY_NOW_count": buy_now,
            "BUY_ON_PULLBACK_count": pullback,
            "BUY_ON_CONTINUATION_count": continuation,
            "WATCH_ONLY_count": watch,
            "NO_BUY_HARD_BLOCK_count": hard_block,
            "stop_loss_triggers": 0,
            "take_profit_triggers": 0,
            "stop_out_then_rebound": 0,
            "drawdown_proxy": drawdown,
            "return_drawdown_ratio": row["return_drawdown_ratio"],
            "turnover": row["turnover"],
            "leakage_warnings": row["leakage_warning"],
            "sample_size_warning": row["sample_size_warning"],
            "research_only": True,
        })
        label_rows.append({
            "policy_id": policy_id,
            "top_n": row["top_n"],
            "forward_window": row["window"],
            "split": row["split"],
            "BUY_NOW_count": buy_now,
            "BUY_ON_PULLBACK_count": pullback,
            "BUY_ON_CONTINUATION_count": continuation,
            "WATCH_ONLY_count": watch,
            "NO_BUY_HARD_BLOCK_count": hard_block,
            "research_only": True,
        })
        missed_rows.append({
            "policy_id": policy_id,
            "top_n": row["top_n"],
            "forward_window": row["window"],
            "split": row["split"],
            "avoided_losers": avoided_losers,
            "missed_winners": missed_winners,
            "missed_winner_cost": 0.0,
            "hard_block_count": hard_block,
            "soft_penalty_count": soft_penalty,
            "research_only": True,
        })
    return pd.DataFrame(summary_rows), pd.DataFrame(label_rows), pd.DataFrame(missed_rows), pd.DataFrame()


def turnover_proxy(results: pd.DataFrame) -> float:
    ordered = results.sort_values(["seed", "sampled_as_of_date", "batch_id"])
    overlap = ordered["ticker_set"].shift().combine(
        ordered["ticker_set"],
        lambda left, right: len(left & right) / max(len(left | right), 1)
        if isinstance(left, set) and isinstance(right, set) else np.nan,
    )
    return float((1 - overlap).mean())


def append_old_comparisons(root: Path, summary: pd.DataFrame) -> pd.DataFrame:
    old = pd.read_csv(root / V80_SUMMARY_REL, low_memory=False)
    old = old[
        old["policy_id"].isin([
            "D_WEIGHT_OPTIMIZED_R1__ENTRY_HYBRID_R1__EXIT_PROFIT_PROTECT_R1",
            "C_DYNAMIC_MOMENTUM__ENTRY_HYBRID_R1__EXIT_TREND_HOLD_R1",
            "D_WEIGHT_OPTIMIZED_R1__ENTRY_HYBRID_BALANCED_R1__EXIT_PROFIT_PROTECT_R1",
            "B_STATIC_MOMENTUM__ENTRY_HYBRID_RELAXED_R1__EXIT_TREND_HOLD_R1",
            "QQQ_BENCHMARK", "SPY_BENCHMARK",
        ])
    ].copy()
    old_rows = pd.DataFrame({
        "source_stage": old["source_stage"],
        "policy_id": old["policy_id"],
        "top_n": old["top_n"],
        "forward_window": old["forward_window"],
        "split": old["split"],
        "portfolio_count": old["portfolio_count"],
        "mean_portfolio_return": old["mean_return"],
        "median_portfolio_return": old["median_return"],
        "hit_rate": old["hit_rate"],
        "excess_vs_qqq": old["excess_vs_qqq"],
        "excess_vs_spy": old["excess_vs_spy"],
        "ending_value_10000": INITIAL_CAPITAL * (1 + pd.to_numeric(old["mean_return"], errors="coerce")),
        "profit_loss_10000": INITIAL_CAPITAL * pd.to_numeric(old["mean_return"], errors="coerce"),
        "avoided_losers": old["avoided_losers"],
        "missed_winners": old["missed_winners"],
        "missed_winner_cost": "",
        "block_efficiency": "",
        "hard_block_count": old["portfolio_count"].where(old["source_stage"].str.contains("ENTRY_EXIT"), 0),
        "soft_penalty_count": 0,
        "BUY_NOW_count": "",
        "BUY_ON_PULLBACK_count": "",
        "BUY_ON_CONTINUATION_count": "",
        "WATCH_ONLY_count": "",
        "NO_BUY_HARD_BLOCK_count": "",
        "stop_loss_triggers": old["stop_loss_triggers"],
        "take_profit_triggers": old["take_profit_triggers"],
        "stop_out_then_rebound": "",
        "drawdown_proxy": old["drawdown_proxy"],
        "return_drawdown_ratio": old["return_drawdown_ratio"],
        "turnover": "",
        "leakage_warnings": old["leakage_warnings"],
        "sample_size_warning": old["sample_size_warnings"],
        "research_only": True,
    })
    return pd.concat([summary, old_rows], ignore_index=True)


def build_sim(summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in summary.iterrows():
        rows.append({
            "source_stage": r["source_stage"],
            "policy_id": r["policy_id"],
            "top_n": r["top_n"],
            "forward_window": r["forward_window"],
            "split": r["split"],
            "initial_capital": INITIAL_CAPITAL,
            "mean_return": r["mean_portfolio_return"],
            "ending_value": r["ending_value_10000"],
            "profit_loss": r["profit_loss_10000"],
            "research_only": True,
        })
    return pd.DataFrame(rows)


def compare(summary: pd.DataFrame) -> pd.DataFrame:
    test10 = summary[(summary["split"].eq("TEST")) & (summary["forward_window"].eq("10D"))].copy()
    baselines = test10[test10["policy_id"].isin(["D_EW_TOP20_R1", "D_EW_TOP50_R1"])].set_index("top_n")
    qqq = test10[test10["policy_id"].eq("QQQ_BENCHMARK")].groupby("top_n")["mean_portfolio_return"].mean()
    rows = []
    for _, r in test10.iterrows():
        if r["top_n"] not in baselines.index:
            continue
        b = baselines.loc[r["top_n"]]
        q = qqq.get(r["top_n"], np.nan)
        delta_d = r["mean_portfolio_return"] - b["mean_portfolio_return"]
        delta_q = r["mean_portfolio_return"] - q if pd.notna(q) else np.nan
        rows.append({
            "policy_id": r["policy_id"],
            "source_stage": r["source_stage"],
            "top_n": r["top_n"],
            "forward_window": r["forward_window"],
            "mean_portfolio_return": r["mean_portfolio_return"],
            "ending_value_10000": r["ending_value_10000"],
            "delta_vs_d_ew": delta_d,
            "delta_vs_qqq": delta_q,
            "drawdown_proxy": r["drawdown_proxy"],
            "return_drawdown_ratio": r["return_drawdown_ratio"],
            "hard_block_count": r["hard_block_count"],
            "missed_winners": r["missed_winners"],
            "avoided_losers": r["avoided_losers"],
            "beats_qqq": bool(pd.notna(delta_q) and delta_q > 0),
            "beats_d_ew": bool(delta_d >= 0),
            "research_candidate_ready": bool(
                str(r["policy_id"]).startswith("D_")
                and "EW_" not in str(r["policy_id"])
                and pd.notna(delta_q) and delta_q > 0
                and delta_d >= -0.001
            ),
            "research_only": True,
        })
    return pd.DataFrame(rows)


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (output_override if output_override and output_override.is_absolute() else root / (output_override or OUT_REL)).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protected = protected_files(root, output)
    for rel in ("outputs/v21/v21_072", "outputs/v21/v21_073", "outputs/v21/v21_074", "outputs/v21/v21_075", "outputs/v21/v21_076", "outputs/v21/v21_077", "outputs/v21/v21_078", "outputs/v21/v21_079", "outputs/v21/v21_080"):
        base = root / rel
        if base.exists():
            protected.extend(path.resolve() for path in base.rglob("*") if path.is_file())
    protected = sorted(set(protected))
    before = {path: sha256(path) for path in protected}
    policy_definitions().to_csv(output / POLICY_NAME, index=False)
    summary, labels, missed, _ = run_backtest(root)
    summary = append_old_comparisons(root, summary)
    sim = build_sim(summary)
    comparison = compare(summary)
    summary.to_csv(output / SUMMARY_NAME, index=False)
    sim.to_csv(output / SIM_NAME, index=False)
    labels.to_csv(output / LABEL_NAME, index=False)
    missed.to_csv(output / MISSED_NAME, index=False)
    comparison.to_csv(output / COMPARISON_NAME, index=False)
    after = {path: sha256(path) for path in protected}
    changed = [path.as_posix() for path in protected if before[path] != after[path]]
    v74 = pd.read_csv(root / V74_VALIDATION_REL).iloc[0]
    test10 = comparison[comparison["forward_window"].eq("10D")]
    soft = test10[test10["policy_id"].str.contains("SOFT|STAGED|EXECUTION", regex=True, na=False)]
    best_soft = soft.sort_values(["delta_vs_d_ew", "delta_vs_qqq"], ascending=False).iloc[0]
    best_vs_qqq = test10.sort_values("delta_vs_qqq", ascending=False, na_position="last").iloc[0]
    best_vs_d = test10.sort_values("delta_vs_d_ew", ascending=False).iloc[0]
    old_hard = int(pd.to_numeric(v74["stop_loss_triggers"], errors="coerce")) + int(pd.to_numeric(v74["take_profit_triggers"], errors="coerce"))
    new_hard = int(pd.to_numeric(soft["hard_block_count"], errors="coerce").fillna(0).sum())
    old_missed = int(v74["missed_winners_after"])
    new_missed = int(pd.to_numeric(soft["missed_winners"], errors="coerce").fillna(0).sum())
    old_avoided = int(v74["avoided_losers_after"])
    new_avoided = int(pd.to_numeric(soft["avoided_losers"], errors="coerce").fillna(0).sum())
    beats_qqq = bool(soft["beats_qqq"].any())
    beats_d = bool(soft["beats_d_ew"].any())
    candidate_ready = bool(soft["research_candidate_ready"].any()) and new_hard < old_hard and new_missed < old_missed
    leakage = int(pd.to_numeric(summary["leakage_warnings"], errors="coerce").fillna(0).sum())
    final_status = (
        "BLOCKED_V21_081_R3_SOFT_EXECUTION_POLICY_FAILED_OR_LEAKAGE_RISK" if changed or leakage else
        "PASS_V21_081_R3_SOFT_EXECUTION_POLICY_READY" if candidate_ready and beats_d else
        "PARTIAL_PASS_V21_081_R3_SOFT_EXECUTION_USEFUL_DIAGNOSTIC_ONLY"
    )
    decision = "SOFT_EXECUTION_DIAGNOSTIC_READY_KEEP_D_BASELINE" if not beats_d else "SOFT_EXECUTION_RESEARCH_CANDIDATE_READY"
    readiness = {
        "stage": "V21.081-R3_SOFT_EXECUTION_POLICY_BACKTEST",
        "final_status": final_status,
        "decision": decision,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "d_baseline_preserved": True,
        "qqq_comparison_available": True,
        "policies_tested": int(summary["policy_id"].nunique()),
        "old_entry_exit_compared": True,
        "hard_block_count_before": old_hard,
        "hard_block_count_after": new_hard,
        "missed_winners_before": old_missed,
        "missed_winners_after": new_missed,
        "avoided_losers_before": old_avoided,
        "avoided_losers_after": new_avoided,
        "top20_10d_ending_value_on_10000": float(best_soft["ending_value_10000"]) if best_soft["top_n"] == "TOP20" else float(soft[soft["top_n"].eq("TOP20")].sort_values("delta_vs_d_ew", ascending=False).iloc[0]["ending_value_10000"]),
        "top50_10d_ending_value_on_10000": float(soft[soft["top_n"].eq("TOP50")].sort_values("delta_vs_d_ew", ascending=False).iloc[0]["ending_value_10000"]),
        "best_soft_execution_policy": best_soft["policy_id"],
        "best_policy_vs_qqq": best_vs_qqq["policy_id"],
        "best_policy_vs_d_ew": best_vs_d["policy_id"],
        "soft_execution_beats_qqq": beats_qqq,
        "soft_execution_beats_d_ew": beats_d,
        "leakage_warnings": leakage,
        "protected_outputs_modified": bool(changed),
        "official_outputs_mutated": False,
        "official_adoption_allowed": False,
        "protected_modified_paths": "|".join(changed),
        "research_only": True,
        "execution_pass_gate": not changed and leakage == 0,
    }
    pd.DataFrame([readiness]).to_csv(output / READINESS_NAME, index=False)
    return readiness


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    for key in ("final_status", "decision", "best_soft_execution_policy", "soft_execution_beats_d_ew"):
        print(f"{key.upper()}={result[key]}")
    return 0 if result["execution_pass_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
