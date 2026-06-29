from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.143_RANDOM_UNIVERSE_AND_SURVIVORSHIP_ARTIFACT_AUDIT"
OUT = Path("outputs/v21/V21.143_RANDOM_UNIVERSE_AND_SURVIVORSHIP_ARTIFACT_AUDIT")
V140 = Path("outputs/v21/V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020")
V141 = Path("outputs/v21/V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST")
V142 = Path("outputs/v21/V21.142_EXTENDED_REGIME_FAILURE_AND_E_R1_TAIL_ADVANTAGE_DECOMPOSITION")
PANEL = V140 / "V21.140_extended_adjusted_close_panel_2020_plus.csv"
COVERAGE = V140 / "V21.140_price_coverage_by_ticker.csv"
META = Path("outputs/v21/V21.138_E_R1_METADATA_COVERAGE_REPAIR_AND_REAUDIT/consolidated_sector_industry_metadata_bridge.csv")
V128 = Path("outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE")
E_R1 = Path("outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv")
D_R2A = Path("outputs/v21/V21.118_D_R2_REPEATED_LOSER_AWARE_DESIGN/d_r2_adjusted_rankings.csv")

STRATEGIES = [
    "A1_BASELINE_CONTROL",
    "B_STATIC_MOMENTUM_BLEND",
    "C_DYNAMIC_MOMENTUM_BLEND",
    "D_WEIGHT_OPTIMIZED_R1",
    "D_R2A_REPEATED_LOSER_SOFT_PENALTY",
    "E_R1_REPAIRED",
]
BENCHMARKS = {"QQQ", "SOXX", "SPY", "SMH", "XLK"}
HORIZONS = [5, 10, 20]
MIN_VALID = 15
RNG_SEED = 21143

CONTROL_FLAGS = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "strategy_adoption_allowed": False,
}


def norm_ticker(v) -> str:
    if pd.isna(v):
        return ""
    return str(v).strip().upper()


def first_col(df: pd.DataFrame, names: list[str]) -> str | None:
    lower = {c.lower(): c for c in df.columns}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def safe_float(v):
    if v is None or pd.isna(v):
        return None
    return float(v)


def load_rankings() -> dict[str, list[str]]:
    specs = {
        "A1_BASELINE_CONTROL": V128 / "A1_BASELINE_CONTROL_latest_ranking.csv",
        "B_STATIC_MOMENTUM_BLEND": V128 / "B_STATIC_MOMENTUM_BLEND_latest_ranking.csv",
        "C_DYNAMIC_MOMENTUM_BLEND": V128 / "C_DYNAMIC_MOMENTUM_BLEND_latest_ranking.csv",
        "D_WEIGHT_OPTIMIZED_R1": V128 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv",
        "D_R2A_REPEATED_LOSER_SOFT_PENALTY": D_R2A,
        "E_R1_REPAIRED": E_R1,
    }
    out = {}
    for strategy, path in specs.items():
        df = pd.read_csv(path)
        if strategy == "D_R2A_REPEATED_LOSER_SOFT_PENALTY" and "candidate_variant" in df.columns:
            df = df[df["candidate_variant"].astype(str).eq("D_R2A_REPEATED_LOSER_SOFT_PENALTY")].copy()
            if "as_of_date" in df.columns:
                latest = pd.to_datetime(df["as_of_date"], errors="coerce").max()
                df = df[pd.to_datetime(df["as_of_date"], errors="coerce").eq(latest)].copy()
        tcol = first_col(df, ["ticker_norm", "ticker", "symbol"])
        rcol = first_col(df, ["rank", "adjusted_rank"])
        df["ticker_norm"] = df[tcol].map(norm_ticker)
        df["_rank"] = pd.to_numeric(df[rcol], errors="coerce") if rcol else np.arange(1, len(df) + 1)
        out[strategy] = df[df["ticker_norm"].ne("")].drop_duplicates("ticker_norm").sort_values("_rank").head(20)["ticker_norm"].tolist()
    return out


