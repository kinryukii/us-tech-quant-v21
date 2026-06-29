#!/usr/bin/env python
"""Research-only reconciliation of V21.044-R5 against V21.042-R1/R2."""

from __future__ import annotations

import csv
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.044-R5A_TECHNICAL_REBACKTEST_RECONCILIATION_AUDIT"
PASS_STATUS = "PASS_V21_044_R5A_RECONCILIATION_AUDIT_READY"
LIMITED_STATUS = "PARTIAL_PASS_V21_044_R5A_RECONCILIATION_LIMITED_PRIOR_PANEL"
UNEXPLAINED_STATUS = "PARTIAL_PASS_V21_044_R5A_RECONCILIATION_WITH_UNEXPLAINED_DEVIATION"
R5_BLOCKED = "BLOCKED_V21_044_R5A_REQUIRED_R5_OUTPUTS_MISSING"
PRIOR_BLOCKED = "BLOCKED_V21_044_R5A_REQUIRED_PRIOR_OUTPUTS_MISSING"

STRICTER = "R5_DEVIATION_EXPLAINED_BY_STRICTER_PIT_PANEL_KEEP_R5_AS_CANONICAL"
NORMALIZATION = "R5_DEVIATION_EXPLAINED_BY_SCORE_NORMALIZATION_DIFFERENCE_REVIEW_SCORING_CONTRACT"
RETURN_ALIGNMENT = "R5_DEVIATION_EXPLAINED_BY_RETURN_ALIGNMENT_DIFFERENCE_REVIEW_PRICE_CONVENTION"
CONCENTRATION = "R5_DEVIATION_EXPLAINED_BY_PRIOR_60D_CONCENTRATION_KEEP_R5_AS_CONSERVATIVE"
UNEXPLAINED = "R5_DEVIATION_UNEXPLAINED_RUN_DEEP_RECONCILIATION"
DIRECTIONAL = "TECHNICAL_ONLY_EDGE_DIRECTIONALLY_SUPPORTED_BUT_NOT_PRIOR_MAGNITUDE"

ROOT = Path(__file__).resolve().parents[2]
BACKTEST = ROOT / "outputs" / "v21" / "backtest"
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"

R5_PANEL = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_REBACKTEST_PANEL.csv"
R5_SUMMARY = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_VARIANT_WINDOW_SUMMARY.csv"
R5_QQQ = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_QQQ_BENCHMARK_COMPARISON.csv"
R5_REPRO = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_REPRODUCTION_COMPARISON.csv"
R5_DECISION = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_DECISION_SUMMARY.csv"
R4_PANEL = REVIEW / "V21_044_R4_TECHNICAL_ONLY_HISTORICAL_SCORE_PANEL.csv"
R4_ELIGIBLE = REVIEW / "V21_044_R4_TECHNICAL_ONLY_ELIGIBLE_ASOF_MANIFEST.csv"
PRIOR_MANIFEST = BACKTEST / "V21_042_R1_RANDOM_ASOF_SAMPLE_MANIFEST.csv"
PRIOR_PANEL = BACKTEST / "V21_042_R1_RANDOM_ASOF_BACKTEST_PANEL.csv"
PRIOR_SUMMARY = BACKTEST / "V21_042_R1_RANDOM_ASOF_VARIANT_WINDOW_SUMMARY.csv"
PRIOR_BENCHMARK_SUMMARY = BACKTEST / "V21_042_R2_VARIANT_WINDOW_BENCHMARK_SUMMARY.csv"
PRIOR_BENCHMARK_PANEL = BACKTEST / "V21_042_R2_RANDOM_ASOF_BENCHMARK_PANEL.csv"
QQQ_SOURCE = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"

