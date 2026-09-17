"""A-versus-A2 incremental realized contribution, without causal claims."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .engine import AttributionInputError, normalize_daily, normalize_rows, reconcile_daily
from .schemas import AttributionConfig


def _sum_min(values: pd.Series) -> float:
    return float(values.sum(min_count=1))


def _side(rows: pd.DataFrame, prefix: str) -> pd.DataFrame:
    keys = ["date", "security_id", "component_type"]
    grouped = rows.groupby(keys, as_index=False).agg(
        net_contribution=("net_contribution", "sum"), gross_contribution=("gross_contribution", _sum_min),
        cost_contribution=("cost_contribution", _sum_min), turnover_contribution=("turnover_contribution", _sum_min),
        portfolio_weight=("portfolio_weight", _sum_min), rank=("rank", "min"),
        sector=("sector", "first"), rank_bucket=("rank_bucket", "first"), universe_id=("universe_id", "first"),
    )
    return grouped.rename(columns={column: f"{prefix}_{column}" for column in grouped if column not in keys})


def _aggregate(frame: pd.DataFrame, dimension: str) -> pd.DataFrame:
    return frame.groupby(dimension, as_index=False, dropna=False).agg(
        a_contribution=("a_net_contribution", "sum"), a2_contribution=("a2_net_contribution", "sum"),
        incremental_contribution=("incremental_contribution", "sum"),
        incremental_cost_a2_minus_a=("incremental_cost_a2_minus_a", _sum_min),
        row_count=("security_id", "count"),
    ).sort_values(["incremental_contribution", dimension], ascending=[False, True], kind="mergesort").reset_index(drop=True)


class IncrementalAttributionEngine:
    def __init__(self, config: AttributionConfig | None = None):
        self.config = config or AttributionConfig()
        self.config.validate()

    def run(
        self,
        a_rows: pd.DataFrame,
        a2_rows: pd.DataFrame,
        a_daily: pd.DataFrame,
        a2_daily: pd.DataFrame,
    ) -> dict[str, Any]:
        a, a2 = normalize_rows(a_rows, self.config), normalize_rows(a2_rows, self.config)
        daily_a, daily_a2 = normalize_daily(a_daily), normalize_daily(a2_daily)
        if a.strategy_id.nunique() != 1 or a2.strategy_id.nunique() != 1:
            raise AttributionInputError("incremental attribution requires one strategy per side")
        reasons: list[str] = []
        a_identity = reconcile_daily(a, daily_a, self.config.identity_tolerance)
        a2_identity = reconcile_daily(a2, daily_a2, self.config.identity_tolerance)
        if a_identity["status"] != "PASS":
            reasons.append("a_attribution_identity_failed")
        if a2_identity["status"] != "PASS":
            reasons.append("a2_attribution_identity_failed")
        dates_a, dates_a2 = set(daily_a.date), set(daily_a2.date)
        if self.config.require_same_incremental_dates and dates_a != dates_a2:
            reasons.append("different_benchmark_window_or_unmatched_date")
        universes_a, universes_a2 = set(a.universe_id), set(a2.universe_id)
        if self.config.require_same_incremental_universe and universes_a != universes_a2:
            reasons.append("universe_identity_mismatch")

        aligned = _side(a, "a").merge(
            _side(a2, "a2"), on=["date", "security_id", "component_type"], how="outer",
            indicator=True, validate="one_to_one",
        )
        a_columns = ("a_net_contribution", "a_gross_contribution", "a_cost_contribution", "a_turnover_contribution", "a_portfolio_weight")
        a2_columns = ("a2_net_contribution", "a2_gross_contribution", "a2_cost_contribution", "a2_turnover_contribution", "a2_portfolio_weight")
        aligned.loc[aligned._merge.eq("right_only"), list(a_columns)] = aligned.loc[
            aligned._merge.eq("right_only"), list(a_columns)
        ].fillna(0.0)
        aligned.loc[aligned._merge.eq("left_only"), list(a2_columns)] = aligned.loc[
            aligned._merge.eq("left_only"), list(a2_columns)
        ].fillna(0.0)
        aligned["incremental_contribution"] = aligned.a2_net_contribution - aligned.a_net_contribution
        aligned["incremental_gross_a2_minus_a"] = aligned.a2_gross_contribution - aligned.a_gross_contribution
        aligned["incremental_cost_a2_minus_a"] = aligned.a2_cost_contribution - aligned.a_cost_contribution
        aligned["incremental_turnover_a2_minus_a"] = aligned.a2_turnover_contribution - aligned.a_turnover_contribution
        weight_diff = (aligned.a2_portfolio_weight - aligned.a_portfolio_weight).abs()
        weights_known = aligned.a_portfolio_weight.notna() & aligned.a2_portfolio_weight.notna()
        aligned["position_class"] = np.where(
            aligned._merge.eq("right_only"), "A2_ONLY",
            np.where(aligned._merge.eq("left_only"), "A_ONLY",
                     np.where(weights_known & (weight_diff > self.config.incremental_weight_tolerance), "DIFFERENT_WEIGHT", "COMMON_POSITION")),
        )
        aligned["difference_taxonomy"] = np.where(
            aligned.component_type.ne("SECURITY"), "EXPLICIT_COMPONENT_DIFFERENCE",
            np.where(aligned._merge.eq("right_only"), "A2_ONLY_SELECTION",
                     np.where(aligned._merge.eq("left_only"), "A_ONLY_SELECTION",
                              np.where(~weights_known, "COMMON_SECURITY_WEIGHT_UNKNOWN",
                                       np.where(weight_diff > self.config.incremental_weight_tolerance,
                                                "COMMON_SECURITY_WEIGHT_DIFFERENCE", "COMMON_SECURITY_SAME_OR_NEAR_WEIGHT")))),
        )
        aligned["sector"] = aligned.a2_sector.combine_first(aligned.a_sector).fillna("UNKNOWN")
        aligned["rank_bucket"] = aligned.a2_rank_bucket.combine_first(aligned.a_rank_bucket).fillna("UNRANKED")
        aligned["year"] = aligned.date.dt.year.astype(str)

        daily_compare = daily_a[["date", "authoritative_portfolio_return"]].rename(
            columns={"authoritative_portfolio_return": "a_portfolio_contribution"}
        ).merge(
            daily_a2[["date", "authoritative_portfolio_return"]].rename(
                columns={"authoritative_portfolio_return": "a2_portfolio_contribution"}
            ), on="date", how="outer", indicator=True,
        )
        observed = aligned.groupby("date", as_index=False).incremental_contribution.sum()
        daily_compare = daily_compare.merge(observed, on="date", how="outer")
        daily_compare["expected_incremental_contribution"] = (
            daily_compare.a2_portfolio_contribution - daily_compare.a_portfolio_contribution
        )
        daily_compare["identity_error"] = (
            daily_compare.incremental_contribution - daily_compare.expected_incremental_contribution
        )
        if daily_compare.identity_error.isna().any():
            reasons.append("missing_row_or_daily_portfolio_contribution")
        max_error = float(daily_compare.identity_error.abs().max()) if daily_compare.identity_error.notna().any() else float("inf")
        if max_error > self.config.identity_tolerance:
            reasons.append("incremental_identity_tolerance_exceeded")
        identity = {
            "status": "PASS" if not reasons else "FAIL", "tolerance": self.config.identity_tolerance,
            "max_daily_identity_error": max_error,
            "total_identity_error": float(aligned.incremental_contribution.sum() - (
                daily_a2.authoritative_portfolio_return.sum() - daily_a.authoritative_portfolio_return.sum()
            )),
            "a_only_row_count": int((aligned.position_class == "A_ONLY").sum()),
            "a2_only_row_count": int((aligned.position_class == "A2_ONLY").sum()),
            "reasons": sorted(set(reasons)), "daily": daily_compare.drop(columns="_merge"),
            "a_identity_status": a_identity["status"], "a2_identity_status": a2_identity["status"],
        }
        return {
            "status": identity["status"], "interpretation": "INCREMENTAL_REALIZED_CONTRIBUTION_NOT_CAUSAL_MODEL_SKILL",
            "aligned": aligned.drop(columns="_merge"), "identity": identity,
            "by_security": _aggregate(aligned, "security_id"), "by_date": _aggregate(aligned, "date"),
            "by_year": _aggregate(aligned, "year"), "by_sector": _aggregate(aligned, "sector"),
            "by_rank_bucket": _aggregate(aligned, "rank_bucket"),
            "incremental_cost_a2_minus_a": (
                float(aligned.incremental_cost_a2_minus_a.sum(min_count=1))
                if aligned.incremental_cost_a2_minus_a.notna().any() else None
            ),
            "incremental_turnover_a2_minus_a": (
                float(aligned.incremental_turnover_a2_minus_a.sum(min_count=1))
                if aligned.incremental_turnover_a2_minus_a.notna().any() else None
            ),
        }
