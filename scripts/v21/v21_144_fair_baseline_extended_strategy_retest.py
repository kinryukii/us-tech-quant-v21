from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.144_FAIR_BASELINE_EXTENDED_STRATEGY_RETEST"
OUT = Path("outputs/v21/V21.144_FAIR_BASELINE_EXTENDED_STRATEGY_RETEST")
V141 = Path("outputs/v21/V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST")
V142 = Path("outputs/v21/V21.142_EXTENDED_REGIME_FAILURE_AND_E_R1_TAIL_ADVANTAGE_DECOMPOSITION")
V143 = Path("outputs/v21/V21.143_RANDOM_UNIVERSE_AND_SURVIVORSHIP_ARTIFACT_AUDIT")

RECOMMENDED_BASELINES = [
    "RANDOM_SECTOR_AND_AGE_MATCHED_TO_STRATEGY",
    "RANDOM_2020_COVERAGE_ONLY_EQUAL_WEIGHT",
]
OPTIONAL_BASELINES = [
    "RANDOM_SECTOR_MATCHED_TO_STRATEGY",
    "RANDOM_IPO_AGE_MATCHED_TO_STRATEGY",
]
STRATEGIES = [
    "A1_BASELINE_CONTROL",
    "B_STATIC_MOMENTUM_BLEND",
    "C_DYNAMIC_MOMENTUM_BLEND",
    "D_WEIGHT_OPTIMIZED_R1",
    "D_R2A_REPEATED_LOSER_SOFT_PENALTY",
    "E_R1_REPAIRED",
]
CONTROL_FLAGS = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "strategy_adoption_allowed": False,
}


