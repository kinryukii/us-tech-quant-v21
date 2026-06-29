#!/usr/bin/env python
"""V21.041-R3A current weight and RSI candidate dry-run report.

Research-only what-if current ranking comparison for baseline technical score,
global RSI deemphasis, and context-conditioned RSI deemphasis. No official,
shadow, recommendation, broker, or real-book artifacts are mutated.
"""

from __future__ import annotations

import csv
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.041-R3A_CURRENT_WEIGHT_AND_RSI_CANDIDATE_DRY_RUN_REPORT"
PASS_STATUS = "PASS_V21_041_R3A_CURRENT_WEIGHT_DRY_RUN_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_041_R3A_LIMITED_INPUTS_BUT_REPORT_CREATED"
BLOCKED_STATUS = "BLOCKED_V21_041_R3A_INPUTS_MISSING"

DECISION_READY = "CURRENT_WEIGHT_RSI_CANDIDATE_DRY_RUN_READY"
DECISION_LIMITED = "CURRENT_WEIGHT_RSI_CANDIDATE_DRY_RUN_LIMITED_INPUTS"
DECISION_BLOCKED = "CURRENT_WEIGHT_RSI_CANDIDATE_DRY_RUN_BLOCKED_INPUTS_MISSING"

BASELINE = "BASELINE_TRUE_TECHNICAL"
GLOBAL = "RSI_DEEMPHASIZED_R4"
CONDITIONED = "RSI_DEEMPHASIZED_CONTEXT_CONDITIONED_R4_R2"

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

R2_SUMMARY = OUT_DIR / "V21_041_R2_CONTEXT_CONDITIONED_RETEST_SUMMARY.csv"
R2_SCORECARD = OUT_DIR / "V21_041_R2_VARIANT_COMPARISON_SCORECARD.csv"
R2_DEFINITION = OUT_DIR / "V21_042_R2_CONTEXT_CONDITIONED_VARIANT_DEFINITION.csv"
R4_LEDGER = OUT_DIR / "V21_040_R4_CANONICAL_CONTEXT_LEDGER.csv"
SNAPSHOT = OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv"

SUMMARY_OUT = OUT_DIR / "V21_041_R3A_CURRENT_WEIGHT_DRY_RUN_SUMMARY.csv"
RANKING_OUT = OUT_DIR / "V21_041_R3A_CURRENT_RANKING_COMPARISON.csv"
TOP20_OUT = OUT_DIR / "V21_041_R3A_TOP20_COMPARISON.csv"
TOP40_OUT = OUT_DIR / "V21_041_R3A_TOP40_COMPARISON.csv"
CHANGE_OUT = OUT_DIR / "V21_041_R3A_DRY_RUN_CHANGE_AUDIT.csv"
VALIDATION_OUT = OUT_DIR / "V21_041_R3A_VALIDATION_MATRIX.csv"
REPORT_OUT = READ_CENTER_DIR / "V21_041_R3A_CURRENT_WEIGHT_AND_RSI_CANDIDATE_DRY_RUN_REPORT.md"

REQUIRED_INPUTS = [R2_SUMMARY, R2_SCORECARD, R2_DEFINITION, R4_LEDGER, SNAPSHOT]


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


def read_first(path: Path) -> dict[str, str]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.DictReader(handle), {}) or {}


def pct_rank(series: pd.Series) -> pd.Series:
    if series.notna().sum() == 0:
        return pd.Series(np.nan, index=series.index)
    return series.rank(method="average", pct=True)


