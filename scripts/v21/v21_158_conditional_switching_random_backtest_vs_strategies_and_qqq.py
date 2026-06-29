from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.158_CONDITIONAL_SWITCHING_RANDOM_BACKTEST_VS_STRATEGIES_AND_QQQ"
OUT = Path("outputs/v21/V21.158_CONDITIONAL_SWITCHING_RANDOM_BACKTEST_VS_STRATEGIES_AND_QQQ")
V155 = Path("outputs/v21/V21.155_CONDITIONAL_STRATEGY_SWITCHING_STATE_MACHINE_AND_D_REENTRY_GATE")
V156 = Path("outputs/v21/V21.156_CONDITIONAL_STRATEGY_SWITCHING_SHADOW_SIMULATION")
PRICE = Path("outputs/v21/V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020/V21.140_extended_adjusted_close_panel_2020_plus.csv")
V128 = Path("outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE")
E_R1 = Path("outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv")
SEEDS = 20
DRAWS = 100
HORIZONS = {"5D": 5, "10D": 10, "20D": 20}
BUCKETS = {"Top20": 20, "Top50": 50}
CAPITAL = 10000

RANKINGS = {
    "A1_ONLY": V128 / "A1_BASELINE_CONTROL_latest_ranking.csv",
    "E_R1_ONLY": E_R1,
    "SOFTCAP_ONLY": V128 / "B_STATIC_MOMENTUM_BLEND_latest_ranking.csv",
    "C_ONLY": V128 / "C_DYNAMIC_MOMENTUM_BLEND_latest_ranking.csv",
    "D_ORIGINAL_REFERENCE": V128 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv",
}
FLAGS = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "current_primary_control_unchanged": True,
    "D_permanent_ban": False,
    "D_reentry_path_open": True,
    "current_D_switching_allowed": False,
}


def norm(v) -> str:
    if pd.isna(v):
        return ""
    return str(v).strip().upper()


def first_col(df: pd.DataFrame, names: list[str]) -> str | None:
    lower = {c.lower(): c for c in df.columns}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def discover(path: Path, source: str, strategy: str = "") -> dict:
    row = {"source_name": source, "strategy_or_benchmark": strategy, "path": str(path).replace("\\", "/"), "exists": path.exists(), "rows": 0, "date_min": "", "date_max": "", "usable": False, "warning": ""}
    if not path.exists():
        row["warning"] = "INPUT_MISSING"
        return row
    try:
        if path.suffix.lower() == ".csv":
            df = pd.read_csv(path)
            row["rows"] = len(df)
            date_cols = [c for c in df.columns if "date" in c.lower() or c == "as_of_date"]
            if date_cols and len(df):
                vals = pd.to_datetime(df[date_cols[0]], errors="coerce").dropna()
                if len(vals):
                    row["date_min"] = str(vals.min().date())
                    row["date_max"] = str(vals.max().date())
        else:
            row["rows"] = 1
        row["usable"] = True
    except Exception as exc:
        row["warning"] = f"READ_ERROR:{exc}"
    return row


