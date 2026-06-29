from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd


sys.path.append(str(Path(__file__).resolve().parent))
import v21_139_multi_strategy_random_asof_backtest as v139  # noqa: E402


STAGE = "V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST"
OUT = Path("outputs/v21/V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST")
PANEL = Path("outputs/v21/V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020/V21.140_extended_adjusted_close_panel_2020_plus.csv")
V140_SUMMARY = Path("outputs/v21/V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020/V21.140_summary.json")
V139_SUMMARY = Path("outputs/v21/V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST/V21.139_summary.json")
V139_METRICS = Path("outputs/v21/V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST/V21.139_strategy_metric_summary.csv")
META = Path("outputs/v21/V21.138_E_R1_METADATA_COVERAGE_REPAIR_AND_REAUDIT/consolidated_sector_industry_metadata_bridge.csv")

SEEDS = 50
DRAWS_PER_SEED = 100
HORIZONS = [5, 10, 20]
BUCKETS = [20, 50]
MIN_HOLDINGS = {20: 15, 50: 35}
RNG_BASE_SEED = 21141
BENCHMARKS = {"QQQ", "SOXX", "SPY", "SMH", "XLK"}

REGIMES = [
    ("COVID_CRASH_AND_REBOUND", "2020-01-01", "2020-12-31"),
    ("LIQUIDITY_GROWTH_BULL", "2021-01-01", "2021-12-31"),
    ("RATE_HIKE_TECH_BEAR", "2022-01-01", "2022-12-31"),
    ("AI_SEMICONDUCTOR_REACCELERATION", "2023-01-01", "2024-12-31"),
    ("LATE_SUPERCYCLE_CURRENT", "2025-01-01", "2099-12-31"),
]

CONTROL_FLAGS = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "strategy_adoption_allowed": False,
}


def regime_for_date(date_value: pd.Timestamp) -> str:
    for label, start, end in REGIMES:
        if pd.Timestamp(start) <= date_value <= pd.Timestamp(end):
            return label
    return "UNCLASSIFIED"


def safe_float(value):
    if value is None or pd.isna(value):
        return None
    return float(value)


def load_panel() -> tuple[pd.DataFrame, list[pd.Timestamp], str]:
    df = pd.read_csv(PANEL)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")
    df.columns = [v139.norm_ticker(c) for c in df.columns]
    df = df.apply(pd.to_numeric, errors="coerce")
    dates = list(df.index)
    return df, dates, str(max(dates).date())


def strategy_registry() -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    rankings, registry = v139.discover_strategies()
    registry = registry.copy()
    mask = registry["source_exists"].astype(str).str.lower().eq("true")
    registry.loc[mask & registry["strategy_id"].ne("B_CLEAN"), "pit_status"] = "SNAPSHOT_RANKING_EXTENDED_PRICE_DIAGNOSTIC"
    registry.loc[mask & registry["strategy_id"].ne("B_CLEAN"), "diagnostic_only"] = True
    registry.loc[mask & registry["strategy_id"].ne("B_CLEAN"), "adoption_grade_included"] = False
    registry.loc[mask & registry["strategy_id"].ne("B_CLEAN"), "note"] = (
        registry.loc[mask & registry["strategy_id"].ne("B_CLEAN"), "note"].astype(str)
        + "; current ranking tested on extended price history, not true historical ranking"
    )
    return rankings, registry


