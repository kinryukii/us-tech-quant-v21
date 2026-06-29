from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.126_R1_B_REPEATED_LOSER_DEPENDENCY_DECOMPOSITION"
OUT = ROOT / "outputs/v21/V21.126_R1_B_REPEATED_LOSER_DEPENDENCY_DECOMPOSITION"

V126 = ROOT / "outputs/v21/V21.126_B_CHALLENGER_REVIEW_VS_A1_C_D_R2C"
V125 = ROOT / "outputs/v21/V21.125_ABCD_VS_QQQ_FORWARD_WINRATE_SUMMARY"
V117_R1 = ROOT / "outputs/v21/V21.117_R1_D_EARLY_EDGE_FAILURE_DECOMPOSITION"
V119_R1 = ROOT / "outputs/v21/V21.119_R1_FORWARD_MATURITY_UPDATE_AFTER_REFRESH"
V116 = ROOT / "outputs/v21/V21.116_DAILY_TOP50_FULL_DATA_LEDGER_20260616_TO_LATEST"
V118 = ROOT / "outputs/v21/V21.118_D_R2_REPEATED_LOSER_AWARE_DESIGN"

V126_MANIFEST = V126 / "V21.126_manifest.json"
V125_SUMMARY = V125 / "abcd_vs_qqq_winrate_summary_all_matured.csv"
LOSER_FILE = V117_R1 / "d_repeated_loser_attribution.csv"
FWD = V119_R1 / "forward_maturity_by_date_horizon_after_refresh.csv"
B_FILE = V116 / "daily_B_top50_full_ledger.csv"
A1_FILE = V116 / "daily_A1_top50_full_ledger.csv"
C_FILE = V116 / "daily_C_top50_full_ledger.csv"
D_R2C_FILE = V118 / "d_r2_top20_top50_membership.csv"
PRICE = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
BENCH = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"


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
    required = [V126_MANIFEST, V125_SUMMARY, LOSER_FILE, FWD, B_FILE, A1_FILE, C_FILE, D_R2C_FILE, PRICE]
    return [rel(path) for path in required if not path.is_file()]


def load_prices() -> dict[tuple[str, str], float]:
    frames = []
    for path in [PRICE, BENCH]:
        if not path.is_file():
            continue
        df = pd.read_csv(path, usecols=["symbol", "date", "close", "adjusted_close"], low_memory=False)
        df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        close = pd.to_numeric(df["close"], errors="coerce")
        adj = pd.to_numeric(df["adjusted_close"], errors="coerce")
        df["px"] = adj.where(adj.notna(), close)
        frames.append(df[["symbol", "date", "px"]])
    prices = pd.concat(frames, ignore_index=True).dropna(subset=["symbol", "date", "px"])
    prices = prices.drop_duplicates(["symbol", "date"], keep="last")
    return {(r["symbol"], r["date"]): float(r["px"]) for r in prices.to_dict("records")}


def px_return(ticker: str, start: str, end: str, prices: dict[tuple[str, str], float]) -> float:
    start_px = prices.get((ticker, start))
    end_px = prices.get((ticker, end))
    if start_px is None or end_px is None or start_px == 0:
        return math.nan
    return end_px / start_px - 1.0