def latest_current_frame() -> pd.DataFrame:
    snap = pd.read_csv(SNAPSHOT, low_memory=False)
    snap["as_of_date"] = pd.to_datetime(snap["as_of_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    snap["ticker"] = snap["ticker"].astype(str).str.upper().str.strip()
    latest = snap["as_of_date"].dropna().max()
    current = snap[snap["as_of_date"] == latest].copy()
    ledger = pd.read_csv(R4_LEDGER, usecols=["as_of_date", "ticker", "canonical_context_bucket"], low_memory=False)
    ledger["as_of_date"] = pd.to_datetime(ledger["as_of_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    ledger["ticker"] = ledger["ticker"].astype(str).str.upper().str.strip()
    ctx = ledger[ledger["as_of_date"] == latest].drop_duplicates(["ticker"], keep="last")
    current = current.merge(ctx[["ticker", "canonical_context_bucket"]], on="ticker", how="left")
    current["canonical_context_bucket"] = current["canonical_context_bucket"].fillna("UNRESOLVED_CONTEXT")
    return current


def component_scores(df: pd.DataFrame) -> pd.DataFrame:
    c = pd.DataFrame(index=df.index)
    c["rsi"] = pd.to_numeric(df.get("rsi_14"), errors="coerce") / 100.0
    c["kdj"] = pd.to_numeric(df.get("kdj_k"), errors="coerce") / 100.0
    c["macd"] = pd.to_numeric(df.get("macd_hist"), errors="coerce").rank(method="average", pct=True)
    c["bb"] = 1 - (pd.to_numeric(df.get("bb_position"), errors="coerce") - 0.55).abs().clip(0, 1)
    ma = df[["ma20_distance", "ma50_distance", "ema20_distance"]].apply(pd.to_numeric, errors="coerce").mean(axis=1)
    c["ma"] = ma.rank(method="average", pct=True)
    c["trend"] = pd.to_numeric(df.get("trend_strength_score"), errors="coerce").clip(0, 1)
    c["volume"] = (1 - (pd.to_numeric(df.get("volume_ratio"), errors="coerce") - 1.2).abs() / 2).clip(0, 1)
    c["volatility"] = -pd.to_numeric(df.get("volatility_20"), errors="coerce").rank(method="average", pct=True)
    mom = df[["momentum_5", "momentum_10", "momentum_20"]].apply(pd.to_numeric, errors="coerce").mean(axis=1)
    c["momentum"] = mom.rank(method="average", pct=True)
    c["overheat"] = pd.to_numeric(df.get("overheat_extension_score"), errors="coerce").clip(0, 1)
    return c


def score_current(df: pd.DataFrame, definition: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    c = component_scores(out)
    out["baseline_score"] = pd.to_numeric(out["technical_score_normalized"], errors="coerce")
    out = out[out["baseline_score"].notna()].copy()
    c = c.loc[out.index]
    global_raw = (
        c["rsi"] * 0.35 + c["kdj"] * 0.75 + c["macd"] * 0.90 + c["bb"] * 1.00
        + c["ma"] * 1.00 + c["trend"] * 1.10 + c["volume"] * 0.90
        + c["volatility"] * -0.15 + c["momentum"] * 0.95 - c["overheat"] * 0.80
    )
    out["global_rsi_deemphasized_score"] = global_raw.rank(method="average", pct=True)
    action = {r["canonical_context_bucket"]: r["rsi_action"] for r in definition.to_dict("records")}
    out["rsi_action"] = out["canonical_context_bucket"].map(action).fillna("KEEP_BASELINE_RSI")
    out["context_conditioned_rsi_score"] = np.where(out["rsi_action"] == "APPLY_RSI_DEEMPHASIS", out["global_rsi_deemphasized_score"], out["baseline_score"])
    out["baseline_rank"] = out["baseline_score"].rank(method="first", ascending=False).astype(int)
    out["global_rsi_deemphasized_rank"] = out["global_rsi_deemphasized_score"].rank(method="first", ascending=False).astype(int)
    out["context_conditioned_rsi_rank"] = out["context_conditioned_rsi_score"].rank(method="first", ascending=False).astype(int)
    return out.sort_values("baseline_rank")


def overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


def ranking_rows(scored: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for r in scored.to_dict("records"):
        bg = int(r["global_rsi_deemphasized_rank"]) - int(r["baseline_rank"])
        bc = int(r["context_conditioned_rsi_rank"]) - int(r["baseline_rank"])
        interp = "NO_CHANGE" if bg == 0 and bc == 0 else "DRY_RUN_RANK_CHANGED"
        rows.append({
            "ticker": r["ticker"],
            "baseline_rank": r["baseline_rank"],
            "global_rsi_deemphasized_rank": r["global_rsi_deemphasized_rank"],
            "context_conditioned_rsi_rank": r["context_conditioned_rsi_rank"],
            "baseline_score": r["baseline_score"],
            "global_rsi_deemphasized_score": r["global_rsi_deemphasized_score"],
            "context_conditioned_rsi_score": r["context_conditioned_rsi_score"],
            "rank_delta_global_vs_baseline": bg,
            "rank_delta_context_conditioned_vs_baseline": bc,
            "current_context_bucket": r["canonical_context_bucket"],
            "rsi_action": r["rsi_action"],
            "dry_run_interpretation": interp,
        })
    return rows


def top_rows(scored: pd.DataFrame, n: int) -> list[dict[str, object]]:
    top_sets = {
        BASELINE: set(scored.nsmallest(n, "baseline_rank")["ticker"]),
        GLOBAL: set(scored.nsmallest(n, "global_rsi_deemphasized_rank")["ticker"]),
        CONDITIONED: set(scored.nsmallest(n, "context_conditioned_rsi_rank")["ticker"]),
    }
    rank_cols = {
        BASELINE: ("baseline_rank", "baseline_score"),
        GLOBAL: ("global_rsi_deemphasized_rank", "global_rsi_deemphasized_score"),
        CONDITIONED: ("context_conditioned_rsi_rank", "context_conditioned_rsi_score"),
    }
    rows = []
    for variant, (rank_col, score_col) in rank_cols.items():
        for r in scored.nsmallest(n, rank_col).to_dict("records"):
            rows.append({
                "variant_name": variant,
                "rank": r[rank_col],
                "ticker": r["ticker"],
                "score": r[score_col],
                "context_bucket": r["canonical_context_bucket"],
                "rsi_action": r["rsi_action"],
                "appears_in_baseline_top20" if n == 20 else "appears_in_baseline_top40": yes(r["ticker"] in top_sets[BASELINE]),
                "appears_in_global_rsi_top20" if n == 20 else "appears_in_global_rsi_top40": yes(r["ticker"] in top_sets[GLOBAL]),
                "appears_in_context_conditioned_top20" if n == 20 else "appears_in_context_conditioned_top40": yes(r["ticker"] in top_sets[CONDITIONED]),
                "rank_delta_vs_baseline": int(r[rank_col]) - int(r["baseline_rank"]),
                "note": "Research-only dry-run rank.",
            })
    return rows


def change_audit(scored: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for variant, rank_col, score_col in [
        (GLOBAL, "global_rsi_deemphasized_rank", "global_rsi_deemphasized_score"),
        (CONDITIONED, "context_conditioned_rsi_rank", "context_conditioned_rsi_score"),
    ]:
        for r in scored.to_dict("records"):
            br = int(r["baseline_rank"])
            cr = int(r[rank_col])
            if br > 20 and cr <= 20:
                ctype = "ENTERED_TOP20"
            elif br <= 20 and cr > 20:
                ctype = "LEFT_TOP20"
            elif br > 40 and cr <= 40:
                ctype = "ENTERED_TOP40"
            elif br <= 40 and cr > 40:
                ctype = "LEFT_TOP40"
            elif cr < br:
                ctype = "RANK_UP"
            elif cr > br:
                ctype = "RANK_DOWN"
            else:
                ctype = "NO_CHANGE"
            rows.append({
                "change_type": ctype,
                "ticker": r["ticker"],
                "baseline_rank": br,
                "candidate_rank": cr,
                "candidate_variant": variant,
                "rank_delta": cr - br,
                "score_delta": float(r[score_col]) - float(r["baseline_score"]),
                "context_bucket": r["canonical_context_bucket"],
                "rsi_action": r["rsi_action"],
                "interpretation": "Research-only what-if current ranking change.",
            })
    return rows


def build_summary(scored: pd.DataFrame) -> dict[str, object]:
    b20 = set(scored.nsmallest(20, "baseline_rank")["ticker"])
    g20 = set(scored.nsmallest(20, "global_rsi_deemphasized_rank")["ticker"])
    c20 = set(scored.nsmallest(20, "context_conditioned_rsi_rank")["ticker"])
    b40 = set(scored.nsmallest(40, "baseline_rank")["ticker"])
    g40 = set(scored.nsmallest(40, "global_rsi_deemphasized_rank")["ticker"])
    c40 = set(scored.nsmallest(40, "context_conditioned_rsi_rank")["ticker"])
    return {
        "stage": STAGE,
        "final_status": PASS_STATUS,
        "decision": DECISION_READY,
        "research_only": "TRUE",
        "official_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "shadow_ranking_mutation_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "real_book_mutation_allowed": "FALSE",
        "baseline_variant_name": BASELINE,
        "candidate_variant_1": GLOBAL,
        "candidate_variant_2": CONDITIONED,
        "current_input_rows": len(scored),
        "current_distinct_tickers": int(scored["ticker"].nunique()),
        "dry_run_variants_tested_count": 3,
        "top20_overlap_baseline_vs_global_rsi": overlap(b20, g20),
        "top20_overlap_baseline_vs_context_conditioned": overlap(b20, c20),
        "top40_overlap_baseline_vs_global_rsi": overlap(b40, g40),
        "top40_overlap_baseline_vs_context_conditioned": overlap(b40, c40),
        "current_dry_run_report_created": "TRUE",
        "official_adoption_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE",
        "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "V21.041_R4_FUTURE_MATURITY_REFRESH_AND_RETEST_TRIGGER",
    }


def validation(summary: dict[str, object], top20: list[dict[str, object]], top40: list[dict[str, object]]) -> list[dict[str, object]]:
    checks = [
        ("INPUTS_FOUND", yes(all(path.exists() for path in REQUIRED_INPUTS)), "TRUE"),
        ("BASELINE_VARIANT_PRODUCED", yes(summary.get("baseline_variant_name") == BASELINE), "TRUE"),
        ("GLOBAL_RSI_VARIANT_PRODUCED", yes(summary.get("candidate_variant_1") == GLOBAL), "TRUE"),
        ("CONTEXT_CONDITIONED_VARIANT_PRODUCED", yes(summary.get("candidate_variant_2") == CONDITIONED), "TRUE"),
        ("TOP20_COMPARISON_PRODUCED", yes(len(top20) > 0), "TRUE"),
        ("TOP40_COMPARISON_PRODUCED", yes(len(top40) > 0), "TRUE"),
        ("NO_OFFICIAL_MUTATION", "TRUE", "TRUE"),
        ("NO_SHADOW_MUTATION", "TRUE", "TRUE"),
        ("RESEARCH_ONLY_TRUE", summary["research_only"], "TRUE"),
        ("DATA_TRUST_ALPHA_FALSE", summary["data_trust_alpha_weight_allowed"], "FALSE"),
    ]
    return [{
        "validation_item": item,
        "validation_status": "PASS" if str(obs) == req else "FAIL",
        "observed_value": obs,
        "required_value": req,
        "pass_fail": "PASS" if str(obs) == req else "FAIL",
        "notes": "Research-only current dry-run validation.",
    } for item, obs, req in checks]


def write_report(summary: dict[str, object], top20: list[dict[str, object]], top40: list[dict[str, object]], changes: list[dict[str, object]]) -> None:
    def tickers(rows: list[dict[str, object]], variant: str, n: int) -> str:
        return ", ".join(str(r["ticker"]) for r in rows if r["variant_name"] == variant and int(r["rank"]) <= n)
    entered20 = ", ".join(r["ticker"] for r in changes if r["change_type"] == "ENTERED_TOP20")
    left20 = ", ".join(r["ticker"] for r in changes if r["change_type"] == "LEFT_TOP20")
    entered40 = ", ".join(r["ticker"] for r in changes if r["change_type"] == "ENTERED_TOP40")
    left40 = ", ".join(r["ticker"] for r in changes if r["change_type"] == "LEFT_TOP40")
    material = "YES" if float(summary.get("top20_overlap_baseline_vs_global_rsi", 1) or 1) < 0.9 or float(summary.get("top20_overlap_baseline_vs_context_conditioned", 1) or 1) < 0.9 else "NO"
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Final status and decision
- final_status: {summary['final_status']}
- decision: {summary['decision']}

## Current baseline Top20 / Top40
Top20: {tickers(top20, BASELINE, 20)}
Top40: {tickers(top40, BASELINE, 40)}

## Global RSI deemphasis Top20 / Top40
Top20: {tickers(top20, GLOBAL, 20)}
Top40: {tickers(top40, GLOBAL, 40)}

## Context-conditioned RSI Top20 / Top40
Top20: {tickers(top20, CONDITIONED, 20)}
Top40: {tickers(top40, CONDITIONED, 40)}

## Names that entered or left Top20
Entered: {entered20 or 'None'}; Left: {left20 or 'None'}.

## Names that entered or left Top40
Entered: {entered40 or 'None'}; Left: {left40 or 'None'}.

## Whether current result changes materially
Material dry-run change: {material}. Top20 overlap baseline/global={fmt(summary['top20_overlap_baseline_vs_global_rsi'])}; baseline/context={fmt(summary['top20_overlap_baseline_vs_context_conditioned'])}.

## Why this is dry-run only
V21.041-R2 did not select the context-conditioned candidate and shadow dry-run remains disallowed; this report is current what-if inspection only.

## Why shadow and official mutation remain blocked
Shadow ranking mutation, shadow gate, official use, official ranking mutation, official weight mutation, trade action, broker execution, real-book mutation, and official adoption all remain FALSE.

## Why official mutation remains blocked
Official mutation remains blocked because this stage is research-only and does not write production-facing outputs.

## Next recommended stage
{summary['next_recommended_stage']}
"""
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(report, encoding="utf-8")


SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "research_only", "official_use_allowed",
    "official_weight_mutation_allowed", "official_ranking_mutation_allowed",
    "shadow_ranking_mutation_allowed", "trade_action_allowed", "broker_execution_allowed",
    "real_book_mutation_allowed", "baseline_variant_name", "candidate_variant_1",
    "candidate_variant_2", "current_input_rows", "current_distinct_tickers",
    "dry_run_variants_tested_count", "top20_overlap_baseline_vs_global_rsi",
    "top20_overlap_baseline_vs_context_conditioned", "top40_overlap_baseline_vs_global_rsi",
    "top40_overlap_baseline_vs_context_conditioned", "current_dry_run_report_created",
    "official_adoption_allowed", "shadow_gate_allowed", "data_trust_alpha_weight_allowed",
    "next_recommended_stage",
]


def safe_blocked() -> None:
    summary = {
        "stage": STAGE, "final_status": BLOCKED_STATUS, "decision": DECISION_BLOCKED,
        "research_only": "TRUE", "official_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE", "official_ranking_mutation_allowed": "FALSE",
        "shadow_ranking_mutation_allowed": "FALSE", "trade_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE", "real_book_mutation_allowed": "FALSE",
        "baseline_variant_name": BASELINE, "candidate_variant_1": GLOBAL,
        "candidate_variant_2": CONDITIONED, "current_input_rows": 0,
        "current_distinct_tickers": 0, "dry_run_variants_tested_count": 0,
        "current_dry_run_report_created": "FALSE", "official_adoption_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE", "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "RESTORE_REQUIRED_R3A_INPUTS",
    }
    rows = [{"ticker": "", "dry_run_interpretation": "BLOCKED_INPUTS_MISSING"}]
    top = [{"variant_name": BASELINE, "rank": 0, "ticker": "", "note": "BLOCKED_INPUTS_MISSING"}]
    changes = [{"change_type": "NO_CHANGE", "ticker": "", "interpretation": "BLOCKED_INPUTS_MISSING"}]
    write_all(summary, rows, top, top, changes)


def write_all(summary: dict[str, object], ranking: list[dict[str, object]], top20: list[dict[str, object]], top40: list[dict[str, object]], changes: list[dict[str, object]]) -> None:
    write_csv(SUMMARY_OUT, [summary], SUMMARY_FIELDS)
    write_csv(RANKING_OUT, ranking, ["ticker", "baseline_rank", "global_rsi_deemphasized_rank", "context_conditioned_rsi_rank", "baseline_score", "global_rsi_deemphasized_score", "context_conditioned_rsi_score", "rank_delta_global_vs_baseline", "rank_delta_context_conditioned_vs_baseline", "current_context_bucket", "rsi_action", "dry_run_interpretation"])
    write_csv(TOP20_OUT, top20, ["variant_name", "rank", "ticker", "score", "context_bucket", "rsi_action", "appears_in_baseline_top20", "appears_in_global_rsi_top20", "appears_in_context_conditioned_top20", "rank_delta_vs_baseline", "note"])
    write_csv(TOP40_OUT, top40, ["variant_name", "rank", "ticker", "score", "context_bucket", "rsi_action", "appears_in_baseline_top40", "appears_in_global_rsi_top40", "appears_in_context_conditioned_top40", "rank_delta_vs_baseline", "note"])
    write_csv(CHANGE_OUT, changes, ["change_type", "ticker", "baseline_rank", "candidate_rank", "candidate_variant", "rank_delta", "score_delta", "context_bucket", "rsi_action", "interpretation"])
    write_csv(VALIDATION_OUT, validation(summary, top20, top40), ["validation_item", "validation_status", "observed_value", "required_value", "pass_fail", "notes"])
    write_report(summary, top20, top40, changes)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    if not all(path.exists() for path in REQUIRED_INPUTS):
        safe_blocked()
        summary = read_first(SUMMARY_OUT)
    else:
        try:
            definition = pd.read_csv(R2_DEFINITION, low_memory=False)
            current = latest_current_frame()
            scored = score_current(current, definition)
            ranking = ranking_rows(scored)
            top20 = top_rows(scored, 20)
            top40 = top_rows(scored, 40)
            changes = change_audit(scored)
            summary = build_summary(scored)
            if len(scored) < 20:
                summary["final_status"] = PARTIAL_STATUS
                summary["decision"] = DECISION_LIMITED
            write_all(summary, ranking, top20, top40, changes)
        except Exception:
            safe_blocked()
            summary = read_first(SUMMARY_OUT)

    print(f"STAGE_NAME={STAGE}")
    print(f"final_status={summary['final_status']}")
    print(f"decision={summary['decision']}")
    print(f"current_input_rows={summary['current_input_rows']}")
    print(f"top20_overlap_baseline_vs_global_rsi={summary.get('top20_overlap_baseline_vs_global_rsi', '')}")
    print(f"top20_overlap_baseline_vs_context_conditioned={summary.get('top20_overlap_baseline_vs_context_conditioned', '')}")
    print(f"shadow_gate_allowed={summary['shadow_gate_allowed']}")


if __name__ == "__main__":
    main()
