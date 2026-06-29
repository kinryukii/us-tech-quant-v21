from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.126_B_CHALLENGER_REVIEW_VS_A1_C_D_R2C"
OUT = ROOT / "outputs/v21/V21.126_B_CHALLENGER_REVIEW_VS_A1_C_D_R2C"

V125 = ROOT / "outputs/v21/V21.125_ABCD_VS_QQQ_FORWARD_WINRATE_SUMMARY"
V121 = ROOT / "outputs/v21/V21.121_CANDIDATE_REBASE_REVIEW_A1_B_C_D_R2C"
V123 = ROOT / "outputs/v21/V21.123_CURRENT_A1_TOP20_CONFIRMATION_FILTER"
V119_R1 = ROOT / "outputs/v21/V21.119_R1_FORWARD_MATURITY_UPDATE_AFTER_REFRESH"
V119_R2 = ROOT / "outputs/v21/V21.119_R2_NEW_MATURITY_ATTRIBUTION_AND_BC_COMPARISON"
V117_R1 = ROOT / "outputs/v21/V21.117_R1_D_EARLY_EDGE_FAILURE_DECOMPOSITION"
V116 = ROOT / "outputs/v21/V21.116_DAILY_TOP50_FULL_DATA_LEDGER_20260616_TO_LATEST"
V118 = ROOT / "outputs/v21/V21.118_D_R2_REPEATED_LOSER_AWARE_DESIGN"

V125_MANIFEST = V125 / "V21.125_manifest.json"
V125_SUMMARY = V125 / "abcd_vs_qqq_winrate_summary_all_matured.csv"
V125_HORIZON = V125 / "abcd_vs_qqq_winrate_by_horizon.csv"
V125_DETAIL = V125 / "abcd_vs_qqq_forward_detail.csv"
V121_MANIFEST = V121 / "V21.121_manifest.json"
V123_MANIFEST = V123 / "V21.123_manifest.json"
V119_R2_MANIFEST = V119_R2 / "V21.119_R2_manifest.json"
LOSER_FILE = V117_R1 / "d_repeated_loser_attribution.csv"
B_FILE = V116 / "daily_B_top50_full_ledger.csv"
A1_FILE = V116 / "daily_A1_top50_full_ledger.csv"
C_FILE = V116 / "daily_C_top50_full_ledger.csv"
D_FILE = V116 / "daily_D_top50_full_ledger.csv"
D_R2C_FILE = V118 / "d_r2_top20_top50_membership.csv"
PRICE = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"

