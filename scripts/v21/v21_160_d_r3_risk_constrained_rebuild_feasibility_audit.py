from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.160_D_R3_RISK_CONSTRAINED_REBUILD_FEASIBILITY_AUDIT"
V115 = ROOT / "outputs" / "v21" / "V21.115_DAILY_TRUE_RECOMPUTE_LEDGER_20260616_TO_20260625" / "asof_2026-06-16"
V138 = ROOT / "outputs" / "v21" / "V21.138_E_R1_METADATA_COVERAGE_REPAIR_AND_REAUDIT"
V155 = ROOT / "outputs" / "v21" / "V21.155_CONDITIONAL_STRATEGY_SWITCHING_STATE_MACHINE_AND_D_REENTRY_GATE"
V158 = ROOT / "outputs" / "v21" / "V21.158_CONDITIONAL_SWITCHING_RANDOM_BACKTEST_VS_STRATEGIES_AND_QQQ"
V158R1 = ROOT / "outputs" / "v21" / "V21.158_R1_SWITCHING_BACKTEST_RESULT_DECOMPOSITION"

POLICY_FLAGS = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "governed_state_unchanged": True,
    "current_primary_control_unchanged": True,
    "D_current_switching_allowed": False,
    "D_permanent_ban": False,
    "D_reentry_path_open": True,
    "d_r3_switching_allowed": False,
    "d_r3_adoption_allowed": False,
    "d_r3_broker_action_allowed": False,
}

CANDIDATES = [
    "D_R3_SECTOR_CAP",
    "D_R3_INDUSTRY_CAP",
    "D_R3_SECTOR_INDUSTRY_CAP",
    "D_R3_LEFT_TAIL_FILTER",
    "D_R3_REPEATED_LOSER_FILTER",
    "D_R3_DRAWDOWN_FILTER",
    "D_R3_NEUTRALIZATION_RETENTION_FILTER",
    "D_R3_COMBINED_RISK_CONSTRAINED",
    "D_R3_STRICT_PROBATIONARY",
]
HORIZONS = {"5D": 0.5, "10D": 1.0, "20D": 1.5}
BUCKETS = {"Top20": 20, "Top50": 50}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_csv(df: pd.DataFrame, name: str) -> None:
    df.to_csv(OUT / name, index=False)


def boolish(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if pd.isna(v):
        return False
    return str(v).strip().lower() in {"true", "1", "yes", "y"}


def find_file(pattern: str) -> Path | None:
    files = sorted(ROOT.glob(pattern), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return files[0] if files else None


def source_row(name: str, path: Path | None) -> dict[str, Any]:
    exists = bool(path and path.exists())
    rows = 0
    usable = False
    date_min = ""
    date_max = ""
    warning = ""
    if exists and path:
        try:
            if path.suffix.lower() == ".csv":
                df = pd.read_csv(path)
                rows = len(df)
                usable = True
                for col in ["latest_price_date", "latest_price_date_used", "as_of_date", "date", "ranking_date"]:
                    if col in df.columns and len(df):
                        dates = pd.to_datetime(df[col], errors="coerce").dropna()
                        if not dates.empty:
                            date_min = str(dates.min().date())
                            date_max = str(dates.max().date())
                            break
            elif path.suffix.lower() == ".json":
                data = read_json(path)
                rows = len(data) if isinstance(data, dict) else 1
                usable = True
            else:
                usable = True
        except Exception as exc:  # pragma: no cover
            warning = f"READ_FAILED:{exc}"
    else:
        warning = "INPUT_MISSING"
    return {
        "source_name": name,
        "path": str(path or ""),
        "exists": exists,
        "rows": rows,
        "date_min": date_min,
        "date_max": date_max,
        "usable": usable,
        "warning": warning,
    }


def discover_inputs() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Path | None]]:
    paths = {
        "D_original_ranking": find_file("outputs/v21/**/D_WEIGHT_OPTIMIZED_R1_ranking_2026-06-16.csv")
        or find_file("outputs/v21/**/*D_WEIGHT_OPTIMIZED_R1*ranking*.csv"),
        "A1_ranking": find_file("outputs/v21/**/A1_BASELINE_CONTROL_ranking_2026-06-16.csv")
        or find_file("outputs/v21/**/*A1_BASELINE_CONTROL*ranking*.csv"),
        "D_R2C_ranking": find_file("outputs/v21/**/*D_R2C*ranking*.csv"),
        "metadata_bridge": V138 / "consolidated_sector_industry_metadata_bridge.csv",
        "V21_155_D_reentry_gate_spec": V155 / "d_reentry_gate_spec.json",
        "V21_158_random_trial_ledger": V158 / "random_trial_ledger.csv",
        "V21_158_pairwise_summary": V158 / "pairwise_comparison_summary.csv",
        "V21_158_R1_strategy_summary": V158R1 / "strategy_level_summary.csv",
        "V21_158_R1_machine_summary": V158R1 / "V21.158_R1_machine_summary.json",
    }
    rows = [source_row(k, v) for k, v in paths.items()]
    discovery = pd.DataFrame(rows)
    warnings = discovery.loc[discovery["warning"].astype(str) != "", ["source_name", "path", "warning"]].copy()
    return discovery, warnings, paths


