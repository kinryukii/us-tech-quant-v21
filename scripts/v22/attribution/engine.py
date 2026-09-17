"""Additive realized portfolio attribution with fail-closed reconciliation."""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .drawdown import detect_drawdown_episodes, drawdown_window_diagnostics
from .schemas import AttributionConfig, COMPONENT_TYPES, FIELD_ROLES


NUMERIC_COLUMNS = (
    "rank", "portfolio_weight", "previous_weight", "security_return", "portfolio_contribution",
    "transaction_cost", "turnover_contribution", "gross_contribution", "net_contribution",
    "cost_contribution", "nav_before", "nav_after",
)
TEXT_COLUMNS = (
    "strategy_id", "date", "security_id", "ticker", "sector", "industry", "component_type",
    "universe_id", "model_id", "vintage_id", "fold", "regime", "contribution_source",
)
DAILY_NUMERIC_COLUMNS = (
    "authoritative_portfolio_return", "authoritative_gross_return",
    "authoritative_cost_contribution", "nav_before", "nav_after",
)


class AttributionInputError(ValueError):
    pass


def _frame(rows: pd.DataFrame | Iterable[dict[str, Any]]) -> pd.DataFrame:
    return rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows))


def _finite_numeric(frame: pd.DataFrame, columns: Iterable[str]) -> None:
    for column in columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        invalid = frame[column].notna() & ~np.isfinite(frame[column])
        if invalid.any():
            raise AttributionInputError(f"non-finite numeric values in {column}")


def normalize_rows(
    rows: pd.DataFrame | Iterable[dict[str, Any]], config: AttributionConfig,
) -> pd.DataFrame:
    frame = _frame(rows)
    for column in TEXT_COLUMNS + NUMERIC_COLUMNS:
        if column not in frame:
            frame[column] = np.nan
    missing_columns = [name for name in FIELD_ROLES["REQUIRED"] if name not in frame or frame[name].isna().any()]
    if missing_columns:
        raise AttributionInputError(f"missing required row fields: {sorted(set(missing_columns))}")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    if frame["date"].isna().any():
        raise AttributionInputError("invalid row date")
    for column in ("strategy_id", "security_id", "model_id", "universe_id", "vintage_id"):
        if frame[column].astype(str).str.strip().isin({"", "UNKNOWN", "nan", "None"}).any():
            raise AttributionInputError(f"required identity field is unknown: {column}")
        frame[column] = frame[column].astype(str)
    frame["component_type"] = frame["component_type"].astype(str).str.upper()
    invalid_components = sorted(set(frame.loc[~frame.component_type.isin(COMPONENT_TYPES), "component_type"]))
    if invalid_components:
        raise AttributionInputError(f"invalid component types: {invalid_components}")
    for column in ("ticker", "sector", "industry"):
        frame[column] = frame[column].where(frame[column].notna() & frame[column].astype(str).str.strip().ne(""), "UNKNOWN")
        frame[column] = frame[column].astype(str)
    frame["contribution_source"] = frame["contribution_source"].astype("object")
    _finite_numeric(frame, NUMERIC_COLUMNS)
    if config.transaction_cost_is_positive_charge and (frame.transaction_cost.dropna() < 0).any():
        raise AttributionInputError("transaction_cost must be a nonnegative charge under configured convention")
    if (frame.cost_contribution.dropna() > config.identity_tolerance).any():
        raise AttributionInputError("cost_contribution must be signed nonpositive")

    if config.transaction_cost_is_positive_charge:
        from_charge = frame.cost_contribution.isna() & frame.transaction_cost.notna()
        frame.loc[from_charge, "cost_contribution"] = -frame.loc[from_charge, "transaction_cost"].abs()
    from_authoritative = frame.net_contribution.isna() & frame.portfolio_contribution.notna()
    frame.loc[from_authoritative, "net_contribution"] = frame.loc[from_authoritative, "portfolio_contribution"]
    frame.loc[from_authoritative & frame.contribution_source.isna(), "contribution_source"] = "AUTHORITATIVE_PORTFOLIO_CONTRIBUTION"

    net_from_components = frame.net_contribution.isna() & frame.gross_contribution.notna() & frame.cost_contribution.notna()
    frame.loc[net_from_components, "net_contribution"] = (
        frame.loc[net_from_components, "gross_contribution"] + frame.loc[net_from_components, "cost_contribution"]
    )
    frame.loc[net_from_components & frame.contribution_source.isna(), "contribution_source"] = "ARITHMETIC_GROSS_PLUS_COST"
    gross_from_net = frame.gross_contribution.isna() & frame.net_contribution.notna() & frame.cost_contribution.notna()
    frame.loc[gross_from_net, "gross_contribution"] = (
        frame.loc[gross_from_net, "net_contribution"] - frame.loc[gross_from_net, "cost_contribution"]
    )
    derived = frame.net_contribution.isna() & frame.portfolio_weight.notna() & frame.security_return.notna()
    if derived.any() and config.allow_weight_return_derived_contribution:
        frame.loc[derived, "gross_contribution"] = frame.loc[derived, "portfolio_weight"] * frame.loc[derived, "security_return"]
        costs = frame.loc[derived, "cost_contribution"].fillna(0.0)
        frame.loc[derived, "net_contribution"] = frame.loc[derived, "gross_contribution"] + costs
        frame.loc[derived, "contribution_source"] = "EXPLICITLY_AUTHORIZED_WEIGHT_TIMES_RETURN"
    if frame.net_contribution.isna().any():
        indexes = frame.index[frame.net_contribution.isna()].tolist()[:10]
        raise AttributionInputError(f"net contribution unavailable for rows: {indexes}")
    frame["contribution_source"] = frame["contribution_source"].fillna("AUTHORITATIVE_NET_CONTRIBUTION")
    frame["rank_bucket"] = [
        config.rank_bucket(None if pd.isna(rank) else float(rank), component)
        for rank, component in zip(frame["rank"], frame["component_type"])
    ]
    frame["year"] = frame.date.dt.year.astype(str)
    frame["quarter"] = frame.date.dt.to_period("Q").astype(str)
    frame["month"] = frame.date.dt.to_period("M").astype(str)
    return frame.sort_values(["date", "component_type", "security_id"], kind="mergesort").reset_index(drop=True)