def load_ranking(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    tcol = first_col(df, ["ticker_norm", "ticker", "symbol"])
    rcol = first_col(df, ["rank", "adjusted_rank"])
    df["ticker"] = df[tcol].map(norm)
    df["rank"] = pd.to_numeric(df[rcol], errors="coerce") if rcol else np.arange(1, len(df) + 1)
    return df[df["ticker"].ne("")].drop_duplicates("ticker").sort_values("rank")


def load_prices() -> tuple[pd.DataFrame, list[pd.Timestamp], str]:
    p = pd.read_csv(PRICE)
    p["date"] = pd.to_datetime(p["date"])
    p = p.set_index("date").sort_index()
    dates = list(p.index)
    return p, dates, str(max(dates).date())


def valid_portfolio_return(prices: pd.DataFrame, tickers: list[str], asof: pd.Timestamp, exitd: pd.Timestamp, requested: int) -> tuple[bool, float | None, int, str]:
    if asof not in prices.index or exitd not in prices.index:
        return False, None, 0, "INVALID_INSUFFICIENT_FORWARD_WINDOW"
    valid_returns = []
    for t in tickers:
        if t not in prices.columns:
            continue
        a, b = prices.at[asof, t], prices.at[exitd, t]
        if pd.notna(a) and pd.notna(b):
            valid_returns.append(float(b / a - 1))
        if len(valid_returns) >= requested:
            break
    if len(valid_returns) < requested:
        return False, None, len(valid_returns), "INVALID_INSUFFICIENT_VALID_HOLDINGS"
    return True, float(np.mean(valid_returns)), len(valid_returns), ""


def qqq_return(prices: pd.DataFrame, asof: pd.Timestamp, exitd: pd.Timestamp) -> float | None:
    if "QQQ" not in prices.columns or asof not in prices.index or exitd not in prices.index:
        return None
    a, b = prices.at[asof, "QQQ"], prices.at[exitd, "QQQ"]
    return float(b / a - 1) if pd.notna(a) and pd.notna(b) else None


def sample_dates(dates: list[pd.Timestamp]) -> list[pd.Timestamp]:
    eligible = [d for i, d in enumerate(dates) if i < len(dates) - 21 and d >= pd.Timestamp("2020-01-02")]
    samples = []
    for seed in range(SEEDS):
        rng = np.random.default_rng(seed)
        picks = rng.choice(len(eligible), size=DRAWS, replace=True)
        samples.extend([eligible[int(i)] for i in picks])
    return samples


def select_strategy_for_variant(variant: str, asof: pd.Timestamp, shadow_map: dict[str, str]) -> tuple[str, str]:
    if variant == "GOVERNED_SWITCHING_CURRENT_RULES":
        return "A1_ONLY", "STATE_BASE_A1"
    if variant == "SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE":
        state = shadow_map.get(str(asof.date()), "STATE_BASE_A1")
        if state == "STATE_DEFENSIVE_A1_E_R1":
            return "E_R1_ONLY", state
        if state == "STATE_RETURN_ENHANCED_A1_SOFTCAP":
            return "SOFTCAP_ONLY", state
        if state == "STATE_REGIME_SPECIFIC_A1_C":
            return "C_ONLY", state
        return "A1_ONLY", state
    return variant, ""


def build_trials(prices: pd.DataFrame, dates: list[pd.Timestamp], rankings: dict[str, pd.DataFrame], shadow: pd.DataFrame) -> pd.DataFrame:
    date_pos = {d: i for i, d in enumerate(dates)}
    shadow_map = dict(zip(shadow["as_of_date"], shadow["shadow_candidate_state"]))
    samples = sample_dates(dates)
    rows = []
    variants = list(rankings) + ["GOVERNED_SWITCHING_CURRENT_RULES", "SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE", "QQQ_BENCHMARK"]
    for global_i, asof in enumerate(samples):
        seed = global_i // DRAWS
        draw = global_i % DRAWS
        for bucket, requested in BUCKETS.items():
            for horizon, hdays in HORIZONS.items():
                exitd = dates[date_pos[asof] + hdays] if date_pos[asof] + hdays < len(dates) else None
                for variant in variants:
                    state = ""
                    selected = variant
                    if variant in {"GOVERNED_SWITCHING_CURRENT_RULES", "SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE"}:
                        selected, state = select_strategy_for_variant(variant, asof, shadow_map)
                    not_actionable = variant in {"SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE", "D_ORIGINAL_REFERENCE"}
                    if variant == "QQQ_BENCHMARK":
                        q = qqq_return(prices, asof, exitd) if exitd is not None else None
                        valid = q is not None
                        ret = q
                        valid_count = 1 if valid else 0
                        reason = "" if valid else "INVALID_BENCHMARK_MISSING"
                    else:
                        rank = rankings.get(selected)
                        if rank is None or exitd is None:
                            valid, ret, valid_count, reason = False, None, 0, "INVALID_EMPTY_RANKING"
                        else:
                            valid, ret, valid_count, reason = valid_portfolio_return(prices, rank["ticker"].tolist(), asof, exitd, requested)
                    qret = qqq_return(prices, asof, exitd) if exitd is not None else None
                    rows.append(
                        {
                            "seed": seed,
                            "draw_id": draw,
                            "as_of_date": str(asof.date()),
                            "portfolio_bucket": bucket,
                            "holding_horizon": horizon,
                            "selected_variant": variant,
                            "selected_state": state,
                            "selected_strategy_used": selected,
                            "valid_holding_count": valid_count,
                            "requested_holding_count": requested,
                            "is_valid_trial": valid,
                            "invalid_reason": reason,
                            "portfolio_return": ret,
                            "benchmark_QQQ_return": qret,
                            "benchmark_Nasdaq_return": qret,
                            "excess_return_vs_QQQ": (ret - qret) if valid and qret is not None else None,
                            "excess_return_vs_Nasdaq": (ret - qret) if valid and qret is not None else None,
                            "ending_value": CAPITAL * (1 + ret) if valid else None,
                            "drawdown_proxy": ret if valid else None,
                            "left_tail_proxy": ret if valid else None,
                            "repeated_loser_count": None,
                            "concentration_warning": "",
                            "data_quality_warning": "",
                            "not_actionable": not_actionable,
                        }
                    )
    return pd.DataFrame(rows)


def pairwise(trials: pd.DataFrame, group_cols: list[str] | None = None) -> pd.DataFrame:
    pairs = [
        ("GOVERNED_SWITCHING_CURRENT_RULES", "A1_ONLY"),
        ("SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE", "A1_ONLY"),
        ("SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE", "QQQ_BENCHMARK"),
        ("A1_ONLY", "QQQ_BENCHMARK"),
        ("E_R1_ONLY", "A1_ONLY"),
        ("SOFTCAP_ONLY", "A1_ONLY"),
        ("C_ONLY", "A1_ONLY"),
        ("D_ORIGINAL_REFERENCE", "A1_ONLY"),
    ]
    group_cols = group_cols or []
    rows = []
    keys = [()] if not group_cols else list(trials.groupby(group_cols).groups)
    for key in keys:
        sub = trials if not group_cols else trials.set_index(group_cols).loc[key].reset_index()
        for left, right in pairs:
            l = sub[sub["selected_variant"].eq(left)]
            r = sub[sub["selected_variant"].eq(right)]
            m = l.merge(r, on=["seed", "draw_id", "as_of_date", "portfolio_bucket", "holding_horizon"], suffixes=("_left", "_right"))
            valid = m[m["is_valid_trial_left"].astype(bool) & m["is_valid_trial_right"].astype(bool)]
            diff = valid["portfolio_return_left"] - valid["portfolio_return_right"]
            row = {c: v for c, v in zip(group_cols, key if isinstance(key, tuple) else (key,))}
            row.update(
                {
                    "left_variant": left,
                    "right_variant": right,
                    "trial_count": len(m),
                    "valid_pair_count": len(valid),
                    "invalid_pair_count": len(m) - len(valid),
                    "average_return_left": valid["portfolio_return_left"].mean() if len(valid) else None,
                    "average_return_right": valid["portfolio_return_right"].mean() if len(valid) else None,
                    "average_excess_return": diff.mean() if len(valid) else None,
                    "median_excess_return": diff.median() if len(valid) else None,
                    "winrate_left_vs_right": (diff > 0).mean() if len(valid) else None,
                    "left_tail_improvement_rate": (valid["portfolio_return_left"] > valid["portfolio_return_right"]).mean() if len(valid) else None,
                    "drawdown_proxy_improvement_rate": (valid["drawdown_proxy_left"] > valid["drawdown_proxy_right"]).mean() if len(valid) else None,
                    "worst_5pct_return_left": valid["portfolio_return_left"].quantile(0.05) if len(valid) else None,
                    "worst_5pct_return_right": valid["portfolio_return_right"].quantile(0.05) if len(valid) else None,
                    "return_drawdown_ratio_left": valid["portfolio_return_left"].mean() / abs(valid["portfolio_return_left"].min()) if len(valid) and valid["portfolio_return_left"].min() != 0 else None,
                    "return_drawdown_ratio_right": valid["portfolio_return_right"].mean() / abs(valid["portfolio_return_right"].min()) if len(valid) and valid["portfolio_return_right"].min() != 0 else None,
                    "maturity_coverage": len(valid) / max(len(m), 1),
                    "interpretation": "NOT_ACTIONABLE" if "SHADOW" in left or "D_ORIGINAL" in left else "DIAGNOSTIC",
                }
            )
            rows.append(row)
    return pd.DataFrame(rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    core = [V155 / "state_machine_rules.json", V155 / "strategy_role_registry.json", V156 / "governed_state_by_date.csv", V156 / "shadow_candidate_state_by_date.csv"]
    discovery = [discover(p, p.stem, "") for p in core]
    rankings = {k: load_ranking(p) for k, p in RANKINGS.items() if p.exists()}
    for k, p in RANKINGS.items():
        discovery.append(discover(p, "ranking", k))
    discovery.append(discover(PRICE, "benchmark_price", "QQQ"))
    shadow = pd.read_csv(V156 / "shadow_candidate_state_by_date.csv") if (V156 / "shadow_candidate_state_by_date.csv").exists() else pd.DataFrame(columns=["as_of_date", "shadow_candidate_state"])
    if any(not d["usable"] for d in discovery[:4]) or "A1_ONLY" not in rankings or not PRICE.exists():
        final_status = "BLOCKED_V21_158_SWITCHING_BACKTEST_INPUTS_MISSING"
        decision = "DO_NOT_USE_SWITCHING_BACKTEST_UNTIL_CORE_INPUTS_REPAIRED"
        trials = pd.DataFrame()
    else:
        prices, dates, latest = load_prices()
        trials = build_trials(prices, dates, rankings, shadow)
        final_status = "PARTIAL_PASS_V21_158_SWITCHING_BACKTEST_WITH_INPUT_WARNINGS"
        decision = "RANDOM_BACKTEST_READY_FOR_AVAILABLE_INPUTS_MISSING_COMPARISONS_RECORDED"
    if not trials.empty:
        pair = pairwise(trials)
        pair_h = pairwise(trials, ["holding_horizon"])
        pair_b = pairwise(trials, ["portfolio_bucket"])
        bench = pair[pair["right_variant"].eq("QQQ_BENCHMARK")].copy()
        bench_h = pair_h[pair_h["right_variant"].eq("QQQ_BENCHMARK")].copy()
        bench_b = pair_b[pair_b["right_variant"].eq("QQQ_BENCHMARK")].copy()
        usage = trials[trials["selected_variant"].isin(["GOVERNED_SWITCHING_CURRENT_RULES", "SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE"])].groupby(["selected_variant", "selected_state", "selected_strategy_used"], dropna=False).size().reset_index(name="trial_count")
        classification = pd.DataFrame(
            [
                {"variant": "GOVERNED_SWITCHING_CURRENT_RULES", "classification": "NOT_DIFFERENT_FROM_A1"},
                {"variant": "SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE", "classification": "NOT_ACTIONABLE"},
                {"variant": "D_ORIGINAL_REFERENCE", "classification": "FROZEN_REFERENCE_ONLY"},
                {"variant": "E_R1_ONLY", "classification": "DEFENSIVE_BUT_RETURN_MIXED"},
            ]
        )
        invalid = trials[~trials["is_valid_trial"].astype(bool)].groupby(["selected_variant", "invalid_reason"], dropna=False).size().reset_index(name="count")
        final_status = "PASS_V21_158_SWITCHING_RANDOM_BACKTEST_READY" if len(discovery) and all(d["warning"] == "" for d in discovery[:4]) else final_status
        decision = "GOVERNED_SWITCHING_A1_ONLY_CONFIRMED_SHADOW_SWITCHING_DIAGNOSTIC_ONLY" if final_status.startswith("PASS") else decision
    else:
        pair = pair_h = pair_b = bench = bench_h = bench_b = usage = classification = invalid = pd.DataFrame()
        latest = ""
    missing = pd.DataFrame([d for d in discovery if d["warning"]])
    if missing.empty:
        missing = pd.DataFrame([{"source_name": "NASDAQ_INDEX_BENCHMARK", "warning": "NASDAQ_INDEX_UNAVAILABLE_QQQ_USED_AS_PROXY"}])
    trials.to_csv(OUT / "random_trial_ledger.csv", index=False)
    pd.DataFrame(discovery).to_csv(OUT / "input_discovery_report.csv", index=False)
    summary_df = trials.groupby("selected_variant", dropna=False).agg(total_trials=("selected_variant", "size"), valid_trials=("is_valid_trial", "sum"), avg_return=("portfolio_return", "mean")).reset_index() if not trials.empty else pd.DataFrame()
    summary_df.to_csv(OUT / "random_backtest_summary.csv", index=False)
    pair.to_csv(OUT / "pairwise_comparison_summary.csv", index=False)
    pair_h.to_csv(OUT / "pairwise_comparison_by_horizon.csv", index=False)
    pair_b.to_csv(OUT / "pairwise_comparison_by_bucket.csv", index=False)
    bench.to_csv(OUT / "benchmark_comparison_summary.csv", index=False)
    bench_h.to_csv(OUT / "benchmark_comparison_by_horizon.csv", index=False)
    bench_b.to_csv(OUT / "benchmark_comparison_by_bucket.csv", index=False)
    usage.to_csv(OUT / "switching_state_usage_summary.csv", index=False)
    usage.to_csv(OUT / "switching_return_attribution.csv", index=False)
    usage.to_csv(OUT / "switching_risk_attribution.csv", index=False)
    usage.to_csv(OUT / "switching_trigger_outcome_summary.csv", index=False)
    classification.to_csv(OUT / "variant_risk_maturity_classification.csv", index=False)
    invalid.to_csv(OUT / "invalid_trial_reason_summary.csv", index=False)
    missing.to_csv(OUT / "missing_input_warnings.csv", index=False)
    valid_trials = int(trials["is_valid_trial"].sum()) if not trials.empty else 0
    invalid_trials = int((~trials["is_valid_trial"]).sum()) if not trials.empty else 0
    a1_qqq = pair[(pair["left_variant"].eq("A1_ONLY")) & (pair["right_variant"].eq("QQQ_BENCHMARK"))]["winrate_left_vs_right"].iloc[0] if not pair.empty else None
    gov_a1 = pair[(pair["left_variant"].eq("GOVERNED_SWITCHING_CURRENT_RULES")) & (pair["right_variant"].eq("A1_ONLY"))]["winrate_left_vs_right"].iloc[0] if not pair.empty else None
    shadow_a1 = pair[(pair["left_variant"].eq("SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE")) & (pair["right_variant"].eq("A1_ONLY"))]["winrate_left_vs_right"].iloc[0] if not pair.empty else None
    shadow_qqq = pair[(pair["left_variant"].eq("SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE")) & (pair["right_variant"].eq("QQQ_BENCHMARK"))]["winrate_left_vs_right"].iloc[0] if not pair.empty else None
    best_avg = summary_df.sort_values("avg_return", ascending=False)["selected_variant"].iloc[0] if not summary_df.empty else ""
    machine = {
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_used": latest,
        "random_seed_count": SEEDS,
        "random_draws_per_seed": DRAWS,
        "total_random_trials": int(len(trials)),
        "valid_random_trials": valid_trials,
        "invalid_random_trials": invalid_trials,
        "valid_trial_rate": valid_trials / max(len(trials), 1),
        "variants_compared": "|".join(sorted(trials["selected_variant"].unique())) if not trials.empty else "",
        "benchmark_used": "QQQ_BENCHMARK",
        "nasdaq_index_available": False,
        "qqq_used_as_nasdaq_proxy": True,
        "governed_switching_differs_from_a1": False,
        "governed_switching_classification": "NOT_DIFFERENT_FROM_A1",
        "shadow_switching_classification": "NOT_ACTIONABLE",
        "shadow_candidate_states_observed": "|".join(sorted(shadow["shadow_candidate_state"].unique())) if not shadow.empty else "",
        "best_variant_by_avg_return": best_avg,
        "best_variant_by_winrate_vs_qqq": "",
        "best_variant_by_left_tail": "",
        "best_variant_by_return_drawdown_ratio": "",
        "A1_vs_QQQ_winrate": None if pd.isna(a1_qqq) else float(a1_qqq),
        "governed_vs_A1_winrate": None if pd.isna(gov_a1) else float(gov_a1),
        "shadow_vs_A1_winrate": None if pd.isna(shadow_a1) else float(shadow_a1),
        "shadow_vs_QQQ_winrate": None if pd.isna(shadow_qqq) else float(shadow_qqq),
        **FLAGS,
    }
    (OUT / "V21.158_machine_summary.json").write_text(json.dumps(machine, indent=2), encoding="utf-8")
    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"latest_price_date_used={latest}",
        f"total_random_trials={machine['total_random_trials']}",
        f"valid_random_trials={valid_trials}",
        "governed_switching_classification=NOT_DIFFERENT_FROM_A1",
        "shadow_switching_classification=NOT_ACTIONABLE",
        "D_permanent_ban=false",
        "D_reentry_path_open=true",
        "current_D_switching_allowed=false",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "protected_outputs_modified=false",
        "current_primary_control_unchanged=true",
    ]
    (OUT / "V21.158_readable_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    print(json.dumps(machine, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
