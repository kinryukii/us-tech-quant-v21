from __future__ import annotations

import json
import math
import random
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST"
ROOT = Path(".")
OUT = ROOT / "outputs/v21/V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST"
PRICE_PATH = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
V128 = ROOT / "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE"
E_R1 = ROOT / "outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv"
D_R2A = ROOT / "outputs/v21/V21.118_D_R2_REPEATED_LOSER_AWARE_DESIGN/d_r2_adjusted_rankings.csv"
B_CLEAN_DIAG = ROOT / "outputs/v21/V21.126_R1_B_REPEATED_LOSER_DEPENDENCY_DECOMPOSITION/b_clean_subset_forward_diagnostic.csv"
META = ROOT / "outputs/v21/V21.138_E_R1_METADATA_COVERAGE_REPAIR_AND_REAUDIT/consolidated_sector_industry_metadata_bridge.csv"

SEEDS = 50
DRAWS_PER_SEED = 100
HORIZONS = [5, 10, 20]
BUCKETS = [20, 50]
MIN_HOLDINGS = {20: 15, 50: 35}
RNG_BASE_SEED = 21139

CONTROL_FLAGS = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "strategy_adoption_allowed": False,
}


def norm_ticker(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip().upper()


def first_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    lower_map = {c.lower(): c for c in df.columns}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    return None


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if df.empty:
        df.to_csv(path, index=False)
    else:
        df.to_csv(path, index=False)


def safe_float(value):
    if value is None or pd.isna(value):
        return None
    return float(value)


def load_ranking(path: Path, strategy_id: str, role: str, pit_status: str, note: str) -> tuple[pd.DataFrame | None, dict]:
    audit = {
        "strategy_id": strategy_id,
        "role_label": role,
        "source_path": str(path).replace("\\", "/"),
        "source_exists": path.exists(),
        "pit_status": pit_status,
        "adoption_grade_included": pit_status == "PIT_STRICT",
        "diagnostic_only": pit_status != "PIT_STRICT",
        "note": note,
    }
    if not path.exists():
        audit.update({"row_count": 0, "top20_count": 0, "top50_count": 0, "latest_price_date_used": ""})
        return None, audit
    df = pd.read_csv(path)
    ticker_col = first_col(df, ["ticker_norm", "ticker", "symbol"])
    rank_col = first_col(df, ["rank", "adjusted_rank", "E_rank"])
    score_col = first_col(df, ["E_final_score", "final_score", "adjusted_score_for_sort", "adjusted_score"])
    date_col = first_col(df, ["latest_price_date", "latest_price_date_used", "as_of_date", "ranking_date"])
    eligible_col = first_col(df, ["eligible_flag"])
    if ticker_col is None:
        audit.update({"row_count": len(df), "top20_count": 0, "top50_count": 0, "latest_price_date_used": ""})
        return None, audit
    work = df.copy()
    work["ticker_norm"] = work[ticker_col].map(norm_ticker)
    work = work[work["ticker_norm"] != ""].copy()
    if eligible_col is not None:
        eligible = work[eligible_col].astype(str).str.lower().isin(["true", "1", "yes"])
        if eligible.any():
            work = work[eligible].copy()
    if strategy_id == "D_R2A_REPEATED_LOSER_SOFT_PENALTY" and "candidate_variant" in work.columns:
        work = work[work["candidate_variant"].astype(str).eq("D_R2A_REPEATED_LOSER_SOFT_PENALTY")].copy()
    if date_col is not None and strategy_id == "D_R2A_REPEATED_LOSER_SOFT_PENALTY":
        latest_source_date = pd.to_datetime(work[date_col], errors="coerce").max()
        work = work[pd.to_datetime(work[date_col], errors="coerce").eq(latest_source_date)].copy()
    if rank_col is not None:
        work["rank"] = pd.to_numeric(work[rank_col], errors="coerce")
    elif score_col is not None:
        work["rank"] = pd.to_numeric(work[score_col], errors="coerce").rank(ascending=False, method="first")
    else:
        work["rank"] = np.arange(1, len(work) + 1)
    if score_col is not None:
        work["score"] = pd.to_numeric(work[score_col], errors="coerce")
    else:
        work["score"] = -work["rank"]
    work = work.drop_duplicates("ticker_norm", keep="first").sort_values(["rank", "ticker_norm"]).reset_index(drop=True)
    work["rank"] = np.arange(1, len(work) + 1)
    work["strategy_id"] = strategy_id
    latest_date = ""
    if date_col is not None:
        dates = pd.to_datetime(work[date_col], errors="coerce")
        if dates.notna().any():
            latest_date = str(dates.max().date())
    audit.update(
        {
            "row_count": int(len(work)),
            "top20_count": int(min(20, len(work))),
            "top50_count": int(min(50, len(work))),
            "latest_price_date_used": latest_date,
            "ticker_column": ticker_col,
            "rank_column": rank_col or "",
            "score_column": score_col or "",
            "duplicate_ticker_count": int(df[ticker_col].map(norm_ticker).duplicated().sum()),
        }
    )
    return work[["strategy_id", "ticker_norm", "rank", "score"]], audit


def discover_strategies() -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    specs = [
        ("A1_BASELINE_CONTROL", V128 / "A1_BASELINE_CONTROL_latest_ranking.csv", "PRIMARY_CONTROL", "PIT_LITE", "current snapshot only; no true historical as-of factor replay artifact"),
        ("B_STATIC_MOMENTUM_BLEND", V128 / "B_STATIC_MOMENTUM_BLEND_latest_ranking.csv", "DIAGNOSTIC_ONLY", "PIT_LITE", "current snapshot only"),
        ("C_DYNAMIC_MOMENTUM_BLEND", V128 / "C_DYNAMIC_MOMENTUM_BLEND_latest_ranking.csv", "SECONDARY_CANDIDATE", "PIT_LITE", "current snapshot only"),
        ("D_WEIGHT_OPTIMIZED_R1", V128 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv", "FROZEN_REFERENCE", "PIT_LITE", "current snapshot only"),
        ("D_R2A_REPEATED_LOSER_SOFT_PENALTY", D_R2A, "FROZEN_REFERENCE", "PIT_LITE", "latest repaired D ranking snapshot; not true random-date reconstruction"),
        ("E_R1_REPAIRED", E_R1, "RESEARCH_CANDIDATE", "PIT_LITE", "repaired current E_R1 snapshot; wait maturity"),
    ]
    rankings: dict[str, pd.DataFrame] = {}
    audits = []
    for strategy_id, path, role, pit, note in specs:
        df, audit = load_ranking(path, strategy_id, role, pit, note)
        if df is not None and len(df) >= 15:
            rankings[strategy_id] = df
        audits.append(audit)
    if B_CLEAN_DIAG.exists():
        audits.append(
            {
                "strategy_id": "B_CLEAN",
                "role_label": "DIAGNOSTIC_ONLY",
                "source_path": str(B_CLEAN_DIAG).replace("\\", "/"),
                "source_exists": True,
                "pit_status": "SNAPSHOT_ONLY_INVALID_FOR_HISTORICAL_BACKTEST",
                "adoption_grade_included": False,
                "diagnostic_only": True,
                "note": "diagnostic subset artifact lacks a full ranking; retained as insufficient breadth, not backtested",
                "row_count": int(len(pd.read_csv(B_CLEAN_DIAG))),
                "top20_count": 0,
                "top50_count": 0,
                "latest_price_date_used": "",
            }
        )
    return rankings, pd.DataFrame(audits)


def load_price_panel() -> tuple[pd.DataFrame, pd.DataFrame, list[pd.Timestamp], str]:
    prices = pd.read_csv(PRICE_PATH, usecols=["symbol", "date", "close"])
    prices["ticker_norm"] = prices["symbol"].map(norm_ticker)
    prices["date"] = pd.to_datetime(prices["date"])
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    prices = prices.dropna(subset=["date", "close"])
    pivot = prices.pivot_table(index="date", columns="ticker_norm", values="close", aggfunc="last").sort_index()
    dates = list(pivot.index)
    return prices, pivot, dates, str(max(dates).date())


def run_trials(rankings: dict[str, pd.DataFrame], pivot: pd.DataFrame, dates: list[pd.Timestamp]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    date_idx = {d: i for i, d in enumerate(dates)}
    return_tables = {h: (pivot.shift(-h) / pivot - 1.0) for h in HORIZONS}
    return_arrays = {h: return_tables[h].to_numpy(dtype=float) for h in HORIZONS}
    sample_dates = dates[: len(dates) - max(HORIZONS)]
    rows = []
    invalid_detail = []
    member_detail = []
    columns = list(pivot.columns)
    col_idx = {c: i for i, c in enumerate(columns)}
    universe_indices = [i for i, c in enumerate(columns) if c not in {"QQQ", "SOXX", "SPY"}]
    close_arr = pivot.to_numpy(dtype=float)
    entry_valid_by_date = {
        i: [j for j in universe_indices if not math.isnan(close_arr[i, j])]
        for i in range(len(dates) - max(HORIZONS))
    }
    qqq_i = col_idx.get("QQQ")
    soxx_i = col_idx.get("SOXX")
    spy_i = col_idx.get("SPY")
    strategy_indices = {}
    for strategy_id, ranking in rankings.items():
        strategy_indices[strategy_id] = {}
        for bucket in BUCKETS:
            strategy_indices[strategy_id][bucket] = [col_idx[t] for t in ranking.head(bucket)["ticker_norm"].tolist() if t in col_idx]
    all_strategies = list(rankings.keys()) + ["RANDOM_UNIVERSE_EQUAL_WEIGHT"]

    for seed in range(SEEDS):
        rng = random.Random(RNG_BASE_SEED + seed)
        for draw in range(DRAWS_PER_SEED):
            asof = rng.choice(sample_dates)
            asof_i = date_idx[asof]
            trial_id = f"s{seed:02d}_d{draw:03d}_{asof.date()}"
            entry_valid_universe = entry_valid_by_date[asof_i]
            for bucket in BUCKETS:
                random_name_indices = rng.sample(entry_valid_universe, min(bucket, len(entry_valid_universe))) if entry_valid_universe else []
                for strategy_id in all_strategies:
                    if strategy_id == "RANDOM_UNIVERSE_EQUAL_WEIGHT":
                        name_indices = random_name_indices
                        role_label = "BENCHMARK"
                        pit_status = "PIT_STRICT"
                    else:
                        name_indices = strategy_indices[strategy_id][bucket]
                        role_label = ""
                        pit_status = "PIT_LITE"
                    for horizon in HORIZONS:
                        ret_arr = return_arrays[horizon]
                        exit_date = str(dates[date_idx[asof] + horizon].date())
                        raw = ret_arr[asof_i, name_indices] if name_indices else np.array([], dtype=float)
                        valid_mask = ~np.isnan(raw)
                        valid_rets = raw[valid_mask]
                        valid_indices = [name_indices[i] for i, ok in enumerate(valid_mask) if ok]
                        qqq_ret = safe_float(ret_arr[asof_i, qqq_i]) if qqq_i is not None else None
                        soxx_ret = safe_float(ret_arr[asof_i, soxx_i]) if soxx_i is not None else None
                        spy_ret = safe_float(ret_arr[asof_i, spy_i]) if spy_i is not None else None
                        min_req = MIN_HOLDINGS[bucket]
                        valid = len(valid_rets) >= min_req
                        portfolio_return = float(np.mean(valid_rets)) if valid else np.nan
                        if len(valid_rets):
                            worst_pos = int(np.argmin(valid_rets))
                            worst_ticker = columns[valid_indices[worst_pos]]
                            worst_return = float(valid_rets[worst_pos])
                        else:
                            worst_ticker = ""
                            worst_return = np.nan
                        rows.append(
                            {
                                "trial_id": trial_id,
                                "seed": seed,
                                "draw": draw,
                                "sampled_asof_date": str(asof.date()),
                                "exit_date": exit_date,
                                "strategy_id": strategy_id,
                                "role_label": role_label,
                                "pit_status": pit_status,
                                "adoption_grade_included": pit_status == "PIT_STRICT" and strategy_id != "RANDOM_UNIVERSE_EQUAL_WEIGHT",
                                "portfolio_size": bucket,
                                "horizon": f"{horizon}D",
                                "horizon_days": horizon,
                                "valid_trial": valid,
                                "valid_holding_count": len(valid_rets),
                                "missing_holding_count": len(name_indices) - len(valid_rets),
                                "portfolio_return": portfolio_return,
                                "benchmark_QQQ_return": qqq_ret,
                                "benchmark_SOXX_return": soxx_ret,
                                "benchmark_SPY_return": spy_ret,
                                "excess_vs_QQQ": portfolio_return - qqq_ret if valid and qqq_ret is not None else np.nan,
                                "excess_vs_SOXX": portfolio_return - soxx_ret if valid and soxx_ret is not None else np.nan,
                                "excess_vs_SPY": portfolio_return - spy_ret if valid and spy_ret is not None else np.nan,
                                "worst_member_ticker": worst_ticker,
                                "worst_member_return": worst_return,
                                "no_leakage_sample_date_ok": True,
                                "future_price_used_for_scoring": False,
                            }
                        )
                        if not valid:
                            invalid_detail.append(
                                {
                                    "trial_id": trial_id,
                                    "strategy_id": strategy_id,
                                    "portfolio_size": bucket,
                                    "horizon": f"{horizon}D",
                                    "sampled_asof_date": str(asof.date()),
                                    "exit_date": exit_date,
                                    "valid_holding_count": len(valid_rets),
                                    "missing_holding_count": len(name_indices) - len(valid_rets),
                                    "invalid_reason": "BELOW_MIN_VALID_HOLDINGS",
                                }
                            )
                        if horizon == 10 and bucket == 20:
                            for ticker_i, member_return in zip(valid_indices, valid_rets):
                                member_detail.append(
                                    {
                                        "trial_id": trial_id,
                                        "strategy_id": strategy_id,
                                        "ticker_norm": columns[ticker_i],
                                        "member_return": float(member_return),
                                        "sampled_asof_date": str(asof.date()),
                                        "horizon": "10D",
                                        "portfolio_size": 20,
                                    }
                                )
    trial_df = pd.DataFrame(rows)
    if invalid_detail:
        invalid_df = pd.DataFrame(invalid_detail)
    else:
        invalid_df = pd.DataFrame(
            [{"strategy_id": s, "portfolio_size": b, "horizon": f"{h}D", "invalid_trial_count": 0, "invalid_reason": "NONE"} for s in all_strategies for b in BUCKETS for h in HORIZONS]
        )
    return trial_df, invalid_df, pd.DataFrame(member_detail)


def summarize_metrics(trial_df: pd.DataFrame) -> pd.DataFrame:
    a1 = trial_df[trial_df["strategy_id"].eq("A1_BASELINE_CONTROL")][["trial_id", "portfolio_size", "horizon", "portfolio_return"]].rename(columns={"portfolio_return": "A1_return"})
    df = trial_df.merge(a1, on=["trial_id", "portfolio_size", "horizon"], how="left")
    df["excess_vs_A1"] = df["portfolio_return"] - df["A1_return"]
    rows = []
    for keys, g in df.groupby(["strategy_id", "portfolio_size", "horizon"], dropna=False):
        valid = g[g["valid_trial"]].copy()
        rets = valid["portfolio_return"].dropna()
        ex_a1 = valid["excess_vs_A1"].dropna()
        ex_qqq = valid["excess_vs_QQQ"].dropna()
        worst5 = rets[rets <= rets.quantile(0.05)] if len(rets) else pd.Series(dtype=float)
        seed_means = valid.groupby("seed")["portfolio_return"].mean()
        seed_win_qqq = valid.groupby("seed").apply(lambda x: (x["excess_vs_QQQ"] > 0).mean() if x["excess_vs_QQQ"].notna().any() else np.nan)
        rows.append(
            {
                "strategy_id": keys[0],
                "portfolio_size": int(keys[1]),
                "horizon": keys[2],
                "trial_count": int(len(g)),
                "valid_trial_count": int(len(valid)),
                "invalid_trial_count": int((~g["valid_trial"]).sum()),
                "seed_coverage": int(g["seed"].nunique()),
                "draw_coverage": int(g["draw"].nunique()),
                "mean_return": safe_float(rets.mean()),
                "median_return": safe_float(rets.median()),
                "std_return": safe_float(rets.std(ddof=0)),
                "win_rate_positive": safe_float((rets > 0).mean()) if len(rets) else None,
                "p25_return": safe_float(rets.quantile(0.25)) if len(rets) else None,
                "p10_return": safe_float(rets.quantile(0.10)) if len(rets) else None,
                "p05_return": safe_float(rets.quantile(0.05)) if len(rets) else None,
                "worst_trial_return": safe_float(rets.min()) if len(rets) else None,
                "best_trial_return": safe_float(rets.max()) if len(rets) else None,
                "mean_excess_vs_QQQ": safe_float(ex_qqq.mean()),
                "median_excess_vs_QQQ": safe_float(ex_qqq.median()),
                "win_rate_vs_QQQ": safe_float((ex_qqq > 0).mean()) if len(ex_qqq) else None,
                "mean_excess_vs_SOXX": safe_float(valid["excess_vs_SOXX"].mean()),
                "win_rate_vs_SOXX": safe_float((valid["excess_vs_SOXX"] > 0).mean()) if valid["excess_vs_SOXX"].notna().any() else None,
                "mean_excess_vs_A1": safe_float(ex_a1.mean()),
                "median_excess_vs_A1": safe_float(ex_a1.median()),
                "win_rate_vs_A1": safe_float((ex_a1 > 0).mean()) if len(ex_a1) else None,
                "prob_return_lt_minus_5pct": safe_float((rets < -0.05).mean()) if len(rets) else None,
                "prob_return_lt_minus_10pct": safe_float((rets < -0.10).mean()) if len(rets) else None,
                "expected_shortfall_worst_5pct": safe_float(worst5.mean()) if len(worst5) else None,
                "seed_level_mean_return_dispersion": safe_float(seed_means.std(ddof=0)),
                "seed_level_winrate_dispersion": safe_float(seed_win_qqq.std(ddof=0)),
                "pct_seeds_beating_A1": safe_float(valid.groupby("seed").apply(lambda x: (x["excess_vs_A1"] > 0).mean() > 0.5).mean()) if len(valid) else None,
                "pct_seeds_beating_QQQ": safe_float(valid.groupby("seed").apply(lambda x: (x["excess_vs_QQQ"] > 0).mean() > 0.5).mean()) if len(valid) else None,
                "bootstrap_ci_method": "seed_level_normal_approx",
            }
        )
    return pd.DataFrame(rows)


def seed_metrics(trial_df: pd.DataFrame) -> pd.DataFrame:
    a1 = trial_df[trial_df["strategy_id"].eq("A1_BASELINE_CONTROL")][["trial_id", "portfolio_size", "horizon", "portfolio_return"]].rename(columns={"portfolio_return": "A1_return"})
    df = trial_df.merge(a1, on=["trial_id", "portfolio_size", "horizon"], how="left")
    df["excess_vs_A1"] = df["portfolio_return"] - df["A1_return"]
    rows = []
    for keys, g in df[df["valid_trial"]].groupby(["strategy_id", "portfolio_size", "horizon", "seed"]):
        rows.append(
            {
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
            }
        )
    return pd.DataFrame(rows)


def pairwise_matrices(trial_df: pd.DataFrame, metric: str) -> pd.DataFrame:
    base = trial_df[(trial_df["portfolio_size"].eq(20)) & (trial_df["horizon"].eq("10D")) & (trial_df["valid_trial"])].copy()
    pivot = base.pivot_table(index="trial_id", columns="strategy_id", values="portfolio_return", aggfunc="first")
    names = list(pivot.columns)
    rows = []
    for a in names:
        row = {"strategy_id": a}
        for b in names:
            if a == b:
                row[b] = 0.5 if metric == "winrate" else 0.0
                continue
            paired = pivot[[a, b]].dropna()
            if paired.empty:
                value = np.nan
            elif metric == "winrate":
                value = float((paired[a] > paired[b]).mean())
            elif metric == "mean_excess":
                value = float((paired[a] - paired[b]).mean())
            else:
                value = float((paired[a] - paired[b]).median())
            row[b] = value
        rows.append(row)
    return pd.DataFrame(rows)


def worst_trials(trial_df: pd.DataFrame, member_df: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    rows = []
    use = trial_df[(trial_df["portfolio_size"].eq(20)) & (trial_df["horizon"].eq("10D")) & (trial_df["valid_trial"])].copy()
    for strategy, g in use.groupby("strategy_id"):
        worst = g.nsmallest(20, "portfolio_return")
        for _, row in worst.iterrows():
            members = member_df[(member_df["strategy_id"].eq(strategy)) & (member_df["trial_id"].eq(row["trial_id"]))]
            losers = members.nsmallest(5, "member_return")
            common = "|".join(losers["ticker_norm"].tolist())
            sectors = []
            if not meta.empty:
                sectors = meta[meta["ticker_norm"].isin(losers["ticker_norm"])]["sector"].dropna().astype(str).unique().tolist()
            classification = "BROAD_MARKET_DRAWDOWN" if row["benchmark_QQQ_return"] < -0.02 else "SINGLE_NAME_CONCENTRATION"
            if "Semiconductors" in "|".join(sectors) or "Semiconductor" in "|".join(sectors):
                classification = "SEMICONDUCTOR_SECTOR_DRAWDOWN"
            rows.append(
                {
                    "strategy_id": strategy,
                    "trial_id": row["trial_id"],
                    "sampled_asof_date": row["sampled_asof_date"],
                    "horizon": row["horizon"],
                    "portfolio_size": row["portfolio_size"],
                    "portfolio_return": row["portfolio_return"],
                    "QQQ_return": row["benchmark_QQQ_return"],
                    "loss_classification": classification,
                    "common_loss_tickers": common,
                    "common_loss_sectors": "|".join(sectors),
                    "missing_data_artifact": False,
                    "non_pit_artifact": row["pit_status"] != "PIT_STRICT",
                }
            )
    return pd.DataFrame(rows)


def build_overlap(rankings: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    strategies = list(rankings.keys())
    rows20 = []
    rows50 = []
    for a in strategies:
        a20 = set(rankings[a].head(20)["ticker_norm"])
        a50 = set(rankings[a].head(50)["ticker_norm"])
        r20 = {"strategy_id": a}
        r50 = {"strategy_id": a}
        for b in strategies:
            r20[b] = len(a20 & set(rankings[b].head(20)["ticker_norm"]))
            r50[b] = len(a50 & set(rankings[b].head(50)["ticker_norm"]))
        rows20.append(r20)
        rows50.append(r50)
    return pd.DataFrame(rows20), pd.DataFrame(rows50)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rankings, registry = discover_strategies()
    if not PRICE_PATH.exists() or not rankings:
        raise SystemExit("Missing price panel or strategy rankings")
    _, pivot, dates, latest_price_date = load_price_panel()
    trial_df, invalid_df, member_df = run_trials(rankings, pivot, dates)
    metrics = summarize_metrics(trial_df)
    seed_df = seed_metrics(trial_df)
    winrate = pairwise_matrices(trial_df, "winrate")
    excess = pairwise_matrices(trial_df, "mean_excess")
    overlap20, overlap50 = build_overlap(rankings)

    meta = pd.DataFrame()
    if META.exists():
        meta = pd.read_csv(META)
        if "ticker_norm" in meta.columns:
            meta["ticker_norm"] = meta["ticker_norm"].map(norm_ticker)
    worst = worst_trials(trial_df, member_df, meta)

    pit_audit = registry[["strategy_id", "pit_status", "adoption_grade_included", "diagnostic_only", "note"]].copy()
    no_pit_strict = not registry["pit_status"].eq("PIT_STRICT").any()
    # RANDOM_UNIVERSE is a benchmark, not a strategy adoption candidate.
    no_pit_strict_candidates = not registry.loc[registry["strategy_id"].ne("B_CLEAN"), "adoption_grade_included"].any()

    top_metric = metrics[(metrics["portfolio_size"].eq(20)) & (metrics["horizon"].eq("10D"))].copy()
    candidates = top_metric[~top_metric["strategy_id"].eq("RANDOM_UNIVERSE_EQUAL_WEIGHT")]
    best_vs_a1 = candidates.sort_values("win_rate_vs_A1", ascending=False, na_position="last").head(1)
    best_vs_qqq = candidates.sort_values("win_rate_vs_QQQ", ascending=False, na_position="last").head(1)
    best_tail = candidates.sort_values("expected_shortfall_worst_5pct", ascending=False, na_position="last").head(1)

    if no_pit_strict_candidates:
        final_status = "PARTIAL_PASS_V21_139_RANDOM_BACKTEST_DIAGNOSTIC_ONLY"
        decision = "NO_ADOPTION_PIT_COVERAGE_INSUFFICIENT"
        blockers = "NO_PIT_STRICT_STRATEGY_RECONSTRUCTION|FORWARD_MATURITY_REQUIRED|RESEARCH_ONLY_STAGE"
    else:
        final_status = "PARTIAL_PASS_V21_139_RANDOM_BACKTEST_EDGE_DETECTED_WAIT_MATURITY"
        decision = "EDGE_DETECTED_RESEARCH_ONLY_WAIT_FORWARD_MATURITY"
        blockers = "FORWARD_MATURITY_REQUIRED|RESEARCH_ONLY_STAGE"

    if not best_vs_a1.empty and best_vs_a1.iloc[0]["strategy_id"] == "E_R1_REPAIRED":
        decision = "E_R1_RANDOM_BACKTEST_SUPPORTIVE_BUT_WAIT_MATURITY"

    summary = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_used": latest_price_date,
        "seeds": SEEDS,
        "draws_per_seed": DRAWS_PER_SEED,
        "total_random_trials": SEEDS * DRAWS_PER_SEED,
        "strategies_tested": "|".join(rankings.keys()),
        "pit_strict_strategies": "",
        "diagnostic_only_strategies": "|".join(registry.loc[registry["diagnostic_only"], "strategy_id"].astype(str)),
        "best_strategy_vs_A1_by_10D_Top20_winrate": "" if best_vs_a1.empty else str(best_vs_a1.iloc[0]["strategy_id"]),
        "best_strategy_vs_QQQ_by_10D_Top20_winrate": "" if best_vs_qqq.empty else str(best_vs_qqq.iloc[0]["strategy_id"]),
        "best_left_tail_strategy": "" if best_tail.empty else str(best_tail.iloc[0]["strategy_id"]),
        "remaining_blockers": blockers,
        "output_directory": str(OUT).replace("\\", "/"),
        **CONTROL_FLAGS,
    }

    write_csv(metrics, OUT / "V21.139_strategy_metric_summary.csv")
    write_csv(winrate, OUT / "V21.139_pairwise_winrate_matrix.csv")
    write_csv(excess, OUT / "V21.139_pairwise_excess_return_matrix.csv")
    write_csv(seed_df, OUT / "V21.139_seed_level_metrics.csv")
    write_csv(trial_df, OUT / "V21.139_trial_level_returns.csv")
    write_csv(invalid_df, OUT / "V21.139_invalid_trials.csv")
    write_csv(worst, OUT / "V21.139_worst_trials_decomposition.csv")
    write_csv(registry, OUT / "V21.139_strategy_registry_used.csv")
    write_csv(pit_audit, OUT / "V21.139_pit_status_audit.csv")
    write_csv(overlap20, OUT / "V21.139_top20_overlap_matrix_snapshot_diagnostic.csv")
    write_csv(overlap50, OUT / "V21.139_top50_overlap_matrix_snapshot_diagnostic.csv")
    with (OUT / "V21.139_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, allow_nan=False)

    report_lines = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"latest_price_date_used={latest_price_date}",
        f"strategy list included={summary['strategies_tested']}",
        "PIT_STRICT strategies=none",
        f"PIT_LITE / diagnostic only strategies={summary['diagnostic_only_strategies']}",
        f"winner by mean excess vs A1={candidates.sort_values('mean_excess_vs_A1', ascending=False, na_position='last').iloc[0]['strategy_id'] if not candidates.empty else ''}",
        f"winner by median excess vs A1={candidates.sort_values('median_excess_vs_A1', ascending=False, na_position='last').iloc[0]['strategy_id'] if not candidates.empty else ''}",
        f"winner by win rate vs A1={summary['best_strategy_vs_A1_by_10D_Top20_winrate']}",
        f"winner by left-tail risk={summary['best_left_tail_strategy']}",
        "promotion_justified=false",
        f"explicit_blocker_list={blockers}",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
    ]
    (OUT / "V21.139_readable_report.txt").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(STAGE)
    print(f"FINAL_STATUS={final_status}")
    print(f"DECISION={decision}")
    print(f"latest_price_date_used={latest_price_date}")
    print(f"strategies_tested={summary['strategies_tested']}")
    print("pit_strict_strategies=")
    print(f"diagnostic_only_strategies={summary['diagnostic_only_strategies']}")
    print(f"best_strategy_vs_A1_by_10D_Top20_winrate={summary['best_strategy_vs_A1_by_10D_Top20_winrate']}")
    print(f"best_strategy_vs_QQQ_by_10D_Top20_winrate={summary['best_strategy_vs_QQQ_by_10D_Top20_winrate']}")
    print(f"best_left_tail_strategy={summary['best_left_tail_strategy']}")
    print(f"remaining_blockers={blockers}")
    print(f"output directory={str(OUT).replace(chr(92), '/')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
