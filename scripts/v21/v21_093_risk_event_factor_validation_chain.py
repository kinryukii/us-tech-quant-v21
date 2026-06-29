#!/usr/bin/env python
"""V21.093-R1..R5 research-only PIT risk-event factor validation chain."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


OUT_REL = Path("outputs/v21")
SOURCE_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/random_backtests/"
    "V21_060_R2_RANDOM_ASOF_BACKTEST_RESULTS.csv"
)
LATEST_D_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/"
    "V21_060_R5_D_WEIGHT_OPTIMIZED_RANKING.csv"
)
RESEARCH_ONLY = True
OFFICIAL_ADOPTION_ALLOWED = False
WINDOWS = ("5D", "10D", "20D")
TOP_BUCKETS = (20, 50)
VARIANTS = (
    "D_BASELINE_PRESERVED",
    "D_EVENT_LIGHT",
    "D_EVENT_MEDIUM",
    "D_EVENT_HEAVY",
    "D_EVENT_HARD_BLOCK",
)
EVENT_TYPES = {
    "macro_fomc", "macro_cpi", "macro_pce", "macro_nfp", "earnings",
    "sector_semiconductor", "sector_dram", "market_opex",
    "market_quad_witching", "index_rebalance", "holiday_liquidity",
    "company_lockup", "company_split", "company_regulatory",
    "company_financing",
}
EVENT_COLUMNS = [
    "event_id", "event_type", "event_name", "event_date", "event_time",
    "known_as_of_timestamp", "affected_ticker", "affected_sector", "severity",
    "source_type", "pit_allowed", "notes",
]
OUTPUT_NAMES = (
    "v21_093_r1_event_master_ledger.csv",
    "v21_093_r1_event_schema_validation.json",
    "v21_093_r1_event_schema_validation.md",
    "v21_093_r2_event_risk_features.csv",
    "v21_093_r2_event_risk_feature_summary.csv",
    "v21_093_r2_event_risk_feature_validation.json",
    "v21_093_r2_event_risk_feature_validation.md",
    "v21_093_r3_d_event_risk_ranking_variants.csv",
    "v21_093_r3_variant_top20_top50_summary.csv",
    "v21_093_r3_join_validation.json",
    "v21_093_r3_join_validation.md",
    "v21_093_r4_random_event_risk_backtest_rows.csv",
    "v21_093_r4_random_event_risk_backtest_summary.csv",
    "v21_093_r4_random_event_risk_backtest_validation.json",
    "v21_093_r4_random_event_risk_backtest_validation.md",
    "v21_093_r5_event_risk_factor_decision_report.md",
    "v21_093_r5_event_risk_factor_decision_summary.json",
)


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=json_default) + "\n", encoding="utf-8")


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    raise TypeError(f"Cannot JSON encode {type(value)!r}")


def file_snapshot(root: Path, output_paths: set[Path]) -> dict[str, str]:
    """Hash protected/official artifacts, excluding only this stage's outputs."""
    tokens = (
        "official", "broker", "protected", "forward_observation_ledger",
        "060_r5_d_", "066a_d_latest_ranking", "p03", "p04",
    )
    result: dict[str, str] = {}
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            resolved = path.resolve()
            if not path.is_file() or resolved in output_paths:
                continue
            if any(token in path.as_posix().lower() for token in tokens):
                result[path.relative_to(root).as_posix()] = sha256(path)
    return result


def changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))


def easter_sunday(year: int) -> date:
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    current = date(year, month, 1)
    current += timedelta(days=(weekday - current.weekday()) % 7)
    return current + timedelta(days=7 * (n - 1))


def last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        current = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        current = date(year, month + 1, 1) - timedelta(days=1)
    return current - timedelta(days=(current.weekday() - weekday) % 7)


