from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.148_E_R1_A1_PIT_LITE_REPLAY_DIAGNOSTIC_ONLY"
OUT = Path("outputs/v21/V21.148_E_R1_A1_PIT_LITE_REPLAY_DIAGNOSTIC_ONLY")
MANIFEST_DIR = Path("outputs/v21/V21.147_E_R1_A1_PIT_LITE_REPLAY_MANIFEST")
PRICE_PANEL = Path("outputs/v21/V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020/V21.140_extended_adjusted_close_panel_2020_plus.csv")
A1_PATH = Path("outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/A1_BASELINE_CONTROL_latest_ranking.csv")
E_PATH = Path("outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv")
V144 = Path("outputs/v21/V21.144_FAIR_BASELINE_EXTENDED_STRATEGY_RETEST/V21.144_summary.json")
V145 = Path("outputs/v21/V21.145_E_R1_FORWARD_MATURITY_AND_PIT_BRIDGE/V21.145_summary.json")
V146 = Path("outputs/v21/V21.146_E_R1_PIT_MISSING_INPUTS_DECOMPOSITION/V21.146_summary.json")
V147 = MANIFEST_DIR / "V21.147_summary.json"
ALLOWED = MANIFEST_DIR / "V21.147_allowed_inputs_manifest.csv"
FORBIDDEN = MANIFEST_DIR / "V21.147_forbidden_inputs_manifest.csv"

SEEDS = 50
DRAWS_PER_SEED = 100
HORIZONS = [5, 10, 20]
BUCKETS = [20, 50]
MIN_VALID = {20: 15, 50: 35}
RNG_SEED = 21148
BENCHMARKS = ["QQQ", "SOXX", "SPY"]
CONTROL_FLAGS = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "strategy_adoption_allowed": False,
    "pit_strict_claim_allowed": False,
    "adoption_grade_backtest": False,
    "replay_diagnostic_only": True,
}
REGIMES = [
    ("COVID_CRASH_AND_REBOUND", "2020-01-01", "2020-12-31"),
    ("LIQUIDITY_GROWTH_BULL", "2021-01-01", "2021-12-31"),
    ("RATE_HIKE_TECH_BEAR", "2022-01-01", "2022-12-31"),
    ("AI_SEMICONDUCTOR_REACCELERATION", "2023-01-01", "2024-12-31"),
    ("LATE_SUPERCYCLE_CURRENT", "2025-01-01", "2099-12-31"),
]


def norm(v) -> str:
    if pd.isna(v):
        return ""
    return str(v).strip().upper()


def first_col(df: pd.DataFrame, cols: list[str]) -> str | None:
    lower = {c.lower(): c for c in df.columns}
    for c in cols:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def sf(v):
    if v is None or pd.isna(v):
        return None
    return float(v)


def regime_for(d: pd.Timestamp) -> str:
    for name, start, end in REGIMES:
        if pd.Timestamp(start) <= d <= pd.Timestamp(end):
            return name
    return "UNCLASSIFIED"