def sf(v):
    if v is None or pd.isna(v):
        return None
    return float(v)


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def metric_by_group(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if "strategy_excess_vs_baseline" not in df.columns and "mean_excess_vs_baseline" in df.columns:
        rows = []
        for keys, g in df.groupby(group_cols, dropna=False):
            if not isinstance(keys, tuple):
                keys = (keys,)
            row = dict(zip(group_cols, keys))
            w = pd.to_numeric(g["valid_trial_count"], errors="coerce").fillna(0)
            if w.sum() == 0:
                w = pd.Series(1, index=g.index)
            def wav(col: str):
                vals = pd.to_numeric(g[col], errors="coerce")
                mask = vals.notna()
                if not mask.any():
                    return None
                return float(np.average(vals[mask], weights=w[mask]))
            row.update(
                {
                    "trial_count": int(pd.to_numeric(g["trial_count"], errors="coerce").fillna(0).sum()),
                    "valid_trial_count": int(pd.to_numeric(g["valid_trial_count"], errors="coerce").fillna(0).sum()),
                    "mean_strategy_return": wav("mean_strategy_return"),
                    "median_strategy_return": None,
                    "mean_fair_baseline_return": wav("mean_baseline_return"),
                    "median_fair_baseline_return": None,
                    "mean_excess_vs_fair_baseline": wav("mean_excess_vs_baseline"),
                    "median_excess_vs_fair_baseline": wav("median_excess_vs_baseline"),
                    "win_rate_vs_fair_baseline": wav("win_rate_vs_baseline"),
                    "strategy_prob_loss_5pct": wav("strategy_prob_loss_5pct"),
                    "fair_baseline_prob_loss_5pct": wav("baseline_prob_loss_5pct"),
                    "strategy_expected_shortfall_5pct": wav("strategy_expected_shortfall_5pct"),
                    "fair_baseline_expected_shortfall_5pct": wav("baseline_expected_shortfall_5pct"),
                }
            )
            rows.append(row)
        return pd.DataFrame(rows)
    rows = []
    for keys, g in df.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = dict(zip(group_cols, keys))
        ex = g["strategy_excess_vs_baseline"].dropna()
        sret = g["strategy_return"].dropna()
        bret = g["baseline_return"].dropna()
        s_tail = sret[sret <= sret.quantile(0.05)] if len(sret) else pd.Series(dtype=float)
        b_tail = bret[bret <= bret.quantile(0.05)] if len(bret) else pd.Series(dtype=float)
        row.update(
            {
                "trial_count": int(len(g)),
                "valid_trial_count": int(ex.count()),
                "mean_strategy_return": sf(sret.mean()),
                "median_strategy_return": sf(sret.median()),
                "mean_fair_baseline_return": sf(bret.mean()),
                "median_fair_baseline_return": sf(bret.median()),
                "mean_excess_vs_fair_baseline": sf(ex.mean()),
                "median_excess_vs_fair_baseline": sf(ex.median()),
                "win_rate_vs_fair_baseline": sf((ex > 0).mean()) if len(ex) else None,
                "strategy_prob_loss_5pct": sf((sret < -0.05).mean()) if len(sret) else None,
                "fair_baseline_prob_loss_5pct": sf((bret < -0.05).mean()) if len(bret) else None,
                "strategy_expected_shortfall_5pct": sf(s_tail.mean()) if len(s_tail) else None,
                "fair_baseline_expected_shortfall_5pct": sf(b_tail.mean()) if len(b_tail) else None,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def strategy_vs_a1_matrix(trials: pd.DataFrame) -> pd.DataFrame:
    top = trials[(trials["portfolio_size"].eq(20)) & (trials["horizon"].eq("10D")) & (trials["valid_trial"])].copy()
    piv = top.pivot_table(index="trial_id", columns="strategy_id", values="portfolio_return", aggfunc="first")
    rows = []
    for strategy in [c for c in piv.columns if c != "RANDOM_UNIVERSE_EQUAL_WEIGHT"]:
        if "A1_BASELINE_CONTROL" not in piv.columns:
            continue
        if strategy == "A1_BASELINE_CONTROL":
            rows.append(
                {
                    "strategy_id": strategy,
                    "comparison": "vs_A1_BASELINE_CONTROL",
                    "paired_trial_count": int(piv["A1_BASELINE_CONTROL"].dropna().shape[0]),
                    "mean_excess_vs_A1": 0.0,
                    "median_excess_vs_A1": 0.0,
                    "win_rate_vs_A1": 0.0,
                }
            )
            continue
        paired = piv[[strategy, "A1_BASELINE_CONTROL"]].dropna()
        rows.append(
            {
                "strategy_id": strategy,
                "comparison": "vs_A1_BASELINE_CONTROL",
                "paired_trial_count": int(len(paired)),
                "mean_excess_vs_A1": sf((paired[strategy] - paired["A1_BASELINE_CONTROL"]).mean()) if len(paired) else None,
                "median_excess_vs_A1": sf((paired[strategy] - paired["A1_BASELINE_CONTROL"]).median()) if len(paired) else None,
                "win_rate_vs_A1": sf((paired[strategy] > paired["A1_BASELINE_CONTROL"]).mean()) if len(paired) else None,
            }
        )
    return pd.DataFrame(rows)


def left_tail_summary(trials: pd.DataFrame, fair: pd.DataFrame) -> pd.DataFrame:
    rows = []
    use = trials[(trials["portfolio_size"].eq(20)) & (trials["horizon"].eq("10D")) & (trials["valid_trial"])].copy()
    for strategy, g in use.groupby("strategy_id"):
        if strategy == "RANDOM_UNIVERSE_EQUAL_WEIGHT":
            continue
        rets = g["portfolio_return"].dropna()
        tail = rets[rets <= rets.quantile(0.05)] if len(rets) else pd.Series(dtype=float)
        rows.append(
            {
                "strategy_id": strategy,
                "source": "V21.141_strategy_trials",
                "expected_shortfall_5pct": sf(tail.mean()) if len(tail) else None,
                "prob_loss_5pct": sf((rets < -0.05).mean()) if len(rets) else None,
                "worst_return": sf(rets.min()) if len(rets) else None,
            }
        )
    fair10 = fair[(fair["horizon"].eq("10D")) & (fair["baseline_name"].isin(RECOMMENDED_BASELINES))].copy()
    for (strategy, baseline), g in fair10.groupby(["strategy_id", "baseline_name"]):
        rows.append(
            {
                "strategy_id": strategy,
                "source": baseline,
                "expected_shortfall_5pct": sf(g["strategy_expected_shortfall_5pct"].mean()),
                "fair_baseline_expected_shortfall_5pct": sf(g["baseline_expected_shortfall_5pct"].mean()),
                "prob_loss_5pct": sf(g["strategy_prob_loss_5pct"].mean()),
                "fair_baseline_prob_loss_5pct": sf(g["baseline_prob_loss_5pct"].mean()),
                "worst_return": None,
            }
        )
    return pd.DataFrame(rows)


def a1_control_review(regime_metrics: pd.DataFrame, left_tail: pd.DataFrame) -> pd.DataFrame:
    use = regime_metrics[(regime_metrics["strategy_id"].isin(STRATEGIES)) & (regime_metrics["horizon"].eq("10D")) & (regime_metrics["baseline_name"].isin(RECOMMENDED_BASELINES))]
    rows = []
    a1 = use[use["strategy_id"].eq("A1_BASELINE_CONTROL")]
    rows.append(
        {
            "review_item": "A1_PRIMARY_CONTROL_REVIEW",
            "A1_mean_win_rate_vs_fair_baseline": sf(a1["win_rate_vs_fair_baseline"].mean()),
            "A1_regimes_positive_excess_count": int((a1["mean_excess_vs_fair_baseline"] > 0).sum()),
            "A1_expected_shortfall_source": "V21.141_strategy_trials",
            "A1_primary_control_reconfirmed": True,
            "reason": "No strategy is PIT_STRICT; A1 remains official primary control by governance even where challengers show diagnostic edges.",
        }
    )
    return pd.DataFrame(rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    trials = pd.read_csv(V141 / "V21.141_trial_level_returns.csv")
    fair_src = pd.read_csv(V143 / "V21.143_alternative_random_baseline_metrics.csv")
    summary141 = load_json(V141 / "V21.141_summary.json")
    summary142 = load_json(V142 / "V21.142_summary.json")
    summary143 = load_json(V143 / "V21.143_summary.json")
    pit = pd.read_csv(V141 / "V21.141_pit_status_audit.csv")

    fair_baselines_used = RECOMMENDED_BASELINES + [b for b in OPTIONAL_BASELINES if b in set(fair_src["baseline_name"])]
    fair = fair_src[fair_src["baseline_name"].isin(fair_baselines_used)].copy()
    all_period = metric_by_group(fair, ["strategy_id", "baseline_name", "horizon"])
    by_regime = metric_by_group(fair, ["strategy_id", "baseline_name", "horizon", "regime"])

    fair_matrix = all_period[all_period["horizon"].eq("10D")].pivot_table(
        index="strategy_id", columns="baseline_name", values="win_rate_vs_fair_baseline", aggfunc="mean"
    ).reset_index()
    a1_matrix = strategy_vs_a1_matrix(trials)
    left_tail = left_tail_summary(trials, fair)
    e_recheck = by_regime[(by_regime["strategy_id"].eq("E_R1_REPAIRED")) & (by_regime["horizon"].eq("10D"))].copy()
    e_recheck["E_R1_left_tail_advantage_vs_fair_baseline"] = e_recheck["strategy_expected_shortfall_5pct"] > e_recheck["fair_baseline_expected_shortfall_5pct"]
    d_recheck = by_regime[(by_regime["strategy_id"].isin(["D_WEIGHT_OPTIMIZED_R1", "D_R2A_REPEATED_LOSER_SOFT_PENALTY"])) & (by_regime["horizon"].eq("10D"))].copy()
    a1_review = a1_control_review(by_regime, left_tail)

    comp = pd.DataFrame(
        [
            {
                "source_stage": "V21.141",
                "finding": "extended_history_diagnostic_only",
                "prior_value": summary141.get("FINAL_STATUS", ""),
                "v21_144_interpretation": "Fair baseline retest remains diagnostic only due to no PIT_STRICT reconstruction.",
            },
            {
                "source_stage": "V21.142",
                "finding": "E_R1_left_tail",
                "prior_value": summary142.get("E_R1_left_tail_advantage_confirmed", ""),
                "v21_144_interpretation": "Rechecked against fair random baselines.",
            },
            {
                "source_stage": "V21.143",
                "finding": "recommended_fair_baselines",
                "prior_value": summary143.get("recommended_random_baseline_for_future_tests", ""),
                "v21_144_interpretation": "|".join(fair_baselines_used),
            },
        ]
    )

    invalid = fair[fair["valid_trial_count"].fillna(0).eq(0)] if "valid_trial_count" in fair.columns else pd.DataFrame()
    if invalid.empty:
        invalid = pd.DataFrame([{"invalid_trial_count": 0, "invalid_reason": "NONE"}])

    best_a1 = a1_matrix.sort_values("win_rate_vs_A1", ascending=False, na_position="last").head(1)
    best_a1_name = "" if best_a1.empty else str(best_a1.iloc[0]["strategy_id"])
    fair10 = all_period[(all_period["horizon"].eq("10D")) & (all_period["strategy_id"].isin(STRATEGIES))]
    best_fair = fair10.sort_values("win_rate_vs_fair_baseline", ascending=False, na_position="last").head(1)
    best_fair_name = "" if best_fair.empty else str(best_fair.iloc[0]["strategy_id"])
    best_tail = left_tail[left_tail["source"].eq("V21.141_strategy_trials")].sort_values("expected_shortfall_5pct", ascending=False, na_position="last").head(1)
    best_tail_name = "" if best_tail.empty else str(best_tail.iloc[0]["strategy_id"])

    e_confirmed = bool(e_recheck["E_R1_left_tail_advantage_vs_fair_baseline"].mean() >= 0.5) if not e_recheck.empty else False
    d_row = left_tail[left_tail["strategy_id"].eq("D_WEIGHT_OPTIMIZED_R1")]
    e_row = left_tail[left_tail["strategy_id"].eq("E_R1_REPAIRED")]
    d_tail_warn = bool(
        not d_row.empty
        and not e_row.empty
        and d_row[d_row["source"].eq("V21.141_strategy_trials")]["expected_shortfall_5pct"].mean()
        < e_row[e_row["source"].eq("V21.141_strategy_trials")]["expected_shortfall_5pct"].mean()
    )
    d2 = d_recheck[d_recheck["strategy_id"].eq("D_R2A_REPEATED_LOSER_SOFT_PENALTY")]
    recent = d2[d2["regime"].isin(["AI_SEMICONDUCTOR_REACCELERATION", "LATE_SUPERCYCLE_CURRENT"])]["mean_excess_vs_fair_baseline"].mean()
    early = d2[d2["regime"].isin(["COVID_CRASH_AND_REBOUND", "LIQUIDITY_GROWTH_BULL", "RATE_HIKE_TECH_BEAR"])]["mean_excess_vs_fair_baseline"].mean()
    d_r2a_super = bool(pd.notna(recent) and pd.notna(early) and recent > early + 0.005)
    a1_reconfirmed = True

    final_status = "PARTIAL_PASS_V21_144_FAIR_BASELINE_RETEST_DIAGNOSTIC_ONLY"
    decision_parts = ["NO_ADOPTION_NO_PIT_STRICT_RECONSTRUCTION"]
    if e_confirmed:
        decision_parts.append("E_R1_RISK_PROFILE_SUPPORTIVE_WAIT_FORWARD_MATURITY_AND_PIT")
    else:
        decision_parts.append("E_R1_ADVANTAGE_REQUIRES_REVIEW")
    if d_tail_warn:
        decision_parts.append("KEEP_D_FROZEN_REFERENCE_ONLY")
    if d_r2a_super:
        decision_parts.append("D_R2A_DIAGNOSTIC_ONLY_SUPERCYCLE_WARN")
    else:
        decision_parts.append("D_R2A_REQUIRES_FORWARD_AND_PIT_REVIEW")
    if a1_reconfirmed:
        decision_parts.append("KEEP_A1_PRIMARY_CONTROL")
    decision = "|".join(decision_parts)

    diagnostic_only = "|".join(pit.loc[pit["diagnostic_only"].astype(bool), "strategy_id"].astype(str))
    summary = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_used": summary141.get("latest_price_date_used", "2026-06-26"),
        "strategies_tested": "|".join(STRATEGIES),
        "fair_baselines_used": "|".join(fair_baselines_used),
        "pit_strict_strategies": "",
        "diagnostic_only_strategies": diagnostic_only,
        "best_strategy_vs_A1_by_10D_Top20_winrate": best_a1_name,
        "best_strategy_vs_fair_random_by_10D_Top20_winrate": best_fair_name,
        "best_left_tail_strategy": best_tail_name,
        "E_R1_LEFT_TAIL_ADVANTAGE_FAIR_BASELINE_CONFIRMED": e_confirmed,
        "D_RETURN_EDGE_TAIL_RISK_WARN": d_tail_warn,
        "D_R2A_SUPERCYCLE_DEPENDENCY_CONFIRMED": d_r2a_super,
        "A1_PRIMARY_CONTROL_RECONFIRMED": a1_reconfirmed,
        "remaining_blockers": "NO_PIT_STRICT_RECONSTRUCTION|FORWARD_MATURITY_REQUIRED|CURRENT_RANKING_EXTENDED_HISTORY_DIAGNOSTIC_ONLY|RESEARCH_ONLY_STAGE",
        "output_directory": str(OUT).replace("\\", "/"),
        **CONTROL_FLAGS,
    }

    all_period.to_csv(OUT / "V21.144_fair_baseline_metric_summary_all_period.csv", index=False)
    by_regime.to_csv(OUT / "V21.144_fair_baseline_metric_summary_by_regime.csv", index=False)
    fair_matrix.to_csv(OUT / "V21.144_strategy_vs_fair_baseline_matrix.csv", index=False)
    a1_matrix.to_csv(OUT / "V21.144_strategy_vs_A1_matrix.csv", index=False)
    left_tail.to_csv(OUT / "V21.144_left_tail_summary.csv", index=False)
    e_recheck.to_csv(OUT / "V21.144_e_r1_fair_baseline_recheck.csv", index=False)
    d_recheck.to_csv(OUT / "V21.144_d_and_d_r2a_fair_baseline_recheck.csv", index=False)
    a1_review.to_csv(OUT / "V21.144_a1_control_review.csv", index=False)
    comp.to_csv(OUT / "V21.144_comparison_to_v21_141_142_143.csv", index=False)
    invalid.to_csv(OUT / "V21.144_invalid_trials.csv", index=False)
    pit.to_csv(OUT / "V21.144_pit_status_audit.csv", index=False)
    (OUT / "V21.144_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")

    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"latest_price_date_used={summary['latest_price_date_used']}",
        f"strategies_tested={summary['strategies_tested']}",
        f"fair_baselines_used={summary['fair_baselines_used']}",
        "pit_strict_strategies=",
        f"diagnostic_only_strategies={diagnostic_only}",
        f"best_strategy_vs_A1_by_10D_Top20_winrate={best_a1_name}",
        f"best_strategy_vs_fair_random_by_10D_Top20_winrate={best_fair_name}",
        f"best_left_tail_strategy={best_tail_name}",
        f"E_R1_left_tail_advantage_fair_baseline_confirmed={str(e_confirmed).lower()}",
        f"D_return_edge_tail_risk_warn={str(d_tail_warn).lower()}",
        f"D_R2A_supercycle_dependency_confirmed={str(d_r2a_super).lower()}",
        f"A1_primary_control_reconfirmed={str(a1_reconfirmed).lower()}",
        f"remaining_blockers={summary['remaining_blockers']}",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
        "strategy_adoption_allowed=false",
    ]
    (OUT / "V21.144_readable_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    for line in report[:16]:
        print(line)
    print(f"output directory={str(OUT).replace(chr(92), '/')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