def normalize_daily(daily: pd.DataFrame | Iterable[dict[str, Any]]) -> pd.DataFrame:
    frame = _frame(daily)
    required = {"strategy_id", "date", "authoritative_portfolio_return"}
    missing = required - set(frame)
    if missing:
        raise AttributionInputError(f"missing daily fields: {sorted(missing)}")
    for column in DAILY_NUMERIC_COLUMNS:
        if column not in frame:
            frame[column] = np.nan
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    if frame.date.isna().any() or frame[["strategy_id", "date"]].duplicated().any():
        raise AttributionInputError("daily dates must be valid and unique per strategy")
    _finite_numeric(frame, DAILY_NUMERIC_COLUMNS)
    if frame.authoritative_portfolio_return.isna().any():
        raise AttributionInputError("authoritative portfolio return is required on every date")
    return frame.sort_values("date", kind="mergesort").reset_index(drop=True)


def _sum_min(values: pd.Series) -> float:
    return float(values.sum(min_count=1))


def reconcile_daily(rows: pd.DataFrame, daily: pd.DataFrame, tolerance: float) -> dict[str, Any]:
    if set(rows.strategy_id.unique()) != set(daily.strategy_id.unique()):
        identity_reason = ["strategy_identity_mismatch"]
    else:
        identity_reason = []
    grouped = rows.groupby("date", as_index=False).agg(
        sum_gross_contribution=("gross_contribution", _sum_min),
        sum_cost_contribution=("cost_contribution", _sum_min),
        sum_net_contribution=("net_contribution", _sum_min),
    )
    checks = daily.merge(grouped, on="date", how="outer", indicator=True, validate="one_to_one")
    checks["identity_error"] = checks.sum_net_contribution - checks.authoritative_portfolio_return
    checks["gross_identity_error"] = checks.sum_gross_contribution - checks.authoritative_gross_return
    checks["cost_identity_error"] = checks.sum_cost_contribution - checks.authoritative_cost_contribution
    both = rows[["gross_contribution", "cost_contribution", "net_contribution"]].notna().all(axis=1)
    row_component_error = (
        rows.loc[both, "net_contribution"]
        - rows.loc[both, "gross_contribution"]
        - rows.loc[both, "cost_contribution"]
    )
    if not checks._merge.eq("both").all():
        identity_reason.append("missing_row_or_authoritative_date")
    if checks.identity_error.isna().any():
        identity_reason.append("net_contribution_not_reconciled")
    if (checks.authoritative_gross_return.notna() & checks.sum_gross_contribution.isna()).any():
        identity_reason.append("gross_contribution_not_reconciled")
    if (checks.authoritative_cost_contribution.notna() & checks.sum_cost_contribution.isna()).any():
        identity_reason.append("cost_contribution_not_reconciled")
    max_error = float(checks.identity_error.abs().max()) if checks.identity_error.notna().any() else math.inf
    max_component_error = float(row_component_error.abs().max()) if len(row_component_error) else 0.0
    gross_available = checks.authoritative_gross_return.notna() & checks.sum_gross_contribution.notna()
    cost_available = checks.authoritative_cost_contribution.notna() & checks.sum_cost_contribution.notna()
    max_gross_error = float(checks.loc[gross_available, "gross_identity_error"].abs().max()) if gross_available.any() else None
    max_cost_error = float(checks.loc[cost_available, "cost_identity_error"].abs().max()) if cost_available.any() else None
    charge_rows = rows.transaction_cost.notna() & rows.cost_contribution.notna()
    charge_error = rows.loc[charge_rows, "cost_contribution"] + rows.loc[charge_rows, "transaction_cost"].abs()
    max_charge_error = float(charge_error.abs().max()) if charge_rows.any() else None
    if max_error > tolerance:
        identity_reason.append("daily_net_identity_tolerance_exceeded")
    if max_component_error > tolerance:
        identity_reason.append("row_gross_cost_net_identity_tolerance_exceeded")
    if max_gross_error is not None and max_gross_error > tolerance:
        identity_reason.append("daily_gross_identity_tolerance_exceeded")
    if max_cost_error is not None and max_cost_error > tolerance:
        identity_reason.append("daily_cost_identity_tolerance_exceeded")
    if max_charge_error is not None and max_charge_error > tolerance:
        identity_reason.append("transaction_cost_contribution_identity_tolerance_exceeded")
    nav_rows = checks.nav_before.notna() & checks.nav_after.notna()
    checks["nav_return_error"] = np.nan
    checks.loc[nav_rows, "nav_return_error"] = (
        checks.loc[nav_rows, "nav_after"] / checks.loc[nav_rows, "nav_before"] - 1.0
        - checks.loc[nav_rows, "authoritative_portfolio_return"]
    )
    max_nav_error = float(checks.loc[nav_rows, "nav_return_error"].abs().max()) if nav_rows.any() else None
    if max_nav_error is not None and max_nav_error > tolerance:
        identity_reason.append("nav_return_identity_tolerance_exceeded")
    checks = checks.drop(columns="_merge")
    return {
        "status": "PASS" if not identity_reason else "FAIL",
        "tolerance": tolerance,
        "max_daily_identity_error": max_error,
        "total_identity_error": float(checks.sum_net_contribution.sum() - checks.authoritative_portfolio_return.sum()),
        "max_row_component_identity_error": max_component_error,
        "max_daily_gross_identity_error": max_gross_error,
        "max_daily_cost_identity_error": max_cost_error,
        "max_transaction_cost_contribution_identity_error": max_charge_error,
        "max_nav_return_identity_error": max_nav_error,
        "reasons": sorted(set(identity_reason)),
        "daily": checks,
    }


