#!/usr/bin/env python
"""V21.122 forward tracking for A1/B/C and frozen D-R2C."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.122_A1_BC_FORWARD_TRACKING_AND_D_R2C_FREEZE_MONITOR"
OUT = ROOT / "outputs/v21/V21.122_A1_BC_FORWARD_TRACKING_AND_D_R2C_FREEZE_MONITOR"

V121 = ROOT / "outputs/v21/V21.121_CANDIDATE_REBASE_REVIEW_A1_B_C_D_R2C"
V119_R2 = ROOT / "outputs/v21/V21.119_R2_NEW_MATURITY_ATTRIBUTION_AND_BC_COMPARISON"
V119_R1 = ROOT / "outputs/v21/V21.119_R1_FORWARD_MATURITY_UPDATE_AFTER_REFRESH"
V120 = ROOT / "outputs/v21/V21.120_CANONICAL_PRICE_REFRESH_AND_MATURITY_GATE"
V116 = ROOT / "outputs/v21/V21.116_DAILY_TOP50_FULL_DATA_LEDGER_20260616_TO_LATEST"
V118 = ROOT / "outputs/v21/V21.118_D_R2_REPEATED_LOSER_AWARE_DESIGN"

V121_MANIFEST = V121 / "V21.121_manifest.json"
V121_SCORECARD = V121 / "candidate_scorecard_a1_b_c_d_d_r2c.csv"
V119_R2_MANIFEST = V119_R2 / "V21.119_R2_manifest.json"
V119_R1_PANEL = V119_R1 / "forward_maturity_by_date_horizon_after_refresh.csv"
V120_MANIFEST = V120 / "V21.120_manifest.json"
ABCD = V116 / "daily_ABCD_top50_full_ledger.csv"
D_R2C_MEMBERS = V118 / "d_r2_top20_top50_membership.csv"
PRICE = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
BENCH = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"

STRATEGIES = [
    "A1_BASELINE_CONTROL",
    "B_STATIC_MOMENTUM_BLEND",
    "C_DYNAMIC_MOMENTUM_BLEND",
    "D_WEIGHT_OPTIMIZED_R1",
    "D_R2C_BC_CONFIRMATION_OVERLAY",
]
HORIZONS = [1, 3, 5, 10, 20]
TOP_NS = [20, 50]
OLD_BUCKET = "OLD_OR_PRIOR_MATURED"
NEW_BUCKET = "NEWLY_MATURED_SINCE_V21_121"
UNMATURED_BUCKET = "STILL_UNMATURED"
PAIRS = [
    ("A1_BASELINE_CONTROL", "B_STATIC_MOMENTUM_BLEND"),
    ("A1_BASELINE_CONTROL", "C_DYNAMIC_MOMENTUM_BLEND"),
    ("A1_BASELINE_CONTROL", "D_R2C_BC_CONFIRMATION_OVERLAY"),
    ("D_R2C_BC_CONFIRMATION_OVERLAY", "D_WEIGHT_OPTIMIZED_R1"),
    ("D_R2C_BC_CONFIRMATION_OVERLAY", "A1_BASELINE_CONTROL"),
    ("D_R2C_BC_CONFIRMATION_OVERLAY", "B_STATIC_MOMENTUM_BLEND"),
    ("D_R2C_BC_CONFIRMATION_OVERLAY", "C_DYNAMIC_MOMENTUM_BLEND"),
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


def missing_inputs() -> list[str]:
    required = [V121_MANIFEST, V121_SCORECARD, V119_R2_MANIFEST, V119_R1_PANEL, V120_MANIFEST, ABCD, D_R2C_MEMBERS, PRICE]
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
    idx = dates.index(as_of) + horizon_days
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
    series = pd.Series(values)
    best = max(details, key=lambda item: item[1])
    worst = min(details, key=lambda item: item[1])
    return {
        "valid_price_count": int(len(values)),
        "missing_price_count": int(missing),
        "equal_weight_return": float(series.mean()),
        "median_member_return": float(series.median()),
        "hit_rate": float((series > 0).sum() / len(series)),
        "best_contributor": best[0],
        "worst_contributor": worst[0],
    }


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


def prior_matured_keys() -> set[tuple[str, str, int, str]]:
    panel = pd.read_csv(V119_R1_PANEL, low_memory=False)
    panel = panel[panel["matured"].astype(str).str.upper().eq("TRUE")]
    return {
        (str(r["ranking_date"]), str(r["strategy"]), int(r["top_n"]), str(r["horizon"]))
        for r in panel.to_dict("records")
    }


def pairwise(panel: pd.DataFrame, bucket: str | None) -> pd.DataFrame:
    rows = panel[panel["matured"].eq(True)].copy()
    if bucket:
        rows = rows[rows["observation_bucket"].eq(bucket)]
    result = []
    for topn in TOP_NS:
        for horizon in [f"{h}D" for h in HORIZONS]:
            for left, right in PAIRS:
                l = rows[rows["strategy"].eq(left) & rows["top_n"].eq(topn) & rows["horizon"].eq(horizon)]
                r = rows[rows["strategy"].eq(right) & rows["top_n"].eq(topn) & rows["horizon"].eq(horizon)]
                merged = l.merge(r, on=["ranking_date", "top_n", "horizon"], suffixes=("_left", "_right"))
                diffs = (merged["equal_weight_return_left"] - merged["equal_weight_return_right"]).dropna()
                result.append({
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
                    "available_observations": int(len(diffs)),
                })
    return pd.DataFrame(result)


def metric(pair: pd.DataFrame, comparison: str, topn: int, field: str = "win_rate") -> float:
    sub = pair[(pair["comparison"].eq(comparison)) & (pair["top_n"].eq(topn)) & (pair["available_observations"] > 0)]
    return float(sub[field].mean()) if not sub.empty else math.nan


def blocked(missing: list[str]) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": "BLOCKED_V21_122_MISSING_REQUIRED_INPUTS",
        "DECISION": "DO_NOT_USE_FORWARD_TRACKING_MONITOR",
        "missing_inputs": missing,
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
    }
    write_json(OUT / "V21.122_manifest.json", manifest)
    (OUT / "V21.122_forward_tracking_report.txt").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return manifest


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    missing = missing_inputs()
    if missing:
        return blocked(missing)

    v121 = json.loads(V121_MANIFEST.read_text(encoding="utf-8"))
    v119r2 = json.loads(V119_R2_MANIFEST.read_text(encoding="utf-8"))
    v120 = json.loads(V120_MANIFEST.read_text(encoding="utf-8"))
    scorecard = pd.read_csv(V121_SCORECARD, low_memory=False)
    prices, dates, latest = load_prices()
    memberships = build_memberships()
    old_keys = prior_matured_keys()

    hierarchy_loaded = (
        v121.get("primary_control") == "A1_BASELINE_CONTROL"
        and v121.get("primary_research_candidate") == "A1_BASELINE_CONTROL"
        and "D_R2C_BC_CONFIRMATION_OVERLAY" in str(v121.get("secondary_research_candidate", ""))
        and "DOWNGRADED" in str(v121.get("D_original_status", ""))
        and v121.get("official_adoption_allowed") is False
        and v121.get("broker_action_allowed") is False
    )
    hierarchy_rows = [{
        "candidate_hierarchy_loaded": hierarchy_loaded,
        "source_v21_121_status": v121.get("FINAL_STATUS", ""),
        "primary_control": v121.get("primary_control", ""),
        "primary_research_candidate": v121.get("primary_research_candidate", ""),
        "secondary_research_candidates": v121.get("secondary_research_candidate", ""),
        "D_original_status": v121.get("D_original_status", ""),
        "D_R2C_status": v121.get("D_R2C_status", ""),
        "B_status": v121.get("B_status", ""),
        "C_status": v121.get("C_status", ""),
        "A1_status": v121.get("A1_status", ""),
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
    }]
    write_csv(OUT / "candidate_hierarchy_audit.csv", hierarchy_rows)

    rows = []
    for (as_of, strategy, topn), tickers in sorted(memberships.items()):
        for h in HORIZONS:
            horizon = f"{h}D"
            matured, end = end_date(as_of, h, dates)
            key = (as_of, strategy, topn, horizon)
            bucket = OLD_BUCKET if matured and key in old_keys else NEW_BUCKET if matured else UNMATURED_BUCKET
            row = {
                "ranking_date": as_of,
                "start_date": as_of,
                "end_date": end,
                "strategy": strategy,
                "top_n": topn,
                "horizon": horizon,
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
    panel.to_csv(OUT / "forward_tracking_by_date_horizon.csv", index=False)

    all_pair = pairwise(panel, None)
    new_pair = pairwise(panel, NEW_BUCKET)
    all_matured_count = int(panel["matured"].sum())
    newly_count = int(panel["observation_bucket"].eq(NEW_BUCKET).sum())
    still_unmatured = int(panel["observation_bucket"].eq(UNMATURED_BUCKET).sum())

    a1_b_20 = metric(new_pair if newly_count else all_pair, "A1_BASELINE_CONTROL_vs_B_STATIC_MOMENTUM_BLEND", 20)
    a1_c_20 = metric(new_pair if newly_count else all_pair, "A1_BASELINE_CONTROL_vs_C_DYNAMIC_MOMENTUM_BLEND", 20)
    a1_r2c_20 = metric(new_pair if newly_count else all_pair, "A1_BASELINE_CONTROL_vs_D_R2C_BC_CONFIRMATION_OVERLAY", 20)
    a1_b_50 = metric(new_pair if newly_count else all_pair, "A1_BASELINE_CONTROL_vs_B_STATIC_MOMENTUM_BLEND", 50)
    a1_c_50 = metric(new_pair if newly_count else all_pair, "A1_BASELINE_CONTROL_vs_C_DYNAMIC_MOMENTUM_BLEND", 50)
    a1_r2c_50 = metric(new_pair if newly_count else all_pair, "A1_BASELINE_CONTROL_vs_D_R2C_BC_CONFIRMATION_OVERLAY", 50)
    a1_rows = panel[panel["strategy"].eq("A1_BASELINE_CONTROL") & panel["matured"].eq(True)]
    if newly_count:
        a1_rows = a1_rows[a1_rows["observation_bucket"].eq(NEW_BUCKET)]
    a1_qqq = float(a1_rows["excess_vs_QQQ"].dropna().mean()) if not a1_rows.empty else math.nan
    a1_soxx = float(a1_rows["excess_vs_SOXX"].dropna().mean()) if not a1_rows.empty else math.nan
    a1_leader = bool(v121.get("evidence_favors") == "A1" and (newly_count == 0 or (a1_b_20 >= 0.5 and a1_c_20 >= 0.5)))
    write_csv(OUT / "a1_leadership_monitor.csv", [{
        "A1_vs_B_Top20_win_rate": a1_b_20,
        "A1_vs_C_Top20_win_rate": a1_c_20,
        "A1_vs_D_R2C_Top20_win_rate": a1_r2c_20,
        "A1_vs_B_Top50_win_rate": a1_b_50,
        "A1_vs_C_Top50_win_rate": a1_c_50,
        "A1_vs_D_R2C_Top50_win_rate": a1_r2c_50,
        "A1_average_excess_vs_QQQ": a1_qqq,
        "A1_average_excess_vs_SOXX": a1_soxx,
        "A1_remains_evidence_leader": a1_leader,
    }])

    b_challenge = bool(newly_count > 0 and a1_b_20 < 0.5)
    c_challenge = bool(newly_count > 0 and a1_c_20 < 0.5)
    bc_challenge = bool(b_challenge or c_challenge)
    b_rows = panel[panel["strategy"].eq("B_STATIC_MOMENTUM_BLEND") & panel["matured"].eq(True)]
    c_rows = panel[panel["strategy"].eq("C_DYNAMIC_MOMENTUM_BLEND") & panel["matured"].eq(True)]
    if newly_count:
        b_rows = b_rows[b_rows["observation_bucket"].eq(NEW_BUCKET)]
        c_rows = c_rows[c_rows["observation_bucket"].eq(NEW_BUCKET)]
    write_csv(OUT / "bc_challenge_monitor.csv", [{
        "B_challenge_detected": b_challenge,
        "C_challenge_detected": c_challenge,
        "B_or_C_challenge_detected": bc_challenge,
        "B_vs_A1_Top20_win_rate": 1.0 - a1_b_20 if not pd.isna(a1_b_20) else math.nan,
        "C_vs_A1_Top20_win_rate": 1.0 - a1_c_20 if not pd.isna(a1_c_20) else math.nan,
        "B_average_excess_vs_QQQ": float(b_rows["excess_vs_QQQ"].dropna().mean()) if not b_rows.empty else math.nan,
        "B_average_excess_vs_SOXX": float(b_rows["excess_vs_SOXX"].dropna().mean()) if not b_rows.empty else math.nan,
        "C_average_excess_vs_QQQ": float(c_rows["excess_vs_QQQ"].dropna().mean()) if not c_rows.empty else math.nan,
        "C_average_excess_vs_SOXX": float(c_rows["excess_vs_SOXX"].dropna().mean()) if not c_rows.empty else math.nan,
        "promotion_allowed_now": False,
    }])

    r2c_d_20 = metric(new_pair if newly_count else all_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_D_WEIGHT_OPTIMIZED_R1", 20)
    r2c_a1_20 = metric(new_pair if newly_count else all_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_A1_BASELINE_CONTROL", 20)
    r2c_b_20 = metric(new_pair if newly_count else all_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_B_STATIC_MOMENTUM_BLEND", 20)
    r2c_c_20 = metric(new_pair if newly_count else all_pair, "D_R2C_BC_CONFIRMATION_OVERLAY_vs_C_DYNAMIC_MOMENTUM_BLEND", 20)
    d2c_score = scorecard[scorecard["candidate"].eq("D_R2C_BC_CONFIRMATION_OVERLAY")].iloc[0].to_dict()
    d_score = scorecard[scorecard["candidate"].eq("D_WEIGHT_OPTIMIZED_R1")].iloc[0].to_dict()
    overfit_status = str(v119r2.get("overfit_status", "UNCHANGED"))
    repeated_meaningful = bool(v119r2.get("repeated_loser_problem_meaningfully_improved", False))
    write_csv(OUT / "d_r2c_freeze_monitor.csv", [{
        "D_R2C_status": v121.get("D_R2C_status", ""),
        "D_original_status": v121.get("D_original_status", ""),
        "D_R2C_vs_original_D_Top20_win_rate": r2c_d_20,
        "D_R2C_vs_A1_Top20_win_rate": r2c_a1_20,
        "D_R2C_vs_B_Top20_win_rate": r2c_b_20,
        "D_R2C_vs_C_Top20_win_rate": r2c_c_20,
        "D_R2C_overfit_status": overfit_status,
        "original_D_repeated_loser_count": d_score.get("repeated_loser_exposure", ""),
        "D_R2C_repeated_loser_count": d2c_score.get("repeated_loser_exposure", ""),
        "D_R2C_repeated_loser_reduction_meaningful": repeated_meaningful,
        "D_R2C_frozen_secondary_tracking_only": True,
        "D_R2C_tuned_or_modified": False,
    }])

    bench_rows = []
    source_panel = panel[panel["matured"].eq(True)]
    if newly_count:
        source_panel = source_panel[source_panel["observation_bucket"].eq(NEW_BUCKET)]
    for strategy in STRATEGIES:
        sub = source_panel[source_panel["strategy"].eq(strategy)]
        bench_rows.append({
            "strategy": strategy,
            "observation_scope": NEW_BUCKET if newly_count else OLD_BUCKET,
            "average_excess_vs_QQQ": float(sub["excess_vs_QQQ"].dropna().mean()) if not sub.empty else math.nan,
            "average_excess_vs_SOXX": float(sub["excess_vs_SOXX"].dropna().mean()) if not sub.empty else math.nan,
            "positive_QQQ_excess_rate": float((sub["excess_vs_QQQ"].dropna() > 0).mean()) if not sub.empty else math.nan,
            "positive_SOXX_excess_rate": float((sub["excess_vs_SOXX"].dropna() > 0).mean()) if not sub.empty else math.nan,
        })
    write_csv(OUT / "benchmark_sanity_tracking.csv", bench_rows)

    if not a1_leader and newly_count > 0:
        drift = "ROLE_REVIEW_REQUIRED"
    elif newly_count == 0:
        drift = "WAIT_MORE_MATURITY"
    else:
        drift = "KEEP_CURRENT_HIERARCHY"
    role_review_required = drift == "ROLE_REVIEW_REQUIRED"
    write_csv(OUT / "candidate_role_drift.csv", [{
        "role_drift_flag": drift,
        "A1_remains_evidence_leader": a1_leader,
        "B_or_C_challenge_detected": bc_challenge,
        "D_R2C_unexpected_broad_improvement": bool(r2c_d_20 > 0.5 and r2c_a1_20 > 0.5 and r2c_b_20 > 0.5 and r2c_c_20 > 0.5 and repeated_meaningful),
        "role_review_required": role_review_required,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
    }])

    if role_review_required or (bc_challenge and newly_count > 0):
        final_status = "WARN_V21_122_ROLE_REVIEW_REQUIRED"
        decision = "ROLE_REVIEW_REQUIRED_RESEARCH_ONLY"
    elif newly_count == 0:
        final_status = "WARN_V21_122_WAIT_MORE_MATURITY"
        decision = "WAIT_MORE_MATURITY_RESEARCH_ONLY"
    elif a1_leader and not bc_challenge:
        final_status = "PASS_V21_122_KEEP_CURRENT_HIERARCHY"
        decision = "KEEP_CURRENT_HIERARCHY_RESEARCH_ONLY"
    else:
        final_status = "PARTIAL_PASS_V21_122_TRACKING_UPDATED_ROLE_REVIEW_NOT_REQUIRED"
        decision = "TRACKING_UPDATED_ROLE_REVIEW_NOT_REQUIRED_RESEARCH_ONLY"

    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_used": latest,
        "source_v21_121_status": v121.get("FINAL_STATUS", ""),
        "candidate_hierarchy_loaded": hierarchy_loaded,
        "primary_control": v121.get("primary_control", ""),
        "primary_research_candidate": v121.get("primary_research_candidate", ""),
        "secondary_research_candidates": v121.get("secondary_research_candidate", ""),
        "D_original_status": v121.get("D_original_status", ""),
        "D_R2C_status": v121.get("D_R2C_status", ""),
        "all_matured_observation_count": all_matured_count,
        "newly_matured_observation_count": newly_count,
        "still_unmatured_observation_count": still_unmatured,
        "A1_remains_evidence_leader": a1_leader,
        "B_or_C_challenge_detected": bc_challenge,
        "D_R2C_overfit_status": overfit_status,
        "D_R2C_repeated_loser_reduction_meaningful": repeated_meaningful,
        "role_review_required": role_review_required,
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "no_parameter_optimization_performed": True,
        "new_variant_generated": False,
        "historical_rankings_recomputed": False,
        "D_R2C_frozen_tracking_only": True,
        "original_D_downgraded_reference_only": True,
        "next_recommended_stage": "V21.123_PRICE_REFRESH_MATURITY_GATE_OR_WAIT_FOR_NEXT_COMPLETED_DAILY_BAR",
        "source_v21_120_status": v120.get("FINAL_STATUS", ""),
    }
    write_json(OUT / "V21.122_manifest.json", manifest)
    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"latest_price_date_used={latest}",
        f"source V21.121 status={v121.get('FINAL_STATUS', '')}",
        f"candidate_hierarchy_loaded={hierarchy_loaded}",
        f"primary_control={manifest['primary_control']}",
        f"primary_research_candidate={manifest['primary_research_candidate']}",
        f"secondary_research_candidates={manifest['secondary_research_candidates']}",
        f"D_original_status={manifest['D_original_status']}",
        f"D_R2C_status={manifest['D_R2C_status']}",
        f"all_matured_observation_count={all_matured_count}",
        f"newly_matured_observation_count={newly_count}",
        f"still_unmatured_observation_count={still_unmatured}",
        f"A1_remains_evidence_leader={a1_leader}",
        f"B_or_C_challenge_detected={bc_challenge}",
        f"D_R2C_overfit_status={overfit_status}",
        f"D_R2C_repeated_loser_reduction_meaningful={repeated_meaningful}",
        f"role_review_required={role_review_required}",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
        f"next recommended stage={manifest['next_recommended_stage']}",
    ]
    (OUT / "V21.122_forward_tracking_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, default=str))
    return manifest


if __name__ == "__main__":
    run()
