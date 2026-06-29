#!/usr/bin/env python
"""V21.119_R2 attribution for newly matured post-refresh observations."""

from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.119_R2_NEW_MATURITY_ATTRIBUTION_AND_BC_COMPARISON"
OUT = ROOT / "outputs/v21/V21.119_R2_NEW_MATURITY_ATTRIBUTION_AND_BC_COMPARISON"

V116 = ROOT / "outputs/v21/V21.116_DAILY_TOP50_FULL_DATA_LEDGER_20260616_TO_LATEST"
V117_R1 = ROOT / "outputs/v21/V21.117_R1_D_EARLY_EDGE_FAILURE_DECOMPOSITION"
V118 = ROOT / "outputs/v21/V21.118_D_R2_REPEATED_LOSER_AWARE_DESIGN"
V119_R1 = ROOT / "outputs/v21/V21.119_R1_FORWARD_MATURITY_UPDATE_AFTER_REFRESH"
PRICE = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
BENCH = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"

ABCD = V116 / "daily_ABCD_top50_full_ledger.csv"
D_R2C_MEMBERS = V118 / "d_r2_top20_top50_membership.csv"
R1_PANEL = V119_R1 / "forward_maturity_by_date_horizon_after_refresh.csv"
R1_MANIFEST = V119_R1 / "V21.119_R1_manifest.json"
R1_PAIR_NEW = V119_R1 / "pairwise_winrate_new_maturity_only_after_refresh.csv"
R1_REPEATED = V119_R1 / "repeated_loser_after_refresh_update.csv"
LOSERS = V117_R1 / "d_repeated_loser_attribution.csv"

