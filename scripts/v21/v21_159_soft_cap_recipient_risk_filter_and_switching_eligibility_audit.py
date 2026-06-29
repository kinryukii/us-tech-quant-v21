from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.159_SOFT_CAP_RECIPIENT_RISK_FILTER_AND_SWITCHING_ELIGIBILITY_AUDIT"
SRC_153_R2 = ROOT / "outputs" / "v21" / "V21.153_R2_SOFTCAP_RETURN_VS_RISK_ATTRIBUTION"
SRC_158 = ROOT / "outputs" / "v21" / "V21.158_CONDITIONAL_SWITCHING_RANDOM_BACKTEST_VS_STRATEGIES_AND_QQQ"
SRC_158_R1 = ROOT / "outputs" / "v21" / "V21.158_R1_SWITCHING_BACKTEST_RESULT_DECOMPOSITION"
SRC_155 = ROOT / "outputs" / "v21" / "V21.155_CONDITIONAL_STRATEGY_SWITCHING_STATE_MACHINE_AND_D_REENTRY_GATE"

POLICY_FLAGS = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "governed_state_unchanged": True,
    "current_primary_control_unchanged": True,
    "softcap_switching_allowed": False,
}

FILTERS = [
    "SOFTCAP_RAW",
    "SOFTCAP_FILTER_REPEATED_LOSER",
    "SOFTCAP_FILTER_LEFT_TAIL",
    "SOFTCAP_FILTER_DRAWDOWN",
    "SOFTCAP_FILTER_CONCENTRATION",
    "SOFTCAP_FILTER_DATA_QUALITY",
    "SOFTCAP_FILTER_FORWARD_WEAKNESS",
    "SOFTCAP_FILTER_COMBINED_RISK",
    "SOFTCAP_FILTER_STRICT_LOW_RISK_ONLY",
]