def run_trials(rankings: dict[str, pd.DataFrame], prices: pd.DataFrame, dates: list[pd.Timestamp]):
    date_idx = {d: i for i, d in enumerate(dates)}
    sample_dates = dates[: len(dates) - max(HORIZONS)]
    by_regime = {
        label: [d for d in sample_dates if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
        for label, start, end in REGIMES
    }
    available_regimes = [r for r, ds in by_regime.items() if ds]
    columns = list(prices.columns)
    col_idx = {c: i for i, c in enumerate(columns)}
    close_arr = prices.to_numpy(dtype=float)
    return_arrays = {h: (prices.shift(-h) / prices - 1.0).to_numpy(dtype=float) for h in HORIZONS}
    universe_indices = [i for i, c in enumerate(columns) if c not in BENCHMARKS]
    entry_valid_by_date = {
        i: [j for j in universe_indices if not np.isnan(close_arr[i, j])]
        for i in range(len(dates) - max(HORIZONS))
    }
    strategy_indices = {
        sid: {bucket: [col_idx[t] for t in df.head(bucket)["ticker_norm"].tolist() if t in col_idx] for bucket in BUCKETS}
        for sid, df in rankings.items()
    }
    qqq_i, soxx_i, spy_i, smh_i, xlk_i = (col_idx.get(x) for x in ["QQQ", "SOXX", "SPY", "SMH", "XLK"])
    all_strategies = list(rankings.keys()) + ["RANDOM_UNIVERSE_EQUAL_WEIGHT"]
    rows, invalid, exclusions, member_detail = [], [], [], []
    for seed in range(SEEDS):
        rng = random.Random(RNG_BASE_SEED + seed)
        for draw in range(DRAWS_PER_SEED):
            regime = available_regimes[draw % len(available_regimes)]
            asof = rng.choice(by_regime[regime])
            asof_i = date_idx[asof]
            trial_id = f"s{seed:02d}_d{draw:03d}_{asof.date()}"
            entry_valid = entry_valid_by_date[asof_i]
            for bucket in BUCKETS:
                random_indices = rng.sample(entry_valid, min(bucket, len(entry_valid))) if entry_valid else []
                for strategy_id in all_strategies:
                    if strategy_id == "RANDOM_UNIVERSE_EQUAL_WEIGHT":
                        name_indices = random_indices
                        pit_status = "PIT_STRICT_BENCHMARK_RANDOM_UNIVERSE"
                    else:
                        name_indices = strategy_indices[strategy_id][bucket]
                        pit_status = "SNAPSHOT_RANKING_EXTENDED_PRICE_DIAGNOSTIC"
                    for horizon in HORIZONS:
                        arr = return_arrays[horizon]
                        raw = arr[asof_i, name_indices] if name_indices else np.array([], dtype=float)
                        valid_mask = ~np.isnan(raw)
                        valid_rets = raw[valid_mask]
                        valid_indices = [name_indices[i] for i, ok in enumerate(valid_mask) if ok]
                        missing_indices = [name_indices[i] for i, ok in enumerate(valid_mask) if not ok]
                        exit_date = str(dates[asof_i + horizon].date())
                        valid = len(valid_rets) >= MIN_HOLDINGS[bucket]
                        portfolio_return = float(np.mean(valid_rets)) if valid else np.nan
                        qqq = safe_float(arr[asof_i, qqq_i]) if qqq_i is not None else None
                        soxx = safe_float(arr[asof_i, soxx_i]) if soxx_i is not None else None
                        spy = safe_float(arr[asof_i, spy_i]) if spy_i is not None else None
                        smh = safe_float(arr[asof_i, smh_i]) if smh_i is not None else None
                        xlk = safe_float(arr[asof_i, xlk_i]) if xlk_i is not None else None
                        worst_ticker = columns[valid_indices[int(np.argmin(valid_rets))]] if len(valid_rets) else ""
                        worst_return = float(np.min(valid_rets)) if len(valid_rets) else np.nan
                        rows.append({
                            "trial_id": trial_id,
                            "seed": seed,
                            "draw": draw,
                            "sampled_asof_date": str(asof.date()),
                            "regime": regime,
                            "exit_date": exit_date,
                            "strategy_id": strategy_id,
                            "pit_status": pit_status,
                            "diagnostic_only": strategy_id != "RANDOM_UNIVERSE_EQUAL_WEIGHT",
                            "adoption_grade_included": False,
                            "portfolio_size": bucket,
                            "horizon": f"{horizon}D",
                            "horizon_days": horizon,
                            "valid_trial": valid,
                            "valid_holding_count": len(valid_rets),
                            "missing_holding_count": len(name_indices) - len(valid_rets),
                            "portfolio_return": portfolio_return,
                            "benchmark_QQQ_return": qqq,
                            "benchmark_SOXX_return": soxx,
                            "benchmark_SPY_return": spy,
                            "benchmark_SMH_return": smh,
                            "benchmark_XLK_return": xlk,
                            "excess_vs_QQQ": portfolio_return - qqq if valid and qqq is not None else np.nan,
                            "excess_vs_SOXX": portfolio_return - soxx if valid and soxx is not None else np.nan,
                            "excess_vs_SPY": portfolio_return - spy if valid and spy is not None else np.nan,
                            "worst_member_ticker": worst_ticker,
                            "worst_member_return": worst_return,
                            "future_price_used_for_scoring": False,
                        })
                        for mi in missing_indices[:20]:
                            exclusions.append({
                                "trial_id": trial_id,
                                "strategy_id": strategy_id,
                                "ticker_norm": columns[mi],
                                "sampled_asof_date": str(asof.date()),
                                "regime": regime,
                                "portfolio_size": bucket,
                                "horizon": f"{horizon}D",
                                "exclusion_reason": "MISSING_ENTRY_OR_EXIT_PRICE",
                            })
                        if not valid:
                            invalid.append({
                                "trial_id": trial_id,
                                "strategy_id": strategy_id,
                                "sampled_asof_date": str(asof.date()),
                                "regime": regime,
                                "portfolio_size": bucket,
                                "horizon": f"{horizon}D",
                                "valid_holding_count": len(valid_rets),
                                "missing_holding_count": len(name_indices) - len(valid_rets),
                                "invalid_reason": "BELOW_MIN_VALID_HOLDINGS",
                            })
                        if horizon == 10 and bucket == 20:
                            for ticker_i, ret in zip(valid_indices, valid_rets):
                                member_detail.append({
                                    "trial_id": trial_id,
                                    "strategy_id": strategy_id,
                                    "ticker_norm": columns[ticker_i],
                                    "member_return": float(ret),
                                    "sampled_asof_date": str(asof.date()),
                                    "regime": regime,
                                    "horizon": "10D",
                                    "portfolio_size": 20,
                                })
    invalid_df = pd.DataFrame(invalid)
    if invalid_df.empty:
        invalid_df = pd.DataFrame([{"strategy_id": "ALL", "invalid_trial_count": 0, "invalid_reason": "NONE"}])
    excl_df = pd.DataFrame(exclusions)
    if excl_df.empty:
        excl_df = pd.DataFrame([{"strategy_id": "ALL", "ticker_norm": "", "exclusion_reason": "NONE"}])
    return pd.DataFrame(rows), invalid_df, excl_df, pd.DataFrame(member_detail)


def add_a1_excess(trials: pd.DataFrame) -> pd.DataFrame:
    a1 = trials[trials["strategy_id"].eq("A1_BASELINE_CONTROL")][["trial_id", "portfolio_size", "horizon", "portfolio_return"]]
    a1 = a1.rename(columns={"portfolio_return": "A1_return"})
    df = trials.merge(a1, on=["trial_id", "portfolio_size", "horizon"], how="left")
    df["excess_vs_A1"] = df["portfolio_return"] - df["A1_return"]
    return df


def metric_summary(trials: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    df = add_a1_excess(trials)
    rows = []
    for keys, g in df.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = dict(zip(group_cols, keys))
        valid = g[g["valid_trial"]].copy()
        rets = valid["portfolio_return"].dropna()
        ex_a1 = valid["excess_vs_A1"].dropna()
        ex_qqq = valid["excess_vs_QQQ"].dropna()
        worst5 = rets[rets <= rets.quantile(0.05)] if len(rets) else pd.Series(dtype=float)
        worst10 = rets[rets <= rets.quantile(0.10)] if len(rets) else pd.Series(dtype=float)
        seed_mean = valid.groupby("seed")["portfolio_return"].mean()
        seed_win = valid.groupby("seed")["excess_vs_QQQ"].apply(lambda s: (s.dropna() > 0).mean() if s.notna().any() else np.nan)
        seed_a1_win = valid.groupby("seed")["excess_vs_A1"].apply(lambda s: (s.dropna() > 0).mean() > 0.5 if s.notna().any() else False)
        seed_qqq_win = valid.groupby("seed")["excess_vs_QQQ"].apply(lambda s: (s.dropna() > 0).mean() > 0.5 if s.notna().any() else False)
        row.update({
            "trial_count": int(len(g)),
            "valid_trial_count": int(len(valid)),
            "invalid_trial_count": int((~g["valid_trial"]).sum()),
            "seed_coverage": int(g["seed"].nunique()) if "seed" in g else 0,
            "draw_coverage": int(g["draw"].nunique()) if "draw" in g else 0,
            "mean_return": safe_float(rets.mean()),
            "median_return": safe_float(rets.median()),
            "std_return": safe_float(rets.std(ddof=0)),
            "win_rate_positive": safe_float((rets > 0).mean()) if len(rets) else None,
            "p25_return": safe_float(rets.quantile(0.25)) if len(rets) else None,
            "p10_return": safe_float(rets.quantile(0.10)) if len(rets) else None,
            "p05_return": safe_float(rets.quantile(0.05)) if len(rets) else None,
            "worst_trial_return": safe_float(rets.min()) if len(rets) else None,
            "best_trial_return": safe_float(rets.max()) if len(rets) else None,
            "mean_excess_vs_A1": safe_float(ex_a1.mean()),
            "median_excess_vs_A1": safe_float(ex_a1.median()),
            "win_rate_vs_A1": safe_float((ex_a1 > 0).mean()) if len(ex_a1) else None,
            "mean_excess_vs_QQQ": safe_float(ex_qqq.mean()),
            "median_excess_vs_QQQ": safe_float(ex_qqq.median()),
            "win_rate_vs_QQQ": safe_float((ex_qqq > 0).mean()) if len(ex_qqq) else None,
            "mean_excess_vs_SOXX": safe_float(valid["excess_vs_SOXX"].mean()),
            "win_rate_vs_SOXX": safe_float((valid["excess_vs_SOXX"] > 0).mean()) if valid["excess_vs_SOXX"].notna().any() else None,
            "mean_excess_vs_SPY": safe_float(valid["excess_vs_SPY"].mean()),
            "win_rate_vs_SPY": safe_float((valid["excess_vs_SPY"] > 0).mean()) if valid["excess_vs_SPY"].notna().any() else None,
            "prob_return_lt_minus_5pct": safe_float((rets < -0.05).mean()) if len(rets) else None,
            "prob_return_lt_minus_10pct": safe_float((rets < -0.10).mean()) if len(rets) else None,
            "expected_shortfall_worst_5pct": safe_float(worst5.mean()) if len(worst5) else None,
            "expected_shortfall_worst_10pct": safe_float(worst10.mean()) if len(worst10) else None,
            "left_tail_underperformance_freq_vs_A1": safe_float(((valid["portfolio_return"] < -0.05) & (valid["excess_vs_A1"] < 0)).mean()) if len(valid) else None,
            "left_tail_underperformance_freq_vs_QQQ": safe_float(((valid["portfolio_return"] < -0.05) & (valid["excess_vs_QQQ"] < 0)).mean()) if len(valid) else None,
            "seed_level_mean_return_dispersion": safe_float(seed_mean.std(ddof=0)),
            "seed_level_winrate_dispersion": safe_float(seed_win.std(ddof=0)),
            "pct_seeds_beating_A1": safe_float(seed_a1_win.mean()) if len(valid) else None,
            "pct_seeds_beating_QQQ": safe_float(seed_qqq_win.mean()) if len(valid) else None,
        })
        rows.append(row)
    return pd.DataFrame(rows)


def seed_metrics(trials: pd.DataFrame) -> pd.DataFrame:
    df = add_a1_excess(trials)
    rows = []
    for keys, g in df[df["valid_trial"]].groupby(["strategy_id", "portfolio_size", "horizon", "seed"]):
        rows.append({
            "strategy_id": keys[0],
            "portfolio_size": int(keys[1]),
            "horizon": keys[2],
            "seed": int(keys[3]),
            "valid_trial_count": int(len(g)),
            "mean_return": safe_float(g["portfolio_return"].mean()),
            "win_rate_positive": safe_float((g["portfolio_return"] > 0).mean()),
            "mean_excess_vs_A1": safe_float(g["excess_vs_A1"].mean()),
            "win_rate_vs_A1": safe_float((g["excess_vs_A1"] > 0).mean()),
            "mean_excess_vs_QQQ": safe_float(g["excess_vs_QQQ"].mean()),
            "win_rate_vs_QQQ": safe_float((g["excess_vs_QQQ"] > 0).mean()),
        })
    return pd.DataFrame(rows)


def pairwise(trials: pd.DataFrame, by_regime: bool = False, metric: str = "winrate") -> pd.DataFrame:
    base = trials[(trials["portfolio_size"].eq(20)) & (trials["horizon"].eq("10D")) & (trials["valid_trial"])].copy()
    groups = ["regime"] if by_regime else [None]
    rows = []
    iterable = base.groupby("regime") if by_regime else [(None, base)]
    for regime, g in iterable:
        piv = g.pivot_table(index="trial_id", columns="strategy_id", values="portfolio_return", aggfunc="first")
        names = list(piv.columns)
        for a in names:
            row = {"strategy_id": a}
            if by_regime:
                row["regime"] = regime
            for b in names:
                if a == b:
                    row[b] = 0.5 if metric == "winrate" else 0.0
                    continue
                paired = piv[[a, b]].dropna()
                if paired.empty:
                    row[b] = np.nan
                elif metric == "winrate":
                    row[b] = float((paired[a] > paired[b]).mean())
                else:
                    row[b] = float((paired[a] - paired[b]).mean())
            rows.append(row)
    return pd.DataFrame(rows)


def robustness(metrics_regime: pd.DataFrame, metrics_all: pd.DataFrame) -> pd.DataFrame:
    use = metrics_regime[(metrics_regime["portfolio_size"].eq(20)) & (metrics_regime["horizon"].eq("10D"))].copy()
    all_use = metrics_all[(metrics_all["portfolio_size"].eq(20)) & (metrics_all["horizon"].eq("10D"))].copy()
    rows = []
    for strategy, g in use.groupby("strategy_id"):
        if strategy == "RANDOM_UNIVERSE_EQUAL_WEIGHT":
            continue
        all_row = all_use[all_use["strategy_id"].eq(strategy)]
        regimes_beating_a1 = int((g["mean_excess_vs_A1"] > 0).sum())
        regimes_beating_qqq = int((g["mean_excess_vs_QQQ"] > 0).sum())
        mean_2023_plus = g[g["regime"].isin(["AI_SEMICONDUCTOR_REACCELERATION", "LATE_SUPERCYCLE_CURRENT"])]["mean_excess_vs_A1"].mean()
        mean_2020_2022 = g[g["regime"].isin(["COVID_CRASH_AND_REBOUND", "LIQUIDITY_GROWTH_BULL", "RATE_HIKE_TECH_BEAR"])]["mean_excess_vs_A1"].mean()
        bear = g[g["regime"].eq("RATE_HIKE_TECH_BEAR")]["mean_excess_vs_A1"].mean()
        es = all_row["expected_shortfall_worst_5pct"].iloc[0] if not all_row.empty else np.nan
        robust_score = (regimes_beating_a1 + regimes_beating_qqq) - max(0, (mean_2023_plus or 0) - (mean_2020_2022 or 0)) * 10
        rows.append({
            "strategy_id": strategy,
            "all_period_rank_by_winrate_vs_A1": None,
            "regimes_beating_A1_count": regimes_beating_a1,
            "regimes_beating_QQQ_count": regimes_beating_qqq,
            "percent_regimes_beating_A1": regimes_beating_a1 / max(g["regime"].nunique(), 1),
            "percent_regimes_beating_QQQ": regimes_beating_qqq / max(g["regime"].nunique(), 1),
            "mean_excess_vs_A1_2023_2026": safe_float(mean_2023_plus),
            "mean_excess_vs_A1_2020_2022": safe_float(mean_2020_2022),
            "supercycle_dependency_score": safe_float((mean_2023_plus or 0) - (mean_2020_2022 or 0)),
            "failed_badly_in_2022": bool(pd.notna(bear) and bear < -0.01),
            "works_across_2020_2022_and_2023_2026": bool(regimes_beating_a1 >= 4),
            "only_works_in_2023_2026": bool((mean_2023_plus or 0) > 0 and (mean_2020_2022 or 0) <= 0),
            "semiconductor_supercycle_dependent": bool((mean_2023_plus or 0) - (mean_2020_2022 or 0) > 0.01),
            "left_tail_expected_shortfall": safe_float(es),
            "regime_robustness_score": safe_float(robust_score),
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        out["all_period_rank_by_winrate_vs_A1"] = out["strategy_id"].map(
            all_use.sort_values("win_rate_vs_A1", ascending=False).reset_index(drop=True).reset_index().set_index("strategy_id")["index"].add(1)
        )
    return out


def worst_trials(trials: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    meta = pd.read_csv(META) if META.exists() else pd.DataFrame()
    if not meta.empty and "ticker_norm" in meta.columns:
        meta["ticker_norm"] = meta["ticker_norm"].map(v139.norm_ticker)
    rows = []
    use = trials[(trials["portfolio_size"].eq(20)) & (trials["horizon"].eq("10D")) & (trials["valid_trial"])]
    for strategy, g in use.groupby("strategy_id"):
        for _, row in g.nsmallest(20, "portfolio_return").iterrows():
            m = members[(members["strategy_id"].eq(strategy)) & (members["trial_id"].eq(row["trial_id"]))]
            losers = m.nsmallest(5, "member_return")
            sectors = []
            if not meta.empty and "sector" in meta.columns:
                sectors = meta[meta["ticker_norm"].isin(losers["ticker_norm"])]["sector"].dropna().astype(str).unique().tolist()
            loss_type = "BROAD_MARKET_DRAWDOWN" if row["benchmark_QQQ_return"] < -0.02 else "SINGLE_NAME_CONCENTRATION"
            if "Semiconductor" in "|".join(sectors):
                loss_type = "SEMICONDUCTOR_SECTOR_DRAWDOWN"
            rows.append({
                "strategy_id": strategy,
                "trial_id": row["trial_id"],
                "sampled_asof_date": row["sampled_asof_date"],
                "regime": row["regime"],
                "portfolio_return": row["portfolio_return"],
                "QQQ_return": row["benchmark_QQQ_return"],
                "loss_classification": loss_type,
                "common_loss_tickers": "|".join(losers["ticker_norm"].tolist()),
                "common_loss_sectors": "|".join(sectors),
                "non_pit_artifact": row["pit_status"] != "PIT_STRICT",
            })
    return pd.DataFrame(rows)


def v139_comparison(metrics_all: pd.DataFrame, robust: pd.DataFrame) -> pd.DataFrame:
    rows = []
    current = metrics_all[(metrics_all["portfolio_size"].eq(20)) & (metrics_all["horizon"].eq("10D"))]
    best_a1 = current.sort_values("win_rate_vs_A1", ascending=False, na_position="last").iloc[0]["strategy_id"]
    best_qqq = current.sort_values("win_rate_vs_QQQ", ascending=False, na_position="last").iloc[0]["strategy_id"]
    best_tail = current.sort_values("expected_shortfall_worst_5pct", ascending=False, na_position="last").iloc[0]["strategy_id"]
    old = {}
    if V139_SUMMARY.exists():
        old = json.loads(V139_SUMMARY.read_text(encoding="utf-8"))
    drow = robust[robust["strategy_id"].eq("D_R2A_REPEATED_LOSER_SOFT_PENALTY")]
    erow = robust[robust["strategy_id"].eq("E_R1_REPAIRED")]
    rows.append({
        "comparison_item": "best_vs_A1_changed",
        "v21_139_value": old.get("best_strategy_vs_A1_by_10D_Top20_winrate", ""),
        "v21_141_value": best_a1,
        "changed": old.get("best_strategy_vs_A1_by_10D_Top20_winrate", "") != best_a1,
    })
    rows.append({
        "comparison_item": "best_vs_QQQ_changed",
        "v21_139_value": old.get("best_strategy_vs_QQQ_by_10D_Top20_winrate", ""),
        "v21_141_value": best_qqq,
        "changed": old.get("best_strategy_vs_QQQ_by_10D_Top20_winrate", "") != best_qqq,
    })
    rows.append({
        "comparison_item": "best_left_tail_changed",
        "v21_139_value": old.get("best_left_tail_strategy", ""),
        "v21_141_value": best_tail,
        "changed": old.get("best_left_tail_strategy", "") != best_tail,
    })
    rows.append({
        "comparison_item": "D_R2A_edge_persisted_outside_supercycle",
        "v21_139_value": "D_R2A_recent_snapshot_edge",
        "v21_141_value": "" if drow.empty else str(drow.iloc[0]["mean_excess_vs_A1_2020_2022"] > 0),
        "changed": False,
    })
    rows.append({
        "comparison_item": "E_R1_left_tail_advantage_persisted",
        "v21_139_value": old.get("best_left_tail_strategy", ""),
        "v21_141_value": str(best_tail == "E_R1_REPAIRED" or (not erow.empty and erow.iloc[0]["left_tail_expected_shortfall"] >= current["expected_shortfall_worst_5pct"].median())),
        "changed": False,
    })
    rows.append({
        "comparison_item": "A1_more_competitive_over_longer_history",
        "v21_139_value": "CONTROL_BASELINE",
        "v21_141_value": str(best_a1 == "A1_BASELINE_CONTROL" or current[current["strategy_id"].eq("A1_BASELINE_CONTROL")]["win_rate_vs_QQQ"].iloc[0] >= current["win_rate_vs_QQQ"].median()),
        "changed": False,
    })
    rows.append({
        "comparison_item": "momentum_variants_overfit_recent_semiconductor_trend",
        "v21_139_value": "UNKNOWN",
        "v21_141_value": str(bool(robust["semiconductor_supercycle_dependent"].any()) if not robust.empty else False),
        "changed": False,
    })
    return pd.DataFrame(rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rankings, registry = strategy_registry()
    prices, dates, latest = load_panel()
    trials, invalid, exclusions, members = run_trials(rankings, prices, dates)
    metrics_all = metric_summary(trials, ["strategy_id", "portfolio_size", "horizon"])
    metrics_regime = metric_summary(trials, ["strategy_id", "portfolio_size", "horizon", "regime"])
    seed_df = seed_metrics(trials)
    pair_win_all = pairwise(trials, by_regime=False, metric="winrate")
    pair_win_regime = pairwise(trials, by_regime=True, metric="winrate")
    pair_excess_all = pairwise(trials, by_regime=False, metric="mean_excess")
    robust = robustness(metrics_regime, metrics_all)
    comp = v139_comparison(metrics_all, robust)
    worst = worst_trials(trials, members)
    pit = registry[["strategy_id", "pit_status", "adoption_grade_included", "diagnostic_only", "note"]].copy()

    top = metrics_all[(metrics_all["portfolio_size"].eq(20)) & (metrics_all["horizon"].eq("10D"))]
    candidates = top[~top["strategy_id"].eq("RANDOM_UNIVERSE_EQUAL_WEIGHT")]
    best_a1 = candidates.sort_values("win_rate_vs_A1", ascending=False, na_position="last").iloc[0]["strategy_id"]
    best_qqq = candidates.sort_values("win_rate_vs_QQQ", ascending=False, na_position="last").iloc[0]["strategy_id"]
    best_tail = candidates.sort_values("expected_shortfall_worst_5pct", ascending=False, na_position="last").iloc[0]["strategy_id"]
    best_robust = robust.sort_values("regime_robustness_score", ascending=False, na_position="last").iloc[0]["strategy_id"] if not robust.empty else ""
    supercycle_dep = robust.sort_values("supercycle_dependency_score", ascending=False, na_position="last").iloc[0]["strategy_id"] if not robust.empty else ""
    erow = robust[robust["strategy_id"].eq("E_R1_REPAIRED")]
    drow = robust[robust["strategy_id"].eq("D_R2A_REPEATED_LOSER_SOFT_PENALTY")]
    e_tail_persisted = bool(best_tail == "E_R1_REPAIRED" or (not erow.empty and erow.iloc[0]["left_tail_expected_shortfall"] >= candidates["expected_shortfall_worst_5pct"].median()))
    d_edge_outside = bool(not drow.empty and drow.iloc[0]["mean_excess_vs_A1_2020_2022"] > 0)

    final_status = "PARTIAL_PASS_V21_141_EXTENDED_RANDOM_BACKTEST_DIAGNOSTIC_ONLY"
    decision = "NO_ADOPTION_PIT_COVERAGE_INSUFFICIENT_EXTENDED_HISTORY"
    blockers = "NO_PIT_STRICT_STRATEGY_RECONSTRUCTION|CURRENT_RANKINGS_ON_EXTENDED_HISTORY_ONLY|FORWARD_MATURITY_REQUIRED|RESEARCH_ONLY_STAGE"

    summary = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_used": latest,
        "earliest_trial_date": str(pd.to_datetime(trials["sampled_asof_date"]).min().date()),
        "latest_trial_date": str(pd.to_datetime(trials["sampled_asof_date"]).max().date()),
        "seeds": SEEDS,
        "draws_per_seed": DRAWS_PER_SEED,
        "total_trials": SEEDS * DRAWS_PER_SEED,
        "strategies_tested": "|".join(rankings.keys()),
        "pit_strict_strategies": "",
        "diagnostic_only_strategies": "|".join(registry.loc[registry["diagnostic_only"], "strategy_id"].astype(str)),
        "best_strategy_vs_A1_by_10D_Top20_winrate_all_period": str(best_a1),
        "best_strategy_vs_QQQ_by_10D_Top20_winrate_all_period": str(best_qqq),
        "best_left_tail_strategy_all_period": str(best_tail),
        "best_regime_robust_strategy": str(best_robust),
        "strategy_most_dependent_on_2023_2026_supercycle": str(supercycle_dep),
        "E_R1_left_tail_advantage_persisted": e_tail_persisted,
        "D_R2A_edge_persisted_outside_supercycle": d_edge_outside,
        "remaining_blockers": blockers,
        "output_directory": str(OUT).replace("\\", "/"),
        **CONTROL_FLAGS,
    }

    metrics_all.to_csv(OUT / "V21.141_strategy_metric_summary_all_period.csv", index=False)
    metrics_regime.to_csv(OUT / "V21.141_strategy_metric_summary_by_regime.csv", index=False)
    pair_win_all.to_csv(OUT / "V21.141_pairwise_winrate_matrix_all_period.csv", index=False)
    pair_win_regime.to_csv(OUT / "V21.141_pairwise_winrate_matrix_by_regime.csv", index=False)
    pair_excess_all.to_csv(OUT / "V21.141_pairwise_excess_return_matrix_all_period.csv", index=False)
    seed_df.to_csv(OUT / "V21.141_seed_level_metrics.csv", index=False)
    trials.to_csv(OUT / "V21.141_trial_level_returns.csv", index=False)
    invalid.to_csv(OUT / "V21.141_invalid_trials.csv", index=False)
    exclusions.to_csv(OUT / "V21.141_missing_price_exclusions.csv", index=False)
    robust.to_csv(OUT / "V21.141_regime_robustness_score.csv", index=False)
    comp.to_csv(OUT / "V21.141_v21_139_comparison.csv", index=False)
    pit.to_csv(OUT / "V21.141_pit_status_audit.csv", index=False)
    worst.to_csv(OUT / "V21.141_worst_trials_decomposition.csv", index=False)
    (OUT / "V21.141_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")

    lines = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"latest_price_date_used={latest}",
        f"earliest_trial_date={summary['earliest_trial_date']}",
        f"latest_trial_date={summary['latest_trial_date']}",
        f"strategies_tested={summary['strategies_tested']}",
        "pit_strict_strategies=",
        f"diagnostic_only_strategies={summary['diagnostic_only_strategies']}",
        f"best_strategy_vs_A1_by_10D_Top20_winrate_all_period={best_a1}",
        f"best_strategy_vs_QQQ_by_10D_Top20_winrate_all_period={best_qqq}",
        f"best_left_tail_strategy_all_period={best_tail}",
        f"best_regime_robust_strategy={best_robust}",
        f"strategy_most_dependent_on_2023_2026_supercycle={supercycle_dep}",
        f"E_R1_left_tail_advantage_persisted={str(e_tail_persisted).lower()}",
        f"D_R2A_edge_persisted_outside_supercycle={str(d_edge_outside).lower()}",
        f"remaining_blockers={blockers}",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
    ]
    (OUT / "V21.141_readable_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    for line in lines[:17]:
        print(line)
    print(f"output directory={str(OUT).replace(chr(92), '/')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
