#!/usr/bin/env python
"""V21.118 D-R2 repeated-loser-aware research candidate design."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.118_D_R2_REPEATED_LOSER_AWARE_DESIGN"
OUT = ROOT / "outputs/v21/V21.118_D_R2_REPEATED_LOSER_AWARE_DESIGN"
V116 = ROOT / "outputs/v21/V21.116_DAILY_TOP50_FULL_DATA_LEDGER_20260616_TO_LATEST"
V117 = ROOT / "outputs/v21/V21.117_EARLY_FORWARD_VALIDITY_EVALUATOR"
V117_R1 = ROOT / "outputs/v21/V21.117_R1_D_EARLY_EDGE_FAILURE_DECOMPOSITION"
PRICE = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
BENCH = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"

ABCD = V116 / "daily_ABCD_top50_full_ledger.csv"
FWD = V117 / "early_forward_by_date_horizon.csv"
WORST = V117 / "d_worst_contributors.csv"
V117_MANIFEST = V117 / "V21.117_manifest.json"
R1_MANIFEST = V117_R1 / "V21.117_R1_manifest.json"
R1_LOSERS = V117_R1 / "d_repeated_loser_attribution.csv"

VARIANTS = [
    "D_R2A_REPEATED_LOSER_SOFT_PENALTY",
    "D_R2B_TOP20_COOLDOWN",
    "D_R2C_BC_CONFIRMATION_OVERLAY",
    "D_R2D_COMBINED_SOFT_PENALTY",
]
BASE_STRATEGIES = ["A1_BASELINE_CONTROL", "B_STATIC_MOMENTUM_BLEND", "C_DYNAMIC_MOMENTUM_BLEND", "D_WEIGHT_OPTIMIZED_R1"]
HORIZONS = [1, 3, 5, 10, 20]
TOP_NS = [20, 50]


def clean(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none"} else text


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


def required_ok() -> tuple[bool, list[str]]:
    missing = [rel(p) for p in [ABCD, FWD, WORST, V117_MANIFEST, R1_MANIFEST, R1_LOSERS, PRICE] if not p.is_file()]
    return not missing, missing


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
    return {(r["symbol"], r["date_str"]): float(r["px"]) for r in prices.to_dict("records")}, dates, max(dates)


def forward_end(as_of: str, horizon: int, dates: list[str]) -> tuple[bool, str]:
    if as_of not in dates:
        return False, ""
    idx = dates.index(as_of) + horizon
    if idx >= len(dates):
        return False, ""
    return True, dates[idx]


def ret(ticker: str, start: str, end: str, prices: dict[tuple[str, str], float]) -> float:
    sp = prices.get((ticker, start))
    ep = prices.get((ticker, end))
    if sp is None or ep is None or sp == 0:
        return math.nan
    return ep / sp - 1.0


def prior_loss_stats(worst: pd.DataFrame, as_of: str) -> dict[str, dict[str, Any]]:
    events = worst[(worst["end_date"].astype(str) < as_of) & (worst["member_return"] < 0)].copy()
    out: dict[str, dict[str, Any]] = {}
    for ticker, group in events.groupby("ticker"):
        out[str(ticker).upper()] = {
            "prior_loss_count": int(len(group)),
            "prior_avg_loss": float(group["member_return"].mean()),
            "prior_worst_loss": float(group["member_return"].min()),
            "prior_loss_horizons": "|".join(sorted(set(group["horizon"].astype(str)))),
        }
    return out


def adjust_rankings(ranks: pd.DataFrame, worst: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    adjusted = []
    penalties = []
    diffs = []
    membership = []
    for as_of in sorted(ranks["as_of_date"].astype(str).unique()):
        snap = ranks[ranks["as_of_date"].astype(str).eq(as_of)].copy()
        d = snap[snap["strategy"].eq("D_WEIGHT_OPTIMIZED_R1")].copy()
        b_top30 = set(snap[(snap["strategy"].eq("B_STATIC_MOMENTUM_BLEND")) & (snap["rank"].le(30))]["ticker"])
        c_top30 = set(snap[(snap["strategy"].eq("C_DYNAMIC_MOMENTUM_BLEND")) & (snap["rank"].le(30))]["ticker"])
        orig_top20 = set(d[d["rank"].le(20)]["ticker"])
        orig_top50 = set(d[d["rank"].le(50)]["ticker"])
        stats = prior_loss_stats(worst, as_of)
        for variant in VARIANTS:
            rows = []
            for row in d.to_dict("records"):
                ticker = row["ticker"]
                base_score = float(row["final_score"])
                st = stats.get(ticker, {"prior_loss_count": 0, "prior_avg_loss": 0.0, "prior_worst_loss": 0.0, "prior_loss_horizons": ""})
                soft_penalty = min(6.0, 1.5 * int(st["prior_loss_count"]) + min(2.0, abs(float(st["prior_worst_loss"])) * 10.0))
                severe = int(st["prior_loss_count"]) >= 2 or float(st["prior_worst_loss"]) <= -0.10
                bc_supported = ticker in b_top30 or ticker in c_top30
                bc_penalty = 0.0 if bc_supported else 2.5
                cooldown_penalty = 1000.0 if severe and variant == "D_R2B_TOP20_COOLDOWN" else 0.0
                if variant == "D_R2A_REPEATED_LOSER_SOFT_PENALTY":
                    penalty = soft_penalty
                elif variant == "D_R2B_TOP20_COOLDOWN":
                    penalty = 0.0
                elif variant == "D_R2C_BC_CONFIRMATION_OVERLAY":
                    penalty = bc_penalty
                else:
                    penalty = min(8.0, soft_penalty + bc_penalty)
                adjusted_score = base_score - penalty - cooldown_penalty
                rows.append({**row, "candidate_variant": variant, "original_d_rank": int(row["rank"]), "original_d_score": base_score, "adjusted_score_for_sort": adjusted_score, "adjusted_score": base_score - penalty, "total_penalty": penalty, "cooldown_top20_block": bool(cooldown_penalty), "prior_loss_count": st["prior_loss_count"], "prior_avg_loss": st["prior_avg_loss"], "prior_worst_loss": st["prior_worst_loss"], "bc_supported_top30": bc_supported})
                penalties.append({"as_of_date": as_of, "candidate_variant": variant, "ticker": ticker, "original_d_score": base_score, "soft_repeated_loser_penalty": soft_penalty if variant in {"D_R2A_REPEATED_LOSER_SOFT_PENALTY", "D_R2D_COMBINED_SOFT_PENALTY"} else 0.0, "bc_confirmation_penalty": bc_penalty if variant in {"D_R2C_BC_CONFIRMATION_OVERLAY", "D_R2D_COMBINED_SOFT_PENALTY"} else 0.0, "total_penalty": penalty, "bounded_penalty_ok": penalty <= 8.0, "top20_cooldown_block": bool(cooldown_penalty), "cooldown_window": "until two clean matured observations after prior loss event", "prior_loss_count_available_before_ranking_date": st["prior_loss_count"], "future_leakage_guard": "only_loss_events_with_end_date_before_ranking_date"})
            df = pd.DataFrame(rows).sort_values(["adjusted_score_for_sort", "ticker"], ascending=[False, True]).reset_index(drop=True)
            df["adjusted_rank"] = range(1, len(df) + 1)
            df["rank"] = df["adjusted_rank"]
            df["final_score"] = df["adjusted_score"]
            df["in_top20"] = df["adjusted_rank"].le(20)
            df["in_top50"] = df["adjusted_rank"].le(50)
            adjusted.extend(df.to_dict("records"))
            new_top20 = set(df[df["adjusted_rank"].le(20)]["ticker"])
            new_top50 = set(df[df["adjusted_rank"].le(50)]["ticker"])
            for ticker in sorted(new_top50 | orig_top50):
                nr = df[df["ticker"].eq(ticker)]
                od = d[d["ticker"].eq(ticker)]
                new_rank = int(nr.iloc[0]["adjusted_rank"]) if not nr.empty else ""
                old_rank = int(od.iloc[0]["rank"]) if not od.empty else ""
                new_score = float(nr.iloc[0]["adjusted_score"]) if not nr.empty else math.nan
                old_score = float(od.iloc[0]["final_score"]) if not od.empty else math.nan
                change = "UNCHANGED"
                if ticker in new_top20 - orig_top20:
                    change = "TOP20_ENTRANT"
                elif ticker in orig_top20 - new_top20:
                    change = "TOP20_REMOVAL"
                elif ticker in new_top50 - orig_top50:
                    change = "TOP50_ENTRANT"
                elif ticker in orig_top50 - new_top50:
                    change = "TOP50_REMOVAL"
                diffs.append({"as_of_date": as_of, "candidate_variant": variant, "ticker": ticker, "original_rank": old_rank, "adjusted_rank": new_rank, "rank_delta": "" if old_rank == "" or new_rank == "" else old_rank - new_rank, "original_score": old_score, "adjusted_score": new_score, "score_delta": "" if math.isnan(old_score) or math.isnan(new_score) else new_score - old_score, "change_type": change})
            for ticker in sorted(new_top50):
                r = df[df["ticker"].eq(ticker)].iloc[0]
                membership.append({"as_of_date": as_of, "candidate_variant": variant, "ticker": ticker, "rank": int(r["adjusted_rank"]), "final_score": float(r["adjusted_score"]), "in_top20": bool(r["adjusted_rank"] <= 20), "in_top50": True, "original_d_rank": int(r["original_d_rank"]), "original_d_top20": ticker in orig_top20, "original_d_top50": ticker in orig_top50})
    return pd.DataFrame(adjusted), penalties, diffs, membership


def summarize_returns(tickers: list[str], start: str, end: str, prices: dict[tuple[str, str], float]) -> dict[str, Any]:
    vals = []
    missing = 0
    details = []
    for ticker in tickers:
        value = ret(ticker, start, end, prices)
        if pd.isna(value):
            missing += 1
        else:
            vals.append(value)
            details.append((ticker, value))
    if not vals:
        return {"valid_price_count": 0, "missing_price_count": missing, "equal_weight_return": math.nan, "median_member_return": math.nan, "hit_rate": math.nan, "best_contributor": "", "worst_contributor": ""}
    best = max(details, key=lambda x: x[1])
    worst = min(details, key=lambda x: x[1])
    return {"valid_price_count": len(vals), "missing_price_count": missing, "equal_weight_return": float(pd.Series(vals).mean()), "median_member_return": float(pd.Series(vals).median()), "hit_rate": float(sum(1 for v in vals if v > 0) / len(vals)), "best_contributor": best[0], "worst_contributor": worst[0]}


def forward_eval(membership: pd.DataFrame, original_fwd: pd.DataFrame, prices: dict[tuple[str, str], float], dates: list[str]) -> pd.DataFrame:
    rows = []
    orig_d = original_fwd[original_fwd["strategy"].eq("D_WEIGHT_OPTIMIZED_R1")]
    for (as_of, variant), group in membership.groupby(["as_of_date", "candidate_variant"], sort=True):
        for topn in TOP_NS:
            tickers = list(group[group["rank"].le(topn)].sort_values("rank")["ticker"])
            for h in HORIZONS:
                matured, end = (False, "")
                if as_of in dates and dates.index(as_of) + h < len(dates):
                    matured, end = True, dates[dates.index(as_of) + h]
                row = {"as_of_date": as_of, "candidate_variant": variant, "top_n": topn, "horizon": f"{h}D", "start_date": as_of, "end_date": end, "matured": matured, "member_count": len(tickers)}
                if matured:
                    stats = summarize_returns(tickers, as_of, end, prices)
                    qqq = ret("QQQ", as_of, end, prices)
                    soxx = ret("SOXX", as_of, end, prices)
                    od = orig_d[(orig_d["as_of_date"].astype(str).eq(as_of)) & (orig_d["top_n"].eq(topn)) & (orig_d["horizon"].eq(f"{h}D"))]
                    orig_ret = float(od.iloc[0]["equal_weight_return"]) if not od.empty and not pd.isna(od.iloc[0]["equal_weight_return"]) else math.nan
                    row.update(stats)
                    row.update({"benchmark_QQQ_return": qqq, "benchmark_SOXX_return": soxx, "excess_vs_QQQ": stats["equal_weight_return"] - qqq if not pd.isna(qqq) else math.nan, "excess_vs_SOXX": stats["equal_weight_return"] - soxx if not pd.isna(soxx) else math.nan, "excess_vs_original_D": stats["equal_weight_return"] - orig_ret if not pd.isna(orig_ret) else math.nan})
                else:
                    row.update({"valid_price_count": 0, "missing_price_count": len(tickers), "equal_weight_return": math.nan, "median_member_return": math.nan, "hit_rate": math.nan, "best_contributor": "", "worst_contributor": "", "benchmark_QQQ_return": math.nan, "benchmark_SOXX_return": math.nan, "excess_vs_QQQ": math.nan, "excess_vs_SOXX": math.nan, "excess_vs_original_D": math.nan})
                rows.append(row)
    return pd.DataFrame(rows)


def pairwise(candidate_fwd: pd.DataFrame, original_fwd: pd.DataFrame) -> pd.DataFrame:
    rows = []
    baselines = original_fwd[original_fwd["strategy"].isin(BASE_STRATEGIES)].copy()
    for variant in VARIANTS:
        for topn in TOP_NS:
            for h in [f"{x}D" for x in HORIZONS]:
                left = candidate_fwd[(candidate_fwd["candidate_variant"].eq(variant)) & (candidate_fwd["top_n"].eq(topn)) & (candidate_fwd["horizon"].eq(h)) & (candidate_fwd["matured"].eq(True))]
                for strategy in BASE_STRATEGIES:
                    right = baselines[(baselines["strategy"].eq(strategy)) & (baselines["top_n"].eq(topn)) & (baselines["horizon"].eq(h)) & (baselines["matured"].astype(str).str.upper().eq("TRUE"))]
                    merged = left.merge(right, on=["as_of_date", "top_n", "horizon"], suffixes=("_candidate", "_baseline"))
                    diffs = (merged["equal_weight_return_candidate"] - merged["equal_weight_return_baseline"]).dropna()
                    rows.append({"candidate_variant": variant, "comparison": f"{variant}_vs_{strategy}", "top_n": topn, "horizon": h, "win_count": int((diffs > 0).sum()), "loss_count": int((diffs < 0).sum()), "tie_count": int((diffs == 0).sum()), "win_rate": float((diffs > 0).sum() / len(diffs)) if len(diffs) else math.nan, "average_excess_return": float(diffs.mean()) if len(diffs) else math.nan, "median_excess_return": float(diffs.median()) if len(diffs) else math.nan, "available_observations": int(len(diffs))})
                for bench in ["QQQ", "SOXX"]:
                    col = f"excess_vs_{bench}"
                    vals = left[col].dropna()
                    rows.append({"candidate_variant": variant, "comparison": f"{variant}_vs_{bench}", "top_n": topn, "horizon": h, "win_count": int((vals > 0).sum()), "loss_count": int((vals < 0).sum()), "tie_count": int((vals == 0).sum()), "win_rate": float((vals > 0).sum() / len(vals)) if len(vals) else math.nan, "average_excess_return": float(vals.mean()) if len(vals) else math.nan, "median_excess_return": float(vals.median()) if len(vals) else math.nan, "available_observations": int(len(vals))})
    return pd.DataFrame(rows)


def diagnostics(adjusted: pd.DataFrame, membership: pd.DataFrame, fwd: pd.DataFrame, pair: pd.DataFrame, losers: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    severe = set(losers[(losers["loss_count"] >= 3) & (losers["ticker"].notna())]["ticker"].astype(str).str.upper())
    reduction = []
    impact = []
    stability = []
    sanity = []
    original_count = len(severe)
    for variant in VARIANTS:
        m = membership[membership["candidate_variant"].eq(variant)]
        top20_severe = set(m[(m["in_top20"].eq(True)) & (m["ticker"].isin(severe))]["ticker"])
        reduction.append({"candidate_variant": variant, "original_D_repeated_loser_count": original_count, "variant_repeated_loser_count": len(top20_severe), "reduction_amount": original_count - len(top20_severe), "worst_repeated_losers_removed_or_downranked": "|".join(sorted(severe - top20_severe))})
        sub = fwd[(fwd["candidate_variant"].eq(variant)) & (fwd["matured"].eq(True))]
        t20 = sub[sub["top_n"].eq(20)].merge(sub[sub["top_n"].eq(50)], on=["as_of_date", "horizon"], suffixes=("_20", "_50"))
        delta = t20["equal_weight_return_20"] - t20["equal_weight_return_50"] if len(t20) else pd.Series(dtype=float)
        impact.append({"candidate_variant": variant, "avg_top20_minus_top50_return": float(delta.mean()) if len(delta) else math.nan, "median_top20_minus_top50_return": float(delta.median()) if len(delta) else math.nan, "top20_helped_rate": float((delta > 0).sum() / len(delta)) if len(delta) else math.nan})
        overlaps = []
        rank_moves = []
        for (as_of, _), group in m.groupby(["as_of_date", "candidate_variant"]):
            overlaps.append(float(group["original_d_top20"].sum()) / 20.0)
            rank_moves.extend((group["original_d_rank"] - group["rank"]).abs().tolist())
        stability.append({"candidate_variant": variant, "avg_top20_overlap_with_original_D": float(pd.Series(overlaps).mean()) if overlaps else math.nan, "avg_abs_rank_movement": float(pd.Series(rank_moves).mean()) if rank_moves else math.nan, "excessive_turnover_warning": bool(pd.Series(overlaps).mean() < 0.65) if overlaps else True})
        p = pair[(pair["candidate_variant"].eq(variant)) & (pair["top_n"].eq(20))]
        sanity.append({"candidate_variant": variant, "beats_QQQ_avg_excess": float(p[p["comparison"].str.endswith("_vs_QQQ")]["average_excess_return"].mean()), "beats_SOXX_avg_excess": float(p[p["comparison"].str.endswith("_vs_SOXX")]["average_excess_return"].mean()), "improvement_only_one_extreme_loser_warning": (original_count - len(top20_severe)) <= 1})
    return reduction, impact, stability, sanity


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    ok, missing = required_ok()
    if not ok:
        manifest = {"FINAL_STATUS": "BLOCKED_V21_118_MISSING_REQUIRED_INPUTS", "DECISION": "DO_NOT_USE_D_R2_DESIGN", "missing_inputs": missing, "protected_outputs_modified": False, "official_adoption_allowed": False, "broker_action_allowed": False, "research_only": True}
        write_json(OUT / "V21.118_manifest.json", manifest)
        (OUT / "V21.118_D_R2_design_report.txt").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest, indent=2))
        return manifest

    v117 = json.loads(V117_MANIFEST.read_text(encoding="utf-8"))
    r1 = json.loads(R1_MANIFEST.read_text(encoding="utf-8"))
    ranks = pd.read_csv(ABCD, low_memory=False)
    ranks["ticker"] = ranks["ticker"].astype(str).str.upper().str.strip()
    ranks["rank"] = pd.to_numeric(ranks["rank"], errors="coerce")
    ranks["final_score"] = pd.to_numeric(ranks["final_score"], errors="coerce")
    worst = pd.read_csv(WORST, low_memory=False)
    losers = pd.read_csv(R1_LOSERS, low_memory=False)
    original_fwd = pd.read_csv(FWD, low_memory=False)
    prices, trading_dates, latest_price = load_prices()

    adjusted, penalty_rows, diff_rows, membership_rows = adjust_rankings(ranks, worst)
    membership = pd.DataFrame(membership_rows)
    cand_fwd = forward_eval(membership, original_fwd, prices, trading_dates)
    pair = pairwise(cand_fwd, original_fwd)
    reduction, impact, stability, sanity = diagnostics(adjusted, membership, cand_fwd, pair, losers)

    adjusted.to_csv(OUT / "d_r2_adjusted_rankings.csv", index=False)
    write_csv(OUT / "d_r2_top20_top50_membership.csv", membership_rows)
    write_csv(OUT / "d_r2_penalty_attribution.csv", penalty_rows)
    write_csv(OUT / "d_r2_diff_vs_original_d.csv", diff_rows)
    cand_fwd.to_csv(OUT / "d_r2_forward_by_date_horizon.csv", index=False)
    pair.to_csv(OUT / "d_r2_pairwise_winrate.csv", index=False)
    write_csv(OUT / "d_r2_repeated_loser_reduction.csv", reduction)
    write_csv(OUT / "d_r2_top20_top50_impact.csv", impact)
    write_csv(OUT / "d_r2_turnover_stability.csv", stability)
    write_csv(OUT / "d_r2_benchmark_sanity.csv", sanity)

    pair_top20 = pair[pair["top_n"].eq(20)]
    original_cmp = pair_top20[pair_top20["comparison"].str.endswith("_vs_D_WEIGHT_OPTIMIZED_R1")]
    best = ""
    best_score = -999.0
    for variant in VARIANTS:
        p = original_cmp[original_cmp["candidate_variant"].eq(variant)]
        red = next((r for r in reduction if r["candidate_variant"] == variant), {})
        stab = next((r for r in stability if r["candidate_variant"] == variant), {})
        score = (float(p["average_excess_return"].mean()) if not p.empty else -1.0) + float(red.get("reduction_amount", 0)) * 0.002 - (0.02 if stab.get("excessive_turnover_warning") else 0)
        if score > best_score:
            best, best_score = variant, score
    def win_rate(comp_suffix: str) -> float:
        sub = pair_top20[(pair_top20["candidate_variant"].eq(best)) & (pair_top20["comparison"].str.endswith(comp_suffix))]
        sub = sub[sub["available_observations"] > 0]
        return float(sub["win_rate"].mean()) if not sub.empty else math.nan
    best_red = next(r for r in reduction if r["candidate_variant"] == best)
    best_stab = next(r for r in stability if r["candidate_variant"] == best)
    best_sanity = next(r for r in sanity if r["candidate_variant"] == best)
    top50_stability_preserved = not bool(best_stab["excessive_turnover_warning"])
    excessive_turnover = bool(best_stab["excessive_turnover_warning"])
    overfit_warning = bool(best_sanity["improvement_only_one_extreme_loser_warning"])
    improved_vs_d = win_rate("_vs_D_WEIGHT_OPTIMIZED_R1") > 0.5
    reduced_drag = int(best_red["reduction_amount"]) > 0
    if reduced_drag and improved_vs_d and top50_stability_preserved and not excessive_turnover and not overfit_warning:
        final_status = "PASS_V21_118_D_R2_CANDIDATE_IMPROVES_REPEATED_LOSER_DRAG"
        decision = "D_R2_CANDIDATE_READY_FOR_RESEARCH_TRACKING_ONLY"
    elif reduced_drag:
        final_status = "PARTIAL_PASS_V21_118_D_R2_MIXED_IMPROVEMENT"
        decision = "D_R2_CANDIDATE_MIXED_RESEARCH_ONLY"
    else:
        final_status = "WARN_V21_118_D_R2_NO_USEFUL_IMPROVEMENT"
        decision = "DO_NOT_ADVANCE_D_R2_CANDIDATE"
    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "source_v21_117_status": v117.get("FINAL_STATUS", ""),
        "source_v21_117_r1_failure_mode": r1.get("primary_D_weakness_classification", ""),
        "latest_price_date_used": latest_price,
        "candidate_variants_evaluated": VARIANTS,
        "best_diagnostic_variant": best,
        "original_D_vs_best_D_R2_Top20_win_rate": win_rate("_vs_D_WEIGHT_OPTIMIZED_R1"),
        "best_D_R2_vs_A1_Top20_win_rate": win_rate("_vs_A1_BASELINE_CONTROL"),
        "best_D_R2_vs_B_Top20_win_rate": win_rate("_vs_B_STATIC_MOMENTUM_BLEND"),
        "best_D_R2_vs_C_Top20_win_rate": win_rate("_vs_C_DYNAMIC_MOMENTUM_BLEND"),
        "best_D_R2_vs_QQQ_average_excess": float(pair_top20[(pair_top20["candidate_variant"].eq(best)) & (pair_top20["comparison"].str.endswith("_vs_QQQ"))]["average_excess_return"].mean()),
        "best_D_R2_vs_SOXX_average_excess": float(pair_top20[(pair_top20["candidate_variant"].eq(best)) & (pair_top20["comparison"].str.endswith("_vs_SOXX"))]["average_excess_return"].mean()),
        "repeated_loser_count_before": best_red["original_D_repeated_loser_count"],
        "repeated_loser_count_after": best_red["variant_repeated_loser_count"],
        "Top50_stability_preserved": top50_stability_preserved,
        "excessive_turnover_warning": excessive_turnover,
        "overfit_warning": overfit_warning,
        "D_R2_official_adoption_allowed": False,
        "broker_action_allowed": False,
        "further_maturity_tracking_required": True,
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "research_only": True,
    }
    write_json(OUT / "V21.118_manifest.json", manifest)
    report = [
        f"{STAGE}",
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"source V21.117 status={v117.get('FINAL_STATUS', '')}",
        f"source V21.117_R1 failure mode={r1.get('primary_D_weakness_classification', '')}",
        f"latest_price_date_used={latest_price}",
        f"candidate variants evaluated={', '.join(VARIANTS)}",
        f"best diagnostic variant={best}",
        f"original D vs best D-R2 Top20 win rate={manifest['original_D_vs_best_D_R2_Top20_win_rate']}",
        f"best D-R2 vs A1/B/C Top20 win rates={manifest['best_D_R2_vs_A1_Top20_win_rate']}/{manifest['best_D_R2_vs_B_Top20_win_rate']}/{manifest['best_D_R2_vs_C_Top20_win_rate']}",
        f"best D-R2 vs QQQ/SOXX average excess={manifest['best_D_R2_vs_QQQ_average_excess']}/{manifest['best_D_R2_vs_SOXX_average_excess']}",
        f"repeated loser count before and after={best_red['original_D_repeated_loser_count']}->{best_red['variant_repeated_loser_count']}",
        f"Top50 stability preserved={top50_stability_preserved}",
        f"excessive turnover warning={excessive_turnover}",
        f"overfit warning={overfit_warning}",
        "D-R2 official adoption allowed=false",
        "broker action allowed=false",
        "further maturity tracking required=true",
    ]
    (OUT / "V21.118_D_R2_design_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, default=str))
    return manifest


if __name__ == "__main__":
    run()