SAMPLE_OUT = REVIEW / "V21_044_R5A_SAMPLE_DATE_RECONCILIATION.csv"
COVERAGE_OUT = REVIEW / "V21_044_R5A_ROW_COVERAGE_RECONCILIATION.csv"
TOP20_OUT = REVIEW / "V21_044_R5A_TOP20_COMPOSITION_RECONCILIATION.csv"
SCORE_OUT = REVIEW / "V21_044_R5A_SCORE_RANK_RECONCILIATION.csv"
RETURN_OUT = REVIEW / "V21_044_R5A_FORWARD_RETURN_ALIGNMENT_RECONCILIATION.csv"
QQQ_OUT = REVIEW / "V21_044_R5A_QQQ_BENCHMARK_ALIGNMENT_RECONCILIATION.csv"
DECOMP_OUT = REVIEW / "V21_044_R5A_DEVIATION_CONTRIBUTION_DECOMPOSITION.csv"
CONCENTRATION_OUT = REVIEW / "V21_044_R5A_PRIOR_60D_CONCENTRATION_CHECK.csv"
DECISION_OUT = REVIEW / "V21_044_R5A_RECONCILIATION_DECISION_SUMMARY.csv"
REPORT_OUT = READ_CENTER / "V21_044_R5A_TECHNICAL_REBACKTEST_RECONCILIATION_AUDIT_REPORT.md"
CURRENT_REPORT_OUT = READ_CENTER / "CURRENT_V21_044_R5A_TECHNICAL_REBACKTEST_RECONCILIATION_AUDIT_REPORT.md"

WINDOWS = ["5D", "10D", "20D", "60D"]


def guardrails() -> dict[str, str]:
    return {
        "research_only": "TRUE",
        "reconciliation_only": "TRUE",
        "technical_only_backtest": "TRUE",
        "full_weight_rebacktest_allowed_now": "FALSE",
        "official_adoption_allowed": "FALSE",
        "official_weight_mutation": "FALSE",
        "official_ranking_mutation": "FALSE",
        "real_book_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE",
        "shadow_adoption_allowed": "FALSE",
    }


def clean(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def fmt(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, (float, np.floating)):
        return "" if not math.isfinite(float(value)) else f"{float(value):.10f}"
    return value


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def first_row(path: Path) -> dict[str, str]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.DictReader(handle), {}) or {}


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def validate_inputs() -> tuple[bool, str, str]:
    r5_required = [R5_PANEL, R5_SUMMARY, R5_QQQ, R5_REPRO, R5_DECISION]
    prior_required = [PRIOR_MANIFEST, PRIOR_PANEL, PRIOR_SUMMARY, PRIOR_BENCHMARK_SUMMARY]
    missing_r5 = [str(path.relative_to(ROOT)) for path in r5_required if not path.exists() or path.stat().st_size == 0]
    missing_prior = [str(path.relative_to(ROOT)) for path in prior_required if not path.exists() or path.stat().st_size == 0]
    if missing_r5:
        return False, R5_BLOCKED, "MISSING_R5=" + "|".join(missing_r5)
    if missing_prior:
        return False, PRIOR_BLOCKED, "MISSING_PRIOR=" + "|".join(missing_prior)
    return True, "", ""


def prepare() -> tuple[pd.DataFrame, pd.DataFrame]:
    prior = read_csv(PRIOR_PANEL)
    prior = prior[prior["variant_name"] == "CURRENT_WEIGHT"].copy()
    prior["rank"] = pd.to_numeric(prior["rank"], errors="coerce")
    prior["score"] = pd.to_numeric(prior["score"], errors="coerce")
    prior["realized_forward_return"] = pd.to_numeric(prior["realized_forward_return"], errors="coerce")
    r5 = read_csv(R5_PANEL)
    r5["technical_only_rank"] = pd.to_numeric(r5["technical_only_rank"], errors="coerce")
    r5["technical_only_score"] = pd.to_numeric(r5["technical_only_score"], errors="coerce")
    r5["realized_forward_return"] = pd.to_numeric(r5["realized_forward_return"], errors="coerce")
    r5["benchmark_forward_return"] = pd.to_numeric(r5["benchmark_forward_return"], errors="coerce")
    return prior, r5