def _shares(values: pd.Series, positive: bool) -> pd.Series:
    mass = values.clip(lower=0) if positive else (-values.clip(upper=0))
    total = float(mass.sum())
    return mass / total if total > 0 else pd.Series(0.0, index=values.index)


def concentration_metrics(values: pd.Series, prefix: str) -> dict[str, Any]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    positive = clean.clip(lower=0)
    negative = -clean.clip(upper=0)

    def metrics(mass: pd.Series, sign: str) -> dict[str, Any]:
        total = float(mass.sum())
        shares = (mass[mass > 0] / total).sort_values(ascending=False) if total > 0 else pd.Series(dtype=float)
        hhi = float((shares**2).sum()) if len(shares) else None
        result = {
            f"{prefix}_{sign}_mass": total,
            f"{prefix}_{sign}_hhi": hhi,
            f"{prefix}_effective_{sign}_contributor_count": (1.0 / hhi) if hhi and hhi > 0 else None,
        }
        for n in (1, 2, 3, 5, 10):
            result[f"top_{n}_{prefix}_{sign}_contribution_share"] = float(shares.head(n).sum()) if len(shares) else None
        return result

    return {**metrics(positive, "positive"), **metrics(negative, "negative")}


def security_attribution(rows: pd.DataFrame) -> pd.DataFrame:
    security = rows.loc[rows.component_type.eq("SECURITY")].copy()
    if security.empty:
        return pd.DataFrame()
    security["entry"] = (
        security.portfolio_weight.notna() & security.previous_weight.notna()
        & security.portfolio_weight.gt(0) & security.previous_weight.le(0)
    ).astype(int)
    grouped = security.groupby(["security_id", "ticker"], as_index=False, dropna=False).agg(
        gross_contribution=("gross_contribution", _sum_min),
        net_contribution=("net_contribution", _sum_min),
        cost_contribution=("cost_contribution", _sum_min),
        turnover_contribution=("turnover_contribution", _sum_min),
        number_of_holding_days=("date", "nunique"), number_of_entries=("entry", "sum"),
        average_weight=("portfolio_weight", "mean"), max_weight=("portfolio_weight", "max"),
        positive_contribution_days=("net_contribution", lambda values: int((values > 0).sum())),
        negative_contribution_days=("net_contribution", lambda values: int((values < 0).sum())),
        entry_metadata_complete=("previous_weight", lambda values: bool(values.notna().all())),
    )
    grouped.loc[~grouped.entry_metadata_complete, "number_of_entries"] = np.nan
    positive_shares = _shares(grouped.net_contribution, True)
    negative_shares = _shares(grouped.net_contribution, False)
    grouped["share_of_total_positive_contribution"] = positive_shares
    grouped["share_of_total_negative_contribution"] = negative_shares
    return grouped.sort_values(["net_contribution", "security_id"], ascending=[False, True], kind="mergesort").reset_index(drop=True)