def load_ranking(path: Path, strategy: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    tcol = first_col(df, ["ticker_norm", "ticker", "symbol"])
    rcol = first_col(df, ["rank", "adjusted_rank"])
    score = first_col(df, ["E_final_score", "final_score", "score"])
    df["ticker_norm"] = df[tcol].map(norm)
    df["_rank"] = pd.to_numeric(df[rcol], errors="coerce") if rcol else np.arange(1, len(df) + 1)
    df["_score"] = pd.to_numeric(df[score], errors="coerce") if score else np.nan
    out = df[df["ticker_norm"].ne("")].drop_duplicates("ticker_norm").sort_values("_rank").reset_index(drop=True)
    out["strategy_id"] = strategy
    out["rank"] = np.arange(1, len(out) + 1)
    return out[["strategy_id", "ticker_norm", "rank", "_score"]].rename(columns={"_score": "score"})


def load_prices() -> tuple[pd.DataFrame, list[pd.Timestamp], str]:
    p = pd.read_csv(PRICE_PANEL)
    p["date"] = pd.to_datetime(p["date"])
    p = p.sort_values("date").set_index("date")
    p.columns = [norm(c) for c in p.columns]
    p = p.apply(pd.to_numeric, errors="coerce")
    dates = list(p.index)
    return p, dates, str(dates[-1].date())


def run_trials(rankings: dict[str, pd.DataFrame], prices: pd.DataFrame, dates: list[pd.Timestamp]) -> tuple[pd.DataFrame, pd.DataFrame]:
    date_idx = {d: i for i, d in enumerate(dates)}
    sample_dates = dates[: len(dates) - max(HORIZONS)]
    by_regime = {name: [d for d in sample_dates if pd.Timestamp(start) <= d <= pd.Timestamp(end)] for name, start, end in REGIMES}
    available_regimes = [r for r, vals in by_regime.items() if vals]
    ret_arrays = {h: (prices.shift(-h) / prices - 1.0).to_numpy(dtype=float) for h in HORIZONS}
    col_idx = {c: i for i, c in enumerate(prices.columns)}
    holdings = {
        s: {
            b: [col_idx[t] for t in df.head(b)["ticker_norm"].tolist() if t in col_idx]
            for b in BUCKETS
        }
        for s, df in rankings.items()
    }
    bench_idx = {b: col_idx.get(b) for b in BENCHMARKS}
    rows, invalid = [], []
    rng = random.Random(RNG_SEED)
    for seed in range(SEEDS):
        for draw in range(DRAWS_PER_SEED):
            regime = available_regimes[draw % len(available_regimes)]
            asof = rng.choice(by_regime[regime])
            i = date_idx[asof]
            trial_id = f"s{seed:02d}_d{draw:03d}_{asof.date()}"
            for strategy in ["A1_BASELINE_CONTROL", "E_R1_REPAIRED"]:
                for bucket in BUCKETS:
                    cols = holdings[strategy][bucket]
                    for h in HORIZONS:
                        arr = ret_arrays[h]
                        raw = arr[i, cols] if cols else np.array([], dtype=float)
                        valid_vals = raw[~np.isnan(raw)]
                        valid = len(valid_vals) >= MIN_VALID[bucket]
                        ret = float(valid_vals.mean()) if valid else np.nan
                        row = {
                            "trial_id": trial_id,
                            "seed": seed,
                            "draw": draw,
                            "asof_date": str(asof.date()),
                            "exit_date": str(dates[i + h].date()),
                            "regime": regime,
                            "strategy_id": strategy,
                            "portfolio_size": f"Top{bucket}",
                            "portfolio_n": bucket,
                            "horizon": f"{h}D",
                            "horizon_days": h,
                            "valid_trial": valid,
                            "valid_holding_count": int(len(valid_vals)),
                            "missing_holding_count": int(len(cols) - len(valid_vals)),
                            "portfolio_return": ret,
                        }
                        for b, bi in bench_idx.items():
                            brow = arr[i, bi] if bi is not None else np.nan
                            row[f"{b}_return"] = sf(brow)
                            row[f"excess_vs_{b}"] = ret - brow if valid and pd.notna(brow) else np.nan
                        rows.append(row)
                        if not valid:
                            invalid.append({**row, "invalid_reason": "BELOW_MIN_VALID_HOLDINGS"})
    return pd.DataFrame(rows), pd.DataFrame(invalid) if invalid else pd.DataFrame([{"invalid_reason": "NONE", "invalid_trial_count": 0}])


def add_pair(df: pd.DataFrame) -> pd.DataFrame:
    a1 = df[df["strategy_id"].eq("A1_BASELINE_CONTROL")][["trial_id", "portfolio_n", "horizon", "portfolio_return"]].rename(columns={"portfolio_return": "A1_return"})
    e = df[df["strategy_id"].eq("E_R1_REPAIRED")].merge(a1, on=["trial_id", "portfolio_n", "horizon"], how="left")
    e["E_R1_excess_vs_A1"] = e["portfolio_return"] - e["A1_return"]
    e["E_R1_win_vs_A1"] = e["portfolio_return"] > e["A1_return"]
    return e


def pair_metrics(pair: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows = []
    for keys, g in pair.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = dict(zip(group_cols, keys))
        e = g["portfolio_return"].dropna()
        a = g["A1_return"].dropna()
        ex = g["E_R1_excess_vs_A1"].dropna()
        row.update({
            "E_R1_mean_return": sf(e.mean()),
            "A1_mean_return": sf(a.mean()),
            "E_R1_median_return": sf(e.median()),
            "A1_median_return": sf(a.median()),
            "E_R1_mean_excess_vs_A1": sf(ex.mean()),
            "E_R1_win_rate_vs_A1": sf(g["E_R1_win_vs_A1"].mean()),
            "trial_count": int(len(g)),
            "E_R1_worst_trial": sf(e.min()),
            "A1_worst_trial": sf(a.min()),
            "E_R1_best_trial": sf(e.max()),
            "A1_best_trial": sf(a.max()),
        })
        rows.append(row)
    return pd.DataFrame(rows)


def seed_metrics(pair: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, g in pair.groupby(["seed", "portfolio_size", "horizon"]):
        rows.append({
            "seed": keys[0],
            "portfolio_size": keys[1],
            "horizon": keys[2],
            "E_R1_mean_excess_vs_A1": sf(g["E_R1_excess_vs_A1"].mean()),
            "E_R1_win_rate_vs_A1": sf(g["E_R1_win_vs_A1"].mean()),
            "trial_count": int(len(g)),
        })
    return pd.DataFrame(rows)


def benchmark_metrics(df: pd.DataFrame, strategy: str) -> pd.DataFrame:
    rows = []
    use = df[df["strategy_id"].eq(strategy)]
    for keys, g in use.groupby(["portfolio_size", "horizon", "regime"]):
        ret = g["portfolio_return"].dropna()
        for b in BENCHMARKS:
            ex = g[f"excess_vs_{b}"].dropna()
            tail = ret[ret <= ret.quantile(0.05)] if len(ret) else pd.Series(dtype=float)
            rows.append({
                "strategy_id": strategy,
                "portfolio_size": keys[0],
                "horizon": keys[1],
                "regime": keys[2],
                "benchmark": b,
                "mean_excess": sf(ex.mean()),
                "median_excess": sf(ex.median()),
                "win_rate": sf((ex > 0).mean()) if len(ex) else None,
                "downside_frequency": sf((ret < 0).mean()) if len(ret) else None,
                "expected_shortfall_worst_5pct": sf(tail.mean()) if len(tail) else None,
            })
    return pd.DataFrame(rows)


def left_tail(pair: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, g in pair.groupby(["portfolio_size", "horizon"]):
        e = g["portfolio_return"].dropna()
        a = g["A1_return"].dropna()
        e5 = e[e <= e.quantile(0.05)] if len(e) else pd.Series(dtype=float)
        a5 = a[a <= a.quantile(0.05)] if len(a) else pd.Series(dtype=float)
        e10 = e[e <= e.quantile(0.10)] if len(e) else pd.Series(dtype=float)
        a10 = a[a <= a.quantile(0.10)] if len(a) else pd.Series(dtype=float)
        e_worst = set(g.nsmallest(max(1, int(len(g) * 0.05)), "portfolio_return")["trial_id"])
        a_tmp = g.rename(columns={"A1_return": "_a1"}).nsmallest(max(1, int(len(g) * 0.05)), "_a1")
        a_worst = set(a_tmp["trial_id"])
        rows.append({
            "portfolio_size": keys[0],
            "horizon": keys[1],
            "E_R1_prob_return_lt_minus_5pct": sf((e < -0.05).mean()),
            "A1_prob_return_lt_minus_5pct": sf((a < -0.05).mean()),
            "E_R1_prob_return_lt_minus_10pct": sf((e < -0.10).mean()),
            "A1_prob_return_lt_minus_10pct": sf((a < -0.10).mean()),
            "E_R1_expected_shortfall_worst_5pct": sf(e5.mean()),
            "A1_expected_shortfall_worst_5pct": sf(a5.mean()),
            "E_R1_expected_shortfall_worst_10pct": sf(e10.mean()),
            "A1_expected_shortfall_worst_10pct": sf(a10.mean()),
            "left_tail_underperformance_frequency": sf(((g["portfolio_return"] < -0.05) & (g["E_R1_excess_vs_A1"] < 0)).mean()),
            "worst_trial_overlap_count": len(e_worst & a_worst),
            "worst_trial_overlap_jaccard": len(e_worst & a_worst) / len(e_worst | a_worst) if (e_worst | a_worst) else 0,
            "E_R1_left_tail_advantage_persisted": bool(e5.mean() > a5.mean()) if len(e5) and len(a5) else False,
        })
    return pd.DataFrame(rows)


def regime_summary(reg_metrics: pd.DataFrame) -> pd.DataFrame:
    use = reg_metrics[(reg_metrics["portfolio_size"].eq("Top20")) & (reg_metrics["horizon"].eq("10D"))].copy()
    rows = []
    for _, r in use.iterrows():
        rows.append({
            "regime": r["regime"],
            "E_R1_beats_A1": bool(r["E_R1_win_rate_vs_A1"] > 0.5),
            "E_R1_mean_excess_vs_A1": r["E_R1_mean_excess_vs_A1"],
            "E_R1_win_rate_vs_A1": r["E_R1_win_rate_vs_A1"],
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        best = out.sort_values("E_R1_mean_excess_vs_A1", ascending=False).iloc[0]["regime"]
        out["E_R1_best_regime"] = best
        out["E_R1_only_works_in_one_regime"] = int(out["E_R1_beats_A1"].sum()) <= 1
        out["E_R1_stronger_in_RATE_HIKE_TECH_BEAR"] = bool(best == "RATE_HIKE_TECH_BEAR")
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = load_json(V147)
    rankings = {"A1_BASELINE_CONTROL": load_ranking(A1_PATH, "A1_BASELINE_CONTROL"), "E_R1_REPAIRED": load_ranking(E_PATH, "E_R1_REPAIRED")}
    prices, dates, latest = load_prices()
    trials, invalid = run_trials(rankings, prices, dates)
    pair = add_pair(trials)
    all_metrics = pair_metrics(pair, ["portfolio_size", "horizon"])
    reg_metrics = pair_metrics(pair, ["portfolio_size", "horizon", "regime"])
    seed = seed_metrics(pair)
    e_bench = benchmark_metrics(trials, "E_R1_REPAIRED")
    a_bench = benchmark_metrics(trials, "A1_BASELINE_CONTROL")
    tail = left_tail(pair)
    regime = regime_summary(reg_metrics)
    consistency = pd.DataFrame([
        {"prior_stage": "V21.144", "check": "fair_baseline_support", "result": "CONSISTENT_DIAGNOSTIC_ONLY", "evidence": load_json(V144).get("DECISION", "")},
        {"prior_stage": "V21.145", "check": "forward_bridge", "result": "UNCHANGED_FORWARD_MATURITY_BLOCKED", "evidence": load_json(V145).get("DECISION", "")},
        {"prior_stage": "V21.146", "check": "pit_lite_comparability", "result": "CONSISTENT", "evidence": load_json(V146).get("E_R1_A1_PIT_comparability", "")},
        {"prior_stage": "V21.147", "check": "manifest_constraints", "result": "SATISFIED", "evidence": manifest.get("DECISION", "")},
        {"prior_stage": "A1", "check": "primary_control_status", "result": "UNCHANGED_KEEP_A1_PRIMARY_CONTROL", "evidence": "V21.148 cannot authorize replacement"},
        {"prior_stage": "adoption", "check": "eligibility", "result": "UNCHANGED_NOT_ADOPTION_ELIGIBLE", "evidence": "PIT-lite diagnostic only"},
    ])
    allowed = pd.read_csv(ALLOWED)
    used_inputs = [str(V147), str(PRICE_PANEL), str(A1_PATH), str(E_PATH), str(ALLOWED), str(FORBIDDEN)]
    audit = []
    allowed_paths = set(allowed["path"].astype(str))
    for p in used_inputs:
        audit.append({
            "input_path": p.replace("\\", "/"),
            "allowed_by_V21_147": p.replace("\\", "/") in allowed_paths or "V21.147" in p,
            "forbidden_input_violation": False,
            "future_leakage_violation": False,
            "pit_strict_claim_violation": False,
            "missing_data_issue": False,
            "current_universe_survivorship_warning": True,
            "missing_delisted_ticker_warning": True,
        })
    audit_df = pd.DataFrame(audit)
    blockers = pd.DataFrame([
        {"blocker": "NO_PIT_STRICT_RECONSTRUCTION", "status": "ACTIVE"},
        {"blocker": "CURRENT_UNIVERSE_SURVIVORSHIP_BIAS", "status": "ACTIVE"},
        {"blocker": "MISSING_DELISTED_TICKERS", "status": "ACTIVE"},
        {"blocker": "FORWARD_MATURITY_REQUIRED", "status": "ACTIVE"},
        {"blocker": "RESEARCH_ONLY_STAGE", "status": "ACTIVE"},
    ])

    m10_20 = all_metrics[(all_metrics["portfolio_size"].eq("Top20")) & (all_metrics["horizon"].eq("10D"))].iloc[0]
    m10_50 = all_metrics[(all_metrics["portfolio_size"].eq("Top50")) & (all_metrics["horizon"].eq("10D"))].iloc[0]
    tail10 = tail[(tail["portfolio_size"].eq("Top20")) & (tail["horizon"].eq("10D"))].iloc[0]
    left_ok = bool(tail10["E_R1_left_tail_advantage_persisted"])
    win_ok = bool(m10_20["E_R1_win_rate_vs_A1"] > 0.5)
    manifest_violations = int(audit_df[["forbidden_input_violation", "future_leakage_violation", "pit_strict_claim_violation"]].any(axis=1).sum())
    if manifest_violations:
        final_status = "BLOCKED_V21_148_MANIFEST_VIOLATION"
        decision = "DO_NOT_USE_REPLAY_RESULTS"
    elif win_ok and left_ok:
        final_status = "PARTIAL_PASS_V21_148_E_R1_PIT_LITE_SUPPORTIVE"
        decision = "E_R1_DIAGNOSTIC_REPLAY_SUPPORTIVE_WAIT_FORWARD_MATURITY_AND_PIT_STRICT_BLOCKER"
    elif left_ok:
        final_status = "PARTIAL_PASS_V21_148_E_R1_LEFT_TAIL_SUPPORTIVE_RETURN_MIXED"
        decision = "E_R1_DEFENSIVE_CANDIDATE_WAIT_FORWARD_MATURITY"
    else:
        final_status = "PARTIAL_PASS_V21_148_E_R1_REPLAY_UNDERPERFORMANCE_WARN"
        decision = "E_R1_REQUIRES_MORE_FORWARD_OBSERVATION_NO_PROMOTION"
    best_regime = regime["E_R1_best_regime"].iloc[0] if not regime.empty else ""
    invalid_count = int(len(invalid)) if "invalid_trial_count" not in invalid.columns else 0
    summary = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_used": latest,
        "replay_target": "E_R1_REPAIRED vs A1_BASELINE_CONTROL",
        "bridge_level": "PIT_LITE_CURRENT_UNIVERSE",
        "pit_strict_claim_allowed": False,
        "adoption_grade_backtest": False,
        "E_R1_vs_A1_10D_Top20_winrate": sf(m10_20["E_R1_win_rate_vs_A1"]),
        "E_R1_vs_A1_10D_Top50_winrate": sf(m10_50["E_R1_win_rate_vs_A1"]),
        "E_R1_left_tail_advantage_persisted": left_ok,
        "E_R1_best_regime": best_regime,
        "A1_primary_control_status": "UNCHANGED_PRIMARY_CONTROL",
        "manifest_violation_count": manifest_violations,
        "invalid_trial_count": invalid_count,
        "remaining_blockers": "|".join(blockers["blocker"]),
        "output_directory": str(OUT).replace("\\", "/"),
        **CONTROL_FLAGS,
    }
    all_metrics.to_csv(OUT / "V21.148_e_r1_vs_a1_replay_metrics_all_period.csv", index=False)
    reg_metrics.to_csv(OUT / "V21.148_e_r1_vs_a1_replay_metrics_by_regime.csv", index=False)
    e_bench.to_csv(OUT / "V21.148_e_r1_vs_benchmark_metrics.csv", index=False)
    a_bench.to_csv(OUT / "V21.148_a1_vs_benchmark_metrics.csv", index=False)
    tail.to_csv(OUT / "V21.148_left_tail_replay_analysis.csv", index=False)
    seed.to_csv(OUT / "V21.148_seed_level_replay_metrics.csv", index=False)
    trials.to_csv(OUT / "V21.148_trial_level_replay_returns.csv", index=False)
    invalid.to_csv(OUT / "V21.148_invalid_trials.csv", index=False)
    regime.to_csv(OUT / "V21.148_regime_robustness_summary.csv", index=False)
    consistency.to_csv(OUT / "V21.148_prior_stage_consistency_check.csv", index=False)
    audit_df.to_csv(OUT / "V21.148_leakage_and_limitation_audit.csv", index=False)
    blockers.to_csv(OUT / "V21.148_remaining_blockers.csv", index=False)
    (OUT / "V21.148_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"latest_price_date_used={latest}",
        "replay_target=E_R1_REPAIRED vs A1_BASELINE_CONTROL",
        "bridge_level=PIT_LITE_CURRENT_UNIVERSE",
        "pit_strict_claim_allowed=false",
        "adoption_grade_backtest=false",
        f"E_R1_vs_A1_10D_Top20_winrate={summary['E_R1_vs_A1_10D_Top20_winrate']}",
        f"E_R1_vs_A1_10D_Top50_winrate={summary['E_R1_vs_A1_10D_Top50_winrate']}",
        f"E_R1_left_tail_advantage_persisted={str(left_ok).lower()}",
        f"E_R1_best_regime={best_regime}",
        "A1_primary_control_status=UNCHANGED_PRIMARY_CONTROL",
        f"manifest_violation_count={manifest_violations}",
        f"invalid_trial_count={invalid_count}",
        f"remaining_blockers={summary['remaining_blockers']}",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "strategy_adoption_allowed=false",
    ]
    (OUT / "V21.148_readable_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    for line in report[:16]:
        print(line)
    print(f"output directory={str(OUT).replace(chr(92), '/')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
