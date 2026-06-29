#!/usr/bin/env python
"""V21.119_R1 forward maturity update after the V21.120 price refresh."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.119_R1_FORWARD_MATURITY_UPDATE_AFTER_REFRESH"
OUT = ROOT / "outputs/v21/V21.119_R1_FORWARD_MATURITY_UPDATE_AFTER_REFRESH"

V116 = ROOT / "outputs/v21/V21.116_DAILY_TOP50_FULL_DATA_LEDGER_20260616_TO_LATEST"
V117 = ROOT / "outputs/v21/V21.117_EARLY_FORWARD_VALIDITY_EVALUATOR"
V117_R1 = ROOT / "outputs/v21/V21.117_R1_D_EARLY_EDGE_FAILURE_DECOMPOSITION"
V118 = ROOT / "outputs/v21/V21.118_D_R2_REPEATED_LOSER_AWARE_DESIGN"
V118_R1 = ROOT / "outputs/v21/V21.118_R1_D_R2C_OVERFIT_GUARD_AND_FORWARD_TRACKING"
V119 = ROOT / "outputs/v21/V21.119_FORWARD_MATURITY_UPDATE_FOR_ABCD_AND_D_R2C"
V120 = ROOT / "outputs/v21/V21.120_CANONICAL_PRICE_REFRESH_AND_MATURITY_GATE"

PRICE = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
BENCH = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"

ABCD = V116 / "daily_ABCD_top50_full_ledger.csv"
D_R2C_MEMBERS = V118 / "d_r2_top20_top50_membership.csv"
V118_REDUCTION = V118 / "d_r2_repeated_loser_reduction.csv"
V117_R1_LOSERS = V117_R1 / "d_repeated_loser_attribution.csv"
V118_R1_MANIFEST = V118_R1 / "V21.118_R1_manifest.json"
V119_PANEL = V119 / "forward_maturity_by_date_horizon.csv"
V120_MANIFEST = V120 / "V21.120_manifest.json"

STRATEGIES = [
    "A1_BASELINE_CONTROL",
    "B_STATIC_MOMENTUM_BLEND",
    "C_DYNAMIC_MOMENTUM_BLEND",
    "D_WEIGHT_OPTIMIZED_R1",
    "D_R2C_BC_CONFIRMATION_OVERLAY",
]
HORIZONS = [1, 3, 5, 10, 20]
TOP_NS = [20, 50]
NEW_BUCKET = "NEWLY_MATURED_AFTER_V21_120_REFRESH"
OLD_BUCKET = "OLD_OR_DESIGN_WINDOW"
UNMATURED_BUCKET = "STILL_UNMATURED"
PAIRS = [
    ("D_R2C_BC_CONFIRMATION_OVERLAY", "D_WEIGHT_OPTIMIZED_R1"),
    ("D_R2C_BC_CONFIRMATION_OVERLAY", "A1_BASELINE_CONTROL"),
    ("D_R2C_BC_CONFIRMATION_OVERLAY", "B_STATIC_MOMENTUM_BLEND"),
    ("D_R2C_BC_CONFIRMATION_OVERLAY", "C_DYNAMIC_MOMENTUM_BLEND"),
    ("D_WEIGHT_OPTIMIZED_R1", "A1_BASELINE_CONTROL"),
    ("D_WEIGHT_OPTIMIZED_R1", "B_STATIC_MOMENTUM_BLEND"),
    ("D_WEIGHT_OPTIMIZED_R1", "C_DYNAMIC_MOMENTUM_BLEND"),
    ("B_STATIC_MOMENTUM_BLEND", "C_DYNAMIC_MOMENTUM_BLEND"),
]


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    if fields is None:
        fields = list(rows[0].keys()) if rows else ["empty"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def required_missing() -> list[str]:
    required = [
        ABCD,
        D_R2C_MEMBERS,
        V118_REDUCTION,
        V117_R1_LOSERS,
        V118_R1_MANIFEST,
        V119_PANEL,
        V120_MANIFEST,
        PRICE,
    ]
    return [rel(path) for path in required if not path.is_file()]


def load_prices() -> tuple[dict[tuple[str, str], float], list[str], str]:
    frames = []
    for path in [PRICE, BENCH]:
        if not path.is_file():
            continue
        df = pd.read_csv(path, usecols=["symbol", "date", "close", "adjusted_close"], low_memory=False)
        df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        close = pd.to_numeric(df["close"], errors="coerce")
        adjusted = pd.to_numeric(df["adjusted_close"], errors="coerce")
        df["px"] = adjusted.where(adjusted.notna(), close)
        frames.append(df[["symbol", "date", "px"]])
    if not frames:
        return {}, [], ""
    prices = pd.concat(frames, ignore_index=True).dropna(subset=["symbol", "date", "px"])
    prices = prices.drop_duplicates(["symbol", "date"], keep="last")
    prices["date_str"] = prices["date"].dt.strftime("%Y-%m-%d")
    dates = sorted(d for d in prices["date_str"].unique() if pd.Timestamp(d).weekday() < 5 and d != "2026-06-19")
    return {(r["symbol"], r["date_str"]): float(r["px"]) for r in prices.to_dict("records")}, dates, max(dates) if dates else ""


def end_date(as_of: str, horizon_days: int, dates: list[str]) -> tuple[bool, str]:
    if as_of not in dates:
        return False, ""
    end_idx = dates.index(as_of) + horizon_days
    if end_idx >= len(dates):
        return False, ""
    return True, dates[end_idx]


def px_return(ticker: str, start: str, end: str, prices: dict[tuple[str, str], float]) -> float:
    start_px = prices.get((ticker, start))
    end_px = prices.get((ticker, end))
    if start_px is None or end_px is None or start_px == 0:
        return math.nan
    return end_px / start_px - 1.0


def summary_returns(tickers: list[str], start: str, end: str, prices: dict[tuple[str, str], float]) -> dict[str, Any]:
    values = []
    missing = 0
    details = []
    for ticker in tickers:
        value = px_return(ticker, start, end, prices)
        if pd.isna(value):
            missing += 1
        else:
            values.append(value)
            details.append((ticker, value))
    if not values:
        return {
            "valid_price_count": 0,
            "missing_price_count": missing,
            "equal_weight_return": math.nan,
            "median_member_return": math.nan,
            "hit_rate": math.nan,
            "best_contributor": "",
            "worst_contributor": "",
        }
    best = max(details, key=lambda item: item[1])
    worst = min(details, key=lambda item: item[1])
    series = pd.Series(values)
    return {
        "valid_price_count": int(len(values)),
        "missing_price_count": int(missing),
        "equal_weight_return": float(series.mean()),
        "median_member_return": float(series.median()),
        "hit_rate": float((series > 0).sum() / len(series)),
        "best_contributor": best[0],
        "worst_contributor": worst[0],
    }


def prior_v119_matured_keys() -> set[tuple[str, str, int, str]]:
    old = pd.read_csv(V119_PANEL, low_memory=False)
    old = old[old["matured"].astype(str).str.upper().eq("TRUE")]
    return {
        (str(row["ranking_date"]), str(row["strategy"]), int(row["top_n"]), str(row["horizon"]))
        for row in old.to_dict("records")
    }


def build_memberships() -> dict[tuple[str, str, int], list[str]]:
    memberships: dict[tuple[str, str, int], list[str]] = {}
    abcd = pd.read_csv(ABCD, low_memory=False)
    abcd["rank"] = pd.to_numeric(abcd["rank"], errors="coerce")
    abcd["ticker"] = abcd["ticker"].astype(str).str.upper().str.strip()
    for (as_of, strategy), group in abcd.groupby(["as_of_date", "strategy"], sort=True):
        for topn in TOP_NS:
            top = group[group["rank"].le(topn)].sort_values("rank")
            memberships[(str(as_of), str(strategy), topn)] = list(top["ticker"])

    r2c = pd.read_csv(D_R2C_MEMBERS, low_memory=False)
    r2c = r2c[r2c["candidate_variant"].eq("D_R2C_BC_CONFIRMATION_OVERLAY")].copy()
    r2c["rank"] = pd.to_numeric(r2c["rank"], errors="coerce")
    r2c["ticker"] = r2c["ticker"].astype(str).str.upper().str.strip()
    for as_of, group in r2c.groupby("as_of_date", sort=True):
        for topn in TOP_NS:
            top = group[group["rank"].le(topn)].sort_values("rank")
            memberships[(str(as_of), "D_R2C_BC_CONFIRMATION_OVERLAY", topn)] = list(top["ticker"])
    return memberships


def pairwise(rows: pd.DataFrame, bucket: str | None, label: str) -> pd.DataFrame:
    subset = rows[rows["matured"].eq(True)].copy()
    if bucket is not None:
        subset = subset[subset["observation_bucket"].eq(bucket)]
    result = []
    for topn in TOP_NS:
        for horizon in [f"{x}D" for x in HORIZONS]:
            for left, right in PAIRS:
                left_rows = subset[
                    subset["strategy"].eq(left)
                    & subset["top_n"].eq(topn)
                    & subset["horizon"].eq(horizon)
                ]
                right_rows = subset[
                    subset["strategy"].eq(right)
                    & subset["top_n"].eq(topn)
                    & subset["horizon"].eq(horizon)
                ]
                merged = left_rows.merge(right_rows, on=["ranking_date", "top_n", "horizon"], suffixes=("_left", "_right"))
                diffs = (merged["equal_weight_return_left"] - merged["equal_weight_return_right"]).dropna()
                result.append({
                    "observation_bucket": label,
                    "comparison": f"{left}_vs_{right}",
                    "left_strategy": left,
                    "right_strategy": right,
                    "top_n": topn,
                    "horizon": horizon,
                    "win_count": int((diffs > 0).sum()),
                    "loss_count": int((diffs < 0).sum()),
                    "tie_count": int((diffs == 0).sum()),
                    "win_rate": float((diffs > 0).sum() / len(diffs)) if len(diffs) else math.nan,
                    "average_excess_return": float(diffs.mean()) if len(diffs) else math.nan,
                    "median_excess_return": float(diffs.median()) if len(diffs) else math.nan,
                    "available_observations": int(len(diffs)),
                })
            for benchmark in ["QQQ", "SOXX"]:
                strategy_rows = subset[
                    subset["strategy"].eq("D_R2C_BC_CONFIRMATION_OVERLAY")
                    & subset["top_n"].eq(topn)
                    & subset["horizon"].eq(horizon)
                ]
                values = strategy_rows[f"excess_vs_{benchmark}"].dropna()
                result.append({
                    "observation_bucket": label,
                    "comparison": f"D_R2C_BC_CONFIRMATION_OVERLAY_vs_{benchmark}",
                    "left_strategy": "D_R2C_BC_CONFIRMATION_OVERLAY",
                    "right_strategy": benchmark,
                    "top_n": topn,
                    "horizon": horizon,
                    "win_count": int((values > 0).sum()),
                    "loss_count": int((values < 0).sum()),
                    "tie_count": int((values == 0).sum()),
                    "win_rate": float((values > 0).sum() / len(values)) if len(values) else math.nan,
                    "average_excess_return": float(values.mean()) if len(values) else math.nan,
                    "median_excess_return": float(values.median()) if len(values) else math.nan,
                    "available_observations": int(len(values)),
                })
    return pd.DataFrame(result)


def aggregate_metric(pair: pd.DataFrame, comparison: str, topn: int, field: str = "win_rate") -> float:
    sub = pair[(pair["comparison"].eq(comparison)) & (pair["top_n"].eq(topn)) & (pair["available_observations"] > 0)]
    return float(sub[field].mean()) if not sub.empty else math.nan


def repeated_loser_update(panel: pd.DataFrame, memberships: dict[tuple[str, str, int], list[str]]) -> tuple[list[dict[str, Any]], bool]:
    reduction = pd.read_csv(V118_REDUCTION, low_memory=False)
    r2c_red = reduction[reduction["candidate_variant"].eq("D_R2C_BC_CONFIRMATION_OVERLAY")].iloc[0]
    original_count = int(r2c_red["original_D_repeated_loser_count"])
    variant_count = int(r2c_red["variant_repeated_loser_count"])
    reduction_amount = int(r2c_red["reduction_amount"])
    meaningful = reduction_amount >= max(3, int(original_count * 0.2))

    losers = pd.read_csv(V117_R1_LOSERS, low_memory=False)
    loser_set = set(losers["ticker"].astype(str).str.upper().str.strip())
    new_d = panel[
        panel["observation_bucket"].eq(NEW_BUCKET)
        & panel["matured"].eq(True)
        & panel["strategy"].eq("D_WEIGHT_OPTIMIZED_R1")
        & panel["top_n"].eq(20)
    ].copy()
    contribution_rows = []
    for row in new_d.to_dict("records"):
        tickers = memberships.get((str(row["ranking_date"]), "D_WEIGHT_OPTIMIZED_R1", 20), [])
        repeated = [ticker for ticker in tickers if ticker in loser_set]
        repeated_returns = []
        for ticker in repeated:
            value = px_return(ticker, str(row["start_date"]), str(row["end_date"]), PRICE_CACHE)
            if not pd.isna(value):
                repeated_returns.append(value)
        contribution_rows.append({
            "ranking_date": row["ranking_date"],
            "horizon": row["horizon"],
            "top_n": 20,
            "repeated_loser_member_count": len(repeated),
            "repeated_loser_valid_return_count": len(repeated_returns),
            "repeated_loser_average_return_new_maturity_only": float(pd.Series(repeated_returns).mean()) if repeated_returns else math.nan,
            "repeated_loser_worst_return_new_maturity_only": float(min(repeated_returns)) if repeated_returns else math.nan,
            "repeated_loser_tickers": "|".join(repeated),
        })

    if contribution_rows:
        avg_drag = pd.Series([r["repeated_loser_average_return_new_maturity_only"] for r in contribution_rows]).dropna()
        worst_drag = pd.Series([r["repeated_loser_worst_return_new_maturity_only"] for r in contribution_rows]).dropna()
        new_avg = float(avg_drag.mean()) if not avg_drag.empty else math.nan
        new_worst = float(worst_drag.min()) if not worst_drag.empty else math.nan
    else:
        new_avg = math.nan
        new_worst = math.nan

    rows = [{
        "original_D_repeated_loser_count": original_count,
        "D_R2C_repeated_loser_count": variant_count,
        "repeated_loser_reduction": reduction_amount,
        "repeated_loser_reduction_meaningful": meaningful,
        "newly_introduced_repeated_losers": "",
        "removed_repeated_losers": str(r2c_red.get("worst_repeated_losers_removed_or_downranked", "")),
        "repeated_loser_overlap": variant_count,
        "newly_matured_repeated_loser_observation_count": len(contribution_rows),
        "newly_matured_repeated_loser_average_return": new_avg,
        "newly_matured_repeated_loser_worst_return": new_worst,
        "newly_matured_repeated_loser_detail": json.dumps(contribution_rows, default=str),
    }]
    return rows, meaningful


def blocked_manifest(missing: list[str]) -> dict[str, Any]:
    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": "BLOCKED_V21_119_R1_MISSING_REQUIRED_INPUTS",
        "DECISION": "DO_NOT_USE_AFTER_REFRESH_MATURITY_UPDATE",
        "missing_inputs": missing,
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "D_R2C_official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
    }
    write_json(OUT / "V21.119_R1_manifest.json", manifest)
    (OUT / "V21.119_R1_forward_maturity_after_refresh_report.txt").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return manifest


PRICE_CACHE: dict[tuple[str, str], float] = {}


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    missing = required_missing()
    if missing:
        return blocked_manifest(missing)

    v120_manifest = json.loads(V120_MANIFEST.read_text(encoding="utf-8"))
    v118r1_manifest = json.loads(V118_R1_MANIFEST.read_text(encoding="utf-8"))
    prices, dates, latest = load_prices()
    global PRICE_CACHE
    PRICE_CACHE = prices

    v120_latest = str(v120_manifest.get("latest_price_date_after_refresh", ""))
    v120_new_count = int(v120_manifest.get("newly_matured_observation_count", 0))
    prerequisite_ok = v120_latest >= "2026-06-26" and v120_new_count == 30 and latest >= "2026-06-26"

    memberships = build_memberships()
    prior_keys = prior_v119_matured_keys()
    rows = []
    for (as_of, strategy, topn), tickers in sorted(memberships.items()):
        for horizon_days in HORIZONS:
            horizon = f"{horizon_days}D"
            matured, end = end_date(as_of, horizon_days, dates)
            key = (as_of, strategy, topn, horizon)
            if matured and key in prior_keys:
                bucket = OLD_BUCKET
            elif matured:
                bucket = NEW_BUCKET
            else:
                bucket = UNMATURED_BUCKET
            row = {
                "ranking_date": as_of,
                "strategy": strategy,
                "top_n": topn,
                "horizon": horizon,
                "start_date": as_of,
                "end_date": end,
                "matured": matured,
                "observation_bucket": bucket,
                "member_count": len(tickers),
            }
            if matured:
                stats = summary_returns(tickers, as_of, end, prices)
                qqq = px_return("QQQ", as_of, end, prices)
                soxx = px_return("SOXX", as_of, end, prices)
                row.update(stats)
                row.update({
                    "benchmark_QQQ_return": qqq,
                    "benchmark_SOXX_return": soxx,
                    "excess_vs_QQQ": stats["equal_weight_return"] - qqq if not pd.isna(qqq) else math.nan,
                    "excess_vs_SOXX": stats["equal_weight_return"] - soxx if not pd.isna(soxx) else math.nan,
                })
            else:
                row.update({
                    "valid_price_count": 0,
                    "missing_price_count": len(tickers),
                    "equal_weight_return": math.nan,
                    "median_member_return": math.nan,
                    "hit_rate": math.nan,
                    "best_contributor": "",
                    "worst_contributor": "",
                    "benchmark_QQQ_return": math.nan,
                    "benchmark_SOXX_return": math.nan,
                    "excess_vs_QQQ": math.nan,
                    "excess_vs_SOXX": math.nan,
                })
            rows.append(row)

    panel = pd.DataFrame(rows)
    panel.to_csv(OUT / "forward_maturity_by_date_horizon_after_refresh.csv", index=False)
    all_pair = pairwise(panel, None, "ALL_MATURED_AFTER_REFRESH")
    new_pair = pairwise(panel, NEW_BUCKET, NEW_BUCKET)
    all_pair.to_csv(OUT / "pairwise_winrate_all_matured_after_refresh.csv", index=False)
    new_pair.to_csv(OUT / "pairwise_winrate_new_maturity_only_after_refresh.csv", index=False)

    repeated_rows, repeated_meaningful = repeated_loser_update(panel, memberships)
    write_csv(OUT / "repeated_loser_after_refresh_update.csv", repeated_rows)

    all_matured_count = int(panel["matured"].sum())
    newly_count = int(panel["observation_bucket"].eq(NEW_BUCKET).sum())
    still_unmatured = int(panel["observation_bucket"].eq(UNMATURED_BUCKET).sum())

    d2c_d_all = aggregate_metric(all_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_D_WEIGHT_OPTIMIZED_R1", 20)
    d2c_d_new = aggregate_metric(new_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_D_WEIGHT_OPTIMIZED_R1", 20)
    d2c_a1_new = aggregate_metric(new_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_A1_BASELINE_CONTROL", 20)
    d2c_b_new = aggregate_metric(new_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_B_STATIC_MOMENTUM_BLEND", 20)
    d2c_c_new = aggregate_metric(new_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_C_DYNAMIC_MOMENTUM_BLEND", 20)
    d2c_qqq_new = aggregate_metric(new_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_QQQ", 20, "average_excess_return")
    d2c_soxx_new = aggregate_metric(new_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_SOXX", 20, "average_excess_return")
    d2c_d_new_top50 = aggregate_metric(new_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_D_WEIGHT_OPTIMIZED_R1", 50)
    d2c_a1_new_top50 = aggregate_metric(new_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_A1_BASELINE_CONTROL", 50)
    d2c_b_new_top50 = aggregate_metric(new_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_B_STATIC_MOMENTUM_BLEND", 50)
    d2c_c_new_top50 = aggregate_metric(new_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_C_DYNAMIC_MOMENTUM_BLEND", 50)
    d2c_qqq_new_top50 = aggregate_metric(new_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_QQQ", 50, "average_excess_return")
    d2c_soxx_new_top50 = aggregate_metric(new_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_SOXX", 50, "average_excess_return")

    bc_better = bool(
        (not pd.isna(d2c_b_new) and d2c_b_new <= 0.5)
        or (not pd.isna(d2c_c_new) and d2c_c_new <= 0.5)
    )
    soxx_alpha = bool(not pd.isna(d2c_soxx_new) and d2c_soxx_new >= 0)
    overfit_likely = bool(
        pd.isna(d2c_d_new)
        or d2c_d_new <= 0.5
        or (not pd.isna(d2c_a1_new) and d2c_a1_new <= 0.5)
        or bc_better
        or not repeated_meaningful
        or not soxx_alpha
    )
    overfit_warning = overfit_likely

    prior_overfit = bool(v118r1_manifest.get("overfit_warning", True))
    if not overfit_warning:
        overfit_status = "RESOLVED"
    elif d2c_d_new > 0.5 and not pd.isna(d2c_d_new):
        overfit_status = "REDUCED_BUT_NOT_RESOLVED" if prior_overfit else "UNCHANGED"
    elif d2c_d_new < 0.5 and not pd.isna(d2c_d_new):
        overfit_status = "WORSENED"
    else:
        overfit_status = "UNCHANGED"

    robustness_rows = [{
        "source_v21_120_latest_price_date_after_refresh": v120_latest,
        "source_v21_120_newly_matured_observation_count": v120_new_count,
        "newly_matured_observation_count": newly_count,
        "D_R2C_vs_original_D_Top20_win_rate_newly_matured_only": d2c_d_new,
        "D_R2C_vs_A1_Top20_win_rate_newly_matured_only": d2c_a1_new,
        "D_R2C_vs_B_Top20_win_rate_newly_matured_only": d2c_b_new,
        "D_R2C_vs_C_Top20_win_rate_newly_matured_only": d2c_c_new,
        "D_R2C_vs_QQQ_Top20_average_excess_newly_matured_only": d2c_qqq_new,
        "D_R2C_vs_SOXX_Top20_average_excess_newly_matured_only": d2c_soxx_new,
        "D_R2C_vs_original_D_Top50_win_rate_newly_matured_only": d2c_d_new_top50,
        "D_R2C_vs_A1_Top50_win_rate_newly_matured_only": d2c_a1_new_top50,
        "D_R2C_vs_B_Top50_win_rate_newly_matured_only": d2c_b_new_top50,
        "D_R2C_vs_C_Top50_win_rate_newly_matured_only": d2c_c_new_top50,
        "D_R2C_vs_QQQ_Top50_average_excess_newly_matured_only": d2c_qqq_new_top50,
        "D_R2C_vs_SOXX_Top50_average_excess_newly_matured_only": d2c_soxx_new_top50,
    }]
    write_csv(OUT / "d_r2c_new_maturity_robustness.csv", robustness_rows)
    write_csv(OUT / "d_r2c_overfit_guard_after_refresh.csv", [{
        "newly_matured_evidence_available": newly_count > 0,
        "overfit_warning": overfit_warning,
        "overfit_likely": overfit_likely,
        "overfit_status": overfit_status,
        "improvement_reproduced_vs_original_D": bool(not pd.isna(d2c_d_new) and d2c_d_new > 0.5),
        "still_loses_to_B_or_C": bc_better,
        "SOXX_alpha_confirmed": soxx_alpha,
        "repeated_loser_reduction_meaningful": repeated_meaningful,
        "no_parameter_optimization_performed": True,
    }])
    write_csv(OUT / "bc_vs_d_r2c_after_refresh_comparison.csv", [{
        "B_or_C_currently_better_than_D_R2C": bc_better,
        "D_R2C_vs_B_Top20_win_rate_newly_matured_only": d2c_b_new,
        "D_R2C_vs_C_Top20_win_rate_newly_matured_only": d2c_c_new,
        "D_R2C_should_not_replace_B_or_C": bc_better,
        "BC_confirmation_helping_or_masking": "MASKING_D_WEAKNESS" if bc_better else "HELPING_D_R2C",
    }])
    write_csv(OUT / "benchmark_sanity_after_refresh.csv", [{
        "D_R2C_vs_QQQ_Top20_average_excess_newly_matured_only": d2c_qqq_new,
        "D_R2C_vs_SOXX_Top20_average_excess_newly_matured_only": d2c_soxx_new,
        "SOXX_alpha_confirmed": soxx_alpha,
        "stock_selection_alpha_not_confirmed": not soxx_alpha,
    }])

    if not prerequisite_ok:
        final_status = "BLOCKED_V21_119_R1_MISSING_REQUIRED_INPUTS"
        decision = "DO_NOT_USE_AFTER_REFRESH_MATURITY_UPDATE"
    elif (
        d2c_d_new > 0.5
        and min(d2c_a1_new, d2c_b_new, d2c_c_new) > 0.5
        and repeated_meaningful
        and (pd.isna(d2c_soxx_new) or d2c_soxx_new >= 0)
    ):
        final_status = "PASS_V21_119_R1_D_R2C_OVERFIT_REDUCED"
        decision = "D_R2C_OVERFIT_REDUCED_RESEARCH_ONLY"
    elif d2c_d_new > 0.5:
        final_status = "PARTIAL_PASS_V21_119_R1_D_R2C_STILL_TRACKING"
        decision = "D_R2C_STILL_TRACKING_AFTER_REFRESH_RESEARCH_ONLY"
    elif d2c_d_new < 0.5 and not pd.isna(d2c_d_new):
        final_status = "WARN_V21_119_R1_D_R2C_OVERFIT_WORSENED"
        decision = "D_R2C_OVERFIT_WORSENED_AFTER_REFRESH_RESEARCH_ONLY"
    else:
        final_status = "WARN_V21_119_R1_D_R2C_OVERFIT_UNCHANGED"
        decision = "D_R2C_OVERFIT_UNCHANGED_AFTER_REFRESH_RESEARCH_ONLY"

    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_used": latest,
        "source_v21_120_status": v120_manifest.get("FINAL_STATUS", ""),
        "source_v21_120_newly_matured_observation_count": v120_new_count,
        "source_v21_120_latest_price_date_after_refresh": v120_latest,
        "strategies_evaluated": STRATEGIES + ["QQQ", "SOXX"],
        "ranking_dates_evaluated": sorted({key[0] for key in memberships}),
        "all_matured_observation_count": all_matured_count,
        "newly_matured_observation_count": newly_count,
        "still_unmatured_observation_count": still_unmatured,
        "D_R2C_vs_original_D_Top20_win_rate_all_matured": d2c_d_all,
        "D_R2C_vs_original_D_Top20_win_rate_newly_matured_only": d2c_d_new,
        "D_R2C_vs_A1_Top20_win_rate_newly_matured_only": d2c_a1_new,
        "D_R2C_vs_B_Top20_win_rate_newly_matured_only": d2c_b_new,
        "D_R2C_vs_C_Top20_win_rate_newly_matured_only": d2c_c_new,
        "D_R2C_vs_QQQ_average_excess_newly_matured_only": d2c_qqq_new,
        "D_R2C_vs_SOXX_average_excess_newly_matured_only": d2c_soxx_new,
        "repeated_loser_reduction_meaningful": repeated_meaningful,
        "B_or_C_currently_better_than_D_R2C": bc_better,
        "overfit_warning": overfit_warning,
        "overfit_status": overfit_status,
        "SOXX_alpha_confirmed": soxx_alpha,
        "D_R2C_official_adoption_allowed": False,
        "broker_action_allowed": False,
        "further_maturity_tracking_required": bool(overfit_warning),
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "research_only": True,
        "no_parameter_optimization_performed": True,
        "new_variant_generated": False,
        "D_R2C_frozen_variant_only": True,
        "required_v21_120_refresh_confirmed": prerequisite_ok,
    }
    write_json(OUT / "V21.119_R1_manifest.json", manifest)

    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"latest_price_date_used={latest}",
        f"source V21.120 status={v120_manifest.get('FINAL_STATUS', '')}",
        f"source V21.120 newly_matured_observation_count={v120_new_count}",
        f"strategies evaluated={', '.join(manifest['strategies_evaluated'])}",
        f"ranking_dates_evaluated={', '.join(manifest['ranking_dates_evaluated'])}",
        f"all_matured_observation_count={all_matured_count}",
        f"newly_matured_observation_count={newly_count}",
        f"still_unmatured_observation_count={still_unmatured}",
        f"D_R2C vs original D Top20 win rate, all matured={d2c_d_all}",
        f"D_R2C vs original D Top20 win rate, newly matured only={d2c_d_new}",
        f"D_R2C vs A1/B/C Top20 win rates, newly matured only={d2c_a1_new}/{d2c_b_new}/{d2c_c_new}",
        f"D_R2C vs QQQ/SOXX average excess, newly matured only={d2c_qqq_new}/{d2c_soxx_new}",
        f"repeated loser reduction meaningful={repeated_meaningful}",
        f"B or C currently better than D_R2C={bc_better}",
        f"overfit warning={overfit_warning}",
        f"overfit status={overfit_status}",
        f"SOXX alpha confirmed={soxx_alpha}",
        "D_R2C official adoption allowed=false",
        "broker action allowed=false",
        f"further maturity tracking required={bool(overfit_warning)}",
    ]
    (OUT / "V21.119_R1_forward_maturity_after_refresh_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, default=str))
    return manifest


if __name__ == "__main__":
    run()