def dimension_attribution(rows: pd.DataFrame, dimension: str) -> pd.DataFrame:
    frame = rows.copy()
    if dimension not in frame:
        raise AttributionInputError(f"dimension unavailable: {dimension}")
    frame[dimension] = frame[dimension].fillna("UNKNOWN").astype(str)
    exposure = frame.groupby(["date", dimension], as_index=False, dropna=False).portfolio_weight.sum(min_count=1)
    exposure = exposure.groupby(dimension, as_index=False).portfolio_weight.mean().rename(
        columns={"portfolio_weight": "average_exposure"}
    )
    grouped = frame.groupby(dimension, as_index=False, dropna=False).agg(
        gross_contribution=("gross_contribution", _sum_min),
        net_contribution=("net_contribution", _sum_min),
        cost_contribution=("cost_contribution", _sum_min),
        turnover_contribution=("turnover_contribution", _sum_min),
        positive_contribution=("net_contribution", lambda values: float(values.clip(lower=0).sum())),
        negative_contribution=("net_contribution", lambda values: float(values.clip(upper=0).sum())),
        average_weight=("portfolio_weight", "mean"), holding_count=("security_id", "count"),
    )
    total = float(grouped.net_contribution.sum())
    grouped["contribution_share"] = grouped.net_contribution / total if total != 0 else np.nan
    grouped = grouped.merge(exposure, on=dimension, how="left", validate="one_to_one")
    return grouped.sort_values(["net_contribution", dimension], ascending=[False, True], kind="mergesort").reset_index(drop=True)


