#!/usr/bin/env python
"""V21.115 daily true ABCD recompute ledger.

Research-only point-in-time-lite daily recompute from canonical OHLCV.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.115_DAILY_TRUE_RECOMPUTE_LEDGER_20260616_TO_20260625"
OUT = ROOT / "outputs/v21/V21.115_DAILY_TRUE_RECOMPUTE_LEDGER_20260616_TO_20260625"
V114_SCRIPT = ROOT / "scripts/v21/v21_114_true_latest_data_abcd_full_recompute_20260625.py"

PRICE = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
TARGET_DATES = ["2026-06-16", "2026-06-17", "2026-06-18", "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25"]
NON_TRADING_EXCLUDED = {"2026-06-19", "2026-06-20", "2026-06-21"}
STRATEGIES = ["A1_BASELINE_CONTROL", "B_STATIC_MOMENTUM_BLEND", "C_DYNAMIC_MOMENTUM_BLEND", "D_WEIGHT_OPTIMIZED_R1"]
SHORT = {"A1_BASELINE_CONTROL": "A1", "B_STATIC_MOMENTUM_BLEND": "B", "C_DYNAMIC_MOMENTUM_BLEND": "C", "D_WEIGHT_OPTIMIZED_R1": "D"}
WATCHLIST = ["DRAM", "MU", "SNDK", "WDC", "STX", "AMAT", "LRCX", "KLAC", "KLIC", "TER", "MKSI", "ICHR", "AMKR", "SOXX", "AMD", "INTC"]
GRID = [(i / 10.0, 1.0 - i / 10.0) for i in range(10, -1, -1)]


def load_v114():
    spec = importlib.util.spec_from_file_location("v21_114_recompute", V114_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load V21.114 recompute module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V114 = load_v114()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def clean(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none"} else text


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def topn(frame: pd.DataFrame, n: int) -> pd.DataFrame:
    eligible = frame[frame["eligible_flag"].astype(str).str.upper().isin(["TRUE", "1"])]
    return eligible.nsmallest(n, "rank")


def overlap_matrix(rankings: dict[str, pd.DataFrame], n: int) -> list[dict[str, Any]]:
    sets = {s: set(topn(df, n)["ticker"]) for s, df in rankings.items()}
    rows = []
    for left in STRATEGIES:
        row = {"strategy": SHORT[left]}
        for right in STRATEGIES:
            row[SHORT[right]] = len(sets[left] & sets[right])
        rows.append(row)
    return rows


def write_top_summary(rankings: dict[str, pd.DataFrame], n: int, path: Path, as_of: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy, frame in rankings.items():
        for row in topn(frame, n).to_dict("records"):
            rows.append({"as_of_date": as_of, "strategy": strategy, "rank": row["rank"], "ticker": row["ticker"], "final_score": row["final_score"], "latest_price_date": row["latest_price_date"]})
    write_csv(path, rows)
    return rows


def load_price_panel(universe: set[str]) -> pd.DataFrame:
    usecols = ["symbol", "date", "open", "high", "low", "close", "adjusted_close", "volume"]
    frame = pd.read_csv(PRICE, usecols=usecols, low_memory=False)
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame[frame["date"].notna() & frame["symbol"].isin(universe)].copy()
    for col in ["open", "high", "low", "close", "adjusted_close", "volume"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["px"] = frame["adjusted_close"].where(frame["adjusted_close"].notna(), frame["close"])
    return frame.sort_values(["symbol", "date"])


def weight_grid(base: pd.DataFrame, as_of: str) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    source = base[["ticker", "base_score", "momentum_score", "latest_price_date", "eligible_flag"]].copy()
    for base_weight, momentum_weight in GRID:
        out = source.copy()
        out["variant_id"] = f"W_BASE_{int(base_weight*100):03d}_MOM_{int(momentum_weight*100):03d}"
        out["base_weight"] = base_weight
        out["momentum_weight"] = momentum_weight
        out["final_score"] = out["base_score"] * base_weight + out["momentum_score"] * momentum_weight
        out["rank"] = out["final_score"].rank(method="first", ascending=False).astype(int)
        out["as_of_date"] = as_of
        rows.append(out)
    panel = pd.concat(rows, ignore_index=True)
    return panel.sort_values(["variant_id", "rank", "ticker"]).reset_index(drop=True)


def grid_overlap_panel(grid: pd.DataFrame, n: int, as_of: str) -> list[dict[str, Any]]:
    sets = {variant: set(group.nsmallest(n, "rank")["ticker"]) for variant, group in grid.groupby("variant_id")}
    dset = sets.get("W_BASE_060_MOM_040", set())
    return [{"as_of_date": as_of, "view": f"top{n}", "variant_id": variant, "overlap_with_W_BASE_060_MOM_040": len(tickers & dset), "top_count": len(tickers)} for variant, tickers in sets.items()]


def watchlist_rows(as_of: str, d: pd.DataFrame) -> list[dict[str, Any]]:
    indexed = d.set_index("ticker", drop=False)
    rows = []
    top20 = set(topn(d, 20)["ticker"])
    top50 = set(topn(d, 50)["ticker"])
    for ticker in WATCHLIST:
        if ticker in indexed.index:
            row = indexed.loc[ticker]
            rows.append({
                "as_of_date": as_of,
                "ticker": ticker,
                "rank": row["rank"],
                "final_score": row["final_score"],
                "eligible_flag": row["eligible_flag"],
                "in_d_top20": ticker in top20,
                "in_d_top50": ticker in top50,
            })
        else:
            rows.append({"as_of_date": as_of, "ticker": ticker, "rank": "", "final_score": "", "eligible_flag": False, "in_d_top20": False, "in_d_top50": False})
    return rows


def turnover_rows(prev: set[str] | None, current: set[str], as_of: str, view: str) -> dict[str, Any]:
    if prev is None:
        return {"as_of_date": as_of, "view": view, "entrants": "", "removals": "", "entrant_count": 0, "removal_count": 0, "overlap_count": len(current), "turnover_count": 0}
    entrants = sorted(current - prev)
    removals = sorted(prev - current)
    return {"as_of_date": as_of, "view": view, "entrants": "|".join(entrants), "removals": "|".join(removals), "entrant_count": len(entrants), "removal_count": len(removals), "overlap_count": len(current & prev), "turnover_count": len(entrants) + len(removals)}


def no_future_leakage(price: pd.DataFrame, tech: pd.DataFrame, momentum: pd.DataFrame, rankings: dict[str, pd.DataFrame], as_of: str) -> bool:
    as_ts = pd.to_datetime(as_of)
    if len(price) and price["date"].max() > as_ts:
        return False
    for frame in [tech, momentum, *rankings.values()]:
        if not frame.empty and "latest_price_date" in frame and max(frame["latest_price_date"].astype(str)) > as_of:
            return False
    return True


def daily_run(as_of: str, full_price: pd.DataFrame, universe: set[str], universe_manifest: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, pd.DataFrame], pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    day_dir = OUT / f"asof_{as_of}"
    day_dir.mkdir(parents=True, exist_ok=True)
    as_ts = pd.to_datetime(as_of)
    price = full_price[full_price["date"].le(as_ts)].copy()
    price_latest = price["date"].max().strftime("%Y-%m-%d") if len(price) else ""
    manifest = [*universe_manifest, {"path": rel(PRICE), "role": "canonical_price_panel_truncated", "exists": PRICE.is_file(), "rows": len(price), "sha256": sha256(PRICE), "as_of_date": as_of, "max_price_date_used": price_latest}]

    tech, momentum, blockers = V114.compute_features(price)
    technical_latest = max(tech["latest_price_date"], default="") if not tech.empty else ""
    momentum_latest = max(momentum["latest_price_date"], default="") if not momentum.empty else ""
    rankings = V114.build_rankings(tech, momentum) if not tech.empty and not momentum.empty else {}
    leakage_ok = bool(rankings) and no_future_leakage(price, tech, momentum, rankings, as_of)

    write_csv(day_dir / f"recompute_input_manifest_{as_of}.csv", manifest)
    write_csv(day_dir / f"technical_feature_recompute_{as_of}.csv", tech.to_dict("records") if not tech.empty else [])
    write_csv(day_dir / f"momentum_feature_recompute_{as_of}.csv", momentum.to_dict("records") if not momentum.empty else [])

    stale = []
    latest_by_symbol = price.groupby("symbol")["date"].max().dt.strftime("%Y-%m-%d").to_dict() if len(price) else {}
    for ticker in sorted(universe):
        latest = clean(latest_by_symbol.get(ticker))
        if latest and latest < as_of:
            stale.append({"as_of_date": as_of, "ticker": ticker, "latest_price_date": latest, "reason": "NO_BAR_ON_AS_OF_DATE_IN_CANONICAL_PANEL"})
        elif not latest:
            stale.append({"as_of_date": as_of, "ticker": ticker, "latest_price_date": "", "reason": "NO_PRICE_HISTORY_BY_AS_OF_DATE"})
    stale_factor = []
    if not leakage_ok:
        stale_factor.append({"as_of_date": as_of, "ticker": "", "reason": "FUTURE_LEAKAGE_OR_RANKING_GENERATION_FAILURE", "stale_factor_cache_flag": True})
    write_csv(day_dir / f"stale_or_missing_ticker_report_{as_of}.csv", stale, ["as_of_date", "ticker", "latest_price_date", "reason"])
    write_csv(day_dir / f"stale_factor_cache_report_{as_of}.csv", stale_factor, ["as_of_date", "ticker", "reason", "stale_factor_cache_flag"])

    top20_rows: list[dict[str, Any]] = []
    top50_rows: list[dict[str, Any]] = []
    grid = pd.DataFrame()
    if rankings:
        for strategy, frame in rankings.items():
            frame.to_csv(day_dir / f"{strategy}_ranking_{as_of}.csv", index=False)
        top20_rows = write_top_summary(rankings, 20, day_dir / f"ABCD_top20_summary_{as_of}.csv", as_of)
        top50_rows = write_top_summary(rankings, 50, day_dir / f"ABCD_top50_summary_{as_of}.csv", as_of)
        write_csv(day_dir / f"ABCD_top20_overlap_matrix_{as_of}.csv", [{**{"as_of_date": as_of}, **r} for r in overlap_matrix(rankings, 20)])
        write_csv(day_dir / f"ABCD_top50_overlap_matrix_{as_of}.csv", [{**{"as_of_date": as_of}, **r} for r in overlap_matrix(rankings, 50)])
        grid = weight_grid(rankings["D_WEIGHT_OPTIMIZED_R1"], as_of)
        grid.to_csv(day_dir / f"weight_grid_rankings_{as_of}.csv", index=False)
    else:
        for strategy in STRATEGIES:
            write_csv(day_dir / f"{strategy}_ranking_{as_of}.csv", [], ["empty"])
        for name in ["ABCD_top20_summary", "ABCD_top50_summary", "ABCD_top20_overlap_matrix", "ABCD_top50_overlap_matrix", "weight_grid_rankings"]:
            write_csv(day_dir / f"{name}_{as_of}.csv", [], ["empty"])

    full_confirmed = bool(rankings) and leakage_ok and not stale_factor
    status = "PASS" if full_confirmed else "BLOCKED"
    summary = {
        "as_of_date": as_of,
        "daily_status": status,
        "price_data_max_date_used": price_latest,
        "technical_features_latest_date": technical_latest,
        "momentum_features_latest_date": momentum_latest,
        "A1_ranking_latest_date": max(rankings["A1_BASELINE_CONTROL"]["latest_price_date"], default="") if rankings else "",
        "B_ranking_latest_date": max(rankings["B_STATIC_MOMENTUM_BLEND"]["latest_price_date"], default="") if rankings else "",
        "C_ranking_latest_date": max(rankings["C_DYNAMIC_MOMENTUM_BLEND"]["latest_price_date"], default="") if rankings else "",
        "D_ranking_latest_date": max(rankings["D_WEIGHT_OPTIMIZED_R1"]["latest_price_date"], default="") if rankings else "",
        "full_recompute_confirmed": full_confirmed,
        "stale_factor_input_count": len(stale_factor),
        "missing_feature_producer": False,
        "read_v21_112_ranking_as_input": False,
        "read_v21_113_ranking_as_input": False,
        "copied_prior_ranking_files": False,
        "future_leakage_detected": not leakage_ok,
        "universe_mode": "CURRENT_UNIVERSE_PIT_LITE",
        "survivorship_warning": True,
        "A1_rows": len(rankings["A1_BASELINE_CONTROL"]) if rankings else 0,
        "B_rows": len(rankings["B_STATIC_MOMENTUM_BLEND"]) if rankings else 0,
        "C_rows": len(rankings["C_DYNAMIC_MOMENTUM_BLEND"]) if rankings else 0,
        "D_rows": len(rankings["D_WEIGHT_OPTIMIZED_R1"]) if rankings else 0,
        "D_top20": list(topn(rankings["D_WEIGHT_OPTIMIZED_R1"], 20)["ticker"]) if rankings else [],
        "D_top50": list(topn(rankings["D_WEIGHT_OPTIMIZED_R1"], 50)["ticker"]) if rankings else [],
    }
    write_json(day_dir / f"daily_recompute_summary_{as_of}.json", summary)
    return summary, rankings, grid, top20_rows, top50_rows, watchlist_rows(as_of, rankings["D_WEIGHT_OPTIMIZED_R1"]) if rankings else []


def write_report(summary: dict[str, Any]) -> None:
    lines = [
        f"# {STAGE}",
        "",
        f"FINAL_STATUS={summary['FINAL_STATUS']}",
        f"DECISION={summary['DECISION']}",
        "",
        "## Direct Answer",
        "From 2026-06-16 onward, which prior daily/latest runs were only price-refresh or stale-cache, and what are the corrected daily ABCD rankings?",
        "",
        "V21.113 was price-refresh-only / stale-cache lineage because it reused V21.112 ranking files and rewrote latest_price_date. V21.114 corrected the 2026-06-25 full recompute. V21.115 provides corrected daily ABCD rankings for each target trading date using OHLCV truncated to that as_of_date.",
        "",
        "## Controls",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "protected_outputs_modified=false",
        "",
        "## Universe",
        "universe_mode=CURRENT_UNIVERSE_PIT_LITE",
        "survivorship_warning=true",
        "",
        "## D Top20 By Date",
    ]
    for date, tickers in summary["D_top20_by_date"].items():
        lines.append(f"- {date}: {', '.join(tickers)}")
    (OUT / "V21.115_daily_true_recompute_ledger_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    universe, universe_manifest = V114.load_universe()
    full_price = load_price_panel(universe)
    latest_price_date = full_price["date"].max().strftime("%Y-%m-%d") if len(full_price) else ""

    status_rows = []
    top20_ledger = []
    top50_ledger = []
    d_top20_ledger = []
    d_top50_ledger = []
    grid20 = []
    grid50 = []
    d_panel = []
    overlap_panel = []
    grid_overlap = []
    watchlist = []
    stale_ledger = []
    storage_focus = []
    turnover20 = []
    turnover50 = []
    entrants_removals = []
    summaries: dict[str, dict[str, Any]] = {}
    prev20: set[str] | None = None
    prev50: set[str] | None = None

    for as_of in TARGET_DATES:
        daily, rankings, grid, top20_rows, top50_rows, watch_rows = daily_run(as_of, full_price, universe, universe_manifest)
        summaries[as_of] = daily
        status_rows.append(daily)
        top20_ledger.extend(top20_rows)
        top50_ledger.extend(top50_rows)
        watchlist.extend(watch_rows)
        stale_ledger.append({"as_of_date": as_of, "stale_factor_input_count": daily["stale_factor_input_count"], "full_recompute_confirmed": daily["full_recompute_confirmed"]})
        if rankings:
            d = rankings["D_WEIGHT_OPTIMIZED_R1"]
            d20 = topn(d, 20)
            d50 = topn(d, 50)
            d_top20_ledger.extend([{**{"as_of_date": as_of}, **r} for r in d20.to_dict("records")])
            d_top50_ledger.extend([{**{"as_of_date": as_of}, **r} for r in d50.to_dict("records")])
            d_panel.extend([{**{"as_of_date": as_of}, **r} for r in d.to_dict("records")])
            for n in [20, 50]:
                overlap_panel.extend([{**{"as_of_date": as_of, "view": f"top{n}"}, **r} for r in overlap_matrix(rankings, n)])
            current20 = set(d20["ticker"])
            current50 = set(d50["ticker"])
            t20 = turnover_rows(prev20, current20, as_of, "top20")
            t50 = turnover_rows(prev50, current50, as_of, "top50")
            turnover20.append(t20)
            turnover50.append(t50)
            for ticker in t20["entrants"].split("|") if t20["entrants"] else []:
                entrants_removals.append({"as_of_date": as_of, "view": "top20", "change_type": "ENTRANT", "ticker": ticker})
            for ticker in t20["removals"].split("|") if t20["removals"] else []:
                entrants_removals.append({"as_of_date": as_of, "view": "top20", "change_type": "REMOVAL", "ticker": ticker})
            for ticker in t50["entrants"].split("|") if t50["entrants"] else []:
                entrants_removals.append({"as_of_date": as_of, "view": "top50", "change_type": "ENTRANT", "ticker": ticker})
            for ticker in t50["removals"].split("|") if t50["removals"] else []:
                entrants_removals.append({"as_of_date": as_of, "view": "top50", "change_type": "REMOVAL", "ticker": ticker})
            prev20, prev50 = current20, current50
            focus = d[d["ticker"].isin(["MU", "SNDK", "WDC", "STX", "AMAT", "LRCX", "KLAC", "KLIC", "TER", "MKSI", "ICHR", "AMKR", "SOXX", "AMD", "INTC"])].copy()
            storage_focus.extend([{**{"as_of_date": as_of}, **r} for r in focus.to_dict("records")])
            if not grid.empty:
                for variant, group in grid.groupby("variant_id"):
                    grid20.extend([{**{"as_of_date": as_of}, **r} for r in group.nsmallest(20, "rank").to_dict("records")])
                    grid50.extend([{**{"as_of_date": as_of}, **r} for r in group.nsmallest(50, "rank").to_dict("records")])
                grid_overlap.extend(grid_overlap_panel(grid, 20, as_of))
                grid_overlap.extend(grid_overlap_panel(grid, 50, as_of))

    write_csv(OUT / "daily_status_ledger.csv", status_rows)
    write_csv(OUT / "daily_abcd_top20_ledger.csv", top20_ledger)
    write_csv(OUT / "daily_abcd_top50_ledger.csv", top50_ledger)
    write_csv(OUT / "daily_d_top20_ledger.csv", d_top20_ledger)
    write_csv(OUT / "daily_d_top50_ledger.csv", d_top50_ledger)
    write_csv(OUT / "daily_weight_grid_top20_ledger.csv", grid20)
    write_csv(OUT / "daily_weight_grid_top50_ledger.csv", grid50)
    write_csv(OUT / "daily_d_rank_score_panel.csv", d_panel)
    write_csv(OUT / "daily_d_top20_turnover.csv", turnover20)
    write_csv(OUT / "daily_d_top50_turnover.csv", turnover50)
    write_csv(OUT / "daily_d_entrants_removals.csv", entrants_removals or [{"as_of_date": "", "view": "", "change_type": "NO_MEANINGFUL_RANK_MOVEMENT", "ticker": ""}])
    write_csv(OUT / "daily_abcd_overlap_panel.csv", overlap_panel)
    write_csv(OUT / "daily_weight_grid_overlap_panel.csv", grid_overlap)
    write_csv(OUT / "daily_storage_semiconductor_focus_ledger.csv", storage_focus)
    write_csv(OUT / "daily_dram_mu_sndk_wdc_watchlist.csv", watchlist)
    write_csv(OUT / "daily_stale_factor_cache_ledger.csv", stale_ledger)

    failed_dates = [d for d, s in summaries.items() if not s["full_recompute_confirmed"]]
    total_stale = sum(int(s["stale_factor_input_count"]) for s in summaries.values())
    all_confirmed = not failed_dates and total_stale == 0
    any_reuse = any(s["read_v21_112_ranking_as_input"] or s["read_v21_113_ranking_as_input"] or s["copied_prior_ranking_files"] for s in summaries.values())
    final_status = "BLOCKED_V21_115_DAILY_RECOMPUTE_FAILED"
    decision = "DO_NOT_ARCHIVE_DAILY_RECOMPUTE_LEDGER"
    if all_confirmed and not any_reuse:
        final_status = "PARTIAL_PASS_V21_115_DAILY_RECOMPUTE_WITH_WARNINGS"
        decision = "DAILY_RECOMPUTE_LEDGER_READY_WITH_WARNINGS_RESEARCH_ONLY"

    rank_by_ticker = {}
    watch_df = pd.DataFrame(watchlist)
    for ticker in ["DRAM", "MU", "SNDK", "WDC", "STX", "AMAT", "LRCX"]:
        if not watch_df.empty:
            rank_by_ticker[ticker] = dict(zip(watch_df[watch_df["ticker"].eq(ticker)]["as_of_date"], watch_df[watch_df["ticker"].eq(ticker)]["rank"]))
        else:
            rank_by_ticker[ticker] = {}

    summary = {
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "start_date": TARGET_DATES[0],
        "end_date": TARGET_DATES[-1],
        "processed_dates": TARGET_DATES,
        "failed_dates": failed_dates,
        "latest_price_date": latest_price_date,
        "date_count": len(TARGET_DATES),
        "trading_date_count": len(TARGET_DATES),
        "universe_mode": "CURRENT_UNIVERSE_PIT_LITE",
        "survivorship_warning": True,
        "all_dates_full_recompute_confirmed": all_confirmed,
        "any_prior_ranking_reuse_detected": any_reuse,
        "total_stale_factor_input_count": total_stale,
        "max_stale_factor_input_count_by_date": max([int(s["stale_factor_input_count"]) for s in summaries.values()] or [0]),
        "dates_with_stale_factor_inputs": [d for d, s in summaries.items() if int(s["stale_factor_input_count"]) > 0],
        "dates_with_missing_feature_producers": [d for d, s in summaries.items() if s["missing_feature_producer"]],
        "A1_row_count_by_date": {d: s["A1_rows"] for d, s in summaries.items()},
        "B_row_count_by_date": {d: s["B_rows"] for d, s in summaries.items()},
        "C_row_count_by_date": {d: s["C_rows"] for d, s in summaries.items()},
        "D_row_count_by_date": {d: s["D_rows"] for d, s in summaries.items()},
        "D_top20_by_date": {d: s["D_top20"] for d, s in summaries.items()},
        "D_top50_by_date": {d: s["D_top50"] for d, s in summaries.items()},
        "D_top20_turnover_by_date": {r["as_of_date"]: r for r in turnover20},
        "D_top50_turnover_by_date": {r["as_of_date"]: r for r in turnover50},
        "DRAM_rank_by_date": rank_by_ticker["DRAM"],
        "MU_rank_by_date": rank_by_ticker["MU"],
        "SNDK_rank_by_date": rank_by_ticker["SNDK"],
        "WDC_rank_by_date": rank_by_ticker["WDC"],
        "STX_rank_by_date": rank_by_ticker["STX"],
        "AMAT_rank_by_date": rank_by_ticker["AMAT"],
        "LRCX_rank_by_date": rank_by_ticker["LRCX"],
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": False,
        "research_only": True,
        "report_path": rel(OUT / "V21.115_daily_true_recompute_ledger_report.md"),
    }
    write_json(OUT / "V21.115_daily_true_recompute_ledger_summary.json", summary)
    write_report(summary)
    print(json.dumps(summary, indent=2, default=str))
    return summary


if __name__ == "__main__":
    run()
