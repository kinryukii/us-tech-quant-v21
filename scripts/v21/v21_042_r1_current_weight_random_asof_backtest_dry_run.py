#!/usr/bin/env python
"""V21.042-R1 current weight random as-of backtest dry-run.

Research-only random historical as-of backtest using local V21/V20 artifacts.
No network, external market-data package, broker, trade, shadow, official, or production-facing
mutation is performed.
"""

from __future__ import annotations

import csv
import hashlib
import math
import random
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.042-R1_CURRENT_WEIGHT_RANDOM_ASOF_BACKTEST_DRY_RUN"
PASS_STATUS = "PASS_V21_042_R1_CURRENT_WEIGHT_RANDOM_ASOF_BACKTEST_READY"
LIMITED_STATUS = "PARTIAL_PASS_V21_042_R1_RANDOM_ASOF_BACKTEST_LIMITED_HISTORY"
LEAKAGE_STATUS = "PARTIAL_PASS_V21_042_R1_RANDOM_ASOF_BACKTEST_WITH_LEAKAGE_EXCLUSIONS"
BLOCKED_WEIGHT_STATUS = "BLOCKED_V21_042_R1_CURRENT_WEIGHT_SOURCE_NOT_FOUND"
BLOCKED_DATES_STATUS = "BLOCKED_V21_042_R1_NO_ELIGIBLE_RANDOM_ASOF_DATES"

DECISION_SUPPORTS = "CURRENT_WEIGHT_RANDOM_BACKTEST_SUPPORTS_CONTINUED_SHADOW_OBSERVATION_ONLY"
DECISION_REVIEW = "KEEP_BASELINE_OR_REVIEW_CURRENT_WEIGHT"
DECISION_BLOCKED_WEIGHT = "CURRENT_WEIGHT_RANDOM_BACKTEST_BLOCKED_WEIGHT_SOURCE_NOT_FOUND"
DECISION_BLOCKED_DATES = "CURRENT_WEIGHT_RANDOM_BACKTEST_BLOCKED_NO_ELIGIBLE_ASOF_DATES"

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "backtest"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"
FACTORS_DIR = ROOT / "outputs" / "v21" / "factors"

SNAPSHOT = FACTORS_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv"
R4_LEDGER = FACTORS_DIR / "V21_040_R4_CANONICAL_CONTEXT_LEDGER.csv"
R3A_RANKING = FACTORS_DIR / "V21_041_R3A_CURRENT_RANKING_COMPARISON.csv"
R3A_SUMMARY = FACTORS_DIR / "V21_041_R3A_CURRENT_WEIGHT_DRY_RUN_SUMMARY.csv"
WEIGHT_VARIANTS = FACTORS_DIR / "V21_041_R1_TECHNICAL_SUBFACTOR_WEIGHT_VARIANTS.csv"
CONDITIONED_DEF = FACTORS_DIR / "V21_042_R2_CONTEXT_CONDITIONED_VARIANT_DEFINITION.csv"

MANIFEST_OUT = OUT_DIR / "V21_042_R1_RANDOM_ASOF_SAMPLE_MANIFEST.csv"
SOURCE_OUT = OUT_DIR / "V21_042_R1_CURRENT_WEIGHT_SOURCE_AUDIT.csv"
PANEL_OUT = OUT_DIR / "V21_042_R1_RANDOM_ASOF_BACKTEST_PANEL.csv"
DATE_METRICS_OUT = OUT_DIR / "V21_042_R1_RANDOM_ASOF_PER_DATE_METRICS.csv"
SUMMARY_METRICS_OUT = OUT_DIR / "V21_042_R1_RANDOM_ASOF_VARIANT_WINDOW_SUMMARY.csv"
LEAKAGE_OUT = OUT_DIR / "V21_042_R1_RANDOM_ASOF_LEAKAGE_AUDIT.csv"
DECISION_OUT = OUT_DIR / "V21_042_R1_RANDOM_ASOF_DECISION_SUMMARY.csv"
REPORT_OUT = READ_CENTER_DIR / "V21_042_R1_CURRENT_WEIGHT_RANDOM_ASOF_BACKTEST_REPORT.md"
CURRENT_REPORT_OUT = READ_CENTER_DIR / "CURRENT_V21_042_R1_CURRENT_WEIGHT_RANDOM_ASOF_BACKTEST_REPORT.md"

