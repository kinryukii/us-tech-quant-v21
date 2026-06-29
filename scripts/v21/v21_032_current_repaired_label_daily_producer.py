#!/usr/bin/env python
"""V21.032 current repaired label daily producer.

Research-only bridge from current daily candidate/factor snapshots to V21
repaired context labels. Does not mutate official rankings, weights,
recommendations, broker actions, market-regime files, or shadow policy.
"""

from __future__ import annotations

import csv
import math
from bisect import bisect_right
from datetime import datetime
from pathlib import Path
from statistics import mean


STAGE_NAME = "V21_032_CURRENT_REPAIRED_LABEL_DAILY_PRODUCER"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "shadow_observation"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"
PRICE_DIR = ROOT / "state" / "v18" / "price_cache"

SUMMARY = OUT_DIR / "V21_032_CURRENT_REPAIRED_LABEL_DAILY_PRODUCER_SUMMARY.csv"
LABELS = OUT_DIR / "V21_032_CURRENT_REPAIRED_LABELS.csv"
FIELD_AUDIT = OUT_DIR / "V21_032_LABEL_SOURCE_FIELD_AUDIT.csv"
FALLBACK_AUDIT = OUT_DIR / "V21_032_FALLBACK_REPAIR_AUDIT.csv"
REPORT = READ_CENTER_DIR / "V21_032_CURRENT_REPAIRED_LABEL_DAILY_PRODUCER_REPORT.md"

SOURCES = [
    ROOT / "outputs" / "v20" / "backtest_snapshots" / "V20_194_CURRENT_RUN_RECOMPUTABLE_FACTOR_SNAPSHOT.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R11_STRICT_EQUITY_SHADOW_RERANK_INPUT_MATRIX.csv",
    ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_RANKED_CANDIDATES.csv",
]


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
            writer.writerow({field: "" if row.get(field) is None else row.get(field, "") for field in fields})