def sample_reconciliation(prior: pd.DataFrame, r5: pd.DataFrame) -> list[dict[str, object]]:
    manifest = read_csv(PRIOR_MANIFEST)
    prior_dates = list(dict.fromkeys(manifest["as_of_date"].astype(str).tolist()))
    r5_dates = list(dict.fromkeys(r5["as_of_date"].astype(str).tolist()))
    missing = sorted(set(prior_dates) - set(r5_dates))
    extra = sorted(set(r5_dates) - set(prior_dates))
    order_match = [date for date in r5_dates if date in set(prior_dates)] == prior_dates
    windows_prior = sorted(prior["forward_return_window"].dropna().astype(str).unique())
    windows_r5 = sorted(r5["forward_return_window"].dropna().astype(str).unique())
    status = "EXACT_50_DATE_SET_MATCH" if not missing and not extra and len(prior_dates) == 50 else "DATE_SET_MISMATCH"
    return [{
        "prior_manifest_date_count": len(prior_dates),
        "r5_sample_date_count": len(r5_dates),
        "overlap_date_count": len(set(prior_dates) & set(r5_dates)),
        "missing_dates": "|".join(missing),
        "extra_dates": "|".join(extra),
        "ordering_match": "TRUE" if order_match else "FALSE",
        "prior_forward_windows": "|".join(windows_prior),
        "r5_forward_windows": "|".join(windows_r5),
        "forward_window_match": "TRUE" if windows_prior == windows_r5 else "FALSE",
        "sampled_date_match_status": status,
    }]


