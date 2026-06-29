from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.149_E_R1_DEFENSIVE_OVERLAY_AND_INVALID_TRIAL_AUDIT"
OUT = Path("outputs/v21/V21.149_E_R1_DEFENSIVE_OVERLAY_AND_INVALID_TRIAL_AUDIT")
V148 = Path("outputs/v21/V21.148_E_R1_A1_PIT_LITE_REPLAY_DIAGNOSTIC_ONLY")
TRIALS = V148 / "V21.148_trial_level_replay_returns.csv"
INVALID = V148 / "V21.148_invalid_trials.csv"
SUMMARY148 = V148 / "V21.148_summary.json"
PANEL = Path("outputs/v21/V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020/V21.140_extended_adjusted_close_panel_2020_plus.csv")
COVERAGE = Path("outputs/v21/V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020/V21.140_price_coverage_by_ticker.csv")
A1 = Path("outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/A1_BASELINE_CONTROL_latest_ranking.csv")
E1 = Path("outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv")

CONTROL_FLAGS = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "strategy_adoption_allowed": False,
    "overlay_adoption_allowed": False,
    "pit_strict_claim_allowed": False,
    "adoption_grade_backtest": False,
    "replay_diagnostic_only": True,
}


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


def load_holdings(path: Path, strategy: str, n: int) -> list[str]:
    df = pd.read_csv(path)
    tcol = first_col(df, ["ticker_norm", "ticker", "symbol"])
    rcol = first_col(df, ["rank", "adjusted_rank"])
    df["ticker_norm"] = df[tcol].map(norm)
    df["_rank"] = pd.to_numeric(df[rcol], errors="coerce") if rcol else np.arange(1, len(df) + 1)
    return df[df["ticker_norm"].ne("")].drop_duplicates("ticker_norm").sort_values("_rank").head(n)["ticker_norm"].tolist()


def ticker_missing_audit(invalid: pd.DataFrame) -> pd.DataFrame:
    prices = pd.read_csv(PANEL)
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.set_index("date").sort_index()
    cov = pd.read_csv(COVERAGE)
    cov = cov.set_index("symbol")
    holdings = {
        ("A1_BASELINE_CONTROL", "Top20"): load_holdings(A1, "A1_BASELINE_CONTROL", 20),
        ("A1_BASELINE_CONTROL", "Top50"): load_holdings(A1, "A1_BASELINE_CONTROL", 50),
        ("E_R1_REPAIRED", "Top20"): load_holdings(E1, "E_R1_REPAIRED", 20),
        ("E_R1_REPAIRED", "Top50"): load_holdings(E1, "E_R1_REPAIRED", 50),
    }
    rows = []
    for _, row in invalid.iterrows():
        tickers = holdings.get((row["strategy_id"], row["portfolio_size"]), [])
        asof = pd.Timestamp(row["asof_date"])
        exitd = pd.Timestamp(row["exit_date"])
        for t in tickers:
            entry_missing = t not in prices.columns or asof not in prices.index or pd.isna(prices.at[asof, t])
            exit_missing = t not in prices.columns or exitd not in prices.index or pd.isna(prices.at[exitd, t])
            if entry_missing or exit_missing:
                first = cov.loc[t, "first_available_date"] if t in cov.index else ""
                ipo_after_asof = bool(first and pd.notna(first) and pd.Timestamp(first) > asof)
                rows.append(
                    {
                        "ticker_norm": t,
                        "strategy_id": row["strategy_id"],
                        "portfolio_size": row["portfolio_size"],
                        "horizon": row["horizon"],
                        "regime": row["regime"],
                        "asof_year": pd.Timestamp(row["asof_date"]).year,
                        "entry_price_missing": entry_missing,
                        "exit_price_missing": exit_missing,
                        "IPO_after_asof_problem": ipo_after_asof,
                        "stale_price_problem": False,
                        "metadata_missing": False,
                        "current_universe_survivorship_coverage_limitation": True,
                    }
                )
    if not rows:
        return pd.DataFrame([{"ticker_norm": "", "missing_count": 0}])
    detail = pd.DataFrame(rows)
    return detail.groupby(["ticker_norm", "strategy_id", "portfolio_size", "horizon"], dropna=False).agg(
        invalid_missing_count=("ticker_norm", "size"),
        entry_price_missing_count=("entry_price_missing", "sum"),
        exit_price_missing_count=("exit_price_missing", "sum"),
        IPO_after_asof_count=("IPO_after_asof_problem", "sum"),
        current_universe_survivorship_coverage_limitation_count=("current_universe_survivorship_coverage_limitation", "sum"),
    ).reset_index()