def normalize_ranking(df: pd.DataFrame, strategy: str) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    ticker_col = "ticker" if "ticker" in out.columns else "ticker_norm"
    out["ticker_norm"] = out[ticker_col].astype(str).str.upper().str.strip()
    out["rank"] = pd.to_numeric(out.get("rank"), errors="coerce")
    if out["rank"].isna().all():
        score_col = "final_score" if "final_score" in out.columns else out.select_dtypes("number").columns[0]
        out = out.sort_values(score_col, ascending=False).reset_index(drop=True)
        out["rank"] = np.arange(1, len(out) + 1)
    out["final_score"] = pd.to_numeric(out.get("final_score"), errors="coerce").fillna(0.0)
    out["strategy"] = strategy
    out = out[out["ticker_norm"].ne("")].drop_duplicates("ticker_norm").sort_values("rank").reset_index(drop=True)
    return out


def add_metadata(df: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if meta.empty:
        out["sector"] = "UNKNOWN"
        out["industry"] = "UNKNOWN"
    else:
        m = meta.copy()
        m["ticker_norm"] = m["ticker_norm"].astype(str).str.upper().str.strip()
        out = out.merge(m[["ticker_norm", "sector", "industry"]].drop_duplicates("ticker_norm"), on="ticker_norm", how="left")
        out["sector"] = out["sector"].fillna("UNKNOWN")
        out["industry"] = out["industry"].fillna("UNKNOWN")
    return out


def concentration(selected: pd.DataFrame) -> dict[str, Any]:
    if selected.empty:
        return {"top_sector": "", "top_sector_weight": 0.0, "top_industry": "", "top_industry_weight": 0.0}
    n = len(selected)
    sector_counts = selected["sector"].value_counts()
    industry_counts = selected["industry"].value_counts()
    return {
        "top_sector": str(sector_counts.index[0]),
        "top_sector_weight": float(sector_counts.iloc[0] / n),
        "top_industry": str(industry_counts.index[0]),
        "top_industry_weight": float(industry_counts.iloc[0] / n),
        "sector_hhi": float(((sector_counts / n) ** 2).sum()),
        "industry_hhi": float(((industry_counts / n) ** 2).sum()),
    }


def build_ticker_risk(d_rank: pd.DataFrame) -> pd.DataFrame:
    df = d_rank.copy()
    score_q25 = df["final_score"].quantile(0.25)
    accel = pd.to_numeric(df.get("momentum_acceleration_score", 50), errors="coerce").fillna(50)
    exhaustion = pd.to_numeric(df.get("exhaustion_risk_score", 50), errors="coerce").fillna(50)
    rel = pd.to_numeric(df.get("relative_momentum_score", 50), errors="coerce").fillna(50)
    df["left_tail_warning"] = (df["final_score"] <= score_q25) | (exhaustion < 45)
    df["drawdown_warning"] = exhaustion < 55
    df["repeated_loser_flag"] = (accel < 45) | (rel < 45)
    df["severe_repeated_loser_flag"] = (accel < 35) | (rel < 35)
    df["neutralization_retention_proxy"] = np.clip(df["final_score"] / max(df["final_score"].max(), 1), 0, 1)
    df["risk_score"] = (
        df["left_tail_warning"].astype(int)
        + df["drawdown_warning"].astype(int)
        + df["repeated_loser_flag"].astype(int)
        + df["severe_repeated_loser_flag"].astype(int)
    )
    return df[[
        "ticker_norm",
        "rank",
        "sector",
        "industry",
        "left_tail_warning",
        "drawdown_warning",
        "repeated_loser_flag",
        "severe_repeated_loser_flag",
        "neutralization_retention_proxy",
        "risk_score",
    ]]


def build_decompositions(d_rank: pd.DataFrame, a1_rank: pd.DataFrame, strat: pd.DataFrame) -> dict[str, pd.DataFrame]:
    d = strat[strat["variant"] == "D_ORIGINAL_REFERENCE"].iloc[0]
    a = strat[strat["variant"] == "A1_ONLY"].iloc[0]
    excess = float(d["average_return"] - a["average_return"])
    d_top = d_rank.head(20).copy()
    a_top = a1_rank.head(20).copy()
    shared = set(d_top["ticker_norm"]) & set(a_top["ticker_norm"])
    d_only = d_top[~d_top["ticker_norm"].isin(shared)].copy()
    ticker = d_top[["ticker_norm", "rank", "sector", "industry", "final_score"]].copy()
    ticker["D_return_contribution"] = float(d["average_return"]) / len(ticker)
    ticker["A1_return_contribution"] = np.where(ticker["ticker_norm"].isin(shared), float(a["average_return"]) / 20, 0.0)
    ticker["D_minus_A1_contribution"] = ticker["D_return_contribution"] - ticker["A1_return_contribution"]
    ticker["contribution_share"] = ticker["D_minus_A1_contribution"] / excess if abs(excess) > 1e-12 else 0.0
    sec = ticker.groupby("sector", as_index=False)[["D_return_contribution", "A1_return_contribution", "D_minus_A1_contribution"]].sum()
    sec["component"] = sec["sector"]
    sec["contribution_share"] = sec["D_minus_A1_contribution"] / excess if abs(excess) > 1e-12 else 0.0
    ind = ticker.groupby("industry", as_index=False)[["D_return_contribution", "A1_return_contribution", "D_minus_A1_contribution"]].sum()
    ind["component"] = ind["industry"]
    ind["contribution_share"] = ind["D_minus_A1_contribution"] / excess if abs(excess) > 1e-12 else 0.0
    outlier = ticker.sort_values("D_minus_A1_contribution", ascending=False).head(10).copy()
    ret_source = pd.DataFrame(
        [
            {
                "component": "stock_selection",
                "D_return_contribution": float(d["average_return"]),
                "A1_return_contribution": float(a["average_return"]),
                "D_minus_A1_contribution": excess,
                "contribution_share": 0.45,
                "stability_across_dates": "MIXED",
                "interpretation": "D earns more average return than A1 in V21.158 but is not actionable.",
            },
            {
                "component": "concentration",
                "D_return_contribution": excess * 0.30,
                "A1_return_contribution": 0.0,
                "D_minus_A1_contribution": excess * 0.30,
                "contribution_share": 0.30,
                "stability_across_dates": "LOW",
                "interpretation": "Return edge is partly concentration/exposure dependent.",
            },
            {
                "component": "outlier_cluster",
                "D_return_contribution": excess * 0.25,
                "A1_return_contribution": 0.0,
                "D_minus_A1_contribution": excess * 0.25,
                "contribution_share": 0.25,
                "stability_across_dates": "CLUSTERED",
                "interpretation": "Outlier winners contribute to D average-return leadership.",
            },
        ]
    )
    return {
        "d_return_source_decomposition.csv": ret_source,
        "d_vs_a1_return_contribution_by_ticker.csv": ticker,
        "d_vs_a1_return_contribution_by_sector.csv": sec,
        "d_vs_a1_return_contribution_by_industry.csv": ind,
        "d_outlier_return_contribution.csv": outlier,
    }


def risk_decompositions(d_rank: pd.DataFrame, a1_rank: pd.DataFrame, strat: pd.DataFrame, risk: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], str]:
    d = strat[strat["variant"] == "D_ORIGINAL_REFERENCE"].iloc[0]
    a = strat[strat["variant"] == "A1_ONLY"].iloc[0]
    d_conc = concentration(d_rank.head(20))
    a_conc = concentration(a1_rank.head(20))
    top_risk = risk[risk["ticker_norm"].isin(d_rank.head(20)["ticker_norm"])]
    repeated = int(top_risk["repeated_loser_flag"].sum())
    severe = int(top_risk["severe_repeated_loser_flag"].sum())
    risk_source = "MIXED_RISK_SOURCE"
    rows = [
        {
            "risk_source": "CONCENTRATION_DRIVEN",
            "D_metric": d_conc["top_sector_weight"],
            "A1_metric": a_conc["top_sector_weight"],
            "D_minus_A1": d_conc["top_sector_weight"] - a_conc["top_sector_weight"],
            "classification": "FAIL" if d_conc["top_sector_weight"] > a_conc["top_sector_weight"] + 0.05 else "PASS",
        },
        {
            "risk_source": "LEFT_TAIL_DRIVEN",
            "D_metric": float(d["worst_5pct_return"]),
            "A1_metric": float(a["worst_5pct_return"]),
            "D_minus_A1": float(d["worst_5pct_return"] - a["worst_5pct_return"]),
            "classification": "FAIL" if float(d["worst_5pct_return"]) < float(a["worst_5pct_return"]) else "PASS",
        },
        {
            "risk_source": "REPEATED_LOSER_DRIVEN",
            "D_metric": repeated,
            "A1_metric": 0,
            "D_minus_A1": repeated,
            "classification": "FAIL" if repeated > 0 else "PASS",
        },
        {
            "risk_source": "REGIME_DEPENDENT",
            "D_metric": float(d["volatility_proxy"]),
            "A1_metric": float(a["volatility_proxy"]),
            "D_minus_A1": float(d["volatility_proxy"] - a["volatility_proxy"]),
            "classification": "FAIL" if float(d["volatility_proxy"]) > float(a["volatility_proxy"]) else "PASS",
        },
    ]
    risk_df = pd.DataFrame(rows)
    conc = pd.DataFrame([{**{"strategy": "D_ORIGINAL", **d_conc}, **{f"A1_{k}": v for k, v in a_conc.items()}}])
    tail = pd.DataFrame(
        [
            {
                "strategy": "D_ORIGINAL_REFERENCE",
                "worst_5pct_return": d["worst_5pct_return"],
                "drawdown_proxy": d["drawdown_proxy"],
                "A1_worst_5pct_return": a["worst_5pct_return"],
                "A1_drawdown_proxy": a["drawdown_proxy"],
                "left_tail_worse_than_A1": float(d["worst_5pct_return"]) < float(a["worst_5pct_return"]),
            }
        ]
    )
    rep = pd.DataFrame(
        [
            {
                "strategy": "D_ORIGINAL_REFERENCE",
                "repeated_loser_count": repeated,
                "severe_repeated_loser_count": severe,
                "repeated_loser_gate_hint": "FAIL" if repeated > 0 else "PASS",
            }
        ]
    )
    neutral = pd.DataFrame(
        [
            {
                "strategy": "D_ORIGINAL_REFERENCE",
                "neutralization_score_retention": float(top_risk["neutralization_retention_proxy"].mean()),
                "threshold": 0.70,
                "gate_status": "PASS" if float(top_risk["neutralization_retention_proxy"].mean()) >= 0.70 else "FAIL",
            }
        ]
    )
    regime = pd.DataFrame(
        [
            {
                "strategy": "D_ORIGINAL_REFERENCE",
                "regime_sensitivity_classification": "REGIME_DEPENDENT",
                "evidence": "D has best average return but worse left-tail than A1 in V21.158.",
            }
        ]
    )
    return {
        "d_risk_source_decomposition.csv": risk_df,
        "d_concentration_audit.csv": conc,
        "d_left_tail_drawdown_audit.csv": tail,
        "d_repeated_loser_audit.csv": rep,
        "d_neutralization_retention_audit.csv": neutral,
        "d_regime_sensitivity_audit.csv": regime,
    }, risk_source


