#!/usr/bin/env python
"""V21.026 market regime source contract repair.

Research-only source contract repair for point-in-time market regime labels.
No official score, rank, recommendation, trade, weight, market-regime, or
shadow-policy files are mutated.
"""

from __future__ import annotations

import csv
import math
import re
from bisect import bisect_right
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean


STAGE_NAME = "V21_026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"
OBS_SELECTION = OUT_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv"

V21_024_INPUTS = [
    OUT_DIR / "V21_024_V21_022_DECISION_INGEST_AUDIT.csv",
    OUT_DIR / "V21_024_REGIME_CONTEXT_SOURCE_CONTRACT_AUDIT.csv",
    OUT_DIR / "V21_024_REGIME_LABEL_ADEQUACY_CONFLICT_AUDIT.csv",
    OUT_DIR / "V21_024_TRUE_CONTEXT_ONLY_LOGIC_REPAIR_AUDIT.csv",
    OUT_DIR / "V21_024_REGIME_SPECIFIC_SCORING_CONTEXT_TEST.csv",
    OUT_DIR / "V21_024_REGIME_SPECIFIC_RISK_GATE_INTERACTION_TEST.csv",
    OUT_DIR / "V21_024_REGIME_CONTEXT_STATISTICAL_CONFIRMATION.csv",
    OUT_DIR / "V21_024_REGIME_TRANSITION_CONFLICT_EXCLUSION_TEST.csv",
    OUT_DIR / "V21_024_CONTEXT_LOGIC_REPAIR_DECISION.csv",
    OUT_DIR / "V21_024_MARKET_REGIME_CONTEXT_LOGIC_REPAIR_SUMMARY.csv",
    READ_CENTER_DIR / "V21_024_MARKET_REGIME_CONTEXT_LOGIC_REPAIR_REPORT.md",
]

INGEST = OUT_DIR / "V21_026_V21_024_DECISION_INGEST_AUDIT.csv"
FAILURE = OUT_DIR / "V21_026_EXISTING_REGIME_LABEL_FAILURE_AUDIT.csv"
INVENTORY = OUT_DIR / "V21_026_MARKET_REGIME_SOURCE_INVENTORY.csv"
CONTRACT = OUT_DIR / "V21_026_PROPOSED_REGIME_LABEL_CONTRACT.csv"
DERIVED = OUT_DIR / "V21_026_DERIVED_RESEARCH_ONLY_REGIME_LABELS.csv"
PIT = OUT_DIR / "V21_026_PIT_VALIDATION_AUDIT.csv"
COVERAGE = OUT_DIR / "V21_026_LABEL_COVERAGE_IMPROVEMENT_AUDIT.csv"
GAPS = OUT_DIR / "V21_026_SOURCE_CONTRACT_GAP_TABLE.csv"
DECISION = OUT_DIR / "V21_026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR_DECISION.csv"
SUMMARY = OUT_DIR / "V21_026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR_SUMMARY.csv"
REPORT = READ_CENTER_DIR / "V21_026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR_REPORT.md"

PRICE_SOURCES = {
    "SPY": ROOT / "state" / "v18" / "price_cache" / "SPY.csv",
    "QQQ": ROOT / "state" / "v18" / "price_cache" / "QQQ.csv",
    "SOXX": ROOT / "state" / "v18" / "price_cache" / "SOXX.csv",
    "SMH": ROOT / "state" / "v18" / "price_cache" / "SMH.csv",
    "XLK": ROOT / "state" / "v18" / "price_cache" / "XLK.csv",
    "IGV": ROOT / "state" / "v18" / "price_cache" / "IGV.csv",
    "VIX": ROOT / "state" / "v18" / "price_cache" / "VIX.csv",
}


def norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def fmt(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.10f}"
    return value


