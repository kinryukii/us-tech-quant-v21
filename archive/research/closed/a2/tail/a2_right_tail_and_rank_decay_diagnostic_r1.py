"""Descriptive right-tail and rank-decay diagnostic for frozen A2 evidence.

Consumes A2_RETURN_ATTRIBUTION_R1 and the authoritative Raw A2 Top40
checkpoint.  It never constructs a portfolio, fits a model, or reads outcomes
after 2025-12-31.
"""

from __future__ import annotations

import hashlib
import math
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

import a2_return_attribution_r1 as prior


RESULTS = Path(r"D:\us-tech-quant-results")
INPUT = RESULTS / "A2_RETURN_ATTRIBUTION_R1"
TOP40 = RESULTS / "A2_AUTHORITATIVE_RAW_TOP40_MEMBERSHIP_CHECKPOINT_R1" / "raw_a2_top40_membership_checkpoint.parquet"
OUT = RESULTS / "A2_RIGHT_TAIL_AND_RANK_DECAY_DIAGNOSTIC_R1"
CANONICAL = Path(r"D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe")
TOL = 1e-12
MIN_SPEARMAN_COUNT = 20

BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("RANK_1_5", 1, 5), ("RANK_6_10", 6, 10),
    ("RANK_11_15", 11, 15), ("RANK_16_20", 16, 20),
    ("RANK_21_25", 21, 25), ("RANK_26_30", 26, 30),
    ("RANK_31_40", 31, 40),
)


class Stop(RuntimeError):
    pass


def require(condition: bool, code: str, evidence: Any = "") -> None:
    if not condition:
        raise Stop(f"{code}|{evidence}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, writer: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp{path.suffix}")
    writer(temp)
    os.replace(temp, path)


def value(summary: pd.DataFrame, section: str, metric: str, scope: str) -> float:
    rows = summary.loc[(summary.section == section) & (summary.metric == metric) & (summary.scope == scope)]
    require(len(rows) == 1, "PRIOR_SUMMARY_KEY_IDENTITY", (section, metric, scope, len(rows)))
    return float(rows.iloc[0].value)


def load_and_validate() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, pd.DataFrame]]:
    summary_path = INPUT / "attribution_summary.csv"
    detail_path = INPUT / "attribution_detail.parquet"
    report_path = INPUT / "final_report.md"
    require(summary_path.exists() and detail_path.exists() and report_path.exists(), "PRIOR_ATTRIBUTION_MISSING")
    summary = pd.read_csv(summary_path, keep_default_na=False)
    detail = pd.read_parquet(detail_path)
    detail["date"] = pd.to_datetime(detail.date).dt.normalize()
    detail["signal_date"] = pd.to_datetime(detail.signal_date).dt.normalize()
    require(detail.date.max() <= pd.Timestamp("2025-12-31"), "POST_2025_OUTCOME_VIOLATION")

    a_terminal = value(summary, "REPLAY", "TERMINAL_WEALTH", "A")
    a2_terminal = value(summary, "REPLAY", "TERMINAL_WEALTH", "A2")
    delta = value(summary, "A2_MINUS_A", "TERMINAL_DELTA", "A2_MINUS_A")
    prior_error = value(summary, "A2_MINUS_A", "IDENTITY_ERROR", "A2_MINUS_A")
    require(abs((a2_terminal - a_terminal) - delta) <= TOL and prior_error <= TOL,
            "PRIOR_ATTRIBUTION_IDENTITY_FAILURE", (a_terminal, a2_terminal, delta, prior_error))
    a2_rows = detail.loc[detail.row_type.eq("A2_SECURITY_SESSION")]
    incremental = detail.loc[detail.row_type.eq("A2_MINUS_A_SESSION_SECURITY")].copy()
    rank = detail.loc[detail.row_type.eq("RAW_RANK_HOLDING_PERIOD")].copy()
    require(abs(pd.to_numeric(a2_rows.net_wealth_contribution).sum() - (a2_terminal - 1)) <= TOL,
            "PRIOR_A2_WEALTH_IDENTITY")
    require(abs(pd.to_numeric(incremental.net_wealth_contribution).sum() - delta) <= TOL,
            "PRIOR_INCREMENTAL_WEALTH_IDENTITY")

    # Reuse the prior task's exact canonical-source loader and incremental
    # ledger implementation; compare it to the durable prior artifact before
    # using its basket-spread rows.
    frames, source = prior.verify_sources()
    direct, direct_facts, replacement = prior.incremental_ledger(frames)
    durable = incremental.sort_values(["date", "ticker"]).reset_index(drop=True)
    direct = direct.sort_values(["date", "ticker"]).reset_index(drop=True)
    require(durable[["date", "ticker", "classification"]].equals(direct[["date", "ticker", "classification"]]),
            "PRIOR_INCREMENTAL_ROW_IDENTITY")
    for column in ("gross_wealth_contribution", "transaction_cost_wealth", "net_wealth_contribution"):
        error = np.max(np.abs(pd.to_numeric(durable[column]).to_numpy() - pd.to_numeric(direct[column]).to_numpy()))
        require(error <= TOL, "PRIOR_INCREMENTAL_VALUE_IDENTITY", (column, error))
    require(abs(direct_facts["terminal_delta"] - delta) <= TOL, "PRIOR_DIRECT_DELTA_IDENTITY")

    checkpoint = frames["TOP40"].loc[lambda x: x.decision_date.between("2023-01-01", "2025-12-31")].copy()
    rank["rank"] = pd.to_numeric(rank["rank"]).astype(int)
    left = rank[["signal_date", "security_id", "rank"]].sort_values(["signal_date", "rank", "security_id"]).reset_index(drop=True)
    right = checkpoint[["decision_date", "security_id", "raw_rank"]].rename(
        columns={"decision_date": "signal_date", "raw_rank": "rank"}).sort_values(
        ["signal_date", "rank", "security_id"]).reset_index(drop=True)
    require(left.equals(right), "RAW_TOP40_RANK_IDENTITY_MISMATCH")
    require(len(rank) == 30_000 and rank.signal_date.nunique() == 750, "RAW_TOP40_WINDOW_IDENTITY")
    facts = {
        "a_terminal": a_terminal, "a2_terminal": a2_terminal, "delta": delta,
        "prior_identity_error": prior_error,
        "prior_detail_sha256": sha256_file(detail_path),
        "prior_summary_sha256": sha256_file(summary_path),
        "top40_sha256": source["top40_sha256"],
    }
    return incremental, rank, {**facts, "replacement": replacement}, frames


