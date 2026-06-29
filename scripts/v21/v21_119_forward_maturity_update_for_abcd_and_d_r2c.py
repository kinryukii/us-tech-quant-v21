#!/usr/bin/env python
"""V21.119 forward maturity update for frozen ABCD and D-R2C."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.119_FORWARD_MATURITY_UPDATE_FOR_ABCD_AND_D_R2C"
OUT = ROOT / "outputs/v21/V21.119_FORWARD_MATURITY_UPDATE_FOR_ABCD_AND_D_R2C"

V116 = ROOT / "outputs/v21/V21.116_DAILY_TOP50_FULL_DATA_LEDGER_20260616_TO_LATEST"
V117 = ROOT / "outputs/v21/V21.117_EARLY_FORWARD_VALIDITY_EVALUATOR"
V117_R1 = ROOT / "outputs/v21/V21.117_R1_D_EARLY_EDGE_FAILURE_DECOMPOSITION"
V118 = ROOT / "outputs/v21/V21.118_D_R2_REPEATED_LOSER_AWARE_DESIGN"
V118_R1 = ROOT / "outputs/v21/V21.118_R1_D_R2C_OVERFIT_GUARD_AND_FORWARD_TRACKING"
PRICE = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
BENCH = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"

ABCD = V116 / "daily_ABCD_top50_full_ledger.csv"
D_R2C_MEMBERS = V118 / "d_r2_top20_top50_membership.csv"
V117_FWD = V117 / "early_forward_by_date_horizon.csv"
V118_FWD = V118 / "d_r2_forward_by_date_horizon.csv"
V118_R1_MANIFEST = V118_R1 / "V21.118_R1_manifest.json"
V118_REDUCTION = V118 / "d_r2_repeated_loser_reduction.csv"

STRATEGIES = [
    "A1_BASELINE_CONTROL",
    "B_STATIC_MOMENTUM_BLEND",
    "C_DYNAMIC_MOMENTUM_BLEND",
    "D_WEIGHT_OPTIMIZED_R1",
    "D_R2C_BC_CONFIRMATION_OVERLAY",
]
BASE_STRATEGIES = STRATEGIES[:4]
HORIZONS = [1, 3, 5, 10, 20]
TOP_NS = [20, 50]
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
    return [rel(p) for p in [ABCD, D_R2C_MEMBERS, V117_FWD, V118_FWD, V118_R1_MANIFEST, V118_REDUCTION, PRICE] if not p.is_file()]


def load_prices() -> tuple[dict[tuple[str, str], float], list[str], str]:
    frames = []
    for path in [PRICE, BENCH]:
        if not path.is_file():
            continue
        df = pd.read_csv(path, usecols=["symbol", "date", "close", "adjusted_close"], low_memory=False)
        df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        adj = pd.to_numeric(df["adjusted_close"], errors="coerce")
        close = pd.to_numeric(df["close"], errors="coerce")
        df["px"] = adj.where(adj.notna(), close)
        frames.append(df[["symbol", "date", "px"]])
    prices = pd.concat(frames, ignore_index=True).dropna(subset=["symbol", "date", "px"])
    prices = prices.drop_duplicates(["symbol", "date"], keep="last")
    prices["date_str"] = prices["date"].dt.strftime("%Y-%m-%d")
    dates = sorted(d for d in prices["date_str"].unique() if pd.Timestamp(d).weekday() < 5 and d != "2026-06-19")
    return {(r["symbol"], r["date_str"]): float(r["px"]) for r in prices.to_dict("records")}, dates, max(dates) if dates else ""


def end_date(as_of: str, h: int, dates: list[str]) -> tuple[bool, str]:
    if as_of not in dates:
        return False, ""
    idx = dates.index(as_of) + h
    if idx >= len(dates):
        return False, ""
    return True, dates[idx]


def px_return(ticker: str, start: str, end: str, prices: dict[tuple[str, str], float]) -> float:
    sp = prices.get((ticker, start))
    ep = prices.get((ticker, end))
    if sp is None or ep is None or sp == 0:
        return math.nan
    return ep / sp - 1.0


def summary_returns(tickers: list[str], start: str, end: str, prices: dict[tuple[str, str], float]) -> dict[str, Any]:
    vals = []
    missing = 0
    details = []
    for ticker in tickers:
        value = px_return(ticker, start, end, prices)
        if pd.isna(value):
            missing += 1
        else:
            vals.append(value)
            details.append((ticker, value))
    if not vals:
        return {"valid_price_count": 0, "missing_price_count": missing, "equal_weight_return": math.nan, "median_member_return": math.nan, "hit_rate": math.nan, "best_contributor": "", "worst_contributor": ""}
    best = max(details, key=lambda x: x[1])
    worst = min(details, key=lambda x: x[1])
    return {
        "valid_price_count": len(vals),
        "missing_price_count": missing,
        "equal_weight_return": float(pd.Series(vals).mean()),
        "median_member_return": float(pd.Series(vals).median()),
        "hit_rate": float(sum(1 for v in vals if v > 0) / len(vals)),
        "best_contributor": best[0],
        "worst_contributor": worst[0],
    }


def prior_matured_keys() -> set[tuple[str, str, int, str]]:
    keys: set[tuple[str, str, int, str]] = set()
    old = pd.read_csv(V117_FWD, low_memory=False)
    old = old[old["matured"].astype(str).str.upper().eq("TRUE")]
    for row in old.to_dict("records"):
        keys.add((str(row["as_of_date"]), str(row["strategy"]), int(row["top_n"]), str(row["horizon"])))
    r2c = pd.read_csv(V118_FWD, low_memory=False)
    r2c = r2c[(r2c["candidate_variant"].eq("D_R2C_BC_CONFIRMATION_OVERLAY")) & (r2c["matured"].astype(str).str.upper().eq("TRUE"))]
    for row in r2c.to_dict("records"):
        keys.add((str(row["as_of_date"]), "D_R2C_BC_CONFIRMATION_OVERLAY", int(row["top_n"]), str(row["horizon"])))
    return keys


def build_memberships() -> dict[tuple[str, str, int], list[str]]:
    out: dict[tuple[str, str, int], list[str]] = {}
    abcd = pd.read_csv(ABCD, low_memory=False)
    abcd["rank"] = pd.to_numeric(abcd["rank"], errors="coerce")
    abcd["ticker"] = abcd["ticker"].astype(str).str.upper().str.strip()
    for (as_of, strategy), group in abcd.groupby(["as_of_date", "strategy"], sort=True):
        for topn in TOP_NS:
            out[(str(as_of), str(strategy), topn)] = list(group[group["rank"].le(topn)].sort_values("rank")["ticker"])
    r2c = pd.read_csv(D_R2C_MEMBERS, low_memory=False)
    r2c = r2c[r2c["candidate_variant"].eq("D_R2C_BC_CONFIRMATION_OVERLAY")].copy()
    r2c["rank"] = pd.to_numeric(r2c["rank"], errors="coerce")
    r2c["ticker"] = r2c["ticker"].astype(str).str.upper().str.strip()
    for as_of, group in r2c.groupby("as_of_date", sort=True):
        for topn in TOP_NS:
            out[(str(as_of), "D_R2C_BC_CONFIRMATION_OVERLAY", topn)] = list(group[group["rank"].le(topn)].sort_values("rank")["ticker"])
    return out


def pairwise(rows: pd.DataFrame, partition: str) -> pd.DataFrame:
    m = rows[(rows["matured"].eq(True)) & (rows["maturity_partition"].eq(partition))].copy()
    result = []
    for topn in TOP_NS:
        for h in [f"{x}D" for x in HORIZONS]:
            for left, right in PAIRS:
                l = m[(m["strategy"].eq(left)) & (m["top_n"].eq(topn)) & (m["horizon"].eq(h))]
                r = m[(m["strategy"].eq(right)) & (m["top_n"].eq(topn)) & (m["horizon"].eq(h))]
                merged = l.merge(r, on=["ranking_date", "top_n", "horizon"], suffixes=("_left", "_right"))
                diffs = (merged["equal_weight_return_left"] - merged["equal_weight_return_right"]).dropna()
                result.append({
                    "partition": partition,
                    "comparison": f"{left}_vs_{right}",
                    "left_strategy": left,
                    "right_strategy": right,
                    "top_n": topn,
                    "horizon": h,
                    "win_count": int((diffs > 0).sum()),
                    "loss_count": int((diffs < 0).sum()),
                    "tie_count": int((diffs == 0).sum()),
                    "win_rate": float((diffs > 0).sum() / len(diffs)) if len(diffs) else math.nan,
                    "average_excess_return": float(diffs.mean()) if len(diffs) else math.nan,
                    "available_observations": int(len(diffs)),
                })
            for bench in ["QQQ", "SOXX"]:
                l = m[(m["strategy"].eq("D_R2C_BC_CONFIRMATION_OVERLAY")) & (m["top_n"].eq(topn)) & (m["horizon"].eq(h))]
                vals = l[f"excess_vs_{bench}"].dropna()
                result.append({
                    "partition": partition,
                    "comparison": f"D_R2C_BC_CONFIRMATION_OVERLAY_vs_{bench}",
                    "left_strategy": "D_R2C_BC_CONFIRMATION_OVERLAY",
                    "right_strategy": bench,
                    "top_n": topn,
                    "horizon": h,
                    "win_count": int((vals > 0).sum()),
                    "loss_count": int((vals < 0).sum()),
                    "tie_count": int((vals == 0).sum()),
                    "win_rate": float((vals > 0).sum() / len(vals)) if len(vals) else math.nan,
                    "average_excess_return": float(vals.mean()) if len(vals) else math.nan,
                    "available_observations": int(len(vals)),
                })
    return pd.DataFrame(result)


def metric(pair: pd.DataFrame, comparison: str, topn: int, field: str = "win_rate") -> float:
    sub = pair[(pair["comparison"].eq(comparison)) & (pair["top_n"].eq(topn)) & (pair["available_observations"] > 0)]
    return float(sub[field].mean()) if not sub.empty else math.nan


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    missing = required_missing()
    if missing:
        manifest = {"FINAL_STATUS": "BLOCKED_V21_119_MISSING_REQUIRED_INPUTS", "DECISION": "DO_NOT_USE_FORWARD_MATURITY_UPDATE", "missing_inputs": missing, "protected_outputs_modified": False, "official_adoption_allowed": False, "broker_action_allowed": False, "research_only": True}
        write_json(OUT / "V21.119_manifest.json", manifest)
        (OUT / "V21.119_forward_maturity_update_report.txt").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest, indent=2))
        return manifest

    v118r1 = json.loads(V118_R1_MANIFEST.read_text(encoding="utf-8"))
    prices, dates, latest = load_prices()
    memberships = build_memberships()
    old_keys = prior_matured_keys()
    rows = []
    for (as_of, strategy, topn), tickers in sorted(memberships.items()):
        for h in HORIZONS:
            horizon = f"{h}D"
            matured, end = end_date(as_of, h, dates)
            key = (as_of, strategy, topn, horizon)
            partition = "OLD_DESIGN_WINDOW" if key in old_keys else "NEWLY_MATURED" if matured else "UNMATURED"
            row = {"ranking_date": as_of, "strategy": strategy, "top_n": topn, "horizon": horizon, "start_date": as_of, "end_date": end, "matured": matured, "maturity_partition": partition, "member_count": len(tickers)}
            if matured:
                stats = summary_returns(tickers, as_of, end, prices)
                qqq = px_return("QQQ", as_of, end, prices)
                soxx = px_return("SOXX", as_of, end, prices)
                row.update(stats)
                row.update({"benchmark_QQQ_return": qqq, "benchmark_SOXX_return": soxx, "excess_vs_QQQ": stats["equal_weight_return"] - qqq if not pd.isna(qqq) else math.nan, "excess_vs_SOXX": stats["equal_weight_return"] - soxx if not pd.isna(soxx) else math.nan})
            else:
                row.update({"valid_price_count": 0, "missing_price_count": len(tickers), "equal_weight_return": math.nan, "median_member_return": math.nan, "hit_rate": math.nan, "best_contributor": "", "worst_contributor": "", "benchmark_QQQ_return": math.nan, "benchmark_SOXX_return": math.nan, "excess_vs_QQQ": math.nan, "excess_vs_SOXX": math.nan})
            rows.append(row)
    panel = pd.DataFrame(rows)
    panel.to_csv(OUT / "forward_maturity_by_date_horizon.csv", index=False)
    all_pair = pairwise(panel, "OLD_DESIGN_WINDOW")
    new_pair = pairwise(panel, "NEWLY_MATURED")
    all_pair.to_csv(OUT / "pairwise_winrate_all_matured.csv", index=False)
    new_pair.to_csv(OUT / "pairwise_winrate_new_maturity_only.csv", index=False)

    reduction = pd.read_csv(V118_REDUCTION, low_memory=False)
    r2c_red = reduction[reduction["candidate_variant"].eq("D_R2C_BC_CONFIRMATION_OVERLAY")].iloc[0]
    meaningful = int(r2c_red["reduction_amount"]) >= max(3, int(int(r2c_red["original_D_repeated_loser_count"]) * 0.2))
    repeated_rows = [{"original_D_repeated_loser_count": int(r2c_red["original_D_repeated_loser_count"]), "D_R2C_repeated_loser_count": int(r2c_red["variant_repeated_loser_count"]), "repeated_loser_reduction": int(r2c_red["reduction_amount"]), "repeated_loser_reduction_meaningful": meaningful, "newly_introduced_repeated_losers": "", "removed_repeated_losers": r2c_red.get("worst_repeated_losers_removed_or_downranked", ""), "repeated_loser_overlap": int(r2c_red["variant_repeated_loser_count"])}]
    write_csv(OUT / "repeated_loser_maturity_update.csv", repeated_rows)

    newly_count = int((panel["maturity_partition"].eq("NEWLY_MATURED")).sum())
    still_unmatured = int((panel["maturity_partition"].eq("UNMATURED")).sum())
    d2c_d_new = metric(new_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_D_WEIGHT_OPTIMIZED_R1", 20)
    d2c_a1_new = metric(new_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_A1_BASELINE_CONTROL", 20)
    d2c_b_new = metric(new_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_B_STATIC_MOMENTUM_BLEND", 20)
    d2c_c_new = metric(new_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_C_DYNAMIC_MOMENTUM_BLEND", 20)
    d2c_qqq_new = metric(new_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_QQQ", 20, "average_excess_return")
    d2c_soxx_new = metric(new_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_SOXX", 20, "average_excess_return")
    d2c_d_all = metric(all_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_D_WEIGHT_OPTIMIZED_R1", 20)

    no_new = newly_count == 0
    overfit_warning = bool(no_new or not meaningful or (not pd.isna(d2c_b_new) and d2c_b_new <= 0.5) or (not pd.isna(d2c_c_new) and d2c_c_new <= 0.5) or (not pd.isna(d2c_soxx_new) and d2c_soxx_new < 0))
    soxx_alpha = bool(not pd.isna(d2c_soxx_new) and d2c_soxx_new >= 0)
    bc_better = bool((not pd.isna(d2c_b_new) and d2c_b_new <= 0.5) or (not pd.isna(d2c_c_new) and d2c_c_new <= 0.5) or no_new)
    robustness = [{"newly_matured_observation_count": newly_count, "D_R2C_vs_original_D_win_rate_all_matured": d2c_d_all, "D_R2C_vs_original_D_win_rate_new_only": d2c_d_new, "D_R2C_vs_A1_new_only": d2c_a1_new, "D_R2C_vs_B_new_only": d2c_b_new, "D_R2C_vs_C_new_only": d2c_c_new, "D_R2C_vs_QQQ_excess_new_only": d2c_qqq_new, "D_R2C_vs_SOXX_excess_new_only": d2c_soxx_new}]
    write_csv(OUT / "d_r2c_robustness_update.csv", robustness)
    write_csv(OUT / "d_r2c_overfit_guard_update.csv", [{"no_new_maturity": no_new, "overfit_warning": overfit_warning, "repeated_loser_reduction_meaningful": meaningful, "D_R2C_improvement_disappears_in_new_maturity": bool(not pd.isna(d2c_d_new) and d2c_d_new <= 0.5)}])
    write_csv(OUT / "bc_vs_d_r2c_comparison.csv", [{"B_or_C_currently_better_than_D_R2C": bc_better, "D_R2C_vs_B_new_top20_win_rate": d2c_b_new, "D_R2C_vs_C_new_top20_win_rate": d2c_c_new, "if_C_remains_superior_do_not_replace_C": bool(not pd.isna(d2c_c_new) and d2c_c_new <= 0.5)}])
    write_csv(OUT / "benchmark_sanity_update.csv", [{"D_R2C_vs_QQQ_excess_new_only": d2c_qqq_new, "D_R2C_vs_SOXX_excess_new_only": d2c_soxx_new, "SOXX_alpha_confirmed": soxx_alpha}])

    if not no_new and d2c_d_new > 0.5 and min(d2c_a1_new, d2c_b_new, d2c_c_new) > 0.5 and meaningful and (pd.isna(d2c_soxx_new) or d2c_soxx_new >= 0):
        final_status = "PASS_V21_119_D_R2C_FORWARD_ROBUSTNESS_CONFIRMED"
        decision = "D_R2C_FORWARD_ROBUSTNESS_CONFIRMED_RESEARCH_ONLY"
    elif not no_new and d2c_d_new > 0.5:
        final_status = "PARTIAL_PASS_V21_119_D_R2C_STILL_TRACKING"
        decision = "D_R2C_STILL_TRACKING_RESEARCH_ONLY"
    else:
        final_status = "WARN_V21_119_D_R2C_OVERFIT_NOT_RESOLVED"
        decision = "D_R2C_OVERFIT_NOT_RESOLVED_RESEARCH_ONLY"
    manifest = {"stage": STAGE, "FINAL_STATUS": final_status, "DECISION": decision, "latest_price_date_used": latest, "source_v21_118_r1_status": v118r1.get("FINAL_STATUS", ""), "strategies_evaluated": STRATEGIES + ["QQQ", "SOXX"], "ranking_dates_evaluated": sorted({k[0] for k in memberships}), "all_matured_observation_count": int((panel["maturity_partition"].eq("OLD_DESIGN_WINDOW")).sum()), "newly_matured_observation_count": newly_count, "still_unmatured_observation_count": still_unmatured, "D_R2C_vs_original_D_Top20_win_rate_all_matured": d2c_d_all, "D_R2C_vs_original_D_Top20_win_rate_newly_matured_only": d2c_d_new, "D_R2C_vs_A1_Top20_win_rate_newly_matured_only": d2c_a1_new, "D_R2C_vs_B_Top20_win_rate_newly_matured_only": d2c_b_new, "D_R2C_vs_C_Top20_win_rate_newly_matured_only": d2c_c_new, "D_R2C_vs_QQQ_average_excess_newly_matured_only": d2c_qqq_new, "D_R2C_vs_SOXX_average_excess_newly_matured_only": d2c_soxx_new, "repeated_loser_reduction_meaningful": meaningful, "B_or_C_currently_better_than_D_R2C": bc_better, "overfit_warning": overfit_warning, "SOXX_alpha_confirmed": soxx_alpha, "D_R2C_official_adoption_allowed": False, "broker_action_allowed": False, "further_maturity_tracking_required": bool(no_new or overfit_warning), "protected_outputs_modified": False, "official_adoption_allowed": False, "research_only": True, "no_parameter_optimization_performed": True, "new_variant_generated": False}
    write_json(OUT / "V21.119_manifest.json", manifest)
    report = [
        f"{STAGE}",
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"latest_price_date_used={latest}",
        f"source V21.118_R1 status={v118r1.get('FINAL_STATUS', '')}",
        f"strategies evaluated={', '.join(manifest['strategies_evaluated'])}",
        f"ranking_dates_evaluated={', '.join(manifest['ranking_dates_evaluated'])}",
        f"all_matured_observation_count={manifest['all_matured_observation_count']}",
        f"newly_matured_observation_count={newly_count}",
        f"still_unmatured_observation_count={still_unmatured}",
        f"D_R2C vs original D Top20 win rate, all matured={d2c_d_all}",
        f"D_R2C vs original D Top20 win rate, newly matured only={d2c_d_new}",
        f"D_R2C vs A1/B/C Top20 win rates, newly matured only={d2c_a1_new}/{d2c_b_new}/{d2c_c_new}",
        f"D_R2C vs QQQ/SOXX average excess, newly matured only={d2c_qqq_new}/{d2c_soxx_new}",
        f"repeated loser reduction meaningful={meaningful}",
        f"B or C currently better than D_R2C={bc_better}",
        f"overfit warning={overfit_warning}",
        f"SOXX alpha confirmed={soxx_alpha}",
        "D_R2C official adoption allowed=false",
        "broker action allowed=false",
        f"further maturity tracking required={bool(no_new or overfit_warning)}",
    ]
    (OUT / "V21.119_forward_maturity_update_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, default=str))
    return manifest


if __name__ == "__main__":
    run()