def fnum(value: object) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def yn(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def load_price(ticker: str) -> list[tuple[str, float]]:
    rows = []
    for row in read_csv(PRICE_DIR / f"{ticker}.csv"):
        d = row.get("date") or row.get("Date")
        close = fnum(row.get("adj_close") or row.get("close") or row.get("Adj Close") or row.get("Close"))
        if d and close is not None:
            rows.append((d[:10], close))
    return sorted(rows)


def price_info(prices: list[tuple[str, float]], as_of: str) -> dict[str, object] | None:
    dates = [d for d, _ in prices]
    idx = bisect_right(dates, as_of) - 1
    if idx < 49:
        return None
    w20 = prices[idx - 19:idx + 1]
    w50 = prices[idx - 49:idx + 1]
    return {"source_date": prices[idx][0], "close": prices[idx][1], "ma20": mean(v for _, v in w20), "ma50": mean(v for _, v in w50)}


def trend(prefix: str, info: dict[str, object] | None) -> tuple[str | None, str]:
    if not info:
        return None, "MISSING_PRICE_HISTORY"
    close, ma20, ma50 = float(info["close"]), float(info["ma20"]), float(info["ma50"])
    if close > ma50 and ma20 > ma50:
        return f"{prefix}_uptrend", "price close > MA50 and MA20 > MA50"
    if close < ma50 and ma20 < ma50:
        return f"{prefix}_downtrend", "price close < MA50 and MA20 < MA50"
    return f"{prefix}_neutral", "price trend neutral versus MA50"


def source_dates(rows: list[dict[str, str]]) -> list[str]:
    out = []
    for row in rows:
        for key in ["as_of_date", "latest_price_date", "refreshed_price_date"]:
            if row.get(key):
                out.append(row[key][:10])
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    all_source_rows: dict[Path, list[dict[str, str]]] = {p: read_csv(p) for p in SOURCES}
    latest_dates = [d for rows in all_source_rows.values() for d in source_dates(rows)]
    latest_date = max(latest_dates) if latest_dates else ""
    primary = SOURCES[0]
    current_rows = [r for r in all_source_rows[primary] if r.get("as_of_date", "")[:10] == latest_date]
    if not current_rows:
        # Fallback to any source that has latest_date.
        for path, rows in all_source_rows.items():
            matching = [r for r in rows if (r.get("as_of_date") or r.get("latest_price_date") or "")[:10] == latest_date]
            if matching:
                primary, current_rows = path, matching
                break

    prev_labels = read_csv(ROOT / "outputs" / "v21" / "factor_backtest" / "V21_026_DERIVED_RESEARCH_ONLY_REGIME_LABELS.csv")
    previous_latest = max([r.get("as_of_date", "") for r in prev_labels] or [""])
    fallback_before = read_csv(OUT_DIR / "V21_030_FALLBACK_SNAPSHOT_LIMITATION_AUDIT.csv")
    fallback_row = fallback_before[0] if fallback_before else {}
    before_gap = (datetime.fromisoformat(latest_date) - datetime.fromisoformat(previous_latest)).days if latest_date and previous_latest else ""

    candidate_fields = {
        "market_regime_score": "broad risk_on/risk_off/neutral",
        "risk_score": "unstable/transition diagnostic",
        "technical_score": "candidate technical context audit",
        "ticker": "ticker identity",
        "as_of_date": "candidate date",
    }
    field_rows = []
    for path, rows in all_source_rows.items():
        headers = set(rows[0].keys()) if rows else set()
        for field, mapped in candidate_fields.items():
            exists = field in headers
            non_null = sum(1 for r in rows if r.get(field))
            usable = exists and non_null > 0 and field in {"market_regime_score", "risk_score", "ticker", "as_of_date"}
            field_rows.append({
                "source_artifact": path.relative_to(ROOT).as_posix(),
                "source_field": field,
                "field_exists": yn(exists),
                "non_null_count": non_null,
                "usable_for_label_derivation": yn(usable),
                "mapped_context_key": mapped if usable else "",
                "mapping_rule": "deterministic threshold or identity" if usable else "",
                "limitation": "" if usable else "not present or not safe for label derivation",
            })

    labels = []
    if current_rows:
        mvals = [fnum(r.get("market_regime_score")) for r in current_rows]
        mvals = [v for v in mvals if v is not None]
        rvals = [fnum(r.get("risk_score")) for r in current_rows]
        rvals = [v for v in rvals if v is not None]
        broad = "risk_on" if mvals and mean(mvals) >= 0.55 else "risk_off" if mvals and mean(mvals) <= 0.45 else "neutral" if mvals else None
        unstable = bool(rvals and mean(rvals) < 0.58)
        price_labels = []
        for ticker in ["QQQ", "SPY"]:
            lab, rule = trend(ticker, price_info(load_price(ticker), latest_date))
            if lab:
                price_labels.append((lab, f"state/v18/price_cache/{ticker}.csv", rule))
        sector_infos = [price_info(load_price(t), latest_date) for t in ["SOXX", "SMH", "XLK", "IGV"]]
        usable_sector = [i for i in sector_infos if i]
        if usable_sector:
            up = sum(1 for i in usable_sector if float(i["close"]) > float(i["ma50"]) and float(i["ma20"]) > float(i["ma50"]))
            down = sum(1 for i in usable_sector if float(i["close"]) < float(i["ma50"]) and float(i["ma20"]) < float(i["ma50"]))
            sector = "sector_uptrend" if up >= 2 else "sector_downtrend" if down >= 2 else "sector_neutral"
            price_labels.append((sector, "state/v18/price_cache/SOXX|SMH|XLK|IGV.csv", "sector ETF trend vote"))
        semi_lab, semi_rule = trend("semiconductor", price_info(load_price("SMH"), latest_date) or price_info(load_price("SOXX"), latest_date))
        if semi_lab:
            price_labels.append((semi_lab, "state/v18/price_cache/SMH|SOXX.csv", semi_rule))
        base_labels = []
        if broad:
            base_labels.append((broad, "market_regime_score", "mean market_regime_score threshold"))
        base_labels.extend(price_labels)
        base_labels.append(("regime_transition_risk" if unstable else "no_regime_transition_risk", "risk_score", "mean risk_score threshold"))
        base_labels.append(("unstable_regime_window" if unstable else "stable_regime_window", "risk_score", "risk-derived stability flag"))
        base_labels.append(("no_regime_conflict_flag", "derived current label set", "no safe conflict source beyond current labels"))
        for r in current_rows:
            ticker = r.get("ticker", "")
            for label, source, method in base_labels:
                lane = "UNSTABLE_CONTEXT_RISK_GATE_OVERLAY" if label in {"unstable_regime_window", "regime_transition_risk"} or label.endswith("downtrend") else "WITHIN_REGIME_ALPHA_ONLY_PRIMARY"
                labels.append({
                    "as_of_date": latest_date,
                    "ticker": ticker,
                    "context_key": label,
                    "context_label": label,
                    "lane_id": lane,
                    "source_candidate_date": r.get("as_of_date", latest_date)[:10],
                    "source_artifact": primary.relative_to(ROOT).as_posix(),
                    "label_derivation_method": method,
                    "repaired_label_status": "DERIVED_RESEARCH_ONLY_CURRENT_DAILY",
                    "research_only": "TRUE",
                })

    usable_fields = any(r["usable_for_label_derivation"] == "TRUE" for r in field_rows)
    produced_date = latest_date if labels else ""
    after_gap = 0 if produced_date == latest_date and produced_date else before_gap
    sufficient = bool(labels) and len({r["ticker"] for r in labels}) == len(current_rows) and {"QQQ_uptrend", "SPY_uptrend"} & {r["context_label"] for r in labels}
    fallback_after = not sufficient
    if not latest_date or not current_rows:
        final_status = "BLOCKED_V21_032_NO_CURRENT_DAILY_CANDIDATE_DATA"
        decision = "CURRENT_REPAIRED_LABEL_DAILY_PRODUCTION_BLOCKED_NO_CURRENT_DATA"
        next_stage = "V21_CURRENT_DAILY_CANDIDATE_SOURCE_REPAIR"
    elif not usable_fields or not labels:
        final_status = "BLOCKED_V21_032_NO_USABLE_LABEL_DERIVATION_FIELDS"
        decision = "CURRENT_REPAIRED_LABEL_DAILY_PRODUCTION_BLOCKED_NO_USABLE_FIELDS"
        next_stage = "V21_032_R1_LABEL_SOURCE_CONTRACT_REPAIR"
    elif fallback_after:
        final_status = "PARTIAL_PASS_V21_032_CURRENT_REPAIRED_LABELS_PRODUCED_WITH_LIMITED_COVERAGE"
        decision = "CURRENT_REPAIRED_LABELS_PRODUCED_LIMITED_COVERAGE"
        next_stage = "V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_REBUILDER"
    else:
        final_status = "PASS_V21_032_CURRENT_REPAIRED_LABELS_PRODUCED_FOR_LATEST_DAILY_DATE"
        decision = "CURRENT_REPAIRED_LABELS_READY_FOR_CURRENT_DAILY_SHADOW_OBSERVATION"
        next_stage = "V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_REBUILDER"

    fallback_audit = [{
        "fallback_as_of_date_before": fallback_row.get("fallback_as_of_date", previous_latest),
        "latest_available_current_daily_candidate_date": latest_date,
        "previous_repaired_label_latest_date": previous_latest,
        "produced_repaired_label_date": produced_date,
        "fallback_prevents_current_daily_observation_use_before": fallback_row.get("fallback_prevents_current_daily_observation_use", "TRUE"),
        "fallback_prevents_current_daily_observation_use_after": yn(fallback_after),
        "repair_status": "REPAIRED_FOR_CURRENT_DAILY" if not fallback_after else "PARTIAL_OR_BLOCKED",
        "remaining_limitation": "" if not fallback_after else "insufficient safe label coverage",
        "recommended_next_stage": next_stage,
        "research_only": "TRUE",
    }]
    summary = [{
        "final_status": final_status,
        "producer_decision": decision,
        "latest_available_current_daily_candidate_date": latest_date,
        "previous_repaired_label_latest_date": previous_latest,
        "produced_repaired_label_date": produced_date,
        "date_gap_days_before": before_gap,
        "date_gap_days_after": after_gap,
        "current_candidate_rows": len(current_rows),
        "produced_label_rows": len(labels),
        "distinct_ticker_count": len({r["ticker"] for r in labels}),
        "distinct_context_label_count": len({r["context_label"] for r in labels}),
        "fallback_required_before": "TRUE",
        "fallback_required_after": yn(fallback_after),
        "current_daily_observation_allowed_after": yn(not fallback_after),
        "official_use_allowed": "FALSE",
        "official_ranking_readiness_allowed": "FALSE",
        "official_weight_update_readiness_allowed": "FALSE",
        "official_weight_update_blocked": "TRUE",
        "broker_execution_supported": "FALSE",
        "shadow_activation": "FALSE",
        "research_only": "TRUE",
        "recommended_next_stage": next_stage,
        "selected_recommended_next_stage": "TRUE",
    }]

    write_csv(SUMMARY, summary, list(summary[0].keys()))
    write_csv(LABELS, labels or [{"as_of_date": latest_date, "ticker": "", "context_key": "NO_LABELS_PRODUCED", "context_label": "NO_LABELS_PRODUCED", "lane_id": "", "source_candidate_date": latest_date, "source_artifact": primary.relative_to(ROOT).as_posix(), "label_derivation_method": "NO_USABLE_FIELDS", "repaired_label_status": "BLOCKED_NO_FABRICATION", "research_only": "TRUE"}], ["as_of_date", "ticker", "context_key", "context_label", "lane_id", "source_candidate_date", "source_artifact", "label_derivation_method", "repaired_label_status", "research_only"])
    write_csv(FIELD_AUDIT, field_rows, ["source_artifact", "source_field", "field_exists", "non_null_count", "usable_for_label_derivation", "mapped_context_key", "mapping_rule", "limitation"])
    write_csv(FALLBACK_AUDIT, fallback_audit, list(fallback_audit[0].keys()))
    REPORT.write_text(f"""# V21.032 Current Repaired Label Daily Producer Report

## Why V21.032 Was Needed
V21.030 and V21.033 were mechanically valid but stuck on 2026-06-05 fallback labels while current daily candidate data reached 2026-06-16.

## Latest Dates
Latest available current daily candidate date: {latest_date}
Previous repaired label latest date: {previous_latest}
Produced repaired label date: {produced_date}

## Source Fields Used
The producer audited current candidate fields and used only deterministic, available fields plus local benchmark price caches. See V21_032_LABEL_SOURCE_FIELD_AUDIT.csv.

## Labels Produced
Produced label rows: {len(labels)}. Distinct labels: {len({r['context_label'] for r in labels}) if labels else 0}.

## Fallback Status
Gap before: {before_gap} days from 2026-06-05 to 2026-06-16. Fallback required after: {yn(fallback_after)}. Current daily observation allowed after: {yn(not fallback_after)}.

## Guardrails
Official use, ranking readiness, weight update readiness, broker execution, and shadow activation remain blocked. No official ranking, weight, recommendation, broker action, or shadow policy is mutated.

## Recommended Next Stage
{next_stage}
""", encoding="utf-8")
    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_status={final_status}")
    print(f"producer_decision={decision}")
    print(f"latest_available_current_daily_candidate_date={latest_date}")
    print(f"produced_repaired_label_date={produced_date}")
    print(f"recommended_next_stage={next_stage}")
    print("official_use_allowed=FALSE")
    print("official_ranking_readiness_allowed=FALSE")
    print("official_weight_update_readiness_allowed=FALSE")
    print("official_weight_update_blocked=TRUE")
    print("broker_execution_supported=FALSE")
    print("shadow_activation=FALSE")
    print("research_only=TRUE")


if __name__ == "__main__":
    main()
