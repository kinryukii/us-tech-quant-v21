#!/usr/bin/env python
"""V21.117 early forward validity evaluator for frozen V21.116 ABCD ledgers."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.117_EARLY_FORWARD_VALIDITY_EVALUATOR"
OUT = ROOT / "outputs/v21/V21.117_EARLY_FORWARD_VALIDITY_EVALUATOR"
V116 = ROOT / "outputs/v21/V21.116_DAILY_TOP50_FULL_DATA_LEDGER_20260616_TO_LATEST"
V116_SUMMARY = V116 / "V21.116_daily_top50_full_data_ledger_summary.json"
RANKING_LEDGER = V116 / "daily_ABCD_top50_full_ledger.csv"
PRICE = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
BENCH = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"

STRATEGIES = ["A1_BASELINE_CONTROL", "B_STATIC_MOMENTUM_BLEND", "C_DYNAMIC_MOMENTUM_BLEND", "D_WEIGHT_OPTIMIZED_R1"]
TOP_NS = [20, 50]
HORIZONS = [1, 3, 5, 10, 20]
PAIRS = [
    ("D_WEIGHT_OPTIMIZED_R1", "A1_BASELINE_CONTROL"),
    ("D_WEIGHT_OPTIMIZED_R1", "B_STATIC_MOMENTUM_BLEND"),
    ("D_WEIGHT_OPTIMIZED_R1", "C_DYNAMIC_MOMENTUM_BLEND"),
    ("B_STATIC_MOMENTUM_BLEND", "A1_BASELINE_CONTROL"),
    ("C_DYNAMIC_MOMENTUM_BLEND", "A1_BASELINE_CONTROL"),
    ("C_DYNAMIC_MOMENTUM_BLEND", "B_STATIC_MOMENTUM_BLEND"),
]


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


def load_prices() -> tuple[pd.DataFrame, dict[tuple[str, str], float], list[str], str]:
    if not PRICE.is_file():
        raise FileNotFoundError(rel(PRICE))
    frames = []
    for path in [PRICE, BENCH]:
        if not path.is_file():
            continue
        usecols = ["symbol", "date", "close", "adjusted_close"]
        frame = pd.read_csv(path, usecols=usecols, low_memory=False)
        frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["px"] = pd.to_numeric(frame["adjusted_close"], errors="coerce").where(
            pd.to_numeric(frame["adjusted_close"], errors="coerce").notna(),
            pd.to_numeric(frame["close"], errors="coerce"),
        )
        frames.append(frame[["symbol", "date", "px"]])
    prices = pd.concat(frames, ignore_index=True).dropna(subset=["symbol", "date", "px"])
    prices = prices.drop_duplicates(["symbol", "date"], keep="last")
    prices["date_str"] = prices["date"].dt.strftime("%Y-%m-%d")
    price_map = {(r["symbol"], r["date_str"]): float(r["px"]) for r in prices.to_dict("records")}
    dates = sorted(d for d in prices["date_str"].unique() if pd.Timestamp(d).weekday() < 5 and d != "2026-06-19")
    latest = max(dates) if dates else ""
    return prices, price_map, dates, latest


def forward_end_date(as_of: str, horizon: int, trading_dates: list[str]) -> tuple[bool, str]:
    if as_of not in trading_dates:
        return False, ""
    idx = trading_dates.index(as_of)
    end_idx = idx + horizon
    if end_idx >= len(trading_dates):
        return False, ""
    return True, trading_dates[end_idx]


def member_returns(tickers: list[str], start: str, end: str, price_map: dict[tuple[str, str], float]) -> tuple[list[dict[str, Any]], int, int]:
    rows = []
    valid = 0
    missing = 0
    for ticker in tickers:
        start_px = price_map.get((ticker, start))
        end_px = price_map.get((ticker, end))
        if start_px is None or end_px is None or start_px == 0:
            missing += 1
            rows.append({"ticker": ticker, "member_return": math.nan, "missing_price": True})
        else:
            valid += 1
            rows.append({"ticker": ticker, "member_return": end_px / start_px - 1.0, "missing_price": False})
    return rows, valid, missing


def bench_return(symbol: str, start: str, end: str, price_map: dict[tuple[str, str], float]) -> float:
    start_px = price_map.get((symbol, start))
    end_px = price_map.get((symbol, end))
    if start_px is None or end_px is None or start_px == 0:
        return math.nan
    return end_px / start_px - 1.0


def summarize_returns(rows: list[dict[str, Any]]) -> dict[str, Any]:
    vals = [float(r["member_return"]) for r in rows if not pd.isna(r["member_return"])]
    if not vals:
        return {
            "equal_weight_return": math.nan,
            "median_member_return": math.nan,
            "hit_rate": math.nan,
            "best_contributor": "",
            "best_contributor_return": math.nan,
            "worst_contributor": "",
            "worst_contributor_return": math.nan,
        }
    best = max((r for r in rows if not pd.isna(r["member_return"])), key=lambda r: r["member_return"])
    worst = min((r for r in rows if not pd.isna(r["member_return"])), key=lambda r: r["member_return"])
    return {
        "equal_weight_return": float(pd.Series(vals).mean()),
        "median_member_return": float(pd.Series(vals).median()),
        "hit_rate": float(sum(1 for v in vals if v > 0) / len(vals)),
        "best_contributor": best["ticker"],
        "best_contributor_return": float(best["member_return"]),
        "worst_contributor": worst["ticker"],
        "worst_contributor_return": float(worst["member_return"]),
    }


def source_inputs_ok() -> tuple[bool, list[str], dict[str, Any]]:
    missing = []
    if not V116_SUMMARY.is_file():
        missing.append(rel(V116_SUMMARY))
        source = {}
    else:
        source = json.loads(V116_SUMMARY.read_text(encoding="utf-8"))
    for path in [RANKING_LEDGER, PRICE]:
        if not path.is_file():
            missing.append(rel(path))
    if source:
        if not source.get("source_stage_full_recompute_confirmed"):
            missing.append("V21.116 source_stage_full_recompute_confirmed is not true")
        if int(source.get("source_stage_stale_factor_input_count", 999)) != 0:
            missing.append("V21.116 source_stage_stale_factor_input_count is not zero")
        if source.get("any_prior_ranking_reuse_detected"):
            missing.append("V21.116 prior ranking reuse detected")
    return not missing, missing, source


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    ok, missing, source = source_inputs_ok()
    if not ok:
        manifest = {
            "FINAL_STATUS": "BLOCKED_V21_117_MISSING_REQUIRED_INPUTS",
            "DECISION": "DO_NOT_USE_EARLY_FORWARD_VALIDATION",
            "missing_inputs": missing,
            "protected_outputs_modified": False,
            "official_adoption_allowed": False,
            "broker_action_allowed": False,
            "research_only": True,
        }
        write_json(OUT / "V21.117_manifest.json", manifest)
        write_csv(OUT / "early_forward_validity_summary.csv", [{"status": "BLOCKED", "missing_inputs": "|".join(missing)}])
        (OUT / "V21.117_early_forward_validity_report.txt").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest, indent=2))
        return manifest

    _, price_map, trading_dates, latest_price = load_prices()
    ledger = pd.read_csv(RANKING_LEDGER, low_memory=False)
    ledger["as_of_date"] = ledger["as_of_date"].astype(str)
    ledger["ticker"] = ledger["ticker"].astype(str).str.upper().str.strip()
    ledger["rank"] = pd.to_numeric(ledger["rank"], errors="coerce")
    ranking_dates = sorted(ledger["as_of_date"].unique())

    by_date_rows = []
    contributor_rows = []
    data_quality = []
    for as_of in ranking_dates:
        malformed = as_of not in trading_dates
        for strategy in STRATEGIES:
            strat = ledger[(ledger["as_of_date"].eq(as_of)) & (ledger["strategy"].eq(strategy))]
            duplicated = int(strat.duplicated(["ticker"]).sum())
            for topn in TOP_NS:
                tickers = list(strat[strat["rank"].le(topn)].sort_values("rank")["ticker"])
                for horizon in HORIZONS:
                    matured, end = forward_end_date(as_of, horizon, trading_dates)
                    row = {
                        "as_of_date": as_of,
                        "strategy": strategy,
                        "top_n": topn,
                        "horizon": f"{horizon}D",
                        "start_date": as_of,
                        "end_date": end,
                        "matured": matured,
                        "member_count": len(tickers),
                        "valid_price_count": 0,
                        "missing_price_count": len(tickers) if not matured else 0,
                        "equal_weight_return": math.nan,
                        "median_member_return": math.nan,
                        "hit_rate": math.nan,
                        "best_contributor": "",
                        "worst_contributor": "",
                        "benchmark_QQQ_return": math.nan,
                        "benchmark_SOXX_return": math.nan,
                        "excess_vs_QQQ": math.nan,
                        "excess_vs_SOXX": math.nan,
                    }
                    if matured:
                        members, valid, missing_count = member_returns(tickers, as_of, end, price_map)
                        stats = summarize_returns(members)
                        qqq = bench_return("QQQ", as_of, end, price_map)
                        soxx = bench_return("SOXX", as_of, end, price_map)
                        row.update(stats)
                        row.update({
                            "valid_price_count": valid,
                            "missing_price_count": missing_count,
                            "benchmark_QQQ_return": qqq,
                            "benchmark_SOXX_return": soxx,
                            "excess_vs_QQQ": stats["equal_weight_return"] - qqq if not pd.isna(stats["equal_weight_return"]) and not pd.isna(qqq) else math.nan,
                            "excess_vs_SOXX": stats["equal_weight_return"] - soxx if not pd.isna(stats["equal_weight_return"]) and not pd.isna(soxx) else math.nan,
                        })
                        for m in members:
                            contributor_rows.append({
                                "as_of_date": as_of,
                                "strategy": strategy,
                                "top_n": topn,
                                "horizon": f"{horizon}D",
                                "start_date": as_of,
                                "end_date": end,
                                **m,
                            })
                    by_date_rows.append(row)
            data_quality.append({
                "as_of_date": as_of,
                "strategy": strategy,
                "malformed_ranking_date": malformed,
                "duplicated_ticker_count": duplicated,
                "non_trading_day_handled": malformed,
            })

    by_date = pd.DataFrame(by_date_rows)
    matured_df = by_date[by_date["matured"].eq(True)].copy()
    pair_rows = []
    for topn in TOP_NS:
        for horizon in [f"{h}D" for h in HORIZONS]:
            for left, right in PAIRS:
                l = matured_df[(matured_df["strategy"].eq(left)) & (matured_df["top_n"].eq(topn)) & (matured_df["horizon"].eq(horizon))]
                r = matured_df[(matured_df["strategy"].eq(right)) & (matured_df["top_n"].eq(topn)) & (matured_df["horizon"].eq(horizon))]
                merged = l.merge(r, on=["as_of_date", "top_n", "horizon"], suffixes=("_left", "_right"))
                diffs = merged["equal_weight_return_left"] - merged["equal_weight_return_right"] if len(merged) else pd.Series(dtype=float)
                diffs = diffs.dropna()
                pair_rows.append({
                    "pair": f"{left}_vs_{right}",
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

    top_compare_rows = []
    for strategy in STRATEGIES:
        t20 = matured_df[(matured_df["strategy"].eq(strategy)) & (matured_df["top_n"].eq(20))]
        t50 = matured_df[(matured_df["strategy"].eq(strategy)) & (matured_df["top_n"].eq(50))]
        merged = t20.merge(t50, on=["as_of_date", "strategy", "horizon"], suffixes=("_top20", "_top50"))
        diffs = (merged["equal_weight_return_top20"] - merged["equal_weight_return_top50"]).dropna()
        top_compare_rows.append({
            "strategy": strategy,
            "available_observations": len(diffs),
            "top20_win_rate_vs_top50": float((diffs > 0).sum() / len(diffs)) if len(diffs) else math.nan,
            "average_top20_minus_top50": float(diffs.mean()) if len(diffs) else math.nan,
            "median_top20_minus_top50": float(diffs.median()) if len(diffs) else math.nan,
        })

    benchmark_rows = []
    for strategy in STRATEGIES:
        for topn in TOP_NS:
            subset = matured_df[(matured_df["strategy"].eq(strategy)) & (matured_df["top_n"].eq(topn))]
            benchmark_rows.append({
                "strategy": strategy,
                "top_n": topn,
                "available_observations": int(len(subset)),
                "avg_excess_vs_QQQ": float(subset["excess_vs_QQQ"].dropna().mean()) if subset["excess_vs_QQQ"].notna().any() else math.nan,
                "avg_excess_vs_SOXX": float(subset["excess_vs_SOXX"].dropna().mean()) if subset["excess_vs_SOXX"].notna().any() else math.nan,
                "qqq_observations": int(subset["excess_vs_QQQ"].notna().sum()),
                "soxx_observations": int(subset["excess_vs_SOXX"].notna().sum()),
            })

    contrib = pd.DataFrame(contributor_rows)
    d_contrib = contrib[(contrib["strategy"].eq("D_WEIGHT_OPTIMIZED_R1")) & (contrib["missing_price"].eq(False))].copy() if not contrib.empty else pd.DataFrame()
    losers = []
    worst_rows = []
    if not d_contrib.empty:
        loss_group = d_contrib[d_contrib["member_return"] < 0].groupby(["ticker", "top_n"])["member_return"].agg(["count", "mean", "min"]).reset_index()
        losers = loss_group.sort_values(["count", "mean"], ascending=[False, True]).rename(columns={"count": "loss_count", "mean": "avg_loss_return", "min": "worst_return"}).to_dict("records")
        worst_rows = d_contrib.sort_values("member_return").head(100).to_dict("records")

    d_rank = ledger[ledger["strategy"].eq("D_WEIGHT_OPTIMIZED_R1")].copy()
    persistence = d_rank.groupby("ticker").agg(
        snapshot_count=("as_of_date", "nunique"),
        top20_count=("in_top20", lambda x: int(pd.Series(x).astype(str).str.upper().isin(["TRUE", "1"]).sum())),
        top50_count=("in_top50", lambda x: int(pd.Series(x).astype(str).str.upper().isin(["TRUE", "1"]).sum())),
        avg_rank=("rank", "mean"),
        best_rank=("rank", "min"),
        worst_rank=("rank", "max"),
    ).reset_index().sort_values(["top50_count", "avg_rank"], ascending=[False, True])

    summary_rows = []
    for strategy in STRATEGIES:
        for topn in TOP_NS:
            subset = matured_df[(matured_df["strategy"].eq(strategy)) & (matured_df["top_n"].eq(topn))]
            summary_rows.append({
                "strategy": strategy,
                "top_n": topn,
                "matured_observation_count": int(len(subset)),
                "avg_equal_weight_return": float(subset["equal_weight_return"].dropna().mean()) if subset["equal_weight_return"].notna().any() else math.nan,
                "median_equal_weight_return": float(subset["equal_weight_return"].dropna().median()) if subset["equal_weight_return"].notna().any() else math.nan,
                "avg_hit_rate": float(subset["hit_rate"].dropna().mean()) if subset["hit_rate"].notna().any() else math.nan,
                "avg_excess_vs_QQQ": float(subset["excess_vs_QQQ"].dropna().mean()) if subset["excess_vs_QQQ"].notna().any() else math.nan,
                "avg_excess_vs_SOXX": float(subset["excess_vs_SOXX"].dropna().mean()) if subset["excess_vs_SOXX"].notna().any() else math.nan,
            })

    write_csv(OUT / "early_forward_validity_summary.csv", summary_rows)
    by_date.to_csv(OUT / "early_forward_by_date_horizon.csv", index=False)
    write_csv(OUT / "strategy_pairwise_winrate.csv", pair_rows)
    write_csv(OUT / "top20_top50_comparison.csv", top_compare_rows)
    write_csv(OUT / "benchmark_comparison_qqq_soxx.csv", benchmark_rows)
    write_csv(OUT / "d_repeated_losers.csv", losers)
    write_csv(OUT / "d_worst_contributors.csv", worst_rows)
    persistence.to_csv(OUT / "ranking_persistence.csv", index=False)
    write_csv(OUT / "data_quality_diagnostics.csv", data_quality)

    pair_df = pd.DataFrame(pair_rows)
    def pair_metric(pair: str, topn: int, field: str) -> float:
        sub = pair_df[(pair_df["pair"].eq(pair)) & (pair_df["top_n"].eq(topn))]
        sub = sub[sub["available_observations"] > 0]
        if sub.empty:
            return math.nan
        return float(sub[field].mean())

    d_a1_win = pair_metric("D_WEIGHT_OPTIMIZED_R1_vs_A1_BASELINE_CONTROL", 20, "win_rate")
    d_b_win = pair_metric("D_WEIGHT_OPTIMIZED_R1_vs_B_STATIC_MOMENTUM_BLEND", 20, "win_rate")
    d_c_win = pair_metric("D_WEIGHT_OPTIMIZED_R1_vs_C_DYNAMIC_MOMENTUM_BLEND", 20, "win_rate")
    d_bench = pd.DataFrame(benchmark_rows)
    d20_bench = d_bench[(d_bench["strategy"].eq("D_WEIGHT_OPTIMIZED_R1")) & (d_bench["top_n"].eq(20))]
    d_qqq_excess = float(d20_bench["avg_excess_vs_QQQ"].iloc[0]) if len(d20_bench) else math.nan
    d_soxx_excess = float(d20_bench["avg_excess_vs_SOXX"].iloc[0]) if len(d20_bench) else math.nan
    repeated_loser_count = int(sum(1 for r in losers if int(r.get("loss_count", 0)) >= 3 and r.get("top_n") == 20))
    obs_count = int(len(matured_df))
    unmatured_count = int((~by_date["matured"]).sum())
    severe_left_tail = repeated_loser_count >= 5

    if obs_count == 0:
        final_status = "BLOCKED_V21_117_MISSING_REQUIRED_INPUTS"
        decision = "DO_NOT_USE_EARLY_FORWARD_VALIDATION"
        edge = "inconclusive"
    elif d_a1_win > 0.5 and min(d_b_win, d_c_win) >= 0.4 and (d_qqq_excess > 0 or d_soxx_excess > 0) and not severe_left_tail:
        final_status = "PASS_V21_117_EARLY_D_FORWARD_EDGE_CONFIRMED"
        decision = "D_EARLY_FORWARD_EDGE_CONFIRMED_RESEARCH_ONLY"
        edge = "confirmed"
    elif d_a1_win > 0.5 or d_qqq_excess > 0 or d_soxx_excess > 0:
        final_status = "PARTIAL_PASS_V21_117_EARLY_EDGE_INCONCLUSIVE"
        decision = "D_EARLY_FORWARD_EDGE_INCONCLUSIVE_RESEARCH_ONLY"
        edge = "inconclusive"
    else:
        final_status = "WARN_V21_117_D_EARLY_FORWARD_EDGE_NOT_CONFIRMED"
        decision = "D_EARLY_FORWARD_EDGE_NOT_CONFIRMED_RESEARCH_ONLY"
        edge = "not confirmed"

    d50_stability = "stable" if float(persistence["top50_count"].mean()) >= 2 else "unstable"
    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_used": latest_price,
        "ranking_dates_evaluated": ranking_dates,
        "matured_observation_count": obs_count,
        "unmatured_observation_count": unmatured_count,
        "D_vs_A1_Top20_win_rate": d_a1_win,
        "D_vs_B_Top20_win_rate": d_b_win,
        "D_vs_C_Top20_win_rate": d_c_win,
        "D_vs_QQQ_Top20_excess_average": d_qqq_excess,
        "D_vs_SOXX_Top20_excess_average": d_soxx_excess,
        "D_Top20_repeated_loser_count": repeated_loser_count,
        "D_Top50_stability_assessment": d50_stability,
        "D_early_forward_edge": edge,
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "source_ranking_ledger": rel(RANKING_LEDGER),
        "source_price_panel": rel(PRICE),
    }
    write_json(OUT / "V21.117_manifest.json", manifest)

    report = [
        f"{STAGE}",
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"latest_price_date_used={latest_price}",
        f"ranking_dates_evaluated={', '.join(ranking_dates)}",
        f"matured_observation_count={obs_count}",
        f"unmatured_observation_count={unmatured_count}",
        f"D vs A1 Top20 win rate={d_a1_win}",
        f"D vs B Top20 win rate={d_b_win}",
        f"D vs C Top20 win rate={d_c_win}",
        f"D vs QQQ Top20 excess average={d_qqq_excess}",
        f"D vs SOXX Top20 excess average={d_soxx_excess}",
        f"D Top20 repeated loser count={repeated_loser_count}",
        f"D Top50 stability assessment={d50_stability}",
        f"D early forward edge={edge}",
        "",
        "Notes:",
        "- Horizons use trading-day offsets from the canonical price calendar, with 2026-06-19 excluded as a market holiday.",
        "- 10D and 20D horizons are expected to be unmatured for this early window unless enough later trading days exist.",
        "- Missing member prices are counted and are not converted to zero returns.",
        "- V21.116 rankings are treated as frozen snapshots; no historical ranking recomputation is performed.",
    ]
    (OUT / "V21.117_early_forward_validity_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, default=str))
    return manifest


if __name__ == "__main__":
    run()