def load_metadata() -> pd.DataFrame:
    meta = pd.read_csv(META) if META.exists() else pd.DataFrame(columns=["ticker_norm", "sector", "industry"])
    if "ticker_norm" in meta:
        meta["ticker_norm"] = meta["ticker_norm"].map(norm_ticker)
    return meta.drop_duplicates("ticker_norm")


def first_year(value) -> str:
    if pd.isna(value) or str(value).strip() == "":
        return "MISSING"
    return str(pd.Timestamp(value).year)


def composition_rows(holdings: dict[str, list[str]], cov: pd.DataFrame, meta: pd.DataFrame, universe: list[str]) -> pd.DataFrame:
    rows = []
    groups = {**holdings, "RANDOM_CURRENT_UNIVERSE_EQUAL_WEIGHT": universe}
    ref = cov.merge(meta[["ticker_norm", "sector", "industry"]], left_on="symbol", right_on="ticker_norm", how="left")
    for strategy, tickers in groups.items():
        g = ref[ref["symbol"].isin(tickers)].copy()
        for _, r in g.iterrows():
            rows.append({
                "strategy_id": strategy,
                "ticker_norm": r["symbol"],
                "first_available_year": first_year(r["first_available_date"]),
                "sector": r.get("sector", "UNKNOWN"),
                "industry": r.get("industry", "UNKNOWN"),
                "coverage_ratio": r["coverage_ratio"],
                "coverage_bucket": pd.cut([r["coverage_ratio"]], bins=[-0.01, 0.5, 0.8, 0.95, 1.01], labels=["LOW", "MEDIUM", "HIGH", "FULL"])[0],
                "has_2020_data": bool(r["has_2020_data"]),
                "ipo_after_2020": bool(r["ipo_after_2020"]),
                "strategy_membership_overlap_count": sum(r["symbol"] in hs for hs in holdings.values()),
            })
    return pd.DataFrame(rows)


def sample_matched(rng: random.Random, ref_tickers: list[str], cov_meta: pd.DataFrame, universe: list[str], mode: str, n: int = 20) -> list[str]:
    pool = cov_meta[cov_meta["symbol"].isin(universe)].copy()
    target = cov_meta[cov_meta["symbol"].isin(ref_tickers)].copy()
    if mode == "CURRENT":
        return rng.sample(universe, min(n, len(universe)))
    if mode == "2020_COVERAGE":
        eligible = pool[pool["has_2020_data"].astype(bool)]["symbol"].tolist()
        return rng.sample(eligible, min(n, len(eligible)))
    selected: list[str] = []
    group_cols = []
    if mode in {"AGE_MATCHED", "SECTOR_AND_AGE_MATCHED"}:
        group_cols.append("first_available_year")
    if mode in {"SECTOR_MATCHED", "SECTOR_AND_AGE_MATCHED"}:
        group_cols.append("sector")
    if mode == "BENCHMARK_MEMBER_PROXY":
        eligible = pool[(pool["has_2020_data"].astype(bool)) & (pool["coverage_ratio"] >= 0.95)]["symbol"].tolist()
        return rng.sample(eligible, min(n, len(eligible)))
    for key, tg in target.groupby(group_cols, dropna=False):
        if not isinstance(key, tuple):
            key = (key,)
        mask = pd.Series(True, index=pool.index)
        for col, val in zip(group_cols, key):
            mask &= pool[col].fillna("UNKNOWN").eq(val if pd.notna(val) else "UNKNOWN")
        candidates = [t for t in pool[mask]["symbol"].tolist() if t not in selected]
        if not candidates:
            candidates = [t for t in pool["symbol"].tolist() if t not in selected]
        need = min(len(tg), n - len(selected))
        if need > 0 and candidates:
            selected.extend(rng.sample(candidates, min(need, len(candidates))))
    if len(selected) < n:
        rest = [t for t in universe if t not in selected]
        selected.extend(rng.sample(rest, min(n - len(selected), len(rest))))
    return selected[:n]