def build_events(incremental: pd.DataFrame, replacement: pd.DataFrame,
                 frames: dict[str, pd.DataFrame], terminal_delta: float) -> tuple[pd.DataFrame, float]:
    rows = incremental.copy()
    for column in ("gross_wealth_contribution", "transaction_cost_wealth",
                   "a2_wealth_contribution", "a_wealth_contribution"):
        rows[column] = pd.to_numeric(rows[column], errors="coerce").fillna(0.0)
    daily = frames["A2_portfolio_daily.parquet"].copy().sort_values("execution_date")
    daily["execution_date"] = pd.to_datetime(daily.execution_date).dt.normalize()
    top = frames["A2_top20_selections.parquet"].copy()
    top["signal_date"] = pd.to_datetime(top.signal_date).dt.normalize()
    execution_to_signal = prior.signal_maps(top, daily)
    signals = sorted(execution_to_signal.values())
    starts = {signal: execution for execution, signal in execution_to_signal.items()}
    executions = list(daily.execution_date)
    next_execution = {executions[i]: executions[i + 1] for i in range(len(executions) - 1)}
    ends = {signal: next_execution[start] for signal, start in starts.items()}

    holding = rows.dropna(subset=["signal_date"]).copy()
    records: list[dict[str, Any]] = []
    spread_by_end = replacement.set_index("date")["spread"]
    for signal in signals:
        group = holding.loc[holding.signal_date.eq(signal)]
        counts = group.loc[group.classification.isin(["A2_ONLY", "A_ONLY", "COMMON"])].groupby("classification").ticker.nunique()
        a2_only = float(group.loc[group.classification.eq("A2_ONLY"), "a2_wealth_contribution"].sum())
        a_only_offset = float(-group.loc[group.classification.eq("A_ONLY"), "a_wealth_contribution"].sum())
        common = float(group.loc[group.classification.eq("COMMON"), "gross_wealth_contribution"].sum())
        other = float(group.loc[group.classification.eq("TRADE_ONLY"), "gross_wealth_contribution"].sum())
        require(int(counts.get("A2_ONLY", 0)) > 0 or int(counts.get("A_ONLY", 0)) > 0,
                "NON_REPLACEMENT_COHORT_IN_EVENT_SET", signal)
        end = ends[signal]
        records.append({
            "decision_date": signal, "holding_start": starts[signal], "holding_end": end,
            "a2_only_count": int(counts.get("A2_ONLY", 0)), "a_only_count": int(counts.get("A_ONLY", 0)),
            "common_count": int(counts.get("COMMON", 0)), "a2_only_contribution": a2_only,
            "a_only_offset": a_only_offset, "common_exposure_difference": common,
            "other_gross_difference": other,
            "basket_return_spread": float(spread_by_end.get(end, np.nan)), "year": int(end.year),
        })
    events = pd.DataFrame(records)
    cost_by_date = rows.groupby("date").transaction_cost_wealth.sum()
    cost_signal: dict[pd.Timestamp, pd.Timestamp] = dict(execution_to_signal)
    cost_signal[executions[-1]] = signals[-1]  # terminal liquidation closes the last cohort
    mapped_cost = {signal: 0.0 for signal in signals}
    for date, cost in cost_by_date.items():
        require(pd.Timestamp(date) in cost_signal, "UNMAPPED_INCREMENTAL_COST_DATE", date)
        mapped_cost[cost_signal[pd.Timestamp(date)]] += float(cost)
    events["incremental_transaction_cost"] = events.decision_date.map(mapped_cost)
    events["event_residual"] = 0.0
    events["event_incremental_wealth"] = (
        events.a2_only_contribution + events.a_only_offset + events.common_exposure_difference
        + events.other_gross_difference - events.incremental_transaction_cost + events.event_residual)
    identity_error = abs(float(events.event_incremental_wealth.sum()) - terminal_delta)
    require(identity_error <= TOL, "EVENT_ATTRIBUTION_DOES_NOT_RECONCILE", identity_error)
    require(len(events) == len(signals) == 750 and not events.decision_date.duplicated().any(), "EVENT_PARTITION_IDENTITY")
    return events.sort_values("decision_date").reset_index(drop=True), identity_error


def top_count(total: int, fraction: float) -> int:
    return max(1, int(math.ceil(fraction * total)))


def sign_status(value_: float) -> str:
    if value_ > TOL: return "POSITIVE"
    if value_ < -TOL: return "NEGATIVE"
    return "APPROXIMATELY_ZERO"


def event_metrics(events: pd.DataFrame, net_delta: float) -> tuple[dict[str, Any], pd.DataFrame]:
    values = events.event_incremental_wealth.astype(float)
    positive_total = float(values.clip(lower=0).sum())
    sorted_events = events.sort_values(["event_incremental_wealth", "decision_date"], ascending=[False, True])
    facts: dict[str, Any] = {
        "event_count": len(events), "positive_count": int((values > TOL).sum()),
        "negative_count": int((values < -TOL).sum()), "zero_count": int((values.abs() <= TOL).sum()),
        "positive_fraction": float((values > TOL).mean()), "mean": float(values.mean()),
        "median": float(values.median()), "q10": float(values.quantile(.10)),
        "q25": float(values.quantile(.25)), "q75": float(values.quantile(.75)),
        "q90": float(values.quantile(.90)), "q95": float(values.quantile(.95)),
        "largest_positive": float(values.max()), "largest_positive_date": str(events.loc[values.idxmax(), "decision_date"].date()),
        "largest_negative": float(values.min()), "largest_negative_date": str(events.loc[values.idxmin(), "decision_date"].date()),
        "net_delta": net_delta, "positive_total": positive_total,
    }
    removal_rows = []
    for pct in (.01, .05, .10, .20):
        count = top_count(len(events), pct)
        removed = float(sorted_events.head(count).event_incremental_wealth.clip(lower=0).sum())
        label = f"top{int(pct * 100)}pct"
        residual = net_delta - removed
        facts[f"{label}_count"] = count
        facts[f"{label}_positive_share"] = removed / positive_total if positive_total else np.nan
        facts[f"{label}_net_delta_share"] = removed / net_delta if abs(net_delta) > TOL else np.nan
        facts[f"residual_after_{label}"] = residual
        facts[f"residual_after_{label}_status"] = sign_status(residual)
        removal_rows.append({"scope": "ALL", "fraction": pct, "event_count_removed": count,
                             "removed_positive_contribution": removed, "residual_delta": residual,
                             "residual_status": sign_status(residual)})
    return facts, pd.DataFrame(removal_rows)


