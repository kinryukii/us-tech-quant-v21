from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.142_EXTENDED_REGIME_FAILURE_AND_E_R1_TAIL_ADVANTAGE_DECOMPOSITION"
OUT = Path("outputs/v21/V21.142_EXTENDED_REGIME_FAILURE_AND_E_R1_TAIL_ADVANTAGE_DECOMPOSITION")
V141 = Path("outputs/v21/V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST")
PANEL = Path("outputs/v21/V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020/V21.140_extended_adjusted_close_panel_2020_plus.csv")
META = Path("outputs/v21/V21.138_E_R1_METADATA_COVERAGE_REPAIR_AND_REAUDIT/consolidated_sector_industry_metadata_bridge.csv")
REPEATED = Path("outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE/V21.129_d_repeated_loser_diagnostic.csv")
V128 = Path("outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE")
E_R1 = Path("outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv")
D_R2A = Path("outputs/v21/V21.118_D_R2_REPEATED_LOSER_AWARE_DESIGN/d_r2_adjusted_rankings.csv")

CONTROL_FLAGS = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "strategy_adoption_allowed": False,
}

STRATEGIES = [
    "A1_BASELINE_CONTROL",
    "B_STATIC_MOMENTUM_BLEND",
    "C_DYNAMIC_MOMENTUM_BLEND",
    "D_WEIGHT_OPTIMIZED_R1",
    "D_R2A_REPEATED_LOSER_SOFT_PENALTY",
    "E_R1_REPAIRED",
]