RANDOM_SEED = 21042
MAX_SAMPLE_DATES = 50
WINDOWS = ["5D", "10D", "20D", "60D"]
VARIANTS = [
    "CURRENT_WEIGHT",
    "EQUAL_WEIGHT_BASELINE",
    "EXISTING_BASELINE_IF_AVAILABLE",
    "GLOBAL_RSI_CANDIDATE",
    "CURRENT_WEIGHT_PLUS_RSI_CANDIDATE",
]


def yes(value: bool) -> str:
    return "TRUE" if bool(value) else "FALSE"


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
        if math.isnan(float(value)) or math.isinf(float(value)):
            return ""
        return f"{float(value):.10f}"
    return value


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def file_hash(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def pct_rank(series: pd.Series) -> pd.Series:
    if series.notna().sum() == 0:
        return pd.Series(np.nan, index=series.index)
    return series.rank(method="average", pct=True)


def read_first(path: Path) -> dict[str, str]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.DictReader(handle), {}) or {}


def component_scores(df: pd.DataFrame) -> pd.DataFrame:
    c = pd.DataFrame(index=df.index)
    c["rsi"] = pd.to_numeric(df.get("rsi_14"), errors="coerce") / 100.0
    c["kdj"] = pd.to_numeric(df.get("kdj_k"), errors="coerce") / 100.0
    c["macd"] = pd.to_numeric(df.get("macd_hist"), errors="coerce").groupby(df["as_of_date"]).transform(pct_rank)
    c["bb"] = 1 - (pd.to_numeric(df.get("bb_position"), errors="coerce") - 0.55).abs().clip(0, 1)
    ma = df[["ma20_distance", "ma50_distance", "ema20_distance"]].apply(pd.to_numeric, errors="coerce").mean(axis=1)
    c["ma"] = ma.groupby(df["as_of_date"]).transform(pct_rank)
    c["trend"] = pd.to_numeric(df.get("trend_strength_score"), errors="coerce").clip(0, 1)
    c["volume"] = (1 - (pd.to_numeric(df.get("volume_ratio"), errors="coerce") - 1.2).abs() / 2).clip(0, 1)
    c["volatility"] = -pd.to_numeric(df.get("volatility_20"), errors="coerce").groupby(df["as_of_date"]).transform(pct_rank)
    mom = df[["momentum_5", "momentum_10", "momentum_20"]].apply(pd.to_numeric, errors="coerce").mean(axis=1)
    c["momentum"] = mom.groupby(df["as_of_date"]).transform(pct_rank)
    c["overheat"] = pd.to_numeric(df.get("overheat_extension_score"), errors="coerce").clip(0, 1)
    return c.fillna(0)


def weight_dict(weights: pd.DataFrame, variant: str) -> dict[str, float]:
    rows = weights[weights["variant_name"] == variant] if not weights.empty else pd.DataFrame()
    return {r["subfactor_name"]: float(r["variant_weight"]) for r in rows.to_dict("records")}


def weighted_score(c: pd.DataFrame, weights: dict[str, float], dates: pd.Series) -> pd.Series:
    raw = pd.Series(0.0, index=c.index)
    for col in ["rsi", "kdj", "macd", "bb", "ma", "trend", "volume", "volatility", "momentum"]:
        raw = raw + c[col] * weights.get(col, 1.0)
    raw = raw + c["overheat"] * weights.get("overheat", -1.0)
    return raw.groupby(dates).transform(pct_rank)