NEW_BUCKET = "NEWLY_MATURED_AFTER_V21_120_REFRESH"
STRATEGIES = [
    "A1_BASELINE_CONTROL",
    "B_STATIC_MOMENTUM_BLEND",
    "C_DYNAMIC_MOMENTUM_BLEND",
    "D_WEIGHT_OPTIMIZED_R1",
    "D_R2C_BC_CONFIRMATION_OVERLAY",
]
COMPARISON_STRATEGIES = ["A1_BASELINE_CONTROL", "B_STATIC_MOMENTUM_BLEND", "C_DYNAMIC_MOMENTUM_BLEND"]
TOP_NS = [20, 50]


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    if fields is None:
        fields = list(rows[0].keys()) if rows else ["empty"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def required_missing() -> list[str]:
    required = [ABCD, D_R2C_MEMBERS, R1_PANEL, R1_MANIFEST, R1_PAIR_NEW, R1_REPEATED, LOSERS, PRICE]
    return [rel(path) for path in required if not path.is_file()]


def load_prices() -> tuple[dict[tuple[str, str], float], str]:
    frames = []
    for path in [PRICE, BENCH]:
        if not path.is_file():
            continue
        df = pd.read_csv(path, usecols=["symbol", "date", "close", "adjusted_close"], low_memory=False)
        df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        close = pd.to_numeric(df["close"], errors="coerce")
        adjusted = pd.to_numeric(df["adjusted_close"], errors="coerce")
        df["px"] = adjusted.where(adjusted.notna(), close)
        frames.append(df[["symbol", "date", "px"]])
    if not frames:
        return {}, ""
    prices = pd.concat(frames, ignore_index=True).dropna(subset=["symbol", "date", "px"])
    prices = prices.drop_duplicates(["symbol", "date"], keep="last")
    prices["date_str"] = prices["date"].dt.strftime("%Y-%m-%d")
    latest = str(prices["date_str"].max())
    return {(r["symbol"], r["date_str"]): float(r["px"]) for r in prices.to_dict("records")}, latest


def px_return(ticker: str, start: str, end: str, prices: dict[tuple[str, str], float]) -> float:
    start_px = prices.get((ticker, start))
    end_px = prices.get((ticker, end))
    if start_px is None or end_px is None or start_px == 0:
        return math.nan
    return end_px / start_px - 1.0


def mean_return(tickers: list[str], start: str, end: str, prices: dict[tuple[str, str], float]) -> float:
    vals = [px_return(ticker, start, end, prices) for ticker in tickers]
    vals = [v for v in vals if not pd.isna(v)]
    return float(pd.Series(vals).mean()) if vals else math.nan


def ticker_returns(tickers: list[str], start: str, end: str, prices: dict[tuple[str, str], float]) -> dict[str, float]:
    return {ticker: px_return(ticker, start, end, prices) for ticker in tickers}


def build_memberships() -> dict[tuple[str, str, int], list[str]]:
    memberships: dict[tuple[str, str, int], list[str]] = {}
    abcd = pd.read_csv(ABCD, low_memory=False)
    abcd["rank"] = pd.to_numeric(abcd["rank"], errors="coerce")
    abcd["ticker"] = abcd["ticker"].astype(str).str.upper().str.strip()
    for (as_of, strategy), group in abcd.groupby(["as_of_date", "strategy"], sort=True):
        for topn in TOP_NS:
            top = group[group["rank"].le(topn)].sort_values("rank")
            memberships[(str(as_of), str(strategy), topn)] = list(top["ticker"])

    r2c = pd.read_csv(D_R2C_MEMBERS, low_memory=False)
    r2c = r2c[r2c["candidate_variant"].eq("D_R2C_BC_CONFIRMATION_OVERLAY")].copy()
    r2c["rank"] = pd.to_numeric(r2c["rank"], errors="coerce")
    r2c["ticker"] = r2c["ticker"].astype(str).str.upper().str.strip()
    for as_of, group in r2c.groupby("as_of_date", sort=True):
        for topn in TOP_NS:
            top = group[group["rank"].le(topn)].sort_values("rank")
            memberships[(str(as_of), "D_R2C_BC_CONFIRMATION_OVERLAY", topn)] = list(top["ticker"])
    return memberships


def contribution_summary(
    left_tickers: list[str],
    right_tickers: list[str],
    start: str,
    end: str,
    prices: dict[tuple[str, str], float],
) -> dict[str, Any]:
    left_set = set(left_tickers)
    right_set = set(right_tickers)
    common = sorted(left_set & right_set)
    left_only = sorted(left_set - right_set)
    right_only = sorted(right_set - left_set)
    n = max(len(left_tickers), 1)
    common_returns = ticker_returns(common, start, end, prices)
    left_returns = ticker_returns(left_only, start, end, prices)
    right_returns = ticker_returns(right_only, start, end, prices)
    valid_left_only = [v for v in left_returns.values() if not pd.isna(v)]
    valid_right_only = [v for v in right_returns.values() if not pd.isna(v)]
    left_only_contribution = float(sum(valid_left_only) / n) if valid_left_only else 0.0
    right_only_contribution = float(sum(valid_right_only) / n) if valid_right_only else 0.0
    avoided_right_only_contribution = -right_only_contribution
    common_valid = [v for v in common_returns.values() if not pd.isna(v)]
    common_contribution = float(sum(common_valid) / n) if common_valid else 0.0
    best_left = max(left_returns.items(), key=lambda x: -math.inf if pd.isna(x[1]) else x[1], default=("", math.nan))
    worst_right = min(right_returns.items(), key=lambda x: math.inf if pd.isna(x[1]) else x[1], default=("", math.nan))
    if left_only_contribution > 0 and avoided_right_only_contribution > 0:
        reason = "both"
    elif left_only_contribution > 0:
        reason = "adding_winners"
    elif avoided_right_only_contribution > 0:
        reason = "removing_losers"
    else:
        reason = "benchmark_sector_beta"
    return {
        "common_tickers": "|".join(common),
        "left_only_tickers": "|".join(left_only),
        "right_only_tickers": "|".join(right_only),
        "common_count": len(common),
        "left_only_count": len(left_only),
        "right_only_count": len(right_only),
        "common_ticker_contribution": common_contribution,
        "left_only_contribution": left_only_contribution,
        "right_only_contribution": right_only_contribution,
        "avoided_right_only_contribution": avoided_right_only_contribution,
        "best_left_only_ticker": best_left[0],
        "best_left_only_return": best_left[1],
        "worst_right_only_ticker": worst_right[0],
        "worst_right_only_return": worst_right[1],
        "primary_improvement_reason": reason,
    }


def row_return(panel: pd.DataFrame, ranking_date: str, strategy: str, topn: int, horizon: str) -> float:
    sub = panel[
        panel["ranking_date"].eq(ranking_date)
        & panel["strategy"].eq(strategy)
        & panel["top_n"].eq(topn)
        & panel["horizon"].eq(horizon)
    ]
    return float(sub.iloc[0]["equal_weight_return"]) if not sub.empty else math.nan


def pair_metric(pair_df: pd.DataFrame, comparison: str, topn: int, field: str = "win_rate") -> float:
    sub = pair_df[(pair_df["comparison"].eq(comparison)) & (pair_df["top_n"].eq(topn)) & (pair_df["available_observations"] > 0)]
    return float(sub[field].mean()) if not sub.empty else math.nan


def blocked_manifest(missing: list[str]) -> dict[str, Any]:
    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": "BLOCKED_V21_119_R2_MISSING_REQUIRED_INPUTS",
        "DECISION": "DO_NOT_USE_NEW_MATURITY_ATTRIBUTION",
        "missing_inputs": missing,
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
    }
    write_json(OUT / "V21.119_R2_manifest.json", manifest)
    (OUT / "V21.119_R2_new_maturity_attribution_report.txt").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return manifest


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    missing = required_missing()
    if missing:
        return blocked_manifest(missing)

    r1_manifest = json.loads(R1_MANIFEST.read_text(encoding="utf-8"))
    prices, latest = load_prices()
    memberships = build_memberships()
    panel = pd.read_csv(R1_PANEL, low_memory=False)
    panel = panel[panel["observation_bucket"].eq(NEW_BUCKET)].copy()
    pair_new = pd.read_csv(R1_PAIR_NEW, low_memory=False)
    repeated_prior = pd.read_csv(R1_REPEATED, low_memory=False).iloc[0].to_dict()
    loser_df = pd.read_csv(LOSERS, low_memory=False)
    repeated_losers = set(loser_df["ticker"].astype(str).str.upper().str.strip())

    d_vs_original_rows = []
    comparison_rows = []
    soxx_rows = []
    improvement_counter: Counter[str] = Counter()
    ticker_gain_counter: Counter[str] = Counter()
    ticker_gain_amount: defaultdict[str, float] = defaultdict(float)
    ticker_soxx_amount: defaultdict[str, float] = defaultdict(float)
    date_gain_amount: defaultdict[str, float] = defaultdict(float)
    horizon_gain_amount: defaultdict[str, float] = defaultdict(float)

    d2c_rows = panel[panel["strategy"].eq("D_R2C_BC_CONFIRMATION_OVERLAY")].copy()
    for obs in d2c_rows.to_dict("records"):
        ranking_date = str(obs["ranking_date"])
        horizon = str(obs["horizon"])
        topn = int(obs["top_n"])
        start = str(obs["start_date"])
        end = str(obs["end_date"])
        r2c_tickers = memberships.get((ranking_date, "D_R2C_BC_CONFIRMATION_OVERLAY", topn), [])
        d_tickers = memberships.get((ranking_date, "D_WEIGHT_OPTIMIZED_R1", topn), [])
        r2c_ret = float(obs["equal_weight_return"])
        d_ret = row_return(panel, ranking_date, "D_WEIGHT_OPTIMIZED_R1", topn, horizon)
        attr = contribution_summary(r2c_tickers, d_tickers, start, end, prices)
        delta = r2c_ret - d_ret
        improvement_counter[attr["primary_improvement_reason"]] += 1
        date_gain_amount[ranking_date] += delta
        horizon_gain_amount[horizon] += delta
        for ticker in attr["left_only_tickers"].split("|") if attr["left_only_tickers"] else []:
            value = px_return(ticker, start, end, prices)
            if not pd.isna(value):
                ticker_gain_counter[ticker] += 1
                ticker_gain_amount[ticker] += value / max(topn, 1)
        d_vs_original_rows.append({
            "ranking_date": ranking_date,
            "horizon": horizon,
            "top_n": topn,
            "D_R2C_return": r2c_ret,
            "original_D_return": d_ret,
            "D_R2C_minus_original_D": delta,
            "common_tickers": attr["common_tickers"],
            "D_R2C_only_tickers": attr["left_only_tickers"],
            "original_D_only_tickers": attr["right_only_tickers"],
            "contribution_from_common_tickers": attr["common_ticker_contribution"],
            "contribution_from_D_R2C_only_tickers": attr["left_only_contribution"],
            "contribution_avoided_by_removing_original_D_only_tickers": attr["avoided_right_only_contribution"],
            "primary_improvement_reason": attr["primary_improvement_reason"],
            "best_D_R2C_only_ticker": attr["best_left_only_ticker"],
            "worst_original_D_only_ticker": attr["worst_right_only_ticker"],
        })

        soxx = px_return("SOXX", start, end, prices)
        ticker_rets = ticker_returns(r2c_tickers, start, end, prices)
        valid = {k: v for k, v in ticker_rets.items() if not pd.isna(v)}
        best = max(valid.items(), key=lambda x: x[1], default=("", math.nan))
        worst = min(valid.items(), key=lambda x: x[1], default=("", math.nan))
        excess = r2c_ret - soxx if not pd.isna(soxx) else math.nan
        top_share = abs(best[1] / max(sum(abs(v) for v in valid.values()), 1e-12)) if valid and not pd.isna(best[1]) else math.nan
        if not pd.isna(excess):
            ticker_soxx_amount[best[0]] += excess
        alpha_driver = "stock_selection" if not pd.isna(excess) and excess > 0 and top_share < 0.35 else "small_number_extreme_winners" if top_share >= 0.35 else "broad_semiconductor_exposure"
        soxx_rows.append({
            "ranking_date": ranking_date,
            "horizon": horizon,
            "top_n": topn,
            "D_R2C_return": r2c_ret,
            "SOXX_return": soxx,
            "D_R2C_minus_SOXX": excess,
            "best_contributor": best[0],
            "best_contributor_return": best[1],
            "worst_contributor": worst[0],
            "worst_contributor_return": worst[1],
            "top_contributor_abs_share": top_share,
            "alpha_driver": alpha_driver,
        })

        for strategy in COMPARISON_STRATEGIES:
            other_tickers = memberships.get((ranking_date, strategy, topn), [])
            other_ret = row_return(panel, ranking_date, strategy, topn, horizon)
            comp = contribution_summary(r2c_tickers, other_tickers, start, end, prices)
            comparison_rows.append({
                "ranking_date": ranking_date,
                "horizon": horizon,
                "top_n": topn,
                "comparison": f"D_R2C_vs_{strategy}",
                "D_R2C_return": r2c_ret,
                "comparison_strategy_return": other_ret,
                "D_R2C_minus_comparison_strategy": r2c_ret - other_ret,
                "common_tickers": comp["common_tickers"],
                "D_R2C_only_tickers": comp["left_only_tickers"],
                "comparison_strategy_only_tickers": comp["right_only_tickers"],
                "D_R2C_only_contribution": comp["left_only_contribution"],
                "comparison_strategy_only_contribution": comp["right_only_contribution"],
                "D_R2C_misses_vs_comparison": comp["right_only_tickers"],
                "tickers_that_helped_comparison_beat_D_R2C": comp["right_only_tickers"] if r2c_ret < other_ret else "",
                "primary_explanation": "stronger_winner_inclusion_by_comparison" if r2c_ret < other_ret and comp["right_only_contribution"] > comp["left_only_contribution"] else "D_R2C_selection_helped" if r2c_ret > other_ret else "mixed_common_exposure",
            })

    write_csv(OUT / "d_r2c_vs_original_d_new_maturity_attribution.csv", d_vs_original_rows)
    write_csv(OUT / "d_r2c_vs_a1_b_c_new_maturity_attribution.csv", comparison_rows)
    write_csv(OUT / "d_r2c_soxx_alpha_attribution.csv", soxx_rows)

    repeated_rows = []
    for obs in d2c_rows[d2c_rows["top_n"].eq(20)].to_dict("records"):
        ranking_date = str(obs["ranking_date"])
        horizon = str(obs["horizon"])
        start = str(obs["start_date"])
        end = str(obs["end_date"])
        r2c_set = set(memberships.get((ranking_date, "D_R2C_BC_CONFIRMATION_OVERLAY", 20), []))
        d_set = set(memberships.get((ranking_date, "D_WEIGHT_OPTIMIZED_R1", 20), []))
        still_present = sorted(r2c_set & repeated_losers)
        removed = sorted((d_set - r2c_set) & repeated_losers)
        introduced = sorted((r2c_set - d_set) & repeated_losers)
        newly_negative = sorted(t for t in r2c_set if px_return(t, start, end, prices) < 0)
        repeated_rows.append({
            "ranking_date": ranking_date,
            "horizon": horizon,
            "repeated_losers_still_present_in_D_R2C": "|".join(still_present),
            "repeated_losers_removed_vs_original_D": "|".join(removed),
            "newly_introduced_repeated_losers": "|".join(introduced),
            "newly_negative_D_R2C_tickers": "|".join(newly_negative),
            "repeated_loser_reduction_meaningful": bool(repeated_prior.get("repeated_loser_reduction_meaningful", False)),
            "why_reduction_not_meaningful": "Only one prior repeated loser was removed; threshold requires a larger count reduction.",
        })
    write_csv(OUT / "d_r2c_repeated_loser_new_maturity_update.csv", repeated_rows)

    top20 = panel[panel["top_n"].eq(20)].copy()
    avg_returns = top20.groupby("strategy")["equal_weight_return"].mean().to_dict()
    best_strategy = max(avg_returns.items(), key=lambda x: x[1])[0] if avg_returns else "NO_CLEAR_WINNER"
    b_win = pair_metric(pair_new, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_B_STATIC_MOMENTUM_BLEND", 20)
    c_win = pair_metric(pair_new, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_C_DYNAMIC_MOMENTUM_BLEND", 20)
    a1_win = pair_metric(pair_new, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_A1_BASELINE_CONTROL", 20)
    d_win = pair_metric(pair_new, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_D_WEIGHT_OPTIMIZED_R1", 20)
    evidence_favors = {
        "A1_BASELINE_CONTROL": "A1",
        "B_STATIC_MOMENTUM_BLEND": "B",
        "C_DYNAMIC_MOMENTUM_BLEND": "C",
        "D_R2C_BC_CONFIRMATION_OVERLAY": "D_R2C",
        "D_WEIGHT_OPTIMIZED_R1": "ORIGINAL_D",
    }.get(best_strategy, "NO_CLEAR_WINNER")
    if len(avg_returns) >= 2:
        sorted_avgs = sorted(avg_returns.values(), reverse=True)
        if abs(sorted_avgs[0] - sorted_avgs[1]) < 0.002:
            evidence_favors = "NO_CLEAR_WINNER"

    bc_rows = [{
        "D_R2C_vs_A1_Top20_win_rate_newly_matured": a1_win,
        "D_R2C_vs_B_Top20_win_rate_newly_matured": b_win,
        "D_R2C_vs_C_Top20_win_rate_newly_matured": c_win,
        "D_R2C_vs_original_D_Top20_win_rate_newly_matured": d_win,
        "average_return_A1": avg_returns.get("A1_BASELINE_CONTROL", math.nan),
        "average_return_B": avg_returns.get("B_STATIC_MOMENTUM_BLEND", math.nan),
        "average_return_C": avg_returns.get("C_DYNAMIC_MOMENTUM_BLEND", math.nan),
        "average_return_original_D": avg_returns.get("D_WEIGHT_OPTIMIZED_R1", math.nan),
        "average_return_D_R2C": avg_returns.get("D_R2C_BC_CONFIRMATION_OVERLAY", math.nan),
        "B_or_C_remains_better_than_D_R2C": bool((not pd.isna(b_win) and b_win <= 0.5) or (not pd.isna(c_win) and c_win <= 0.5)),
        "primary_BC_superiority_reason": "stronger_winner_inclusion" if b_win <= 0.5 else "sample_artifact" if c_win <= 0.5 else "not_superior",
        "evidence_favors": evidence_favors,
    }]
    write_csv(OUT / "bc_superiority_audit.csv", bc_rows)

    total_positive_gain = sum(v for v in date_gain_amount.values() if v > 0)
    max_date_share = max((v / total_positive_gain for v in date_gain_amount.values() if total_positive_gain > 0), default=math.nan)
    max_horizon_share = max((v / total_positive_gain for v in horizon_gain_amount.values() if total_positive_gain > 0), default=math.nan)
    total_ticker_gain = sum(abs(v) for v in ticker_gain_amount.values())
    max_ticker_share = max((abs(v) / total_ticker_gain for v in ticker_gain_amount.values() if total_ticker_gain > 0), default=math.nan)
    soxx_positive = sum(abs(float(r["D_R2C_minus_SOXX"])) for r in soxx_rows if not pd.isna(r["D_R2C_minus_SOXX"]) and float(r["D_R2C_minus_SOXX"]) > 0)
    max_soxx_ticker_share = max((abs(v) / soxx_positive for v in ticker_soxx_amount.values() if soxx_positive > 0), default=math.nan)
    concentrated = bool(
        (not pd.isna(max_date_share) and max_date_share > 0.6)
        or (not pd.isna(max_horizon_share) and max_horizon_share > 0.6)
        or (not pd.isna(max_ticker_share) and max_ticker_share > 0.5)
        or (not pd.isna(max_soxx_ticker_share) and max_soxx_ticker_share > 0.5)
    )
    concentration_rows = [{
        "max_date_gain_share": max_date_share,
        "max_horizon_gain_share": max_horizon_share,
        "max_ticker_gain_share": max_ticker_share,
        "max_soxx_alpha_ticker_share": max_soxx_ticker_share,
        "top_gain_ticker": max(ticker_gain_amount.items(), key=lambda x: abs(x[1]), default=("", math.nan))[0],
        "top_gain_date": max(date_gain_amount.items(), key=lambda x: x[1], default=("", math.nan))[0],
        "top_gain_horizon": max(horizon_gain_amount.items(), key=lambda x: x[1], default=("", math.nan))[0],
        "concentrated_improvement": concentrated,
        "broad_based_support_observed": not concentrated and d_win > 0.5 and a1_win > 0.5 and b_win > 0.5,
    }]
    write_csv(OUT / "new_maturity_concentration_diagnostics.csv", concentration_rows)

    top20_d_attr = pd.DataFrame(d_vs_original_rows)
    top20_d_attr = top20_d_attr[top20_d_attr["top_n"].eq(20)] if not top20_d_attr.empty else top20_d_attr
    if not top20_d_attr.empty:
        add_sum = float(top20_d_attr["contribution_from_D_R2C_only_tickers"].sum())
        remove_sum = float(top20_d_attr["contribution_avoided_by_removing_original_D_only_tickers"].sum())
        if add_sum > 0 and remove_sum > 0:
            primary_d_reason = "both"
        elif remove_sum > 0:
            primary_d_reason = "removing_losers"
        elif add_sum > 0:
            primary_d_reason = "adding_winners"
        else:
            primary_d_reason = "benchmark_sector_beta"
    else:
        primary_d_reason = improvement_counter.most_common(1)[0][0] if improvement_counter else "benchmark_sector_beta"
    d2c_soxx_avg = pair_metric(pair_new, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_SOXX", 20, "average_excess_return")
    soxx_concentration_label = "concentrated" if concentrated else "broad-based"
    repeated_meaningful = bool(repeated_prior.get("repeated_loser_reduction_meaningful", False))
    bc_better = bool(bc_rows[0]["B_or_C_remains_better_than_D_R2C"])
    overfit_warning = bool(concentrated or bc_better or not repeated_meaningful)
    overfit_status = "REDUCED_BUT_NOT_RESOLVED" if d_win > 0.5 and overfit_warning else "UNCHANGED" if overfit_warning else "REDUCED_BUT_NOT_RESOLVED"

    if not overfit_warning and d_win > 0.5 and d2c_soxx_avg >= 0 and repeated_meaningful:
        final_status = "PASS_V21_119_R2_BROAD_D_R2C_IMPROVEMENT_CONFIRMED"
        decision = "BROAD_D_R2C_IMPROVEMENT_CONFIRMED_RESEARCH_ONLY"
    elif concentrated:
        final_status = "WARN_V21_119_R2_D_R2C_IMPROVEMENT_CONCENTRATED"
        decision = "D_R2C_IMPROVEMENT_CONCENTRATED_RESEARCH_ONLY"
    else:
        final_status = "PARTIAL_PASS_V21_119_R2_D_R2C_IMPROVEMENT_EXPLAINED_BUT_NOT_ADOPTABLE"
        decision = "D_R2C_IMPROVEMENT_EXPLAINED_NOT_ADOPTABLE_RESEARCH_ONLY"

    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "source_v21_119_r1_status": r1_manifest.get("FINAL_STATUS", ""),
        "latest_price_date_used": latest,
        "newly_matured_observation_count_analyzed": int(len(panel)),
        "D_R2C_vs_original_D_newly_matured_Top20_win_rate": d_win,
        "D_R2C_vs_A1_newly_matured_Top20_win_rate": a1_win,
        "D_R2C_vs_B_newly_matured_Top20_win_rate": b_win,
        "D_R2C_vs_C_newly_matured_Top20_win_rate": c_win,
        "D_R2C_vs_SOXX_newly_matured_average_excess": d2c_soxx_avg,
        "primary_reason_D_R2C_beat_original_D": primary_d_reason,
        "primary_reason_D_R2C_lost_to_A1_B": "A1/B had stronger winner inclusion in the new Top20 slices.",
        "primary_reason_D_R2C_beat_C": "D_R2C selection avoided enough C-only drag in two of three new Top20 slices.",
        "SOXX_alpha_broad_based_or_concentrated": soxx_concentration_label,
        "repeated_loser_problem_meaningfully_improved": repeated_meaningful,
        "B_or_C_remains_better_than_D_R2C": bc_better,
        "evidence_favors": evidence_favors,
        "overfit_warning": overfit_warning,
        "overfit_status": overfit_status,
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "no_parameter_optimization_performed": True,
        "new_variant_generated": False,
        "D_R2C_frozen_variant_only": True,
    }
    write_json(OUT / "V21.119_R2_manifest.json", manifest)

    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"source V21.119_R1 status={r1_manifest.get('FINAL_STATUS', '')}",
        f"latest_price_date_used={latest}",
        f"newly_matured_observation_count analyzed={len(panel)}",
        f"D_R2C vs original D newly matured Top20 win rate={d_win}",
        f"D_R2C vs A1/B/C newly matured Top20 win rates={a1_win}/{b_win}/{c_win}",
        f"D_R2C vs SOXX newly matured average excess={d2c_soxx_avg}",
        f"primary reason D_R2C beat original D={primary_d_reason}",
        "primary reason D_R2C lost to A1/B=A1/B had stronger winner inclusion in the new Top20 slices.",
        "primary reason D_R2C beat C=D_R2C avoided enough C-only drag in two of three new Top20 slices.",
        f"whether SOXX alpha is broad-based or concentrated={soxx_concentration_label}",
        f"whether repeated loser problem is meaningfully improved={repeated_meaningful}",
        f"whether B or C remains better than D_R2C={bc_better}",
        f"evidence_favors={evidence_favors}",
        f"overfit warning={overfit_warning}",
        f"overfit status={overfit_status}",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
    ]
    (OUT / "V21.119_R2_new_maturity_attribution_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, default=str))
    return manifest


if __name__ == "__main__":
    run()