def load_variant(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    df["as_of_date"] = df["as_of_date"].astype(str)
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["rank"] = pd.to_numeric(df["rank"], errors="coerce")
    return df


def members(df: pd.DataFrame, as_of: str, topn: int) -> list[str]:
    return list(df[(df["as_of_date"].eq(as_of)) & (df["rank"].le(topn))].sort_values("rank")["ticker"])


def mean_returns(tickers: list[str], start: str, end: str, prices: dict[tuple[str, str], float]) -> tuple[float, int, int, list[float]]:
    vals = []
    missing = 0
    for ticker in tickers:
        value = px_return(ticker, start, end, prices)
        if pd.isna(value):
            missing += 1
        else:
            vals.append(value)
    return (float(pd.Series(vals).mean()) if vals else math.nan, len(vals), missing, vals)


def summary_value(summary: pd.DataFrame, strategy: str, topn: int, field: str) -> float:
    sub = summary[summary["strategy"].eq(strategy) & summary["topN"].eq(topn)]
    return float(sub.iloc[0][field]) if not sub.empty else math.nan


def blocked(missing: list[str]) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": "BLOCKED_V21_126_R1_MISSING_REQUIRED_INPUTS",
        "DECISION": "BLOCKED_MISSING_REQUIRED_INPUTS",
        "missing_inputs": missing,
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
    }
    write_json(OUT / "V21.126_R1_manifest.json", manifest)
    (OUT / "V21.126_R1_B_repeated_loser_dependency_report.txt").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return manifest


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    missing = missing_inputs()
    if missing:
        return blocked(missing)

    v126 = json.loads(V126_MANIFEST.read_text(encoding="utf-8"))
    prices = load_prices()
    summary = pd.read_csv(V125_SUMMARY, low_memory=False)
    summary["topN"] = pd.to_numeric(summary["topN"], errors="coerce")
    losers = pd.read_csv(LOSER_FILE, low_memory=False)
    losers["ticker"] = losers["ticker"].astype(str).str.upper().str.strip()
    loser_set = set(losers["ticker"])
    b_df = load_variant(B_FILE)
    a1_df = load_variant(A1_FILE)
    c_df = load_variant(C_FILE)
    r2c = pd.read_csv(D_R2C_FILE, low_memory=False)
    r2c = r2c[r2c["candidate_variant"].eq("D_R2C_BC_CONFIRMATION_OVERLAY")].copy()
    r2c["as_of_date"] = r2c["as_of_date"].astype(str)
    r2c["ticker"] = r2c["ticker"].astype(str).str.upper().str.strip()
    r2c["rank"] = pd.to_numeric(r2c["rank"], errors="coerce")

    latest_b_date = str(b_df["as_of_date"].max())
    overlap_rows = []
    for topn in [20, 50]:
        b_members = set(members(b_df, latest_b_date, topn))
        a1_members = set(members(a1_df, latest_b_date, topn))
        c_members = set(members(c_df, latest_b_date, topn))
        r2c_members = set(r2c[(r2c["as_of_date"].eq(latest_b_date)) & (r2c["rank"].le(topn))]["ticker"])
        repeated = sorted(b_members & loser_set)
        shared = sorted((b_members & loser_set) & (a1_members | c_members | r2c_members))
        unique = sorted((b_members & loser_set) - (a1_members | c_members | r2c_members))
        overlap_rows.append({
            "as_of_date": latest_b_date,
            "topN": topn,
            "B_member_count": len(b_members),
            "repeated_loser_overlap_count": len(repeated),
            "repeated_loser_overlap_ratio": len(repeated) / max(len(b_members), 1),
            "repeated_loser_tickers": "|".join(repeated),
            "repeated_loser_tickers_unique_to_B": "|".join(unique),
            "repeated_loser_tickers_shared_with_A1_C_D_R2C": "|".join(shared),
        })
    write_csv(OUT / "b_repeated_loser_overlap.csv", overlap_rows)

    fwd = pd.read_csv(FWD, low_memory=False)
    fwd = fwd[
        fwd["strategy"].eq("B_STATIC_MOMENTUM_BLEND")
        & fwd["matured"].astype(str).str.upper().eq("TRUE")
        & fwd["top_n"].isin([20, 50])
    ].copy()
    all_panel = pd.read_csv(FWD, low_memory=False)
    all_panel = all_panel[all_panel["matured"].astype(str).str.upper().eq("TRUE")].copy()

    decomposition_rows = []
    clean_rows = []
    repeated_contribs = []
    clean_contribs = []
    clean_vs_qqq_wins = {20: [], 50: []}
    clean_vs_b_wins = {20: [], 50: []}
    clean_vs_a1_wins = {20: [], 50: []}
    clean_excesses = {20: [], 50: []}
    b_excesses = {20: [], 50: []}
    member_counts = {20: [], 50: []}

    for obs in fwd.to_dict("records"):
        as_of = str(obs["ranking_date"])
        end = str(obs["end_date"])
        topn = int(obs["top_n"])
        b_members = members(b_df, as_of, topn)
        repeated = [ticker for ticker in b_members if ticker in loser_set]
        clean = [ticker for ticker in b_members if ticker not in loser_set]
        a1_members = set(members(a1_df, as_of, topn))
        c_members = set(members(c_df, as_of, topn))
        common_a1 = [ticker for ticker in b_members if ticker in a1_members]
        b_only = [ticker for ticker in b_members if ticker not in a1_members]
        bc_confirmed = [ticker for ticker in b_members if ticker in c_members]

        repeated_mean, repeated_valid, repeated_missing, repeated_vals = mean_returns(repeated, as_of, end, prices)
        clean_mean, clean_valid, clean_missing, clean_vals = mean_returns(clean, as_of, end, prices)
        common_mean, _, _, _ = mean_returns(common_a1, as_of, end, prices)
        bonly_mean, _, _, _ = mean_returns(b_only, as_of, end, prices)
        bc_mean, _, _, _ = mean_returns(bc_confirmed, as_of, end, prices)
        repeated_contribution = sum(repeated_vals) / max(topn, 1)
        clean_contribution = sum(clean_vals) / max(topn, 1)
        repeated_contribs.append(repeated_contribution)
        clean_contribs.append(clean_contribution)
        qqq = float(obs["benchmark_QQQ_return"])
        soxx = float(obs["benchmark_SOXX_return"]) if "benchmark_SOXX_return" in obs and not pd.isna(obs["benchmark_SOXX_return"]) else math.nan
        b_return = float(obs["equal_weight_return"])
        a1_row = all_panel[
            all_panel["strategy"].eq("A1_BASELINE_CONTROL")
            & all_panel["ranking_date"].astype(str).eq(as_of)
            & all_panel["horizon"].astype(str).eq(str(obs["horizon"]))
            & all_panel["top_n"].eq(topn)
        ]
        a1_return = float(a1_row.iloc[0]["equal_weight_return"]) if not a1_row.empty else math.nan
        clean_excess = clean_mean - qqq if not pd.isna(clean_mean) else math.nan
        clean_soxx = clean_mean - soxx if not pd.isna(clean_mean) and not pd.isna(soxx) else math.nan
        clean_vs_qqq_wins[topn].append(clean_excess > 0 if not pd.isna(clean_excess) else False)
        clean_vs_b_wins[topn].append(clean_mean > b_return if not pd.isna(clean_mean) else False)
        clean_vs_a1_wins[topn].append(clean_mean > a1_return if not pd.isna(clean_mean) and not pd.isna(a1_return) else False)
        clean_excesses[topn].append(clean_excess)
        b_excesses[topn].append(float(obs["excess_vs_QQQ"]))
        member_counts[topn].append(len(clean))
        decomposition_rows.append({
            "ranking_date": as_of,
            "horizon": obs["horizon"],
            "topN": topn,
            "B_return": b_return,
            "QQQ_return": qqq,
            "B_excess_vs_QQQ": obs["excess_vs_QQQ"],
            "repeated_loser_count": len(repeated),
            "clean_count": len(clean),
            "repeated_loser_tickers": "|".join(repeated),
            "contribution_from_repeated_losers": repeated_contribution,
            "contribution_from_clean_tickers": clean_contribution,
            "contribution_from_common_tickers_with_A1": common_mean,
            "contribution_from_B_only_tickers": bonly_mean,
            "contribution_from_B_C_confirmed_tickers": bc_mean,
        })
        clean_rows.append({
            "diagnostic_subset": f"B_CLEAN_EX_REPEATED_LOSERS_TOP{topn}",
            "ranking_date": as_of,
            "horizon": obs["horizon"],
            "topN": topn,
            "member_count": len(clean),
            "valid_price_count": clean_valid,
            "missing_price_count": clean_missing,
            "equal_weight_forward_return": clean_mean,
            "QQQ_excess": clean_excess,
            "SOXX_excess": clean_soxx,
            "win_vs_QQQ": clean_excess > 0 if not pd.isna(clean_excess) else False,
            "win_vs_original_B": clean_mean > b_return if not pd.isna(clean_mean) else False,
            "win_vs_A1": clean_mean > a1_return if not pd.isna(clean_mean) and not pd.isna(a1_return) else False,
            "diagnostic_only": True,
            "official_variant": False,
        })
    write_csv(OUT / "b_repeated_loser_contribution_decomposition.csv", decomposition_rows)
    write_csv(OUT / "b_clean_subset_forward_diagnostic.csv", clean_rows)

    def rate(values: list[bool]) -> float:
        return float(sum(values) / len(values)) if values else math.nan

    clean20_win = rate(clean_vs_qqq_wins[20])
    clean50_win = rate(clean_vs_qqq_wins[50])
    b20_win = summary_value(summary, "B_STATIC_MOMENTUM_BLEND", 20, "win_rate_vs_QQQ")
    b50_win = summary_value(summary, "B_STATIC_MOMENTUM_BLEND", 50, "win_rate_vs_QQQ")
    avg_clean20_excess = float(pd.Series(clean_excesses[20]).dropna().mean()) if clean_excesses[20] else math.nan
    avg_clean50_excess = float(pd.Series(clean_excesses[50]).dropna().mean()) if clean_excesses[50] else math.nan
    avg_b20_excess = summary_value(summary, "B_STATIC_MOMENTUM_BLEND", 20, "avg_excess_vs_QQQ")
    avg_b50_excess = summary_value(summary, "B_STATIC_MOMENTUM_BLEND", 50, "avg_excess_vs_QQQ")
    repeated_avg = float(pd.Series(repeated_contribs).mean()) if repeated_contribs else 0.0
    clean_avg = float(pd.Series(clean_contribs).mean()) if clean_contribs else 0.0
    repeated_share = abs(repeated_avg) / max(abs(repeated_avg) + abs(clean_avg), 1e-12)
    dependency_score = max(overlap_rows[1]["repeated_loser_overlap_ratio"], repeated_share)
    clean_member_sufficient = min(member_counts[20] or [0]) >= 10 and min(member_counts[50] or [0]) >= 25
    retained = bool(
        clean20_win >= 0.65
        and clean50_win >= 0.65
        and avg_clean20_excess >= avg_b20_excess * 0.6
        and avg_clean50_excess >= avg_b50_excess * 0.6
    )

    if not clean_member_sufficient or len(clean_rows) < 10:
        classification = "B_EDGE_INCONCLUSIVE_INSUFFICIENT_MATURITY"
    elif retained and dependency_score < 0.35:
        classification = "B_EDGE_CLEAN_AND_BROAD"
    elif retained:
        classification = "B_EDGE_PARTIALLY_REPEATED_LOSER_DEPENDENT"
    else:
        classification = "B_EDGE_PRIMARILY_REPEATED_LOSER_DEPENDENT"

    concentration_warning = bool(dependency_score >= 0.5)
    overfit_warning = bool(classification in {"B_EDGE_PRIMARILY_REPEATED_LOSER_DEPENDENT", "B_EDGE_INCONCLUSIVE_INSUFFICIENT_MATURITY"} or concentration_warning)
    write_csv(OUT / "b_dependency_classification.csv", [{
        "dependency_classification": classification,
        "B_original_Top20_win_rate_vs_QQQ": b20_win,
        "B_original_Top50_win_rate_vs_QQQ": b50_win,
        "B_clean_Top20_win_rate_vs_QQQ": clean20_win,
        "B_clean_Top50_win_rate_vs_QQQ": clean50_win,
        "B_clean_Top20_avg_excess_vs_QQQ": avg_clean20_excess,
        "B_clean_Top50_avg_excess_vs_QQQ": avg_clean50_excess,
    }])
    write_csv(OUT / "b_risk_review.csv", [{
        "repeated_loser_dependency_score": dependency_score,
        "repeated_loser_contribution_share": repeated_share,
        "clean_subset_performance_retained": retained,
        "clean_subset_member_count_sufficient": clean_member_sufficient,
        "concentration_warning": concentration_warning,
        "overfit_warning": overfit_warning,
        "sector_metadata_available": False,
        "metadata_warning": "sector_industry_metadata_unavailable_no_sector_conclusion_fabricated",
    }])

    if classification == "B_EDGE_CLEAN_AND_BROAD":
        final_status = "PASS_V21_126_R1_B_CLEAN_EDGE_SUPPORTED_DIAGNOSTIC_ONLY"
        decision = "ALLOW_B_CLEAN_SUBSET_FUTURE_TRACKING_DIAGNOSTIC_ONLY"
        recommended_role = "ALLOW_B_CLEAN_SUBSET_FUTURE_TRACKING_DIAGNOSTIC_ONLY"
    elif classification == "B_EDGE_PARTIALLY_REPEATED_LOSER_DEPENDENT":
        final_status = "PARTIAL_PASS_V21_126_R1_B_EDGE_PARTIALLY_DEPENDENT"
        decision = "KEEP_B_SECONDARY_TRACKING_ONLY"
        recommended_role = "KEEP_B_SECONDARY_TRACKING_ONLY"
    elif classification == "B_EDGE_INCONCLUSIVE_INSUFFICIENT_MATURITY":
        final_status = "WARN_V21_126_R1_B_INCONCLUSIVE"
        decision = "KEEP_B_NOT_SUPPORTED"
        recommended_role = "KEEP_B_NOT_SUPPORTED"
    else:
        final_status = "WARN_V21_126_R1_B_EDGE_REPEATED_LOSER_DEPENDENT"
        decision = "KEEP_B_NOT_SUPPORTED"
        recommended_role = "KEEP_B_NOT_SUPPORTED"

    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_used": v126.get("latest_price_date_used", ""),
        "latest_B_ranking_date_used": latest_b_date,
        "source_v21_126_status": v126.get("FINAL_STATUS", ""),
        "B_Top20_repeated_loser_overlap_count": overlap_rows[0]["repeated_loser_overlap_count"],
        "B_Top50_repeated_loser_overlap_count": overlap_rows[1]["repeated_loser_overlap_count"],
        "B_Top20_repeated_loser_overlap_ratio": overlap_rows[0]["repeated_loser_overlap_ratio"],
        "B_Top50_repeated_loser_overlap_ratio": overlap_rows[1]["repeated_loser_overlap_ratio"],
        "B_original_Top20_win_rate_vs_QQQ": b20_win,
        "B_clean_ex_repeated_losers_Top20_win_rate_vs_QQQ": clean20_win,
        "B_original_Top50_win_rate_vs_QQQ": b50_win,
        "B_clean_ex_repeated_losers_Top50_win_rate_vs_QQQ": clean50_win,
        "repeated_loser_dependency_score": dependency_score,
        "repeated_loser_contribution_share": repeated_share,
        "clean_subset_performance_retained": retained,
        "dependency_classification": classification,
        "recommended_B_role": recommended_role,
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "model_parameters_changed": False,
        "rankings_recomputed": False,
        "official_new_strategy_variants_created": False,
        "diagnostic_subsets_created": True,
        "next_recommended_stage": "V21.127_B_CLEAN_SUBSET_DIAGNOSTIC_TRACKING_OR_PRICE_REFRESH_GATE",
    }
    write_json(OUT / "V21.126_R1_manifest.json", manifest)
    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"latest_price_date_used={manifest['latest_price_date_used']}",
        f"latest_B_ranking_date_used={latest_b_date}",
        f"source V21.126 status={v126.get('FINAL_STATUS', '')}",
        f"B Top20 repeated-loser overlap count={manifest['B_Top20_repeated_loser_overlap_count']}",
        f"B Top50 repeated-loser overlap count={manifest['B_Top50_repeated_loser_overlap_count']}",
        f"B Top20 repeated-loser overlap ratio={manifest['B_Top20_repeated_loser_overlap_ratio']}",
        f"B Top50 repeated-loser overlap ratio={manifest['B_Top50_repeated_loser_overlap_ratio']}",
        f"B original Top20 win rate vs QQQ={b20_win}",
        f"B clean-ex-repeated-losers Top20 win rate vs QQQ={clean20_win}",
        f"B original Top50 win rate vs QQQ={b50_win}",
        f"B clean-ex-repeated-losers Top50 win rate vs QQQ={clean50_win}",
        f"repeated_loser_dependency_score={dependency_score}",
        f"repeated_loser_contribution_share={repeated_share}",
        f"clean_subset_performance_retained={retained}",
        f"dependency_classification={classification}",
        f"recommended_B_role={recommended_role}",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
        f"next recommended stage={manifest['next_recommended_stage']}",
    ]
    (OUT / "V21.126_R1_B_repeated_loser_dependency_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, default=str))
    return manifest


if __name__ == "__main__":
    run()