def time_attribution(rows: pd.DataFrame, period: str) -> pd.DataFrame:
    grouped = dimension_attribution(rows, period).rename(columns={period: "period"})
    grouped["positive_period"] = grouped.net_contribution > 0
    grouped["negative_period"] = grouped.net_contribution < 0
    positive_total = float(grouped.net_contribution.clip(lower=0).sum())
    grouped["share_of_total_positive_period_contribution"] = (
        grouped.net_contribution.clip(lower=0) / positive_total if positive_total > 0 else np.nan
    )
    return grouped


def winner_loser_attribution(security: pd.DataFrame, threshold: float) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = security.copy()
    frame["winner_loser_class"] = np.where(
        frame.net_contribution > threshold, "WINNER",
        np.where(frame.net_contribution < -threshold, "LOSER", "FLAT"),
    )
    summary = frame.groupby("winner_loser_class", as_index=False).agg(
        security_count=("security_id", "count"), total_contribution=("net_contribution", "sum"),
        average_contribution=("net_contribution", "mean"),
    )
    by_class = summary.set_index("winner_loser_class") if len(summary) else pd.DataFrame()
    winner_total = float(by_class.at["WINNER", "total_contribution"]) if "WINNER" in by_class.index else 0.0
    loser_total = float(by_class.at["LOSER", "total_contribution"]) if "LOSER" in by_class.index else 0.0
    return frame, {
        "winner_count": int(by_class.at["WINNER", "security_count"]) if "WINNER" in by_class.index else 0,
        "loser_count": int(by_class.at["LOSER", "security_count"]) if "LOSER" in by_class.index else 0,
        "winner_total_contribution": winner_total, "loser_total_contribution": loser_total,
        "winner_average_contribution": float(by_class.at["WINNER", "average_contribution"]) if "WINNER" in by_class.index else None,
        "loser_average_contribution": float(by_class.at["LOSER", "average_contribution"]) if "LOSER" in by_class.index else None,
        "winner_contribution_share": (
            winner_total / (winner_total + abs(loser_total))
            if winner_total + abs(loser_total) > 0 else None
        ),
        "classification_threshold": threshold,
        "threshold_interpretation": "ARITHMETIC_SIGN_ONLY" if threshold == 0 else "CALLER_CONFIGURED",
    }


