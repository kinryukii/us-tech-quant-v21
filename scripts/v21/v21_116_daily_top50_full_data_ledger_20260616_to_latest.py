#!/usr/bin/env python
"""V21.116 daily Top50 full data ledger from verified V21.115 recompute outputs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.116_DAILY_TOP50_FULL_DATA_LEDGER_20260616_TO_LATEST"
OUT = ROOT / "outputs/v21/V21.116_DAILY_TOP50_FULL_DATA_LEDGER_20260616_TO_LATEST"
SOURCE = ROOT / "outputs/v21/V21.115_DAILY_TRUE_RECOMPUTE_LEDGER_20260616_TO_20260625"
SOURCE_SUMMARY = SOURCE / "V21.115_daily_true_recompute_ledger_summary.json"
PRICE = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"

STRATEGIES = ["A1_BASELINE_CONTROL", "B_STATIC_MOMENTUM_BLEND", "C_DYNAMIC_MOMENTUM_BLEND", "D_WEIGHT_OPTIMIZED_R1"]
SHORT = {"A1_BASELINE_CONTROL": "A1", "B_STATIC_MOMENTUM_BLEND": "B", "C_DYNAMIC_MOMENTUM_BLEND": "C", "D_WEIGHT_OPTIMIZED_R1": "D"}
NON_TRADING_EXCLUDED = {"2026-06-19", "2026-06-20", "2026-06-21"}
WATCHLIST = ["DRAM", "MU", "SNDK", "WDC", "STX", "AMAT", "LRCX", "KLAC", "KLIC", "TER", "MKSI", "ICHR", "AMKR", "SOXX", "SMH", "AMD", "INTC"]
STORAGE = ["DRAM", "MU", "SNDK", "WDC", "STX"]
EQUIPMENT = ["AMAT", "LRCX", "KLAC", "KLIC", "TER", "MKSI", "ICHR", "AMKR", "COHU", "ENTG", "ASML"]
BASE_COLS = [
    "as_of_date", "strategy", "weight_variant", "rank", "ticker", "final_score", "base_score", "momentum_score",
    "absolute_momentum_score", "relative_momentum_score", "momentum_acceleration_score", "eligible_flag",
    "in_top20", "in_top50", "latest_price_date", "technical_features_latest_date",
    "momentum_features_latest_date", "universe_mode", "survivorship_warning",
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


def latest_completed_daily_price_date() -> str:
    if not PRICE.is_file():
        return ""
    latest = ""
    for chunk in pd.read_csv(PRICE, usecols=["date"], chunksize=500_000, low_memory=False):
        dates = pd.to_datetime(chunk["date"], errors="coerce")
        if dates.notna().any():
            latest = max(latest, dates.max().strftime("%Y-%m-%d"))
    return latest


def source_summary() -> dict[str, Any]:
    if not SOURCE_SUMMARY.is_file():
        raise FileNotFoundError(rel(SOURCE_SUMMARY))
    return json.loads(SOURCE_SUMMARY.read_text(encoding="utf-8"))


def daily_meta(as_of: str) -> dict[str, Any]:
    path = SOURCE / f"asof_{as_of}" / f"daily_recompute_summary_{as_of}.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_abcd(frame: pd.DataFrame, as_of: str, strategy: str, meta: dict[str, Any]) -> pd.DataFrame:
    out = frame.copy()
    out["as_of_date"] = as_of
    out["strategy"] = strategy
    out["weight_variant"] = ""
    out["rank"] = pd.to_numeric(out["rank"], errors="coerce")
    out["in_top20"] = out["rank"].le(20)
    out["in_top50"] = out["rank"].le(50)
    out["technical_features_latest_date"] = meta.get("technical_features_latest_date", "")
    out["momentum_features_latest_date"] = meta.get("momentum_features_latest_date", "")
    out["universe_mode"] = meta.get("universe_mode", "CURRENT_UNIVERSE_PIT_LITE")
    out["survivorship_warning"] = meta.get("survivorship_warning", True)
    for col in BASE_COLS:
        if col not in out:
            out[col] = ""
    extras = [c for c in out.columns if c not in BASE_COLS]
    return out[BASE_COLS + extras].sort_values(["rank", "ticker"]).reset_index(drop=True)


def normalize_grid(frame: pd.DataFrame, as_of: str, meta: dict[str, Any]) -> pd.DataFrame:
    out = frame.copy()
    out["as_of_date"] = as_of
    out["strategy"] = "WEIGHT_GRID"
    out["weight_variant"] = out["variant_id"]
    out["rank"] = pd.to_numeric(out["rank"], errors="coerce")
    out["in_top20"] = out["rank"].le(20)
    out["in_top50"] = out["rank"].le(50)
    out["technical_features_latest_date"] = meta.get("technical_features_latest_date", "")
    out["momentum_features_latest_date"] = meta.get("momentum_features_latest_date", "")
    out["universe_mode"] = meta.get("universe_mode", "CURRENT_UNIVERSE_PIT_LITE")
    out["survivorship_warning"] = meta.get("survivorship_warning", True)
    for col in ["absolute_momentum_score", "relative_momentum_score", "momentum_acceleration_score"]:
        if col not in out:
            out[col] = ""
    for col in BASE_COLS:
        if col not in out:
            out[col] = ""
    extras = [c for c in out.columns if c not in BASE_COLS]
    return out[BASE_COLS + extras].sort_values(["weight_variant", "rank", "ticker"]).reset_index(drop=True)


def top50(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[pd.to_numeric(frame["rank"], errors="coerce").le(50)].copy()


def write_report(summary: dict[str, Any]) -> None:
    lines = [
        f"# {STAGE}",
        "",
        f"FINAL_STATUS={summary['FINAL_STATUS']}",
        f"DECISION={summary['DECISION']}",
        "",
        "## Source Validation",
        f"- source_stage={summary['source_stage']}",
        f"- source_stage_full_recompute_confirmed={str(summary['source_stage_full_recompute_confirmed']).lower()}",
        f"- source_stage_stale_factor_input_count={summary['source_stage_stale_factor_input_count']}",
        f"- any_prior_ranking_reuse_detected={str(summary['any_prior_ranking_reuse_detected']).lower()}",
        "",
        "## Date Coverage",
        f"- processed_dates={', '.join(summary['processed_dates'])}",
        f"- failed_dates={', '.join(summary['failed_dates']) if summary['failed_dates'] else 'none'}",
        f"- skipped_dates={', '.join(summary['skipped_dates']) if summary['skipped_dates'] else 'none'}",
        f"- included_2026_06_26={str(summary['included_2026_06_26']).lower()}",
        "",
        "## D Top50 By Date",
    ]
    for as_of, tickers in summary["D_top50_by_date"].items():
        lines.append(f"- {as_of}: {', '.join(tickers)}")
    lines.extend([
        "",
        "Research-only export. No official ranking, official weights, broker actions, or protected outputs were modified.",
    ])
    (OUT / "V21.116_daily_top50_full_data_ledger_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def turnover(records: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    prev: dict[str, set[str]] = {}
    for (variant, as_of), group in records.sort_values(["weight_variant", "as_of_date", "rank"]).groupby(["weight_variant", "as_of_date"], sort=True):
        current = set(group["ticker"].astype(str))
        prior = prev.get(variant)
        entrants = sorted(current - prior) if prior is not None else []
        removals = sorted(prior - current) if prior is not None else []
        rows.append({
            "as_of_date": as_of,
            "variant": variant,
            "entrant_count": len(entrants),
            "removal_count": len(removals),
            "overlap_count": len(current & prior) if prior is not None else len(current),
            "entrants": "|".join(entrants),
            "removals": "|".join(removals),
        })
        prev[variant] = current
    return rows


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    src = source_summary()
    source_ok = bool(src.get("all_dates_full_recompute_confirmed")) and int(src.get("total_stale_factor_input_count", 999)) == 0 and not bool(src.get("any_prior_ranking_reuse_detected"))
    source_dates = list(src.get("processed_dates", []))
    latest_price = latest_completed_daily_price_date()
    target_dates = [d for d in source_dates if d <= latest_price and d not in NON_TRADING_EXCLUDED]
    skipped_dates = sorted(set(source_dates) - set(target_dates))
    included_626 = "2026-06-26" in target_dates

    ledgers = {s: [] for s in STRATEGIES}
    abcd_all = []
    grid_all = []
    all_variants = []
    export_status = []
    failed_dates = []
    watch_rows = []
    storage_rows = []
    equipment_rows = []
    rank_panel = []
    score_panel = []
    presence_rows = []
    d_top50_by_date: dict[str, list[str]] = {}
    a1_top50_by_date: dict[str, list[str]] = {}
    b_top50_by_date: dict[str, list[str]] = {}
    c_top50_by_date: dict[str, list[str]] = {}
    storage_presence: dict[str, list[str]] = {}
    equipment_presence: dict[str, list[str]] = {}
    counts_by_strategy = {SHORT[s]: {} for s in STRATEGIES}
    grid_counts: dict[str, int] = {}
    rank_by_ticker = {t: {} for t in ["DRAM", "MU", "SNDK", "WDC", "STX", "AMAT", "LRCX", "KLAC", "KLIC", "TER", "MKSI"]}

    for as_of in target_dates:
        meta = daily_meta(as_of)
        day_out = OUT / f"asof_{as_of}"
        day_out.mkdir(parents=True, exist_ok=True)
        day_failed = False
        day_combined = []
        full_by_variant: list[pd.DataFrame] = []
        top_by_variant: list[pd.DataFrame] = []

        for strategy in STRATEGIES:
            src_path = SOURCE / f"asof_{as_of}" / f"{strategy}_ranking_{as_of}.csv"
            if not src_path.is_file():
                day_failed = True
                continue
            full = normalize_abcd(pd.read_csv(src_path, low_memory=False), as_of, strategy, meta)
            top = top50(full)
            if len(top) != 50:
                day_failed = True
            short = SHORT[strategy]
            ledgers[strategy].extend(top.to_dict("records"))
            abcd_all.extend(top.to_dict("records"))
            day_combined.extend(top.to_dict("records"))
            full_by_variant.append(full.assign(variant_key=strategy))
            top_by_variant.append(top.assign(variant_key=strategy))
            counts_by_strategy[short][as_of] = int(len(top))
            top.to_csv(day_out / f"{strategy}_top50_{as_of}.csv", index=False)
            tickers = list(top.sort_values("rank")["ticker"].astype(str))
            if strategy == "A1_BASELINE_CONTROL":
                a1_top50_by_date[as_of] = tickers
            elif strategy == "B_STATIC_MOMENTUM_BLEND":
                b_top50_by_date[as_of] = tickers
            elif strategy == "C_DYNAMIC_MOMENTUM_BLEND":
                c_top50_by_date[as_of] = tickers
            elif strategy == "D_WEIGHT_OPTIMIZED_R1":
                d_top50_by_date[as_of] = tickers
                storage_presence[as_of] = [t for t in STORAGE if t in set(tickers)]
                equipment_presence[as_of] = [t for t in EQUIPMENT if t in set(tickers)]

        grid_path = SOURCE / f"asof_{as_of}" / f"weight_grid_rankings_{as_of}.csv"
        if not grid_path.is_file():
            day_failed = True
            grid_top = pd.DataFrame()
            grid_full = pd.DataFrame()
        else:
            grid_full = normalize_grid(pd.read_csv(grid_path, low_memory=False), as_of, meta)
            grid_top = top50(grid_full)
            variant_counts = grid_top.groupby("weight_variant")["ticker"].count().to_dict()
            if len(variant_counts) != 11 or any(int(v) != 50 for v in variant_counts.values()):
                day_failed = True
            grid_counts[as_of] = int(len(grid_top))
            grid_all.extend(grid_top.to_dict("records"))
            day_combined.extend(grid_top.to_dict("records"))
            full_by_variant.append(grid_full.assign(variant_key=grid_full["weight_variant"]))
            top_by_variant.append(grid_top.assign(variant_key=grid_top["weight_variant"]))
            grid_top.to_csv(day_out / f"weight_grid_top50_{as_of}.csv", index=False)

        combined = pd.DataFrame(day_combined)
        if not combined.empty:
            combined.to_csv(day_out / f"combined_all_variants_top50_{as_of}.csv", index=False)
            all_variants.extend(combined.to_dict("records"))
            storage_rows.extend(combined[combined["ticker"].isin(STORAGE)].to_dict("records"))
            equipment_rows.extend(combined[combined["ticker"].isin(EQUIPMENT)].to_dict("records"))
        else:
            write_csv(day_out / f"combined_all_variants_top50_{as_of}.csv", [], BASE_COLS)

        full_concat = pd.concat(full_by_variant, ignore_index=True) if full_by_variant else pd.DataFrame()
        top_concat = pd.concat(top_by_variant, ignore_index=True) if top_by_variant else pd.DataFrame()
        if not full_concat.empty:
            for variant, group in full_concat.groupby("variant_key", sort=True):
                top20_set = set(group[pd.to_numeric(group["rank"], errors="coerce").le(20)]["ticker"].astype(str))
                top50_set = set(group[pd.to_numeric(group["rank"], errors="coerce").le(50)]["ticker"].astype(str))
                indexed = group.set_index("ticker", drop=False)
                for ticker in WATCHLIST:
                    if ticker in indexed.index:
                        row = indexed.loc[ticker]
                        watch_rows.append({
                            "as_of_date": as_of,
                            "variant": variant,
                            "ticker": ticker,
                            "rank": row["rank"],
                            "final_score": row["final_score"],
                            "in_top20": ticker in top20_set,
                            "in_top50": ticker in top50_set,
                        })
                    else:
                        watch_rows.append({"as_of_date": as_of, "variant": variant, "ticker": ticker, "rank": "", "final_score": "", "in_top20": False, "in_top50": False})
        if not top_concat.empty:
            for row in top_concat.to_dict("records"):
                variant = row.get("variant_key", row.get("strategy", ""))
                key = f"{row['as_of_date']}|{variant}"
                rank_panel.append({"as_of_date": row["as_of_date"], "variant": variant, "ticker": row["ticker"], "rank": row["rank"]})
                score_panel.append({"as_of_date": row["as_of_date"], "variant": variant, "ticker": row["ticker"], "final_score": row["final_score"]})
                presence_rows.append({"as_of_date": row["as_of_date"], "variant": variant, "ticker": row["ticker"], "present_in_top50": True})

        write_json(day_out / f"top50_metadata_{as_of}.json", {
            "as_of_date": as_of,
            "source_stage": "V21.115_DAILY_TRUE_RECOMPUTE_LEDGER_20260616_TO_20260625",
            "source_full_recompute_confirmed": meta.get("full_recompute_confirmed", False),
            "technical_features_latest_date": meta.get("technical_features_latest_date", ""),
            "momentum_features_latest_date": meta.get("momentum_features_latest_date", ""),
            "universe_mode": meta.get("universe_mode", src.get("universe_mode", "")),
            "survivorship_warning": meta.get("survivorship_warning", src.get("survivorship_warning", True)),
            "day_failed": day_failed,
        })
        export_status.append({"as_of_date": as_of, "export_status": "FAIL" if day_failed else "PASS", "A1_top50_rows": counts_by_strategy["A1"].get(as_of, 0), "B_top50_rows": counts_by_strategy["B"].get(as_of, 0), "C_top50_rows": counts_by_strategy["C"].get(as_of, 0), "D_top50_rows": counts_by_strategy["D"].get(as_of, 0), "weight_grid_top50_rows": grid_counts.get(as_of, 0)})
        if day_failed:
            failed_dates.append(as_of)

    for strategy, rows in ledgers.items():
        write_csv(OUT / f"daily_{SHORT[strategy]}_top50_full_ledger.csv", rows)
    write_csv(OUT / "daily_ABCD_top50_full_ledger.csv", abcd_all)
    write_csv(OUT / "daily_weight_grid_top50_full_ledger.csv", grid_all)
    write_csv(OUT / "daily_all_variants_top50_full_ledger.csv", all_variants)
    write_csv(OUT / "daily_top50_ticker_presence_matrix.csv", presence_rows)
    write_csv(OUT / "daily_top50_rank_panel.csv", rank_panel)
    write_csv(OUT / "daily_top50_score_panel.csv", score_panel)
    write_csv(OUT / "daily_top50_turnover_all_variants.csv", turnover(pd.DataFrame(all_variants).assign(weight_variant=lambda x: x["weight_variant"].where(x["weight_variant"].astype(str).ne(""), x["strategy"])) if all_variants else pd.DataFrame(columns=["weight_variant", "as_of_date", "ticker"])))
    d_turn = turnover(pd.DataFrame(ledgers["D_WEIGHT_OPTIMIZED_R1"]).assign(weight_variant="D_WEIGHT_OPTIMIZED_R1") if ledgers["D_WEIGHT_OPTIMIZED_R1"] else pd.DataFrame(columns=["weight_variant", "as_of_date", "ticker"]))
    write_csv(OUT / "daily_D_top50_turnover_rechecked.csv", d_turn)
    write_csv(OUT / "daily_storage_chain_top50_ledger.csv", storage_rows)
    write_csv(OUT / "daily_semiconductor_equipment_top50_ledger.csv", equipment_rows)
    write_csv(OUT / "daily_watchlist_top50_ledger.csv", watch_rows)
    write_csv(OUT / "daily_top50_export_status_ledger.csv", export_status)

    watch_df = pd.DataFrame(watch_rows)
    for ticker in rank_by_ticker:
        subset = watch_df[(watch_df["ticker"].eq(ticker)) & (watch_df["variant"].eq("D_WEIGHT_OPTIMIZED_R1"))] if not watch_df.empty else pd.DataFrame()
        rank_by_ticker[ticker] = dict(zip(subset["as_of_date"], subset["rank"])) if not subset.empty else {}

    required_root = [
        "daily_A1_top50_full_ledger.csv", "daily_B_top50_full_ledger.csv", "daily_C_top50_full_ledger.csv",
        "daily_D_top50_full_ledger.csv", "daily_ABCD_top50_full_ledger.csv", "daily_weight_grid_top50_full_ledger.csv",
        "daily_all_variants_top50_full_ledger.csv", "daily_top50_ticker_presence_matrix.csv", "daily_top50_rank_panel.csv",
        "daily_top50_score_panel.csv", "daily_top50_turnover_all_variants.csv", "daily_D_top50_turnover_rechecked.csv",
        "daily_storage_chain_top50_ledger.csv", "daily_semiconductor_equipment_top50_ledger.csv",
        "daily_watchlist_top50_ledger.csv", "daily_top50_export_status_ledger.csv",
    ]
    missing_root = [name for name in required_root if not (OUT / name).is_file()]
    complete = source_ok and not failed_dates and not missing_root
    if complete and bool(src.get("survivorship_warning")):
        final_status = "PARTIAL_PASS_V21_116_DAILY_TOP50_LEDGER_WITH_WARNINGS"
        decision = "DAILY_TOP50_FULL_DATA_LEDGER_READY_WITH_WARNINGS_RESEARCH_ONLY"
    elif complete:
        final_status = "PASS_V21_116_DAILY_TOP50_FULL_DATA_LEDGER_COMPLETE"
        decision = "DAILY_TOP50_FULL_DATA_LEDGER_READY_RESEARCH_ONLY"
    else:
        final_status = "BLOCKED_V21_116_DAILY_TOP50_LEDGER_FAILED"
        decision = "DO_NOT_ARCHIVE_AS_COMPLETE_DAILY_TOP50_LEDGER"

    summary = {
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "start_date": min(target_dates) if target_dates else "",
        "end_date": max(target_dates) if target_dates else "",
        "processed_dates": target_dates,
        "failed_dates": failed_dates,
        "skipped_dates": skipped_dates,
        "latest_completed_daily_price_date": latest_price,
        "included_2026_06_26": included_626,
        "universe_mode": src.get("universe_mode", "CURRENT_UNIVERSE_PIT_LITE"),
        "survivorship_warning": bool(src.get("survivorship_warning", True)),
        "source_stage": "V21.115_DAILY_TRUE_RECOMPUTE_LEDGER_20260616_TO_20260625",
        "source_stage_full_recompute_confirmed": bool(src.get("all_dates_full_recompute_confirmed")),
        "source_stage_stale_factor_input_count": int(src.get("total_stale_factor_input_count", 0)),
        "any_prior_ranking_reuse_detected": bool(src.get("any_prior_ranking_reuse_detected")),
        "A1_top50_rows_by_date": counts_by_strategy["A1"],
        "B_top50_rows_by_date": counts_by_strategy["B"],
        "C_top50_rows_by_date": counts_by_strategy["C"],
        "D_top50_rows_by_date": counts_by_strategy["D"],
        "weight_grid_top50_rows_by_date": grid_counts,
        "all_variants_top50_rows_total": len(all_variants),
        "D_top50_by_date": d_top50_by_date,
        "A1_top50_by_date": a1_top50_by_date,
        "B_top50_by_date": b_top50_by_date,
        "C_top50_by_date": c_top50_by_date,
        "storage_chain_top50_presence_by_date": storage_presence,
        "equipment_chain_top50_presence_by_date": equipment_presence,
        "DRAM_rank_by_date": rank_by_ticker["DRAM"],
        "MU_rank_by_date": rank_by_ticker["MU"],
        "SNDK_rank_by_date": rank_by_ticker["SNDK"],
        "WDC_rank_by_date": rank_by_ticker["WDC"],
        "STX_rank_by_date": rank_by_ticker["STX"],
        "AMAT_rank_by_date": rank_by_ticker["AMAT"],
        "LRCX_rank_by_date": rank_by_ticker["LRCX"],
        "KLAC_rank_by_date": rank_by_ticker["KLAC"],
        "KLIC_rank_by_date": rank_by_ticker["KLIC"],
        "TER_rank_by_date": rank_by_ticker["TER"],
        "MKSI_rank_by_date": rank_by_ticker["MKSI"],
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "report_path": rel(OUT / "V21.116_daily_top50_full_data_ledger_report.md"),
    }
    write_json(OUT / "V21.116_daily_top50_full_data_ledger_summary.json", summary)
    write_report(summary)
    print(json.dumps(summary, indent=2, default=str))
    return summary


if __name__ == "__main__":
    run()