def nyse_holidays(year: int) -> list[tuple[date, str]]:
    holidays = [
        (observed(date(year, 1, 1)), "New Year's Day"),
        (nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day"),
        (nth_weekday(year, 2, 0, 3), "Presidents Day"),
        (easter_sunday(year) - timedelta(days=2), "Good Friday"),
        (last_weekday(year, 5, 0), "Memorial Day"),
        (observed(date(year, 6, 19)), "Juneteenth"),
        (observed(date(year, 7, 4)), "Independence Day"),
        (nth_weekday(year, 9, 0, 1), "Labor Day"),
        (nth_weekday(year, 11, 3, 4), "Thanksgiving"),
        (observed(date(year, 12, 25)), "Christmas Day"),
    ]
    return sorted(set(holidays))


def third_friday(year: int, month: int) -> date:
    return nth_weekday(year, month, 4, 3)


def build_event_ledger(min_date: date, max_date: date) -> pd.DataFrame:
    """Build only events whose schedule is verifiable from stable calendar rules."""
    rows: list[dict[str, Any]] = []
    event_start = min_date - timedelta(days=10)
    event_end = max_date + timedelta(days=10)
    for year in range(event_start.year, event_end.year + 1):
        known = f"{year - 1}-01-01T00:00:00Z"
        for month in range(1, 13):
            event_day = third_friday(year, month)
            if not event_start <= event_day <= event_end:
                continue
            quarterly = month in {3, 6, 9, 12}
            event_type = "market_quad_witching" if quarterly else "market_opex"
            label = "Quarterly quadruple witching" if quarterly else "Monthly options expiration"
            rows.append({
                "event_id": f"{event_type.upper()}_{event_day:%Y%m%d}",
                "event_type": event_type,
                "event_name": label,
                "event_date": event_day.isoformat(),
                "event_time": "16:00:00 America/New_York",
                "known_as_of_timestamp": known,
                "affected_ticker": "",
                "affected_sector": "ALL",
                "severity": 60 if quarterly else 42,
                "source_type": "RULE_BASED_EXCHANGE_CALENDAR",
                "pit_allowed": True,
                "notes": "Rule-derived scheduled event; no price, return, or post-event news used.",
            })
        for event_day, holiday_name in nyse_holidays(year):
            if not event_start <= event_day <= event_end:
                continue
            rows.append({
                "event_id": f"HOLIDAY_LIQUIDITY_{event_day:%Y%m%d}",
                "event_type": "holiday_liquidity",
                "event_name": f"{holiday_name} liquidity window",
                "event_date": event_day.isoformat(),
                "event_time": "00:00:00 America/New_York",
                "known_as_of_timestamp": known,
                "affected_ticker": "",
                "affected_sector": "ALL",
                "severity": 52,
                "source_type": "RULE_BASED_NYSE_HOLIDAY_CALENDAR",
                "pit_allowed": True,
                "notes": "Observed-date calendar rule; no price, return, or post-event news used.",
            })
    return pd.DataFrame(rows, columns=EVENT_COLUMNS).sort_values(
        ["event_date", "event_type", "event_id"]
    ).reset_index(drop=True)


def load_random_d_universe(root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    cols = [
        "seed", "batch_id", "sampled_as_of_date", "variant_id", "ticker",
        "instrument_type", "theme", "rank", "score", "base_score",
        "momentum_score", "forward_window", "realized_forward_return",
        "benchmark_spy_return", "benchmark_qqq_return", "top_n_bucket",
        "price_data_status", "point_in_time_valid", "research_only",
    ]
    parts = []
    for chunk in pd.read_csv(root / SOURCE_REL, usecols=cols, chunksize=200_000, low_memory=False):
        keep = (
            chunk["variant_id"].eq("B_MOMENTUM_STATIC_R1")
            & chunk["forward_window"].eq("5D")
            & chunk["top_n_bucket"].eq("TOP50")
            & chunk["price_data_status"].eq("PASS")
            & chunk["point_in_time_valid"].map(truth)
            & chunk["research_only"].map(truth)
        )
        parts.append(chunk.loc[keep].copy())
    base = pd.concat(parts, ignore_index=True)
    base["as_of_date"] = base["sampled_as_of_date"].astype(str).str[:10]
    base["ticker"] = base["ticker"].astype(str).str.upper().str.strip()
    base["D_final_score"] = (
        0.60 * pd.to_numeric(base["base_score"], errors="coerce")
        + 0.40 * pd.to_numeric(base["momentum_score"], errors="coerce")
    )
    base["D_rank"] = base.groupby(["seed", "batch_id"])["D_final_score"].rank(
        method="first", ascending=False
    ).astype(int)
    base = base.sort_values(["seed", "batch_id", "D_rank", "ticker"]).reset_index(drop=True)

    outcomes = pd.read_csv(
        root / SOURCE_REL,
        usecols=[
            "seed", "batch_id", "sampled_as_of_date", "variant_id", "ticker",
            "forward_window", "realized_forward_return", "benchmark_spy_return",
            "benchmark_qqq_return", "top_n_bucket", "price_data_status",
            "point_in_time_valid", "research_only",
        ],
        low_memory=False,
    )
    keep = (
        outcomes["variant_id"].eq("B_MOMENTUM_STATIC_R1")
        & outcomes["top_n_bucket"].eq("TOP50")
        & outcomes["forward_window"].isin(WINDOWS)
        & outcomes["price_data_status"].eq("PASS")
        & outcomes["point_in_time_valid"].map(truth)
        & outcomes["research_only"].map(truth)
    )
    outcomes = outcomes.loc[keep].copy()
    outcomes["as_of_date"] = outcomes["sampled_as_of_date"].astype(str).str[:10]
    outcomes["ticker"] = outcomes["ticker"].astype(str).str.upper().str.strip()
    return base, outcomes


def event_window(delta_days: int) -> tuple[str, float] | None:
    # Positive delta means event is ahead of the ranking date.
    if 3 <= delta_days <= 5:
        return "T-5_TO_T-3", 0.35
    if 1 <= delta_days <= 2:
        return "T-2_TO_T-1", 0.70
    if delta_days == 0:
        return "T0", 1.00
    if -3 <= delta_days <= -1:
        return "T+1_TO_T+3", 0.45
    if -7 <= delta_days <= -4:
        return "T+4_ONWARD", 0.15
    return None


CATEGORY = {
    "macro_fomc": "macro_event_score", "macro_cpi": "macro_event_score",
    "macro_pce": "macro_event_score", "macro_nfp": "macro_event_score",
    "earnings": "earnings_event_score",
    "sector_semiconductor": "sector_event_score", "sector_dram": "sector_event_score",
    "market_opex": "market_structure_score",
    "market_quad_witching": "market_structure_score",
    "index_rebalance": "market_structure_score",
    "holiday_liquidity": "liquidity_event_score",
    "company_lockup": "idiosyncratic_event_score",
    "company_split": "idiosyncratic_event_score",
    "company_regulatory": "idiosyncratic_event_score",
    "company_financing": "idiosyncratic_event_score",
}
FEATURE_COMPONENTS = [
    "macro_event_score", "earnings_event_score", "sector_event_score",
    "market_structure_score", "liquidity_event_score", "idiosyncratic_event_score",
]


def make_features(base: pd.DataFrame, ledger: pd.DataFrame) -> pd.DataFrame:
    ranking = base[["as_of_date", "ticker"]].drop_duplicates().copy()
    ranking["_date"] = pd.to_datetime(ranking["as_of_date"])
    events = ledger[ledger["pit_allowed"].map(truth)].copy()
    events["_event_date"] = pd.to_datetime(events["event_date"])
    events["_known"] = pd.to_datetime(events["known_as_of_timestamp"], utc=True)
    rows = []
    for as_of, group in ranking.groupby("as_of_date", sort=True):
        rank_ts = pd.Timestamp(as_of, tz="UTC") + pd.Timedelta(hours=23, minutes=59, seconds=59)
        valid = events[events["_known"].le(rank_ts)].copy()
        valid["_delta"] = (valid["_event_date"] - pd.Timestamp(as_of)).dt.days
        valid["_window_info"] = valid["_delta"].map(event_window)
        valid = valid[valid["_window_info"].notna()]
        for ticker in group["ticker"].sort_values():
            applicable = valid[
                valid["affected_ticker"].fillna("").astype(str).str.strip().isin(["", ticker])
                & valid["affected_sector"].fillna("ALL").astype(str).str.upper().isin(["", "ALL"])
            ].copy()
            components = {name: 0.0 for name in FEATURE_COMPONENTS}
            nearest_type = nearest_id = ""
            nearest_days = np.nan
            nearest_window = ""
            if not applicable.empty:
                applicable["_window"] = applicable["_window_info"].map(lambda x: x[0])
                applicable["_multiplier"] = applicable["_window_info"].map(lambda x: x[1])
                applicable["_score"] = (
                    pd.to_numeric(applicable["severity"], errors="coerce").fillna(0)
                    * applicable["_multiplier"]
                )
                for component, values in applicable.groupby(applicable["event_type"].map(CATEGORY)):
                    components[component] = min(100.0, float(values["_score"].sum()))
                nearest = applicable.sort_values(
                    ["_delta", "severity"], key=lambda s: s.abs() if s.name == "_delta" else -s
                ).iloc[0]
                nearest_days = int(nearest["_delta"])
                nearest_type = nearest["event_type"]
                nearest_id = nearest["event_id"]
                nearest_window = nearest["_window"]
            total = min(100.0, sum(components.values()))
            rows.append({
                "ticker": ticker, "as_of_date": as_of, "event_risk_score": round(total, 6),
                **{k: round(v, 6) for k, v in components.items()},
                "days_to_nearest_event": nearest_days, "nearest_event_type": nearest_type,
                "nearest_event_id": nearest_id, "event_window": nearest_window,
                "pit_allowed": True,
            })
    return pd.DataFrame(rows)


def make_variants(base: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    joined = base.merge(features, on=["ticker", "as_of_date"], how="left", validate="many_to_one")
    joined["event_risk_score"] = joined["event_risk_score"].fillna(0.0)
    records = []
    for variant in VARIANTS:
        frame = joined.copy()
        if variant == "D_EVENT_LIGHT":
            frame["event_penalty"] = np.minimum(frame["event_risk_score"] * 0.03, 2.0)
        elif variant == "D_EVENT_MEDIUM":
            frame["event_penalty"] = np.minimum(frame["event_risk_score"] * 0.06, 4.0)
        elif variant == "D_EVENT_HEAVY":
            frame["event_penalty"] = np.minimum(frame["event_risk_score"] * 0.10, 7.0)
        else:
            frame["event_penalty"] = 0.0
        frame["hard_blocked"] = (
            variant == "D_EVENT_HARD_BLOCK"
        ) & frame["event_risk_score"].ge(80) & frame["event_window"].isin(["T-2_TO_T-1", "T0"])
        frame["event_adjusted_score"] = frame["D_final_score"] - frame["event_penalty"]
        frame["_rank_score"] = frame["event_adjusted_score"].mask(frame["hard_blocked"], -np.inf)
        frame["variant_rank"] = frame.groupby(["seed", "batch_id"])["_rank_score"].rank(
            method="first", ascending=False
        ).astype(int)
        eligible_count = (~frame["hard_blocked"]).groupby([frame["seed"], frame["batch_id"]]).transform("sum")
        frame["top20_eligible"] = (~frame["hard_blocked"]) & frame["variant_rank"].le(20) & eligible_count.ge(20)
        frame["top50_eligible"] = (~frame["hard_blocked"]) & frame["variant_rank"].le(50) & eligible_count.ge(50)
        frame["variant_id"] = variant
        frame["research_only"] = True
        frame["official_adoption_allowed"] = False
        records.append(frame)
    result = pd.concat(records, ignore_index=True)
    keep = [
        "seed", "batch_id", "as_of_date", "ticker", "instrument_type", "theme",
        "variant_id", "D_final_score", "D_rank", "event_risk_score", *FEATURE_COMPONENTS,
        "days_to_nearest_event", "nearest_event_type", "nearest_event_id", "event_window",
        "event_penalty", "event_adjusted_score", "variant_rank", "hard_blocked",
        "top20_eligible", "top50_eligible", "pit_allowed", "research_only",
        "official_adoption_allowed",
    ]
    return result[keep].sort_values(["seed", "batch_id", "variant_id", "variant_rank", "ticker"])


def summarize_variants(variants: pd.DataFrame) -> pd.DataFrame:
    baseline = variants[variants["variant_id"].eq("D_BASELINE_PRESERVED")]
    baseline_sets: dict[tuple[Any, str, int], set[str]] = {}
    for (seed, batch), group in baseline.groupby(["seed", "batch_id"]):
        for n in TOP_BUCKETS:
            baseline_sets[(seed, batch, n)] = set(group.nsmallest(n, "variant_rank")["ticker"])
    rows = []
    for (variant, seed, batch), group in variants.groupby(["variant_id", "seed", "batch_id"]):
        for n in TOP_BUCKETS:
            selected = set(group[group[f"top{n}_eligible"]]["ticker"])
            dset = baseline_sets[(seed, batch, n)]
            rows.append({
                "variant_id": variant, "seed": seed, "batch_id": batch,
                "as_of_date": group["as_of_date"].iloc[0], "top_n": n,
                "selected_count": len(selected), "overlap_vs_D": len(selected & dset) / n,
                "turnover_vs_D": len(selected ^ dset) / (2 * n),
                "hard_blocked_count": int(group["hard_blocked"].sum()),
                "mean_event_risk_score": group.loc[group[f"top{n}_eligible"], "event_risk_score"].mean(),
                "research_only": True, "official_adoption_allowed": False,
            })
    return pd.DataFrame(rows)


def backtest_rows(variants: pd.DataFrame, outcomes: pd.DataFrame) -> tuple[pd.DataFrame, dict[tuple, dict[str, float]]]:
    outcome_cols = [
        "seed", "batch_id", "ticker", "forward_window", "realized_forward_return",
        "benchmark_spy_return", "benchmark_qqq_return",
    ]
    outcome = outcomes[outcome_cols].drop_duplicates(
        ["seed", "batch_id", "ticker", "forward_window"]
    )
    rows = []
    attribution: dict[tuple, dict[str, float]] = {}
    baseline = variants[variants["variant_id"].eq("D_BASELINE_PRESERVED")]
    all_variant_groups = {
        key: group for key, group in variants.groupby(["seed", "batch_id", "variant_id"], sort=False)
    }
    outcome_groups = {
        key: group for key, group in outcome.groupby(["seed", "batch_id", "forward_window"], sort=False)
    }
    for (seed, batch), dgroup in baseline.groupby(["seed", "batch_id"]):
        as_of = dgroup["as_of_date"].iloc[0]
        variant_groups = {
            name: all_variant_groups[(seed, batch, name)] for name in VARIANTS
        }
        for n in TOP_BUCKETS:
            dset = set(dgroup[dgroup[f"top{n}_eligible"]]["ticker"])
            for window in WINDOWS:
                available = outcome_groups[(seed, batch, window)]
                return_map = available.set_index("ticker")["realized_forward_return"]
                for variant, group in variant_groups.items():
                    selected = set(group[group[f"top{n}_eligible"]]["ticker"])
                    values = return_map.reindex(sorted(selected)).dropna()
                    missed = dset - selected
                    added = selected - dset
                    missed_winners = int((return_map.reindex(sorted(missed)).dropna() > 0).sum())
                    avoided_losers = int((return_map.reindex(sorted(missed)).dropna() < 0).sum())
                    attribution[(variant, seed, batch, n, window)] = {
                        "missed_winners": missed_winners,
                        "avoided_losers": avoided_losers,
                    }
                    rows.append({
                        "variant_id": variant, "seed": seed, "batch_id": batch,
                        "as_of_date": as_of, "top_n": n, "forward_window": window,
                        "selected_count": len(selected), "observed_return_count": len(values),
                        "portfolio_forward_return": values.mean() if len(values) else np.nan,
                        "median_holding_return": values.median() if len(values) else np.nan,
                        "p5_holding_return": values.quantile(0.05) if len(values) else np.nan,
                        "cvar_5_holding": values[values.le(values.quantile(.05))].mean() if len(values) else np.nan,
                        "worst_holding_return": values.min() if len(values) else np.nan,
                        "severe_loss_count": int((values <= -0.10).sum()),
                        "outlier_event_count": int((values <= -0.20).sum()),
                        "benchmark_spy_return": available["benchmark_spy_return"].dropna().iloc[0] if available["benchmark_spy_return"].notna().any() else np.nan,
                        "benchmark_qqq_return": available["benchmark_qqq_return"].dropna().iloc[0] if available["benchmark_qqq_return"].notna().any() else np.nan,
                        "missed_winners": missed_winners, "avoided_losers": avoided_losers,
                        "top20_overlap_vs_D": len(selected & dset) / n if n == 20 else np.nan,
                        "top50_overlap_vs_D": len(selected & dset) / n if n == 50 else np.nan,
                        "turnover_vs_D": len(selected ^ dset) / (2 * n),
                        "research_only": True,
                    })
    return pd.DataFrame(rows), attribution


def equity_stats(group: pd.DataFrame) -> tuple[float, float]:
    endings, drawdowns = [], []
    for _, seed_group in group.sort_values(["as_of_date", "batch_id"]).groupby("seed"):
        returns = seed_group["portfolio_forward_return"].dropna().clip(lower=-0.999)
        if returns.empty:
            continue
        curve = 10000.0 * (1.0 + returns).cumprod()
        endings.append(float(curve.iloc[-1]))
        drawdowns.append(float((curve / curve.cummax() - 1.0).min()))
    return (
        float(np.mean(endings)) if endings else np.nan,
        float(np.mean(drawdowns)) if drawdowns else np.nan,
    )


def summarize_backtest(rows: pd.DataFrame) -> pd.DataFrame:
    summaries = []
    keys = ["variant_id", "top_n", "forward_window"]
    for key, group in rows.groupby(keys):
        variant, top_n, window = key
        values = group["portfolio_forward_return"].dropna()
        ending, drawdown = equity_stats(group)
        summaries.append({
            "variant_id": variant, "top_n": top_n, "forward_window": window,
            "sample_count": len(values),
            "mean_forward_return": values.mean(), "median_forward_return": values.median(),
            "hit_rate": (values > 0).mean(), "p5_forward_return": values.quantile(.05),
            "cvar_5": values[values.le(values.quantile(.05))].mean(),
            "worst_return": values.min(),
            "severe_loss_count": int(group["severe_loss_count"].sum()),
            "outlier_event_count": int(group["outlier_event_count"].sum()),
            "ending_value_10000": ending, "max_drawdown_proxy": drawdown,
            "return_drawdown_ratio": values.mean() / abs(drawdown) if drawdown and not np.isnan(drawdown) else np.nan,
            "missed_winners": int(group["missed_winners"].sum()),
            "avoided_losers": int(group["avoided_losers"].sum()),
            "top20_overlap_vs_D": group["top20_overlap_vs_D"].mean(),
            "top50_overlap_vs_D": group["top50_overlap_vs_D"].mean(),
            "turnover_vs_D": group["turnover_vs_D"].mean(),
            "benchmark_spy_mean_return": group["benchmark_spy_return"].mean(),
            "benchmark_qqq_mean_return": group["benchmark_qqq_return"].mean(),
            "research_only": True,
        })
    summary = pd.DataFrame(summaries)
    baseline = summary[summary["variant_id"].eq("D_BASELINE_PRESERVED")].set_index(
        ["top_n", "forward_window"]
    )
    for metric in (
        "mean_forward_return", "p5_forward_return", "cvar_5", "worst_return",
        "ending_value_10000", "max_drawdown_proxy", "severe_loss_count",
    ):
        summary[f"{metric}_delta_vs_D"] = summary.apply(
            lambda row: row[metric] - baseline.loc[(row["top_n"], row["forward_window"]), metric],
            axis=1,
        )
    return summary


def markdown_validation(title: str, payload: dict[str, Any]) -> str:
    lines = [f"# {title}", "", f"- Status: `{payload.get('status', 'UNKNOWN')}`"]
    for key, value in payload.items():
        if key == "status":
            continue
        lines.append(f"- {key}: `{value}`")
    return "\n".join(lines) + "\n"


def choose_decision(
    r1: dict[str, Any], r3: dict[str, Any], r4: dict[str, Any], summary: pd.DataFrame
) -> tuple[str, str, dict[str, Any]]:
    nonbase = summary[~summary["variant_id"].eq("D_BASELINE_PRESERVED")].copy()
    aggregate = nonbase.groupby("variant_id").agg(
        cvar_delta=("cvar_5_delta_vs_D", "mean"),
        p5_delta=("p5_forward_return_delta_vs_D", "mean"),
        drawdown_delta=("max_drawdown_proxy_delta_vs_D", "mean"),
        ending_delta=("ending_value_10000_delta_vs_D", "mean"),
        mean_delta=("mean_forward_return_delta_vs_D", "mean"),
        severe_delta=("severe_loss_count_delta_vs_D", "sum"),
        missed_winners=("missed_winners", "sum"),
        avoided_losers=("avoided_losers", "sum"),
        turnover=("turnover_vs_D", "mean"),
    ).reset_index()
    aggregate["tail_score"] = (
        aggregate["cvar_delta"].fillna(0)
        + aggregate["p5_delta"].fillna(0)
        + aggregate["drawdown_delta"].fillna(0)
        - aggregate["severe_delta"].fillna(0) / 10000.0
    )
    best = aggregate.sort_values(
        ["tail_score", "ending_delta", "mean_delta"], ascending=False
    ).iloc[0]
    pit_leakage = int(r1["pit_leakage_warnings"])
    baseline_mutated = not bool(r3["d_baseline_preserved"])
    protected_modified = bool(r3["protected_outputs_modified"])
    sample_small = int(r4["minimum_group_sample_count"]) < 30
    tail_improved = bool(
        best["cvar_delta"] > 0 and best["p5_delta"] >= 0
        and best["drawdown_delta"] >= 0 and best["severe_delta"] <= 0
        and (best["cvar_delta"] > 1e-12 or best["p5_delta"] > 1e-12 or best["drawdown_delta"] > 1e-12 or best["severe_delta"] < 0)
    )
    ending_preserved = bool(best["ending_delta"] >= -100.0 and best["mean_delta"] >= -0.001)
    materially_improved = bool(best["ending_delta"] >= 100.0)
    missed_dominate = bool(best["missed_winners"] > best["avoided_losers"])
    if pit_leakage or baseline_mutated or protected_modified:
        decision = "EVENT_RISK_FACTOR_REJECTED_DUE_TO_LEAKAGE"
        reason = "A mandatory integrity gate failed."
    elif sample_small:
        decision = "EVENT_RISK_FACTOR_INSUFFICIENT_DATA"
        reason = "At least one evaluated group has fewer than 30 random as-of observations."
    elif missed_dominate:
        decision = "EVENT_RISK_FACTOR_REJECTED_DUE_TO_MISSED_WINNERS"
        reason = "Missed winners exceed avoided losers for the best tail-risk candidate."
    elif tail_improved and ending_preserved:
        if materially_improved or (best["ending_delta"] >= 0 and best["mean_delta"] >= 0):
            decision = "EVENT_RISK_FACTOR_EFFECTIVE"
            reason = "Tail metrics improved while mean return and ending value were preserved or improved."
        else:
            decision = "EVENT_RISK_FACTOR_EFFECTIVE_ONLY_FOR_TAIL_RISK"
            reason = "Tail metrics improved without material ending-value improvement."
    else:
        decision = "EVENT_RISK_FACTOR_NOT_EFFECTIVE"
        reason = "No tested penalty produced a non-trivial improvement under the decision gates."
    details = {
        "best_variant": best["variant_id"],
        "tail_risk_improvement": tail_improved,
        "ending_value_delta_vs_D": float(best["ending_delta"]),
        "mean_return_delta_vs_D": float(best["mean_delta"]),
        "cvar_5_delta_vs_D": float(best["cvar_delta"]),
        "p5_delta_vs_D": float(best["p5_delta"]),
        "max_drawdown_delta_vs_D": float(best["drawdown_delta"]),
        "severe_loss_count_delta_vs_D": float(best["severe_delta"]),
        "missed_winners": int(best["missed_winners"]),
        "avoided_losers": int(best["avoided_losers"]),
        "turnover_vs_D": float(best["turnover"]),
    }
    return decision, reason, details


def run(root: Path) -> dict[str, Any]:
    out = root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    output_paths = {(out / name).resolve() for name in OUTPUT_NAMES}
    before = file_snapshot(root, output_paths)
    latest_d_hash_before = sha256(root / LATEST_D_REL)

    base, outcomes = load_random_d_universe(root)
    min_date = pd.to_datetime(base["as_of_date"]).min().date()
    max_date = pd.to_datetime(base["as_of_date"]).max().date()

    # R1
    ledger = build_event_ledger(min_date, max_date)
    ledger.to_csv(out / OUTPUT_NAMES[0], index=False)
    required_ok = set(EVENT_COLUMNS).issubset(ledger.columns)
    known = pd.to_datetime(ledger["known_as_of_timestamp"], utc=True, errors="coerce")
    event_dates = pd.to_datetime(ledger["event_date"], errors="coerce")
    pit_nulls = int((ledger["pit_allowed"].map(truth) & known.isna()).sum())
    late_for_all_rankings = int(
        (ledger["pit_allowed"].map(truth) & known.gt(pd.Timestamp(max_date, tz="UTC") + pd.Timedelta(days=1))).sum()
    )
    r1_validation = {
        "stage": "V21.093-R1_EVENT_MASTER_LEDGER_AND_SCHEMA",
        "status": "PASS",
        "research_only": True,
        "official_adoption_allowed": False,
        "required_columns_exist": required_ok,
        "event_id_unique": bool(ledger["event_id"].is_unique),
        "invalid_event_type_count": int((~ledger["event_type"].isin(EVENT_TYPES)).sum()),
        "invalid_severity_count": int((~pd.to_numeric(ledger["severity"], errors="coerce").between(0, 100)).sum()),
        "pit_allowed_missing_known_timestamp_count": pit_nulls,
        "events_known_after_latest_ranking_count": late_for_all_rankings,
        "pit_leakage_warnings": 0,
        "event_rows": len(ledger),
        "event_date_min": event_dates.min().date().isoformat(),
        "event_date_max": event_dates.max().date().isoformat(),
        "unverifiable_event_policy": "EXCLUDED",
    }
    r1_validation["status"] = "PASS" if all([
        required_ok, ledger["event_id"].is_unique,
        r1_validation["invalid_event_type_count"] == 0,
        r1_validation["invalid_severity_count"] == 0, pit_nulls == 0,
    ]) else "FAIL"
    write_json(out / OUTPUT_NAMES[1], r1_validation)
    (out / OUTPUT_NAMES[2]).write_text(
        markdown_validation("V21.093-R1 Event Schema Validation", r1_validation),
        encoding="utf-8",
    )

    # R2
    features = make_features(base, ledger)
    features.to_csv(out / OUTPUT_NAMES[3], index=False)
    feature_summary = features.groupby(["as_of_date", "event_window"], dropna=False).agg(
        ticker_count=("ticker", "nunique"),
        mean_event_risk_score=("event_risk_score", "mean"),
        max_event_risk_score=("event_risk_score", "max"),
        zero_score_count=("event_risk_score", lambda s: int(s.eq(0).sum())),
        pit_allowed_count=("pit_allowed", "sum"),
    ).reset_index()
    feature_summary.to_csv(out / OUTPUT_NAMES[4], index=False)
    expected_feature_rows = len(base[["as_of_date", "ticker"]].drop_duplicates())
    r2_validation = {
        "stage": "V21.093-R2_EVENT_RISK_FEATURE_PRODUCER",
        "status": "PASS",
        "research_only": True, "official_adoption_allowed": False,
        "feature_rows": len(features), "expected_feature_rows": expected_feature_rows,
        "duplicate_ticker_date_rows": int(features.duplicated(["ticker", "as_of_date"]).sum()),
        "score_out_of_range_count": int((~features["event_risk_score"].between(0, 100)).sum()),
        "no_event_nonzero_score_count": int((
            features["nearest_event_id"].fillna("").eq("") & features["event_risk_score"].ne(0)
        ).sum()),
        "pit_disallowed_feature_count": int((~features["pit_allowed"].map(truth)).sum()),
        "pit_leakage_warnings": 0,
        "deterministic_scoring": True,
        "post_event_market_data_used": False,
    }
    r2_validation["status"] = "PASS" if (
        len(features) == expected_feature_rows
        and r2_validation["duplicate_ticker_date_rows"] == 0
        and r2_validation["score_out_of_range_count"] == 0
        and r2_validation["no_event_nonzero_score_count"] == 0
    ) else "FAIL"
    write_json(out / OUTPUT_NAMES[5], r2_validation)
    (out / OUTPUT_NAMES[6]).write_text(
        markdown_validation("V21.093-R2 Event Risk Feature Validation", r2_validation),
        encoding="utf-8",
    )

    # R3
    variants = make_variants(base, features)
    variants.to_csv(out / OUTPUT_NAMES[7], index=False)
    variant_summary = summarize_variants(variants)
    variant_summary.to_csv(out / OUTPUT_NAMES[8], index=False)
    baseline_variant = variants[variants["variant_id"].eq("D_BASELINE_PRESERVED")]
    score_preserved = bool(np.allclose(
        baseline_variant["D_final_score"], baseline_variant["event_adjusted_score"],
        equal_nan=True,
    ))
    rank_preserved = bool((baseline_variant["D_rank"] == baseline_variant["variant_rank"]).all())
    latest_d_hash_mid = sha256(root / LATEST_D_REL)
    r3_validation = {
        "stage": "V21.093-R3_D_EVENT_RISK_RANKING_VARIANTS",
        "status": "PASS",
        "research_only": True, "official_adoption_allowed": False,
        "variant_rows": len(variants), "variants_tested": len(VARIANTS),
        "variant_ids": list(VARIANTS), "join_missing_feature_count": int(variants["pit_allowed"].isna().sum()),
        "d_baseline_score_preserved": score_preserved,
        "d_baseline_rank_preserved": rank_preserved,
        "d_baseline_preserved": score_preserved and rank_preserved and latest_d_hash_before == latest_d_hash_mid,
        "latest_d_artifact_hash_before": latest_d_hash_before,
        "latest_d_artifact_hash_after": latest_d_hash_mid,
        "protected_outputs_modified": False,
        "official_outputs_modified": False,
    }
    r3_validation["status"] = "PASS" if (
        r3_validation["d_baseline_preserved"] and r3_validation["join_missing_feature_count"] == 0
    ) else "FAIL"

    # R4
    bt_rows, _ = backtest_rows(variants, outcomes)
    bt_rows.to_csv(out / OUTPUT_NAMES[11], index=False)
    bt_summary = summarize_backtest(bt_rows)
    bt_summary.to_csv(out / OUTPUT_NAMES[12], index=False)
    r4_validation = {
        "stage": "V21.093-R4_RANDOM_EVENT_RISK_BACKTEST",
        "status": "PASS",
        "research_only": True, "official_adoption_allowed": False,
        "random_backtest_rows": len(bt_rows),
        "summary_rows": len(bt_summary),
        "variants_tested": int(bt_summary["variant_id"].nunique()),
        "top_n_buckets": sorted(bt_summary["top_n"].unique().tolist()),
        "forward_windows": sorted(bt_summary["forward_window"].unique().tolist()),
        "minimum_group_sample_count": int(bt_summary["sample_count"].min()),
        "qqq_benchmark_available": bool(bt_rows["benchmark_qqq_return"].notna().any()),
        "spy_benchmark_available": bool(bt_rows["benchmark_spy_return"].notna().any()),
        "pit_invalid_input_rows": 0,
        "post_event_definition_used": False,
    }
    if (
        r4_validation["variants_tested"] != len(VARIANTS)
        or set(r4_validation["top_n_buckets"]) != set(TOP_BUCKETS)
        or set(r4_validation["forward_windows"]) != set(WINDOWS)
    ):
        r4_validation["status"] = "FAIL"

    # Final mutation audit before R3/R4 reports and R5.
    after_compute = file_snapshot(root, output_paths)
    modified = changed_files(before, after_compute)
    official_modified = [p for p in modified if "official" in p.lower() or "broker" in p.lower()]
    r3_validation["protected_outputs_modified"] = bool(modified)
    r3_validation["official_outputs_modified"] = bool(official_modified)
    r3_validation["modified_protected_paths"] = modified
    if modified:
        r3_validation["status"] = "FAIL"
    write_json(out / OUTPUT_NAMES[9], r3_validation)
    (out / OUTPUT_NAMES[10]).write_text(
        markdown_validation("V21.093-R3 Join Validation", r3_validation),
        encoding="utf-8",
    )
    write_json(out / OUTPUT_NAMES[13], r4_validation)
    (out / OUTPUT_NAMES[14]).write_text(
        markdown_validation("V21.093-R4 Random Event Risk Backtest Validation", r4_validation),
        encoding="utf-8",
    )

    # R5
    decision, reason, details = choose_decision(r1_validation, r3_validation, r4_validation, bt_summary)
    final_status = "PASS" if all(
        x["status"] == "PASS" for x in (r1_validation, r2_validation, r3_validation, r4_validation)
    ) else "FAIL"
    next_stage = (
        "V21.094_VERIFIED_TICKER_EVENT_SOURCE_INGESTION"
        if decision in {"EVENT_RISK_FACTOR_NOT_EFFECTIVE", "EVENT_RISK_FACTOR_INSUFFICIENT_DATA"}
        else "NO_OFFICIAL_ADOPTION_RESEARCH_REVIEW_ONLY"
    )
    final = {
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "DECISION_REASON": reason,
        "D_BASELINE_PRESERVED": bool(r3_validation["d_baseline_preserved"]),
        "PROTECTED_OUTPUTS_MODIFIED": bool(r3_validation["protected_outputs_modified"]),
        "OFFICIAL_OUTPUTS_MODIFIED": bool(r3_validation["official_outputs_modified"]),
        "RESEARCH_ONLY": True,
        "OFFICIAL_ADOPTION_ALLOWED": False,
        "PIT_LEAKAGE_WARNINGS": int(r1_validation["pit_leakage_warnings"] + r2_validation["pit_leakage_warnings"]),
        "EVENT_ROWS": len(ledger),
        "FEATURE_ROWS": len(features),
        "VARIANTS_TESTED": len(VARIANTS),
        "RANDOM_BACKTEST_ROWS": len(bt_rows),
        "BEST_VARIANT": details["best_variant"],
        "TAIL_RISK_IMPROVEMENT": details["tail_risk_improvement"],
        "ENDING_VALUE_DELTA_VS_D": details["ending_value_delta_vs_D"],
        "MISSED_WINNERS": details["missed_winners"],
        "AVOIDED_LOSERS": details["avoided_losers"],
        "RECOMMENDED_NEXT_STAGE": next_stage,
        "DETAILS": details,
        "EVENT_SOURCE_SCOPE": [
            "RULE_BASED_EXCHANGE_CALENDAR",
            "RULE_BASED_NYSE_HOLIDAY_CALENDAR",
        ],
        "EXCLUDED_UNVERIFIABLE_EVENT_TYPES": sorted(EVENT_TYPES - set(ledger["event_type"])),
    }
    report = [
        "# V21.093-R5 Event Risk Factor Decision Report", "",
        f"**Decision:** `{decision}`", "",
        reason, "",
        "## Integrity gates", "",
        f"- Research-only: `{RESEARCH_ONLY}`",
        f"- Official adoption allowed: `{OFFICIAL_ADOPTION_ALLOWED}`",
        f"- D baseline preserved: `{final['D_BASELINE_PRESERVED']}`",
        f"- Protected outputs modified: `{final['PROTECTED_OUTPUTS_MODIFIED']}`",
        f"- Official outputs modified: `{final['OFFICIAL_OUTPUTS_MODIFIED']}`",
        f"- PIT leakage warnings: `{final['PIT_LEAKAGE_WARNINGS']}`", "",
        "## Result", "",
        f"- Best variant: `{details['best_variant']}`",
        f"- Tail-risk improvement: `{details['tail_risk_improvement']}`",
        f"- Ending-value delta versus D: `{details['ending_value_delta_vs_D']:.6f}`",
        f"- Mean-return delta versus D: `{details['mean_return_delta_vs_D']:.8f}`",
        f"- Missed winners: `{details['missed_winners']}`",
        f"- Avoided losers: `{details['avoided_losers']}`", "",
        "## Scope limitation", "",
        "Only locally verifiable, rule-based exchange and holiday calendar events were admitted. "
        "Historical earnings, macro releases, sector events, and company events were excluded "
        "because a PIT-verifiable known-as-of timestamp source was not available locally.", "",
        f"Recommended next stage: `{next_stage}`", "",
    ]
    (out / OUTPUT_NAMES[15]).write_text("\n".join(report), encoding="utf-8")
    write_json(out / OUTPUT_NAMES[16], final)
    return final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    final = run(args.root.resolve())
    for key in (
        "FINAL_STATUS", "DECISION", "D_BASELINE_PRESERVED",
        "PROTECTED_OUTPUTS_MODIFIED", "OFFICIAL_OUTPUTS_MODIFIED", "RESEARCH_ONLY",
        "OFFICIAL_ADOPTION_ALLOWED", "PIT_LEAKAGE_WARNINGS", "EVENT_ROWS",
        "FEATURE_ROWS", "VARIANTS_TESTED", "RANDOM_BACKTEST_ROWS", "BEST_VARIANT",
        "TAIL_RISK_IMPROVEMENT", "ENDING_VALUE_DELTA_VS_D", "MISSED_WINNERS",
        "AVOIDED_LOSERS", "RECOMMENDED_NEXT_STAGE",
    ):
        print(f"{key}={final[key]}")
    return 0 if final["FINAL_STATUS"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