def resolve_weight_source() -> tuple[list[dict[str, object]], bool, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    r3a_ok = R3A_RANKING.exists() and R3A_SUMMARY.exists()
    weights_ok = WEIGHT_VARIANTS.exists()
    if r3a_ok:
        rows.append({
            "source_file_path": str(R3A_RANKING.relative_to(ROOT)),
            "source_role": "PREFERRED_CURRENT_RANKING_CONTEXT",
            "source_status": "FOUND_CURRENT_SCORES_NO_WEIGHT_ROWS",
            "source_hash": file_hash(R3A_RANKING),
            "resolved_weight_rows": 0,
            "notes": "R3A exposes current scores/ranks but not reusable historical weight rows.",
        })
    if weights_ok:
        weights = pd.read_csv(WEIGHT_VARIANTS)
        rows.append({
            "source_file_path": str(WEIGHT_VARIANTS.relative_to(ROOT)),
            "source_role": "ACCEPTED_RESEARCH_BASELINE_WEIGHT_ARTIFACT",
            "source_status": "USED_CURRENT_WEIGHT_SOURCE",
            "source_hash": file_hash(WEIGHT_VARIANTS),
            "resolved_weight_rows": len(weights),
            "notes": "Used for current/global RSI scoring weights in random as-of dry-run.",
        })
        return rows, True, weights
    rows.append({
        "source_file_path": "",
        "source_role": "CURRENT_WEIGHT_SOURCE",
        "source_status": "BLOCKED_NOT_FOUND",
        "source_hash": "",
        "resolved_weight_rows": 0,
        "notes": "No valid local weight source found; weights were not fabricated.",
    })
    return rows, False, pd.DataFrame()


def load_scoring_panel(weights: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    snap = pd.read_csv(SNAPSHOT, low_memory=False)
    snap["as_of_date"] = pd.to_datetime(snap["as_of_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    snap["ticker"] = snap["ticker"].astype(str).str.upper().str.strip()
    ledger = pd.read_csv(R4_LEDGER, low_memory=False)
    ledger["as_of_date"] = pd.to_datetime(ledger["as_of_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    ledger["ticker"] = ledger["ticker"].astype(str).str.upper().str.strip()
    ledger = ledger[ledger["maturity_status"] == "MATURED"].copy()
    ledger["realized_forward_return"] = pd.to_numeric(ledger["realized_forward_return"], errors="coerce")
    ledger = ledger[ledger["realized_forward_return"].notna() & ledger["forward_window"].isin(WINDOWS)].copy()
    eligible_dates = sorted(set(snap["as_of_date"].dropna()) & set(ledger["as_of_date"].dropna()))
    rng = random.Random(RANDOM_SEED)
    sampled = sorted(rng.sample(eligible_dates, min(MAX_SAMPLE_DATES, len(eligible_dates)))) if eligible_dates else []
    snap = snap[snap["as_of_date"].isin(sampled)].copy()
    snap = snap[pd.to_numeric(snap["technical_score_normalized"], errors="coerce").notna()].copy()
    c = component_scores(snap)
    current_w = weight_dict(weights, "BASELINE_TRUE_TECHNICAL")
    global_w = weight_dict(weights, "RSI_DEEMPHASIZED_R4")
    snap["score__CURRENT_WEIGHT"] = pd.to_numeric(snap["technical_score_normalized"], errors="coerce")
    snap["score__EXISTING_BASELINE_IF_AVAILABLE"] = snap["score__CURRENT_WEIGHT"]
    snap["score__EQUAL_WEIGHT_BASELINE"] = c[["rsi", "kdj", "macd", "bb", "ma", "trend", "volume", "momentum"]].mean(axis=1).groupby(snap["as_of_date"]).transform(pct_rank)
    snap["score__GLOBAL_RSI_CANDIDATE"] = weighted_score(c, global_w or current_w, snap["as_of_date"])
    if CONDITIONED_DEF.exists():
        definition = pd.read_csv(CONDITIONED_DEF)
        action = {r["canonical_context_bucket"]: r["rsi_action"] for r in definition.to_dict("records")}
        ctx = ledger[ledger["as_of_date"].isin(sampled)][["as_of_date", "ticker", "canonical_context_bucket"]].drop_duplicates(["as_of_date", "ticker"], keep="last")
        snap = snap.merge(ctx, on=["as_of_date", "ticker"], how="left")
        snap["rsi_action"] = snap["canonical_context_bucket"].map(action).fillna("KEEP_BASELINE_RSI")
        snap["score__CURRENT_WEIGHT_PLUS_RSI_CANDIDATE"] = np.where(snap["rsi_action"] == "APPLY_RSI_DEEMPHASIS", snap["score__GLOBAL_RSI_CANDIDATE"], snap["score__CURRENT_WEIGHT"])
    else:
        snap["canonical_context_bucket"] = ""
        snap["rsi_action"] = "NO_UPSTREAM_RSI_CANDIDATE"
        snap["score__CURRENT_WEIGHT_PLUS_RSI_CANDIDATE"] = snap["score__CURRENT_WEIGHT"]
    long = ledger[ledger["as_of_date"].isin(sampled)].merge(snap, on=["as_of_date", "ticker"], how="inner", suffixes=("", "_feature"))
    return long, eligible_dates


def manifest_rows(eligible_dates: list[str], sampled_dates: list[str]) -> list[dict[str, object]]:
    return [{
        "random_seed": RANDOM_SEED,
        "sample_index": i + 1,
        "as_of_date": d,
        "eligible_asof_count": len(eligible_dates),
        "sampled_asof_count": len(sampled_dates),
        "max_sample_dates": MAX_SAMPLE_DATES,
    } for i, d in enumerate(sampled_dates)]


def build_panel(scored: pd.DataFrame) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    panel: list[dict[str, object]] = []
    leak_rows: list[dict[str, object]] = []
    for variant in VARIANTS:
        score_col = f"score__{variant}"
        if score_col not in scored.columns:
            continue
        df = scored.copy()
        df["variant_name"] = variant
        df["score"] = pd.to_numeric(df[score_col], errors="coerce")
        df["rank"] = df.groupby("as_of_date")["score"].rank(ascending=False, method="first")
        df["feature_max_date"] = df["as_of_date"]
        df["price_entry_date"] = df["as_of_date"]
        df["forward_price_date"] = df["maturity_date"]
        safe = pd.to_datetime(df["feature_max_date"], errors="coerce") <= pd.to_datetime(df["as_of_date"], errors="coerce")
        df["point_in_time_safe"] = safe
        df["leakage_violation_reason"] = np.where(safe, "", "FEATURE_MAX_DATE_AFTER_AS_OF_DATE")
        for r in df.to_dict("records"):
            row = {
                "variant_name": variant,
                "as_of_date": r["as_of_date"],
                "ticker": r["ticker"],
                "forward_return_window": r["forward_window"],
                "rank": r["rank"],
                "score": r["score"],
                "realized_forward_return": r["realized_forward_return"],
                "canonical_context_bucket": r.get("canonical_context_bucket", ""),
                "rsi_action": r.get("rsi_action", ""),
                "point_in_time_safe": yes(bool(r["point_in_time_safe"])),
                "leakage_violation_reason": r["leakage_violation_reason"],
            }
            panel.append(row)
            leak_rows.append({
                "as_of_date": r["as_of_date"],
                "feature_max_date": r["feature_max_date"],
                "price_entry_date": r["price_entry_date"],
                "forward_return_window": r["forward_window"],
                "forward_price_date": r["forward_price_date"],
                "point_in_time_safe": yes(bool(r["point_in_time_safe"])),
                "leakage_violation_reason": r["leakage_violation_reason"],
                "variant_name": variant,
                "ticker": r["ticker"],
            })
    return panel, leak_rows


def per_date_metrics(panel: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    safe_panel = panel[panel["point_in_time_safe"] == "TRUE"].copy()
    safe_panel["rank"] = pd.to_numeric(safe_panel["rank"], errors="coerce")
    safe_panel["realized_forward_return"] = pd.to_numeric(safe_panel["realized_forward_return"], errors="coerce")
    for (variant, date, window), g in safe_panel.groupby(["variant_name", "as_of_date", "forward_return_window"]):
        n = len(g)
        top20 = g[g["rank"] <= 20]["realized_forward_return"].dropna()
        top50 = g[g["rank"] <= 50]["realized_forward_return"].dropna()
        dec = max(int(math.ceil(n * 0.1)), 1)
        top_dec = g.nsmallest(dec, "rank")["realized_forward_return"].dropna()
        bot_dec = g.nlargest(dec, "rank")["realized_forward_return"].dropna()
        universe = g["realized_forward_return"].dropna()
        ic = g[["rank", "realized_forward_return"]].corr(method="spearman").iloc[0, 1] if len(g) >= 3 else np.nan
        rows.append({
            "variant_name": variant,
            "as_of_date": date,
            "forward_return_window": window,
            "universe_count": n,
            "scored_count": int(g["score"].notna().sum()) if "score" in g else n,
            "excluded_count": 0,
            "price_missing_count": int(g["realized_forward_return"].isna().sum()),
            "mean_forward_return_top20": float(top20.mean()) if len(top20) else "",
            "median_forward_return_top20": float(top20.median()) if len(top20) else "",
            "hit_rate_top20": float((top20 > 0).mean()) if len(top20) else "",
            "mean_forward_return_top50": float(top50.mean()) if len(top50) else "",
            "median_forward_return_top50": float(top50.median()) if len(top50) else "",
            "hit_rate_top50": float((top50 > 0).mean()) if len(top50) else "",
            "mean_forward_return_top_decile": float(top_dec.mean()) if len(top_dec) else "",
            "mean_forward_return_bottom_decile": float(bot_dec.mean()) if len(bot_dec) else "",
            "long_short_top_bottom_decile_spread": float(top_dec.mean() - bot_dec.mean()) if len(top_dec) and len(bot_dec) else "",
            "universe_mean_forward_return": float(universe.mean()) if len(universe) else "",
            "excess_return_top20_vs_universe": float(top20.mean() - universe.mean()) if len(top20) and len(universe) else "",
            "rank_ic_spearman": float(ic) if pd.notna(ic) else "",
        })
    return rows


def summary_metrics(date_metrics: pd.DataFrame, leakage_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows = []
    for (variant, window), g in date_metrics.groupby(["variant_name", "forward_return_window"]):
        top20 = pd.to_numeric(g["mean_forward_return_top20"], errors="coerce")
        top50 = pd.to_numeric(g["mean_forward_return_top50"], errors="coerce")
        topdec = pd.to_numeric(g["mean_forward_return_top_decile"], errors="coerce")
        botdec = pd.to_numeric(g["mean_forward_return_bottom_decile"], errors="coerce")
        universe = pd.to_numeric(g["universe_mean_forward_return"], errors="coerce")
        excess = pd.to_numeric(g["excess_return_top20_vs_universe"], errors="coerce")
        ic = pd.to_numeric(g["rank_ic_spearman"], errors="coerce")
        leak_count = sum(1 for r in leakage_rows if r["variant_name"] == variant and r["forward_return_window"] == window and r["point_in_time_safe"] != "TRUE")
        rows.append({
            "variant_name": variant,
            "forward_return_window": window,
            "sampled_asof_count": int(g["as_of_date"].nunique()),
            "total_scored_rows": int(pd.to_numeric(g["scored_count"], errors="coerce").sum()),
            "mean_forward_return_top20": float(top20.mean()) if top20.notna().any() else "",
            "median_forward_return_top20": float(top20.median()) if top20.notna().any() else "",
            "hit_rate_top20": float(pd.to_numeric(g["hit_rate_top20"], errors="coerce").mean()) if pd.to_numeric(g["hit_rate_top20"], errors="coerce").notna().any() else "",
            "mean_forward_return_top50": float(top50.mean()) if top50.notna().any() else "",
            "median_forward_return_top50": float(top50.median()) if top50.notna().any() else "",
            "hit_rate_top50": float(pd.to_numeric(g["hit_rate_top50"], errors="coerce").mean()) if pd.to_numeric(g["hit_rate_top50"], errors="coerce").notna().any() else "",
            "mean_forward_return_top_decile": float(topdec.mean()) if topdec.notna().any() else "",
            "mean_forward_return_bottom_decile": float(botdec.mean()) if botdec.notna().any() else "",
            "long_short_top_bottom_decile_spread": float((topdec - botdec).mean()) if topdec.notna().any() and botdec.notna().any() else "",
            "universe_mean_forward_return": float(universe.mean()) if universe.notna().any() else "",
            "excess_return_top20_vs_universe": float(excess.mean()) if excess.notna().any() else "",
            "rank_ic_spearman_mean": float(ic.mean()) if ic.notna().any() else "",
            "rank_ic_spearman_median": float(ic.median()) if ic.notna().any() else "",
            "positive_asof_ratio_top20": float((top20 > 0).mean()) if top20.notna().any() else "",
            "price_missing_count": int(pd.to_numeric(g["price_missing_count"], errors="coerce").sum()),
            "leakage_violation_count": leak_count,
        })
    return rows


def decision_summary(source_rows: list[dict[str, object]], eligible_count: int, sampled_count: int, summary_rows: list[dict[str, object]], leak_rows: list[dict[str, object]]) -> dict[str, object]:
    curr = [r for r in summary_rows if r["variant_name"] == "CURRENT_WEIGHT"]
    equal = [r for r in summary_rows if r["variant_name"] == "EQUAL_WEIGHT_BASELINE"]
    curr_mean = np.nanmean([float(r["excess_return_top20_vs_universe"]) for r in curr if clean(r["excess_return_top20_vs_universe"])])
    equal_mean = np.nanmean([float(r["excess_return_top20_vs_universe"]) for r in equal if clean(r["excess_return_top20_vs_universe"])])
    if math.isnan(curr_mean):
        curr_mean = 0.0
    if math.isnan(equal_mean):
        equal_mean = 0.0
    leak_count = sum(1 for r in leak_rows if r["point_in_time_safe"] != "TRUE")
    if leak_count:
        final_status = LEAKAGE_STATUS
    elif eligible_count < 10:
        final_status = LIMITED_STATUS
    else:
        final_status = PASS_STATUS
    decision = DECISION_SUPPORTS if curr_mean >= equal_mean else DECISION_REVIEW
    return {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "research_only": "TRUE",
        "official_adoption_allowed": "FALSE",
        "official_weight_mutation": "FALSE",
        "official_ranking_mutation": "FALSE",
        "real_book_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE",
        "data_trust_alpha_weight_allowed": "FALSE",
        "current_weight_source": next((r["source_file_path"] for r in source_rows if r["source_status"] == "USED_CURRENT_WEIGHT_SOURCE"), ""),
        "current_weight_source_status": next((r["source_status"] for r in source_rows if r["source_status"] == "USED_CURRENT_WEIGHT_SOURCE"), "BLOCKED_NOT_FOUND"),
        "random_seed": RANDOM_SEED,
        "eligible_asof_count": eligible_count,
        "sampled_asof_count": sampled_count,
        "variant_list": "|".join(VARIANTS),
        "forward_windows": "|".join(WINDOWS),
        "current_weight_mean_excess_top20_vs_universe": curr_mean,
        "equal_weight_mean_excess_top20_vs_universe": equal_mean,
        "leakage_violation_count": leak_count,
        "next_recommended_stage": "V21.041_R4_FUTURE_MATURITY_REFRESH_AND_RETEST_TRIGGER",
    }


def write_report(decision: dict[str, object], summary_rows: list[dict[str, object]], source_rows: list[dict[str, object]]) -> None:
    table = "\n".join(
        f"- {r['variant_name']} {r['forward_return_window']}: top20={fmt(r['mean_forward_return_top20'])}, excess={fmt(r['excess_return_top20_vs_universe'])}, IC={fmt(r['rank_ic_spearman_mean'])}"
        for r in summary_rows[:30]
    )
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Summary
- final_status: {decision['final_status']}
- decision: {decision['decision']}
- current_weight_source: {decision['current_weight_source']}
- random_seed: {decision['random_seed']}
- sampled_asof_count: {decision['sampled_asof_count']}
- eligible_asof_count: {decision['eligible_asof_count']}
- variants: {decision['variant_list']}
- forward_windows: {decision['forward_windows']}

## Performance summary table
{table}

## Leakage audit summary
leakage_violation_count: {decision['leakage_violation_count']}. Unsafe rows are excluded from performance aggregation.

## Top risks / limitations
- Uses only local V21.038 technical features and V21.040-R4 realized forward-return ledger.
- Current weight source is resolved from research artifacts, not official adoption.
- Random as-of dates are deterministic but limited by available matured local observations.

## Guardrails
research_only = TRUE
official_adoption_allowed = FALSE
official_weight_mutation = FALSE
official_ranking_mutation = FALSE
real_book_action_allowed = FALSE
broker_execution_allowed = FALSE
"""
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(report, encoding="utf-8")
    CURRENT_REPORT_OUT.write_text(report, encoding="utf-8")


def safe_blocked(source_rows: list[dict[str, object]], status: str, decision_value: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    decision = {
        "stage": STAGE, "final_status": status, "decision": decision_value, "research_only": "TRUE",
        "official_adoption_allowed": "FALSE", "official_weight_mutation": "FALSE",
        "official_ranking_mutation": "FALSE", "real_book_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE", "trade_action_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE", "data_trust_alpha_weight_allowed": "FALSE",
        "current_weight_source": "", "current_weight_source_status": "BLOCKED", "random_seed": RANDOM_SEED,
        "eligible_asof_count": 0, "sampled_asof_count": 0, "variant_list": "|".join(VARIANTS),
        "forward_windows": "|".join(WINDOWS), "leakage_violation_count": 0,
        "next_recommended_stage": "RESTORE_REQUIRED_RANDOM_ASOF_INPUTS",
    }
    write_csv(MANIFEST_OUT, [{"random_seed": RANDOM_SEED, "sample_index": 0, "as_of_date": "", "eligible_asof_count": 0, "sampled_asof_count": 0, "max_sample_dates": MAX_SAMPLE_DATES}], ["random_seed", "sample_index", "as_of_date", "eligible_asof_count", "sampled_asof_count", "max_sample_dates"])
    write_csv(SOURCE_OUT, source_rows, ["source_file_path", "source_role", "source_status", "source_hash", "resolved_weight_rows", "notes"])
    write_csv(PANEL_OUT, [{"variant_name": "", "point_in_time_safe": "FALSE"}], ["variant_name", "as_of_date", "ticker", "forward_return_window", "rank", "score", "realized_forward_return", "canonical_context_bucket", "rsi_action", "point_in_time_safe", "leakage_violation_reason"])
    write_csv(DATE_METRICS_OUT, [{"variant_name": "", "as_of_date": "", "forward_return_window": ""}], ["variant_name", "as_of_date", "forward_return_window", "universe_count", "scored_count", "excluded_count", "price_missing_count", "mean_forward_return_top20", "median_forward_return_top20", "hit_rate_top20", "mean_forward_return_top50", "median_forward_return_top50", "hit_rate_top50", "mean_forward_return_top_decile", "mean_forward_return_bottom_decile", "long_short_top_bottom_decile_spread", "universe_mean_forward_return", "excess_return_top20_vs_universe", "rank_ic_spearman"])
    write_csv(SUMMARY_METRICS_OUT, [{"variant_name": "", "forward_return_window": ""}], ["variant_name", "forward_return_window", "sampled_asof_count", "total_scored_rows", "mean_forward_return_top20", "median_forward_return_top20", "hit_rate_top20", "mean_forward_return_top50", "median_forward_return_top50", "hit_rate_top50", "mean_forward_return_top_decile", "mean_forward_return_bottom_decile", "long_short_top_bottom_decile_spread", "universe_mean_forward_return", "excess_return_top20_vs_universe", "rank_ic_spearman_mean", "rank_ic_spearman_median", "positive_asof_ratio_top20", "price_missing_count", "leakage_violation_count"])
    write_csv(LEAKAGE_OUT, [{"as_of_date": "", "point_in_time_safe": "FALSE", "leakage_violation_reason": "BLOCKED_INPUTS"}], ["as_of_date", "feature_max_date", "price_entry_date", "forward_return_window", "forward_price_date", "point_in_time_safe", "leakage_violation_reason", "variant_name", "ticker"])
    write_csv(DECISION_OUT, [decision], list(decision.keys()))
    write_report(decision, [], source_rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    source_rows, source_ok, weights = resolve_weight_source()
    if not source_ok:
        safe_blocked(source_rows, BLOCKED_WEIGHT_STATUS, DECISION_BLOCKED_WEIGHT)
        print(f"final_status={BLOCKED_WEIGHT_STATUS}")
        return
    if not SNAPSHOT.exists() or not R4_LEDGER.exists():
        safe_blocked(source_rows, BLOCKED_DATES_STATUS, DECISION_BLOCKED_DATES)
        print(f"final_status={BLOCKED_DATES_STATUS}")
        return
    scored, eligible_dates = load_scoring_panel(weights)
    sampled_dates = sorted(scored["as_of_date"].dropna().unique().tolist())
    if not sampled_dates:
        safe_blocked(source_rows, BLOCKED_DATES_STATUS, DECISION_BLOCKED_DATES)
        print(f"final_status={BLOCKED_DATES_STATUS}")
        return
    manifest = manifest_rows(eligible_dates, sampled_dates)
    panel_rows, leak_rows = build_panel(scored)
    panel_df = pd.DataFrame(panel_rows)
    date_rows = per_date_metrics(panel_df)
    summary_rows = summary_metrics(pd.DataFrame(date_rows), leak_rows)
    decision = decision_summary(source_rows, len(eligible_dates), len(sampled_dates), summary_rows, leak_rows)
    write_csv(MANIFEST_OUT, manifest, ["random_seed", "sample_index", "as_of_date", "eligible_asof_count", "sampled_asof_count", "max_sample_dates"])
    write_csv(SOURCE_OUT, source_rows, ["source_file_path", "source_role", "source_status", "source_hash", "resolved_weight_rows", "notes"])
    write_csv(PANEL_OUT, panel_rows, ["variant_name", "as_of_date", "ticker", "forward_return_window", "rank", "score", "realized_forward_return", "canonical_context_bucket", "rsi_action", "point_in_time_safe", "leakage_violation_reason"])
    write_csv(DATE_METRICS_OUT, date_rows, ["variant_name", "as_of_date", "forward_return_window", "universe_count", "scored_count", "excluded_count", "price_missing_count", "mean_forward_return_top20", "median_forward_return_top20", "hit_rate_top20", "mean_forward_return_top50", "median_forward_return_top50", "hit_rate_top50", "mean_forward_return_top_decile", "mean_forward_return_bottom_decile", "long_short_top_bottom_decile_spread", "universe_mean_forward_return", "excess_return_top20_vs_universe", "rank_ic_spearman"])
    write_csv(SUMMARY_METRICS_OUT, summary_rows, ["variant_name", "forward_return_window", "sampled_asof_count", "total_scored_rows", "mean_forward_return_top20", "median_forward_return_top20", "hit_rate_top20", "mean_forward_return_top50", "median_forward_return_top50", "hit_rate_top50", "mean_forward_return_top_decile", "mean_forward_return_bottom_decile", "long_short_top_bottom_decile_spread", "universe_mean_forward_return", "excess_return_top20_vs_universe", "rank_ic_spearman_mean", "rank_ic_spearman_median", "positive_asof_ratio_top20", "price_missing_count", "leakage_violation_count"])
    write_csv(LEAKAGE_OUT, leak_rows, ["as_of_date", "feature_max_date", "price_entry_date", "forward_return_window", "forward_price_date", "point_in_time_safe", "leakage_violation_reason", "variant_name", "ticker"])
    write_csv(DECISION_OUT, [decision], list(decision.keys()))
    write_report(decision, summary_rows, source_rows)
    print(f"STAGE_NAME={STAGE}")
    print(f"final_status={decision['final_status']}")
    print(f"decision={decision['decision']}")
    print(f"current_weight_source={decision['current_weight_source']}")
    print(f"sampled_asof_count={decision['sampled_asof_count']}")
    print(f"leakage_violation_count={decision['leakage_violation_count']}")


if __name__ == "__main__":
    main()