class AttributionEngine:
    def __init__(self, config: AttributionConfig | None = None):
        self.config = config or AttributionConfig()
        self.config.validate()

    def run(self, rows: pd.DataFrame | Iterable[dict[str, Any]], daily: pd.DataFrame | Iterable[dict[str, Any]]) -> dict[str, Any]:
        normalized = normalize_rows(rows, self.config)
        normalized_daily = normalize_daily(daily)
        if normalized.strategy_id.nunique() != 1 or normalized_daily.strategy_id.nunique() != 1:
            raise AttributionInputError("single-strategy attribution requires exactly one strategy")
        reconciliation = reconcile_daily(normalized, normalized_daily, self.config.identity_tolerance)
        security = security_attribution(normalized)
        rank_bucket = dimension_attribution(normalized, "rank_bucket")
        sector = dimension_attribution(normalized, "sector")
        industry = dimension_attribution(normalized, "industry")
        times = {period: time_attribution(normalized, period) for period in ("year", "quarter", "month")}
        for optional in ("fold", "regime"):
            if normalized[optional].notna().any():
                times[optional] = time_attribution(normalized, optional)
        classified, winner_loser = winner_loser_attribution(security, self.config.winner_loser_threshold)
        concentration = concentration_metrics(security.set_index("security_id").net_contribution, "security")
        year_values = times["year"].set_index("period").net_contribution
        concentration.update(concentration_metrics(year_values, "period"))
        concentration["best_year_positive_contribution_share"] = concentration["top_1_period_positive_contribution_share"]
        concentration["top_2_year_positive_contribution_share"] = concentration["top_2_period_positive_contribution_share"]
        concentration["top_3_period_positive_contribution_share"] = concentration["top_3_period_positive_contribution_share"]
        concentration["status"] = self.config.concentration_status
        episodes = detect_drawdown_episodes(normalized_daily)
        drawdown = drawdown_window_diagnostics(normalized, episodes, self.config)

        total_gross_raw = _sum_min(normalized.gross_contribution)
        total_cost_raw = _sum_min(normalized.cost_contribution)
        total_gross = None if pd.isna(total_gross_raw) else total_gross_raw
        total_cost = None if pd.isna(total_cost_raw) else total_cost_raw
        total_net = float(normalized.net_contribution.sum())
        best_year = times["year"].iloc[0].period if len(times["year"]) else None
        worst_year = times["year"].iloc[-1].period if len(times["year"]) else None
        bucket_map = dict(zip(rank_bucket.rank_bucket, rank_bucket.net_contribution))
        summary = {
            "framework": "A2_ATTRIBUTION_FRAMEWORK_R1", "schema_version": "1.0.0",
            "strategy_id": normalized.strategy_id.iloc[0],
            "model_id": normalized.model_id.iloc[0] if normalized.model_id.nunique() == 1 else normalized.model_id.unique().tolist(),
            "date_start": normalized.date.min().date().isoformat(), "date_end": normalized.date.max().date().isoformat(),
            "input_rows": len(normalized), "security_count": int(normalized.loc[normalized.component_type.eq("SECURITY"), "security_id"].nunique()),
            "trading_days": int(normalized.date.nunique()), "attribution_identity_status": reconciliation["status"],
            "max_daily_identity_error": reconciliation["max_daily_identity_error"],
            "total_identity_error": reconciliation["total_identity_error"],
            "total_gross_contribution": total_gross, "total_cost": total_cost, "total_net_contribution": total_net,
            "top_security_contributors": security.head(5)[["security_id", "net_contribution"]].to_dict("records"),
            "bottom_security_contributors": security.tail(5)[["security_id", "net_contribution"]].sort_values("net_contribution").to_dict("records"),
            "top_5_security_positive_share": concentration["top_5_security_positive_contribution_share"],
            "top_10_security_positive_share": concentration["top_10_security_positive_contribution_share"],
            "effective_positive_contributor_count": concentration["security_effective_positive_contributor_count"],
            "best_year": best_year, "worst_year": worst_year,
            "best_year_positive_share": concentration["best_year_positive_contribution_share"],
            "rank_1_5_contribution": bucket_map.get("RANK_1_5"),
            "rank_6_10_contribution": bucket_map.get("RANK_6_10"),
            "rank_11_20_contribution": bucket_map.get("RANK_11_20"),
            "sector_concentration_status": self.config.concentration_status,
            "drawdown_episode_count": len(episodes),
            "worst_drawdown_window": min(episodes, key=lambda item: item["drawdown_magnitude"], default=None),
            "a_vs_a2_incremental_status": "NOT_EVALUATED_BY_SINGLE_STRATEGY_ENGINE",
            "full_history_executed": False, "model_training_executed": False, "live_research_touched": False,
            "research_governance_version": "R1", "model_registry_reference": "config/research_governance/alpha_registry.json",
        }
        return {
            "summary": summary, "normalized_rows": normalized, "daily": normalized_daily,
            "security_attribution": classified, "time_attribution": times,
            "rank_bucket_attribution": rank_bucket, "sector_attribution": sector,
            "industry_attribution": industry, "winner_loser_summary": winner_loser,
            "concentration": concentration, "drawdown_episodes": episodes,
            "drawdown_window_attribution": drawdown, "reconciliation": reconciliation,
        }
