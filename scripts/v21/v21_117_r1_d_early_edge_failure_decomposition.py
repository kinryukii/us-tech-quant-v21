#!/usr/bin/env python
"""V21.117 R1 D early edge failure decomposition."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.117_R1_D_EARLY_EDGE_FAILURE_DECOMPOSITION"
OUT = ROOT / "outputs/v21/V21.117_R1_D_EARLY_EDGE_FAILURE_DECOMPOSITION"
V117 = ROOT / "outputs/v21/V21.117_EARLY_FORWARD_VALIDITY_EVALUATOR"
V116 = ROOT / "outputs/v21/V21.116_DAILY_TOP50_FULL_DATA_LEDGER_20260616_TO_LATEST"
PRICE = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
EXPOSURE20 = ROOT / "outputs/v21/V21.111_D_FAILURE_MODE_DECOMPOSITION/exposure_top20.csv"
EXPOSURE50 = ROOT / "outputs/v21/V21.111_D_FAILURE_MODE_DECOMPOSITION/exposure_top50.csv"

FWD = V117 / "early_forward_by_date_horizon.csv"
LOSERS = V117 / "d_repeated_losers.csv"
WORST = V117 / "d_worst_contributors.csv"
MANIFEST = V117 / "V21.117_manifest.json"
RANKS = V116 / "daily_ABCD_top50_full_ledger.csv"

STRATEGIES = ["A1_BASELINE_CONTROL", "B_STATIC_MOMENTUM_BLEND", "C_DYNAMIC_MOMENTUM_BLEND", "D_WEIGHT_OPTIMIZED_R1"]
NON_D = ["A1_BASELINE_CONTROL", "B_STATIC_MOMENTUM_BLEND", "C_DYNAMIC_MOMENTUM_BLEND"]


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
    missing = [rel(p) for p in [FWD, LOSERS, WORST, MANIFEST, RANKS, PRICE] if not p.is_file()]
    return not missing, missing


def load_exposure_metadata() -> dict[str, dict[str, str]]:
    meta: dict[str, dict[str, str]] = {}
    for path in [EXPOSURE20, EXPOSURE50]:
        if not path.is_file():
            continue
        try:
            df = pd.read_csv(path, low_memory=False)
        except Exception:
            continue
        if "ticker" not in df.columns:
            continue
        for row in df.to_dict("records"):
            ticker = clean(row.get("ticker")).upper()
            if not ticker:
                continue
            cur = meta.setdefault(ticker, {})
            for col in ["sector", "industry", "bucket", "exposure_type"]:
                if clean(row.get(col)) and col not in cur:
                    cur[col] = clean(row.get(col))
    return meta


def price_map() -> dict[tuple[str, str], float]:
    df = pd.read_csv(PRICE, usecols=["symbol", "date", "close", "adjusted_close"], low_memory=False)
    df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    adj = pd.to_numeric(df["adjusted_close"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")
    df["px"] = adj.where(adj.notna(), close)
    df = df.dropna(subset=["symbol", "date", "px"]).drop_duplicates(["symbol", "date"], keep="last")
    return {(r["symbol"], r["date"]): float(r["px"]) for r in df.to_dict("records")}


def member_return(ticker: str, start: str, end: str, prices: dict[tuple[str, str], float]) -> float:
    start_px = prices.get((ticker, start))
    end_px = prices.get((ticker, end))
    if start_px is None or end_px is None or start_px == 0:
        return math.nan
    return end_px / start_px - 1.0


def underperformance(fwd: pd.DataFrame) -> list[dict[str, Any]]:
    m = fwd[fwd["matured"].astype(str).str.upper().eq("TRUE")].copy()
    rows = []
    for (as_of, horizon, topn), group in m.groupby(["as_of_date", "horizon", "top_n"], sort=True):
        vals = {r["strategy"]: r for r in group.to_dict("records")}
        if "D_WEIGHT_OPTIMIZED_R1" not in vals:
            continue
        d = vals["D_WEIGHT_OPTIMIZED_R1"]
        returns = {s: vals.get(s, {}).get("equal_weight_return", math.nan) for s in STRATEGIES}
        candidates = {**returns, "QQQ": d.get("benchmark_QQQ_return", math.nan), "SOXX": d.get("benchmark_SOXX_return", math.nan)}
        valid = {k: v for k, v in candidates.items() if not pd.isna(v)}
        winner = max(valid, key=valid.get) if valid else ""
        loser = min(valid, key=valid.get) if valid else ""
        rows.append({
            "ranking_date": as_of,
            "horizon": horizon,
            "topN": topn,
            "D_return": returns["D_WEIGHT_OPTIMIZED_R1"],
            "A1_return": returns["A1_BASELINE_CONTROL"],
            "B_return": returns["B_STATIC_MOMENTUM_BLEND"],
            "C_return": returns["C_DYNAMIC_MOMENTUM_BLEND"],
            "QQQ_return": d.get("benchmark_QQQ_return", math.nan),
            "SOXX_return": d.get("benchmark_SOXX_return", math.nan),
            "D_minus_A1": returns["D_WEIGHT_OPTIMIZED_R1"] - returns["A1_BASELINE_CONTROL"],
            "D_minus_B": returns["D_WEIGHT_OPTIMIZED_R1"] - returns["B_STATIC_MOMENTUM_BLEND"],
            "D_minus_C": returns["D_WEIGHT_OPTIMIZED_R1"] - returns["C_DYNAMIC_MOMENTUM_BLEND"],
            "D_minus_QQQ": d.get("excess_vs_QQQ", math.nan),
            "D_minus_SOXX": d.get("excess_vs_SOXX", math.nan),
            "winner_variant": winner,
            "loser_variant": loser,
        })
    return rows


def top20_top50_decomp(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, float]]:
    df = pd.DataFrame(rows)
    out = []
    if df.empty:
        return out, {"avg": math.nan, "median": math.nan}
    d = df[["ranking_date", "horizon", "topN", "D_return"]].copy()
    t20 = d[d["topN"].eq(20)]
    t50 = d[d["topN"].eq(50)]
    merged = t20.merge(t50, on=["ranking_date", "horizon"], suffixes=("_top20", "_top50"))
    merged["top20_minus_top50_excess"] = merged["D_return_top20"] - merged["D_return_top50"]
    for row in merged.to_dict("records"):
        excess = row["top20_minus_top50_excess"]
        out.append({
            "ranking_date": row["ranking_date"],
            "horizon": row["horizon"],
            "D_top20_return": row["D_return_top20"],
            "D_top50_return": row["D_return_top50"],
            "top20_minus_top50_excess": excess,
            "concentration_helped_or_hurt": "HELPED" if excess > 0 else "HURT" if excess < 0 else "NEUTRAL",
        })
    return out, {"avg": float(merged["top20_minus_top50_excess"].mean()), "median": float(merged["top20_minus_top50_excess"].median())}


def repeated_loser_attr(losers: pd.DataFrame, worst: pd.DataFrame, ranks: pd.DataFrame, meta: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    rows = []
    top20_losers = losers[losers["top_n"].eq(20)].copy()
    for loser in top20_losers.to_dict("records"):
        ticker = clean(loser["ticker"]).upper()
        events = worst[(worst["ticker"].astype(str).str.upper().eq(ticker)) & (worst["top_n"].eq(20))]
        b_or_c_count = 0
        unique_d_count = 0
        for event in events.to_dict("records"):
            as_of = clean(event["as_of_date"])
            snapshot = ranks[ranks["as_of_date"].astype(str).eq(as_of)]
            in_d = not snapshot[(snapshot["strategy"].eq("D_WEIGHT_OPTIMIZED_R1")) & (snapshot["ticker"].eq(ticker)) & (snapshot["rank"].le(20))].empty
            in_b = not snapshot[(snapshot["strategy"].eq("B_STATIC_MOMENTUM_BLEND")) & (snapshot["ticker"].eq(ticker)) & (snapshot["rank"].le(20))].empty
            in_c = not snapshot[(snapshot["strategy"].eq("C_DYNAMIC_MOMENTUM_BLEND")) & (snapshot["ticker"].eq(ticker)) & (snapshot["rank"].le(20))].empty
            if in_b or in_c:
                b_or_c_count += 1
            if in_d and not in_b and not in_c:
                unique_d_count += 1
        m = meta.get(ticker, {})
        rows.append({
            "ticker": ticker,
            "loss_count": int(loser["loss_count"]),
            "avg_return_contribution": loser["avg_loss_return"],
            "worst_single_period_contribution": loser["worst_return"],
            "appears_in_B_or_C_top20_same_date_count": b_or_c_count,
            "unique_to_D_top20_loss_event_count": unique_d_count,
            "sector": m.get("sector", m.get("bucket", "")),
            "industry": m.get("industry", ""),
        })
    return rows


def missed_winners(ranks: pd.DataFrame, prices: dict[tuple[str, str], float], fwd: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    matured = fwd[fwd["matured"].astype(str).str.upper().eq("TRUE")]
    for event in matured[matured["top_n"].eq(20)].to_dict("records"):
        as_of = clean(event["as_of_date"])
        end = clean(event["end_date"])
        if not end:
            continue
        snap = ranks[ranks["as_of_date"].astype(str).eq(as_of)]
        d20 = set(snap[(snap["strategy"].eq("D_WEIGHT_OPTIMIZED_R1")) & (snap["rank"].le(20))]["ticker"])
        for strategy in NON_D:
            s20 = snap[(snap["strategy"].eq(strategy)) & (snap["rank"].le(20))].copy()
            for r in s20.to_dict("records"):
                ticker = r["ticker"]
                if ticker in d20:
                    continue
                ret = member_return(ticker, as_of, end, prices)
                if pd.isna(ret) or ret <= 0:
                    continue
                d_rank = snap[(snap["strategy"].eq("D_WEIGHT_OPTIMIZED_R1")) & (snap["ticker"].eq(ticker))]
                d_rank_value = "" if d_rank.empty else int(d_rank.iloc[0]["rank"])
                status = "D_EXCLUDED" if d_rank.empty else "D_INCLUDED_OUTSIDE_TOP20" if d_rank_value > 20 else "D_INCLUDED_TOP20"
                rows.append({
                    "ranking_date": as_of,
                    "horizon": event["horizon"],
                    "end_date": end,
                    "winner_ticker": ticker,
                    "source_strategy": strategy,
                    "source_rank": int(r["rank"]),
                    "member_return": ret,
                    "d_rank": d_rank_value,
                    "d_status": status,
                })
    return sorted(rows, key=lambda x: x["member_return"], reverse=True)


def soxx_decomp(rows: list[dict[str, Any]], repeated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    repeated_set = {r["ticker"] for r in repeated if int(r["loss_count"]) >= 3}
    out = []
    for row in rows:
        if row["topN"] not in {20, 50} or pd.isna(row["D_minus_SOXX"]):
            continue
        under = row["D_minus_SOXX"] < 0
        d_vs_top50 = ""
        cause = "OUTPERFORMED_SOXX"
        if under:
            if row["topN"] == 20:
                cause = "CONCENTRATION_EFFECT_OR_STOCK_SELECTION_DRAG"
            else:
                cause = "STOCK_SELECTION_DRAG_VS_SOXX"
            if row["D_minus_A1"] < 0 and row["D_minus_B"] < 0 and row["D_minus_C"] < 0:
                cause = "STOCK_SELECTION_DRAG"
        out.append({
            "ranking_date": row["ranking_date"],
            "horizon": row["horizon"],
            "topN": row["topN"],
            "D_return": row["D_return"],
            "SOXX_return": row["SOXX_return"],
            "D_minus_SOXX": row["D_minus_SOXX"],
            "underperformed_SOXX": under,
            "attribution": cause,
            "repeated_loser_set_used": "|".join(sorted(repeated_set)),
        })
    return out


def churn(ranks: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    prev20: set[str] | None = None
    prev50: set[str] | None = None
    for as_of in sorted(ranks["as_of_date"].astype(str).unique()):
        d = ranks[(ranks["as_of_date"].astype(str).eq(as_of)) & (ranks["strategy"].eq("D_WEIGHT_OPTIMIZED_R1"))]
        cur20 = set(d[d["rank"].le(20)]["ticker"])
        cur50 = set(d[d["rank"].le(50)]["ticker"])
        rows.append({
            "ranking_date": as_of,
            "top20_overlap_prev": "" if prev20 is None else len(cur20 & prev20),
            "top20_entrants": "" if prev20 is None else "|".join(sorted(cur20 - prev20)),
            "top20_removals": "" if prev20 is None else "|".join(sorted(prev20 - cur20)),
            "top50_overlap_prev": "" if prev50 is None else len(cur50 & prev50),
            "top50_entrants": "" if prev50 is None else "|".join(sorted(cur50 - prev50)),
            "top50_removals": "" if prev50 is None else "|".join(sorted(prev50 - cur50)),
            "repeated_losers_persist_too_long": "",
            "winners_removed_too_early": "",
        })
        prev20, prev50 = cur20, cur50
    return rows


def bc_rescue(ranks: pd.DataFrame, repeated: list[dict[str, Any]], missed: list[dict[str, Any]], under_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    repeated_set = {r["ticker"] for r in repeated if int(r["loss_count"]) >= 3}
    rows = []
    for as_of in sorted(ranks["as_of_date"].astype(str).unique()):
        snap = ranks[ranks["as_of_date"].astype(str).eq(as_of)]
        d20 = set(snap[(snap["strategy"].eq("D_WEIGHT_OPTIMIZED_R1")) & (snap["rank"].le(20))]["ticker"])
        for strategy in ["B_STATIC_MOMENTUM_BLEND", "C_DYNAMIC_MOMENTUM_BLEND"]:
            s20 = set(snap[(snap["strategy"].eq(strategy)) & (snap["rank"].le(20))]["ticker"])
            avoided = sorted((d20 & repeated_set) - s20)
            included_winners = sorted({m["winner_ticker"] for m in missed if m["ranking_date"] == as_of and m["source_strategy"] == strategy})
            rows.append({
                "ranking_date": as_of,
                "strategy": strategy,
                "avoided_d_repeated_loser_count": len(avoided),
                "avoided_d_repeated_losers": "|".join(avoided),
                "included_missed_winner_count": len(included_winners),
                "included_missed_winners": "|".join(included_winners[:20]),
                "evidence_favors": "B_OR_C" if avoided or included_winners else "NO_CLEAR_VARIANT",
            })
    return rows


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    ok, missing = required_ok()
    if not ok:
        manifest = {
            "FINAL_STATUS": "BLOCKED_V21_117_R1_MISSING_INPUTS",
            "DECISION": "DO_NOT_USE_FAILURE_DECOMPOSITION",
            "missing_inputs": missing,
            "protected_outputs_modified": False,
            "official_adoption_allowed": False,
            "broker_action_allowed": False,
            "research_only": True,
        }
        write_json(OUT / "V21.117_R1_manifest.json", manifest)
        write_csv(OUT / "d_underperformance_by_date_horizon.csv", [{"missing_inputs": "|".join(missing)}])
        (OUT / "V21.117_R1_failure_decomposition_report.txt").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest, indent=2))
        return manifest

    source_manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    fwd = pd.read_csv(FWD, low_memory=False)
    losers = pd.read_csv(LOSERS, low_memory=False)
    worst = pd.read_csv(WORST, low_memory=False)
    ranks = pd.read_csv(RANKS, low_memory=False)
    ranks["rank"] = pd.to_numeric(ranks["rank"], errors="coerce")
    ranks["ticker"] = ranks["ticker"].astype(str).str.upper().str.strip()
    prices = price_map()
    meta = load_exposure_metadata()

    under_rows = underperformance(fwd)
    t20_t50_rows, t20_t50_stats = top20_top50_decomp(under_rows)
    repeated_rows = repeated_loser_attr(losers, worst, ranks, meta)
    missed_rows = missed_winners(ranks, prices, fwd)
    soxx_rows = soxx_decomp(under_rows, repeated_rows)
    churn_rows = churn(ranks)
    rescue_rows = bc_rescue(ranks, repeated_rows, missed_rows, under_rows)

    write_csv(OUT / "d_underperformance_by_date_horizon.csv", under_rows)
    write_csv(OUT / "d_top20_vs_top50_decomposition.csv", t20_t50_rows)
    write_csv(OUT / "d_repeated_loser_attribution.csv", repeated_rows)
    write_csv(OUT / "missed_winners_vs_d.csv", missed_rows)
    write_csv(OUT / "d_vs_soxx_decomposition.csv", soxx_rows)
    write_csv(OUT / "d_ranking_churn.csv", churn_rows)
    write_csv(OUT / "bc_rescue_analysis.csv", rescue_rows)

    under_df = pd.DataFrame(under_rows)
    soxx_df = pd.DataFrame(soxx_rows)
    repeated_count = sum(1 for r in repeated_rows if int(r["loss_count"]) >= 3)
    avg_top20_minus_top50 = t20_t50_stats["avg"]
    d_vs_soxx_under_rate = float(soxx_df["underperformed_SOXX"].mean()) if not soxx_df.empty else math.nan
    d_losses_vs_all = int(((under_df["D_minus_A1"] < 0) & (under_df["D_minus_B"] < 0) & (under_df["D_minus_C"] < 0)).sum()) if not under_df.empty else 0

    weaknesses = {
        "D_TOP20_CONCENTRATION_DRAG": abs(avg_top20_minus_top50) if not pd.isna(avg_top20_minus_top50) and avg_top20_minus_top50 < 0 else 0,
        "D_STOCK_SELECTION_DRAG_VS_SOXX": d_vs_soxx_under_rate if not pd.isna(d_vs_soxx_under_rate) else 0,
        "D_REPEATED_LOSER_DRAG": min(repeated_count / 10.0, 1.0),
    }
    primary = max(weaknesses, key=weaknesses.get) if weaknesses else "D_SAMPLE_TOO_SMALL"
    if int(source_manifest.get("matured_observation_count", 0)) < 20:
        primary = "D_SAMPLE_TOO_SMALL"
    elif sorted(weaknesses.values(), reverse=True)[0] - sorted(weaknesses.values(), reverse=True)[1] < 0.15:
        primary = "D_MIXED_INCONCLUSIVE"

    b_c_better = bool(
        source_manifest.get("D_vs_B_Top20_win_rate", 0) < 0.5
        or source_manifest.get("D_vs_C_Top20_win_rate", 0) < 0.5
    )
    d_top50_worth = bool(t20_t50_stats["avg"] < 0 or source_manifest.get("D_Top50_stability_assessment") == "stable")
    d_r2_allowed = primary not in {"D_MIXED_INCONCLUSIVE", "D_SAMPLE_TOO_SMALL"} and max(weaknesses.values()) >= 0.65

    if primary in {"D_TOP20_CONCENTRATION_DRAG", "D_STOCK_SELECTION_DRAG_VS_SOXX", "D_REPEATED_LOSER_DRAG"} and d_r2_allowed:
        final_status = "PASS_V21_117_R1_FAILURE_MODE_IDENTIFIED"
        decision = "FAILURE_MODE_IDENTIFIED_RESEARCH_ONLY"
    elif primary == "D_REPEATED_LOSER_DRAG" and repeated_count >= 10:
        final_status = "WARN_V21_117_R1_D_TOP20_NOT_SUPPORTED"
        decision = "D_TOP20_NOT_SUPPORTED_RESEARCH_ONLY"
    else:
        final_status = "PARTIAL_PASS_V21_117_R1_MIXED_FAILURE_MODE"
        decision = "MIXED_FAILURE_MODE_RESEARCH_ONLY"

    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "source_v21_117_status": source_manifest.get("FINAL_STATUS", ""),
        "latest_price_date_used": source_manifest.get("latest_price_date_used", ""),
        "matured_observations_analyzed": source_manifest.get("matured_observation_count", 0),
        "primary_D_weakness_classification": primary,
        "B_or_C_currently_looks_better_than_D": b_c_better,
        "D_Top50_remains_worth_tracking": d_top50_worth,
        "D_R2_design_allowed_now": d_r2_allowed,
        "additional_maturity_required": not d_r2_allowed,
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
    }
    write_json(OUT / "V21.117_R1_manifest.json", manifest)

    report = [
        f"{STAGE}",
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"source V21.117 status={source_manifest.get('FINAL_STATUS', '')}",
        f"latest_price_date_used={source_manifest.get('latest_price_date_used', '')}",
        f"matured observations analyzed={source_manifest.get('matured_observation_count', 0)}",
        f"primary D weakness classification={primary}",
        f"whether B or C currently looks better than D={b_c_better}",
        f"whether D Top50 remains worth tracking={d_top50_worth}",
        f"whether D-R2 design is allowed now={d_r2_allowed}",
        f"whether additional maturity is required={not d_r2_allowed}",
        "",
        "Summary:",
        f"- average D Top20 minus D Top50 excess={avg_top20_minus_top50}",
        f"- D underperformed SOXX rate={d_vs_soxx_under_rate}",
        f"- repeated D Top20 loser count={repeated_count}",
        f"- D losses vs A1/B/C on same observation count={d_losses_vs_all}",
    ]
    (OUT / "V21.117_R1_failure_decomposition_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, default=str))
    return manifest


if __name__ == "__main__":
    run()
