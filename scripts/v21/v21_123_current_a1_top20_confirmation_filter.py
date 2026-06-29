#!/usr/bin/env python
"""V21.123 current A1 Top20 confirmation filter."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.123_CURRENT_A1_TOP20_CONFIRMATION_FILTER"
OUT = ROOT / "outputs/v21/V21.123_CURRENT_A1_TOP20_CONFIRMATION_FILTER"

V116 = ROOT / "outputs/v21/V21.116_DAILY_TOP50_FULL_DATA_LEDGER_20260616_TO_LATEST"
V118 = ROOT / "outputs/v21/V21.118_D_R2_REPEATED_LOSER_AWARE_DESIGN"
V117_R1 = ROOT / "outputs/v21/V21.117_R1_D_EARLY_EDGE_FAILURE_DECOMPOSITION"
V121 = ROOT / "outputs/v21/V21.121_CANDIDATE_REBASE_REVIEW_A1_B_C_D_R2C"

A1_FILE = V116 / "daily_A1_top50_full_ledger.csv"
B_FILE = V116 / "daily_B_top50_full_ledger.csv"
C_FILE = V116 / "daily_C_top50_full_ledger.csv"
D_FILE = V116 / "daily_D_top50_full_ledger.csv"
D_R2C_FILE = V118 / "d_r2_top20_top50_membership.csv"
LOSER_FILE = V117_R1 / "d_repeated_loser_attribution.csv"
V121_MANIFEST = V121 / "V21.121_manifest.json"

ETF_TICKERS = {"QQQ", "SOXX", "SMH", "SPY", "IWM", "DIA", "EWY", "KWEB", "XLK", "XLF", "XLI", "XLV", "XLY", "XLP", "XLE", "XLU", "XLC", "XLRE", "XLB"}
SEMICONDUCTOR_TICKERS = {"AMD", "INTC", "NVDA", "MU", "SNDK", "WDC", "STX", "AMAT", "LRCX", "KLAC", "KLIC", "TER", "MKSI", "ICHR", "AMKR", "ASML", "COHU", "ENTG", "ACLS", "ACMR", "ARM", "TSM", "SOXX", "SMH"}
RATE_SENSITIVE_TICKERS = {"PLD", "AMT", "CCI", "EQIX", "DLR", "O", "VICI", "SPG", "PSA", "WELL", "EXR", "AVB", "EQR", "MAA", "UDR", "ESS", "ARE", "WY", "JHX", "LEN", "DHI", "PHM", "NVR", "TOL", "KBH"}


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
    required = [A1_FILE, B_FILE, C_FILE, D_FILE, D_R2C_FILE, LOSER_FILE, V121_MANIFEST]
    return [rel(path) for path in required if not path.is_file()]


def load_variant(path: Path, date: str | None = None) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    df["as_of_date"] = df["as_of_date"].astype(str)
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["rank"] = pd.to_numeric(df["rank"], errors="coerce")
    df["final_score"] = pd.to_numeric(df["final_score"], errors="coerce")
    if date is not None:
        df = df[df["as_of_date"].eq(date)].copy()
    return df


def rank_lookup(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    return {
        str(row["ticker"]): {
            "rank": int(row["rank"]) if pd.notna(row["rank"]) else "",
            "final_score": float(row["final_score"]) if pd.notna(row["final_score"]) else "",
        }
        for row in df.to_dict("records")
    }


def bool_rank(rank: Any, threshold: int) -> bool:
    try:
        return int(rank) <= threshold
    except (TypeError, ValueError):
        return False


def blocked(missing: list[str]) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": "BLOCKED_V21_123_MISSING_A1_TOP20",
        "DECISION": "DO_NOT_USE_A1_CONFIRMATION_FILTER",
        "missing_inputs": missing,
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
    }
    write_json(OUT / "V21.123_manifest.json", manifest)
    (OUT / "V21.123_current_a1_top20_confirmation_filter_report.txt").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return manifest


def classify(row: dict[str, Any]) -> str:
    if row["repeated_loser_flag"] or row["concentration_warning"] or row["ETF_flag"] or row["REIT_or_rate_sensitive_flag"]:
        return "RISK_FLAGGED"
    if row["in_B_top20"] or row["in_C_top20"] or row["in_B_top30"] or row["in_C_top30"]:
        return "HIGH_PRIORITY_CONFIRMED"
    if row["in_B_top50"] or row["in_C_top50"] or row["in_D_R2C_top20"] or row["in_D_R2C_top50"]:
        return "MEDIUM_PRIORITY_WATCH"
    return "LOW_PRIORITY_A1_ONLY"


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    missing = missing_inputs()
    if missing:
        return blocked(missing)

    v121 = json.loads(V121_MANIFEST.read_text(encoding="utf-8"))
    a1_all = load_variant(A1_FILE)
    if a1_all.empty or not {"as_of_date", "rank", "ticker", "final_score"}.issubset(a1_all.columns):
        return blocked([rel(A1_FILE) + ": malformed_or_empty"])
    latest_date = str(a1_all["as_of_date"].max())
    a1 = a1_all[(a1_all["as_of_date"].eq(latest_date)) & (a1_all["rank"].le(20))].sort_values("rank").copy()
    if len(a1) != 20:
        return blocked([rel(A1_FILE) + f": expected_20_latest_rows_found_{len(a1)}"])

    b_lookup = rank_lookup(load_variant(B_FILE, latest_date))
    c_lookup = rank_lookup(load_variant(C_FILE, latest_date))
    d_lookup = rank_lookup(load_variant(D_FILE, latest_date))
    d_r2c = pd.read_csv(D_R2C_FILE, low_memory=False)
    d_r2c = d_r2c[d_r2c["candidate_variant"].eq("D_R2C_BC_CONFIRMATION_OVERLAY")].copy()
    d_r2c["as_of_date"] = d_r2c["as_of_date"].astype(str)
    d_r2c["ticker"] = d_r2c["ticker"].astype(str).str.upper().str.strip()
    d_r2c["rank"] = pd.to_numeric(d_r2c["rank"], errors="coerce")
    d_r2c["final_score"] = pd.to_numeric(d_r2c["final_score"], errors="coerce")
    r2c_lookup = rank_lookup(d_r2c[d_r2c["as_of_date"].eq(latest_date)])

    losers = pd.read_csv(LOSER_FILE, low_memory=False)
    losers["ticker"] = losers["ticker"].astype(str).str.upper().str.strip()
    loser_set = set(losers["ticker"])

    clusters = []
    for ticker in a1["ticker"]:
        if ticker in SEMICONDUCTOR_TICKERS:
            clusters.append("semiconductor_or_technology")
        if ticker in ETF_TICKERS:
            clusters.append("ETF")
        if ticker in RATE_SENSITIVE_TICKERS:
            clusters.append("rate_sensitive")
    cluster_counts = Counter(clusters)

    rows = []
    for item in a1.to_dict("records"):
        ticker = str(item["ticker"]).upper().strip()
        b = b_lookup.get(ticker, {})
        c = c_lookup.get(ticker, {})
        d = d_lookup.get(ticker, {})
        r2c = r2c_lookup.get(ticker, {})
        semiconductor_flag = ticker in SEMICONDUCTOR_TICKERS
        etf_flag = ticker in ETF_TICKERS
        rate_flag = ticker in RATE_SENSITIVE_TICKERS
        concentration_warning = bool(
            (semiconductor_flag and cluster_counts["semiconductor_or_technology"] >= 4)
            or (etf_flag and cluster_counts["ETF"] >= 2)
            or (rate_flag and cluster_counts["rate_sensitive"] >= 3)
        )
        row = {
            "ranking_date": latest_date,
            "ticker": ticker,
            "A1_rank": int(item["rank"]),
            "A1_score": float(item["final_score"]),
            "B_rank": b.get("rank", ""),
            "C_rank": c.get("rank", ""),
            "D_rank": d.get("rank", ""),
            "D_R2C_rank": r2c.get("rank", ""),
            "in_B_top20": bool_rank(b.get("rank"), 20),
            "in_B_top30": bool_rank(b.get("rank"), 30),
            "in_B_top50": bool_rank(b.get("rank"), 50),
            "in_C_top20": bool_rank(c.get("rank"), 20),
            "in_C_top30": bool_rank(c.get("rank"), 30),
            "in_C_top50": bool_rank(c.get("rank"), 50),
            "in_D_top20": bool_rank(d.get("rank"), 20),
            "in_D_top50": bool_rank(d.get("rank"), 50),
            "in_D_R2C_top20": bool_rank(r2c.get("rank"), 20),
            "in_D_R2C_top50": bool_rank(r2c.get("rank"), 50),
            "repeated_loser_flag": ticker in loser_set,
            "semiconductor_or_technology_flag": semiconductor_flag,
            "ETF_flag": etf_flag,
            "REIT_or_rate_sensitive_flag": rate_flag,
            "concentration_warning": concentration_warning,
            "sector_metadata_available": False,
            "metadata_warning": "ticker_sector_industry_metadata_not_found_rule_based_flags_used",
            "current_rule_variant": "A1_BASELINE_CONTROL",
            "D_R2C_used_as_frozen_tracking_evidence_only": True,
        }
        row["current_research_bucket"] = classify(row)
        rows.append(row)

    write_csv(OUT / "current_a1_top20_confirmation_filter.csv", rows)

    summary_counter = Counter(row["current_research_bucket"] for row in rows)
    top_confirmed = [r["ticker"] for r in rows if r["current_research_bucket"] == "HIGH_PRIORITY_CONFIRMED"]
    a1_only = [r["ticker"] for r in rows if r["current_research_bucket"] == "LOW_PRIORITY_A1_ONLY"]
    bc_confirmed = [r["ticker"] for r in rows if r["in_B_top20"] or r["in_B_top30"] or r["in_C_top20"] or r["in_C_top30"] or r["in_B_top50"] or r["in_C_top50"]]
    r2c_confirmed = [r["ticker"] for r in rows if r["in_D_R2C_top20"] or r["in_D_R2C_top50"]]
    repeated_flagged = [r["ticker"] for r in rows if r["repeated_loser_flag"]]
    special_handling = [r["ticker"] for r in rows if r["semiconductor_or_technology_flag"] or r["ETF_flag"] or r["REIT_or_rate_sensitive_flag"]]
    summary_rows = [{
        "latest_ranking_date_used": latest_date,
        "HIGH_PRIORITY_CONFIRMED_count": summary_counter["HIGH_PRIORITY_CONFIRMED"],
        "MEDIUM_PRIORITY_WATCH_count": summary_counter["MEDIUM_PRIORITY_WATCH"],
        "LOW_PRIORITY_A1_ONLY_count": summary_counter["LOW_PRIORITY_A1_ONLY"],
        "RISK_FLAGGED_count": summary_counter["RISK_FLAGGED"],
        "top_confirmed_tickers": "|".join(top_confirmed),
        "A1_only_tickers": "|".join(a1_only),
        "B_C_confirmed_tickers": "|".join(bc_confirmed),
        "D_R2C_confirmed_tickers": "|".join(r2c_confirmed),
        "repeated_loser_flagged_tickers": "|".join(repeated_flagged),
        "semiconductor_cluster_count": cluster_counts["semiconductor_or_technology"],
        "ETF_REIT_rate_sensitive_count": cluster_counts["ETF"] + cluster_counts["rate_sensitive"],
        "metadata_warning": "sector_industry_metadata_missing_rule_based_annotations_used",
    }]
    write_csv(OUT / "current_a1_top20_bucket_summary.csv", summary_rows)

    risk_fields = [
        "ranking_date", "ticker", "A1_rank", "repeated_loser_flag", "semiconductor_or_technology_flag",
        "ETF_flag", "REIT_or_rate_sensitive_flag", "concentration_warning", "current_research_bucket",
        "metadata_warning",
    ]
    write_csv(OUT / "current_a1_top20_risk_annotations.csv", [{k: r[k] for k in risk_fields} for r in rows], risk_fields)

    overlap_rows = []
    for name, pred in [
        ("B_top20", lambda r: r["in_B_top20"]),
        ("B_top30", lambda r: r["in_B_top30"]),
        ("B_top50", lambda r: r["in_B_top50"]),
        ("C_top20", lambda r: r["in_C_top20"]),
        ("C_top30", lambda r: r["in_C_top30"]),
        ("C_top50", lambda r: r["in_C_top50"]),
        ("D_R2C_top20", lambda r: r["in_D_R2C_top20"]),
        ("D_R2C_top50", lambda r: r["in_D_R2C_top50"]),
    ]:
        tickers = [r["ticker"] for r in rows if pred(r)]
        overlap_rows.append({"variant_overlap": name, "count": len(tickers), "tickers": "|".join(tickers)})
    write_csv(OUT / "current_a1_top20_cross_variant_overlap.csv", overlap_rows)

    optional_metadata_missing = True
    if len(a1_only) >= 15 or not bc_confirmed:
        final_status = "WARN_V21_123_NO_STRONG_CONFIRMATION"
        decision = "A1_TOP20_FILTER_READY_LOW_CONFIRMATION_RESEARCH_ONLY"
    elif optional_metadata_missing:
        final_status = "PARTIAL_PASS_V21_123_FILTER_READY_WITH_METADATA_WARN"
        decision = "A1_TOP20_CONFIRMATION_FILTER_READY_WITH_METADATA_WARN_RESEARCH_ONLY"
    else:
        final_status = "PASS_V21_123_A1_TOP20_CONFIRMATION_FILTER_READY"
        decision = "A1_TOP20_CONFIRMATION_FILTER_READY_RESEARCH_ONLY"

    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_ranking_date_used": latest_date,
        "source_A1_Top20_file": rel(A1_FILE),
        "current_rule_variant": "A1_BASELINE_CONTROL",
        "high_priority_confirmed_count": summary_counter["HIGH_PRIORITY_CONFIRMED"],
        "medium_priority_watch_count": summary_counter["MEDIUM_PRIORITY_WATCH"],
        "low_priority_a1_only_count": summary_counter["LOW_PRIORITY_A1_ONLY"],
        "risk_flagged_count": summary_counter["RISK_FLAGGED"],
        "top_confirmed_tickers": top_confirmed,
        "A1_only_tickers": a1_only,
        "B_C_confirmed_tickers": bc_confirmed,
        "D_R2C_confirmed_tickers": r2c_confirmed,
        "repeated_loser_flagged_tickers": repeated_flagged,
        "semiconductor_rate_ETF_special_handling_tickers": special_handling,
        "source_v21_121_status": v121.get("FINAL_STATUS", ""),
        "primary_control_from_v21_121": v121.get("primary_control", ""),
        "D_R2C_used_as_frozen_tracking_evidence_only": True,
        "optional_sector_industry_metadata_available": False,
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "no_parameter_optimization_performed": True,
        "new_variant_generated": False,
        "rankings_recomputed": False,
    }
    write_json(OUT / "V21.123_manifest.json", manifest)
    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"latest_ranking_date_used={latest_date}",
        f"source A1 Top20 file={rel(A1_FILE)}",
        "current_rule_variant=A1_BASELINE_CONTROL",
        f"high_priority_confirmed_count={manifest['high_priority_confirmed_count']}",
        f"medium_priority_watch_count={manifest['medium_priority_watch_count']}",
        f"low_priority_a1_only_count={manifest['low_priority_a1_only_count']}",
        f"risk_flagged_count={manifest['risk_flagged_count']}",
        f"top confirmed tickers={', '.join(top_confirmed)}",
        f"A1-only tickers={', '.join(a1_only)}",
        f"B/C-confirmed tickers={', '.join(bc_confirmed)}",
        f"D_R2C-confirmed tickers if any={', '.join(r2c_confirmed)}",
        f"repeated loser flagged tickers={', '.join(repeated_flagged)}",
        f"semiconductor/rate/ETF special handling tickers={', '.join(special_handling)}",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
    ]
    (OUT / "V21.123_current_a1_top20_confirmation_filter_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, default=str))
    return manifest


if __name__ == "__main__":
    run()