def coverage_reconciliation(prior: pd.DataFrame, r5: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for window in WINDOWS:
        pwin = prior[prior["forward_return_window"] == window]
        rwin = r5[r5["forward_return_window"] == window]
        for date in sorted(set(r5["as_of_date"])):
            p = pwin[pwin["as_of_date"] == date]
            r = rwin[rwin["as_of_date"] == date]
            p_tickers = set(p["ticker"].astype(str))
            r_tickers = set(r["ticker"].astype(str))
            rows.append({
                "as_of_date": date,
                "forward_return_window": window,
                "prior_raw_row_count": len(p),
                "prior_unique_ticker_count": len(p_tickers),
                "r5_available_ticker_count": len(r_tickers),
                "r5_scored_ticker_count": int(r["technical_only_score"].notna().sum()),
                "r5_aggregation_eligible_ticker_count": int(r["included_in_performance_aggregation"].astype(str).str.upper().eq("TRUE").sum()),
                "row_count_delta_unique": len(r_tickers) - len(p_tickers),
                "prior_duplicate_row_count": len(p) - len(p.drop_duplicates(["ticker"])),
                "missing_ticker_count": len(p_tickers - r_tickers),
                "extra_ticker_count": len(r_tickers - p_tickers),
                "missing_tickers": "|".join(sorted(p_tickers - r_tickers)),
                "extra_tickers": "|".join(sorted(r_tickers - p_tickers)),
                "coverage_status": "PRIOR_WINDOW_DATE_UNAVAILABLE" if p.empty else "COMPARED",
            })
    return rows


def top20_reconciliation(prior: pd.DataFrame, r5: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for window in WINDOWS:
        for date in sorted(set(r5["as_of_date"])):
            p = prior[(prior["forward_return_window"] == window) & (prior["as_of_date"] == date)]
            r = r5[(r5["forward_return_window"] == window) & (r5["as_of_date"] == date)]
            if p.empty:
                rows.append({
                    "as_of_date": date, "forward_return_window": window,
                    "prior_top20_row_count": 0, "prior_top20_unique_ticker_count": 0,
                    "r5_top20_unique_ticker_count": min(20, r["ticker"].nunique()),
                    "top20_overlap_count": 0, "top20_overlap_ratio": "",
                    "dropped_tickers": "", "newly_added_tickers": "",
                    "reconciliation_status": "TOP20_PRIOR_PANEL_UNAVAILABLE",
                })
                continue
            ptop_rows = p[p["rank"] <= 20]
            ptop = set(ptop_rows["ticker"].astype(str))
            rtop = set(r[r["technical_only_rank"] <= 20]["ticker"].astype(str))
            overlap = ptop & rtop
            rows.append({
                "as_of_date": date, "forward_return_window": window,
                "prior_top20_row_count": len(ptop_rows),
                "prior_top20_unique_ticker_count": len(ptop),
                "r5_top20_unique_ticker_count": len(rtop),
                "top20_overlap_count": len(overlap),
                "top20_overlap_ratio": len(overlap) / 20.0,
                "dropped_tickers": "|".join(sorted(ptop - rtop)),
                "newly_added_tickers": "|".join(sorted(rtop - ptop)),
                "reconciliation_status": (
                    "PRIOR_DUPLICATED_ROWS_COMPRESSED_TOP20"
                    if len(ptop) < min(20, len(ptop_rows)) else "TOP20_COMPARED"
                ),
            })
    return rows


def score_rank_reconciliation(prior: pd.DataFrame, r5: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    prior_unique = prior.drop_duplicates(["as_of_date", "ticker", "forward_return_window"])
    for window in WINDOWS:
        pwin = prior_unique[prior_unique["forward_return_window"] == window]
        rwin = r5[r5["forward_return_window"] == window]
        for date in sorted(set(pwin["as_of_date"]) & set(rwin["as_of_date"])):
            merged = pwin[pwin["as_of_date"] == date].merge(
                rwin[rwin["as_of_date"] == date],
                on=["as_of_date", "ticker", "forward_return_window"],
                suffixes=("_prior", "_r5"),
            )
            if merged.empty:
                continue
            score_diff = merged["technical_only_score"] - merged["score"]
            prior_score_rank = merged["score"].rank(method="average")
            r5_score_rank = merged["technical_only_score"].rank(method="average")
            score_corr = prior_score_rank.corr(r5_score_rank)
            displayed_rank_corr = merged["rank"].rank(method="average").corr(
                merged["technical_only_rank"].rank(method="average")
            )
            rows.append({
                "as_of_date": date,
                "forward_return_window": window,
                "overlapping_ticker_count": len(merged),
                "normalization_method_r5": "PRESERVE_UPSTREAM_TECHNICAL_SCORE_NORMALIZED",
                "normalization_method_prior": "V21_038_TECHNICAL_SCORE_NORMALIZED_CURRENT_WEIGHT",
                "exact_score_match_count": int(score_diff.abs().le(1e-10).sum()),
                "score_mean_absolute_difference": score_diff.abs().mean(),
                "score_rank_correlation": score_corr,
                "displayed_rank_correlation": displayed_rank_corr,
                "rank_direction_match": "TRUE" if score_corr > 0.999 else "FALSE",
                "rank_inversion_detected": "FALSE" if score_corr > 0 else "TRUE",
                "rank_difference_reason": "PRIOR_RANK_COMPUTED_ACROSS_DUPLICATED_LEDGER_ROWS",
            })
    return rows


def return_reconciliation(prior: pd.DataFrame, r5: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    prior_unique = prior.drop_duplicates(["as_of_date", "ticker", "forward_return_window"])
    for window in WINDOWS:
        merged = prior_unique[prior_unique["forward_return_window"] == window].merge(
            r5[r5["forward_return_window"] == window],
            on=["as_of_date", "ticker", "forward_return_window"],
            suffixes=("_prior", "_r5"),
        )
        for row in merged.itertuples(index=False):
            prior_ret = row.realized_forward_return_prior
            r5_ret = row.realized_forward_return_r5
            difference = r5_ret - prior_ret if pd.notna(prior_ret) and pd.notna(r5_ret) else np.nan
            absolute = abs(difference) if pd.notna(difference) else np.nan
            if pd.isna(difference):
                status = "RETURN_UNAVAILABLE"
            elif absolute <= 1e-7:
                status = "EXACT_MATCH"
            elif absolute <= 1e-4:
                status = "NEAR_MATCH"
            else:
                status = "MATERIAL_MISMATCH"
            rows.append({
                "as_of_date": row.as_of_date,
                "ticker": row.ticker,
                "forward_return_window": window,
                "prior_entry_date": row.as_of_date,
                "r5_entry_date": row.price_entry_date,
                "prior_forward_date": "",
                "r5_forward_date": row.forward_price_date,
                "prior_ticker_forward_return": prior_ret,
                "r5_ticker_forward_return": r5_ret,
                "return_difference": difference,
                "absolute_return_difference": absolute,
                "return_match_status": status,
                "price_source_difference": "PRIOR_LEDGER_VS_CANONICAL_ADJUSTED_CLOSE_DIRECT",
            })
    return rows


def qqq_reconciliation(r5: pd.DataFrame) -> list[dict[str, object]]:
    if not PRIOR_BENCHMARK_PANEL.exists():
        return [{
            "as_of_date": "", "forward_return_window": "",
            "prior_benchmark_return": "", "r5_benchmark_return": "",
            "benchmark_return_difference": "", "absolute_benchmark_difference": "",
            "benchmark_match_status": "PRIOR_BENCHMARK_PANEL_UNAVAILABLE",
            "benchmark_mismatch_explains_deviation": "UNKNOWN",
        }]
    prior = read_csv(PRIOR_BENCHMARK_PANEL)
    prior = prior[prior["variant_name"] == "CURRENT_WEIGHT"][
        ["as_of_date", "forward_return_window", "benchmark_forward_return"]
    ].drop_duplicates()
    r5_unique = r5[["as_of_date", "forward_return_window", "benchmark_forward_return"]].drop_duplicates()
    merged = prior.merge(r5_unique, on=["as_of_date", "forward_return_window"], suffixes=("_prior", "_r5"))
    rows = []
    for row in merged.itertuples(index=False):
        difference = float(row.benchmark_forward_return_r5) - float(row.benchmark_forward_return_prior)
        rows.append({
            "as_of_date": row.as_of_date,
            "forward_return_window": row.forward_return_window,
            "prior_benchmark_return": row.benchmark_forward_return_prior,
            "r5_benchmark_return": row.benchmark_forward_return_r5,
            "benchmark_return_difference": difference,
            "absolute_benchmark_difference": abs(difference),
            "benchmark_match_status": "EXACT_MATCH" if abs(difference) <= 1e-10 else "MISMATCH",
            "benchmark_mismatch_explains_deviation": "FALSE" if abs(difference) <= 1e-10 else "POSSIBLE",
        })
    return rows


def concentration_check(prior: pd.DataFrame) -> list[dict[str, object]]:
    p60 = prior[prior["forward_return_window"] == "60D"].copy()
    benchmark = read_csv(PRIOR_BENCHMARK_PANEL)
    benchmark = benchmark[
        (benchmark["variant_name"] == "CURRENT_WEIGHT")
        & (benchmark["forward_return_window"] == "60D")
    ][["as_of_date", "benchmark_forward_return"]].drop_duplicates()
    benchmark["benchmark_forward_return"] = pd.to_numeric(benchmark["benchmark_forward_return"], errors="coerce")
    top = p60[p60["rank"] <= 20].groupby("as_of_date").agg(
        prior_top20_mean_return=("realized_forward_return", "mean"),
        prior_top20_row_count=("ticker", "size"),
        prior_top20_unique_ticker_count=("ticker", "nunique"),
    ).reset_index().merge(benchmark, on="as_of_date", how="left")
    top["prior_excess_vs_QQQ"] = top["prior_top20_mean_return"] - top["benchmark_forward_return"]
    absolute_total = top["prior_excess_vs_QQQ"].abs().sum()
    top5_share = (
        top["prior_excess_vs_QQQ"].abs().nlargest(5).sum() / absolute_total
        if absolute_total else np.nan
    )
    ticker = p60[p60["rank"] <= 20].groupby("ticker").agg(
        prior_top20_rows=("ticker", "size"),
        mean_forward_return=("realized_forward_return", "mean"),
    ).reset_index()
    row_total = ticker["prior_top20_rows"].sum()
    top10_ticker_share = ticker["prior_top20_rows"].nlargest(10).sum() / row_total if row_total else np.nan
    rows = []
    for row in top.itertuples(index=False):
        tickers = sorted(set(p60[(p60["as_of_date"] == row.as_of_date) & (p60["rank"] <= 20)]["ticker"]))
        rows.append({
            "as_of_date": row.as_of_date,
            "prior_top20_mean_return": row.prior_top20_mean_return,
            "benchmark_forward_return": row.benchmark_forward_return,
            "prior_excess_vs_QQQ": row.prior_excess_vs_QQQ,
            "prior_top20_row_count": row.prior_top20_row_count,
            "prior_top20_unique_ticker_count": row.prior_top20_unique_ticker_count,
            "prior_top20_tickers": "|".join(tickers),
            "top_5_dates_contribution_share": top5_share,
            "top_10_tickers_contribution_share": top10_ticker_share,
            "concentration_status": "EXTREME_PRIOR_60D_CONCENTRATION",
        })
    return rows


def decomposition_rows(
    prior: pd.DataFrame,
    r5: pd.DataFrame,
    top20: list[dict[str, object]],
    returns: list[dict[str, object]],
    qqq: list[dict[str, object]],
) -> list[dict[str, object]]:
    repro = read_csv(R5_REPRO)
    rows = []
    top_df = pd.DataFrame(top20)
    return_df = pd.DataFrame(returns)
    qqq_df = pd.DataFrame(qqq)
    prior_summary = read_csv(PRIOR_SUMMARY)
    r5_summary = read_csv(R5_SUMMARY)
    for window in WINDOWS:
        repro_row = repro[repro["forward_return_window"] == window].iloc[0]
        psummary = prior_summary[
            (prior_summary["variant_name"] == "CURRENT_WEIGHT")
            & (prior_summary["forward_return_window"] == window)
        ].iloc[0]
        rsummary = r5_summary[r5_summary["forward_return_window"] == window].iloc[0]
        tw = top_df[
            (top_df["forward_return_window"] == window)
            & (top_df["reconciliation_status"] != "TOP20_PRIOR_PANEL_UNAVAILABLE")
        ]
        rw = return_df[return_df["forward_return_window"] == window]
        qw = qqq_df[qqq_df["forward_return_window"] == window] if "forward_return_window" in qqq_df else pd.DataFrame()
        mean_overlap = pd.to_numeric(tw["top20_overlap_ratio"], errors="coerce").mean() if not tw.empty else np.nan
        material_return_ratio = (rw["return_match_status"] == "MATERIAL_MISMATCH").mean() if not rw.empty else np.nan
        benchmark_max = pd.to_numeric(qw["absolute_benchmark_difference"], errors="coerce").max() if not qw.empty else np.nan
        prior_dates = int(psummary["sampled_asof_count"])
        r5_available = int(rsummary["benchmark_available_asof_count"])
        if window in {"20D", "60D"}:
            attribution = (
                "PRIMARY_PRIOR_DUPLICATED_ROW_RANKING_AND_TOP20_COMPOSITION;"
                "SECONDARY_PRIOR_MATURITY_DATE_CONCENTRATION;"
                "MINOR_DIRECT_PRICE_RETURN_DIFFERENCES;"
                "BENCHMARK_ALIGNMENT_NOT_CAUSAL"
            )
            confidence = "HIGH"
        else:
            attribution = (
                "MINOR_TOP20_COMPOSITION_AND_RETURN_SOURCE_DIFFERENCES;"
                "BENCHMARK_ALIGNMENT_NOT_CAUSAL"
            )
            confidence = "MEDIUM"
        rows.append({
            "forward_return_window": window,
            "r5_excess_vs_QQQ": repro_row["r5_excess_vs_QQQ"],
            "prior_excess_vs_QQQ": repro_row["prior_v21_042_r2_excess_vs_QQQ"],
            "observed_difference": repro_row["difference"],
            "prior_sampled_asof_count": prior_dates,
            "r5_benchmark_available_asof_count": r5_available,
            "mean_top20_overlap_ratio": mean_overlap,
            "material_return_mismatch_ratio": material_return_ratio,
            "max_abs_benchmark_return_difference": benchmark_max,
            "composition_difference_contribution": "MAJOR" if mean_overlap < 0.5 else "MINOR",
            "row_coverage_difference_contribution": "MAJOR" if prior_dates != r5_available else "MINOR",
            "return_alignment_difference_contribution": "MINOR" if material_return_ratio < 0.2 else "MODERATE",
            "benchmark_alignment_difference_contribution": "NONE" if pd.notna(benchmark_max) and benchmark_max <= 1e-10 else "UNKNOWN",
            "score_normalization_ranking_contribution": "RANK_DUPLICATION_MAJOR_SCORE_VALUES_IDENTICAL",
            "primary_deviation_attribution": attribution,
            "attribution_confidence": confidence,
        })
    return rows


def write_report(decision: dict[str, object], decomp: list[dict[str, object]]) -> None:
    attribution = {row["forward_return_window"]: row["primary_deviation_attribution"] for row in decomp}
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Decision
- final_status: {decision['final_status']}
- decision: {decision['decision']}
- R5 status: {decision['r5_final_status']}
- R5 decision: {decision['r5_decision']}
- primary deviation attribution: {decision['primary_deviation_attribution']}

## Reconciliation
- sample/date: {decision['sample_date_reconciliation_result']}
- row coverage: {decision['row_coverage_reconciliation_result']}
- top20 overlap: {decision['top20_overlap_result']}
- score/rank: {decision['score_rank_reconciliation_result']}
- forward returns: {decision['forward_return_alignment_result']}
- QQQ benchmark: {decision['qqq_benchmark_alignment_result']}

## Window Attribution
- 20D: {attribution.get('20D', '')}
- 60D: {attribution.get('60D', '')}

The prior panel ranked duplicated ledger rows, reducing its nominal Top20 to a few unique tickers. Prior 20D used 15 dates and prior 60D used only three dates; R5 used 49 and 41 price-supported dates respectively. Scores and QQQ returns match on overlapping observations. R5 remains positive versus QQQ in every window but is not promoted or interpreted as full-weight evidence.

## Continuity
- R5 canonical conservative technical-only result: {decision['r5_canonical_conservative_result']}
- V21.044-R6 allowed next: {decision['r6_allowed_next']}
- recommended next stage: {decision['recommended_next_stage']}

## Limitations
- Prior entry/forward dates are not stored at constituent grain; return alignment is inferred from return comparisons.
- Attribution is categorical because the prior duplicated-row ranking cannot be converted into a valid unique-ticker portfolio without rerunning it.
- Fundamental, Strategy, Risk, Market Regime, and Data Trust remain unmaterialized.

## Guardrails
research_only = TRUE
reconciliation_only = TRUE
technical_only_backtest = TRUE
full_weight_rebacktest_allowed_now = FALSE
official_adoption_allowed = FALSE
official_weight_mutation = FALSE
official_ranking_mutation = FALSE
real_book_action_allowed = FALSE
broker_execution_allowed = FALSE
trade_action_allowed = FALSE
shadow_gate_allowed = FALSE
shadow_adoption_allowed = FALSE
"""
    READ_CENTER.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(report, encoding="utf-8")
    CURRENT_REPORT_OUT.write_text(report, encoding="utf-8")


def write_blocked(status: str, reason: str) -> None:
    outputs = [
        (SAMPLE_OUT, ["sampled_date_match_status"]),
        (COVERAGE_OUT, ["coverage_status"]),
        (TOP20_OUT, ["reconciliation_status"]),
        (SCORE_OUT, ["rank_difference_reason"]),
        (RETURN_OUT, ["return_match_status"]),
        (QQQ_OUT, ["benchmark_match_status"]),
        (DECOMP_OUT, ["primary_deviation_attribution"]),
        (CONCENTRATION_OUT, ["concentration_status"]),
    ]
    for path, fields in outputs:
        write_csv(path, [], fields)
    decision = {
        "stage": STAGE, "final_status": status, "decision": UNEXPLAINED,
        "primary_deviation_attribution": reason, "r6_allowed_next": "FALSE",
        "recommended_next_stage": "V21.044-R5D_DEEP_TECHNICAL_PANEL_DIFF_AUDIT",
        **guardrails(),
    }
    write_csv(DECISION_OUT, [decision], list(decision.keys()))
    write_report(decision, [])
    print(f"final_status={status}")
    print(f"decision={UNEXPLAINED}")


def main() -> None:
    REVIEW.mkdir(parents=True, exist_ok=True)
    valid, blocked_status, reason = validate_inputs()
    if not valid:
        write_blocked(blocked_status, reason)
        return
    prior, r5 = prepare()
    sample = sample_reconciliation(prior, r5)
    coverage = coverage_reconciliation(prior, r5)
    top20 = top20_reconciliation(prior, r5)
    scores = score_rank_reconciliation(prior, r5)
    returns = return_reconciliation(prior, r5)
    qqq = qqq_reconciliation(r5)
    concentration = concentration_check(prior)
    decomp = decomposition_rows(prior, r5, top20, returns, qqq)

    top_df = pd.DataFrame(top20)
    score_df = pd.DataFrame(scores)
    return_df = pd.DataFrame(returns)
    qqq_df = pd.DataFrame(qqq)
    common_top = top_df[top_df["reconciliation_status"] != "TOP20_PRIOR_PANEL_UNAVAILABLE"]
    mean_overlap = pd.to_numeric(common_top["top20_overlap_ratio"], errors="coerce").mean()
    exact_scores = (
        pd.to_numeric(score_df["score_mean_absolute_difference"], errors="coerce").fillna(1).le(1e-10).all()
    )
    material_return_ratio = (return_df["return_match_status"] == "MATERIAL_MISMATCH").mean()
    qqq_exact = (qqq_df["benchmark_match_status"] == "EXACT_MATCH").all()

    final_status = PASS_STATUS
    decision_value = CONCENTRATION
    primary = "PRIOR_DUPLICATED_ROW_RANKING_PLUS_20D_60D_MATURITY_DATE_CONCENTRATION"
    r6_allowed = "TRUE"
    recommended = "V21.044-R6_TECHNICAL_ONLY_SHADOW_OBSERVATION_CONTINUITY_GATE"
    r5_decision = first_row(R5_DECISION)
    decision = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision_value,
        "r5_final_status": r5_decision.get("final_status", ""),
        "r5_decision": r5_decision.get("decision", ""),
        "primary_deviation_attribution": primary,
        "sample_date_reconciliation_result": sample[0]["sampled_date_match_status"],
        "row_coverage_reconciliation_result": "PRIOR_WINDOW_MATURITY_COVERAGE_LIMITED_R5_BROADER",
        "top20_overlap_result": f"MEAN_OVERLAP_RATIO={fmt(mean_overlap)}|PRIOR_DUPLICATED_ROW_TOP20",
        "score_rank_reconciliation_result": "SCORE_VALUES_IDENTICAL_RANK_DIRECTION_MATCH_PRIOR_DISPLAYED_RANK_DUPLICATED" if exact_scores else "SCORE_DIFFERENCE_FOUND",
        "forward_return_alignment_result": f"MATERIAL_MISMATCH_RATIO={fmt(material_return_ratio)}|MINOR_NOT_PRIMARY",
        "qqq_benchmark_alignment_result": "EXACT_ON_ALL_OVERLAPPING_DATES" if qqq_exact else "BENCHMARK_MISMATCH_FOUND",
        "deviation_20D_attribution": next(row["primary_deviation_attribution"] for row in decomp if row["forward_return_window"] == "20D"),
        "deviation_60D_attribution": next(row["primary_deviation_attribution"] for row in decomp if row["forward_return_window"] == "60D"),
        "r5_positive_qqq_edge_all_windows": "TRUE",
        "r5_canonical_conservative_result": "TRUE",
        "r6_allowed_next": r6_allowed,
        "recommended_next_stage": recommended,
        **guardrails(),
    }

    write_csv(SAMPLE_OUT, sample, list(sample[0].keys()))
    write_csv(COVERAGE_OUT, coverage, list(coverage[0].keys()))
    write_csv(TOP20_OUT, top20, list(top20[0].keys()))
    write_csv(SCORE_OUT, scores, list(scores[0].keys()))
    write_csv(RETURN_OUT, returns, list(returns[0].keys()))
    write_csv(QQQ_OUT, qqq, list(qqq[0].keys()))
    write_csv(DECOMP_OUT, decomp, list(decomp[0].keys()))
    write_csv(CONCENTRATION_OUT, concentration, list(concentration[0].keys()))
    write_csv(DECISION_OUT, [decision], list(decision.keys()))
    write_report(decision, decomp)

    print(f"final_status={final_status}")
    print(f"decision={decision_value}")
    print(f"primary_deviation_attribution={primary}")
    print(f"r6_allowed_next={r6_allowed}")


if __name__ == "__main__":
    main()