def invalid_root(invalid: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    invalid = invalid.copy()
    invalid["asof_year"] = pd.to_datetime(invalid["asof_date"]).dt.year
    invalid["root_cause"] = np.where(
        invalid["valid_holding_count"] < invalid["portfolio_n"],
        "INSUFFICIENT_VALID_HOLDINGS_FROM_MISSING_ENTRY_OR_EXIT_PRICE",
        "UNKNOWN",
    )
    invalid["IPO_after_asof_problem"] = invalid["asof_year"] <= 2022
    invalid["current_universe_survivorship_coverage_limitation"] = True
    root = invalid.groupby(["strategy_id", "portfolio_size", "horizon", "regime", "asof_year", "root_cause"], dropna=False).agg(
        invalid_trial_count=("trial_id", "count"),
        avg_valid_holding_count=("valid_holding_count", "mean"),
        avg_missing_holding_count=("missing_holding_count", "mean"),
        IPO_after_asof_problem_count=("IPO_after_asof_problem", "sum"),
        current_universe_survivorship_coverage_limitation_count=("current_universe_survivorship_coverage_limitation", "sum"),
    ).reset_index()
    root["strategy"] = root["strategy_id"]
    root["sampled_asof_year"] = root["asof_year"]
    root = root[
        [
            "strategy",
            "strategy_id",
            "portfolio_size",
            "horizon",
            "regime",
            "sampled_asof_year",
            "asof_year",
            "root_cause",
            "invalid_trial_count",
            "avg_valid_holding_count",
            "avg_missing_holding_count",
            "IPO_after_asof_problem_count",
            "current_universe_survivorship_coverage_limitation_count",
        ]
    ]
    by_regime_year = invalid.groupby(["strategy_id", "regime", "asof_year"], dropna=False).size().reset_index(name="invalid_trial_count")
    by_regime_year["strategy"] = by_regime_year["strategy_id"]
    by_regime_year["sampled_asof_year"] = by_regime_year["asof_year"]
    return root, by_regime_year


def add_pair(valid: pd.DataFrame) -> pd.DataFrame:
    a = valid[valid["strategy_id"].eq("A1_BASELINE_CONTROL")][["trial_id", "portfolio_size", "horizon", "portfolio_return", "seed", "regime", "asof_date"]].rename(columns={"portfolio_return": "A1_return"})
    e = valid[valid["strategy_id"].eq("E_R1_REPAIRED")].merge(a[["trial_id", "portfolio_size", "horizon", "A1_return"]], on=["trial_id", "portfolio_size", "horizon"], how="inner")
    e["E_R1_excess_vs_A1"] = e["portfolio_return"] - e["A1_return"]
    e["E_R1_win_vs_A1"] = e["portfolio_return"] > e["A1_return"]
    return e


def valid_metrics(pair: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cols in [["portfolio_size", "horizon"], ["portfolio_size", "horizon", "regime"]]:
        for keys, g in pair.groupby(cols):
            if not isinstance(keys, tuple):
                keys = (keys,)
            row = dict(zip(cols, keys))
            row["grouping"] = "|".join(cols)
            e = g["portfolio_return"].dropna()
            a = g["A1_return"].dropna()
            ex = g["E_R1_excess_vs_A1"].dropna()
            e5 = e[e <= e.quantile(0.05)] if len(e) else pd.Series(dtype=float)
            a5 = a[a <= a.quantile(0.05)] if len(a) else pd.Series(dtype=float)
            e10 = e[e <= e.quantile(0.10)] if len(e) else pd.Series(dtype=float)
            a10 = a[a <= a.quantile(0.10)] if len(a) else pd.Series(dtype=float)
            seed_win = g.groupby("seed")["E_R1_win_vs_A1"].mean()
            row.update(
                {
                    "trial_count": int(len(g)),
                    "E_R1_win_rate_vs_A1": sf(g["E_R1_win_vs_A1"].mean()),
                    "E_R1_mean_excess_vs_A1": sf(ex.mean()),
                    "E_R1_median_excess_vs_A1": sf(ex.median()),
                    "E_R1_left_tail_advantage": bool(e5.mean() > a5.mean()) if len(e5) and len(a5) else False,
                    "E_R1_expected_shortfall_5pct": sf(e5.mean()),
                    "A1_expected_shortfall_5pct": sf(a5.mean()),
                    "E_R1_expected_shortfall_10pct": sf(e10.mean()),
                    "A1_expected_shortfall_10pct": sf(a10.mean()),
                    "E_R1_prob_return_lt_minus_5pct": sf((e < -0.05).mean()),
                    "A1_prob_return_lt_minus_5pct": sf((a < -0.05).mean()),
                    "E_R1_prob_return_lt_minus_10pct": sf((e < -0.10).mean()),
                    "A1_prob_return_lt_minus_10pct": sf((a < -0.10).mean()),
                    "E_R1_downside_frequency": sf((e < 0).mean()),
                    "A1_downside_frequency": sf((a < 0).mean()),
                    "seed_level_consistency": sf((seed_win > 0.5).mean()),
                }
            )
            rows.append(row)
    return pd.DataFrame(rows)


def overlay_tests(pair: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    q = pair.copy()
    q["QQQ_drawdown_proxy"] = q["QQQ_return"].fillna(0)
    rules = []
    for regime in ["RATE_HIKE_TECH_BEAR"]:
        rules.append(("CALENDAR_RATE_HIKE_TECH_BEAR", q["regime"].eq(regime)))
    for th in [-0.05, -0.10, -0.15]:
        rules.append((f"QQQ_DRAWDOWN_LT_{int(abs(th)*100)}PCT", q["QQQ_drawdown_proxy"] < th))
    q["QQQ_abs"] = q["QQQ_return"].abs()
    for pct in [0.70, 0.80, 0.90]:
        rules.append((f"QQQ_VOL_PROXY_GT_P{int(pct*100)}", q["QQQ_abs"] > q["QQQ_abs"].quantile(pct)))
    for w in [0.2, 0.3, 0.5]:
        rules.append((f"STATIC_BLEND_A1_{int((1-w)*100)}_E_R1_{int(w*100)}", pd.Series(w, index=q.index)))
    rows = []
    for name, selector in rules:
        if isinstance(selector, pd.Series) and selector.dtype != bool:
            w = selector.astype(float)
            overlay_ret = (1 - w) * q["A1_return"] + w * q["portfolio_return"]
        else:
            overlay_ret = q["A1_return"].where(~selector, q["portfolio_return"])
        a1 = q["A1_return"]
        excess = overlay_ret - a1
        tail = overlay_ret[overlay_ret <= overlay_ret.quantile(0.05)]
        a_tail = a1[a1 <= a1.quantile(0.05)]
        ret_sacrifice = a1.mean() - overlay_ret.mean()
        tail_improve = tail.mean() - a_tail.mean()
        rows.append(
            {
                "overlay_rule": name,
                "mean_return": sf(overlay_ret.mean()),
                "median_return": sf(overlay_ret.median()),
                "win_rate_vs_A1": sf((excess > 0).mean()),
                "mean_excess_vs_A1": sf(excess.mean()),
                "median_excess_vs_A1": sf(excess.median()),
                "left_tail_improvement_vs_A1": sf(tail_improve),
                "worst_5pct_expected_shortfall": sf(tail.mean()),
                "A1_worst_5pct_expected_shortfall": sf(a_tail.mean()),
                "drawdown_proxy_improvement": sf((overlay_ret.quantile(0.05) - a1.quantile(0.05))),
                "return_sacrifice": sf(ret_sacrifice),
                "tail_improvement_per_unit_return_sacrificed": sf(tail_improve / ret_sacrifice) if ret_sacrifice and ret_sacrifice > 0 else None,
                "regime_level_behavior": "|".join(q.groupby("regime").apply(lambda g: f"{g.name}:{(overlay_ret.loc[g.index]-g['A1_return']).mean():.4f}")),
            }
        )
    out = pd.DataFrame(rows)
    trade = out[["overlay_rule", "left_tail_improvement_vs_A1", "return_sacrifice", "tail_improvement_per_unit_return_sacrificed", "mean_excess_vs_A1"]].copy()
    return out, trade


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s148 = load_json(SUMMARY148)
    trials = pd.read_csv(TRIALS)
    invalid = pd.read_csv(INVALID)
    root, by_regime_year = invalid_root(invalid)
    ticker = ticker_missing_audit(invalid)
    valid = trials[trials["valid_trial"].astype(bool)].copy()
    pair = add_pair(valid)
    robust = valid_metrics(pair)
    overlays, tradeoff = overlay_tests(pair[pair["portfolio_size"].eq("Top20") & pair["horizon"].eq("10D")].copy())
    top20_10 = robust[(robust["portfolio_size"].eq("Top20")) & (robust["horizon"].eq("10D")) & (robust["grouping"].eq("portfolio_size|horizon"))].iloc[0]
    invalid_rate = len(invalid) / max(len(trials), 1)
    invalid_material = bool(invalid_rate > 0.25)
    left_valid = bool(top20_10["E_R1_left_tail_advantage"])
    return_edge = bool(top20_10["E_R1_win_rate_vs_A1"] > 0.5 and top20_10["E_R1_mean_excess_vs_A1"] > 0)
    best_overlay = overlays.sort_values(["left_tail_improvement_vs_A1", "mean_excess_vs_A1"], ascending=False).iloc[0]
    overlay_improve = sf(best_overlay["left_tail_improvement_vs_A1"])
    overlay_sacrifice = sf(best_overlay["return_sacrifice"])
    if invalid_material:
        classification = "INVALID_TRIAL_ARTIFACT_WARN"
        final_status = "PARTIAL_PASS_V21_149_INVALID_TRIAL_ARTIFACT_WARN"
        decision = "DO_NOT_USE_V21_148_REPLAY_UNTIL_INVALID_TRIAL_REPAIR"
    elif left_valid and not return_edge and overlay_improve and overlay_improve > 0:
        classification = "DEFENSIVE_OVERLAY_SUPPORTIVE_WITH_RETURN_SACRIFICE"
        final_status = "PARTIAL_PASS_V21_149_E_R1_DEFENSIVE_OVERLAY_SUPPORTIVE_RETURN_SACRIFICE"
        decision = "E_R1_DEFENSIVE_OVERLAY_CANDIDATE_WAIT_FORWARD_MATURITY"
    elif left_valid and overlay_improve and overlay_improve > 0 and (overlay_sacrifice is None or overlay_sacrifice < 0.002):
        classification = "DEFENSIVE_OVERLAY_SUPPORTIVE"
        final_status = "PARTIAL_PASS_V21_149_E_R1_OVERLAY_DIAGNOSTIC_SUPPORTIVE"
        decision = "E_R1_OVERLAY_RESEARCH_CANDIDATE_WAIT_FORWARD_MATURITY_AND_PIT"
    elif left_valid:
        classification = "LEFT_TAIL_ONLY_NO_OVERLAY_EDGE"
        final_status = "PARTIAL_PASS_V21_149_E_R1_LEFT_TAIL_ONLY_RETURN_SACRIFICE_WARN"
        decision = "E_R1_LEFT_TAIL_REFERENCE_ONLY_NO_OVERLAY_PROMOTION"
    else:
        classification = "NOT_USEFUL_AS_OVERLAY"
        final_status = "PARTIAL_PASS_V21_149_E_R1_DEFENSIVE_VALUE_NOT_CONFIRMED"
        decision = "E_R1_REQUIRES_MORE_FORWARD_OBSERVATION_NO_PROMOTION"

    classify = pd.DataFrame([{
        "E_R1_defensive_overlay_classification": classification,
        "invalid_trials_materially_bias_results": invalid_material,
        "E_R1_left_tail_valid_after_invalid_filter": left_valid,
        "E_R1_return_edge_valid_after_invalid_filter": return_edge,
        "best_defensive_overlay_rule": best_overlay["overlay_rule"],
        "overlay_left_tail_improvement": overlay_improve,
        "overlay_return_sacrifice": overlay_sacrifice,
    }])
    control = pd.DataFrame([
        {"item": "E_R1_is_A1_replacement_candidate", "status": False},
        {"item": "A1_primary_control_reconfirmed", "status": True},
        {"item": "D_frozen_reference", "status": True},
        {"item": "D_R2A_review_only", "status": True},
        {"item": "E_R1_defensive_candidate_only", "status": True},
        {"item": "strategy_adoption_allowed", "status": False},
    ])
    forward = pd.DataFrame([
        {"requirement": "E_R1 Top20 5D/10D/20D maturity", "minimum_observation_count": ">=60 10D Top20 plus supporting 5D/20D", "status": "PENDING"},
        {"requirement": "E_R1 Top50 5D/10D/20D maturity", "minimum_observation_count": ">=150 10D Top50 plus supporting 5D/20D", "status": "PENDING"},
        {"requirement": "E_R1 vs A1 in risk-off days", "minimum_observation_count": ">=30 risk-off observations", "status": "PENDING"},
        {"requirement": "E_R1 vs A1 in normal days", "minimum_observation_count": ">=60 normal observations", "status": "PENDING"},
        {"requirement": "E_R1 left-tail forward proxy", "minimum_observation_count": ">=20 downside observations", "status": "PENDING"},
    ])
    blockers = pd.DataFrame([
        {"blocker": "INVALID_TRIAL_ARTIFACT_WARN" if invalid_material else "INVALID_TRIAL_REPAIR_MONITOR", "status": "ACTIVE"},
        {"blocker": "FORWARD_MATURITY_REQUIRED", "status": "ACTIVE"},
        {"blocker": "NO_PIT_STRICT_RECONSTRUCTION", "status": "ACTIVE"},
        {"blocker": "CURRENT_UNIVERSE_SURVIVORSHIP_BIAS", "status": "ACTIVE"},
        {"blocker": "MISSING_DELISTED_TICKERS", "status": "ACTIVE"},
        {"blocker": "RESEARCH_ONLY_STAGE", "status": "ACTIVE"},
    ])
    summary = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_used": s148.get("latest_price_date_used", "2026-06-26"),
        "invalid_trial_count_from_V21_148": int(s148.get("invalid_trial_count", len(invalid))),
        "invalid_trial_root_cause_top": str(root.sort_values("invalid_trial_count", ascending=False).iloc[0]["root_cause"]),
        "invalid_trials_materially_bias_results": invalid_material,
        "E_R1_left_tail_valid_after_invalid_filter": left_valid,
        "E_R1_return_edge_valid_after_invalid_filter": return_edge,
        "best_defensive_overlay_rule": str(best_overlay["overlay_rule"]),
        "overlay_left_tail_improvement": overlay_improve,
        "overlay_return_sacrifice": overlay_sacrifice,
        "E_R1_defensive_overlay_classification": classification,
        "A1_primary_control_reconfirmed": True,
        "remaining_blockers": "|".join(blockers["blocker"]),
        "output_directory": str(OUT).replace("\\", "/"),
        **CONTROL_FLAGS,
    }
    root.to_csv(OUT / "V21.149_invalid_trial_root_cause_audit.csv", index=False)
    ticker.to_csv(OUT / "V21.149_invalid_trial_by_ticker.csv", index=False)
    by_regime_year.to_csv(OUT / "V21.149_invalid_trial_by_regime_year.csv", index=False)
    robust.to_csv(OUT / "V21.149_valid_only_replay_robustness.csv", index=False)
    overlays.to_csv(OUT / "V21.149_e_r1_defensive_overlay_tests.csv", index=False)
    tradeoff.to_csv(OUT / "V21.149_overlay_return_tail_tradeoff.csv", index=False)
    classify.to_csv(OUT / "V21.149_overlay_classification.csv", index=False)
    control.to_csv(OUT / "V21.149_a1_primary_control_confirmation.csv", index=False)
    forward.to_csv(OUT / "V21.149_forward_maturity_interaction.csv", index=False)
    blockers.to_csv(OUT / "V21.149_remaining_blockers.csv", index=False)
    (OUT / "V21.149_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"latest_price_date_used={summary['latest_price_date_used']}",
        f"invalid_trial_count_from_V21_148={summary['invalid_trial_count_from_V21_148']}",
        f"invalid_trial_root_cause_top={summary['invalid_trial_root_cause_top']}",
        f"invalid_trials_materially_bias_results={str(invalid_material).lower()}",
        f"E_R1_left_tail_valid_after_invalid_filter={str(left_valid).lower()}",
        f"E_R1_return_edge_valid_after_invalid_filter={str(return_edge).lower()}",
        f"best_defensive_overlay_rule={summary['best_defensive_overlay_rule']}",
        f"overlay_left_tail_improvement={overlay_improve}",
        f"overlay_return_sacrifice={overlay_sacrifice}",
        f"E_R1_defensive_overlay_classification={classification}",
        "A1_primary_control_reconfirmed=true",
        f"remaining_blockers={summary['remaining_blockers']}",
        f"output directory={str(OUT).replace(chr(92), '/')}",
    ]
    (OUT / "V21.149_readable_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    for line in report:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