STRATEGIES = [
    "A1_BASELINE_CONTROL",
    "B_STATIC_MOMENTUM_BLEND",
    "C_DYNAMIC_MOMENTUM_BLEND",
    "D_WEIGHT_OPTIMIZED_R1",
    "D_R2C_BC_CONFIRMATION_OVERLAY",
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
    required = [
        V125_MANIFEST, V125_SUMMARY, V125_HORIZON, V125_DETAIL,
        V121_MANIFEST, V123_MANIFEST, V119_R2_MANIFEST, LOSER_FILE,
        B_FILE, A1_FILE, C_FILE, D_FILE, D_R2C_FILE, PRICE,
    ]
    return [rel(path) for path in required if not path.is_file()]


def load_prices() -> dict[tuple[str, str], float]:
    df = pd.read_csv(PRICE, usecols=["symbol", "date", "close", "adjusted_close"], low_memory=False)
    df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    close = pd.to_numeric(df["close"], errors="coerce")
    adj = pd.to_numeric(df["adjusted_close"], errors="coerce")
    df["px"] = adj.where(adj.notna(), close)
    df = df.dropna(subset=["symbol", "date", "px"]).drop_duplicates(["symbol", "date"], keep="last")
    return {(r["symbol"], r["date"]): float(r["px"]) for r in df.to_dict("records")}


def px_return(ticker: str, start: str, end: str, prices: dict[tuple[str, str], float]) -> float:
    sp = prices.get((ticker, start))
    ep = prices.get((ticker, end))
    if sp is None or ep is None or sp == 0:
        return math.nan
    return ep / sp - 1.0


def load_variant(path: Path, date: str | None = None) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    df["as_of_date"] = df["as_of_date"].astype(str)
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["rank"] = pd.to_numeric(df["rank"], errors="coerce")
    df["final_score"] = pd.to_numeric(df["final_score"], errors="coerce")
    if date:
        df = df[df["as_of_date"].eq(date)].copy()
    return df


def top_set(path: Path, date: str, n: int) -> set[str]:
    df = load_variant(path, date)
    return set(df[df["rank"].le(n)]["ticker"])


def summary_row(summary: pd.DataFrame, strategy: str, topn: int) -> dict[str, Any]:
    sub = summary[summary["strategy"].eq(strategy) & summary["topN"].eq(topn)]
    return sub.iloc[0].to_dict() if not sub.empty else {}


def blocked(missing: list[str]) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": "BLOCKED_V21_126_MISSING_REQUIRED_INPUTS",
        "DECISION": "DO_NOT_USE_B_CHALLENGER_REVIEW",
        "missing_inputs": missing,
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
    }
    write_json(OUT / "V21.126_manifest.json", manifest)
    (OUT / "V21.126_B_challenger_review_report.txt").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return manifest


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    missing = missing_inputs()
    if missing:
        return blocked(missing)

    v125 = json.loads(V125_MANIFEST.read_text(encoding="utf-8"))
    v121 = json.loads(V121_MANIFEST.read_text(encoding="utf-8"))
    v123 = json.loads(V123_MANIFEST.read_text(encoding="utf-8"))
    v119r2 = json.loads(V119_R2_MANIFEST.read_text(encoding="utf-8"))
    summary = pd.read_csv(V125_SUMMARY, low_memory=False)
    horizon = pd.read_csv(V125_HORIZON, low_memory=False)
    detail = pd.read_csv(V125_DETAIL, low_memory=False)
    for col in ["topN", "observations", "win_rate_vs_QQQ", "avg_excess_vs_QQQ", "median_excess_vs_QQQ", "worst_excess_vs_QQQ"]:
        if col in summary.columns:
            summary[col] = pd.to_numeric(summary[col], errors="coerce")
    prices = load_prices()

    b20 = summary_row(summary, "B_STATIC_MOMENTUM_BLEND", 20)
    b50 = summary_row(summary, "B_STATIC_MOMENTUM_BLEND", 50)
    a120 = summary_row(summary, "A1_BASELINE_CONTROL", 20)
    a150 = summary_row(summary, "A1_BASELINE_CONTROL", 50)

    leadership_rows = []
    for topn in [20, 50]:
        b = summary_row(summary, "B_STATIC_MOMENTUM_BLEND", topn)
        for strategy in STRATEGIES:
            row = summary_row(summary, strategy, topn)
            leadership_rows.append({
                "topN": topn,
                "strategy": strategy,
                "win_rate_vs_QQQ": row.get("win_rate_vs_QQQ", math.nan),
                "avg_excess_vs_QQQ": row.get("avg_excess_vs_QQQ", math.nan),
                "median_excess_vs_QQQ": row.get("median_excess_vs_QQQ", math.nan),
                "worst_excess_vs_QQQ": row.get("worst_excess_vs_QQQ", math.nan),
                "B_advantage_win_rate": float(b.get("win_rate_vs_QQQ", math.nan)) - float(row.get("win_rate_vs_QQQ", math.nan)) if row else math.nan,
                "B_advantage_avg_excess": float(b.get("avg_excess_vs_QQQ", math.nan)) - float(row.get("avg_excess_vs_QQQ", math.nan)) if row else math.nan,
            })
    write_csv(OUT / "b_leadership_confirmation.csv", leadership_rows)

    consistency_rows = []
    b_h = horizon[horizon["strategy"].eq("B_STATIC_MOMENTUM_BLEND")].copy()
    broad_count = 0
    mature_h_count = 0
    for _, b_row in b_h.iterrows():
        mature_h_count += 1
        topn = int(b_row["topN"])
        h = str(b_row["horizon"])
        comp = {"topN": topn, "horizon": h, "B_win_rate_vs_QQQ": b_row["win_rate_vs_QQQ"], "B_avg_excess_vs_QQQ": b_row["avg_excess_vs_QQQ"]}
        beats_all = True
        for strategy in ["A1_BASELINE_CONTROL", "C_DYNAMIC_MOMENTUM_BLEND", "D_WEIGHT_OPTIMIZED_R1", "D_R2C_BC_CONFIRMATION_OVERLAY"]:
            other = horizon[(horizon["strategy"].eq(strategy)) & (horizon["topN"].eq(topn)) & (horizon["horizon"].eq(h))]
            if other.empty:
                comp[f"B_minus_{strategy}_avg_excess"] = math.nan
                comp[f"B_minus_{strategy}_win_rate"] = math.nan
                beats_all = False
            else:
                comp[f"B_minus_{strategy}_avg_excess"] = float(b_row["avg_excess_vs_QQQ"]) - float(other.iloc[0]["avg_excess_vs_QQQ"])
                comp[f"B_minus_{strategy}_win_rate"] = float(b_row["win_rate_vs_QQQ"]) - float(other.iloc[0]["win_rate_vs_QQQ"])
                if comp[f"B_minus_{strategy}_avg_excess"] < 0:
                    beats_all = False
        comp["B_beats_all_avg_excess_this_horizon"] = beats_all
        if beats_all:
            broad_count += 1
        consistency_rows.append(comp)
    if mature_h_count < 2:
        horizon_assessment = "INSUFFICIENT_MATURITY"
    elif broad_count >= max(2, int(mature_h_count * 0.6)):
        horizon_assessment = "BROAD"
    elif broad_count == 0:
        horizon_assessment = "CONCENTRATED"
    else:
        horizon_assessment = "MIXED"
    write_csv(OUT / "b_consistency_by_horizon.csv", consistency_rows)

    stability_rows = [{
        "B_top20_win_rate_vs_QQQ": b20.get("win_rate_vs_QQQ", math.nan),
        "B_top50_win_rate_vs_QQQ": b50.get("win_rate_vs_QQQ", math.nan),
        "B_top20_avg_excess_vs_QQQ": b20.get("avg_excess_vs_QQQ", math.nan),
        "B_top50_avg_excess_vs_QQQ": b50.get("avg_excess_vs_QQQ", math.nan),
        "top20_top50_stable": bool(float(b20.get("win_rate_vs_QQQ", 0)) >= 0.5 and float(b50.get("win_rate_vs_QQQ", 0)) >= 0.5),
        "instability_warning": bool(float(b20.get("win_rate_vs_QQQ", 0)) >= 0.5 and float(b50.get("win_rate_vs_QQQ", 0)) < 0.5),
    }]
    write_csv(OUT / "b_top20_top50_stability.csv", stability_rows)

    b_detail = detail[detail["strategy"].eq("B_STATIC_MOMENTUM_BLEND")].copy()
    gains = b_detail[b_detail["excess_vs_QQQ_calc"] > 0]
    total_gain = float(gains["excess_vs_QQQ_calc"].sum()) if not gains.empty else 0.0
    date_share = float(gains.groupby("ranking_date")["excess_vs_QQQ_calc"].sum().max() / total_gain) if total_gain else math.nan
    horizon_share = float(gains.groupby("horizon")["excess_vs_QQQ_calc"].sum().max() / total_gain) if total_gain else math.nan

    latest_b_date = str(load_variant(B_FILE)["as_of_date"].max())
    b_ledger = load_variant(B_FILE)
    # Ticker concentration from actual B members over matured detail rows.
    ticker_gain = defaultdict(float)
    for obs in b_detail.to_dict("records"):
        if bool(obs.get("win_vs_QQQ")) is not True:
            continue
        members = b_ledger[(b_ledger["as_of_date"].eq(str(obs["ranking_date"]))) & (b_ledger["rank"].le(int(obs["topN"])))]["ticker"].tolist()
        for ticker in members:
            value = px_return(ticker, str(obs["ranking_date"]), str(obs["ranking_date"]) if pd.isna(obs.get("horizon")) else str(obs["ranking_date"]), prices)
            # If exact forward endpoint is not in V21.125 detail, use concentration by repeated membership as a conservative proxy.
            ticker_gain[ticker] += float(obs["excess_vs_QQQ_calc"]) / max(len(members), 1)
    total_ticker = sum(abs(v) for v in ticker_gain.values())
    ticker_share = max((abs(v) / total_ticker for v in ticker_gain.values()), default=math.nan) if total_ticker else math.nan
    top_ticker = max(ticker_gain.items(), key=lambda x: abs(x[1]), default=("", math.nan))[0]
    concentration_warning = bool((not pd.isna(date_share) and date_share > 0.6) or (not pd.isna(horizon_share) and horizon_share > 0.6) or (not pd.isna(ticker_share) and ticker_share > 0.5))
    overfit_warning = concentration_warning or horizon_assessment in {"CONCENTRATED", "INSUFFICIENT_MATURITY"}
    write_csv(OUT / "b_concentration_overfit_audit.csv", [{
        "max_date_gain_share": date_share,
        "max_horizon_gain_share": horizon_share,
        "max_ticker_gain_share": ticker_share,
        "top_gain_ticker_proxy": top_ticker,
        "sector_metadata_available": False,
        "metadata_warning": "sector_industry_metadata_not_available_for_b_concentration",
        "B_concentration_warning": concentration_warning,
        "B_overfit_warning": overfit_warning,
    }])

    losers = pd.read_csv(LOSER_FILE, low_memory=False)
    loser_set = set(losers["ticker"].astype(str).str.upper().str.strip())
    b_top50 = load_variant(B_FILE, latest_b_date)
    b_loser_overlap = sorted(set(b_top50[b_top50["rank"].le(50)]["ticker"]) & loser_set)
    risk_level = "LOW" if len(b_loser_overlap) <= 5 else "MEDIUM" if len(b_loser_overlap) <= 12 else "HIGH"
    write_csv(OUT / "b_repeated_loser_audit.csv", [{
        "latest_B_ranking_date_used": latest_b_date,
        "B_top50_repeated_loser_overlap_count": len(b_loser_overlap),
        "B_top50_repeated_loser_overlap_tickers": "|".join(b_loser_overlap),
        "B_avoids_original_D_repeated_loser_drag": len(b_loser_overlap) <= 5,
        "B_repeated_loser_risk_level": risk_level,
    }])

    b_vs_a1_top20 = bool(float(b20["win_rate_vs_QQQ"]) > float(a120["win_rate_vs_QQQ"]) and float(b20["avg_excess_vs_QQQ"]) > float(a120["avg_excess_vs_QQQ"]))
    b_vs_a1_top50 = bool(float(b50["win_rate_vs_QQQ"]) > float(a150["win_rate_vs_QQQ"]) and float(b50["avg_excess_vs_QQQ"]) > float(a150["avg_excess_vs_QQQ"]))
    if b_vs_a1_top20 and b_vs_a1_top50 and not overfit_warning and risk_level != "HIGH" and horizon_assessment == "BROAD":
        recommended_role = "B_PRIMARY_RESEARCH_CHALLENGER"
    elif float(b20["win_rate_vs_QQQ"]) < 0.5 or float(b50["win_rate_vs_QQQ"]) < 0.5 or risk_level == "HIGH":
        recommended_role = "B_NOT_SUPPORTED"
    else:
        recommended_role = "B_SECONDARY_RESEARCH_CANDIDATE_CONTINUE_TRACKING"
    write_csv(OUT / "b_vs_a1_role_review.csv", [{
        "B_vs_A1_Top20_advantage": b_vs_a1_top20,
        "B_vs_A1_Top50_advantage": b_vs_a1_top50,
        "horizon_consistency_assessment": horizon_assessment,
        "B_concentration_warning": concentration_warning,
        "B_overfit_warning": overfit_warning,
        "B_repeated_loser_risk_level": risk_level,
        "recommended_B_role": recommended_role,
        "A1_primary_control_remains": True,
        "official_adoption_allowed": False,
    }])

    a1_20, a1_50 = top_set(A1_FILE, latest_b_date, 20), top_set(A1_FILE, latest_b_date, 50)
    c_20, c_50 = top_set(C_FILE, latest_b_date, 20), top_set(C_FILE, latest_b_date, 50)
    r2c = pd.read_csv(D_R2C_FILE, low_memory=False)
    r2c = r2c[(r2c["candidate_variant"].eq("D_R2C_BC_CONFIRMATION_OVERLAY")) & (r2c["as_of_date"].astype(str).eq(latest_b_date))].copy()
    r2c["rank"] = pd.to_numeric(r2c["rank"], errors="coerce")
    r2c20, r2c50 = set(r2c[r2c["rank"].le(20)]["ticker"].astype(str).str.upper()), set(r2c[r2c["rank"].le(50)]["ticker"].astype(str).str.upper())
    current_rows = []
    for row in b_top50[b_top50["rank"].le(50)].sort_values("rank").to_dict("records"):
        ticker = str(row["ticker"])
        current_rows.append({
            "as_of_date": latest_b_date,
            "ticker": ticker,
            "B_rank": int(row["rank"]),
            "B_score": float(row["final_score"]),
            "in_B_top20": int(row["rank"]) <= 20,
            "in_B_top50": True,
            "in_A1_top20": ticker in a1_20,
            "in_A1_top50": ticker in a1_50,
            "in_C_top20": ticker in c_20,
            "in_C_top50": ticker in c_50,
            "in_D_R2C_top20": ticker in r2c20,
            "in_D_R2C_top50": ticker in r2c50,
            "repeated_loser_flag": ticker in loser_set,
            "not_trade_list": True,
        })
    write_csv(OUT / "current_b_top20_top50_with_cross_confirmation.csv", current_rows)

    if recommended_role == "B_PRIMARY_RESEARCH_CHALLENGER":
        final_status = "PASS_V21_126_B_PRIMARY_CHALLENGER_SUPPORTED"
        decision = "B_PRIMARY_RESEARCH_CHALLENGER_RESEARCH_ONLY"
    elif recommended_role == "B_NOT_SUPPORTED":
        final_status = "WARN_V21_126_B_NOT_SUPPORTED"
        decision = "B_NOT_SUPPORTED_RESEARCH_ONLY"
    elif concentration_warning:
        final_status = "WARN_V21_126_B_ADVANTAGE_CONCENTRATED"
        decision = "B_ADVANTAGE_CONCENTRATED_RESEARCH_ONLY"
    else:
        final_status = "PARTIAL_PASS_V21_126_B_CHALLENGER_MIXED_BUT_PROMISING"
        decision = "B_CHALLENGER_MIXED_BUT_PROMISING_RESEARCH_ONLY"

    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_used": v121.get("latest_price_date_used", ""),
        "latest_B_ranking_date_used": latest_b_date,
        "source_v21_125_status": v125.get("FINAL_STATUS", ""),
        "B_Top20_win_rate_vs_QQQ": float(b20["win_rate_vs_QQQ"]),
        "B_Top50_win_rate_vs_QQQ": float(b50["win_rate_vs_QQQ"]),
        "B_average_excess_vs_QQQ_Top20": float(b20["avg_excess_vs_QQQ"]),
        "B_average_excess_vs_QQQ_Top50": float(b50["avg_excess_vs_QQQ"]),
        "B_vs_A1_Top20_advantage": b_vs_a1_top20,
        "B_vs_A1_Top50_advantage": b_vs_a1_top50,
        "B_horizon_consistency_assessment": horizon_assessment,
        "B_concentration_warning": concentration_warning,
        "B_overfit_warning": overfit_warning,
        "B_repeated_loser_risk_level": risk_level,
        "recommended_B_role": recommended_role,
        "A1_primary_control_remains": True,
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "model_parameters_changed": False,
        "rankings_recomputed": False,
        "new_strategy_variants_created": False,
        "v21_125_read_as_frozen_evidence": True,
        "next_recommended_stage": "V21.127_B_CHALLENGER_FORWARD_MATURITY_MONITOR_OR_PRICE_REFRESH_GATE",
        "source_v21_123_status": v123.get("FINAL_STATUS", ""),
        "source_v21_119_r2_status": v119r2.get("FINAL_STATUS", ""),
    }
    write_json(OUT / "V21.126_manifest.json", manifest)
    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"latest_price_date_used={manifest['latest_price_date_used']}",
        f"latest_B_ranking_date_used={latest_b_date}",
        f"source V21.125 status={v125.get('FINAL_STATUS', '')}",
        f"B Top20 win rate vs QQQ={manifest['B_Top20_win_rate_vs_QQQ']}",
        f"B Top50 win rate vs QQQ={manifest['B_Top50_win_rate_vs_QQQ']}",
        f"B average excess vs QQQ Top20={manifest['B_average_excess_vs_QQQ_Top20']}",
        f"B average excess vs QQQ Top50={manifest['B_average_excess_vs_QQQ_Top50']}",
        f"B vs A1 Top20 advantage={b_vs_a1_top20}",
        f"B vs A1 Top50 advantage={b_vs_a1_top50}",
        f"B horizon consistency assessment={horizon_assessment}",
        f"B concentration warning={concentration_warning}",
        f"B overfit warning={overfit_warning}",
        f"B repeated loser risk level={risk_level}",
        f"recommended_B_role={recommended_role}",
        "A1 primary control remains=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
        f"next recommended stage={manifest['next_recommended_stage']}",
    ]
    (OUT / "V21.126_B_challenger_review_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, default=str))
    return manifest


if __name__ == "__main__":
    run()