def fnum(value: object) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def fint(value: object) -> int | None:
    parsed = fnum(value)
    return int(parsed) if parsed is not None else None


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def yn(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def field(row: dict[str, str], candidates: list[str]) -> str:
    by_norm = {norm(key): key for key in row}
    for candidate in candidates:
        if candidate in by_norm:
            return row.get(by_norm[candidate], "")
    return ""


def family_score(row: dict[str, str], family: str) -> float | None:
    low = family.lower()
    for candidate in [f"normalized_{low}_score", f"{low}_score"]:
        parsed = fnum(row.get(candidate) if candidate in row else field(row, [candidate]))
        if parsed is not None:
            return parsed
    return None


def original_regime(row: dict[str, str]) -> str:
    score = family_score(row, "MARKET_REGIME")
    if score is None:
        return "missing"
    if score >= 0.55:
        return "risk_on"
    if score <= 0.45:
        return "risk_off"
    return "neutral"


def load_primary_rows() -> list[dict[str, str]]:
    selection = [row for row in read_csv(OBS_SELECTION) if row.get("selection_status") == "USABLE_PRIMARY" and row.get("maturity_status") == "MATURED"]
    wanted: dict[str, set[int]] = defaultdict(set)
    selected: dict[tuple[str, int], dict[str, str]] = {}
    for row in selection:
        source, number = row.get("source_artifact", ""), fint(row.get("row_number"))
        if source and number is not None:
            wanted[source].add(number)
            selected[(source, number)] = row
    output = []
    for source, numbers in sorted(wanted.items()):
        path = ROOT / source.replace("\\", "/")
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for idx, row in enumerate(csv.DictReader(handle), start=1):
                if idx not in numbers:
                    continue
                sel = selected[(source, idx)]
                merged = dict(row)
                merged["_id"] = f"{source}:{idx}"
                merged["_ticker"] = sel.get("ticker") or field(row, ["ticker"])
                merged["_as_of_date"] = sel.get("as_of_date") or field(row, ["as_of_date"])
                merged["_available_forward_windows"] = sel.get("available_forward_windows", "")
                merged["_original_regime"] = original_regime(merged)
                output.append(merged)
    return output


def load_price(path: Path) -> list[dict[str, object]]:
    rows = []
    for row in read_csv(path):
        date = row.get("date") or row.get("Date")
        close = fnum(row.get("close") or row.get("adj_close") or row.get("Close") or row.get("Adj Close"))
        if date and close is not None:
            rows.append({"date": date[:10], "close": close, "source": row.get("source", ""), "source_file": row.get("source_file", "")})
    rows.sort(key=lambda item: str(item["date"]))
    return rows


def price_asof(prices: list[dict[str, object]], as_of_date: str, min_history: int = 50) -> dict[str, object] | None:
    dates = [str(row["date"]) for row in prices]
    idx = bisect_right(dates, as_of_date) - 1
    if idx < min_history - 1:
        return None
    window20 = prices[idx - 19: idx + 1]
    window50 = prices[idx - 49: idx + 1]
    return {
        "source_date": prices[idx]["date"],
        "close": prices[idx]["close"],
        "ma20": mean(float(row["close"]) for row in window20),
        "ma50": mean(float(row["close"]) for row in window50),
    }


def trend_label(prefix: str, pinfo: dict[str, object] | None) -> tuple[str, str]:
    if not pinfo:
        return f"{prefix}_missing", "MISSING_PRICE_HISTORY"
    close, ma20, ma50 = float(pinfo["close"]), float(pinfo["ma20"]), float(pinfo["ma50"])
    if close > ma50 and ma20 > ma50:
        return f"{prefix}_uptrend", "HIGH_CONFIDENCE"
    if close < ma50 and ma20 < ma50:
        return f"{prefix}_downtrend", "HIGH_CONFIDENCE"
    return f"{prefix}_neutral", "MEDIUM_CONFIDENCE"


def sector_label(price_infos: list[dict[str, object] | None]) -> tuple[str, str]:
    usable = [info for info in price_infos if info]
    if not usable:
        return "sector_missing", "MISSING_PRICE_HISTORY"
    up = sum(1 for info in usable if float(info["close"]) > float(info["ma50"]) and float(info["ma20"]) > float(info["ma50"]))
    down = sum(1 for info in usable if float(info["close"]) < float(info["ma50"]) and float(info["ma20"]) < float(info["ma50"]))
    if up >= max(2, math.ceil(len(usable) * 0.6)):
        return "sector_uptrend", "MEDIUM_CONFIDENCE"
    if down >= max(2, math.ceil(len(usable) * 0.6)):
        return "sector_downtrend", "MEDIUM_CONFIDENCE"
    return "sector_neutral", "LOW_CONFIDENCE"


def source_inventory() -> list[dict[str, object]]:
    rows = []
    extra = {
        "benchmark_context": ROOT / "outputs" / "v20" / "consolidation" / "V20_48_REFRESHED_BENCHMARK_CONTEXT_VIEW.csv",
        "macro_event_dates": ROOT / "data" / "macro_event_calendar.csv",
        "fomc_dates": ROOT / "data" / "fomc_dates.csv",
        "cpi_dates": ROOT / "data" / "cpi_dates.csv",
        "nfp_dates": ROOT / "data" / "nfp_dates.csv",
        "earnings_season_proxy": ROOT / "data" / "earnings_season_calendar.csv",
        "existing_market_regime_file": ROOT / "outputs" / "v21" / "factor_backtest" / "V21_008_REGIME_LABEL_INVENTORY.csv",
    }
    for name, path in {**{f"{ticker}_prices": path for ticker, path in PRICE_SOURCES.items()}, **extra}.items():
        data = read_csv(path)
        dates = []
        for row in data:
            d = row.get("date") or row.get("as_of_date") or row.get("refreshed_price_date")
            if d:
                dates.append(d[:10])
        header = list(data[0].keys()) if data else []
        required = "date|close" if name.endswith("_prices") else "date_or_as_of_date"
        missing = []
        if name.endswith("_prices"):
            if not any(norm(col) == "date" for col in header):
                missing.append("date")
            if not any(norm(col) in {"close", "adj_close"} for col in header):
                missing.append("close")
        rows.append({
            "source_name": name,
            "file_path": path.relative_to(ROOT).as_posix(),
            "exists_non_empty": yn(path.exists() and path.stat().st_size > 0),
            "row_count": len(data),
            "date_coverage_start": min(dates) if dates else "",
            "date_coverage_end": max(dates) if dates else "",
            "freshness": "AVAILABLE_LOCAL_SOURCE" if data else "MISSING_SOURCE",
            "required_fields": required,
            "missing_fields": "|".join(missing),
            "pit_eligibility": "ELIGIBLE_IF_SOURCE_DATE_LTE_AS_OF_DATE" if data and not missing else "NOT_ELIGIBLE_SOURCE_MISSING_OR_FIELDS_MISSING",
            "repair_usability": "USABLE_FOR_RESEARCH_DERIVATION" if data and not missing else "REQUIRES_DATA_PRODUCER",
            "research_only": "TRUE",
        })
    return rows


def contract_rows() -> list[dict[str, object]]:
    specs = [
        ("risk_on", "broad", "market_regime_score >= 0.55 or repaired broad source says risk_on", "none", "candidate source table", "missing if no market_regime score"),
        ("risk_off", "broad", "market_regime_score <= 0.45 or repaired broad source says risk_off", "none", "candidate source table", "missing if no market_regime score"),
        ("neutral", "broad", "0.45 < market_regime_score < 0.55 or repaired broad source says neutral", "none", "candidate source table", "missing if no market_regime score"),
        ("high_vix", "volatility", "VIX > rolling 80th percentile or fixed threshold where source exists", "252 trading days", "VIX daily close", "missing; do not fabricate without VIX"),
        ("low_vix", "volatility", "VIX < rolling 20th percentile or fixed threshold where source exists", "252 trading days", "VIX daily close", "missing; do not fabricate without VIX"),
        ("normal_vix", "volatility", "not high_vix and not low_vix where VIX source exists", "252 trading days", "VIX daily close", "missing; do not fabricate without VIX"),
        ("QQQ_uptrend", "index_trend", "QQQ close > MA50 and MA20 > MA50", "20/50 trading days", "QQQ daily close", "missing if insufficient price history"),
        ("QQQ_downtrend", "index_trend", "QQQ close < MA50 and MA20 < MA50", "20/50 trading days", "QQQ daily close", "missing if insufficient price history"),
        ("QQQ_neutral", "index_trend", "neither QQQ_uptrend nor QQQ_downtrend", "20/50 trading days", "QQQ daily close", "missing if insufficient price history"),
        ("SPY_uptrend", "index_trend", "SPY close > MA50 and MA20 > MA50", "20/50 trading days", "SPY daily close", "missing if insufficient price history"),
        ("SPY_downtrend", "index_trend", "SPY close < MA50 and MA20 < MA50", "20/50 trading days", "SPY daily close", "missing if insufficient price history"),
        ("SPY_neutral", "index_trend", "neither SPY_uptrend nor SPY_downtrend", "20/50 trading days", "SPY daily close", "missing if insufficient price history"),
        ("sector_uptrend", "sector_trend", ">=60% of available sector/theme ETFs are uptrend", "20/50 trading days", "SOXX/SMH/XLK/IGV daily close", "missing if no sector ETF source"),
        ("sector_downtrend", "sector_trend", ">=60% of available sector/theme ETFs are downtrend", "20/50 trading days", "SOXX/SMH/XLK/IGV daily close", "missing if no sector ETF source"),
        ("sector_neutral", "sector_trend", "neither sector_uptrend nor sector_downtrend", "20/50 trading days", "SOXX/SMH/XLK/IGV daily close", "missing if no sector ETF source"),
        ("AI_theme_uptrend", "theme_trend", "theme ETF/proxy close > MA50 and MA20 > MA50 if source exists", "20/50 trading days", "AI theme proxy", "missing; do not fabricate without source"),
        ("semiconductor_uptrend", "theme_trend", "SMH or SOXX close > MA50 and MA20 > MA50", "20/50 trading days", "SMH/SOXX daily close", "missing if insufficient price history"),
        ("FOMC_window", "event_window", "+/- 1 trading day around known FOMC date", "event calendar", "FOMC calendar", "missing; do not fabricate without calendar"),
        ("CPI_window", "event_window", "+/- 1 trading day around known CPI date", "event calendar", "CPI calendar", "missing; do not fabricate without calendar"),
        ("NFP_window", "event_window", "+/- 1 trading day around known NFP date", "event calendar", "NFP calendar", "missing; do not fabricate without calendar"),
        ("earnings_season_window", "event_window", "known earnings season calendar or approved deterministic proxy", "calendar", "earnings calendar", "missing; do not fabricate without calendar"),
        ("regime_transition_risk", "transition", "any broad/index/sector label changed within prior 5 trading days", "5 trading days", "derived labels", "missing if no base labels"),
        ("regime_conflict_flag", "transition", "risk_on conflicts with SPY/QQQ downtrend or high_vix; risk_off conflicts with SPY/QQQ uptrend or low_vix", "same as labels", "derived labels", "missing if conflict inputs missing"),
        ("unstable_regime_window", "transition", "transition_risk or conflict_flag true", "5 trading days", "derived labels", "missing if no transition/conflict inputs"),
    ]
    out = []
    for label, group, formula, lookback, source, missing_rule in specs:
        out.append({
            "label_name": label,
            "label_group": group,
            "formula": formula,
            "lookback_window": lookback,
            "input_source": source,
            "as_of_date_handling": "use latest source_date <= as_of_date",
            "effective_date_handling": "effective on as_of_date after source_date availability",
            "freshness_rule": "source_date must be <= as_of_date and latest available local source",
            "pit_eligibility_rule": "rolling calculations use only rows with source_date <= as_of_date",
            "missing_data_rule": missing_rule,
            "conflict_handling_rule": "emit conflict flag; never override source label silently",
            "research_only": "TRUE",
        })
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    missing = [path.relative_to(ROOT).as_posix() for path in V21_024_INPUTS if not path.exists() or path.stat().st_size == 0]
    decision_024 = first(read_csv(OUT_DIR / "V21_024_CONTEXT_LOGIC_REPAIR_DECISION.csv"))
    summary_024 = first(read_csv(OUT_DIR / "V21_024_MARKET_REGIME_CONTEXT_LOGIC_REPAIR_SUMMARY.csv"))
    rows = load_primary_rows()
    inventory_rows = source_inventory()
    prices = {ticker: load_price(path) for ticker, path in PRICE_SOURCES.items()}

    ingest_rows = [
        {"audit_item": "required_v21_024_artifacts_present", "audit_passed": yn(not missing), "observed_value": "|".join(missing) if missing else "ALL_PRESENT", "required_value": "TRUE", "research_only": "TRUE"},
        {"audit_item": "v21_024_decision_ingested", "audit_passed": yn(decision_024.get("context_logic_repair_decision") == "MARKET_REGIME_CONTEXT_LOGIC_PARTIAL_LABELS_LIMITED"), "observed_value": decision_024.get("context_logic_repair_decision", ""), "required_value": "MARKET_REGIME_CONTEXT_LOGIC_PARTIAL_LABELS_LIMITED", "research_only": "TRUE"},
        {"audit_item": "candidate_research_path_label_source_repair", "audit_passed": yn(decision_024.get("candidate_research_path_decision") == "market regime label/source repair"), "observed_value": decision_024.get("candidate_research_path_decision", ""), "required_value": "market regime label/source repair", "research_only": "TRUE"},
        {"audit_item": "recommended_next_stage_v21_026", "audit_passed": yn(decision_024.get("recommended_next_stage") == "V21.026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR"), "observed_value": decision_024.get("recommended_next_stage", ""), "required_value": "V21.026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR", "research_only": "TRUE"},
        {"audit_item": "official_use_false", "audit_passed": yn(summary_024.get("official_use_allowed") == "FALSE"), "observed_value": summary_024.get("official_use_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_ranking_readiness_false", "audit_passed": yn(summary_024.get("official_ranking_readiness_allowed") == "FALSE"), "observed_value": summary_024.get("official_ranking_readiness_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_weight_update_readiness_false", "audit_passed": yn(summary_024.get("official_weight_update_readiness_allowed") == "FALSE"), "observed_value": summary_024.get("official_weight_update_readiness_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_weight_update_blocked", "audit_passed": yn(summary_024.get("official_weight_update_blocked") == "TRUE"), "observed_value": summary_024.get("official_weight_update_blocked", ""), "required_value": "TRUE", "research_only": "TRUE"},
        {"audit_item": "data_trust_zero_alpha_ranking_contribution", "audit_passed": yn(summary_024.get("data_trust_alpha_contribution") == "0" and summary_024.get("data_trust_ranking_weight") == "0"), "observed_value": f"{summary_024.get('data_trust_ranking_weight','')}|{summary_024.get('data_trust_alpha_contribution','')}", "required_value": "0|0", "research_only": "TRUE"},
        {"audit_item": "risk_additive_alpha_contribution_zero", "audit_passed": yn(summary_024.get("risk_additive_alpha_contribution") == "0"), "observed_value": summary_024.get("risk_additive_alpha_contribution", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "market_regime_additive_alpha_contribution_zero", "audit_passed": yn(summary_024.get("market_regime_additive_alpha_contribution") == "0"), "observed_value": summary_024.get("market_regime_additive_alpha_contribution", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "official_ranking_mutation_count_zero", "audit_passed": yn(summary_024.get("official_ranking_mutation_count") == "0"), "observed_value": summary_024.get("official_ranking_mutation_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "official_factor_weight_mutation_count_zero", "audit_passed": yn(summary_024.get("official_factor_weight_mutation_count") == "0"), "observed_value": summary_024.get("official_factor_weight_mutation_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "official_recommendation_count_zero", "audit_passed": yn(summary_024.get("official_recommendation_count") == "0"), "observed_value": summary_024.get("official_recommendation_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "trade_action_count_zero", "audit_passed": yn(summary_024.get("trade_action_count") == "0"), "observed_value": summary_024.get("trade_action_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "shadow_activation_false", "audit_passed": yn(summary_024.get("shadow_activation") == "FALSE"), "observed_value": summary_024.get("shadow_activation", ""), "required_value": "FALSE", "research_only": "TRUE"},
    ]

    failure_specs = [
        ("risk_on_risk_off_neutral_only", "Only broad score-derived labels exist", "approved PIT market regime source", True, False, True, False),
        ("high_vix_missing", "No local VIX source file", "VIX daily close producer", False, True, False, True),
        ("low_vix_missing", "No local VIX source file", "VIX daily close producer", False, True, False, True),
        ("QQQ_trend_missing", "Prior stages did not materialize QQQ trend labels", "local QQQ price cache", True, False, True, False),
        ("SPY_trend_missing", "Prior stages did not materialize SPY trend labels", "local SPY price cache", True, False, True, False),
        ("sector_trend_missing", "Prior stages did not materialize sector/theme trend labels", "SOXX/SMH/XLK/IGV price caches", True, False, True, False),
        ("event_labels_missing", "No macro event calendar artifacts", "FOMC/CPI/NFP/earnings calendars", False, True, False, True),
        ("transition_risk_count_too_high", "Prior context repair used coarse ticker transition heuristic", "derived label transition history", True, False, True, False),
        ("regime_effective_date_ambiguity", "Existing labels lack explicit effective_date", "source contract metadata", True, False, True, False),
        ("regime_source_ambiguity", "Existing labels do not name formula/source per label", "source contract metadata", True, False, True, False),
        ("regime_freshness_ambiguity", "Existing labels lack freshness rule", "source contract metadata", True, False, True, False),
        ("pit_eligibility_ambiguity", "Existing labels lack source_date <= as_of_date proof", "PIT validation audit", True, False, True, False),
    ]
    failure_rows = [{
        "failure_item": item,
        "root_cause": root,
        "required_source": source,
        "derivable_from_existing_local_data": yn(derivable),
        "external_or_manual_source_contract_needed": yn(external),
        "can_generate_research_only": yn(can_generate),
        "must_remain_missing": yn(must_missing),
        "research_only": "TRUE",
    } for item, root, source, derivable, external, can_generate, must_missing in failure_specs]

    contract = contract_rows()
    derived_rows = []
    as_of_dates = sorted({row["_as_of_date"] for row in rows if row.get("_as_of_date")})
    by_date_original = defaultdict(list)
    for row in rows:
        by_date_original[row["_as_of_date"]].append(row["_original_regime"])
    previous_labels: dict[str, str] = {}
    for as_of in as_of_dates:
        original_counts = defaultdict(int)
        for label in by_date_original[as_of]:
            original_counts[label] += 1
        original = max(original_counts, key=original_counts.get) if original_counts else "missing"
        qqq = price_asof(prices["QQQ"], as_of)
        spy = price_asof(prices["SPY"], as_of)
        sector_infos = [price_asof(prices[ticker], as_of) for ticker in ["SOXX", "SMH", "XLK", "IGV"]]
        qqq_label, qqq_conf = trend_label("QQQ", qqq)
        spy_label, spy_conf = trend_label("SPY", spy)
        sector_trend, sector_conf = sector_label(sector_infos)
        smh_label, _ = trend_label("semiconductor", price_asof(prices["SMH"], as_of) or price_asof(prices["SOXX"], as_of))
        conflict = (original == "risk_on" and (qqq_label == "QQQ_downtrend" or spy_label == "SPY_downtrend")) or (original == "risk_off" and (qqq_label == "QQQ_uptrend" or spy_label == "SPY_uptrend"))
        transition = False
        for key, label in [("original", original), ("qqq", qqq_label), ("spy", spy_label), ("sector", sector_trend)]:
            prev = previous_labels.get(key)
            if prev is not None and prev != label:
                transition = True
            previous_labels[key] = label
        unstable = transition or conflict
        label_infos = [
            (original, "candidate_market_regime_score", "market_regime_score threshold", as_of, "HIGH_CONFIDENCE" if original != "missing" else "MISSING_SOURCE"),
            (qqq_label, "state/v18/price_cache/QQQ.csv", "QQQ close >/< MA50 and MA20 >/< MA50", qqq["source_date"] if qqq else "", qqq_conf),
            (spy_label, "state/v18/price_cache/SPY.csv", "SPY close >/< MA50 and MA20 >/< MA50", spy["source_date"] if spy else "", spy_conf),
            (sector_trend, "state/v18/price_cache/SOXX|SMH|XLK|IGV.csv", ">=60% sector ETF trend vote", max([str(info["source_date"]) for info in sector_infos if info], default=""), sector_conf),
            (smh_label if smh_label != "semiconductor_missing" else "semiconductor_missing", "state/v18/price_cache/SMH|SOXX.csv", "semiconductor proxy close > MA50 and MA20 > MA50", (price_asof(prices["SMH"], as_of) or price_asof(prices["SOXX"], as_of) or {}).get("source_date", ""), "MEDIUM_CONFIDENCE"),
            ("regime_transition_risk" if transition else "no_regime_transition_risk", "V21_026_DERIVED_RESEARCH_ONLY_REGIME_LABELS", "label changed versus prior as_of_date", as_of, "MEDIUM_CONFIDENCE"),
            ("regime_conflict_flag" if conflict else "no_regime_conflict_flag", "V21_026_DERIVED_RESEARCH_ONLY_REGIME_LABELS", "broad label conflicts with SPY/QQQ trend", as_of, "MEDIUM_CONFIDENCE"),
            ("unstable_regime_window" if unstable else "stable_regime_window", "V21_026_DERIVED_RESEARCH_ONLY_REGIME_LABELS", "transition or conflict flag true", as_of, "MEDIUM_CONFIDENCE"),
        ]
        for label, source, formula, source_date, confidence in label_infos:
            if label.endswith("_missing"):
                continue
            derived_rows.append({
                "as_of_date": as_of,
                "effective_date": as_of,
                "label_name": label,
                "label_scope": "DATE_CONTEXT",
                "label_status": "DERIVED_RESEARCH_ONLY",
                "source": source,
                "formula": formula,
                "source_date": source_date,
                "freshness": "SOURCE_DATE_LTE_AS_OF_DATE" if source_date and source_date <= as_of else "UNCERTAIN_SOURCE_DATE",
                "point_in_time_eligible": yn(bool(source_date) and source_date <= as_of),
                "label_confidence": confidence,
                "original_label_preserved": original,
                "transition_flag": yn(transition),
                "conflict_flag": yn(conflict),
                "research_only": "TRUE",
            })

    pit_rows = []
    for row in derived_rows:
        ok = bool(row["source_date"]) and str(row["source_date"]) <= str(row["as_of_date"])
        pit_rows.append({
            "as_of_date": row["as_of_date"],
            "label_name": row["label_name"],
            "source_date": row["source_date"],
            "source_date_lte_as_of_date": yn(ok),
            "future_data_used": yn(not ok),
            "rolling_calculation_historical_only": yn(ok),
            "event_calendar_source_known": "NOT_APPLICABLE",
            "uncertain_pit_fields": "" if ok else "source_date",
            "pit_validation_status": "PASS" if ok else "FAIL",
            "research_only": "TRUE",
        })

    before = read_csv(OUT_DIR / "V21_024_REGIME_LABEL_ADEQUACY_CONFLICT_AUDIT.csv")
    before_by_label = {row.get("regime_label", ""): row for row in before}
    after_by_label = defaultdict(set)
    for row in derived_rows:
        after_by_label[row["label_name"]].add(row["as_of_date"])
    coverage_rows = []
    for label in sorted(set(before_by_label) | set(after_by_label)):
        before_obs = fint(before_by_label.get(label, {}).get("observation_count")) or 0
        before_dates = fint(before_by_label.get(label, {}).get("distinct_as_of_date_count")) or 0
        after_dates = len(after_by_label.get(label, set()))
        after_obs = sum(1 for row in rows if row.get("_as_of_date") in after_by_label.get(label, set()))
        coverage_rows.append({
            "label_name": label,
            "before_observation_count": before_obs,
            "after_observation_count": after_obs,
            "before_distinct_as_of_date_count": before_dates,
            "after_distinct_as_of_date_count": after_dates,
            "distinct_ticker_count": len({row["_ticker"] for row in rows if row.get("_as_of_date") in after_by_label.get(label, set())}),
            "label_coverage_forward_windows": "5d|10d|20d" if after_obs else before_by_label.get(label, {}).get("available_forward_return_windows", ""),
            "transition_risk_count": sum(1 for row in derived_rows if row["label_name"] == label and row["transition_flag"] == "TRUE"),
            "conflict_count": sum(1 for row in derived_rows if row["label_name"] == label and row["conflict_flag"] == "TRUE"),
            "missing_count": max(0, len(as_of_dates) - after_dates),
            "derived_count": after_dates,
            "coverage_improved": yn(after_dates > before_dates),
            "research_only": "TRUE",
        })

    gap_specs = [
        ("VIX daily close", "high_vix|low_vix|normal_vix", "HIGH", "volatility context unavailable", "implement VIX price producer", "market_regime_data_producer", "V21.028_MARKET_REGIME_DATA_PRODUCER_IMPLEMENTATION", False, True),
        ("FOMC calendar", "FOMC_window", "MEDIUM", "FOMC event context unavailable", "implement event calendar producer", "market_regime_data_producer", "V21.028_MARKET_REGIME_DATA_PRODUCER_IMPLEMENTATION", False, True),
        ("CPI calendar", "CPI_window", "MEDIUM", "CPI event context unavailable", "implement event calendar producer", "market_regime_data_producer", "V21.028_MARKET_REGIME_DATA_PRODUCER_IMPLEMENTATION", False, True),
        ("NFP calendar", "NFP_window", "MEDIUM", "NFP event context unavailable", "implement event calendar producer", "market_regime_data_producer", "V21.028_MARKET_REGIME_DATA_PRODUCER_IMPLEMENTATION", False, True),
        ("earnings season calendar", "earnings_season_window", "LOW", "earnings-season context unavailable", "implement earnings calendar or approved proxy", "market_regime_data_producer", "V21.028_MARKET_REGIME_DATA_PRODUCER_IMPLEMENTATION", False, True),
        ("explicit broad regime source metadata", "risk_on|risk_off|neutral", "MEDIUM", "broad source/effective date ambiguous", "materialize source contract metadata", "V21_026_research_contract", "V21.027_MARKET_REGIME_CONTEXT_RETEST_WITH_REPAIRED_LABELS", True, False),
    ]
    gap_rows = [{
        "missing_source": source,
        "affected_label": labels,
        "severity": severity,
        "impact_on_backtest": impact,
        "repair_method": method,
        "required_producer": producer,
        "required_next_stage": next_stage,
        "can_repair_now": yn(can_now),
        "cannot_fabricate": yn(cannot_fabricate),
        "research_only": "TRUE",
    } for source, labels, severity, impact, method, producer, next_stage, can_now, cannot_fabricate in gap_specs]

    derived_dates = {row["as_of_date"] for row in derived_rows}
    improved_labels = sum(1 for row in coverage_rows if row["coverage_improved"] == "TRUE")
    pit_fail = any(row["pit_validation_status"] != "PASS" for row in pit_rows)
    missing_producers = any(row["can_repair_now"] == "FALSE" and row["severity"] == "HIGH" for row in gap_rows)
    if missing or any(row["audit_passed"] == "FALSE" for row in ingest_rows[:4]):
        repair_decision = "MARKET_REGIME_SOURCE_CONTRACT_INCONCLUSIVE_REQUIRED_FILES_MISSING"
        next_stage = "V21.028_MARKET_REGIME_DATA_PRODUCER_IMPLEMENTATION"
    elif not derived_rows or pit_fail:
        repair_decision = "MARKET_REGIME_SOURCE_CONTRACT_NOT_REPAIRABLE_WITH_CURRENT_DATA"
        next_stage = "V21.028_MARKET_REGIME_DATA_PRODUCER_IMPLEMENTATION"
    elif missing_producers and improved_labels > 0 and len(derived_dates) >= 20:
        repair_decision = "MARKET_REGIME_SOURCE_CONTRACT_PARTIAL_REPAIR_READY_FOR_CONTEXT_RETEST"
        next_stage = "V21.027_MARKET_REGIME_CONTEXT_RETEST_WITH_REPAIRED_LABELS"
    elif missing_producers:
        repair_decision = "MARKET_REGIME_SOURCE_CONTRACT_REQUIRES_NEW_DATA_PRODUCERS"
        next_stage = "V21.028_MARKET_REGIME_DATA_PRODUCER_IMPLEMENTATION"
    else:
        repair_decision = "MARKET_REGIME_SOURCE_CONTRACT_REPAIRED_RESEARCH_ONLY"
        next_stage = "V21.027_MARKET_REGIME_CONTEXT_RETEST_WITH_REPAIRED_LABELS"
    prefix = "PASS" if repair_decision == "MARKET_REGIME_SOURCE_CONTRACT_REPAIRED_RESEARCH_ONLY" else "PARTIAL_PASS"
    final_status = f"{prefix}_V21_026_{repair_decision}"
    decision_rows = [{
        "source_contract_repair_decision": repair_decision,
        "final_status": final_status,
        "official_use_allowed": "FALSE",
        "official_ranking_readiness_allowed": "FALSE",
        "official_weight_update_readiness_allowed": "FALSE",
        "official_weight_update_blocked": "TRUE",
        "recommended_next_stage": next_stage,
        "selected_recommended_next_stage": "TRUE",
        "research_only": "TRUE",
    }]
    summary = {
        "stage_name": STAGE_NAME,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "research_only": "TRUE",
        "final_status": final_status,
        "source_contract_repair_decision": repair_decision,
        "v21_024_context_logic_repair_decision": decision_024.get("context_logic_repair_decision", ""),
        "v21_024_candidate_research_path_decision": decision_024.get("candidate_research_path_decision", ""),
        "v21_024_recommended_next_stage": decision_024.get("recommended_next_stage", ""),
        "derived_research_only_label_count": len(derived_rows),
        "derived_as_of_date_count": len(derived_dates),
        "coverage_improved_label_count": improved_labels,
        "pit_validation_fail_count": sum(1 for row in pit_rows if row["pit_validation_status"] != "PASS"),
        "missing_high_severity_source_count": sum(1 for row in gap_rows if row["severity"] == "HIGH" and row["cannot_fabricate"] == "TRUE"),
        "official_use_allowed": "FALSE",
        "official_ranking_readiness_allowed": "FALSE",
        "official_weight_update_readiness_allowed": "FALSE",
        "official_weight_update_blocked": "TRUE",
        "recommended_next_stage": next_stage,
        "prototype_output_scope": "V21_026_RESEARCH_ONLY",
        "data_trust_ranking_weight": "0",
        "data_trust_alpha_contribution": "0",
        "risk_additive_alpha_contribution": "0",
        "market_regime_additive_alpha_contribution": "0",
        "official_ranking_mutation_count": "0",
        "official_factor_weight_mutation_count": "0",
        "official_recommendation_count": "0",
        "trade_action_count": "0",
        "shadow_activation": "FALSE",
    }

    write_csv(INGEST, ingest_rows, ["audit_item", "audit_passed", "observed_value", "required_value", "research_only"])
    write_csv(FAILURE, failure_rows, ["failure_item", "root_cause", "required_source", "derivable_from_existing_local_data", "external_or_manual_source_contract_needed", "can_generate_research_only", "must_remain_missing", "research_only"])
    write_csv(INVENTORY, inventory_rows, ["source_name", "file_path", "exists_non_empty", "row_count", "date_coverage_start", "date_coverage_end", "freshness", "required_fields", "missing_fields", "pit_eligibility", "repair_usability", "research_only"])
    write_csv(CONTRACT, contract, ["label_name", "label_group", "formula", "lookback_window", "input_source", "as_of_date_handling", "effective_date_handling", "freshness_rule", "pit_eligibility_rule", "missing_data_rule", "conflict_handling_rule", "research_only"])
    write_csv(DERIVED, derived_rows, ["as_of_date", "effective_date", "label_name", "label_scope", "label_status", "source", "formula", "source_date", "freshness", "point_in_time_eligible", "label_confidence", "original_label_preserved", "transition_flag", "conflict_flag", "research_only"])
    write_csv(PIT, pit_rows, ["as_of_date", "label_name", "source_date", "source_date_lte_as_of_date", "future_data_used", "rolling_calculation_historical_only", "event_calendar_source_known", "uncertain_pit_fields", "pit_validation_status", "research_only"])
    write_csv(COVERAGE, coverage_rows, ["label_name", "before_observation_count", "after_observation_count", "before_distinct_as_of_date_count", "after_distinct_as_of_date_count", "distinct_ticker_count", "label_coverage_forward_windows", "transition_risk_count", "conflict_count", "missing_count", "derived_count", "coverage_improved", "research_only"])
    write_csv(GAPS, gap_rows, ["missing_source", "affected_label", "severity", "impact_on_backtest", "repair_method", "required_producer", "required_next_stage", "can_repair_now", "cannot_fabricate", "research_only"])
    write_csv(DECISION, decision_rows, ["source_contract_repair_decision", "final_status", "official_use_allowed", "official_ranking_readiness_allowed", "official_weight_update_readiness_allowed", "official_weight_update_blocked", "recommended_next_stage", "selected_recommended_next_stage", "research_only"])
    write_csv(SUMMARY, [summary], list(summary.keys()))

    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(f"""# V21.026 Market Regime Source Contract Repair Report

## Executive summary
This research-only stage defines, audits, and partially repairs the point-in-time market regime source contract after V21.024 found context logic limited by labels. Generated labels are V21_026 research-only outputs and are marked DERIVED_RESEARCH_ONLY.

## Final source contract repair decision
{repair_decision}

Final status: {final_status}

## V21.024 decision ingestion
V21.024 decision: {decision_024.get('context_logic_repair_decision', '')}. Candidate path: {decision_024.get('candidate_research_path_decision', '')}. Recommended next stage: {decision_024.get('recommended_next_stage', '')}.

## Existing regime label failure audit
See V21_026_EXISTING_REGIME_LABEL_FAILURE_AUDIT.csv. Missing VIX and event labels are not fabricated.

## Market regime source inventory
See V21_026_MARKET_REGIME_SOURCE_INVENTORY.csv.

## Proposed regime label contract
See V21_026_PROPOSED_REGIME_LABEL_CONTRACT.csv.

## Derived research-only regime labels
Generated derived label rows: {len(derived_rows)}. All generated labels are marked DERIVED_RESEARCH_ONLY and preserve the original broad label separately.

## Point-in-time validation
PIT validation fail count: {summary['pit_validation_fail_count']}. Every derived label must have source_date <= as_of_date.

## Coverage improvement audit
Coverage-improved labels: {improved_labels}. See V21_026_LABEL_COVERAGE_IMPROVEMENT_AUDIT.csv.

## Source contract gap table
See V21_026_SOURCE_CONTRACT_GAP_TABLE.csv. High-severity missing VIX source remains a producer gap.

## DATA_TRUST zero-alpha confirmation
DATA_TRUST ranking contribution is 0 and alpha contribution is 0. RISK and MARKET_REGIME additive alpha contribution are also 0.

## Explicit blocked actions
No official ranking mutation. No official factor weight mutation. No official recommendation. No trade action. No shadow activation. No official use. No official ranking readiness. No official weight update readiness. No production readiness. No real-book readiness.

## What this stage proves
It defines deterministic source contracts and derives only locally supported PIT research labels without fabricating missing VIX or event labels.

## What this stage still cannot prove
It cannot approve official scoring, official ranking, official weight updates, recommendations, trade actions, shadow activation, production use, or real-book use.

## Recommended next stage
{next_stage}
""", encoding="utf-8")

    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_status={final_status}")
    print(f"source_contract_repair_decision={repair_decision}")
    print(f"recommended_next_stage={next_stage}")
    print("official_use_allowed=FALSE")
    print("official_ranking_readiness_allowed=FALSE")
    print("official_weight_update_readiness_allowed=FALSE")
    print("official_weight_update_blocked=TRUE")
    print("data_trust_ranking_weight=0")
    print("data_trust_alpha_contribution=0")
    print("risk_additive_alpha_contribution=0")
    print("market_regime_additive_alpha_contribution=0")
    print("official_ranking_mutation_count=0")
    print("official_factor_weight_mutation_count=0")
    print("official_recommendation_count=0")
    print("trade_action_count=0")
    print("shadow_activation=FALSE")
    print("research_only=TRUE")


if __name__ == "__main__":
    main()