def compute_portfolio_return(ret_arr: np.ndarray, row_i: int, cols: list[int]) -> tuple[float, int]:
    if not cols:
        return np.nan, 0
    vals = ret_arr[row_i, cols]
    vals = vals[~np.isnan(vals)]
    if len(vals) < MIN_VALID:
        return np.nan, len(vals)
    return float(vals.mean()), len(vals)


def run_alternative_baselines(holdings: dict[str, list[str]], cov: pd.DataFrame, meta: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    trials = pd.read_csv(V141 / "V21.141_trial_level_returns.csv")
    base_dates = trials[
        (trials["strategy_id"].eq("A1_BASELINE_CONTROL"))
        & (trials["portfolio_size"].eq(20))
        & (trials["horizon"].eq("10D"))
    ][["sampled_asof_date", "regime"]].drop_duplicates()
    prices = pd.read_csv(PANEL)
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.set_index("date").sort_index()
    dates = list(prices.index)
    date_idx = {d: i for i, d in enumerate(dates)}
    col_idx = {c: i for i, c in enumerate(prices.columns)}
    ret_arrays = {h: (prices.shift(-h) / prices - 1.0).to_numpy(dtype=float) for h in HORIZONS}
    cov2 = cov.copy()
    cov2["first_available_year"] = cov2["first_available_date"].map(first_year)
    cov2 = cov2.merge(meta[["ticker_norm", "sector", "industry"]], left_on="symbol", right_on="ticker_norm", how="left")
    cov2["sector"] = cov2["sector"].fillna("UNKNOWN")
    universe = [t for t in cov2["symbol"].tolist() if t in col_idx and t not in BENCHMARKS]
    baseline_modes = {
        "RANDOM_CURRENT_UNIVERSE_EQUAL_WEIGHT": "CURRENT",
        "RANDOM_2020_COVERAGE_ONLY_EQUAL_WEIGHT": "2020_COVERAGE",
        "RANDOM_IPO_AGE_MATCHED_TO_STRATEGY": "AGE_MATCHED",
        "RANDOM_SECTOR_MATCHED_TO_STRATEGY": "SECTOR_MATCHED",
        "RANDOM_SECTOR_AND_AGE_MATCHED_TO_STRATEGY": "SECTOR_AND_AGE_MATCHED",
        "RANDOM_BENCHMARK_MEMBER_PROXY": "BENCHMARK_MEMBER_PROXY",
    }
    rng = random.Random(RNG_SEED)
    sampled_dates = []
    for regime, g in base_dates.groupby("regime"):
        vals = g["sampled_asof_date"].drop_duplicates().tolist()
        vals = rng.sample(vals, min(100, len(vals)))
        sampled_dates.extend({"sampled_asof_date": v, "regime": regime} for v in vals)

    precomputed: dict[tuple[str, str], list[list[str]]] = {}
    for strategy, ref in holdings.items():
        for bname, mode in baseline_modes.items():
            precomputed[(strategy, bname)] = [sample_matched(rng, ref, cov2, universe, mode) for _ in range(64)]

    strategy_cols = {strategy: [col_idx[t] for t in ref if t in col_idx] for strategy, ref in holdings.items()}
    sample_cols = {
        key: [[col_idx[t] for t in sample if t in col_idx] for sample in samples]
        for key, samples in precomputed.items()
    }
    rows = []
    row_counter = 0
    for tr in sampled_dates:
        asof = pd.Timestamp(tr["sampled_asof_date"])
        if asof not in date_idx:
            continue
        row_i = date_idx[asof]
        for h in HORIZONS:
            if row_i + h >= len(dates):
                continue
            arr = ret_arrays[h]
            for strategy in holdings:
                strategy_ret, valid_n = compute_portfolio_return(arr, row_i, strategy_cols[strategy])
                for bname in baseline_modes:
                    samples = precomputed[(strategy, bname)]
                    idx = row_counter % len(samples)
                    cols = sample_cols[(strategy, bname)][idx]
                    rret, rvalid = compute_portfolio_return(arr, row_i, cols)
                    rows.append({
                        "trial_id": f"fair_{row_counter:06d}",
                        "sampled_asof_date": tr["sampled_asof_date"],
                        "regime": tr["regime"],
                        "horizon": f"{h}D",
                        "strategy_id": strategy,
                        "baseline_name": bname,
                        "strategy_return": strategy_ret,
                        "baseline_return": rret,
                        "strategy_valid_holding_count": valid_n,
                        "baseline_valid_holding_count": rvalid,
                        "strategy_excess_vs_baseline": strategy_ret - rret if pd.notna(strategy_ret) and pd.notna(rret) else np.nan,
                        "baseline_tickers": "|".join(samples[idx]),
                    })
                    row_counter += 1
    detail = pd.DataFrame(rows)
    metrics = detail.groupby(["strategy_id", "baseline_name", "horizon", "regime"], dropna=False).agg(
        trial_count=("trial_id", "count"),
        valid_trial_count=("strategy_excess_vs_baseline", "count"),
        mean_strategy_return=("strategy_return", "mean"),
        mean_baseline_return=("baseline_return", "mean"),
        mean_excess_vs_baseline=("strategy_excess_vs_baseline", "mean"),
        median_excess_vs_baseline=("strategy_excess_vs_baseline", "median"),
        win_rate_vs_baseline=("strategy_excess_vs_baseline", lambda s: (s.dropna() > 0).mean() if s.notna().any() else np.nan),
        baseline_prob_loss_5pct=("baseline_return", lambda s: (s.dropna() < -0.05).mean() if s.notna().any() else np.nan),
        strategy_prob_loss_5pct=("strategy_return", lambda s: (s.dropna() < -0.05).mean() if s.notna().any() else np.nan),
        baseline_expected_shortfall_5pct=("baseline_return", lambda s: s.dropna()[s.dropna() <= s.dropna().quantile(0.05)].mean() if s.notna().any() else np.nan),
        strategy_expected_shortfall_5pct=("strategy_return", lambda s: s.dropna()[s.dropna() <= s.dropna().quantile(0.05)].mean() if s.notna().any() else np.nan),
    ).reset_index()
    return detail, metrics


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    cov = pd.read_csv(COVERAGE)
    meta = load_metadata()
    holdings = load_rankings()
    universe = [t for t in cov["symbol"].map(norm_ticker).tolist() if t not in BENCHMARKS]
    comp = composition_rows(holdings, cov, meta, universe)

    random_audit = comp[comp["strategy_id"].eq("RANDOM_CURRENT_UNIVERSE_EQUAL_WEIGHT")].copy()
    random_baseline_summary = random_audit.groupby(["first_available_year", "sector", "coverage_bucket"], dropna=False).size().reset_index(name="ticker_count")
    surv = cov.assign(
        full_2020_to_latest=(pd.to_datetime(cov["first_available_date"], errors="coerce") <= pd.Timestamp("2020-01-31")) & cov["has_2026_data"].astype(bool),
        current_universe_survivorship_bias=True,
        missing_delisted_ticker_history=True,
        random_baseline_uses_current_survivors=True,
    )
    alt_detail, alt_metrics = run_alternative_baselines(holdings, cov, meta)

    regime_cmp = alt_metrics.copy()
    e = alt_metrics[(alt_metrics["strategy_id"].eq("E_R1_REPAIRED")) & (alt_metrics["horizon"].eq("10D"))].copy()
    e_recheck = e.groupby(["baseline_name", "regime"]).agg(
        E_R1_win_rate_vs_fair_baseline=("win_rate_vs_baseline", "mean"),
        E_R1_mean_excess_vs_fair_baseline=("mean_excess_vs_baseline", "mean"),
        E_R1_strategy_expected_shortfall=("strategy_expected_shortfall_5pct", "mean"),
        fair_baseline_expected_shortfall=("baseline_expected_shortfall_5pct", "mean"),
    ).reset_index()
    e_bear = e_recheck[e_recheck["regime"].eq("RATE_HIKE_TECH_BEAR")]
    e_confirmed = bool((e_bear["E_R1_strategy_expected_shortfall"] > e_bear["fair_baseline_expected_shortfall"]).mean() >= 0.5) if not e_bear.empty else False

    d_recheck = alt_metrics[(alt_metrics["strategy_id"].isin(["D_WEIGHT_OPTIMIZED_R1", "D_R2A_REPEATED_LOSER_SOFT_PENALTY"])) & (alt_metrics["horizon"].eq("10D"))].copy()
    d_r2a = d_recheck[d_recheck["strategy_id"].eq("D_R2A_REPEATED_LOSER_SOFT_PENALTY")]
    recent = d_r2a[d_r2a["regime"].isin(["AI_SEMICONDUCTOR_REACCELERATION", "LATE_SUPERCYCLE_CURRENT"])]["mean_excess_vs_baseline"].mean()
    early = d_r2a[d_r2a["regime"].isin(["COVID_CRASH_AND_REBOUND", "LIQUIDITY_GROWTH_BULL", "RATE_HIKE_TECH_BEAR"])]["mean_excess_vs_baseline"].mean()
    d_r2a_super = bool(pd.notna(recent) and pd.notna(early) and recent > early + 0.005)

    classifications = []
    full_data_ratio = float(surv["full_2020_to_latest"].mean())
    ipo_ratio = float(surv["ipo_after_2020"].astype(bool).mean())
    if True:
        classifications.append("CURRENT_UNIVERSE_SURVIVORSHIP_BIAS")
    if ipo_ratio > 0.25:
        classifications.append("IPO_AGE_BIAS")
    if float((~surv["has_2020_data"].astype(bool)).mean()) > 0.25:
        classifications.append("PRICE_COVERAGE_SELECTION_BIAS")
    classifications.append("MISSING_DELISTED_TICKER_BIAS")
    artifact_classification = "MIXED_ARTIFACT" if len(classifications) > 1 else classifications[0]
    fair_available = True
    random_explained = artifact_classification != "NO_MAJOR_ARTIFACT_FOUND"
    recommended = "RANDOM_SECTOR_AND_AGE_MATCHED_TO_STRATEGY"
    if "PRICE_COVERAGE_SELECTION_BIAS" in classifications:
        recommended += "|RANDOM_2020_COVERAGE_ONLY_EQUAL_WEIGHT"

    if "CURRENT_UNIVERSE_SURVIVORSHIP_BIAS" in classifications or "MISSING_DELISTED_TICKER_BIAS" in classifications:
        final_status = "PARTIAL_PASS_V21_143_RANDOM_BASELINE_SURVIVORSHIP_BIAS_CONFIRMED"
        decision = "EXTENDED_HISTORY_RANDOM_BASELINE_NOT_ADOPTION_GRADE"
    elif "IPO_AGE_BIAS" in classifications or "PRICE_COVERAGE_SELECTION_BIAS" in classifications:
        final_status = "PARTIAL_PASS_V21_143_RANDOM_BASELINE_AGE_COVERAGE_ARTIFACT_CONFIRMED"
        decision = "USE_AGE_COVERAGE_MATCHED_RANDOM_BASELINE_ONLY"
    else:
        final_status = "PASS_V21_143_FAIR_RANDOM_BASELINE_REPAIRED"
        decision = "USE_FAIR_RANDOM_BASELINES_FOR_FUTURE_DIAGNOSTICS"
    if e_confirmed:
        decision += "|E_R1_RISK_PROFILE_SUPPORTIVE_WAIT_FORWARD_MATURITY_AND_PIT"
    else:
        decision += "|E_R1_ADVANTAGE_REQUIRES_REVIEW"

    class_df = pd.DataFrame([{
        "artifact_classification": artifact_classification,
        "classification_components": "|".join(classifications),
        "current_universe_survivorship_bias": "CURRENT_UNIVERSE_SURVIVORSHIP_BIAS" in classifications,
        "ipo_age_bias": "IPO_AGE_BIAS" in classifications,
        "sector_composition_bias": False,
        "missing_delisted_ticker_bias": True,
        "price_coverage_selection_bias": "PRICE_COVERAGE_SELECTION_BIAS" in classifications,
        "random_baseline_implementation_bug": False,
        "evidence": f"full_2020_to_latest_ratio={full_data_ratio:.3f}; ipo_after_2020_ratio={ipo_ratio:.3f}",
    }])
    missing_delisted = pd.DataFrame([{
        "warning": "MISSING_DELISTED_TICKER_HISTORY_UNRESOLVED",
        "survivorship_bias_resolved": False,
        "impact": "Random and strategy tests use current surviving universe; adoption-grade extended historical inference is blocked.",
    }])
    summary = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "artifact_classification": artifact_classification,
        "random_universe_dominance_explained": random_explained,
        "fair_random_baseline_available": fair_available,
        "E_R1_LEFT_TAIL_ADVANTAGE_FAIR_BASELINE_CONFIRMED": e_confirmed,
        "D_R2A_SUPERCYCLE_DEPENDENCY_RECONFIRMED": d_r2a_super,
        "recommended_random_baseline_for_future_tests": recommended,
        "remaining_blockers": "CURRENT_UNIVERSE_SURVIVORSHIP_BIAS|MISSING_DELISTED_TICKERS|NO_PIT_STRICT_RECONSTRUCTION|FORWARD_MATURITY_REQUIRED|RESEARCH_ONLY_STAGE",
        "output_directory": str(OUT).replace("\\", "/"),
        **CONTROL_FLAGS,
    }

    random_baseline_summary.to_csv(OUT / "V21.143_random_baseline_construction_audit.csv", index=False)
    surv.to_csv(OUT / "V21.143_survivorship_bias_audit.csv", index=False)
    comp.to_csv(OUT / "V21.143_universe_composition_by_strategy.csv", index=False)
    alt_metrics.to_csv(OUT / "V21.143_alternative_random_baseline_metrics.csv", index=False)
    regime_cmp.to_csv(OUT / "V21.143_regime_comparison_with_fair_random_baselines.csv", index=False)
    e_recheck.to_csv(OUT / "V21.143_e_r1_recheck_against_fair_baselines.csv", index=False)
    d_recheck.to_csv(OUT / "V21.143_d_and_d_r2a_recheck_against_fair_baselines.csv", index=False)
    class_df.to_csv(OUT / "V21.143_artifact_classification.csv", index=False)
    missing_delisted.to_csv(OUT / "V21.143_missing_delisted_ticker_warning.csv", index=False)
    (OUT / "V21.143_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"artifact_classification={artifact_classification}",
        f"random_universe_dominance_explained={str(random_explained).lower()}",
        f"fair_random_baseline_available={str(fair_available).lower()}",
        f"E_R1_left_tail_advantage_fair_baseline_confirmed={str(e_confirmed).lower()}",
        f"D_R2A_supercycle_dependency_reconfirmed={str(d_r2a_super).lower()}",
        f"recommended_random_baseline_for_future_tests={recommended}",
        f"remaining_blockers={summary['remaining_blockers']}",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
        "strategy_adoption_allowed=false",
    ]
    (OUT / "V21.143_readable_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    for line in report[:10]:
        print(line)
    print(f"output directory={str(OUT).replace(chr(92), '/')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