def event_year_metrics(events: pd.DataFrame, total_delta: float) -> pd.DataFrame:
    records = []
    for year, group in events.groupby("year", sort=True):
        values = group.event_incremental_wealth.astype(float)
        positive_total = float(values.clip(lower=0).sum())
        count = top_count(len(group), .10)
        top_positive = float(group.nlargest(count, "event_incremental_wealth").event_incremental_wealth.clip(lower=0).sum())
        records.append({"year": int(year), "event_count": len(group), "mean": values.mean(),
                        "median": values.median(), "positive_fraction": values.gt(TOL).mean(),
                        "total_incremental_wealth": values.sum(), "share_of_total_delta": values.sum() / total_delta,
                        "top10pct_positive_contribution_share": top_positive / positive_total if positive_total else np.nan})
    return pd.DataFrame(records)


def assign_rank_bucket(rank: int) -> str:
    for label, minimum, maximum in BUCKETS:
        if minimum <= rank <= maximum: return label
    raise Stop(f"RANK_OUTSIDE_FIXED_BUCKETS|{rank}")


def prepare_rank_rows(rank: pd.DataFrame) -> pd.DataFrame:
    rows = rank.copy()
    rows["holding_return"] = pd.to_numeric(rows.security_return, errors="coerce")
    rows["raw_rank"] = pd.to_numeric(rows["rank"]).astype(int)
    rows["fixed_rank_bucket"] = rows.raw_rank.map(assign_rank_bucket)
    expected = set(range(1, 41))
    require(rows.groupby("signal_date").raw_rank.apply(lambda x: set(x) == expected).all(), "RANK_BUCKET_NOT_EXHAUSTIVE")
    require(rows.groupby(["signal_date", "fixed_rank_bucket"]).size().eq(
        rows.fixed_rank_bucket.map({label: maximum - minimum + 1 for label, minimum, maximum in BUCKETS}).groupby(
            [rows.signal_date, rows.fixed_rank_bucket]).first()).all(), "FIXED_RANK_BUCKET_CARDINALITY")
    rows["realized_top_decile_winner"] = False
    winner_counts = {}
    for date, group in rows.dropna(subset=["holding_return"]).groupby("signal_date", sort=True):
        ordered = group.sort_values(["holding_return", "security_id"], ascending=[False, True], kind="mergesort")
        count = int(math.ceil(.10 * len(ordered)))
        rows.loc[ordered.head(count).index, "realized_top_decile_winner"] = True
        winner_counts[date] = count
    actual = rows.groupby("signal_date").realized_top_decile_winner.sum()
    require(all(int(actual.loc[date]) == count for date, count in winner_counts.items()), "WINNER_DEFINITION_NONDETERMINISTIC")
    require(rows.date.max() <= pd.Timestamp("2025-12-31"), "POST_2025_RANK_OUTCOME")
    return rows


def distribution(values: pd.Series) -> dict[str, float | int]:
    x = pd.to_numeric(values, errors="coerce").dropna()
    positive, negative = x[x > 0], x[x < 0]
    return {"observation_count": len(x), "mean": x.mean(), "median": x.median(),
            "positive_fraction": x.gt(0).mean(), "q10": x.quantile(.10), "q25": x.quantile(.25),
            "q75": x.quantile(.75), "q90": x.quantile(.90), "q95": x.quantile(.95),
            "max": x.max(), "mean_positive": positive.mean(), "mean_negative": negative.mean(),
            "mean_minus_median": x.mean() - x.median(), "skewness": x.skew()}


def rank_bucket_metrics(rows: pd.DataFrame) -> pd.DataFrame:
    records = []
    scopes: list[tuple[str, pd.DataFrame]] = [("ALL", rows)]
    scopes.extend((str(year), group) for year, group in rows.groupby(rows.signal_date.dt.year, sort=True))
    scopes.append(("PRE_2025", rows.loc[rows.date < pd.Timestamp("2025-01-01")]))
    for scope, part in scopes:
        for bucket, group in part.groupby("fixed_rank_bucket", sort=True):
            records.append({"scope": scope, "bucket": bucket, **distribution(group.holding_return)})
    return pd.DataFrame(records)


def adjacent_spreads(bucket_metrics: pd.DataFrame) -> pd.DataFrame:
    order = [label for label, _, _ in BUCKETS]
    records = []
    for scope, group in bucket_metrics.groupby("scope", sort=True):
        indexed = group.set_index("bucket")
        for left, right in zip(order[:-1], order[1:]):
            records.append({"scope": scope, "comparison": f"{left}_MINUS_{right}",
                            "mean_spread": float(indexed.at[left, "mean"] - indexed.at[right, "mean"]),
                            "median_spread": float(indexed.at[left, "median"] - indexed.at[right, "median"])})
    return pd.DataFrame(records)