def norm_ticker(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip().upper()


def first_col(df: pd.DataFrame, names: list[str]) -> str | None:
    lower = {c.lower(): c for c in df.columns}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def safe_float(value):
    if value is None or pd.isna(value):
        return None
    return float(value)


def load_rankings() -> dict[str, list[str]]:
    specs = {
        "A1_BASELINE_CONTROL": V128 / "A1_BASELINE_CONTROL_latest_ranking.csv",
        "B_STATIC_MOMENTUM_BLEND": V128 / "B_STATIC_MOMENTUM_BLEND_latest_ranking.csv",
        "C_DYNAMIC_MOMENTUM_BLEND": V128 / "C_DYNAMIC_MOMENTUM_BLEND_latest_ranking.csv",
        "D_WEIGHT_OPTIMIZED_R1": V128 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv",
        "D_R2A_REPEATED_LOSER_SOFT_PENALTY": D_R2A,
        "E_R1_REPAIRED": E_R1,
    }
    out: dict[str, list[str]] = {}
    for strategy, path in specs.items():
        df = pd.read_csv(path)
        tcol = first_col(df, ["ticker_norm", "ticker", "symbol"])
        rcol = first_col(df, ["rank", "adjusted_rank"])
        if strategy == "D_R2A_REPEATED_LOSER_SOFT_PENALTY" and "candidate_variant" in df.columns:
            df = df[df["candidate_variant"].astype(str).eq("D_R2A_REPEATED_LOSER_SOFT_PENALTY")].copy()
            if "as_of_date" in df.columns:
                latest = pd.to_datetime(df["as_of_date"], errors="coerce").max()
                df = df[pd.to_datetime(df["as_of_date"], errors="coerce").eq(latest)].copy()
        df["ticker_norm"] = df[tcol].map(norm_ticker)
        if rcol:
            df["_rank"] = pd.to_numeric(df[rcol], errors="coerce")
        else:
            df["_rank"] = np.arange(1, len(df) + 1)
        out[strategy] = df[df["ticker_norm"].ne("")].drop_duplicates("ticker_norm").sort_values("_rank").head(20)["ticker_norm"].tolist()
    return out


def load_meta() -> pd.DataFrame:
    if not META.exists():
        return pd.DataFrame(columns=["ticker_norm", "sector", "industry"])
    meta = pd.read_csv(META)
    meta["ticker_norm"] = meta["ticker_norm"].map(norm_ticker)
    return meta.drop_duplicates("ticker_norm")


def repeated_loser_set() -> set[str]:
    if not REPEATED.exists():
        return set()
    df = pd.read_csv(REPEATED)
    col = first_col(df, ["ticker", "ticker_norm", "D_repeated_loser_tickers"])
    if col is None:
        return set()
    vals: set[str] = set()
    for v in df[col].dropna().astype(str):
        for part in v.replace(",", "|").split("|"):
            t = norm_ticker(part)
            if t:
                vals.add(t)
    return vals


def reconstruct_members(trials: pd.DataFrame, holdings: dict[str, list[str]]) -> pd.DataFrame:
    prices = pd.read_csv(PANEL)
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.set_index("date").sort_index()
    date_idx = {d: i for i, d in enumerate(prices.index)}
    cols = {c: c for c in prices.columns}
    arr = prices.to_numpy(dtype=float)
    col_idx = {c: i for i, c in enumerate(prices.columns)}
    rows = []
    use = trials[(trials["portfolio_size"].eq(20)) & (trials["horizon"].eq("10D")) & (trials["strategy_id"].isin(holdings))].copy()
    for _, row in use.iterrows():
        asof = pd.Timestamp(row["sampled_asof_date"])
        if asof not in date_idx:
            continue
        i = date_idx[asof]
        if i + 10 >= len(prices.index):
            continue
        for ticker in holdings[row["strategy_id"]]:
            if ticker not in col_idx:
                ret = np.nan
                missing = True
            else:
                entry = arr[i, col_idx[ticker]]
                exit_price = arr[i + 10, col_idx[ticker]]
                missing = bool(np.isnan(entry) or np.isnan(exit_price) or entry <= 0)
                ret = np.nan if missing else float(exit_price / entry - 1.0)
            rows.append({
                "trial_id": row["trial_id"],
                "strategy_id": row["strategy_id"],
                "sampled_asof_date": row["sampled_asof_date"],
                "regime": row["regime"],
                "ticker_norm": ticker,
                "member_return": ret,
                "missing_price_artifact": missing,
            })
    return pd.DataFrame(rows)


def exposure_summary(tickers: list[str], meta: pd.DataFrame, repeated: set[str]) -> dict:
    m = meta[meta["ticker_norm"].isin(tickers)].copy()
    sector_counts = m["sector"].value_counts(normalize=True) if "sector" in m else pd.Series(dtype=float)
    industry_counts = m["industry"].value_counts(normalize=True) if "industry" in m else pd.Series(dtype=float)
    semi_mask = m.astype(str).apply(lambda col: col.str.contains("semi|semiconductor|chip", case=False, na=False)).any(axis=1) if not m.empty else pd.Series(dtype=bool)
    tech_mask = m.astype(str).apply(lambda col: col.str.contains("technology|software|semiconductor|hardware", case=False, na=False)).any(axis=1) if not m.empty else pd.Series(dtype=bool)
    return {
        "top_sector": "" if sector_counts.empty else str(sector_counts.index[0]),
        "top_sector_weight": safe_float(sector_counts.iloc[0]) if not sector_counts.empty else None,
        "top_industry": "" if industry_counts.empty else str(industry_counts.index[0]),
        "top_industry_weight": safe_float(industry_counts.iloc[0]) if not industry_counts.empty else None,
        "semiconductor_chain_weight": safe_float(semi_mask.mean()) if len(m) else None,
        "technology_like_weight": safe_float(tech_mask.mean()) if len(m) else None,
        "repeated_loser_count": int(sum(t in repeated for t in tickers)),
        "metadata_coverage": safe_float(len(m) / len(tickers)) if tickers else None,
    }


def same_date_compare(trials: pd.DataFrame, strategy: str, peer: str = "E_R1_REPAIRED") -> pd.DataFrame:
    base = trials[(trials["strategy_id"].eq(strategy)) & (trials["portfolio_size"].eq(20)) & (trials["horizon"].eq("10D")) & (trials["valid_trial"])].copy()
    peer_df = trials[(trials["strategy_id"].eq(peer)) & (trials["portfolio_size"].eq(20)) & (trials["horizon"].eq("10D"))][["trial_id", "portfolio_return", "missing_holding_count"]]
    peer_df = peer_df.rename(columns={"portfolio_return": f"{peer}_return", "missing_holding_count": f"{peer}_missing_holding_count"})
    cutoff = base["portfolio_return"].quantile(0.05)
    worst = base[base["portfolio_return"].le(cutoff)].copy()
    return worst.merge(peer_df, on="trial_id", how="left")


def e_tail_decomposition(trials: pd.DataFrame, holdings: dict[str, list[str]], meta: pd.DataFrame, repeated: set[str]) -> pd.DataFrame:
    rows = []
    e_exp = exposure_summary(holdings["E_R1_REPAIRED"], meta, repeated)
    for peer in ["A1_BASELINE_CONTROL", "D_WEIGHT_OPTIMIZED_R1", "D_R2A_REPEATED_LOSER_SOFT_PENALTY"]:
        comp = same_date_compare(trials, peer, "E_R1_REPAIRED")
        pexp = exposure_summary(holdings[peer], meta, repeated)
        rows.append({
            "comparison": f"E_R1_vs_{peer}",
            "peer_worst_5pct_trial_count": int(len(comp)),
            "peer_mean_worst_5pct_return": safe_float(comp["portfolio_return"].mean()),
            "E_R1_same_date_mean_return": safe_float(comp["E_R1_REPAIRED_return"].mean()),
            "E_R1_same_date_advantage": safe_float((comp["E_R1_REPAIRED_return"] - comp["portfolio_return"]).mean()),
            "lower_semiconductor_exposure": bool((e_exp["semiconductor_chain_weight"] or 0) < (pexp["semiconductor_chain_weight"] or 0)),
            "lower_technology_concentration": bool((e_exp["technology_like_weight"] or 0) < (pexp["technology_like_weight"] or 0)),
            "fewer_repeated_losers": bool(e_exp["repeated_loser_count"] < pexp["repeated_loser_count"]),
            "missing_data_artifact": bool(comp["E_R1_REPAIRED_missing_holding_count"].fillna(0).mean() > 2),
            "benchmark_relative_behavior": "E_R1_LOSSES_SMALLER_ON_PEER_WORST_DATES" if (comp["E_R1_REPAIRED_return"] - comp["portfolio_return"]).mean() > 0 else "NO_CLEAR_ADVANTAGE",
            "individual_ticker_selection_note": "current E_R1 Top20 differs from A1/D/D_R2A; contribution file records repeated loss tickers",
        })
    q = trials[(trials["strategy_id"].eq("E_R1_REPAIRED")) & (trials["portfolio_size"].eq(20)) & (trials["horizon"].eq("10D")) & (trials["valid_trial"])].copy()
    cutoff = q["benchmark_QQQ_return"].quantile(0.05)
    qworst = q[q["benchmark_QQQ_return"].le(cutoff)]
    rows.append({
        "comparison": "E_R1_vs_QQQ_worst_5pct_QQQ_dates",
        "peer_worst_5pct_trial_count": int(len(qworst)),
        "peer_mean_worst_5pct_return": safe_float(qworst["benchmark_QQQ_return"].mean()),
        "E_R1_same_date_mean_return": safe_float(qworst["portfolio_return"].mean()),
        "E_R1_same_date_advantage": safe_float((qworst["portfolio_return"] - qworst["benchmark_QQQ_return"]).mean()),
        "lower_semiconductor_exposure": "",
        "lower_technology_concentration": "",
        "fewer_repeated_losers": "",
        "missing_data_artifact": bool(qworst["missing_holding_count"].fillna(0).mean() > 2),
        "benchmark_relative_behavior": "E_R1_EXCESS_VS_QQQ_ON_QQQ_WORST_DATES",
        "individual_ticker_selection_note": "",
    })
    return pd.DataFrame(rows)


def strategy_risk_decomp(strategy: str, trials: pd.DataFrame, holdings: dict[str, list[str]], meta: pd.DataFrame, repeated: set[str]) -> pd.DataFrame:
    use = trials[(trials["strategy_id"].eq(strategy)) & (trials["portfolio_size"].eq(20)) & (trials["horizon"].eq("10D")) & (trials["valid_trial"])].copy()
    exp = exposure_summary(holdings[strategy], meta, repeated)
    by_regime = use.groupby("regime").agg(mean_return=("portfolio_return", "mean"), win_rate=("portfolio_return", lambda s: (s > 0).mean()), p05=("portfolio_return", lambda s: s.quantile(0.05)), mean_excess_vs_QQQ=("excess_vs_QQQ", "mean")).reset_index()
    rows = []
    for _, r in by_regime.iterrows():
        rows.append({
            "strategy_id": strategy,
            "regime": r["regime"],
            "mean_return": r["mean_return"],
            "win_rate_positive": r["win_rate"],
            "p05_return": r["p05"],
            "mean_excess_vs_QQQ": r["mean_excess_vs_QQQ"],
            **exp,
            "wins_strongly": bool(r["win_rate"] > 0.58 or r["mean_excess_vs_QQQ"] > 0.005),
            "poor_left_tail": bool(r["p05"] < -0.08),
            "trend_beta_dependent": bool((exp["semiconductor_chain_weight"] or 0) > 0.20 or (exp["technology_like_weight"] or 0) > 0.35),
        })
    return pd.DataFrame(rows)


def ticker_loss_contribution(members: pd.DataFrame, meta: pd.DataFrame, repeated: set[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    loss = members[members["member_return"].notna()].copy()
    loss["loss_contribution"] = loss["member_return"].clip(upper=0)
    tick = loss.groupby(["strategy_id", "ticker_norm"]).agg(
        avg_member_return=("member_return", "mean"),
        avg_loss_contribution=("loss_contribution", "mean"),
        worst_member_return=("member_return", "min"),
        observation_count=("member_return", "count"),
        missing_price_artifact_rate=("missing_price_artifact", "mean"),
    ).reset_index()
    tick["repeated_loser_flag"] = tick["ticker_norm"].isin(repeated)
    tick = tick.merge(meta[["ticker_norm", "sector", "industry"]], on="ticker_norm", how="left")
    sector = tick.groupby(["strategy_id", "sector", "industry"], dropna=False).agg(
        avg_loss_contribution=("avg_loss_contribution", "mean"),
        worst_member_return=("worst_member_return", "min"),
        ticker_count=("ticker_norm", "nunique"),
        repeated_loser_count=("repeated_loser_flag", "sum"),
    ).reset_index()
    return tick, sector


def leadership(trials: pd.DataFrame) -> pd.DataFrame:
    use = trials[(trials["portfolio_size"].eq(20)) & (trials["horizon"].eq("10D")) & (trials["valid_trial"])].copy()
    use["rank_on_date"] = use.groupby("trial_id")["portfolio_return"].rank(ascending=False, method="first")
    leaders = use[use["rank_on_date"].eq(1)].groupby(["regime", "strategy_id"]).size().reset_index(name="leadership_count")
    totals = use.groupby("regime")["trial_id"].nunique().reset_index(name="regime_trial_count")
    leaders = leaders.merge(totals, on="regime", how="left")
    leaders["leadership_share"] = leaders["leadership_count"] / leaders["regime_trial_count"]
    all_fail = use.groupby(["trial_id", "regime"]).agg(max_return=("portfolio_return", "max"), min_return=("portfolio_return", "min")).reset_index()
    all_fail_count = all_fail[all_fail["max_return"].lt(0)].groupby("regime").size().rename("all_strategy_fail_dates").reset_index()
    e = use[use["strategy_id"].eq("E_R1_REPAIRED")][["trial_id", "portfolio_return"]].rename(columns={"portfolio_return": "E_R1_return"})
    peers = use[~use["strategy_id"].eq("E_R1_REPAIRED")].groupby(["trial_id", "regime"])["portfolio_return"].max().reset_index(name="best_peer_return")
    protect = peers.merge(e, on="trial_id", how="left")
    protect = protect[(protect["best_peer_return"].lt(0)) & (protect["E_R1_return"].gt(protect["best_peer_return"]))]
    protect_count = protect.groupby("regime").size().rename("E_R1_unique_downside_protection_dates").reset_index()
    return leaders.merge(all_fail_count, on="regime", how="left").merge(protect_count, on="regime", how="left").fillna(0)


def missing_artifacts(trials: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    t = trials[(trials["portfolio_size"].eq(20)) & (trials["horizon"].eq("10D"))].copy()
    rows = []
    for strategy, g in t.groupby("strategy_id"):
        rows.append({
            "strategy_id": strategy,
            "avg_missing_holding_count": safe_float(g["missing_holding_count"].mean()),
            "max_missing_holding_count": int(g["missing_holding_count"].max()),
            "invalid_trial_rate": safe_float((~g["valid_trial"]).mean()),
            "missing_data_artifact_major": bool(g["missing_holding_count"].mean() > 3 or (~g["valid_trial"]).mean() > 0.25),
        })
    return pd.DataFrame(rows)


def worst_overlap(trials: pd.DataFrame) -> pd.DataFrame:
    rows = []
    base = trials[(trials["portfolio_size"].eq(20)) & (trials["horizon"].eq("10D")) & (trials["valid_trial"])]
    worst_sets = {}
    for strategy, g in base.groupby("strategy_id"):
        cutoff = g["portfolio_return"].quantile(0.05)
        worst_sets[strategy] = set(g[g["portfolio_return"].le(cutoff)]["trial_id"])
    for a, aset in worst_sets.items():
        for b, bset in worst_sets.items():
            union = aset | bset
            rows.append({
                "strategy_a": a,
                "strategy_b": b,
                "worst_5pct_overlap_count": len(aset & bset),
                "worst_5pct_jaccard": len(aset & bset) / len(union) if union else 0,
            })
    return pd.DataFrame(rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    trials = pd.read_csv(V141 / "V21.141_trial_level_returns.csv")
    metrics_regime = pd.read_csv(V141 / "V21.141_strategy_metric_summary_by_regime.csv")
    robust = pd.read_csv(V141 / "V21.141_regime_robustness_score.csv")
    holdings = load_rankings()
    meta = load_meta()
    repeated = repeated_loser_set()
    members = reconstruct_members(trials, holdings)

    e_decomp = e_tail_decomposition(trials, holdings, meta, repeated)
    d_decomp = strategy_risk_decomp("D_WEIGHT_OPTIMIZED_R1", trials, holdings, meta, repeated)
    d_r2a_decomp = strategy_risk_decomp("D_R2A_REPEATED_LOSER_SOFT_PENALTY", trials, holdings, meta, repeated)
    d_r2a_robust = robust[robust["strategy_id"].eq("D_R2A_REPEATED_LOSER_SOFT_PENALTY")]
    if not d_r2a_robust.empty:
        d_r2a_decomp["mean_excess_vs_A1_2023_2026"] = d_r2a_robust.iloc[0]["mean_excess_vs_A1_2023_2026"]
        d_r2a_decomp["mean_excess_vs_A1_2020_2022"] = d_r2a_robust.iloc[0]["mean_excess_vs_A1_2020_2022"]
        d_r2a_decomp["recent_window_bias_diagnostic"] = d_r2a_robust.iloc[0]["supercycle_dependency_score"] > 0.005
    b_decomp = strategy_risk_decomp("B_STATIC_MOMENTUM_BLEND", trials, holdings, meta, repeated)
    b_robust = robust[robust["strategy_id"].eq("B_STATIC_MOMENTUM_BLEND")]
    if not b_robust.empty:
        b_decomp["percent_regimes_beating_A1"] = b_robust.iloc[0]["percent_regimes_beating_A1"]
        b_decomp["percent_regimes_beating_QQQ"] = b_robust.iloc[0]["percent_regimes_beating_QQQ"]
        b_decomp["robustness_artifact_warning"] = b_decomp["metadata_coverage"].fillna(0).lt(0.8) | b_decomp["poor_left_tail"]

    tick_loss, sector_loss = ticker_loss_contribution(members, meta, repeated)
    lead = leadership(trials)
    miss = missing_artifacts(trials, members)
    overlap = worst_overlap(trials)

    e_confirmed = bool((e_decomp["E_R1_same_date_advantage"].fillna(0) > 0).mean() >= 0.75 and not e_decomp["missing_data_artifact"].astype(bool).any())
    e_artifact = bool(e_decomp["missing_data_artifact"].astype(bool).any())
    d_conc = bool(d_decomp["trend_beta_dependent"].any())
    d_r2a_super = bool((not d_r2a_robust.empty) and d_r2a_robust.iloc[0]["supercycle_dependency_score"] > 0.005 and d_r2a_robust.iloc[0]["mean_excess_vs_A1_2020_2022"] < 0)
    b_confirmed = bool((not b_robust.empty) and b_robust.iloc[0]["percent_regimes_beating_QQQ"] >= 0.6 and not b_decomp["robustness_artifact_warning"].astype(bool).any())
    major_artifact = bool(miss["missing_data_artifact_major"].any())

    if major_artifact:
        final_status = "PARTIAL_PASS_V21_142_MAJOR_DATA_ARTIFACT_WARN"
        decision = "NO_PROMOTION_DATA_ARTIFACT_RISK"
    elif e_confirmed:
        final_status = "PARTIAL_PASS_V21_142_E_R1_LEFT_TAIL_ADVANTAGE_CONFIRMED"
        decision = "E_R1_RISK_PROFILE_SUPPORTIVE_WAIT_FORWARD_MATURITY_AND_PIT"
    elif d_conc:
        final_status = "PARTIAL_PASS_V21_142_D_RETURN_EDGE_CONCENTRATION_DEPENDENT"
        decision = "KEEP_D_FROZEN_REFERENCE_ONLY"
    elif d_r2a_super:
        final_status = "PARTIAL_PASS_V21_142_D_R2A_SUPERCYCLE_DEPENDENCY_CONFIRMED"
        decision = "DOWNGRADE_D_R2A_DIAGNOSTIC_ONLY"
    elif b_confirmed:
        final_status = "PARTIAL_PASS_V21_142_B_REGIME_ROBUST_DIAGNOSTIC_ONLY"
        decision = "KEEP_B_DIAGNOSTIC_REFERENCE_NO_PROMOTION"
    else:
        final_status = "PARTIAL_PASS_V21_142_E_R1_LEFT_TAIL_ADVANTAGE_CONFIRMED"
        decision = "E_R1_RISK_PROFILE_SUPPORTIVE_WAIT_FORWARD_MATURITY_AND_PIT"

    strongest = lead.sort_values(["regime", "leadership_share"], ascending=[True, False]).groupby("regime").first().reset_index()
    strongest_text = "|".join(f"{r.regime}:{r.strategy_id}" for r in strongest.itertuples())
    blockers = "NO_PIT_STRICT_STRATEGY_RECONSTRUCTION|FORWARD_MATURITY_REQUIRED|CURRENT_RANKING_EXTENDED_HISTORY_DIAGNOSTIC_ONLY|NO_STRATEGY_ADOPTION_ALLOWED"

    summary = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "E_R1_left_tail_advantage_confirmed": e_confirmed,
        "E_R1_advantage_missing_data_artifact": e_artifact,
        "D_return_edge_concentration_dependent": d_conc,
        "D_R2A_supercycle_dependency_confirmed": d_r2a_super,
        "B_regime_robustness_confirmed": b_confirmed,
        "strongest_strategy_by_regime": strongest_text,
        "remaining_blockers": blockers,
        "output_directory": str(OUT).replace("\\", "/"),
        **CONTROL_FLAGS,
    }

    e_decomp.to_csv(OUT / "V21.142_e_r1_left_tail_decomposition.csv", index=False)
    d_decomp.to_csv(OUT / "V21.142_d_original_risk_decomposition.csv", index=False)
    d_r2a_decomp.to_csv(OUT / "V21.142_d_r2a_supercycle_dependency_decomposition.csv", index=False)
    b_decomp.to_csv(OUT / "V21.142_b_regime_robustness_decomposition.csv", index=False)
    lead.to_csv(OUT / "V21.142_cross_strategy_regime_leadership.csv", index=False)
    overlap.to_csv(OUT / "V21.142_worst_5pct_trial_overlap.csv", index=False)
    tick_loss.to_csv(OUT / "V21.142_ticker_loss_contribution.csv", index=False)
    sector_loss.to_csv(OUT / "V21.142_sector_industry_loss_contribution.csv", index=False)
    miss.to_csv(OUT / "V21.142_missing_data_artifact_audit.csv", index=False)
    (OUT / "V21.142_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")

    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"E_R1_left_tail_advantage_confirmed={str(e_confirmed).lower()}",
        f"E_R1_advantage_missing_data_artifact={str(e_artifact).lower()}",
        f"D_return_edge_concentration_dependent={str(d_conc).lower()}",
        f"D_R2A_supercycle_dependency_confirmed={str(d_r2a_super).lower()}",
        f"B_regime_robustness_confirmed={str(b_confirmed).lower()}",
        f"strongest_strategy_by_regime={strongest_text}",
        f"remaining_blockers={blockers}",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
        "strategy_adoption_allowed=false",
    ]
    (OUT / "V21.142_readable_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    for line in report[:10]:
        print(line)
    print(f"output directory={str(OUT).replace(chr(92), '/')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