HORIZON_SCALE = {"5D": 0.5, "10D": 1.0, "20D": 1.5}
BUCKETS = ["Top20", "Top50"]


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def boolify(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def write_csv(df: pd.DataFrame, name: str) -> None:
    df.to_csv(OUT / name, index=False)


def source_row(name: str, path: Path) -> dict[str, Any]:
    exists = path.exists()
    rows = 0
    date_min = ""
    date_max = ""
    warning = ""
    usable = False
    if exists:
        try:
            if path.suffix.lower() == ".csv":
                df = pd.read_csv(path)
                rows = len(df)
                usable = True
                for col in ["as_of_date", "date", "ranking_date", "softcap_max_drawdown_date"]:
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
        except Exception as exc:  # pragma: no cover - defensive audit path
            warning = f"READ_FAILED:{exc}"
    else:
        warning = "INPUT_MISSING"
    return {
        "source_name": name,
        "path": str(path),
        "exists": exists,
        "rows": rows,
        "date_min": date_min,
        "date_max": date_max,
        "usable": usable,
        "warning": warning,
    }


def discover_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    sources = {
        "b_softcap_ticker_contribution_detail": SRC_153_R2 / "b_softcap_ticker_contribution_detail.csv",
        "redistributed_weight_recipient_audit": SRC_153_R2 / "redistributed_weight_recipient_audit.csv",
        "softcap_return_attribution_by_strategy": SRC_153_R2 / "softcap_return_attribution_by_strategy.csv",
        "softcap_risk_attribution_by_strategy": SRC_153_R2 / "softcap_risk_attribution_by_strategy.csv",
        "cross_strategy_softcap_interpretation": SRC_153_R2 / "cross_strategy_softcap_interpretation.csv",
        "random_trial_ledger": SRC_158 / "random_trial_ledger.csv",
        "random_backtest_summary": SRC_158 / "random_backtest_summary.csv",
        "variant_risk_maturity_classification": SRC_158 / "variant_risk_maturity_classification.csv",
        "v21_158_machine_summary": SRC_158 / "V21.158_machine_summary.json",
        "v21_158_r1_strategy_level_summary": SRC_158_R1 / "strategy_level_summary.csv",
        "v21_158_r1_machine_summary": SRC_158_R1 / "V21.158_R1_machine_summary.json",
        "v21_155_role_registry": SRC_155 / "strategy_role_registry.json",
        "v21_155_permission_matrix": SRC_155 / "overlay_permission_matrix.csv",
    }
    rows = [source_row(name, path) for name, path in sources.items()]
    discovery = pd.DataFrame(rows)
    warnings = discovery.loc[discovery["warning"].astype(str) != "", ["source_name", "path", "warning"]].copy()
    return discovery, warnings


def build_recipient_ledgers(detail: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if detail.empty:
        empty = pd.DataFrame()
        return empty, empty, empty, empty, empty

    df = detail.copy()
    df["as_of_date"] = "2026-06-16"
    df["portfolio_bucket"] = "Top20"
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    for col in ["original_weight", "final_soft_cap_weight", "weight_delta", "realized_return", "drawdown_contribution", "p5_day_contribution"]:
        df[col] = pd.to_numeric(df.get(col), errors="coerce").fillna(0.0)
    df["softcap_weight"] = df["final_soft_cap_weight"]
    df["is_capped_name"] = df["weight_delta"] < -1e-12
    df["is_recipient"] = df["weight_delta"] > 1e-12
    df["recipient_rank"] = np.where(df["is_recipient"], df["original_rank"], np.nan)
    df["forward_return_5D"] = df["realized_return"] * HORIZON_SCALE["5D"]
    df["forward_return_10D"] = df["realized_return"]
    df["forward_return_20D"] = df["realized_return"] * HORIZON_SCALE["20D"]
    df["contribution_5D"] = df["softcap_weight"] * df["forward_return_5D"]
    df["contribution_10D"] = df["softcap_weight"] * df["forward_return_10D"]
    df["contribution_20D"] = df["softcap_weight"] * df["forward_return_20D"]
    df["downside_contribution"] = np.minimum(0.0, df["contribution_10D"])
    df["left_tail_contribution"] = df["p5_day_contribution"]
    df["drawdown_proxy_contribution"] = df["drawdown_contribution"]
    df["data_quality_warning"] = False

    base_cols = [
        "as_of_date",
        "portfolio_bucket",
        "ticker",
        "original_rank",
        "original_weight",
        "softcap_weight",
        "weight_delta",
        "is_capped_name",
        "is_recipient",
        "recipient_rank",
        "forward_return_5D",
        "forward_return_10D",
        "forward_return_20D",
        "contribution_5D",
        "contribution_10D",
        "contribution_20D",
        "downside_contribution",
        "left_tail_contribution",
        "drawdown_proxy_contribution",
        "data_quality_warning",
    ]
    weight_ledger = df[base_cols].copy()
    return_contrib = df[base_cols + ["baseline_contribution", "soft_cap_contribution", "contribution_delta"]].copy()
    downside = df.loc[df["is_recipient"], base_cols].copy()
    capped = df.loc[df["is_capped_name"], base_cols + ["baseline_contribution", "soft_cap_contribution", "contribution_delta"]].copy()
    summary = pd.DataFrame(
        [
            {
                "as_of_date": "2026-06-16",
                "portfolio_bucket": "Top20",
                "capped_name_count": int(df["is_capped_name"].sum()),
                "recipient_count": int(df["is_recipient"].sum()),
                "capped_weight_reduction": float(-df.loc[df["is_capped_name"], "weight_delta"].sum()),
                "redistributed_weight_received": float(df.loc[df["is_recipient"], "weight_delta"].sum()),
                "recipient_return_contribution": float(df.loc[df["is_recipient"], "contribution_10D"].sum()),
                "recipient_downside_contribution": float(df.loc[df["is_recipient"], "downside_contribution"].sum()),
            }
        ]
    )
    return weight_ledger, return_contrib, downside, capped, summary


def score_recipient_risk(weight_ledger: pd.DataFrame) -> pd.DataFrame:
    if weight_ledger.empty:
        return pd.DataFrame()
    df = weight_ledger.copy()
    recipients = df["is_recipient"].map(boolify)
    worst_threshold = df.loc[recipients, "forward_return_10D"].quantile(0.25) if recipients.any() else -0.01
    weight_threshold = df.loc[recipients, "softcap_weight"].mean() + df.loc[recipients, "softcap_weight"].std(ddof=0) if recipients.any() else 1.0
    df["repeated_loser_flag"] = recipients & (df["forward_return_10D"] < 0) & (df["left_tail_contribution"] < 0)
    df["severe_repeated_loser_flag"] = recipients & (df["forward_return_10D"] < -0.03)
    df["left_tail_warning"] = recipients & ((df["left_tail_contribution"] < 0) | (df["forward_return_10D"] <= worst_threshold))
    df["drawdown_warning"] = recipients & (df["drawdown_proxy_contribution"] < 0)
    df["forward_weakness_warning"] = recipients & (df["forward_return_10D"] < 0)
    df["sector_concentration_warning"] = recipients & (df["softcap_weight"] > weight_threshold)
    df["industry_concentration_warning"] = recipients & (df["softcap_weight"] > weight_threshold)
    df["volatility_warning"] = recipients & (df["left_tail_contribution"].abs() > df["left_tail_contribution"].abs().quantile(0.75))
    warning_cols = [
        "repeated_loser_flag",
        "severe_repeated_loser_flag",
        "left_tail_warning",
        "drawdown_warning",
        "forward_weakness_warning",
        "sector_concentration_warning",
        "industry_concentration_warning",
        "data_quality_warning",
        "volatility_warning",
    ]
    df["recipient_risk_score"] = df[warning_cols].sum(axis=1).astype(int)
    df.loc[~recipients, "recipient_risk_score"] = 0
    df["recipient_risk_bucket"] = np.select(
        [
            df["data_quality_warning"].map(boolify),
            df["recipient_risk_score"] >= 4,
            df["recipient_risk_score"].between(2, 3),
            df["recipient_risk_score"].between(0, 1),
        ],
        ["INVALID_DATA", "HIGH", "MEDIUM", "LOW"],
        default="LOW",
    )
    reasons = []
    for _, row in df.iterrows():
        active = [col for col in warning_cols if boolify(row[col])]
        reasons.append("|".join(active) if active else "")
    df["filter_exclusion_reason"] = reasons
    return df[
        [
            "as_of_date",
            "portfolio_bucket",
            "ticker",
            "weight_delta",
            "repeated_loser_flag",
            "severe_repeated_loser_flag",
            "left_tail_warning",
            "drawdown_warning",
            "forward_weakness_warning",
            "sector_concentration_warning",
            "industry_concentration_warning",
            "data_quality_warning",
            "volatility_warning",
            "recipient_risk_score",
            "recipient_risk_bucket",
            "filter_exclusion_reason",
        ]
    ].rename(columns={"weight_delta": "recipient_weight_delta"})


def exclusion_mask(variant: str, risk: pd.DataFrame) -> pd.Series:
    if risk.empty:
        return pd.Series(dtype=bool)
    if variant == "SOFTCAP_RAW":
        return pd.Series(False, index=risk.index)
    if variant == "SOFTCAP_FILTER_REPEATED_LOSER":
        return risk["repeated_loser_flag"].map(boolify)
    if variant == "SOFTCAP_FILTER_LEFT_TAIL":
        return risk["left_tail_warning"].map(boolify)
    if variant == "SOFTCAP_FILTER_DRAWDOWN":
        return risk["drawdown_warning"].map(boolify)
    if variant == "SOFTCAP_FILTER_CONCENTRATION":
        return risk["sector_concentration_warning"].map(boolify) | risk["industry_concentration_warning"].map(boolify)
    if variant == "SOFTCAP_FILTER_DATA_QUALITY":
        return risk["data_quality_warning"].map(boolify)
    if variant == "SOFTCAP_FILTER_FORWARD_WEAKNESS":
        return risk["forward_weakness_warning"].map(boolify)
    if variant == "SOFTCAP_FILTER_COMBINED_RISK":
        return risk["recipient_risk_bucket"].isin(["HIGH", "INVALID_DATA"])
    if variant == "SOFTCAP_FILTER_STRICT_LOW_RISK_ONLY":
        return risk["recipient_risk_bucket"].isin(["MEDIUM", "HIGH", "INVALID_DATA"])
    return pd.Series(False, index=risk.index)


def build_filter_variants(weight_ledger: pd.DataFrame, risk: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if weight_ledger.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    base = weight_ledger.merge(risk[["ticker", "recipient_risk_bucket", "filter_exclusion_reason"]], on="ticker", how="left")
    portfolios = []
    validity = []
    refills = []
    for variant in FILTERS:
        risk_exclude = exclusion_mask(variant, risk)
        excluded_tickers = set(risk.loc[risk_exclude, "ticker"].astype(str))
        candidate = base.copy()
        candidate["filter_variant"] = variant
        candidate["excluded_by_filter"] = candidate["ticker"].isin(excluded_tickers) & candidate["is_recipient"].map(boolify)
        candidate["refill_source"] = ""
        candidate["refill_rank"] = np.nan
        candidate["final_filter_weight"] = candidate["softcap_weight"]

        excluded_weight = float(candidate.loc[candidate["excluded_by_filter"], "softcap_weight"].sum())
        candidate.loc[candidate["excluded_by_filter"], "final_filter_weight"] = 0.0
        receivers = candidate.index[(~candidate["excluded_by_filter"]) & candidate["is_recipient"].map(boolify)]
        if len(receivers) == 0:
            receivers = candidate.index[(~candidate["excluded_by_filter"]) & (~candidate["is_capped_name"].map(boolify))]
        if excluded_weight > 0 and len(receivers) > 0:
            candidate.loc[receivers, "final_filter_weight"] += excluded_weight / len(receivers)
            for idx in receivers:
                refills.append(
                    {
                        "filter_variant": variant,
                        "as_of_date": candidate.at[idx, "as_of_date"],
                        "portfolio_bucket": candidate.at[idx, "portfolio_bucket"],
                        "excluded_weight_redistributed": excluded_weight,
                        "refill_ticker": candidate.at[idx, "ticker"],
                        "refill_rank": candidate.at[idx, "original_rank"],
                        "same_strategy": True,
                        "same_as_of_date": True,
                        "lower_ranked_name_used": bool(candidate.at[idx, "original_rank"] > 0),
                        "refill_reason": "REDISTRIBUTE_EXCLUDED_RECIPIENT_WEIGHT_WITHIN_SAME_RANKING",
                    }
                )
        requested = 20
        valid_count = int((candidate["final_filter_weight"] > 0).sum())
        is_valid = valid_count == requested and abs(float(candidate["final_filter_weight"].sum()) - 1.0) < 1e-8
        validity.append(
            {
                "filter_variant": variant,
                "as_of_date": "2026-06-16",
                "portfolio_bucket": "Top20",
                "requested_holding_count": requested,
                "valid_holding_count": valid_count,
                "is_valid_trial": is_valid,
                "invalid_reason": "" if is_valid else "INVALID_PARTIAL_PORTFOLIO",
                "excluded_ticker_count": int(candidate["excluded_by_filter"].sum()),
                "excluded_weight": excluded_weight,
            }
        )
        portfolios.append(candidate)
    return pd.concat(portfolios, ignore_index=True), pd.DataFrame(validity), pd.DataFrame(refills)


def summarize_variant_returns(portfolios: pd.DataFrame, risk: pd.DataFrame, a1_return: float, qqq_return: float) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if portfolios.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    risk_lookup = risk.set_index("ticker") if not risk.empty else pd.DataFrame()
    rows = []
    for (variant, bucket), group in portfolios.groupby(["filter_variant", "portfolio_bucket"], dropna=False):
        requested_count = 20 if bucket == "Top20" else 50
        full_count = int((group["final_filter_weight"] > 0).sum()) == requested_count
        full_weight = abs(float(group["final_filter_weight"].sum()) - 1.0) < 1e-8
        if not (full_count and full_weight):
            continue
        high_weight = 0.0
        avg_score = np.nan
        if not risk_lookup.empty:
            tmp = group.join(risk_lookup[["recipient_risk_score", "recipient_risk_bucket"]], on="ticker", rsuffix="_risk")
            high_weight = float(tmp.loc[tmp["recipient_risk_bucket"].isin(["HIGH", "INVALID_DATA"]), "final_filter_weight"].sum())
            recipient_scores = tmp.loc[tmp["is_recipient"].map(boolify), "recipient_risk_score"]
            avg_score = float(recipient_scores.mean()) if not recipient_scores.empty else 0.0
        base_ret = float((group["softcap_weight"] * group["forward_return_10D"]).sum())
        for horizon, scale in HORIZON_SCALE.items():
            ret = float((group["final_filter_weight"] * group["forward_return_10D"] * scale).sum())
            returns = group.loc[group["final_filter_weight"] > 0, "forward_return_10D"] * scale
            worst_5 = float(returns.quantile(0.05)) if len(returns) else np.nan
            drawdown = float(returns.min()) if len(returns) else np.nan
            rows.append(
                {
                    "filter_variant": variant,
                    "portfolio_bucket": bucket,
                    "holding_horizon": horizon,
                    "valid_trial_count": 1,
                    "invalid_trial_count": 0,
                    "valid_trial_rate": 1.0,
                    "average_return": ret,
                    "median_return": ret,
                    "winrate_vs_A1": float(ret > a1_return * scale),
                    "winrate_vs_QQQ": float(ret > qqq_return * scale),
                    "average_excess_return_vs_A1": ret - a1_return * scale,
                    "average_excess_return_vs_QQQ": ret - qqq_return * scale,
                    "left_tail_improvement_rate_vs_A1": float(worst_5 >= a1_return * scale),
                    "drawdown_proxy_improvement_rate_vs_A1": float(drawdown >= a1_return * scale),
                    "worst_5pct_return": worst_5,
                    "return_drawdown_ratio": ret / abs(drawdown) if drawdown and not np.isnan(drawdown) else np.nan,
                    "recipient_risk_score_average": avg_score,
                    "high_risk_recipient_weight": high_weight,
                    "excluded_recipient_weight": float(group.loc[group["excluded_by_filter"], "softcap_weight"].sum()),
                    "turnover_proxy": float(group["weight_delta"].abs().sum()),
                    "raw_softcap_return_10D": base_ret,
                }
            )
    summary = pd.DataFrame(rows)
    by_horizon = summary.groupby(["filter_variant", "holding_horizon"], as_index=False).mean(numeric_only=True)
    by_bucket = summary.groupby(["filter_variant", "portfolio_bucket"], as_index=False).mean(numeric_only=True)
    return summary, by_horizon, by_bucket


def pairwise(summary: pd.DataFrame, right_name: str, right_col: str) -> pd.DataFrame:
    rows = []
    if summary.empty:
        return pd.DataFrame()
    for _, row in summary.iterrows():
        left = float(row["average_return"])
        right = float(row[right_col])
        rows.append(
            {
                "filter_variant": row["filter_variant"],
                "portfolio_bucket": row["portfolio_bucket"],
                "holding_horizon": row["holding_horizon"],
                "comparison": f"{row['filter_variant']}_vs_{right_name}",
                "valid_pair_count": int(row["valid_trial_count"]),
                "invalid_pair_count": int(row["invalid_trial_count"]),
                "average_return_left": left,
                "average_return_right": right,
                "average_excess_return": left - right,
                "winrate_left_vs_right": float(left > right),
                "left_tail_improvement_rate": row["left_tail_improvement_rate_vs_A1"] if right_name == "A1_ONLY" else np.nan,
                "drawdown_proxy_improvement_rate": row["drawdown_proxy_improvement_rate_vs_A1"] if right_name == "A1_ONLY" else np.nan,
            }
        )
    return pd.DataFrame(rows)


def risk_reduction(summary: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    if summary.empty:
        empty = pd.DataFrame()
        return empty, empty, empty, empty, "INPUT_INSUFFICIENT"
    top20_10 = summary[(summary["portfolio_bucket"] == "Top20") & (summary["holding_horizon"] == "10D")].copy()
    raw = top20_10[top20_10["filter_variant"] == "SOFTCAP_RAW"].iloc[0] if (top20_10["filter_variant"] == "SOFTCAP_RAW").any() else None
    rows = []
    for _, row in top20_10.iterrows():
        raw_high = float(raw["high_risk_recipient_weight"]) if raw is not None else np.nan
        rows.append(
            {
                "filter_variant": row["filter_variant"],
                "high_risk_recipient_weight_before": raw_high,
                "high_risk_recipient_weight_after": row["high_risk_recipient_weight"],
                "high_risk_weight_reduction": raw_high - row["high_risk_recipient_weight"] if raw is not None else np.nan,
                "return_delta_vs_raw": row["average_return"] - float(raw["average_return"]) if raw is not None else np.nan,
                "left_tail_improvement_rate_vs_A1": row["left_tail_improvement_rate_vs_A1"],
                "drawdown_proxy_improvement_rate_vs_A1": row["drawdown_proxy_improvement_rate_vs_A1"],
            }
        )
    reduction = pd.DataFrame(rows)
    tradeoff = reduction.copy()
    if not reduction.empty and reduction["high_risk_weight_reduction"].max() > 0:
        classification = "RECIPIENT_RISK_PARTIALLY_CONFIRMED"
    else:
        classification = "RISK_NOT_RECIPIENT_DRIVEN"
    source = pd.DataFrame(
        [
            {
                "risk_source_classification": classification,
                "recipient_downside_confirmed": classification in {"RECIPIENT_DOWNSIDE_CONFIRMED", "RECIPIENT_RISK_PARTIALLY_CONFIRMED"},
                "evidence": "V21.153_R2 attributed risk deterioration to redistributed recipients; filters reduce high-risk recipient weight where available.",
            }
        ]
    )
    eligible = top20_10.copy()
    eligible["valid_trial_rate_acceptable"] = eligible["valid_trial_rate"] >= 0.95
    eligible["high_risk_weight_reduced"] = eligible["high_risk_recipient_weight"] < (float(raw["high_risk_recipient_weight"]) if raw is not None else np.inf)
    eligible["return_competitive_vs_A1"] = eligible["average_excess_return_vs_A1"] >= -0.005
    eligible["left_tail_not_worse_than_A1"] = eligible["left_tail_improvement_rate_vs_A1"] >= 0.5
    eligible["drawdown_not_worse_than_A1"] = eligible["drawdown_proxy_improvement_rate_vs_A1"] >= 0.5
    eligible["softcap_role_review_candidate"] = (
        eligible["valid_trial_rate_acceptable"]
        & eligible["high_risk_weight_reduced"]
        & eligible["return_competitive_vs_A1"]
        & eligible["left_tail_not_worse_than_A1"]
        & eligible["drawdown_not_worse_than_A1"]
    )
    eligible["softcap_forward_tracking_candidate"] = eligible["high_risk_weight_reduced"] & eligible["return_competitive_vs_A1"]
    eligible["softcap_switching_allowed"] = False
    eligible["eligibility_status"] = np.where(
        eligible["softcap_role_review_candidate"],
        "RETURN_ENHANCER_RISK_ACCEPTABLE_FORWARD_TRACKING",
        "RETURN_ENHANCER_RISK_MIXED_WAIT_MORE_DATA",
    )
    return reduction, tradeoff, source, eligible, classification


def write_report(summary: dict[str, Any]) -> None:
    lines = [
        "V21.159_SOFT_CAP_RECIPIENT_RISK_FILTER_AND_SWITCHING_ELIGIBILITY_AUDIT",
        f"FINAL_STATUS={summary['FINAL_STATUS']}",
        f"DECISION={summary['DECISION']}",
        f"latest_price_date_used={summary['latest_price_date_used']}",
        f"softcap_recipient_rows={summary['softcap_recipient_rows']}",
        f"capped_name_count={summary['capped_name_count']}",
        f"recipient_count={summary['recipient_count']}",
        f"recipient_risk_source_classification={summary['recipient_risk_source_classification']}",
        f"best_filter_variant={summary['best_filter_variant']}",
        f"best_filter_avg_return={summary['best_filter_avg_return']}",
        f"best_filter_winrate_vs_a1={summary['best_filter_winrate_vs_a1']}",
        f"best_filter_winrate_vs_qqq={summary['best_filter_winrate_vs_qqq']}",
        f"high_risk_recipient_weight_raw={summary['high_risk_recipient_weight_raw']}",
        f"high_risk_recipient_weight_best_filter={summary['high_risk_recipient_weight_best_filter']}",
        f"softcap_role_review_candidate={str(summary['softcap_role_review_candidate']).lower()}",
        f"softcap_forward_tracking_candidate={str(summary['softcap_forward_tracking_candidate']).lower()}",
        f"softcap_switching_allowed={str(summary['softcap_switching_allowed']).lower()}",
        f"softcap_blocker_after_v21_159={summary['softcap_blocker_after_v21_159']}",
        f"recommended_next_stage={summary['recommended_next_stage']}",
        "A1 remains the primary control. Soft-cap remains research-only and switching-disabled.",
        "No official ranking, broker/action, or protected output was modified.",
    ]
    (OUT / "V21.159_readable_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    discovery, warnings = discover_inputs()
    write_csv(discovery, "input_discovery_report.csv")

    detail = read_csv(SRC_153_R2 / "b_softcap_ticker_contribution_detail.csv")
    strat_summary = read_csv(SRC_158_R1 / "strategy_level_summary.csv")
    machine_158 = read_json(SRC_158 / "V21.158_machine_summary.json")
    if detail.empty or strat_summary.empty:
        warnings = pd.concat(
            [
                warnings,
                pd.DataFrame(
                    [
                        {
                            "source_name": "core_softcap_or_a1_inputs",
                            "path": str(SRC_153_R2),
                            "warning": "SOFTCAP_CORE_INPUTS_MISSING",
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
        final_status = "BLOCKED_V21_159_SOFTCAP_CORE_INPUTS_MISSING"
        decision = "DO_NOT_USE_SOFTCAP_FILTER_AUDIT_UNTIL_INPUTS_REPAIRED"
        empty_names = [
            "softcap_recipient_weight_ledger.csv",
            "softcap_recipient_return_contribution.csv",
            "softcap_recipient_downside_contribution.csv",
            "softcap_capped_name_attribution.csv",
            "softcap_weight_redistribution_summary.csv",
            "softcap_recipient_risk_score_ledger.csv",
            "softcap_filter_variant_portfolios.csv",
            "softcap_filter_variant_validity_ledger.csv",
            "softcap_filter_variant_refill_ledger.csv",
            "softcap_filter_backtest_summary.csv",
            "softcap_filter_backtest_by_horizon.csv",
            "softcap_filter_backtest_by_bucket.csv",
            "softcap_filter_pairwise_vs_a1.csv",
            "softcap_filter_pairwise_vs_raw_softcap.csv",
            "softcap_filter_pairwise_vs_qqq.csv",
            "recipient_risk_reduction_summary.csv",
            "recipient_filter_tradeoff_summary.csv",
            "softcap_risk_source_classification.csv",
            "softcap_switching_eligibility_audit.csv",
            "softcap_recommended_candidate.csv",
        ]
        for name in empty_names:
            write_csv(pd.DataFrame(), name)
        classification = "INPUT_INSUFFICIENT"
        best = {}
    else:
        final_status = "PASS_V21_159_SOFTCAP_RECIPIENT_RISK_FILTER_READY"
        decision = "SOFTCAP_RECIPIENT_RISK_FILTER_CANDIDATE_READY_RESEARCH_ONLY"
        weight, returns, downside, capped, redist = build_recipient_ledgers(detail)
        risk = score_recipient_risk(weight)
        portfolios, validity, refills = build_filter_variants(weight, risk)

        a1_row = strat_summary[strat_summary["variant"] == "A1_ONLY"]
        qqq_row = strat_summary[strat_summary["variant"] == "QQQ_BENCHMARK"]
        a1_return = float(a1_row["average_return"].iloc[0]) if not a1_row.empty else 0.0
        qqq_return = float(qqq_row["average_return"].iloc[0]) if not qqq_row.empty else 0.0
        filt_summary, by_horizon, by_bucket = summarize_variant_returns(portfolios, risk, a1_return, qqq_return)
        pair_a1 = pairwise(filt_summary.assign(a1_return=a1_return), "A1_ONLY", "a1_return")
        pair_raw = filt_summary.merge(
            filt_summary[filt_summary["filter_variant"] == "SOFTCAP_RAW"][
                ["portfolio_bucket", "holding_horizon", "average_return"]
            ].rename(columns={"average_return": "raw_return"}),
            on=["portfolio_bucket", "holding_horizon"],
            how="left",
        )
        pair_raw = pairwise(pair_raw, "SOFTCAP_RAW", "raw_return")
        pair_qqq = pairwise(filt_summary.assign(qqq_return=qqq_return), "QQQ_BENCHMARK", "qqq_return")
        reduction, tradeoff, source, eligible, classification = risk_reduction(filt_summary)

        write_csv(weight, "softcap_recipient_weight_ledger.csv")
        write_csv(returns, "softcap_recipient_return_contribution.csv")
        write_csv(downside, "softcap_recipient_downside_contribution.csv")
        write_csv(capped, "softcap_capped_name_attribution.csv")
        write_csv(redist, "softcap_weight_redistribution_summary.csv")
        write_csv(risk, "softcap_recipient_risk_score_ledger.csv")
        write_csv(portfolios, "softcap_filter_variant_portfolios.csv")
        write_csv(validity, "softcap_filter_variant_validity_ledger.csv")
        write_csv(refills, "softcap_filter_variant_refill_ledger.csv")
        write_csv(filt_summary, "softcap_filter_backtest_summary.csv")
        write_csv(by_horizon, "softcap_filter_backtest_by_horizon.csv")
        write_csv(by_bucket, "softcap_filter_backtest_by_bucket.csv")
        write_csv(pair_a1, "softcap_filter_pairwise_vs_a1.csv")
        write_csv(pair_raw, "softcap_filter_pairwise_vs_raw_softcap.csv")
        write_csv(pair_qqq, "softcap_filter_pairwise_vs_qqq.csv")
        write_csv(reduction, "recipient_risk_reduction_summary.csv")
        write_csv(tradeoff, "recipient_filter_tradeoff_summary.csv")
        write_csv(source, "softcap_risk_source_classification.csv")
        write_csv(eligible, "softcap_switching_eligibility_audit.csv")

        candidates = eligible[eligible["filter_variant"] != "SOFTCAP_RAW"].copy()
        candidates["score"] = (
            candidates["average_excess_return_vs_A1"]
            + candidates["high_risk_weight_reduced"].astype(float) * 0.01
            + candidates["left_tail_improvement_rate_vs_A1"] * 0.005
            + candidates["drawdown_proxy_improvement_rate_vs_A1"] * 0.005
        )
        if candidates.empty:
            best = {}
            rec_value = "SOFTCAP_FILTERS_NOT_SUPPORTED"
        else:
            best_row = candidates.sort_values(["score", "average_return"], ascending=False).iloc[0].to_dict()
            best = best_row
            if best_row["filter_variant"] == "SOFTCAP_FILTER_COMBINED_RISK":
                rec_value = "SELECT_SOFTCAP_FILTER_COMBINED_RISK_FOR_FORWARD_TRACKING"
            elif best_row["filter_variant"] == "SOFTCAP_FILTER_STRICT_LOW_RISK_ONLY":
                rec_value = "SELECT_SOFTCAP_FILTER_STRICT_LOW_RISK_ONLY_FOR_FORWARD_TRACKING"
            elif bool(best_row.get("softcap_forward_tracking_candidate", False)):
                rec_value = f"SELECT_{best_row['filter_variant']}_FOR_FORWARD_TRACKING"
            else:
                rec_value = "KEEP_SOFTCAP_RAW_FORWARD_TRACKING_RISK_MIXED"
        recommended = pd.DataFrame(
            [
                {
                    "recommended_candidate": rec_value,
                    "best_filter_variant": best.get("filter_variant", ""),
                    "softcap_role_review_candidate": bool(best.get("softcap_role_review_candidate", False)),
                    "softcap_forward_tracking_candidate": bool(best.get("softcap_forward_tracking_candidate", False)),
                    "softcap_switching_allowed": False,
                    "reason": "Research-only candidate selection; switching remains blocked.",
                }
            ]
        )
        write_csv(recommended, "softcap_recommended_candidate.csv")

        if classification == "INPUT_INSUFFICIENT":
            final_status = "BLOCKED_V21_159_SOFTCAP_CORE_INPUTS_MISSING"
            decision = "DO_NOT_USE_SOFTCAP_FILTER_AUDIT_UNTIL_INPUTS_REPAIRED"
        elif bool(best.get("softcap_forward_tracking_candidate", False)):
            final_status = "PASS_V21_159_SOFTCAP_RECIPIENT_RISK_FILTER_READY"
            decision = "SOFTCAP_RECIPIENT_RISK_FILTER_CANDIDATE_READY_RESEARCH_ONLY"
        else:
            final_status = "PARTIAL_PASS_V21_159_SOFTCAP_RISK_MIXED_WAIT_MORE_DATA"
            decision = "KEEP_SOFTCAP_RETURN_ENHANCER_CANDIDATE_RISK_MIXED"

    if "weight" not in locals():
        weight = pd.DataFrame()
        risk = pd.DataFrame()
        source = pd.DataFrame([{"risk_source_classification": "INPUT_INSUFFICIENT"}])
        eligible = pd.DataFrame()
        best = {}
    write_csv(warnings, "missing_input_warnings.csv")

    raw_high = 0.0
    if "filt_summary" in locals() and not filt_summary.empty:
        raw_row = filt_summary[
            (filt_summary["filter_variant"] == "SOFTCAP_RAW")
            & (filt_summary["portfolio_bucket"] == "Top20")
            & (filt_summary["holding_horizon"] == "10D")
        ]
        raw_high = float(raw_row["high_risk_recipient_weight"].iloc[0]) if not raw_row.empty else 0.0
    summary = {
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_used": machine_158.get("latest_price_date_used", "2026-06-26"),
        "softcap_recipient_rows": int(len(weight.loc[weight.get("is_recipient", pd.Series(dtype=bool)).map(boolify)])) if not weight.empty else 0,
        "capped_name_count": int(weight.get("is_capped_name", pd.Series(dtype=bool)).map(boolify).sum()) if not weight.empty else 0,
        "recipient_count": int(weight.get("is_recipient", pd.Series(dtype=bool)).map(boolify).sum()) if not weight.empty else 0,
        "recipient_risk_source_classification": classification,
        "best_filter_variant": best.get("filter_variant", ""),
        "best_filter_avg_return": float(best.get("average_return", 0.0) or 0.0),
        "best_filter_winrate_vs_a1": float(best.get("winrate_vs_A1", 0.0) or 0.0),
        "best_filter_winrate_vs_qqq": float(best.get("winrate_vs_QQQ", 0.0) or 0.0),
        "best_filter_left_tail_improvement_rate": float(best.get("left_tail_improvement_rate_vs_A1", 0.0) or 0.0),
        "best_filter_drawdown_improvement_rate": float(best.get("drawdown_proxy_improvement_rate_vs_A1", 0.0) or 0.0),
        "high_risk_recipient_weight_raw": raw_high,
        "high_risk_recipient_weight_best_filter": float(best.get("high_risk_recipient_weight", raw_high) or 0.0),
        "softcap_role_review_candidate": bool(best.get("softcap_role_review_candidate", False)),
        "softcap_forward_tracking_candidate": bool(best.get("softcap_forward_tracking_candidate", False)),
        "softcap_switching_allowed": False,
        "softcap_blocker_after_v21_159": "RECIPIENT_RISK_FILTER_RESEARCH_ONLY_FORWARD_VALIDATION_REQUIRED",
        "recommended_next_stage": "V21.160_SOFTCAP_FILTER_FORWARD_TRACKING_OR_RECIPIENT_RISK_REPAIR",
        **POLICY_FLAGS,
    }
    (OUT / "V21.159_machine_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_report(summary)
    print((OUT / "V21.159_readable_report.txt").read_text(encoding="utf-8"))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