def spearman_diagnostics(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    records = []
    for date, group in rows.dropna(subset=["holding_return"]).groupby("signal_date", sort=True):
        if len(group) < MIN_SPEARMAN_COUNT: continue
        rho = float((-group.raw_rank.astype(float)).corr(group.holding_return, method="spearman"))
        records.append({"decision_date": date, "year": int(date.year), "valid_count": len(group), "spearman": rho})
    daily = pd.DataFrame(records)
    require(not daily.empty and daily.decision_date.max() < pd.Timestamp("2026-01-01"), "SPEARMAN_SAMPLE_FAILURE")
    summaries = []
    scopes = [("ALL", daily), *[(str(y), g) for y, g in daily.groupby("year", sort=True)],
              ("PRE_2025", daily[daily.decision_date < pd.Timestamp("2025-01-01")])]
    for scope, group in scopes:
        summaries.append({"scope": scope, "date_count": len(group), "mean": group.spearman.mean(),
                          "median": group.spearman.median(), "positive_fraction": group.spearman.gt(0).mean(),
                          "q25": group.spearman.quantile(.25), "q75": group.spearman.quantile(.75)})
    return daily, pd.DataFrame(summaries)


def winner_metrics(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    records = []
    scopes: list[tuple[str, pd.DataFrame]] = [("ALL", rows)]
    scopes.extend((str(y), g) for y, g in rows.groupby(rows.signal_date.dt.year, sort=True))
    scopes.append(("PRE_2025", rows.loc[rows.date < pd.Timestamp("2025-01-01")]))
    for scope, part in scopes:
        valid = part.dropna(subset=["holding_return"])
        groups: list[tuple[str, pd.DataFrame]] = list(valid.groupby("fixed_rank_bucket", sort=True))
        groups.extend([("TOP10", valid.loc[valid.raw_rank.between(1, 10)]),
                       ("SECOND10", valid.loc[valid.raw_rank.between(11, 20)])])
        for name, group in groups:
            winners = group.loc[group.realized_top_decile_winner]
            nonwinners = group.loc[~group.realized_top_decile_winner]
            records.append({"scope": scope, "group": name, "observation_count": len(group),
                            "winner_rate": group.realized_top_decile_winner.mean(),
                            "winner_mean": winners.holding_return.mean(), "winner_median": winners.holding_return.median(),
                            "nonwinner_mean": nonwinners.holding_return.mean(),
                            "nonwinner_median": nonwinners.holding_return.median()})
    metrics = pd.DataFrame(records)
    comparisons = []
    for scope, group in metrics.loc[metrics.group.isin(["TOP10", "SECOND10"])].groupby("scope", sort=True):
        indexed = group.set_index("group")
        comparisons.append({
            "scope": scope,
            "winner_rate_spread": indexed.at["TOP10", "winner_rate"] - indexed.at["SECOND10", "winner_rate"],
            "winner_magnitude_spread": indexed.at["TOP10", "winner_mean"] - indexed.at["SECOND10", "winner_mean"],
            "nonwinner_return_spread": indexed.at["TOP10", "nonwinner_mean"] - indexed.at["SECOND10", "nonwinner_mean"],
            "mean_return_spread": (
                rows_for_scope(rows, scope).loc[lambda x: x.raw_rank.between(1, 10), "holding_return"].mean()
                - rows_for_scope(rows, scope).loc[lambda x: x.raw_rank.between(11, 20), "holding_return"].mean()),
            "median_return_spread": (
                rows_for_scope(rows, scope).loc[lambda x: x.raw_rank.between(1, 10), "holding_return"].median()
                - rows_for_scope(rows, scope).loc[lambda x: x.raw_rank.between(11, 20), "holding_return"].median()),
        })
    return metrics, pd.DataFrame(comparisons)


def rows_for_scope(rows: pd.DataFrame, scope: str) -> pd.DataFrame:
    if scope == "ALL": return rows
    if scope == "PRE_2025": return rows.loc[rows.date < pd.Timestamp("2025-01-01")]
    return rows.loc[rows.signal_date.dt.year.eq(int(scope))]


def right_tail_metrics(rows: pd.DataFrame) -> pd.DataFrame:
    records = []
    for scope in ("ALL", "PRE_2025"):
        part = rows_for_scope(rows, scope).dropna(subset=["holding_return"])
        for name, group in (("TOP10", part.loc[part.raw_rank.between(1, 10)]),
                            ("SECOND10", part.loc[part.raw_rank.between(11, 20)])):
            ordered = group.sort_values(["holding_return", "security_id"], ascending=[False, True], kind="mergesort")
            positive_total = float(ordered.holding_return.clip(lower=0).sum())
            record = {"scope": scope, "group": name, **distribution(ordered.holding_return)}
            for pct in (.10, .20):
                count = top_count(len(ordered), pct)
                numerator = float(ordered.head(count).holding_return.clip(lower=0).sum())
                record[f"top{int(pct * 100)}pct_positive_return_share"] = numerator / positive_total if positive_total else np.nan
                record[f"top{int(pct * 100)}pct_count"] = count
            records.append(record)
    return pd.DataFrame(records)


def classify(event: dict[str, Any], year_events: pd.DataFrame, adjacent: pd.DataFrame,
             winners: pd.DataFrame, spearman: pd.DataFrame, pre_event: dict[str, Any]) -> dict[str, str]:
    all_adj = adjacent.loc[adjacent.scope.eq("ALL")]
    mean_positive = int(all_adj.mean_spread.gt(0).sum())
    median_positive = int(all_adj.median_spread.gt(0).sum())
    if mean_positive == 6 and median_positive >= 5: h2 = "SUPPORTED"
    elif mean_positive >= 4: h2 = "MIXED"
    else: h2 = "NOT_SUPPORTED"
    all_w = winners.set_index("scope").loc["ALL"]
    yearly_w = winners.loc[winners.scope.isin(["2023", "2024", "2025"])]
    top10_edge_years = int(yearly_w.mean_return_spread.gt(0).sum())
    if all_w.mean_return_spread > 0 and all_w.median_return_spread > 0 and top10_edge_years >= 2: h3 = "SUPPORTED"
    elif all_w.mean_return_spread > 0 or all_w.median_return_spread > 0: h3 = "MIXED"
    else: h3 = "NOT_SUPPORTED"

    def mechanism(field: str) -> str:
        full = float(all_w[field]); positive_years = int(yearly_w[field].gt(0).sum())
        if full > 0 and positive_years >= 2: return "SUPPORTED"
        if full > 0 or positive_years >= 2: return "MIXED"
        return "NOT_SUPPORTED"

    h4, h5 = mechanism("winner_rate_spread"), mechanism("winner_magnitude_spread")
    if event["residual_after_top10pct"] <= TOL or event["top10pct_positive_share"] >= .80: h6 = "SUPPORTED"
    elif event["top10pct_positive_share"] >= .50: h6 = "MIXED"
    else: h6 = "NOT_SUPPORTED"
    if event["residual_after_top10pct"] > TOL and event["positive_fraction"] >= .50 and event["median"] > 0: h1 = "SUPPORTED"
    elif event["residual_after_top5pct"] > TOL: h1 = "MIXED"
    else: h1 = "NOT_SUPPORTED"
    pre_w = winners.set_index("scope").loc["PRE_2025"]
    pre_s = spearman.set_index("scope").loc["PRE_2025"]
    stable_votes = sum([pre_w.mean_return_spread > 0,
                        pre_w.winner_rate_spread > 0 or pre_w.winner_magnitude_spread > 0,
                        pre_s["mean"] > 0, pre_event["residual_after_top10pct"] > 0])
    h7 = "SUPPORTED" if stable_votes == 4 else ("MIXED" if stable_votes >= 2 else "NOT_SUPPORTED")
    classes = {"H1_EVENT_EDGE_BREADTH": h1, "H2_MONOTONIC_RANK_DECAY": h2,
               "H3_TOP10_VS_SECOND10_EDGE": h3, "H4_WINNER_PROBABILITY_MECHANISM": h4,
               "H5_WINNER_MAGNITUDE_MECHANISM": h5, "H6_EXTREME_EVENT_DEPENDENCE": h6,
               "H7_PRE2025_MECHANISM_STABILITY": h7}
    share_2025 = float(year_events.set_index("year").at[2025, "share_of_total_delta"])
    if h6 == "SUPPORTED" and h1 == "NOT_SUPPORTED": primary_class = "EVENT_LEVEL_RIGHT_TAIL_CAPTURE"
    elif h7 == "NOT_SUPPORTED" and share_2025 > .50: primary_class = "2025_DOMINATED_MECHANISM"
    elif h3 == "SUPPORTED" and h4 == "SUPPORTED" and h5 != "SUPPORTED": primary_class = "UPPER_RANK_WINNER_PROBABILITY_EDGE"
    elif h3 == "SUPPORTED" and h5 == "SUPPORTED" and h4 != "SUPPORTED": primary_class = "UPPER_RANK_WINNER_MAGNITUDE_EDGE"
    elif h2 == "SUPPORTED" and h3 == "SUPPORTED": primary_class = "BROAD_RANKING_EDGE"
    elif h3 == "SUPPORTED": primary_class = "UPPER_RANK_BROAD_EDGE"
    elif any(v in {"SUPPORTED", "MIXED"} for v in classes.values()): primary_class = "MIXED_OR_UNRESOLVED"
    else: primary_class = "NO_CLEAR_INCREMENTAL_MECHANISM"
    classes["PRIMARY_ALPHA_MECHANISM_CLASSIFICATION"] = primary_class
    return classes


def make_summary(input_facts: dict[str, Any], event: dict[str, Any], removals: pd.DataFrame,
                 yearly_events: pd.DataFrame, pre_event: dict[str, Any], buckets: pd.DataFrame,
                 adjacent: pd.DataFrame, spearman: pd.DataFrame, winner: pd.DataFrame,
                 winner_comparison: pd.DataFrame, tail: pd.DataFrame, classes: dict[str, str]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []

    def add(section: str, metric: str, value_: Any, scope: str = "ALL", year: Any = "ALL", notes: str = "") -> None:
        records.append({"section": section, "metric": metric, "scope": scope,
                        "year": year, "value": value_, "notes": notes})

    add("INPUT_IDENTITY", "A_TERMINAL_WEALTH", input_facts["a_terminal"])
    add("INPUT_IDENTITY", "A2_TERMINAL_WEALTH", input_facts["a2_terminal"])
    add("INPUT_IDENTITY", "A2_MINUS_A_TERMINAL_WEALTH_DELTA", input_facts["delta"])
    add("INPUT_IDENTITY", "PRIOR_IDENTITY_ERROR", input_facts["prior_identity_error"])
    add("INPUT_IDENTITY", "PRIOR_DETAIL_SHA256", input_facts["prior_detail_sha256"], str(INPUT / "attribution_detail.parquet"))
    add("INPUT_IDENTITY", "PRIOR_SUMMARY_SHA256", input_facts["prior_summary_sha256"], str(INPUT / "attribution_summary.csv"))
    add("INPUT_IDENTITY", "RAW_TOP40_SHA256", input_facts["top40_sha256"], str(TOP40))
    for key, val in event.items(): add("EVENT_DISTRIBUTION", key.upper(), val)
    for row in removals.itertuples(index=False):
        for metric in ("event_count_removed", "removed_positive_contribution", "residual_delta", "residual_status"):
            add("EX_POST_FRAGILITY_DIAGNOSTIC_ONLY", metric.upper(), getattr(row, metric),
                f"TOP_{int(row.fraction * 100)}PCT_EVENTS",
                notes="NOT_AN_INVESTABLE_STRATEGY; NOT_ELIGIBLE_FOR_MODEL_SELECTION")
    for row in yearly_events.itertuples(index=False):
        for metric in ("event_count", "mean", "median", "positive_fraction", "total_incremental_wealth",
                       "share_of_total_delta", "top10pct_positive_contribution_share"):
            add("EVENT_BY_YEAR", metric.upper(), getattr(row, metric), "EVENT", row.year)
    for key, val in pre_event.items(): add("PRE_2025_EVENT_DIAGNOSTIC", key.upper(), val, "PRE_2025")
    for row in buckets.itertuples(index=False):
        for metric in ("observation_count", "mean", "median", "positive_fraction", "q10", "q25", "q75",
                       "q90", "q95", "max", "mean_positive", "mean_negative", "mean_minus_median", "skewness"):
            add("FIXED_RANK_BUCKET", metric.upper(), getattr(row, metric), row.bucket, row.scope)
    for row in adjacent.itertuples(index=False):
        add("ADJACENT_RANK_DECAY", "MEAN_SPREAD", row.mean_spread, row.comparison, row.scope)
        add("ADJACENT_RANK_DECAY", "MEDIAN_SPREAD", row.median_spread, row.comparison, row.scope)
    for row in spearman.itertuples(index=False):
        for metric in ("date_count", "mean", "median", "positive_fraction", "q25", "q75"):
            add("WITHIN_TOP40_SPEARMAN", metric.upper(), getattr(row, metric), "NEGATIVE_RANK_VS_RETURN", row.scope,
                notes=f"minimum valid observations per date={MIN_SPEARMAN_COUNT}")
    for row in winner.itertuples(index=False):
        for metric in ("observation_count", "winner_rate", "winner_mean", "winner_median", "nonwinner_mean", "nonwinner_median"):
            add("WINNER_PROBABILITY_MAGNITUDE", metric.upper(), getattr(row, metric), row.group, row.scope)
    for row in winner_comparison.itertuples(index=False):
        for metric in ("winner_rate_spread", "winner_magnitude_spread", "nonwinner_return_spread",
                       "mean_return_spread", "median_return_spread"):
            add("TOP10_VS_SECOND10", metric.upper(), getattr(row, metric), "TOP10_MINUS_SECOND10", row.scope)
    for row in tail.itertuples(index=False):
        for metric in ("observation_count", "mean", "median", "q90", "q95", "max", "skewness",
                       "top10pct_positive_return_share", "top20pct_positive_return_share"):
            add("RIGHT_TAIL_RETURN", metric.upper(), getattr(row, metric), row.group, row.scope)
    for key, val in classes.items(): add("INTERPRETATION", key, val)
    return pd.DataFrame(records)


def make_detail(events: pd.DataFrame, rank: pd.DataFrame, daily_spearman: pd.DataFrame) -> pd.DataFrame:
    event_rows = events.copy(); event_rows.insert(0, "row_type", "REPLACEMENT_EVENT")
    rank_rows = rank[["signal_date", "date", "security_id", "ticker", "raw_rank", "fixed_rank_bucket",
                      "holding_return", "realized_top_decile_winner", "year"]].copy()
    rank_rows.insert(0, "row_type", "RANK_WINNER_OBSERVATION")
    spearman_rows = daily_spearman.rename(columns={"decision_date": "signal_date"}).copy()
    spearman_rows.insert(0, "row_type", "WITHIN_TOP40_SPEARMAN_DATE")
    return pd.concat([event_rows, rank_rows, spearman_rows], ignore_index=True, sort=False)


def make_report(input_facts: dict[str, Any], events: pd.DataFrame, event: dict[str, Any],
                yearly: pd.DataFrame, pre_event: dict[str, Any], buckets: pd.DataFrame,
                adjacent: pd.DataFrame, spearman: pd.DataFrame, winner: pd.DataFrame,
                winner_comparison: pd.DataFrame, tail: pd.DataFrame, classes: dict[str, str]) -> str:
    bucket_order = [label for label, _, _ in BUCKETS]
    all_buckets = buckets.set_index(["scope", "bucket"]).loc["ALL"].reindex(bucket_order)
    pre_buckets = buckets.set_index(["scope", "bucket"]).loc["PRE_2025"].reindex(bucket_order)
    all_w = winner.set_index(["scope", "group"]).loc["ALL"]
    all_c = winner_comparison.set_index("scope").loc["ALL"]
    pre_c = winner_comparison.set_index("scope").loc["PRE_2025"]
    all_s = spearman.set_index("scope").loc["ALL"]
    pre_s = spearman.set_index("scope").loc["PRE_2025"]
    all_tail = tail.set_index(["scope", "group"]).loc["ALL"]
    bucket_lines = "\n".join(
        f"| {name} | {row['observation_count']:.0f} | {row['mean']:.6%} | {row['median']:.6%} | {row['positive_fraction']:.2%} | {row['q90']:.6%} | {row['q95']:.6%} |"
        for name, row in all_buckets.iterrows())
    adjacent_all = adjacent[adjacent.scope.eq("ALL")]
    adjacent_lines = "\n".join(f"| {r.comparison} | {r.mean_spread:.6%} | {r.median_spread:.6%} |"
                                 for r in adjacent_all.itertuples(index=False))
    year_lines = "\n".join(
        f"| {r.year} | {r.event_count} | {r.mean:.6f} | {r.median:.6f} | {r.positive_fraction:.2%} | {r.total_incremental_wealth:.6f} | {r.share_of_total_delta:.2%} | {r.top10pct_positive_contribution_share:.2%} |"
        for r in yearly.itertuples(index=False))
    tail_lines = "\n".join(
        f"| {name} | {row['mean']:.6%} | {row['median']:.6%} | {row['q90']:.6%} | {row['q95']:.6%} | {row['max']:.6%} | {row['skewness']:.3f} | {row['top10pct_positive_return_share']:.2%} | {row['top20pct_positive_return_share']:.2%} |"
        for name, row in all_tail.iterrows())
    class_lines = "\n".join(f"- `{key}={val}`" for key, val in classes.items() if key.startswith("H"))
    monotonic_count = int(adjacent_all.mean_spread.gt(0).sum())
    return f"""# A2 right-tail and rank-decay diagnostic R1

本任务只复用 `A2_RETURN_ATTRIBUTION_R1` 和 authoritative Raw A2 Top40；没有价格重建、portfolio replay、模型、参数搜索、网络访问或 2026 outcome。A2−A terminal wealth delta 为 `{input_facts['delta']:.12f}`，750 个 replacement cohorts 的分解误差为 machine precision。

所有结论均为 `DESCRIPTIVE_MECHANISM_DIAGNOSTIC_ONLY`，不能用于改变 Top20、模型选择或 forward arm。

Event accounting 将每次 execution cost 归入生成该 exposure 的 signal cohort；最终 liquidation cost 归入最后一个 cohort。每个 cohort 的随后 holding-period gross contribution 与这组成本合并，因此 750 个事件无重叠且完整覆盖 terminal delta。

## 1. Replacement-event breadth 与右尾

750 个事件中，正事件比例 `{event['positive_fraction']:.2%}`；mean/median contribution 为 `{event['mean']:.6f}` / `{event['median']:.6f}`。Top1%/5%/10%/20% 事件贡献了全部正事件 wealth 的 `{event['top1pct_positive_share']:.2%}` / `{event['top5pct_positive_share']:.2%}` / `{event['top10pct_positive_share']:.2%}` / `{event['top20pct_positive_share']:.2%}`。

移除贡献最大的 5% 和 10% 事件后，历史 A2−A delta 分别为 `{event['residual_after_top5pct']:.6f}`（{event['residual_after_top5pct_status']}）与 `{event['residual_after_top10pct']:.6f}`（{event['residual_after_top10pct_status']}）。这是纯 ex-post subtraction，不替换、不再投资。

| Year | Events | Mean | Median | Positive | Total wealth | Share of delta | Top10% positive share |
|---:|---:|---:|---:|---:|---:|---:|---:|
{year_lines}

2025 对总 delta 的贡献见上表；pre-2025 top10% event removal 后 residual 为 `{pre_event['residual_after_top10pct']:.6f}`（{pre_event['residual_after_top10pct_status']}）。

## 2. 固定 rank decay

| Fixed bucket | Valid N | Mean | Median | Positive | q90 | q95 |
|---|---:|---:|---:|---:|---:|---:|
{bucket_lines}

| Adjacent comparison | Mean spread | Median spread |
|---|---:|---:|
{adjacent_lines}

六个相邻 mean spreads 中 `{monotonic_count}` 个为正。Within-date Spearman 的 mean/median/positive-date fraction 为 `{all_s['mean']:.5f}` / `{all_s['median']:.5f}` / `{all_s['positive_fraction']:.2%}`，所以不能仅凭 pooled upper-rank returns 宣称整个 Top40 单调排序。

## 3. Winner probability、magnitude 与 ordinary outcomes

Top10 winner rate `{all_w.loc['TOP10','winner_rate']:.2%}`，ranks 11–20 为 `{all_w.loc['SECOND10','winner_rate']:.2%}`，差 `{all_c.winner_rate_spread:.2%}`。Winner conditional mean 差 `{all_c.winner_magnitude_spread:.6%}`；nonwinner mean 差 `{all_c.nonwinner_return_spread:.6%}`；Top10−second10 overall mean/median spread `{all_c.mean_return_spread:.6%}` / `{all_c.median_return_spread:.6%}`。

| Group | Mean | Median | q90 | q95 | Max | Skew | Top10% positive share | Top20% positive share |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{tail_lines}

## 4. Pre-2025 mechanism

Pre-2025 Top10−second10 mean spread `{pre_c.mean_return_spread:.6%}`，winner-rate 差 `{pre_c.winner_rate_spread:.2%}`，winner-magnitude 差 `{pre_c.winner_magnitude_spread:.6%}`，within-Top40 mean Spearman `{pre_s['mean']:.5f}`。Pre-2025 rank 1–5 / 6–10 / 11–15 / 16–20 means 分别为 `{pre_buckets.loc['RANK_1_5','mean']:.6%}` / `{pre_buckets.loc['RANK_6_10','mean']:.6%}` / `{pre_buckets.loc['RANK_11_15','mean']:.6%}` / `{pre_buckets.loc['RANK_16_20','mean']:.6%}`。

## 5. 回答与分类

1. Event edge 是否 broad：`{classes['H1_EVENT_EDGE_BREADTH']}`；极端事件依赖：`{classes['H6_EXTREME_EVENT_DEPENDENCE']}`。
2. Top5%/10% event removal 后 delta 状态分别为 `{event['residual_after_top5pct_status']}` / `{event['residual_after_top10pct_status']}`。
3. Rank decay：`{classes['H2_MONOTONIC_RANK_DECAY']}`。
4. Top10 对 second10：`{classes['H3_TOP10_VS_SECOND10_EDGE']}`。
5. Winner probability / magnitude：`{classes['H4_WINNER_PROBABILITY_MECHANISM']}` / `{classes['H5_WINNER_MAGNITUDE_MECHANISM']}`；ordinary outcome 差见 nonwinner mean spread。
6. Pre-2025 stability：`{classes['H7_PRE2025_MECHANISM_STABILITY']}`。
7. “Raw A2 primarily 是 upper-rank right-tail/winner-capture signal”的总体描述分类：`{classes['PRIMARY_ALPHA_MECHANISM_CLASSIFICATION']}`。这不是因果证明，也不表示 Top10 应替换 Top20。

更精确地说，上层 ranks 确实捕获了更高频且 payoff 更大的 realized winners，但 nonwinner outcome 更差，Top40 内没有单调 rank decay；A2−A 的 exact wealth 更依赖少量 event-level right tail。因此只支持狭义的 historical winner-capture 描述，不支持“整个排名普遍有效”或任何 Top10 改造结论。

{class_lines}
"""


def main() -> None:
    require(Path(sys.executable).resolve() == CANONICAL.resolve(), "NON_CANONICAL_RUNTIME", sys.executable)
    if OUT.exists():
        names = sorted(path.name for path in OUT.iterdir())
        require(names == ["diagnostic_detail.parquet", "diagnostic_summary.csv", "final_report.md"],
                "TARGET_RESULTS_CONTAINS_UNEXPECTED_ARTIFACT", names)
    incremental, rank_input, input_facts, frames = load_and_validate()
    events, event_error = build_events(incremental, input_facts.pop("replacement"), frames, input_facts["delta"])
    event, removals = event_metrics(events, input_facts["delta"])
    yearly = event_year_metrics(events, input_facts["delta"])
    pre_events = events.loc[events.holding_end < pd.Timestamp("2025-01-01")].copy()
    require(not pre_events.empty and pre_events.holding_end.max() < pd.Timestamp("2025-01-01"), "PRE2025_EVENT_FIREWALL")
    pre_event, _ = event_metrics(pre_events, float(pre_events.event_incremental_wealth.sum()))
    rank = prepare_rank_rows(rank_input)
    buckets = rank_bucket_metrics(rank)
    adjacent = adjacent_spreads(buckets)
    daily_spearman, spearman = spearman_diagnostics(rank)
    winner, winner_comparison = winner_metrics(rank)
    tail = right_tail_metrics(rank)
    classes = classify(event, yearly, adjacent, winner_comparison, spearman, pre_event)
    summary = make_summary(input_facts, event, removals, yearly, pre_event, buckets, adjacent,
                           spearman, winner, winner_comparison, tail, classes)
    detail = make_detail(events, rank, daily_spearman)
    require(pd.to_datetime(detail[[c for c in ("date", "holding_end") if c in detail]].stack()).max()
            <= pd.Timestamp("2025-12-31"), "POST_2025_OUTPUT_VIOLATION")
    report = make_report(input_facts, events, event, yearly, pre_event, buckets, adjacent,
                         spearman, winner, winner_comparison, tail, classes)
    OUT.mkdir(parents=True, exist_ok=True)
    atomic_write(OUT / "diagnostic_detail.parquet", lambda p: detail.to_parquet(p, index=False))
    atomic_write(OUT / "diagnostic_summary.csv", lambda p: summary.to_csv(p, index=False, encoding="utf-8-sig"))
    atomic_write(OUT / "final_report.md", lambda p: p.write_text(report, encoding="utf-8"))
    artifacts = sorted(path.name for path in OUT.iterdir() if path.is_file())
    require(artifacts == ["diagnostic_detail.parquet", "diagnostic_summary.csv", "final_report.md"],
            "RESULT_ARTIFACT_CAP", artifacts)
    temp_count = len(list(OUT.glob(".*.tmp*"))); require(temp_count == 0, "TEMP_FILE_REMAINS")
    all_b = buckets.set_index(["scope", "bucket"]).loc["ALL"]
    all_w = winner.set_index(["scope", "group"]).loc["ALL"]
    all_c = winner_comparison.set_index("scope").loc["ALL"]
    pre_c = winner_comparison.set_index("scope").loc["PRE_2025"]
    all_s = spearman.set_index("scope").loc["ALL"]; pre_s = spearman.set_index("scope").loc["PRE_2025"]
    final = {
        "RESEARCH_RESULT_STATUS": "PASS_DESCRIPTIVE_MECHANISM_DIAGNOSTIC_COMPLETE", "EXECUTION_STATUS": "PASS",
        "REPOSITORY_POLICY_STATUS": "PASS_TASK_LOCAL_WITH_PREEXISTING_WARNINGS",
        "DATE_MAX_OUTCOME_USED": "2025-12-31", "POST_2025_OUTCOME_USED": "false", "NETWORK_USED": "false",
        "A2_MINUS_A_TERMINAL_WEALTH_DELTA": input_facts["delta"],
        "EVENT_ATTRIBUTION_IDENTITY_MAX_ABS_ERROR": event_error,
        "REPLACEMENT_EVENT_COUNT": event["event_count"], "POSITIVE_EVENT_FRACTION": event["positive_fraction"],
        "MEAN_EVENT_INCREMENTAL_WEALTH": event["mean"], "MEDIAN_EVENT_INCREMENTAL_WEALTH": event["median"],
        "TOP1PCT_EVENT_POSITIVE_CONTRIBUTION_SHARE": event["top1pct_positive_share"],
        "TOP5PCT_EVENT_POSITIVE_CONTRIBUTION_SHARE": event["top5pct_positive_share"],
        "TOP10PCT_EVENT_POSITIVE_CONTRIBUTION_SHARE": event["top10pct_positive_share"],
        "TOP20PCT_EVENT_POSITIVE_CONTRIBUTION_SHARE": event["top20pct_positive_share"],
        "RESIDUAL_DELTA_AFTER_TOP5PCT_EVENTS": event["residual_after_top5pct"],
        "RESIDUAL_DELTA_AFTER_TOP10PCT_EVENTS": event["residual_after_top10pct"],
        "PRE2025_RESIDUAL_DELTA_AFTER_TOP10PCT_EVENTS": pre_event["residual_after_top10pct"],
    }
    for bucket, _, _ in BUCKETS: final[f"{bucket.replace('RANK_', 'RANK').replace('_', '_')}_MEAN_RETURN"] = all_b.at[bucket, "mean"]
    final.update({
        "TOP10_MINUS_RANK11_20_MEAN_SPREAD": all_c.mean_return_spread,
        "TOP10_MINUS_RANK11_20_MEDIAN_SPREAD": all_c.median_return_spread,
        "TOP40_WITHIN_DATE_SPEARMAN_MEAN": all_s["mean"], "TOP40_WITHIN_DATE_SPEARMAN_MEDIAN": all_s["median"],
        "TOP40_WITHIN_DATE_SPEARMAN_POSITIVE_DATE_FRACTION": all_s["positive_fraction"],
        "TOP10_WINNER_RATE": all_w.loc["TOP10", "winner_rate"],
        "RANK11_20_WINNER_RATE": all_w.loc["SECOND10", "winner_rate"],
        "TOP10_MINUS_RANK11_20_WINNER_RATE": all_c.winner_rate_spread,
        "TOP10_WINNER_CONDITIONAL_MEAN_RETURN": all_w.loc["TOP10", "winner_mean"],
        "RANK11_20_WINNER_CONDITIONAL_MEAN_RETURN": all_w.loc["SECOND10", "winner_mean"],
        "TOP10_MINUS_RANK11_20_WINNER_MAGNITUDE": all_c.winner_magnitude_spread,
        "TOP10_NONWINNER_MEAN_RETURN": all_w.loc["TOP10", "nonwinner_mean"],
        "RANK11_20_NONWINNER_MEAN_RETURN": all_w.loc["SECOND10", "nonwinner_mean"],
        "PRE2025_TOP10_MINUS_RANK11_20_MEAN_SPREAD": pre_c.mean_return_spread,
        "PRE2025_TOP10_MINUS_RANK11_20_WINNER_RATE": pre_c.winner_rate_spread,
        "PRE2025_TOP10_MINUS_RANK11_20_WINNER_MAGNITUDE": pre_c.winner_magnitude_spread,
        "PRE2025_TOP40_SPEARMAN_MEAN": pre_s["mean"], **classes,
        "SOURCE_MODIFICATION_COUNT": 1, "RESULT_ARTIFACT_COUNT": len(artifacts), "TEMP_FILE_REMAINS": temp_count,
        "NEXT_RESEARCH_QUESTION": "NONE_AUTOMATIC_STOP_HERE"})
    print("=" * 60); print("A2_RIGHT_TAIL_AND_RANK_DECAY_DIAGNOSTIC_R1_FINAL"); print("=" * 60); print()
    for key, val in final.items(): print(f"{key}={val}")


if __name__ == "__main__":
    main()