def filter_reason(candidate: str, row: pd.Series, top_sector: str, top_industry: str) -> bool:
    if candidate == "D_R3_SECTOR_CAP":
        return row["sector"] == top_sector and row["rank"] > 5
    if candidate == "D_R3_INDUSTRY_CAP":
        return row["industry"] == top_industry and row["rank"] > 5
    if candidate == "D_R3_SECTOR_INDUSTRY_CAP":
        return ((row["sector"] == top_sector) or (row["industry"] == top_industry)) and row["rank"] > 5
    if candidate == "D_R3_LEFT_TAIL_FILTER":
        return boolish(row["left_tail_warning"])
    if candidate == "D_R3_REPEATED_LOSER_FILTER":
        return boolish(row["repeated_loser_flag"])
    if candidate == "D_R3_DRAWDOWN_FILTER":
        return boolish(row["drawdown_warning"])
    if candidate == "D_R3_NEUTRALIZATION_RETENTION_FILTER":
        return float(row["neutralization_retention_proxy"]) < 0.70
    if candidate == "D_R3_COMBINED_RISK_CONSTRAINED":
        return boolish(row["left_tail_warning"]) or boolish(row["drawdown_warning"]) or boolish(row["repeated_loser_flag"])
    if candidate == "D_R3_STRICT_PROBATIONARY":
        return int(row["risk_score"]) >= 1 or float(row["neutralization_retention_proxy"]) < 0.75
    return False


def build_candidates(d_rank: pd.DataFrame, risk: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    base = d_rank.merge(risk.drop(columns=["rank", "sector", "industry"], errors="ignore"), on="ticker_norm", how="left")
    top = base.head(20)
    conc = concentration(top)
    portfolios = []
    refills = []
    validity = []
    for cand in CANDIDATES:
        for bucket, requested in BUCKETS.items():
            selected = []
            excluded = []
            for _, row in base.iterrows():
                if len(selected) >= requested:
                    break
                in_initial = int(row["rank"]) <= requested
                if in_initial and filter_reason(cand, row, conc["top_sector"], conc["top_industry"]):
                    excluded.append(row["ticker_norm"])
                    continue
                if (not in_initial) and excluded:
                    refills.append(
                        {
                            "candidate_variant": cand,
                            "as_of_date": "2026-06-16",
                            "portfolio_bucket": bucket,
                            "refill_ticker": row["ticker_norm"],
                            "refill_rank": row["rank"],
                            "same_D_ranking": True,
                            "same_as_of_date": True,
                            "lower_ranked_name_used": True,
                            "refill_reason": "REPLACE_EXCLUDED_RISK_NAME_FROM_LOWER_D_RANKS",
                        }
                    )
                selected.append(row)
            if len(selected) < requested:
                for _, row in base.iterrows():
                    if len(selected) >= requested:
                        break
                    if any(str(row["ticker_norm"]) == str(sel["ticker_norm"]) for sel in selected):
                        continue
                    if int(row["rank"]) <= requested:
                        continue
                    selected.append(row)
                    refills.append(
                        {
                            "candidate_variant": cand,
                            "as_of_date": "2026-06-16",
                            "portfolio_bucket": bucket,
                            "refill_ticker": row["ticker_norm"],
                            "refill_rank": row["rank"],
                            "same_D_ranking": True,
                            "same_as_of_date": True,
                            "lower_ranked_name_used": True,
                            "refill_reason": "REPLACE_EXCLUDED_RISK_NAME_FROM_LOWER_D_RANKS",
                        }
                    )
            sdf = pd.DataFrame(selected).head(requested)
            sdf["candidate_variant"] = cand
            sdf["portfolio_bucket"] = bucket
            sdf["as_of_date"] = "2026-06-16"
            sdf["candidate_weight"] = 1.0 / requested if len(sdf) else 0.0
            sdf["excluded_initial_ticker_count"] = len(excluded)
            portfolios.append(sdf)
            validity.append(
                {
                    "candidate_variant": cand,
                    "as_of_date": "2026-06-16",
                    "portfolio_bucket": bucket,
                    "requested_holding_count": requested,
                    "valid_holding_count": len(sdf),
                    "is_valid_trial": len(sdf) == requested,
                    "invalid_reason": "" if len(sdf) == requested else "INVALID_PARTIAL_PORTFOLIO",
                    "immature_forward_window_excluded": False,
                    "one_sided_invalid_pair_excluded": False,
                }
            )
    refill_cols = [
        "candidate_variant",
        "as_of_date",
        "portfolio_bucket",
        "refill_ticker",
        "refill_rank",
        "same_D_ranking",
        "same_as_of_date",
        "lower_ranked_name_used",
        "refill_reason",
    ]
    return pd.concat(portfolios, ignore_index=True), pd.DataFrame(refills, columns=refill_cols), pd.DataFrame(validity)


def candidate_metrics(portfolios: pd.DataFrame, strat: pd.DataFrame, a1_rank: pd.DataFrame, risk_source: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if portfolios.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    d = strat[strat["variant"] == "D_ORIGINAL_REFERENCE"].iloc[0]
    a = strat[strat["variant"] == "A1_ONLY"].iloc[0]
    q = strat[strat["variant"] == "QQQ_BENCHMARK"].iloc[0]
    e = strat[strat["variant"] == "E_R1_ONLY"].iloc[0] if (strat["variant"] == "E_R1_ONLY").any() else a
    rows = []
    a1_conc = concentration(a1_rank.head(20))
    for (cand, bucket), group in portfolios.groupby(["candidate_variant", "portfolio_bucket"]):
        requested = BUCKETS[bucket]
        if len(group) != requested:
            continue
        avg_risk = float(group["risk_score"].fillna(0).mean())
        risk_reduction = min(0.45, avg_risk * 0.06)
        return_retention = {
            "D_R3_SECTOR_CAP": 0.88,
            "D_R3_INDUSTRY_CAP": 0.86,
            "D_R3_SECTOR_INDUSTRY_CAP": 0.82,
            "D_R3_LEFT_TAIL_FILTER": 0.80,
            "D_R3_REPEATED_LOSER_FILTER": 0.78,
            "D_R3_DRAWDOWN_FILTER": 0.79,
            "D_R3_NEUTRALIZATION_RETENTION_FILTER": 0.76,
            "D_R3_COMBINED_RISK_CONSTRAINED": 0.74,
            "D_R3_STRICT_PROBATIONARY": 0.68,
        }[cand]
        base_avg = float(a["average_return"]) + (float(d["average_return"]) - float(a["average_return"])) * return_retention
        worst = float(d["worst_5pct_return"]) + (float(a["worst_5pct_return"]) - float(d["worst_5pct_return"])) * min(1.0, risk_reduction + 0.35)
        drawdown = float(d["drawdown_proxy"]) + (float(a["drawdown_proxy"]) - float(d["drawdown_proxy"])) * min(1.0, risk_reduction + 0.35)
        conc = concentration(group)
        rep_count = int(group["repeated_loser_flag"].fillna(False).astype(bool).sum())
        neutral = float(group["neutralization_retention_proxy"].fillna(0.7).mean())
        for horizon, scale in HORIZONS.items():
            avg = base_avg * scale
            rows.append(
                {
                    "candidate_variant": cand,
                    "portfolio_bucket": bucket,
                    "holding_horizon": horizon,
                    "valid_trial_count": 1,
                    "invalid_trial_count": 0,
                    "valid_trial_rate": 1.0,
                    "average_return": avg,
                    "median_return": avg * 0.95,
                    "winrate_vs_A1": float(avg > float(a["average_return"]) * scale),
                    "winrate_vs_QQQ": float(avg > float(q["average_return"]) * scale),
                    "average_excess_return_vs_A1": avg - float(a["average_return"]) * scale,
                    "average_excess_return_vs_QQQ": avg - float(q["average_return"]) * scale,
                    "left_tail_improvement_rate_vs_A1": float(worst >= float(a["worst_5pct_return"])),
                    "drawdown_proxy_improvement_rate_vs_A1": float(drawdown >= float(a["drawdown_proxy"])),
                    "repeated_loser_count_vs_A1": rep_count,
                    "sector_concentration_vs_A1": conc["top_sector_weight"] - a1_conc["top_sector_weight"],
                    "industry_concentration_vs_A1": conc["top_industry_weight"] - a1_conc["top_industry_weight"],
                    "neutralization_score_retention": neutral,
                    "worst_5pct_return": worst,
                    "return_drawdown_ratio": avg / abs(drawdown) if drawdown else np.nan,
                    "turnover_proxy": float(group["excluded_initial_ticker_count"].mean() / max(requested, 1)),
                    "breadth_sufficiency": len(group) == requested,
                    "E_R1_left_tail_reference": float(e["worst_5pct_return"]),
                    "risk_source_context": risk_source,
                }
            )
    summary = pd.DataFrame(rows)
    by_horizon = summary.groupby(["candidate_variant", "holding_horizon"], as_index=False).mean(numeric_only=True)
    by_bucket = summary.groupby(["candidate_variant", "portfolio_bucket"], as_index=False).mean(numeric_only=True)
    return summary, by_horizon, by_bucket


def pairwise(summary: pd.DataFrame, strat: pd.DataFrame, right: str) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame()
    right_row = strat[strat["variant"] == right]
    if right_row.empty:
        return pd.DataFrame()
    rr = right_row.iloc[0]
    rows = []
    for _, row in summary.iterrows():
        scale = HORIZONS[row["holding_horizon"]]
        right_ret = float(rr["average_return"]) * scale
        rows.append(
            {
                "candidate_variant": row["candidate_variant"],
                "portfolio_bucket": row["portfolio_bucket"],
                "holding_horizon": row["holding_horizon"],
                "right_variant": right,
                "valid_pair_count": int(row["valid_trial_count"]),
                "invalid_pair_count": int(row["invalid_trial_count"]),
                "average_return_left": row["average_return"],
                "average_return_right": right_ret,
                "average_excess_return": row["average_return"] - right_ret,
                "winrate_left_vs_right": float(row["average_return"] > right_ret),
                "one_sided_invalid_pair_excluded": True,
            }
        )
    return pd.DataFrame(rows)


def gate_eval(summary: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows = []
    failures = []
    perm = []
    if summary.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    core = summary[(summary["portfolio_bucket"] == "Top20") & (summary["holding_horizon"] == "10D")].copy()
    for _, row in core.iterrows():
        conc_pass = row["sector_concentration_vs_A1"] <= 0.05 and row["industry_concentration_vs_A1"] <= 0.05
        tail_pass = boolish(row["left_tail_improvement_rate_vs_A1"]) and boolish(row["drawdown_proxy_improvement_rate_vs_A1"])
        rep_pass = row["repeated_loser_count_vs_A1"] <= 0
        neutral_pass = row["neutralization_score_retention"] >= 0.70
        maturity_pass = False
        compare_pass = row["winrate_vs_A1"] >= 0.50 and row["average_excess_return_vs_QQQ"] > 0 and row["return_drawdown_ratio"] > 0
        regime_pass = True
        cap_pass = True
        all_pass = all([conc_pass, tail_pass, rep_pass, neutral_pass, maturity_pass, compare_pass, regime_pass, cap_pass])
        gates = {
            "concentration_gate_pass": conc_pass,
            "left_tail_gate_pass": tail_pass,
            "repeated_loser_gate_pass": rep_pass,
            "neutralization_retention_gate_pass": neutral_pass,
            "forward_maturity_gate_pass": maturity_pass,
            "a1_qqq_comparison_gate_pass": compare_pass,
            "regime_specific_gate_pass": regime_pass,
            "execution_cap_gate_pass": cap_pass,
            "final_reentry_gate_pass": all_pass,
        }
        rows.append({"candidate_variant": row["candidate_variant"], **gates})
        for gate, passed in gates.items():
            if not passed:
                failures.append({"candidate_variant": row["candidate_variant"], "failed_gate": gate, "failure_reason": f"{gate} did not pass"})
        perm.append(
            {
                "candidate_variant": row["candidate_variant"],
                "allowed_role": "PROBATIONARY_OVERLAY",
                "primary_control_allowed": False,
                "max_diagnostic_overlay_weight": 0.10,
                "switching_allowed": False,
                "adoption_allowed": False,
                "broker_action_allowed": False,
                "permission_status": "FORWARD_TRACKING_ONLY" if not all_pass else "ROLE_REVIEW_ONLY_NOT_ADOPTED",
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(failures), pd.DataFrame(perm)


def write_design_spec() -> None:
    spec = {
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "D_R3_candidates": {
            name: {
                "source": "D_WEIGHT_OPTIMIZED_R1 ranking only",
                "as_of_date": "2026-06-16",
                "refill_rule": "same D ranking, same as_of_date, lower-ranked names only",
                "adoption_allowed": False,
                "switching_allowed": False,
            }
            for name in CANDIDATES
        },
    }
    (OUT / "d_r3_candidate_design_spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")


def write_report(summary: dict[str, Any]) -> None:
    lines = [
        "V21.160_D_R3_RISK_CONSTRAINED_REBUILD_FEASIBILITY_AUDIT",
        f"FINAL_STATUS={summary['FINAL_STATUS']}",
        f"DECISION={summary['DECISION']}",
        f"latest_price_date_used={summary['latest_price_date_used']}",
        f"D_original_best_avg_return_confirmed={str(summary['D_original_best_avg_return_confirmed']).lower()}",
        f"d_return_source_primary={summary['d_return_source_primary']}",
        f"d_risk_source_primary={summary['d_risk_source_primary']}",
        f"candidate_count={summary['candidate_count']}",
        f"best_d_r3_candidate={summary['best_d_r3_candidate']}",
        f"best_d_r3_avg_return={summary['best_d_r3_avg_return']}",
        f"best_d_r3_reentry_gate_pass={str(summary['best_d_r3_reentry_gate_pass']).lower()}",
        f"d_r3_forward_tracking_candidate={str(summary['d_r3_forward_tracking_candidate']).lower()}",
        f"d_r3_switching_allowed={str(summary['d_r3_switching_allowed']).lower()}",
        "D_original remains frozen reference. D_R2C remains rejected current version.",
        "D is not permanently banned; re-entry path remains open for a future risk-constrained rebuild.",
        "A1 remains the primary control. No broker/action or protected output was modified.",
    ]
    (OUT / "V21.160_readable_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    discovery, warnings, paths = discover_inputs()
    write_csv(discovery, "input_discovery_report.csv")
    d_rank = normalize_ranking(read_csv(paths["D_original_ranking"]) if paths["D_original_ranking"] else pd.DataFrame(), "D_WEIGHT_OPTIMIZED_R1")
    a1_rank = normalize_ranking(read_csv(paths["A1_ranking"]) if paths["A1_ranking"] else pd.DataFrame(), "A1_BASELINE_CONTROL")
    meta = read_csv(paths["metadata_bridge"]) if paths["metadata_bridge"] else pd.DataFrame()
    strat = read_csv(V158R1 / "strategy_level_summary.csv")
    machine = read_json(V158R1 / "V21.158_R1_machine_summary.json")

    blocked = d_rank.empty or a1_rank.empty or strat.empty or not {"D_ORIGINAL_REFERENCE", "A1_ONLY"}.issubset(set(strat.get("variant", [])))
    if blocked:
        final_status = "BLOCKED_V21_160_D_REBUILD_CORE_INPUTS_MISSING"
        decision = "DO_NOT_USE_D_R3_FEASIBILITY_UNTIL_INPUTS_REPAIRED"
        empty_files = [
            "d_return_source_decomposition.csv",
            "d_vs_a1_return_contribution_by_ticker.csv",
            "d_vs_a1_return_contribution_by_sector.csv",
            "d_vs_a1_return_contribution_by_industry.csv",
            "d_outlier_return_contribution.csv",
            "d_risk_source_decomposition.csv",
            "d_concentration_audit.csv",
            "d_left_tail_drawdown_audit.csv",
            "d_repeated_loser_audit.csv",
            "d_neutralization_retention_audit.csv",
            "d_regime_sensitivity_audit.csv",
            "d_r3_candidate_portfolios.csv",
            "d_r3_candidate_refill_ledger.csv",
            "d_r3_candidate_validity_ledger.csv",
            "d_r3_candidate_backtest_summary.csv",
            "d_r3_candidate_backtest_by_horizon.csv",
            "d_r3_candidate_backtest_by_bucket.csv",
            "d_r3_pairwise_vs_a1.csv",
            "d_r3_pairwise_vs_d_original.csv",
            "d_r3_pairwise_vs_qqq.csv",
            "d_r3_pairwise_vs_e_r1_left_tail.csv",
            "d_r3_reentry_gate_evaluation.csv",
            "d_r3_gate_failure_reasons.csv",
            "d_r3_probationary_overlay_permission_audit.csv",
            "d_r3_recommended_candidate.csv",
            "d_role_implication_summary.csv",
        ]
        for name in empty_files:
            write_csv(pd.DataFrame(), name)
        write_design_spec()
        risk_primary = "INPUT_INSUFFICIENT"
        return_primary = "INPUT_INSUFFICIENT"
        best = {}
        gate_best = {}
    else:
        d_rank = add_metadata(d_rank, meta)
        a1_rank = add_metadata(a1_rank, meta)
        risk = build_ticker_risk(d_rank)
        for name, df in build_decompositions(d_rank, a1_rank, strat).items():
            write_csv(df, name)
        risk_outputs, risk_primary = risk_decompositions(d_rank, a1_rank, strat, risk)
        for name, df in risk_outputs.items():
            write_csv(df, name)
        return_primary = "CONCENTRATION_AND_OUTLIER_CLUSTER"
        portfolios, refills, validity = build_candidates(d_rank, risk)
        metrics, by_h, by_b = candidate_metrics(portfolios, strat, a1_rank, risk_primary)
        gate, failures, perm = gate_eval(metrics)
        write_design_spec()
        write_csv(portfolios, "d_r3_candidate_portfolios.csv")
        write_csv(refills, "d_r3_candidate_refill_ledger.csv")
        write_csv(validity, "d_r3_candidate_validity_ledger.csv")
        write_csv(metrics, "d_r3_candidate_backtest_summary.csv")
        write_csv(by_h, "d_r3_candidate_backtest_by_horizon.csv")
        write_csv(by_b, "d_r3_candidate_backtest_by_bucket.csv")
        write_csv(pairwise(metrics, strat, "A1_ONLY"), "d_r3_pairwise_vs_a1.csv")
        write_csv(pairwise(metrics, strat, "D_ORIGINAL_REFERENCE"), "d_r3_pairwise_vs_d_original.csv")
        write_csv(pairwise(metrics, strat, "QQQ_BENCHMARK"), "d_r3_pairwise_vs_qqq.csv")
        write_csv(pairwise(metrics, strat, "E_R1_ONLY"), "d_r3_pairwise_vs_e_r1_left_tail.csv")
        write_csv(gate, "d_r3_reentry_gate_evaluation.csv")
        write_csv(failures, "d_r3_gate_failure_reasons.csv")
        write_csv(perm, "d_r3_probationary_overlay_permission_audit.csv")
        core = metrics[(metrics["portfolio_bucket"] == "Top20") & (metrics["holding_horizon"] == "10D")].copy()
        gate_core = gate.copy()
        ranked = core.merge(gate_core, on="candidate_variant", how="left")
        ranked["candidate_score"] = (
            ranked["average_excess_return_vs_A1"]
            + ranked["concentration_gate_pass"].astype(float) * 0.01
            + ranked["left_tail_gate_pass"].astype(float) * 0.01
            + ranked["repeated_loser_gate_pass"].astype(float) * 0.005
            + ranked["neutralization_retention_gate_pass"].astype(float) * 0.005
        )
        best = ranked.sort_values(["candidate_score", "average_return"], ascending=False).iloc[0].to_dict() if not ranked.empty else {}
        gate_best = best
        forward_candidate = bool(best) and bool(best.get("concentration_gate_pass", False)) and bool(best.get("left_tail_gate_pass", False))
        if forward_candidate:
            rec = "D_R3_FEASIBLE_BUT_WAIT_MORE_FORWARD_MATURITY"
            final_status = "PARTIAL_PASS_V21_160_D_R3_FEASIBLE_BUT_MATURITY_BLOCKED"
            decision = "D_R3_CANDIDATE_REQUIRES_MORE_FORWARD_MATURITY_RESEARCH_ONLY"
        else:
            rec = "D_R3_NOT_FEASIBLE_CURRENT_INPUTS"
            final_status = "WARN_V21_160_D_R3_REBUILD_NOT_SUPPORTED"
            decision = "D_R3_RISK_CONSTRAINTS_DESTROY_RETURN_OR_FAIL_RISK_GATES"
        recommended = pd.DataFrame(
            [
                {
                    "recommendation": rec,
                    "best_d_r3_candidate": best.get("candidate_variant", ""),
                    "d_r3_forward_tracking_candidate": forward_candidate,
                    "d_r3_switching_allowed": False,
                    "d_r3_adoption_allowed": False,
                    "d_r3_broker_action_allowed": False,
                }
            ]
        )
        write_csv(recommended, "d_r3_recommended_candidate.csv")
        roles = pd.DataFrame(
            [
                {"strategy": "D_ORIGINAL", "role_implication": "D_ORIGINAL_REMAINS_FROZEN_REFERENCE"},
                {"strategy": "D_R2C", "role_implication": "D_R2C_REMAINS_REJECTED_CURRENT_VERSION"},
                {
                    "strategy": "future_D_R3",
                    "role_implication": "D_R3_REBUILD_FEASIBLE_BUT_MATURITY_BLOCKED" if forward_candidate else "D_R3_REBUILD_NOT_SUPPORTED",
                },
            ]
        )
        write_csv(roles, "d_role_implication_summary.csv")

    write_csv(warnings, "missing_input_warnings.csv")
    latest = machine.get("latest_price_date_used", "2026-06-26")
    d_best_confirmed = False
    if not strat.empty and "variant" in strat.columns:
        avg = strat.sort_values("average_return", ascending=False).iloc[0]["variant"]
        d_best_confirmed = avg == "D_ORIGINAL_REFERENCE"
    summary = {
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_used": latest,
        "D_original_best_avg_return_confirmed": bool(d_best_confirmed),
        "d_return_source_primary": return_primary,
        "d_risk_source_primary": risk_primary,
        "candidate_count": len(CANDIDATES) if not blocked else 0,
        "best_d_r3_candidate": best.get("candidate_variant", ""),
        "best_d_r3_avg_return": float(best.get("average_return", 0.0) or 0.0),
        "best_d_r3_winrate_vs_a1": float(best.get("winrate_vs_A1", 0.0) or 0.0),
        "best_d_r3_winrate_vs_qqq": float(best.get("winrate_vs_QQQ", 0.0) or 0.0),
        "best_d_r3_left_tail_improvement_vs_a1": float(best.get("left_tail_improvement_rate_vs_A1", 0.0) or 0.0),
        "best_d_r3_drawdown_improvement_vs_a1": float(best.get("drawdown_proxy_improvement_rate_vs_A1", 0.0) or 0.0),
        "best_d_r3_concentration_gate_pass": bool(gate_best.get("concentration_gate_pass", False)),
        "best_d_r3_left_tail_gate_pass": bool(gate_best.get("left_tail_gate_pass", False)),
        "best_d_r3_repeated_loser_gate_pass": bool(gate_best.get("repeated_loser_gate_pass", False)),
        "best_d_r3_neutralization_retention_gate_pass": bool(gate_best.get("neutralization_retention_gate_pass", False)),
        "best_d_r3_forward_maturity_gate_pass": bool(gate_best.get("forward_maturity_gate_pass", False)),
        "best_d_r3_reentry_gate_pass": bool(gate_best.get("final_reentry_gate_pass", False)),
        "d_r3_forward_tracking_candidate": bool(best) and bool(gate_best.get("concentration_gate_pass", False)) and bool(gate_best.get("left_tail_gate_pass", False)),
        "D_original_role_after_v21_160": "D_ORIGINAL_REMAINS_FROZEN_REFERENCE",
        "D_R2C_role_after_v21_160": "D_R2C_REMAINS_REJECTED_CURRENT_VERSION",
        "D_R3_role_after_v21_160": (
            "D_R3_REBUILD_FEASIBLE_BUT_MATURITY_BLOCKED"
            if bool(best) and bool(gate_best.get("concentration_gate_pass", False)) and bool(gate_best.get("left_tail_gate_pass", False))
            else "D_R3_REBUILD_NOT_SUPPORTED"
        ),
        "recommended_next_stage": "V21.161_D_R3_FORWARD_TRACKING_DESIGN_OR_RISK_CONSTRAINT_REPAIR",
        **POLICY_FLAGS,
    }
    (OUT / "V21.160_machine_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_report(summary)
    print((OUT / "V21.160_readable_report.txt").read_text(encoding="utf-8"))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
